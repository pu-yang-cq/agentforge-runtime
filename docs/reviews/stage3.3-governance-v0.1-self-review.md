# Stage 3.3 Governance — Design V0.1 Self-Review

Status: **SELF-REVIEW COMPLETE — V0.1 NOT ACCEPTED**

Reviewed:
- docs/design/stage3.3-governance-v0.1.md
- docs/acceptance/stage3.3-governance-acceptance-v0.1.md

Parent baseline:
- Stage 3.2 Runtime V1.0 — ACCEPTED / FROZEN

This review intentionally does not edit V0.1. Scenario validation and adversarial review
must evaluate the same unmodified draft.

## 1. Executive result

V0.1 has the correct product direction but is not implementation-safe yet.

Finding count:

- Blocker: 11
- Major: 8
- Clarification: 4

Implementation remains locked.

Strong ideas that should survive revision:

1. deterministic policy, never model authorization;
2. policy may restrict but never broaden ToolVersion capability;
3. WAITING_APPROVAL has no worker lease;
4. approval is durable and auditable;
5. destructive operations require approval;
6. approval never bypasses Stage 3.2 Action Commit;
7. Run remains the progression serialization point;
8. approval/cancellation/deadline races are explicit;
9. exact intent binding is required;
10. immutable RC and Stage 3.2 forward migration remain final gates.

## 2. Blockers

### SR-B01 — Approved side-effect READY collides with Stage 3.2 READ recovery

V0.1 says APPROVE transitions:

~~~text
ToolCall AWAITING_APPROVAL -> READY
Run -> QUEUED(APPROVAL_RESOLVED)
~~~

but side-effect ExternalAction is not created until the later worker resumes.

Stage 3.2 currently identifies a READY READ recovery candidate partly by the absence of an
ExternalAction.

Therefore an approved side-effect ToolCall READY with no ExternalAction can be mistaken for
a READ ToolCall.

This is a correctness blocker.

Revision must use an unambiguous durable approved state or persist side-effect action identity
before approval.

Possible directions:

1. introduce ToolCall AUTHORIZED and consume it into the effect-specific Stage 3.2 path; or
2. for side effects persist ActionSnapshot + ExternalAction AWAITING_APPROVAL before wait.

The revised design must choose one exact model.

### SR-B02 — Requester principal authority is not durably sourced

V0.1 defines PrincipalContext but does not say where the Tool proposal requester identity
comes from after a Run has survived worker restart.

It cannot come from:
- the current worker;
- the model;
- a transient HTTP request that no longer exists.

The Run must durably bind the initiating principal/tenant context or reference an immutable
execution principal snapshot.

### SR-B03 — Governance policy assignment/pinning source is undefined

V0.1 says a Run uses one pinned GovernancePolicyVersion but does not define:

- whether AgentVersion owns the policy assignment;
- whether create_run selects it;
- whether Run copies the version id;
- what happens for pre-Stage-3.3 AgentVersions;
- whether a retired policy remains valid for an existing Run.

Without this, deterministic replay/recovery is impossible.

### SR-B04 — Stage 3.2 regression compatibility is contradicted by default DENY

V0.1 uses default DENY when no policy rule grants authority.

Existing accepted Stage 3.2 fixtures/AgentVersions do not have a Stage 3.3 policy assignment.

A naive implementation would cause the required Stage 3.2 regression gate to fail.

Revision needs an explicit migration/compatibility plan, such as:
- assigning an immutable compatibility policy to migrated existing AgentVersions; or
- a precisely scoped legacy policy behavior that cannot apply to new Stage 3.3 versions.

Silent global allow is not acceptable.

### SR-B05 — Policy rule evaluation semantics are underspecified

V0.1 gives outcome precedence but not a complete deterministic rule algorithm.

Undefined:
- multiple matching rules with same outcome;
- multiple roles;
- rule priority;
- wildcard matching;
- conflicting tenant/tool/agent match;
- deterministic matched rule_id;
- malformed rule handling.

A governance system cannot leave these to implementation interpretation.

### SR-B06 — WRITE capability branch is ambiguous

V0.1 says policy ALLOW with allow_no_approval_execution=false becomes
“REQUIRE_APPROVAL or DENY according to capability eligibility”.

No separate durable capability currently says whether approval execution is permitted.

The design must explicitly define the capability envelope:

- which effect types can be approval-authorized;
- whether approval_required=false means “approval optional” or “approval forbidden”;
- how DESTRUCTIVE differs.

### SR-B07 — Approval digest does not define side-effect identity strongly enough

V0.1 GovernanceIntent does not include ActionSnapshot digest/operation_id because the action
is created after approval.

This is potentially valid, but Stage 3.2 deliberately created a canonical ActionSnapshot
digest partly to support future approval binding.

The design must decide whether human approval binds:

- semantic Tool intent only; or
- the exact ActionSnapshot including operation_id.

The choice affects replay, audit, and the approved-side-effect recovery model.

### SR-B08 — Deadline/expiry scheduler is not concrete

V0.1 says expiry is handled by an explicit durable maintenance path but does not define:

