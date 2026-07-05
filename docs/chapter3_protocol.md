# Chapter 3 — Protocol Design

## 3.1 Scope of this chapter

This chapter specifies the AI Agent Provenance & Compliance Protocol. It describes four record types — Agent Step, Tool Invocation, Human Intervention, and Pipeline Bundle — and the conventions that govern how they are produced, ordered, and sealed. For each record type the chapter gives the rationale for its existence, a field-by-field table including the type, optionality, and the EU AI Act clause the field discharges, and a worked JSON example.

The chapter does not specify a wire format beyond JSON, a transport layer, or a storage backend. It does not specify how records are signed by an external authority; the only integrity guarantee at the protocol layer is the in-bundle `bundle_hash`. Signing, retention, and access control are out of scope; they belong to the deployment that wraps the protocol.

The chapter closes with a unified field-to-clause mapping table (§3.8) and a short statement of what the protocol deliberately leaves to the application layer (§3.9).

The canonical machine-readable definitions live in `src/agent_prov/schemas/*.schema.json`. The tables in this chapter and the schemas are kept in sync; when they disagree, the schemas are authoritative.

---

## 3.2 Design decisions

Several decisions cut across all four record types. They are stated here once so the per-record sections can refer back without restating the rationale.

**JSON Schema 2020-12 as the specification language.** The schemas are written against draft 2020-12 of JSON Schema. This is the most recent stable draft with broad implementation support and gives access to `$defs`, `oneOf` discriminated by `const`, and cross-schema `$ref`. The choice constrains what conditional rules are expressible in the schema itself: in particular, "field A's value depends on field B's value" patterns of the kind required by the Human Intervention Record's `action_type` semantics. Where such rules are not expressible, they are stated in the schema description and enforced by the protocol's validation surface at bundle seal time (§3.7.5).

**`additionalProperties: false` on every record.** Every record schema closes its property set. Unknown fields are rejected. This is a deliberate strictness: the protocol's value as compliance evidence depends on a predictable shape, and accepting unknown fields silently would allow records to drift across implementations without breaking validation. Adding a new field is a `protocol_version` bump, not a permissive extension.

**`record_type` as a `const` discriminator.** Every record carries a fixed `record_type` value — `"agent_step"`, `"tool_invocation"`, `"human_intervention"`, or `"pipeline_bundle"`. Validators and downstream tooling dispatch on this field without inspecting other fields. The Pipeline Bundle's `records` array uses `oneOf` against the three record-type schemas; the discriminator makes the union unambiguous.

**`protocol_version` (semver) on every record.** Each record stamps the protocol version it was produced under. Bumping the major version is the path for any breaking field change. Consumers can therefore detect mixed-version bundles and reject them at ingestion. The reference implementation defaults to `"0.4.0"`.

**Lowercase canonical hex for all hex-encoded fields.** UUIDs and SHA-256 digests are emitted as lowercase hex strings, validated by a pattern at the schema level. This avoids the situation in which two equivalent records produce different canonical-JSON serialisations because one used uppercase and the other lowercase hex, which would in turn produce different bundle hashes.

**SHA-256 as the only hash algorithm.** All content hashes (`input_hash`, `output_hash`, `output_before_hash`, `output_after_hash`, optional `justification_hash`) and the bundle integrity hash (`bundle_hash`) are SHA-256. SHA-256 is the FIPS 180-4 algorithm with the broadest implementation support across languages and operating systems. The protocol does not currently allow algorithm negotiation; a future major version may add an algorithm-identifier prefix should NIST deprecate SHA-256 for new use.

**Canonical JSON before hashing.** Any object that is hashed is first serialised as canonical JSON following RFC 8785, the JSON Canonicalisation Scheme (JCS): keys sorted lexicographically by Unicode code point, no insignificant whitespace, UTF-8 encoded, non-ASCII characters preserved (not `\uXXXX`-escaped), and ECMAScript number formatting so that semantically equal numbers — for example `1.0` and `1` — serialise to identical bytes. The reference implementation in `agent_prov/_hashing.py` delegates canonicalisation to the `rfc8785` library rather than hand-rolling it. Because the scheme is a published standard, any independent verifier using a conformant JCS implementation reproduces a digest byte-for-byte, without having to match an implementation-specific number-formatting quirk.

**Hashes, not raw content, by default.** The protocol stores SHA-256 digests of prompts, tool inputs, model outputs, tool outputs, and reviewer rationale. The raw content remains in application storage. This decision serves two purposes: it satisfies the GDPR data-minimisation principle for deployments that process personal data, and it gives the record set a fixed-size footprint independent of prompt or response length. The application-layer storage that holds the raw content is what links the hash back to its preimage; the protocol records the hash as the immutable evidence that a specific input was processed.

**Universal application of the Art. 12(3) biometric minimums.** Article 12(3) of the EU AI Act specifies record-content minimums for biometric identification systems only. The protocol applies those minimums — start and end timestamps, reference data identifier, input hash, reviewer identity — to every record type. A protocol that meets the biometric floor on every record is straightforwardly compliant for biometric pipelines and over-compliant (harmlessly) for the rest. This decision avoids profile-specific schemas and keeps the record set uniform across deployment classes.

