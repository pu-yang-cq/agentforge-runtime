from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one anchor, found {count}: {old[:140]!r}")
    file.write_text(text.replace(old, new))


def append_text(path: str, marker: str, block: str) -> None:
    file = Path(path)
    text = file.read_text()
    if marker in text:
        raise SystemExit(f"{path}: marker already present: {marker}")
    file.write_text(text + block)


# ---------------------------------------------------------------------------
# Domain: final manual-resolution outcome + durable resolution entity.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/domain/enums.py",
    '''class ReconciliationBusinessResult(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    NOT_EXECUTED = "NOT_EXECUTED"
    UNKNOWN = "UNKNOWN"


class ModelInvocationStatus(StrEnum):
''',
    '''class ReconciliationBusinessResult(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    NOT_EXECUTED = "NOT_EXECUTED"
    UNKNOWN = "UNKNOWN"


class ActionResolutionOutcome(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    ABORTED = "ABORTED"


class ModelInvocationStatus(StrEnum):
''',
)

replace_once(
    "src/agentforge/domain/enums.py",
    '''    ACTION_MANUAL_REVIEW = "ACTION_MANUAL_REVIEW"
    ACTION_ABORTED = "ACTION_ABORTED"
''',
    '''    ACTION_MANUAL_REVIEW = "ACTION_MANUAL_REVIEW"
    ACTION_RESOLUTION_RECORDED = "ACTION_RESOLUTION_RECORDED"
    ACTION_ABORTED = "ACTION_ABORTED"
''',
)

replace_once(
    "src/agentforge/domain/actions.py",
    '''from dataclasses import dataclass
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from agentforge.domain.enums import ExternalActionStatus, ToolEffectType
''',
    '''from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from agentforge.domain.enums import (
    ActionResolutionOutcome,
    ExternalActionStatus,
    ToolEffectType,
)
''',
)

replace_once(
    "src/agentforge/domain/actions.py",
    '''@dataclass(slots=True)
class ExternalAction:
''',
    '''@dataclass(frozen=True, slots=True)
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
''',
)

replace_once(
    "src/agentforge/domain/actions.py",
    '''    def reconcile_abort_not_executed(self) -> None:
        if self.status is not ExternalActionStatus.RECONCILING:
            raise ValueError("reconciliation abort requires RECONCILING")
        self.status = ExternalActionStatus.ABORTED

    def abort(self) -> None:
''',
    '''    def reconcile_abort_not_executed(self) -> None:
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
''',
)

replace_once(
    "src/agentforge/domain/models.py",
    '''    def succeed(self, result: Any) -> None:
        if self.status is not ToolCallStatus.EXECUTING:
            raise ValueError("tool call can only succeed from EXECUTING")
        self.status = ToolCallStatus.SUCCEEDED
        self.result = result

    def fail(self, error: str) -> None:
''',
    '''    def resolve_manual_succeeded(self, result: Any) -> None:
        if self.status is not ToolCallStatus.UNRESOLVED:
            raise ValueError("manual success requires UNRESOLVED ToolCall")
        self.status = ToolCallStatus.SUCCEEDED
        self.result = result
        self.error = None

    def resolve_manual_failed(self, reason: str) -> None:
        if self.status is not ToolCallStatus.UNRESOLVED:
            raise ValueError("manual failure requires UNRESOLVED ToolCall")
        self.status = ToolCallStatus.FAILED
        self.error = reason

    def resolve_manual_aborted(self, reason: str) -> None:
        if self.status is not ToolCallStatus.UNRESOLVED:
            raise ValueError("manual abort requires UNRESOLVED ToolCall")
        self.status = ToolCallStatus.NOT_EXECUTED
        self.error = reason

    def succeed(self, result: Any) -> None:
        if self.status is not ToolCallStatus.EXECUTING:
            raise ValueError("tool call can only succeed from EXECUTING")
        self.status = ToolCallStatus.SUCCEEDED
        self.result = result

    def fail(self, error: str) -> None:
''',
)

replace_once(
    "src/agentforge/domain/models.py",
    '''    def request_cancel(self) -> None:
        if self.status in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}:
            return
        self.cancel_requested = True
''',
    '''    def resume_after_action_resolution(self) -> None:
        if self.status is not RunStatus.WAITING_ACTION_RESOLUTION:
            raise ValueError(f"cannot resume action resolution from {self.status}")
        if self.cancel_requested:
            raise ValueError("cancel-requested run cannot resume business progression")
        self.status = RunStatus.QUEUED
        self.queue_reason = QueueReason.ACTION_RESOLVED
        self.available_at = None
        self.owner_worker_id = None
        self.lease_expires_at = None

    def fail_after_action_resolution(self, reason: str) -> None:
        if self.status is not RunStatus.WAITING_ACTION_RESOLUTION:
            raise ValueError(f"cannot fail action resolution from {self.status}")
        self.status = RunStatus.FAILED
        self.queue_reason = None
        self.available_at = None
        self.final_output = None
        self.failure_reason = reason
        self.owner_worker_id = None
        self.lease_expires_at = None
        self.completed_at = utcnow()

    def request_cancel(self) -> None:
        if self.status in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}:
            return
        self.cancel_requested = True
''',
)


