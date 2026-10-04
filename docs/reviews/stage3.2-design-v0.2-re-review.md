# Stage 3.2 Durable Runtime — Design V0.2 Re-Review

Status: **RE-REVIEW COMPLETE — V0.2 NOT YET ACCEPTED**

Reviewed:

- `docs/design/stage3.2-durable-runtime-v0.2.md`
- `docs/acceptance/stage3.2-acceptance-v0.2.md`
- V0.1 Self-Review
- V0.1 Scenario Validation
- V0.1 Adversarial Review

Parent baseline:

- Stage 3.1 Core Runtime V1.0 — ACCEPTED / FROZEN

No implementation work is authorized by this review.

---

## 1. Executive result

V0.2 is a substantial improvement and closes the majority of V0.1 findings.

Original blocker closure:

- Fully closed: 9
- Partially closed: 1

Original major finding closure:

- Fully closed: 7
- Partially closed: 2

New re-review findings:

- Blocker: 5
- Major: 6
- Clarification: 3

Therefore:

```text
Design V0.2
❌ NOT YET ACCEPTED

Re-review
✅ COMPLETE

Small corrective revision
🔓 REQUIRED

Implementation
🔒
```

The remaining work is narrow. A V0.3 corrective revision should be sufficient;
a new broad architecture cycle is not required unless that revision introduces
new contradictions.

---

# 2. Closure of V0.1 blockers

## SR-B01 — physical attempt failure vs logical action failure

**CLOSED**

V0.2 explicitly separates ToolExecutionAttempt from ExternalAction and allows:

```text
Attempt FAILED + definite_not_executed=true
ExternalAction EXECUTING -> READY
```

when retry is permitted.

## SR-B02 — reconciliation transport failure vs business result

**CLOSED**

ReconciliationAttempt now has its own lifecycle and request failure no longer
means business action failure.

## SR-B03 — Action Commit Boundary atomicity

**CLOSED**

Run and ExternalAction locks plus fencing/cancel/budget/deadline checks are now
normative before STARTED/EXECUTING commit.

## SR-B04 — late-result semantics

**CLOSED**

The winner rule is now explicit: once UNKNOWN/reconciliation/manual/final state
wins, stale physical result becomes evidence only.

## SR-B05 — MANUAL_REVIEW vs terminal Run

**CLOSED**

V0.2 defines the terminal matrix and permits documented post-terminal
CANCELLED/FAILED + MANUAL_REVIEW while prohibiting COMPLETED + unresolved
action.

## SR-B06 — ToolExecutionAttempt state machine

**CLOSED**

STARTED -> SUCCEEDED | FAILED | UNKNOWN is explicit.

## SR-B07 — ToolCall projection

**CLOSED**

The ExternalAction -> ToolCall projection table is normative.

## SR-B08 — canonical snapshot digest

**PARTIALLY CLOSED**

V0.2 now defines format version, fields, key ordering, integer policy, secret
reference handling, and SHA-256.

One determinism gap remains: Unicode normalization / JSON string escaping and
canonical byte generation are not specified strongly enough for a digest that
will later bind approvals. See RR-M01.

## SR-B09 — cross-table progression enforcement

**CLOSED**

Run-row locking is now the normative progression serialization mechanism.

## SR-B10 — high-risk fail-closed

**CLOSED**

DESTRUCTIVE / approval-required / ineligible tools cannot execute in Stage 3.2.

---

# 3. Closure of V0.1 major findings

## SR-M01 — unified attempts

**CLOSED**

READ and side-effect physical calls now both use ToolExecutionAttempt.

## SR-M02 — budget reservation

**CLOSED**

Budget usage is atomically consumed with STARTED invocation/attempt.

## SR-M03 — absolute deadline

**CLOSED**

V0.2 defines DB-derived absolute `deadline_at`.

## SR-M04 — one retry scheduling source

**PARTIALLY CLOSED**

V0.2 chooses Run.available_at as the scheduling source, but does not yet define
the required Run status / lease-release transaction when entering durable
backoff. See RR-B02.

## SR-M05 — credential boundary

**CLOSED**

Secret resolution is restricted to adapter execution/reconciliation edge.

## SR-M06 — reconciliation from durable facts only

**CLOSED**

Model reasoning is explicitly excluded from reconciliation identity.

## SR-M07 — result/evidence shape

**CLOSED**

Redacted external resource/provider evidence is defined.

## SR-M08 — manual resolution race

**CLOSED**

Resolution locks the action and delayed reconciliation becomes evidence only.

## SR-M09 — terminalization guards

**PARTIALLY CLOSED**

The terminal matrix is strong, but budget/deadline denial of an already READY
action still lacks the stabilization transition required to satisfy it.
See RR-B03.

---

# 4. New blockers

## RR-B01 — takeover does not close orphaned physical attempts

V0.2 says:

- orphaned side-effect EXECUTING -> ExternalAction UNKNOWN;
- orphaned READ ToolCall is deterministically retried;
- reconciliation is retried after failure/restart.

But it does not define the durable status transition of the old physical
attempt when ownership is lost.

This creates concrete implementation contradictions.

### Side effect

