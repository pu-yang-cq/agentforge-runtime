# Stage 3.2 Durable Runtime — Acceptance Criteria V0.3

Status: **CORRECTIVE DRAFT — NOT YET ACCEPTED**
Depends on: `docs/design/stage3.2-durable-runtime-v0.3.md`
Regression baseline: Stage 3.1 Core Runtime V1.0 official acceptance

Stage 3.2 implementation remains locked until Design V0.3 passes final
re-review and explicit design acceptance.

---

## A. Stage 3.1 regression gate

All frozen Stage 3.1 guarantees must continue to pass.

No accepted Stage 3.1 migration may be rewritten.

Target environment remains:

```text
CPython 3.14
PostgreSQL 18
uv --locked
Ruff
mypy strict
Alembic online migration
mandatory PostgreSQL integration
```

---

## B. State-machine gate

Legal and illegal transitions must be tested for:

- Run;
- ToolCall;
- ToolExecutionAttempt;
- ExternalAction;
- ReconciliationAttempt;
- ActionResolution.

Examples that must fail closed:

- ExternalAction UNKNOWN -> EXECUTING;
- ToolExecutionAttempt FAILED -> STARTED;
- ToolExecutionAttempt UNKNOWN -> STARTED;
- contradictory second ActionResolution;
- ambiguous UNKNOWN -> ABORTED without proof;
- MANUAL_REVIEW on COMPLETED Run.

---

## C. Unified physical Tool attempts

Every physical Tool adapter invocation creates ToolExecutionAttempt.

Mandatory:

- READ attempt #1 persisted before call;
- READ retry creates attempt #2;
- side-effect retry creates new attempt with same ExternalAction;
- attempt numbering survives restart;
- max one STARTED attempt per ToolCall;
- max_tool_attempts counts READ and side-effect physical attempts consistently.

---

## D. Orphaned attempt takeover gate

### D1 — side-effect attempt

Arrange:

```text
Action EXECUTING
Attempt #1 STARTED
owner lease expires
new worker takes over
```

Required same recovery transaction:

- Attempt #1 -> UNKNOWN;
- reason = LEASE_LOST_RESULT_NOT_DURABLE;
- Action -> UNKNOWN;
- current_attempt_id -> NULL;
- ToolCall -> UNRESOLVED;
- no new business attempt starts;
- reconciliation precedes any retry.

### D2 — READ attempt

Arrange STARTED READ attempt + lease loss.

Required:

- old attempt -> UNKNOWN;
- ToolCall -> READY;
- exact same logical ToolCall/ToolVersion/args retried;
- new physical attempt gets next attempt number;
- model is not asked again first.

### D3 — reconciliation attempt

Arrange:

```text
Action RECONCILING
ReconciliationAttempt STARTED
lease loss
```

Required:

- old reconcile attempt -> FAILED;
- reason = LEASE_LOST;
- business truth remains unresolved;
- bounded reconcile retry is scheduled;
- new reconcile attempt gets next number.

---

## E. Durable yield / requeue gate

For model, READ, side-effect-safe, and reconciliation retry:

when retry is delayed, the scheduling transaction must atomically produce:

- Run.status = QUEUED;
- queue_reason = RETRY;
- available_at = DB-derived due time;
- owner_worker_id cleared;
- lease_expires_at cleared;
- durable scheduling event.

Mandatory assertions:

- worker lease expiry is not used as the retry timer;
- Run is not claimable before DB-time `available_at`;
- Run is claimable at/after due time;
- claim increments execution_generation;
- restart preserves due time.

Also test:

- ACTION_RESOLVED;
- RECOVERY;
- YIELD;
- RESCHEDULED QueueReason mapping.

---

## F. ActionSnapshot canonical-byte gate

Canonical ActionSnapshot V1 must use the frozen restricted RFC 8785-based
algorithm.

Mandatory golden vectors include:

- empty object;
- nested object with reordered input keys;
- Unicode strings;
- quote/backslash/control characters;
- arrays;
- negative and positive integers at the exact safe-range boundaries
  -9007199254740991 and 9007199254740991;
- rejection just outside those boundaries;
- null/boolean;
- operation_id/tool_version/effect/credential_ref changes.

Tests must assert:

1. exact canonical UTF-8 bytes;
2. exact SHA-256 digest;
3. identical vectors in separate processes;
4. object input order does not affect bytes;
5. different Unicode scalar sequences remain different if inputs differ;
6. raw non-integer floats are rejected;
7. runtime never silently rounds numeric values.

ActionSnapshot is immutable through normal repository/application paths.

---

