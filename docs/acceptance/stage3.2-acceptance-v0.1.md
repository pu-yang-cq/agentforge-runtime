# Stage 3.2 Durable Runtime — Acceptance Criteria V0.1

Status: **DRAFT — NOT ACCEPTED**
Depends on: Stage 3.2 Design V0.1
Regression baseline: Stage 3.1 official acceptance, 68 tests passed

The final Stage 3.2 implementation is not accepted until every mandatory gate
below passes in Python 3.14 + PostgreSQL 18.

## A. Regression gate

All Stage 3.1 frozen acceptance behaviors continue to pass.

No Stage 3.1 database invariant, FK, lease/generation fence, READ recovery rule,
or transaction boundary may be weakened merely to enable Stage 3.2.

## B. Checkpoint / resume

Mandatory scenarios:

| Scenario | Required result |
|---|---|
| restart from current checkpoint | Run resumes without replaying already committed consequence |
| stale checkpoint + newer ToolCall fact | newer ToolCall wins |
| stale checkpoint + newer ExternalAction fact | ExternalAction wins |
| stale checkpoint + cancel_requested | cancellation wins |
| corrupted/unsupported checkpoint schema | fail closed or use supported recovery path; never invent business truth |
| worker process restart | queued/running recoverable Run survives |

## C. Retry

| Scenario | Required result |
|---|---|
| transient READ failure | bounded retry using durable schedule |
| permanent READ failure | no blind retry |
| model transient failure | failed ModelInvocation remains durable; retry is a new invocation |
| retry delay | PostgreSQL server time / durable available_at |
| process restart during backoff | retry schedule survives restart |
| retry budget exhausted | no additional attempt |

## D. Budget / deadline

| Scenario | Required result |
|---|---|
| model budget reached | no new ModelInvocation |
| tool-attempt budget reached | no new ToolExecutionAttempt |
| durable deadline reached | no new autonomous work |
| action is UNKNOWN when budget expires | reconciliation still takes precedence |
| budget state after restart | usage is unchanged and durable |

## E. Cancellation

| Scenario | Required result |
|---|---|
| cancel queued Run | terminal CANCELLED without new work |
| cancel before next model call | no new ModelInvocation |
| cancel with READY side effect | action ABORTED; no external call |
| cancel while EXECUTING side effect | no rollback claim; current attempt outcome still recorded |
| cancel + ambiguous outcome | reconciliation still occurs |
| duplicate cancel command | idempotent |
| stale worker after cancel | cannot create new progression |
| cancelled Run | never reopens |

## F. Side-effect intent-before-effect

| Scenario | Required result |
|---|---|
| normal side-effect success | snapshot/action committed before adapter invocation |
| external adapter observes operation_id | stable ID supplied |
| retry same logical action | same operation_id, new attempt number |
| DB failure before Action READY commit | adapter is never called |
| DB failure before EXECUTING/attempt commit | adapter is never called |
| external call success | ExternalAction + ToolCall become SUCCEEDED |
| definite external failure | durable FAILED without duplicate retry unless policy permits |

The test adapter must be able to assert that the action row and attempt row
already exist before it is allowed to report an external effect.

## G. UNKNOWN / crash windows

| Crash / ambiguity | Required result |
|---|---|
| crash after READY commit, before attempt commit | recovery may safely start action |
| crash after EXECUTING commit, before external call | action becomes UNKNOWN; no blind retry |
| crash during external call | UNKNOWN |
| external success then worker dies before result commit | UNKNOWN then reconciliation |
| network timeout without proof | UNKNOWN |
| UNKNOWN action takeover | reconcile before any model progression |
| UNKNOWN non-idempotent action | never auto-retry without authoritative NOT_EXECUTED |

## H. Reconciliation

| Scenario | Required result |
|---|---|
| authoritative reconcile = SUCCEEDED | finalize action without second external call |
| authoritative reconcile = FAILED | finalize failed |
| authoritative reconcile = NOT_EXECUTED | action may return READY and retry |
| authoritative reconcile = UNKNOWN | fail contract / explicit unresolved path; no blind retry |
| best-effort reconcile = UNKNOWN | MANUAL_REVIEW |
| reconcile mode NONE | MANUAL_REVIEW |
| restart while RECONCILING | reconciliation resumes durably |
| reconciliation attempt history | append-only durable evidence |

