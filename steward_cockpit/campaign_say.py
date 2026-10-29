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
        return fast_steward_command(folder, text, goal=goal)
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

_CONV_PREFIX_RX = re.compile(
    r"^(?:(?:hey|hi|hello|okay|ok|alright|so|well)(?:\s+steward|\s+jarvis|\s+aladdin)?[\s,.:;\-]+)*"
    r"(?:(?:please|can you|could you|would you|you can|let'?s|i want to|i'd like to|we can|we should|go ahead and|just|help me)\s+)+",
    re.I,
)

_CREATE_COCKPIT_RX = re.compile(
    r"^(?:create|make|start|spin up|launch|build|add|set up|open up)\s+"
    r"(?:a\s+|an\s+)?(?:new\s+)?(?:(?:ai\s+)?cockpit|one|project|effort|initiative|tile)"
    r"(?:\s+(?:for|called|named|on|about|to|with)\s*[:\-]?\s*|\s*[:\-]\s*|\s+)(.+?)\s*[.!?]?$",
    re.I,
)
_CREATE_BARE_RX = re.compile(
    r"^(?:create|make|start|spin up|launch|build|add|set up)\s+"
    r"(?:a\s+|an\s+)?(?:new\s+)?(?:(?:ai\s+)?cockpit|one|tile)\s*[.!?]?$",
    re.I,
)
_OPEN_COCKPIT_RX = re.compile(
    r"^(?:open|launch|go to|take me to|pull up|switch to|show me)\s+"
    r"(?:the\s+)?(?:ai\s+)?(?:cockpit\s+(?:for|on|of)\s+)?(.+?)(?:\s+ai)?(?:\s+cockpit|\s+project|\s+goal|\s+tile)?\s*[.!?]?$",
    re.I,
)
_ARCHIVE_DONE_RX = re.compile(
    r"^(?:archive|retire|shelve|close|clear|remove|drop|dismiss|put away|unseat|"
    r"(?:we'?re\s+|i'?m\s+)?done\s+with|finish\s+with|take\s+off)"
    r"(?:\s+this(?:\s+one|\s+cockpit|\s+tile|\s+project)?)?"
    r"(?:\s+(?:with|for|on|called|named))?\s*(.*?)"
    r"(?:\s+(?:for now|off the board|off the deck|off active|from active|from on deck|from the board|from the deck))?\s*[.!?]?$",
    re.I,
)
_ELEVATE_UP_RX = re.compile(
    r"^(?:elevate|promote|bump(?:\s+up)?|move\s+up|push\s+up|bring\s+up|raise|prioritize|make\s+top\s+priority)"
    r"(?:\s+this(?:\s+one|\s+cockpit|\s+tile|\s+goal)?)?"
    r"(?:\s+(?:with|for|on))?\s*(.*?)"
    r"(?:\s+(?:up|to active|into active|to the top|to tier\s*([123])))?\s*[.!?]?$",
    re.I,
)
_DEMOTE_DOWN_RX = re.compile(
    r"^(?:demote|lower|move\s+down|push\s+down|send\s+down|drop\s+down|deprioritize)"
    r"(?:\s+this(?:\s+one|\s+cockpit|\s+tile|\s+goal)?)?"
    r"(?:\s+(?:with|for|on))?\s*(.*?)"
    r"(?:\s+(?:down|to on deck|to deck|into on deck|off the board|off active|to tier\s*([123])))?\s*[.!?]?$",
    re.I,
)
_MOVE_DOWN_INFIX_RX = re.compile(
    r"^(?:move|push|send|drop|shift|take)\s+(.+?)\s+(down|up)(?:\s+to\s+(on deck|deck|active|inactive|off the board|tier\s*[123]))?\s*[.!?]?$",
    re.I,
)
_MARK_DONE_RX = re.compile(
    r"^(?:mark|check off|complete|finish|tick)(?:\s+the)?\s+"
    r"(?:(next\s+step)(?:\s+(?:done|complete|completed|off))?(?:\s+(?:on|for|in)\s+(.+?))?|(.+?)\s+(?:as\s+)?(?:done|complete|completed|off)(?:\s+for\s+now)?)\s*[.!?]?$",
    re.I,
)
_REARRANGE_RX = re.compile(
    r"^(?:rearrange(?:\s+the\s+priority\s+of)?(?:\s+and)?\s+)?"
    r"(?:put|move|set|make|shift|promote|demote|elevate|rearrange|prioritize|place|seat|send|take|archive)\s+"
    r"(.+?)\s+(?:into|in|to|on|onto|as|at|under|off|from)?\s*"
    r"(active|top of active|first in active|first|on deck|deck|not active|inactive|off active|off the board|off the deck|bench|home|back|"
    r"tier\s*[123]|today|this week|this month|this quarter|this year)\s*[.!?]?$",
    re.I,
)

