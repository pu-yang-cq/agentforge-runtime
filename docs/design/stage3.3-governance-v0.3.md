# Stage 3.3 Governance Control Plane — Design V0.3 Freeze Candidate

Status: **FREEZE CANDIDATE — FINAL REVIEW REQUIRED**

Parent:
- Stage 3.2 Runtime V1.0 — ACCEPTED / FROZEN
- Design V0.2 + Acceptance V0.2
- V0.2 Re-Review

This document is the corrective freeze candidate. It preserves the V0.2 architecture except
where this document makes a rule more precise.

Implementation remains locked until final review + V1.0 freeze.

## 1. Product definition

Stage 3.3 is the AgentForge Governance Control Plane.

It adds deterministic authorization and durable approval to the accepted Stage 3.2 runtime.

Normative authority chain:

~~~text
trusted requester identity
        ↓
immutable AgentVersion governance spec
        ↓
pinned GovernancePolicyVersion
        ↓
deterministic PolicyDecision
        ↓
ALLOW | DENY | REQUIRE_APPROVAL
        ↓
if approval:
  exact durable pre-effect intent
  + authorized human decision
        ↓
Stage 3.2 durable execution boundary
~~~

Governance never substitutes for runtime correctness.

## 2. Explicit scope

In scope:
- requester principal snapshot;
- minimal versioned policy;
- deterministic policy evaluation;
- policy decision durability;
- READ and side-effect approval;
- destructive approval;
- approval expiry/cancel/deadline races;
- minimal control-plane authorization;
- durable audit evidence;
- restart/recovery;
- Stage 3.2 migration/regression preservation.

Deferred:
- authentication protocol implementation;
- arbitrary ABAC;
- OPA/Rego/Cedar language implementation;
- policy UI/general HTTP CRUD;
- quorum/sequential approvals;
- live revocation of already-pinned Runs;
- adaptive model replanning after DENY;
- cryptographic/WORM audit archive;
- generic enterprise IAM.

## 3. AgentVersion governance specification is immutable

AgentVersion gains immutable execution-spec fields:

~~~text
governance_mode = LEGACY_STAGE32 | GOVERNED
governance_policy_version_id nullable
~~~

Invariant:

~~~text
LEGACY_STAGE32 => policy_version_id NULL
GOVERNED      => policy_version_id references PUBLISHED policy
~~~

Once an AgentVersion exists, these fields do not change.

Changing policy for future executions requires creating a new AgentVersion.

Run copies the exact policy version id for governed execution.

## 4. Stage 3.2 compatibility

Stage 3.3 migration backfills every existing AgentVersion:

~~~text
governance_mode = LEGACY_STAGE32
governance_policy_version_id = NULL
~~~

LEGACY_STAGE32 executes the accepted Stage 3.2 behavior without Stage 3.3 reinterpretation.

It:
- does not gain approval-authorized destructive execution;
- preserves frozen API/runtime regression behavior;
- remains explicitly identifiable as legacy compatibility mode.

New governance behavior is exercised only by GOVERNED AgentVersion.

## 5. Trusted PrincipalContext

PrincipalContext:

~~~text
principal_id
principal_type = USER | SERVICE
roles
principal_scope
authn_source
~~~

Normalization before persistence:

- principal_id: stripped, nonblank, bounded;
- principal_scope: stripped, nonblank, bounded;
- authn_source: stripped, nonblank, bounded;
- roles: stripped, nonblank, unique, lexicographically sorted, bounded count/length.

Governed Run persists an immutable requester snapshot from trusted PrincipalResolver.

Model output and worker identity are never requester authority.

## 6. LegacyDevelopmentPrincipalResolver

To preserve accepted Stage 3.2 API contract, application construction may use an explicit
development compatibility resolver when no production resolver is injected.

Properties:

- named/documented as non-production;
- valid only for LEGACY_STAGE32 compatibility behavior;
- preserves existing wave1 anonymous/local tests;
- may preserve legacy resolver_identity request semantics solely for legacy API regression.

It must never grant authority over a GOVERNED Run.

For GOVERNED Run:
- trusted PrincipalResolver is mandatory;
- caller-provided resolver/approver identity cannot grant authority;
- if a legacy identity field is still accepted for wire compatibility, it is ignored as
  authority and may be rejected when inconsistent with authenticated principal.

