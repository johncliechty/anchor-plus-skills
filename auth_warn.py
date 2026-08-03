"""ANCHOR_AUTH_WARN — the log-only would-401 recorder for the C2 soak (rearch W8).

The re-architecture flips the gated data plane (``/artifact``, ``/report``,
``/summary``, ``/project``, ``/api/rnd/projects``, ``/api/rnd/tail``,
``/api/rnd/jobs``) from ``open`` → ``token`` in two steps so nothing breaks:

  * **W8 — warn (this module).** With ``ANCHOR_AUTH_MODE=warn`` (or the
    compatibility alias ``ANCHOR_AUTH_WARN=1``) the server STILL serves those
    routes, but every request that WOULD have been 401'd once enforcement is on
    (a token is configured and the request presented none/a wrong one) is
    appended here as a structured JSONL line. A soak day of the live log is the
    W8 gate artifact: reviewed against the W2 consumer inventory, the flip to
    enforce ships only when every would-401 entry maps to a known consumer that
    has a token path.
  * **W9 — enforce.** Same routes, mode ``enforce`` → a real 401 for the
    tokenless request (and the table row flips ``open`` → ``token``).

Design notes:
  * **No secret is ever logged.** Only the path *without* its query string is
    recorded (a wrong ``?token=`` value never lands in the log); ``has_token``
    is a boolean saying whether the request presented *any* token, not its value.
  * **Append-only, atomic, stdlib only.** One JSON object per line under
    :data:`paths.WRITE_LOCK`; the file lives in the data dir (overridable via
    ``ANCHOR_AUTH_WARN_LOG`` for tests) so it rides the W11 data-dir migration.
  * **Reviewable.** :func:`summarize` and :func:`review_against_consumers` turn
    a raw log into the by-path counts and the unexplained-consumer set the gate
    checklist asserts is empty before the enforce flip.

The gated set is declared ONCE in :mod:`route_table` (``DATA_PLANE_GATED``) so the
server gate, the healthcheck row-walk, and this reviewer never drift apart.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import paths as _paths

#: Test/deploy override for the log location; unset → the data dir.
WARN_LOG_ENV = "ANCHOR_AUTH_WARN_LOG"
WARN_LOG_NAME = "auth-warn.log"

#: Mode strings (mirrors pillar_flags.FLAG_VALUES['auth']).
MODE_OPEN = "open"
MODE_WARN = "warn"
MODE_ENFORCE = "enforce"


def warn_log_path() -> Path:
    """Resolve the would-401 log path (``ANCHOR_AUTH_WARN_LOG`` or the data dir)."""
    raw = os.environ.get(WARN_LOG_ENV)
    if raw and raw.strip():
        return Path(raw).expanduser()
    return _paths.data_dir() / WARN_LOG_NAME


def _path_only(path: str) -> str:
    """The path with any query string stripped (never log a token value)."""
    p = path or ""
    for sep in ("?", "#"):
        i = p.find(sep)
        if i != -1:
            p = p[:i]
    return p


def record_would_401(method, path, *, remote=None, has_token=False,
                     user_agent=None, referer=None, mode=MODE_WARN, ts=None,
                     log_path=None) -> dict:
    """Append ONE would-401 entry and return it.

    Called by the server's data-plane gate for a tokenless request against a
    gated route while auth mode is ``warn`` or ``enforce``. Best-effort: a write
    failure never breaks the request (the caller wraps this in try/except), but
    we still raise nothing here beyond OS errors the caller swallows.
    """
    entry = {
        "ts": float(time.time() if ts is None else ts),
        "mode": mode,
        "method": (method or "").upper(),
        "path": _path_only(path),
        "remote": remote,
        "has_token": bool(has_token),
        "user_agent": user_agent,
        "referer": referer,
    }
    p = Path(log_path) if log_path is not None else warn_log_path()
    line = json.dumps(entry, ensure_ascii=False)
    with _paths.WRITE_LOCK:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    return entry


def read_entries(log_path=None) -> list:
    """Parse the JSONL warn log into a list of dicts (missing file → ``[]``)."""
    p = Path(log_path) if log_path is not None else warn_log_path()
    if not p.exists():
        return []
    out = []
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return []
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except ValueError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def summarize(log_path=None, entries=None) -> dict:
    """Roll a warn log up into review-ready counts.

    Returns ``{total, by_path, by_remote, tokenless, presented_wrong_token,
    paths}`` — the shape the soak-review gate artifact reports.
    """
    rows = read_entries(log_path) if entries is None else list(entries)
    by_path: dict = {}
    by_remote: dict = {}
    tokenless = 0
    wrong_token = 0
    for e in rows:
        path = e.get("path")
        by_path[path] = by_path.get(path, 0) + 1
        remote = e.get("remote")
        by_remote[remote] = by_remote.get(remote, 0) + 1
        if e.get("has_token"):
            wrong_token += 1
        else:
            tokenless += 1
    return {
        "total": len(rows),
        "by_path": by_path,
        "by_remote": by_remote,
        "tokenless": tokenless,
        "presented_wrong_token": wrong_token,
        "paths": sorted(k for k in by_path if k is not None),
    }


def _explained(path, known) -> bool:
    """True iff ``path`` maps to a known consumer route.

    ``known`` entries are route patterns — an EXACT path (``/api/rnd/jobs``) or a
    PREFIX (``/artifact/``). A logged path is concrete (``/artifact/abc123``), so
    a would-401 is *explained* when it equals or begins with a known pattern.
    """
    if not path:
        return False
    for k in known:
        if not k:
            continue
        if path == k or path.startswith(k):
            return True
    return False


def review_against_consumers(known_paths, log_path=None, entries=None) -> dict:
    """The W8 soak-review verdict: does every would-401 map to a known consumer?

    ``known_paths`` is the iterable of route patterns the W2 consumer inventory
    accounts for (a consumer with a token path is EXPECTED to be the source of a
    would-401 entry once auth is warned) — the gated data-plane batch itself plus
    any additional blessed paths. An entry whose concrete path matches NONE of
    them (by exact or prefix) is *unexplained* — the flip to enforce is HELD until
    it is triaged.

    Returns ``{ok, total, explained, unexplained_paths, unexplained_count}``.
    ``ok`` is True iff there are zero unexplained entries (the gate's green).
    """
    known = list(known_paths or ())
    rows = read_entries(log_path) if entries is None else list(entries)
    unexplained: dict = {}
    explained = 0
    for e in rows:
        path = e.get("path")
        if _explained(path, known):
            explained += 1
        else:
            unexplained[path] = unexplained.get(path, 0) + 1
    return {
        "ok": not unexplained,
        "total": len(rows),
        "explained": explained,
        "unexplained_paths": sorted(k for k in unexplained if k is not None)
        + ([None] if None in unexplained else []),
        "unexplained_count": sum(unexplained.values()),
    }
