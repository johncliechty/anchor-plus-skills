"""Dev tool — snapshot a project's live session_registry + effort store into an
ANONYMIZED fixture dir (telemetry-resume W1).

Purpose: the diag-B2 tile/resume reproductions must run against CAPTURED REAL
states, not hand-built toys. This command reads the live `.anchor/sessions.json`
(filtered to one project) plus the project's effort pointer-records, **scrubs
every sensitive / host-identifying field**, remaps ids to stable anonymized
aliases, and writes a self-describing fixture set:

    <out>/sessions.json                     the {session_id: record} map
    <out>/efforts/<proj>_<lane>.json        one flattened file per (project, lane)
    <out>/MANIFEST.json                     tile-class map + mandatory-class flags
    <out>/README.md                         (left in place if it already exists)

It is **READ-ONLY on the live store** — it never writes back to `.anchor/`. Stdlib
only (json / os / re / argparse / pathlib). Point it at the live store with
`--data-dir` (defaults to `ANCHOR_DATA_DIR`, else the code dir).

CLI:
    python tools/capture_registry_fixture.py --project <pid> \
        --out tests/fixtures/registry_state [--data-dir <dir>] [--alias proj-0000]

The W1 done-when requires the capture set to include >=1 evicted-parked session
and >=1 finished one-shot job. This tool does NOT synthesize those — it captures
whatever the live store holds and FLAGS in MANIFEST.json which classes were found,
warning (non-zero exit under --require-mandatory) if either mandatory class is
absent, so the operator captures from a project that has them.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

# ── Fields scrubbed before a record leaves the live store ───────────────────
# Host paths / free text → placeholder; secrets → empty; process identity → null.
_SCRUB_TO_PLACEHOLDER = {
    "worktree_path": "<scrubbed-worktree>",
    "branch": "<scrubbed-branch>",
    "seed_text": "<scrubbed-seed>",
    "prompt_seed": "<scrubbed-prompt-seed>",
}
_SCRUB_TO_EMPTY = ("crypt_token", "label")
_SCRUB_TO_NULL = ("pid", "proc_create_time")

#: Lanes whose effort stores are captured (the trio + general/grass content).
_CAPTURE_LANES = ("research", "planning", "build", "deliverables", "general", "grass")

#: Non-running terminal statuses that mean a worktree was reclaimed.
_EVICTED_STATUSES = ("parked-warm", "idle", "reaped-orphan", "cancelled")


class CaptureError(RuntimeError):
    pass


def _scrub_str(value, placeholder):
    """A non-empty string → placeholder; empty stays empty (shape preserved)."""
    return placeholder if (value or "").strip() else ""


def scrub_record(rec: dict, id_map: dict, project_alias: str) -> dict:
    """Return an anonymized COPY of one session record.

    Remaps `session_id` / `parent_session_id` / `chain_id` / `effort_id` through
    `id_map` (built by :func:`_build_id_map`), rewrites `project_id` to the alias,
    scrubs host paths / free text / secrets / process identity, and preserves the
    structural fields the reproductions depend on (status, lane, stage, lineage,
    timestamps, effort_managed, cost).
    """
    out = dict(rec)
    for key in ("session_id", "parent_session_id", "chain_id", "effort_id"):
        v = out.get(key)
        if v:
            out[key] = id_map.get(v, v)
    if "project_id" in out:
        out["project_id"] = project_alias
    for key, placeholder in _SCRUB_TO_PLACEHOLDER.items():
        if key in out:
            out[key] = _scrub_str(out.get(key), placeholder)
    for key in _SCRUB_TO_EMPTY:
        if key in out:
            out[key] = ""
    for key in _SCRUB_TO_NULL:
        if key in out:
            out[key] = None
    # An evicted-parked session has NO worktree — force it empty regardless.
    if (out.get("status") in _EVICTED_STATUSES) and not (rec.get("worktree_path") or "").strip():
        out["worktree_path"] = ""
    return out


def _build_id_map(records: list) -> dict:
    """Map real session ids → stable `sess-000N` aliases (creation order).

    Deterministic: sorted by `created_at` then id, so re-capturing the same store
    yields the same aliases.
    """
    ordered = sorted(records, key=lambda r: (r.get("created_at") or 0.0,
                                             r.get("session_id") or ""))
    id_map = {}
    for i, rec in enumerate(ordered, start=1):
        sid = rec.get("session_id")
        if sid:
            id_map[sid] = "sess-%04d" % i
    return id_map


def _scrub_effort(rec: dict, id_map: dict, project_alias: str) -> dict:
    """Anonymize one effort pointer-record (cost preserved; text scrubbed)."""
    out = dict(rec)
    if "project_id" in out:
        out["project_id"] = project_alias
    if out.get("session_id"):
        out["session_id"] = id_map.get(out["session_id"], out["session_id"])
    if "prompt_seed" in out:
        out["prompt_seed"] = _scrub_str(out.get("prompt_seed"), "<scrubbed-prompt-seed>")
    return out


def _is_one_shot_job(effort: dict) -> bool:
    """A finished durable one-shot job: a run-provenance effort with a cost block
    and no live PTY session_id (job_id typically ``run-…``)."""
    if (effort.get("session_id") or ""):
        return False
    if not (effort.get("cost") or {}):
        return False
    jid = str(effort.get("job_id") or "")
    return jid.startswith("run-") or (effort.get("provenance") == "run")


def capture(project_id: str, out_dir: Path, project_alias: str = "proj-0000",
            require_mandatory: bool = False) -> dict:
    """Snapshot the project's registry + effort store into ``out_dir`` (anonymized).

    Returns the MANIFEST dict. Raises :class:`CaptureError` under
    ``require_mandatory`` when either mandatory class is absent.
    """
    import session_registry as _reg
    import effort_history as _eh
    import rnd_registry as _rnd

    out_dir = Path(out_dir)
    (out_dir / "efforts").mkdir(parents=True, exist_ok=True)

    records = _reg.list_sessions(project_id=project_id)
    id_map = _build_id_map(records)
    sessions = {}
    for rec in records:
        scrubbed = scrub_record(rec, id_map, project_alias)
        sessions[scrubbed["session_id"]] = scrubbed
    (out_dir / "sessions.json").write_text(
        json.dumps(sessions, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    proj = _rnd.get_project(project_id) or {}
    folder_path = proj.get("folder_path", "")
    effort_files = []
    one_shot_jobs = []
    if folder_path:
        for lane in _CAPTURE_LANES:
            try:
                efforts = _eh.list_efforts(folder_path, project_id, lane)
            except Exception:
                efforts = []
            if not efforts:
                continue
            scrubbed = [_scrub_effort(e, id_map, project_alias) for e in efforts]
            fname = "efforts/%s_%s.json" % (project_alias, lane)
            (out_dir / fname).write_text(json.dumps({
                "project_id": project_alias,
                "lane": lane,
                "index": [e.get("job_id") for e in scrubbed],
                "efforts": scrubbed,
            }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            effort_files.append(fname)
            one_shot_jobs.extend(e.get("job_id") for e in scrubbed
                                 if _is_one_shot_job(e))

    evicted = [sid for sid, r in sessions.items()
               if r.get("status") in _EVICTED_STATUSES
               and not (r.get("worktree_path") or "").strip()]
    tile_classes = {sid: {"class": _classify_tile(r), "status": r.get("status"),
                          "lane": r.get("lane")} for sid, r in sessions.items()}

    manifest = {
        "project_id": project_alias,
        "captured_by": "tools/capture_registry_fixture.py",
        "anonymized": True,
        "scrubbed_fields": sorted(set(list(_SCRUB_TO_PLACEHOLDER)
                                      + list(_SCRUB_TO_EMPTY) + list(_SCRUB_TO_NULL))),
        "sessions_file": "sessions.json",
        "efforts_files": effort_files,
        "tile_classes": tile_classes,
        "mandatory_classes_present": {
            "evicted_parked_session": evicted[0] if evicted else None,
            "finished_one_shot_job": one_shot_jobs[0] if one_shot_jobs else None,
        },
    }
    (out_dir / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if require_mandatory:
        missing = [k for k, v in manifest["mandatory_classes_present"].items() if not v]
        if missing:
            raise CaptureError(
                "capture from a project WITH these classes — missing: %s" % ", ".join(missing))
    return manifest


def _classify_tile(rec: dict) -> str:
    status = rec.get("status") or ""
    lane = rec.get("lane") or ""
    if lane == "general":
        return "general"
    if status == "running":
        return "running"
    if status == "done":
        return "done"
    if status == "failed":
        return "failed"
    if status in _EVICTED_STATUSES and not (rec.get("worktree_path") or "").strip():
        return "evicted-parked"
    if status in ("parked-warm", "idle"):
        return "parked-idle"
    if status == "reaped-orphan":
        return "server-dead-stale-running"
    return status or "unknown"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Capture an anonymized registry-state fixture.")
    ap.add_argument("--project", required=True, help="project id to snapshot")
    ap.add_argument("--out", default="tests/fixtures/registry_state",
                    help="output fixture dir")
    ap.add_argument("--alias", default="proj-0000", help="anonymized project id")
    ap.add_argument("--data-dir", default=None,
                    help="ANCHOR_DATA_DIR of the LIVE store to read (default: env / code dir)")
    ap.add_argument("--require-mandatory", action="store_true",
                    help="exit non-zero if evicted-parked or one-shot-job class is absent")
    args = ap.parse_args(argv)

    if args.data_dir:
        os.environ["ANCHOR_DATA_DIR"] = args.data_dir
    # Make the repo importable regardless of cwd.
    import sys
    repo = Path(__file__).resolve().parent.parent
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))

    try:
        manifest = capture(args.project, Path(args.out), project_alias=args.alias,
                           require_mandatory=args.require_mandatory)
    except CaptureError as exc:
        print("capture-registry-fixture: %s" % exc)
        return 2
    print("captured %d sessions + %d effort file(s) -> %s"
          % (len(json.loads((Path(args.out) / "sessions.json").read_text())),
             len(manifest["efforts_files"]), args.out))
    mc = manifest["mandatory_classes_present"]
    print("  evicted-parked: %s | one-shot-job: %s"
          % (mc["evicted_parked_session"], mc["finished_one_shot_job"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
