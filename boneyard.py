#!/usr/bin/env python3
"""Anchor Boneyard — a per-project, searchable index over DISCARDED material.

v10 "Live Handoff & Boneyard", Pillar 3 (frozen design in
``planning/rnd-v10/MASTER-PLAN.md``). The Boneyard is a per-project (D4),
searchable store of the work a user threw away, fed by THREE locked sources (D3):

  1. ``killed``       — a hard-KILLED session that had produced material (a kill is
                        the deliberate "I'm done / discarding" action since v5;
                        the session's normal finished tile is UNAFFECTED — the
                        Boneyard record is purely additive);
  2. ``deleted``      — a v9-DELETED session (whose registry record + effort
                        pointer-records are dropped) — the Boneyard is its ONLY
                        remaining home;
  3. ``grass-deleted``— a DELETED grass idea (its pointer + index + refinements
                        are purged) — the Boneyard preserves the idea text.

The Boneyard is an **INDEX over the already-persisted docs (D9), NOT a second
copy**: the v8 keystone (``effort_history.persist_session_docs``) already copies +
commits a session's produced docs into the main project; a Boneyard entry merely
REFERENCES those main-folder-relative ``doc_rels``. Nothing is copied here.

Store (per project, mirroring the effort/summary store idioms):

    <folder>/.anchor/projects/<id>/boneyard/
        index.json            ordered list of entry ids, NEWEST-FIRST
        entries/<entry_id>.json

``entry_id`` is **content-addressed** (a stable hash over
``source + session_id/idea_id + sorted(doc_rels)``) so re-recording the SAME
discard is an idempotent UPSERT — never a duplicate. Every write runs under
``paths.WRITE_LOCK`` and is atomic (tmp + ``os.replace``). All capture wiring is
**BEST-EFFORT** — a Boneyard failure must NEVER break the kill / delete /
grass-delete path it hangs off.

Stdlib only (``hashlib`` / ``json`` / ``os`` / ``time`` / ``pathlib``). No
third-party, no native deps. The read seams (``list_entries`` / ``search`` /
``get_entry``) return SAFE projections — no absolute paths / worktree / branch.
"""

import hashlib
import json
import os
import time
from pathlib import Path

import paths as _paths
import rnd_registry as _rnd
import journal as _journal

#: The three locked Boneyard sources (D3).
SOURCE_KILLED = "killed"
SOURCE_DELETED = "deleted"
SOURCE_GRASS_DELETED = "grass-deleted"
SOURCES = (SOURCE_KILLED, SOURCE_DELETED, SOURCE_GRASS_DELETED)

#: How much of a summary blurb we keep on an entry (the search/display excerpt).
_EXCERPT_MAX = 400

#: The SAFE keys exposed by ``list_entries`` / ``get_entry`` projections — never
#: an absolute path / worktree / branch / engine internal.
_SAFE_KEYS = (
    "entry_id", "source", "session_id", "lane", "title",
    "summary_excerpt", "doc_rels", "idea_text", "when",
    # Honest Telemetry W5: a discarded session carries its FINALIZED cost block
    # (tokens/time/$ + usage_state/usage_reason) so the Boneyard tells the honest
    # cost of what was thrown away. The cost block holds only measured facts — no
    # absolute path / worktree / branch — so it is SAFE to project.
    "cost", "usage_state", "usage_reason",
)


# ── Store paths ──────────────────────────────────────────────────────────────

def boneyard_dir(folder_path, project_id: str) -> Path:
    """``<folder>/.anchor/projects/<id>/boneyard/`` (not created)."""
    return _rnd.project_store_dir(folder_path, project_id) / "boneyard"


def _entries_dir(folder_path, project_id: str) -> Path:
    return boneyard_dir(folder_path, project_id) / "entries"


def _index_path(folder_path, project_id: str) -> Path:
    return boneyard_dir(folder_path, project_id) / "index.json"


def _entry_path(folder_path, project_id: str, entry_id: str) -> Path:
    return _entries_dir(folder_path, project_id) / f"{entry_id}.json"


