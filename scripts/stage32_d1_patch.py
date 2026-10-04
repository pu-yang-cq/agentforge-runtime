from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one anchor, found {count}: {old[:140]!r}")
    file.write_text(text.replace(old, new))


def append_text(path: str, marker: str, block: str) -> None:
    file = Path(path)
    text = file.read_text()
    if marker in text:
        raise SystemExit(f"{path}: marker already present: {marker}")
    file.write_text(text + block)


# ---------------------------------------------------------------------------
# Domain states: UNKNOWN side-effect truth projects ToolCall -> UNRESOLVED.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/domain/enums.py",
    '''class ToolCallStatus(StrEnum):
    CREATED = "CREATED"
    READY = "READY"
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
''',
    '''class ToolCallStatus(StrEnum):
    CREATED = "CREATED"
    READY = "READY"
    EXECUTING = "EXECUTING"
    UNRESOLVED = "UNRESOLVED"
    SUCCEEDED = "SUCCEEDED"
''',
)

replace_once(
    "src/agentforge/domain/enums.py",
    '''    ACTION_COMMITTED = "ACTION_COMMITTED"
    ACTION_SUCCEEDED = "ACTION_SUCCEEDED"
    ACTION_ABORTED = "ACTION_ABORTED"
''',
    '''    ACTION_COMMITTED = "ACTION_COMMITTED"
    ACTION_SUCCEEDED = "ACTION_SUCCEEDED"
    ACTION_UNKNOWN = "ACTION_UNKNOWN"
    ACTION_FAILED = "ACTION_FAILED"
    ACTION_ABORTED = "ACTION_ABORTED"
''',
)

replace_once(
    "src/agentforge/domain/actions.py",
    '''    def succeed(self) -> None:
        if self.status is not ExternalActionStatus.EXECUTING or self.current_attempt_id is None:
            raise ValueError("external action can only succeed from EXECUTING")
        self.status = ExternalActionStatus.SUCCEEDED
        self.current_attempt_id = None

    def abort(self) -> None:
''',
    '''    def succeed(self) -> None:
        if self.status is not ExternalActionStatus.EXECUTING or self.current_attempt_id is None:
            raise ValueError("external action can only succeed from EXECUTING")
        self.status = ExternalActionStatus.SUCCEEDED
        self.current_attempt_id = None

    def mark_unknown(self) -> None:
        if self.status is not ExternalActionStatus.EXECUTING or self.current_attempt_id is None:
            raise ValueError("external action can only become UNKNOWN from EXECUTING")
        self.status = ExternalActionStatus.UNKNOWN
        self.current_attempt_id = None

    def fail_definite_not_executed(self) -> None:
        if self.status is not ExternalActionStatus.EXECUTING or self.current_attempt_id is None:
            raise ValueError("external action can only fail from EXECUTING")
        self.status = ExternalActionStatus.FAILED
        self.current_attempt_id = None

    def abort(self) -> None:
''',
)

replace_once(
    "src/agentforge/domain/models.py",
    '''    def not_executed(self, reason: str) -> None:
        if self.status is not ToolCallStatus.READY:
            raise ValueError("tool call can only become NOT_EXECUTED from READY")
        self.status = ToolCallStatus.NOT_EXECUTED
        self.error = reason

    def retry_after_failure(self, reason: str) -> None:
''',
    '''    def not_executed(self, reason: str) -> None:
        if self.status is not ToolCallStatus.READY:
            raise ValueError("tool call can only become NOT_EXECUTED from READY")
        self.status = ToolCallStatus.NOT_EXECUTED
        self.error = reason

    def unresolve(self, reason: str) -> None:
        if self.status is not ToolCallStatus.EXECUTING:
            raise ValueError("tool call can only become UNRESOLVED from EXECUTING")
        self.status = ToolCallStatus.UNRESOLVED
        self.error = reason

    def retry_after_failure(self, reason: str) -> None:
''',
)

replace_once(
    "src/agentforge/domain/models.py",
    '''    def mark_unknown(self, reason: str) -> None:
        if self.status is not ToolExecutionAttemptStatus.STARTED:
            raise ValueError("tool attempt can only become UNKNOWN from STARTED")
        self.status = ToolExecutionAttemptStatus.UNKNOWN
        self.outcome_reason = reason
        self.finished_at = utcnow()
''',
    '''    def mark_unknown(
        self,
        reason: str,
        *,
        error: str | None = None,
        error_class: str | None = None,
    ) -> None:
        if self.status is not ToolExecutionAttemptStatus.STARTED:
            raise ValueError("tool attempt can only become UNKNOWN from STARTED")
        self.status = ToolExecutionAttemptStatus.UNKNOWN
        self.error = error
        self.error_class = error_class
        self.definite_not_executed = False
        self.outcome_reason = reason
        self.finished_at = utcnow()
''',
)


