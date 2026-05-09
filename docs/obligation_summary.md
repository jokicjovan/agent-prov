# EU AI Act — Obligation Summary
## Articles 12, 14, 50 · Technical Requirements for Provenance Protocol Mapping
*Day 1 output · AI Agent Provenance & Compliance Protocol thesis*

---

## Article 12 — Record-Keeping

**Scope:** High-risk AI systems (Chapter III, Section 2)

**Core obligation:** High-risk AI systems must technically allow for the automatic recording of events (logs) over the system's lifetime, with sufficient traceability for risk identification, post-market monitoring, and operational monitoring.

### Technical requirements extracted

| Clause | Requirement | Protocol field implication |
|--------|-------------|---------------------------|
| Art. 12(1) | System must *technically allow* automatic log generation — logging cannot be optional or manual | Every pipeline execution must emit records automatically; the middleware must be non-bypassable |
| Art. 12(2)(a) | Logs must identify situations that may result in risk (Art. 79(1)) or substantial modification | Satisfied by the logging capability itself — if records exist and can be reviewed, the obligation is met. No per-record `risk_flag` field; risk assessment is application-layer logic outside the protocol scope. |
| Art. 12(2)(b) | Logs must facilitate post-market monitoring (Art. 72) | `model_id` + `model_version` on every record — enables drift detection across deployments |
| Art. 12(2)(c) | Logs must support operational monitoring by deployers (Art. 26(5)) | `pipeline_id` + `session_id` linking all records in a run |
| Art. 12(3)(a) | *Minimum for biometric systems:* record start and end time of each use | `timestamp_start`, `timestamp_end` on Agent Step Record |
| Art. 12(3)(b) | *Minimum for biometric systems:* record the reference database consulted | `reference_data_id` on Agent Step Record / Tool Invocation Record |
| Art. 12(3)(c) | *Minimum for biometric systems:* record input data that produced a match | `input_hash` (SHA-256 of input) on Agent Step Record |
| Art. 12(3)(d) | *Minimum for biometric systems:* identify natural persons who verified results (per Art. 14(5)) | `reviewer_id` on Human Intervention Record — **direct clause-level justification** |

### Notes
- Art. 12(3) specifies minimums for biometric identification systems only, but the general traceability obligation in Art. 12(2) applies to all high-risk systems. The thesis treats 12(3) fields as the floor and applies them universally across all record types.
- "Technically allow" in Art. 12(1) means the logging capability must be built into the system architecture — post-hoc or optional logging does not satisfy the obligation. This justifies the middleware-as-infrastructure design approach.

---

## Article 14 — Human Oversight

**Scope:** High-risk AI systems (Chapter III, Section 2)

**Core obligation:** High-risk AI systems must be designed so that natural persons can effectively oversee them during operation. Oversight persons must be enabled to understand, monitor, interpret, override, and halt the system.

### Technical requirements extracted

| Clause | Requirement | Protocol field implication |
|--------|-------------|---------------------------|
| Art. 14(1) | System must be *designed* to allow effective oversight — not just permit it in principle | A human decision point must exist in the pipeline architecture; HITL record's existence proves a decision point was built in |
| Art. 14(2) | Oversight must prevent/minimise risks to health, safety, fundamental rights | `action_type` on Human Intervention Record captures whether risk was acted on (rejected/escalated) |
| Art. 14(4)(a) | Oversight person must be able to understand capabilities/limitations and detect anomalies | `model_id` + `model_version` *enable* review of capabilities/limitations at oversight time; full satisfaction of 14(4)(a) is a UI-level disclosure obligation beyond protocol scope. Anomaly detection is an upstream design requirement. |
| Art. 14(4)(b) | Oversight person must be aware of automation bias risk | UI/UX design obligation for the oversight interface — out of provenance schema scope. Addressed in PoC interface design (Chapter 4), not captured as a logged field. |
| Art. 14(4)(c) | Oversight person must be able to correctly interpret the system's output | `output_before_hash` on Human Intervention Record — proves the human saw the actual output before deciding |
| Art. 14(4)(d) | Oversight person must be able to disregard, override, or reverse the output | `action_type: rejected` or `action_type: edited`; `output_after_hash` proves the override was recorded |
| Art. 14(4)(e) | Oversight person must be able to intervene or halt via a stop mechanism | `action_type: escalated`; `intervention_timestamp` proves timely intervention before next automated step |
| Art. 14(5) | For biometric ID systems: no decision taken unless verified by *at least two* natural persons | `reviewer_id` (array, min length 2 for biometric pipelines); dual-sign-off constraint in protocol spec |

