# Anchor Brownfield Discovery — Master Plan (Crucible Stage 1, approved)

*Lane: planning · validated, cached summary*

**When run:** 2026-06-10

**What was asked:** Anchor Brownfield Discovery — Master Plan (Crucible Stage 1, approved)

**North Star:** When an R&D project is registered or opened on an existing folder, Anchor instantly (local, no tokens) discovers genuine pre-existing trio artifacts and adopts them so the dashboard populates (home R&D panel + tile rollup + project Kanban) — honestly: discovered items are excluded from the real effort count (shown as "M imported"), get no `vN` label, are clickable to their real on-disk file, and carry a subtle `imported` marker. Anchor also writes `Anchor.md` (human, structure-only, no-churn) + a machine sidecar describing the folder's R&D structure.

## Actions & files produced

- Brownfield Discovery — Execution Log
- Anchor Brownfield Discovery — Master Plan (Crucible Stage 1, approved)
- Anchor Brownfield Discovery + `Anchor.md` Marker — Implementation Plan

**Effort:** imported — no run metrics

## Goal & key decisions

- **North Star (locked):** When an R&D project is registered or opened on an existing folder, Anchor instantly discovers genuine pre-existing trio artifacts locally â€” no tokens, no agent â€” and adopts them so the dashboard populates (home R&D panel + tile rollup + project Kanban).
- **Honest adoption:** Discovered items are excluded from the real `effort_count` (shown separately as "M imported"), receive no `vN` label, are clickable to their real on-disk file, and carry a subtle `imported` marker (a small dot) â€” never given fake provenance.
- **Marker outputs:** Anchor writes/maintains two artifacts per folder â€” `Anchor.md` (human-readable, structure-only, regenerated with no churn) plus a machine JSON sidecar describing the folder's R&D structure.
- **Scan triggers (approved):** Discovery runs on project register, on `/project/<id>` open, and via a manual Rescan button.
- **Labeling ruling (Stage-1):** Discovered artifacts are adopted as efforts so existing tile/Kanban readers fill in, but visibly and subtly labeled "imported" â€” as understated as possible while remaining honest â€” and separately counted.
- **Constraints (approved):** Python stdlib only; integrate with `rnd_registry` / `lanes` / `effort_history` / `anchor_gui` and the Kanban window; keep the 236-test suite green; commit-safe.
- **Document set:** This session's planning trio comprises the approved Master Plan (Crucible Stage 1), the Implementation Plan for Brownfield Discovery + the `Anchor.md` marker, and the Execution Log.

## Files

- [Brownfield Discovery — Execution Log](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Fbrownfield-discovery%2FEXECUTION-LOG.md)
- [Anchor Brownfield Discovery — Master Plan (Crucible Stage 1, approved)](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Fbrownfield-discovery%2FMASTER-PLAN.md)
- [Anchor Brownfield Discovery + `Anchor.md` Marker — Implementation Plan](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Fbrownfield-discovery%2FIMPLEMENTATION-PLAN.md)
