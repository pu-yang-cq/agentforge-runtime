# Stage 3.3 Governance Control Plane — Design V0.2

Status: **CORRECTIVE DRAFT — NOT YET ACCEPTED**

Parent baseline:
- Stage 3.2 Runtime V1.0 — ACCEPTED / FROZEN
- immutable RC: rc/stage3.2-v1.0-r2
- RC SHA: fa747268cfbf1d5b57e5796b9cbc767abc3d4e0c

Derived from:
- Design V0.1;
- V0.1 Self Review;
- V0.1 Scenario Validation;
- V0.1 Adversarial Review.

Implementation remains locked.

## 1. Objective

Stage 3.3 adds deterministic Tool authorization and durable human approval above Stage 3.2.

It owns:

~~~text
who may request
which immutable policy decides
whether Tool use is allowed/denied/approval-gated
who may approve
what exact intent was approved
how approval waits/resumes durably
~~~

It does not replace Stage 3.2 execution safety.

## 2. Scope corrections from V0.1

V0.2 explicitly does not build:

- general IAM;
- OAuth/OIDC;
- OPA/Rego/Cedar language;
- arbitrary ABAC;
- policy management UI;
- quorum/multi-step approval workflow;
- live revocation of already pinned Runs;
- cryptographically tamper-proof audit archive;
- adaptive model replanning after governance DENY.

A future policy-engine adapter may replace the built-in evaluator while preserving durable
governance facts.

## 3. Governance compatibility mode

AgentVersion gains:

~~~text
governance_mode = LEGACY_STAGE32 | GOVERNED
governance_policy_version_id nullable
~~~

Invariant:

~~~text
LEGACY_STAGE32
  => governance_policy_version_id IS NULL

GOVERNED
  => governance_policy_version_id IS NOT NULL
~~~

Migration from accepted Stage 3.2:

- every existing AgentVersion is backfilled LEGACY_STAGE32;
- its accepted Stage 3.2 behavior remains byte/semantic regression compatible;
- no existing AgentVersion silently gains approval-authorized destructive behavior.

Stage 3.3 governance features require GOVERNED AgentVersion.

New Stage 3.3 governance acceptance fixtures use GOVERNED mode.

This compatibility exception is explicit and auditable rather than an implicit default allow.

## 4. Run requester authority snapshot

A governed Run durably stores an immutable requester snapshot created by a trusted
PrincipalResolver at Run creation:

~~~text
requester_principal_id
requester_principal_type = USER | SERVICE
requester_roles[]
principal_scope
authn_source
governance_policy_version_id
~~~

The snapshot is authorization/audit input for the lifetime of the Run.

It does not come from:
- model output;
- worker identity;
- later approval request body.

Requester role revocation for already-created Runs is deferred to future live-revocation
semantics.

## 5. PrincipalResolver trust boundary

The API/application boundary receives PrincipalContext from a trusted PrincipalResolver.

Stage 3.3 does not implement authentication protocols.

A development resolver may produce:

~~~text
principal_id = wave1:anonymous
principal_scope = wave1
roles = [developer]
~~~

for compatibility tests.

Production deployments must inject a real resolver.

Caller-provided approver/resolver identity strings are not authority.

## 6. GovernancePolicyVersion lifecycle

Policy version fields:

~~~text
id
policy_set_id
version_number
status = DRAFT | PUBLISHED | RETIRED
rules
created_at
published_at
retired_at
~~~

Rules:
- DRAFT content may change before publish;
- PUBLISHED content is immutable;
- PUBLISHED -> RETIRED changes lifecycle metadata only;
- RETIRED cannot be assigned to a new GOVERNED AgentVersion;
- a Run already pinned to that published version continues using it for deterministic
  reproducibility.

Live revocation of pinned Runs is deferred.

## 7. Minimal policy rule schema

Each published policy contains a bounded ordered set of rules.

Rule fields:

~~~text
rule_id
priority
principal_roles_any[]
agent_version_ids[]
tool_version_ids[]
effect_types[]
principal_scopes[]
decision = ALLOW | DENY | REQUIRE_APPROVAL

