"""campaign_page — the Campaign, version D: John's initiatives in three priority tiers, and the same record
against the five-week ruler behind one button.

W3c of the High Seat plan (2026-09-26). The approved design is the mockup
``Skill Foundry/planning/high-seat-2026-09-24/ideation/mockups/campaign/campaign-D.html``; its stylesheet is
``static/campaign-page.css`` ported as it is. This module renders that page from the Campaign record —
the initiatives (heading steps with tier, area, outcome, their root group's order), their parts (steps whose
path starts with the initiative; a ``ref`` part read through the resolver), the strip's seeds — plus the
steward livery and the effort's own conversation. Pure: a context dict in, HTML out. Every count on the
page is counted from the record. The acts on the page go through ``steward_cockpit/campaign_acts``.
"""
from __future__ import annotations

from datetime import timedelta

import home_rows as _hr
from high_seat_page import tab_icon_link, HIS_NAME, conversation_view
from high_seat_page import esc, _brand_img, _masthead, ruler_weeks, LIGHTS, initiative_light, initiative_line, initiative_status_html, is_initiative, nudge_html, mode_name
import home_attention as _ha

TIER_WORDS = {1: "do first", 2: "next in line", 3: "when there is room"}
TIER_COLOURS = {1: "#6c9cfc", 2: "#8b93a6", 3: "#5f6674"}
AREA_COLOURS = {"family": "#e78aa6", "professional": "#6c9cfc", "writing": "#a78bfa", "research": "#4fc9c2",
                "tools": "#94a3b8", "personal": "#d0975f"}
AREAS = ("family", "professional", "writing", "research", "tools", "personal")


def _short(d):
    return _hr.short_date(d) if d else ""


def _needs(n, noun="part"):
    """"⚑ 2 parts need you" — the noun said (Grok R8: the board counts parts, a tier header counts initiatives)."""
    return "&#9873; %d %s%s need%s you" % (n, noun, "" if n == 1 else "s", "s" if n == 1 else "")


def _part_state(p):
    # W1 (2026-09-28): a referenced part's done/closed comes from the RESOLVED target too (campaign_initiatives'
    # `done` / `closed` flags), never the wrapper's status alone
    if p["broken"]:
        return "broken reference"
    if p.get("done", p["status"] == "done"):
        return "done"
    if p["status"] == "parked" or p.get("target_status") == "parked":
        return "parked"
    if p["needs_you"]:
        return "needs you"
    return p["state"] or p["status"] or "open"


# ── the board: grouped view ────────────────────────────────────────────────────────────────────

KIND_WORDS = {"task": "desk item", "project": "cockpit", "effort": "effort (a cockpit within a project)", "step": "step of a project", "deliverable": "deliverable", "calendar": "date"}


def _part_row(i, p, today, tick_allowed):
    pid = esc(p["id"])
    done = bool(p.get("done", p["status"] == "done"))
    ref = p["kind"] != "task"
    date_chip = (('<button class="mchip dated" data-act="date" data-part="%s">%s</button>' % (pid, esc(_short(p["date"])))) if p["date"] else
                 ('<button class="mchip" data-act="date" data-part="%s">no date</button>' % pid)) if not ref else (
        ('<span class="mchip dated" title="its date lives in its own record">%s</span>' % esc(_short(p["date"]))) if p["date"] else '<span class="mchip" title="its date lives in its own record">no date</span>')
    state = _part_state(p)
    state_chip = ('<span class="mchip donew">&#10003; done</span>' if done else
                  ('<span class="mchip flagon">&#9873; needs you</span>' if p["needs_you"] else
                   ('<span class="mchip state" style="color:var(--amber-t)">%s</span>' % esc("broken reference: " + p["gap"]) if p["broken"] else
                    '<span class="mchip state">%s</span>' % esc(state))))
    flag_chip = ("" if ref or done else (
        ('<button class="mchip flagon" data-act="unflag" data-part="%s">&#9873; needs you &middot; clear</button>' % pid) if p["needs_you"] else
        ('<button class="mchip" data-act="flag" data-part="%s">&#9873; flag it</button>' % pid)))
    link = ('<a class="mchip proj" href="%s" target="_blank" rel="noopener">%s &rarr; cockpit</a>' % (esc(p["href"]), esc(p["target"] or p["kind"]))) if p["href"] else ""
    park = (('<button class="mchip" data-act="unpark" data-part="%s">unpark</button>' % pid) if p["status"] == "parked" else
            ('<button class="mchip" data-act="park" data-part="%s">park</button>' % pid)) if not ref else ""
    tick = (('<button class="tick%s" data-act="tick" data-part="%s" aria-label="mark done"%s></button>' % (
        " on" if done else "", pid, "" if (tick_allowed and not ref) else ' disabled title="a tick waits on your word on the close law"'))
            if not ref else (('<a class="tickpad%s" href="%s" target="_blank" rel="noopener" title="done or parked in its own record &mdash; open it"></a>' % (" on" if done else "", esc(p["href"])))
                             if p["href"] else '<span class="tickpad" title="a referenced part is closed in its own record"></span>'))
    name = ('<span class="rt" data-act="name" data-part="%s">%s</span>' % (pid, esc(p["text"]))) if not ref else ('<span class="rt">%s</span>' % esc(p["text"]))
    return ('<li class="row%s%s" data-part="%s">%s<div class="rb">%s<div class="rm">'
            '<span class="mchip kind">%s</span>%s%s%s%s%s'
            '</div></div></li>' % (
                " done" if done else "", " pparked" if p["status"] == "parked" else "", pid, tick, name,
                esc(KIND_WORDS.get(p["kind"], p["kind"])), date_chip, flag_chip, state_chip, link, park))


def _part_light(p, working):
    """A project part's own light: needs him · working (a live session on it) · waiting · done · idle."""
    if p.get("done"):
        return "done"
    if p.get("needs_you"):
        return "needs"
    if p.get("pid") and p["pid"] in (working or set()):
        return "working"
    if str(p.get("state") or "").lower().startswith("waiting") or p.get("status") == "waiting":
        return "waiting"
    return "idle"


