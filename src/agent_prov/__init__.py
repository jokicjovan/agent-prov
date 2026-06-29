"""AI Agent Provenance & Compliance Protocol - reference implementation.

A provenance layer for LLM multi-agent pipelines. It captures automated agent
steps, tool calls, and human oversight interventions as four record types,
seals them into a tamper-evident Pipeline Bundle, and can render the bundle as
an EU AI Act compliance report.

The names re-exported here are the framework-neutral protocol core: build a
session, seal a bundle, validate and independently verify it. They pull in no
optional extra, so ``from agent_prov import PipelineSession, BundleGenerator,
verify_bundle`` works on a bare ``pip install agent-prov``.

Two surfaces are deliberately *not* re-exported here, to keep this import free
of the optional extras:

* ``ProvenanceMiddleware`` (the LangChain/LangGraph adapter) - import from
  ``agent_prov.adapters.langchain``; needs the ``agent-prov[langchain]`` extra.
* ``ComplianceReport`` (PDF reporting) - import from
  ``agent_prov.reporting``; needs the ``agent-prov[reporting]`` extra.
"""

from __future__ import annotations

from agent_prov.bundle_generator import BundleGenerator, compute_bundle_hash
from agent_prov.persistence import EventLog, EventLogError, recover_session
from agent_prov.session import PipelineSession, SessionProtocol, now_iso8601
from agent_prov.validation import (
    ProtocolValidationError,
    validate_bundle,
    validate_record,
)
from agent_prov.verify import VerificationResult, verify_bundle

__all__ = [
    "BundleGenerator",
    "compute_bundle_hash",
    "PipelineSession",
    "SessionProtocol",
    "now_iso8601",
    "EventLog",
    "EventLogError",
    "recover_session",
    "ProtocolValidationError",
    "validate_bundle",
    "validate_record",
    "VerificationResult",
    "verify_bundle",
]
