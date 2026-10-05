# Stage 3.3-A2 — Deterministic Evaluator + GovernanceIntent + PolicyDecision

Status: **ACCEPTED / FROZEN**

Parent:
- Stage 3.3 Governance Design V1.0 — ACCEPTED / FROZEN
- Stage 3.3 Governance Acceptance Criteria V1.0 — FROZEN
- Stage 3.3-A1 — ACCEPTED / FROZEN
- Stage 3.3 implementation slices — FROZEN PLAN

Accepted semantic candidate:

`9b8a9bd45dd8f76f93a06d1ece4a2846e7043af9`

Independent acceptance trigger:

`bbb02c4195672b53baa3a1c7754e88ab543ed091`

Successful GitHub Actions run:

`37275301253`

Execution record:

`docs/execution/stage3.3-a2-execution-record.md`

## Accepted scope

Stage 3.3-A2 establishes the deterministic policy-evaluation and immutable audit substrate:

- deterministic rule matching and ordering;
- frozen capability-envelope evaluation;
- GovernanceIntent V1 canonical bytes and SHA-256 digest;
- exact requester / Run / AgentVersion / ToolVersion / proposal identity binding;
- immutable one-per-proposal PolicyDecision persistence;
- policy decision audit event;
- malformed/no-match fail closed;
- exact retired pinned policy remains evaluable by existing Runs;
- no Tool execution consequence bridge.

## Independent acceptance evidence

Workflow:
- **Stage 3.3-A2 Evaluator Intent PolicyDecision**

Successful run:
- **37275301253**

Verified gate:
- frozen Stage 3.3 lineage and A2 surface: PASS;
- frozen Stage 3.2 + A1 migration lineage unchanged: PASS;
- Stage 3.3-A1 + A2 unit contracts: PASS;
- Stage 3.3-A1 + A2 PostgreSQL 18 contracts: PASS;
- complete Stage 3.2 regression on A2 head: PASS;
- workflow conclusion: **SUCCESS**.

## Rejected candidate history

1. Run `37274722249`
   - unit: PASS;
   - PostgreSQL fixture failed before decision semantics due to FK insert ordering.

2. Run `37274891436`
   - unit: PASS;
   - PostgreSQL: PASS;
   - rejected on three Ruff E501 findings.

3. Run `37275054761`
   - unit: PASS;
   - PostgreSQL: PASS — 7 passed;
   - Ruff lint: PASS;
   - rejected on Ruff formatter normalization only.

Candidate #4 passed the complete gate.

## Frozen A2 invariants

### A2-I1 — Deterministic rule selection

Matching rules are selected exactly by:
1. priority descending;
2. DENY > REQUIRE_APPROVAL > ALLOW;
3. rule_id ascending.

Empty match dimensions are wildcards.

No match -> DENY.

Malformed policy -> fail closed.

### A2-I2 — Capability envelope

Policy cannot broaden immutable Tool capability.

- READ follows DENY / approval-required / ALLOW rules;
- WRITE and EXTERNAL_SIDE_EFFECT require no-approval capability before effective ALLOW;
- DESTRUCTIVE can never effective-ALLOW.

### A2-I3 — GovernanceIntent V1

GovernanceIntent binds:
- Run;
- AgentVersion;
- proposal;
- ToolVersion;
- effect type;
- exact canonical arguments;
- normalized requester;
- principal scope.

It reuses the frozen Stage 3.2 canonical JSON rules:
- Unicode scalar validation;
- safe integer bounds;
- float rejection;
- deterministic RFC-8785-compatible object ordering.

Credential/secret sentinel material is excluded.

### A2-I4 — Immutable PolicyDecision

One immutable PolicyDecision exists per governed proposal.

It binds:
- exact Run;
- exact proposal;
- exact ToolVersion;
- exact pinned policy version;
- exact requester;
- principal scope;
- effective decision;
- matched rule id when present;
- GovernanceIntent digest.

Database mutation of persisted GovernanceIntent/PolicyDecision is rejected.

### A2-I5 — Durable facts are revalidated before persistence

The PostgreSQL decision store:
- reconstructs GovernanceIntent from durable Run/proposal/ToolVersion facts;
- reconstructs the exact pinned policy;
- re-evaluates the deterministic decision;
- rejects caller-supplied intent/evaluation that differs from durable truth.

### A2-I6 — Audit evidence is not execution authority

Evaluation and PolicyDecision persistence create:
- zero ToolCall;
- zero ToolExecutionAttempt;
- zero adapter I/O.

A2 does not bridge ALLOW, DENY or REQUIRE_APPROVAL into runtime execution consequences.

## Freeze boundary

A2 is frozen.

Stage 3.3-A Aggregate may only independently re-run and verify A1+A2 plus complete Stage 3.2
compatibility. It may not introduce new runtime semantics.

Stage 3.3-B remains locked until A Aggregate is independently accepted.

## Gate

~~~text
Stage 3.3-A1
✅ ACCEPTED / FROZEN

Stage 3.3-A2
✅ ACCEPTED / FROZEN

Stage 3.3-A Aggregate
🔓 UNLOCKED

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

Governing rule:

> A durable deterministic PolicyDecision is audit evidence; it is not yet physical execution
> authority.
