# Stage 3.2 Durable Runtime — Design V0.1 Adversarial Review

Status: **ADVERSARIAL REVIEW COMPLETE — V0.1 NOT ACCEPTED**

Reviewed inputs:

- `docs/design/stage3.2-durable-runtime-v0.1.md`
- `docs/reviews/stage3.2-design-v0.1-self-review.md`
- `docs/validation/stage3.2-design-v0.1-scenario-validation.md`

Parent baseline:

- Stage 3.1 Core Runtime V1.0 — ACCEPTED / FROZEN

This review deliberately argues against the design from the perspective of a
skeptical staff engineer, platform buyer, and future maintainer.

No Design V0.1 text is modified in this phase.

## 1. Executive verdict

The core Stage 3.2 thesis survives adversarial review:

> AgentForge needs its own durable side-effect semantics even if an external
> workflow engine, provider idempotency key, or queue system is used underneath.

However, the adversarial review also confirms that V0.1 is too broad in several
implementation areas.

The correct response is not to remove ExternalAction / UNKNOWN /
reconciliation. Those are the product-defining semantics.

The correct response is to aggressively avoid rebuilding generic workflow
infrastructure around them.

Summary:

- Core ideas that survive attack: 8
- Scope reductions required: 7
- Architecture clarifications required: 8
- Ideas that should be explicitly deferred: 8

Design V0.1 therefore remains **NOT ACCEPTED**.

---

# 2. Challenge AR-01 — Why not use Temporal and delete most of Stage 3.2?

## Attack

Temporal already provides:

- durable workflows;
- retries;
- timers;
- crash recovery;
- replay;
- activity execution;
- long-running waits;
- workflow history.

Why build custom Postgres leases, checkpoints, retries, and recovery?

## Verdict

**PARTIALLY VALID, CORE THESIS SURVIVES**

Temporal could replace or simplify parts of the *durable execution substrate*.

It does **not** decide:

- whether an ambiguous Jira create happened;
- whether a non-idempotent operation may be retried;
- what `UNKNOWN` means;
- whether cancellation implies rollback;
- what operation identity must remain stable;
- how a ToolCall maps to an ExternalAction;
- what future approval digest binds to;
- how manual resolution changes durable business truth.

Those remain AgentForge domain semantics even if Temporal executes them.

Therefore V0.2 should explicitly separate:

```text
AgentForge durable semantics
        vs
durable scheduling/execution substrate
```

P0 remains the accepted PostgreSQL/custom-worker substrate because Stage 3.1
already proves it and the project goal includes understanding these semantics.

But V0.2 must **not** expand into:

- generic workflow DSL;
- arbitrary DAG scheduling;
- child workflows;
- signals as a general abstraction;
- distributed timers as a standalone platform;
- Temporal-compatible replay semantics.

A future execution-backend adapter is acceptable. Rebuilding Temporal is not.

---

# 3. Challenge AR-02 — Why not trust third-party idempotency keys and skip UNKNOWN?

## Attack

Stripe, Jira-like APIs, email providers, and many modern APIs support request or
idempotency keys.

If AgentForge supplies `operation_id`, why not retry on timeout and rely on the
provider?

## Verdict

**REJECTED**

Provider idempotency is valuable but insufficient as the universal correctness
model.

Reasons:

- not every system supports idempotency;
- semantics differ by endpoint;
- retention windows vary;
- keys may be scoped per tenant/account/endpoint;
- an adapter may fail before knowing whether the server accepted the key;
- some APIs expose deduplication but no authoritative lookup;
- email/message systems may acknowledge after downstream delivery semantics
  diverge;
- provider bugs and proxy layers exist.

Therefore:

```text
provider idempotency
= one reconciliation/idempotency capability

not
= AgentForge correctness model
```

`operation_id`, UNKNOWN, and reconciliation remain justified.

---

# 4. Challenge AR-03 — UNKNOWN is too complex; just mark timeout FAILED

## Attack

Most application code treats timeout as failure. UNKNOWN creates more states,
tables, operator burden, and test cases.

## Verdict

**REJECTED — UNKNOWN IS ESSENTIAL**

Marking timeout FAILED is only safe for operations proven not to have crossed
the external effect boundary.

For a real side effect:

```text
request transmitted
server committed
response lost
```

is indistinguishable from:

```text
request transmitted
server never committed
response lost
```

without external evidence.

Conflating both with FAILED creates duplicate side effects under retry.

UNKNOWN is not feature complexity; it is representation of unavoidable
epistemic uncertainty.

This is a core AgentForge differentiator and must remain.

---

