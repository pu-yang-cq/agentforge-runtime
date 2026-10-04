from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from .enums import (
    EventType,
    MessageRole,
    ModelInvocationStatus,
    QueueReason,
    RunStatus,
    ToolCallStatus,
    ToolExecutionAttemptStatus,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class Agent:
    id: UUID
    name: str
    description: str = ""


@dataclass(frozen=True, slots=True)
class ToolBinding:
    tool_version_id: UUID
    name: str


@dataclass(frozen=True, slots=True)
class AgentVersion:
    id: UUID
    agent_id: UUID
    version_number: int
    instructions: str
    tool_bindings: tuple[ToolBinding, ...] = ()


@dataclass(slots=True)
class Run:
    id: UUID
    agent_version_id: UUID
    input_text: str
    status: RunStatus = RunStatus.CREATED
    queue_reason: QueueReason | None = None
    final_output: str | None = None
    failure_reason: str | None = None
    execution_generation: int = 0
    owner_worker_id: str | None = None
    lease_expires_at: datetime | None = None
    available_at: datetime | None = None
    created_at: datetime = field(default_factory=utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def queue(self, reason: QueueReason = QueueReason.INITIAL) -> None:
        if self.status is not RunStatus.CREATED:
            raise ValueError(f"cannot queue run from {self.status}")
        self.status = RunStatus.QUEUED
        self.queue_reason = reason

    def start(self) -> None:
        if self.status is not RunStatus.QUEUED:
            raise ValueError(f"cannot start run from {self.status}")
        self.status = RunStatus.RUNNING
        self.started_at = utcnow()

    def complete(self, output: str) -> None:
        if self.status is not RunStatus.RUNNING:
            raise ValueError(f"cannot complete run from {self.status}")
        self.status = RunStatus.COMPLETED
        self.final_output = output
        self.completed_at = utcnow()

    def fail(self, reason: str) -> None:
        if self.status not in {RunStatus.QUEUED, RunStatus.RUNNING}:
            raise ValueError(f"cannot fail run from {self.status}")
        self.status = RunStatus.FAILED
        self.failure_reason = reason
        self.completed_at = utcnow()


@dataclass(slots=True)
class RunState:
    run_id: UUID
    state_version: int = 0
    turn_count: int = 0
    tool_call_count: int = 0


@dataclass(frozen=True, slots=True)
class RunMessage:
    run_id: UUID
    sequence: int
    role: MessageRole
    content: str
    source_id: UUID | None = None
    created_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class ModelInvocation:
    id: UUID
    run_id: UUID
    turn: int
    status: ModelInvocationStatus = ModelInvocationStatus.STARTED
    outcome_type: str | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=utcnow)
    completed_at: datetime | None = None

    def complete(self, outcome_type: str) -> None:
        if self.status is not ModelInvocationStatus.STARTED:
            raise ValueError("model invocation can only complete from STARTED")
        self.status = ModelInvocationStatus.COMPLETED
        self.outcome_type = outcome_type
        self.completed_at = utcnow()

    def fail(self, error: str) -> None:
        if self.status is not ModelInvocationStatus.STARTED:
            raise ValueError("model invocation can only fail from STARTED")
        self.status = ModelInvocationStatus.FAILED
        self.error = error
        self.completed_at = utcnow()


@dataclass(frozen=True, slots=True)
class ToolProposal:
    id: UUID
    run_id: UUID
    model_invocation_id: UUID
    tool_name: str
    arguments: dict[str, Any]

    @classmethod
    def create(
        cls,
        *,
        run_id: UUID,
        model_invocation_id: UUID,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> ToolProposal:
        return cls(uuid4(), run_id, model_invocation_id, tool_name, arguments)


@dataclass(slots=True)
class ToolCall:
    id: UUID
    run_id: UUID
    proposal_id: UUID
    tool_version_id: UUID | None
    tool_name: str
    arguments: dict[str, Any]
    status: ToolCallStatus = ToolCallStatus.CREATED
    result: Any = None
    error: str | None = None

    @classmethod
    def from_proposal(cls, proposal: ToolProposal, *, tool_version_id: UUID) -> ToolCall:
        return cls(
            uuid4(),
            proposal.run_id,
            proposal.id,
            tool_version_id,
            proposal.tool_name,
            proposal.arguments,
        )

    @classmethod
    def denied_from_proposal(cls, proposal: ToolProposal, *, error: str) -> ToolCall:
        return cls(
            uuid4(),
            proposal.run_id,
            proposal.id,
            None,
            proposal.tool_name,
            proposal.arguments,
            status=ToolCallStatus.DENIED,
            error=error,
        )

    def ready(self) -> None:
        if self.status is not ToolCallStatus.CREATED:
            raise ValueError("tool call can only become READY from CREATED")
        self.status = ToolCallStatus.READY

    def retry_ready(self, reason: str) -> None:
        if self.status is not ToolCallStatus.EXECUTING:
            raise ValueError("tool call can only return to READY from EXECUTING")
        self.status = ToolCallStatus.READY
        self.error = reason

    def start(self) -> None:
        if self.status is not ToolCallStatus.READY:
            raise ValueError("tool call can only execute from READY")
        self.status = ToolCallStatus.EXECUTING
        self.error = None

    def succeed(self, result: Any) -> None:
        if self.status is not ToolCallStatus.EXECUTING:
            raise ValueError("tool call can only succeed from EXECUTING")
        self.status = ToolCallStatus.SUCCEEDED
        self.result = result

    def fail(self, error: str) -> None:
        if self.status is not ToolCallStatus.EXECUTING:
            raise ValueError("tool call can only fail from EXECUTING")
        self.status = ToolCallStatus.FAILED
        self.error = error


@dataclass(slots=True)
class ToolExecutionAttempt:
    id: UUID
    run_id: UUID
    tool_call_id: UUID
    attempt_number: int
    execution_generation: int
    status: ToolExecutionAttemptStatus = ToolExecutionAttemptStatus.STARTED
    result: Any = None
    error: str | None = None
    outcome_reason: str | None = None
    definite_not_executed: bool | None = None
    started_at: datetime = field(default_factory=utcnow)
    finished_at: datetime | None = None

    def succeed(self, result: Any) -> None:
        if self.status is not ToolExecutionAttemptStatus.STARTED:
            raise ValueError("tool attempt can only succeed from STARTED")
        self.status = ToolExecutionAttemptStatus.SUCCEEDED
        self.result = result
        self.finished_at = utcnow()

    def fail(
        self,
        error: str,
        *,
        definite_not_executed: bool | None = None,
        outcome_reason: str | None = None,
    ) -> None:
        if self.status is not ToolExecutionAttemptStatus.STARTED:
            raise ValueError("tool attempt can only fail from STARTED")
        self.status = ToolExecutionAttemptStatus.FAILED
        self.error = error
        self.definite_not_executed = definite_not_executed
        self.outcome_reason = outcome_reason
        self.finished_at = utcnow()

    def mark_unknown(self, reason: str) -> None:
        if self.status is not ToolExecutionAttemptStatus.STARTED:
            raise ValueError("tool attempt can only become UNKNOWN from STARTED")
        self.status = ToolExecutionAttemptStatus.UNKNOWN
        self.outcome_reason = reason
        self.finished_at = utcnow()


@dataclass(frozen=True, slots=True)
class DomainEvent:
    run_id: UUID
    sequence: int
    type: EventType
    payload: dict[str, Any]
    occurred_at: datetime = field(default_factory=utcnow)
