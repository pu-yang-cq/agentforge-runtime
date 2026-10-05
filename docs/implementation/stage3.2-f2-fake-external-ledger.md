# Stage 3.2-F2 — Stateful Fake External Ledger + Crash Barriers — ACCEPTED / FROZEN

Status: **ACCEPTED / FROZEN**

Parent frozen surfaces:
- Stage 3.2-E aggregate
- Stage 3.2-F1 Checkpoint V1 Overlay Authority
- `docs/implementation/stage3.2-f-slices-frozen.md`

Implementation commit:
- `87691c7bf2d369059c18516c4cc8a2ff1fcc6c2e`

Target implementation gate:
- workflow: **Stage 3.2-F2 Fake External Ledger**
- successful run: `37259060659`

Independent acceptance:
- workflow: **Stage 3.2-F2 Acceptance**
- successful run: `37259235589`

Rejected pre-acceptance candidates:
- `37258877242`: test-support import-path failure;
- `37258948052`: same unstable tests-package import surface;
- `37259024550`: stale verification path after moving support into typed namespace;
- `37259206699`: independent acceptance invoked source package without PYTHONPATH.

All rejected candidates were environment/test-harness defects. No failed candidate
was accepted or used to unlock F3.

## Accepted F2 test system

Test-only module:
- `src/agentforge/testing/fake_external_system.py`

Production runtime imports from `agentforge.testing` are explicitly rejected by
independent acceptance.

### Observable external ledger

Each durable operation identity can be observed through:
- operation_id;
- external_resource_id;
- call_count;
- effect_count;
- duplicate_request_count;
- reconciliation_query_count.

This separates physical request count from actual external business-effect count.

### Side-effect scenarios

The deterministic fake supports:
- normal success;
- definite pre-effect failure;
- ambiguous timeout;
- effect commit + response loss;
- delayed success.

### Idempotency behavior

For repeated physical requests with the same operation_id:
- independent idempotency guarantee: duplicate request is observable but
  effect_count remains one;
- non-idempotent behavior: duplicate request increments effect_count and is
  therefore detectable as a safety violation by F3.

### Reconciliation behavior

Reconciliation:
- is read-only with respect to business effects;
- increments reconciliation_query_count;
- can return scripted authoritative/best-effort business outcomes;
- otherwise derives deterministic evidence from the ledger.

### Controlled crash barriers

F2 declares all 12 frozen Stage 3.2 crash windows:

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

Armed barriers:
- expose a deterministic hit signal;
- block until released by the test driver;
- make crash/race placement reproducible instead of timing-based.

### Secret boundary

The fake ledger does not retain:
- credential_ref;
- resolved credential material;
- secret values.

It stores only redacted external evidence necessary for safety assertions.

## Frozen F2 invariants

### F2-I1 — Test infrastructure only

The fake external provider is acceptance infrastructure and is not production
provider logic.

### F2-I2 — Operation identity is observable

Every fake external request is keyed by stable operation_id.

### F2-I3 — Request count != effect count

Tests can distinguish:
- duplicate transport/request delivery;
- duplicate business effect.

This is required to prove no blind duplicate non-idempotent effect.

### F2-I4 — Commit+response-loss is representable

The fake can durably expose an external effect while withholding/losing the
adapter response.

This is the central UNKNOWN/reconciliation crash scenario.

### F2-I5 — Reconciliation is measurable and read-only

Safety queries are counted separately and never create a business effect.

### F2-I6 — Crash barriers are deterministic

F3 must consume these barriers rather than relying on sleep/timing races.

### F2-I7 — No secret persistence

Provider credentials remain adapter-edge inputs and never enter fake durable
evidence.

## State

```text
Stage 3.2-F1
Checkpoint V1 Overlay Authority
✅ ACCEPTED / FROZEN

Stage 3.2-F2
Stateful Fake External Ledger + Crash Barriers
✅ ACCEPTED / FROZEN

Stage 3.2-F3
Full Recovery / Crash Matrix + F Aggregate
🔓 UNLOCKED

Stage 3.2-G
Immutable RC + Final Acceptance
🔒
```

Governing rule:

> Crash testing must measure external effects, not merely process exceptions.
