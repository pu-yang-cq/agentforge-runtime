# AgentForge

Production-Grade Agent Runtime & Governance Platform.

## Current release gate

**Stage 3.1 Core Runtime — V1.0 ACCEPTED / FROZEN**

Stage 3.1 passed the independent Python 3.14 + PostgreSQL 18 target acceptance.

**Stage 3.2 Durable Runtime Design — V1.0 ACCEPTED / FROZEN**

The Stage 3.2 design and its acceptance contract have completed:

`Design -> Self Review -> Scenario Validation -> Adversarial Review -> Revision -> Re-review -> Final Review -> Acceptance -> Freeze`

Stage 3.2 runtime implementation is now **UNLOCKED**. Stage 3.2 runtime acceptance
remains locked until the implementation passes the frozen acceptance criteria.

Frozen Stage 3.2 design artifacts:

- `docs/design/stage3.2-durable-runtime-v1.0-frozen.md`
- `docs/acceptance/stage3.2-acceptance-v1.0-frozen.md`
- `docs/acceptance/stage3.2-design-v1.0-accepted.md`
- frozen branch: `stage3.2-design-v1.0-frozen`

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

Stage 3.2 implementation must conform to the frozen Durable Runtime Design V1.0
and Acceptance Criteria V1.0. Any correctness-affecting deviation requires an
explicit design amendment and re-review.

Stage 3.3 Governance remains locked until Stage 3.2 runtime implementation is
accepted.
