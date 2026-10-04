from __future__ import annotations

from uuid import UUID

from agentforge.domain.actions import ActionSnapshot, ExternalAction
from agentforge.domain.enums import ReconciliationMode, ToolEffectType
from agentforge.domain.models import AgentVersion, Run, RunMessage, RunState, ToolBinding, ToolCall
from agentforge.infrastructure.db.models import (
    ActionSnapshotRow,
    ExternalActionRow,
    RunMessageRow,
    RunRow,
    RunStateRow,
    ToolCallRow,
)


def run_from_row(row: RunRow) -> Run:
    return Run(
        id=row.id,
        agent_version_id=row.agent_version_id,
        input_text=row.input_text,
        status=row.status,
        queue_reason=row.queue_reason,
        final_output=row.final_output,
        failure_reason=row.failure_reason,
        execution_generation=row.execution_generation,
        owner_worker_id=row.owner_worker_id,
        lease_expires_at=row.lease_expires_at,
        available_at=row.available_at,
        created_at=row.created_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
        max_model_invocations=row.max_model_invocations,
        max_tool_attempts=row.max_tool_attempts,
        deadline_at=row.deadline_at,
    )


def run_state_from_row(row: RunStateRow) -> RunState:
    return RunState(
        run_id=row.run_id,
        state_version=row.state_version,
        turn_count=row.turn_count,
        tool_call_count=row.tool_call_count,
        model_invocations_used=row.model_invocations_used,
        tool_attempts_used=row.tool_attempts_used,
    )


def message_from_row(row: RunMessageRow) -> RunMessage:
    from agentforge.domain.enums import MessageRole

    return RunMessage(
        run_id=row.run_id,
        sequence=row.sequence,
        role=MessageRole(row.role),
        content=row.content,
        source_id=row.source_id,
        created_at=row.created_at,
    )


def agent_version_from_parts(
    *,
    version_id: UUID,
    agent_id: UUID,
    version_number: int,
    instructions: str,
    bindings: list[
        tuple[
            UUID,
            str,
            int,
            int,
            int,
            ToolEffectType,
            bool,
            bool,
            str | None,
            bool,
            ReconciliationMode,
            int,
            int,
            int,
        ]
    ],
) -> AgentVersion:
    return AgentVersion(
        id=version_id,
        agent_id=agent_id,
        version_number=version_number,
        instructions=instructions,
        tool_bindings=tuple(
            ToolBinding(
                tool_version_id,
                alias,
                retry_max_attempts,
                retry_initial_backoff,
                retry_max_backoff,
                effect_type=effect_type,
                approval_required=approval_required,
                allow_no_approval_execution=allow_no_approval_execution,
                credential_ref=credential_ref,
                idempotency_supported=idempotency_supported,
                reconciliation_mode=reconciliation_mode,
                side_effect_retry_max_attempts=side_effect_retry_max_attempts,
                side_effect_retry_initial_backoff_seconds=side_effect_retry_initial_backoff_seconds,
                side_effect_retry_max_backoff_seconds=side_effect_retry_max_backoff_seconds,
            )
            for (
                tool_version_id,
                alias,
                retry_max_attempts,
                retry_initial_backoff,
                retry_max_backoff,
                effect_type,
                approval_required,
                allow_no_approval_execution,
                credential_ref,
                idempotency_supported,
                reconciliation_mode,
                side_effect_retry_max_attempts,
                side_effect_retry_initial_backoff_seconds,
                side_effect_retry_max_backoff_seconds,
            ) in bindings
        ),
    )


def tool_call_from_row(row: ToolCallRow) -> ToolCall:
    return ToolCall(
        id=row.id,
        run_id=row.run_id,
        proposal_id=row.proposal_id,
        tool_version_id=row.tool_version_id,
        tool_name=row.tool_name,
        arguments=dict(row.arguments),
        status=row.status,
        result=row.result,
        error=row.error,
    )


def action_snapshot_from_row(row: ActionSnapshotRow) -> ActionSnapshot:
    return ActionSnapshot(
        id=row.id,
        format_version=row.format_version,
        operation_id=row.operation_id,
        tool_version_id=row.tool_version_id,
        effect_type=row.effect_type,
        credential_ref=row.credential_ref,
        arguments=dict(row.arguments),
        canonical_json=row.canonical_json,
        digest=row.digest,
    )


def external_action_from_row(row: ExternalActionRow) -> ExternalAction:
    return ExternalAction(
        id=row.id,
        run_id=row.run_id,
        tool_call_id=row.tool_call_id,
        action_snapshot_id=row.action_snapshot_id,
        operation_id=row.operation_id,
        status=row.status,
        current_attempt_id=row.current_attempt_id,
    )
