# Stage 3.2 Durable Runtime — Acceptance Criteria V0.2

Status: **REVISED DRAFT — NOT YET ACCEPTED**
Depends on: `docs/design/stage3.2-durable-runtime-v0.2.md`
Regression baseline: Stage 3.1 Core Runtime V1.0 official acceptance

Stage 3.2 cannot be accepted until every mandatory gate below passes in the
target environment:

- CPython 3.14;
- PostgreSQL 18;
- locked dependencies;
- mandatory real PostgreSQL integration tests;
- no skipped mandatory durability/concurrency tests.

---

## A. Stage 3.1 regression gate

All frozen Stage 3.1 guarantees remain true.

At minimum:

- durable Run creation/idempotency;
- SKIP LOCKED claim;
- DB-time lease;
- execution-generation fencing;
- durable ModelInvocation;
- logical ToolProposal / ToolCall;
- deterministic READ recovery;
- worker takeover/restart;
- event/message sequencing;
- active progression invariants;
- terminal Run constraints.

No accepted Stage 3.1 migration may be rewritten.

---

## B. State-model contract gate

Tests must verify legal and illegal transitions for:

1. Run;
2. ToolCall;
3. ToolExecutionAttempt;
4. ExternalAction;
5. ReconciliationAttempt;
6. ActionResolution.

Illegal direct transitions must fail closed.

Examples:

- ExternalAction UNKNOWN -> EXECUTING is rejected;
- ToolExecutionAttempt FAILED -> STARTED is rejected;
- second contradictory ActionResolution is rejected;
- ABORTED cannot be used from an ambiguous UNKNOWN outcome.

---

## C. ToolCall projection gate

For side effects, the exact projection must be tested:

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

No projection may depend on model reasoning.

READ ToolCall projection must remain compatible with Stage 3.1 semantics.

---

## D. Unified ToolExecutionAttempt gate

Every physical Tool invocation, READ or side effect, must create a durable
ToolExecutionAttempt.

Mandatory tests:

- first READ invocation -> attempt #1;
- transient READ retry -> attempt #2 on same ToolCall;
- process restart preserves attempt numbering;
- side-effect safe retry -> new attempt on same ToolCall/ExternalAction;
- one STARTED attempt per ToolCall;
- max_tool_attempts counts physical Tool attempts consistently.

---

## E. ActionSnapshot / digest gate

Canonical ActionSnapshot V1 must be deterministic.

Mandatory assertions:

- same durable action input in separate processes yields identical digest;
- object key input ordering does not change digest;
- array ordering does change digest when semantically changed;
- material ToolVersion change changes digest;
- material argument change changes digest;
- operation_id change changes digest;
- credential reference change changes digest;
- non-normalized float rejected according to V1 rule;
- digest algorithm is SHA-256;
- stored format_version is 1;
- snapshot cannot be mutated through normal repository/application path.

---

## F. Credential isolation gate

Use a sentinel secret.

The sentinel may be visible only inside the fake adapter execution edge.

It must be absent from:

- ModelRequest;
- model-visible Context;
- RunMessage;
- DomainEvent;
- ActionSnapshot;
- Checkpoint;
- public trace projection;
- durable error detail;
- structured logs captured by tests.

Only an opaque credential reference may persist.

Reconciliation must obey the same rule.

---

## G. Side-effect preparation gate

Before the first side-effect physical attempt:

```text
ToolCall
ActionSnapshot
ExternalAction READY
operation_id
```

must be committed.

Mandatory failure injections:

- DB error before preparation commit -> external adapter call count = 0;
- process crash after preparation commit -> action remains READY;
- takeover from READY may safely start exactly one authorized attempt.

---

## H. Action Commit Boundary gate

The fake external adapter must assert before accepting a side-effect call that
PostgreSQL already contains:

- ExternalAction EXECUTING;
- current ToolExecutionAttempt STARTED;
- matching stable operation_id;
- matching action snapshot/digest;
- reserved tool-attempt budget usage.

External I/O before this commit is a test failure.

---