approval:
  required_approver_role
  separation_of_duties
  ttl_seconds
~~~

Empty match arrays mean wildcard for that dimension.

Rules are validated before publish.

Limits:
- rule_id unique;
- priority is signed bounded integer;
- ttl_seconds positive and bounded;
- approval fields required only for REQUIRE_APPROVAL.

No recursive conditions or arbitrary expressions exist in Stage 3.3.

## 8. Deterministic evaluation algorithm

For one Tool proposal:

1. load the Run-pinned published policy version;
2. load immutable ToolBinding/ToolVersion capability;
3. evaluate all matching rules;
4. if none match -> DENY;
5. sort matches by:
   - priority descending;
   - decision severity DENY > REQUIRE_APPROVAL > ALLOW;
   - rule_id ascending;
6. first sorted match is the raw policy result;
7. apply the immutable capability envelope;
8. persist effective PolicyDecision.

The selected rule_id is therefore deterministic.

Malformed published policy is a fail-closed runtime configuration error and cannot produce
ALLOW.

## 9. Capability envelope V0.2

Policy may restrict but not broaden capability.

### READ

- raw DENY -> DENY;
- approval_required=true -> REQUIRE_APPROVAL;
- raw REQUIRE_APPROVAL -> REQUIRE_APPROVAL;
- raw ALLOW -> ALLOW.

### WRITE / EXTERNAL_SIDE_EFFECT

- raw DENY -> DENY;
- approval_required=true -> REQUIRE_APPROVAL;
- raw REQUIRE_APPROVAL -> REQUIRE_APPROVAL;
- raw ALLOW + allow_no_approval_execution=true -> ALLOW;
- raw ALLOW + allow_no_approval_execution=false -> REQUIRE_APPROVAL.

Therefore approval is a valid authorization mode for a side-effect Tool even when
no-approval execution is forbidden.

### DESTRUCTIVE

- raw DENY -> DENY;
- every other raw outcome -> REQUIRE_APPROVAL.

DESTRUCTIVE can never be effective ALLOW without human approval.

## 10. PolicyDecision

Every governed Tool proposal produces one immutable PolicyDecision.

Fields:

~~~text
id
run_id
proposal_id
tool_version_id
policy_version_id
requester_principal_id
principal_scope
effective_decision
matched_rule_id
intent_digest
created_at
~~~

PolicyDecision does not consume physical Tool-attempt budget.

## 11. GovernanceIntent V1

GovernanceIntent provides deterministic policy/audit binding for every Tool proposal.

Canonical object:

~~~json
{
  "agent_version_id": "<uuid>",
  "arguments": "<restricted canonical value>",
  "effect_type": "<enum>",
  "format_version": 1,
  "principal_scope": "<scope>",
  "proposal_id": "<uuid>",
  "requester_principal_id": "<principal>",
  "run_id": "<uuid>",
  "tool_version_id": "<uuid>"
}
~~~

Canonicalization reuses the frozen restricted RFC 8785 discipline and safe integer range.

No secret material enters GovernanceIntent.

## 12. Side-effect approval identity uses ActionSnapshot

For WRITE / EXTERNAL_SIDE_EFFECT / DESTRUCTIVE that require approval, the governance
consequence transaction creates before waiting:

~~~text
ToolCall AWAITING_APPROVAL
ActionSnapshot immutable
ExternalAction AWAITING_APPROVAL
ApprovalRequest PENDING
Run WAITING_APPROVAL
~~~

ActionSnapshot includes the stable operation_id exactly as in Stage 3.2.

ApprovalRequest stores:

~~~text
governance_intent_digest
action_snapshot_digest
external_action_id
~~~

The human therefore approves the exact frozen side-effect identity that may later enter
Action Commit.

No ToolExecutionAttempt exists yet.

## 13. READ approval identity

READ has no ExternalAction.

For approval-required READ:

~~~text
ToolCall AWAITING_APPROVAL
ApprovalRequest PENDING
Run WAITING_APPROVAL
~~~

