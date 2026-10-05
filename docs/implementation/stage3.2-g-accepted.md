# Stage 3.2-G — Immutable RC + Final Runtime Acceptance — ACCEPTED / FROZEN

Status: **ACCEPTED / FROZEN**

Frozen parents:
- Stage 3.2 Design V1.0
- Stage 3.2-A
- Stage 3.2-B
- Stage 3.2-C
- Stage 3.2-D aggregate
- Stage 3.2-E aggregate
- Stage 3.2-F aggregate

## Immutable release-candidate history

### RC1 — rejected, preserved for audit

Immutable branch:
- `rc/stage3.2-v1.0`

Exact SHA:
- `3286e348166bc4e704121e5057444767a9cab8ac`

Gate:
- workflow: **Stage 3.2-G Immutable RC Gate**
- run: `37260449370`
- result: **REJECTED / FAILURE**

RC1 correctly passed:
- exact commit/ref identity;
- pinned Python/PostgreSQL/toolchain proof;
- frozen Stage 3.1 migration-lineage hash proof.

It failed the mandatory resume-migration proof:

```text
frozen Stage 3.1 head
0005_run_terminal_shape
        ↓
resume Alembic in a later process
        ↓
Stage 3.2 head
0016_checkpoint_overlay
```

The 12-window crash matrix and final full gate were therefore correctly skipped.
RC1 never became an accepted Stage 3.2 release candidate.

The immutable RC1 ref was not moved after rejection.

## RC1 root cause

The Stage 3.2 migration:

- `migrations/versions/0009_external_action_intent.py`

expanded the already-existing PostgreSQL enum `tool_effect_type` with:

- `WRITE`;
- `EXTERNAL_SIDE_EFFECT`;
- `DESTRUCTIVE`.

When upgrading from an already committed Stage 3.1 database, PostgreSQL
requires newly added enum values to commit before later DDL in the migration
references those values.

A base-to-head migration could hide this resume boundary because the enum type
itself was created earlier in the same migration run. The explicit
`0005 -> head` acceptance path correctly exposed the production-upgrade defect.

## Corrective migration amendment

Only the Stage 3.2 migration `0009_external_action_intent.py` was amended.

The enum expansion now runs inside an Alembic:

```python
with op.get_context().autocommit_block():
    ...
```

so the enum values are committed before the subsequent Stage 3.2 DDL uses
them.

Corrected RC implementation SHA:
- `fa747268cfbf1d5b57e5796b9cbc767abc3d4e0c`

Corrected `0009_external_action_intent.py` blob:
- `6becaf625042262b2fbd43f94b69564738fe2238`

The frozen Stage 3.1 migrations `0001` through `0005` were not modified.

## RC2 — accepted immutable candidate

Immutable branch:
- `rc/stage3.2-v1.0-r2`

Exact SHA:
- `fa747268cfbf1d5b57e5796b9cbc767abc3d4e0c`

Final gate:
- workflow: **Stage 3.2-G Immutable RC Gate**
- successful run: `37262139363`

Result:
- **SUCCESS**

### G1 — Exact immutable identity

Passed:
- checkout exactly `fa747268cfbf1d5b57e5796b9cbc767abc3d4e0c`;
- remote `rc/stage3.2-v1.0-r2` points to that exact SHA;
- the gate does not validate moving `main` as the release identity.

### G2 — Pinned toolchain + frozen Stage 3.1 lineage

Passed:
- Python 3.14 pin;
- locked dependency graph;
- PostgreSQL 18.6 acceptance image;
- pinned acceptance configuration;
- exact hashes for Stage 3.1 migrations `0001` through `0005`;
- exact hash for the RC2 `0009` migration amendment.

Stage 3.2 acceptance therefore did not rewrite the frozen Stage 3.1 baseline.

### G3 — Real forward upgrade from frozen Stage 3.1

Passed:

```text
empty PostgreSQL 18
    ↓
alembic upgrade 0005_run_terminal_shape
    ↓
new Alembic process
    ↓
alembic upgrade head
    ↓
0016_checkpoint_overlay
```

This proves the accepted Stage 3.2 schema can be applied to the frozen Stage
3.1 database lineage, not merely created successfully from an empty database.

### G4 — Immutable 12-window crash matrix

Passed against the exact RC2 SHA.

The matrix covers:

1. before Action preparation commit;
2. after READY commit;
3. before Action Commit;
4. after Action Commit before external call;
5. during external call;
6. after external effect commit before response;
7. after response before DB result commit;
8. during result commit;
9. during reconciliation request;
10. after reconciliation response before result commit;
11. during durable retry/yield;
12. during cancellation/model-result race.

The accepted candidate preserves the frozen no-blind-duplicate and
UNKNOWN-before-retry invariants.

### G5 — Final full project gate

Passed against the same immutable RC2 SHA:

- Python 3.14;
- `uv sync --locked`;
- Ruff;
- Ruff format check;
- mypy strict;
- compile/import validation;
- Alembic online migrations;
- full unit suite;
- full PostgreSQL integration suite;
- required durability/concurrency/recovery cases.

No mutable-main substitution was used for final release acceptance.

## Final Stage 3.2 acceptance assertions

The accepted RC proves all Stage 3.2 governing properties remain true:

- every physical Tool call has a durable attempt;
- durable intent precedes every side effect;
- Action Commit precedes every physical side-effect invocation;
- UNKNOWN is distinct from FAILED;
- uncertain side effects are reconciled before potentially duplicating retry;
- safe retry requires proof of non-execution;
- stable operation identity survives retry/restart/takeover;
- BEST_EFFORT reconciliation cannot authorize unsafe non-idempotent retry;
- bounded reconciliation safety work is separate from ordinary business budget;
- cancellation fences progression and never claims rollback;
- manual resolution cannot be overwritten by late autonomous evidence;
- late/stale executor results cannot regain progression authority;
- checkpoints remain subordinate to newer durable facts;
- PostgreSQL server time remains scheduling/deadline authority;
- the frozen Stage 3.1 migration lineage remains intact;
- Stage 3.1 -> Stage 3.2 forward upgrade is proven;
- the complete Python 3.14 + PostgreSQL 18 acceptance gate is green.

## Stage 3.2 final state

```text
Stage 3.2 Design V1.0
✅ ACCEPTED / FROZEN

Stage 3.2-A
✅ ACCEPTED / FROZEN

Stage 3.2-B
✅ ACCEPTED / FROZEN

Stage 3.2-C
✅ ACCEPTED / FROZEN

Stage 3.2-D
✅ ACCEPTED / FROZEN

Stage 3.2-E
✅ ACCEPTED / FROZEN

Stage 3.2-F
✅ ACCEPTED / FROZEN

Stage 3.2-G
✅ ACCEPTED / FROZEN

Stage 3.2 Runtime V1.0
✅ ACCEPTED / FROZEN

Stage 3.3
🔓 UNLOCKED
```

The authoritative Stage 3.2 Runtime V1.0 implementation identity is:

```text
branch: rc/stage3.2-v1.0-r2
sha:    fa747268cfbf1d5b57e5796b9cbc767abc3d4e0c
gate:   37262139363
```

Governing release rule:

> Acceptance belongs to the immutable candidate that passed the gate, not to a
> later mutable branch head.
