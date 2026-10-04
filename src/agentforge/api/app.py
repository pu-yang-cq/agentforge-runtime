from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, status

from agentforge.api.schemas import RunCreate, RunView
from agentforge.application.errors import IdempotencyConflictError
from agentforge.application.ports import RuntimeStore
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

    @app.get("/v1/runs/{run_id}", response_model=RunView)
    async def get_run(run_id: UUID) -> RunView:
        run = await store.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        return _run_view(run)

    return app
