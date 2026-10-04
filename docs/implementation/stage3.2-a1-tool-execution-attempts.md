# Stage 3.2-A1 — Unified READ ToolExecutionAttempt

Status: **IMPLEMENTED / SLICE GATE PASSED**
Parent design: **Stage 3.2 Durable Runtime Design V1.0 — FROZEN**
Parent runtime baseline: **Stage 3.1 Core Runtime V1.0 — FROZEN**

## Scope implemented

This slice introduces the physical Tool execution layer for the existing READ
runtime without changing the logical ToolCall contract.

Implemented:

- ToolExecutionAttemptStatus:
  - STARTED
  - SUCCEEDED
  - FAILED
  - UNKNOWN
- ToolExecutionAttempt domain model;
- PostgreSQL tool_execution_attempts table;
- unique (tool_call_id, attempt_number);
- one STARTED physical attempt per ToolCall;
- execution_generation persisted on attempts;
- every new READ physical invocation creates a durable STARTED attempt before
  adapter invocation;
- deterministic recovered READ retry creates the next attempt number while
  reusing the same logical ToolCall;
- takeover closes an orphaned READ STARTED attempt as UNKNOWN with
  LEASE_LOST_RESULT_NOT_DURABLE before returning ToolCall to READY;
- READ success/failure finalizes the current physical attempt;
- Stage 3.1 logical ToolCall identity and deterministic recovery semantics are
  preserved.

## Migration

New migration:

`0006_tool_attempts`

Parent:

`0005_run_terminal_shape`

No accepted Stage 3.1 migration was modified.

## Target gate evidence

GitHub Actions:

- workflow: Stage 3.2-A1 Unified Tool Attempts
- run ID: 37194901015
- conclusion: SUCCESS
- implementation commit:
  `b917062ddc2f0ac4ab498b06ea4fc35ea8e744c7`

Target evidence:

- CPython 3.14.7;
- Ruff lint: PASS;
- Ruff format: PASS, 49 files;
- mypy: PASS, 27 source files;
- PostgreSQL major: 18;
- Alembic online migration through 0006: PASS;
- full suite: **71 passed**;
- temporary patcher removed before implementation commit.

## Explicitly not implemented in A1

A1 does not implement:

- durable task Budget;
- durable deadline;
- delayed retry/backoff policy;
- durable Run yield/requeue;
- ExternalAction;
- ActionSnapshot;
- side-effect execution;
- UNKNOWN side-effect reconciliation;
- cancellation expansion;
- manual action resolution;
- checkpoint V1.

These remain later Stage 3.2 slices.

## Gate

```text
Stage 3.2-A1
✅ IMPLEMENTED
✅ TARGET SLICE GATE PASSED

Stage 3.2-A2 — Budget / Deadline / Durable Yield
🔓 UNLOCKED

Stage 3.2 Side Effects
🔒 NOT YET

Stage 3.2 Runtime Acceptance
🔒 NOT YET

Stage 3.3
🔒
```
