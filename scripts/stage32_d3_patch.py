from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one anchor, found {count}: {old[:160]!r}")
    file.write_text(text.replace(old, new))


def append_text(path: str, marker: str, block: str) -> None:
    file = Path(path)
    text = file.read_text()
    if marker in text:
        raise SystemExit(f"{path}: marker already present: {marker}")
    file.write_text(text + block)


# ---------------------------------------------------------------------------
# Domain enums and reconciliation value objects.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/domain/enums.py",
    '''class ModelInvocationStatus(StrEnum):
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class MessageRole(StrEnum):
''',
    '''class ModelInvocationStatus(StrEnum):
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ReconciliationAttemptStatus(StrEnum):
    STARTED = "STARTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class ReconciliationResult(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    NOT_EXECUTED = "NOT_EXECUTED"
    UNKNOWN = "UNKNOWN"


class MessageRole(StrEnum):
''',
)

replace_once(
    "src/agentforge/domain/enums.py",
    '''    ACTION_RETRY_READY = "ACTION_RETRY_READY"
    ACTION_ABORTED = "ACTION_ABORTED"
    TOOL_STARTED = "TOOL_STARTED"
''',
    '''    ACTION_RETRY_READY = "ACTION_RETRY_READY"
    ACTION_MANUAL_REVIEW = "ACTION_MANUAL_REVIEW"
    ACTION_ABORTED = "ACTION_ABORTED"
    RECONCILIATION_STARTED = "RECONCILIATION_STARTED"
    RECONCILIATION_SUCCEEDED = "RECONCILIATION_SUCCEEDED"
    RECONCILIATION_FAILED = "RECONCILIATION_FAILED"
    RECONCILIATION_RETRY_SCHEDULED = "RECONCILIATION_RETRY_SCHEDULED"
    TOOL_STARTED = "TOOL_STARTED"
''',
)

replace_once(
    "src/agentforge/domain/enums.py",
    '''class RunStatus(StrEnum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
''',
    '''class RunStatus(StrEnum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_ACTION_RESOLUTION = "WAITING_ACTION_RESOLUTION"
    COMPLETED = "COMPLETED"
''',
)

Path("src/agentforge/domain/reconciliation.py").write_text(
    '''from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from agentforge.domain.enums import (
    ReconciliationAttemptStatus,
    ReconciliationResult,
)
from agentforge.domain.models import utcnow


@dataclass(frozen=True, slots=True)
class ReconciliationOutcome:
    result: ReconciliationResult
    evidence: Any = None


@dataclass(slots=True)
class ReconciliationAttempt:
    id: UUID
    run_id: UUID
    external_action_id: UUID
    attempt_number: int
    execution_generation: int
    status: ReconciliationAttemptStatus = ReconciliationAttemptStatus.STARTED
    result: ReconciliationResult | None = None
    evidence: Any = None
    error: str | None = None
    outcome_reason: str | None = None
    started_at: datetime = field(default_factory=utcnow)
    finished_at: datetime | None = None

    def succeed(self, outcome: ReconciliationOutcome) -> None:
        if self.status is not ReconciliationAttemptStatus.STARTED:
            raise ValueError("reconciliation attempt can only succeed from STARTED")
        self.status = ReconciliationAttemptStatus.SUCCEEDED
        self.result = outcome.result
        self.evidence = outcome.evidence
        self.finished_at = utcnow()

    def fail(self, error: str, *, outcome_reason: str) -> None:
        if self.status is not ReconciliationAttemptStatus.STARTED:
            raise ValueError("reconciliation attempt can only fail from STARTED")
        self.status = ReconciliationAttemptStatus.FAILED
        self.error = error
        self.outcome_reason = outcome_reason
        self.finished_at = utcnow()
'''
)


# ---------------------------------------------------------------------------
# Versioned reconciliation safety policy.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/domain/models.py",
    '''    side_effect_retry_max_backoff_seconds: int = 30

    def __post_init__(self) -> None:
''',
    '''    side_effect_retry_max_backoff_seconds: int = 30
    reconciliation_retry_max_attempts: int = 3
    reconciliation_retry_initial_backoff_seconds: int = 1
    reconciliation_retry_max_backoff_seconds: int = 30

    def __post_init__(self) -> None:
''',
)

replace_once(
    "src/agentforge/domain/models.py",
    '''        if (
            self.side_effect_retry_max_backoff_seconds
            < self.side_effect_retry_initial_backoff_seconds
        ):
            raise ValueError("side-effect retry max backoff cannot be below initial backoff")

    @property
''',
    '''        if (
            self.side_effect_retry_max_backoff_seconds
            < self.side_effect_retry_initial_backoff_seconds
        ):
            raise ValueError("side-effect retry max backoff cannot be below initial backoff")
        if self.reconciliation_retry_max_attempts <= 0:
            raise ValueError("reconciliation_retry_max_attempts must be positive")
        if self.reconciliation_retry_initial_backoff_seconds < 0:
            raise ValueError("reconciliation retry initial backoff cannot be negative")
        if (
            self.reconciliation_retry_max_backoff_seconds
            < self.reconciliation_retry_initial_backoff_seconds
        ):
            raise ValueError("reconciliation retry max backoff cannot be below initial backoff")

    @property
''',
)

replace_once(
    "src/agentforge/domain/models.py",
    '''    def side_effect_retry_delay_seconds(self, failed_attempt_number: int) -> int:
        if failed_attempt_number <= 0:
            raise ValueError("failed_attempt_number must be positive")
        delay: int = self.side_effect_retry_initial_backoff_seconds * (
            2 ** (failed_attempt_number - 1)
        )
        return min(delay, self.side_effect_retry_max_backoff_seconds)


@dataclass(frozen=True, slots=True)
class AgentVersion:
''',
    '''    def side_effect_retry_delay_seconds(self, failed_attempt_number: int) -> int:
        if failed_attempt_number <= 0:
            raise ValueError("failed_attempt_number must be positive")
        delay: int = self.side_effect_retry_initial_backoff_seconds * (
            2 ** (failed_attempt_number - 1)
        )
        return min(delay, self.side_effect_retry_max_backoff_seconds)

    def reconciliation_retry_delay_seconds(self, failed_attempt_number: int) -> int:
        if failed_attempt_number <= 0:
            raise ValueError("failed_attempt_number must be positive")
        delay: int = self.reconciliation_retry_initial_backoff_seconds * (
            2 ** (failed_attempt_number - 1)
        )
        return min(delay, self.reconciliation_retry_max_backoff_seconds)


@dataclass(frozen=True, slots=True)
class AgentVersion:
''',
)


# ---------------------------------------------------------------------------
# ExternalAction / ToolCall reconciliation projections.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/domain/actions.py",
    '''    def abort(self) -> None:
        if self.status is not ExternalActionStatus.READY or self.current_attempt_id is not None:
            raise ValueError("external action can only abort before Action Commit")
        self.status = ExternalActionStatus.ABORTED
''',
    '''    def begin_reconciliation(self) -> None:
        if self.status not in {
            ExternalActionStatus.UNKNOWN,
            ExternalActionStatus.RECONCILING,
        }:
            raise ValueError("external action can only reconcile unresolved truth")
        if self.current_attempt_id is not None:
            raise ValueError("reconciliation cannot overlap a physical side-effect attempt")
        self.status = ExternalActionStatus.RECONCILING

    def reconciliation_succeeded(self) -> None:
        if self.status is not ExternalActionStatus.RECONCILING:
            raise ValueError("reconciliation result requires RECONCILING action")
        self.status = ExternalActionStatus.SUCCEEDED

    def reconciliation_failed_business(self) -> None:
        if self.status is not ExternalActionStatus.RECONCILING:
            raise ValueError("reconciliation result requires RECONCILING action")
        self.status = ExternalActionStatus.FAILED

    def reconciliation_retry_ready(self) -> None:
        if self.status is not ExternalActionStatus.RECONCILING:
            raise ValueError("reconciliation result requires RECONCILING action")
        self.status = ExternalActionStatus.READY

    def manual_review(self) -> None:
        if self.status not in {
            ExternalActionStatus.UNKNOWN,
            ExternalActionStatus.RECONCILING,
        }:
            raise ValueError("manual review requires unresolved external truth")
        self.status = ExternalActionStatus.MANUAL_REVIEW
        self.current_attempt_id = None

    def abort(self) -> None:
        if self.status is not ExternalActionStatus.READY or self.current_attempt_id is not None:
            raise ValueError("external action can only abort before Action Commit")
        self.status = ExternalActionStatus.ABORTED
''',
)

replace_once(
    "src/agentforge/domain/models.py",
    '''    def fail(self, error: str) -> None:
        if self.status is not ToolCallStatus.EXECUTING:
            raise ValueError("tool call can only fail from EXECUTING")
        self.status = ToolCallStatus.FAILED
        self.error = error


@dataclass(slots=True)
class ToolExecutionAttempt:
''',
    '''    def reconcile_succeed(self, result: Any) -> None:
        if self.status is not ToolCallStatus.UNRESOLVED:
            raise ValueError("reconciled success requires UNRESOLVED ToolCall")
        self.status = ToolCallStatus.SUCCEEDED
        self.result = result
        self.error = None

    def reconcile_fail(self, reason: str) -> None:
        if self.status is not ToolCallStatus.UNRESOLVED:
            raise ValueError("reconciled failure requires UNRESOLVED ToolCall")
        self.status = ToolCallStatus.FAILED
        self.error = reason

    def reconcile_retry_ready(self, reason: str) -> None:
        if self.status is not ToolCallStatus.UNRESOLVED:
            raise ValueError("reconciled retry requires UNRESOLVED ToolCall")
        self.status = ToolCallStatus.READY
        self.error = reason

    def reconcile_abort(self, reason: str) -> None:
        if self.status is not ToolCallStatus.UNRESOLVED:
            raise ValueError("reconciled abort requires UNRESOLVED ToolCall")
        self.status = ToolCallStatus.NOT_EXECUTED
        self.error = reason

    def fail(self, error: str) -> None:
        if self.status is not ToolCallStatus.EXECUTING:
            raise ValueError("tool call can only fail from EXECUTING")
        self.status = ToolCallStatus.FAILED
        self.error = error


@dataclass(slots=True)
class ToolExecutionAttempt:
''',
)


# ---------------------------------------------------------------------------
# Reconciliation adapter contract.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/application/ports.py",
    '''from agentforge.domain.model_contract import ModelRequest, ModelResponse, ModelToolSpec
''',
    '''from agentforge.domain.model_contract import ModelRequest, ModelResponse, ModelToolSpec
from agentforge.domain.reconciliation import ReconciliationAttempt, ReconciliationOutcome
''',
)

