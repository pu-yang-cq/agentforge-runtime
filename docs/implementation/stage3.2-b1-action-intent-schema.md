# Stage 3.2-B1 — ActionSnapshot V1 and ExternalAction Intent Schema

Status: **IMPLEMENTED / SLICE GATE PASSED**
Parent design: **Stage 3.2 Durable Runtime Design V1.0 — FROZEN**
Parent accepted slice: **Stage 3.2-A — ACCEPTED / FROZEN**

## Scope implemented

B1 establishes the durable side-effect intent substrate without crossing the
external-effect boundary.

Implemented:

- ToolEffectType expanded with WRITE, EXTERNAL_SIDE_EFFECT and DESTRUCTIVE;
- ExternalActionStatus domain enum;
- ActionSnapshot V1 domain value;
- AgentForge Canonical JSON V1 restricted value validation;
- UTF-16 object-member ordering required by RFC 8785 semantics;
- raw floating-point rejection;
- interoperable safe-integer range enforcement;
- Unicode scalar-value validation;
- SHA-256 snapshot digest;
- golden canonical-byte/digest vectors;
- ExternalAction durable domain identity with stable operation_id;
- action_snapshots PostgreSQL table;
- external_actions PostgreSQL table;
- globally unique ExternalAction operation_id;
- one ActionSnapshot per ExternalAction;
- one ExternalAction per ToolCall;
- max one nonterminal ExternalAction per Run;
- current_attempt_id shape constraint;
- ToolExecutionAttempt.external_action_id upgraded to a real foreign key;
- migration 0009_external_action_intent.

## Target gate evidence

GitHub Actions:

- workflow: Stage 3.2-B1 Snapshot Persistence
- run ID: 37201697196
- conclusion: SUCCESS
- implementation commit:
  `4e47639ce5c97e4fe5ea81ae694342d5d8bf5388`

Evidence:

- Ruff lint: PASS;
- Ruff format: PASS, 55 files;
- mypy: PASS, 28 source files;
- PostgreSQL major: 18;
- Alembic online migration through 0009: PASS;
- full suite: **96 passed**.

## Safety boundary

B1 performs no external side-effect I/O.

It does not:

- start a side-effect ToolExecutionAttempt;
- move ExternalAction to EXECUTING;
- resolve credentials;
- call a side-effect adapter;
- reconcile UNKNOWN outcomes.

The Action Commit Boundary remains locked for Stage 3.2-C.

## Next B sub-slice

B2 must implement the fenced side-effect preparation transaction:

- lock Run;
- re-check ownership/generation/lease;
- re-check deadline and budget;
- reject destructive/not-executable ToolVersion;
- create ToolCall + ActionSnapshot + ExternalAction READY atomically;
- append durable events;
- perform zero external I/O.

## Gate

```text
Stage 3.2-A
✅ ACCEPTED / FROZEN

Stage 3.2-B1
✅ IMPLEMENTED
✅ TARGET SLICE GATE PASSED

Stage 3.2-B2 — fenced side-effect preparation
🔓 UNLOCKED

Stage 3.2-B aggregate acceptance
🔒

Stage 3.2-C
🔒
```
