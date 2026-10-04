from datetime import timedelta
from uuid import uuid4

import pytest

from agentforge.application.errors import RunExecutionFailedError
from agentforge.application.run_manager import ExecutionJournal, RunManager
from agentforge.domain.enums import (
    EventType,
    QueueReason,
    RunStatus,
    ToolCallStatus,
    ToolExecutionAttemptStatus,
)
from agentforge.domain.models import (
    AgentVersion,
    DomainEvent,
    Run,
    RunState,
    ToolBinding,
    ToolCall,
    ToolExecutionAttempt,
    ToolProposal,
    utcnow,
)
from agentforge.runtime.fake_model import FinalStep, ScriptedFakeModel, ToolStep
from agentforge.runtime.native_runner import NativeRunner
from agentforge.runtime.tool_coordinator import ToolCoordinator
from agentforge.runtime.tools import FunctionTool, InMemoryToolRegistry


@pytest.mark.asyncio
async def test_core_read_tool_flow_completes() -> None:
    version_id = uuid4()
    registry = InMemoryToolRegistry(
        [
            FunctionTool(
                version_id=version_id,
                name="list_complaints",
                description="List complaints",
                input_schema={"type": "object", "properties": {"days": {"type": "integer"}}},
                func=lambda days: ["login issue", "billing issue"] if days == 30 else [],
            )
        ]
    )
    model = ScriptedFakeModel(
        [ToolStep("list_complaints", {"days": 30}), FinalStep("Top issues: login, billing")]
    )
    manager = RunManager(NativeRunner(model, registry), ToolCoordinator(registry))
    av = AgentVersion(
        uuid4(), uuid4(), 1, "Analyze complaints", (ToolBinding(version_id, "list_complaints"),)
    )
    run = Run(uuid4(), av.id, "Analyze the last 30 days")
    run.queue()
    state = RunState(run.id)
    journal = ExecutionJournal()

    result = await manager.execute(run=run, run_state=state, agent_version=av, recorder=journal)

    assert result.startswith("Top issues")
    assert run.status is RunStatus.COMPLETED
    assert state.turn_count == 2
    assert state.tool_call_count == 1
    assert len(journal.model_invocations) == 2
    assert len(journal.proposals) == 1
    assert journal.tool_calls[0].tool_version_id == version_id
    assert journal.tool_calls[0].status is ToolCallStatus.SUCCEEDED
    assert len(journal.tool_attempts) == 1
    assert journal.tool_attempts[0].attempt_number == 1
    assert journal.tool_attempts[0].status is ToolExecutionAttemptStatus.SUCCEEDED
    assert [e.type for e in journal.events] == [
        EventType.RUN_STARTED,
        EventType.MODEL_STARTED,
        EventType.MODEL_COMPLETED,
        EventType.TOOL_PROPOSED,
        EventType.TOOL_STARTED,
        EventType.TOOL_SUCCEEDED,
        EventType.MODEL_STARTED,
        EventType.MODEL_COMPLETED,
        EventType.RUN_COMPLETED,
    ]


@pytest.mark.asyncio
async def test_hallucinated_unbound_tool_cannot_execute() -> None:
    bound_version = uuid4()
    registry = InMemoryToolRegistry(
        [
            FunctionTool(
                version_id=bound_version,
                name="safe_read",
                description="Safe read",
                input_schema={"type": "object"},
                func=lambda: "ok",
            )
        ]
    )
    model = ScriptedFakeModel([ToolStep("delete_customer", {"id": "c1"})])
    manager = RunManager(NativeRunner(model, registry), ToolCoordinator(registry))
    av = AgentVersion(uuid4(), uuid4(), 1, "Read only", (ToolBinding(bound_version, "safe_read"),))
    run = Run(uuid4(), av.id, "do something unsafe")
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
    assert len(journal.proposals) == 1
    assert len(journal.tool_calls) == 1
    assert journal.tool_calls[0].status is ToolCallStatus.DENIED
    assert journal.tool_calls[0].tool_version_id is None
    assert EventType.TOOL_DENIED in [event.type for event in journal.events]


