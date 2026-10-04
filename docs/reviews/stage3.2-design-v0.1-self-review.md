# Stage 3.2 Durable Runtime — Design V0.1 Self-Review

Status: **SELF-REVIEW COMPLETE — V0.1 NOT ACCEPTED**
Reviewed documents:

- `docs/design/stage3.2-durable-runtime-v0.1.md`
- `docs/acceptance/stage3.2-acceptance-v0.1.md`

Parent baseline:

- Stage 3.1 Core Runtime V1.0 — ACCEPTED / FROZEN

This review intentionally does not edit Design V0.1. Findings are recorded
first so that scenario validation and adversarial review can test the same
unmodified draft. The design will be revised only after those phases.

## 1. Review result

Design V0.1 **does not pass self-review yet**.

Finding count:

- Blocker: 10
- Major: 9
- Minor / clarification: 5

No implementation work should start.

## 2. What V0.1 gets right

The draft correctly establishes several foundation rules that should survive
revision:

1. no global exactly-once claim;
2. durable intent before any external side effect;
3. no database transaction held across external I/O;
4. UNKNOWN is distinct from FAILED;
5. UNKNOWN precedes any potentially duplicating retry;
6. cancellation is not rollback;
7. persisted facts outrank stale checkpoints and new model reasoning;
8. operation_id is stable across attempts of one logical action;
9. PostgreSQL server time remains authoritative for durable timing;
10. Stage 3.1 invariants remain regression requirements.

These are accepted as review anchors, not yet as a frozen Stage 3.2 design.

---

# 3. Blockers

## SR-B01 — Side-effect retry state machine is incomplete

V0.1 allows:

```text
EXECUTING → SUCCEEDED | FAILED | UNKNOWN
```

but also says a definite retryable side-effect failure may retry.

Those two statements are inconsistent. If `FAILED` is terminal, there is no
legal state transition for a physical attempt that definitely did not execute
the effect but failed transiently.

The revised design must distinguish:

- physical attempt failure;
- logical ExternalAction terminal failure;
- definite NOT_EXECUTED / pre-effect transient failure;
- retry scheduling.

Likely direction:

```text
Attempt FAILED(definite-not-executed, retryable)
        ↓
ExternalAction READY + durable backoff
```

while `ExternalAction FAILED` remains a terminal logical outcome.

This must be resolved before implementation.

## SR-B02 — Reconciliation result and reconciliation transport failure are mixed

V0.1 defines reconciliation result:

```text
SUCCEEDED | FAILED | NOT_EXECUTED | UNKNOWN
```

but does not distinguish that from a failed reconciliation *request* such as:

- timeout;
- provider 503;
- connection reset;
- malformed response.

A reconciliation transport failure does not mean the business action is
UNKNOWN in a new sense and must not finalize the ExternalAction.

The revised design needs a separate `ReconciliationAttempt` lifecycle and two
layers:

1. attempt execution status;
2. normalized reconciliation business result.

Reconciliation itself must use durable backoff and bounded retry.

## SR-B03 — Action Commit Boundary is not atomic enough in the written design

The frozen architecture requires the commit boundary to re-check, under the
correct lock order:

- current Run ownership/generation;
- lease validity;
- cancel_requested;
- action state;
- current attempt absence;
- budget permission;
- future Stage 3.3 approval/policy conditions.

V0.1 only says execution is "subject to" cancellation/budget.

That is insufficient for the race:

```text
Worker A reads cancel_requested = false
Operator requests cancel
Worker A commits EXECUTING
External effect occurs
```

The revised design must require one transaction that locks the Run and
ExternalAction, re-checks cancellation and fencing, reserves budget, creates
the attempt, sets EXECUTING, appends the event, and commits before external I/O.

## SR-B04 — Late-result semantics are underspecified

V0.1 says a stale worker result "may update" the same action when the attempt is
still current.

This is too vague for races among:

- old worker result;
- takeover transition to UNKNOWN;
- reconciliation start/result;
- operator manual resolution.

Required rule must define an atomic winner.

Proposed review direction:

- before takeover changes EXECUTING → UNKNOWN, the authorized current attempt
  may still finalize;
