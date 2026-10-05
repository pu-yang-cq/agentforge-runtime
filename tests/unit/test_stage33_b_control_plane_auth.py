from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from agentforge.api.app import create_app
from agentforge.domain.actions import ActionResolution
from agentforge.domain.enums import ActionResolutionOutcome, PrincipalType, RunStatus
from agentforge.domain.governance import PrincipalContext
from agentforge.domain.models import Run


@dataclass(frozen=True, slots=True)
class TrustedResolver:
    principal: PrincipalContext
    trusted_for_governed: bool = True

    def resolve(self) -> PrincipalContext:
        return self.principal


@dataclass(frozen=True, slots=True)
class UntrustedResolver:
    principal: PrincipalContext
    trusted_for_governed: bool = False

    def resolve(self) -> PrincipalContext:
        return self.principal


class FakeRuntimeStore:
    def __init__(self) -> None:
        self.agent_version_id = uuid4()
        self.runs: dict[object, Run] = {}
        self.last_resolution_identity: str | None = None

    async def create_run(
        self,
        *,
        agent_version_id,
        input_text: str,
        idempotency_key: str,
        principal_scope: str,
        principal: PrincipalContext | None = None,
    ) -> Run:
        if agent_version_id != self.agent_version_id:
            raise KeyError(agent_version_id)
        run = Run(
            id=uuid4(),
            agent_version_id=agent_version_id,
            input_text=input_text,
            status=RunStatus.QUEUED,
            created_at=datetime.now(UTC),
            policy_version_id=uuid4() if principal is not None else None,
            requester_principal_id=None if principal is None else principal.principal_id,
            requester_principal_type=None if principal is None else principal.principal_type,
            requester_roles=None if principal is None else principal.roles,
            requester_scope=None if principal is None else principal.principal_scope,
            requester_authn_source=None if principal is None else principal.authn_source,
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

    async def resolve_action(
        self,
        *,
        run_id,
        action_id,
        outcome,
        evidence,
        reason,
        resolver_identity,
    ):
        run = self.runs.get(run_id)
        if run is None:
            raise KeyError(run_id)
        self.last_resolution_identity = resolver_identity
        return run, ActionResolution(
            id=uuid4(),
            action_id=action_id,
            outcome=outcome,
            evidence=evidence,
            reason=reason,
            resolver_identity=resolver_identity,
        )


def _principal(
    principal_id: str,
    *,
    scope: str = "tenant-a",
    roles: tuple[str, ...] = (),
) -> PrincipalContext:
    return PrincipalContext(
        principal_id=principal_id,
        principal_type=PrincipalType.USER,
        roles=roles,
        principal_scope=scope,
        authn_source="test-oidc",
    )


def _governed_run(
    store: FakeRuntimeStore,
    *,
    requester: str = "owner",
    scope: str = "tenant-a",
) -> Run:
    run = Run(
        id=uuid4(),
        agent_version_id=store.agent_version_id,
        input_text="existing",
        status=RunStatus.QUEUED,
        policy_version_id=uuid4(),
        requester_principal_id=requester,
        requester_principal_type=PrincipalType.USER,
        requester_roles=("runtime:run:create",),
        requester_scope=scope,
        requester_authn_source="test-oidc",
    )
    store.runs[run.id] = run
    return run


def test_governed_create_requires_runtime_run_create_and_persists_trusted_principal() -> None:
    store = FakeRuntimeStore()
    denied = TestClient(create_app(store, TrustedResolver(_principal("user-no-role"))))
    response = denied.post(
        "/v1/runs",
        json={"agent_version_id": str(store.agent_version_id), "input": "hello"},
        headers={"Idempotency-Key": "governed-create-denied"},
    )
    assert response.status_code == 403

    allowed = TestClient(
        create_app(
            store,
            TrustedResolver(
                _principal("owner", roles=("runtime:run:create",)),
            ),
        )
    )
    response = allowed.post(
        "/v1/runs",
        json={"agent_version_id": str(store.agent_version_id), "input": "hello"},
        headers={"Idempotency-Key": "governed-create-allow"},
    )
    assert response.status_code == 201
    run = store.runs[next(reversed(store.runs))]
    assert run.requester_principal_id == "owner"
    assert run.requester_scope == "tenant-a"


def test_untrusted_resolver_cannot_enter_governed_control_plane() -> None:
    store = FakeRuntimeStore()
    client = TestClient(
        create_app(
            store,
            UntrustedResolver(
                _principal("legacy", roles=("runtime:run:create",)),
            ),
        )
    )
    response = client.post(
        "/v1/runs",
        json={"agent_version_id": str(store.agent_version_id), "input": "hello"},
        headers={"Idempotency-Key": "untrusted-resolver"},
    )
    assert response.status_code == 403


def test_governed_get_hides_cross_scope_and_requires_read_any_for_non_requester() -> None:
    store = FakeRuntimeStore()
    run = _governed_run(store)

    cross_scope = TestClient(
        create_app(
            store,
            TrustedResolver(
                _principal("admin", scope="tenant-b", roles=("runtime:run:read:any",)),
            ),
        )
    )
    assert cross_scope.get(f"/v1/runs/{run.id}").status_code == 404

    same_scope_no_role = TestClient(
        create_app(store, TrustedResolver(_principal("other")))
    )
    assert same_scope_no_role.get(f"/v1/runs/{run.id}").status_code == 403

    owner = TestClient(create_app(store, TrustedResolver(_principal("owner"))))
    assert owner.get(f"/v1/runs/{run.id}").status_code == 200

    same_scope_admin = TestClient(
        create_app(
            store,
            TrustedResolver(
                _principal("admin", roles=("runtime:run:read:any",)),
            ),
        )
    )
    assert same_scope_admin.get(f"/v1/runs/{run.id}").status_code == 200


def test_governed_cancel_requester_or_same_scope_cancel_any_only() -> None:
    store = FakeRuntimeStore()
    denied_run = _governed_run(store)
    denied = TestClient(create_app(store, TrustedResolver(_principal("other"))))
    assert denied.post(f"/v1/runs/{denied_run.id}/cancel").status_code == 403

    admin_run = _governed_run(store)
    admin = TestClient(
        create_app(
            store,
            TrustedResolver(
                _principal("admin", roles=("runtime:cancel:any",)),
            ),
        )
    )
    response = admin.post(f"/v1/runs/{admin_run.id}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"

    cross_run = _governed_run(store)
    cross = TestClient(
        create_app(
            store,
            TrustedResolver(
                _principal("admin", scope="tenant-b", roles=("runtime:cancel:any",)),
            ),
        )
    )
    assert cross.post(f"/v1/runs/{cross_run.id}/cancel").status_code == 404


def test_governed_action_resolution_uses_trusted_identity_not_body_identity() -> None:
    store = FakeRuntimeStore()
    run = _governed_run(store)
    client = TestClient(
        create_app(
            store,
            TrustedResolver(
                _principal("trusted-operator", roles=("runtime:resolve_action",)),
            ),
        )
    )
    response = client.post(
        f"/v1/runs/{run.id}/actions/{uuid4()}/resolve",
        json={
            "outcome": ActionResolutionOutcome.SUCCEEDED.value,
            "evidence": {"ticket": "T-1"},
            "reason": "verified",
            "resolver_identity": "forged-body-identity",
        },
    )
    assert response.status_code == 200
    assert store.last_resolution_identity == "trusted-operator"
    assert response.json()["resolution"]["resolver_identity"] == "trusted-operator"