## 7. Minimal control-plane authorization

For GOVERNED mode:

create_run:
- principal must have runtime:run:create.

get_run:
- requester or authorized same-scope runtime:run:read:any principal;
- a caller outside principal_scope receives 404 so resource existence is not disclosed.

cancel_run:
- requester in same scope; or
- same-scope runtime:cancel:any.

resolve_action:
- same-scope runtime:resolve_action.

approval list/get/decide:
- same scope;
- required approval role for decision;
- collection/list filters out requests the caller cannot review;
- single approval detail outside the caller's visible scope returns 404.

No cross-scope read or mutation is permitted. Mutating requests that identify an already
visible same-scope resource but lack the required role return 403.

LEGACY development compatibility keeps frozen Stage 3.2 API tests separate from these
production/governed rules.

## 8. GovernancePolicyVersion

Lifecycle:

~~~text
DRAFT -> PUBLISHED -> RETIRED
~~~

Rules:
- DRAFT is editable but cannot authorize runtime work;
- publish validates schema and freezes rule content;
- PUBLISHED rule content is immutable;
- RETIRED only changes lifecycle metadata;
- RETIRED cannot be assigned to a new AgentVersion;
- an already-pinned Run continues with its exact policy version.

Live revocation of already-pinned Runs is deferred.

## 9. Minimal policy rule

Fields:

~~~text
rule_id
priority
principal_roles_any
agent_version_ids
tool_version_ids
effect_types
principal_scopes
decision = ALLOW | DENY | REQUIRE_APPROVAL

approval.required_approver_role
approval.separation_of_duties
approval.ttl_seconds
~~~

Empty match set means wildcard for that dimension.

Deterministic selection:
1. all matching rules;
2. priority descending;
3. DENY > REQUIRE_APPROVAL > ALLOW;
4. rule_id ascending;
5. no match -> DENY.

Malformed published policy fails closed.

## 10. Capability envelope

Policy restricts but does not broaden immutable ToolBinding capability.

READ:
- DENY stays DENY;
- approval_required or raw REQUIRE_APPROVAL -> REQUIRE_APPROVAL;
- otherwise ALLOW.

WRITE / EXTERNAL_SIDE_EFFECT:
- DENY stays DENY;
- approval_required or raw REQUIRE_APPROVAL -> REQUIRE_APPROVAL;
- raw ALLOW + allow_no_approval_execution=true -> ALLOW;
- raw ALLOW + no no-approval capability -> REQUIRE_APPROVAL.

DESTRUCTIVE:
- DENY stays DENY;
- every other result -> REQUIRE_APPROVAL.

No DESTRUCTIVE no-approval path exists.

## 11. GovernanceIntent V1

Every GOVERNED Tool proposal gets a canonical GovernanceIntent.

Fields bind:
- Run;
- AgentVersion;
- proposal;
- ToolVersion;
- effect type;
- exact arguments;
- requester principal;
- principal scope.

Canonicalization uses the frozen restricted RFC 8785-compatible algorithm and safe integer
range.

No secret material enters the intent.

SHA-256 digest is persisted with PolicyDecision.

## 12. PolicyDecision

One immutable decision per governed Tool proposal:

~~~text
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

PolicyDecision is audit evidence, not physical execution authority.

## 13. Policy consequence fence

Pure policy computation may happen before persistence.

The consequence transaction locks Run and rechecks:
- current execution_generation and lease;
- RUNNING;
- cancel_requested=false;
- DB deadline;
- pinned policy id;
- immutable Tool binding.

If a still-authorized ModelInvocation returned a Tool proposal but cancellation/deadline wins
before governance consequence commit:

- ModelInvocation outcome may be recorded as durable evidence;
- MODEL_RESULT_DISCARDED is recorded;
- no PolicyDecision/ToolCall/ApprovalRequest/ExternalAction business consequence is created.

If generation/lease is stale, existing stale-executor rejection remains authoritative and the
old executor cannot finalize the invocation.

## 14. Governance Tool states

Stage 3.3 adds:

~~~text
RunStatus.WAITING_APPROVAL
ToolCallStatus.AWAITING_APPROVAL
ExternalActionStatus.AWAITING_APPROVAL
~~~