## I. Cancel vs Action Commit race

Use real concurrent PostgreSQL transactions.

Case 1:

```text
cancel gets Run lock and commits first
```

Required:

- cancel_requested = true;
- READY action -> ABORTED;
- ToolCall -> NOT_EXECUTED;
- no attempt created;
- external call count = 0.

Case 2:

```text
Action Commit transaction commits first
```

Required:

- attempt is validly authorized;
- cancellation does not claim rollback;
- no later business attempt starts;
- current attempt is stabilized to final/UNKNOWN path.

Exactly one transactional ordering wins.

---

## J. Normal side-effect success

Required durable order:

```text
prepare durable intent
commit
start attempt / EXECUTING
commit
external effect
commit result
```

Required result:

- one external effect;
- one logical ExternalAction;
- one operation_id;
- attempt #1 SUCCEEDED;
- action SUCCEEDED;
- ToolCall SUCCEEDED;
- durable external resource evidence recorded.

---

## K. Definite pre-effect retry

Fake adapter must simulate:

- attempt #1 starts;
- failure definitely occurs before effect;
- error TRANSIENT;
- definite_not_executed = true.

Required:

- attempt #1 FAILED;
- action returns READY if retry policy allows;
- same operation_id;
- durable backoff;
- process restart preserves backoff;
- attempt #2 gets new attempt number;
- no duplicate external effect.

If retry budget is exhausted, no attempt #2 starts.

---

## L. Ambiguous external outcome

Fake adapter must simulate request/effect ambiguity.

Required:

- attempt -> UNKNOWN;
- ExternalAction -> UNKNOWN;
- ToolCall -> UNRESOLVED;
- no blind retry;
- no new model progression;
- reconciliation takes precedence.

Timeout must never be silently normalized to FAILED when execution may have
occurred.

---

## M. Crash-window matrix

Mandatory controlled crash points:

1. before preparation commit;
2. after READY commit;
3. before Action Commit transaction;
4. after EXECUTING/attempt commit but before adapter call;
5. during adapter call;
6. after external effect commit but before response;
7. after response arrives but before result DB commit;
8. during result DB transaction.

Required recovery must match Design V0.2.

Particularly:

- #1 -> no action/effect;
- #2 -> safe READY;
- #4-#8 when business truth cannot be proven -> UNKNOWN/reconciliation;
- no crash window causes blind duplicate non-idempotent execution.

---

## N. ReconciliationAttempt gate

Reconciliation request execution and business result must be independently
represented.

Mandatory:

- ReconciliationAttempt STARTED before external query;
- successful query -> attempt SUCCEEDED + normalized result;
- HTTP/transport failure -> attempt FAILED, business action remains unresolved;
- retry uses new reconciliation attempt;
- retry backoff survives process restart;
- attempt history remains queryable.

---

## O. Reconciliation business-result gate

### AUTHORITATIVE

- SUCCEEDED -> ExternalAction SUCCEEDED;
- FAILED -> ExternalAction FAILED;
- NOT_EXECUTED -> READY when retry allowed;
- UNKNOWN -> adapter contract violation path -> MANUAL_REVIEW;
- never blind retry from UNKNOWN.

### BEST_EFFORT

- inconclusive UNKNOWN -> MANUAL_REVIEW;
- accepted conclusive results must match declared capability.

### NONE

- uncertain ExternalAction -> MANUAL_REVIEW;
- no fake reconcile query is performed.

---

## P. Reconciliation safety-budget gate

Ordinary task budget/deadline may be exhausted while an action remains UNKNOWN.

Required:

- no new business/model work;
- reconciliation safety work may continue;
- bounded reconciliation attempts;
- durable backoff;
- after safety retry exhaustion -> MANUAL_REVIEW;
- no infinite autonomous reconciliation loop.

---

## Q. Late result vs takeover race

Real concurrency test:

```text
Worker A owns EXECUTING attempt
A lease expires
Worker B takes over
A external result returns concurrently
```

Two allowed serialized outcomes:

### A result transaction wins before UNKNOWN transition

