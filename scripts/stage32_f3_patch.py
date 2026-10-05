from pathlib import Path
import json

def append_once(path: str, marker: str, block: str) -> None:
    p=Path(path)
    text=p.read_text()
    if marker in text:
        raise SystemExit(f"{path}: marker already present: {marker}")
    p.write_text(text+block)

matrix = {
  "version": 1,
  "windows": [
    {
      "id": 1,
      "barrier": "before_action_preparation_commit",
      "pytest_nodes": [
        "tests/integration/test_postgres_runtime.py::test_side_effect_preparation_stale_lease_creates_no_intent"
      ],
      "safety": "No ActionSnapshot, ExternalAction, ToolCall, or external effect survives a rejected pre-intent commit."
    },
    {
      "id": 2,
      "barrier": "after_ready_commit",
      "pytest_nodes": [
        "tests/integration/test_postgres_runtime.py::test_ready_action_recovery_uses_same_operation_id_without_model_reproposal"
      ],
      "safety": "READY recovery reuses durable operation identity and does not re-propose through the model."
    },
    {
      "id": 3,
      "barrier": "before_action_commit",
      "pytest_nodes": [
        "tests/integration/test_postgres_runtime.py::test_action_commit_deadline_block_aborts_ready_action_without_external_call"
      ],
      "safety": "Pre-commit business stop produces zero physical attempts and zero external effects."
    },
    {
      "id": 4,
      "barrier": "after_action_commit_before_external_call",
      "pytest_nodes": [
        "tests/integration/test_postgres_runtime.py::test_f3_crash_post_commit_pre_call_no_duplicate_effect"
      ],
      "safety": "Orphan STARTED becomes UNKNOWN; authoritative NOT_EXECUTED permits one safe retry with one business effect."
    },
    {
      "id": 5,
      "barrier": "during_external_call",
      "pytest_nodes": [
        "tests/integration/test_postgres_runtime.py::test_f3_crash_during_external_call_recovers_without_duplicate_effect"
      ],
      "safety": "A transport-level duplicate request after takeover may occur only after reconciliation proves NOT_EXECUTED; effect_count remains one."
    },
    {
      "id": 6,
      "barrier": "after_external_effect_before_response",
      "pytest_nodes": [
        "tests/integration/test_postgres_runtime.py::test_f3_crash_after_external_effect_before_response_reconciles_without_replay"
      ],
      "safety": "Committed external truth is reconciled to SUCCEEDED and the physical side effect is never replayed."
    },
    {
      "id": 7,
      "barrier": "after_response_before_db_result_commit",
      "pytest_nodes": [
        "tests/integration/test_postgres_runtime.py::test_f3_crash_after_response_before_result_commit_reconciles_without_replay"
      ],
      "safety": "Lost local result commit becomes UNKNOWN on takeover; reconciliation preserves the single external effect."
    },
    {
      "id": 8,
      "barrier": "during_result_commit",
      "pytest_nodes": [
        "tests/integration/test_postgres_runtime.py::test_e3_result_wins_then_cancellation_does_not_rollback_succeeded_action"
      ],
      "safety": "A durable successful business result remains authoritative across cancellation/race boundaries."
    },
    {
      "id": 9,
      "barrier": "during_reconciliation_request",
      "pytest_nodes": [
        "tests/integration/test_postgres_runtime.py::test_orphaned_reconciliation_attempt_closes_failed_and_preserves_truth"
      ],
      "safety": "Orphaned reconciliation closes FAILED(LEASE_LOST) without changing ExternalAction business truth."
    },
    {
      "id": 10,
      "barrier": "after_reconciliation_response_before_result_commit",
      "pytest_nodes": [
        "tests/integration/test_postgres_runtime.py::test_e3_cancellation_wins_reconciliation_success_truth_without_continuation"
      ],
      "safety": "Returned reconciliation truth may update Action truth while cancellation still fences continuation."
    },
    {
      "id": 11,
      "barrier": "during_durable_retry_yield",
      "pytest_nodes": [
        "tests/integration/test_postgres_runtime.py::test_side_effect_safe_retry_reuses_action_and_operation_id_across_claims"
      ],
      "safety": "RETRY is durable scheduling with stable Action identity and monotonic physical attempt number."
    },
    {
      "id": 12,
      "barrier": "during_cancellation_model_result_race",
      "pytest_nodes": [
        "tests/integration/test_postgres_runtime.py::test_e3_cancel_wins_side_effect_result_records_truth_and_fences_worker"
      ],
      "safety": "Cancellation fences new progression while late physical truth is still durably recorded."
    }
  ]
}
Path("docs/acceptance/stage3.2-f3-recovery-matrix.json").write_text(
    json.dumps(matrix, indent=2) + "\n"
)