Pending side-effect projection:

~~~text
ExternalAction AWAITING_APPROVAL
        ⇕
ToolCall AWAITING_APPROVAL
~~~

No ToolExecutionAttempt exists in this state.

Action Commit cannot select it.

## 15. Side-effect preapproval identity

For WRITE / EXTERNAL_SIDE_EFFECT / DESTRUCTIVE effective REQUIRE_APPROVAL, the policy
consequence transaction creates:

- ToolCall AWAITING_APPROVAL;
- stable operation_id;
- immutable Stage 3.2 ActionSnapshot;
- ExternalAction AWAITING_APPROVAL;
- ApprovalRequest PENDING.

ApprovalRequest binds:
- GovernanceIntent digest;
- ActionSnapshot digest;
- ExternalAction id;
- operation_id through ActionSnapshot.

Human approval therefore binds the exact side-effect identity.

## 16. READ preapproval identity

For READ REQUIRE_APPROVAL:

- ToolCall AWAITING_APPROVAL;
- ApprovalRequest PENDING;
- no ExternalAction;
- no ToolExecutionAttempt.

Approval binds GovernanceIntent digest.

## 17. WAITING_APPROVAL

When approval request commits:

~~~text
Run -> WAITING_APPROVAL
owner_worker_id = NULL
lease_expires_at = NULL
~~~

It is not a normal worker claim candidate.

Fresh model reasoning cannot start.

The pending request survives restart.

## 18. ApprovalRequest

Fields include:

~~~text
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

effective expires_at is DB-time derived:

~~~text
min(
  created_at + policy ttl,
  Run.deadline_at
)
~~~

## 19. Logical expiry is authoritative

Safety does not depend on the expiry sweeper running on time.

For any PENDING request:

~~~text
db_now >= expires_at
=> request is logically expired
=> it cannot authorize business progression
~~~

Every:
- approve path;
- approved-resume path;
- maintenance path

checks this predicate.

expire_due_approvals(limit) only materializes EXPIRED state and terminal projections.

## 20. Expiry materialization

For each due candidate:

~~~text
Run
 -> ExternalAction if present
 -> ToolCall
 -> ApprovalRequest
~~~

then:
- verify still PENDING and due;
- request -> EXPIRED;
- side-effect action -> ABORTED if present;
- ToolCall -> NOT_EXECUTED;
- Run -> FAILED;
- append events.

Discovery may be unlocked/read-only; mutation uses canonical Run-root order.

## 21. Global lock order

Stage 3.3 extends the frozen Stage 3.2 order.

Whenever participating:

~~~text
Run
 -> ExternalAction
 -> ToolCall
 -> ApprovalRequest
 -> ToolExecutionAttempt / ReconciliationAttempt when relevant
 -> ApprovalDecision insert
~~~

READ approval paths omit ExternalAction.

PolicyDecision, ActionSnapshot and immutable records are verified but do not define a
conflicting mutable lock order.

No Stage 3.3 transaction intentionally locks ToolCall before ExternalAction for a side-effect
mutation.

## 22. ApprovalDecision

Final human fact:

~~~text
decision = APPROVE | DENY
approver_principal_id
approver_scope
reason
redacted_evidence
created_at
~~~

One final human decision per request.

Exact replay:
- same authenticated principal;
- same decision;
- same reason/evidence

returns existing durable decision even if Run later progressed.

Any different replay is conflict.

## 23. Approval authorization

Decision requires:
- same principal_scope;
- required approver role;
- request still logically pending;
- separation-of-duties if configured.

If SoD=true, requester cannot decide own request even if holding approver role.

Identity comes from PrincipalResolver.

## 24. APPROVE READ

Transaction under canonical locks verifies:
- Run WAITING_APPROVAL;
- cancel_requested=false;
- request PENDING and not logically expired;
- digest match;
- approver authority.

Commit:

~~~text
ApprovalDecision APPROVE
ApprovalRequest APPROVED
ToolCall READY
Run QUEUED
queue_reason APPROVAL_RESOLVED
owner/lease cleared
~~~

No adapter call occurs inside approval transaction.

Later worker verifies:
- effect type READ;
- linked request APPROVED;
- request was not expired when approved;
- exact digest.

Then existing Stage 3.2 READ physical-attempt boundary applies.