@pytest.mark.asyncio
async def test_model_failure_marks_run_failed_without_tool_side_effect() -> None:
    class FailingModel:
        async def invoke(self, request):
            raise TimeoutError("model timeout")

    registry = InMemoryToolRegistry([])
    manager = RunManager(NativeRunner(FailingModel(), registry), ToolCoordinator(registry))
    av = AgentVersion(uuid4(), uuid4(), 1, "No tools")
    run = Run(uuid4(), av.id, "hello")
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
    assert run.failure_reason == "model invocation failed: model timeout"
    assert [event.type for event in journal.events[-3:]] == [
        EventType.MODEL_STARTED,
        EventType.MODEL_FAILED,
        EventType.RUN_FAILED,
    ]
    assert journal.model_invocations[-1].status.value == "FAILED"


@pytest.mark.asyncio
async def test_missing_bound_tool_implementation_is_not_misreported_as_policy_denial() -> None:
    version_id = uuid4()
    registry = InMemoryToolRegistry([])
    model = ScriptedFakeModel([ToolStep("bound_but_missing", {})])
    manager = RunManager(NativeRunner(model, registry), ToolCoordinator(registry))
    av = AgentVersion(
        uuid4(),
        uuid4(),
        1,
        "Use configured tool",
        (ToolBinding(version_id, "bound_but_missing"),),
    )
    run = Run(uuid4(), av.id, "invoke missing runtime implementation")
    run.queue()
    journal = ExecutionJournal()

    with pytest.raises(KeyError):
        await manager.execute(
            run=run,
            run_state=RunState(run.id),
            agent_version=av,
            recorder=journal,
        )

    # Infrastructure/configuration failure is not a business DENY and is not
    # silently terminalized by the agent loop. A durable worker will lose/expire
    # its lease and a later owner can retry after the deployment is fixed.
    assert run.status is RunStatus.RUNNING
    assert len(journal.proposals) == 0
    assert len(journal.tool_calls) == 0
    assert len(journal.model_invocations) == 0
    assert model.requests == []
    assert journal.run_state is not None
    assert journal.run_state.turn_count == 0
    assert EventType.MODEL_STARTED not in [event.type for event in journal.events]
    assert EventType.TOOL_DENIED not in [event.type for event in journal.events]


@pytest.mark.asyncio
async def test_recovered_read_tool_is_retried_before_new_model_reasoning() -> None:
    version_id = uuid4()
    invocations: list[str] = []

    async def read_tool(q: str):
        invocations.append(q)
        return {"q": q, "value": "recovered"}

    registry = InMemoryToolRegistry(
        [
            FunctionTool(
                version_id=version_id,
                name="lookup",
                description="lookup",
                input_schema={"type": "object"},
                func=read_tool,
            )
        ]
    )
    model = ScriptedFakeModel([FinalStep("done after deterministic recovery")])
    manager = RunManager(NativeRunner(model, registry), ToolCoordinator(registry))
    av = AgentVersion(uuid4(), uuid4(), 1, "recover", (ToolBinding(version_id, "lookup"),))
    run = Run(
        uuid4(),
        av.id,
        "recover my read",
        status=RunStatus.RUNNING,
        execution_generation=2,
    )
    state = RunState(run.id, state_version=2, turn_count=1, tool_call_count=1)
    journal = ExecutionJournal()
    journal.seed(run, state)

    proposal = ToolProposal.create(
        run_id=run.id,
        model_invocation_id=uuid4(),
        tool_name="lookup",
        arguments={"q": "same-durable-intent"},
    )
    recovered_call = ToolCall.from_proposal(proposal, tool_version_id=version_id)
    recovered_call.ready()
    journal.proposals.append(proposal)
    journal.tool_calls.append(recovered_call)
    previous_attempt = ToolExecutionAttempt(
        uuid4(),
        run.id,
        recovered_call.id,
        1,
        1,
    )
    previous_attempt.mark_unknown("LEASE_LOST_RESULT_NOT_DURABLE")
    journal.tool_attempts.append(previous_attempt)
    journal.events.append(
        DomainEvent(
            run.id,
            len(journal.events) + 1,
            EventType.TOOL_RETRY_READY,
            {"tool_call_id": str(recovered_call.id)},
        )
    )

    result = await manager.execute(
        run=run,
        run_state=state,
        agent_version=av,
        recorder=journal,
    )

    assert result == "done after deterministic recovery"
    assert invocations == ["same-durable-intent"]
    assert recovered_call.status is ToolCallStatus.SUCCEEDED
    recovered_attempts = [
        attempt for attempt in journal.tool_attempts if attempt.tool_call_id == recovered_call.id
    ]
    assert [attempt.attempt_number for attempt in recovered_attempts] == [1, 2]
    assert [attempt.status for attempt in recovered_attempts] == [
        ToolExecutionAttemptStatus.UNKNOWN,
        ToolExecutionAttemptStatus.SUCCEEDED,
    ]
    assert state.tool_call_count == 1  # same logical ToolCall, not a new model-created one
    assert state.turn_count == 2
    assert len(model.requests) == 1
    assert model.requests[0].messages[-1].role == "tool"
    assert "recovered" in model.requests[0].messages[-1].content
    assert [event.type for event in journal.events].count(EventType.TOOL_STARTED) == 1


