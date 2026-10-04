# Stage 3.2 Durable Runtime — Design V0.1 Scenario Validation

Status: **SCENARIO VALIDATION COMPLETE — V0.1 NOT ACCEPTED**
Validated against:

- `docs/design/stage3.2-durable-runtime-v0.1.md`
- `docs/reviews/stage3.2-design-v0.1-self-review.md`
- `docs/acceptance/stage3.2-acceptance-v0.1.md`

Parent baseline:

- Stage 3.1 Core Runtime V1.0 — ACCEPTED / FROZEN

This phase intentionally validates the unmodified Design V0.1. No design
rewrite is performed here.

## 1. Validation method

Each scenario is evaluated as a concrete timeline across:

- Worker A;
- Worker B / takeover owner;
- PostgreSQL;
- external business system;
- operator/cancel command where relevant.

Verdicts:

- **PASS** — V0.1 already determines one safe and implementable outcome.
- **PARTIAL** — direction is safe, but one or more transaction/state details
  are insufficiently specified.
- **FAIL** — V0.1 permits contradictory or unsafe implementations, or lacks a
  legal state transition needed by the scenario.

Summary:

- PASS: 5
- PARTIAL: 5
- FAIL: 10

Design V0.1 therefore does **not** pass scenario validation.

---

# 2. Scenario SV-01 — Normal side-effect success

## Timeline

```text
Worker A
  |
  | model proposes create_jira(...)
  v
PostgreSQL
  ToolProposal committed
  ToolCall committed
  ActionSnapshot committed
  ExternalAction READY + operation_id committed
  |
  v
Worker A locks Run + Action
  ExternalAction READY -> EXECUTING
  ToolExecutionAttempt STARTED
  COMMIT
  |
  v
External Jira
  receives operation_id
  creates issue ABC-123
  returns success
  |
  v
PostgreSQL
  attempt -> SUCCEEDED
  action -> SUCCEEDED
  ToolCall projected -> SUCCEEDED
  event/message committed
  |
  v
Worker A continues model reasoning
```

## Verdict

**PARTIAL**

V0.1 correctly requires durable intent and a committed attempt before external
I/O.

Missing details:

- exact ToolExecutionAttempt state machine;
- exact ToolCall projection;
- atomic budget reservation;
- exact action-result/evidence shape.

Mapped findings:

- SR-B06;
- SR-B07;
- SR-M02;
- SR-M07.

---

# 3. Scenario SV-02 — Crash after Action READY commit, before attempt commit

## Timeline

```text
PostgreSQL
  ExternalAction READY committed
  no ToolExecutionAttempt exists

Worker A crashes

lease expires

Worker B takeover
  reads ExternalAction READY
  verifies ownership/cancel/budget
  creates attempt + EXECUTING
  commits
  invokes external system
```

## Verdict

**PASS**

V0.1 explicitly distinguishes this window and permits safe execution because no
attempt crossed the Action Commit Boundary.

Required invariant to preserve in revision:

> READY means durable intent exists but no authorized physical side-effect
> attempt has crossed the execution commit boundary.

---

# 4. Scenario SV-03 — Crash after EXECUTING commit, before actual socket write

## Timeline

```text
Worker A
  commits:
    ExternalAction EXECUTING
    Attempt #1 STARTED

Worker A crashes
  before external client writes bytes

Worker B takeover
```

Worker B cannot prove from durable facts whether A wrote the request before
crashing.

## Verdict

**PASS**

V0.1 correctly requires:

```text
EXECUTING orphan
  -> UNKNOWN
  -> reconciliation
```

It must not assume NOT_EXECUTED merely because the process died quickly.

This scenario validates the conservative UNKNOWN rule.

---

# 5. Scenario SV-04 — External system succeeds, response commit is lost

## Timeline

