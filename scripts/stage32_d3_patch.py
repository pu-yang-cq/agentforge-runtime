from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one anchor, found {count}: {old[:160]!r}")
    file.write_text(text.replace(old, new))


def replace_last_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text()
    count = text.count(old)
    if count < 1:
        raise SystemExit(f"{path}: expected at least one anchor: {old[:160]!r}")
    index = text.rfind(old)
    file.write_text(text[:index] + new + text[index + len(old):])


def append_text(path: str, marker: str, block: str) -> None:
    file = Path(path)
    text = file.read_text()
    if marker in text:
        raise SystemExit(f"{path}: marker already present: {marker}")
    file.write_text(text + block)


# ---------------------------------------------------------------------------
# Domain enums and Run waiting state.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/domain/enums.py",
    '''    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
''',
    '''    RUNNING = "RUNNING"
    WAITING_ACTION_RESOLUTION = "WAITING_ACTION_RESOLUTION"
    COMPLETED = "COMPLETED"
''',
)

replace_once(
    "src/agentforge/domain/enums.py",
    '''class ModelInvocationStatus(StrEnum):
''',
    '''class ReconciliationAttemptStatus(StrEnum):
    STARTED = "STARTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class ReconciliationBusinessResult(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    NOT_EXECUTED = "NOT_EXECUTED"
    UNKNOWN = "UNKNOWN"


class ModelInvocationStatus(StrEnum):
''',
)

replace_once(
    "src/agentforge/domain/enums.py",
    '''    ACTION_RETRY_READY = "ACTION_RETRY_READY"
    ACTION_ABORTED = "ACTION_ABORTED"
''',
    '''    ACTION_RETRY_READY = "ACTION_RETRY_READY"
    ACTION_MANUAL_REVIEW = "ACTION_MANUAL_REVIEW"
    ACTION_ABORTED = "ACTION_ABORTED"
    RECONCILIATION_STARTED = "RECONCILIATION_STARTED"
    RECONCILIATION_SUCCEEDED = "RECONCILIATION_SUCCEEDED"
    RECONCILIATION_FAILED = "RECONCILIATION_FAILED"
    RECONCILIATION_RETRY_SCHEDULED = "RECONCILIATION_RETRY_SCHEDULED"
''',
)


# ---------------------------------------------------------------------------
# ReconciliationAttempt durable domain object.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/domain/models.py",
    '''    QueueReason,
    ReconciliationMode,
    RunStatus,
''',
    '''    QueueReason,
    ReconciliationAttemptStatus,
    ReconciliationBusinessResult,
    ReconciliationMode,
    RunStatus,
''',
)

replace_once(
    "src/agentforge/domain/models.py",
    '''    side_effect_retry_max_backoff_seconds: int = 30

    def __post_init__(self) -> None:
''',
    '''    side_effect_retry_max_backoff_seconds: int = 30
    reconciliation_max_attempts: int = 3
    reconciliation_initial_backoff_seconds: int = 1
    reconciliation_max_backoff_seconds: int = 30

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
        if self.reconciliation_max_attempts <= 0:
            raise ValueError("reconciliation_max_attempts must be positive")
        if self.reconciliation_initial_backoff_seconds < 0:
            raise ValueError("reconciliation initial backoff cannot be negative")
        if self.reconciliation_max_backoff_seconds < self.reconciliation_initial_backoff_seconds:
            raise ValueError("reconciliation max backoff cannot be below initial backoff")

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

    def reconciliation_delay_seconds(self, failed_attempt_number: int) -> int:
        if failed_attempt_number <= 0:
            raise ValueError("failed_attempt_number must be positive")
        delay: int = self.reconciliation_initial_backoff_seconds * (
            2 ** (failed_attempt_number - 1)
        )
        return min(delay, self.reconciliation_max_backoff_seconds)


@dataclass(frozen=True, slots=True)
class AgentVersion:
''',
)

replace_once(
    "src/agentforge/domain/models.py",
    '''    def yield_to_queue(self, reason: QueueReason = QueueReason.YIELD) -> None:
        if self.status is not RunStatus.RUNNING:
            raise ValueError(f"cannot yield run from {self.status}")
        self.status = RunStatus.QUEUED
        self.queue_reason = reason
        self.owner_worker_id = None
        self.lease_expires_at = None


@dataclass(slots=True)
class RunState:
''',
    '''    def yield_to_queue(self, reason: QueueReason = QueueReason.YIELD) -> None:
        if self.status is not RunStatus.RUNNING:
            raise ValueError(f"cannot yield run from {self.status}")
        self.status = RunStatus.QUEUED
        self.queue_reason = reason
        self.owner_worker_id = None
        self.lease_expires_at = None

    def wait_for_action_resolution(self) -> None:
        if self.status is not RunStatus.RUNNING:
            raise ValueError(f"cannot wait for action resolution from {self.status}")
        self.status = RunStatus.WAITING_ACTION_RESOLUTION
        self.queue_reason = None
        self.available_at = None
        self.owner_worker_id = None
        self.lease_expires_at = None


@dataclass(slots=True)
class RunState:
''',
)