replace_once(
    "src/agentforge/application/ports.py",
    '''class ToolRegistry(Protocol):
''',
    '''@dataclass(frozen=True, slots=True)
class ReconciliationInvocation:
    operation_id: UUID
    arguments: dict[str, Any]
    credential_ref: str | None


@runtime_checkable
class ReconciliableSideEffectTool(Protocol):
    @property
    def version_id(self) -> UUID: ...

    @property
    def spec(self) -> ModelToolSpec: ...

    async def invoke_side_effect(self, invocation: SideEffectInvocation) -> Any: ...

    async def reconcile_side_effect(
        self,
        invocation: ReconciliationInvocation,
    ) -> ReconciliationOutcome: ...


class ToolRegistry(Protocol):
''',
)

replace_once(
    "src/agentforge/application/ports.py",
    '''    async def load_unknown_external_action(
        self,
        run_id: UUID,
    ) -> tuple[ToolCall, ActionSnapshot, ExternalAction] | None: ...

    async def record_side_effect_attempt_started(
''',
    '''    async def load_unknown_external_action(
        self,
        run_id: UUID,
    ) -> tuple[ToolCall, ActionSnapshot, ExternalAction] | None: ...

    async def load_reconciling_external_action(
        self,
        run_id: UUID,
    ) -> tuple[ToolCall, ActionSnapshot, ExternalAction] | None: ...

    async def begin_reconciliation_attempt(
        self,
        action: ExternalAction,
        *,
        expected_generation: int,
    ) -> ReconciliationAttempt: ...

    async def record_reconciliation_transport_failure(
        self,
        action: ExternalAction,
        attempt: ReconciliationAttempt,
        run: Run,
        *,
        error: str,
        max_attempts: int,
        initial_backoff_seconds: int,
        max_backoff_seconds: int,
        expected_generation: int,
    ) -> bool: ...

    async def record_reconciliation_outcome(
        self,
        call: ToolCall,
        action: ExternalAction,
        attempt: ReconciliationAttempt,
        outcome: ReconciliationOutcome,
        run: Run,
        *,
        reconciliation_mode: str,
        idempotency_supported: bool,
        side_effect_retry_max_attempts: int,
        expected_generation: int,
    ) -> RunMessage | None: ...

    async def record_no_reconciliation_manual_review(
        self,
        call: ToolCall,
        action: ExternalAction,
        run: Run,
        *,
        reason: str,
        expected_generation: int,
    ) -> None: ...

    async def record_side_effect_attempt_started(
''',
)


# ---------------------------------------------------------------------------
# Tool implementation helper and coordinator reconciliation preparation.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/runtime/tools.py",
    '''from agentforge.application.ports import Tool
''',
    '''from agentforge.application.ports import ReconciliationInvocation, SideEffectInvocation, Tool
from agentforge.domain.reconciliation import ReconciliationOutcome
''',
)

append_text(
    "src/agentforge/runtime/tools.py",
    "class ReconciliableSideEffectFunctionTool",
    r'''


class ReconciliableSideEffectFunctionTool(SideEffectFunctionTool):
    """Side-effect adapter with an explicit read-only reconciliation query."""

    def __init__(
        self,
        *,
        version_id: UUID,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        func: Callable[[SideEffectInvocation], Any],
        reconcile_func: Callable[[ReconciliationInvocation], Any],
    ) -> None:
        super().__init__(
            version_id=version_id,
            name=name,
            description=description,
            input_schema=input_schema,
            func=func,
        )
        self._reconcile_func = reconcile_func

    async def reconcile_side_effect(
        self,
        invocation: ReconciliationInvocation,
    ) -> ReconciliationOutcome:
        if inspect.iscoroutinefunction(self._reconcile_func):
            value = await self._reconcile_func(invocation)
        else:
            value = await asyncio.to_thread(self._reconcile_func, invocation)
            if inspect.isawaitable(value):
                value = await value
        if not isinstance(value, ReconciliationOutcome):
            raise TypeError("reconciliation adapter must return ReconciliationOutcome")
        return value
'''
)

replace_once(
    "src/agentforge/runtime/tool_coordinator.py",
    '''from agentforge.application.ports import (
    SideEffectInvocation,
    SideEffectTool,
    Tool,
    ToolRegistry,
)
''',
    '''from agentforge.application.ports import (
    ReconciliableSideEffectTool,
    ReconciliationInvocation,
    SideEffectInvocation,
    SideEffectTool,
    Tool,
    ToolRegistry,
)
''',
)

replace_once(
    "src/agentforge/runtime/tool_coordinator.py",
    '''from agentforge.domain.enums import ExternalActionStatus, ToolCallStatus, ToolEffectType
''',
    '''from agentforge.domain.enums import (
    ExternalActionStatus,
    ReconciliationMode,
    ToolCallStatus,
    ToolEffectType,
)
from agentforge.domain.reconciliation import ReconciliationOutcome
''',
)

replace_once(
    "src/agentforge/runtime/tool_coordinator.py",
    '''    async def execute_prepared(self, prepared: PreparedToolCall) -> ToolCall:
''',
    '''    def prepare_reconciliation(
        self,
        *,
        call: ToolCall,
        snapshot: ActionSnapshot,
        action: ExternalAction,
        agent_version: AgentVersion,
    ) -> tuple[ReconciliableSideEffectTool, ToolBinding]:
        if call.status is not ToolCallStatus.UNRESOLVED:
            raise ValueError("reconciliation requires UNRESOLVED ToolCall")
        if action.status not in {
            ExternalActionStatus.UNKNOWN,
            ExternalActionStatus.RECONCILING,
        }:
            raise ValueError("reconciliation requires unresolved ExternalAction")
        if action.current_attempt_id is not None:
            raise ValueError("reconciliation cannot overlap physical side-effect attempt")
        if call.id != action.tool_call_id or snapshot.id != action.action_snapshot_id:
            raise ValueError("reconciliation durable identity mismatch")
        if action.operation_id != snapshot.operation_id:
            raise ValueError("reconciliation operation identity mismatch")
        if call.tool_version_id != snapshot.tool_version_id:
            raise ValueError("reconciliation ToolVersion mismatch")
        binding = self._binding(call.tool_name, agent_version)
        if binding.tool_version_id != snapshot.tool_version_id:
            raise ValueError("reconciliation binding no longer matches snapshot")
        if binding.reconciliation_mode is ReconciliationMode.NONE:
            raise PermissionError("ToolVersion declares no reconciliation capability")
        tool = self._resolve_bound_tool(binding, agent_version)
        if not isinstance(tool, ReconciliableSideEffectTool):
            raise PermissionError("adapter does not implement reconciliation contract")
        return cast(ReconciliableSideEffectTool, tool), binding

    async def execute_reconciliation(
        self,
        *,
        tool: ReconciliableSideEffectTool,
        snapshot: ActionSnapshot,
        action: ExternalAction,
    ) -> ReconciliationOutcome:
        invocation = ReconciliationInvocation(
            operation_id=action.operation_id,
            arguments=dict(snapshot.arguments),
            credential_ref=snapshot.credential_ref,
        )
        return await tool.reconcile_side_effect(invocation)

    async def execute_prepared(self, prepared: PreparedToolCall) -> ToolCall:
''',
)


# ---------------------------------------------------------------------------
# SQLAlchemy durable model + policy columns.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/infrastructure/db/models.py",
    '''    ReconciliationMode,
    RunStatus,
''',
    '''    ReconciliationAttemptStatus,
    ReconciliationMode,
    ReconciliationResult,
    RunStatus,
''',
)

replace_once(
    "src/agentforge/infrastructure/db/models.py",
    '''        CheckConstraint(
            "side_effect_retry_max_backoff_seconds >= side_effect_retry_initial_backoff_seconds",
            name="ck_tool_versions_side_effect_retry_backoff_order",
        ),
    )
''',
    '''        CheckConstraint(
            "side_effect_retry_max_backoff_seconds >= side_effect_retry_initial_backoff_seconds",
            name="ck_tool_versions_side_effect_retry_backoff_order",
        ),
        CheckConstraint(
            "reconciliation_retry_max_attempts > 0",
            name="ck_tool_versions_positive_reconciliation_retry_attempts",
        ),
        CheckConstraint(
            "reconciliation_retry_initial_backoff_seconds >= 0",
            name="ck_tool_versions_nonnegative_reconciliation_retry_initial_backoff",
        ),
        CheckConstraint(
            "reconciliation_retry_max_backoff_seconds >= reconciliation_retry_initial_backoff_seconds",
            name="ck_tool_versions_reconciliation_retry_backoff_order",
        ),
    )
''',
)

replace_once(
    "src/agentforge/infrastructure/db/models.py",
    '''    side_effect_retry_max_backoff_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30
    )
    created_at: Mapped[datetime] = mapped_column(
''',
    '''    side_effect_retry_max_backoff_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30
    )
    reconciliation_retry_max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3
    )
    reconciliation_retry_initial_backoff_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )
    reconciliation_retry_max_backoff_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30
    )
    created_at: Mapped[datetime] = mapped_column(
''',
)

insert_model_anchor = '''class DomainEventRow(Base):
'''
replace_once(
    "src/agentforge/infrastructure/db/models.py",
    insert_model_anchor,
    '''class ReconciliationAttemptRow(Base):
    __tablename__ = "reconciliation_attempts"
    __table_args__ = (
        UniqueConstraint(
            "external_action_id",
            "attempt_number",
            name="uq_reconciliation_attempts_action_number",
        ),
        Index(
            "uq_reconciliation_attempts_one_started_per_action",
            "external_action_id",
            unique=True,
            postgresql_where=text("status = 'STARTED'"),
        ),
        Index("ix_reconciliation_attempts_run_id", "run_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id", ondelete="RESTRICT"), nullable=False)
    external_action_id: Mapped[UUID] = mapped_column(
        ForeignKey("external_actions.id", ondelete="RESTRICT"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    execution_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ReconciliationAttemptStatus] = mapped_column(
        Enum(ReconciliationAttemptStatus, name="reconciliation_attempt_status"),
        nullable=False,
    )
    result: Mapped[ReconciliationResult | None] = mapped_column(
        Enum(ReconciliationResult, name="reconciliation_result"),
        nullable=True,
    )
    evidence: Mapped[object | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    outcome_reason: Mapped[str | None] = mapped_column(String(120))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DomainEventRow(Base):
''',
)


