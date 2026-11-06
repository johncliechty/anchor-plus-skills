# Crucible — Implementation Plan (Foreman-ready)

**Status:** Stage-2 v2.2 — **CONVERGED** (Stage-2 Shark-Tank rounds 2 & 3 both dry = convergence bar met; round-1 + round-2 findings fixed; passes the well-formedness gate, 11 waves). Supersedes v1 (`plans/proto/implementation-plan-v1.md`). Derived from `MASTER-PLAN.md` v4.1 (approved). Verdicts in `plans/debates/stage2-round-{1,2,3}/SYNTHESIS.md`. **Awaiting user approval to start the Foreman build.**

test-command: node --test test/

> Gate = Node native test runner over `test/`. **Every wave must ship real SOURCE its new tests import and exercise** (Foreman's vacuous-GREEN guard, `wave-engine.mjs:350`, HALTs a wave that changes no executed source; the anti-test-weakening guard HALTs on reduced/skip tests). Negative/HALT fixtures are added in the wave that introduces the behavior they cover, not deferred.
>
> **Test discovery (established in Wave 1, keep it):** `node --test test/` runs `test/index.mjs` (via `test/package.json` `main`), which **auto-discovers every `test/*.test.mjs`**. A wave just drops its `<name>.test.mjs` file in `test/` — do NOT hand-edit `index.mjs`, and do NOT change the `test-command`.

**Project-DONE:** Wave 11 GREEN via the orchestrator-run gate; the Wave-11 self-run demonstrates **convergence** (a real finding tallied → a subsequent dry round) AND emits a doc-trio that `foreman/bin/locate-plan.mjs --json` accepts with zero HALTs; the 5-gate Skill Productionization Checklist passes.

**Acceptance-criteria convention (D16):** every wave has a one-line **done-when**; non-trivial waves add 1–3 **Given/When/Then** scenarios.

**Foreman contract facts (verified against source — honor these):** import `newCheckpoint` / `validateCheckpoint` / `writeCheckpointAtomic` / `readCheckpoint` / `makeBudget` / `HaltError` from `foreman-lib.mjs`; `makeAgentDriver` from `wave-workflow.js`; `makeGitContext` from `git-hygiene.mjs`. Crucible's checkpoint is the **`newCheckpoint(...)` superset + Crucible deltas** and must satisfy Foreman's `validateCheckpoint` — **assert behaviorally via `validateCheckpoint`, never against a magic field-count constant**. `makeGitContext` calls `assertContainment`, which HALTs if a managed repo's git toplevel **either contains OR is nested inside** `C:\dev\foreman` — Crucible must resolve toplevel per project and isolate in either case. (Crucible's own repo `C:\dev\crucible` is a *sibling* of `C:\dev\foreman` — unaffected.)

---

## Wave 1 — Engine skeleton, contract & substrate seams

**Intent:** Stand up the Crucible Node engine importing (never forking) Foreman's modules, with the live-agent seam and git wiring in place.

**Deliverables:** `package.json` (`"type":"module"`, `"test":"node --test test/"`); `bin/crucible-lib.mjs` re-exporting the imported Foreman primitives (named above) + a **Foreman import smoke-test**; the **checkpoint as `newCheckpoint(...)` superset + Crucible deltas** (`stage`,`phase`,`round`,`drift_flags`,`synthesizer_direction_ref`) passing `validateCheckpoint`; the three-stage **state machine** + **halt-gate set** (`haltForHuman(reason, pending_action)`); `bin/agent.mjs` — the **live `agent()` seam** mirroring Foreman's `run-live.mjs` (`claude -p`), env-gated, stubbable in tests; **git context** that resolves a managed project's repo toplevel and **isolates when it would either contain OR be nested inside `C:\dev\foreman`** (the `assertContainment` guard fires in both directions).

**Depends on:** —

**done-when:** `node --test test/` passes: import smoke-test, checkpoint superset round-trips + validates, state-machine transition guard, and the git-toplevel/containment resolver.

- **Given** Crucible's checkpoint, **when** `validateCheckpoint` runs, **then** it passes and Crucible's delta fields survive round-trip (assert behaviorally — no hard-coded field count).
- **Given** a managed repo whose toplevel would either contain OR be nested inside `C:\dev\foreman`, **when** the git context initializes, **then** it isolates (separate worktree/copy) instead of letting `assertContainment` HALT.

## Wave 2 — Shark-Tank round engine

**Intent:** The adversarial round: 3 independent fresh-context Sharks + adjudication.

