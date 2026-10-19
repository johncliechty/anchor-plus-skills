#!/usr/bin/env python3
"""Anchor git-worktree isolation for managed terminal sessions (stdlib only).

v3 "Mission Control" (MASTER-PLAN §F, Implementation-Plan Wave 2). Each managed
terminal session runs in its OWN git worktree + branch so a planning session can
never dirty a running Foreman build's tree. This module owns the lifecycle:

- :func:`create_worktree` — resolve the project's repo (from
  ``rnd_registry.get_project(pid)["folder_path"]``), create a NEW branch and
  ``git worktree add`` it at a MANAGED, git-ignored location;
- :func:`remove_worktree` — ``git worktree remove`` with safety checks (only
  ever a path under the managed base; tolerate already-gone);
- :func:`reap_orphans` — sweep managed worktrees whose session id is not in the
  active set, and ``git worktree prune``.

**Where worktrees live + why:** under ``<data_dir>/.anchor/worktrees/<session_id>``
(``managed_base()``). This is OUTSIDE the project's tracked working tree, and the
``.anchor/.gitignore`` already excludes the per-project store; we additionally
ensure ``worktrees/`` is git-ignored there so a managed worktree is NEVER tracked
by the host repo. The base is overridable via the ``ANCHOR_WORKTREE_BASE`` env
var (and a ``base`` arg) so tests are hermetic — they point it at a tmp dir and
never create a worktree off the real build repo.

Robust by contract: a non-git folder, a missing path, or an already-removed
worktree must NOT crash — every entry point returns a clear status dict.

Stdlib ``subprocess`` only. No third-party imports.
"""

import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path

import paths as _paths
import rnd_registry as _rnd

#: Env var overriding the managed worktree base (hermetic tests set this).
WORKTREE_BASE_ENV = "ANCHOR_WORKTREE_BASE"
#: Subdir under ``.anchor/`` that holds managed worktrees.
WORKTREES_DIRNAME = "worktrees"

#: W11 (C6) — reaper dry-run env override. When truthy, :func:`reap_orphans`
#: computes a would-reap report WITHOUT deleting anything. The scripted data-dir
#: migration ALSO arms a persistent on-disk marker (see :func:`arm_reaper_dryrun`)
#: so the FIRST post-move boot is report-only regardless of the env: a path-rewrite
#: miss would otherwise make the reaper delete a legit parked/live worktree it can
#: no longer resolve. Live reaping is re-armed only after a CLEAN report.
REAPER_DRYRUN_ENV = "ANCHOR_REAPER_DRYRUN"
#: Persistent "first post-move boot is dry-run" marker under the managed base.
REAPER_DRYRUN_MARKER = ".reaper_dryrun"

#: Branch-name prefix; the branch is deterministic from the session id.
BRANCH_PREFIX = "anchor/session/"

#: Bounded timeout (seconds) for every git invocation — a hung git must not
#: wedge the server.
_GIT_TIMEOUT = 60


# ── Managed base ────────────────────────────────────────────────────────────

def managed_base(base=None) -> Path:
    """Resolve the managed worktree base dir (absolute).

    Precedence: explicit ``base`` arg → ``ANCHOR_WORKTREE_BASE`` env →
    ``<data_dir>/.anchor/worktrees``. Does NOT create the directory.
    """
    if base is not None:
        return Path(base).expanduser().resolve()
    raw = os.environ.get(WORKTREE_BASE_ENV)
    if raw and raw.strip():
        return Path(raw).expanduser().resolve()
    return (_paths.data_dir() / ".anchor" / WORKTREES_DIRNAME).resolve()


def worktree_path_for(session_id: str, base=None) -> Path:
    """Deterministic managed worktree path for a session id."""
    return managed_base(base) / str(session_id)


def branch_for(session_id: str) -> str:
    """Deterministic, COLLISION-RESISTANT branch name from a session id.

    Derived from the FULL session id (not a truncated 12-char prefix, which let
    two ids sharing a prefix collide onto one branch). We combine a readable,
    git-ref-safe slug of the id with a stable 16-hex SHA-1 of the full id, so
    distinct ids always map to distinct, valid branch names.
    """
    sid = str(session_id)
    digest = hashlib.sha1(sid.encode("utf-8")).hexdigest()[:16]
    # Readable, git-ref-safe slug of the id (no spaces/illegal chars); the hash
    # guarantees uniqueness even when the slug is empty or shared.
    slug = re.sub(r"[^A-Za-z0-9._-]", "-", sid)[:24].strip("-/.") or "s"
    return BRANCH_PREFIX + slug + "-" + digest


