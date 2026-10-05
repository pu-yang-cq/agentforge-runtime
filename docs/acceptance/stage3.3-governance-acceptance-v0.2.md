# Stage 3.3 Governance Control Plane — Acceptance Criteria V0.2

Status: **CORRECTIVE DRAFT — NOT YET ACCEPTED**

Depends on:
- docs/design/stage3.3-governance-v0.2.md
- V0.1 review chain

Regression baseline:
- Stage 3.2 Runtime V1.0 immutable RC2
- rc/stage3.2-v1.0-r2
- fa747268cfbf1d5b57e5796b9cbc767abc3d4e0c

Implementation remains locked.

## A. Stage 3.2 compatibility mode gate

Migration must backfill all existing AgentVersion rows:

~~~text
governance_mode = LEGACY_STAGE32
governance_policy_version_id = NULL
~~~

Mandatory:
- complete Stage 3.2 regression remains green;
- legacy AgentVersion behavior does not silently gain approval/destructive capabilities;
- GOVERNED mode requires a published policy version.

## B. Governed Run requester snapshot gate

For GOVERNED AgentVersion create_run must persist trusted requester facts:

- requester_principal_id;
- requester_principal_type;
- requester_roles snapshot;
- principal_scope;
- authn_source;
- pinned governance_policy_version_id.

Restart/worker takeover must read these facts from PostgreSQL rather than transient API
context.

## C. Policy lifecycle gate

Mandatory:
- DRAFT policy cannot authorize runtime work;
- publish validates rule schema;
- PUBLISHED rule content cannot be edited;
- PUBLISHED may transition to RETIRED;
- RETIRED cannot be assigned to new governed AgentVersion;
- Run already pinned to a retired version remains reproducible.

## D. Deterministic rule ordering gate

Given multiple matching rules, evaluator must sort exactly:

1. priority descending;
2. DENY > REQUIRE_APPROVAL > ALLOW;
3. rule_id ascending.

Golden tests must prove result/matched rule are identical across input order and process
restart.

No matching rule -> DENY.

Malformed published rule -> fail closed.

## E. Capability-envelope gate

Mandatory cases:

### READ
- raw DENY -> DENY;
- approval_required=true -> REQUIRE_APPROVAL;
- raw REQUIRE_APPROVAL -> REQUIRE_APPROVAL;
- otherwise ALLOW.

### WRITE / EXTERNAL_SIDE_EFFECT
- raw DENY -> DENY;
- approval_required=true -> REQUIRE_APPROVAL;
- raw REQUIRE_APPROVAL -> REQUIRE_APPROVAL;
- raw ALLOW + allow_no_approval_execution=true -> ALLOW;
- raw ALLOW + allow_no_approval_execution=false -> REQUIRE_APPROVAL.

### DESTRUCTIVE
- raw DENY -> DENY;
- otherwise REQUIRE_APPROVAL;
- no no-approval execution path exists.

## F. GovernanceIntent canonical gate

GovernanceIntent V1 exact bytes/digest must be deterministic for:
- reordered objects;
- nested values;
- Unicode;
- arrays;
- safe integer bounds;
- rejected floats;
- requester change;
- scope change;
- Run/proposal/tool/agent/effect change.

Secret/token sentinels must not enter canonical bytes.

## G. PolicyDecision consequence-fence gate

Policy candidate may be computed outside transaction.

Before persisting Tool consequence, transaction must lock Run and re-check:
- current generation/lease;
- RUNNING;
- cancel_requested=false;
- DB deadline;
- pinned policy version;
- immutable Tool binding.

If cancellation/deadline/stale generation wins:
- no governance Tool consequence is created;
- no ApprovalRequest;
- no ExternalAction progression;
- no adapter call.

## H. Policy ALLOW READ gate

Required:
- PolicyDecision ALLOW durable;
- no ApprovalRequest;
- logical tool_call_count increments once;
- physical tool_attempt budget increments only at ToolExecutionAttempt STARTED;
- Stage 3.2 cancellation/deadline/fencing unchanged.

## I. Policy ALLOW side-effect gate

Only no-approval-capable ToolVersion may use this path.

Required:
- PolicyDecision ALLOW;
- ToolCall/ActionSnapshot/ExternalAction durable;
- no ApprovalRequest;
- Stage 3.2 Action Commit still precedes physical I/O.

## J. Policy DENY gate

Required:
- PolicyDecision DENY;
- ToolCall DENIED;
- no ExternalAction for denied proposal;
- no ApprovalRequest;
- no ToolExecutionAttempt;
- no adapter call;
- Run fails closed unless cancellation already won.

## K. READ approval creation gate

One Run-root transaction must produce:

- ToolProposal;
- GovernanceIntent;
- PolicyDecision REQUIRE_APPROVAL;
- ToolCall AWAITING_APPROVAL;
- ApprovalRequest PENDING;
- Run WAITING_APPROVAL;
- owner/lease cleared.

