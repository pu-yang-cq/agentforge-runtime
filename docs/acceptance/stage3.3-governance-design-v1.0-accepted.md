# Stage 3.3 Governance Design V1.0 — ACCEPTED / FROZEN

Status: **ACCEPTED / FROZEN**

Parent runtime baseline:
- Stage 3.2 Runtime V1.0 — ACCEPTED / FROZEN
- immutable release branch: rc/stage3.2-v1.0-r2
- immutable release SHA: fa747268cfbf1d5b57e5796b9cbc767abc3d4e0c
- final Stage 3.2 gate: 37262139363

Process contract:
- docs/execution/verified-execution-protocol-v1.0.md

## 1. Frozen artifacts

Authoritative Design V1.0:

- file: docs/design/stage3.3-governance-v1.0-frozen.md
- freeze commit: 9909bfcc9fea2cdfdf4b8d6a5fd19efbea3a3d29
- verified blob: 85a0c462676415f0a7a7977bea027b152e8203af

Authoritative Acceptance Criteria V1.0:

- file: docs/acceptance/stage3.3-governance-acceptance-v1.0-frozen.md
- initial freeze commit: 029f76ecc32fdac7c3803c2c584019e7687f56aa
- frozen-design provenance correction: cc5f738267e1cb33092003106c78bcfbf0bd0a8d
- verified final blob: eb42fa46b120ba7b17eec3b380650f127714c298

No runtime implementation is included in this design acceptance.

## 2. Review chain

The design followed the same gated method used for Stage 3.2:

~~~text
Design V0.1
  ↓
Acceptance V0.1
  ↓
Self Review
  ↓
Scenario Validation
  ↓
Adversarial Review
  ↓
Corrective Design V0.2
  ↓
Acceptance V0.2
  ↓
V0.2 Re-Review
  ↓
Corrective Design V0.3
  ↓
Acceptance V0.3
  ↓
Final Clarification
  ↓
Final Review
  ↓
Design V1.0 Freeze
  ↓
Acceptance V1.0 Freeze
~~~

Evidence:

- docs/design/stage3.3-governance-v0.1.md
- docs/acceptance/stage3.3-governance-acceptance-v0.1.md
- docs/reviews/stage3.3-governance-v0.1-self-review.md
- docs/validation/stage3.3-governance-v0.1-scenario-validation.md
- docs/reviews/stage3.3-governance-v0.1-adversarial-review.md
- docs/design/stage3.3-governance-v0.2.md
- docs/acceptance/stage3.3-governance-acceptance-v0.2.md
- docs/reviews/stage3.3-governance-v0.2-re-review.md
- docs/design/stage3.3-governance-v0.3.md
- docs/acceptance/stage3.3-governance-acceptance-v0.3.md
- docs/reviews/stage3.3-governance-v0.3-final-review.md

## 3. Review results

V0.1 Self Review:

~~~text
Blockers:       11
Major:           8
Clarifications:  4
Verdict: NOT ACCEPTED
~~~

V0.1 Scenario Validation:

~~~text
PASS:    5
PARTIAL: 5
FAIL:    7
Verdict: NOT ACCEPTED
~~~

V0.1 Adversarial Review:

~~~text
Core ideas survive:             9
Scope cuts required:            7
Architecture corrections:      10
Explicit deferrals:             8
Verdict: NOT ACCEPTED
~~~

V0.2 Re-Review:

~~~text
Remaining Blockers:       4
Remaining Major:          6
Clarifications:           3
Verdict: NOT YET ACCEPTED
~~~

V0.3 Final Review:

~~~text
Unresolved V0.1 blockers:                  0
Unresolved V0.2 blockers:                  0
New correctness blockers:                 0
Unresolved major findings:                0
Scope expansion beyond reviewed boundary: 0

Verdict: PASSED
~~~

## 4. Critical design corrections made before freeze

### 4.1 Approved side effects cannot collide with READ recovery

V0.1 would have produced a READY ToolCall with no ExternalAction after approval.

That could be mistaken for Stage 3.2 READ recovery.

The frozen design instead uses:

~~~text
before approval:
ToolCall AWAITING_APPROVAL
ExternalAction AWAITING_APPROVAL
ActionSnapshot frozen
operation_id stable

after approval:
ToolCall READY
ExternalAction READY
~~~

The durable ExternalAction makes the recovery class unambiguous.

### 4.2 Side-effect approval binds Stage 3.2 ActionSnapshot

The frozen design does not create a second competing side-effect truth model.

Human approval binds:
- GovernanceIntent digest;
- ActionSnapshot digest;
- exact ExternalAction id;
- stable operation_id already present in ActionSnapshot.

Approval therefore freezes the exact pre-effect action that later enters Stage 3.2.

### 4.3 Existing Stage 3.2 behavior is explicit legacy compatibility

Existing AgentVersions are migrated to:

~~~text
governance_mode = LEGACY_STAGE32
governance_policy_version_id = NULL
~~~

New governance semantics require GOVERNED AgentVersion.

No existing AgentVersion silently gains destructive approval capability or changes runtime
authorization behavior.

### 4.4 Governance policy assignment is immutable execution specification

For GOVERNED AgentVersion:
- exact published GovernancePolicyVersion is immutable;
- changing policy for future work requires a new AgentVersion;
- governed Run copies exact policy version id.

Runtime authorization therefore remains reproducible after restart or policy retirement.

