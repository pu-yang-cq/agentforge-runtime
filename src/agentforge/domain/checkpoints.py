from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

CHECKPOINT_SCHEMA_VERSION = 1

# Checkpoints are private acceleration state, never a second source of business
# truth. These keys are rejected recursively so callers cannot accidentally
# persist authority, resolved credentials, or chain-of-thought-like material.
_FORBIDDEN_CHECKPOINT_KEYS = frozenset(
    {
        "action_outcome",
        "cancel_requested",
        "chain_of_thought",
        "external_action_status",
        "reasoning_trace",
        "resolved_credential",
        "resolved_credentials",
        "secret",
        "secrets",
        "tool_call_outcome",
    }
)


def validate_checkpoint_private_payload(value: object, *, path: str = "$") -> None:
    if value is None or isinstance(value, (bool, int, float, str)):
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            validate_checkpoint_private_payload(item, path=f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"checkpoint object key at {path} must be a string")
            normalized = key.strip().lower()
            if normalized in _FORBIDDEN_CHECKPOINT_KEYS:
                raise ValueError(
                    f"checkpoint payload contains forbidden authoritative/private key: {path}.{key}"
                )
            validate_checkpoint_private_payload(item, path=f"{path}.{key}")
        return
    raise ValueError(f"unsupported checkpoint payload type at {path}: {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class RuntimeCheckpoint:
    run_id: UUID
    schema_version: int
    runner_version: str
    run_state_version: int
    execution_spec_identity: str
    working_state: dict[str, Any]
    message_high_water: int
    event_high_water: int
    context_cursor: dict[str, Any] | None
    created_at: datetime