@pytest.mark.asyncio
async def test_terminalization_is_rejected_while_a_tool_call_is_active() -> None:
    run = Run(uuid4(), uuid4(), "terminal guard", status=RunStatus.RUNNING)
    state = RunState(run.id, tool_call_count=1)
    journal = ExecutionJournal()
    journal.seed(run, state)

    proposal = ToolProposal.create(
        run_id=run.id,
        model_invocation_id=uuid4(),
        tool_name="lookup",
        arguments={"q": "still-running"},
    )
    call = ToolCall.from_proposal(proposal, tool_version_id=uuid4())
    call.ready()
    journal.proposals.append(proposal)
    journal.tool_calls.append(call)

    run.fail("should not be durably terminal yet")
    with pytest.raises(RuntimeError, match="active ToolCall"):
        await journal.record_run_failed(run, expected_generation=0)

    assert call.status is ToolCallStatus.READY
    assert EventType.RUN_FAILED not in [event.type for event in journal.events]


@pytest.mark.asyncio
async def test_terminalization_is_rejected_while_model_invocation_is_started() -> None:
    from agentforge.domain.models import ModelInvocation

    run = Run(uuid4(), uuid4(), "model still in flight", status=RunStatus.RUNNING)
    journal = ExecutionJournal()
    journal.seed(run, RunState(run.id, turn_count=1))
    journal.model_invocations.append(ModelInvocation(uuid4(), run.id, 1))

    run.fail("should not be durably terminal yet")
    with pytest.raises(RuntimeError, match="STARTED ModelInvocation"):
        await journal.record_run_failed(run, expected_generation=0)

    assert EventType.RUN_FAILED not in [event.type for event in journal.events]


@pytest.mark.asyncio
async def test_model_invocation_cannot_start_while_tool_call_is_active() -> None:

    run = Run(uuid4(), uuid4(), "cross-boundary guard", status=RunStatus.RUNNING)
    journal = ExecutionJournal()
    journal.seed(run, RunState(run.id, turn_count=1, tool_call_count=1))

    proposal = ToolProposal.create(
        run_id=run.id,
        model_invocation_id=uuid4(),
        tool_name="lookup",
        arguments={"q": "active"},
    )
    call = ToolCall.from_proposal(proposal, tool_version_id=uuid4())
    call.ready()
    journal.proposals.append(proposal)
    journal.tool_calls.append(call)

    with pytest.raises(RuntimeError, match="active ToolCall"):
        await journal.begin_model_invocation(
            run_id=run.id,
            invocation_id=uuid4(),
            expected_generation=0,
        )

    assert len(journal.model_invocations) == 0
    assert journal.run_state is not None
    assert journal.run_state.turn_count == 1


@pytest.mark.asyncio
async def test_recovered_read_cannot_restart_while_model_invocation_is_started() -> None:
    from agentforge.domain.models import ModelInvocation

    run = Run(uuid4(), uuid4(), "cross-boundary guard", status=RunStatus.RUNNING)
    journal = ExecutionJournal()
    journal.seed(run, RunState(run.id, turn_count=1, tool_call_count=1))
    journal.model_invocations.append(ModelInvocation(uuid4(), run.id, 1))

    proposal = ToolProposal.create(
        run_id=run.id,
        model_invocation_id=uuid4(),
        tool_name="lookup",
        arguments={"q": "recover"},
    )
    call = ToolCall.from_proposal(proposal, tool_version_id=uuid4())
    call.ready()
    call.start()
    journal.proposals.append(proposal)
    journal.tool_calls.append(call)

    with pytest.raises(RuntimeError, match="STARTED ModelInvocation"):
        await journal.record_recovered_read_started(call, expected_generation=0)

    assert EventType.TOOL_STARTED not in [event.type for event in journal.events]