# ---------------------------------------------------------------------------
# Recorder protocol: unknown truth is durable and blocks new model reasoning.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/application/ports.py",
    '''    async def load_ready_external_action(
        self,
        run_id: UUID,
    ) -> tuple[ToolCall, ActionSnapshot, ExternalAction] | None: ...

    async def record_side_effect_attempt_started(
''',
    '''    async def load_ready_external_action(
        self,
        run_id: UUID,
    ) -> tuple[ToolCall, ActionSnapshot, ExternalAction] | None: ...

    async def load_unknown_external_action(
        self,
        run_id: UUID,
    ) -> tuple[ToolCall, ActionSnapshot, ExternalAction] | None: ...

    async def record_side_effect_attempt_started(
''',
)

replace_once(
    "src/agentforge/application/ports.py",
    '''    async def record_side_effect_succeeded(
        self,
        call: ToolCall,
        action: ExternalAction,
        attempt: ToolExecutionAttempt,
        message: RunMessage,
        *,
        expected_generation: int,
    ) -> None: ...

    async def record_recovered_read_started(
''',
    '''    async def record_side_effect_succeeded(
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
''',
)


# ---------------------------------------------------------------------------
# In-memory journal implementation and safety stop.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/application/run_manager.py",
    '''from agentforge.application.errors import (
    BusinessProgressionBlockedError,
    RunExecutionFailedError,
    ToolTransientError,
)
''',
    '''from agentforge.application.errors import (
    BusinessProgressionBlockedError,
    RunExecutionFailedError,
    ToolAdapterError,
    ToolTransientError,
)
''',
)

replace_once(
    "src/agentforge/application/run_manager.py",
    '''        if call.status is not ToolCallStatus.READY:
            raise RuntimeError("READY ExternalAction does not project to READY ToolCall")
        return call, snapshot, action

    async def record_side_effect_attempt_started(
''',
    '''        if call.status is not ToolCallStatus.READY:
            raise RuntimeError("READY ExternalAction does not project to READY ToolCall")
        return call, snapshot, action

    async def load_unknown_external_action(
        self,
        run_id: UUID,
    ) -> tuple[ToolCall, ActionSnapshot, ExternalAction] | None:
        actions = [
            action
            for action in self.external_actions
            if action.run_id == run_id and action.status is ExternalActionStatus.UNKNOWN
        ]
        if len(actions) > 1:
            raise RuntimeError("found multiple UNKNOWN ExternalActions for one Run")
        if not actions:
            return None
        action = actions[0]
        call = next(item for item in self.tool_calls if item.id == action.tool_call_id)
        snapshot = next(
            item for item in self.action_snapshots if item.id == action.action_snapshot_id
        )
        if action.current_attempt_id is not None:
            raise RuntimeError("UNKNOWN ExternalAction cannot retain current_attempt_id")
        if call.status is not ToolCallStatus.UNRESOLVED:
            raise RuntimeError("UNKNOWN ExternalAction does not project to UNRESOLVED ToolCall")
        return call, snapshot, action

    async def record_side_effect_attempt_started(
''',
)

