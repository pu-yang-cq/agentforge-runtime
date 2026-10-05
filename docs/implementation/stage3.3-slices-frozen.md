# Stage 3.3 Governance — Implementation Slices — FROZEN PLAN

Status: **IMPLEMENTATION PLAN FROZEN**

Frozen parents:
- docs/design/stage3.3-governance-v1.0-frozen.md
- docs/acceptance/stage3.3-governance-acceptance-v1.0-frozen.md
- docs/acceptance/stage3.3-governance-design-v1.0-accepted.md
- Stage 3.2 Runtime V1.0 immutable RC2

Process:
- docs/execution/verified-execution-protocol-v1.0.md

Stage 3.3 Runtime Acceptance remains locked until every slice and aggregate gate below is
accepted.

## 1. Gate discipline

Every implementation slice follows:

~~~text
frozen slice contract
        ↓
implementation candidate
        ↓
target gate
        ↓
GitHub read-back verification
        ↓
independent acceptance
        ↓
GitHub read-back verification
        ↓
freeze record
        ↓
next slice unlocked
~~~

A failed candidate:
- remains rejected;
- does not unlock later work;
- is recorded with Run ID / failed step / root cause;
- may receive diagnostic-only workflows without changing acceptance state.

Correctness-affecting deviation from Governance Design V1.0 requires design amendment and
re-review before implementation acceptance.

## 2. Stage 3.3-A — Identity + Policy Foundation

Purpose:
create durable governance identity/policy facts without yet changing Tool execution behavior
for GOVERNED Runs.

### A1 — Governance compatibility + identity/policy schema

Scope:
- GovernanceMode LEGACY_STAGE32 / GOVERNED;
- PrincipalType;
- normalized PrincipalContext domain;
- requester snapshot durable Run fields;
- GovernancePolicyVersion durable schema/lifecycle;
- bounded rule schema;
- immutable AgentVersion governance_mode + policy_version_id;
- Stage 3.2 existing AgentVersion backfill to LEGACY_STAGE32;
- policy publish/retire repository operations sufficient for test/admin bootstrap;
- migration from 0016 without rewriting accepted Stage 3.2 migrations;
- LegacyDevelopmentPrincipalResolver contract;
- no model Tool governance enforcement yet.

A1 target acceptance must prove:
- Stage 3.2 full regression;
- exact legacy backfill;
- GOVERNED requires published policy;
- immutable AgentVersion policy assignment;
- principal normalization;
- trusted vs legacy resolver isolation at domain/application boundary;
- Stage 3.2 migration hashes unchanged.

### A2 — Deterministic evaluator + GovernanceIntent + PolicyDecision

Scope:
- deterministic rule matcher/order;
- capability-envelope evaluator;
- GovernanceIntent V1 canonical bytes/digest;
- immutable PolicyDecision persistence;
- policy decision audit events;
- fail-closed malformed/no-match behavior;
- no Tool execution behavior bridge yet.

A2 target acceptance must prove:
- golden deterministic policy selection;
- canonical intent digest vectors;
- secret-sentinel exclusion;
- policy cannot broaden Tool capability;
- DESTRUCTIVE cannot effective-ALLOW;
- exact policy/requester/tool/run identity in PolicyDecision;
- no physical Tool attempt created merely by evaluation.

### A aggregate

Independent Stage 3.3-A acceptance re-runs:
- A1;
- A2;
- complete Stage 3.2 regression;
- migration/compatibility evidence.

Only after A aggregate is green does B unlock.

## 3. Stage 3.3-B — Governed ALLOW / DENY + Control-plane Authorization

Scope:
- integrate deterministic policy consequence into model Tool proposal path;
- preserve Stage 3.2 ModelInvocation consequence fencing;
- governed READ ALLOW;
- governed no-approval WRITE / EXTERNAL_SIDE_EFFECT ALLOW;
- DENY fail-closed;
- exact logical/physical budget accounting;
- trusted PrincipalContext on governed create/get/cancel/action-resolution;
- explicit legacy API compatibility adapter;
- cross-scope non-disclosure;
- no WAITING_APPROVAL behavior yet.

B must not:
- add approval waiting;
- add DESTRUCTIVE execution;
- weaken stage32_side_effect_executable.

Acceptance focus:
- ALLOW still crosses Stage 3.2 physical boundaries;
- DENY performs zero I/O;
- cancellation/deadline/stale generation can discard governance consequence;
- no body-supplied governed authority;
- legacy Stage 3.2 API tests remain green.

