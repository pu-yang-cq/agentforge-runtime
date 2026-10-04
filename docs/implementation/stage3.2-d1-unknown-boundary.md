# Stage 3.2-D1 — UNKNOWN Result Boundary — ACCEPTED / FROZEN

Status: **ACCEPTED / FROZEN**

Parent frozen surfaces:
- Stage 3.2-A
- Stage 3.2-B
- Stage 3.2-C
- `docs/implementation/stage3.2-d-slices-frozen.md`

Implementation commit:
- `d29397071913dcff4aa7d3c1ae822bb33321f405`

Target implementation gate:
- workflow: **Stage 3.2-D1 UNKNOWN Boundary**
- successful run: `37207443075`

Independent acceptance:
- workflow: **Stage 3.2-D1 Acceptance**
- successful run: `37207570248`

## Accepted D1 semantics

After Action Commit, a physical side-effect result is classified conservatively.

### Successful result

```text
Attempt STARTED -> SUCCEEDED
Action EXECUTING -> SUCCEEDED
ToolCall EXECUTING -> SUCCEEDED
current_attempt_id -> NULL
```

### Proven definite non-execution

An explicit `ToolAdapterError(definite_not_executed=True)` means the runtime
has proof that the external business effect did not execute.

D1 persists:

```text
Attempt STARTED -> FAILED
definite_not_executed = true
Action EXECUTING -> FAILED
ToolCall EXECUTING -> FAILED
current_attempt_id -> NULL
Run -> FAILED
```

Automatic safe retry is intentionally deferred to D2. D1 freezes only the
classification fact: proven non-execution is distinct from uncertainty.

### Possible / ambiguous execution

An explicit adapter failure with `definite_not_executed=False`, or an
unclassified exception after Action Commit, is never treated as a normal
failure or implicit retry.

D1 persists:

```text
Attempt STARTED -> UNKNOWN
definite_not_executed = false
Action EXECUTING -> UNKNOWN
ToolCall EXECUTING -> UNRESOLVED
current_attempt_id -> NULL
Run remains nonterminal
```

The stable `operation_id` and immutable ActionSnapshot remain authoritative.

## Frozen D1 invariants

### D1-I1 — Uncertainty is first-class truth

Possible execution must be represented as UNKNOWN.

It may not be silently converted to:
- FAILED;
- READY;
- ABORTED;
- a fresh model proposal;
- an automatic physical retry.

### D1-I2 — Generic post-commit exceptions fail safe

Once Action Commit has durably authorized a physical side-effect attempt,
an unclassified adapter exception is conservatively treated as possible
execution.

Unknown exceptions are not assumed to be definite non-execution.

### D1-I3 — UNKNOWN clears active authorization

When an action leaves EXECUTING for UNKNOWN:
- `current_attempt_id = NULL`;
- historical ToolExecutionAttempt remains queryable;
- the attempt is UNKNOWN, not reused.

### D1-I4 — UNKNOWN projects ToolCall to UNRESOLVED

D1 adds the durable ToolCall projection:

```text
ExternalAction UNKNOWN
        ⇕
ToolCall UNRESOLVED
```

Migration:
- `0011_side_effect_unknown`

### D1-I5 — Durable UNKNOWN outranks new reasoning

Before any new ModelInvocation, RunManager checks for durable UNKNOWN action
truth.

If one exists, the current business progression stops.

The model may not reconstruct or replace the unresolved action.

### D1-I6 — No blind retry edge

The side-effect ambiguity path contains no READ retry machinery and no generic
retry transition.

Retry authority must be introduced only by D2/D3 under the frozen safety rules.

## Deferred to D2

D2 is now unlocked for:
- orphaned STARTED side-effect attempt takeover;
- `LEASE_LOST_RESULT_NOT_DURABLE` -> UNKNOWN stabilization;
- explicit retryable definite-not-executed signal/policy;
- stable-operation-id side-effect safe retry;
- durable RETRY scheduling;
- monotonic attempt numbering across retry/restart;
- budget/deadline stabilization around safe retry.

## State

```text
Stage 3.2-D1
✅ ACCEPTED / FROZEN

Stage 3.2-D2
Orphan Takeover + Safe Side-effect Retry
🔓 UNLOCKED

Stage 3.2-D3
ReconciliationAttempt + Reconciliation Modes
🔒

Stage 3.2-D aggregate acceptance
🔒

Stage 3.2-E
🔒
```

Governing rule:

> UNKNOWN Before Retry when external truth is uncertain.