---

## 3.3 Agent Step Record

### 3.3.1 Rationale

The Agent Step Record captures one execution of an LLM agent node within a pipeline. It is the protocol's analogue of PROV-AGENT's `AIModelInvocation` and discharges the bulk of the Article 12 record-keeping obligations for the automated portion of a pipeline run.

An agent step is delimited by the start and end of a single chat-model call. A LangGraph node that issues multiple model calls produces multiple Agent Step Records; a node that issues no model call produces none. This grain matches the EU AI Act's framing of "events" as discrete model interactions rather than coarser pipeline activities.

### 3.3.2 Fields

| Field | Type | Required | EU AI Act clause |
|-------|------|----------|------------------|
| `record_id` | UUID | yes | metadata |
| `record_type` | const `"agent_step"` | yes | metadata |
| `protocol_version` | semver string | yes | metadata |
| `pipeline_id` | UUID | yes | 12(2)(c) |
| `session_id` | UUID | yes | 12(2)(c) |
| `agent_id` | non-empty string | yes | 12(2)(c) |
| `model_id` | non-empty string | yes | 12(2)(b), 14(4)(a) |
| `model_version` | non-empty string | yes | 12(2)(b), 14(4)(a) |
| `timestamp_start` | ISO 8601 / RFC 3339 | yes | 12(3)(a) |
| `timestamp_end` | ISO 8601 / RFC 3339 | yes | 12(3)(a) |
| `input_hash` | SHA-256 hex | yes | 12(3)(c) |
| `status` | `"success"` or `"error"` | yes | 12(2)(a) |
| `output_hash` | SHA-256 hex | only when `status` is `"success"` | 12(2)(c) |
| `error` | error object | only when `status` is `"error"` | 12(2)(a) |
| `reference_data_id` | string or `null` | yes (nullable) | 12(3)(b) |
| `parent_record_id` | UUID or `null` | yes (nullable) | 12(2) traceability |
| `runtime_metadata` | object | no (optional) | metadata (forensic) |

`status` is a required, explicit discriminator of the step's outcome, so a record is interpretable without reference to the protocol version that produced it. On `"success"` the `output_hash` field is present and `error` is absent; on `"error"` the step produced no output, so `output_hash` is absent and `error` carries the failure detail. Recording failures — not only successful steps — is what discharges Article 12(2)(a), which calls for logging events relevant to identifying situations in which the system may present a risk, including malfunctions. The presence rules bind two field values and so are enforced at the validation surface rather than in JSON Schema (§3.7).

The `error` object has one required member, `type` (the exception class name, e.g. `"TimeoutError"` — a low-PII identifier suitable for an audit trail), and three optional members: `message_hash` (SHA-256 of the error message, hashed for the same data-minimisation reason as `input_hash`/`output_hash`), `source` (the component at whose boundary the failure surfaced — `"provider"`, `"tool"`, `"network"`, `"middleware"`, or `"unknown"`), and `retryable` (whether the failure is transient, when the deployment can determine it).

`agent_id` is a free-form non-empty string rather than a UUID. An agent in a multi-agent pipeline is identified by its role in the graph (`"researcher"`, `"summarizer"`, `"writer"`), and these names are stable and human-meaningful across runs. A UUID here would lose information without adding any.

`model_id` and `model_version` are separated because they decay at different rates. A deployment may pin to `claude-opus-4-7` for months while the specific snapshot served behind that identifier rotates. Post-market monitoring under Article 72 requires the granularity of both. Where a provider does not expose a distinct version string, the reference implementation falls back to using the model identifier as both fields; this is degenerate but well-formed.

`reference_data_id` is nullable because not every model call consults a reference corpus. For retrieval-augmented generation, this field carries the version identifier of the consulted corpus and discharges Article 12(3)(b). For a model call that operates solely on its parameters, this field is `null`.

`parent_record_id` is the `record_id` of the immediately preceding record in the bundle, or `null` for the first record. It establishes the structural chain of custody referenced by Article 12(2) traceability. The chain is chronological, not causal; §3.7.3 discusses this in more detail.

`runtime_metadata` is an optional, non-hashed side field. The content hashes are computed over a projection of the messages that rewrites the runtime tool-call identifiers to deterministic labels and omits the free-standing message id, so that identical content digests identically across replays (§4.5.6); the raw identifiers the projection removes are preserved here instead — the framework `run_id`, the provider's response `message_id`, and a map from each canonical tool-call label to the real `tool_call_id` — so a record can still be cross-referenced against the provider's request log or the framework's execution trace. It is excluded from `input_hash` and `output_hash` (keeping those replay-stable) but covered by the bundle's `bundle_hash` seal, so its values are tamper-evident. The object is open — an implementation may add framework-specific identifiers — and is omitted entirely when it would be empty.

### 3.3.3 Example

