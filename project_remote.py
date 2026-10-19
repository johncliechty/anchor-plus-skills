#!/usr/bin/env python3
"""Anchor project ↔ GitHub remote linking + auto-push (stdlib only).

v8 "Durable Artifacts" (IMPLEMENTATION-PLAN Wave 3 — the offsite layer). Once a
project's documents are durable (Wave 2 persists + commits them), an OPT-IN
GitHub remote lets that work survive offsite and auto-push on session finish.

Three best-effort, never-raising helpers, all routed through an INJECTABLE seam
so tests never touch the real network / real ``gh`` / real github.com:

- :func:`link_github` — link the project's repo to a GitHub remote. ``mode``:

  * ``'create'`` → ``gh repo create <name> --private --source . --remote origin``
    (a brand-new PRIVATE repo) THROUGH the ``ANCHOR_GH_CMD`` seam. The seam env
    var mirrors ``ANCHOR_RUNNER_CMD``: when set, its command is run INSTEAD of the
    real ``gh`` binary (tests point it at ``tests/stub_gh.py`` which prints a fake
    URL). When the seam is unset AND a real authed ``gh`` is absent → degrade
    cleanly to ``{"ok": False, "reason": "gh-unavailable", "suggest": "paste-url"}``.
  * ``'existing'`` → ``git remote add origin <url>`` (a purely LOCAL git op — real
    git in a temp repo is fine, no network).

  On success it PERSISTS the remote url on the project's registry record
  (:func:`rnd_registry.set_remote`) and returns ``{"ok": True, "remote_url": ...}``.

- :func:`set_auto_push` / :func:`get_auto_push` — the per-project auto-push opt-in
  flag, persisted on the registry record.

- :func:`push_project` — ``git push -u origin <current-branch>`` (NETWORK in prod;
  in tests the "remote" is a LOCAL BARE repo at a ``file://`` path so a real push
  has no network). Never raises — returns a status dict.

REUSE :func:`worktrees._git` for every LOCAL git invocation (never forks the
subprocess call). ``git`` + ``gh`` are external CLIs (subprocess), not python
deps — every entry point degrades gracefully when they are absent. Stdlib only.
"""

import os
import re
import shlex
import subprocess
from pathlib import Path

import paths as _paths
import worktrees as _wt
import rnd_registry as _rnd


#: Env var overriding the ``gh`` command (the NETWORK seam — tests stub it). When
#: set, its (shlex-split) command is run INSTEAD of the real ``gh`` binary, with
#: the ``gh`` sub-args appended. Mirrors ``ANCHOR_RUNNER_CMD``.
GH_CMD_ENV = "ANCHOR_GH_CMD"

#: Bounded timeout (seconds) for a gh/push invocation — a hung network call must
#: never wedge the server.
_NET_TIMEOUT = 90


# ── gh seam ──────────────────────────────────────────────────────────────────

def _gh_base_cmd():
    """The base ``gh`` command, honoring the ``ANCHOR_GH_CMD`` seam.

    Returns a list to which gh sub-args are appended. When the seam is set we run
    that command (e.g. ``python tests/stub_gh.py``) instead of the real ``gh`` —
    so a test never hits the network. Returns ``None`` only if the seam is set to
    an unparseable value.
    """
    raw = os.environ.get(GH_CMD_ENV)
    if raw and raw.strip():
        try:
            return shlex.split(raw)
        except ValueError:
            return None
    return ["gh"]


def _run_gh(args, cwd, timeout=_NET_TIMEOUT):
    """Run the (seam-aware) ``gh`` command; return ``(ok, rc, stdout, stderr)``.

    Never raises — a missing ``gh`` binary / timeout / OSError folds into
    ``ok=False`` with an explanatory ``stderr`` so callers degrade gracefully.
    """
    base = _gh_base_cmd()
    if base is None:
        return False, None, "", "gh seam misconfigured"
    cmd = list(base) + [str(a) for a in args]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, cwd=str(cwd),
            creationflags=_paths.NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, None, "", "gh invocation failed: %s" % exc
    return (proc.returncode == 0, proc.returncode,
            proc.stdout or "", proc.stderr or "")


