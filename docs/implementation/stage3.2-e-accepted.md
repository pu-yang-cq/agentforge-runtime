# Stage 3.2-E — Cancellation + Manual Resolution + Late-result Races — ACCEPTED / FROZEN

Status: **ACCEPTED / FROZEN**

Frozen child slices:
- `docs/implementation/stage3.2-e1-cancellation.md`
- `docs/implementation/stage3.2-e2-action-resolution.md`
- `docs/implementation/stage3.2-e3-late-result-authority.md`

Aggregate acceptance:
- workflow: **Stage 3.2-E Aggregate Acceptance**
- successful run: `37256683913`

E3 implementation:
- commit: `f1e5cd9d80497bd39953a7d21704a563e6bf8d85`
- target gate: `37256391604`
- independent acceptance: `37256507004`

## Aggregate capability accepted

Stage 3.2-E freezes the complete control-plane semantics for cancellation,
manual action resolution and late autonomous results.

The runtime now distinguishes three different authorities:

1. **external business truth** — what actually happened in the provider;
2. **operator resolution truth** — the final manual decision for an unresolved
   action;
3. **business progression authority** — whether the Run may continue.

These authorities are related but are not interchangeable.

## Aggregate state-machine guarantees

### Cancellation

Cancellation:
- is idempotent;
- is durably represented by `cancel_requested`;
- terminalizes immediately when no unresolved/in-flight business truth requires
  stabilization;
- never rolls back already durable external truth;
- prevents later autonomous work from reopening business progression.

### Manual resolution

An ExternalAction in MANUAL_REVIEW may receive exactly one final
ActionResolution.

The resolution:
- is idempotent for exact replay;
- rejects contradiction;
- projects final action/call truth;
- may requeue a non-cancelled successful Run with
  `QueueReason.ACTION_RESOLVED`;
- never reopens a CANCELLED Run;
- remains final against stale autonomous results.

### Late results

Late physical/reconciliation evidence may still settle external truth.

It may not:
- restore an old generation;
- recreate progression authority;
- reopen cancellation;
- overwrite a committed ActionResolution;
- silently schedule a replacement effect.

## Aggregate lock-order contract

Business-state races serialize through:

```text
Run
  -> ExternalAction
  -> ToolCall
  -> ToolExecutionAttempt / ReconciliationAttempt
```

The Run row is the authoritative progression serialization point.

## Aggregate claimability contract

Only:
- QUEUED Runs whose `available_at` is due; and
- expired RUNNING Runs

are claim candidates.

WAITING_ACTION_RESOLUTION, CANCELLED, FAILED and COMPLETED Runs are never
normal worker claim candidates.

## Aggregate acceptance evidence

The E aggregate workflow independently verified:
- all E1/E2/E3 frozen records;
- cancellation and ActionResolution state surface;
- claim-state isolation;
- Run-first cancellation/resolution serialization;
- cancelled manual-resolution finality;
- E3 late-result fencing;
- explicit PostgreSQL race regression cases;
- full containerized regression gate.

## Frozen Stage 3.2-E invariants

> Cancellation ends progression authority, not necessarily external evidence.

> Manual ActionResolution is single-valued final business truth.

> Late evidence may refine external truth but cannot resurrect progression.

> Every race that can change business progression serializes through the Run row.

## State

```text
Stage 3.2-D
✅ ACCEPTED / FROZEN

Stage 3.2-E
✅ ACCEPTED / FROZEN

Stage 3.2-F
Checkpoint + Recovery Matrix
🔓 UNLOCKED

Stage 3.2-G
Immutable RC + Final Acceptance
🔒
```