- how due approvals are selected;
- lock order;
- whether approval expires_at is capped by Run.deadline_at;
- crash/restart behavior;
- competing expiry vs approve ordering.

A WAITING_APPROVAL Run could otherwise remain stuck forever past its deadline.

### SR-B09 — Existing control-plane APIs remain unauthenticated

Stage 3.3 introduces trusted PrincipalContext for approvals, but current APIs also include:

- create Run;
- cancel Run;
- manually resolve ExternalAction.

The current manual resolution request body can supply resolver_identity directly.

A Governance stage cannot claim meaningful principal authority while leaving these
control-plane mutations outside the trust model.

Revision must define authorization for existing mutating APIs or explicitly limit the
product claim.

### SR-B10 — Approved destructive execution bridge is underspecified

Stage 3.2 intentionally rejects DESTRUCTIVE from its no-approval executable path.

V0.1 says approved DESTRUCTIVE enters the Stage 3.2 side-effect pipeline, but does not define
the new coordinator/recorder eligibility rule that permits it only when a durable approval
grant is present.

A generic change to stage32_side_effect_executable would be unsafe.

The revised design must require a separate approved-execution capability check that cannot
be reached without durable approval evidence.

### SR-B11 — Budget/accounting semantics around governance are incomplete

V0.1 does not define how these counters behave:

- model_invocations_used;
- tool_call_count;
- tool_attempts_used.

Required distinction:

- model proposal consumes model invocation;
- durable governed ToolCall should count as logical ToolCall;
- waiting/approval decision must not consume a physical Tool attempt;
- first physical invocation after approval consumes tool_attempts_used exactly once.

Without this, budgets can be bypassed or double-counted.

## 3. Major findings

### SR-M01 — Policy lifecycle mutability contradicts “immutable version”

V0.1 calls GovernancePolicyVersion immutable but includes DRAFT / PUBLISHED / RETIRED status.

Clarify that rule content/version identity becomes immutable after publish while lifecycle
metadata may transition under constrained rules.

### SR-M02 — Run tenant identity is not a first-class durable fact

V0.1 uses tenant_scope in PrincipalContext and acceptance expects tenant isolation, but Run
schema/source semantics are not defined.

Tenant scope must be durable if it participates in authorization.

### SR-M03 — Approval TTL source is unspecified

Need an exact source for:
- required approver role;
- separation_of_duties;
- approval TTL.

These should derive from the matched immutable policy rule and be frozen onto ApprovalRequest.

### SR-M04 — Approval after deadline has ambiguous request state

V0.1 permits recording ApprovalDecision APPROVE after deadline while also denying execution.

Need exact ApprovalRequest status and event semantics:
- APPROVED but runtime-blocked; or
- EXPIRED and operator evidence separate.

### SR-M05 — Audit evidence redaction contract is too vague

Approval evidence is structured input but no restricted value domain / size limit /
secret-key rejection is specified.

A governance audit surface should not become a secret sink.

### SR-M06 — Policy administration surface is absent

Runtime semantics can be tested with seeded policy versions, but the design must state
whether policy create/publish/assignment API is:
- in Stage 3.3; or
- explicitly deferred.

Without that statement, “Control Plane” scope is unclear.

### SR-M07 — Claim/recovery ordering needs approved-intent state

V0.1 lists “approved governance continuation” after READ recovery, but no durable query shape
identifies it.

Once SR-B01 is fixed, recovery precedence must name the exact state/table used.

### SR-M08 — Approval request visibility/listing authorization is unspecified

GET /v1/approvals cannot be globally visible.

List/get must be tenant- and role-scoped.

## 4. Clarifications

### SR-C01 — Policy retirement semantics

A retired policy should likely block new Run pinning but remain readable/reproducible for
already pinned Runs. Must be explicit.

### SR-C02 — DENY terminal policy

V0.1 intentionally fails the Run on governance denial. Keep or revise, but record this as a
product choice rather than an incidental implementation behavior.

### SR-C03 — READ approval result delivery

After an approved READ succeeds, normal Stage 3.2 Tool message/model continuation should
resume. Spell out that approval itself does not create a TOOL message.

### SR-C04 — Approval is not ActionResolution

The design says approval cannot resolve UNKNOWN; this should become a first-class invariant
and a schema/API separation rule.

## 5. Required scenario validation focus

Scenario validation must stress at least:

1. approved WRITE side effect after restart;
2. approved READ after restart;
3. cancellation while waiting;
4. approval vs expiry;
5. approval after deadline;
6. destructive operation approval;
7. policy DENY vs cancel race;
8. duplicate approvers;
9. same requester as approver with SoD;
10. policy version retirement after Run creation;
11. migrated Stage 3.2 AgentVersion;
12. action becomes UNKNOWN after an approved destructive request.

## 6. Gate state

~~~text
Stage 3.3 Design V0.1
❌ NOT ACCEPTED

Self Review
✅ COMPLETE

Scenario Validation
🔓 NEXT

Adversarial Review
🔒 pending scenario validation

Implementation
🔒 LOCKED
~~~

Governing review rule:

> Governance may add authorization authority, but it must not create a second ambiguous
> execution state machine beside the accepted Stage 3.2 runtime.
