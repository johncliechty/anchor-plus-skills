# rnd-v11.1

*Lane: build · validated, cached summary*

**When run:** 2026-06-20

**What was asked:** rnd-v11.1

## Actions & files produced

- Anchor R&D Surface v11.1 — "Handoff Always Primes" — Execution Log

**Effort:** imported — no run metrics

## What was built & errors overcome

- ## rnd-v11.1 â€” "Handoff Always Primes" â€” Build Session Summary
- **Objective (delivered):** Close the v11 keystone's last gap â€” advancing a research session whose work lived only as a *terminal conversation* (no written file) used to refuse or open a misleading prompt; v11.1 makes the handoff always prime the next stage with a real, readable artifact. All 3 waves GREEN; branch `foreman/rnd-surface-v11.1` cut off master `b6719bd` (baseline GREEN 1232).
- **Wave 1 (keystone, 3 iters) â€” GREEN 1254.** `prepare_stage_handoff` gained a synchronous transcript snapshot: when the initial persist produced no doc-classified file, it reads the source PTY buffer (`read_since(sid,0)`), cleans it, writes `<source_worktree>/<lane>/<sid[:12]>-transcript.md`, re-persists it session-tagged, and names it in the prompt. Best-effort, never-raises, fires only when no file was produced. `handoff.build_next_stage_prompt`'s no-docs fallback was rewritten honest+actionable ("create the materials", no false "report in worktree").
- **Wave 1 adversarial review caught a stub-blind-spot (the v11 lesson recurring).** Reviewer B blocked: the first cleaner was stub-adequate but real-ConPTY-inadequate (`\r`-replace expanded spinner redraws; byte-exact seed-strip failed on wrapped output; background-refine was dead in prod because it gated on env `ANCHOR_PROACTIVE_SUMMARY` that `main()` never exported; 32KB tail-only cap dropped early framing). Judge: NO-GO on the green.
- **Wave 1 fixes.** Rewrote `_clean_transcript_text` into a 6-stage real-ConPTY pipeline (redraw frame-collapse â†’ broadened ANSI/CSI/OSC/DCS strip â†’ wrap-tolerant seed/greet strip â†’ chrome drop â†’ dup-line collapse â†’ HEAD+TAIL cap). `anchor_gui.main()` now exports `ANCHOR_PROACTIVE_SUMMARY=1`. Iter 2 fixed a real prod double-summary the live env-gate exposed: `_trigger_background_source_summary` now skips a TERMINAL source (the finish hook owns it) and fires only for a LIVE source.
- **Wave 2 (grass, 2 iters) â€” GREEN 1260; John signed off 2026-06-20.** Removed the `no-research-material` hard-refusal so `advance_grass_research_to_plan` always falls through to the v10 contained-grass mint/focus/link machinery with the transcript-backed (or honest-minimal) prompt; kept the `no-research-session` negative.
- **Wave 2 review caught an ordering bug.** Develop-plan-first + conversation-only: the transcript was committed to main HEAD and named in the prompt, but the pre-existing plan worktree was cut *before* the commit â†’ file absent from its checkout â†’ Crucible file-not-found. Fix: `_materialize_handoff_into_plan_worktree` copies the persisted transcript into the plan worktree and writes HANDOFF.md + NEXT-PROMPT.md there (matching the non-grass path), wired into both fresh-mint and focused-existing branches; a new test asserts `(plan_wt/rel).is_file()` and fails pre-fix.
- **Wave 3 (PROJECT DONE) â€” GREEN 1266.** `anchor_healthcheck.check_rnd_v11_1_surface` (registered in `main()`) walks the real conversation-only flow fully stubbed â€” seeds the stub PTY buffer (no file/`record_effort`/kill), asserts the transcript is snapshotted+persisted+committed+named and idempotent for researchâ†’plan, and materialized on disk in the plan worktree for grass; saves/restores `ANCHOR_PROACTIVE_SUMMARY` in an unconditional finally.
- **Status:** branch ready for merge + deploy; **no merge / no `nssm restart` until John signs off the whole branch.** (Per memory, this was subsequently merged + deployed 2026-06-21, merge `f2e0e40`.)
- ## rnd-v11.1 â€” "Handoff Always Primes" â€” Build Trio Summary
- **Objective (delivered):** Close the v11 keystone's last gap â€” a research session whose work lived only as a terminal **conversation** (no written file). All 3 waves GREEN; branch `foreman/rnd-surface-v11.1` ready for merge, awaiting John's whole-branch sign-off.
- **Wave 1 â€” transcript-snapshot keystone (backend, GREEN after 3 iters).** `prepare_stage_handoff` now synchronously snapshots the source PTY buffer (`read_since(sid,0)`) when the initial persist produced **no doc-classified file**, cleans it, writes `<source_worktree>/<lane>/<sid[:12]>-transcript.md`, re-persists it session-tagged, and builds a prompt that names the real path. Best-effort, never-raises, fires only in the no-doc case. `handoff.build_next_stage_prompt`'s no-docs fallback was rewritten **honest + actionable** ("create the materials" â€” never a false "report in worktree").
- **Wave 1 review caught a real stub blind-spot (the v11 lesson recurring).** Reviewer B found the first cleaner was **stub-adequate but real-ConPTY-inadequate** â€” `\r`-handling expanded spinner redraws, byte-exact seed-strip failed on wrapped output, the background-refine was dead in prod (gated on `ANCHOR_PROACTIVE_SUMMARY`, which `main()` never exported), and the 32KB tail-only cap dropped early framing. Judge: NO-GO.
- **Wave 1 fix.** Rewrote `_clean_transcript_text` as a **6-stage real-ConPTY pipeline** (redraw frame-collapse â†’ broadened ANSI/CSI/OSC/DCS strip â†’ wrap-tolerant seed/greet strip â†’ chrome drop â†’ dup-line collapse â†’ HEAD+TAIL cap). `anchor_gui.main()` now **exports `ANCHOR_PROACTIVE_SUMMARY=1`** so the refine runs in prod. A second gate iter caught a prod **double-summary regression** (kill fires both the finish hook and the keystone summary) â€” fixed by skipping a TERMINAL source in `_trigger_background_source_summary`. Gate of record: GREEN 1254.
- **Wave 2 â€” grass always proceeds (UI, GREEN after 2 iters).** Removed the `no-research-material` hard-refusal so `advance_grass_research_to_plan` falls through to the v10 W5 contained-grass machinery with the transcript-backed (or honest-minimal) prompt; kept the `no-research-session` negative. Review found an **ordering BLOCKER**: develop-plan-first + conversation-only committed the transcript to main HEAD but the pre-existing plan worktree was cut **before** the commit â†’ file absent â†’ Crucible file-not-found.
- **Wave 2 fix.** Added `effort_history._materialize_handoff_into_plan_worktree` â€” copies the persisted transcript/doc rels into the plan worktree + writes HANDOFF.md/NEXT-PROMPT.md (matching the non-grass path), wired into both fresh-mint and focused-existing branches. New test asserts `(plan_wt/rel).is_file()` â€” proven to fail pre-fix. Gate of record: GREEN 1260. **John signed off 2026-06-20** (saw a grass conversation advance to a plan session naming `research/<sid>-transcript.md`).
- **Wave 3 â€” healthcheck + docs (PROJECT DONE, GREEN).** `check_rnd_v11_1_surface` (registered in `main()`) walks the real conversation-only flow fully stubbed (`ANCHOR_PROACTIVE_SUMMARY` off+restored in the finally â€” load-bearing now that the keystone reads it): researchâ†’plan and grass both **seed the stub PTY buffer (no file)**, advance, and assert the transcript is snapshotted/persisted/committed/named (idempotent) and **materialized on disk** in the plan worktree. Final gate of record: **GREEN 1266 passed, 1 skipped**.
- 1. Cleaner was stub-only, useless on real ConPTY (caught at Wave-1 review â†’ 6-stage rewrite).
- 2. `ANCHOR_PROACTIVE_SUMMARY` never exported by `main()` â†’ background refine dead in prod (fixed).
- 3. Prod **double-summary** on planning-session kill (caught by a Wave-1 gate regression â†’ terminal-source skip).
- 4. Develop-plan-first grass handoff named a file absent from the plan worktree (caught at Wave-2 review â†’ `_materialize_handoff_into_plan_worktree`).
- **Status:** Built, not merged/deployed â€” no `nssm restart anchor` until John signs off the whole branch.

## Files

- [Anchor R&D Surface v11.1 — "Handoff Always Primes" — Execution Log](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Frnd-v11.1%2FEXECUTION-LOG.md)
