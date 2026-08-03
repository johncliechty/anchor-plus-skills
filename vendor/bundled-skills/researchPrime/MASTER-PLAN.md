# researchPrime Verification+Foresight Upgrade — Master Plan v5 (Crucible Stage 1, post Shark-Tank round 3)

> **Changelog:** v2 closed round-1's 5 structural BLOCKERs. v3 elevated the Synthesizer. v4 closed round-2's
> reviewer-error-correlation (ρ) finding. **v5 closes round-3: gates the correlated-blind-spot recall (no longer
> theater), makes ρ-mitigation honestly Enhanced-only (default mode DETECTS, doesn't pretend to close),
> re-bases Δ as gap-closure, makes the independence basis an attested enum — and DE-SPECIFIES (lifts Stage-2
> mechanism out, keeping invariants as the lock) to fix the altitude breach the Analyst flagged.**
>
> **Altitude note:** anything below written as a concrete key/predicate/number is **illustrative — Stage 2
> finalizes the encoding.** What Stage 1 LOCKS is the *invariant* each one serves (collected under "Locked
> invariants"). Stage 2 is free to choose a better encoding that preserves the invariant.

## Locked North Star
Make researchPrime's conclusions measurably more **trustworthy** AND its research path better-**aimed**, via an
**engine-backed, stakes-scaled** verification + foresight loop built on the evidenced levers — **independence
(CoVe), multiplicity (self-consistency), a separate context-free Judge, heterogeneous ≥2-agree reviewers, and
convergence-until-dry** — that **reuses the trio's machinery**, with a **persistent, ACTIVE Deep-Think
Synthesizer** (medium+; steers, argues theory, files a separate brief) and **conditional** debate, plus
**Oranges foresight in Phase-1**. All **scaled by the declared AXIS stakes**, and **ρ-HONEST in both modes**:
by default it reports correlated-blind-spot recall separately and caps same-family agreement; in Enhanced mode
it fuses genuinely cross-lineage review into GATE-1's independent-origins count. Keep **every existing rigor**.
*No element survives that doesn't serve the AXIS; no agreement is counted as corroboration beyond what reviewer
independence supports; the default mode never claims a mitigation it doesn't possess.*

**North-Star amendment (v6, user authority 2026-06-06):** scope now INCLUDES (a) a **trio-level
independence-accounting module** — a single shared component (in the trio-core) that tracks reviewer lineage and
refuses to count same-lineage agreements as independent origins, generalizing I3; researchPrime wires it now,
Crucible/Foreman adoption is a **gated fast-follow** (no forced rewrite of two GREEN engines); and (b) a
**ρ-calibration ledger** — cross-run persistence that empirically estimates reviewer-error correlation ρ̂ and turns
the ≥2-agree quorum into a **learned, stakes-scaled threshold** (cold-start falls back to the static rule, stamped).
This lifts the A5 deferral: ρ moves from "nonzero/unmeasured" to "estimated over runs."

### Six criteria (with which mode exercises each)
1. **Trustworthiness ↑ (measured, correlation-gated) — both modes.** On a planted-defect fixture that **must
   include a correlated-blind-spot (CBS) class**, loop recall **closes ≥ G% of the single-pass baseline's miss
   rate** (G pre-registered; Δ expressed as gap-closure, not an absolute) — **AND CBS recall ≥ a pre-registered
   floor `C_min`** (CBS recall below `C_min`, e.g. 0, **fails crit-1 regardless** of the blended number). Recall
   is attributed to its source gate (G1 fresh-fetch = accuracy; G2 majority = precision only).
2. **Bounded low-stakes overhead — both modes.** ≤ X% over *current* researchPrime (absolute). G and X% are
   **pre-registered with the fixture size set by a power calc** so the target is statistically reachable.
3. **Research path better-aimed (falsifiable) — both modes.** The Oranges receipt must **name ≥1 dropped/reordered
   branch + its counterfactual cost** to pass, else it is stamped "no foresight value added" and crit-3 is
   reported **NOT satisfied**; a planted-path-defect probe confirms it re-aims.
4. **Density preserved — both modes.** No existing rigor removed; zero-AXIS-finding rounds skipped; a low-stakes
   run fires zero Synthesizer/Judge/debate sub-agents.
5. **Cross-lineage origin fusion — ENHANCED ONLY (N/A by default).** A reviewer adds +1 independent origin only
   with an **attested-lineage basis** (a value in a committed **closed enum** of vendor lineages; agreement across
   the same lineage adds 0; off-enum/absent ⇒ capped at +1 total). Default substrate forces `cross_model:false`.
6. **Reuse-not-fork — both modes.** Each imported module resolves to a single canonical path.
7. **Learned independence (amendment) — Enhanced-leaning, MONOTONE-SAFE.** A single **shared independence-accounting
   module** is the sole origin/quorum counter (same-lineage agreement adds 0, **invariant under any ρ̂**), and a
   **cross-run calibration ledger** produces ρ̂ that may only **TIGHTEN** the quorum with stakes — **never loosen it
   below the pre-registered static ≥2 floor** (ρ̂ is a censored LOWER bound on true ρ; loosening would chase the
   bias). Below a pre-registered N_min (or no data), it falls back to the static rule and stamps "ρ unestimated."
   Ratcheting the static floor *down* requires human re-approval. researchPrime is wired; Crucible/Foreman adoption
   is a gated fast-follow.

## Locked invariants (the real Stage-1 lock — encodings are Stage-2's)
- **I1 ρ-honesty:** the default (single-family) mode may DETECT/REPORT a shared blind spot but must NOT claim to
  close it; it stamps the correlated-class recall as a **measured ceiling, not a guarded result**. True
  ρ-mitigation (a fresh cross-lineage origin) is **Enhanced-only**.
- **I2 CBS floor:** correlated-blind-spot recall is a **gating** sub-criterion, not a reported aside.
- **I3 origin integrity:** only an attested distinct-lineage reviewer increments `independent_origins`;
  `cross_model:true` is a heterogeneity proxy, never an independence guarantee; degraded mode ⇒ `cross_model:false`.
- **I4 G7 downgrade-only:** the audit cannot raise a ladder level without a NEW fetched pointer (engine AND degraded).
- **I5 G2 precision-only:** self-consistency reduces variance, injects no new external bits, cannot raise the ladder.
- **I6 no gamed gates:** thresholds (G, X%, C_min, N) are pre-registered before measurement; the **stakes vector
  is itself adjudicated** (reviewer-checkable; a "declared-low-but-irreversible" planted case guards under-calling);
  irreversibility forces tier ≥ medium.
- **I7 honest convergence:** a high-stakes round going dry suspiciously fast forces a probe-or-dissent; only rounds
  that introduced a fresh pointer/claim count toward the dry threshold N (no padding to N with empty rounds).
- **I8 ledger-reproducibility (amendment):** every run stamps the calibration-ledger hash it consumed, the learned
  threshold it derived, AND what the static ≥2 rule would have required; given the same (inputs + ledger-hash) a
  run is replayable to an identical verdict. **Default mode is a pure function of its inputs** — ledger influence is
  Enhanced-leaning and always overridable to the static rule. The learned quorum is **monotone-tighten-only** (I7/crit-7):
  it can never relax the bar below the pre-registered floor, so it cannot self-drift trustworthiness downward.

## Architecture (unchanged from v4)
`researchPrime/bin/` (Node ESM), a sibling of Crucible/Foreman that **imports, never forks** the trio machinery;
researchPrime owns the ledger, the ladder, GATE-1, and the stakes governor. Import surface + topology proven in Phase 0.

## Phased plan (what/why — Stage-2 finalizes mechanism)
- **Phase 0 — Import GO/NO-GO + pre-registration (gates all).** Prove the trio import from researchPrime's dir;
  freeze Crucible's export surface + a contract test. **Pre-register G (gap-closure), X%, C_min, N + the fixture
  size (power calc)**; author the fixture spec **including the CBS class and a declared-low-but-irreversible case**.
  NO-GO → **Phase 0.5** (owned trio-core extraction; all three repos stay GREEN, one canonical copy each).
- **Phase A — Phase-1 seam.** Emit a stakes **vector** (captures irreversibility; reviewer-checkable; irreversible ⇒
  tier ≥ medium), projected to a governor tier; emit the Oranges foresight receipt (names a dropped branch + cost).
- **Phase B — Engine skeleton (reuse, not fork).** Import the frozen trio surface; orchestrator owns ledger + ladder;
  `agent()` seam; checkpoint/resume.
- **Phase C-1 — Evidenced core (cheap, measured first).** G1 CoVe independence, G2 self-consistency (precision-only),
  G7 invariant. Measure recall vs single-pass baseline, broken out by source gate AND by CBS class.
- **Phase C-2 — Round orchestration.** G3 heterogeneous ≥2-agree reviewers, G4 separate Judge, G5 convergence-until-dry
  (+ I7 suspiciously-dry honest handling), G6 finding-identity/oscillation guard, G8 cross-lineage fusion (Enhanced),
  G9 conditional debate, and the active Synthesizer (steering measured vs a token-matched control).
- **Phase D — Governor wiring + inclusion-test enforcement.** Tune the tier projection; enforce "no round that
  doesn't serve the AXIS"; low-stakes fires zero high-tier agents.
- **Phase E — Deliverables + honest degraded mode.** Surface round history, Judge verdict, convergence proof, and the
  separate **Synthesizer Brief**. Non-engine hosts get the honesty stamp ("schema conforms; adversarial verification
  did NOT run"); the prose check is an **output-conformance** fixture (the word "parity" is forbidden for prose).
- **Phase F — Verification.** `node --test`; recall A/B against pre-registered G + the **CBS floor** (I2); cost delta
  vs X%; AXIS→tier accuracy incl. irreversible override + the under-call guard (I6); one-canonical-copy (crit 6);
  G7-upgrade-throws + degraded `cross_model:false` asserted; dogfood proving the dry + suspiciously-dry predicates.

## Assumption map
A1 → Phase-0 gate. A2 engine primary; degraded honest. A3 stakes inferability validated (Phase F). A4 high-stakes
cost → budget pre-flight. **A5 ρ is nonzero and ESTIMATED-WITH-KNOWN-BIAS** (amendment): heterogeneity reduces not eliminates; the
calibration ledger's ρ̂ is **right-censored** (uncaught shared blind spots are unobservable), so ρ̂ is a LOWER bound
that under-estimates true ρ. Hence the learned quorum is monotone-tighten-only (crit 7 / I8) and ρ̂ is stamped
"censored lower-bound" — never used to relax the bar; it is calibrated against the planted-CBS fixture ground
truth, never the live ledger's self-reported catches.

## Premortem (closed-by)
1 governor→crit-2 gate. 2 A1→Phase 0/0.5. 3 oscillation→G6+dry predicate. 4 false independence→attested-enum + cap.
5 portability→honest stamp. 6 Synthesizer credit→token-matched. **7 shared blind spot → DETECTED+stamped by default,
mitigated only in Enhanced (I1) — no hollow claim.** 8 mis-tiered irreversible→vector + override + under-call guard.
9 gamed thresholds→pre-registered G/X%/C_min/N. **10 over-polish → Stage-1 locks invariants, Stage-2 owns encodings.**

## Out of scope (Grasscatcher)
Phase-2 gathering changes; new deliverable tiers; PM merge; retiring prose mode. **(The trio-level independence-
accounting module + ρ-calibration ledger were PULLED INTO SCOPE by the v6 amendment — no longer deferred.)**
Remaining deferral: **wiring Crucible's Shark-Tank and Foreman's reviewers to the shared module** (gated fast-follow,
its own plan — this plan builds the shared module + researchPrime's use of it, not the other two engines' rewrite).
