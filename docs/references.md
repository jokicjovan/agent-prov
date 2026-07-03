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
4. R. Souza, L. G. Azevedo, V. Lourenço, et al., "Provenance Data in the Machine
   Learning Lifecycle in Computational Science and Engineering," in *Proc. IEEE/ACM
   Workflows in Support of Large-Scale Science (WORKS)*, Denver, CO, USA, 2019.
   arXiv:1910.04223. — Defines the PROV-ML representation; same research line as
   PROV-AGENT, cited to situate the present work as an extension of an established
   trajectory of PROV specialisation.
5. R. Souza and M. Mattoso, "Provenance of Dynamic Adaptations in User-Steered
   Dataflows," in *Provenance and Annotation of Data and Processes (IPAW 2018)*,
   Lecture Notes in Computer Science, vol. 11017, Springer, 2018. — Defines
   PROV-DfA; models human *steering actions* as activities, contrasted in Ch. 2
   with human *oversight of AI output*.
6. V. Cuevas-Vicenttín, B. Ludäscher, P. Missier, et al., *The ProvONE Data Model
   for Scientific Workflow Provenance*, DataONE, 2016.
   https://purl.dataone.org/provone-v1-dev — PROV extension for scientific-workflow
   systems; predates the LLM-agent paradigm.
7. Research Data Alliance, *FAIR4ML: A schema.org-based Metadata Schema for Machine
   Learning Models*, RDA FAIR for Machine Learning (FAIR4ML) Interest Group.
   https://w3id.org/fair4ml — Metadata schema for model registries, not an
   execution-trace standard.

## Provenance standards and vocabularies

8. World Wide Web Consortium, *PROV-O: The PROV Ontology*, W3C Recommendation,
   30 April 2013. https://www.w3.org/TR/prov-o/
9. World Wide Web Consortium, *PROV Model Primer*, W3C Working Group Note,
   30 April 2013. https://www.w3.org/TR/prov-primer/
10. World Wide Web Consortium, *PROV-DM: The PROV Data Model*, W3C Recommendation,
    30 April 2013. https://www.w3.org/TR/prov-dm/

## Content provenance

11. Coalition for Content Provenance and Authenticity, *C2PA Technical
    Specification*, version 2.x. https://c2pa.org/specifications/

## Software supply-chain attestation

Cited as the established provenance-signing practice the optional signing layer
follows (Ch. 4 §4.8.1, Ch. 6 §6.5.4).

12. S. Torres-Arias, H. Afzali, T. K. Kuppusamy, R. Curtmola, and J. Cappos,
    "in-toto: Providing Farm-to-Table Guarantees for Bits and Bytes," in *Proc.
    28th USENIX Security Symposium*, Santa Clara, CA, USA, 2019. — Standard format
    for signed supply-chain attestations.
13. Open Source Security Foundation, *Supply-chain Levels for Software Artifacts
    (SLSA)*, specification. https://slsa.dev — The opinionated layer specifying
    what provenance an attestation must carry.
14. Secure Systems Lab, *DSSE: Dead Simple Signing Envelope*, specification.
    https://github.com/secure-systems-lab/dsse — The signing-envelope pattern the
    detached signature layer follows (bind a typed payload, not the bare digest).
15. Sigstore project, *Sigstore and the Rekor Transparency Log*, specification.
    https://www.sigstore.dev — Keyless signing and transparency-log key identity,
    named as the trust-root direction for future work.

## Agent interoperability protocols

Cited as capability-declaration prior art contrasted with the behavioural-
constraint future direction (Ch. 6 §6.5.9).

16. Anthropic, *Model Context Protocol (MCP)*, specification, 2024.
    https://modelcontextprotocol.io — Declares what tools an agent *can* call.
17. Google, *Agent2Agent (A2A) Protocol* — Agent Cards, specification, 2025.
    https://a2a-protocol.org — Declares an agent's advertised capabilities and
    skills.

## Canonicalisation and timestamping

18. A. Rundgren, B. Jordan, and S. Erdtman, *JSON Canonicalization Scheme (JCS)*,
    RFC 8785, Internet Engineering Task Force, June 2020.
    https://www.rfc-editor.org/rfc/rfc8785
19. C. Adams, P. Cain, D. Pinkas, and R. Zuccherato, *Internet X.509 Public Key
    Infrastructure Time-Stamp Protocol (TSP)*, RFC 3161, Internet Engineering Task
    Force, August 2001. (Cited as the basis for trusted timestamping in future
    work.) https://www.rfc-editor.org/rfc/rfc3161

## Tools

20. LangChain, *LangGraph — Building stateful, multi-actor applications with
    LLMs*, software documentation. https://langchain-ai.github.io/langgraph/ —
    The framework targeted by the reference implementation.