```json
{
  "record_id": "c841bdac-d615-44bf-8db9-c941c1d58551",
  "record_type": "agent_step",
  "protocol_version": "0.4.0",
  "pipeline_id": "8d3fecf8-42d6-4f45-824f-7dde23407026",
  "session_id": "3174f399-0c98-4779-912d-ada24e61d126",
  "agent_id": "researcher",
  "model_id": "claude-opus-4-7",
  "model_version": "20260101",
  "timestamp_start": "2026-05-12T09:51:26.825990Z",
  "timestamp_end": "2026-05-12T09:51:26.826783Z",
  "input_hash": "2463dde6d2c54c083a2d531b5d6d989f722bde7ab72b10a4d2b07c48e43cf457",
  "status": "success",
  "output_hash": "102900748cf7170b814b19c74e79183a190bbcc4311629cc166cf1fd550075fe",
  "reference_data_id": null,
  "parent_record_id": "d77ab248-29bf-4933-92c4-8b11017a592a",
  "runtime_metadata": {
    "run_id": "019f2a71-3a47-7523-b82d-7e14aee7b14a",
    "message_id": "lc_run--019f2a71-3a47-7523-b82d-7e14aee7b14a-0"
  }
}
```

A failed step instead carries `"status": "error"`, no `output_hash`, and an `error` object — for example `"error": {"type": "TimeoutError", "message_hash": "…", "source": "provider"}`.

A `timestamp_end >= timestamp_start` ordering constraint compares two field values, which no JSON Schema draft can express; it is enforced by the protocol's validation surface alongside structural schema validation (§3.9).

---

## 3.4 Tool Invocation Record

### 3.4.1 Rationale

The Tool Invocation Record captures one tool or function call made by an agent. Tool calls are the channel through which an LLM agent interacts with the world: web searches, database queries, code execution, retrieval, calculator use. The protocol treats them as first-class events, not as attributes of the agent step that issued them, because tool calls are independently auditable: a single agent step may dispatch several tool calls in parallel, and the same tool may be invoked from multiple agent steps in the same run.

The structural symmetry with the Agent Step Record is intentional. Both records describe a bounded activity (start time, end time), carry hashes of input and output, identify a stable artefact (`model_id` / `model_version` for one, `tool_name` / `tool_version` for the other), and attribute the activity to an agent.

### 3.4.2 Fields

| Field | Type | Required | EU AI Act clause |
|-------|------|----------|------------------|
| `record_id` | UUID | yes | metadata |
| `record_type` | const `"tool_invocation"` | yes | metadata |
| `protocol_version` | semver string | yes | metadata |
| `pipeline_id` | UUID | yes | 12(2)(c) |
| `session_id` | UUID | yes | 12(2)(c) |
| `agent_id` | non-empty string | yes | 12(2)(c) |
| `tool_name` | non-empty string | yes | 12(2)(c) |
| `tool_version` | non-empty string | yes | 12(2)(b) |
| `timestamp_start` | ISO 8601 / RFC 3339 | yes | 12(3)(a) |
| `timestamp_end` | ISO 8601 / RFC 3339 | yes | 12(3)(a) |
| `input_hash` | SHA-256 hex | yes | 12(3)(c) |
| `status` | `"success"` or `"error"` | yes | 12(2)(a) |
| `output_hash` | SHA-256 hex | only when `status` is `"success"` | 12(2)(c) |
| `error` | error object | only when `status` is `"error"` | 12(2)(a) |
| `reference_data_id` | string or `null` | yes (nullable) | 12(3)(b) |
| `parent_record_id` | UUID or `null` | yes (nullable) | 12(2) traceability |
| `runtime_metadata` | object | no (optional) | metadata (forensic) |

`status`, `output_hash`, and `error` behave exactly as on the Agent Step Record (§3.3.2): `status` is a required explicit outcome discriminator, `output_hash` is present only on success, and the `error` object (required `type`, optional `message_hash`/`source`/`retryable`) is present only on failure. A tool call that raises is recorded with `"status": "error"` and `"source": "tool"`, discharging Article 12(2)(a) for the tool layer.

`tool_name` is a free-form non-empty string and serves the same identifier role as `agent_id` and `model_id`: a stable, human-meaningful handle. `tool_version` is required even when no formal version exists; deployments must commit to *some* version string (a git SHA, an API version, the literal `"unversioned"`) so that drift across pipeline runs is detectable in the record set.

`reference_data_id` for a tool invocation captures the version of any external corpus or API surface the tool consulted: a retrieval corpus, an external knowledge base, a third-party API version pin. `null` when the tool has no such reference data, for example a pure-function calculator.

`runtime_metadata` is the same optional, non-hashed forensic side field defined on the Agent Step Record (§3.3.2). A tool call has no message or tool-call identifiers of its own to project, so the reference implementation records only the framework `run_id` here; the field remains open for deployment-specific identifiers and is omitted when empty.

### 3.4.3 Example

