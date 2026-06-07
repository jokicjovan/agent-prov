# Chapter 1 — Introduction

## 1.1 Motivation

Large language models are no longer deployed as single request-response endpoints. The dominant pattern in production systems is the *multi-agent pipeline*: a directed graph of LLM-backed nodes that plan, call tools, consult external data, and pass intermediate results to one another, often with a human reviewer positioned at one or more decision points. A customer-facing assistant may route a query through a retrieval agent, a drafting agent, and a compliance agent before a human approves the final text; a document-processing system may summarise, have a person edit the summary, and then finalise it. The output that reaches a user is the product of many automated steps and, frequently, at least one human judgement.

This architectural shift coincides with the arrival of the first comprehensive regulation of AI systems. Regulation (EU) 2024/1689, the Artificial Intelligence Act, entered into force on 1 August 2024 and is being applied in phases through 2025 and 2026. For systems classified as high-risk, it imposes two obligations that bear directly on the multi-agent pipeline. Article 12 requires that the system *technically allow for the automatic recording of events* over its lifetime — a record-keeping duty that is explicitly technical rather than procedural. Article 14 requires that the system be *designed to permit effective human oversight*, including the ability for a person to disregard, override, or reverse its output. A third article, Article 50, adds transparency duties — chiefly that users be informed when they are interacting with an AI system and that synthetic content be marked as such.

These obligations create a concrete engineering requirement: a regulated multi-agent pipeline must emit a record stream that an auditor can inspect to answer two kinds of question. *What did the automated parts of the system do* — which model produced which output, from which input, at what time, in which pipeline run? And *what did the humans do* — who reviewed which output, what decision did they take, and what did the output look like before and after their intervention? The first question is, in principle, answerable with existing provenance tooling. The second is not. No existing provenance standard models a human oversight event as a first-class record: the reviewer's identity, the action taken, and — critically — the state of the output before and after the human's decision. Yet it is precisely this before/after override evidence that Article 14(4) turns on, and precisely this evidence that an auditor would need to confirm that human oversight was not merely *possible* but *exercised*.

This work addresses this gap. It proposes a provenance protocol for LLM multi-agent pipelines that captures automated agent steps, tool calls, and human oversight intervention events, and maps each captured field, clause by clause, to the obligations of EU AI Act Articles 12, 14, and 50.

## 1.2 Problem statement

The closest published predecessor to this work is PROV-AGENT (Souza et al., IEEE e-Science, August 2025), which extends the W3C PROV family with classes for LLM agentic workflows and has been deployed in a scientific HPC setting. PROV-AGENT comprehensively captures the *automated* portion of a pipeline — model identity, prompt and response, inference parameters, timestamps, tool inputs and outputs, and inter-record linkage. For a scientific workflow whose primary requirement is reproducibility, this is sufficient.

It leaves a specific shape of gap when the requirement shifts from reproducibility to regulatory compliance. PROV-AGENT does not model human oversight events; it carries no mapping to any regulatory framework; it stores raw prompts and responses by default rather than content hashes, which is often unacceptable under data-minimisation principles; and it provides no integrity seal over the record set, so post-hoc tampering with the trace is not detectable. The vocabulary layer beneath it, W3C PROV, supplies the general primitives — entity, activity, agent — but no AI-specific or compliance-specific schema. C2PA, the standard most often invoked in discussions of "AI provenance," operates at the level of individual media artefacts and says nothing about pipeline execution. And the EU AI Act itself prescribes *that* records must exist and *what* they must enable, but deliberately specifies no record format, hashing scheme, or serialisation.

The problem this work solves is therefore the design and implementation of the missing layer: a concrete, machine-readable provenance protocol that (i) records human oversight events as first-class records with before/after override evidence, (ii) maps its fields explicitly to EU AI Act Articles 12, 14, and 50, (iii) stores content hashes rather than raw text by default, and (iv) seals each pipeline run with a tamper-evident integrity hash — and that does so without imposing prohibitive runtime, storage, or developer-effort cost on the pipeline it observes.

## 1.3 Research questions

The thesis is organised around three research questions.

**RQ1 — Schema.** What set of record types, and what fields on each, are necessary and sufficient to capture an LLM multi-agent pipeline run such that the technical obligations of EU AI Act Articles 12, 14, and 50 can be discharged by reference to populated fields?

**RQ2 — Human oversight.** How can a human oversight event be modelled as a first-class provenance record — capturing reviewer identity, the action taken, and the before/after state of the reviewed output — so that the human-oversight obligations of Article 14, which no prior provenance schema addresses, become verifiable from the record stream?

**RQ3 — Viability.** Can such a protocol be implemented as non-invasive middleware over a real agent framework, and what runtime overhead, storage cost, and developer effort does instrumenting a pipeline incur? In particular, does the cost scale acceptably with pipeline size?

RQ1 is answered by the protocol specification and its field-to-clause mapping; RQ2 by the design of the Human Intervention Record, the central novelty; RQ3 by a reference implementation and a three-axis evaluation of completeness, overhead, and developer effort.

