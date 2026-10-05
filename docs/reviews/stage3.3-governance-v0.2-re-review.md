# Stage 3.3 Governance — Design V0.2 Re-Review

Status: **RE-REVIEW COMPLETE — V0.2 NOT YET ACCEPTED**

Reviewed:
- docs/design/stage3.3-governance-v0.2.md
- docs/acceptance/stage3.3-governance-acceptance-v0.2.md
- complete V0.1 review chain
- current Stage 3.2 API/runtime surfaces

Parent baseline:
- Stage 3.2 Runtime V1.0 — ACCEPTED / FROZEN

Implementation remains locked.

## 1. Executive result

V0.2 closes the central V0.1 architecture defects.

V0.1 blocker closure:

- Fully closed: 9
- Partially closed: 2

New/narrow remaining findings:

- Blocker: 4
- Major: 6
- Clarification: 3

A small V0.3 corrective pass should be sufficient.

## 2. V0.1 blocker closure

### SR-B01 — approved side-effect READY/read collision

**CLOSED**

Side effects now persist ActionSnapshot + ExternalAction AWAITING_APPROVAL before wait.

After approval, ExternalAction READY makes the side-effect recovery class structurally
unambiguous.

### SR-B02 — requester principal source

**CLOSED**

Governed Run stores immutable requester snapshot.

### SR-B03 — policy assignment/pinning

**MOSTLY CLOSED**

Governance mode and pinned version are explicit.

One remaining immutability question about when policy assignment may change is tracked in
RR-B04.

### SR-B04 — Stage 3.2 compatibility

**CLOSED**

LEGACY_STAGE32 is explicit and existing AgentVersions are backfilled without silently gaining
governance capabilities.

### SR-B05 — rule evaluation

**CLOSED**

Priority/severity/rule_id ordering is deterministic.

### SR-B06 — WRITE capability ambiguity

**CLOSED**

No-approval capability and approval-authorized capability are now explicitly distinct.

### SR-B07 — approval digest strength

**CLOSED**

Side-effect human approval binds the frozen ActionSnapshot digest + operation_id.

### SR-B08 — expiry scheduler

**MOSTLY CLOSED**

expire_due_approvals(limit), DB time and Run-root mutation are explicit.

A remaining correctness dependency on maintenance timing is tracked in RR-B03.

### SR-B09 — control-plane APIs

**PARTIALLY CLOSED**

PrincipalContext authorization is designed for mutating APIs.

However direct replacement of resolver_identity breaks accepted Stage 3.2 API regression.
See RR-B02.

### SR-B10 — destructive bridge

**CLOSED**

Approved destructive execution has a separate predicate and does not broaden Stage 3.2
no-approval eligibility.

### SR-B11 — budget accounting

**CLOSED**

Logical ToolCall vs physical ToolExecutionAttempt counters are explicit.

## 3. Remaining blockers

### RR-B01 — approval lock order conflicts with frozen Stage 3.2 child order

V0.2 specifies:

~~~text
Run
 -> ApprovalRequest
 -> ToolCall
 -> ExternalAction
~~~

For transactions touching a side-effect action, the frozen Stage 3.2 order is:

~~~text
Run
 -> ExternalAction
 -> ToolCall
 -> Attempt/ReconciliationAttempt
~~~

Run-first serialization reduces practical same-Run deadlock risk, but Stage 3.3 should not
create a second contradictory global order.

V0.3 must extend, not replace, the frozen order.

Recommended:

~~~text
Run
 -> ExternalAction when present
 -> ToolCall
 -> ApprovalRequest
 -> ApprovalDecision insert
~~~

READ path omits ExternalAction.

### RR-B02 — trusted identity change breaks frozen Stage 3.2 API contract

Current accepted API tests submit:

~~~json
{
  "resolver_identity": "operator:test"
}
~~~

and assert it is persisted/returned.

V0.2 says resolver_identity should be removed as an authority field.

A direct removal would fail the mandatory Stage 3.2 regression gate.

V0.3 must separate:

1. explicit LEGACY development/API compatibility behavior used by frozen regression; and
2. GOVERNED production behavior where authority comes only from PrincipalResolver.

The compatibility path must be labeled non-production and must never be used to authorize a
GOVERNED Run.

### RR-B03 — correctness must not depend on expiry sweeper punctuality