```json
{
  "record_id": "d77ab248-29bf-4933-92c4-8b11017a592a",
  "record_type": "tool_invocation",
  "protocol_version": "0.4.0",
  "pipeline_id": "8d3fecf8-42d6-4f45-824f-7dde23407026",
  "session_id": "3174f399-0c98-4779-912d-ada24e61d126",
  "agent_id": "researcher",
  "tool_name": "web_search",
  "tool_version": "1.4.0",
  "timestamp_start": "2026-05-12T09:51:26.824062Z",
  "timestamp_end": "2026-05-12T09:51:26.825252Z",
  "input_hash": "43db217faadadc58f3abec361efa0164ff518e9be78233ba677e8e2e5eed8baa",
  "status": "success",
  "output_hash": "a6ff9c0630131ec5f0417e6b2dee03e864f2dd81d76d3c4a93a6de6308cdd773",
  "reference_data_id": null,
  "parent_record_id": null,
  "runtime_metadata": {
    "run_id": "019f2a71-3a45-7a71-9b6c-f4b4e7adec5f"
  }
}
```

---

## 3.5 Human Intervention Record

### 3.5.1 Rationale — the core novelty

The Human Intervention Record is the protocol's central contribution. It models a single human oversight decision point in a multi-agent pipeline and is the field-level mechanism by which the protocol discharges Article 14 of the EU AI Act.

As established in §2.6, no existing AI provenance standard models human oversight events. PROV-AGENT records human association at the campaign level but provides no record type for an oversight act; PROV-DfA models human action but treats the human as the actor whose work is recorded, not as the supervisor whose approval, rejection, or override constitutes regulatory evidence. The Human Intervention Record fills the gap by capturing, at minimum: who reviewed (`reviewer_id`), in what role (`reviewer_role`), what they decided (`action_type`), the state of the output they saw (`output_before_hash`), the state they committed downstream (`output_after_hash`), and when (`intervention_timestamp`).

The semantic structure that distinguishes this record from any prior standard is the *before/after pair*. To prove that a human had the ability to override an agent output — Article 14(4)(d) — the record must capture both the input to the decision and its result. A record that captures only the reviewer's action without the before/after state proves attendance, not authority. The protocol commits to before/after as required structure.

### 3.5.2 Fields

| Field | Type | Required | EU AI Act clause |
|-------|------|----------|------------------|
| `record_id` | UUID | yes | metadata |
| `record_type` | const `"human_intervention"` | yes | metadata |
| `protocol_version` | semver string | yes | metadata |
| `pipeline_id` | UUID | yes | 12(2)(c) |
| `session_id` | UUID | yes | 12(2)(c) |
| `reviewer_id` | non-empty array of non-empty strings | yes (min 1, unique) | 12(3)(d), 14(5) |
| `reviewer_role` | non-empty string | yes | 50(4) exception |
| `action_type` | enum: `approved`, `rejected`, `edited`, `escalated` | yes | 14(4)(d), 14(4)(e), 50(4) exception |
| `output_before_hash` | SHA-256 hex | yes | 14(4)(c) |
| `output_after_hash` | SHA-256 hex or `null` | yes (nullable per `action_type`) | 14(4)(d) |
| `intervention_timestamp` | ISO 8601 / RFC 3339 | yes | 14(4)(e) |
| `justification_hash` | SHA-256 hex | optional | 14(4)(c) |
| `parent_record_id` | UUID | yes (non-null) | 12(2) traceability |

Two structural choices warrant note.

`reviewer_id` is an array, not a single string. Article 14(5) requires that for biometric identification systems "no decision shall be taken unless verified and confirmed by at least two natural persons." Modelling reviewer identity as a single value would force biometric deployments either to overload the field with a delimited string or to maintain a parallel record. An array is uniform, lets the protocol enforce `minItems: 1` at the base schema, and allows a biometric profile (§3.7.4) to tighten the constraint to `minItems: 2` without a schema fork.

`parent_record_id` is required and non-null on the Human Intervention Record, in contrast to its nullable form on Agent Step and Tool Invocation Records. A Human Intervention Record always reviews an upstream record (an Agent Step Record or a Tool Invocation Record); it cannot be the first record in the bundle. The schema enforces this asymmetry directly.

### 3.5.3 `action_type` semantics and the before/after pair

The four `action_type` values bind to specific shapes of the `output_before_hash` / `output_after_hash` pair:

| `action_type` | `output_after_hash` | meaning |
|---------------|---------------------|---------|
| `approved` | equal to `output_before_hash` | reviewer accepted the agent output unchanged; downstream pipeline proceeds with the original output |
| `edited` | non-null, differs from `output_before_hash` | reviewer modified the output; downstream pipeline proceeds with the edited output |
| `rejected` | `null` | reviewer discarded the output; downstream pipeline does not consume it |
| `escalated` | `null` | reviewer declined to commit a decision at this point; the decision is deferred to a higher authority and no output is committed at this step |

The `approved`/`edited` rows compare `output_after_hash` against `output_before_hash` — a value-to-value comparison no JSON Schema draft can express — so they are enforced by the protocol's validation surface rather than the schema (§3.9). The schema description for `output_after_hash` documents the rules so that independent implementations can reproduce the same conditional verifier.

