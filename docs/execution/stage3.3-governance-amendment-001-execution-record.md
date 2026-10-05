# Stage 3.3 Governance Amendment 001 — Engineering Execution Record

Status: **IMPLEMENTATION + INDEPENDENT ACCEPTANCE COMPLETE / VERIFIED**

Amendment:
- `docs/design/stage3.3-governance-amendment-001-approval-metadata.md`
- `docs/acceptance/stage3.3-governance-amendment-001-approval-metadata.md`

Parent authorities:
- `docs/design/stage3.3-governance-v1.0-frozen.md`
- `docs/acceptance/stage3.3-governance-acceptance-v1.0-frozen.md`
- `docs/implementation/stage3.3-a2-accepted.md`
- `docs/implementation/stage3.3-b-accepted.md`
- `docs/execution/verified-execution-protocol-v1.0.md`

Pre-amendment implementation baseline:

`46b97f7e7d73cf8239a00014ef7d51ded9fecc2d`

## 1. Problem discovered during Stage 3.3-C2

The frozen capability envelope can tighten raw ALLOW into effective REQUIRE_APPROVAL for:
- approval-required READ;
- WRITE / EXTERNAL_SIDE_EFFECT without no-approval capability;
- every non-DENY DESTRUCTIVE proposal.

The original frozen rule schema required approval metadata only on raw REQUIRE_APPROVAL.
That left capability-derived REQUIRE_APPROVAL without:
- required approver role;
- separation-of-duties flag;
- approval TTL.

Runtime defaults were rejected because runtime must not invent approval authority.

## 2. Accepted amendment semantics

GovernancePolicyRule approval metadata is:
- mandatory for REQUIRE_APPROVAL;
- optional fallback metadata for ALLOW;
- forbidden for DENY.

The fallback metadata has no effect while raw ALLOW remains effective ALLOW.

If the capability envelope tightens ALLOW to REQUIRE_APPROVAL:
- exact metadata from the selected immutable ALLOW rule is used;
- if metadata is missing, evaluation fails closed to effective DENY.

No default role, TTL, approver or separation-of-duties value is synthesized.

## 3. Implementation

Rule-schema implementation:
- `4b50cc0e5a43b58e1f3a7af44c603122db94369d`

Evaluator fail-closed implementation:
- `d5673cae6442314a22dc440f9d90f4d75533a117`

A1 schema contracts:
- `d7b319254f0bfde7a127448cfd3cffa0245d702b`

A2 capability-envelope contracts:
- `868d09dc1b03ddf964ebb04cd206c257f9f1bf26`

C planner contracts:
- `74031b8f3af2dc7c21bee672bd370b94d6e4cda9`

Formatter-only repairs required by the complete regression:
- `1a7770e11fca8ae1775d296833e6f6d601971905`
- `48714fac843f340b018ed6471eea5d4da947b90a`
- `731136d015c87160a8deabe476cacd462ebf4f7d`
- `606523f655f11d98c9081a1b66123e21a8fd0b9f`
- `63a49a114445521020620d61cd8720f2a6b1e677`
- `6ccd9d2503ee19c7c36c33ed3aa10a65b7a00fae`
- `29b1a8c70fa7d00ccbaff01a753bca7a8c78afda`
- `b15c19017d5e0ea7970e27cd873f8b5c0af48bcc`

## 4. Dedicated acceptance gate

Workflow:
- `.github/workflows/stage33-amendment001-acceptance.yml`

Final gate candidate:
- `8d7b214c9ce38e201da364af59dcc35a90565205`

Final trigger:
- `04452c3e0ded87852bb4c03b2096a08eb4603f7b`

Successful GitHub Actions run:
- `37325262562`

The gate proved:
- original frozen V1.0 design/acceptance artifacts unchanged;
- accepted A2/B freeze artifacts unchanged;
- Stage 3.3 migrations before 0019 unchanged;
- 0019 formatter repair AST-equivalent to the pre-amendment baseline;
- amendment A1/A2/B/C unit contracts pass;
- A1/A2/B/C PostgreSQL regression passes;
- no Stage 3.3-D approval-decision/resume behavior introduced;
- complete Stage 3.2 regression passes.

## 5. Rejected candidate history

### Attempt #1
Run:
- `37322613462`

Rejected because:
- gate script referenced removed `$stage32` variable.

No semantic test executed.

### Attempt #2
Run:
- `37323322736`

Passed:
- surface;
- unit;
- PostgreSQL;
- no-D guard.

Rejected only by three Ruff E501 findings in the full regression.

### Attempt #3
Run:
- `37323976654`

Passed:
- surface;
- unit;
- PostgreSQL;
- no-D guard.

Rejected only because five files required Ruff formatter normalization.

### Attempt #4
Run:
- `37324593726`

Rejected because `git diff --ignore-all-space` cannot prove semantic equality between
multi-line and formatter-collapsed Python expressions.

The migration change remained formatter-only.

### Attempt #5 — accepted
Run:
- `37325262562`

All acceptance steps:
- PASS.

## 6. Final acceptance

Accepted semantic candidate:

`8d7b214c9ce38e201da364af59dcc35a90565205`

Acceptance trigger:

`04452c3e0ded87852bb4c03b2096a08eb4603f7b`

Acceptance Run:

`37325262562`

Conclusion:

**SUCCESS**

## 7. Governing frozen rule

> Runtime may never invent approval authority. Every effective REQUIRE_APPROVAL must carry
> complete approval metadata from the exact deterministically selected immutable policy rule;
> otherwise the proposal fails closed as DENY.