def _is_under(child: Path, parent: Path) -> bool:
    """True iff ``child`` is ``parent`` or nested under it (safety check)."""
    try:
        child = Path(child).resolve()
        parent = Path(parent).resolve()
    except (OSError, ValueError):
        return False
    return child == parent or parent in child.parents


# ── git plumbing ────────────────────────────────────────────────────────────

def _git(repo, args, timeout=_GIT_TIMEOUT):
    """Run ``git -C <repo> <args>``; return ``(ok, returncode, stdout, stderr)``.

    Never raises for a non-zero git exit — returns ``ok=False`` instead. A
    missing git binary / timeout / OSError is also folded into ``ok=False`` with
    an explanatory ``stderr`` so callers degrade gracefully.
    """
    cmd = ["git", "-C", str(repo)] + [str(a) for a in args]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            creationflags=_paths.NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, None, "", "git invocation failed: %s" % exc
    return (proc.returncode == 0, proc.returncode,
            proc.stdout or "", proc.stderr or "")


def _is_git_repo(folder) -> bool:
    """Best-effort: is ``folder`` inside a git work tree?"""
    if not folder:
        return False
    try:
        git_dir = Path(folder) / ".git"
        return git_dir.exists()
    except (OSError, ValueError):
        return False


def _repo_for_project(project_id: str):
    """Return the project's repo folder_path, or ``None`` if unresolvable."""
    proj = _rnd.get_project(project_id)
    if not proj:
        return None
    folder = proj.get("folder_path") or ""
    return folder or None


# ── create / remove / reap ──────────────────────────────────────────────────

def create_worktree(project_id, session_id, base=None, start_point=None):
    """Create a worktree + branch for a session. Returns a status dict.

    Resolves the project's git repo (``rnd_registry.get_project(pid)
    ["folder_path"]``), then ``git worktree add -b <branch> <path>`` at
    ``managed_base()/<session_id>`` (outside the tracked tree). The branch name
    is deterministic from the session id (:func:`branch_for`).

    Returns ``{"ok": True, "path": str, "branch": str}`` on success, else
    ``{"ok": False, "reason": ..., "detail": ...}`` (unknown project, not a git
    repo, git failure) — never raises.
    """
    if project_id == "__dashboard__":
        return {"ok": True, "path": str(base) if base else _paths.data_dir().parent.as_posix(), "branch": "dashboard-root"}
    folder = _repo_for_project(project_id)
    if folder is None:
        return {"ok": False, "reason": "unknown-project",
                "project_id": project_id}
    if not _is_git_repo(folder):
        return {"ok": False, "reason": "not-a-git-repo", "folder": str(folder)}

    path = worktree_path_for(session_id, base)
    branch = branch_for(session_id)
    managed_base(base).mkdir(parents=True, exist_ok=True)

    # If the target path already exists, treat it as already-created (idempotent
    # enough for a retry) only when git already lists it; otherwise it's a
    # conflict we refuse to clobber.
    if path.exists():
        if _worktree_is_registered(folder, path):
            return {"ok": True, "path": str(path), "branch": branch,
                    "already": True}
        return {"ok": False, "reason": "path-exists", "path": str(path)}

    # Resolve the start point = repo's current HEAD, so the fresh branch is
    # rooted at HEAD's tip. Fall back to a sane default branch if HEAD can't be
    # resolved (e.g. an unusual but committed repo).
    if start_point is None:
        ok_h, _rc_h, out_h, _err_h = _git(folder, ["rev-parse", "HEAD"])
        if ok_h and out_h.strip():
            start_point = out_h.strip()
        else:
            start_point = "HEAD"

    # ALWAYS create a FRESH branch (``-b``) off the resolved start point — never
    # silently attach to a pre-existing branch and inherit its tip. If the branch
    # already exists, fail clearly rather than reuse it.
    args = ["worktree", "add", "-b", branch, str(path), str(start_point)]
    ok, rc, out, err = _git(folder, args)
    if not ok:
        if "already exists" in (err or "").lower():
            return {"ok": False, "reason": "branch-exists", "branch": branch,
                    "detail": (err or out).strip()}
        return {"ok": False, "reason": "git-worktree-add-failed",
                "detail": (err or out).strip(), "returncode": rc}
    return {"ok": True, "path": str(path), "branch": branch}