def _looks_like_missing_gh(stderr) -> bool:
    """Heuristic: does the gh failure look like an absent/un-authed gh CLI?"""
    s = (stderr or "").lower()
    return ("invocation failed" in s
            or "no such file" in s
            or "not found" in s
            or "cannot find" in s
            or "is not recognized" in s
            or "not logged" in s
            or "authentication" in s
            or "gh auth" in s)


#: Match the first http(s)/ssh GitHub-ish URL in arbitrary gh output.
_URL_RE = re.compile(
    r"(https?://[^\s'\"]+|git@[^\s'\"]+:[^\s'\"]+\.git)")


def _parse_repo_url(text) -> str:
    """Best-effort: pull the repo URL out of ``gh repo create`` output."""
    m = _URL_RE.search(text or "")
    return m.group(1).strip() if m else ""


# ── link ─────────────────────────────────────────────────────────────────────

def _folder_ok(folder):
    try:
        path = Path(folder)
        if not folder or not path.exists() or not path.is_dir():
            return None
        return path
    except (OSError, ValueError):
        return None


def _current_remote_url(folder):
    """Return the configured ``origin`` url, or ``""`` if none."""
    ok, _rc, out, _err = _wt._git(folder, ["remote", "get-url", "origin"])
    return out.strip() if ok else ""


def _persist_remote(project_id, remote_url):
    """Best-effort: store the remote url on the project record."""
    if not project_id:
        return
    try:
        _rnd.set_remote(project_id, remote_url)
    except Exception:
        pass


def link_github(folder, mode, value, project_id=None) -> dict:
    """Link the project repo to a GitHub remote. Best-effort; never raises.

    ``mode='create'`` → create a NEW PRIVATE repo via the ``gh`` seam and wire
    ``origin``; ``mode='existing'`` → ``git remote add origin <value>`` (local).
    On success the remote url is persisted on the project record (when
    ``project_id`` is given). Returns ``{"ok", "remote_url", ...}`` or a clean
    ``{"ok": False, "reason": ...}``. For ``create`` with gh absent/un-authed it
    degrades to ``{"ok": False, "reason": "gh-unavailable", "suggest": "paste-url"}``.
    """
    path = _folder_ok(folder)
    if path is None:
        return {"ok": False, "reason": "path-missing", "folder": str(folder)}
    if not _wt._is_git_repo(path):
        return {"ok": False, "reason": "not-a-git-repo", "folder": str(path)}

    mode = (mode or "").strip().lower()

    if mode == "existing":
        url = (value or "").strip()
        if not url:
            return {"ok": False, "reason": "missing-url"}
        # If an origin already exists, set-url (idempotent re-link) rather than
        # fail on "remote origin already exists".
        if _current_remote_url(path):
            ok, _rc, _out, err = _wt._git(
                path, ["remote", "set-url", "origin", url])
        else:
            ok, _rc, _out, err = _wt._git(
                path, ["remote", "add", "origin", url])
        if not ok:
            return {"ok": False, "reason": "git-remote-add-failed",
                    "detail": (err or "").strip()}
        _persist_remote(project_id, url)
        return {"ok": True, "mode": "existing", "remote_url": url,
                "linked": True}

    if mode == "create":
        name = (value or "").strip() or path.name
        # gh repo create <name> --private --source . --remote origin
        # creates the repo AND wires origin in one shot. Through the seam so a
        # test prints a fake URL and never hits github.com.
        ok, _rc, out, err = _run_gh(
            ["repo", "create", name, "--private",
             "--source", ".", "--remote", "origin"], cwd=path)
        if not ok:
            if _looks_like_missing_gh(err) or _looks_like_missing_gh(out):
                return {"ok": False, "reason": "gh-unavailable",
                        "suggest": "paste-url",
                        "detail": (err or out or "").strip()}
            return {"ok": False, "reason": "gh-create-failed",
                    "detail": (err or out or "").strip()}
        url = _parse_repo_url(out) or _parse_repo_url(err)
        if not url:
            # gh may have wired origin without echoing a clean URL — read it back.
            url = _current_remote_url(path)
        # Ensure origin is wired even if the seam stub didn't (real gh --source .
        # does this; a minimal stub may only print the URL).
        if url and not _current_remote_url(path):
            _wt._git(path, ["remote", "add", "origin", url])
        if not url:
            return {"ok": False, "reason": "no-url-parsed",
                    "detail": (out or err or "").strip()}
        _persist_remote(project_id, url)
        return {"ok": True, "mode": "create", "remote_url": url,
                "linked": True, "private": True}

    return {"ok": False, "reason": "bad-mode", "mode": mode}


