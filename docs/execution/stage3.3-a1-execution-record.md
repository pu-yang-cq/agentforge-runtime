# Stage 3.3-A1 — Engineering Execution Record

Status: **IMPLEMENTATION + ACCEPTANCE COMPLETE / VERIFIED**

Parent contracts:
- `docs/design/stage3.3-governance-v1.0-frozen.md`
- `docs/acceptance/stage3.3-governance-acceptance-v1.0-frozen.md`
- `docs/implementation/stage3.3-slices-frozen.md`
- `docs/execution/verified-execution-protocol-v1.0.md`

Frozen regression baseline:
- Stage 3.2 Runtime V1.0 immutable RC2
- `rc/stage3.2-v1.0-r2`
- `fa747268cfbf1d5b57e5796b9cbc767abc3d4e0c`

## 1. A1 gate creation

A dedicated target gate was created before A1 runtime implementation:

- workflow: `.github/workflows/stage33-a1-acceptance.yml`
- commit: `247d3958900df2042736e65437bfb9a4992acc1d`

The gate proves:
- frozen Stage 3.3 lineage and A1 surface;
- accepted Stage 3.2 migration bytes unchanged;
- A1 unit contracts;
- A1 PostgreSQL 18 contracts;
- complete Stage 3.2 regression on the Stage 3.3 head.

The trigger is the durable marker:
- `rc/RUN_STAGE33_A1_ACCEPTANCE`

## 2. Connector-safe write recovery

An attempted low-level Git tree/commit/ref composition returned `INVALID_ARGUMENT`.

Verified Execution Protocol response:

~~~text
write response uncertain/error
        ↓
read main HEAD
        ↓
read intended target files
        ↓
main unchanged + targets absent
        ↓
remote durable effect proven ABSENT
        ↓
safe retry with smaller durable writes
~~~

No blind replay occurred.

The implementation was then split into independently verifiable GitHub content operations,
each followed by HEAD/file read-back.

## 3. Domain and application foundation

Verified commits:

- governance enums:
  `baa97bea0074c7b799edf75cd9374cfbfeccb161`
- PrincipalContext / bounded policy schema:
  `028c607c35945fb0348cb17687b44435d9431db5`
- AgentVersion governance pin + Run requester snapshot domain fields:
  `eebe6117d3f0b40e4e90464985206d8252d19246`
- PrincipalResolver / GovernancePolicyStore ports:
  `f116c2d8d0050c926a80c38c893500c2aa3b3a3b`
- LegacyDevelopmentPrincipalResolver trust fence:
  `f0dab39fa0d06557923044a1f51ad00a84a87217`

Verified boundary:
- legacy resolver is explicitly non-authoritative for GOVERNED mode;
- A1 defines policy facts but does not create PolicyDecision or alter Tool execution behavior.

## 4. Persistence and migration foundation

Verified commits:

- ORM governance persistence:
  `24faa79a0ee79b89d8dc37ab4f6a26b7026ee4d9`
- forward-only migration `0017_governance_identity_policy`:
  `4a0a9095154a8c1c4701ca42d66b59360a6ba564`
- DB/domain mappers:
  `42c83dde783f5834faa811569081565e73783b27`
- PostgreSQL policy lifecycle store:
  `bc05265742e9c4eb8c06eee86e8c09021b36315a`
- governed Run exact policy/requester snapshot wiring:
  `d642c446c264ba05dbb1d6323299f82efe51e4a1`

Migration contract:
- `0017_governance_identity_policy`
- down revision: `0016_checkpoint_overlay`
- accepted migrations `0001` through `0016` were not rewritten.

Database enforcement includes:
- existing AgentVersion -> `LEGACY_STAGE32` + NULL policy;
- GOVERNED AgentVersion requires a PUBLISHED policy version;
- governance_mode and policy_version_id are immutable after AgentVersion persistence;
- published policy rule content is immutable;
- retired policy cannot be newly assigned.

## 5. Target tests

Verified commits:

- A1 unit contracts:
  `098534c912a6b23c246107432e0f50b1a3b113f7`
- A1 PostgreSQL contracts:
  `7fcf67f16f649de05810fd1a5010928e5c4a998d`

The initial implementation candidate was:

`7fcf67f16f649de05810fd1a5010928e5c4a998d`

## 6. Candidate #1 — rejected

Trigger:
- commit: `cb14e9ff776a4f396c2e1a1d82ec995865bcfd32`
- workflow run: `37267459937`

Results:
- frozen lineage/surface: PASS;
- Stage 3.2 migration byte immutability: PASS;
- A1 unit: PASS;
- A1 PostgreSQL 18: PASS;
- full Stage 3.2 regression: FAIL at quality gate.

Root cause:
- Ruff reported two import-order findings and three E501 findings.

No runtime semantic failure was found.

Candidate #1 remained rejected and was not re-run.

## 7. Formatting repair #1

Formatting-only commits:

- application governance imports:
  `1a36dff6c54af13d6e28a255e7869b1424f46d38`
- domain model import order:
  `b891bb7428d4e1924b836624a89561c25900a038`