replace_once(
    "src/agentforge/application/run_manager.py",
    '''    async def record_recovered_read_started(
        self,
        call: ToolCall,
        *,
        expected_generation: int,
    ) -> None:
''',
    '''    async def record_side_effect_unknown(
        self,
        call: ToolCall,
        action: ExternalAction,
        attempt: ToolExecutionAttempt,
        *,
        error: str,
        error_class: str,
        outcome_reason: str,
        expected_generation: int,
    ) -> None:
        if call.status is not ToolCallStatus.EXECUTING:
            raise ValueError("UNKNOWN persistence requires EXECUTING ToolCall")
        if action.status is not ExternalActionStatus.EXECUTING:
            raise ValueError("UNKNOWN persistence requires EXECUTING ExternalAction")
        if action.current_attempt_id != attempt.id:
            raise ValueError("UNKNOWN persistence attempt is not current")
        durable_attempt = self._started_tool_attempt(call.id)
        if durable_attempt.id != attempt.id or durable_attempt.external_action_id != action.id:
            raise RuntimeError("UNKNOWN durable attempt mismatch")
        durable_attempt.mark_unknown(
            outcome_reason,
            error=error,
            error_class=error_class,
        )
        call.unresolve(error)
        action.mark_unknown()
        self.events.append(
            DomainEvent(
                call.run_id,
                len(self.events) + 1,
                EventType.ACTION_UNKNOWN,
                {
                    "tool_call_id": str(call.id),
                    "external_action_id": str(action.id),
                    "operation_id": str(action.operation_id),
                    "attempt_id": str(attempt.id),
                    "attempt_number": attempt.attempt_number,
                    "error_class": error_class,
                    "outcome_reason": outcome_reason,
                },
            )
        )

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
    ) -> None:
        if run.status is not RunStatus.FAILED:
            raise ValueError("definite side-effect failure requires FAILED Run")
        if call.status is not ToolCallStatus.EXECUTING:
            raise ValueError("definite side-effect failure requires EXECUTING ToolCall")
        if action.status is not ExternalActionStatus.EXECUTING:
            raise ValueError("definite side-effect failure requires EXECUTING ExternalAction")
        if action.current_attempt_id != attempt.id:
            raise ValueError("definite side-effect failure attempt is not current")
        durable_attempt = self._started_tool_attempt(call.id)
        if durable_attempt.id != attempt.id or durable_attempt.external_action_id != action.id:
            raise RuntimeError("definite side-effect durable attempt mismatch")
        durable_attempt.fail(
            error,
            error_class=error_class,
            definite_not_executed=True,
            outcome_reason="SIDE_EFFECT_DEFINITE_NOT_EXECUTED",
        )
        call.fail(error)
        action.fail_definite_not_executed()
        self._append_event(
            run,
            EventType.ACTION_FAILED,
            {
                "tool_call_id": str(call.id),
                "external_action_id": str(action.id),
                "operation_id": str(action.operation_id),
                "attempt_id": str(attempt.id),
                "attempt_number": attempt.attempt_number,
                "error_class": error_class,
                "definite_not_executed": True,
            },
        )
        self._append_event(
            run,
            EventType.TOOL_FAILED,
            {
                "tool_call_id": str(call.id),
                "tool_name": call.tool_name,
                "attempt_id": str(attempt.id),
                "attempt_number": attempt.attempt_number,
                "error_class": error_class,
                "definite_not_executed": True,
                "error": error,
            },
        )
        self._append_event(run, EventType.RUN_FAILED, {"reason": run.failure_reason})

    async def record_recovered_read_started(
        self,
        call: ToolCall,
        *,
        expected_generation: int,
    ) -> None:
''',
)


# ---------------------------------------------------------------------------
# RunManager: ambiguous truth is UNKNOWN and stops progression immediately.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/application/run_manager.py",
    '''    async def _execute_side_effect_action(
        self,
        *,
        run: Run,
        prepared: PreparedExternalAction,
        recorder: ExecutionRecorder,
        expected_generation: int,
    ) -> RunMessage:
''',
    '''    async def _execute_side_effect_action(
        self,
        *,
        run: Run,
        prepared: PreparedExternalAction,
        recorder: ExecutionRecorder,
        expected_generation: int,
    ) -> RunMessage | None:
''',
)

replace_once(
    "src/agentforge/application/run_manager.py",
    '''        call = await self._tools.execute_side_effect(prepared, attempt)
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
''',
    '''        try:
            call = await self._tools.execute_side_effect(prepared, attempt)
        except ToolAdapterError as exc:
            if exc.definite_not_executed:
                reason = f"side-effect tool {prepared.call.tool_name} definitely did not execute: {exc}"
                run.fail(reason)
                await recorder.record_side_effect_definite_failure_and_fail_run(
                    prepared.call,
                    prepared.action,
                    attempt,
                    run,
                    error=str(exc),
                    error_class=exc.error_class,
                    expected_generation=expected_generation,
                )
                raise RunExecutionFailedError(run.failure_reason) from exc
            await recorder.record_side_effect_unknown(
                prepared.call,
                prepared.action,
                attempt,
                error=str(exc),
                error_class=exc.error_class,
                outcome_reason="SIDE_EFFECT_POSSIBLE_EXECUTION",
                expected_generation=expected_generation,
            )
            return None
        except Exception as exc:
            await recorder.record_side_effect_unknown(
                prepared.call,
                prepared.action,
                attempt,
                error=str(exc),
                error_class=type(exc).__name__,
                outcome_reason="SIDE_EFFECT_UNCLASSIFIED_EXCEPTION_AFTER_COMMIT",
                expected_generation=expected_generation,
            )
            return None

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
''',
)

replace_once(
    "src/agentforge/application/run_manager.py",
    '''        progression_steps = 0
        prepared: PreparedToolCall | PreparedExternalAction

        ready_action = await recorder.load_ready_external_action(run.id)
''',
    '''        progression_steps = 0
        prepared: PreparedToolCall | PreparedExternalAction

        # D1 safety stop: unresolved external truth outranks new model reasoning.
        # D2/D3 will add takeover/reconciliation continuation from this durable fact.
        unknown_action = await recorder.load_unknown_external_action(run.id)
        if unknown_action is not None:
            return None

        ready_action = await recorder.load_ready_external_action(run.id)
''',
)

