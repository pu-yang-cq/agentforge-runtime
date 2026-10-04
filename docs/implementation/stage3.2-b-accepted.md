# Stage 3.2-B Aggregate Acceptance — ACCEPTED / FROZEN

Status: **ACCEPTED / FROZEN**

Accepted implementation surface:
- Stage 3.2-B1 — Canonical ActionSnapshot V1 + ExternalAction persistence
- Stage 3.2-B2 — fenced side-effect preparation transaction

Implementation commits:
- B1: `4e47639ce5c97e4fe5ea81ae694342d5d8bf5388`
- B2: `eb5f6f0e5b833221946ae3b95fa7800f935d8c03`

Independent aggregate acceptance:
- workflow: **Stage 3.2-B Aggregate Acceptance**
- successful run: `37204534145`
- first aggregate diagnostic run: `37204486028` (acceptance-script text-slice bug only; runtime implementation unchanged)

Aggregate gate:
- B1/B2 durable surfaces: PASS
- Intent Before Effect AST structural proof: PASS
- Ruff: PASS
- Ruff format: PASS, 56 files
- mypy strict: PASS, 28 source files
- PostgreSQL: PASS, major 18
- Alembic online upgrade: PASS through `0010_side_effect_preparation`
- full tests: PASS, 105 passed

## Frozen B invariants

The following are now frozen and may not be weakened by later Stage 3.2 slices.

### B-I1 — Intent before effect

A side-effect adapter may not be called from preparation.

Preparation commits durable intent and then stops:

```text
ToolProposal
  ↓
ToolCall READY
+ ActionSnapshot V1
+ ExternalAction READY
+ stable operation_id
  ↓
COMMIT
  ↓
STOP
```

### B-I2 — No physical attempt in preparation

Stage 3.2-B preparation:
- does not create `ToolExecutionAttempt`;
- does not increment `tool_attempts_used`;
- does not transition `ExternalAction` to EXECUTING;
- leaves `current_attempt_id = NULL`;
- performs zero external adapter I/O.

Those transitions are exclusively owned by Stage 3.2-C Action Commit Boundary.

### B-I3 — Fenced preparation

The durable preparation transaction locks the Run and re-checks all currently implemented business-progression predicates:
- current Run is RUNNING/nonterminal;
- current execution generation;
- live DB lease;
- DB deadline;
- remaining ordinary Tool-attempt budget sufficient for at least one future attempt;
- no conflicting active ToolCall;
- no STARTED ToolExecutionAttempt;
- durable ToolVersion remains bound and Stage-3.2-executable.

If a checked predicate fails, no READY ExternalAction is committed.

### B-I4 — Durable ToolVersion eligibility

Stage 3.2 side-effect capability facts are durable ToolVersion configuration:
- effect type;
- approval requirement;
- explicit no-approval execution eligibility;
- credential reference;
- idempotency capability declaration;
- reconciliation mode declaration.

READ and DESTRUCTIVE paths cannot be marked as B2 side-effect executable.
Approval-required Tools fail closed.

### B-I5 — Immutable action identity

ExternalAction and ActionSnapshot share one stable `operation_id`.

ActionSnapshot V1 remains the immutable canonical input to all later:
- Action Commit execution;
- idempotency handling;
- reconciliation;
- manual resolution evidence.

### B-I6 — READ recovery isolation

A READY ExternalAction-backed ToolCall must never be interpreted as a recoverable READ.

This is independently guarded by:
1. the PostgreSQL recovery query filtering `ToolVersion.effect_type = READ` and excluding ExternalAction-linked ToolCalls;
2. `ToolCoordinator.prepare_recovered_read()` rejecting non-READ bindings.

### B-I7 — Later slices may strengthen, not weaken

Stage 3.2-C through G may add additional predicates and state transitions around the frozen B transaction, but may not:
- move external I/O before durable intent commit;
- create a physical attempt inside B preparation;
- weaken Run/generation/lease/deadline/budget/ToolVersion fencing;
- make ActionSnapshot mutable;
- allow side-effect READY calls into READ recovery.

## Explicit deferred final-acceptance obligation

The frozen Stage 3.2 design and Acceptance Gate H also require:

```text
cancel_requested = false
```

inside side-effect preparation.

The `cancel_requested` durable field, cancellation command, model-result consequence fence, and cancel-vs-action races are intentionally assigned by the frozen implementation plan to **Stage 3.2-E**.

Therefore:

- this B aggregate acceptance is a **slice acceptance**, not a claim that final Stage 3.2 Gate H is already complete;
- Stage 3.2-E MUST add the cancellation predicate to B2 preparation before Stage 3.2-G final acceptance;
- that E change is defined as an additive strengthening of the frozen B progression fence, not a weakening or redesign of B.

Final Stage 3.2 acceptance remains locked until every frozen acceptance criterion, including cancellation, is satisfied.

## Freeze result

```text
Stage 3.2-A
✅ ACCEPTED / FROZEN

Stage 3.2-B1
✅ IMPLEMENTED

Stage 3.2-B2
✅ IMPLEMENTED

Stage 3.2-B aggregate acceptance
✅ ACCEPTED / FROZEN

Stage 3.2-C
Action Commit Boundary + side-effect fake
🔓 UNLOCKED

Stage 3.2-D
UNKNOWN + Reconciliation
🔒

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

Governing rule:

> Intent Before Effect.
