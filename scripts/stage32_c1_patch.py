from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one anchor, found {count}: {old[:120]!r}")
    file.write_text(text.replace(old, new))


def append_text(path: str, marker: str, block: str) -> None:
    file = Path(path)
    text = file.read_text()
    if marker in text:
        raise SystemExit(f"{path}: marker already present: {marker}")
    file.write_text(text + block)


# ---------------------------------------------------------------------------
# Domain transitions and explicit Action Commit lifecycle events.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/domain/enums.py",
    '''    ACTION_PREPARED = "ACTION_PREPARED"
    TOOL_STARTED = "TOOL_STARTED"
''',
    '''    ACTION_PREPARED = "ACTION_PREPARED"
    ACTION_COMMITTED = "ACTION_COMMITTED"
    ACTION_SUCCEEDED = "ACTION_SUCCEEDED"
    ACTION_ABORTED = "ACTION_ABORTED"
    TOOL_STARTED = "TOOL_STARTED"
''',
)

replace_once(
    "src/agentforge/domain/actions.py",
    '''    def create(
        cls,
        *,
        run_id: UUID,
        tool_call_id: UUID,
        action_snapshot_id: UUID,
        operation_id: UUID,
    ) -> ExternalAction:
        return cls(
            id=uuid4(),
            run_id=run_id,
            tool_call_id=tool_call_id,
            action_snapshot_id=action_snapshot_id,
            operation_id=operation_id,
        )
''',
    '''    def create(
        cls,
        *,
        run_id: UUID,
        tool_call_id: UUID,
        action_snapshot_id: UUID,
        operation_id: UUID,
    ) -> ExternalAction:
        return cls(
            id=uuid4(),
            run_id=run_id,
            tool_call_id=tool_call_id,
            action_snapshot_id=action_snapshot_id,
            operation_id=operation_id,
        )

    def start(self, attempt_id: UUID) -> None:
        if self.status is not ExternalActionStatus.READY or self.current_attempt_id is not None:
            raise ValueError("external action can only execute from READY without an active attempt")
        self.status = ExternalActionStatus.EXECUTING
        self.current_attempt_id = attempt_id

    def succeed(self) -> None:
        if self.status is not ExternalActionStatus.EXECUTING or self.current_attempt_id is None:
            raise ValueError("external action can only succeed from EXECUTING")
        self.status = ExternalActionStatus.SUCCEEDED
        self.current_attempt_id = None

    def abort(self) -> None:
        if self.status is not ExternalActionStatus.READY or self.current_attempt_id is not None:
            raise ValueError("external action can only abort before Action Commit")
        self.status = ExternalActionStatus.ABORTED
''',
)

replace_once(
    "src/agentforge/domain/models.py",
    '''    def start(self) -> None:
        if self.status is not ToolCallStatus.READY:
            raise ValueError("tool call can only execute from READY")
        self.status = ToolCallStatus.EXECUTING
        self.error = None
''',
    '''    def start(self) -> None:
        if self.status is not ToolCallStatus.READY:
            raise ValueError("tool call can only execute from READY")
        self.status = ToolCallStatus.EXECUTING
        self.error = None

    def not_executed(self, reason: str) -> None:
        if self.status is not ToolCallStatus.READY:
            raise ValueError("tool call can only become NOT_EXECUTED from READY")
        self.status = ToolCallStatus.NOT_EXECUTED
        self.error = reason
''',
)

replace_once(
    "src/agentforge/domain/models.py",
    '''    finished_at: datetime | None = None

    def succeed(self, result: Any) -> None:
''',
    '''    finished_at: datetime | None = None
    external_action_id: UUID | None = None

    def succeed(self, result: Any) -> None:
''',
)

# ---------------------------------------------------------------------------
# Side-effect adapter contract. operation_id/idempotency cross the adapter edge;
# credential_ref stays opaque and no resolved secret enters durable runtime.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/application/ports.py",
    '''from typing import Any, Protocol
''',
    '''from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable
''',
)

replace_once(
    "src/agentforge/application/ports.py",
    '''class ToolRegistry(Protocol):
''',
    '''@dataclass(frozen=True, slots=True)
class SideEffectInvocation:
    operation_id: UUID
    arguments: dict[str, Any]
    credential_ref: str | None
    idempotency_key: str | None


@runtime_checkable
class SideEffectTool(Protocol):
    @property
    def version_id(self) -> UUID: ...

    @property
    def spec(self) -> ModelToolSpec: ...

    async def invoke_side_effect(self, invocation: SideEffectInvocation) -> Any: ...


class ToolRegistry(Protocol):
''',
)

replace_once(
    "src/agentforge/application/ports.py",
    '''    async def load_recoverable_read_call(self, run_id: UUID) -> ToolCall | None: ...

    async def record_recovered_read_started(
''',
    '''    async def load_recoverable_read_call(self, run_id: UUID) -> ToolCall | None: ...

    async def load_ready_external_action(
        self,
        run_id: UUID,
    ) -> tuple[ToolCall, ActionSnapshot, ExternalAction] | None: ...

    async def record_side_effect_attempt_started(
        self,
        call: ToolCall,
        action: ExternalAction,
        *,
        expected_generation: int,
    ) -> "ToolExecutionAttempt": ...

    async def record_ready_side_effect_blocked_and_fail_run(
        self,
        call: ToolCall,
        action: ExternalAction,
        run: Run,
        reason: str,
        *,
        expected_generation: int,
    ) -> None: ...

    async def record_side_effect_succeeded(
        self,
        call: ToolCall,
        action: ExternalAction,
        attempt: "ToolExecutionAttempt",
        message: RunMessage,
        *,
        expected_generation: int,
    ) -> None: ...

    async def record_recovered_read_started(
''',
)

replace_once(
    "src/agentforge/application/ports.py",
    '''    ToolCall,
    ToolProposal,
)
''',
    '''    ToolCall,
    ToolExecutionAttempt,
    ToolProposal,
)
''',
)

# String forward refs are no longer necessary once ToolExecutionAttempt imports.
replace_once(
    "src/agentforge/application/ports.py",
    ''') -> "ToolExecutionAttempt": ...
''',
    ''') -> ToolExecutionAttempt: ...
''',
)

replace_once(
    "src/agentforge/application/ports.py",
    '''        attempt: "ToolExecutionAttempt",
''',
    '''        attempt: ToolExecutionAttempt,
''',
)

# ---------------------------------------------------------------------------
# Generic side-effect function adapter for tests/composition; READ FunctionTool
# remains incapable of accidentally satisfying the side-effect protocol.
# ---------------------------------------------------------------------------
append_text(
    "src/agentforge/runtime/tools.py",
    "class SideEffectFunctionTool:",
    '''


class SideEffectFunctionTool:
    """Explicit adapter wrapper for physical side effects.

    The wrapped callable receives a SideEffectInvocation so stable operation
    identity is never reconstructed from model text or mutable ToolCall state.
    """

    def __init__(
        self,
        *,
        version_id: UUID,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        func: Callable[[object], Any],
    ) -> None:
        self._version_id = version_id
        self._spec = ModelToolSpec(name, description, input_schema)
        self._func = func

    @property
    def version_id(self) -> UUID:
        return self._version_id

    @property
    def spec(self) -> ModelToolSpec:
        return self._spec

    async def invoke(self, arguments: dict[str, Any]) -> Any:
        raise RuntimeError("side-effect tools must cross the Action Commit Boundary")

    async def invoke_side_effect(self, invocation: object) -> Any:
        if inspect.iscoroutinefunction(self._func):
            return await self._func(invocation)
        value = await asyncio.to_thread(self._func, invocation)
        if inspect.isawaitable(value):
            return await value
        return value
''',
)

