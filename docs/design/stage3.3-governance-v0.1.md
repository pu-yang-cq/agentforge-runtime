# Stage 3.3 Governance Control Plane — Design V0.1

Status: **DRAFT — NOT ACCEPTED**

Parent baseline:
- Stage 3.2 Runtime V1.0 — ACCEPTED / FROZEN
- immutable RC: rc/stage3.2-v1.0-r2
- RC SHA: fa747268cfbf1d5b57e5796b9cbc767abc3d4e0c
- final gate: 37262139363

Process contract:
- docs/execution/verified-execution-protocol-v1.0.md

No implementation work is authorized by this draft.

## 1. Objective

Stage 3.3 adds a deterministic Governance Control Plane above the frozen Stage 3.2
durable runtime.

Stage 3.2 answers:

> Once an Agent action is authorized, how does AgentForge execute it durably and safely?

Stage 3.3 answers:

> Who is allowed to authorize a Tool action, which policy governs that decision, when is
> human approval required, and how is that authority proven and audited?

The governance layer must never weaken Stage 3.2 safety boundaries.

In particular:

- governance approval is not physical execution authority by itself;
- an approved side effect must still cross Stage 3.2 Action Commit;
- approval never turns UNKNOWN into safe retry authority;
- governance cannot bypass cancellation, deadline, generation fencing, budget, or
  reconciliation rules.

## 2. Product boundary

Stage 3.3 is a focused governance layer, not a general enterprise IAM platform.

In scope:

1. durable principal identity used for authorization;
2. immutable/versioned governance policy assignment;
3. deterministic policy evaluation;
4. policy outcomes ALLOW / DENY / REQUIRE_APPROVAL;
5. durable human ApprovalRequest / ApprovalDecision;
6. WAITING_APPROVAL Run state and APPROVAL_RESOLVED queueing;
7. approval expiry and cancellation interaction;
8. separation-of-duties support for approval;
9. exact approval binding to the proposed Tool execution intent;
10. audit-grade governance events and query surface;
11. approval recovery after process restart;
12. destructive Tool execution only through explicit approval.

Out of scope:

- login/password implementation;
- OAuth/OIDC provider implementation;
- directory synchronization;
- arbitrary ABAC expression language;
- Rego/OPA-compatible policy language;
- multi-step approval workflow designer;
- N-of-M quorum approval;
- approval UI;
- billing/entitlement platform;
- cross-organization federation;
- generic workflow/DAG orchestration.

Authentication may be supplied by a trusted upstream adapter. Stage 3.3 owns authorization
and durable governance semantics.

## 3. Existing Stage 3.2 surfaces reused

Stage 3.3 intentionally builds on surfaces already reserved by Stage 3.2:

- ToolBinding.approval_required;
- ToolBinding.allow_no_approval_execution;
- ToolCallStatus.DENIED;
- QueueReason.APPROVAL_RESOLVED;
- ActionSnapshot canonical digest;
- Run-row serialization;
- Action Commit Boundary.

Stage 3.3 activates the previously reserved Run state:

~~~text
WAITING_APPROVAL
~~~

Stage 3.3 must preserve all accepted Stage 3.2 invariants.

## 4. Governance authority model

Governance has four distinct authorities.

### 4.1 Capability authority

ToolVersion / ToolBinding defines the immutable execution capability envelope:

- ToolVersion identity;
- effect type;
- whether approval is intrinsically required;
- whether no-approval execution is permitted;
- credential reference;
- idempotency/reconciliation capabilities.

A governance policy may restrict this envelope. It may never broaden it.

Examples:

~~~text
approval_required = true
policy says ALLOW
=> effective result cannot become no-approval ALLOW
~~~

~~~text
DESTRUCTIVE
policy says ALLOW
=> effective result still requires approval
~~~

### 4.2 Policy authority

A published immutable GovernancePolicyVersion determines whether a Tool proposal is:

~~~text
ALLOW
DENY
REQUIRE_APPROVAL
~~~

Policy evaluation is deterministic application logic.

The model never decides its own authorization result.

### 4.3 Human approval authority

An authorized approver may decide one durable pending ApprovalRequest.

Approval authorizes the exact bound intent only.

It does not authorize:
- different arguments;
- another ToolVersion;
- another Run;
- another proposal;
- a future retry of an UNKNOWN side effect;
- any physical adapter call that has not crossed the Stage 3.2 boundary.

### 4.4 Runtime progression authority

The Run row remains the per-Run serialization point.

Even a valid approved decision cannot continue business work if:
- cancellation already won;
- Run deadline expired;
- ownership/generation is stale;
- Run is terminal;
- approved intent no longer matches durable facts.

## 5. PrincipalContext

Stage 3.3 introduces a trusted application-level principal context.

Minimum fields:

~~~text
principal_id
principal_type = USER | SERVICE
roles[]
authn_source
tenant_scope
~~~

The principal context used for a governance decision is persisted in redacted normalized
form sufficient for later audit.

Stage 3.3 does not accept model-produced principal identity.

Production authentication is expected to inject PrincipalContext through a trusted adapter.

A development/test resolver may provide a fixed local principal.

## 6. GovernancePolicyVersion

A GovernancePolicyVersion is immutable once published.

Minimum fields:

~~~text
id
policy_set_id
version_number
status = DRAFT | PUBLISHED | RETIRED
rules
created_at
published_at
~~~

A Run uses one pinned published policy version for governance decisions.

Initial Stage 3.3 policy matching is intentionally limited to:

- principal role;
- ToolVersion id;
- Tool effect type;
- AgentVersion id;
- tenant scope.

V0.1 does not define an arbitrary expression language.

Rule result:

~~~text
ALLOW
DENY
REQUIRE_APPROVAL
~~~

Rule precedence:

1. explicit DENY;
2. explicit REQUIRE_APPROVAL;
3. ALLOW;
4. otherwise default DENY.

The capability envelope is applied after policy matching so policy cannot broaden ToolVersion
safety.

## 7. PolicyDecision

Every model Tool proposal that reaches governance produces a durable PolicyDecision before a
physical Tool attempt can occur.

Minimum fields:

~~~text
id
run_id
proposal_id
tool_version_id
policy_version_id
principal_id
decision = ALLOW | DENY | REQUIRE_APPROVAL
rule_id
intent_digest
created_at
~~~

PolicyDecision is immutable evidence.

A decision records what policy decided at that durable point; it is not retroactively
rewritten.

## 8. Governance intent binding

Approval must bind to exact immutable intent, not merely Tool name.

Stage 3.3 V0.1 defines a canonical GovernanceIntent V1 containing:

~~~json
{
  "agent_version_id": "<uuid>",
  "arguments": "<canonical restricted value>",
  "effect_type": "<enum>",
  "format_version": 1,
  "principal_id": "<normalized principal>",
  "proposal_id": "<uuid>",
  "run_id": "<uuid>",
  "tool_version_id": "<uuid>"
}
~~~

Canonicalization uses the same restricted RFC 8785-compatible value domain and SHA-256
discipline frozen for ActionSnapshot.

The resulting intent_digest binds PolicyDecision and ApprovalRequest.

For side effects, ActionSnapshot generated after approval must preserve the exact:

- ToolVersion;
- effect type;
- arguments.

The new operation_id remains a runtime execution identity and does not change what human
intent was approved.

## 9. Effective policy outcome

The raw GovernancePolicyVersion result is combined with immutable ToolVersion capability.

### READ

- policy DENY -> DENY;
- policy REQUIRE_APPROVAL -> REQUIRE_APPROVAL;
- policy ALLOW + approval_required=false -> ALLOW;
- approval_required=true -> REQUIRE_APPROVAL.

### WRITE / EXTERNAL_SIDE_EFFECT

