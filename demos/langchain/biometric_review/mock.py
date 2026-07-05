"""Biometric Identity Verification pipeline - mock variant.

Flow:  matcher  ->  [interrupt: two-person verification]  ->  END

A biometric identification system proposes a candidate identity for a probe
image, and - because this is a biometric identification system in the sense of
EU AI Act Article 14(5) - the match may not be acted upon until it has been
*separately verified and confirmed by at least two natural persons*. Two forensic
examiners jointly verify the candidate at a single review gate, producing one
``human_intervention`` record that carries both reviewers in ``reviewer_id``.

The bundle is sealed with ``oversight_regime="biometric_dual_control"``, which
opts the run into the Article 14(5) two-person rule. The rule is enforced at seal
time: had the review carried only one reviewer, ``BundleGenerator.generate()``
would raise ``ProtocolValidationError`` and the bundle could not be produced at
all. This demo is the concrete artifact showing the field and its enforcement;
the negative case (single reviewer refused) is covered in the test suite.

The workflow is one multi-node LangGraph - ``matcher -> verify -> END`` - where
the review point is a gate node that calls LangGraph's ``interrupt()``. When the
gate is reached the graph pauses and returns control to the runner, which
collects the joint decision in a ``HumanReview`` block and resumes the graph.
A node-level interrupt requires a checkpointer, so the graph is compiled with an
in-memory ``MemorySaver``.

Deterministic; no external API calls. (Mock only - there is no live variant,
because the two-person verification is a scripted human decision, not a model
call.)

Usage:
    uv run python demos/langchain/biometric_review/mock.py
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


PIPELINE_ID = "c7a1f4e2-8b93-4d6a-b5e0-1f2a3c4d5e6f"


# ---------------------------------------------------------------------------
# Probe under identification
# ---------------------------------------------------------------------------

PROBE = (
    "Access-control probe #A-7731. A face image captured at the secure-facility "
    "entrance is queried 1:N against the enrolled gallery (4,120 identities). "
    "Adjudicate the top candidate returned by the matching engine and state "
    "whether it is fit to act upon."
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


_matcher_llm = _FakeLLM(
    role="matcher",
    response=(
        "Top candidate: enrolment E-0442 (Novak, D.), match score 0.89 against "
        "the 0.82 acceptance threshold. Second-best candidate scores 0.61, so the "
        "margin is clear. Recommendation: candidate E-0442 - route for two-person "
        "verification before any access decision is taken."
    ),
)


# ---------------------------------------------------------------------------
# Pipeline state
# ---------------------------------------------------------------------------

class MatchState(TypedDict, total=False):
    probe: str
    candidate: str


# ---------------------------------------------------------------------------
# Node functions
# ---------------------------------------------------------------------------

def matcher(state: MatchState, config: RunnableConfig) -> MatchState:
    llm_config = merge_configs(config, {"metadata": {"ls_model_name": "fake-matcher"}})
    response = _matcher_llm.invoke(
        [HumanMessage(content=f"Adjudicate this biometric identification:\n\n{state['probe']}")],
        config=llm_config,
    )
    return {"candidate": response.content}


def verify(state: MatchState) -> MatchState:
    """Review-gate node: pause for the two-person verification (Art. 14(5))."""
    interrupt({"stage": "verification", "value": state["candidate"]})
    return {}


# ---------------------------------------------------------------------------
# Graph - one multi-node pipeline with a two-person verification gate
# ---------------------------------------------------------------------------

def _build_graph():
    g = StateGraph(MatchState)
    g.add_node("matcher", matcher)
    g.add_node("verify", verify)
    g.set_entry_point("matcher")
    g.add_edge("matcher", "verify")
    g.add_edge("verify", END)
    return g.compile(checkpointer=MemorySaver())


def _interrupt_value(state: dict) -> str:
    """Pull the payload the paused gate handed back to the runner."""
    return state["__interrupt__"][0].value["value"]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run(output_dir: str | pathlib.Path = "demos/langchain/biometric_review") -> dict:
    """Run the biometric verification pipeline and write the sealed bundle."""
    session = PipelineSession(pipeline_id=PIPELINE_ID)
    middleware = ProvenanceMiddleware(session)
    graph = _build_graph()
    config: RunnableConfig = {
        "callbacks": [middleware],
        "configurable": {"thread_id": session.session_id},
    }

    # 1. Run until the gate - matcher emits its agent_step, then pauses.
    state = graph.invoke({"probe": PROBE}, config=config)
    candidate = _interrupt_value(state)

    # 2. Two-person verification - both examiners named on one record, so
    #    reviewer_id carries two entries and the Art. 14(5) rule is satisfied.
    with HumanReview(
        session=session,
        reviewer_id=["examiner:forensic-11", "examiner:forensic-23"],
        reviewer_role="forensic_examiner",
        output_before=candidate,
    ) as review:
        review.approve(
            justification="Both examiners independently confirmed candidate E-0442; margin clear.",
        )

    # 3. Resume - verify returns and the graph reaches END.
    graph.invoke(Command(resume=True), config=config)

    # Sealing under the biometric regime enforces the two-person rule: a bundle
    # whose Human Intervention Record carried fewer than two reviewers would be
    # refused here with a ProtocolValidationError.
    output_path = pathlib.Path(output_dir) / "mock_bundle.json"
    bundle = BundleGenerator(
        session,
        disclosure_presented=True,
        oversight_regime="biometric_dual_control",
    ).to_file(output_path)

    _print_summary(bundle, output_path)
    return bundle


def _print_summary(bundle: dict, path: pathlib.Path) -> None:
    records = bundle["records"]
    print("\n=== Biometric Verification Pipeline (mock): Bundle Summary ===")
    print(f"Bundle ID        : {bundle['bundle_id']}")
    print(f"Pipeline ID      : {bundle['pipeline_id']}")
    print(f"Session ID       : {bundle['session_id']}")
    print(f"Oversight regime : {bundle['oversight_regime']}")
    print(f"Records          : {len(records)}")
    print(f"Bundle hash      : {bundle['bundle_hash']}")
    print(f"Output           : {path.resolve()}")
    print("\nRecord chain:")
    for i, r in enumerate(records):
        rtype = r["record_type"]
        if rtype == "human_intervention":
            reviewers = ", ".join(r["reviewer_id"])
            label = f"action={r['action_type']:9s} reviewers=[{reviewers}]"
        else:
            label = f"agent={r.get('agent_id', '-')} model={r.get('model_id', '-')}"
        parent_id = r.get("parent_record_id")
        print(f"  [{i + 1:2d}] {rtype:20s}  {label}")
        if parent_id:
            print(f"        ^ parent: {parent_id}")


if __name__ == "__main__":
    run()
