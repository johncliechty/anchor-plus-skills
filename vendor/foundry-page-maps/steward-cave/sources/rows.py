"""home_rows — the facts each project row on the home is made of.

W1a of the High Seat plan (2026-09-26). Every row on the home is a fact from a project's
steward record — its strip (the human wait, the next step and why), its last persisted
status (the lead line), its roadmap (the open steps that carry a date) — never task
markdown, never steward prose. Three small reads per project, no scan, no model, no
bridge spawn on GET /. Never raises; a project without a record yields honest empties.
"""
from __future__ import annotations

import json
import time
from datetime import date, timedelta
from pathlib import Path

from steward_cockpit.steward_campaign import _real_wait as _cockpit_wait   # the cockpit's one rule for a wait that says "none"

_OPEN = ("proposed", "planned", "active", "waiting")


def _read_json(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return None


def _iso(v):
    try:
        return date.fromisoformat(str(v or "")[:10])
    except Exception:
        return None


def project_facts(entry, today=None):
    """One registry entry → the facts its home row is made of.

    ``needs_you``  the strip's human wait, else the last status's "waiting on you" (the fact
                   behind a needs-you row); ``next`` / ``why`` the strip's next step and its reason;
                   ``summary`` the last persisted status, parsed once, with ``summary_age_s`` (the
                   row's steward line reads it from here, not from the file again); ``dated`` the
                   open steps that carry a ``due`` (soonest first, each with its project);
                   ``nearest_due`` the first of them; ``has_record`` whether any file existed.
    """
    today = today or date.today()
    entry = entry if isinstance(entry, dict) else {}
    pid = str(entry.get("id") or "")
    name = str(entry.get("name") or pid[:8])
    folder = str(entry.get("folder_path") or "").strip()
    out = {"id": pid, "name": name, "href": ("/project/%s" % pid) if pid else "",
           "needs_you": "", "next": "", "why": "", "summary": None, "summary_age_s": None, "dated": [],
           "nearest_due": "", "has_record": False, "folder": folder, "projection": None}
    if not folder or not pid:
        return out
    root = Path(folder)
    # the record may live one folder down (the cockpit's own discovery: the root, or a subfolder with a Face);
    # the card reads the effort touched last and names it (John, 2026-09-27: "I don't see many efforts")
    rel = current_effort(folder)
    if rel:
        root = root / rel
    out["effort"] = rel
    strip = _read_json(root / "strip.json")
    if isinstance(strip, dict):
        out["has_record"] = True
        out["needs_you"] = _real_wait(strip.get("human_wait"))
        out["next"] = str(strip.get("next_recommended") or "").strip()
        out["why"] = str(strip.get("why_next") or "").strip()
    sfile = root / ".ecgberht" / "status-summary.json"
    summ = _read_json(sfile)
    if isinstance(summ, dict):
        out["has_record"] = True
        out["summary"] = summ
        try:
            out["summary_age_s"] = max(0.0, time.time() - sfile.stat().st_mtime)
        except Exception:
            out["summary_age_s"] = None
        plan = summ.get("plan") if isinstance(summ.get("plan"), dict) else {}
        if not out["needs_you"]:
            out["needs_you"] = _real_wait(plan.get("waiting_on_you"))
    rm = _read_json(root / "roadmap.json")
    if isinstance(rm, dict):
        out["has_record"] = True
        if not rel:
            out["projection"] = rm.get("roadmap_projection") or []   # the ROOT record only: a resolver in the same request keys on the project folder
        dated = []
        for s in rm.get("roadmap_projection") or []:
            if not isinstance(s, dict) or s.get("status") not in _OPEN:
                continue
            d = _iso(s.get("due")) if s.get("due") else None
            if d is None:
                continue
            dated.append({"step_id": str(s.get("id") or ""), "name": str(s.get("name") or ""),
                          "due": d.isoformat(), "status": str(s.get("status") or ""),
                          "project_id": pid, "project_name": name})
        dated.sort(key=lambda x: (x["due"], x["name"]))
        out["dated"] = dated
        out["nearest_due"] = dated[0]["due"] if dated else ""
        # W2 (2026-09-28): what closed — every status flip to done with its INSTANT (the event's `at`, else the
        # receipt's date at midnight), one per step (the latest), so the head's "since you last opened" can compare
        # against the real instant of his last page open (Grok W2: the date alone cannot see a second open)
        names_by_id = {str(s.get("id")): str(s.get("name") or s.get("id") or "") for s in rm.get("roadmap_projection") or [] if isinstance(s, dict)}
        closed = {}
        for ev in rm.get("roadmap_events") or []:
            if not isinstance(ev, dict) or ev.get("kind") != "status_flip" or str(ev.get("to") or "") != "done":
                continue
            rc = ev.get("receipt") if isinstance(ev.get("receipt"), dict) else {}
            instant = _instant(ev.get("at")) or _instant(rc.get("when"))
            if instant is None:
                continue
            sid = str(ev.get("step_id") or "")
            closed[sid] = {"step_id": sid, "name": names_by_id.get(sid, sid), "at": instant, "project_name": name, "project_id": pid}
        out["closed_recent"] = sorted(closed.values(), key=lambda x: x["at"])
        # W4 (2026-09-28): the repairs proposed and not yet resolved on his word (the card says "proposed: N corrections")
        try:
            from steward_cockpit.repair import open_proposals as _open_proposals
            props = _open_proposals(rm.get("roadmap_events"))
            out["repair_proposals"] = [{"proposal_id": str(p.get("proposal_id") or ""), "count": int(p.get("count") or 0)} for p in props]
        except Exception:
            out["repair_proposals"] = []
    # W2 (2026-09-28): the age of the wait — from the record, never the strip's last touch: the earliest instrument
    # that set the current wait, else the status summary's own time when it carries it; None when unknown
    out["wait_age_days"] = _wait_age_days(root, out["needs_you"], strip, summ, sfile, today) if out["needs_you"] else None
    # W5 (2026-09-28): where he left — the strip's last leave receipt (W0's, written on the switch he made), re-read
    # against the roadmap as it stands now (how many events since); None when he never left this record
    out["resume"] = _resume(strip, rm if isinstance(rm, dict) else None, rel)
    # W1 of the steward revision (2026-09-28): EVERY effort's wait, not only the effort touched last — Grok's live
    # replay (2026-09-27) showed alternating touches hiding the second MBA effort's review from the home. The card
    # keeps the shown effort for its line; the other efforts' waits ride beside it, each opening its own record.
    out["efforts"], out["efforts_gap"] = _effort_waits(folder, rel, today)
    out["other_waits"] = [x for x in out["efforts"] if x["needs_you"] and x["rel"] != rel]
    if not out["needs_you"] and out["other_waits"]:
        first = out["other_waits"][0]
        out["needs_you"] = "%s: %s" % (first["name"], first["needs_you"])
        out["needs_you_effort"] = first["rel"]
        out["wait_age_days"] = first.get("age_days")     # the promoted wait's own age (Grok W2)
    return out


def _ago(epoch, now=None):
    """An instant as words: "just now", "12 min ago", "3 h ago", "2 days ago"; "" when unknown."""
    if epoch is None:
        return ""
    s = max(0, int((now if now is not None else time.time()) - epoch))
    if s < 90:
        return "just now"
    if s < 3600:
        return "%d min ago" % (s // 60)
    if s < 86400:
        return "%d h ago" % (s // 3600)
    d = s // 86400
    return "1 day ago" if d == 1 else "%d days ago" % d


def _resume(strip, rm, rel=""):
    """The last `leave` receipt on the strip as the Resume act's fact: the step he was on (named from the roadmap
    when it can be), when, the effort, and how many roadmap events landed since — so Resume re-reads the state
    rather than replaying the receipt. None without a receipt."""
    if not isinstance(strip, dict):
        return None
    leaves = [r for r in (strip.get("receipts") or []) if isinstance(r, dict) and r.get("kind") == "leave"]
    if not leaves:
        return None
    last = leaves[-1]
    steps = {str(st.get("id")): st for st in ((rm or {}).get("roadmap_projection") or []) if isinstance(st, dict)}
    sid = str(last.get("current_step_id") or last.get("last_event_step_id") or "")
    st = steps.get(sid) or {}
    events = [e for e in ((rm or {}).get("roadmap_events") or []) if isinstance(e, dict)]
    last_seq = max([int(e.get("seq") or 0) for e in events] or [0])
    seen = last.get("last_event_seq")
    since = max(0, last_seq - int(seen)) if isinstance(seen, int) else None
    at = _instant(last.get("at"))
    return {"at": str(last.get("at") or ""), "epoch": at, "ago": _ago(at), "step_id": sid,
            "step": str(st.get("name") or sid or last.get("active_effort") or "where you were"),
            "step_status": str(st.get("status") or ""), "effort": rel, "events_since": since,
            "presentation_id": last.get("presentation_id"), "wait_ref": last.get("wait_ref")}


def _instant(v):
    """An event's instant as epoch seconds: an ISO datetime, or a date (midnight, local); None when neither."""
    s = str(v or "").strip()
    if not s:
        return None
    try:
        from datetime import datetime as _dt, timezone as _tz
        if len(s) <= 10:
            return _dt.combine(date.fromisoformat(s[:10]), _dt.min.time()).timestamp()
        s2 = s.replace("Z", "+00:00")
        d = _dt.fromisoformat(s2)
        if d.tzinfo is None:
            d = d.replace(tzinfo=_tz.utc)
        return d.timestamp()
    except Exception:
        return None


def _wait_age_days(root, wait, strip, summ, sfile, today):
    """Days the current wait has stood, from the record: the ``as_of`` of the earliest instrument in the latest run
    that carries this wait text; else the status summary's ``waiting_since`` (the composer's stamp from the managed
    request's own time) when its plan carries the same wait; else None — no number without a reader, and never the
    strip's or the summary's own last touch."""
    try:
        w = " ".join(str(wait or "").split()).lower()
        since = None
        ins = strip.get("instruments") if isinstance(strip, dict) else None
        if isinstance(ins, list):
            for i in reversed(ins):
                if not isinstance(i, dict) or "human_wait" not in i:
                    continue
                if " ".join(str(i.get("human_wait") or "").split()).lower() == w:
                    since = _iso(i.get("as_of")) or since
                    continue
                break
        if since is None and isinstance(summ, dict):
            # the status summary is rewritten every ten minutes, so its own `at` is the strip's last touch in
            # another form — only a `waiting_since` the composer stamps from the decision's time counts
            plan = summ.get("plan") if isinstance(summ.get("plan"), dict) else {}
            if " ".join(str(plan.get("waiting_on_you") or "").split()).lower() == w and plan.get("waiting_since"):
                since = _iso(str(plan.get("waiting_since") or "")[:10])
        if since is None:
            return None
        return max(0, (today - since).days)
    except Exception:
        return None


def _effort_waits(folder, shown_rel="", today=None):
    """Every steward effort of a project (the cockpit's own discovery: the root with a Face, plus one level of
    subfolders with their own) with its wait — the strip's human wait, else the last status's "waiting on you" —
    and the wait's age from that effort's record, as ``([{rel, name, needs_you, age_days, shown}], gap)`` in the
    cockpit's order. Read-only; never raises. A failure is never a silent empty list (Grok W1: that would recreate
    the hidden second effort): the gap names it and the card shows it."""
    today = today or date.today()
    try:
        from steward_cockpit.steward_campaign import discover_efforts
        efforts = discover_efforts(str(folder)) or []
    except Exception as e:
        return [], "the project's efforts could not be listed: %s" % (type(e).__name__)
    out, gap = [], ""
    for e in efforts:
        try:
            rel = str((e or {}).get("rel") or "")
            root = Path(folder) / rel if rel else Path(folder)
            wait = ""
            strip = _read_json(root / "strip.json")
            if isinstance(strip, dict):
                wait = _real_wait(strip.get("human_wait"))
            sfile = root / ".ecgberht" / "status-summary.json"
            summ = _read_json(sfile)
            if not wait:
                plan = summ.get("plan") if isinstance(summ, dict) and isinstance(summ.get("plan"), dict) else {}
                wait = _real_wait(plan.get("waiting_on_you"))
            out.append({"rel": rel, "name": str((e or {}).get("name") or rel or "root"), "needs_you": wait,
                        "age_days": _wait_age_days(root, wait, strip, summ, sfile, today) if wait else None,
                        "shown": rel == str(shown_rel or "")})
        except Exception as ex:
            gap = "%s could not be read: %s" % (str((e or {}).get("name") or "an effort"), type(ex).__name__)
    return out, gap


def _real_wait(text):
    """The cockpit's own rule for a wait (steward_campaign._real_wait, called directly — no second list, Grok R7): a
    strip that says "none" / "nothing" / "-" / "none — explanation" is not waiting on anyone, so its project has no
    business on Needs you (the live board showed "Needs you: none" on four cards, 2026-09-27)."""
    return str(_cockpit_wait(text) or "").strip()


def current_effort(folder):
    """The effort the card shows: of the efforts the cockpit discovers (the root when it has a Face, plus one level
    of subfolders with their own ECGBERHT.md), the one the cockpit itself lists first — by its own clock,
    ``steward_campaign.last_touched`` (the conversation log, the strip, the roadmap), the same sort the cockpit's
    efforts row uses; "" for the root or when no effort exists. Read-only; never raises."""
    try:
        from steward_cockpit.steward_campaign import discover_efforts, last_touched
        efforts = discover_efforts(str(folder)) or []
    except Exception:
        return ""
    best, best_t = "", -1.0
    for e in efforts:
        rel = str((e or {}).get("rel") or "")
        try:
            t = float(last_touched(str(Path(folder) / rel if rel else Path(folder))) or 0.0)
        except Exception:
            t = 0.0
        if t > best_t:
            best, best_t = rel, t
    return best


def all_project_facts(entries, today=None):
    """The facts for every entry, in the entries' order; a bad entry is skipped, never fatal."""
    out = []
    for e in entries or ():
        try:
            out.append(project_facts(e, today))
        except Exception:
            continue
    return out


def week_in_words(today=None):
    """The week header in words: 'this week Sep 22–28' (Monday to Sunday of today's week)."""
    today = today or date.today()
    mon = today - timedelta(days=today.weekday())
    sun = mon + timedelta(days=6)

    def md(d):
        return "%s %d" % (d.strftime("%b"), d.day)
    if mon.month == sun.month:
        return "this week %s–%d" % (md(mon), sun.day)
    return "this week %s – %s" % (md(mon), md(sun))


def due_label(iso, today=None):
    """'overdue since Sep 20' · 'due today' · 'due Oct 8' — the same date, said against today."""
    d = _iso(iso)
    if not d:
        return ""
    today = today or date.today()
    if d < today:
        return "overdue since " + short_date(iso)
    if d == today:
        return "due today"
    return "due " + short_date(iso)


def short_date(iso):
    """'2026-10-08' → 'Oct 8'; anything else comes back as it is."""
    d = _iso(iso)
    return ("%s %d" % (d.strftime("%b"), d.day)) if d else str(iso or "")
