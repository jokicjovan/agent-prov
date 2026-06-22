# Chapter 6 — Discussion and Future Work

## 6.1 What the protocol establishes, and what remains open

The preceding chapters specified a provenance protocol for regulated
multi-agent pipelines (Chapter 3), implemented it as non-invasive LangGraph
middleware (Chapter 4), and evaluated it along completeness, overhead, and
developer effort (Chapter 5). The evaluation supports the three thesis claims
within stated limits: the protocol is complete against the in-scope obligations
of EU AI Act Articles 12, 14, and 50 with zero uncovered clauses, it adds a
linear and seal-dominated overhead that is negligible against real model
latency, and it instruments a pipeline for a near-constant effort that grows
only with the number of human decision points. The Human Intervention Record —
the contribution that distinguishes this work from PROV-AGENT — is implemented,
schema-validated, and the field that discharges the cluster of Article 14
oversight obligations no prior provenance schema addresses.

This chapter is the honest counterweight to that result. It examines what the
protocol does *not* establish: the precise evidentiary force of a hash-based
bundle and the adversaries it does and does not defend against (§6.2); the
limitations carried forward from the implementation and evaluation (§6.3); the
meaning of the out-of-scope verdicts, which mark a layer boundary rather than a
hole (§6.4); and the directions that follow — multi-framework adapters,
canonical identifier rewriting, content-addressed recovery of multi-agent
topology, cryptographic signing, deployment-profile schemas, and a
machine-readable declaration of behavioural constraints (§6.5).
The intent throughout is to state the boundaries precisely enough that a reader
can tell what the protocol guarantees from what a deployment must add.

## 6.2 The threat model for hash-based evidence

The protocol's central evidentiary device is the bundle: an ordered chain of
content-addressed records sealed by a `bundle_hash` over their canonical-JSON
form (§4.8). It is worth stating exactly what that device proves, because the
strength of the thesis's compliance claim is bounded by it, and a provenance
mechanism whose guarantees are overstated is worse than none.

### 6.2.1 What the bundle proves

A sealed bundle is **tamper-evident over its own contents.** Because
`bundle_hash` is the SHA-256 digest of the canonical serialisation of every
record (with the hash field itself excluded), any later alteration to any
record — reordering the chain, editing a timestamp, swapping an `action_type`,
removing a Human Intervention Record — changes the recomputed digest and is
detectable by anyone holding the original `bundle_hash`. Within the set of
records it contains, the bundle answers structural questions with cryptographic
force: how many records there were, in what order, with what parent-chain
linkage, with which human actions and before/after commitments, and whether the
set has been altered since sealing.

The per-record `input_hash` and `output_hash` are **binding commitments** to
content the bundle does not itself carry. Given the original message and the
canonical projection rules (§4.5.1), a verifier recomputes the digest and
confirms — again with cryptographic force — that *this* input produced *this*
output at the recorded step. This is the content-addressable property the
protocol relies on, and it is what lets a regulated deployment store the heavy
content out of band (§6.4.3) while keeping the lightweight, tamper-evident chain
of events in the bundle that goes to the auditor.

### 6.2.2 What the bundle does not prove

Three limits bound that force, and each is a candidate for the future work in
§6.5.

**The seal proves integrity, not authenticity.** `bundle_hash` is an unkeyed
digest. It detects *accidental or unattributed* modification, but it is not a
signature: anyone who can alter a bundle can recompute a fresh, internally
consistent `bundle_hash` over the altered contents. The seal therefore protects
a bundle in transit to an auditor who already holds the expected digest through
a trusted channel, and it protects against silent corruption — but it does not
on its own bind the bundle to the party that produced it, and it does not stop a
malicious producer from generating a wholly fabricated-but-consistent bundle
after the fact. Closing this gap requires a digital signature over `bundle_hash`
by a key the deployer controls, and ideally a trusted timestamp; both are noted
in §6.5.4. The current protocol provides the canonical form that such a
signature would sign, which is the prerequisite, but it does not specify the
signature itself.

**The chain proves order, not causation, and not completeness.** As recorded in
§4.13 and §3.7.3, `parent_record_id` is a chronological cursor — it links each
record to its immediate predecessor in emission order, not to the record that
*caused* it. A verifier can reconstruct the sequence of observed events but
cannot, from the chain alone, prove that a given tool call was issued *by* a
given agent step. Separately, the seal proves nothing about records that were
never emitted: an instrumented pipeline that is selectively un-instrumented for
one sensitive node produces a bundle that is internally consistent and complete
*as far as it goes*, with no intrinsic evidence that a step is missing. Detecting
omission requires an external expectation of what the pipeline should have
produced — a registered pipeline definition, or a node-count assertion — which
is a deployment control outside the record stream.