# ── Atomic write helpers (tmp + os.replace, mirroring the effort/summary store) ─

def _atomic_write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(str(tmp), str(path))


def _load_index(folder_path, project_id: str) -> list:
    """The ordered list of entry ids, as stored (NEWEST-FIRST). ``[]`` on miss."""
    p = _index_path(folder_path, project_id)
    if not p.exists():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return [str(x) for x in raw] if isinstance(raw, list) else []


def _save_index(folder_path, project_id: str, order: list) -> None:
    _atomic_write_json(_index_path(folder_path, project_id), list(order))


# ── Entry id (content-addressed → idempotent upsert) ─────────────────────────

def _norm_doc_rels(doc_rels) -> list:
    """Normalize ``doc_rels`` to a clean, de-duped, POSIX-relative string list."""
    out = []
    seen = set()
    for r in (doc_rels or []):
        s = str(r or "").strip().replace("\\", "/")
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def compute_entry_id(source: str, key: str, doc_rels, lane: str = "") -> str:
    """Content-addressed entry id: stable over ``source + key + lane + sorted(doc_rels)``.

    ``key`` is the session_id (killed/deleted) or the idea_id (grass-deleted).
    ``lane`` is folded into the basis so two same-source/same-key/same-docs
    discards on DIFFERENT lanes cannot collide (it matches the lane-bearing
    ``_SAFE_KEYS``). Re-recording the SAME discard yields the SAME id → an
    idempotent upsert (recomputing the same entry is stable).
    """
    rels = sorted(_norm_doc_rels(doc_rels))
    basis = " ".join([str(source or ""), str(key or ""), str(lane or ""), *rels])
    h = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]
    return f"bone-{h}"


def _safe_view(entry: dict) -> dict:
    """A SAFE projection of an entry — only the public keys, never internals."""
    e = entry or {}
    return {
        "entry_id": e.get("entry_id", ""),
        "source": e.get("source", ""),
        "session_id": e.get("session_id", ""),
        "lane": e.get("lane", ""),
        "title": e.get("title", ""),
        "summary_excerpt": e.get("summary_excerpt", ""),
        "doc_rels": list(e.get("doc_rels", []) or []),
        "idea_text": e.get("idea_text", ""),
        "when": e.get("when", 0),
        # Honest Telemetry W5: the finalized cost block + usage verdict (SAFE —
        # measured facts only). ``cost`` is None for a capture-failed/unmeasured
        # discard (never a fabricated $0).
        "cost": e.get("cost", None),
        "usage_state": e.get("usage_state", ""),
        "usage_reason": e.get("usage_reason", ""),
    }


# ── Record (idempotent upsert) ───────────────────────────────────────────────

