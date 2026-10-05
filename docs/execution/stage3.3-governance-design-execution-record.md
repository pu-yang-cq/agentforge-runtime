# Stage 3.3 Governance Design — Engineering Execution Record

Status: **DESIGN PHASE COMPLETE / VERIFIED**

Process contract:
- docs/execution/verified-execution-protocol-v1.0.md

Parent:
- Stage 3.2 Runtime V1.0 immutable RC2
- rc/stage3.2-v1.0-r2
- fa747268cfbf1d5b57e5796b9cbc767abc3d4e0c
- gate 37262139363

## 1. Initial repository inspection

Before writing Stage 3.3 design, current main and Stage 3.2 frozen surfaces were read back.

Existing governance reservations confirmed:

- ToolBinding.approval_required;
- ToolBinding.allow_no_approval_execution;
- ToolCallStatus.DENIED;
- QueueReason.APPROVAL_RESOLVED;
- Stage 3.2 design reservation for WAITING_APPROVAL;
- frozen ActionSnapshot canonical digest;
- Stage 3.2 Action Commit Boundary.

Current runtime also proved that approval was not yet implemented:
- RunStatus had no WAITING_APPROVAL;
- approval-required side effects failed closed through PermissionError;
- no durable ApprovalRequest/ApprovalDecision existed.

## 2. Design V0.1

First create attempt failed before a GitHub write because the local orchestration script had a
JavaScript syntax error.

Verified Execution Protocol response:

~~~text
write attempt returns local syntax error
        ↓
classify remote state UNKNOWN until read-back
        ↓
read target path
        ↓
GitHub returns 404
        ↓
remote effect proven ABSENT
        ↓
safe retry
~~~

No blind duplicate write occurred.

Accepted retry:

- file: docs/design/stage3.3-governance-v0.1.md
- commit: 8dc3d6edf4b96368eea038ebe590d2bec0407929
- verified blob: 43e1dc787a0a999dddf85692a6e7193ab170a5c7

## 3. Acceptance V0.1

- file: docs/acceptance/stage3.3-governance-acceptance-v0.1.md
- commit: 6c8926d2e39e8bb10426228e66a86d090b4821c6
- verified blob: 9b90ad8808b0361b8de644a4c45a9bd568ad8042

This established the first mandatory governance test matrix.

## 4. V0.1 Self Review

- file: docs/reviews/stage3.3-governance-v0.1-self-review.md
- commit: 0ea6f02e77bb893fc420d5a08ba43884e1d98cc4
- verified blob: d55e42826f1c482b6d76c5eccd99a5e463eba02b

Result:

~~~text
Blockers:       11
Major:           8
Clarifications:  4
V0.1: NOT ACCEPTED
~~~

Critical finding:
- approved side-effect ToolCall READY with no ExternalAction could collide with existing
  Stage 3.2 READ recovery.

## 5. V0.1 Scenario Validation

- file: docs/validation/stage3.3-governance-v0.1-scenario-validation.md
- commit: 149e75f9e22c951eabef5bb07a507400c669c23e
- verified blob: 8b42f3ea554d46abea7fda5939d0d3d1dba47423

Result:

~~~text
PASS:    5
PARTIAL: 5
FAIL:    7
~~~

The READ/side-effect recovery collision was reproduced as a concrete state-machine failure.

## 6. V0.1 Adversarial Review

- file: docs/reviews/stage3.3-governance-v0.1-adversarial-review.md
- commit: 7235b9a69e8b226bb3d8682a79b6b2df8eb59986
- verified blob: 14119cbc7167f797e756d349edd03e43b6654b02

Major architecture decision:
- do not build a second side-effect approval digest/state engine;
- create Stage 3.2 ActionSnapshot + ExternalAction before waiting approval;
- add ExternalAction AWAITING_APPROVAL;
- bind human approval to exact frozen ActionSnapshot digest;
- keep Stage 3.2 Action Commit as physical-effect authority.

Scope was reduced away from a general IAM/policy language product.

## 7. Corrective Design V0.2

- file: docs/design/stage3.3-governance-v0.2.md
- commit: ea5362c6f0cab6584389f4d4e58e1456a91b04f5
- verified blob: c10f162985f881dbb96fccf0ff4f89dada8558c4

Important corrections:
- LEGACY_STAGE32 vs GOVERNED AgentVersion mode;
- durable requester snapshot;
- pinned policy version;
- deterministic rule ordering;
- ActionSnapshot/ExternalAction AWAITING_APPROVAL;
- approval expiry primitive;
- trusted PrincipalContext boundary;
- separate approved-destructive execution predicate;
- exact budget accounting.

## 8. Acceptance V0.2

- file: docs/acceptance/stage3.3-governance-acceptance-v0.2.md
- commit: 1119c54415279c821c70f923b221d741d6d3f3b5
- verified blob: 51da9b368935cafcd87c288030d2f1734ebf7543

## 9. Current API compatibility inspection

Before V0.2 re-review, current accepted Stage 3.2 API tests were inspected.

