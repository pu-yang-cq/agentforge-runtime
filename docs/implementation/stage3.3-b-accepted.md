# Stage 3.3-B — Governed ALLOW / DENY + Control-plane Authorization

Status: **ACCEPTED / FROZEN**

Parent:
- Stage 3.3 Governance Design V1.0 — ACCEPTED / FROZEN
- Stage 3.3 Governance Acceptance Criteria V1.0 — FROZEN
- Stage 3.3-A Aggregate — ACCEPTED / FROZEN
- Stage 3.3 implementation slices — FROZEN PLAN

Accepted semantic candidate:

`bdeef5adbda0408b7b17af9042ce1dd731ab3804`

Independent acceptance trigger:

`a28977d7b8a484faa73166e9f38ab74246246cd9`

Successful GitHub Actions run:

`37300886491`

Execution record:

`docs/execution/stage3.3-b-execution-record.md`

## Accepted scope

Stage 3.3-B establishes the first governed runtime consequence bridge:

- trusted PrincipalContext authorization on governed control-plane operations;
- explicit legacy API compatibility mode;
- cross-scope non-disclosure;
- exact pinned-policy loading in Worker;
- deterministic governed READ ALLOW;
- governed no-approval WRITE / EXTERNAL_SIDE_EFFECT ALLOW;
- governed DENY fail closed;
- atomic GovernanceIntent + PolicyDecision + business consequence persistence;
- exact logical and physical budget accounting;
- cancellation/deadline/stale-generation consequence fencing;
- complete Stage 3.2 compatibility.

## Independent acceptance evidence

Workflow:
- **Stage 3.3-B Governed Allow Deny Authorization**

Successful run:
- **37300886491**

Trigger head:
- `a28977d7b8a484faa73166e9f38ab74246246cd9`

Verified gate:
- frozen Stage 3.3 lineage and B surface: PASS;
- accepted Stage 3.2 + A1 + A2 migration lineage unchanged: PASS;
- Stage 3.3-B unit contracts: PASS;
- Stage 3.3-B PostgreSQL 18 contracts: PASS;
- no early approval-state implementation: PASS;
- complete Stage 3.2 regression: PASS;
- workflow conclusion: **SUCCESS**.

## Rejected candidate history

1. Run `37285889157`
   - B unit: PASS;
   - PostgreSQL: 12 passed / 1 failed;
   - rejected on a test-only ORM string/Enum assertion.

2. Run `37291417246`
   - B unit/PostgreSQL/no-approval guard: PASS;
   - rejected on Ruff import-order only.

3. Run `37295408478`
   - B unit/PostgreSQL/no-approval guard: PASS;
   - Ruff lint: PASS;
   - rejected on Ruff formatter normalization only.

4. Run `37297994779`
   - B unit: PASS;
   - B PostgreSQL: PASS — 13 passed;
   - Ruff lint: PASS;
   - rejected on three remaining formatter-only test files.

Candidate #5 passed the complete gate.

## Frozen B invariants

### B-I1 — Trusted control-plane identity

GOVERNED control-plane authority comes only from trusted PrincipalContext resolution.

- create requires `runtime:run:create`;
- requester may read/cancel its own same-scope Run;
- privileged read/cancel requires explicit same-scope role;
- action resolution requires same-scope `runtime:resolve_action`;
- resolver identity cannot be forged from the request body;
- cross-scope resources are hidden as 404.

### B-I2 — Exact governed consequence

Every governed model Tool proposal binds:
- exact Run;
- exact AgentVersion;
- exact proposal;
- exact immutable ToolVersion binding;
- exact pinned policy;
- exact durable requester snapshot;
- exact GovernanceIntent digest;
- deterministic PolicyEvaluation.

The durable transaction revalidates these facts before consequence persistence.

### B-I3 — READ ALLOW physical boundary

A governed READ ALLOW persists in one transaction:
- completed model outcome;
- ToolProposal;
- GovernanceIntent;
- PolicyDecision ALLOW;
- ToolCall EXECUTING;
- ToolExecutionAttempt STARTED.

The adapter is called only after that transaction commits.

### B-I4 — Side-effect ALLOW preserves Stage 3.2 Action Commit

Governed no-approval WRITE / EXTERNAL_SIDE_EFFECT can be prepared only when the immutable
ToolVersion remains eligible under the existing Stage 3.2 side-effect predicate.

Preparation persists:
- GovernanceIntent;
- PolicyDecision ALLOW;
- ToolCall READY;
- ActionSnapshot;
- ExternalAction READY.

It creates zero physical ToolExecutionAttempt. Physical I/O still requires the accepted
Stage 3.2 Action Commit path.

### B-I5 — DENY is fail closed and zero-I/O

Governed DENY persists:
- GovernanceIntent;
- PolicyDecision DENY;
- exact ToolVersion-bound ToolCall DENIED;
- FAILED Run.

It creates:
- zero ExternalAction;
- zero ToolExecutionAttempt;
- zero adapter I/O.

### B-I6 — Consequence fencing

Before governance consequence commit, the PostgreSQL recorder rechecks:
- execution generation;
- live lease;
- RUNNING ownership;
- cancellation;
- DB deadline;
- exact pinned policy;
- immutable Tool binding.

If cancellation/deadline/stale ownership wins, candidate governance/business consequences do
not partially commit.

### B-I7 — Compatibility and stage boundary

LEGACY_STAGE32 continues using the accepted Stage 3.2 behavior.

B does not:
- add WAITING_APPROVAL;
- add AWAITING_APPROVAL;
- add ApprovalRequest;
- add ApprovalDecision;
- execute DESTRUCTIVE tools;
- broaden `stage32_side_effect_executable`.

REQUIRE_APPROVAL remains non-executable until Stage 3.3-C.

## Freeze boundary

Stage 3.3-B is frozen.

Any correctness-affecting change to:
- governed authorization;
- ALLOW / DENY consequence semantics;
- physical execution boundaries;
- consequence transaction fencing;
- budget accounting;
- legacy compatibility

requires an explicit governance design amendment or later accepted slice that preserves these
frozen invariants.

Stage 3.3-C may now implement durable approval intent only.

## Gate

~~~text
Stage 3.3-A1
✅ ACCEPTED / FROZEN

Stage 3.3-A2
✅ ACCEPTED / FROZEN

Stage 3.3-A Aggregate
✅ ACCEPTED / FROZEN

Stage 3.3-B
✅ ACCEPTED / FROZEN

Stage 3.3-C
🔓 UNLOCKED

Stage 3.3-D
🔒 LOCKED

Stage 3.3-E
🔒 LOCKED

Stage 3.3-F
🔒 LOCKED

Stage 3.3 Runtime Acceptance
🔒 LOCKED
~~~

Governing rule:

> A governed ALLOW or DENY becomes durable runtime consequence only after exact durable
> identity/policy/tool facts are revalidated under the Stage 3.2 ownership, deadline,
> cancellation and physical execution fences.
