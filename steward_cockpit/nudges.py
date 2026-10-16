"""W3 of the active set — the steward steps in (PLAN v1.3.2 fits 8–9, 2026-10-01).

ONE nudge at a speaking boundary, derived from the records alone — never a model turn, never a write — in his words,
with its receipt (the fact it read) and one-click acts. The kinds, in the order one wins:

  dated      a dated part due within three days in a goal he is NOT working in now ("Excuse me: … is due tomorrow")
  deck_wait  an initiative that waits on him and is only on deck ("… waits on you and is only on deck — make it active?")
  starving   a Tier-1 goal untouched for a week, a Tier-2 for two ("… untouched for 12 days — put one of its cockpits on deck?")
  seed       a seed that reads like a goal ("the seed '…' reads like a goal — make it one?")
  free       nothing active and something on deck ("A free moment: … is on deck — make it active?")

"Not now" is a receipt kept in the Campaign's own folder (``.ecgberht/nudges.json``) that silences THAT nudge until its
fact changes: the key names the kind, the subject and the fact, so a new date, a new wait, another week of silence or
another seed is a new nudge. Never twice for the same fact; never more than one at a boundary; nothing moves without
his click or his word (the acts are the Campaign's own: seat, promote, not_now).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path

STARVE_DAYS = {1: 7, 2: 14}
NOT_DATED = frozenset({"deck_wait", "starving", "seed", "free"})     # every kind but the interrupt lane's (2026-10-03)
DATED_WINDOW_DAYS = 3
NUDGES_FILE = ".ecgberht/nudges.json"
RESUME_FILE = ".ecgberht/resume.json"      # the interrupt lane's ready-to-resume note (2026-10-03)
RESUME_DAYS = 2
PREMORTEM_FILE = ".ecgberht/premortem.json"   # the Star Chart's premortem asks (2026-10-03)
_SEED_VERBS = re.compile(r"\b(finish|ship|write|launch|build|publish|get|teach|run|deliver|submit|complete|start|set up|create|design|draft)\b", re.I)


def _iso(d):
    if isinstance(d, date):
        return d
    try:
        return datetime.strptime(str(d)[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def when_words(d, today):
    """'today' · 'tomorrow' · 'Fri, Oct 3' — the date as he says it."""
    if d == today:
        return "today"
    if d == today + timedelta(days=1):
        return "tomorrow"
    return d.strftime("%a, %b %d").replace(" 0", " ")


def _open(p):
    return isinstance(p, dict) and not p.get("done") and not p.get("closed") and str(p.get("status") or "").lower() not in ("done", "parked", "cancelled", "dropped")


def fact_key(kind, subject, fact):
    """The receipt's key: the kind, the subject and the fact it read — a changed fact is a new nudge."""
    h = hashlib.sha1(("%s|%s|%s" % (kind, subject, fact)).encode("utf-8")).hexdigest()[:12]
    return "%s:%s:%s" % (kind, str(subject)[:40], h)


def _goals_at_hand(initiatives, working):
    """The goals he is working in now: those with an ACTIVE initiative, or a cockpit with a live session."""
    at_hand = set()
    for i in initiatives or ():
        for p in i.get("parts") or ():
            if p.get("seat") == "active" or (p.get("pid") and p["pid"] in (working or set())):
                at_hand.add(i["id"])
    return at_hand


