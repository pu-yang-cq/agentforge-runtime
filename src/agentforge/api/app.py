from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, status

from agentforge.api.schemas import (
    ActionResolutionCreate,
    ActionResolutionResultView,
    ActionResolutionView,
    RunCreate,
    RunView,
)
from agentforge.application.errors import (
    ActionResolutionConflictError,
    IdempotencyConflictError,
)
from agentforge.application.ports import RuntimeStore
from agentforge.domain.actions import ActionResolution
from agentforge.domain.models import Run


def _run_view(run: Run) -> RunView:
    return RunView(
        id=run.id,
        agent_version_id=run.agent_version_id,
        status=run.status,
        final_output=run.final_output,
        failure_reason=run.failure_reason,
        cancel_requested=run.cancel_requested,
        created_at=run.created_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
    )


def _resolution_view(resolution: ActionResolution) -> ActionResolutionView:
    return ActionResolutionView(
        id=resolution.id,
        action_id=resolution.action_id,
        outcome=resolution.outcome,
        evidence=resolution.evidence,
        reason=resolution.reason,
        resolver_identity=resolution.resolver_identity,
        created_at=resolution.created_at,
    )


def create_app(store: RuntimeStore) -> FastAPI:
    app = FastAPI(title="AgentForge", version="0.1.0")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/runs", response_model=RunView, status_code=status.HTTP_201_CREATED)
    async def create_run(
        request: RunCreate,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=8, max_length=200)
        ],
    ) -> RunView:
        try:
            run = await store.create_run(
                agent_version_id=request.agent_version_id,
                input_text=request.input,
                idempotency_key=idempotency_key,
                principal_scope="wave1:anonymous",
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="agent version not found") from exc
        except IdempotencyConflictError as exc:
            raise HTTPException(status_code=409, detail="idempotency conflict") from exc
        return _run_view(run)

    @app.post("/v1/runs/{run_id}/cancel", response_model=RunView)
    async def cancel_run(run_id: UUID) -> RunView:
        try:
            run = await store.cancel_run(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        return _run_view(run)

    @app.post(
        "/v1/runs/{run_id}/actions/{action_id}/resolve",
        response_model=ActionResolutionResultView,
    )
    async def resolve_action(
        run_id: UUID,
        action_id: UUID,
        request: ActionResolutionCreate,
    ) -> ActionResolutionResultView:
        try:
            run, resolution = await store.resolve_action(
                run_id=run_id,
                action_id=action_id,
                outcome=request.outcome,
                evidence=request.evidence,
                reason=request.reason,
                resolver_identity=request.resolver_identity,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run or action not found") from exc
        except ActionResolutionConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return ActionResolutionResultView(
            run=_run_view(run),
            resolution=_resolution_view(resolution),
        )

    @app.get("/v1/runs/{run_id}", response_model=RunView)
    async def get_run(run_id: UUID) -> RunView:
        run = await store.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        return _run_view(run)

    return app
