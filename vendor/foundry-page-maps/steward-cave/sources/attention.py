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
import re

from datetime import date, datetime, timedelta

# Rule order == rank order. (name, severity, plain label)
RULES = (
    ("health", "red", "health check"),
    ("needs-you", "red", "a session is waiting on you"),
    ("overdue", "red", "overdue task"),
    ("due-today", "amber", "due today"),
    ("due-soon", "amber", "due within five weeks"),
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


def _row(rule, text, why, href, kind, project_id="", label=None):
    return {
        "rule": rule,
        "rule_label": label or _LABEL[rule],
        "severity": _SEV[rule],
        "text": str(text or "").strip(),
        "why": str(why or "").strip(),
        "href": href or "",
        "kind": kind,            # 'system' | 'project' | 'task'
        "project_id": project_id or "",
    }


def build_attention(tasks=(), sessions=(), health=None, today=None, now=None,
                    project_names=None, limit=6, projects=()):
    """Return the ranked attention rows (at most ``limit``).

    ``tasks``    — home task dicts (``text`` · ``priority`` · ``due`` · ``done``).
    ``sessions`` — session-registry records (``status`` · ``lane`` · ``project_id``
                   · ``label`` · ``updated_at``/``created_at``).
    ``health``   — ``(report_date, status)`` from the latest health report or None.
    ``projects`` — ``home_rows.project_facts`` dicts (W1a, High Seat 2026-09-26): a project whose
                   steward record waits on John raises a needs-you row; its open dated steps raise
                   overdue / due-today / due-soon rows (soonest first, within five weeks).
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
    # one needs-you row per project (W1a): the project's own steward record — the strip's human
    # wait, else the last status's "waiting on you" — is the fact when it exists, and the row says
    # so; a managed session parked in needs-attention raises the row otherwise, and says that
    record_wait = {}
    for f in projects or ():
        try:
            if isinstance(f, dict) and f.get("id") and f.get("needs_you"):
                why = " ".join(str(f["needs_you"]).split())
                why = (why[:88].rstrip() + "…") if len(why) > 90 else why
                record_wait[str(f["id"])] = (str(f.get("name") or str(f["id"])[:8]), why)
        except Exception:
            continue
    seen = set()
    for when, rec, pid in needs:
        if pid in seen:
            continue
        seen.add(pid)
        if pid in record_wait:
            nm, why = record_wait[pid]
            rows.append(_row("needs-you", "%s is waiting on you" % nm, why, "/project/%s" % pid,
                             "project", pid, label="the steward's record waits on you"))
        else:
            nm = names.get(pid) or rec.get("label") or pid[:8]
            rows.append(_row("needs-you", "%s is waiting on you" % nm,
                             "%s session needs an answer" % (rec.get("lane") or "a"),
                             "/project/%s" % pid, "project", pid))
    for pid, (nm, why) in record_wait.items():
        if pid in seen:
            continue
        seen.add(pid)
        rows.append(_row("needs-you", "%s is waiting on you" % nm, why, "/project/%s" % pid,
                         "project", pid, label="the steward's record waits on you"))

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
    # 3b./4b./4c. dated steps — a project's open steps that carry a due (W1a): overdue, due today,
    #     and due within five weeks (the ruler's reach), soonest first; each links to its plan
    late, todays, soon = [], [], []
    horizon = today + timedelta(days=35)
    for f in projects or ():
        if not isinstance(f, dict):
            continue
        for st in f.get("dated") or ():
            try:
                d = _iso_date(st.get("due"))
                if d is None:
                    continue
                if d < today:
                    late.append((d, st))
                elif d == today:
                    todays.append((d, st))
                elif d <= horizon:
                    soon.append((d, st))
            except Exception:
                continue
    for bucket in (late, todays, soon):
        bucket.sort(key=lambda x: (x[0], x[1].get("name", "")))
    for d, st in late:
        days = (today - d).days
        rows.append(_row("overdue", st.get("name", ""),
                         "due %s (%d day%s ago) · %s" % (_short(d), days, "" if days == 1 else "s", st.get("project_name", "")),
                         "/project/%s" % st.get("project_id", ""), "step", st.get("project_id", "")))
    for d, st in todays:
        rows.append(_row("due-today", st.get("name", ""), "due today · %s" % st.get("project_name", ""),
                         "/project/%s" % st.get("project_id", ""), "step", st.get("project_id", "")))
    for d, st in soon:
        rows.append(_row("due-soon", st.get("name", ""), "due %s · %s" % (_short(d), st.get("project_name", "")),
                         "/project/%s" % st.get("project_id", ""), "step", st.get("project_id", "")))

    # 5. failed — recent failed sessions, newest first
    failed.sort(key=lambda t: t[0], reverse=True)
    for when, rec, pid in failed:
        nm = names.get(pid) or rec.get("label") or pid[:8]
        rows.append(_row("failed", "%s: a %s session failed" % (nm, rec.get("lane") or "work"),
                         when.strftime("%a %d %b %H:%M"), "/project/%s" % pid, "project", pid))

    rows.sort(key=lambda r: _RANK[r["rule"]])  # stable: keeps each rule's own order
    return rows[: max(0, int(limit or 0))] if limit else rows


def _short(d):
    """date → 'Oct 8'."""
    d = _iso_date(d)
    return ("%s %d" % (d.strftime("%b"), d.day)) if d else ""


def brief_bullets(rows, projects=(), today=None, seat_name="High Seat"):
    """The rail's brief as bullets (W1a, High Seat 2026-09-26): the move, who waits on him, what the
    week holds (or the nearest date), and the standing line. Facts only; never more than four."""
    today = today or date.today()
    bullets = []
    top = rows[0] if rows else None
    if top:
        bullets.append("%s%s." % (top["text"], (" — " + top["why"]) if top.get("why") else ""))
    else:
        bullets.append("Nothing is waiting on you.")
    # who waits: counted from the facts (every project whose record waits), never from the capped rows
    waiting = [str(f.get("name") or "") for f in projects or () if isinstance(f, dict) and f.get("needs_you")]
    for r in rows or ():
        if r.get("rule") == "needs-you":
            nm = r["text"].replace(" is waiting on you", "")
            if nm not in waiting:
                waiting.append(nm)
    if len(waiting) > 1:
        bullets.append("%d wait on you: %s." % (len(waiting), ", ".join(waiting[:4]) + (" and more" if len(waiting) > 4 else "")))
    # the week is the header's: Monday to Sunday; a date already past inside it is named overdue
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    dated = []
    for f in projects or ():
        if isinstance(f, dict):
            for st in f.get("dated") or ():
                d = _iso_date(st.get("due"))
                if d is not None:
                    dated.append((d, st))
    dated.sort(key=lambda x: (x[0], x[1].get("name", "")))
    this_week = [(d, st) for d, st in dated if week_start <= d <= week_end]
    if this_week:
        def _say(d, st):
            tag = "overdue since %s" % _short(d) if d < today else ("today" if d == today else _short(d))
            return "%s (%s, %s)" % (st.get("name", ""), tag, st.get("project_name", ""))
        bullets.append("This week: " + "; ".join(_say(d, st) for d, st in this_week[:3]) + ".")
    else:
        ahead = next(((d, st) for d, st in dated if d >= today), None)
        if ahead:
            bullets.append("Nothing is due this week; the nearest date is %s (%s, %s)." % (
                _short(ahead[0]), ahead[1].get("name", ""), ahead[1].get("project_name", "")))
        else:
            bullets.append("Nothing carries a date yet.")
    bullets.append("You can act from here. Opening the %s is optional." % seat_name)
    return bullets[:4]


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


_PART_CLOSED = ("done", "cancelled", "dropped", "parked")


def _part_open(p):
    return (isinstance(p, dict) and not p.get("broken") and p.get("status") not in ("done", "parked")
            and p.get("target_status") not in _PART_CLOSED)


def _wait_reason(p):
    """What a seated initiative waits for: the reason the tile line already reads ("waiting on you: <reason>"); empty
    when the state is not a wait, when the reason only repeats the part's name, or when it only names him (Grok's
    read of W2b: the sentence never restates its own head)."""
    st = str(p.get("state") or "")
    if not st.lower().startswith("waiting on you"):
        return ""
    reason = re.sub(r"^waiting on you[:\s]*", "", st, flags=re.I).strip(" .")
    name = " ".join(str(p.get("target") or p.get("text") or "").lower().split())
    if not reason or " ".join(reason.lower().split()) == name or reason.lower() in ("john", "you", "me"):
        return ""
    return reason


def head_act(initiatives, facts, today=None):
    """THE HEAD — one act, never a list (W2 of the steward revision, 2026-09-28; the synthesis R2; his answer Q3).
    The SEATS read first (2026-09-30, his three levels): an ACTIVE initiative — a cockpit, an effort or a desk item
    he pulled out of its goal — that needs him leads, in his order; then one ON DECK that needs him; the sentence
    says the date when there is one. Then his tiers: the first Tier-1 part that needs him, in his
    order (a Tier-1 part that needs him AND is due comes first among them); the one exception, his word (narrowed on
    Grok's W2 read): a Tier-2/3 part that NEEDS him and is due today or overdue — marked as the exception, with its
    date — earliest date first, then his tier and order; it yields to a Tier-1 part that needs him and is due, and to
    anything inside the set (an outside deadline while he is deep in the set is W3's nudge, not the head). Else the
    oldest wait across the projects, with its age from the record. ``None`` when nothing needs him and nothing is
    due."""
    today = today or date.today()
    inits = sorted([i for i in initiatives or () if isinstance(i, dict)],
                   key=lambda i: (i.get("tier") or 9, int(i.get("order") or 0), str(i.get("name") or "")))

    def _act(i, p, kind, **more):
        parts = [x for x in i.get("parts") or () if isinstance(x, dict)]
        after = next((x for x in parts[parts.index(p) + 1:] if _part_open(x)), None) if p in parts else None
        a = {"kind": kind, "tier": i.get("tier"), "initiative": str(i.get("name") or ""), "text": str(p.get("text") or ""),
             "target": str(p.get("target") or ""), "pid": str(p.get("pid") or ""), "href": str(p.get("href") or ""),
             "date": str(p.get("date") or ""), "then": str(after.get("text") or "") if after else "", "age_days": None,
             "effort": "", "dir": None,
             # the seated act (2026-09-30): the initiative's own name and what it waits for, said as the sentence says them
             "part": str(p.get("target") or p.get("text") or ""),
             "what": _wait_reason(p)}
        a.update(more)
        return a

    def _due(p):
        d = _iso_date(p.get("date")) if p.get("date") else None
        return d if (d is not None and d <= today) else None

    def _needs(p):
        return _part_open(p) and bool(p.get("needs_you"))

    # the seats read FIRST (2026-09-30): an active initiative that needs him, in his order; then one on deck
    from high_seat_page import seated
    for kind in ("active", "deck"):
        for g, p in seated(inits, kind):
            if _needs(p):
                d = _due(p)
                return _act(g, p, kind, due=d.isoformat() if d else "", overdue=bool(d and d < today))
    # a Tier-1 part that needs him and is due leads everything
    t1_due = sorted(((_due(p), int(i.get("order") or 0), n, i, p) for i in inits if i.get("tier") == 1
                     for n, p in enumerate(i.get("parts") or ()) if _needs(p) and _due(p)), key=lambda t: t[:3])
    if t1_due:
        _d, _o, _n, i, p = t1_due[0]
        return _act(i, p, "tier1")
    # the exception: a lower-tier part that needs him, due today or overdue — earliest date, then tier and order
    low = sorted(((_due(p), int(i.get("tier")), int(i.get("order") or 0), n, i, p)
                  for i in inits if i.get("tier") in (2, 3)
                  for n, p in enumerate(i.get("parts") or ()) if _needs(p) and _due(p)), key=lambda t: t[:4])
    if low:
        d, _t, _o, _n, i, p = low[0]
        return _act(i, p, "exception", due=d.isoformat(), overdue=d < today)
    for i in inits:
        if i.get("tier") == 1:
            for p in i.get("parts") or ():
                if _needs(p):
                    return _act(i, p, "tier1")
    waits = [f for f in facts or () if isinstance(f, dict) and f.get("needs_you")]
    if waits:
        f = max(waits, key=lambda f: (f.get("wait_age_days") if isinstance(f.get("wait_age_days"), (int, float)) else -1))
        return {"kind": "oldest-wait", "tier": None, "initiative": "", "text": str(f.get("needs_you") or ""),
                "target": str(f.get("name") or ""), "pid": str(f.get("id") or ""), "href": str(f.get("href") or ""),
                "date": "", "then": str(f.get("next") or ""), "age_days": f.get("wait_age_days"),
                "effort": str(f.get("needs_you_effort") or f.get("effort") or ""),
                "dir": str(f.get("needs_you_effort") or f.get("effort") or "")}
    return None


def pick_up(initiatives, facts=None, working=None, today=None):
    """What to take up while Active runs (2026-09-30, his three levels): when Active is not empty, nothing in it needs
    him and every active initiative is RUNNING (a live session on its project) or WAITING on someone else, the top
    of ON DECK — his own pick-up list, in his order. None otherwise: an active initiative with a free hand is his
    next act, not a pick-up; an empty Active has nothing to be "while" of; an empty deck offers nothing. The answer
    says which active initiatives run and which wait, so the sentence can too."""
    from high_seat_page import seated, part_name
    working = working or set()
    inits = [i for i in initiatives or () if isinstance(i, dict)]
    active = seated(inits, "active")
    if not active:
        return None
    running, waiting = [], []
    for g, p in active:
        if _part_open(p) and p.get("needs_you"):
            return None
        if p.get("pid") and p["pid"] in working:
            running.append(part_name(p))
        elif str(p.get("state") or "").lower().startswith("waiting") or p.get("status") == "waiting":
            waiting.append(part_name(p))
        else:
            return None      # a free hand: that is his next act, not a pick-up
    deck = seated(inits, "deck")
    if not deck:
        return None
    g, p = deck[0]
    st = str(p.get("state") or "")
    what = re.sub(r"^waiting on you:\s*", "", st, flags=re.I).strip() if st.lower().startswith("waiting on you") else ""
    return {"initiative": part_name(p), "goal": str(g.get("name") or ""), "id": str(p.get("id") or ""), "why": "on deck", "text": what,
            "pid": str(p.get("pid") or ""), "active": [part_name(x) for _g, x in active], "running": running, "waiting": waiting}


def head_sentence(act, overnight=(), pickup=None):
    """The head as one sentence he can act on: the pick, why now, the exact record (its effort when named), what
    follows — and, only when a step closed since he last opened the page, what finished (gated on the real
    instant of his last open: a quiet day and a second open repeat nothing)."""
    s = _head_core(act)
    if act is None and isinstance(pickup, dict) and pickup.get("initiative"):
        run = list(pickup.get("running") or ()) if ("running" in pickup or "waiting" in pickup) else list(pickup.get("active") or ())
        wait = list(pickup.get("waiting") or ())

        def _who(names):
            return (" and ".join(names) if len(names) <= 2 else ", ".join(names[:-1]) + " and " + names[-1]), ("is" if len(names) == 1 else "are")
        state = []
        if run:
            state.append("%s %s running" % _who(run))
        if wait:
            state.append("%s %s waiting on someone else" % _who(wait))      # said as the light says it (Grok W1): never "running" for a wait
        clause = ("While %s run%s" % (("it", "s") if len(run) == 1 else ("they", ""))) if run and not wait else (
            ("While %s wait%s" % (("it", "s") if len(wait) == 1 else ("they", ""))) if wait and not run else "Meanwhile")
        s = "Active: %s. %s: pick up %s%s%s (%s)." % (
            "; ".join(state) or "the set", clause, pickup["initiative"], (" (%s)" % pickup["goal"]) if pickup.get("goal") else "",
            (" — " + pickup["text"][:80]) if pickup.get("text") else "", pickup.get("why") or "")
    closed = [x for x in overnight or () if isinstance(x, dict) and x.get("name")]
    if closed:
        names = ", ".join(str(x["name"]) for x in closed[:3]) + (" and %d more" % (len(closed) - 3) if len(closed) > 3 else "")
        s += " Since you last opened: %d step%s closed — %s." % (len(closed), "" if len(closed) == 1 else "s", names)
    return s


def _head_core(act):
    if not act:
        return "Nothing is waiting on you."
    age = act.get("age_days")
    age_s = (" · waiting %d day%s" % (int(age), "" if int(age) == 1 else "s")) if isinstance(age, (int, float)) and age >= 1 else ""
    then = (" Then: %s." % act["then"][:100]) if act.get("then") else ""
    if act["kind"] == "exception":
        when = ("overdue since %s" % _short(act.get("due"))) if act.get("overdue") else "due today"
        return "Exception, %s: %s (%s, tier %s).%s" % (when, act["text"], act["initiative"], act.get("tier") or "?", then)
    if act["kind"] == "tier1":
        where = (" (%s%s)" % (act["target"], (" · " + act["effort"]) if act.get("effort") else "")) if act.get("target") else ""
        return "Tier 1 · %s: %s%s — waiting on you%s.%s" % (act["initiative"], act["text"], where, age_s, then)
    if act["kind"] in ("active", "deck"):
        # a seated initiative (2026-09-30): "Active · Family Trusts (The trusts): <what it waits for> — waiting on you."
        when = (", overdue since %s" % _short(act.get("due"))) if act.get("overdue") else (", due today" if act.get("due") else "")
        head = "Active" if act["kind"] == "active" else "On deck"
        what = str(act.get("what") or "")
        return "%s · %s (%s)%s — waiting on you%s%s.%s" % (head, act.get("part") or act["text"], act["initiative"], (": " + what) if what else "", when, age_s, then)
    where = "%s%s" % (act.get("target") or "A project", (" · " + act["effort"]) if act.get("effort") else "")
    return "%s: %s%s.%s" % (where, act["text"], age_s, then)


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


def due_rows(tasks=(), today=None, limit=5, projects=()):
    """The rail's 'Due today' list — overdue and today, P1 first, as (text, priority, overdue?);
    a project's overdue or due-today roadmap steps sit beside the tasks (W1a), so the card never
    says nothing is due while a step is."""
    today = today or date.today()
    out = []
    for f in projects or ():
        if not isinstance(f, dict):
            continue
        for st in f.get("dated") or ():
            try:
                d = _iso_date(st.get("due"))
                if d is None or d > today:
                    continue
                out.append((d, 1, "%s · %s" % (st.get("name", ""), st.get("project_name", "")), d < today))
            except Exception:
                continue
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
