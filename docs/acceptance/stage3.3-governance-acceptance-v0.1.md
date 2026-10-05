# Stage 3.3 Governance Control Plane — Acceptance Criteria V0.1

Status: **DRAFT — NOT ACCEPTED**

Depends on:
- docs/design/stage3.3-governance-v0.1.md

Regression baseline:
- Stage 3.2 Runtime V1.0 immutable RC2
- rc/stage3.2-v1.0-r2
- fa747268cfbf1d5b57e5796b9cbc767abc3d4e0c

No implementation work is authorized by these draft criteria.

## A. Stage 3.2 regression gate

The complete accepted Stage 3.2 Python 3.14 + PostgreSQL 18 gate must remain green.

Mandatory:
- no accepted Stage 3.1 or Stage 3.2 migration may be rewritten;
- all Stage 3.2 crash/recovery invariants still pass;
- Action Commit remains the physical side-effect boundary;
- UNKNOWN/reconciliation/cancellation/manual-resolution semantics remain unchanged.

## B. Deterministic governance decision gate

Given identical:
- PrincipalContext;
- AgentVersion;
- ToolVersion;
- Tool proposal;
- pinned GovernancePolicyVersion;

the policy engine must produce the same:
- effective decision;
- matched rule id;
- intent digest.

The model is never called to determine ALLOW / DENY / REQUIRE_APPROVAL.

## C. Capability-envelope gate

Policy may restrict but never broaden ToolVersion capability.

Mandatory cases:

1. approval_required=true + policy ALLOW -> REQUIRE_APPROVAL;
2. DESTRUCTIVE + policy ALLOW -> REQUIRE_APPROVAL;
3. policy DENY -> DENY regardless of no-approval capability;
4. WRITE/EXTERNAL_SIDE_EFFECT may no-approval ALLOW only when durable capability permits;
5. unbound or mismatched ToolVersion -> DENY/fail closed;
6. READ with approval_required=true -> REQUIRE_APPROVAL.

## D. GovernanceIntent canonical digest gate

GovernanceIntent V1 must have deterministic canonical bytes and SHA-256 digest.

Golden cases must cover:
- object key reordering;
- nested arguments;
- Unicode;
- arrays;
- safe-range integers;
- rejected non-integer floats;
- proposal id change;
- Run id change;
- principal id change;
- ToolVersion change;
- effect-type change;
- argument change.

Exact replay must produce identical bytes/digest across separate processes.

No secret value may enter the digest input.

## E. PolicyDecision durability gate

Before any physical Tool attempt:

- ToolProposal is durable;
- PolicyDecision is durable;
- intent_digest is durable;
- policy_version_id is durable;
- principal identity is durable in redacted normalized form.

PolicyDecision is immutable after commit.

## F. ALLOW path gate

For policy/capability effective ALLOW:

### READ

Required:
- no ApprovalRequest;
- Tool execution still uses ToolExecutionAttempt;
- Stage 3.2 budget/deadline/cancellation fencing remains active.

### Side effect

Required:
- no ApprovalRequest;
- only eligible no-approval ToolVersion may proceed;
- ActionSnapshot + ExternalAction intent is persisted;
- Stage 3.2 Action Commit still occurs before adapter I/O.

## G. DENY path gate

Policy DENY must produce:

- durable PolicyDecision DENY;
- ToolCall DENIED;
- no ApprovalRequest;
- no ToolExecutionAttempt;
- no ExternalAction physical execution;
- no adapter call;
- no model retry/workaround in V0.1;
- Run terminal fail-closed result.

Cancellation winning the consequence race still outranks DENY terminalization per Stage 3.2.

## H. Approval creation gate

For REQUIRE_APPROVAL, one transaction must durably produce:

- completed ModelInvocation consequence;
- ToolProposal;
- ToolCall AWAITING_APPROVAL;
- PolicyDecision REQUIRE_APPROVAL;
- ApprovalRequest PENDING;
- exact intent_digest;
- Run WAITING_APPROVAL;
- owner_worker_id = NULL;
- lease_expires_at = NULL;
- approval-requested event.

Mandatory zero-I/O assertions:

- ToolExecutionAttempt count unchanged;
- no side-effect adapter call;
- no READ adapter call;
- no Action Commit;
- no fresh model continuation.

