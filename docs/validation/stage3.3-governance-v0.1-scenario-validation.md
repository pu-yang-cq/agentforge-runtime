# Stage 3.3 Governance — Design V0.1 Scenario Validation

Status: **SCENARIO VALIDATION COMPLETE — V0.1 NOT ACCEPTED**

Validated against:
- docs/design/stage3.3-governance-v0.1.md
- docs/acceptance/stage3.3-governance-acceptance-v0.1.md
- docs/reviews/stage3.3-governance-v0.1-self-review.md

Parent baseline:
- Stage 3.2 Runtime V1.0 — ACCEPTED / FROZEN

No design rewrite is performed in this phase.

## 1. Validation method

Each scenario is evaluated as a concrete timeline across:

- initiating principal;
- model/worker;
- PostgreSQL;
- approver;
- policy engine;
- external provider;
- cancellation/expiry/deadline actor where relevant.

Verdicts:
- PASS — one safe implementable outcome is already determined;
- PARTIAL — direction is safe but state/transaction details are incomplete;
- FAIL — V0.1 permits unsafe or contradictory implementation.

Summary:

- PASS: 5
- PARTIAL: 5
- FAIL: 7

V0.1 does not pass scenario validation.

## 2. SV-01 — policy ALLOW READ

Timeline:

~~~text
Run RUNNING
  -> model proposes READ
  -> deterministic policy ALLOW
  -> PolicyDecision durable
  -> ToolExecutionAttempt STARTED
  -> READ adapter
  -> result
~~~

Verdict: **PARTIAL**

Direction is valid.

Missing:
- exact Run requester/policy source;
- exact budget increments around governance decision.

Mapped:
- SR-B02;
- SR-B03;
- SR-B11.

## 3. SV-02 — policy DENY side effect

Timeline:

~~~text
model proposes create_ticket
policy DENY
  -> durable PolicyDecision
  -> ToolCall DENIED
  -> Run FAILED
  -> no adapter call
~~~

Verdict: **PASS**

The fail-closed behavior is unambiguous.

Cancellation still needs to win if it commits first, as already required by the parent
Stage 3.2 consequence fence.

## 4. SV-03 — approval-required READ survives restart

Timeline:

~~~text
model proposes READ
policy REQUIRE_APPROVAL
ToolCall AWAITING_APPROVAL
Run WAITING_APPROVAL
worker exits

approver APPROVE
Run QUEUED(APPROVAL_RESOLVED)

new worker claims
~~~

Verdict: **PARTIAL**

V0.1 says the ToolCall becomes READY and can be recovered, which is directionally correct
for READ.

It does not define a durable discriminator that also works safely for approved side effects.

Mapped:
- SR-B01;
- SR-M07.

## 5. SV-04 — approved WRITE is misclassified as READ recovery

Timeline:

~~~text
model proposes WRITE
policy REQUIRE_APPROVAL
ToolCall AWAITING_APPROVAL
no ExternalAction yet

approver APPROVE
ToolCall -> READY
Run -> QUEUED(APPROVAL_RESOLVED)

worker claims

Stage 3.2 load_recoverable_read_call:
  sees READY ToolCall
  sees no ExternalAction
  therefore may classify as READ
~~~

Verdict: **FAIL**

This is a concrete unsafe state collision, not merely naming ambiguity.

An approved side effect requires a distinct durable state or preapproval ExternalAction
identity.

Mapped:
- SR-B01;
- SR-B07;
- SR-M07.

## 6. SV-05 — destructive operation approved correctly

Timeline:

~~~text
DESTRUCTIVE proposal
policy ALLOW
effective REQUIRE_APPROVAL
human APPROVE
resume
ActionSnapshot + ExternalAction
Action Commit
physical effect
~~~

Verdict: **PARTIAL**

The policy direction is safe.

The bridge from durable approval to a DESTRUCTIVE-capable coordinator path is not specified.
A careless implementation could broaden stage32_side_effect_executable globally.

Mapped:
- SR-B06;
- SR-B10.

## 7. SV-06 — requester identity lost after restart

Timeline:

~~~text
HTTP principal = alice
Run created
worker executes later after restart

policy requires requester role/operator relationship
~~~

Question:

Where does runtime recover that the requester was alice?

Verdict: **FAIL**

V0.1 lacks the durable authority source.

Using the current worker, model text, or a new API request would be incorrect.

Mapped:
- SR-B02;
- SR-M02.

## 8. SV-07 — old Stage 3.2 AgentVersion after migration

Timeline:

~~~text
existing AgentVersion from accepted Stage 3.2
no GovernancePolicyVersion reference
Stage 3.3 code deployed
existing Stage 3.2 regression creates Run
~~~

V0.1 default is DENY when no matching policy exists.

Verdict: **FAIL**

This conflicts with the mandatory Stage 3.2 regression requirement unless migration assigns
a deterministic compatibility policy.

Mapped:
- SR-B04.

## 9. SV-08 — two matching policy rules conflict

Rules:

~~~text
rule A: role=developer, tool=X -> ALLOW
rule B: effect=WRITE, tool=X -> REQUIRE_APPROVAL
same principal matches both
~~~

V0.1 states outcome precedence but not whether all matching rules are evaluated, how
rule_id is chosen, or whether explicit priority overrides outcome precedence.

Verdict: **FAIL**

The same policy JSON could be interpreted differently by two implementations.

Mapped:
- SR-B05.

## 10. SV-09 — cancellation while waiting

Timeline:

~~~text
Run WAITING_APPROVAL
Request PENDING
ToolCall AWAITING_APPROVAL

cancel transaction locks Run first
  -> request CANCELLED
  -> ToolCall NOT_EXECUTED
  -> Run CANCELLED

late approver submits APPROVE
~~~

Verdict: **PASS**

V0.1 clearly requires late approve to fail and zero physical attempts.

The state machine is sufficient for this order.

## 11. SV-10 — approve vs cancel concurrent race

Two transactions:

~~~text
T1 APPROVE
T2 CANCEL
~~~

Both require Run root lock.

Verdict: **PASS**

The serialization principle determines a winner.

Acceptance must verify both orders against real PostgreSQL.

## 12. SV-11 — approval vs expiry

At DB time T:

~~~text
expires_at <= T
approver submits APPROVE
expiry sweeper selects request
~~~

Verdict: **FAIL**

V0.1 requires DB time but does not define the expiry selector/lock order or whether expiry is
capped to the Run deadline.

Two implementations could disagree about whether APPROVE or EXPIRED wins.

Mapped:
- SR-B08;
- SR-M03;
- SR-M04.

## 13. SV-12 — approval arrives after Run deadline

Timeline:

~~~text
request PENDING
Run deadline passes
authorized human approves
~~~

Verdict: **PARTIAL**

V0.1 correctly prohibits physical continuation.

It is ambiguous whether ApprovalRequest becomes APPROVED or EXPIRED and how this differs from
ApprovalDecision evidence.

Mapped:
- SR-M04.

## 14. SV-13 — separation of duties

Timeline:

~~~text
requester alice
policy requires approver role=ops
SoD=true

alice has ops role and attempts approve
~~~

Verdict: **PASS**

V0.1 clearly rejects self-approval.

A different authorized ops principal may decide.

## 15. SV-14 — policy retired after Run creation

Timeline:

~~~text
Run pins policy v7
policy v7 later RETIRED
Run reaches Tool proposal
~~~

Verdict: **FAIL**

V0.1 says policy is pinned but does not specify retirement semantics.

Possible unsafe implementations:
- silently switch Run to newest version;
- reject existing Run;
- continue v7.

Only one must be normative.

Mapped:
- SR-B03;
- SR-M01;
- SR-C01.

## 16. SV-15 — approval API identity spoof

Caller sends:

~~~text
POST /approve
body.approver_identity = "admin"
~~~

Verdict: **PASS for new approval API**, because V0.1 forbids caller-chosen identity.

However current ActionResolution still accepts resolver_identity from the body.

Overall governance product claim remains **PARTIAL** until existing mutating API trust
surfaces are aligned.

Mapped:
- SR-B09.

## 17. SV-16 — approved destructive action becomes UNKNOWN

Timeline:

~~~text
human approves exact destructive intent
worker crosses Action Commit
provider commits effect
response lost
ToolExecutionAttempt -> UNKNOWN
ExternalAction -> UNKNOWN
~~~

Question:
Can the previous approval be used to retry?

Verdict: **PASS**

V0.1 explicitly says approval cannot authorize UNKNOWN retry.

Stage 3.2 reconciliation/manual resolution remains authoritative.

This is a strong preserved boundary.

## 18. SV-17 — approval decision commits, worker crashes before claim

Timeline:

~~~text
APPROVE commits
Run QUEUED(APPROVAL_RESOLVED)
process crashes

later worker claims
~~~

Verdict: **FAIL for side effect / PARTIAL for READ**

READ can plausibly recover from READY.

Side effect hits the SR-B01 ambiguity and may enter the wrong recovery path.

## 19. Required V0.2 scenario closures

V0.2 must determine one exact result for:

1. approved READ durable state;
2. approved side-effect durable state;
3. side-effect intent identity before/after approval;
4. requester principal persistence;
5. policy assignment/pinning;
6. migrated Stage 3.2 versions;
7. rule conflict/priority;
8. policy retirement;
9. expiry/approve ordering;
10. post-deadline decision state;
11. control-plane API authorization;
12. exact budget accounting.

## 20. Gate state

~~~text
Stage 3.3 V0.1 Scenario Validation
✅ COMPLETE

PASS:    5
PARTIAL: 5
FAIL:    7

Design V0.1
❌ NOT ACCEPTED

Adversarial Review
🔓 NEXT

Implementation
🔒 LOCKED
~~~

Governing finding:

> Approval waiting is safe only if the durable post-approval state cannot be confused with
> a pre-existing Stage 3.2 execution/recovery state.
