import asyncio

from agentforge.application.worker import CoreWorker
from agentforge.config import Settings
from agentforge.demo import build_demo_model, build_demo_registry
from agentforge.infrastructure.db.execution_recorder import PostgresExecutionRecorderFactory
from agentforge.infrastructure.db.runtime_store import PostgresRuntimeStore
from agentforge.infrastructure.db.session import create_engine, create_session_factory


async def run_forever() -> None:
    settings = Settings()
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    store = PostgresRuntimeStore(session_factory)
    worker = CoreWorker(
        runtime_store=store,
        recorder_factory=PostgresExecutionRecorderFactory(session_factory),
        tool_registry=build_demo_registry(),
        model_factory=build_demo_model,
        worker_id=settings.worker_id,
        lease_seconds=settings.worker_lease_seconds,
    )
    try:
        while True:
            worked = await worker.run_once()
            if not worked:
                await asyncio.sleep(settings.worker_idle_sleep_seconds)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_forever())
