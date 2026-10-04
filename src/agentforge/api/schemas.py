from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from agentforge.domain.enums import RunStatus


class RunCreate(BaseModel):
    agent_version_id: UUID
    input: str = Field(min_length=1, max_length=100_000)


class RunView(BaseModel):
    id: UUID
    agent_version_id: UUID
    status: RunStatus
    final_output: str | None = None
    failure_reason: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