def _cockpits(i, ctx):
    """The goal's cockpits on the tile's face (his 13:5x word: a goal holds one, several, or no project yet): each
    project part by name with its own light; "at the desk" when the goal has no project."""
    working = ctx.get("working") or set()
    projs = [p for p in i["parts"] if p["kind"] in ("project", "effort") and not p["broken"]]
    if not projs:
        return '<div class="gcock"><span class="dim">at the desk &mdash; no project yet</span></div>'
    glyphs = {"needs": "&#9873;", "working": "&#9679;", "waiting": "&#9679;", "idle": "&#9675;", "done": "&#10003;"}
    return '<div class="gcock">%s</div>' % " &middot; ".join(
        '<span class="gpc %s" title="%s">%s <i>%s</i>%s</span>' % (_part_light(p, working), esc(p["state"] or p["status"] or ""), esc(p["target"] or p["text"]), glyphs[_part_light(p, working)],
                                                                    ('<b class="seat %s">%s</b>' % (p["seat"], "active" if p["seat"] == "active" else "on deck")) if p.get("seat") else "")
        for p in projs[:4]) + ((' <span class="dim">+%d</span>' % (len(projs) - 4)) if len(projs) > 4 else "")


def _gtile(i, ctx, band, draggable=True):
    """One goal on the board (W2 v2, his lock of 11:0x): its number, its name (opens its place), its tier and light,
    the goal in a line, its cockpits with their lights (or "at the desk"), and the facts — progress, pace, next
    deadline, what waits on him. It drags."""
    today = ctx["today"]
    glyph, word = LIGHTS[initiative_light(i, ctx.get("working") or set())]
    n, done = len(i["parts"]), int(i.get("done_count") or 0)
    pct = int(round(100.0 * done / n)) if n else 0
    nd = i.get("next_deadline") or ""
    nd_d = _hr._iso(nd) if nd else None
    dcls = ("over" if nd_d and nd_d < today else ("soon" if nd_d and (nd_d - today).days <= 7 else ""))
    return (
        '<article class="gtile%s%s" draggable="%s" data-lane="%s" data-band="%s" style="--areac:%s">'
        '<div class="ihead"><button class="iname" data-open="%s" title="open its place">%s</button>'
        '<span class="gtier">tier %s</span><span class="ilight %s" title="the light: needs you · working · waiting · idle, read from its parts">%s %s</span></div>'
        '<div class="ggoal" title="%s">%s</div>%s%s'
        '<div class="gfacts"><span class="gprog"><span class="bar"><i style="width:%d%%"></i></span>%d of %d</span><span class="%s">%s</span><span class="gdl %s">%s</span>%s</div></article>'
    ) % (" needs" if i["needs"] else "", " bone" if i["status"] in ("done", "parked") else "", "true" if draggable else "false", esc(i["id"]), band, AREA_COLOURS.get(i["area"], "#8b93a6"),
         esc(i["id"]), esc(i["name"]), i["tier"] or "?",
         initiative_light(i, ctx.get("working") or set()), glyph, word,
         esc(i["done_when"]), esc(i["done_when"]) or '<span class="dim">no goal written yet</span>',
         _cockpits(i, ctx), _ifthen(i) + _premortem(i, ctx),
         pct, done, n, "" if i.get("pace") else "dim", ("pace " + esc(_short(i["pace"]))) if i.get("pace") else "no pace",
         dcls, (("overdue " if dcls == "over" else "next ") + esc(_short(nd))) if nd else "no deadline",
         (' <span class="am">&#9873; %s</span>' % _needs(len(i["needs"]))) if i["needs"] else "")


def _not_dated(n):
    """One lane per item (2026-10-03): a dated nudge is the Cave's interrupt lane, never a goal place's here."""
    return n if isinstance(n, dict) and n.get("kind") != "dated" else None


PREMORTEM_Q = "It is three months on and this goal fell short: what went wrong?"


def _ifthen(i):
    """The Star Chart (2026-10-03, the research's Adopt): a Tier-1 goal carries ONE if-then next step in his words
    ("If it is Monday 9:00, then I send the trust questions"); unwritten, the line asks for it. Click to write or revise."""
    if i.get("tier") != 1 or i.get("status") in ("done", "parked"):
        return ""
    t = str(i.get("if_then") or "")
    return ('<div class="gift%s" data-ifthen="%s" data-text="%s" title="the next step as an if-then, in your words - click to %s">&#8627; %s</div>') % (
        "" if t else " empty", esc(i["id"]), esc(t), "revise" if t else "write it",
        esc(t) if t else "If-then step not written yet &middot; add one in your words")


def _premortem(i, ctx):
    """The premortem ask (2026-10-03, the research's Try): asked once when a goal is made or its pace slips later; the
    answer goes into the goal's guide; 'not now' sets it aside."""
    pm = (ctx.get("premortems") or {}).get(i["id"])
    if not isinstance(pm, dict) or i.get("status") in ("done", "parked"):
        return ""
    return ('<div class="gpm" data-pm="%s"><b>Premortem</b> &middot; %s. &ldquo;%s&rdquo; Your answer goes into the goal&rsquo;s guide. '
            '<button class="mini" data-pm-answer="%s">Answer</button> <button class="mini" data-pm-skip="%s">Not now</button></div>') % (
        esc(i["id"]), esc(pm.get("reason") or "asked"), esc(PREMORTEM_Q), esc(i["id"]), esc(i["id"]))


def _band(key, label, note, items, ctx, cls="", extra="", quiet_empty=False):
    tiles = "".join(_gtile(i, ctx, key) for i in items)
    empty = {"1": "nothing in tier 1", "2": "nothing in tier 2", "3": "no seed goal yet"}.get(key, "nothing here")
    return ('<section class="band%s" data-band="%s"><h4 class="band-h">%s <span class="c">%s</span></h4>'
            '<div class="tiles">%s</div>%s</section>' % ((" " + cls) if cls else "", key, label, note,
                                                       tiles or ("" if quiet_empty else '<div class="empty">%s</div>' % empty), extra))


