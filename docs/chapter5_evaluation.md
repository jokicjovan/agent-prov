# Chapter 5 — Evaluation

## 5.1 What the evaluation asks

Chapter 3 specified the protocol and Chapter 4 described its reference
implementation. This chapter asks whether the result is good enough to be useful,
along three axes that follow directly from the thesis claims:

1. **Completeness** — does the protocol actually capture what the EU AI Act's
   record-keeping and oversight obligations require? (§5.2)
2. **Overhead** — what runtime and storage cost does the provenance layer add to
   a pipeline, and how does that cost scale? (§5.3)
3. **Developer effort** — how much code must a developer write to instrument a
   pipeline, and does that effort grow with pipeline size? (§5.4)

The chapter then positions the result against the closest prior work, PROV-AGENT
(§5.5), and closes with the threats to validity that qualify every number here
(§5.6).

The three axes are deliberately chosen to test the protocol's central promise. A
provenance layer for regulated AI is worthless if it misses the obligations it
claims to discharge (completeness), unusable if it slows the pipeline it observes
(overhead), and unadopted if instrumenting a pipeline is laborious (effort). Each
axis has a corresponding data artefact committed to the repository:
`evaluation/completeness_checklist.csv`, `evaluation/benchmark_results.csv`, and
`evaluation/dev_effort.md`. This chapter reports over those artefacts; it does
not introduce numbers that are not reproducible from them.

---

## 5.2 Completeness against the EU AI Act

### 5.2.1 Method

Completeness was evaluated as a clause-by-clause audit rather than a
self-assessment. Every technical sub-clause of Articles 12, 14, and 50 that
could bear on an agent pipeline's record stream was extracted into a row of
`evaluation/completeness_checklist.csv`. Each row records the clause, its exact
technical requirement, the population of systems it applies to, a coverage
verdict, the record types and protocol fields that discharge it, the evidence for
the verdict, and — where coverage is not total — a gap note explaining the
boundary. The audit is conservative: a clause is marked *covered* only when a
populated, schema-validated field carries the required information, and the
default for any obligation that is a UI, design, or application-layer concern is
*out of scope* rather than a generous *covered*.

Four verdicts are used:

- **covered** — a protocol field discharges the obligation, and its presence in a
  bundle is verifiable evidence the obligation was met.
- **partial** — the protocol provides the substrate but full satisfaction depends
  on deployer instrumentation or a constraint the schema cannot mechanically
  enforce.
- **out_of_scope** — the obligation is real but belongs to a layer the protocol
  deliberately does not model (risk classification, oversight-UI design,
  artifact-level watermarking).
- **not_covered** — the protocol should capture it but does not.

### 5.2.2 Results

Twenty-one clauses were audited. The distribution of verdicts:

| Verdict | Count | Share |
|---------|-------|-------|
| covered | 13 | 62% |
| partial | 4 | 19% |
| out_of_scope | 4 | 19% |
| not_covered | **0** | **0%** |
| **Total** | **21** | |

Broken down by article:

| Article | Clauses | covered | partial | out_of_scope | not_covered |
|---------|--------:|--------:|--------:|-------------:|------------:|
| Art. 12 — record-keeping | 8 | 6 | 2 | 0 | 0 |
| Art. 14 — human oversight | 8 | 5 | 2 | 1 | 0 |
| Art. 50 — transparency | 5 | 2 | 0 | 3 | 0 |
| **Total** | **21** | **13** | **4** | **4** | **0** |

The headline result is the zero in the `not_covered` column: there is no clause
within scope that the protocol fails to address. Every obligation is either
discharged by a field, partially discharged with a documented boundary, or
explicitly placed outside the protocol's layer with a justification. The shape of
the table is also informative: Article 12 (record-keeping) and Article 14 (human
oversight) — the two articles the protocol primarily targets — are almost entirely
covered, while the out-of-scope verdicts concentrate in Article 50, whose
transparency duties are mostly artifact- and UI-level obligations the record
stream does not own (§5.2.3).

The full clause-level audit:

| Clause | Requirement (abbreviated) | Verdict | Discharging field(s) |
|--------|---------------------------|---------|----------------------|
| 12(1) | System allows automatic log generation | covered | `bundle_hash` |
| 12(2)(a) | Identify situations that may result in risk | partial | `status`, `error`, `outcome` |
| 12(2)(b) | Facilitate post-market monitoring (drift) | covered | `model_id`, `model_version` |
| 12(2)(c) | Support operational monitoring (linkable records) | covered | `pipeline_id`, `session_id` |
| 12(3)(a) | Record start and end time of each use | covered | `timestamp_start`, `timestamp_end` |
| 12(3)(b) | Record the reference database consulted | partial | `reference_data_id` |
| 12(3)(c) | Record input data that produced a result | covered | `input_hash` |
| 12(3)(d) | Identify persons who verified results | covered | `reviewer_id` |
| 14(1) | Allow effective oversight (a decision point exists) | covered | `human_intervention` (record existence) |
| 14(2) | Oversight prevents/minimises risk | covered | `action_type` |
| 14(4)(a) | Understand capabilities/limitations | partial | `model_id`, `model_version` |
| 14(4)(b) | Awareness of automation bias | out_of_scope | — |
| 14(4)(c) | Correctly interpret the output | covered | `output_before_hash`, `justification_hash` |
| 14(4)(d) | Disregard, override, or reverse the output | covered | `action_type`, `output_after_hash` |
| 14(4)(e) | Intervene or halt via a stop mechanism | covered | `action_type`, `intervention_timestamp` |
| 14(5) | Biometric: ≥2 persons verify | partial | `reviewer_id` |
| 50(1) | Inform users they interact with an AI system | covered | `disclosure_presented` |
| 50(2) | Mark AI-generated content machine-readable | out_of_scope | — |
| 50(3) | Inform persons exposed to emotion/biometric systems | out_of_scope | — |
| 50(4) | Disclose deepfake content | out_of_scope | — |
| 50(4) exc. | Editorial-responsibility exemption for AI text | covered | `action_type`, `reviewer_role` |

The thirteen *covered* clauses span the protocol's two target articles: the
logging-capability and traceability obligations of Article 12 and the
human-oversight obligations of Article 14, plus the Article 50(1) disclosure flag
and the Article 50(4) editorial-review exception. The last is worth singling out,
because it is discharged by the thesis's novel record type rather than a
conventional log field: an AI-generated text is exempt from the deepfake
disclosure duty when it has been reviewed under editorial responsibility, and the
Human Intervention Record substantiates exactly that through `action_type:
approved` combined with a `reviewer_role`.

More broadly, the Article 14 oversight cluster is the coverage most directly
attributable to the Human Intervention Record. The before/after override evidence
(`output_before_hash`, `output_after_hash`), the action type, and the intervention
timestamp together substantiate the "disregard, override, reverse, and halt"
requirements of 14(4)(c)–(e) — obligations that turn on *what a human did to an
agent's output and when*, which no prior provenance schema records. Without that
record type these five Article 14 rows would be uncovered; with it, they are the
protocol's strongest evidence.

### 5.2.3 The partial and out-of-scope verdicts

The four *partial* verdicts each mark a clean boundary between what the protocol
can guarantee and what only a deployment can:

- **Art. 12(2)(a)** (identify situations that may result in risk) — per-step
  `status`/`error` and the bundle-level `outcome` record malfunctions, failed
  steps, and aborted runs, which are the events most relevant to risk situations.
  What remains application-layer is the *classification* judgement: deciding which
  recorded events constitute reportable risk under Article 79(1). The protocol
  surfaces the events; it does not tag them as risk.
- **Art. 12(3)(b)** (reference database consulted) — `reference_data_id` exists on
  both automated record types and the middleware populates it from run metadata
  (the same path as `tool_version`), so a deployer can supply the consulted-corpus
  identifier. What the schema cannot enforce is that it is *actually* populated
  when external data was used, because whether a call consulted a corpus is
  out-of-band knowledge. Coverage is structural; substantive coverage depends on
  the deployer instrumenting the field.
- **Art. 14(4)(a)** (understand capabilities/limitations) — `model_id` and
  `model_version` give the reviewer the identifiers needed to look up capability
  documentation, but the human-readable capability summary is an oversight-UI
  obligation, not a logged field.
- **Art. 14(5)** (two-person rule for biometric ID) — `reviewer_id` is an array
  with `uniqueItems`, so it *accommodates* two reviewers, but the schema enforces
  `minItems: 1` universally; the `≥2` constraint for biometric pipelines would
  require a deployment-profile schema variant.

The four *out-of-scope* verdicts are consistent: they cover automation-bias
awareness (14(4)(b)) and the artifact-level disclosure and watermarking duties of
Article 50(2)–(4). These are properties of the application's oversight interface
or output artifacts — not of the pipeline's internal record stream — and Chapter 6
records the boundary deliberately rather than papering over it with a token field.

