"""Research Assistant pipeline — mock variant.

Graph:  researcher  →  summarizer  →  writer

The researcher node calls a mock web_search tool before synthesising with a
fake LLM, so the resulting bundle contains both agent_step and
tool_invocation records. Deterministic; no external API calls.

For a real-API counterpart see ``demos/research/live.py``.

Usage:
    uv run python demos/research/mock.py
"""

from __future__ import annotations

import pathlib
from typing import TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.config import merge_configs
from langchain_core.tools import tool
from langgraph.graph import END, StateGraph

from agent_prov.bundle_generator import BundleGenerator
from agent_prov.adapters.langchain import ProvenanceMiddleware
from agent_prov.session import PipelineSession


PIPELINE_ID = "8d3fecf8-42d6-4f45-824f-7dde23407026"


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


# ---------------------------------------------------------------------------
# LLM instances (one per agent role)
# ---------------------------------------------------------------------------

_researcher_llm = _FakeLLM(
    role="researcher",
    response=(
        "Key findings: LLM-powered agents use tool calls and memory for "
        "multi-step reasoning. Multi-agent pipelines distribute work across "
        "specialised nodes — researcher, summariser, writer — improving "
        "quality and auditability."
    ),
)

_summarizer_llm = _FakeLLM(
    role="summarizer",
    response=(
        "LLM agents reason autonomously using tool calls and memory. "
        "Multi-agent pipelines improve quality through task specialisation."
    ),
)

_writer_llm = _FakeLLM(
    role="writer",
    response=(
        "# AI Agents in Multi-Agent Systems\n\n"
        "Modern AI agents use large language models as reasoning engines, "
        "augmented with tool use and memory. In multi-agent architectures, "
        "specialised agents collaborate — each handling research, summarisation, "
        "or synthesis — enabling scalable and auditable AI pipelines."
    ),
)


# ---------------------------------------------------------------------------
# Mock tool
# ---------------------------------------------------------------------------

@tool
def web_search(query: str) -> str:
    """Search the web for recent information on a topic."""
    return (
        f"Top results for '{query}': "
        "(1) AI agents are autonomous systems driven by LLMs. "
        "(2) Multi-agent frameworks enable task decomposition across specialised nodes. "
        "(3) Provenance tracking is required under EU AI Act Art. 12 for high-risk systems."
    )


# ---------------------------------------------------------------------------
# Pipeline state
# ---------------------------------------------------------------------------

class ResearchState(TypedDict, total=False):
    topic: str
    search_results: str
    research_notes: str
    summary: str
    report: str


# ---------------------------------------------------------------------------
# Node functions
# ---------------------------------------------------------------------------

def researcher(state: ResearchState, config: RunnableConfig) -> ResearchState:
    topic = state["topic"]
    search_results = web_search.invoke({"query": topic}, config=config)
    llm_config = merge_configs(config, {"metadata": {"ls_model_name": "fake-researcher"}})
    response = _researcher_llm.invoke(
        [HumanMessage(content=f"Topic: {topic}\n\nSearch results:\n{search_results}")],
        config=llm_config,
    )
    return {"search_results": str(search_results), "research_notes": response.content}


def summarizer(state: ResearchState, config: RunnableConfig) -> ResearchState:
    llm_config = merge_configs(config, {"metadata": {"ls_model_name": "fake-summarizer"}})
    response = _summarizer_llm.invoke(
        [HumanMessage(content=f"Summarise these research notes:\n\n{state.get('research_notes', '')}")],
        config=llm_config,
    )
    return {"summary": response.content}


def writer(state: ResearchState, config: RunnableConfig) -> ResearchState:
    llm_config = merge_configs(config, {"metadata": {"ls_model_name": "fake-writer"}})
    response = _writer_llm.invoke(
        [HumanMessage(content=f"Write a final report from this summary:\n\n{state.get('summary', '')}")],
        config=llm_config,
    )
    return {"report": response.content}


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

def _build_graph():
    g = StateGraph(ResearchState)
    g.add_node("researcher", researcher)
    g.add_node("summarizer", summarizer)
    g.add_node("writer", writer)
    g.set_entry_point("researcher")
    g.add_edge("researcher", "summarizer")
    g.add_edge("summarizer", "writer")
    g.add_edge("writer", END)
    return g.compile()


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run(
    topic: str = "AI agents in multi-agent systems",
    output_dir: str | pathlib.Path = "demos/research",
) -> dict:
    """Run the research pipeline and write the sealed bundle to *output_dir*."""
    session = PipelineSession(pipeline_id=PIPELINE_ID)
    middleware = ProvenanceMiddleware(session)

    graph = _build_graph()
    graph.invoke(
        {"topic": topic},
        config={"callbacks": [middleware]},
    )

    output_path = pathlib.Path(output_dir) / "mock_bundle.json"
    bundle = BundleGenerator(session, disclosure_presented=True).to_file(output_path)

    _print_summary(bundle, output_path)
    return bundle


def _print_summary(bundle: dict, path: pathlib.Path) -> None:
    records = bundle["records"]
    print("\n=== Research Pipeline (mock): Bundle Summary ===")
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
            detail = r.get("tool_name", "-")
            label = f"tool={detail}"
        else:
            detail = r.get("model_id", "-")
            label = f"model={detail}"
        parent_id = r.get("parent_record_id")
        print(f"  [{i + 1:2d}] {rtype:22s}  agent={agent:14s}  {label}")
        if parent_id:
            print(f"        ^ parent: {parent_id}")


if __name__ == "__main__":
    run()
