"""AI Agent Provenance & Compliance Protocol — reference implementation.

A provenance layer for LLM multi-agent pipelines. It captures automated agent
steps, tool calls, and human oversight interventions as four record types,
seals them into a tamper-evident Pipeline Bundle, and can render the bundle as
an EU AI Act compliance report.

Submodules are imported explicitly (e.g. ``from agent_prov.session import
PipelineSession``); this package root intentionally exposes no eager re-exports
so that importing one component never pulls in the optional ``reporting`` extra.
"""
