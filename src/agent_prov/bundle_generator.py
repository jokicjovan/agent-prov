"""Bundle serialization and integrity-hash helpers."""

from __future__ import annotations

import json
import pathlib
from typing import Any
from uuid import uuid4

from agent_prov._hashing import _now_iso8601, canonical_json_sha256
from agent_prov.validation import validate_bundle


def compute_bundle_hash(bundle: dict) -> str:
    """Return the canonical-JSON SHA-256 of *bundle* with `bundle_hash` removed.

    Excluding the `bundle_hash` field is required to break the chicken-and-egg
    of self-containing the digest. Verification recomputes the same exclusion
    and compares against the stored value (see tests/test_schemas.py).
    """
    bundle_without_hash = {k: v for k, v in bundle.items() if k != "bundle_hash"}
    return canonical_json_sha256(bundle_without_hash)


_VALID_OUTCOMES = frozenset({"completed", "aborted", "error"})


class BundleGenerator:
    """Serializes a PipelineSession into a sealed Pipeline Bundle.

    Args:
        session: The session whose accumulated records will be bundled.
        disclosure_presented: Whether an AI-interaction disclosure was shown
            to the user during this pipeline run (EU AI Act Art. 50(1)).
        outcome: Terminal outcome of the run ('completed' | 'aborted' |
            'error'). When omitted it is derived from the records: 'error' if
            any record has status 'error', otherwise 'completed'. Pass it
            explicitly to record an 'aborted' run (the generator cannot infer
            that the run was stopped early).
    """

    def __init__(
        self,
        session: Any,
        *,
        disclosure_presented: bool = False,
        outcome: str | None = None,
    ) -> None:
        if outcome is not None and outcome not in _VALID_OUTCOMES:
            raise ValueError(
                f"outcome must be one of {sorted(_VALID_OUTCOMES)}; got {outcome!r}"
            )
        self._session = session
        self._disclosure_presented = disclosure_presented
        self._outcome = outcome

    def _resolve_outcome(self) -> str:
        if self._outcome is not None:
            return self._outcome
        if any(r.get("status") == "error" for r in self._session.records):
            return "error"
        return "completed"

    def generate(self) -> dict[str, Any]:
        """Build and seal a Pipeline Bundle from the current session state.

        The sealed bundle is validated through the single protocol validation
        surface (structure of the bundle and every record, plus the conditional
        rules JSON Schema cannot express) before it is returned. This runs at
        seal time — after the observed pipeline has finished — so enforcement
        never crashes the pipeline mid-run.

        Raises:
            ValueError: if the session contains no records (schema requires minItems: 1).
            ProtocolValidationError: if the sealed bundle fails validation.
        """
        if not self._session.records:
            raise ValueError("cannot generate a bundle from an empty session")

        bundle: dict[str, Any] = {
            "bundle_id": str(uuid4()),
            "record_type": "pipeline_bundle",
            "protocol_version": self._session.protocol_version,
            "pipeline_id": self._session.pipeline_id,
            "session_id": self._session.session_id,
            "created_at": _now_iso8601(),
            "disclosure_presented": self._disclosure_presented,
            "outcome": self._resolve_outcome(),
            "records": list(self._session.records),
            "bundle_hash": "",
        }
        bundle["bundle_hash"] = compute_bundle_hash(bundle)
        validate_bundle(bundle)
        return bundle

    def to_file(self, path: str | pathlib.Path) -> dict[str, Any]:
        """Generate the bundle and write it as pretty-printed JSON to *path*.

        Returns the sealed bundle dict.
        """
        bundle = self.generate()
        pathlib.Path(path).write_text(
            json.dumps(bundle, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return bundle
