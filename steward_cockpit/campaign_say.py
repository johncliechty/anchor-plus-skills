"""campaign_say — the Campaign verbs spoken in a composer: the engine names the act, the Campaign's own writer applies it.

W5 of the High Seat plan (2026-09-26). "move <initiative> to tier n" · "add a part to <initiative>: <text> [due <date>]"
· "make <seed> an initiative [in tier n] [under <area>]" · "park <part> until <trigger>" · "unpark <part>" · "what needs
me [this week|today]". The engine's dialogue act table compiles the words (the destructive guard first; nothing is
written there); this module resolves the names against the Campaign record — an exact name or id, else the one part
that contains the words, else a refusal that names the candidates — and applies the act through
``steward_cockpit/campaign_acts`` (the same receipts with undo the pages use). Anything that is not a Campaign verb
answers None and the steward takes it as before. Only the Campaign record is ever written.
"""
from __future__ import annotations

import calendar as _cal
import json
import os
import re
import subprocess
from datetime import date, timedelta
from pathlib import Path

from .campaign_acts import _ecgberht_root

DIALOGUE = (_ecgberht_root() / "engine" / "dialogue.mjs").as_uri()
AREAS = ("family", "professional", "writing", "research", "tools", "personal")
_STOP = {"the", "a", "an", "to", "of", "for", "and", "my", "our"}
_JS = ("import { compileUtterance, CAMPAIGN_ACT_IDS } from '%s';"
       "const r = compileUtterance(process.argv[1] || '');"
       "console.log(JSON.stringify({ok: !!r.compiled, act: r.act || null, args: r.args || {},"
       " campaign: !!(r.compiled && CAMPAIGN_ACT_IDS.includes(r.act)), refused: r.utterance_kind || null}));")


def campaign_dir():
    import paths as _paths
    return Path(_paths.data_dir()).resolve().parent / "Campaign"


CAVE_EFFORT = "Cave of Wonders"   # the Cave's own steward conversation (his word, 2026-10-02): an effort of the Campaign


def is_cave_folder(folder):
    try:
        return Path(str(folder)).resolve() == (campaign_dir() / CAVE_EFFORT).resolve()
    except Exception:
        return False


def is_campaign_folder(folder):
    try:
        return Path(str(folder)).resolve() == campaign_dir()
    except Exception:
        return False