- after UNKNOWN/RECONCILING/MANUAL_REVIEW or a newer resolution is committed,
  the old attempt result becomes evidence only;
- stale result ingestion must never enqueue progression;
- conflict evidence must be durable.

## SR-B05 — MANUAL_REVIEW vs terminal Run semantics are unresolved

The frozen architecture permits post-terminal operator resolution for
FAILED/CANCELLED Runs, but COMPLETED cannot contain unresolved action state.

V0.1 does not decide whether:

```text
Run CANCELLED + ExternalAction MANUAL_REVIEW
```

is an allowed stable state, or whether the Run must remain
`WAITING_ACTION_RESOLUTION` until the operator resolves it.

This is correctness-critical because it affects cancellation, queue behavior,
terminalization guards, and operator workflows.

A precise matrix is required for:

- RUNNING;
- WAITING_ACTION_RESOLUTION;
- FAILED;
- CANCELLED;
- COMPLETED

against every nonterminal ExternalAction state.

## SR-B06 — ToolExecutionAttempt state machine is missing

V0.1 introduces ToolExecutionAttempt but does not define its statuses and legal
transitions.

At minimum the revised design must distinguish:

```text
STARTED
SUCCEEDED
FAILED
UNKNOWN
```

and define whether NOT_EXECUTED is:

- an attempt outcome;
- a reconciliation outcome;
- an action outcome;
- or some combination.

Without this, attempt uniqueness, late results, budgets, and retry accounting
cannot be implemented consistently.

## SR-B07 — ToolCall ↔ ExternalAction projection is not defined

V0.1 says side-effect ToolCall outcome is projected from ExternalAction but
does not provide the projection table.

The design must state exactly what ToolCall status corresponds to:

- ExternalAction READY;
- EXECUTING;
- UNKNOWN;
- RECONCILING;
- MANUAL_REVIEW;
- SUCCEEDED;
- FAILED;
- ABORTED.

In particular, `ToolCall.UNRESOLVED` and `ToolCall.NOT_EXECUTED` currently
have no exact projection rule.

## SR-B08 — Snapshot digest is not reproducible enough for future approval binding

V0.1 says ActionSnapshot is canonicalized and hashed but does not freeze:

- canonical serialization algorithm/version;
- key ordering;
- number handling;
- UTF-8 normalization;
- included/excluded fields;
- hash algorithm;
- whether credential references participate;
- whether operation_id participates.

Because Stage 3.3 approval will bind to this digest, ambiguity here would create
an approval-integrity bug later.

The revised design must define a versioned canonical snapshot format and
digest algorithm now.

## SR-B09 — Cross-table single-progression invariant lacks an enforcement mechanism

The design requires:

- no new ModelInvocation while an unresolved ExternalAction exists;
- one side-effect progression path per Run.

As learned in Stage 3.1, a partial unique index cannot express all cross-table
invariants.

The revised design must explicitly preserve the Stage 3.1 pattern:

> every progression-start transaction locks the Run row first and performs
> cross-table active-work checks under that lock.

This must cover model start, READ retry, action start, reconciliation start,
and recovery transitions.

## SR-B10 — High-risk tool behavior is unsafe before Stage 3.3 unless fail-closed

Stage 3.2 deliberately excludes approval/policy.

V0.1 currently says "side-effect Tool support" without deciding what happens to
a ToolVersion that is:

- DESTRUCTIVE;
- marked approval-required;
- or otherwise governance-dependent.

Stage 3.2 must not create a temporary insecure execution path.

Required review direction:

- Stage 3.2 may execute only side-effect ToolVersions explicitly eligible for
  no-approval Stage 3.2 execution;
- DESTRUCTIVE and approval-required tools must fail closed / remain
  NOT_EXECUTED until Stage 3.3 governance exists.

---

# 4. Major findings

## SR-M01 — READ attempts should probably use ToolExecutionAttempt too

If READ retries remain outside ToolExecutionAttempt while side effects use it,
then:

- max_tool_attempts is ambiguous;
- retry telemetry differs by effect type;
- physical invocation accounting is inconsistent.

The preferred revision is to model every physical Tool execution as a
ToolExecutionAttempt in Stage 3.2, while preserving Stage 3.1 ToolCall
semantics.

