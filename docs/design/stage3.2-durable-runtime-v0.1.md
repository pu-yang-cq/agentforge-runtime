# Stage 3.2 Durable Runtime — Design V0.1

Status: **DRAFT — NOT ACCEPTED**
Parent baseline: **Stage 3.1 Core Runtime V1.0 — ACCEPTED / FROZEN**

This document is the first design draft for Stage 3.2. It is intentionally
not an implementation plan approval. It must still pass self-review, scenario
validation, adversarial review, revision, re-review, and explicit acceptance.

## 1. Goal

Stage 3.2 extends the accepted READ-only Core Runtime into a durable runtime
that can safely execute real side effects and survive crashes, retries,
cancellation, uncertain external outcomes, worker takeover, and process
restart without inventing exactly-once guarantees.

The central invariant is:

> A probabilistic model may propose an external effect, but only the durable
> runtime may authorize, record, execute, reconcile, retry, or resolve it.

Stage 3.2 must preserve every accepted Stage 3.1 invariant.

## 2. Scope

Stage 3.2 adds:

- durable checkpoint / resume;
- retry policy and durable retry scheduling;
- run budgets and durable deadlines;
- cancellation as a durable request;
- side-effect Tool support;
- ToolExecutionAttempt;
- ExternalAction;
- ActionSnapshot + canonical digest;
- UNKNOWN external outcomes;
- reconciliation;
- manual action resolution at the application/domain boundary;
- late-result handling;
- durable recovery precedence;
- one-active-side-effect invariant;
- failure taxonomy needed by recovery.

Stage 3.2 does **not** add:

- user-facing approval workflows;
- authorization / enterprise IAM;
- live platform policy enforcement;
- MCP client;
- OpenAI production adapter;
- frontend;
- eval expansion;
- unrestricted networking;
- multi-agent orchestration.

Approval, policy, and auth remain Stage 3.3 concerns. Stage 3.2 must however
leave stable domain boundaries for them.

## 3. Non-negotiable semantics

### 3.1 No global exactly-once claim

AgentForge provides:

- durable intent;
- stable operation identity;
- at-least-once execution where safe;
- idempotency where supported;
- reconciliation where available;
- explicit UNKNOWN when execution cannot be proven;
- manual resolution when uncertainty cannot be eliminated.

An ExternalAction is never presented as exactly-once merely because AgentForge
itself wrote one database row.

### 3.2 Intent before effect

For every side effect, durable facts must exist before any external call:

```text
ToolProposal
    ↓
ToolCall
    ↓
ActionSnapshot + digest
    ↓
ExternalAction(operation_id, READY)
    ↓ COMMIT
Action Commit Boundary
    ↓
ExternalAction(EXECUTING) + ToolExecutionAttempt
    ↓ COMMIT
External call
```

The database transaction must never be held open across the external call.

### 3.3 Persisted facts before new reasoning

Recovery always consumes durable facts before asking the model to decide again.

A stale checkpoint can never overwrite a newer ExternalAction,
ToolExecutionAttempt, ActionResolution, cancellation request, or committed
message/event.

### 3.4 UNKNOWN is a first-class state

If the runtime cannot prove whether an external side effect occurred, the
action is UNKNOWN. UNKNOWN is not FAILED.

UNKNOWN must be reconciled before any retry that could duplicate the effect.

### 3.5 Cancellation is not rollback

Cancellation prevents new progression. It does not erase a side effect that
already crossed the Action Commit Boundary and does not imply that an external
system rolled anything back.

## 4. Runtime state extensions

### 4.1 Run states

Stage 3.2 uses the frozen architecture state set:

```text
CREATED
QUEUED
RUNNING
WAITING_ACTION_RESOLUTION
COMPLETED
FAILED
CANCELLED
```

`WAITING_APPROVAL` remains reserved for Stage 3.3 and is not entered by
Stage 3.2 runtime logic.

`cancel_requested` remains an orthogonal durable flag, not an immediate state
transition.

### 4.2 ToolCall states

```text
CREATED
READY
EXECUTING
UNRESOLVED
DENIED
SUCCEEDED
FAILED
NOT_EXECUTED
```

READ ToolCalls keep the Stage 3.1 deterministic recovery semantics.

For side-effect ToolCalls, final business outcome is projected from the linked
ExternalAction.

### 4.3 ExternalAction states

```text
READY
EXECUTING
UNKNOWN
RECONCILING
MANUAL_REVIEW
SUCCEEDED
FAILED
ABORTED
```

`PENDING_APPROVAL` is reserved for Stage 3.3.

Allowed high-level progression:

```text
READY → EXECUTING
EXECUTING → SUCCEEDED | FAILED | UNKNOWN
UNKNOWN → RECONCILING
RECONCILING → SUCCEEDED | FAILED | READY | MANUAL_REVIEW
READY → ABORTED             # only before a new attempt crosses commit boundary
MANUAL_REVIEW → SUCCEEDED | FAILED | ABORTED
```

