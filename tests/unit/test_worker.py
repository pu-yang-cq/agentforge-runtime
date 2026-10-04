from uuid import uuid4

import pytest

from agentforge.application.errors import StaleExecutorError
from agentforge.application.worker import CoreWorker
from agentforge.domain.enums import RunStatus
from agentforge.domain.models import AgentVersion, Run, RunState
from agentforge.runtime.fake_model import FinalStep, ScriptedFakeModel
from agentforge.runtime.tools import InMemoryToolRegistry


class FakeRuntimeStore:
    def __init__(self, run: Run, agent_version: AgentVersion) -> None:
        self.run = run
        self.agent_version = agent_version
        self.claimed = False

    async def claim_next_run(self, *, worker_id: str, lease_seconds: int):
        if self.claimed:
            return None
        self.claimed = True
        return self.run

    async def renew_lease(self, **kwargs):
        return True

    async def load_agent_version(self, agent_version_id):
        return self.agent_version

    async def load_run_state(self, run_id):
        return RunState(run_id)

    async def create_run(self, **kwargs):
        raise NotImplementedError

    async def get_run(self, run_id):
        return self.run


class AlwaysStaleRecorder:
    def __init__(self, *args, **kwargs) -> None:
        pass

    async def list_messages(self, run_id):
        raise StaleExecutorError("ownership lost")


@pytest.mark.asyncio
async def test_worker_treats_stale_executor_as_ownership_loss_not_process_failure() -> None:
    agent_version = AgentVersion(uuid4(), uuid4(), 1, "finish")
    run = Run(
        uuid4(),
        agent_version.id,
        "hello",
        status=RunStatus.RUNNING,
        execution_generation=3,
        owner_worker_id="worker-a",
    )
    store = FakeRuntimeStore(run, agent_version)
    worker = CoreWorker(
        runtime_store=store,
        recorder_factory=lambda **_: AlwaysStaleRecorder(),
        tool_registry=InMemoryToolRegistry([]),
        model_factory=lambda _: ScriptedFakeModel([FinalStep("done")]),
        worker_id="worker-a",
        lease_seconds=30,
    )

    assert await worker.run_once() is True
