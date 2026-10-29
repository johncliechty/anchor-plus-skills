# Gandalf (full "magic" advisor) — Research FINDINGS + converged method

> **Run stamps:** researchPrime ENGINE mode (import spike go:true, 28 crossed symbols, 0 missing) · sub-agent
> axis = PARALLEL-SWARM with real fresh-context isolation · substrate = single-family (all Claude) →
> **cross_model:false** (correlated blind spots FLAGGED, not mitigated) · stakes = HIGH · adversarial loop
> **CONVERGED** (dryStreak=2 at N=2; Rounds 3+5 dry, Round 4 empty/not-counted) · suspiciously-dry guard did
> NOT fire (roundsToDry=3 ≥ K=2) · `verified:true`. Evidence ladder OBSERVED>CORROBORATED>CLAIMED>UNVERIFIED>
> REFUTED. **SCOPE (user, mid-dive):** Gandalf = UNDERSTAND + SITUATE + ANTICIPATE; NO brainstorming (that is
> Jumper, a SEPARATE later skill that composes Gandalf). See `run/SCOPE-CORRECTION.md`.

## 0. What this dive solved
The diagnose core was already vetted. This dive solved the 5 open problems behind the FULL magic Gandalf —
weighting the two hardest (the generative-AND-vetted method; the skill-composition mechanism). The mid-dive
scope correction (Gandalf is not a brainstorming skill) **dissolved the original crux** (the kill-filter-vs-
boldness tension is Jumper's, not Gandalf's) and **unblocked Gandalf** (no Jumper dependency). What remained
was re-derived and adversarially hardened to convergence.

## 1. Evidence ledger (the disciplining findings)
**The transfer leap (the honest cap on everything below):**
- **L0 [UNVERIFIED]** The ledger below is HUMAN ideation/forecasting/editing/peer-review evidence. That a
  STATELESS LLM executing this protocol in one pass reproduces those gains is the load-bearing, UNTESTED
  transfer. The literature grounds the MECHANISM DESIGN, not the LLM's execution efficacy. Upgradable ONLY by
  passing the M4 oracle.

**SITUATE/ANTICIPATE is real, evidenced value:**
- **L1 [CORROBORATED]** Distant solvers win broadcast search at higher rates; winning probability rises with
  solver–problem distance (Jeppesen & Lakhani, *Org Science* 2010, 166 InnoCentive challenges). → Gandalf's
  edge is the marginal seat the author can't occupy; situate value from a NAMED adjacent field is repeatable.
- **L2 [CORROBORATED]** Sound transfer = relational STRUCTURE-MAPPING, not surface (Gentner 1983; Gick &
  Holyoak). → groundedness test = name ≥2 relational correspondences; noun-only matches rejected.
- **L3 [CORROBORATED]** Analogical distance is NON-MONOTONIC (sweet spot): too-near=fixation, too-far=novel
  but low feasibility (Dahl & Moreau 2002; Fu/Chan/Cagan/Schunn). → distance × mapping = value; distance
  without mapping = variance.
- **L4 [CORROBORATED]** Outside-view / reference-class forecasting beats inside-view (Kahneman & Lovallo 1993;
  Flyvbjerg). → after "field X solved this with Y," check Y's base rate in its home field (anti-recklessness).
- **L5 [OBSERVED]** NIH scores innovation as a SEPARATE axis from approach. → dual-axis (value-if-true ×
  groundedness), never collapsed; high-value/low-grounded surfaced LABELED-as-a-bet.
- **L6 [OBSERVED]** Consultant method = hypothesis-led + answer-first + disconfirmation (Minto; McKinsey
  day-1). → state the anticipation answer-first, then enumerate what disconfirms it.
- **L7 [OBSERVED]** Developmental editing adds FORWARD value as a pass distinct from error-catching (Stein). →
  separate DEFECT (diagnose) from ELEVATION (anticipate/situate); grade the second. ("magic, not just critique")
- **L8 [OBSERVED]** Scenario planning holds a SET of bold futures, not a point prediction (Wack 1985). → when
  an anticipation hinges on an unknowable, emit a small conservative/aggressive set with enabling assumptions.

