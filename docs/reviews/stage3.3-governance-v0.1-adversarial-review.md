# Stage 3.3 Governance — Design V0.1 Adversarial Review

Status: **ADVERSARIAL REVIEW COMPLETE — V0.1 NOT ACCEPTED**

Reviewed inputs:
- docs/design/stage3.3-governance-v0.1.md
- docs/acceptance/stage3.3-governance-acceptance-v0.1.md
- docs/reviews/stage3.3-governance-v0.1-self-review.md
- docs/validation/stage3.3-governance-v0.1-scenario-validation.md

Parent baseline:
- Stage 3.2 Runtime V1.0 — ACCEPTED / FROZEN

This review argues against the design from the perspective of:
- a skeptical staff engineer;
- a security reviewer;
- a platform buyer;
- a future maintainer.

No V0.1 text is changed in this phase.

## 1. Executive verdict

The Stage 3.3 thesis survives adversarial review:

> A production Agent runtime needs deterministic authorization and durable human approval
> semantics that are separate from model reasoning.

However, V0.1 risks expanding into an IAM/policy platform and contains one important state
collision with the accepted Stage 3.2 runtime.

Result:

- Core ideas that survive: 9
- Scope cuts required: 7
- Architecture corrections required: 10
- Explicit deferrals required: 8

V0.1 remains NOT ACCEPTED.

## 2. AR-01 — Why not use OPA/Cedar and delete GovernancePolicyVersion?

Attack:

OPA, Cedar, Zanzibar-style systems and cloud IAM already solve authorization.

Why invent a policy engine?

Verdict: **PARTIALLY VALID**

AgentForge should not invent a general-purpose policy language.

But it still needs durable Agent-specific semantics for:

- binding the exact Tool proposal to a decision;
- persisting which policy/version decided;
- WAITING_APPROVAL;
- approval/cancellation races;
- approval expiry;
- safe resume into Stage 3.2;
- proving that no physical Tool call happened before authorization.

V0.2 should define a deliberately tiny policy schema and an evaluator interface.

The built-in evaluator is a reference implementation.

A future OPA/Cedar adapter may implement the evaluator interface without changing durable
PolicyDecision / Approval semantics.

Cut:
- no general expression language;
- no policy compiler;
- no recursive conditions.

## 3. AR-02 — Why persist PolicyDecision if evaluation is deterministic?

Attack:

If policy evaluation is pure, recompute it when needed.

Verdict: **REJECTED**

Recomputation alone loses:
- historical policy version;
- matched rule;
- exact requester principal snapshot;
- exact proposal digest;
- audit evidence;
- race winner timing.

The durable decision is needed even if the decision algorithm is deterministic.

## 4. AR-03 — Why have GovernanceIntent and ActionSnapshot?

Attack:

Two canonical digests look redundant and invite divergence.

Verdict: **VALID FOR SIDE EFFECTS**

For side effects, Stage 3.2 ActionSnapshot already contains:

- ToolVersion;
- effect type;
- arguments;
- credential_ref;
- operation_id.

It already has a frozen canonical digest and was explicitly designed with future approval
binding in mind.

V0.2 should prefer:

~~~text
side effect proposal
  -> ActionSnapshot + ExternalAction AWAITING_APPROVAL
  -> approval binds ActionSnapshot.digest
~~~

instead of inventing a second semantic side-effect digest.

For READ, no ExternalAction exists, so a smaller immutable ReadApprovalSnapshot or
GovernanceIntent remains justified.

This also solves the V0.1 READY/read-recovery collision.

## 5. AR-04 — Persisting ExternalAction before approval sounds like “intent before authority”

Attack:

Does creating an ExternalAction before human approval accidentally mean the effect is
authorized?

Verdict: **REJECTED IF STATE IS EXPLICIT**

A durable action-intent record is not physical execution authority.

V0.2 should add:

~~~text
ExternalAction AWAITING_APPROVAL
ToolCall AWAITING_APPROVAL
~~~

with invariant:

- current_attempt_id = NULL;
- no ToolExecutionAttempt;
- Action Commit rejects AWAITING_APPROVAL;
- recovery never executes it;
- cancellation/deny may safely abort it.

This is stronger than creating a side-effect identity after approval because the human can
approve the exact frozen ActionSnapshot digest and operation_id.

## 6. AR-05 — Why support approval for READ at all?

Attack:

Human approval for READ increases complexity and latency.

Verdict: **KEEP**

Some READ tools expose:
- customer records;
- production logs;
- HR data;
- security findings;
- regulated information.

Governance cannot equate read-only with low-risk.

But READ approval should use a separate lightweight snapshot, not ExternalAction.

## 7. AR-06 — Multi-tenancy is becoming too broad

Attack:

tenant_scope, policy isolation, approval lists, role scopes: this looks like a SaaS tenancy
platform.

Verdict: **PARTIALLY VALID**

Stage 3.3 needs a namespace boundary because authorization without scope is unsafe.

But V0.2 should call it principal_scope / governance_scope and avoid building:
- tenant lifecycle;
- organization CRUD;
- billing tenancy;
- cross-tenant admin hierarchy.

Reuse the existing principal_scope concept where possible.

## 8. AR-07 — Full policy administration API is not necessary for runtime acceptance

Attack:

Do we need CRUD/publish UI/API to prove governance semantics?

Verdict: **VALID**

V0.2 should defer general policy administration API.

Stage 3.3 can:
- persist immutable policy versions;
- seed/create them through repository/test/admin fixture paths;
- expose runtime decision/approval APIs.

A narrow publish/assignment repository interface is sufficient.

Full management UI/API is future work.

## 9. AR-08 — Current create/cancel/resolve APIs undermine governance claims

Attack:

Approval endpoint may be secure while cancel and manual action resolution remain anonymous
or caller-identity-driven.

Verdict: **VALID**

V0.2 must bring mutating control-plane commands under PrincipalContext:

- create_run requester identity;
- cancel authorization;
- manual ActionResolution resolver identity;
- approval decision identity.

This does not require implementing authentication itself.

A trusted PrincipalResolver boundary is enough.

## 10. AR-09 — Approval summary can be prompt-injected by the model

Attack:

If human sees a model-generated description such as:

“Harmless maintenance action, please approve”

the model can socially engineer the approver.

Verdict: **VALID SECURITY ISSUE**

Approval review data must be generated from deterministic durable facts:

- Tool name/version;
- effect type;
- canonical/redacted arguments;
- action digest;
- policy rule/reason;
- requester;
- scope;
- expiry.

Model-generated prose may be shown only as explicitly untrusted context and is not part of
authorization evidence.

V0.2 should not require any model-generated approval explanation.

## 11. AR-10 — Separation of duties is too enterprise-heavy

Attack:

SoD adds roles and identity complexity.

Verdict: **KEEP MINIMAL**

A single boolean derived from policy plus one required approver role provides large security
value and is still small.

Do not add:
- organizational hierarchy;
- manager chain;
- quorum;
- sequential approvals.

## 12. AR-11 — Approval expiration needs a scheduler platform

Attack:

Does Stage 3.3 need a new background scheduler?

Verdict: **NO**

Use a narrow PostgreSQL maintenance primitive:

~~~text
expire_due_approvals(limit)
~~~

that:
- selects due PENDING approvals;
- locks Run first before mutation;
- uses DB time;
- is safe to call periodically by worker/control-plane maintenance.

Also set:

~~~text
effective_expires_at = min(policy approval TTL, Run.deadline_at)
~~~

so approval wait cannot outlive business deadline.

No generic scheduler framework is needed.

## 13. AR-12 — Policy retirement should revoke in-flight Runs immediately

Attack:

Security policy changed; why let an old pinned Run keep executing?

Verdict: **IMPORTANT BUT DEFER LIVE REVOCATION**

For deterministic V1 governance:

- Run pins exact policy version;
- retirement prevents new Run assignment;
- already pinned Run remains reproducible.

Emergency revocation of already-running/pending Runs needs a separate explicit revocation
authority and race model.

Do not silently make “current newest policy” a moving runtime dependency.

Defer live revocation to a later governance extension.

## 14. AR-13 — DENY should return to model so it can choose another Tool

Attack:

Failing the entire Run on DENY is unfriendly.

Verdict: **DEFER ADAPTIVE DENIAL**

Allowing the model to automatically work around a denied Tool can create policy probing and
circumvention loops.

Stage 3.3 V1 should remain fail-closed:
- durable DENY;
- Run fails.

A later design may permit policy-safe alternative planning with explicit limits.

## 15. AR-14 — Approval could be reused after UNKNOWN to justify retry

Attack:

A human approved the action once. Why not replay on timeout?

Verdict: **REJECTED**

Approval answers:

> May this intended action be attempted?

It does not answer:

> Did the previous physical attempt execute?

UNKNOWN remains Stage 3.2 business uncertainty.

Reconciliation remains mandatory before any potentially duplicating retry.

## 16. AR-15 — Why keep operation_id before approval?

Attack:

Generating operation_id before approval creates identity for work that may never execute.

Verdict: **ACCEPTABLE AND USEFUL**

For side effects, creating ActionSnapshot + ExternalAction AWAITING_APPROVAL:

- freezes exact provider idempotency identity;
- lets approval bind exact ActionSnapshot digest;
- makes restart recovery deterministic;
- avoids the READY/read collision.

If denied/cancelled/expired:
- ExternalAction -> ABORTED;
- current_attempt_id stays NULL;
- no external effect occurred.

This fits Stage 3.2 meaning of ABORTED.

## 17. AR-16 — Governance event log is not tamper-proof audit storage

Attack:

Normal PostgreSQL events are mutable by DB administrators.

Verdict: **TRUE, OUT OF SCOPE**

Stage 3.3 should claim:
- durable application audit trail;

not:
- cryptographically tamper-evident regulatory archive.

Hash-chained/WORM audit export is future work.

## 18. Required V0.2 architecture corrections

V0.2 should:

1. persist Run requester principal_scope + principal_id snapshot;
2. pin GovernancePolicyVersion deterministically at Run creation;
3. define compatibility policy migration for existing Stage 3.2 AgentVersions;
4. specify exact small policy rule schema/order;
5. use ActionSnapshot digest as side-effect approval subject;
6. add ExternalAction AWAITING_APPROVAL;
7. keep READ approval snapshot separate;
8. define approved side-effect bridge that does not broaden Stage 3.2 no-approval eligibility;
9. define expire_due_approvals(limit) with DB time and Run-root locks;
10. protect create/cancel/action-resolution/approval mutations with PrincipalContext;
11. define exact budget accounting;
12. make approval review projection deterministic and non-model-authored.

## 19. Explicit V0.2 scope cuts

Defer:

- arbitrary ABAC;
- OPA/Rego language implementation;
- full policy CRUD UI/API;
- quorum approvals;
- multi-step approval chains;
- live policy revocation of already pinned Runs;
- cryptographic audit archive;
- adaptive model replanning after DENY.

## 20. Gate state

~~~text
Stage 3.3 V0.1
Self Review             ✅
Scenario Validation     ✅
Adversarial Review      ✅

Design V0.1             ❌ NOT ACCEPTED

Corrective Design V0.2  🔓 REQUIRED
Implementation          🔒 LOCKED
~~~

Governing adversarial conclusion:

> Build durable Agent governance semantics, not a second IAM product and not a second
> execution engine.
