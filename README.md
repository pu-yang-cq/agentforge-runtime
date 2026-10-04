# AgentForge

Production-Grade Agent Runtime & Governance Platform.

## Current release gate

**Stage 3.1 Core Runtime — V1.0 ACCEPTED / FROZEN**

Stage 3.1 passed the independent Python 3.14 + PostgreSQL 18 target acceptance.
Stage 3.2 Durable Runtime is now **UNLOCKED**.

Accepted immutable source:

- Release candidate: `V1.0-RC4`
- RC4 SHA-256:
  `696a889a86fc35ea127f6fde803818269427df978d2268345ea614af56d847b7`
- Reviewed `uv.lock` SHA-256:
  `ea589824df68c1412a9ba797f673cf4110e122540a06e02ffcf15bb3e4fa406a`
- Official acceptance run: `37185024586`
- Accepted envelope commit:
  `7a03504daa3a1e2d66d96b5f3c59ed15b7965c41`
- Frozen branch: `stage3.1-v1.0-frozen`

Official target evidence:

- CPython 3.14.7
- PostgreSQL 18
- Ruff lint: PASS
- Ruff format check: PASS
- mypy strict: PASS
- Alembic online migration `0001 -> 0005`: PASS
- mandatory PostgreSQL integration/concurrency/recovery suite: PASS
- full suite: **68 passed**
- target gate: **PASSED**

See `docs/acceptance/stage3.1-v1.0-accepted.md` for the final acceptance record.

## Freeze rule

Stage 3.1 behavior is frozen. Stage 3.2 must extend the accepted runtime without
silently weakening Stage 3.1 invariants. Any regression fix must include a
regression test and re-run the relevant acceptance gates.
