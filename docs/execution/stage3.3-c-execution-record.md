# Stage 3.3-C — Engineering Execution Record

Status: **IMPLEMENTATION + ACCEPTANCE COMPLETE / VERIFIED**

Parent contracts:
- `docs/design/stage3.3-governance-v1.0-frozen.md`
- `docs/acceptance/stage3.3-governance-acceptance-v1.0-frozen.md`
- `docs/design/stage3.3-governance-amendment-001-approval-metadata.md`
- `docs/acceptance/stage3.3-governance-amendment-001-approval-metadata.md`
- `docs/implementation/stage3.3-governance-amendment-001-accepted.md`
- `docs/implementation/stage3.3-b-accepted.md`
- `docs/implementation/stage3.3-slices-frozen.md`
- `docs/execution/verified-execution-protocol-v1.0.md`

Frozen upstream evidence:
- Stage 3.2 Runtime V1.0 RC2:
  `fa747268cfbf1d5b57e5796b9cbc767abc3d4e0c`
- Stage 3.3-B accepted semantic candidate:
  `bdeef5adbda0408b7b17af9042ce1dd731ab3804`
- Governance Amendment 001 accepted semantic candidate:
  `8d7b214c9ce38e201da364af59dcc35a90565205`
- Governance Amendment 001 successful gate:
  `37325262562`

## 1. C target gate

Dedicated workflow:
- `.github/workflows/stage33-c-acceptance.yml`

Trigger:
- `rc/RUN_STAGE33_C_ACCEPTANCE`

Final accepted semantic candidate:
- `400336d6086c550039626f6717b6401410cc8e3b`

Final acceptance trigger:
- `165cce2b98a3143bef52b73226e240ce2fe25db2`

Successful GitHub Actions run:
- `37329756162`

The gate independently proves:
- frozen Stage 3.3 lineage and C surface;
- accepted Stage 3.2 + A1 + A2 migration lineage unchanged;
- frozen Governance Amendment 001 is present and bound;
- Stage 3.3-C unit contracts;
- Stage 3.3-C PostgreSQL contracts;
- C stops before human decision/resume/expiry materialization;
- complete Stage 3.2 regression.

## 2. C1 — Domain / schema / migration

Key commits:
- statuses:
  `8582472951940e3062ef4180a2426b387b366ae9`
- ApprovalRequest domain:
  `10f97d4a0c155d8286c8036c634f53ce219fad1c`
- Run / ToolCall transitions:
  `e0f9460ae93c6567936bac2003b053df8f8ce99b`
- ExternalAction awaiting constructor:
  `587149854b7319b0f429f1515e14cb198fcbf3e6`
- ApprovalRequest ORM:
  `aff05329896f1de565215f79509b45842c1b40c9`
- migration 0019:
  `4bcf86b9e8ba7f0ccedc7ba42dfd23ac0025d064`
- C unit contract:
  `17772287207026cda24ef082cc73adf6f8360621`
- migration contract:
  `d1d69330472a8d868aa4d01ed10c3d2c3eea8d8e`

C1 established:
- Run WAITING_APPROVAL;
- ToolCall / ExternalAction AWAITING_APPROVAL;
- ApprovalRequest lifecycle;
- exact request binding fields;
- DB-time expiry shape;
- one pending request per Run;
- active/nonterminal uniqueness guards;
- zero ApprovalDecision semantics.

## 3. C2 — Atomic REQUIRE_APPROVAL pending consequence

Key commits:
- pending planner:
  `1c5492637f079282d7edd28e12d22d037f357051`
- APPROVAL_REQUESTED event:
  `ee3f5b7b80cc690b401bf4a893c87294bfbde077`
- recorder ports:
  `73957db5af6182b36a848d5fa704a2634a550e3a`
- recorder active-state fences:
  `34b6a00145d654352a27fd554e62d8da206f7429`
- PostgreSQL pending recorder:
  `2fd8cd20a4dda20859dd6b8e74d8dce951e8f608`
- journal pending facts:
  `5eecc4974651e19ce761ede7d113b4a517988213`
- journal C recorder:
  `bbaec5848afe16caa90c793c395f3fe95b4af9da`
- RunManager pending bridge:
  `77ddb8fa1d9c20ed6cd8035ac8baadb16aee419f`
- B regression update:
  `bd2b5a8b8c5603a7da1f564596166b5de4502dbc`
- C PostgreSQL initial contracts:
  `b44197297f7663290c4955e5ec82035b6a17c249`
- C unit bridge:
  `46b97f7e7d73cf8239a00014ef7d51ded9fecc2d`

C2 pending consequence:
- persists completed ModelInvocation + ToolProposal + GovernanceIntent + PolicyDecision;
- READ creates ToolCall AWAITING_APPROVAL + ApprovalRequest PENDING;
- side effect additionally creates immutable ActionSnapshot + ExternalAction AWAITING_APPROVAL;
- clears owner/lease and moves Run to WAITING_APPROVAL;
- increments logical tool_call_count only;
- creates zero ToolExecutionAttempt;
- performs zero adapter I/O.

