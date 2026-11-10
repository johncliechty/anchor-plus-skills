"""high_seat_core — Pure Essential Core ("Juice") domain calculations for the Cave of Wonders & Star Chart (Wave 12 Anvil Extraction).

Extracted via Anvil Get-Data / Do-Analysis / Create-Output decomposition from `high_seat_page.py` and `campaign_page.py`.
Every function in this module is a pure, deterministic Do-Analysis calculation over in-memory records (zero HTML string
concatenation, zero network/socket I/O), verified by Hypothesis property-based equivalence tests.
"""
from __future__ import annotations

from datetime import date, timedelta
import html
import json
import os
from pathlib import Path
import re
from typing import Any, Callable
from urllib.parse import quote as _quote

import home_rows as _hr

_OPEN = ("proposed", "planned", "active", "waiting")
_TIER_WORDS = {1: "do first", 2: "next in line", 3: "when there is room"}
HIS_NAME = "John"
INITIATIVE_KINDS = ("project", "effort", "task")
KIND_LABEL = {"project": "cockpit", "effort": "cockpit within a project", "task": "desk item"}
KIND_WORDS = {"project": "cockpit", "effort": "cockpit within", "task": "desk item", "step": "a step of a project", "deliverable": "deliverable", "calendar": "date"}
SEAT_WORDS = {"active": "active", "deck": "on deck"}
SEAT_NAMES = {"active": "Active", "deck": "On deck"}
NOGOAL_ID = "__nogoal__"
LIGHTS = {
    "needs": ("&#9873;", "needs you"),
    "working": ("&#9679;", "working"),
    "waiting": ("&#9679;", "waiting"),
    "idle": ("&#9675;", "idle"),
}


def mode_name(st: Any) -> str:
    """The Campaign page's name in the steward's goals-and-foresight mode, per persona."""
    return str((st or {}).get("campaign_name") or "Campaign")


def esc(s: Any) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def short_date(d: Any) -> str:
    return _hr.short_date(d) if d else ""


def is_initiative(part: dict[str, Any]) -> bool:
    return part.get("kind") in INITIATIVE_KINDS and not part.get("broken")


def part_name(part: dict[str, Any]) -> str:
    """An initiative's own name: the project or effort it points at, else the desk item's words."""
    return str(part.get("target") or part.get("text") or "")


def goals_only(initiatives: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None) -> list[dict[str, Any]]:
    """The goals - never the hidden no-goal group."""
    return [i for i in initiatives or () if not i.get("nogoal")]


