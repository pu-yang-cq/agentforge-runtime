from __future__ import annotations

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