## I. Manual resolution boundary

The application/domain command must support explicit resolution of
MANUAL_REVIEW actions with evidence and reason.

Mandatory behavior:

- append ActionResolution;
- update ExternalAction consistently;
- update projected ToolCall outcome;
- append domain event/audit-ready fact;
- never reopen terminal Run;
- duplicate identical resolution is idempotent or explicitly rejected without
  contradictory second outcome;
- contradictory resolution after final resolution is rejected.

Public RBAC protection is Stage 3.3 and is not a Stage 3.2 acceptance blocker.

## J. Late result / fencing

| Scenario | Required result |
|---|---|
| worker A lease expires, worker B takes over | A cannot start new attempt |
| A returns late model result | cannot create consequence |
| A returns late side-effect result for current committed attempt | may be accepted only under valid current-attempt transition |
| A returns result for superseded attempt | recorded/rejected as conflict; cannot advance Run |
| execution_generation mismatch | progression write rejected |
| expired lease before takeover | old worker already lacks progression authority |

## K. Concurrency / database invariants

PostgreSQL must enforce or transactionally protect:

- one nonterminal ExternalAction per Run;
- globally unique operation_id;
- one active/current side-effect attempt per action;
- no new model call while unresolved active side effect exists;
- action snapshot immutability;
- terminal Run cannot autonomously progress;
- all event/message sequences remain gap-free for committed facts under the
  accepted sequence-allocation model.

At least two real workers must contend for the same runnable Run in the
integration suite.

## L. Checkpoint authority test

A dedicated adversarial test must construct:

1. checkpoint at state X;
2. newer durable ExternalAction / cancellation / message facts at state X+N;
3. process restart;
4. resume.

Required result: the runtime chooses the newer durable facts and never rolls the
Run backward to X.

## M. Database / migration gate

Mandatory:

- forward migration from the frozen Stage 3.1 schema;
- migration on PostgreSQL 18;
- downgrade behavior defined for development/test if supported;
- Alembic revision identifiers fit version-table constraints;
- no rewrite of accepted Stage 3.1 migration history;
- FK and CHECK constraints remain enabled.

## N. Quality gate

Target environment must execute:

```text
Python 3.14
uv sync --locked
Ruff
Ruff format --check
mypy strict
compile/import checks
Alembic online migration
full unit + integration suite
```

The PostgreSQL integration suite is mandatory and may not silently skip in the
target gate.

## O. Required test doubles

Stage 3.2 must have deterministic fake external systems capable of simulating:

- success;
- definite failure;
- timeout/ambiguous result;
- effect succeeded but response lost;
- authoritative reconciliation to SUCCEEDED;
- authoritative reconciliation to FAILED;
- authoritative reconciliation to NOT_EXECUTED;
- reconciliation UNKNOWN;
- delayed/late result;
- worker crash at controlled boundaries.

These fakes must assert operation_id and call counts so duplicate effects are
observable in tests.

## P. Acceptance evidence

Final acceptance must record:

- immutable Stage 3.2 candidate source digest;
- reviewed uv.lock digest if it changes;
- target Python version;
- PostgreSQL major version;
- migration head;
- full test count;
- zero skipped mandatory integration tests;
- official CI run ID / commit;
- frozen Stage 3.2 branch or equivalent immutable checkpoint.

## Q. Exit condition

Stage 3.2 is accepted only when the final review can state all of the following
without qualification:

```text
A side effect is always durably intended before execution.
An ambiguous side effect is never silently treated as failed.
UNKNOWN is reconciled before retry.
Cancellation never claims rollback.
Stale workers cannot create new progression.
A stale checkpoint cannot override newer durable facts.
No non-idempotent side effect is blindly retried.
All Stage 3.1 invariants still hold.
The full Python 3.14 + PostgreSQL 18 target gate is green.
```

Until then:

```text
Stage 3.2 — IN PROGRESS
Stage 3.2 Acceptance — LOCKED
Stage 3.3 Governance — LOCKED
```