# ── auto-push opt-in ─────────────────────────────────────────────────────────

def set_auto_push(project_id, enabled) -> dict:
    """Persist the per-project auto-push opt-in flag. Best-effort; never raises."""
    try:
        return _rnd.set_auto_push(project_id, bool(enabled))
    except Exception as exc:
        return {"ok": False, "reason": "persist-failed", "detail": str(exc)}


def get_auto_push(project_id) -> bool:
    """Read the per-project auto-push opt-in flag (default False)."""
    try:
        proj = _rnd.get_project(project_id)
        return bool(proj and proj.get("auto_push"))
    except Exception:
        return False


def is_linked(project_id) -> bool:
    """True iff the project has a persisted remote url."""
    try:
        proj = _rnd.get_project(project_id)
        return bool(proj and (proj.get("remote_url") or "").strip())
    except Exception:
        return False


def remote_status(project_id) -> dict:
    """Read-only view: ``{linked, remote_url, auto_push}`` for the project."""
    proj = None
    try:
        proj = _rnd.get_project(project_id)
    except Exception:
        proj = None
    if not proj:
        return {"linked": False, "remote_url": "", "auto_push": False}
    url = (proj.get("remote_url") or "").strip()
    return {"linked": bool(url), "remote_url": url,
            "auto_push": bool(proj.get("auto_push"))}


# ── push ─────────────────────────────────────────────────────────────────────

def _current_branch(folder):
    ok, _rc, out, _err = _wt._git(folder, ["rev-parse", "--abbrev-ref", "HEAD"])
    b = out.strip() if ok else ""
    return b or "HEAD"


def push_project(folder, project_id=None) -> dict:
    """``git push -u origin <current-branch>``. Best-effort; never raises.

    In tests the configured ``origin`` is a LOCAL BARE repo (a ``file://`` path),
    so a real push has NO network. Returns ``{"ok", "pushed", "branch", ...}``.
    A project with no configured ``origin`` returns
    ``{"ok": False, "reason": "no-remote"}`` (never an exception).
    """
    path = _folder_ok(folder)
    if path is None:
        return {"ok": False, "reason": "path-missing", "pushed": False}
    if not _wt._is_git_repo(path):
        return {"ok": False, "reason": "not-a-git-repo", "pushed": False}
    if not _current_remote_url(path):
        return {"ok": False, "reason": "no-remote", "pushed": False}

    branch = _current_branch(path)
    ok, _rc, out, err = _wt._git(
        path, ["push", "-u", "origin", branch], timeout=_NET_TIMEOUT)
    if not ok:
        return {"ok": False, "reason": "push-failed", "pushed": False,
                "branch": branch, "detail": (err or out or "").strip()}
    return {"ok": True, "pushed": True, "branch": branch}


def auto_push_if_opted(project_id) -> dict:
    """Push the project's repo ONLY when it is linked AND auto-push is opted-in.

    Wired into the session-finish path: a non-linked OR non-opted project never
    pushes. Best-effort + never raises. Returns a status dict including a
    ``{"pushed": False, "reason": "not-linked"|"not-opted"}`` skip explanation.
    """
    try:
        if not is_linked(project_id):
            return {"ok": True, "pushed": False, "reason": "not-linked"}
        if not get_auto_push(project_id):
            return {"ok": True, "pushed": False, "reason": "not-opted"}
        proj = _rnd.get_project(project_id)
        folder = (proj or {}).get("folder_path", "")
        if not folder:
            return {"ok": False, "pushed": False, "reason": "no-folder"}
        return push_project(folder, project_id)
    except Exception as exc:
        return {"ok": False, "pushed": False, "reason": "error",
                "detail": str(exc)}