- policy DENY -> DENY;
- approval_required=true -> REQUIRE_APPROVAL;
- policy REQUIRE_APPROVAL -> REQUIRE_APPROVAL;
- policy ALLOW is permitted only when allow_no_approval_execution=true;
- otherwise -> REQUIRE_APPROVAL or DENY according to capability eligibility.

### DESTRUCTIVE

Always REQUIRE_APPROVAL unless policy produces DENY.

DESTRUCTIVE may never use no-approval execution in Stage 3.3.

## 10. ToolCall approval projection

Stage 3.3 adds:

~~~text
ToolCallStatus.AWAITING_APPROVAL
~~~

Legal governance transitions:

~~~text
CREATED -> AWAITING_APPROVAL
CREATED -> DENIED

AWAITING_APPROVAL -> READY
AWAITING_APPROVAL -> DENIED
AWAITING_APPROVAL -> NOT_EXECUTED
~~~

After READY, existing Stage 3.2 execution semantics apply.

For READ, READY may immediately enter the existing physical-attempt start transaction.

For side effects, READY means governance authorization exists but Stage 3.2 Action Commit
has not yet occurred.

No physical ToolExecutionAttempt exists while AWAITING_APPROVAL.

## 11. Run approval state

Stage 3.3 adds the previously reserved Run state:

~~~text
WAITING_APPROVAL
~~~

Normal transition:

~~~text
RUNNING
  -> WAITING_APPROVAL
  -> QUEUED(APPROVAL_RESOLVED)
  -> RUNNING
~~~

WAITING_APPROVAL:
- has no worker owner;
- has no live lease;
- is not a normal worker claim candidate;
- is resumed only by a durable approval result that authorizes continuation.

DENY, expiry, deadline, or cancellation may terminate instead of requeueing.

## 12. ApprovalRequest

ApprovalRequest is durable and immutable except for its lifecycle state.

Minimum fields:

~~~text
id
run_id
tool_call_id
policy_decision_id
intent_digest
requested_by_principal
required_approver_role
separation_of_duties
status
expires_at
created_at
decided_at
~~~

Statuses:

~~~text
PENDING
APPROVED
DENIED
EXPIRED
CANCELLED
~~~

There is at most one active approval request for one governed ToolCall.

## 13. ApprovalDecision

ApprovalDecision is a durable final human governance fact.

Minimum fields:

~~~text
id
approval_request_id
decision = APPROVE | DENY
approver_principal_id
reason
evidence
created_at
~~~

One final decision per ApprovalRequest.

Exact replay is idempotent.

A contradictory second decision is rejected.

If separation_of_duties=true:

~~~text
approver_principal_id != requested_by_principal
~~~

and the approver must hold the required approval role.

## 14. Approval creation transaction

When policy result is REQUIRE_APPROVAL:

~~~text
BEGIN
  lock Run
  verify current generation/lease
  verify RUNNING
  verify not cancel_requested
  verify DB-time deadline
  persist completed ModelInvocation
  persist ToolProposal
  persist ToolCall AWAITING_APPROVAL
  persist GovernanceIntent digest
  persist PolicyDecision REQUIRE_APPROVAL
  persist ApprovalRequest PENDING
  Run -> WAITING_APPROVAL
  clear owner + lease
  append governance events
COMMIT
~~~

Then STOP.

There is:
- no physical Tool attempt;
- no side-effect adapter call;
- no ExternalAction Action Commit;
- no model continuation.

## 15. Approval resolution transaction

Approval decisions serialize through Run first.

Lock order:

~~~text
Run
  -> ApprovalRequest
  -> ToolCall
  -> PolicyDecision
~~~

For side-effect continuation, later ActionSnapshot / ExternalAction creation remains a
separate durable preparation transaction before Stage 3.2 Action Commit.

### APPROVE

Required rechecks:

