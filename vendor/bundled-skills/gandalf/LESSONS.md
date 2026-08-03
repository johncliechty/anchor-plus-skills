# Gandalf v1 — LESSONS (anti-drift ledger)

> Wave-7 scaffolding (the committed Gandalf v1 SHIP milestone). The running ledger of what the build
> learned and — load-bearing — the **anti-drift sleep gate** every Gandalf cycle passes through
> before it is allowed to conclude. The North Star is `NORTH-STAR.md` (LOCKED); this file records how
> the implementation is kept from drifting away from it.

## The anti-drift sleep gate (the rule that keeps Gandalf on its North Star)

**Canary set = the test suite.** The deterministic done-floor IS `node --test test/*.test.mjs test/mapreduce/*.test.mjs` (the mapreduce dir holds real --analyze-path canaries; a non-recursive glob silently excluded them until 2026-07-25). There
is no second, hidden gate.

**The sleep gate:** before any Gandalf cycle is considered DONE — before the skill "sleeps" / ships /
hands back — the FULL canary set MUST be GREEN. A RED canary set BLOCKS the cycle from sleeping: a
failing canary is a drift signal (the implementation has moved away from the LOCKED North Star), and
the cycle may not conclude until it is GREEN again or the drift is escalated to a human re-lock.

The canary set the sleep gate runs (the Increment-1 deterministic done-floor):

- **B1** zero ideation (ideation is Jumper's, not Gandalf's) · **B3** premortem ≠ Crucible's
  Oranges-engine (cardinality-1, no regret/counterfactual fields) · **B5** diagnose exclusive to the
  vetted core · **B6** no silent degradation · **B8** honest synthesis (every leg labelled, rung ≤
  envelope) · **B9** anticipate = not-yet-present future-state + enabling assumption · **B-honesty**
  named-defeater + refutation_provenance (or stamped SPECULATIVE) · **B-ceiling** single-family ⇒ max
  tier PROMISING.
- Each canary has a DISCRIMINATING NEGATIVE (a planted violation that MUST fail) — that is how the
  canary proves it tests a real invariant, not a tautology.
- The umbrella `assertIncrement1Conformant` runs the whole set over one output (the integration).

**PRINCIPLE-D (what the sleep gate must NEVER become):** the LLM / cross-family judge and the
elevation oracle are **ADVISORY** — recorded as artifacts a human reads, NEVER part of the sleep
gate. The PRINCIPLE-D meta-isolation test proves this: with the judge endpoint made UNREACHABLE the
gate still exits 0, and the gate's static import closure provably excludes `seam/oracle.mjs`. If a
change ever routes oracle/judge output into the gate, that test fails — the drift is caught.

**WITHOUT-ledger honesty (B2′/B7′):** the anti-laundering content-binding canaries are
BLOCKED-this-cycle and NON-GATING (no Phase-0 ledger yet). The honor-system checklist
(`seam/anti-laundering.mjs`) surfaces that gap rather than hiding it; a forged commission-id rides
free through the gate until the ledger lands (Increment 2). The sleep gate does not pretend
otherwise.

## Lessons

- _(2026-06-22, runtime host — journal/0002)_ **The missing seam-pass wiring is now BUILT (Tier-1).**
  The journal/0001 follow-up — "build a thin Gandalf runtime entry (model raw output → seam stamping →
  conformant output)" — shipped as `runtime/seam-pass.applySeamPass` (the pure composer) +
  `runtime/gandalf-run.mjs` (the real CLI) + `runtime/RAW-DRAFT-CONTRACT.md` (the model now emits ONLY
  the raw draft and does NOT self-assign tiers/stamps — the host applies them). The host REUSES the
  shipped seams and reimplements NO grading logic; a malformed draft fails HONESTLY (`SeamPassInputError`
  → non-zero exit, no forged output). This directly closes the three over-claim failure modes from the
  first real run: the tiers + the "no independent refutation ran" stamp are now applied deterministically
  by `vetElevationRefutation` + `labelTier`, so the output is canary-conformant by construction.
  **SCOPE = Tier-1 deterministic:** ONE model run, NO live independent named-defeater refuters and NO
  researchPrime SITUATE commission (those need the `agent()` seam the gate never runs), so every elevation
  honestly lands at SPECULATIVE + the stamp and `risk_labels` cap at the single-family PROMISING ceiling.
  **The live-refuter PROMISING tier is the SEQUENCED FOLLOW-ON** — it needs the `agent()` seam, consistent
  with the Gandalf program's own dependency sequencing, and is NOT in this effort. Lesson reinforced: a
  skill plan must build the runtime that COMPOSES the model with its seams, not just the seams + canaries.
- _(2026-06-21, Wave 7)_ The integration wave's value was negative-space: proving the eight canaries
  hold TOGETHER on one real v1 output, and proving — structurally, via the import closure — that the
  advisory layer cannot leak into the gate. Asserting isolation is cheap; proving it is the point.
- _(2026-06-21, first real run — journal/0001)_ **The honesty stamps are the SEAM's job, not the
  model's — and the v1 runtime wiring is missing.** Dogfooding v1 on a webhook-idempotency note (3 passes)
  showed the model produces excellent DIAGNOSE/SITUATE/ANTICIPATE content but, run as pure SKILL.md prose
  with no seam pass, keeps hand-approximating tier stamps and failing B-honesty three different ways
  (named-defeater not a structured field → a below-threshold elevation stamped above SPECULATIVE → a
  SPECULATIVE elevation missing the literal "no independent refutation ran" stamp). Root cause: the honest
  tiers + stamps are meant to be APPLIED DETERMINISTICALLY by `seam/score-label.labelTier` +
  `seam/refute.{firesRefuter,composeRefutationProvenance,NO_INDEPENDENT_REFUTATION_STAMP}`, but the build
  shipped seams + canaries + SKILL.md with **no thin runtime entry** chaining model-content → seam-stamping →
  `assertIncrement1Conformant`. The canaries did their job (each caught a real over-claim); the fix is the
  missing seam-pass wiring, NOT more SKILL.md prose. SKILL.md §RUNTIME now documents the intended chain; the
  runtime entry is an open build follow-up. Same class as the SKILL.md-authoring gap → a skill plan must build
  the runtime that composes the model with its seams, not just the seams + canaries (PROGRAM-SEQUENCE lesson).
- _(seed)_ Append one bullet per cycle: what drifted, which canary caught it (or should have), and
  whether the North Star or a constant had to be re-locked by a human.
