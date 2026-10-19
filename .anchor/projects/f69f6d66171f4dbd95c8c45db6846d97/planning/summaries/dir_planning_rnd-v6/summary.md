# Anchor R&D Surface v6 — "Linked Pipeline" — Master Plan (frozen design)

*Lane: planning · validated, cached summary*

**When run:** 2026-06-15

**What was asked:** Anchor R&D Surface v6 — "Linked Pipeline" — Master Plan (frozen design)

**North Star:** Make the researchPrime → Crucible → Foreman trio a **single linked pipeline of first-class session windows, backed by summaries that are actually true and a main dashboard that reflects live project work.** Concretely: 1. **Every session is a first-class window.** A research, planning, or build session opens as a window the user can **minimize, freely resize, and maximize** (plus the v5 close-to-tile and hard-kill). Windows **stack in a column** (not floating). 2. **Every new session mints a new tile.** Starting a session ALWAYS adds a new tile to the tiles row — it never silently reuses or re

## Actions & files produced

- Anchor R&D Surface v6 — "Linked Pipeline" — Execution Log
- Anchor R&D Surface v6 — "Linked Pipeline" — Master Plan (frozen design)
- Anchor R&D Surface v6 — "Linked Pipeline" — Implementation Plan (Foreman-ready)

**Effort:** imported — no run metrics

## Goal & key decisions

- ## Anchor R&D Surface v6 â€” "Linked Pipeline" â€” Planning Session Summary
- **Goal / North Star (locked)**
- The session's locked objective is to make the researchPrime â†’ Crucible â†’ Foreman trio a **single linked pipeline of first-class session windows**, backed by summaries that are actually true and a main dashboard that reflects live project work.
- Every research, planning, or build session is to open as a **first-class window** the user can minimize, freely resize, and maximize â€” on top of the v5 close-to-tile and hard-kill behaviors.
- Session windows **stack in a column** (not floating), and **every new session mints a new tile** â€” a session start never silently reuses an existing tile.
- **Key decisions (Stage 0/1 user gates, from John's answers on the mockup)**
- **Window controls = minimize Â· resize Â· maximize Â· close Â· kill, STACKED.** Each session window gains **maximize** (fill the cockpit viewport, toggle to restore) and **free resize** (drag any edge/corner) on top of the existing minimize, close-to-tile (keeps the session running), and hard-kill.
- Layout stays the **v5 stacked panel column** â€” explicitly NOT floating/draggable windows (John: "Stacked is fine for tiles.").
- **New session â‡’ new tile, always** â€” every session-start path (`term_start`, continue, advance, promote-grass, grass-develop) mints a distinct tile.
- **Artifacts produced (frozen design set)**
- **Master Plan** (frozen design) â€” this document.
- **Implementation Plan** (Foreman-ready) â€” the buildable wave breakdown.
- **Execution Log** â€” per-wave EXECUTE/REVIEW/FIX/JUDGE history.
- This is a discovered/imported planning trio session; the summary is grounded in the three member documents (Master Plan, Implementation Plan, Execution Log) and the cited Stage 0/1 gate anchors.
- **North Star (locked):** Make the researchPrime â†’ Crucible â†’ Foreman trio a **single linked pipeline of first-class session windows**, backed by summaries that are actually true and a main dashboard that reflects live project work.
- **Every session is a first-class window:** A research, planning, or build session opens as a window the user can **minimize, freely resize, and maximize** â€” on top of the existing v5 close-to-tile and hard-kill controls.
- **Windows stack in a column** (not floating/draggable) â€” John's gate: "Stacked is fine for tiles."
- **Every new session mints a new tile:** Every session-start path (`term_start`, continue, advance, promote-grass, grass-develop) always adds a **distinct new tile** to the tiles row â€” it never silently reuses an existing one.
- **Window controls = minimize Â· resize Â· maximize Â· close Â· kill, stacked** (locked Stage 0/1 user gate): maximize fills the cockpit viewport and toggles to restore; free resize drags any edge/corner; layout remains the v5 stacked panel column.
- **Member documents** for this planning trio session: the v6 **Master Plan** (frozen design), the **Implementation Plan** (Foreman-ready), and the **Execution Log**.

## Files

- [Anchor R&D Surface v6 — "Linked Pipeline" — Execution Log](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Frnd-v6%2FEXECUTION-LOG.md)
- [Anchor R&D Surface v6 — "Linked Pipeline" — Master Plan (frozen design)](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Frnd-v6%2FMASTER-PLAN.md)
- [Anchor R&D Surface v6 — "Linked Pipeline" — Implementation Plan (Foreman-ready)](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Frnd-v6%2FIMPLEMENTATION-PLAN.md)
