# Stage 3.2-C Aggregate Acceptance — ACCEPTED / FROZEN

Status: **ACCEPTED / FROZEN**

Parent accepted surfaces:
- Stage 3.2-A — unified physical ToolExecutionAttempt, budget/deadline/yield, READ retry
- Stage 3.2-B — ActionSnapshot V1 + ExternalAction durable intent and fenced preparation

Accepted Stage 3.2-C implementation surface:
- C1 — fenced Action Commit Boundary + explicit side-effect adapter edge

Implementation commit:
- C1: `faea579a6c47b05556d8e35764e4ca67f13c0453`

Target implementation gate:
- workflow: **Stage 3.2-C1 Action Commit Boundary**
- successful run: `37205740852`

Independent aggregate acceptance:
- workflow: **Stage 3.2-C Aggregate Acceptance**
- successful run: `37206636147`
- trigger commit: `777f5eff7c7b0fbd73d998af2698bf7bb9f7830c`

Aggregate acceptance proved:
- accepted Stage 3.2-B surfaces remain present;
- Action Commit API and side-effect adapter surfaces are present;
- AST ordering proof: durable Action Commit precedes external adapter invocation, which precedes durable success recording;
- READY action recovery regression coverage is present;
- stable operation identity regression coverage is present;
- deadline/budget pre-commit denial coverage is present;
- full inherited Python 3.14 / PostgreSQL 18 target validation passed.

## Frozen C invariants

### C-I1 — Action Commit before effect

No physical side-effect adapter invocation is authorized directly from an
ExternalAction READY state.

The required ordering is:

```text
ExternalAction READY
+ ToolCall READY
+ immutable ActionSnapshot
        ↓
Action Commit transaction
        ↓
ToolExecutionAttempt STARTED
ToolCall EXECUTING
ExternalAction EXECUTING
current_attempt_id = attempt.id
tool_attempts_used reserved
        ↓
COMMIT
        ↓
physical external adapter invocation
```

If the Action Commit transaction does not commit, the external call count must
remain zero.

### C-I2 — Every physical side-effect call has a durable Attempt

Each physical side-effect adapter invocation is represented by a distinct
`ToolExecutionAttempt`.

Before invocation:
- Attempt status is STARTED;
- Attempt references the ExternalAction;
- ordinary Tool-attempt budget is already reserved;
- ToolCall is EXECUTING;
- ExternalAction is EXECUTING.

Later retries may create additional attempts, but may never reuse a completed
physical attempt.

### C-I3 — current_attempt_id means active authorization only

`ExternalAction.current_attempt_id` identifies the currently authorized
STARTED side-effect attempt.

For the implemented C success path:

```text
READY
  current_attempt_id = NULL
      ↓ Action Commit
EXECUTING
  current_attempt_id = STARTED attempt
      ↓ durable success
SUCCEEDED
  current_attempt_id = NULL
```

Later Stage 3.2-D/E transitions must preserve the frozen meaning and clear this
pointer whenever the action leaves EXECUTING.

### C-I4 — Stable operation identity crosses the adapter edge

The external adapter receives identity from the frozen durable intent:
- stable `operation_id`;
- immutable ActionSnapshot arguments;
- opaque `credential_ref`;
- provider idempotency key derived from `operation_id` when the ToolVersion
  declares idempotency support.

The runtime must not reconstruct side-effect identity from a fresh model
proposal after restart/takeover.

### C-I5 — READY recovery precedes new model reasoning

A durable READY ExternalAction is recovered and handled as the same logical
intent before asking the model to generate a replacement side-effect proposal.

The same:
- ToolCall;
- ActionSnapshot;
- ExternalAction;
- operation_id

remain authoritative.

### C-I6 — Permanent denial before Action Commit is zero-I/O

If a READY action becomes permanently non-executable because ordinary
Tool-attempt budget is exhausted or the DB deadline expires before Action
Commit:

```text
ExternalAction READY -> ABORTED
ToolCall READY        -> NOT_EXECUTED
ToolExecutionAttempt  -> none newly created
external adapter call -> zero
```

No terminal Run may be produced by this path while leaving the action READY.

### C-I7 — Later slices may strengthen, not weaken

Stage 3.2-D through G may add:
- FAILED / UNKNOWN physical result classification;
- safe retry;
- orphan recovery;
- reconciliation;
- cancellation fences;
- manual resolution;
- late-result handling;
- checkpoint reconstruction.

They may not:
- invoke a side-effect adapter before durable Action Commit;
- bypass the durable STARTED attempt;
- bypass ordinary Tool-attempt budget reservation;
- mutate/reconstruct ActionSnapshot identity for retry/recovery;
- allow READY recovery to be replaced by fresh model reasoning.

## Explicit deferred obligations

This C slice does **not** claim completion of the full Stage 3.2 result and
recovery state machine.

The following remain intentionally assigned to later frozen slices:

### Stage 3.2-D
- possible-execution outcome -> UNKNOWN;
- definite-not-executed classification;
- safe side-effect retry;
- orphaned EXECUTING attempt takeover;
- ReconciliationAttempt;
- AUTHORITATIVE / BEST_EFFORT / NONE reconciliation;
- bounded reconciliation safety budget.

### Stage 3.2-E
- `cancel_requested` fence in preparation and Action Commit;
- cancel-vs-commit serialization;
- in-flight model-result consequence fence;
- ActionResolution / MANUAL_REVIEW;
- late-result and resolution races.

### Stage 3.2-F
- checkpoint overlay;
- full restart/takeover recovery matrix.

Therefore this is a **slice acceptance**, not final Stage 3.2 runtime
acceptance.

## Freeze result

```text
Stage 3.1
✅ ACCEPTED / FROZEN

Stage 3.2 Design V1.0
✅ ACCEPTED / FROZEN

Stage 3.2-A
✅ ACCEPTED / FROZEN

Stage 3.2-B
✅ ACCEPTED / FROZEN

Stage 3.2-C
✅ ACCEPTED / FROZEN

Stage 3.2-D
UNKNOWN + Reconciliation
🔓 UNLOCKED

Stage 3.2-E
Cancellation / Manual Resolution / Late Races
🔒

Stage 3.2-F
Checkpoint + Recovery Matrix
🔒

Stage 3.2-G
Immutable RC / Final Acceptance
🔒
```

Governing rules:

> Intent Before Effect.

> Action Commit Before Effect.