## I. WAITING_APPROVAL claimability gate

A WAITING_APPROVAL Run:

- is not selected by normal worker claim;
- remains durable across restart;
- remains nonterminal;
- cannot create a fresh ModelInvocation;
- cannot reconstruct approval by asking the model again.

Approval resolution is the only normal business continuation source.

## J. Approval APPROVE gate

Approving a valid pending request must lock Run first and verify:

- request still PENDING;
- exact intent digest match;
- approver authorization;
- required role;
- separation-of-duties if configured;
- cancel_requested=false;
- Run is WAITING_APPROVAL;
- DB-time deadline still permits continuation.

Successful approval must durably produce:

- ApprovalDecision APPROVE;
- ApprovalRequest APPROVED;
- ToolCall READY;
- Run QUEUED;
- QueueReason APPROVAL_RESOLVED;
- owner/lease cleared;
- approval events.

No adapter call occurs in the approval transaction.

## K. Approval DENY gate

Valid deny must durably produce:

- ApprovalDecision DENY;
- ApprovalRequest DENIED;
- ToolCall DENIED;
- Run FAILED;
- no ToolExecutionAttempt;
- no physical external effect.

Exact replay is idempotent.

Contradictory later APPROVE is rejected.

## L. Duplicate approval race gate

Use real concurrent PostgreSQL transactions.

Two approvers race on one PENDING request.

Required:
- exactly one final ApprovalDecision commits;
- second conflicting decision is rejected;
- no double queue;
- no duplicate physical Tool attempt;
- one durable audit winner.

Approve vs deny must be explicitly tested.

## M. Separation-of-duties gate

When separation_of_duties=true:

- requester cannot approve own request;
- approver without required role cannot approve/deny;
- authorized distinct approver can decide;
- rejected decision attempt does not mutate ApprovalRequest state.

Approver identity must come from trusted PrincipalContext, not request body.

## N. Cancellation vs approval race

Use real concurrent PostgreSQL transactions.

### Cancellation wins

Required:
- cancel_requested=true;
- ApprovalRequest -> CANCELLED;
- ToolCall -> NOT_EXECUTED;
- Run -> CANCELLED;
- later APPROVE rejected;
- zero physical attempts.

### Approval wins

Required:
- ApprovalDecision APPROVE durable;
- Run may become QUEUED(APPROVAL_RESOLVED);
- if cancellation then wins before physical start, Stage 3.2 cancellation fence prevents execution;
- approval is never interpreted as rollback immunity.

Exactly one ordering wins under Run serialization.

## O. Approval expiry gate

Use PostgreSQL server time.

For due PENDING request:

- ApprovalRequest -> EXPIRED;
- ToolCall -> DENIED or frozen final non-executed governance projection;
- Run -> FAILED;
- no physical attempt;
- later decision rejected.

A worker lease is never used as the approval timer.

Restart must preserve expires_at.

## P. Deadline vs approval gate

Approval does not extend Run deadline.

Arrange:
- PENDING approval;
- Run deadline passes;
- authorized APPROVE arrives.

Required:
- operator decision evidence may be persisted if contract permits;
- no APPROVAL_RESOLVED business continuation;
- no physical attempt;
- ToolCall finalizes non-executed;
- Run fails with explicit after-approval deadline reason.

## Q. Destructive Tool gate

DESTRUCTIVE execution must prove all of:

- effective policy was REQUIRE_APPROVAL;
- ApprovalRequest existed;
- final decision was APPROVE;
- intent digest matches approved proposal;
- approved continuation was durably requeued;
- Stage 3.2 ActionSnapshot/ExternalAction intent exists;
- Action Commit transaction committed;
- ToolExecutionAttempt STARTED exists;
- only then did physical adapter I/O occur.

Mandatory negative case:

~~~text
DESTRUCTIVE + no ApprovalDecision
=> external call count = 0
~~~

## R. Approval cannot resolve UNKNOWN gate

Arrange:
- Stage 3.2 ExternalAction UNKNOWN / ToolCall UNRESOLVED.

Attempting to use ApprovalRequest/ApprovalDecision as business-truth resolution must fail.

Only Stage 3.2 reconciliation or ActionResolution may resolve that uncertainty.

## S. Approved side-effect identity gate

After approval, side-effect preparation must preserve approved:

- Run;
- proposal;
- ToolVersion;
- effect type;
- arguments.

Any mismatch between approved intent digest and durable continuation fails closed before
Action Commit.

A new model proposal cannot substitute for the approved one.

## T. Approved continuation recovery gate

Crash after APPROVE commit but before worker claim.

Required:
- Run remains QUEUED(APPROVAL_RESOLVED);
- approved ToolCall remains READY;
- next worker resumes exact durable intent before fresh reasoning;
- no second approval request;
- no model reproposal.

## U. Approved continuation vs cancellation before Action Commit

Arrange:
- APPROVE committed;
- Run claimed;
- side-effect intent not yet across Action Commit;
- cancellation commits.

Required:
- no external call;
- pending READY work stabilizes according to Stage 3.2 cancellation rules;
- approval does not override cancel_requested.

## V. Principal and tenant isolation gate

Policy matching must not authorize across tenant_scope.

Mandatory:
- same role in tenant A cannot decide tenant B approval;
- policy assignment for one tenant does not authorize another tenant;
- audit record shows normalized tenant/principal identity.

## W. Policy pinning gate

A Run must use a deterministic published GovernancePolicyVersion.

Mandatory:
- DRAFT policy cannot authorize;
- published version id is durable with PolicyDecision;
- later policy edits create a new version rather than rewriting historical decision evidence;
- historical decision remains reproducible from pinned version.

V0.1 does not yet require live emergency revocation of already pinned Runs.

## X. Audit and secret-isolation gate

Use sentinels for:
- credential secret;
- bearer token;
- unredacted auth header.

Sentinels must be absent from:
- GovernanceIntent;
- PolicyDecision;
- ApprovalRequest;
- ApprovalDecision evidence unless explicitly redacted safe test value;
- DomainEvent;
- logs captured by acceptance;
- model context;
- ActionSnapshot/checkpoint.

Audit must retain:
- stable ids;
- policy version;
- rule id;
- decision;
- principal/approver ids;
- intent digest;
- timestamps;
- final approval status.

## Y. API authorization gate

Approval decision endpoints must not trust an arbitrary approver id from the request body.

Required:
- PrincipalContext supplied by trusted resolver;
- unauthorized principal -> 403;
- wrong tenant -> 403;
- missing approval -> 404;
- contradictory decision -> 409;
- exact replay -> idempotent success.

## Z. Stage 3.2 -> Stage 3.3 migration gate

Final RC must prove on PostgreSQL 18:

~~~text
accepted Stage 3.2 head
0016_checkpoint_overlay
        ↓
new Alembic process
        ↓
Stage 3.3 head
~~~

Mandatory:
- accepted Stage 3.1 and Stage 3.2 migration hashes unchanged;
- no base-only migration shortcut accepted as sufficient evidence.

## AA. Governance race matrix

At minimum deterministic barriers/tests must cover:

1. policy ALLOW vs cancellation consequence race;
2. policy DENY vs cancellation consequence race;
3. REQUIRE_APPROVAL commit vs worker crash;
4. approval vs cancellation;
5. approval vs expiry;
6. approval vs deadline;
7. approve vs deny;
8. duplicate approve;
9. approved continuation crash before worker claim;
10. cancellation after approval before Tool attempt;
11. cancellation after side-effect intent before Action Commit;
12. cancellation after Action Commit;
13. stale generation attempting approval-related continuation;
14. destructive approval then response-loss UNKNOWN;
15. approval decision replay after Run terminalization.

## AB. Full final gate

Stage 3.3 final acceptance requires the same production envelope:

~~~text
CPython 3.14
PostgreSQL 18
uv --locked
Ruff
Ruff format
mypy strict
Alembic online migration
unit tests
mandatory PostgreSQL integration
governance race tests
Stage 3.2 full regression
~~~

No focused approval test may substitute for the full project gate.

## AC. Immutable RC

Final acceptance belongs to an immutable Stage 3.3 candidate ref.

Required:
- exact branch/ref SHA check;
- accepted Stage 3.2 lineage check;
- forward migration check;
- governance race matrix;
- full final gate;
- rejected RC preserved rather than moved.

Governing acceptance rule:

> Authorization is durable evidence, but physical execution authority still comes from the
> frozen runtime boundary.