def _bands(ctx):
    """The goal board (PLAN v1.3): Tier 1 · Tier 2 · Seed goals (the tier-3 and untiered goals, and the seeds) · the
    Boneyard (done or parked goals, folded, never deleted). No Active band: seats live at the High Seat. No order
    inside a tier (his word, 09-29 18:4x)."""
    inits = ctx["initiatives"]
    live = [i for i in inits if i["status"] not in ("done", "parked")]
    bone = [i for i in inits if i["status"] in ("done", "parked")]
    out = []
    for t in (1, 2):
        mine = [i for i in live if i["tier"] == t]
        needs = sum(1 for i in mine if i["needs"])
        out.append(_band(str(t), "Tier %d" % t, "%s &middot; %d goal%s%s" % (TIER_WORDS[t], len(mine), "" if len(mine) == 1 else "s",
                         (' &middot; <span class="am">%s</span>' % _needs(needs, "goal")) if needs else ""), mine, ctx))
    seedy = [i for i in live if i["tier"] not in (1, 2)]
    out.append(_band("3", "Seed goals", "for the future &middot; a tier-3 goal sits here until you say tier 2; a goal with no tier yet is marked tier ? until you pick one; a seed becomes a goal on its card", seedy, ctx, "seeds", extra=_seedband(ctx), quiet_empty=bool(ctx.get("seeds"))))
    out.append('<section class="band bone" data-band="bone"><h4 class="band-h">The boneyard <span class="c">done or abandoned goals &mdash; folded, never deleted</span><button class="mini" id="boneTog" aria-expanded="false">show (%d)</button></h4>'
               '<div class="bonefold" id="boneFold" hidden>%s</div></section>' % (len(bone), "".join(_gtile(i, ctx, "bone", draggable=False) for i in bone) or '<div class="empty">nothing here yet &mdash; a goal marked done or abandoned lands here</div>'))
    return '<div class="bands" id="viewGrouped">%s</div>' % "".join(out)


def _thread(i, ctx):
    turns = (ctx.get("goal_turns") or {}).get(i["id"]) or []
    if not turns:
        return '<li class="exfade">Nothing said about this goal yet.</li>'
    return "".join('<li class="exrow %s"><div class="exw %s">%s<span class="t">%s</span></div><div class="ext">%s</div></li>' % (
        "you" if t["you"] else "st", "you" if t["you"] else "st", HIS_NAME if t["you"] else esc(ctx["steward"]["label"]), esc(t["at"]), esc(t["text"])) for t in turns[-12:])


def _guide_block(i, ctx):
    """W2d: the goal's guide in its place - the steward's writing rendered, when it is revised, the History folded, a
    revise button (the raw markdown in a box; Save writes it whole with a dated History line); absent = one line saying
    how it gets written (on his word, in the conversation below)."""
    g = (ctx.get("guides") or {}).get(i["id"]) or {}
    gid = esc(i["id"])
    if not g.get("exists"):
        return ('<div class="guide empty" data-guide="%s"><span class="dim">No guide yet &mdash; say &ldquo;write the guide&rdquo; below and the steward writes it from this conversation and the record.</span></div>' % gid)
    from report_viewer import markdown_to_html
    from steward_cockpit.steward_campaign import guide_body
    hist = g.get("history") or []
    shown = hist[-12:]      # the history ONCE on the page, folded: the body is rendered without its History section (Grok's read of W2d)
    count = ("%d" % len(shown)) if len(shown) == len(hist) else ("the last %d of %d" % (len(shown), len(hist)))
    return ('<div class="guide" data-guide="%s" data-updated="%s"><div class="gbody">%s</div>'
            '<div class="gfoot"><span class="gwhen">updated %s</span><button class="linkish" data-guide-edit="%s">revise</button>%s</div>'
            '<textarea class="gsrc" hidden>%s</textarea></div>') % (
        gid, esc(g.get("updated") or ""), markdown_to_html(guide_body(g.get("text") or "")), esc(g.get("updated") or ""), gid,
        ('<details class="ghist"><summary>history &middot; %s</summary><ul>%s</ul></details>' % (count, "".join('<li>%s</li>' % esc(h) for h in shown))) if hist else "",
        esc(g.get("text") or ""))


