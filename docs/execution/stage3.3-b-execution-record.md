# Stage 3.3-B — Engineering Execution Record

Status: **IMPLEMENTATION + ACCEPTANCE COMPLETE / VERIFIED**

Parent contracts:
- `docs/design/stage3.3-governance-v1.0-frozen.md`
- `docs/acceptance/stage3.3-governance-acceptance-v1.0-frozen.md`
- `docs/implementation/stage3.3-a-accepted.md`
- `docs/implementation/stage3.3-slices-frozen.md`
- `docs/execution/verified-execution-protocol-v1.0.md`

Frozen baselines:
- Stage 3.2 Runtime V1.0 RC2:
  `fa747268cfbf1d5b57e5796b9cbc767abc3d4e0c`
- Stage 3.3-A accepted semantic surface:
  `9b8a9bd45dd8f76f93a06d1ece4a2846e7043af9`
- Stage 3.3-A aggregate gate:
  `37281068420`

## 1. B target gate

Dedicated workflow:
- `.github/workflows/stage33-b-acceptance.yml`
- workflow commit:
  `dd71a7dce23a0a2e105d1653f25c461e23ab7ae3`
- trigger:
  `rc/RUN_STAGE33_B_ACCEPTANCE`

The gate independently proves:
- frozen Stage 3.3 lineage and B surface;
- accepted Stage 3.2 + A1 + A2 migration lineage unchanged;
- Stage 3.3-B unit contracts;
- Stage 3.3-B PostgreSQL 18 contracts;
- B does not implement approval waiting early;
- complete Stage 3.2 regression.

## 2. B1 — Control-plane authorization

Core authorization:
- `14339a5a226619a51b63ceefaf89e1e86dc7a961`

API integration:
- `99c86c35a0f6adf81a8155321b94c000cdccfa3e`
- typing cleanup:
  `7dc0ac652e422d8ea9fc89f2523521b610af19a5`

Targeted contracts:
- `b9c1513ec9cca58b0ae0f6a37e6a8d9f89e537b4`

Frozen behavior:
- governed create requires `runtime:run:create`;
- governed identity comes from a trusted PrincipalResolver;
- request body/header data is not governed authority;
- same-scope requester may read/cancel its own Run;
- same-scope privileged read/cancel requires explicit roles;
- action resolution requires same-scope `runtime:resolve_action`;
- resolver identity is forced from trusted PrincipalContext;
- cross-scope single-resource access is hidden as 404;
- same-scope visible-but-unauthorized access is 403;
- legacy `create_app(store)` compatibility remains isolated.

## 3. B2.1 — Pure governed consequence planning

Initial planner:
- `fa6e08b60797fa2b40bfe7840834a64c35567634`

Style correction:
- `636f5f975625b901b570fc66080f651ff853c323`

Planner contracts:
- `be7899041776ac8df9392e74e0204d6adcbc3aeb`

The planner:
- binds exact Run / AgentVersion / pinned policy / proposal / ToolVersion / requester facts;
- computes deterministic A2 evaluation without DB or adapter I/O;
- prepares READ ALLOW through existing Stage 3.2 ToolCoordinator;
- prepares no-approval WRITE / EXTERNAL_SIDE_EFFECT only through existing Stage 3.2 eligibility;
- creates exact ToolVersion-bound DENY candidates;
- leaves REQUIRE_APPROVAL non-executable for Stage 3.3-C.

## 4. B2.2 — Atomic PostgreSQL consequence persistence

ExecutionRecorder governed contract:
- `1ca5c2183c28ead8fb0256d4c828106cacc8ab0d`

Durable governance revalidation helper:
- `1c9414ca55ac7548952e704642254681fc34c05d`

Atomic governed READ / side-effect / DENY transactions:
- `ff2995dc577cdd2578c7659ea1159fa80a9c8315`

PostgreSQL consequence contracts:
- `19e5692fc28e65aef06d645a704a47661f79a06d`
- test import correction:
  `08cee605c49e70766e6e6dc92e73556f44acc76b`

Frozen transaction rule:

~~~text
lock owned Run
-> generation + live lease
-> cancellation
-> DB deadline
-> exact AgentVersion / immutable Tool binding
-> exact pinned policy
-> durable requester snapshot
-> reconstruct GovernanceIntent
-> re-evaluate policy
-> persist GovernanceIntent + PolicyDecision
-> persist business consequence
-> commit
~~~

READ ALLOW creates a STARTED ToolExecutionAttempt before adapter I/O.

No-approval side-effect ALLOW creates durable ActionSnapshot + ExternalAction READY with zero
physical attempt; the existing Stage 3.2 Action Commit remains the later physical boundary.

DENY creates:
- PolicyDecision DENY;
- exact ToolVersion-bound ToolCall DENIED;
- FAILED Run;
- zero ExternalAction;
- zero ToolExecutionAttempt;
- zero adapter I/O.

If cancellation/deadline/generation authority wins before consequence commit, governance and
business consequence rows are not partially persisted.

## 5. B2.3 — RunManager / Worker integration

RunManager bridge:
- `0ec1dac8fbdb83e1f2436222421a397269b854cb`

Worker exact pinned-policy loading:
- `c99d5b2ac4f74517b07524a91f3ef47be8e6d185`

Targeted wiring contracts:
- `5846ec0083f590941be0095981703109a505e806`