# ---------------------------------------------------------------------------
# Error and RuntimeStore contract.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/application/errors.py",
    '''class IdempotencyConflictError(RuntimeError):
    pass


class RunExecutionFailedError(RuntimeError):
''',
    '''class IdempotencyConflictError(RuntimeError):
    pass


class ActionResolutionConflictError(RuntimeError):
    """Manual resolution conflicts with durable action/run truth."""


class RunExecutionFailedError(RuntimeError):
''',
)

replace_once(
    "src/agentforge/application/ports.py",
    '''from agentforge.domain.actions import ActionSnapshot, ExternalAction
''',
    '''from agentforge.domain.actions import ActionResolution, ActionSnapshot, ExternalAction
''',
)

replace_once(
    "src/agentforge/application/ports.py",
    '''    async def cancel_run(self, run_id: UUID) -> Run: ...

    async def claim_next_run(self, *, worker_id: str, lease_seconds: int) -> Run | None: ...
''',
    '''    async def cancel_run(self, run_id: UUID) -> Run: ...

    async def resolve_action(
        self,
        *,
        run_id: UUID,
        action_id: UUID,
        outcome: ActionResolutionOutcome,
        evidence: dict[str, Any] | None,
        reason: str | None,
        resolver_identity: str,
    ) -> tuple[Run, ActionResolution]: ...

    async def claim_next_run(self, *, worker_id: str, lease_seconds: int) -> Run | None: ...
''',
)

replace_once(
    "src/agentforge/application/ports.py",
    '''from agentforge.domain.model_contract import ModelRequest, ModelResponse, ModelToolSpec
''',
    '''from agentforge.domain.enums import ActionResolutionOutcome
from agentforge.domain.model_contract import ModelRequest, ModelResponse, ModelToolSpec
''',
)


# ---------------------------------------------------------------------------
# ORM + mapper + migration.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/infrastructure/db/models.py",
    '''from agentforge.domain.enums import (
    ExternalActionStatus,
''',
    '''from agentforge.domain.enums import (
    ActionResolutionOutcome,
    ExternalActionStatus,
''',
)

replace_once(
    "src/agentforge/infrastructure/db/models.py",
    '''class DomainEventRow(Base):
''',
    '''class ActionResolutionRow(Base):
    __tablename__ = "action_resolutions"
    __table_args__ = (
        UniqueConstraint(
            "external_action_id",
            name="uq_action_resolutions_external_action",
        ),
        CheckConstraint(
            "length(btrim(resolver_identity)) > 0",
            name="ck_action_resolutions_nonblank_resolver",
        ),
        Index("ix_action_resolutions_run_id", "run_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="RESTRICT"), nullable=False
    )
    external_action_id: Mapped[UUID] = mapped_column(
        ForeignKey("external_actions.id", ondelete="RESTRICT"), nullable=False
    )
    outcome: Mapped[ActionResolutionOutcome] = mapped_column(
        Enum(ActionResolutionOutcome, name="action_resolution_outcome"),
        nullable=False,
    )
    evidence: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    reason: Mapped[str | None] = mapped_column(Text)
    resolver_identity: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class DomainEventRow(Base):
''',
)

replace_once(
    "src/agentforge/infrastructure/db/mappers.py",
    '''from agentforge.domain.actions import ActionSnapshot, ExternalAction
''',
    '''from agentforge.domain.actions import ActionResolution, ActionSnapshot, ExternalAction
''',
)

replace_once(
    "src/agentforge/infrastructure/db/mappers.py",
    '''    ActionSnapshotRow,
    ExternalActionRow,
''',
    '''    ActionResolutionRow,
    ActionSnapshotRow,
    ExternalActionRow,
''',
)

append_text(
    "src/agentforge/infrastructure/db/mappers.py",
    "def action_resolution_from_row",
    '''


def action_resolution_from_row(row: ActionResolutionRow) -> ActionResolution:
    return ActionResolution(
        id=row.id,
        action_id=row.external_action_id,
        outcome=row.outcome,
        evidence=None if row.evidence is None else dict(row.evidence),
        reason=row.reason,
        resolver_identity=row.resolver_identity,
        created_at=row.created_at,
    )
''',
)

