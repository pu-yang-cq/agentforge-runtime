# Stage 3.3-A — Identity + Policy Foundation Aggregate Acceptance

Status: **ACCEPTED / FROZEN**

Parent contracts:
- Stage 3.3 Governance Design V1.0 — ACCEPTED / FROZEN
- Stage 3.3 Governance Acceptance Criteria V1.0 — FROZEN
- Stage 3.3 implementation slices — FROZEN PLAN

Accepted slices:
- Stage 3.3-A1 — Governance compatibility + identity/policy schema
- Stage 3.3-A2 — Deterministic evaluator + GovernanceIntent + PolicyDecision

Accepted semantic surface:

`9b8a9bd45dd8f76f93a06d1ece4a2846e7043af9`

Independent aggregate trigger:

`c17f04b14560eed7aee6cd1d1b2d463ee5c7e32b`

Successful aggregate GitHub Actions run:

`37281068420`

## Accepted slice evidence

### Stage 3.3-A1

Accepted semantic candidate:

`cf1c7571b67210bedfe411865bb940c83e6da4f0`

Successful independent gate:

`37268108885`

Acceptance artifact:

`docs/implementation/stage3.3-a1-accepted.md`

### Stage 3.3-A2

Accepted semantic candidate:

`9b8a9bd45dd8f76f93a06d1ece4a2846e7043af9`

Successful independent gate:

`37275301253`

Acceptance artifact:

`docs/implementation/stage3.3-a2-accepted.md`

Execution record:

`docs/execution/stage3.3-a2-execution-record.md`

## Aggregate acceptance evidence

Workflow:
- **Stage 3.3-A Aggregate Acceptance**

Successful run:
- **37281068420**

Trigger head:
- `c17f04b14560eed7aee6cd1d1b2d463ee5c7e32b`

Verified steps:
- frozen Stage 3.3-A lineage: PASS;
- accepted A2 runtime semantic surface has not drifted: PASS;
- frozen Stage 3.2 + A1 + A2 migration lineage unchanged: PASS;
- Stage 3.3-A unit aggregate: PASS;
- Stage 3.3-A PostgreSQL 18 aggregate: PASS;
- Stage 3.2 database forward migration through Stage 3.3-A head: PASS;
- complete Stage 3.2 regression on Stage 3.3-A aggregate head: PASS;
- workflow conclusion: **SUCCESS**.

## Frozen Stage 3.3-A invariants

Stage 3.3-A now freezes the complete identity/policy foundation:

- explicit LEGACY_STAGE32 / GOVERNED AgentVersion governance mode;
- normalized bounded PrincipalContext;
- trusted-vs-legacy principal resolver isolation;
- versioned durable GovernancePolicyVersion lifecycle;
- immutable AgentVersion policy assignment;
- exact governed Run policy/requester snapshot;
- exact legacy SQL-NULL compatibility;
- deterministic policy rule ordering;
- no-match and malformed-policy fail closed;
- exact retired pinned policy remains usable by already-pinned Runs;
- capability envelope cannot broaden immutable Tool capability;
- DESTRUCTIVE cannot effective-ALLOW;
- GovernanceIntent V1 canonical identity and digest;
- credential/secret sentinel exclusion from GovernanceIntent;
- immutable one-per-proposal PolicyDecision;
- exact policy/requester/tool/run binding;
- durable POLICY_DECIDED audit evidence;
- evaluation creates zero ToolCall;
- evaluation creates zero ToolExecutionAttempt;
- evaluation performs zero adapter I/O;
- accepted Stage 3.2 migrations remain byte-identical;
- accepted A1 migration remains unchanged;
- accepted A2 migration remains unchanged.

## Aggregate freeze boundary

Stage 3.3-A establishes facts and deterministic decisions only.

It still does **not**:
- make ALLOW execute a Tool;
- make DENY change Run/ToolCall business state;
- add WAITING_APPROVAL;
- add ApprovalRequest / ApprovalDecision;
- authorize DESTRUCTIVE execution;
- weaken Stage 3.2 physical execution boundaries.

Those consequences belong to later frozen slices.

## Next gate

With A1, A2 and the independent A aggregate all accepted, Stage 3.3-B may now unlock.

Stage 3.3-B must preserve:
- Stage 3.2 ModelInvocation consequence fencing;
- Stage 3.2 physical Tool execution boundaries;
- exact logical/physical budget accounting;
- A1 identity/policy invariants;
- A2 deterministic decision/audit invariants.

## Gate

~~~text
Stage 3.3-A1
✅ ACCEPTED / FROZEN

Stage 3.3-A2
✅ ACCEPTED / FROZEN

Stage 3.3-A Aggregate
✅ ACCEPTED / FROZEN

Stage 3.3-B
🔓 UNLOCKED

Stage 3.3-C
🔒 LOCKED

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

> Stage 3.3-A freezes who is asking, which policy is pinned, what exact Tool intent is being
> evaluated, and what deterministic policy decision was made; Stage 3.3-B is the first slice
> allowed to turn that durable decision into runtime ALLOW/DENY consequences.
