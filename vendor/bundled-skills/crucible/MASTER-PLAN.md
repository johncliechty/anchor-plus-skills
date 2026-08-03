# Crucible — Master Plan (v4.1)

> *A vessel that withstands extreme heat to refine raw metal into something pure.*
> Crucible is the **planning brain** of John's skill trio: **ResearchOne** (research) → **Crucible** (planning) → **Foreman** (build).

**Status:** v4.1, 2026-06-05. v4 **converged** (Shark-Tank round 3 = unanimous dry round, `plans/debates/round-3/SYNTHESIS.md`). v4.1 adds John's two approval-review additions: the **same-model fresh-context Judge** for degraded mode (§8/§10) and an explicit **Enhanced (cross-model) mode** description (§10). Awaiting final user approval.

---

## 1. North-Star Objective (the drift anchor)

**Objective:** Build *Crucible* — a standalone production planning skill that reliably turns an intent (or a messy existing project) into a **vetted, gold-standard, Foreman-ready implementation plan**, while **never drifting** from the project's locked objective.

**Success criteria:** (1) emits a Foreman-ready doc-trio that `foreman/bin/locate-plan.mjs` accepts with **zero HALTs**, each wave carrying **testable acceptance criteria**; (2) both stages **converge** (Shark Tank draws no new blood) and the **user approves** each, on ≥1 real project; (3) **zero untracked drift**; (4) **autonomous between gates, with checkpoint/resume**; (5) **independence honored** (fresh-context Sharks; cross-model judge + reasoning Synthesizer when reachable, else degraded-and-stamped).

