# Gap Analysis — PROV-O, PROV-AGENT, and This Protocol
## What Existing Provenance Standards Cover vs. What They Miss
*AI Agent Provenance & Compliance Protocol*

---

## 1. W3C PROV-O — Baseline Standard

W3C PROV-O is the foundational ontology for provenance on the web. It defines three core constructs:

- **Entity** — a physical, digital, or conceptual thing (data, documents, models)
- **Activity** — a dynamic process that generates or consumes entities
- **Agent** — a person, software, or organisation responsible for activities

Core relationships: `wasGeneratedBy`, `used`, `wasAssociatedWith`, `wasAttributedTo`, `wasDerivedFrom`, `actedOnBehalfOf`, `hadMember`.

PROV-O supports qualified relationships (e.g., `qualifiedAssociation`, `qualifiedUsage`) that add roles, timestamps, and plans to any relationship. It is deliberately domain-agnostic — it provides a vocabulary, not a schema.

**Relevance to this protocol:** PROV-O is the vocabulary layer that PROV-AGENT and this protocol both build on. It provides the conceptual foundation but defines no fields specific to LLM agents, tool calls, or human oversight.

---

## 2. PROV-AGENT — Closest Prior Work

**Citation:** R. Souza et al., "PROV-AGENT: Unified Provenance for Tracking AI Agent Interactions in Agentic Workflows," IEEE e-Science, Chicago, 2025.

### What PROV-AGENT Does

PROV-AGENT extends W3C PROV with LLM-specific classes and relationships for scientific agentic workflows. It captures automated agent execution end-to-end.

**Classes defined:**

| Class | Type | Description |
|-------|------|-------------|
| `AIAgent` | Agent subclass | The LLM agent node |
| `AIModelInvocation` | Activity subclass | A single LLM call |
| `AgentTool` | Activity subclass | A tool/function execution |
| `Campaign` / `Workflow` / `Task` | Activity subclasses | Pipeline hierarchy |
| `Prompt` | Entity subclass | Input to an LLM |
| `ResponseData` | Entity subclass | Output from an LLM |
| `AIModel` | Entity subclass | The model itself (name, provider, temperature) |
| `DomainData` | Entity subclass | Tool inputs/outputs |

**Fields captured per agent interaction:**
- Prompt text, response text
- Model name, provider, temperature, parameters
- Execution timestamp, response latency
- Tool inputs and outputs
- Agent identity (`wasAttributedTo`)
- Inter-record linking (`wasInformedBy`)

**Implementation:** A generic Python wrapper compatible with CrewAI, LangChain, and OpenAI.

**Use case:** Deployed in an autonomous additive manufacturing workflow at Oak Ridge National Laboratory.

### What PROV-AGENT Covers

| Capability | Covered |
|------------|---------|
| Automated agent step capture | ✅ |
| Tool invocation capture | ✅ |
| Model metadata (name, provider, parameters) | ✅ |
| Timestamps and latency | ✅ |
| Pipeline/workflow hierarchy | ✅ |
| Inter-record parent linkage | ✅ |
| Multi-framework support (LangChain, CrewAI, OpenAI) | ✅ |

---

## 3. Gap Analysis — What PROV-AGENT Does Not Cover

### Gap 1 — No Human Intervention Modelling (Critical)

PROV-AGENT does not define any record type for human oversight events. The schema references `wasAssociatedWith` for persons at the campaign level but provides no mechanism to capture:

- That a human reviewed an agent output at a specific point in the pipeline
- The state of the output *before* the human decision (`output_before_hash`)
- The state of the output *after* the human decision (`output_after_hash`)
- The type of decision made (`approved`, `rejected`, `edited`, `escalated`)
- The identity of the reviewer(s) (`reviewer_id`)
- The timestamp of the intervention (`intervention_timestamp`)

This is the core gap this protocol addresses. No existing provenance standard models the before/after state of a human override or links it to regulatory oversight obligations.

### Gap 2 — No Regulatory Compliance Mapping

PROV-AGENT contains no references to the EU AI Act, GDPR, NIST AI RMF, or any regulatory framework. It is designed and evaluated for scientific HPC workflows (additive manufacturing, federated computing) where reproducibility and traceability — not legal compliance — are the goals. There is no mapping between provenance fields and statutory obligations.