- request still PENDING;
- intent digest matches durable ToolCall/proposal facts;
- approver authorized;
- separation-of-duties satisfied;
- Run is WAITING_APPROVAL;
- cancel_requested=false;
- DB-time deadline not expired.

Then:

~~~text
ApprovalDecision APPROVE persisted
ApprovalRequest -> APPROVED
ToolCall -> READY
Run -> QUEUED
queue_reason = APPROVAL_RESOLVED
clear owner/lease
COMMIT
~~~

A worker later resumes from durable approved intent.

### DENY

~~~text
ApprovalDecision DENY persisted
ApprovalRequest -> DENIED
ToolCall -> DENIED
Run -> FAILED
no physical attempt
~~~

V0.1 uses fail-closed terminal denial rather than asking the model to work around a rejected
governance decision.

## 16. Approval expiry

ApprovalRequest has a DB-time expires_at.

A pending approval that reaches expiry becomes:

~~~text
ApprovalRequest -> EXPIRED
ToolCall -> DENIED
Run -> FAILED
reason = APPROVAL_EXPIRED
~~~

No worker lease is used as an approval timer.

Expiry is processed by an explicit durable maintenance/decision path using PostgreSQL time.

## 17. Cancellation while waiting approval

Cancellation serializes through Run.

If cancellation wins while:

~~~text
Run WAITING_APPROVAL
ApprovalRequest PENDING
ToolCall AWAITING_APPROVAL
~~~

then:

~~~text
cancel_requested = true
ApprovalRequest -> CANCELLED
ToolCall -> NOT_EXECUTED
Run -> CANCELLED
~~~

No later APPROVE may re-open the Run.

Cancellation while waiting approval is safe because no physical Tool attempt crossed its
execution boundary.

## 18. Deadline vs approval

Approval does not extend the Run deadline.

If an approval command arrives after deadline:

- durable ApprovalDecision may be recorded as operator evidence;
- it must not authorize new physical business work;
- ToolCall becomes NOT_EXECUTED;
- Run -> FAILED;
- reason = DEADLINE_EXCEEDED_AFTER_APPROVAL.

A late approval cannot create APPROVAL_RESOLVED queueing.

## 19. Side-effect execution after approval

Approval never calls an adapter directly.

After approved intent is claimed:

~~~text
approved ToolCall READY
        ↓
construct/persist immutable ActionSnapshot + ExternalAction READY
        ↓
Stage 3.2 Action Commit transaction
        ↓
ToolExecutionAttempt STARTED
ExternalAction EXECUTING
        ↓
COMMIT
        ↓
physical adapter I/O
~~~

For DESTRUCTIVE operations this is mandatory.

Approval is authorization to enter the Stage 3.2 side-effect pipeline, not a replacement for
that pipeline.

## 20. Recovery precedence

On worker claim, Stage 3.3 preserves Stage 3.2 recovery authority.

Proposed precedence:

~~~text
unresolved reconciliation / external truth
        ↓
durable READY side-effect recovery
        ↓
durable READY READ recovery
        ↓
approved governance continuation
        ↓
fresh model reasoning
~~~

WAITING_APPROVAL is never worker-claimable.

A ToolCall AWAITING_APPROVAL must never be reconstructed by asking the model again.

## 21. Governance audit events

Stage 3.3 adds events such as:

~~~text
POLICY_DECIDED
APPROVAL_REQUESTED
APPROVAL_APPROVED
APPROVAL_DENIED
APPROVAL_EXPIRED
APPROVAL_CANCELLED
APPROVAL_RESOLVED_QUEUED
~~~

Events must include stable ids/digests and redacted identities sufficient for audit.

They must not include:
- resolved credential secrets;
- authorization tokens;
- model chain-of-thought;
- unrestricted request headers.

## 22. API surface

Proposed minimal API:

~~~text
GET  /v1/approvals
GET  /v1/approvals/{approval_id}
POST /v1/approvals/{approval_id}/approve
POST /v1/approvals/{approval_id}/deny
~~~