The honest reading of §5.2 is therefore: within the layer the protocol claims —
the tamper-evident record stream of a pipeline run — coverage is complete; the
gaps are at the layer boundaries, where they are documented rather than hidden.

---

## 5.3 Runtime and storage overhead

### 5.3.1 Method

Overhead was measured with a self-contained parametric harness,
`evaluation/benchmark.py`, that does **not** import the demonstration pipelines.
It defines its own deterministic fake-LLM graphs so that the numbers isolate
protocol cost from network and model variance, and so the benchmark does not
couple to demo internals. Two workloads are swept over a record-count grid of
{1, 5, 10, 25, 50}, with ten timed runs at each size:

- **agent_steps** — a linear chain of *N* fake-LLM nodes whose first node also
  calls a tool, producing *N* `agent_step` records plus one `tool_invocation`.
- **hitl** — one seed agent step followed by *M* `HumanReview` blocks, producing
  one `agent_step` plus *M* `human_intervention` records.

Each size is run under two paired conditions: a **baseline** with no callbacks
(the pipeline as it would run without the protocol) and an **instrumented** run
with `ProvenanceMiddleware` attached, after which the session is sealed into a
bundle. The seal — canonical-JSON hashing, validation, and the file write — is
timed separately as `seal_ms`. Graphs are compiled once per size and reused, so
compilation is excluded from the per-run timings. The reported figures are
medians over the ten runs.

The fake-LLM baseline is the load-bearing caveat for this section and is returned
to in §5.3.4: because a fake model returns instantly, the baseline is
sub-millisecond, which inflates every *percentage* of overhead. The *absolute*
per-record costs are the figures that transfer to a real deployment.

### 5.3.2 Results — automated steps

| Records | baseline (ms) | emit (ms) | seal (ms) | overhead (ms) | overhead (%) | bytes | B/record |
|--------:|--------------:|----------:|----------:|--------------:|-------------:|------:|---------:|
| 2  | 0.769 | 0.771 | 1.002 | 1.007 | 128.7 | 1 907 | 954 |
| 6  | 1.669 | 1.728 | 1.859 | 1.931 | 115.2 | 4 919 | 820 |
| 11 | 2.623 | 2.858 | 2.888 | 3.158 | 120.6 | 8 684 | 789 |
| 26 | 5.438 | 6.208 | 5.907 | 6.653 | 123.9 | 20 024 | 770 |
| 51 | 10.235 | 12.140 | 10.676 | 12.652 | 122.5 | 38 924 | 763 |

(*emit* is the instrumented graph execution with per-node emission, excluding the
seal; *overhead* is `emit + seal − baseline`.)

Two facts stand out. First, **overhead is linear in record count**: a
least-squares fit over the grid gives ≈ 0.24 ms of total overhead per record.
Second, **the cost is the seal, not per-node emission.** Subtracting the baseline
from the emit column shows per-node emission adds only ~1.9 ms across 51 records —
under 40 µs per record — while the seal grows at ≈ 0.20 ms per record and
accounts for the bulk of the overhead at every size. This is the expected shape:
emission is a constant-work callback per event, whereas the seal canonicalises
and validates the whole accumulated record set once at the end, so it scales with
the number of records.

### 5.3.3 Results — human interventions

| Records | baseline (ms) | emit (ms) | seal (ms) | overhead (ms) | overhead (%) | bytes | B/record |
|--------:|--------------:|----------:|----------:|--------------:|-------------:|------:|---------:|
| 2  | 0.526 | 0.513 | 0.996 | 0.991 | 188.1 | 1 966 | 983 |
| 6  | 0.558 | 0.580 | 2.484 | 2.512 | 456.8 | 5 254 | 876 |
| 11 | 0.575 | 0.639 | 4.295 | 4.358 | 750.9 | 9 364 | 851 |
| 26 | 0.796 | 0.801 | 9.822 | 9.912 | 1 276.7 | 21 694 | 834 |
| 51 | 0.693 | 0.992 | 18.851 | 19.055 | 2 792.0 | 42 244 | 828 |

The HITL workload makes the seal-dominated structure unmistakable. The baseline
here is just the single seed node and stays flat (~0.5–0.8 ms) no matter how many
human reviews follow, because in the no-provenance world a human decision records
nothing. The instrumented `HumanReview` blocks are cheap to execute (the *emit*
column stays near 1 ms), so almost the entire overhead is the seal, which grows
at ≈ 0.36 ms per record. Per-record overhead from the linear fit is ≈ 0.37 ms —
essentially all of it the seal.

