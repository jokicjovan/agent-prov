"""Document Review pipeline - mock variant.

Flow:  summarizer  ->  [interrupt: edit]  ->  finalizer  ->  [interrupt: approve]

A document is summarised by an agent, a human reviewer edits the summary to
correct an omission, a second agent drafts a decision letter from the edited
summary, and a compliance reviewer approves the final letter. The resulting
bundle contains two ``agent_step`` records interleaved with two
``human_intervention`` records, demonstrating the ``parent_record_id`` chain
crossing automated and human nodes.

The workflow is one multi-node LangGraph - ``summarizer -> review_summary ->
finalizer -> approve_letter -> END`` - where the two review points are gate nodes
that call LangGraph's ``interrupt()``. When a gate is reached the graph pauses
and returns control to the runner, which collects the human decision in a
``HumanReview`` block and resumes the graph with ``Command(resume=...)``. Because
every invocation shares one ``PipelineSession`` and ``ProvenanceMiddleware``,
``session.last_record_id`` persists across the pause and each Human Intervention
Record chains onto the agent step it reviewed. A node-level interrupt requires a
checkpointer, so the graph is compiled with an in-memory ``MemorySaver``.

Deterministic; no external API calls. For a real-API counterpart see
``demos/langchain/document_review/live.py``.

Usage:
    uv run python demos/langchain/document_review/mock.py
"""

from __future__ import annotations

import pathlib
from typing import TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.config import merge_configs
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt

from agent_prov.bundle_generator import BundleGenerator
from agent_prov.adapters.langchain import ProvenanceMiddleware
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
# Scripted reviewer edit
# ---------------------------------------------------------------------------

# Reviewer notices the agent summary omitted the dependants and adds them.
REVIEWER_EDIT = (
    "Applicant requests EUR 12,000 over 36 months for home renovation. "
    "Stable employment (5 years, EUR 1,850 net/month) and limited "
    "existing obligations (EUR 400 credit card). Credit history is "
    "clean apart from one late payment 18 months ago. Two dependants "
    "declared - factor into affordability assessment."
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


def review_summary(state: ReviewState) -> ReviewState:
    """Review-gate node: pause for the editor and adopt the returned summary."""
    revised = interrupt({"stage": "summary", "value": state["summary"]})
    return {"summary": revised}


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


def approve_letter(state: ReviewState) -> ReviewState:
    """Review-gate node: pause for the compliance officer's sign-off."""
    interrupt({"stage": "decision", "value": state["decision"]})
    return {}


# ---------------------------------------------------------------------------
# Graph - one multi-node pipeline with two interrupt gates
# ---------------------------------------------------------------------------

def _build_graph():
    g = StateGraph(ReviewState)
    g.add_node("summarizer", summarizer)
    g.add_node("review_summary", review_summary)
    g.add_node("finalizer", finalizer)
    g.add_node("approve_letter", approve_letter)
    g.set_entry_point("summarizer")
    g.add_edge("summarizer", "review_summary")
    g.add_edge("review_summary", "finalizer")
    g.add_edge("finalizer", "approve_letter")
    g.add_edge("approve_letter", END)
    return g.compile(checkpointer=MemorySaver())


def _interrupt_value(state: dict) -> str:
    """Pull the payload the paused gate handed back to the runner."""
    return state["__interrupt__"][0].value["value"]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run(output_dir: str | pathlib.Path = "demos/langchain/document_review") -> dict:
    """Run the document review pipeline and write the sealed bundle."""
    session = PipelineSession(pipeline_id=PIPELINE_ID)
    middleware = ProvenanceMiddleware(session)
    graph = _build_graph()
    config: RunnableConfig = {
        "callbacks": [middleware],
        "configurable": {"thread_id": session.session_id},
    }

    # 1. Run until the first gate - summarizer emits its agent_step, then pauses.
    state = graph.invoke({"document": DOCUMENT}, config=config)
    agent_summary = _interrupt_value(state)

    # 2. Human review - editor edits the summary (chains onto the summarizer step).
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

    # 3. Resume with the edited summary - finalizer runs, then pauses at the second gate.
    state = graph.invoke(Command(resume=REVIEWER_EDIT), config=config)
    final_decision = _interrupt_value(state)

    # 4. Human review - compliance officer approves the letter unchanged.
    with HumanReview(
        session=session,
        reviewer_id=["reviewer:compliance-07"],
        reviewer_role="compliance_officer",
        output_before=final_decision,
    ) as review:
        review.approve(justification="Decision aligns with internal credit policy.")

    # 5. Final resume - approve_letter returns and the graph reaches END.
    graph.invoke(Command(resume=True), config=config)

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
