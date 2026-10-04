# Stage 3.2 Durable Runtime — Design V0.2

Status: **REVISED DRAFT — NOT YET ACCEPTED**
Parent baseline: **Stage 3.1 Core Runtime V1.0 — ACCEPTED / FROZEN**

Derived from:

- Design V0.1;
- V0.1 Self-Review;
- V0.1 Scenario Validation;
- V0.1 Adversarial Review.

This revision resolves the correctness blockers discovered before implementation.
It is still not frozen. It must pass re-review and explicit design acceptance.

---

## 1. Stage objective

Stage 3.2 extends the accepted Core Runtime with durable execution semantics for
real-world side effects, retries, crash recovery, cancellation, uncertain
outcomes, reconciliation, and resume.

The defining invariant is:

> Probabilistic model intent never directly causes a real-world effect.
> A deterministic durable runtime must first establish authorization-ready
> durable intent, then cross a transactionally fenced execution boundary.

Stage 3.2 is not a general workflow engine.

It defines AgentForge domain semantics that could later run on a different
durable execution substrate without changing those semantics.

---

## 2. Scope

### In scope

- ToolExecutionAttempt for every physical Tool invocation;
- ExternalAction for side-effecting ToolCalls;
- ActionSnapshot and canonical action digest;
- intent-before-effect execution;
- retry and durable backoff;
- UNKNOWN outcome;
- ReconciliationAttempt;
- ActionResolution domain/application command;
- cancellation;
- minimal Run budget and absolute deadline;
- minimal checkpoint/resume;
- crash/takeover/late-result handling;
- credential-resolution execution boundary;
- deterministic fake external system;
- PostgreSQL invariants and target acceptance.

### Explicitly deferred

- Temporal integration;
- generic workflow/DAG DSL;
- concurrent side-effect branches;
- multi-region scheduling;
- queue sharding;
- cost/billing quotas;
- organization quota hierarchy;
- generic RetryPolicy DSL;
- manual-review UI;
- enterprise RBAC/auth;
- approval workflow;
- generic policy engine;
- real Jira/email SaaS acceptance;
- checkpoint compaction framework;
- event sourcing;
- unrestricted force/retry/resume endpoints.

Stage 3.3 will add governance around the stable action boundaries created here.

---

## 3. Core invariants

### I1 — No global exactly-once claim

AgentForge guarantees durable intent and deterministic recovery semantics, not
global exactly-once external execution.

### I2 — Intent before effect

No side-effect adapter call may occur before:

1. immutable ActionSnapshot exists;
2. stable operation_id exists;
3. ExternalAction READY exists;
4. those facts are committed.

### I3 — Action Commit Boundary

No physical side-effect execution may begin before a second transaction commits:

- current Run ownership/generation validity;
- unexpired lease;
- cancel_requested = false;
- action still READY;
- no current attempt;
- budget reservation;
- ExternalAction -> EXECUTING;
- ToolExecutionAttempt -> STARTED;
- transition event.

Only after this transaction commits may external I/O begin.

### I4 — One per-Run progression serialization point

Every transaction that starts or changes autonomous progression must lock the
Run row first.

This includes:

- starting ModelInvocation;
- starting READ ToolExecutionAttempt;
- starting side-effect ToolExecutionAttempt;
- starting reconciliation;
- takeover recovery transitions;
- cancellation;
- manual action resolution when it changes runnable state.

Cross-table single-progression correctness is protected under this Run lock,
not by independent partial unique indexes alone.

### I5 — UNKNOWN is first-class

UNKNOWN means the runtime cannot prove the real-world effect outcome.

UNKNOWN is not FAILED and never permits blind retry.

### I6 — Persisted facts outrank checkpoints and model reasoning

```text
authoritative durable facts
    >
checkpoint
    >
new model reasoning
```

### I7 — Cancellation is not rollback

Cancellation prevents new autonomous work. It does not undo an already
authorized or externally executed side effect.

### I8 — DB time is authoritative

Lease expiry, backoff, deadline, takeover, and reconciliation scheduling use
PostgreSQL server time.

---

## 4. Domain layers

Stage 3.2 separates six distinct concepts.

### 4.1 Run

Owns overall lifecycle, cancellation, ownership, deadline, and progression
serialization.

### 4.2 ToolCall

Logical accepted Tool request.

A ToolCall exists once per logical model/runtime request, regardless of how
many physical attempts occur.

