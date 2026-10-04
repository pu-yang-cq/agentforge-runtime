from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from typing import Any
from uuid import UUID

from agentforge.application.ports import ReconciliationInvocation, ReconciliationResult, Tool
from agentforge.domain.model_contract import ModelToolSpec
from agentforge.domain.models import ToolBinding


class FunctionTool(Tool):
    def __init__(
        self,
        *,
        version_id: UUID,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        func: Callable[..., Any],
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
        # Synchronous tools must never block the Worker event loop: heartbeats,
        # lease fencing, and other Runs share that loop. Async callables stay on
        # the loop; sync callables execute in a worker thread.
        if inspect.iscoroutinefunction(self._func):
            return await self._func(**arguments)
        value = await asyncio.to_thread(self._func, **arguments)
        if inspect.isawaitable(value):
            return await value
        return value


class InMemoryToolRegistry:
    def __init__(self, tools: list[Tool]) -> None:
        self._tools_by_version = {tool.version_id: tool for tool in tools}

    def specs(self, bindings: tuple[ToolBinding, ...]) -> tuple[ModelToolSpec, ...]:
        return tuple(self._get_bound_tool(binding).spec for binding in bindings)

    def resolve(self, name: str, bindings: tuple[ToolBinding, ...]) -> Tool:
        matches = [binding for binding in bindings if binding.name == name]
        if len(matches) != 1:
            raise PermissionError(f"tool is not uniquely bound to agent version: {name}")
        return self._get_bound_tool(matches[0])

    def _get_bound_tool(self, binding: ToolBinding) -> Tool:
        try:
            tool = self._tools_by_version[binding.tool_version_id]
        except KeyError as exc:
            raise KeyError(f"unregistered tool version: {binding.tool_version_id}") from exc
        if tool.spec.name != binding.name:
            raise ValueError("tool binding name/version mismatch")
        return tool


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
        reconcile_func: Callable[[object], Any] | None = None,
    ) -> None:
        self._version_id = version_id
        self._spec = ModelToolSpec(name, description, input_schema)
        self._func = func
        self._reconcile_func = reconcile_func

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

    async def reconcile(self, invocation: ReconciliationInvocation) -> ReconciliationResult:
        if self._reconcile_func is None:
            raise RuntimeError("tool adapter has no reconciliation implementation")
        if inspect.iscoroutinefunction(self._reconcile_func):
            value = await self._reconcile_func(invocation)
        else:
            value = await asyncio.to_thread(self._reconcile_func, invocation)
            if inspect.isawaitable(value):
                value = await value
        if not isinstance(value, ReconciliationResult):
            raise TypeError("reconciliation adapter must return ReconciliationResult")
        return value