The four-value enum is closed by design. Each value maps to a specific Article 14 sub-clause: `rejected` and `edited` discharge Article 14(4)(d) (the right to disregard or override); `escalated` discharges Article 14(4)(e) (intervention or halt via stop mechanism); `approved` plays no role under Article 14 directly but is the anchor for the Article 50(4) exemption when paired with an editorial `reviewer_role`. Extending the enum is a major version bump.

Note that the Human Intervention Record carries no `status` field, unlike the Agent Step and Tool Invocation Records (§3.3.2). This is deliberate: `action_type` already *is* this record's outcome axis, and a Human Intervention Record is only ever produced for a decision that was actually committed — the record means "a human oversight decision happened." A *technical* failure of the oversight process — a reviewer who times out, is unavailable, or a review system that crashes before a decision is reached — is the absence of a decision rather than a different kind of decision, and the protocol does not currently record it as a Human Intervention Record. That case (oversight required but failing to engage) is a meaningful Article 14 signal in its own right and is noted as future work in §6.5: it is better modelled as a distinct oversight-failure event than by overloading the before/after decision record whose clean shape is the protocol's central contribution.

### 3.5.4 `reviewer_role` and the Article 50(4) hook

`reviewer_role` is a free-form non-empty string rather than an enum. Deployment-specific role taxonomies differ — `editor`, `compliance_officer`, `domain_expert`, `clinical_reviewer`, `case_handler` — and the protocol does not have grounds to impose a closed vocabulary across them. The freedom comes with a cost: matching a role to a regulatory anchor (for example, finding all interventions performed under editorial responsibility) is a deployment-level convention rather than a protocol-level guarantee.

The Article 50(4) deepfake-disclosure exemption is anchored by the combination of `action_type: "approved"` and a `reviewer_role` that the deployment has declared editorial. The protocol records the evidence; whether a given role satisfies the Article's "editorial responsibility" requirement is a legal determination outside the protocol's scope.

### 3.5.5 `justification_hash`

`justification_hash` is the only optional field on the Human Intervention Record. It hashes a free-form rationale text supplied by the reviewer. Hashing rather than storing the text mirrors the input/output stance in §3.2 and preserves GDPR data minimisation; the original rationale remains in application storage.

Article 14(4)(c) requires that the oversight person be able to correctly interpret the system's output, which strongly suggests that a rationale is good practice but does not strictly mandate one. The protocol therefore makes the field optional. A future deployment profile may require it.

### 3.5.6 Example

```json
{
  "record_id": "8b6a4d2c-1e23-4f56-9a7b-3c5d6e7f8910",
  "record_type": "human_intervention",
  "protocol_version": "0.4.0",
  "pipeline_id": "8d3fecf8-42d6-4f45-824f-7dde23407026",
  "session_id": "3174f399-0c98-4779-912d-ada24e61d126",
  "reviewer_id": ["alice.r"],
  "reviewer_role": "editor",
  "action_type": "edited",
  "output_before_hash": "102900748cf7170b814b19c74e79183a190bbcc4311629cc166cf1fd550075fe",
  "output_after_hash":  "ee36c97a8a4ed5b6c8af0a4f0fef36d6e2c89b59b1bb7f3e7b2a0d8c4ad53e1f",
  "intervention_timestamp": "2026-05-12T09:51:30.110000Z",
  "justification_hash": "5be8b5d6f8b6c2cab4f2e1aaf3e9f7c8b0a1d2e3f4a5b6c7d8e9f0a1b2c3d4e5",
  "parent_record_id": "c841bdac-d615-44bf-8db9-c941c1d58551"
}
```

The example shows the `edited` case: the reviewer changed the agent output, so `output_after_hash` is non-null and differs from `output_before_hash`. The `parent_record_id` points at the Agent Step Record whose output was reviewed.

---

## 3.6 Pipeline Bundle

### 3.6.1 Rationale

The Pipeline Bundle is the top-level container for the records produced by a single pipeline run. It serves four purposes: it groups all records belonging to one execution under a common identifier, it carries the Article 50(1) disclosure flag at the run granularity, it records the run's terminal `outcome`, and — most importantly — it carries the integrity seal (`bundle_hash`) that makes post-hoc tampering with the record set detectable.

The bundle is not a record in the same sense as the three preceding types. It does not describe an event; it describes a *collection* of events. Its `record_type: "pipeline_bundle"` keeps it dispatchable by the same discriminator pattern.

### 3.6.2 Fields

| Field | Type | Required | EU AI Act clause |
|-------|------|----------|------------------|
| `bundle_id` | UUID | yes | metadata |
| `record_type` | const `"pipeline_bundle"` | yes | metadata |
| `protocol_version` | semver string | yes | metadata |
| `pipeline_id` | UUID | yes | 12(2)(c) |
| `session_id` | UUID | yes | 12(2)(c) |
| `created_at` | ISO 8601 / RFC 3339 | yes | 12(2) traceability |
| `disclosure_presented` | boolean | yes | 50(1) |
| `outcome` | enum: `completed`, `aborted`, `error` | yes | 12(2)(a) |
| `oversight_regime` | enum: `standard`, `biometric_dual_control` | no | 14(5) |
| `records` | ordered array, min 1, `oneOf` the three record schemas | yes | 12(2) traceability |
| `bundle_hash` | SHA-256 hex | yes | 12(1) |

