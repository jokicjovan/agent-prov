"""Document Review pipeline — live variant (real OpenAI chat model).

Flow:  summarizer  →  HumanReview(edit)  →  finalizer  →  HumanReview(approve)

Same structure as ``demos/document_review/mock.py``, but the two agent
nodes call a real OpenAI chat model via langchain-openai so that middleware
overhead on a HITL-bearing pipeline is measured against realistic LLM
latency rather than a synchronous stub.

Requires:
    OPENAI_API_KEY  in the environment, or in a `.env` file at the repo root
                    (loaded via python-dotenv on import).
    OPENAI_MODEL    (optional, default "gpt-4o-mini")

Usage:
    uv run python demos/document_review/live.py
"""

from __future__ import annotations

import os
import pathlib
from typing import TypedDict

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph

from middleware.bundle_generator import BundleGenerator
from middleware.core import ProvenanceMiddleware
from middleware.hitl import HumanReview
from middleware.session import PipelineSession

load_dotenv()


PIPELINE_ID = "8f5e449c-dd8f-4a2d-91c6-db484350d39a"
DEFAULT_MODEL = "gpt-4o-mini"


DOCUMENT = (
    "Loan application #4821. Applicant: Mara Petrović, employed full-time at "
    "Adriatic Foods (5 years), monthly net income EUR 1,850. Requested amount: "
    "EUR 12,000 over 36 months for home renovation. Existing obligations: one "
    "credit card with EUR 400 balance, no other loans. Credit bureau report "
    "indicates a single late payment 18 months ago, otherwise clean history. "
    "Applicant declares two dependants."
)


# Scripted reviewer edit — adds the dependants line the summariser is likely
# to underweight or omit. Kept identical to the mock variant so bundles are
# directly comparable.
REVIEWER_EDIT = (
    "Applicant requests EUR 12,000 over 36 months for home renovation. "
    "Stable employment (5 years, EUR 1,850 net/month) and limited "
    "existing obligations (EUR 400 credit card). Credit history is "
    "clean apart from one late payment 18 months ago. Two dependants "
    "declared — factor into affordability assessment."
)


def _make_llm() -> ChatOpenAI:
    model = os.getenv("OPENAI_MODEL", DEFAULT_MODEL)
    return ChatOpenAI(model=model, temperature=0)


class ReviewState(TypedDict, total=False):
    document: str
    summary: str
    decision: str


def summarizer(state: ReviewState, config: RunnableConfig) -> ReviewState:
    prompt = (
        "You are a credit analyst. Summarise the following loan application "
        "in three to four sentences, covering income, requested amount, "
        "obligations, and credit history.\n\n"
        f"{state['document']}"
    )
    response = _make_llm().invoke([HumanMessage(content=prompt)], config=config)
    return {"summary": response.content}


def finalizer(state: ReviewState, config: RunnableConfig) -> ReviewState:
    prompt = (
        "Draft a one-paragraph credit decision letter from the reviewed "
        "summary below. State an approve/decline decision and a short "
        "rationale.\n\n"
        f"Reviewed summary:\n{state['summary']}"
    )
    response = _make_llm().invoke([HumanMessage(content=prompt)], config=config)
    return {"decision": response.content}


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


def run(output_dir: str | pathlib.Path = "demos/document_review") -> dict:
    """Run the live document review pipeline and write the sealed bundle."""
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Export it in your shell before running "
            "the live demo, or run demos/document_review/mock.py for a "
            "deterministic offline variant."
        )

    session = PipelineSession(pipeline_id=PIPELINE_ID)
    middleware = ProvenanceMiddleware(session)
    callbacks: RunnableConfig = {"callbacks": [middleware]}

    summary_state = _build_summarizer_graph().invoke(
        {"document": DOCUMENT}, config=callbacks
    )
    agent_summary = summary_state["summary"]

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

    final_state = _build_finalizer_graph().invoke(
        {"document": DOCUMENT, "summary": REVIEWER_EDIT},
        config=callbacks,
    )
    final_decision = final_state["decision"]

    with HumanReview(
        session=session,
        reviewer_id=["reviewer:compliance-07"],
        reviewer_role="compliance_officer",
        output_before=final_decision,
    ) as review:
        review.approve(justification="Decision aligns with internal credit policy.")

    output_path = pathlib.Path(output_dir) / "live_bundle.json"
    bundle = BundleGenerator(session, disclosure_presented=True).to_file(output_path)

    _print_summary(bundle, output_path)
    return bundle


def _print_summary(bundle: dict, path: pathlib.Path) -> None:
    records = bundle["records"]
    print(f"\n=== Document Review Pipeline (live): Bundle Summary ===")
    print(f"Bundle ID    : {bundle['bundle_id']}")
    print(f"Pipeline ID  : {bundle['pipeline_id']}")
    print(f"Session ID   : {bundle['session_id']}")
    print(f"Records      : {len(records)}")
    print(f"Bundle hash  : {bundle['bundle_hash']}")
    print(f"Output       : {path.resolve()}")
    print(f"\nRecord chain:")
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