### 4.3 ToolExecutionAttempt

One physical adapter invocation.

Used for both READ and side-effecting ToolCalls.

### 4.4 ExternalAction

One logical real-world side effect.

Exists only for side-effecting ToolCalls.

Stable across retries of the same logical action.

### 4.5 ReconciliationAttempt

One physical attempt to determine the truth of an uncertain ExternalAction.

### 4.6 ActionResolution

Append-only explicit final human/operator resolution of an unresolved action.

These concepts must not collapse into one shared FAILED state.

---

## 5. Run states

Stage 3.2 uses:

```text
CREATED
QUEUED
RUNNING
WAITING_ACTION_RESOLUTION
COMPLETED
FAILED
CANCELLED
```

`WAITING_APPROVAL` remains reserved for Stage 3.3.

`cancel_requested` remains an orthogonal durable flag.

---

## 6. ToolCall states

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

ToolCall represents logical outcome, not physical attempt lifecycle.

### Projection for READ ToolCalls

- active physical attempt -> EXECUTING;
- durable retry scheduled with no active attempt -> READY;
- final success -> SUCCEEDED;
- final logical failure -> FAILED;
- known never executed and will not execute -> NOT_EXECUTED.

### Projection for side-effect ToolCalls from ExternalAction

| ExternalAction | ToolCall |
|---|---|
| READY | READY |
| EXECUTING | EXECUTING |
| UNKNOWN | UNRESOLVED |
| RECONCILING | UNRESOLVED |
| MANUAL_REVIEW | UNRESOLVED |
| SUCCEEDED | SUCCEEDED |
| FAILED | FAILED |
| ABORTED | NOT_EXECUTED |

This projection is normative.

---

## 7. ToolExecutionAttempt state machine

Each physical Tool invocation has:

```text
STARTED
SUCCEEDED
FAILED
UNKNOWN
```

Legal transitions:

```text
STARTED -> SUCCEEDED
STARTED -> FAILED
STARTED -> UNKNOWN
```

Attempts never return to STARTED.

Attempt fields include:

- id;
- run_id;
- tool_call_id;
- external_action_id nullable;
- attempt_number;
- execution_generation;
- started_at;
- finished_at nullable;
- status;
- error_class nullable;
- definite_not_executed boolean nullable;
- result/evidence metadata redacted;
- adapter metadata redacted.

Attempt number is unique per ToolCall.

For side-effect retries, the same ExternalAction and operation_id are reused.

---

## 8. ExternalAction state machine

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

Legal transitions:

```text
READY -> EXECUTING
READY -> ABORTED

EXECUTING -> SUCCEEDED
EXECUTING -> FAILED
EXECUTING -> READY
EXECUTING -> UNKNOWN

UNKNOWN -> RECONCILING

RECONCILING -> SUCCEEDED
RECONCILING -> FAILED
RECONCILING -> READY
RECONCILING -> MANUAL_REVIEW

MANUAL_REVIEW -> SUCCEEDED
MANUAL_REVIEW -> FAILED
MANUAL_REVIEW -> ABORTED
```

### Meaning of EXECUTING -> READY

This transition is allowed only when the just-finished physical attempt proves:

- the external effect definitely did not execute;
- the failure is retryable;
- retry budget/policy permits another attempt.

The failed physical attempt remains durable as FAILED.

ExternalAction does not become logically FAILED merely because one physical
attempt failed before the effect boundary.

### Meaning of ABORTED

ABORTED means AgentForge knows the external effect did not execute and will not
execute it.

Typical cause: cancellation wins before Action Commit Boundary.

ABORTED must never represent ambiguity.

---

## 9. Stable external action identity

Each ExternalAction has one globally unique `operation_id`.

Rules:

- generated once before ExternalAction READY persistence;
- stored in the same transaction as ActionSnapshot and ExternalAction;
- never regenerated by retry, restart, takeover, or reconciliation;
- passed to adapter as provider idempotency key where supported;
- used as primary stable reconciliation evidence.

Provider idempotency support is a capability, not AgentForge's global
correctness guarantee.

---

## 10. ActionSnapshot and canonical digest

ActionSnapshot is immutable.

### Canonical format V1

Digest input is a UTF-8 encoded canonical JSON object:

```json
{
  "format_version": 1,
  "operation_id": "<uuid>",
  "tool_version_id": "<uuid>",
  "effect_type": "<enum>",
  "arguments": <canonical-json-value>,
  "credential_ref": "<opaque-reference-or-null>"
}
```

