# Stage 3.2-E2 — Durable ActionResolution + Manual-review Continuation — ACCEPTED / FROZEN

Status: **ACCEPTED / FROZEN**

Parent frozen surfaces:
- Stage 3.2-D aggregate
- Stage 3.2-E1 durable cancellation
- `docs/implementation/stage3.2-e-slices-frozen.md`

Implementation commit:
- `3d366f297e6a19973ffc03f36356fb87b943ffe8`

Target implementation gate:
- workflow: **Stage 3.2-E2 Action Resolution**
- first candidate run `37214920965` rejected by full target gate;
- diagnostics isolated the failure to candidate Ruff canonicalization;
- runtime semantics were unchanged;
- successful target run: `37215071242`.

Independent acceptance:
- workflow: **Stage 3.2-E2 Acceptance**
- successful run: `37215212570`.

## Accepted E2 semantics

### ActionResolution is a durable final manual fact

E2 introduces one durable ActionResolution per ExternalAction:

```text
ActionResolution
  id
  action_id
  outcome = SUCCEEDED | FAILED | ABORTED
  evidence
  reason
  resolver_identity
  created_at
```

Database uniqueness on `external_action_id` enforces one final resolution.

An exact replay of the same resolution request is idempotent and returns the
existing durable resolution.

A contradictory or different second final resolution is rejected.

### Resolution eligibility

Only:

```text
ExternalAction = MANUAL_REVIEW
ToolCall = UNRESOLVED
```

may be manually resolved.

Valid Run combinations are:

```text
WAITING_ACTION_RESOLUTION + MANUAL_REVIEW
CANCELLED + MANUAL_REVIEW
```

No resolution command creates or legitimizes:
- COMPLETED + MANUAL_REVIEW;
- FAILED + MANUAL_REVIEW;
- READY/EXECUTING/UNKNOWN/RECONCILING manual resolution.

### Lock order

Manual resolution uses the frozen per-Run ordering:

```text
Run
  -> ExternalAction
  -> ToolCall
```

The Run row remains the serialization point.

### Non-cancelled SUCCEEDED

When the operator resolves the action as SUCCEEDED:

```text
ExternalAction MANUAL_REVIEW -> SUCCEEDED
ToolCall UNRESOLVED -> SUCCEEDED
ActionResolution persisted
```

If PostgreSQL time is still before the Run deadline:

```text
durable TOOL message
Run -> QUEUED
queue_reason = ACTION_RESOLVED
owner_worker_id = NULL
lease_expires_at = NULL
```

A later worker resumes normal model progression from the durable resolved fact.

### SUCCEEDED after deadline

Manual truth is still accepted:

```text
Action -> SUCCEEDED
ToolCall -> SUCCEEDED
ActionResolution -> durable
```

but no fresh business work is allowed.

The Run terminalizes FAILED with:

```text
DEADLINE_EXCEEDED_AFTER_ACTION_RESOLUTION
```

### FAILED / ABORTED

Manual FAILED:

```text
Action -> FAILED
ToolCall -> FAILED
Run -> FAILED
```

Manual ABORTED:

```text
Action -> ABORTED
ToolCall -> NOT_EXECUTED
Run -> FAILED
```

Neither branch schedules new autonomous business work.

### Post-terminal CANCELLED + MANUAL_REVIEW

A cancelled Run may still receive explicit human resolution of unresolved
external truth.

Resolution updates:
- Action;
- ToolCall;
- ActionResolution evidence/events.

It does not reopen the Run.

```text
Run CANCELLED
        ↓
manual resolution
        ↓
Run CANCELLED
```

No ACTION_RESOLVED queue is created.

## Frozen E2 invariants

### E2-I1 — One final resolution per action

The first committed ActionResolution is final.

Exact replay is idempotent; contradictory second resolution is rejected.

### E2-I2 — Manual resolution only resolves MANUAL_REVIEW

ActionResolution cannot be used as a generic action-state override.

### E2-I3 — Resolution locks Run first

All resolution transitions serialize through:

```text
Run -> ExternalAction -> ToolCall
```

### E2-I4 — Manual success does not bypass deadline

Human evidence may settle external truth after deadline, but it cannot authorize
new model/business work after deadline.

### E2-I5 — Cancellation remains terminal authority

Manual resolution on CANCELLED updates facts only.

It may never:
- queue ACTION_RESOLVED;
- acquire worker ownership;
- restore lease;
- restart model progression.

### E2-I6 — ToolCall projection remains deterministic

Manual outcomes project:

```text
SUCCEEDED -> ToolCall SUCCEEDED
FAILED    -> ToolCall FAILED
ABORTED   -> ToolCall NOT_EXECUTED
```

No model reasoning is used to derive this projection.

### E2-I7 — E2 stops before late-result race acceptance

E2 does not yet claim that delayed:
- physical side-effect result;
- reconciliation result;
- stale worker result

cannot race and overwrite a committed manual resolution.

That authority/race matrix remains Stage 3.2-E3.

## Durable additions

Migration:
- `0015_action_resolution`

Table:
- `action_resolutions`

Enum:
- `ActionResolutionOutcome`

API:
- `POST /v1/runs/{run_id}/actions/{action_id}/resolve`

## State

```text
Stage 3.2-E1
✅ ACCEPTED / FROZEN

Stage 3.2-E2
✅ ACCEPTED / FROZEN

Stage 3.2-E3
Late-result Authority + Cancellation/Resolution Races
🔓 UNLOCKED

Stage 3.2-E aggregate acceptance
🔒

Stage 3.2-F
🔒

Stage 3.2-G
🔒
```

Governing rules:

> Manual resolution cannot be overwritten.

> Cancellation is not rollback.

> Late evidence cannot regain progression authority.

> The Run row remains the per-Run serialization point.
