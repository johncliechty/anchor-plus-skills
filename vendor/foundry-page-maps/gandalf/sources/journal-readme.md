# Gandalf v1 — journal/

> Wave-7 scaffolding (the committed Gandalf v1 SHIP milestone). This directory is the per-run journal
> for Gandalf advisor cycles. The North Star is `NORTH-STAR.md` (LOCKED); the anti-drift sleep gate is
> documented in `../LESSONS.md`.

## What gets journaled

One entry per Gandalf cycle (a deep-think advisor pass over an artifact/effort), named
`NNNN-<slug>.md`. An entry records:

- **Effort** — what was diagnosed/situated/anticipated (the subject of the pass).
- **Legs run** — diagnose / situate / anticipate, and whether the SITUATE firing gate fired (a
  researchPrime commission) and whether any independent refuter fired (the refuter-firing threshold).
- **Output** — the committed advisor output (schema `gandalf-advisor-1`): findings, elevations
  (with tier + the dual-axis value×groundedness score), risk_labels, and any `degraded:true` the run
  surfaced.
- **Sleep gate** — the result of the anti-drift sleep gate for the cycle: `node --test test/*.test.mjs`
  GREEN (the canary set passed) before the cycle concluded. A RED gate is recorded with the drift it
  caught.
- **Advisory artifacts (PRINCIPLE-D, never gating)** — any elevation-oracle / cross-family judge
  verdict recorded for a human to read; explicitly NOT part of the sleep gate.

## Invariants this journal must not violate

- The journal is a RECORD, never a gate input. The deterministic done-floor is the test suite alone.
- Nothing here lifts the single-family ceiling (PROMISING) or launders a same-family commission into
  independent-origin credit — those honesty invariants live in the seams and their canaries.

---

(no cycle entries yet — seeded at the Gandalf v1 SHIP milestone)
