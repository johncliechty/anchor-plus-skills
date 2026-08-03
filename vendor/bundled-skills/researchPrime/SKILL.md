---
name: researchPrime
description: Universal best-in-class research skill with an engine-backed, stakes-scaled adversarial verification loop. Runs a distinct PLANNING phase and a FRESH plan-only EXECUTION phase (true context isolation on sub-agent hosts; honest degraded mode elsewhere), then a Phase-3 that — on hosts with Node — drives a multi-round adversarial loop (heterogeneous >=2-agree reviewers, a separate context-free Judge, an active Deep-Think Synthesizer, convergence-until-dry, cross-lineage origin fusion) via a Node engine that IMPORTS, never forks, the trio's Crucible+Foreman machinery. Weights evidence on the OBSERVED>CORROBORATED>CLAIMED>UNVERIFIED>REFUTED ladder, reports correlated-blind-spot recall honestly, resists the bandwagon effect, refuses to flatter or hallucinate, and returns three summary levels (full report / executive / agent-implementation). Hosts without Node get a schema-conformant prose run stamped "adversarial verification did NOT run". Use for /researchPrime, "deep research with validation", or any high-stakes investigation.
---

> **Humans:** read `HUMAN.md` first. This file is the agent/engine protocol.

# researchPrime — Universal Best-in-Class Research Skill (engine-backed)

This skill runs a distinct planning phase, a fresh plan-only execution phase, and an adversarial validation phase. It reports the true state of the world, weights evidence by verification quality, and does not tell the requester what they hope to hear. Popularity is not treated as truth.

researchPrime OWNS the evidence ledger, the verification ladder (OBSERVED > CORROBORATED > CLAIMED > UNVERIFIED > REFUTED), GATE-1 independent-origins, the stakes governor, and the three report shapes. On a host with `node`, Phase-3 escalates to a real, stakes-scaled, multi-round adversarial loop in the Node engine in `bin/` — which IMPORTS (never forks) the trio's Crucible+Foreman modules. On a host without Node, Phase-3 runs an honest degraded prose pass and says so.

This file is self-contained for the prose protocol; the engine is in `bin/` alongside it.

