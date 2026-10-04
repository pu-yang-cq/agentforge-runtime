from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one anchor, found {count}: {old[:120]!r}")
    file.write_text(text.replace(old, new))


def append_text(path: str, marker: str, block: str) -> None:
    file = Path(path)
    text = file.read_text()
    if marker in text:
        raise SystemExit(f"{path}: marker already present: {marker}")
    file.write_text(text + block)


# ---------------------------------------------------------------------------
# Domain vocabulary and explicit Stage-3.2 ToolVersion execution capability.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/domain/enums.py",
    '''class ExternalActionStatus(StrEnum):
''',
    '''class ReconciliationMode(StrEnum):
    AUTHORITATIVE = "AUTHORITATIVE"
    BEST_EFFORT = "BEST_EFFORT"
    NONE = "NONE"


class ExternalActionStatus(StrEnum):
''',
)

replace_once(
    "src/agentforge/domain/enums.py",
    '''    TOOL_PROPOSED = "TOOL_PROPOSED"
    TOOL_STARTED = "TOOL_STARTED"
''',
    '''    TOOL_PROPOSED = "TOOL_PROPOSED"
    ACTION_PREPARED = "ACTION_PREPARED"
    TOOL_STARTED = "TOOL_STARTED"
''',
)

replace_once(
    "src/agentforge/domain/models.py",
    '''    QueueReason,
    RunStatus,
    ToolCallStatus,
    ToolExecutionAttemptStatus,
)
''',
    '''    QueueReason,
    ReconciliationMode,
    RunStatus,
    ToolCallStatus,
    ToolEffectType,
    ToolExecutionAttemptStatus,
)
''',
)

replace_once(
    "src/agentforge/domain/models.py",
    '''@dataclass(frozen=True, slots=True)
class ToolBinding:
    tool_version_id: UUID
    name: str
    read_retry_max_attempts: int = 1
    read_retry_initial_backoff_seconds: int = 1
    read_retry_max_backoff_seconds: int = 30

    def __post_init__(self) -> None:
        if self.read_retry_max_attempts <= 0:
            raise ValueError("read_retry_max_attempts must be positive")
        if self.read_retry_initial_backoff_seconds < 0:
            raise ValueError("read retry initial backoff cannot be negative")
        if self.read_retry_max_backoff_seconds < self.read_retry_initial_backoff_seconds:
            raise ValueError("read retry max backoff cannot be below initial backoff")

    def read_retry_delay_seconds(self, failed_attempt_number: int) -> int:
        if failed_attempt_number <= 0:
            raise ValueError("failed_attempt_number must be positive")
        delay: int = self.read_retry_initial_backoff_seconds * (2 ** (failed_attempt_number - 1))
        return min(delay, self.read_retry_max_backoff_seconds)
''',
    '''@dataclass(frozen=True, slots=True)
class ToolBinding:
    tool_version_id: UUID
    name: str
    read_retry_max_attempts: int = 1
    read_retry_initial_backoff_seconds: int = 1
    read_retry_max_backoff_seconds: int = 30
    effect_type: ToolEffectType = ToolEffectType.READ
    approval_required: bool = False
    allow_no_approval_execution: bool = False
    credential_ref: str | None = None
    idempotency_supported: bool = False
    reconciliation_mode: ReconciliationMode = ReconciliationMode.NONE

    def __post_init__(self) -> None:
        if self.read_retry_max_attempts <= 0:
            raise ValueError("read_retry_max_attempts must be positive")
        if self.read_retry_initial_backoff_seconds < 0:
            raise ValueError("read retry initial backoff cannot be negative")
        if self.read_retry_max_backoff_seconds < self.read_retry_initial_backoff_seconds:
            raise ValueError("read retry max backoff cannot be below initial backoff")
        if self.credential_ref is not None and not self.credential_ref.strip():
            raise ValueError("credential_ref cannot be blank")
        if self.approval_required and self.allow_no_approval_execution:
            raise ValueError("approval-required tool cannot allow no-approval execution")
        if self.effect_type is ToolEffectType.DESTRUCTIVE and self.allow_no_approval_execution:
            raise ValueError("destructive tool cannot allow Stage-3.2 execution")
        if self.effect_type is ToolEffectType.READ and self.allow_no_approval_execution:
            raise ValueError("READ tool cannot be marked for side-effect execution")

    @property
    def stage32_side_effect_executable(self) -> bool:
        return (
            self.effect_type
            in {
                ToolEffectType.WRITE,
                ToolEffectType.EXTERNAL_SIDE_EFFECT,
            }
            and not self.approval_required
            and self.allow_no_approval_execution
        )

    def read_retry_delay_seconds(self, failed_attempt_number: int) -> int:
        if failed_attempt_number <= 0:
            raise ValueError("failed_attempt_number must be positive")
        delay: int = self.read_retry_initial_backoff_seconds * (2 ** (failed_attempt_number - 1))
        return min(delay, self.read_retry_max_backoff_seconds)
''',
)

# ---------------------------------------------------------------------------
# ToolVersion persistence declares execution/credential/idempotency/reconcile
# capability before a side effect can be prepared.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/infrastructure/db/models.py",
    '''from agentforge.domain.enums import (
    ExternalActionStatus,
    QueueReason,
''',
    '''from agentforge.domain.enums import (
    ExternalActionStatus,
    QueueReason,
    ReconciliationMode,
''',
)

replace_once(
    "src/agentforge/infrastructure/db/models.py",
    '''        CheckConstraint(
            "read_retry_max_backoff_seconds >= read_retry_initial_backoff_seconds",
            name="ck_tool_versions_read_retry_backoff_order",
        ),
    )
''',
    '''        CheckConstraint(
            "read_retry_max_backoff_seconds >= read_retry_initial_backoff_seconds",
            name="ck_tool_versions_read_retry_backoff_order",
        ),
        CheckConstraint(
            "NOT (approval_required AND allow_no_approval_execution)",
            name="ck_tool_versions_approval_execution_exclusive",
        ),
        CheckConstraint(
            "credential_ref IS NULL OR length(btrim(credential_ref)) > 0",
            name="ck_tool_versions_nonblank_credential_ref",
        ),
        CheckConstraint(
            "effect_type <> 'DESTRUCTIVE' OR NOT allow_no_approval_execution",
            name="ck_tool_versions_destructive_not_stage32_executable",
        ),
        CheckConstraint(
            "effect_type <> 'READ' OR NOT allow_no_approval_execution",
            name="ck_tool_versions_read_not_side_effect_executable",
        ),
    )
''',
)