Scenario validation should confirm this does not weaken deterministic READ
recovery.

## SR-M02 — Budget reservation must be atomic with work start

"Check budget before starting work" is not sufficient.

The usage increment/reservation must be committed in the same transaction as:

- ModelInvocation STARTED;
- ToolExecutionAttempt STARTED.

Otherwise a crash or concurrent path can overspend or consume budget without a
corresponding attempt.

Reconciliation safety work also needs a separately bounded retry policy so
"budget does not block reconciliation" cannot create an infinite loop.

## SR-M03 — Deadline must be an absolute DB-derived fact

The design should freeze an absolute `deadline_at` computed using PostgreSQL
time when the Run execution spec is created.

Workers must never recompute deadline from local duration.

The design must also state whether human/manual wait time counts toward the
deadline. P0 should prefer simple absolute wall-clock deadline semantics unless
scenario review finds that unacceptable.

## SR-M04 — Retry scheduling needs one source of truth

V0.1 mentions durable `available_at` but does not define whether it lives on:

- Run;
- ExternalAction;
- attempt;
- retry record.

Because P0 permits only one active progression path per Run, a clean design is
needed so queue scheduling and action retry scheduling cannot disagree.

## SR-M05 — Credential isolation boundary is missing from side-effect execution

Real side-effect adapters need credentials even though end-user auth is Stage
3.3.

The Stage 2 technology baseline already froze a credential resolver boundary.

Stage 3.2 must state:

- snapshot stores credential reference, never secret value;
- model context never receives the secret;
- database events/messages/logs never receive the secret;
- adapter resolves secret only at the execution edge;
- reconciliation uses the same credential boundary.

## SR-M06 — Reconciliation must be based only on durable action facts

The design should explicitly prohibit reconciliation from consulting the model
for operation identity or reconstructing arguments from conversational state.

Reconcile input must come from:

- immutable ActionSnapshot;
- operation_id;
- durable external resource reference/evidence.

This is an extension of Persisted Facts > New Reasoning.

## SR-M07 — Action result / external resource evidence shape is missing

A successful side effect often returns durable identifiers such as:

- Jira issue key;
- email provider message id;
- ticket id;
- remote request id.

These identifiers are central to reconciliation and traceability.

The design needs a normalized persisted result/evidence field with redaction
rules, not only `adapter_metadata`.

## SR-M08 — Manual resolution race with reconciliation is undefined

An operator may resolve MANUAL_REVIEW while a delayed reconciliation response
returns.

The revised design must define locking and winner rules:

- one final ActionResolution;
- final resolution prevents later reconciliation from changing business
  outcome;
- delayed reconciliation becomes evidence/conflict only.

## SR-M09 — Terminalization guards must be extended for ExternalAction

Stage 3.1 already guards terminal Runs against active ModelInvocation /
ToolCall.

Stage 3.2 must extend this.

Likely minimum:

- COMPLETED: no nonterminal ExternalAction or unresolved ToolCall;
- FAILED/CANCELLED: may coexist only with the explicitly permitted
  post-terminal MANUAL_REVIEW form, never EXECUTING/UNKNOWN/RECONCILING;
- no terminal Run has autonomous runnable work.

Exact rules must be frozen.

---

# 5. Minor / clarification findings

## SR-C01 — Canonical operation_id generation should be explicit

Generate once before Action READY persistence, persist it in the same
transaction, and never regenerate on recovery/retry.

## SR-C02 — Checkpoints must explicitly exclude secrets and chain-of-thought

The checkpoint section should inherit the existing rule that private model
chain-of-thought is never persisted.

Checkpoint payload must also exclude resolved credentials.

## SR-C03 — Reconciliation must be defined as read-only

The adapter contract should state that reconcile itself may not create or
modify the business side effect being reconciled.

## SR-C04 — Cancellation after terminal Run needs explicit idempotent behavior

A cancel command against COMPLETED/FAILED/CANCELLED should not mutate business
truth or reopen the Run.

The API/application response semantics can be decided later, but domain
behavior should be explicit.

## SR-C05 — ExternalAction ABORTED meaning needs narrowing

