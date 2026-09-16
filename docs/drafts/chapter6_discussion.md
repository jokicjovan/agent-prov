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
content-addressed recovery of multi-agent topology, cryptographic signing,
deployment-profile schemas, and a machine-readable declaration of behavioural
constraints (§6.5).
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
*on its own* bind the bundle to the party that produced it, and it does not stop a
malicious producer from generating a wholly fabricated-but-consistent bundle
after the fact. Closing this gap requires a digital signature over `bundle_hash`
by a key the deployer controls, and ideally a trusted timestamp. The
implementation now ships the first of these as an optional detached signature
layer (`agent_prov.signing`, §6.5.4): a deployment that opts in binds the seal to
a signing key, so the unkeyed-recompute attack above no longer produces a valid
bundle. The bare protocol core remains unsigned by design — signing is an opt-in
layer over the canonical seal, not a property of every bundle — and trusted
timestamping remains future work.

**The chain proves order, not causation, and not completeness.** As recorded in
§4.13 and §3.7.3, `parent_record_id` is a chronological cursor — it links each
record to its immediate predecessor in emission order, not to the record that
*caused* it. A verifier can reconstruct the sequence of observed events but
cannot, from the chain alone, prove that a given tool call was issued *by* a
given agent step. What the verifier now *does* guard against is the chain's most
misleading failure — silently presenting a parallel region as a straight line:
it derives concurrency from the execution intervals every record already carries
and warns wherever two records overlap in time, so the chronological ordering is
flagged as an approximation rather than trusted as sequence (§6.3). This is
detection, not reconstruction; recovering the actual data-flow graph remains the
content-addressed direction of §6.5.3. Separately, the seal proves nothing about records that were
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
produce a chain that under-describes its true structure. This limitation is now
*partially* mitigated: the independent verifier derives concurrency from the
`timestamp_start`/`timestamp_end` interval on every record — grouping any set of
overlapping intervals into a concurrent cluster and emitting a non-fatal warning
— so the false sequential edge is *detected and reported* rather than silently
asserted. Crucially this stays framework-neutral, reading only observables the
records already carry rather than any engine's execution model, and it is a
warning rather than an error because a parallel pipeline is a valid, untampered
bundle the chronological cursor merely under-describes. What remains is
*reconstruction* rather than detection: the defined resolutions are an optional
`caused_by_record_id` field (§3.7.3), deferred because the demos do not exercise
the case it solves, and a fuller treatment that recovers the causal topology from
content and timestamps — developed in §6.5.3.

**Semantic projection of identifiers.** `input_hash` and `output_hash` are
computed over a projection of the LangChain message list rather than the raw
messages, because LangChain stamps a fresh runtime identifier on every generated
message and tool call and hashing those would re-randomise the digest on every
replay (§4.5.1). The projection does not simply discard those identifiers: the
ones that carry *correlation* — a tool call's id and the `tool_call_id` on the
`ToolMessage` that answers it — are rewritten to deterministic per-scope labels
(`0, 1, 2, …`), so the tool-call ↔ tool-result edge is preserved *inside* the
hashed structure and survives parallel or out-of-order tool calls (§4.5.6). The
real runtime identifiers are not lost either: they are preserved in a non-hashed
`runtime_metadata` side field, so a record can still be cross-referenced against
the provider's request log or the framework's execution trace. One narrow
residual remains: `runtime_metadata` sits outside the content hashes — it is
covered by the `bundle_hash` seal, so it is tamper-evident, but it is not part of
the replay-stable content commitment — and the free-standing response id is
preserved only there rather than folded into the digest, a deliberate choice
since it correlates with nothing inside a step and is not reliably present across
runs (§6.5.2).

**Runner-emitted HITL record.** The document-review demonstration expresses its
human review points as node-level `interrupt()` gates inside a single multi-node
graph (§4.11.2), which is the idiomatic LangGraph form. One seam remains:
because the human decision occurs out of process while the graph is paused, the
`HumanReview` record is emitted by the runner on resume rather than from inside
the gate node itself. The record produced is identical either way; folding the
emission into the resume path, so the gate node and its record are one unit, is
the refinement noted in §6.5.6.