contract = r'''from __future__ import annotations

import ast
import json
from pathlib import Path

from agentforge.testing.fake_external_system import CrashBarrierPoint


def test_f3_recovery_matrix_covers_exact_frozen_crash_windows_and_real_tests() -> None:
    matrix = json.loads(
        Path("docs/acceptance/stage3.2-f3-recovery-matrix.json").read_text()
    )
    windows = matrix["windows"]
    assert [item["id"] for item in windows] == list(range(1, 13))
    assert {item["barrier"] for item in windows} == {
        point.value for point in CrashBarrierPoint
    }

    functions_by_file: dict[str, set[str]] = {}
    for item in windows:
        assert item["pytest_nodes"]
        assert item["safety"]
        for node in item["pytest_nodes"]:
            file_name, function_name = node.split("::", 1)
            path = Path(file_name)
            assert path.exists(), node
            if file_name not in functions_by_file:
                tree = ast.parse(path.read_text())
                functions_by_file[file_name] = {
                    n.name
                    for n in ast.walk(tree)
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                }
            assert function_name in functions_by_file[file_name], node


def test_f3_matrix_has_effect_count_assertions_for_ambiguous_external_windows() -> None:
    source = Path("tests/integration/test_postgres_runtime.py").read_text()
    tree = ast.parse(source)
    helper_names = {
        "_f3_assert_pre_effect_crash_recovery",
        "_f3_assert_post_effect_crash_recovery",
    }
    helpers = {
        n.name: (ast.get_source_segment(source, n) or "")
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name in helper_names
    }
    assert set(helpers) == helper_names
    for helper_text in helpers.values():
        assert "effect_count" in helper_text
        assert "reconciliation_query_count" in helper_text
        assert "duplicate_request_count" in helper_text
'''

Path("tests/unit/test_stage32_f3_recovery_matrix.py").write_text(contract)