Worker PostgreSQL end-to-end contracts:
- `8535d1b39547bb660f2162cae1ad6acc792347c4`

Compatibility rule:
- LEGACY_STAGE32 does not require GovernancePolicyStore and keeps the accepted Stage 3.2 path;
- GOVERNED requires the exact pinned policy before RunManager execution.

REQUIRE_APPROVAL remains explicitly outside B:
- no WAITING_APPROVAL;
- no ApprovalRequest;
- no ApprovalDecision;
- no physical execution;
- Stage 3.3-C owns the durable pending-approval consequence.

## 6. Candidate #1 — rejected

Candidate:
`8535d1b39547bb660f2162cae1ad6acc792347c4`

Trigger:
`1aff2570ce3e681b9351968358956baee0401cb4`

Run:
`37285889157`

Results:
- lineage: PASS;
- B unit: PASS;
- PostgreSQL: 12 passed / 1 failed.

Root cause:
- test-only ORM assertion used `invocation.status.value` even though ModelInvocationRow.status is
  already a string.

No runtime semantic change was required.

Repair:
- `f6ca2b9c468c227e59d4fd5955263b3e1e36b724`

## 7. Candidate #2 — rejected

Candidate:
`f6ca2b9c468c227e59d4fd5955263b3e1e36b724`

Trigger:
`114842895da9db456d066946221325a59d7c44db`

Run:
`37291417246`

Results:
- B unit: PASS;
- B PostgreSQL: PASS;
- no-early-approval guard: PASS;
- full regression stopped at Ruff import ordering.

Root cause:
- import-order only.

Repair:
- `a8505ce459537ed40c7cc78cbbc3f67c0930c925`

## 8. Candidate #3 — rejected

Candidate:
`a8505ce459537ed40c7cc78cbbc3f67c0930c925`

Trigger:
`b87f62a67c1e5142b27f83cf1915007b2bfca020`

Run:
`37295408478`

Results:
- B unit/PostgreSQL/no-early-approval: PASS;
- Ruff lint: PASS;
- Ruff format: FAIL.

Formatter-only repairs:
- RunManager:
  `34f8f2e7cda6b507756c8a5da4cc2bbd838019b8`
- Worker:
  `f5338affd3683388aa34251256fcfebc8fb1e730`
- recorder:
  `19521b64653bcd896e3305f2fe711cd398405fff`
- PostgreSQL test:
  `f1fd828c637333da109676264867c0de8a0e71ef`

## 9. Candidate #4 — rejected

Candidate:
`f1fd828c637333da109676264867c0de8a0e71ef`

Trigger:
`9e0ff873c1b7bfe368ef41155f542e13ce2a4718`

Run:
`37297994779`

Results:
- B unit: PASS;
- B PostgreSQL: PASS — 13 passed;
- no-early-approval guard: PASS;
- Ruff lint: PASS;
- Ruff format: FAIL on three remaining test files.

Formatter-only repairs:
- PostgreSQL tests:
  `bd31bf59c80925dccb6ffc5735cf2eb01aa7dc2c`
- control-plane tests:
  `c77cd5915f0945993f4a1ac9e7840c9210aedb6d`
- governed consequence tests:
  `bdeef5adbda0408b7b17af9042ce1dd731ab3804`

## 10. Candidate #5 — accepted

Accepted semantic candidate:

`bdeef5adbda0408b7b17af9042ce1dd731ab3804`

Trigger:

`a28977d7b8a484faa73166e9f38ab74246246cd9`

Successful workflow run:

`37300886491`

Final workflow conclusion:
**SUCCESS**

Verified steps:
- frozen Stage 3.3 lineage and B surface: PASS;
- accepted Stage 3.2 + A1 + A2 migration lineage unchanged: PASS;
- Stage 3.3-B unit contracts: PASS;
- Stage 3.3-B PostgreSQL 18 contracts: PASS;
- B no-early-approval-state guard: PASS;
- complete Stage 3.2 regression: PASS.

## 11. Frozen B invariants

Stage 3.3-B now freezes:
- trusted governed control-plane authorization;
- cross-scope non-disclosure;
- exact pinned-policy Worker loading;
- deterministic governed ALLOW / DENY bridge;
- Stage 3.2 ModelInvocation consequence fencing;
- atomic governance audit + business consequence;
- READ STARTED-before-I/O;
- no-approval side-effect Action Commit preservation;
- DENY zero physical I/O;
- exact logical/physical budget accounting;
- cancellation/deadline/stale-generation consequence discard;
- LEGACY_STAGE32 compatibility;
- no WAITING_APPROVAL behavior;
- no DESTRUCTIVE execution;
- no weakening of Stage 3.2 side-effect executable predicate.

## 12. Gate conclusion

~~~text
Stage 3.3-A
✅ ACCEPTED / FROZEN

Stage 3.3-B
✅ IMPLEMENTED
✅ INDEPENDENTLY ACCEPTED
✅ FROZEN

Stage 3.3-C
🔓 UNLOCKED

Stage 3.3-D+
🔒 LOCKED
~~~

Governing rule:

> Stage 3.3-B may turn an exact durable policy decision into ALLOW or DENY runtime consequence
> only through the already-frozen Stage 3.2 physical execution boundaries. Approval waiting and
> approved execution remain separate later slices.
