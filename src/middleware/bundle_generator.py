"""Bundle serialization and integrity-hash helpers."""

from __future__ import annotations

import json
import pathlib
from typing import Any
from uuid import uuid4

from middleware.core import _now_iso8601, canonical_json_sha256


def compute_bundle_hash(bundle: dict) -> str:
    """Return the canonical-JSON SHA-256 of *bundle* with `bundle_hash` removed.

    Excluding the `bundle_hash` field is required to break the chicken-and-egg
    of self-containing the digest. Verification recomputes the same exclusion
    and compares against the stored value (see tests/test_schemas.py).
    """
    bundle_without_hash = {k: v for k, v in bundle.items() if k != "bundle_hash"}
    return canonical_json_sha256(bundle_without_hash)


class BundleGenerator:
    """Serializes a PipelineSession into a sealed Pipeline Bundle.

    Args:
        session: The session whose accumulated records will be bundled.
        disclosure_presented: Whether an AI-interaction disclosure was shown
            to the user during this pipeline run (EU AI Act Art. 50(1)).
    """

    def __init__(
        self,
        session: Any,
        *,
        disclosure_presented: bool = False,
    ) -> None:
        self._session = session
        self._disclosure_presented = disclosure_presented

    def generate(self) -> dict[str, Any]:
        """Build and seal a Pipeline Bundle from the current session state.

        Raises:
            ValueError: if the session contains no records (schema requires minItems: 1).
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
            "records": list(self._session.records),
            "bundle_hash": "",
        }
        bundle["bundle_hash"] = compute_bundle_hash(bundle)
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