**Deliverables:** `bin/shark-tank.mjs` via `makeAgentDriver({agent})` (using Wave-1's seam) — Skeptic/Contrarian/Analyst, each prompt embedding the North Star + a rotated PM critique angle; file-based verdict artifacts; **finding-identity with cross-Shark normalization** so ≥2-agree actually fires on the *same* issue; the **`traces-to-north-star` emission** that **inclusion-test demotion** consumes; **BLOCKER = ≥2 agree**; **dry-round detection**.

**Depends on:** Wave 1

**done-when:** `node --test` shows (with a stubbed agent) a scripted round producing correct BLOCKER vs dry-round verdicts, and inclusion-test demotion dropping a non-tracing finding.

- **Given** two Sharks raise findings that normalize to the same id, **when** tallied, **then** it's a BLOCKER; **given** a finding with `traces-to-north-star: no`, **then** it's demoted and cannot hold the loop open.

## Wave 3 — The Synthesizer & the Judge

**Intent:** The persistent Director (steers, never decides) + the deciding Judge.

**Deliverables:** `bin/synthesizer.mjs` (last-round-verbatim + direction log; Oranges suggesting; the **fresh-eyes cold pass** as a *new* no-context instance; Director ≠ decider); `bin/judge.mjs` (decider: cross-model when reachable, else a **same-model judge persona in a fresh, context-free sub-agent** with all evidence in-prompt); per-role **model stamp**.

**Depends on:** Wave 2

**done-when:** `node --test` proves the Director never decides, the Judge decides from injected evidence, and a **fresh-eyes isolation oracle** test confirms the cold-pass instance receives no prior context.

- **Given** the Director holds a prior position, **when** the fresh-eyes pass runs, **then** the oracle confirms an empty journal and divergence routes to the Judge/challenge round.

## Wave 4 — Gates + first end-to-end loop proof

**Intent:** The two-gate machinery, proven as a full cycle this early (not at the end).

**Deliverables:** `bin/gates.mjs` — **well-formedness gate** that **spawns** `foreman/bin/locate-plan.mjs --json` and gates on exit 0 (forge-proof artifact; **ENOENT/stderr handling** on spawn failure); **quality/convergence gate** (dry-round + Judge + user-approval HALT); **drift detector** (post-lock, tiered, two-option resolution). Plus a **round→tally→gate integration test** asserting a complete cycle end-to-end.

**Depends on:** Wave 3

**done-when:** `node --test` shows the well-formedness gate pass on a good fixture / fail (exit≠0) on a malformed one and on spawn-ENOENT; the drift detector tiering; and **one integration test driving round → tally → gate to a verdict**.

- **Given** a malformed doc-trio, **when** the well-formedness gate runs, **then** it captures the non-zero exit + stderr to a forge-proof artifact and reports FAIL (no crash).
- **Given** a scripted finding then a clean round, **when** the integration test runs, **then** it shows tally → dry round → gate verdict.

## Wave 5 — ResearchOne integration

**Intent:** Wire research into framing + rounds, cost-guarded.

**Deliverables:** `bin/research.mjs` — ResearchOne **once up-front** + **per-round only on a genuinely new candidate**; a **Tier-3 deep-archaeology** lane for brownfield Stage 0; findings flow to the Analyst Shark + the Synthesizer.

**Depends on:** Wave 4

**done-when:** `node --test` (stubbed ResearchOne) shows once-up-front invocation, the per-round novelty cost-guard (no re-invoke when no new candidate), and findings reaching consumers.

## Wave 6 — Stage 0: Intake & Framing

**Intent:** Greenfield framing + tiered brownfield ingest → North-Star lock.

**Deliverables:** `bin/stage0.mjs` — greenfield Oranges framing (→ candidate North Star/criteria/Non-Goals/risk taxonomy/foresight brief); **tiered brownfield ingest** (T1 inventory/dedupe→`plans/intake/`; T2 reproduce-first + test-coverage done-vs-claimed; T3 delegate deep archaeology to ResearchOne) with **Confirmed/Inferred/Gap** labels that **gate** (criterion-touching Gap blocks lock; irresolvable/people-only Gap HALTs); **salvage-vs-rewrite as a user gate question** (never scored); the **North-Star-lock** HALT gate (drift detection begins after it).

**Depends on:** Wave 5

**done-when:** `node --test` covers greenfield framing shape, correct tier selection by input, label-gating (criterion-touching Gap → HALT), and the lock gate.

- **Given** a docs-only input, **when** the tier is chosen, **then** Tier 1 runs (no archaeology); **given** a criterion-touching Gap, **then** Stage 0 HALTs rather than locking.

## Wave 7 — Stage 1 protocol (Master Plan)

**Intent:** The Master-Plan refinement stage end-to-end.

**Deliverables:** `bin/stage1.mjs` — Oranges brainstorm with **assumption-mapping → premortem**; **batch** idea-triage (integrate / Grasscatcher / drop); phased plan with near-term specifics; the Shark-Tank loop (Waves 2–4); the user-approval HALT gate.

**Depends on:** Wave 6

**done-when:** `node --test` drives a scripted greenfield intent through Stage 1 to an approved phased Master Plan, exercising one full Shark-Tank loop.

- **Given** brainstorm output with an out-of-scope idea, **when** batch-triage runs, **then** it lands in the Grasscatcher and the plan does not absorb it.

## Wave 8 — Stage 2 protocol (Implementation Plan + handoff)

**Intent:** Emit the Foreman-ready doc-trio and hand off — the literal North-Star deliverable, given its own wave.

**Deliverables:** `bin/stage2.mjs` — wave **decomposition** (PM heuristics); emit the **doc-trio** with `## Wave N` + `test-command:` + **hybrid acceptance criteria** (done-when + G/W/T) **and a generated `foreman.config.json`** so locate-plan resolves HALT-free; the Shark-Tank loop; the user-approval gate; the **handoff guarded by the well-formedness gate** (must pass before handoff).

**Depends on:** Wave 7

**done-when:** `node --test` runs a scripted approved Master Plan through Stage 2 producing a doc-trio (+ config) that **passes the Wave-4 well-formedness gate** with zero HALTs.

- **Given** an approved Master Plan, **when** Stage 2 emits the doc-trio, **then** every wave has a done-when, non-trivial waves have G/W/T, a `foreman.config.json` is written, and locate-plan returns OK.

## Wave 9 — Cross-model Enhanced mode + remote

**Intent:** Capability-bound upgrades + GitHub remote.

**Deliverables:** capability-binding (try-and-observe) for Gemini/ChatGPT/Grok; **cross-model Judge at lock** + **reasoning Synthesizer** when reachable, using **reasoning-strength + family-diverse** selection, per-role stamping, graceful degrade; **GitHub private remote** + **push-at-approval-gates (ask each time)** via a **hermetic push seam testable without network**; never auto-push.

**Depends on:** Wave 8

**done-when:** `node --test` (stubbed probes + a fake remote) shows correct model selection/stamping present-vs-absent, degrade-and-stamp, and that push only occurs at a gate with confirmation.

- **Given** a Claude-authored plan with Gemini reachable, **when** the lock Judge is selected, **then** it is Gemini (different family) and is stamped; **given** none reachable, **then** the same-model fresh-context judge persona is used and stamped.

## Wave 10 — Docs & version-control layer

**Intent:** Generate/maintain the living-doc set.

**Deliverables:** writers for `CLAUDE.md`/`CLAUDE_hist.md`, `DECISION-LOG.md` (MADR/DACI), `GRASSCATCHER.md`, `plans/{intake,proto,debates,research}/`; the **optional flag** (default OFF) for `RTM.md`/`viz/` (Mermaid)/`SUMMARY.md`.

**Depends on:** Wave 9

**done-when:** `node --test` verifies the core doc set generates correctly and the optional docs appear only when the flag is set.

## Wave 11 — Tests, fixtures, dogfood self-run & productionization

**Intent:** Harden and prove the skill end-to-end.

**Deliverables:** `bin/self-run.mjs` (a runnable entrypoint) + a productionization **checklist-checker** source module (so this wave ships real executed source, not just docs); a **real buildable project** brownfield fixture + distributed negative/HALT fixtures; the **dogfood self-run** that proves **convergence** (a real finding tallied → a subsequent dry round) AND a **user-gate HALT + resume**, then emits a doc-trio + `foreman.config.json` **into a dedicated isolated output dir** and gates against that dir (locate-plan zero HALTs; avoids a multi-`.md`-per-role HALT); the **5-gate Skill Productionization Checklist**; `SKILL.md`.

**Depends on:** Wave 10

**done-when:** the full `node --test` suite is green; the self-run transcript shows convergence (finding → dry round) + a user-gate HALT/resume + a zero-HALT doc-trio; the 5-gate checklist passes.

- **Given** a fixture intent, **when** the self-run executes, **then** its transcript contains a tallied finding followed by a dry round, a user-gate HALT and resume, and a final doc-trio that locate-plan accepts with zero HALTs.