## G. Credential isolation gate

Use a sentinel secret.

Preparation may validate credential reference configuration but must not fetch
the secret.

Secret retrieval occurs only at adapter execution/reconciliation edge.

The sentinel must be absent from:

- ModelRequest/context;
- RunMessage;
- DomainEvent;
- ActionSnapshot;
- Checkpoint;
- public trace;
- durable errors;
- captured structured logs.

Credential retrieval failure before external request must be classified as
definite-not-executed.

---

## H. Side-effect preparation fence

Preparation transaction must lock Run and reject creation of a READY action if:

- cancel_requested;
- terminal Run;
- deadline expired;
- tool-attempt budget can no longer permit an attempt;
- stale generation/lease;
- conflicting active progression;
- ToolVersion is not Stage-3.2-executable.

Required:

- rejected preparation creates no ExternalAction;
- rejected preparation calls no external adapter.

---

## I. Action Commit Boundary

Before fake external effect can occur, DB must already contain:

- ToolCall EXECUTING;
- ExternalAction EXECUTING;
- ActionSnapshot/digest;
- stable operation_id;
- current_attempt_id;
- referenced ToolExecutionAttempt STARTED;
- incremented tool_attempts_used.

If any required write fails/rolls back, external call count must remain zero.

---

## J. current_attempt_id invariant

Mandatory:

- non-null exactly while Action = EXECUTING;
- points to the authorized STARTED attempt;
- cleared on EXECUTING -> READY;
- cleared on EXECUTING -> UNKNOWN;
- cleared on EXECUTING -> SUCCEEDED;
- cleared on EXECUTING -> FAILED;
- old attempt history remains queryable;
- late result uses explicit attempt id, not mutable current pointer.

DB/domain tests must reject inconsistent combinations where enforceable.

---

## K. Definite-not-executed side-effect retry

Simulate a physical attempt that fails before any external effect.

Required:

- attempt -> FAILED;
- definite_not_executed = true;
- Action -> READY if retry is allowed;
- current_attempt_id cleared;
- same operation_id retained;
- Run durably requeued with RETRY + available_at;
- next attempt uses next attempt number;
- no duplicate effect.

If budget/deadline forbids future attempt, apply Section L stabilization instead
of leaving Action READY.

---

## L. READY action stabilization on budget/deadline

Arrange:

```text
ExternalAction READY
no physical attempt crossed Action Commit
```

Then independently test:

1. tool-attempt budget exhausted;
2. deadline expires.

Required same stabilization path:

- Action READY -> ABORTED;
- ToolCall -> NOT_EXECUTED;
- no external call;
- no STARTED attempt;
- current_attempt_id remains NULL.

Terminal result:

- if cancel_requested already owns termination -> CANCELLED;
- otherwise -> FAILED with explicit budget/deadline reason.

No terminal Run may retain READY action.

---

## M. Cancel vs Action Commit race

Use real concurrent DB transactions.

### Cancel wins first

Required:

- cancel_requested = true;
- READY action -> ABORTED;
- ToolCall -> NOT_EXECUTED;
- no attempt;
- no external call.

### Action Commit wins first

Required:

- current attempt is validly authorized;
- cancel does not claim rollback;
- no subsequent business attempt starts;
- attempt result is stabilized through final/UNKNOWN path.

Exactly one ordering wins under Run lock.

---

## N. In-flight ModelInvocation vs cancellation

Arrange:

1. ModelInvocation STARTED validly;
2. provider response delayed;
3. cancel commits;
4. model returns Tool proposal.

Required result transaction:

- records ModelInvocation outcome/evidence;
- locks Run;
- observes cancel_requested;
- marks result disposition discarded for progression;
- appends discard event;
- creates no RunMessage business consequence;
- creates no ToolProposal;
- creates no ToolCall;
- creates no ExternalAction;
- queues no new progression.

Run proceeds only through cancellation stabilization.

---

## O. In-flight ModelInvocation vs deadline

Same as N, but deadline expires before provider result.

Required:

- ModelInvocation result remains durable evidence;
- no new business consequence;
- no new action/tool progression;
- Run fails/settles according to deadline semantics after any pre-existing
  safety work.

---

## P. In-flight ModelInvocation vs stale generation

If takeover/fencing makes the invocation result stale:

- expired lease / stale generation follows the frozen Stage 3.1 stale-executor
  rejection path;
- stale executor cannot finalize authoritative ModelInvocation lifecycle;
- stale result cannot create consequence;
- no new RunMessage/ToolProposal/ToolCall/Action from stale invocation;
- no progression is queued.