def record_entry(folder_path, project_id: str, entry: dict) -> dict:
    """Upsert a Boneyard entry. Idempotent, atomic, best-effort (never raises).

    ``entry`` shape (caller-supplied; missing fields default):
        ``{source, session_id|idea_id, lane, title, summary_excerpt,
           doc_rels:[rel...], idea_text, when}``

    The stored entry carries a content-addressed ``entry_id`` (see
    :func:`compute_entry_id`) so re-recording the same discard is a true no-op
    upsert (no duplicate index entry, ``created_at`` preserved). The entry is
    NEWEST-FIRST in the index (most-recent at position 0). doc_rels REFERENCE the
    already-persisted main-folder-relative paths — nothing is copied here.

    W7 ROUTING NOTE (entry shape): a ``deleted`` entry's session had its effort
    pointer-records DROPPED by the v9 delete, so its ``doc_rels`` links must be
    resolved via ``/artifact?path=<rel>`` (the file survives on disk, Option A) —
    NOT ``/report/<pid>/<lane>/<job_id>`` (which 404s with no pointer-record). The
    same holds for ``grass-deleted`` (the idea's pointer/index/refinements are
    purged). A ``killed`` entry KEEPS its pointer-records, so its docs route via
    ``/report``. The carried ``doc_rels`` are sufficient for W7 to route
    accordingly.

    Returns the stored entry dict (or a ``{"ok": False, ...}`` stub on a resolved
    failure). Never raises into the caller's kill/delete path.
    """
    try:
        src = str((entry or {}).get("source", "") or "").strip()
        if src not in SOURCES:
            return {"ok": False, "reason": "bad-source", "entry_id": ""}

        session_id = str((entry or {}).get("session_id", "") or "").strip()
        idea_id = str((entry or {}).get("idea_id", "") or "").strip()
        key = session_id or idea_id
        doc_rels = _norm_doc_rels((entry or {}).get("doc_rels"))
        title = str((entry or {}).get("title", "") or "").strip()
        idea_text = str((entry or {}).get("idea_text", "") or "").strip()
        lane = str((entry or {}).get("lane", "") or "").strip()
        summary_excerpt = str((entry or {}).get("summary_excerpt", "") or "")
        if len(summary_excerpt) > _EXCERPT_MAX:
            summary_excerpt = summary_excerpt[:_EXCERPT_MAX].rstrip() + "…"
        when = (entry or {}).get("when")
        try:
            when = float(when) if when else time.time()
        except (TypeError, ValueError):
            when = time.time()

        # Honest Telemetry W5: carry the finalized cost block + usage verdict
        # verbatim when the caller supplied them (a discarded RUN session). ``cost``
        # is kept as-is (a dict or None — never fabricated); the states default to
        # empty for a non-session (grass) discard.
        cost = (entry or {}).get("cost", None)
        usage_state = str((entry or {}).get("usage_state", "") or "")
        usage_reason = str((entry or {}).get("usage_reason", "") or "")

        eid = compute_entry_id(src, key, doc_rels, lane)
        record = {
            "entry_id": eid,
            "source": src,
            "session_id": session_id,
            "lane": lane,
            "title": title,
            "summary_excerpt": summary_excerpt,
            "doc_rels": doc_rels,
            "idea_text": idea_text,
            "when": when,
            "cost": cost,
            "usage_state": usage_state,
            "usage_reason": usage_reason,
        }

        with _paths.WRITE_LOCK, _journal.journaled(project_id, _journal.EV_BONEYARD_CAPTURED, correlation_id=(key or project_id), folder_path=folder_path, payload={"source": src, "entry_id": eid}):
            epath = _entry_path(folder_path, project_id, eid)
            # Preserve the first-write timestamp on a re-record (true upsert).
            if epath.exists():
                try:
                    prior = json.loads(epath.read_text(encoding="utf-8"))
                    if isinstance(prior, dict) and prior.get("when"):
                        record["when"] = prior["when"]
                except (json.JSONDecodeError, OSError):
                    pass
            _atomic_write_json(epath, record)
            order = _load_index(folder_path, project_id)
            if eid in order:
                order.remove(eid)
            order.insert(0, eid)  # NEWEST-FIRST
            _save_index(folder_path, project_id, order)
        return record
    except Exception:
        return {"ok": False, "reason": "error", "entry_id": ""}


# ── Read seams (SAFE projections; newest-first; stdlib search) ───────────────

def get_entry(folder_path, project_id: str, entry_id: str):
    """Return ONE Boneyard entry (SAFE projection), or ``None``. Never raises."""
    eid = str(entry_id or "").strip()
    if not eid:
        return None
    p = _entry_path(folder_path, project_id, eid)
    if not p.exists():
        return None
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return _safe_view(rec) if isinstance(rec, dict) else None


def list_entries(folder_path, project_id: str) -> list:
    """All Boneyard entries, NEWEST-FIRST, as SAFE projections. ``[]`` on miss.

    Never leaks absolute paths / worktree / branch (only the ``_SAFE_KEYS``).
    Best-effort: a missing/corrupt entry file is skipped. Never raises.
    """
    out = []
    try:
        for eid in _load_index(folder_path, project_id):
            view = get_entry(folder_path, project_id, eid)
            if view is not None:
                out.append(view)
    except Exception:
        return out
    return out