# ---------------------------------------------------------------------------
# Coordinator owns adapter capability validation and immutable snapshot execution.
# ---------------------------------------------------------------------------
Path("src/agentforge/runtime/tool_coordinator.py").write_text(
    '''from __future__ import annotations

import json
from dataclasses import dataclass
from typing import cast
from uuid import uuid4

from agentforge.application.ports import (
    SideEffectInvocation,
    SideEffectTool,
    Tool,
    ToolRegistry,
)
from agentforge.domain.actions import ActionSnapshot, ExternalAction
from agentforge.domain.enums import ExternalActionStatus, ToolCallStatus, ToolEffectType
from agentforge.domain.models import (
    AgentVersion,
    ToolBinding,
    ToolCall,
    ToolExecutionAttempt,
    ToolProposal,
)


@dataclass(slots=True)
class PreparedToolCall:
    call: ToolCall
    tool: Tool
    binding: ToolBinding


@dataclass(slots=True)
class PreparedExternalAction:
    call: ToolCall
    snapshot: ActionSnapshot
    action: ExternalAction
    tool: SideEffectTool
    binding: ToolBinding


class ToolCoordinator:
    """Separate durable acceptance, Action Commit, and physical Tool invocation."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    @staticmethod
    def _binding(name: str, agent_version: AgentVersion) -> ToolBinding:
        matches = [binding for binding in agent_version.tool_bindings if binding.name == name]
        if len(matches) != 1:
            raise PermissionError(f"tool is not uniquely bound to agent version: {name}")
        return matches[0]

    def _resolve_bound_tool(self, binding: ToolBinding, agent_version: AgentVersion) -> Tool:
        tool = self._registry.resolve(binding.name, agent_version.tool_bindings)
        if tool.version_id != binding.tool_version_id:
            raise ValueError("resolved tool version no longer matches immutable binding")
        return tool

    def _resolve_side_effect_tool(
        self,
        binding: ToolBinding,
        agent_version: AgentVersion,
    ) -> SideEffectTool:
        tool = self._resolve_bound_tool(binding, agent_version)
        if not isinstance(tool, SideEffectTool):
            raise PermissionError(
                f"tool adapter does not implement the side-effect contract: {binding.name}"
            )
        return cast(SideEffectTool, tool)

    def prepare_model_tool(
        self,
        *,
        proposal: ToolProposal,
        agent_version: AgentVersion,
    ) -> PreparedToolCall | PreparedExternalAction:
        binding = self._binding(proposal.tool_name, agent_version)
        if binding.effect_type is ToolEffectType.READ:
            return self._prepare_read_with_binding(
                proposal=proposal,
                agent_version=agent_version,
                binding=binding,
            )
        return self._prepare_side_effect_with_binding(
            proposal=proposal,
            agent_version=agent_version,
            binding=binding,
        )

    def prepare_read(
        self, *, proposal: ToolProposal, agent_version: AgentVersion
    ) -> PreparedToolCall:
        binding = self._binding(proposal.tool_name, agent_version)
        return self._prepare_read_with_binding(
            proposal=proposal,
            agent_version=agent_version,
            binding=binding,
        )

    def _prepare_read_with_binding(
        self,
        *,
        proposal: ToolProposal,
        agent_version: AgentVersion,
        binding: ToolBinding,
    ) -> PreparedToolCall:
        if binding.effect_type is not ToolEffectType.READ:
            raise PermissionError(f"tool is not a READ ToolVersion: {proposal.tool_name}")
        tool = self._resolve_bound_tool(binding, agent_version)
        call = ToolCall.from_proposal(proposal, tool_version_id=tool.version_id)
        call.ready()
        call.start()
        return PreparedToolCall(call=call, tool=tool, binding=binding)

    def prepare_side_effect(
        self, *, proposal: ToolProposal, agent_version: AgentVersion
    ) -> PreparedExternalAction:
        binding = self._binding(proposal.tool_name, agent_version)
        return self._prepare_side_effect_with_binding(
            proposal=proposal,
            agent_version=agent_version,
            binding=binding,
        )

    def _prepare_side_effect_with_binding(
        self,
        *,
        proposal: ToolProposal,
        agent_version: AgentVersion,
        binding: ToolBinding,
    ) -> PreparedExternalAction:
        if not binding.stage32_side_effect_executable:
            raise PermissionError(
                f"ToolVersion is not Stage-3.2 side-effect executable: {proposal.tool_name}"
            )
        tool = self._resolve_side_effect_tool(binding, agent_version)
        call = ToolCall.from_proposal(proposal, tool_version_id=binding.tool_version_id)
        call.ready()
        operation_id = uuid4()
        snapshot = ActionSnapshot.create(
            operation_id=operation_id,
            tool_version_id=binding.tool_version_id,
            effect_type=binding.effect_type,
            arguments=proposal.arguments,
            credential_ref=binding.credential_ref,
        )
        action = ExternalAction.create(
            run_id=proposal.run_id,
            tool_call_id=call.id,
            action_snapshot_id=snapshot.id,
            operation_id=operation_id,
        )
        return PreparedExternalAction(
            call=call,
            snapshot=snapshot,
            action=action,
            tool=tool,
            binding=binding,
        )

    def prepare_recovered_read(
        self, *, call: ToolCall, agent_version: AgentVersion
    ) -> PreparedToolCall:
        if call.status is not ToolCallStatus.READY:
            raise ValueError("recovered READ call must be READY")
        if call.tool_version_id is None:
            raise ValueError("recovered READ call must bind a tool version")
        binding = self._binding(call.tool_name, agent_version)
        if binding.effect_type is not ToolEffectType.READ:
            raise ValueError("recovered ToolCall is not a READ ToolVersion")
        tool = self._resolve_bound_tool(binding, agent_version)
        if tool.version_id != call.tool_version_id:
            raise ValueError("recovered READ call tool version no longer matches binding")
        call.start()
        return PreparedToolCall(call=call, tool=tool, binding=binding)

    def prepare_recovered_side_effect(
        self,
        *,
        call: ToolCall,
        snapshot: ActionSnapshot,
        action: ExternalAction,
        agent_version: AgentVersion,
    ) -> PreparedExternalAction:
        if call.status is not ToolCallStatus.READY:
            raise ValueError("recovered side-effect ToolCall must be READY")
        if action.status is not ExternalActionStatus.READY or action.current_attempt_id is not None:
            raise ValueError("recovered ExternalAction must be READY without an active attempt")
        if call.id != action.tool_call_id or snapshot.id != action.action_snapshot_id:
            raise ValueError("recovered side-effect durable identity mismatch")
        if call.tool_version_id != snapshot.tool_version_id:
            raise ValueError("recovered side-effect ToolVersion mismatch")
        if call.arguments != snapshot.arguments or action.operation_id != snapshot.operation_id:
            raise ValueError("recovered side-effect snapshot mismatch")
        binding = self._binding(call.tool_name, agent_version)
        if binding.tool_version_id != snapshot.tool_version_id:
            raise ValueError("recovered side-effect binding no longer matches snapshot")
        if not binding.stage32_side_effect_executable:
            raise PermissionError("recovered ToolVersion is not Stage-3.2 executable")
        tool = self._resolve_side_effect_tool(binding, agent_version)
        return PreparedExternalAction(
            call=call,
            snapshot=snapshot,
            action=action,
            tool=tool,
            binding=binding,
        )

    async def execute_prepared(self, prepared: PreparedToolCall) -> ToolCall:
        call = prepared.call
        try:
            raw_result = await prepared.tool.invoke(call.arguments)
            encoded = json.dumps(
                raw_result,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            result = json.loads(encoded)
        except Exception as exc:
            call.fail(str(exc))
            raise
        call.succeed(result)
        return call

    async def execute_side_effect(
        self,
        prepared: PreparedExternalAction,
        attempt: ToolExecutionAttempt,
    ) -> ToolCall:
        if prepared.call.status is not ToolCallStatus.EXECUTING:
            raise RuntimeError("side-effect adapter call requires EXECUTING ToolCall")
        if prepared.action.status is not ExternalActionStatus.EXECUTING:
            raise RuntimeError("side-effect adapter call requires EXECUTING ExternalAction")
        if prepared.action.current_attempt_id != attempt.id:
            raise RuntimeError("side-effect attempt is not the current authorized attempt")
        if attempt.external_action_id != prepared.action.id:
            raise RuntimeError("side-effect attempt does not reference ExternalAction")
        invocation = SideEffectInvocation(
            operation_id=prepared.action.operation_id,
            arguments=dict(prepared.snapshot.arguments),
            credential_ref=prepared.snapshot.credential_ref,
            idempotency_key=(
                str(prepared.action.operation_id) if prepared.binding.idempotency_supported else None
            ),
        )
        raw_result = await prepared.tool.invoke_side_effect(invocation)
        encoded = json.dumps(
            raw_result,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        prepared.call.succeed(json.loads(encoded))
        return prepared.call


def tool_result_message_content(result: object) -> str:
    """Canonical JSON representation fed back to the model."""
    return json.dumps(
        result,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
'''
)

# ---------------------------------------------------------------------------
# Mapper helpers for durable READY side-effect recovery.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/infrastructure/db/mappers.py",
    '''from agentforge.domain.enums import ReconciliationMode, ToolEffectType
from agentforge.domain.models import AgentVersion, Run, RunMessage, RunState, ToolBinding, ToolCall
from agentforge.infrastructure.db.models import RunMessageRow, RunRow, RunStateRow, ToolCallRow
''',
    '''from agentforge.domain.actions import ActionSnapshot, ExternalAction
from agentforge.domain.enums import ReconciliationMode, ToolEffectType
from agentforge.domain.models import AgentVersion, Run, RunMessage, RunState, ToolBinding, ToolCall
from agentforge.infrastructure.db.models import (
    ActionSnapshotRow,
    ExternalActionRow,
    RunMessageRow,
    RunRow,
    RunStateRow,
    ToolCallRow,
)
''',
)