```text
DB:
  action EXECUTING
  attempt #1 STARTED

External Jira:
  creates ABC-123
  returns HTTP 201

Worker A:
  receives result
  crashes before DB result transaction

lease expires

Worker B:
  sees orphaned EXECUTING
```

## Verdict

**PASS**

V0.1 correctly requires:

```text
UNKNOWN
 -> RECONCILING
 -> query by operation_id / durable evidence
 -> SUCCEEDED
```

and explicitly forbids blindly creating a second issue.

This is one of the strongest parts of V0.1.

---

# 6. Scenario SV-05 — Network timeout after request transmission

## Timeline

```text
Worker A sends create request
network path times out

possibility A:
  server never received request

possibility B:
  server created resource, response lost

Worker A cannot distinguish A vs B
```

## Verdict

**PASS**

V0.1 correctly classifies the outcome as UNKNOWN rather than FAILED.

Required preserved rule:

> Transport ambiguity is not proof of business failure or non-execution.

---

# 7. Scenario SV-06 — Cancellation races Action Commit Boundary

## Timeline

```text
T1 Worker A:
  reads cancel_requested = false

T2 User:
  requests cancellation

T3 Worker A:
  sets ExternalAction EXECUTING
  creates attempt
  commits

T4 Cancel transaction:
  commits cancel_requested = true

T5 Worker A:
  invokes external Jira
```

A different interleaving is also possible:

```text
cancel commits first
worker commits EXECUTING second
```

## Verdict

**FAIL**

V0.1 says execution is "subject to cancellation" but does not define the
transactional serialization point.

Without a normative lock rule, both implementations below satisfy the text:

1. cancel commits first and external call still happens;
2. worker commits first and external call happens.

The revised design must require both commands to serialize on the Run row.

Required rule:

```text
Action Commit Tx:
  lock Run
  lock ExternalAction
  verify current generation/lease
  verify cancel_requested = false
  reserve budget
  create current attempt
  action -> EXECUTING
  append event
  COMMIT
```

Cancel command also locks the same Run row.

If cancellation wins the lock/commit first, no new attempt may cross the
boundary.

Mapped findings:

- SR-B03;
- AC-G01.

---

# 8. Scenario SV-07 — Late worker result races takeover UNKNOWN transition

## Timeline

```text
A:
  action EXECUTING
  attempt #1 STARTED
  external request in flight

A lease expires

B:
  takes generation N+1

race:

A receives external SUCCESS
B prepares EXECUTING -> UNKNOWN
```

Possible ordering 1:

```text
A result transaction commits first
B later sees action SUCCEEDED
```

Possible ordering 2:

```text
B commits UNKNOWN first
A result arrives later
```

## Verdict

**FAIL**

V0.1 says the late result "may update" if the attempt is still current, but that
is not enough.

The design must define the atomic winner based on the action row state under
lock.

Recommended rule for later revision:

- if the authorized attempt finalizes while action is still EXECUTING and no
  takeover uncertainty transition has committed, its result may finalize the
  action;
- once UNKNOWN/RECONCILING/MANUAL_REVIEW/final resolution is committed, the
  old worker result is evidence only;
- a stale worker result never grants progression authority.

Mapped findings:

- SR-B04;
- AC-G03.

---

# 9. Scenario SV-08 — Reconciliation request itself times out

## Timeline

```text
Action UNKNOWN

Worker B:
  action -> RECONCILING
  ReconciliationAttempt #1 starts

External Jira query:
  HTTP timeout

Business truth remains unknown
```

## Verdict

**FAIL**

V0.1 only defines the normalized business reconciliation result:

```text
SUCCEEDED | FAILED | NOT_EXECUTED | UNKNOWN
```

It does not distinguish:

```text
the reconcile request failed
```

from:

```text
the reconcile request succeeded and authoritatively returned UNKNOWN
```

Those are operationally different.

Required later model:

```text
ReconciliationAttempt:
  STARTED
  SUCCEEDED(result = ...)
  FAILED(error = TRANSIENT/PERMANENT)
```