**The commitment proves correspondence, not retention.** An `output_hash` proves
that a revealed piece of content is the one that was committed to; it does
nothing to guarantee that the content still *exists* to be revealed. If a
deployment's content store loses or destroys the original message, the hash
becomes an unfalsifiable claim: it can never be contradicted, but it can also
never be substantiated. The protocol deliberately leaves content storage to the
deployment (§6.4.3), so retention — and the access control and legal-hold
discipline around it — is a deployment obligation the bundle cannot enforce.

### 6.2.3 Trust assumptions

The honest reading of §6.2 is that the protocol's adversary model is **a party
who tampers with the record stream after the fact, observed by a verifier who
holds the original seal.** Against that adversary the bundle is strong. It is
explicitly *not* a defence against a **dishonest producer at emission time** —
an operator who instruments selectively, fabricates a consistent bundle, or
destroys the backing content — because every such defence reduces to a question
of *who* vouches for the records and *when*, which is the province of signing,
timestamping, and external pipeline registration rather than of the hash chain
itself. Positioning the protocol this way is not a weakness to be hidden; it is
the standard division between an integrity-preserving data format and the
key-management and attestation infrastructure that turns integrity into
non-repudiation. The protocol occupies the first layer cleanly and names the
second as future work.

## 6.3 Limitations

Several limitations are distributed across the earlier chapters; they are
collected here so the contribution is read against a single, explicit account of
its boundaries. The threats to the *evaluation numbers* specifically are in §5.6
and are not repeated; this section concerns limitations of the protocol and
implementation themselves.

**Single packaged framework adapter.** The reference implementation ships one
packaged adapter, for LangGraph (§4.2). The record *schemas* are
framework-agnostic — they describe agent steps, tool calls, and human decisions
in terms no LangGraph concept leaks into — and the capture *seam* is the
framework-neutral record factory (§4.5), not the callback system: the
framework-free adapter of §4.5.5 records a complete bundle with no LangChain
present, so the seam itself is demonstrably not bound to one framework. What
remains LangGraph-specific is the *passive* capture property — recording without
touching the pipeline's own code. Nothing in the evaluation demonstrates that
this passive property holds in a framework whose execution model exposes
different (or no) extension points; the framework-free demo in fact instruments
more invasively, by inline calls. Packaged adapters for other frameworks (§6.5.1)
are the direct response, and the clean separation between the framework-specific
adapter and the framework-agnostic factory, session, and bundle layers (§4.3) is
what makes them tractable.

**Chronological parent chain.** As discussed in §4.13 and §6.2.2,
`parent_record_id` records order rather than causation. For the linear demo
pipelines the distinction is invisible — emission order *is* the causal order —
but a pipeline with parallel branches or out-of-order tool responses would
produce a chain that under-describes its true structure. The defined resolution
is an optional `caused_by_record_id` field (§3.7.3), deferred because the demos
do not exercise the case it solves; a fuller treatment that recovers the causal
topology from content and timestamps — without binding the protocol to any one
engine's execution model — is developed in §6.5.3.

**Semantic projection of identifiers.** `input_hash` and `output_hash` are
computed over a projection of the LangChain message list that strips runtime
identifiers — `AIMessage.id`, `tool_call_id` — so that identical content digests
identically across replays (§4.5.1). This is necessary for the digests to be
useful as evidence, but it has a cost: the projected hash cannot be
cross-referenced against the LLM provider's request log via the runtime id, so a
forensic correlation between a record and the provider's own trace is not
possible from the bundle alone. Two refinements address this from opposite
directions — a non-hashed `runtime_metadata` side field that preserves the id
without polluting the digest, and canonical identifier rewriting that keeps the
correlation *inside* the hashed structure (§6.5.2).

**Runner-emitted HITL record.** The document-review demonstration expresses its
human review points as node-level `interrupt()` gates inside a single multi-node
graph (§4.11.2), which is the idiomatic LangGraph form. One seam remains:
because the human decision occurs out of process while the graph is paused, the
`HumanReview` record is emitted by the runner on resume rather than from inside
the gate node itself. The record produced is identical either way; folding the
emission into the resume path, so the gate node and its record are one unit, is
the refinement noted in §6.5.6.