- governance validation wrapping:
  `ddffbd8163a7600b4ea1680b76c87a744464e09d`
- ORM constraint wrapping:
  `b85a782c40fa855b5f2c742e9e16ce5848f3e4a2`

Candidate #2:
`b85a782c40fa855b5f2c742e9e16ce5848f3e4a2`

## 8. Candidate #2 — rejected

Trigger:
- commit: `e90d2bcfec508eda85ca33c1eeb5282b4efd8ce8`
- workflow run: `37267652894`

Results:
- A1 unit: PASS;
- A1 PostgreSQL 18: PASS;
- Ruff lint: PASS;
- Ruff format check: FAIL.

Root cause:
- formatter required only two files to be normalized:
  - `migrations/versions/0017_governance_identity_policy.py`
  - `tests/integration/test_stage33_a1_postgres.py`

No runtime semantic change was required.

## 9. Formatting repair #2

Formatting-only commits:

- migration formatting:
  `fa24a4d241e86ea83ca3c21a479c073d37afabdc`
- PostgreSQL contract formatting:
  `e6714d6f8037057e1a552c60e1c6635f37eeb3a5`

Candidate #3:
`e6714d6f8037057e1a552c60e1c6635f37eeb3a5`

## 10. Candidate #3 — rejected

Trigger:
- commit: `ed8a31d2209de099070088834556a24989ea5345`
- workflow run: `37267770281`

Results before integration regression:
- A1 unit: PASS;
- A1 PostgreSQL 18: PASS;
- Ruff lint: PASS;
- Ruff format: PASS — 73 files already formatted;
- mypy strict: PASS — 34 source files.

Full regression result:
- 58 failed;
- 112 passed.

All 58 failures shared one compatibility root cause:

~~~text
LEGACY Run
requester_roles = Python None
        ↓
plain JSONB bind
        ↓
JSON null
        ↓
not SQL NULL
        ↓
ck_runs_governance_snapshot_shape violated
~~~

The log contained one `requester_roles: Jsonb(None)` occurrence for each of the 58 failed
legacy integration paths.

This was a persistence-null-semantics bug, not a governance design or Stage 3.2 execution
semantic failure.

## 11. Legacy SQL-NULL compatibility repair

Fix:
- `requester_roles` uses `JSONB(none_as_null=True)`
- commit:
  `0752c806cfca8f32ebcfe248d4606cfe6c44bf4e`

Regression lock:
- added a dedicated legacy Run test that asserts both:
  - domain value is `None`;
  - PostgreSQL `requester_roles IS NULL` is true.
- commit:
  `cf1c7571b67210bedfe411865bb940c83e6da4f0`

Candidate #4:
`cf1c7571b67210bedfe411865bb940c83e6da4f0`

## 12. Candidate #4 — accepted

Trigger:
- commit: `cfeaef8f868e976982e7ed1986101c2743bf15ab`
- workflow run: `37268108885`

Final workflow conclusion:
**SUCCESS**

Verified steps:
- frozen Stage 3.3 lineage and A1 surface: PASS;
- accepted Stage 3.2 migration bytes unchanged: PASS;
- Stage 3.3-A1 unit contracts: PASS;
- Stage 3.3-A1 PostgreSQL 18 contracts: PASS;
- complete Stage 3.2 regression on Stage 3.3 head: PASS.

## 13. Accepted semantic head

A1 accepted implementation candidate:

`cf1c7571b67210bedfe411865bb940c83e6da4f0`

Acceptance trigger head:

`cfeaef8f868e976982e7ed1986101c2743bf15ab`

The trigger commit changes only the acceptance marker; A1 runtime semantics belong to the
candidate SHA above.

## 14. Frozen A1 invariants

Stage 3.3-A1 now freezes:

- explicit `LEGACY_STAGE32` / `GOVERNED` AgentVersion governance mode;
- normalized bounded PrincipalContext;
- explicit legacy-development principal resolver isolation;
- durable bounded GovernancePolicyVersion schema/lifecycle;
- DRAFT cannot authorize assignment;
- PUBLISHED rule content immutable;
- RETIRED cannot be assigned to new AgentVersion;
- immutable AgentVersion policy assignment;
- exact policy pin copied onto GOVERNED Run;
- exact normalized requester snapshot copied onto GOVERNED Run;
- legacy Run governance snapshot remains SQL NULL;
- accepted Stage 3.2 migration lineage remains byte-identical;
- no A2 evaluator / GovernanceIntent / PolicyDecision behavior implemented early.

## 15. Gate conclusion

~~~text
Stage 3.3-A1
✅ IMPLEMENTED
✅ INDEPENDENTLY ACCEPTED
✅ FROZEN

Stage 3.3-A2
🔓 UNLOCKED

Stage 3.3-A Aggregate
🔒 LOCKED

Stage 3.3-B+
🔒 LOCKED
~~~

Governing rule:

> Identity and policy facts are now durable and deterministic; they still do not authorize
> Tool execution until the later frozen slices explicitly bridge that consequence.
