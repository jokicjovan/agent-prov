# References

Consolidated bibliography for the AI Agent Provenance & Compliance Protocol. The
individual chapter drafts carry per-chapter working lists; this file is the merged,
de-duplicated source of truth that those lists point to. Citation formatting is
IEEE-style and will be finalised at manuscript-assembly time.

## Regulation

1. European Parliament and Council, *Regulation (EU) 2024/1689 of 13 June 2024
   laying down harmonised rules on artificial intelligence (Artificial
   Intelligence Act)*, Official Journal of the European Union, L series, 12 July
   2024. http://data.europa.eu/eli/reg/2024/1689/oj
2. European Parliament and Council, *Regulation (EU) 2016/679 (General Data
   Protection Regulation)*, Official Journal of the European Union, L 119, 4 May
   2016. (Cited for the data-minimisation principle motivating hash-over-content
   storage.) http://data.europa.eu/eli/reg/2016/679/oj

## Prior and related work

3. R. Souza, T. Skluzacek, S. Wilkinson, et al., "PROV-AGENT: Unified Provenance
   for Tracking AI Agent Interactions in Agentic Workflows," in *Proc. IEEE
   e-Science*, Chicago, IL, USA, 2025. arXiv:2508.02866. — Closest prior work; the
   protocol extends and differentiates from it.

## Provenance standards and vocabularies

4. World Wide Web Consortium, *PROV-O: The PROV Ontology*, W3C Recommendation,
   30 April 2013. https://www.w3.org/TR/prov-o/
5. World Wide Web Consortium, *PROV Model Primer*, W3C Working Group Note,
   30 April 2013. https://www.w3.org/TR/prov-primer/
6. World Wide Web Consortium, *PROV-DM: The PROV Data Model*, W3C Recommendation,
   30 April 2013. https://www.w3.org/TR/prov-dm/

## Content provenance

7. Coalition for Content Provenance and Authenticity, *C2PA Technical
   Specification*, version 2.x. https://c2pa.org/specifications/

## Canonicalisation and timestamping

8. A. Rundgren, B. Jordan, and S. Erdtman, *JSON Canonicalization Scheme (JCS)*,
   RFC 8785, Internet Engineering Task Force, June 2020.
   https://www.rfc-editor.org/rfc/rfc8785
9. C. Adams, P. Cain, D. Pinkas, and R. Zuccherato, *Internet X.509 Public Key
   Infrastructure Time-Stamp Protocol (TSP)*, RFC 3161, Internet Engineering Task
   Force, August 2001. (Cited as the basis for trusted timestamping in future
   work.) https://www.rfc-editor.org/rfc/rfc3161

## Tools

10. LangChain, *LangGraph — Building stateful, multi-actor applications with
    LLMs*, software documentation. https://langchain-ai.github.io/langgraph/ —
    The framework targeted by the reference implementation.

## To finalise at manuscript assembly

The following works are named in the chapter prose but do not yet have verified
bibliographic entries above. Each must have its author list, venue, and year
confirmed from the primary source before assembly — details are deliberately left
blank here rather than guessed, to avoid propagating a wrong citation.

- **PROV-ML** — ML-experiment-tracking extension of PROV (Ch. 2 §2.3.2,
  `gap_analysis.md` §6). NOTE: §2.3.2 currently attributes it to "Pimentel et
  al."; verify authorship — Pimentel is associated with ProvONE/noWorkflow, so
  this attribution is suspect.
- **ProvONE** — PROV extension for scientific-workflow provenance (Ch. 2 §2.3.2,
  `gap_analysis.md` §6).
- **PROV-DfA** — provenance for human-steered / data-from-activities workflows
  (Ch. 2 §2.3.2, `gap_analysis.md` §6).
- **FAIR4ML** — FAIR-principles metadata schema for ML models (Ch. 2 §2.3.2,
  `gap_analysis.md` §6).
- **in-toto / SLSA / DSSE / Sigstore (Rekor)** — the software-supply-chain
  attestation and transparency-log practice the signing layer follows (Ch. 4
  §4.8.1, Ch. 6 §6.5.4).
- **A2A Agent Cards; MCP tool schemas** — capability-declaration prior art
  contrasted with the behavioural-constraint future direction (Ch. 6 §6.5.9).
