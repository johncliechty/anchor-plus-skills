"""campaign_acts — what John does on the Campaign page, written into the Campaign's own record through the
engine's writer (the CLI and its spine), each act a receipt with its inverse.

W3c of the High Seat plan (2026-09-26), trimmed by its Rabbit read. Acts: move_tier · rank (up/down within a
tier) · rename · date · park (with its trigger) · unpark · flag / unflag (a native part's "needs you") · add (a
task, or a project part by reference) · promote (a seed, by id → an initiative, with the tier and the area he
picked) · withdraw / restore (the inverse of add and promote: the record is append-only, so a step is never
deleted — its navigation is cleared, which takes it off the board while the ordinary cockpit still shows it;
restore puts the navigation back). A tick on a native part waits on John's word on the close law (PLAN §9.6)
and is refused here with that sentence. The Campaign never writes another record: a date or a flip on a
referenced part is refused by the engine and the refusal is the receipt.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from .campaign_seeds import seed_by_id

ECG = Path(r"C:\dev\Ecgberht\bin\ecgberht.mjs")
SPINE = "file:///C:/dev/Ecgberht/engine/ledger-spine.mjs"
WHO = "john"


def _cli(project, *args):
    r = subprocess.run(["node", str(ECG), *args, "--project", str(project)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    try:
        return json.loads(r.stdout or "{}")
    except Exception:
        return {"ok": False, "error": "engine answered no json", "raw": (r.stdout or r.stderr)[:200]}


def _spine_set(project, step_id, fields):
    js = ("import { appendRoadmapEventThroughSpine } from '%s';"
          "const r = appendRoadmapEventThroughSpine(%s, {kind:'step_set', step_id:%s, fields:%s});"
          "console.log(JSON.stringify({ok:r.ok, error:r.error||null}));") % (
        SPINE, json.dumps(str(project).replace("\\", "/")), json.dumps(step_id), json.dumps(fields))
    r = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        return {"ok": False, "error": (r.stderr or r.stdout)[:200] or "the spine answered nothing"}


def _projection(project):
    try:
        d = json.loads((Path(project) / "roadmap.json").read_text(encoding="utf-8"))
        return d.get("roadmap_projection") or []
    except Exception:
        return []


def _step(project, sid):
    return next((s for s in _projection(project) if s.get("id") == sid), None)


def _own_group(s):
    nav = s.get("navigation") if isinstance(s.get("navigation"), dict) else {}
    return next((g for g in nav.get("groups") or [] if isinstance(g, dict) and g.get("id") == s.get("id") and g.get("parent_id") is None), None)


def _initiatives(project):
    out = []
    for s in _projection(project):
        g = _own_group(s)
        if g is not None:
            out.append((s, g))
    return out


def _parts_of(project, sid):
    out = []
    for p in _projection(project):
        nav = p.get("navigation") if isinstance(p.get("navigation"), dict) else {}
        path = nav.get("path") or []
        if p.get("id") != sid and path and path[0] == sid:
            out.append(p)
    return out


def _slug(text, prefix=""):
    s = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:48].strip("-") or "part"
    return (prefix[:12] + "-" + s) if prefix else s


def _ok(receipt, undo=None, **extra):
    return {"ok": True, "receipt": receipt, "undo": undo, **extra}


def _no(text, **extra):
    return {"ok": False, "receipt": text, **extra}


def _write_nav(project, s, order=None):
    """Write the heading step's navigation back whole, with only its own group's order changed."""
    nav = dict(s.get("navigation") or {})
    groups = [dict(g) for g in nav.get("groups") or []]
    for g in groups:
        if g.get("id") == s.get("id") and order is not None:
            g["order"] = int(order)
    nav["groups"] = groups
    nav.setdefault("path", [s.get("id")])
    return _spine_set(project, s["id"], {"navigation": nav})


def _foot(project, tier, except_id=None):
    return max([int(g.get("order") or 0) for x, g in _initiatives(project) if x.get("tier") == tier and x.get("id") != except_id] or [-1]) + 1


# ── the acts ───────────────────────────────────────────────────────────────────────────────────

def move_tier(project, step, tier, order=None):
    """Move an initiative to a tier: one step_set of its tier, then its place — the foot of that tier, or the
    order the undo carries (so a head of a tier comes back as its head, not at the bottom with a new number)."""
    s = _step(project, step)
    if s is None or _own_group(s) is None:
        return _no("no such goal")
    try:
        tier = int(tier)
    except Exception:
        return _no("a tier is 1, 2 or 3")
    if tier not in (1, 2, 3):
        return _no("a tier is 1, 2 or 3")
    old = s.get("tier")
    old_order = int(_own_group(s).get("order") or 0)
    if old == tier:
        return _no("%s is already in tier %d" % (s.get("name"), tier))
    r = _cli(project, "roadmap-set", "--step", step, "--tier", str(tier))
    if not r.get("ok"):
        return _no("the engine refused: %s" % r.get("error"))
    place = int(order) if order is not None else _foot(project, tier, except_id=step)
    r2 = _write_nav(project, _step(project, step), order=place)
    if not r2.get("ok"):
        return _no("%s moved to tier %d, but its place there was refused: %s — it keeps its old order number" % (s.get("name"), tier, r2.get("error")))
    return _ok("%s moved to tier %d (from %s), %s" % (s.get("name"), tier, ("tier %d" % old) if old else "no tier",
                                                      ("at its foot" if order is None else "back in its place")),
               undo={"act": "move_tier", "step": step, "tier": old, "order": old_order} if old else None)


def rank(project, step, direction):
    """Move an initiative up or down within its tier. The tier is first renumbered to its sorted positions
    (a write only where an order differs — equal orders would otherwise make Up sort later), then the two
    neighbours swap; a refused second write puts the first back."""
    s = _step(project, step)
    if s is None or _own_group(s) is None:
        return _no("no such goal")
    same = sorted([(int(g.get("order") or 0), x) for x, g in _initiatives(project) if x.get("tier") == s.get("tier")], key=lambda t: (t[0], t[1].get("name") or ""))
    idx = next((k for k, (o, x) in enumerate(same) if x.get("id") == step), None)
    if idx is None:
        return _no("not in a tier")
    j = idx - 1 if direction == "up" else idx + 1
    if j < 0 or j >= len(same):
        return _no("%s is already at the %s of its tier — the Tier menu moves it between tiers" % (s.get("name"), "top" if direction == "up" else "foot"))
    for k, (o, x) in enumerate(same):
        if o != k:
            r0 = _write_nav(project, x, order=k)
            if not r0.get("ok"):
                return _no("the tier could not be renumbered: %s" % r0.get("error"))
    mover, other = same[idx][1], same[j][1]
    r1 = _write_nav(project, other, order=idx)
    if not r1.get("ok"):
        return _no("the engine refused: %s" % r1.get("error"))
    r2 = _write_nav(project, mover, order=j)
    if not r2.get("ok"):
        _write_nav(project, other, order=j)
        return _no("the engine refused: %s — nothing moved" % r2.get("error"))
    return _ok("%s moved %s within tier %s, past %s" % (s.get("name"), direction, s.get("tier"), other.get("name")),
               undo={"act": "rank", "step": step, "direction": "down" if direction == "up" else "up"})


def rename(project, step, name):
    s = _step(project, step)
    name = " ".join(str(name or "").split())
    if s is None:
        return _no("no such part")
    if not name:
        return _no("a name is needed")
    r = _cli(project, "roadmap-set", "--step", step, "--name", name)
    if not r.get("ok"):
        return _no("the engine refused: %s" % r.get("error"))
    return _ok("renamed \u2018%s\u2019 to \u2018%s\u2019" % (s.get("name"), name), undo={"act": "rename", "step": step, "name": s.get("name")})


def date(project, step, due):
    s = _step(project, step)
    if s is None:
        return _no("no such part")
    if s.get("ref"):
        return _no("a referenced part takes its date from its own record — set it in that cockpit")
    due = str(due or "").strip() or "none"
    r = _cli(project, "roadmap-set", "--step", step, "--due", due)
    if not r.get("ok"):
        return _no("the engine refused: %s (a date is YYYY-MM-DD)" % r.get("error"))
    old = s.get("due") or "none"
    return _ok("%s now %s" % (s.get("name"), ("due " + due) if due != "none" else "carries no date"), undo={"act": "date", "step": step, "due": old})


def _flip(project, step, status, why, waiting_on=None):
    if waiting_on is not None:
        r0 = _cli(project, "roadmap-set", "--step", step, "--waiting-on", waiting_on)
        if not r0.get("ok"):
            return r0
    return _cli(project, "roadmap-set", "--step", step, "--status", status, "--who", WHO, "--reason", why)


def park(project, step, waiting_on):
    s = _step(project, step)
    if s is None:
        return _no("no such part")
    if s.get("ref"):
        return _no("a referenced part is parked in its own record — open that cockpit")
    trigger = " ".join(str(waiting_on or "").split())
    if not trigger:
        return _no("a park carries its trigger — say until when, or what")
    r = _flip(project, step, "parked", "parked by John on the Campaign until " + trigger, waiting_on=trigger)
    if not r.get("ok"):
        return _no("the engine refused: %s" % r.get("error"))
    return _ok("%s parked until %s" % (s.get("name"), trigger), undo={"act": "unpark", "step": step})


def unpark(project, step):
    s = _step(project, step)
    if s is None:
        return _no("no such part")
    if s.get("ref"):
        return _no("a referenced part is flipped in its own record")
    r = _flip(project, step, "planned", "unparked by John on the Campaign")
    if not r.get("ok"):
        return _no("the engine refused: %s" % r.get("error"))
    return _ok("%s is back in play" % s.get("name"), undo={"act": "park", "step": step, "waiting_on": s.get("waiting_on") or "later"})


def flag(project, step, on=True):
    s = _step(project, step)
    if s is None:
        return _no("no such part")
    if s.get("ref"):
        return _no("a referenced part's wait lives in its own record")
    if on:
        r = _flip(project, step, "waiting", "flagged by John on the Campaign: it needs him", waiting_on="John")
        text = "%s now needs you" % s.get("name")
    else:
        r = _flip(project, step, "planned", "unflagged by John on the Campaign")
        text = "%s no longer waits on you" % s.get("name")
    if not r.get("ok"):
        return _no("the engine refused: %s" % r.get("error"))
    return _ok(text, undo={"act": "unflag" if on else "flag", "step": step})


def tick(project, step):
    return _no("a tick on a native part waits on your word on the close law — the question in the approval; say it and the tick lands")


def add(project, initiative, kind, text, due=None, project_id=None):
    head = _step(project, initiative)
    if head is None or _own_group(head) is None:
        return _no("no such goal")
    kind = str(kind or "task")
    text = " ".join(str(text or "").split())
    if kind == "project":
        if not project_id:
            return _no("which project?")
        ref = "project:%s" % project_id
        text = text or ("%s (the project)" % project_id[:8])
        sid = _slug(text, initiative)
        r = _cli(project, "roadmap-propose", "--step", sid, "--name", text, "--ref", ref)
    else:
        if not text:
            return _no("say what the part is")
        sid = _slug(text, initiative)
        args = ["roadmap-propose", "--step", sid, "--name", text]
        if due:
            args += ["--due", str(due).strip()]
        r = _cli(project, *args)
    if not r.get("ok"):
        return _no("the engine refused: %s" % r.get("error"))
    r2 = _spine_set(project, sid, {"navigation": {"path": [initiative]}})
    if not r2.get("ok"):
        return _no("the part was written but not placed: %s" % r2.get("error"))
    return _ok("added \u2018%s\u2019 to %s%s" % (text, head.get("name"), (" · due " + str(due)) if due else ""), undo={"act": "withdraw", "step": sid}, step=sid)


def promote(project, seed_id, tier, area, done_when=None):
    """A seed (by its id on the strip) becomes an initiative: the heading step with the tier and area he picked,
    its root group at the foot of that tier, and the seed spent by one later receipt that cites its id."""
    seed = seed_by_id(project, seed_id)
    if seed is None:
        return _no("no such seed — the row above the board is the list")
    text = seed["text"]
    try:
        tier = int(tier) if str(tier or "").strip() else 3
    except Exception:
        return _no("a tier is 1, 2 or 3")
    if tier not in (1, 2, 3):
        return _no("a tier is 1, 2 or 3")
    sid = _slug(text)
    if _step(project, sid) is not None:
        return _no("a goal with that name exists already")
    args = ["roadmap-propose", "--step", sid, "--name", text, "--tier", str(tier), "--done-when", done_when or "not written yet — say what done looks like"]
    if area:
        args += ["--area", str(area)]
    r = _cli(project, *args)
    if not r.get("ok"):
        return _no("the engine refused: %s" % r.get("error"))
    r2 = _spine_set(project, sid, {"navigation": {"path": [sid], "groups": [{"id": sid, "label": text, "order": _foot(project, tier), "parent_id": None}], "role": "primary"}})
    if not r2.get("ok"):
        return _no("the heading was written but not grouped: %s" % r2.get("error"))
    r3 = _cli(project, "grasscatch", "--deferred", text, "--reason", "promoted seed %s → the initiative %s, by John on the Campaign" % (seed["id"], sid))
    spent = " — but the seed could not be spent on the strip: %s" % r3.get("error") if not r3.get("ok") else ""
    try:   # a goal made from a seed asks its premortem too (2026-10-03, Grok code R1 F3)
        from . import nudges as _n
        _n.ask_premortem(project, sid, "a new goal")
    except Exception:
        pass
    return _ok("%s is now a goal in tier %d%s%s" % (text, tier, (" · " + str(area)) if area else "", spent),
               undo={"act": "withdraw", "step": sid, "seed": seed["id"]}, step=sid)


def retag(project, step, initiative):
    """A part moves to another initiative: one step_set of its navigation path. A heading is refused."""
    s = _step(project, step)
    if s is None:
        return _no("no such part")
    if _own_group(s) is not None:
        return _no("%s is a goal, not a part — the Tier menu moves it" % s.get("name"))
    head = _step(project, initiative)
    if head is None or _own_group(head) is None:
        return _no("no such goal")
    nav = dict(s.get("navigation") or {})
    old = list(nav.get("path") or [])
    if old and old[0] == initiative:
        return _no("%s is already under %s" % (s.get("name"), head.get("name")))
    nav["path"] = [initiative]
    r = _spine_set(project, step, {"navigation": nav})
    if not r.get("ok"):
        return _no("the engine refused: %s" % r.get("error"))
    return _ok("%s moved to %s" % (s.get("name"), head.get("name")), undo={"act": "retag", "step": step, "initiative": old[0]} if old else None)


def withdraw(project, step, seed=None):
    """The inverse of add and promote. The record is append-only, so nothing is deleted: the step's navigation
    is cleared (one step_set), which takes it off the board; the ordinary cockpit still shows it. A heading that
    has parts is refused (the engine would refuse their paths). With a seed id, the seed is given back."""
    s = _step(project, step)
    if s is None:
        return _no("no such part")
    old_nav = s.get("navigation")
    if not old_nav:
        return _no("%s is already off the board" % s.get("name"))
    if _own_group(s) is not None and _parts_of(project, step):
        return _no("%s has parts now — move them first, then withdraw it" % s.get("name"))
    r = _spine_set(project, step, {"navigation": None})
    if not r.get("ok"):
        return _no("the engine refused: %s" % r.get("error"))
    back = ""
    if seed:
        r2 = _cli(project, "grasscatch", "--deferred", s.get("name") or "", "--reason", "restored seed %s — the initiative %s was undone by John on the Campaign" % (seed, step))
        back = " and the seed is back above the board" if r2.get("ok") else " — but the seed could not be restored on the strip: %s" % r2.get("error")
    return _ok("%s withdrawn — off the board; the record keeps it (the cockpit shows it)%s" % (s.get("name"), back),
               undo={"act": "restore", "step": step, "navigation": old_nav, "seed": seed})


def restore(project, step, navigation, seed=None):
    s = _step(project, step)
    if s is None:
        return _no("no such part")
    if not isinstance(navigation, dict):
        return _no("nothing to restore it to")
    r = _spine_set(project, step, {"navigation": navigation})
    if not r.get("ok"):
        return _no("the engine refused: %s" % r.get("error"))
    spent = ""
    if seed:
        r2 = _cli(project, "grasscatch", "--deferred", s.get("name") or "", "--reason", "promoted seed %s → the initiative %s, by John on the Campaign (restored)" % (seed, step))
        spent = "" if r2.get("ok") else " — but the seed could not be spent on the strip: %s" % r2.get("error")
    return _ok("%s is back on the board%s" % (s.get("name"), spent), undo={"act": "withdraw", "step": step, "seed": seed})


ACTS = {"move_tier", "rank", "rename", "date", "park", "unpark", "flag", "unflag", "tick", "add", "promote", "withdraw", "restore", "retag",
        "pace", "done_when", "place", "seat", "home", "new_goal", "guide", "not_now", "nudge_again", "seat_new",
        "resume", "resume_done", "if_then", "premortem", "premortem_skip", "premortem_ask"}


# ── the seats (2026-09-30, John's three levels): a goal's component on the desk ─────────────────────────────────────

SEATS = ("active", "deck")
INITIATIVE_KINDS = ("project", "effort", "task")


def _kind_of(step):
    ref = str(step.get("ref") or "")
    return ref.split(":", 1)[0] if ref else "task"


def _goal_of(project, step):
    """The heading a part sits under (its navigation path's root), or None."""
    nav = step.get("navigation") if isinstance(step.get("navigation"), dict) else {}
    path = nav.get("path") or []
    return _step(project, path[0]) if path else None


def _seat_ids(project, seat, except_id=None):
    """The components in a seat, in his order."""
    rows = [(x.get("seat_order") if isinstance(x.get("seat_order"), int) else 999, x.get("name") or "", x["id"])
            for x in _projection(project) if x.get("seat") == seat and x["id"] != except_id and x.get("status") not in ("done", "parked")]
    return [sid for _o, _n, sid in sorted(rows)]


def _seat_line(project, seat):
    names = []
    for sid in _seat_ids(project, seat):
        x = _step(project, sid) or {}
        names.append(x.get("name") or sid)
    line = ("active: " if seat == "active" else "on deck: ") + (", ".join(names) if names else "nothing")
    if seat == "active" and len(names) > 3:
        line += " %s %d active is wider than three; the steward would keep to three" % ("\u2014", len(names))     # said, never refused (his word: no cap)
    return line


def _place_seat(project, step, seat, position):
    """Put a component at a position in a seat's order; the others close up. The first refused write is the error."""
    ids = _seat_ids(project, seat, except_id=step)
    position = max(0, min(int(position), len(ids)))
    ids.insert(position, step)
    for k, sid in enumerate(ids):
        cur = _step(project, sid)
        if cur.get("seat_order") != k:
            r = _cli(project, "roadmap-set", "--step", sid, "--seat-order", str(k))
            if not r.get("ok"):
                return "the engine refused: %s" % r.get("error")
    return None


def _component(project, step):
    """The step as a seatable component, or a refusal."""
    s = _step(project, step)
    if s is None:
        return None, _no("no such part")
    if _own_group(s) is not None:
        names = ", ".join((x.get("name") or x["id"]) for x in _parts_of(project, step) if _kind_of(x) in INITIATIVE_KINDS)[:200]
        return None, _no("%s is a goal \u2014 a goal has no seat; name one of its components%s" % (s.get("name"), (": " + names) if names else ""))
    if _kind_of(s) not in INITIATIVE_KINDS:
        return None, _no("%s is a %s \u2014 it rides inside its goal; a cockpit, an effort or a desk item takes a seat" % (s.get("name"), _kind_of(s)))
    return s, None


def seat(project, step, seat, position=None):
    """Put a component on the desk: ACTIVE or ON DECK, at a position (the foot when none); one receipt naming the
    seat as it now is; the undo puts it back where it sat (its old seat and place, or its goal)."""
    s, refusal = _component(project, step)
    if refusal:
        return refusal
    seat = str(seat or "").strip().lower()
    if seat not in SEATS:
        return _no("a seat is active or deck")
    old_seat = s.get("seat") if s.get("seat") in SEATS else None
    old_pos = _seat_ids(project, old_seat).index(step) if old_seat and step in _seat_ids(project, old_seat) else None
    if old_seat == seat and position is None:
        return _no("%s is already %s" % (s.get("name"), "active" if seat == "active" else "on deck"))
    place = int(position) if position is not None else len(_seat_ids(project, seat, except_id=step))
    r = _cli(project, "roadmap-set", "--step", step, "--seat-in", seat, "--seat-order", str(place))
    if not r.get("ok"):
        return _no("the engine refused: %s" % r.get("error"))
    undo = {"act": "seat", "step": step, "seat": old_seat, "position": old_pos or 0} if old_seat else {"act": "home", "step": step}
    err = _place_seat(project, step, seat, place)
    if not err and old_seat and old_seat != seat:
        err = _renumber_seat(project, old_seat)
    if err:
        return _no("%s is %s, but the order could not close up: %s \u2014 undo puts it back" % (s.get("name"), "active" if seat == "active" else "on deck", err), undo=undo)
    g = _goal_of(project, s)
    where = ("%s (%s)" % (s.get("name"), g.get("name"))) if g else s.get("name")
    return _ok("%s is %s \u2014 %s" % (where, "active" if seat == "active" else "on deck", _seat_line(project, seat)), undo=undo)


def _renumber_seat(project, seat):
    for k, sid in enumerate(_seat_ids(project, seat)):
        cur = _step(project, sid)
        if cur.get("seat_order") != k:
            r = _cli(project, "roadmap-set", "--step", sid, "--seat-order", str(k))
            if not r.get("ok"):
                return "the engine refused: %s" % r.get("error")
    return None


def home(project, step):
    """Send a component back into its goal (no seat); the seat it left closes up; the undo re-seats it where it was."""
    s, refusal = _component(project, step)
    if refusal:
        return refusal
    old_seat = s.get("seat") if s.get("seat") in SEATS else None
    if not old_seat:
        return _no("%s is in its goal already" % s.get("name"))
    old_pos = _seat_ids(project, old_seat).index(step) if step in _seat_ids(project, old_seat) else 0
    r = _cli(project, "roadmap-set", "--step", step, "--seat-in", "none")
    if not r.get("ok"):
        return _no("the engine refused: %s" % r.get("error"))
    undo = {"act": "seat", "step": step, "seat": old_seat, "position": old_pos}
    err = _renumber_seat(project, old_seat)
    if err:
        return _no("%s is back in its goal, but %s could not close up: %s \u2014 undo puts it back" % (s.get("name"), "Active" if old_seat == "active" else "On deck", err), undo=undo)
    g = _goal_of(project, s)
    return _ok("%s back in %s \u2014 %s" % (s.get("name"), g.get("name") if g else "its goal", _seat_line(project, old_seat)), undo=undo)


def new_goal(project, text, tier=None, area=None, done_when=None):
    """A goal from his words (no seed): the heading step with its tier and its root group at the foot of that tier."""
    text = " ".join(str(text or "").split())
    if not text:
        return _no("a goal needs a name")
    try:
        tier = int(tier) if str(tier or "").strip() else 3
    except Exception:
        return _no("a tier is 1, 2 or 3")
    if tier not in (1, 2, 3):
        return _no("a tier is 1, 2 or 3")
    sid = _slug(text)
    if _step(project, sid) is not None:
        return _no("a goal with that name exists already")
    args = ["roadmap-propose", "--step", sid, "--name", text, "--tier", str(tier), "--done-when", done_when or "not written yet \u2014 say what done looks like"]
    if area:
        args += ["--area", str(area)]
    r = _cli(project, *args)
    if not r.get("ok"):
        return _no("the engine refused: %s" % r.get("error"))
    r2 = _spine_set(project, sid, {"navigation": {"path": [sid], "groups": [{"id": sid, "label": text, "order": _foot(project, tier), "parent_id": None}], "role": "primary"}})
    if not r2.get("ok"):
        return _no("the heading was written but not grouped: %s" % r2.get("error"))
    try:   # the Star Chart asks its premortem once on a new goal (2026-10-03)
        from . import nudges as _n
        _n.ask_premortem(project, sid, "a new goal")
    except Exception:
        pass
    return _ok("%s is now a goal in tier %d%s" % (text, tier, (" \u00b7 " + str(area)) if area else ""), undo={"act": "withdraw", "step": sid}, step=sid)


def pace(project, step, when):
    """The date he drives an initiative toward (YYYY-MM-DD, or none)."""
    s = _step(project, step)
    if s is None or _own_group(s) is None:
        return _no("no such goal")
    when = str(when or "").strip() or "none"
    r = _cli(project, "roadmap-set", "--step", step, "--pace", when)
    if not r.get("ok"):
        return _no("the engine refused: %s (a pace is YYYY-MM-DD, or none)" % r.get("error"))
    old = s.get("pace") or "none"
    if old != "none" and when != "none" and when > old:   # the pace slipped later: the Star Chart asks its premortem (2026-10-03)
        try:
            from . import nudges as _n
            _n.ask_premortem(project, step, "its pace moved from %s to %s" % (old, when))
        except Exception:
            pass
    return _ok("%s: the pace is %s" % (s.get("name"), ("now " + when) if when != "none" else "cleared"), undo={"act": "pace", "step": step, "when": old})


def done_when(project, step, text):
    """Revise a goal — what done looks like — on its initiative (the goal's place, W2 v2)."""
    s = _step(project, step)
    if s is None or _own_group(s) is None:
        return _no("no such goal")
    text = " ".join(str(text or "").split())
    if not text:
        return _no("a goal is a sentence — say what done looks like")
    old = s.get("done_when") or ""
    if text == old:
        return _no("the goal of %s already reads so" % s.get("name"))
    r = _cli(project, "roadmap-set", "--step", step, "--done-when", text)
    if not r.get("ok"):
        return _no("the engine refused: %s" % r.get("error"))
    return _ok("Goal of %s revised" % s.get("name"), undo={"act": "done_when", "step": step, "text": old} if old else None)


def _tier_ids(project, tier, except_id=None):
    same = sorted([(int(g.get("order") or 0), x.get("name") or "", x["id"]) for x, g in _initiatives(project) if x.get("tier") == tier and x["id"] != except_id])
    return [sid for _o, _n, sid in same]


def _place_tier(project, step, tier, position):
    """Put an initiative at a position in its tier's order; the others close up. The first refused write is the error."""
    ids = _tier_ids(project, tier, except_id=step)
    position = max(0, min(int(position), len(ids)))
    ids.insert(position, step)
    for k, sid in enumerate(ids):
        cur = _step(project, sid)
        if int((_own_group(cur) or {}).get("order") or 0) != k:
            r = _write_nav(project, cur, order=k)
            if not r.get("ok"):
                return "the engine refused: %s" % r.get("error")
    return None


def place(project, step, band, position=0, tier=None, tier_position=None):
    """ONE act for a drop of a goal on the board: into a tier's band (1 · 2 · 3, the last being the seed goals). The
    tier only \u2014 his word: no ranking inside a tier. One receipt; the undo is the old tier."""
    s = _step(project, step)
    if s is None or _own_group(s) is None:
        return _no("no such goal")
    band = str(band or "").strip().lower()
    if band not in ("1", "2", "3"):
        return _no("a band is a tier 1, 2 or 3")
    tier = int(band)
    old_tier = s.get("tier") if s.get("tier") in (1, 2, 3) else None
    if old_tier == tier:
        return _no("%s is already in tier %d \u2014 there is no order inside a tier" % (s.get("name"), tier))
    r = move_tier(project, step, tier)
    if not r.get("ok"):
        return r
    return _ok("%s moved to tier %d" % (s.get("name"), tier), undo={"act": "place", "step": step, "band": str(old_tier), "position": 0} if old_tier else None)


def guide(project, step, text):
    """W2d (2026-09-30): his revision of a goal's guide from its place. The steward writes the guide on his word in the
    conversation; this is his own hand on the file - written whole with a dated History line, committed. No undo: the
    History line and the Campaign's commits keep every version."""
    s = _step(project, step)
    if not s or not _own_group(s):
        return _no("no such goal")
    from .steward_campaign import write_guide
    r = write_guide(project, step, text, who="John")
    if not r.get("ok"):
        return _no(str(r.get("error") or "the guide was not written"))
    return _ok("the guide of %s revised \u2014 %s" % (s.get("name"), r.get("note") or "written"), undo=None, updated=r.get("updated"))


def not_now(project, key, fact="", text=""):
    """W3 (2026-10-01): his 'not now' on a nudge - a receipt in the Campaign's folder that silences THAT nudge until its
    fact changes; the undo drops the receipt. Nothing on the record moves."""
    from . import nudges as _n
    r = _n.dismiss(project, key, fact, text)
    if not r.get("ok"):
        return _no(str(r.get("error") or "that did not go through"))
    return _ok("not now \u2014 that nudge stays quiet until its fact changes", undo={"act": "nudge_again", "key": key})


def nudge_again(project, key):
    from . import nudges as _n
    was = (_n.read_dismissed(project) or {}).get(str(key)) or {}     # the receipt as it stood, so its undo puts it back whole (Grok W3)
    r = _n.undismiss(project, key)
    if not r.get("ok"):
        return _no(str(r.get("error") or "that did not go through"))
    return _ok("the nudge may speak again", undo={"act": "not_now", "key": key, "fact": str(was.get("fact") or ""), "text": str(was.get("text") or "")})


def resume(project, note, switched_to=""):
    """The interrupt lane (2026-10-03): opening a dated item keeps one line of what he was on; undo clears it."""
    from . import nudges as _n
    r = _n.write_resume(project, note, switched_to)
    if not r.get("ok"):
        return _no(str(r.get("error") or "that did not go through"))
    return _ok("kept: you were on %s" % r["note"], undo={"act": "resume_done"})


def resume_done(project):
    from . import nudges as _n
    r = _n.clear_resume(project)
    if not r.get("ok"):
        return _no(str(r.get("error") or "that did not go through"))
    was = r.get("was") or {}
    return _ok("the note is cleared", undo=({"act": "resume", "note": was.get("note"), "switched_to": was.get("switched_to") or ""} if was.get("note") else None))


def if_then(project, step, text):
    """The Star Chart (2026-10-03): a goal's one if-then next step, in his words, on the record (receipted step_set)."""
    s = _step(project, step)
    if s is None or _own_group(s) is None:
        return _no("no such goal")
    text = " ".join(str(text or "").split())[:300]
    old = s.get("if_then") or ""
    if text == old:
        return _no("the if-then of %s already reads so" % s.get("name"))
    r = _spine_set(project, step, {"if_then": text or None})
    if not r.get("ok"):
        return _no("the engine refused: %s" % r.get("error"))
    return _ok("%s: %s" % (s.get("name"), ("the next step is \u201c%s\u201d" % text) if text else "the if-then is cleared"),
               undo={"act": "if_then", "step": step, "text": old})


PREMORTEM_Q = "It is three months on and this goal fell short: what went wrong?"


def premortem(project, step, text):
    """His answer to the premortem goes into the goal's guide under '## Premortem', then the ask is closed."""
    s = _step(project, step)
    if s is None or _own_group(s) is None:
        return _no("no such goal")
    answer = " ".join(str(text or "").split())
    if not answer:
        return _no("say what went wrong, in a sentence")
    import time as _time
    from .steward_campaign import read_guide, write_guide
    from . import nudges as _n
    g = read_guide(project, step)
    body = (g.get("text") or ("# %s\n" % (s.get("name") or step))).rstrip("\n")
    block = "## Premortem, %s\n%s\n%s" % (_time.strftime("%Y-%m-%d"), PREMORTEM_Q, answer)
    lines = body.split("\n")
    h = next((k for k, ln in enumerate(lines) if ln.strip().lower() == "## history"), None)
    if h is not None:
        body = "\n".join(lines[:h]).rstrip("\n") + "\n\n" + block + "\n\n" + "\n".join(lines[h:])
    else:
        body = body + "\n\n" + block + "\n"
    r = write_guide(project, step, body, who="John")
    if not r.get("ok"):
        return _no(str(r.get("error") or "the guide was not written"))
    _n.close_premortem(project, step)
    return _ok("the premortem of %s is in its guide" % s.get("name"), undo=None, updated=r.get("updated"))


def premortem_skip(project, step):
    from . import nudges as _n
    was = _n.close_premortem(project, step)
    return _ok("not now \u2014 the premortem is set aside",
               undo=({"act": "premortem_ask", "step": step, "reason": (was or {}).get("reason") or ""} if was else None))


def premortem_ask(project, step, reason=""):
    from . import nudges as _n
    if not _n.ask_premortem(project, step, reason or "asked again"):
        return _no("that did not go through")
    return _ok("the premortem is asked again", undo={"act": "premortem_skip", "step": step})


def seat_new(project, ref, name, seat_to):
    """A candidate not yet on the Campaign - a cockpit (project:<pid>) or a cockpit within a project
    (effort:<pid>/<dir>) - put on the desk in one act (his word, 2026-10-02: "a tile ... right below the on deck that
    shows all of the candidates ... anything with an AI Cockpit"): it becomes a component in no goal, then takes the
    seat. One receipt; the undo withdraws it. A ref already on the map is seated as it is (never a second card)."""
    from steward_cockpit.campaign_parts import parse_ref
    ref = str(ref or "").strip()
    p = parse_ref(ref)
    if p is None or p.get("kind") not in ("project", "effort"):
        return _no("a candidate is a cockpit (project:) or a cockpit within a project (effort:)")
    seat_to = str(seat_to or "").strip().lower()
    if seat_to not in SEATS:
        return _no("a seat is active or deck")
    there = next((x for x in _projection(project) if str(x.get("ref") or "") == ref and x.get("status") not in ("done",)), None)
    if there is not None:
        return seat(project, there["id"], seat_to)
    name = " ".join(str(name or "").split())[:120] or ref
    sid, n = _slug(name, "cand"), 2
    while _step(project, sid) is not None:
        sid, n = "%s-%d" % (_slug(name, "cand"), n), n + 1
    r = _cli(project, "roadmap-propose", "--step", sid, "--name", name, "--ref", ref)
    if not r.get("ok"):
        return _no("the engine refused: %s" % r.get("error"))
    out = seat(project, sid, seat_to)
    if not out.get("ok"):
        withdraw(project, sid)
        return out
    out["undo"] = {"act": "withdraw", "step": sid}
    return out


def act(project, body):
    """Dispatch one act from the page; every answer is a receipt sentence, ok or refused."""
    body = body if isinstance(body, dict) else {}
    a = str(body.get("act") or "")
    if a not in ACTS:
        return _no("no such act")
    try:
        if a == "move_tier":
            return move_tier(project, body.get("step"), body.get("tier"), body.get("order"))
        if a == "rank":
            return rank(project, body.get("step"), "up" if body.get("direction") == "up" else "down")
        if a == "rename":
            return rename(project, body.get("step"), body.get("name"))
        if a == "date":
            return date(project, body.get("step"), body.get("due"))
        if a == "park":
            return park(project, body.get("step"), body.get("waiting_on"))
        if a == "unpark":
            return unpark(project, body.get("step"))
        if a == "flag":
            return flag(project, body.get("step"), True)
        if a == "unflag":
            return flag(project, body.get("step"), False)
        if a == "tick":
            return tick(project, body.get("step"))
        if a == "add":
            return add(project, body.get("initiative"), body.get("kind"), body.get("text"), body.get("due"), body.get("project_id"))
        if a == "promote":
            return promote(project, body.get("seed"), body.get("tier"), body.get("area"), body.get("done_when"))
        if a == "retag":
            return retag(project, body.get("step"), body.get("initiative"))
        if a == "seat":
            return seat(project, body.get("step"), body.get("seat"), body.get("position"))
        if a == "home":
            return home(project, body.get("step"))
        if a == "new_goal":
            return new_goal(project, body.get("text"), body.get("tier"), body.get("area"), body.get("done_when"))
        if a == "done_when":
            return done_when(project, body.get("step"), body.get("text"))
        if a == "place":
            return place(project, body.get("step"), body.get("band"), body.get("position") or 0)
        if a == "pace":
            return pace(project, body.get("step"), body.get("when"))
        if a == "withdraw":
            return withdraw(project, body.get("step"), body.get("seed"))
        if a == "restore":
            return restore(project, body.get("step"), body.get("navigation"), body.get("seed"))
        if a == "guide":
            return guide(project, body.get("step"), body.get("text"))
        if a == "not_now":
            return not_now(project, body.get("key"), body.get("fact"), body.get("text"))
        if a == "nudge_again":
            return nudge_again(project, body.get("key"))
        if a == "seat_new":
            return seat_new(project, body.get("ref"), body.get("name"), body.get("seat"))
        if a == "resume":
            return resume(project, body.get("note"), body.get("switched_to"))
        if a == "resume_done":
            return resume_done(project)
        if a == "if_then":
            return if_then(project, body.get("step"), body.get("text"))
        if a == "premortem":
            return premortem(project, body.get("step"), body.get("text"))
        if a == "premortem_skip":
            return premortem_skip(project, body.get("step"))
        if a == "premortem_ask":
            return premortem_ask(project, body.get("step"), body.get("reason"))
    except Exception as e:
        return _no("that did not go through: %s" % e)
    return _no("no such act")
