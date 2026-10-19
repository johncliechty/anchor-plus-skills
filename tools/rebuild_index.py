#!/usr/bin/env python3
"""W14 (C3) — rebuild a deleted/torn index.json (and sessions.json rows).

The C3 journal is dual-written journal-first, so the derived layers — a lane's
``index.json`` and the session registry rows — are **recoverable-by-
construction**: everything they hold that the journal carries can be re-derived
from the journal (and, for the non-grass effort lanes whose journal events are
lane-granular only, from the surviving per-effort pointer-records). This is the
operator tool that does that recovery, proving the 'lost from an index' class is
never a real data loss.

Three rebuild paths (:func:`run_rebuild` runs all three):

1. **grass ``index.json`` from the journal** — the ordered idea/job ids the
   ``grass-idea-added`` / inbox ``effort-promoted`` events added, minus the
   ``grass-idea-deleted`` ones (:func:`rebuild_grass_index_from_journal`). This
   is the journal-driven path the W14 acceptance test exercises.
2. **any lane's ``index.json`` from its pointer-records** — enumerate the lane's
   surviving ``efforts/*.pointer.json`` and re-derive the ordered id list
   (:func:`rebuild_effort_index_from_pointers`). The general recovery for the
   effort lanes the journal can't reconstruct at id granularity.
3. **``sessions.json`` rows from the journal** — re-materialize the project's
   session rows (id, lane, backend, status, parent, chain) from the
   session-lifecycle events, MERGED into the global store so OTHER projects'
   rows are never touched (:func:`rebuild_session_rows_from_journal`).

**dry-run-first.** :func:`run_rebuild` defaults to ``dry_run=True`` — it reports
exactly what it WOULD write and mutates nothing. Pass ``dry_run=False`` (CLI
``--apply``) to write. Every rebuild is **idempotent**: re-running on an
already-consistent store is a no-op that converges to the same bytes. All writes
run under :data:`paths.WRITE_LOCK`.

Stdlib only. This tool WRITES the legacy stores (never the journal); it is the
operational answer to a journal-ahead divergence the parity gate reports.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import paths as _paths
import journal as _journal
import parity as _parity


# ── 1) grass index.json from the journal ─────────────────────────────────────

def rebuild_grass_index_from_journal(folder_path, project_id, *, dry_run=True):
    """Re-derive the grass ``index.json`` order from the journal.

    Returns ``{"lane":"grass", "current":[...], "rebuilt":[...],
    "changed":bool, "wrote":bool}``. Idempotent.
    """
    import effort_history as _eh
    folder_path = _parity.resolve_folder(project_id, folder_path)
    with _paths.WRITE_LOCK:
        events = _journal.read_events(project_id, folder_path=folder_path)
        derived = _parity.derive_effort_view_from_journal(events).get("grass", {})
        order = list(derived.keys())  # insertion order == append order
        current = _eh._load_index(folder_path, project_id, "grass")
        changed = current != order
        wrote = False
        if changed and not dry_run:
            _eh._save_index(folder_path, project_id, "grass", order)
            wrote = True
    return {"lane": "grass", "current": current, "rebuilt": order,
            "changed": changed, "wrote": wrote}


# ── 2) any lane's index.json from its pointer-records ────────────────────────

def rebuild_effort_index_from_pointers(folder_path, project_id, lane, *,
                                       dry_run=True):
    """Re-derive a lane's ``index.json`` from its surviving pointer-records.

    Enumerates ``efforts/*.pointer.json``, orders by each record's ``created_at``
    (then job_id for a stable tiebreak), and writes the ordered id list. The
    general recovery for the effort lanes whose journal events are lane-granular
    only. Returns the same shape as :func:`rebuild_grass_index_from_journal`.
    """
    import effort_history as _eh
    folder_path = _parity.resolve_folder(project_id, folder_path)
    with _paths.WRITE_LOCK:
        ed = _eh.efforts_dir(folder_path, project_id, lane)
        recs = []
        if ed.is_dir():
            for p in ed.glob("*" + _eh.POINTER_SUFFIX):
                jid = p.name[:-len(_eh.POINTER_SUFFIX)]
                try:
                    rec = json.loads(p.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    rec = {}
                created = rec.get("created_at")
                try:
                    created = float(created) if created is not None else None
                except (TypeError, ValueError):
                    created = None
                recs.append((created, jid))
        # created_at ascending (append order); None sorts last; job_id tiebreak.
        recs.sort(key=lambda t: (t[0] is None, t[0] or 0.0, t[1]))
        order = [jid for _, jid in recs]
        current = _eh._load_index(folder_path, project_id, lane)
        changed = current != order
        wrote = False
        if changed and not dry_run:
            _eh._save_index(folder_path, project_id, lane, order)
            wrote = True
    return {"lane": lane, "current": current, "rebuilt": order,
            "changed": changed, "wrote": wrote}


# ── 3) sessions.json rows from the journal ───────────────────────────────────

def derive_session_rows_from_journal(project_id, folder_path=None) -> dict:
    """Reconstruct the project's full session rows from the journal.

    Richer than :func:`parity.derive_session_view_from_journal`: also recovers
    ``backend`` (started payload), ``chain_id`` (the event correlation_id) and
    ``parent_session_id`` (the causation_id) so a whole registry row can be
    re-materialized. Returns ``{sid: {session_id, project_id, lane, backend,
    status, parent_session_id, chain_id}}``.
    """
    from session_registry import (STATUS_RUNNING, STATUS_DONE, STATUS_IDLE,
                                   BACKEND_CLAUDE)
    events = _journal.read_events(project_id, folder_path=folder_path)
    rows = {}
    for ev in sorted(events, key=lambda e: _parity._seq_of(e)):
        t = ev.get("type")
        payload = ev.get("payload") or {}
        sid = payload.get("session_id")
        if not sid:
            continue
        if t == _journal.EV_SESSION_STARTED:
            rows[sid] = {
                "session_id": sid,
                "project_id": project_id,
                "lane": payload.get("lane", "") or "",
                "backend": payload.get("backend", "") or BACKEND_CLAUDE,
                "status": STATUS_RUNNING,
                "parent_session_id": ev.get("causation_id") or "",
                "chain_id": ev.get("correlation_id") or sid,
            }
        elif t == _journal.EV_SESSION_ADVANCED:
            row = rows.get(sid)
            if row is None:
                continue
            row["lane"] = payload.get("lane", row.get("lane", "")) or ""
        elif t == _journal.EV_SESSION_KILLED:
            row = rows.get(sid)
            if row is not None:
                row["status"] = STATUS_DONE
        elif t == _journal.EV_SESSION_CLOSED:
            row = rows.get(sid)
            if row is not None:
                row["status"] = STATUS_IDLE
    return rows


def rebuild_session_rows_from_journal(project_id, folder_path=None, *,
                                      dry_run=True):
    """Re-materialize the project's session rows into the global store.

    MERGES into ``sessions.json``: a journal-derived row missing from the store
    is ADDED; a present row whose lane/status has drifted is CONVERGED to the
    journal's (the recovery source of truth). Other projects' rows — and fields
    the journal does not carry (``worktree_path``/``branch``/``created_at`` on an
    existing row) — are left untouched. Idempotent.

    Returns ``{"added":[sid...], "converged":[sid...], "wrote":bool}``.
    """
    import session_registry as _reg
    added, converged = [], []
    with _paths.WRITE_LOCK:
        derived = derive_session_rows_from_journal(project_id,
                                                   folder_path=folder_path)
        reg = _reg.load_sessions()
        for sid, drow in derived.items():
            cur = reg.get(sid)
            if cur is None:
                rec = dict(drow)
                rec.setdefault("created_at", time.time())
                reg[sid] = _reg._normalize(rec)
                added.append(sid)
            else:
                # Converge only the journal-carried fields; preserve the rest.
                if (cur.get("lane") != drow["lane"]
                        or cur.get("status") != drow["status"]):
                    merged = dict(cur)
                    merged["lane"] = drow["lane"]
                    merged["status"] = drow["status"]
                    reg[sid] = _reg._normalize(merged)
                    converged.append(sid)
        wrote = False
        if (added or converged) and not dry_run:
            _reg._save_sessions(reg)
            wrote = True
    return {"added": added, "converged": converged, "wrote": wrote}


# ── The all-in-one recovery pass ─────────────────────────────────────────────

#: The non-grass effort lanes rebuilt from their pointer-records.
_POINTER_LANES = ("research", "planning", "build", "deliverables")


def run_rebuild(folder_path, project_id, *, dry_run=True,
                pointer_lanes=_POINTER_LANES):
    """Rebuild grass (from journal), the other indexes (from pointers) and the
    session rows (from journal) in one pass. dry-run-first (mutates nothing
    unless ``dry_run=False``). Returns a structured report."""
    folder_path = _parity.resolve_folder(project_id, folder_path)
    report = {"project_id": project_id, "folder_path": str(folder_path),
              "dry_run": bool(dry_run), "grass": None,
              "pointer_lanes": {}, "sessions": None}
    report["grass"] = rebuild_grass_index_from_journal(
        folder_path, project_id, dry_run=dry_run)
    for lane in pointer_lanes:
        report["pointer_lanes"][lane] = rebuild_effort_index_from_pointers(
            folder_path, project_id, lane, dry_run=dry_run)
    report["sessions"] = rebuild_session_rows_from_journal(
        project_id, folder_path=folder_path, dry_run=dry_run)
    return report


if __name__ == "__main__":  # pragma: no cover - operator convenience
    ap = argparse.ArgumentParser(
        description="Rebuild a project's index.json / sessions.json rows from "
                    "the journal (W14/C3 recovery).")
    ap.add_argument("project_id", help="the R&D project id")
    ap.add_argument("--folder", default=None,
                    help="the project folder (else resolved from the registry)")
    ap.add_argument("--apply", action="store_true",
                    help="write the rebuilt stores (default: dry-run only)")
    args = ap.parse_args()
    rep = run_rebuild(args.folder, args.project_id, dry_run=not args.apply)
    print(json.dumps(rep, indent=2, default=str))
    raise SystemExit(0)