ABORTED should mean the runtime knows the external effect was not executed and
will not execute it, e.g. cancellation before Action Commit.

It must not be used as a synonym for UNKNOWN or "operator does not care".

---

# 6. Acceptance-criteria gaps

The V0.1 acceptance criteria are strong but need additional mandatory cases.

## AC-G01 — cancel vs Action Commit race

Two concurrent transactions:

1. cancellation command;
2. worker trying to cross Action Commit Boundary.

Required: exactly one ordering wins under Run lock; if cancellation commits
first, adapter is never called.

## AC-G02 — manual resolution vs late reconciliation

Once manual resolution finalizes the action, a delayed reconciliation result
cannot overwrite it.

## AC-G03 — late result after takeover transition

After new owner changes EXECUTING → UNKNOWN, old worker result cannot directly
finalize progression.

It may only become evidence according to the final late-result rule.

## AC-G04 — retryable definite-not-executed side-effect failure

Must prove:

- first physical attempt is durable FAILED/NOT_EXECUTED as appropriate;
- logical action remains retryable;
- retry uses same operation_id;
- new attempt_number;
- no duplicate effect.

## AC-G05 — reconciliation transport failure

A failed reconcile HTTP/request attempt must not be confused with a business
FAILED action.

Retry/backoff must survive restart.

## AC-G06 — high-risk fail-closed

An approval-required or DESTRUCTIVE ToolVersion must not execute in Stage 3.2.

## AC-G07 — snapshot digest determinism

Equivalent accepted action data must produce identical versioned digest across
restart/processes.

A material argument/tool-version/operation change must change the digest.

## AC-G08 — credentials never enter model-visible or durable public facts

Tests should use a sentinel secret and assert it is absent from:

- ModelRequest;
- RunMessage;
- DomainEvent;
- ActionSnapshot public fields;
- logs/test projections.

## AC-G09 — terminal Run / unresolved action matrix

Mandatory tests must cover each permitted/disallowed combination, especially
CANCELLED/FAILED + MANUAL_REVIEW and COMPLETED + any unresolved action.

## AC-G10 — generic ToolExecutionAttempt accounting

If the design adopts attempts for READ as recommended, acceptance must prove
READ retry attempt numbers and budget usage are durable and deterministic.

---

# 7. Open-question recommendations

These are recommendations for the later revision phase; they are not yet
changes to Design V0.1.

## Budget representation

Prefer one per-Run durable budget record with immutable limit fields plus
mutable usage counters, or an equally explicit one-to-one representation.

Avoid a globally reusable mutable BudgetConfig entity.

## Checkpoint cadence

Prefer checkpoint at semantically complete durable boundaries only.

Do not checkpoint an in-flight external action as if the checkpoint carried its
truth.

Retention is operational, not correctness-critical; correctness should depend
only on latest compatible checkpoint plus authoritative durable facts.

## NOT_EXECUTED representation

Prefer it as a normalized execution/reconciliation *outcome/evidence* rather
than a long-lived ExternalAction state.

ExternalAction can transition back to READY when retry is allowed, or ABORTED
when the runtime definitively will not execute it.

ToolCall.NOT_EXECUTED can remain the final projection for a never-executed call.

## Manual-review terminal relationship

Scenario review should explicitly compare two designs:

A. keep Run WAITING_ACTION_RESOLUTION until resolution;
B. allow FAILED/CANCELLED + MANUAL_REVIEW as stable post-terminal state.

The frozen Stage 2 architecture suggests B must remain supported at least for
post-terminal resolution, but the exact transition point still needs proof.

## Attempt unification

Prefer ToolExecutionAttempt for both READ and side-effect physical invocations.

This aligns retries, budgets, observability, and late-result handling.

---

# 8. Self-review gate decision

```text
Stage 3.2 Design V0.1
❌ NOT ACCEPTED

Self-Review
✅ COMPLETE

Design Modification
🔒 NOT YET

Scenario Validation
🔓 NEXT

Adversarial / Reverse Challenge
🔒

Design V0.2
🔒

Design Acceptance / Freeze
🔒

Implementation
🔒
```

The next phase must validate the unmodified V0.1 + these findings against
concrete crash/concurrency scenarios before any design rewrite.