replace_once(
    "src/agentforge/infrastructure/db/models.py",
    '''    implementation_ref: Mapped[str] = mapped_column(String(300), nullable=False)
    read_retry_max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
''',
    '''    implementation_ref: Mapped[str] = mapped_column(String(300), nullable=False)
    approval_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    allow_no_approval_execution: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    credential_ref: Mapped[str | None] = mapped_column(String(300), nullable=True)
    idempotency_supported: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    reconciliation_mode: Mapped[ReconciliationMode] = mapped_column(
        Enum(ReconciliationMode, name="reconciliation_mode"),
        nullable=False,
        default=ReconciliationMode.NONE,
        server_default=text("'NONE'"),
    )
    read_retry_max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
''',
)

Path("migrations/versions/0010_side_effect_preparation.py").write_text(
    '''"""add Stage 3.2 side-effect preparation capability

Revision ID: 0010_side_effect_preparation
Revises: 0009_external_action_intent
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_side_effect_preparation"
down_revision: str | None = "0009_external_action_intent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    reconciliation_mode = postgresql.ENUM(
        "AUTHORITATIVE",
        "BEST_EFFORT",
        "NONE",
        name="reconciliation_mode",
    )
    reconciliation_mode.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "tool_versions",
        sa.Column(
            "approval_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "tool_versions",
        sa.Column(
            "allow_no_approval_execution",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "tool_versions",
        sa.Column("credential_ref", sa.String(length=300), nullable=True),
    )
    op.add_column(
        "tool_versions",
        sa.Column(
            "idempotency_supported",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "tool_versions",
        sa.Column(
            "reconciliation_mode",
            postgresql.ENUM(
                "AUTHORITATIVE",
                "BEST_EFFORT",
                "NONE",
                name="reconciliation_mode",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'NONE'"),
        ),
    )

    op.create_check_constraint(
        "ck_tool_versions_approval_execution_exclusive",
        "tool_versions",
        "NOT (approval_required AND allow_no_approval_execution)",
    )
    op.create_check_constraint(
        "ck_tool_versions_nonblank_credential_ref",
        "tool_versions",
        "credential_ref IS NULL OR length(btrim(credential_ref)) > 0",
    )
    op.create_check_constraint(
        "ck_tool_versions_destructive_not_stage32_executable",
        "tool_versions",
        "effect_type <> 'DESTRUCTIVE' OR NOT allow_no_approval_execution",
    )
    op.create_check_constraint(
        "ck_tool_versions_read_not_side_effect_executable",
        "tool_versions",
        "effect_type <> 'READ' OR NOT allow_no_approval_execution",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_tool_versions_read_not_side_effect_executable",
        "tool_versions",
        type_="check",
    )
    op.drop_constraint(
        "ck_tool_versions_destructive_not_stage32_executable",
        "tool_versions",
        type_="check",
    )
    op.drop_constraint(
        "ck_tool_versions_nonblank_credential_ref",
        "tool_versions",
        type_="check",
    )
    op.drop_constraint(
        "ck_tool_versions_approval_execution_exclusive",
        "tool_versions",
        type_="check",
    )
    op.drop_column("tool_versions", "reconciliation_mode")
    op.drop_column("tool_versions", "idempotency_supported")
    op.drop_column("tool_versions", "credential_ref")
    op.drop_column("tool_versions", "allow_no_approval_execution")
    op.drop_column("tool_versions", "approval_required")
    postgresql.ENUM(name="reconciliation_mode").drop(op.get_bind(), checkfirst=True)
'''
)

# ---------------------------------------------------------------------------
# AgentVersion bindings carry immutable ToolVersion execution facts.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/infrastructure/db/mappers.py",
    '''from uuid import UUID

from agentforge.domain.models import AgentVersion, Run, RunMessage, RunState, ToolBinding, ToolCall
''',
    '''from uuid import UUID

from agentforge.domain.enums import ReconciliationMode, ToolEffectType
from agentforge.domain.models import AgentVersion, Run, RunMessage, RunState, ToolBinding, ToolCall
''',
)

replace_once(
    "src/agentforge/infrastructure/db/mappers.py",
    '''    bindings: list[tuple[UUID, str, int, int, int]],
''',
    '''    bindings: list[
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
        ]
    ],
''',
)

replace_once(
    "src/agentforge/infrastructure/db/mappers.py",
    '''            ToolBinding(
                tool_version_id,
                alias,
                retry_max_attempts,
                retry_initial_backoff,
                retry_max_backoff,
            )
            for (
                tool_version_id,
                alias,
                retry_max_attempts,
                retry_initial_backoff,
                retry_max_backoff,
            ) in bindings
''',
    '''            ToolBinding(
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
            ) in bindings
''',
)

replace_once(
    "src/agentforge/infrastructure/db/runtime_store.py",
    '''                        ToolVersionRow.read_retry_max_attempts,
                        ToolVersionRow.read_retry_initial_backoff_seconds,
                        ToolVersionRow.read_retry_max_backoff_seconds,
                    )
''',
    '''                        ToolVersionRow.read_retry_max_attempts,
                        ToolVersionRow.read_retry_initial_backoff_seconds,
                        ToolVersionRow.read_retry_max_backoff_seconds,
                        ToolVersionRow.effect_type,
                        ToolVersionRow.approval_required,
                        ToolVersionRow.allow_no_approval_execution,
                        ToolVersionRow.credential_ref,
                        ToolVersionRow.idempotency_supported,
                        ToolVersionRow.reconciliation_mode,
                    )
''',
)

replace_once(
    "src/agentforge/infrastructure/db/runtime_store.py",
    '''                        retry_max_attempts,
                        retry_initial_backoff,
                        retry_max_backoff,
                    )
                    for (
                        tool_version_id,
                        alias,
                        retry_max_attempts,
                        retry_initial_backoff,
                        retry_max_backoff,
                    ) in rows
''',
    '''                        retry_max_attempts,
                        retry_initial_backoff,
                        retry_max_backoff,
                        effect_type,
                        approval_required,
                        allow_no_approval_execution,
                        credential_ref,
                        idempotency_supported,
                        reconciliation_mode,
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
                    ) in rows
''',
)

