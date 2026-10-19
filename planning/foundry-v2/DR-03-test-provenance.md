# DR-03 — Test/lesson provenance classes + per-class trust ceilings

> Phase-0 §3 decision record (foundry-v2 Wave 1). Machine-readable form:
> `foundry_decisions.TEST_PROVENANCE_CLASSES` (+ `PROMOTION_ACCEPTED_CLASSES`, `TRUST_LADDER`).
> Traces to North Star: **NS#3 (the sleep loop turns over test-gated)**.

## Problem

The sleep gate's documented failure mode is **circular validation**: an agent proposes an
improvement, generates the test that "proves" it, and grades its own work — the gate then
measures agreement, not improvement. Phase 4 leans entirely on this taxonomy to escape that.

## Decision

Trust ladder (closed enum): `REJECTED` < `ADVISORY` < `PROMOTION_GATE`. A test/lesson may
never gate above its class ceiling; **the human remains the promotion authority for every
class** (a `PROMOTION_GATE` ceiling means "may serve as the gate a human approves against",
never auto-promotion).

| Class | Ceiling | Applies to | Escape from circularity |
|---|---|---|---|
| `human_authored` | PROMOTION_GATE | code + prose | a human wrote or line-by-line reviewed it |
| `agent_cross_model_verified` | PROMOTION_GATE | code | independent verification by a DIFFERENT model family, and **held-out** — the test never ran inside the loop that produced the improvement |
| `agent_human_ratified` | PROMOTION_GATE | code + prose | explicit human ratification before first gating use |
| `frozen_benchmark_delta` | PROMOTION_GATE | prose | before/after delta on a benchmark **frozen before the improvement was proposed** — the ONLY accepted gate for prose lessons |
| `agent_unverified` | **REJECTED** | — | none — this IS the circular-validation failure mode, encoded explicitly so rejection is machine-checkable |

**v2 accepts for promotion:** the first four classes. `agent_unverified` gates nothing, ever.

## Why this shape

- The four accepted classes are exactly the Master Plan's Phase-0 §3 taxonomy; the fifth
  (`agent_unverified`, REJECTED) is added so the anti-circular rule is a positive,
  importable constant rather than an implication by omission.
- Prose lessons get no unit test, so they route exclusively through `frozen_benchmark_delta`
  (freeze-before-propose kills the "move the goalposts" variant of circularity).
- Cross-model verification maps onto the platform's standing 5:1 rule (Claude writes,
  Gemini checks) — the verifying family is already wired and cheap.

## Consumed by

Wave 6 (the sleep gate: improvement units carry a provenance class; promotion checks the
ceiling), Wave 14 (the North-Star acceptance proof re-asserts the gate integrity).
