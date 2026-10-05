# Stage 3.3-A2 — Engineering Execution Record

Status: **IMPLEMENTATION + ACCEPTANCE COMPLETE / VERIFIED**

Parent contracts:
- `docs/design/stage3.3-governance-v1.0-frozen.md`
- `docs/acceptance/stage3.3-governance-acceptance-v1.0-frozen.md`
- `docs/implementation/stage3.3-a1-accepted.md`
- `docs/implementation/stage3.3-slices-frozen.md`
- `docs/execution/verified-execution-protocol-v1.0.md`

Frozen baselines:
- Stage 3.2 Runtime V1.0 RC2:
  `fa747268cfbf1d5b57e5796b9cbc767abc3d4e0c`
- Stage 3.3-A1 accepted semantic candidate:
  `cf1c7571b67210bedfe411865bb940c83e6da4f0`
- A1 successful gate:
  `37268108885`

## 1. A2 target gate

A dedicated A2 gate was created before implementation:

- workflow: `.github/workflows/stage33-a2-acceptance.yml`
- commit: `1e5ff7954e0253ae690e4664afe47cb185fd26f8`
- trigger: `rc/RUN_STAGE33_A2_ACCEPTANCE`

The gate independently proves:
- frozen Stage 3.3/A1 lineage;
- accepted Stage 3.2 migrations unchanged;
- frozen A1 migration `0017` unchanged;
- A1 + A2 unit contracts;
- A1 + A2 PostgreSQL 18 contracts;
- complete Stage 3.2 regression.

## 2. Deterministic evaluator and GovernanceIntent

Domain implementation:
- initial evaluator/intent commit:
  `11c05e51b83a165d16eeb9a87be010510c48f151`
- exact retired-pinned-policy correction:
  `59c62db1d08f62c472f80b872efa5f819808a321`

Implemented domain facts:
- `GovernanceIntentV1`;
- `PolicyEvaluation`;
- `PolicyDecision`;
- deterministic rule matching;
- frozen selection order:
  priority descending -> DENY > REQUIRE_APPROVAL > ALLOW -> rule_id ascending;
- no-match -> DENY;
- malformed policy -> fail closed;
- capability envelope;
- DESTRUCTIVE never effective-ALLOW;
- exact RETIRED policy remains evaluable for already-pinned Runs.

GovernanceIntent V1 reuses the accepted Stage 3.2 `canonical_json_v1()` implementation rather
than introducing a second canonicalization engine.

It binds:
- Run;
- AgentVersion;
- proposal;
- ToolVersion;
- effect type;
- exact canonical arguments;
- normalized requester;
- normalized principal scope.

Credential references are not included.

## 3. Durable audit schema

Audit event enum:
- commit: `851ac49d112d05e0e43609209ef7186deb45752a`

Persistence models:
- initial commit: `7714c0a02190b81717a320955eec6e9714065440`
- formatter-only follow-up: `95b4cf9952139ab738309abdf53343070e6b86da`

Migration:
- `0018_governance_decision`
- commit: `22c0054e8a216b080c3f246ab2619fb58bb1e06f`
- down revision: `0017_governance_identity_policy`

Durable tables:
- `governance_intents`;
- `policy_decisions`.

Database invariants:
- one GovernanceIntent per proposal;
- one PolicyDecision per proposal;
- one PolicyDecision per GovernanceIntent;
- 64-character SHA-256 digest shape;
- GovernanceIntent / PolicyDecision UPDATE or DELETE rejected by DB trigger.

## 4. Decision store

Application port:
- commit: `c15bc18d1b5e116d42bdcd4925749b1ffa013c3b`

Conflict type:
- `GovernanceDecisionConflictError`
- commit: `8cee65a2b27ffae692214a76ee1e048636e2e1dc`

PostgreSQL implementation:
- initial commit: `123a367810c6ec23a06625b48fcdee37cf3f3f0b`
- Ruff-line-format commit:
  `545d1eb6b19e27f6b3266d08eec1f10a17e32959`
- formatter-only commit:
  `c92032c6bd822bc7e390a2fa2e10f20846ed4c35`

The store does not trust a caller-supplied effective decision.

Before persistence it:
1. locks the durable Run;
2. verifies exact pinned policy;
3. verifies AgentVersion and requester snapshot;
4. verifies proposal belongs to the Run;
5. verifies immutable ToolVersion binding;
6. reconstructs GovernanceIntent from durable facts and compares canonical bytes/digest;
7. reloads the exact policy and re-evaluates it;
8. persists only an identical evaluation.

Exact replay returns the existing decision.
Different replay raises a governance decision conflict.

The transaction writes:
- GovernanceIntent;
- PolicyDecision;
- one `POLICY_DECIDED` audit event.

It writes no ToolCall and no ToolExecutionAttempt.

## 5. Target contracts

Evaluator tests:
- commit: `fbaede4541d8ab1e3c1bd0f380ba6168c6a33911`
- helper formatting follow-up:
  `9d40b0179897a346ce5ff9aabf06d8e49510dc70`

GovernanceIntent golden vectors:
- commit: `22719b02eb3e6e0ae14358dde1c762b7375cd570`
- frozen golden SHA-256:
  `2596669fe9fbae6271d42c0f9ccec05733d3d9a5577c9102dd3b31552d5bda4a`

