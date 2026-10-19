# Anchor R&D Surface v5 — "Durable Work" — Master Plan (frozen design)

*Lane: planning · validated, cached summary*

**When run:** 2026-06-14

**What was asked:** Anchor R&D Surface v5 — "Durable Work" — Master Plan (frozen design)

**North Star:** Make every R&D session and idea a **durable, resumable, well-summarized unit of work**. Closing a session never loses it (it stays a reopenable tile); a *separate* deliberate action kills it. Opening a past session shows a **real summary** — the skill invoked, the prompts asked, the actions/files produced — with one click to **continue it in a fresh live session** seeded from that context. The Grass Catcher is a **filterable two-pane idea workbench**: ideas carry stable ids and a raw→refined→promoted status, are developed in-place with Research/Plan, versioned, and pulled into other efforts. *

## Actions & files produced

- Anchor R&D Surface v5 — "Durable Work" — Master Plan (frozen design)
- Anchor R&D Surface v5 — "Durable Work" — Implementation Plan (Foreman-ready)
- Anchor R&D Surface v5 — "Durable Work" — Execution Log

**Effort:** imported — no run metrics

## Goal & key decisions

- **North Star (locked):** Make every R&D session and idea a durable, resumable, well-summarized unit of work â€” closing a session never loses it (it stays a reopenable tile), while a separate deliberate action kills it.
- **Past-session view:** Opening a done/historical session shows a real summary â€” the skill invoked, the prompts/turns asked, and the actions/files produced â€” with one-click "continue it in a fresh live session" seeded from that context.
- **Grass Catcher (locked):** A filterable two-pane idea workbench where ideas carry stable ids and a rawâ†’refinedâ†’promoted status, are developed in-place via Research/Plan, versioned, and pulled into other efforts.
- **Locked decision #1 â€” run lifecycle:** The panel's **X closes the panel but keeps the session as a reopenable tile** (record persists; running stays running, done stays done); a **separate, visually-distinct control hard-kills** (terminate + remove worktree + drop the tile) behind an "Are you sure?" confirm. Closing must never lose work.
- **Locked decision #2 â€” past-session view:** Opening a done/historical session surfaces a summary of the skill invoked and the prompts/turns asked, plus continue-live.
- **Wave 3 â€” better project summaries:** Improve `summarizer.summarize_project` with a stronger seed (CLAUDE.md / README / Anchor.md + newest plan docs + pinned deliverables + per-lane activity) and a prompt yielding a grounded 1â€“2 sentence objective/purpose summary, grounding-filtered, cached at `.anchor/projects/<id>/project-summary.*` (generate-once on rescan; `force` regenerates; a failed run never poisons the cache).
- **Wave 3 â€” render contract:** The dashboard row (`render_project_tile_html`) and project header **read the cache only** â€” no synchronous model run on render; generation runs in the background on `rescan`.
- **Wave 3 â€” status GREEN (2026-06-14):** Delivered in two parts â€” PART 1: `summarizer.project_extraction_seed` adds per-lane activity, `_project_seed_prompt` rewritten to ask for a grounded 1â€“2 sentence objective, `render_project_markdown` emits a prose `## Objective`, and the cache-only render path is proven by a stub-counter. PART 2 (folded in): a read-only `GET /api/...` endpoint addressing the mid-build user request that "project-window changes should reflect on the main dashboard timely," since it touches the same dashboard-row/summary render path.
- **Member documents:** Master Plan (frozen design), Implementation Plan (Foreman-ready), and Execution Log for Anchor R&D Surface v5 "Durable Work."
- Here is a grounded summary of the v5 "Durable Work" planning trio session, drawn only from the member documents:
- ## Anchor R&D Surface v5 â€” "Durable Work" â€” Planning Summary
- **North Star (locked)**
- Make every R&D session and idea a **durable, resumable, well-summarized unit of work**.
- Closing a session never loses it â€” it stays a **reopenable tile**; a *separate, deliberate* action kills it.
- Opening a past session shows a **real summary** (skill invoked Â· prompts asked Â· actions/files produced) with one click to **continue it in a fresh live session** seeded from that context.
- The Grass Catcher becomes a **filterable two-pane idea workbench**: ideas carry stable ids and a rawâ†’refinedâ†’promoted status, are developed in-place with Research/Plan, versioned, and pulled into other efforts.
- **Locked decisions (Stage 0/1 user gates)**
- **#1 â€” Run lifecycle = close-to-tile vs. deliberate kill.** The panel's **X closes the panel but KEEPS the session as a reopenable tile** (record persists; a running session keeps running, a done one stays done). A **separate, clearly distinct control hard-KILLS** (terminate + remove worktree + drop the tile) behind an "Are you sure?" confirm. The two are visually and behaviorally distinct â€” closing must never lose work.
- **#2 â€” Past-session view = real summary + continue-live.** Opening a done/historical session shows the skill invoked and the prompts/turns asked (continued in the docs).
- **Wave 3 â€” Better project summaries (objective/purpose)**
- Improve `summarizer.summarize_project`: a **stronger seed** (CLAUDE.md / README / Anchor.md + newest plan docs + pinned deliverables + per-lane activity) and a prompt yielding a grounded **1â€“2 sentence objective/purpose** summary, grounding-filtered.
- Cache `.anchor/projects/<id>/project-summary.*` â€” **generate-once on rescan**; `force` regenerates; a failed run never poisons the cache.
- The dashboard row (`render_project_tile_html`) and project header **READ the cache only** â€” no synchronous model run on render; generation runs in the background on `rescan`.
- **Wave 3 â€” Execution outcome (GREEN, 2026-06-14)**
- A mid-build user request â€” *"project-window changes should reflect on the main dashboard timely"* â€” was **folded into this wave** because it touches the same dashboard-row/summary render path.
- PART 1: `summarizer.project_extraction_seed` adds per-lane activity; `_project_seed_prompt` rewritten to ask for a grounded 1â€“2 sentence **OBJECTIVE**; `render_project_markdown` â†’ prose `## Objective`; project header renders the cached `Objective:` line; render path proven **cache-only** via a stub-counter.
- PART 2 (folded): a read-only `GET /api/...` endpoint (truncated in the anchor) supports timely in-place dashboard reflection.

## Files

- [Anchor R&D Surface v5 — "Durable Work" — Master Plan (frozen design)](/artifact/2fe37f39157f4c7aa3e2523baa41f40f?path=planning%2Frnd-v5%2FMASTER-PLAN.md)
- [Anchor R&D Surface v5 — "Durable Work" — Implementation Plan (Foreman-ready)](/artifact/2fe37f39157f4c7aa3e2523baa41f40f?path=planning%2Frnd-v5%2FIMPLEMENTATION-PLAN.md)
- [Anchor R&D Surface v5 — "Durable Work" — Execution Log](/artifact/2fe37f39157f4c7aa3e2523baa41f40f?path=planning%2Frnd-v5%2FEXECUTION-LOG.md)