Rules:

- object keys sorted lexicographically;
- no insignificant whitespace;
- strings encoded as standard JSON UTF-8;
- booleans/null use JSON representation;
- integers allowed;
- non-integer floating-point values are rejected from V1 action arguments
  unless normalized by Tool schema before snapshot creation;
- arrays preserve order;
- secrets are never included, only opaque credential reference;
- digest algorithm: SHA-256 over exact canonical UTF-8 bytes.

The stored snapshot records `format_version=1`.

Material change to any included field changes the digest.

This digest becomes the future Stage 3.3 approval binding target.

---

## 11. Credential boundary

Resolved credentials exist only at adapter execution/reconciliation edge.

The runtime persists only credential references.

Resolved secret material must never enter:

- ModelRequest;
- RunMessage;
- DomainEvent payload;
- ActionSnapshot canonical data except opaque reference;
- Checkpoint;
- public trace projection;
- structured logs.

Adapter execution:

```text
durable credential_ref
        ↓
CredentialResolver
        ↓
secret in process memory at adapter edge
        ↓
external request
```

Reconciliation follows the same boundary.

---

## 12. Side-effect preparation transaction

When the model proposes an executable side effect:

```text
lock Run
validate current progression authority
validate ToolVersion is Stage-3.2-executable
create ToolCall
create immutable ActionSnapshot
create ExternalAction READY + operation_id
append event
commit
```

No external I/O occurs here.

### Stage-3.2 executable ToolVersion rule

A side-effect ToolVersion may execute in Stage 3.2 only if all are true:

- effect is not DESTRUCTIVE;
- approval_required is false;
- ToolVersion is explicitly marked eligible for no-approval execution;
- credential binding is resolvable through CredentialResolver;
- reconciliation/idempotency metadata is declared.

Otherwise ToolCall becomes NOT_EXECUTED / denied-by-runtime according to the
application error contract.

Stage 3.2 does not temporarily bypass future governance.

---

## 13. Action Commit Boundary transaction

To start a side-effect attempt:

```text
BEGIN
  lock Run
  lock ExternalAction

  verify:
    Run nonterminal
    Run owner/generation current
    lease unexpired by DB time
    cancel_requested = false
    ExternalAction = READY
    no current STARTED ToolExecutionAttempt
    no conflicting active ModelInvocation / READ progression
    task budget permits tool attempt
    deadline permits new business work

  reserve/increment tool-attempt usage
  create ToolExecutionAttempt STARTED
  ExternalAction -> EXECUTING
  current_attempt_id = attempt.id
  ToolCall -> EXECUTING
  append event
COMMIT

external adapter call occurs only now
```

Cancellation uses the same Run lock. Therefore cancel-vs-start has one
transactional ordering.

---

## 14. READ execution boundary

READ ToolCalls also use ToolExecutionAttempt.

To start/retry a READ attempt:

```text
BEGIN
  lock Run
  verify progression/fencing/cancel/budget/deadline
  reserve attempt budget
  create ToolExecutionAttempt STARTED
  ToolCall -> EXECUTING
  append event
COMMIT

invoke READ adapter
```

Stage 3.1 deterministic retry semantics remain unchanged:

- takeover retries the same logical ToolCall;
- exact ToolVersion and arguments are reused;
- no model reasoning occurs before recovered READ is resolved.

---

## 15. Attempt result classification

Adapter result is normalized into one of:

### SUCCEEDED

Physical call completed successfully.

### FAILED, definite_not_executed=true

Runtime has proof the external effect did not occur.

Examples may include validation failure before send or an adapter capability
that can prove request never crossed the effect boundary.

If retryable and policy permits:

- attempt -> FAILED;
- ExternalAction -> READY;
- durable backoff scheduled;
- same operation_id reused.

Otherwise:

- ExternalAction -> FAILED or ABORTED according to reason.

### FAILED, definite_not_executed=false

Not permitted for a side-effect business result.

If execution may have occurred, normalize to UNKNOWN.

### UNKNOWN

Physical call outcome cannot prove external business truth.

ExternalAction -> UNKNOWN.

---

## 16. Reconciliation model

ToolVersion declares:

```text
AUTHORITATIVE
BEST_EFFORT
NONE
```

Reconcile is read-only with respect to the business effect.

It may query external state but must not create/modify the effect being
reconciled.

