"""Anchor friction journaling — user-initiated, sleep-cycle-ready (2026-07-26).

THE GAP THIS CLOSES. Anchor journals SKILL runs (``foundry_journal``) and can
export SKILL friction upstream (``share_feedback``), but it had **no way for the
user to tell Anchor that Anchor itself hurt**. The best evidence in the
2026-07-26 hardening review — the files that correctly diagnosed the iPad
dictation blow-up before any agent did — were hand-written markdown under
``docs/friction/``. This module replaces that manual labor.

THE LOOP:
    user hits friction  →  one call captures it WITH context
                        →  records accumulate in .anchor/friction/
                        →  ``friction_report()`` renders ONE intake brief
                        →  a sleep cycle (Fable et al.) fixes things
                        →  ``resolve()`` closes records with the fixing commit
                        →  the next cycle sees only what is still open

HONESTY RULES (locked — mirroring the skills-hardening doctrine):
  * The user's words are stored VERBATIM. Anchor never rewrites them.
  * Auto-context is FACTS ONLY (ids, route, version, recent error lines).
    No model interpretation at capture time.
  * **ZERO model calls on the capture path.** The moment of friction is exactly
    when engines are down, wedged, or burning money — capture must still work.
  * A record is never auto-resolved. Only an explicit action closes it.
  * Append-only. Nothing here deletes or rewrites a prior record.

Stdlib only.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import paths as _paths

#: Record schema version (bump when the shape changes).
SCHEMA_VERSION = 1

#: Store dirname under the Anchor data dir.
FRICTION_DIRNAME = "friction"
INDEX_NAME = "index.json"

#: How the user classifies what happened. Ordered by escalation.
SEVERITIES = ("concern", "friction", "problem")
DEFAULT_SEVERITY = "friction"

#: Lifecycle. A record only leaves ``open`` by an explicit action.
STATUSES = ("open", "triaged", "resolved")

#: How many recent error-log lines ride along as context.
RECENT_ERROR_LINES = 8
#: Hard caps so one runaway capture can never bloat the store.
MAX_TITLE_CHARS = 200
MAX_BODY_CHARS = 20000


class FrictionJournalError(RuntimeError):
    """A friction-journal operation failed for a clear, reportable reason."""


# ── store ─────────────────────────────────────────────────────────────────────

def friction_dir() -> Path:
    """``<data dir>/friction/`` — created on demand."""
    # data_dir() is resolved at CALL time (ANCHOR_DATA_DIR), so tests can
    # redirect the store without reimporting this module.
    d = Path(_paths.data_dir()) / FRICTION_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _index_path() -> Path:
    return friction_dir() / INDEX_NAME


def _slug(text: str, limit: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return (s[:limit].rstrip("-")) or "note"


def _load_index() -> list:
    p = _index_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []  # a torn index never blocks capture


def _save_index(ids: list) -> None:
    tmp = _index_path().with_suffix(".json.tmp")
    tmp.write_text(json.dumps(ids, indent=1), encoding="utf-8")
    os.replace(tmp, _index_path())


def _record_path(rec_id: str) -> Path:
    return friction_dir() / f"{rec_id}.json"


# ── auto-context (FACTS ONLY — never a model call) ───────────────────────────

def _recent_errors(limit: int = RECENT_ERROR_LINES) -> list:
    """The last few error-log lines, best-effort. Never raises."""
    try:
        log = Path(__file__).resolve().parent / "logs" / "errors.log"
        if not log.exists():
            return []
        # errors.log has mixed encodings (cp1252 separators) — read forgivingly.
        text = log.read_text(encoding="utf-8", errors="replace")
        # errors.log is cp1252/utf-8 MIXED, so a forgiving read yields U+FFFD
        # replacement chars. Strip them: a friction brief must render on a
        # cp1252 console (and in any collaborator's terminal) without blowing up.
        lines = [ln.replace("�", "").strip()
                 for ln in text.splitlines() if ln.strip()]
        return [ln for ln in lines if ln][-limit:]
    except Exception:
        return []


def _anchor_version() -> str:
    try:
        v = (Path(__file__).resolve().parent / "VERSION").read_text(
            encoding="utf-8")
        return v.strip()
    except Exception:
        return "unknown"


def build_context(project_id=None, session_id=None, lane=None, route=None,
                  engine=None, extra=None) -> dict:
    """Assemble the auto-context. FACTS ONLY; never raises."""
    ctx = {
        "anchor_version": _anchor_version(),
        "recent_errors": _recent_errors(),
    }
    for key, val in (("project_id", project_id), ("session_id", session_id),
                     ("lane", lane), ("route", route), ("engine", engine)):
        if val:
            ctx[key] = str(val)
    if isinstance(extra, dict):
        for k, v in extra.items():
            if k not in ctx and isinstance(k, str):
                try:
                    json.dumps(v)  # only carry JSON-able facts
                    ctx[k] = v
                except Exception:
                    continue
    return ctx


# ── capture ───────────────────────────────────────────────────────────────────

def capture(title: str, body: str = "", severity: str = DEFAULT_SEVERITY,
            source: str = "user", project_id=None, session_id=None, lane=None,
            route=None, engine=None, extra_context=None) -> dict:
    """Record ONE friction/problem/concern. The capture path never calls a model.

    Returns the written record. Raises :class:`FrictionJournalError` only on an
    empty title (the one thing that makes a record useless).
    """
    t = str(title or "").strip()
    if not t:
        raise FrictionJournalError(
            "a friction record needs a title (one line: what hurt?)")
    sev = str(severity or DEFAULT_SEVERITY).strip().lower()
    if sev not in SEVERITIES:
        sev = DEFAULT_SEVERITY
    ts = time.time()
    stamp = time.strftime("%Y-%m-%d", time.localtime(ts))
    existing = _load_index()
    seq = sum(1 for rid in existing if str(rid).startswith(stamp)) + 1
    rec_id = f"{stamp}-{seq:02d}-{_slug(t)}"
    rec = {
        "schema_version": SCHEMA_VERSION,
        "id": rec_id,
        "ts": ts,
        "iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts)),
        "source": "auto" if str(source).lower() == "auto" else "user",
        "severity": sev,
        # VERBATIM — Anchor never rewrites what the user said.
        "title": t[:MAX_TITLE_CHARS],
        "body": str(body or "")[:MAX_BODY_CHARS],
        "context": build_context(project_id, session_id, lane, route, engine,
                                 extra_context),
        "status": "open",
    }
    path = _record_path(rec_id)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rec, indent=1), encoding="utf-8")
    os.replace(tmp, path)
    existing.append(rec_id)
    try:
        _save_index(existing)
    except Exception:
        pass  # the record file is the truth; the index is an ordering aid
    return rec


# ── read ──────────────────────────────────────────────────────────────────────

def load(rec_id: str):
    """One record, or ``None``."""
    try:
        return json.loads(_record_path(rec_id).read_text(encoding="utf-8"))
    except Exception:
        return None


def list_records(status: str = None, since_ts: float = None,
                 severity: str = None) -> list:
    """Records NEWEST-FIRST. Directory-authoritative (the index only orders).

    Deliberately mirrors the effort-history index-loss repair: a record present
    on disk but missing from a clobbered index is still returned.
    """
    seen, out = set(), []
    for rid in reversed(_load_index()):
        rec = load(rid)
        if rec is not None:
            seen.add(rid)
            out.append(rec)
    try:
        for p in sorted(friction_dir().glob("*.json"), reverse=True):
            if p.name == INDEX_NAME:
                continue
            rid = p.stem
            if rid in seen:
                continue
            rec = load(rid)
            if rec is not None:
                out.append(rec)
    except Exception:
        pass
    if status:
        out = [r for r in out if r.get("status") == status]
    if severity:
        out = [r for r in out if r.get("severity") == severity]
    if since_ts is not None:
        out = [r for r in out if float(r.get("ts") or 0) >= float(since_ts)]
    out.sort(key=lambda r: float(r.get("ts") or 0), reverse=True)
    return out


def safe_projection(rec: dict) -> dict:
    """The shape safe to hand a browser/API caller (no host paths)."""
    ctx = dict(rec.get("context") or {})
    ctx.pop("recent_errors", None)  # error lines can carry host paths
    return {
        "id": rec.get("id"), "iso": rec.get("iso"), "ts": rec.get("ts"),
        "severity": rec.get("severity"), "status": rec.get("status"),
        "source": rec.get("source"), "title": rec.get("title"),
        "body": rec.get("body"), "context": ctx,
        "resolution": rec.get("resolution"),
    }


# ── lifecycle (explicit only — nothing self-resolves) ────────────────────────

def set_status(rec_id: str, status: str, note: str = "", commit: str = "") -> dict:
    """Move a record's lifecycle state. Explicit action only."""
    st = str(status or "").strip().lower()
    if st not in STATUSES:
        raise FrictionJournalError(
            f"unknown status {status!r} — expected one of {', '.join(STATUSES)}")
    rec = load(rec_id)
    if rec is None:
        raise FrictionJournalError(f"no friction record {rec_id!r}")
    rec["status"] = st
    if st != "open":
        rec["resolution"] = {
            "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "note": str(note or "")[:MAX_BODY_CHARS],
            "commit": str(commit or "").strip(),
        }
    path = _record_path(rec_id)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rec, indent=1), encoding="utf-8")
    os.replace(tmp, path)
    return rec