**Article 14(5) is accommodated, not enforced.** The two-person rule for
biometric identification systems is *accommodated* by `reviewer_id` being an
array with `uniqueItems`, but the schema enforces `minItems: 1` universally, so
it cannot mechanically require the second reviewer that 14(5) demands (§5.2.3).
Enforcing it requires a deployment-profile schema variant that tightens the
constraint for the biometric population without forcing it on every pipeline
(§6.5.5).

## 6.4 The boundaries the out-of-scope obligations mark

Four clauses were marked *out of scope* in the completeness audit (§5.2.3):
automation-bias awareness (14(4)(b)) and the artifact-level disclosure and
watermarking duties of Article 50(2)–(4). A fifth, risk classification (12(2)(a)),
was reclassified from out-of-scope to *partial* once the protocol began recording
the malfunction substrate (per-step `status`/`error` and the bundle-level
`outcome`); the residue that remains application-logic — deciding which recorded
events constitute reportable risk — is discussed in §6.4.1. It would
have been easy to add a token field for each remaining gap and claim a higher coverage number.
The audit deliberately does not, because each of these obligations lives at a
layer the record stream does not own, and a field that *records a claim* without
*carrying the evidence* is worse than an honest gap — it invites an auditor to
mistake a self-assertion for substantiation. This section states which layer
owns each boundary, so that a deployment built on the protocol knows where to
look for the rest of its compliance story.

### 6.4.1 Application-logic obligations

Article 12(2)(a) splits cleanly along this boundary. The protocol now records the
*events* relevant to risk — a step or tool that malfunctioned (`status: "error"`
with a structured `error`) and a run that ended in `error` or was `aborted`
(`outcome`) — which is why the audit moves it to *partial*. What stays out of
scope is the *classification* step: whether a given recorded event "may result in
risk" within the meaning of Article 79(1) is a judgement encoded in the
application's control flow and risk register, not a property of the event itself.
A provenance field asserting "this event was assessed as risk" would be an
unfalsifiable label; the protocol instead surfaces the malfunction faithfully and
leaves the assessment to the application's risk-management documentation under
Article 9 — a different obligation than the Article 12 record-keeping duty this
protocol targets.

Automation-bias awareness (14(4)(b)) remains fully out of scope: whether an
overseer is aware of automation bias is a property of how the oversight interface
is designed and how the overseer was trained, not observable from any record
stream, and a field asserting "the reviewer was aware of automation bias" would
be the kind of unfalsifiable label the audit avoids.

### 6.4.2 Artifact- and interface-level obligations

The Article 50 transparency duties beyond the 50(1) disclosure flag — marking
AI-generated content as machine-readable (50(2)), informing persons exposed to
emotion-recognition or biometric systems (50(3)), and labelling deepfake content
(50(4)) — operate on *output artifacts and user interfaces*, not on pipeline
execution. A watermark is a property of a generated image or text file; an
interaction disclosure is a property of the chat surface. These are the natural
domain of a standard like C2PA, which attaches provenance assertions to media
artifacts at the file level (§2.4), and of the application's front end. The
protocol records the one Article 50 fact that *is* a pipeline event — whether a
disclosure was presented (`disclosure_presented`) — and the one that the Human
Intervention Record uniquely substantiates: the 50(4) editorial-responsibility
exemption, established by `action_type: approved` with a `reviewer_role`
(§5.2.2). The boundary is therefore not arbitrary: the protocol owns the Article
50 obligations that are pipeline events and cedes the ones that are artifact or
interface properties to the layers that own those artifacts.

### 6.4.3 The content-storage boundary

A boundary that is not an out-of-scope clause but belongs in the same discussion
is content storage. The bundle stores hashes, not content (§4.8, §1.5): the
digests are commitments, and proving *what* a model said requires the original
message from a separate, access-controlled content store, recomputed and
compared against the record. This is a deliberate non-specification, because
regulated deployments differ widely in how content must be stored — WORM object
storage, an encrypted database, in-memory only with rotating keys — and binding
the protocol to one storage model would make it unusable for deployments with a
different requirement. The operational pattern the protocol assumes is
selective: the tamper-evident bundle goes to the auditor as the chain of events,
the content lives in a store keyed by hash, and on challenge the deployment
reveals the specific content whose digest the auditor recomputes. The PoC does
not *demonstrate* a selective-disclosure deployment — the demos hold content
only transiently in the running process — so this remains a specified boundary
rather than an exercised one, and §6.5.8 notes the content-store integration
that would close it.