Before takeover:

```text
ExternalAction EXECUTING
ToolExecutionAttempt #1 STARTED
```

Takeover changes only the action to UNKNOWN.

If attempt #1 remains STARTED:

- "max one STARTED attempt per ToolCall" blocks future safe attempt after
  authoritative NOT_EXECUTED;
- operational history incorrectly says an old worker still owns an active
  physical invocation.

Required transition at takeover:

```text
ToolExecutionAttempt #1 STARTED -> UNKNOWN
ExternalAction EXECUTING -> UNKNOWN
```

in the same recovery transaction.

### READ

An orphaned READ physical invocation may safely be retried, but the old
ToolExecutionAttempt must first leave STARTED.

Required rule must choose a final attempt state, for example:

```text
STARTED -> UNKNOWN
reason = LEASE_LOST_RESULT_NOT_DURABLE
ToolCall -> READY
```

The logical READ remains retryable even if the old physical attempt outcome is
unknown because READ has no business side effect.

### Reconciliation

An orphaned ReconciliationAttempt STARTED must also be closed before a new
reconciliation attempt may start.

Because reconciliation is read-only:

```text
old ReconciliationAttempt STARTED -> FAILED
reason = LEASE_LOST
action remains unresolved
new reconciliation attempt may later start
```

The exact chosen statuses must be frozen before implementation.

---

## RR-B02 — durable backoff lacks a Run queue/yield state transition

V0.2 correctly says `Run.available_at` is the scheduling source.

It does not define how a currently owned RUNNING Run becomes claimable after
the retry time.

A durable wait cannot rely on lease expiry as a scheduler.

Required normative transaction when business/reconciliation retry is scheduled:

```text
lock Run
set Run.status = QUEUED
set queue_reason = RETRY or RESCHEDULED
set available_at = DB-derived retry time
clear owner_worker_id
clear lease_expires_at
commit
```

or an equivalent explicit frozen rule.

At `available_at`, normal SKIP LOCKED claim resumes the Run and increments
execution_generation.

The same pattern must cover:

- model retry;
- READ retry;
- side-effect safe retry;
- reconciliation retry;
- deliberate runtime yield.

Without this, backoff/restart semantics are incomplete.

---

## RR-B03 — budget/deadline denial can leave an impossible READY action

Consider:

```text
ExternalAction READY
no attempt has started

deadline passes
or
tool-attempt budget is exhausted
```

Action Commit correctly refuses to start new business work.

But the terminal matrix also forbids FAILED/CANCELLED terminalization with a
runnable READY action.

V0.2 does not specify the stabilization transition.

Required rule:

When task budget/deadline permanently prevents a READY side effect from ever
crossing Action Commit:

```text
ExternalAction READY -> ABORTED
ToolCall -> NOT_EXECUTED
Run -> FAILED
failure_reason = BUDGET_EXCEEDED or deadline reason
```

unless cancellation already owns the terminal result.

Because no attempt crossed Action Commit, ABORTED is semantically valid.

The same design must define behavior before side-effect preparation so a model
result arriving after deadline/cancel cannot create a fresh runnable action.

---

## RR-B04 — cancel/deadline vs in-flight model result is not fully serialized

V0.2 prevents *starting* a new ModelInvocation after cancellation, but does not
state what happens when:

1. ModelInvocation was validly started;
2. cancel or deadline commits while provider request is in flight;
3. model returns a Tool proposal afterward.

If the normal model-consequence transaction creates ToolCall /
ActionSnapshot / ExternalAction without re-checking Run state under the Run
lock, a side-effect intent can appear after cancellation.

Required rule:

Every model-result consequence transaction must:

```text
lock Run
verify current invocation identity/generation
record ModelInvocation outcome
re-check cancel_requested / terminal / deadline
```

If new business progression is no longer permitted:

- preserve the durable ModelInvocation result/evidence;
- do not create a runnable ExternalAction;
- any Tool proposal is durably represented only as denied/not-executed
  consequence according to one frozen rule;
- no new model/tool progression is queued.

This must also be covered by acceptance concurrency tests.

---

## RR-B05 — BEST_EFFORT NOT_EXECUTED can weaken the frozen non-idempotent safety rule

V0.2 says BEST_EFFORT reconciliation may accept
`SUCCEEDED/FAILED/NOT_EXECUTED` according to adapter capability.

That is too broad.

The frozen architecture rule is:

> A non-idempotent side effect may automatically retry only after authoritative
> proof of NOT_EXECUTED.

Therefore a BEST_EFFORT "probably not executed" result must not silently become
READY for a non-idempotent action.

Required rule:

- AUTHORITATIVE NOT_EXECUTED may authorize retry;
- BEST_EFFORT NOT_EXECUTED:
  - may authorize retry only when independent idempotency semantics make retry
    safe under the declared ToolVersion capability; otherwise
  - MANUAL_REVIEW;
- NONE never auto-retries an UNKNOWN action.

The acceptance criteria must test this explicitly.

---

# 5. New major findings

## RR-M01 — canonical JSON byte generation needs one exact algorithm

