"""Tool-calling agent pipeline - mock variant.

Graph:  agent  <->  tools   (a single agent node that loops through a tool step)

Unlike the research demo, which invokes its tool imperatively from node code,
here the *model* decides to call tools: the agent's first response emits two
tool calls in one step, a tool node executes both, and a second agent call
synthesises the final answer from the two tool results.

This is the flow that exercises canonical identifier rewriting end to end:

* The first agent step's output carries two tool calls. Their runtime ids are
  rewritten to canonical labels "0" and "1" inside output_hash, and the real
  ids are preserved in runtime_metadata.tool_call_ids ({"0": ..., "1": ...}).
* The synthesis step's input carries the two ToolMessages answering those calls.
  Each ToolMessage's tool_call_id is rewritten to the same label as the call it
  answers, so the call<->result correlation lives inside input_hash - and would
  survive the results arriving in either order.

Note on the record chain: the two tool calls are dispatched in parallel from the
single first agent step, but parent_record_id links records in chronological
emission order (agent step -> web_search -> glossary -> synthesis), not by causal
branch. This is the protocol's documented chronological-not-causal chaining; the
tool_invocation records' order between web_search and glossary reflects when each
completed, not a dependency between them.

Deterministic; no external API calls. There is no live counterpart: the point of
the demo is a reproducible bundle a reader can recompute, and a fake model that
emits fixed tool calls is what makes the canonical labels and the id map stable
run to run.

Usage:
    uv run python demos/langchain/tool_calling/mock.py
"""

from __future__ import annotations

import pathlib

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.config import merge_configs
from langchain_core.tools import tool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from agent_prov.bundle_generator import BundleGenerator
from agent_prov.adapters.langchain import ProvenanceMiddleware
from agent_prov.session import PipelineSession


PIPELINE_ID = "a4c1f6e2-0b93-4d17-8a5e-2f7c9d61b430"

# Fixed tool-call ids the fake model emits. Real deployments get these from the
# provider; here they are pinned so the demo is reproducible. Canonical
# rewriting maps them to "0" and "1" in the hashes, and the runtime_metadata
# id map records this exact correspondence.
_CALL_SEARCH = "call_search_0001"
_CALL_GLOSSARY = "call_glossary_0002"


# ---------------------------------------------------------------------------
# Mock tools
# ---------------------------------------------------------------------------

@tool
def web_search(query: str) -> str:
    """Search the web for recent information on a topic."""
    return (
        f"Top results for '{query}': the EU AI Act (Regulation 2024/1689) sets "
        "record-keeping duties for high-risk AI systems in Article 12."
    )


@tool
def glossary(term: str) -> str:
    """Look up a short definition for a regulatory term."""
    return (
        f"{term}: automatic recording of events over a system's lifetime, "
        "sufficient for tracing and post-market monitoring."
    )


_TOOLS = [web_search, glossary]


# ---------------------------------------------------------------------------
# Fake tool-calling LLM
# ---------------------------------------------------------------------------

class _FakeToolCallingLLM(BaseChatModel):
    """Deterministic fake model that calls two tools, then synthesises.

    On its first turn (no tool results in the history yet) it emits two tool
    calls in a single message. Once both ToolMessages are present it returns the
    final answer instead.
    """

    @property
    def _llm_type(self) -> str:
        return "fake-tool-caller"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager=None,
        **kwargs,
    ) -> ChatResult:
        if any(isinstance(m, ToolMessage) for m in messages):
            message = AIMessage(
                content=(
                    "# Record-keeping under the EU AI Act\n\n"
                    "Article 12 requires high-risk AI systems to automatically record "
                    "events over their lifetime, supporting traceability and post-market "
                    "monitoring."
                )
            )
        else:
            message = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "web_search",
                        "args": {"query": "EU AI Act Article 12 record-keeping"},
                        "id": _CALL_SEARCH,
                        "type": "tool_call",
                    },
                    {
                        "name": "glossary",
                        "args": {"term": "record-keeping"},
                        "id": _CALL_GLOSSARY,
                        "type": "tool_call",
                    },
                ],
            )
        return ChatResult(generations=[ChatGeneration(message=message)])

    def bind_tools(self, tools, **kwargs):  # noqa: ANN001, ANN003
        # The fake model chooses its own tool calls, so binding is a no-op; it is
        # provided only so the node can call bind_tools like a real model.
        return self


_llm = _FakeToolCallingLLM().bind_tools(_TOOLS)


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

def agent(state: MessagesState, config: RunnableConfig) -> dict:
    llm_config = merge_configs(config, {"metadata": {"ls_model_name": "fake-tool-caller"}})
    response = _llm.invoke(state["messages"], config=llm_config)
    return {"messages": [response]}


def _route(state: MessagesState) -> str:
    """Go to the tool node while the last message carries tool calls, else stop."""
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None):
        return "tools"
    return END


def _build_graph():
    g = StateGraph(MessagesState)
    g.add_node("agent", agent)
    g.add_node("tools", ToolNode(_TOOLS))
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", _route, {"tools": "tools", END: END})
    g.add_edge("tools", "agent")
    return g.compile()


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run(
    question: str = "What does EU AI Act Article 12 require, and what is record-keeping?",
    output_dir: str | pathlib.Path = "demos/langchain/tool_calling",
) -> dict:
    """Run the tool-calling pipeline and write the sealed bundle to *output_dir*."""
    session = PipelineSession(pipeline_id=PIPELINE_ID)
    middleware = ProvenanceMiddleware(session)

    graph = _build_graph()
    graph.invoke(
        {"messages": [HumanMessage(content=question)]},
        config={"callbacks": [middleware]},
    )

    output_path = pathlib.Path(output_dir) / "mock_bundle.json"
    bundle = BundleGenerator(session, disclosure_presented=True).to_file(output_path)

    _print_summary(bundle, output_path)
    return bundle


def _print_summary(bundle: dict, path: pathlib.Path) -> None:
    records = bundle["records"]
    print("\n=== Tool-calling Pipeline (mock): Bundle Summary ===")
    print(f"Bundle ID    : {bundle['bundle_id']}")
    print(f"Pipeline ID  : {bundle['pipeline_id']}")
    print(f"Session ID   : {bundle['session_id']}")
    print(f"Records      : {len(records)}")
    print(f"Bundle hash  : {bundle['bundle_hash']}")
    print(f"Output       : {path.resolve()}")
    print("\nRecord chain:")
    for i, r in enumerate(records):
        rtype = r["record_type"]
        agent_id = r.get("agent_id", "-")
        if rtype == "tool_invocation":
            label = f"tool={r.get('tool_name', '-')}"
        else:
            label = f"model={r.get('model_id', '-')}"
        print(f"  [{i + 1:2d}] {rtype:22s}  agent={agent_id:10s}  {label}")
        id_map = (r.get("runtime_metadata") or {}).get("tool_call_ids")
        if id_map:
            print(f"        tool_call_ids (label -> real): {id_map}")


if __name__ == "__main__":
    run()
