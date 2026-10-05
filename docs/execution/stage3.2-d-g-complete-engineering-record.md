# Stage 3.2-D..G Complete Engineering Execution Record

Status: **RETROSPECTIVELY RECOVERED / VERIFIED**

Protocol:
- `docs/execution/verified-execution-protocol-v1.0.md`

Purpose:
- reconstruct the GitHub execution history that was partially hidden in the chat by
  connector interruptions/timeouts;
- separate durable GitHub facts from connector-return visibility;
- preserve rejected candidates and diagnostic work, not only accepted endpoints;
- provide a teaching/audit record before Stage 3.3 begins.

## 1. Evidence model

This record was reconstructed from authoritative GitHub state:

- commit history on `main`;
- accepted/frozen implementation records;
- workflow Run IDs and conclusions;
- failed job/step names;
- immutable RC refs and exact SHAs.

Important limitation:

A missing connector response in the original conversation cannot be used to prove the
remote write failed. This record therefore treats GitHub durable state as authoritative.

## 2. Stage 3.2-D — uncertainty, safe retry, reconciliation

### D planning boundary

Execution-plan freeze:

- commit `3c68ffdcc16b8004a28157a904134b5b312329f4`
- document `docs/implementation/stage3.2-d-slices-frozen.md`

Frozen slices:

```text
D1 UNKNOWN result boundary
D2 safe side-effect retry + orphan recovery
D3 durable reconciliation
```

### D1 — UNKNOWN result boundary

Chronology:

| Step | Durable evidence | Result |
| --- | --- | --- |
| stage patcher | `86a32a61ad840fc8a7c5e91c91798948d381e90f` | staged |
| add target gate | `6bed4b5324fb7e54fdea1a088730b2e9cbcca888` | staged |
| trigger target | `5e3a15b58b28bb51acb5f3155b0374d2920950e1` | run created |
| target run | `37207443075` | **SUCCESS** |
| accepted implementation | `d29397071913dcff4aa7d3c1ae822bb33321f405` | accepted candidate |
| add independent acceptance | `eacaefd384e42218895192c1a11e2fb7536bb9f1` | staged |
| trigger acceptance | `c578e8711d22b71ac87f4b008b1266d488487f6d` | run created |
| independent run | `37207570248` | **SUCCESS** |
| freeze | `1ac48873059ad1bbb646a2c2d88910dd4376a7f3` | **FROZEN** |

What D1 proved:

- possible execution -> ToolExecutionAttempt UNKNOWN;
- ExternalAction -> UNKNOWN;
- ToolCall -> UNRESOLVED;
- active current_attempt_id cleared;
- generic post-commit exceptions cannot become implicit retry;
- durable UNKNOWN blocks fresh model reasoning.

### D2 — safe retry + orphan takeover

Chronology:

| Step | Durable evidence | Result |
| --- | --- | --- |
| stage patcher | `0045c79d11f1910e0a3c9f9b3c7afe943dc47ef4` | staged |
| add target gate | `3e5243cbde156a41d6cee26964da2ab464453027` | staged |
| trigger target | `16410e459be7f913bd1ea6a4fed38df778f8248d` | run created |
| target run | `37208021132` | **SUCCESS** |
| accepted implementation | `237f5b39bef108954f2aff3d0733f117dd5a216a` | accepted candidate |
| add independent acceptance | `5f712395224a22716f18eb53ae3d865c5ecaaad8` | staged |
| trigger acceptance | `950d5e860a98c96ed235b83838c15706290ee16c` | run created |
| independent run | `37208147987` | **SUCCESS** |
| freeze | `99e4ceb0af7f9f50be5be7ec3331637ff3ae02b6` | **FROZEN** |

What D2 proved:

- retry requires explicit proven non-execution;
- retry preserves ExternalAction, ActionSnapshot and operation_id;
- retry creates only a new physical attempt;
- lease loss after Action Commit is UNKNOWN, never proof of non-execution;
- orphan takeover closes the old STARTED attempt before any replacement work.

### D3 — durable reconciliation

D3 generated the largest diagnostic chain in Stage D. The conversation sometimes appeared
to jump because many GitHub actions completed even when individual connector returns were
not visible.