This protocol provides an explicit field-to-clause mapping for EU AI Act Articles 12, 14, and 50, making it suitable as compliance evidence, not just an audit trail.

### Gap 3 — Default Storage Model: Raw Content vs. Content Hashing

PROV-AGENT's default storage model is raw prompt and response text as provenance entities. PROV-AGENT does not forbid hashing, but its default behaviour is incompatible with two constraints typical of enterprise and regulated deployments:

1. **Privacy** — storing raw LLM inputs/outputs may include personal data, conflicting with GDPR data minimisation principles
2. **Integrity** — storing mutable text strings does not provide tamper evidence; a SHA-256 hash of canonical content does

This protocol stores `input_hash` and `output_hash` (SHA-256) by default rather than raw content, satisfying Art. 12(3)(c) while preserving privacy. The original content remains in application storage; the hash proves what was processed.

### Gap 4 — No Pipeline Integrity Guarantee

PROV-AGENT has no equivalent to the Pipeline Bundle with a `bundle_hash`. There is no mechanism to detect post-hoc tampering with the provenance record set. A SHA-256 hash of the canonical ordered JSON of all records in a run provides a single integrity seal for the entire pipeline execution.

---

## 4. Differentiation Table

| Dimension | PROV-AGENT | This Protocol |
|-----------|-----------|-------------|
| Automated agent step capture | ✅ | ✅ |
| Tool invocation capture | ✅ | ✅ |
| Human intervention record | ❌ | ✅ (core novelty) |
| Before/after override state | ❌ | ✅ (`output_before_hash`, `output_after_hash`) |
| HITL action type | ❌ | ✅ (`approved`, `rejected`, `edited`, `escalated`) |
| Reviewer identity | ❌ | ✅ (`reviewer_id` array) |
| EU AI Act mapping | ❌ | ✅ (Arts. 12, 14, 50) |
| Content hashing (privacy-preserving) | ❌ (raw text) | ✅ (SHA-256) |
| Pipeline integrity seal | ❌ | ✅ (`bundle_hash`) |
| Multi-framework support | ✅ | LangGraph adapter + a framework-free adapter; packaged AutoGen/CrewAI future work |
| Scientific workflow optimisation | ✅ | ❌ (not the target domain) |

---

## 5. Positioning Statement

This protocol does not replace PROV-AGENT. It extends and differentiates from it:

- **Extends:** The automated step and tool invocation capture mirrors PROV-AGENT's `AIModelInvocation` and `AgentTool` patterns. It inherits the same PROV-O foundation.
- **Differentiates:** The Human Intervention Record is novel — it models a class of provenance event that PROV-AGENT explicitly does not address. The EU AI Act mapping is novel — it frames provenance as compliance evidence, not just scientific audit trail. The SHA-256 hashing approach addresses privacy constraints absent from the scientific workflow context.

The single packaged adapter (LangGraph) is a PoC scope decision, not a protocol limitation: the record schemas are framework-agnostic, and the framework-neutral record factory is already exercised by two adapters — the LangGraph one and a framework-free agent loop (`demos/openai_loop/`) — so adapters for AutoGen or CrewAI are additional future work, not a redesign.

The contribution is targeted: one new record type (HITL) and one new framing (regulatory compliance) on top of a well-established provenance foundation.

---

## 6. Other Related Standards (Brief)

| Standard | Scope | Gap relative to this protocol |
|----------|-------|-----------------------------|
| **PROV-DfA** | Human-steered workflows | Models human *actions*, not human *oversight of AI output* |
| **ProvONE** | Scientific workflow metadata | No AI-specific fields, no regulatory framing |
| **PROV-ML** | ML experiment tracking | Focused on model training artifacts, not inference pipelines |
| **C2PA** | Content authenticity (media) | Artifact-level provenance, not pipeline-level; no HITL modelling |
| **FAIR4ML** | FAIR principles for ML models | Model-centric, not execution-centric; no compliance mapping |

---

*Sources: W3C PROV-O Primer (https://www.w3.org/TR/prov-primer/); Souza et al., PROV-AGENT, arXiv:2508.02866, IEEE e-Science 2025*
