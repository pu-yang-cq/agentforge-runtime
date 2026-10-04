# Stage 3.2-C1 — Fenced Action Commit Boundary

Status: **IMPLEMENTED / TARGET GATE PASSED**

Parent frozen contracts:
- `docs/design/stage3.2-durable-runtime-v1.0-frozen.md`
- `docs/acceptance/stage3.2-acceptance-v1.0-frozen.md`
- `docs/implementation/stage3.2-b-accepted.md`

Implementation commit:
- `faea579a6c47b05556d8e35764e4ca67f13c0453`

Target gate:
- workflow: **Stage 3.2-C1 Action Commit Boundary**
- successful run: `37205740852`

## Implemented boundary

A durable READY ExternalAction is recovered before any new model reasoning and crosses a second fenced transaction before physical external I/O:

```text
ExternalAction READY
+ ToolCall READY
+ immutable ActionSnapshot
        ↓
BEGIN
  lock/fence current Run authority
  re-check DB deadline + ordinary Tool-attempt budget
  verify action is still READY and has no current attempt
  reserve one tool attempt
  create ToolExecutionAttempt STARTED
  ToolCall -> EXECUTING
  ExternalAction -> EXECUTING
  current_attempt_id = attempt.id
  append ACTION_COMMITTED / TOOL_STARTED
COMMIT
        ↓
SideEffectInvocation
  operation_id
  immutable snapshot arguments
  opaque credential_ref
  provider idempotency key when declared
        ↓
physical side-effect adapter call
```

The adapter cannot be invoked through the ordinary READ `Tool.invoke()` path.

## C1 invariants

1. **Commit before effect** — adapter invocation occurs only after `record_side_effect_attempt_started()` has durably committed the authorization tuple.
2. **One physical call = one durable attempt** — side-effect execution owns a `ToolExecutionAttempt STARTED` with `external_action_id`.
3. **Stable identity** — retries/recovery use the B-frozen `operation_id` and ActionSnapshot; model text never reconstructs external identity.
4. **Active pointer semantics** — `current_attempt_id` is non-null only while the action is EXECUTING and is cleared on the implemented success path.
5. **READY recovery precedes reasoning** — takeover/restart loads a READY ExternalAction and executes the same durable intent before asking the model for a replacement proposal.
6. **Permanent pre-commit denial is zero-I/O** — if budget/deadline permanently forbids a READY action, the action becomes ABORTED and ToolCall NOT_EXECUTED without creating a STARTED attempt.
7. **No new migration** — C1 is a runtime transition slice over the frozen B schema; Alembic remains at `0010_side_effect_preparation`.

## Explicitly deferred

C1 does not yet claim the full Stage 3.2 result-classification/reconciliation contract. In particular, ambiguous/possible-execution outcomes, UNKNOWN, reconciliation attempts, orphaned side-effect takeover, safe side-effect retry, cancellation races, manual resolution, late-result races, and checkpoint recovery remain assigned to D/E/F.

## Gate conclusion

```text
Stage 3.2-B
✅ ACCEPTED / FROZEN

Stage 3.2-C1
✅ IMPLEMENTED
✅ TARGET GATE PASSED

Stage 3.2-C aggregate acceptance
🔓 READY FOR INDEPENDENT ACCEPTANCE

Stage 3.2-D
🔒
```

Governing rule:

> Action Commit before Effect.