**Article 14(5) is conditionally enforced, not unconditionally guaranteed.** The
two-person rule for biometric identification systems is now *enforced* rather than
merely accommodated: a bundle declaring `oversight_regime: "biometric_dual_control"`
cannot be sealed unless every Human Intervention Record carries at least two
distinct reviewers (§3.7.4, §5.2.2). What remains is that the trigger is a
*self-declared* field: `reviewer_id` still keeps a universal `minItems: 1`, because
the second reviewer is required only for the biometric population, and it is the
run's own declaration that opts it into the stricter rule. A producer under a 14(5)
obligation could therefore under-declare the regime and escape the check — but this
is the general emission-time trust boundary of §6.2.3, not specific to this field
(the same producer could fabricate a second `reviewer_id`), and it is mitigated by
the declaration being sealed and signable and so attributable after the fact. The
part that is genuinely out of the record stream's reach — proving a run *belongs*
to the biometric population regardless of what it declares — needs an external,
registered notion of system type, discussed as future work in §6.5.5.

**The durability log is operational, not evidential.** The optional event log
(§4.7.1) closes the window in which an unsealed run lives only in process memory,
but it is deliberately a recovery aid rather than a second evidentiary artefact:
it is plain JSON, carries no integrity hash of its own, and is trusted only to
the extent the host's filesystem is. Its guarantee is "a record `add_record`
accepted is on disk", not "this log was not tampered with" — the tamper-evidence
and tamper-proof properties belong to the sealed bundle and its signature
(§6.2), which a recovered run is put through unchanged. Three operational
boundaries remain a deployment's responsibility: the log grows unbounded within a
run (no segment rotation or compaction), a single session writes a single log
from scratch (resuming an existing log across a process restart is not modelled),
and the log is not itself signed. None of these affect the evidentiary force of
the bundle a recovered session produces; they are the difference between a
proof-of-concept durability layer and a production log subsystem.

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

### 6.5.2 Extending identifier canonicalisation

The semantic-projection trade-off of §6.3 was resolved during the work of this
thesis, and the resolution is now part of the reference implementation (§4.5.6)
rather than a future direction. Instead of stripping runtime identifiers, the
projection canonicalises the *correlating* ones — each tool call's id and the
answering `ToolMessage`'s `tool_call_id` — rewriting them to a deterministic
`0, 1, 2, …` sequence in order of first appearance within a projection scope,
with the same source id always mapping to the same label. This keeps the digest
replay-stable exactly as stripping did, but preserves the tool-call ↔
tool-result correlation graph *inside* the hashed structure rather than relying
on implicit list order, so it is robust against the cases stripping silently
mishandled: parallel tool calls within one step, and out-of-order responses. The
complementary `runtime_metadata` side field (§4.5.6) carries the original ids —
the framework run id, the provider response id, and the label-to-real-id map for
the tool calls — alongside the record, unhashed, for forensic cross-referencing.
This closed a breaking change into the schema, taken as the `0.2.0 → 0.3.0`
version bump.

Two narrower extensions remain open. First, the free-standing response id
(`AIMessage.id`) is currently kept out of the digest and preserved only in
`runtime_metadata`, because it correlates with nothing inside a step and is not
reliably present across runs; folding a canonicalised form of it into the hash
would close the last gap between the hashed structure and the raw message set, at
the cost of that fragility. Second, `runtime_metadata` is covered by the bundle
seal but is not itself independently attested or timestamped; a deployment that
needs the forensic side channel to carry the same evidentiary weight as the
content commitments would pair it with the signing and timestamping layer of
§6.5.4.

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
of a confident error. This first observable is no longer prospective: the
independent verifier (§4.8.1) implements exactly this check, grouping
overlapping-interval records into concurrent clusters and reporting each as a
non-fatal warning, so the false sequential edge is already detected and surfaced
to an auditor. What follows in this section is therefore the *reconstruction*
half — turning that detection into an actual data-flow graph — which remains
future work. Second, and more powerfully, the content commitments
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