def _place(i, ctx):
    """The goal's place (fit 10): the goal to revise, where it stands, the pace and the deadlines, the workflow
    (the parts with their acts, as the tile's body had them), the projects and cockpits, and the goal's own
    conversation. Rendered for every goal, shown for the one he opens — UNDER the bands, which stay at the top
    with their tiles shortened to a name (his 13:2x word: the list of goals first, the large details on a click)."""
    today = ctx["today"]
    glyph, word = LIGHTS[initiative_light(i, ctx.get("working") or set())]
    tier_opts = "".join('<option value="%d"%s>%d &middot; %s</option>' % (t, " selected" if i["tier"] == t else "", t, TIER_WORDS[t]) for t in (1, 2, 3))
    rows = "".join(_part_row(i, p, today, ctx.get("tick_allowed", False)) for p in i["parts"])
    projects = "".join('<option value="%s">%s</option>' % (esc(e.get("id")), esc(e.get("name"))) for e in ctx.get("projects") or [])
    n, done = len(i["parts"]), int(i.get("done_count") or 0)
    waits = [p for p in i["needs"]]
    nxt = i["next"]
    dated = sorted([p for p in i["parts"] if p["date"] and not p["broken"] and p["status"] not in ("done", "parked")], key=lambda p: p["date"])
    stands = "%s%s%s%s%s." % (
        ("%d of %d part%s done" % (done, n, "" if n == 1 else "s")) if n else "no parts yet",
        ('; <span class="am">%d wait%s on you &mdash; %s</span>' % (len(waits), "s" if len(waits) == 1 else "", esc(waits[0]["text"]))) if waits else "",
        ("; the next deadline is <b>%s</b>" % esc(_short(i["next_deadline"]))) if i["next_deadline"] else "; nothing dated",
        ("; the pace is <b>%s</b>" % esc(_short(i["pace"]))) if i.get("pace") else "; no pace set",
        (". Next: <b>%s</b>" % esc(nxt["text"])) if nxt else "")
    comps = [p for p in i["parts"] if not p["done"]]

    def _seat_ctl(p):
        if not is_initiative(p):
            return ""
        pid_ = esc(p["id"])
        if p.get("seat"):
            return ('<span class="seat %s">%s</span><span class="sacts">%s<button class="linkish" data-home="%s">back to the goal</button></span>' % (
                p["seat"], "active" if p["seat"] == "active" else "on deck",
                ('<button class="linkish" data-seat="deck" data-step="%s">&rarr; on deck</button>' % pid_) if p["seat"] == "active" else ('<button class="linkish" data-seat="active" data-step="%s">&rarr; active</button>' % pid_), pid_))
        return '<span class="sacts"><button class="linkish" data-seat="deck" data-step="%s">&rarr; on deck</button><button class="linkish" data-seat="active" data-step="%s">&rarr; active</button></span>' % (pid_, pid_)
    proj_html = "".join('<div class="proj"><span class="ck">%s</span> %s%s<span class="st">%s</span></div>' % (
        KIND_WORDS.get(p["kind"], p["kind"]),
        ('<a href="%s" target="_blank" rel="noopener">%s &#8599;</a>' % (esc(p["href"]), esc(p["target"] or p["text"]))) if p.get("href") else esc(p["text"] if p["kind"] not in ("project", "effort") else (p["target"] or p["text"])),
        _seat_ctl(p), esc(p["state"] or p["status"] or "")) for p in comps) or '<div class="proj dim">no open component &mdash; add one as a part</div>'
    return (
        '<article class="place" id="place-%s" data-goal="%s" hidden style="--areac:%s"><div class="ptop"><span class="pname">%s</span>'
        '<span class="ilight %s">%s %s</span><div class="imore"><span class="larea">%s</span><span class="tierpick">Tier <select class="tsel" data-tiersel="%s">%s</select></span></div>'
        '<button class="mini" data-close="1">close</button></div>'
        '<div class="pcols"><div>'
        '<div class="k">The objective &middot; done when <span class="h">(click to revise &mdash; one line with undo)</span></div><div class="g" data-goal-text="%s">%s</div>'
        '<div class="k">Where it stands</div><div class="stand">%s</div>%s'
        '<div class="facts3"><div class="fact"><div class="k">Pace</div><span class="v click" data-pace="%s">%s</span></div>'
        '<div class="fact"><div class="k">Deadlines</div><span class="v">%s</span></div></div>'
        '<div class="pfold">%s</div><div class="k">The guide <span class="h">(the steward writes it on your word &mdash; &ldquo;write the guide&rdquo; in the conversation &mdash; from what you dictate there and the record; revise it here; its history keeps every change)</span></div>%s'
        '<div class="obody"><div class="plist"><div class="pl-h"><h4>The plan &middot; the parts in order</h4><span class="c">%d &middot; %d dated%s</span>'
        '<span class="hint">Click a name to rename, a date to move it. A project or a step of one is read from its own record.</span></div>'
        '<ul class="rows">%s</ul>'
        '<div class="addline"><select data-add="kind"><option value="task">desk item</option><option value="project">cockpit</option></select>'
        '<input class="at" data-add="text" data-lane="%s" type="text" autocomplete="off" placeholder="Add a part">'
        '<select data-add="project" style="display:none"><option value="">which project</option>%s</select>'
        '<input class="ad" data-add="date" type="text" autocomplete="off" placeholder="2026-10-27 &middot; blank">'
        '<button class="mk" data-act="add" data-lane="%s">Add</button>'
        '<span class="ah">Enter adds it. No date and it sits in the <b>no date</b> column of the calendar view.</span></div></div></div>'
        '<div class="k">Its components <span class="h">(a cockpit, a desk item, a step of a project, a deliverable, a date; a cockpit or a desk item can be put on deck or made active &mdash; then it sits on the High Seat)</span></div>%s'
        '</div><div>'
        '<div class="k" style="margin-top:0">Brainstorm with the steward <span class="h">(dictate here &mdash; it is logged to this goal; a verb acts on the goal; the steward answers here as it writes)</span></div>'
        '<div class="gconv">%s<ul class="ex gthread" data-thread="%s">%s</ul>'
        '<div class="composer gcomp"><label class="sr" for="gsay-%s">Tell the steward about this goal</label>'
        '<textarea id="gsay-%s" class="gsay" data-goal="%s" rows="2" placeholder="add a part: &hellip; &middot; pace by Oct 10 &middot; tier 2 &middot; goal: &hellip; &middot; summarize &middot; or just talk"></textarea>'
        '<div class="comp-row"><span class="hint">Ctrl+Enter sends &middot; inside this goal nothing needs its name &middot; the steward answers here as it writes</span><button class="send gsend" data-goal="%s">Send</button></div>'
        '<div class="chips"><button data-say="write the guide">write the guide</button><button data-say="update the guide">update the guide</button><button data-say="summarize where this goal stands">summarize</button><button data-say="what is the next step?">what is the next step?</button><button data-say="what is starving here?">what is starving?</button></div></div></div>'
        '</div></div></article>'
    ) % (esc(i["id"]), esc(i["id"]), AREA_COLOURS.get(i["area"], "#8b93a6"), esc(i["name"]),
         initiative_light(i, ctx.get("working") or set()), glyph, word, esc(i["area"].title() or "no area"), esc(i["id"]), tier_opts,
         esc(i["id"]), esc(i["done_when"]) or '<span class="dim">not written yet &mdash; say what done looks like</span>',
         stands, initiative_status_html(i),
         esc(i["id"]), ("by " + esc(_short(i["pace"]))) if i.get("pace") else "set a pace",
         "<br>".join('<span class="%s">%s</span> %s' % ("over" if (_hr._iso(p["date"]) or today) < today else ("soon" if (_hr._iso(p["date"]) - today).days <= 7 else ""), esc(_short(p["date"])), esc(p["text"][:36]) + ("&hellip;" if len(p["text"]) > 36 else "")) for p in dated[:4]) or "none dated",
         _ifthen(i) + _premortem(i, ctx), _guide_block(i, ctx),
         n, len(dated), (' &middot; <span class="am">%s</span>' % _needs(len(i["needs"]))) if i["needs"] else "",
         rows or '<li class="row"><div class="rb"><span class="rt dim">no parts yet</span></div></li>', esc(i["id"]), projects, esc(i["id"]),
         proj_html,
         nudge_html(_not_dated((ctx.get("nudges") or {}).get(i["id"])), "goal"), esc(i["id"]), _thread(i, ctx), esc(i["id"]), esc(i["id"]), esc(i["id"]), esc(i["id"]))


