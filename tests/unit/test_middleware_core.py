"""Smoke tests for ProvenanceMiddleware lifecycle wiring.

The real emitters (step_emitter, tool_emitter) are not yet implemented;
these tests exercise only the open/close bookkeeping and the hand-off
hook (`_on_step_complete`, `_on_tool_complete`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from agent_prov._frames import _StepFrame, _ToolFrame
from agent_prov.core import ProvenanceMiddleware


@dataclass
class FakeSession:
    pipeline_id: str = "00000000-0000-0000-0000-000000000001"
    session_id: str = "00000000-0000-0000-0000-000000000002"
    protocol_version: str = "0.1.0"
    records: list[dict[str, Any]] = field(default_factory=list)

    def add_record(self, record: dict[str, Any]) -> None:
        self.records.append(record)


class RecordingMiddleware(ProvenanceMiddleware):
    """Subclass that captures hand-offs for assertion."""

    def __init__(self, session: FakeSession) -> None:
        super().__init__(session)
        self.completed_steps: list[tuple[_StepFrame, Any]] = []
        self.completed_tools: list[tuple[_ToolFrame, Any]] = []

    def _on_step_complete(self, frame: _StepFrame, response: Any) -> None:
        self.completed_steps.append((frame, response))

    def _on_tool_complete(self, frame: _ToolFrame, output: Any) -> None:
        self.completed_tools.append((frame, output))


def _uuid() -> UUID:
    return uuid4()


def test_chat_model_start_then_llm_end_completes_step_and_clears_state():
    mw = RecordingMiddleware(FakeSession())
    run_id = _uuid()

    mw.on_chat_model_start(
        serialized={"name": "ChatOpenAI"},
        messages=[[{"type": "human", "content": "hello"}]],
        run_id=run_id,
        parent_run_id=None,
        metadata={"ls_model_name": "gpt-4o"},
    )

    assert mw.in_flight == {"nodes": 0, "steps": 1, "tools": 0}

    mw.on_llm_end(response={"generations": [[{"text": "hi"}]]}, run_id=run_id)

    assert mw.in_flight == {"nodes": 0, "steps": 0, "tools": 0}
    assert len(mw.completed_steps) == 1
    frame, response = mw.completed_steps[0]
    assert frame.run_id == run_id
    assert frame.serialized == {"name": "ChatOpenAI"}
    assert frame.metadata == {"ls_model_name": "gpt-4o"}
    assert response == {"generations": [[{"text": "hi"}]]}


def test_tool_start_then_tool_end_completes_tool_and_clears_state():
    mw = RecordingMiddleware(FakeSession())
    run_id = _uuid()
    parent_run_id = _uuid()

    mw.on_tool_start(
        serialized={"name": "web_search"},
        input_str='{"q": "AI Act"}',
        run_id=run_id,
        parent_run_id=parent_run_id,
    )

    assert mw.in_flight == {"nodes": 0, "steps": 0, "tools": 1}

    mw.on_tool_end(output="result", run_id=run_id)

    assert mw.in_flight == {"nodes": 0, "steps": 0, "tools": 0}
    assert len(mw.completed_tools) == 1
    frame, output = mw.completed_tools[0]
    assert frame.run_id == run_id
    assert frame.parent_run_id == parent_run_id
    assert frame.input_str == '{"q": "AI Act"}'
    assert output == "result"


def test_unmatched_end_event_is_ignored_without_error():
    mw = RecordingMiddleware(FakeSession())
    mw.on_llm_end(response={}, run_id=_uuid())
    mw.on_tool_end(output=None, run_id=_uuid())
    assert mw.in_flight == {"nodes": 0, "steps": 0, "tools": 0}
    assert mw.completed_steps == []
    assert mw.completed_tools == []


def test_chain_start_end_open_and_close_a_node_frame():
    mw = RecordingMiddleware(FakeSession())
    run_id = _uuid()

    mw.on_chain_start(
        serialized={"name": "researcher"},
        inputs={"topic": "AI Act"},
        run_id=run_id,
    )
    assert mw.in_flight == {"nodes": 1, "steps": 0, "tools": 0}
    assert mw._nodes[run_id].node_name == "researcher"
    assert mw._nodes[run_id].inputs == {"topic": "AI Act"}

    mw.on_chain_end(outputs={"draft": "..."}, run_id=run_id)
    assert mw.in_flight == {"nodes": 0, "steps": 0, "tools": 0}


def test_concurrent_runs_are_tracked_independently_by_run_id():
    mw = RecordingMiddleware(FakeSession())
    a, b = _uuid(), _uuid()

    mw.on_chat_model_start(serialized={}, messages=[], run_id=a)
    mw.on_chat_model_start(serialized={}, messages=[], run_id=b)
    assert mw.in_flight["steps"] == 2

    mw.on_llm_end(response="A done", run_id=a)
    assert mw.in_flight["steps"] == 1
    assert {f.run_id for f, _ in mw.completed_steps} == {a}

    mw.on_llm_end(response="B done", run_id=b)
    assert mw.in_flight["steps"] == 0
    assert {f.run_id for f, _ in mw.completed_steps} == {a, b}