def _worktree_is_registered(repo, path) -> bool:
    """True iff git lists ``path`` as a worktree of ``repo``."""
    ok, _rc, out, _err = _git(repo, ["worktree", "list", "--porcelain"])
    if not ok:
        return False
    target = str(Path(path).resolve())
    for line in out.splitlines():
        if line.startswith("worktree "):
            wt = line[len("worktree "):].strip()
            try:
                if str(Path(wt).resolve()) == target:
                    return True
            except (OSError, ValueError):
                continue
    return False


def remove_worktree(session_id, project_id=None, base=None, force=True):
    """Remove a session's managed worktree (and prune). Returns a status dict.

    SAFETY: only ever operates on the deterministic managed path
    (``managed_base()/<session_id>``) — it refuses any path NOT under the managed
    base, so it can never remove an arbitrary directory.

    Uses ``git worktree remove [--force]`` when the owning repo is resolvable,
    then falls back to a directory delete + ``git worktree prune`` so an
    already-detached/orphaned dir is still cleaned. Tolerates an already-gone
    worktree (``{"ok": True, "removed": False, "reason": "already-gone"}``).
    Never raises.
    """
    path = worktree_path_for(session_id, base)
    base_dir = managed_base(base)

    if not _is_under(path, base_dir):
        return {"ok": False, "reason": "unsafe-path", "path": str(path)}

    existed = path.exists()

    # Resolve the owning repo (explicit project_id, else best-effort skip).
    repo = _repo_for_project(project_id) if project_id is not None else None

    git_removed = False
    if repo and _is_git_repo(repo):
        ok, _rc, _out, _err = _git(
            repo, ["worktree", "remove"] + (["--force"] if force else [])
            + [str(path)])
        git_removed = ok
        # Prune git's worktree admin records regardless.
        _git(repo, ["worktree", "prune"])
        # Delete the per-session branch so ``anchor/session/*`` refs don't
        # accumulate forever. Tolerate "already gone" / failure cleanly.
        _git(repo, ["branch", "-D", branch_for(session_id)])

    # Fallback hard-delete if git didn't take the dir down but it's still there.
    if path.exists():
        try:
            shutil.rmtree(path, ignore_errors=True)
        except OSError:
            pass

    if not existed and not path.exists():
        return {"ok": True, "removed": False, "reason": "already-gone",
                "path": str(path)}
    return {"ok": True, "removed": not path.exists(), "git_removed": git_removed,
            "path": str(path)}


def list_managed_worktrees(base=None) -> list:
    """Return the session ids that currently have a managed worktree on disk."""
    base_dir = managed_base(base)
    if not base_dir.exists():
        return []
    out = []
    try:
        for child in base_dir.iterdir():
            if child.is_dir():
                out.append(child.name)
    except OSError:
        return []
    return out


def _is_parked_idle(session_id):
    """True if ``session_id``'s registry record is parked at ``STATUS_IDLE`` (W6).

    The crucible-improve W6 graceful panel "×" CLOSE stops the PTY but KEEPS the
    worktree + registry record at ``STATUS_IDLE`` so the session is resumable WARM
    (W3/W4). The boot orphan-reaper must therefore KEEP such a worktree even though
    it has no live PTY — otherwise a parked session's worktree is reaped on restart
    and the work is lost. Best-effort: any registry-lookup failure → NOT parked
    (the pre-W6 reap behavior), never raises. Imported lazily to avoid a
    module-load cycle (``session_registry`` is a higher-level module).
    """
    try:
        import session_registry as _sr
        rec = _sr.get_session(session_id)
        return bool(rec) and rec.get("status") == _sr.STATUS_IDLE
    except Exception:
        return False


def reaper_dryrun_marker(base=None) -> Path:
    """Path to the persistent 'first post-move boot is dry-run' marker."""
    return managed_base(base) / REAPER_DRYRUN_MARKER


def arm_reaper_dryrun(base=None) -> Path:
    """Arm the persistent reaper dry-run (the migration calls this post-move).

    Creates the marker under the managed base so the NEXT :func:`reap_orphans`
    (typically the first post-move boot) is report-only. Idempotent; best-effort
    (a filesystem error is swallowed — arming is a safety belt, not a hard dep).
    Returns the marker path.
    """
    marker = reaper_dryrun_marker(base)
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        if not marker.exists():
            marker.write_text(
                "reaper armed report-only after data-dir migration (W11/C6);"
                " cleared automatically after one clean sweep.\n",
                encoding="utf-8")
    except OSError:
        pass
    return marker


