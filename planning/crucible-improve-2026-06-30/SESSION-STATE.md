# Crucible Session State — Anchor Improvement Effort

> ## ✅ BUILT 2026-07-01 — all 9 Foreman waves GREEN (final gate 274 passed, exit 0).
> Branch `foreman/crucible-improve-2026-06-30` in worktree `C:\dev\anchor-build-crucible`.
> **MERGE + DEPLOY PENDING (John):** merge → master + elevated `nssm restart anchor` +
> rescan. Then UI/live sign-offs: **W4** warm-resume + previous-efforts link · **W5**
> deliverables-collapse + terminal full-width · **W6** `×`=stop/preserve + one
> `Kill→Boneyard` (drop redundant controls) · **W8** model-flex fallback states · **W9**
> gandalf map-reduce findings — each Playwright + screenshot; PLUS **W2 #1** live
> orphan-banner check on gwl-server after restart (only warns on genuine orphans). See
> `EXECUTION-LOG.md` for the full wave/amendment history.

**Carry-on doc.** This is the resume point for a Crucible planning session on the
Anchor dashboard. If you opened this inside an Anchor plan-lane session, read all
three docs in this folder, then continue from "Next step" below.

- **Skill:** Crucible (planning brain of researchPrime → Crucible → Foreman).
- **Mode:** brownfield, depth **FULL**.
- **Date:** 2026-06-30.
- **Project:** Anchor (`C:\dev\Anchor`).

## Where we are (updated 2026-06-30, resumed inside Anchor worktree)
- **Stage 0 — Intake & Framing: COMPLETE.** North Star **LOCKED** (`NORTH-STAR.md`).
  Triage → **FULL**. Brownfield ingest done + **verified against code by 5 Gemini
  swarms** via `agy-dispatch` (the 5:1 pattern, live). Corrections in `DIAGNOSIS.md`.
- **Stage 1 — Master Plan: LOCKED.** `MASTER-PLAN.md` + Shark-Tank Round 1
  (`SHARK-TANK.md`): 2 BLOCKERs resolved (#1 fix was dangerous → reproduce-first; #10
  5:1 → skill/session layer, NOT Anchor's job_runner — user-decided). Scope now **13
  items** (added #12 zombie live-view, #13 Boneyard-button consistency).
- **Stage 2 — Implementation Plan: REVISED + machine-gated.** `IMPLEMENTATION-PLAN.md`
  (9 waves) + Stage-2 Shark-Tank (`S2-SHARK-TANK.md`): 5 BLOCKERs resolved (PTY
  re-adoption impossible → owner-liveness discriminator; reorder so keystone precedes
  UI; split keystone; `×`→stop+preserve not suspend; done-whens split into stub-gate +
  sign-off). `foreman.config.json` written; `locate-plan.mjs --json` → **exit 0**.
- **NEXT: user approves the Foreman handoff → invoke Foreman to build the 9 waves.**

## Doc-trio for Foreman
`MASTER-PLAN.md` (description) · `IMPLEMENTATION-PLAN.md` (plan, 9 waves) ·
`EXECUTION-LOG.md` (log). Config: `foreman.config.json`. Gate: `python -m pytest -q`.

## Honest caveats carried to the build
- **#1 (Wave 2)** banner-stops-live is a **post-deploy sign-off on gwl-server** (needs
  the elevated restart only the user runs) — the *design* is stub-tested, doesn't depend
  on it.
- **UI waves (4,5,6,8,9)** finish on a Playwright + screenshot + **user sign-off** (the
  v4 rule), not the headless gate alone.
- Deploy = one elevated `nssm restart anchor` after merge (user runs).

## Documents available
- `NORTH-STAR.md` — locked objective + 3 pillars (A resumable / B honest UI &
  warnings / C model-flexible execution) + 11-item scope.
- `DIAGNOSIS.md` — grounded per-item diagnosis + the reframes.
- `SESSION-STATE.md` — this file.

## Next step (Stage 1 — Master Plan)
Oranges brainstorm (assumption-map → premortem → ideate), batch-triage the 11 items
into phases mapped to pillars A/B/C, then run the Shark-Tank loop (3 fresh-context
Sharks; BLOCKER = ≥2 agree) to convergence, steered by the Synthesizer and decided
by the Judge + user. Two T2 reproduce-first targets must resolve during Stage 1:
the **swarm-warning emitter** (#1/#11) and the **context-window warning source**
(#7).

### Suggested phasing seed (to be vetted in Stage 1, not locked)
- **Phase 1 — Honest warnings (B):** reproduce + fix the swarm-warning false
  positive (orphan-only) and the context-window warning (suppress/contextualize).
  Lowest-risk, high daily-annoyance payoff.
- **Phase 2 — UI correctness (B):** previous-efforts link, deliverables collapse,
  terminal controls (remove redundant hard-kill, `×` = archive), terminal width.
- **Phase 3 — Resumable sessions (A) [keystone]:** promote discovered/brownfield
  efforts to first-class resumable sessions; restore phase + docs + skills + summary
  on resume; model-switch handoff doc.
- **Phase 4 — Gandalf map-reduce (B):** real fan-out/reduce + in-progress indicator.
- **Phase 5 — Model-flexible execution (C) [biggest build]:** Claude-orchestrates-
  Gemini 5:1 sub-agent substrate with single-subscription fallback (never
  cross-calling). Depends on the new Claude→Gemini sub-agent tool.

## Substrate note
The 5:1 Claude→Gemini sub-agent capability does NOT exist yet (it is item #10 / Phase
5). It is a build target, not a tool available to build this effort. Do not assume it
when planning the earlier phases.

## Open thread for the user
This effort was framed in the main workbench, then persisted here so it appears in
the Anchor project. The first real test of Pillar A is whether *this* session
resumes cleanly inside Anchor — skills loaded, these docs read, this summary
orienting the new turn. If it opens cold, that IS the bug Phase 3 fixes.