append_text(
    "src/agentforge/infrastructure/db/mappers.py",
    "def action_snapshot_from_row",
    '''


def action_snapshot_from_row(row: ActionSnapshotRow) -> ActionSnapshot:
    return ActionSnapshot(
        id=row.id,
        format_version=row.format_version,
        operation_id=row.operation_id,
        tool_version_id=row.tool_version_id,
        effect_type=row.effect_type,
        credential_ref=row.credential_ref,
        arguments=dict(row.arguments),
        canonical_json=row.canonical_json,
        digest=row.digest,
    )


def external_action_from_row(row: ExternalActionRow) -> ExternalAction:
    return ExternalAction(
        id=row.id,
        run_id=row.run_id,
        tool_call_id=row.tool_call_id,
        action_snapshot_id=row.action_snapshot_id,
        operation_id=row.operation_id,
        status=row.status,
        current_attempt_id=row.current_attempt_id,
    )
''',
)

# ---------------------------------------------------------------------------
# In-memory recorder: READY recovery, Action Commit, abort stabilization, success.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/application/run_manager.py",
    '''    async def record_recovered_read_started(
''',
    '''    async def load_ready_external_action(
        self,
        run_id: UUID,
    ) -> tuple[ToolCall, ActionSnapshot, ExternalAction] | None:
        actions = [
            action
            for action in self.external_actions
            if action.run_id == run_id and action.status is ExternalActionStatus.READY
        ]
        if len(actions) > 1:
            raise RuntimeError("found multiple READY ExternalActions for one Run")
        if not actions:
            return None
        action = actions[0]
        call = next(item for item in self.tool_calls if item.id == action.tool_call_id)
        snapshot = next(
            item for item in self.action_snapshots if item.id == action.action_snapshot_id
        )
        if call.status is not ToolCallStatus.READY:
            raise RuntimeError("READY ExternalAction does not project to READY ToolCall")
        return call, snapshot, action

    async def record_side_effect_attempt_started(
        self,
        call: ToolCall,
        action: ExternalAction,
        *,
        expected_generation: int,
    ) -> ToolExecutionAttempt:
        if call.status is not ToolCallStatus.READY:
            raise ValueError("Action Commit requires READY ToolCall")
        if action.status is not ExternalActionStatus.READY or action.current_attempt_id is not None:
            raise ValueError("Action Commit requires READY ExternalAction")
        if action.tool_call_id != call.id:
            raise ValueError("ExternalAction does not reference ToolCall")
        self._assert_deadline_not_expired(call.run_id)
        self._assert_tool_budget(call.run_id)
        self._assert_no_started_model_invocations(call.run_id)
        self._assert_no_started_tool_attempts(call.run_id)
        assert self.run_state is not None
        attempt = ToolExecutionAttempt(
            uuid4(),
            call.run_id,
            call.id,
            self._next_tool_attempt_number(call.id),
            expected_generation,
            external_action_id=action.id,
        )
        self.run_state.tool_attempts_used += 1
        self.run_state.state_version += 1
        self.tool_attempts.append(attempt)
        call.start()
        action.start(attempt.id)
        self.events.append(
            DomainEvent(
                call.run_id,
                len(self.events) + 1,
                EventType.ACTION_COMMITTED,
                {
                    "tool_call_id": str(call.id),
                    "external_action_id": str(action.id),
                    "operation_id": str(action.operation_id),
                    "attempt_id": str(attempt.id),
                    "attempt_number": attempt.attempt_number,
                },
            )
        )
        self.events.append(
            DomainEvent(
                call.run_id,
                len(self.events) + 1,
                EventType.TOOL_STARTED,
                {
                    "tool_call_id": str(call.id),
                    "tool_name": call.tool_name,
                    "external_action_id": str(action.id),
                    "attempt_id": str(attempt.id),
                    "attempt_number": attempt.attempt_number,
                },
            )
        )
        return attempt

    async def record_ready_side_effect_blocked_and_fail_run(
        self,
        call: ToolCall,
        action: ExternalAction,
        run: Run,
        reason: str,
        *,
        expected_generation: int,
    ) -> None:
        if call.status is not ToolCallStatus.READY:
            raise ValueError("blocked action stabilization requires READY ToolCall")
        if action.status is not ExternalActionStatus.READY:
            raise ValueError("blocked action stabilization requires READY ExternalAction")
        self._assert_no_started_tool_attempts(run.id)
        call.not_executed(reason)
        action.abort()
        self._append_event(
            run,
            EventType.ACTION_ABORTED,
            {
                "tool_call_id": str(call.id),
                "external_action_id": str(action.id),
                "operation_id": str(action.operation_id),
                "reason": reason,
            },
        )
        self._append_event(run, EventType.RUN_FAILED, {"reason": run.failure_reason})

    async def record_side_effect_succeeded(
        self,
        call: ToolCall,
        action: ExternalAction,
        attempt: ToolExecutionAttempt,
        message: RunMessage,
        *,
        expected_generation: int,
    ) -> None:
        if call.status is not ToolCallStatus.SUCCEEDED:
            raise ValueError("side-effect success requires SUCCEEDED ToolCall")
        if action.status is not ExternalActionStatus.EXECUTING:
            raise ValueError("side-effect success requires EXECUTING ExternalAction")
        if action.current_attempt_id != attempt.id:
            raise ValueError("side-effect success attempt is not current")
        durable_attempt = self._started_tool_attempt(call.id)
        if durable_attempt.id != attempt.id or durable_attempt.external_action_id != action.id:
            raise RuntimeError("side-effect durable attempt mismatch")
        durable_attempt.succeed(call.result)
        action.succeed()
        self.messages.append(
            RunMessage(
                message.run_id,
                len(self.messages) + 1,
                message.role,
                message.content,
                message.source_id,
            )
        )
        self.events.append(
            DomainEvent(
                call.run_id,
                len(self.events) + 1,
                EventType.ACTION_SUCCEEDED,
                {
                    "tool_call_id": str(call.id),
                    "external_action_id": str(action.id),
                    "operation_id": str(action.operation_id),
                    "attempt_id": str(attempt.id),
                },
            )
        )
        self.events.append(
            DomainEvent(
                call.run_id,
                len(self.events) + 1,
                EventType.TOOL_SUCCEEDED,
                {
                    "tool_call_id": str(call.id),
                    "tool_name": call.tool_name,
                    "attempt_id": str(attempt.id),
                    "attempt_number": attempt.attempt_number,
                },
            )
        )

    async def record_recovered_read_started(
''',
)

# ---------------------------------------------------------------------------
# PostgreSQL READY loader and the fenced Action Commit/success transactions.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''from agentforge.domain.models import (
    ModelInvocation,
    Run,
    RunMessage,
    RunState,
    ToolCall,
    ToolProposal,
)
''',
    '''from agentforge.domain.models import (
    ModelInvocation,
    Run,
    RunMessage,
    RunState,
    ToolCall,
    ToolExecutionAttempt,
    ToolProposal,
)
''',
)

replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''from agentforge.infrastructure.db.mappers import (
    message_from_row,
    run_state_from_row,
    tool_call_from_row,
)
''',
    '''from agentforge.infrastructure.db.mappers import (
    action_snapshot_from_row,
    external_action_from_row,
    message_from_row,
    run_state_from_row,
    tool_call_from_row,
)
''',
)

replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''    async def record_recovered_read_started(
''',
    '''    async def load_ready_external_action(
        self,
        run_id: UUID,
    ) -> tuple[ToolCall, ActionSnapshot, ExternalAction] | None:
        if run_id != self._run_id:
            raise ValueError("recorder is scoped to one run")
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(ExternalActionRow, ToolCallRow, ActionSnapshotRow)
                    .join(ToolCallRow, ToolCallRow.id == ExternalActionRow.tool_call_id)
                    .join(
                        ActionSnapshotRow,
                        ActionSnapshotRow.id == ExternalActionRow.action_snapshot_id,
                    )
                    .where(
                        ExternalActionRow.run_id == run_id,
                        ExternalActionRow.status == ExternalActionStatus.READY,
                        ExternalActionRow.current_attempt_id.is_(None),
                        ToolCallRow.status == ToolCallStatus.READY,
                    )
                )
            ).all()
        if len(rows) > 1:
            raise RuntimeError("found multiple READY ExternalActions for one Run")
        if not rows:
            return None
        action_row, call_row, snapshot_row = rows[0]
        return (
            tool_call_from_row(call_row),
            action_snapshot_from_row(snapshot_row),
            external_action_from_row(action_row),
        )

    async def record_side_effect_attempt_started(
        self,
        call: ToolCall,
        action: ExternalAction,
        *,
        expected_generation: int,
    ) -> ToolExecutionAttempt:
        """Action Commit: durable authorization must commit before adapter I/O."""
        self._assert_generation(expected_generation)
        if call.status is not ToolCallStatus.READY:
            raise ValueError("Action Commit requires READY ToolCall")
        if action.status is not ExternalActionStatus.READY or action.current_attempt_id is not None:
            raise ValueError("Action Commit requires READY ExternalAction")
        if action.run_id != call.run_id or action.tool_call_id != call.id:
            raise ValueError("ExternalAction does not reference ToolCall")

        attempt_id = uuid4()
        attempt_number = 0
        async with self._sessions() as session, session.begin():
            run_row = await _lock_owned_run(
                session,
                run_id=call.run_id,
                expected_generation=expected_generation,
            )
            action_row = (
                await session.execute(
                    select(ExternalActionRow)
                    .where(
                        ExternalActionRow.id == action.id,
                        ExternalActionRow.run_id == call.run_id,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if (
                action_row is None
                or action_row.status is not ExternalActionStatus.READY
                or action_row.current_attempt_id is not None
                or action_row.tool_call_id != call.id
                or action_row.operation_id != action.operation_id
            ):
                raise RuntimeError("ExternalAction is no longer READY for Action Commit")

            call_row = (
                await session.execute(
                    select(ToolCallRow)
                    .where(
                        ToolCallRow.id == call.id,
                        ToolCallRow.run_id == call.run_id,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if (
                call_row is None
                or call_row.status is not ToolCallStatus.READY
                or call_row.tool_version_id != call.tool_version_id
            ):
                raise RuntimeError("ToolCall is no longer READY for Action Commit")

            conflicting = await session.scalar(
                select(ToolCallRow.id)
                .where(
                    ToolCallRow.run_id == call.run_id,
                    ToolCallRow.id != call.id,
                    ToolCallRow.status.in_([ToolCallStatus.READY, ToolCallStatus.EXECUTING]),
                )
                .limit(1)
            )
            if conflicting is not None:
                raise RuntimeError(f"conflicting active ToolCall exists: {conflicting}")
            await _assert_no_started_model_invocations(session, call.run_id)
            await _assert_no_started_tool_attempts(session, call.run_id)
            state = await _lock_run_state(session, call.run_id)
            await _assert_deadline_not_expired(session, run_row)
            _assert_tool_budget(run_row, state)

            snapshot_row = await session.get(ActionSnapshotRow, action_row.action_snapshot_id)
            if snapshot_row is None:
                raise RuntimeError("ExternalAction snapshot is missing")
            if (
                snapshot_row.operation_id != action_row.operation_id
                or snapshot_row.tool_version_id != call_row.tool_version_id
                or dict(snapshot_row.arguments) != dict(call_row.arguments)
            ):
                raise RuntimeError("ActionSnapshot no longer matches durable action identity")

            attempt_number = await _next_tool_attempt_number(session, call.id)
            attempt_row = ToolExecutionAttemptRow(
                id=attempt_id,
                run_id=call.run_id,
                tool_call_id=call.id,
                external_action_id=action.id,
                attempt_number=attempt_number,
                execution_generation=expected_generation,
                status=ToolExecutionAttemptStatus.STARTED,
            )
            session.add(attempt_row)
            await session.flush()

            state.tool_attempts_used += 1
            state.state_version += 1
            call_row.status = ToolCallStatus.EXECUTING
            call_row.error = None
            action_row.status = ExternalActionStatus.EXECUTING
            action_row.current_attempt_id = attempt_id
            action_row.updated_at = func.clock_timestamp()

            seqs = list(await _allocate_event_sequences(session, call.run_id, 2))
            session.add_all(
                [
                    DomainEventRow(
                        id=uuid4(),
                        run_id=call.run_id,
                        sequence=seqs[0],
                        event_type=EventType.ACTION_COMMITTED.value,
                        payload={
                            "tool_call_id": str(call.id),
                            "external_action_id": str(action.id),
                            "operation_id": str(action.operation_id),
                            "attempt_id": str(attempt_id),
                            "attempt_number": attempt_number,
                        },
                    ),
                    DomainEventRow(
                        id=uuid4(),
                        run_id=call.run_id,
                        sequence=seqs[1],
                        event_type=EventType.TOOL_STARTED.value,
                        payload={
                            "tool_call_id": str(call.id),
                            "tool_name": call.tool_name,
                            "external_action_id": str(action.id),
                            "attempt_id": str(attempt_id),
                            "attempt_number": attempt_number,
                        },
                    ),
                ]
            )
            await session.flush()

        attempt = ToolExecutionAttempt(
            attempt_id,
            call.run_id,
            call.id,
            attempt_number,
            expected_generation,
            external_action_id=action.id,
        )
        call.start()
        action.start(attempt.id)
        return attempt

    async def record_ready_side_effect_blocked_and_fail_run(
        self,
        call: ToolCall,
        action: ExternalAction,
        run: Run,
        reason: str,
        *,
        expected_generation: int,
    ) -> None:
        """Stabilize a pre-commit action that can no longer execute."""
        self._assert_generation(expected_generation)
        if call.status is not ToolCallStatus.READY:
            raise ValueError("blocked action stabilization requires READY ToolCall")
        if action.status is not ExternalActionStatus.READY:
            raise ValueError("blocked action stabilization requires READY ExternalAction")
        if run.status is not RunStatus.FAILED:
            raise ValueError("blocked action stabilization requires FAILED Run")

        async with self._sessions() as session, session.begin():
            run_row = await _lock_owned_run(
                session,
                run_id=run.id,
                expected_generation=expected_generation,
            )
            action_row = (
                await session.execute(
                    select(ExternalActionRow)
                    .where(
                        ExternalActionRow.id == action.id,
                        ExternalActionRow.run_id == run.id,
                    )
                    .with_for_update()
                )
            ).scalar_one()
            call_row = (
                await session.execute(
                    select(ToolCallRow)
                    .where(
                        ToolCallRow.id == call.id,
                        ToolCallRow.run_id == run.id,
                    )
                    .with_for_update()
                )
            ).scalar_one()
            if (
                action_row.status is not ExternalActionStatus.READY
                or action_row.current_attempt_id is not None
                or call_row.status is not ToolCallStatus.READY
            ):
                raise RuntimeError("blocked action is no longer pre-commit READY")
            await _assert_no_started_tool_attempts(session, run.id)
            action_row.status = ExternalActionStatus.ABORTED
            action_row.current_attempt_id = None
            action_row.updated_at = func.clock_timestamp()
            call_row.status = ToolCallStatus.NOT_EXECUTED
            call_row.error = reason
            run_row.status = RunStatus.FAILED
            run_row.failure_reason = reason
            run_row.completed_at = func.clock_timestamp()
            run_row.owner_worker_id = None
            run_row.lease_expires_at = None
            seqs = list(await _allocate_event_sequences(session, run.id, 2))
            session.add_all(
                [
                    DomainEventRow(
                        id=uuid4(),
                        run_id=run.id,
                        sequence=seqs[0],
                        event_type=EventType.ACTION_ABORTED.value,
                        payload={
                            "tool_call_id": str(call.id),
                            "external_action_id": str(action.id),
                            "operation_id": str(action.operation_id),
                            "reason": reason,
                        },
                    ),
                    DomainEventRow(
                        id=uuid4(),
                        run_id=run.id,
                        sequence=seqs[1],
                        event_type=EventType.RUN_FAILED.value,
                        payload={"reason": reason},
                    ),
                ]
            )

        call.not_executed(reason)
        action.abort()

    async def record_side_effect_succeeded(
        self,
        call: ToolCall,
        action: ExternalAction,
        attempt: ToolExecutionAttempt,
        message: RunMessage,
        *,
        expected_generation: int,
    ) -> None:
        """Commit a current side-effect attempt's successful business result."""
        self._assert_generation(expected_generation)
        if call.status is not ToolCallStatus.SUCCEEDED:
            raise ValueError("side-effect success requires SUCCEEDED ToolCall")
        if action.status is not ExternalActionStatus.EXECUTING:
            raise ValueError("side-effect success requires EXECUTING ExternalAction")
        if action.current_attempt_id != attempt.id:
            raise ValueError("side-effect success attempt is not current")

        async with self._sessions() as session, session.begin():
            await _lock_owned_run(
                session,
                run_id=call.run_id,
                expected_generation=expected_generation,
            )
            action_row = (
                await session.execute(
                    select(ExternalActionRow)
                    .where(
                        ExternalActionRow.id == action.id,
                        ExternalActionRow.run_id == call.run_id,
                    )
                    .with_for_update()
                )
            ).scalar_one()
            call_row = (
                await session.execute(
                    select(ToolCallRow)
                    .where(
                        ToolCallRow.id == call.id,
                        ToolCallRow.run_id == call.run_id,
                    )
                    .with_for_update()
                )
            ).scalar_one()
            attempt_row = (
                await session.execute(
                    select(ToolExecutionAttemptRow)
                    .where(
                        ToolExecutionAttemptRow.id == attempt.id,
                        ToolExecutionAttemptRow.tool_call_id == call.id,
                        ToolExecutionAttemptRow.external_action_id == action.id,
                    )
                    .with_for_update()
                )
            ).scalar_one()
            if (
                action_row.status is not ExternalActionStatus.EXECUTING
                or action_row.current_attempt_id != attempt.id
                or call_row.status is not ToolCallStatus.EXECUTING
                or attempt_row.status is not ToolExecutionAttemptStatus.STARTED
            ):
                raise RuntimeError("side-effect result lost current-attempt authorization")

            attempt_row.status = ToolExecutionAttemptStatus.SUCCEEDED
            attempt_row.result = call.result
            attempt_row.finished_at = func.clock_timestamp()
            call_row.status = ToolCallStatus.SUCCEEDED
            call_row.result = call.result
            action_row.status = ExternalActionStatus.SUCCEEDED
            action_row.current_attempt_id = None
            action_row.updated_at = func.clock_timestamp()

            message_seq = await _allocate_message_sequence(session, call.run_id)
            session.add(
                RunMessageRow(
                    id=uuid4(),
                    run_id=call.run_id,
                    sequence=message_seq,
                    role=message.role.value,
                    content=message.content,
                    source_id=message.source_id,
                )
            )
            seqs = list(await _allocate_event_sequences(session, call.run_id, 2))
            session.add_all(
                [
                    DomainEventRow(
                        id=uuid4(),
                        run_id=call.run_id,
                        sequence=seqs[0],
                        event_type=EventType.ACTION_SUCCEEDED.value,
                        payload={
                            "tool_call_id": str(call.id),
                            "external_action_id": str(action.id),
                            "operation_id": str(action.operation_id),
                            "attempt_id": str(attempt.id),
                        },
                    ),
                    DomainEventRow(
                        id=uuid4(),
                        run_id=call.run_id,
                        sequence=seqs[1],
                        event_type=EventType.TOOL_SUCCEEDED.value,
                        payload={
                            "tool_call_id": str(call.id),
                            "tool_name": call.tool_name,
                            "attempt_id": str(attempt.id),
                            "attempt_number": attempt.attempt_number,
                        },
                    ),
                ]
            )
            await session.flush()

        attempt.succeed(call.result)
        action.succeed()

    async def record_recovered_read_started(
''',
)

# ---------------------------------------------------------------------------
# RunManager: recover READY side effects first; newly prepared actions immediately
# cross a second durable Action Commit transaction before adapter invocation.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/application/run_manager.py",
    '''        progression_steps = 0
        prepared: PreparedToolCall | PreparedExternalAction
        recoverable_call = await recorder.load_recoverable_read_call(run.id)
''',
    '''        progression_steps = 0
        prepared: PreparedToolCall | PreparedExternalAction

        ready_action = await recorder.load_ready_external_action(run.id)
        if ready_action is not None:
            ready_call, ready_snapshot, external_action = ready_action
            prepared_action = self._tools.prepare_recovered_side_effect(
                call=ready_call,
                snapshot=ready_snapshot,
                action=external_action,
                agent_version=agent_version,
            )
            recovered_message = await self._execute_side_effect_action(
                run=run,
                prepared=prepared_action,
                recorder=recorder,
                expected_generation=expected_generation,
            )
            messages.append(recovered_message)
            progression_steps += 1

        recoverable_call = await recorder.load_recoverable_read_call(run.id)
''',
)

replace_once(
    "src/agentforge/application/run_manager.py",
    '''                # B2 stops at durable intent. Action Commit and physical side-effect
                # execution remain locked for Stage 3.2-C.
                return None

            call = prepared.call
''',
    '''                side_effect_message = await self._execute_side_effect_action(
                    run=run,
                    prepared=prepared,
                    recorder=recorder,
                    expected_generation=expected_generation,
                )
                messages.append(side_effect_message)
                progression_steps += 1
                continue

            call = prepared.call
''',
)

# Insert helper before execute().
replace_once(
    "src/agentforge/application/run_manager.py",
    '''    async def execute(
        self,
''',
    '''    async def _execute_side_effect_action(
        self,
        *,
        run: Run,
        prepared: PreparedExternalAction,
        recorder: ExecutionRecorder,
        expected_generation: int,
    ) -> RunMessage:
        try:
            attempt = await recorder.record_side_effect_attempt_started(
                prepared.call,
                prepared.action,
                expected_generation=expected_generation,
            )
        except BusinessProgressionBlockedError as exc:
            run.fail(exc.failure_reason)
            await recorder.record_ready_side_effect_blocked_and_fail_run(
                prepared.call,
                prepared.action,
                run,
                exc.failure_reason,
                expected_generation=expected_generation,
            )
            raise RunExecutionFailedError(run.failure_reason) from exc

        call = await self._tools.execute_side_effect(prepared, attempt)
        message = RunMessage(
            run.id,
            0,
            MessageRole.TOOL,
            tool_result_message_content(call.result),
            call.id,
        )
        await recorder.record_side_effect_succeeded(
            call,
            prepared.action,
            attempt,
            message,
            expected_generation=expected_generation,
        )
        return message

    async def execute(
        self,
''',
)

# ---------------------------------------------------------------------------
# B2 tests remain B2 tests: exercise preparation directly, not the now-unlocked
# C execution continuation.
# ---------------------------------------------------------------------------
replace_once(
    "tests/unit/test_run_manager.py",
    '''from agentforge.runtime.tools import FunctionTool, InMemoryToolRegistry
''',
    '''from agentforge.runtime.tools import FunctionTool, InMemoryToolRegistry, SideEffectFunctionTool
''',
)

old_unit = '''    registry = InMemoryToolRegistry(
        [
            FunctionTool(
                version_id=version_id,
                name="create_ticket",
                description="create external ticket",
                input_schema={"type": "object"},
                func=forbidden_external_call,
            )
        ]
    )
    model = ScriptedFakeModel([ToolStep("create_ticket", {"summary": "intent only"})])
    manager = RunManager(NativeRunner(model, registry), ToolCoordinator(registry))
'''
new_unit = '''    registry = InMemoryToolRegistry(
        [
            SideEffectFunctionTool(
                version_id=version_id,
                name="create_ticket",
                description="create external ticket",
                input_schema={"type": "object"},
                func=lambda invocation: forbidden_external_call(
                    str(invocation.arguments["summary"])
                ),
            )
        ]
    )
'''
replace_once("tests/unit/test_run_manager.py", old_unit, new_unit)

replace_once(
    "tests/unit/test_run_manager.py",
    '''    result = await manager.execute(
        run=run,
        run_state=state,
        agent_version=av,
        recorder=journal,
    )

    assert result is None
''',
    '''    journal.seed(run, state)
    _, invocation = await journal.begin_model_invocation(
        run_id=run.id,
        invocation_id=uuid4(),
        expected_generation=run.execution_generation,
    )
    invocation.complete("TOOL_PROPOSAL")
    proposal = ToolProposal.create(
        run_id=run.id,
        model_invocation_id=invocation.id,
        tool_name="create_ticket",
        arguments={"summary": "intent only"},
    )
    prepared = ToolCoordinator(registry).prepare_side_effect(
        proposal=proposal,
        agent_version=av,
    )
    await journal.record_model_side_effect_prepared(
        invocation,
        proposal,
        prepared.call,
        prepared.snapshot,
        prepared.action,
        expected_generation=run.execution_generation,
    )

''',
)

# Only first exact B2 test block should gain SideEffectFunctionTool replacements below.
replace_once(
    "tests/integration/test_postgres_runtime.py",
    '''from agentforge.runtime.tools import FunctionTool, InMemoryToolRegistry
''',
    '''from agentforge.runtime.tools import FunctionTool, InMemoryToolRegistry, SideEffectFunctionTool
''',
)

old_int_registry = '''            FunctionTool(
                version_id=side_version_id,
                name="create_ticket",
                description="external side effect",
                input_schema={"type": "object"},
                func=forbidden_external_call,
            ),
'''
new_int_registry = '''            SideEffectFunctionTool(
                version_id=side_version_id,
                name="create_ticket",
                description="external side effect",
                input_schema={"type": "object"},
                func=lambda invocation: forbidden_external_call(
                    str(invocation.arguments["summary"])
                ),
            ),
'''
replace_once("tests/integration/test_postgres_runtime.py", old_int_registry, new_int_registry)

old_worker = '''    worker = CoreWorker(
        runtime_store=store,
        recorder_factory=PostgresExecutionRecorderFactory(sessions),
        tool_registry=registry,
        model_factory=lambda _: ScriptedFakeModel(
            [ToolStep("create_ticket", {"summary": "durable intent"})]
        ),
        worker_id="worker-side-effect-b2",
        lease_seconds=30,
    )

    assert await worker.run_once() is True
    assert physical_calls == 0

    refreshed = await store.get_run(created.id)
    assert refreshed is not None
    assert refreshed.status is RunStatus.RUNNING
'''
new_worker = '''    claimed = await store.claim_next_run(worker_id="worker-side-effect-b2", lease_seconds=30)
    assert claimed is not None
    recorder = PostgresExecutionRecorder(
        sessions,
        run_id=created.id,
        generation=claimed.execution_generation,
    )
    _, invocation = await recorder.begin_model_invocation(
        run_id=created.id,
        invocation_id=uuid4(),
        expected_generation=claimed.execution_generation,
    )
    invocation.complete("TOOL_PROPOSAL")
    proposal = ToolProposal.create(
        run_id=created.id,
        model_invocation_id=invocation.id,
        tool_name="create_ticket",
        arguments={"summary": "durable intent"},
    )
    prepared = ToolCoordinator(registry).prepare_side_effect(
        proposal=proposal,
        agent_version=await store.load_agent_version(DEMO_AGENT_VERSION_ID),
    )
    await recorder.record_model_side_effect_prepared(
        invocation,
        proposal,
        prepared.call,
        prepared.snapshot,
        prepared.action,
        expected_generation=claimed.execution_generation,
    )
    assert physical_calls == 0

    refreshed = await store.get_run(created.id)
    assert refreshed is not None
    assert refreshed.status is RunStatus.RUNNING
'''
replace_once("tests/integration/test_postgres_runtime.py", old_worker, new_worker)

# Stale/policy B2 direct preparation must use an explicit side-effect adapter wrapper.
replace_once(
    "tests/integration/test_postgres_runtime.py",
    '''            FunctionTool(
                version_id=side_version_id,
                name="write_stale",
                description="write",
                input_schema={"type": "object"},
                func=lambda: {"must": "not run"},
            ),
''',
    '''            SideEffectFunctionTool(
                version_id=side_version_id,
                name="write_stale",
                description="write",
                input_schema={"type": "object"},
                func=lambda invocation: {"must": "not run"},
            ),
''',
)
replace_once(
    "tests/integration/test_postgres_runtime.py",
    '''            FunctionTool(
                version_id=side_version_id,
                name="write_policy",
                description="write",
                input_schema={"type": "object"},
                func=lambda: {"must": "not run"},
            ),
''',
    '''            SideEffectFunctionTool(
                version_id=side_version_id,
                name="write_policy",
                description="write",
                input_schema={"type": "object"},
                func=lambda invocation: {"must": "not run"},
            ),
''',
)

replace_once(
    "tests/unit/test_run_manager.py",
    '''    run = Run(uuid4(), av.id, "create a ticket")
    run.queue()
    state = RunState(run.id)
    journal = ExecutionJournal()

    journal.seed(run, state)
''',
    '''    run = Run(uuid4(), av.id, "create a ticket")
    run.queue()
    run.start()
    state = RunState(run.id)
    journal = ExecutionJournal()

    journal.seed(run, state)
''',
)

replace_once(
    "tests/unit/test_run_manager.py",
    '''            FunctionTool(
                version_id=version_id,
                name="write_once",
                description="side effect",
                input_schema={"type": "object"},
                func=forbidden_external_call,
            )
''',
    '''            SideEffectFunctionTool(
                version_id=version_id,
                name="write_once",
                description="side effect",
                input_schema={"type": "object"},
                func=lambda invocation: forbidden_external_call(),
            )
''',
)

# ---------------------------------------------------------------------------
# C1 pure-runtime tests: commit-before-call, success projection, READY recovery,
# and budget stabilization without external I/O.
# ---------------------------------------------------------------------------
append_text(
    "tests/unit/test_run_manager.py",
    "test_action_commit_is_durable_before_side_effect_adapter_call",
    '''


@pytest.mark.asyncio
async def test_action_commit_is_durable_before_side_effect_adapter_call() -> None:
    from agentforge.application.ports import SideEffectInvocation
    from agentforge.domain.enums import ExternalActionStatus, ReconciliationMode, ToolEffectType

    version_id = uuid4()
    state = RunState(uuid4())
    journal = ExecutionJournal()
    observed_calls = 0

    async def create_ticket(invocation: SideEffectInvocation):
        nonlocal observed_calls
        observed_calls += 1
        assert invocation.idempotency_key == str(invocation.operation_id)
        assert invocation.credential_ref == "credential://jira/c1"
        assert journal.external_actions[0].status is ExternalActionStatus.EXECUTING
        assert journal.external_actions[0].current_attempt_id is not None
        assert journal.tool_calls[0].status is ToolCallStatus.EXECUTING
        assert journal.tool_attempts[0].status is ToolExecutionAttemptStatus.STARTED
        assert journal.tool_attempts[0].external_action_id == journal.external_actions[0].id
        assert state.tool_attempts_used == 1
        return {"ticket_id": "T-1"}

    registry = InMemoryToolRegistry(
        [
            SideEffectFunctionTool(
                version_id=version_id,
                name="create_ticket",
                description="create ticket",
                input_schema={"type": "object"},
                func=create_ticket,
            )
        ]
    )
    model = ScriptedFakeModel(
        [ToolStep("create_ticket", {"summary": "commit first"}), FinalStep("created")]
    )
    manager = RunManager(NativeRunner(model, registry), ToolCoordinator(registry))
    av = AgentVersion(
        uuid4(),
        uuid4(),
        1,
        "create one ticket",
        (
            ToolBinding(
                version_id,
                "create_ticket",
                effect_type=ToolEffectType.EXTERNAL_SIDE_EFFECT,
                allow_no_approval_execution=True,
                credential_ref="credential://jira/c1",
                idempotency_supported=True,
                reconciliation_mode=ReconciliationMode.AUTHORITATIVE,
            ),
        ),
    )
    run = Run(state.run_id, av.id, "create ticket")
    run.queue()

    result = await manager.execute(
        run=run,
        run_state=state,
        agent_version=av,
        recorder=journal,
    )

    assert result == "created"
    assert observed_calls == 1
    assert run.status is RunStatus.COMPLETED
    assert state.tool_attempts_used == 1
    assert journal.external_actions[0].status is ExternalActionStatus.SUCCEEDED
    assert journal.external_actions[0].current_attempt_id is None
    assert journal.tool_calls[0].status is ToolCallStatus.SUCCEEDED
    assert journal.tool_attempts[0].status is ToolExecutionAttemptStatus.SUCCEEDED
    event_types = [event.type for event in journal.events]
    assert EventType.ACTION_PREPARED in event_types
    assert EventType.ACTION_COMMITTED in event_types
    assert EventType.ACTION_SUCCEEDED in event_types


@pytest.mark.asyncio
async def test_ready_external_action_is_recovered_before_new_model_reasoning() -> None:
    from agentforge.application.ports import SideEffectInvocation
    from agentforge.domain.enums import ExternalActionStatus, ReconciliationMode, ToolEffectType

    version_id = uuid4()
    calls = 0

    async def create_ticket(invocation: SideEffectInvocation):
        nonlocal calls
        calls += 1
        return {"ticket_id": str(invocation.operation_id)}

    registry = InMemoryToolRegistry(
        [
            SideEffectFunctionTool(
                version_id=version_id,
                name="create_ticket",
                description="create ticket",
                input_schema={"type": "object"},
                func=create_ticket,
            )
        ]
    )
    av = AgentVersion(
        uuid4(),
        uuid4(),
        1,
        "recover",
        (
            ToolBinding(
                version_id,
                "create_ticket",
                effect_type=ToolEffectType.WRITE,
                allow_no_approval_execution=True,
                idempotency_supported=True,
                reconciliation_mode=ReconciliationMode.NONE,
            ),
        ),
    )
    run = Run(uuid4(), av.id, "recover ready action")
    run.queue()
    run.start()
    state = RunState(run.id)
    journal = ExecutionJournal()
    journal.seed(run, state)
    _, invocation = await journal.begin_model_invocation(
        run_id=run.id,
        invocation_id=uuid4(),
        expected_generation=run.execution_generation,
    )
    invocation.complete("TOOL_PROPOSAL")
    proposal = ToolProposal.create(
        run_id=run.id,
        model_invocation_id=invocation.id,
        tool_name="create_ticket",
        arguments={"summary": "recover me"},
    )
    prepared = ToolCoordinator(registry).prepare_side_effect(
        proposal=proposal,
        agent_version=av,
    )
    await journal.record_model_side_effect_prepared(
        invocation,
        proposal,
        prepared.call,
        prepared.snapshot,
        prepared.action,
        expected_generation=run.execution_generation,
    )
    assert prepared.action.status is ExternalActionStatus.READY
    assert state.tool_attempts_used == 0

    manager = RunManager(
        NativeRunner(ScriptedFakeModel([FinalStep("recovered")]), registry),
        ToolCoordinator(registry),
    )
    result = await manager.execute(
        run=run,
        run_state=state,
        agent_version=av,
        recorder=journal,
    )

    assert result == "recovered"
    assert calls == 1
    assert state.model_invocations_used == 2
    assert state.tool_attempts_used == 1
    assert journal.external_actions[0].status is ExternalActionStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_action_commit_budget_block_aborts_ready_action_without_external_io() -> None:
    from agentforge.application.ports import SideEffectInvocation
    from agentforge.domain.enums import ExternalActionStatus, ReconciliationMode, ToolEffectType

    version_id = uuid4()
    calls = 0

    async def forbidden(invocation: SideEffectInvocation):
        nonlocal calls
        calls += 1
        return {"unexpected": True}

    registry = InMemoryToolRegistry(
        [
            SideEffectFunctionTool(
                version_id=version_id,
                name="write_once",
                description="write",
                input_schema={"type": "object"},
                func=forbidden,
            )
        ]
    )
    av = AgentVersion(
        uuid4(),
        uuid4(),
        1,
        "budget block",
        (
            ToolBinding(
                version_id,
                "write_once",
                effect_type=ToolEffectType.WRITE,
                allow_no_approval_execution=True,
                reconciliation_mode=ReconciliationMode.NONE,
            ),
        ),
    )
    run = Run(uuid4(), av.id, "blocked", max_tool_attempts=1)
    run.queue()
    run.start()
    state = RunState(run.id)
    journal = ExecutionJournal()
    journal.seed(run, state)
    _, invocation = await journal.begin_model_invocation(
        run_id=run.id,
        invocation_id=uuid4(),
        expected_generation=run.execution_generation,
    )
    invocation.complete("TOOL_PROPOSAL")
    proposal = ToolProposal.create(
        run_id=run.id,
        model_invocation_id=invocation.id,
        tool_name="write_once",
        arguments={},
    )
    prepared = ToolCoordinator(registry).prepare_side_effect(proposal=proposal, agent_version=av)
    await journal.record_model_side_effect_prepared(
        invocation,
        proposal,
        prepared.call,
        prepared.snapshot,
        prepared.action,
        expected_generation=run.execution_generation,
    )
    state.tool_attempts_used = 1

    manager = RunManager(
        NativeRunner(ScriptedFakeModel([FinalStep("must not run")]), registry),
        ToolCoordinator(registry),
    )
    with pytest.raises(RunExecutionFailedError, match="BUDGET_EXCEEDED"):
        await manager.execute(
            run=run,
            run_state=state,
            agent_version=av,
            recorder=journal,
        )

    assert calls == 0
    assert journal.external_actions[0].status is ExternalActionStatus.ABORTED
    assert journal.external_actions[0].current_attempt_id is None
    assert journal.tool_calls[0].status is ToolCallStatus.NOT_EXECUTED
    assert journal.tool_attempts == []
    assert state.tool_attempts_used == 1
''',
)

replace_once(
    "tests/integration/test_postgres_runtime.py",
    '''from agentforge.application.errors import (
    BusinessProgressionBlockedError,
    IdempotencyConflictError,
    StaleExecutorError,
    ToolTransientError,
)
''',
    '''from agentforge.application.errors import (
    BusinessProgressionBlockedError,
    IdempotencyConflictError,
    RunExecutionFailedError,
    StaleExecutorError,
    ToolTransientError,
)
from agentforge.application.run_manager import RunManager
''',
)

replace_once(
    "tests/integration/test_postgres_runtime.py",
    '''from agentforge.runtime.fake_model import FinalStep, ScriptedFakeModel, ToolStep
from agentforge.runtime.tool_coordinator import ToolCoordinator
''',
    '''from agentforge.runtime.fake_model import FinalStep, ScriptedFakeModel, ToolStep
from agentforge.runtime.native_runner import NativeRunner
from agentforge.runtime.tool_coordinator import ToolCoordinator
''',
)

# ---------------------------------------------------------------------------
# PostgreSQL C1 acceptance: a separate DB session observes committed authorization
# before the fake adapter records the effect.
# ---------------------------------------------------------------------------
append_text(
    "tests/integration/test_postgres_runtime.py",
    "test_action_commit_is_visible_before_physical_side_effect",
    '''


@pytest.mark.asyncio
async def test_action_commit_is_visible_before_physical_side_effect() -> None:
    from agentforge.application.ports import SideEffectInvocation
    from agentforge.domain.enums import ExternalActionStatus, ReconciliationMode
    from agentforge.infrastructure.db.models import ActionSnapshotRow, ExternalActionRow, RunStateRow

    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)

    side_tool_id = uuid4()
    side_version_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(
            ToolDefinitionRow(id=side_tool_id, name="create_commit_ticket", description="write")
        )
        await session.flush()
        session.add(
            ToolVersionRow(
                id=side_version_id,
                tool_id=side_tool_id,
                version_number=1,
                input_schema={"type": "object"},
                effect_type=ToolEffectType.EXTERNAL_SIDE_EFFECT,
                implementation_ref="tests:create_commit_ticket",
                allow_no_approval_execution=True,
                credential_ref="credential://jira/c1-integration",
                idempotency_supported=True,
                reconciliation_mode=ReconciliationMode.AUTHORITATIVE,
            )
        )
        await session.flush()
        session.add(
            AgentVersionToolRow(
                agent_version_id=DEMO_AGENT_VERSION_ID,
                tool_version_id=side_version_id,
                tool_alias="create_commit_ticket",
            )
        )

    physical_calls = 0

    async def external_effect(invocation: SideEffectInvocation):
        nonlocal physical_calls
        # A fresh transaction must see the full authorization tuple before effect.
        async with sessions() as observer:
            action = (
                await observer.execute(
                    select(ExternalActionRow).where(
                        ExternalActionRow.operation_id == invocation.operation_id
                    )
                )
            ).scalar_one()
            call = await observer.get(ToolCallRow, action.tool_call_id)
            snapshot = await observer.get(ActionSnapshotRow, action.action_snapshot_id)
            attempt = await observer.get(ToolExecutionAttemptRow, action.current_attempt_id)
            state = await observer.get(RunStateRow, action.run_id)
            assert call is not None and call.status is ToolCallStatus.EXECUTING
            assert snapshot is not None and snapshot.digest
            assert snapshot.operation_id == invocation.operation_id
            assert action.status is ExternalActionStatus.EXECUTING
            assert action.current_attempt_id is not None
            assert attempt is not None
            assert attempt.status is ToolExecutionAttemptStatus.STARTED
            assert attempt.external_action_id == action.id
            assert state is not None and state.tool_attempts_used == 1
        physical_calls += 1
        return {"ticket_id": "T-C1", "operation_id": str(invocation.operation_id)}

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
                name="create_commit_ticket",
                description="write",
                input_schema={"type": "object"},
                func=external_effect,
            ),
        ]
    )
    store = PostgresRuntimeStore(sessions)
    created = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="commit before effect",
        idempotency_key="integration-action-commit-visible-1",
        principal_scope="test-user",
    )
    worker = CoreWorker(
        runtime_store=store,
        recorder_factory=PostgresExecutionRecorderFactory(sessions),
        tool_registry=registry,
        model_factory=lambda _: ScriptedFakeModel(
            [
                ToolStep("create_commit_ticket", {"summary": "commit first"}),
                FinalStep("ticket created"),
            ]
        ),
        worker_id="worker-action-commit",
        lease_seconds=30,
    )

    assert await worker.run_once() is True
    assert physical_calls == 1

    durable = await store.get_run(created.id)
    assert durable is not None and durable.status is RunStatus.COMPLETED
    state = await store.load_run_state(created.id)
    assert state.tool_attempts_used == 1

    async with sessions() as session:
        action = (
            (
                await session.execute(
                    select(ExternalActionRow).where(ExternalActionRow.run_id == created.id)
                )
            )
            .scalars()
            .one()
        )
        call = await session.get(ToolCallRow, action.tool_call_id)
        attempt = (
            (
                await session.execute(
                    select(ToolExecutionAttemptRow).where(
                        ToolExecutionAttemptRow.external_action_id == action.id
                    )
                )
            )
            .scalars()
            .one()
        )
        event_types = (
            (
                await session.execute(
                    select(DomainEventRow.event_type)
                    .where(DomainEventRow.run_id == created.id)
                    .order_by(DomainEventRow.sequence)
                )
            )
            .scalars()
            .all()
        )
    assert action.status is ExternalActionStatus.SUCCEEDED
    assert action.current_attempt_id is None
    assert call is not None and call.status is ToolCallStatus.SUCCEEDED
    assert attempt.status is ToolExecutionAttemptStatus.SUCCEEDED
    assert EventType.ACTION_PREPARED.value in event_types
    assert EventType.ACTION_COMMITTED.value in event_types
    assert EventType.ACTION_SUCCEEDED.value in event_types
    await engine.dispose()


@pytest.mark.asyncio
async def test_ready_action_recovery_uses_same_operation_id_without_model_reproposal() -> None:
    from agentforge.application.ports import SideEffectInvocation
    from agentforge.domain.enums import ExternalActionStatus, ReconciliationMode
    from agentforge.infrastructure.db.models import ExternalActionRow

    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)

    side_tool_id = uuid4()
    side_version_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(ToolDefinitionRow(id=side_tool_id, name="recover_write", description="write"))
        await session.flush()
        session.add(
            ToolVersionRow(
                id=side_version_id,
                tool_id=side_tool_id,
                version_number=1,
                input_schema={"type": "object"},
                effect_type=ToolEffectType.WRITE,
                implementation_ref="tests:recover_write",
                allow_no_approval_execution=True,
                idempotency_supported=True,
                reconciliation_mode=ReconciliationMode.NONE,
            )
        )
        await session.flush()
        session.add(
            AgentVersionToolRow(
                agent_version_id=DEMO_AGENT_VERSION_ID,
                tool_version_id=side_version_id,
                tool_alias="recover_write",
            )
        )

    observed_operation_ids = []

    async def external_effect(invocation: SideEffectInvocation):
        observed_operation_ids.append(invocation.operation_id)
        return {"resource_id": "R-RECOVERED"}

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
                name="recover_write",
                description="write",
                input_schema={"type": "object"},
                func=external_effect,
            ),
        ]
    )
    store = PostgresRuntimeStore(sessions)
    created = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="recover ready action",
        idempotency_key="integration-ready-action-recovery-1",
        principal_scope="test-user",
    )
    claimed_a = await store.claim_next_run(worker_id="worker-ready-a", lease_seconds=1)
    assert claimed_a is not None
    recorder_a = PostgresExecutionRecorder(
        sessions,
        run_id=created.id,
        generation=claimed_a.execution_generation,
    )
    _, invocation = await recorder_a.begin_model_invocation(
        run_id=created.id,
        invocation_id=uuid4(),
        expected_generation=claimed_a.execution_generation,
    )
    invocation.complete("TOOL_PROPOSAL")
    proposal = ToolProposal.create(
        run_id=created.id,
        model_invocation_id=invocation.id,
        tool_name="recover_write",
        arguments={"value": "same intent"},
    )
    prepared = ToolCoordinator(registry).prepare_side_effect(
        proposal=proposal,
        agent_version=await store.load_agent_version(DEMO_AGENT_VERSION_ID),
    )
    await recorder_a.record_model_side_effect_prepared(
        invocation,
        proposal,
        prepared.call,
        prepared.snapshot,
        prepared.action,
        expected_generation=claimed_a.execution_generation,
    )
    original_operation_id = prepared.action.operation_id

    await asyncio.sleep(1.2)
    worker_b = CoreWorker(
        runtime_store=store,
        recorder_factory=PostgresExecutionRecorderFactory(sessions),
        tool_registry=registry,
        model_factory=lambda _: ScriptedFakeModel([FinalStep("recovered and complete")]),
        worker_id="worker-ready-b",
        lease_seconds=30,
    )
    assert await worker_b.run_once() is True

    assert observed_operation_ids == [original_operation_id]
    durable = await store.get_run(created.id)
    assert durable is not None and durable.status is RunStatus.COMPLETED
    assert durable.execution_generation == 2
    async with sessions() as session:
        action = (
            (
                await session.execute(
                    select(ExternalActionRow).where(ExternalActionRow.run_id == created.id)
                )
            )
            .scalars()
            .one()
        )
        proposals = await session.scalar(
            select(func.count()).select_from(ToolProposalRow).where(
                ToolProposalRow.run_id == created.id
            )
        )
    assert action.operation_id == original_operation_id
    assert action.status is ExternalActionStatus.SUCCEEDED
    assert proposals == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_action_commit_deadline_block_aborts_ready_action_without_external_call() -> None:
    from agentforge.application.ports import SideEffectInvocation
    from agentforge.domain.enums import ExternalActionStatus, ReconciliationMode
    from agentforge.infrastructure.db.models import ExternalActionRow, RunRow

    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)

    side_tool_id = uuid4()
    side_version_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(ToolDefinitionRow(id=side_tool_id, name="deadline_write", description="write"))
        await session.flush()
        session.add(
            ToolVersionRow(
                id=side_version_id,
                tool_id=side_tool_id,
                version_number=1,
                input_schema={"type": "object"},
                effect_type=ToolEffectType.WRITE,
                implementation_ref="tests:deadline_write",
                allow_no_approval_execution=True,
                idempotency_supported=False,
                reconciliation_mode=ReconciliationMode.NONE,
            )
        )
        await session.flush()
        session.add(
            AgentVersionToolRow(
                agent_version_id=DEMO_AGENT_VERSION_ID,
                tool_version_id=side_version_id,
                tool_alias="deadline_write",
            )
        )

    calls = 0

    async def forbidden(invocation: SideEffectInvocation):
        nonlocal calls
        calls += 1
        return {"unexpected": True}

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
                name="deadline_write",
                description="write",
                input_schema={"type": "object"},
                func=forbidden,
            ),
        ]
    )
    store = PostgresRuntimeStore(sessions)
    created = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="deadline after ready",
        idempotency_key="integration-action-commit-deadline-1",
        principal_scope="test-user",
    )
    claimed = await store.claim_next_run(worker_id="worker-deadline-a", lease_seconds=30)
    assert claimed is not None
    recorder = PostgresExecutionRecorder(
        sessions,
        run_id=created.id,
        generation=claimed.execution_generation,
    )
    _, invocation = await recorder.begin_model_invocation(
        run_id=created.id,
        invocation_id=uuid4(),
        expected_generation=claimed.execution_generation,
    )
    invocation.complete("TOOL_PROPOSAL")
    proposal = ToolProposal.create(
        run_id=created.id,
        model_invocation_id=invocation.id,
        tool_name="deadline_write",
        arguments={},
    )
    prepared = ToolCoordinator(registry).prepare_side_effect(
        proposal=proposal,
        agent_version=await store.load_agent_version(DEMO_AGENT_VERSION_ID),
    )
    await recorder.record_model_side_effect_prepared(
        invocation,
        proposal,
        prepared.call,
        prepared.snapshot,
        prepared.action,
        expected_generation=claimed.execution_generation,
    )
    async with sessions() as session, session.begin():
        await session.execute(
            update(RunRow)
            .where(RunRow.id == created.id)
            .values(deadline_at=func.clock_timestamp() - text("INTERVAL '1 second'"))
        )

    manager = RunManager(
        NativeRunner(ScriptedFakeModel([FinalStep("must not reason")]), registry),
        ToolCoordinator(registry),
    )
    with pytest.raises(RunExecutionFailedError, match="DEADLINE_EXCEEDED"):
        await manager.execute(
            run=claimed,
            run_state=await store.load_run_state(created.id),
            agent_version=await store.load_agent_version(DEMO_AGENT_VERSION_ID),
            recorder=recorder,
        )

    assert calls == 0
    durable = await store.get_run(created.id)
    assert durable is not None and durable.status is RunStatus.FAILED
    state = await store.load_run_state(created.id)
    assert state.tool_attempts_used == 0
    async with sessions() as session:
        action = (
            (
                await session.execute(
                    select(ExternalActionRow).where(ExternalActionRow.run_id == created.id)
                )
            )
            .scalars()
            .one()
        )
        call = await session.get(ToolCallRow, action.tool_call_id)
        attempts = await session.scalar(
            select(func.count()).select_from(ToolExecutionAttemptRow).where(
                ToolExecutionAttemptRow.run_id == created.id
            )
        )
    assert action.status is ExternalActionStatus.ABORTED
    assert action.current_attempt_id is None
    assert call is not None and call.status is ToolCallStatus.NOT_EXECUTED
    assert attempts == 0
    await engine.dispose()
''',
)

# Integration test imports need ToolProposalRow for READY-recovery assertion.
replace_once(
    "tests/integration/test_postgres_runtime.py",
    '''    ToolExecutionAttemptRow,
    ToolVersionRow,
)
''',
    '''    ToolExecutionAttemptRow,
    ToolProposalRow,
    ToolVersionRow,
)
''',
)
