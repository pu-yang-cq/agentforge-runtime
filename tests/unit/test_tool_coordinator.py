from uuid import uuid4

import pytest

from agentforge.domain.models import AgentVersion, ToolBinding, ToolCall, ToolProposal
from agentforge.runtime.tool_coordinator import ToolCoordinator
from agentforge.runtime.tools import FunctionTool, InMemoryToolRegistry


@pytest.mark.asyncio
async def test_tool_call_is_executing_before_invocation_and_succeeds_after() -> None:
    version_id = uuid4()
    invoked = False

    async def read_tool(q: str):
        nonlocal invoked
        invoked = True
        return {"q": q}

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
    coordinator = ToolCoordinator(registry)
    av = AgentVersion(uuid4(), uuid4(), 1, "x", (ToolBinding(version_id, "lookup"),))
    proposal = ToolProposal.create(
        run_id=uuid4(), model_invocation_id=uuid4(), tool_name="lookup", arguments={"q": "x"}
    )

    prepared = coordinator.prepare_read(proposal=proposal, agent_version=av)
    assert prepared.call.status.value == "EXECUTING"
    assert invoked is False

    call = await coordinator.execute_prepared(prepared)
    assert invoked is True
    assert call.status.value == "SUCCEEDED"


def test_prepare_recovered_read_reuses_exact_tool_version_and_call_identity() -> None:
    version_id = uuid4()
    registry = InMemoryToolRegistry(
        [
            FunctionTool(
                version_id=version_id,
                name="lookup",
                description="lookup",
                input_schema={"type": "object"},
                func=lambda q: q,
            )
        ]
    )
    coordinator = ToolCoordinator(registry)
    av = AgentVersion(uuid4(), uuid4(), 1, "x", (ToolBinding(version_id, "lookup"),))
    proposal = ToolProposal.create(
        run_id=uuid4(), model_invocation_id=uuid4(), tool_name="lookup", arguments={"q": "x"}
    )
    call = ToolCall.from_proposal(proposal, tool_version_id=version_id)
    call.ready()
    original_id = call.id

    prepared = coordinator.prepare_recovered_read(call=call, agent_version=av)

    assert prepared.call.id == original_id
    assert prepared.call.status.value == "EXECUTING"
    assert prepared.tool.version_id == version_id


@pytest.mark.asyncio
async def test_sync_function_tool_does_not_block_event_loop() -> None:
    import asyncio
    import time

    version_id = uuid4()
    event_loop_progressed = asyncio.Event()

    def blocking_read() -> str:
        time.sleep(0.05)
        return "ok"

    async def ticker() -> None:
        await asyncio.sleep(0.01)
        event_loop_progressed.set()

    registry = InMemoryToolRegistry(
        [
            FunctionTool(
                version_id=version_id,
                name="blocking_read",
                description="blocking sync read",
                input_schema={"type": "object"},
                func=blocking_read,
            )
        ]
    )
    coordinator = ToolCoordinator(registry)
    av = AgentVersion(uuid4(), uuid4(), 1, "x", (ToolBinding(version_id, "blocking_read"),))
    proposal = ToolProposal.create(
        run_id=uuid4(),
        model_invocation_id=uuid4(),
        tool_name="blocking_read",
        arguments={},
    )
    prepared = coordinator.prepare_read(proposal=proposal, agent_version=av)
    ticker_task = asyncio.create_task(ticker())

    call = await coordinator.execute_prepared(prepared)

    assert event_loop_progressed.is_set()
    assert call.result == "ok"
    await ticker_task


@pytest.mark.asyncio
async def test_non_json_tool_result_fails_before_durable_success() -> None:
    from datetime import datetime

    version_id = uuid4()
    registry = InMemoryToolRegistry(
        [
            FunctionTool(
                version_id=version_id,
                name="bad_result",
                description="returns a Python-only object",
                input_schema={"type": "object"},
                func=lambda: datetime.now(),
            )
        ]
    )
    coordinator = ToolCoordinator(registry)
    av = AgentVersion(uuid4(), uuid4(), 1, "x", (ToolBinding(version_id, "bad_result"),))
    proposal = ToolProposal.create(
        run_id=uuid4(),
        model_invocation_id=uuid4(),
        tool_name="bad_result",
        arguments={},
    )
    prepared = coordinator.prepare_read(proposal=proposal, agent_version=av)

    with pytest.raises(TypeError):
        await coordinator.execute_prepared(prepared)

    assert prepared.call.status.value == "FAILED"
    assert prepared.call.result is None


def test_tool_result_message_content_is_canonical_json() -> None:
    from agentforge.runtime.tool_coordinator import tool_result_message_content

    assert tool_result_message_content({"b": 2, "a": 1}) == '{"a":1,"b":2}'
