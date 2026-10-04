from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from agentforge.domain.enums import (
    ActionResolutionOutcome,
    ExternalActionStatus,
    ToolEffectType,
)

ACTION_SNAPSHOT_FORMAT_VERSION = 1
MIN_SAFE_INTEGER = -9_007_199_254_740_991
MAX_SAFE_INTEGER = 9_007_199_254_740_991


def _validate_string(value: str) -> None:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("canonical strings must contain Unicode scalar values only") from exc


def _normalize(value: Any) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        _validate_string(value)
        return value
    if isinstance(value, int):
        if not MIN_SAFE_INTEGER <= value <= MAX_SAFE_INTEGER:
            raise ValueError("integer is outside the AgentForge canonical safe range")
        return value
    if isinstance(value, float):
        raise ValueError("floating-point values are prohibited in ActionSnapshot V1")
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("canonical object keys must be strings")
            _validate_string(key)
            normalized[key] = _normalize(item)
        # RFC 8785 object-name order uses UTF-16 code units.
        return {
            key: normalized[key]
            for key in sorted(normalized, key=lambda item: item.encode("utf-16-be"))
        }
    raise ValueError(f"unsupported ActionSnapshot V1 value type: {type(value).__name__}")


def canonical_json_v1(value: Any) -> bytes:
    normalized = _normalize(value)
    encoded = json.dumps(
        normalized,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=False,
    )
    return encoded.encode("utf-8")


@dataclass(frozen=True, slots=True)
class ActionSnapshot:
    id: UUID
    format_version: int
    operation_id: UUID
    tool_version_id: UUID
    effect_type: ToolEffectType
    credential_ref: str | None
    arguments: dict[str, Any]
    canonical_json: str
    digest: str

    @classmethod
    def create(
        cls,
        *,
        operation_id: UUID,
        tool_version_id: UUID,
        effect_type: ToolEffectType,
        arguments: dict[str, Any],
        credential_ref: str | None,
    ) -> ActionSnapshot:
        if credential_ref is not None:
            _validate_string(credential_ref)
        payload = {
            "arguments": arguments,
            "credential_ref": credential_ref,
            "effect_type": effect_type.value,
            "format_version": ACTION_SNAPSHOT_FORMAT_VERSION,
            "operation_id": str(operation_id),
            "tool_version_id": str(tool_version_id),
        }
        canonical = canonical_json_v1(payload)
        return cls(
            id=uuid4(),
            format_version=ACTION_SNAPSHOT_FORMAT_VERSION,
            operation_id=operation_id,
            tool_version_id=tool_version_id,
            effect_type=effect_type,
            credential_ref=credential_ref,
            arguments=_normalize(arguments),
            canonical_json=canonical.decode("utf-8"),
            digest=sha256(canonical).hexdigest(),
        )


@dataclass(frozen=True, slots=True)
class ActionResolution:
    id: UUID
    action_id: UUID
    outcome: ActionResolutionOutcome
    evidence: dict[str, Any] | None
    reason: str | None
    resolver_identity: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.resolver_identity.strip():
            raise ValueError("resolver_identity cannot be blank")