> **Tier definition (Heavy vs regular · always-cross-model · seat mapping):** canonical in `<path> Foundry\AGENTS.md` → "Skill tiers". A `-Heavy` run uses top-frontier models on EVERY seat regardless of the base session (delegate the frontier seat to a frontier-pinned sub-agent if the base session isn't frontier); foundry skills are ALWAYS true cross-model. Do not re-define tiers locally.

---

## Step 0 — Mode + capability binding + run-dir (FIRST, every run)

You cannot reliably enumerate your own host's tool list mid-turn. Bind by try-and-observe.

1. **Sub-agent axis.** Default to single-context (sequential role-play). Switch to parallel-swarm only if the host explicitly signals sub-agent support. When unsure, stay single-context.

2. **Engine capability (import probe — NOT direct CLI).** From this skill's directory run:
   `node -e "import('./bin/contract.mjs').then(m=>m.runImportSpike()).then(v=>{process.stdout.write(JSON.stringify(v));process.exit(v.go?0:1)})"`
   If it exits 0 / prints `"go":true`, bind ENGINE mode for Phase-3. If `node` is absent or it exits non-zero, bind DEGRADED prose mode.
   Do NOT use `node bin/contract.mjs` for this probe: when the skill is installed via the onboard junction, that command prints nothing and exits 0 (its CLI guard compares the junction path to the symlink-resolved real path), which would falsely look like NO-GO.

3. **Other capabilities** (web-fetch, code-exec, file-write, sub-agent, search): bind each by a low-cost attempt, never by introspection.

4. **Run-dir.** Create a working dir for the ledger and the engine's crash-durable checkpoints.

---

## Phase 1 — PLAN (deliberate; gather nothing) + stakes vector + foresight

Produce only a written plan: the AXIS (the load-bearing win-condition and what would FALSIFY a candidate); a stakes VECTOR (impact / reversibility / blast-radius — irreversibility forces tier >= medium); the candidate branches; the best-in-class baselines to beat. Name no expected winner.

Oranges foresight receipt (required): name >=1 dropped or reordered branch AND its counterfactual cost. If you cannot, stamp "no foresight value added."

Emit the stakes vector + foresight receipt as the Phase-1 hand-off; the governor projects the vector to a tier that scales Phase-3. Freeze the plan and STOP.

---

## PLAN REVIEW GATE — report the plan ONE-SHOT to the user (approve / edit / abort)

Before crossing the context boundary, present the frozen Phase-1 plan to the user **in one shot** and get an explicit decision. This is the load-bearing checkpoint: execution does not begin until the user APPROVEs. Surface the whole plan in the message body (never clipped into a dialog preview): the AXIS + what would falsify a candidate, the candidate branches, the best-in-class baselines to beat, the stakes vector + projected tier, and the Oranges foresight receipt.

Accept exactly one of: **APPROVE** (proceed to execution), **EDIT** (revise the plan per the user's change and re-present — bounded to 3 cycles), **ABORT** (halt the run). On EDIT, the revised plan is re-frozen and re-reported before any approval counts.

**On a host with Node**, record the decision durably (hash-bound governance record, EDIT re-hash, replay binding) by driving the real engine gate:
`node bin/plan-gate.mjs <planInputs.json> [runDir]` — where `planInputs.json` is `{ objective, axis, branches:[…], baselines:[…], stakes:{ declared_stakes:'low|medium|high', reversibility:'reversible|hard-to-reverse|irreversible', blast_radius:'narrow|moderate|wide', magnitude:'minor|moderate|major' } }` (the `adjudicateStakes` axes; `irreversible` floors the tier at `medium`). Gate 2 renders and approves the ACTUAL Phase-1 plan (AXIS/branches/baselines + stakes/tier/foresight from `runPhase1`), NOT the generic `planMatrix`. APPROVE writes `governance.json` + `gate2-record.json` bound to the plan hash; EDIT re-hashes; ABORT/EDIT-overflow HALTs before execution. The plan artifact is a pure function of the inputs, so the same plan always yields the same `planHash`.

**On a host without Node**, run the same gate as prose: report the plan, capture APPROVE/EDIT/ABORT in the transcript, and only cross the boundary on APPROVE (stamp "plan-gate: prose, not hash-bound").

Only after APPROVE do you cross into fresh execution.

---

## CONTEXT BOUNDARY — FRESH EXECUTION (plan-only)

Execution reads ONLY the frozen plan. On sub-agent hosts this is a real forget (stamp ISOLATION: real only with a recorded nonce check); on single-context hosts it is approximated — quote the plan and derive every step from the quote (stamp ISOLATION: approximated).

---

## Phase 2 — EXECUTE

Gather evidence; record each item in the evidence ledger with its origin(s) and place it on the ladder. Empirical (OBSERVED) requires real code execution; cap at CLAIMED with a NO-EXEC stamp where the host cannot run code. A claim supported only by "everyone says so / most popular" with no primary origin is BANDWAGON-ONLY and never exceeds UNVERIFIED without fresh independent verification. Count origins ONLY through the shared independence module — never re-implement origin counting.

---

## Phase 3 — VALIDATE: the stakes-scaled adversarial loop

### ENGINE mode (Node available)

**Operator recipe (T9, 2026-07-11 — THE canonical way to run rounds; no per-run harness authoring):**
1. Make a run dir; write `round-1-input.json`: `{ round, northStar, stakes, reviews:[{reviewer, angle,
   lineage, findings:[{claim_id?, topic, severity, traces_to_north_star, message}]}], adjudications?:{...} }`.
   When the reviewed artifact carries claim ids, reviewers MUST set `claim_id` (agreement keys on it — G6).
2. `node bin/run-rounds.mjs <runDir> [--max-rounds N]` — replay mode by default (recorded adjudications);
   `RESEARCHPRIME_LIVE_ROUND=1` routes reviewer/debate/judge LIVE to Gemini via agy (5:1; agy down ⇒
   honest HALT, never self-review). `--max-rounds` (default 8) is a HARD budget — the cap stops honestly
   with open blockers in `RUN-STATE.json`, never an unbounded loop.
3. Fix blockers, add `round-<N+1>-input.json`, re-run. Convergence = dry streak N, OR N+1 consecutive
   genuinely-empty rounds = **CLEAN convergence** (explicit stamp, distinct from DRY — a defect-free
   artifact converges honestly instead of pressuring reviewers into filler nits).
4. Deliverable lands as `DELIVERABLE-ENGINE.json`; a training record auto-writes to `journal/runs/`.

Drive the REAL engine loop. The assembled orchestrator is `bin/governor.mjs` + `bin/round.mjs`, presented by `bin/deliverable.mjs`; `bin/dogfood.mjs` is the canonical worked example. Do NOT call `bin/engine.mjs runEngine` — that module is a skeleton with no-op gate slots.

Per governed round (`runGovernedRound({ agent, stakes, reviews, round, northStar })` -> `orchestrateRound(...)`):
- **Governor (stakes scaling).** Tier `low` fires ZERO Synthesizer/Judge/debate sub-agents; `medium`/`high` include them. A zero-AXIS-finding round is skipped at every tier.
- **G3 heterogeneous >=2-agree reviewers** + **G6 stable finding identity** via the trio `tallyFindings`/`SHARK_ROLES`/`angleForShark` (a finding counts only with >=2 agreeing reviewers).
- **GATE-1 independent origins** through the single shared independence module (same-lineage agreement adds 0 origins).
- **G9 conditional debate** — fires only on a conflicting independent-origin pair.
- **G8 cross-lineage origin fusion** — Enhanced-only; INERT by default behind the human-gated lineage enum (claims zero cross-lineage origins, wears the inert stamp).
- **G4 separate context-free Judge** (`makeJudge`) — DECIDES.
- **Active Deep-Think Synthesizer** (`makeSynthesizer`) — STEERS and files a separate brief; never decides.
- **G5 convergence-until-dry, or CLEAN** with the honest tracker: an EMPTY round never counts toward DRY convergence (I7 — you cannot fake adversarial dryness by declining to look), but N+1 CONSECUTIVE empty rounds converge CLEAN with the explicit distinct stamp (T8 — a defect-free artifact terminates honestly). The suspiciously-dry guard is unchanged (a high-stakes run going dry too fast with unresolved high-severity findings fires probe-or-dissent; on a single-family substrate it emits the shared-blind-spot UN-MITIGABLE stamp — it FLAGS, it does not claim to mitigate).
- **Durability (honest statement, corrected 2026-07-11):** the governed round loop is resumable via the ON-DISK round protocol — `bin/run-rounds.mjs` persists every round's input/result JSON plus `RUN-STATE.json`, and re-running continues from the files (Foreman-style in-process checkpointing exists only in the forbidden `runEngine` skeleton; do not rely on it). A mid-round agy HALT costs at most the in-flight round, never the run.

Assemble the run with `assembleDeliverable({ mode:'engine', rounds, convergence, calibration, substrateFamilies, northStar })`: it carries the round history, the Judge verdict, the convergence proof, the rho-hat/learned-quorum state, and the separate Synthesizer Brief (decides:false). The engine resolves the trio's Crucible/Foreman via its in-repo siblings — no configuration; leave RP_TRIO_ROOT unset. If the import probe is NO-GO (a trio symbol was renamed), do not fork — fall back to degraded mode.

### DEGRADED prose mode (no Node)

Run a best-effort sequential audit: a reviewer pass, an independent second reviewer, a separate judge pass, repeat until no new AXIS finding. Stamp the deliverable with the engine's literal honesty stamp: "schema conforms; adversarial verification did NOT run"; force cross_model:false; the word "parity" is FORBIDDEN in any prose-mode surface.

---

## Deliverables — three summary levels (one ledger)

Build the findings + sources ledger first; render full report / executive / agent-implementation as parallel projections. In ENGINE mode each carries the round history, Judge verdict, convergence proof, calibration state, and the separate Synthesizer Brief. In DEGRADED mode those are null and the honesty stamp leads every surface. Every deliverable carries the ISOLATION and mode (engine|degraded) stamps.

Never flatter, never hallucinate a source, never count popularity as truth, never claim a mitigation the run did not perform.

## Reserved / HALT-worthy

The attested-lineage enum membership, the pre-registered thresholds (G / X% / C_min / N / K / M / T / N_min), and any change to the locked North Star / invariants are human calls — HALT for a human.
> **⏱ STATUS UPDATES TO CHAT:** When running a long research phase in the background, you MUST arm a 10-minute cadence (`ScheduleWakeup` ~600s, AT LAUNCH) and post scheduled updates in the LOCKED Status-table format — canonical definition in ONE place: user-global `AGENTS.md` → "Long-run progress updates" (`[HH:MM]` header · Effort/Doing/Status/Tests/Blocker/Procs/**Journal** rows · ETA + To do footer). The **Journal** row (mandatory, `none` when empty) recaps everything journaled since the last tick — the SESSION composes it from this skill's `journal/`.

## Usage journal (sleep-loop feed — append after every REAL run)

At the end of any real (non-test) run of this skill, append ONE entry to
`journal/` in this skill folder as `NNNN-<slug>.md` (next number; APPEND-ONLY —
a correction is a new entry, never an edit). Keep it under ~15 lines, honest over
polished, with the 7 canonical fields (see the Skill Foundry's
`planning/portfolio-program/src/journal.mjs`): id, skill, situation, context,
observation, outcome (worked | friction | failed | refused), provenance
(genuine-execution | seeded — only genuine-execution corroborates).
No journal entries → the sleep loop has nothing to learn from.
