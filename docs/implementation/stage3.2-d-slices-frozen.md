# Stage 3.2-D Implementation Slices — FROZEN EXECUTION PLAN

Status: **IMPLEMENTATION PLAN FROZEN**

Parent contracts:
- `docs/design/stage3.2-durable-runtime-v1.0-frozen.md`
- `docs/acceptance/stage3.2-acceptance-v1.0-frozen.md`
- `docs/implementation/stage3.2-c-accepted.md`

Stage 3.2-D remains one aggregate acceptance unit, but implementation is split
into three independently gated slices so no reconciliation/recovery behavior is
accepted implicitly.

## D1 — Physical side-effect result classification + UNKNOWN boundary

Scope:
- add ToolCall `UNRESOLVED` projection;
- classify explicit definite-not-executed adapter failures;
- conservatively classify possible/ambiguous execution as UNKNOWN;
- unknown/unclassified exception after Action Commit must become UNKNOWN, never
  an implicit retry;
- atomically persist:
  - ToolExecutionAttempt STARTED -> UNKNOWN;
  - ExternalAction EXECUTING -> UNKNOWN;
  - current_attempt_id -> NULL;
  - ToolCall EXECUTING -> UNRESOLVED;
- block new model reasoning while an UNKNOWN action exists;
- preserve stable operation_id / ActionSnapshot;
- no reconciliation request yet;
- no automatic side-effect retry yet.

D1 is intentionally a safety stop. A Run with UNKNOWN durable truth may remain
nonterminal until D2/D3 add the recovery/reconciliation continuation path.

## D2 — Orphan takeover + safe side-effect retry

Scope:
- recover orphaned STARTED side-effect attempt after lease loss;
- old Attempt -> UNKNOWN with
  `LEASE_LOST_RESULT_NOT_DURABLE`;
- Action -> UNKNOWN, current_attempt_id -> NULL;
- ToolCall -> UNRESOLVED;
- no replacement side-effect attempt before reconciliation;
- add explicit retryable definite-not-executed side-effect failure policy;
- safe retry retains ExternalAction + ActionSnapshot + operation_id;
- delayed retry uses durable RETRY yield/requeue;
- attempt number remains monotonic across restart/takeover;
- budget/deadline exhaustion stabilizes without duplicate effect.

D2 may add a narrowly typed retryable adapter failure signal. It may not make
generic exceptions retryable.

## D3 — ReconciliationAttempt + resolution modes + safety budget

Scope:
- durable ReconciliationAttempt lifecycle;
- STARTED row committed before physical reconciliation query;
- AUTHORITATIVE / BEST_EFFORT / NONE semantics;
- bounded reconciliation retry policy and DB-time scheduling;
- reconciliation transport failure does not change business truth;
- UNKNOWN/NOT_EXECUTED handling follows frozen capability safety rules;
- NONE and unresolved unsafe BEST_EFFORT results stop at MANUAL_REVIEW state;
- no model reconstruction of action identity;
- no blind retry of non-idempotent actions;
- orphan reconciliation recovery;
- Stage 3.2-D aggregate acceptance.

Cancellation/manual ActionResolution behavior remains deferred to Stage 3.2-E,
so D3 may create the action-side MANUAL_REVIEW truth but must not claim the full
E Run-state/manual-resolution contract.

## Gate discipline

For each slice:

```text
implement
  ↓
target gate
  ↓
review frozen-parent regressions
  ↓
record accepted slice evidence
  ↓
unlock next slice
```

Stage 3.2-D aggregate acceptance stays locked until D1, D2 and D3 have each
passed their target gates and the independent D aggregate workflow passes.

Governing safety rules:

> Intent Before Effect.

> Action Commit Before Effect.

> UNKNOWN Before Retry when external truth is uncertain.