- it may finalize current EXECUTING action;
- B observes final action and does not reconcile/retry.

### B UNKNOWN transition wins first

- A late result cannot directly finalize ExternalAction;
- result becomes late/conflicting evidence;
- A cannot enqueue progression;
- reconciliation/manual resolution owns business truth.

The test must force both orderings.

---

## R. Manual resolution vs delayed reconciliation race

Start with ExternalAction MANUAL_REVIEW.

Race:

- operator ActionResolution transaction;
- delayed reconciliation result transaction.

Required:

- exactly one business final outcome;
- if ActionResolution commits first, delayed reconciliation becomes evidence;
- contradictory second resolution rejected;
- terminal Run is never reopened.

---

## S. Cancellation while EXECUTING

Required:

- cancel_requested committed;
- no new business progression;
- current authorized attempt may record result;
- successful external effect remains SUCCEEDED;
- ambiguity still reconciles;
- cancellation does not produce ABORTED for an already uncertain/executing effect;
- Run terminalizes only after a stable action state.

---

## T. Terminal Run × ExternalAction matrix

Mandatory DB/domain tests:

### COMPLETED

Reject coexistence with:

- READY;
- EXECUTING;
- UNKNOWN;
- RECONCILING;
- MANUAL_REVIEW;
- required FAILED action.

### FAILED

May have final FAILED/ABORTED.

May have MANUAL_REVIEW only through documented post-terminal resolution path.

No autonomous runnable action state.

### CANCELLED

May coexist with:

- ABORTED;
- final SUCCEEDED;
- final FAILED;
- post-terminal MANUAL_REVIEW.

Must not terminalize with:

- READY;
- EXECUTING;
- UNKNOWN;
- RECONCILING.

### WAITING_ACTION_RESOLUTION

Must correspond to nonterminal Run with MANUAL_REVIEW when not using an allowed
post-terminal cancelled/failed resolution path.

---

## U. Post-terminal manual resolution

For:

```text
Run = CANCELLED or FAILED
ExternalAction = MANUAL_REVIEW
```

Required:

- explicit resolution accepted;
- ExternalAction finalizes;
- ToolCall projection updates;
- event/evidence appended;
- Run state remains terminal and unchanged;
- no autonomous progression is queued.

COMPLETED + MANUAL_REVIEW is prohibited.

---

## V. Cross-table single-progression gate

Under one Run, concurrently attempt:

- start ModelInvocation;
- start READ attempt;
- start side-effect attempt;
- start reconciliation.

Required:

- Run-row serialization permits only the valid next progression;
- no state with concurrent conflicting STARTED work commits;
- invariant survives two real worker processes/connections.

This gate must not rely only on independent partial indexes.

---

## W. Worker fencing gate

Mandatory:

- lease expiry alone removes old worker progression authority;
- takeover increments generation;
- stale worker cannot start new model/Tool/reconcile attempt;
- stale generation write rejected;
- stale result handling follows late-result evidence rules.

---

## X. Retry scheduling gate

All retry schedules use durable PostgreSQL time.

Mandatory:

- available_at survives restart;
- worker local clock skew does not trigger early retry;
- queue does not run before DB-time due;
- one Run-level runnable schedule remains consistent with action/reconcile retry;
- repeated retry rescheduling is deterministic.

---

## Y. Budget gate

Run budget minimum:

- max_model_invocations;
- max_tool_attempts;
- deadline_at;
- durable usage counters.

Mandatory:

- ModelInvocation START and budget consumption are atomic;
- ToolExecutionAttempt START and budget consumption are atomic;
- failed transaction consumes neither;
- restart does not reset usage;
- concurrent starts cannot exceed budget;
- deadline uses DB-derived absolute timestamp;
- no new business work after deadline.

Cost/billing budgets are explicitly out of scope.

---

## Z. Checkpoint / resume gate

Checkpoint must be optional for correctness.

Mandatory:

- current compatible checkpoint resumes private runner state;
- missing checkpoint still recovers from durable facts;
- stale checkpoint cannot overwrite newer ToolCall;
- stale checkpoint cannot overwrite newer ExternalAction;
- stale checkpoint cannot overwrite cancellation;
- unsupported checkpoint schema fails closed to durable reconstruction path;
- checkpoint contains no chain-of-thought;
- checkpoint contains no resolved credentials.

Adversarial authority case:

```text
checkpoint event high-water = 100
new durable events/actions = 101..104
restart
```

Required: 101..104 win.

---

## AA. High-risk fail-closed gate

ToolVersion examples:

1. non-destructive + approval_required=false + explicit no-approval eligibility;
2. DESTRUCTIVE;
3. approval_required=true;
4. missing reconciliation/idempotency declaration.

Only #1 may execute in Stage 3.2.

Others must not call external adapter.

No Stage 3.3 governance placeholder may default to allow.

---

## AB. Fake external system quality gate

The fake must be stateful and externally observable.

It must expose:

- operation ledger;
- operation_id lookup;
- external resource ids;
- physical call count;
- effect count;
- duplicate request count;
- reconciliation query count.

It must simulate:

- success;
- definite pre-effect failure;
- ambiguous timeout;
- effect committed + response lost;
- authoritative SUCCEEDED;
- authoritative FAILED;
- authoritative NOT_EXECUTED;
- authoritative contract-violating UNKNOWN;
- best-effort UNKNOWN;
- no reconciliation support;
- delayed response;
- controlled crash barriers.

A trivial scripted return-value mock does not satisfy this gate.

---

## AC. External evidence gate

Successful/reconciled actions must persist redacted evidence such as:

- external_resource_id;
- provider_request_id where applicable;
- provider status;
- redacted result metadata.

Evidence must survive restart and support reconciliation/manual review.

Secrets may not appear.

---

## AD. Migration gate

Mandatory:

- forward migration from frozen Stage 3.1 migration head;
- no edit to accepted Stage 3.1 migration files;
- PostgreSQL 18 online upgrade;
- revision id length compatible with Alembic version table;
- FK/CHECK/unique constraints enabled;
- downgrade path defined for development/test where supported;
- migration contract tests updated without weakening old guarantees.

---

## AE. Quality gate

Target acceptance runs:

```text
Python 3.14
uv sync --locked
Ruff
Ruff format --check
mypy strict
compile/import validation
Alembic online migration
full unit tests
full PostgreSQL integration tests
real concurrency tests
controlled crash-window tests
```

Mandatory PostgreSQL integration tests may not silently skip.

---

## AF. Acceptance evidence

Final acceptance record must include:

- immutable Stage 3.2 source digest;
- uv.lock digest and review record if dependencies change;
- Python target version;
- PostgreSQL major version;
- Alembic migration head;
- full test count;
- mandatory integration skip count = 0;
- official CI Run ID;
- accepted commit SHA;
- frozen Stage 3.2 branch/tag/checkpoint.

---

## AG. Stage exit assertions

Stage 3.2 is accepted only when all can be stated without qualification:

```text
Every physical Tool call has a durable Attempt.
A side effect is durably prepared before execution.
Action Commit is transactionally fenced against cancellation and stale owners.
An ambiguous side effect becomes UNKNOWN, not FAILED.
UNKNOWN is reconciled before any potentially duplicating retry.
A definite non-execution retry keeps the same operation_id.
Reconciliation request failure is distinct from business failure.
Cancellation never claims rollback.
Late stale results cannot regain progression authority.
Manual resolution cannot be overwritten by delayed reconciliation.
A stale checkpoint cannot override newer durable facts.
High-risk/approval-required tools fail closed in Stage 3.2.
Secrets exist only at adapter credential-resolution edge.
No non-idempotent effect is blindly retried.
Stage 3.1 invariants still pass.
The full Python 3.14 + PostgreSQL 18 target gate is green.
```

Until explicit design acceptance:

```text
Stage 3.2 Design V0.2 — REVISED DRAFT
Re-review — REQUIRED
Implementation — LOCKED
Stage 3.3 — LOCKED
```