_CLAUSE_SPLIT_RX = re.compile(
    r"\s*(?:;|\band\s+then\b|,\s*then\b|,\s*(?:and\s+)?(?=(?:let'?s|please|can you|you can|we can|archive|elevate|promote|demote|move|put|set|make|create|start|spin up|launch|open|mark|finish|complete|remove|drop|take|bench)\b)|\band\s+(?=(?:let'?s|please|can you|you can|we can|archive|elevate|promote|demote|move|put|set|make|create|start|spin up|launch|open|mark|finish|complete|remove|drop|take|bench)\b))\s*",
    re.I,
)


def _strip_conv_prefix(s: str) -> str:
    t = " ".join(str(s or "").split()).strip()
    for _ in range(3):
        nt = _CONV_PREFIX_RX.sub("", t).strip()
        if nt == t:
            break
        t = nt
    return t


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


_FUZZY_NOISE_WORDS = {
    "the", "and", "for", "with", "from", "that", "this", "what", "when", "where", "which",
    "who", "how", "why", "can", "will", "would", "could", "should", "might", "may", "let",
    "make", "put", "set", "get", "use", "try", "see", "out", "new", "one", "two", "three",
    "not", "all", "way", "day", "now", "our", "your", "his", "her", "its", "are", "was",
    "were", "been", "have", "has", "had", "into", "onto", "upon", "over", "under", "about",
    "some", "more", "very", "just", "like", "also", "then", "than", "here", "there", "want",
    "need", "think", "know", "help", "work", "good", "best", "free", "open", "high", "seat",
    "level", "purpose", "reference", "exist", "does", "target", "october", "oct", "step",
}


def _fuzzy_match_item(proj: list, query: str, prefer_goals: bool = False):
    from . import campaign_acts as acts
    q = _norm(query)
    q = re.sub(r"\b(the|a|an|this|that|one|cockpit|ai cockpit|project|goal|initiative|tile|tier|in|into|to|on|for|with|from|board|deck)\b", " ", q)
    q = " ".join(q.split())
    if not q or len(q.split()) > 10:
        return None
    goals = [s for s in proj if isinstance(s, dict) and acts._own_group(s) is not None]
    comps = [s for s in proj if isinstance(s, dict) and acts._own_group(s) is None and s.get("status") != "withdrawn"]
    pool = (goals + comps) if prefer_goals else (comps + goals)
    for s in pool:
        if _norm(s.get("id") or "") == q or _norm(s.get("name") or "") == q:
            return s
    q_words = [w for w in q.split() if len(w) >= 3 and w not in _FUZZY_NOISE_WORDS]
    for s in pool:
        nm = _norm(s.get("name") or "")
        sid = _norm(s.get("id") or "")
        if (len(q) >= 4 and (q in nm or q in sid)) or (q_words and any(w in nm.split() for w in q_words)):
            return s
    return None



_FLEET_BRIEF_RX = re.compile(
    r"^(?:hey\s+|aladdin[,\s]+|steward[,\s]+)*(?:what(?:'s| is)\s+(?:ready\s+for\s+(?:my\s+)?(?:input|review)|going\s+on(?:\s+across\s+all\s+cockpits)?|waiting\s+on\s+me)|which\s+cockpits?\s+are\s+ready(?:\s+for\s+(?:my\s+)?(?:input|review))?|brief\s+me(?:\s+on\s+(?:all\s+)?(?:the\s+)?cockpits)?|status\s+of\s+(?:all\s+)?(?:the\s+)?cockpits|coordinate\s+(?:the\s+)?cockpits)\s*[.!?]*$",
    re.I,
)

_OPEN_DELIV_RX = re.compile(
    r"^(?:hey\s+|oh\s+|aladdin[,\s]+|please\s+)*(?:open(?:\s+this)?(?:\s+up)?(?:\s+for\s+me)?[,\s]+let\s+me\s+see\s+the\s+deliverable(?:\s+for\s+(.+?))?|(?:open(?:\s+up)?|show\s+me|let\s+me\s+see)\s+(?:the\s+)?(?:latest\s+|current\s+|top\s+)?deliverables?(?:\s+(?:for|in|on|from)\s+(.+?))?|open\s+(.+?)\s+deliverables?)\s*[.!?]*$",
    re.I,
)

_FEEDBACK_RELAY_RX = re.compile(
    r"^(?:okay[,\s]+|ok[,\s]+|hey[,\s]+|aladdin[,\s]+)*(?:(?:this\s+is\s+|here\s+is\s+)?my\s+feedback\s+on\s+(?:the\s+deliverable\s+for\s+)?(.+?)\s*(?:is|:|-)\s*(.+)|feedback\s+(?:on|for)\s+(.+?)\s*(?:is|:|-)\s*(.+)|tell\s+(?:the\s+)?(.+?)\s+steward\s+(?:to\s+|that\s+)?(.+)|tell\s+(.+?)\s+to\s+(.+))\s*$",
    re.I,
)