## 4. Stage 3.3-C — Durable Approval Intent

Scope:
- Run WAITING_APPROVAL;
- ToolCall AWAITING_APPROVAL;
- ExternalAction AWAITING_APPROVAL;
- ApprovalRequest PENDING;
- READ preapproval GovernanceIntent binding;
- side-effect preapproval ActionSnapshot + stable operation_id;
- ApprovalRequest binding to exact ActionSnapshot digest;
- deterministic approval review projection;
- effective expires_at;
- pending terminal guards;
- worker claim isolation.

C stops before human decision/resume.

Acceptance focus:
- one transaction creates pending governance state;
- owner/lease cleared;
- zero ToolExecutionAttempt;
- zero adapter I/O;
- pending side effect cannot be READ-recovery candidate;
- Action Commit cannot select AWAITING_APPROVAL;
- WAITING_APPROVAL survives restart and is unclaimable.

## 5. Stage 3.3-D — Approval Decision + Approved Execution Bridge

Scope:
- ApprovalDecision;
- approve/deny API/application commands;
- same-scope role checks;
- separation of duties;
- exact replay/idempotency/conflict;
- logical expiry;
- expire_due_approvals(limit);
- cancellation vs approval/expiry;
- approved READ recovery;
- approved WRITE/EXTERNAL_SIDE_EFFECT recovery;
- approved DESTRUCTIVE execution predicate;
- Stage 3.2 Action Commit preservation.

Acceptance focus:
- approve transaction performs zero adapter I/O;
- approved READ gets one physical attempt later;
- approved side effect reuses frozen ActionSnapshot/operation_id;
- DESTRUCTIVE requires durable ApprovalDecision;
- no Stage 3.2 no-approval predicate broadening;
- cancellation/expiry/deadline/stale generation still fence work;
- approval never resolves UNKNOWN.

## 6. Stage 3.3-E — Governance Recovery / Audit Aggregate

Scope:
- full governed restart/recovery matrix;
- real PostgreSQL approve/cancel/expire/deny races;
- duplicate decision races;
- stale generation races;
- policy pinning/retirement recovery;
- cross-scope isolation;
- audit projection;
- secret/token sentinel leakage tests;
- pending terminal guards;
- destructive response-loss -> UNKNOWN/reconciliation regression;
- Stage 3.3 aggregate acceptance.

Mandatory deterministic race matrix includes at least the 18 frozen Acceptance V1.0 cases.

E aggregate must re-run:
- all A/B/C/D frozen acceptance;
- Stage 3.2 full recovery/crash matrix;
- full Python 3.14 + PostgreSQL 18 regression.

## 7. Stage 3.3-F — Immutable RC + Final Acceptance

Scope:
- pin exact Stage 3.3 candidate SHA;
- create immutable RC ref;
- hash/prove accepted Stage 3.1 + Stage 3.2 migration lineage unchanged;
- real forward migration:
  accepted Stage 3.2 database -> new Alembic process -> Stage 3.3 head;
- run governance race matrix against exact RC;
- run complete Python 3.14 + PostgreSQL 18 gate against exact RC;
- preserve rejected RCs rather than moving them;
- freeze Stage 3.3 Runtime V1.0 only after all gates pass.

Acceptance belongs to immutable RC SHA, not mutable main.

## 8. Slice dependency graph

~~~text
Stage 3.3 Design V1.0
✅ FROZEN
      ↓
A1 Identity / Compatibility / Policy Schema
      ↓
A2 Evaluator / Intent / PolicyDecision
      ↓
A Aggregate
      ↓
B ALLOW / DENY + Control-plane Auth
      ↓
C Durable Approval Intent
      ↓
D Approval Decision + Execution Bridge
      ↓
E Recovery / Audit + Aggregate
      ↓
F Immutable RC
      ↓
Stage 3.3 Runtime V1.0
~~~

No later slice may be implemented early to make an earlier slice easier to pass.

## 9. Current gate

~~~text
Stage 3.3 Governance Design V1.0
✅ ACCEPTED / FROZEN

Implementation Plan
✅ FROZEN

Stage 3.3-A1
✅ ACCEPTED / FROZEN

Stage 3.3-A2
🔓 UNLOCKED

Stage 3.3-A Aggregate
🔒 LOCKED

Stage 3.3-B
🔒 LOCKED

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

Governing implementation rule:

> First make governance identity and policy facts deterministic; only then let them influence
> runtime execution.