Path("migrations/versions/0015_action_resolution.py").write_text(
    '''"""add durable manual ActionResolution

Revision ID: 0015_action_resolution
Revises: 0014_cancellation_intent
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_action_resolution"
down_revision: str | None = "0014_cancellation_intent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    outcome = postgresql.ENUM(
        "SUCCEEDED",
        "FAILED",
        "ABORTED",
        name="action_resolution_outcome",
    )
    outcome.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "action_resolutions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_action_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "outcome",
            postgresql.ENUM(
                "SUCCEEDED",
                "FAILED",
                "ABORTED",
                name="action_resolution_outcome",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("resolver_identity", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "length(btrim(resolver_identity)) > 0",
            name="ck_action_resolutions_nonblank_resolver",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["external_action_id"],
            ["external_actions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "external_action_id",
            name="uq_action_resolutions_external_action",
        ),
    )
    op.create_index(
        "ix_action_resolutions_run_id",
        "action_resolutions",
        ["run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_action_resolutions_run_id", table_name="action_resolutions")
    op.drop_table("action_resolutions")
    postgresql.ENUM(name="action_resolution_outcome").drop(
        op.get_bind(),
        checkfirst=True,
    )
'''
)


# ---------------------------------------------------------------------------
# RuntimeStore manual-resolution transaction.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/infrastructure/db/runtime_store.py",
    '''from __future__ import annotations

from hashlib import sha256
''',
    '''from __future__ import annotations

import json
from hashlib import sha256
''',
)

replace_once(
    "src/agentforge/infrastructure/db/runtime_store.py",
    '''from agentforge.application.errors import IdempotencyConflictError
''',
    '''from agentforge.application.errors import (
    ActionResolutionConflictError,
    IdempotencyConflictError,
)
''',
)

replace_once(
    "src/agentforge/infrastructure/db/runtime_store.py",
    '''from agentforge.domain.enums import (
    EventType,
''',
    '''from agentforge.domain.actions import ActionResolution
from agentforge.domain.enums import (
    ActionResolutionOutcome,
    EventType,
''',
)

replace_once(
    "src/agentforge/infrastructure/db/runtime_store.py",
    '''from agentforge.infrastructure.db.mappers import (
    agent_version_from_parts,
''',
    '''from agentforge.infrastructure.db.mappers import (
    action_resolution_from_row,
    agent_version_from_parts,
''',
)

replace_once(
    "src/agentforge/infrastructure/db/runtime_store.py",
    '''from agentforge.infrastructure.db.models import (
    AgentVersionRow,
''',
    '''from agentforge.infrastructure.db.models import (
    ActionResolutionRow,
    AgentVersionRow,
''',
)

replace_once(
    "src/agentforge/infrastructure/db/runtime_store.py",
    '''async def _close_orphaned_model_invocations_on_recovery(
''',
    '''async def _allocate_message_sequence(session: AsyncSession, run_id: UUID) -> int:
    result = await session.execute(
        update(RunCounterRow)
        .where(RunCounterRow.run_id == run_id)
        .values(message_sequence=RunCounterRow.message_sequence + 1)
        .returning(RunCounterRow.message_sequence)
    )
    return result.scalar_one()


async def _close_orphaned_model_invocations_on_recovery(
''',
)

