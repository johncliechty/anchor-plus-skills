#!/usr/bin/env python3
"""Anchor usage index — one small file per project: the reader's file for delegated jobs.

codex-discipline Wave 2 S1 (2026-09-17), hardened in Wave 5 (2026-11-13) with
schema v2 token-breakdown normalization, cross-process file locking, atomic
PID/thread-scoped replacement, corrupt-line quarantine, and explicit unreadable
store classification. Stdlib only.
"""

from contextlib import contextmanager
import json
import os
import re
import threading
import time
from pathlib import Path

import paths as _paths
import journal as _journal

INDEX_DIRNAME = "usage_index"
ANCHOR_DIRNAME = ".anchor"
INDEX_SCHEMA_VERSION = 2
DEFAULT_LOCK_TIMEOUT_S = 5.0

_UNSAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_LOCK_TLS = threading.local()


class LockBusyError(TimeoutError):
    """Raised when a cross-process usage_index lock cannot be acquired in time."""


class IndexUnreadableError(OSError):
    """Raised when a project's usage_index or meta store is unreadable or corrupt."""


def index_dir() -> Path:
    """Absolute path to the index dir (``.anchor/usage_index/``). Not created."""
    return _paths.data_dir() / ANCHOR_DIRNAME / INDEX_DIRNAME


def _safe_id(project_id) -> str:
    s = _UNSAFE_NAME_RE.sub("_", str(project_id or "").strip())
    return s or "unknown"


def index_path(project_id) -> Path:
    """Absolute path to one project's index file. Not created."""
    return index_dir() / f"{_safe_id(project_id)}.jsonl"


def lock_path(project_id) -> Path:
    """Absolute path to one project's cross-process lock file. Not created."""
    return index_dir() / f"{_safe_id(project_id)}.lock"


def meta_path(project_id) -> Path:
    """Absolute path to one project's index metadata JSON file. Not created."""
    return index_dir() / f"{_safe_id(project_id)}.meta.json"


def quarantine_path(project_id) -> Path:
    """Absolute path to one project's quarantined-lines JSONL file. Not created."""
    return index_dir() / f"{_safe_id(project_id)}.quarantine.jsonl"


def _tok_int(value) -> int:
    if isinstance(value, bool) or value is None:
        return 0
    try:
        v = int(value)
        return v if v > 0 else 0
    except (TypeError, ValueError):
        return 0


def _normalize_row(row) -> dict:
    """Ensure top-level token breakdown and model fields are always persisted."""
    out = dict(row) if isinstance(row, dict) else {}
    u = out.get("usage") if isinstance(out.get("usage"), dict) else {}
    if isinstance(out.get("usage"), dict):
        out["usage"] = dict(out["usage"])

    if out.get("input_tokens") is not None:
        inp = _tok_int(out.get("input_tokens")) or _tok_int(u.get("input_tokens"))
    else:
        inp = _tok_int(u.get("input_tokens"))

    if out.get("cache_read_input_tokens") is not None:
        cr = _tok_int(out.get("cache_read_input_tokens")) or _tok_int(
            u.get("cache_read_input_tokens"))
    elif u.get("cache_read_input_tokens") is not None:
        cr = _tok_int(u.get("cache_read_input_tokens"))
    elif out.get("cached_input_tokens") is not None:
        cr = _tok_int(out.get("cached_input_tokens"))
    elif u.get("cached_input_tokens") is not None:
        cr = _tok_int(u.get("cached_input_tokens"))
    else:
        cr = 0

    if out.get("cache_creation_input_tokens") is not None:
        cc = _tok_int(out.get("cache_creation_input_tokens")) or _tok_int(
            u.get("cache_creation_input_tokens"))
    else:
        cc = _tok_int(u.get("cache_creation_input_tokens"))

    if out.get("output_tokens") is not None:
        outp = _tok_int(out.get("output_tokens")) or _tok_int(u.get("output_tokens"))
    else:
        outp = _tok_int(u.get("output_tokens"))

    raw_model = out.get("model")
    if not (isinstance(raw_model, str) and raw_model.strip()):
        raw_model = u.get("model")
    mdl = raw_model.strip() if isinstance(raw_model, str) and raw_model.strip() else None

    out["input_tokens"] = inp
    out["cache_read_input_tokens"] = cr
    out["cache_creation_input_tokens"] = cc
    out["output_tokens"] = outp
    out["model"] = mdl
    return out