# ---------------------------------------------------------------------------
# Migration 0013.
# ---------------------------------------------------------------------------
Path("migrations/versions/0013_reconciliation_attempt.py").write_text(
    '''"""add durable reconciliation attempt and safety policy

Revision ID: 0013_reconciliation_attempt
Revises: 0012_side_effect_retry
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_reconciliation_attempt"
down_revision: str | None = "0012_side_effect_retry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE run_status ADD VALUE IF NOT EXISTS 'WAITING_ACTION_RESOLUTION'")

    reconciliation_attempt_status = postgresql.ENUM(
        "STARTED",
        "SUCCEEDED",
        "FAILED",
        name="reconciliation_attempt_status",
    )
    reconciliation_attempt_status.create(op.get_bind(), checkfirst=True)
    reconciliation_result = postgresql.ENUM(
        "SUCCEEDED",
        "FAILED",
        "NOT_EXECUTED",
        "UNKNOWN",
        name="reconciliation_result",
    )
    reconciliation_result.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "tool_versions",
        sa.Column(
            "reconciliation_retry_max_attempts",
            sa.Integer(),
            nullable=False,
            server_default="3",
        ),
    )
    op.add_column(
        "tool_versions",
        sa.Column(
            "reconciliation_retry_initial_backoff_seconds",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "tool_versions",
        sa.Column(
            "reconciliation_retry_max_backoff_seconds",
            sa.Integer(),
            nullable=False,
            server_default="30",
        ),
    )
    op.create_check_constraint(
        "ck_tool_versions_positive_reconciliation_retry_attempts",
        "tool_versions",
        "reconciliation_retry_max_attempts > 0",
    )
    op.create_check_constraint(
        "ck_tool_versions_nonnegative_reconciliation_retry_initial_backoff",
        "tool_versions",
        "reconciliation_retry_initial_backoff_seconds >= 0",
    )
    op.create_check_constraint(
        "ck_tool_versions_reconciliation_retry_backoff_order",
        "tool_versions",
        "reconciliation_retry_max_backoff_seconds >= reconciliation_retry_initial_backoff_seconds",
    )

    op.create_table(
        "reconciliation_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_action_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("execution_generation", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "STARTED",
                "SUCCEEDED",
                "FAILED",
                name="reconciliation_attempt_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "result",
            postgresql.ENUM(
                "SUCCEEDED",
                "FAILED",
                "NOT_EXECUTED",
                "UNKNOWN",
                name="reconciliation_result",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("outcome_reason", sa.String(length=120), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["external_action_id"],
            ["external_actions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "external_action_id",
            "attempt_number",
            name="uq_reconciliation_attempts_action_number",
        ),
    )
    op.create_index(
        "uq_reconciliation_attempts_one_started_per_action",
        "reconciliation_attempts",
        ["external_action_id"],
        unique=True,
        postgresql_where=sa.text("status = 'STARTED'"),
    )
    op.create_index(
        "ix_reconciliation_attempts_run_id",
        "reconciliation_attempts",
        ["run_id"],
        unique=False,
    )

    op.alter_column("tool_versions", "reconciliation_retry_max_attempts", server_default=None)
    op.alter_column(
        "tool_versions",
        "reconciliation_retry_initial_backoff_seconds",
        server_default=None,
    )
    op.alter_column(
        "tool_versions",
        "reconciliation_retry_max_backoff_seconds",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_index("ix_reconciliation_attempts_run_id", table_name="reconciliation_attempts")
    op.drop_index(
        "uq_reconciliation_attempts_one_started_per_action",
        table_name="reconciliation_attempts",
    )
    op.drop_table("reconciliation_attempts")
    op.drop_constraint(
        "ck_tool_versions_reconciliation_retry_backoff_order",
        "tool_versions",
        type_="check",
    )
    op.drop_constraint(
        "ck_tool_versions_nonnegative_reconciliation_retry_initial_backoff",
        "tool_versions",
        type_="check",
    )
    op.drop_constraint(
        "ck_tool_versions_positive_reconciliation_retry_attempts",
        "tool_versions",
        type_="check",
    )
    op.drop_column("tool_versions", "reconciliation_retry_max_backoff_seconds")
    op.drop_column("tool_versions", "reconciliation_retry_initial_backoff_seconds")
    op.drop_column("tool_versions", "reconciliation_retry_max_attempts")
    postgresql.ENUM(name="reconciliation_result").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="reconciliation_attempt_status").drop(op.get_bind(), checkfirst=True)
'''
)


# ---------------------------------------------------------------------------
# Mapper + RuntimeStore binding policy.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/infrastructure/db/mappers.py",
    '''            int,
            int,
            int,
        ]
''',
    '''            int,
            int,
            int,
            int,
            int,
            int,
        ]
''',
)

replace_once(
    "src/agentforge/infrastructure/db/mappers.py",
    '''                side_effect_retry_max_backoff_seconds=side_effect_retry_max_backoff_seconds,
            )
            for (
''',
    '''                side_effect_retry_max_backoff_seconds=side_effect_retry_max_backoff_seconds,
                reconciliation_retry_max_attempts=reconciliation_retry_max_attempts,
                reconciliation_retry_initial_backoff_seconds=reconciliation_retry_initial_backoff_seconds,
                reconciliation_retry_max_backoff_seconds=reconciliation_retry_max_backoff_seconds,
            )
            for (
''',
)

replace_once(
    "src/agentforge/infrastructure/db/mappers.py",
    '''                side_effect_retry_max_attempts,
                side_effect_retry_initial_backoff_seconds,
                side_effect_retry_max_backoff_seconds,
            ) in bindings
''',
    '''                side_effect_retry_max_attempts,
                side_effect_retry_initial_backoff_seconds,
                side_effect_retry_max_backoff_seconds,
                reconciliation_retry_max_attempts,
                reconciliation_retry_initial_backoff_seconds,
                reconciliation_retry_max_backoff_seconds,
            ) in bindings
''',
)

replace_once(
    "src/agentforge/infrastructure/db/runtime_store.py",
    '''                        ToolVersionRow.side_effect_retry_max_attempts,
                        ToolVersionRow.side_effect_retry_initial_backoff_seconds,
                        ToolVersionRow.side_effect_retry_max_backoff_seconds,
                    )
''',
    '''                        ToolVersionRow.side_effect_retry_max_attempts,
                        ToolVersionRow.side_effect_retry_initial_backoff_seconds,
                        ToolVersionRow.side_effect_retry_max_backoff_seconds,
                        ToolVersionRow.reconciliation_retry_max_attempts,
                        ToolVersionRow.reconciliation_retry_initial_backoff_seconds,
                        ToolVersionRow.reconciliation_retry_max_backoff_seconds,
                    )
''',
)

replace_once(
    "src/agentforge/infrastructure/db/runtime_store.py",
    '''                        side_effect_retry_max_attempts,
                        side_effect_retry_initial_backoff_seconds,
                        side_effect_retry_max_backoff_seconds,
                    )
                    for (
''',
    '''                        side_effect_retry_max_attempts,
                        side_effect_retry_initial_backoff_seconds,
                        side_effect_retry_max_backoff_seconds,
                        reconciliation_retry_max_attempts,
                        reconciliation_retry_initial_backoff_seconds,
                        reconciliation_retry_max_backoff_seconds,
                    )
                    for (
''',
)

replace_once(
    "src/agentforge/infrastructure/db/runtime_store.py",
    '''                        side_effect_retry_max_attempts,
                        side_effect_retry_initial_backoff_seconds,
                        side_effect_retry_max_backoff_seconds,
                    ) in rows
''',
    '''                        side_effect_retry_max_attempts,
                        side_effect_retry_initial_backoff_seconds,
                        side_effect_retry_max_backoff_seconds,
                        reconciliation_retry_max_attempts,
                        reconciliation_retry_initial_backoff_seconds,
                        reconciliation_retry_max_backoff_seconds,
                    ) in rows
''',
)


# ---------------------------------------------------------------------------
# ExecutionJournal reconciliation state.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/application/run_manager.py",
    '''from agentforge.domain.model_contract import ModelMessage
''',
    '''from agentforge.domain.model_contract import ModelMessage
from agentforge.domain.reconciliation import ReconciliationAttempt, ReconciliationOutcome
''',
)

replace_once(
    "src/agentforge/application/run_manager.py",
    '''    RunStatus,
    ToolCallStatus,
''',
    '''    ReconciliationMode,
    ReconciliationResult,
    RunStatus,
    ToolCallStatus,
''',
)

replace_once(
    "src/agentforge/application/run_manager.py",
    '''    tool_attempts: list[ToolExecutionAttempt] = field(default_factory=list)
    events: list[DomainEvent] = field(default_factory=list)
''',
    '''    tool_attempts: list[ToolExecutionAttempt] = field(default_factory=list)
    reconciliation_attempts: list[ReconciliationAttempt] = field(default_factory=list)
    events: list[DomainEvent] = field(default_factory=list)
''',
)