# 5. Challenge AR-04 — Why have Checkpoint at all if durable facts are truth?

## Attack

Stage 3.1 already persists:

- messages;
- events;
- model invocations;
- ToolCalls;
- run state.

If checkpoint is not authoritative, perhaps it should be removed entirely.

## Verdict

**PARTIALLY VALID — KEEP MINIMAL CHECKPOINT, CUT SCOPE**

Checkpoint is useful for restoring private runner working state and avoiding
expensive reconstruction as runtime complexity grows.

But it must remain an optimization.

V0.2 should reduce checkpoint ambitions:

- one versioned private snapshot contract;
- checkpoint only at semantic durable boundaries;
- no checkpoint-based business-state restoration;
- no complex retention algorithm in Stage 3.2;
- no checkpoint compaction framework;
- no replay engine;
- no "rollback to checkpoint".

Correctness tests must pass even if the latest checkpoint is missing or stale,
provided authoritative durable facts are intact.

This turns checkpoint from a second persistence system into a bounded runtime
optimization.

---

# 6. Challenge AR-05 — ExternalAction duplicates ToolCall

## Attack

Why not add a few fields to ToolCall:

- operation_id;
- status;
- reconciliation metadata;

and avoid another table/state machine?

## Verdict

**REJECTED**

ToolCall and ExternalAction answer different questions.

```text
ToolCall:
"What logical tool request did the runtime accept?"

ExternalAction:
"What durable real-world effect operation exists?"
```

A ToolCall may:

- be READ-only and have no ExternalAction;
- be denied/not executed;
- map to one stable action across multiple physical attempts.

An ExternalAction needs semantics that should not infect every ToolCall:

- operation identity;
- immutable action snapshot;
- UNKNOWN;
- reconciliation;
- external resource evidence;
- manual resolution.

Keeping the split is justified.

However V0.2 must define the projection table precisely so the duplication does
not become contradictory state.

---

# 7. Challenge AR-06 — ReconciliationAttempt is another unnecessary table

## Attack

Could reconciliation history simply be DomainEvents plus fields on
ExternalAction?

## Verdict

**REJECTED FOR PHYSICAL ATTEMPT HISTORY, BUT KEEP IT SMALL**

Reconciliation is real external I/O with:

- retries;
- timeouts;
- timestamps;
- errors;
- potentially different evidence each time.

A single mutable field loses operational history, while DomainEvent payloads
alone make querying and invariants weak.

A small append-oriented ReconciliationAttempt model is justified.

Do not turn it into a generic job table.

---

# 8. Challenge AR-07 — Manual Review belongs entirely in Stage 3.3 Governance

## Attack

Stage 3.2 has no RBAC, approver role, or operator UI.

Why implement manual resolution now?

## Verdict

**PARTIALLY VALID — DOMAIN BOUNDARY NOW, PRODUCT WORKFLOW LATER**

Manual review is unavoidable when:

- reconciliation mode is NONE;
- BEST_EFFORT reconciliation remains inconclusive;
- external evidence conflicts.

Stage 3.2 therefore needs the domain/application capability to represent and
resolve unresolved action truth.

Stage 3.2 should **not** add:

- public operator UI;
- enterprise roles;
- approval inbox;
- notification workflow;
- generic human task management.

Those remain Stage 3.3.

P0 Stage 3.2 needs only:

- MANUAL_REVIEW durable state;
- ActionResolution fact;
- controlled internal/application command;
- deterministic tests.

---

# 9. Challenge AR-08 — Budget is unrelated scope creep

## Attack

Side-effect safety is already complex. Budget/deadline can be implemented later.

## Verdict

**PARTIALLY VALID — KEEP ONLY SAFETY-RELEVANT MINIMUM**

Budget is useful because uncontrolled retries/model loops are production
runtime concerns.

But V0.1 should not grow a general billing/quota platform.

Stage 3.2 should keep only:

- max_model_invocations;
- max_tool_attempts;
- absolute `deadline_at`.

Explicitly defer:

- dollar-cost budget;
- organization quota;
- per-provider price tables;
- token forecasting;
- dynamic budget reallocation;
- budget hierarchy.

Reconciliation safety work must be separately bounded so ordinary task budget
cannot block correctness recovery.

---

# 10. Challenge AR-09 — Build a generic RetryPolicy DSL

## Attack

Model, READ, side-effect, and reconciliation retries differ. A generic policy
engine could encode all combinations cleanly.

## Verdict

**REJECTED FOR STAGE 3.2**

A generic retry DSL would create framework complexity before requirements are
stable.

V0.2 should define a small typed policy with explicit categories:

- model transient retry;
- READ transient retry;
- side-effect retry after proven NOT_EXECUTED;
- reconciliation retry.

Use fixed bounded exponential/backoff parameters in versioned config.

Do not build:

- expression language;
- arbitrary predicates;
- user scripting;
- pluggable retry strategy marketplace.

---

# 11. Challenge AR-10 — ActionSnapshot digest is premature Stage 3.3 work

## Attack

Approval does not exist yet. Why freeze canonical digest in Stage 3.2?

## Verdict

**REJECTED, WITH SCOPE LIMIT**

The digest belongs at the point where the action becomes immutable, not later
when approval is added.

If Stage 3.2 executes side effects without a stable canonical action identity,
Stage 3.3 would either:

- change historical action identity;
- require migration/backfill;
- or approve a representation different from the executed representation.

Therefore canonical snapshot + digest belongs in Stage 3.2.

But only one minimal canonical format version is needed now.

Do not build a generic signing/notarization system.

---

# 12. Challenge AR-11 — Serial side effects per Run destroy throughput

## Attack

A production Agent may need to create many Jira tickets or send many emails.
Why force one active side effect per Run?

## Verdict

**VALID LIMITATION, KEEP FOR P0**

Parallel side effects multiply:

- partial completion states;
- cancellation semantics;
- budget races;
- approval binding;
- recovery ordering;
- reconciliation fan-out;
- late-result conflicts.

Stage 3.2's goal is correctness, not maximum throughput.

Keep:

> at most one nonterminal ExternalAction per Run in P0.

Document it as an intentional throughput limitation.

Parallel action branches are a post-MVP concern.

---

# 13. Challenge AR-12 — Custom Postgres queue/lease is already too much infrastructure

## Attack

The project is drifting from Agent Runtime into distributed-systems
infrastructure.

## Verdict

**VALID WARNING, NO REVERSAL**

Stage 3.1 already froze the Postgres lease/generation substrate.

Stage 3.2 should reuse it, not broaden it.

Explicitly defer:

- multi-region leases;
- shard-aware scheduling;
- priority scheduler framework;
- autoscaling controller;
- worker pools by capability;
- distributed cron service;
- queue fairness research beyond simple stable ordering.

The custom substrate exists only to support AgentForge semantics.

---

# 14. Challenge AR-13 — Why not use only mocked external systems in acceptance?

## Attack

Real Jira/email integration adds network flakiness and credentials to CI.

Mocks are deterministic and sufficient for state-machine testing.

## Verdict

**VALID FOR STAGE 3.2 ACCEPTANCE**

Stage 3.2 should use deterministic fake external systems that can simulate exact
crash windows and ambiguous outcomes.

Real SaaS integration is not required for the durable-semantics acceptance
gate.

However the fake must be behaviorally strong:

- persist its own external operation ledger;
- enforce operation_id/idempotency behavior;
- simulate response loss after effect commit;
- provide authoritative/best-effort/none reconciliation modes;
- count physical calls;
- expose external resource ids;
- simulate delayed late results.

A weak mock that merely returns predefined strings would not validate the
design.

---

# 15. Challenge AR-14 — Side effects before Auth/Policy are inherently unsafe

## Attack

Stage 3.3 owns governance. Stage 3.2 should not execute any side effect at all.

## Verdict

**PARTIALLY VALID — RESTRICT EXECUTABLE TOOL CLASS**

Stage 3.2 needs side-effect execution to validate durable semantics.

But only explicitly safe-for-no-approval test/demo side effects may execute.

Stage 3.2 must fail closed for:

- DESTRUCTIVE effect;
- approval_required;
- policy-dependent high-risk tool;
- missing credential authorization boundary.

This preserves security architecture while allowing durable semantics to be
implemented before full governance.

---

# 16. Challenge AR-15 — Reconciliation NONE makes the system operationally unusable

## Attack

If a provider offers no lookup/idempotency support, every timeout becomes human
work.

Why support such tools?

## Verdict

**ACCEPT THE COST, MAKE CAPABILITY EXPLICIT**

The alternative is worse: silently risk duplicate real-world effects.

ToolVersion capability metadata should make the limitation visible before
execution.

A future policy may forbid certain NONE-reconciliation side effects in
production.

Stage 3.2 should represent the truth, not fake reliability the provider does
not offer.

---

# 17. Challenge AR-16 — DomainEvent, attempt tables, action rows, and resolutions are too much duplication

## Attack

Could the system use pure event sourcing and derive everything?

Or keep only current state and logs?

## Verdict

**REJECT BOTH EXTREMES**

The frozen Stage 2 architecture already chose:

