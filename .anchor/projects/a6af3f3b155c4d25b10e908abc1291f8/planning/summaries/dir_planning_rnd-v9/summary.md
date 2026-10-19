# Anchor R&D Surface v9 — "Tidy" — Master Plan (frozen design)

*Lane: planning · validated, cached summary*

**When run:** 2026-07-24

**What was asked:** Anchor R&D Surface v9 — "Tidy" — Master Plan (frozen design)

**North Star:** Make the R&D surface **tidy and organizable** — the user can permanently remove what they don't want and arrange what they keep: 1. **True session delete.** A red **✕** (top-right of a session tile) → "are you sure?" → the session is **completely gone and stays gone across a refresh**: the registry record (`remove_session`), the lane effort pointer-records + index entries, and the cached summary are removed. **Produced documents are KEPT** (Option A — a delete removes the Anchor session, never the real committed work). Ghost/empty sessions (empty DONE records with no efforts) delete cleanly; a

## Actions & files produced

- Anchor R&D Surface v9 — "Tidy" — Master Plan (frozen design)
- Anchor R&D Surface v9 — "Tidy" — Implementation Plan (Foreman-ready)

**Effort:** imported — no run metrics

## Goal & key decisions

- This planning session produced the frozen design and Foreman-ready implementation plan for Anchor R&D Surface v9, nicknamed "Tidy," whose goal is to let the user permanently remove what they don't want from the R&D surface and organize what they keep. The session opened by locking a North Star around three capabilities: a true session delete, a grass idea delete, and project folders. It then settled the key design questions through John's Stage-0 gate answers. Session delete was defined as "remove from Anchor, keep the documents" (Option A): clicking the red ✕ on a session tile and confirming clears the registry record, the lane effort pointer-records and index entries, and the cached summary, so the tile is gone and stays gone across a refresh, while any produced or committed work is never touched. Grass delete was defined as a full delete, since everything involved (the idea's pointer, index entry, refinements, and dev-session map) is Anchor scratch rather than committed work. Folders were defined as "drag groups instantly, ask before moving on disk" (Option C): dragging a project always regroups it in the dashboard, which is safe and reversible, and a dialog then offers either a guarded atomic on-disk move plus grouping or just the grouping. With those decisions fixed, the session carried the design through to a Master Plan and a wave-by-wave Implementation Plan that Foreman can execute directly.
- This planning session was a Crucible run that designed Anchor R&D Surface v9, nicknamed "Tidy," and carried it all the way from a locked North Star through a frozen Master Plan to a Foreman-ready Implementation Plan. The goal John set at Stage 0 was to make the R&D surface tidy and organizable, so a user can permanently remove what they don't want and arrange what they keep. The session locked three decisions that shape the whole feature. First, a session delete removes the session from Anchor but keeps its documents: clicking the red ✕ on a tile and confirming clears the registry record, the lane effort pointer records and index entries, and the cached summary, so the tile is gone and stays gone across a refresh, while any produced or committed work on disk is never touched. Ghost sessions, meaning empty finished records with no efforts, delete cleanly under the same rule. Second, deleting a grass idea is a full delete, since everything involved (the idea's pointer, index entry, refinements, and dev-session map) is Anchor scratch rather than committed work. Third, project folders use a drag-to-group model where a drag always regroups the project on the dashboard instantly and reversibly, then a dialog offers either "just group" or a guarded atomic move of the project folder on disk to match. The two member documents, the Master Plan and the Implementation Plan, capture that frozen design and break it into build waves so Foreman can execute it without further design decisions.

## Files

- [Anchor R&D Surface v9 — "Tidy" — Master Plan (frozen design)](/artifact/a6af3f3b155c4d25b10e908abc1291f8?path=planning%2Frnd-v9%2FMASTER-PLAN.md)
- [Anchor R&D Surface v9 — "Tidy" — Implementation Plan (Foreman-ready)](/artifact/a6af3f3b155c4d25b10e908abc1291f8?path=planning%2Frnd-v9%2FIMPLEMENTATION-PLAN.md)
