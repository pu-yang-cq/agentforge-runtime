# Stage 3.2-D3 — Durable Reconciliation — ACCEPTED / FROZEN

Status: **ACCEPTED / FROZEN**

Parent frozen surfaces:
- Stage 3.2-A
- Stage 3.2-B
- Stage 3.2-C
- Stage 3.2-D1 UNKNOWN boundary
- Stage 3.2-D2 safe side-effect retry + orphan takeover
- `docs/implementation/stage3.2-d-slices-frozen.md`

Implementation commit:
- `9e8fb391bace884775a34f53015c220d2fecc2af`

Target implementation gate:
- workflow: **Stage 3.2-D3 Reconciliation**
- successful run: `37211132877`

Independent acceptance:
- workflow: **Stage 3.2-D3 Acceptance**
- successful run: `37211514523`

## Accepted D3 semantics

### Reconciliation is a distinct physical read-only attempt

D3 introduces durable `ReconciliationAttempt` facts independent from
`ToolExecutionAttempt`.

Lifecycle:

```text
UNKNOWN ExternalAction
UNRESOLVED ToolCall
        ↓
lock owned Run
lock ExternalAction
verify unresolved truth
        ↓
persist ReconciliationAttempt STARTED
ExternalAction -> RECONCILING
COMMIT
        ↓
only now perform physical reconciliation query
```

The physical query may never occur before the STARTED attempt is durable.

### Reconciliation result classes

The reconciliation adapter returns one of:

```text
SUCCEEDED
FAILED
NOT_EXECUTED
UNKNOWN
```

with optional evidence.

### AUTHORITATIVE

AUTHORITATIVE evidence is allowed to finalize external business truth.

- SUCCEEDED -> Action SUCCEEDED, ToolCall SUCCEEDED, tool message may continue reasoning.
- FAILED -> Action FAILED, ToolCall FAILED, Run FAILED.
- NOT_EXECUTED -> may authorize the frozen safe side-effect retry path, subject to retry
  attempts, Tool attempt budget, and Run deadline.
- UNKNOWN -> MANUAL_REVIEW.

### BEST_EFFORT

BEST_EFFORT never broadens non-idempotent retry safety.

- SUCCEEDED / FAILED may be recorded according to the accepted reconciliation contract.
- NOT_EXECUTED may authorize retry only when the ToolVersion independently declares
  sufficient idempotency support.
- non-idempotent NOT_EXECUTED -> MANUAL_REVIEW.
- UNKNOWN -> MANUAL_REVIEW.

### NONE

NONE performs no physical reconciliation query.

The unresolved action moves to:

```text
ExternalAction -> MANUAL_REVIEW
ToolCall remains UNRESOLVED
Run -> WAITING_ACTION_RESOLUTION
```

This is only the D3 stopping state required by the frozen Stage 3.2 state machine.

D3 does **not** implement:
- ActionResolution;
- manual resolution API/transaction;
- cancel_requested;
- cancellation races;
- late-result-vs-manual-resolution semantics.

Those remain Stage 3.2-E.

## Reconciliation safety budget

Reconciliation has its own versioned bounded policy:

- `reconciliation_max_attempts`;
- `reconciliation_initial_backoff_seconds`;
- `reconciliation_max_backoff_seconds`.

It does not consume the ordinary physical Tool attempt counter.

Transport/query failure does not change business truth.

When retryable:
- ReconciliationAttempt -> FAILED;
- business truth remains unresolved;
- Run -> QUEUED / RETRY;
- available_at is DB-derived;
- owner and lease are cleared;
- later claim creates the next reconciliation attempt number.

Exhaustion stops at MANUAL_REVIEW.

## Orphaned reconciliation recovery

If lease loss occurs while:

```text
ExternalAction RECONCILING
ReconciliationAttempt STARTED
```

takeover closes the stale read-only attempt:

```text
old ReconciliationAttempt -> FAILED
outcome_reason = LEASE_LOST
business truth remains unresolved
```

A later owner may perform another bounded reconciliation attempt.

Unlike a side-effect physical attempt, reconciliation is read-only, so lease loss does not
turn business truth into a new effect nor authorize a side-effect retry.

## Frozen D3 invariants

### D3-I1 — Commit before reconciliation query

STARTED ReconciliationAttempt must be durable before adapter I/O.

### D3-I2 — Reconciliation is not business execution

Reconciliation cannot create a new model proposal or reconstruct Action identity.

It consumes the existing immutable:
- ExternalAction;
- ActionSnapshot;
- operation_id;
- ToolVersion capability.

### D3-I3 — Safety budget is separate

Safety reconciliation remains bounded without consuming normal ToolExecutionAttempt budget.

### D3-I4 — Transport failure does not mutate business truth

A failed reconciliation query is evidence about the query, not evidence that the original
side effect succeeded, failed, or did not execute.

### D3-I5 — Non-idempotent BEST_EFFORT cannot authorize blind retry

Only AUTHORITATIVE NOT_EXECUTED, or an independently idempotent capability under the frozen
BEST_EFFORT contract, may authorize automatic retry.

### D3-I6 — NONE means no external reconciliation call

NONE stops at MANUAL_REVIEW and WAITING_ACTION_RESOLUTION.

### D3-I7 — Unresolved durable truth outranks new model reasoning

UNKNOWN / RECONCILING / MANUAL_REVIEW business truth blocks a fresh ModelInvocation.

### D3-I8 — D3 does not implement E

The Run waiting state is present because it belongs to the frozen Stage 3.2 state machine,
but ActionResolution and cancellation behavior remain absent and locked.

## Durable additions

Migration:
- `0013_reconciliation`

Durable table:
- `reconciliation_attempts`

Enums:
- `ReconciliationAttemptStatus`
- `ReconciliationBusinessResult`

Runtime adapter contract:
- `ReconciliationTool`
- `ReconciliationInvocation`
- `ReconciliationResult`

## State

```text
Stage 3.2-D1
✅ ACCEPTED / FROZEN

Stage 3.2-D2
✅ ACCEPTED / FROZEN

Stage 3.2-D3
✅ ACCEPTED / FROZEN

Stage 3.2-D aggregate acceptance
🔓 UNLOCKED

Stage 3.2-E
🔒
```

Governing rules:

> Intent Before Effect.

> Action Commit Before Effect.

> UNKNOWN Before Retry when external truth is uncertain.

> Reconcile before retry when business truth is unresolved.