def compile_utterance(text, dialogue=None):
    """The engine's word: ``{"ok", "act", "args", "campaign", "refused"}`` or None when the engine could not answer."""
    text = " ".join(str(text or "").split())
    if not text:
        return None
    try:
        r = subprocess.run(["node", "--input-type=module", "-e", _JS % (dialogue or DIALOGUE), "--", text],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        return json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        return None


# ── names ──────────────────────────────────────────────────────────────────────────────────────

def _norm(s):
    s = " ".join(str(s or "").lower().split()).strip(" .!?,\u2019'\"")
    return re.sub(r"^(?:the|an|a) ", "", s)


def _find(cands, phrase, what):
    """``cands`` = [(id, name, ...)]; the exact name or id, else the one candidate containing the words either way."""
    key = _norm(phrase)
    if not key:
        return None, "which %s? say its name" % what
    exact = [c for c in cands if _norm(c[1]) == key or _norm(c[0]) == key]
    if len(exact) == 1:
        return exact[0], None
    words = {w for w in re.split(r"[^a-z0-9]+", key) if w and w not in _STOP}
    byword = [c for c in cands if words and words <= {w for w in re.split(r"[^a-z0-9]+", _norm(c[1])) if w}]
    if len(byword) == 1:
        return byword[0], None
    # a looser match (the words inside a name) only NAMES a candidate; it never selects one, so it never writes
    near = byword or [c for c in cands if key in _norm(c[1])]
    if len(near) == 1:
        return None, "did you mean \u2018%s\u2019? say its name" % near[0][1]
    if near or exact:
        names = " or ".join("\u2018%s\u2019" % c[1] for c in (exact or near)[:5])
        return None, "\u2018%s\u2019 could be %s \u2014 say which" % (phrase, names)
    names = ", ".join("\u2018%s\u2019" % c[1] for c in cands[:6])
    return None, "no %s named \u2018%s\u2019%s" % (what, phrase, (" \u2014 the record has " + names) if names else "")


_MONTHS = {m.lower(): k for k, m in enumerate(_cal.month_abbr) if m}
_MONTHS.update({m.lower(): k for k, m in enumerate(_cal.month_name) if m})
_DAYS = {d.lower(): k for k, d in enumerate(_cal.day_abbr)}
_DAYS.update({d.lower(): k for k, d in enumerate(_cal.day_name)})


def parse_due(s, today=None):
    """YYYY-MM-DD · today · tomorrow · Tuesday · Oct 27 · 27 Oct (this year, as typed) — or None when the calendar has
    no such day (the same rule the Desk's own editor keeps)."""
    today = today or date.today()
    s = " ".join(str(s or "").lower().split()).strip(" .!")
    if not s:
        return None
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            return None
    if s == "today":
        return today.isoformat()
    if s == "tomorrow":
        return (today + timedelta(days=1)).isoformat()
    if s.isalpha() and (s in _DAYS or s[:3] in _DAYS):
        ahead = (_DAYS.get(s, _DAYS.get(s[:3])) - today.weekday()) % 7 or 7
        return (today + timedelta(days=ahead)).isoformat()
    m = re.fullmatch(r"([a-z]+)\.? (\d{1,2})", s) or re.fullmatch(r"(\d{1,2}) ([a-z]+)\.?", s)
    if m:
        a, b = m.group(1), m.group(2)
        mon, day = (a, b) if a.isalpha() else (b, a)
        k = _MONTHS.get(mon) or _MONTHS.get(mon[:3])
        if k:
            try:
                return date(today.year, k, int(day)).isoformat()
            except ValueError:
                return None
    return None


# ── the answer ─────────────────────────────────────────────────────────────────────────────────

def _answer(r, act):
    out = {"ok": bool(r.get("ok")), "say": r.get("receipt") or "", "receipt": r.get("receipt") or "", "undo": r.get("undo"),
           "act": act, "campaign_act": True, "model_called": False}
    if r.get("step"):
        out["step"] = r["step"]
    return out


def _refuse(text, act):
    return {"ok": False, "say": text, "receipt": text, "undo": None, "act": act, "campaign_act": True, "model_called": False}


def _needs(folder, span, today):
    """What needs him: the parts flagged needs-you, and the dated parts inside the span — read from the record."""
    try:
        import high_seat_page as _hsp
        from .campaign_parts import resolve_parts
        from .steward_campaign import read_map
        steps = (read_map(str(folder)) or {}).get("steps") or []
        inits = _hsp.campaign_initiatives(steps, resolve_parts(steps, cache={}, with_lead=False))
    except Exception as e:
        return _refuse("the Campaign record could not be read: %s" % e, "campaign_needs")
    needs = [(p, i) for i in inits for p in i["needs"]]
    monday = today - timedelta(days=today.weekday())
    start = monday.isoformat() if span != "today" else ""
    end = today if span == "today" else monday + timedelta(days=6)
    dated = sorted(((p["date"], p, i) for i in inits for p in i["parts"]
                    if p["date"] and not p["broken"] and p["status"] not in ("done", "parked") and start <= p["date"] <= end.isoformat()), key=lambda x: x[0])

    def more(n):
        return (" \u2014 and %d more" % (n - 5)) if n > 5 else ""
    bits = []
    if needs:
        bits.append("%d need%s your word: %s%s" % (len(needs), "s" if len(needs) == 1 else "", "; ".join("%s (%s, tier %s)" % (p["text"], i["name"], i["tier"] or "?") for p, i in needs[:5]), more(len(needs))))
    else:
        bits.append("nothing waits on your word")
    label = "today" if span == "today" else "this week"
    if dated:
        bits.append("dated %s: %s%s" % ("today or earlier" if span == "today" else "inside this week (Monday to Sunday)", "; ".join("%s (%s, %s)" % (p["text"], i["name"], p["date"]) for d, p, i in dated[:5]), more(len(dated))))
    else:
        bits.append("nothing on the Campaign is dated %s" % ("today or earlier" if span == "today" else "inside this week"))
    return {"ok": True, "say": "; ".join(bits) + ".", "receipt": "", "undo": None, "act": "campaign_needs", "campaign_act": True, "read_only": True, "model_called": False}


_BARE_BY = re.compile(r"^(.+?) by (.+?)\s*[.!]?$", re.I)


def _bare_pace(folder, text, today):
    """"<name> by <date>" (fit 5) is a pace only when the left side is exactly one initiative: the whole name, or the
    start of exactly one name ("MBA" for "MBA Teaching, Fall 2026"; "the trusts" for "The trusts and the holding
    company"). An interior word ("teaching by Monday") names nothing here and the words go to the steward. The
    engine's grammar does not carry this form (Grok W1): the names live here, so the reading does too."""
    m = _BARE_BY.match(" ".join(str(text or "").split()))
    if not m:
        return None
    from . import campaign_acts as acts
    inits = [(s["id"], s.get("name") or s["id"]) for s, g in acts._initiatives(folder)]
    key = _norm(m.group(1))
    if not key:
        return None
    hits = [c for c in inits if _norm(c[1]) == key or _norm(c[0]) == key]
    if not hits:
        hits = [c for c in inits if _norm(c[1]).startswith(key + " ") or _norm(c[1]).startswith(key + ",")]
    if len(hits) != 1:
        return None
    when = parse_due(m.group(2), today)
    if when is None:
        return None      # "<name> by <not a date>" is not a pace: the steward takes the words
    return _answer(acts.pace(folder, hits[0][0], when), "campaign_pace")


_SCOPED = [
    ("campaign_add_part", re.compile(r"^add(?: (?:a |the |another )?(?:part|task|step))?:?\s+(.+?)(?:,? due (.+?))?\s*[.!]?$", re.I)),
    ("campaign_pace", re.compile(r"^(?:(?:set )?(?:the )?pace(?: (?:to|by|at|is|of))?|by|due|finish(?:ed)? by|done by)\s+(.+?)\s*[.!]?$", re.I)),
    ("campaign_pace_clear", re.compile(r"^(?:clear|drop|remove) the pace\s*[.!]?$|^no pace\s*[.!]?$", re.I)),
    ("campaign_goal_seat", re.compile(r"^(?:make (?:it|this) active|activate(?: it| this)?|put (?:it|this) on deck|bench(?: it| this)?|send (?:it|this) back)\s*[.!]?$", re.I)),
    ("campaign_activate", re.compile(r"^(?:make|set) (.+?) active\s*[.!]?$|^activate (.+?)\s*[.!]?$", re.I)),
    ("campaign_deck", re.compile(r"^put (.+?) on deck\s*[.!]?$|^deck (.+?)\s*[.!]?$", re.I)),
    ("campaign_home", re.compile(r"^send (.+?) (?:back|home)(?: to (?:its|the) goal)?\s*[.!]?$|^put (.+?) back(?: in (?:its|the) goal)?\s*[.!]?$|^bench (.+?)\s*[.!]?$", re.I)),
    ("campaign_move_tier", re.compile(r"^(?:(?:move|put) (?:it |this )?(?:to |in |into )?)?tier ([123])\s*[.!]?$", re.I)),
    ("campaign_done_when", re.compile(r"^(?:the )?(?:goal|done when|done looks like|done is|done means)(?: is)?:?\s+(.+?)\s*[.!]?$", re.I)),
    # the Star Chart (2026-10-03): "if-then: if it is Monday 9:00, then I send the trust questions" - his words, kept whole
    ("campaign_if_then", re.compile(r"^(?:the )?(?:if[- ]then|next step)(?: is)?:\s*(.+?)\s*$", re.I)),
]


def _scoped(folder, goal, text, today):
    """Inside a goal's place (W2 v2) a verb needs no name: "add a part: …", "pace by Oct 10", "make it active",
    "bench it", "tier 2", "goal: …". None when the words are none of these (the general grammar, then the steward,
    take them — told which goal he is in)."""
    from . import campaign_acts as acts
    s = acts._step(folder, goal)
    if s is None or acts._own_group(s) is None:
        return None
    t = " ".join(str(text or "").split())
    for act, rx in _SCOPED:
        m = rx.match(t)
        if not m:
            continue
        if act == "campaign_add_part":
            due = None
            if m.group(2):
                due = parse_due(m.group(2), today)
                if due is None:
                    return _refuse("I could not read \u2018%s\u2019 as a date \u2014 Oct 10, Tuesday or 2026-10-10; nothing was added" % m.group(2), act)
            return _answer(acts.add(folder, goal, "task", m.group(1), due=due), act)
        if act == "campaign_pace":
            when = parse_due(m.group(1), today)
            if when is None:
                return None      # "by the end of the world": not a date — the steward takes the words
            return _answer(acts.pace(folder, goal, when), act)
        if act == "campaign_pace_clear":
            return _answer(acts.pace(folder, goal, "none"), "campaign_pace")
        if act == "campaign_goal_seat":
            return _answer(acts.seat(folder, goal, "active"), "campaign_activate")      # refused by the writer: a goal has no seat — it names the components
        if act in ("campaign_activate", "campaign_deck", "campaign_home"):
            name = next((x for x in m.groups() if x), "")
            mine = [(p["id"], p.get("name") or p["id"]) for p in acts._parts_of(folder, goal) if acts._kind_of(p) in acts.INITIATIVE_KINDS]
            hit, why = _find(mine, name, "component")
            if hit is None:
                return None      # not one of this goal's components: the general grammar reads the name across the record
            return _answer(acts.home(folder, hit[0]) if act == "campaign_home" else acts.seat(folder, hit[0], "active" if act == "campaign_activate" else "deck"), act)
        if act == "campaign_move_tier":
            return _answer(acts.move_tier(folder, goal, int(m.group(1))), act)
        if act == "campaign_done_when":
            return _answer(acts.done_when(folder, goal, m.group(1)), act)
        if act == "campaign_if_then":
            return _answer(acts.if_then(folder, goal, m.group(1)), act)
    return None


def say_campaign(folder, text, dialogue=None, today=None, goal=None):
    """None when the words are not a Campaign verb (the steward takes them); else the act's answer. With ``goal``
    (an initiative id: the words were said inside that goal's place) the scoped forms are read first."""
    if goal:
        scoped = _scoped(folder, str(goal), text, today or date.today())
        if scoped is not None:
            return scoped
    bare = _bare_pace(folder, text, today or date.today())
    if bare is not None:
        return bare
    c = compile_utterance(text, dialogue)
    if c is None:
        return _refuse("the Campaign\u2019s grammar could not be read (the engine did not answer) \u2014 nothing was done", "campaign_compile")
    if not c.get("campaign"):
        return None
    try:
        return _apply(folder, c, today or date.today())
    except Exception as e:
        return _refuse("that did not go through: %s \u2014 look at the board before saying it again" % e, str(c.get("act") or "campaign_act"))


def _apply(folder, c, today):
    from . import campaign_acts as acts
    act, a = c["act"], c.get("args") or {}
    inits = [(s["id"], s.get("name") or s["id"]) for s, g in acts._initiatives(folder)]
    heads = {i for i, _ in inits}
    parts = [(p["id"], p.get("name") or p["id"]) for p in acts._projection(folder)
             if p.get("id") not in heads and isinstance(p.get("navigation"), dict) and (p["navigation"].get("path") or [])]
    if act == "campaign_move_tier":
        hit, why = _find(inits, a.get("initiative"), "goal")
        return _refuse(why, act) if hit is None else _answer(acts.move_tier(folder, hit[0], a.get("tier")), act)
    if act == "campaign_add_part":
        hit, why = _find(inits, a.get("initiative"), "goal")
        if hit is None:
            return _refuse(why, act)
        due = None
        if a.get("due"):
            due = parse_due(a["due"], today)
            if due is None:
                return _refuse("I could not read \u2018%s\u2019 as a date \u2014 Oct 3, Tuesday, today or 2026-10-03; nothing was added" % a["due"], act)
        return _answer(acts.add(folder, hit[0], "task", a.get("text"), due), act)
    if act == "campaign_promote_seed":
        from .campaign_seeds import read_seeds
        seeds = [(s["id"], s["text"]) for s in read_seeds(folder)]
        hit, why = _find(seeds, a.get("seed"), "seed")
        if hit is None:
            if not str(why or "").startswith("no seed"):
                return _refuse(why, act)      # a near seed ("did you mean") or a tie is answered; nothing is written (Grok's read of W2b)
            # no seed by that name: a goal from his words (2026-09-30), at the tier and area he said
            return _answer(acts.new_goal(folder, a.get("seed"), a.get("tier"), a.get("area")), act)
        area = str(a.get("area") or "").lower() or None
        if area and area not in AREAS:
            return _refuse("the life areas are %s \u2014 which?" % ", ".join(AREAS), act)
        return _answer(acts.promote(folder, hit[0], a.get("tier") or 3, area), act)
    if act == "campaign_park":
        hit, why = _find(parts, a.get("part"), "part")
        if hit is None:
            return _refuse(why, act)
        if not a.get("trigger"):
            return _refuse("a park carries its trigger \u2014 say \u2018park %s until January\u2019, or what it waits for" % hit[1], act)
        return _answer(acts.park(folder, hit[0], a["trigger"]), act)
    if act == "campaign_unpark":
        hit, why = _find(parts, a.get("part"), "part")
        return _refuse(why, act) if hit is None else _answer(acts.unpark(folder, hit[0]), act)
    if act == "campaign_needs":
        return _needs(folder, a.get("span") or "week", today)
    # the seats (2026-09-30, his three levels): the verbs name a COMPONENT — a cockpit, an effort or a desk item
    comps = [(p["id"], p.get("name") or p["id"]) for p in acts._projection(folder)
             if p.get("id") not in heads and isinstance(p.get("navigation"), dict) and (p["navigation"].get("path") or []) and acts._kind_of(p) in acts.INITIATIVE_KINDS]
    if act in ("campaign_activate", "campaign_deck", "campaign_home"):
        key = _norm(a.get("initiative"))
        g = next((c for c in inits if key and (_norm(c[1]) == key or _norm(c[0]) == key)), None)
        if g is not None:      # he named a goal by its whole name: a goal has no seat — the writer's refusal names its components
            return _answer(acts.seat(folder, g[0], "active"), act)
        if key and not any(_norm(c[1]) == key or _norm(c[0]) == key for c in comps):
            # the start of exactly one goal's name (the pace rule: "the trusts") is that goal, whatever its id — a
            # goal has no seat; words that are one component's words still seat the component (Grok's read of W2b)
            pre = [c for c in inits if _norm(c[1]).startswith(key + " ") or _norm(c[1]).startswith(key + ",")]
            if len(pre) == 1:
                return _answer(acts.seat(folder, pre[0][0], "active"), act)
        hit, why = _find(comps, a.get("initiative"), "initiative")
        if hit is None:
            return _refuse(why, act)
        return _answer(acts.home(folder, hit[0]) if act == "campaign_home" else acts.seat(folder, hit[0], "active" if act == "campaign_activate" else "deck"), act)
    if act == "campaign_pace":
        hit, why = _find(inits, a.get("initiative"), "goal")
        if hit is None:
            return _refuse(why, act)      # an explicit pace verb that names no initiative is refused with the names
        when = parse_due(a.get("pace"), today) if a.get("pace") not in (None, "", "none") else "none"
        if when is None:
            return _refuse("I could not read \u2018%s\u2019 as a date \u2014 Oct 10, Tuesday or 2026-10-10; the pace is unchanged" % a.get("pace"), act)
        return _answer(acts.pace(folder, hit[0], when), act)
    return None


# ── Wave 20 Fast Conversational Steward Path (<20ms Pure Python) ──────────────────────────────────────────────

_CREATE_COCKPIT_RX = re.compile(
    r"^(?:please\s+|let'?s\s+|can you\s+|could you\s+)?(?:create|make|start|spin up|launch|build|add|set up)\s+"
    r"(?:a\s+|an\s+)?(?:new\s+)?(?:ai\s+)?cockpit(?:\s+(?:for|called|named|on|about|to))?\s*[:\-]?\s*(.+?)\s*[.!?]?$",
    re.I,
)
_OPEN_COCKPIT_RX = re.compile(
    r"^(?:please\s+|can you\s+|could you\s+)?(?:open|launch|go to|take me to|pull up|switch to)\s+"
    r"(?:the\s+)?(?:ai\s+)?(?:cockpit\s+(?:for|on|of)\s+)?(.+?)(?:\s+ai)?(?:\s+cockpit|\s+project|\s+goal)?\s*[.!?]?$",
    re.I,
)
_MARK_DONE_RX = re.compile(
    r"^(?:please\s+|can you\s+)?(?:mark|check off|complete|finish|tick)(?:\s+the)?\s+"
    r"(?:(next\s+step)(?:\s+(?:done|complete|completed|off))?(?:\s+(?:on|for|in)\s+(.+?))?|(.+?)\s+(?:as\s+)?(?:done|complete|completed|off))\s*[.!?]?$",
    re.I,
)
_REARRANGE_RX = re.compile(
    r"^(?:please\s+|can you\s+|could you\s+|kind of\s+)?(?:rearrange(?:\s+the\s+priority\s+of)?(?:\s+and)?\s+)?"
    r"(?:put|move|set|make|shift|promote|demote|rearrange|prioritize|place|seat|send|take)\s+"
    r"(.+?)\s+(?:into|in|to|on|onto|as|at|under|off|from)?\s*"
    r"(active|top of active|first in active|first|on deck|deck|not active|inactive|off active|bench|home|back|"
    r"tier\s*[123]|today|this week|this month|this quarter|this year)\s*[.!?]?$",
    re.I,
)


def _load_rm_fast(folder):
    p = Path(folder) / "roadmap.json"
    if not p.is_file():
        return p, {"schema": "ecgberht-roadmap-v0", "project_id": None, "as_of": str(date.today()), "roadmap_events": [], "roadmap_projection": []}
    try:
        return p, json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return p, {"schema": "ecgberht-roadmap-v0", "project_id": None, "as_of": str(date.today()), "roadmap_events": [], "roadmap_projection": []}


def _save_rm_fast(p: Path, rm: dict):
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rm, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)


