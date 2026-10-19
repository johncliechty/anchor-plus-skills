#!/usr/bin/env python3
"""One-time, idempotent backfill of the per-project usage index from job records.

codex-discipline Wave 2 S1 (2026-09-17). Jobs that finished before S1 went live
have their usage in the ledger (keyed ``job:<job_id>``) but no project on the
row and no index row, so the cockpit's "jobs" figure would start at zero. This
walks ``rnd_jobs/`` once, re-runs each finished job (with or without a
result envelope — a spawn without one becomes an ``unknown`` row) through the SAME seam
(``usage_capture.ingest_job_cost`` with the record), and lets the seam's
idempotency do the rest: the ledger entry already exists (nothing added), the
index row is created if missing. Safe to re-run; never touches a job record.

    python tools/backfill_usage_index.py            # report only
    python tools/backfill_usage_index.py --apply    # write index rows
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import job_runner as jr          # noqa: E402
import usage_capture as uc       # noqa: E402
import usage_index as ui         # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    jobs_dir = jr.jobs_dir()
    seen = with_cost = attributed = written = 0
    per_project = {}
    before_rows = sum(len(ui.load_rows(p.stem)) for p in ui.index_dir().glob('*.jsonl')) if ui.index_dir().is_dir() else 0
    for name in sorted(os.listdir(jobs_dir)):
        if not name.endswith(".json"):
            continue
        try:
            rec = json.loads((Path(jobs_dir) / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(rec, dict) or not rec.get("job_id"):
            continue
        if rec.get("status") not in ("done", "failed", "cancelled", "interrupted"):
            continue
        seen += 1
        cost = rec.get("cost") if isinstance(rec.get("cost"), dict) else None
        euuid = (cost or {}).get("session_id") or None
        if euuid:
            with_cost += 1
        where = (rec.get("effort_dir") or rec.get("refinement_dir") or rec.get("cwd")
                 or rec.get("folder_path"))
        pid = rec.get("project_id") or uc.resolve_project(where)[0]
        if not pid:
            continue
        attributed += 1
        per_project[pid] = per_project.get(pid, 0) + 1
        if args.apply:
            uc.ingest_job_cost(euuid, cost, rec["job_id"], record=rec)
    if args.apply:
        written = sum(len(ui.load_rows(pid)) for pid in per_project) - before_rows
    print(f"finished job records {seen} · with usage {with_cost} · attributable to a project "
          f"{attributed} · index rows written {written}{'' if args.apply else ' (dry run)'}")
    for pid, n in sorted(per_project.items(), key=lambda kv: -kv[1])[:12]:
        print(f"  {pid[:8]}  {n}")


if __name__ == "__main__":
    main()
