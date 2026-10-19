# Anchor Brownfield Discovery — Master Plan (Crucible Stage 1, approved)

*Lane: planning · validated, cached summary*

**When run:** 2026-06-10

**What was asked:** Anchor Brownfield Discovery — Master Plan (Crucible Stage 1, approved)

**North Star:** When an R&D project is registered or opened on an existing folder, Anchor instantly (local, no tokens) discovers genuine pre-existing trio artifacts and adopts them so the dashboard populates (home R&D panel + tile rollup + project Kanban) — honestly: discovered items are excluded from the real effort count (shown as "M imported"), get no `vN` label, are clickable to their real on-disk file, and carry a subtle `imported` marker. Anchor also writes `Anchor.md` (human, structure-only, no-churn) + a machine sidecar describing the folder's R&D structure.

## Actions & files produced

- Anchor Brownfield Discovery — Master Plan (Crucible Stage 1, approved)
- Anchor Brownfield Discovery + `Anchor.md` Marker — Implementation Plan
- Brownfield Discovery — Execution Log

**Effort:** imported — no run metrics

## Goal & key decisions

- **North Star (locked):** When an R&D project is registered or opened on an existing folder, Anchor instantly â€” locally, with no tokens and no agent â€” discovers genuine pre-existing trio artifacts and adopts them so the dashboard populates (home R&D panel + tile rollup + project Kanban).
- **Honest adoption:** Discovered items are excluded from the real `effort_count` and shown separately as "M imported," get no `vN` label, are clickable to their real on-disk file, and carry a subtle `imported` marker (a small dot) â€” as understated as possible while staying honest (the user's Stage-1 ruling). They are never given fake provenance.
- **Markers written:** Anchor writes/maintains `Anchor.md` (human-readable, structure-only, no-churn / regenerated) plus a machine JSON sidecar describing the folder's R&D structure.
- **Scan triggers:** Discovery runs on project register, on `/project/<id>` open, and on a manual Rescan button.
- **Constraints (approved):** Python stdlib only; integrate with `rnd_registry` / `lanes` / `effort_history` / `anchor_gui` and the Kanban window; keep the 236-test suite green; commit-safe.
- **Member documents covered:** the Master Plan (Crucible Stage 1, approved), the Implementation Plan for Brownfield Discovery + the `Anchor.md` marker, and the Brownfield Discovery Execution Log.
- **North Star (locked):** When an R&D project is registered or opened on an existing folder, Anchor INSTANTLY discovers genuine pre-existing trio artifacts locally â€” no tokens, no agent â€” and adopts them so the dashboard populates (home R&D panel + tile rollup + project Kanban).
- **Honest adoption:** Discovered items are excluded from the real `effort_count` (shown separately as "M imported"), get NO `vN` label, are clickable to their REAL on-disk file, and carry a SUBTLE `imported` marker (a small dot) â€” never fake provenance.
- **Scan triggers (approved):** Discovery runs on project register, on `/project/<id>` open, and via a manual Rescan button.
- **Adoption model (approved decision):** Discovered artifacts are ADOPTED as efforts so the existing tile/Kanban readers fill in, but visibly/subtly labeled "imported" (Stage-1 ruling: as understated as possible while honest) and separately counted.
- **Implementation constraints (approved):** Python stdlib only; integrate with `rnd_registry` / `lanes` / `effort_history` / `anchor_gui` + the Kanban window; keep the 236-test suite green; remain commit-safe.
- **Member documents:** Master Plan (Crucible Stage 1, approved), the Brownfield Discovery + `Anchor.md` Marker Implementation Plan, and the Execution Log.

## Files

- [Anchor Brownfield Discovery — Master Plan (Crucible Stage 1, approved)](/artifact/2fe37f39157f4c7aa3e2523baa41f40f?path=planning%2Fbrownfield-discovery%2FMASTER-PLAN.md)
- [Anchor Brownfield Discovery + `Anchor.md` Marker — Implementation Plan](/artifact/2fe37f39157f4c7aa3e2523baa41f40f?path=planning%2Fbrownfield-discovery%2FIMPLEMENTATION-PLAN.md)
- [Brownfield Discovery — Execution Log](/artifact/2fe37f39157f4c7aa3e2523baa41f40f?path=planning%2Fbrownfield-discovery%2FEXECUTION-LOG.md)