A transient failed reconciliation request schedules another reconciliation
attempt; it does not mutate business truth to FAILED.

Mapped findings:

- SR-B02;
- AC-G05.

---

# 10. Scenario SV-09 — Definite pre-effect transient failure

Example: adapter fails while resolving DNS or creating a connection before any
request bytes can possibly reach the external system.

## Timeline

```text
Action EXECUTING
Attempt #1 STARTED

adapter returns:
  definite_not_executed = true
  error_class = TRANSIENT

retry policy allows retry
```

## Verdict

**FAIL**

V0.1 currently has:

```text
EXECUTING -> FAILED | UNKNOWN | SUCCEEDED
```

but also says retryable side-effect failures may retry.

If `ExternalAction.FAILED` is final, the retry has no legal transition.

This validates SR-B01.

Later design must distinguish physical attempt failure from logical action
failure.

Expected semantic shape:

```text
Attempt #1 -> FAILED(definite NOT_EXECUTED)
Action -> READY
available_at = durable backoff
same operation_id

Attempt #2 -> STARTED
```

Mapped findings:

- SR-B01;
- AC-G04.

---

# 11. Scenario SV-10 — Cancel while Action is READY

## Timeline

```text
Action READY
no attempt exists

Cancel command begins
Worker action-start command begins concurrently
```

## Verdict

**FAIL**

The desired result is clear:

- if cancel wins serialization: Action -> ABORTED, adapter never called;
- if action commit wins first: cancellation cannot claim rollback; authorized
  attempt must stabilize.

V0.1 does not define the shared locking point, so this is the same fundamental
race as SV-06.

It also validates that ABORTED must mean known-not-executed.

Mapped findings:

- SR-B03;
- SR-C05.

---

# 12. Scenario SV-11 — Cancel while Action is EXECUTING, external system succeeds

## Timeline

```text
Action EXECUTING
Attempt #1 STARTED

cancel_requested = true

external system succeeds
result arrives

DB records action SUCCEEDED
```

The Run must not continue autonomous work, but the already-authorized external
result is real business truth.

## Verdict

**PARTIAL**

V0.1 correctly says cancellation is not rollback and permits the attempt result
to be recorded.

What remains undefined is terminalization:

- should the Run become CANCELLED immediately after the action is stabilized?
- can the successful Tool result be added to RunMessage before terminalization?
- if action resolution is still uncertain, may CANCELLED coexist with
  MANUAL_REVIEW?

Mapped findings:

- SR-B05;
- SR-M09.

---

# 13. Scenario SV-12 — Manual resolution races delayed reconciliation

## Timeline

```text
Action MANUAL_REVIEW

Operator:
  resolves SUCCEEDED with evidence

at the same time:
  delayed reconcile request returns FAILED
```

## Verdict

**FAIL**

V0.1 does not define a locking/winner rule.

Required property:

> Exactly one final business outcome wins.

Recommended later rule:

- resolution transaction locks ExternalAction;
- once a final ActionResolution is committed, reconciliation cannot overwrite
  the business outcome;
- delayed reconciliation result is stored only as evidence/conflict.

Mapped findings:

- SR-M08;
- AC-G02.

---

# 14. Scenario SV-13 — Stale checkpoint vs newer durable action facts

## Timeline

```text
Checkpoint C:
  event high-water = 100
  runner working state = before side effect

Later durable facts:
  event 101 ToolProposal
  event 102 ExternalAction READY
  event 103 attempt STARTED
  event 104 action UNKNOWN
  cancel_requested = true

process restarts and loads checkpoint C
```

## Verdict

**PASS**

V0.1 clearly states that checkpoint is not the system of record and that newer
ExternalAction/cancellation facts win.

However implementation still needs an explicit replay/overlay algorithm.

This scenario validates the principle but leaves an implementation detail, not
a design contradiction.

---

# 15. Scenario SV-14 — Budget expires while action is UNKNOWN