### 4.5 Trusted identity is separated from legacy API compatibility

GOVERNED authority comes from a trusted PrincipalResolver.

Caller-supplied resolver/approver strings cannot grant governed authority.

A clearly named LegacyDevelopmentPrincipalResolver may preserve the accepted Stage 3.2 local
API regression contract, but cannot authorize a GOVERNED Run.

### 4.6 Logical expiry does not depend on maintenance punctuality

For a PENDING approval:

~~~text
DB now >= expires_at
=> logically expired
=> cannot authorize progression
~~~

expire_due_approvals(limit) materializes durable EXPIRED state; it is not the safety source.

### 4.7 One global lock order is preserved

Stage 3.3 extends the Stage 3.2 lock order:

~~~text
Run
 -> ExternalAction when present
 -> ToolCall
 -> ApprovalRequest
 -> ToolExecutionAttempt / ReconciliationAttempt when participating
 -> ApprovalDecision insert
~~~

No separate governance lock hierarchy may invert the established side-effect order.

### 4.8 DESTRUCTIVE has no no-approval path

DESTRUCTIVE effective result is:
- DENY; or
- REQUIRE_APPROVAL.

Even after APPROVE, physical I/O still requires the Stage 3.2 Action Commit transaction and a
durable STARTED ToolExecutionAttempt.

### 4.9 Approval does not resolve execution uncertainty

After a physical side-effect attempt:

~~~text
APPROVED
  +
ambiguous provider outcome
  ≠
safe retry authority
~~~

UNKNOWN/reconciliation/ActionResolution remain Stage 3.2 authority.

### 4.10 Cross-scope resource existence is not disclosed

For GOVERNED APIs:
- cross-scope single-resource lookup -> 404;
- collection/list filters invisible entries;
- visible same-scope mutation without required role -> 403.

## 5. Frozen architecture

The accepted authority chain is:

~~~text
trusted PrincipalContext
        ↓
immutable AgentVersion governance specification
        ↓
pinned immutable GovernancePolicyVersion
        ↓
deterministic PolicyDecision
        ↓
ALLOW | DENY | REQUIRE_APPROVAL
        ↓
if approval required:
  durable exact pre-effect intent
  + authorized ApprovalDecision
        ↓
Stage 3.2 durable execution pipeline
        ↓
Action Commit / ToolExecutionAttempt
        ↓
physical I/O
~~~

## 6. Frozen core invariants

### G-I1
Model output never grants authorization.

### G-I2
AgentVersion governance specification is immutable.

### G-I3
Policy may restrict but never broaden Tool capability.

### G-I4
Existing AgentVersions remain explicit LEGACY_STAGE32.

### G-I5
WAITING_APPROVAL has no worker lease and no physical Tool attempt.

### G-I6
Side-effect approval binds exact ActionSnapshot digest and stable operation_id.

### G-I7
Pending side-effect state is structurally distinct from READY READ recovery.

### G-I8
Logical expiry blocks authorization even if maintenance is late.

### G-I9
Run remains the root lock and Stage 3.2 side-effect child order is preserved.

### G-I10
Approval grants pre-effect authority; it does not establish business-result truth.

### G-I11
DESTRUCTIVE has no no-approval execution path.

### G-I12
Approval never bypasses Stage 3.2 Action Commit.

### G-I13
Cancellation, deadline and stale generation can still fence approved work.

### G-I14
Governed principal authority comes only from trusted PrincipalContext.

### G-I15
Governance audit evidence excludes secrets, auth tokens and model reasoning.

## 7. Frozen acceptance envelope

Implementation cannot be accepted without proving:

- exact Stage 3.2 regression;
- legacy/governed compatibility isolation;
- deterministic policy evaluation;
- canonical GovernanceIntent;
- immutable ActionSnapshot approval binding;
- zero I/O while waiting approval;
- WAITING_APPROVAL claim isolation;
- approve/deny/cancel/expiry races under real PostgreSQL;
- logical expiry independent of sweeper timing;
- exact budget accounting;
- approved READ recovery;
- approved side-effect recovery;
- destructive approval chain;
- approval cannot resolve UNKNOWN;
- principal/scope isolation;
- secret-sentinel isolation;
- governed API non-disclosure;
- Stage 3.2 -> Stage 3.3 forward migration in a new Alembic process;
- Python 3.14 + PostgreSQL 18 full gate;
- immutable final RC.

## 8. Frozen scope boundary

Stage 3.3 V1.0 does not build:

- authentication protocol implementation;
- general IAM;
- arbitrary ABAC;
- OPA/Rego/Cedar policy language;
- policy-management UI/general CRUD API;
- quorum or sequential approval chains;
- live revocation of already pinned Runs;
- adaptive model replanning after DENY;
- cryptographic/WORM audit archive;
- generic workflow/DAG engine.

## 9. Design acceptance state

~~~text
Stage 3.2 Runtime V1.0
✅ ACCEPTED / FROZEN

Stage 3.3 Governance Design V1.0
✅ ACCEPTED / FROZEN

Stage 3.3 Implementation
🔓 UNLOCKED AFTER THIS ACCEPTANCE RECORD IS VERIFIED

Stage 3.3 Runtime Acceptance
🔒 LOCKED

Stage 3.3 Final RC
🔒 LOCKED
~~~

Governing design rule:

> Governance decides whether an exact pre-effect intent may proceed; the accepted Stage 3.2
> runtime still decides whether and how physical execution is safe.