replace_once(
    "src/agentforge/infrastructure/db/runtime_store.py",
    '''    async def claim_next_run(self, *, worker_id: str, lease_seconds: int) -> Run | None:
''',
    '''    async def resolve_action(
        self,
        *,
        run_id: UUID,
        action_id: UUID,
        outcome: ActionResolutionOutcome,
        evidence: dict[str, Any] | None,
        reason: str | None,
        resolver_identity: str,
    ) -> tuple[Run, ActionResolution]:
        """Commit one final manual business truth under Run -> Action -> ToolCall locks."""
        if not resolver_identity.strip():
            raise ValueError("resolver_identity cannot be blank")

        async with self._sessions() as session, session.begin():
            run_row = (
                await session.execute(
                    select(RunRow).where(RunRow.id == run_id).with_for_update()
                )
            ).scalar_one_or_none()
            if run_row is None:
                raise KeyError(f"run not found: {run_id}")

            action_row = (
                await session.execute(
                    select(ExternalActionRow)
                    .where(
                        ExternalActionRow.id == action_id,
                        ExternalActionRow.run_id == run_id,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if action_row is None:
                raise KeyError(f"external action not found: {action_id}")

            existing = (
                await session.execute(
                    select(ActionResolutionRow).where(
                        ActionResolutionRow.external_action_id == action_id
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                same_request = (
                    existing.outcome is outcome
                    and (
                        (existing.evidence is None and evidence is None)
                        or (
                            existing.evidence is not None
                            and evidence is not None
                            and dict(existing.evidence) == evidence
                        )
                    )
                    and existing.reason == reason
                    and existing.resolver_identity == resolver_identity
                )
                if not same_request:
                    raise ActionResolutionConflictError(
                        "external action already has a contradictory final resolution"
                    )
                await session.refresh(run_row)
                return run_from_row(run_row), action_resolution_from_row(existing)

            if action_row.status is not ExternalActionStatus.MANUAL_REVIEW:
                raise ActionResolutionConflictError(
                    "only MANUAL_REVIEW ExternalAction may be manually resolved"
                )
            if run_row.status not in {
                RunStatus.WAITING_ACTION_RESOLUTION,
                RunStatus.CANCELLED,
            }:
                raise ActionResolutionConflictError(
                    "MANUAL_REVIEW action is inconsistent with Run terminal/waiting state"
                )
            if (
                run_row.status is RunStatus.WAITING_ACTION_RESOLUTION
                and run_row.cancel_requested
            ):
                raise ActionResolutionConflictError(
                    "cancel-requested manual review must stabilize Run to CANCELLED first"
                )
            if run_row.status is RunStatus.CANCELLED and not run_row.cancel_requested:
                raise ActionResolutionConflictError(
                    "CANCELLED manual-review Run lacks durable cancel_requested"
                )

            call_row = (
                await session.execute(
                    select(ToolCallRow)
                    .where(
                        ToolCallRow.id == action_row.tool_call_id,
                        ToolCallRow.run_id == run_id,
                    )
                    .with_for_update()
                )
            ).scalar_one()
            if call_row.status is not ToolCallStatus.UNRESOLVED:
                raise ActionResolutionConflictError(
                    "MANUAL_REVIEW action does not project to UNRESOLVED ToolCall"
                )

            db_now = await session.scalar(select(func.clock_timestamp()))
            if db_now is None:
                raise RuntimeError("database clock_timestamp() returned no value")

            resolution_row = ActionResolutionRow(
                id=uuid4(),
                run_id=run_id,
                external_action_id=action_id,
                outcome=outcome,
                evidence=evidence,
                reason=reason,
                resolver_identity=resolver_identity.strip(),
            )
            session.add(resolution_row)
            await session.flush()

            if outcome is ActionResolutionOutcome.SUCCEEDED:
                action_row.status = ExternalActionStatus.SUCCEEDED
                call_row.status = ToolCallStatus.SUCCEEDED
                call_row.error = None
                call_row.result = {
                    "manual_resolution": ActionResolutionOutcome.SUCCEEDED.value,
                    "evidence": evidence,
                }
            elif outcome is ActionResolutionOutcome.FAILED:
                action_row.status = ExternalActionStatus.FAILED
                call_row.status = ToolCallStatus.FAILED
                call_row.error = reason or "manual resolution confirmed action failure"
            elif outcome is ActionResolutionOutcome.ABORTED:
                action_row.status = ExternalActionStatus.ABORTED
                call_row.status = ToolCallStatus.NOT_EXECUTED
                call_row.error = reason or "manual resolution confirmed action did not execute"
            else:
                raise ValueError(f"unsupported ActionResolution outcome: {outcome}")
            action_row.updated_at = db_now

            events: list[tuple[EventType, dict[str, object]]] = [
                (
                    EventType.ACTION_RESOLUTION_RECORDED,
                    {
                        "resolution_id": str(resolution_row.id),
                        "external_action_id": str(action_id),
                        "operation_id": str(action_row.operation_id),
                        "outcome": outcome.value,
                        "resolver_identity": resolver_identity.strip(),
                    },
                )
            ]

            if run_row.status is RunStatus.CANCELLED:
                # Post-terminal resolution updates facts only. Cancellation remains final.
                pass
            elif outcome is ActionResolutionOutcome.SUCCEEDED:
                if db_now < run_row.deadline_at:
                    message_seq = await _allocate_message_sequence(session, run_id)
                    content = json.dumps(
                        call_row.result,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    session.add(
                        RunMessageRow(
                            id=uuid4(),
                            run_id=run_id,
                            sequence=message_seq,
                            role=MessageRole.TOOL.value,
                            content=content,
                            source_id=call_row.id,
                        )
                    )
                    run_row.status = RunStatus.QUEUED
                    run_row.queue_reason = QueueReason.ACTION_RESOLVED
                    run_row.available_at = None
                    run_row.failure_reason = None
                    run_row.final_output = None
                    run_row.owner_worker_id = None
                    run_row.lease_expires_at = None
                    run_row.completed_at = None
                    events.append(
                        (
                            EventType.RUN_QUEUED,
                            {"queue_reason": QueueReason.ACTION_RESOLVED.value},
                        )
                    )
                else:
                    run_row.status = RunStatus.FAILED
                    run_row.queue_reason = None
                    run_row.available_at = None
                    run_row.failure_reason = (
                        "DEADLINE_EXCEEDED_AFTER_ACTION_RESOLUTION: "
                        "manual success arrived after Run deadline"
                    )
                    run_row.final_output = None
                    run_row.owner_worker_id = None
                    run_row.lease_expires_at = None
                    run_row.completed_at = db_now
                    events.append(
                        (
                            EventType.RUN_FAILED,
                            {"reason": run_row.failure_reason},
                        )
                    )
            else:
                run_row.status = RunStatus.FAILED
                run_row.queue_reason = None
                run_row.available_at = None
                run_row.failure_reason = (
                    "MANUAL_ACTION_RESOLUTION_FAILED"
                    if outcome is ActionResolutionOutcome.FAILED
                    else "MANUAL_ACTION_RESOLUTION_ABORTED"
                )
                run_row.final_output = None
                run_row.owner_worker_id = None
                run_row.lease_expires_at = None
                run_row.completed_at = db_now
                events.append(
                    (
                        EventType.RUN_FAILED,
                        {"reason": run_row.failure_reason},
                    )
                )

            seqs = list(await _allocate_event_sequences(session, run_id, len(events)))
            for seq, (event_type, payload) in zip(seqs, events, strict=True):
                session.add(
                    DomainEventRow(
                        id=uuid4(),
                        run_id=run_id,
                        sequence=seq,
                        event_type=event_type.value,
                        payload=payload,
                    )
                )

            await session.flush()
            await session.refresh(run_row)
            await session.refresh(resolution_row)
            return run_from_row(run_row), action_resolution_from_row(resolution_row)

    async def claim_next_run(self, *, worker_id: str, lease_seconds: int) -> Run | None:
''',
)