Approval binds GovernanceIntent.digest.

No physical attempt exists before approval.

## 14. New ExternalAction state

Stage 3.3 adds:

~~~text
AWAITING_APPROVAL
~~~

Legal governance transitions:

~~~text
AWAITING_APPROVAL -> READY
AWAITING_APPROVAL -> ABORTED
~~~

Invariants:

- current_attempt_id = NULL;
- no STARTED ToolExecutionAttempt references the action;
- Action Commit rejects AWAITING_APPROVAL;
- normal READY recovery does not select it;
- no reconciliation applies because no physical effect was attempted.

Projection while pending:

~~~text
ExternalAction AWAITING_APPROVAL
        ⇕
ToolCall AWAITING_APPROVAL
~~~

After approval:

~~~text
ExternalAction READY
        ⇕
ToolCall READY
~~~

After deny/expiry/cancel:

~~~text
ExternalAction ABORTED
        ⇕
ToolCall NOT_EXECUTED
~~~

Policy DENY occurs before ExternalAction creation and may still use ToolCall DENIED.

## 15. Run WAITING_APPROVAL

Stage 3.3 activates:

~~~text
WAITING_APPROVAL
~~~

Transition:

~~~text
RUNNING
 -> WAITING_APPROVAL
 -> QUEUED(APPROVAL_RESOLVED)
 -> RUNNING
~~~

WAITING_APPROVAL:
- owner_worker_id = NULL;
- lease_expires_at = NULL;
- not selected by normal worker claim;
- not a terminal state.

## 16. ApprovalRequest

Fields:

~~~text
id
run_id
tool_call_id
external_action_id nullable
policy_decision_id
governance_intent_digest
action_snapshot_digest nullable
requested_by_principal
principal_scope
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

Unique:
- one ApprovalRequest per governed ToolCall;
- max one PENDING request per Run because one business ToolCall progresses at a time.

effective expires_at:

~~~text
min(
  request_created_at + matched_rule.ttl_seconds,
  Run.deadline_at
)
~~~

using PostgreSQL time.

## 17. ApprovalDecision

Fields:

~~~text
id
approval_request_id
decision = APPROVE | DENY
approver_principal_id
approver_scope
reason
redacted_evidence
created_at
~~~

One final human decision per request.

Exact replay by the same authenticated principal with identical content is idempotent.

Contradictory replay is rejected.

Evidence uses a restricted bounded JSON value contract and secret-key/value sentinel checks.

## 18. Approval review projection

Human review data is generated from durable facts only.

Required fields:

- Tool name/version;
- effect type;
- canonical/redacted arguments;
- requester principal id/scope;
- policy version and matched rule;
- GovernanceIntent digest;
- ActionSnapshot digest + operation_id for side effect;
- expires_at.

Model-authored explanation is not authorization evidence.

If exposed later, model prose must be labeled untrusted context.

## 19. Approval creation transaction — READ

When effective decision REQUIRE_APPROVAL for READ:

~~~text
BEGIN
  lock Run
  verify generation/lease/RUNNING
  verify not cancel_requested
  verify DB deadline
  persist ModelInvocation outcome
  persist ToolProposal
  persist GovernanceIntent
  persist PolicyDecision
  persist ToolCall AWAITING_APPROVAL
  persist ApprovalRequest PENDING
  Run -> WAITING_APPROVAL
  clear owner/lease
  append events
COMMIT
STOP
~~~

No ToolExecutionAttempt and no READ adapter call.

## 20. Approval creation transaction — side effect

When effective decision REQUIRE_APPROVAL for side effect:

~~~text
BEGIN
  lock Run
  verify generation/lease/RUNNING
  verify not cancel_requested
  verify DB deadline
  persist ModelInvocation outcome
  persist ToolProposal
  persist GovernanceIntent
  persist PolicyDecision
  generate stable operation_id
  persist ToolCall AWAITING_APPROVAL
  persist ActionSnapshot
  persist ExternalAction AWAITING_APPROVAL
  persist ApprovalRequest PENDING bound to ActionSnapshot.digest
  Run -> WAITING_APPROVAL
  clear owner/lease
  append events
