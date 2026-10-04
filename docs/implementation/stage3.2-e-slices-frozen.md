# Stage 3.2-E Implementation Slices — FROZEN EXECUTION PLAN

Status: **IMPLEMENTATION PLAN FROZEN**

Parent frozen surfaces:
- `docs/design/stage3.2-durable-runtime-v1.0-frozen.md`
- `docs/acceptance/stage3.2-acceptance-v1.0-frozen.md`
- `docs/implementation/stage3.2-d-accepted.md`

Stage 3.2-E implements cancellation/manual-resolution authority and the races
around already-authorized external work. Implementation is split into three
independently gated slices.

## E1 — Durable cancellation intent + safe cancellation terminalization

Scope:
- add durable orthogonal `Run.cancel_requested`;
- cancellation transaction locks Run first;
- cancellation never claims rollback;
- stop any new ModelInvocation / READ attempt / side-effect Action Commit once
  cancellation owns progression authority;
- READY side-effect intent is stabilized to ABORTED / ToolCall NOT_EXECUTED
  before Run cancellation;
- no-active-work Run may terminalize CANCELLED immediately;
- EXECUTING side-effect is not blindly aborted: cancellation remains requested
  until external truth is safely stabilized;
- UNKNOWN / RECONCILING action may continue bounded safety reconciliation even
  though no fresh business work is allowed;
- MANUAL_REVIEW may coexist with CANCELLED as the frozen post-terminal unresolved
  combination;
- cancellation/result serialization is fenced by the Run row.

E1 does **not** create ActionResolution.

## E2 — Durable ActionResolution + manual-review continuation

Scope:
- durable ActionResolution entity/table;
- outcomes SUCCEEDED / FAILED / ABORTED;
- one final resolution per ExternalAction;
- resolution locks Run -> ExternalAction -> ToolCall;
- only MANUAL_REVIEW may be resolved;
- contradictory second resolution rejected;
- SUCCEEDED on non-cancelled Run:
  - queue ACTION_RESOLVED if DB-time deadline still permits continuation;
  - otherwise terminalize FAILED without new business work;
- FAILED / ABORTED on non-cancelled Run -> FAILED;
- CANCELLED + MANUAL_REVIEW resolution updates Action/ToolCall facts but never
  reopens the cancelled Run;
- terminal Run × ExternalAction matrix enforced.

E2 does not yet claim late-result race acceptance.

## E3 — Late-result authority + cancellation/resolution races + E aggregate

Scope:
- result-wins vs takeover-wins serialization orders;
- stale/late Tool result may become evidence only after UNKNOWN,
  RECONCILING, MANUAL_REVIEW, resolution, or final action transition won;
- late result cannot queue progression or restore stale generation authority;
- ActionResolution wins permanently once committed;
- delayed reconciliation / late physical result cannot overwrite resolution;
- cancellation vs model-result and cancellation vs side-effect-result races;
- real PostgreSQL concurrency tests for Run-row serialization;
- lock-order audit: Run -> ExternalAction -> ToolCall -> Attempt/Reconciliation;
- Stage 3.2-E aggregate acceptance and freeze.

## Gate discipline

For each slice:

```text
implement
  ↓
target gate
  ↓
independent acceptance
  ↓
freeze accepted slice
  ↓
unlock next slice
```

Stage 3.2-E aggregate acceptance remains locked until E1, E2 and E3-specific
acceptance evidence is green.

## Frozen safety rules

> Cancellation is not rollback.

> Persisted facts outrank new reasoning.

> Late evidence cannot regain progression authority.

> Manual resolution cannot be overwritten.

> The Run row remains the per-Run serialization point.
