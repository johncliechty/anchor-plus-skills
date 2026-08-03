# researchPrime Verification+Foresight Upgrade — Implementation Plan v4 (Foreman-ready, post amendment Shark-Tank)

<!-- v4 closes the amendment round: ρ̂ is MONOTONE-TIGHTEN-ONLY (never loosens below the static floor — kills the
censored-bias + feedback loop); I8 ledger-reproducibility; ρ̂ tolerance + N_min pre-registered; cross-repo GREEN
made assertable; Wave-2 canonicity + Wave-7 sole-counter routing named. -->


test-command: node --test test/

> **Stage-2 principle (the lock):** Foreman enforces ONLY `node --test test/` GREEN (orchestrator-run) + reviewer
> prose. Therefore **every acceptance criterion is a concrete `node --test` assertion**, **reserved decisions are
> RED-until-committed tests**, and **every wave lands covered source** (else the vacuous-GREEN guard HALTs it).
> Reserved decisions (North Star, invariants I1–I7, the lineage enum, thresholds G/X%/C_min/N/K/M) are HALTs.
>
> **v6 amendment:** Wave 2 (trio-core + shared independence-accounting module) is now REQUIRED (was contingent),
> and Wave 9 (ρ-calibration ledger) is new. Crucible/Foreman adoption of the shared module is a gated fast-follow,
> NOT in this plan.

Invariants: I1 ρ-honesty · I2 CBS floor · I3 origin integrity · I4 G7 downgrade-only · I5 G2 precision-only ·
I6 no gamed gates · I7 honest convergence. Criteria 1–7 per MASTER-PLAN v6.

---

## Wave 1 — Import GO/NO-GO spike, frozen contract surface, fixture spec, pre-registration RED-gate
- **done-when:** (a) a smoke import of `crucible/bin/{shark-tank,synthesizer,judge,enhanced}.mjs` + `foreman-lib`
  runs from `researchPrime/`, exercised by a contract test against a **real source module `bin/contract.mjs`**;
  (b) the crossed-symbol list is recorded; (c) the fixture spec is authored **incl. a correlated-blind-spot class
  AND a declared-low-but-irreversible case**; (d) `test/preregistration.test.mjs` exists and is **RED until a human
  commits** non-placeholder G/X%/C_min/N/K/M **plus the ρ̂ tolerance T and the calibration N_min** (Wave 9 gates, I6).
- **HALT-for-human:** preregistration RED ⇒ Foreman HALTs; human commits thresholds; resume (I6).

## Wave 2 — Trio-core extraction + shared independence-accounting module (REQUIRED per v6)
Extract the shared core and build the one true origin/quorum counter.
- **done-when:** `crucible-lib` is split into `-core` (HaltError, REVIEW_SCHEMA, stamp) vs `-stages`, with the
  shared specifier resolved via package exports (not `../../`); a **shared `independence-accounting` module** lives
  in the trio-core as the single origin/quorum counter; `test/canonical-copy.test.mjs` resolves each shared
  specifier and asserts **exactly one on-disk path** (crit 6); `test/trio-green.test.mjs` shells out to run
  Crucible's AND Foreman's suites + a Foreman-side smoke import and asserts all GREEN (so the cross-repo claim is an
  orchestrator-runnable assertion, not prose).
- **Scope note:** Wave 2 makes **no behavioral change** to Crucible/Foreman — it re-homes shared modules and
  re-points import specifiers, guarded by both engines' suites staying GREEN. Their *adoption* of the module is the
  gated fast-follow, not this wave.
- **Given** two reviewers of the **same declared lineage** agree, **When** origins are counted by the module,
  **Then** they add **0** independent origins; only an attested distinct lineage adds +1 (I3, generalized) — and
  this holds **regardless of any ρ̂** (the learned quorum changes the COUNT required, never reclassifies a
  same-lineage agreement as an independent origin).

## Wave 3 — Freeze thresholds + capture the single-pass baseline (named + hashed)
- **done-when:** after preregistration is GREEN, the current single-pass Phase-3 runs on the power-calc-sized
  fixture; recall committed as a **named, hashed artifact**; `test/baseline.test.mjs` asserts existence + hash match
  (later waves LOAD it by hash; regeneration ⇒ RED).

## Wave 4 — Phase-1 seam: stakes vector + Oranges foresight
- **done-when:** Phase-1 emits a persisted stakes **vector** → governor tier, and an Oranges receipt; each a test.
- **Given** reversibility="irreversible", **Then** tier ≥ medium (I6); raw vector persisted (no schema break).
- **Given** a fixture with a planted path defect, **Then** foresight drops/reorders that exact branch (equality
  assertion, crit-3 re-aim); a no-op pass is stamped "no foresight value added" and crit-3 reported NOT satisfied.

## Wave 5 — Engine skeleton (reuse, not fork)
- **done-when:** the orchestrator (real `bin/` source) imports the frozen trio surface **and the shared
  independence-accounting module** (Wave 2) for GATE-1; owns the ledger + ladder; runs the loop via the scripted driver.
- **Given** the no-op loop runs, **Then** the contract test asserts it traverses every gate-slot in real call-order.
- **Given** a checkpoint mid-loop, **Then** a spy counter throws if any completed step re-runs (real resume).

