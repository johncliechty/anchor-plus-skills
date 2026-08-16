---
name: crucible
description: >-
  Standalone production planning skill — the planning brain of the trio
  researchPrime (research) -> Crucible (planning) -> Foreman (build). Invoke it on
  an intent (greenfield) or a messy existing project (brownfield) to forge a
  vetted, gold-standard, Foreman-ready implementation plan WITHOUT drifting from
  the project's locked objective. Three you-approve stages — Stage 0 Intake &
  Framing (lock the North Star) -> Stage 1 Master Plan -> Stage 2 Implementation
  Plan + Foreman handoff — each refined by an adversarial Shark-Tank loop (3
  fresh-context Sharks; BLOCKER needs >=2 to agree) steered by a persistent
  Deep-Think Synthesizer (steers, never decides) and decided by a context-free
  Judge plus the user (the convergence authority). A Node engine that IMPORTS
  Foreman's durability/git/driver modules (never forks) and SPAWNS
  locate-plan.mjs as the machine well-formedness gate. STATUS (2026-06-05): the
  full engine — Waves 1-11 — is built and GREEN; the dogfood self-run proves
  convergence (finding -> dry round) + a user-gate HALT/resume and emits a
  zero-HALT doc-trio, and the 5-gate Skill Productionization Checklist passes.
---

<!-- ELEGANCE-LAW v2 -->
## The Elegance Law (locked by John — binding on this skill)

Canonical text: `Skill Foundry/ELEGANCE.md`. Applies to ANY agent running this
skill on ANY host. If this block and a longer procedure below disagree, this
block wins.

1. **Approvals are ≤200 words** — what changes in his world, the recommendation,
   the one thing that gets worse. The artifact stays on disk and is named, not
   pasted. An approval obtained with a longer block is VOID.
2. **Summaries are ≤150 words** — goal in one line, done / not done, ≤3 findings
   ranked by consequence, the single next decision. Never rounds, waves, seats,
   stamps, gate counts, or file inventories.
3. **Default to the lightest band, without asking.** A heavier tier requires the
   first status line to NAME its trigger: irreversible or externally visible,
   inputs unconverged, a prior failure in this exact area, or he asked for it.
4. **Needed-because line.** Any element he did not request carries one line:
   "Needed because ___; dropping it costs ___." No line, no element.
5. **Show a cut.** ONE dry round ends a review loop — never a streak. Every plan
   names something it removed; "nothing cut" is said aloud.

**THE VERIFICATION LAW** (added 2026-08-15 after its FOURTH recurrence — each of
the first three was written into a journal and recurred anyway):

6. **Verify the claim you actually made, on the surface he actually uses.**
   "It's live / fixed / renders" is a claim about HIS screen. That the server
   emits new bytes, that a build exited zero, or that assertions passed are
   claims about something else. Render it and look at it.
7. **A symptom reported twice retires the first explanation.** Test the
   hypothesis; never repeat it. An explanation that makes his report false
   ("it's your cache", "it's a data issue") needs MORE evidence, not less.
8. **Prefer a mechanism to an instruction.** If the same instruction is given
   every session, the instruction is the defect — build what removes it.
9. **A correction that lives only in a journal or a memory has not been made.**
   Promote it to where it is loaded BEFORE the work starts.

**Two laws these serve.** A gate that cannot see what the user sees is not a gate
— structure diffs are lints, and must be labelled as lints. And a guardrail is
never the whole product of a turn — if enforcement withholds output he already
paid for, show it anyway.
<!-- ELEGANCE-V2.1 addendum -->
**What elegance IS (researchPrime-vetted, 2026-08-15):** the largest result
carried by the least machinery its user can actually hold — every element
forced by an INDEPENDENT citable need, nothing present the objective does not
pay for. Earned by iteration, never by skipping work: as simple as the task
allows, no simpler than a single datum permits.