def _upgrades(existing, row) -> bool:
    """A later row replaces an earlier one when the earlier is an ``unknown`` /
    ``unmeasured`` placeholder and the later carries usage, when a sub-agent's
    cumulative total grew, or when a previously unsplit v1 row gains a non-zero
    token breakdown for the same key."""
    if existing.get("usage_state") in ("unknown", "unmeasured") and row.get(
            "usage_state") not in (None, "unknown", "unmeasured"):
        return True
    if existing.get("source") == "subagent" and row.get("source") == "subagent":
        try:
            return float(row.get("tokens") or 0) > float(existing.get("tokens") or 0)
        except (TypeError, ValueError):
            return False
    prev_bd = sum(_tok_int(existing.get(k)) for k in (
        "input_tokens", "cache_read_input_tokens",
        "cache_creation_input_tokens", "output_tokens"))
    new_bd = sum(_tok_int(row.get(k)) for k in (
        "input_tokens", "cache_read_input_tokens",
        "cache_creation_input_tokens", "output_tokens"))
    if prev_bd == 0 and new_bd > 0:
        try:
            return float(row.get("tokens") or 0) >= float(existing.get("tokens") or 0)
        except (TypeError, ValueError):
            return False
    return False


def _unreadable_error() -> IndexUnreadableError:
    return IndexUnreadableError("Spend unreadable (unknown) — inspect usage_index")


@contextmanager
def _acquire_index_lock(project_id, lock_timeout: float = DEFAULT_LOCK_TIMEOUT_S):
    """Serialize in-process and cross-process access to one project's index."""
    lp = lock_path(project_id)
    norm = os.path.normcase(os.path.abspath(str(lp)))
    held = getattr(_LOCK_TLS, "held", None)
    if held is None:
        held = {}
        _LOCK_TLS.held = held
    depth = held.get(norm, 0)
    if depth > 0:
        held[norm] = depth + 1
        try:
            yield
        finally:
            held[norm] = depth
        return

    try:
        index_dir().mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise _unreadable_error() from exc

    cp_timeout_cls = getattr(_paths, "CrossProcessLockTimeout", TimeoutError)
    with _paths.WRITE_LOCK:
        try:
            cm = _paths.cross_process_lock(lp, timeout_sec=lock_timeout)
            cm.__enter__()
        except (cp_timeout_cls, TimeoutError) as exc:
            raise LockBusyError("Usage index lock busy — retry") from exc
        except OSError as exc:
            raise _unreadable_error() from exc
        held[norm] = 1
        try:
            yield
        finally:
            held.pop(norm, None)
            try:
                cm.__exit__(None, None, None)
            except Exception:
                pass


def _read_meta(project_id, *, strict: bool) -> dict | None:
    mp = meta_path(project_id)
    if not mp.exists():
        return None
    if mp.is_dir():
        if strict:
            raise _unreadable_error()
        return None
    try:
        raw = mp.read_bytes()
    except OSError as exc:
        if strict:
            raise _unreadable_error() from exc
        return None
    if b"\x00" in raw:
        if strict:
            raise _unreadable_error()
        return None
    try:
        text = raw.decode("utf-8")
        obj = json.loads(text)
    except (UnicodeDecodeError, ValueError) as exc:
        if strict:
            raise _unreadable_error() from exc
        return None
    if not isinstance(obj, dict):
        if strict:
            raise _unreadable_error()
        return None
    return obj


def _quarantined_line_count(project_id) -> int:
    qp = quarantine_path(project_id)
    if not qp.exists() or qp.is_dir():
        return 0
    try:
        text = qp.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    return sum(1 for ln in text.splitlines() if ln.strip())