V0.2 defines expire_due_approvals(limit), but a scheduler may be delayed.

A PENDING row with expires_at in the past must already be logically unauthorized even before
maintenance materializes EXPIRED.

V0.3 must define:

> PENDING + db_now >= expires_at is effectively expired and can never authorize progress.

Every approve/resume path must check this predicate.

The sweeper materializes state; it is not the source of safety.

### RR-B04 — GovernancePolicyVersion assignment must respect AgentVersion immutability

V0.2 says a published policy can be assigned to a GOVERNED AgentVersion but does not define
whether that assignment may change later.

AgentVersion is already treated as immutable execution specification.

Changing its policy reference in place would make the same AgentVersion id authorize
different behavior over time.

V0.3 must require:
- governance_mode + policy_version_id are immutable parts of AgentVersion configuration;
- changing policy for future Runs requires a new AgentVersion;
- Run additionally copies the exact version id for audit/recovery.

## 4. Major findings

### RR-M01 — requester roles/scope normalization

Persisted requester_roles should be:
- unique;
- sorted;
- bounded strings.

principal_scope/principal_id/authn_source need nonblank bounded normalization.

Otherwise GovernanceIntent digest/audit can vary for semantically identical role sets.

### RR-M02 — governed read APIs need scope filtering too

V0.2 protects approval GET/list but does not explicitly protect existing:

~~~text
GET /v1/runs/{run_id}
~~~

Governed Run read surfaces must not leak across principal_scope.

Legacy development mode may preserve old anonymous test contract.

### RR-M03 — model outcome evidence on blocked policy consequence

If cancellation/deadline wins after model returned ToolProposal but before PolicyDecision
consequence commits, V0.2 says candidate governance consequence is discarded.

It should explicitly preserve the Stage 3.2 rule:

- still-authorized ModelInvocation outcome may be recorded as evidence;
- Tool/governance business consequence is discarded;
- stale generation cannot finalize invocation.

### RR-M04 — AWAITING_APPROVAL terminal matrix needs explicit guards

A Run must not become:
- COMPLETED;
- normal FAILED via unrelated progression;
- worker-claimable

while an AWAITING_APPROVAL action/request remains inconsistent.

Cancellation/deny/expiry must stabilize the pending action atomically.

### RR-M05 — approval decision replay semantics after terminalization

Exact replay after a previously committed APPROVE/DENY should return the durable result even
if Run has since moved to another state.

A different decision remains conflict.

This should be explicit for API idempotency.

### RR-M06 — create_run authorization is incomplete

V0.2 persists requester identity but does not require permission to start a governed Run.

V0.3 should require a minimal same-scope capability such as:

~~~text
runtime:run:create
~~~

for GOVERNED mode.

Do not add per-Agent IAM in Stage 3.3.

## 5. Clarifications

### RR-C01 — compatibility resolver

Default create_app(store) may retain a clearly named LegacyDevelopmentPrincipalResolver for
Stage 3.2 API regression.

Production/governed app creation should require/inject a trusted resolver.

### RR-C02 — policy retirement

The current decision to let already-pinned Runs continue is accepted for V1 and must be
called a deliberate scope boundary, not a security guarantee against emergency revocation.

### RR-C03 — audit claim

Keep wording “durable application audit evidence”, not “tamper-proof compliance log”.

## 6. V0.3 required corrections

V0.3 only needs to:

1. extend global lock order consistently;
2. formalize legacy API compatibility vs governed PrincipalResolver;
3. make expiry a logical predicate independent of sweeper timing;
4. freeze policy assignment as part of immutable AgentVersion;
5. normalize principal/roles;
6. scope governed Run reads;
7. preserve model outcome/discard semantics;
8. add AWAITING_APPROVAL terminal guards;
9. define exact decision replay after later Run transitions;
10. require runtime:run:create for governed creation.

No broad redesign is needed.

## 7. Gate state

~~~text
Stage 3.3 Design V0.2
❌ NOT YET ACCEPTED

V0.2 Re-Review
✅ COMPLETE

Corrective V0.3
🔓 REQUIRED

Final Review
🔒

Implementation
🔒 LOCKED
~~~

Governing re-review conclusion:

> Governance state may extend the runtime state machine, but it must inherit one lock order,
> one identity authority model, and one immutable execution specification.
