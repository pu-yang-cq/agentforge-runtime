# Stage 3.2 Durable Runtime — Design V0.3

Status: **CORRECTIVE DRAFT — NOT YET ACCEPTED**
Parent baseline: **Stage 3.1 Core Runtime V1.0 — ACCEPTED / FROZEN**

Supersedes for review purposes:

- Stage 3.2 Design V0.2

Derived from:

- V0.1 Self-Review;
- V0.1 Scenario Validation;
- V0.1 Adversarial Review;
- V0.2 Re-Review.

V0.3 is a narrow corrective revision. It does not expand Stage 3.2 scope.

---

## 1. Objective and product boundary

Stage 3.2 defines the deterministic durable semantics that safely map
probabilistic Agent decisions onto real-world operations.

It is not a generic workflow engine.

The execution substrate is PostgreSQL + the accepted AgentForge worker model in
P0. A future Temporal or other durable-execution backend may replace parts of
the scheduling substrate without changing the domain semantics frozen here.

---

## 2. In-scope domain concepts

Stage 3.2 uses six distinct durable concepts:

1. Run — lifecycle, ownership, deadline, cancellation, serialization point;
2. ToolCall — one logical accepted Tool request;
3. ToolExecutionAttempt — one physical Tool adapter invocation;
4. ExternalAction — one logical real-world side effect;
5. ReconciliationAttempt — one physical read-only reconciliation query;
6. ActionResolution — explicit manual finalization of unresolved action truth.

ActionSnapshot is an immutable value/fact bound to ExternalAction.

No concept above may be collapsed into one generic FAILED state.

---

## 3. Core invariants

### I1 — No global exactly-once claim

AgentForge does not claim global exactly-once execution.

### I2 — Intent before effect

No external side-effect call occurs until durable action intent is committed.

### I3 — Action Commit Boundary

No physical side-effect attempt occurs until a second fenced transaction
commits STARTED attempt + EXECUTING action.

### I4 — Run row is the per-Run serialization point

Every transaction that starts, stops, reschedules, resolves, or otherwise
changes autonomous progression locks the Run row first.

### I5 — UNKNOWN is first-class

Uncertain external truth is UNKNOWN, never silently FAILED.

### I6 — Persisted facts outrank checkpoint and new reasoning

```text
authoritative durable facts
    >
checkpoint
    >
new model reasoning
```

### I7 — Cancellation is not rollback

Cancellation prevents new business progression. It does not undo an already
authorized or executed external effect.

### I8 — PostgreSQL time is authoritative

Lease, retry due time, deadline, takeover, and scheduling correctness use
PostgreSQL server time.

### I9 — Progression consequences are fenced too

It is not enough to fence the start of ModelInvocation/Tool execution.

The transaction that consumes a completed external/model result and creates the
next durable consequence must also lock Run and re-check whether progression is
still permitted.

---

## 4. Run states

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

`cancel_requested` is an orthogonal durable flag.

---

## 5. QueueReason and durable yield

Stage 3.2 preserves the frozen QueueReason set:

```text
INITIAL
RETRY
APPROVAL_RESOLVED
ACTION_RESOLVED
RECOVERY
YIELD
RESCHEDULED
```

Stage 3.2 mapping:

- initial Run creation -> INITIAL;
- model retry -> RETRY;
- READ Tool retry -> RETRY;
- safe side-effect retry -> RETRY;
- reconciliation retry -> RETRY;
- explicit continuation after manual action resolution -> ACTION_RESOLVED;
- recovery that intentionally requeues after takeover stabilization -> RECOVERY;
- cooperative worker yield without failure -> YIELD;
- non-retry future scheduling -> RESCHEDULED;
- APPROVAL_RESOLVED remains reserved for Stage 3.3.

QueueReason identifies the scheduling class. Exact retry subtype remains visible
through durable ModelInvocation/Attempt/Action/Reconciliation facts and events.

### Durable wait/yield transaction

A worker must never use lease expiry as a retry scheduler.

When the next autonomous work is not due yet:

```text
BEGIN
  lock Run
  verify current ownership/generation
  set Run.status = QUEUED
  set queue_reason = appropriate reason
  set available_at = DB-derived due timestamp
  clear owner_worker_id
  clear lease_expires_at
  append scheduling event
COMMIT
```

At or after `available_at`, normal SKIP LOCKED claim resumes the Run and
increments execution_generation.

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

### Side-effect projection

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

Projection is deterministic runtime logic and never model reasoning.

---

## 7. ToolExecutionAttempt