## 6.5 Future work

The directions below follow from the limitations and boundaries above. They are
ordered roughly from the most immediate engineering extensions to the most
open-ended research direction.

### 6.5.1 Adapters for further agent frameworks

The most direct extension is *packaged* capture adapters for AutoGen and CrewAI,
the two frameworks PROV-AGENT supports that this PoC does not (§5.5). The
groundwork is in place and already partially demonstrated. The session, bundle,
sealing, and reporting layers are framework-agnostic and reach the capture layer
only through the record factory on `PipelineSession` — `add_agent_step` /
`add_tool_invocation` and their `_error` variants, the `SessionProtocol` seam of
§4.4.3. A new adapter extracts its framework's primitives and calls that factory;
record shape, canonical hashing, and the parent chain are reused unchanged.

Crucially, an adapter need not be a callback middleware. The LangChain adapter is
one because LangChain exposes a passive callback system worth exploiting; where a
framework offers no such hook, instrumentation is inline factory calls at each
model and tool call site. This is not hypothetical: the framework-free demo of
§4.5.5 (`demos/openai_loop/`) is exactly such an adapter, and it seals a valid,
recomputable bundle on the bare core with no framework present. What a packaged
AutoGen or CrewAI adapter adds over that demo is reusable machinery for *its*
framework, not a new path through the protocol.

The open question each adapter answers is therefore not whether the seam
generalises — the framework-free demo shows it does — but whether the target
framework exposes a *passive* extension point comparable to LangChain's callbacks.
Where it does, the non-invasiveness result of §5.4 carries over; where it does
not, capture is more invasive (code at each call site, as in the framework-free
demo) even though the sealed bundle is identical. Non-invasiveness, in other
words, is the property that is framework-specific; the factory seam is not.

### 6.5.2 Canonical identifier rewriting

The preferred resolution to the semantic-projection trade-off (§6.3) is to stop
*stripping* runtime identifiers and instead *canonicalise* them. Walking the
message list and rewriting every `AIMessage.id` and `tool_call_id` to a
deterministic sequence — `0, 1, 2, …` in order of first appearance, with the
same source id always mapping to the same number — keeps the digest replay-stable
exactly as stripping does, but it preserves the tool-call ↔ tool-result
correlation graph *inside* the hashed structure rather than relying on the
implicit list order. This is robust against the cases the current approach
silently mishandles: parallel tool calls within one step, and out-of-order
responses, where implicit-order linkage breaks. It was not adopted in the PoC
because the demos use single-tool-per-step flows where implicit order is
unambiguous, because adopting it would regenerate every committed bundle, and
because it changes no thesis claim — it is a production-grade refinement of an
already-principled approach. A complementary, lighter option is a non-hashed
`runtime_metadata` side field that simply carries the original ids alongside the
record for forensic cross-referencing without entering the digest. The PoC
established the principle; canonical id rewriting is the next step (a v0.2
schema revision).

### 6.5.3 Content-addressed recovery of multi-agent topology

The chronological parent chain (§6.3) under-describes any pipeline whose agents
do not execute in a single line, and the obvious remedy — reading the true
data-flow graph from the orchestrator — would re-couple the capture layer to one
engine's execution model, surrendering the framework-neutral property §6.5.1
works to preserve. LangGraph exposes that structure directly: its superstep
boundaries and per-node channel writes, surfaced through the `updates` and
`debug` stream modes, name exactly which node produced each piece of state and
which downstream node consumed it, and an adapter built on them would
reconstruct the exact directed acyclic graph of agent dependencies. But it would
do so in terms of *supersteps* and *channels* — concepts that exist only inside
LangGraph's Pregel execution model. AutoGen and CrewAI have neither, so a
topology mechanism defined against those primitives would not transfer, and the
protocol's claim to describe pipelines in framework-agnostic terms would hold for
the records but not for the graph that links them.

