from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from .enums import (
    EventType,
    MessageRole,
    ModelInvocationStatus,
    QueueReason,
    ReconciliationMode,
    RunStatus,
    ToolCallStatus,
    ToolEffectType,
    ToolExecutionAttemptStatus,
)

DEFAULT_MAX_MODEL_INVOCATIONS = 16
DEFAULT_MAX_TOOL_ATTEMPTS = 32
DEFAULT_RUN_DEADLINE_SECONDS = 15 * 60


def utcnow() -> datetime:
    return datetime.now(UTC)


def default_deadline_at() -> datetime:
    return utcnow() + timedelta(seconds=DEFAULT_RUN_DEADLINE_SECONDS)


@dataclass(frozen=True, slots=True)
class Agent:
    id: UUID
    name: str
    description: str = ""


@dataclass(frozen=True, slots=True)
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
    max_model_invocations: int = DEFAULT_MAX_MODEL_INVOCATIONS
    max_tool_attempts: int = DEFAULT_MAX_TOOL_ATTEMPTS
    deadline_at: datetime = field(default_factory=default_deadline_at)

    def queue(self, reason: QueueReason = QueueReason.INITIAL) -> None:
        if self.status is not RunStatus.CREATED:
            raise ValueError(f"cannot queue run from {self.status}")
        self.status = RunStatus.QUEUED
        self.queue_reason = reason

    def start(self) -> None:
        if self.status is not RunStatus.QUEUED:
            raise ValueError(f"cannot start run from {self.status}")
        self.status = RunStatus.RUNNING
        self.queue_reason = None
        self.available_at = None
        if self.started_at is None:
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

    def yield_to_queue(self, reason: QueueReason = QueueReason.YIELD) -> None:
        if self.status is not RunStatus.RUNNING:
            raise ValueError(f"cannot yield run from {self.status}")
        self.status = RunStatus.QUEUED
        self.queue_reason = reason
        self.owner_worker_id = None
        self.lease_expires_at = None


@dataclass(slots=True)
class RunState:
    run_id: UUID
    state_version: int = 0
    turn_count: int = 0
    tool_call_count: int = 0
    model_invocations_used: int = 0
    tool_attempts_used: int = 0


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

    def not_executed(self, reason: str) -> None:
        if self.status is not ToolCallStatus.READY:
            raise ValueError("tool call can only become NOT_EXECUTED from READY")
        self.status = ToolCallStatus.NOT_EXECUTED
        self.error = reason

    def unresolve(self, reason: str) -> None:
        if self.status is not ToolCallStatus.EXECUTING:
            raise ValueError("tool call can only become UNRESOLVED from EXECUTING")
        self.status = ToolCallStatus.UNRESOLVED
        self.error = reason

    def retry_after_failure(self, reason: str) -> None:
        if self.status is not ToolCallStatus.FAILED:
            raise ValueError("tool call can only retry from FAILED")
        self.status = ToolCallStatus.READY
        self.error = reason

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
    error_class: str | None = None
    outcome_reason: str | None = None
    definite_not_executed: bool | None = None
    started_at: datetime = field(default_factory=utcnow)
    finished_at: datetime | None = None
    external_action_id: UUID | None = None

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
        error_class: str | None = None,
        definite_not_executed: bool | None = None,
        outcome_reason: str | None = None,
    ) -> None:
        if self.status is not ToolExecutionAttemptStatus.STARTED:
            raise ValueError("tool attempt can only fail from STARTED")
        self.status = ToolExecutionAttemptStatus.FAILED
        self.error = error
        self.error_class = error_class
        self.definite_not_executed = definite_not_executed
        self.outcome_reason = outcome_reason
        self.finished_at = utcnow()

    def mark_unknown(
        self,
        reason: str,
        *,
        error: str | None = None,
        error_class: str | None = None,
    ) -> None:
        if self.status is not ToolExecutionAttemptStatus.STARTED:
            raise ValueError("tool attempt can only become UNKNOWN from STARTED")
        self.status = ToolExecutionAttemptStatus.UNKNOWN
        self.error = error
        self.error_class = error_class
        self.definite_not_executed = False
        self.outcome_reason = reason
        self.finished_at = utcnow()


@dataclass(frozen=True, slots=True)
class DomainEvent:
    run_id: UUID
    sequence: int
    type: EventType
    payload: dict[str, Any]
    occurred_at: datetime = field(default_factory=utcnow)
