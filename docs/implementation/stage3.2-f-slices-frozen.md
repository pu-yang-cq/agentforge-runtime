# Stage 3.2-F Implementation Slices — FROZEN EXECUTION PLAN

Status: **IMPLEMENTATION PLAN FROZEN**

Parent contracts:
- `docs/design/stage3.2-durable-runtime-v1.0-frozen.md`
- `docs/acceptance/stage3.2-acceptance-v1.0-frozen.md`
- `docs/implementation/stage3.2-e-accepted.md`

Stage 3.2-F implements recovery evidence and crash validation. It does not add
new business authority.

## F1 — Checkpoint V1 overlay authority

Scope:
- durable optional Checkpoint V1;
- schema_version and runner_version compatibility checks;
- run_state_version, message_high_water and event_high_water freshness checks;
- execution-spec identity binding;
- private working_state/context_cursor only;
- explicit rejection of authoritative business truth, secrets and
  chain-of-thought-like fields from checkpoint payloads;
- missing/stale/unsupported checkpoint -> durable reconstruction path;
- checkpoint never overrides Run, ToolCall, ExternalAction,
  ToolExecutionAttempt, ReconciliationAttempt, cancellation or resolution facts.

Checkpoint remains optional for correctness.

## F2 — Stateful fake external ledger + crash barriers

Scope:
- deterministic in-memory/stateful fake provider ledger exposing:
  operation_id, external_resource_id, call count, effect count,
  duplicate-request count and reconciliation-query count;
- success, definite-no-effect, ambiguous timeout, commit+response-loss,
  delayed result, authoritative and best-effort reconciliation modes;
- controlled barriers at the frozen Stage 3.2 crash boundaries;
- no secret leakage into durable/runtime evidence.

F2 is test infrastructure. It does not become production provider logic.

## F3 — Full recovery/crash matrix + F aggregate

Scope:
- execute all 12 mandatory crash windows from acceptance AG;
- verify takeover precedence from frozen design section 31;
- verify checkpoint missing/stale/unsupported reconstruction;
- prove no blind duplicate non-idempotent effect at any crash point;
- exercise retry due-time persistence/restart behavior;
- cross-table recovery and lock-order stress;
- run full Python 3.14 + PostgreSQL 18 regression gate;
- independent F aggregate acceptance and freeze.

## Gate discipline

Each F slice follows:

```text
implement
  -> target gate
  -> independent acceptance
  -> freeze
  -> unlock next slice
```

Stage 3.2-G stays locked until F1/F2/F3 and the F aggregate gate are all green.

Governing precedence:

> authoritative durable facts > checkpoint > new model reasoning.
