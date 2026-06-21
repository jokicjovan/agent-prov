# Developer Effort — Instrumentation Cost

This document measures how much code a developer must add to an existing
LangGraph pipeline to make it emit provenance records. It is the third leg of
the evaluation, alongside completeness (`completeness_checklist.csv`) and
runtime/storage overhead (`benchmark_results.csv`).

The claim under test is the *non-invasiveness* claim: that the provenance layer
is attached to a pipeline through configuration rather than by restructuring it,
so the effort to instrument a pipeline is small and, for the automated path,
independent of pipeline size.

---

## 1. Metric

**Instrumentation line** — a non-blank, non-comment source line that exists in
the instrumented pipeline *solely* to produce provenance, i.e. a line that would
be deleted if provenance were removed. Import statements, the objects that wire
capture, the bundle seal, and the `HumanReview` blocks all count. The pipeline's
own logic — node functions, graph construction, prompts, state schema — does not.

Counts are decomposed into three buckets, because they scale differently:

| Bucket | Scales with | What it is |
|--------|-------------|------------|
| **A — fixed wiring** | constant per pipeline | imports, session, middleware, the `callbacks` config key, the bundle seal |
| **B — per automated record** | number of agent/tool steps | config propagation and (where needed) a model-name hint |
| **C — per human-intervention record** | number of oversight acts | one `HumanReview` block per human decision |

The decomposition is the point. A flat "lines added" figure hides that the
automated path costs nothing per step while human capture costs a fixed amount
per oversight act.

The two demonstration pipelines are the measured subjects: the fully-automated
research assistant (`demos/research/`) and the document review pipeline with two
human interventions (`demos/document_review/`). For each, the `live.py` variant
(real `ChatOpenAI`) is the reference for bucket B, because a real provider
advertises its own model name and the mock's name-hint line is then unnecessary.

---

## 2. Bucket A — fixed wiring

These lines appear once per pipeline run regardless of how many nodes it has.

```python
from agent_prov.session import PipelineSession                  # 1  import
from agent_prov.adapters.langchain import ProvenanceMiddleware  # 2  import
from agent_prov.bundle_generator import BundleGenerator         # 3  import

session = PipelineSession(pipeline_id=PIPELINE_ID)        # 4  capture
middleware = ProvenanceMiddleware(session)                # 5  capture

graph.invoke({...}, config={"callbacks": [middleware]})   # 6  capture (config key)

bundle = BundleGenerator(session, disclosure_presented=True).to_file(path)  # 7  seal
```

- **Fully automated pipeline (research):** **7 lines** — 3 imports, 2
  construction lines, 1 `callbacks` config key, 1 seal. The middle three
  (session, middleware, `callbacks` key) are the *capture* wiring; this is the
  "three lines" claim made in Chapter 4 §4.11. The remaining four are imports
  and the seal.
- **Pipeline with HITL (document review):** **8 lines** — the same seven plus
  one import, `from agent_prov.hitl import HumanReview`.

No node function is modified for bucket A. The middleware never appears inside
the graph; it is handed to the run through LangChain's standard `callbacks`
mechanism and removed by deleting these lines.

---

## 3. Bucket B — per automated record

For each `agent_step` and `tool_invocation` record, the dedicated provenance
code required is:

**Zero lines.** Once the middleware is attached (bucket A), every chat-model and
tool call inside the run fires the LangChain callbacks the middleware listens
on; records emit with no per-node code.

Two qualifications, neither of which is a true per-record cost:

1. **Config propagation.** For callbacks to reach a model or tool call, the
   injected `config` must be threaded into that call (`model.invoke(msgs,
   config=config)`). This is *idiomatic LangGraph* — node functions already take
   a `config` parameter and pass it down — so in well-written pipelines it is
   already present. Where it is absent it is one line per call site, but it is
   ordinary framework usage, not provenance-specific API.