**Non-goals:** ❌ no pedagogy/education · ❌ not a builder · ❌ not the everyday lightweight planner (Project-Manager is that, and Crucible's lighter sibling for non-critical work) · ❌ v1 doesn't *require* cross-model.

---

## 2. What Crucible is / is NOT

- **Is:** its **own standalone skill** — a deliberately-invoked, heavyweight planner that forges a gold-standard plan through framing, brainstorming, a best-in-class restatement, and **Shark-Tank** refinement steered by a persistent **Deep-Think Synthesizer** and backed by ResearchOne, then hands a Foreman-ready plan to the builder.
- **Reuses, does not absorb or fork:** imports/calls Project-Manager (Real-Intent ethos, critique angles, decomposition), ResearchOne, and Foreman's durability code.
- **Is NOT:** a lightweight everyday planner, a code builder, or an infinite-polishing machine.

*(Build note: Crucible is developed by running its own process on itself — "sharkfooding" each draft. "Dogfood" is just that build note, not a product concept.)*

---

## 3. Two guiding principles

**3a. The inclusion test (North-Star justification — the size rule).** Every element — phase, step, artifact, role — must earn its place by **serving a North-Star success criterion** (or being a load-bearing enabler / risk-reducer for one). *Growth that serves the objective is welcome; only what fails the test is bloat → cut or Grasscatch.* We do **not** cut for brevity, and we do **not** keep ceremony no criterion needs. (This is the anti-drift rule applied to the plan's own content; it is also the round-level mechanic — see §9.)

**3b. The Parable of the Oranges (real-intent foresight).** From PM's Real-Intent Protocol (Brother Randall Ridd's *Parable of the Oranges*): the second employee learns the oranges are for juice at a party of twenty, asks which variety juices best, gets a bulk discount, and drops them at the house — *same task, radically better outcome.* Crucible is the second employee. Concretely it must: **probe for the real goal** before planning; **bring expertise** (best-in-class options, not the user's input lightly edited); **optimize for the actual outcome**, not the literal request; **think 2–3 steps ahead** (surface what will be needed later — the auth wall, the data to capture now); **add justified value**; and **show the receipt** (decisions + why + trade-offs). This ethos lives in **Stage-0 framing**, **Stage-1 brainstorming**, and the **Synthesizer's suggesting mandate** (§7).

---

## 4. The pipeline — three stages, each you-approve

Each refinement stage runs the **Shark-Tank loop** (*draft → sharkfood → fix → sharkfood → … → converge*), steered by the **Synthesizer** (§7), and ends at a **user gate** (the user is the convergence authority).

### Stage 0 — INTAKE & FRAMING  → 🚦 user locks the North Star
- **Greenfield:** capture intent; the Synthesizer runs an Oranges-style **framing pass** → candidate Objective + criteria + Non-Goals + risk taxonomy + foresight brief.
- **Brownfield:** run the **tiered ingest** (§5), then the framing pass produces a **reverse-engineered** candidate North Star + gap list.
- **🚦 Gate:** user **confirms/edits and locks the North Star** (the single most reliable anti-drift mechanism). Drift detection begins **after** this lock.

### Stage 1 — MASTER PLAN (the *what & why*)  → 🚦 user approves
1. **Brainstorm widely** with Oranges foresight (Phase-1 **batch** triage: refinements integrate · out-of-scope → Grasscatcher · drop). Mandatory order: **assumption mapping → premortem**.
2. Refine into a **phased plan** with **enough concrete near-term specifics to seed an implementation plan**; defer the rest explicitly.
3. **Sharkfood → fix → …** until dry; the Synthesizer issues direction between rounds.
4. **🚦 User reviews, understands, and APPROVES.**

### Stage 2 — IMPLEMENTATION PLAN (the *how*, Foreman-ready)  → 🚦 user approves
5. Decompose into waves (PM decomposition heuristics) and draft the **Foreman doc-trio** — `IMPLEMENTATION-PLAN.md` carries `## Wave N` + `test-command:` **and per-wave acceptance criteria** (a one-line *done-when* per wave, plus 1–3 **Given/When/Then** scenarios for non-trivial waves — right-sized by the inclusion test).
6. **Sharkfood → fix → …** until convergence.
7. **🚦 User APPROVES** → run the **well-formedness gate** → hand off to Foreman.

---

## 5. Stage 0 in depth — tiered brownfield ingest (Lane E, right-sized)

Stage 0 stays load-bearing but **scales to the input** (the inclusion test):
- **Tier 1 — docs/notes only (default):** inventory & **dedupe conflicting plan versions** → find the latest truth; build a manifest in `plans/intake/`.
- **Tier 2 — has a repo:** add a **done-vs-claimed** read — **reproduce-first** (does it build/run?) + a **test-coverage sweep** (no test ⇒ label *Inferred-untested*, not Confirmed).
- **Tier 3 — large/contested:** **delegate deep archaeology to a ResearchOne lane** (Crucible calls, never re-implements a 16-step pipeline).

Throughout: **Confirmed / Inferred / Gap** labels that **gate** — a *Gap touching a North-Star criterion blocks the lock*; an **irresolvable/people-only gap HALTs** at the checkpoint (it does not silently become a RAID assumption). Then: **AS-IS → TO-BE gap analysis** (seeds Stage-1 brainstorming); **salvage-vs-rewrite = a user-answered gate question** (Crucible surfaces the facts and trade-offs but **never scores** it — it lacks the org facts; the "40%" heuristic is UNVERIFIED). End at the **North-Star lock**.

---

## 6. The Shark Tank (the adversarial review)

Each round = a **Shark Tank**: the draft is pitched; the **Sharks** (independent, **fresh/cleared context**, refute-prompted, each given the **North Star verbatim**) try to sink it.
- 🦈 **Skeptic** *(Critic)* · 🦈 **Contrarian** *(Devil's-Advocate)* · 🦈 **Analyst** *(ResearchOne)*. Shark briefs rotate **PM's 8 critique angles** (security, frustrated-UX, operator, skeptical-researcher, competitor, bored-investor, future-maintainer, steel-man-the-premise) for diverse pushback.

Rules: **BLOCKER needs ≥2 Sharks to agree**; stable finding `id` (anti-oscillation); each finding tagged `refinement | out-of-scope`; findings that **fail the inclusion test** (don't trace to a criterion) are demoted/discarded — they cannot keep the loop open. A round with **no new BLOCKER/MAJOR** is a **dry round**.

---

## 7. The Synthesizer — a persistent Deep-Think Director (Lane F, right-sized)

A reasoning model in a **dedicated, persistent role, separate from the Sharks** — it **directs**, it does **not decide**.
- **Where:** the **Stage-0 framing pass** (Oranges foresight → North Star, risk taxonomy, foresight brief) **and after every Shark Tank** (reads the round, issues direction + proactively **suggests what's missing / needed downstream** — the Oranges "two steps ahead").
- **Persistence (simplified):** carries the **last round verbatim** + a short running **direction log** (open disputes · risk register · probing brief for the next round). *(The capped-journal compression + variance-collapse machinery are deferred to v2 — they were sized for the 5-round edge case.)*
- **Mandate:** reason by **evidence quality, not which side is louder**; keep fresh ResearchOne input each cycle (avoid the epistemic bubble).
- **Director ≠ decider (round-2 fix):** the Synthesizer steers; **the decider of convergence is the cross-model judge (when reachable) + the user.** This dissolves the "grades its own homework" anchoring risk.
- **Anti-anchoring:** **one fresh-eyes cold pass before each lock** — a *new* Synthesizer instance, **no prior context**, reads the transcripts cold; **material divergence → a challenge round / surfaced to the decider** (never reconciled by the anchored Director).
- **Provisioning (best-available, capability-bound — D13):** prefer a true reasoning model (Gemini Deep Think via `deep-mind`; Claude extended-thinking on the Pro sub; o-series with a key), else the `deep-think` **skill** ("SYNTHESIZER-BETA"). Pin the tier at stage start; degrade-and-stamp within a stage; **always stamp which ran.**

---

## 8. Convergence & gates

- **Convergence = sharkfood-until-dry; the USER is the final authority**, with **the Judge (§10) as the model-side decider** — cross-model when reachable, else a same-model judge persona run as a fresh-context sub-agent. Lockable when: no open BLOCKER/MAJOR · a dry round · no unresolved drift flags · the fresh-eyes pass concurs · the user approves.
- **Round cap = a safety ceiling only** (default 5; halt-to-user if hit). Most stages converge in 2–3.
- **Two distinct gates:**
  - **Well-formedness (machine, forge-proof):** the orchestrator **spawns** `foreman/bin/locate-plan.mjs --json` as a child process and gates on **exit code 0** (it's a CLI, not importable). This is the only executable ground truth.
  - **Quality (judgment):** Shark verdict + fresh-eyes pass + **the Judge (§10)** + user approval. Backed by **per-wave acceptance criteria** (a *done-when* line + Given/When/Then for non-trivial waves) so Foreman has a per-wave oracle and can't silently default-fill ambiguity. *(Full machine-verifiable YAML conformance contracts remain v2 — Grasscatcher #1.)*

---

## 9. Anti-drift (central pillar; Tiered; two-option resolution)

Lock the North Star at the Stage-0 gate; every change is **goal-tagged**. **Drift = new ideas surfacing** → classify + offer **two options** (recommend one): **(A) out-of-scope → Grasscatcher** (with a suggested future home), or **(B) refinement → sharpen the North Star** (logged amendment, user-approved). Tiered: minor = flag + offer; MAJOR = HALT + offer. **Drift detection runs only after the North-Star lock** (Stage-0 gaps are exempt — they're the brainstorm seed). Brainstorm **batches** then summarizes. Every Shark/research/Synthesizer prompt **embeds the current North Star** and emits `traces-to-north-star: yes/no + which criterion`; a finding/change that fails this is demoted (the inclusion test as a round mechanic). *(The `north_star_hash` plumbing is v1.1 hardening; the embedding itself is v1.)*

---

## 10. Independence & substrate — two modes

**Default mode (Pro / Claude, no API keys — like Foreman).** Independence comes from **context isolation**: every Shark runs in a fresh/cleared context with a role-differentiated refute brief. The model-side **Judge** is a **same-model judge persona run as a fresh-context, context-free sub-agent** with all relevant evidence (the round's surviving findings, the North Star, the acceptance criteria) placed in its prompt — *never* the anchored Synthesizer. The Synthesizer reasons on Claude extended-thinking. **This mode is fully functional on the subscription alone.**

**Enhanced mode (non-default — activated when API keys / extra model CLIs are reachable).** Capability-binding (ResearchOne try-and-observe) detects reachable models and upgrades independence where a *different model family* helps most:
- **Cross-model Judge at the lock gate** — the decider is a model from a **different family** than the plan's author (e.g. Claude wrote it ⇒ judge with Gemini, GPT, or Grok), removing same-family self-preference at the single highest-leverage decision point.
- **True reasoning model for the Synthesizer** — prefer Gemini Deep Think (`deep-mind`) or an o-series model for the Stage-0 framing + cross-round direction, where reasoning depth pays off most.
- **(v2) Full cross-model debate roster** — mixing families across the Sharks themselves (Grasscatcher #3); deepest but most complex; deferred.

**Selection order when several are reachable:** the Synthesizer takes the strongest reasoning model (Gemini Deep Think → o-series → Claude extended-thinking); the Judge takes the strongest model from a *different family* than the plan's author (Claude-authored ⇒ Gemini → GPT → Grok). Overridable per project. Every run **stamps which model filled which role**, so a plan's provenance shows exactly how much cross-model independence it got. Missing keys never block a run — it degrades to Default mode and says so.

**Honest residual risk:** in Default mode the Shark panel *and* the Judge share the same model's blind spots; fresh context fixes anchoring, not model-level/sycophantic correlation. Default mitigations = the ≥2-agree BLOCKER rule + the fresh-eyes cold pass + the human as final authority. **Enhanced mode is what actually closes the same-family gap at the decision point — it is the recommended setup for a Critical project.**

---

## 11. Architecture — autonomous Node engine (Foreman sibling)

A standalone skill whose orchestrator is a **Node engine**, like Foreman.
- **Import/share** Foreman's importable modules — **never fork**: `foreman-lib.mjs` (atomic checkpoint writes, budget), `git-hygiene.mjs` (git hygiene), and `makeAgentDriver({agent})` from `wave-workflow.js`. The contract resolver (`locate-plan.mjs`) is a **spawned CLI**, not an import.
- **State machine:** stages → phases → rounds; checkpoint extends Foreman's with `stage`, `phase`, `round`, `open_findings`, `drift_flags`, `synthesizer_direction_ref`.
- **Halt-to-human gates:** North-Star lock · Master-Plan approval · Implementation-Plan approval · MAJOR-drift · goal-amendment · cap reached · unrecoverable. Autonomous between gates; checkpoint + resume.
- **Sub-agents communicate via file paths only.**
- **Remote (D13):** local commits per round automatic; create a **private GitHub repo** and **push at the two approval gates, asking each time** (never auto-push).

---

## 12. Docs & version control

**v1 core (always):** `CLAUDE.md` · `CLAUDE_hist.md` · `MASTER-PLAN.md` (live truth) · `DECISION-LOG.md` (MADR/DACI) · `GRASSCATCHER.md` · `plans/{intake,proto,debates,research}/` · the Foreman doc-trio · `.git/`.
**Optional flag (default OFF — no tiers in v1):** `RTM.md`, `viz/` (Mermaid C4/roadmap/dependency), `SUMMARY.md` (investor-brief) — generated on request. `MASTER-PLAN.md` stays sharp; history offloads to `CLAUDE_hist.md` + `plans/proto/` + git.

---

## 13. Build waves for Crucible itself (→ IMPLEMENTATION-PLAN.md at Stage-2 lock)

1. **Engine skeleton** — import Foreman libs; state machine; halt gates; checkpoint deltas.
2. **Shark-Tank round engine** — fresh-context Shark driver (PM 8 angles), file verdicts, finding-identity, BLOCKER=≥2, inclusion-test demotion.
3. **The Synthesizer** — persistent Director (last-round-verbatim + direction log), Oranges suggesting, the **fresh-eyes cold pass**; Director≠decider; best-available provisioning + stamp.
4. **Gates** — spawn-resolver well-formedness + quality/convergence (dry-round + judge + user) + acceptance-criteria emission + drift detector.
5. **ResearchOne integration** — once-up-front weakness + best-in-class; per-round only on a new candidate; Tier-3 deep-archaeology lane for Stage 0.
6. **Stage-0 intake** — greenfield Oranges framing + tiered brownfield ingest (§5), → North-Star lock.
7. **Stage-1 + Stage-2 protocols** — Oranges brainstorm (assumption-map→premortem; batch triage), phased Master Plan, wave decomposition + acceptance criteria, Shark-Tank loops, approvals, Foreman handoff.
8. **Cross-model layer** — judge at lock + reasoning Synthesizer when reachable; GitHub-private remote + push-at-gates.
9. **Docs/VC layer** — CLAUDE.md/CLAUDE_hist split, DECISION-LOG/ADR, Grasscatcher, intake; optional RTM/viz/SUMMARY.
10. **Tests, fixtures, self-run, productionization** — negative/HALT fixtures (use a real buildable project as the brownfield fixture); full self-run; Skill Productionization Checklist (5 gates).

---

## 14. Open items — resolved (D16)
- ✅ **Enhanced-mode model order** = reasoning-strength + family-diverse (§10), overridable per project.
- ✅ **Per-wave acceptance-criteria format** = hybrid (a *done-when* line + Given/When/Then for non-trivial waves) — §3 step 5, §8.

No material plan-level open items remain; the rest is build-time detail handled in the waves (§13).

---

## 15. Change history

### v4 → v4.1 (John's approval-review additions)
- **Degraded-mode Judge defined:** when no cross-model judge is reachable, the model-side decider is a **same-model judge persona run as a fresh-context, context-free sub-agent** with all evidence in its prompt (never the anchored Synthesizer) — §8, §10.
- **§10 rewritten as two explicit modes:** Default (subscription-only) vs Enhanced (the cross-model effort when API keys/CLIs are present), with per-role model stamping.
- **Open items resolved (D16):** Enhanced-mode model order = reasoning-strength + family-diverse; per-wave acceptance criteria = hybrid (done-when + Given/When/Then for non-trivial waves).

### v3 → v4
- **Added the inclusion test (§3a)** as the size rule (North-Star service, not brevity) — and restored the **Parable of the Oranges / Real-Intent ethos (§3b)** into Stage-0 framing, Stage-1 brainstorming, and the Synthesizer's suggesting mandate. Pulled in PM's **8 critique angles** (Sharks) and **decomposition heuristics** (Stage 2).
- **Right-sized, not gutted (round 2):** Stage 0 is now **tiered** and delegates deep archaeology to ResearchOne; the Synthesizer keeps its persistent Director role but with **simplified** persistence (last-round-verbatim + direction log; compression/variance → v2).
- **Synthesizer directs, doesn't decide** (decider = cross-model judge + user); **one fresh-eyes cold pass before each lock.**
- **Added per-wave acceptance criteria** (justified growth, serves Criterion #1; full YAML conformance stays v2).
- **Fixed the gate:** spawn `locate-plan.mjs` (exit 0), don't import. Confirmed/Inferred/Gap labels now **gate**; salvage-vs-rewrite = a user question; drift detection starts after lock; intake artifacts → `plans/intake/`; residual same-model conformity risk documented honestly.
