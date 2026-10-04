from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from uuid import UUID

from agentforge.application.errors import RunExecutionFailedError, StaleExecutorError
from agentforge.application.ports import (
    ExecutionRecorderFactory,
    ModelGateway,
    RuntimeStore,
    ToolRegistry,
)
from agentforge.application.run_manager import RunManager
from agentforge.runtime.native_runner import NativeRunner
from agentforge.runtime.tool_coordinator import ToolCoordinator


class CoreWorker:
    """Infrastructure-neutral Worker orchestration.

    PostgreSQL/SQLAlchemy ownership belongs to the composition root. The Worker
    only asks for an ExecutionRecorder scoped to the claimed Run generation.
    """

    def __init__(
        self,
        *,
        runtime_store: RuntimeStore,
        recorder_factory: ExecutionRecorderFactory,
        tool_registry: ToolRegistry,
        model_factory: Callable[[str], ModelGateway],
        worker_id: str,
        lease_seconds: int,
        max_progression_steps_per_claim: int = 8,
    ) -> None:
        self._runtime_store = runtime_store
        self._recorder_factory = recorder_factory
        self._tool_registry = tool_registry
        self._model_factory = model_factory
        self._worker_id = worker_id
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        if max_progression_steps_per_claim <= 0:
            raise ValueError("max_progression_steps_per_claim must be positive")
        self._lease_seconds = lease_seconds
        self._max_progression_steps_per_claim = max_progression_steps_per_claim

    async def _heartbeat(self, *, run_id: UUID, generation: int) -> None:
        interval = max(0.1, self._lease_seconds / 3)
        while True:
            await asyncio.sleep(interval)
            try:
                renewed = await self._runtime_store.renew_lease(
                    run_id=run_id,
                    worker_id=self._worker_id,
                    expected_generation=generation,
                    lease_seconds=self._lease_seconds,
                )
            except Exception:
                # Progression writes independently re-check generation + DB-time lease.
                # A heartbeat failure therefore cannot grant stale authority.
                return
            if not renewed:
                return

    async def run_once(self) -> bool:
        run = await self._runtime_store.claim_next_run(
            worker_id=self._worker_id,
            lease_seconds=self._lease_seconds,
        )
        if run is None:
            return False

        heartbeat = asyncio.create_task(
            self._heartbeat(run_id=run.id, generation=run.execution_generation)
        )
        try:
            agent_version = await self._runtime_store.load_agent_version(run.agent_version_id)
            run_state = await self._runtime_store.load_run_state(run.id)
            recorder = self._recorder_factory(
                run_id=run.id,
                generation=run.execution_generation,
            )
            manager = RunManager(
                NativeRunner(self._model_factory(run.input_text), self._tool_registry),
                ToolCoordinator(self._tool_registry),
                max_progression_steps_per_claim=self._max_progression_steps_per_claim,
            )
            try:
                await manager.execute(
                    run=run,
                    run_state=run_state,
                    agent_version=agent_version,
                    recorder=recorder,
                )
            except RunExecutionFailedError:
                # The Run was durably marked FAILED; this is not a Worker-process failure.
                pass
            except StaleExecutorError:
                # Lease/generation authority was lost. Do not convert ownership loss into
                # a business failure; a later owner will recover the durable Run.
                pass
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat
        return True