2. **Model-name hint (mock only).** The deterministic fake LLM used in the
   `mock.py` variants does not advertise a model name, so each node adds one
   line (`merge_configs(config, {"metadata": {"ls_model_name": ...}})`) to give
   the emitter a clean `model_id` instead of the class-name fallback. A real
   provider (`ChatOpenAI` in `live.py`) sets `ls_model_name` itself, so the
   `live.py` nodes add **zero** lines. This cost is an artefact of the test
   double, not of instrumenting a real pipeline.

The consequence: instrumenting the three-node research pipeline costs the same 7
fixed lines whether it has 3 nodes or 30. Bucket B is flat at zero.

---

## 4. Bucket C — per human-intervention record

A human decision is not a LangChain event, so it cannot be captured by the
passive middleware. Each oversight act is wrapped explicitly in a `HumanReview`
block — this is the one place provenance requires genuinely new per-event code,
and it is irreducible: the before/after evidence that is the protocol's central
contribution only exists because the application declares the decision point.

A block, in the document review pipeline's formatting:

```python
with HumanReview(
    session=session,
    reviewer_id=["reviewer:editor-01"],
    reviewer_role="editor",
    output_before=agent_summary,
) as review:
    review.edit(REVIEWER_EDIT, justification="...")
```

- **Per oversight act:** ~6 instrumentation lines as formatted above (2 logical
  statements — the `with` construction and the decision call). The document
  review pipeline has two interventions (one `edit`, one `approve`), so bucket C
  is **~12 lines** there.

This is per *human decision point*, not per record produced by automation, and
it buys the full Human Intervention Record: reviewer identity and role, the
before/after output hashes, the action type, the timestamp, and an optional
justification hash. The conditional rules tying `action_type` to
`output_after_hash` are enforced inside the context manager, not left to the
caller, so the ~6 lines cannot produce an inconsistent record.

---

## 5. Totals

| Pipeline | Records | A (fixed) | B (per auto) | C (per HITL) | Total instrumentation |
|----------|---------|-----------|--------------|--------------|-----------------------|
| Research (live) | 1 tool + 3 agent | 7 | 0 | — | **7** |
| Research (mock) | 1 tool + 3 agent | 7 | +3 (name hints) | — | 10 |
| Document review (live) | 2 agent + 2 HITL | 8 | 0 | ~12 | **~20** |
| Document review (mock) | 2 agent + 2 HITL | 8 | +2 (name hints) | ~12 | ~22 |

Reading the reference (`live`) rows:

- A fully automated multi-agent pipeline is instrumented for **7 lines, flat** —
  no per-step cost, no graph changes.
- Adding human-oversight capture costs **one extra import plus ~6 lines per
  oversight act**. In the document review pipeline this is ~13 lines on top of
  the fixed wiring, and all of it is concentrated in the two `HumanReview`
  blocks.

The marginal cost of provenance is therefore close to zero for automated steps
and a small fixed amount per human decision — which matches where the
information actually has to come from. Automated steps are observable from
framework callbacks and cost nothing to record; human decisions are not
observable and must be declared, and the declaration is ~6 lines.

---

## 6. Threats to this measurement

- **Line counts are formatting-dependent.** The `HumanReview` blocks are counted
  as written (one argument per line); collapsed onto fewer lines they are
  smaller, expanded with comments larger. The logical-statement counts (2 per
  block) are formatting-independent and are the more robust figure.
- **The demos are small.** Two pipelines are not a population. The buckets,
  however, are structural: bucket B is zero by construction (callbacks fire
  without per-node code) and bucket A is constant by construction (the wiring
  does not grow with the graph), so the per-pipeline totals scale predictably to
  larger graphs — the only term that grows is bucket C, once per human decision.
- **Config threading is attributed to the framework, not the protocol.** A
  pipeline that does not already thread `config` would pay a per-call-site line
  to do so. This is counted as idiomatic LangGraph rather than provenance
  effort; a stricter accounting would add it to bucket B. Even under that
  stricter rule the cost is one line per existing call site, not new structure.
- **The seal and report are one-time.** Generating the compliance PDF is a
  single command (`python -m agent_prov.reporting <bundle.json> <out.pdf>`) and
  adds no lines to the pipeline; it is excluded from these counts.