def derive(initiatives, facts=None, seeds=None, working=None, today=None, strip_ages=None, goal_last_at=None,
           dismissed=None, scope_goal=None, campaign_pid="", head_lead=None, kinds=None):
    """The one nudge for this boundary, or None. ``scope_goal`` narrows it to one goal's conversation (the Campaign
    page's place): only that goal's dated parts, deck waits and starvation; seeds and the free moment belong to the
    High Seat's brief. ``dismissed`` is the receipts file read (``read_dismissed``). ``head_lead`` is (pid, part name)
    of the brief's own lead sentence: a part the head already names is never nudged too (Grok W3, RC-3). ``kinds``
    limits the candidates to those kinds (None = all): one lane per item (John, 2026-10-03) - the Cave's interrupt lane
    asks for ``{"dated"}``, its panel and the Star Chart's goal places for the rest, so a dated item shows once."""
    today = today or date.today()
    inits = [i for i in initiatives or () if isinstance(i, dict) and i.get("status") not in ("done", "parked")]
    if scope_goal:
        inits = [i for i in inits if i.get("id") == scope_goal]
    dismissed = dismissed or {}
    working = working or set()
    seeds = [s for s in (seeds if isinstance(seeds, (list, tuple)) else ()) if isinstance(s, dict)]   # rows, never a count
    at_hand = _goals_at_hand(initiatives, working)
    lead_pid, lead_part = (str(head_lead[0] or ""), str(head_lead[1] or "")) if isinstance(head_lead, (list, tuple)) and len(head_lead) == 2 else ("", "")

    def _is_lead(p):
        name = str(p.get("target") or p.get("text") or "")
        return bool((lead_pid and p.get("pid") == lead_pid) or (lead_part and name == lead_part))
    cands = []

    def add(kind, subject, fact, text, why, acts, goal=None, rank=0):
        key = fact_key(kind, subject, fact)
        if (kinds is not None and kind not in kinds) or key in dismissed:
            return
        cands.append({"kind": kind, "key": key, "fact": str(fact), "text": text, "why": why, "acts": acts, "goal": goal, "rank": rank})

    # 1. a dated thing near while he is elsewhere
    best = None
    for i in inits:
        for p in i.get("parts") or ():
            if not _open(p) or p.get("broken"):
                continue
            d = _iso(p.get("date"))
            if d is None or d < today or (d - today).days > DATED_WINDOW_DAYS:
                continue
            if not scope_goal and i["id"] in at_hand:
                continue      # his own goal at hand: the head says it, not a nudge
            if best is None or d < best[0]:
                best = (d, i, p)
    if best:
        d, i, p = best
        name = str(p.get("target") or p.get("text") or "a part")
        # in the goal's own place the goal is already open on screen: no link to it (Grok W3)
        opens = [{"act": "open", "href": "/project/%s?open=%s" % (campaign_pid, i["id"]), "label": "open the goal"}] if campaign_pid and not scope_goal else []
        if p.get("pid"):
            opens.insert(0, {"act": "open", "href": "/project/%s" % p["pid"], "label": "open the cockpit"})
        add("dated", p.get("id") or name, d.isoformat(),
            "Excuse me: %s is due %s (%s)." % (name, when_words(d, today), i.get("name") or "a goal"),
            "the part's date on the Campaign record: %s" % d.isoformat(), opens, goal=i["id"], rank=1)

    # 2. an initiative that needs him and is only on deck - unless the head's own sentence already leads with it
    for i in inits:
        for p in i.get("parts") or ():
            if _open(p) and p.get("seat") == "deck" and p.get("needs_you") and not _is_lead(p):
                wait = re.sub(r"^waiting on you[:\s]*", "", str(p.get("state") or ""), flags=re.I).strip(" .") or "a wait"
                name = str(p.get("target") or p.get("text") or "it")
                add("deck_wait", p.get("id"), wait,
                    "%s waits on you and is only on deck — make it active?" % name,
                    "its record: needs you · %s" % wait[:120],
                    [{"act": "seat", "step": p.get("id"), "seat": "active", "label": "make it active"}] + ([{"act": "open", "href": "/project/%s" % p["pid"], "label": "open"}] if p.get("pid") else []),
                    goal=i["id"], rank=2)
                break

    # 3. a top goal starving
    for i in inits:
        tier = i.get("tier")
        if tier not in STARVE_DAYS or i["id"] in at_hand:
            continue
        ages = [int((strip_ages or {}).get(p.get("pid"), 0) or 0) for p in i.get("parts") or () if p.get("pid")]
        age = max(ages) if ages else 0
        last = (goal_last_at or {}).get(i["id"])
        if not age and last:
            try:
                age = (today - _iso(last)).days if _iso(last) else 0
            except Exception:
                age = 0
        if age >= STARVE_DAYS[tier]:
            # the cockpit offered is the one whose age was quoted when it is unseated, else the first unseated (Grok W3)
            unseated = [p for p in i.get("parts") or () if _open(p) and p.get("kind") in ("project", "effort") and not p.get("seat")]
            unseated.sort(key=lambda p: -int((strip_ages or {}).get(p.get("pid"), 0) or 0))
            cockpit = unseated[0] if unseated else None
            acts = ([{"act": "seat", "step": cockpit.get("id"), "seat": "deck", "label": "put %s on deck" % str(cockpit.get("target") or cockpit.get("text") or "it")[:40]}] if cockpit else [])
            if campaign_pid:
                acts.append({"act": "open", "href": "/project/%s?open=%s" % (campaign_pid, i["id"]), "label": "open the goal"})
            add("starving", i["id"], age // 7,
                "%s is a Tier-%d goal untouched for %d days — %s" % (i.get("name") or "a goal", tier, age, "put one of its cockpits on deck?" if cockpit else "pick it up?"),
                "the strip's anti_starvation_age_days of its cockpits, else the days since its last turn: %d" % age, acts, goal=i["id"], rank=3)

    if not scope_goal:
        # 4. a seed that reads like a goal
        for s in seeds or ():
            text = " ".join(str(s.get("text") or "").split())
            words = text.split()
            if len(words) >= 6 and not text.endswith("?") and (_SEED_VERBS.search(text) or re.search(r"\bby\b", text, re.I)):
                add("seed", s.get("id"), s.get("id"),
                    "the seed ‘%s’ reads like a goal — make it one?" % (text[:90] + ("…" if len(text) > 90 else "")),
                    "a seed on the Campaign's strip, %d words with a verb" % len(words),
                    [{"act": "promote", "seed": s.get("id"), "tier": 2, "area": "", "done_when": text[:200], "label": "make it a goal (tier 2)"}] + ([{"act": "open", "href": "/project/%s" % campaign_pid, "label": "open the seeds"}] if campaign_pid else []),
                    rank=4)
                break
        # 5. a free moment: nothing active, something on deck - never the part whose deck wait he already put off
        # (that would be the same "make it active?" twice)
        put_off = {k.split(":", 2)[1] for k in dismissed if k.startswith("deck_wait:")}
        active = [p for i in inits for p in i.get("parts") or () if _open(p) and p.get("seat") == "active"]
        deck = sorted([(i, p) for i in inits for p in i.get("parts") or () if _open(p) and p.get("seat") == "deck" and str(p.get("id"))[:40] not in put_off and not _is_lead(p)],
                      key=lambda t: (t[1].get("seat_order") if isinstance(t[1].get("seat_order"), int) else 999))
        if not active and deck:
            i, p = deck[0]
            name = str(p.get("target") or p.get("text") or "it")
            add("free", p.get("id"), p.get("id"),
                "A free moment: %s is on deck (%s) — make it active?" % (name, i.get("name") or "a goal"),
                "nothing is active; the top of On deck", [{"act": "seat", "step": p.get("id"), "seat": "active", "label": "make it active"}], goal=i["id"], rank=5)

    if not cands:
        return None
    cands.sort(key=lambda c: c["rank"])
    return cands[0]


