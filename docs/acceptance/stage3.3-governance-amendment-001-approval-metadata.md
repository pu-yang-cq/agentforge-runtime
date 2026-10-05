# Stage 3.3 Governance Acceptance Amendment 001 — Approval Metadata Source

Status: **ACCEPTED AMENDMENT / FROZEN**

Depends on:
- `docs/design/stage3.3-governance-amendment-001-approval-metadata.md`
- `docs/acceptance/stage3.3-governance-acceptance-v1.0-frozen.md`

This amendment is normative only for approval metadata sourcing when the capability envelope
changes a selected raw ALLOW into effective REQUIRE_APPROVAL.

## Amended acceptance rule

A PolicyEvaluation may expose non-null approval metadata only when its effective decision is
REQUIRE_APPROVAL.

For a deterministically selected rule:

- raw REQUIRE_APPROVAL requires approval metadata;
- raw ALLOW may carry optional fallback approval metadata;
- raw DENY must not carry approval metadata.

If capability-envelope evaluation produces REQUIRE_APPROVAL and the selected rule does not
carry approval metadata, the evaluator must fail closed to effective DENY.

Runtime code must never synthesize:
- required_approver_role;
- separation_of_duties;
- ttl_seconds.

## Required tests

The accepted Stage 3.3 gate must prove:

1. ALLOW with fallback approval metadata round-trips through the immutable policy record.
2. ALLOW that remains ALLOW yields `PolicyEvaluation.approval is None`.
3. approval-required READ from ALLOW uses the exact fallback metadata.
4. WRITE / EXTERNAL_SIDE_EFFECT without no-approval capability from ALLOW uses the exact
   fallback metadata.
5. DESTRUCTIVE from ALLOW uses the exact fallback metadata.
6. the same capability-derived cases without fallback metadata become DENY.
7. explicit REQUIRE_APPROVAL keeps exact metadata.
8. DENY cannot carry metadata.
9. no Stage 3.2 physical-execution rule changes.
10. accepted Stage 3.3-B ALLOW / DENY behavior remains green.

## Governing assertion

> An effective REQUIRE_APPROVAL is valid only when the exact selected policy rule supplies the
> complete approval requirement. Missing metadata is denial, not an invitation for runtime
> defaults.
