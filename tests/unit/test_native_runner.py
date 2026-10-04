from uuid import uuid4

import pytest

from agentforge.domain.model_contract import ModelMessage
from agentforge.domain.models import AgentVersion, ToolBinding
from agentforge.runtime.fake_model import FinalStep, ScriptedFakeModel, ToolStep
from agentforge.runtime.native_runner import FinalDecision, NativeRunner, ToolDecision
from agentforge.runtime.tools import FunctionTool, InMemoryToolRegistry


@pytest.mark.asyncio
async def test_native_runner_returns_tool_proposal_then_final() -> None:
    version_id = uuid4()
    model = ScriptedFakeModel([ToolStep("lookup", {"q": "x"}), FinalStep("finished")])
    registry = InMemoryToolRegistry(
        [
            FunctionTool(
                version_id=version_id,
                name="lookup",
                description="lookup data",
                input_schema={"type": "object"},
                func=lambda q: {"q": q},
            )
        ]
    )
    runner = NativeRunner(model, registry)
    av = AgentVersion(uuid4(), uuid4(), 1, "be useful", (ToolBinding(version_id, "lookup"),))
    run_id = uuid4()

    invocation_1 = uuid4()
    d1 = await runner.decide(
        invocation_id=invocation_1,
        run_id=run_id,
        agent_version=av,
        messages=(ModelMessage("user", "do it"),),
    )
    assert isinstance(d1, ToolDecision)
    assert d1.proposal.tool_name == "lookup"
    assert d1.proposal.model_invocation_id == invocation_1

    invocation_2 = uuid4()
    d2 = await runner.decide(
        invocation_id=invocation_2,
        run_id=run_id,
        agent_version=av,
        messages=(ModelMessage("user", "do it"),),
    )
    assert isinstance(d2, FinalDecision)
    assert d2.text == "finished"
    assert d2.model_invocation_id == invocation_2