def _append_quarantine_lines(project_id, bad_lines: list[str]) -> int:
    if not bad_lines:
        return _quarantined_line_count(project_id)
    qp = quarantine_path(project_id)
    qp.parent.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    existing_lines = []
    if qp.exists() and not qp.is_dir():
        try:
            existing_lines = [
                ln for ln in qp.read_text(encoding="utf-8", errors="replace").splitlines()
                if ln.strip()
            ]
        except OSError:
            existing_lines = []
    lines = list(existing_lines) + [
        json.dumps({"raw": bad, "quarantined_at": stamp}, ensure_ascii=False)
        for bad in bad_lines
    ]
    _paths.atomic_write_text(qp, "\n".join(lines) + "\n")
    return len(lines)


def _scan_index_lines(project_id, *, strict: bool) -> tuple[dict, list[str]]:
    """Read and parse ``index_path(project_id)``.

    Returns ``(ordered_rows_by_key, corrupt_raw_lines)``. When ``strict=True``,
    raises :class:`IndexUnreadableError` if the index file is a directory, fails
    OS read, contains NUL bytes, or fails UTF-8 decoding.
    """
    p = index_path(project_id)
    out = {}
    bad = []
    if not p.exists():
        return out, bad
    if p.is_dir():
        if strict:
            raise _unreadable_error()
        return out, bad
    try:
        raw = p.read_bytes()
    except OSError as exc:
        if strict:
            raise _unreadable_error() from exc
        return out, bad
    if b"\x00" in raw:
        if strict:
            raise _unreadable_error()
        return out, bad
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        if strict:
            raise _unreadable_error() from exc
        return out, bad
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            bad.append(raw_line)
            continue
        if not isinstance(row, dict) or not row.get("key"):
            bad.append(raw_line)
            continue
        norm = _normalize_row(row)
        have = out.get(norm["key"])
        if have is None:
            out[norm["key"]] = norm
        elif _upgrades(have, norm):
            out[norm["key"]] = norm
    return out, bad


def _write_meta(project_id, quarantined_count: int) -> None:
    mp = meta_path(project_id)
    mp.parent.mkdir(parents=True, exist_ok=True)
    _paths.atomic_write_json(mp, {
        "schema_version": INDEX_SCHEMA_VERSION,
        "quarantined_count": _tok_int(quarantined_count),
    })


def _rows(project_id) -> dict:
    """``{key: row}`` in first-write order; malformed lines are skipped; never raises."""
    try:
        rows_map, _ = _scan_index_lines(project_id, strict=False)
        return rows_map
    except Exception:
        return {}


def rebuild_index(project_id, rows=None, *,
                  lock_timeout: float = DEFAULT_LOCK_TIMEOUT_S) -> dict:
    """Atomically rebuild a project's schema-v2 index and meta under cross-process lock."""
    if not project_id:
        return {
            "ok": False,
            "schema_version": INDEX_SCHEMA_VERSION,
            "row_count": 0,
            "quarantined_count": 0,
        }
    with _acquire_index_lock(project_id, lock_timeout=lock_timeout), _journal.pairing():
        mp = meta_path(project_id)
        if mp.exists() and mp.is_dir():
            raise _unreadable_error()
        prior_meta = _read_meta(project_id, strict=False) or {}
        bad_lines = []
        if rows is None:
            have, bad_lines = _scan_index_lines(project_id, strict=True)
        else:
            have = {}
            for item in (rows or []):
                if not isinstance(item, dict) or not item.get("key"):
                    bad_lines.append(json.dumps(item, default=str))
                    continue
                norm = _normalize_row(item)
                prev = have.get(norm["key"])
                if prev is None or _upgrades(prev, norm):
                    have[norm["key"]] = norm

        q_count = _append_quarantine_lines(project_id, bad_lines)
        q_count = max(q_count, _tok_int(prior_meta.get("quarantined_count")))
        deduped = list(have.values())
        ip = index_path(project_id)
        ip.parent.mkdir(parents=True, exist_ok=True)
        _paths.atomic_write_text(
            ip, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in deduped)
        )
        _write_meta(project_id, q_count)
        return {
            "ok": True,
            "schema_version": INDEX_SCHEMA_VERSION,
            "row_count": len(deduped),
            "quarantined_count": q_count,
        }