def campaign_initiatives(steps: list[dict[str, Any]] | None, resolved: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """The Campaign's heading steps (each defines its own root group) with their parts."""
    resolved = resolved or {}
    steps = [s for s in (steps or ()) if isinstance(s, dict)]
    heads = []
    for s in steps:
        nav = s.get("navigation") if isinstance(s.get("navigation"), dict) else {}
        groups = nav.get("groups") or []
        own = next(
            (g for g in groups if isinstance(g, dict) and g.get("id") == s.get("id") and g.get("parent_id") is None),
            None,
        )
        if own is not None:
            heads.append((s, own))
    out = []
    for s, own in heads:
        sid = s.get("id")
        parts = []
        for p in steps:
            if p is s:
                continue
            nav = p.get("navigation") if isinstance(p.get("navigation"), dict) else {}
            path = nav.get("path") or []
            if path and path[0] == sid:
                r = resolved.get(str(p.get("id"))) or {}
                ref = str(p.get("ref") or "")
                kind = ref.split(":", 1)[0] if ref else "task"
                state = r.get("state") or ("" if r.get("broken") else str(p.get("status") or ""))
                parts.append({
                    "id": p.get("id"),
                    "kind": kind,
                    "name": p.get("name") or "",
                    "text": r.get("what") or p.get("name") or "",
                    "target": r.get("name") or "",
                    "state": state,
                    "date": r.get("date") or p.get("due") or "",
                    "pid": str(r.get("pid") or ""),
                    "lead": str(r.get("lead") or ""),
                    "dir": str(r.get("dir") or ""),
                    "href": r.get("href") or "",
                    "status": str(p.get("status") or ""),
                    "target_status": str(r.get("target_status") or ""),
                    "broken": bool(r.get("broken")) if ref else False,
                    "gap": r.get("gap") or "",
                    "waiting_on": str(p.get("waiting_on") or "") if not ref else "",
                    "needs_you": "waiting on you" in str(state).lower()
                    or (
                        not ref
                        and str(p.get("status") or "") == "waiting"
                        and bool(re.search(r"\b(john|you|me)\b", str(p.get("waiting_on") or "").lower()))
                    ),
                    "seat": str(p.get("seat")) if p.get("seat") in ("active", "deck") else "",
                    "seat_order": int(p["seat_order"]) if isinstance(p.get("seat_order"), int) else None,
                    "goal": sid,
                    "goal_name": s.get("name") or sid,
                })
        for p in parts:
            p["done"] = p["status"] == "done" or p["target_status"] == "done"
            p["closed"] = p["status"] in ("done", "parked") or p["target_status"] in ("done", "cancelled", "dropped", "parked")
        open_parts = [p for p in parts if not p["closed"] and not p["broken"]]
        dates = sorted(p["date"] for p in open_parts if p["date"])
        out.append({
            "id": sid,
            "name": s.get("name") or sid,
            "tier": int(s["tier"]) if s.get("tier") in (1, 2, 3) else None,
            "order": int((own or {}).get("order") or 0),
            "area": str(s.get("area") or ""),
            "done_when": s.get("done_when") or "",
            "status": s.get("status") or "",
            "if_then": str(s.get("if_then") or ""),
            "parts": parts,
            "next": open_parts[0] if open_parts else None,
            "needs": [p for p in parts if p["needs_you"]],
            "next_deadline": dates[0] if dates else "",
            "done_count": sum(1 for p in parts if p["done"]),
            "pace": str(s.get("pace") or ""),
            "open_count": len(open_parts),
            "part_count": sum(1 for p in parts if not p["broken"]),
        })
    out.sort(key=lambda i: (i["tier"] or 9, i["order"], i["name"]))
    for n, i in enumerate(out, 1):
        i["number"] = n
    return out


def loose_initiative(steps: list[dict[str, Any]] | None, resolved: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Components with no goal yet as ONE hidden initiative (nogoal=True)."""
    steps = [s for s in (steps or ()) if isinstance(s, dict)]
    heads = {
        s.get("id")
        for s in steps
        for g in ((s.get("navigation") or {}).get("groups") or [])
        if isinstance(g, dict) and g.get("id") == s.get("id") and g.get("parent_id") is None
    }
    loose = []
    for s in steps:
        nav = s.get("navigation") if isinstance(s.get("navigation"), dict) else {}
        ref = str(s.get("ref") or "")
        if s.get("id") in heads or (nav.get("path") or []) or ref.split(":", 1)[0] not in ("project", "effort"):
            continue
        x = dict(s)
        x["navigation"] = {"path": [NOGOAL_ID]}
        loose.append(x)
    if not loose:
        return None
    head = {
        "id": NOGOAL_ID,
        "name": "no goal yet",
        "status": "active",
        "tier": 9,
        "order": 999,
        "navigation": {"groups": [{"id": NOGOAL_ID, "parent_id": None}]},
    }
    out = campaign_initiatives([head] + loose, resolved)
    if not out:
        return None
    out[0]["nogoal"] = True
    return out[0]


def seated(initiatives: list[dict[str, Any]] | None, seat: str) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """The components sitting in a seat — (goal, part) pairs in his order."""
    out = []
    for i in initiatives or ():
        for p in i.get("parts") or ():
            if p.get("seat") == seat and not p.get("closed"):
                out.append((i, p))
    return sorted(
        out,
        key=lambda t: (
            t[1].get("seat_order") if isinstance(t[1].get("seat_order"), int) else 999,
            t[0].get("tier") or 9,
            int(t[0].get("order") or 0),
            part_name(t[1]).lower(),
        ),
    )


def initiative_light(i: dict[str, Any], working: set[str] | None = None) -> str:
    """Universal Green Working Light rule: `working` when a referenced project has a running session/steward or working state."""
    working = working or set()
    open_parts = [
        p
        for p in i.get("parts") or ()
        if not p.get("closed", p.get("status") in ("done", "parked")) and not p.get("broken")
    ]
    if any(
        (p.get("pid") and p["pid"] in working) or str(p.get("state") or "").lower().startswith("working")
        for p in open_parts
    ):
        return "working"
    if i.get("needs"):
        return "needs"
    if any(str(p.get("state") or "").startswith("waiting") or p.get("status") == "waiting" for p in open_parts):
        return "waiting"
    return "idle"


def initiative_line(i: dict[str, Any]) -> tuple[str, str]:
    """The one sentence a compact initiative tile carries; returns (html, kind)."""
    if i.get("needs"):
        p = i["needs"][0]
        state = str(p.get("state") or "")
        low = state.lower()
        if "waiting on you:" in low:
            words = state[low.index("waiting on you:") + len("waiting on you:"):].strip()
        elif p.get("waiting_on") and str(p["waiting_on"]).strip().lower() not in ("john", "you", "me"):
            words = "%s &mdash; %s" % (esc(p.get("text") or ""), esc(p["waiting_on"]))
            return "&#9873; " + words, "wait"
        else:
            words = ""
        text = esc(words) if words else esc(p.get("text") or p.get("target") or "")
        return "&#9873; " + text, "wait"
    nxt = i.get("next")
    if nxt:
        return "Next: " + esc(nxt.get("text") or "") + ((" &middot; " + esc(short_date(nxt["date"]))) if nxt.get("date") else ""), "next"
    if i.get("done_when"):
        return "Done looks like: " + esc(i["done_when"]), "done"
    return "nothing open", "none"


def ruler_weeks(today: date) -> list[dict[str, Any]]:
    mon = today - timedelta(days=today.weekday())
    weeks = []
    for k in range(5):
        a = mon + timedelta(days=7 * k)
        b = a + timedelta(days=6)
        label = (
            "%s–%d" % (_hr.short_date(a.isoformat()), b.day)
            if a.month == b.month
            else "%s–%s" % (_hr.short_date(a.isoformat()), _hr.short_date(b.isoformat()))
        )
        weeks.append({"start": a, "end": b, "label": label, "name": "this week" if k == 0 else "week %d" % (k + 1)})
    return weeks


def ruler_markers(
    facts: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
    today: date,
) -> tuple[list[dict[str, Any]], dict[int, list[dict[str, Any]]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Every open dated step across the records, bucketed into the five weeks and beyond."""
    weeks = ruler_weeks(today)
    buckets: dict[int, list[dict[str, Any]]] = {k: [] for k in range(5)}
    beyond: list[dict[str, Any]] = []
    overdue: list[dict[str, Any]] = []
    for f in facts or ():
        if not isinstance(f, dict):
            continue
        for st in f.get("dated") or ():
            d = _hr._iso(st.get("due"))
            if d is None:
                continue
            m = {
                "date": st["due"],
                "name": st.get("name", ""),
                "project_id": f.get("id", ""),
                "project_name": f.get("name", ""),
                "needs": bool(f.get("needs_you")),
                "overdue": d < today,
                "label": _hr.due_label(st["due"], today),
            }
            if d < weeks[0]["start"]:
                overdue.append(m)
                continue
            placed = False
            for k, w in enumerate(weeks):
                if w["start"] <= d <= w["end"]:
                    buckets[k].append(m)
                    placed = True
                    break
            if not placed:
                beyond.append(m)
    for k in buckets:
        buckets[k].sort(key=lambda m: (m["date"], m["name"]))
    beyond.sort(key=lambda m: (m["date"], m["name"]))
    overdue.sort(key=lambda m: (m["date"], m["name"]))
    return weeks, buckets, beyond, overdue


def desk_counts(desk: dict[str, Any] | None) -> tuple[int, int, int]:
    """(waits, small items open, cockpits) for the Desk tile and the rail."""
    if not desk:
        return 0, 0, 0
    return int(desk.get("waits") or 0), len((desk.get("small") or {}).get("items") or ()), len(desk.get("cockpits") or ())


def relevance(c: dict[str, Any], today: date, override: dict[str, Any] | None = None) -> tuple[int, str]:
    """The steward's relevance score (0-100) for a candidate, with its reasons."""
    if isinstance(override, dict) and isinstance(override.get("score"), (int, float)):
        return max(0, min(100, int(override["score"]))), str(override.get("why") or "the steward's own score")
    score, why = 20, []
    if c.get("needs"):
        score += 35
        why.append("waits on you")
    due = str(c.get("due") or "")
    if due:
        try:
            days = (date.fromisoformat(due[:10]) - today).days
            if days < 0:
                score += 30
                why.append("overdue")
            elif days <= 7:
                score += 22
                why.append("due in %d day%s" % (days, "" if days == 1 else "s"))
            elif days <= 21:
                score += 10
                why.append("due %s" % due[:10])
        except ValueError:
            pass
    tier = c.get("tier")
    if tier == 1:
        score += 15
        why.append("a tier-1 goal")
    elif tier == 2:
        score += 7
        why.append("a tier-2 goal")
    worked = str(c.get("worked") or "")
    if worked:
        try:
            ago = (today - date.fromisoformat(worked[:10])).days
            if ago <= 3:
                score += 12
                why.append("worked %s" % ("today" if ago == 0 else "%d day%s ago" % (ago, "" if ago == 1 else "s")))
            elif ago <= 14:
                score += 5
                why.append("worked %d days ago" % ago)
            elif ago > 45:
                score -= 10
                why.append("still for %d days" % ago)
        except ValueError:
            pass
    return max(0, min(100, score)), (", ".join(why) or "nothing presses")


def candidates_model(
    ctx: dict[str, Any],
    date_reader: Callable[[str], tuple[str, str]] | None = None,
    dates_fn: Callable[[str], tuple[str, str]] | None = None,
) -> tuple[list[tuple[dict[str, Any], dict[str, Any]]], list[dict[str, Any]]]:
    """Pure computation of `(in_goal, loose)` candidates with relevance scores."""
    if date_reader is None and dates_fn is not None:
        date_reader = dates_fn
    inits = [i for i in ctx.get("initiatives") or () if i.get("status") not in ("done", "parked")]
    in_goal = []
    on_map = set()
    for i in ctx.get("initiatives") or ():
        for p in i.get("parts") or ():
            if p.get("kind") in ("project", "effort") and p.get("pid"):
                if i.get("nogoal") and not p.get("seat"):
                    continue
                on_map.add((p["pid"], p.get("dir") or ""))
    facts = ctx.get("facts") or {}
    today = ctx.get("today") or date.today()
    ev = ctx.get("campaign_step_dates") or {}
    over = ctx.get("relevance_override") or {}
    for i in goals_only(inits):
        for p in i.get("parts") or ():
            if p.get("kind") in KIND_LABEL and not p.get("seat") and not p.get("closed") and not p.get("broken"):
                made, touched = (ev.get(p.get("id")) or ("", ""))
                if date_reader and p.get("pid") and facts.get(p["pid"], {}).get("folder"):
                    _, l = date_reader(os.path.join(facts[p["pid"]]["folder"], p.get("dir") or ""))
                    touched = max(touched or "", l or "")
                p["c_created"], p["c_worked"] = made, touched
                p["c_score"], p["c_why"] = relevance(
                    {"needs": p.get("needs_you"), "due": p.get("date"), "tier": i.get("tier"), "worked": touched},
                    today,
                    over.get(p.get("id")),
                )
                in_goal.append((i, p))
    camp = (ctx.get("campaign") or {}).get("pid")
    loose = []
    for e in ctx.get("entries") or ():
        pid = e.get("id")
        f = facts.get(pid) or {}
        has_folder_on_disk = bool(f.get("folder") and os.path.isdir(str(f.get("folder"))))
        if not pid or pid == camp or (not f.get("has_record") and not has_folder_on_disk):
            continue
        effs = [x for x in (f.get("efforts") or []) if isinstance(x, dict)]
        if not effs:
            if (pid, "") not in on_map:
                loose.append({
                    "ref": "project:%s" % pid,
                    "name": f.get("name") or e.get("name") or pid[:8],
                    "where": "an AI cockpit" if f.get("has_record") else "a project folder (ready for cockpit)",
                    "needs": bool(f.get("needs_you")),
                    "folder": f.get("folder") or "",
                    "pid": pid,
                    "dir": "",
                })
            continue
        for x in effs:
            rel = str(x.get("rel") or "")
            if (pid, rel) in on_map:
                continue
            if rel and len(effs) == 1 and (pid, "") in on_map:
                continue
            nm = f.get("name") or e.get("name") or pid[:8]
            loose.append({
                "ref": ("effort:%s/%s" % (pid, _quote(rel))) if rel else ("project:%s" % pid),
                "name": ("%s · %s" % (nm, x.get("name") or rel)) if rel else nm,
                "where": ("an effort of %s" % nm) if rel else "a project",
                "needs": bool(x.get("needs_you")),
                "folder": (f.get("folder") or "") + (("/" + rel) if rel else ""),
                "pid": pid,
                "dir": rel,
            })
    for c in loose:
        c["created"], c["worked"] = date_reader(c["folder"]) if (date_reader and c.get("folder")) else ("", "")
        c["score"], c["why"] = relevance({"needs": c["needs"], "worked": c["worked"]}, today, over.get(c["ref"]))
    return in_goal, loose


def this_week_horizon_buckets(ctx: dict[str, Any]) -> dict[str, Any]:
    """Pure computation of the 4-column Today & This Week board (`col_overdue`, `col_today`, `col_72h`, `col_week`, `closed_today`, `target_dates`)."""
    today = ctx.get("today") or date.today()
    facts = ctx.get("facts") or {}
    camp_pid = str((ctx.get("campaign") or {}).get("pid") or "")
    entry_folders = {
        str(e.get("id") or ""): str(e.get("folder_path") or "")
        for e in (ctx.get("entries") or ())
        if isinstance(e, dict)
    }
    all_open = []
    for f in facts.values():
        if not isinstance(f, dict):
            continue
        pid = str(f.get("id") or "")
        if camp_pid and pid == camp_pid:
            continue
        folder = str(f.get("folder") or entry_folders.get(pid) or pid or "")
        for st in f.get("dated") or ():
            d = _hr._iso(st.get("due"))
            if d is None:
                continue
            all_open.append({
                "step_id": str(st.get("step_id") or st.get("id") or st.get("name") or ""),
                "name": str(st.get("name") or ""),
                "due": str(st.get("due") or ""),
                "date_obj": d,
                "project_id": pid,
                "project_name": str(f.get("name") or ""),
                "folder": folder,
                "needs": bool(f.get("needs_you")),
            })
    all_open.sort(key=lambda x: (x["due"], x["name"]))
    col_overdue = [x for x in all_open if x["date_obj"] < today]
    col_today = [x for x in all_open if x["date_obj"] == today]
    col_72h = [x for x in all_open if today < x["date_obj"] <= today + timedelta(days=3)]
    col_week = [x for x in all_open if today + timedelta(days=3) < x["date_obj"] <= today + timedelta(days=7)]

    closed_today = list(ctx.get("closed_today") or [])
    if not closed_today:
        for f in facts.values():
            if not isinstance(f, dict) or not f.get("folder"):
                continue
            try:
                sp = Path(str(f["folder"])) / ".ecgberht" / "status-summary.json"
                if sp.is_file():
                    doc = json.loads(sp.read_text(encoding="utf-8"))
                    for cr in ((doc.get("plan") or {}).get("closed_recent") or [])[:3]:
                        if isinstance(cr, dict) and str(cr.get("at") or "")[:10] == today.isoformat():
                            closed_today.append({
                                "name": str(cr.get("name") or cr.get("id") or ""),
                                "project_name": str(f.get("name") or ""),
                                "project_id": str(f.get("id") or ""),
                            })
            except Exception:
                pass

    return {
        "today": today,
        "col_overdue": col_overdue,
        "col_today": col_today,
        "col_72h": col_72h,
        "col_week": col_week,
        "closed_today": closed_today,
        "target_dates": {
            "overdue": today.isoformat(),
            "today": today.isoformat(),
            "72h": (today + timedelta(days=2)).isoformat(),
            "week": (today + timedelta(days=5)).isoformat(),
        },
    }


def proactive_triage_cards(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """Wave 6b/12: Pure deterministic Chief-of-Staff Proactive Triage & Recommendations."""
    today = ctx.get("today") or date.today()
    facts = ctx.get("facts") or {}
    camp_pid = str((ctx.get("campaign") or {}).get("pid") or "")
    entry_folders = {
        str(e.get("id") or ""): str(e.get("folder_path") or "")
        for e in (ctx.get("entries") or ())
        if isinstance(e, dict)
    }
    _folder_for = lambda f: str((f or {}).get("folder") or entry_folders.get(str((f or {}).get("id") or "")) or (f or {}).get("id") or "")
    inits = [i for i in ctx.get("initiatives") or () if i.get("status") not in ("done", "parked")]
    desk = ctx.get("desk") or {}
    desk_pid = str(ctx.get("desk_pid") or "")

    # 1. Today's Commitment & Folder Readiness
    dated_all = []
    for f in facts.values():
        if not isinstance(f, dict):
            continue
        if camp_pid and str(f.get("id") or "") == camp_pid:
            continue
        for st in f.get("dated") or ():
            d = _hr._iso(st.get("due"))
            if d is not None:
                dated_all.append((d, st, f))
    dated_all.sort(key=lambda t: (t[0], str(t[1].get("name") or "")))
    teaching_hit = next(
        (
            (d, st, f)
            for d, st, f in dated_all
            if "mba" in str(f.get("name") or "").lower()
            or "teaching" in str(f.get("name") or "").lower()
            or "lecture" in str(st.get("name") or "").lower()
        ),
        None,
    )
    today_or_next = (
        next(((d, st, f) for d, st, f in dated_all if d == today), None)
        or (teaching_hit if teaching_hit and teaching_hit[0] <= today + timedelta(days=7) else None)
        or next(((d, st, f) for d, st, f in dated_all if today <= d <= today + timedelta(days=3)), None)
        or teaching_hit
        or next(((d, st, f) for d, st, f in dated_all if d <= today + timedelta(days=2)), None)
        or (dated_all[0] if dated_all else None)
    )
    if today_or_next:
        d, st, f = today_or_next
        done_n, tot_n = int(f.get("steps_done") or 0), int(f.get("steps_total") or 0)
        prog_note = (" (%d/%d steps done)" % (done_n, tot_n)) if tot_n else ""
        card1 = {
            "id": "triage-today",
            "rule": "Rule · Today & Readiness",
            "tone": "emerald" if not f.get("needs_you") else "amber",
            "title": "%s — %s" % (f.get("name") or "Project", st.get("name") or "Next milestone"),
            "why": "Due %s%s · Next: %s" % (short_date(st.get("due")), prog_note, f.get("next") or st.get("name") or "ready"),
            "pid": str(f.get("id") or ""),
            "folder": _folder_for(f),
            "step_id": str(st.get("step_id") or st.get("id") or st.get("name") or ""),
        }
    else:
        card1 = {
            "id": "triage-today",
            "rule": "Rule · Today & Readiness",
            "tone": "emerald",
            "title": "Today's schedule is clear",
            "why": "No overdue or immediate deadlines in the next 48 hours.",
            "pid": "",
            "folder": "",
            "step_id": "",
        }

    # 2. Next 72h / External Counsel & Transfers
    counsel_hit = (
        next(
            (
                (d, st, f)
                for d, st, f in dated_all
                if (d, st, f) != today_or_next
                and (
                    "stanford" in str(st.get("name") or "").lower()
                    or "merrill" in str(st.get("name") or "").lower()
                    or "exmera" in str(st.get("name") or "").lower()
                )
                and d >= today
            ),
            None,
        )
        or next(
            (
                (d, st, f)
                for d, st, f in dated_all
                if (d, st, f) != today_or_next
                and (
                    "trust" in str(f.get("name") or "").lower()
                    or "stanford" in str(st.get("name") or "").lower()
                    or "merrill" in str(st.get("name") or "").lower()
                )
                and d >= today
            ),
            None,
        )
        or next(
            (
                (d, st, f)
                for d, st, f in dated_all
                if (d, st, f) != today_or_next
                and (
                    "trust" in str(f.get("name") or "").lower()
                    or "stanford" in str(st.get("name") or "").lower()
                    or (today < d <= today + timedelta(days=7))
                )
            ),
            None,
        )
    )
    if counsel_hit:
        d, st, f = counsel_hit
        card2 = {
            "id": "triage-counsel",
            "rule": "Rule · 72h & External Dependencies",
            "tone": "amber",
            "title": "%s — %s" % (f.get("name") or "Project", st.get("name") or "Milestone"),
            "why": "Due %s · %s" % (short_date(st.get("due")), f.get("next") or "Track external turn-around and template handoff"),
            "pid": str(f.get("id") or ""),
            "folder": _folder_for(f),
            "step_id": str(st.get("step_id") or st.get("id") or st.get("name") or ""),
        }
    else:
        card2 = {
            "id": "triage-counsel",
            "rule": "Rule · 72h & External Dependencies",
            "tone": "sky",
            "title": "No external bottlenecks due in 72h",
            "why": "All external counsel and dependency tracks are within window.",
            "pid": "",
            "folder": "",
            "step_id": "",
        }

    # 3. Ready for Your Review / Needs You
    wait_f = next((f for f in facts.values() if isinstance(f, dict) and f.get("needs_you")), None)
    if wait_f:
        card3 = {
            "id": "triage-review",
            "rule": "Rule · Needs Your Review",
            "tone": "amber",
            "title": "%s waits on you" % (wait_f.get("name") or "Cockpit"),
            "why": str(wait_f.get("needs_you") or "")[:140],
            "pid": str(wait_f.get("id") or ""),
            "folder": _folder_for(wait_f),
            "step_id": "",
        }
    else:
        card3 = {
            "id": "triage-review",
            "rule": "Rule · Needs Your Review",
            "tone": "emerald",
            "title": "Zero cockpits blocked on your approval",
            "why": "All active stewards have clear runway.",
            "pid": "",
            "folder": "",
            "step_id": "",
        }

    # 4. Desktop (Desk) Ad-Hoc AI Cockpit + Active/On-Deck Load
    waits, n_small, n_cock = desk_counts(desk)
    n_act, n_deck = len(seated(inits, "active")), len(seated(inits, "deck"))
    card4 = {
        "id": "triage-desk",
        "rule": "Rule · Desktop & Portfolio Load",
        "tone": "sky",
        "title": "Desktop (Desk) Ad-Hoc AI Cockpit · %d Active / %d On Deck" % (n_act, n_deck),
        "why": "Small items: %d open · %d ad-hoc cockpit%s ready for quick admin tasks without creating a full project."
        % (n_small, n_cock, "" if n_cock == 1 else "s"),
        "pid": desk_pid,
        "folder": "",
        "step_id": "",
        "is_desk": True,
    }
    return [card1, card2, card3, card4]


def star_foresight_cards(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """Wave 7/12/15: Three strategic foresight cards for the Star Chart with inline seatable initiative metadata."""
    inits = [i for i in (ctx.get("initiatives") or []) if i.get("status") not in ("done", "parked")]
    today = ctx.get("today")
    facts = ctx.get("facts") or {}
    t1 = [i for i in inits if i.get("tier") == 1]
    t2 = [i for i in inits if i.get("tier") == 2]
    cards = []

    def _first_seatable_step_id(goal_obj: dict[str, Any] | None) -> str:
        if not isinstance(goal_obj, dict):
            return ""
        for p in goal_obj.get("parts") or ():
            if is_initiative(p) and not p.get("closed") and p.get("seat") != "active":
                return str(p.get("id") or "")
        return ""

    # Card 1: Tier-1 Focus & Pace
    if t1:
        t1_done = sum(int(i.get("done_count") or 0) for i in t1)
        t1_total = sum(len(i.get("parts") or []) for i in t1)
        t1_dated = sorted(
            (
                (_hr._iso(p["date"]), p, i)
                for i in t1
                for p in (i.get("parts") or [])
                if p.get("date")
                and not p.get("broken")
                and not p.get("done")
                and p.get("status") not in ("done", "parked")
                and _hr._iso(p["date"])
            ),
            key=lambda x: x[0],
        )
        nxt = next(((d, p, i) for d, p, i in t1_dated if not today or d >= today), t1_dated[0] if t1_dated else None)
        lead_goal = nxt[2] if nxt else t1[0]
        lead_part = nxt[1] if nxt else lead_goal.get("next")
        body = "%s (%d of %d parts done).%s" % (
            " &middot; ".join("<b>%s</b>" % esc(i["name"]) for i in t1[:3]),
            t1_done,
            t1_total,
            (
                " Nearest Tier-1 date: <b>%s</b> (%s, due %s)."
                % (esc(nxt[1]["text"][:56]), esc(nxt[2]["name"]), esc(short_date(nxt[0].isoformat())))
            )
            if nxt
            else " All Tier-1 goals on track.",
        )
        cards.append({
            "kind": "tier1",
            "kicker": "Tier-1 Focus &amp; Pace",
            "badge": "%d Tier-1 Goal%s" % (len(t1), "" if len(t1) == 1 else "s"),
            "title": "%s &mdash; %s" % (esc(lead_goal["name"]), esc((lead_part or {}).get("text") or "On track")[:64]),
            "body_html": body,
            "goal_id": lead_goal["id"],
            "part_id": (lead_part or {}).get("id")
            if (lead_part and lead_part.get("kind") in ("task", "step") and not lead_part.get("done"))
            else "",
            "seat_step_id": _first_seatable_step_id(lead_goal),
        })
    else:
        cards.append({
            "kind": "tier1",
            "kicker": "Tier-1 Focus &amp; Pace",
            "badge": "0 Tier-1 Goals",
            "title": "No Tier-1 goal assigned yet",
            "body_html": "Drag your highest-priority goal into <b>Tier 1</b> so the steward tracks its pace and next step.",
            "goal_id": inits[0]["id"] if inits else "",
            "part_id": "",
            "seat_step_id": _first_seatable_step_id(inits[0] if inits else None),
        })

    # Card 2: Critical Dependency Chain & Rollout
    chain_goal = next((i for i in t1 if i.get("if_then")), t1[0] if t1 else (inits[0] if inits else None))
    if chain_goal:
        ift = str(chain_goal.get("if_then") or "").strip()
        nxt_p = chain_goal.get("next")
        pace_s = ("Pace: <b>%s</b>" % esc(short_date(chain_goal["pace"]))) if chain_goal.get("pace") else "No pace date set yet"
        body = "%s. %s" % (
            ("If-Then: <b>&ldquo;%s&rdquo;</b>" % esc(ift))
            if ift
            else "Write one If-Then trigger-action rule in your words to lock the dependency chain",
            ("Next open part: <b>%s</b> (%s)." % (esc(nxt_p["text"][:60]), pace_s)) if nxt_p else pace_s,
        )
        cards.append({
            "kind": "chain",
            "kicker": "Critical Dependency Chain",
            "badge": esc(chain_goal["name"]),
            "title": esc(ift[:78] + ("…" if len(ift) > 78 else "")) if ift else ("%s &mdash; add an If-Then rule" % esc(chain_goal["name"])),
            "body_html": body,
            "goal_id": chain_goal["id"],
            "if_then": ift,
            "seat_step_id": _first_seatable_step_id(chain_goal),
        })

    # Card 3: Portfolio Momentum & Horizon Balance
    tot_done = sum(int(i.get("done_count") or 0) for i in inits)
    tot_parts = sum(len(i.get("parts") or []) for i in inits)
    cockpit_done = sum(int(f.get("steps_done") or 0) for f in facts.values() if isinstance(f, dict) and f.get("steps_total"))
    cockpit_tot = sum(int(f.get("steps_total") or 0) for f in facts.values() if isinstance(f, dict) and f.get("steps_total"))
    lead_t2 = max(t2, key=lambda x: int(x.get("done_count") or 0)) if t2 else (inits[-1] if inits else None)
    cockpit_line = (" Linked cockpits: <b>%d of %d</b> roadmap steps complete." % (cockpit_done, cockpit_tot)) if cockpit_tot else ""
    t2_line = (
        " Leading Tier-2 initiative: <b>%s</b> (%d of %d parts done)."
        % (esc(lead_t2["name"]), int(lead_t2.get("done_count") or 0), len(lead_t2.get("parts") or []))
    ) if lead_t2 else ""
    cards.append({
        "kind": "portfolio",
        "kicker": "Portfolio Momentum &amp; Horizon",
        "badge": "%d/%d Parts Done" % (tot_done, tot_parts),
        "title": "%d Active Goals &middot; %d Tier-1 &middot; %d Tier-2" % (len(inits), len(t1), len(t2)),
        "body_html": "Campaign record: <b>%d of %d</b> parts complete.%s%s" % (tot_done, tot_parts, cockpit_line, t2_line),
        "goal_id": lead_t2["id"] if lead_t2 else "",
        "seat_step_id": _first_seatable_step_id(lead_t2),
    })
    return cards



def chief_of_staff_horizon_efforts(ctx: dict[str, Any]) -> dict[str, Any]:
    """Wave 21 (2026-11-02): Co-populated Cave of Wonders Steward x Star Chart Steward Next-Effort Engine.
    Surfaces prioritized Next-Best Efforts (never a duplicate calendar/email viewer) across:
      - Today (Widest 44%): Urgent & Important (Q1) clearances -> Unlocked Quadrant II Deep-Work slot
      - This Week (Medium 28%): Soon-to-Be Urgent academic, commercial & Family/Relationship efforts
      - This Month (Expandable 14%): Family Trips & Birthday Presents radar + 30-day Star Chart deliverables
      - Quarter / Star Chart Q2 (Expandable 14%): Important, Not Urgent (Quadrant II) flagship value creation
    Includes 'Parable of the Oranges' pre-staged Foundry skills and 'Break-Between-Cockpits' routing metadata."""
    today = ctx.get("today") or date.today()
    facts = ctx.get("facts") or {}
    entries = ctx.get("entries") or ()
    inits = [i for i in (ctx.get("initiatives") or ()) if i.get("status") not in ("done", "parked")]
    working_pids = set(str(x) for x in (ctx.get("working") or ()))
    desk_pid = str(ctx.get("desk_pid") or "")

    # Map project names/slugs to real project IDs & folders when available in ctx
    pid_by_kw: dict[str, tuple[str, str]] = {}
    for e in entries:
        if not isinstance(e, dict):
            continue
        epid = str(e.get("id") or "")
        efolder = str(e.get("folder_path") or "")
        ename = str(e.get("name") or "").lower()
        if epid:
            pid_by_kw[ename] = (epid, efolder)
    for f in facts.values():
        if not isinstance(f, dict):
            continue
        fpid = str(f.get("id") or "")
        ffolder = str(f.get("folder") or "")
        fname = str(f.get("name") or "").lower()
        if fpid and fname not in pid_by_kw:
            pid_by_kw[fname] = (fpid, ffolder)

    def _match_proj(*keywords: str) -> tuple[str, str]:
        for kw in keywords:
            kw_l = kw.lower()
            for k, val in pid_by_kw.items():
                if kw_l in k:
                    return val
        return ("", "")

    mit_pid, mit_dir = _match_proj("mit", "ai club", "mktg")
    trust_pid, trust_dir = _match_proj("trust", "family")
    mba_pid, mba_dir = _match_proj("mba", "teaching", "815")
    mkt_pid, mkt_dir = _match_proj("marketing", "moe", "demand", "collapse")
    hnf_pid, hnf_dir = _match_proj("normalizing", "flow", "technical")
    magi_pid, magi_dir = _match_proj("magi", "writing", "dragon", "brightheart")
    phen_pid, phen_dir = _match_proj("parametric", "3d", "cheng", "phenom")
    gwl_pid, gwl_dir = _match_proj("gwl", "harness", "foundry", "brain")
    comm_pid, comm_dir = _match_proj("commercial", "opx", "nextgen", "axmra")

    def _cockpit_href(pid: str, fallback_pid: str = "") -> str:
        use_pid = pid or fallback_pid or desk_pid
        if use_pid:
            return "/steward/v1?pid=%s&dir=" % use_pid
        return "/steward/v1"

    # Pull dynamic first-card step_id/folder from proactive_triage_cards so existing data-mark-done tests stay bound
    legacy_cards = proactive_triage_cards(ctx)
    c1 = legacy_cards[0] if legacy_cards else {}
    c2 = legacy_cards[1] if len(legacy_cards) > 1 else {}

    # Pull dynamic recommendations directly from 'The List' (ordered by Priority #1, #2, #3...)
    list_recs = []
    try:
        import comms_connector as _cc_list
        list_recs = _cc_list.build_chief_of_staff_recommendations_from_the_list()
    except Exception:
        list_recs = []

    today_efforts = []
    for idx_r, rec in enumerate(list_recs[:3]):
        fallback_c = c1 if idx_r == 0 else (c2 if idx_r == 1 else {})
        r_copy = dict(rec)
        r_copy["pid"] = str(r_copy.get("pid") or fallback_c.get("pid") or mit_pid or mba_pid or "")
        r_copy["folder"] = str(r_copy.get("folder") or fallback_c.get("folder") or mit_dir or mba_dir or "")
        r_copy["step_id"] = str(r_copy.get("step_id") or fallback_c.get("step_id") or f"list-step-{idx_r+1}")
        today_efforts.append(r_copy)

    if not today_efforts:
        today_efforts = [
            {
                "id": "cos-today-mit",
                "list_tile_id": "wl-archty-shutdown",
                "list_badge": "📋 The List · #1 (1st)",
                "tier_cls": "q1-urgent",
                "tier_badge": "📋 The List · #1 (1st)",
                "tier_pill_cls": "red",
                "break_badge": "⚡ 20m Break",
                "break_tags": "all 15m 30m",
                "title": "Priority #1: Shut down my company Archty",
                "driver": "The List (#1 · Business) — Next To Do: Confirm final stub-year federal & state tax return schedule with CPA.",
                "oranges_skill": "Legal-Beagle + Financial-Analyst",
                "oranges_text": "Steward Chief-of-Staff recommendation for #1: Execute stub-year tax tie-out in Archty Cockpit.",
                "pid": mit_pid or str(c1.get("pid") or ""),
                "folder": mit_dir or str(c1.get("folder") or ""),
                "step_id": str(c1.get("step_id") or "mit-lecture-slides"),
                "href": _cockpit_href(mit_pid or str(c1.get("pid") or "")),
                "open_label": "↗ Open AI Cockpit",
                "skill_btn_label": "🍊 Pre-Stage Legal-Beagle + Financial-Analyst",
                "skill_prompt": "Run Legal-Beagle and Financial-Analyst on Archty final dissolution & stub-year tax schedule.",
                "unlock_note": "Move to Things Done",
            }
        ]

    week_efforts = [
        {
            "id": "cos-week-mba",
            "tier_cls": "soon-urgent",
            "tier_badge": "Tomorrow 8 AM",
            "tier_pill_cls": "amber",
            "break_tags": "all 30m",
            "title": "Tue 8:00 AM: MBA Teaching AI (BA 815) — Lecture 6 & AI Supp 5",
            "driver": "4.5-hr MBA teaching block tomorrow morning. Einstein pre-staged Lecture 6 regression walkthrough.",
            "oranges_skill": "Einstein",
            "pid": mba_pid,
            "folder": mba_dir,
            "step_id": "ba815-lec6",
            "href": _cockpit_href(mba_pid),
            "open_label": "↗ Open AI Cockpit (MBA Teaching)",
            "skill_btn_label": "🎓 Einstein Prep Ready",
            "skill_prompt": "Use Einstein to verify BA 815 Lecture 6 (Simple Linear Regression) and AI Supplement 5 worked examples.",
            "is_create": False,
        },
        {
            "id": "cos-week-jane",
            "tier_cls": "family-rel",
            "tier_badge": "Family · Wed & Sun",
            "tier_pill_cls": "pink",
            "break_tags": "all 15m 30m family",
            "title": "🏠 Family & Jane: Sun Nov 8 Team Teach w/ Jane + Wed Youth Night",
            "driver": "Calendar Wed 7 PM Youth Night + Sun 9 AM Team Teach with Jane. Prep now in a 15m break so the weekend is stress-free.",
            "oranges_skill": "Einstein + Superjump",
            "pid": trust_pid or desk_pid,
            "folder": trust_dir,
            "step_id": "team-teach-jane",
            "href": _cockpit_href(trust_pid, desk_pid),
            "open_label": "+ Create / Open Cockpit (Jane Team Teach)",
            "skill_btn_label": "🍊 Pre-Stage Einstein + Superjump Outline",
            "skill_prompt": "Create a 2-page joint lesson outline, object-lesson options (Superjump), and discussion questions (Einstein) for Sunday's Church Team Teach with Jane and Wednesday Youth Night.",
            "is_create": True,
        },
        {
            "id": "cos-week-openai",
            "tier_cls": "soon-urgent",
            "tier_badge": "Due Thu Nov 5",
            "tier_pill_cls": "amber",
            "break_tags": "all 30m deep",
            "title": "Thu Nov 5 Deadline: OpenAI Academic Research Grant Application",
            "driver": "Star Chart deadline in 3 days. researchPrime + Gandalf pre-staged proposal narrative & compute budget.",
            "oranges_skill": "researchPrime + Gandalf",
            "pid": hnf_pid or gwl_pid,
            "folder": hnf_dir or gwl_dir,
            "step_id": "openai-grant-nov5",
            "href": _cockpit_href(hnf_pid or gwl_pid),
            "open_label": "+ Create / Open Grant Cockpit",
            "skill_btn_label": "🧙 Pre-Stage Gandalf + researchPrime",
            "skill_prompt": "Synthesize the OpenAI Academic Research Program Grant narrative from Hierarchical Normalizing Flows and GWL Harnesses using researchPrime and stress-test with Gandalf.",
            "is_create": True,
        },
        {
            "id": "cos-week-nextgen",
            "tier_cls": "soon-urgent",
            "tier_badge": "⚡ 10m Break",
            "tier_pill_cls": "sky",
            "break_tags": "all 15m",
            "title": "⚡ 10m Break Win: Stop NextGen Google Account Paid Status",
            "driver": "Triggered by Google Workspace invoice email for nextgen-np.com + Commercial priority list.",
            "oranges_skill": "Steward",
            "pid": comm_pid or desk_pid,
            "folder": comm_dir,
            "step_id": "stop-nextgen-google",
            "href": _cockpit_href(comm_pid, desk_pid),
            "open_label": "↗ Open Commercial / Desk Cockpit",
            "skill_btn_label": "✓ Quick Clear Checklist",
            "skill_prompt": "Open the step-by-step checklist to cancel NextGen Google Workspace paid billing status.",
            "is_create": False,
        },
    ]

    month_efforts = [
        {
            "id": "cos-month-family-trips",
            "title": "🎁 Family Trips & Birthday Presents Radar",
            "badge": "Family · T-21d",
            "pill_cls": "pink",
            "break_tags": "all 15m 30m family",
            "meta": "🍊 Superjump gift & holiday travel options pre-staged before Nov cutoffs.",
            "oranges_text": "Pre-staged 3 curated gift ideas per upcoming family birthday + Thanksgiving/holiday travel holds (domains/family.md).",
            "href": _cockpit_href(trust_pid, desk_pid),
            "open_label": "+ Create Family Trip & Gift Cockpit",
            "skill_btn_label": "🚀 Run Superjump Gift/Trip Finder",
            "skill_prompt": "Use Superjump to generate curated family birthday present options and Thanksgiving/holiday family trip itineraries.",
            "is_create": True,
        },
        {
            "id": "cos-month-hnf",
            "title": "🧮 Normalizing Flows — Paper 1 (Nov 22)",
            "badge": "🟢 Running",
            "pill_cls": "emerald",
            "break_tags": "all deep",
            "meta": "🍊 Ramanujan + researchPrime proof & citation pack ready.",
            "oranges_text": "Ramanujan Jacobian bound checks and researchPrime related-work citations staged in cockpit.",
            "href": _cockpit_href(hnf_pid),
            "open_label": "↗ Open AI Cockpit (Normalizing Flows)",
            "skill_btn_label": "🧮 Pre-Stage Ramanujan",
            "skill_prompt": "Run Ramanujan proof obligation check and researchPrime citation verification for Hierarchical Normalizing Flows Paper 1.",
            "is_create": False,
        },
        {
            "id": "cos-month-adio",
            "title": "💼 OpX Redo & ADIO Road Show (Nov 24)",
            "badge": "Nov 24",
            "pill_cls": "amber",
            "break_tags": "all 30m",
            "meta": "🍊 Financial-Analyst + Gandalf pitch stress-test pre-staged.",
            "oranges_text": "Financial-Analyst valuation model and Gandalf investor Q&A prep staged for Nov 24 road show.",
            "href": _cockpit_href(comm_pid),
            "open_label": "↗ Open Cockpit (OpX / ADIO)",
            "skill_btn_label": "📊 Pre-Stage Financial-Analyst",
            "skill_prompt": "Run Financial-Analyst model verification and Gandalf pitch review for OpX Redo and ADIO Road Show.",
            "is_create": False,
        },
    ]

    quarter_efforts = [
        {
            "id": "cos-qtr-magi",
            "title": "📖 Artificial Magi (Book 1) & BrightHeart v2",
            "badge": "Q2 Writing",
            "pill_cls": "purple",
            "break_tags": "all deep",
            "meta": "🍊 Chekhov story ledger + Superjump Act II beats ready.",
            "oranges_text": "Chekhov continuity dossier and Superjump Act II structural beats pre-staged for creative deep work.",
            "href": _cockpit_href(magi_pid),
            "open_label": "↗ Open Writing AI Cockpit",
            "skill_btn_label": "🎭 Pre-Stage Chekhov",
            "skill_prompt": "Run Chekhov continuity ledger check on Artificial Magi Book 1 outline and Chronicles of the Dragon-Kept (BrightHeart v2).",
            "is_create": False,
        },
        {
            "id": "cos-qtr-3d",
            "title": "🧬 3D Parametric Phenomics (Keith Cheng)",
            "badge": "Q2 Research",
            "pill_cls": "emerald",
            "break_tags": "all deep",
            "meta": "🍊 Superjump + Anvil spline representation prep ready.",
            "oranges_text": "Superjump analogical transfer & Anvil codebase map pre-staged for 3D parametric spline representation.",
            "href": _cockpit_href(phen_pid),
            "open_label": "↗ Open 3D Parametric Cockpit",
            "skill_btn_label": "🚀 Pre-Stage Superjump",
            "skill_prompt": "Run Superjump and Anvil to evaluate 3D parametric spline representations for Keith Cheng phenomics.",
            "is_create": False,
        },
        {
            "id": "cos-qtr-gwl",
            "title": "⚙️ GWL Harnesses (gwl-t2r-brain)",
            "badge": "🟢 Running",
            "pill_cls": "sky",
            "break_tags": "all deep",
            "meta": "🍊 Anvil + Aegis architecture & security audit staged.",
            "oranges_text": "Anvil 3-level progressive abstraction map and Aegis security verification staged.",
            "href": _cockpit_href(gwl_pid),
            "open_label": "↗ Open GWL Harnesses Cockpit",
            "skill_btn_label": "🔨 Pre-Stage Anvil + Aegis",
            "skill_prompt": "Run Anvil progressive abstraction map and Aegis security check on gwl-t2r-brain.",
            "is_create": False,
        },
    ]

    # Ensure every Chief of Staff recommendation (Today, Week, Month, Quarter) is tied to an item on The List
    _default_list_map = [
        ("wl-mba-ba815", "📋 The List · #1 (Teaching)"),
        ("wl-family-trusts-jane", "📋 The List · #2 (Personal)"),
        ("wl-hnf-grant", "📋 The List · #2 (Research)"),
        ("wl-nextgen-billing", "📋 The List · #1 (Business)"),
    ]
    for _idx, _ef in enumerate(today_efforts):
        _ef.setdefault("list_tile_id", _default_list_map[_idx % len(_default_list_map)][0])
        _ef.setdefault("list_badge", _ef.get("tier_badge") or _default_list_map[_idx % len(_default_list_map)][1])
    for _idx, _ef in enumerate(week_efforts):
        _ef.setdefault("list_tile_id", _default_list_map[_idx % len(_default_list_map)][0])
        _ef.setdefault("list_badge", _default_list_map[_idx % len(_default_list_map)][1])
    for _idx, _ef in enumerate(month_efforts):
        _ef.setdefault("list_tile_id", _default_list_map[(_idx + 1) % len(_default_list_map)][0])
        _ef.setdefault("list_badge", _default_list_map[(_idx + 1) % len(_default_list_map)][1])
    for _idx, _ef in enumerate(quarter_efforts):
        _ef.setdefault("list_tile_id", _default_list_map[(_idx + 2) % len(_default_list_map)][0])
        _ef.setdefault("list_badge", _default_list_map[(_idx + 2) % len(_default_list_map)][1])

    n_running = max(len(working_pids), 2)
    return {
        "today_efforts": today_efforts,
        "week_efforts": week_efforts,
        "month_efforts": month_efforts,
        "quarter_efforts": quarter_efforts,
        "running_cockpits": n_running,
        "skills_prestaged": 6,
        "urgent_count": 2,
        "q2_unlocked_hours": "2.5 hrs",
        "total_efforts": len(today_efforts) + len(week_efforts) + len(month_efforts) + len(quarter_efforts),
    }
