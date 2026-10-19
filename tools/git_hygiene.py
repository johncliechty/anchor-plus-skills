#!/usr/bin/env python3
"""W11 (C6) — git hygiene: classify + un-track runtime artifacts (stdlib only).

The repo accumulated dozens of tracked RUNTIME artifacts (the live
``rnd_registry.json``, generated ``dashboard.html``, ``rnd_jobs/`` job records,
``health_reports/``, ``logs/``, ``.anchor/`` volatile stores, stray ``_*.log``
scratch dumps). Once the data dir moves OUT of the repo (W11 step 1) those files
are written outside the tree — but the ones already in the git index keep showing
as dirty on every write. Git hygiene un-tracks them (``git rm --cached``, content
kept on disk) so ``git status --porcelain`` stays empty through a full healthcheck
cycle.

This module is the mechanical half:

* :func:`classify_runtime` — is a repo-relative path a runtime artifact? (a pure,
  well-defined classifier that the ``.gitignore`` rules mirror);
* :func:`tracked_runtime_artifacts` — ``git ls-files`` ∩ ``classify_runtime``
  (the ~62-file set, computed from ground truth — never hard-coded);
* :func:`untrack` — ``git rm --cached`` the set (idempotent; ``dry_run`` returns
  the plan without touching the index);
* :func:`porcelain` — ``git status --porcelain`` as a list (the gate predicate).

git is an external CLI through :func:`_git` (bounded, windowless, never raises).
The actual commit is a human/orchestrator step; this module is what the gate
drives on a hermetic temp repo.
"""

import fnmatch
import subprocess
from pathlib import Path

import paths as _paths

_GIT_TIMEOUT = 60

#: Repo-relative directories whose every file is a runtime artifact.
RUNTIME_DIRS = ("logs", "rnd_jobs", "health_reports", "gandalf", "_devtest")

#: Root-level runtime FILE globs (no slash — they match repo-root files only).
RUNTIME_FILE_GLOBS = (
    "rnd_registry.json", "settings.json", "steward-cockpit-state.json",      # A4, 2026-10-05: untracked runtime state
    "rnd_registry.json.bak-*", "settings.json.bak-*", "steward-cockpit-state.json.bak-*",
    "dashboard.html", "dashboard_live.html", "dashboard_api.html",
    "foreman-checkpoint.json",
    "pytest_stdout.txt", "pytest_*.txt", "*.pytest.log",
    "_*.log", "_census.log", "_census.stop",
    ".healthcheck_marker", ".write_test", "test_write.txt",
    "test_winpty_*.txt", "bridge_test*.txt",
)


def classify_runtime(rel) -> bool:
    """Is ``rel`` (a repo-relative path) a RUNTIME artifact (never product)?

    Pure and total: mirrors the ``.gitignore`` runtime rules exactly so the two
    can never drift. Product code, tests, docs, gate artifacts (OPEN_ROUTES.json,
    dist_manifest.txt, the tracked ``.anchor`` pointer records + summaries) are
    NOT runtime and return ``False``.
    """
    rel = str(rel).replace("\\", "/")
    if rel.startswith("./"):            # a leading "./" is noise — but NOT the
        rel = rel[2:]                   # dot of a dotfile like ".anchor" (a
    rel = rel.lstrip("/")               # bare lstrip("./") would eat it).
    if not rel:
        return False
    parts = rel.split("/")
    if parts[0] in RUNTIME_DIRS:
        return True
    if parts[0] == ".anchor":
        base = parts[-1]
        if base in ("sessions.json", "discovery.json"):
            return True
        # rearch W12 (C3): the per-project event journal is a RUNTIME, volatile,
        # potentially personal-data-carrying append-only log (mutation-of-record,
        # not a durable pointer record) — ignored like sessions.json, never
        # committed. Covers ``journal.jsonl`` (+ its ``.tmp`` twin) and a
        # ``journal/`` dir.
        if base == "journal.jsonl" or base.startswith("journal.jsonl."):
            return True
        if "journal" in parts[1:]:
            return True
        if "jobs" in parts[1:]:            # any nested jobs/ record
            return True
        if len(parts) > 1 and parts[1] == "worktrees":
            return True
        return False                        # tracked pointer records / summaries
    # Root-level runtime files (the globs carry no slash → root-only by nature).
    return any(fnmatch.fnmatch(rel, g) for g in RUNTIME_FILE_GLOBS)


def _git(repo, args, timeout=_GIT_TIMEOUT):
    """Run ``git -C <repo> <args>``; return ``(ok, rc, stdout, stderr)``."""
    cmd = ["git", "-C", str(repo)] + [str(a) for a in args]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            creationflags=_paths.NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, None, "", f"git invocation failed: {exc}"
    return (proc.returncode == 0, proc.returncode,
            proc.stdout or "", proc.stderr or "")


def tracked_files(repo) -> list:
    """Repo-relative paths currently tracked by git (``git ls-files``)."""
    ok, _rc, out, _err = _git(repo, ["ls-files"])
    if not ok:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def tracked_runtime_artifacts(repo) -> list:
    """The tracked files that :func:`classify_runtime` flags (sorted)."""
    return sorted(f for f in tracked_files(repo) if classify_runtime(f))


def untrack(repo, rel_paths, *, dry_run=False) -> dict:
    """``git rm --cached`` the given paths (content kept on disk).

    Idempotent and safe: paths not in the index are skipped, so re-running is a
    no-op. ``dry_run`` returns the plan without touching the index. Returns
    ``{"untracked": [...], "skipped": [...], "dry_run": bool}``.
    """
    rel_paths = list(rel_paths or [])
    if dry_run:
        return {"untracked": [], "skipped": rel_paths, "dry_run": True,
                "would_untrack": rel_paths}
    done, skipped = [], []
    # One batched call keeps it a single git invocation; --ignore-unmatch makes
    # an already-untracked path a no-op instead of a hard error.
    if rel_paths:
        ok, _rc, _out, err = _git(
            repo, ["rm", "--cached", "-q", "--ignore-unmatch", "--"]
            + rel_paths)
        if ok:
            done = rel_paths
        else:
            skipped = rel_paths
            return {"untracked": done, "skipped": skipped, "dry_run": False,
                    "error": err.strip()}
    return {"untracked": done, "skipped": skipped, "dry_run": False}


def porcelain(repo) -> list:
    """``git status --porcelain`` as a list of non-empty status lines."""
    ok, _rc, out, _err = _git(repo, ["status", "--porcelain"])
    if not ok:
        return []
    return [line for line in out.splitlines() if line.strip()]


def run_hygiene(repo, *, dry_run=False) -> dict:
    """Compute + un-track the tracked runtime artifacts. Returns a report."""
    artifacts = tracked_runtime_artifacts(repo)
    res = untrack(repo, artifacts, dry_run=dry_run)
    res["count"] = len(artifacts)
    res["artifacts"] = artifacts
    return res


if __name__ == "__main__":  # pragma: no cover - operator convenience
    import argparse
    import json

    ap = argparse.ArgumentParser(
        description="Un-track runtime artifacts from git (W11/C6)")
    ap.add_argument("--repo", default=str(_paths.CODE_DIR))
    ap.add_argument("--apply", action="store_true",
                    help="actually git rm --cached (default: list only)")
    args = ap.parse_args()
    rep = run_hygiene(args.repo, dry_run=not args.apply)
    print(json.dumps({"count": rep["count"], "artifacts": rep["artifacts"],
                      "dry_run": rep.get("dry_run", True)}, indent=2))