def _path(campaign_dir):
    return Path(campaign_dir) / NUDGES_FILE


def read_dismissed(campaign_dir):
    """The 'not now' receipts: {key: {at, fact, text}}; empty when none."""
    try:
        d = json.loads(_path(campaign_dir).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def dismiss(campaign_dir, key, fact="", text=""):
    """His 'not now': a receipt that silences that nudge until its fact changes. Written whole, never raises."""
    key = str(key or "").strip()
    if not key or len(key) > 120 or "/" in key or "\\" in key:
        return {"ok": False, "error": "no such nudge"}
    d = read_dismissed(campaign_dir)
    d[key] = {"at": time.strftime("%Y-%m-%d %H:%M"), "fact": str(fact or "")[:200], "text": str(text or "")[:240]}
    try:
        p = _path(campaign_dir); p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp"); tmp.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8"); os.replace(str(tmp), str(p))
    except OSError as e:
        return {"ok": False, "error": "the receipt could not be kept: %s" % e}
    return {"ok": True, "key": key}


def undismiss(campaign_dir, key):
    d = read_dismissed(campaign_dir)
    if str(key) not in d:
        return {"ok": False, "error": "that nudge was not silenced"}
    d.pop(str(key), None)
    try:
        p = _path(campaign_dir); tmp = p.with_suffix(".json.tmp"); tmp.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8"); os.replace(str(tmp), str(p))
    except OSError as e:
        return {"ok": False, "error": "the receipt could not be dropped: %s" % e}
    return {"ok": True, "key": str(key)}