A separate case must prove that a still-authorized invocation whose result
arrives after cancellation/deadline may record its invocation outcome while its
business consequence is discarded.

---

## Q. Ambiguous side-effect outcome

Simulate effect ambiguity.

Required:

- physical attempt -> UNKNOWN;
- Action -> UNKNOWN;
- current_attempt_id cleared;
- ToolCall -> UNRESOLVED;
- no blind retry;
- no new model progression;
- reconciliation precedes business continuation.

---

## R. ReconciliationAttempt gate

Physical reconcile request must be distinct from business result.

Mandatory:

- STARTED row committed before query;
- successful query -> ReconciliationAttempt SUCCEEDED + business result;
- transport/503/timeout -> ReconciliationAttempt FAILED only;
- business Action remains unresolved;
- durable reconcile retry/yield;
- retry numbering/history survives restart.

---

## S. AUTHORITATIVE reconciliation

Test:

- SUCCEEDED -> Action SUCCEEDED;
- FAILED -> Action FAILED;
- NOT_EXECUTED -> Action READY only if retry policy/budget/deadline permit;
- UNKNOWN -> adapter contract violation -> MANUAL_REVIEW.

For a non-idempotent action, only AUTHORITATIVE NOT_EXECUTED may authorize
automatic retry.

---

## T. BEST_EFFORT reconciliation safety

### Non-idempotent action

If BEST_EFFORT returns NOT_EXECUTED:

- must not auto-retry;
- Action -> MANUAL_REVIEW unless another independent authoritative/idempotent
  capability proves retry safety.

### Independently idempotent action

If ToolVersion declares an independent idempotency guarantee sufficient for
safe duplicate submission, BEST_EFFORT NOT_EXECUTED may enter the safe retry
path according to explicit capability contract.

Tests must demonstrate both branches.

BEST_EFFORT UNKNOWN -> MANUAL_REVIEW.

---

## U. NONE reconciliation

For uncertain action with reconciliation mode NONE:

- no reconcile external call;
- Action -> MANUAL_REVIEW;
- ToolCall remains UNRESOLVED;
- non-cancelled Run -> WAITING_ACTION_RESOLUTION;
- cancelled Run may terminalize CANCELLED + MANUAL_REVIEW.

---

## V. Reconciliation safety budget

Required:

- ordinary task budget/deadline does not permit new business work;
- bounded safety reconcile attempts still occur;
- every delayed safety retry durably yields Run;
- exhaustion -> MANUAL_REVIEW;
- no infinite external reconciliation loop.

---

## W. Late result vs takeover

Force both serialization orders.

### Result wins while still current EXECUTING

It may finalize Action.

Takeover then observes final state and does not convert it to UNKNOWN.

### Takeover wins first

Recovery commits:

- old attempt UNKNOWN;
- Action UNKNOWN;
- current_attempt_id NULL.

Later old-worker result:

- may be stored as evidence;
- cannot directly finalize Action;
- cannot queue progression;
- cannot regain generation authority.

---

## X. Manual resolution race

For Action MANUAL_REVIEW, race:

- ActionResolution;
- delayed reconciliation/late result.

Required:

- one final business outcome;
- ActionResolution transaction wins permanently once committed;
- later evidence cannot overwrite outcome;
- contradictory second resolution rejected.

---

## Y. Nonterminal manual review

For non-cancelled Run:

```text
Action MANUAL_REVIEW
Run WAITING_ACTION_RESOLUTION
```

After resolution:

### SUCCEEDED

- if deadline still permits continuation:
  Run -> QUEUED, queue_reason = ACTION_RESOLVED;
- if deadline expired:
  Run -> FAILED with no new business work.

### FAILED / ABORTED

- Run -> FAILED.

No unsupported FAILED + MANUAL_REVIEW state is created.

---

## Z. Post-terminal manual review

Stage 3.2 permits only:

```text
Run CANCELLED
Action MANUAL_REVIEW
```

as a post-terminal unresolved combination.

Resolution:

- updates Action;
- updates ToolCall projection;
- appends evidence/event;
- Run remains CANCELLED;
- no autonomous progression.

Tests must reject:

- COMPLETED + MANUAL_REVIEW;
- newly created FAILED + MANUAL_REVIEW.

---

## AA. Terminal matrix

### COMPLETED

Only:

- no required action; or
- required Action SUCCEEDED.

### FAILED

May coexist with final SUCCEEDED/FAILED/ABORTED according to failure cause.

Must reject:

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

Must not terminalize with:

- READY;
- EXECUTING;
- UNKNOWN;
- RECONCILING.

