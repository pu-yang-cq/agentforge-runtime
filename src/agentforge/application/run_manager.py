from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

from agentforge.application.errors import (
    BusinessProgressionBlockedError,
    RunExecutionFailedError,
    SideEffectTransientError,
    ToolAdapterError,
    ToolTransientError,
)
from agentforge.application.ports import ExecutionRecorder, ReconciliationResult
from agentforge.domain.actions import ActionSnapshot, ExternalAction
from agentforge.domain.enums import (
    EventType,
    ExternalActionStatus,
    MessageRole,
    QueueReason,
    ReconciliationAttemptStatus,
    ReconciliationBusinessResult,
    ReconciliationMode,
    RunStatus,
    ToolCallStatus,
    ToolExecutionAttemptStatus,
)
from agentforge.domain.model_contract import ModelMessage
from agentforge.domain.models import (
    AgentVersion,
    DomainEvent,
    ModelInvocation,
    ReconciliationAttempt,
    Run,
    RunMessage,
    RunState,
    ToolBinding,
    ToolCall,
    ToolExecutionAttempt,
    ToolProposal,
    utcnow,
)
from agentforge.runtime.native_runner import FinalDecision, NativeRunner, ToolDecision
from agentforge.runtime.tool_coordinator import (
    PreparedExternalAction,
    PreparedToolCall,
    ToolCoordinator,
    tool_result_message_content,
)


