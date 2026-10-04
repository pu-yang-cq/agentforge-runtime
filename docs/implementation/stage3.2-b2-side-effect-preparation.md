# Stage 3.2-B2 — Fenced Side-effect Preparation Transaction

Status: **IMPLEMENTED / TARGET GATE PASSED**

Parent design:
- `docs/design/stage3.2-durable-runtime-v1.0-frozen.md`
- `docs/acceptance/stage3.2-acceptance-v1.0-frozen.md`

Implementation commit:
- `eb5f6f0e5b833221946ae3b95fa7800f935d8c03`

Target gate:
- workflow: **Stage 3.2-B2 Side-effect Preparation**
- successful run: `37204268914`
- first diagnostic run: `37204159309` (failed only on mypy union inference; no implementation commit was emitted)
- Ruff: PASS
- Ruff format: PASS, 56 files
- mypy strict: PASS, 28 source files
- PostgreSQL: PASS, major 18
- Alembic: PASS through `0010_side_effect_preparation`
- tests: PASS, 105 passed

## Implemented boundary

A model-originated Stage-3.2-executable side-effect proposal now follows:

```text
ToolProposal
    ↓
resolve immutable ToolVersion binding/capabilities
    ↓
construct ToolCall READY
    +
stable operation_id
    +
ActionSnapshot V1
    +
ExternalAction READY
    ↓
BEGIN
  lock live owned Run
  re-check generation + DB lease
  reject conflicting active ToolCall / STARTED Tool attempt
  check DB deadline
  check remaining ordinary Tool-attempt budget
  re-check durable ToolVersion eligibility
  atomically complete ModelInvocation
  persist ToolProposal
  persist ToolCall READY
  persist ActionSnapshot
  persist ExternalAction READY
  append MODEL_COMPLETED / TOOL_PROPOSED / ACTION_PREPARED
COMMIT
    ↓
STOP
```

No `ToolExecutionAttempt` is created by preparation.
No `tool_attempts_used` budget is reserved by preparation.
No side-effect adapter is invoked by preparation.

Physical side-effect execution remains locked until Stage 3.2-C Action Commit Boundary.

## ToolVersion eligibility facts

Stage 3.2-B2 adds durable ToolVersion capability/configuration facts:

- `approval_required`
- `allow_no_approval_execution`
- `credential_ref`
- `idempotency_supported`
- `reconciliation_mode = AUTHORITATIVE | BEST_EFFORT | NONE`

Preparation fails closed for:
- READ routed through the side-effect path;
- DESTRUCTIVE execution;
- approval-required execution;
- a side effect not explicitly eligible for no-approval execution;
- invalid/blank credential reference configuration;
- stale generation / expired DB lease;
- expired DB deadline;
- exhausted ordinary Tool-attempt budget;
- conflicting active Tool progression;
- a ToolVersion no longer durably bound/eligible at transaction time.

## Recovery safety correction

B2 closes a critical intermediate-stage hazard.

Before B2, recovery loaded any `ToolCall READY` as a recoverable READ. Once B2 introduced side-effect `ToolCall READY`, that broad query could have made a READY side-effect intent eligible for the READ execution path.

The accepted B2 implementation adds two independent guards:

1. PostgreSQL recovery selects only ToolVersions whose `effect_type = READ` and rejects calls linked to an ExternalAction.
2. `ToolCoordinator.prepare_recovered_read()` independently rejects non-READ ToolBindings.

Therefore a durable side-effect intent cannot cross the external-I/O boundary through READ recovery.

## Explicitly not implemented here

B2 does **not** implement:
- side-effect `ToolExecutionAttempt STARTED`;
- `ExternalAction READY -> EXECUTING`;
- `current_attempt_id` authorization;
- ordinary Tool-attempt budget reservation for a side effect;
- credential secret resolution;
- external API invocation;
- result classification;
- UNKNOWN / reconciliation;
- cancellation / manual resolution.

Those remain assigned to later frozen Stage 3.2 slices.

## Gate conclusion

```text
Stage 3.2-B1  ActionSnapshot V1 + ExternalAction persistence
✅ IMPLEMENTED

Stage 3.2-B2  Fenced side-effect preparation transaction
✅ IMPLEMENTED
✅ TARGET GATE PASSED

Stage 3.2-B aggregate acceptance
🔓 READY FOR INDEPENDENT ACCEPTANCE

Stage 3.2-C Action Commit Boundary
🔒
```

The governing safety rule remains:

> Intent Before Effect