Every physical Tool adapter call, READ or side effect, creates one attempt.

States:

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

Fields include:

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
- outcome_reason nullable;
- definite_not_executed nullable;
- redacted result/evidence;
- redacted adapter metadata.

Attempt number is unique and monotonic per ToolCall.

A completed attempt is never reused.

---

## 8. Orphaned ToolExecutionAttempt recovery

Lease loss removes progression authority even before takeover.

On takeover, orphaned STARTED attempts are closed before any replacement
attempt is allowed.

### 8.1 Side-effect attempt

If:

```text
ToolExecutionAttempt = STARTED
ExternalAction = EXECUTING
previous owner lease expired
```

the takeover recovery transaction performs:

```text
BEGIN
  lock Run
  lock ExternalAction
  lock old Attempt

  verify old Attempt is current
  old Attempt -> UNKNOWN
  outcome_reason = LEASE_LOST_RESULT_NOT_DURABLE
  ExternalAction EXECUTING -> UNKNOWN
  ExternalAction.current_attempt_id = NULL
  ToolCall -> UNRESOLVED
  append recovery events
COMMIT
```

No new side-effect attempt may start before reconciliation.

### 8.2 READ attempt

READ has no external business side effect.

For an orphaned STARTED READ attempt:

```text
BEGIN
  lock Run
  lock ToolCall
  lock old Attempt

  old Attempt -> UNKNOWN
  outcome_reason = LEASE_LOST_RESULT_NOT_DURABLE
  ToolCall -> READY
  append recovery events
COMMIT
```

The same logical ToolCall, ToolVersion, and arguments are retried
deterministically before new model reasoning.

### 8.3 Late result after orphan closure

The old physical attempt may still later return.

Its result is handled by the late-result rule and cannot restore progression
authority.

---

## 9. ExternalAction

States:

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

### ABORTED

ABORTED means AgentForge knows the external effect did not execute and has
decided it will not execute it.

ABORTED never represents uncertainty.

---

## 10. ExternalAction attempt pointer semantics

`current_attempt_id` has one meaning only:

> the currently authorized STARTED side-effect ToolExecutionAttempt.

Invariant:

```text
ExternalAction.status = EXECUTING
    iff current_attempt_id references the one authorized STARTED attempt
```

When ExternalAction leaves EXECUTING for:

- READY;
- UNKNOWN;
- SUCCEEDED;
- FAILED;

`current_attempt_id` is cleared in the same transaction.

Historical/latest attempts are queried from ToolExecutionAttempt history.

No separate mutable `latest_attempt_id` is required in Stage 3.2.

Late-result handlers reference the attempt id carried by the execution result,
not `current_attempt_id`.

---

## 11. Stable operation identity

Every ExternalAction has one globally unique `operation_id`.

It is:

- generated exactly once before READY persistence;
- committed with ActionSnapshot + ExternalAction;
- reused across all attempts/restarts/takeovers;
- supplied to providers where idempotency keys are supported;
- used as reconciliation evidence.

Provider idempotency is a capability, not the global correctness model.

---

## 12. ActionSnapshot Canonical Format V1

ActionSnapshot is immutable.

Digest input object:

```json
{
  "arguments": <value>,
  "credential_ref": "<opaque-reference-or-null>",
  "effect_type": "<enum>",
  "format_version": 1,
  "operation_id": "<uuid>",
  "tool_version_id": "<uuid>"
}
```

### Allowed value domain

Canonical V1 accepts only:

- null;
- boolean;
- string;
- signed integer within the application-supported integer range;
- array of allowed values;
- object with string keys and allowed values.

Raw non-integer floating-point values are rejected before snapshot creation.

Tool schema normalization may convert decimal-like business values to an
explicit canonical string or integer representation. The runtime never silently
rounds floats.

### Exact byte algorithm

AgentForge Canonical JSON V1 is:

> RFC 8785 JSON Canonicalization Scheme semantics applied to the restricted
> value domain above, with non-integer numbers prohibited by AgentForge before
> canonicalization.

Consequences:

- object member ordering follows RFC 8785;
- string escaping and UTF-8 byte emission follow RFC 8785;
- no insignificant whitespace;
- arrays preserve order;
- Unicode strings are not application-normalized before canonicalization;
  different Unicode scalar sequences remain different action values/digests;
- SHA-256 is computed over the exact canonical UTF-8 bytes.

The implementation must maintain golden canonical-byte and digest vectors in
tests.

Secrets never enter the canonical object; only opaque credential reference may.

---