**The Rabbit-Catcher (canonical battery: `ELEGANCE.md` Part II, ships with
the bundle):** the steering seat runs the full RC battery at PLAN APPROVAL
and on any NEW mid-run element; round boundaries ask only RC-6 ("still on the
critical path?"). Uncertain ⇒ PARK the element (zero further spend) + one
batched line in the next block the user already reads — never silent pursuit,
never ad-hoc interruption. Needs and hazards must be independent of their
proposer (no self-authored justification records); malleability work is
never cut as "unused capability"; guards are judged by RC-G, never by
retirement. Verdicts: KEEP / HOLD (with written trigger or budget) / CUT
(logged).
<!-- /ELEGANCE-V2.1 -->
<!-- /ELEGANCE-LAW -->


> **Humans:** read `HUMAN.md` first. This file is the agent/engine protocol.

# Crucible

Crucible is the **planning brain** of John's skill trio: **researchPrime** (research)
→ **Crucible** (planning) → **Foreman** (build). It is a deliberately-invoked,
heavyweight planner that turns an intent — or a messy existing project — into a
**vetted, gold-standard, Foreman-ready implementation plan**, while **never
drifting** from the project's locked objective.

> **Tier definition (Heavy vs regular · always-cross-model · seat mapping):** canonical in `AGENTS.md` (Foundry root on the author host; your install root in a distributed bundle) → "Skill tiers". A `-Heavy` run uses top-frontier models on EVERY seat regardless of the base session (delegate the frontier seat to a frontier-pinned sub-agent if the base session isn't frontier); foundry skills are ALWAYS true cross-model. Do not re-define tiers locally.

> **Status (2026-06-05): the engine is built and GREEN through Wave 11.** The
> three-stage pipeline, the Shark-Tank round engine, the Synthesizer + Judge, the
> two-gate convergence, researchPrime integration, the cross-model Enhanced mode +
> GitHub remote, the docs/VC layer, and the dogfood self-run + 5-gate
> productionization checklist all live in `bin/` and are exercised by
> `node --test test/`. The model-driven steps run through an injected `agent()`
> seam; the machine well-formedness gate is Foreman's real `locate-plan.mjs`,
> SPAWNED (never forked) so its exit code is forge-proof.

## What Crucible is / is NOT

- **Is:** a standalone skill that forges a plan through framing, brainstorming, and
  **Shark-Tank** refinement steered by a persistent **Deep-Think Synthesizer** and
  backed by researchPrime, then hands a Foreman-ready plan to the builder.
- **Reuses, never forks:** imports Foreman's `foreman-lib.mjs` (atomic checkpoints,
  budget, contract primitives), `git-hygiene.mjs`, and `makeAgentDriver` from
  `wave-workflow.js`; **spawns** `foreman/bin/locate-plan.mjs` as the well-formedness
  gate. Exactly one copy of each on disk.
- **Is NOT:** a lightweight everyday planner (that's Project-Manager), a code builder
  (that's Foreman), or an infinite-polishing machine.

## Two guiding principles

- **The inclusion test (the size rule):** every element must serve a North-Star
  criterion; growth that serves the objective is welcome — only non-serving bloat is
  cut or Grasscatched.
- **The Parable of the Oranges (real-intent foresight):** probe for the real goal,
  bring expertise, think 2–3 steps ahead, add justified value, show the receipt.

## The pipeline — three you-approve stages

1. **Stage 0 — Intake & Framing** → 🚦 the user **locks the North Star**. It opens with
   a **complexity triage** (`assessComplexity`): cheap intake signals (scope, novelty,
   stakes/irreversibility, unknowns) recommend a pipeline depth — **LITE** (single-pass,
   minimal/no Shark rounds for small/clear work), **FULL** (the full 3-stage + Shark-Tank
   machinery — the default), or **SPIKE-FIRST** (probe before planning when genuinely
   uncertain). Right-sizing is **your** judgment, so it **HALTs for you to confirm** and
   **defaults to FULL** when uncertain or when stakes are high — rigor is never silently
   downgraded. The triage only right-sizes *ceremony*: the North-Star lock, post-lock drift
   detection, the inclusion test, and full Shark-Tank rigor (when FULL) are unchanged in
   every band. Then greenfield Oranges framing, or a tiered brownfield ingest (T1
   inventory/dedupe → T2 reproduce-first + coverage → T3 delegate deep archaeology to
   researchPrime), with Confirmed/Inferred/Gap labels that gate. Drift detection begins
   **after** the lock.
2. **Stage 1 — Master Plan** → 🚦 the user **approves**. Oranges brainstorm
   (assumption-map → premortem → ideate), batch triage, a phased plan, then the
   Shark-Tank loop to convergence.
3. **Stage 2 — Implementation Plan** → 🚦 the user **approves** → the well-formedness
   gate → **Foreman handoff**. Wave decomposition with per-wave acceptance criteria
   (a one-line *done-when* + Given/When/Then for non-trivial waves), the Shark-Tank
   loop, then the emitted doc-trio + `foreman.config.json`.

### The hardening law (Stage 2 — MANDATORY; `bin/hardening-gate.mjs`, journal 0080)

**A plan that ASSERTS a property must EMIT a mechanical gate for it.** This is the
sibling of the mockup-contract law (journal 0079): the plan does not get to *describe*
a guarantee, it must emit the artifact that makes the guarantee checkable.

It exists because Crucible planned, and Foreman built GREEN, a subsystem whose plan
asserted *"Strip is append-only; receipts are never lost"* and *"the steward never
invents; unknown is spoken as unknown"* — and shipped both as prose. The ledger was a
bare `writeFileSync` read-modify-write, so two concurrent acts silently dropped
receipts; a swallowed exception rendered a **broken** store as the cheerful *"no
projects"* with an ambient queue badge of **0** (= "nothing needs you").

At Stage 2, run `checkPropertyGates({plan, waves, addsSurface})` — **enforced in engine**
(`bin/apply-hardening-to-plan.mjs` + `writeDocTrio` fail-closed, journal **0081**). Draft injects
the checklist; emit HALTs with `hardening-gate-failed` if still not pass:

1. **Durability claims are STORAGE claims.** "append-only" / "never lost" / "single
   writer" / "atomic" ⇒ the plan must name atomic write (temp + fsync + rename), a lock
   or documented serialization, **and a concurrency test**. A module that *validates* a
   rule does not *provide* it — say which layer provides it.
2. **Every surface-bearing wave emits a failure-state table**: dependency-missing,
   dependency-slow-or-killed, dependency-returns-garbage, backing-store-unreadable,
   empty-but-valid. Each row names the **status code AND the user-visible text**.
   **"unknown" and "empty" are DIFFERENT rows** — collapsing them is the single most
   common honesty defect across this codebase.
3. **Any value crossing a process boundary as a delimited string** needs a delimiter
   guard in the plan (reject / escape / drop-and-report), not just in review.
4. **Any client-side poller against an endpoint that spawns a process** must be planned
   with visibility gating + failure backoff. Fixed-rate polling of a spawning endpoint
   is a standing BLOCKER.
5. **Sharks attack the plan for "property asserted, no gate emitted"** as a standard
   finding class.

**The Shark Tank** is the adversarial review round: 3 independent fresh-context Sharks
(Skeptic / Contrarian / Analyst), each prompted to refute, each embedding the North
Star + a rotated PM critique angle. **BLOCKER = ≥2 Sharks agree.** **The Synthesizer**
is a persistent Director that steers but never decides; **the Judge** decides
(cross-model when reachable, else a same-model fresh-context judge persona), and **the
user is the final convergence authority**.

## Substrate (two modes)

- **Default (subscription-only):** fresh-context Sharks + a same-model fresh-context
  Judge persona. Fully functional on the bare subscription.
- **Enhanced (API keys / CLIs present):** a cross-model Judge at the lock gate + a
  reasoning Synthesizer, selected by reasoning-strength + family diversity, with
  graceful degrade. Every run **stamps which model filled which role**.

## Files in this skill

**Engine (Node — ESM `.mjs`):**
- `bin/crucible-lib.mjs` — the contract layer: re-exports the imported Foreman
  primitives, the checkpoint superset (`newCrucibleCheckpoint`), the three-stage state
  machine + HALT-gate set, and the containment-safe managed-git context.
- `bin/agent.mjs` — the live `agent()` seam (`claude -p`), env-gated by
  `CRUCIBLE_AGENT_LIVE=1`, stubbable in tests.
- `bin/shark-tank.mjs` — the adversarial round engine (Sharks, cross-Shark finding
  identity, ≥2-agree BLOCKER, inclusion-test demotion, dry-round detection).
- `bin/synthesizer.mjs` / `bin/judge.mjs` — the Director (steers, never decides; the
  fresh-eyes cold pass + isolation oracle) and the context-free deciding Judge.
- `bin/gates.mjs` — the well-formedness gate (spawns `locate-plan.mjs`), the
  quality/convergence gate, and the post-lock tiered drift detector.
- `bin/hardening-gate.mjs` — the **hardening law** (journal 0080): detects properties a
  plan ASSERTS; pure predicates; `renderPropertyGateChecklist()` emits plan text.
- `bin/apply-hardening-to-plan.mjs` — inject + re-check; wired into `writeDocTrio` fail-closed
  (journal **0081**).
- `bin/research.mjs` — researchPrime integration (once up-front + cost-guarded per round).
- `bin/stage0.mjs` / `bin/stage1.mjs` / `bin/stage2.mjs` — the three stage protocols.
- `bin/band-profile.mjs` — LITE / SPIKE-FIRST / FULL ceremony profiles (cf-slick; depth → real path).
- `bin/enhanced.mjs` / `bin/remote.mjs` — the CROSS-FAMILY verification seam (builds the
  live role-routed agent: Gemini Sharks/Judge, Claude steering — the 5:1 split, via the
  shared `makeRoleRoutedAgent` + gemini-cli tier ladder) + the push-at-approval-gates
  GitHub remote (never auto-pushes).
- `bin/docs.mjs` — the living-doc + version-control layer.
- `bin/self-run.mjs` — the dogfood self-run (drives Stage 0→1→2, proves convergence +
  HALT/resume, emits a zero-HALT doc-trio) — also the runnable entrypoint.
- `bin/checklist.mjs` — the 5-gate Skill Productionization Checklist (the five
  North-Star criteria, made checkable) + the SKILL.md manifest checker.

**Tests:** `test/*.test.mjs`, auto-discovered by `test/index.mjs`. The gate is
`node --test test/`.

## How to invoke — the OPERATOR RUNBOOK (2026-07-11; a live session drives THIS, never an improvised protocol)

1. **Bind the live seam.** `CRUCIBLE_AGENT_LIVE=1`; build the cross-family agent via
   `buildLiveCrucibleAgent()` (`bin/enhanced.mjs` — Gemini Sharks/Judge, Claude steering, the 5:1
   split, Gemini cap 2). Pass its ROUTES into the loop (`runMasterPlanLoop({ ..., routes })`) so the
   Judge's stamp derives from where the judge role ACTUALLY dispatches (T7) — the default same-model
   Judge persona is the agy-down fallback, not the normal path.
2. **Stage 0** → `runStage0`/protocol: complexity triage HALTs for depth confirmation; frame; candidate
   North Star. **Gate ergonomics (John's locked preferences):**
   > **THE SHOW-THE-ARTIFACT RULE (locked by John, 2026-07-16): NEVER ask the user to approve/lock a
   > North Star they have not just been SHOWN. At the moment of the ask, print the ENTIRE candidate
   > North Star document — statement, success criteria, non-goals, risk taxonomy, foresight brief,
   > every section, verbatim — to the screen in the message body. A file pointer is NOT showing it.
   > A summary or paraphrase is NOT showing it. A clipped dialog preview is NOT showing it. If it was
   > shown earlier but anything intervened since, print it again in full with the ask. The same
   > discipline applies to every user-approval artifact (Stage-1 Master Plan, Stage-2 plan, amendment
   > diffs): the user approves what is on the screen, never what is in a file.**
   > **PROTOTYPE RULE (locked by John, 2026-07-18):** If the stage involves generating GUI prototypes or images, you MUST physically open them in the user's local browser (e.g. via an HTML wrapper and `Start-Process chrome`) BEFORE asking for their approval. Asking for approval before they have seen the prototypes on their screen is strictly forbidden.
   If the user asked for research, DELIVER IT BEFORE the lock ask; present decisions ONE AT A TIME,
   each with 30-second plain-English context and a recommendation first.
3. **Stage 1** → `runStage1({ agent, northStar, depth, routes, artifactsDir, statusLog, ... })` —
   brainstorm → triage → phased plan → Shark loop. On the round cap it HALTs WITH the best draft +
   open findings attached and persisted (T5) — review those, never restart from zero.
4. **Stage 2** → `runStage2({ agent, northStar, masterPlan, outputDir, depth, routes, statusLog, ... })`
   — decompose → loop → approval → emit + well-formedness gate → Foreman handoff. A cap HALT emits the
   unapproved doc-trio to `<outputDir>/_unapproved-cap-draft` (gated, clearly not the handoff).
5. **Dogfood deterministically** (no model, no billing): `node bin/self-run.mjs [outputDir]`.
6. **LITE / SPIKE / FULL bands (cf-slick 2026-07-22):** locked Stage-0 depth is resolved by
   `bin/band-profile.mjs` into a real ceremony profile — **not** label-only.
   - **LITE:** single-pass brainstorm (no full assumption→premortem→wide ideation), roundCap 1,
     2 concurrent Sharks, research-upfront off by default, low call budget. Still NS-embedded +
     inclusion test + user approval + locate-plan.
   - **SPIKE-FIRST:** probe required (`spikeProbe=`) before Stage-1 plan ceremony; then re-band.
   - **FULL:** full Oranges order, roundCap 5, 3 concurrent Sharks, effort-scoped caps + human-lockable.
   Explicit `roundCap` still wins over the profile default.

> **⏱ STATUS UPDATES TO CHAT — the launch pattern (2026-07-11 fix).** A Shark-Tank stage loop runs
> 20-40 min; a driving session that calls a stage FOREGROUND is frozen and CANNOT post updates — the
> silent-cadence bug. So when a session drives Crucible:
> 1. **Pass `statusLog: '<outputDir>/_crucible-status.log'`** into `runStage1`/`runStage2` — the loop
>    then writes the LOCKED Status table there at t=0, every ~10 min, and on stop (`bin/status-heartbeat.mjs`;
>    OFF when `statusLog` is omitted, so tests/dogfood stay silent). Crucible had NO emitter before this.
> 2. **Run the stage detached from the agent job tree.** P1 2026-07-25 (journals 0020–0027,
>    0064–0067): stages launched via the agent's background Bash (`run_in_background: true`) or
>    `Start-Process -WindowStyle Hidden` died SILENTLY 9+ times — external job-object SIGKILL, not
>    catchable in-process (0066 proved even installed lifetime guards + a watchdog all died with a
>    frozen heartbeat and 0-byte stderr). The PROVEN survivor (0067, ~44 min end-to-end) is a
>    **Windows Scheduled-Task breakaway**:
>    `schtasks /create /tn crucible-<name> /tr "node <launcher> ..." /sc once /st <now+1min> /f`
>    then `schtasks /run /tn crucible-<name>` (delete after). For FULL runs use schtasks; a
>    foreground tool-owned node call also survives (0027) when the operator can hold the window.
>    In-process guards now cover BOTH stages (last-crash.json + HALT.json + per-round BEST-DRAFT.md),
>    but they cannot catch a job-object kill — the launch path is the real mitigation.
> 3. **Arm the cadence at launch** (`ScheduleWakeup` ~600s or `/loop 10m`) and **each tick READ the tail
>    of `_crucible-status.log` (shell-free) and POST the latest status to chat in the LOCKED Status-table
>    format — canonical definition in ONE place: the canonical `AGENTS.md` → "Long-run progress updates"
>    (`[HH:MM]` header · Effort/Doing/Status/Tests/Blocker/Procs/**Journal** rows · ETA + To do footer).
>    The **Journal** row (mandatory, `none` when empty) recaps everything journaled since the last tick —
>    the engine log is the data source; the SESSION composes the Journal row from `journal/`.**
> 4. **Stop** at the stage's user-approval HALT (the loop's `stop()` fires the final table automatically).
> The chat window is the PRIMARY channel; the log is the data source. Only a session reaches chat.

Every real run writes a `journal/runs/` training record (Skill Foundry AGENTS.md "Run capture").

## Standing rules (sleep-cycle promotion 2026-08-15 — journals 0086-0089, 0005, 0069)

- **A criterion names the SURFACE, not the capability.** "The chamber can
  render M1" was green while the page deleted it; the criterion is "M1 is ON
  THE USER'S SCREEN after open," and its gate must look there. (0086)
- **Right-size on task signals, never invocation vocabulary.** Invoking
  Crucible by name is not a request for FULL; converged inputs + fixed scope
  + reversible ⇒ LITE. An `assessComplexity` schema mismatch must be a loud
  refusal — `emptyIntake:true` silently defaulting to FULL is how ceremony
  taxes small tasks. (0087)
- **The declared testCommand must be machine-countable** — a Stage-2 lint on
  runner names; a "gate" that cannot emit counts is not a gate. (0088)
- **A plan that replaces a surface names the DELETION** — acceptance asserts
  the old surface is ABSENT, or the replacement ships beside its ghost. (0089)
- **agy takes model LABEL strings** — stale short ids kill every Shark in a
  round and the wreckage reads as a dry round; the abstain path (never
  silent-drop) exists for exactly this. (0005)
- **`approved=true` must emit, full stop.** A Stage-2 that re-tanks an
  approved plan without emitting is a defect (0069/0076's force-emit exists
  for it) — approval is the user's convergence authority being exercised.

## Usage journal (sleep-loop feed — append after every REAL run)

At the end of any real (non-test) run of this skill, append ONE entry to
`journal/` in this skill folder as `NNNN-<slug>.md` (next number = **max(existing NNNN)+1 over the WHOLE directory** — gandalf accumulated 32 colliding ids because sessions read the low numbers as the frontier; APPEND-ONLY —
a correction is a new entry, never an edit). Keep it under ~15 lines, honest over
polished, with the 7 canonical fields (see the Skill Foundry's
`planning/portfolio-program/src/journal.mjs`): id, skill, situation, context,
observation, outcome (worked | friction | failed | refused), provenance
(genuine-execution | seeded — only genuine-execution corroborates).
No journal entries → the sleep loop has nothing to learn from.
