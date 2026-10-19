# Anchor R&D Surface v9 — "Tidy" — Master Plan (frozen design)

*Lane: planning · validated, cached summary*

**When run:** 2026-06-17

**What was asked:** Anchor R&D Surface v9 — "Tidy" — Master Plan (frozen design)

**North Star:** Make the R&D surface **tidy and organizable** — the user can permanently remove what they don't want and arrange what they keep: 1. **True session delete.** A red **✕** (top-right of a session tile) → "are you sure?" → the session is **completely gone and stays gone across a refresh**: the registry record (`remove_session`), the lane effort pointer-records + index entries, and the cached summary are removed. **Produced documents are KEPT** (Option A — a delete removes the Anchor session, never the real committed work). Ghost/empty sessions (empty DONE records with no efforts) delete cleanly; a

## Actions & files produced

- Anchor R&D Surface v9 — "Tidy" — Master Plan (frozen design)
- Anchor R&D Surface v9 — "Tidy" — Implementation Plan (Foreman-ready)

**Effort:** imported — no run metrics

## Goal & key decisions

- ## Anchor R&D Surface v9 â€” "Tidy" â€” Planning Session Summary
- **Goal (North Star, locked from John's Stage-0 answers)**
- Make the R&D surface **tidy and organizable**: the user can permanently remove what they don't want and arrange what they keep.
- **Locked decisions (Stage-0 user gates)**
- **Session delete = Option A (remove-from-Anchor, KEEP documents).** A delete clears the registry record (`remove_session`), the lane effort pointer-records + index entries, and the cached summary â€” so the tile is gone permanently and survives a refresh â€” but **produced/committed documents are never deleted**.
- **Session delete UX:** a red **âœ•** at the top-right of a session tile â†’ "are you sure?" â†’ the session is completely gone and stays gone across a refresh. Ghost/empty sessions (empty DONE records with no efforts) delete cleanly.
- **Grass delete = full.** Removes the idea's pointer + index entry + refinements + dev-session map â€” all Anchor scratch, nothing committed.
- **Folders = Option C (drag-groups-instantly + ask-to-move-on-disk).** A drag always groups in the dashboard (safe, reversible); a dialog then offers "Move on disk + group" (the guarded atomic move) vs. "Just group".
- **Scope of the two member documents**
- The session produced a frozen-design **Master Plan** and a Foreman-ready **Implementation Plan** for v9.
- Delete is distinguished from kill: kill ends a *running* session; delete *removes the Anchor record entirely* (keeping the on-disk documents).
- Grouping (dashboard-only) is distinguished from the on-disk move (guarded, atomic, reversible) â€” grouping never touches disk by itself.
- The locked objective is to make the R&D surface **tidy and organizable** â€” the user can permanently remove what they don't want and arrange what they keep.
- **Key decisions (locked at Stage 0 by John's gates)**
- **Session delete = Option A (remove-from-Anchor, KEEP documents).** A red **âœ•** on a session tile â†’ "are you sure?" â†’ the session is permanently gone and stays gone across a refresh: the registry record (`remove_session`), the lane effort pointer-records + index entries, and the cached summary are all removed â€” but **produced/committed documents are never deleted**.
- **Ghost/empty sessions** (empty DONE records with no efforts) delete cleanly under the same path.
- **Grass delete = full.** Removing a grass idea clears the idea's pointer + index entry + refinements + dev-session map â€” all Anchor scratch, nothing committed.
- **Scope / structure of the plan**
- Frozen design captured across two member documents: the **Master Plan** (frozen design) and the **Implementation Plan** (Foreman-ready).

## Files

- [Anchor R&D Surface v9 — "Tidy" — Master Plan (frozen design)](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Frnd-v9%2FMASTER-PLAN.md)
- [Anchor R&D Surface v9 — "Tidy" — Implementation Plan (Foreman-ready)](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Frnd-v9%2FIMPLEMENTATION-PLAN.md)