## 13. Credential boundary

Preparation may validate that a credential reference is configured and eligible
for later resolution.

Preparation must not retrieve secret material.

Actual secret retrieval occurs only:

- immediately before adapter execution;
- immediately before reconciliation request.

Resolved secret material is process-memory-only at the adapter edge and must
not enter:

- ModelRequest/context;
- RunMessage;
- DomainEvent;
- ActionSnapshot;
- Checkpoint;
- trace projection;
- durable error detail;
- structured logs.

If credential retrieval fails before any external request, the physical attempt
is a definite-not-executed failure.

---

## 14. Stage-3.2 executable ToolVersion

A side-effect ToolVersion may execute only when:

- effect is not DESTRUCTIVE;
- approval_required = false;
- explicitly eligible for no-approval execution;
- credential reference configuration is valid;
- idempotency/reconciliation capabilities are declared.

Otherwise the runtime fails closed and no external adapter is called.

---

## 15. Side-effect preparation transaction

Preparation is a business-progression consequence and therefore must re-check
eligibility under Run lock.

```text
BEGIN
  lock Run

  verify:
    Run nonterminal
    current ownership/generation valid
    lease valid when worker-owned
    cancel_requested = false
    DB deadline has not expired
    task budget can still permit at least one Tool attempt
    no conflicting active progression
    ToolVersion is Stage-3.2-executable

  create ToolCall
  create immutable ActionSnapshot
  create ExternalAction READY + stable operation_id
  append events
COMMIT
```

No external I/O occurs.

If cancellation/deadline/budget already prohibits business work, preparation
does not create a READY ExternalAction.

---

## 16. Action Commit Boundary

To start a side-effect physical attempt:

```text
BEGIN
  lock Run
  lock ExternalAction

  verify:
    Run nonterminal
    owner/generation current
    lease valid by DB time
    cancel_requested = false
    DB deadline not expired
    ExternalAction = READY
    current_attempt_id IS NULL
    no conflicting active progression
    task Tool-attempt budget permits

  reserve/increment tool_attempts_used
  create ToolExecutionAttempt STARTED
  ExternalAction -> EXECUTING
  ExternalAction.current_attempt_id = attempt.id
  ToolCall -> EXECUTING
  append event
COMMIT

external adapter call begins only after commit
```

Cancel command uses the same Run lock, so cancel-vs-commit has one serial order.

---

## 17. READ execution boundary

READ ToolCall physical attempts use the same Run-row progression fence.

```text
BEGIN
  lock Run
  verify owner/generation/lease/cancel/deadline/budget
  reserve tool attempt usage
  create ToolExecutionAttempt STARTED
  ToolCall -> EXECUTING
  append event
COMMIT

invoke READ adapter
```

Recovered READ uses the same logical ToolCall/ToolVersion/arguments.

---

## 18. Attempt result classification

### SUCCEEDED

Attempt -> SUCCEEDED.

Logical projection finalizes accordingly.

### FAILED + definite_not_executed=true

The runtime has proof the effect did not occur.

For side effects:

- attempt -> FAILED;
- clear current_attempt_id;
- if retryable and retry policy/budget/deadline permit:
  ExternalAction -> READY and durable retry is scheduled;
- otherwise:
  ExternalAction -> FAILED or ABORTED according to reason.

### Possible execution

If the effect may have happened, the physical attempt outcome is UNKNOWN.

For side effects:

- attempt -> UNKNOWN;
- ExternalAction -> UNKNOWN;
- clear current_attempt_id;
- ToolCall -> UNRESOLVED.

No blind retry.

---

## 19. READY action stabilization on permanent business-work denial

A READY ExternalAction has not crossed Action Commit.

If future execution becomes permanently prohibited by:

- task deadline expiry; or
- exhausted tool-attempt budget;

then under Run + Action lock:

```text
ExternalAction READY -> ABORTED
ToolCall -> NOT_EXECUTED
append event
```

Then:

- if cancel_requested owns termination -> Run CANCELLED;
- otherwise -> Run FAILED with BUDGET_EXCEEDED / deadline failure reason.

No external call occurs.

This transition closes the state machine before terminalization.

---

## 20. ModelInvocation result consequence fence

A ModelInvocation may have been validly started before cancellation, deadline
expiry, takeover, or another terminal condition.

Provider completion does not automatically authorize its business consequence.

Every model-result transaction must:

```text
BEGIN
  lock Run
  load referenced ModelInvocation

  verify result belongs to the durable invocation
  persist invocation outcome/evidence

  re-check:
    current generation / permitted result ownership
    Run terminal state
    cancel_requested
    DB deadline
    conflicting durable progression

  if progression still permitted:
      atomically create normal consequence
      (assistant message or ToolProposal/ToolCall/action preparation)

  else:
      mark/store result disposition as discarded for progression
      append MODEL_RESULT_DISCARDED event
      create no new RunMessage business response
      create no ToolProposal
      create no ToolCall
      create no ExternalAction
      enqueue no new progression
COMMIT
```

A late model result may remain observable as ModelInvocation evidence but cannot
break cancellation/deadline/fencing.

Stage 3.1 stale-executor behavior remains preserved.

---

## 21. Reconciliation capability

ToolVersion declares:

```text
AUTHORITATIVE
BEST_EFFORT
NONE
```

Reconciliation is read-only with respect to the business effect.

Its inputs come only from durable:

- ActionSnapshot;
- operation_id;
- external evidence/resource reference;
- credential_ref resolved at adapter edge.

The model is never used to reconstruct reconciliation identity.

---

## 22. ReconciliationAttempt

States:

```text
STARTED
SUCCEEDED
FAILED
```

A SUCCEEDED attempt carries business result:

```text
SUCCEEDED
FAILED
NOT_EXECUTED
UNKNOWN
```

A FAILED attempt means the reconciliation request itself failed.

### Orphaned reconciliation attempt

On takeover:

```text
BEGIN
  lock Run
  lock ExternalAction
  lock old ReconciliationAttempt

  old STARTED ReconciliationAttempt -> FAILED
  outcome_reason = LEASE_LOST
  ExternalAction remains RECONCILING
  append event
  schedule bounded reconciliation retry
COMMIT
```

Because reconcile is read-only, closing the orphaned query as FAILED does not
change business truth.

---

## 23. Reconciliation result safety

### AUTHORITATIVE

- SUCCEEDED -> action SUCCEEDED;
- FAILED -> action FAILED;
- NOT_EXECUTED -> action READY only if retry policy/budget/deadline permit;
- UNKNOWN -> adapter contract violation -> MANUAL_REVIEW.

Authoritative NOT_EXECUTED may authorize automatic retry of a non-idempotent
action.

### BEST_EFFORT

- conclusive SUCCEEDED/FAILED evidence may finalize only according to the
  declared adapter capability contract;
- UNKNOWN -> MANUAL_REVIEW;
- NOT_EXECUTED does **not** authorize automatic retry for a non-idempotent
  action.

BEST_EFFORT NOT_EXECUTED may permit automatic retry only when an independent
declared idempotency guarantee makes duplicate execution safe.

Otherwise -> MANUAL_REVIEW.

### NONE

UNKNOWN -> MANUAL_REVIEW without reconcile request.

---

## 24. Reconciliation safety budget

Ordinary task budget/deadline does not block safety stabilization.

Reconciliation has separate bounded policy:

- max reconciliation attempts per action;
- bounded exponential backoff;
- DB-time schedule;
- after exhaustion -> MANUAL_REVIEW.

No unbounded external safety loop is permitted.

Other post-deadline stabilization steps are local database transitions and do
not create new business effects.

---

## 25. Retry scheduling

No generic Retry DSL.

Versioned explicit policies exist for:

- model transient retry;
- READ transient retry;
- side-effect retry after safe non-execution proof;
- reconciliation retry.

All delayed retries use the durable yield transaction from Section 5.

A Run has one `available_at` because P0 permits one autonomous progression path.

---

## 26. Budget and deadline

Immutable Run limits:

- max_model_invocations;
- max_tool_attempts;
- deadline_at.

Mutable usage:

- model_invocations_used;
- tool_attempts_used.

Usage reservation is atomic with creation of the corresponding STARTED
ModelInvocation/ToolExecutionAttempt.

`deadline_at` is an absolute DB-derived timestamp.

Wall-clock time continues through human/manual waits.

After deadline:

- no new model/business Tool work;
- no fresh ExternalAction preparation;
- READY action is stabilized to ABORTED before failure terminalization;
- bounded reconciliation safety work remains permitted.

---

## 27. Cancellation

Cancel transaction:

```text
BEGIN
  lock Run

  if terminal:
      return idempotent terminal result

  set cancel_requested = true

  if ExternalAction = READY and no attempt crossed Action Commit:
      lock action
      action -> ABORTED
      ToolCall -> NOT_EXECUTED

  append cancel event
COMMIT
```

After cancel commit:

- no new ModelInvocation;
- no new ToolExecutionAttempt for business work;
- no new ExternalAction;
- in-flight model result cannot create a business consequence;
- already authorized Tool attempt may report result;
- uncertain action safety reconciliation remains permitted;
- Run terminalizes when action state is stable enough under Section 31.

---

## 28. Late-result winner rule

Every Tool attempt result transaction locks:

1. Run;
2. logical ToolCall;
3. ExternalAction when side-effecting;
4. referenced ToolExecutionAttempt.

A result may change business state only if:

- the referenced attempt is still the currently authorized STARTED attempt;
- logical state is still matching EXECUTING;
- no UNKNOWN/RECONCILING/MANUAL_REVIEW/final action transition won first.

Otherwise:

- result is late/conflicting evidence;
- physical attempt record may be completed where valid;
- business outcome is not overwritten;
- no progression is queued;
- stale generation authority is not restored.

External/provider evidence never grants authorization to start new work.

---

## 29. Manual resolution

ActionResolution:

- id;
- action_id;
- outcome SUCCEEDED | FAILED | ABORTED;
- evidence;
- reason;
- resolver placeholder identity;
- created_at.

Resolution transaction locks Run then ExternalAction.

Only MANUAL_REVIEW may be manually resolved.

One final ActionResolution per ExternalAction.

Delayed reconciliation/late result after resolution becomes evidence only.

### Nonterminal manual review

If Run is not cancelled:

```text
ExternalAction -> MANUAL_REVIEW
Run -> WAITING_ACTION_RESOLUTION
```

After resolution:

- SUCCEEDED:
  - if cancel/deadline does not prohibit continuation, queue with
    ACTION_RESOLVED;
  - if deadline now prohibits continuation, Run FAILED without new business
    progression;
- FAILED/ABORTED:
  - Run FAILED.

### Post-terminal manual review

Stage 3.2 permits only:

```text
Run = CANCELLED
ExternalAction = MANUAL_REVIEW
```

as a post-terminal unresolved combination.

Manual resolution updates Action/ToolCall facts but never reopens CANCELLED Run.

Stage 3.2 does **not** permit creating a new
`FAILED + MANUAL_REVIEW` state.

A non-cancelled unresolved action remains WAITING_ACTION_RESOLUTION until
resolved.

---

## 30. Terminal Run × ExternalAction matrix

### COMPLETED

May coexist only with:

- no ExternalAction; or
- required ExternalAction SUCCEEDED.

No unresolved/failed required action.

### FAILED

May coexist with final:

- FAILED;
- ABORTED;
- SUCCEEDED when the Run failed later for another reason.

May not coexist with:

- READY;
- EXECUTING;
- UNKNOWN;
- RECONCILING;
- MANUAL_REVIEW.

### CANCELLED

May coexist with:

- ABORTED;
- SUCCEEDED;
- FAILED;
- MANUAL_REVIEW.

At terminalization time it may not coexist with:

- READY;
- EXECUTING;
- UNKNOWN;
- RECONCILING.

### WAITING_ACTION_RESOLUTION

For non-cancelled Run with ExternalAction MANUAL_REVIEW.

---

## 31. Recovery precedence

Normative takeover/resume order:

```text
1. Terminal Run
   - no autonomous business progression
   - CANCELLED + MANUAL_REVIEW may accept explicit resolution only

2. Close orphaned STARTED ModelInvocation according to Stage 3.1 fencing rules

3. Close orphaned STARTED ToolExecutionAttempt
   - side effect -> attempt UNKNOWN + action UNKNOWN
   - READ -> attempt UNKNOWN + ToolCall READY

4. Close orphaned STARTED ReconciliationAttempt
   - attempt FAILED(LEASE_LOST)
   - action remains unresolved

5. UNKNOWN / due RECONCILING action
   - safety reconciliation first

6. cancel_requested
   - no new business work
   - stabilize READY action or terminalize when safe

7. retry/backoff not due
   - durable yield to QUEUED + available_at

8. budget/deadline prohibits business work
   - stabilize READY action
   - terminalize FAILED unless cancellation owns terminal result

9. restore compatible checkpoint private state

10. continue normal model progression
```

Persisted unresolved action facts always precede new reasoning.

---

## 32. Checkpoint V1

Checkpoint is optional for correctness and contains only private runtime state:

- schema_version;
- runner_version;
- run_state_version;
- execution spec identity;
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

Unsupported/missing/stale checkpoint falls back to reconstruction from durable
facts.

No rollback-to-checkpoint feature exists.