### Notes
- Art. 14 is primarily a *design* obligation, not a *logging* obligation. However, provenance records serve as the evidence that the design obligation was met in practice. A HITL record in the bundle is proof that a human decision point existed and was exercised.
- Art. 14(4)(d) — the right to override — is the **primary novel contribution** of the Human Intervention Record. No existing provenance standard (including PROV-AGENT) models the before/after state of a human override.
- Art. 14(5)'s two-person verification requirement is scoped to biometric systems, but the `reviewer_id` field design should support multiple reviewers to accommodate it.

---

## Article 50 — Transparency Obligations

**Scope:** Broader than high-risk — applies to any AI system interacting with natural persons, generating synthetic content, or performing emotion/biometric categorisation

**Core obligation:** Users must be informed they are interacting with AI; AI-generated content must be machine-readable marked as such; deepfakes must be disclosed.

### Technical requirements extracted

| Clause | Requirement | Protocol field implication |
|--------|-------------|---------------------------|
| Art. 50(1) | Users must be informed they are interacting with an AI system (at first interaction) | `disclosure_presented: boolean` on Pipeline Bundle — records whether disclosure was shown |
| Art. 50(2) | AI-generated content (audio, image, video, text) must be marked in machine-readable format as artificially generated | Artifact-level obligation — the marker belongs on the output file/content itself, not on a provenance record. Out of protocol scope; `output_hash` links to the artifact where the marker should reside. |
| Art. 50(3) | Deployers of emotion recognition / biometric categorisation systems must inform exposed persons | Upstream design requirement; not directly captured in provenance record |
| Art. 50(4) | Deployers generating/manipulating content constituting a deepfake must disclose it | User-facing disclosure obligation — out of provenance schema scope. The Tool Invocation Record's `output_hash` links to the artifact; disclosure to the user is an application-layer responsibility. |
| Art. 50(4) exception | AI-generated text is *exempt* from disclosure obligation if it has undergone human review with editorial responsibility | `action_type: approved` on Human Intervention Record with `reviewer_role: editor` — HITL record serves as Art. 50(4) exemption evidence |

### Notes
- Art. 50 is the **weakest fit** for this thesis. Its obligations are primarily user-facing disclosure requirements, not internal provenance requirements. The protocol addresses Art. 50 incidentally rather than as its primary target.
- The most useful Art. 50 hook is the Art. 50(4) exemption: when a human reviewer approves AI-generated text, the Human Intervention Record constitutes evidence of "human review with editorial responsibility." This is a secondary compliance benefit worth one paragraph in Chapter 3.
- Art. 50 is scoped to a different population of AI systems than Arts. 12 and 14. A multi-agent pipeline producing internal outputs (not user-facing content) may not trigger Art. 50 at all.

---

## Cross-Article Field Summary

| Protocol field | Art. 12 | Art. 14 | Art. 50 |
|---------------|---------|---------|---------|
| `timestamp_start`, `timestamp_end` | 12(3)(a) | — | — |
| `model_id`, `model_version` | 12(2)(b) | 14(4)(a) | — |
| `input_hash` | 12(3)(c) | — | — |
| `output_hash` | 12(2)(c) | — | — |
| `reference_data_id` | 12(3)(b) | — | — |
| `pipeline_id`, `session_id` | 12(2)(c) | — | — |
| `reviewer_id` | 12(3)(d) | 14(5) | — |
| `action_type` | — | 14(4)(d), 14(4)(e) | 50(4) exception |
| `output_before_hash` | — | 14(4)(c) | — |
| `output_after_hash` | — | 14(4)(d) | — |
| `intervention_timestamp` | — | 14(4)(e) | — |
| `disclosure_presented` | — | — | 50(1) |

---

*Source: Regulation (EU) 2024/1689, Official Journal of the European Union, 13 June 2024*
