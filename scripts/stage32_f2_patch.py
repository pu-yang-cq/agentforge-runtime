from pathlib import Path

SUPPORT = r'''from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from agentforge.application.errors import ToolAdapterError
from agentforge.application.ports import (
    ReconciliationInvocation,
    ReconciliationResult,
    SideEffectInvocation,
)
from agentforge.domain.enums import ReconciliationBusinessResult


class CrashBarrierPoint(StrEnum):
    BEFORE_ACTION_PREPARATION_COMMIT = "before_action_preparation_commit"
    AFTER_READY_COMMIT = "after_ready_commit"
    BEFORE_ACTION_COMMIT = "before_action_commit"
    AFTER_ACTION_COMMIT_BEFORE_EXTERNAL_CALL = "after_action_commit_before_external_call"
    DURING_EXTERNAL_CALL = "during_external_call"
    AFTER_EXTERNAL_EFFECT_BEFORE_RESPONSE = "after_external_effect_before_response"
    AFTER_RESPONSE_BEFORE_DB_RESULT_COMMIT = "after_response_before_db_result_commit"
    DURING_RESULT_COMMIT = "during_result_commit"
    DURING_RECONCILIATION_REQUEST = "during_reconciliation_request"
    AFTER_RECONCILIATION_RESPONSE_BEFORE_RESULT_COMMIT = (
        "after_reconciliation_response_before_result_commit"
    )
    DURING_DURABLE_RETRY_YIELD = "during_durable_retry_yield"
    DURING_CANCELLATION_MODEL_RESULT_RACE = "during_cancellation_model_result_race"


class SideEffectScenario(StrEnum):
    SUCCESS = "SUCCESS"
    DEFINITE_NO_EFFECT = "DEFINITE_NO_EFFECT"
    AMBIGUOUS_TIMEOUT = "AMBIGUOUS_TIMEOUT"
    COMMIT_RESPONSE_LOSS = "COMMIT_RESPONSE_LOSS"
    DELAYED_SUCCESS = "DELAYED_SUCCESS"


@dataclass(slots=True)
class ExternalOperationRecord:
    operation_id: UUID
    external_resource_id: str | None = None
    call_count: int = 0
    effect_count: int = 0
    duplicate_request_count: int = 0
    reconciliation_query_count: int = 0


class CrashBarrierController:
    """Deterministic async barriers shared by F2/F3 crash tests.

    Unarmed barriers are no-ops. An armed barrier exposes a hit event and blocks
    until explicitly released by the test driver.
    """

    def __init__(self) -> None:
        self._armed: dict[CrashBarrierPoint, tuple[asyncio.Event, asyncio.Event]] = {}

    def arm(self, point: CrashBarrierPoint) -> None:
        if point in self._armed:
            raise ValueError(f"barrier already armed: {point}")
        self._armed[point] = (asyncio.Event(), asyncio.Event())

    async def hit(self, point: CrashBarrierPoint) -> None:
        pair = self._armed.get(point)
        if pair is None:
            return
        hit, release = pair
        hit.set()
        await release.wait()

    async def wait_until_hit(self, point: CrashBarrierPoint) -> None:
        pair = self._armed.get(point)
        if pair is None:
            raise ValueError(f"barrier is not armed: {point}")
        await pair[0].wait()

    def release(self, point: CrashBarrierPoint) -> None:
        pair = self._armed.get(point)
        if pair is None:
            raise ValueError(f"barrier is not armed: {point}")
        pair[1].set()

    def clear(self, point: CrashBarrierPoint) -> None:
        self._armed.pop(point, None)


class StatefulFakeExternalSystem:
    """Observable deterministic external provider used only by Stage 3.2 tests.

    The ledger records business-safe evidence only. Credential references and
    resolved secret material are intentionally not stored.
    """

    def __init__(self, *, barriers: CrashBarrierController | None = None) -> None:
        self.barriers = barriers or CrashBarrierController()
        self._ledger: dict[UUID, ExternalOperationRecord] = {}
        self._side_effect_script: list[SideEffectScenario] = []
        self._reconciliation_script: list[ReconciliationBusinessResult] = []
        self._resource_sequence = 0

    def queue_side_effect(self, *scenarios: SideEffectScenario) -> None:
        self._side_effect_script.extend(scenarios)

    def queue_reconciliation(self, *outcomes: ReconciliationBusinessResult) -> None:
        self._reconciliation_script.extend(outcomes)

    def record(self, operation_id: UUID) -> ExternalOperationRecord:
        try:
            return self._ledger[operation_id]
        except KeyError as exc:
            raise KeyError(f"operation not observed: {operation_id}") from exc

    def records(self) -> tuple[ExternalOperationRecord, ...]:
        return tuple(self._ledger[key] for key in sorted(self._ledger, key=str))

    def _get_or_create(self, operation_id: UUID) -> ExternalOperationRecord:
        record = self._ledger.get(operation_id)
        if record is None:
            record = ExternalOperationRecord(operation_id=operation_id)
            self._ledger[operation_id] = record
        return record

    def _commit_effect(
        self,
        record: ExternalOperationRecord,
        *,
        idempotency_key: str | None,
    ) -> str:
        if record.effect_count > 0 and idempotency_key is not None:
            assert record.external_resource_id is not None
            return record.external_resource_id
        self._resource_sequence += 1
        record.effect_count += 1
        record.external_resource_id = f"fake-resource-{self._resource_sequence}"
        return record.external_resource_id

    async def invoke(self, invocation: SideEffectInvocation) -> dict[str, object]:
        record = self._get_or_create(invocation.operation_id)
        record.call_count += 1
        if record.call_count > 1:
            record.duplicate_request_count += 1

        await self.barriers.hit(CrashBarrierPoint.AFTER_ACTION_COMMIT_BEFORE_EXTERNAL_CALL)
        await self.barriers.hit(CrashBarrierPoint.DURING_EXTERNAL_CALL)

        scenario = (
            self._side_effect_script.pop(0)
            if self._side_effect_script
            else SideEffectScenario.SUCCESS
        )
        if scenario is SideEffectScenario.DEFINITE_NO_EFFECT:
            raise ToolAdapterError(
                "fake provider rejected request before any business effect",
                error_class="FAKE_PRE_EFFECT",
                definite_not_executed=True,
            )
        if scenario is SideEffectScenario.AMBIGUOUS_TIMEOUT:
            raise ToolAdapterError(
                "fake provider transport timed out with ambiguous external truth",
                error_class="FAKE_TIMEOUT",
                definite_not_executed=False,
            )

        resource_id = self._commit_effect(
            record,
            idempotency_key=invocation.idempotency_key,
        )
        await self.barriers.hit(CrashBarrierPoint.AFTER_EXTERNAL_EFFECT_BEFORE_RESPONSE)

        if scenario is SideEffectScenario.COMMIT_RESPONSE_LOSS:
            raise ToolAdapterError(
                "fake provider committed effect but response was lost",
                error_class="FAKE_RESPONSE_LOST",
                definite_not_executed=False,
            )

        if scenario is SideEffectScenario.DELAYED_SUCCESS:
            # The same post-effect barrier supplies deterministic delay control.
            await asyncio.sleep(0)

        result: dict[str, object] = {
            "operation_id": str(invocation.operation_id),
            "external_resource_id": resource_id,
        }
        await self.barriers.hit(CrashBarrierPoint.AFTER_RESPONSE_BEFORE_DB_RESULT_COMMIT)
        return result

    async def reconcile(self, invocation: ReconciliationInvocation) -> ReconciliationResult:
        record = self._get_or_create(invocation.operation_id)
        record.reconciliation_query_count += 1
        await self.barriers.hit(CrashBarrierPoint.DURING_RECONCILIATION_REQUEST)

        if self._reconciliation_script:
            outcome = self._reconciliation_script.pop(0)
        elif record.effect_count > 0:
            outcome = ReconciliationBusinessResult.SUCCEEDED
        else:
            outcome = ReconciliationBusinessResult.NOT_EXECUTED

        evidence: dict[str, object] = {
            "operation_id": str(invocation.operation_id),
            "effect_count": record.effect_count,
        }
        if record.external_resource_id is not None:
            evidence["external_resource_id"] = record.external_resource_id

        result = ReconciliationResult(outcome=outcome, evidence=evidence)
        await self.barriers.hit(
            CrashBarrierPoint.AFTER_RECONCILIATION_RESPONSE_BEFORE_RESULT_COMMIT
        )
        return result
'''

