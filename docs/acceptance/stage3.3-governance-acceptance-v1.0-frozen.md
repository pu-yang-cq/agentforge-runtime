# Stage 3.3 Governance Control Plane — Acceptance Criteria V1.0 — FROZEN

Status: **ACCEPTED / FROZEN**

Depends on:
- docs/design/stage3.3-governance-v0.3.md
- complete V0.1/V0.2 review chain

Regression baseline:
- Stage 3.2 Runtime V1.0 immutable RC2
- rc/stage3.2-v1.0-r2
- fa747268cfbf1d5b57e5796b9cbc767abc3d4e0c

These criteria are the authoritative Stage 3.3 implementation and runtime-acceptance contract.

## A. Frozen Stage 3.2 regression

The exact accepted Stage 3.2 full gate remains mandatory.

No accepted Stage 3.1/3.2 migration may be rewritten.

LEGACY_STAGE32 AgentVersion behavior must preserve accepted Stage 3.2 runtime and API tests.

## B. AgentVersion governance immutability

Mandatory DB/domain tests:

~~~text
LEGACY_STAGE32 -> policy_version_id NULL
GOVERNED      -> PUBLISHED policy_version_id non-null
~~~

After AgentVersion creation/persistence:
- governance_mode cannot change;
- policy_version_id cannot change;
- changing governance policy for future work requires a new AgentVersion.

Governed Run copies exact policy_version_id.

## C. Legacy compatibility isolation

Default legacy/development API compatibility may preserve accepted Stage 3.2 tests.

Mandatory:
- explicitly identifiable LegacyDevelopmentPrincipalResolver;
- it cannot authorize a GOVERNED Run;
- governed production path requires trusted PrincipalResolver;
- caller-provided identity cannot elevate governed authority;
- resolver_identity wire compatibility, if retained, is non-authoritative for GOVERNED mode.

## D. Principal normalization

Persisted governed requester:
- principal_id stripped/nonblank/bounded;
- principal_scope stripped/nonblank/bounded;
- authn_source stripped/nonblank/bounded;
- roles stripped, unique, sorted, bounded.

Equivalent role sets in different input order produce identical GovernanceIntent digest.

## E. Governed create/read authorization

For GOVERNED mode:

create_run requires runtime:run:create.

GET Run:
- requester allowed; or
- same-scope runtime:run:read:any allowed;
- cross-scope single-resource read -> 404 to avoid resource-existence disclosure.

Legacy compatibility behavior remains separately tested.

## F. Policy lifecycle and pinning

Mandatory:
- DRAFT cannot authorize;
- publish freezes rule content;
- RETIRED cannot be assigned to new AgentVersion;
- existing pinned Run continues exact version;
- no automatic switch to newest policy;
- historical PolicyDecision keeps exact policy_version_id.

## G. Deterministic policy evaluation

All matching rules sorted exactly:
1. priority descending;
2. DENY > REQUIRE_APPROVAL > ALLOW;
3. rule_id ascending.

No match -> DENY.

Malformed published policy -> fail closed.

Evaluation result identical across input rule order and process restart.

## H. Capability envelope

READ:
- DENY -> DENY;
- approval_required or raw REQUIRE_APPROVAL -> REQUIRE_APPROVAL;
- otherwise ALLOW.

WRITE/EXTERNAL_SIDE_EFFECT:
- DENY -> DENY;
- approval_required or raw REQUIRE_APPROVAL -> REQUIRE_APPROVAL;
- ALLOW only when no-approval capability true;
- otherwise REQUIRE_APPROVAL.

DESTRUCTIVE:
- DENY -> DENY;
- otherwise REQUIRE_APPROVAL.

No destructive no-approval path.

## I. GovernanceIntent V1

Golden canonical byte/digest vectors must cover:
- requester/scope/roles;
- ToolVersion;
- AgentVersion;
- Run/proposal;
- effect type;
- nested arguments;
- Unicode;
- integer bounds;
- float rejection;
- input object ordering.

Secrets/tokens absent.

## J. Model-result governance consequence fence

Arrange:
1. ModelInvocation STARTED;
2. provider returns Tool proposal;
3. before governance consequence commit, cancellation/deadline wins.

If invocation is still authorized:
- model outcome may be durably recorded;
- MODEL_RESULT_DISCARDED recorded;
- no PolicyDecision;
- no ToolCall business consequence;
- no ApprovalRequest;
- no ExternalAction.

If generation is stale:
- old executor cannot finalize invocation or governance consequence.

## K. Policy ALLOW paths

READ ALLOW:
- PolicyDecision durable;
- no approval;
- physical attempt still Stage 3.2 STARTED-before-I/O.

