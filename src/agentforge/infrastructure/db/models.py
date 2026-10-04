from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from agentforge.domain.enums import (
    QueueReason,
    RunStatus,
    ToolCallStatus,
    ToolEffectType,
)


class Base(DeclarativeBase):
    pass


class AgentRow(Base):
    __tablename__ = "agents"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class ToolDefinitionRow(Base):
    __tablename__ = "tool_definitions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class ToolVersionRow(Base):
    __tablename__ = "tool_versions"
    __table_args__ = (UniqueConstraint("tool_id", "version_number"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tool_id: Mapped[UUID] = mapped_column(
        ForeignKey("tool_definitions.id", ondelete="RESTRICT"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    input_schema: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    effect_type: Mapped[ToolEffectType] = mapped_column(
        Enum(ToolEffectType, name="tool_effect_type"), nullable=False
    )
    implementation_ref: Mapped[str] = mapped_column(String(300), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class AgentVersionRow(Base):
    __tablename__ = "agent_versions"
    __table_args__ = (UniqueConstraint("agent_id", "version_number"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    agent_id: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    instructions: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class AgentVersionToolRow(Base):
    __tablename__ = "agent_version_tools"
    __table_args__ = (UniqueConstraint("agent_version_id", "tool_alias"),)

    agent_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_versions.id", ondelete="RESTRICT"), primary_key=True
    )
    tool_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("tool_versions.id", ondelete="RESTRICT"), primary_key=True
    )
    tool_alias: Mapped[str] = mapped_column(String(200), nullable=False)


class IdempotencyRecordRow(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (UniqueConstraint("principal_scope", "endpoint", "idempotency_key"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    principal_scope: Mapped[str] = mapped_column(String(200), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(200), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class RunRow(Base):
    __tablename__ = "runs"
    __table_args__ = (
        CheckConstraint(
            "status <> 'COMPLETED' OR "
            "(completed_at IS NOT NULL AND final_output IS NOT NULL AND failure_reason IS NULL)",
            name="ck_runs_completed_shape",
        ),
        CheckConstraint(
            "status <> 'FAILED' OR "
            "(completed_at IS NOT NULL AND failure_reason IS NOT NULL AND final_output IS NULL)",
            name="ck_runs_failed_shape",
        ),
        CheckConstraint(
            "status NOT IN ('CREATED', 'QUEUED', 'RUNNING') OR completed_at IS NULL",
            name="ck_runs_nonterminal_has_no_completed_at",
        ),
        Index("ix_runs_runnable", "status", "available_at", "created_at"),
        Index("ix_runs_lease", "status", "lease_expires_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    agent_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_versions.id", ondelete="RESTRICT"), nullable=False
    )
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[RunStatus] = mapped_column(Enum(RunStatus, name="run_status"), nullable=False)
    queue_reason: Mapped[QueueReason | None] = mapped_column(
        Enum(QueueReason, name="queue_reason"), nullable=True
    )
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    final_output: Mapped[str | None] = mapped_column(Text)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    execution_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    owner_worker_id: Mapped[str | None] = mapped_column(String(200))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RunStateRow(Base):
    __tablename__ = "run_states"

    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
    )
    state_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    turn_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tool_call_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class RunCounterRow(Base):
    __tablename__ = "run_counters"

    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
    )
    event_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    message_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class RunMessageRow(Base):
    __tablename__ = "run_messages"
    __table_args__ = (UniqueConstraint("run_id", "sequence"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id", ondelete="RESTRICT"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class ModelInvocationRow(Base):
    __tablename__ = "model_invocations"
    __table_args__ = (
        Index(
            "uq_model_invocations_one_started_per_run",
            "run_id",
            unique=True,
            postgresql_where=text("status = 'STARTED'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id", ondelete="RESTRICT"), nullable=False)
    turn: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    outcome_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ToolProposalRow(Base):
    __tablename__ = "tool_proposals"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id", ondelete="RESTRICT"), nullable=False)
    model_invocation_id: Mapped[UUID] = mapped_column(
        ForeignKey("model_invocations.id", ondelete="RESTRICT"), nullable=False
    )
    tool_name: Mapped[str] = mapped_column(String(200), nullable=False)
    arguments: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)


class ToolCallRow(Base):
    __tablename__ = "tool_calls"
    __table_args__ = (
        CheckConstraint(
            "status = 'DENIED' OR tool_version_id IS NOT NULL",
            name="ck_tool_calls_bound_version_unless_denied",
        ),
        Index(
            "uq_tool_calls_one_active_per_run",
            "run_id",
            unique=True,
            postgresql_where=text("status IN ('READY', 'EXECUTING')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id", ondelete="RESTRICT"), nullable=False)
    proposal_id: Mapped[UUID] = mapped_column(
        ForeignKey("tool_proposals.id", ondelete="RESTRICT"), nullable=False
    )
    tool_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("tool_versions.id", ondelete="RESTRICT"), nullable=True
    )
    tool_name: Mapped[str] = mapped_column(String(200), nullable=False)
    arguments: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    status: Mapped[ToolCallStatus] = mapped_column(
        Enum(ToolCallStatus, name="tool_call_status"), nullable=False
    )
    result: Mapped[object | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)


class DomainEventRow(Base):
    __tablename__ = "domain_events"
    __table_args__ = (UniqueConstraint("run_id", "sequence"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id", ondelete="RESTRICT"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
