#!/usr/bin/env python3
"""W11 (C6) — scripted data-dir migration unit (stdlib only).

Move Anchor's runtime state OUT of the repo as ONE rollback-able unit. The
ops wrapper (``migrate_data_dir.ps1``) owns the service stop/start + live
healthcheck around this Python core; the core is the migrate → path-rewrite →
verify → arm-reaper sequence with rollback, and it is what the W11 gate proves.

Sequence (:func:`run_migration`):

1. **copy** — the data allowlist (markdown via ``paths.migrate_data`` + the
   ``.anchor/`` tree, ``rnd_jobs/``, ``rnd_registry.json``, ``dashboard.html``)
   from the OLD root into the NEW root. The old root is never mutated, so it is
   the rollback source (the ops wrapper additionally flips it read-only for a
   week);
2. **rewrite** — :func:`path_audit.apply_rewrites` swaps every repo-rooted
   absolute path (worktree_path, job log_path/cwd, folder_path, discovery paths)
   from the old root to the new root;
3. **verify** — :func:`path_audit.remaining_repo_rooted` must be empty (zero
   stores still reference the pre-move location);
4. **arm reaper dry-run** — :func:`worktrees.arm_reaper_dryrun` so the first
   post-move boot sweeps report-only (a rewrite miss can never delete a legit
   worktree).

Any failure after the new root is created **rolls back** by removing the
partially-migrated new root — the old root is intact, so the service restarts
from it unchanged. Returns a structured report; never leaves a half-migrated
new root behind on failure.

Stdlib only. Does NOT stop/start the service, bind a port, or call the network.
"""

import shutil
from pathlib import Path

import paths as _paths
import worktrees as _worktrees
from tools import path_audit

#: Runtime data subdirectories copied wholesale into the new root.
_DATA_TREES = (".anchor", "rnd_jobs", "domains", "logs", "health_reports")
#: Runtime data files copied into the new root (markdown is handled by
#: ``paths.migrate_data``; these are the JSON/HTML runtime stores it omits).
_DATA_FILES = ("rnd_registry.json", "dashboard.html")


def _copy_tree(src: Path, dst: Path):
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True)


def _copy_file(src: Path, dst: Path):
    if src.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def preflight(old_root, new_root):
    """Validate the migration is safe to run. Returns ``(ok, reason)``.

    Refuses: a missing old root, a new root INSIDE the old root (would recurse),
    the old root inside the new root, and a non-empty existing new root (never
    clobber real data). Pure — checks the filesystem only, changes nothing.
    """
    old = Path(old_root).resolve()
    new = Path(new_root).resolve()
    if not old.is_dir():
        return False, "old-root-missing"
    if old == new:
        return False, "same-root"
    if _worktrees._is_under(new, old):
        return False, "new-root-inside-old"
    if _worktrees._is_under(old, new):
        return False, "old-root-inside-new"
    if new.exists() and any(new.iterdir()):
        return False, "new-root-not-empty"
    return True, "ok"


def run_migration(old_root, new_root, *, arm_reaper=True):
    """Migrate the data dir from ``old_root`` to ``new_root`` with rollback.

    Returns a report::

        {"ok": bool, "old_root", "new_root",
         "copied": {...},            # paths.migrate_data report
         "rewrites": {"total": int, "stores": {...}},
         "verified": bool, "remaining": {...},
         "reaper_armed": bool,
         "rolled_back": bool, "reason": str|None}

    On any failure after the new root is created, the new root is removed
    (rollback) and ``ok`` is False with a ``reason``; the old root is untouched.
    """
    old = Path(old_root).resolve()
    new = Path(new_root).resolve()
    report = {"ok": False, "old_root": str(old), "new_root": str(new),
              "copied": None, "rewrites": {"total": 0, "stores": {}},
              "verified": False, "remaining": {}, "reaper_armed": False,
              "rolled_back": False, "reason": None}

    ok, reason = preflight(old, new)
    if not ok:
        report["reason"] = reason
        return report

    created = not new.exists()
    try:
        new.mkdir(parents=True, exist_ok=True)
        # 1) copy — markdown allowlist + the runtime JSON/HTML stores + trees.
        report["copied"] = _paths.migrate_data(source=old, dest=new)
        for name in _DATA_FILES:
            _copy_file(old / name, new / name)
        for tree in _DATA_TREES:
            _copy_tree(old / tree, new / tree)

        # 2) rewrite — swap every repo-rooted absolute path to the new root.
        rw = path_audit.apply_rewrites(new, str(old), str(new))
        report["rewrites"] = {"total": rw["total"], "stores": rw["stores"]}

        # 3) verify — zero stores may still reference the pre-move location.
        remaining = path_audit.remaining_repo_rooted(new, str(old))
        report["remaining"] = remaining
        report["verified"] = not remaining
        if remaining:
            raise RuntimeError(
                f"verify failed: {path_audit.audit_change_count(remaining)} "
                f"path(s) still under the old root")

        # 4) arm the reaper dry-run for the first post-move boot.
        if arm_reaper:
            base = (new / ".anchor" / _worktrees.WORKTREES_DIRNAME)
            _worktrees.arm_reaper_dryrun(base=base)
            report["reaper_armed"] = (
                _worktrees.reaper_dryrun_marker(base=base).exists())

        report["ok"] = True
        return report
    except Exception as exc:  # rollback: remove the partial new root
        report["reason"] = f"{type(exc).__name__}: {exc}"
        if created:
            shutil.rmtree(new, ignore_errors=True)
            report["rolled_back"] = True
        return report


if __name__ == "__main__":  # pragma: no cover - operator convenience
    import argparse
    import json

    ap = argparse.ArgumentParser(
        description="Migrate the Anchor data dir out of the repo (W11/C6)")
    ap.add_argument("old_root", help="the current (in-repo) data root")
    ap.add_argument("new_root", help="the new (out-of-repo) data root")
    ap.add_argument("--no-arm-reaper", action="store_true",
                    help="skip arming the first-boot reaper dry-run")
    args = ap.parse_args()
    rep = run_migration(args.old_root, args.new_root,
                        arm_reaper=not args.no_arm_reaper)
    print(json.dumps(rep, indent=2))
    raise SystemExit(0 if rep["ok"] else 1)
