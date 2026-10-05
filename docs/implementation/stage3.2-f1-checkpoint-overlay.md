# Stage 3.2-F1 — Checkpoint V1 Overlay Authority — ACCEPTED / FROZEN

Status: **ACCEPTED / FROZEN**

Parent frozen surfaces:
- Stage 3.2-E aggregate
- `docs/implementation/stage3.2-f-slices-frozen.md`
- Stage 3.2 Design V1.0
- Stage 3.2 Acceptance Criteria V1.0

Implementation commit:
- `2cd8de79fd3f2e81278ea18a9d1fe46bc48d057a`

Target implementation gate:
- workflow: **Stage 3.2-F1 Checkpoint Overlay**
- successful run: `37257254728`

Independent acceptance:
- workflow: **Stage 3.2-F1 Acceptance**
- successful run: `37257397286`

Rejected pre-acceptance candidates:
- `37257111325`: rejected by target gate;
- `37257164716`: diagnostic rerun identified an import-order-only Ruff failure;
- the accepted candidate corrected that diagnosed defect before the green target gate.

## Accepted Checkpoint V1 contract

Checkpoint is optional private runtime state and is never required for
correctness.

Durable row:
- one `run_checkpoints` row per Run;
- migration: `0016_checkpoint_overlay`.

Stored fields:
- schema_version;
- runner_version;
- run_state_version;
- execution_spec_identity;
- working_state;
- message_high_water;
- event_high_water;
- context_cursor;
- created_at.

## Restore eligibility

A checkpoint overlay is returned only when all of the following are exact:

```text
checkpoint.schema_version == supported schema
checkpoint.runner_version == current runner
checkpoint.execution_spec_identity == current execution spec
checkpoint.run_state_version == durable RunState.state_version
checkpoint.message_high_water == durable message sequence
checkpoint.event_high_water == durable event sequence
Run is QUEUED or RUNNING
```

Any mismatch returns no checkpoint overlay.

Correctness then reconstructs from durable facts.

## Frozen F1 invariants

### F1-I1 — Durable facts outrank checkpoint

```text
authoritative durable facts
    >
checkpoint
    >
new model reasoning
```

Checkpoint never overrides:
- Run lifecycle/cancellation;
- ToolCall outcome;
- ExternalAction outcome;
- ToolExecutionAttempt;
- ReconciliationAttempt;
- ActionResolution;
- message/event durable history.

### F1-I2 — Checkpoint is disposable

Missing checkpoint, unsupported schema, runner mismatch, execution-spec
mismatch, or stale high-water marks are ordinary recovery conditions.

They are not Run failures.

### F1-I3 — Exact high-water only

F1 deliberately does not attempt a merge between stale private state and newer
business facts.

If any durable state/message/event has advanced, the older checkpoint is
discarded as an overlay.

### F1-I4 — No business authority in checkpoint payload

Checkpoint payload validation rejects authoritative/final business-state keys,
including cancellation/action/tool outcome projections.

Checkpoint cannot become a parallel state machine.

### F1-I5 — No chain-of-thought or resolved secrets

Checkpoint private payload validation rejects chain-of-thought/reasoning-trace
and resolved credential/secret fields.

Credential truth remains at the adapter edge only.

### F1-I6 — Save uses current owned generation

Checkpoint save is allowed only for the live owned RUNNING generation under
the Run lock and DB-time lease validation.

The stored high-water marks therefore describe one precise durable prefix.

### F1-I7 — No rollback-to-checkpoint

There is no restore operation that mutates durable business rows backward.

Loading a checkpoint can only supply compatible private runner overlay state.

## Accepted regression evidence

The PostgreSQL integration suite explicitly proves:
- missing checkpoint fallback;
- compatible checkpoint load;
- unsupported schema fallback;
- runner-version mismatch fallback;
- prohibited authority/secret/reasoning payload rejection;
- newer ToolCall/ExternalAction/ToolExecutionAttempt facts stale an older checkpoint;
- newer ReconciliationAttempt facts stale an older checkpoint;
- newer cancellation fact prevents checkpoint restore;
- full Python 3.14 + PostgreSQL 18 regression remains green.

## State

```text
Stage 3.2-F1
Checkpoint V1 Overlay Authority
✅ ACCEPTED / FROZEN

Stage 3.2-F2
Stateful Fake External Ledger + Crash Barriers
🔓 UNLOCKED

Stage 3.2-F3
Full Recovery / Crash Matrix + F Aggregate
🔒

Stage 3.2-G
Immutable RC + Final Acceptance
🔒
```

Governing rule:

> Checkpoint may accelerate reconstruction; it never defines business truth.
