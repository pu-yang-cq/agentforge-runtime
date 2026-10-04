from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from agentforge.api.app import create_app
from agentforge.domain.enums import RunStatus
from agentforge.domain.models import Run


class FakeRuntimeStore:
    def __init__(self) -> None:
        self.agent_version_id = uuid4()
        self.runs: dict[object, Run] = {}

    async def create_run(
        self, *, agent_version_id, input_text: str, idempotency_key: str, principal_scope: str
    ) -> Run:
        if agent_version_id != self.agent_version_id:
            raise KeyError(agent_version_id)
        run = Run(
            id=uuid4(),
            agent_version_id=agent_version_id,
            input_text=input_text,
            status=RunStatus.QUEUED,
            created_at=datetime.now(UTC),
        )
        self.runs[run.id] = run
        return run

    async def get_run(self, run_id):
        return self.runs.get(run_id)

    async def cancel_run(self, run_id):
        run = self.runs.get(run_id)
        if run is None:
            raise KeyError(run_id)
        run.request_cancel()
        run.cancel()
        return run

    async def claim_next_run(self, *, worker_id: str, lease_seconds: int):
        raise NotImplementedError

    async def renew_lease(
        self, *, run_id, worker_id: str, expected_generation: int, lease_seconds: int
    ):
        raise NotImplementedError

    async def load_run_state(self, run_id):
        raise NotImplementedError

    async def load_agent_version(self, agent_version_id):
        raise NotImplementedError


def test_create_and_get_run_api_contract() -> None:
    store = FakeRuntimeStore()
    client = TestClient(create_app(store))

    response = client.post(
        "/v1/runs",
        json={"agent_version_id": str(store.agent_version_id), "input": "hello"},
        headers={"Idempotency-Key": "run-create-0001"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "QUEUED"
    assert "execution_generation" not in body

    fetched = client.get(f"/v1/runs/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == body["id"]


def test_create_run_requires_idempotency_key() -> None:
    store = FakeRuntimeStore()
    client = TestClient(create_app(store))
    response = client.post(
        "/v1/runs",
        json={"agent_version_id": str(store.agent_version_id), "input": "hello"},
    )
    assert response.status_code == 422


def test_cancel_run_api_contract() -> None:
    store = FakeRuntimeStore()
    client = TestClient(create_app(store))
    created = client.post(
        "/v1/runs",
        json={"agent_version_id": str(store.agent_version_id), "input": "cancel me"},
        headers={"Idempotency-Key": "run-cancel-0001"},
    ).json()

    response = client.post(f"/v1/runs/{created['id']}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"
    assert response.json()["cancel_requested"] is True