append_text(
    "src/agentforge/domain/models.py",
    "class ReconciliationAttempt:",
    r'''


@dataclass(slots=True)
class ReconciliationAttempt:
    id: UUID
    run_id: UUID
    external_action_id: UUID
    attempt_number: int
    execution_generation: int
    status: ReconciliationAttemptStatus = ReconciliationAttemptStatus.STARTED
    business_result: ReconciliationBusinessResult | None = None
    evidence: dict[str, Any] | None = None
    error: str | None = None
    outcome_reason: str | None = None
    started_at: datetime = field(default_factory=utcnow)
    finished_at: datetime | None = None

    def succeed(
        self,
        business_result: ReconciliationBusinessResult,
        evidence: dict[str, Any] | None,
    ) -> None:
        if self.status is not ReconciliationAttemptStatus.STARTED:
            raise ValueError("reconciliation attempt can only succeed from STARTED")
        self.status = ReconciliationAttemptStatus.SUCCEEDED
        self.business_result = business_result
        self.evidence = evidence
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
# ExternalAction reconciliation transitions.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/domain/actions.py",
    '''    def abort_after_definite_not_executed(self) -> None:
        if self.status is not ExternalActionStatus.EXECUTING or self.current_attempt_id is None:
            raise ValueError("external action can only abort an executing proven-no-effect attempt")
        self.status = ExternalActionStatus.ABORTED
        self.current_attempt_id = None

    def abort(self) -> None:
''',
    '''    def abort_after_definite_not_executed(self) -> None:
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

    def abort(self) -> None:
''',
)


# ---------------------------------------------------------------------------
# Reconciliation adapter contract.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/application/ports.py",
    '''from agentforge.domain.actions import ActionSnapshot, ExternalAction
from agentforge.domain.model_contract import ModelRequest, ModelResponse, ModelToolSpec
from agentforge.domain.models import (
''',
    '''from agentforge.domain.actions import ActionSnapshot, ExternalAction
from agentforge.domain.enums import ReconciliationBusinessResult
from agentforge.domain.model_contract import ModelRequest, ModelResponse, ModelToolSpec
from agentforge.domain.models import (
''',
)

replace_once(
    "src/agentforge/application/ports.py",
    '''    RunState,
    ToolBinding,
''',
    '''    ReconciliationAttempt,
    RunState,
    ToolBinding,
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


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    outcome: ReconciliationBusinessResult
    evidence: dict[str, Any] | None = None


@runtime_checkable
class ReconciliationTool(Protocol):
    @property
    def version_id(self) -> UUID: ...

    @property
    def spec(self) -> ModelToolSpec: ...

    async def reconcile(self, invocation: ReconciliationInvocation) -> ReconciliationResult: ...


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

    async def load_reconciliation_external_action(
        self,
        run_id: UUID,
    ) -> tuple[ToolCall, ActionSnapshot, ExternalAction] | None: ...

    async def record_action_manual_review(
        self,
        call: ToolCall,
        action: ExternalAction,
        run: Run,
        reason: str,
        *,
        expected_generation: int,
    ) -> None: ...

    async def record_reconciliation_started(
        self,
        call: ToolCall,
        action: ExternalAction,
        run: Run,
        *,
        max_attempts: int,
        expected_generation: int,
    ) -> ReconciliationAttempt | None: ...

    async def record_reconciliation_failed(
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

    async def record_reconciliation_result(
        self,
        call: ToolCall,
        action: ExternalAction,
        attempt: ReconciliationAttempt,
        run: Run,
        result: ReconciliationResult,
        *,
        binding: ToolBinding,
        expected_generation: int,
    ) -> RunMessage | None: ...

    async def record_side_effect_attempt_started(
''',
)


# ---------------------------------------------------------------------------
# Runtime tool wrapper + coordinator reconciliation preparation/query.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/runtime/tools.py",
    '''from agentforge.application.ports import Tool
''',
    '''from agentforge.application.ports import ReconciliationInvocation, ReconciliationResult, Tool
''',
)

replace_once(
    "src/agentforge/runtime/tools.py",
    '''        input_schema: dict[str, Any],
        func: Callable[[object], Any],
    ) -> None:
''',
    '''        input_schema: dict[str, Any],
        func: Callable[[object], Any],
        reconcile_func: Callable[[object], Any] | None = None,
    ) -> None:
''',
)

replace_last_once(
    "src/agentforge/runtime/tools.py",
    '''        self._spec = ModelToolSpec(name, description, input_schema)
        self._func = func
''',
    '''        self._spec = ModelToolSpec(name, description, input_schema)
        self._func = func
        self._reconcile_func = reconcile_func
''',
)

replace_once(
    "src/agentforge/runtime/tools.py",
    '''    async def invoke_side_effect(self, invocation: object) -> Any:
        if inspect.iscoroutinefunction(self._func):
            return await self._func(invocation)
        value = await asyncio.to_thread(self._func, invocation)
        if inspect.isawaitable(value):
            return await value
        return value
''',
    '''    async def invoke_side_effect(self, invocation: object) -> Any:
        if inspect.iscoroutinefunction(self._func):
            return await self._func(invocation)
        value = await asyncio.to_thread(self._func, invocation)
        if inspect.isawaitable(value):
            return await value
        return value

    async def reconcile(self, invocation: ReconciliationInvocation) -> ReconciliationResult:
        if self._reconcile_func is None:
            raise RuntimeError("tool adapter has no reconciliation implementation")
        if inspect.iscoroutinefunction(self._reconcile_func):
            value = await self._reconcile_func(invocation)
        else:
            value = await asyncio.to_thread(self._reconcile_func, invocation)
            if inspect.isawaitable(value):
                value = await value
        if not isinstance(value, ReconciliationResult):
            raise TypeError("reconciliation adapter must return ReconciliationResult")
        return value
''',
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
    ReconciliationInvocation,
    ReconciliationResult,
    ReconciliationTool,
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
''',
)

replace_once(
    "src/agentforge/runtime/tool_coordinator.py",
    '''class ToolCoordinator:
''',
    '''@dataclass(slots=True)
class PreparedReconciliation:
    call: ToolCall
    snapshot: ActionSnapshot
    action: ExternalAction
    tool: ReconciliationTool
    binding: ToolBinding


class ToolCoordinator:
''',
)

replace_once(
    "src/agentforge/runtime/tool_coordinator.py",
    '''    def prepare_recovered_side_effect(
''',
    '''    def reconciliation_binding(
        self,
        *,
        call: ToolCall,
        snapshot: ActionSnapshot,
        action: ExternalAction,
        agent_version: AgentVersion,
    ) -> ToolBinding:
        if call.status is not ToolCallStatus.UNRESOLVED:
            raise ValueError("reconciliation requires UNRESOLVED ToolCall")
        if action.status not in {
            ExternalActionStatus.UNKNOWN,
            ExternalActionStatus.RECONCILING,
        }:
            raise ValueError("reconciliation requires UNKNOWN/RECONCILING ExternalAction")
        if call.id != action.tool_call_id or snapshot.id != action.action_snapshot_id:
            raise ValueError("reconciliation durable identity mismatch")
        if call.tool_version_id != snapshot.tool_version_id:
            raise ValueError("reconciliation ToolVersion mismatch")
        if action.operation_id != snapshot.operation_id or call.arguments != snapshot.arguments:
            raise ValueError("reconciliation snapshot identity mismatch")
        binding = self._binding(call.tool_name, agent_version)
        if binding.tool_version_id != snapshot.tool_version_id:
            raise ValueError("reconciliation binding no longer matches snapshot")
        return binding

    def prepare_reconciliation(
        self,
        *,
        call: ToolCall,
        snapshot: ActionSnapshot,
        action: ExternalAction,
        agent_version: AgentVersion,
    ) -> PreparedReconciliation:
        binding = self.reconciliation_binding(
            call=call,
            snapshot=snapshot,
            action=action,
            agent_version=agent_version,
        )
        if binding.reconciliation_mode is ReconciliationMode.NONE:
            raise PermissionError("ToolVersion declares no reconciliation capability")
        tool = self._resolve_bound_tool(binding, agent_version)
        if not isinstance(tool, ReconciliationTool):
            raise PermissionError("tool adapter does not implement reconciliation contract")
        return PreparedReconciliation(
            call=call,
            snapshot=snapshot,
            action=action,
            tool=cast(ReconciliationTool, tool),
            binding=binding,
        )

    async def execute_reconciliation(
        self,
        prepared: PreparedReconciliation,
    ) -> ReconciliationResult:
        invocation = ReconciliationInvocation(
            operation_id=prepared.action.operation_id,
            arguments=dict(prepared.snapshot.arguments),
            credential_ref=prepared.snapshot.credential_ref,
        )
        return await prepared.tool.reconcile(invocation)

    def prepare_recovered_side_effect(
''',
)


# ---------------------------------------------------------------------------
# ORM model and migration.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/infrastructure/db/models.py",
    '''    ExternalActionStatus,
    QueueReason,
    ReconciliationMode,
''',
    '''    ExternalActionStatus,
    QueueReason,
    ReconciliationAttemptStatus,
    ReconciliationBusinessResult,
    ReconciliationMode,
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
            "reconciliation_max_attempts > 0",
            name="ck_tool_versions_positive_reconciliation_attempts",
        ),
        CheckConstraint(
            "reconciliation_initial_backoff_seconds >= 0",
            name="ck_tool_versions_nonnegative_reconciliation_initial_backoff",
        ),
        CheckConstraint(
            "reconciliation_max_backoff_seconds >= reconciliation_initial_backoff_seconds",
            name="ck_tool_versions_reconciliation_backoff_order",
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
    reconciliation_max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    reconciliation_initial_backoff_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )
    reconciliation_max_backoff_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30
    )
    created_at: Mapped[datetime] = mapped_column(
''',
)

replace_once(
    "src/agentforge/infrastructure/db/models.py",
    '''class DomainEventRow(Base):
''',
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
    business_result: Mapped[ReconciliationBusinessResult | None] = mapped_column(
        Enum(ReconciliationBusinessResult, name="reconciliation_business_result"),
        nullable=True,
    )
    evidence: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    outcome_reason: Mapped[str | None] = mapped_column(String(120))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DomainEventRow(Base):
''',
)

Path("migrations/versions/0013_reconciliation.py").write_text(
    '''"""add Stage 3.2-D3 reconciliation lifecycle and safety policy

Revision ID: 0013_reconciliation
Revises: 0012_side_effect_retry
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_reconciliation"
down_revision: str | None = "0012_side_effect_retry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # PostgreSQL requires a newly added enum value to commit before it can be
    # referenced by later DDL such as the Run-state CHECK constraint below.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE run_status ADD VALUE IF NOT EXISTS 'WAITING_ACTION_RESOLUTION'")

    reconciliation_attempt_status = postgresql.ENUM(
        "STARTED",
        "SUCCEEDED",
        "FAILED",
        name="reconciliation_attempt_status",
    )
    reconciliation_attempt_status.create(op.get_bind(), checkfirst=True)
    reconciliation_business_result = postgresql.ENUM(
        "SUCCEEDED",
        "FAILED",
        "NOT_EXECUTED",
        "UNKNOWN",
        name="reconciliation_business_result",
    )
    reconciliation_business_result.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "tool_versions",
        sa.Column("reconciliation_max_attempts", sa.Integer(), nullable=False, server_default="3"),
    )
    op.add_column(
        "tool_versions",
        sa.Column(
            "reconciliation_initial_backoff_seconds",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "tool_versions",
        sa.Column(
            "reconciliation_max_backoff_seconds",
            sa.Integer(),
            nullable=False,
            server_default="30",
        ),
    )
    op.create_check_constraint(
        "ck_tool_versions_positive_reconciliation_attempts",
        "tool_versions",
        "reconciliation_max_attempts > 0",
    )
    op.create_check_constraint(
        "ck_tool_versions_nonnegative_reconciliation_initial_backoff",
        "tool_versions",
        "reconciliation_initial_backoff_seconds >= 0",
    )
    op.create_check_constraint(
        "ck_tool_versions_reconciliation_backoff_order",
        "tool_versions",
        "reconciliation_max_backoff_seconds >= reconciliation_initial_backoff_seconds",
    )
    op.alter_column("tool_versions", "reconciliation_max_attempts", server_default=None)
    op.alter_column(
        "tool_versions",
        "reconciliation_initial_backoff_seconds",
        server_default=None,
    )
    op.alter_column(
        "tool_versions",
        "reconciliation_max_backoff_seconds",
        server_default=None,
    )

    op.drop_constraint("ck_runs_nonterminal_has_no_completed_at", "runs", type_="check")
    op.create_check_constraint(
        "ck_runs_nonterminal_has_no_completed_at",
        "runs",
        "status NOT IN ('CREATED', 'QUEUED', 'RUNNING', 'WAITING_ACTION_RESOLUTION') "
        "OR completed_at IS NULL",
    )

    op.create_table(
        "reconciliation_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "external_action_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("external_actions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
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
            "business_result",
            postgresql.ENUM(
                "SUCCEEDED",
                "FAILED",
                "NOT_EXECUTED",
                "UNKNOWN",
                name="reconciliation_business_result",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column("evidence", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("outcome_reason", sa.String(length=120), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
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


def downgrade() -> None:
    op.drop_index("ix_reconciliation_attempts_run_id", table_name="reconciliation_attempts")
    op.drop_index(
        "uq_reconciliation_attempts_one_started_per_action",
        table_name="reconciliation_attempts",
    )
    op.drop_table("reconciliation_attempts")
    op.drop_constraint(
        "ck_tool_versions_reconciliation_backoff_order",
        "tool_versions",
        type_="check",
    )
    op.drop_constraint(
        "ck_tool_versions_nonnegative_reconciliation_initial_backoff",
        "tool_versions",
        type_="check",
    )
    op.drop_constraint(
        "ck_tool_versions_positive_reconciliation_attempts",
        "tool_versions",
        type_="check",
    )
    op.drop_column("tool_versions", "reconciliation_max_backoff_seconds")
    op.drop_column("tool_versions", "reconciliation_initial_backoff_seconds")
    op.drop_column("tool_versions", "reconciliation_max_attempts")
    postgresql.ENUM(name="reconciliation_business_result").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="reconciliation_attempt_status").drop(op.get_bind(), checkfirst=True)
'''
)


# ---------------------------------------------------------------------------
# ToolVersion mapping.
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
''',
    '''                side_effect_retry_max_backoff_seconds=side_effect_retry_max_backoff_seconds,
                reconciliation_max_attempts=reconciliation_max_attempts,
                reconciliation_initial_backoff_seconds=reconciliation_initial_backoff_seconds,
                reconciliation_max_backoff_seconds=reconciliation_max_backoff_seconds,
            )
''',
)

replace_once(
    "src/agentforge/infrastructure/db/mappers.py",
    '''                side_effect_retry_max_backoff_seconds,
            ) in bindings
''',
    '''                side_effect_retry_max_backoff_seconds,
                reconciliation_max_attempts,
                reconciliation_initial_backoff_seconds,
                reconciliation_max_backoff_seconds,
            ) in bindings
''',
)

replace_once(
    "src/agentforge/infrastructure/db/runtime_store.py",
    '''                        ToolVersionRow.side_effect_retry_max_backoff_seconds,
                    )
''',
    '''                        ToolVersionRow.side_effect_retry_max_backoff_seconds,
                        ToolVersionRow.reconciliation_max_attempts,
                        ToolVersionRow.reconciliation_initial_backoff_seconds,
                        ToolVersionRow.reconciliation_max_backoff_seconds,
                    )
''',
)

replace_once(
    "src/agentforge/infrastructure/db/runtime_store.py",
    '''                        side_effect_retry_max_backoff_seconds,
                    )
                    for (
''',
    '''                        side_effect_retry_max_backoff_seconds,
                        reconciliation_max_attempts,
                        reconciliation_initial_backoff_seconds,
                        reconciliation_max_backoff_seconds,
                    )
                    for (
''',
)

replace_once(
    "src/agentforge/infrastructure/db/runtime_store.py",
    '''                        side_effect_retry_max_backoff_seconds,
                    ) in rows
''',
    '''                        side_effect_retry_max_backoff_seconds,
                        reconciliation_max_attempts,
                        reconciliation_initial_backoff_seconds,
                        reconciliation_max_backoff_seconds,
                    ) in rows
''',
)


# ---------------------------------------------------------------------------
# ExecutionJournal reconciliation lifecycle.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/application/run_manager.py",
    '''    QueueReason,
    RunStatus,
''',
    '''    QueueReason,
    ReconciliationAttemptStatus,
    ReconciliationBusinessResult,
    ReconciliationMode,
    RunStatus,
''',
)

replace_once(
    "src/agentforge/application/run_manager.py",
    '''    ModelInvocation,
    Run,
''',
    '''    ModelInvocation,
    ReconciliationAttempt,
    Run,
''',
)

replace_once(
    "src/agentforge/application/run_manager.py",
    '''    PreparedExternalAction,
    PreparedToolCall,
''',
    '''    PreparedExternalAction,
    PreparedToolCall,
''',
)

replace_once(
    "src/agentforge/application/run_manager.py",
    '''from agentforge.application.ports import ExecutionRecorder
''',
    '''from agentforge.application.ports import ExecutionRecorder, ReconciliationResult
''',
)

replace_once(
    "src/agentforge/application/run_manager.py",
    '''    tool_attempts: list[ToolExecutionAttempt] = field(default_factory=list)
''',
    '''    tool_attempts: list[ToolExecutionAttempt] = field(default_factory=list)
    reconciliation_attempts: list[ReconciliationAttempt] = field(default_factory=list)
''',
)

replace_once(
    "src/agentforge/application/run_manager.py",
    '''    async def record_side_effect_attempt_started(
''',
    r'''    async def load_reconciliation_external_action(
        self,
        run_id: UUID,
    ) -> tuple[ToolCall, ActionSnapshot, ExternalAction] | None:
        actions = [
            action
            for action in self.external_actions
            if action.run_id == run_id
            and action.status in {
                ExternalActionStatus.UNKNOWN,
                ExternalActionStatus.RECONCILING,
            }
        ]
        if len(actions) > 1:
            raise RuntimeError("found multiple reconciliation ExternalActions for one Run")
        if not actions:
            return None
        action = actions[0]
        call = next(item for item in self.tool_calls if item.id == action.tool_call_id)
        snapshot = next(
            item for item in self.action_snapshots if item.id == action.action_snapshot_id
        )
        if call.status is not ToolCallStatus.UNRESOLVED:
            raise RuntimeError("reconciliation action does not project to UNRESOLVED ToolCall")
        return call, snapshot, action

    async def record_action_manual_review(
        self,
        call: ToolCall,
        action: ExternalAction,
        run: Run,
        reason: str,
        *,
        expected_generation: int,
    ) -> None:
        if call.status is not ToolCallStatus.UNRESOLVED:
            raise ValueError("manual review requires UNRESOLVED ToolCall")
        action.manual_review()
        run.wait_for_action_resolution()
        self._append_event(
            run,
            EventType.ACTION_MANUAL_REVIEW,
            {
                "external_action_id": str(action.id),
                "operation_id": str(action.operation_id),
                "reason": reason,
            },
        )

    async def record_reconciliation_started(
        self,
        call: ToolCall,
        action: ExternalAction,
        run: Run,
        *,
        max_attempts: int,
        expected_generation: int,
    ) -> ReconciliationAttempt | None:
        if call.status is not ToolCallStatus.UNRESOLVED:
            raise ValueError("reconciliation requires UNRESOLVED ToolCall")
        if action.status not in {
            ExternalActionStatus.UNKNOWN,
            ExternalActionStatus.RECONCILING,
        }:
            raise ValueError("reconciliation requires unresolved ExternalAction")
        if max_attempts <= 0:
            raise ValueError("reconciliation max_attempts must be positive")
        active = [
            item
            for item in self.reconciliation_attempts
            if item.external_action_id == action.id
            and item.status is ReconciliationAttemptStatus.STARTED
        ]
        if active:
            raise RuntimeError("reconciliation attempt already STARTED")
        attempts = [
            item for item in self.reconciliation_attempts if item.external_action_id == action.id
        ]
        if len(attempts) >= max_attempts:
            await self.record_action_manual_review(
                call,
                action,
                run,
                "RECONCILIATION_BUDGET_EXHAUSTED",
                expected_generation=expected_generation,
            )
            return None
        attempt = ReconciliationAttempt(
            uuid4(),
            run.id,
            action.id,
            len(attempts) + 1,
            expected_generation,
        )
        self.reconciliation_attempts.append(attempt)
        action.start_reconciliation()
        self._append_event(
            run,
            EventType.RECONCILIATION_STARTED,
            {
                "external_action_id": str(action.id),
                "attempt_id": str(attempt.id),
                "attempt_number": attempt.attempt_number,
            },
        )
        return attempt

    async def record_reconciliation_failed(
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
        if action.status is not ExternalActionStatus.RECONCILING:
            raise ValueError("reconciliation request failure requires RECONCILING action")
        attempt.fail(error, outcome_reason="RECONCILIATION_REQUEST_FAILED")
        self._append_event(
            run,
            EventType.RECONCILIATION_FAILED,
            {
                "external_action_id": str(action.id),
                "attempt_id": str(attempt.id),
                "attempt_number": attempt.attempt_number,
                "error": error,
            },
        )
        if attempt.attempt_number < max_attempts:
            delay_seconds = min(
                initial_backoff_seconds * (2 ** (attempt.attempt_number - 1)),
                max_backoff_seconds,
            )
            run.yield_to_queue(QueueReason.RETRY)
            run.available_at = utcnow() + timedelta(seconds=delay_seconds)
            self._append_event(
                run,
                EventType.RECONCILIATION_RETRY_SCHEDULED,
                {
                    "external_action_id": str(action.id),
                    "attempt_number": attempt.attempt_number,
                    "delay_seconds": delay_seconds,
                },
            )
            return True
        action.manual_review()
        run.wait_for_action_resolution()
        self._append_event(
            run,
            EventType.ACTION_MANUAL_REVIEW,
            {
                "external_action_id": str(action.id),
                "operation_id": str(action.operation_id),
                "reason": "RECONCILIATION_BUDGET_EXHAUSTED",
            },
        )
        return False

    async def record_reconciliation_result(
        self,
        call: ToolCall,
        action: ExternalAction,
        attempt: ReconciliationAttempt,
        run: Run,
        result: ReconciliationResult,
        *,
        binding: ToolBinding,
        expected_generation: int,
    ) -> RunMessage | None:
        if action.status is not ExternalActionStatus.RECONCILING:
            raise ValueError("reconciliation result requires RECONCILING action")
        attempt.succeed(result.outcome, result.evidence)
        self._append_event(
            run,
            EventType.RECONCILIATION_SUCCEEDED,
            {
                "external_action_id": str(action.id),
                "attempt_id": str(attempt.id),
                "attempt_number": attempt.attempt_number,
                "business_result": result.outcome.value,
            },
        )
        if result.outcome is ReconciliationBusinessResult.SUCCEEDED:
            action.reconcile_succeeded()
            call.status = ToolCallStatus.SUCCEEDED
            call.result = {
                "reconciliation": "SUCCEEDED",
                "evidence": result.evidence,
            }
            message = RunMessage(
                run.id,
                len(self.messages) + 1,
                MessageRole.TOOL,
                tool_result_message_content(call.result),
                call.id,
            )
            self.messages.append(message)
            self._append_event(
                run,
                EventType.ACTION_SUCCEEDED,
                {
                    "external_action_id": str(action.id),
                    "operation_id": str(action.operation_id),
                    "source": "RECONCILIATION",
                },
            )
            return message

        if result.outcome is ReconciliationBusinessResult.FAILED:
            action.reconcile_failed()
            call.status = ToolCallStatus.FAILED
            call.error = "authoritative reconciliation confirmed action failure"
            run.fail("RECONCILIATION_CONFIRMED_ACTION_FAILED")
            self._append_event(
                run,
                EventType.ACTION_FAILED,
                {
                    "external_action_id": str(action.id),
                    "operation_id": str(action.operation_id),
                    "source": "RECONCILIATION",
                },
            )
            self._append_event(run, EventType.RUN_FAILED, {"reason": run.failure_reason})
            return None

        safe_not_executed = (
            result.outcome is ReconciliationBusinessResult.NOT_EXECUTED
            and (
                binding.reconciliation_mode is ReconciliationMode.AUTHORITATIVE
                or (
                    binding.reconciliation_mode is ReconciliationMode.BEST_EFFORT
                    and binding.idempotency_supported
                )
            )
        )
        if safe_not_executed:
            physical_attempts = [
                item for item in self.tool_attempts if item.external_action_id == action.id
            ]
            physical_number = max((item.attempt_number for item in physical_attempts), default=0)
            delay_seconds = binding.side_effect_retry_delay_seconds(max(physical_number, 1))
            assert self.run_state is not None
            retry_allowed = (
                physical_number < binding.side_effect_retry_max_attempts
                and self.run_state.tool_attempts_used < run.max_tool_attempts
                and utcnow() + timedelta(seconds=delay_seconds) < run.deadline_at
            )
            if retry_allowed:
                action.reconcile_retry_ready()
                call.status = ToolCallStatus.READY
                call.error = "reconciliation proved NOT_EXECUTED"
                run.yield_to_queue(QueueReason.RETRY)
                run.available_at = utcnow() + timedelta(seconds=delay_seconds)
                self._append_event(
                    run,
                    EventType.ACTION_RETRY_READY,
                    {
                        "external_action_id": str(action.id),
                        "operation_id": str(action.operation_id),
                        "source": "RECONCILIATION_NOT_EXECUTED",
                    },
                )
                self._append_event(
                    run,
                    EventType.TOOL_RETRY_SCHEDULED,
                    {
                        "tool_call_id": str(call.id),
                        "attempt_number": physical_number,
                        "delay_seconds": delay_seconds,
                        "source": "RECONCILIATION",
                    },
                )
                return None
            if physical_number >= binding.side_effect_retry_max_attempts:
                action.reconcile_failed()
                call.status = ToolCallStatus.FAILED
                call.error = "side-effect retry policy exhausted after reconciliation"
                run.fail("SIDE_EFFECT_RETRY_EXHAUSTED_AFTER_RECONCILIATION")
                self._append_event(
                    run,
                    EventType.ACTION_FAILED,
                    {
                        "external_action_id": str(action.id),
                        "operation_id": str(action.operation_id),
                        "reason": run.failure_reason,
                    },
                )
            else:
                action.reconcile_abort_not_executed()
                call.status = ToolCallStatus.NOT_EXECUTED
                reason = (
                    "BUDGET_EXCEEDED: max_tool_attempts exhausted"
                    if self.run_state.tool_attempts_used >= run.max_tool_attempts
                    else "DEADLINE_EXCEEDED: side-effect retry due time reaches run deadline"
                )
                call.error = reason
                run.fail(reason)
                self._append_event(
                    run,
                    EventType.ACTION_ABORTED,
                    {
                        "external_action_id": str(action.id),
                        "operation_id": str(action.operation_id),
                        "reason": reason,
                    },
                )
            self._append_event(run, EventType.RUN_FAILED, {"reason": run.failure_reason})
            return None

        action.manual_review()
        run.wait_for_action_resolution()
        reason = (
            "RECONCILIATION_UNKNOWN"
            if result.outcome is ReconciliationBusinessResult.UNKNOWN
            else "BEST_EFFORT_NOT_EXECUTED_UNSAFE"
        )
        self._append_event(
            run,
            EventType.ACTION_MANUAL_REVIEW,
            {
                "external_action_id": str(action.id),
                "operation_id": str(action.operation_id),
                "reason": reason,
            },
        )
        return None

    async def record_side_effect_attempt_started(
''',
)


# ---------------------------------------------------------------------------
# PostgreSQL recorder reconciliation persistence.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''    ExternalActionStatus,
    ModelInvocationStatus,
''',
    '''    ExternalActionStatus,
    ModelInvocationStatus,
    ReconciliationAttemptStatus,
    ReconciliationBusinessResult,
    ReconciliationMode,
''',
)

replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''    ModelInvocation,
    Run,
''',
    '''    ModelInvocation,
    ReconciliationAttempt,
    Run,
''',
)

replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''from agentforge.application.ports import ExecutionRecorder
''',
    '''from agentforge.application.ports import ExecutionRecorder, ReconciliationResult
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
    '''    async def record_side_effect_attempt_started(
''',
    r'''    async def load_reconciliation_external_action(
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
                        ExternalActionRow.status.in_(
                            [ExternalActionStatus.UNKNOWN, ExternalActionStatus.RECONCILING]
                        ),
                        ExternalActionRow.current_attempt_id.is_(None),
                        ToolCallRow.status == ToolCallStatus.UNRESOLVED,
                    )
                )
            ).all()
        if len(rows) > 1:
            raise RuntimeError("found multiple reconciliation ExternalActions for one Run")
        if not rows:
            return None
        action_row, call_row, snapshot_row = rows[0]
        return (
            tool_call_from_row(call_row),
            action_snapshot_from_row(snapshot_row),
            external_action_from_row(action_row),
        )

    async def record_action_manual_review(
        self,
        call: ToolCall,
        action: ExternalAction,
        run: Run,
        reason: str,
        *,
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
                    .where(
                        ExternalActionRow.id == action.id,
                        ExternalActionRow.run_id == run.id,
                    )
                    .with_for_update()
                )
            ).scalar_one()
            call_row = (
                await session.execute(
                    select(ToolCallRow)
                    .where(
                        ToolCallRow.id == call.id,
                        ToolCallRow.run_id == run.id,
                    )
                    .with_for_update()
                )
            ).scalar_one()
            if action_row.status not in {
                ExternalActionStatus.UNKNOWN,
                ExternalActionStatus.RECONCILING,
            }:
                raise RuntimeError("manual review action is no longer unresolved")
            if call_row.status is not ToolCallStatus.UNRESOLVED:
                raise RuntimeError("manual review ToolCall is no longer UNRESOLVED")
            started_reconcile = await session.scalar(
                select(ReconciliationAttemptRow.id)
                .where(
                    ReconciliationAttemptRow.external_action_id == action.id,
                    ReconciliationAttemptRow.status == ReconciliationAttemptStatus.STARTED,
                )
                .limit(1)
            )
            if started_reconcile is not None:
                raise RuntimeError("cannot enter manual review with STARTED reconciliation")
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
                        "operation_id": str(action.operation_id),
                        "reason": reason,
                    },
                )
            )
            await session.flush()
        action.manual_review()
        run.wait_for_action_resolution()

    async def record_reconciliation_started(
        self,
        call: ToolCall,
        action: ExternalAction,
        run: Run,
        *,
        max_attempts: int,
        expected_generation: int,
    ) -> ReconciliationAttempt | None:
        self._assert_generation(expected_generation)
        if max_attempts <= 0:
            raise ValueError("reconciliation max_attempts must be positive")
        attempt_id = uuid4()
        attempt_number = 0
        async with self._sessions() as session, session.begin():
            run_row = await _lock_owned_run(
                session,
                run_id=run.id,
                expected_generation=expected_generation,
            )
            action_row = (
                await session.execute(
                    select(ExternalActionRow)
                    .where(
                        ExternalActionRow.id == action.id,
                        ExternalActionRow.run_id == run.id,
                    )
                    .with_for_update()
                )
            ).scalar_one()
            call_row = (
                await session.execute(
                    select(ToolCallRow)
                    .where(
                        ToolCallRow.id == call.id,
                        ToolCallRow.run_id == run.id,
                    )
                    .with_for_update()
                )
            ).scalar_one()
            if action_row.status not in {
                ExternalActionStatus.UNKNOWN,
                ExternalActionStatus.RECONCILING,
            }:
                raise RuntimeError("ExternalAction is not eligible for reconciliation")
            if action_row.current_attempt_id is not None:
                raise RuntimeError("reconciliation cannot overlap side-effect authorization")
            if call_row.status is not ToolCallStatus.UNRESOLVED:
                raise RuntimeError("reconciliation ToolCall is not UNRESOLVED")
            await _assert_no_started_model_invocations(session, run.id)
            await _assert_no_started_tool_attempts(session, run.id)
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
            count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(ReconciliationAttemptRow)
                    .where(ReconciliationAttemptRow.external_action_id == action.id)
                )
                or 0
            )
            if count >= max_attempts:
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
                            "operation_id": str(action.operation_id),
                            "reason": "RECONCILIATION_BUDGET_EXHAUSTED",
                        },
                    )
                )
                await session.flush()
                action.manual_review()
                run.wait_for_action_resolution()
                return None

            attempt_number = count + 1
            session.add(
                ReconciliationAttemptRow(
                    id=attempt_id,
                    run_id=run.id,
                    external_action_id=action.id,
                    attempt_number=attempt_number,
                    execution_generation=expected_generation,
                    status=ReconciliationAttemptStatus.STARTED,
                )
            )
            action_row.status = ExternalActionStatus.RECONCILING
            action_row.updated_at = func.clock_timestamp()
            seq = next(iter(await _allocate_event_sequences(session, run.id, 1)))
            session.add(
                DomainEventRow(
                    id=uuid4(),
                    run_id=run.id,
                    sequence=seq,
                    event_type=EventType.RECONCILIATION_STARTED.value,
                    payload={
                        "external_action_id": str(action.id),
                        "attempt_id": str(attempt_id),
                        "attempt_number": attempt_number,
                    },
                )
            )
            await session.flush()

        action.start_reconciliation()
        return ReconciliationAttempt(
            attempt_id,
            run.id,
            action.id,
            attempt_number,
            expected_generation,
        )

    async def record_reconciliation_failed(
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
                    .where(
                        ExternalActionRow.id == action.id,
                        ExternalActionRow.run_id == run.id,
                    )
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
                raise RuntimeError("reconciliation request failure lost current authority")
            db_now = await _database_now(session)
            attempt_row.status = ReconciliationAttemptStatus.FAILED
            attempt_row.error = error
            attempt_row.outcome_reason = "RECONCILIATION_REQUEST_FAILED"
            attempt_row.finished_at = db_now

            seq_count = 2 if attempt.attempt_number < max_attempts else 2
            seqs = list(await _allocate_event_sequences(session, run.id, seq_count))
            session.add(
                DomainEventRow(
                    id=uuid4(),
                    run_id=run.id,
                    sequence=seqs[0],
                    event_type=EventType.RECONCILIATION_FAILED.value,
                    payload={
                        "external_action_id": str(action.id),
                        "attempt_id": str(attempt.id),
                        "attempt_number": attempt.attempt_number,
                        "error": error,
                    },
                )
            )
            if attempt.attempt_number < max_attempts:
                delay_seconds = min(
                    initial_backoff_seconds * (2 ** (attempt.attempt_number - 1)),
                    max_backoff_seconds,
                )
                run_row.status = RunStatus.QUEUED
                run_row.queue_reason = QueueReason.RETRY
                run_row.available_at = db_now + timedelta(seconds=delay_seconds)
                run_row.owner_worker_id = None
                run_row.lease_expires_at = None
                session.add(
                    DomainEventRow(
                        id=uuid4(),
                        run_id=run.id,
                        sequence=seqs[1],
                        event_type=EventType.RECONCILIATION_RETRY_SCHEDULED.value,
                        payload={
                            "external_action_id": str(action.id),
                            "attempt_number": attempt.attempt_number,
                            "delay_seconds": delay_seconds,
                        },
                    )
                )
                await session.flush()
                attempt.fail(error, outcome_reason="RECONCILIATION_REQUEST_FAILED")
                run.status = RunStatus.QUEUED
                run.queue_reason = QueueReason.RETRY
                run.available_at = db_now + timedelta(seconds=delay_seconds)
                run.owner_worker_id = None
                run.lease_expires_at = None
                return True

            action_row.status = ExternalActionStatus.MANUAL_REVIEW
            action_row.updated_at = db_now
            run_row.status = RunStatus.WAITING_ACTION_RESOLUTION
            run_row.queue_reason = None
            run_row.available_at = None
            run_row.owner_worker_id = None
            run_row.lease_expires_at = None
            session.add(
                DomainEventRow(
                    id=uuid4(),
                    run_id=run.id,
                    sequence=seqs[1],
                    event_type=EventType.ACTION_MANUAL_REVIEW.value,
                    payload={
                        "external_action_id": str(action.id),
                        "operation_id": str(action.operation_id),
                        "reason": "RECONCILIATION_BUDGET_EXHAUSTED",
                    },
                )
            )
            await session.flush()
        attempt.fail(error, outcome_reason="RECONCILIATION_REQUEST_FAILED")
        action.manual_review()
        run.wait_for_action_resolution()
        return False

    async def record_reconciliation_result(
        self,
        call: ToolCall,
        action: ExternalAction,
        attempt: ReconciliationAttempt,
        run: Run,
        result: ReconciliationResult,
        *,
        binding: ToolBinding,
        expected_generation: int,
    ) -> RunMessage | None:
        self._assert_generation(expected_generation)
        returned_message: RunMessage | None = None
        async with self._sessions() as session, session.begin():
            run_row = await _lock_owned_run(
                session,
                run_id=run.id,
                expected_generation=expected_generation,
            )
            action_row = (
                await session.execute(
                    select(ExternalActionRow)
                    .where(
                        ExternalActionRow.id == action.id,
                        ExternalActionRow.run_id == run.id,
                    )
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
            call_row = (
                await session.execute(
                    select(ToolCallRow)
                    .where(
                        ToolCallRow.id == call.id,
                        ToolCallRow.run_id == run.id,
                    )
                    .with_for_update()
                )
            ).scalar_one()
            if (
                action_row.status is not ExternalActionStatus.RECONCILING
                or attempt_row.status is not ReconciliationAttemptStatus.STARTED
                or call_row.status is not ToolCallStatus.UNRESOLVED
            ):
                raise RuntimeError("reconciliation result lost current authority")

            db_now = await _database_now(session)
            attempt_row.status = ReconciliationAttemptStatus.SUCCEEDED
            attempt_row.business_result = result.outcome
            attempt_row.evidence = result.evidence
            attempt_row.finished_at = db_now
            seqs = list(await _allocate_event_sequences(session, run.id, 3))
            session.add(
                DomainEventRow(
                    id=uuid4(),
                    run_id=run.id,
                    sequence=seqs[0],
                    event_type=EventType.RECONCILIATION_SUCCEEDED.value,
                    payload={
                        "external_action_id": str(action.id),
                        "attempt_id": str(attempt.id),
                        "attempt_number": attempt.attempt_number,
                        "business_result": result.outcome.value,
                    },
                )
            )

            if result.outcome is ReconciliationBusinessResult.SUCCEEDED:
                action_row.status = ExternalActionStatus.SUCCEEDED
                action_row.updated_at = db_now
                call_row.status = ToolCallStatus.SUCCEEDED
                call_row.error = None
                call_row.result = {
                    "reconciliation": "SUCCEEDED",
                    "evidence": result.evidence,
                }
                message_seq = await _allocate_message_sequence(session, run.id)
                session.add(
                    RunMessageRow(
                        id=uuid4(),
                        run_id=run.id,
                        sequence=message_seq,
                        role=MessageRole.TOOL.value,
                        content=tool_result_message_content(call_row.result),
                        source_id=call.id,
                    )
                )
                session.add(
                    DomainEventRow(
                        id=uuid4(),
                        run_id=run.id,
                        sequence=seqs[1],
                        event_type=EventType.ACTION_SUCCEEDED.value,
                        payload={
                            "external_action_id": str(action.id),
                            "operation_id": str(action.operation_id),
                            "source": "RECONCILIATION",
                        },
                    )
                )
                session.add(
                    DomainEventRow(
                        id=uuid4(),
                        run_id=run.id,
                        sequence=seqs[2],
                        event_type=EventType.TOOL_SUCCEEDED.value,
                        payload={
                            "tool_call_id": str(call.id),
                            "tool_name": call.tool_name,
                            "source": "RECONCILIATION",
                        },
                    )
                )
                returned_message = RunMessage(
                    run.id,
                    message_seq,
                    MessageRole.TOOL,
                    tool_result_message_content(call_row.result),
                    call.id,
                )

            elif result.outcome is ReconciliationBusinessResult.FAILED:
                action_row.status = ExternalActionStatus.FAILED
                action_row.updated_at = db_now
                call_row.status = ToolCallStatus.FAILED
                call_row.error = "reconciliation confirmed action failure"
                run_row.status = RunStatus.FAILED
                run_row.failure_reason = "RECONCILIATION_CONFIRMED_ACTION_FAILED"
                run_row.completed_at = db_now
                run_row.owner_worker_id = None
                run_row.lease_expires_at = None
                session.add(
                    DomainEventRow(
                        id=uuid4(),
                        run_id=run.id,
                        sequence=seqs[1],
                        event_type=EventType.ACTION_FAILED.value,
                        payload={
                            "external_action_id": str(action.id),
                            "operation_id": str(action.operation_id),
                            "source": "RECONCILIATION",
                        },
                    )
                )
                session.add(
                    DomainEventRow(
                        id=uuid4(),
                        run_id=run.id,
                        sequence=seqs[2],
                        event_type=EventType.RUN_FAILED.value,
                        payload={"reason": "RECONCILIATION_CONFIRMED_ACTION_FAILED"},
                    )
                )

            elif result.outcome is ReconciliationBusinessResult.NOT_EXECUTED and (
                binding.reconciliation_mode is ReconciliationMode.AUTHORITATIVE
                or (
                    binding.reconciliation_mode is ReconciliationMode.BEST_EFFORT
                    and binding.idempotency_supported
                )
            ):
                physical_number = int(
                    await session.scalar(
                        select(func.max(ToolExecutionAttemptRow.attempt_number)).where(
                            ToolExecutionAttemptRow.external_action_id == action.id
                        )
                    )
                    or 0
                )
                state = await _lock_run_state(session, run.id)
                delay_seconds = binding.side_effect_retry_delay_seconds(max(physical_number, 1))
                due_at = db_now + timedelta(seconds=delay_seconds)
                retry_allowed = (
                    physical_number < binding.side_effect_retry_max_attempts
                    and state.tool_attempts_used < run_row.max_tool_attempts
                    and due_at < run_row.deadline_at
                )
                if retry_allowed:
                    action_row.status = ExternalActionStatus.READY
                    action_row.updated_at = db_now
                    call_row.status = ToolCallStatus.READY
                    call_row.error = "reconciliation proved NOT_EXECUTED"
                    run_row.status = RunStatus.QUEUED
                    run_row.queue_reason = QueueReason.RETRY
                    run_row.available_at = due_at
                    run_row.owner_worker_id = None
                    run_row.lease_expires_at = None
                    session.add(
                        DomainEventRow(
                            id=uuid4(),
                            run_id=run.id,
                            sequence=seqs[1],
                            event_type=EventType.ACTION_RETRY_READY.value,
                            payload={
                                "external_action_id": str(action.id),
                                "operation_id": str(action.operation_id),
                                "source": "RECONCILIATION_NOT_EXECUTED",
                            },
                        )
                    )
                    session.add(
                        DomainEventRow(
                            id=uuid4(),
                            run_id=run.id,
                            sequence=seqs[2],
                            event_type=EventType.TOOL_RETRY_SCHEDULED.value,
                            payload={
                                "tool_call_id": str(call.id),
                                "attempt_number": physical_number,
                                "delay_seconds": delay_seconds,
                                "source": "RECONCILIATION",
                            },
                        )
                    )
                elif physical_number >= binding.side_effect_retry_max_attempts:
                    action_row.status = ExternalActionStatus.FAILED
                    action_row.updated_at = db_now
                    call_row.status = ToolCallStatus.FAILED
                    call_row.error = "side-effect retry policy exhausted after reconciliation"
                    run_row.status = RunStatus.FAILED
                    run_row.failure_reason = "SIDE_EFFECT_RETRY_EXHAUSTED_AFTER_RECONCILIATION"
                    run_row.completed_at = db_now
                    run_row.owner_worker_id = None
                    run_row.lease_expires_at = None
                    session.add(
                        DomainEventRow(
                            id=uuid4(),
                            run_id=run.id,
                            sequence=seqs[1],
                            event_type=EventType.ACTION_FAILED.value,
                            payload={
                                "external_action_id": str(action.id),
                                "operation_id": str(action.operation_id),
                                "reason": run_row.failure_reason,
                            },
                        )
                    )
                    session.add(
                        DomainEventRow(
                            id=uuid4(),
                            run_id=run.id,
                            sequence=seqs[2],
                            event_type=EventType.RUN_FAILED.value,
                            payload={"reason": run_row.failure_reason},
                        )
                    )
                else:
                    reason = (
                        "BUDGET_EXCEEDED: max_tool_attempts exhausted"
                        if state.tool_attempts_used >= run_row.max_tool_attempts
                        else "DEADLINE_EXCEEDED: side-effect retry due time reaches run deadline"
                    )
                    action_row.status = ExternalActionStatus.ABORTED
                    action_row.updated_at = db_now
                    call_row.status = ToolCallStatus.NOT_EXECUTED
                    call_row.error = reason
                    run_row.status = RunStatus.FAILED
                    run_row.failure_reason = reason
                    run_row.completed_at = db_now
                    run_row.owner_worker_id = None
                    run_row.lease_expires_at = None
                    session.add(
                        DomainEventRow(
                            id=uuid4(),
                            run_id=run.id,
                            sequence=seqs[1],
                            event_type=EventType.ACTION_ABORTED.value,
                            payload={
                                "external_action_id": str(action.id),
                                "operation_id": str(action.operation_id),
                                "reason": reason,
                            },
                        )
                    )
                    session.add(
                        DomainEventRow(
                            id=uuid4(),
                            run_id=run.id,
                            sequence=seqs[2],
                            event_type=EventType.RUN_FAILED.value,
                            payload={"reason": reason},
                        )
                    )

            else:
                reason = (
                    "RECONCILIATION_UNKNOWN"
                    if result.outcome is ReconciliationBusinessResult.UNKNOWN
                    else "BEST_EFFORT_NOT_EXECUTED_UNSAFE"
                )
                action_row.status = ExternalActionStatus.MANUAL_REVIEW
                action_row.updated_at = db_now
                run_row.status = RunStatus.WAITING_ACTION_RESOLUTION
                run_row.queue_reason = None
                run_row.available_at = None
                run_row.owner_worker_id = None
                run_row.lease_expires_at = None
                session.add(
                    DomainEventRow(
                        id=uuid4(),
                        run_id=run.id,
                        sequence=seqs[1],
                        event_type=EventType.ACTION_MANUAL_REVIEW.value,
                        payload={
                            "external_action_id": str(action.id),
                            "operation_id": str(action.operation_id),
                            "reason": reason,
                        },
                    )
                )
                session.add(
                    DomainEventRow(
                        id=uuid4(),
                        run_id=run.id,
                        sequence=seqs[2],
                        event_type=EventType.RUN_YIELDED.value,
                        payload={"reason": "WAITING_ACTION_RESOLUTION"},
                    )
                )
            await session.flush()

        attempt.succeed(result.outcome, result.evidence)
        if result.outcome is ReconciliationBusinessResult.SUCCEEDED:
            action.reconcile_succeeded()
            call.status = ToolCallStatus.SUCCEEDED
            call.error = None
            call.result = {"reconciliation": "SUCCEEDED", "evidence": result.evidence}
        elif result.outcome is ReconciliationBusinessResult.FAILED:
            action.reconcile_failed()
            call.status = ToolCallStatus.FAILED
            call.error = "reconciliation confirmed action failure"
            run.status = RunStatus.FAILED
            run.failure_reason = "RECONCILIATION_CONFIRMED_ACTION_FAILED"
            run.completed_at = datetime.now(run.deadline_at.tzinfo)
            run.owner_worker_id = None
            run.lease_expires_at = None
        elif result.outcome is ReconciliationBusinessResult.NOT_EXECUTED and (
            binding.reconciliation_mode is ReconciliationMode.AUTHORITATIVE
            or (
                binding.reconciliation_mode is ReconciliationMode.BEST_EFFORT
                and binding.idempotency_supported
            )
        ):
            if run_row.status is RunStatus.QUEUED:
                action.reconcile_retry_ready()
                call.status = ToolCallStatus.READY
                call.error = "reconciliation proved NOT_EXECUTED"
                run.status = RunStatus.QUEUED
                run.queue_reason = QueueReason.RETRY
                run.available_at = run_row.available_at
                run.owner_worker_id = None
                run.lease_expires_at = None
            elif action_row.status is ExternalActionStatus.FAILED:
                action.reconcile_failed()
                call.status = ToolCallStatus.FAILED
                call.error = call_row.error
                run.status = RunStatus.FAILED
                run.failure_reason = run_row.failure_reason
                run.completed_at = run_row.completed_at
                run.owner_worker_id = None
                run.lease_expires_at = None
            else:
                action.reconcile_abort_not_executed()
                call.status = ToolCallStatus.NOT_EXECUTED
                call.error = call_row.error
                run.status = RunStatus.FAILED
                run.failure_reason = run_row.failure_reason
                run.completed_at = run_row.completed_at
                run.owner_worker_id = None
                run.lease_expires_at = None
        else:
            action.manual_review()
            run.wait_for_action_resolution()
        return returned_message

    async def record_side_effect_attempt_started(
''',
)


# ---------------------------------------------------------------------------
# RunManager drives safety reconciliation before any new business reasoning.
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
    r'''        # Persisted unresolved external truth outranks new model reasoning.
        reconciliation_action = await recorder.load_reconciliation_external_action(run.id)
        if reconciliation_action is not None:
            unresolved_call, unresolved_snapshot, unresolved_action = reconciliation_action
            binding = self._tools.reconciliation_binding(
                call=unresolved_call,
                snapshot=unresolved_snapshot,
                action=unresolved_action,
                agent_version=agent_version,
            )
            if binding.reconciliation_mode is ReconciliationMode.NONE:
                await recorder.record_action_manual_review(
                    unresolved_call,
                    unresolved_action,
                    run,
                    "RECONCILIATION_MODE_NONE",
                    expected_generation=expected_generation,
                )
                return None
            prepared_reconciliation = self._tools.prepare_reconciliation(
                call=unresolved_call,
                snapshot=unresolved_snapshot,
                action=unresolved_action,
                agent_version=agent_version,
            )
            reconciliation_attempt = await recorder.record_reconciliation_started(
                unresolved_call,
                unresolved_action,
                run,
                max_attempts=binding.reconciliation_max_attempts,
                expected_generation=expected_generation,
            )
            if reconciliation_attempt is None:
                return None
            try:
                reconciliation_result = await self._tools.execute_reconciliation(
                    prepared_reconciliation
                )
            except Exception as exc:
                await recorder.record_reconciliation_failed(
                    unresolved_action,
                    reconciliation_attempt,
                    run,
                    error=str(exc),
                    max_attempts=binding.reconciliation_max_attempts,
                    initial_backoff_seconds=binding.reconciliation_initial_backoff_seconds,
                    max_backoff_seconds=binding.reconciliation_max_backoff_seconds,
                    expected_generation=expected_generation,
                )
                return None
            reconciled_message = await recorder.record_reconciliation_result(
                unresolved_call,
                unresolved_action,
                reconciliation_attempt,
                run,
                reconciliation_result,
                binding=binding,
                expected_generation=expected_generation,
            )
            if run.failure_reason is not None:
                raise RunExecutionFailedError(run.failure_reason)
            if reconciled_message is None:
                return None
            messages.append(reconciled_message)
            progression_steps += 1

        ready_action = await recorder.load_ready_external_action(run.id)
''',
)


# ---------------------------------------------------------------------------
# RuntimeStore orphan reconciliation recovery.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/infrastructure/db/runtime_store.py",
    '''    QueueReason,
    RunStatus,
''',
    '''    QueueReason,
    ReconciliationAttemptStatus,
    RunStatus,
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
    '''async def _prepare_orphaned_read_calls_for_retry(session: AsyncSession, run_id: UUID) -> list[UUID]:
''',
    r'''async def _recover_orphaned_reconciliation_attempts(
    session: AsyncSession,
    run_id: UUID,
) -> list[tuple[UUID, UUID]]:
    actions = (
        (
            await session.execute(
                select(ExternalActionRow)
                .where(
                    ExternalActionRow.run_id == run_id,
                    ExternalActionRow.status == ExternalActionStatus.RECONCILING,
                )
                .order_by(ExternalActionRow.id)
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    recovered: list[tuple[UUID, UUID]] = []
    for action in actions:
        attempt = (
            await session.execute(
                select(ReconciliationAttemptRow)
                .where(
                    ReconciliationAttemptRow.external_action_id == action.id,
                    ReconciliationAttemptRow.status == ReconciliationAttemptStatus.STARTED,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if attempt is None:
            continue
        attempt.status = ReconciliationAttemptStatus.FAILED
        attempt.error = "previous executor lease expired during read-only reconciliation"
        attempt.outcome_reason = "LEASE_LOST"
        attempt.finished_at = func.clock_timestamp()
        recovered.append((action.id, attempt.id))
    return recovered


async def _prepare_orphaned_read_calls_for_retry(session: AsyncSession, run_id: UUID) -> list[UUID]:
''',
)

replace_once(
    "src/agentforge/infrastructure/db/runtime_store.py",
    '''            recovered_call_ids = (
                await _prepare_orphaned_read_calls_for_retry(session, row.id)
                if was_recovery
                else []
            )
''',
    '''            recovered_reconciliations = (
                await _recover_orphaned_reconciliation_attempts(session, row.id)
                if was_recovery
                else []
            )
            recovered_call_ids = (
                await _prepare_orphaned_read_calls_for_retry(session, row.id)
                if was_recovery
                else []
            )
''',
)

replace_once(
    "src/agentforge/infrastructure/db/runtime_store.py",
    '''                    + len(recovered_side_effects)
                    + len(recovered_call_ids),
''',
    '''                    + len(recovered_side_effects)
                    + len(recovered_reconciliations)
                    + len(recovered_call_ids),
''',
)

replace_once(
    "src/agentforge/infrastructure/db/runtime_store.py",
    '''            for tool_call_id in recovered_call_ids:
                session.add(
''',
    '''            for external_action_id, attempt_id in recovered_reconciliations:
                session.add(
                    DomainEventRow(
                        id=uuid4(),
                        run_id=row.id,
                        sequence=sequences[offset],
                        event_type=EventType.RECONCILIATION_FAILED.value,
                        payload={
                            "external_action_id": str(external_action_id),
                            "attempt_id": str(attempt_id),
                            "reason": "LEASE_LOST",
                        },
                    )
                )
                offset += 1
            for tool_call_id in recovered_call_ids:
                session.add(
''',
)


# ---------------------------------------------------------------------------
# Unit test imports + D3 cases.
# ---------------------------------------------------------------------------
replace_once(
    "tests/unit/test_run_manager.py",
    '''from agentforge.domain.enums import (
    EventType,
    QueueReason,
''',
    '''from agentforge.domain.enums import (
    EventType,
    QueueReason,
    ReconciliationAttemptStatus,
    ReconciliationBusinessResult,
''',
)

replace_once(
    "tests/unit/test_run_manager.py",
    '''from agentforge.application.run_manager import ExecutionJournal, RunManager
''',
    '''from agentforge.application.ports import ReconciliationResult
from agentforge.application.run_manager import ExecutionJournal, RunManager
''',
)

append_text(
    "tests/unit/test_run_manager.py",
    "test_authoritative_reconciliation_not_executed_requeues_non_idempotent",
    r'''


@pytest.mark.asyncio
async def test_authoritative_reconciliation_not_executed_requeues_non_idempotent() -> None:
    from agentforge.application.errors import ToolAdapterError
    from agentforge.domain.enums import ExternalActionStatus, ReconciliationMode, ToolEffectType

    version_id = uuid4()
    physical_calls = 0
    reconcile_calls = 0

    async def ambiguous(_invocation):
        nonlocal physical_calls
        physical_calls += 1
        raise ToolAdapterError(
            "response lost",
            error_class="RESPONSE_LOST",
            definite_not_executed=False,
        )

    async def reconcile(_invocation):
        nonlocal reconcile_calls
        reconcile_calls += 1
        return ReconciliationResult(
            ReconciliationBusinessResult.NOT_EXECUTED,
            {"provider": "authoritative-ledger"},
        )

    registry = InMemoryToolRegistry(
        [
            SideEffectFunctionTool(
                version_id=version_id,
                name="authoritative_write",
                description="write",
                input_schema={"type": "object"},
                func=ambiguous,
                reconcile_func=reconcile,
            )
        ]
    )
    manager = RunManager(
        NativeRunner(
            ScriptedFakeModel([ToolStep("authoritative_write", {"v": 1})]),
            registry,
        ),
        ToolCoordinator(registry),
    )
    version = AgentVersion(
        uuid4(),
        uuid4(),
        1,
        "authoritative reconcile",
        (
            ToolBinding(
                version_id,
                "authoritative_write",
                effect_type=ToolEffectType.WRITE,
                allow_no_approval_execution=True,
                idempotency_supported=False,
                reconciliation_mode=ReconciliationMode.AUTHORITATIVE,
                side_effect_retry_max_attempts=2,
                side_effect_retry_initial_backoff_seconds=0,
                side_effect_retry_max_backoff_seconds=0,
            ),
        ),
    )
    run = Run(uuid4(), version.id, "write")
    run.queue()
    state = RunState(run.id)
    journal = ExecutionJournal()

    assert (
        await manager.execute(
            run=run,
            run_state=state,
            agent_version=version,
            recorder=journal,
        )
        is None
    )
    action = journal.external_actions[0]
    original_operation_id = action.operation_id
    assert action.status is ExternalActionStatus.UNKNOWN

    assert (
        await manager.execute(
            run=run,
            run_state=state,
            agent_version=version,
            recorder=journal,
        )
        is None
    )
    assert reconcile_calls == 1
    assert physical_calls == 1
    assert action.operation_id == original_operation_id
    assert action.status is ExternalActionStatus.READY
    assert journal.tool_calls[0].status is ToolCallStatus.READY
    assert run.status is RunStatus.QUEUED
    assert run.queue_reason is QueueReason.RETRY
    assert len(journal.reconciliation_attempts) == 1
    assert (
        journal.reconciliation_attempts[0].business_result
        is ReconciliationBusinessResult.NOT_EXECUTED
    )


@pytest.mark.asyncio
async def test_best_effort_non_idempotent_not_executed_requires_manual_review() -> None:
    from agentforge.application.errors import ToolAdapterError
    from agentforge.domain.enums import ExternalActionStatus, ReconciliationMode, ToolEffectType

    version_id = uuid4()

    async def ambiguous(_invocation):
        raise ToolAdapterError(
            "timeout",
            error_class="TIMEOUT",
            definite_not_executed=False,
        )

    async def reconcile(_invocation):
        return ReconciliationResult(ReconciliationBusinessResult.NOT_EXECUTED)

    registry = InMemoryToolRegistry(
        [
            SideEffectFunctionTool(
                version_id=version_id,
                name="best_effort_write",
                description="write",
                input_schema={"type": "object"},
                func=ambiguous,
                reconcile_func=reconcile,
            )
        ]
    )
    manager = RunManager(
        NativeRunner(ScriptedFakeModel([ToolStep("best_effort_write", {})]), registry),
        ToolCoordinator(registry),
    )
    version = AgentVersion(
        uuid4(),
        uuid4(),
        1,
        "best effort",
        (
            ToolBinding(
                version_id,
                "best_effort_write",
                effect_type=ToolEffectType.WRITE,
                allow_no_approval_execution=True,
                idempotency_supported=False,
                reconciliation_mode=ReconciliationMode.BEST_EFFORT,
                side_effect_retry_max_attempts=3,
            ),
        ),
    )
    run = Run(uuid4(), version.id, "write")
    run.queue()
    state = RunState(run.id)
    journal = ExecutionJournal()
    await manager.execute(run=run, run_state=state, agent_version=version, recorder=journal)
    await manager.execute(run=run, run_state=state, agent_version=version, recorder=journal)

    assert journal.external_actions[0].status is ExternalActionStatus.MANUAL_REVIEW
    assert journal.tool_calls[0].status is ToolCallStatus.UNRESOLVED
    assert run.status is RunStatus.WAITING_ACTION_RESOLUTION


@pytest.mark.asyncio
async def test_best_effort_idempotent_not_executed_may_safe_retry() -> None:
    from agentforge.application.errors import ToolAdapterError
    from agentforge.domain.enums import ExternalActionStatus, ReconciliationMode, ToolEffectType

    version_id = uuid4()

    async def ambiguous(_invocation):
        raise ToolAdapterError(
            "timeout",
            error_class="TIMEOUT",
            definite_not_executed=False,
        )

    async def reconcile(_invocation):
        return ReconciliationResult(ReconciliationBusinessResult.NOT_EXECUTED)

    registry = InMemoryToolRegistry(
        [
            SideEffectFunctionTool(
                version_id=version_id,
                name="idempotent_write",
                description="write",
                input_schema={"type": "object"},
                func=ambiguous,
                reconcile_func=reconcile,
            )
        ]
    )
    manager = RunManager(
        NativeRunner(ScriptedFakeModel([ToolStep("idempotent_write", {})]), registry),
        ToolCoordinator(registry),
    )
    version = AgentVersion(
        uuid4(),
        uuid4(),
        1,
        "best effort idempotent",
        (
            ToolBinding(
                version_id,
                "idempotent_write",
                effect_type=ToolEffectType.WRITE,
                allow_no_approval_execution=True,
                idempotency_supported=True,
                reconciliation_mode=ReconciliationMode.BEST_EFFORT,
                side_effect_retry_max_attempts=2,
                side_effect_retry_initial_backoff_seconds=0,
                side_effect_retry_max_backoff_seconds=0,
            ),
        ),
    )
    run = Run(uuid4(), version.id, "write")
    run.queue()
    state = RunState(run.id)
    journal = ExecutionJournal()
    await manager.execute(run=run, run_state=state, agent_version=version, recorder=journal)
    await manager.execute(run=run, run_state=state, agent_version=version, recorder=journal)

    assert journal.external_actions[0].status is ExternalActionStatus.READY
    assert run.status is RunStatus.QUEUED
    assert run.queue_reason is QueueReason.RETRY


@pytest.mark.asyncio
async def test_reconciliation_mode_none_enters_manual_review_without_query() -> None:
    from agentforge.application.errors import ToolAdapterError
    from agentforge.domain.enums import ExternalActionStatus, ReconciliationMode, ToolEffectType

    version_id = uuid4()
    reconcile_calls = 0

    async def ambiguous(_invocation):
        raise ToolAdapterError(
            "timeout",
            error_class="TIMEOUT",
            definite_not_executed=False,
        )

    async def reconcile(_invocation):
        nonlocal reconcile_calls
        reconcile_calls += 1
        return ReconciliationResult(ReconciliationBusinessResult.SUCCEEDED)

    registry = InMemoryToolRegistry(
        [
            SideEffectFunctionTool(
                version_id=version_id,
                name="none_write",
                description="write",
                input_schema={"type": "object"},
                func=ambiguous,
                reconcile_func=reconcile,
            )
        ]
    )
    manager = RunManager(
        NativeRunner(ScriptedFakeModel([ToolStep("none_write", {})]), registry),
        ToolCoordinator(registry),
    )
    version = AgentVersion(
        uuid4(),
        uuid4(),
        1,
        "none",
        (
            ToolBinding(
                version_id,
                "none_write",
                effect_type=ToolEffectType.WRITE,
                allow_no_approval_execution=True,
                reconciliation_mode=ReconciliationMode.NONE,
            ),
        ),
    )
    run = Run(uuid4(), version.id, "write")
    run.queue()
    state = RunState(run.id)
    journal = ExecutionJournal()
    await manager.execute(run=run, run_state=state, agent_version=version, recorder=journal)
    await manager.execute(run=run, run_state=state, agent_version=version, recorder=journal)

    assert reconcile_calls == 0
    assert journal.external_actions[0].status is ExternalActionStatus.MANUAL_REVIEW
    assert run.status is RunStatus.WAITING_ACTION_RESOLUTION
    assert journal.reconciliation_attempts == []


@pytest.mark.asyncio
async def test_reconciliation_transport_failure_uses_separate_bounded_budget() -> None:
    from agentforge.application.errors import ToolAdapterError
    from agentforge.domain.enums import ExternalActionStatus, ReconciliationMode, ToolEffectType

    version_id = uuid4()
    reconcile_calls = 0

    async def ambiguous(_invocation):
        raise ToolAdapterError(
            "timeout",
            error_class="TIMEOUT",
            definite_not_executed=False,
        )

    async def reconcile(_invocation):
        nonlocal reconcile_calls
        reconcile_calls += 1
        raise RuntimeError("provider reconcile 503")

    registry = InMemoryToolRegistry(
        [
            SideEffectFunctionTool(
                version_id=version_id,
                name="reconcile_retry",
                description="write",
                input_schema={"type": "object"},
                func=ambiguous,
                reconcile_func=reconcile,
            )
        ]
    )
    manager = RunManager(
        NativeRunner(ScriptedFakeModel([ToolStep("reconcile_retry", {})]), registry),
        ToolCoordinator(registry),
    )
    version = AgentVersion(
        uuid4(),
        uuid4(),
        1,
        "reconcile retry",
        (
            ToolBinding(
                version_id,
                "reconcile_retry",
                effect_type=ToolEffectType.WRITE,
                allow_no_approval_execution=True,
                reconciliation_mode=ReconciliationMode.AUTHORITATIVE,
                reconciliation_max_attempts=2,
                reconciliation_initial_backoff_seconds=0,
                reconciliation_max_backoff_seconds=0,
            ),
        ),
    )
    run = Run(uuid4(), version.id, "write")
    run.queue()
    state = RunState(run.id)
    journal = ExecutionJournal()

    await manager.execute(run=run, run_state=state, agent_version=version, recorder=journal)
    run.deadline_at = utcnow() - timedelta(seconds=1)

    await manager.execute(run=run, run_state=state, agent_version=version, recorder=journal)
    assert run.status is RunStatus.QUEUED
    assert run.queue_reason is QueueReason.RETRY
    assert reconcile_calls == 1
    assert len(journal.reconciliation_attempts) == 1
    assert journal.reconciliation_attempts[0].status is ReconciliationAttemptStatus.FAILED
    assert journal.external_actions[0].status is ExternalActionStatus.RECONCILING

    await manager.execute(run=run, run_state=state, agent_version=version, recorder=journal)
    assert reconcile_calls == 2
    assert len(journal.reconciliation_attempts) == 2
    assert journal.external_actions[0].status is ExternalActionStatus.MANUAL_REVIEW
    assert run.status is RunStatus.WAITING_ACTION_RESOLUTION
'''
)


# ---------------------------------------------------------------------------
# Integration imports + D3 durable boundary cases.
# ---------------------------------------------------------------------------
replace_once(
    "tests/integration/test_postgres_runtime.py",
    '''from agentforge.domain.enums import (
    EventType,
    QueueReason,
''',
    '''from agentforge.domain.enums import (
    EventType,
    QueueReason,
    ReconciliationAttemptStatus,
    ReconciliationBusinessResult,
''',
)

replace_once(
    "tests/integration/test_postgres_runtime.py",
    '''from agentforge.application.run_manager import RunManager
''',
    '''from agentforge.application.ports import ReconciliationResult
from agentforge.application.run_manager import RunManager
''',
)

replace_once(
    "tests/integration/test_postgres_runtime.py",
    '''    DomainEventRow,
    RunMessageRow,
''',
    '''    DomainEventRow,
    ReconciliationAttemptRow,
    RunMessageRow,
''',
)

append_text(
    "tests/integration/test_postgres_runtime.py",
    "test_reconciliation_started_is_durable_before_query_and_can_finalize_success",
    r'''


@pytest.mark.asyncio
async def test_reconciliation_started_is_durable_before_query_and_can_finalize_success() -> None:
    from agentforge.domain.enums import ExternalActionStatus, ReconciliationMode
    from agentforge.infrastructure.db.models import ExternalActionRow

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
                name="reconcile_commit",
                description="write",
            )
        )
        await session.flush()
        session.add(
            ToolVersionRow(
                id=side_version_id,
                tool_id=side_tool_id,
                version_number=1,
                input_schema={"type": "object"},
                effect_type=ToolEffectType.WRITE,
                implementation_ref="tests:reconcile_commit",
                allow_no_approval_execution=True,
                reconciliation_mode=ReconciliationMode.AUTHORITATIVE,
                reconciliation_max_attempts=2,
                reconciliation_initial_backoff_seconds=0,
                reconciliation_max_backoff_seconds=0,
            )
        )
        await session.flush()
        session.add(
            AgentVersionToolRow(
                agent_version_id=DEMO_AGENT_VERSION_ID,
                tool_version_id=side_version_id,
                tool_alias="reconcile_commit",
            )
        )

    async def ambiguous(_invocation):
        raise ToolAdapterError(
            "effect may have committed",
            error_class="RESPONSE_LOST",
            definite_not_executed=False,
        )

    observed_started_before_query = False

    async def reconcile(_invocation):
        nonlocal observed_started_before_query
        async with sessions() as session:
            attempt = (
                await session.execute(
                    select(ReconciliationAttemptRow)
                    .where(ReconciliationAttemptRow.status == ReconciliationAttemptStatus.STARTED)
                )
            ).scalar_one()
            action = await session.get(ExternalActionRow, attempt.external_action_id)
            observed_started_before_query = (
                action is not None and action.status is ExternalActionStatus.RECONCILING
            )
        return ReconciliationResult(
            ReconciliationBusinessResult.SUCCEEDED,
            {"resource_id": "R-committed"},
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
            SideEffectFunctionTool(
                version_id=side_version_id,
                name="reconcile_commit",
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
        input_text="reconcile commit boundary",
        idempotency_key="integration-d3-started-before-query",
        principal_scope="test-user",
    )
    claimed = await store.claim_next_run(worker_id="d3-start", lease_seconds=30)
    assert claimed is not None
    version = await store.load_agent_version(DEMO_AGENT_VERSION_ID)
    manager1 = RunManager(
        NativeRunner(ScriptedFakeModel([ToolStep("reconcile_commit", {"v": 1})]), registry),
        ToolCoordinator(registry),
    )
    recorder = PostgresExecutionRecorder(
        sessions,
        run_id=created.id,
        generation=claimed.execution_generation,
    )
    await manager1.execute(
        run=claimed,
        run_state=await store.load_run_state(created.id),
        agent_version=version,
        recorder=recorder,
    )

    manager2 = RunManager(
        NativeRunner(ScriptedFakeModel([FinalStep("reconciled")]), registry),
        ToolCoordinator(registry),
    )
    assert (
        await manager2.execute(
            run=claimed,
            run_state=await store.load_run_state(created.id),
            agent_version=version,
            recorder=recorder,
        )
        == "reconciled"
    )
    assert observed_started_before_query is True

    async with sessions() as session:
        attempt = (await session.execute(select(ReconciliationAttemptRow))).scalar_one()
        action = (await session.execute(select(ExternalActionRow))).scalar_one()
        call = await session.get(ToolCallRow, action.tool_call_id)
    assert attempt.status is ReconciliationAttemptStatus.SUCCEEDED
    assert attempt.business_result is ReconciliationBusinessResult.SUCCEEDED
    assert action.status is ExternalActionStatus.SUCCEEDED
    assert call is not None and call.status is ToolCallStatus.SUCCEEDED
    await engine.dispose()


@pytest.mark.asyncio
async def test_reconciliation_retry_survives_deadline_and_exhausts_to_manual_review() -> None:
    from datetime import UTC, datetime, timedelta

    from agentforge.domain.enums import ExternalActionStatus, ReconciliationMode
    from agentforge.infrastructure.db.models import ExternalActionRow, RunRow

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
                name="reconcile_budget",
                description="write",
            )
        )
        await session.flush()
        session.add(
            ToolVersionRow(
                id=side_version_id,
                tool_id=side_tool_id,
                version_number=1,
                input_schema={"type": "object"},
                effect_type=ToolEffectType.WRITE,
                implementation_ref="tests:reconcile_budget",
                allow_no_approval_execution=True,
                reconciliation_mode=ReconciliationMode.AUTHORITATIVE,
                reconciliation_max_attempts=2,
                reconciliation_initial_backoff_seconds=0,
                reconciliation_max_backoff_seconds=0,
            )
        )
        await session.flush()
        session.add(
            AgentVersionToolRow(
                agent_version_id=DEMO_AGENT_VERSION_ID,
                tool_version_id=side_version_id,
                tool_alias="reconcile_budget",
            )
        )

    async def ambiguous(_invocation):
        raise ToolAdapterError(
            "maybe committed",
            error_class="TIMEOUT",
            definite_not_executed=False,
        )

    async def reconcile(_invocation):
        raise RuntimeError("reconciliation transport 503")

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
                version_id=side_version_id,
                name="reconcile_budget",
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
        input_text="reconciliation safety budget",
        idempotency_key="integration-d3-safety-budget",
        principal_scope="test-user",
    )
    claimed1 = await store.claim_next_run(worker_id="d3-budget-1", lease_seconds=30)
    assert claimed1 is not None
    version = await store.load_agent_version(DEMO_AGENT_VERSION_ID)
    manager1 = RunManager(
        NativeRunner(ScriptedFakeModel([ToolStep("reconcile_budget", {})]), registry),
        ToolCoordinator(registry),
    )
    recorder1 = PostgresExecutionRecorder(
        sessions,
        run_id=created.id,
        generation=claimed1.execution_generation,
    )
    await manager1.execute(
        run=claimed1,
        run_state=await store.load_run_state(created.id),
        agent_version=version,
        recorder=recorder1,
    )

    async with sessions() as session, session.begin():
        row = await session.get(RunRow, created.id)
        assert row is not None
        row.deadline_at = datetime.now(UTC) - timedelta(seconds=1)

    await manager1.execute(
        run=claimed1,
        run_state=await store.load_run_state(created.id),
        agent_version=version,
        recorder=recorder1,
    )
    after_first_reconcile = await store.get_run(created.id)
    assert after_first_reconcile is not None
    assert after_first_reconcile.status is RunStatus.QUEUED
    assert after_first_reconcile.queue_reason is QueueReason.RETRY

    claimed2 = await store.claim_next_run(worker_id="d3-budget-2", lease_seconds=30)
    assert claimed2 is not None
    recorder2 = PostgresExecutionRecorder(
        sessions,
        run_id=created.id,
        generation=claimed2.execution_generation,
    )
    manager2 = RunManager(
        NativeRunner(ScriptedFakeModel([FinalStep("must not reason")]), registry),
        ToolCoordinator(registry),
    )
    await manager2.execute(
        run=claimed2,
        run_state=await store.load_run_state(created.id),
        agent_version=version,
        recorder=recorder2,
    )

    durable = await store.get_run(created.id)
    assert durable is not None
    assert durable.status is RunStatus.WAITING_ACTION_RESOLUTION
    async with sessions() as session:
        attempts = (
            (
                await session.execute(
                    select(ReconciliationAttemptRow).order_by(
                        ReconciliationAttemptRow.attempt_number
                    )
                )
            )
            .scalars()
            .all()
        )
        action = (await session.execute(select(ExternalActionRow))).scalar_one()
    assert [item.attempt_number for item in attempts] == [1, 2]
    assert all(item.status is ReconciliationAttemptStatus.FAILED for item in attempts)
    assert action.status is ExternalActionStatus.MANUAL_REVIEW
    await engine.dispose()


@pytest.mark.asyncio
async def test_orphaned_reconciliation_attempt_closes_failed_and_preserves_truth() -> None:
    from datetime import UTC, datetime, timedelta

    from agentforge.domain.enums import ExternalActionStatus, ReconciliationMode
    from agentforge.infrastructure.db.models import ExternalActionRow, RunRow

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
                name="orphan_reconcile",
                description="write",
            )
        )
        await session.flush()
        session.add(
            ToolVersionRow(
                id=side_version_id,
                tool_id=side_tool_id,
                version_number=1,
                input_schema={"type": "object"},
                effect_type=ToolEffectType.WRITE,
                implementation_ref="tests:orphan_reconcile",
                allow_no_approval_execution=True,
                reconciliation_mode=ReconciliationMode.AUTHORITATIVE,
                reconciliation_max_attempts=2,
                reconciliation_initial_backoff_seconds=0,
                reconciliation_max_backoff_seconds=0,
            )
        )
        await session.flush()
        session.add(
            AgentVersionToolRow(
                agent_version_id=DEMO_AGENT_VERSION_ID,
                tool_version_id=side_version_id,
                tool_alias="orphan_reconcile",
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
            SideEffectFunctionTool(
                version_id=side_version_id,
                name="orphan_reconcile",
                description="write",
                input_schema={"type": "object"},
                func=lambda invocation: {"unused": True},
                reconcile_func=lambda invocation: ReconciliationResult(
                    ReconciliationBusinessResult.UNKNOWN
                ),
            ),
        ]
    )
    store = PostgresRuntimeStore(sessions)
    created = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="orphan reconciliation",
        idempotency_key="integration-d3-orphan-reconcile",
        principal_scope="test-user",
    )
    claimed1 = await store.claim_next_run(worker_id="d3-orphan-1", lease_seconds=30)
    assert claimed1 is not None
    recorder1 = PostgresExecutionRecorder(
        sessions,
        run_id=created.id,
        generation=claimed1.execution_generation,
    )
    version = await store.load_agent_version(DEMO_AGENT_VERSION_ID)

    _, invocation = await recorder1.begin_model_invocation(
        run_id=created.id,
        invocation_id=uuid4(),
        expected_generation=claimed1.execution_generation,
    )
    invocation.complete("TOOL_PROPOSAL")
    proposal = ToolProposal.create(
        run_id=created.id,
        model_invocation_id=invocation.id,
        tool_name="orphan_reconcile",
        arguments={"v": 1},
    )
    prepared = ToolCoordinator(registry).prepare_side_effect(
        proposal=proposal,
        agent_version=version,
    )
    await recorder1.record_model_side_effect_prepared(
        invocation,
        proposal,
        prepared.call,
        prepared.snapshot,
        prepared.action,
        expected_generation=claimed1.execution_generation,
    )
    physical = await recorder1.record_side_effect_attempt_started(
        prepared.call,
        prepared.action,
        expected_generation=claimed1.execution_generation,
    )
    await recorder1.record_side_effect_unknown(
        prepared.call,
        prepared.action,
        physical,
        error="ambiguous",
        error_class="TIMEOUT",
        outcome_reason="SIDE_EFFECT_POSSIBLE_EXECUTION",
        expected_generation=claimed1.execution_generation,
    )
    unresolved = await recorder1.load_reconciliation_external_action(created.id)
    assert unresolved is not None
    call, _snapshot, action = unresolved
    recon_attempt = await recorder1.record_reconciliation_started(
        call,
        action,
        claimed1,
        max_attempts=2,
        expected_generation=claimed1.execution_generation,
    )
    assert recon_attempt is not None

    async with sessions() as session, session.begin():
        row = await session.get(RunRow, created.id)
        assert row is not None
        row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)

    claimed2 = await store.claim_next_run(worker_id="d3-orphan-2", lease_seconds=30)
    assert claimed2 is not None
    async with sessions() as session:
        durable_attempt = await session.get(ReconciliationAttemptRow, recon_attempt.id)
        durable_action = (await session.execute(select(ExternalActionRow))).scalar_one()
    assert durable_attempt is not None
    assert durable_attempt.status is ReconciliationAttemptStatus.FAILED
    assert durable_attempt.outcome_reason == "LEASE_LOST"
    assert durable_action.status is ExternalActionStatus.RECONCILING
    assert durable_action.current_attempt_id is None
    await engine.dispose()
'''
)


# ---------------------------------------------------------------------------
# Cross-table serialization: unresolved action truth blocks new model reasoning
# even if a caller bypasses RunManager sequencing.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/application/run_manager.py",
    '''    def _started_tool_attempt(self, tool_call_id: UUID) -> ToolExecutionAttempt:
''',
    '''    def _assert_no_unresolved_actions(self, run_id: UUID) -> None:
        unresolved = [
            action
            for action in self.external_actions
            if action.run_id == run_id
            and action.status
            in {
                ExternalActionStatus.UNKNOWN,
                ExternalActionStatus.RECONCILING,
                ExternalActionStatus.MANUAL_REVIEW,
            }
        ]
        if unresolved:
            raise RuntimeError(
                f"cannot start model reasoning with unresolved ExternalAction {unresolved[0].id}"
            )

    def _started_tool_attempt(self, tool_call_id: UUID) -> ToolExecutionAttempt:
''',
)

replace_once(
    "src/agentforge/application/run_manager.py",
    '''        if self.run_state is None or self.run_state.run_id != run_id:
            raise RuntimeError("journal run state is not seeded")
        self._assert_no_active_tool_calls(run_id)
        self._assert_no_started_tool_attempts(run_id)
''',
    '''        if self.run_state is None or self.run_state.run_id != run_id:
            raise RuntimeError("journal run state is not seeded")
        self._assert_no_active_tool_calls(run_id)
        self._assert_no_unresolved_actions(run_id)
        self._assert_no_started_tool_attempts(run_id)
''',
)

replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''async def _assert_no_started_tool_attempts(session: AsyncSession, run_id: UUID) -> None:
''',
    '''async def _assert_no_unresolved_actions(session: AsyncSession, run_id: UUID) -> None:
    unresolved_id = await session.scalar(
        select(ExternalActionRow.id)
        .where(
            ExternalActionRow.run_id == run_id,
            ExternalActionRow.status.in_(
                [
                    ExternalActionStatus.UNKNOWN,
                    ExternalActionStatus.RECONCILING,
                    ExternalActionStatus.MANUAL_REVIEW,
                ]
            ),
        )
        .limit(1)
    )
    if unresolved_id is not None:
        raise RuntimeError(
            f"cannot start model reasoning with unresolved ExternalAction {unresolved_id}"
        )


async def _assert_no_started_tool_attempts(session: AsyncSession, run_id: UUID) -> None:
''',
)

replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''            run_row = await _lock_owned_run(
                session, run_id=run_id, expected_generation=expected_generation
            )
            await _assert_no_active_tool_calls(session, run_id)
            await _assert_no_started_tool_attempts(session, run_id)
            await _assert_no_started_model_invocations(session, run_id)
''',
    '''            run_row = await _lock_owned_run(
                session, run_id=run_id, expected_generation=expected_generation
            )
            await _assert_no_active_tool_calls(session, run_id)
            await _assert_no_unresolved_actions(session, run_id)
            await _assert_no_started_tool_attempts(session, run_id)
            await _assert_no_started_model_invocations(session, run_id)
''',
)


# ---------------------------------------------------------------------------
# D3 generated-source import completeness. Keep these explicit even though the
# workflow also canonicalizes imports, because undefined symbols must never be
# hidden by formatting.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/application/run_manager.py",
    '''    RunMessage,
    RunState,
    ToolCall,
''',
    '''    RunMessage,
    RunState,
    ToolBinding,
    ToolCall,
''',
)

replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''    EventType,
    ExternalActionStatus,
    ModelInvocationStatus,
''',
    '''    EventType,
    ExternalActionStatus,
    MessageRole,
    ModelInvocationStatus,
''',
)

replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''    RunMessage,
    RunState,
    ToolCall,
''',
    '''    RunMessage,
    RunState,
    ToolBinding,
    ToolCall,
''',
)

replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''from agentforge.infrastructure.db.runtime_store import _allocate_event_sequences
''',
    '''from agentforge.infrastructure.db.runtime_store import _allocate_event_sequences
from agentforge.runtime.tool_coordinator import tool_result_message_content
''',
)


# ---------------------------------------------------------------------------
# Generate Ruff-clean import ordering instead of relying on a later auto-fix.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/application/ports.py",
    '''    ModelInvocation,
    Run,
    RunMessage,
    ReconciliationAttempt,
    RunState,
''',
    '''    ModelInvocation,
    ReconciliationAttempt,
    Run,
    RunMessage,
    RunState,
''',
)

replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''    MessageRole,
    ModelInvocationStatus,
    ReconciliationAttemptStatus,
    ReconciliationBusinessResult,
    ReconciliationMode,
    QueueReason,
    RunStatus,
''',
    '''    MessageRole,
    ModelInvocationStatus,
    QueueReason,
    ReconciliationAttemptStatus,
    ReconciliationBusinessResult,
    ReconciliationMode,
    RunStatus,
''',
)