The overhead *percentage* column is where the fake-LLM artefact is most visible:
it climbs to 2 792% at 51 records. This number is not a finding about the protocol;
it is an arithmetic consequence of dividing a growing seal cost by a flat,
near-instant baseline. §5.3.4 explains why it must be read that way.

### 5.3.4 Storage cost and the percentage caveat

**Storage is a near-constant per record.** Both workloads converge on a stable
bytes-per-record figure as the fixed bundle envelope is amortised: ≈ 763 B per
record for `agent_step`-heavy bundles and ≈ 828 B per record for HITL-heavy
bundles at the largest size. A bundle's on-disk size is therefore predictable
from its record count — a 1 000-record run produces a bundle on the order of
0.8 MB. Because the bundle stores hashes, not content (§4.8), this figure is
independent of how large the underlying prompts and outputs are.

**The percentages must be read as artefacts, not findings.** Every overhead
percentage in §5.3.2–§5.3.3 is computed against a fake LLM that returns in
microseconds. A real model call takes hundreds of milliseconds to several
seconds. Against that baseline, a per-record cost of 0.24–0.37 ms and a seal
measured in single-digit milliseconds is **negligible** — well under 1% of the
wall-clock time of a single real LLM call, and the seal runs once per pipeline,
not once per call. The honest summary is the absolute figures: sub-millisecond
emission per event, low-single-digit-millisecond sealing for typical bundles, and
sub-kilobyte storage per record. The percentage column exists only because the
benchmark deliberately removed model latency to expose protocol cost in
isolation; it would shrink to near zero the moment a real model is substituted.
The `live.py` demo variants exist precisely so this substitution can be confirmed
qualitatively against a real provider.

---

## 5.4 Developer effort

### 5.4.1 Method

Instrumentation effort was measured as the count of source lines that exist in an
instrumented pipeline *solely* to produce provenance — lines that would be deleted
if provenance were removed — over the two demonstration pipelines. The full
method and line-by-line accounting are in `evaluation/dev_effort.md`. Counts are
decomposed into three buckets that scale differently: **A**, fixed wiring
(constant per pipeline); **B**, per automated record; and **C**, per
human-intervention record. The decomposition matters more than any single total,
because it shows *where* effort is and is not incurred.

### 5.4.2 Results

| Pipeline | Records | A (fixed) | B (per auto) | C (per HITL) | Total |
|----------|---------|----------:|-------------:|-------------:|------:|
| Research (live) | 1 tool + 3 agent | 7 | 0 | — | **7** |
| Document review (live) | 2 agent + 2 HITL | 8 | 0 | ~12 | **~20** |

(The `live` variants are the reference: a real provider advertises its own model
name, so the per-node model-name hint the deterministic `mock` variants add is
unnecessary. The `mock` totals in `dev_effort.md` are 3 and 2 lines higher
respectively for that reason — a property of the test double, not of instrumenting
a real pipeline.)

Three results follow:

1. **Fixed wiring is small and constant.** A fully automated pipeline is
   instrumented for seven lines — three imports, two construction lines
   (`PipelineSession`, `ProvenanceMiddleware`), one `callbacks` config key, and
   one bundle seal — and that figure does not grow with the graph. The three
   capture lines are the "three lines" non-invasiveness claim of §4.11 made
   concrete; the other four are imports and the seal.
2. **Automated steps cost nothing per record.** Bucket B is zero. Once the
   middleware is attached, every model and tool call fires the callbacks it
   listens on; no node function is modified, and a three-node pipeline costs the
   same seven lines as a thirty-node one. (Config threading — `model.invoke(...,
   config=config)` — is required for callbacks to propagate, but it is idiomatic
   LangGraph already present in well-written nodes, so it is attributed to the
   framework, not the protocol.)
3. **Human capture is the only marginal cost, and it is appropriate.** Each
   oversight act adds one `HumanReview` block (~6 lines, 2 logical statements)
   plus, once, the `HumanReview` import. This is the one place the protocol
   requires genuinely new per-event code — and it must, because a human decision
   is not a framework event and the before/after override evidence only exists
   because the application declares the decision point. The ~6 lines buy a
   complete Human Intervention Record with the `action_type` ↔ `output_after_hash`
   rules enforced inside the context manager, so the block cannot produce an
   inconsistent record.

The shape of the effort mirrors the shape of the information. Automated steps are
observable from framework callbacks and cost nothing to record; human decisions
are not observable and must be declared, at a small fixed cost per decision.