@pytest.mark.asyncio
async def test_persistence_commands_reject_inconsistent_terminal_objects() -> None:
    from agentforge.domain.enums import MessageRole
    from agentforge.domain.models import ModelInvocation, RunMessage

    run = Run(uuid4(), uuid4(), "shape guard", status=RunStatus.CREATED)
    journal = ExecutionJournal()
    journal.seed(run, RunState(run.id))
    invocation = ModelInvocation(uuid4(), run.id, 1)
    journal.model_invocations.append(ModelInvocation(invocation.id, run.id, 1))
    invocation.complete("FINAL")
    message = RunMessage(run.id, 0, MessageRole.ASSISTANT, "done", invocation.id)

    with pytest.raises(ValueError, match="RUNNING run"):
        await journal.record_model_final_decision(invocation, run, message, expected_generation=0)


@pytest.mark.asyncio
async def test_non_json_read_result_durably_fails_run_instead_of_retry_loop() -> None:
    from datetime import datetime

    version_id = uuid4()
    registry = InMemoryToolRegistry(
        [
            FunctionTool(
                version_id=version_id,
                name="bad_json",
                description="bad durable result",
                input_schema={"type": "object"},
                func=lambda: datetime.now(),
            )
        ]
    )
    model = ScriptedFakeModel([ToolStep("bad_json", {})])
    manager = RunManager(NativeRunner(model, registry), ToolCoordinator(registry))
    av = AgentVersion(uuid4(), uuid4(), 1, "use bad tool", (ToolBinding(version_id, "bad_json"),))
    run = Run(uuid4(), av.id, "trigger non-json result")
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
    assert journal.tool_calls[-1].status is ToolCallStatus.FAILED
    assert EventType.TOOL_FAILED in [event.type for event in journal.events]
    assert EventType.RUN_FAILED in [event.type for event in journal.events]
    assert all(message.role.value != "TOOL" for message in journal.messages)


@pytest.mark.asyncio
async def test_durable_model_budget_stops_before_extra_invocation() -> None:
    version_id = uuid4()
    registry = InMemoryToolRegistry(
        [
            FunctionTool(
                version_id=version_id,
                name="read_once",
                description="read once",
                input_schema={"type": "object"},
                func=lambda: {"ok": True},
            )
        ]
    )
    model = ScriptedFakeModel(
        [
            ToolStep("read_once", {}),
            FinalStep("must never be requested"),
        ]
    )
    manager = RunManager(NativeRunner(model, registry), ToolCoordinator(registry))
    av = AgentVersion(
        uuid4(),
        uuid4(),
        1,
        "budget",
        (ToolBinding(version_id, "read_once"),),
    )
    run = Run(
        uuid4(),
        av.id,
        "budget",
        max_model_invocations=1,
        max_tool_attempts=4,
    )
    run.queue()
    state = RunState(run.id)
    journal = ExecutionJournal()

    with pytest.raises(RunExecutionFailedError, match="BUDGET_EXCEEDED"):
        await manager.execute(
            run=run,
            run_state=state,
            agent_version=av,
            recorder=journal,
        )

    assert run.status is RunStatus.FAILED
    assert state.model_invocations_used == 1
    assert state.tool_attempts_used == 1
    assert len(journal.model_invocations) == 1
    assert len(model.requests) == 1


@pytest.mark.asyncio
async def test_exhausted_tool_budget_discards_model_result_before_tool_call() -> None:
    version_id = uuid4()
    registry = InMemoryToolRegistry(
        [
            FunctionTool(
                version_id=version_id,
                name="blocked_read",
                description="blocked by durable budget",
                input_schema={"type": "object"},
                func=lambda: {"should": "not execute"},
            )
        ]
    )
    model = ScriptedFakeModel([ToolStep("blocked_read", {})])
    manager = RunManager(NativeRunner(model, registry), ToolCoordinator(registry))
    av = AgentVersion(
        uuid4(),
        uuid4(),
        1,
        "budget",
        (ToolBinding(version_id, "blocked_read"),),
    )
    run = Run(
        uuid4(),
        av.id,
        "tool budget",
        max_model_invocations=4,
        max_tool_attempts=1,
    )
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

    assert run.status is RunStatus.FAILED
    assert state.model_invocations_used == 1
    assert state.tool_attempts_used == 1
    assert journal.proposals == []
    assert journal.tool_calls == []
    assert EventType.MODEL_RESULT_DISCARDED in [event.type for event in journal.events]