# ---------------------------------------------------------------------------
# Coordinator: explicit READ vs side-effect preparation. No side-effect invoke.
# ---------------------------------------------------------------------------
Path("src/agentforge/runtime/tool_coordinator.py").write_text(
    '''from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import uuid4

from agentforge.application.ports import Tool, ToolRegistry
from agentforge.domain.actions import ActionSnapshot, ExternalAction
from agentforge.domain.enums import ToolCallStatus, ToolEffectType
from agentforge.domain.models import AgentVersion, ToolBinding, ToolCall, ToolProposal


@dataclass(slots=True)
class PreparedToolCall:
    call: ToolCall
    tool: Tool
    binding: ToolBinding


@dataclass(slots=True)
class PreparedExternalAction:
    call: ToolCall
    snapshot: ActionSnapshot
    action: ExternalAction
    binding: ToolBinding


class ToolCoordinator:
    """Separate durable acceptance from every physical Tool invocation."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    @staticmethod
    def _binding(name: str, agent_version: AgentVersion) -> ToolBinding:
        matches = [binding for binding in agent_version.tool_bindings if binding.name == name]
        if len(matches) != 1:
            raise PermissionError(f"tool is not uniquely bound to agent version: {name}")
        return matches[0]

    def _resolve_bound_tool(self, binding: ToolBinding, agent_version: AgentVersion) -> Tool:
        tool = self._registry.resolve(binding.name, agent_version.tool_bindings)
        if tool.version_id != binding.tool_version_id:
            raise ValueError("resolved tool version no longer matches immutable binding")
        return tool

    def prepare_model_tool(
        self,
        *,
        proposal: ToolProposal,
        agent_version: AgentVersion,
    ) -> PreparedToolCall | PreparedExternalAction:
        binding = self._binding(proposal.tool_name, agent_version)
        if binding.effect_type is ToolEffectType.READ:
            return self._prepare_read_with_binding(
                proposal=proposal,
                agent_version=agent_version,
                binding=binding,
            )
        return self._prepare_side_effect_with_binding(
            proposal=proposal,
            agent_version=agent_version,
            binding=binding,
        )

    def prepare_read(
        self, *, proposal: ToolProposal, agent_version: AgentVersion
    ) -> PreparedToolCall:
        binding = self._binding(proposal.tool_name, agent_version)
        return self._prepare_read_with_binding(
            proposal=proposal,
            agent_version=agent_version,
            binding=binding,
        )

    def _prepare_read_with_binding(
        self,
        *,
        proposal: ToolProposal,
        agent_version: AgentVersion,
        binding: ToolBinding,
    ) -> PreparedToolCall:
        if binding.effect_type is not ToolEffectType.READ:
            raise PermissionError(f"tool is not a READ ToolVersion: {proposal.tool_name}")
        tool = self._resolve_bound_tool(binding, agent_version)
        call = ToolCall.from_proposal(proposal, tool_version_id=tool.version_id)
        call.ready()
        call.start()
        return PreparedToolCall(call=call, tool=tool, binding=binding)

    def prepare_side_effect(
        self, *, proposal: ToolProposal, agent_version: AgentVersion
    ) -> PreparedExternalAction:
        binding = self._binding(proposal.tool_name, agent_version)
        return self._prepare_side_effect_with_binding(
            proposal=proposal,
            agent_version=agent_version,
            binding=binding,
        )

    def _prepare_side_effect_with_binding(
        self,
        *,
        proposal: ToolProposal,
        agent_version: AgentVersion,
        binding: ToolBinding,
    ) -> PreparedExternalAction:
        if not binding.stage32_side_effect_executable:
            raise PermissionError(
                f"ToolVersion is not Stage-3.2 side-effect executable: {proposal.tool_name}"
            )
        self._resolve_bound_tool(binding, agent_version)
        call = ToolCall.from_proposal(proposal, tool_version_id=binding.tool_version_id)
        call.ready()
        operation_id = uuid4()
        snapshot = ActionSnapshot.create(
            operation_id=operation_id,
            tool_version_id=binding.tool_version_id,
            effect_type=binding.effect_type,
            arguments=proposal.arguments,
            credential_ref=binding.credential_ref,
        )
        action = ExternalAction.create(
            run_id=proposal.run_id,
            tool_call_id=call.id,
            action_snapshot_id=snapshot.id,
            operation_id=operation_id,
        )
        return PreparedExternalAction(
            call=call,
            snapshot=snapshot,
            action=action,
            binding=binding,
        )

    def prepare_recovered_read(
        self, *, call: ToolCall, agent_version: AgentVersion
    ) -> PreparedToolCall:
        if call.status is not ToolCallStatus.READY:
            raise ValueError("recovered READ call must be READY")
        if call.tool_version_id is None:
            raise ValueError("recovered READ call must bind a tool version")
        binding = self._binding(call.tool_name, agent_version)
        if binding.effect_type is not ToolEffectType.READ:
            raise ValueError("recovered ToolCall is not a READ ToolVersion")
        tool = self._resolve_bound_tool(binding, agent_version)
        if tool.version_id != call.tool_version_id:
            raise ValueError("recovered READ call tool version no longer matches binding")
        call.start()
        return PreparedToolCall(call=call, tool=tool, binding=binding)

    async def execute_prepared(self, prepared: PreparedToolCall) -> ToolCall:
        call = prepared.call
        try:
            raw_result = await prepared.tool.invoke(call.arguments)
            encoded = json.dumps(
                raw_result,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            result = json.loads(encoded)
        except Exception as exc:
            call.fail(str(exc))
            raise
        call.succeed(result)
        return call


def tool_result_message_content(result: object) -> str:
    """Canonical JSON representation fed back to the model."""
    return json.dumps(
        result,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
'''
)

# ---------------------------------------------------------------------------
# ExecutionRecorder protocol exposes the atomic intent-preparation transaction.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/application/ports.py",
    '''from agentforge.domain.model_contract import ModelRequest, ModelResponse, ModelToolSpec
from agentforge.domain.models import (
''',
    '''from agentforge.domain.actions import ActionSnapshot, ExternalAction
from agentforge.domain.model_contract import ModelRequest, ModelResponse, ModelToolSpec
from agentforge.domain.models import (
''',
)

replace_once(
    "src/agentforge/application/ports.py",
    '''    async def record_model_tool_denied_and_fail_run(
''',
    '''    async def record_model_side_effect_prepared(
        self,
        invocation: ModelInvocation,
        proposal: ToolProposal,
        call: ToolCall,
        snapshot: ActionSnapshot,
        action: ExternalAction,
        *,
        expected_generation: int,
    ) -> RunState: ...

    async def record_model_tool_denied_and_fail_run(
''',
)

# ---------------------------------------------------------------------------
# In-memory journal + RunManager route side effects to preparation and STOP.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/application/run_manager.py",
    '''from agentforge.application.ports import ExecutionRecorder
from agentforge.domain.enums import (
    EventType,
''',
    '''from agentforge.application.ports import ExecutionRecorder
from agentforge.domain.actions import ActionSnapshot, ExternalAction
from agentforge.domain.enums import (
    EventType,
    ExternalActionStatus,
''',
)

replace_once(
    "src/agentforge/application/run_manager.py",
    '''from agentforge.runtime.tool_coordinator import ToolCoordinator, tool_result_message_content
''',
    '''from agentforge.runtime.tool_coordinator import (
    PreparedExternalAction,
    ToolCoordinator,
    tool_result_message_content,
)
''',
)

