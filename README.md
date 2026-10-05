# AgentForge

Production-Grade Agent Runtime & Governance Platform.

## Current release gate

**Stage 3.1 Core Runtime — V1.0 ACCEPTED / FROZEN**

Stage 3.1 passed the independent Python 3.14 + PostgreSQL 18 target acceptance.

**Stage 3.2 Runtime — V1.0 ACCEPTED / FROZEN**

Authoritative immutable runtime release:

- branch: `rc/stage3.2-v1.0-r2`
- SHA: `fa747268cfbf1d5b57e5796b9cbc767abc3d4e0c`
- final gate: `37262139363`
- acceptance: `docs/implementation/stage3.2-g-accepted.md`

Frozen Stage 3.2 design artifacts:

- `docs/design/stage3.2-durable-runtime-v1.0-frozen.md`
- `docs/acceptance/stage3.2-acceptance-v1.0-frozen.md`
- `docs/acceptance/stage3.2-design-v1.0-accepted.md`
- frozen branch: `stage3.2-design-v1.0-frozen`

**Stage 3.3 Governance Design — V1.0 ACCEPTED / FROZEN**

The governance design completed:

`Design V0.1 -> Self Review -> Scenario Validation -> Adversarial Review -> V0.2 -> Re-review -> V0.3 -> Final Review -> V1.0 Freeze`

Frozen Stage 3.3 design artifacts:

- `docs/design/stage3.3-governance-v1.0-frozen.md`
- `docs/acceptance/stage3.3-governance-acceptance-v1.0-frozen.md`
- `docs/acceptance/stage3.3-governance-design-v1.0-accepted.md`
- frozen branch: `stage3.3-governance-design-v1.0-frozen`

Stage 3.3 implementation is now **UNLOCKED**.
Stage 3.3 runtime acceptance remains **LOCKED** until implementation passes the frozen
Governance Acceptance Criteria V1.0.

Stage 3.1 accepted immutable source:

- Release candidate: `V1.0-RC4`
- RC4 SHA-256:
  `696a889a86fc35ea127f6fde803818269427df978d2268345ea614af56d847b7`
- Reviewed `uv.lock` SHA-256:
  `ea589824df68c1412a9ba797f673cf4110e122540a06e02ffcf15bb3e4fa406a`
- Official acceptance run: `37185024586`
- Accepted envelope commit:
  `7a03504daa3a1e2d66d96b5f3c59ed15b7965c41`
- frozen branch: `stage3.1-v1.0-frozen`

## Freeze rules

Stage 3.1 behavior remains frozen.

Stage 3.2 runtime behavior remains frozen at the accepted immutable RC.

Stage 3.3 implementation must conform to the frozen Governance Design V1.0 and Governance
Acceptance Criteria V1.0. Any correctness-affecting deviation requires an explicit design
amendment and re-review.

Later stages remain locked until Stage 3.3 runtime implementation is accepted.
