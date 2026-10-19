#!/usr/bin/env python3
"""Anchor usage ledger — durable, atomic, idempotent per-engine-session store.

Honest-Telemetry durability substrate (W2). The append-only ledger the W4
usage-capture pipeline writes each engine session's per-message usage entries
into, keyed by ``(engine_session_uuid, entry_key)`` so a re-ingestion of the
SAME sidecar line is a no-op. That idempotency is what makes the W4 switch-engine
invariant hold — a resumed / engine-switched session's parts A and B are counted
EXACTLY once, and re-parsing a file never double-counts.

W2 ships the STORAGE SUBSTRATE ONLY — the crash-safe atomic tmp→rename write plus
the idempotent-by-key append — BEFORE any sidecar parser / finalize code exists
(that is W4). This module deliberately does NO sidecar parsing and computes no
totals beyond what its entries already carry; it is the durable sink the parser
writes into.

Storage layout: one JSON doc per engine session under
``<data-dir>/.anchor/usage_ledger/<engine-session-uuid>.json`` of the shape
``{"engine_session_uuid": <str>, "entries": {<entry-key>: <entry-dict>}}``. Every
write goes through :func:`paths.atomic_write_text` under ``paths.WRITE_LOCK`` and
a ``journal.pairing()`` scope, so it is crash-safe AND clean under the permanent
write-completeness enforce gate (a ``.anchor/`` mutation must be journal-paired) —
exactly the discipline ``effort_history.record_effort`` already uses.

Stdlib only. No third-party imports.
"""

import hashlib
import json
import re
from pathlib import Path

import paths as _paths
import journal as _journal

#: Subdir under ``.anchor/`` holding one usage-ledger doc per engine session.
LEDGER_DIRNAME = "usage_ledger"
ANCHOR_DIRNAME = ".anchor"

#: Filesystem-safe name sanitizer (a session UUID is hex+dashes, but a legacy /
#: engine-switch fallback id could carry other chars; never let it escape the dir).
_UNSAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def ledger_dir() -> Path:
    """Absolute path to the ledger dir (``.anchor/usage_ledger/``). Not created."""
    return _paths.data_dir() / ANCHOR_DIRNAME / LEDGER_DIRNAME


def _safe_uuid(engine_session_uuid: str) -> str:
    """Sanitize an engine-session id to a single filesystem-safe path component."""
    s = _UNSAFE_NAME_RE.sub("_", str(engine_session_uuid or "").strip())
    return s or "unknown"


def ledger_path(engine_session_uuid: str) -> Path:
    """Absolute path to one engine session's ledger doc. Not created."""
    return ledger_dir() / f"{_safe_uuid(engine_session_uuid)}.json"


def entry_key(engine_session_uuid, message_uuid=None, line=None) -> str:
    """The stable dedup key for one ledger entry.

    Per the pinned W1 sidecar shape, a single assistant turn can span multiple
    JSONL lines that SHARE a ``message.id`` and repeat the identical usage block;
    the ledger key is therefore ``message.id`` when present (so those duplicate
    lines collapse to one entry), else a hash of the raw line scoped by the engine
    session uuid — the ``(engine_session_uuid, message_uuid/line-hash)`` key the
    North Star pins. Pure / deterministic.
    """
    if message_uuid:
        return f"msg:{message_uuid}"
    h = hashlib.sha1(
        (str(engine_session_uuid or "") + "\x00" + str(line or "")).encode("utf-8")
    ).hexdigest()
    return f"line:{h}"


def load_ledger(engine_session_uuid) -> dict:
    """Load one engine session's ledger doc (best-effort).

    Returns ``{"engine_session_uuid": <str>, "entries": {key: entry}}``. A
    missing / unreadable / corrupt doc yields an empty ledger (never raises) —
    atomic writes never leave a torn file, so a decode error is a genuine fault
    and the honest fallback is an empty entries map.
    """
    p = ledger_path(engine_session_uuid)
    empty = {"engine_session_uuid": str(engine_session_uuid or ""), "entries": {}}
    if not p.exists():
        return empty
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError):
        return empty
    if not isinstance(raw, dict):
        return empty
    entries = raw.get("entries")
    if not isinstance(entries, dict):
        entries = {}
    return {
        "engine_session_uuid": raw.get("engine_session_uuid")
        or str(engine_session_uuid or ""),
        "entries": entries,
    }


def append_entries(engine_session_uuid, entries) -> int:
    """Idempotently append usage entries for an engine session. Returns the count
    of NEW entries actually added.

    ``entries`` is an iterable of dicts; each MUST carry a ``"key"`` (compute it
    with :func:`entry_key`). An entry whose key already exists is a NO-OP
    (first-write-wins) — re-ingesting the same sidecar line, or the same file
    twice, never double-counts. Entries with no ``"key"`` are skipped.

    Atomic + crash-safe: the whole read-merge-write runs under
    ``paths.WRITE_LOCK`` and a ``journal.pairing()`` scope, and the doc is written
    via :func:`paths.atomic_write_text` (tmp→fsync→rename). When nothing new is
    added the file is left untouched (a pure no-op).
    """
    entries = list(entries or [])
    if not engine_session_uuid:
        return 0
    with _paths.WRITE_LOCK, _journal.pairing():
        doc = load_ledger(engine_session_uuid)
        store = doc["entries"]
        added = 0
        for ent in entries:
            if not isinstance(ent, dict):
                continue
            k = ent.get("key")
            if not k:
                continue
            if k in store:
                continue  # idempotent: this sidecar line is already ledgered
            store[k] = ent
            added += 1
        if added:
            doc["engine_session_uuid"] = str(engine_session_uuid)
            ledger_dir().mkdir(parents=True, exist_ok=True)
            _paths.atomic_write_text(
                ledger_path(engine_session_uuid),
                json.dumps(doc, indent=2, ensure_ascii=False),
            )
        return added


def ledger_entries(engine_session_uuid) -> list:
    """Return the deduped ledger entries for an engine session (a list of dicts).

    Read-only. Order is the stable dict-insertion order of first ingestion.
    """
    return list(load_ledger(engine_session_uuid)["entries"].values())
