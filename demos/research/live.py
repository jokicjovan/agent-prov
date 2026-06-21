"""Research Assistant pipeline — live variant (real OpenAI chat model).

Graph:  researcher  →  summarizer  →  writer

Same structure as ``demos/research/mock.py``, but the three nodes call a
real OpenAI chat model via langchain-openai so that middleware overhead is
measured against realistic LLM latency rather than a synchronous stub. The
mock variant remains the deterministic reference run.

Requires:
    OPENAI_API_KEY  in the environment, or in a `.env` file at the repo root
                    (loaded via python-dotenv on import).
    OPENAI_MODEL    (optional, default "gpt-4o-mini")

Usage:
    uv run python demos/research/live.py
"""

from __future__ import annotations

import os
import pathlib
from typing import TypedDict

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph

from agent_prov.bundle_generator import BundleGenerator
from agent_prov.adapters.langchain import ProvenanceMiddleware
from agent_prov.session import PipelineSession

# Load OPENAI_API_KEY (and other secrets) from a `.env` file at the repo root
# when present. Real shell-exported environment values still take precedence.
load_dotenv()


PIPELINE_ID = "b1f4a2d0-7c8e-4a1f-9b3d-6e5a8c2f4d11"
DEFAULT_MODEL = "gpt-4o-mini"


def _make_llm() -> ChatOpenAI:
    model = os.getenv("OPENAI_MODEL", DEFAULT_MODEL)
    return ChatOpenAI(model=model, temperature=0)


@tool
def web_search(query: str) -> str:
    """Search the web for recent information on a topic."""
    return (
        f"Top results for '{query}': "
        "(1) AI agents are autonomous systems driven by LLMs. "
        "(2) Multi-agent frameworks enable task decomposition across specialised nodes. "
        "(3) Provenance tracking is required under EU AI Act Art. 12 for high-risk systems."
    )


class ResearchState(TypedDict, total=False):
    topic: str
    search_results: str
    research_notes: str
    summary: str
    report: str


def researcher(state: ResearchState, config: RunnableConfig) -> ResearchState:
    topic = state["topic"]
    search_results = web_search.invoke({"query": topic}, config=config)
    prompt = (
        "You are a research analyst. Synthesise the search results below into "
        "concise research notes (3-5 sentences).\n\n"
        f"Topic: {topic}\n\nSearch results:\n{search_results}"
    )
    response = _make_llm().invoke([HumanMessage(content=prompt)], config=config)
    return {"search_results": str(search_results), "research_notes": response.content}


def summarizer(state: ResearchState, config: RunnableConfig) -> ResearchState:
    prompt = (
        "Summarise the following research notes into two crisp sentences:\n\n"
        f"{state.get('research_notes', '')}"
    )
    response = _make_llm().invoke([HumanMessage(content=prompt)], config=config)
    return {"summary": response.content}


def writer(state: ResearchState, config: RunnableConfig) -> ResearchState:
    prompt = (
        "Write a short markdown report (about 150 words, with a heading) from "
        "this summary:\n\n"
        f"{state.get('summary', '')}"
    )
    response = _make_llm().invoke([HumanMessage(content=prompt)], config=config)
    return {"report": response.content}


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


def run(
    topic: str = "AI agents in multi-agent systems",
    output_dir: str | pathlib.Path = "demos/research",
) -> dict:
    """Run the live research pipeline and write the sealed bundle to *output_dir*."""
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Export it in your shell before running "
            "the live demo, or run demos/research/mock.py for a deterministic "
            "offline variant."
        )

    session = PipelineSession(pipeline_id=PIPELINE_ID)
    middleware = ProvenanceMiddleware(session)

    graph = _build_graph()
    graph.invoke({"topic": topic}, config={"callbacks": [middleware]})

    output_path = pathlib.Path(output_dir) / "live_bundle.json"
    bundle = BundleGenerator(session, disclosure_presented=True).to_file(output_path)

    _print_summary(bundle, output_path)
    return bundle


def _print_summary(bundle: dict, path: pathlib.Path) -> None:
    records = bundle["records"]
    print("\n=== Research Pipeline (live): Bundle Summary ===")
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
        print(f"  [{i + 1:2d}] {rtype:22s}  agent={agent:14s}  {label}")
        if parent_id:
            print(f"        ^ parent: {parent_id}")


if __name__ == "__main__":
    run()