Decision endpoints take authenticated PrincipalContext from a trusted API auth adapter.

The request body may contain:
- reason;
- structured redacted evidence.

It may not choose an arbitrary approver identity string supplied by the caller.

## 23. Security rules

Stage 3.3 V0.1 requires:

1. default-deny when no policy rule grants authority;
2. policy cannot broaden immutable ToolVersion capability;
3. model output is never authorization evidence;
4. destructive Tools never execute without explicit approved request;
5. approver identity comes from trusted PrincipalContext;
6. optional separation-of-duties enforced transactionally;
7. approval binds exact intent digest;
8. approval cannot bypass cancellation/deadline/stale generation;
9. no secret material in governance snapshots/events;
10. no approval can resolve Stage 3.2 UNKNOWN business truth.

## 24. Concurrency and race rules

Mandatory serialized races include:

- approval vs cancellation;
- approval vs expiry;
- approval vs deadline;
- duplicate approvers;
- approve vs deny;
- approval vs stale Run generation;
- approval result vs operator retry;
- approved continuation vs later cancellation before Action Commit.

Run remains the root lock for any race that may create business progression.

## 25. Migration / compatibility rules

Stage 3.3 migrations must be strictly forward from accepted Stage 3.2 head:

~~~text
0016_checkpoint_overlay
        ↓
Stage 3.3 migrations
~~~

Accepted Stage 3.1 and Stage 3.2 migration files may not be rewritten.

The final Stage 3.3 RC must prove:

~~~text
accepted Stage 3.2 database
        ↓
new Alembic process
        ↓
Stage 3.3 head
~~~

in PostgreSQL 18.

## 26. Proposed implementation slices

This is a draft slicing plan, not yet frozen.

### 3.3-A — Governance domain + immutable policy decisions

- PrincipalContext;
- GovernancePolicyVersion;
- deterministic evaluator;
- GovernanceIntent V1;
- PolicyDecision;
- capability-envelope rules;
- policy decision audit.

### 3.3-B — Enforcement bridge

- policy evaluation on model Tool proposal;
- ALLOW / DENY behavior;
- READ enforcement;
- existing no-approval side-effect compatibility;
- destructive fail-closed;
- no approval waiting yet.

### 3.3-C — Durable approval wait/resume

- WAITING_APPROVAL;
- ToolCall AWAITING_APPROVAL;
- ApprovalRequest / ApprovalDecision;
- approve/deny API;
- expiry;
- separation-of-duties;
- APPROVAL_RESOLVED queueing.

### 3.3-D — Approved side-effect + destructive execution

- approved intent -> ActionSnapshot/ExternalAction;
- destructive Tool support;
- cancellation/deadline/approval races;
- approval-bound identity checks;
- no bypass of Action Commit.

### 3.3-E — Governance recovery + audit matrix

- restart/recovery of pending approvals;
- duplicate decision races;
- audit query projection;
- secret leakage gate;
- full governance adversarial matrix;
- Stage 3.3 aggregate acceptance.

### 3.3-F — Immutable RC + final acceptance

- frozen Stage 3.2 lineage hashes;
- Stage 3.2 -> Stage 3.3 forward migration;
- full Python 3.14 + PostgreSQL 18 gate;
- immutable RC.

## 27. Initial acceptance thesis

Stage 3.3 should not be considered complete merely because an Approve button works.

Acceptance must prove:

~~~text
Model proposes Tool
        ↓
deterministic policy
        ↓
ALLOW / DENY / REQUIRE_APPROVAL
        ↓
if approval:
  durable wait
  no worker lease
  no physical I/O
        ↓
authorized human decision
        ↓
exact intent match
        ↓
durable resume
        ↓
Stage 3.2 safety boundary still applies
~~~

The defining rule is:

> Governance grants authority to enter the durable runtime; it never replaces durable
> runtime correctness.