replace_once(
    "src/agentforge/application/run_manager.py",
    '''            recovered_message = await self._execute_side_effect_action(
                run=run,
                prepared=prepared_action,
                recorder=recorder,
                expected_generation=expected_generation,
            )
            messages.append(recovered_message)
            progression_steps += 1
''',
    '''            recovered_message = await self._execute_side_effect_action(
                run=run,
                prepared=prepared_action,
                recorder=recorder,
                expected_generation=expected_generation,
            )
            if recovered_message is None:
                return None
            messages.append(recovered_message)
            progression_steps += 1
''',
)

replace_once(
    "src/agentforge/application/run_manager.py",
    '''                side_effect_message = await self._execute_side_effect_action(
                    run=run,
                    prepared=prepared,
                    recorder=recorder,
                    expected_generation=expected_generation,
                )
                messages.append(side_effect_message)
                progression_steps += 1
                continue
''',
    '''                side_effect_message = await self._execute_side_effect_action(
                    run=run,
                    prepared=prepared,
                    recorder=recorder,
                    expected_generation=expected_generation,
                )
                if side_effect_message is None:
                    return None
                messages.append(side_effect_message)
                progression_steps += 1
                continue
''',
)


# ---------------------------------------------------------------------------
# PostgreSQL recorder: Run -> Action -> ToolCall -> Attempt lock order.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''        return (
            tool_call_from_row(call_row),
            action_snapshot_from_row(snapshot_row),
            external_action_from_row(action_row),
        )

    async def record_side_effect_attempt_started(
''',
    '''        return (
            tool_call_from_row(call_row),
            action_snapshot_from_row(snapshot_row),
            external_action_from_row(action_row),
        )

    async def load_unknown_external_action(
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
                        ExternalActionRow.status == ExternalActionStatus.UNKNOWN,
                        ExternalActionRow.current_attempt_id.is_(None),
                        ToolCallRow.status == ToolCallStatus.UNRESOLVED,
                    )
                )
            ).all()
        if len(rows) > 1:
            raise RuntimeError("found multiple UNKNOWN ExternalActions for one Run")
        if not rows:
            return None
        action_row, call_row, snapshot_row = rows[0]
        return (
            tool_call_from_row(call_row),
            action_snapshot_from_row(snapshot_row),
            external_action_from_row(action_row),
        )

    async def record_side_effect_attempt_started(
''',
)

replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''        attempt.succeed(call.result)
        action.succeed()

    async def record_recovered_read_started(
''',
    '''        attempt.succeed(call.result)
        action.succeed()

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
    ) -> None:
        """Persist possible execution as UNKNOWN; never convert uncertainty to retry."""
        self._assert_generation(expected_generation)
        if call.status is not ToolCallStatus.EXECUTING:
            raise ValueError("UNKNOWN persistence requires EXECUTING ToolCall")
        if action.status is not ExternalActionStatus.EXECUTING:
            raise ValueError("UNKNOWN persistence requires EXECUTING ExternalAction")
        if action.current_attempt_id != attempt.id:
            raise ValueError("UNKNOWN persistence attempt is not current")

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
                raise RuntimeError("side-effect UNKNOWN result lost current-attempt authorization")

            attempt_row.status = ToolExecutionAttemptStatus.UNKNOWN
            attempt_row.error = error
            attempt_row.error_class = error_class
            attempt_row.definite_not_executed = False
            attempt_row.outcome_reason = outcome_reason
            attempt_row.finished_at = func.clock_timestamp()
            call_row.status = ToolCallStatus.UNRESOLVED
            call_row.error = error
            action_row.status = ExternalActionStatus.UNKNOWN
            action_row.current_attempt_id = None
            action_row.updated_at = func.clock_timestamp()

            seq = next(iter(await _allocate_event_sequences(session, call.run_id, 1)))
            session.add(
                DomainEventRow(
                    id=uuid4(),
                    run_id=call.run_id,
                    sequence=seq,
                    event_type=EventType.ACTION_UNKNOWN.value,
                    payload={
                        "tool_call_id": str(call.id),
                        "external_action_id": str(action.id),
                        "operation_id": str(action.operation_id),
                        "attempt_id": str(attempt.id),
                        "attempt_number": attempt.attempt_number,
                        "error_class": error_class,
                        "outcome_reason": outcome_reason,
                    },
                )
            )
            await session.flush()

        attempt.mark_unknown(
            outcome_reason,
            error=error,
            error_class=error_class,
        )
        call.unresolve(error)
        action.mark_unknown()

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
    ) -> None:
        """Persist proven non-execution as FAILED; retry policy is deferred to D2."""
        self._assert_generation(expected_generation)
        if run.status is not RunStatus.FAILED:
            raise ValueError("definite side-effect failure requires FAILED Run")
        if call.status is not ToolCallStatus.EXECUTING:
            raise ValueError("definite side-effect failure requires EXECUTING ToolCall")
        if action.status is not ExternalActionStatus.EXECUTING:
            raise ValueError("definite side-effect failure requires EXECUTING ExternalAction")
        if action.current_attempt_id != attempt.id:
            raise ValueError("definite side-effect failure attempt is not current")

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
                raise RuntimeError(
                    "side-effect definite failure lost current-attempt authorization"
                )

            attempt_row.status = ToolExecutionAttemptStatus.FAILED
            attempt_row.error = error
            attempt_row.error_class = error_class
            attempt_row.definite_not_executed = True
            attempt_row.outcome_reason = "SIDE_EFFECT_DEFINITE_NOT_EXECUTED"
            attempt_row.finished_at = func.clock_timestamp()
            call_row.status = ToolCallStatus.FAILED
            call_row.error = error
            action_row.status = ExternalActionStatus.FAILED
            action_row.current_attempt_id = None
            action_row.updated_at = func.clock_timestamp()
            run_row.status = RunStatus.FAILED
            run_row.failure_reason = run.failure_reason
            run_row.completed_at = func.clock_timestamp()
            run_row.owner_worker_id = None
            run_row.lease_expires_at = None

            seqs = list(await _allocate_event_sequences(session, call.run_id, 3))
            session.add_all(
                [
                    DomainEventRow(
                        id=uuid4(),
                        run_id=call.run_id,
                        sequence=seqs[0],
                        event_type=EventType.ACTION_FAILED.value,
                        payload={
                            "tool_call_id": str(call.id),
                            "external_action_id": str(action.id),
                            "operation_id": str(action.operation_id),
                            "attempt_id": str(attempt.id),
                            "attempt_number": attempt.attempt_number,
                            "error_class": error_class,
                            "definite_not_executed": True,
                        },
                    ),
                    DomainEventRow(
                        id=uuid4(),
                        run_id=call.run_id,
                        sequence=seqs[1],
                        event_type=EventType.TOOL_FAILED.value,
                        payload={
                            "tool_call_id": str(call.id),
                            "tool_name": call.tool_name,
                            "attempt_id": str(attempt.id),
                            "attempt_number": attempt.attempt_number,
                            "error_class": error_class,
                            "definite_not_executed": True,
                            "error": error,
                        },
                    ),
                    DomainEventRow(
                        id=uuid4(),
                        run_id=call.run_id,
                        sequence=seqs[2],
                        event_type=EventType.RUN_FAILED.value,
                        payload={"reason": run.failure_reason},
                    ),
                ]
            )
            await session.flush()

        attempt.fail(
            error,
            error_class=error_class,
            definite_not_executed=True,
            outcome_reason="SIDE_EFFECT_DEFINITE_NOT_EXECUTED",
        )
        call.fail(error)
        action.fail_definite_not_executed()

    async def record_recovered_read_started(
''',
)


