# Stage 3.3 Governance — Design V0.3 Final Review

Status: **PASSED**

Reviewed freeze candidate:
- docs/design/stage3.3-governance-v0.3.md
- docs/acceptance/stage3.3-governance-acceptance-v0.3.md

Reviewed evidence:
- V0.1 Self Review
- V0.1 Scenario Validation
- V0.1 Adversarial Review
- V0.2 Re-Review
- current Stage 3.2 runtime/API compatibility surfaces

Parent baseline:
- Stage 3.2 Runtime V1.0 — ACCEPTED / FROZEN

## 1. Final verdict

The Stage 3.3 Governance V0.3 freeze candidate passes final review.

Result:

~~~text
Unresolved V0.1 blockers: 0
Unresolved V0.2 blockers: 0
New correctness blockers: 0
Unresolved major findings: 0
Scope expansion beyond reviewed boundary: 0
~~~

Implementation may be unlocked only after V1.0 frozen artifacts and design-acceptance record
are committed and read-back verified.

## 2. Core architecture closure

The final candidate establishes one coherent authority stack:

~~~text
trusted PrincipalContext
        ↓
immutable AgentVersion governance spec
        ↓
pinned immutable policy version
        ↓
deterministic PolicyDecision
        ↓
ALLOW / DENY / REQUIRE_APPROVAL
        ↓
durable approval when required
        ↓
existing Stage 3.2 execution boundary
~~~

No model output becomes authorization authority.

No approval becomes business-result truth.

## 3. V0.1 blocker closure

### Approved side-effect vs READ recovery

Closed by:

~~~text
ExternalAction AWAITING_APPROVAL
ToolCall AWAITING_APPROVAL
ActionSnapshot already frozen
~~~

After APPROVE, side effect becomes ExternalAction READY and is structurally distinct from
READ READY recovery.

### Requester identity source

Closed by immutable requester snapshot on governed Run.

### Policy assignment

Closed by immutable AgentVersion governance_mode + policy_version_id and Run copy.

### Stage 3.2 compatibility

Closed by explicit LEGACY_STAGE32 mode.

### Rule ambiguity

Closed by priority/severity/rule_id deterministic ordering.

### Capability ambiguity

Closed by explicit READ / side-effect / DESTRUCTIVE effective-outcome matrix.

### Approval identity binding

Closed by ActionSnapshot digest for side effects and GovernanceIntent digest for READ.

### Expiry

Closed by DB-time effective expiry plus maintenance materialization.

### Control-plane identity

Closed by trusted PrincipalResolver for governed mode plus isolated legacy development
compatibility.

### Destructive bridge

Closed by separate approved-side-effect eligibility; Stage 3.2 no-approval predicate remains
unchanged.

### Budget accounting

Closed by explicit logical vs physical counters.

## 4. V0.2 blocker closure

### RR-B01 — lock order

Closed.

Canonical side-effect governance order extends Stage 3.2:

~~~text
Run
 -> ExternalAction
 -> ToolCall
 -> ApprovalRequest
 -> physical/reconciliation attempt when participating
 -> ApprovalDecision insert
~~~

No reviewed side-effect mutation intentionally reverses ExternalAction/ToolCall.

### RR-B02 — API compatibility vs trusted identity

Closed.

The design explicitly separates:
- LegacyDevelopmentPrincipalResolver for frozen local/legacy compatibility; and
- trusted PrincipalResolver required for GOVERNED authority.

Caller body identity cannot authorize governed actions.

### RR-B03 — expiry sweeper dependency

Closed.

PENDING with db_now >= expires_at is logically expired even before materialization.

Therefore safety does not depend on maintenance punctuality.

### RR-B04 — policy assignment mutability

Closed.

Governance specification is immutable AgentVersion configuration.

Changing policy requires a new AgentVersion.

## 5. Security review closure

The final candidate explicitly prevents:

- model self-authorization;
- cross-scope Run/approval enumeration;
- body-supplied governed approver identity;
- self-approval when separation of duties is required;
- destructive no-approval execution;
- approval reuse as UNKNOWN retry authority;
- secret/token persistence in governance evidence;
- late approval after logical expiry;
- cancellation bypass by an earlier human approval;
- policy broadening of immutable Tool capability.

Single-resource cross-scope lookup returns 404; collection queries filter invisible records.

## 6. Stage 3.2 safety preservation

Final review rechecked that governance does not weaken:

- Run-row progression serialization;
- Stage 3.2 lock order;
- Action Commit Boundary;
- ToolExecutionAttempt-before-I/O;
- UNKNOWN before potentially duplicating retry;
- reconciliation authority;
- cancellation != rollback;
- deadline/budget fencing;
- stable operation_id;
- ActionSnapshot canonical digest;
- stale generation fencing;
- durable recovery precedence.

Especially:

> APPROVE does not call the provider.

For a side effect:

~~~text
APPROVE
 -> Action READY
 -> worker claim
 -> Action Commit
 -> Attempt STARTED
 -> commit
 -> provider I/O
~~~

## 7. State-machine closure

New states are bounded and compatible:

~~~text
Run:
RUNNING -> WAITING_APPROVAL -> QUEUED(APPROVAL_RESOLVED)

ToolCall:
CREATED/derived proposal -> AWAITING_APPROVAL
AWAITING_APPROVAL -> READY | DENIED | NOT_EXECUTED

ExternalAction:
AWAITING_APPROVAL -> READY | ABORTED
~~~

No physical attempt exists while waiting.

Pending governance must be stabilized before terminalization.

WAITING_APPROVAL is never normal worker-claimable.

## 8. Race closure

Acceptance V0.3 requires deterministic PostgreSQL coverage for:

- policy consequence vs cancellation;
- approval vs cancellation;
- approval vs logical expiry;
- approve vs deny;
- duplicate replay;
- approved continuation crash;
- stale generation;
- cancellation before/after Action Commit;
- destructive response-loss UNKNOWN;
- pending-governance terminal guards.

This is sufficient to prevent a happy-path-only approval implementation from being accepted.

## 9. Compatibility review

Existing accepted Stage 3.2 AgentVersions become LEGACY_STAGE32.

The design does not reinterpret them as governed versions.

Existing Stage 3.2 API contract may run through explicit development compatibility resolver.

Governed production behavior is separately tested and cannot use that compatibility identity
as authority.

Final RC must prove forward migration from accepted Stage 3.2 database in a new Alembic
process.

## 10. Scope review

The design remains narrower than a general IAM/policy product.

Explicitly deferred:

- OIDC/OAuth implementation;
- general policy language;
- arbitrary ABAC;
- policy-management UI;
- quorum/sequential approval workflow;
- live revocation of pinned Runs;
- adaptive model workaround after DENY;
- cryptographic audit archive.

This scope is appropriate for Stage 3.3.

## 11. Acceptance quality

Acceptance V0.3 is concrete enough to drive implementation.

It includes:
- exact state projections;
- exact capability matrix;
- exact lock order;
- canonical digest golden tests;
- real PostgreSQL races;
- restart/recovery;
- zero-I/O approval assertions;
- secret-sentinel tests;
- cross-scope non-disclosure;
- legacy compatibility regression;
- Stage 3.2 full regression;
- forward migration;
- immutable RC.

No correctness-critical behavior is left only as prose without a corresponding acceptance
surface.

## 12. Final design gate

~~~text
Stage 3.3 Governance Design V0.3
✅ FINAL REVIEW PASSED

Correctness blockers
✅ 0

Design Acceptance
✅ APPROVED FOR FREEZE

V1.0 Frozen Artifacts
🔓 MAY BE COMMITTED

Implementation
🔒 remains locked until V1.0 freeze is committed and verified
~~~

Governing final-review rule:

> Governance is accepted only because it narrows authority before execution without creating
> a competing execution truth model.
