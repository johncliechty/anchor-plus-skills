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

DIALOGUE = "file:///C:/dev/Ecgberht/engine/dialogue.mjs"
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