## Wave 6 — Evidenced verification core (C-1)
- **done-when:** G1 CoVe independence, G2 self-consistency (precision-only), G7 invariant — each a test; recall
  measured by **loading the Wave-3 baseline by hash**, broken out by source gate AND CBS class; origin counts come
  from the shared module (Wave 2).
- **Given** the audit tries to raise a ladder level without a new pointer, **Then** it throws (I4) in both modes.
- **Given** a G2-only recall gain, **Then** the crit-1 accuracy number does not move (I5 attribution).

## Wave 7 — Round orchestration (C-2)
G3 ≥2-agree heterogeneous reviewers, G4 separate Judge, G5 convergence-until-dry, G6 finding identity, G8
cross-lineage fusion (Enhanced, flagged), G9 conditional debate, active Synthesizer.
- **done-when (each a separate assertion):** (a) dry-round predicate fires; (b) an empty round does NOT increment N
  (I7); (c) a high-stakes run reaching dry in **< K rounds with > M unresolved high-severity findings** fires the
  probe-or-dissent and on single-family substrate emits the "shared-blind-spot un-mitigable" stamp, not a mitigation
  claim (I1); (d) G9 fires exactly once on a conflicting origin pair, zero otherwise; (e) Synthesizer steering
  measured vs a token/round-matched control; (f) Synthesizer/Judge/debate expose a call-count spy seam;
  (g) `test/lineage-enum.test.mjs` is RED until the closed attested-lineage enum is committed (HALT-for-human,
  crit-5); G8 stays inert behind its flag so (a)–(f) reach GREEN meanwhile; (h) G8's origin fusion **routes through
  the Wave-2 shared module** (sole counter) — a test asserts no other code path increments `independent_origins`.

## Wave 8 — Governor wiring + inclusion-test enforcement
- **done-when:** a **low-stakes** run fires **zero** Synthesizer/Judge/debate sub-agents (call-count 0 via the
  spy seam) AND a **high-stakes** run fires call-count **> 0** (positive control); a zero-AXIS-finding round is
  provably skipped/demoted.

## Wave 9 — ρ-calibration ledger + learned quorum (NEW per v6; MONOTONE-SAFE)
Cross-run persistence that estimates reviewer-error correlation and may only TIGHTEN the quorum.
- **done-when (each a real assertion):** (a) a persistent ledger records per-lineage-pair co-miss vs
  independent-catch events across runs (asserted by **two simulated runs** persisting + reloading + appending);
  (b) the estimator **round-trips a seeded ρ within the pre-registered tolerance T** — this is an *arithmetic*
  check and the test comment states it does **NOT** validate ρ̂ against real reviewer correlation (ρ̂ is calibrated
  only against the planted-CBS fixture ground truth, never the live ledger's self-reported catches);
  (c) **MONOTONE-SAFETY (the load-bearing test): no value of ρ̂ ever produces a quorum looser than the static ≥2
  floor** — ρ̂ may only raise the bar; lowering the floor itself requires a human-committed change (I8/crit-7);
  (d) ρ̂ is stamped a **"censored lower-bound"** in the run output (A5);
  (e) **I8 reproducibility:** the run stamps the ledger hash + derived threshold + what the static rule would have
  required, and a replay with the same (inputs + ledger-hash) yields an identical verdict; default mode with the
  ledger disabled is a pure function of inputs.
- **Given** prior data below the pre-registered **N_min** (or none), **When** the loop runs, **Then** it falls back
  to the static ≥2 rule and stamps "ρ unestimated (n<N_min)" (crit 7) — it never fabricates a ρ̂ from too-few samples.
- **Given** a high-stakes run, **When** the ledger is read/written, **Then** the added overhead is ≤ a stated bound
  (Wave 9 is strictly gated behind Waves 6–8 GREEN — the learning layer cannot be built before the floor it learns from).

## Wave 10 — Deliverable integration + honest degraded mode
- **done-when:** deliverables carry round history, Judge verdict, convergence proof, **ρ̂ + the learned-quorum
  state**, and the separate **Synthesizer Brief**; non-engine runs emit the honesty stamp ("schema conforms;
  adversarial verification did NOT run"); `test/output-conformance.test.mjs` passes AND asserts "parity" appears in
  no prose-mode user surface.

## Wave 11 — Verification + dogfood (acceptance gate; every criterion a real assertion)
- **done-when:** `node --test test/` GREEN AND each a discrete assertion reading committed thresholds + the
  baseline-by-hash: recall **closes ≥ G%** (G1-attributed, crit 1); **CBS recall ≥ C_min** (I2; below ⇒ crit-1
  FAIL); low-stakes cost delta **≤ X%** (crit 2); AXIS→tier accuracy incl. irreversible override + under-call guard
  (I6); **one-canonical-copy** of every shared module (crit 6); degraded forces `cross_model:false` (I3);
  **same-lineage agreement adds 0 origins via the shared module, invariant under any ρ̂** (crit 7); **ρ̂ estimator
  round-trip (tol T) + MONOTONE-SAFETY (no ρ̂ loosens below the static floor) + N_min cold-start fallback + I8
  ledger-reproducibility replay** all pass (crit 7/I8); the pre-existing researchPrime rigor suite still passes
  unchanged (crit 4 no-regression); a dogfood self-run proves the dry + suspiciously-dry predicates.
- **Given** any criterion 1–7 fails its assertion, **Then** the project is NOT done and the failing gate is reported
  (no vacuous GREEN; orchestrator-run gate, never sub-agent-pasted).
