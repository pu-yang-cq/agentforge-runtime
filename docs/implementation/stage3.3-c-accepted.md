# Stage 3.3-C — Durable Approval Intent

Status: **ACCEPTED / FROZEN**

Parents:
- Stage 3.3 Governance Design V1.0 — ACCEPTED / FROZEN
- Stage 3.3 Governance Acceptance Criteria V1.0 — FROZEN
- Governance Amendment 001 — ACCEPTED / FROZEN
- Stage 3.3-B — ACCEPTED / FROZEN
- Stage 3.3 implementation slices — FROZEN PLAN

Accepted semantic candidate:

`400336d6086c550039626f6717b6401410cc8e3b`

Independent acceptance trigger:

`165cce2b98a3143bef52b73226e240ce2fe25db2`

Successful GitHub Actions run:

`37329756162`

Execution record:

`docs/execution/stage3.3-c-execution-record.md`

## Accepted scope

Stage 3.3-C establishes durable approval intent without implementing approval decision or
approved execution.

Accepted behavior includes:
- Run WAITING_APPROVAL;
- ToolCall AWAITING_APPROVAL;
- ExternalAction AWAITING_APPROVAL for side effects;
- ApprovalRequest PENDING;
- READ request binding to exact GovernanceIntent digest;
- side-effect request binding to exact GovernanceIntent + ActionSnapshot + ExternalAction +
  stable operation_id;
- DB-time effective expiry bounded by Run.deadline_at;
- zero ToolExecutionAttempt while pending;
- zero adapter I/O while pending;
- owner/lease clearing;
- worker claim isolation;
- restart durability;
- pending cancellation stabilization;
- deterministic approval review projection from durable facts;
- canonical identity revalidation;
- preservation of Stage 3.2 physical execution fences.

## Independent acceptance evidence

Workflow:
- **Stage 3.3-C Durable Approval Intent**

Successful run:
- **37329756162**

Trigger head:
- `165cce2b98a3143bef52b73226e240ce2fe25db2`

Verified gate:
- frozen Stage 3.3 lineage and C surface: PASS;
- accepted Stage 3.2 + A1 + A2 migration lineage unchanged: PASS;
- Stage 3.3-C unit contracts: PASS;
- Stage 3.3-C PostgreSQL contracts: PASS;
- no Stage 3.3-D approval decision/resume implementation: PASS;
- complete Stage 3.2 regression: PASS;
- workflow conclusion: **SUCCESS**.

## Rejected candidate history

1. Run `37328632050`
   - C unit/PostgreSQL/no-D guard: PASS;
   - rejected only on Ruff formatter normalization in three C3 files.

2. Run `37329148579`
   - C unit/PostgreSQL/no-D guard: PASS;
   - Ruff lint/format: PASS;
   - rejected only on one mypy type-narrowing issue.

Candidate #3 passed the complete gate.

## Frozen C invariants

### C-I1 — Pending approval is durable and unowned

A successful approval-pending consequence moves the Run to WAITING_APPROVAL and clears:
- owner_worker_id;
- lease_expires_at;
- queue_reason;
- available_at.

WAITING_APPROVAL is not a normal worker claim candidate.

### C-I2 — Pending approval has zero physical authority

Before approval is decided:
- zero ToolExecutionAttempt exists for the pending ToolCall;
- no adapter I/O occurs;
- READ recovery cannot select the pending call;
- Action Commit cannot select AWAITING_APPROVAL ExternalAction.

### C-I3 — READ approval binding

READ pending approval persists:
- exact GovernanceIntent digest;
- exact PolicyDecision;
- exact ToolCall;
- ApprovalRequest PENDING.

It does not create ExternalAction or ActionSnapshot.

### C-I4 — Side-effect approval binding

WRITE / EXTERNAL_SIDE_EFFECT / DESTRUCTIVE pending approval persists:
- exact GovernanceIntent digest;
- immutable ActionSnapshot;
- stable operation_id;
- ExternalAction AWAITING_APPROVAL;
- ApprovalRequest PENDING bound to ExternalAction id and ActionSnapshot digest.

The ActionSnapshot is the only later executable side-effect identity.

### C-I5 — Approval authority provenance

Every effective REQUIRE_APPROVAL uses approval metadata from the exact selected immutable policy
rule under frozen Governance Amendment 001.

Missing metadata fails closed as DENY.

Runtime never invents approver role, separation-of-duties rule or TTL.

### C-I6 — Effective expiry

ApprovalRequest expires_at is calculated from DB time as:

`min(created_at + policy ttl, Run.deadline_at)`

If the DB clock has already reached Run.deadline_at before request creation, the transaction
fails closed with DEADLINE_EXCEEDED rather than persisting an invalid request.

### C-I7 — Pending cancellation stabilization

Cancellation of WAITING_APPROVAL is atomic.

For READ:
- ApprovalRequest -> CANCELLED;
- ToolCall -> NOT_EXECUTED;
- Run -> CANCELLED.

For side effect:
- ApprovalRequest -> CANCELLED;
- ExternalAction -> ABORTED;
- ToolCall -> NOT_EXECUTED;
- Run -> CANCELLED.

No ToolExecutionAttempt or adapter I/O is created.

The lock order is:
Run -> ExternalAction when present -> ToolCall -> ApprovalRequest.

### C-I8 — Restart / stale-executor fencing

WAITING_APPROVAL survives process restart as durable state.

A new worker cannot claim it as ordinary work.

The executor generation/lease that created the pending consequence cannot continue fresh model
reasoning after ownership is cleared.

### C-I9 — Deterministic approval review projection

Pending review is reconstructed from durable:
- ApprovalRequest;
- GovernanceIntent;
- PolicyDecision;
- ToolCall;
- optional ActionSnapshot / ExternalAction.

The projection revalidates:
- durable identity;
- requester/scope authority snapshot;
- GovernanceIntent canonical JSON + digest;
- side-effect ActionSnapshot canonical JSON + digest;
- ToolVersion / proposal / operation_id binding.

Identity drift fails closed.

### C-I10 — C stops before decision and execution

Stage 3.3-C does not implement:
- ApprovalDecision;
- approve/deny application commands or APIs;
- approver role / separation-of-duties decision enforcement;
- decision replay/idempotency;
- expire_due_approvals;
- approved recovery/resume;
- approved DESTRUCTIVE physical execution.

Those belong to Stage 3.3-D.

## Freeze boundary

Stage 3.3-C is frozen.

Correctness-affecting changes to durable pending approval semantics require an explicit later
accepted slice or governance design amendment preserving these invariants.

Stage 3.3-D may now implement approval decision and approved execution bridge only.

## Gate

~~~text
Stage 3.3-A1
✅ ACCEPTED / FROZEN

Stage 3.3-A2
✅ ACCEPTED / FROZEN

Stage 3.3-A Aggregate
✅ ACCEPTED / FROZEN

Stage 3.3-B
✅ ACCEPTED / FROZEN

Governance Amendment 001
✅ ACCEPTED / FROZEN

Stage 3.3-C
✅ ACCEPTED / FROZEN

Stage 3.3-D
🔓 UNLOCKED

Stage 3.3-E
🔒 LOCKED

Stage 3.3-F
🔒 LOCKED

Stage 3.3 Runtime Acceptance
🔒 LOCKED
~~~

Governing rule:

> Approval intent may become durable before a human decision, but it carries no physical
> execution authority until a later accepted Stage 3.3-D decision bridge explicitly grants it.
