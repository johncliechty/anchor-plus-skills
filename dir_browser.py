#!/usr/bin/env python3
"""Server-side directory browser (stdlib only).

Browsers cannot show a native folder picker, so the "+ New Project → select
existing" flow (Master Plan UX) needs the server to enumerate child
directories of a given path. This module is intentionally tiny and contained.

Safety:
- A missing / inaccessible / non-directory path returns a structured result
  with an ``error`` field — it never raises to the caller.
- Listing only returns child *directories* (not files), each with its absolute
  path, so the UI can drill down.

Stdlib only. No third-party imports.
"""

from pathlib import Path


def _drive_roots() -> list:
    """Best-effort list of root locations to start browsing from.

    On Windows, enumerate the available drive letters; elsewhere, ``/``.
    """
    roots = []
    import string
    import os

    if os.name == "nt":
        for letter in string.ascii_uppercase:
            root = f"{letter}:\\"
            if Path(root).exists():
                roots.append(root)
    if not roots:
        roots.append(str(Path(os.sep)))
    return roots


def browse(path=None) -> dict:
    """List the child directories of ``path``.

    Returns a dict:
        {
          "path": <resolved absolute path or None>,
          "parent": <absolute path of parent, or None at a root>,
          "dirs": [ {"name": ..., "path": ...}, ... ],   # child directories
          "roots": [...],                                 # drive roots
          "error": <str or None>,
        }

    A missing/inaccessible/non-directory ``path`` yields ``dirs == []`` and a
    populated ``error`` — never an exception.
    """
    result = {
        "path": None,
        "parent": None,
        "dirs": [],
        "roots": _drive_roots(),
        "error": None,
    }

    # No path → present the drive roots as the starting point.
    if path is None or str(path).strip() == "":
        return result

    try:
        p = Path(path).expanduser()
    except (TypeError, ValueError) as exc:
        result["error"] = f"invalid path: {exc}"
        return result

    try:
        p = p.resolve()
    except (OSError, RuntimeError):
        # resolve() can raise on some inaccessible paths; fall back to raw.
        pass

    result["path"] = str(p)

    if not p.exists():
        result["error"] = "path-missing"
        return result
    if not p.is_dir():
        result["error"] = "not-a-directory"
        # Still expose the parent so the UI can recover.
        try:
            result["parent"] = str(p.parent)
        except Exception:
            result["parent"] = None
        return result

    try:
        result["parent"] = str(p.parent) if p.parent != p else None
    except Exception:
        result["parent"] = None

    dirs = []
    try:
        for child in sorted(p.iterdir(), key=lambda c: c.name.lower()):
            try:
                if child.is_dir():
                    dirs.append({"name": child.name, "path": str(child)})
            except OSError:
                # A child we cannot stat (permission / junction) — skip it.
                continue
    except PermissionError:
        result["error"] = "permission-denied"
        return result
    except OSError as exc:
        result["error"] = f"os-error: {exc}"
        return result

    result["dirs"] = dirs
    return result
