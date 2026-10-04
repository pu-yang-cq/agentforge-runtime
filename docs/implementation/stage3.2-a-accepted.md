# Stage 3.2-A — Durable READ Runtime Acceptance

Status: **ACCEPTED / FROZEN**
Parent design: **Stage 3.2 Durable Runtime Design V1.0 — FROZEN**

## Accepted scope

Stage 3.2-A now provides the durable READ execution substrate required by later
side-effect work:

- unified logical ToolCall versus physical ToolExecutionAttempt;
- durable physical attempt numbering and generation fencing;
- orphaned READ attempt closure to UNKNOWN on takeover;
- deterministic retry of the same logical ToolCall before new model reasoning;
- task model-invocation budget;
- task tool-attempt budget;
- PostgreSQL database-time deadline enforcement;
- cooperative durable Run yield/requeue;
- explicit transient READ retry classification;
- versioned READ retry policy;
- bounded exponential retry backoff;
- durable available_at scheduling;
- retry behavior constrained by budget and deadline.

## Aggregate acceptance evidence

GitHub Actions:

- workflow: Stage 3.2-A Acceptance
- run ID: 37201310656
- conclusion: SUCCESS
- accepted main head at trigger:
  `98a1a945710135724209d1def544c4581a17b3a6`

Evidence:

- migration envelope 0006 / 0007 / 0008: PASS;
- Ruff lint: PASS;
- Ruff format: PASS, 51 files;
- mypy: PASS, 27 source files;
- PostgreSQL major: 18;
- Alembic online migration through 0008: PASS;
- full suite: **90 passed**;
- Stage 3.2-A semantic-surface assertions: PASS.

## Freeze boundary

The accepted Stage 3.2-A semantics are frozen while Stage 3.2-B is built.
Later slices may extend the runtime but must preserve:

- same logical ToolCall across deterministic retries;
- one physical ToolExecutionAttempt per adapter invocation;
- durable attempt budget accounting;
- database-time deadline authority;
- no blind retry of unknown outcomes;
- Run-row progression fencing;
- durable yield/requeue behavior.

## Not yet accepted

Stage 3.2-A does not implement or accept:

- ActionSnapshot V1;
- ExternalAction;
- side-effect adapter execution;
- Action Commit Boundary;
- reconciliation;
- cancellation expansion;
- manual resolution;
- checkpoint V1.

## Gate

```text
Stage 3.2-A
✅ ACCEPTED
✅ FROZEN

Stage 3.2-B — ActionSnapshot V1 + ExternalAction persistence
🔓 UNLOCKED

Stage 3.2-C
🔒

Stage 3.2-D
🔒

Stage 3.2-E
🔒

Stage 3.2-F
🔒

Stage 3.2-G
🔒
```