_APPROVE_COCKPIT_RX = re.compile(
    r"^(?:okay[,\s]+|ok[,\s]+|hey[,\s]+)*(?:approve|sign\s+off\s+on|mark\s+review\s+done\s+(?:for|on))\s+(?:the\s+)?(?:deliverables?\s+(?:for|in|on)\s+)?(.+?)\s*[.!?]*$",
    re.I,
)

_LAST_INSPECTED_COCKPIT = {}


def _resolve_cockpit_step_and_dir(folder, step):
    from urllib.parse import unquote
    ref = str(step.get("ref") or "").strip()
    pid, rel_dir = "", ""
    if ref.startswith("effort:"):
        body = ref[len("effort:"):]
        if "/" in body:
            pid, rel_dir = body.split("/", 1)
            rel_dir = unquote(rel_dir)
        else:
            pid = body
    elif ref.startswith("project:"):
        pid = ref[len("project:"):].split("/", 1)[0]
    if not pid:
        if step.get("effort_dir") and Path(str(step.get("effort_dir"))).is_dir():
            return str(step.get("effort_dir")), "", ""
        return None, "", ""
    try:
        import rnd_registry as _rnd
        proj_info = _rnd.get_project(pid) or {}
        base_path = proj_info.get("folder_path") or proj_info.get("path") or proj_info.get("folder") or ""
        if not base_path:
            return None, pid, rel_dir
        cdir = Path(base_path) / rel_dir if rel_dir else Path(base_path)
        if cdir.is_dir():
            return str(cdir), pid, rel_dir
    except Exception:
        pass
    return None, pid, rel_dir


def build_fleet_brief(folder):
    """Coordinate across all seated AI Cockpit stewards on the Cave of Wonders board."""
    from urllib.parse import quote
    from . import steward_campaign as sc
    _, rm = _load_rm_fast(folder)
    proj = rm.get("roadmap_projection") or []
    seated = [s for s in proj if isinstance(s, dict) and s.get("seat") in ("active", "deck") and s.get("status") not in ("done", "withdrawn")]
    seated.sort(key=lambda s: (0 if s.get("seat") == "active" else 1, int(s.get("seat_order") or 0)))
    items = []
    ready_names = []
    running_names = []
    for s in seated:
        cdir, pid, rel_dir = _resolve_cockpit_step_and_dir(folder, s)
        cname = str(s.get("name") or s.get("id") or "Cockpit")
        seat_kind = str(s.get("seat") or "active")
        cockpit_url = f"/steward/v1?pid={quote(pid)}&dir={quote(rel_dir)}" if pid else ""
        entry = {
            "step_id": s.get("id"),
            "name": cname,
            "seat": seat_kind,
            "pid": pid,
            "dir": rel_dir,
            "cdir": cdir or "",
            "cockpit_url": cockpit_url,
            "review_count": 0,
            "waiting_on_you": "",
            "top_deliverable_title": "",
            "top_deliverable_url": "",
            "top_deliverable_path": "",
            "running": False,
            "doing": "Idle",
            "eta": "",
        }
        if cdir:
            try:
                deliv = sc.read_deliverables(cdir)
                cur_items = [it for it in (deliv.get("items") or []) if isinstance(it, dict) and it.get("is_current") and not it.get("reviewed_done")]
                all_items = [it for it in (deliv.get("items") or []) if isinstance(it, dict) and it.get("path")]
                entry["review_count"] = len(cur_items)
                top_it = cur_items[0] if cur_items else (all_items[0] if all_items else None)
                if top_it:
                    raw_p = str(top_it.get("open_path") or top_it.get("path") or "")
                    entry["top_deliverable_path"] = raw_p
                    entry["top_deliverable_title"] = str(top_it.get("what") or Path(raw_p).name or "Deliverable")[:90]
                    ext = Path(raw_p).suffix.lower()
                    extra_q = "&view=1" if ext in (".docx", ".pptx", ".xlsx") else ("&render=1" if ext in (".md", ".markdown", ".txt") else "")
                    entry["top_deliverable_url"] = f"/api/steward/deliverable-file?pid={quote(pid)}&dir={quote(rel_dir)}&path={quote(raw_p)}{extra_q}"
            except Exception:
                pass
            try:
                st_path = Path(cdir) / "strip.json"
                if st_path.is_file():
                    st_raw = json.loads(st_path.read_text(encoding="utf-8"))
                    hw = sc._real_wait(str(st_raw.get("human_wait") or ""))
                    entry["waiting_on_you"] = hw
            except Exception:
                pass
            try:
                jobs = sc.running_code_jobs(cdir)
                skills = sc.running_skill_jobs(cdir)
                if jobs or skills:
                    entry["running"] = True
                    if jobs:
                        j0 = jobs[0]
                        mins = int(j0.get("minutes") or 0)
                        rem = max(4, 15 - mins) if mins < 15 else max(4, round(mins * 0.35))
                        entry["doing"] = f"Running {j0.get('title') or 'code job'} ({mins}m elapsed)"
                        entry["eta"] = f"~{rem}m left"
                    else:
                        k0 = skills[-1]
                        entry["doing"] = f"Running {k0.get('label') or 'skill'}"
                        entry["eta"] = "~8m left"
            except Exception:
                pass
        if entry["review_count"] > 0 or entry["waiting_on_you"]:
            ready_names.append(entry)
        elif entry["running"]:
            running_names.append(entry)
        items.append(entry)

    lines = []
    if ready_names:
        lines.append(f"**{len(ready_names)} AI Cockpit{'s' if len(ready_names) != 1 else ''} ready for your input right now:**")
        for r in ready_names[:6]:
            d_link = f" — [{r['top_deliverable_title']}]({r['top_deliverable_url']})" if r["top_deliverable_url"] else ""
            wait_note = f" ({r['review_count']} for review)" if r["review_count"] else (f" ({r['waiting_on_you'][:70]})" if r["waiting_on_you"] else "")
            lines.append(f"- **{r['name']}**{wait_note}{d_link}")
    if running_names:
        lines.append(f"**{len(running_names)} AI Cockpit{'s' if len(running_names) != 1 else ''} actively running:**")
        for rn in running_names[:4]:
            lines.append(f"- **{rn['name']}**: {rn['doing']} · ETA {rn['eta']}")
    if not ready_names and not running_names:
        lines.append(f"All **{len(items)} seated AI Cockpits** are currently caught up and waiting on your next command.")
    lines.append("Say **“open the deliverable for <cockpit>”** to inspect it in split-screen, or **“feedback on <cockpit>: <your notes>”** to relay instructions straight to its Steward.")

    spoken_parts = []
    if ready_names:
        top3 = ", ".join(r["name"] for r in ready_names[:3])
        spoken_parts.append(f"{len(ready_names)} cockpits are ready for your review, led by {top3}.")
    if running_names:
        rtop = ", ".join(f"{r['name']} with ETA {r['eta']}" for r in running_names[:2])
        spoken_parts.append(f"{len(running_names)} running now: {rtop}.")
    if not spoken_parts:
        spoken_parts.append(f"All {len(items)} seated cockpits are idle and caught up.")
    spoken_parts.append("Say open the deliverable for any cockpit, or give me your feedback to relay.")
    return {
        "ok": True,
        "items": items,
        "say": "\n".join(lines),
        "spoken_summary": " ".join(spoken_parts),
    }