## Timeline

```text
Run deadline reached

ExternalAction UNKNOWN
requires reconciliation for safety
```

## Verdict

**PARTIAL**

V0.1 correctly says action safety/reconciliation takes precedence over budget
termination.

Missing details:

- whether reconciliation attempts have a separate bounded safety budget;
- how infinite transient reconciliation failure is prevented;
- whether Run deadline remains exceeded while WAITING_ACTION_RESOLUTION;
- when the Run may finally terminalize.

Mapped findings:

- SR-M02;
- SR-M03;
- SR-M04.

---

# 16. Scenario SV-15 — Two workers race to start different progression types

## Timeline

```text
Run generation belongs to Worker B after takeover

Worker B path:
  wants to start ModelInvocation

Concurrent recovery path:
  sees ExternalAction READY and wants to start Attempt

or due to bug:
  two worker tasks in same process attempt both
```

## Verdict

**FAIL**

Separate partial unique indexes cannot protect the cross-table invariant:

```text
no STARTED ModelInvocation
while active ExternalAction/Attempt exists
```

V0.1 lists the invariant but does not define its enforcement mechanism.

Stage 3.1 already demonstrated the needed pattern:

```text
lock Run first
  -> inspect all active progression tables
  -> perform exactly one start transition
```

This must become normative in V0.2.

Mapped finding:

- SR-B09.

---

# 17. Scenario SV-16 — Approval-required / destructive tool proposed in Stage 3.2

## Timeline

```text
ToolVersion:
  effect = DESTRUCTIVE
  approval_required = true

Model proposes tool

Stage 3.3 approval/policy does not exist yet
```

## Verdict

**FAIL**

V0.1's generic "side-effect Tool support" could be implemented as immediate
execution.

That would create a temporary unsafe path that contradicts the frozen security
architecture.

Required later rule:

```text
Stage 3.2 executable side effect
  only if ToolVersion is explicitly eligible for no-approval execution

approval-required or DESTRUCTIVE
  -> fail closed / NOT_EXECUTED
```

Mapped findings:

- SR-B10;
- AC-G06.

---

# 18. Scenario SV-17 — Snapshot digest reproduced after restart

## Timeline

```text
Process A canonicalizes action:
  tool_version = V17
  args = {"summary": "x", "priority": 1}
  operation_id = O123
  digest = D

process dies

Process B reconstructs from durable facts
and later Stage 3.3 wants to validate an approval against D
```

## Verdict

**FAIL**

V0.1 does not define enough canonicalization detail to guarantee the same digest
across processes/languages/library versions.

This is a future governance-integrity issue, not merely an implementation
detail.

Required later specification must freeze:

- canonical format version;
- exact included fields;
- UTF-8;
- object key ordering;
- number restrictions/normalization;
- hash algorithm;
- treatment of credential references;
- operation_id inclusion.

Mapped findings:

- SR-B08;
- AC-G07.

---

# 19. Scenario SV-18 — Credential sentinel leaks through side-effect path

## Timeline

```text
CredentialResolver returns:
  SECRET_SENTINEL_9f0...

Adapter uses secret to call Jira

Later inspect:
  ModelRequest
  ActionSnapshot
  RunMessage
  DomainEvent
  checkpoint
  logs
```

## Verdict

**FAIL**

V0.1 only says "Secrets are references, not copied secret values" in
ActionSnapshot.

It does not explicitly re-establish the full execution-edge credential boundary
for side effects and reconciliation.

The revised design must prohibit resolved secret material from all durable/model
facts and resolve credentials only at adapter edge.

Mapped findings:

- SR-M05;
- SR-C02;
- AC-G08.

---

# 20. Scenario SV-19 — Run is CANCELLED while action still requires manual review

Consider:

```text
Action EXECUTING
cancel_requested = true
attempt becomes ambiguous
Action -> UNKNOWN -> RECONCILING -> MANUAL_REVIEW
```

