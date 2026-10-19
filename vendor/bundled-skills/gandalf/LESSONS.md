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
- _(2026-08-04, SLEEP CYCLE — promoted from journal 0001+0002+0209+0210, four DISTINCT
  pytest-fixture contexts)_ **An empty or bootstrap target is a REAL read with a
  DIFFERENT SUBJECT — never a thin one to pad.** When a deep-read target turns out to be
  an empty scaffold or a pytest fixture, the load-bearing signal is the CONTAINING PATH
  (`test_project_files_traversal_r0`, `test_no_floating_window_markup0`), not any file
  content, and `discovery.json total:0` confirms zero substance. The correct move, taken
  in all four runs, is to NAME the emptiness and re-identify the real subject — the
  feature under test, or the `.anchor` store — and refuse to manufacture project-level
  findings that do not exist. SITUATE correctly does not fire (no central claim / stakes
  below threshold); ANTICIPATE carries the forward value. The transferable defects found
  this way were in the MACHINERY, not the folder: an up-front `status:"running"` index
  pointer with null artifact links and no reconciler (orphan-record lifecycle risk), and
  a tracked `discovery.json` embedding an absolute `root` containing the username while
  its sibling correctly uses `*_rel` fields (portability + privacy on clone). Both are
  exactly what a padded read would have buried.
- _(2026-08-04, SLEEP CYCLE — promoted from journal 0274+0275, the cluster's named fix)_
  **A `main()` guard that compares `resolve(argv[1])` to the module's own path is a
  SILENT NO-OP through a junction.** They are two spellings of one file, never equal, so
  `main()` does not run and the process exits 0 with empty stdout — success and silence,
  the worst pair. Journal 0275 hit this as `node <junction>/runtime/gandalf-run.mjs`
  writing no report. The fix is to realpath BOTH sides. This cycle promoted that fix into
  Ecgberht (`engine/direct-invocation.mjs` + `test/wh2-junction-invocation.test.mjs`),
  where it was live and unnoticed: skills are REGISTERED as junctions, so
  `~/.claude/skills/<skill>/bin/...` — the canonical host path — is precisely the
  spelling that triggers it, and BOTH Ecgberht CLIs were dead that way, one of them
  shipped hours earlier with the defective guard copied in. **Any skill with a
  `bin/`/`runtime/` entry should be checked through its registered junction path, not
  only its real path.**
- _(seed)_ Append one bullet per cycle: what drifted, which canary caught it (or should have), and
  whether the North Star or a constant had to be re-locked by a human.

## Promoted 2026-08-15 (the post-08-04 backlog — journals 0292-0301)

6. **Read `err.message`, not the error prefix.** `gandalf-run.mjs` prints one
   fixed prefix for ANY live-path failure; a refuter-budget HALT was reported
   as "agy down" twice in one day while agy was up throughout (0300 correcting
   0298/0299). Fix the prefix; until then, the message text is the truth.
7. **Derive `--budget` from the firing-elevation count BEFORE launching** —
   R=3 trips on most real artifact reads (5-7 firing elevations is normal);
   the budget HALT is the common case, not the exception (0299, jumper 0024).
8. **A cap must HALT or stamp — never silently drop.** The elevation cap at
   FULL silently discarded the FIRST/highest-value elevation ungraded (0292,
   0295); refuted elevations lose their reasoning entirely (0301). Until the
   engine keeps a `refuted[]` with reasoning, paste refuter verdicts into the
   run notes by hand.
9. **The journal namespace is append-only AND monotone**: next id =
   max(existing NNNN)+1 — 0299 found 190 entries with 32 colliding numbers
   because sessions read the low numbers as the frontier. Machine dumps never
   land in the curated namespace (0285's disarm holds).
