#!/usr/bin/env python3
"""W14 (C3) — idempotent journal replay + reconcile-report (recovery tooling).

The parity gate (:mod:`parity`) classifies journal↔legacy divergence. This is
the operational ANSWER — the pair of operator tools that act on that report:

* :func:`reconcile_report` — a **dry-run-first, read-only** reconcile report. It
  runs the parity gate and annotates every divergence with a recommended action:
  a journal-ahead row is REPLAYABLE (the journal holds an intent the legacy store
  lost — replay converges it); a legacy-ahead or conflict row is
  ``investigate`` — the journal is MISSING the event, which replay must never
  paper over by mutating a store unasked (a completeness bug for a human). It
  mutates nothing.

* :func:`replay` — **idempotent, bounded, dry-run-first** convergence of the
  legacy stores TO the journal for the recoverable (journal-ahead) class only:
  it re-materializes the grass ``index.json`` and the session rows from the
  journal (delegating to :mod:`tools.rebuild_index`, which is itself idempotent).
  It NEVER deletes/rewrites a legacy-ahead or conflict row — those are reported,
  not silently reconciled. Default ``dry_run=True`` mutates nothing; ``--apply``
  writes. Re-running after an apply is a no-op (the gate then reads clean).

"Bounded": replay acts per-project on a bounded snapshot; it does not fan out.
Stdlib only; writes the legacy stores only via the rebuild tool (never the
journal).
"""

from __future__ import annotations

import argparse
import json

import parity as _parity
from tools import rebuild_index as _rebuild


#: Recommended action per divergence class.
ACTION_REPLAY = "replay"        # journal-ahead → converge the legacy store
ACTION_INVESTIGATE = "investigate"  # legacy-ahead / conflict → human decision

_ACTION_FOR_CLASS = {
    _parity.CLASS_JOURNAL_AHEAD: ACTION_REPLAY,
    _parity.CLASS_LEGACY_AHEAD: ACTION_INVESTIGATE,
    _parity.CLASS_CONFLICT: ACTION_INVESTIGATE,
}


def reconcile_report(folder_path, project_id, *,
                     tail_window=_parity.DEFAULT_TAIL_WINDOW) -> dict:
    """Read-only reconcile report: the classified divergences + recommended
    actions. Mutates nothing (dry-run by nature). Returns a structured dict."""
    rep = _parity.classify_parity(project_id, folder_path=folder_path,
                                  tail_window=tail_window)
    rows = []
    for d in rep.effective_divergences():
        rows.append({
            "entity": d.get("entity"),
            "key": d.get("key"),
            "classification": d.get("classification"),
            "severity": d.get("severity"),
            "action": _ACTION_FOR_CLASS.get(d.get("classification"),
                                            ACTION_INVESTIGATE),
            "detail": d.get("detail"),
        })
    return {
        "project_id": project_id,
        "clean": rep.is_clean(),
        "summary": rep.summary(),
        "counts": rep.classification_counts(),
        "bugs": len(rep.bugs),
        "divergences": rows,
        "replayable": [r for r in rows if r["action"] == ACTION_REPLAY],
        "investigate": [r for r in rows if r["action"] == ACTION_INVESTIGATE],
    }


def replay(folder_path, project_id, *, dry_run=True,
           tail_window=_parity.DEFAULT_TAIL_WINDOW) -> dict:
    """Idempotently converge the legacy stores to the journal (journal-ahead).

    Runs the reconcile report first; if there are recoverable journal-ahead
    rows, converges them by re-materializing the grass index + the session rows
    from the journal via :mod:`tools.rebuild_index`. Legacy-ahead/conflict rows
    are carried into ``investigate`` untouched. dry-run-first (``dry_run=True``
    mutates nothing). Idempotent: a second run after an apply reports clean +
    writes nothing. Returns ``{"report", "rebuild", "applied":bool}``.
    """
    report = reconcile_report(folder_path, project_id, tail_window=tail_window)
    rebuild = None
    # Only touch the stores when there is a recoverable divergence to converge.
    if report["replayable"]:
        rebuild = _rebuild.run_rebuild(folder_path, project_id, dry_run=dry_run,
                                       pointer_lanes=())  # journal-only classes
    return {"report": report, "rebuild": rebuild, "applied": bool(
        rebuild and not dry_run and (
            rebuild["grass"]["wrote"] or rebuild["sessions"]["wrote"]))}


if __name__ == "__main__":  # pragma: no cover - operator convenience
    ap = argparse.ArgumentParser(
        description="Reconcile-report + idempotent journal replay (W14/C3).")
    ap.add_argument("project_id", help="the R&D project id")
    ap.add_argument("--folder", default=None,
                    help="the project folder (else resolved from the registry)")
    ap.add_argument("--tail-window", type=int,
                    default=_parity.DEFAULT_TAIL_WINDOW,
                    help="tolerate journal-ahead within this many tip seqs")
    ap.add_argument("--apply", action="store_true",
                    help="converge the stores to the journal (default: report)")
    args = ap.parse_args()
    if args.apply:
        out = replay(args.folder, args.project_id, dry_run=False,
                     tail_window=args.tail_window)
    else:
        out = {"report": reconcile_report(args.folder, args.project_id,
                                          tail_window=args.tail_window),
               "rebuild": None, "applied": False}
    print(json.dumps(out, indent=2, default=str))
    raise SystemExit(0)