**Honest labeling of anticipations (the residue of open-problem #1 that binds Gandalf):**
- **L9 [CORROBORATED]** Graduated, revisable confidence beats binary (Tetlock; GJP/IARPA ACE 2014); ICD 203 +
  Kent decouple boldness from certainty, reporting confidence WITH its basis. → tier the anticipation; only a
  REFUTED one drops.
- **L10 [UNVERIFIED→constraint]** A label is honest ONLY IF falsifiable + names what moves it + EARNED by a
  survived refutation, never self-assigned. → each elevation carries {named defeater, refutation_provenance,
  what-would-upgrade}.

**Composition (Agent C read the real trio source):**
- **L11 [OBSERVED]** Trio's only composition primitive is the injected `agent(prompt,opts)=>result` seam;
  engine→engine = in-process IMPORT (never fork), skill→skill = the seam realized by a spawned sub-agent.
- **L12 [OBSERVED]** Degraded mode is first-class + STAMPED; capability bound by try-and-observe, not introspection.
- **L13 [OBSERVED]** NO spawn-depth/fan-out cap exists in the trio (`makeBudget` caps waves/wall-clock only).
  → the compose contract MUST add depth + spawn caps + cycle guard.
- **L14 [CLAIMED]** A same-model-family commission is NOT an independent origin (generalizes the trio I1
  shared-blind-spot stamp). → the result envelope carries substrate_family; same-family ⇒ no corroboration credit.

**Measuring "magic" (reframed must-ANTICIPATE / must-SITUATE):**
- **L15 [OBSERVED]** The diagnose core already has a must-find oracle (`defects.jsonl` + recall-vs-baseline +
  power-calc + prereg); the path-defect class is already a forward-insight oracle. → must-elevate = its sibling
  generalization, not green-field.
- **L16 [CORROBORATED]** Held-out real design-history (answer key = a documented LATER real revision) is the
  cleanest non-circular oracle (retrodiction design); carries hindsight-selection bias — disclose, don't close.
- **L17 [CORROBORATED]** A valid "beats generic review on insight" A/B requires paired design + position-swap-
  with-agreement (Zheng 2023) + length control (Dubois 2024) + answer-key anchoring + CAT novelty×usefulness
  (Amabile) + cross-family judge at HIGH stakes + pre-registered power-calc. Less than this measures artifacts.

## 2. The converged method (after the adversarial loop)
### ELEVATE protocol (the magic) — stateless SKILL.md steps, run AFTER the diagnose core, gated by the firing gate
**SITUATE (commission researchPrime):** S0 ABSTRACT the artifact's core challenge to a domain-neutral pattern
(Gandalf-only — the author can't abstract their own framing) → S1 commission researchPrime to find the field
where that pattern is a solved, mature problem (moderate-to-far distance; exclude the artifact's own field) →
S2 structure-map (≥2 relational correspondences, answer-first) → **route the CORRESPONDENCE CLAIM itself
through a SEPARATE-origin refuter** (find the strongest disanalogy) → outside-view base rate of Y in its home field.

**ANTICIPATE (Gandalf owns — bounded premortem on a sound artifact):** "N months later this sound artifact hit
a wall — what coming problem did the author miss?"; each anticipation asserts a problem NOT YET PRESENT (a
future-state condition + enabling assumption — machine-checkably distinct from a present-tense diagnose
finding); subject_cardinality==1; NO counterfactual-cost/regret pricing (that is Crucible's Oranges → commission
Crucible). Hold a conservative/aggressive SET when an anticipation hinges on an unknowable.

**SCORE + LABEL (honest, never a kill-filter):** dual-axis value-if-true × groundedness (NIH); tier = the
refutation OUTCOME, earned by an INDEPENDENT named-defeater refutation (never a self-score):
- **GROUNDED** *(requires a CROSS-FAMILY refuter that could not land the named defeater + a researchPrime-
  verified basis)*
- **PROMISING-BUT-UNVERIFIED** *(a same-family refuter could not land the defeater — a frame-bounded lower
  bound; THE TOP TIER ACHIEVABLE ON A SINGLE-FAMILY HOST)*
- **SPECULATIVE** *(not refuted, no independent refutation ran)* · **REFUTED** *(defeater landed — DROP; the
  only drop condition)*.

### Composition mechanism (SCC — general Phase-0 capability; Gandalf is first consumer, commissions ONLY researchPrime)
- **Spawn:** SPAWN (Skill-tool-inside-Agent, fresh-context sub-agent → typed envelope) by default; INLINE-LOAD
  on a no-sub-agent host (ISOLATION:approximated); DEGRADED-INLINE when unavailable (emit a could-not-run
  envelope; never fake). Capability bound by try-and-observe.
- **Typed envelopes:** commission `{scc_version,commission_id,skill,intent,task,context,stakes,north_star,
  budget{depth_remaining,spawn_remaining},commission_chain[],caller_lineage}`; result `{ran,mode,isolation,
  honesty_stamp,substrate_family,result,ladder[],open_questions,degraded_reason,budget_consumed}`.
- **Anti-laundering law:** carry every ladder rung AT OR BELOW source (never upgrade); needs_verification
  survives; preserve honesty_stamp/mode; same-substrate_family ⇒ no independent-origin credit; ATTRIBUTE
  ("SITUATE via researchPrime"), never absorb.
- **(B) realness (honest rung):** satisfied NOW only by the bare `agent()` seam, which is IMPORT-RESOLVED this
  run (spike go:true) — a LIVE call was not executed this dive; the orchestrator commission-ledger (unforgeable
  id minting + resolution) is an **UNVERIFIED STEP-0 deliverable** that makes the anti-laundering law machine-
  checked (until then it is an honest honor-system SKILL.md checklist).
- **Firing gate:** SITUATE fires iff the artifact has a central load-bearing claim + a plausible better-in-class
  frame Gandalf can't already cite OBSERVED/CORROBORATED + stakes ≥ medium.
- **Budget cap + cycle guard:** seed depth/spawn budgets; a skill twice in commission_chain ⇒ HALT-for-human;
  **bounded refuter fan-out** (only value-above-threshold findings get an independent refuter; rest ship
  SPECULATIVE; exceeding the per-run refuter budget R HALTs, never silent-drops).

### Boundary (compose-not-reimplement) — machine-checkable canaries
B1 Gandalf emits ZERO ideation findings (divergent idea generation is Jumper's). · B2′/B7′ content-binding
verify (cited id RESOLVES in the ledger; cited rung ≤ envelope rung; situate correspondences appear in the
envelope — BLOCKED until the ledger is built). · B3 premortem ≠ Oranges (cardinality-1, no regret/counterfactual
fields → else commission Crucible). · B4 refutation-to-convergence is Crucible's. · B5 diagnose exclusive to the
core. · B6 no silent degradation (any per-finding degraded stamp ⇒ top-level degraded:true). · B8 honest
synthesis (risk_labels cover every leg). · B9 anticipate = future-state condition + enabling assumption. ·
B-honesty named-defeater + refutation_provenance, else auto-downgrade. · **B-ceiling single-family ⇒ max
PROMISING; GROUNDED unreachable without a cross-family refuter.**

### Oracle (measurable "magic")
Sibling `elevations.jsonl` (must-anticipate / must-situate) reusing the defects.jsonl spine: SOUND artifact +
ground_truth_elevation (documented later real revision / coming problem with external anchor) + non_obvious_at_
time + surface_review_misses (MEASURED, incl. a full diagnose-core pass, not asserted). Construction order:
held-out real design-history > retrodiction framing > expert-panel ≥2-of-3 (the weak arms NEVER pooled with the
real arm). A/B = paired (same fixture+seed), cross-family judge, position-swap-with-agreement, length-control,
rubric anchored to the answer key (primary metric = elevate_recall, a LOWER BOUND) + a paired false-elevation
(precision) guard, vs THREE baselines: generic review / diagnose-core / **abstraction-equipped direct-
researchPrime (the BINDING baseline)**. **GATE-0.5 hard SHIP/NO-SHIP:** if real-history k < power floor →
elevate efficacy UNPROVEN (never "beats baseline on N=k"). **Self-disproof owned:** if Gandalf does not beat the
direct-researchPrime arm by margin G, SITUATE is declared NON-ADDITIVE → SHIP BLOCKED → descope to a
researchPrime prompt template.

### Build sequencing (HONEST — Gandalf is Jumper-unblocked but compose-contract-blocked)
Depends on: diagnose core (build-ready) + researchPrime (exists) + Phase-0 SCC compose contract incl. the
orchestrator-ledger (NOT built). Does NOT depend on Jumper (inverted — Jumper is a later cycle that composes the
finished Gandalf). Order: STEP-0 orchestrator-ledger ids (UNVERIFIED) → GATE-0 per-finding schema + canary
harness → GATE-0.5 oracle feasibility → SITUATE seam (B2′/B7′) → DIAGNOSE seam (B5) → ANTICIPATE (B3/B9) →
SCORE/LABEL/SYNTHESIS (B1/B6/B8/B-ceiling/B-honesty) → ORACLE A/B (must beat the binding arm by G) → ship-or-
descope.

## 3. Adversarial round history (engine-verified)
- **R1 — BLOCKED:** gated BLOCKER `self-rated-groundedness` (3/3 reviewers: the load-bearing bold claim is
  self-graded, not independently refuted; CBS-1) + gated MAJOR-blocking `compose-contract-blocked` (2/3) + gated
  MINOR `anticipate-vs-diagnose`. FIXED: external named-defeater refutation; orchestrator-minted ids + honest
  sequencing; future-state separability. (Plus elevated singles: cross-context leap, oracle circularity,
  situate non-additivity, axis reconciliation, precision.)
- **R2 — BLOCKED:** gated BLOCKER `grounded-tier-overreads-single-family` (3/3: the same-family refuter is not
  independent, so GROUNDED over-reads) + gated MINOR + strong singles (orchestrator-ledger unverified vs L11;
  refuter fan-out unbounded; "fixes are specifications not survived tests"). FIXED: HARD single-family ceiling
  (max PROMISING; GROUNDED needs cross-family) as a machine-checked invariant; meta-honesty stamp; ledger →
  UNVERIFIED STEP-0; bounded refuter fan-out; self-disproving oracle bound to the direct-researchPrime arm.
- **R3 — DRY (non-empty):** zero blockers; one sub-threshold MINOR (bare-seam "real on host" over-read) recorded
  + fixed (→ IMPORT-RESOLVED, not OBSERVED live call).
- **R4 — EMPTY:** all three fresh adversaries found nothing (I7: not counted toward the dry streak).
- **R5 — DRY (non-empty), CONVERGED:** zero blockers; only MINOR Crucible-handoff residuals (gated:
  prereg-unbound-values 3/3; consolidate-patch 2/3). dryStreak → 2 → CONVERGED.

## 4. CBS register (single-family — FLAGGED, not mitigated)
- **CBS-1 RESOLVED WITHIN-FRAME; residual = CBS-5.** Self-grading eliminated (a separate origin attacks a named
  defeater), but on single-family substrate that origin shares the frame → frame-bounded lower bound; the tier
  ceiling (B-ceiling) CARRIES this rather than hiding it.
- **CBS-2** transfer lineage — partially de-risked by independent converging lineages (open-innovation,
  decision); capped by L0.
- **CBS-3** TRIZ/biomimicry anecdotal — only the abstraction discipline used; no hit-rate claim.
- **CBS-4** oracle shared blind spot — elevate_recall is a lower bound; + a false-elevation precision guard;
  periodic fresh human/cross-family audit.
- **CBS-5** same-family composition incl. the refuter — UN-MITIGABLE on single-family host; enforced as the hard
  B-ceiling, not a footnote.

## 5. Residual decisions for the Crucible (the dive does NOT lock these)
1. Pre-register concrete VALUES: refuter budget `R`; non-additivity margin `G` (with the paired-test power calc);
   the value-if-true threshold that gates a refuter; the single k power-floor (collapse "≥8–10 × ≥20" to one
   committed pair); the re-derived spawn cap N (incl. worst-case refuter count); the commission recursion/cycle
   depth cap. (Style = the PLAN's frozen N=2/K=2/M=0 prereg block.)
2. **Ledger-ownership fork:** is the orchestrator commission-ledger (unforgeable id minting + resolution +
   anti-laundering enforcement) a **Phase-0 compose-contract** deliverable shared by all compositional skills
   (preferred — it must generalize to Jumper-composes-Gandalf) or scoped into Gandalf's STEP-0? Lock the choice +
   the dependency edge before build.
3. Oracle calibration: the human-dual-scored subset size + the minimum grader-vs-human ICC/κ the automated oracle
   must hit before its elevate_recall / false-elevation outputs are trusted (else degrade to SPECULATIVE).
4. Build-time re-stamps: CBS-5 re-stamped UN-MITIGABLE unless a cross-family refuter is actually wired (which
   also lifts the B-ceiling toward GROUNDED); B2′/B7′ + the STEP-0 forgery fixture run + pass as STEP-0 GREEN to
   upgrade the anti-laundering law from honor-system to machine-checked.
5. Consolidate the candidate (v3 + the Round-3 patch) into one sealed intake so the (B) honesty rung is
   single-sourced (no stale "real on this host" read).
6. (Carried from the diagnose core) N (hypothesis count), nitpick/elevation caps, LIGHT/FULL depth thresholds,
   committed schema field types, the operator-wrong-pass scoring rubric.