`outcome` records the run's terminal state at the bundle granularity: `completed` (the run finished normally), `error` (the run finished but at least one record has `status: "error"`), or `aborted` (the run was stopped before reaching its end). It complements the per-step `status` field by answering, at a glance, whether the pipeline as a whole malfunctioned — the run-level facet of Article 12(2)(a). The reference `BundleGenerator` derives it automatically (`error` if any record failed, else `completed`) and accepts an explicit override for the `aborted` case, which it cannot infer.

`records` is ordered, not a set. The order is chronological by the producing event's effective timestamp and is significant: it is the chain of custody the bundle's integrity seal protects. The minimum size is one — a pipeline run that emits no records is treated as an error by the BundleGenerator (`ValueError`) rather than producing an empty bundle.

`disclosure_presented` lives on the bundle, not on each record. The disclosure under Article 50(1) is presented to a user at most once per interaction with the system; expressing it per record would either force duplication or invite inconsistent values. Carrying it on the bundle binds it to the session.

`oversight_regime` is optional and, like the disclosure flag, is a run-level property rather than a per-record one — Article 14(5)'s two-person rule attaches to the *system*, so declaring it once on the bundle rather than repeating it on every Human Intervention Record matches the granularity of the obligation. An absent value is treated as `standard` (single-reviewer intervention permitted); `biometric_dual_control` declares the run subject to Article 14(5), and the validation layer then requires every Human Intervention Record in the bundle to carry at least two distinct reviewers (§3.7.4). The full field-level treatment, including what the declaration does and does not prove, is in §3.7.4.

### 3.6.3 `bundle_hash` and the integrity seal

`bundle_hash` is SHA-256 of the canonical JSON of the bundle with the `bundle_hash` field itself excluded from the input. The exclusion is necessary to break the chicken-and-egg of a hash that would otherwise need to include itself. Verification is the same procedure: the verifier strips `bundle_hash`, recomputes canonical JSON, hashes, and compares against the stored value.

Three points are worth being explicit about.

First, the seal protects integrity of the entire ordered record set, not of any single record. Mutating one byte of one record's `output_hash` is detectable because it changes the bundle's canonical JSON serialisation. Reordering records is detectable for the same reason. Adding or removing a record is detectable.

Second, the seal is not a signature. The protocol does not bind the bundle to a signing identity. Whether the seal's evidentiary value is sufficient depends on the deployment's storage controls: a bundle held in append-only storage with access logging is strong evidence; a bundle in a mutable filesystem is weaker. The protocol provides the integrity primitive; signing and storage hardening are the deployment's responsibility.

Third, the canonical JSON form used by the reference implementation conforms to RFC 8785 (JCS), as noted in §3.2. Because canonicalisation follows a published standard rather than an implementation-specific convention, an independent verifier using any conformant JCS library reproduces a digest exactly, without having to replicate this implementation's number formatting.

### 3.6.4 Example

```json
{
  "bundle_id": "7ff04ca5-4db0-4705-8981-7109e6dda5e8",
  "record_type": "pipeline_bundle",
  "protocol_version": "0.4.0",
  "pipeline_id": "8d3fecf8-42d6-4f45-824f-7dde23407026",
  "session_id": "3174f399-0c98-4779-912d-ada24e61d126",
  "created_at": "2026-05-12T09:51:26.828182Z",
  "disclosure_presented": true,
  "outcome": "completed",
  "records": [
    { "record_type": "tool_invocation", "...": "see §3.4.3" },
    { "record_type": "agent_step",     "...": "see §3.3.3" },
    { "record_type": "agent_step",     "...": "second agent_step" },
    { "record_type": "agent_step",     "...": "third agent_step" }
  ],
  "bundle_hash": "<computed over the canonical JSON of the full bundle>"
}
```

The records are abbreviated here for readability, so `bundle_hash` is shown as a placeholder; it is the SHA-256 of the canonical JSON of the complete bundle with the `bundle_hash` field excluded. A complete, recomputable bundle (four records sealed under protocol 0.4.0) ships in the repository at `demos/langchain/research/mock_bundle.json`.

---

## 3.7 Cross-cutting concerns

### 3.7.1 Identifier policy

UUIDs are used for identifiers that must be unique across deployments without coordination: `record_id`, `bundle_id`, `pipeline_id`, `session_id`, `parent_record_id`. Free-form non-empty strings are used for identifiers that are stable role names within a deployment and are not required to be globally unique: `agent_id`, `model_id`, `model_version`, `tool_name`, `tool_version`, `reviewer_id`, `reviewer_role`, `reference_data_id`. The split reflects two different jobs an identifier does. A `record_id` is a primary key; a UUID is appropriate. An `agent_id` is a role label; a name is appropriate.

`pipeline_id` is a UUID by design. A pipeline definition is a long-lived artefact and benefits from a globally unique handle that is stable across runs. A deployment that wishes to attach a human-readable label to a pipeline definition can do so in its own catalogue and resolve the UUID through that catalogue.

### 3.7.2 Hashing policy