Confirmed:
- create_app(store) currently works without an injected PrincipalResolver;
- ActionResolution request currently accepts resolver_identity from the request body;
- the frozen unit API test asserts resolver_identity == "operator:test".

This evidence prevented a design that would have broken the mandatory Stage 3.2 regression.

## 10. V0.2 Re-Review

- file: docs/reviews/stage3.3-governance-v0.2-re-review.md
- commit: 3c431cddc726f0455027c464c9c607b6c129f8e7
- verified blob: 79f003de8da37d5d3a3f78280003637200add3f6

Result:

~~~text
Remaining blockers:       4
Remaining major:          6
Clarifications:           3
V0.2: NOT YET ACCEPTED
~~~

Remaining blockers:
1. governance lock order conflicted with Stage 3.2 child order;
2. trusted identity migration could break frozen legacy API;
3. expiry correctness depended too much on maintenance timing;
4. policy assignment mutability conflicted with immutable AgentVersion semantics.

## 11. Design V0.3 Freeze Candidate

- file: docs/design/stage3.3-governance-v0.3.md
- initial commit: c95d05f3b02973283decde0731bfc3d08ac2e914
- final clarification commit: 26d8b6e7ac4e5e7c9520f4b9deaeda46b38cf760
- verified final blob: c8db4b1cbab81d4a40c68838780dd0ea38fac322

V0.3 closed:
- one global Run -> ExternalAction -> ToolCall -> ApprovalRequest lock order;
- LegacyDevelopmentPrincipalResolver isolation;
- logical expiry independent of sweeper punctuality;
- immutable policy assignment as AgentVersion execution specification;
- normalized principal/roles;
- governed read authorization;
- terminal guards;
- exact ApprovalDecision replay semantics.

Final clarification fixed the cross-scope non-disclosure contract:
- hidden single resource -> 404;
- collection/list filters invisible entries;
- visible same-scope mutation without role -> 403.

## 12. Acceptance V0.3

- file: docs/acceptance/stage3.3-governance-acceptance-v0.3.md
- initial commit: e6c765ae073e1a83c3f7870f717ec7235e905599
- non-disclosure clarification commit: a89652af0a4f074cfdbc4920cc1e41acc93ea786
- verified final blob: fab1a413996244d7b53193177f6421d2ec509347

## 13. Final Review

- file: docs/reviews/stage3.3-governance-v0.3-final-review.md
- commit: 72dda46fc558543c3fead2eba79db54d07b71d0f
- verified blob: 4ad1aa52f1b093346da615c2d714ce3c58a1f21f

Result:

~~~text
Unresolved V0.1 blockers:                  0
Unresolved V0.2 blockers:                  0
New correctness blockers:                 0
Unresolved major findings:                0
Scope expansion beyond reviewed boundary: 0
Final Review: PASSED
~~~

## 14. V1.0 Design Freeze

- file: docs/design/stage3.3-governance-v1.0-frozen.md
- commit: 9909bfcc9fea2cdfdf4b8d6a5fd19efbea3a3d29
- verified blob: 85a0c462676415f0a7a7977bea027b152e8203af

## 15. V1.0 Acceptance Freeze

Initial frozen artifact:
- commit: 029f76ecc32fdac7c3803c2c584019e7687f56aa

Frozen-design provenance correction:
- commit: cc5f738267e1cb33092003106c78bcfbf0bd0a8d

Final:
- file: docs/acceptance/stage3.3-governance-acceptance-v1.0-frozen.md
- verified blob: eb42fa46b120ba7b17eec3b380650f127714c298

The provenance correction changed only the dependency path from V0.3 design to the
authoritative V1.0 frozen design.

## 16. Design Acceptance

- file: docs/acceptance/stage3.3-governance-design-v1.0-accepted.md
- commit: 2cd53961cb2d0385b9438fe1c181220bf21fd847
- verified blob: e77620fbf870b01f54e04a9c9341dfe87922f69c

Frozen design ref:

~~~text
stage3.3-governance-design-v1.0-frozen
 -> 2cd53961cb2d0385b9438fe1c181220bf21fd847
~~~

The ref was read back after creation and matched exactly.

## 17. README release-gate update

- commit: 1f5f807bc50782a48f2db9274c3ac388ca8ce433
- verified blob: c2af9f1500d2ac6c57d33cf16eaf9b3c3ce5c99a

README now states:
- Stage 3.2 Runtime V1.0 accepted/frozen;
- Stage 3.3 Governance Design V1.0 accepted/frozen;
- Stage 3.3 implementation unlocked;
- Stage 3.3 runtime acceptance remains locked.

## 18. Design-phase conclusion

~~~text
Stage 3.3 Governance Design V1.0
✅ REVIEWED
✅ ACCEPTED
✅ FROZEN

Frozen design ref
✅ VERIFIED

Stage 3.3 Implementation
🔓 UNLOCKED

Stage 3.3 Runtime Acceptance
🔒 LOCKED
~~~

No Stage 3.3 runtime code was implemented during this design phase.

Governing process rule:

> Design acceptance was earned by closing concrete state, identity, concurrency, security and
> compatibility failures before implementation began.
