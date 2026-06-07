"""Document Review pipeline — mock variant.

Flow:  summarizer  →  HumanReview(edit)  →  finalizer  →  HumanReview(approve)

A document is summarised by an agent, a human reviewer edits the summary to
correct an omission, a second agent drafts a decision letter from the edited
summary, and a compliance reviewer approves the final letter. The resulting
bundle contains two agent_step records interleaved with two
human_intervention records, demonstrating the parent_record_id chain
crossing automated and human nodes.

The two graph nodes are compiled as separate single-node graphs and invoked
in sequence on the same PipelineSession/ProvenanceMiddleware pair. This is
the simplest way to surface a HITL emission between two LangGraph node runs
without resorting to graph-level interrupts.

Deterministic; no external API calls. For a real-API counterpart see
``demos/document_review/live.py``.

Usage:
    uv run python demos/document_review/mock.py
"""

from __future__ import annotations

import pathlib
from typing import TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.config import merge_configs
from langgraph.graph import END, StateGraph

from agent_prov.bundle_generator import BundleGenerator
from agent_prov.core import ProvenanceMiddleware
from agent_prov.hitl import HumanReview
from agent_prov.session import PipelineSession


PIPELINE_ID = "951e06e5-f3b3-443f-ba1e-45e9416e1be3"


# ---------------------------------------------------------------------------
# Sample document
# ---------------------------------------------------------------------------

DOCUMENT = (
    "Loan application #4821. Applicant: Mara Petrović, employed full-time at "
    "Adriatic Foods (5 years), monthly net income EUR 1,850. Requested amount: "
    "EUR 12,000 over 36 months for home renovation. Existing obligations: one "
    "credit card with EUR 400 balance, no other loans. Credit bureau report "
    "indicates a single late payment 18 months ago, otherwise clean history. "
    "Applicant declares two dependants."
)


# ---------------------------------------------------------------------------
# Fake LLM
# ---------------------------------------------------------------------------

class _FakeLLM(BaseChatModel):
    """Deterministic fake LLM that returns a fixed response."""

    response: str
    role: str = "agent"

    @property
    def _llm_type(self) -> str:
        return f"fake-{self.role}"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager=None,
        **kwargs,
    ) -> ChatResult:
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=self.response))]
        )


_summarizer_llm = _FakeLLM(
    role="summarizer",
    response=(
        "Applicant requests EUR 12,000 over 36 months for home renovation. "
        "Stable employment (5 years, EUR 1,850 net/month) and limited "
        "existing obligations (EUR 400 credit card). Credit history is "
        "clean apart from one late payment."
    ),
)

_finalizer_llm = _FakeLLM(
    role="finalizer",
    response=(
        "Decision: APPROVE subject to standard collateral check. Rationale: "
        "stable long-term employment, low debt-to-income ratio, and a "
        "substantially clean credit history outweigh the single late "
        "payment recorded 18 months ago. Two dependants noted in the "
        "affordability assessment."
    ),
)


# ---------------------------------------------------------------------------
# Pipeline state
# ---------------------------------------------------------------------------

class ReviewState(TypedDict, total=False):
    document: str
    summary: str
    decision: str


# ---------------------------------------------------------------------------
# Node functions
# ---------------------------------------------------------------------------

def summarizer(state: ReviewState, config: RunnableConfig) -> ReviewState:
    llm_config = merge_configs(config, {"metadata": {"ls_model_name": "fake-summarizer"}})
    response = _summarizer_llm.invoke(
        [HumanMessage(content=f"Summarise this loan application:\n\n{state['document']}")],
        config=llm_config,
    )
    return {"summary": response.content}


def finalizer(state: ReviewState, config: RunnableConfig) -> ReviewState:
    llm_config = merge_configs(config, {"metadata": {"ls_model_name": "fake-finalizer"}})
    response = _finalizer_llm.invoke(
        [HumanMessage(
            content=(
                "Draft a one-paragraph credit decision letter from this "
                f"reviewed summary:\n\n{state['summary']}"
            )
        )],
        config=llm_config,
    )
    return {"decision": response.content}


