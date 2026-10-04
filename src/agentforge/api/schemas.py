from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from agentforge.domain.enums import ActionResolutionOutcome, RunStatus


class RunCreate(BaseModel):
    agent_version_id: UUID
    input: str = Field(min_length=1, max_length=100_000)


class RunView(BaseModel):
    id: UUID
    agent_version_id: UUID
    status: RunStatus
    final_output: str | None = None
    failure_reason: str | None = None
    cancel_requested: bool = False
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ActionResolutionCreate(BaseModel):
    outcome: ActionResolutionOutcome
    evidence: dict[str, object] | None = None
    reason: str | None = Field(default=None, max_length=4_000)
    resolver_identity: str = Field(
        default="wave1:anonymous",
        min_length=1,
        max_length=200,
    )


class ActionResolutionView(BaseModel):
    id: UUID
    action_id: UUID
    outcome: ActionResolutionOutcome
    evidence: dict[str, object] | None = None
    reason: str | None = None
    resolver_identity: str
    created_at: datetime


class ActionResolutionResultView(BaseModel):
    run: RunView
    resolution: ActionResolutionView
