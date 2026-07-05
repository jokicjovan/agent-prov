"""Framework-free agent loop - mock variant.

Loop:  researcher (model -> web_search -> model)  ->  writer (model)

This demo has no orchestration framework: no LangChain, no LangGraph, no
callbacks. It is a plain Python ``while`` loop calling a chat-completions-style
client by hand and dispatching tool calls itself -- the shape a great many
production agents actually take.

Because there is no framework lifecycle to hook, provenance is captured by
*inline instrumentation*: at each model call and each tool call the loop calls
``PipelineSession``'s record factory directly (``add_agent_step`` /
``add_tool_invocation``). The factory owns record assembly, canonical hashing,
and the parent-record chain exactly as it does for the LangChain adapter, so the
sealed bundle is byte-for-byte the same shape and validates identically -- yet
this module imports no agent framework and runs on the bare ``agent-prov`` core
(no ``[langchain]`` extra).

The client here is a deterministic offline stand-in that mimics the OpenAI
Python SDK's response objects (``resp.choices[0].message.content`` /
``.tool_calls[i].function.name`` / ``.arguments``). Swapping in the real client
is a one-line change (``from openai import OpenAI; client = OpenAI()``); the
instrumentation around it does not change.

Usage:
    uv run python demos/openai_loop/mock.py
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field
from typing import Any

from agent_prov.bundle_generator import BundleGenerator
from agent_prov.session import PipelineSession, now_iso8601


PIPELINE_ID = "c7a2e9d4-3b16-4f8a-9e20-1d5c8b7f2a44"
MODEL = "mock-gpt-4o-mini"


# ---------------------------------------------------------------------------
# Fake OpenAI-shaped client (deterministic, offline)
#
# These dataclasses mirror the shape of the objects the real OpenAI Python SDK
# returns from ``client.chat.completions.create(...)``, so the agent loop and
# its instrumentation read exactly as they would against the live SDK.
# ---------------------------------------------------------------------------

@dataclass
class _Function:
    name: str
    arguments: str  # JSON string, as the real SDK returns


@dataclass
class _ToolCall:
    id: str
    function: _Function
    type: str = "function"


@dataclass
class _Message:
    role: str
    content: str | None = None
    tool_calls: list[_ToolCall] = field(default_factory=list)


@dataclass
class _Choice:
    message: _Message


@dataclass
class _Completion:
    id: str
    choices: list[_Choice]


class _FakeChatClient:
    """Deterministic stand-in for ``OpenAI().chat.completions``.

    Decides its reply from the conversation state, not a turn counter, so the
    loop drives it the same way it would drive the real client:
      - tools offered and no tool result yet  -> ask to call web_search
      - a tool result is present              -> return the research notes
      - no tools offered                      -> return the final report
    """

    def create(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> _Completion:
        has_tool_result = any(m.get("role") == "tool" for m in messages)
        if tools and not has_tool_result:
            topic = messages[-1]["content"]
            call = _ToolCall(
                id="call_0",
                function=_Function(
                    name="web_search",
                    arguments=json.dumps({"query": topic}),
                ),
            )
            return _Completion(
                id="cmpl_researcher_1",
                choices=[_Choice(_Message(role="assistant", content="", tool_calls=[call]))],
            )
        if has_tool_result:
            return _Completion(
                id="cmpl_researcher_2",
                choices=[_Choice(_Message(
                    role="assistant",
                    content=(
                        "Key findings: LLM-powered agents use tool calls and memory "
                        "for multi-step reasoning. Multi-agent pipelines distribute "
                        "work across specialised roles, improving quality and "
                        "auditability."
                    ),
                ))],
            )
        return _Completion(
            id="cmpl_writer_1",
            choices=[_Choice(_Message(
                role="assistant",
                content=(
                    "# AI Agents in Multi-Agent Systems\n\n"
                    "Modern AI agents use large language models as reasoning engines, "
                    "augmented with tool use and memory. Specialised agents "
                    "collaborate -- each handling research or synthesis -- enabling "
                    "scalable and auditable AI pipelines."
                ),
            ))],
        )


# ---------------------------------------------------------------------------
# Tool (a plain function - no framework wrapper)
# ---------------------------------------------------------------------------

def web_search(query: str) -> str:
    """Search the web for recent information on a topic."""
    return (
        f"Top results for '{query}': "
        "(1) AI agents are autonomous systems driven by LLMs. "
        "(2) Multi-agent frameworks enable task decomposition across specialised roles. "
        "(3) Provenance tracking is required under EU AI Act Art. 12 for high-risk systems."
    )


TOOLS = [{
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the web for recent information on a topic.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
}]
_TOOL_FNS = {"web_search": web_search}


# ---------------------------------------------------------------------------
# Semantic projection (the OpenAI analog of the LangChain adapter's projection)
#
# A model response carries a runtime ``id`` (and each tool call its own ``id``)
# that re-randomises every run; hashing it would make identical content digest
# differently each time. The projection keeps only the semantic payload (role,
# content, and each tool call's name/args) so input_hash / output_hash are
# replay-stable, exactly as in the LangChain adapter (§4.5.1).
# ---------------------------------------------------------------------------

def _project(message: _Message | dict[str, Any]) -> dict[str, Any]:
    """Reduce a chat message (SDK object or plain dict) to its run-stable form."""
    role = _get(message, "role")
    content = _get(message, "content")
    tool_calls = _get(message, "tool_calls") or []
    projected_calls = []
    for tc in tool_calls:
        fn = _get(tc, "function")
        projected_calls.append({
            "name": _get(fn, "name"),
            "args": _parse_args(_get(fn, "arguments")),
        })
    return {"role": role, "content": content, "tool_calls": projected_calls}


def _project_all(messages: list[Any]) -> list[dict[str, Any]]:
    return [_project(m) for m in messages]


def _parse_args(arguments: Any) -> Any:
    if isinstance(arguments, str):
        try:
            return json.loads(arguments)
        except json.JSONDecodeError:
            return arguments
    return arguments


def _get(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


# ---------------------------------------------------------------------------
# The agent loop - instrumented inline by calling the record factory directly
# ---------------------------------------------------------------------------

def _run_agent(
    client: _FakeChatClient,
    session: PipelineSession,
    *,
    agent_id: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
) -> str:
    """Run one agent to completion, recording every model and tool call.

    Returns the agent's final text answer. The two ``session.add_*`` calls are
    the entire provenance integration: no callbacks, no middleware object.
    """
    while True:
        # --- model call -----------------------------------------------------
        ts = now_iso8601()  # the factory stamps timestamp_end itself
        completion = client.create(model=MODEL, messages=messages, tools=tools)
        message = completion.choices[0].message

        session.add_agent_step(
            agent_id=agent_id,
            model_id=MODEL,
            model_version=MODEL,
            timestamp_start=ts,
            input=_project_all(messages),
            output=_project(message),
        )
        messages.append(_message_to_dict(message))

        if not message.tool_calls:
            return message.content or ""

        # --- tool calls -----------------------------------------------------
        for call in message.tool_calls:
            args = _parse_args(call.function.arguments)
            ts = now_iso8601()
            result = _TOOL_FNS[call.function.name](**args)

            session.add_tool_invocation(
                agent_id=agent_id,
                tool_name=call.function.name,
                tool_version="1.0.0",
                timestamp_start=ts,
                input=args,
                output=result,
            )
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": result,
            })


def _message_to_dict(message: _Message) -> dict[str, Any]:
    """Append-shape of an assistant message for the running transcript."""
    out: dict[str, Any] = {"role": message.role, "content": message.content}
    if message.tool_calls:
        out["tool_calls"] = [
            {
                "id": tc.id,
                "type": tc.type,
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in message.tool_calls
        ]
    return out


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run(
    topic: str = "AI agents in multi-agent systems",
    output_dir: str | pathlib.Path = "demos/openai_loop",
) -> dict:
    """Run the framework-free pipeline and write the sealed bundle to *output_dir*."""
    client = _FakeChatClient()
    session = PipelineSession(pipeline_id=PIPELINE_ID)

    notes = _run_agent(
        client, session,
        agent_id="researcher",
        messages=[{"role": "user", "content": topic}],
        tools=TOOLS,
    )
    _run_agent(
        client, session,
        agent_id="writer",
        messages=[{"role": "user", "content": f"Write a short report from these notes:\n\n{notes}"}],
        tools=None,
    )

    output_path = pathlib.Path(output_dir) / "mock_bundle.json"
    bundle = BundleGenerator(session, disclosure_presented=True).to_file(output_path)

    _print_summary(bundle, output_path)
    return bundle


def _print_summary(bundle: dict, path: pathlib.Path) -> None:
    records = bundle["records"]
    print("\n=== Framework-free Loop (mock): Bundle Summary ===")
    print(f"Bundle ID    : {bundle['bundle_id']}")
    print(f"Pipeline ID  : {bundle['pipeline_id']}")
    print(f"Session ID   : {bundle['session_id']}")
    print(f"Records      : {len(records)}")
    print(f"Bundle hash  : {bundle['bundle_hash']}")
    print(f"Output       : {path.resolve()}")
    print("\nRecord chain:")
    for i, r in enumerate(records):
        rtype = r["record_type"]
        agent = r.get("agent_id", "-")
        if rtype == "tool_invocation":
            label = f"tool={r.get('tool_name', '-')}"
        else:
            label = f"model={r.get('model_id', '-')}"
        parent_id = r.get("parent_record_id")
        print(f"  [{i + 1:2d}] {rtype:22s}  agent={agent:12s}  {label}")
        if parent_id:
            print(f"        ^ parent: {parent_id}")


if __name__ == "__main__":
    run()
