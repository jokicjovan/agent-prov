"""Framework adapters for the provenance protocol.

The protocol core (schemas, validation, ``PipelineSession`` and its record
factory, bundle sealing, reporting) is framework-neutral. Each adapter in this
namespace observes a specific agent framework and translates its lifecycle into
calls on ``PipelineSession``'s ``add_*`` factory methods.

``agent_prov.adapters.langchain`` is the reference adapter (LangChain /
LangGraph) and requires the ``langchain`` optional extra
(``pip install agent-prov[langchain]``).
"""
