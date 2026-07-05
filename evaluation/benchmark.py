"""Overhead benchmark for the provenance middleware.

Measures the runtime and storage cost the provenance layer adds to a pipeline,
as a function of how many records it produces. The benchmark is self-contained:
it defines its own deterministic fake-LLM graphs and HITL workloads rather than
importing the demo pipelines, so the numbers isolate protocol overhead from
network/model variance and the benchmark does not couple to demo internals.

Two parametric workloads are swept over a record-count grid:

* ``agent_steps`` - a linear chain of N fake-LLM nodes whose first node also
  calls a tool. Produces N ``agent_step`` records + 1 ``tool_invocation``.
* ``hitl`` - one seed agent step followed by M ``HumanReview`` blocks. Produces
  1 ``agent_step`` + M ``human_intervention`` records.

Each (workload, size) is run under two paired conditions:

* **baseline**     - graphs run with no callbacks; no records, no bundle. The
  pipeline as it would run without the protocol.
* **instrumented** - the same compiled graphs run with ``ProvenanceMiddleware``
  attached (and ``HumanReview`` blocks for the HITL workload), then the session
  is sealed into a bundle. ``seal_ms`` (canonical-JSON hashing + validation +
  file write) is timed separately from graph execution.

Graphs are compiled once per size and reused across runs, so compilation cost
is excluded from per-run timings. Per-run rows are written to
``evaluation/benchmark_results.csv``:

    workload, n_records, run, baseline_ms, instrumented_ms, seal_ms,
    overhead_ms, overhead_pct, bundle_bytes

where ``overhead_ms = (instrumented_ms + seal_ms) - baseline_ms``. Sweeping
record count lets the evaluation report a per-record latency cost (the slope of
overhead vs. n_records) and a bytes-per-record storage cost.

Usage:
    uv run python evaluation/benchmark.py
"""

from __future__ import annotations

import csv
import pathlib
import statistics
import tempfile
from time import perf_counter
from typing import Callable, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.config import merge_configs
from langchain_core.tools import tool
from langgraph.graph import END, StateGraph

from agent_prov.bundle_generator import BundleGenerator
from agent_prov.adapters.langchain import ProvenanceMiddleware
from agent_prov.hitl import HumanReview
from agent_prov.session import PipelineSession


RUNS = 10
SIZES = [1, 5, 10, 25, 50]
OUTPUT_CSV = pathlib.Path(__file__).parent / "benchmark_results.csv"

CSV_FIELDS = [
    "workload",
    "n_records",
    "run",
    "baseline_ms",
    "instrumented_ms",
    "seal_ms",
    "overhead_ms",
    "overhead_pct",
    "bundle_bytes",
]


# ---------------------------------------------------------------------------
# Fake LLM + tool (deterministic; no external calls)
# ---------------------------------------------------------------------------

class _FakeLLM(BaseChatModel):
    """Deterministic fake LLM that echoes a fixed response."""

    response: str = (
        "Synthesised step output for the provenance overhead benchmark. "
        "Content is fixed so timings reflect protocol cost, not model variance."
    )

    @property
    def _llm_type(self) -> str:
        return "fake-bench"

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


_LLM = _FakeLLM()


@tool
def lookup(query: str) -> str:
    """Look up reference information for a query (benchmark stub)."""
    return f"Reference result for '{query}' used by the first pipeline step."


class _BenchState(TypedDict, total=False):
    text: str


def _make_step_node(name: str, *, call_tool: bool) -> Callable:
    """Build a node that optionally calls the tool, then invokes the fake LLM."""

    def node(state: _BenchState, config: RunnableConfig) -> _BenchState:
        text = state.get("text", "initial prompt")
        if call_tool:
            tool_config = merge_configs(config, {"metadata": {"tool_version": "1.0.0"}})
            text = lookup.invoke({"query": str(text)}, config=tool_config)
        llm_config = merge_configs(config, {"metadata": {"ls_model_name": name}})
        response = _LLM.invoke([HumanMessage(content=str(text))], config=llm_config)
        return {"text": response.content}

    return node


def _build_step_graph(n: int):
    """Compile a linear chain of *n* fake-LLM nodes; the first also calls a tool."""
    g = StateGraph(_BenchState)
    names = [f"step_{i}" for i in range(n)]
    for i, name in enumerate(names):
        g.add_node(name, _make_step_node(name, call_tool=(i == 0)))
    g.set_entry_point(names[0])
    for a, b in zip(names, names[1:]):
        g.add_edge(a, b)
    g.add_edge(names[-1], END)
    return g.compile()


def _build_seed_graph():
    """Single fake-LLM node used to seed one agent_step before HITL reviews."""
    g = StateGraph(_BenchState)
    g.add_node("seed", _make_step_node("seed", call_tool=False))
    g.set_entry_point("seed")
    g.add_edge("seed", END)
    return g.compile()


# Compile once per size; reuse across runs so compilation is not timed.
_STEP_GRAPHS = {n: _build_step_graph(n) for n in SIZES}
_SEED_GRAPH = _build_seed_graph()


# ---------------------------------------------------------------------------
# agent_steps workload: N fake-LLM nodes (+1 tool) -> N+1 records
# ---------------------------------------------------------------------------

def _steps_baseline(n: int) -> None:
    _STEP_GRAPHS[n].invoke({"text": "initial prompt"})