## 25. APPROVE side effect

Canonical locks:

~~~text
Run
 -> ExternalAction
 -> ToolCall
 -> ApprovalRequest
~~~

Commit:

~~~text
ApprovalDecision APPROVE
ApprovalRequest APPROVED
ExternalAction AWAITING_APPROVAL -> READY
ToolCall AWAITING_APPROVAL -> READY
Run -> QUEUED(APPROVAL_RESOLVED)
~~~

ActionSnapshot and operation_id do not change.

No external adapter call occurs in approval transaction.

## 26. DENY

READ:

~~~text
request -> DENIED
ToolCall -> DENIED
Run -> FAILED
~~~

Side effect:

~~~text
request -> DENIED
ExternalAction -> ABORTED
ToolCall -> NOT_EXECUTED
Run -> FAILED
~~~

No physical attempt is created.

## 27. Cancellation

Cancellation authorization follows Section 7.

While PENDING:

READ:
- request CANCELLED;
- call NOT_EXECUTED;
- Run CANCELLED.

Side effect:
- request CANCELLED;
- action ABORTED;
- call NOT_EXECUTED;
- Run CANCELLED.

After APPROVE but before physical execution, existing Stage 3.2 cancellation fence prevents
new physical business work.

After Action Commit, cancellation remains non-rollback and Stage 3.2 truth semantics govern.

## 28. AWAITING_APPROVAL terminal guards

A Run with active PENDING ApprovalRequest or AWAITING_APPROVAL ToolCall/Action cannot:

- COMPLETED;
- be normally worker-claimed;
- start a fresh ModelInvocation;
- terminalize through unrelated ordinary failure leaving pending governance rows unstabilized.

Every terminal transition must first or atomically stabilize pending governance state to:
- DENIED;
- EXPIRED;
- CANCELLED;
- ABORTED/NOT_EXECUTED projection as applicable.

## 29. Budget accounting

- model proposal: model_invocations_used +1;
- durable governed Tool proposal: tool_call_count +1;
- PolicyDecision: no physical attempt;
- ApprovalRequest/Decision: no physical attempt;
- waiting: no physical attempt;
- each physical READ/side-effect invocation: exactly one tool_attempts_used increment in
  existing Stage 3.2 physical start transaction.

Pre-effect governance denial/expiry/cancel never consumes tool_attempts_used.

## 30. Approved READ recovery

After crash post-APPROVE:

~~~text
Run QUEUED(APPROVAL_RESOLVED)
ToolCall READY
ApprovalRequest APPROVED
no ExternalAction
~~~

Worker verifies ToolVersion effect_type=READ and exact approval binding before using the
existing READ recovery/start path.

No model reproposal and no second approval.

## 31. Approved side-effect recovery

After crash post-APPROVE:

~~~text
Run QUEUED(APPROVAL_RESOLVED)
ExternalAction READY
ToolCall READY
ActionSnapshot frozen
ApprovalRequest APPROVED
~~~

ExternalAction presence makes it unambiguously side effect.

Worker verifies approval/action digest binding, then uses a distinct approved-side-effect
eligibility path.

## 32. Destructive execution

The accepted Stage 3.2 no-approval predicate is unchanged.

Approved side-effect predicate requires:
- linked APPROVED request;
- exact ActionSnapshot digest;
- exact ExternalAction id;
- matching ToolVersion/binding;
- non-expired approval-at-decision fact;
- Run progression still permitted.

DESTRUCTIVE can reach adapter I/O only after:
- human APPROVE;
- action READY;
- Stage 3.2 Action Commit;
- STARTED ToolExecutionAttempt commit.

## 33. Approval is not business-truth resolution

Once physical side-effect attempt starts:
- approval does not prove success/failure/non-execution;
- ambiguous outcome still becomes UNKNOWN;
- reconciliation/ActionResolution remain authoritative.

An old APPROVE can never authorize blind retry of UNKNOWN.

## 34. Governed read/query authorization

For GOVERNED Run:
- GET Run requires requester or same-scope runtime:run:read:any;
- approval list/detail are same-scope and role filtered;
- mutating API rules are enforced from PrincipalContext.

LEGACY development compatibility keeps accepted Stage 3.2 API tests operational but is not
a production authorization path.