def _places(ctx):
    return '<div id="placeSlot"></div>' + "".join(_place(i, ctx) for i in ctx["initiatives"])


# ── the board: calendar view (the same record, re-bucketed) ────────────────────────────────────

def _calendar(ctx):
    today = ctx["today"]
    weeks = ruler_weeks(today)
    inits = ctx["initiatives"]
    monday = weeks[0]["start"]

    # cells: 0 = no date (undated, and parked — a parked part is never on the ruler); 7 = before this week (a past
    # date: overdue while open, done with its date otherwise); 1–5 = the weeks; 6 = beyond the ruler
    def bucket(p):
        d = _hr._iso(p["date"]) if p["date"] else None
        if d is None or p["status"] == "parked":
            return 0
        if d < monday:
            return 7
        for k, w in enumerate(weeks):
            if w["start"] <= d <= w["end"]:
                return k + 1
        return 6
    counts = [0] * 8
    overdue = parked_dated = 0
    for i in [x for x in inits if x["status"] not in ("done", "parked")]:
        for p in i["parts"]:
            b = bucket(p)
            counts[b] += 1
            if b == 7 and p["status"] != "done" and not p["broken"]:
                overdue += 1
            if b == 0 and p["date"] and p["status"] == "parked":
                parked_dated += 1
    has_over = counts[7] > 0
    order = [0] + ([7] if has_over else []) + [1, 2, 3, 4, 5, 6]
    head = ['<div class=" nod"><b>No date</b><span class="sm">undated and parked parts</span><span class="cn">%d undated%s</span></div>' % (
        counts[0] - parked_dated, (" &middot; %d parked" % parked_dated) if parked_dated else "")]
    if has_over:
        head.append('<div class=" over"><b>Before this week</b><span class="sm">past dates</span><span class="cn">%s</span></div>' % (
            ("%d overdue" % overdue) if overdue else ("%d done" % counts[7])))
    for k, w in enumerate(weeks):
        head.append('<div class="%s"><b>%s</b><span class="sm">%s</span><span class="cn">%s</span></div>' % (
            "now" if k == 0 else "", esc(w["label"]), esc(w["name"]), ("%d dated" % counts[k + 1]) if counts[k + 1] else "nothing dated"))
    head.append('<div class=" beyond"><b>%s &rarr;</b><span class="sm">beyond the ruler</span><span class="cn">%s</span></div>' % (
        esc(_hr.short_date((weeks[-1]["end"] + timedelta(days=1)).isoformat())), ("%d dated" % counts[6]) if counts[6] else "nothing dated"))

    def chip(i, p, past):
        pdone = bool(p.get("done", p["status"] == "done"))
        pclosed = bool(p.get("closed", p["status"] in ("done", "parked")))
        late = past and not pclosed and not p["broken"]
        cls = " need" if p["needs_you"] else (" done" if pdone else (" over" if late else ""))
        tail = ('<span class="pc-f">&#9873; needs you</span>' if p["needs_you"] else
                ('<span class="pc-s ok">&#10003; done</span>' if pdone else
                 ('<span class="pc-f">overdue</span>' if late else ('<span class="pc-c">parked</span>' if (pclosed and not pdone) else ""))))
        return ('<button class="pc%s" data-act="chip" data-lane="%s" data-part="%s"><span class="pc-top"><span class="pc-d">%s</span><span class="pc-k">%s</span></span>'
                '<span class="pc-n">%s</span>%s</button>' % (cls, esc(i["id"]), esc(p["id"]), esc(_short(p["date"])) if p["date"] else "no date", esc(p["kind"]), esc(p["text"]), tail))

    def cell_class(k):
        return " now" if k == 1 else (" beyond" if k == 6 else (" over" if k == 7 else ""))

    def lane(i):
        cells = [[] for _ in range(8)]
        for p in i["parts"]:
            b = bucket(p)
            cells[b].append(chip(i, p, b == 7))
        track = "".join('<div class="cell%s">%s</div>' % (cell_class(k), "".join(cells[k])) for k in order)
        return (
            '<section class="lane" data-lane="%s" style="--areac:%s"><div class="lane-h">'
            '<button class="lane-t" data-act="toggle" data-lane="%s"><span class="lrow1"><span class="ln">%s</span><span class="larea" style="--areac:%s">%s</span></span>'
            '<span class="ldone"><span class="k">Done looks like</span>%s</span></button><span class="lmeta">%s%d parts &middot; %d dated</span></div>'
            '<div class="track">%s</div></section>' % (
                esc(i["id"]), AREA_COLOURS.get(i["area"], "#8b93a6"), esc(i["id"]), esc(i["name"]), AREA_COLOURS.get(i["area"], "#8b93a6"),
                esc(i["area"].title() or "no area"), esc(i["done_when"]) or "not written yet",
                ('<span class="fl">%s</span>' % _needs(len(i["needs"]))) if i["needs"] else "",
                len(i["parts"]), sum(1 for p in i["parts"] if p["date"] and p["status"] not in ("done", "parked") and not p["broken"]), track))

    def strip(label, word, colour, mine):
        needs = sum(1 for i in mine if i["needs"])
        dated = sum(1 for i in mine for p in i["parts"] if p["date"] and p["status"] not in ("done", "parked") and not p["broken"])
        return '<div class="tierstrip" style="--tierc:%s"><span class="tn">%s</span><span class="tw">%s</span><span class="tm">%d goal%s &middot; %s &middot; %d dated part%s</span></div>' % (
            colour, label, word, len(mine), "" if len(mine) == 1 else "s", ('<span class="am">%s</span>' % _needs(needs, "goal")) if needs else "no goal needs you", dated, "" if dated == 1 else "s")
    # the board's buckets (Grok, the W2 trim): the live tier 1, the live tier 2, the seed goals; done and parked goals stay out
    lanes = []
    live = [i for i in inits if i["status"] not in ("done", "parked")]
    for t in (1, 2):
        mine = [i for i in live if i["tier"] == t]
        lanes.append(strip("Tier %d" % t, TIER_WORDS[t], TIER_COLOURS[t], mine))
        lanes.extend(lane(i) for i in mine)
    seedy = [i for i in live if i["tier"] not in (1, 2)]
    lanes.append(strip("Seed goals", "for the future", TIER_COLOURS[3], seedy))
    lanes.extend(lane(i) for i in seedy)
    return '<div class="scroll%s" id="viewCal" style="flex:1;display:none"><div id="boardScroll"><div class="rl-head">%s</div>%s</div></div>' % (
        " has-over" if has_over else "", "".join(head), "".join(lanes))