Zero physical attempts and zero adapter calls.

## L. Side-effect approval creation gate

One Run-root transaction must produce:

- ToolProposal;
- GovernanceIntent;
- PolicyDecision REQUIRE_APPROVAL;
- ToolCall AWAITING_APPROVAL;
- stable operation_id;
- immutable ActionSnapshot;
- ExternalAction AWAITING_APPROVAL;
- ApprovalRequest PENDING;
- governance intent digest;
- exact action_snapshot_digest;
- Run WAITING_APPROVAL;
- owner/lease cleared.

Mandatory:
- current_attempt_id NULL;
- no ToolExecutionAttempt;
- no Action Commit;
- zero provider calls.

## M. Pending projection gate

Mandatory projection:

~~~text
ExternalAction AWAITING_APPROVAL
        ⇕
ToolCall AWAITING_APPROVAL
~~~

It must be impossible for:
- READY action recovery;
- READ recovery;
- reconciliation;
- Action Commit

to select this state.

## N. WAITING_APPROVAL claimability gate

Run WAITING_APPROVAL:
- is never normal worker claim candidate;
- survives restart;
- has no owner/lease;
- cannot start ModelInvocation;
- cannot be reconstructed by model reasoning.

## O. Approval subject gate

READ approval binds GovernanceIntent.digest.

Side-effect approval binds:
- GovernanceIntent.digest;
- ActionSnapshot.digest;
- exact external_action_id.

Changing any approved ToolVersion/effect/argument/action snapshot must fail closed before
resume.

## P. Approval review projection gate

Human-facing review record must derive only from deterministic durable facts:

- Tool/version;
- effect type;
- redacted canonical arguments;
- requester/scope;
- policy/rule;
- digests;
- operation_id for side effect;
- expiry.

Model-generated summary is not required and cannot be authorization evidence.

## Q. Approval APPROVE READ gate

Under Run -> ApprovalRequest -> ToolCall locks:

Required:
- authenticated approver scope/role valid;
- separation of duties valid;
- DB now < expires_at;
- request PENDING;
- digests match;
- cancel_requested=false.

Commit:
- ApprovalDecision APPROVE;
- request APPROVED;
- ToolCall READY;
- Run QUEUED(APPROVAL_RESOLVED);
- no adapter call in decision transaction.

Later worker must verify READ effect type + APPROVED request before STARTED attempt.

## R. Approval APPROVE side-effect gate

Lock order:

~~~text
Run
 -> ApprovalRequest
 -> ToolCall
 -> ExternalAction
~~~

Commit:
- ApprovalDecision APPROVE;
- request APPROVED;
- action AWAITING_APPROVAL -> READY;
- ToolCall AWAITING_APPROVAL -> READY;
- Run QUEUED(APPROVAL_RESOLVED);
- owner/lease cleared.

ActionSnapshot/operation_id remain unchanged.

No adapter call in approval transaction.

## S. Approval DENY gate

READ:
- request DENIED;
- call DENIED;
- Run FAILED.

Side effect:
- request DENIED;
- action ABORTED;
- call NOT_EXECUTED;
- Run FAILED.

No physical attempt.

Exact replay idempotent.
Contradictory decision rejected.

## T. Separation-of-duties gate

When configured:
- requester cannot decide own approval even with role;
- missing required role -> 403/no mutation;
- wrong principal_scope -> 403/no mutation;
- distinct authorized approver succeeds.

Identity comes from PrincipalResolver, not body.

## U. Approval expiry gate

effective expires_at must equal:

~~~text
min(
  request_created_at + policy_rule.ttl_seconds,
  Run.deadline_at
)
~~~

expire_due_approvals(limit) must:
- use PostgreSQL clock;
- mutate under Run first;
- recheck request PENDING/due;
- expire READ or side-effect projection correctly;
- never create physical attempt.

Restart preserves expires_at.

## V. Approve vs expiry race

Both paths serialize Run first.

At decision time:
- if db_now >= expires_at, expiry wins;
- no APPROVE decision is committed;
- later approve is rejected/idempotently observes expired state.

Both transaction orderings must be tested with real PostgreSQL.

## W. Cancellation vs pending approval

Cancellation wins:
- request CANCELLED;
- READ call NOT_EXECUTED; or
- side action ABORTED + call NOT_EXECUTED;
- Run CANCELLED;
- later decision rejected;
- zero physical attempts.

Approval wins first:
- Run may queue APPROVAL_RESOLVED;
- later cancellation before physical start still fences via Stage 3.2.

## X. Approved READ crash recovery

Arrange:
- APPROVE committed;
- Run QUEUED(APPROVAL_RESOLVED);
- process crash before claim.

Required:
- same ToolCall remains READY;
- same approval request APPROVED;
- new worker proves effect_type READ;
- exact governed READ is attempted once;
- no second approval;
- no fresh model reasoning first.

