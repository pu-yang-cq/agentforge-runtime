# Stage 3.2-D — Side-effect Uncertainty, Safe Retry and Reconciliation — ACCEPTED / FROZEN

Status: **ACCEPTED / FROZEN**

Accepted slices:
- `docs/implementation/stage3.2-d1-unknown-boundary.md`
- `docs/implementation/stage3.2-d2-safe-retry-orphan.md`
- `docs/implementation/stage3.2-d3-reconciliation.md`

D3 implementation commit:
- `9e8fb391bace884775a34f53015c220d2fecc2af`

D3 target gate:
- **Stage 3.2-D3 Reconciliation**
- successful run: `37211132877`

D3 independent acceptance:
- **Stage 3.2-D3 Acceptance**
- successful run: `37211514523`

D aggregate acceptance:
- **Stage 3.2-D Aggregate Acceptance**
- first run `37211677419` rejected because the acceptance script scanned beyond
  `record_reconciliation_result()` and produced a false-positive identity-recreation check;
- implementation inspection proved no ActionSnapshot/ExternalAction/operation_id recreation;
- acceptance script scope was corrected without changing runtime semantics;
- successful rerun: `37211751509`.

## Aggregate accepted chain

```text
Model Tool Proposal
        ↓
durable ToolCall + ActionSnapshot + ExternalAction
        ↓
Action Commit
        ↓
ToolExecutionAttempt STARTED
        ↓
physical side-effect adapter call
        ↓
┌──────────────────────────────────────────────────────┐
│                                                      │
│ success                                              │ definite no-effect
↓                                                      ↓
SUCCEEDED                                       explicit safe retry policy
                                                       ↓
                                             same logical action identity
                                                       ↓
                                             new physical attempt only

possible / ambiguous execution
        ↓
ToolExecutionAttempt UNKNOWN
ExternalAction UNKNOWN
ToolCall UNRESOLVED
        ↓
NO blind retry
NO replacement model proposal
        ↓
ReconciliationAttempt STARTED committed
        ↓
read-only reconciliation query
        ↓
AUTHORITATIVE / BEST_EFFORT / NONE
        ↓
business truth or MANUAL_REVIEW
```

## Aggregate frozen invariants

### D-I1 — UNKNOWN is not failure

Possible execution is represented as UNKNOWN and may not be silently converted to
FAILED, READY, ABORTED, or an automatic retry.

### D-I2 — Retry requires authority

Automatic side-effect retry requires either:
- explicit adapter proof of definite non-execution; or
- reconciliation proof permitted by the frozen capability contract.

### D-I3 — Logical action identity is stable

Across retry and reconciliation the runtime preserves:
- the same ExternalAction;
- the same ActionSnapshot;
- the same operation_id;
- the same accepted ToolCall/model proposal.

Only physical attempt rows are new.

### D-I4 — Lease loss never proves non-execution

Orphaned side-effect STARTED attempts become UNKNOWN with
`LEASE_LOST_RESULT_NOT_DURABLE`.

No physical replacement attempt starts before reconciliation.

### D-I5 — Reconciliation is read-only safety work

A ReconciliationAttempt is distinct from ToolExecutionAttempt, uses a bounded
independent policy, and is durably STARTED before the query.

### D-I6 — Reconciliation transport failure does not decide business truth

Transport/query failure may schedule another bounded reconciliation attempt; it cannot
mark the original action SUCCEEDED, FAILED, or NOT_EXECUTED.

### D-I7 — Capability modes remain fail-safe

- AUTHORITATIVE may establish business truth.
- BEST_EFFORT cannot authorize non-idempotent blind retry.
- NONE makes no reconciliation external call and stops at MANUAL_REVIEW.

### D-I8 — Persisted unresolved truth outranks new reasoning

UNKNOWN, RECONCILING, and MANUAL_REVIEW durable facts block a fresh model decision from
reconstructing the unresolved action.

### D-I9 — D stops before E

D may place a non-cancelled Run in WAITING_ACTION_RESOLUTION because that is part of the
frozen Stage 3.2 state machine.

D does not implement:
- ActionResolution;
- cancel_requested;
- cancellation transitions/races;
- late side-effect result vs takeover/manual resolution authority;
- contradictory second manual resolution handling.

Those are Stage 3.2-E.

## Durable migrations accepted through D

```text
0011_side_effect_unknown
0012_side_effect_retry
0013_reconciliation
```

## State

```text
Stage 3.2-A
✅ ACCEPTED / FROZEN

Stage 3.2-B
✅ ACCEPTED / FROZEN

Stage 3.2-C
✅ ACCEPTED / FROZEN

Stage 3.2-D1
✅ ACCEPTED / FROZEN

Stage 3.2-D2
✅ ACCEPTED / FROZEN

Stage 3.2-D3
✅ ACCEPTED / FROZEN

Stage 3.2-D
✅ ACCEPTED / FROZEN

Stage 3.2-E
Cancellation + Manual Resolution + Late Races
🔓 UNLOCKED

Stage 3.2-F
🔒

Stage 3.2-G
🔒
```

Governing rules:

> Intent Before Effect.

> Action Commit Before Effect.

> UNKNOWN Before Retry when external truth is uncertain.

> Reconcile before retry when business truth is unresolved.

> Persisted facts outrank new reasoning.