def reaper_dryrun_active(base=None, env=None) -> bool:
    """Is the reaper in report-only mode? (env override OR the armed marker)."""
    e = os.environ if env is None else env
    raw = (e.get(REAPER_DRYRUN_ENV) or "").strip().lower()
    if raw in ("1", "true", "yes", "on", "dryrun"):
        return True
    try:
        return reaper_dryrun_marker(base).exists()
    except OSError:
        return False


def _disarm_reaper_dryrun(base=None) -> None:
    """Clear the marker so live reaping is re-armed on the next boot."""
    try:
        marker = reaper_dryrun_marker(base)
        if marker.exists():
            marker.unlink()
    except OSError:
        pass


def reap_orphans(active_session_ids, base=None, project_id=None, dryrun=None):
    """Remove managed worktrees whose session id is NOT in the active set.

    Sweeps ``managed_base()`` for ``<session_id>`` dirs; any whose id is not in
    ``active_session_ids`` is removed (via :func:`remove_worktree`, which keeps
    the safety check + git prune). ``project_id``, if given, lets git remove the
    worktree cleanly; otherwise the dir is hard-deleted and a global prune is
    skipped (git's per-repo prune needs the repo). Returns what it reaped::

        {"reaped": [session_id, ...], "kept": [session_id, ...],
         "would_reap": [...], "dryrun": bool, "errors": [{...}]}

    crucible-improve W6: a worktree whose registry record is parked at
    ``STATUS_IDLE`` (a graceful panel "×" close) is KEPT even when it has no live
    PTY — such a session is reopenable/resumable and its worktree must survive a
    restart (see :func:`_is_parked_idle`). The boot caller passes the live-PTY ids
    as ``active_session_ids``; the IDLE keep is consulted from the registry here so
    it holds for that caller AND a direct call.

    W11 (C6) — DRY-RUN: on the first post-move boot the reaper must NOT delete a
    worktree it can no longer resolve because a path-rewrite miss left the record
    stale. ``dryrun`` (env ``ANCHOR_REAPER_DRYRUN`` or the armed marker when the
    arg is ``None``) makes the sweep REPORT-ONLY — it fills ``would_reap`` and
    deletes nothing. When a dry sweep is CLEAN (nothing would be reaped and no
    errors) the marker is cleared, RE-ARMING live reaping for the next boot; an
    unclean dry report keeps the marker so nothing is ever wrongly deleted from a
    path miss.

    Never raises.
    """
    if dryrun is None:
        dryrun = reaper_dryrun_active(base)
    active = set(active_session_ids or ())
    reaped, kept, would_reap, errors = [], [], [], []
    for sid in list_managed_worktrees(base):
        if sid in active or _is_parked_idle(sid):
            kept.append(sid)
            continue
        if dryrun:
            would_reap.append(sid)
            continue
        res = remove_worktree(sid, project_id=project_id, base=base)
        if res.get("ok"):
            reaped.append(sid)
        else:
            errors.append({"session_id": sid,
                           "reason": res.get("reason", "remove-failed")})
    if dryrun and not would_reap and not errors:
        # A clean dry sweep: re-arm live reaping for the next boot.
        _disarm_reaper_dryrun(base)
    return {"reaped": reaped, "kept": kept, "would_reap": would_reap,
            "dryrun": bool(dryrun), "errors": errors}


# ── git-ignore safety (managed base under .anchor/) ─────────────────────────

def ensure_gitignored() -> None:
    """Ensure the managed ``worktrees/`` base is git-ignored under ``.anchor/``.

    Only relevant when the base lives under the data dir's ``.anchor/`` (the
    default). Idempotent and best-effort: a managed worktree must NEVER be
    tracked by the host repo. Appends a ``worktrees/`` rule to
    ``.anchor/.gitignore`` if not already present.
    """
    base = managed_base()
    anchor_dir = (_paths.data_dir() / ".anchor").resolve()
    if not _is_under(base, anchor_dir):
        return  # custom base elsewhere — nothing to add here
    gi = anchor_dir / ".gitignore"
    rule = "worktrees/"
    try:
        anchor_dir.mkdir(parents=True, exist_ok=True)
        existing = gi.read_text(encoding="utf-8") if gi.exists() else ""
        if rule not in existing.split():
            with _paths.WRITE_LOCK:
                text = gi.read_text(encoding="utf-8") if gi.exists() else ""
                if rule not in text.split():
                    sep = "" if text.endswith("\n") or not text else "\n"
                    gi.write_text(
                        text + sep
                        + "\n# Managed git worktrees for live sessions"
                          " (v3 Mission Control) — never tracked.\n"
                        + rule + "\n",
                        encoding="utf-8",
                    )
    except OSError:
        pass