# ---------------------------------------------------------------------------
# API surface.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/api/schemas.py",
    '''from agentforge.domain.enums import RunStatus
''',
    '''from agentforge.domain.enums import ActionResolutionOutcome, RunStatus
''',
)

append_text(
    "src/agentforge/api/schemas.py",
    "class ActionResolutionCreate",
    '''


class ActionResolutionCreate(BaseModel):
    outcome: ActionResolutionOutcome
    evidence: dict[str, object] | None = None
    reason: str | None = Field(default=None, max_length=4_000)
    resolver_identity: str = Field(
        default="wave1:anonymous",
        min_length=1,
        max_length=200,
    )


class ActionResolutionView(BaseModel):
    id: UUID
    action_id: UUID
    outcome: ActionResolutionOutcome
    evidence: dict[str, object] | None = None
    reason: str | None = None
    resolver_identity: str
    created_at: datetime


class ActionResolutionResultView(BaseModel):
    run: RunView
    resolution: ActionResolutionView
''',
)

replace_once(
    "src/agentforge/api/app.py",
    '''from agentforge.api.schemas import RunCreate, RunView
from agentforge.application.errors import IdempotencyConflictError
''',
    '''from agentforge.api.schemas import (
    ActionResolutionCreate,
    ActionResolutionResultView,
    ActionResolutionView,
    RunCreate,
    RunView,
)
from agentforge.application.errors import (
    ActionResolutionConflictError,
    IdempotencyConflictError,
)
''',
)

replace_once(
    "src/agentforge/api/app.py",
    '''from agentforge.domain.models import Run
''',
    '''from agentforge.domain.actions import ActionResolution
from agentforge.domain.models import Run
''',
)

replace_once(
    "src/agentforge/api/app.py",
    '''def create_app(store: RuntimeStore) -> FastAPI:
''',
    '''def _resolution_view(resolution: ActionResolution) -> ActionResolutionView:
    return ActionResolutionView(
        id=resolution.id,
        action_id=resolution.action_id,
        outcome=resolution.outcome,
        evidence=resolution.evidence,
        reason=resolution.reason,
        resolver_identity=resolution.resolver_identity,
        created_at=resolution.created_at,
    )


def create_app(store: RuntimeStore) -> FastAPI:
''',
)

replace_once(
    "src/agentforge/api/app.py",
    '''    @app.get("/v1/runs/{run_id}", response_model=RunView)
''',
    '''    @app.post(
        "/v1/runs/{run_id}/actions/{action_id}/resolve",
        response_model=ActionResolutionResultView,
    )
    async def resolve_action(
        run_id: UUID,
        action_id: UUID,
        request: ActionResolutionCreate,
    ) -> ActionResolutionResultView:
        try:
            run, resolution = await store.resolve_action(
                run_id=run_id,
                action_id=action_id,
                outcome=request.outcome,
                evidence=request.evidence,
                reason=request.reason,
                resolver_identity=request.resolver_identity,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run or action not found") from exc
        except ActionResolutionConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return ActionResolutionResultView(
            run=_run_view(run),
            resolution=_resolution_view(resolution),
        )

    @app.get("/v1/runs/{run_id}", response_model=RunView)
''',
)


