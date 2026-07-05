"""LangChain / LangGraph adapter for the provenance protocol.

``ProvenanceMiddleware`` is a LangChain ``BaseCallbackHandler``: attach it to a
graph run (``config={"callbacks": [mw]}``) and it observes node, chat-model, and
tool lifecycle events, projecting each into a record via the framework-neutral
``PipelineSession`` factory.

Requires the ``langchain`` optional extra (``pip install agent-prov[langchain]``).
"""

from agent_prov.adapters.langchain.middleware import ProvenanceMiddleware

__all__ = ["ProvenanceMiddleware"]