```text
relational current state
+
append facts/events
!= full event sourcing
```

That remains appropriate.

Current-state rows are needed for locking, indexing, scheduling, and invariant
enforcement.

Append facts are needed for auditability and debugging.

V0.2 should avoid duplicating large payloads across both:

- store authoritative structured data once;
- events reference identifiers and concise transition facts;
- snapshots/results use redacted structured JSON where required.

---

# 18. Challenge AR-17 — All physical tool calls using ToolExecutionAttempt is needless refactoring

## Attack

READ works already in Stage 3.1. Why touch it?

## Verdict

**REJECTED — UNIFY IN STAGE 3.2**

A physical invocation is the same operational concept regardless of effect
type.

Without unification:

- max_tool_attempts means different things;
- retry history has two models;
- metrics differ;
- late-result/fencing logic diverges.

V0.2 should add ToolExecutionAttempt for READ while preserving the frozen
logical ToolCall behavior.

This is a controlled internal extension, not a rewrite of Stage 3.1 semantics.

---

# 19. Challenge AR-18 — Why not let the model decide whether retry is safe?

## Attack

Modern models can inspect the error and decide whether to retry or query the
external system.

## Verdict

**REJECTED — VIOLATES CORE THESIS**

Retry safety is an authorization/correctness decision, not a reasoning
suggestion.

The model may propose a new business action after the runtime reaches a safe
stable state.

The model may not decide:

- UNKNOWN means NOT_EXECUTED;
- duplicate side effect risk is acceptable;
- reconciliation can be skipped;
- cancellation can be ignored;
- a stale worker may progress.

Those decisions remain deterministic runtime policy.

---

# 20. Scope cuts required for V0.2

The following cuts are mandatory to keep Stage 3.2 from becoming a generic
workflow platform.

## Keep in Stage 3.2

- ToolExecutionAttempt for all physical tool calls;
- ExternalAction;
- ActionSnapshot + one canonical digest format;
- UNKNOWN;
- ReconciliationAttempt;
- ActionResolution domain fact;
- cancellation;
- minimal retry/backoff;
- minimal budget/deadline;
- minimal checkpoint/resume;
- crash/takeover/late-result rules;
- deterministic fake external system;
- PostgreSQL enforcement and target acceptance.

## Explicitly defer

- Temporal integration;
- generic workflow/DAG language;
- concurrent side-effect branches;
- cost/billing budget;
- organization quotas;
- generic retry DSL;
- manual-review UI;
- RBAC/enterprise auth;
- approval inbox/workflow;
- generic policy engine;
- real Jira/email SaaS acceptance;
- multi-region scheduling;
- queue sharding;
- checkpoint compaction framework;
- event sourcing;
- unrestricted operator "force" endpoints.

---

# 21. Architectural clarifications required for V0.2

The next design revision must make these normative, not advisory:

1. **Run-row lock is the global per-Run progression serialization point.**
2. **Action Commit Boundary transaction** defines cancel/budget/fencing winner.
3. **Separate state machines** for ToolCall, ToolExecutionAttempt,
   ExternalAction, ReconciliationAttempt, and ActionResolution.
4. **Exact ToolCall projection table** from ExternalAction.
5. **Exact late-result winner rule** after takeover/reconciliation/resolution.
6. **Exact terminal Run × ExternalAction matrix.**
7. **Versioned canonical ActionSnapshot digest.**
8. **Credential resolution only at adapter edge.**

---

# 22. Product-positioning conclusion

The adversarial review changes one important framing.

AgentForge should not claim:

> "We built a workflow engine for Agents."

The stronger and narrower claim is:

> "We built the deterministic runtime semantics that safely map probabilistic
> Agent decisions onto durable real-world actions. PostgreSQL is the initial
> execution substrate; another durable workflow substrate could be integrated
> later without changing those semantics."

This keeps the project differentiated from:

- Temporal;
- Celery;
- LangGraph;
- generic orchestration frameworks.

The project value is the correctness model around Agent side effects.

---

# 23. Adversarial-review gate decision

```text
Stage 3.2 Design V0.1
❌ NOT ACCEPTED

Draft
✅ COMPLETE

Self Review
✅ COMPLETE

Scenario Validation
✅ COMPLETE

Adversarial Review
✅ COMPLETE

Design Modification
🔓 UNLOCKED

Design V0.2
🔒 UNTIL MODIFICATION IS WRITTEN

Re-review
🔒

Design Acceptance / Freeze
🔒

Implementation
🔒
```

The next phase may now modify the design. It must resolve the self-review,
scenario-validation, and adversarial findings together rather than patching
them independently.
