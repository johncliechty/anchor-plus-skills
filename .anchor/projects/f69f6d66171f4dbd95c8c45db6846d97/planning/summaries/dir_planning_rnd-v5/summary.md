# Anchor R&D Surface v5 — "Durable Work" — Master Plan (frozen design)

*Lane: planning · validated, cached summary*

**When run:** 2026-06-14

**What was asked:** Anchor R&D Surface v5 — "Durable Work" — Master Plan (frozen design)

**North Star:** > Scope note: this wave ALSO delivers a user request raised mid-build — "project- > window changes should reflect on the main dashboard timely" — folded in here > because it touches the same dashboard-row/summary render path. - **EXECUTE** (fresh sub-agent): PART 1 — `summarizer.project_extraction_seed` adds per-lane activity; `_project_seed_prompt` rewritten to ask for a grounded 1-2 sentence OBJECTIVE; `render_project_markdown` → prose `## Objective`; project header renders the cached `Objective:` line; render path is cache-only (proven by stub-counter). PART 2 (folded) — read-only `GET /api

## Actions & files produced

- Anchor R&D Surface v5 — "Durable Work" — Execution Log
- Anchor R&D Surface v5 — "Durable Work" — Master Plan (frozen design)
- Anchor R&D Surface v5 — "Durable Work" — Implementation Plan (Foreman-ready)

**Effort:** imported — no run metrics

## Goal & key decisions

- # Anchor R&D Surface v5 â€” "Durable Work" â€” Planning Trio Summary
- **North Star (locked):** Make every R&D session and idea a durable, resumable, well-summarized unit of work â€” closing a session never loses it (it stays a reopenable tile); a *separate* deliberate action kills it.
- **Past-session view = real summary + continue-live:** Opening a done/historical session shows the skill invoked, the prompts/turns asked, and the actions/files produced, with one click to continue it in a fresh live session seeded from that context.
- **Grass Catcher = filterable two-pane idea workbench:** Ideas carry stable ids and a rawâ†’refinedâ†’promoted status, are developed in-place with Research/Plan, versioned, and pulled into other efforts.
- **Locked decision #1 â€” close-to-tile vs. deliberate kill:** The panel's X closes the panel but KEEPS the session as a reopenable tile (record persists; a running session keeps running, a done one stays done). A separate, clearly-distinct control hard-KILLS the session (terminate + remove worktree + drop the tile) behind an "Are you sure?" confirm â€” the two are visually and behaviorally distinct, and closing must never lose work.
- **Locked decision #2 â€” past-session view:** Opening a done/historical session surfaces a real summary (skill invoked, prompts/turns asked, actions/files produced).
- **Wave 3 â€” Better project summaries (objective/purpose):** Improve `summarizer.summarize_project` with a stronger seed (CLAUDE.md / README / Anchor.md + newest plan docs + pinned deliverables + per-lane activity) and a prompt that yields a 1â€“2 sentence objective/task/purpose summary, grounding-filtered; cache to `.anchor/projects/<id>/project-summary.*` (generate-once on rescan; `force` regenerates; a failed run never poisons the cache).
- **Wave 3 â€” cache-only render:** The dashboard row (`render_project_tile_html`) and project header READ the cache only â€” no synchronous model run on render; generation runs in the background on `rescan`.
- **Wave 3 â€” folded-in dashboard reflection (GREEN 2026-06-14):** This wave also delivered a mid-build user request â€” "project-window changes should reflect on the main dashboard timely" â€” folded in here because it touches the same dashboard-row/summary render path.
- **Wave 3 EXECUTE (fresh sub-agent), PART 1:** `summarizer.project_extraction_seed` adds per-lane activity; `_project_seed_prompt` rewritten to ask for a grounded 1â€“2 sentence OBJECTIVE; `render_project_markdown` â†’ prose `## Objective`; the project header renders the cached `Objective:` line; render path proven cache-only via a stub-counter. PART 2 (folded): a read-only `GET /api/...` endpoint for in-place dashboard refresh.
- **Member documents:** the v5 Master Plan (frozen design), the Implementation Plan (Foreman-ready), and the Execution Log.
- # Anchor R&D Surface v5 â€” "Durable Work" â€” Planning Session Summary
- **North Star (locked):** Make every R&D session and idea a durable, resumable, well-summarized unit of work â€” closing a session never loses it (it stays a reopenable tile), while a *separate* deliberate action kills it.
- **Past-session view:** Opening a done/historical session shows a real summary â€” the skill invoked, the prompts/turns asked, and the actions/files produced â€” with one click to continue it in a fresh live session seeded from that context.
- **Grass Catcher:** Becomes a filterable two-pane idea workbench â€” ideas carry stable ids and a rawâ†’refinedâ†’promoted status, are developed in-place with Research/Plan, versioned, and pulled into other efforts.
- **Locked decision #1 â€” run lifecycle (close-to-tile vs. deliberate kill):** The panel's X closes the panel but keeps the session as a reopenable tile (record persists; a running session keeps running, a done one stays done). A separate, clearly-distinct control hard-kills (terminate + remove worktree + drop the tile) behind an "Are you sure?" confirm. The two are visually and behaviorally distinct; closing must never lose work.
- **Locked decision #2 â€” past-session view = real summary + continue-live:** Opening a done/historical session surfaces the skill invoked and the prompts/turns asked (continued in the member docs).
- **Wave 3 â€” Better project summaries (objective/purpose):** Improve `summarizer.summarize_project` with a stronger seed (CLAUDE.md / README / Anchor.md + newest plan docs + pinned deliverables + per-lane activity) and a prompt that yields a 1â€“2 sentence objective/task/purpose summary, grounding-filtered.
- Cache to `.anchor/projects/<id>/project-summary.*` â€” generate-once on rescan, `force` regenerates, a failed run never poisons the cache.
- The dashboard row (`render_project_tile_html`) and project header read the cache only â€” no synchronous model run on render; generation runs in the background on `rescan`.
- **Wave 3 status â€” GREEN (2026-06-14):** Also delivered a mid-build user request â€” "project-window changes should reflect on the main dashboard timely" â€” folded in here because it touches the same dashboard-row/summary render path.
- **PART 1:** `summarizer.project_extraction_seed` adds per-lane activity; `_project_seed_prompt` rewritten to ask for a grounded 1â€“2 sentence objective; `render_project_markdown` â†’ prose `## Objective`; project header renders the cached `Objective:` line; render path is cache-only (proven by a stub-counter).
- **PART 2 (folded):** a read-only `GET /api/...` endpoint for in-place dashboard-row refresh after a background summary lands.
- **Member documents:** Master Plan (frozen design), Implementation Plan (Foreman-ready), and Execution Log â€” i.e. this was a full planning trio (Crucible-planned, Foreman-built) session.

## Files

- [Anchor R&D Surface v5 — "Durable Work" — Execution Log](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Frnd-v5%2FEXECUTION-LOG.md)
- [Anchor R&D Surface v5 — "Durable Work" — Master Plan (frozen design)](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Frnd-v5%2FMASTER-PLAN.md)
- [Anchor R&D Surface v5 — "Durable Work" — Implementation Plan (Foreman-ready)](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Frnd-v5%2FIMPLEMENTATION-PLAN.md)