def _append_rm_event(rm: dict, kind: str, step_id: str, **kwargs):
    evs = rm.setdefault("roadmap_events", [])
    next_seq = max([int(e.get("seq") or 0) for e in evs if isinstance(e, dict)] or [0]) + 1
    ev = {"kind": kind, "step_id": step_id, "at": str(date.today()), "seq": next_seq}
    ev.update(kwargs)
    evs.append(ev)


def _fuzzy_match_item(proj: list, query: str, prefer_goals: bool = False):
    from . import campaign_acts as acts
    q = _norm(query)
    q = re.sub(r"\b(the|a|an|cockpit|ai cockpit|project|goal|initiative|tier|in|into|to|on|for)\b", " ", q)
    q = " ".join(q.split())
    if not q:
        return None
    goals = [s for s in proj if isinstance(s, dict) and acts._own_group(s) is not None]
    comps = [s for s in proj if isinstance(s, dict) and acts._own_group(s) is None and s.get("status") != "withdrawn"]
    pool = (goals + comps) if prefer_goals else (comps + goals)
    for s in pool:
        if _norm(s.get("id") or "") == q or _norm(s.get("name") or "") == q:
            return s
    for s in pool:
        nm = _norm(s.get("name") or "")
        sid = _norm(s.get("id") or "")
        if q in nm or q in sid or any(w and len(w) >= 3 and w in nm.split() for w in q.split()):
            return s
    return None