## 35. Approval evidence boundary

Reason/evidence:
- bounded size;
- restricted JSON value domain;
- redaction/forbidden secret-key checks;
- no bearer token/raw header/credential secret;
- no chain-of-thought.

Approval review projection is deterministic from durable facts.

Model prose is not authorization evidence.

## 36. Recovery precedence

For governed execution:

~~~text
unresolved external truth / reconciliation
        ↓
READY ExternalAction recovery
        ↓
READY READ recovery
        ↓
fresh model reasoning
~~~

WAITING_APPROVAL is unclaimable.

APPROVE converts pending state to an existing unambiguous READY recovery shape before claim.

## 37. Audit claim

Stage 3.3 provides durable application audit evidence:

- policy version;
- matched rule;
- requester;
- decision;
- approval request/decision;
- digests;
- operation id for side effect;
- timestamps/status events.

It does not claim cryptographically tamper-proof archival compliance.

## 38. Migration and immutable release

Migration begins after accepted Stage 3.2 head:

~~~text
0016_checkpoint_overlay
 -> Stage 3.3 migrations
~~~

Stage 3.1/3.2 migration bytes remain unchanged.

Final immutable RC must prove:
- exact ref/SHA;
- Stage 3.2 lineage hashes;
- Stage 3.2 database -> Stage 3.3 head in a new Alembic process;
- governance race matrix;
- full Python 3.14 + PostgreSQL 18 regression.

## 39. Implementation slices — freeze candidate

### 3.3-A — Identity + Policy Foundation

- PrincipalContext normalization;
- requester snapshot;
- governance mode/policy pinning;
- policy domain/lifecycle;
- evaluator;
- GovernanceIntent;
- PolicyDecision;
- legacy Stage 3.2 compatibility.

### 3.3-B — Governed ALLOW / DENY + Control-plane Auth

- policy consequence fence;
- READ ALLOW;
- no-approval side-effect ALLOW;
- DENY;
- governed create/get/cancel/resolve auth;
- exact budget accounting.

### 3.3-C — Durable Approval Intent

- WAITING_APPROVAL;
- ToolCall/ExternalAction AWAITING_APPROVAL;
- preapproval ActionSnapshot;
- ApprovalRequest;
- deterministic review projection;
- pending terminal guards;
- zero-I/O proof.

### 3.3-D — Approval Decision + Execution Bridge

- ApprovalDecision;
- approve/deny;
- SoD;
- logical/materialized expiry;
- cancel/approve races;
- approved READ recovery;
- approved side-effect/destructive eligibility;
- Action Commit preservation.

### 3.3-E — Governance Recovery / Audit Aggregate

- crash/restart matrix;
- duplicate decision races;
- scope isolation;
- policy retirement/pinning;
- secret leakage;
- Stage 3.3 aggregate acceptance.

### 3.3-F — Immutable RC

- exact lineage;
- forward migration;
- full project gate;
- immutable RC/final acceptance.

## 40. Frozen-candidate invariants

G1. Model output never grants authorization.

G2. AgentVersion governance specification is immutable.

G3. Policy may restrict but never broaden capability.

G4. Existing AgentVersions remain explicit LEGACY_STAGE32.

G5. WAITING_APPROVAL has no worker lease and no physical attempt.

G6. Side-effect approval binds exact ActionSnapshot digest/operation_id.

G7. Pending side-effect state is structurally distinct from READY recovery.

G8. Logical expiry prevents authorization even if maintenance is late.

G9. Run is root lock; side-effect child order preserves Stage 3.2.

G10. Approval grants pre-effect authority, not business-result truth.

G11. DESTRUCTIVE has no no-approval path.

G12. Approval never bypasses Stage 3.2 Action Commit.

G13. Cancellation/deadline/stale generation can still fence approved work.

G14. Principal authority comes from trusted context in GOVERNED mode.

G15. Durable audit evidence excludes secrets/model reasoning.

## 41. Gate state

~~~text
Stage 3.3 Design V0.3
✅ FREEZE CANDIDATE WRITTEN

Final Review
🔓 REQUIRED

Implementation
🔒 LOCKED
~~~

Governing rule:

> Governance decides whether an exact pre-effect intent may proceed; the durable runtime
> still decides whether and how physical execution is safe.