# ── seeds, areas, the panel ────────────────────────────────────────────────────────────────────

def _seedband(ctx):
    """The seeds as a tile (John, 2026-09-27): closed by default with the count in its head; the head toggles it open to
    the seed row as it was — each seed with Make it an initiative and its two questions on the card."""
    seeds = ctx.get("seeds") or []
    if not seeds:
        row = '<div class="seed"><div class="st dim">No seeds yet.</div><div class="sw">Tell the steward &ldquo;seed: &hellip;&rdquo; on the home, or in the cockpit&rsquo;s grasscatcher.</div></div>'
    else:
        tiers = "".join('<button data-picktier="%d"%s>Tier %d%s</button>' % (t, ' class="on"' if t == 3 else "", t, " &middot; suggested" if t == 3 else "") for t in (1, 2, 3))
        areas = "".join('<button data-pickarea="%s">%s</button>' % (a, a.title()) for a in AREAS) + '<button data-pickarea="" class="on">none yet</button>'
        row = "".join('<div class="seed" data-seed="%s"><div class="st">%s</div><div class="sw">would suit <b>tier 3</b> &mdash; you choose the tier and the life area</div>'
                      '<button class="mk" data-act="promote" data-seed="%s">Make it a goal</button>'
                      '<div class="pick" hidden><div class="q">Which tier?</div><div class="prow">%s</div><div class="q">Which life area?</div><div class="prow">%s</div>'
                      '<div class="prow"><button class="go" data-pickgo="%s">Create it in tier 3</button><button class="cancel" data-pickcancel="1">cancel</button></div></div></div>'
                      % (esc(s["id"]), esc(s["text"]), esc(s["id"]), tiers, areas, esc(s["id"])) for s in seeds)
    return ('<section class="seedband" id="seedband" aria-label="Seeds"><button class="sb-h" id="seedToggle" aria-expanded="false"><span class="t">Seeds</span>'
            '<span class="c" id="seedCount"><b>%d</b> idea%s, not yet goals</span>'
            '<span class="note">Making one a goal asks for its tier and its life area on the card &mdash; nothing is created until Create it.</span>'
            '<span class="tog" id="seedTog">Show</span></button><div class="seedrow" id="seedRow">%s</div></section>'
            % (len(seeds), "" if len(seeds) == 1 else "s", row))


def _areas(ctx):
    inits = ctx["initiatives"]
    counts = {a: sum(1 for i in inits if i["area"] == a) for a in AREAS}
    chips = "".join('<button class="ac" data-area="%s" style="--c:%s"><i></i>%s <b>%d</b></button>' % (a, AREA_COLOURS[a], a.title(), counts[a]) for a in AREAS if counts[a])
    t = {k: sum(1 for i in inits if i["tier"] == k) for k in (1, 2, 3)}
    top = max(AREAS, key=lambda a: counts[a]) if inits else None
    note = "Click an area to hold the board to it.%s" % (
        (" <b style=\"color:%s\">%s</b> carries %d." % (AREA_COLOURS[top], top.title(), counts[top])) if top and counts[top] > 1 else "")
    return '<div class="areas" id="areas">%s<span class="note">%s</span></div>' % (chips or '<span class="note">no areas yet</span>', note)


def brief_bullets(ctx):
    inits = [i for i in ctx["initiatives"] if i["status"] not in ("done", "parked")]      # the board's live goals (Grok, the W2 trim)
    today = ctx["today"]
    out = []
    t1 = [i for i in inits if i["tier"] == 1]
    dated = sorted(((p["date"], p, i) for i in inits for p in i["parts"] if p["date"] and not p["broken"] and p["status"] not in ("done", "parked")), key=lambda x: x[0])
    ahead = next(((d, p, i) for d, p, i in dated if _hr._iso(d) and _hr._iso(d) >= today), None)
    if t1:
        out.append("<b>Tier 1</b> holds %s.%s" % (" &middot; ".join(esc(i["name"]) for i in t1),
                   (" The nearest hard date is <b>%s</b>, on <b>%s</b> in %s (tier %d)." % (esc(_short(ahead[0])), esc(ahead[1]["text"]), esc(ahead[2]["name"]), ahead[2]["tier"])) if ahead else " Nothing in the Campaign carries a date yet."))
    else:
        out.append("No Tier 1 goal yet &mdash; give one a tier.")
    mon = today - timedelta(days=today.weekday()); sun = mon + timedelta(days=6)
    week = [(d, p, i) for d, p, i in dated if _hr._iso(d) and mon <= _hr._iso(d) <= sun]
    if week:
        out.append("This week, %s: %s." % (esc(_hr.week_in_words(today).replace("this week ", "")), "; ".join("%s (%s, %s)" % (esc(p["text"]), esc(_short(d)), esc(i["name"])) for d, p, i in week[:3])))
    else:
        out.append("This week, %s: <b>nothing in the Campaign is dated inside it</b>.%s" % (
            esc(_hr.week_in_words(today).replace("this week ", "")), (" The first mark is %s." % esc(_short(ahead[0]))) if ahead else ""))
    needs = [(p, i) for i in inits for p in i["needs"]]
    if needs:
        out.append('<span class="amberword">&#9873; %d part%s need%s you</span>, %d with no date. In tier order: %s%s.' % (
            len(needs), "" if len(needs) == 1 else "s", "s" if len(needs) == 1 else "", sum(1 for p, i in needs if not p["date"]),
            " &middot; ".join('<button class="goto" data-goto="%s">%s</button> (tier %s)' % (esc(i["id"]), esc(p["text"]), i["tier"] or "?") for p, i in needs[:3]),
            (" &hellip; and %d more" % (len(needs) - 3)) if len(needs) > 3 else ""))
    else:
        out.append("Nothing in the Campaign waits on your word.")
    counts = {a: sum(1 for i in inits if i["area"] == a) for a in AREAS}
    out.append("Across your life: %s. <span class=\"n\">%d</span> seed%s sit%s in Seed goals." % (
        " &middot; ".join("%s <span class=\"n\">%d</span>" % (a.title(), counts[a]) for a in AREAS if counts[a]) or "no areas yet",
        len(ctx.get("seeds") or []), "" if len(ctx.get("seeds") or []) == 1 else "s", "s" if len(ctx.get("seeds") or []) == 1 else ""))
    return out


