#!/usr/bin/env python3
"""Anchor R&D project on-disk move — the guarded atomic folder move (stdlib only).

v9 Wave 4 "Tidy" (the HIGH-RISK wave; MASTER-PLAN Risk R3). Wave 3 added a
dashboard-only ``group`` field (no disk move). This module makes the DEV TREE
mirror those folders — *safely*. It moves a project's directory into a
group-named subfolder of its current parent, re-points the registry
``folder_path`` + the managed git worktrees + ``discovery.json``, and ROLLS BACK
fully on any failure.

The move is GUARDED — it REFUSES (no filesystem change) when moving would
corrupt the running server or a live session:

- **refused-anchor-repo:** the project's ``folder_path`` IS the running Anchor
  code dir (``paths.CODE_DIR``). Moving the live server out from under itself is
  never allowed.
- **refused-live-sessions:** the project has any managed session whose registry
  status is ``running`` — a live PTY/worktree must not have its repo yanked.

Everything is testable on TEMP dirs: the move uses ``shutil.move`` +
``worktrees._git`` (both injectable / hermetic), and tests pass a TEMP
``projects_root`` + a TEMP registry + a TEMP worktree base — NEVER the live
registry, the real Anchor repo, or ``:8777``.

Stdlib only (``shutil``, ``pathlib``, ``re``). No third-party imports.
"""

import re
import shutil
from pathlib import Path

import paths as _paths
import rnd_registry as _rnd
import worktrees as _wt

#: Max length of a slugified group folder name (a sane upper bound).
_SLUG_MAX = 80


def slug_group(group: str) -> str:
    """Filesystem-safe slug for a group name → a single directory name.

    Lower-cased, non-alphanumerics collapsed to a single ``-``, trimmed. Empty /
    unusable input yields ``""`` (the caller treats that as "Ungrouped" — a move
    back to the root, no group subfolder).
    """
    s = (group or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:_SLUG_MAX].strip("-")


def _norm(p) -> str:
    """Normalized absolute string form of a path (best-effort, never raises)."""
    try:
        return str(Path(p).resolve())
    except (OSError, ValueError, TypeError):
        return str(p)


def is_anchor_repo(folder_path) -> bool:
    """True iff ``folder_path`` IS the running Anchor code dir (``paths.CODE_DIR``).

    Compared on resolved/normalized paths so a relative or differently-cased
    form still matches. This is the hard guard that refuses to move the live
    server's own repo out from under itself.
    """
    if not folder_path:
        return False
    return _norm(folder_path) == _norm(_paths.CODE_DIR)


def has_live_sessions(project_id: str) -> bool:
    """True iff the project has any managed session in the ``running`` status.

    Best-effort: a missing/unreadable session registry yields ``False`` (no
    block) rather than crashing the move. Reuses the existing
    ``session_registry`` primitive — never forks the status logic.
    """
    try:
        import session_registry as _sr
    except Exception:
        return False
    try:
        running = _sr.list_sessions(project_id=project_id,
                                    status=_sr.STATUS_RUNNING)
    except Exception:
        return False
    return bool(running)


def _rescan(project_id: str) -> None:
    """Regenerate the moved project's ``discovery.json`` (``root``) via the
    existing rescan pipeline. Best-effort — a rescan failure must not fail the
    move (the move itself already succeeded). Imported lazily to avoid a hard
    import cycle (``anchor_gui`` imports this module's siblings)."""
    try:
        import anchor_gui as _gui
    except Exception:
        return
    try:
        _gui.discover_and_adopt(project_id)
    except Exception:
        pass