All content hashes are SHA-256 over the canonical JSON form (§3.2) of the hashed object. For LLM messages this means the message list is first normalised to its serialisable dictionary form (provider-specific `BaseMessage.dict()` / `model_dump()`), then canonically serialised, then hashed. For tool inputs and outputs the same normalisation applies. In the reference implementation the LangChain-specific message projection lives in the adapter (`agent_prov/adapters/langchain/step_emitter.py` and `tool_emitter.py`) and the canonical hashing itself lives in the framework-neutral core (`agent_prov/_hashing.py`).

A practical consequence: two semantically identical model calls that differ in non-content metadata (a different request ID, a different cache header) produce identical `input_hash` values, because non-content metadata is not in the canonical form. This is intentional. The hash answers the question "was this specific content processed", not "was this specific HTTP request made".

### 3.7.3 The `parent_record_id` chain

`parent_record_id` forms a linear chain through the records in a bundle. Each record points at the immediately preceding record by `record_id`; the first record in the bundle has `parent_record_id: null`, except for a Human Intervention Record, which always has a non-null parent because it cannot be first.

The chain is *chronological*, not *causal*. If an agent step issues a tool call and the tool's invocation precedes the step's completion in time, the resulting Tool Invocation Record will appear before the Agent Step Record in the bundle, and the agent step's `parent_record_id` will point at the tool invocation rather than at a preceding agent step. This is consistent with the chronological framing: the chain is the order in which events were recorded, not a derivation graph in the PROV-O sense.

A causal "issued-by" link could be added in a later major version of the protocol as a separate optional field (`caused_by_record_id`), without disturbing the existing chronological chain. The present protocol prefers the simpler structure and treats causal recovery as an analysis-layer concern.

### 3.7.4 The two-person rule and `oversight_regime`

Article 14(5) requires that for biometric identification systems no decision be taken unless verified by at least two natural persons. The Human Intervention Record's `reviewer_id` accepts `minItems: 1` at the base schema, because a single reviewer is legitimate for the great majority of pipelines; tightening the count universally would force a second reviewer on deployments the Article does not govern. The two-person rule therefore has to be *conditional*, and the condition — whether this run belongs to the biometric population — has to be declared somewhere the constraint can read it.

The protocol declares it in the record stream itself: the Pipeline Bundle carries an optional `oversight_regime` field, and a bundle set to `biometric_dual_control` is validated at seal time against the rule that every Human Intervention Record must carry at least two reviewers. Because `reviewer_id` already has `uniqueItems`, two entries mean two distinct people. The check is a value comparison against a bundle-level field, so — like the other rules of §3.7.5 — it lives in the single validation surface rather than in the JSON Schema, and it fires in `BundleGenerator` at seal time, never during pipeline observation.

Declaring the regime *in the bundle* rather than by an external choice of validator is deliberate: the declaration is then covered by `bundle_hash` and any signature over it, so it is tamper-evident and attributable, and an auditor holding only the bundle can see both which regime was claimed and whether the reviewer count honoured it. What the field does **not** do is prove the run genuinely belongs to the biometric population: a producer can under-declare (`standard`, or omit the field) exactly as it could fabricate any other self-asserted field, which is the same emission-time trust boundary discussed in §6.2.3. So the mechanism is best read as *conditional enforcement*: given an honest — or, under a signature, attributable — declaration, the two-person invariant cannot be violated within the record. Binding the regime to an external, non-repudiable source of truth about what kind of system this is (a registered system definition) is a governance concern outside the record stream, noted as future work in §6.5.5.

### 3.7.5 Conditional rules outside the schema layer

Two classes of constraint are stated in the schemas' descriptions but cannot live in the JSON Schema, because each compares two field *values* — something no JSON Schema draft can express:

- `timestamp_end >= timestamp_start` on Agent Step and Tool Invocation Records.
- The `status` / `output_hash` / `error` presence rule on Agent Step and Tool Invocation Records: `status: "success"` requires `output_hash` present and `error` absent; `status: "error"` requires `output_hash` absent and `error` present.
- The `action_type` / `output_after_hash` conditional rules on the Human Intervention Record, summarised in §3.5.3.
- The bundle-level two-person rule: when the Pipeline Bundle declares `oversight_regime: "biometric_dual_control"`, every Human Intervention Record it carries must have at least two `reviewer_id` entries (§3.7.4). This compares a bundle-level value against a per-record array length, which no JSON Schema draft can express.

Rather than leave these to each deployment to re-implement, the protocol's reference implementation enforces them in a single validation surface that composes both mechanisms: structural validation against the JSON Schema, followed by these conditional checks. A record or bundle is valid only if it passes both, and there is one entry point (`validate_record` / `validate_bundle`) for callers and conformance tests alike, so structural and conditional validity are never checked in two different places (§3.9; the implementation is described in Chapter 4). The schema descriptions still document the conditional rules in full, so an independent verifier can reproduce the same checks. Note that the *null*/non-null half of the `action_type` rules (`rejected`/`escalated` → `null`, `edited` → non-null) is in fact expressible with JSON Schema `if`/`then`/`else`; it is kept in the unified validator with the value-comparison rules so that all conditional logic resides in one place rather than split across the schema and the validator.