# ---------------------------------------------------------------------------
# API contract fake.
# ---------------------------------------------------------------------------
replace_once(
    "tests/unit/test_api_contract.py",
    '''from agentforge.domain.enums import RunStatus
from agentforge.domain.models import Run
''',
    '''from agentforge.domain.actions import ActionResolution
from agentforge.domain.enums import ActionResolutionOutcome, RunStatus
from agentforge.domain.models import Run
''',
)

replace_once(
    "tests/unit/test_api_contract.py",
    '''    async def claim_next_run(self, *, worker_id: str, lease_seconds: int):
''',
    '''    async def resolve_action(
        self,
        *,
        run_id,
        action_id,
        outcome,
        evidence,
        reason,
        resolver_identity,
    ):
        run = self.runs.get(run_id)
        if run is None:
            raise KeyError(run_id)
        resolution = ActionResolution(
            id=uuid4(),
            action_id=action_id,
            outcome=outcome,
            evidence=evidence,
            reason=reason,
            resolver_identity=resolver_identity,
        )
        return run, resolution

    async def claim_next_run(self, *, worker_id: str, lease_seconds: int):
''',
)

append_text(
    "tests/unit/test_api_contract.py",
    "test_action_resolution_api_contract",
    r'''


def test_action_resolution_api_contract() -> None:
    store = FakeRuntimeStore()
    client = TestClient(create_app(store))
    created = client.post(
        "/v1/runs",
        json={"agent_version_id": str(store.agent_version_id), "input": "resolve me"},
        headers={"Idempotency-Key": "run-resolve-0001"},
    ).json()
    action_id = uuid4()

    response = client.post(
        f"/v1/runs/{created['id']}/actions/{action_id}/resolve",
        json={
            "outcome": ActionResolutionOutcome.SUCCEEDED.value,
            "evidence": {"ticket": "T-1"},
            "reason": "operator verified provider state",
            "resolver_identity": "operator:test",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["run"]["id"] == created["id"]
    assert body["resolution"]["action_id"] == str(action_id)
    assert body["resolution"]["outcome"] == "SUCCEEDED"
    assert body["resolution"]["resolver_identity"] == "operator:test"
'''
)


# ---------------------------------------------------------------------------
# PostgreSQL integration coverage.
# ---------------------------------------------------------------------------
replace_once(
    "tests/integration/test_postgres_runtime.py",
    '''    BusinessProgressionBlockedError,
    IdempotencyConflictError,
''',
    '''    ActionResolutionConflictError,
    BusinessProgressionBlockedError,
    IdempotencyConflictError,
''',
)

replace_once(
    "tests/integration/test_postgres_runtime.py",
    '''from agentforge.domain.enums import (
    EventType,
''',
    '''from agentforge.domain.enums import (
    ActionResolutionOutcome,
    EventType,
    ExternalActionStatus,
''',
)

replace_once(
    "tests/integration/test_postgres_runtime.py",
    '''from agentforge.infrastructure.db.models import (
    AgentRow,
''',
    '''from agentforge.infrastructure.db.models import (
    ActionResolutionRow,
    AgentRow,
''',
)

replace_once(
    "tests/integration/test_postgres_runtime.py",
    '''    DomainEventRow,
    ReconciliationAttemptRow,
''',
    '''    DomainEventRow,
    ExternalActionRow,
    ReconciliationAttemptRow,
''',
)