Reconcile input comes only from durable facts:

- ActionSnapshot;
- operation_id;
- stored external evidence/resource reference;
- credential reference resolved at adapter edge.

The model is never consulted to reconstruct reconciliation identity.

---

## 17. ReconciliationAttempt state machine

Each physical reconciliation request has:

```text
STARTED
SUCCEEDED
FAILED
```

A SUCCEEDED reconciliation attempt carries one normalized business result:

```text
SUCCEEDED
FAILED
NOT_EXECUTED
UNKNOWN
```

A FAILED reconciliation attempt means the reconciliation request itself failed,
for example timeout/503/transport error.

That does not change business truth.

### Start reconciliation

```text
BEGIN
  lock Run
  lock ExternalAction

  verify ExternalAction = UNKNOWN
         or retryable RECONCILING wait is due

  create ReconciliationAttempt STARTED
  ExternalAction -> RECONCILING
  append event
COMMIT
```

### Reconciliation request failure

- attempt -> FAILED;
- action remains unresolved;
- durable reconciliation backoff scheduled;
- bounded safety retry applies.

### Reconciliation business result

AUTHORITATIVE:

- SUCCEEDED -> action SUCCEEDED;
- FAILED -> action FAILED;
- NOT_EXECUTED -> action READY if normal retry policy allows, otherwise ABORTED/FAILED;
- UNKNOWN from an adapter declared authoritative is treated as adapter contract
  violation and moves to MANUAL_REVIEW rather than blind retry.

BEST_EFFORT:

- SUCCEEDED/FAILED/NOT_EXECUTED may be accepted only according to adapter
  capability contract;
- UNKNOWN -> MANUAL_REVIEW.

NONE:

- UNKNOWN action -> MANUAL_REVIEW without external reconcile request.

---

## 18. Reconciliation safety budget

Task budget exhaustion does not block action safety work.

To avoid infinite reconciliation loops, Stage 3.2 defines a separate bounded
safety policy:

- max reconciliation attempts per action;
- bounded exponential backoff;
- after exhaustion -> MANUAL_REVIEW.

This is not part of ordinary `max_tool_attempts`.

---

## 19. Retry model

No generic DSL.

Versioned Run execution configuration contains explicit bounded policies for:

- model transient retry;
- READ transient retry;
- side-effect retry after proven NOT_EXECUTED;
- reconciliation retry.

Retry schedule uses DB-derived `available_at`.

One source of runnable scheduling truth remains on Run because P0 permits one
autonomous progression path per Run.

When action/reconciliation retry is scheduled, Run.queue/available_at reflects
the earliest allowed next autonomous progression.

---

## 20. Budget and deadline

Per Run:

### Immutable limits

- max_model_invocations;
- max_tool_attempts;
- deadline_at.

### Mutable usage

- model_invocations_used;
- tool_attempts_used.

Usage reservation/increment occurs in the same transaction that creates the
corresponding STARTED ModelInvocation/ToolExecutionAttempt.

`deadline_at` is an absolute timestamp established using PostgreSQL server time
when the execution specification is created.

Stage 3.2 uses wall-clock deadline semantics. Human/manual wait time still
passes wall clock.

Unresolved action safety recovery may continue after deadline only to reach a
safe stable unresolved/final state; deadline does not authorize new business
work.

---

## 21. Cancellation

Cancel command:

```text
BEGIN
  lock Run
  if terminal:
      return idempotent terminal result
  set cancel_requested = true

  if ExternalAction READY and no attempt crossed boundary:
      action -> ABORTED
      ToolCall -> NOT_EXECUTED

  append cancel event
COMMIT
```

After cancellation is committed:

- no new ModelInvocation;
- no new business ToolExecutionAttempt;
- no new ExternalAction;
- safety reconciliation of an already uncertain action remains allowed;
- result of an already authorized current attempt may still be recorded under
  late-result winner rules;
- Run terminalizes only after it reaches a stable action state.

Cancellation never reopens a terminal Run.

---

## 22. Late-result winner rule

Late physical results are evidence, not progression authority.

Every result transaction:

```text
lock Run
lock ExternalAction / ToolCall
load referenced Attempt
```

### Current attempt may finalize only when

- referenced attempt is still current;
- logical object is still in the matching EXECUTING state;
- no UNKNOWN/RECONCILING/MANUAL_REVIEW/final resolution transition has already
  committed.

If so, result may update durable business state.