replace_once(
    "src/agentforge/application/run_manager.py",
    '''    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_attempts: list[ToolExecutionAttempt] = field(default_factory=list)
    run_state: RunState | None = None
''',
    '''    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_attempts: list[ToolExecutionAttempt] = field(default_factory=list)
    action_snapshots: list[ActionSnapshot] = field(default_factory=list)
    external_actions: list[ExternalAction] = field(default_factory=list)
    run_state: RunState | None = None
''',
)

replace_once(
    "src/agentforge/application/run_manager.py",
    '''        calls = [
            call
            for call in self.tool_calls
            if call.run_id == run_id and call.status is ToolCallStatus.READY
        ]
''',
    '''        side_effect_call_ids = {action.tool_call_id for action in self.external_actions}
        calls = [
            call
            for call in self.tool_calls
            if call.run_id == run_id
            and call.status is ToolCallStatus.READY
            and call.id not in side_effect_call_ids
        ]
''',
)

journal_marker = '''    async def record_model_tool_denied_and_fail_run(
'''
journal_method = '''    async def record_model_side_effect_prepared(
        self,
        invocation: ModelInvocation,
        proposal: ToolProposal,
        call: ToolCall,
        snapshot: ActionSnapshot,
        action: ExternalAction,
        *,
        expected_generation: int,
    ) -> RunState:
        if self.run_state is None:
            raise RuntimeError("journal run state is not seeded")
        if call.status is not ToolCallStatus.READY:
            raise ValueError("side-effect ToolCall must be READY before persistence")
        if call.tool_version_id is None:
            raise ValueError("side-effect ToolCall must bind a tool version")
        if action.status is not ExternalActionStatus.READY:
            raise ValueError("prepared ExternalAction must be READY")
        if snapshot.operation_id != action.operation_id:
            raise ValueError("ActionSnapshot and ExternalAction operation_id mismatch")
        if action.tool_call_id != call.id or action.action_snapshot_id != snapshot.id:
            raise ValueError("ExternalAction references do not match prepared intent")
        if snapshot.tool_version_id != call.tool_version_id:
            raise ValueError("ActionSnapshot tool version does not match ToolCall")
        if snapshot.arguments != call.arguments or call.arguments != proposal.arguments:
            raise ValueError("prepared side-effect arguments diverged")
        self._assert_no_active_tool_calls(call.run_id)
        self._assert_no_started_tool_attempts(call.run_id)
        self._assert_deadline_not_expired(call.run_id)
        self._assert_tool_budget(call.run_id)
        self._persist_completed_invocation(invocation)
        self.events.append(
            DomainEvent(
                invocation.run_id,
                len(self.events) + 1,
                EventType.MODEL_COMPLETED,
                {"turn": invocation.turn, "outcome_type": invocation.outcome_type},
            )
        )
        self.proposals.append(proposal)
        self.events.append(
            DomainEvent(
                proposal.run_id,
                len(self.events) + 1,
                EventType.TOOL_PROPOSED,
                {"proposal_id": str(proposal.id), "tool_name": proposal.tool_name},
            )
        )
        self.run_state.tool_call_count += 1
        self.run_state.state_version += 1
        self.tool_calls.append(call)
        self.action_snapshots.append(snapshot)
        self.external_actions.append(action)
        self.events.append(
            DomainEvent(
                call.run_id,
                len(self.events) + 1,
                EventType.ACTION_PREPARED,
                {
                    "tool_call_id": str(call.id),
                    "external_action_id": str(action.id),
                    "operation_id": str(action.operation_id),
                    "snapshot_digest": snapshot.digest,
                    "effect_type": snapshot.effect_type.value,
                },
            )
        )
        return self.run_state

'''
replace_once(
    "src/agentforge/application/run_manager.py",
    journal_marker,
    journal_method + journal_marker,
)

replace_once(
    "src/agentforge/application/run_manager.py",
    '''            try:
                prepared = self._tools.prepare_read(proposal=proposal, agent_version=agent_version)
            except PermissionError as exc:
''',
    '''            try:
                prepared = self._tools.prepare_model_tool(
                    proposal=proposal,
                    agent_version=agent_version,
                )
            except PermissionError as exc:
''',
)

replace_once(
    "src/agentforge/application/run_manager.py",
    '''            call = prepared.call
            try:
                run_state = await recorder.record_model_tool_started(
''',
    '''            if isinstance(prepared, PreparedExternalAction):
                call = prepared.call
                try:
                    run_state = await recorder.record_model_side_effect_prepared(
                        invocation,
                        proposal,
                        call,
                        prepared.snapshot,
                        prepared.action,
                        expected_generation=expected_generation,
                    )
                except BusinessProgressionBlockedError as exc:
                    run.fail(exc.failure_reason)
                    await recorder.record_model_result_discarded_and_fail_run(
                        invocation,
                        run,
                        exc.failure_reason,
                        expected_generation=expected_generation,
                    )
                    raise RunExecutionFailedError(run.failure_reason) from exc
                # B2 stops at durable intent. Action Commit and physical side-effect
                # execution remain locked for Stage 3.2-C.
                return None

            call = prepared.call
            try:
                run_state = await recorder.record_model_tool_started(
''',
)