The reframe that resolves the tension is to derive the topology from observables
the protocol *already records* and that every framework necessarily exposes,
rather than from any engine's private notion of a graph. Two such observables
suffice. First, the `timestamp_start`/`timestamp_end` pair on every record makes
concurrency directly detectable: two records whose intervals overlap demonstrably
ran in parallel, which is enough to *refuse* the false sequential edge the
chronological cursor would otherwise assert — truthful under-description in place
of a confident error. Second, and more powerfully, the content commitments
`input_hash` and `output_hash` make data-flow edges recoverable by content
addressing: if the content one record produced is the content another consumed, a
real dependency edge between them exists, derivable from content identity alone
with no reference to how the orchestrator routed it. This is the principle by
which content-addressed build systems and version-control graphs reconstruct
dependency structure without any scheduler naming the edges, and it reuses the
hashing machinery the protocol already depends on (§4.5). Engine-native
introspection then changes role: instead of the *source* of the graph,
LangGraph's channel writes become an optional *accelerator* that auto-populates
the same produced/consumed artifact relation for the one framework that exposes
it cheaply, while content matching remains the portable fallback for every
framework that does not. The topology is defined by content, not by the engine;
the adapter's only task is to populate the artifact relation by whatever means it
has — content matching (universal), engine introspection (exact, framework-
specific), or a thin application-level annotation in the spirit of the
`HumanReview` block (§4.11), where the integrator names a consumed artifact in a
line or two when automated matching cannot.

The honest obstacle is that the present digests are computed over the whole
projected message list for a step (§4.5.1), so an upstream `output_hash` will
rarely equal a downstream `input_hash` verbatim once the producing content has
been reformatted into a new prompt. Realising content-addressed topology
therefore requires moving from whole-message digests to artifact-level ones —
hashing the discrete pieces of content that flow between steps so a produced
artifact can be matched *within* a later consumed set despite the surrounding
prompt differing — together with light normalisation to survive templating, and
the annotation escape hatch above for the cases where an agent transforms content
beyond recognition rather than passing it through. The result is a directed
acyclic provenance graph recovered from content and time rather than from a
scheduler, which subsumes the optional `caused_by_record_id` field of §3.7.3 —
the matched producer becomes the causal parent — and generalises beyond LangGraph
to any pipeline that moves content between steps. It is noted here, rather than
built, because it reaches past the linear demonstrations the evaluation exercises
and is a research direction in its own right: framework-agnostic, content-
addressed multi-agent provenance.

### 6.5.4 Cryptographic signing and trusted timestamping

The authenticity gap identified in §6.2.2 is closed by signing. A digital
signature over `bundle_hash` by a key the deployer controls binds the bundle to
its producer and converts tamper-*evidence* into non-repudiable attestation: an
auditor verifies not only that the bundle is internally consistent but that it
was sealed by the claimed party and not fabricated by a third one. Pairing the
signature with a timestamp from a trusted timestamping authority (RFC 3161)
additionally binds the seal to a point in time, which matters for an oversight
record whose evidentiary value depends on *when* the human decision was attested.
The protocol already produces the canonical, stable byte form that such a
signature must sign — this is why RFC 8785 canonicalisation was chosen over an
ad-hoc serialisation — so the extension is additive: a signature envelope around
the existing seal, not a change to the records. The harder, deployment-specific
question is key management and the chain of trust for the signing key, which is
why the PoC stops at the integrity layer.

### 6.5.5 Deployment-profile schema variants

Article 14(5)'s two-person rule (§6.3) is one instance of a general need:
obligations that apply to a *sub-population* of pipelines rather than all of
them. The base schema enforces what every pipeline must satisfy (`minItems: 1`
on `reviewer_id`); a *deployment profile* would be a schema that extends the base
with the tighter constraints a specific regulatory population requires
(`minItems: 2` for biometric identification systems), without imposing them on
pipelines outside that population. This keeps the core protocol minimal while
letting a deployment opt into a stricter, mechanically-enforced variant matched
to its risk class — the same pattern by which profiles specialise a base
standard elsewhere. The validation surface (§4.12) already centralises
constraint checking, so a profile is a parameterisation of an existing seam
rather than a new mechanism.

### 6.5.6 Graph-interrupt human-intervention capture

The document-review demonstration already expresses its human review points as
node-level `interrupt()` gates inside a single multi-node graph (§4.11.2): the
graph pauses at each gate and resumes around the `HumanReview` block, so the
human decision point lives in the graph definition rather than being sequenced
externally by the runner. What remains is the last seam: because the human
decision occurs out of process while the graph is paused, the Human Intervention
Record is still emitted by the runner on resume rather than from inside the gate
node. Folding the emission into the resume path — so the gate node and its record
are one unit — would make the human decision a fully first-class part of the
pipeline structure and model the interrupt-and-resume oversight flow end to end.
The record it produces is identical either way, which is why emitting it from the
runner is sufficient to validate the protocol.