V0.2 still allows different valid JSON byte encodings for the same Unicode
string, for example literal UTF-8 vs escaped `\uXXXX`, and does not specify
Unicode normalization.

For a future approval-binding digest, "standard JSON" is not precise enough.

The corrective revision must freeze one exact canonicalization algorithm,
including:

- Unicode normalization policy;
- string escaping;
- key ordering comparison rule;
- separators;
- UTF-8 emission;
- accepted numeric representation.

Using a named standard or a fully specified AgentForge Canonical JSON V1 is
acceptable, but tests must use golden byte vectors, not only digest equality
inside one process.

---

## RR-M02 — current_attempt_id lifecycle is ambiguous

ExternalAction has `current_attempt_id`.

The design must say whether it means:

- currently STARTED attempt only; or
- most recent attempt.

If it means current active attempt, it must be cleared on:

- definite pre-effect failure -> READY;
- UNKNOWN transition;
- finalization.

If historical lineage needs the last attempt, use a separate
`latest_attempt_id` or query attempts.

Ambiguous pointer semantics will complicate late-result fencing.

---

## RR-M03 — side-effect preparation should explicitly re-check business-work eligibility

The preparation transaction currently validates progression authority and
ToolVersion eligibility but should explicitly re-check:

- cancel_requested;
- terminal state;
- deadline;
- whether task budget can ever permit a Tool attempt.

No external I/O occurs in preparation, but creating a fresh READY business
action after business work is already prohibited is undesirable and forces
immediate cleanup.

This overlaps RR-B04 for model consequences and should be resolved with one
normative consequence transaction rule.

---

## RR-M04 — creation path for FAILED + MANUAL_REVIEW needs definition

The terminal matrix allows post-terminal:

```text
FAILED + MANUAL_REVIEW
```

but the design does not identify which transition creates it.

The corrective revision should either:

1. define explicit allowed causes; or
2. remove the combination for Stage 3.2 and keep only
   CANCELLED + MANUAL_REVIEW post-terminal.

No state combination should exist only as a theoretical exception.

---

## RR-M05 — credential "resolvable" check must not resolve the secret during preparation

The Stage-3.2 executable ToolVersion rule says credential binding must be
"resolvable through CredentialResolver".

This must mean:

- reference/configuration is valid and permitted to be resolved later;

not:

- fetch secret material during preparation.

Actual secret retrieval remains execution/reconciliation-edge only.

---

## RR-M06 — retry queue reason mapping should be explicit

V0.2 mentions RETRY/available_at semantics but should freeze the QueueReason
mapping for:

- model retry;
- READ retry;
- side-effect safe retry;
- reconciliation retry;
- recovery takeover;
- voluntary yield.

This improves observability and prevents retry cause from becoming inferred
from mutable state.

---

# 6. Clarifications

## RR-C01 — non-integer numeric arguments

Rejecting raw non-integer floats is safe but restrictive.

The corrective revision should state that Tool schema normalization may convert
decimal-like business values to a canonical string/integer representation
before snapshot creation.

The runtime must not silently round floats.

## RR-C02 — result evidence is not authorization

External resource ids/provider ids may support reconciliation but do not grant
permission to start new work.

This should be stated explicitly in the late-result/evidence section.

## RR-C03 — safety work after deadline remains bounded

V0.2 already introduces a reconciliation safety budget.

The corrective revision should state that other post-deadline safety
stabilization transactions are local/database-only and do not create unbounded
external business work.

---

# 7. Required acceptance additions

The next Acceptance Criteria revision must add mandatory cases for:

1. orphaned side-effect attempt is closed on takeover;
2. orphaned READ attempt is closed before deterministic retry;
3. orphaned reconciliation attempt is closed before retry;
4. retry scheduling atomically queues/yields the Run and releases lease;
5. deadline/budget with READY action produces ABORTED/NOT_EXECUTED before Run
   terminalization;
6. cancel while ModelInvocation is in flight cannot create new ExternalAction
   from the late model result;
7. deadline expiry while ModelInvocation is in flight cannot create new
   business progression;
8. BEST_EFFORT NOT_EXECUTED on a non-idempotent action cannot authorize blind
   retry;
9. canonical digest golden byte vectors across independent processes;
10. current/latest attempt pointer behavior across retry/UNKNOWN/finalization.

---

# 8. Re-review decision

V0.2 successfully solved the broad architectural problems.

The remaining defects are narrow but correctness-sensitive.

A small V0.3 revision should:

- specify orphaned physical-attempt cleanup;
- freeze durable yield/backoff queue transition;
- stabilize READY action on budget/deadline exhaustion;
- serialize model-result consequence against cancel/deadline;
- tighten BEST_EFFORT NOT_EXECUTED;
- finalize canonical bytes and attempt-pointer semantics;
- clarify the few remaining terminal/credential/queue details.

Then a short final re-review can decide design acceptance.

Current gate:

```text
Stage 3.2 Design V0.2
❌ NOT YET ACCEPTED

Design V0.2 Re-review
✅ COMPLETE

Corrective Design V0.3
🔓 UNLOCKED

Design Acceptance
🔒

Design Freeze
🔒

Implementation
🔒

Stage 3.3
🔒
```
