# Anchor R&D Surface v6 — "Linked Pipeline" — Master Plan (frozen design)

*Lane: planning · validated, cached summary*

**When run:** 2026-06-15

**What was asked:** Anchor R&D Surface v6 — "Linked Pipeline" — Master Plan (frozen design)

**North Star:** Make the researchPrime → Crucible → Foreman trio a **single linked pipeline of first-class session windows, backed by summaries that are actually true and a main dashboard that reflects live project work.** Concretely: 1. **Every session is a first-class window.** A research, planning, or build session opens as a window the user can **minimize, freely resize, and maximize** (plus the v5 close-to-tile and hard-kill). Windows **stack in a column** (not floating). 2. **Every new session mints a new tile.** Starting a session ALWAYS adds a new tile to the tiles row — it never silently reuses or re

## Actions & files produced

- Anchor R&D Surface v6 — "Linked Pipeline" — Master Plan (frozen design)
- Anchor R&D Surface v6 — "Linked Pipeline" — Implementation Plan (Foreman-ready)
- Anchor R&D Surface v6 — "Linked Pipeline" — Execution Log

**Effort:** imported — no run metrics

## Goal & key decisions

- **North Star (locked):** v6 "Linked Pipeline" makes the researchPrime â†’ Crucible â†’ Foreman trio a **single linked pipeline of first-class session windows**, backed by summaries that are actually true and a main dashboard that reflects live project work.
- **First-class session windows:** Every research, planning, or build session opens as a window the user can **minimize, freely resize, and maximize** (on top of the v5 close-to-tile and hard-kill controls).
- **Stacked layout, not floating:** Windows **stack in a column** rather than floating; John's gate confirmed "Stacked is fine for tiles" â€” layout stays the v5 stacked panel column, NOT floating/draggable windows.
- **New session â‡’ new tile, always:** Every session-start path (`term_start`, continue, advance, promote-grass, grass-develop) **mints a distinct new tile** in the tiles row â€” it never silently reuses or replaces an existing tile.
- **Window controls (locked decision #1):** Each session window gains **maximize** (fill the cockpit viewport, toggle to restore) and **free resize** (drag any edge/corner), added to the existing minimize, close-to-tile (keeps the session), and hard-kill.
- **Member document set:** This trio session is grounded in three frozen docs â€” the **Master Plan** (frozen design), the Foreman-ready **Implementation Plan**, and the **Execution Log**.
- **Stage gating:** The locked decisions originate from **John's Stage 0/1 user-gate answers on the mockup**, establishing the window-controls and one-tile-per-session contracts before build.
- Here is a grounded summary of the planning trio session, with each claim tied to the anchor text provided.
- ## Anchor R&D Surface v6 â€” "Linked Pipeline" â€” Master Plan (grounded summary)
- **North Star (locked)**
- The goal is to make the researchPrime â†’ Crucible â†’ Foreman trio a **single linked pipeline of first-class session windows**, backed by summaries that are **actually true** and a main dashboard that **reflects live project work**.
- **Every session is a first-class window:** a research, planning, or build session opens as a window the user can **minimize, freely resize, and maximize** â€” on top of the v5 close-to-tile and hard-kill controls.
- Windows **stack in a column** â€” they are explicitly **not** floating/draggable windows.
- **Every new session mints a new tile:** starting a session ALWAYS adds a new tile to the tiles row; it never silently reuses an existing one.
- **Locked decisions (Stage 0/1 user gates, from John's answers on the mockup)**
- **Window controls = minimize Â· resize Â· maximize Â· close Â· kill, STACKED.** Each session window gains **maximize** (fill the cockpit viewport, toggle to restore) and **free resize** (drag any edge/corner) on top of the existing minimize, close-to-tile (keeps the session alive), and hard-kill.
- Layout stays the **v5 stacked panel column** â€” not floating/draggable (John: *"Stacked is fine for tiles."*).
- **New session â‡’ new tile, always.** Every session-start path â€” `term_start`, continue, advance, promote-grass, grass-develop â€” mints a **distinct** tile that appears in the tiles row (none reuse or replace an existing tile).
- **Session scope**
- This is a **planning trio session** comprising three member documents: the **Master Plan** (frozen design), the **Implementation Plan** (Foreman-ready), and the **Execution Log**.

## Files

- [Anchor R&D Surface v6 — "Linked Pipeline" — Master Plan (frozen design)](/artifact/2fe37f39157f4c7aa3e2523baa41f40f?path=planning%2Frnd-v6%2FMASTER-PLAN.md)
- [Anchor R&D Surface v6 — "Linked Pipeline" — Implementation Plan (Foreman-ready)](/artifact/2fe37f39157f4c7aa3e2523baa41f40f?path=planning%2Frnd-v6%2FIMPLEMENTATION-PLAN.md)
- [Anchor R&D Surface v6 — "Linked Pipeline" — Execution Log](/artifact/2fe37f39157f4c7aa3e2523baa41f40f?path=planning%2Frnd-v6%2FEXECUTION-LOG.md)