# ---------------------------------------------------------------------------
# Migration 0011: ToolCall UNRESOLVED projection.
# ---------------------------------------------------------------------------
Path("migrations/versions/0011_side_effect_unknown.py").write_text(
    '''"""add side-effect UNKNOWN ToolCall projection

Revision ID: 0011_side_effect_unknown
Revises: 0010_side_effect_preparation
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011_side_effect_unknown"
down_revision: str | None = "0010_side_effect_preparation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE tool_call_status ADD VALUE IF NOT EXISTS 'UNRESOLVED'")


def downgrade() -> None:
    # PostgreSQL enum-value removal requires type recreation. Stage 3.2 migrations
    # preserve enum history rather than rewrite accepted prior values.
    pass
'''
)


# ---------------------------------------------------------------------------
# D1 unit coverage.
# ---------------------------------------------------------------------------
replace_once(
    "tests/unit/test_run_manager.py",
    '''from agentforge.application.errors import RunExecutionFailedError, ToolTransientError
''',
    '''from agentforge.application.errors import (
    RunExecutionFailedError,
    ToolAdapterError,
    ToolTransientError,
)
''',
)

append_text(
    "tests/unit/test_run_manager.py",
    "test_side_effect_possible_execution_becomes_unknown_and_stops_reasoning",
    r'''


@pytest.mark.asyncio
async def test_side_effect_possible_execution_becomes_unknown_and_stops_reasoning() -> None:
    from agentforge.domain.enums import ExternalActionStatus, ReconciliationMode, ToolEffectType

    version_id = uuid4()
    calls = 0

    async def ambiguous(_invocation):
        nonlocal calls
        calls += 1
        raise ToolAdapterError(
            "provider timed out after request write",
            error_class="TIMEOUT",
            definite_not_executed=False,
        )

    registry = InMemoryToolRegistry(
        [
            SideEffectFunctionTool(
                version_id=version_id,
                name="create_ticket_unknown",
                description="create ticket",
                input_schema={"type": "object"},
                func=ambiguous,
            )
        ]
    )
    model = ScriptedFakeModel(
        [
            ToolStep("create_ticket_unknown", {"summary": "ambiguous"}),
            FinalStep("must not be reached"),
        ]
    )
    manager = RunManager(NativeRunner(model, registry), ToolCoordinator(registry))
    av = AgentVersion(
        uuid4(),
        uuid4(),
        1,
        "unknown boundary",
        (
            ToolBinding(
                version_id,
                "create_ticket_unknown",
                effect_type=ToolEffectType.EXTERNAL_SIDE_EFFECT,
                allow_no_approval_execution=True,
                idempotency_supported=False,
                reconciliation_mode=ReconciliationMode.AUTHORITATIVE,
            ),
        ),
    )
    run = Run(uuid4(), av.id, "create ticket")
    run.queue()
    state = RunState(run.id)
    journal = ExecutionJournal()

    result = await manager.execute(
        run=run,
        run_state=state,
        agent_version=av,
        recorder=journal,
    )

    assert result is None
    assert calls == 1
    assert run.status is RunStatus.RUNNING
    assert state.model_invocations_used == 1
    assert state.tool_attempts_used == 1
    assert journal.tool_calls[0].status is ToolCallStatus.UNRESOLVED
    assert journal.tool_attempts[0].status is ToolExecutionAttemptStatus.UNKNOWN
    assert journal.tool_attempts[0].definite_not_executed is False
    assert journal.tool_attempts[0].error_class == "TIMEOUT"
    assert journal.external_actions[0].status is ExternalActionStatus.UNKNOWN
    assert journal.external_actions[0].current_attempt_id is None
    assert EventType.ACTION_UNKNOWN in [event.type for event in journal.events]

    # A second execution pass observes durable UNKNOWN first and must not ask
    # the model for a replacement proposal.
    second = await manager.execute(
        run=run,
        run_state=state,
        agent_version=av,
        recorder=journal,
    )
    assert second is None
    assert state.model_invocations_used == 1
    assert calls == 1


@pytest.mark.asyncio
async def test_unclassified_side_effect_exception_is_conservatively_unknown() -> None:
    from agentforge.domain.enums import ExternalActionStatus, ReconciliationMode, ToolEffectType

    version_id = uuid4()

    async def ambiguous(_invocation):
        raise TimeoutError("socket closed after request may have been accepted")

    registry = InMemoryToolRegistry(
        [
            SideEffectFunctionTool(
                version_id=version_id,
                name="unclassified_write",
                description="write",
                input_schema={"type": "object"},
                func=ambiguous,
            )
        ]
    )
    manager = RunManager(
        NativeRunner(
            ScriptedFakeModel([ToolStep("unclassified_write", {"value": "x"})]),
            registry,
        ),
        ToolCoordinator(registry),
    )
    av = AgentVersion(
        uuid4(),
        uuid4(),
        1,
        "conservative unknown",
        (
            ToolBinding(
                version_id,
                "unclassified_write",
                effect_type=ToolEffectType.WRITE,
                allow_no_approval_execution=True,
                reconciliation_mode=ReconciliationMode.NONE,
            ),
        ),
    )
    run = Run(uuid4(), av.id, "write")
    run.queue()
    state = RunState(run.id)
    journal = ExecutionJournal()

    assert (
        await manager.execute(
            run=run,
            run_state=state,
            agent_version=av,
            recorder=journal,
        )
        is None
    )
    assert journal.tool_attempts[0].status is ToolExecutionAttemptStatus.UNKNOWN
    assert journal.tool_attempts[0].error_class == "TimeoutError"
    assert journal.tool_calls[0].status is ToolCallStatus.UNRESOLVED
    assert journal.external_actions[0].status is ExternalActionStatus.UNKNOWN


@pytest.mark.asyncio
async def test_definite_not_executed_side_effect_failure_is_not_unknown() -> None:
    from agentforge.domain.enums import ExternalActionStatus, ReconciliationMode, ToolEffectType

    version_id = uuid4()

    async def rejected_before_send(_invocation):
        raise ToolAdapterError(
            "credential lookup failed before request",
            error_class="CREDENTIAL",
            definite_not_executed=True,
        )

    registry = InMemoryToolRegistry(
        [
            SideEffectFunctionTool(
                version_id=version_id,
                name="definite_write_failure",
                description="write",
                input_schema={"type": "object"},
                func=rejected_before_send,
            )
        ]
    )
    manager = RunManager(
        NativeRunner(
            ScriptedFakeModel([ToolStep("definite_write_failure", {})]),
            registry,
        ),
        ToolCoordinator(registry),
    )
    av = AgentVersion(
        uuid4(),
        uuid4(),
        1,
        "definite nonexecution",
        (
            ToolBinding(
                version_id,
                "definite_write_failure",
                effect_type=ToolEffectType.WRITE,
                allow_no_approval_execution=True,
                reconciliation_mode=ReconciliationMode.NONE,
            ),
        ),
    )
    run = Run(uuid4(), av.id, "write")
    run.queue()
    state = RunState(run.id)
    journal = ExecutionJournal()

    with pytest.raises(RunExecutionFailedError, match="definitely did not execute"):
        await manager.execute(
            run=run,
            run_state=state,
            agent_version=av,
            recorder=journal,
        )

    assert run.status is RunStatus.FAILED
    assert journal.tool_attempts[0].status is ToolExecutionAttemptStatus.FAILED
    assert journal.tool_attempts[0].definite_not_executed is True
    assert journal.tool_attempts[0].error_class == "CREDENTIAL"
    assert journal.tool_calls[0].status is ToolCallStatus.FAILED
    assert journal.external_actions[0].status is ExternalActionStatus.FAILED
    assert journal.external_actions[0].current_attempt_id is None
    event_types = [event.type for event in journal.events]
    assert EventType.ACTION_FAILED in event_types
    assert EventType.ACTION_UNKNOWN not in event_types
'''
)


