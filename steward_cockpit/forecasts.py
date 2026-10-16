"""W4 (2026-10-10): every forecast Anchor shows is kept with its issue time, the job or skill it is about, its basis
and the milestone it names ("worker finished"); when that same milestone happens, its actual time is recorded beside
it. So "accurate updates and estimates" (John, 2026-10-08) can be measured, not asserted - only for forecasts whose
milestone was observed.

One append-only file per effort: <effort>/.ecgberht/forecasts.jsonl. A forecast is written only when it CHANGES for
its subject (the status pane recomposes every few seconds); an actual is written once. Never raises.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path

MILESTONE = "worker finished"
_CLOCK = re.compile(r"\b(\d{1,2}):(\d{2})\b")
_RANGE = re.compile(r"\b(\d{1,2}:\d{2})\s*(?:[-\u2013\u2014]|to)\s*(\d{1,2}:\d{2})\b")
MAX_BYTES = 512 * 1024          # past this the file is compacted: resolved history moves to the archive
KEEP_ROWS = 300                 # the newest rows a compaction keeps, beside every unresolved subject
_LOCK = threading.Lock()


def _path(cdir):
    return Path(cdir) / ".ecgberht" / "forecasts.jsonl"


def _rows(cdir):
    try:
        lines = _path(cdir).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:                       # bounded by compaction, so an old unresolved forecast is never dropped
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _append(cdir, row):
    p = _path(cdir)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    try:
        if p.stat().st_size > MAX_BYTES:
            _compact(cdir)
    except OSError:
        pass


def _compact(cdir):
    """Keep every row of a subject still waiting for its actual, and the newest KEEP_ROWS rows; the rest (resolved
    history) moves to forecasts-archive.jsonl. The active file stays small; nothing unresolved is lost."""
    p = _path(cdir)
    rows = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    done = {r.get("subject") for r in rows if r.get("type") == "actual"}
    keep_idx = {i for i, r in enumerate(rows) if r.get("subject") not in done} | set(range(max(0, len(rows) - KEEP_ROWS), len(rows)))
    keep = [r for i, r in enumerate(rows) if i in keep_idx]
    moved = [r for i, r in enumerate(rows) if i not in keep_idx]
    if moved:
        with open(p.with_name("forecasts-archive.jsonl"), "a", encoding="utf-8") as fh:
            for r in moved:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in keep), encoding="utf-8")
    os.replace(str(tmp), str(p))


def clock_epoch(text, now=None):
    """The epoch of the first HH:MM in a forecast's text (the next such time at or after 12 h before now), or None."""
    m = _CLOCK.search(str(text or ""))
    if not m:
        return None
    now = time.time() if now is None else now
    lt = time.localtime(now)
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return None
    t = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, h, mi, 0, 0, 0, -1))
    if t < now - 12 * 3600:
        t += 86400
    return t


def basis_of(text):
    """The basis the forecast's own words state: own (the work's own estimate), typical (same-kind history),
    provisional, none (no basis), or calculated."""
    t = str(text or "").lower()
    if "its own estimate" in t:
        return "own"
    if "typical" in t or "longer than usual" in t:
        return "typical"
    if "provisional" in t:
        return "provisional"
    if "no basis" in t or "no finish time" in t:
        return "none"
    return "calculated"


def window(text, now=None):
    """(low, high) epochs of the forecast's stated time - a range "14:10-14:30" kept as a range, one time as (t, t)."""
    m = _RANGE.search(str(text or ""))
    if m:
        a, b = clock_epoch(m.group(1), now), clock_epoch(m.group(2), now)
        if a and b:
            return (a, b) if a <= b else (a, b + 86400)
    t = clock_epoch(text, now)
    return (t, t) if t else (None, None)


def note(cdir, subject, kind, text, basis=None, now=None):
    """Record a forecast for ``subject`` (a job id or skill run id) when its text changed; a forecast with no clock
    time ("no basis ...") is recorded too - it is what John was told."""
    if not subject or not text:
        return False
    now = time.time() if now is None else now
    try:
        with _LOCK:
            last = None
            for row in reversed(_rows(cdir)):
                if row.get("subject") == subject and row.get("type") == "forecast":
                    last = row
                    break
            if last and last.get("text") == text:
                return False
            low, high = window(text, now)
            _append(cdir, {"type": "forecast", "subject": subject, "kind": kind, "milestone": MILESTONE,
                           "issued_at": round(now, 1), "text": text, "forecast_epoch": low, "forecast_high": high,
                           "basis": basis or basis_of(text)})
            return True
    except Exception:
        return False


def observe(cdir, subject, actual_epoch):
    """Record the milestone's actual time for a subject that was forecast, once."""
    if not subject or not actual_epoch:
        return False
    try:
        with _LOCK:
            rows = _rows(cdir)
            if not any(r.get("subject") == subject and r.get("type") == "forecast" for r in rows):
                return False
            if any(r.get("subject") == subject and r.get("type") == "actual" for r in rows):
                return False
            _append(cdir, {"type": "actual", "subject": subject, "milestone": MILESTONE,
                           "actual_epoch": round(float(actual_epoch), 1), "recorded_at": round(time.time(), 1)})
            return True
    except Exception:
        return False


def pending(cdir):
    """The subjects forecast but with no actual recorded yet."""
    rows = _rows(cdir)
    done = {r.get("subject") for r in rows if r.get("type") == "actual"}
    return {r.get("subject") for r in rows if r.get("type") == "forecast"} - done


def observe_finished(cdir, epoch_of):
    """For every pending subject, read its job record (code-jobs.json / skill-jobs.json) and record the finish it
    reached. ``epoch_of`` turns a record's stamp into an epoch."""
    subjects = pending(cdir)
    if not subjects:
        return 0
    n = 0
    for name, prefix in (("code-jobs.json", "code:"), ("skill-jobs.json", "skill:")):
        try:
            raw = json.loads((Path(cdir) / ".ecgberht" / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for jid, rec in (raw.items() if isinstance(raw, dict) else []):
            subject = prefix + str((rec or {}).get("id") or jid)
            if subject in subjects and isinstance(rec, dict) and rec.get("finished"):
                if observe(cdir, subject, epoch_of(rec.get("finished"))):
                    n += 1
    return n


def accuracy(cdir):
    """[{subject, kind, issued_at, text, forecast_epoch, actual_epoch, error_min}] for every forecast with a clock
    time whose milestone was observed (the last forecast issued before the actual)."""
    rows = _rows(cdir)
    actual = {r["subject"]: r["actual_epoch"] for r in rows if r.get("type") == "actual" and r.get("actual_epoch")}
    out = []
    for subject, act in actual.items():
        fc = [r for r in rows if r.get("type") == "forecast" and r.get("subject") == subject
              and r.get("forecast_epoch") and r.get("issued_at", 0) <= act]
        if not fc:
            continue
        last = fc[-1]
        low, high = last["forecast_epoch"], last.get("forecast_high") or last["forecast_epoch"]
        err = 0.0 if low <= act <= high else ((act - high) if act > high else (act - low))   # inside the window: 0
        out.append({"subject": subject, "kind": last.get("kind"), "basis": last.get("basis"), "issued_at": last["issued_at"],
                    "text": last["text"], "forecast_epoch": low, "forecast_high": high, "actual_epoch": act,
                    "error_min": round(err / 60.0, 1)})
    return out
