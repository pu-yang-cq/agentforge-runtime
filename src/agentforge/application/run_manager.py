from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from agentforge.application.errors import RunExecutionFailedError
from agentforge.application.ports import ExecutionRecorder
from agentforge.domain.enums import (
    EventType,
    MessageRole,
    RunStatus,
    ToolCallStatus,
    ToolExecutionAttemptStatus,
)
from agentforge.domain.model_contract import ModelMessage
from agentforge.domain.models import (
    AgentVersion,
    DomainEvent,
    ModelInvocation,
    Run,
    RunMessage,
    RunState,
    ToolCall,
    ToolExecutionAttempt,
    ToolProposal,
)
from agentforge.runtime.native_runner import FinalDecision, NativeRunner, ToolDecision
from agentforge.runtime.tool_coordinator import ToolCoordinator, tool_result_message_content


@dataclass(slots=True)
class ExecutionJournal(ExecutionRecorder):
    """In-memory recorder used only by unit tests and pure-runtime validation."""

    messages: list[RunMessage] = field(default_factory=list)
    events: list[DomainEvent] = field(default_factory=list)
    model_invocations: list[ModelInvocation] = field(default_factory=list)
    proposals: list[ToolProposal] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_attempts: list[ToolExecutionAttempt] = field(default_factory=list)
    run_state: RunState | None = None

    def seed(self, run: Run, run_state: RunState) -> None:
        self.run_state = run_state
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
        calls = [
            call
            for call in self.tool_calls
            if call.run_id == run_id and call.status is ToolCallStatus.READY
        ]
        if len(calls) > 1:
            raise RuntimeError("Wave-1 recovery found multiple READY ToolCalls")
        return calls[0] if calls else None

    async def record_recovered_read_started(
        self,
        call: ToolCall,
        *,
        expected_generation: int,
    ) -> None:
        if call.status is not ToolCallStatus.EXECUTING:
            raise ValueError("recovered READ call must be EXECUTING before persistence")
        self._assert_no_started_model_invocations(call.run_id)
        self._assert_no_started_tool_attempts(call.run_id)
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
        self._assert_no_started_tool_attempts(run_id)
        self._assert_no_started_model_invocations(run_id)
        self.run_state.turn_count += 1
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
        if run.status is not RunStatus.COMPLETED:
            raise ValueError("final decision persistence requires a COMPLETED run")
        self._assert_no_active_tool_calls(run.id)
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
        attempt.fail(call.error or "tool failed")
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


class RunManager:
    """Owns Wave-1 Run progression; the recorder owns durable facts/transactions."""

    def __init__(
        self,
        runner: NativeRunner,
        tools: ToolCoordinator,
        *,
        max_turns: int = 16,
    ) -> None:
        self._runner = runner
        self._tools = tools
        self._max_turns = max_turns

    async def execute(
        self,
        *,
        run: Run,
        run_state: RunState,
        agent_version: AgentVersion,
        recorder: ExecutionRecorder,
    ) -> str:
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

        recoverable_call = await recorder.load_recoverable_read_call(run.id)
        if recoverable_call is not None:
            prepared = self._tools.prepare_recovered_read(
                call=recoverable_call, agent_version=agent_version
            )
            await recorder.record_recovered_read_started(
                recoverable_call, expected_generation=expected_generation
            )
            try:
                recovered_call = await self._tools.execute_prepared(prepared)
            except Exception as exc:
                run.fail(f"recovered READ tool {recoverable_call.tool_name} failed: {exc}")
                await recorder.record_tool_failed_and_fail_run(
                    recoverable_call, run, expected_generation=expected_generation
                )
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

        while run_state.turn_count < self._max_turns:
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
            run_state, invocation = await recorder.begin_model_invocation(
                run_id=run.id,
                invocation_id=invocation_id,
                expected_generation=expected_generation,
            )
            try:
                decision = await self._runner.decide_prepared(request)
            except Exception as exc:
                invocation.fail(str(exc))
                run.fail(f"model invocation failed: {exc}")
                await recorder.record_model_failed_and_fail_run(
                    invocation, run, expected_generation=expected_generation
                )
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
                run.complete(decision.text)
                await recorder.record_model_final_decision(
                    invocation, run, message, expected_generation=expected_generation
                )
                return decision.text

            assert isinstance(decision, ToolDecision)
            invocation.complete("TOOL_PROPOSAL")
            proposal = decision.proposal
            try:
                prepared = self._tools.prepare_read(proposal=proposal, agent_version=agent_version)
            except PermissionError as exc:
                call = ToolCall.denied_from_proposal(proposal, error=str(exc))
                run.fail(f"tool {proposal.tool_name} rejected: {exc}")
                await recorder.record_model_tool_denied_and_fail_run(
                    invocation,
                    proposal,
                    call,
                    run,
                    expected_generation=expected_generation,
                )
                raise RunExecutionFailedError(run.failure_reason) from exc

            call = prepared.call
            run_state = await recorder.record_model_tool_started(
                invocation,
                proposal,
                call,
                expected_generation=expected_generation,
            )
            try:
                call = await self._tools.execute_prepared(prepared)
            except Exception as exc:
                run.fail(f"tool {proposal.tool_name} failed: {exc}")
                await recorder.record_tool_failed_and_fail_run(
                    call, run, expected_generation=expected_generation
                )
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

        run.fail("max turns exceeded")
        await recorder.record_run_failed(run, expected_generation=expected_generation)
        raise RunExecutionFailedError("max turns exceeded")