COMMIT
STOP
~~~

There is no Action Commit and zero physical I/O.

## 21. Budget accounting

Governance does not create hidden budget consumption.

Normative accounting:

- model proposal consumes one model invocation exactly as Stage 3.2;
- accepted durable Tool proposal increments logical tool_call_count once;
- PolicyDecision consumes no physical Tool attempt;
- ApprovalRequest/Decision consumes no physical Tool attempt;
- WAITING_APPROVAL consumes no physical Tool attempt;
- first approved physical READ or side-effect invocation increments tool_attempts_used in the
  existing Stage 3.2 start/Action-Commit transaction;
- denied/expired/cancelled-before-effect Tool never increments tool_attempts_used.

## 22. Approval resolution lock order

All decision paths serialize:

~~~text
Run
 -> ApprovalRequest
 -> ToolCall
 -> ExternalAction when present
 -> ApprovalDecision insert
~~~

PolicyDecision and immutable snapshots may be read/verified without becoming a conflicting
mutable lock root.

The Run row remains first.

## 23. APPROVE semantics

Within the decision transaction:

1. lock Run;
2. lock request;
3. use PostgreSQL clock;
4. if request is due/expired, expiry wins;
5. verify WAITING_APPROVAL;
6. verify cancel_requested=false;
7. verify exact subject digests;
8. verify authenticated approver scope/role;
9. verify separation of duties;
10. insert ApprovalDecision APPROVE.

READ:

~~~text
ApprovalRequest -> APPROVED
ToolCall -> READY
Run -> QUEUED(APPROVAL_RESOLVED)
~~~

Side effect:

~~~text
ApprovalRequest -> APPROVED
ExternalAction AWAITING_APPROVAL -> READY
ToolCall AWAITING_APPROVAL -> READY
Run -> QUEUED(APPROVAL_RESOLVED)
~~~

No adapter I/O occurs in this transaction.

## 24. DENY semantics

READ:

~~~text
ApprovalRequest -> DENIED
ToolCall -> DENIED
Run -> FAILED
~~~

Side effect:

~~~text
ApprovalRequest -> DENIED
ExternalAction AWAITING_APPROVAL -> ABORTED
ToolCall AWAITING_APPROVAL -> NOT_EXECUTED
Run -> FAILED
~~~

No physical attempt exists.

The policy/audit facts express that the reason was governance denial.

## 25. Expiry semantics

Stage 3.3 defines a narrow maintenance operation:

~~~text
expire_due_approvals(limit)
~~~

Discovery may read candidate ids without lock.

For each candidate, mutation transaction:

~~~text
BEGIN
  lock Run
  lock ApprovalRequest
  re-read DB clock
  verify still PENDING
  verify expires_at <= now
  lock ToolCall
  lock ExternalAction if present
  request -> EXPIRED
  side-effect action -> ABORTED if present
  call -> NOT_EXECUTED
  Run -> FAILED
  append events
COMMIT
~~~

Because effective expires_at <= Run.deadline_at, WAITING_APPROVAL cannot legitimately outlive
the Run deadline.

Approve and expiry use the same Run-first serialization and DB clock.

If approve sees the request due, it performs/observes expiry instead of recording APPROVE.

## 26. Cancellation while waiting

Authorized cancellation uses Run first.

PENDING READ approval:

~~~text
request -> CANCELLED
ToolCall -> NOT_EXECUTED
Run -> CANCELLED
~~~

PENDING side effect:

~~~text
request -> CANCELLED
ExternalAction AWAITING_APPROVAL -> ABORTED
ToolCall -> NOT_EXECUTED
Run -> CANCELLED
~~~

No later approval may reopen the Run.

## 27. Control-plane authorization

Stage 3.3 brings mutating APIs under PrincipalContext.

### create_run

Requester snapshot comes from authenticated/trusted context.

### cancel_run

Allowed when:
- same principal_scope and requester owns Run; or
- caller has runtime:cancel:any role in the same scope.