# ── the sleep-cycle intake brief ─────────────────────────────────────────────

#: Cheap deterministic clustering — keyword → area. No model call.
_AREAS = (
    ("terminal", ("terminal", "pty", "console", "xterm", "double", "print",
                  "scroll", "paste")),
    ("dictation/input", ("dictat", "voice", "speech", "ipad", "keyboard",
                         "compose", "type", "input")),
    ("summaries/restart", ("summary", "summaries", "restart", "resume",
                           "handoff", "carry", "brief")),
    ("usage/cost", ("token", "usage", "cost", "$", "spend", "meter", "billing")),
    ("zombie/sessions", ("zombie", "orphan", "session", "reaper", "kill",
                         "freeze", "hunter")),
    ("dashboard/tiles", ("tile", "board", "dashboard", "kanban", "render",
                         "transition", "flash", "slow")),
    ("skills/engines", ("skill", "crucible", "foreman", "gandalf", "jumper",
                        "claude", "gemini", "grok", "engine")),
)


def classify_area(rec: dict) -> str:
    """Deterministic keyword area for grouping. Never a model call."""
    hay = f"{rec.get('title','')} {rec.get('body','')}".lower()
    for area, keys in _AREAS:
        if any(k in hay for k in keys):
            return area
    return "other"


def friction_report(status: str = "open", since_ts: float = None) -> str:
    """Render the SLEEP-CYCLE INTAKE BRIEF as markdown.

    This is the document a cleanup session (Fable et al.) reads. It is the
    automated replacement for the hand-written ``docs/friction/*.md`` files.
    """
    recs = list_records(status=status, since_ts=since_ts)
    now = time.strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# Anchor friction — sleep-cycle intake ({now})",
        "",
        f"**{len(recs)} record(s)**"
        + (f" · status `{status}`" if status else " · all statuses")
        + f" · Anchor {_anchor_version()}",
        "",
    ]
    if not recs:
        lines += ["_No friction recorded for this filter — nothing to clean up._",
                  ""]
        return "\n".join(lines)
    buckets = {}
    for r in recs:
        buckets.setdefault(classify_area(r), []).append(r)
    lines += ["## What hurt, by area", ""]
    for area in sorted(buckets, key=lambda a: (-len(buckets[a]), a)):
        rs = buckets[area]
        sevs = ", ".join(sorted({r.get("severity", "?") for r in rs}))
        lines.append(f"### {area} — {len(rs)} record(s) ({sevs})")
        lines.append("")
        for r in rs:
            lines.append(f"- **{r.get('title','(untitled)')}** "
                         f"`{r.get('id')}` · {r.get('iso','')} · "
                         f"{r.get('severity','')}")
            body = (r.get("body") or "").strip()
            if body:
                for bl in body.splitlines()[:6]:
                    lines.append(f"  > {bl}")
            ctx = r.get("context") or {}
            facts = [f"{k}={ctx[k]}" for k in
                     ("project_id", "session_id", "lane", "route", "engine")
                     if ctx.get(k)]
            if facts:
                lines.append(f"  - context: {' · '.join(facts)}")
            errs = (ctx.get("recent_errors") or [])[-2:]
            for e in errs:
                lines.append(f"  - log: `{e[:160]}`")
        lines.append("")
    lines += [
        "## How to work this brief",
        "",
        "1. Each record is the USER'S WORDS, verbatim — treat them as ground truth.",
        "2. Verify against the code before believing any diagnosis (including this",
        "   file's clustering, which is keyword-only and never a model judgement).",
        "3. Close a record explicitly when fixed:",
        "   `python anchor.py friction-resolve <id> --commit <sha> --note \"…\"`",
        "   Records stay OPEN until someone says otherwise — nothing self-resolves.",
        "",
    ]
    return "\n".join(lines)