def relay_to_cockpit_steward(folder, target_query: str, action: str, message: str = "") -> dict:
    """Open a cockpit's deliverable or relay feedback/approval from Cave of Wonders to that cockpit's Steward."""
    brief = build_fleet_brief(folder)
    items = brief.get("items") or []
    q_norm = _norm(target_query or "")
    target = None
    if not q_norm or q_norm in ("this", "it", "that", "the deliverable", "this cockpit"):
        last_id = _LAST_INSPECTED_COCKPIT.get("step_id")
        if last_id:
            target = next((it for it in items if it.get("step_id") == last_id), None)
        if target is None:
            ready = [it for it in items if it.get("review_count", 0) > 0 or it.get("waiting_on_you")]
            target = ready[0] if ready else (items[0] if items else None)
    else:
        for it in items:
            nm = _norm(it.get("name") or "")
            sid = _norm(it.get("step_id") or "")
            dr = _norm(it.get("dir") or "")
            if q_norm == nm or q_norm == sid or q_norm == dr or q_norm in nm or (dr and q_norm in dr):
                target = it
                break
        if target is None:
            q_words = [w for w in q_norm.split() if len(w) >= 2]
            for it in items:
                hay = _norm((it.get("name") or "") + " " + (it.get("dir") or ""))
                if q_words and all(w in hay for w in q_words):
                    target = it
                    break
    if target is None:
        return {"ok": False, "say": f"I could not find a seated AI Cockpit matching “{target_query}”."}

    _LAST_INSPECTED_COCKPIT["step_id"] = target.get("step_id")
    cname = target["name"]
    cdir = target.get("cdir") or ""

    if action == "open_deliverable":
        url = target.get("top_deliverable_url") or target.get("cockpit_url") or ""
        title = target.get("top_deliverable_title") or cname
        if not url:
            return {"ok": False, "say": f"**{cname}** does not have an openable deliverable registered yet."}
        msg = f"Opening **{title}** from **{cname}** in the split-screen viewer. Give me your feedback whenever you are ready, or say **“approve {cname}”** to mark it reviewed."
        return {
            "ok": True,
            "say": msg,
            "receipt": msg,
            "spoken_summary": f"Opening {title} from {cname}. Tell me your feedback when you're ready.",
            "act": "open_deliverable",
            "campaign_act": True,
            "fast": True,
            "read_only": True,
            "model_called": False,
            "open_deliverable_url": url,
            "open_deliverable_title": f"{cname} · {title}",
            "open_deliverable": {"url": url, "title": f"{cname} · {title}"},
            "cockpit_name": cname,
            "step": target.get("step_id"),
        }

    if action == "approve" and cdir:
        from . import steward_campaign as sc
        deliv = sc.read_deliverables(cdir)
        cur_items = [it for it in (deliv.get("items") or []) if isinstance(it, dict) and it.get("is_current") and not it.get("reviewed_done")]
        for it in cur_items:
            sc.dismiss_deliverable(
                cdir,
                path=str(it.get("open_path") or it.get("path") or ""),
                product_id=str(it.get("product_id") or ""),
                what=str(it.get("what") or ""),
                revision_id=str(it.get("revision_id") or ""),
                hash_val=str(it.get("hash") or ""),
            )
        sc.clear_human_wait(cdir)
        msg = f"Marked {len(cur_items) or 'all'} review deliverable(s) Done in **{cname}** and cleared its review gate."
        return {
            "ok": True,
            "say": msg,
            "receipt": msg,
            "spoken_summary": f"Approved {cname} and marked its review deliverables done.",
            "act": "approve_cockpit",
            "campaign_act": True,
            "fast": True,
            "read_only": False,
            "model_called": False,
            "step": target.get("step_id"),
        }

    if action == "feedback" and cdir:
        fb_text = str(message or "").strip()
        if not fb_text:
            return {"ok": False, "say": f"Tell me what feedback you want sent to **{cname}**."}
        dispatched = False
        try:
            from . import steward_routes as sr
            eng = sr.get_engine(cdir, create=True)
            if eng is not None:
                eng.say(f"[Relayed from Cave of Wonders by John]: {fb_text}")
                dispatched = True
        except Exception:
            dispatched = False
        msg = (
            f"Relayed your feedback directly to the **{cname}** Steward: *“{fb_text}”* ? "
            + ("its Steward is now working on those revisions." if dispatched else "queued for its next turn.")
        )
        return {
            "ok": True,
            "say": msg,
            "receipt": msg,
            "spoken_summary": f"Sent your feedback to the {cname} Steward. It is working on your revisions now.",
            "act": "relay_feedback",
            "campaign_act": True,
            "fast": True,
            "read_only": False,
            "model_called": False,
            "step": target.get("step_id"),
        }
    return {"ok": False, "say": f"Could not relay action to **{cname}**."}


