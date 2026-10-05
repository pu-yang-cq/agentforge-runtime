# Stage 3.3 Governance Amendment 001 — Approval Metadata Source

Status: **ACCEPTED / FROZEN**

Amends:
- Stage 3.3 Governance Design V1.0 — ACCEPTED / FROZEN
- Stage 3.3 Governance Acceptance Criteria V1.0 — FROZEN

Normative amendment artifacts:
- `docs/design/stage3.3-governance-amendment-001-approval-metadata.md`
- `docs/acceptance/stage3.3-governance-amendment-001-approval-metadata.md`

Accepted semantic candidate:

`8d7b214c9ce38e201da364af59dcc35a90565205`

Independent acceptance trigger:

`04452c3e0ded87852bb4c03b2096a08eb4603f7b`

Successful GitHub Actions run:

`37325262562`

Execution record:

`docs/execution/stage3.3-governance-amendment-001-execution-record.md`

## Accepted semantics

A selected immutable policy rule may provide approval metadata as follows:

- REQUIRE_APPROVAL: metadata mandatory;
- ALLOW: metadata optional and treated only as fallback approval metadata;
- DENY: metadata forbidden.

If capability-envelope evaluation keeps ALLOW:
- PolicyEvaluation exposes no approval metadata;
- normal ALLOW semantics remain unchanged.

If capability-envelope evaluation tightens ALLOW into REQUIRE_APPROVAL:
- the exact fallback metadata from that selected ALLOW rule is used.

If capability requires approval but the selected rule has no metadata:
- evaluation fails closed to effective DENY;
- no runtime default approval authority is invented.

## Frozen invariants

### AM001-I1 — No capability broadening

The amendment cannot turn a previously forbidden physical operation into an ALLOW path.

DESTRUCTIVE still has no no-approval execution path.

### AM001-I2 — Exact metadata provenance

Every effective REQUIRE_APPROVAL must carry:
- required_approver_role;
- separation_of_duties;
- ttl_seconds

from the exact selected immutable GovernancePolicyRule.

### AM001-I3 — Missing metadata is denial

Capability-derived REQUIRE_APPROVAL with no selected-rule approval metadata becomes effective
DENY.

It does not create an incomplete ApprovalRequest and does not invent defaults.

### AM001-I4 — ALLOW metadata is inert unless capability tightens

ALLOW fallback metadata:
- does not itself require approval;
- is not exposed by PolicyEvaluation while effective decision remains ALLOW;
- cannot broaden ToolBinding capability.

### AM001-I5 — Frozen compatibility

The successful independent gate proves:
- A1/A2/B/C targeted contracts;
- PostgreSQL regression;
- Stage 3.2 full regression;
- no Stage 3.3-D behavior.

Stage 3.3 migrations before 0019 remain unchanged.

The accepted 0019 formatting-only normalization is Python-AST equivalent to its pre-amendment
form.

## Freeze boundary

Amendment 001 is frozen.

Future correctness-affecting changes to approval metadata provenance require another explicit
governance design amendment and independent re-review.

Stage 3.3-C may continue implementing durable approval intent under this amendment.

Stage 3.3-D remains locked until Stage 3.3-C is independently accepted and frozen.

## Governing rule

> Approval authority is policy data, never a runtime default.