### 6.5.7 Recording oversight failures

The Agent Step and Tool Invocation Records now record their failures: a call that
raises is captured with `status: "error"` and a structured `error` object, so a
malfunction in the automated layer is auditable (§3.3.2, Article 12(2)(a)). The
Human Intervention Record has no equivalent. By construction it is emitted only
when a reviewer commits a decision, and `action_type` is its outcome axis (§3.5.3);
a *technical* failure of oversight — a reviewer who times out, is unavailable, or a
review system that crashes before any decision is reached — currently raises in the
host application and produces no record, leaving the failed oversight invisible in
the bundle.

This is the oversight-layer analogue of the gap the per-step `status` field closed,
and "oversight was required but did not engage" is a first-class Article 14 signal.
The reason it was not simply folded into the Human Intervention Record is that a
failed review shares almost none of that record's shape — there is no committed
`action_type`, no `output_after_hash`, and often no reviewer at all — so attaching a
`status` field would make most of the core-novelty record conditionally absent and
blur the before/after decision evidence that is its contribution. The cleaner
direction is a distinct *oversight-failure* event (capturing the assigned reviewer
or reviewer pool, the output awaiting review, the failure mode, and a timestamp),
chained to the upstream record exactly as a Human Intervention Record is, so that a
bundle can show "oversight was due here and did not happen" without overloading the
record that models oversight that did.

### 6.5.8 Content-store integration and selective disclosure

The content-storage boundary (§6.4.3) is specified but not demonstrated. A
natural next step is a reference content-store adapter — a hash-keyed store with
access control and a challenge/response interface — paired with a demonstration
that exercises the full selective-disclosure pattern end to end: bundle to
auditor, content held under access control, a specific output revealed on
challenge and its digest recomputed against the record. This would turn the
content-addressable property from a specified capability into a demonstrated one
and would let the threat-model claims of §6.2 be evaluated against an actual
retention-and-disclosure deployment rather than argued analytically.

### 6.5.9 Behavioural constraint declaration

The most open-ended direction, and one deliberately kept out of this thesis's
scope, is a formal, machine-readable declaration of what an agent is *not*
allowed to do. Capability declaration is a solved-enough problem — A2A Agent
Cards and MCP tool schemas describe what an agent *can* do — but there is no
standard counterpart for verifiable *prohibitions*: the constraints an agent
must provably never violate. This is distinct from provenance: where the present
protocol produces *post-hoc evidence* of what a pipeline did, a constraint
declaration would be a *prior specification* of what it must not do, against
which the provenance record could then be checked. The two compose naturally — a
behavioural constraint schema states the rule, the provenance bundle supplies the
evidence to audit it — and the combination points toward provenance that is not
merely descriptive but *verifiable against a declared policy*. Developing that
schema, and the relationship between a prohibition language and the EU AI Act's
risk-management obligations, is a research programme in its own right and is
noted here as the principal direction this work opens rather than one it begins
to answer.

## 6.6 Concluding remarks

This thesis set out to close a specific gap: existing provenance work captures
what the automated parts of an AI pipeline do, but no standard models the human
oversight events that the EU AI Act makes central, nor maps a provenance record
to the regulation's obligations. The protocol answers RQ1 with four versioned,
schema-validated record types and a clause-by-clause mapping; RQ2 with the Human
Intervention Record and its before/after override evidence, the contribution that
distinguishes this work from PROV-AGENT; and RQ3 with a non-invasive LangGraph
implementation whose overhead is negligible against real model latency and whose
instrumentation cost is near-constant. The completeness audit found no uncovered
in-scope clause.

The discussion above is the measure of how far that result reaches and where it
stops. The bundle is tamper-evident but not yet self-authenticating; the parent
chain records order, not causation; the capture layer is proven for one
framework; and the obligations that live in application logic, output artifacts,
and user interfaces are ceded, explicitly, to the layers that own them. None of
these is a flaw concealed by the evaluation — each is a named boundary with a
defined next step, from signing and canonical identifier rewriting to
deployment-profile schemas and, most openly, a verifiable language for the
behaviour an agent must never exhibit. The protocol establishes the evidentiary
substrate for regulated multi-agent provenance, including the human-oversight
record the regulation demands and prior work omits; turning that substrate into
a fully attested, multi-framework, policy-verifiable compliance layer is the work
it makes possible.