Question:

Should Run be:

```text
WAITING_ACTION_RESOLUTION
```

or:

```text
CANCELLED
while ExternalAction remains MANUAL_REVIEW
```

## Verdict

**FAIL**

V0.1 explicitly leaves this unresolved.

Both designs have implications:

### Option A — stay WAITING_ACTION_RESOLUTION

Pros:

- no terminal Run contains unresolved business truth;
- simpler terminal invariant.

Cons:

- user's cancel request does not reach terminal CANCELLED until operator work
  completes.

### Option B — CANCELLED + MANUAL_REVIEW

Pros:

- cancellation semantics finish independently of external uncertainty;
- matches frozen Stage 2 allowance for post-terminal operator resolution.

Cons:

- terminal Run contains unresolved action;
- every read projection and terminal guard must understand that exception.

Scenario validation does not choose between them yet, but proves that V0.2 must
freeze the matrix.

Mapped findings:

- SR-B05;
- SR-M09;
- AC-G09.

---

# 21. Scenario SV-20 — READ retry and attempt accounting

## Timeline

```text
READ ToolCall C1

physical invocation #1
  transient failure

durable backoff

process restart

physical invocation #2
  success
```

Questions:

- max_tool_attempts increments by 1 or 2?
- where are both physical calls recorded?
- can observability distinguish them?
- can a stale invocation result be fenced?

## Verdict

**PARTIAL**

Stage 3.1 ToolCall semantics remain safe, but V0.1 does not clearly say whether
READ physical attempts use ToolExecutionAttempt.

Scenario validation supports the self-review recommendation:

> Stage 3.2 should unify all physical Tool invocations under
> ToolExecutionAttempt while preserving ToolCall as the logical request.

Mapped findings:

- SR-M01;
- AC-G10.

---

# 22. Cross-scenario conclusions

## 22.1 Principles that survived validation

The following V0.1 principles survived all tested scenarios and should be
carried into V0.2:

```text
Intent Before Effect
UNKNOWN != FAILED
Cancellation != Rollback
Persisted Facts > Checkpoint > New Reasoning
No global exactly-once claim
Stable operation_id across logical retries
DB time is authoritative
No DB transaction across external I/O
```

## 22.2 Main architectural defect class

The dominant failure class is not missing components.

It is:

> V0.1 often states *what must be true* but does not yet state the atomic
> transaction / lock / state-transition rule that makes competing actors
> converge on one outcome.

This appears in:

- cancel vs action start;
- late result vs takeover;
- manual resolution vs reconciliation;
- model start vs action start;
- budget vs work start.

Therefore V0.2 must elevate transaction boundaries and lock order from
implementation detail to normative architecture.

## 22.3 Required state-model refinements

Scenario validation confirms that V0.2 needs separate state machines for:

1. Run;
2. logical ToolCall;
3. physical ToolExecutionAttempt;
4. logical ExternalAction;
5. ReconciliationAttempt;
6. ActionResolution finalization.

A single FAILED concept cannot safely represent all layers.

## 22.4 Required terminal matrix

V0.2 must contain an explicit matrix for:

```text
Run state
x
ExternalAction state
x
whether autonomous work is allowed
x
whether operator resolution is allowed
```

No terminal-state exception may be left implicit.

---

# 23. Scenario-validation gate decision

```text
Stage 3.2 Design V0.1
❌ NOT ACCEPTED

Self Review
✅ COMPLETE

Scenario Validation
✅ COMPLETE

Scenario result:
  PASS     5
  PARTIAL  5
  FAIL    10

Reverse / Adversarial Review
🔓 NEXT

Design Modification
🔒

Design V0.2
🔒

Design Acceptance
🔒

Implementation
🔒
```

The next phase must perform reverse/adversarial review of the unmodified V0.1
plus the self-review and scenario findings. Only after that phase should the
design be rewritten.
