# AgentForge Verified Execution Protocol V1.0

Status: **FROZEN PROCESS CONTRACT**

Effective scope:
- Stage 3.3 and later implementation work;
- any GitHub write performed while developing AgentForge;
- retrospective recovery/audit when a connector response is interrupted or times out.

This protocol exists because a remote GitHub operation has two distinct facts:

1. whether GitHub committed the requested operation;
2. whether the connector successfully returned that result to the conversation.

A connector timeout is therefore never sufficient evidence that the GitHub operation failed.

## 1. Governing rule

> Remote write timeout is UNKNOWN, not FAILED.

The project applies the same safety principle to its own development workflow that
the runtime applies to uncertain external side effects:

```text
write requested
      ↓
connector returns?
  ┌───┴───────────────┐
  │                   │
yes                 timeout/error
  │                   │
  ↓                   ↓
VERIFY             UNKNOWN
                      ↓
                  READ BACK
                      ↓
             ┌────────┴────────┐
             │                 │
        effect exists      effect absent
             │                 │
             ↓                 ↓
          VERIFIED         safe to retry
```

No GitHub write may be blindly replayed after an uncertain connector result.

## 2. Step state machine

Every material GitHub step is tracked with one of these states:

```text
PLANNED
   ↓
EXECUTING
   ↓
┌───────────────┐
│               │
result       timeout/error
│               │
↓               ↓
VERIFYING      UNKNOWN
│               │
└───────┬───────┘
        ↓
   READ-BACK VERIFY
        ↓
┌───────────────┐
│               │
effect exists  effect absent
│               │
↓               ↓
VERIFIED       RETRYABLE
│
↓
ACCEPTED / REJECTED
```

A step is never called VERIFIED merely because the write tool returned success.

## 3. Pre-write chat record

Before every material GitHub write, the conversation must record:

- step identifier;
- intended repository;
- operation type;
- target path/ref;
- purpose;
- expected durable effect;
- current state = PLANNED.

Example:

```text
Step 3.3-B2-04
State: PLANNED

Operation: update_file
Target: src/agentforge/...
Purpose: add ...
Expected effect: one new commit on main
```

This record must appear before the remote write so the user can reconstruct intent even
if the following connector result is interrupted.

## 4. Post-write reconciliation

After every material GitHub write, perform a read-back using the most authoritative
available fact.

### File create/update

Verify:
- branch HEAD;
- target file exists;
- target blob SHA;
- expected semantic token/content;
- expected commit is reachable from the branch.

### Branch/ref creation

Verify:
- exact ref name;
- exact target commit SHA.

### Workflow trigger

Verify:
- workflow run exists;
- run head_sha matches the trigger commit;
- workflow name matches the intended gate;
- final conclusion is read from GitHub, not inferred from the trigger call.

### CI result

Verify:
- run conclusion;
- failed/succeeded job;
- failed/succeeded step;
- accepted implementation commit remains distinct from trigger/CI-only commits.

## 5. Execution receipt

After read-back, emit a conversation receipt:

```text
GitHub Execution Receipt

Step:
Operation:
Target:
Write result:
Read-back evidence:
Commit / blob / ref / Run ID:
State: VERIFIED | REJECTED
```

If the original write returned timeout but read-back proves success, the receipt must say:

```text
Write response: UNKNOWN
GitHub durable state: VERIFIED
Replay performed: NO
```

## 6. No blind retry

A timed-out write may be repeated only after read-back proves the intended durable effect
is absent.

Forbidden:

```text
create/update
   ↓
timeout
   ↓
repeat same write immediately
```

Required:

```text
create/update
   ↓
timeout
   ↓
read branch/file/commit/ref
   ↓
effect already exists?
   ├─ yes -> continue, no replay
   └─ no  -> retry once with current authoritative SHA/ref
```

## 7. One write, one verification boundary

Do not intentionally batch a long chain of unrelated writes without intermediate receipts.

Preferred cadence:

```text
Write #1
  -> Verify #1
  -> Receipt #1

Write #2
  -> Verify #2
  -> Receipt #2
```

A small atomic pair may be grouped only when neither operation is independently meaningful
and the pair is verified together.

## 8. Long-running GitHub Actions

Workflow execution is asynchronous on GitHub even when the conversation is synchronous.

The development protocol therefore distinguishes:

- trigger durability;
- workflow discovery;
- job progression;
- final conclusion.

Polling/query timeout never changes workflow truth.

If a query fails:
1. keep the known Run ID/head SHA if already discovered;
2. re-read that same run;
3. do not retrigger unless GitHub proves the intended run does not exist.

## 9. Diagnostic candidates are first-class history

Rejected candidates must remain visible in the engineering record.

For each rejected run record:
- Run ID;
- head SHA;
- failed job/step;
- root-cause classification;
- whether runtime semantics changed in the fix;
- next accepted run.

A failed candidate never unlocks the next slice.

## 10. Slice acceptance discipline

Every implementation slice follows:

```text
design/contract frozen
        ↓
implementation candidate
        ↓
target gate
        ↓
read-back verification
        ↓
independent acceptance
        ↓
read-back verification
        ↓
freeze record
        ↓
next slice unlocked
```

Aggregate stages additionally require an aggregate acceptance gate.

Release stages additionally require an immutable RC identity.

## 11. Persistent execution logs

For stages with substantial GitHub interaction, maintain a repository-backed execution log
under:

```text
docs/execution/
```

The log should preserve:
- intent;
- chronological writes;
- implementation commit;
- trigger commits;
- workflow Run IDs;
- rejected candidates;
- diagnostics;
- fixes;
- independent acceptance;
- frozen outcome.

Repository execution logs complement, rather than replace, the detailed conversation
receipts.

## 12. Conversation teaching contract

GitHub execution and engineering explanation are separate deliverables.

For material steps explain:
- what changed;
- why that file/surface was changed;
- which invariant it implements;
- what the Gate proves;
- why a rejected candidate failed;
- why the chosen fix is safe.

A successfully completed repository is not sufficient if the user cannot reconstruct how it
was built.

## 13. Recovery after conversation interruption

If the conversation loses an intermediate connector result:

1. do not assume failure;
2. read current branch HEAD;
3. inspect recent commits;
4. inspect target file/ref;
5. inspect workflow runs by head SHA;
6. classify the missing operation as VERIFIED or ABSENT;
7. reconstruct a receipt in the next visible update;
8. continue only from the verified durable state.

This is the development-workflow analogue of AgentForge reconciliation.

## 14. Immutable release-candidate rule

For final release acceptance:

> Acceptance belongs to the exact immutable candidate that passed the gate, not to a later
> mutable branch head.

A rejected RC ref is preserved for audit.

A corrected candidate gets a new immutable RC ref rather than moving the rejected one.

## 15. Protocol state

```text
Verified Execution Protocol V1.0
✅ FROZEN

Stage 3.2-D..G retrospective recovery
🔄 REQUIRED

Stage 3.3
may begin only after the retrospective record is committed and verified.
```