A side-effect action never moves directly from UNKNOWN to EXECUTING.

## 5. External action identity

Every ExternalAction has a globally unique `operation_id`.

The same logical action keeps the same `operation_id` across safe retries.
A retry creates a new ToolExecutionAttempt, not a new ExternalAction.

External adapters receive `operation_id` as the preferred idempotency key
when the target system supports it.

The action also stores:

- run_id;
- tool_call_id;
- tool_version_id;
- snapshot_id;
- action_digest;
- reconciliation_mode;
- current_attempt_id;
- status;
- last_error;
- created_at / updated_at.

## 6. Action snapshot

Before execution, the runtime canonicalizes and persists an immutable
ActionSnapshot containing at minimum:

- exact ToolVersion identity;
- canonical tool arguments;
- effect type;
- operation_id;
- runtime-relevant execution metadata.

The snapshot has a stable digest.

Stage 3.2 does not use this digest for approval yet, but Stage 3.3 approval will
bind to this exact digest. Therefore the snapshot must already be immutable in
Stage 3.2.

Secrets are references, not copied secret values.

## 7. ToolExecutionAttempt

Each physical invocation of a tool adapter is an attempt.

Minimum fields:

- id;
- run_id;
- tool_call_id;
- external_action_id when applicable;
- attempt_number;
- execution_generation;
- started_at;
- finished_at;
- status;
- error_class;
- error_detail;
- adapter_metadata.

Attempt numbers are unique per ToolCall / ExternalAction.

For a side effect, the attempt row and `ExternalAction=EXECUTING` must be
committed together before the external adapter is called.

## 8. Crash windows and required recovery

### Window A — action intent committed, attempt not started

Database says `ExternalAction=READY`.

Recovery may start the action, subject to cancellation, budget, live ownership,
and future Stage 3.3 governance checks.

### Window B — EXECUTING committed, external call may or may not have started

An expired owner finding an orphaned `EXECUTING` side effect must not retry
blindly.

It transitions the action to UNKNOWN and starts reconciliation.

### Window C — external system succeeded, result commit was lost

This is also UNKNOWN after takeover.

Reconciliation must discover the external result using operation_id or other
stable evidence.

### Window D — network timeout / transport ambiguity

If the adapter cannot prove "not executed", the result is UNKNOWN.

### Window E — authoritative reconciliation proves NOT_EXECUTED

The action may return to READY and create a new attempt.

### Window F — reconciliation proves SUCCEEDED / FAILED

The durable action is finalized without a second external call.

### Window G — reconciliation cannot decide

AUTHORITATIVE mode: adapter contract violation / runtime failure if it cannot
produce a definitive supported answer.

BEST_EFFORT or NONE: action moves to MANUAL_REVIEW and the Run moves to
WAITING_ACTION_RESOLUTION unless already terminal under the frozen
post-terminal resolution rule.

## 9. Reconciliation contract

ToolVersion declares one of:

```text
AUTHORITATIVE
BEST_EFFORT
NONE
```

The side-effect adapter exposes a reconcile operation returning a normalized
result:

```text
SUCCEEDED
FAILED
NOT_EXECUTED
UNKNOWN
```

Only authoritative `NOT_EXECUTED` proof permits an automatic retry of a
non-idempotent action.

BEST_EFFORT UNKNOWN never turns into a blind retry.

NONE always requires manual review once the action becomes uncertain.

## 10. Manual action resolution

Stage 3.2 implements the application/domain command but not the final
role-protected public API.

A resolution records:

- action_id;
- resolution outcome;
- evidence;
- reason;
- resolver principal placeholder / system identity;
- timestamp.

Resolution is append-only and auditable.

A resolution never reopens a terminal Run.

## 11. Recovery precedence

On claim / takeover / resume, recovery executes in this order:

```text
1. If terminal Run:
      no autonomous progression.
      unresolved post-terminal action may still accept operator resolution.

2. If orphaned side-effect action exists:
      resolve/reconcile it first.

3. If cancel_requested:
      create no new model invocation or new external action.

4. If orphaned READ ToolCall exists:
      deterministic retry of the same durable call.

5. If retry/backoff is not yet due:
      release/yield until available_at.

6. If budget/deadline prohibits new work:
      stop progression.

7. Restore checkpoint as an optimization index only.

8. Continue normal model/runtime progression.
```

This precedence is normative.

## 12. Checkpoint / resume

Checkpoint is not a second system of record.

A checkpoint stores a private runtime snapshot:

- schema_version;
- runner_version;
- run_state_version;
- execution specification identity;
- working-state cursor;
- message high-water mark;
- event high-water mark;
- context cursor;
- created_at.

Checkpoints must never duplicate authoritative ExternalAction outcome,
cancellation state, ToolCall outcome, or message/event truth.

A checkpoint may be stale. Recovery overlays newer durable facts on top of it.

Initial Stage 3.2 policy: checkpoint after safe durable boundaries rather than
after every SQL mutation.

Safe examples:

- after a Tool result has been committed;
- after a model decision and its consequence are committed;
- before a durable wait/yield;
- after action resolution has been committed.

## 13. Retry policy

Retry decisions are explicit runtime decisions, never hidden SDK behavior.

Normalized failure classes:

```text
TRANSIENT
PERMANENT
POLICY_DENIED
BUDGET_EXCEEDED
CANCELLED
UNKNOWN_OUTCOME
```

READ operations may retry transient failures according to bounded policy.

Model provider transient failures may create a new ModelInvocation after a
durable failed invocation.

Side effects:

- never retry UNKNOWN blindly;
- idempotent action retry still uses the same operation_id;
- non-idempotent retry requires authoritative NOT_EXECUTED proof;
- retries create new ToolExecutionAttempt rows;
- backoff uses durable `available_at` and PostgreSQL server time.

## 14. Budget and deadline

Stage 3.2 introduces a frozen per-Run BudgetConfig / durable BudgetUsage.

P0 budget dimensions:

- max model invocations;
- max tool attempts;
- max total runtime deadline.

Optional token/cost fields may be recorded when provider usage is available,
but cost-based enforcement is not required for Stage 3.2 acceptance.

Budget is checked before starting new work.

Budget exhaustion never rewrites an already executing external attempt into
"not executed".

If unresolved action recovery is required, action safety takes precedence over
budget termination.

## 15. Cancellation

`POST /runs/{id}/cancel` or the equivalent application command sets a durable
`cancel_requested` fact.

Rules:

- cancellation is idempotent;
- no new model call after cancellation is observed;
- no new ExternalAction after cancellation is observed;
- a READY side-effect action that has not crossed Action Commit may be ABORTED;
- an EXECUTING action is not assumed rolled back;
- late result of an already authorized attempt may still update the action;
- if that attempt becomes uncertain, reconciliation still runs;
- after safe stabilization, Run becomes CANCELLED;
- a CANCELLED Run never reopens.

## 16. Late results and fencing

Lease + generation remains the authority for progression.

A stale worker may not:

- create a new model consequence;
- create a new action;
- start a new attempt;
- enqueue new progression.

A late result belonging to an already committed attempt is evidence, not new
authority.

It may update the same action only if the attempt is still the current
authorized attempt and the state transition is still valid. Otherwise it is
recorded as late/conflicting evidence and does not advance the Run.

## 17. Concurrency invariants

Stage 3.2 retains Stage 3.1 single-Run serial progression.

Additional database invariants:

- at most one nonterminal ExternalAction per Run;
- at most one current side-effect attempt per ExternalAction;
- one active side-effect action implies no simultaneous new ModelInvocation;
- operation_id globally unique;
- action snapshot immutable;
- one current owner/generation controls progression.

Side effects are serial within one Run in P0.

## 18. Database-time rule

The Stage 3.1 rule remains frozen:

> durable correctness time comes from PostgreSQL, not worker local clocks.

This covers:

- lease expiry;
- retry `available_at`;
- durable deadline;
- takeover;
- reconciliation scheduling.

## 19. Data model additions

Planned persistence additions:

```text
checkpoints
tool_execution_attempts
external_actions
action_snapshots
reconciliation_attempts
action_resolutions
budget_configs / budget_usage (or equivalent frozen run-level representation)
```

Existing tables are extended only through forward migrations. Stage 3.1
migrations are not rewritten after freeze.

## 20. API / application boundary

Stage 3.2 may add:

- durable cancel command;
- internal/application action resolution command;
- action/read projections needed by tests and future operator API.

Stage 3.2 does not add a public unprotected "force retry", "set action status",
"resume", or "execute tool" endpoint.

Recovery is runtime-controlled.

## 21. Implementation strategy

Implementation should proceed in narrow slices:

```text
A. checkpoint + retry + budget + cancel
B. side-effect domain model + persistence
C. intent-before-effect execution
D. UNKNOWN + reconciliation
E. crash/takeover/late-result recovery
F. full target acceptance
```

Each slice must preserve Stage 3.1 regression tests.

Before Stage 3.2 coding starts, the accepted RC4 source should be materialized
into a normal source tree on a Stage 3.2 development branch while the
`stage3.1-v1.0-frozen` branch remains untouched.

## 22. Open questions for self-review

Design V0.1 deliberately leaves these for the next review phase:

- whether BudgetConfig / BudgetUsage should be dedicated tables or run-level
  immutable/mutable columns;
- exact checkpoint cadence and retention policy;
- exact representation of reconciliation "NOT_EXECUTED";
- whether MANUAL_REVIEW should coexist with terminal CANCELLED/FAILED immediately
  or require WAITING_ACTION_RESOLUTION first;
- whether all READ executions should be migrated onto ToolExecutionAttempt in
  Stage 3.2 or only side-effect executions initially;
- exact late-result conflict evidence table/event representation;
- retry policy shape and maximums for model vs READ vs side-effect attempts.

No open question may remain correctness-critical at Stage 3.2 design freeze.