Side-effect ALLOW:
- only no-approval-capable Tool;
- ActionSnapshot/ExternalAction intent durable;
- Action Commit still before physical I/O.

## L. Policy DENY

Required:
- PolicyDecision DENY;
- ToolCall DENIED;
- no ApprovalRequest;
- no ExternalAction;
- no ToolExecutionAttempt;
- no adapter I/O;
- Run fail closed unless cancellation already won.

## M. READ pending approval

Transaction must commit:
- ToolProposal;
- GovernanceIntent;
- PolicyDecision REQUIRE_APPROVAL;
- ToolCall AWAITING_APPROVAL;
- ApprovalRequest PENDING;
- Run WAITING_APPROVAL;
- owner/lease NULL.

No physical attempt/I/O.

## N. Side-effect pending approval

Transaction must commit:
- ToolProposal;
- GovernanceIntent;
- PolicyDecision REQUIRE_APPROVAL;
- ToolCall AWAITING_APPROVAL;
- stable operation_id;
- ActionSnapshot immutable;
- ExternalAction AWAITING_APPROVAL;
- ApprovalRequest PENDING bound to both digests/action id;
- Run WAITING_APPROVAL.

Required:
- current_attempt_id NULL;
- no ToolExecutionAttempt;
- zero provider I/O.

## O. Pending projection and terminal guard

Projection:

~~~text
ExternalAction AWAITING_APPROVAL
        ⇕
ToolCall AWAITING_APPROVAL
~~~

While active pending governance exists:
- Run cannot COMPLETED;
- cannot fresh model reason;
- cannot normal worker claim;
- cannot terminalize through unrelated path leaving request/action inconsistent.

Terminal path must atomically stabilize pending governance.

## P. Global lock order

Every Stage 3.3 side-effect mutation must follow:

~~~text
Run
 -> ExternalAction when present
 -> ToolCall
 -> ApprovalRequest
 -> ToolExecutionAttempt/ReconciliationAttempt when participating
 -> ApprovalDecision insert
~~~

READ omits ExternalAction.

Static/structural tests and real PostgreSQL races must reject/avoid reverse ToolCall ->
ExternalAction order.

## Q. Logical expiry safety

For PENDING request:

~~~text
db_now >= expires_at
=> cannot authorize progression
~~~

Mandatory even if expire_due_approvals has never run.

Test:
- leave request physically PENDING past expires_at;
- call approve directly;
- no APPROVE decision;
- no requeue;
- materialize/observe expiry;
- zero I/O.

## R. Expiry materialization

expire_due_approvals(limit):
- candidate discovery may be unlocked;
- mutation locks Run first;
- canonical child order;
- PostgreSQL clock;
- recheck due/PENDING;
- request EXPIRED;
- side action ABORTED if present;
- ToolCall NOT_EXECUTED;
- Run FAILED.

effective expires_at = min(policy TTL due, Run deadline).

Restart preserves due time.

## S. Approval authorization and SoD

Decision requires:
- same scope;
- required role;
- trusted principal;
- request logically pending;
- SoD if configured.

Requester self-approval with SoD=true -> no mutation.

Cross-scope -> no mutation.

## T. APPROVE READ

Commit:
- ApprovalDecision APPROVE;
- Request APPROVED;
- ToolCall READY;
- Run QUEUED(APPROVAL_RESOLVED);
- owner/lease cleared.

No adapter I/O in decision transaction.

Later worker verifies approval binding and READ effect before physical STARTED attempt.

## U. APPROVE side effect

Canonical lock order.

Commit:
- ApprovalDecision APPROVE;
- Request APPROVED;
- Action AWAITING_APPROVAL -> READY;
- ToolCall AWAITING_APPROVAL -> READY;
- Run QUEUED(APPROVAL_RESOLVED).

ActionSnapshot/operation_id unchanged.

No adapter I/O in approval transaction.

## V. DENY

READ:
- request DENIED;
- ToolCall DENIED;
- Run FAILED.

Side effect:
- request DENIED;
- Action ABORTED;
- ToolCall NOT_EXECUTED;
- Run FAILED.

No physical attempt.

## W. Decision idempotency after later progression

After APPROVE commits and Run later:
- is claimed;
- executes;
- completes/fails/cancels;

an exact replay of same decision/principal/reason/evidence returns existing durable decision
without mutating Run/action.

Different replay -> conflict.

Same requirement for DENY.

## X. Cancellation races

Pending cancel:
- request CANCELLED;
- side action ABORTED when present;
- ToolCall NOT_EXECUTED;
- Run CANCELLED;
- no physical attempt.