---

## 5.5 Comparison with PROV-AGENT

The closest prior work, PROV-AGENT (Souza et al., IEEE e-Science 2025), captures
automated agent execution for scientific workflows. This thesis extends its
automated-capture pattern and differentiates on human oversight and regulatory
framing. The differentiation, established analytically in the gap analysis
(`docs/gap_analysis.md`), is summarised here against the evaluation results:

| Dimension | PROV-AGENT | This protocol |
|-----------|------------|---------------|
| Automated agent step capture | ✅ | ✅ |
| Tool invocation capture | ✅ | ✅ |
| Human intervention record | ❌ | ✅ — the core contribution |
| Before/after override state | ❌ | ✅ `output_before_hash` / `output_after_hash` |
| HITL action type | ❌ | ✅ approved / rejected / edited / escalated |
| Reviewer identity | ❌ | ✅ `reviewer_id` array (supports Art. 14(5)) |
| EU AI Act clause mapping | ❌ | ✅ Arts. 12, 14, 50 — 13/21 clauses covered, 0 uncovered |
| Privacy-preserving content hashing | ❌ (raw text default) | ✅ SHA-256, content stored out of band |
| Pipeline integrity seal | ❌ | ✅ `bundle_hash` (RFC 8785 canonical JSON) |
| Multi-framework support | ✅ (LangChain, CrewAI, OpenAI) | LangGraph only (PoC scope) |

The comparison is not a scoreboard. PROV-AGENT and this protocol target different
problems: PROV-AGENT optimises reproducibility for scientific HPC workflows and
supports several frameworks; this protocol targets regulatory compliance for a
single framework and adds the one record type — human oversight — that the Act
requires and PROV-AGENT does not model. The two rows where PROV-AGENT leads
(multi-framework support, scientific-workflow optimisation) are scope decisions of
this PoC rather than protocol limitations: the record schemas are
framework-agnostic, and Chapter 6 notes adapters for AutoGen and CrewAI as future
work. The rows where this protocol leads — the HITL record, the before/after
evidence, the EU AI Act mapping, the integrity seal — are the thesis
contribution, and §5.2–§5.4 are the evidence that they are not merely specified
but implemented, complete against the obligations they target, and cheap to adopt.

---

## 5.6 Threats to validity

The numbers above are honest only if their limits are stated.

**The benchmark uses fake LLMs.** This is a deliberate choice to isolate protocol
cost from model variance (§5.3.1), but it means the overhead *percentages* are
not deployment figures — they are inflated by a near-instant baseline and must be
read as the absolute per-record and per-seal costs in §5.3.4. The qualitative
claim that overhead is negligible against real model latency is supported by the
absolute numbers and by the `live.py` variants, but it is not separately
quantified against a real provider here; doing so would reintroduce the network
variance the benchmark was designed to exclude.

**The demonstration set is two pipelines.** Two pipelines are not a population,
so the effort figures in §5.4 are illustrative rather than statistical. They are,
however, decomposed into structural buckets (§5.4.2): bucket B is zero *by
construction* (callbacks fire without per-node code) and bucket A is constant *by
construction* (the wiring does not grow with the graph), so the per-pipeline
totals are expected to scale predictably — only bucket C grows, once per human
decision.

**Completeness is an audit, not a legal opinion.** The verdicts in §5.2 are a
software-engineering judgement of whether a field carries the information a clause
requires, not a determination that a deployment using the protocol is legally
compliant. Compliance is a property of a whole system and its operation; the
protocol provides the evidentiary substrate, and the audit shows the substrate is
complete within its layer. The *partial* and *out-of-scope* verdicts are the
explicit record of where that substrate ends and application, UI, and legal
judgement begin.

**Single-machine, single-implementation timings.** All timings come from one
machine and one implementation. They establish the *shape* of the cost — linear,
seal-dominated, sub-millisecond per record — which is a property of the algorithm
(one canonicalisation pass over the record set) rather than of the hardware, and
that shape is what transfers; the absolute milliseconds would shift on other
hardware.

Read together, §5.2–§5.5 support the thesis claims with their stated limits: the
protocol is complete against the in-scope obligations of Articles 12, 14, and 50
(zero uncovered clauses), adds overhead that is linear, seal-dominated, and
negligible against real model latency, and is adopted for a near-constant
instrumentation cost that grows only with the number of human decision points.
Chapter 6 turns to what these limits imply — the threat model for hash-based
evidence, the boundaries the out-of-scope verdicts mark, and the directions that
follow from them.