def append_rows(project_id, rows, *,
                lock_timeout: float = DEFAULT_LOCK_TIMEOUT_S) -> int:
    """Idempotently append normalized schema-v2 rows for a project under lock.

    Performs an in-lock schema-v2 upgrade/compaction (and corrupt-line quarantine)
    if ``meta_path(project_id)`` is missing or older than ``INDEX_SCHEMA_VERSION``.
    """
    incoming = [_normalize_row(r) for r in (rows or [])
                if isinstance(r, dict) and r.get("key")]
    if not project_id or not incoming:
        return 0
    with _acquire_index_lock(project_id, lock_timeout=lock_timeout), _journal.pairing():
        ip = index_path(project_id)
        mp = meta_path(project_id)
        existed = ip.exists()
        meta = _read_meta(project_id, strict=False)
        schema_ver = _tok_int((meta or {}).get("schema_version"))
        needs_upgrade = existed and (meta is None or schema_ver < INDEX_SCHEMA_VERSION)

        have, bad_lines = _scan_index_lines(project_id, strict=True)
        fresh = []
        seen_keys = set()
        for row in incoming:
            k = row["key"]
            if k in seen_keys:
                continue
            seen_keys.add(k)
            present = have.get(k)
            if present is not None and not _upgrades(present, row):
                continue
            have[k] = row
            fresh.append(row)

        if fresh or needs_upgrade or bad_lines or (existed and meta is None):
            q_count = _append_quarantine_lines(project_id, bad_lines)
            q_count = max(q_count, _tok_int((meta or {}).get("quarantined_count")))
            ip.parent.mkdir(parents=True, exist_ok=True)
            _paths.atomic_write_text(
                ip, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in have.values())
            )
            _write_meta(project_id, q_count)
        return len(fresh)


def inspect_project_index(project_id, *,
                          lock_timeout: float = DEFAULT_LOCK_TIMEOUT_S) -> dict:
    """Inspect a project's usage index under cross-process lock.

    Raises :class:`LockBusyError` on lock contention timeout and
    :class:`IndexUnreadableError` when ``index_path`` or ``meta_path`` is
    unreadable/binary-corrupted. Quarantines malformed JSONL lines into
    ``quarantine_path(project_id)`` and returns valid rows plus quarantine count.
    """
    if not project_id:
        return {
            "ok": True,
            "rows": [],
            "quarantined_count": 0,
            "schema_version": INDEX_SCHEMA_VERSION,
        }
    with _acquire_index_lock(project_id, lock_timeout=lock_timeout), _journal.pairing():
        meta = _read_meta(project_id, strict=True)
        ip = index_path(project_id)
        have, bad_lines = _scan_index_lines(project_id, strict=True)
        valid_rows = list(have.values())

        file_q_before = _quarantined_line_count(project_id)
        prior_q = max(file_q_before, _tok_int((meta or {}).get("quarantined_count")))
        if bad_lines:
            appended_total = _append_quarantine_lines(project_id, bad_lines)
            q_count = max(appended_total,
                          prior_q + len(bad_lines) if prior_q > file_q_before else appended_total)
            ip.parent.mkdir(parents=True, exist_ok=True)
            _paths.atomic_write_text(
                ip, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in valid_rows)
            )
            _write_meta(project_id, q_count)
            schema_ver = INDEX_SCHEMA_VERSION
        else:
            q_count = prior_q
            if meta is not None:
                schema_ver = _tok_int(meta.get("schema_version")) or 1
            elif ip.exists():
                schema_ver = 1
            else:
                schema_ver = INDEX_SCHEMA_VERSION

        return {
            "ok": True,
            "rows": valid_rows,
            "quarantined_count": q_count,
            "schema_version": schema_ver,
        }


def load_rows(project_id) -> list:
    """The project's rows in first-write order. Never raises."""
    if not project_id:
        return []
    return list(_rows(project_id).values())
