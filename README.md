# AgentForge

Production-Grade Agent Runtime & Governance Platform.

## Current release gate

**Stage 3.1 Core Runtime — V1.0-RC1**

Stage 3.1 is code-frozen and is **not accepted yet**. Stage 3.2 remains locked until the
real Python 3.14 + PostgreSQL 18 target acceptance passes.

Local RC1 evidence before remote acceptance:

- 49 local/unit/contract tests passed
- 1 integration module intentionally skipped without PostgreSQL 18
- offline Alembic migration chain passed
- local/static blockers: 0

## Immutable RC1 acceptance payload

The source under acceptance is stored as four base64 parts in `rc/`.
GitHub Actions reconstructs the tarball and verifies:

`20a19cd990dbf121cecc308e446d322432ab41ad85d2255f57695e3f2cb5f05d`

before executing it. See `rc/RC1_SOURCE_SHA256`.

## Acceptance sequence

1. Actions → **Stage 3.1 Lock Bootstrap** → Run workflow.
2. Download `stage31-uv-lock-review`.
3. Review `uv.lock` and its SHA-256.
4. Commit the reviewed `uv.lock` to repository root.
5. Actions → **Stage 3.1 Acceptance** → Run workflow.
6. Only a fully green target gate may mark Stage 3.1 ACCEPTED / FROZEN.

The acceptance workflow runs the frozen containerized gate with Python 3.14,
PostgreSQL 18, Ruff, formatting, mypy, Alembic, and real concurrency/recovery tests.

No acceptance workflow is allowed to generate or silently modify `uv.lock`.