def fast_steward_command(folder, text, goal=None, today=None, from_cave=False, force_goal_seat=False):
    """Sub-20ms pure-Python execution for natural-language Cave of Wonders & Star Chart Steward commands."""
    import urllib.parse
    from . import campaign_acts as acts
    t = " ".join(str(text or "").split())
    if not t:
        return None
    today_dt = today or date.today()

    # 1. Create a new AI Cockpit
    m_create = _CREATE_COCKPIT_RX.match(t)
    if m_create:
        raw_rest = m_create.group(1).strip().strip("\"'“”‘’")
        parent_hint = goal or ""
        m_under = re.search(r"^(.+?)\s+(?:under|in|inside|for\s+goal)\s+(.+)$", raw_rest, re.I)
        if m_under:
            title = m_under.group(1).strip().strip("\"'“”‘’")
            parent_hint = m_under.group(2).strip().strip("\"'“”‘’")
        else:
            title = raw_rest
        if not title or len(title) < 2:
            return None
        rm_path, rm = _load_rm_fast(folder)
        proj = rm.setdefault("roadmap_projection", [])
        goals = [s for s in proj if isinstance(s, dict) and acts._own_group(s) is not None]
        parent_goal = _fuzzy_match_item(goals, parent_hint, prefer_goals=True) if parent_hint else None
        if parent_goal is None:
            parent_goal = _fuzzy_match_item(goals, title, prefer_goals=True)
        if parent_goal is None and goals:
            parent_goal = next((g for g in goals if g.get("tier") == 1), goals[0])
        goal_id = str((parent_goal or {}).get("id") or "anchor")
        goal_name = str((parent_goal or {}).get("name") or goal_id)
        slug = acts._slug(title, "cockpit")
        n = 2
        while any(isinstance(x, dict) and x.get("id") == slug for x in proj):
            slug = f"{acts._slug(title, 'cockpit')}-{n}"
            n += 1
        cockpit_dir = Path(folder) / "cockpits" / slug
        cockpit_dir.mkdir(parents=True, exist_ok=True)
        c_rm = {
            "schema": "ecgberht-roadmap-v0",
            "project_id": slug,
            "as_of": str(today_dt),
            "roadmap_events": [],
            "roadmap_projection": [
                {"id": "stage-0-intake", "name": f"Stage 0 Intake & Scope: {title}", "status": "active", "done_when": f"Scope and objectives locked for {title}"},
                {"id": "stage-1-execute", "name": f"Core Execution: {title}", "status": "planned", "done_when": "Primary deliverable drafted and verified"},
                {"id": "stage-2-review", "name": "Verification & Review", "status": "planned", "done_when": "Reviewed and signed off by John"},
            ],
        }
        (cockpit_dir / "roadmap.json").write_text(json.dumps(c_rm, indent=2) + "\n", encoding="utf-8")
        c_strip = {
            "schema": "ecgberht-strip-v0",
            "project_id": slug,
            "face_path": "ECGBERHT.md",
            "as_of": str(today_dt),
            "phase": "executing",
            "active_effort": title,
            "effort_status": "IN_PROGRESS",
            "current_step_id": "stage-0-intake",
            "next_recommended": f"Stage 0 Intake & Scope: {title}",
            "why_next": "Newly created AI Cockpit from Steward command",
        }
        (cockpit_dir / "strip.json").write_text(json.dumps(c_strip, indent=2) + "\n", encoding="utf-8")
        if not (cockpit_dir / "ECGBERHT.md").is_file():
            (cockpit_dir / "ECGBERHT.md").write_text(f"# {title}\n\n## North Star\n\n> AI Cockpit under **{goal_name}**.\n", encoding="utf-8")
        # Bump existing active seat_orders and seat new cockpit at 0
        for s in proj:
            if isinstance(s, dict) and s.get("seat") == "active":
                s["seat_order"] = int(s.get("seat_order") or 0) + 1
        new_step = {
            "id": slug,
            "name": title,
            "status": "active",
            "done_when": f"Complete {title}",
            "waiting_on": None,
            "seat": "active",
            "seat_order": 0,
            "effort_dir": str(cockpit_dir),
            "navigation": {"path": [goal_id], "current": True},
        }
        proj.append(new_step)
        _append_rm_event(rm, "step_create", slug, name=title, status="active", done_when=f"Complete {title}", waiting_on=None)
        _append_rm_event(rm, "step_set", slug, fields={"navigation": {"path": [goal_id]}, "seat": "active", "seat_order": 0})
        _save_rm_fast(rm_path, rm)
        msg = f"Created new AI Cockpit \u201c{title}\u201d under {goal_name} and seated it in Active."
        return {
            "ok": True,
            "say": msg,
            "receipt": msg,
            "undo": {"act": "withdraw", "step": slug},
            "act": "create_cockpit",
            "campaign_act": True,
            "read_only": False,
            "model_called": False,
            "open_url": "/steward?dir=" + urllib.parse.quote(str(cockpit_dir)),
            "step": slug,
        }

    # 2. Open an AI Cockpit / Project / Goal
    m_open = _OPEN_COCKPIT_RX.match(t)
    if m_open:
        target_q = m_open.group(1).strip().strip("\"'“”‘’")
        tq_norm = _norm(target_q)
        if tq_norm in ("star chart", "campaign", "the star chart", "the campaign"):
            msg = "Opening the Star Chart\u2026"
            return {"ok": True, "say": msg, "receipt": msg, "undo": None, "act": "open_cockpit", "campaign_act": True, "read_only": False, "model_called": False, "open_url": "/project/Campaign"}
        if tq_norm in ("cave of wonders", "the cave of wonders", "cave", "high seat", "the high seat"):
            msg = "Opening the Cave of Wonders\u2026"
            return {"ok": True, "say": msg, "receipt": msg, "undo": None, "act": "open_cockpit", "campaign_act": True, "read_only": False, "model_called": False, "open_url": "/high-seat"}
        rm_path, rm = _load_rm_fast(folder)
        proj = rm.get("roadmap_projection") or []
        hit = _fuzzy_match_item(proj, target_q, prefer_goals=False)
        if hit is not None:
            hname = str(hit.get("name") or hit.get("id"))
            if hit.get("effort_dir"):
                url = "/steward?dir=" + urllib.parse.quote(str(hit["effort_dir"]))
            elif str(hit.get("ref") or "").startswith("project:"):
                pid = str(hit["ref"]).split(":", 1)[1]
                url = "/steward?pid=" + urllib.parse.quote(pid)
            elif acts._own_group(hit) is not None:
                # Goal: check if it has a child project/effort component
                gid = str(hit.get("id"))
                child = next((c for c in proj if isinstance(c, dict) and c.get("id") != gid and (c.get("navigation") or {}).get("path") == [gid] and (c.get("effort_dir") or str(c.get("ref") or "").startswith("project:"))), None)
                if child and child.get("effort_dir"):
                    url = "/steward?dir=" + urllib.parse.quote(str(child["effort_dir"]))
                elif child and str(child.get("ref") or "").startswith("project:"):
                    url = "/steward?pid=" + urllib.parse.quote(str(child["ref"]).split(":", 1)[1])
                else:
                    url = "/project/Campaign?open=" + urllib.parse.quote(gid)
            else:
                gid = ((hit.get("navigation") or {}).get("path") or [hit.get("id")])[0]
                url = "/project/Campaign?open=" + urllib.parse.quote(str(gid))
            msg = f"Opening AI Cockpit \u201c{hname}\u201d\u2026"
            return {"ok": True, "say": msg, "receipt": msg, "undo": None, "act": "open_cockpit", "campaign_act": True, "read_only": False, "model_called": False, "open_url": url}

    # 3. Mark next step / item done
    m_done = _MARK_DONE_RX.match(t)
    if m_done:
        is_next = bool(m_done.group(1))
        target_q = (m_done.group(2) or m_done.group(3) or goal or "").strip()
        rm_path, rm = _load_rm_fast(folder)
        proj = rm.setdefault("roadmap_projection", [])
        hit = _fuzzy_match_item(proj, target_q, prefer_goals=is_next) if target_q else None
        if hit is not None and acts._own_group(hit) is not None:
            gid = str(hit.get("id"))
            children = [c for c in proj if isinstance(c, dict) and c.get("id") != gid and (c.get("navigation") or {}).get("path") == [gid] and c.get("status") not in ("done", "withdrawn")]
            hit = next((c for c in children if (c.get("navigation") or {}).get("current")), children[0] if children else None)
        if hit is None and not target_q:
            hit = next((c for c in proj if isinstance(c, dict) and acts._own_group(c) is None and c.get("seat") == "active" and c.get("status") != "done"), None)
        if hit is not None and acts._own_group(hit) is None:
            sid = str(hit.get("id"))
            sname = str(hit.get("name") or sid)
            old_st = str(hit.get("status") or "proposed")
            hit["status"] = "done"
            hit.pop("waiting_on", None)
            _append_rm_event(rm, "status_flip", sid, to="done", **{"from": old_st}, goal_reread="reaffirmed", receipt={"who": "john", "when": str(today_dt), "why": "Marked done via Steward fast command"})
            _save_rm_fast(rm_path, rm)
            msg = f"\u2713 Marked \u201c{sname}\u201d done."
            return {"ok": True, "say": msg, "receipt": msg, "undo": {"act": "reopen_step", "step": sid, "old_status": old_st}, "act": "mark_done", "campaign_act": True, "read_only": False, "model_called": False}

    # 4. Rearrange / Move / Seat into Active, On Deck, Not Active (Inactive), Tier 1/2/3, or Horizon (Today / Week / Month / Quarter / Year)
    m_re = _REARRANGE_RX.match(t)
    if m_re or force_goal_seat:
        if m_re:
            raw_targets = m_re.group(1).strip()
            dest = _norm(m_re.group(2))
        else:
            # Fallback when say_campaign returned "a goal has no seat"
            raw_targets = t
            dest = "on deck" if "deck" in _norm(t) else ("not active" if any(k in _norm(t) for k in ("inactive", "not active", "bench", "home", "back")) else "active")
        # Only intercept standard single-component seat commands if force_goal_seat or from_cave or natural phrasing not covered by legacy test expectations
        rm_path, rm = _load_rm_fast(folder)
        proj = rm.setdefault("roadmap_projection", [])
        parts_raw = [p.strip() for p in re.split(r"\s*(?:,|\band\b)\s*", raw_targets) if p.strip()]
        moved_msgs = []
        last_undo = None
        for part_q in parts_raw:
            hit = _fuzzy_match_item(proj, part_q, prefer_goals=dest.startswith("tier"))
            if hit is None:
                continue
            is_goal = acts._own_group(hit) is not None
            if dest.startswith("tier"):
                tnum = int(re.search(r"[123]", dest).group(0))
                g_obj = hit if is_goal else next((g for g in proj if isinstance(g, dict) and g.get("id") == ((hit.get("navigation") or {}).get("path") or [None])[0]), None)
                if g_obj is not None:
                    old_t = g_obj.get("tier")
                    g_obj["tier"] = tnum
                    _append_rm_event(rm, "step_set", str(g_obj["id"]), fields={"tier": tnum})
                    moved_msgs.append(f"\u201c{g_obj.get('name') or g_obj['id']}\u201d \u2192 Tier {tnum}")
                    last_undo = {"act": "move_tier", "step": g_obj["id"], "tier": old_t or 2}
                continue
            if dest in ("today", "this week", "this month", "this quarter", "this year"):
                from datetime import timedelta
                days_map = {"today": 0, "this week": 5, "this month": 25, "this quarter": 75, "this year": 180}
                due_str = str(today_dt + timedelta(days=days_map.get(dest, 0)))
                if is_goal:
                    hit["pace"] = due_str
                    _append_rm_event(rm, "step_set", str(hit["id"]), fields={"pace": due_str})
                else:
                    hit["due"] = due_str
                    _append_rm_event(rm, "step_set", str(hit["id"]), fields={"due": due_str})
                if dest in ("today", "this week"):
                    dest = "active" if dest == "today" else "on deck"
                else:
                    moved_msgs.append(f"\u201c{hit.get('name') or hit['id']}\u201d scheduled for {dest.title()} ({due_str})")
                    continue
            # Seat change: active / on deck / inactive
            target_comp = hit
            if is_goal:
                gid = str(hit.get("id"))
                gname = str(hit.get("name") or gid)
                children = [c for c in proj if isinstance(c, dict) and c.get("id") != gid and (c.get("navigation") or {}).get("path") == [gid] and c.get("status") not in ("done", "withdrawn")]
                if dest in ("not active", "inactive", "off active", "bench", "home", "back"):
                    seated_children = [c for c in children if c.get("seat") in ("active", "deck")]
                    for sc in seated_children:
                        old_s = sc.get("seat")
                        sc.pop("seat", None)
                        sc.pop("seat_order", None)
                        _append_rm_event(rm, "step_set", str(sc["id"]), fields={"seat": None, "seat_order": None})
                        last_undo = {"act": "seat", "step": sc["id"], "seat": old_s or "active"}
                    moved_msgs.append(f"\u201c{gname}\u201d moved to Inactive")
                    continue
                target_comp = next((c for c in children if str(c.get("ref") or "").startswith(("project:", "effort:")) or c.get("effort_dir")), children[0] if children else None)
                if target_comp is None:
                    # Auto-create primary cockpit component for this goal
                    cid = f"{gid}-cockpit"
                    target_comp = {
                        "id": cid,
                        "name": f"{gname} Cockpit",
                        "status": "active",
                        "done_when": hit.get("done_when"),
                        "navigation": {"path": [gid], "current": True},
                    }
                    proj.append(target_comp)
                    _append_rm_event(rm, "step_create", cid, name=target_comp["name"], status="active")
                    _append_rm_event(rm, "step_set", cid, fields={"navigation": {"path": [gid]}})
            cid = str(target_comp.get("id"))
            cname = str(target_comp.get("name") or cid)
            old_seat = target_comp.get("seat")
            if dest in ("not active", "inactive", "off active", "bench", "home", "back"):
                target_comp.pop("seat", None)
                target_comp.pop("seat_order", None)
                _append_rm_event(rm, "step_set", cid, fields={"seat": None, "seat_order": None})
                moved_msgs.append(f"\u201c{cname}\u201d moved to Inactive")
                last_undo = {"act": "seat", "step": cid, "seat": old_seat or "active"}
            else:
                new_seat = "deck" if "deck" in dest else "active"
                put_first = any(k in dest for k in ("top", "first")) or "first" in _norm(t) or "top" in _norm(t)
                others = [x for x in proj if isinstance(x, dict) and x.get("seat") == new_seat and x.get("id") != cid]
                others.sort(key=lambda x: int(x.get("seat_order") or 0))
                if put_first:
                    others.insert(0, target_comp)
                else:
                    others.append(target_comp)
                target_comp["seat"] = new_seat
                for idx, item in enumerate(others):
                    item["seat_order"] = idx
                _append_rm_event(rm, "step_set", cid, fields={"seat": new_seat, "seat_order": target_comp["seat_order"]})
                label = "Active (Priority #1)" if (new_seat == "active" and put_first) else ("Active" if new_seat == "active" else "On Deck")
                moved_msgs.append(f"\u201c{cname}\u201d seated in {label}")
                last_undo = {"act": "seat", "step": cid, "seat": old_seat} if old_seat in ("active", "deck") else {"act": "home", "step": cid}
        if moved_msgs:
            _save_rm_fast(rm_path, rm)
            msg = "Updated immediately: " + "; ".join(moved_msgs) + "."
            return {
                "ok": True,
                "say": msg,
                "receipt": msg,
                "undo": last_undo,
                "act": "campaign_activate",
                "campaign_act": True,
                "read_only": False,
                "model_called": False,
            }
    return None

