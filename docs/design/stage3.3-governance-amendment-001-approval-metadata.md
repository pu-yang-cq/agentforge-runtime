# Stage 3.3 Governance Design Amendment 001 — Approval Metadata for Capability-Derived Approval

Status: **ACCEPTED AMENDMENT / FROZEN**

Amends:
- `docs/design/stage3.3-governance-v1.0-frozen.md`
- `docs/acceptance/stage3.3-governance-acceptance-v1.0-frozen.md`

Reason:

The frozen capability envelope can transform a selected raw `ALLOW` into effective
`REQUIRE_APPROVAL` when immutable ToolBinding capability is stricter:

- READ with `approval_required=true`;
- WRITE / EXTERNAL_SIDE_EFFECT without no-approval capability;
- every non-DENY DESTRUCTIVE proposal.

The original V1.0 rule schema allowed approval metadata only on raw
`REQUIRE_APPROVAL` rules. That left capability-derived `REQUIRE_APPROVAL` without the
required approver role, separation-of-duties flag, or TTL needed to create a durable
ApprovalRequest.

This amendment resolves only that metadata-source gap.

## 1. Rule schema amendment

`GovernancePolicyRule.approval` is now valid for:

- raw `REQUIRE_APPROVAL`: **mandatory**;
- raw `ALLOW`: **optional fallback approval metadata**;
- raw `DENY`: **forbidden**.

An ALLOW rule carrying approval metadata does not itself require approval.

Its approval metadata is ignored when the capability envelope leaves the effective decision
as ALLOW.

## 2. Effective approval metadata

After deterministic rule selection and capability-envelope evaluation:

~~~text
effective ALLOW
  -> approval metadata = None

effective DENY
  -> approval metadata = None

effective REQUIRE_APPROVAL
  -> approval metadata = selected rule approval metadata
~~~

If the effective decision is `REQUIRE_APPROVAL` but the selected rule has no approval
metadata, evaluation fails closed:

~~~text
raw selected decision may be ALLOW
capability envelope requires approval
approval metadata missing
        ↓
effective decision = DENY
approval metadata = None
~~~

No default approver, role, TTL, or separation-of-duties value may be invented by runtime code.

## 3. Security properties

This amendment does not broaden capability.

- ALLOW with no-approval-capable READ/side-effect remains ALLOW exactly as before.
- DENY remains DENY.
- DESTRUCTIVE still has no no-approval path.
- Missing approval metadata becomes more restrictive: DENY.
- Policy ordering and matching are unchanged.
- GovernanceIntent V1 is unchanged.
- PolicyDecision durable shape is unchanged.
- Stage 3.2 physical execution boundaries are unchanged.
- Stage 3.3-B ALLOW / DENY consequence semantics are unchanged.

## 4. Persistence compatibility

No migration is required.

GovernancePolicyVersion already stores rule records in bounded JSONB, and the frozen record
shape already contains the nullable `approval` field.

Existing published policies remain readable.

For an existing ALLOW rule without approval metadata:
- if capability leaves it effective ALLOW, behavior is unchanged;
- if capability would require approval, it now fails closed DENY instead of producing an
  unusable metadata-less REQUIRE_APPROVAL result.

## 5. Acceptance amendment

Mandatory contracts:

1. raw REQUIRE_APPROVAL without approval metadata is rejected at rule construction;
2. raw DENY with approval metadata is rejected;
3. raw ALLOW may carry approval metadata;
4. raw ALLOW + READ without approval requirement remains effective ALLOW and does not expose
   approval metadata in PolicyEvaluation;
5. raw ALLOW + approval-required READ uses fallback metadata and becomes REQUIRE_APPROVAL;
6. raw ALLOW + WRITE/EXTERNAL_SIDE_EFFECT without no-approval capability uses fallback metadata
   and becomes REQUIRE_APPROVAL;
7. raw ALLOW + DESTRUCTIVE uses fallback metadata and becomes REQUIRE_APPROVAL;
8. any capability-derived REQUIRE_APPROVAL without fallback metadata becomes DENY;
9. deterministic rule ordering remains unchanged across rule permutations;
10. Stage 3.3-B accepted ALLOW/DENY regression remains green.

## 6. Frozen governing rule

> Runtime may never invent approval authority. Every effective REQUIRE_APPROVAL must carry
> approval metadata from the exact deterministically selected immutable policy rule; otherwise
> the proposal fails closed as DENY.
