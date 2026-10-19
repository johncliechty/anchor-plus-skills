"""health_state - the banner tells the truth (W3 of the overnight plan of 2026-10-08; John that day: "I want it to
diagnose, resolve health issues and have the banner go down once that is done").

ONE store and ONE reading of it for every banner (the Cave's, the classic dashboard's, the Doctor's card):
``paths.health_reports_dir()``, where only a dated report (``YYYY-MM-DD.md``) is ever taken as "the newest" - never
README.md or a soak ledger. It is written by the daily self-test and by the Doctor's re-run, both of which check the
code the service runs. Red stays red until such a run passes.

Stdlib only; never raises.
"""
from __future__ import annotations

import re

DATED = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")


def reports_dir():
    import paths as _paths
    return _paths.health_reports_dir()


def dated_reports():
    """The dated reports, newest first (by name - the date)."""
    try:
        return sorted((p for p in reports_dir().glob("*.md") if p.is_file() and DATED.match(p.name)),
                      key=lambda p: p.name, reverse=True)
    except OSError:
        return []


def status_of(body):
    """red | yellow | green | unknown, per the locked severity rule (correctness red; timing notes yellow)."""
    body = body or ""
    if "Status: ISSUES FOUND" in body:
        return "red"
    m = re.search(r"^## Warnings[^\n]*\n+(.*?)(?=^## |\Z)", body, re.S | re.M)
    if m and m.group(1).strip() and m.group(1).strip() != "(none)":
        return "yellow"
    if re.search(r"^Status: OK\s*$", body, re.M):
        return "green"
    return "unknown"


def field(body, name):
    m = re.search(r"^%s:\s*(.+)$" % re.escape(name), body or "", re.M)
    return m.group(1).strip() if m else ""


def latest():
    """(path, body) of the newest readable dated report, or (None, "")."""
    for p in dated_reports():
        try:
            return p, p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    return None, ""


def _parse_issues(body):
    try:
        m = re.search(r"^## Issues[^\n]*\n+(.*?)(?=^## |\Z)", body or "", re.S | re.M)
        if not m:
            return []
        out = []
        for ln in m.group(1).splitlines():
            ln = ln.strip()
            if not ln.startswith("- "):
                continue
            mm = re.match(r"- \[([^\]]+)\]\s*(.*)", ln)
            comp = mm.group(1) if mm else ""
            detail = (mm.group(2) if mm else ln[2:]).strip()
            out.append({"component": comp[:120], "detail": detail[:400]})
            if len(out) >= 8:
                break
        return out
    except Exception:
        return []


def banner():
    """None, or the red banner's facts: {"status", "date", "report", "text", "why", "issues", "plain_issues"}."""
    path, body = latest()
    if path is None or status_of(body) != "red":
        return None
    issues = _parse_issues(body)
    plain_issues = []
    try:
        import doctor_plain as _dp
        for ex in _dp.explain_all(issues, []):
            t = (ex.get("title") or "").strip()
            if t:
                plain_issues.append(t)
    except Exception:
        plain_issues = [f"{it.get('component') or 'check'}: {it.get('detail') or ''}".strip(": ") for it in issues]
    return {"status": "red", "date": path.stem, "report": path.name,
            "text": "Health check found issues", "why": "%s — Doctor can diagnose it" % path.stem,
            "issues": issues, "plain_issues": plain_issues[:4]}


def signature():
    """An opaque fingerprint of what the banner says (no content leaves): the newest report's name, time and status.
    A page compares it to know its banner is stale."""
    import hashlib
    path, body = latest()
    try:
        stamp = str(int(path.stat().st_mtime)) if path else ""
    except OSError:
        stamp = ""
    parts = [path.name if path else "", stamp, status_of(body)]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]