## Y. Approved side-effect crash recovery

Arrange:
- APPROVE committed;
- Action READY;
- process crash before claim.

Required:
- existing ExternalAction/ActionSnapshot/operation_id reused;
- no READ misclassification;
- new worker verifies approval linkage;
- Stage 3.2 Action Commit creates first physical attempt;
- no second approval/model proposal.

## Z. Destructive Tool gate

Mandatory proof chain:

~~~text
DESTRUCTIVE proposal
 -> PolicyDecision REQUIRE_APPROVAL
 -> ActionSnapshot + ExternalAction AWAITING_APPROVAL
 -> ApprovalRequest PENDING
 -> human APPROVE
 -> ExternalAction READY
 -> Stage 3.2 Action Commit
 -> ToolExecutionAttempt STARTED
 -> physical adapter I/O
~~~

Negative cases:
- policy ALLOW but no human approval -> call count 0;
- forged APPROVED flag without matching ApprovalDecision/digest -> call count 0;
- stale/cancelled/expired approval -> call count 0.

## AA. Approved side-effect coordinator isolation gate

Existing Stage 3.2 no-approval predicate must remain unchanged.

Approved execution uses a separate eligibility path requiring durable approval evidence.

A test must prove DESTRUCTIVE cannot become executable by setting
allow_no_approval_execution.

## AB. Approval vs UNKNOWN gate

After Action Commit, approval state is not retry authority.

Simulate approved action:
- physical attempt ambiguous;
- Attempt -> UNKNOWN;
- Action -> UNKNOWN;
- ToolCall -> UNRESOLVED.

Required:
- no direct replay because request was previously APPROVED;
- reconciliation/manual ActionResolution only.

## AC. Budget accounting gate

Mandatory counters:

- one model proposal -> model_invocations_used +1;
- one governed Tool proposal -> tool_call_count +1;
- PolicyDecision -> no tool_attempt increment;
- ApprovalRequest/Decision -> no tool_attempt increment;
- denied/expired/cancelled pre-effect -> no tool_attempt increment;
- each physical adapter call -> exactly one tool_attempt increment.

## AD. Control-plane PrincipalContext gate

create_run:
- requester identity persisted from trusted context.

cancel:
- requester in same scope or same-scope runtime:cancel:any role.

manual action resolution:
- same-scope runtime:resolve_action role;
- resolver identity comes from trusted context.

approval:
- same scope + required role + SoD.

Caller-provided identity string cannot grant authority.

## AE. Approval list/get isolation

GET approval collection/detail must filter by principal_scope and role.

A principal from another scope cannot enumerate:
- pending approvals;
- requester ids;
- arguments/digests.

## AF. Policy retirement gate

Retirement:
- prevents new assignment;
- does not mutate historical PolicyDecision;
- does not switch an already-pinned Run to another version.

Restart reproduces same decision from pinned policy.

## AG. Audit/secret isolation

Sentinels for:
- credential secret;
- bearer token;
- raw auth header;
- password-like approval evidence key.

Must be absent from:
- GovernanceIntent;
- PolicyDecision;
- ApprovalRequest;
- ApprovalDecision durable evidence after validation/redaction;
- DomainEvent;
- logs;
- model context;
- ActionSnapshot;
- checkpoint.

## AH. Governance race matrix

At minimum:

1. ALLOW consequence vs cancel;
2. DENY consequence vs cancel;
3. approval request commit vs worker crash;
4. approve vs cancel;
5. approve vs expiry;
6. approve vs deadline/effective expiry;
7. approve vs deny;
8. duplicate approve;
9. approved READ crash before claim;
10. approved side effect crash before claim;
11. cancellation after approve before claim;
12. cancellation after side-effect READY before Action Commit;
13. cancellation after Action Commit;
14. stale generation approved continuation;
15. destructive action response-loss -> UNKNOWN;
16. manual ActionResolution cannot be replaced by approval semantics.

## AI. Stage 3.2 -> Stage 3.3 migration gate

On PostgreSQL 18:

~~~text
accepted Stage 3.2 database
0016_checkpoint_overlay
        ↓
new Alembic process
        ↓
Stage 3.3 head
~~~

Accepted Stage 3.1/3.2 migration hashes remain unchanged.

## AJ. Final project gate

Required on exact final candidate:

- CPython 3.14;
- uv --locked;
- Ruff;
- Ruff format;
- mypy strict;
- online Alembic migrations;
- full unit suite;
- PostgreSQL integration;
- governance race matrix;
- Stage 3.2 crash matrix/regression.

## AK. Immutable RC

Final acceptance belongs to exact immutable Stage 3.3 ref/SHA.

Rejected RC is preserved rather than moved.

Governing acceptance rule:

> Human approval authorizes an exact pre-effect intent; only the Stage 3.2 execution
> boundary can authorize physical side-effect I/O.
