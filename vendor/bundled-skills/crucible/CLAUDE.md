# CLAUDE.md — Crucible

Orientation for any coding-agent session opened in `C:\dev\crucible`. Read first.

## What this is
**Crucible** = the **planning brain** of John's skill trio: **researchPrime** (research) → **Crucible** (planning) → **Foreman** (build). A **standalone** skill that turns an intent (or a messy existing project) into a vetted, **gold-standard, Foreman-ready implementation plan**, without drifting from the project's locked objective.

**Status (2026-06-05):** Master Plan v4.1 APPROVED (3 dry-converged rounds). **Stage-2 Implementation Plan CONVERGED** (v2.2, 11 waves; Stage-2 Shark-Tank rounds 2 & 3 both dry; passes Foreman's well-formedness gate). **Awaiting user approval to start the autonomous Foreman build** (first real code). Engine not built yet. Decisions D1–D18 — see `DECISION-LOG.md`.

## Two guiding principles
- **The inclusion test (size rule):** every element must serve a North-Star criterion; growth that serves the objective is welcome, only non-serving bloat is cut/Grasscatched. (Not brevity-for-its-own-sake.)
- **The Parable of the Oranges (real-intent foresight):** probe for the real goal, bring expertise, think 2–3 steps ahead, add justified value, show the receipt — in Stage-0 framing, Stage-1 brainstorming, and the Synthesizer's suggesting.

## The current plan (sharp version)
- **Three stages, each you-approve:** **Stage 0 Intake & Framing** (greenfield Oranges framing OR tiered brownfield ingest → candidate North Star → **you lock it**) → **Stage 1 Master Plan** (Oranges brainstorm → phased plan w/ near-term specifics → sharkfood to convergence → **you approve**) → **Stage 2 Implementation Plan** (decompose → Foreman doc-trio w/ per-wave acceptance criteria → sharkfood → **you approve** → well-formedness gate → Foreman). **You are the convergence authority.**
- **Shark Tank** = the adversarial review round (you "sharkfood" a draft). 3 Sharks (fresh context, refute-prompted, North-Star-anchored, rotating PM's 8 critique angles): Skeptic / Contrarian / Analyst. BLOCKER needs ≥2 to agree.
- **The Synthesizer** = a persistent Deep-Think Director, separate from the Sharks: Stage-0 framing + between-round direction + Oranges suggesting. It **steers but does NOT decide** — the decider is the cross-model judge + you. One **fresh-eyes anti-anchoring pass** before each lock. Best-available reasoning model, else the deep-think skill (stamped).
- **Anti-drift pillar:** locked North Star; goal-tagged changes; **tiered** guard; on drift two options — out-of-scope → **Grasscatcher**, or refinement → North-Star amendment. Drift detection starts after the lock. Every sub-agent prompt embeds the North Star.
- **Convergence:** sharkfood-until-dry + judge + your approval; cap = safety ceiling. **Two gates:** well-formedness (machine — **spawn** Foreman's contract resolver, exit 0) vs quality (Shark + fresh-eyes + judge + you, backed by per-wave acceptance criteria).
- **Substrate (two modes):** *Default* (subscription-only) — fresh-context Sharks + a **same-model fresh-context Judge persona** as the model-side decider. *Enhanced* (API keys/CLIs present) — a cross-model Judge at the lock gate + a true reasoning model for the Synthesizer. Every run stamps which model filled which role.
- **Architecture:** standalone skill, **Node engine** (Foreman sibling) — **imports** Foreman's `foreman-lib` durability code (the resolver is a **spawned CLI**), never forks; autonomous between gates; HALT gates at every approval; checkpoint/resume. Remote = GitHub private, push at gates with your OK.

## Key files
- `MASTER-PLAN.md` — full current plan (v4, live truth). Prior: `plans/proto/master-plan-v{1,2,3}.md`.
- `DECISION-LOG.md` — D1–D14 + round-1/2 amendments.
- `GRASSCATCHER.md` — idea-catcher backlog.
- `plans/debates/round-{1,2}/SYNTHESIS.md` — Shark-Tank verdicts.
- `plans/research/round-2/` — Lane E (brownfield ingest), Lane F (persistent Deep-Think). Round-1 research: `C:\dev\researchOne-out\crucible-planning-skill-20260604\`.
- `CLAUDE_hist.md` — dated history.

## Building Crucible (the Foreman run)
The plan is converged + Foreman-ready (passes `node C:/dev/foreman/bin/locate-plan.mjs --json .`). Build harness: **`C:\dev\foreman-targets\_crucible-run.mjs`** — binds `agent()` to headless `claude -p` on the subscription (no API key); git ON, branch `foreman/run`, never pushes; containment-safe (crucible is a sibling of foreman). Commands:
- `node C:/dev/foreman-targets/_crucible-run.mjs --smoke` — wiring check (passed 2026-06-05).
- `node C:/dev/foreman-targets/_crucible-run.mjs --max-waves=1` — **proving wave** (Wave 1 only); recommended first.
- `node C:/dev/foreman-targets/_crucible-run.mjs --resume` — continue remaining waves.
- `node C:/dev/foreman-targets/_crucible-run.mjs` — full autonomous (all 11 waves).

Live progress → `C:\dev\foreman-targets\_crucible-status.log`. Code lands in `bin/` + `test/` on branch `foreman/run`; Foreman commits per GREEN wave. Halts on blocker/budget/Pro-window → re-run with `--resume`. NOTE: launching an autonomous agent loop requires an explicit human go — an agent cannot self-launch it (the auto-mode classifier blocks that); run it via the `!` prefix or grant a Bash permission rule.

## Standing rules
- Production-only — no pedagogy/education content.
- Never push to a remote without explicit permission (push only at approval gates, asking each time).
- Reuse (import) Foreman/researchPrime/PM machinery; don't reinvent or fork. The inclusion test governs what goes in.