def _fast_single_clause(folder, raw_text, goal=None, today_dt=None, from_cave=False, force_goal_seat=False):
    import urllib.parse
    from . import campaign_acts as acts
    orig = " ".join(str(raw_text or "").split())
    t = _strip_conv_prefix(orig)
    if not t:
        return None
    today_dt = today_dt or date.today()

    # 0. Bare "create a new one / cockpit" without a name yet -> instant helpful prompt
    if _CREATE_BARE_RX.match(t):
        msg = "Ready to create a new AI Cockpit immediately — reply with `create a new cockpit for <Name>` (or `under <Goal>`) and I will create and seat it in Active right away."
        return {
            "ok": True,
            "say": msg,
            "receipt": msg,
            "undo": None,
            "act": "create_cockpit_prompt",
            "campaign_act": True,
            "read_only": True,
            "model_called": False,
        }

        # 0. Cross-Cockpit Steward Coordination (Fleet Brief, Open Deliverable in Split-Screen, Relay Feedback / Approve)
    if _FLEET_BRIEF_RX.match(t):
        fb = build_fleet_brief(folder)
        return {
            "ok": True,
            "say": fb["say"],
            "receipt": "Coordinated status across all seated AI Cockpits.",
            "spoken_summary": fb.get("spoken_summary", ""),
            "act": "fleet_brief",
            "campaign_act": True,
            "fast": True,
            "read_only": True,
            "model_called": False,
        }
    m_od = _OPEN_DELIV_RX.match(t)
    if m_od:
        q_c = (m_od.group(1) or m_od.group(2) or m_od.group(3) or "").strip()
        return relay_to_cockpit_steward(folder, q_c, "open_deliverable")
    m_fb = _FEEDBACK_RELAY_RX.match(t)
    if m_fb:
        q_c = (m_fb.group(1) or m_fb.group(3) or m_fb.group(5) or m_fb.group(7) or "").strip()
        msg_c = (m_fb.group(2) or m_fb.group(4) or m_fb.group(6) or m_fb.group(8) or "").strip()
        return relay_to_cockpit_steward(folder, q_c, "feedback", msg_c)
    m_ap = _APPROVE_COCKPIT_RX.match(t)
    if m_ap:
        q_c = (m_ap.group(1) or "").strip()
        return relay_to_cockpit_steward(folder, q_c, "approve")

    # 1. Create a new AI Cockpit / "let's create a new one for X"
    m_create = _CREATE_COCKPIT_RX.match(t)
    if m_create:
        raw_rest = m_create.group(1).strip().strip("\"'“”‘’")
        if raw_rest.lower() in ("this", "it", "one", "cockpit", "ai cockpit", "project"):
            msg = "Ready to create a new AI Cockpit — say `create a new cockpit for <Name>` and I will spin it up in Active immediately."
            return {"ok": True, "say": msg, "receipt": msg, "undo": None, "act": "create_cockpit_prompt", "campaign_act": True, "read_only": True, "model_called": False}
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
        open_url = "/steward?dir=" + urllib.parse.quote(str(cockpit_dir))
        msg = f"Created new AI Cockpit \u201c{title}\u201d under {goal_name} and seated it in Active ([Open Cockpit]({open_url}))."
        return {
            "ok": True,
            "say": msg,
            "receipt": f"Created new AI Cockpit \u201c{title}\u201d under {goal_name} and seated it in Active.",
            "undo": {"act": "withdraw", "step": slug},
            "act": "create_cockpit",
            "campaign_act": True,
            "read_only": False,
            "model_called": False,
            "open_url": open_url,
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

    # 3. Convert shorthand conversational verbs ("archive X", "elevate X", "move X down") into canonical rearrange/archive operations
    m_infix = _MOVE_DOWN_INFIX_RX.match(t)
    if m_infix:
        tgt_expr = m_infix.group(1).strip()
        dir_word = m_infix.group(2).lower()
        explicit_dest = (m_infix.group(3) or "").strip().lower()
        if explicit_dest:
            t = f"move {tgt_expr} to {explicit_dest}"
        else:
            rm_path, rm = _load_rm_fast(folder)
            proj = rm.get("roadmap_projection") or []
            hit = _fuzzy_match_item(proj, tgt_expr if tgt_expr.lower() not in ("this", "it") else (goal or ""), prefer_goals=False)
            if hit is not None:
                if dir_word == "down":
                    cur_s = hit.get("seat")
                    t = f"move {hit.get('name') or hit.get('id')} to {'on deck' if cur_s == 'active' else 'inactive'}"
                else:
                    t = f"move {hit.get('name') or hit.get('id')} to top of active"

    m_elev = _ELEVATE_UP_RX.match(t)
    if m_elev and not _REARRANGE_RX.match(t):
        tgt_expr = (m_elev.group(1) or goal or "").strip()
        tier_num = m_elev.group(2)
        if tgt_expr.lower() in ("this", "it", "this one", "that"):
            tgt_expr = goal or ""
        if tgt_expr:
            t = f"move {tgt_expr} to {'tier ' + tier_num if tier_num else 'top of active'}"
        else:
            rm_path, rm = _load_rm_fast(folder)
            proj = rm.get("roadmap_projection") or []
            deck_first = next((x for x in proj if isinstance(x, dict) and x.get("seat") == "deck"), None)
            if deck_first:
                t = f"move {deck_first.get('name') or deck_first.get('id')} to top of active"

    m_dem = _DEMOTE_DOWN_RX.match(t)
    if m_dem and not _REARRANGE_RX.match(t):
        tgt_expr = (m_dem.group(1) or goal or "").strip()
        tier_num = m_dem.group(2)
        if tgt_expr.lower() in ("this", "it", "this one", "that"):
            tgt_expr = goal or ""
        if tgt_expr:
            rm_path, rm = _load_rm_fast(folder)
            proj = rm.get("roadmap_projection") or []
            hit = _fuzzy_match_item(proj, tgt_expr, prefer_goals=False)
            if tier_num:
                t = f"move {tgt_expr} to tier {tier_num}"
            elif hit and hit.get("seat") == "active":
                t = f"move {hit.get('name') or hit.get('id')} to on deck"
            else:
                t = f"move {tgt_expr} to inactive"

    m_arch = _ARCHIVE_DONE_RX.match(t)
    if m_arch and not _REARRANGE_RX.match(t) and not _MARK_DONE_RX.match(t):
        tgt_expr = (m_arch.group(1) or goal or "").strip()
        if tgt_expr.lower() in ("this", "it", "this one", "that", "for now"):
            tgt_expr = goal or ""
        if tgt_expr:
            t = f"move {tgt_expr} to inactive"
        else:
            # If said on the Cave without naming which tile, archive the last/current active or deck tile if only 1, else ask clearly
            rm_path, rm = _load_rm_fast(folder)
            proj = rm.get("roadmap_projection") or []
            seated_all = [x for x in proj if isinstance(x, dict) and x.get("seat") in ("active", "deck")]
            if len(seated_all) == 1:
                t = f"move {seated_all[0].get('name') or seated_all[0].get('id')} to inactive"
            else:
                names = ", ".join(f"\u201c{x.get('name') or x.get('id')}\u201d" for x in seated_all[:6]) or "none currently seated"
                msg = f"Which cockpit would you like to archive/move off the board? Currently on the board: {names}. (Say `archive <Name>` or click `\u2713 Done` on its tile.)"
                return {"ok": True, "say": msg, "receipt": msg, "undo": None, "act": "archive_prompt", "campaign_act": True, "read_only": True, "model_called": False}

    # 4. Mark next step / item done (and unseat if it is a seated cockpit tile!)
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
            old_seat = hit.get("seat")
            hit["status"] = "done"
            hit.pop("waiting_on", None)
            if old_seat in ("active", "deck") and not is_next:
                hit.pop("seat", None)
                hit.pop("seat_order", None)
                _append_rm_event(rm, "step_set", sid, fields={"seat": None, "seat_order": None})
            _append_rm_event(rm, "status_flip", sid, to="done", **{"from": old_st}, goal_reread="reaffirmed", receipt={"who": "john", "when": str(today_dt), "why": "Marked done via Steward fast command"})
            _save_rm_fast(rm_path, rm)
            msg = f"\u2713 Marked \u201c{sname}\u201d done" + (" and moved it off the board." if (old_seat in ("active", "deck") and not is_next) else ".")
            return {"ok": True, "say": msg, "receipt": msg, "undo": {"act": "reopen_step", "step": sid, "old_status": old_st, "old_seat": old_seat}, "act": "mark_done", "campaign_act": True, "read_only": False, "model_called": False}

    # 5. Rearrange / Move / Seat into Active, On Deck, Not Active (Inactive), Tier 1/2/3, or Horizon (Today / Week / Month / Quarter / Year)
    m_re = _REARRANGE_RX.match(t)
    if m_re or force_goal_seat:
        if m_re:
            raw_targets = m_re.group(1).strip()
            dest = _norm(m_re.group(2))
        else:
            raw_targets = t
            dest = "on deck" if "deck" in _norm(t) else ("not active" if any(k in _norm(t) for k in ("inactive", "not active", "bench", "home", "back", "off")) else "active")
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
            target_comp = hit
            if is_goal:
                gid = str(hit.get("id"))
                gname = str(hit.get("name") or gid)
                children = [c for c in proj if isinstance(c, dict) and c.get("id") != gid and (c.get("navigation") or {}).get("path") == [gid] and c.get("status") not in ("done", "withdrawn")]
                if dest in ("not active", "inactive", "off active", "off the board", "off the deck", "bench", "home", "back"):
                    seated_children = [c for c in children if c.get("seat") in ("active", "deck")]
                    for sc in seated_children:
                        old_s = sc.get("seat")
                        sc.pop("seat", None)
                        sc.pop("seat_order", None)
                        _append_rm_event(rm, "step_set", str(sc["id"]), fields={"seat": None, "seat_order": None})
                        last_undo = {"act": "seat", "step": sc["id"], "seat": old_s or "active"}
                    moved_msgs.append(f"\u201c{gname}\u201d moved off the board (Inactive)")
                    continue
                target_comp = next((c for c in children if str(c.get("ref") or "").startswith(("project:", "effort:")) or c.get("effort_dir")), children[0] if children else None)
                if target_comp is None:
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
            if dest in ("not active", "inactive", "off active", "off the board", "off the deck", "bench", "home", "back"):
                target_comp.pop("seat", None)
                target_comp.pop("seat_order", None)
                _append_rm_event(rm, "step_set", cid, fields={"seat": None, "seat_order": None})
                moved_msgs.append(f"\u201c{cname}\u201d moved off the board (Inactive)")
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


_BRAINSTORM_DISCUSSION_RX = re.compile(
    r"\b(?:brainstorm|brainstorming|brain\s+dump|what\s+do\s+you\s+think|let\s+me\s+know\s+what\s+you\s+think|"
    r"help\s+me\s+think|the\s+idea\s+(?:of|is)|i\s+need\s+to\s+know|how\s+do\s+i\s+actually|"
    r"gofundme|non\s*-?profit|philanthrop\w*|school\s+district|"
    r"token\s+compression|context\s+compression|llmlingua|kvzip|headkv|round[\s\-]*2\s+plan)\b",
    re.I,
)

_EXPLICIT_SHORT_BOARD_CMD_RX = re.compile(
    r"^(?:open|activate|seat|move|put|archive|elevate|bench|send|park|unpark|mark)\b",
    re.I,
)


def fast_steward_command(folder, text, goal=None, today=None, from_cave=False, force_goal_seat=False):
    """Sub-20ms pure-Python execution for single or multi-clause natural-language Cave of Wonders & Star Chart Steward commands."""
    t = " ".join(str(text or "").split())
    if not t:
        return None
    # Never hijack long brainstorming / strategic discussion turns into board rearrangement verbs,
    # while preserving short explicit board commands like "open the u-osts cockpit".
    if not _FEEDBACK_RELAY_RX.match(t):
        if len(t.split()) > 35:
            return None
        if _BRAINSTORM_DISCUSSION_RX.search(t) and not (len(t.split()) <= 10 and _EXPLICIT_SHORT_BOARD_CMD_RX.match(t)):
            return None
    today_dt = today or date.today()
    clauses = [c.strip() for c in _CLAUSE_SPLIT_RX.split(t) if c and c.strip()]
    if len(clauses) > 1:
        results = []
        for cl in clauses:
            r = _fast_single_clause(folder, cl, goal=goal, today_dt=today_dt, from_cave=from_cave, force_goal_seat=force_goal_seat)
            if r is not None and r.get("ok"):
                results.append(r)
        if results:
            combined_say = " ".join(r.get("say") or r.get("receipt") or "" for r in results if (r.get("say") or r.get("receipt"))).strip()
            combined_receipt = " ".join(r.get("receipt") or r.get("say") or "" for r in results if (r.get("receipt") or r.get("say"))).strip()
            last = results[-1]
            return {
                "ok": True,
                "say": combined_say,
                "receipt": combined_receipt,
                "undo": last.get("undo"),
                "act": last.get("act") or "campaign_activate",
                "campaign_act": True,
                "read_only": all(bool(r.get("read_only")) for r in results),
                "model_called": False,
                "open_url": next((r.get("open_url") for r in reversed(results) if r.get("open_url")), None),
                "step": next((r.get("step") for r in reversed(results) if r.get("step")), None),
            }
    return _fast_single_clause(folder, t, goal=goal, today_dt=today_dt, from_cave=from_cave, force_goal_seat=force_goal_seat)


_ANVIL_REPORT_RE = re.compile(
    r"\b(?:anvil|anvil[_\-\s]?report|code\s+walkthrough|null\s+space|essential\s+core|paper[-\s]to[-\s]code)\b",
    re.I,
)

_TOPIC_EFFORT_HINTS = [
    (
        re.compile(
            r"\b(?:u-osts|osts|gwl-free|gwl\s+free|open\s+source\s+token\s+source|"
            r"token\s+compression|context\s+compression|llmlingua|kvzip|headkv)\b",
            re.I,
        ),
        "Open Source Token Source / Basic Infastructure (U-OSTS & GWL-Free)",
        str(Path(__file__).resolve().parent.parent.parent / "Open Source Token Source" / "Basic Infastructure"),
    ),
    (
        re.compile(r"\b(?:hierarchical\s+normalizing\s+flows|hnf|paper\s*1|normalizing\s+flow)\b", re.I),
        "Hierarchical Normalizing Flows / Paper 1",
        str(Path(__file__).resolve().parent.parent.parent / "Hierarchical Normalizing Flows" / "Paper 1"),
    ),
    (
        re.compile(r"\b(?:book\s*1|chekhov|thriller\s+novel|artificial\s+magi)\b", re.I),
        "Writing - Thriller Novel / Book 1",
        str(Path(__file__).resolve().parent.parent.parent / "Writing - Thriller Novel" / "Book 1"),
    ),
]


def _campaign_scope_prompt_block(cdir, text: str) -> str:
    """Return a mandatory Campaign/Effort Scope Guard block when a prompt on Campaign or Cave of Wonders
    addresses a specific topic/initiative, ensuring the Steward NEVER hijacks the turn into an unrelated
    sub-campaign that happens to be listed in strip.json."""
    raw = str(text or "").strip()
    if not raw:
        return ""
    matches = []
    matched_labels = []
    for rx, label, target_dir in _TOPIC_EFFORT_HINTS:
        if rx.search(raw):
            matches.append(f"{label} ({target_dir})")
            matched_labels.append(label)
    cdir_str = str(cdir or "")
    if not matches and not (is_campaign_folder(cdir_str) or is_cave_folder(cdir_str)):
        return ""
    focus_line = (
        "Target initiative(s) detected from John's words: " + "; ".join(matches) + ". "
        if matches
        else "Answer strictly within the initiative or topic John named in this message. "
    )
    unrelated_example = (
        "unrelated projects in strip.json"
        if any("Book 1" in lbl for lbl in matched_labels)
        else "Book 1 / Chekhov or any other unrelated project in strip.json"
    )
    return (
        "\n\n[CAMPAIGN / EFFORT SCOPE GUARD — MANDATORY]\n"
        + focus_line
        + f"NEVER hijack, redirect, or reinterpret John's message into an unrelated campaign step or cockpit "
        f"(such as {unrelated_example}) that he did not ask about in this turn. "
        "Address ONLY the exact topic, deliverables, and files John is asking about right now."
    )
