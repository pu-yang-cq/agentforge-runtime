# Stage 3.2-A3 — Durable READ Transient Retry

Status: **IMPLEMENTED / SLICE GATE PASSED**
Parent design: **Stage 3.2 Durable Runtime Design V1.0 — FROZEN**

## Scope implemented

This slice completes the READ retry portion of Stage 3.2-A.

Implemented:

- explicit structured transient adapter failure classification;
- retry is opt-in and is not inferred from arbitrary exceptions;
- durable versioned READ retry policy on ToolVersion;
- retry attempt count is derived from durable ToolExecutionAttempt history;
- exponential backoff bounded by the versioned maximum;
- transient READ failure finalizes the current physical attempt;
- retryable logical ToolCall returns to READY;
- Run durably yields to QUEUED with RETRY scheduling;
- available_at controls future claim eligibility using PostgreSQL database time;
- retry reuses the same logical ToolCall, ToolVersion and arguments;
- tool-attempt budget and deadline remain authoritative across retries.

## Migration

New migration:

`0008_read_retry_policy`

Parent:

`0007_run_limits`

## Target gate evidence

GitHub Actions:

- workflow: Stage 3.2-A3 READ Retry
- run ID: 37200350033
- conclusion: SUCCESS
- implementation commit:
  `d364fba378bbbafb6e442d70ecfef736a5bd6399`

Target evidence:

- Ruff lint: PASS;
- Ruff format: PASS, 51 files;
- mypy: PASS, 27 source files;
- PostgreSQL major: 18;
- Alembic online migration through 0008: PASS;
- full suite: **90 passed**.

## Explicitly not implemented in A3

A3 does not implement:

- ActionSnapshot;
- ExternalAction;
- side-effect execution;
- Action Commit Boundary;
- reconciliation;
- cancellation expansion;
- manual resolution;
- checkpoint V1.

## Gate

```text
Stage 3.2-A1
✅ COMPLETE

Stage 3.2-A2
✅ ACCEPTED

Stage 3.2-A3
✅ IMPLEMENTED
✅ TARGET SLICE GATE PASSED

Stage 3.2-A aggregate acceptance
🟡 REQUIRED BEFORE B

Stage 3.2-B
🔒
```