def _tokenize(text: str) -> list:
    """Lowercase alnum-ish tokens for the stdlib token match (paths split too)."""
    text = (text or "").lower()
    tok = []
    cur = []
    for ch in text:
        if ch.isalnum():
            cur.append(ch)
        else:
            if cur:
                tok.append("".join(cur))
                cur = []
    if cur:
        tok.append("".join(cur))
    return tok


def _entry_haystack(entry: dict) -> str:
    """The searchable text of an entry: title + summary + idea + doc paths/names."""
    parts = [
        entry.get("title", ""),
        entry.get("summary_excerpt", ""),
        entry.get("idea_text", ""),
        entry.get("lane", ""),
    ]
    for rel in (entry.get("doc_rels", []) or []):
        rel = str(rel or "")
        parts.append(rel)
        parts.append(rel.replace("\\", "/").rsplit("/", 1)[-1])  # filename
    return "\n".join(p for p in parts if p)


def search(folder_path, project_id: str, query: str) -> list:
    """Stdlib token/substring search over the project's Boneyard, NEWEST-FIRST.

    Case-insensitive. An entry MATCHES when EVERY query token appears (as a
    substring) somewhere in its title + summary excerpt + idea text + doc paths
    (full rel path AND bare filename). An empty query returns ALL entries (same
    as :func:`list_entries`). Non-destructive — a pure read. Never raises.
    """
    q = (query or "").strip()
    entries = list_entries(folder_path, project_id)
    if not q:
        return entries
    tokens = _tokenize(q) or [q.lower()]
    out = []
    for e in entries:
        hay = _entry_haystack(e).lower()
        if all(t in hay for t in tokens):
            out.append(e)
    return out


# ── Capture helpers (build an entry from a session / a grass idea) ────────────

def _summary_excerpt_for_session(folder_path, project_id, lane, session_id) -> str:
    """A short summary blurb for the entry — best-effort from the cached summary.

    Prefers the cached session summary's text/first-claim, then the blurb. Returns
    ``""`` (honest empty) when nothing is cached. Never raises / never runs the
    model (cache-only). Lazy import keeps ``boneyard`` free of a hard summarizer
    dependency in environments where it is absent.
    """
    try:
        import summarizer as _summ
    except Exception:
        return ""
    try:
        cached = _summ.load_cached(folder_path, project_id, lane, session_id)
    except Exception:
        cached = None
    if isinstance(cached, dict):
        for key in ("summary_text", "title", "what_was_asked"):
            v = (cached.get(key) or "").strip()
            if v:
                return v
        claims = cached.get("claims") or []
        for c in claims:
            if c and str(c).strip():
                return str(c).strip()
    # Fall back to the short blurb seam (still cache-only).
    try:
        return _summ.session_blurb(folder_path, project_id, lane, session_id,
                                   max_chars=_EXCERPT_MAX) or ""
    except Exception:
        return ""


def build_session_entry(folder_path, project_id: str, lane: str,
                        session_id: str, source: str,
                        record: dict = None, doc_rels=None) -> dict:
    """Build a Boneyard entry dict from a session. Best-effort; never raises.

    Resolves ``doc_rels`` from the v8 join (``efforts_for_session_id``) when not
    supplied (so a v9-delete caller can pass the docs it captured BEFORE the
    pointer-records are dropped — D10). Resolves a title from the registry record
    label / lane, and a summary excerpt from the cached summary. Returns the entry
    dict ready for :func:`record_entry` (it may have empty ``doc_rels``; the
    caller decides whether to skip a no-material kill).
    """
    lane = str(lane or "")
    sid = str(session_id or "")
    rec = record or {}

    if doc_rels is None:
        try:
            import effort_history as _eh
            efforts = _eh.efforts_for_session_id(folder_path, project_id, lane, sid)
            doc_rels = [e.get("artifact_path", "") for e in efforts
                        if e.get("artifact_path")]
        except Exception:
            doc_rels = []

    title = (rec.get("label") or "").strip()
    if not title:
        title = (f"{lane} session" if lane else "session").strip()

    excerpt = _summary_excerpt_for_session(folder_path, project_id, lane, sid)

    # Honest Telemetry W5: attach the session's FINALIZED cost block so the
    # Boneyard tells the honest cost of the discarded work. The eager finalize
    # (usage_capture) wrote a ``run-cost`` effort record tagged with this
    # session_id carrying ``cost`` (dict for measured; None for capture-failed/
    # unmeasured) + ``usage_state``/``usage_reason`` — never a fabricated $0.
    cost, usage_state, usage_reason = _resolve_finalized_cost(
        folder_path, project_id, lane, sid, rec)

    return {
        "source": source,
        "session_id": sid,
        "lane": lane,
        "title": title,
        "summary_excerpt": excerpt,
        "doc_rels": _norm_doc_rels(doc_rels),
        "idea_text": "",
        "when": time.time(),
        "cost": cost,
        "usage_state": usage_state,
        "usage_reason": usage_reason,
    }