integration = r'''


async def _f3_build_barrier_run(
    sessions,
    *,
    system,
    tool_name: str,
    idempotency_key: str,
):
    from agentforge.domain.enums import ReconciliationMode

    side_tool_id = uuid4()
    side_version_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(ToolDefinitionRow(id=side_tool_id, name=tool_name, description="F3 side effect"))
        await session.flush()
        session.add(
            ToolVersionRow(
                id=side_version_id,
                tool_id=side_tool_id,
                version_number=1,
                input_schema={"type": "object"},
                effect_type=ToolEffectType.EXTERNAL_SIDE_EFFECT,
                implementation_ref=f"tests:{tool_name}",
                allow_no_approval_execution=True,
                idempotency_supported=False,
                reconciliation_mode=ReconciliationMode.AUTHORITATIVE,
                side_effect_retry_max_attempts=2,
                side_effect_retry_initial_backoff_seconds=0,
                side_effect_retry_max_backoff_seconds=0,
                reconciliation_max_attempts=2,
                reconciliation_initial_backoff_seconds=0,
                reconciliation_max_backoff_seconds=0,
            )
        )
        await session.flush()
        session.add(
            AgentVersionToolRow(
                agent_version_id=DEMO_AGENT_VERSION_ID,
                tool_version_id=side_version_id,
                tool_alias=tool_name,
            )
        )

    registry = InMemoryToolRegistry(
        [
            FunctionTool(
                version_id=DEMO_TOOL_VERSION_ID,
                name="echo_read",
                description="read",
                input_schema={"type": "object"},
                func=lambda text: {"echo": text},
            ),
            SideEffectFunctionTool(
                version_id=side_version_id,
                name=tool_name,
                description="F3 observable side effect",
                input_schema={"type": "object"},
                func=system.invoke,
                reconcile_func=system.reconcile,
            ),
        ]
    )
    store = PostgresRuntimeStore(sessions)
    created = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text=f"F3 barrier {tool_name}",
        idempotency_key=idempotency_key,
        principal_scope="test-user",
    )
    claimed = await store.claim_next_run(worker_id=f"{tool_name}-a", lease_seconds=30)
    assert claimed is not None
    version = await store.load_agent_version(DEMO_AGENT_VERSION_ID)
    manager = RunManager(
        NativeRunner(
            ScriptedFakeModel(
                [
                    ToolStep(tool_name, {"value": "same logical action"}),
                    FinalStep("done"),
                ]
            ),
            registry,
        ),
        ToolCoordinator(registry),
    )
    recorder = PostgresExecutionRecorder(
        sessions,
        run_id=created.id,
        generation=claimed.execution_generation,
    )
    return store, created, claimed, version, registry, manager, recorder


async def _f3_expire_and_claim(sessions, store, run_id, *, worker_id: str):
    from datetime import UTC, datetime, timedelta

    from agentforge.infrastructure.db.models import RunRow

    async with sessions() as session, session.begin():
        row = await session.get(RunRow, run_id)
        assert row is not None
        row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    claimed = await store.claim_next_run(worker_id=worker_id, lease_seconds=30)
    assert claimed is not None
    return claimed


async def _f3_assert_pre_effect_crash_recovery(barrier_point, *, key: str, tool_name: str) -> None:
    from contextlib import suppress

    from agentforge.testing.fake_external_system import (
        CrashBarrierController,
        StatefulFakeExternalSystem,
    )

    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)
    barriers = CrashBarrierController()
    barriers.arm(barrier_point)
    system = StatefulFakeExternalSystem(barriers=barriers)
    store, created, claimed1, version, registry, manager1, recorder1 = (
        await _f3_build_barrier_run(
            sessions,
            system=system,
            tool_name=tool_name,
            idempotency_key=key,
        )
    )

    task = asyncio.create_task(
        manager1.execute(
            run=claimed1,
            run_state=await store.load_run_state(created.id),
            agent_version=version,
            recorder=recorder1,
        )
    )
    await barriers.wait_until_hit(barrier_point)
    operation = system.records()[0]
    assert operation.call_count == 1
    assert operation.effect_count == 0

    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
    barriers.clear(barrier_point)

    claimed2 = await _f3_expire_and_claim(
        sessions,
        store,
        created.id,
        worker_id=f"{tool_name}-b",
    )
    manager2 = RunManager(
        NativeRunner(ScriptedFakeModel([FinalStep("must not reason before retry")]), registry),
        ToolCoordinator(registry),
    )
    recorder2 = PostgresExecutionRecorder(
        sessions,
        run_id=created.id,
        generation=claimed2.execution_generation,
    )
    assert (
        await manager2.execute(
            run=claimed2,
            run_state=await store.load_run_state(created.id),
            agent_version=version,
            recorder=recorder2,
        )
        is None
    )
    operation = system.records()[0]
    assert operation.effect_count == 0
    assert operation.reconciliation_query_count == 1

    claimed3 = await store.claim_next_run(worker_id=f"{tool_name}-c", lease_seconds=30)
    assert claimed3 is not None
    manager3 = RunManager(
        NativeRunner(ScriptedFakeModel([FinalStep("done")]), registry),
        ToolCoordinator(registry),
    )
    recorder3 = PostgresExecutionRecorder(
        sessions,
        run_id=created.id,
        generation=claimed3.execution_generation,
    )
    assert (
        await manager3.execute(
            run=claimed3,
            run_state=await store.load_run_state(created.id),
            agent_version=version,
            recorder=recorder3,
        )
        == "done"
    )
    operation = system.records()[0]
    assert operation.call_count == 2
    assert operation.duplicate_request_count == 1
    assert operation.effect_count == 1
    assert operation.reconciliation_query_count == 1
    durable = await store.get_run(created.id)
    assert durable is not None and durable.status is RunStatus.COMPLETED
    await engine.dispose()


async def _f3_assert_post_effect_crash_recovery(
    barrier_point,
    *,
    key: str,
    tool_name: str,
) -> None:
    from contextlib import suppress

    from agentforge.testing.fake_external_system import (
        CrashBarrierController,
        StatefulFakeExternalSystem,
    )

    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)
    barriers = CrashBarrierController()
    barriers.arm(barrier_point)
    system = StatefulFakeExternalSystem(barriers=barriers)
    store, created, claimed1, version, registry, manager1, recorder1 = (
        await _f3_build_barrier_run(
            sessions,
            system=system,
            tool_name=tool_name,
            idempotency_key=key,
        )
    )

    task = asyncio.create_task(
        manager1.execute(
            run=claimed1,
            run_state=await store.load_run_state(created.id),
            agent_version=version,
            recorder=recorder1,
        )
    )
    await barriers.wait_until_hit(barrier_point)
    operation = system.records()[0]
    assert operation.call_count == 1
    assert operation.effect_count == 1

    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
    barriers.clear(barrier_point)

    claimed2 = await _f3_expire_and_claim(
        sessions,
        store,
        created.id,
        worker_id=f"{tool_name}-b",
    )
    manager2 = RunManager(
        NativeRunner(ScriptedFakeModel([FinalStep("done")]), registry),
        ToolCoordinator(registry),
    )
    recorder2 = PostgresExecutionRecorder(
        sessions,
        run_id=created.id,
        generation=claimed2.execution_generation,
    )
    assert (
        await manager2.execute(
            run=claimed2,
            run_state=await store.load_run_state(created.id),
            agent_version=version,
            recorder=recorder2,
        )
        == "done"
    )
    operation = system.records()[0]
    assert operation.call_count == 1
    assert operation.effect_count == 1
    assert operation.duplicate_request_count == 0
    assert operation.reconciliation_query_count == 1
    durable = await store.get_run(created.id)
    assert durable is not None and durable.status is RunStatus.COMPLETED
    await engine.dispose()


@pytest.mark.asyncio
async def test_f3_crash_post_commit_pre_call_no_duplicate_effect() -> None:
    from agentforge.testing.fake_external_system import CrashBarrierPoint

    await _f3_assert_pre_effect_crash_recovery(
        CrashBarrierPoint.AFTER_ACTION_COMMIT_BEFORE_EXTERNAL_CALL,
        key="f3-window-4",
        tool_name="f3_window_4",
    )


@pytest.mark.asyncio
async def test_f3_crash_during_external_call_recovers_without_duplicate_effect() -> None:
    from agentforge.testing.fake_external_system import CrashBarrierPoint

    await _f3_assert_pre_effect_crash_recovery(
        CrashBarrierPoint.DURING_EXTERNAL_CALL,
        key="f3-window-5",
        tool_name="f3_window_5",
    )


@pytest.mark.asyncio
async def test_f3_crash_after_external_effect_before_response_reconciles_without_replay() -> None:
    from agentforge.testing.fake_external_system import CrashBarrierPoint

    await _f3_assert_post_effect_crash_recovery(
        CrashBarrierPoint.AFTER_EXTERNAL_EFFECT_BEFORE_RESPONSE,
        key="f3-window-6",
        tool_name="f3_window_6",
    )


@pytest.mark.asyncio
async def test_f3_crash_after_response_before_result_commit_reconciles_without_replay() -> None:
    from agentforge.testing.fake_external_system import CrashBarrierPoint

    await _f3_assert_post_effect_crash_recovery(
        CrashBarrierPoint.AFTER_RESPONSE_BEFORE_DB_RESULT_COMMIT,
        key="f3-window-7",
        tool_name="f3_window_7",
    )
'''
append_once(
    "tests/integration/test_postgres_runtime.py",
    "test_f3_crash_post_commit_pre_call_no_duplicate_effect",
    integration,
)
