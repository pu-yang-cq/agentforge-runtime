# Stage 3.2 Durable Runtime — Design V0.3 Final Re-Review

Status: **PASSED**

Reviewed freeze candidate:

- `docs/design/stage3.2-durable-runtime-v0.3.md`
- `docs/acceptance/stage3.2-acceptance-v0.3.md`

Parent baseline:

- Stage 3.1 Core Runtime V1.0 — ACCEPTED / FROZEN

## 1. Final verdict

The Stage 3.2 Design V0.3 freeze candidate passes final re-review.

No unresolved correctness blocker remains in the design.

The final review specifically re-checked:

- state-machine closure;
- Run-row progression serialization;
- global multi-row lock order;
- cancel vs Action Commit ordering;
- stale generation / lease fencing;
- in-flight ModelInvocation consequence fencing;
- orphaned ToolExecutionAttempt closure;
- orphaned ReconciliationAttempt closure;
- durable retry/yield semantics;
- READY-action stabilization under budget/deadline;
- UNKNOWN / reconciliation safety;
- BEST_EFFORT retry restrictions;
- late-result winner semantics;
- manual-resolution winner semantics;
- terminal Run × ExternalAction matrix;
- current_attempt_id lifecycle;
- canonical ActionSnapshot bytes/digest;
- credential isolation;
- checkpoint authority;
- Stage 3.1 regression compatibility.

Result:

```text
New Blockers: 0
Unresolved V0.2 Blockers: 0
Unresolved V0.2 Major findings: 0
Scope expansion: 0
```

## 2. Freeze-candidate corrections reviewed

The final corrective pass fixed three last issues without expanding scope.

### FC-01 — lock-order consistency

Late Tool result paths now follow:

```text
Run
-> ExternalAction when present
-> ToolCall
-> ToolExecutionAttempt
```

Side-effect takeover paths also lock ToolCall before Attempt when ToolCall is
mutated.

Manual resolution and cancellation paths that mutate Action + ToolCall follow
the same relative order.

Reconciliation result paths follow:

```text
Run
-> ExternalAction
-> ReconciliationAttempt
```

No reviewed path intentionally acquires ToolCall before ExternalAction for the
same side-effect transaction.

### FC-02 — canonical integer range

Canonical ActionSnapshot V1 now restricts integers to:

```text
[-9007199254740991, 9007199254740991]
```

and uses restricted RFC 8785 semantics with golden canonical-byte/digest
vectors.

This removes the final cross-language ambiguity in the approval-binding digest
contract.

### FC-03 — stale ModelInvocation result semantics

The design now distinguishes:

1. stale execution authority caused by expired lease / stale generation; and
2. still-authorized invocation whose business consequence is later blocked by
   cancellation/deadline.

Case 1 preserves the frozen Stage 3.1 stale-executor rejection rule.

Case 2 may record the ModelInvocation outcome but must discard the business
consequence and create no new message/tool/action progression.

This preserves Stage 3.1 behavior while adding the Stage 3.2 cancellation and
deadline fence.

## 3. V0.1 blocker closure

All ten V0.1 self-review blockers are closed:

- physical attempt vs logical action failure separation;
- reconciliation transport failure separation;
- atomic Action Commit Boundary;
- late-result winner rule;
- terminal/manual-review semantics;
- ToolExecutionAttempt state machine;
- ToolCall projection;
- canonical action digest;
- cross-table progression enforcement;
- high-risk fail-closed behavior.

## 4. Scenario-validation closure

The V0.1 scenario failures are now represented by normative rules and mandatory
acceptance tests, including:

- cancel vs Action Commit;
- late result vs takeover;
- reconcile transport failure;
- definite-not-executed retry;
- manual resolution vs delayed reconcile;
- stale checkpoint;
- budget/deadline with unresolved action;
- competing progression types;
- high-risk Tool fail-closed;
- credential leakage;
- terminal cancellation + manual review;
- READ attempt accounting.

No scenario requires model reasoning to repair durable runtime uncertainty.

## 5. Adversarial-review closure

The design remains intentionally narrower than a general workflow engine.

Explicitly not part of the frozen Stage 3.2 design:

- workflow/DAG DSL;
- parallel side-effect branches;
- Temporal-compatible replay;
- generic retry DSL;
- multi-region scheduling;
- billing/quota platform;
- enterprise RBAC/approval UI;
- real SaaS acceptance dependency.

The product thesis remains:

> AgentForge owns deterministic Agent side-effect semantics; PostgreSQL is the
> initial execution substrate, not the product definition.

## 6. Acceptance-criteria quality

Acceptance Criteria V0.3 are sufficiently concrete to drive implementation.

They require:

- real PostgreSQL concurrency races;
- controlled crash windows;
- observable fake external ledger;
- canonical byte golden vectors;
- secret-sentinel leakage checks;
- DB-time retry/deadline tests;
- no skipped mandatory durability tests;
- full Stage 3.1 regression.

The acceptance criteria do not rely on happy-path mocks alone.

## 7. Final design gate

```text
Stage 3.2 Design V0.3
✅ FINAL RE-REVIEW PASSED

Design Acceptance
✅ APPROVED FOR FREEZE

Implementation
🔓 MAY BE UNLOCKED AFTER FROZEN V1.0 ARTIFACTS ARE COMMITTED

Stage 3.2 Runtime Acceptance
🔒 remains locked until implementation is complete

Stage 3.3 Governance
🔒 remains locked
```