TESTS = r'''from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from agentforge.application.errors import ToolAdapterError
from agentforge.application.ports import ReconciliationInvocation, SideEffectInvocation
from agentforge.domain.enums import ReconciliationBusinessResult
from agentforge.testing.fake_external_system import (
    CrashBarrierController,
    CrashBarrierPoint,
    SideEffectScenario,
    StatefulFakeExternalSystem,
)


def side_invocation(operation_id, *, idempotent: bool = False) -> SideEffectInvocation:
    return SideEffectInvocation(
        operation_id=operation_id,
        arguments={"ticket": "A-1"},
        credential_ref="vault://fake/ref",
        idempotency_key=str(operation_id) if idempotent else None,
    )


@pytest.mark.asyncio
async def test_fake_external_success_records_observable_ledger() -> None:
    system = StatefulFakeExternalSystem()
    operation_id = uuid4()

    result = await system.invoke(side_invocation(operation_id))
    record = system.record(operation_id)

    assert result["operation_id"] == str(operation_id)
    assert record.external_resource_id == result["external_resource_id"]
    assert record.call_count == 1
    assert record.effect_count == 1
    assert record.duplicate_request_count == 0
    assert record.reconciliation_query_count == 0


@pytest.mark.asyncio
async def test_fake_external_definite_no_effect_and_ambiguous_timeout_are_distinct() -> None:
    definite = StatefulFakeExternalSystem()
    definite.queue_side_effect(SideEffectScenario.DEFINITE_NO_EFFECT)
    operation_a = uuid4()
    with pytest.raises(ToolAdapterError) as exc_info:
        await definite.invoke(side_invocation(operation_a))
    assert exc_info.value.definite_not_executed is True
    assert definite.record(operation_a).effect_count == 0

    ambiguous = StatefulFakeExternalSystem()
    ambiguous.queue_side_effect(SideEffectScenario.AMBIGUOUS_TIMEOUT)
    operation_b = uuid4()
    with pytest.raises(ToolAdapterError) as exc_info:
        await ambiguous.invoke(side_invocation(operation_b))
    assert exc_info.value.definite_not_executed is False
    assert ambiguous.record(operation_b).effect_count == 0


@pytest.mark.asyncio
async def test_fake_external_commit_response_loss_exposes_committed_effect() -> None:
    system = StatefulFakeExternalSystem()
    system.queue_side_effect(SideEffectScenario.COMMIT_RESPONSE_LOSS)
    operation_id = uuid4()

    with pytest.raises(ToolAdapterError) as exc_info:
        await system.invoke(side_invocation(operation_id))

    record = system.record(operation_id)
    assert exc_info.value.definite_not_executed is False
    assert record.call_count == 1
    assert record.effect_count == 1
    assert record.external_resource_id is not None


@pytest.mark.asyncio
async def test_fake_external_idempotent_duplicate_does_not_duplicate_effect() -> None:
    system = StatefulFakeExternalSystem()
    operation_id = uuid4()
    invocation = side_invocation(operation_id, idempotent=True)

    first = await system.invoke(invocation)
    second = await system.invoke(invocation)
    record = system.record(operation_id)

    assert first["external_resource_id"] == second["external_resource_id"]
    assert record.call_count == 2
    assert record.effect_count == 1
    assert record.duplicate_request_count == 1


@pytest.mark.asyncio
async def test_fake_external_non_idempotent_duplicate_is_observable() -> None:
    system = StatefulFakeExternalSystem()
    operation_id = uuid4()
    invocation = side_invocation(operation_id, idempotent=False)

    await system.invoke(invocation)
    await system.invoke(invocation)
    record = system.record(operation_id)

    assert record.call_count == 2
    assert record.effect_count == 2
    assert record.duplicate_request_count == 1


@pytest.mark.asyncio
async def test_fake_external_reconciliation_is_read_only_and_counted() -> None:
    system = StatefulFakeExternalSystem()
    operation_id = uuid4()

    before = await system.reconcile(
        ReconciliationInvocation(operation_id, {"ticket": "A-1"}, "vault://fake/ref")
    )
    assert before.outcome is ReconciliationBusinessResult.NOT_EXECUTED
    assert system.record(operation_id).effect_count == 0

    await system.invoke(side_invocation(operation_id))
    system.queue_reconciliation(ReconciliationBusinessResult.UNKNOWN)
    after = await system.reconcile(
        ReconciliationInvocation(operation_id, {"ticket": "A-1"}, "vault://fake/ref")
    )
    record = system.record(operation_id)

    assert after.outcome is ReconciliationBusinessResult.UNKNOWN
    assert record.reconciliation_query_count == 2
    assert record.effect_count == 1


@pytest.mark.asyncio
async def test_fake_external_barrier_exposes_effect_commit_before_response() -> None:
    barriers = CrashBarrierController()
    barriers.arm(CrashBarrierPoint.AFTER_EXTERNAL_EFFECT_BEFORE_RESPONSE)
    system = StatefulFakeExternalSystem(barriers=barriers)
    operation_id = uuid4()

    task = asyncio.create_task(system.invoke(side_invocation(operation_id)))
    await barriers.wait_until_hit(CrashBarrierPoint.AFTER_EXTERNAL_EFFECT_BEFORE_RESPONSE)

    record = system.record(operation_id)
    assert record.call_count == 1
    assert record.effect_count == 1
    assert not task.done()

    barriers.release(CrashBarrierPoint.AFTER_EXTERNAL_EFFECT_BEFORE_RESPONSE)
    result = await task
    assert result["external_resource_id"] == record.external_resource_id


def test_fake_external_declares_all_frozen_stage32_crash_windows() -> None:
    assert set(CrashBarrierPoint) == {
        CrashBarrierPoint.BEFORE_ACTION_PREPARATION_COMMIT,
        CrashBarrierPoint.AFTER_READY_COMMIT,
        CrashBarrierPoint.BEFORE_ACTION_COMMIT,
        CrashBarrierPoint.AFTER_ACTION_COMMIT_BEFORE_EXTERNAL_CALL,
        CrashBarrierPoint.DURING_EXTERNAL_CALL,
        CrashBarrierPoint.AFTER_EXTERNAL_EFFECT_BEFORE_RESPONSE,
        CrashBarrierPoint.AFTER_RESPONSE_BEFORE_DB_RESULT_COMMIT,
        CrashBarrierPoint.DURING_RESULT_COMMIT,
        CrashBarrierPoint.DURING_RECONCILIATION_REQUEST,
        CrashBarrierPoint.AFTER_RECONCILIATION_RESPONSE_BEFORE_RESULT_COMMIT,
        CrashBarrierPoint.DURING_DURABLE_RETRY_YIELD,
        CrashBarrierPoint.DURING_CANCELLATION_MODEL_RESULT_RACE,
    }


@pytest.mark.asyncio
async def test_fake_external_ledger_never_stores_credential_reference_or_secret_material() -> None:
    system = StatefulFakeExternalSystem()
    operation_id = uuid4()
    secret = "SENTINEL-RESOLVED-SECRET-DO-NOT-PERSIST"
    invocation = SideEffectInvocation(
        operation_id=operation_id,
        arguments={"ticket": "A-1"},
        credential_ref="vault://fake/credential",
        idempotency_key=str(operation_id),
    )

    await system.invoke(invocation)
    await system.reconcile(
        ReconciliationInvocation(
            operation_id=operation_id,
            arguments={"ticket": "A-1"},
            credential_ref="vault://fake/credential",
        )
    )

    representation = repr(system.records())
    assert "vault://fake/credential" not in representation
    assert secret not in representation
'''

p=Path("src/agentforge/testing")
p.mkdir(parents=True, exist_ok=True)
(p/"__init__.py").write_text("")
(p/"fake_external_system.py").write_text(SUPPORT)
Path("tests/unit/test_fake_external_system.py").write_text(TESTS)