Initial construction:

| Step | Commit |
| --- | --- |
| stage reconciliation patcher | `f95282a7e577c8fe15b5a24bef66dc6416158159` |
| deterministic tool-patch anchor fix | `02ecccbaa359090bc82bdb863218c3dc35924e3d` |
| harden reconciliation patch | `50f115d2e77ff82d59e43b1dfdf3724ca10bc48f` |
| add target gate | `0a9a1c991ad0b88658bd1bd6cd4d653097adafe1` |
| first trigger | `49ce24fb1b7e155b3f43f03f5c114d21cd9d431a` |

Target/diagnostic sequence:

| Run | Conclusion | Failed/diagnostic surface |
| --- | --- | --- |
| `37209550503` | FAILURE | target gate |
| `37209730919` | SUCCESS | debug materialization |
| `37209788312` | SUCCESS | static diagnostics |
| `37209916833` | SUCCESS | runtime diagnostics |
| `37209986174` | SUCCESS | debug materialization |
| `37210058079` | FAILURE | target gate |
| `37210140878` | SUCCESS | read-only diagnostics |
| `37210212092` | SUCCESS | exact-gate diagnostics |
| `37210345803` | FAILURE | canonical formatting |
| `37210385963` | SUCCESS | debug materialization |
| `37210431180` | SUCCESS | exact-gate diagnostics |
| `37210498818` | FAILURE | debug candidate materialization |
| `37210588310` | FAILURE | canonical formatting |
| `37210699199` | SUCCESS | canonical diagnostics |
| `37210763847` | SUCCESS | canonical diagnostics after E501 fixes |
| `37210803479` | FAILURE | target gate |
| `37210942954` | SUCCESS | final-gate diagnostics |
| `37211038696` | SUCCESS | final-gate diagnostics after mypy fix |
| `37211132877` | **SUCCESS** | official D3 target gate |

Notable corrective commits during the chain included:

- `bb0176515678c1e9fe9fee0be11a2c64e59d07da` — wrap remaining reconciliation test lines;
- `84db64c8a28ebb90733cff9433098c1fc858920a` — remove invalid status narrowing in reconciliation failure handling.

Accepted D3 implementation:

- commit `9e8fb391bace884775a34f53015c220d2fecc2af`

Independent acceptance:

- gate definition `aef44ff8aeaa023b5080b94ce151b4bd6af7ddfb`
- trigger `76442ec2db36ab3f5798c640e335acaf3b52568a`
- run `37211514523` — **SUCCESS**
- freeze `f418ad14bceb1d4f726d49d0ad66c897041d5199`

What D3 proved:

- ReconciliationAttempt STARTED is committed before physical read-only query;
- reconciliation transport failure does not decide business truth;
- reconciliation has independent bounded safety policy;
- AUTHORITATIVE / BEST_EFFORT / NONE semantics are distinct;
- BEST_EFFORT non-idempotent NOT_EXECUTED cannot authorize blind retry;
- orphaned reconciliation attempts close FAILED/LEASE_LOST and preserve unresolved truth.

### D aggregate

First aggregate candidate:

- gate definition `023467122bab67f1601b3f42ce31d8166fcc3235`
- trigger `bbd8093bde7377d0fa134e1b4d930eb9e85b3a76`
- run `37211677419` — **FAILURE**

Root cause:

- acceptance proof searched too broad a source slice and falsely concluded action identity
  could be recreated;
- runtime semantics were not the defect.

Fix:

- `d6951017aeb2a3081ad62ece5f1a2ff22445720e` — scope aggregate identity proof correctly.

Rerun:

- trigger `b6b304c6ac97ffbc151502e49da9442c1a1da31e`
- run `37211751509` — **SUCCESS**
- freeze `40cfa74e9fa1d7f94d8631609c2cd52c29884070`

Final state:

```text
Stage 3.2-D
✅ ACCEPTED / FROZEN
```

## 3. Stage 3.2-E — cancellation, manual resolution, late-result authority

### E1 — durable cancellation intent

Primary implementation:

- `db27b22030b8e68505cf6a580c800e6ecc2b1fc8`

Initial target history:

| Run | Result | Failed surface |
| --- | --- | --- |
| `37212363185` | FAILURE | apply E1 implementation |
| `37212484527` | FAILURE | target gate |
| `37212659816` | **SUCCESS** | accepted E1 target |

The target success followed the lock/serialization corrections recorded before the primary
implementation was accepted.

Independent-review cycle exposed two real semantic gaps.

#### Review gap 1 — denied model consequence after cancellation

Initial acceptance:

- `37212823417` — FAILURE
- review fix commit `285b41177ce293277d364770e4730a85816b611c`
- review-fix gate `37212896765` — SUCCESS

The fix established that cancellation also dominates the permission-denied model-consequence
path.

#### Review gap 2 — in-flight result fences

Acceptance still rejected incomplete fencing:

- `37212991285` — FAILURE

A dedicated result-fence series followed:

| Run | Result | Surface |
| --- | --- | --- |
| `37213351451` | FAILURE | apply result-fence fix |
| `37213412150` | FAILURE | format candidate |
| `37213524803` | FAILURE | full E1 regression |
| `37213603415` | **SUCCESS** | result-fence regression gate |

Final semantic fix:

- `c5aa53c95cb9d926a735d3a731c320c4da85a43a` — fence in-flight model/tool/side-effect/reconciliation results after cancellation.

Independent acceptance then found a proof-script scope error:

- `37214284520` — FAILURE
- failure: acceptance proof matched ExecutionJournal method definitions instead of the
  intended RunManager.execute consequence calls.

The proof was scoped correctly without runtime semantic change.

Final independent acceptance:

- `37214422018` — **SUCCESS**
- freeze `d1a0b014d0241f110fc98e762c056aa7bec6c08b`

What E1 proved:

- cancellation is durable orthogonal intent;
- cancellation is not rollback;
- Run row serializes cancellation and consequence persistence;
- pre-effect READY work may be stabilized NOT_EXECUTED/ABORTED;
- unresolved safety reconciliation can continue;
- late in-flight evidence cannot regain business progression authority.

### E2 — ActionResolution

Construction:

- stage patcher `f93e868454040814793b40a41a86929f9e465ee5`
- target gate `21e08f13e869d713622274a929d4989bccb07ea6`
- first trigger `a9766ad682bd613f7e2d8d0c1a51f36094f18520`

First target:

- `37214920965` — FAILURE at full target gate.

Diagnostics:

- workflow commit `25ff59146a1d64371785cc146f34eddc99f571dd`
- diagnostic trigger `04f7995e8514595e907b44a7a73acacd1b568f6e`
- run `37215020972` — FAILURE specifically at Ruff gate.

No runtime semantic redesign was required.

Canonicalization rerun:

- trigger `5c5d5050143a445b6f515ef649e318d992c92450`
- target run `37215071242` — **SUCCESS**

Accepted implementation:

- `3d366f297e6a19973ffc03f36356fb87b943ffe8`

Independent acceptance:

- gate `2290c85a27d08cb021cc1076083180db0c8aa9d0`
- trigger `b6c8591cf6037aa250aa368990f160c477113e1e`
- run `37215212570` — **SUCCESS**
- freeze `3657a0c4400f45b8c3cb8ff9f254d98c1b519fae`

What E2 proved:

- one final ActionResolution per action;
- exact replay idempotent, contradiction rejected;
- MANUAL_REVIEW-only eligibility;
- Run -> ExternalAction -> ToolCall lock order;
- manual SUCCEEDED can queue ACTION_RESOLVED only when non-cancelled and before deadline;
- manual resolution never reopens CANCELLED.

### E3 — late-result authority

Construction:

- patcher `315d235e673b1f39862e70d0f64ec24b64b2838b`
- target gate `a2460cea62860d00a902f22fcaeafa05ce87b77a`
- first trigger `52dd5289039eb65d0c2c054936d7d578d38e76ba`

Rejected candidates:

| Run | Result | Failed surface |
| --- | --- | --- |
| `37256023484` | FAILURE | apply patch / anchor |
| `37256112573` | FAILURE | target regression |
| `37256235138` | FAILURE | target regression; diagnostics isolated Ruff-only defects |

Corrective commits:

- `b37c78ccab97fa09316d569cdd31685cc8f4a3f4` — scope side-effect result patch anchor;
- `d33469adfd7b59e0f55e5ca385005b41557d61ed` — satisfy lint gate;
- `5c36c80e694294fad46ee4960971fa6af785b288` — align E3 assertion name.

Accepted target:

- trigger `29bde5126a746837a1eb406103a4f3461adc2158`
- run `37256391604` — **SUCCESS**
- implementation `f1e5cd9d80497bd39953a7d21704a563e6bf8d85`

Independent acceptance:

- workflow `d5e29a8f72397a59d39db6ca0038d8d69d51b57f`
- trigger `862f2f151f568e810d2afdb0edc9bee94b9d0245`
- run `37256507004` — **SUCCESS**
- freeze `ae0dc56983f24d10add619a54f6ff54b47b32066`

What E3 proved:

- result-before-cancel keeps external truth;
- cancel-before-result may still record evidence but fences stale progression;
- reconciliation cannot reopen cancellation;
- committed manual resolution cannot be overwritten by late autonomous evidence;
- stale generations cannot resurrect authority.

### E aggregate

- gate `0576abdbe378b70eaeebc0e3a8284ebeccf0ff84`
- trigger `c6c2977525fceb7874d7332efd4b0485b5d5d97b`
- run `37256683913` — **SUCCESS**
- freeze `a0f40d5934ca6d7ffc1aae0e4b384fe15dc881f3`

Final state:

```text
Stage 3.2-E
✅ ACCEPTED / FROZEN
```

## 4. Stage 3.2-F — checkpoint authority and crash recovery evidence

Execution-plan freeze:

- `486c035542733265233411baf61b38043f545309`

### F1 — Checkpoint V1 overlay

Construction:

- patcher `800f32fd63b3cef0606282287d1490e52ff720be`
- target gate `bb8ade0686f2f5c1865f72fdbb3e3b13d252c3df`
- first trigger `13d4bf5281f980d3c21ab4f471c36771b437ea80`

Rejected runs:

- `37257111325` — target gate failure;
- `37257164716` — diagnostic rerun identified import-order-only Ruff failure.

Fix:

- `48d648b6b939e57d10dd548970272d05480ecc75` — order checkpoint model import.

Accepted target:

- trigger `bb6b3c58c863ca75c9b4c8a8494c64e40c64ed3f`
- run `37257254728` — **SUCCESS**
- implementation `2cd8de79fd3f2e81278ea18a9d1fe46bc48d057a`

Independent acceptance:

- workflow `a0c45768254bbe33d018b9cd71828623b70874f2`
- trigger `14de5c05f06297826a8324ad65bca203b61c260b`
- run `37257397286` — **SUCCESS**
- freeze `280447e0cc3a32bbba1339ba6a75acca396bc08f`

What F1 proved:

```text
durable business facts
    >
checkpoint
    >
new model reasoning
```

Checkpoint is disposable private state, never business authority.

### F2 — stateful fake external ledger

Construction:

- patcher `663244353e96de43cbc311ea928cab5f48475ada`
- gate `a19d973aea29fd2a42abaf66def603d07f28cf60`
- first trigger `0e3882d64b068f12c62892a292b70f794bd18688`

Rejected target candidates:

| Run | Failed surface | Diagnosis |
| --- | --- | --- |
| `37258877242` | focused fake-provider tests | test-support import path |
| `37258948052` | focused fake-provider tests | unstable tests-package import surface |
| `37259024550` | observability-surface verification | stale path after typed namespace move |

Accepted target:

- implementation `87691c7bf2d369059c18516c4cc8a2ff1fcc6c2e`
- trigger `05b1bca5cf029fadd96c0b081603b7896ee7c8a6`
- run `37259060659` — **SUCCESS**

Independent acceptance first candidate:

- trigger `2c6c0bb3e486547108cb6a63ef0ee49d1f5a5a02`
- run `37259206699` — FAILURE;
- cause: acceptance source-package invocation lacked correct PYTHONPATH.