replace_once(
    "src/agentforge/application/run_manager.py",
    '''    async def record_side_effect_attempt_started(
        self,
        call: ToolCall,
''',
    '''    async def load_reconciling_external_action(
        self,
        run_id: UUID,
    ) -> tuple[ToolCall, ActionSnapshot, ExternalAction] | None:
        actions = [
            action
            for action in self.external_actions
            if action.run_id == run_id and action.status is ExternalActionStatus.RECONCILING
        ]
        if len(actions) > 1:
            raise RuntimeError("found multiple RECONCILING ExternalActions for one Run")
        if not actions:
            return None
        action = actions[0]
        call = next(item for item in self.tool_calls if item.id == action.tool_call_id)
        snapshot = next(
            item for item in self.action_snapshots if item.id == action.action_snapshot_id
        )
        if call.status is not ToolCallStatus.UNRESOLVED:
            raise RuntimeError("RECONCILING action must project to UNRESOLVED ToolCall")
        return call, snapshot, action

    async def begin_reconciliation_attempt(
        self,
        action: ExternalAction,
        *,
        expected_generation: int,
    ) -> ReconciliationAttempt:
        if action.status not in {
            ExternalActionStatus.UNKNOWN,
            ExternalActionStatus.RECONCILING,
        }:
            raise ValueError("reconciliation start requires unresolved action")
        if any(
            item.external_action_id == action.id
            and item.status.value == "STARTED"
            for item in self.reconciliation_attempts
        ):
            raise RuntimeError("reconciliation attempt already STARTED")
        number = (
            max(
                (
                    item.attempt_number
                    for item in self.reconciliation_attempts
                    if item.external_action_id == action.id
                ),
                default=0,
            )
            + 1
        )
        attempt = ReconciliationAttempt(
            uuid4(),
            action.run_id,
            action.id,
            number,
            expected_generation,
        )
        self.reconciliation_attempts.append(attempt)
        action.begin_reconciliation()
        self.events.append(
            DomainEvent(
                action.run_id,
                len(self.events) + 1,
                EventType.RECONCILIATION_STARTED,
                {
                    "external_action_id": str(action.id),
                    "operation_id": str(action.operation_id),
                    "reconciliation_attempt_id": str(attempt.id),
                    "attempt_number": attempt.attempt_number,
                },
            )
        )
        return attempt

    async def record_reconciliation_transport_failure(
        self,
        action: ExternalAction,
        attempt: ReconciliationAttempt,
        run: Run,
        *,
        error: str,
        max_attempts: int,
        initial_backoff_seconds: int,
        max_backoff_seconds: int,
        expected_generation: int,
    ) -> bool:
        attempt.fail(error, outcome_reason="RECONCILIATION_TRANSPORT_FAILURE")
        self._append_event(
            run,
            EventType.RECONCILIATION_FAILED,
            {
                "external_action_id": str(action.id),
                "reconciliation_attempt_id": str(attempt.id),
                "attempt_number": attempt.attempt_number,
                "error": error,
            },
        )
        if attempt.attempt_number < max_attempts:
            delay = min(
                initial_backoff_seconds * (2 ** (attempt.attempt_number - 1)),
                max_backoff_seconds,
            )
            run.yield_to_queue(QueueReason.RETRY)
            run.available_at = utcnow() + timedelta(seconds=delay)
            self._append_event(
                run,
                EventType.RECONCILIATION_RETRY_SCHEDULED,
                {
                    "external_action_id": str(action.id),
                    "attempt_number": attempt.attempt_number,
                    "delay_seconds": delay,
                },
            )
            return True
        action.manual_review()
        run.status = RunStatus.WAITING_ACTION_RESOLUTION
        run.owner_worker_id = None
        run.lease_expires_at = None
        self._append_event(
            run,
            EventType.ACTION_MANUAL_REVIEW,
            {
                "external_action_id": str(action.id),
                "reason": "RECONCILIATION_RETRY_EXHAUSTED",
            },
        )
        return False

    async def record_reconciliation_outcome(
        self,
        call: ToolCall,
        action: ExternalAction,
        attempt: ReconciliationAttempt,
        outcome: ReconciliationOutcome,
        run: Run,
        *,
        reconciliation_mode: str,
        idempotency_supported: bool,
        side_effect_retry_max_attempts: int,
        expected_generation: int,
    ) -> RunMessage | None:
        attempt.succeed(outcome)
        self._append_event(
            run,
            EventType.RECONCILIATION_SUCCEEDED,
            {
                "external_action_id": str(action.id),
                "reconciliation_attempt_id": str(attempt.id),
                "attempt_number": attempt.attempt_number,
                "result": outcome.result.value,
            },
        )
        mode = ReconciliationMode(reconciliation_mode)
        if outcome.result is ReconciliationResult.SUCCEEDED:
            action.reconciliation_succeeded()
            call.reconcile_succeed(outcome.evidence)
            message = RunMessage(
                run.id,
                0,
                MessageRole.TOOL,
                tool_result_message_content(outcome.evidence),
                call.id,
            )
            self.messages.append(
                RunMessage(
                    message.run_id,
                    len(self.messages) + 1,
                    message.role,
                    message.content,
                    message.source_id,
                )
            )
            return message
        if outcome.result is ReconciliationResult.FAILED:
            action.reconciliation_failed_business()
            call.reconcile_fail("reconciliation proved external action failed")
            run.fail("RECONCILIATION_CONFIRMED_ACTION_FAILED")
            self._append_event(run, EventType.RUN_FAILED, {"reason": run.failure_reason})
            return None
        safe_not_executed = outcome.result is ReconciliationResult.NOT_EXECUTED and (
            mode is ReconciliationMode.AUTHORITATIVE
            or (mode is ReconciliationMode.BEST_EFFORT and idempotency_supported)
        )
        if safe_not_executed:
            physical_attempts = [
                item
                for item in self.tool_attempts
                if item.external_action_id == action.id
            ]
            if len(physical_attempts) < side_effect_retry_max_attempts:
                assert self.run_state is not None
                if self.run_state.tool_attempts_used >= run.max_tool_attempts:
                    action.status = ExternalActionStatus.ABORTED
                    call.reconcile_abort("BUDGET_EXCEEDED: max_tool_attempts exhausted")
                    run.fail("BUDGET_EXCEEDED: max_tool_attempts exhausted")
                elif utcnow() >= run.deadline_at:
                    action.status = ExternalActionStatus.ABORTED
                    call.reconcile_abort("DEADLINE_EXCEEDED: run deadline has expired")
                    run.fail("DEADLINE_EXCEEDED: run deadline has expired")
                else:
                    action.reconciliation_retry_ready()
                    call.reconcile_retry_ready(
                        "reconciliation proved previous side effect NOT_EXECUTED"
                    )
                    return None
            else:
                action.status = ExternalActionStatus.ABORTED
                call.reconcile_abort(
                    "SIDE_EFFECT_RETRY_EXHAUSTED: versioned safe retry attempts exhausted"
                )
                run.fail("SIDE_EFFECT_RETRY_EXHAUSTED: versioned safe retry attempts exhausted")
            self._append_event(run, EventType.RUN_FAILED, {"reason": run.failure_reason})
            return None

        action.manual_review()
        run.status = RunStatus.WAITING_ACTION_RESOLUTION
        run.owner_worker_id = None
        run.lease_expires_at = None
        self._append_event(
            run,
            EventType.ACTION_MANUAL_REVIEW,
            {
                "external_action_id": str(action.id),
                "reason": (
                    "AUTHORITATIVE_UNKNOWN_CONTRACT_VIOLATION"
                    if mode is ReconciliationMode.AUTHORITATIVE
                    else "RECONCILIATION_RESULT_REQUIRES_MANUAL_REVIEW"
                ),
            },
        )
        return None

    async def record_no_reconciliation_manual_review(
        self,
        call: ToolCall,
        action: ExternalAction,
        run: Run,
        *,
        reason: str,
        expected_generation: int,
    ) -> None:
        if call.status is not ToolCallStatus.UNRESOLVED:
            raise ValueError("manual review requires UNRESOLVED ToolCall")
        action.manual_review()
        run.status = RunStatus.WAITING_ACTION_RESOLUTION
        run.owner_worker_id = None
        run.lease_expires_at = None
        self._append_event(
            run,
            EventType.ACTION_MANUAL_REVIEW,
            {"external_action_id": str(action.id), "reason": reason},
        )

    async def record_side_effect_attempt_started(
        self,
        call: ToolCall,
''',
)


# ---------------------------------------------------------------------------
# PostgreSQL recorder imports and helpers.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''    ModelInvocationStatus,
    QueueReason,
''',
    '''    ModelInvocationStatus,
    ReconciliationAttemptStatus,
    ReconciliationMode,
    ReconciliationResult,
    QueueReason,
''',
)

replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''from agentforge.domain.models import (
''',
    '''from agentforge.domain.reconciliation import ReconciliationAttempt, ReconciliationOutcome
from agentforge.domain.models import (
''',
)

replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''    ModelInvocationRow,
    RunCounterRow,
''',
    '''    ModelInvocationRow,
    ReconciliationAttemptRow,
    RunCounterRow,
''',
)

replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''async def _next_tool_attempt_number(session: AsyncSession, tool_call_id: UUID) -> int:
''',
    '''async def _next_reconciliation_attempt_number(
    session: AsyncSession,
    external_action_id: UUID,
) -> int:
    current = await session.scalar(
        select(func.max(ReconciliationAttemptRow.attempt_number)).where(
            ReconciliationAttemptRow.external_action_id == external_action_id
        )
    )
    return int(current or 0) + 1


async def _next_tool_attempt_number(session: AsyncSession, tool_call_id: UUID) -> int:
''',
)


# ---------------------------------------------------------------------------
# PostgreSQL recorder reconciliation methods.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''    async def record_side_effect_attempt_started(
        self,
        call: ToolCall,