def look_ahead(ctx):
    """The look-ahead (the Star Chart, 2026-10-03; it took the brief's place): what is coming up in the next seven days,
    the Tier-1/2 goals behind their pace, the goals starving (each with Open · Not now · Park), and one preparation -
    all read from the record. A dated item within three days is named here only; its alert is the Cave's interrupt lane."""
    inits = [i for i in ctx["initiatives"] if i["status"] not in ("done", "parked")]
    today = ctx["today"]
    dated = sorted(((_hr._iso(p["date"]), p, i) for i in inits for p in i["parts"]
                    if p["date"] and not p["broken"] and p["status"] not in ("done", "parked") and _hr._iso(p["date"])), key=lambda x: x[0])
    soon = [(d, p, i) for d, p, i in dated if today <= d <= today + timedelta(days=7)]
    items = []
    if soon:
        items.append('<li><b>Coming up:</b> %s.</li>' % " &middot; ".join(
            '%s %s (%s)%s' % (esc(_short(d.isoformat())), esc(p["text"][:60]), esc(i["name"]),
                              ' <span class="dim">its alert is on the %s</span>' % esc(ctx["steward"]["high_seat_name"]) if (d - today).days <= 3 else "")
            for d, p, i in soon[:4]))
    else:
        nxt = next(((d, p, i) for d, p, i in dated if d >= today), None)
        items.append('<li><b>Coming up:</b> nothing dated in the next seven days%s.</li>' % (
            (" &middot; the first is %s, %s (%s)" % (esc(_short(nxt[0].isoformat())), esc(nxt[1]["text"][:60]), esc(nxt[2]["name"]))) if nxt else ""))
    behind = []
    for i in inits:
        if i["tier"] not in (1, 2):
            continue
        pace = _hr._iso(i.get("pace") or "")
        n = int(i.get("part_count") or 0); done = int(i.get("done_count") or 0)
        if not pace:
            if i["tier"] == 1:
                behind.append('%s has no pace set' % esc(i["name"]))
            continue
        if pace < today and done < n:
            behind.append('%s is past its pace (%s) with %d of %d parts done' % (esc(i["name"]), esc(_short(pace.isoformat())), done, n))
        elif n and (pace - today).days <= 14 and done < n / 2:
            behind.append('%s paces to %s with %d of %d parts done' % (esc(i["name"]), esc(_short(pace.isoformat())), done, n))
    if behind:
        items.append('<li><b>Behind pace:</b> %s.</li>' % "; ".join(behind[:4]))
    starving = [(gid, n) for gid, n in (ctx.get("nudges") or {}).items() if isinstance(n, dict) and n.get("kind") == "starving"]
    names = {i["id"]: i["name"] for i in inits}
    for gid, n in starving[:3]:
        items.append('<li class="starve"><b>Starving:</b> %s <span class="lacts"><button class="mini" data-goto="%s">Open</button>'
                     '<button class="mini" data-nudge-act="not_now" data-key="%s" data-fact="%s" data-text="%s">Not now</button>'
                     '<button class="mini" data-look-park="%s" title="to the boneyard, with undo">Park</button></span></li>' % (
                         esc(n.get("text") or names.get(gid, gid)), esc(gid), esc(n.get("key") or ""), esc(n.get("fact") or ""), esc((n.get("text") or "")[:200]), esc(gid)))
    first = next(((d, p, i) for d, p, i in dated if d >= today), None)
    if first:
        items.append('<li><b>One preparation:</b> the nearest date is %s (%s), due %s &mdash; ready it before the week fills.</li>' % (
            esc(first[1]["text"][:80]), esc(first[2]["name"]), esc(_short(first[0].isoformat()))))
    return ('<section class="lookahead" id="lookAhead"><div class="kicker">The look-ahead <span class="k-when">the next seven days, from %s</span></div><ul class="blist">%s</ul>'
            '<div class="lane-note">The nudges that are not urgent wait here instead of interrupting.</div></section>') % (
        esc(today.strftime("%A %d %B").replace(" 0", " ")), "".join(items))


def _lead(ctx):
    """The brief's lead when a set exists: the head as the High Seat reads it - a part that needs him in an active
    initiative, else the tiers, else the pick-up while the set runs - with an open to its tile."""
    return None      # Grok (the W2 trim): the set-first lead went with the Active band; the High Seat's head keeps head_act
    inits = ctx["initiatives"]
    working = ctx.get("working") or set()
    head = _ha.head_act(inits, [], today=ctx["today"])
    pk = _ha.pick_up(inits, [], working=working, today=ctx["today"])
    name = (head or {}).get("initiative") or (pk or {}).get("initiative") or ""
    hit = next((i for i in inits if i["name"] == name), None)
    goto = (' <button class="goto" data-goto="%s">open</button>' % esc(hit["id"])) if hit else ""
    return esc(_ha.head_sentence(head, pickup=pk)) + goto


