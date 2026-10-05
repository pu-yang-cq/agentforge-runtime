# Stage 3.3-A1 — Governance Compatibility + Identity / Policy Schema

Status: **ACCEPTED / FROZEN**

Parent:
- Stage 3.3 Governance Design V1.0 — ACCEPTED / FROZEN
- Stage 3.3 Governance Acceptance Criteria V1.0 — FROZEN
- Stage 3.3 implementation slices — FROZEN PLAN

Accepted semantic candidate:

`cf1c7571b67210bedfe411865bb940c83e6da4f0`

Independent acceptance trigger:

`cfeaef8f868e976982e7ed1986101c2743bf15ab`

Successful GitHub Actions run:

`37268108885`

Execution record:

`docs/execution/stage3.3-a1-execution-record.md`

## Accepted scope

Stage 3.3-A1 establishes the durable identity and policy foundation required before policy
evaluation may influence runtime behavior:

- `GovernanceMode.LEGACY_STAGE32` / `GovernanceMode.GOVERNED`;
- `PrincipalType`;
- normalized bounded `PrincipalContext`;
- durable requester snapshot fields on Run;
- durable `GovernancePolicyVersion` schema and lifecycle;
- bounded governance rule schema;
- immutable AgentVersion `governance_mode` + `policy_version_id`;
- existing Stage 3.2 AgentVersion migration/backfill to `LEGACY_STAGE32`;
- policy draft/publish/retire repository operations for bootstrap/test administration;
- forward-only migration from `0016_checkpoint_overlay`;
- explicit `LegacyDevelopmentPrincipalResolver`;
- trusted-vs-legacy resolver boundary;
- exact governed Run policy/requester pinning;
- Stage 3.2 legacy Run compatibility preserved.

A1 does **not** yet add deterministic policy evaluation, GovernanceIntent, PolicyDecision, or
Tool execution governance consequences.

## Independent acceptance evidence

Workflow:
- **Stage 3.3-A1 Identity Policy Foundation**

Successful run:
- **37268108885**

Verified gate:
- frozen Stage 3.3 lineage and A1 implementation surface: PASS;
- accepted Stage 3.2 migration bytes unchanged: PASS;
- A1 unit contracts: PASS;
- A1 PostgreSQL 18 contracts: PASS;
- complete Stage 3.2 regression on Stage 3.3 head: PASS;
- workflow conclusion: **SUCCESS**.

## Accepted compatibility facts

### A1-I1 — Exact legacy backfill

Existing Stage 3.2 AgentVersion rows migrate to:

~~~text
governance_mode   = LEGACY_STAGE32
policy_version_id = NULL
~~~

No accepted Stage 3.1/3.2 migration was rewritten.

### A1-I2 — Immutable AgentVersion governance assignment

A GOVERNED AgentVersion:
- requires a non-null policy_version_id;
- may only be created against a PUBLISHED policy version;
- cannot later mutate governance_mode;
- cannot later mutate policy_version_id.

A new policy assignment requires a new AgentVersion.

### A1-I3 — Policy lifecycle

GovernancePolicyVersion lifecycle is:

~~~text
DRAFT
  ↓ publish
PUBLISHED
  ↓ retire
RETIRED
~~~

Frozen behavior:
- DRAFT cannot be assigned to a governed AgentVersion;
- PUBLISHED rule content is immutable;
- RETIRED cannot be assigned to a new AgentVersion;
- existing AgentVersion/Run exact-version references remain valid historical facts;
- no automatic switch to a newer policy exists.

### A1-I4 — Principal normalization

Governed principal authority facts are normalized before durable use:
- principal_id stripped/nonblank/bounded;
- principal_scope stripped/nonblank/bounded;
- authn_source stripped/nonblank/bounded;
- roles stripped, unique, sorted, bounded.

### A1-I5 — Legacy identity isolation

`LegacyDevelopmentPrincipalResolver` is explicitly identifiable and is not trusted to authorize
GOVERNED mode.

A trusted PrincipalResolver boundary is required before later governed authorization slices may
consume identity as authority.

### A1-I6 — Exact governed Run snapshot

For a GOVERNED AgentVersion, Run creation durably copies:
- exact policy_version_id;
- normalized requester principal_id;
- principal_type;
- normalized/sorted roles;
- principal_scope;
- authn_source.

The idempotency authority scope comes from the normalized PrincipalContext, not an untrusted
body-supplied compatibility value.

### A1-I7 — Legacy Run SQL NULL compatibility

For LEGACY_STAGE32 Run creation, governance snapshot fields remain absent.

In particular:
- `requester_roles=None` persists as PostgreSQL SQL NULL;
- it must not persist as JSON `null`.

This is enforced by `JSONB(none_as_null=True)` and a dedicated PostgreSQL regression test.

### A1-I8 — No early policy consequence bridge

A1 contains no accepted implementation of:
- deterministic evaluator consequence;
- GovernanceIntent V1;
- PolicyDecision;
- ALLOW/DENY Tool behavior;
- approval waiting;
- destructive execution authority.

Those remain owned by later frozen slices.

## Rejected candidate history

Acceptance was earned after three rejected candidates:

1. Run `37267459937`
   - A1 unit/PostgreSQL passed;
   - rejected on Ruff lint/line formatting.

2. Run `37267652894`
   - A1 unit/PostgreSQL and Ruff lint passed;
   - rejected on Ruff formatter normalization.

3. Run `37267770281`
   - Ruff, format and mypy passed;
   - A1 targeted contracts passed;
   - full regression exposed 58 legacy failures caused by JSON null vs SQL NULL persistence.

The compatibility bug was repaired and locked with a dedicated PostgreSQL regression test before
the final acceptance run.

## Freeze boundary

The A1 semantics above are now frozen.

Stage 3.3-A2 may add:
- deterministic policy evaluator;
- GovernanceIntent V1 canonicalization/digest;
- immutable PolicyDecision persistence;
- audit events for policy decisions.

A2 may not weaken:
- A1 principal normalization;
- legacy resolver isolation;
- immutable AgentVersion policy assignment;
- exact policy pinning;
- legacy SQL-NULL compatibility;
- Stage 3.2 migration immutability.

A2 also may not yet bridge policy consequence into physical Tool execution behavior.

## Gate

~~~text
Stage 3.3-A1
✅ ACCEPTED
✅ FROZEN

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

Governing rule:

> A1 freezes durable identity and policy facts only; policy consequence remains inert until the
> later frozen implementation slices explicitly consume it.