Approve wins first:
- may queue APPROVAL_RESOLVED;
- later cancel before physical start still fences physical work under Stage 3.2.

After Action Commit:
- cancellation remains non-rollback.

Real PostgreSQL tests must force both orderings.

## Y. Approved READ restart

Crash after APPROVE before claim.

Required:
- Run QUEUED(APPROVAL_RESOLVED);
- exact ToolCall READY;
- exact approved request;
- worker recognizes READ;
- no fresh model proposal/second approval;
- one physical attempt.

## Z. Approved side-effect restart

Crash after APPROVE before claim.

Required:
- ActionSnapshot/operation_id reused;
- ExternalAction READY;
- no READ misclassification;
- approval binding checked;
- first physical call only after Action Commit.

## AA. Destructive execution

Required chain:

~~~text
DESTRUCTIVE
 -> REQUIRE_APPROVAL
 -> ActionSnapshot/ExternalAction AWAITING_APPROVAL
 -> APPROVE
 -> READY
 -> Action Commit
 -> Attempt STARTED
 -> I/O
~~~

No ApprovalDecision or forged/mismatched/expired approval -> call_count 0.

Existing Stage 3.2 no-approval predicate remains unchanged.

## AB. Approval does not resolve UNKNOWN

After approved side effect crosses Action Commit and becomes UNKNOWN:
- old APPROVE is not retry authority;
- reconciliation/ActionResolution required;
- no blind physical replay.

## AC. Exact budget accounting

- proposal -> model invocation accounted once;
- governed ToolCall -> logical tool_call_count once;
- PolicyDecision/approval wait/decision -> zero physical attempts;
- denied/expired/cancelled pre-effect -> zero physical attempts;
- each adapter call -> exactly one tool_attempts_used.

## AD. Mutating control-plane authorization

GOVERNED:
- create -> runtime:run:create;
- cancel -> requester or same-scope runtime:cancel:any;
- manual resolve -> same-scope runtime:resolve_action;
- approval decision -> required role/scope/SoD.

ActionResolution durable resolver identity must come from trusted context.

Legacy Stage 3.2 API contract remains isolated in development compatibility mode.

## AE. Governed read isolation

Run get + approval list/detail must not leak across principal_scope.

Mandatory:
- cross-scope single-resource Run/approval lookup -> 404;
- approval collection/list silently filters invisible requests;
- same-scope mutation on a visible resource without the required role -> 403;
- no response body leaks hidden requester/argument/digest metadata.

Approval review projection is deterministic durable data, not model-written prose.

## AF. Audit/secret boundary

Sentinels absent from:
- GovernanceIntent;
- PolicyDecision;
- ApprovalRequest;
- ApprovalDecision after evidence validation/redaction;
- DomainEvent;
- logs;
- ModelRequest/messages;
- ActionSnapshot;
- checkpoint.

Audit claims durable application evidence only.

## AG. Governance recovery/race matrix

At minimum:
1. ALLOW consequence vs cancel;
2. DENY consequence vs cancel;
3. request commit vs worker crash;
4. approve vs cancel;
5. approve vs logical expiry;
6. approve vs deny;
7. duplicate approve;
8. exact decision replay after Run progression;
9. approved READ crash before claim;
10. approved side effect crash before claim;
11. cancel after approve before physical start;
12. cancel after side-effect READY before Action Commit;
13. cancel after Action Commit;
14. stale generation governance consequence;
15. destructive response-loss UNKNOWN;
16. pending approval terminal guard;
17. policy retirement during pinned Run;
18. legacy compatibility cannot authorize governed Run.

## AH. Stage 3.2 -> 3.3 forward migration

Exact final candidate must prove on PostgreSQL 18:

~~~text
accepted Stage 3.2 database
0016_checkpoint_overlay
        ↓
new Alembic process
        ↓
Stage 3.3 head
~~~

Accepted Stage 3.1/3.2 migration hashes unchanged.

## AI. Full final gate

Exact candidate:
- CPython 3.14;
- uv --locked;
- Ruff;
- Ruff format;
- mypy strict;
- Alembic online;
- unit tests;
- PostgreSQL integration;
- governance race matrix;
- full Stage 3.2 recovery/crash regression.

## AJ. Immutable RC

Final acceptance belongs to exact immutable Stage 3.3 ref/SHA.

Rejected RC remains preserved.

Governing acceptance rule:

> A durable approval can authorize an exact pre-effect intent, but it cannot override
> identity fencing, logical expiry, cancellation, or the Stage 3.2 physical execution
> boundary.
