# Stage 3.1 Core Runtime V1.0 — ACCEPTED / FROZEN

Status: **ACCEPTED**
Freeze: **Core Runtime V1.0**
Next stage: **Stage 3.2 Durable Runtime UNLOCKED**

## Accepted immutable source

- Release candidate: V1.0-RC4
- RC4 source SHA-256:
  `696a889a86fc35ea127f6fde803818269427df978d2268345ea614af56d847b7`
- Reviewed `uv.lock` SHA-256:
  `ea589824df68c1412a9ba797f673cf4110e122540a06e02ffcf15bb3e4fa406a`

## Official target acceptance

- GitHub Actions workflow: Stage 3.1 Acceptance
- Run ID: 37185024586
- Accepted envelope commit:
  `7a03504daa3a1e2d66d96b5f3c59ed15b7965c41`
- Result: **SUCCESS**

Verified by the official run:

- immutable RC4 payload SHA verification: PASS
- reviewed lockfile SHA verification: PASS
- CPython 3.14.7: PASS
- locked dependency environment: PASS
- installed AgentForge package import: PASS
- Ruff lint: PASS
- Ruff format check: PASS (47 files)
- mypy strict: PASS (27 source files)
- PostgreSQL major version 18: PASS
- Alembic online migration 0001 -> 0005: PASS
- mandatory PostgreSQL integration/concurrency/recovery suite: PASS
- full suite: **68 passed**
- target acceptance result: **PASSED**

## Real target failures resolved before acceptance

The target gate materially improved the implementation before freeze:

1. Python package boundary / mypy duplicate `main` module.
2. SQLAlchemy result typing under the target mypy version.
3. Alembic revision identifier exceeded the default `VARCHAR(32)` version column.
4. Integration fixture relied on implicit ORM insert ordering across FK parents/association rows.
5. Production `create_run()` relied on implicit ORM ordering between `RunRow` and FK child facts; RC4 now explicitly flushes the Run parent inside the same ACID transaction before state/counter/message/events.

No FK constraint was weakened to make the tests pass.

## Frozen Stage 3.1 guarantees

The accepted Wave-1 runtime covers:

- durable Run creation and idempotency
- immutable AgentVersion / ToolVersion binding for the Wave-1 slice
- PostgreSQL-backed queue and `FOR UPDATE SKIP LOCKED` claim
- DB-time lease and execution-generation fencing
- provider-neutral model boundary with durable ModelInvocation lifecycle
- durable ToolProposal / READ ToolCall lifecycle
- deterministic READ recovery before new model reasoning
- worker takeover / restart recovery
- event and message sequencing
- active-progression database invariants
- terminal Run shape constraints
- Python 3.14 + PostgreSQL 18 target validation

## Non-blocking follow-up

The accepted run emitted Alembic configuration deprecation warnings about
`path_separator`; this is maintenance debt, not a Stage 3.1 correctness blocker.

## Freeze rule

Stage 3.1 behavior is frozen. Future Stage 3.2 work must extend the accepted
runtime without silently weakening Stage 3.1 invariants. Any necessary
regression fix must include a regression test and re-run the relevant gates.
