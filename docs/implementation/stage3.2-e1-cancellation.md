# Stage 3.2-E1 — Durable Cancellation Intent — ACCEPTED / FROZEN

Status: **ACCEPTED / FROZEN**

Parent frozen surfaces:
- Stage 3.2-A/B/C
- Stage 3.2-D aggregate
- `docs/implementation/stage3.2-e-slices-frozen.md`

Primary implementation commit:
- `db27b22030b8e68505cf6a580c800e6ecc2b1fc8`

Accepted review/result-fence fixes:
- `285b41177ce293277d364770e4730a85816b611c`
  - cancellation wins over denied model-consequence persistence;
- `c5aa53c95cb9d926a735d3a731c320c4da85a43a`
  - in-flight model/tool/side-effect/reconciliation results are fenced by durable
    cancellation authority.

Target implementation gate:
- workflow: **Stage 3.2-E1 Cancellation**
- successful run: `37212659816`

Result-fence regression gate:
- workflow: **Stage 3.2-E1 Result Fence Fix**
- successful run: `37213603415`

Independent acceptance:
- workflow: **Stage 3.2-E1 Acceptance**
- earlier runs correctly rejected incomplete E1 behavior;
- run `37214284520` exposed an acceptance-script scope bug: it matched
  `ExecutionJournal` method definitions instead of the corresponding
  `RunManager.execute()` consequence calls;
- acceptance proof was scoped to `RunManager.execute()` without changing
  runtime semantics;
- successful independent run: `37214422018`.

## Accepted E1 semantics

### Durable orthogonal cancellation intent

Cancellation is represented independently from the current Run execution status:

```text
Run.cancel_requested = true
```

The flag is durable and survives ownership/generation changes.

Cancellation is a progression-authority fact, not an assertion that already
authorized external work was rolled back.

### Run-row serialization

`cancel_run()` locks the Run first.

The Run row remains the per-Run serialization point between:
- cancellation;
- model-result persistence;
- READ result/retry persistence;
- side-effect result persistence;
- reconciliation result/retry persistence.

### Pre-commit work can be locally stabilized

If cancellation wins while a side-effect intent is still:

```text
ExternalAction READY
ToolCall READY
no STARTED physical attempt
```

the runtime may safely persist:

```text
ExternalAction -> ABORTED
ToolCall -> NOT_EXECUTED
```

because Action Commit has not occurred.

This is cancellation-before-effect, not rollback.

Recovered/prepared ordinary READY business ToolCalls are likewise stabilized as
NOT_EXECUTED.

### EXECUTING side effects are never directly rolled back

If the durable action is already EXECUTING, cancellation does not claim that the
external effect disappeared.

The cancellation request remains durable while external truth is stabilized by
the already-frozen D safety machinery.

### UNKNOWN / RECONCILING remain safety work

Cancellation blocks fresh business progression, but it does not block the
read-only safety work necessary to establish external truth.

Therefore an unresolved action may still:
- reconcile;
- exhaust reconciliation safety budget;
- arrive at MANUAL_REVIEW.

### CANCELLED + MANUAL_REVIEW is legal

If cancellation owns business progression authority but external truth remains
unresolved, the accepted stopping state is:

```text
Run CANCELLED
cancel_requested = true

ExternalAction MANUAL_REVIEW
ToolCall UNRESOLVED
```

Run cancellation does not erase the unresolved external fact.

### Model-result consequence fencing

If cancellation wins the Run-row race after a model request was already
in-flight, the returned model result cannot create a new business consequence.

The following consequence paths all discard current-authority model output when
the recorder reports `CANCEL_REQUESTED`:
- final answer;
- side-effect Tool proposal;
- READ Tool proposal;
- permission-denied Tool proposal.

The durable result is cancellation, not FAILED/COMPLETED/new Tool intent.

### In-flight failure/result fencing

Cancellation also dominates business continuation after already in-flight:
- model failure;
- READ transient/permanent failure;
- side-effect definite-no-effect failure;
- side-effect transient safe-retry candidate;
- reconciliation NOT_EXECUTED/retry candidate.

A result may still be recorded as evidence where appropriate, but it cannot:
- schedule new business retry;
- queue a new model continuation;
- convert the Run to FAILED when cancellation already won;
- reopen a cancelled Run.

## Frozen E1 invariants

### E1-I1 — Cancellation is not rollback

`cancel_requested` never means an EXECUTING external action was undone.

### E1-I2 — Persisted cancel intent outranks new business progression

After cancellation wins serialization:
- no new ModelInvocation;
- no new READ physical attempt;
- no new side-effect Action Commit;
- no business retry scheduling.

### E1-I3 — Safety reconciliation may continue

Reconciliation is read-only safety work, not fresh business progression.

### E1-I4 — Pre-commit stabilization is allowed

READY work that has not crossed its physical-effect boundary may be marked
NOT_EXECUTED/ABORTED.

### E1-I5 — In-flight returned data cannot regain authority

A late response from an already-running model/tool/reconciliation operation
cannot defeat durable cancellation.

### E1-I6 — CANCELLED may retain unresolved external truth

Terminal Run state does not imply every ExternalAction is resolved.

### E1-I7 — E1 does not implement manual resolution

E1 introduces no ActionResolution entity/API and makes no claim about:
- contradictory second manual resolution;
- manual SUCCEEDED/FAILED/ABORTED continuation;
- late physical result vs committed manual resolution.

Those remain E2/E3.

## Durable addition

Migration:
- `0014_cancellation_intent`

Primary durable field:
- `runs.cancel_requested`

## State

```text
Stage 3.2-D
✅ ACCEPTED / FROZEN

Stage 3.2-E1
Durable Cancellation Intent
✅ ACCEPTED / FROZEN

Stage 3.2-E2
ActionResolution + Manual-review Continuation
🔓 UNLOCKED

Stage 3.2-E3
Late-result Authority + Cancellation/Resolution Races
🔒

Stage 3.2-E aggregate acceptance
🔒

Stage 3.2-F
🔒

Stage 3.2-G
🔒
```

Governing rules:

> Cancellation is not rollback.

> Persisted facts outrank new reasoning.

> Late evidence cannot regain progression authority.

> The Run row remains the per-Run serialization point.