def _resolve_finalized_cost(folder_path, project_id, lane, session_id, record):
    """Resolve a session's finalized (``run-cost``) cost block + usage verdict.

    Prefers the ``run-cost`` effort record (``kind == 'run-cost'``) tagged with
    this ``session_id``; falls back to the registry record's ``usage_state`` /
    ``usage_reason`` stamp (an unmeasured session writes NO cost effort record).
    Returns ``(cost|None, usage_state, usage_reason)``. Best-effort; never raises.
    """
    cost = None
    usage_state = str((record or {}).get("usage_state", "") or "")
    usage_reason = str((record or {}).get("usage_reason", "") or "")
    try:
        import effort_history as _eh
        for e in _eh.efforts_for_session_id(folder_path, project_id, lane,
                                            session_id):
            if e.get("kind") == "run-cost":
                cost = e.get("cost", None)
                if e.get("usage_state"):
                    usage_state = str(e.get("usage_state") or "")
                if e.get("usage_reason"):
                    usage_reason = str(e.get("usage_reason") or "")
                break
    except Exception:
        pass
    return cost, usage_state, usage_reason


def build_grass_entry(folder_path, project_id: str, idea: dict,
                      doc_rels=None) -> dict:
    """Build a ``grass-deleted`` Boneyard entry from a grass idea record.

    Captures the idea TEXT (title/notes) + the union of its doc references:
    BOTH the dev/refinement artifacts (``list_grass_refinements``) AND the W4
    archive bundles' persisted docs (``list_grass_archives(...)[*]["docs"]``,
    written by ``effort_history.archive_grass_session``). An idea that was
    ARCHIVED then deleted must still surface its archived docs from the Boneyard
    (the files survive on disk, Option A). Deduped. Best-effort; never raises.
    The caller invokes this BEFORE purging the idea so the text + doc references
    survive the delete.
    """
    idea = idea or {}
    jid = (idea.get("job_id") or "").strip()
    idea_text = (idea.get("title") or "").strip()
    notes = (idea.get("notes") or "").strip()
    if notes and notes not in idea_text:
        idea_text = (idea_text + "\n" + notes).strip() if idea_text else notes

    rels = list(doc_rels or [])
    if doc_rels is None:
        rels = []
        try:
            import effort_history as _eh
            # Refinement artifacts (the dev-N versions).
            for ref in _eh.list_grass_refinements(folder_path, project_id, jid):
                for a in (ref.get("artifacts") or []):
                    if a:
                        rels.append(str(a))
            # W4 archive bundles' persisted docs — an archived-then-deleted idea
            # would otherwise lose these from the Boneyard.
            for bundle in _eh.list_grass_archives(folder_path, project_id, jid):
                for d in (bundle.get("docs") or []):
                    if d:
                        rels.append(str(d))
        except Exception:
            pass

    return {
        "source": SOURCE_GRASS_DELETED,
        "session_id": "",
        "idea_id": jid,
        "lane": "grass",
        "title": (idea_text[:80] if idea_text else "grass idea"),
        "summary_excerpt": "",
        "doc_rels": _norm_doc_rels(rels),
        "idea_text": idea_text,
        "when": time.time(),
    }