### Otherwise

The result:

- is stored as late/conflicting evidence;
- may finalize the physical attempt record if appropriate;
- must not overwrite ExternalAction business outcome;
- must not enqueue autonomous progression;
- must not restore stale generation authority.

Once takeover commits EXECUTING -> UNKNOWN, an old worker success cannot directly
change ExternalAction to SUCCEEDED.

Reconciliation or manual resolution must decide the action.

---

## 23. Manual resolution

Stage 3.2 implements only domain/application capability.

ActionResolution fields:

- id;
- action_id;
- outcome: SUCCEEDED | FAILED | ABORTED;
- evidence;
- reason;
- resolver identity placeholder;
- created_at.

Resolution transaction:

```text
lock Run
lock ExternalAction

require action = MANUAL_REVIEW
require no prior final ActionResolution

insert ActionResolution
transition ExternalAction to final outcome
project ToolCall
append event
commit
```

A delayed reconciliation result after this commit becomes conflict evidence
only.

Contradictory second resolution is rejected.

---

## 24. Terminal Run × ExternalAction matrix

### COMPLETED

Allowed ExternalAction states:

- none;
- SUCCEEDED;
- FAILED only if Run semantics intentionally treat failed action as handled
  before final completion, which P0 does not do.

P0 rule:

> COMPLETED requires no unresolved or failed required action.

Therefore practical P0 accepted side-effect state for successful task completion
is SUCCEEDED or no action.

COMPLETED may never coexist with:

- READY;
- EXECUTING;
- UNKNOWN;
- RECONCILING;
- MANUAL_REVIEW.

### FAILED

May coexist with:

- final FAILED;
- ABORTED;
- MANUAL_REVIEW only for explicit post-terminal unresolved evidence path.

May not coexist with autonomous runnable READY/EXECUTING/RECONCILING work.

### CANCELLED

May coexist with:

- ABORTED;
- SUCCEEDED from an already-authorized attempt;
- FAILED from an already-authorized attempt;
- MANUAL_REVIEW for post-terminal operator resolution.

May not coexist with READY/EXECUTING/UNKNOWN/RECONCILING at the moment the Run
is terminalized.

### WAITING_ACTION_RESOLUTION

Used while the Run remains nonterminal and action = MANUAL_REVIEW.

### P0 transition preference

If cancellation occurs and uncertainty ultimately reaches MANUAL_REVIEW,
Stage 3.2 permits terminal `CANCELLED + MANUAL_REVIEW` once all autonomous
safety work is exhausted.

The action may later be operator-resolved without reopening the Run.

If the Run is not cancelled/failed, MANUAL_REVIEW places it in
WAITING_ACTION_RESOLUTION.

This preserves the Stage 2 post-terminal resolution rule.

---

## 25. Progression recovery precedence

Normative order on claim/takeover/resume:

```text
1. Terminal Run:
     no autonomous business progression.
     post-terminal MANUAL_REVIEW may accept explicit resolution only.

2. Active EXECUTING side-effect attempt orphaned by lease loss:
     action -> UNKNOWN.

3. UNKNOWN / due RECONCILING action:
     perform safety reconciliation first.

4. cancel_requested:
     no new business/model work.
     stabilize action; abort READY action if applicable; terminalize when safe.

5. orphaned READ ToolCall / attempt:
     deterministic retry same logical ToolCall.

6. durable retry/backoff not due:
     release/yield until Run.available_at.

7. task budget/deadline prevents new work:
     stop business progression and terminalize according to failure/cancel rules.

8. restore compatible checkpoint private state.

9. continue normal model progression.
```

No model reasoning precedes unresolved durable action safety work.

---

## 26. Checkpoint V1

Checkpoint remains optional for correctness.

Fields:

- schema_version;
- runner_version;
- run_state_version;
- execution_spec identity;
- working_state;
- message_high_water;
- event_high_water;
- context_cursor;
- created_at.

Checkpoint excludes:

- chain-of-thought;
- resolved credentials;
- authoritative action outcome;
- cancellation truth;
- ToolCall outcome truth.

Checkpoint cadence:

- after committed model consequence;
- after committed Tool logical result;
- before durable wait/yield;
- after action/reconciliation/manual resolution stabilization.

No compaction framework in Stage 3.2.

Recovery must succeed from authoritative facts when checkpoint is missing,
stale, or unsupported.

---

## 27. External result evidence

