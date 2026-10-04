from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from agentforge.domain.actions import ActionSnapshot, ExternalAction
from agentforge.domain.model_contract import ModelRequest, ModelResponse, ModelToolSpec
from agentforge.domain.models import (
    AgentVersion,
    ModelInvocation,
    Run,
    RunMessage,
    RunState,
    ToolBinding,
    ToolCall,
    ToolExecutionAttempt,
    ToolProposal,
)


class ModelGateway(Protocol):
    async def invoke(self, request: ModelRequest) -> ModelResponse: ...


class Tool(Protocol):
    @property
    def version_id(self) -> UUID: ...

    @property
    def spec(self) -> ModelToolSpec: ...

    async def invoke(self, arguments: dict[str, Any]) -> Any: ...


@dataclass(frozen=True, slots=True)
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
    def specs(self, bindings: tuple[ToolBinding, ...]) -> tuple[ModelToolSpec, ...]: ...

    def resolve(self, name: str, bindings: tuple[ToolBinding, ...]) -> Tool: ...


class ExecutionRecorder(Protocol):
    async def list_messages(self, run_id: UUID) -> list[RunMessage]: ...

    async def load_recoverable_read_call(self, run_id: UUID) -> ToolCall | None: ...

    async def load_ready_external_action(
        self,
        run_id: UUID,
    ) -> tuple[ToolCall, ActionSnapshot, ExternalAction] | None: ...

    async def load_unknown_external_action(
        self,
        run_id: UUID,
    ) -> tuple[ToolCall, ActionSnapshot, ExternalAction] | None: ...

    async def record_side_effect_attempt_started(
        self,
        call: ToolCall,
        action: ExternalAction,
        *,
        expected_generation: int,
    ) -> ToolExecutionAttempt: ...

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
        attempt: ToolExecutionAttempt,
        message: RunMessage,
        *,
        expected_generation: int,
    ) -> None: ...

    async def record_side_effect_unknown(
        self,
        call: ToolCall,
        action: ExternalAction,
        attempt: ToolExecutionAttempt,
        *,
        error: str,
        error_class: str,
        outcome_reason: str,
        expected_generation: int,
    ) -> None: ...

    async def record_side_effect_definite_failure_and_fail_run(
        self,
        call: ToolCall,
        action: ExternalAction,
        attempt: ToolExecutionAttempt,
        run: Run,
        *,
        error: str,
        error_class: str,
        expected_generation: int,
    ) -> None: ...

    async def record_recovered_read_started(
        self,
        call: ToolCall,
        *,
        expected_generation: int,
    ) -> None: ...

    async def record_recovered_read_blocked_and_fail_run(
        self,
        call: ToolCall,
        run: Run,
        *,
        expected_generation: int,
    ) -> None: ...

    async def record_run_started(self, run: Run) -> None: ...

    async def begin_model_invocation(
        self,
        *,
        run_id: UUID,
        invocation_id: UUID,
        expected_generation: int,
    ) -> tuple[RunState, ModelInvocation]: ...

    async def record_model_tool_started(
        self,
        invocation: ModelInvocation,
        proposal: ToolProposal,
        call: ToolCall,
        *,
        expected_generation: int,
    ) -> RunState: ...

    async def record_model_side_effect_prepared(
        self,
        invocation: ModelInvocation,
        proposal: ToolProposal,
        call: ToolCall,
        snapshot: ActionSnapshot,
        action: ExternalAction,
        *,
        expected_generation: int,
    ) -> RunState: ...

    async def record_model_tool_denied_and_fail_run(
        self,
        invocation: ModelInvocation,
        proposal: ToolProposal,
        call: ToolCall,
        run: Run,
        *,
        expected_generation: int,
    ) -> None: ...

    async def record_model_final_decision(
        self,
        invocation: ModelInvocation,
        run: Run,
        message: RunMessage,
        *,
        expected_generation: int,
    ) -> None: ...

    async def record_model_result_discarded_and_fail_run(
        self,
        invocation: ModelInvocation,
        run: Run,
        reason: str,
        *,
        expected_generation: int,
    ) -> None: ...

    async def record_model_failed_and_fail_run(
        self,
        invocation: ModelInvocation,
        run: Run,
        *,
        expected_generation: int,
    ) -> None: ...

    async def record_tool_succeeded(
        self,
        call: ToolCall,
        message: RunMessage,
        *,
        expected_generation: int,
    ) -> None: ...

    async def record_read_transient_failure(
        self,
        call: ToolCall,
        run: Run,
        *,
        max_attempts: int,
        initial_backoff_seconds: int,
        max_backoff_seconds: int,
        expected_generation: int,
    ) -> bool: ...

    async def record_tool_failed_and_fail_run(
        self,
        call: ToolCall,
        run: Run,
        *,
        expected_generation: int,
    ) -> None: ...

    async def record_run_failed(self, run: Run, *, expected_generation: int) -> None: ...

    async def record_run_yielded(
        self,
        run: Run,
        *,
        delay_seconds: int,
        expected_generation: int,
    ) -> None: ...


class ExecutionRecorderFactory(Protocol):
    def __call__(self, *, run_id: UUID, generation: int) -> ExecutionRecorder: ...


class RuntimeStore(Protocol):
    async def create_run(
        self,
        *,
        agent_version_id: UUID,
        input_text: str,
        idempotency_key: str,
        principal_scope: str,
    ) -> Run: ...

    async def get_run(self, run_id: UUID) -> Run | None: ...

    async def claim_next_run(self, *, worker_id: str, lease_seconds: int) -> Run | None: ...

    async def renew_lease(
        self,
        *,
        run_id: UUID,
        worker_id: str,
        expected_generation: int,
        lease_seconds: int,
    ) -> bool: ...

    async def load_run_state(self, run_id: UUID) -> RunState: ...

    async def load_agent_version(self, agent_version_id: UUID) -> AgentVersion: ...