# ── the interrupt lane's ready-to-resume note (John, 2026-10-03: the lane lives on the Cave of Wonders) ─────────────
# When he opens a dated item from the lane, what he was on is kept as one line; the Cave shows it at the top of the
# panel ("You were on: ...") until he clears it or two days pass. One note at a time; never raises.

def write_resume(campaign_dir, note, switched_to=""):
    note = " ".join(str(note or "").split())[:240]
    if not note:
        return {"ok": False, "error": "nothing to keep"}
    d = {"at": time.strftime("%Y-%m-%d %H:%M"), "note": note, "switched_to": " ".join(str(switched_to or "").split())[:160]}
    try:
        p = Path(campaign_dir) / RESUME_FILE; p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp"); tmp.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8"); os.replace(str(tmp), str(p))
    except OSError as e:
        return {"ok": False, "error": "the note could not be kept: %s" % e}
    return {"ok": True, **d}


def read_resume(campaign_dir, today=None):
    """The note, or None when there is none or it is older than RESUME_DAYS."""
    try:
        d = json.loads((Path(campaign_dir) / RESUME_FILE).read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(d, dict) or not d.get("note"):
        return None
    at = _iso(str(d.get("at") or "")[:10])
    if at and ((today or date.today()) - at).days > RESUME_DAYS:
        return None
    return d


def clear_resume(campaign_dir):
    was = read_resume(campaign_dir)
    try:
        (Path(campaign_dir) / RESUME_FILE).unlink()
    except FileNotFoundError:
        pass
    except OSError as e:
        return {"ok": False, "error": "the note could not be cleared: %s" % e}
    return {"ok": True, "was": was}


# ── the Star Chart's premortem (2026-10-03): asked once when a goal is made or its pace slips later ──────────────────
# {goal_id: {at, reason}}; the ask stands on the goal's card until he answers (the answer goes into the goal's guide)
# or says not now. Never raises.

def _pm_read(campaign_dir):
    try:
        d = json.loads((Path(campaign_dir) / PREMORTEM_FILE).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _pm_write(campaign_dir, d):
    try:
        p = Path(campaign_dir) / PREMORTEM_FILE; p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp"); tmp.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8"); os.replace(str(tmp), str(p))
        return True
    except OSError:
        return False


def read_premortems(campaign_dir):
    return _pm_read(campaign_dir)


def ask_premortem(campaign_dir, goal_id, reason):
    goal_id = str(goal_id or "").strip()
    if not goal_id or "/" in goal_id or "\\" in goal_id:
        return False
    d = _pm_read(campaign_dir)
    d[goal_id] = {"at": time.strftime("%Y-%m-%d %H:%M"), "reason": " ".join(str(reason or "").split())[:160]}
    return _pm_write(campaign_dir, d)


def close_premortem(campaign_dir, goal_id):
    d = _pm_read(campaign_dir)
    was = d.pop(str(goal_id), None)
    return was if _pm_write(campaign_dir, d) else None
