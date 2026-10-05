# Stage 3.2-E3 — Late-result Authority + Race Semantics — ACCEPTED / FROZEN

Status: **ACCEPTED / FROZEN**

Parent frozen surfaces:
- Stage 3.2-D aggregate
- Stage 3.2-E1 cancellation
- Stage 3.2-E2 action resolution
- `docs/implementation/stage3.2-e-slices-frozen.md`

Implementation commit:
- `f1e5cd9d80497bd39953a7d21704a563e6bf8d85`

Target implementation gate:
- workflow: **Stage 3.2-E3 Late-result Authority**
- successful run: `37256391604`

Independent acceptance:
- workflow: **Stage 3.2-E3 Acceptance**
- successful run: `37256507004`

Earlier rejected candidates:
- `37256023484`: patch anchor rejected before test execution;
- `37256112573`: target regression gate rejected;
- `37256235138`: diagnostic rerun identified Ruff-only failures;
- the accepted candidate fixed only those diagnosed defects before the green target gate.

## Accepted E3 authority semantics

All cancellation/result/resolution races serialize through the durable Run row
before action/call/attempt mutation.

### Result wins before cancellation

If a physical side-effect result becomes durable first:

```text
Run lock
  -> ExternalAction
  -> ToolCall
  -> ToolExecutionAttempt
  -> external success truth committed
  -> cancellation arrives later
```

Cancellation may terminalize the Run, but it does not roll back the already
committed business truth.

The durable Action, ToolCall and Attempt remain SUCCEEDED.

### Cancellation wins before a late physical result

If cancellation acquires and commits the Run-row decision while an already
authorized physical side effect is still in flight:

```text
cancel_requested = true
        ↓
late physical result returns
        ↓
result recorder locks Run first
        ↓
external result truth may still be recorded
        ↓
Run = CANCELLED
        ↓
old worker progression authority is fenced
```

The runtime therefore separates:

- **external business truth** — which may still need to be recorded; from
- **business progression authority** — which cancellation has permanently won.

After recording the late success, the stale worker receives
`StaleExecutorError` and cannot feed that result into a new model turn.

### Cancellation wins before reconciliation result

A reconciliation result may still settle ExternalAction / ToolCall truth after
cancel_requested becomes durable.

For authoritative SUCCEEDED or FAILED reconciliation:

- ReconciliationAttempt records the returned business truth;
- ExternalAction / ToolCall project that truth;
- Run remains CANCELLED;
- no model continuation is emitted;
- cancellation is not converted into FAILED or QUEUED.

### Manual ActionResolution wins permanently

Once an ActionResolution has committed:

- the resolution row is final and single-valued per ExternalAction;
- contradictory replay is rejected;
- resolved ExternalAction / ToolCall truth may not be overwritten by a late
  physical result or reconciliation;
- stale generation / non-RUNNING Run ownership fences old result recorders.

## Frozen E3 invariants

### E3-I1 — Run row is the race serialization point

Every business-state result transition that can race cancellation or manual
resolution must establish current Run authority before mutating child state.

Canonical lock order remains:

```text
Run
  -> ExternalAction
  -> ToolCall
  -> ToolExecutionAttempt / ReconciliationAttempt
```

### E3-I2 — Cancellation stops progression, not evidence

A late external result after cancel_requested may establish durable external
truth.

It may not:
- reopen the Run;
- queue a new model turn;
- schedule a side-effect retry;
- restore an old generation;
- clear cancellation authority.

### E3-I3 — Result-before-cancel does not lose truth

Cancellation is not a rollback mechanism.

Already durable success/failure truth survives later cancellation.

### E3-I4 — Cancel-before-result fences the old executor

After the result transaction records external truth under a previously committed
cancel_requested flag, the current executor is explicitly denied further
progression authority.

### E3-I5 — Reconciliation cannot reopen cancellation

A reconciliation result returned after cancellation may update action truth but
must leave the Run CANCELLED and return no continuation message.

### E3-I6 — ActionResolution is final

Manual resolution is not advisory evidence. Once committed it is the final
operator-owned business truth for the unresolved action.

Late autonomous results cannot overwrite it.

### E3-I7 — No stale generation resurrection

A recorder whose generation is no longer the currently owned RUNNING generation
cannot mutate business progression after takeover, manual resolution, or
terminalization.

## Accepted race coverage

The committed PostgreSQL integration suite explicitly covers:

- result wins, then cancellation;
- cancellation wins, then physical result;
- cancellation wins, then reconciliation success;
- manual resolution wins, then stale physical result;
- E1/E2 cancellation and resolution regressions;
- full Stage 3.1 / Stage 3.2 regression suite.

## State

```text
Stage 3.2-E1
Cancellation
✅ ACCEPTED / FROZEN

Stage 3.2-E2
Action Resolution
✅ ACCEPTED / FROZEN

Stage 3.2-E3
Late-result Authority + Races
✅ ACCEPTED / FROZEN

Stage 3.2-E aggregate acceptance
🔓 UNLOCKED

Stage 3.2-F
Checkpoint + Recovery Matrix
🔒

Stage 3.2-G
Immutable RC + Final Acceptance
🔒
```

Governing rule:

> Late evidence may refine external truth; it may never resurrect lost
> progression authority.
