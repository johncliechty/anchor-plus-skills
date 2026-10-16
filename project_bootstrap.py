#!/usr/bin/env python3
"""Anchor project bootstrap — auto git-init + starter CLAUDE.md (stdlib only).

v8 "Durable Artifacts" (IMPLEMENTATION-PLAN Wave 1; the keystone prerequisite).
Registering / opening / rescanning an R&D project must leave it in a state where
the trio can actually run: a git repo (so :func:`worktrees.create_worktree` no
longer dead-ends a session start with ``not-a-git-repo``) and a starter
``CLAUDE.md`` (so the keystone — Wave 2 doc persistence — has something to commit
and the model has project context).

Two best-effort, idempotent helpers:

- :func:`ensure_git_repo` — if ``folder`` is not a git repo, ``git init`` + an
  initial commit of the existing files (honoring any ``.gitignore``). A second
  call on an existing repo is a no-op. If ``git`` is genuinely unavailable it
  returns a clean ``{"ok": False, "reason": "git-unavailable"}`` WITHOUT raising.
- :func:`ensure_claude_md` — write a minimal starter ``CLAUDE.md`` only when one
  is absent; NEVER overwrites an existing one.

Both REUSE :func:`worktrees._git` (the single subprocess git wrapper) — git
invocation is never forked here. Stdlib only.
"""

from pathlib import Path

import worktrees as _wt


#: Minimal starter CLAUDE.md body (project name is filled in).
_STARTER_CLAUDE_MD = (
    "# {name}\n"
    "\n"
    "R&D project managed by Anchor — research/plan/build via the trio.\n"
)


def ensure_git_repo(folder) -> dict:
    """Idempotently make ``folder`` a git repo with an initial commit.

    Best-effort and idempotent:

    - if ``folder`` is already a git repo → no-op, returns
      ``{"ok": True, "initialized": False}``;
    - else ``git init`` + (config a local identity if none) + ``git add -A`` +
      ``git commit`` of the existing files, HONORING any ``.gitignore`` present
      (a normal ``add -A`` respects ignore rules) → returns
      ``{"ok": True, "initialized": True}``;
    - if ``git`` is genuinely unavailable (or any git step fails such that no
      repo could be made) → returns ``{"ok": False, "reason": ...}`` WITHOUT
      raising.

    Reuses :func:`worktrees._git` for every git invocation (never forks the
    subprocess call). Never raises.
    """
    try:
        path = Path(folder)
        if not folder or not path.exists() or not path.is_dir():
            return {"ok": False, "reason": "path-missing", "folder": str(folder)}
    except (OSError, ValueError):
        return {"ok": False, "reason": "path-missing", "folder": str(folder)}

    # Already a repo → no-op.
    if _wt._is_git_repo(path):
        return {"ok": True, "initialized": False}

    # git init. A missing git binary folds into ok=False (the _git wrapper turns
    # OSError into a clean failure tuple) → surface "git-unavailable".
    ok, _rc, _out, err = _wt._git(path, ["init"])
    if not ok:
        reason = "git-unavailable" if _looks_like_missing_git(err) else "git-init-failed"
        return {"ok": False, "reason": reason, "detail": (err or "").strip()}

    # Ensure a commit identity exists locally so the initial commit never fails
    # on a host without a global user.name/user.email. Best-effort, scoped to
    # this repo only (never touches the user's global config).
    have_email, _r, eout, _e = _wt._git(path, ["config", "user.email"])
    if not (have_email and (eout or "").strip()):
        _wt._git(path, ["config", "user.email", "anchor@localhost"])
    have_name, _r2, nout, _e2 = _wt._git(path, ["config", "user.name"])
    if not (have_name and (nout or "").strip()):
        _wt._git(path, ["config", "user.name", "Anchor"])

    # Stage everything (respecting .gitignore) and commit. An empty repo (no
    # files, or everything ignored) still yields a valid repo via an
    # allow-empty initial commit so create_worktree (which needs a HEAD) works.
    _wt._git(path, ["add", "-A"])
    okc, _rc2, _outc, errc = _wt._git(
        path, ["commit", "--allow-empty", "-m", "Initial commit (Anchor bootstrap)",
               "--no-gpg-sign"])
    if not okc:
        # The repo exists (init succeeded) but the commit failed — surface it,
        # but the repo is still real (subsequent calls will no-op).
        return {"ok": True, "initialized": True, "committed": False,
                "detail": (errc or "").strip()}
    return {"ok": True, "initialized": True, "committed": True}


def _looks_like_missing_git(stderr) -> bool:
    """Heuristic: does the git failure look like an absent git binary?"""
    s = (stderr or "").lower()
    return ("invocation failed" in s          # _git's OSError wrap
            or "no such file" in s
            or "not found" in s
            or "cannot find" in s
            or "is not recognized" in s)


def ensure_claude_md(folder, project_name) -> dict:
    """Write a minimal starter ``CLAUDE.md`` only when one is ABSENT.

    NEVER overwrites an existing ``CLAUDE.md``. Returns ``{"created": bool}``.
    Best-effort — a write failure (e.g. read-only dir) returns
    ``{"created": False, "reason": ...}`` WITHOUT raising.
    """
    try:
        path = Path(folder)
        if not folder or not path.is_dir():
            return {"created": False, "reason": "path-missing"}
    except (OSError, ValueError):
        return {"created": False, "reason": "path-missing"}

    claude = path / "CLAUDE.md"
    try:
        if claude.exists():
            return {"created": False, "reason": "exists"}
        name = str(project_name or "").strip() or path.name or "R&D Project"
        claude.write_text(_STARTER_CLAUDE_MD.format(name=name), encoding="utf-8")
        return {"created": True}
    except OSError as exc:
        return {"created": False, "reason": "write-failed", "detail": str(exc)}


def bootstrap_project(folder, project_name) -> dict:
    """Convenience: ensure a starter ``CLAUDE.md`` THEN ensure the git repo.

    CLAUDE.md first so the initial commit captures it. Best-effort — never
    raises. Returns ``{"claude_md": <ensure_claude_md result>,
    "git": <ensure_git_repo result>}``.
    """
    cm = ensure_claude_md(folder, project_name)
    git = ensure_git_repo(folder)
    return {"claude_md": cm, "git": git}