Fix:

- `dccee60c4d6db96e3a262c228a68c676e2a46f16` — load source package correctly.

Accepted independent run:

- trigger `17955c4b6546def0a429757a2ac72ad3008ffb71`
- run `37259235589` — **SUCCESS**
- freeze `9268709d950c1cc326d13a718bb1f8b84882dedb`

What F2 added:

- observable operation_id;
- request call_count;
- actual business effect_count;
- duplicate_request_count;
- reconciliation_query_count;
- deterministic barriers at all 12 frozen crash windows.

### F3 — full recovery/crash matrix

Construction:

- patcher `10250bc63e87023ec7fc45ae6573db919c475c07`
- gate `0f4efc2ffefc06f976bd0703edcb63c547a22d4d`
- trigger `25abbfae8bf60a0edb53753cbe946141c1c1c1ad`

Rejected candidate 1:

- run `37259687487` — FAILURE at matrix contract tests;
- cause: contract inspected only thin wrapper test bodies and missed shared
  effect-count assertions.

Fix:

- `4b9361d8fb0563a1643584301d842f41ade0d760` — validate effect invariants in
  shared crash helpers.

Rejected candidate 2:

- trigger `17b51fa6687128bf730013fba58afc7727d42aa9`
- run `37259787966` — FAILURE at full regression;
- the 12-window PostgreSQL crash matrix itself passed;
- quality gate rejected one overlong test function declaration.

Fix:

- `94670ae493fb95b2f70c9036798f990cec621e70` — shorten F3 crash test name.

Accepted target:

- trigger `e93f993aa6e3cc2be6fb8a74ce769d1c1f099567`
- run `37259885423` — **SUCCESS**
- implementation `9b92830d907379dc132fd433b42e74591adfc392`

Independent F aggregate:

- workflow `34356a099602cf73e3b5c4b44d04a58907a2bc70`
- trigger `bc5b8a35f74a91440cf035472ceccc5bcc8e7afb`
- run `37260097961` — **SUCCESS**
- freeze `3286e348166bc4e704121e5057444767a9cab8ac`

The accepted matrix covers:

1. before Action preparation commit;
2. after READY commit;
3. before Action Commit;
4. after Action Commit before external call;
5. during external call;
6. after external effect commit before response;
7. after response before DB result commit;
8. during result commit;
9. during reconciliation request;
10. after reconciliation response before result commit;
11. during durable retry/yield transaction;
12. during cancellation/model-result race.

Final state:

```text
Stage 3.2-F
✅ ACCEPTED / FROZEN
```

## 5. Stage 3.2-G — immutable release candidate and final gate

### RC1 construction

Manifest:

- `4b0cf99179c188828f7f544504ead588ea57d0ce`

Gate:

- `12bf05e8146803795138f33738e78d327d194850`

Immutable branch:

```text
rc/stage3.2-v1.0
3286e348166bc4e704121e5057444767a9cab8ac
```

Trigger:

- `90964bcedb95ad9b6ca27dd7424b25daa760282b`

Run:

- `37260449370` — **FAILURE**

Exact failed step:

```text
Prove forward migration from frozen Stage 3.1 head to Stage 3.2 head
```

The later crash-matrix and full-project steps were correctly skipped.

### RC1 root cause

Stage 3.2 migration `0009_external_action_intent.py` expanded an already committed
PostgreSQL enum:

- WRITE;
- EXTERNAL_SIDE_EFFECT;
- DESTRUCTIVE.

When resuming from the frozen Stage 3.1 database in a new Alembic process, PostgreSQL
requires newly added enum values to commit before later DDL uses them.

The ordinary empty-database base->head path did not expose this production-upgrade
boundary.

### RC2 correction

A temporary obsolete D3 patch scaffold created during retrospective state confusion was
removed before release work:

- obsolete scaffold commit `012465fac776e879ee6201848fdefbc2dbf33093`;
- cleanup `8d09a0ad398d1bc7347852e169aa3203887f3e70`.

The actual RC correction changed only the Stage 3.2 migration:

- fix commit `fa747268cfbf1d5b57e5796b9cbc767abc3d4e0c`;
- `0009_external_action_intent.py` enum expansion placed in Alembic
  `autocommit_block()`;
- Stage 3.1 migrations `0001..0005` remained unchanged.

New immutable branch:

```text
rc/stage3.2-v1.0-r2
fa747268cfbf1d5b57e5796b9cbc767abc3d4e0c
```

Gate pinned to RC2:

- `47cf0bd621b1d6398427b288f33e16ff5413449e`

Trigger:

- `c843501f3fb51e175c6c13367879d8b668804ee2`

Final run:

- `37262139363` — **SUCCESS**

Step-by-step result:

```text
exact RC identity/ref             ✅
toolchain + Stage 3.1 lineage     ✅
0005 -> 0016 resumed migration    ✅
12-window crash matrix            ✅
Python 3.14 + PostgreSQL 18 gate  ✅
```

Final freeze:

- `109cb260ce39dccbe0be3bf59070b81edb2ece60`
- document `docs/implementation/stage3.2-g-accepted.md`

Authoritative Stage 3.2 release identity:

```text
branch: rc/stage3.2-v1.0-r2
sha:    fa747268cfbf1d5b57e5796b9cbc767abc3d4e0c
gate:   37262139363
```

Final state:

```text
Stage 3.2 Runtime V1.0
✅ ACCEPTED / FROZEN
```

## 6. What the interrupted chat had hidden

The original conversation could make several periods look like:

```text
tool call
   ↓
timeout / missing visible return
   ↓
later assistant message suddenly sees a commit/run already completed
```

GitHub durable history proves that many of those operations had in fact completed.

The missing item was the **conversation receipt**, not necessarily the GitHub operation.

The highest-density examples were:

- D3's repeated diagnostic/materialization loop;
- E1's review-fix and in-flight result-fence loop;
- F2's import-path/test-harness repair loop;
- G RC1 failure -> migration diagnosis -> immutable RC2 acceptance.

From Stage 3.3 onward, the Verified Execution Protocol requires a visible pre-write record
and post-write read-back receipt so this distinction is explicit in real time.

## 7. Recovered stage summary

| Stage | Accepted implementation / freeze evidence | Final acceptance |
| --- | --- | --- |
| D1 | `d2939707...` / `1ac48873...` | `37207570248` |
| D2 | `237f5b39...` / `99e4ceb0...` | `37208147987` |
| D3 | `9e8fb391...` / `f418ad14...` | `37211514523` |
| D aggregate | `40cfa74e...` | `37211751509` |
| E1 | `db27b220...` + review fences / `d1a0b014...` | `37214422018` |
| E2 | `3d366f29...` / `3657a0c4...` | `37215212570` |
| E3 | `f1e5cd9d...` / `ae0dc569...` | `37256507004` |
| E aggregate | `a0f40d59...` | `37256683913` |
| F1 | `2cd8de79...` / `280447e0...` | `37257397286` |
| F2 | `87691c7b...` / `9268709d...` | `37259235589` |
| F3/F aggregate | `9b92830d...` / `3286e348...` | `37260097961` |
| G RC2 | `fa747268...` / `109cb260...` | `37262139363` |

## 8. Audit conclusion

The retrospective audit found no missing accepted runtime slice in D through G.

The issue was primarily **observability in the conversation**, not loss of GitHub durable
operations.

Recovered facts show that:

- rejected candidates stayed rejected;
- later stages were unlocked only after accepted gates;
- D, E and F each received aggregate acceptance;
- RC1 remained rejected and immutable;
- RC2 received a new immutable ref;
- Stage 3.2 Runtime V1.0 acceptance belongs to exact RC2 SHA
  `fa747268cfbf1d5b57e5796b9cbc767abc3d4e0c`.

## 9. Gate before Stage 3.3

Stage 3.3 may proceed only after:

- this recovered execution record is committed;
- it is read back from GitHub;
- main HEAD contains it;
- the Verified Execution Protocol remains present.

After those checks, the retrospective recovery task is accepted and Stage 3.3 can resume
under the new process contract.