''',
    '''    async def load_reconciling_external_action(
        self,
        run_id: UUID,
    ) -> tuple[ToolCall, ActionSnapshot, ExternalAction] | None:
        if run_id != self._run_id:
            raise ValueError("recorder is scoped to one run")
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(ExternalActionRow, ToolCallRow, ActionSnapshotRow)
                    .join(ToolCallRow, ToolCallRow.id == ExternalActionRow.tool_call_id)
                    .join(
                        ActionSnapshotRow,
                        ActionSnapshotRow.id == ExternalActionRow.action_snapshot_id,
                    )
                    .where(
                        ExternalActionRow.run_id == run_id,
                        ExternalActionRow.status == ExternalActionStatus.RECONCILING,
                        ExternalActionRow.current_attempt_id.is_(None),
                        ToolCallRow.status == ToolCallStatus.UNRESOLVED,
                    )
                )
            ).all()
        if len(rows) > 1:
            raise RuntimeError("found multiple RECONCILING ExternalActions for one Run")
        if not rows:
            return None
        action_row, call_row, snapshot_row = rows[0]
        return (
            tool_call_from_row(call_row),
            action_snapshot_from_row(snapshot_row),
            external_action_from_row(action_row),
        )

    async def begin_reconciliation_attempt(
        self,
        action: ExternalAction,
        *,
        expected_generation: int,
    ) -> ReconciliationAttempt:
        self._assert_generation(expected_generation)
        attempt_id = uuid4()
        async with self._sessions() as session, session.begin():
            await _lock_owned_run(
                session,
                run_id=action.run_id,
                expected_generation=expected_generation,
            )
            action_row = (
                await session.execute(
                    select(ExternalActionRow)
                    .where(
                        ExternalActionRow.id == action.id,
                        ExternalActionRow.run_id == action.run_id,
                    )
                    .with_for_update()
                )
            ).scalar_one()
            if action_row.status not in {
                ExternalActionStatus.UNKNOWN,
                ExternalActionStatus.RECONCILING,
            }:
                raise RuntimeError("ExternalAction is not eligible for reconciliation")
            started = await session.scalar(
                select(ReconciliationAttemptRow.id)
                .where(
                    ReconciliationAttemptRow.external_action_id == action.id,
                    ReconciliationAttemptRow.status == ReconciliationAttemptStatus.STARTED,
                )
                .limit(1)
            )
            if started is not None:
                raise RuntimeError("reconciliation attempt already STARTED")
            number = await _next_reconciliation_attempt_number(session, action.id)
            session.add(
                ReconciliationAttemptRow(
                    id=attempt_id,
                    run_id=action.run_id,
                    external_action_id=action.id,
                    attempt_number=number,
                    execution_generation=expected_generation,
                    status=ReconciliationAttemptStatus.STARTED,
                )
            )
            action_row.status = ExternalActionStatus.RECONCILING
            action_row.updated_at = func.clock_timestamp()
            seq = next(iter(await _allocate_event_sequences(session, action.run_id, 1)))
            session.add(
                DomainEventRow(
                    id=uuid4(),
                    run_id=action.run_id,
                    sequence=seq,
                    event_type=EventType.RECONCILIATION_STARTED.value,
                    payload={
                        "external_action_id": str(action.id),
                        "operation_id": str(action.operation_id),
                        "reconciliation_attempt_id": str(attempt_id),
                        "attempt_number": number,
                    },
                )
            )
            await session.flush()
        action.begin_reconciliation()
        return ReconciliationAttempt(
            attempt_id,
            action.run_id,
            action.id,
            number,
            expected_generation,
        )

    async def record_reconciliation_transport_failure(
        self,
        action: ExternalAction,
        attempt: ReconciliationAttempt,
        run: Run,
        *,
        error: str,
        max_attempts: int,
        initial_backoff_seconds: int,
        max_backoff_seconds: int,
        expected_generation: int,
    ) -> bool:
        self._assert_generation(expected_generation)
        async with self._sessions() as session, session.begin():
            run_row = await _lock_owned_run(
                session,
                run_id=run.id,
                expected_generation=expected_generation,
            )
            action_row = (
                await session.execute(
                    select(ExternalActionRow)
                    .where(ExternalActionRow.id == action.id)
                    .with_for_update()
                )
            ).scalar_one()
            attempt_row = (
                await session.execute(
                    select(ReconciliationAttemptRow)
                    .where(
                        ReconciliationAttemptRow.id == attempt.id,
                        ReconciliationAttemptRow.external_action_id == action.id,
                    )
                    .with_for_update()
                )
            ).scalar_one()
            if (
                action_row.status is not ExternalActionStatus.RECONCILING
                or attempt_row.status is not ReconciliationAttemptStatus.STARTED
            ):
                raise RuntimeError("reconciliation transport result lost current authorization")
            db_now = await _database_now(session)
            attempt_row.status = ReconciliationAttemptStatus.FAILED
            attempt_row.error = error
            attempt_row.outcome_reason = "RECONCILIATION_TRANSPORT_FAILURE"
            attempt_row.finished_at = db_now
            seqs_count = 1
            scheduled = attempt.attempt_number < max_attempts
            if scheduled:
                delay = min(
                    initial_backoff_seconds * (2 ** (attempt.attempt_number - 1)),
                    max_backoff_seconds,
                )
                run_row.status = RunStatus.QUEUED
                run_row.queue_reason = QueueReason.RETRY
                run_row.available_at = db_now + timedelta(seconds=delay)
                run_row.owner_worker_id = None
                run_row.lease_expires_at = None
                seqs_count = 2
            else:
                action_row.status = ExternalActionStatus.MANUAL_REVIEW
                action_row.updated_at = db_now
                run_row.status = RunStatus.WAITING_ACTION_RESOLUTION
                run_row.queue_reason = None
                run_row.available_at = None
                run_row.owner_worker_id = None
                run_row.lease_expires_at = None
                seqs_count = 2
            seqs = list(await _allocate_event_sequences(session, run.id, seqs_count))
            session.add(
                DomainEventRow(
                    id=uuid4(),
                    run_id=run.id,
                    sequence=seqs[0],
                    event_type=EventType.RECONCILIATION_FAILED.value,
                    payload={
                        "external_action_id": str(action.id),
                        "reconciliation_attempt_id": str(attempt.id),
                        "attempt_number": attempt.attempt_number,
                        "error": error,
                    },
                )
            )
            if scheduled:
                session.add(
                    DomainEventRow(
                        id=uuid4(),
                        run_id=run.id,
                        sequence=seqs[1],
                        event_type=EventType.RECONCILIATION_RETRY_SCHEDULED.value,
                        payload={
                            "external_action_id": str(action.id),
                            "attempt_number": attempt.attempt_number,
                            "delay_seconds": delay,
                        },
                    )
                )
            else:
                session.add(
                    DomainEventRow(
                        id=uuid4(),
                        run_id=run.id,
                        sequence=seqs[1],
                        event_type=EventType.ACTION_MANUAL_REVIEW.value,
                        payload={
                            "external_action_id": str(action.id),
                            "reason": "RECONCILIATION_RETRY_EXHAUSTED",
                        },
                    )
                )
            await session.flush()
        attempt.fail(error, outcome_reason="RECONCILIATION_TRANSPORT_FAILURE")
        if scheduled:
            run.status = RunStatus.QUEUED
            run.queue_reason = QueueReason.RETRY
            run.owner_worker_id = None
            run.lease_expires_at = None
            return True
        action.manual_review()
        run.status = RunStatus.WAITING_ACTION_RESOLUTION
        run.queue_reason = None
        run.owner_worker_id = None
        run.lease_expires_at = None
        return False

    async def record_reconciliation_outcome(
        self,
        call: ToolCall,
        action: ExternalAction,
        attempt: ReconciliationAttempt,
        outcome: ReconciliationOutcome,
        run: Run,
        *,
        reconciliation_mode: str,
        idempotency_supported: bool,
        side_effect_retry_max_attempts: int,
        expected_generation: int,
    ) -> RunMessage | None:
        self._assert_generation(expected_generation)
        mode = ReconciliationMode(reconciliation_mode)
        message: RunMessage | None = None
        async with self._sessions() as session, session.begin():
            run_row = await _lock_owned_run(
                session,
                run_id=run.id,
                expected_generation=expected_generation,
            )
            action_row = (
                await session.execute(
                    select(ExternalActionRow)
                    .where(ExternalActionRow.id == action.id)
                    .with_for_update()
                )
            ).scalar_one()
            call_row = (
                await session.execute(
                    select(ToolCallRow)
                    .where(ToolCallRow.id == call.id)
                    .with_for_update()
                )
            ).scalar_one()
            attempt_row = (
                await session.execute(
                    select(ReconciliationAttemptRow)
                    .where(
                        ReconciliationAttemptRow.id == attempt.id,
                        ReconciliationAttemptRow.external_action_id == action.id,
                    )
                    .with_for_update()
                )
            ).scalar_one()
            if (
                action_row.status is not ExternalActionStatus.RECONCILING
                or call_row.status is not ToolCallStatus.UNRESOLVED
                or attempt_row.status is not ReconciliationAttemptStatus.STARTED
            ):
                raise RuntimeError("reconciliation outcome lost current authorization")
            db_now = await _database_now(session)
            attempt_row.status = ReconciliationAttemptStatus.SUCCEEDED
            attempt_row.result = outcome.result
            attempt_row.evidence = outcome.evidence
            attempt_row.finished_at = db_now

            event_count = 1
            manual_reason: str | None = None
            if outcome.result is ReconciliationResult.SUCCEEDED:
                action_row.status = ExternalActionStatus.SUCCEEDED
                call_row.status = ToolCallStatus.SUCCEEDED
                call_row.result = outcome.evidence
                call_row.error = None
                message_seq = await _allocate_message_sequence(session, run.id)
                session.add(
                    RunMessageRow(
                        id=uuid4(),
                        run_id=run.id,
                        sequence=message_seq,
                        role=MessageRole.TOOL.value,
                        content=tool_result_message_content(outcome.evidence),
                        source_id=call.id,
                    )
                )
                message = RunMessage(
                    run.id,
                    message_seq,
                    MessageRole.TOOL,
                    tool_result_message_content(outcome.evidence),
                    call.id,
                )
            elif outcome.result is ReconciliationResult.FAILED:
                action_row.status = ExternalActionStatus.FAILED
                call_row.status = ToolCallStatus.FAILED
                call_row.error = "reconciliation proved external action failed"
                run_row.status = RunStatus.FAILED
                run_row.failure_reason = "RECONCILIATION_CONFIRMED_ACTION_FAILED"
                run_row.completed_at = db_now
                run_row.owner_worker_id = None
                run_row.lease_expires_at = None
                event_count = 2
            elif outcome.result is ReconciliationResult.NOT_EXECUTED and (
                mode is ReconciliationMode.AUTHORITATIVE
                or (mode is ReconciliationMode.BEST_EFFORT and idempotency_supported)
            ):
                physical_attempt_count = await session.scalar(
                    select(func.count())
                    .select_from(ToolExecutionAttemptRow)
                    .where(ToolExecutionAttemptRow.external_action_id == action.id)
                )
                state = await _lock_run_state(session, run.id)
                if int(physical_attempt_count or 0) >= side_effect_retry_max_attempts:
                    action_row.status = ExternalActionStatus.ABORTED
                    call_row.status = ToolCallStatus.NOT_EXECUTED
                    call_row.error = (
                        "SIDE_EFFECT_RETRY_EXHAUSTED: versioned safe retry attempts exhausted"
                    )
                    run_row.status = RunStatus.FAILED
                    run_row.failure_reason = call_row.error
                    run_row.completed_at = db_now
                    run_row.owner_worker_id = None
                    run_row.lease_expires_at = None
                    event_count = 2
                elif state.tool_attempts_used >= run_row.max_tool_attempts:
                    action_row.status = ExternalActionStatus.ABORTED
                    call_row.status = ToolCallStatus.NOT_EXECUTED
                    call_row.error = "BUDGET_EXCEEDED: max_tool_attempts exhausted"
                    run_row.status = RunStatus.FAILED
                    run_row.failure_reason = call_row.error
                    run_row.completed_at = db_now
                    run_row.owner_worker_id = None
                    run_row.lease_expires_at = None
                    event_count = 2
                elif db_now >= run_row.deadline_at:
                    action_row.status = ExternalActionStatus.ABORTED
                    call_row.status = ToolCallStatus.NOT_EXECUTED
                    call_row.error = "DEADLINE_EXCEEDED: run deadline has expired"
                    run_row.status = RunStatus.FAILED
                    run_row.failure_reason = call_row.error
                    run_row.completed_at = db_now
                    run_row.owner_worker_id = None
                    run_row.lease_expires_at = None
                    event_count = 2
                else:
                    action_row.status = ExternalActionStatus.READY
                    call_row.status = ToolCallStatus.READY
                    call_row.error = "reconciliation proved previous side effect NOT_EXECUTED"
            else:
                action_row.status = ExternalActionStatus.MANUAL_REVIEW
                run_row.status = RunStatus.WAITING_ACTION_RESOLUTION
                run_row.queue_reason = None
                run_row.available_at = None
                run_row.owner_worker_id = None
                run_row.lease_expires_at = None
                manual_reason = (
                    "AUTHORITATIVE_UNKNOWN_CONTRACT_VIOLATION"
                    if mode is ReconciliationMode.AUTHORITATIVE
                    else "RECONCILIATION_RESULT_REQUIRES_MANUAL_REVIEW"
                )
                event_count = 2

            action_row.current_attempt_id = None
            action_row.updated_at = db_now
            seqs = list(await _allocate_event_sequences(session, run.id, event_count))
            session.add(
                DomainEventRow(
                    id=uuid4(),
                    run_id=run.id,
                    sequence=seqs[0],
                    event_type=EventType.RECONCILIATION_SUCCEEDED.value,
                    payload={
                        "external_action_id": str(action.id),
                        "reconciliation_attempt_id": str(attempt.id),
                        "attempt_number": attempt.attempt_number,
                        "result": outcome.result.value,
                    },
                )
            )
            if event_count == 2:
                if manual_reason is not None:
                    event_type = EventType.ACTION_MANUAL_REVIEW
                    payload = {
                        "external_action_id": str(action.id),
                        "reason": manual_reason,
                    }
                else:
                    event_type = EventType.RUN_FAILED
                    payload = {"reason": run_row.failure_reason}
                session.add(
                    DomainEventRow(
                        id=uuid4(),
                        run_id=run.id,
                        sequence=seqs[1],
                        event_type=event_type.value,
                        payload=payload,
                    )
                )
            await session.flush()

        attempt.succeed(outcome)
        if outcome.result is ReconciliationResult.SUCCEEDED:
            action.reconciliation_succeeded()
            call.reconcile_succeed(outcome.evidence)
            return message
        if outcome.result is ReconciliationResult.FAILED:
            action.reconciliation_failed_business()
            call.reconcile_fail("reconciliation proved external action failed")
            run.fail("RECONCILIATION_CONFIRMED_ACTION_FAILED")
            return None
        safe_not_executed = outcome.result is ReconciliationResult.NOT_EXECUTED and (
            mode is ReconciliationMode.AUTHORITATIVE
            or (mode is ReconciliationMode.BEST_EFFORT and idempotency_supported)
        )
        if safe_not_executed:
            if run_row.status is RunStatus.RUNNING:
                action.reconciliation_retry_ready()
                call.reconcile_retry_ready(
                    "reconciliation proved previous side effect NOT_EXECUTED"
                )
            else:
                action.status = ExternalActionStatus.ABORTED
                call.status = ToolCallStatus.NOT_EXECUTED
                call.error = run_row.failure_reason
                run.status = RunStatus.FAILED
                run.failure_reason = run_row.failure_reason
            return None
        action.manual_review()
        run.status = RunStatus.WAITING_ACTION_RESOLUTION
        run.owner_worker_id = None
        run.lease_expires_at = None
        return None

    async def record_no_reconciliation_manual_review(
        self,
        call: ToolCall,
        action: ExternalAction,
        run: Run,
        *,
        reason: str,
        expected_generation: int,
    ) -> None:
        self._assert_generation(expected_generation)
        async with self._sessions() as session, session.begin():
            run_row = await _lock_owned_run(
                session,
                run_id=run.id,
                expected_generation=expected_generation,
            )
            action_row = (
                await session.execute(
                    select(ExternalActionRow)
                    .where(ExternalActionRow.id == action.id)
                    .with_for_update()
                )
            ).scalar_one()
            call_row = (
                await session.execute(
                    select(ToolCallRow)
                    .where(ToolCallRow.id == call.id)
                    .with_for_update()
                )
            ).scalar_one()
            if (
                action_row.status is not ExternalActionStatus.UNKNOWN
                or call_row.status is not ToolCallStatus.UNRESOLVED
            ):
                raise RuntimeError("manual review no-reconcile path lost unresolved truth")
            action_row.status = ExternalActionStatus.MANUAL_REVIEW
            action_row.updated_at = func.clock_timestamp()
            run_row.status = RunStatus.WAITING_ACTION_RESOLUTION
            run_row.queue_reason = None
            run_row.available_at = None
            run_row.owner_worker_id = None
            run_row.lease_expires_at = None
            seq = next(iter(await _allocate_event_sequences(session, run.id, 1)))
            session.add(
                DomainEventRow(
                    id=uuid4(),
                    run_id=run.id,
                    sequence=seq,
                    event_type=EventType.ACTION_MANUAL_REVIEW.value,
                    payload={
                        "external_action_id": str(action.id),
                        "reason": reason,
                    },
                )
            )
        action.manual_review()
        run.status = RunStatus.WAITING_ACTION_RESOLUTION
        run.owner_worker_id = None
        run.lease_expires_at = None

    async def record_side_effect_attempt_started(
        self,
        call: ToolCall,
''',
)


# ---------------------------------------------------------------------------
# RuntimeStore orphan reconciliation recovery before all other takeover work.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/infrastructure/db/runtime_store.py",
    '''    ModelInvocationStatus,
    QueueReason,
''',
    '''    ModelInvocationStatus,
    ReconciliationAttemptStatus,
    QueueReason,
''',
)
replace_once(
    "src/agentforge/infrastructure/db/runtime_store.py",
    '''    ModelInvocationRow,
    RunCounterRow,
''',
    '''    ModelInvocationRow,
    ReconciliationAttemptRow,
    RunCounterRow,
''',
)

replace_once(
    "src/agentforge/infrastructure/db/runtime_store.py",
    '''async def _recover_orphaned_side_effect_attempts(
''',
    '''async def _recover_orphaned_reconciliation_attempts(
    session: AsyncSession,
    run_id: UUID,
) -> list[tuple[UUID, UUID, int, int]]:
    rows = (
        await session.execute(
            select(
                ReconciliationAttemptRow,
                ExternalActionRow,
                ToolVersionRow.reconciliation_retry_max_attempts,
                ToolVersionRow.reconciliation_retry_initial_backoff_seconds,
                ToolVersionRow.reconciliation_retry_max_backoff_seconds,
            )
            .join(
                ExternalActionRow,
                ExternalActionRow.id == ReconciliationAttemptRow.external_action_id,
            )
            .join(ToolCallRow, ToolCallRow.id == ExternalActionRow.tool_call_id)
            .join(ToolVersionRow, ToolVersionRow.id == ToolCallRow.tool_version_id)
            .where(
                ReconciliationAttemptRow.run_id == run_id,
                ReconciliationAttemptRow.status == ReconciliationAttemptStatus.STARTED,
                ExternalActionRow.status == ExternalActionStatus.RECONCILING,
            )
            .order_by(ReconciliationAttemptRow.id)
            .with_for_update()
        )
    ).all()
    recovered: list[tuple[UUID, UUID, int, int]] = []
    for attempt, action, max_attempts, initial_backoff, max_backoff in rows:
        attempt.status = ReconciliationAttemptStatus.FAILED
        attempt.error = "previous executor lease expired during reconciliation query"
        attempt.outcome_reason = "LEASE_LOST"
        attempt.finished_at = func.clock_timestamp()
        delay = min(
            initial_backoff * (2 ** (attempt.attempt_number - 1)),
            max_backoff,
        )
        recovered.append((action.id, attempt.id, attempt.attempt_number, delay))
        if attempt.attempt_number >= max_attempts:
            action.status = ExternalActionStatus.MANUAL_REVIEW
            action.updated_at = func.clock_timestamp()
    return recovered


async def _recover_orphaned_side_effect_attempts(
''',
)

# Early scheduling branch inside claim_next_run.
replace_once(
    "src/agentforge/infrastructure/db/runtime_store.py",
    '''            recovered_model_ids = (
                await _close_orphaned_model_invocations_on_recovery(session, row.id)
                if was_recovery
                else []
            )
''',
    '''            recovered_reconciliations = (
                await _recover_orphaned_reconciliation_attempts(session, row.id)
                if was_recovery
                else []
            )
            if recovered_reconciliations:
                exhausted = False
                max_delay = 0
                for external_action_id, attempt_id, attempt_number, delay in recovered_reconciliations:
                    max_delay = max(max_delay, delay)
                    action_status = await session.scalar(
                        select(ExternalActionRow.status).where(
                            ExternalActionRow.id == external_action_id
                        )
                    )
                    exhausted = exhausted or action_status is ExternalActionStatus.MANUAL_REVIEW
                if exhausted:
                    row.status = RunStatus.WAITING_ACTION_RESOLUTION
                    row.queue_reason = None
                    row.available_at = None
                else:
                    row.status = RunStatus.QUEUED
                    row.queue_reason = QueueReason.RETRY
                    row.available_at = func.clock_timestamp() + text(
                        f"INTERVAL '{int(max_delay)} seconds'"
                    )
                row.owner_worker_id = None
                row.lease_expires_at = None
                seqs = list(
                    await _allocate_event_sequences(
                        session,
                        row.id,
                        1 + len(recovered_reconciliations) * 2,
                    )
                )
                session.add(
                    DomainEventRow(
                        id=uuid4(),
                        run_id=row.id,
                        sequence=seqs[0],
                        event_type=EventType.RUN_RECOVERED.value,
                        payload={
                            "worker_id": worker_id,
                            "generation": next_generation,
                            "reconciliation_orphan": True,
                        },
                    )
                )
                offset = 1
                for external_action_id, attempt_id, attempt_number, delay in recovered_reconciliations:
                    session.add(
                        DomainEventRow(
                            id=uuid4(),
                            run_id=row.id,
                            sequence=seqs[offset],
                            event_type=EventType.RECONCILIATION_FAILED.value,
                            payload={
                                "external_action_id": str(external_action_id),
                                "reconciliation_attempt_id": str(attempt_id),
                                "attempt_number": attempt_number,
                                "reason": "LEASE_LOST",
                            },
                        )
                    )
                    offset += 1
                    action_status = await session.scalar(
                        select(ExternalActionRow.status).where(
                            ExternalActionRow.id == external_action_id
                        )
                    )
                    if action_status is ExternalActionStatus.MANUAL_REVIEW:
                        event_type = EventType.ACTION_MANUAL_REVIEW
                        payload = {
                            "external_action_id": str(external_action_id),
                            "reason": "RECONCILIATION_RETRY_EXHAUSTED_AFTER_LEASE_LOSS",
                        }
                    else:
                        event_type = EventType.RECONCILIATION_RETRY_SCHEDULED
                        payload = {
                            "external_action_id": str(external_action_id),
                            "attempt_number": attempt_number,
                            "delay_seconds": delay,
                        }
                    session.add(
                        DomainEventRow(
                            id=uuid4(),
                            run_id=row.id,
                            sequence=seqs[offset],
                            event_type=event_type.value,
                            payload=payload,
                        )
                    )
                    offset += 1
                await session.flush()
                await session.refresh(row)
                return None

            recovered_model_ids = (
                await _close_orphaned_model_invocations_on_recovery(session, row.id)
                if was_recovery
                else []
            )
''',
)


# ---------------------------------------------------------------------------
# RunManager reconciliation before any new model reasoning.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/application/run_manager.py",
    '''        # D1 safety stop: unresolved external truth outranks new model reasoning.
        # D2/D3 will add takeover/reconciliation continuation from this durable fact.
        unknown_action = await recorder.load_unknown_external_action(run.id)
        if unknown_action is not None:
            return None

        ready_action = await recorder.load_ready_external_action(run.id)
''',
    '''        # Durable unresolved external truth outranks all new model reasoning.
        unknown_action = await recorder.load_unknown_external_action(run.id)
        reconciling_action = await recorder.load_reconciling_external_action(run.id)
        unresolved_action = unknown_action or reconciling_action
        if unresolved_action is not None:
            unresolved_call, unresolved_snapshot, external_action = unresolved_action
            binding = next(
                item
                for item in agent_version.tool_bindings
                if item.name == unresolved_call.tool_name
                and item.tool_version_id == unresolved_call.tool_version_id
            )
            if binding.reconciliation_mode is ReconciliationMode.NONE:
                await recorder.record_no_reconciliation_manual_review(
                    unresolved_call,
                    external_action,
                    run,
                    reason="RECONCILIATION_MODE_NONE",
                    expected_generation=expected_generation,
                )
                return None
            tool, binding = self._tools.prepare_reconciliation(
                call=unresolved_call,
                snapshot=unresolved_snapshot,
                action=external_action,
                agent_version=agent_version,
            )
            reconciliation_attempt = await recorder.begin_reconciliation_attempt(
                external_action,
                expected_generation=expected_generation,
            )
            try:
                outcome = await self._tools.execute_reconciliation(
                    tool=tool,
                    snapshot=unresolved_snapshot,
                    action=external_action,
                )
            except Exception as exc:
                scheduled = await recorder.record_reconciliation_transport_failure(
                    external_action,
                    reconciliation_attempt,
                    run,
                    error=str(exc),
                    max_attempts=binding.reconciliation_retry_max_attempts,
                    initial_backoff_seconds=binding.reconciliation_retry_initial_backoff_seconds,
                    max_backoff_seconds=binding.reconciliation_retry_max_backoff_seconds,
                    expected_generation=expected_generation,
                )
                if scheduled:
                    return None
                return None

            reconciled_message = await recorder.record_reconciliation_outcome(
                unresolved_call,
                external_action,
                reconciliation_attempt,
                outcome,
                run,
                reconciliation_mode=binding.reconciliation_mode.value,
                idempotency_supported=binding.idempotency_supported,
                side_effect_retry_max_attempts=binding.side_effect_retry_max_attempts,
                expected_generation=expected_generation,
            )
            if run.status is RunStatus.FAILED:
                raise RunExecutionFailedError(
                    run.failure_reason or "reconciliation finalized action failure"
                )
            if run.status is RunStatus.WAITING_ACTION_RESOLUTION:
                return None
            if external_action.status is ExternalActionStatus.READY:
                prepared_action = self._tools.prepare_recovered_side_effect(
                    call=unresolved_call,
                    snapshot=unresolved_snapshot,
                    action=external_action,
                    agent_version=agent_version,
                )
                recovered_message = await self._execute_side_effect_action(
                    run=run,
                    prepared=prepared_action,
                    recorder=recorder,
                    expected_generation=expected_generation,
                )
                if recovered_message is None:
                    return None
                messages.append(recovered_message)
                progression_steps += 1
            elif reconciled_message is not None:
                messages.append(reconciled_message)
                progression_steps += 1

        ready_action = await recorder.load_ready_external_action(run.id)
''',
)


# ---------------------------------------------------------------------------
# Integration imports needed by tests.
# ---------------------------------------------------------------------------
replace_once(
    "tests/integration/test_postgres_runtime.py",
    '''    ToolExecutionAttemptStatus,
)
''',
    '''    ToolExecutionAttemptStatus,
    ReconciliationResult,
)
''',
)
replace_once(
    "tests/integration/test_postgres_runtime.py",
    '''from agentforge.runtime.tools import FunctionTool, InMemoryToolRegistry, SideEffectFunctionTool
''',
    '''from agentforge.runtime.tools import (
    FunctionTool,
    InMemoryToolRegistry,
    ReconciliableSideEffectFunctionTool,
    SideEffectFunctionTool,
)
from agentforge.domain.reconciliation import ReconciliationOutcome
''',
)


# ---------------------------------------------------------------------------
# D3 focused integration coverage.
# ---------------------------------------------------------------------------
append_text(
    "tests/integration/test_postgres_runtime.py",
    "test_authoritative_reconciliation_succeeds_after_ambiguous_side_effect",
    r'''


@pytest.mark.asyncio
async def test_authoritative_reconciliation_succeeds_after_ambiguous_side_effect() -> None:
    from agentforge.domain.enums import ExternalActionStatus, ReconciliationMode
    from agentforge.infrastructure.db.models import (
        ExternalActionRow,
        ReconciliationAttemptRow,
    )

    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)

    tool_id = uuid4()
    version_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(ToolDefinitionRow(id=tool_id, name="reconcile_authoritative", description="write"))
        await session.flush()
        session.add(
            ToolVersionRow(
                id=version_id,
                tool_id=tool_id,
                version_number=1,
                input_schema={"type": "object"},
                effect_type=ToolEffectType.EXTERNAL_SIDE_EFFECT,
                implementation_ref="tests:reconcile_authoritative",
                allow_no_approval_execution=True,
                reconciliation_mode=ReconciliationMode.AUTHORITATIVE,
                reconciliation_retry_max_attempts=3,
                reconciliation_retry_initial_backoff_seconds=0,
                reconciliation_retry_max_backoff_seconds=0,
            )
        )
        await session.flush()
        session.add(
            AgentVersionToolRow(
                agent_version_id=DEMO_AGENT_VERSION_ID,
                tool_version_id=version_id,
                tool_alias="reconcile_authoritative",
            )
        )

    physical_calls = 0
    reconciliation_calls = 0

    async def ambiguous(_invocation):
        nonlocal physical_calls
        physical_calls += 1
        raise ToolAdapterError(
            "effect committed but response lost",
            error_class="RESPONSE_LOST",
            definite_not_executed=False,
        )

    async def reconcile(invocation):
        nonlocal reconciliation_calls
        reconciliation_calls += 1
        return ReconciliationOutcome(
            ReconciliationResult.SUCCEEDED,
            {"resource_id": "ticket-123", "operation_id": str(invocation.operation_id)},
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
            ReconciliableSideEffectFunctionTool(
                version_id=version_id,
                name="reconcile_authoritative",
                description="write",
                input_schema={"type": "object"},
                func=ambiguous,
                reconcile_func=reconcile,
            ),
        ]
    )
    store = PostgresRuntimeStore(sessions)
    created = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="authoritative reconcile",
        idempotency_key="integration-d3-auth-success",
        principal_scope="test-user",
    )
    claimed = await store.claim_next_run(worker_id="d3-auth", lease_seconds=30)
    assert claimed is not None
    recorder = PostgresExecutionRecorder(
        sessions,
        run_id=created.id,
        generation=claimed.execution_generation,
    )
    manager1 = RunManager(
        NativeRunner(
            ScriptedFakeModel([ToolStep("reconcile_authoritative", {"v": 1})]),
            registry,
        ),
        ToolCoordinator(registry),
    )
    assert (
        await manager1.execute(
            run=claimed,
            run_state=await store.load_run_state(created.id),
            agent_version=await store.load_agent_version(DEMO_AGENT_VERSION_ID),
            recorder=recorder,
        )
        is None
    )
    assert physical_calls == 1

    manager2 = RunManager(
        NativeRunner(ScriptedFakeModel([FinalStep("reconciled")]), registry),
        ToolCoordinator(registry),
    )
    assert (
        await manager2.execute(
            run=claimed,
            run_state=await store.load_run_state(created.id),
            agent_version=await store.load_agent_version(DEMO_AGENT_VERSION_ID),
            recorder=recorder,
        )
        == "reconciled"
    )
    assert reconciliation_calls == 1
    assert physical_calls == 1
    async with sessions() as session:
        action = (
            await session.execute(
                select(ExternalActionRow).where(ExternalActionRow.run_id == created.id)
            )
        ).scalar_one()
        attempts = (
            (
                await session.execute(
                    select(ReconciliationAttemptRow)
                    .where(ReconciliationAttemptRow.external_action_id == action.id)
                    .order_by(ReconciliationAttemptRow.attempt_number)
                )
            )
            .scalars()
            .all()
        )
    assert action.status is ExternalActionStatus.SUCCEEDED
    assert len(attempts) == 1
    assert attempts[0].status is ReconciliationAttemptStatus.SUCCEEDED
    assert attempts[0].result is ReconciliationResult.SUCCEEDED
    await engine.dispose()