## 4. Governance Amendment 001 dependency

C2 review exposed that capability-derived REQUIRE_APPROVAL could lack approver metadata when
the selected raw rule was ALLOW.

That gap was resolved and independently frozen before C3 continued.

Accepted rule:
- REQUIRE_APPROVAL rule: approval metadata mandatory;
- ALLOW rule: optional fallback approval metadata;
- DENY rule: approval metadata forbidden;
- capability-derived approval without selected-rule metadata fails closed to DENY;
- runtime never invents approval authority.

Accepted semantic candidate:
- `8d7b214c9ce38e201da364af59dcc35a90565205`

Successful gate:
- `37325262562`

## 5. C3 — Restart / claim / terminal guards / review projection

Pending cancellation:
- `803a848160a7b746d48d48dc104279b65b24cf7a`

Deterministic review projection:
- `bacd45b5f0ef8304b6aa2264cc3e982c090c1673`

PostgreSQL review store:
- `f3b3a2b084506cb4f02ae99c2e0381242793af7d`

Review store port:
- `3360edff806d97f2a9f50f6723d790fab01b4de7`

Pending-only review cleanup:
- `97639c21374d3cfae5094859496f0cf34bb0ee19`

C3 PostgreSQL contracts:
- `9627bdcb3362fc8ea41421efd5811bbe997e20d7`

Approval-request DB deadline race fence:
- `1a5efa6af2bc0a2b8158682582e64283530b5ef7`

C gate bound to Amendment 001:
- `ab4229c6379b66f4e613da4ac4fe4614d6ebf193`

Review projection unit contract:
- `14200811561c295c48be123fa8d7979ff0f7541d`

Canonical GovernanceIntent / ActionSnapshot revalidation:
- `880e391e0f07941071ad1c3859db4989ab73e893`

WAITING_APPROVAL terminal guard contract:
- `0341b1ee1f0247533613d61bb45e45faaa66349c`

C3 proves:
- WAITING_APPROVAL is not a worker claim candidate;
- checkpoint overlay does not resume it as ordinary work;
- stale pre-wait executor loses ownership;
- pending READ is not a READ recovery candidate;
- pending side effect is not READY Action Commit work;
- cancellation atomically stabilizes pending governance state;
- review projection is reconstructed from durable facts and fails closed on identity drift;
- no approval decision or approved execution behavior is introduced.

## 6. Candidate #1 — rejected

Candidate:
- `0341b1ee1f0247533613d61bb45e45faaa66349c`

Trigger:
- `b8b85ff4ccfc0fe4c1c75d0432ac997a40a431c0`

Run:
- `37328632050`

Passed:
- frozen lineage;
- migration lineage;
- C unit;
- C PostgreSQL;
- no-D guard.

Rejected only because Ruff formatter required normalization in three C3 files.

Formatter-only repairs:
- `055508e3b70c607343f94eec58847402b35215fc`
- `2bc9e710372e691c8b1de59531b4d3a3b97d22e2`
- `e3a10c5f27494ec4adc3d2564a96a4088f78c422`

## 7. Candidate #2 — rejected

Candidate:
- `e3a10c5f27494ec4adc3d2564a96a4088f78c422`

Trigger:
- `ead242d04848b5273134455eae81abefcfb52c08`

Run:
- `37329148579`

Passed:
- C unit;
- C PostgreSQL;
- no-D guard;
- Ruff lint;
- Ruff format.

Rejected only by one mypy narrowing error in pending cancellation:
`ToolCallRow | None` assigned to a variable inferred as `ToolCallRow`.

Type-only repair:
- `400336d6086c550039626f6717b6401410cc8e3b`

## 8. Candidate #3 — accepted

Accepted semantic candidate:

`400336d6086c550039626f6717b6401410cc8e3b`

Trigger:

`165cce2b98a3143bef52b73226e240ce2fe25db2`

Successful workflow run:

`37329756162`

Final workflow conclusion:
**SUCCESS**

Verified steps:
- frozen Stage 3.3 lineage and C surface: PASS;
- accepted Stage 3.2 + A1 + A2 migration lineage unchanged: PASS;
- Stage 3.3-C unit contracts: PASS;
- Stage 3.3-C PostgreSQL contracts: PASS;
- no Stage 3.3-D decision/resume implementation: PASS;
- complete Stage 3.2 regression: PASS.

## 9. Final frozen C properties

Stage 3.3-C creates durable approval intent only.

It does not:
- make approval decisions;
- authorize human approve/deny commands;
- materialize approval expiry;
- resume approved work;
- execute DESTRUCTIVE tools;
- weaken Stage 3.2 no-approval physical execution predicates.

Those remain Stage 3.3-D responsibilities.