def _panel(ctx):
    """The steward's column (W2b-3, 2026-09-30, his word: the dialogue "should open up and fill the whole open space on
    the right below the brief, it should be interactive and able for me to follow what is going on, ask, discuss";
    W2c-3: the cockpit's shape): the brief, then the DIALOGUE filling the rest of the column - the one conversation log
    of the Campaign's cockpit (the last 40 turns; a turn said from a goal's place carries the goal's chip, which opens
    the goal), live from the moment the page opens (the script polls the cockpit's own stream), the steward's state at
    its head - and the composer at the column's foot. A login box, hidden until a read is refused (Grok's read of
    W2c-3: the refusal is answered on the page he is looking at)."""
    st = ctx["steward"]
    return (
        # the brief is gone (John, 2026-10-03: "I don't think that it helps"); the look-ahead takes its place
        '<aside class="panel" aria-label="The steward">%s'
        '%s'
        '<div class="loginbox" id="loginBox" hidden><span class="lb-t">This browser is not logged in to Anchor.</span>'
        '<input id="loginTok" type="password" placeholder="paste the token here" autocomplete="off" spellcheck="false">'
        '<button class="mini" id="loginGo">Log in</button><span class="lb-msg" id="loginMsg"></span></div>'
        '<section class="composer"><label class="sr" for="say">Tell the steward what to do</label>'
        '<textarea id="say" rows="2" placeholder="Ask %s, discuss, or tell it what to do &mdash; it runs the %s: move &hellip; to tier 2, add a part to &hellip;, &hellip; by Oct 10"></textarea>'
        '<div class="comp-row"><span class="hint">Ctrl+Enter sends &middot; the steward answers above as it writes; when it changes the record the board reloads with the receipt</span><button class="send" id="sendBtn">Send</button></div>'
        '<div class="receipt" id="receipt" hidden><span class="r-mark">&#10003;</span><span id="receiptText"></span> <button class="mini" id="undoBtn" hidden>undo</button></div></section>'
        '</aside>'
    ) % (look_ahead(ctx), conversation_view(st["label"], ctx.get("pid") or "", "campaign", "", "the " + mode_name(st)), esc(st["label"]), esc(mode_name(st)))


# ── the page ───────────────────────────────────────────────────────────────────────────────────

def render_campaign_html(ctx, open_id=None) -> str:
    st = ctx["steward"]
    inits = ctx["initiatives"]
    ctx["n_total"] = len(inits)
    tiers = {k: sum(1 for i in inits if i["tier"] == k) for k in (1, 2, 3)}
    n_parts = sum(len(i["parts"]) for i in inits)
    n_dated = sum(1 for i in inits for p in i["parts"] if p["date"] and not p["broken"] and p["status"] not in ("done", "parked"))
    n_needs = sum(len(i["needs"]) for i in inits)
    live = [i for i in inits if i["status"] not in ("done", "parked")]
    n_bone = len(inits) - len(live)
    n_seedy = sum(1 for i in live if i["tier"] not in (1, 2))      # Tier 1 + Tier 2 + seed goals = the goals; the seeds fold keeps its own idea count
    n_parts = sum(len(i["parts"]) for i in live)
    n_dated = sum(1 for i in live for p in i["parts"] if p["date"] and not p["broken"] and p["status"] not in ("done", "parked"))
    n_needs = sum(len(i["needs"]) for i in live)
    board = (
        '<section class="board" aria-label="The %s" data-place="%s"><div class="colk"><h3 id="viewTitle">The goals</h3>'
        '<span class="c" id="boardCount">%d goals &middot; Tier 1 %d &middot; Tier 2 %d &middot; seed goals %d &middot; the boneyard %d &middot; %d parts &middot; %d dated%s</span>'
        '<span class="rule"></span><button class="viewbtn" id="viewBtn">&#128197; Calendar view</button><button class="mini" id="closeAll">Close the goal</button></div>'
        '%s%s%s%s'
        '<p class="boardfoot" id="boardFoot">Drag a goal into another tier or into Seed goals; there is no order inside a tier. Click a name for its place &mdash; every change is one line with undo.</p></section>'
    ) % (esc(mode_name(st)), esc(open_id or ""), len(live), sum(1 for i in live if i["tier"] == 1), sum(1 for i in live if i["tier"] == 2), n_seedy, n_bone, n_parts, n_dated, (' &middot; <span style="color:var(--amber-t);font-weight:700">%s</span>' % _needs(n_needs)) if n_needs else "",
         _areas(ctx), _bands(ctx), _places(ctx), _calendar(ctx))
    hdr = (
        '<div class="hdr"><h2 class="modeh">%s</h2>'
        '<button class="tool doctor" data-tool="doctor">&#10010; Anchor Doctor</button><button class="tool" data-tool="zombie">%sZombie Hunter</button><button class="tool" data-tool="foundry">%sSkill Foundry</button>'
        '<a class="tool" href="/steward/v1?pid=%s&amp;dir=" target="_blank" rel="noopener" title="this conversation in its cockpit, full size">%s — AI Cockpit</a><div class="date">%s</div></div>'
    ) % (esc(mode_name(st)),
         _brand_img(ctx["build"], "zombie-hunter-radar.jpg"), _brand_img(ctx["build"], "skill-foundry-icon.jpg"), esc(ctx["pid"]), esc(mode_name(st)), esc(ctx["today_str"]))
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>%s</title>%s'
        '<link rel="stylesheet" href="/static/steward-dialogue.css?v=%s"><link rel="stylesheet" href="/static/campaign-page.css?v=%s">'
        '<script>window.ANCHOR_BOOT = {build_id: "%s", campaign_pid: "%s", stamp: "%s", steward: "%s", you: "%s"};</script></head>'
        '<body><div class="page">%s%s<div class="prefs">%s</div><div class="canvas">%s%s</div>'
        '<div class="foot">%s<span>A <b class="gwl-accent">Ghost World Labs</b> tool &middot; Powered by NextGen Nuclear &middot; AI Cockpit &middot; J.C. Liechty</span>'
        '<span>&mdash; every goal, part, date and count on this page is read from the Campaign record; a project part is read from its own record.</span></div></div>'
        '<script src="/steward-static/md.js?v=%s"></script><script src="/static/steward-dialogue.js?v=%s"></script><script src="/static/campaign-page.js?v=%s"></script></body></html>'
    ) % (esc(mode_name(st)), tab_icon_link(st.get("high_seat") or st.get("seal"), ctx["build"], anchor=False), esc(ctx["build"]), esc(ctx["build"]), esc(ctx["build"]), esc(ctx["pid"]), esc(str(ctx.get("stamp") or "")), esc(st["label"]), esc(HIS_NAME), _masthead(ctx, mode=True), hdr, ctx.get("prefs_html") or "", board, _panel(ctx),
         _brand_img(ctx["build"], "gwl-m-icon.svg"), esc(ctx["build"]), esc(ctx["build"]), esc(ctx["build"]))