---

## 3.8 EU AI Act mapping — unified table

The table below consolidates the per-record mappings into a single reference. It is the conceptual centre of the protocol: every field that appears in the schemas is here, and every Act clause the protocol claims to discharge is here.

| Protocol field | Records carrying it | Art. 12 | Art. 14 | Art. 50 |
|----------------|---------------------|---------|---------|---------|
| `pipeline_id`, `session_id` | all | 12(2)(c) | — | — |
| `agent_id` | agent_step, tool_invocation | 12(2)(c) | — | — |
| `model_id`, `model_version` | agent_step | 12(2)(b) | 14(4)(a) | — |
| `tool_name`, `tool_version` | tool_invocation | 12(2)(b), 12(2)(c) | — | — |
| `timestamp_start`, `timestamp_end` | agent_step, tool_invocation | 12(3)(a) | — | — |
| `input_hash` | agent_step, tool_invocation | 12(3)(c) | — | — |
| `output_hash` | agent_step, tool_invocation | 12(2)(c) | — | — |
| `status`, `error` | agent_step, tool_invocation | 12(2)(a) | — | — |
| `reference_data_id` | agent_step, tool_invocation | 12(3)(b) | — | — |
| `reviewer_id` | human_intervention | 12(3)(d) | 14(5) | — |
| `reviewer_role` | human_intervention | — | — | 50(4) exception |
| `action_type` | human_intervention | — | 14(4)(d), 14(4)(e) | 50(4) exception |
| `output_before_hash` | human_intervention | — | 14(4)(c) | — |
| `output_after_hash` | human_intervention | — | 14(4)(d) | — |
| `intervention_timestamp` | human_intervention | — | 14(4)(e) | — |
| `justification_hash` (optional) | human_intervention | — | 14(4)(c) | — |
| `parent_record_id` | all records | 12(2) traceability | — | — |
| `disclosure_presented` | pipeline_bundle | — | — | 50(1) |
| `outcome` | pipeline_bundle | 12(2)(a) | — | — |
| `oversight_regime` (optional) | pipeline_bundle | — | 14(5) | — |
| `bundle_hash` | pipeline_bundle | 12(1) | — | — |

Two reading aids. First, fields whose only mapping is `metadata` (such as `record_id`, `record_type`, `protocol_version`, `created_at`, `bundle_id`) are omitted from this table; they discharge no Act obligation directly but are required for the protocol to function as evidence. Second, the cross-record fields — `pipeline_id`, `session_id`, `agent_id`, `parent_record_id` — appear once in the table even though they are present on multiple record types, to keep the structure readable.

The mapping is *deliberate but not exhaustive*. The protocol provides the technical evidence on which compliance claims rest; it does not, by itself, prove compliance. A deployment claiming Article 12 compliance must also satisfy operational obligations (retention periods, access control, post-market monitoring procedures) that are out of the protocol's scope. The same applies to Article 14: a Human Intervention Record proves the oversight act occurred, but Article 14's design obligation — that the system be designed to permit oversight — is a system-architecture claim made at design review, not in a record.

---

## 3.9 What the protocol does not specify

For clarity, the protocol leaves the following deliberately to the application layer:

- **Transport, storage, and retention.** Where bundles live, how long they are retained, who can read them. The protocol provides only the document; deployment hardens the document.
- **Signing.** The bundle carries an integrity seal but no signature. Binding a bundle to a signing identity (an organisational PKI, a hardware token, a transparency log) is a deployment choice.
- **Raw content management.** The hashes in the protocol record evidence; the preimages live in application storage. Linking a hash to its preimage is the deployment's job.
- **Risk classification.** Article 12(2)(a) has two facets. The protocol now records the *malfunction substrate* — per-step `status`/`error` and the bundle-level `outcome` capture failed steps and aborted runs, the events most relevant to identifying risk situations. What it does not do is *classify* whether a given situation "may result in risk" within the meaning of Article 79(1): that judgement is application logic, not a field on a record. The protocol surfaces the events; the deployment decides which of them constitute reportable risk.
- **User interface for disclosure.** The bundle carries `disclosure_presented` as a boolean. Whether the disclosure was correctly worded and rendered to the user is a UI design responsibility.
- **Reviewer-role taxonomies.** `reviewer_role` is free-form; the meaning of a role within a deployment is a deployment concern.
- **Algorithm negotiation.** SHA-256 is the only hash algorithm. The protocol does not currently support algorithm identifiers; a future major version may.
- **Causal recovery.** The `parent_record_id` chain is chronological. Recovering causal "issued-by" links is an analysis-layer task or a feature of a future protocol version.

These exclusions are not gaps; they are the boundary of the protocol. A successful protocol is one whose scope is small enough to be implementable correctly and large enough to be regulatorily useful. The four record types specified here aim at that boundary.

Chapter 4 turns from this static specification to the dynamic side: the LangGraph middleware that emits these records automatically from a running pipeline, and the two demo pipelines that exercise the protocol end to end.