The authenticity gap identified in §6.2.2 is closed by signing, and the
implementation now provides it as an optional layer. A digital signature over
`bundle_hash` by a key the deployer controls binds the bundle to its producer and
converts tamper-*evidence* into non-repudiable attestation: an auditor verifies
not only that the bundle is internally consistent but that it was sealed by the
claimed party and not fabricated by a third one. The `agent_prov.signing` package
(behind the `agent-prov[signing]` extra, so the protocol core stays crypto-free)
implements this as a *detached* envelope rather than a field inside the bundle,
keeping the record set byte-stable and independently hashable. Following
established provenance-signing practice (in-toto / SLSA / DSSE / Sigstore), it
uses an asymmetric scheme (Ed25519) so a verifier needs only the public key, and
it signs a *bound* payload — `{payload_type, algorithm, signed_hash}`
canonicalised through the same RFC 8785 path used for the seal — rather than the
bare digest, so a signature cannot be lifted and replayed in another context.
This is also why RFC 8785 canonicalisation was chosen over an ad-hoc
serialisation: the signature is additive, an envelope around the existing seal,
not a change to the records.

Two things remain genuinely future work. First, *trusted timestamping*: pairing
the signature with a timestamp from a timestamping authority (RFC 3161) binds the
seal to a point in time, which matters for an oversight record whose evidentiary
value depends on *when* the human decision was attested. Second, the
*chain of trust* for the signing key: the PoC envelope self-describes its public
key (trust on first use), which proves a bundle was signed by *some* key but not
*whose* — production use needs a certificate chain or a transparency log
(Sigstore/Rekor-style) to anchor key identity. The signing layer deliberately
stops at the cryptographic primitive and names key management as the next step.

### 6.5.5 Sub-population obligations and external regime attestation

Article 14(5)'s two-person rule is the first instance of a general need:
obligations that apply to a *sub-population* of pipelines rather than all of them.
It is now met in-protocol (§3.7.4): the base schema keeps what every pipeline must
satisfy (`minItems: 1` on `reviewer_id`), and a run opts into the stricter rule by
declaring `oversight_regime: "biometric_dual_control"` on its bundle, which the
existing validation surface enforces at seal time. Because the trigger is a
declared field checked in the surface that already centralises constraint checking
(§3.7.5), adding further population-specific rules is a parameterisation of that
seam rather than a new mechanism — new regimes, or the alternative of a *deployment
profile* (a schema variant that structurally tightens the base for one population),
both extend the same point. That generalisation is the lighter half of the
remaining work.

The harder half is the residual identified in §6.3: the regime is *self-declared*,
so the enforcement holds only for a run that honestly opts in. Closing it means
binding the declaration to something the producer does not unilaterally control —
an external, registered notion of what kind of system this is, against which the
declared `oversight_regime` can be cross-checked. This is the same shape as the
completeness problem of §6.2.2 (detecting an omitted record also needs an external
expectation of what the pipeline should have produced) and reduces, like the
signing and timestamping directions of §6.5.4, to attestation and registration
infrastructure that sits outside the record stream. The protocol's part — carrying
the declaration inside the tamper-evident, signable bundle so a mis-declaration is
recorded and attributable — is built; the external source of truth that would make
under-declaration detectable rather than merely attributable is the future work.

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
defined next step, from signing and content-addressed topology recovery to
deployment-profile schemas and, most openly, a verifiable language for the
behaviour an agent must never exhibit. The protocol establishes the evidentiary
substrate for regulated multi-agent provenance, including the human-oversight
record the regulation demands and prior work omits; turning that substrate into
a fully attested, multi-framework, policy-verifiable compliance layer is the work
it makes possible.