@pytest.mark.asyncio
async def test_model_result_after_deadline_is_discarded_for_progression() -> None:
    run_holder: dict[str, Run] = {}

    scripted = ScriptedFakeModel([FinalStep("too late")])

    class DeadlineCrossingModel:
        async def invoke(self, request):
            run_holder["run"].deadline_at = utcnow() - timedelta(seconds=1)
            return await scripted.invoke(request)

    registry = InMemoryToolRegistry([])
    manager = RunManager(
        NativeRunner(DeadlineCrossingModel(), registry),
        ToolCoordinator(registry),
    )
    av = AgentVersion(uuid4(), uuid4(), 1, "deadline")
    run = Run(uuid4(), av.id, "deadline")
    run_holder["run"] = run
    run.queue()
    journal = ExecutionJournal()

    with pytest.raises(RunExecutionFailedError, match="DEADLINE_EXCEEDED"):
        await manager.execute(
            run=run,
            run_state=RunState(run.id),
            agent_version=av,
            recorder=journal,
        )

    assert run.status is RunStatus.FAILED
    assert all(message.role.value != "ASSISTANT" for message in journal.messages)
    assert EventType.MODEL_RESULT_DISCARDED in [event.type for event in journal.events]


@pytest.mark.asyncio
async def test_cooperative_yield_requeues_and_resumes_without_failure() -> None:
    version_id = uuid4()
    registry = InMemoryToolRegistry(
        [
            FunctionTool(
                version_id=version_id,
                name="yielding_read",
                description="yield after this read",
                input_schema={"type": "object"},
                func=lambda: {"ok": True},
            )
        ]
    )
    model = ScriptedFakeModel(
        [
            ToolStep("yielding_read", {}),
            FinalStep("completed after yield"),
        ]
    )
    manager = RunManager(
        NativeRunner(model, registry),
        ToolCoordinator(registry),
        max_progression_steps_per_claim=1,
    )
    av = AgentVersion(
        uuid4(),
        uuid4(),
        1,
        "yield",
        (ToolBinding(version_id, "yielding_read"),),
    )
    run = Run(uuid4(), av.id, "yield")
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
    assert run.queue_reason is QueueReason.YIELD
    assert EventType.RUN_YIELDED in [event.type for event in journal.events]

    second = await manager.execute(
        run=run,
        run_state=state,
        agent_version=av,
        recorder=journal,
    )

    assert second == "completed after yield"
    assert run.status is RunStatus.COMPLETED
    assert state.model_invocations_used == 2
    assert state.tool_attempts_used == 1



@pytest.mark.asyncio
async def test_denied_tool_result_after_deadline_is_discarded_not_persisted() -> None:
    run_holder: dict[str, Run] = {}
    scripted = ScriptedFakeModel([ToolStep("unbound_tool", {"id": "c1"})])

    class DeadlineCrossingModel:
        async def invoke(self, request):
            run_holder["run"].deadline_at = utcnow() - timedelta(seconds=1)
            return await scripted.invoke(request)

    registry = InMemoryToolRegistry([])
    manager = RunManager(
        NativeRunner(DeadlineCrossingModel(), registry),
        ToolCoordinator(registry),
    )
    av = AgentVersion(uuid4(), uuid4(), 1, "deadline denial")
    run = Run(uuid4(), av.id, "deadline denial")
    run_holder["run"] = run
    run.queue()
    journal = ExecutionJournal()

    with pytest.raises(RunExecutionFailedError, match="DEADLINE_EXCEEDED"):
        await manager.execute(
            run=run,
            run_state=RunState(run.id),
            agent_version=av,
            recorder=journal,
        )

    assert run.status is RunStatus.FAILED
    assert journal.proposals == []
    assert journal.tool_calls == []
    assert EventType.TOOL_DENIED not in [event.type for event in journal.events]
    assert EventType.MODEL_RESULT_DISCARDED in [event.type for event in journal.events]