# ---------------------------------------------------------------------------
# Graphs (one node each so the HITL block can sit between them)
# ---------------------------------------------------------------------------

def _build_summarizer_graph():
    g = StateGraph(ReviewState)
    g.add_node("summarizer", summarizer)
    g.set_entry_point("summarizer")
    g.add_edge("summarizer", END)
    return g.compile()


def _build_finalizer_graph():
    g = StateGraph(ReviewState)
    g.add_node("finalizer", finalizer)
    g.set_entry_point("finalizer")
    g.add_edge("finalizer", END)
    return g.compile()


# ---------------------------------------------------------------------------
# Scripted reviewer edit
# ---------------------------------------------------------------------------

# Reviewer notices the agent summary omitted the dependants and adds them.
REVIEWER_EDIT = (
    "Applicant requests EUR 12,000 over 36 months for home renovation. "
    "Stable employment (5 years, EUR 1,850 net/month) and limited "
    "existing obligations (EUR 400 credit card). Credit history is "
    "clean apart from one late payment 18 months ago. Two dependants "
    "declared — factor into affordability assessment."
)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run(output_dir: str | pathlib.Path = "demos/document_review") -> dict:
    """Run the document review pipeline and write the sealed bundle."""
    session = PipelineSession(pipeline_id=PIPELINE_ID)
    middleware = ProvenanceMiddleware(session)
    callbacks: RunnableConfig = {"callbacks": [middleware]}

    # 1. Summariser node
    summary_state = _build_summarizer_graph().invoke(
        {"document": DOCUMENT}, config=callbacks
    )
    agent_summary = summary_state["summary"]

    # 2. Human review — editor edits the summary
    with HumanReview(
        session=session,
        reviewer_id=["reviewer:editor-01"],
        reviewer_role="editor",
        output_before=agent_summary,
    ) as review:
        review.edit(
            REVIEWER_EDIT,
            justification="Summary omitted declared dependants; added for affordability.",
        )

    # 3. Finaliser node — runs on the reviewer-approved summary
    final_state = _build_finalizer_graph().invoke(
        {"document": DOCUMENT, "summary": REVIEWER_EDIT},
        config=callbacks,
    )
    final_decision = final_state["decision"]

    # 4. Human review — compliance officer approves the letter
    with HumanReview(
        session=session,
        reviewer_id=["reviewer:compliance-07"],
        reviewer_role="compliance_officer",
        output_before=final_decision,
    ) as review:
        review.approve(justification="Decision aligns with internal credit policy.")

    output_path = pathlib.Path(output_dir) / "mock_bundle.json"
    bundle = BundleGenerator(session, disclosure_presented=True).to_file(output_path)

    _print_summary(bundle, output_path)
    return bundle


def _print_summary(bundle: dict, path: pathlib.Path) -> None:
    records = bundle["records"]
    print("\n=== Document Review Pipeline (mock): Bundle Summary ===")
    print(f"Bundle ID    : {bundle['bundle_id']}")
    print(f"Pipeline ID  : {bundle['pipeline_id']}")
    print(f"Session ID   : {bundle['session_id']}")
    print(f"Records      : {len(records)}")
    print(f"Bundle hash  : {bundle['bundle_hash']}")
    print(f"Output       : {path.resolve()}")
    print("\nRecord chain:")
    for i, r in enumerate(records):
        rtype = r["record_type"]
        if rtype == "human_intervention":
            label = f"action={r['action_type']:9s} reviewer={r['reviewer_role']}"
        elif rtype == "tool_invocation":
            label = f"tool={r.get('tool_name', '-')}"
        else:
            label = f"agent={r.get('agent_id', '-')} model={r.get('model_id', '-')}"
        parent_id = r.get("parent_record_id")
        print(f"  [{i + 1:2d}] {rtype:20s}  {label}")
        if parent_id:
            print(f"        ^ parent: {parent_id}")


if __name__ == "__main__":
    run()