append_text(
    "tests/integration/test_postgres_runtime.py",
    "_build_manual_review_run_for_e2",
    r'''


async def _build_manual_review_run_for_e2(sessions, *, key: str, tool_name: str):
    from agentforge.domain.enums import ReconciliationMode

    side_tool_id = uuid4()
    side_version_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(
            ToolDefinitionRow(
                id=side_tool_id,
                name=tool_name,
                description="manual-review side effect",
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
                implementation_ref=f"tests:{tool_name}",
                allow_no_approval_execution=True,
                reconciliation_mode=ReconciliationMode.NONE,
            )
        )
        await session.flush()
        session.add(
            AgentVersionToolRow(
                agent_version_id=DEMO_AGENT_VERSION_ID,
                tool_version_id=side_version_id,
                tool_alias=tool_name,
            )
        )

    async def ambiguous(_invocation):
        raise ToolAdapterError(
            "provider truth unavailable",
            error_class="RESPONSE_LOST",
            definite_not_executed=False,
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
                name=tool_name,
                description="write",
                input_schema={"type": "object"},
                func=ambiguous,
            ),
        ]
    )
    store = PostgresRuntimeStore(sessions)
    created = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="manual review",
        idempotency_key=key,
        principal_scope="test-user",
    )
    claimed = await store.claim_next_run(worker_id=f"{tool_name}-worker", lease_seconds=30)
    assert claimed is not None
    version = await store.load_agent_version(DEMO_AGENT_VERSION_ID)
    recorder = PostgresExecutionRecorder(
        sessions,
        run_id=created.id,
        generation=claimed.execution_generation,
    )
    manager = RunManager(
        NativeRunner(ScriptedFakeModel([ToolStep(tool_name, {"v": 1})]), registry),
        ToolCoordinator(registry),
    )
    assert (
        await manager.execute(
            run=claimed,
            run_state=await store.load_run_state(created.id),
            agent_version=version,
            recorder=recorder,
        )
        is None
    )
    # Second pass observes UNKNOWN and mode NONE, producing MANUAL_REVIEW.
    assert (
        await manager.execute(
            run=claimed,
            run_state=await store.load_run_state(created.id),
            agent_version=version,
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
    return store, created.id, action.id, registry


@pytest.mark.asyncio
async def test_manual_success_resolution_requeues_action_resolved_and_continues() -> None:
    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)
    store, run_id, action_id, registry = await _build_manual_review_run_for_e2(
        sessions,
        key="integration-e2-success",
        tool_name="manual_success",
    )

    run, resolution = await store.resolve_action(
        run_id=run_id,
        action_id=action_id,
        outcome=ActionResolutionOutcome.SUCCEEDED,
        evidence={"ticket": "T-42"},
        reason="operator verified success",
        resolver_identity="operator:e2",
    )

    assert run.status is RunStatus.QUEUED
    assert run.queue_reason is QueueReason.ACTION_RESOLVED
    assert run.cancel_requested is False
    assert resolution.action_id == action_id
    assert resolution.outcome is ActionResolutionOutcome.SUCCEEDED

    async with sessions() as session:
        action = await session.get(ExternalActionRow, action_id)
        call = await session.get(ToolCallRow, action.tool_call_id if action else uuid4())
        resolution_row = (
            await session.execute(
                select(ActionResolutionRow).where(
                    ActionResolutionRow.external_action_id == action_id
                )
            )
        ).scalar_one()
        tool_messages = (
            (
                await session.execute(
                    select(RunMessageRow).where(
                        RunMessageRow.run_id == run_id,
                        RunMessageRow.role == "TOOL",
                    )
                )
            )
            .scalars()
            .all()
        )
    assert action is not None and action.status is ExternalActionStatus.SUCCEEDED
    assert call is not None and call.status is ToolCallStatus.SUCCEEDED
    assert resolution_row.outcome is ActionResolutionOutcome.SUCCEEDED
    assert len(tool_messages) == 1
    assert '"manual_resolution":"SUCCEEDED"' in tool_messages[0].content

    claimed = await store.claim_next_run(worker_id="e2-continuation", lease_seconds=30)
    assert claimed is not None and claimed.id == run_id
    manager = RunManager(
        NativeRunner(ScriptedFakeModel([FinalStep("manual resolution continued")]), registry),
        ToolCoordinator(registry),
    )
    recorder = PostgresExecutionRecorder(
        sessions,
        run_id=run_id,
        generation=claimed.execution_generation,
    )
    assert (
        await manager.execute(
            run=claimed,
            run_state=await store.load_run_state(run_id),
            agent_version=await store.load_agent_version(DEMO_AGENT_VERSION_ID),
            recorder=recorder,
        )
        == "manual resolution continued"
    )
    await engine.dispose()


@pytest.mark.asyncio
async def test_manual_success_after_deadline_finalizes_action_but_fails_run() -> None:
    from datetime import UTC, datetime, timedelta
    from agentforge.infrastructure.db.models import RunRow

    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)
    store, run_id, action_id, _ = await _build_manual_review_run_for_e2(
        sessions,
        key="integration-e2-deadline",
        tool_name="manual_deadline",
    )

    async with sessions() as session, session.begin():
        row = await session.get(RunRow, run_id)
        assert row is not None
        row.deadline_at = datetime.now(UTC) - timedelta(seconds=1)

    run, _ = await store.resolve_action(
        run_id=run_id,
        action_id=action_id,
        outcome=ActionResolutionOutcome.SUCCEEDED,
        evidence={"provider": "success"},
        reason="verified after deadline",
        resolver_identity="operator:e2",
    )
    assert run.status is RunStatus.FAILED
    assert run.failure_reason is not None
    assert run.failure_reason.startswith("DEADLINE_EXCEEDED_AFTER_ACTION_RESOLUTION")
    async with sessions() as session:
        action = await session.get(ExternalActionRow, action_id)
        assert action is not None
        call = await session.get(ToolCallRow, action.tool_call_id)
    assert action.status is ExternalActionStatus.SUCCEEDED
    assert call is not None and call.status is ToolCallStatus.SUCCEEDED
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("outcome", "expected_action", "expected_call", "failure_reason"),
    [
        (
            ActionResolutionOutcome.FAILED,
            ExternalActionStatus.FAILED,
            ToolCallStatus.FAILED,
            "MANUAL_ACTION_RESOLUTION_FAILED",
        ),
        (
            ActionResolutionOutcome.ABORTED,
            ExternalActionStatus.ABORTED,
            ToolCallStatus.NOT_EXECUTED,
            "MANUAL_ACTION_RESOLUTION_ABORTED",
        ),
    ],
)
async def test_manual_failed_or_aborted_resolution_terminalizes_failed_run(
    outcome,
    expected_action,
    expected_call,
    failure_reason,
) -> None:
    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)
    store, run_id, action_id, _ = await _build_manual_review_run_for_e2(
        sessions,
        key=f"integration-e2-{outcome.value.lower()}",
        tool_name=f"manual_{outcome.value.lower()}",
    )

    run, _ = await store.resolve_action(
        run_id=run_id,
        action_id=action_id,
        outcome=outcome,
        evidence={"operator": "checked"},
        reason="manual final outcome",
        resolver_identity="operator:e2",
    )
    assert run.status is RunStatus.FAILED
    assert run.failure_reason == failure_reason
    async with sessions() as session:
        action = await session.get(ExternalActionRow, action_id)
        assert action is not None
        call = await session.get(ToolCallRow, action.tool_call_id)
    assert action.status is expected_action
    assert call is not None and call.status is expected_call
    await engine.dispose()


@pytest.mark.asyncio
async def test_cancelled_manual_review_resolution_never_reopens_run_and_is_idempotent() -> None:
    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)
    store, run_id, action_id, _ = await _build_manual_review_run_for_e2(
        sessions,
        key="integration-e2-cancelled",
        tool_name="manual_cancelled",
    )

    cancelled = await store.cancel_run(run_id)
    assert cancelled.status is RunStatus.CANCELLED
    assert cancelled.cancel_requested is True

    kwargs = dict(
        run_id=run_id,
        action_id=action_id,
        outcome=ActionResolutionOutcome.SUCCEEDED,
        evidence={"ticket": "T-cancelled"},
        reason="verified after cancellation",
        resolver_identity="operator:e2",
    )
    run, first = await store.resolve_action(**kwargs)
    replay_run, replay = await store.resolve_action(**kwargs)
    assert run.status is RunStatus.CANCELLED
    assert replay_run.status is RunStatus.CANCELLED
    assert first.id == replay.id

    with pytest.raises(ActionResolutionConflictError, match="contradictory"):
        await store.resolve_action(
            run_id=run_id,
            action_id=action_id,
            outcome=ActionResolutionOutcome.FAILED,
            evidence={"ticket": "T-cancelled"},
            reason="contradictory operator result",
            resolver_identity="operator:e2",
        )

    async with sessions() as session:
        action = await session.get(ExternalActionRow, action_id)
        assert action is not None
        call = await session.get(ToolCallRow, action.tool_call_id)
        resolution_count = await session.scalar(
            select(func.count())
            .select_from(ActionResolutionRow)
            .where(ActionResolutionRow.external_action_id == action_id)
        )
    assert action.status is ExternalActionStatus.SUCCEEDED
    assert call is not None and call.status is ToolCallStatus.SUCCEEDED
    assert resolution_count == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_manual_resolution_rejects_non_manual_review_action() -> None:
    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)
    store, run_id, action_id, _ = await _build_manual_review_run_for_e2(
        sessions,
        key="integration-e2-state-guard",
        tool_name="manual_state_guard",
    )

    # Resolve once, then a distinct second request must be rejected permanently.
    await store.resolve_action(
        run_id=run_id,
        action_id=action_id,
        outcome=ActionResolutionOutcome.ABORTED,
        evidence=None,
        reason="first final resolution",
        resolver_identity="operator:e2",
    )
    with pytest.raises(ActionResolutionConflictError):
        await store.resolve_action(
            run_id=run_id,
            action_id=action_id,
            outcome=ActionResolutionOutcome.SUCCEEDED,
            evidence=None,
            reason="cannot overwrite",
            resolver_identity="operator:e2",
        )
    await engine.dispose()
'''
)
