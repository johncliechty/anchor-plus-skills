# Anchor R&D Surface v7 — "Integrated Board" — Master Plan (frozen design)

*Lane: planning · validated, cached summary*

**When run:** 2026-06-15

**What was asked:** Anchor R&D Surface v7 — "Integrated Board" — Master Plan (frozen design)

**North Star:** Make the project board an **honest, integrated, well-summarized view of all work**: 1. **Short, clean summaries.** Every *displayed short* summary (the project objective line, the per-tile blurb) is length-capped and **scrubbed of markdown/decorative glyphs** (`**`, `—`, `##`, backticks, the `✓` greeting, etc.). Full markdown stays only on the dedicated summary page. 2. **Live sessions live in their lane column.** A session started in research / plan / build / deliverables appears **as a tile in its lane column on the board the moment it starts** (green = running) and **stays there when done**

## Actions & files produced

- Anchor R&D Surface v7 — "Integrated Board" — Master Plan (frozen design)
- Anchor R&D Surface v7 — "Integrated Board" — Implementation Plan (Foreman-ready)
- Anchor R&D Surface v7 — "Integrated Board" — Execution Log

**Effort:** imported — no run metrics

## Goal & key decisions

- **North Star (locked from John's Stage-0 answers):** make the project board an honest, integrated, well-summarized view of all work â€” short/clean summaries, live sessions shown in their lane columns, every session summarized on finish, and a one-click bare terminal.
- **Decision #1 â€” short + clean summaries:** add a plain-text normalizer that strips markdown (`**`, `##`, backticks, link syntax) and decorative glyphs (`â€”`, `âœ“`, etc.) from any *short displayed* summary, with length caps (objective â‰ˆ 1 sentence; per-tile blurb ~8â€“12 words). Generate-twice + grounding are retained. Full markdown survives only on the dedicated `/summary` page.
- **Decision #2 â€” live sessions in their lane column (Option B, approved):** session tiles appear in BOTH places. The top active strip keeps currently-running sessions; AND every session appears as a tile in its research/plan/build/deliverables lane column the moment it starts (green = running) and persists when done â€” newest prominent, older sessions collapsed under an openable "previous sessions" expander (the v6 pattern).
- **Scope framing:** v7 "Integrated Board" extends existing v4/v5/v6 seams â€” no new modules â€” building on master with v6 already merged.
- **Member documents grounding this session:** the frozen Master Plan (design), the Foreman-ready Implementation Plan, and the Execution Log.
- **Provenance note:** these claims are anchored to the Master Plan's locked North Star and Stage-0 locked decisions; the implementation details (waves, summarize-on-finish hook, bare `general` lane) live in the companion Implementation Plan and Execution Log rather than being restated in this design-doc summary.
- ## Anchor R&D Surface v7 â€” "Integrated Board" â€” Planning Summary
- **Goal / North Star (locked from John's Stage-0 answers)**
- Make the project board an *honest, integrated, well-summarized* view of all work â€” driven by four locked decisions.
- **#1 â€” Short, clean summaries:** every *displayed short* summary (the project-objective line and the per-tile blurb) is length-capped and scrubbed of markdown + decorative glyphs (`**`, `â€”`, `##`, backticks, the `âœ“` greeting, etc.). Full markdown survives only on the dedicated `/summary` page.
- **#2 â€” Live sessions in their lane column (Option B):** a session started in research/plan/build/deliverables appears as a tile in its lane column the moment it starts (green = running) and persists when done â€” newest prominent, older under an openable "previous sessions" expander (the v6 pattern); the top active strip *also* stays for currently-running sessions (tiles in both places).
- **#3 â€” Summarize each session on finish.**
- **#4 â€” Bare "Open terminal" general session = a lane NOT in the board columns.**
- **Scope discipline (frozen design)**
- v7 EXTENDS the existing v4/v5/v6 seams over **5 waves** â€” **no new modules**.
- Verification standard carried forward (the v4 lesson, non-negotiable): each UI wave needs rendered-DOM assertions (positive + negative) + a real Playwright+Chromium interaction test + an orchestrator screenshot against the rnd-v7 mockup + John's sign-off. Playwright stays DEV-ONLY (`pytest.importorskip`), never imported by product code.
- **Wave-by-wave plan (Implementation Plan)**
- **Wave 1 (#1, `summarizer.py`):** `short_summary_text(...)` plain-text normalizer (strips markdown control sequences + a decorative-glyph set, collapses whitespace, caps on a word boundary with ellipsis) + tighter `tile_blurb(...)`; applied only at short display sites; a clean in-cap sentence is returned unchanged.
- **Wave 2 (#3):** `anchor_gui._trigger_session_summary_on_finish` schedules a **background** session summary on terminal-state transitions (`term_kill` / `finish_to_build` / `reconcile_and_advance`) â€” non-blocking, idempotent, a failed gen never poisons the cache; `summarizer.session_blurb(...)` returns the short clean one-liner (read-only, never runs the model).
- **Wave 3 (#2):** `_gather_project_sessions` / `_merge_registry_sessions` bridge live `session_registry` sessions into the trio lane columns, **deduped by `session_id`** (live status wins), newest-first; `general`/`grass` excluded via `_REGISTRY_LANE_TO_COLUMN`; render stays cache/registry-only (no model call).
- **Wave 4 (#4):** "Open terminal" starts a bare `general` session â€” a valid lane intentionally absent from `LANE_SKILL` (so `seed_for_lane('general')` is `None` â†’ bare PTY), excluded from the trio columns and the auto-advance chain; summarizable/continuable like any session.
- **Wave 5 (PROJECT DONE):** CLI mirror `rnd blurb <pid> --lane --session` â†’ `summarizer.session_blurb` (read-only, cache-only, honest "(no summary yet)"); `check_rnd_v7_surface` healthcheck walks the surface fully stubbed (stub PTY + stream-json stub runner + temp worktree base + throwaway git project), restores all forced env, never binds `:8777`; `distro.py` import scan stays clean.
- BUILT by Foreman â€” all 5 waves on branch `foreman/rnd-surface-v7` (off master, which has v6 merged), reported **GREEN 879**.
- **Status caveat (grounded):** NOT merged to master and not yet deployed â€” awaiting John's UI sign-off; deploy steps after sign-off are merge â†’ `nssm restart anchor` (elevated) â†’ rescan to heal summaries.
- This is a read-only summary of the frozen planning docs â€” no files were changed. Want me to also save a memory pointer or kick off the merge/deploy once you've signed off on the UI waves?

## Files

- [Anchor R&D Surface v7 — "Integrated Board" — Master Plan (frozen design)](/artifact/2fe37f39157f4c7aa3e2523baa41f40f?path=planning%2Frnd-v7%2FMASTER-PLAN.md)
- [Anchor R&D Surface v7 — "Integrated Board" — Implementation Plan (Foreman-ready)](/artifact/2fe37f39157f4c7aa3e2523baa41f40f?path=planning%2Frnd-v7%2FIMPLEMENTATION-PLAN.md)
- [Anchor R&D Surface v7 — "Integrated Board" — Execution Log](/artifact/2fe37f39157f4c7aa3e2523baa41f40f?path=planning%2Frnd-v7%2FEXECUTION-LOG.md)
