# Stage 3.2-A2 — Durable Budget, Deadline, and Cooperative Yield

Status: **ACCEPTED**
Parent: **Stage 3.2 Durable Runtime Design V1.0 — FROZEN**
Previous slice: **Stage 3.2-A1 — ACCEPTED**

## Accepted implementation

Implementation commit:

`a51e5471fafc0106f8f52e7969a19a65e1703503`

A2 adds:

- immutable Run limits:
  - max_model_invocations;
  - max_tool_attempts;
  - deadline_at;
- durable RunState usage:
  - model_invocations_used;
  - tool_attempts_used;
- usage reservation atomically with STARTED ModelInvocation / ToolExecutionAttempt;
- PostgreSQL `clock_timestamp()` as authoritative deadline clock;
- model-result consequence fencing after deadline;
- MODEL_RESULT_DISCARDED;
- cooperative durable yield:
  - RUNNING -> QUEUED;
  - QueueReason.YIELD;
  - DB-derived available_at;
  - lease/owner release;
- progression-step cap per claim;
- frozen QueueReason expansion needed by Stage 3.2.

Migration head:

`0007_run_limits`

## Final review

Verified:

- PostgreSQL persistence uses `clock_timestamp()`, not worker-local time, for
  deadline and durable scheduling correctness;
- yield is one fenced transaction under the Run lock;
- yield releases owner_worker_id and lease_expires_at;
- model/business work cannot start after durable budget/deadline denial;
- a still-authorized model result crossing deadline is recorded but discarded
  for business progression;
- client Run creation surface does not accept arbitrary runtime budget/deadline
  overrides in this slice.

## Target acceptance

GitHub Actions:

- workflow: Stage 3.2-A2 Acceptance
- run ID: `37198621802`
- conclusion: **SUCCESS**
- accepted main head: `9f636b1e7e136cea206ef54d8b86ef35b7582ebc`

Evidence:

- Ruff: PASS;
- Ruff format: PASS, 50 files;
- mypy: PASS, 27 source files;
- PostgreSQL: major 18;
- Alembic: 0001 -> 0007 PASS;
- full suite: **85 passed**.

## Gate

```text
Stage 3.2-A1
✅ ACCEPTED

Stage 3.2-A2
✅ ACCEPTED

Stage 3.2-A3 — READ transient retry/backoff
🔓 UNLOCKED

Stage 3.2-B — ActionSnapshot + ExternalAction
🔒

Stage 3.2 Runtime Acceptance
🔒

Stage 3.3
🔒
```
