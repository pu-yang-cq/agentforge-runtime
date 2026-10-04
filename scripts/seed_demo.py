import asyncio

from sqlalchemy import select

from agentforge.config import Settings
from agentforge.demo import (
    DEMO_AGENT_ID,
    DEMO_AGENT_VERSION_ID,
    DEMO_TOOL_ID,
    DEMO_TOOL_VERSION_ID,
)
from agentforge.domain.enums import ToolEffectType
from agentforge.infrastructure.db.models import (
    AgentRow,
    AgentVersionRow,
    AgentVersionToolRow,
    ToolDefinitionRow,
    ToolVersionRow,
)
from agentforge.infrastructure.db.session import create_engine, create_session_factory


async def seed() -> None:
    settings = Settings()
    engine = create_engine(settings.database_url)
    sessions = create_session_factory(engine)
    try:
        async with sessions() as session, session.begin():
            existing = await session.scalar(
                select(AgentVersionRow.id).where(AgentVersionRow.id == DEMO_AGENT_VERSION_ID)
            )
            if existing is not None:
                print(f"demo already seeded: agent_version_id={DEMO_AGENT_VERSION_ID}")
                return
            session.add_all(
                [
                    AgentRow(
                        id=DEMO_AGENT_ID,
                        name="wave1-demo-agent",
                        description="Deterministic Stage 3.1 demo agent",
                    ),
                    ToolDefinitionRow(
                        id=DEMO_TOOL_ID,
                        name="echo_read",
                        description="Read-only deterministic demo tool",
                    ),
                    ToolVersionRow(
                        id=DEMO_TOOL_VERSION_ID,
                        tool_id=DEMO_TOOL_ID,
                        version_number=1,
                        input_schema={
                            "type": "object",
                            "properties": {"text": {"type": "string"}},
                            "required": ["text"],
                        },
                        effect_type=ToolEffectType.READ,
                        implementation_ref="agentforge.demo:echo_read",
                    ),
                    AgentVersionRow(
                        id=DEMO_AGENT_VERSION_ID,
                        agent_id=DEMO_AGENT_ID,
                        version_number=1,
                        instructions="Call echo_read once, then return a final answer.",
                    ),
                    AgentVersionToolRow(
                        agent_version_id=DEMO_AGENT_VERSION_ID,
                        tool_version_id=DEMO_TOOL_VERSION_ID,
                        tool_alias="echo_read",
                    ),
                ]
            )
        print(f"seeded demo agent_version_id={DEMO_AGENT_VERSION_ID}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