---

## 33. External result evidence

Persist redacted evidence such as:

- external_resource_id;
- provider_request_id;
- provider_status;
- result_metadata.

Evidence supports reconciliation/traceability but never grants authorization to
execute new work.

Events reference concise transition facts rather than duplicate full payloads.

---

## 34. Database invariants

PostgreSQL must enforce or transactionally protect:

- operation_id globally unique;
- immutable ActionSnapshot through repository/application contract;
- max one nonterminal ExternalAction per Run;
- max one STARTED ToolExecutionAttempt per ToolCall;
- max one STARTED ReconciliationAttempt per ExternalAction;
- max one final ActionResolution per ExternalAction;
- ExternalAction.current_attempt_id non-null only for EXECUTING and references
  its STARTED attempt;
- terminal matrix constraints where expressible;
- Stage 3.1 active progression constraints preserved;
- every cross-table progression start serialized by Run lock.

Partial unique indexes are used where expressible.

Cross-table rules use Run lock + transactional checks.

---

## 35. Lock order

Default:

```text
1. Run
2. ExternalAction
3. ToolCall
4. ToolExecutionAttempt / ReconciliationAttempt
5. RunState
6. RunCounter
```

Result paths that do not need every object omit later locks but never reverse
the order.

Stage 3.3 may extend this lock order for Approval without weakening it.

---

## 36. Failure taxonomy

Primary classes:

```text
TRANSIENT
PERMANENT
POLICY_DENIED
BUDGET_EXCEEDED
CANCELLED
UNKNOWN_OUTCOME
```

Structured reasons may include:

- DEFINITE_NOT_EXECUTED;
- DEADLINE_EXCEEDED;
- RECONCILIATION_EXHAUSTED;
- ADAPTER_CONTRACT_VIOLATION;
- LEASE_LOST;
- LEASE_LOST_RESULT_NOT_DURABLE;
- LATE_RESULT_CONFLICT;
- MODEL_RESULT_DISCARDED.

---

## 37. Stateful fake external system

Acceptance fake must maintain an external operation ledger with:

- operation_id lookup;
- external resource ids;
- physical call count;
- effect count;
- duplicate request count;
- reconciliation query count;
- controlled barriers.

It must simulate:

- normal success;
- definite pre-effect failure;
- ambiguous timeout;
- effect committed + response lost;
- delayed response;
- authoritative reconciliation outcomes;
- best-effort uncertainty;
- no reconciliation capability.

Real SaaS integration is deferred.

---

## 38. Implementation slices after design freeze

Only after explicit acceptance:

```text
3.2-A
  unified ToolExecutionAttempt + retry/budget/deadline/yield

3.2-B
  ActionSnapshot V1 + ExternalAction persistence

3.2-C
  Action Commit Boundary + side-effect fake

3.2-D
  UNKNOWN + ReconciliationAttempt + orphan recovery

3.2-E
  cancellation + model-result consequence fence + manual resolution + late races

3.2-F
  checkpoint overlay + full recovery matrix

3.2-G
  immutable RC + Python 3.14/PostgreSQL 18 acceptance
```

Every slice preserves Stage 3.1 regression behavior.

---

## 39. V0.2 re-review finding closure

- RR-B01: closed by explicit orphaned Tool/Reconciliation attempt transitions.
- RR-B02: closed by durable yield/requeue transaction.
- RR-B03: closed by READY -> ABORTED stabilization before budget/deadline
  terminalization.
- RR-B04: closed by model-result consequence fencing and discard rule.
- RR-B05: closed by authoritative-vs-best-effort NOT_EXECUTED retry rule.
- RR-M01: closed by RFC 8785-based restricted Canonical JSON V1 + golden vectors.
- RR-M02: closed by active-only current_attempt_id semantics.
- RR-M03: closed by explicit cancel/deadline/budget re-check in preparation.
- RR-M04: closed by removing FAILED + MANUAL_REVIEW creation from Stage 3.2.
- RR-M05: closed by separating credential-reference validation from secret
  retrieval.
- RR-M06: closed by explicit QueueReason mapping.

Clarifications are incorporated for numeric normalization, evidence authority,
and bounded post-deadline safety work.

---

## 40. V0.3 status

```text
Stage 3.2 Design V0.3
✅ WRITTEN

Final Re-review
🔓 NEXT

Design Acceptance
🔒

Design Freeze
🔒

Implementation
🔒
```

No Stage 3.2 runtime implementation is authorized until final re-review and
explicit design acceptance complete.
