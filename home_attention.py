"""Home attention — the deterministic v0 ranking behind the steward's rail and the
"Needs attention" rows on the home page.

Design contract: ``_mockups/dashboard-v2`` (prototype r3, 2026-08-27/28) and its
SCORECARD — "Ranked. One raise. ... no hidden score" — as read by the 2026-08-29
best-in-class addendum ("home is an attention and intervention surface, not a
repository browser"; "Anchor should show the exact rule that raised an item").

Pure: takes facts, returns rows. No I/O, no model, no clock of its own (the
caller passes ``today``/``now``), never raises on odd input. The ranking IS the
rule order below; every row names the rule that raised it so the order is
explainable, and nothing here is a score a user cannot see.

The steward's own raise queue is NOT computed here — it needs the Ecgberht
bridge process, which the home render must never spawn. The page adds that row
client-side from the badge it already polls (``static/high-seat.js``).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

# Rule order == rank order. (name, severity, plain label)
RULES = (
    ("health", "red", "health check"),
    ("needs-you", "red", "a session is waiting on you"),
    ("overdue", "red", "overdue task"),
    ("due-today", "amber", "due today"),
    ("failed", "amber", "failed session (7 days)"),
)
_RANK = {name: i for i, (name, _sev, _lab) in enumerate(RULES)}
_SEV = {name: sev for name, sev, _lab in RULES}
_LABEL = {name: lab for name, _sev, lab in RULES}

FAILED_WINDOW = timedelta(days=7)
# Lanes whose sessions are project work a person can act on. Swarm seats and
# other engine-internal lanes fail and finish on their own; they are not
# "waiting on you".
ACTIONABLE_LANES = frozenset(
    {"research", "plan", "planning", "build", "general", "grass", "steward"})


def _iso_date(v):
    """'YYYY-MM-DD' → date, else None. Tolerates datetimes and junk."""
    if isinstance(v, date):
        return v
    s = str(v or "").strip()[:10]
    try:
        return date.fromisoformat(s)
    except Exception:
        return None


def _ts(v):
    """epoch seconds / ISO string → datetime (naive, local), else None."""
    if v is None or v == "":
        return None
    try:
        if isinstance(v, (int, float)):
            return datetime.fromtimestamp(float(v))
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _row(rule, text, why, href, kind, project_id=""):
    return {
        "rule": rule,
        "rule_label": _LABEL[rule],
        "severity": _SEV[rule],
        "text": str(text or "").strip(),
        "why": str(why or "").strip(),
        "href": href or "",
        "kind": kind,            # 'system' | 'project' | 'task'
        "project_id": project_id or "",
    }


def build_attention(tasks=(), sessions=(), health=None, today=None, now=None,
                    project_names=None, limit=6):
    """Return the ranked attention rows (at most ``limit``).

    ``tasks``    — home task dicts (``text`` · ``priority`` · ``due`` · ``done``).
    ``sessions`` — session-registry records (``status`` · ``lane`` · ``project_id``
                   · ``label`` · ``updated_at``/``created_at``).
    ``health``   — ``(report_date, status)`` from the latest health report or None.
    ``today``    — date; ``now`` — datetime (both default to the wall clock only
                   when omitted, so tests pass them explicitly).
    """
    today = today or date.today()
    now = now or datetime.now()
    names = project_names or {}
    rows = []

    # 1. health — the daily self-test found issues (the red banner's fact)
    try:
        if health:
            report_date, status = health[0], str(health[1] or "")
            if any(w in status.upper() for w in ("ISSUE", "FAIL", "ERROR")):
                rows.append(_row(
                    "health", "Health check found issues",
                    "%s — Doctor can diagnose it" % report_date,
                    "/doctor?issueId=ZH_HEALTH_CHECK_ISSUES&diagnose=1", "system"))
    except Exception:
        pass

    # 2. needs-you — a managed session parked in needs-attention
    needs, failed = [], []
    for rec in sessions or ():
        try:
            if not isinstance(rec, dict):
                continue
            pid = str(rec.get("project_id") or "")
            lane = str(rec.get("lane") or "")
            if not pid or (lane and lane not in ACTIONABLE_LANES):
                continue
            st = str(rec.get("status") or "")
            when = _ts(rec.get("updated_at")) or _ts(rec.get("created_at"))
            if st == "needs-attention":
                needs.append((when or datetime.min, rec, pid))
            elif st == "failed" and when and now - when <= FAILED_WINDOW:
                failed.append((when, rec, pid))
        except Exception:
            continue
    needs.sort(key=lambda t: t[0], reverse=True)
    for when, rec, pid in needs:
        nm = names.get(pid) or rec.get("label") or pid[:8]
        rows.append(_row("needs-you", "%s is waiting on you" % nm,
                         "%s session needs an answer" % (rec.get("lane") or "a"),
                         "/project/%s" % pid, "project", pid))

    # 3./4. tasks — overdue (oldest first, P1 first), then due today (P1 first)
    overdue, due_today = [], []
    for t in tasks or ():
        try:
            if not isinstance(t, dict) or t.get("done"):
                continue
            d = _iso_date(t.get("due"))
            if d is None:
                continue
            pr = int(t.get("priority") or 3)
            if d < today:
                overdue.append((d, pr, t))
            elif d == today:
                due_today.append((pr, t))
        except Exception:
            continue
    overdue.sort(key=lambda x: (x[0], x[1], x[2].get("text", "")))
    due_today.sort(key=lambda x: (x[0], x[1].get("text", "")))
    for d, pr, t in overdue:
        days = (today - d).days
        rows.append(_row("overdue", t.get("text", ""),
                         "P%d · due %s (%d day%s ago)" % (pr, d.isoformat(), days, "" if days == 1 else "s"),
                         "#tile-tasks", "task"))
    for pr, t in due_today:
        rows.append(_row("due-today", t.get("text", ""), "P%d · due today" % pr,
                         "#tile-tasks", "task"))

    # 5. failed — recent failed sessions, newest first
    failed.sort(key=lambda t: t[0], reverse=True)
    for when, rec, pid in failed:
        nm = names.get(pid) or rec.get("label") or pid[:8]
        rows.append(_row("failed", "%s: a %s session failed" % (nm, rec.get("lane") or "work"),
                         when.strftime("%a %d %b %H:%M"), "/project/%s" % pid, "project", pid))

    rows.sort(key=lambda r: _RANK[r["rule"]])  # stable: keeps each rule's own order
    return rows[: max(0, int(limit or 0))] if limit else rows


def the_move(rows, seat_name="High Seat"):
    """The rail's one sentence: the top row, or an honest quiet line."""
    if not rows:
        return ("Nothing is waiting on you.",
                "The steward will raise the next thing here.")
    top = rows[0]
    lead = top["text"]
    if top["why"]:
        lead = "%s — %s." % (lead, top["why"])
    return (lead, "You can act from here. Opening the %s is optional." % seat_name)