def _steps_instrumented(n: int, bundle_path: pathlib.Path) -> tuple[float, int, int]:
    session = PipelineSession()
    middleware = ProvenanceMiddleware(session)
    _STEP_GRAPHS[n].invoke(
        {"text": "initial prompt"}, config={"callbacks": [middleware]}
    )

    seal_start = perf_counter()
    bundle = BundleGenerator(session, disclosure_presented=True).to_file(bundle_path)
    seal_ms = (perf_counter() - seal_start) * 1000.0

    return seal_ms, bundle_path.stat().st_size, len(bundle["records"])


# ---------------------------------------------------------------------------
# hitl workload: 1 seed agent_step + M HumanReview blocks -> M+1 records
# ---------------------------------------------------------------------------

def _hitl_baseline(m: int) -> None:
    # No-provenance equivalent: the seed step runs; human decisions record
    # nothing, so they contribute no work beyond producing their text.
    _SEED_GRAPH.invoke({"text": "initial prompt"})


def _hitl_instrumented(m: int, bundle_path: pathlib.Path) -> tuple[float, int, int]:
    session = PipelineSession()
    middleware = ProvenanceMiddleware(session)
    _SEED_GRAPH.invoke({"text": "initial prompt"}, config={"callbacks": [middleware]})

    for i in range(m):
        with HumanReview(
            session=session,
            reviewer_id=[f"reviewer:{i:03d}"],
            reviewer_role="editor",
            output_before=f"output before review {i}",
        ) as review:
            review.edit(
                f"output after review {i}",
                justification=f"adjustment {i}",
            )

    seal_start = perf_counter()
    bundle = BundleGenerator(session, disclosure_presented=True).to_file(bundle_path)
    seal_ms = (perf_counter() - seal_start) * 1000.0

    return seal_ms, bundle_path.stat().st_size, len(bundle["records"])


# ---------------------------------------------------------------------------
# Benchmark driver
# ---------------------------------------------------------------------------

# workload name -> (baseline_fn(size), instrumented_fn(size, path))
WORKLOADS: dict[str, tuple[Callable, Callable]] = {
    "agent_steps": (_steps_baseline, _steps_instrumented),
    "hitl": (_hitl_baseline, _hitl_instrumented),
}


def _benchmark(tmp_dir: pathlib.Path) -> list[dict]:
    rows: list[dict] = []

    for name, (baseline_fn, instrumented_fn) in WORKLOADS.items():
        bundle_path = tmp_dir / f"{name}_bench_bundle.json"

        for size in SIZES:
            # Warm-up at this size to absorb lazy init before timing.
            baseline_fn(size)
            instrumented_fn(size, bundle_path)

            for run in range(1, RUNS + 1):
                base_start = perf_counter()
                baseline_fn(size)
                baseline_ms = (perf_counter() - base_start) * 1000.0

                instr_start = perf_counter()
                seal_ms, bundle_bytes, n_records = instrumented_fn(size, bundle_path)
                instrumented_ms = (perf_counter() - instr_start) * 1000.0 - seal_ms

                overhead_ms = (instrumented_ms + seal_ms) - baseline_ms
                overhead_pct = (overhead_ms / baseline_ms * 100.0) if baseline_ms else 0.0

                rows.append(
                    {
                        "workload": name,
                        "n_records": n_records,
                        "run": run,
                        "baseline_ms": round(baseline_ms, 4),
                        "instrumented_ms": round(instrumented_ms, 4),
                        "seal_ms": round(seal_ms, 4),
                        "overhead_ms": round(overhead_ms, 4),
                        "overhead_pct": round(overhead_pct, 2),
                        "bundle_bytes": bundle_bytes,
                    }
                )

    return rows


def _print_summary(rows: list[dict]) -> None:
    print(f"\n=== Overhead Benchmark ({RUNS} runs/size, fake LLMs) ===")
    for name in WORKLOADS:
        print(f"\n{name}")
        print(
            f"  {'records':>8} {'base ms':>9} {'instr ms':>9} {'seal ms':>9} "
            f"{'ovhd ms':>9} {'ovhd %':>8} {'bytes':>8} {'B/rec':>7}"
        )
        for size in SIZES:
            srows = [r for r in rows if r["workload"] == name and r["n_records"]
                     == (size + 1)]
            if not srows:
                continue
            nrec = srows[0]["n_records"]
            base = statistics.median(r["baseline_ms"] for r in srows)
            instr = statistics.median(r["instrumented_ms"] for r in srows)
            seal = statistics.median(r["seal_ms"] for r in srows)
            ovhd = statistics.median(r["overhead_ms"] for r in srows)
            ovhd_pct = statistics.median(r["overhead_pct"] for r in srows)
            size_b = srows[0]["bundle_bytes"]
            print(
                f"  {nrec:8d} {base:9.3f} {instr:9.3f} {seal:9.3f} "
                f"{ovhd:9.3f} {ovhd_pct:8.1f} {size_b:8d} {size_b / nrec:7.0f}"
            )


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        rows = _benchmark(pathlib.Path(tmp))

    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    _print_summary(rows)
    print(f"\nWrote {len(rows)} rows -> {OUTPUT_CSV.resolve()}")


if __name__ == "__main__":
    main()