ExternalAction stores normalized redacted evidence such as:

- external_resource_id;
- provider_request_id;
- provider_status;
- result_metadata JSON.

ToolExecutionAttempt and ReconciliationAttempt may store redacted adapter
metadata.

Events should reference identifiers and concise transition facts rather than
duplicate complete payloads.

Secrets are prohibited.

---

## 28. Database invariants

PostgreSQL must enforce or transactionally protect:

- operation_id globally unique;
- ActionSnapshot immutable by application contract and no normal update path;
- max one nonterminal ExternalAction per Run;
- max one STARTED ToolExecutionAttempt per ToolCall;
- max one STARTED ReconciliationAttempt per ExternalAction;
- at most one final ActionResolution per ExternalAction;
- side-effect current_attempt_id references matching action attempt;
- Stage 3.1 active ModelInvocation/ToolCall constraints preserved;
- terminal Run shape extended consistently;
- all progression-start transactions serialize through Run-row lock.

Partial unique indexes should be used where expressible.

Cross-table invariants must use Run lock + transactional checks.

---

## 29. Lock order

Default transaction lock order:

```text
1. Run
2. ExternalAction
3. ToolCall
4. ToolExecutionAttempt / ReconciliationAttempt when needed
5. RunState
6. RunCounter
```

Stage 3.3 may insert Approval after ExternalAction in its frozen lock order.

Special result-finalization paths must document any deviation and prove no lock
cycle.

---

## 30. Failure taxonomy

Normalized runtime classes remain:

```text
TRANSIENT
PERMANENT
POLICY_DENIED
BUDGET_EXCEEDED
CANCELLED
UNKNOWN_OUTCOME
```

Stage 3.2 may additionally use internal structured reasons such as:

- DEFINITE_NOT_EXECUTED;
- RECONCILIATION_EXHAUSTED;
- ADAPTER_CONTRACT_VIOLATION;
- LEASE_LOST;
- LATE_RESULT_CONFLICT.

These reasons do not replace the main taxonomy.

---

## 31. Fake external system

The Stage 3.2 deterministic fake is a stateful external ledger, not a trivial
mock.

It must support:

- operation_id lookup;
- external resource ids;
- effect commit then response loss;
- no-effect transport failure;
- ambiguous timeout;
- authoritative reconciliation;
- best-effort reconciliation;
- no reconciliation;
- delayed result;
- call counters;
- duplicate request detection;
- controlled crash barriers.

This fake is the acceptance reference external system.

Real SaaS integration is deferred.

---

## 32. Implementation slices after design freeze

Only after V0.2 or successor is accepted:

```text
3.2-A
  ToolExecutionAttempt for READ + minimal retry/budget/deadline

3.2-B
  ActionSnapshot + ExternalAction persistence

3.2-C
  Action Commit Boundary + side-effect fake success/failure

3.2-D
  UNKNOWN + ReconciliationAttempt

3.2-E
  Cancellation + manual resolution + late-result races

3.2-F
  Checkpoint/resume overlay + full crash matrix

3.2-G
  immutable RC + Python 3.14/PostgreSQL 18 acceptance
```

Every slice keeps Stage 3.1 acceptance behavior green.

---

## 33. Resolution of V0.1 review blockers

- SR-B01 resolved by separating physical attempt FAILED from logical action
  FAILED and allowing EXECUTING -> READY only on proven non-execution.
- SR-B02 resolved by ReconciliationAttempt state machine.
- SR-B03 resolved by normative Run/Action lock Action Commit Boundary.
- SR-B04 resolved by explicit late-result winner rule.
- SR-B05 resolved by terminal matrix and post-terminal MANUAL_REVIEW rule.
- SR-B06 resolved by ToolExecutionAttempt state machine.
- SR-B07 resolved by exact ToolCall projection table.
- SR-B08 resolved by canonical digest V1.
- SR-B09 resolved by Run-row progression serialization.
- SR-B10 resolved by Stage-3.2 executable ToolVersion fail-closed rule.

Major findings are incorporated through unified attempts, atomic budget
reservation, absolute deadline_at, credential isolation, durable result
evidence, manual-resolution race rules, and terminalization guards.

---

## 34. Design V0.2 status

```text
Design V0.2
✅ WRITTEN

Re-review
🔓 NEXT

Design Acceptance
🔒

Implementation
🔒
```

No implementation may begin until V0.2 passes re-review and explicit design
acceptance.
