# Stage 3.2-D2 — Safe Side-effect Retry + Orphan Recovery — ACCEPTED / FROZEN

Status: **ACCEPTED / FROZEN**

Parent frozen surfaces:
- Stage 3.2-A
- Stage 3.2-B
- Stage 3.2-C
- Stage 3.2-D1 UNKNOWN boundary

Implementation commit:
- `237f5b39bef108954f2aff3d0733f117dd5a216a`

Target implementation gate:
- workflow: **Stage 3.2-D2 Safe Retry and Orphan Recovery**
- successful run: `37208021132`

Independent acceptance:
- workflow: **Stage 3.2-D2 Acceptance**
- successful run: `37208147987`

## Accepted D2 semantics

### Explicit safe side-effect retry

A side-effect may automatically retry only from an explicit adapter signal that
proves the external effect did not execute:

```text
SideEffectTransientError
  definite_not_executed = true
        ↓
Attempt STARTED -> FAILED
ExternalAction EXECUTING -> READY
ToolCall EXECUTING -> READY
current_attempt_id -> NULL
same ExternalAction
same ActionSnapshot
same operation_id
        ↓
Run -> QUEUED / RETRY
available_at = DB-time due timestamp
owner_worker_id = NULL
lease_expires_at = NULL
        ↓
new claim / generation
        ↓
new physical ToolExecutionAttempt
attempt_number + 1
```

The default side-effect retry policy remains one attempt, so automatic retry is
opt-in through durable ToolVersion configuration.

### Retry exhaustion / permanent denial

If the explicit safe-retry policy is exhausted:
- Attempt remains a proven definite-not-executed FAILED attempt;
- Action becomes FAILED;
- ToolCall becomes FAILED;
- Run becomes FAILED.

If ordinary Tool-attempt budget or deadline prohibits the future retry:
- Action becomes ABORTED;
- ToolCall becomes NOT_EXECUTED;
- no replacement attempt is created;
- Run becomes FAILED.

### Orphaned side-effect takeover

When a new owner claims an expired RUNNING Run whose prior owner left:

```text
ExternalAction EXECUTING
ToolCall EXECUTING
ToolExecutionAttempt STARTED
```

the takeover transaction first closes the stale authorization:

```text
old Attempt -> UNKNOWN
outcome_reason = LEASE_LOST_RESULT_NOT_DURABLE
definite_not_executed = false

ExternalAction -> UNKNOWN
current_attempt_id -> NULL

ToolCall -> UNRESOLVED
```

No replacement physical side-effect attempt is created by orphan recovery.
Reconciliation must precede any retry.

## Frozen D2 invariants

### D2-I1 — Retry requires positive proof of non-execution

Generic exceptions, timeouts, response loss, lease loss and ambiguous adapter
failures are not retry authority.

Only the explicit proven-no-effect path may enter safe retry.

### D2-I2 — Safe retry preserves logical action identity

A retry does not create:
- a new ExternalAction;
- a new ActionSnapshot;
- a new operation_id;
- a new model proposal.

It creates only a new physical ToolExecutionAttempt after a later Action Commit.

### D2-I3 — Delayed retry is durable scheduling

Safe retry uses:
- Run.status = QUEUED;
- queue_reason = RETRY;
- DB-derived available_at;
- owner_worker_id cleared;
- lease_expires_at cleared.

Worker lease expiry is not the retry scheduler.

### D2-I4 — Attempt history is monotonic

Each physical retry gets a new ToolExecutionAttempt and monotonically increasing
attempt_number.

A completed FAILED or UNKNOWN attempt is never reused.

### D2-I5 — Lease loss implies uncertainty

Lease loss after Action Commit can never prove the external effect did not occur.

Therefore orphaned side-effect STARTED attempts are UNKNOWN, not FAILED/READY.

### D2-I6 — Takeover stabilizes before new progression

The Run row remains the serialization point.

During takeover the recovery order is:

```text
Run lock
  -> ExternalAction
  -> ToolCall
  -> old ToolExecutionAttempt
```

The orphan is closed before READ recovery, model reasoning, or any replacement
side-effect attempt.

### D2-I7 — D1 ambiguity rules remain frozen

D2 does not broaden retryability.

All D1 possible-execution/unclassified paths remain UNKNOWN + UNRESOLVED.

## Durable additions

Migration:
- `0012_side_effect_retry`

ToolVersion policy:
- `side_effect_retry_max_attempts`
- `side_effect_retry_initial_backoff_seconds`
- `side_effect_retry_max_backoff_seconds`

Default:
- max attempts = 1

Therefore existing side-effect tools do not silently acquire retries.

## Next slice

Stage 3.2-D3 is now unlocked for:
- ReconciliationAttempt durable lifecycle;
- STARTED-before-query boundary;
- AUTHORITATIVE / BEST_EFFORT / NONE semantics;
- bounded reconciliation safety budget;
- orphaned reconciliation recovery;
- reconciliation transport retry;
- authoritative NOT_EXECUTED safe retry decision;
- BEST_EFFORT non-idempotent safety;
- action-side MANUAL_REVIEW truth.

Full cancellation and ActionResolution behavior remains Stage 3.2-E.

## State

```text
Stage 3.2-D1
✅ ACCEPTED / FROZEN

Stage 3.2-D2
✅ ACCEPTED / FROZEN

Stage 3.2-D3
ReconciliationAttempt + Reconciliation Modes
🔓 UNLOCKED

Stage 3.2-D aggregate acceptance
🔒

Stage 3.2-E
🔒
```

Governing rules:

> UNKNOWN Before Retry when external truth is uncertain.

> Retry only after proof of non-execution.