def move_to_group(project_id, group, projects_root=None,
                  *, rescan=True):
    """Guarded ATOMIC move of a project's directory into a group subfolder.

    Sequence (each step rolls back ALL prior steps on failure):

      0. REFUSE (no fs change) if the project is the running Anchor code dir
         (``refused-anchor-repo``) or has any live (running) session
         (``refused-live-sessions``).
      1. Resolve the destination: ``<projects_root>/<slug(group)>/<dir-name>``
         where ``projects_root`` defaults to the project's CURRENT parent dir.
         An empty ``group`` ("Ungrouped") moves the dir to ``<projects_root>/
         <dir-name>`` (no group subfolder) — a no-op when already there.
      2. ``shutil.move(src, dest)`` the directory.
      3. ``update_project(folder_path=dest)`` + ``set_group(group)``.
      4. ``git worktree prune`` in the moved repo + reconcile managed worktrees
         (best-effort — a non-git folder is fine).
      5. Regenerate ``discovery.json`` via the existing rescan.

    Returns ``{"ok": True, "from": src, "to": dest, "group": group}`` on
    success, or ``{"ok": False, "reason": ...}`` (incl. the refusal reasons)
    otherwise. NEVER raises into the caller — a mid-move failure is rolled back
    (dir moved back + ``folder_path`` restored) and reported as
    ``{"ok": False, "reason": "move-failed", ...}``.
    """
    proj = _rnd.get_project(project_id)
    if proj is None:
        return {"ok": False, "reason": "unknown-project",
                "project_id": project_id}

    src = proj.get("folder_path", "") or ""
    if not src:
        return {"ok": False, "reason": "no-folder-path",
                "project_id": project_id}

    # ── Guard 0a: never move the running Anchor repo. ────────────────────────
    if is_anchor_repo(src):
        return {"ok": False, "reason": "refused-anchor-repo",
                "project_id": project_id, "folder_path": src}

    # ── Guard 0b: never move a project with a live (running) session. ────────
    if has_live_sessions(project_id):
        return {"ok": False, "reason": "refused-live-sessions",
                "project_id": project_id}

    src_path = Path(src)
    if not src_path.is_dir():
        return {"ok": False, "reason": "src-missing", "from": str(src_path)}

    # ── Resolve destination. ─────────────────────────────────────────────────
    root = Path(projects_root) if projects_root else src_path.parent
    dir_name = src_path.name
    slug = slug_group(group)
    dest_path = (root / slug / dir_name) if slug else (root / dir_name)

    # No-op: already exactly where it would go (e.g. Ungrouped → root and the
    # dir already sits at the root). Still re-label the group + (optionally)
    # rescan so the registry stays consistent, but no fs move.
    if _norm(dest_path) == _norm(src_path):
        try:
            _rnd.update_project(project_id, folder_path=str(src_path))
            _rnd.set_group(project_id, group or "")
        except Exception as exc:
            return {"ok": False, "reason": "group-update-failed",
                    "detail": str(exc), "from": str(src_path)}
        return {"ok": True, "from": str(src_path), "to": str(src_path),
                "group": group or "", "moved": False}

    if dest_path.exists():
        return {"ok": False, "reason": "dest-exists", "to": str(dest_path)}

    # Create the group folder if absent (the parent of dest).
    try:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {"ok": False, "reason": "mkdir-failed", "detail": str(exc),
                "to": str(dest_path)}

    # ── Step 2: the directory move. ──────────────────────────────────────────
    moved = False
    try:
        shutil.move(str(src_path), str(dest_path))
        moved = True

        # ── Step 3: re-point the registry. ───────────────────────────────────
        _rnd.update_project(project_id, folder_path=str(dest_path))
        _rnd.set_group(project_id, group or "")

        # ── Step 4: prune + reconcile managed worktrees (best-effort). ───────
        # The managed worktree base is OUTSIDE the project (under the data dir /
        # ANCHOR_WORKTREE_BASE), so the move does not relocate worktrees — but
        # git's per-worktree admin records in the moved repo may dangle. Prune
        # them so a subsequent create_worktree on the moved repo is clean.
        if _wt._is_git_repo(str(dest_path)):
            _wt._git(str(dest_path), ["worktree", "prune"])

        # ── Step 5: regenerate discovery.json (root) via the existing rescan. ─
        if rescan:
            _rescan(project_id)
    except Exception as exc:
        # ── ROLLBACK: undo whatever we did, in reverse. ──────────────────────
        if moved:
            try:
                # Move the dir back to its original location.
                if dest_path.exists() and not src_path.exists():
                    shutil.move(str(dest_path), str(src_path))
            except Exception:
                pass
        try:
            _rnd.update_project(project_id, folder_path=str(src_path))
            _rnd.set_group(project_id, proj.get("group", "") or "")
        except Exception:
            pass
        return {"ok": False, "reason": "move-failed", "detail": str(exc),
                "from": str(src_path), "to": str(dest_path),
                "rolled_back": True}

    return {"ok": True, "from": str(src_path), "to": str(dest_path),
            "group": group or "", "moved": True}