## 1.4 Contributions

This work makes four contributions.

1. **A provenance protocol for regulated multi-agent pipelines**, defined as four versioned, JSON-Schema-validated record types — Agent Step, Tool Invocation, Human Intervention, and Pipeline Bundle — together with an explicit mapping from each compliance-relevant field to the EU AI Act clause it discharges. The protocol stores cryptographic hashes of inputs and outputs rather than raw content, and seals each pipeline run with a canonical-JSON integrity hash (RFC 8785) so that independent verifiers can reproduce the digest byte-for-byte and detect tampering.

2. **The Human Intervention Record**, the core novelty. It models a human decision point as a record carrying the reviewer's identity (as an array, to express the dual-sign-off that Article 14(5) requires for biometric systems), the action taken (`approved`, `rejected`, `edited`, `escalated`), the hash of the output before the human saw it, the hash of the output after the decision, and the intervention timestamp. This before/after override evidence is the technical substantiation of Article 14(4)'s "disregard, override, reverse" requirement, and it is not captured by any existing provenance standard.

3. **A reference implementation** as middleware for LangGraph, comprising provenance-emitting hooks that attach to a pipeline's existing callback mechanism without modifying node logic, a context manager that declares human decision points, a single validation surface that enforces both structural and value-comparison rules at seal time, and a compliance-report generator that renders a bundle into a per-record table of discharged obligations.

4. **A three-axis evaluation** of the implementation over two demonstration pipelines and a parametric benchmark: a clause-by-clause completeness audit against Articles 12, 14, and 50; a measurement of runtime and storage overhead and how it scales; and a measurement of the developer effort required to instrument a pipeline.

## 1.5 Scope

Three boundaries are set deliberately and revisited where relevant in later chapters.

The reference implementation targets **LangGraph only**. The record schemas are framework-agnostic, but the PoC instruments a single framework; adapters for other agent frameworks are noted as future work. **Article 50 is a secondary mapping**: most of its duties are user-facing disclosure and artifact-level watermarking obligations that belong to the application surface, not the pipeline's record stream, and the protocol records only whether disclosure was presented and the editorial-responsibility evidence relevant to the Article 50(4) exemption. Finally, the protocol stores **hashes, not content**: it provides tamper-evident commitments to inputs and outputs, but where and how the underlying content is stored is treated as a deployment concern, because regulated deployments differ widely in their storage requirements. A bundle alone is sufficient to verify the *structure* of a run — record count, parent-chain integrity, the human-intervention action sequence, and the integrity seal — while verifying *what was said* additionally requires the original content from the deployment's content store.

The protocol is positioned throughout as an *extension and differentiation* of PROV-AGENT, not a replacement: it adopts that work's automated-capture pattern and adds the human-oversight record type and regulatory mapping that the compliance setting requires.

## 1.6 Structure of the thesis

The remainder of the thesis is organised as follows.

**Chapter 2 (Background)** establishes the technical and regulatory ground: the W3C PROV vocabulary, PROV-AGENT and adjacent AI/ML provenance work, C2PA, and the relevant articles of the EU AI Act, closing with a synthesis of the gap the protocol fills.

**Chapter 3 (Protocol Design)** specifies the four record types field by field and walks through the field-to-clause mapping against Articles 12, 14, and 50.

**Chapter 4 (Implementation)** describes the reference implementation — the middleware architecture, the human-intervention context manager, the validation surface, the bundle integrity seal, and the compliance-report generator — together with the two demonstration pipelines.

**Chapter 5 (Evaluation)** reports the three-axis evaluation: completeness against the Act, runtime and storage overhead and its scaling, and developer effort, and positions the result against PROV-AGENT.

**Chapter 6 (Discussion and Future Work)** examines the limitations, the threat model for hash-based evidence, the boundaries marked by the out-of-scope obligations, and the directions that follow — including adapters for further frameworks and a machine-readable declaration of behavioural constraints.

---

## References (working list)

The reference list below is the working set used for this chapter; the consolidated, formatted bibliography is maintained in `references.md`.

1. European Parliament and Council, *Regulation (EU) 2024/1689 laying down harmonised rules on artificial intelligence (Artificial Intelligence Act)*, Official Journal of the European Union, 13 June 2024.
2. R. Souza et al., "PROV-AGENT: Unified Provenance for Tracking AI Agent Interactions in Agentic Workflows," IEEE e-Science, Chicago, August 2025. arXiv:2508.02866.
3. World Wide Web Consortium, *PROV-O: The PROV Ontology*, W3C Recommendation, 30 April 2013. https://www.w3.org/TR/prov-o/
4. Coalition for Content Provenance and Authenticity, *C2PA Technical Specification*, version 2.x. https://c2pa.org/specifications/
5. A. Rundgren, B. Jordan, S. Erdtman, *JSON Canonicalization Scheme (JCS)*, RFC 8785, IETF, June 2020.
