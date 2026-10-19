# Anchor Brownfield Discovery — Master Plan (Crucible Stage 1, approved)

## North Star (locked)
When an R&D project is registered or opened on an existing folder, Anchor instantly
(local, no tokens) discovers genuine pre-existing trio artifacts and adopts them so the
dashboard populates (home R&D panel + tile rollup + project Kanban) — honestly:
discovered items are excluded from the real effort count (shown as "M imported"), get
no `vN` label, are clickable to their real on-disk file, and carry a subtle `imported`
marker. Anchor also writes `Anchor.md` (human, structure-only, no-churn) + a machine
sidecar describing the folder's R&D structure.

## Approved decisions
- Marker = `Anchor.md` (human, regenerated) + a machine JSON sidecar.
- Discovered artifacts ADOPTED as efforts (so the existing tile/Kanban readers fill in)
  — but visibly, subtly labeled "imported" (user Stage-1 ruling: as understated as
  possible while honest), separately counted, never given fake provenance/`vN`.
- Scan on register + `/project/<id>` open + a manual Rescan button.
- Python stdlib only; integrate with `rnd_registry`/`lanes`/`effort_history`/`anchor_gui`
  + the Kanban window; keep the 236-test suite green; commit-safe.

## Phasing → see `IMPLEMENTATION-PLAN.md` (7 waves)
Scan → honest data model + reconciliation → render honesty → file route + status line +
home panel → marker writer → wiring → end-to-end gate.

## Resolved risks (from two Shark-Tank rounds, code-verified)
Provenance honesty (source flag, no fake cost, excluded from count); `vN` would have
broken the kanban test (compute over real efforts only); the `/artifact` route is a
traversal risk (use the `katex_asset` containment pattern + negative tests); `Anchor.md`
write-on-GET race (WRITE_LOCK + concurrency test); over-broad globs (provenance-signal
classification); self-scan of `.anchor` (excluded); deletion/staleness (reconcile/prune
discovered records on rescan); home R&D panel must also fill in (in trigger+render set).