@dataclass(slots=True)
class ExternalAction:
    id: UUID
    run_id: UUID
    tool_call_id: UUID
    action_snapshot_id: UUID
    operation_id: UUID
    status: ExternalActionStatus = ExternalActionStatus.READY
    current_attempt_id: UUID | None = None

    @classmethod
    def create(
        cls,
        *,
        run_id: UUID,
        tool_call_id: UUID,
        action_snapshot_id: UUID,
        operation_id: UUID,
    ) -> ExternalAction:
        return cls(
            id=uuid4(),
            run_id=run_id,
            tool_call_id=tool_call_id,
            action_snapshot_id=action_snapshot_id,
            operation_id=operation_id,
        )

    def start(self, attempt_id: UUID) -> None:
        if self.status is not ExternalActionStatus.READY or self.current_attempt_id is not None:
            raise ValueError(
                "external action can only execute from READY without an active attempt"
            )
        self.status = ExternalActionStatus.EXECUTING
        self.current_attempt_id = attempt_id

    def succeed(self) -> None:
        if self.status is not ExternalActionStatus.EXECUTING or self.current_attempt_id is None:
            raise ValueError("external action can only succeed from EXECUTING")
        self.status = ExternalActionStatus.SUCCEEDED
        self.current_attempt_id = None

    def mark_unknown(self) -> None:
        if self.status is not ExternalActionStatus.EXECUTING or self.current_attempt_id is None:
            raise ValueError("external action can only become UNKNOWN from EXECUTING")
        self.status = ExternalActionStatus.UNKNOWN
        self.current_attempt_id = None

    def fail_definite_not_executed(self) -> None:
        if self.status is not ExternalActionStatus.EXECUTING or self.current_attempt_id is None:
            raise ValueError("external action can only fail from EXECUTING")
        self.status = ExternalActionStatus.FAILED
        self.current_attempt_id = None

    def retry_ready_after_definite_not_executed(self) -> None:
        if self.status is not ExternalActionStatus.EXECUTING or self.current_attempt_id is None:
            raise ValueError("external action can only retry from EXECUTING")
        self.status = ExternalActionStatus.READY
        self.current_attempt_id = None

    def abort_after_definite_not_executed(self) -> None:
        if self.status is not ExternalActionStatus.EXECUTING or self.current_attempt_id is None:
            raise ValueError("external action can only abort an executing proven-no-effect attempt")
        self.status = ExternalActionStatus.ABORTED
        self.current_attempt_id = None

    def start_reconciliation(self) -> None:
        if self.status not in {
            ExternalActionStatus.UNKNOWN,
            ExternalActionStatus.RECONCILING,
        }:
            raise ValueError("external action can reconcile only from UNKNOWN/RECONCILING")
        if self.current_attempt_id is not None:
            raise ValueError("reconciliation cannot own side-effect current_attempt_id")
        self.status = ExternalActionStatus.RECONCILING

    def reconcile_succeeded(self) -> None:
        if self.status is not ExternalActionStatus.RECONCILING:
            raise ValueError("reconciliation success requires RECONCILING")
        self.status = ExternalActionStatus.SUCCEEDED

    def reconcile_failed(self) -> None:
        if self.status is not ExternalActionStatus.RECONCILING:
            raise ValueError("reconciliation failure requires RECONCILING")
        self.status = ExternalActionStatus.FAILED

    def reconcile_retry_ready(self) -> None:
        if self.status is not ExternalActionStatus.RECONCILING:
            raise ValueError("reconciliation retry-ready requires RECONCILING")
        self.status = ExternalActionStatus.READY

    def manual_review(self) -> None:
        if self.status not in {
            ExternalActionStatus.UNKNOWN,
            ExternalActionStatus.RECONCILING,
        }:
            raise ValueError("manual review requires unresolved action")
        self.status = ExternalActionStatus.MANUAL_REVIEW
        self.current_attempt_id = None

    def reconcile_abort_not_executed(self) -> None:
        if self.status is not ExternalActionStatus.RECONCILING:
            raise ValueError("reconciliation abort requires RECONCILING")
        self.status = ExternalActionStatus.ABORTED

    def resolve_manual(self, outcome: ActionResolutionOutcome) -> None:
        if self.status is not ExternalActionStatus.MANUAL_REVIEW:
            raise ValueError("manual resolution requires MANUAL_REVIEW")
        if outcome is ActionResolutionOutcome.SUCCEEDED:
            self.status = ExternalActionStatus.SUCCEEDED
        elif outcome is ActionResolutionOutcome.FAILED:
            self.status = ExternalActionStatus.FAILED
        elif outcome is ActionResolutionOutcome.ABORTED:
            self.status = ExternalActionStatus.ABORTED
        else:
            raise ValueError(f"unsupported action resolution outcome: {outcome}")

    def abort(self) -> None:
        if self.status is not ExternalActionStatus.READY or self.current_attempt_id is not None:
            raise ValueError("external action can only abort before Action Commit")
        self.status = ExternalActionStatus.ABORTED