---

## AB. Cross-table progression serialization

Concurrent real PostgreSQL transactions try to start:

- ModelInvocation;
- READ attempt;
- side-effect attempt;
- reconciliation;
- cancellation;
- manual resolution.

Required:

- Run-row lock serializes them;
- only the state-valid transition commits;
- no conflicting active progression survives;
- independent partial indexes are not the only defense;
- multi-row paths obey the global lock order
  Run -> ExternalAction -> ToolCall -> Attempt/ReconciliationAttempt where
  those objects participate;
- stress tests must not contain a reversed ToolCall -> ExternalAction lock path.

---

## AC. Budget atomicity

Required:

- ModelInvocation START and model usage increment atomic;
- ToolExecutionAttempt START and tool usage increment atomic;
- rollback consumes neither;
- concurrent starts cannot exceed limit;
- restart preserves counters.

Reconciliation safety attempts are counted separately from ordinary
max_tool_attempts.

---

## AD. Deadline authority

Required:

- deadline_at generated from PostgreSQL time;
- worker local clock skew irrelevant;
- no fresh business work starts after deadline;
- READY action stabilizes before failure terminalization;
- in-flight model result creates no new consequence after deadline;
- bounded safety reconciliation still allowed.

---

## AE. Checkpoint authority

Mandatory:

- checkpoint missing -> recovery from durable facts;
- checkpoint stale -> newer durable facts win;
- unsupported schema -> durable reconstruction path;
- no chain-of-thought;
- no resolved secret.

Test stale checkpoint against:

- newer ToolCall;
- newer ExternalAction;
- newer cancellation;
- newer attempt/reconciliation facts.

---

## AF. Stateful fake external system

Must expose observable ledger:

- operation_id;
- external_resource_id;
- call count;
- effect count;
- duplicate request count;
- reconciliation query count.

Must simulate:

- normal success;
- definite no-effect failure;
- ambiguous timeout;
- effect commit + response loss;
- delayed result;
- authoritative results;
- best-effort NOT_EXECUTED/UNKNOWN;
- no reconciliation;
- controlled crash barriers.

---

## AG. Crash matrix

Mandatory crash points:

1. before Action preparation commit;
2. after READY commit;
3. before Action Commit;
4. after EXECUTING/Attempt commit before external call;
5. during external call;
6. after external effect commit before response;
7. after response before DB result commit;
8. during result commit;
9. during reconciliation request;
10. after reconcile response before result commit;
11. during durable retry/yield transaction;
12. during cancellation/model-result race.

No crash point may lead to blind duplicate non-idempotent execution.

---

## AH. Migration gate

Required:

- forward migration from frozen Stage 3.1 head;
- no Stage 3.1 migration edits;
- PostgreSQL 18 online upgrade;
- revision ids fit version column;
- FKs/checks/uniques active;
- new attempt/action/reconcile/resolution constraints verified.

---

## AI. Quality gate

Official target acceptance must execute:

```text
Python 3.14
uv sync --locked
Ruff
Ruff format --check
mypy strict
compile/import validation
Alembic online migration
full unit suite
full PostgreSQL integration suite
real concurrency races
controlled crash-window suite
```

Mandatory durability/concurrency tests may not silently skip.

---

## AJ. Exit assertions

Stage 3.2 may be accepted only if all are true:

```text
Every physical Tool call has a durable Attempt.
Orphaned physical attempts are durably closed before retry.
Retry waits explicitly requeue/yield the Run; lease expiry is not a scheduler.
A READY action blocked forever by budget/deadline is stabilized to ABORTED.
Late model results cannot bypass cancel/deadline/fencing.
Side-effect intent is committed before external execution.
Action Commit is transactionally fenced.
UNKNOWN is distinct from FAILED.
UNKNOWN is reconciled before potentially duplicating retry.
BEST_EFFORT NOT_EXECUTED cannot authorize unsafe non-idempotent retry.
current_attempt_id means active attempt only.
Canonical action bytes/digest are deterministic with golden vectors.
Cancellation never claims rollback.
Late results cannot regain progression authority.
Manual resolution cannot be overwritten.
Secrets exist only at adapter credential edge.
A stale checkpoint cannot override newer durable facts.
Stage 3.1 invariants still pass.
The full Python 3.14 + PostgreSQL 18 target gate is green.
```

Until final design re-review and acceptance:

```text
Stage 3.2 Design V0.3 — CORRECTIVE DRAFT
Final Re-review — REQUIRED
Design Acceptance — LOCKED
Implementation — LOCKED
Stage 3.3 — LOCKED
```