@pytest.mark.asyncio
async def test_best_effort_not_executed_non_idempotent_requires_manual_review() -> None:
    from agentforge.domain.enums import (
        ExternalActionStatus,
        ReconciliationAttemptStatus,
        ReconciliationMode,
    )
    from agentforge.infrastructure.db.models import ExternalActionRow

    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)

    tool_id = uuid4()
    version_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(ToolDefinitionRow(id=tool_id, name="best_effort_non_idem", description="write"))
        await session.flush()
        session.add(
            ToolVersionRow(
                id=version_id,
                tool_id=tool_id,
                version_number=1,
                input_schema={"type": "object"},
                effect_type=ToolEffectType.WRITE,
                implementation_ref="tests:best_effort_non_idem",
                allow_no_approval_execution=True,
                idempotency_supported=False,
                reconciliation_mode=ReconciliationMode.BEST_EFFORT,
            )
        )
        await session.flush()
        session.add(
            AgentVersionToolRow(
                agent_version_id=DEMO_AGENT_VERSION_ID,
                tool_version_id=version_id,
                tool_alias="best_effort_non_idem",
            )
        )

    async def ambiguous(_invocation):
        raise ToolAdapterError(
            "ambiguous",
            error_class="TIMEOUT",
            definite_not_executed=False,
        )

    async def reconcile(_invocation):
        return ReconciliationOutcome(ReconciliationResult.NOT_EXECUTED, {"best_effort": True})

    registry = InMemoryToolRegistry(
        [
            FunctionTool(
                version_id=DEMO_TOOL_VERSION_ID,
                name="echo_read",
                description="read",
                input_schema={"type": "object"},
                func=lambda text: {"echo": text},
            ),
            ReconciliableSideEffectFunctionTool(
                version_id=version_id,
                name="best_effort_non_idem",
                description="write",
                input_schema={"type": "object"},
                func=ambiguous,
                reconcile_func=reconcile,
            ),
        ]
    )
    store = PostgresRuntimeStore(sessions)
    created = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="best effort manual",
        idempotency_key="integration-d3-best-effort-manual",
        principal_scope="test-user",
    )
    claimed = await store.claim_next_run(worker_id="d3-best", lease_seconds=30)
    assert claimed is not None
    recorder = PostgresExecutionRecorder(
        sessions,
        run_id=created.id,
        generation=claimed.execution_generation,
    )
    manager = RunManager(
        NativeRunner(ScriptedFakeModel([ToolStep("best_effort_non_idem", {})]), registry),
        ToolCoordinator(registry),
    )
    assert (
        await manager.execute(
            run=claimed,
            run_state=await store.load_run_state(created.id),
            agent_version=await store.load_agent_version(DEMO_AGENT_VERSION_ID),
            recorder=recorder,
        )
        is None
    )
    manager2 = RunManager(
        NativeRunner(ScriptedFakeModel([FinalStep("must not reason")]), registry),
        ToolCoordinator(registry),
    )
    assert (
        await manager2.execute(
            run=claimed,
            run_state=await store.load_run_state(created.id),
            agent_version=await store.load_agent_version(DEMO_AGENT_VERSION_ID),
            recorder=recorder,
        )
        is None
    )
    durable = await store.get_run(created.id)
    assert durable is not None
    assert durable.status is RunStatus.WAITING_ACTION_RESOLUTION
    async with sessions() as session:
        action = (
            await session.execute(
                select(ExternalActionRow).where(ExternalActionRow.run_id == created.id)
            )
        ).scalar_one()
    assert action.status is ExternalActionStatus.MANUAL_REVIEW
    await engine.dispose()


