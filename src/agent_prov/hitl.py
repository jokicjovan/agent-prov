"""Human Intervention Record emitter.

A context manager that wraps a human oversight decision point and emits a
Human Intervention Record on exit. The caller supplies the output that was
presented to the reviewer on entry, then commits exactly one decision inside
the ``with`` block via :meth:`HumanReview.approve`, :meth:`HumanReview.edit`,
:meth:`HumanReview.reject`, or :meth:`HumanReview.escalate`.

The action_type ↔ output_after_hash conventions documented in
``schemas/human_intervention.schema.json`` are enforced here:

* ``approved``  → ``output_after_hash`` equals ``output_before_hash``
* ``edited``    → ``output_after_hash`` differs from ``output_before_hash``
* ``rejected``  → ``output_after_hash`` is ``null``
* ``escalated`` → ``output_after_hash`` is ``null``

``parent_record_id`` is taken from ``session.last_record_id`` and must be
non-null: a Human Intervention Record always reviews an upstream record.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from agent_prov._frames import SessionProtocol
from agent_prov._hashing import _now_iso8601, hash_content


_ACTION_TYPES = frozenset({"approved", "rejected", "edited", "escalated"})


class HITLError(RuntimeError):
    """Raised for HITL flow violations: no decision, double decision, bad action."""


class HumanReview:
    """Context manager that captures a human oversight decision.

    Args:
        session: PipelineSession (or any object satisfying SessionProtocol +
            ``last_record_id``) the record will be appended to.
        reviewer_id: One or more identifiers of the natural persons who
            performed the review. Required by EU AI Act Art. 12(3)(d); for
            biometric-identification pipelines Art. 14(5) requires at least
            two reviewers — enforce that at the application layer.
        reviewer_role: Role of the reviewer(s) (e.g. ``"editor"``,
            ``"compliance_officer"``). Free-form to accommodate
            deployment-specific role taxonomies.
        output_before: The agent output as it was presented to the reviewer.
            Hashed canonically to populate ``output_before_hash``.
    """

    def __init__(
        self,
        *,
        session: SessionProtocol,
        reviewer_id: list[str],
        reviewer_role: str,
        output_before: Any,
    ) -> None:
        if not reviewer_id:
            raise HITLError("reviewer_id must contain at least one identifier")
        if not reviewer_role:
            raise HITLError("reviewer_role must be a non-empty string")

        self._session = session
        self._reviewer_id = list(reviewer_id)
        self._reviewer_role = reviewer_role
        self._output_before = output_before
        self._output_before_hash = hash_content(output_before)

        self._decided = False
        self._action_type: str | None = None
        self._output_after_hash: str | None = None
        self._justification_hash: str | None = None
        self._record: dict[str, Any] | None = None

    # ------------------------------------------------------------------ ctx mgr

    def __enter__(self) -> HumanReview:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: Any,
    ) -> None:
        if exc is not None:
            # Body raised — do not emit a half-built record.
            return None
        if not self._decided:
            raise HITLError(
                "HumanReview context exited without a decision; call approve(),"
                " edit(), reject(), or escalate() inside the with-block"
            )

        parent_record_id = getattr(self._session, "last_record_id", None)
        if parent_record_id is None:
            raise HITLError(
                "Human Intervention Record requires a non-null parent_record_id; "
                "no prior record exists in the session"
            )

        record: dict[str, Any] = {
            "record_id": str(uuid4()),
            "record_type": "human_intervention",
            "protocol_version": self._session.protocol_version,
            "pipeline_id": self._session.pipeline_id,
            "session_id": self._session.session_id,
            "reviewer_id": self._reviewer_id,
            "reviewer_role": self._reviewer_role,
            "action_type": self._action_type,
            "output_before_hash": self._output_before_hash,
            "output_after_hash": self._output_after_hash,
            "intervention_timestamp": _now_iso8601(),
            "parent_record_id": parent_record_id,
        }
        if self._justification_hash is not None:
            record["justification_hash"] = self._justification_hash

        self._record = record
        self._session.add_record(record)
        return None

    # ------------------------------------------------------------ decision API

    def approve(self, *, justification: Any | None = None) -> None:
        """Commit an ``approved`` decision; output_after_hash = output_before_hash."""
        self._commit(
            action_type="approved",
            output_after_hash=self._output_before_hash,
            justification=justification,
        )

    def edit(self, new_output: Any, *, justification: Any | None = None) -> None:
        """Commit an ``edited`` decision; the new output must differ from before."""
        new_hash = hash_content(new_output)
        if new_hash == self._output_before_hash:
            raise HITLError(
                "edit() requires output_after to differ from output_before; "
                "use approve() to record an unchanged output"
            )
        self._commit(
            action_type="edited",
            output_after_hash=new_hash,
            justification=justification,
        )

    def reject(self, *, justification: Any | None = None) -> None:
        """Commit a ``rejected`` decision; output_after_hash is null."""
        self._commit(
            action_type="rejected",
            output_after_hash=None,
            justification=justification,
        )

    def escalate(self, *, justification: Any | None = None) -> None:
        """Commit an ``escalated`` decision; output_after_hash is null."""
        self._commit(
            action_type="escalated",
            output_after_hash=None,
            justification=justification,
        )

    # --------------------------------------------------------------- internals

    def _commit(
        self,
        *,
        action_type: str,
        output_after_hash: str | None,
        justification: Any | None,
    ) -> None:
        if self._decided:
            raise HITLError(
                f"decision already committed as {self._action_type!r};"
                " a HumanReview block accepts exactly one decision"
            )
        if action_type not in _ACTION_TYPES:
            raise HITLError(f"unknown action_type {action_type!r}")
        self._decided = True
        self._action_type = action_type
        self._output_after_hash = output_after_hash
        if justification is not None:
            self._justification_hash = hash_content(justification)

    # ------------------------------------------------------------------ access

    @property
    def output_before_hash(self) -> str:
        """SHA-256 of the canonical output as presented to the reviewer."""
        return self._output_before_hash

    @property
    def record(self) -> dict[str, Any] | None:
        """The emitted record, or ``None`` if the context has not exited yet."""
        return self._record
