# Stage 3.2-F — Recovery / Crash Matrix Aggregate — ACCEPTED / FROZEN

Status: **ACCEPTED / FROZEN**

Frozen parent:
- Stage 3.2-E aggregate
- `docs/implementation/stage3.2-f-slices-frozen.md`

## Accepted slices

### F1 — Checkpoint V1 Overlay Authority

Status: **ACCEPTED / FROZEN**

Implementation commit:
- `2cd8de79fd3f2e81278ea18a9d1fe46bc48d057a`

Target gate:
- `37257254728`

Independent acceptance:
- `37257397286`

Checkpoint remains an optional optimization overlay and never overrides newer
business-authoritative durable facts.

### F2 — Stateful Fake External Ledger + Crash Barriers

Status: **ACCEPTED / FROZEN**

Implementation commit:
- `87691c7bf2d369059c18516c4cc8a2ff1fcc6c2e`

Target gate:
- `37259060659`

Independent acceptance:
- `37259235589`

Freeze record:
- `docs/implementation/stage3.2-f2-fake-external-ledger.md`

The test-only fake external system records:
- operation_id;
- physical call_count;
- business effect_count;
- duplicate_request_count;
- reconciliation_query_count;
- external_resource_id.

It exposes all 12 frozen deterministic crash barriers without entering
production runtime dependencies.

### F3 — Full Recovery / Crash Matrix

Status: **ACCEPTED / FROZEN**

Implementation commit:
- `9b92830d907379dc132fd433b42e74591adfc392`

Target gate:
- workflow: **Stage 3.2-F3 Recovery Crash Matrix**
- successful run: `37259885423`

Independent F aggregate acceptance:
- workflow: **Stage 3.2-F Aggregate Acceptance**
- successful run: `37260097961`

Executable matrix:
- `docs/acceptance/stage3.2-f3-recovery-matrix.json`

## Rejected F3 candidates

The following runs were not accepted and did not unlock later work:

- `37259687487`
  - F3 matrix contract incorrectly searched only thin wrapper test bodies for
    shared effect-count assertions.
- `37259787966`
  - 12-window PostgreSQL matrix passed, but full quality gate rejected one
    overlong test function declaration.

Both defects were corrected before the accepted target run.

## Frozen 12-window recovery matrix

The aggregate gate binds each frozen crash/race window to executable PostgreSQL
evidence:

1. before Action preparation commit;
2. after READY commit;
3. before Action Commit;
4. after Action Commit before external call;
5. during external call;
6. after external effect commit before response;
7. after response before DB result commit;
8. during result commit;
9. during reconciliation request;
10. after reconciliation response before result commit;
11. during durable retry/yield transaction;
12. during cancellation/model-result race.

Windows 4–7 use the F2 stateful external ledger and deterministic barriers to
measure actual external business effects rather than only Python exceptions.

## Aggregate acceptance evidence

Independent acceptance re-ran all of the following from committed main:

- exact 12-window matrix contract;
- production/test-infrastructure dependency isolation;
- recovery precedence proof;
- F1 checkpoint authority regression;
- F2 observable external-ledger regression;
- the full 12-window PostgreSQL recovery matrix;
- the complete Python 3.14 + PostgreSQL 18 project regression.

All passed in run `37260097961`.

## Frozen Stage 3.2-F invariants

### F-I1 — Durable business facts outrank checkpoints

Checkpoint payload is never business authority.

Newer ToolCall, ExternalAction, physical attempt, reconciliation, cancellation
or resolution facts invalidate a stale checkpoint overlay.

### F-I2 — Recovery outranks fresh model reasoning

The accepted RunManager recovery precedence is:

```text
reconciliation / unresolved external truth
        ↓
durable READY side-effect recovery
        ↓
durable READ recovery
        ↓
fresh model invocation
```

The model cannot reconstruct or replace already-durable action truth.

### F-I3 — UNKNOWN precedes retry

A crash or transport ambiguity after Action Commit never creates automatic retry
authority.

UNKNOWN must first be reconciled or manually resolved.

### F-I4 — Request duplication is not hidden

The fake ledger distinguishes:
- physical request count;
- actual business effect count.

A recovery path is unsafe if it merely hides duplicate effects behind retry
bookkeeping.

### F-I5 — No blind duplicate non-idempotent effect

The accepted barrier tests prove:
- pre-effect crash: authoritative NOT_EXECUTED may authorize one safe retry;
- post-effect crash: reconciliation observes SUCCEEDED and the action is not
  physically replayed.

For the accepted non-idempotent crash cases, final `effect_count == 1`.

### F-I6 — Action Commit remains the physical-effect boundary

No physical business effect may occur before durable:
- ExternalAction EXECUTING;
- ToolCall EXECUTING;
- ToolExecutionAttempt STARTED;
- current_attempt_id authorization.

### F-I7 — Reconciliation preserves business truth

A reconciliation transport/process failure does not change external business
truth.

Returned reconciliation truth may update durable action projection while
cancellation still fences continuation.

### F-I8 — Cancellation fences progression, not truth recording

Cancellation prevents new business progression but does not erase a late
externally observed success/failure.

### F-I9 — Durable retry is scheduling, not a worker sleep

Retry/yield remains represented by durable Run queue state and DB-time
`available_at`.

### F-I10 — Test infrastructure is non-authoritative

`agentforge.testing` is acceptance infrastructure only and is not imported by
production runtime modules.

### F-I11 — Secrets remain outside durable/test evidence

Credential references and resolved secret material are not stored in fake
external ledger evidence.

### F-I12 — Full regression is part of acceptance

Focused crash tests cannot substitute for the complete project gate.

F3 was accepted only after both focused recovery tests and the full regression
passed, followed by a second independent aggregate acceptance.

## Stage state

```text
Stage 3.2-A
✅ ACCEPTED / FROZEN

Stage 3.2-B
✅ ACCEPTED / FROZEN

Stage 3.2-C
✅ ACCEPTED / FROZEN

Stage 3.2-D
✅ ACCEPTED / FROZEN

Stage 3.2-E
✅ ACCEPTED / FROZEN

Stage 3.2-F1
✅ ACCEPTED / FROZEN

Stage 3.2-F2
✅ ACCEPTED / FROZEN

Stage 3.2-F3
✅ ACCEPTED / FROZEN

Stage 3.2-F aggregate
✅ ACCEPTED / FROZEN

Stage 3.2-G
Immutable RC + Final Acceptance
🔓 UNLOCKED
```

Governing rule:

> Recovery correctness is proven against observable external business effects,
> not inferred from process-local success or failure.