@dataclass(slots=True)
class ExecutionJournal(ExecutionRecorder):
    """In-memory recorder used only by unit tests and pure-runtime validation."""

    messages: list[RunMessage] = field(default_factory=list)
    events: list[DomainEvent] = field(default_factory=list)
    model_invocations: list[ModelInvocation] = field(default_factory=list)
    proposals: list[ToolProposal] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_attempts: list[ToolExecutionAttempt] = field(default_factory=list)
    reconciliation_attempts: list[ReconciliationAttempt] = field(default_factory=list)
    action_snapshots: list[ActionSnapshot] = field(default_factory=list)
    external_actions: list[ExternalAction] = field(default_factory=list)
    run_state: RunState | None = None
    seeded_run: Run | None = None

    def seed(self, run: Run, run_state: RunState) -> None:
        self.run_state = run_state
        self.seeded_run = run
        if not self.messages:
            self._append_message(run, MessageRole.USER, run.input_text)

    def _stored_invocation(self, invocation_id: UUID) -> ModelInvocation:
        for invocation in self.model_invocations:
            if invocation.id == invocation_id:
                return invocation
        raise RuntimeError(f"model invocation not durably started: {invocation_id}")

    def _persist_completed_invocation(self, invocation: ModelInvocation) -> None:
        stored = self._stored_invocation(invocation.id)
        if invocation.outcome_type is None:
            raise ValueError("completed invocation requires outcome_type")
        stored.complete(invocation.outcome_type)

    def _persist_failed_invocation(self, invocation: ModelInvocation) -> None:
        stored = self._stored_invocation(invocation.id)
        if invocation.error is None:
            raise ValueError("failed invocation requires error")
        stored.fail(invocation.error)

    def _append_message(
        self,
        run: Run,
        role: MessageRole,
        content: str,
        source_id: UUID | None = None,
    ) -> RunMessage:
        message = RunMessage(run.id, len(self.messages) + 1, role, content, source_id)
        self.messages.append(message)
        return message

    def _append_event(self, run: Run, event_type: EventType, payload: dict[str, Any]) -> None:
        self.events.append(DomainEvent(run.id, len(self.events) + 1, event_type, payload))

    def _assert_no_active_tool_calls(self, run_id: UUID) -> None:
        active = [
            call
            for call in self.tool_calls
            if call.run_id == run_id
            and call.status in {ToolCallStatus.READY, ToolCallStatus.EXECUTING}
        ]
        if active:
            raise RuntimeError(
                f"cannot terminalize run {run_id} with active ToolCall {active[0].id}"
            )

    def _assert_no_unresolved_actions(self, run_id: UUID) -> None:
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
        attempts = [
            attempt
            for attempt in self.tool_attempts
            if attempt.tool_call_id == tool_call_id
            and attempt.status is ToolExecutionAttemptStatus.STARTED
        ]
        if len(attempts) != 1:
            raise RuntimeError(
                f"expected one STARTED ToolExecutionAttempt for {tool_call_id}, "
                f"found {len(attempts)}"
            )
        return attempts[0]

    def _next_tool_attempt_number(self, tool_call_id: UUID) -> int:
        numbers = [
            attempt.attempt_number
            for attempt in self.tool_attempts
            if attempt.tool_call_id == tool_call_id
        ]
        return max(numbers, default=0) + 1

    def _assert_no_started_tool_attempts(self, run_id: UUID) -> None:
        started = [
            attempt
            for attempt in self.tool_attempts
            if attempt.run_id == run_id and attempt.status is ToolExecutionAttemptStatus.STARTED
        ]
        if started:
            raise RuntimeError(
                f"cannot progress run {run_id} with STARTED ToolExecutionAttempt {started[0].id}"
            )

    def _limits(self, run_id: UUID) -> tuple[Run, RunState]:
        if self.seeded_run is None or self.seeded_run.id != run_id:
            raise RuntimeError("journal run is not seeded")
        if self.run_state is None or self.run_state.run_id != run_id:
            raise RuntimeError("journal run state is not seeded")
        return self.seeded_run, self.run_state

    def _assert_deadline_not_expired(self, run_id: UUID) -> None:
        run, _ = self._limits(run_id)
        if utcnow() >= run.deadline_at:
            raise BusinessProgressionBlockedError(
                "DEADLINE_EXCEEDED",
                "run deadline has expired",
            )

    def _assert_model_budget(self, run_id: UUID) -> None:
        run, state = self._limits(run_id)
        if state.model_invocations_used >= run.max_model_invocations:
            raise BusinessProgressionBlockedError(
                "BUDGET_EXCEEDED",
                "max_model_invocations exhausted",
            )

    def _assert_tool_budget(self, run_id: UUID) -> None:
        run, state = self._limits(run_id)
        if state.tool_attempts_used >= run.max_tool_attempts:
            raise BusinessProgressionBlockedError(
                "BUDGET_EXCEEDED",
                "max_tool_attempts exhausted",
            )

    def _assert_no_started_model_invocations(self, run_id: UUID) -> None:
        started = [
            invocation
            for invocation in self.model_invocations
            if invocation.run_id == run_id and invocation.status.value == "STARTED"
        ]
        if started:
            raise RuntimeError(
                f"cannot terminalize run {run_id} with STARTED ModelInvocation {started[0].id}"
            )

    async def list_messages(self, run_id: UUID) -> list[RunMessage]:
        return [message for message in self.messages if message.run_id == run_id]

    async def load_recoverable_read_call(self, run_id: UUID) -> ToolCall | None:
        side_effect_call_ids = {action.tool_call_id for action in self.external_actions}
        calls = [
            call
            for call in self.tool_calls
            if call.run_id == run_id
            and call.status is ToolCallStatus.READY
            and call.id not in side_effect_call_ids
        ]
        if len(calls) > 1:
            raise RuntimeError("Wave-1 recovery found multiple READY ToolCalls")
        return calls[0] if calls else None

    async def load_ready_external_action(
        self,
        run_id: UUID,
    ) -> tuple[ToolCall, ActionSnapshot, ExternalAction] | None:
        actions = [
            action
            for action in self.external_actions
            if action.run_id == run_id and action.status is ExternalActionStatus.READY
        ]
        if len(actions) > 1:
            raise RuntimeError("found multiple READY ExternalActions for one Run")
        if not actions:
            return None
        action = actions[0]
        call = next(item for item in self.tool_calls if item.id == action.tool_call_id)
        snapshot = next(
            item for item in self.action_snapshots if item.id == action.action_snapshot_id
        )
        if call.status is not ToolCallStatus.READY:
            raise RuntimeError("READY ExternalAction does not project to READY ToolCall")
        return call, snapshot, action

    async def load_unknown_external_action(
        self,
        run_id: UUID,
    ) -> tuple[ToolCall, ActionSnapshot, ExternalAction] | None:
        actions = [
            action
            for action in self.external_actions
            if action.run_id == run_id and action.status is ExternalActionStatus.UNKNOWN
        ]
        if len(actions) > 1:
            raise RuntimeError("found multiple UNKNOWN ExternalActions for one Run")
        if not actions:
            return None
        action = actions[0]
        call = next(item for item in self.tool_calls if item.id == action.tool_call_id)
        snapshot = next(
            item for item in self.action_snapshots if item.id == action.action_snapshot_id
        )
        if action.current_attempt_id is not None:
            raise RuntimeError("UNKNOWN ExternalAction cannot retain current_attempt_id")
        if call.status is not ToolCallStatus.UNRESOLVED:
            raise RuntimeError("UNKNOWN ExternalAction does not project to UNRESOLVED ToolCall")
        return call, snapshot, action

    async def load_reconciliation_external_action(
        self,
        run_id: UUID,
    ) -> tuple[ToolCall, ActionSnapshot, ExternalAction] | None:
        actions = [
            action
            for action in self.external_actions
            if action.run_id == run_id
            and action.status
            in {
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

        safe_not_executed = result.outcome is ReconciliationBusinessResult.NOT_EXECUTED and (
            binding.reconciliation_mode is ReconciliationMode.AUTHORITATIVE
            or (
                binding.reconciliation_mode is ReconciliationMode.BEST_EFFORT
                and binding.idempotency_supported
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
        self,
        call: ToolCall,
        action: ExternalAction,
        *,
        expected_generation: int,
    ) -> ToolExecutionAttempt:
        if call.status is not ToolCallStatus.READY:
            raise ValueError("Action Commit requires READY ToolCall")
        if action.status is not ExternalActionStatus.READY or action.current_attempt_id is not None:
            raise ValueError("Action Commit requires READY ExternalAction")
        if action.tool_call_id != call.id:
            raise ValueError("ExternalAction does not reference ToolCall")
        self._assert_deadline_not_expired(call.run_id)
        self._assert_tool_budget(call.run_id)
        self._assert_no_started_model_invocations(call.run_id)
        self._assert_no_started_tool_attempts(call.run_id)
        assert self.run_state is not None
        attempt = ToolExecutionAttempt(
            uuid4(),
            call.run_id,
            call.id,
            self._next_tool_attempt_number(call.id),
            expected_generation,
            external_action_id=action.id,
        )
        self.run_state.tool_attempts_used += 1
        self.run_state.state_version += 1
        self.tool_attempts.append(attempt)
        call.start()
        action.start(attempt.id)
        self.events.append(
            DomainEvent(
                call.run_id,
                len(self.events) + 1,
                EventType.ACTION_COMMITTED,
                {
                    "tool_call_id": str(call.id),
                    "external_action_id": str(action.id),
                    "operation_id": str(action.operation_id),
                    "attempt_id": str(attempt.id),
                    "attempt_number": attempt.attempt_number,
                },
            )
        )
        self.events.append(
            DomainEvent(
                call.run_id,
                len(self.events) + 1,
                EventType.TOOL_STARTED,
                {
                    "tool_call_id": str(call.id),
                    "tool_name": call.tool_name,
                    "external_action_id": str(action.id),
                    "attempt_id": str(attempt.id),
                    "attempt_number": attempt.attempt_number,
                },
            )
        )
        return attempt

    async def record_ready_side_effect_blocked_and_fail_run(
        self,
        call: ToolCall,
        action: ExternalAction,
        run: Run,
        reason: str,
        *,
        expected_generation: int,
    ) -> None:
        if call.status is not ToolCallStatus.READY:
            raise ValueError("blocked action stabilization requires READY ToolCall")
        if action.status is not ExternalActionStatus.READY:
            raise ValueError("blocked action stabilization requires READY ExternalAction")
        self._assert_no_started_tool_attempts(run.id)
        call.not_executed(reason)
        action.abort()
        self._append_event(
            run,
            EventType.ACTION_ABORTED,
            {
                "tool_call_id": str(call.id),
                "external_action_id": str(action.id),
                "operation_id": str(action.operation_id),
                "reason": reason,
            },
        )
        self._append_event(run, EventType.RUN_FAILED, {"reason": run.failure_reason})

    async def record_side_effect_succeeded(
        self,
        call: ToolCall,
        action: ExternalAction,
        attempt: ToolExecutionAttempt,
        message: RunMessage,
        *,
        expected_generation: int,
    ) -> None:
        if call.status is not ToolCallStatus.SUCCEEDED:
            raise ValueError("side-effect success requires SUCCEEDED ToolCall")
        if action.status is not ExternalActionStatus.EXECUTING:
            raise ValueError("side-effect success requires EXECUTING ExternalAction")
        if action.current_attempt_id != attempt.id:
            raise ValueError("side-effect success attempt is not current")
        durable_attempt = self._started_tool_attempt(call.id)
        if durable_attempt.id != attempt.id or durable_attempt.external_action_id != action.id:
            raise RuntimeError("side-effect durable attempt mismatch")
        durable_attempt.succeed(call.result)
        action.succeed()
        self.messages.append(
            RunMessage(
                message.run_id,
                len(self.messages) + 1,
                message.role,
                message.content,
                message.source_id,
            )
        )
        self.events.append(
            DomainEvent(
                call.run_id,
                len(self.events) + 1,
                EventType.ACTION_SUCCEEDED,
                {
                    "tool_call_id": str(call.id),
                    "external_action_id": str(action.id),
                    "operation_id": str(action.operation_id),
                    "attempt_id": str(attempt.id),
                },
            )
        )
        self.events.append(
            DomainEvent(
                call.run_id,
                len(self.events) + 1,
                EventType.TOOL_SUCCEEDED,
                {
                    "tool_call_id": str(call.id),
                    "tool_name": call.tool_name,
                    "attempt_id": str(attempt.id),
                    "attempt_number": attempt.attempt_number,
                },
            )
        )

    async def record_side_effect_unknown(
        self,
        call: ToolCall,
        action: ExternalAction,
        attempt: ToolExecutionAttempt,
        *,
        error: str,
        error_class: str,
        outcome_reason: str,
        expected_generation: int,
    ) -> None:
        if call.status is not ToolCallStatus.EXECUTING:
            raise ValueError("UNKNOWN persistence requires EXECUTING ToolCall")
        if action.status is not ExternalActionStatus.EXECUTING:
            raise ValueError("UNKNOWN persistence requires EXECUTING ExternalAction")
        if action.current_attempt_id != attempt.id:
            raise ValueError("UNKNOWN persistence attempt is not current")
        durable_attempt = self._started_tool_attempt(call.id)
        if durable_attempt.id != attempt.id or durable_attempt.external_action_id != action.id:
            raise RuntimeError("UNKNOWN durable attempt mismatch")
        durable_attempt.mark_unknown(
            outcome_reason,
            error=error,
            error_class=error_class,
        )
        call.unresolve(error)
        action.mark_unknown()
        self.events.append(
            DomainEvent(
                call.run_id,
                len(self.events) + 1,
                EventType.ACTION_UNKNOWN,
                {
                    "tool_call_id": str(call.id),
                    "external_action_id": str(action.id),
                    "operation_id": str(action.operation_id),
                    "attempt_id": str(attempt.id),
                    "attempt_number": attempt.attempt_number,
                    "error_class": error_class,
                    "outcome_reason": outcome_reason,
                },
            )
        )

    async def record_side_effect_definite_failure_and_fail_run(
        self,
        call: ToolCall,
        action: ExternalAction,
        attempt: ToolExecutionAttempt,
        run: Run,
        *,
        error: str,
        error_class: str,
        expected_generation: int,
    ) -> None:
        if run.status is not RunStatus.FAILED:
            raise ValueError("definite side-effect failure requires FAILED Run")
        if call.status is not ToolCallStatus.EXECUTING:
            raise ValueError("definite side-effect failure requires EXECUTING ToolCall")
        if action.status is not ExternalActionStatus.EXECUTING:
            raise ValueError("definite side-effect failure requires EXECUTING ExternalAction")
        if action.current_attempt_id != attempt.id:
            raise ValueError("definite side-effect failure attempt is not current")
        durable_attempt = self._started_tool_attempt(call.id)
        if durable_attempt.id != attempt.id or durable_attempt.external_action_id != action.id:
            raise RuntimeError("definite side-effect durable attempt mismatch")
        durable_attempt.fail(
            error,
            error_class=error_class,
            definite_not_executed=True,
            outcome_reason="SIDE_EFFECT_DEFINITE_NOT_EXECUTED",
        )
        call.fail(error)
        action.fail_definite_not_executed()
        self._append_event(
            run,
            EventType.ACTION_FAILED,
            {
                "tool_call_id": str(call.id),
                "external_action_id": str(action.id),
                "operation_id": str(action.operation_id),
                "attempt_id": str(attempt.id),
                "attempt_number": attempt.attempt_number,
                "error_class": error_class,
                "definite_not_executed": True,
            },
        )
        self._append_event(
            run,
            EventType.TOOL_FAILED,
            {
                "tool_call_id": str(call.id),
                "tool_name": call.tool_name,
                "attempt_id": str(attempt.id),
                "attempt_number": attempt.attempt_number,
                "error_class": error_class,
                "definite_not_executed": True,
                "error": error,
            },
        )
        self._append_event(run, EventType.RUN_FAILED, {"reason": run.failure_reason})

    async def record_side_effect_transient_failure(
        self,
        call: ToolCall,
        action: ExternalAction,
        attempt: ToolExecutionAttempt,
        run: Run,
        *,
        max_attempts: int,
        initial_backoff_seconds: int,
        max_backoff_seconds: int,
        expected_generation: int,
    ) -> bool:
        if call.status is not ToolCallStatus.EXECUTING:
            raise ValueError("side-effect retry requires EXECUTING ToolCall")
        if action.status is not ExternalActionStatus.EXECUTING:
            raise ValueError("side-effect retry requires EXECUTING ExternalAction")
        if action.current_attempt_id != attempt.id:
            raise ValueError("side-effect retry attempt is not current")
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        if initial_backoff_seconds < 0 or max_backoff_seconds < initial_backoff_seconds:
            raise ValueError("invalid side-effect retry backoff")
        durable_attempt = self._started_tool_attempt(call.id)
        if durable_attempt.id != attempt.id:
            raise RuntimeError("side-effect retry durable attempt mismatch")
        error = "retryable side-effect failure with proven non-execution"
        durable_attempt.fail(
            error,
            error_class="TRANSIENT",
            definite_not_executed=True,
            outcome_reason="SIDE_EFFECT_TRANSIENT_DEFINITE_NOT_EXECUTED",
        )
        assert self.run_state is not None
        delay_seconds = min(
            initial_backoff_seconds * (2 ** (attempt.attempt_number - 1)),
            max_backoff_seconds,
        )
        due_at = utcnow() + timedelta(seconds=delay_seconds)
        retry_allowed = (
            attempt.attempt_number < max_attempts
            and self.run_state.tool_attempts_used < run.max_tool_attempts
            and due_at < run.deadline_at
        )
        if retry_allowed:
            call.retry_ready(error)
            action.retry_ready_after_definite_not_executed()
            run.yield_to_queue(QueueReason.RETRY)
            run.available_at = due_at
            self._append_event(
                run,
                EventType.TOOL_FAILED,
                {
                    "tool_call_id": str(call.id),
                    "attempt_id": str(attempt.id),
                    "attempt_number": attempt.attempt_number,
                    "error_class": "TRANSIENT",
                    "definite_not_executed": True,
                },
            )
            self._append_event(
                run,
                EventType.ACTION_RETRY_READY,
                {
                    "external_action_id": str(action.id),
                    "operation_id": str(action.operation_id),
                    "attempt_id": str(attempt.id),
                },
            )
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
            reason = "SIDE_EFFECT_RETRY_EXHAUSTED: versioned safe retry attempts exhausted"
            call.fail(error)
            action.fail_definite_not_executed()
            run.fail(reason)
            self._append_event(
                run,
                EventType.ACTION_FAILED,
                {
                    "external_action_id": str(action.id),
                    "operation_id": str(action.operation_id),
                    "reason": reason,
                },
            )
        else:
            reason = (
                "BUDGET_EXCEEDED: max_tool_attempts exhausted"
                if self.run_state.tool_attempts_used >= run.max_tool_attempts
                else "DEADLINE_EXCEEDED: side-effect retry due time reaches run deadline"
            )
            call.abort_after_definite_not_executed(reason)
            action.abort_after_definite_not_executed()
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
        return False

    async def record_recovered_read_started(
        self,
        call: ToolCall,
        *,
        expected_generation: int,
    ) -> None:
        if call.status is not ToolCallStatus.EXECUTING:
            raise ValueError("recovered READ call must be EXECUTING before persistence")
        self._assert_deadline_not_expired(call.run_id)
        self._assert_tool_budget(call.run_id)
        self._assert_no_started_model_invocations(call.run_id)
        self._assert_no_started_tool_attempts(call.run_id)
        assert self.run_state is not None
        self.run_state.tool_attempts_used += 1
        self.run_state.state_version += 1
        attempt = ToolExecutionAttempt(
            uuid4(),
            call.run_id,
            call.id,
            self._next_tool_attempt_number(call.id),
            expected_generation,
        )
        self.tool_attempts.append(attempt)
        self.events.append(
            DomainEvent(
                call.run_id,
                len(self.events) + 1,
                EventType.TOOL_STARTED,
                {
                    "tool_call_id": str(call.id),
                    "tool_name": call.tool_name,
                    "attempt_id": str(attempt.id),
                    "attempt_number": attempt.attempt_number,
                    "recovered_retry": True,
                },
            )
        )

    async def record_recovered_read_blocked_and_fail_run(
        self,
        call: ToolCall,
        run: Run,
        *,
        expected_generation: int,
    ) -> None:
        if call.status is not ToolCallStatus.FAILED:
            raise ValueError("blocked recovered READ must be FAILED")
        if run.status is not RunStatus.FAILED:
            raise ValueError("blocked recovered READ requires FAILED run")
        self._assert_no_started_tool_attempts(run.id)
        self._assert_no_started_model_invocations(run.id)
        durable = next(item for item in self.tool_calls if item.id == call.id)
        if durable.status is not ToolCallStatus.READY:
            raise RuntimeError("durable recovered READ is no longer READY")
        durable.status = ToolCallStatus.FAILED
        durable.error = call.error
        self._append_event(
            run,
            EventType.TOOL_FAILED,
            {"tool_call_id": str(call.id), "error": call.error},
        )
        self._append_event(run, EventType.RUN_FAILED, {"reason": run.failure_reason})

    async def record_run_started(self, run: Run) -> None:
        self._append_event(run, EventType.RUN_STARTED, {})

    async def begin_model_invocation(
        self,
        *,
        run_id: UUID,
        invocation_id: UUID,
        expected_generation: int,
    ) -> tuple[RunState, ModelInvocation]:
        if self.run_state is None or self.run_state.run_id != run_id:
            raise RuntimeError("journal run state is not seeded")
        self._assert_no_active_tool_calls(run_id)
        self._assert_no_unresolved_actions(run_id)
        self._assert_no_started_tool_attempts(run_id)
        self._assert_no_started_model_invocations(run_id)
        self._assert_deadline_not_expired(run_id)
        self._assert_model_budget(run_id)
        self.run_state.turn_count += 1
        self.run_state.model_invocations_used += 1
        self.run_state.state_version += 1
        invocation = ModelInvocation(invocation_id, run_id, self.run_state.turn_count)
        self.model_invocations.append(
            ModelInvocation(invocation.id, invocation.run_id, invocation.turn)
        )
        self.events.append(
            DomainEvent(
                run_id,
                len(self.events) + 1,
                EventType.MODEL_STARTED,
                {"turn": invocation.turn, "invocation_id": str(invocation.id)},
            )
        )
        return self.run_state, invocation

    async def record_model_tool_started(
        self,
        invocation: ModelInvocation,
        proposal: ToolProposal,
        call: ToolCall,
        *,
        expected_generation: int,
    ) -> RunState:
        if self.run_state is None:
            raise RuntimeError("journal run state is not seeded")
        if call.status is not ToolCallStatus.EXECUTING:
            raise ValueError("accepted tool call must be EXECUTING before persistence")
        self._assert_no_active_tool_calls(call.run_id)
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
        self.run_state.tool_attempts_used += 1
        self.run_state.state_version += 1
        self.tool_calls.append(call)
        attempt = ToolExecutionAttempt(
            uuid4(),
            call.run_id,
            call.id,
            self._next_tool_attempt_number(call.id),
            expected_generation,
        )
        self.tool_attempts.append(attempt)
        self.events.append(
            DomainEvent(
                call.run_id,
                len(self.events) + 1,
                EventType.TOOL_STARTED,
                {
                    "tool_call_id": str(call.id),
                    "tool_name": call.tool_name,
                    "attempt_id": str(attempt.id),
                    "attempt_number": attempt.attempt_number,
                },
            )
        )
        return self.run_state

    async def record_model_side_effect_prepared(
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

    async def record_model_tool_denied_and_fail_run(
        self,
        invocation: ModelInvocation,
        proposal: ToolProposal,
        call: ToolCall,
        run: Run,
        *,
        expected_generation: int,
    ) -> None:
        if self.run_state is None:
            raise RuntimeError("journal run state is not seeded")
        if run.status is not RunStatus.FAILED:
            raise ValueError("denied tool persistence requires a FAILED run")
        if call.status is not ToolCallStatus.DENIED:
            raise ValueError("denied tool persistence requires a DENIED ToolCall")
        self._assert_no_active_tool_calls(run.id)
        self._assert_deadline_not_expired(run.id)
        self._persist_completed_invocation(invocation)
        self._assert_no_started_model_invocations(run.id)
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
        self.events.append(
            DomainEvent(
                call.run_id,
                len(self.events) + 1,
                EventType.TOOL_DENIED,
                {"tool_call_id": str(call.id), "tool_name": call.tool_name, "error": call.error},
            )
        )
        self._append_event(run, EventType.RUN_FAILED, {"reason": run.failure_reason})

    async def record_model_final_decision(
        self,
        invocation: ModelInvocation,
        run: Run,
        message: RunMessage,
        *,
        expected_generation: int,
    ) -> None:
        if run.status is not RunStatus.RUNNING:
            raise ValueError("final decision persistence requires a RUNNING run")
        self._assert_no_active_tool_calls(run.id)
        self._assert_deadline_not_expired(run.id)
        self._persist_completed_invocation(invocation)
        self._assert_no_started_model_invocations(run.id)
        self.events.append(
            DomainEvent(
                invocation.run_id,
                len(self.events) + 1,
                EventType.MODEL_COMPLETED,
                {"turn": invocation.turn, "outcome_type": invocation.outcome_type},
            )
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
        self._append_event(run, EventType.RUN_COMPLETED, {})

    async def record_model_result_discarded_and_fail_run(
        self,
        invocation: ModelInvocation,
        run: Run,
        reason: str,
        *,
        expected_generation: int,
    ) -> None:
        if run.status is not RunStatus.FAILED:
            raise ValueError("discarded model result requires FAILED run")
        self._assert_no_active_tool_calls(run.id)
        self._persist_completed_invocation(invocation)
        self._assert_no_started_model_invocations(run.id)
        self._append_event(
            run,
            EventType.MODEL_COMPLETED,
            {"turn": invocation.turn, "outcome_type": invocation.outcome_type},
        )
        self._append_event(
            run,
            EventType.MODEL_RESULT_DISCARDED,
            {"invocation_id": str(invocation.id), "reason": reason},
        )
        self._append_event(run, EventType.RUN_FAILED, {"reason": run.failure_reason})

    async def record_model_result_discarded_and_cancel_run(
        self,
        invocation: ModelInvocation,
        run: Run,
        reason: str,
        *,
        expected_generation: int,
    ) -> None:
        self._persist_completed_invocation(invocation)
        run.cancel()
        self._append_event(
            run,
            EventType.MODEL_RESULT_DISCARDED,
            {"invocation_id": str(invocation.id), "reason": reason},
        )
        self._append_event(run, EventType.RUN_CANCELLED, {})

    async def record_run_cancelled(
        self,
        run: Run,
        *,
        expected_generation: int,
    ) -> None:
        run.cancel()
        self._append_event(run, EventType.RUN_CANCELLED, {})

    async def record_model_failed_and_fail_run(
        self,
        invocation: ModelInvocation,
        run: Run,
        *,
        expected_generation: int,
    ) -> None:
        if run.status is not RunStatus.FAILED:
            raise ValueError("model failure persistence requires a FAILED run")
        self._assert_no_active_tool_calls(run.id)
        self._persist_failed_invocation(invocation)
        self._assert_no_started_model_invocations(run.id)
        self.events.append(
            DomainEvent(
                invocation.run_id,
                len(self.events) + 1,
                EventType.MODEL_FAILED,
                {"turn": invocation.turn, "error": invocation.error},
            )
        )
        self._append_event(run, EventType.RUN_FAILED, {"reason": run.failure_reason})

    async def record_tool_succeeded(
        self,
        call: ToolCall,
        message: RunMessage,
        *,
        expected_generation: int,
    ) -> None:
        if call.status is not ToolCallStatus.SUCCEEDED:
            raise ValueError("tool success persistence requires a SUCCEEDED ToolCall")
        attempt = self._started_tool_attempt(call.id)
        attempt.succeed(call.result)
        self.messages.append(
            RunMessage(
                message.run_id,
                len(self.messages) + 1,
                message.role,
                message.content,
                message.source_id,
            )
        )
        self.events.append(
            DomainEvent(
                call.run_id,
                len(self.events) + 1,
                EventType.TOOL_SUCCEEDED,
                {
                    "tool_call_id": str(call.id),
                    "tool_name": call.tool_name,
                    "attempt_id": str(attempt.id),
                    "attempt_number": attempt.attempt_number,
                },
            )
        )

    async def record_read_transient_failure(
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
        if run.status is not RunStatus.FAILED:
            raise ValueError("tool failure persistence requires a FAILED run")
        if call.status is not ToolCallStatus.FAILED:
            raise ValueError("tool failure persistence requires a FAILED ToolCall")
        attempt = self._started_tool_attempt(call.id)
        attempt.fail(
            call.error or "tool failed",
            error_class="PERMANENT",
            definite_not_executed=True,
            outcome_reason="READ_NON_RETRYABLE_FAILURE",
        )
        self._assert_no_active_tool_calls(run.id)
        self._assert_no_started_tool_attempts(run.id)
        self._assert_no_started_model_invocations(run.id)
        self.events.append(
            DomainEvent(
                call.run_id,
                len(self.events) + 1,
                EventType.TOOL_FAILED,
                {"tool_call_id": str(call.id), "error": call.error},
            )
        )
        self._append_event(run, EventType.RUN_FAILED, {"reason": run.failure_reason})

    async def record_run_failed(self, run: Run, *, expected_generation: int) -> None:
        if run.status is not RunStatus.FAILED:
            raise ValueError("run failure persistence requires a FAILED run")
        self._assert_no_active_tool_calls(run.id)
        self._assert_no_started_tool_attempts(run.id)
        self._assert_no_started_model_invocations(run.id)
        self._append_event(run, EventType.RUN_FAILED, {"reason": run.failure_reason})

    async def record_run_yielded(
        self,
        run: Run,
        *,
        delay_seconds: int,
        expected_generation: int,
    ) -> None:
        if run.status is not RunStatus.QUEUED or run.queue_reason is not QueueReason.YIELD:
            raise ValueError("durable yield requires QUEUED/YIELD run")
        if delay_seconds < 0:
            raise ValueError("delay_seconds cannot be negative")
        self._assert_no_active_tool_calls(run.id)
        self._assert_no_started_tool_attempts(run.id)
        self._assert_no_started_model_invocations(run.id)
        self._assert_deadline_not_expired(run.id)
        self._assert_model_budget(run.id)
        self._append_event(
            run,
            EventType.RUN_YIELDED,
            {"delay_seconds": delay_seconds},
        )


class RunManager:
    """Owns Wave-1 Run progression; the recorder owns durable facts/transactions."""

    def __init__(
        self,
        runner: NativeRunner,
        tools: ToolCoordinator,
        *,
        max_progression_steps_per_claim: int = 8,
    ) -> None:
        if max_progression_steps_per_claim <= 0:
            raise ValueError("max_progression_steps_per_claim must be positive")
        self._runner = runner
        self._tools = tools
        self._max_progression_steps_per_claim = max_progression_steps_per_claim

    async def _execute_side_effect_action(
        self,
        *,
        run: Run,
        prepared: PreparedExternalAction,
        recorder: ExecutionRecorder,
        expected_generation: int,
    ) -> RunMessage | None:
        try:
            attempt = await recorder.record_side_effect_attempt_started(
                prepared.call,
                prepared.action,
                expected_generation=expected_generation,
            )
        except BusinessProgressionBlockedError as exc:
            run.fail(exc.failure_reason)
            await recorder.record_ready_side_effect_blocked_and_fail_run(
                prepared.call,
                prepared.action,
                run,
                exc.failure_reason,
                expected_generation=expected_generation,
            )
            raise RunExecutionFailedError(run.failure_reason) from exc

        try:
            call = await self._tools.execute_side_effect(prepared, attempt)
        except SideEffectTransientError as exc:
            scheduled = await recorder.record_side_effect_transient_failure(
                prepared.call,
                prepared.action,
                attempt,
                run,
                max_attempts=prepared.binding.side_effect_retry_max_attempts,
                initial_backoff_seconds=prepared.binding.side_effect_retry_initial_backoff_seconds,
                max_backoff_seconds=prepared.binding.side_effect_retry_max_backoff_seconds,
                expected_generation=expected_generation,
            )
            if scheduled:
                return None
            if run.cancel_requested:
                return None
            raise RunExecutionFailedError(run.failure_reason or str(exc)) from exc
        except ToolAdapterError as exc:
            if exc.definite_not_executed:
                reason = (
                    f"side-effect tool {prepared.call.tool_name} definitely did not execute: {exc}"
                )
                run.fail(reason)
                await recorder.record_side_effect_definite_failure_and_fail_run(
                    prepared.call,
                    prepared.action,
                    attempt,
                    run,
                    error=str(exc),
                    error_class=exc.error_class,
                    expected_generation=expected_generation,
                )
                if run.cancel_requested:
                    return None
                raise RunExecutionFailedError(run.failure_reason) from exc
            await recorder.record_side_effect_unknown(
                prepared.call,
                prepared.action,
                attempt,
                error=str(exc),
                error_class=exc.error_class,
                outcome_reason="SIDE_EFFECT_POSSIBLE_EXECUTION",
                expected_generation=expected_generation,
            )
            return None
        except Exception as exc:
            await recorder.record_side_effect_unknown(
                prepared.call,
                prepared.action,
                attempt,
                error=str(exc),
                error_class=type(exc).__name__,
                outcome_reason="SIDE_EFFECT_UNCLASSIFIED_EXCEPTION_AFTER_COMMIT",
                expected_generation=expected_generation,
            )
            return None

        message = RunMessage(
            run.id,
            0,
            MessageRole.TOOL,
            tool_result_message_content(call.result),
            call.id,
        )
        await recorder.record_side_effect_succeeded(
            call,
            prepared.action,
            attempt,
            message,
            expected_generation=expected_generation,
        )
        return message

    async def execute(
        self,
        *,
        run: Run,
        run_state: RunState,
        agent_version: AgentVersion,
        recorder: ExecutionRecorder,
    ) -> str | None:
        if isinstance(recorder, ExecutionJournal):
            recorder.seed(run, run_state)

        if run.status is RunStatus.QUEUED:
            run.start()
            await recorder.record_run_started(run)
        elif run.status is not RunStatus.RUNNING:
            raise ValueError(f"run must be QUEUED or RUNNING, got {run.status}")

        expected_generation = run.execution_generation
        messages = await recorder.list_messages(run.id)
        if not messages:
            raise RuntimeError("run has no durable user message")

        progression_steps = 0
        prepared: PreparedToolCall | PreparedExternalAction

        # Persisted unresolved external truth outranks new model reasoning.
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
        if ready_action is not None:
            ready_call, ready_snapshot, external_action = ready_action
            prepared_action = self._tools.prepare_recovered_side_effect(
                call=ready_call,
                snapshot=ready_snapshot,
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

        recoverable_call = await recorder.load_recoverable_read_call(run.id)
        if recoverable_call is not None:
            prepared = self._tools.prepare_recovered_read(
                call=recoverable_call, agent_version=agent_version
            )
            try:
                await recorder.record_recovered_read_started(
                    recoverable_call, expected_generation=expected_generation
                )
            except BusinessProgressionBlockedError as exc:
                recoverable_call.fail(exc.failure_reason)
                run.fail(exc.failure_reason)
                await recorder.record_recovered_read_blocked_and_fail_run(
                    recoverable_call,
                    run,
                    expected_generation=expected_generation,
                )
                raise RunExecutionFailedError(run.failure_reason) from exc
            try:
                recovered_call = await self._tools.execute_prepared(prepared)
            except ToolTransientError as exc:
                scheduled = await recorder.record_read_transient_failure(
                    recoverable_call,
                    run,
                    max_attempts=prepared.binding.read_retry_max_attempts,
                    initial_backoff_seconds=prepared.binding.read_retry_initial_backoff_seconds,
                    max_backoff_seconds=prepared.binding.read_retry_max_backoff_seconds,
                    expected_generation=expected_generation,
                )
                if scheduled:
                    return None
                if run.cancel_requested:
                    return None
                raise RunExecutionFailedError(run.failure_reason or str(exc)) from exc
            except Exception as exc:
                run.fail(f"recovered READ tool {recoverable_call.tool_name} failed: {exc}")
                await recorder.record_tool_failed_and_fail_run(
                    recoverable_call, run, expected_generation=expected_generation
                )
                if run.cancel_requested:
                    run.status = RunStatus.RUNNING
                    run.failure_reason = None
                    run.completed_at = None
                    run.cancel()
                    return None
                raise RunExecutionFailedError(run.failure_reason) from exc

            recovered_message = RunMessage(
                run.id,
                0,
                MessageRole.TOOL,
                tool_result_message_content(recovered_call.result),
                recovered_call.id,
            )
            await recorder.record_tool_succeeded(
                recovered_call, recovered_message, expected_generation=expected_generation
            )
            messages.append(recovered_message)
            progression_steps += 1

        while True:
            if progression_steps >= self._max_progression_steps_per_claim:
                run.yield_to_queue(QueueReason.YIELD)
                try:
                    await recorder.record_run_yielded(
                        run,
                        delay_seconds=0,
                        expected_generation=expected_generation,
                    )
                except BusinessProgressionBlockedError as exc:
                    run.status = RunStatus.RUNNING
                    run.queue_reason = None
                    run.fail(exc.failure_reason)
                    await recorder.record_run_failed(
                        run,
                        expected_generation=expected_generation,
                    )
                    raise RunExecutionFailedError(run.failure_reason) from exc
                return None
            invocation_id = uuid4()
            model_messages = tuple(
                ModelMessage(message.role.value.lower(), message.content) for message in messages
            )
            request = self._runner.prepare_request(
                invocation_id=invocation_id,
                run_id=run.id,
                agent_version=agent_version,
                messages=model_messages,
            )
            try:
                run_state, invocation = await recorder.begin_model_invocation(
                    run_id=run.id,
                    invocation_id=invocation_id,
                    expected_generation=expected_generation,
                )
            except BusinessProgressionBlockedError as exc:
                if exc.code == "CANCEL_REQUESTED":
                    run.request_cancel()
                    await recorder.record_run_cancelled(
                        run,
                        expected_generation=expected_generation,
                    )
                    return None
                run.fail(exc.failure_reason)
                await recorder.record_run_failed(
                    run,
                    expected_generation=expected_generation,
                )
                raise RunExecutionFailedError(run.failure_reason) from exc
            try:
                decision = await self._runner.decide_prepared(request)
            except Exception as exc:
                invocation.fail(str(exc))
                run.fail(f"model invocation failed: {exc}")
                await recorder.record_model_failed_and_fail_run(
                    invocation, run, expected_generation=expected_generation
                )
                if run.cancel_requested:
                    run.status = RunStatus.RUNNING
                    run.failure_reason = None
                    run.completed_at = None
                    run.cancel()
                    return None
                raise RunExecutionFailedError(run.failure_reason) from exc

            if isinstance(decision, FinalDecision):
                invocation.complete("FINAL")
                message = RunMessage(
                    run.id,
                    0,
                    MessageRole.ASSISTANT,
                    decision.text,
                    decision.model_invocation_id,
                )
                try:
                    await recorder.record_model_final_decision(
                        invocation,
                        run,
                        message,
                        expected_generation=expected_generation,
                    )
                except BusinessProgressionBlockedError as exc:
                    if exc.code == "CANCEL_REQUESTED":
                        run.request_cancel()
                        await recorder.record_model_result_discarded_and_cancel_run(
                            invocation,
                            run,
                            exc.failure_reason,
                            expected_generation=expected_generation,
                        )
                        return None
                    run.fail(exc.failure_reason)
                    await recorder.record_model_result_discarded_and_fail_run(
                        invocation,
                        run,
                        exc.failure_reason,
                        expected_generation=expected_generation,
                    )
                    raise RunExecutionFailedError(run.failure_reason) from exc
                run.complete(decision.text)
                return decision.text

            assert isinstance(decision, ToolDecision)
            invocation.complete("TOOL_PROPOSAL")
            proposal = decision.proposal
            try:
                prepared = self._tools.prepare_model_tool(
                    proposal=proposal,
                    agent_version=agent_version,
                )
            except PermissionError as exc:
                call = ToolCall.denied_from_proposal(proposal, error=str(exc))
                run.fail(f"tool {proposal.tool_name} rejected: {exc}")
                try:
                    await recorder.record_model_tool_denied_and_fail_run(
                        invocation,
                        proposal,
                        call,
                        run,
                        expected_generation=expected_generation,
                    )
                except BusinessProgressionBlockedError as blocked:
                    if blocked.code == "CANCEL_REQUESTED":
                        # Permission rejection was only an in-memory candidate
                        # business consequence. Cancellation won the Run-row
                        # serialization race, so discard that candidate rather
                        # than persist FAILED.
                        run.status = RunStatus.RUNNING
                        run.failure_reason = None
                        run.completed_at = None
                        run.request_cancel()
                        await recorder.record_model_result_discarded_and_cancel_run(
                            invocation,
                            run,
                            blocked.failure_reason,
                            expected_generation=expected_generation,
                        )
                        return None
                    run.failure_reason = blocked.failure_reason
                    await recorder.record_model_result_discarded_and_fail_run(
                        invocation,
                        run,
                        blocked.failure_reason,
                        expected_generation=expected_generation,
                    )
                    raise RunExecutionFailedError(run.failure_reason) from blocked
                raise RunExecutionFailedError(run.failure_reason) from exc

            if isinstance(prepared, PreparedExternalAction):
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
                    if exc.code == "CANCEL_REQUESTED":
                        run.request_cancel()
                        await recorder.record_model_result_discarded_and_cancel_run(
                            invocation,
                            run,
                            exc.failure_reason,
                            expected_generation=expected_generation,
                        )
                        return None
                    run.fail(exc.failure_reason)
                    await recorder.record_model_result_discarded_and_fail_run(
                        invocation,
                        run,
                        exc.failure_reason,
                        expected_generation=expected_generation,
                    )
                    raise RunExecutionFailedError(run.failure_reason) from exc
                side_effect_message = await self._execute_side_effect_action(
                    run=run,
                    prepared=prepared,
                    recorder=recorder,
                    expected_generation=expected_generation,
                )
                if side_effect_message is None:
                    return None
                messages.append(side_effect_message)
                progression_steps += 1
                continue

            call = prepared.call
            try:
                run_state = await recorder.record_model_tool_started(
                    invocation,
                    proposal,
                    call,
                    expected_generation=expected_generation,
                )
            except BusinessProgressionBlockedError as exc:
                if exc.code == "CANCEL_REQUESTED":
                    run.request_cancel()
                    await recorder.record_model_result_discarded_and_cancel_run(
                        invocation,
                        run,
                        exc.failure_reason,
                        expected_generation=expected_generation,
                    )
                    return None
                run.fail(exc.failure_reason)
                await recorder.record_model_result_discarded_and_fail_run(
                    invocation,
                    run,
                    exc.failure_reason,
                    expected_generation=expected_generation,
                )
                raise RunExecutionFailedError(run.failure_reason) from exc
            try:
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
                if run.cancel_requested:
                    return None
                raise RunExecutionFailedError(run.failure_reason or str(exc)) from exc
            except Exception as exc:
                run.fail(f"tool {proposal.tool_name} failed: {exc}")
                await recorder.record_tool_failed_and_fail_run(
                    call, run, expected_generation=expected_generation
                )
                if run.cancel_requested:
                    run.status = RunStatus.RUNNING
                    run.failure_reason = None
                    run.completed_at = None
                    run.cancel()
                    return None
                raise RunExecutionFailedError(run.failure_reason) from exc

            message = RunMessage(
                run.id,
                0,
                MessageRole.TOOL,
                tool_result_message_content(call.result),
                call.id,
            )
            await recorder.record_tool_succeeded(
                call, message, expected_generation=expected_generation
            )
            messages.append(message)
            progression_steps += 1
