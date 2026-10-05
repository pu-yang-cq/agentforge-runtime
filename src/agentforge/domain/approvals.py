from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from agentforge.domain.enums import ApprovalRequestStatus

_HEX_DIGITS = frozenset("0123456789abcdef")


def _normalized_text(value: str, *, field: str, max_length: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} cannot be blank")
    if len(normalized) > max_length:
        raise ValueError(f"{field} exceeds maximum length {max_length}")
    return normalized


def _validate_digest(value: str, *, field: str) -> str:
    if len(value) != 64 or any(char not in _HEX_DIGITS for char in value):
        raise ValueError(f"{field} must be a lowercase SHA-256 hex digest")
    return value


def _require_aware(value: datetime, *, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


@dataclass(slots=True)
class ApprovalRequest:
    id: UUID
    run_id: UUID
    tool_call_id: UUID
    external_action_id: UUID | None
    policy_decision_id: UUID
    governance_intent_digest: str
    action_snapshot_digest: str | None
    requested_by_principal: str
    principal_scope: str
    required_approver_role: str
    separation_of_duties: bool
    status: ApprovalRequestStatus
    expires_at: datetime
    created_at: datetime
    decided_at: datetime | None = None

    def __post_init__(self) -> None:
        self.governance_intent_digest = _validate_digest(
            self.governance_intent_digest,
            field="governance_intent_digest",
        )
        if (self.external_action_id is None) != (self.action_snapshot_digest is None):
            raise ValueError(
                "external_action_id and action_snapshot_digest must either both be set or both be null"
            )
        if self.action_snapshot_digest is not None:
            self.action_snapshot_digest = _validate_digest(
                self.action_snapshot_digest,
                field="action_snapshot_digest",
            )
        self.requested_by_principal = _normalized_text(
            self.requested_by_principal,
            field="requested_by_principal",
            max_length=200,
        )
        self.principal_scope = _normalized_text(
            self.principal_scope,
            field="principal_scope",
            max_length=200,
        )
        self.required_approver_role = _normalized_text(
            self.required_approver_role,
            field="required_approver_role",
            max_length=100,
        )
        _require_aware(self.created_at, field="created_at")
        _require_aware(self.expires_at, field="expires_at")
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be later than created_at")
        if self.decided_at is not None:
            _require_aware(self.decided_at, field="decided_at")
        if self.status is ApprovalRequestStatus.PENDING:
            if self.decided_at is not None:
                raise ValueError("PENDING approval request cannot have decided_at")
        elif self.decided_at is None:
            raise ValueError("non-PENDING approval request requires decided_at")

    @property
    def is_side_effect(self) -> bool:
        return self.external_action_id is not None