### resolve_action

Caller must have runtime:resolve_action role in the same principal_scope.

resolver_identity is removed as an authority field from request body.

Durable ActionResolution resolver identity comes from PrincipalContext.

### approval decision

Caller must:
- share principal_scope;
- hold required approver role;
- satisfy separation of duties.

List/get approval APIs are scope-filtered.

A development PrincipalResolver preserves existing local API tests without claiming
production authentication.

## 28. Policy administration scope

General policy CRUD HTTP API is deferred.

Stage 3.3 provides repository/domain operations sufficient to:
- create DRAFT policy version in tests/admin bootstrap;
- validate/publish it;
- retire it;
- assign PUBLISHED policy version to a GOVERNED AgentVersion.

Production policy-management UI/API is future work.

## 29. Approved READ recovery

After APPROVE:

~~~text
Run QUEUED(APPROVAL_RESOLVED)
ToolCall READY
no ExternalAction
~~~

Worker recovery verifies:
- ToolVersion effect_type = READ;
- ApprovalRequest APPROVED;
- exact intent digest.

Then existing Stage 3.2 READ start transaction creates ToolExecutionAttempt STARTED and
consumes physical attempt budget.

Fresh model reasoning comes later.

## 30. Approved side-effect recovery

After APPROVE:

~~~text
Run QUEUED(APPROVAL_RESOLVED)
ToolCall READY
ExternalAction READY
ActionSnapshot frozen
ApprovalRequest APPROVED
~~~

Worker sees ExternalAction, so it cannot be misclassified as READ.

Coordinator uses a separate approved-side-effect authorization path.

It verifies:
- request APPROVED;
- request.external_action_id matches;
- ActionSnapshot digest matches;
- proposal/tool/version/effect/arguments match;
- principal scope matches;
- binding remains immutable.

Then the existing Stage 3.2 Action Commit transaction authorizes the physical attempt.

## 31. Destructive execution bridge

Stage 3.2 no-approval eligibility remains unchanged.

Do not broaden stage32_side_effect_executable.

Stage 3.3 adds an approved execution predicate:

~~~text
approved_side_effect_executable
~~~

which requires:
- effect type WRITE / EXTERNAL_SIDE_EFFECT / DESTRUCTIVE;
- linked ApprovalRequest APPROVED;
- exact snapshot digest;
- matching ToolVersion/binding;
- no unresolved/cancelled/expired governance state.

DESTRUCTIVE reaches physical I/O only through this predicate plus Stage 3.2 Action Commit.

## 32. Recovery precedence

For GOVERNED Run:

~~~text
unresolved external truth / reconciliation
        ↓
READY ExternalAction recovery
        ↓
READY READ recovery
        ↓
fresh model reasoning
~~~

Approval resolution itself transforms pending state to READY before worker claim.

Therefore no separate ambiguous “approved continuation” state is required.

WAITING_APPROVAL remains unclaimable.

## 33. PolicyDecision consequence fencing

Policy evaluation may be computed as a pure candidate outside the consequence transaction.

Persistence must lock Run and re-check:
- generation/lease;
- cancellation;
- deadline;
- pinned policy version;
- immutable Tool binding.

If cancellation/deadline wins before governance consequence commit:
- candidate decision may be discarded as non-authoritative;
- no ToolCall/ApprovalRequest/ExternalAction progression is created.

This preserves Stage 3.2 consequence fencing.

## 34. Policy retirement

RETIRED means:
- not assignable to new GOVERNED AgentVersion;
- existing AgentVersion and Run historical references remain readable;
- already pinned Runs continue under the pinned version.

Emergency revocation of pinned Runs is explicitly deferred.

## 35. Approval vs UNKNOWN

ApprovalRequest exists only for pre-physical authorization.

Once a side-effect action crosses Action Commit:
- approval state does not decide business truth;
- possible execution still becomes UNKNOWN;
- reconciliation/manual ActionResolution remains mandatory.

An APPROVED request can never be used as proof of NOT_EXECUTED.

## 36. Audit events

Stage 3.3 durable events include:

~~~text
POLICY_DECIDED
APPROVAL_REQUESTED
APPROVAL_APPROVED
APPROVAL_DENIED
APPROVAL_EXPIRED
APPROVAL_CANCELLED
APPROVAL_RESOLVED_QUEUED
CONTROL_PLANE_AUTHZ_DENIED
~~~

Audit projection contains durable ids, scope, policy/rule, digest and status.

It excludes:
- resolved secrets;
- bearer tokens;
- unrestricted headers;
- chain-of-thought;
- model-authored approval summary.

Stage 3.3 claims durable application audit evidence, not tamper-proof archival compliance.

## 37. Migration lineage

Stage 3.3 migration chain starts after:

~~~text
0016_checkpoint_overlay
~~~

Accepted Stage 3.1/3.2 migration files remain byte-identical.

Final immutable RC must prove:

~~~text
accepted Stage 3.2 database
 -> new Alembic process
 -> Stage 3.3 head
~~~

on PostgreSQL 18.

## 38. Corrected implementation slices

Draft until design acceptance.

### 3.3-A — Identity + policy foundation

- PrincipalContext / requester snapshot;
- AgentVersion governance mode;
- policy schema/lifecycle;
- evaluator interface/reference evaluator;
- GovernanceIntent;
- PolicyDecision;
- Stage 3.2 compatibility gate.

### 3.3-B — Governed ALLOW / DENY enforcement

- policy consequence transaction;
- READ ALLOW;
- no-approval side-effect ALLOW;
- DENY;
- control-plane PrincipalContext authorization;
- budget/accounting proof.

### 3.3-C — Durable approval intent

- WAITING_APPROVAL;
- ToolCall AWAITING_APPROVAL;
- ExternalAction AWAITING_APPROVAL;
- preapproval ActionSnapshot for side effects;
- ApprovalRequest;
- deterministic approval review projection;
- zero-I/O acceptance.

### 3.3-D — Approval decision + approved execution

- ApprovalDecision;
- approve/deny API;
- SoD;
- expiry;
- cancellation races;
- approved READ resume;
- approved side-effect/destructive path;
- Action Commit preservation.

### 3.3-E — Governance recovery/audit matrix

- restart recovery;
- duplicate decisions;
- policy pinning/retirement;
- scope isolation;
- secret leakage;
- full concurrency/adversarial matrix;
- Stage 3.3 aggregate acceptance.

### 3.3-F — Immutable RC

- exact Stage 3.2 lineage;
- Stage 3.2 -> 3.3 forward migration;
- full Python 3.14/PostgreSQL 18 gate;
- immutable RC.

## 39. V0.2 governing invariants

### G-I1

Model reasoning never grants authorization.

### G-I2

Policy may restrict but never broaden ToolVersion capability.

### G-I3

WAITING_APPROVAL has zero physical Tool attempts and zero worker ownership.

### G-I4

Side-effect approval binds the exact immutable ActionSnapshot digest.

### G-I5

Approval authorizes entry into the runtime; Stage 3.2 Action Commit still authorizes physical
side-effect invocation.

### G-I6

DESTRUCTIVE has no no-approval path.

### G-I7

Approval cannot resolve UNKNOWN business truth.

### G-I8

Run is the root serialization point for approval/cancel/expiry/progression races.

### G-I9

DB time determines approval expiry/deadline ordering.

### G-I10

Governance facts are durable and redacted; credentials/auth tokens remain outside them.

### G-I11

Existing Stage 3.2 AgentVersions remain explicit LEGACY_STAGE32 rather than silently changing
governance behavior.

### G-I12

A governed side-effect waiting for approval is structurally distinguishable from READY READ
recovery.

## 40. Gate state

~~~text
Stage 3.3 Design V0.2
🔄 CORRECTIVE DRAFT

V0.2 Re-Review
🔒 REQUIRED

Implementation
🔒 LOCKED
~~~

Governing rule:

> Approval freezes and grants authority over a precise pre-effect intent; only the durable
> runtime may turn that authority into physical execution.