@pytest.mark.asyncio
async def test_none_reconciliation_enters_manual_review_without_query() -> None:
    from agentforge.domain.enums import ExternalActionStatus, ReconciliationMode
    from agentforge.infrastructure.db.models import ExternalActionRow, ReconciliationAttemptRow

    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)

    tool_id = uuid4()
    version_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(ToolDefinitionRow(id=tool_id, name="none_reconcile", description="write"))
        await session.flush()
        session.add(
            ToolVersionRow(
                id=version_id,
                tool_id=tool_id,
                version_number=1,
                input_schema={"type": "object"},
                effect_type=ToolEffectType.WRITE,
                implementation_ref="tests:none_reconcile",
                allow_no_approval_execution=True,
                reconciliation_mode=ReconciliationMode.NONE,
            )
        )
        await session.flush()
        session.add(
            AgentVersionToolRow(
                agent_version_id=DEMO_AGENT_VERSION_ID,
                tool_version_id=version_id,
                tool_alias="none_reconcile",
            )
        )

    async def ambiguous(_invocation):
        raise ToolAdapterError("ambiguous", error_class="TIMEOUT", definite_not_executed=False)

    registry = InMemoryToolRegistry(
        [
            FunctionTool(
                version_id=DEMO_TOOL_VERSION_ID,
                name="echo_read",
                description="read",
                input_schema={"type": "object"},
                func=lambda text: {"echo": text},
            ),
            SideEffectFunctionTool(
                version_id=version_id,
                name="none_reconcile",
                description="write",
                input_schema={"type": "object"},
                func=ambiguous,
            ),
        ]
    )
    store = PostgresRuntimeStore(sessions)
    created = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="none reconciliation",
        idempotency_key="integration-d3-none",
        principal_scope="test-user",
    )
    claimed = await store.claim_next_run(worker_id="d3-none", lease_seconds=30)
    assert claimed is not None
    recorder = PostgresExecutionRecorder(
        sessions,
        run_id=created.id,
        generation=claimed.execution_generation,
    )
    manager = RunManager(
        NativeRunner(ScriptedFakeModel([ToolStep("none_reconcile", {})]), registry),
        ToolCoordinator(registry),
    )
    assert (
        await manager.execute(
            run=claimed,
            run_state=await store.load_run_state(created.id),
            agent_version=await store.load_agent_version(DEMO_AGENT_VERSION_ID),
            recorder=recorder,
        )
        is None
    )
    manager2 = RunManager(
        NativeRunner(ScriptedFakeModel([FinalStep("must not reason")]), registry),
        ToolCoordinator(registry),
    )
    assert (
        await manager2.execute(
            run=claimed,
            run_state=await store.load_run_state(created.id),
            agent_version=await store.load_agent_version(DEMO_AGENT_VERSION_ID),
            recorder=recorder,
        )
        is None
    )
    durable = await store.get_run(created.id)
    assert durable is not None and durable.status is RunStatus.WAITING_ACTION_RESOLUTION
    async with sessions() as session:
        action = (
            await session.execute(
                select(ExternalActionRow).where(ExternalActionRow.run_id == created.id)
            )
        ).scalar_one()
        count = await session.scalar(
            select(func.count())
            .select_from(ReconciliationAttemptRow)
            .where(ReconciliationAttemptRow.external_action_id == action.id)
        )
    assert action.status is ExternalActionStatus.MANUAL_REVIEW
    assert count == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_reconciliation_transport_failure_uses_separate_bounded_safety_budget() -> None:
    from agentforge.domain.enums import ExternalActionStatus, ReconciliationMode
    from agentforge.infrastructure.db.models import ExternalActionRow, ReconciliationAttemptRow

    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)

    tool_id = uuid4()
    version_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(ToolDefinitionRow(id=tool_id, name="reconcile_retry", description="write"))
        await session.flush()
        session.add(
            ToolVersionRow(
                id=version_id,
                tool_id=tool_id,
                version_number=1,
                input_schema={"type": "object"},
                effect_type=ToolEffectType.WRITE,
                implementation_ref="tests:reconcile_retry",
                allow_no_approval_execution=True,
                reconciliation_mode=ReconciliationMode.AUTHORITATIVE,
                reconciliation_retry_max_attempts=2,
                reconciliation_retry_initial_backoff_seconds=0,
                reconciliation_retry_max_backoff_seconds=0,
            )
        )
        await session.flush()
        session.add(
            AgentVersionToolRow(
                agent_version_id=DEMO_AGENT_VERSION_ID,
                tool_version_id=version_id,
                tool_alias="reconcile_retry",
            )
        )

    async def ambiguous(_invocation):
        raise ToolAdapterError("ambiguous", error_class="TIMEOUT", definite_not_executed=False)

    async def reconcile(_invocation):
        raise TimeoutError("reconciliation transport failed")

    registry = InMemoryToolRegistry(
        [
            FunctionTool(
                version_id=DEMO_TOOL_VERSION_ID,
                name="echo_read",
                description="read",
                input_schema={"type": "object"},
                func=lambda text: {"echo": text},
            ),
            ReconciliableSideEffectFunctionTool(
                version_id=version_id,
                name="reconcile_retry",
                description="write",
                input_schema={"type": "object"},
                func=ambiguous,
                reconcile_func=reconcile,
            ),
        ]
    )
    store = PostgresRuntimeStore(sessions)
    created = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="reconcile retry",
        idempotency_key="integration-d3-reconcile-retry",
        principal_scope="test-user",
    )
    claimed1 = await store.claim_next_run(worker_id="d3-r1", lease_seconds=30)
    assert claimed1 is not None
    recorder1 = PostgresExecutionRecorder(
        sessions,
        run_id=created.id,
        generation=claimed1.execution_generation,
    )
    manager1 = RunManager(
        NativeRunner(ScriptedFakeModel([ToolStep("reconcile_retry", {})]), registry),
        ToolCoordinator(registry),
    )
    assert (
        await manager1.execute(
            run=claimed1,
            run_state=await store.load_run_state(created.id),
            agent_version=await store.load_agent_version(DEMO_AGENT_VERSION_ID),
            recorder=recorder1,
        )
        is None
    )
    # Make ordinary business budget exhausted; safety reconciliation must still run.
    async with sessions() as session, session.begin():
        state = await session.get(RunStateRow, created.id)
        run_row = await session.get(RunRow, created.id)
        assert state is not None and run_row is not None
        state.tool_attempts_used = run_row.max_tool_attempts

    manager2 = RunManager(
        NativeRunner(ScriptedFakeModel([FinalStep("must not reason")]), registry),
        ToolCoordinator(registry),
    )
    assert (
        await manager2.execute(
            run=claimed1,
            run_state=await store.load_run_state(created.id),
            agent_version=await store.load_agent_version(DEMO_AGENT_VERSION_ID),
            recorder=recorder1,
        )
        is None
    )
    queued = await store.get_run(created.id)
    assert queued is not None
    assert queued.status is RunStatus.QUEUED
    assert queued.queue_reason is QueueReason.RETRY

    claimed2 = await store.claim_next_run(worker_id="d3-r2", lease_seconds=30)
    assert claimed2 is not None
    recorder2 = PostgresExecutionRecorder(
        sessions,
        run_id=created.id,
        generation=claimed2.execution_generation,
    )
    assert (
        await manager2.execute(
            run=claimed2,
            run_state=await store.load_run_state(created.id),
            agent_version=await store.load_agent_version(DEMO_AGENT_VERSION_ID),
            recorder=recorder2,
        )
        is None
    )
    waiting = await store.get_run(created.id)
    assert waiting is not None
    assert waiting.status is RunStatus.WAITING_ACTION_RESOLUTION
    async with sessions() as session:
        action = (
            await session.execute(
                select(ExternalActionRow).where(ExternalActionRow.run_id == created.id)
            )
        ).scalar_one()
        attempts = (
            (
                await session.execute(
                    select(ReconciliationAttemptRow)
                    .where(ReconciliationAttemptRow.external_action_id == action.id)
                    .order_by(ReconciliationAttemptRow.attempt_number)
                )
            )
            .scalars()
            .all()
        )
    assert action.status is ExternalActionStatus.MANUAL_REVIEW
    assert [item.attempt_number for item in attempts] == [1, 2]
    assert all(item.status is ReconciliationAttemptStatus.FAILED for item in attempts)
    await engine.dispose()
'''
)