The golden tests cover:
- nested object ordering;
- Unicode;
- normalized role order;
- safe integer restrictions;
- float rejection;
- credential sentinel exclusion.

PostgreSQL contracts:
- initial commit: `2b3d0f74f41cc8fa23e12c5dd3a6448c61a38bab`
- fixture-order repair:
  `c735a53772cb162ac92eac4b405f5636daa1d75d`
- final formatter commit:
  `9b8a9bd45dd8f76f93a06d1ece4a2846e7043af9`

PostgreSQL proves:
- real `0017 -> 0018` migration;
- exact durable identity;
- immutable PolicyDecision;
- immutable GovernanceIntent;
- exact replay;
- conflicting replay rejection;
- one POLICY_DECIDED event;
- malformed durable policy -> DENY;
- ToolCall count remains zero;
- ToolExecutionAttempt count remains zero.

## 6. Candidate #1 — rejected

Candidate:
`2b3d0f74f41cc8fa23e12c5dd3a6448c61a38bab`

Trigger:
`6d991c91653f3ba4ede59b6934f7822de92d6fa9`

Run:
`37274722249`

Results:
- migration lineage: PASS;
- A1 + A2 unit: PASS;
- PostgreSQL: 2 failed / 5 passed.

Root cause:
- test fixture dependency ordering only;
- AgentVersionTool rows were flushed before the corresponding ToolVersion rows;
- PostgreSQL correctly rejected the foreign-key violation.

No runtime semantic change was required.

Repair:
- explicit fixture flush before binding rows;
- commit: `c735a53772cb162ac92eac4b405f5636daa1d75d`.

## 7. Candidate #2 — rejected

Candidate:
`c735a53772cb162ac92eac4b405f5636daa1d75d`

Trigger:
`77a101e37b920a1f05ccdffd703c0c6e86f8e9d1`

Run:
`37274891436`

Results:
- unit: PASS;
- PostgreSQL: PASS;
- full regression stopped at Ruff.

Root cause:
- three E501 line-length findings only.

Formatting-only repair:
- decision-store wrapping:
  `545d1eb6b19e27f6b3266d08eec1f10a17e32959`;
- evaluator-test helper wrapping:
  `9d40b0179897a346ce5ff9aabf06d8e49510dc70`.

## 8. Candidate #3 — rejected

Candidate:
`9d40b0179897a346ce5ff9aabf06d8e49510dc70`

Trigger:
`9128f9cf8f8a244b3a263777e2edd527234c9935`

Run:
`37275054761`

Results:
- unit: PASS;
- PostgreSQL: PASS — 7 passed;
- Ruff lint: PASS;
- Ruff format: FAIL.

Root cause:
- four files required formatter normalization only.

Formatter-only repairs:
- domain evaluator:
  `3ac14e16d35c03054928b3d4a5aa6d551eff9783`;
- decision store:
  `c92032c6bd822bc7e390a2fa2e10f20846ed4c35`;
- ORM models:
  `95b4cf9952139ab738309abdf53343070e6b86da`;
- PostgreSQL tests:
  `9b8a9bd45dd8f76f93a06d1ece4a2846e7043af9`.

## 9. Candidate #4 — accepted

Accepted semantic candidate:

`9b8a9bd45dd8f76f93a06d1ece4a2846e7043af9`

Trigger:

`bbb02c4195672b53baa3a1c7754e88ab543ed091`

Successful workflow run:

`37275301253`

Final workflow conclusion:
**SUCCESS**

Verified steps:
- frozen Stage 3.3 lineage and A2 surface: PASS;
- frozen Stage 3.2 + A1 migration lineage: PASS;
- Stage 3.3-A1 + A2 unit contracts: PASS;
- Stage 3.3-A1 + A2 PostgreSQL 18 contracts: PASS;
- complete Stage 3.2 regression on A2 head: PASS.

## 10. Frozen A2 invariants

Stage 3.3-A2 now freezes:
- deterministic rule selection;
- wildcard empty match dimensions;
- no match -> DENY;
- malformed policy -> fail closed;
- exact retired pinned policy remains usable by existing Runs;
- policy cannot broaden Tool capability;
- DESTRUCTIVE cannot effective-ALLOW;
- GovernanceIntent V1 canonical identity;
- secret/credential sentinel exclusion;
- immutable one-per-proposal PolicyDecision;
- exact policy/requester/tool/run binding;
- audit event for durable PolicyDecision;
- evaluation creates zero ToolCall;
- evaluation creates zero ToolExecutionAttempt;
- no adapter I/O is introduced by A2.

## 11. Explicit non-goals / lock boundary

A2 does not yet:
- make ALLOW create/execute a ToolCall;
- make DENY fail a Run;
- add WAITING_APPROVAL;
- add ApprovalRequest / ApprovalDecision;
- permit DESTRUCTIVE physical execution;
- modify Stage 3.2 ToolCoordinator execution authority.

Those consequences remain locked for later frozen slices.

## 12. Gate conclusion

~~~text
Stage 3.3-A1
✅ ACCEPTED / FROZEN

Stage 3.3-A2
✅ IMPLEMENTED
✅ INDEPENDENTLY ACCEPTED
✅ FROZEN

Stage 3.3-A Aggregate
🔓 UNLOCKED

Stage 3.3-B
🔒 LOCKED
~~~

Governing rule:

> A durable deterministic PolicyDecision is audit evidence; it is not yet physical execution
> authority.
