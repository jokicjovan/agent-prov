"""End-to-end middleware integration test.

Builds a minimal LangGraph pipeline in-process — agent (with tool call) →
human review (edit) → finaliser agent — exercises it through
``ProvenanceMiddleware`` + ``PipelineSession`` + ``HumanReview`` +
``BundleGenerator``, and validates the resulting bundle against the
Pipeline Bundle schema and the chronological parent-chain contract.

Why a fresh in-test pipeline rather than importing the demos: the demos
exist for narrative/evaluation reasons (specific document, scripted
reviewer wording) and can evolve. The integration test owns its own
fixture so it stays stable as long as the middleware contract holds.

What this exercises that the unit tests do not:

* LangGraph callback wiring (``on_chain_start/end``, ``on_chat_model_start``,
  ``on_llm_end``, ``on_tool_start/end``) under a real ``StateGraph.invoke``.
* Composition of two emitters (``AgentStepEmitter``,
  ``ToolInvocationEmitter``) with ``HumanReview`` between graph segments.
* ``parent_record_id`` chaining across the human/agent boundary —
  the finaliser agent must point at the HITL record, not the previous
  agent step.
* ``BundleGenerator.to_file`` + canonical hashing on a real session.
"""

from __future__ import annotations

import pathlib
from typing import TypedDict
from uuid import uuid4

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.config import merge_configs
from langchain_core.tools import tool
from langgraph.graph import END, StateGraph

from _helpers import PIPELINE_BUNDLE_SCHEMA, validator
from middleware.bundle_generator import BundleGenerator
from middleware.core import ProvenanceMiddleware
from middleware.hitl import HumanReview
from middleware.validation import validate_record
from middleware.session import PipelineSession


# ---------------------------------------------------------------------------
# Minimal pipeline scaffolding (owned by this test)
# ---------------------------------------------------------------------------


class _FakeLLM(BaseChatModel):
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


@tool
def _lookup(key: str) -> str:
    """Stand-in tool the analyst node calls before responding."""
    return f"value-for-{key}"


class _State(TypedDict, total=False):
    query: str
    notes: str
    final: str


_ANALYST_LLM = _FakeLLM(role="analyst", response="Notes synthesised from lookup result.")
_FINALISER_LLM = _FakeLLM(role="finaliser", response="Final answer based on reviewed notes.")


def _analyst(state: _State, config: RunnableConfig) -> _State:
    lookup_result = _lookup.invoke({"key": state["query"]}, config=config)
    llm_config = merge_configs(config, {"metadata": {"ls_model_name": "fake-analyst"}})
    response = _ANALYST_LLM.invoke(
        [HumanMessage(content=f"Query: {state['query']}\nLookup: {lookup_result}")],
        config=llm_config,
    )
    return {"notes": response.content}


def _finaliser(state: _State, config: RunnableConfig) -> _State:
    llm_config = merge_configs(config, {"metadata": {"ls_model_name": "fake-finaliser"}})
    response = _FINALISER_LLM.invoke(
        [HumanMessage(content=f"Reviewed notes:\n{state['notes']}")],
        config=llm_config,
    )
    return {"final": response.content}


def _build(node):
    g = StateGraph(_State)
    g.add_node(node.__name__, node)
    g.set_entry_point(node.__name__)
    g.add_edge(node.__name__, END)
    return g.compile()


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


def test_full_pipeline_with_hitl_produces_valid_bundle(tmp_path: pathlib.Path) -> None:
    session = PipelineSession(pipeline_id=str(uuid4()))
    callbacks: RunnableConfig = {"callbacks": [ProvenanceMiddleware(session)]}

    analyst_state = _build(_analyst).invoke({"query": "alpha"}, config=callbacks)
    analyst_notes = analyst_state["notes"]

    reviewed_notes = analyst_notes + "\n(reviewer addendum)"
    with HumanReview(
        session=session,
        reviewer_id=["reviewer:test-01"],
        reviewer_role="editor",
        output_before=analyst_notes,
    ) as review:
        review.edit(reviewed_notes, justification="appended reviewer note")

    _build(_finaliser).invoke({"notes": reviewed_notes}, config=callbacks)

    bundle = BundleGenerator(session, disclosure_presented=True).to_file(
        tmp_path / "bundle.json"
    )

    # 1. Schema
    errors = sorted(
        validator(PIPELINE_BUNDLE_SCHEMA).iter_errors(bundle),
        key=lambda e: list(e.path),
    )
    assert not errors, "schema errors:\n" + "\n".join(
        f"  - {list(e.path)}: {e.message}" for e in errors
    )

    records = bundle["records"]

    # 2. Expected record types (order: tool then agent for analyst,
    #    then HITL, then finaliser agent)
    types = [r["record_type"] for r in records]
    assert types == [
        "tool_invocation",
        "agent_step",
        "human_intervention",
        "agent_step",
    ], f"unexpected record sequence: {types}"

    # 3. Chronological parent chain — head has no parent; every subsequent
    #    record points at the immediately preceding record_id. The third
    #    record's parent must be the HITL, crossing the human boundary.
    assert records[0].get("parent_record_id") is None
    for i in range(1, len(records)):
        assert records[i]["parent_record_id"] == records[i - 1]["record_id"], (
            f"record[{i}] ({records[i]['record_type']}) parent does not "
            f"match preceding record_id"
        )
    assert records[3]["parent_record_id"] == records[2]["record_id"], (
        "finaliser agent_step must point at the HITL record"
    )

    # 4. HITL action ↔ output_after_hash conventions
    validate_record(records[2])
    assert records[2]["action_type"] == "edited"
    assert records[2]["output_before_hash"] != records[2]["output_after_hash"]