# ---------------------------------------------------------------------------
# PostgreSQL preparation transaction: Run lock, fence, budget/deadline,
# authoritative ToolVersion re-check, then ToolCall+Snapshot+Action atomically.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''from agentforge.application.ports import ExecutionRecorder
from agentforge.domain.enums import (
    EventType,
''',
    '''from agentforge.application.ports import ExecutionRecorder
from agentforge.domain.actions import ActionSnapshot, ExternalAction
from agentforge.domain.enums import (
    EventType,
    ExternalActionStatus,
''',
)

replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''    RunStatus,
    ToolCallStatus,
    ToolExecutionAttemptStatus,
)
''',
    '''    RunStatus,
    ToolCallStatus,
    ToolEffectType,
    ToolExecutionAttemptStatus,
)
''',
)

replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''from agentforge.infrastructure.db.models import (
    DomainEventRow,
    ModelInvocationRow,
''',
    '''from agentforge.infrastructure.db.models import (
    ActionSnapshotRow,
    AgentVersionToolRow,
    DomainEventRow,
    ExternalActionRow,
    ModelInvocationRow,
''',
)

replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''    ToolExecutionAttemptRow,
    ToolProposalRow,
)
''',
    '''    ToolExecutionAttemptRow,
    ToolProposalRow,
    ToolVersionRow,
)
''',
)

helper_anchor = '''async def _assert_no_started_model_invocations(session: AsyncSession, run_id: UUID) -> None:
'''
helper = '''async def _lock_stage32_side_effect_tool_version(
    session: AsyncSession,
    *,
    run: RunRow,
    proposal: ToolProposal,
    call: ToolCall,
) -> ToolVersionRow:
    if call.tool_version_id is None:
        raise PermissionError("side-effect ToolCall must bind a ToolVersion")
    row = (
        await session.execute(
            select(ToolVersionRow)
            .join(
                AgentVersionToolRow,
                AgentVersionToolRow.tool_version_id == ToolVersionRow.id,
            )
            .where(
                AgentVersionToolRow.agent_version_id == run.agent_version_id,
                AgentVersionToolRow.tool_alias == proposal.tool_name,
                ToolVersionRow.id == call.tool_version_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise PermissionError("side-effect ToolVersion is no longer bound to the Run AgentVersion")
    if row.effect_type not in {
        ToolEffectType.WRITE,
        ToolEffectType.EXTERNAL_SIDE_EFFECT,
    }:
        raise PermissionError("ToolVersion is not an executable Stage-3.2 side effect")
    if row.approval_required or not row.allow_no_approval_execution:
        raise PermissionError("ToolVersion is not eligible for no-approval Stage-3.2 execution")
    if row.credential_ref is not None and not row.credential_ref.strip():
        raise PermissionError("ToolVersion credential_ref configuration is invalid")
    return row


'''
replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    helper_anchor,
    helper + helper_anchor,
)

replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''                        select(ToolCallRow)
                        .where(
                            ToolCallRow.run_id == run_id,
                            ToolCallRow.status == ToolCallStatus.READY,
                        )
                        .order_by(ToolCallRow.id)
''',
    '''                        select(ToolCallRow)
                        .join(
                            ToolVersionRow,
                            ToolVersionRow.id == ToolCallRow.tool_version_id,
                        )
                        .outerjoin(
                            ExternalActionRow,
                            ExternalActionRow.tool_call_id == ToolCallRow.id,
                        )
                        .where(
                            ToolCallRow.run_id == run_id,
                            ToolCallRow.status == ToolCallStatus.READY,
                            ToolVersionRow.effect_type == ToolEffectType.READ,
                            ExternalActionRow.id.is_(None),
                        )
                        .order_by(ToolCallRow.id)
''',
)

pg_marker = '''    async def record_model_tool_denied_and_fail_run(
'''
pg_method = '''    async def record_model_side_effect_prepared(
        self,
        invocation: ModelInvocation,
        proposal: ToolProposal,
        call: ToolCall,
        snapshot: ActionSnapshot,
        action: ExternalAction,
        *,
        expected_generation: int,
    ) -> RunState:
        """Atomically commit side-effect intent without crossing the effect boundary."""
        self._assert_generation(expected_generation)
        if invocation.status is not ModelInvocationStatus.COMPLETED:
            raise ValueError("model invocation must be COMPLETED before persistence")
        if call.status is not ToolCallStatus.READY:
            raise ValueError("side-effect ToolCall must be READY before persistence")
        if call.tool_version_id is None:
            raise ValueError("side-effect ToolCall must bind a tool version")
        if action.status is not ExternalActionStatus.READY:
            raise ValueError("prepared ExternalAction must be READY")
        if snapshot.operation_id != action.operation_id:
            raise ValueError("ActionSnapshot and ExternalAction operation_id mismatch")
        if action.run_id != call.run_id:
            raise ValueError("ExternalAction run does not match ToolCall")
        if action.tool_call_id != call.id or action.action_snapshot_id != snapshot.id:
            raise ValueError("ExternalAction references do not match prepared intent")
        if snapshot.tool_version_id != call.tool_version_id:
            raise ValueError("ActionSnapshot ToolVersion does not match ToolCall")
        if snapshot.arguments != call.arguments or call.arguments != proposal.arguments:
            raise ValueError("prepared side-effect arguments diverged")

        async with self._sessions() as session, session.begin():
            run_row = await _lock_owned_run(
                session,
                run_id=call.run_id,
                expected_generation=expected_generation,
            )
            await _assert_no_active_tool_calls(session, call.run_id)
            await _assert_no_started_tool_attempts(session, call.run_id)
            state = await _lock_run_state(session, call.run_id)
            await _assert_deadline_not_expired(session, run_row)
            _assert_tool_budget(run_row, state)
            tool_version = await _lock_stage32_side_effect_tool_version(
                session,
                run=run_row,
                proposal=proposal,
                call=call,
            )
            if snapshot.effect_type is not tool_version.effect_type:
                raise ValueError("ActionSnapshot effect type does not match durable ToolVersion")
            if snapshot.credential_ref != tool_version.credential_ref:
                raise ValueError("ActionSnapshot credential_ref does not match durable ToolVersion")

            result = await session.execute(
                update(ModelInvocationRow)
                .where(
                    ModelInvocationRow.id == invocation.id,
                    ModelInvocationRow.run_id == call.run_id,
                    ModelInvocationRow.status == ModelInvocationStatus.STARTED.value,
                )
                .values(
                    status=invocation.status.value,
                    outcome_type=invocation.outcome_type,
                    completed_at=func.clock_timestamp(),
                )
            )
            if cast(CursorResult[Any], result).rowcount != 1:
                raise RuntimeError("model invocation no longer STARTED")

            session.add(
                ToolProposalRow(
                    id=proposal.id,
                    run_id=proposal.run_id,
                    model_invocation_id=proposal.model_invocation_id,
                    tool_name=proposal.tool_name,
                    arguments=proposal.arguments,
                )
            )
            await session.flush()

            state.tool_call_count += 1
            state.state_version += 1
            session.add(
                ToolCallRow(
                    id=call.id,
                    run_id=call.run_id,
                    proposal_id=call.proposal_id,
                    tool_version_id=call.tool_version_id,
                    tool_name=call.tool_name,
                    arguments=call.arguments,
                    status=ToolCallStatus.READY,
                )
            )
            session.add(
                ActionSnapshotRow(
                    id=snapshot.id,
                    format_version=snapshot.format_version,
                    operation_id=snapshot.operation_id,
                    tool_version_id=snapshot.tool_version_id,
                    effect_type=snapshot.effect_type,
                    credential_ref=snapshot.credential_ref,
                    arguments=snapshot.arguments,
                    canonical_json=snapshot.canonical_json,
                    digest=snapshot.digest,
                )
            )
            await session.flush()
            session.add(
                ExternalActionRow(
                    id=action.id,
                    run_id=action.run_id,
                    tool_call_id=action.tool_call_id,
                    action_snapshot_id=action.action_snapshot_id,
                    operation_id=action.operation_id,
                    status=ExternalActionStatus.READY,
                    current_attempt_id=None,
                )
            )

            seqs = list(await _allocate_event_sequences(session, call.run_id, 3))
            session.add_all(
                [
                    DomainEventRow(
                        id=uuid4(),
                        run_id=call.run_id,
                        sequence=seqs[0],
                        event_type=EventType.MODEL_COMPLETED.value,
                        payload={
                            "turn": invocation.turn,
                            "outcome_type": invocation.outcome_type,
                        },
                    ),
                    DomainEventRow(
                        id=uuid4(),
                        run_id=call.run_id,
                        sequence=seqs[1],
                        event_type=EventType.TOOL_PROPOSED.value,
                        payload={
                            "proposal_id": str(proposal.id),
                            "tool_name": proposal.tool_name,
                        },
                    ),
                    DomainEventRow(
                        id=uuid4(),
                        run_id=call.run_id,
                        sequence=seqs[2],
                        event_type=EventType.ACTION_PREPARED.value,
                        payload={
                            "tool_call_id": str(call.id),
                            "external_action_id": str(action.id),
                            "operation_id": str(action.operation_id),
                            "snapshot_digest": snapshot.digest,
                            "effect_type": snapshot.effect_type.value,
                        },
                    ),
                ]
            )
            await session.flush()
            return run_state_from_row(state)

'''
replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    pg_marker,
    pg_method + pg_marker,
)

# ---------------------------------------------------------------------------
# Contract and pure-runtime tests.
# ---------------------------------------------------------------------------
append_text(
    "tests/unit/test_postgres_contracts.py",
    "test_tool_version_declares_stage32_side_effect_capabilities",
    '''


def test_tool_version_declares_stage32_side_effect_capabilities() -> None:
    table = Base.metadata.tables["tool_versions"]
    assert {
        "approval_required",
        "allow_no_approval_execution",
        "credential_ref",
        "idempotency_supported",
        "reconciliation_mode",
    }.issubset(table.c.keys())
    checks = {constraint.name for constraint in table.constraints if constraint.name}
    assert {
        "ck_tool_versions_approval_execution_exclusive",
        "ck_tool_versions_nonblank_credential_ref",
        "ck_tool_versions_destructive_not_stage32_executable",
        "ck_tool_versions_read_not_side_effect_executable",
    }.issubset(checks)
''',
)

replace_once(
    "tests/unit/test_migration_contract.py",
    '''    assert "FK_TOOL_EXECUTION_ATTEMPTS_EXTERNAL_ACTION" in ddl
''',
    '''    assert "FK_TOOL_EXECUTION_ATTEMPTS_EXTERNAL_ACTION" in ddl
    assert "0010_SIDE_EFFECT_PREPARATION" in ddl
    assert "ALLOW_NO_APPROVAL_EXECUTION" in ddl
    assert "RECONCILIATION_MODE" in ddl
    assert "CK_TOOL_VERSIONS_APPROVAL_EXECUTION_EXCLUSIVE" in ddl
''',
)

append_text(
    "tests/unit/test_run_manager.py",
    "test_side_effect_proposal_prepares_durable_intent_without_external_io",
    '''


@pytest.mark.asyncio
async def test_side_effect_proposal_prepares_durable_intent_without_external_io() -> None:
    from agentforge.domain.enums import (
        ExternalActionStatus,
        ReconciliationMode,
        ToolEffectType,
    )

    version_id = uuid4()
    physical_calls = 0

    def forbidden_external_call(summary: str):
        nonlocal physical_calls
        physical_calls += 1
        return {"created": summary}

    registry = InMemoryToolRegistry(
        [
            FunctionTool(
                version_id=version_id,
                name="create_ticket",
                description="create external ticket",
                input_schema={"type": "object"},
                func=forbidden_external_call,
            )
        ]
    )
    model = ScriptedFakeModel([ToolStep("create_ticket", {"summary": "intent only"})])
    manager = RunManager(NativeRunner(model, registry), ToolCoordinator(registry))
    av = AgentVersion(
        uuid4(),
        uuid4(),
        1,
        "prepare external action",
        (
            ToolBinding(
                version_id,
                "create_ticket",
                effect_type=ToolEffectType.EXTERNAL_SIDE_EFFECT,
                allow_no_approval_execution=True,
                credential_ref="credential://jira/test",
                idempotency_supported=True,
                reconciliation_mode=ReconciliationMode.AUTHORITATIVE,
            ),
        ),
    )
    run = Run(uuid4(), av.id, "create a ticket")
    run.queue()
    state = RunState(run.id)
    journal = ExecutionJournal()

    result = await manager.execute(
        run=run,
        run_state=state,
        agent_version=av,
        recorder=journal,
    )

    assert result is None
    assert physical_calls == 0
    assert run.status is RunStatus.RUNNING
    assert state.model_invocations_used == 1
    assert state.tool_call_count == 1
    assert state.tool_attempts_used == 0
    assert len(journal.tool_calls) == 1
    assert journal.tool_calls[0].status is ToolCallStatus.READY
    assert journal.tool_attempts == []
    assert len(journal.action_snapshots) == 1
    assert len(journal.external_actions) == 1
    action = journal.external_actions[0]
    snapshot = journal.action_snapshots[0]
    assert action.status is ExternalActionStatus.READY
    assert action.current_attempt_id is None
    assert action.operation_id == snapshot.operation_id
    assert snapshot.effect_type is ToolEffectType.EXTERNAL_SIDE_EFFECT
    assert snapshot.credential_ref == "credential://jira/test"
    assert EventType.ACTION_PREPARED in [event.type for event in journal.events]
    assert await journal.load_recoverable_read_call(run.id) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("effect_type", "allow_no_approval_execution", "approval_required"),
    [
        ("DESTRUCTIVE", False, False),
        ("EXTERNAL_SIDE_EFFECT", False, False),
        ("EXTERNAL_SIDE_EFFECT", False, True),
    ],
)
async def test_non_executable_side_effect_toolversion_fails_closed(
    effect_type: str,
    allow_no_approval_execution: bool,
    approval_required: bool,
) -> None:
    from agentforge.domain.enums import ToolEffectType

    version_id = uuid4()
    physical_calls = 0

    def forbidden_external_call():
        nonlocal physical_calls
        physical_calls += 1
        return {"unexpected": True}

    registry = InMemoryToolRegistry(
        [
            FunctionTool(
                version_id=version_id,
                name="dangerous_write",
                description="must not execute",
                input_schema={"type": "object"},
                func=forbidden_external_call,
            )
        ]
    )
    model = ScriptedFakeModel([ToolStep("dangerous_write", {})])
    manager = RunManager(NativeRunner(model, registry), ToolCoordinator(registry))
    av = AgentVersion(
        uuid4(),
        uuid4(),
        1,
        "fail closed",
        (
            ToolBinding(
                version_id,
                "dangerous_write",
                effect_type=ToolEffectType(effect_type),
                approval_required=approval_required,
                allow_no_approval_execution=allow_no_approval_execution,
            ),
        ),
    )
    run = Run(uuid4(), av.id, "unsafe")
    run.queue()
    journal = ExecutionJournal()

    with pytest.raises(RunExecutionFailedError):
        await manager.execute(
            run=run,
            run_state=RunState(run.id),
            agent_version=av,
            recorder=journal,
        )

    assert physical_calls == 0
    assert run.status is RunStatus.FAILED
    assert journal.external_actions == []
    assert journal.action_snapshots == []
    assert journal.tool_attempts == []
    assert journal.tool_calls[-1].status is ToolCallStatus.DENIED


@pytest.mark.asyncio
async def test_side_effect_preparation_respects_tool_budget_without_reserving_attempt() -> None:
    from agentforge.domain.enums import ToolEffectType

    version_id = uuid4()
    physical_calls = 0

    def forbidden_external_call():
        nonlocal physical_calls
        physical_calls += 1
        return {"unexpected": True}

    registry = InMemoryToolRegistry(
        [
            FunctionTool(
                version_id=version_id,
                name="write_once",
                description="side effect",
                input_schema={"type": "object"},
                func=forbidden_external_call,
            )
        ]
    )
    model = ScriptedFakeModel([ToolStep("write_once", {})])
    manager = RunManager(NativeRunner(model, registry), ToolCoordinator(registry))
    av = AgentVersion(
        uuid4(),
        uuid4(),
        1,
        "budget",
        (
            ToolBinding(
                version_id,
                "write_once",
                effect_type=ToolEffectType.WRITE,
                allow_no_approval_execution=True,
            ),
        ),
    )
    run = Run(uuid4(), av.id, "budget", max_tool_attempts=1)
    run.queue()
    state = RunState(run.id, tool_attempts_used=1)
    journal = ExecutionJournal()

    with pytest.raises(RunExecutionFailedError, match="BUDGET_EXCEEDED"):
        await manager.execute(
            run=run,
            run_state=state,
            agent_version=av,
            recorder=journal,
        )

    assert physical_calls == 0
    assert state.tool_attempts_used == 1
    assert journal.external_actions == []
    assert journal.action_snapshots == []
    assert journal.tool_attempts == []
    assert journal.tool_calls == []
''',
)

# ---------------------------------------------------------------------------
# PostgreSQL integration: real transaction + zero I/O + recovery guard + fence.
# ---------------------------------------------------------------------------
append_text(
    "tests/integration/test_postgres_runtime.py",
    "test_side_effect_preparation_commits_intent_without_attempt_or_external_io",
    '''


@pytest.mark.asyncio
async def test_side_effect_preparation_commits_intent_without_attempt_or_external_io() -> None:
    from agentforge.domain.enums import (
        ExternalActionStatus,
        ReconciliationMode,
        ToolEffectType,
    )
    from agentforge.infrastructure.db.models import (
        ActionSnapshotRow,
        ExternalActionRow,
        RunStateRow,
        ToolExecutionAttemptRow,
    )

    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)

    side_tool_id = uuid4()
    side_version_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(
            ToolDefinitionRow(
                id=side_tool_id,
                name="create_ticket",
                description="external side effect",
            )
        )
        await session.flush()
        session.add(
            ToolVersionRow(
                id=side_version_id,
                tool_id=side_tool_id,
                version_number=1,
                input_schema={"type": "object"},
                effect_type=ToolEffectType.EXTERNAL_SIDE_EFFECT,
                implementation_ref="tests:create_ticket",
                allow_no_approval_execution=True,
                credential_ref="credential://jira/integration",
                idempotency_supported=True,
                reconciliation_mode=ReconciliationMode.AUTHORITATIVE,
            )
        )
        await session.flush()
        session.add(
            AgentVersionToolRow(
                agent_version_id=DEMO_AGENT_VERSION_ID,
                tool_version_id=side_version_id,
                tool_alias="create_ticket",
            )
        )

    physical_calls = 0

    def forbidden_external_call(summary: str):
        nonlocal physical_calls
        physical_calls += 1
        return {"created": summary}

    registry = InMemoryToolRegistry(
        [
            FunctionTool(
                version_id=DEMO_TOOL_VERSION_ID,
                name="echo_read",
                description="read",
                input_schema={"type": "object"},
                func=lambda text: {"echo": text},
            ),
            FunctionTool(
                version_id=side_version_id,
                name="create_ticket",
                description="external side effect",
                input_schema={"type": "object"},
                func=forbidden_external_call,
            ),
        ]
    )
    store = PostgresRuntimeStore(sessions)
    created = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="prepare side effect",
        idempotency_key="integration-side-effect-preparation-1",
        principal_scope="test-user",
    )
    worker = CoreWorker(
        runtime_store=store,
        recorder_factory=PostgresExecutionRecorderFactory(sessions),
        tool_registry=registry,
        model_factory=lambda _: ScriptedFakeModel(
            [ToolStep("create_ticket", {"summary": "durable intent"})]
        ),
        worker_id="worker-side-effect-b2",
        lease_seconds=30,
    )

    assert await worker.run_once() is True
    assert physical_calls == 0

    refreshed = await store.get_run(created.id)
    assert refreshed is not None
    assert refreshed.status is RunStatus.RUNNING

    async with sessions() as session:
        calls = (
            (
                await session.execute(
                    select(ToolCallRow).where(ToolCallRow.run_id == created.id)
                )
            )
            .scalars()
            .all()
        )
        actions = (
            (
                await session.execute(
                    select(ExternalActionRow).where(ExternalActionRow.run_id == created.id)
                )
            )
            .scalars()
            .all()
        )
        attempts = (
            (
                await session.execute(
                    select(ToolExecutionAttemptRow).where(
                        ToolExecutionAttemptRow.run_id == created.id
                    )
                )
            )
            .scalars()
            .all()
        )
        state = await session.get(RunStateRow, created.id)
        assert state is not None
        assert len(calls) == 1
        assert calls[0].status is ToolCallStatus.READY
        assert len(actions) == 1
        assert actions[0].status is ExternalActionStatus.READY
        assert actions[0].current_attempt_id is None
        snapshot = await session.get(ActionSnapshotRow, actions[0].action_snapshot_id)
        assert snapshot is not None
        assert snapshot.operation_id == actions[0].operation_id
        assert snapshot.effect_type is ToolEffectType.EXTERNAL_SIDE_EFFECT
        assert snapshot.credential_ref == "credential://jira/integration"
        assert attempts == []
        assert state.tool_attempts_used == 0

    recorder = PostgresExecutionRecorder(
        sessions,
        run_id=created.id,
        generation=refreshed.execution_generation,
    )
    assert await recorder.load_recoverable_read_call(created.id) is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_side_effect_preparation_stale_lease_creates_no_intent() -> None:
    from datetime import UTC, datetime, timedelta

    from agentforge.domain.enums import ReconciliationMode, ToolEffectType
    from agentforge.infrastructure.db.models import ActionSnapshotRow, ExternalActionRow, RunRow

    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)

    side_tool_id = uuid4()
    side_version_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(
            ToolDefinitionRow(id=side_tool_id, name="write_stale", description="write")
        )
        await session.flush()
        session.add(
            ToolVersionRow(
                id=side_version_id,
                tool_id=side_tool_id,
                version_number=1,
                input_schema={"type": "object"},
                effect_type=ToolEffectType.WRITE,
                implementation_ref="tests:write_stale",
                allow_no_approval_execution=True,
                idempotency_supported=False,
                reconciliation_mode=ReconciliationMode.NONE,
            )
        )
        await session.flush()
        session.add(
            AgentVersionToolRow(
                agent_version_id=DEMO_AGENT_VERSION_ID,
                tool_version_id=side_version_id,
                tool_alias="write_stale",
            )
        )

    registry = InMemoryToolRegistry(
        [
            FunctionTool(
                version_id=DEMO_TOOL_VERSION_ID,
                name="echo_read",
                description="read",
                input_schema={"type": "object"},
                func=lambda text: {"echo": text},
            ),
            FunctionTool(
                version_id=side_version_id,
                name="write_stale",
                description="write",
                input_schema={"type": "object"},
                func=lambda: {"must": "not run"},
            ),
        ]
    )
    store = PostgresRuntimeStore(sessions)
    await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="stale prep",
        idempotency_key="integration-side-effect-preparation-stale",
        principal_scope="test-user",
    )
    claimed = await store.claim_next_run(worker_id="stale-b2", lease_seconds=30)
    assert claimed is not None
    recorder = PostgresExecutionRecorder(
        sessions,
        run_id=claimed.id,
        generation=claimed.execution_generation,
    )
    _, invocation = await recorder.begin_model_invocation(
        run_id=claimed.id,
        invocation_id=uuid4(),
        expected_generation=claimed.execution_generation,
    )
    proposal = ToolProposal.create(
        run_id=claimed.id,
        model_invocation_id=invocation.id,
        tool_name="write_stale",
        arguments={},
    )
    prepared = ToolCoordinator(registry).prepare_side_effect(
        proposal=proposal,
        agent_version=await store.load_agent_version(claimed.agent_version_id),
    )
    invocation.complete("TOOL_PROPOSAL")

    async with sessions() as session, session.begin():
        row = await session.get(RunRow, claimed.id)
        assert row is not None
        row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)

    with pytest.raises(StaleExecutorError):
        await recorder.record_model_side_effect_prepared(
            invocation,
            proposal,
            prepared.call,
            prepared.snapshot,
            prepared.action,
            expected_generation=claimed.execution_generation,
        )

    async with sessions() as session:
        action_count = await session.scalar(
            select(func.count()).select_from(ExternalActionRow)
        )
        snapshot_count = await session.scalar(
            select(func.count()).select_from(ActionSnapshotRow)
        )
        call_count = await session.scalar(
            select(func.count())
            .select_from(ToolCallRow)
            .where(ToolCallRow.run_id == claimed.id)
        )
    assert action_count == 0
    assert snapshot_count == 0
    assert call_count == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_side_effect_preparation_rechecks_durable_toolversion_eligibility() -> None:
    from agentforge.domain.enums import ReconciliationMode, ToolEffectType
    from agentforge.infrastructure.db.models import ActionSnapshotRow, ExternalActionRow

    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)

    side_tool_id = uuid4()
    side_version_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(
            ToolDefinitionRow(id=side_tool_id, name="write_policy", description="write")
        )
        await session.flush()
        session.add(
            ToolVersionRow(
                id=side_version_id,
                tool_id=side_tool_id,
                version_number=1,
                input_schema={"type": "object"},
                effect_type=ToolEffectType.WRITE,
                implementation_ref="tests:write_policy",
                allow_no_approval_execution=True,
                reconciliation_mode=ReconciliationMode.NONE,
            )
        )
        await session.flush()
        session.add(
            AgentVersionToolRow(
                agent_version_id=DEMO_AGENT_VERSION_ID,
                tool_version_id=side_version_id,
                tool_alias="write_policy",
            )
        )

    registry = InMemoryToolRegistry(
        [
            FunctionTool(
                version_id=DEMO_TOOL_VERSION_ID,
                name="echo_read",
                description="read",
                input_schema={"type": "object"},
                func=lambda text: {"echo": text},
            ),
            FunctionTool(
                version_id=side_version_id,
                name="write_policy",
                description="write",
                input_schema={"type": "object"},
                func=lambda: {"must": "not run"},
            ),
        ]
    )
    store = PostgresRuntimeStore(sessions)
    await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="policy prep",
        idempotency_key="integration-side-effect-preparation-policy",
        principal_scope="test-user",
    )
    claimed = await store.claim_next_run(worker_id="policy-b2", lease_seconds=30)
    assert claimed is not None
    agent_version = await store.load_agent_version(claimed.agent_version_id)
    recorder = PostgresExecutionRecorder(
        sessions,
        run_id=claimed.id,
        generation=claimed.execution_generation,
    )
    _, invocation = await recorder.begin_model_invocation(
        run_id=claimed.id,
        invocation_id=uuid4(),
        expected_generation=claimed.execution_generation,
    )
    proposal = ToolProposal.create(
        run_id=claimed.id,
        model_invocation_id=invocation.id,
        tool_name="write_policy",
        arguments={},
    )
    prepared = ToolCoordinator(registry).prepare_side_effect(
        proposal=proposal,
        agent_version=agent_version,
    )
    invocation.complete("TOOL_PROPOSAL")

    async with sessions() as session, session.begin():
        durable_version = await session.get(ToolVersionRow, side_version_id)
        assert durable_version is not None
        durable_version.allow_no_approval_execution = False

    with pytest.raises(PermissionError):
        await recorder.record_model_side_effect_prepared(
            invocation,
            proposal,
            prepared.call,
            prepared.snapshot,
            prepared.action,
            expected_generation=claimed.execution_generation,
        )

    async with sessions() as session:
        assert (
            await session.scalar(select(func.count()).select_from(ExternalActionRow))
            == 0
        )
        assert (
            await session.scalar(select(func.count()).select_from(ActionSnapshotRow))
            == 0
        )
    await engine.dispose()
''',
)
