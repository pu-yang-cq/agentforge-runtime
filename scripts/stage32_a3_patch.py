from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"{path}: expected exactly one anchor, found {count}: {old[:120]!r}"
        )
    file.write_text(text.replace(old, new))


# ---------- adapter error contract ----------
replace_once(
    "src/agentforge/application/errors.py",
    '''class BusinessProgressionBlockedError(RuntimeError):
''',
    '''class ToolAdapterError(RuntimeError):
    """Structured adapter failure; unknown exceptions are never implicitly retryable."""

    def __init__(
        self,
        message: str,
        *,
        error_class: str,
        definite_not_executed: bool,
    ) -> None:
        self.error_class = error_class
        self.definite_not_executed = definite_not_executed
        super().__init__(message)


class ToolTransientError(ToolAdapterError):
    """Explicit opt-in signal for a retryable READ adapter failure."""

    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            error_class="TRANSIENT",
            definite_not_executed=True,
        )


class BusinessProgressionBlockedError(RuntimeError):
''',
)

# ---------- versioned READ retry policy ----------
replace_once(
    "src/agentforge/domain/models.py",
    '''@dataclass(frozen=True, slots=True)
class ToolBinding:
    tool_version_id: UUID
    name: str
''',
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
        delay: int = self.read_retry_initial_backoff_seconds * (
            2 ** (failed_attempt_number - 1)
        )
        return min(delay, self.read_retry_max_backoff_seconds)
''',
)

replace_once(
    "src/agentforge/domain/models.py",
    '''    error: str | None = None
    outcome_reason: str | None = None
''',
    '''    error: str | None = None
    error_class: str | None = None
    outcome_reason: str | None = None
''',
)

replace_once(
    "src/agentforge/domain/models.py",
    '''    def fail(
        self,
        error: str,
        *,
        definite_not_executed: bool | None = None,
        outcome_reason: str | None = None,
    ) -> None:
''',
    '''    def fail(
        self,
        error: str,
        *,
        error_class: str | None = None,
        definite_not_executed: bool | None = None,
        outcome_reason: str | None = None,
    ) -> None:
''',
)

replace_once(
    "src/agentforge/domain/models.py",
    '''        self.status = ToolExecutionAttemptStatus.FAILED
        self.error = error
        self.definite_not_executed = definite_not_executed
''',
    '''        self.status = ToolExecutionAttemptStatus.FAILED
        self.error = error
        self.error_class = error_class
        self.definite_not_executed = definite_not_executed
''',
)

replace_once(
    "src/agentforge/domain/models.py",
    '''    def start(self) -> None:
        if self.status is not ToolCallStatus.READY:
            raise ValueError("tool call can only execute from READY")
        self.status = ToolCallStatus.EXECUTING
        self.error = None
''',
    '''    def start(self) -> None:
        if self.status is not ToolCallStatus.READY:
            raise ValueError("tool call can only execute from READY")
        self.status = ToolCallStatus.EXECUTING
        self.error = None

    def retry_after_failure(self, reason: str) -> None:
        if self.status is not ToolCallStatus.FAILED:
            raise ValueError("tool call can only retry from FAILED")
        self.status = ToolCallStatus.READY
        self.error = reason
''',
)

# ---------- ToolVersion persistence ----------
replace_once(
    "src/agentforge/infrastructure/db/models.py",
    '''class ToolVersionRow(Base):
    __tablename__ = "tool_versions"
    __table_args__ = (UniqueConstraint("tool_id", "version_number"),)
''',
    '''class ToolVersionRow(Base):
    __tablename__ = "tool_versions"
    __table_args__ = (
        UniqueConstraint("tool_id", "version_number"),
        CheckConstraint(
            "read_retry_max_attempts > 0",
            name="ck_tool_versions_positive_read_retry_attempts",
        ),
        CheckConstraint(
            "read_retry_initial_backoff_seconds >= 0",
            name="ck_tool_versions_nonnegative_read_retry_initial_backoff",
        ),
        CheckConstraint(
            "read_retry_max_backoff_seconds >= read_retry_initial_backoff_seconds",
            name="ck_tool_versions_read_retry_backoff_order",
        ),
    )
''',
)

replace_once(
    "src/agentforge/infrastructure/db/models.py",
    '''    implementation_ref: Mapped[str] = mapped_column(String(300), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
''',
    '''    implementation_ref: Mapped[str] = mapped_column(String(300), nullable=False)
    read_retry_max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    read_retry_initial_backoff_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )
    read_retry_max_backoff_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30
    )
    created_at: Mapped[datetime] = mapped_column(
''',
)

# ---------- binding mapper + loader ----------
replace_once(
    "src/agentforge/infrastructure/db/mappers.py",
    '''    bindings: list[tuple[UUID, str]],
''',
    '''    bindings: list[tuple[UUID, str, int, int, int]],
''',
)

replace_once(
    "src/agentforge/infrastructure/db/mappers.py",
    '''        tool_bindings=tuple(
            ToolBinding(tool_version_id, alias) for tool_version_id, alias in bindings
        ),
''',
    '''        tool_bindings=tuple(
            ToolBinding(
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
        ),
''',
)

replace_once(
    "src/agentforge/infrastructure/db/runtime_store.py",
    '''                    select(
                        AgentVersionToolRow.tool_version_id,
                        AgentVersionToolRow.tool_alias,
                    )
                    .where(AgentVersionToolRow.agent_version_id == agent_version_id)
''',
    '''                    select(
                        AgentVersionToolRow.tool_version_id,
                        AgentVersionToolRow.tool_alias,
                        ToolVersionRow.read_retry_max_attempts,
                        ToolVersionRow.read_retry_initial_backoff_seconds,
                        ToolVersionRow.read_retry_max_backoff_seconds,
                    )
                    .join(
                        ToolVersionRow,
                        ToolVersionRow.id == AgentVersionToolRow.tool_version_id,
                    )
                    .where(AgentVersionToolRow.agent_version_id == agent_version_id)
''',
)

replace_once(
    "src/agentforge/infrastructure/db/runtime_store.py",
    '''                bindings=[(tool_version_id, alias) for tool_version_id, alias in rows],
''',
    '''                bindings=[
                    (
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
                    ) in rows
                ],
''',
)

# ---------- ToolCoordinator exposes the frozen binding policy ----------
replace_once(
    "src/agentforge/runtime/tool_coordinator.py",
    '''from agentforge.domain.models import AgentVersion, ToolCall, ToolProposal
''',
    '''from agentforge.domain.models import AgentVersion, ToolBinding, ToolCall, ToolProposal
''',
)

replace_once(
    "src/agentforge/runtime/tool_coordinator.py",
    '''class PreparedToolCall:
    call: ToolCall
    tool: Tool
''',
    '''class PreparedToolCall:
    call: ToolCall
    tool: Tool
    binding: ToolBinding
''',
)

replace_once(
    "src/agentforge/runtime/tool_coordinator.py",
    '''    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def prepare_read(
''',
    '''    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    @staticmethod
    def _binding(name: str, agent_version: AgentVersion) -> ToolBinding:
        matches = [binding for binding in agent_version.tool_bindings if binding.name == name]
        if len(matches) != 1:
            raise PermissionError(f"tool is not uniquely bound to agent version: {name}")
        return matches[0]

    def prepare_read(
''',
)

replace_once(
    "src/agentforge/runtime/tool_coordinator.py",
    '''        tool = self._registry.resolve(proposal.tool_name, agent_version.tool_bindings)
        call = ToolCall.from_proposal(proposal, tool_version_id=tool.version_id)
        call.ready()
        call.start()
        return PreparedToolCall(call=call, tool=tool)
''',
    '''        binding = self._binding(proposal.tool_name, agent_version)
        tool = self._registry.resolve(proposal.tool_name, agent_version.tool_bindings)
        call = ToolCall.from_proposal(proposal, tool_version_id=tool.version_id)
        call.ready()
        call.start()
        return PreparedToolCall(call=call, tool=tool, binding=binding)
''',
)

replace_once(
    "src/agentforge/runtime/tool_coordinator.py",
    '''        tool = self._registry.resolve(call.tool_name, agent_version.tool_bindings)
        if tool.version_id != call.tool_version_id:
            raise ValueError("recovered READ call tool version no longer matches binding")
        call.start()
        return PreparedToolCall(call=call, tool=tool)
''',
    '''        binding = self._binding(call.tool_name, agent_version)
        tool = self._registry.resolve(call.tool_name, agent_version.tool_bindings)
        if tool.version_id != call.tool_version_id or binding.tool_version_id != call.tool_version_id:
            raise ValueError("recovered READ call tool version no longer matches binding")
        call.start()
        return PreparedToolCall(call=call, tool=tool, binding=binding)
''',
)

# ---------- ExecutionRecorder contract ----------
replace_once(
    "src/agentforge/application/ports.py",
    '''    async def record_tool_failed_and_fail_run(
        self,
        call: ToolCall,
        run: Run,
        *,
        expected_generation: int,
    ) -> None: ...

    async def record_run_failed(self, run: Run, *, expected_generation: int) -> None: ...
''',
    '''    async def record_read_transient_failure(
        self,
        call: ToolCall,
        run: Run,
        *,
        max_attempts: int,
        initial_backoff_seconds: int,
        max_backoff_seconds: int,
        expected_generation: int,
    ) -> bool: ...

    async def record_tool_failed_and_fail_run(
        self,
        call: ToolCall,
        run: Run,
        *,
        expected_generation: int,
    ) -> None: ...

    async def record_run_failed(self, run: Run, *, expected_generation: int) -> None: ...
''',
)

# ---------- events ----------
replace_once(
    "src/agentforge/domain/enums.py",
    '''    TOOL_RETRY_READY = "TOOL_RETRY_READY"
''',
    '''    TOOL_RETRY_READY = "TOOL_RETRY_READY"
    TOOL_RETRY_SCHEDULED = "TOOL_RETRY_SCHEDULED"
''',
)

# ---------- RunManager imports ----------
replace_once(
    "src/agentforge/application/run_manager.py",
    '''    BusinessProgressionBlockedError,
    RunExecutionFailedError,
)
''',
    '''    BusinessProgressionBlockedError,
    RunExecutionFailedError,
    ToolTransientError,
)
''',
)

# ---------- In-memory retry command ----------
replace_once(
    "src/agentforge/application/run_manager.py",
    '''    async def record_tool_failed_and_fail_run(
        self,
        call: ToolCall,
        run: Run,
        *,
        expected_generation: int,
    ) -> None:
''',
    '''    async def record_read_transient_failure(
        self,
        call: ToolCall,
        run: Run,
        *,
        max_attempts: int,
        initial_backoff_seconds: int,
        max_backoff_seconds: int,
        expected_generation: int,
    ) -> bool:
        if call.status is not ToolCallStatus.FAILED:
            raise ValueError("transient READ persistence requires FAILED ToolCall")
        if run.status is not RunStatus.RUNNING:
            raise ValueError("transient READ persistence requires RUNNING Run")
        if initial_backoff_seconds < 0:
            raise ValueError("retry initial backoff cannot be negative")
        if max_backoff_seconds < initial_backoff_seconds:
            raise ValueError("retry max backoff cannot be below initial backoff")
        attempt = self._started_tool_attempt(call.id)
        delay_seconds = min(
            initial_backoff_seconds * (2 ** (attempt.attempt_number - 1)),
            max_backoff_seconds,
        )
        attempt.fail(
            call.error or "transient READ failure",
            error_class="TRANSIENT",
            definite_not_executed=True,
            outcome_reason="READ_TRANSIENT_FAILURE",
        )
        self._assert_no_started_tool_attempts(run.id)
        assert self.run_state is not None
        retry_allowed = (
            attempt.attempt_number < max_attempts
            and self.run_state.tool_attempts_used < run.max_tool_attempts
            and utcnow() + timedelta(seconds=delay_seconds) < run.deadline_at
        )
        self._append_event(
            run,
            EventType.TOOL_FAILED,
            {
                "tool_call_id": str(call.id),
                "attempt_id": str(attempt.id),
                "attempt_number": attempt.attempt_number,
                "error_class": "TRANSIENT",
                "definite_not_executed": True,
                "error": call.error,
            },
        )
        if retry_allowed:
            call.retry_after_failure(call.error or "transient READ failure")
            run.yield_to_queue(QueueReason.RETRY)
            run.available_at = utcnow() + timedelta(seconds=delay_seconds)
            self._append_event(
                run,
                EventType.TOOL_RETRY_SCHEDULED,
                {
                    "tool_call_id": str(call.id),
                    "attempt_number": attempt.attempt_number,
                    "delay_seconds": delay_seconds,
                },
            )
            return True

        if attempt.attempt_number >= max_attempts:
            failure_reason = "READ_RETRY_EXHAUSTED: versioned READ retry attempts exhausted"
        elif self.run_state.tool_attempts_used >= run.max_tool_attempts:
            failure_reason = "BUDGET_EXCEEDED: max_tool_attempts exhausted"
        else:
            failure_reason = "DEADLINE_EXCEEDED: READ retry due time reaches run deadline"
        run.fail(failure_reason)
        self._append_event(run, EventType.RUN_FAILED, {"reason": failure_reason})
        return False

    async def record_tool_failed_and_fail_run(
        self,
        call: ToolCall,
        run: Run,
        *,
        expected_generation: int,
    ) -> None:
''',
)

# timedelta import required by in-memory durable scheduler.
replace_once(
    "src/agentforge/application/run_manager.py",
    '''from dataclasses import dataclass, field
from typing import Any
''',
    '''from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any
''',
)

# Generic READ failures become explicit non-retryable attempt evidence.
replace_once(
    "src/agentforge/application/run_manager.py",
    '''        attempt = self._started_tool_attempt(call.id)
        attempt.fail(call.error or "tool failed")
''',
    '''        attempt = self._started_tool_attempt(call.id)
        attempt.fail(
            call.error or "tool failed",
            error_class="PERMANENT",
            definite_not_executed=True,
            outcome_reason="READ_NON_RETRYABLE_FAILURE",
        )
''',
)

# ---------- RunManager transient branches ----------
replace_once(
    "src/agentforge/application/run_manager.py",
    '''            try:
                recovered_call = await self._tools.execute_prepared(prepared)
            except Exception as exc:
                run.fail(f"recovered READ tool {recoverable_call.tool_name} failed: {exc}")
                await recorder.record_tool_failed_and_fail_run(
                    recoverable_call, run, expected_generation=expected_generation
                )
                raise RunExecutionFailedError(run.failure_reason) from exc

            recovered_message = RunMessage(
''',
    '''            try:
                recovered_call = await self._tools.execute_prepared(prepared)
            except ToolTransientError as exc:
                delay_seconds = prepared.binding.read_retry_delay_seconds(
                    self._current_attempt_number(recorder, recoverable_call.id)
                )
                scheduled = await recorder.record_read_transient_failure(
                    recoverable_call,
                    run,
                    max_attempts=prepared.binding.read_retry_max_attempts,
                    delay_seconds=delay_seconds,
                    expected_generation=expected_generation,
                )
                if scheduled:
                    return None
                raise RunExecutionFailedError(run.failure_reason or str(exc)) from exc
            except Exception as exc:
                run.fail(f"recovered READ tool {recoverable_call.tool_name} failed: {exc}")
                await recorder.record_tool_failed_and_fail_run(
                    recoverable_call, run, expected_generation=expected_generation
                )
                raise RunExecutionFailedError(run.failure_reason) from exc

            recovered_message = RunMessage(
''',
)

# Add a recorder-independent attempt number helper by using ToolCall history cannot be queried.
# We instead compute delay in recorder from current attempt number, so revise the prior block.
replace_once(
    "src/agentforge/application/run_manager.py",
    '''                delay_seconds = prepared.binding.read_retry_delay_seconds(
                    self._current_attempt_number(recorder, recoverable_call.id)
                )
                scheduled = await recorder.record_read_transient_failure(
                    recoverable_call,
                    run,
                    max_attempts=prepared.binding.read_retry_max_attempts,
                    delay_seconds=delay_seconds,
''',
    '''                scheduled = await recorder.record_read_transient_failure(
                    recoverable_call,
                    run,
                    max_attempts=prepared.binding.read_retry_max_attempts,
                    initial_backoff_seconds=prepared.binding.read_retry_initial_backoff_seconds,
                    max_backoff_seconds=prepared.binding.read_retry_max_backoff_seconds,
''',
)

replace_once(
    "src/agentforge/application/run_manager.py",
    '''            try:
                call = await self._tools.execute_prepared(prepared)
            except Exception as exc:
                run.fail(f"tool {proposal.tool_name} failed: {exc}")
                await recorder.record_tool_failed_and_fail_run(
                    call, run, expected_generation=expected_generation
                )
                raise RunExecutionFailedError(run.failure_reason) from exc

            message = RunMessage(
''',
    '''            try:
                call = await self._tools.execute_prepared(prepared)
            except ToolTransientError as exc:
                scheduled = await recorder.record_read_transient_failure(
                    call,
                    run,
                    max_attempts=prepared.binding.read_retry_max_attempts,
                    initial_backoff_seconds=prepared.binding.read_retry_initial_backoff_seconds,
                    max_backoff_seconds=prepared.binding.read_retry_max_backoff_seconds,
                    expected_generation=expected_generation,
                )
                if scheduled:
                    return None
                raise RunExecutionFailedError(run.failure_reason or str(exc)) from exc
            except Exception as exc:
                run.fail(f"tool {proposal.tool_name} failed: {exc}")
                await recorder.record_tool_failed_and_fail_run(
                    call, run, expected_generation=expected_generation
                )
                raise RunExecutionFailedError(run.failure_reason) from exc

            message = RunMessage(
''',
)

# ---------- PostgreSQL retry command ----------
replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''    async def record_tool_failed_and_fail_run(
        self,
        call: ToolCall,
        run: Run,
        *,
        expected_generation: int,
    ) -> None:
''',
    '''    async def record_read_transient_failure(
        self,
        call: ToolCall,
        run: Run,
        *,
        max_attempts: int,
        initial_backoff_seconds: int,
        max_backoff_seconds: int,
        expected_generation: int,
    ) -> bool:
        self._assert_generation(expected_generation)
        if call.status is not ToolCallStatus.FAILED:
            raise ValueError("transient READ persistence requires FAILED ToolCall")
        if run.status is not RunStatus.RUNNING:
            raise ValueError("transient READ persistence requires RUNNING Run")
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        if initial_backoff_seconds < 0:
            raise ValueError("retry initial backoff cannot be negative")
        if max_backoff_seconds < initial_backoff_seconds:
            raise ValueError("retry max backoff cannot be below initial backoff")

        async with self._sessions() as session, session.begin():
            row = await _lock_owned_run(
                session, run_id=call.run_id, expected_generation=expected_generation
            )
            tool_call = (
                await session.execute(
                    select(ToolCallRow)
                    .where(
                        ToolCallRow.id == call.id,
                        ToolCallRow.run_id == call.run_id,
                        ToolCallRow.status == ToolCallStatus.EXECUTING,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if tool_call is None:
                raise RuntimeError("tool call no longer EXECUTING")
            attempt = await _lock_started_tool_attempt(session, call.id)
            state = await _lock_run_state(session, run.id)
            db_now = await _database_now(session)
            delay_seconds = min(
                initial_backoff_seconds * (2 ** (attempt.attempt_number - 1)),
                max_backoff_seconds,
            )
            due_at = db_now + timedelta(seconds=delay_seconds)

            attempt.status = ToolExecutionAttemptStatus.FAILED
            attempt.error = call.error
            attempt.error_class = "TRANSIENT"
            attempt.outcome_reason = "READ_TRANSIENT_FAILURE"
            attempt.definite_not_executed = True
            attempt.finished_at = db_now

            retry_allowed = (
                attempt.attempt_number < max_attempts
                and state.tool_attempts_used < row.max_tool_attempts
                and due_at < row.deadline_at
            )
            if retry_allowed:
                tool_call.status = ToolCallStatus.READY
                tool_call.error = call.error
                row.status = RunStatus.QUEUED
                row.queue_reason = QueueReason.RETRY
                row.available_at = due_at
                row.owner_worker_id = None
                row.lease_expires_at = None
                seqs = list(await _allocate_event_sequences(session, run.id, 2))
                session.add_all(
                    [
                        DomainEventRow(
                            id=uuid4(),
                            run_id=run.id,
                            sequence=seqs[0],
                            event_type=EventType.TOOL_FAILED.value,
                            payload={
                                "tool_call_id": str(call.id),
                                "attempt_id": str(attempt.id),
                                "attempt_number": attempt.attempt_number,
                                "error_class": "TRANSIENT",
                                "definite_not_executed": True,
                                "error": call.error,
                            },
                        ),
                        DomainEventRow(
                            id=uuid4(),
                            run_id=run.id,
                            sequence=seqs[1],
                            event_type=EventType.TOOL_RETRY_SCHEDULED.value,
                            payload={
                                "tool_call_id": str(call.id),
                                "attempt_number": attempt.attempt_number,
                                "delay_seconds": delay_seconds,
                            },
                        ),
                    ]
                )
                run.status = RunStatus.QUEUED
                run.queue_reason = QueueReason.RETRY
                run.owner_worker_id = None
                run.lease_expires_at = None
                run.available_at = due_at
                return True

            if attempt.attempt_number >= max_attempts:
                failure_reason = (
                    "READ_RETRY_EXHAUSTED: versioned READ retry attempts exhausted"
                )
            elif state.tool_attempts_used >= row.max_tool_attempts:
                failure_reason = "BUDGET_EXCEEDED: max_tool_attempts exhausted"
            else:
                failure_reason = (
                    "DEADLINE_EXCEEDED: READ retry due time reaches run deadline"
                )

            tool_call.status = ToolCallStatus.FAILED
            tool_call.error = call.error
            row.status = RunStatus.FAILED
            row.failure_reason = failure_reason
            row.completed_at = db_now
            row.owner_worker_id = None
            row.lease_expires_at = None
            seqs = list(await _allocate_event_sequences(session, run.id, 2))
            session.add_all(
                [
                    DomainEventRow(
                        id=uuid4(),
                        run_id=run.id,
                        sequence=seqs[0],
                        event_type=EventType.TOOL_FAILED.value,
                        payload={
                            "tool_call_id": str(call.id),
                            "attempt_id": str(attempt.id),
                            "attempt_number": attempt.attempt_number,
                            "error_class": "TRANSIENT",
                            "definite_not_executed": True,
                            "error": call.error,
                        },
                    ),
                    DomainEventRow(
                        id=uuid4(),
                        run_id=run.id,
                        sequence=seqs[1],
                        event_type=EventType.RUN_FAILED.value,
                        payload={"reason": failure_reason},
                    ),
                ]
            )
            run.status = RunStatus.FAILED
            run.failure_reason = failure_reason
            run.completed_at = db_now
            return False

    async def record_tool_failed_and_fail_run(
        self,
        call: ToolCall,
        run: Run,
        *,
        expected_generation: int,
    ) -> None:
''',
)

# datetime timedelta import for due time.
replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''from datetime import datetime
''',
    '''from datetime import datetime, timedelta
''',
)

# Populate attempt failure semantics on non-retryable READ.
replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''            attempt.status = ToolExecutionAttemptStatus.FAILED
            attempt.error = call.error
            attempt.finished_at = func.clock_timestamp()
''',
    '''            attempt.status = ToolExecutionAttemptStatus.FAILED
            attempt.error = call.error
            attempt.error_class = "PERMANENT"
            attempt.outcome_reason = "READ_NON_RETRYABLE_FAILURE"
            attempt.definite_not_executed = True
            attempt.finished_at = func.clock_timestamp()
''',
)

# ---------- migration ----------
Path("migrations/versions/0008_read_retry_policy.py").write_text(
    '''"""add versioned READ retry policy

Revision ID: 0008_read_retry_policy
Revises: 0007_run_limits
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_read_retry_policy"
down_revision: str | None = "0007_run_limits"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tool_versions",
        sa.Column(
            "read_retry_max_attempts",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "tool_versions",
        sa.Column(
            "read_retry_initial_backoff_seconds",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "tool_versions",
        sa.Column(
            "read_retry_max_backoff_seconds",
            sa.Integer(),
            nullable=False,
            server_default="30",
        ),
    )
    op.create_check_constraint(
        "ck_tool_versions_positive_read_retry_attempts",
        "tool_versions",
        "read_retry_max_attempts > 0",
    )
    op.create_check_constraint(
        "ck_tool_versions_nonnegative_read_retry_initial_backoff",
        "tool_versions",
        "read_retry_initial_backoff_seconds >= 0",
    )
    op.create_check_constraint(
        "ck_tool_versions_read_retry_backoff_order",
        "tool_versions",
        "read_retry_max_backoff_seconds >= read_retry_initial_backoff_seconds",
    )
    op.alter_column("tool_versions", "read_retry_max_attempts", server_default=None)
    op.alter_column(
        "tool_versions",
        "read_retry_initial_backoff_seconds",
        server_default=None,
    )
    op.alter_column(
        "tool_versions",
        "read_retry_max_backoff_seconds",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_tool_versions_read_retry_backoff_order",
        "tool_versions",
        type_="check",
    )
    op.drop_constraint(
        "ck_tool_versions_nonnegative_read_retry_initial_backoff",
        "tool_versions",
        type_="check",
    )
    op.drop_constraint(
        "ck_tool_versions_positive_read_retry_attempts",
        "tool_versions",
        type_="check",
    )
    op.drop_column("tool_versions", "read_retry_max_backoff_seconds")
    op.drop_column("tool_versions", "read_retry_initial_backoff_seconds")
    op.drop_column("tool_versions", "read_retry_max_attempts")
'''
)

# ---------- migration/schema contracts ----------
replace_once(
    "tests/unit/test_migration_contract.py",
    '''    assert "TOOL_ATTEMPTS_USED" in ddl
''',
    '''    assert "TOOL_ATTEMPTS_USED" in ddl
    assert "0008_READ_RETRY_POLICY" in ddl
    assert "READ_RETRY_MAX_ATTEMPTS" in ddl
    assert "CK_TOOL_VERSIONS_POSITIVE_READ_RETRY_ATTEMPTS" in ddl
''',
)

replace_once(
    "tests/unit/test_postgres_contracts.py",
    '''def test_agent_version_tool_binding_remains_non_nullable() -> None:
''',
    '''def test_tool_version_has_bounded_read_retry_policy() -> None:
    table = Base.metadata.tables["tool_versions"]
    assert {
        "read_retry_max_attempts",
        "read_retry_initial_backoff_seconds",
        "read_retry_max_backoff_seconds",
    }.issubset(table.c.keys())
    checks = {constraint.name for constraint in table.constraints if constraint.name}
    assert {
        "ck_tool_versions_positive_read_retry_attempts",
        "ck_tool_versions_nonnegative_read_retry_initial_backoff",
        "ck_tool_versions_read_retry_backoff_order",
    }.issubset(checks)


def test_agent_version_tool_binding_remains_non_nullable() -> None:
''',
)

# ---------- unit retry tests ----------
replace_once(
    "tests/unit/test_run_manager.py",
    '''from agentforge.application.errors import RunExecutionFailedError
''',
    '''from agentforge.application.errors import RunExecutionFailedError, ToolTransientError
''',
)

append_unit = r'''

@pytest.mark.asyncio
async def test_read_transient_failure_durably_schedules_retry_without_new_model_reasoning() -> None:
    version_id = uuid4()
    invocations = 0

    async def flaky_read():
        nonlocal invocations
        invocations += 1
        if invocations == 1:
            raise ToolTransientError("temporary upstream timeout")
        return {"ok": True}

    registry = InMemoryToolRegistry(
        [
            FunctionTool(
                version_id=version_id,
                name="flaky_read",
                description="retryable read",
                input_schema={"type": "object"},
                func=flaky_read,
            )
        ]
    )
    model = ScriptedFakeModel(
        [
            ToolStep("flaky_read", {}),
            FinalStep("done after retry"),
        ]
    )
    manager = RunManager(NativeRunner(model, registry), ToolCoordinator(registry))
    av = AgentVersion(
        uuid4(),
        uuid4(),
        1,
        "retry",
        (
            ToolBinding(
                version_id,
                "flaky_read",
                read_retry_max_attempts=3,
                read_retry_initial_backoff_seconds=0,
                read_retry_max_backoff_seconds=4,
            ),
        ),
    )
    run = Run(uuid4(), av.id, "retry")
    run.queue()
    state = RunState(run.id)
    journal = ExecutionJournal()

    first = await manager.execute(
        run=run,
        run_state=state,
        agent_version=av,
        recorder=journal,
    )
    assert first is None
    assert run.status is RunStatus.QUEUED
    assert run.queue_reason is QueueReason.RETRY
    assert len(model.requests) == 1
    assert len(journal.tool_calls) == 1
    assert journal.tool_calls[0].status is ToolCallStatus.READY
    assert journal.tool_attempts[0].status is ToolExecutionAttemptStatus.FAILED
    assert journal.tool_attempts[0].error_class == "TRANSIENT"
    assert journal.tool_attempts[0].definite_not_executed is True
    assert EventType.TOOL_RETRY_SCHEDULED in [event.type for event in journal.events]

    second = await manager.execute(
        run=run,
        run_state=state,
        agent_version=av,
        recorder=journal,
    )
    assert second == "done after retry"
    assert invocations == 2
    assert len(model.requests) == 2
    assert [attempt.attempt_number for attempt in journal.tool_attempts] == [1, 2]
    assert [attempt.status for attempt in journal.tool_attempts] == [
        ToolExecutionAttemptStatus.FAILED,
        ToolExecutionAttemptStatus.SUCCEEDED,
    ]


@pytest.mark.asyncio
async def test_unknown_read_exception_is_not_implicitly_retried() -> None:
    version_id = uuid4()
    registry = InMemoryToolRegistry(
        [
            FunctionTool(
                version_id=version_id,
                name="broken_read",
                description="nonretryable read",
                input_schema={"type": "object"},
                func=lambda: (_ for _ in ()).throw(RuntimeError("bad response")),
            )
        ]
    )
    model = ScriptedFakeModel([ToolStep("broken_read", {})])
    manager = RunManager(NativeRunner(model, registry), ToolCoordinator(registry))
    av = AgentVersion(
        uuid4(),
        uuid4(),
        1,
        "do not blind retry",
        (
            ToolBinding(
                version_id,
                "broken_read",
                read_retry_max_attempts=3,
                read_retry_initial_backoff_seconds=0,
                read_retry_max_backoff_seconds=4,
            ),
        ),
    )
    run = Run(uuid4(), av.id, "fail")
    run.queue()
    journal = ExecutionJournal()

    with pytest.raises(RunExecutionFailedError):
        await manager.execute(
            run=run,
            run_state=RunState(run.id),
            agent_version=av,
            recorder=journal,
        )

    assert run.status is RunStatus.FAILED
    assert journal.tool_calls[0].status is ToolCallStatus.FAILED
    assert journal.tool_attempts[0].error_class == "PERMANENT"
    assert EventType.TOOL_RETRY_SCHEDULED not in [event.type for event in journal.events]


def test_versioned_read_retry_backoff_is_bounded_exponential() -> None:
    binding = ToolBinding(
        uuid4(),
        "read",
        read_retry_max_attempts=5,
        read_retry_initial_backoff_seconds=2,
        read_retry_max_backoff_seconds=5,
    )
    assert [binding.read_retry_delay_seconds(n) for n in (1, 2, 3, 4)] == [2, 4, 5, 5]
'''
Path("tests/unit/test_run_manager.py").write_text(
    Path("tests/unit/test_run_manager.py").read_text() + append_unit
)

# ---------- integration retry gate ----------
replace_once(
    "tests/integration/test_postgres_runtime.py",
    '''from agentforge.application.errors import (
    BusinessProgressionBlockedError,
    IdempotencyConflictError,
    StaleExecutorError,
)
''',
    '''from agentforge.application.errors import (
    BusinessProgressionBlockedError,
    IdempotencyConflictError,
    StaleExecutorError,
    ToolTransientError,
)
''',
)

replace_once(
    "tests/integration/test_postgres_runtime.py",
    '''from agentforge.runtime.tool_coordinator import ToolCoordinator
''',
    '''from agentforge.runtime.tool_coordinator import ToolCoordinator
from agentforge.runtime.tools import FunctionTool, InMemoryToolRegistry
''',
)

append_integration = r'''

@pytest.mark.asyncio
async def test_read_transient_retry_uses_db_time_and_survives_worker_restart() -> None:
    from agentforge.infrastructure.db.models import ToolExecutionAttemptRow

    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)

    async with sessions() as session, session.begin():
        tool_version = await session.get(ToolVersionRow, DEMO_TOOL_VERSION_ID)
        assert tool_version is not None
        tool_version.read_retry_max_attempts = 3
        tool_version.read_retry_initial_backoff_seconds = 1
        tool_version.read_retry_max_backoff_seconds = 4

    invocations = 0

    async def flaky_echo(text: str):
        nonlocal invocations
        invocations += 1
        if invocations == 1:
            raise ToolTransientError("temporary read outage")
        return {"echo": text}

    registry = InMemoryToolRegistry(
        [
            FunctionTool(
                version_id=DEMO_TOOL_VERSION_ID,
                name="echo_read",
                description="retryable read",
                input_schema={"type": "object"},
                func=flaky_echo,
            )
        ]
    )
    store = PostgresRuntimeStore(sessions)
    run = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="durable read retry",
        idempotency_key="integration-read-transient-retry-1",
        principal_scope="test-user",
    )

    worker_a = CoreWorker(
        runtime_store=store,
        recorder_factory=PostgresExecutionRecorderFactory(sessions),
        tool_registry=registry,
        model_factory=lambda _: ScriptedFakeModel(
            [ToolStep("echo_read", {"text": "durable read retry"})]
        ),
        worker_id="worker-a",
        lease_seconds=30,
    )
    assert await worker_a.run_once() is True

    scheduled = await store.get_run(run.id)
    assert scheduled is not None
    assert scheduled.status is RunStatus.QUEUED
    assert scheduled.queue_reason is QueueReason.RETRY
    assert scheduled.available_at is not None

    async with sessions() as session:
        calls = (
            (
                await session.execute(
                    select(ToolCallRow).where(ToolCallRow.run_id == run.id)
                )
            )
            .scalars()
            .all()
        )
        attempts = (
            (
                await session.execute(
                    select(ToolExecutionAttemptRow)
                    .where(ToolExecutionAttemptRow.run_id == run.id)
                    .order_by(ToolExecutionAttemptRow.attempt_number)
                )
            )
            .scalars()
            .all()
        )
    assert len(calls) == 1
    original_call_id = calls[0].id
    assert calls[0].status is ToolCallStatus.READY
    assert len(attempts) == 1
    assert attempts[0].status is ToolExecutionAttemptStatus.FAILED
    assert attempts[0].error_class == "TRANSIENT"
    assert attempts[0].definite_not_executed is True

    # The DB available_at gate, not lease expiry, blocks an early claim.
    assert await store.claim_next_run(worker_id="too-early", lease_seconds=30) is None

    await engine.dispose()
    await asyncio.sleep(1.2)

    restarted_engine = create_engine(DATABASE_URL)
    restarted_sessions = create_session_factory(restarted_engine)
    restarted_store = PostgresRuntimeStore(restarted_sessions)
    worker_b = CoreWorker(
        runtime_store=restarted_store,
        recorder_factory=PostgresExecutionRecorderFactory(restarted_sessions),
        tool_registry=registry,
        model_factory=lambda _: ScriptedFakeModel([FinalStep("done after retry")]),
        worker_id="worker-b",
        lease_seconds=30,
    )
    assert await worker_b.run_once() is True

    completed = await restarted_store.get_run(run.id)
    assert completed is not None
    assert completed.status is RunStatus.COMPLETED
    assert completed.execution_generation == 2

    async with restarted_sessions() as session:
        calls = (
            (
                await session.execute(
                    select(ToolCallRow).where(ToolCallRow.run_id == run.id)
                )
            )
            .scalars()
            .all()
        )
        attempts = (
            (
                await session.execute(
                    select(ToolExecutionAttemptRow)
                    .where(ToolExecutionAttemptRow.run_id == run.id)
                    .order_by(ToolExecutionAttemptRow.attempt_number)
                )
            )
            .scalars()
            .all()
        )
        event_types = (
            (
                await session.execute(
                    select(DomainEventRow.event_type)
                    .where(DomainEventRow.run_id == run.id)
                    .order_by(DomainEventRow.sequence)
                )
            )
            .scalars()
            .all()
        )

    assert len(calls) == 1
    assert calls[0].id == original_call_id
    assert calls[0].status is ToolCallStatus.SUCCEEDED
    assert [attempt.attempt_number for attempt in attempts] == [1, 2]
    assert [attempt.status for attempt in attempts] == [
        ToolExecutionAttemptStatus.FAILED,
        ToolExecutionAttemptStatus.SUCCEEDED,
    ]
    assert EventType.TOOL_RETRY_SCHEDULED.value in event_types
    assert invocations == 2
    await restarted_engine.dispose()
'''
Path("tests/integration/test_postgres_runtime.py").write_text(
    Path("tests/integration/test_postgres_runtime.py").read_text() + append_integration
)