# ---------------------------------------------------------------------------
# PostgreSQL D1 integration coverage.
# ---------------------------------------------------------------------------
replace_once(
    "tests/integration/test_postgres_runtime.py",
    '''    RunExecutionFailedError,
    StaleExecutorError,
    ToolTransientError,
)
''',
    '''    RunExecutionFailedError,
    StaleExecutorError,
    ToolAdapterError,
    ToolTransientError,
)
''',
)

append_text(
    "tests/integration/test_postgres_runtime.py",
    "test_side_effect_ambiguous_result_persists_unknown_without_new_reasoning",
    r'''


@pytest.mark.asyncio
async def test_side_effect_ambiguous_result_persists_unknown_without_new_reasoning() -> None:
    from agentforge.domain.enums import ExternalActionStatus, ReconciliationMode
    from agentforge.infrastructure.db.models import (
        ExternalActionRow,
        ModelInvocationRow,
    )

    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)

    side_tool_id = uuid4()
    side_version_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(
            ToolDefinitionRow(id=side_tool_id, name="ambiguous_ticket", description="write")
        )
        await session.flush()
        session.add(
            ToolVersionRow(
                id=side_version_id,
                tool_id=side_tool_id,
                version_number=1,
                input_schema={"type": "object"},
                effect_type=ToolEffectType.EXTERNAL_SIDE_EFFECT,
                implementation_ref="tests:ambiguous_ticket",
                allow_no_approval_execution=True,
                idempotency_supported=False,
                reconciliation_mode=ReconciliationMode.AUTHORITATIVE,
            )
        )
        await session.flush()
        session.add(
            AgentVersionToolRow(
                agent_version_id=DEMO_AGENT_VERSION_ID,
                tool_version_id=side_version_id,
                tool_alias="ambiguous_ticket",
            )
        )

    physical_calls = 0

    async def ambiguous(_invocation):
        nonlocal physical_calls
        physical_calls += 1
        raise ToolAdapterError(
            "response lost after request may have committed",
            error_class="RESPONSE_LOST",
            definite_not_executed=False,
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
                name="ambiguous_ticket",
                description="write",
                input_schema={"type": "object"},
                func=ambiguous,
            ),
        ]
    )
    store = PostgresRuntimeStore(sessions)
    created = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="ambiguous side effect",
        idempotency_key="integration-d1-ambiguous-1",
        principal_scope="test-user",
    )
    claimed = await store.claim_next_run(worker_id="worker-d1", lease_seconds=30)
    assert claimed is not None
    recorder = PostgresExecutionRecorder(
        sessions,
        run_id=created.id,
        generation=claimed.execution_generation,
    )
    manager = RunManager(
        NativeRunner(
            ScriptedFakeModel(
                [
                    ToolStep("ambiguous_ticket", {"summary": "maybe created"}),
                    FinalStep("must not be reached"),
                ]
            ),
            registry,
        ),
        ToolCoordinator(registry),
    )

    result = await manager.execute(
        run=claimed,
        run_state=await store.load_run_state(created.id),
        agent_version=await store.load_agent_version(DEMO_AGENT_VERSION_ID),
        recorder=recorder,
    )
    assert result is None
    assert physical_calls == 1

    async with sessions() as session:
        action = (
            await session.execute(
                select(ExternalActionRow).where(ExternalActionRow.run_id == created.id)
            )
        ).scalar_one()
        call = await session.get(ToolCallRow, action.tool_call_id)
        attempt = (
            await session.execute(
                select(ToolExecutionAttemptRow).where(
                    ToolExecutionAttemptRow.external_action_id == action.id
                )
            )
        ).scalar_one()
        invocations = await session.scalar(
            select(func.count())
            .select_from(ModelInvocationRow)
            .where(ModelInvocationRow.run_id == created.id)
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

    assert action.status is ExternalActionStatus.UNKNOWN
    assert action.current_attempt_id is None
    assert call is not None and call.status is ToolCallStatus.UNRESOLVED
    assert attempt.status is ToolExecutionAttemptStatus.UNKNOWN
    assert attempt.definite_not_executed is False
    assert attempt.error_class == "RESPONSE_LOST"
    assert attempt.outcome_reason == "SIDE_EFFECT_POSSIBLE_EXECUTION"
    assert invocations == 1
    assert EventType.ACTION_UNKNOWN.value in event_types

    # Same generation: durable UNKNOWN short-circuits before a second model call.
    second = await manager.execute(
        run=claimed,
        run_state=await store.load_run_state(created.id),
        agent_version=await store.load_agent_version(DEMO_AGENT_VERSION_ID),
        recorder=recorder,
    )
    assert second is None
    assert physical_calls == 1
    async with sessions() as session:
        invocations_after = await session.scalar(
            select(func.count())
            .select_from(ModelInvocationRow)
            .where(ModelInvocationRow.run_id == created.id)
        )
    assert invocations_after == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_side_effect_definite_nonexecution_persists_failed_truth() -> None:
    from agentforge.domain.enums import ExternalActionStatus, ReconciliationMode
    from agentforge.infrastructure.db.models import ExternalActionRow

    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)

    side_tool_id = uuid4()
    side_version_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(
            ToolDefinitionRow(id=side_tool_id, name="preflight_failure", description="write")
        )
        await session.flush()
        session.add(
            ToolVersionRow(
                id=side_version_id,
                tool_id=side_tool_id,
                version_number=1,
                input_schema={"type": "object"},
                effect_type=ToolEffectType.WRITE,
                implementation_ref="tests:preflight_failure",
                allow_no_approval_execution=True,
                reconciliation_mode=ReconciliationMode.NONE,
            )
        )
        await session.flush()
        session.add(
            AgentVersionToolRow(
                agent_version_id=DEMO_AGENT_VERSION_ID,
                tool_version_id=side_version_id,
                tool_alias="preflight_failure",
            )
        )

    async def definite(_invocation):
        raise ToolAdapterError(
            "credential resolution failed before external request",
            error_class="CREDENTIAL",
            definite_not_executed=True,
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
                name="preflight_failure",
                description="write",
                input_schema={"type": "object"},
                func=definite,
            ),
        ]
    )
    store = PostgresRuntimeStore(sessions)
    created = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="definite nonexecution",
        idempotency_key="integration-d1-definite-1",
        principal_scope="test-user",
    )
    claimed = await store.claim_next_run(worker_id="worker-d1-definite", lease_seconds=30)
    assert claimed is not None
    manager = RunManager(
        NativeRunner(
            ScriptedFakeModel([ToolStep("preflight_failure", {})]),
            registry,
        ),
        ToolCoordinator(registry),
    )
    recorder = PostgresExecutionRecorder(
        sessions,
        run_id=created.id,
        generation=claimed.execution_generation,
    )

    with pytest.raises(RunExecutionFailedError, match="definitely did not execute"):
        await manager.execute(
            run=claimed,
            run_state=await store.load_run_state(created.id),
            agent_version=await store.load_agent_version(DEMO_AGENT_VERSION_ID),
            recorder=recorder,
        )

    durable = await store.get_run(created.id)
    assert durable is not None and durable.status is RunStatus.FAILED
    async with sessions() as session:
        action = (
            await session.execute(
                select(ExternalActionRow).where(ExternalActionRow.run_id == created.id)
            )
        ).scalar_one()
        call = await session.get(ToolCallRow, action.tool_call_id)
        attempt = (
            await session.execute(
                select(ToolExecutionAttemptRow).where(
                    ToolExecutionAttemptRow.external_action_id == action.id
                )
            )
        ).scalar_one()
    assert action.status is ExternalActionStatus.FAILED
    assert action.current_attempt_id is None
    assert call is not None and call.status is ToolCallStatus.FAILED
    assert attempt.status is ToolExecutionAttemptStatus.FAILED
    assert attempt.definite_not_executed is True
    assert attempt.error_class == "CREDENTIAL"
    assert attempt.outcome_reason == "SIDE_EFFECT_DEFINITE_NOT_EXECUTED"
    await engine.dispose()
'''
)
