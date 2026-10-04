# Stage 3.2 Durable Runtime Design V1.0 — ACCEPTED / FROZEN

Status: **ACCEPTED / FROZEN**

Frozen artifacts:

- `docs/design/stage3.2-durable-runtime-v1.0-frozen.md`
- `docs/acceptance/stage3.2-acceptance-v1.0-frozen.md`

Parent baseline:

- Stage 3.1 Core Runtime V1.0 — ACCEPTED / FROZEN

## Review chain

The design passed the required gated process:

```text
Design V0.1
  -> Self Review
  -> Scenario Validation
  -> Adversarial Review
  -> Design V0.2
  -> V0.2 Re-Review
  -> Corrective Design V0.3
  -> Final Re-Review
  -> Design Acceptance
  -> V1.0 FROZEN
```

Evidence documents:

- `docs/reviews/stage3.2-design-v0.1-self-review.md`
- `docs/validation/stage3.2-design-v0.1-scenario-validation.md`
- `docs/reviews/stage3.2-design-v0.1-adversarial-review.md`
- `docs/reviews/stage3.2-design-v0.2-re-review.md`
- `docs/reviews/stage3.2-design-v0.3-final-review.md`

## Final review result

Final V0.3 re-review:

```text
New Blockers: 0
Unresolved V0.2 Blockers: 0
Unresolved V0.2 Major findings: 0
Scope expansion: 0
```

The freeze candidate was corrected before acceptance for:

- global lock-order consistency;
- exact canonical integer range;
- preservation of Stage 3.1 stale ModelInvocation fencing.

## Frozen architecture commitments

Stage 3.2 implementation must preserve:

- no global exactly-once claim;
- durable intent before effect;
- Run-row progression serialization;
- Action Commit Boundary;
- ToolExecutionAttempt for every physical Tool call;
- stable operation_id per logical ExternalAction;
- explicit UNKNOWN outcome;
- reconciliation before potentially duplicating retry;
- authoritative NOT_EXECUTED requirement for unsafe non-idempotent retry;
- cancellation != rollback;
- explicit orphan-attempt closure;
- DB-time durable retry/yield;
- model-result consequence fencing;
- deterministic ActionSnapshot Canonical JSON V1 + SHA-256;
- credential resolution only at adapter edge;
- terminal Run × ExternalAction matrix;
- checkpoint as non-authoritative optimization only;
- Stage 3.1 regression compatibility.

## Implementation gate

```text
Stage 3.2 Design
✅ ACCEPTED / FROZEN

Stage 3.2 Implementation
🔓 UNLOCKED

Stage 3.2 Runtime Acceptance
🔒 LOCKED until implementation passes frozen Acceptance Criteria V1.0

Stage 3.3 Governance
🔒 LOCKED
```

A correctness-affecting implementation deviation from Design V1.0 requires an
explicit design amendment and re-review before acceptance.