def rail_counts(sessions=(), rows=(), folders=0, open_projects=0):
    """The rail's 2×2: open · running · need you · folders."""
    running = 0
    for rec in sessions or ():
        try:
            if isinstance(rec, dict) and rec.get("status") == "running":
                running += 1
        except Exception:
            continue
    need_you = sum(1 for r in rows or () if r.get("kind") == "project")
    return {"open": int(open_projects or 0), "running": running,
            "need_you": need_you, "folders": int(folders or 0)}


def due_rows(tasks=(), today=None, limit=5):
    """The rail's 'Due today' list — overdue and today, P1 first, as (text, priority, overdue?)."""
    today = today or date.today()
    out = []
    for t in tasks or ():
        try:
            if not isinstance(t, dict) or t.get("done"):
                continue
            d = _iso_date(t.get("due"))
            if d is None or d > today:
                continue
            out.append((d, int(t.get("priority") or 3), t.get("text", ""), d < today))
        except Exception:
            continue
    out.sort(key=lambda x: (x[1], x[0], x[2]))
    rows = [{"text": x[2], "priority": x[1], "overdue": x[3]} for x in out]
    return rows[:limit], max(0, len(rows) - limit)


def live_rows(sessions=(), project_names=None, limit=3):
    """The rail's 'Workbench' list — running sessions, newest first."""
    names = project_names or {}
    live = []
    for rec in sessions or ():
        try:
            if not isinstance(rec, dict) or rec.get("status") != "running":
                continue
            pid = str(rec.get("project_id") or "")
            when = _ts(rec.get("updated_at")) or _ts(rec.get("created_at")) or datetime.min
            label = rec.get("label") or names.get(pid) or (rec.get("lane") or "session")
            live.append((when, {"text": str(label), "project_id": pid,
                                "lane": str(rec.get("lane") or "")}))
        except Exception:
            continue
    live.sort(key=lambda x: x[0], reverse=True)
    rows = [x[1] for x in live]
    return rows[:limit], max(0, len(rows) - limit)
