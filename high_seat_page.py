"""high_seat_page — the High Seat: Anchor's home as the steward's portfolio surface.

W1b of the High Seat plan (2026-09-26). The approved design is the mockup
``Skill Foundry/planning/high-seat-2026-09-24/ideation/mockups/r5/10-high-seat.html`` (John's
picks of 2026-09-25/26); its stylesheet is ``static/high-seat-page.css`` ported as it is. This
module renders that page from FACTS — the registry, each project's steward record (home_rows),
the ranked rows and the brief (home_attention), the session registry, the Campaign record when
it exists — with no model call and no bridge spawn on the request. Pure: it takes a context
dict the application builds (``anchor_gui._high_seat_context``) and returns HTML. Every number
on the page is read from a record or is an honest "not connected / not measured yet".
"""
from __future__ import annotations

import html
import re
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote as _quote

import home_rows as _hr

from high_seat_core import (
    _OPEN,
    _TIER_WORDS,
    HIS_NAME,
    INITIATIVE_KINDS,
    KIND_LABEL,
    KIND_WORDS,
    LIGHTS,
    NOGOAL_ID,
    SEAT_NAMES,
    SEAT_WORDS,
    campaign_initiatives,
    candidates_model,
    desk_counts,
    esc,
    goals_only,
    initiative_light,
    initiative_line,
    is_initiative,
    loose_initiative,
    mode_name,
    part_name,
    proactive_triage_cards,
    relevance,
    ruler_markers,
    ruler_weeks,
    seated,
    short_date as _short,
    this_week_horizon_buckets,
)


def initiative_status_html(i):
    """The Status of an opened initiative (John: "the status is missing"): each project part's own steward status —
    its last lead line, read from its record. Only that (Grok R8): the wait and the counts are already on the tile.
    A part without a recorded status says so."""
    rows = []
    for p in i.get("parts") or ():
        if p.get("kind") != "project":
            continue
        lead = " ".join(str(p.get("lead") or "").split())[:220]
        rows.append('<div class="isrow"><a href="%s" target="_blank" rel="noopener">%s</a> &mdash; %s</div>' % (
            esc(p.get("href") or "#"), esc(p.get("target") or p.get("text") or "project"), esc(lead) or "no status recorded yet"))
    return '<div class="istatus"><span class="k">Status</span>%s</div>' % (
        "".join(rows) or '<div class="isrow dim">No project part yet &mdash; the parts below carry their own states.</div>')


# ── pieces ─────────────────────────────────────────────────────────────────────────────────────

ANCHOR_ICON_SIZES = "16x16 32x32 48x48 64x64 128x128 256x256"   # the sizes inside his anchor-icon.ico
ANCHOR_TAB_SIZES = "16x16 32x32 48x48"                           # the sizes inside anchor-tab.ico, the tab drawing
BRAND_DIR = Path(__file__).parent / "vendor" / "brand"


def anchor_tab_stem(brand=None):
    """Which anchor a browser tab wears. His export (anchor-icon.*) is a dark painting: scaled to 16 px on a dark tab
    strip it read as no icon at all (his tab strip, captured 2026-10-01: "where are my icons in Chrome tabs?"). When the
    tab drawing of the same anchor is there (anchor-tab.ico + its 32 and 16 px PNGs - his painting redrawn for the small
    sizes) the tab wears that; his export stays the large icon (the touch icon, the desktop, the app). None = no anchor."""
    brand = brand or BRAND_DIR
    if all((brand / f).is_file() for f in ("anchor-tab.ico", "anchor-tab-32.png", "anchor-tab-16.png")):
        return "anchor-tab"
    if (brand / "anchor-icon.ico").is_file() and (brand / "anchor-icon-32.png").is_file():
        return "anchor-icon"
    return None


def tab_icon_link(name, build, anchor=None):
    """A page's tab icon. His rule (2026-10-01 18:1x): "the cave of wonders and the campaign web pages should have the
    cave of wonders icon in the tab; the rest of the other tabs should have the new anchor icon." So the High Seat and
    the Campaign page call this with ``anchor=False`` and the steward's High Seat picture; every other page wears the
    anchor (``anchor`` None = when the files exist): the set he dropped into vendor/brand at 13:12, its small sizes from
    the tab drawing when that is there (``anchor_tab_stem``), the 180 px touch icon always his export.
    The picture rule (2026-09-30: "the icons in the web page tabs are missing"): a steward's 1024-px JPEG
    is too large for a browser tab, so the small PNG beside it stands in when it exists (vendor/brand/<stem>.png - a
    bright tile with the steward's initial, legible at 16 px); an SVG or a small image is linked as it is."""
    stem = anchor_tab_stem() if anchor is None or anchor else None
    if anchor is None:
        anchor = bool(stem)
    if anchor:
        v, stem = esc(build), stem or "anchor-icon"
        touch = ('<link rel="apple-touch-icon" sizes="180x180" href="/vendor/brand/anchor-icon-180.png?v=%s">' % v)
        return ('<link rel="icon" href="/vendor/brand/%s.ico?v=%s" sizes="%s">'
                '<link rel="icon" type="image/png" sizes="32x32" href="/vendor/brand/%s-32.png?v=%s">'
                '<link rel="icon" type="image/png" sizes="16x16" href="/vendor/brand/%s-16.png?v=%s">'
                % (stem, v, ANCHOR_TAB_SIZES if stem == "anchor-tab" else ANCHOR_ICON_SIZES, stem, v, stem, v)) + touch
    base = str(name or "gwl-m-icon.svg")
    stem, _, ext = base.rpartition(".")
    if ext.lower() in ("jpg", "jpeg") and (BRAND_DIR / (stem + ".png")).is_file():
        return '<link rel="icon" href="/vendor/brand/%s.png?v=%s" type="image/png" sizes="64x64">' % (esc(stem), esc(build))
    ctype = "image/svg+xml" if ext.lower() == "svg" else ("image/png" if ext.lower() == "png" else "image/jpeg")
    return '<link rel="icon" href="/vendor/brand/%s?v=%s" type="%s">' % (esc(base), esc(build), ctype)


_ANY_ICON_LINK = re.compile(r'<link\b[^>]*\brel=["\'](?:shortcut icon|icon)["\'][^>]*>', re.I)
_OLD_ANCHOR_LINK = re.compile(r'<link\b[^>]*\brel=["\'](?:shortcut icon|icon|apple-touch-icon)["\'][^>]*\bhref=["\'](?:/anchor(?:-touch)?\.(?:ico|png)|/vendor/brand/anchor-icon[-.])[^"\']*["\'][^>]*>\s*', re.I)
_HEAD_OPEN = re.compile(r"<head\b[^>]*>", re.I)
_HEAD_CLOSE = re.compile(r"</head\s*>", re.I)
_SCRIPT_OR_BODY = re.compile(r"<(?:script|body)\b", re.I)


def with_tab_icon(html_text, build):
    """Every page the server sends wears his anchor in its tab (2026-10-01, his fourth ask: "where are my icons in
    Chrome tabs?"). What his tab strip showed: the Desk still linked the lamp painting, the cockpit linked the old
    /anchor.ico with no version (Chrome keeps a tab icon it has seen for a week, whatever the cache header says), and a
    page with no link at all waited on /favicon.ico. One rule at the one door (``_send_html``), and only once the tab
    drawing is on disk (his dark export is never written onto a tab that has something else - Grok W3d): a page that
    already links the drawing is left; the old anchor links (/anchor.ico, /anchor.png, his export's set) become the
    drawing's set, with the build in the address so a new icon is a new address; a page with no icon gets the set; a
    page with a mark of its own (a tool's) keeps it. Only a real head is touched: the one that opens before any script
    or body and closes with </head>."""
    if anchor_tab_stem() != "anchor-tab":
        return html_text
    window = html_text[:4096]
    m = _HEAD_OPEN.search(window)
    first = _SCRIPT_OR_BODY.search(window)
    close = _HEAD_CLOSE.search(html_text, m.end()) if m else None
    if not m or not close or (first and first.start() < m.start()):
        return html_text
    head = html_text[m.end():close.start()]
    if "/vendor/brand/anchor-tab.ico" in head:
        return html_text
    bare = _OLD_ANCHOR_LINK.sub("", head)
    if _ANY_ICON_LINK.search(bare):
        return html_text                                       # a mark of its own
    return html_text[:m.end()] + tab_icon_link(None, build) + bare + html_text[close.start():]


def _brand_img(build, name, cls=""):
    return '<img%s src="/vendor/brand/%s?v=%s" alt="" onerror="this.style.display=\'none\'">' % (
        (' class="%s"' % cls) if cls else "", esc(name), esc(build))


def capacity_row_html(c):
    """One capacity line (W4): the name, the two bars when a run reported the account's windows (amber over 80%),
    the state in words, the note that says what the row cannot see."""
    bars = "".join(
        '<span class="wbar"><span class="wl">%s</span><span class="bar%s"><b style="width:%d%%"></b></span><span class="p%s">%s</span></span>' % (
            esc(b.get("label")), " warn" if b.get("warn") else "",
            int(b.get("pct") or 0), " warn" if b.get("warn") else "", ("%d%%" % int(b["pct"])) if b.get("pct") is not None else "?")
        for b in (c.get("bars") or []) if isinstance(b, dict))
    sub = (('<span class="amberword">%s</span> &middot; ' % esc(c.get("amber"))) if c.get("amber") else "") + esc(c.get("note"))
    state = esc(c.get("state"))
    short = len(str(c.get("state") or "")) <= 24 and not bars     # a short state sits beside the name, as the mockup's rows do
    return ('<div class="cr"><div class="cr-top"><span class="cr-n">%s</span>%s%s</div>%s<div class="cr-sub">%s</div></div>'
            % (esc(c.get("name")), bars, ('<span class="cr-none">%s</span>' % state) if short else "",
               "" if short else '<div class="cr-state">%s</div>' % state, sub))


def _rail(ctx):
    st = ctx["steward"]
    counts = ctx.get("counts") or {}
    n_camp = len(goals_only(ctx.get("initiatives")))
    live_inits = [i for i in ctx.get("initiatives") or [] if i.get("status") not in ("done", "parked")]
    n_active, n_deck = len(seated(live_inits, "active")), len(seated(live_inits, "deck"))     # W2c: the shelves
    n_bench = int(ctx.get("terms_open") or 0)      # the Cave's plain terminals open now (the Workbench retired 2026-10-02)
    cap_rows = "".join(capacity_row_html(c) for c in ctx.get("capacity") or ())
    return (
        '<nav class="rail">'
        '<div class="provider-rail-head"><button id="setup-gear" class="setup-gear" type="button" aria-label="Setup settings" title="Setup settings">&#9881;</button><span class="provider-rail-brand">%sAnchor</span></div>'
        '<div class="lockup">%s<div class="wordmark">Ghost World <span class="gwl-accent">Labs</span></div></div>'
        '<div class="gwl-badge">Powered by NextGen Nuclear %s</div>'
        '<div class="railseat">%s<h1>The %s</h1></div>'   # the Cave's picture alone (his word 2026-10-02); the anchor stays by the word Anchor
        '<div class="sub">Anchor &middot; the whole portfolio, ranked</div>'
        '<div class="navk">Destinations</div>'
        '<ul class="nav" id="railNav">'
        '<li><button data-rail="seat"><span class="n">%s</span><span class="c">nudges</span></button></li>'
        '<li><button data-rail="campaign"><span class="n">%s</span><span class="c">%s</span></button></li>'
        '<li><button data-rail="active"><span class="n">Active</span><span class="c">%d</span></button></li>'
        '<li><button data-rail="week"><span class="n">This week</span><span class="c">%s</span></button></li>'
        '<li><button data-rail="desk"><span class="n">Desk</span><span class="c">%d</span></button></li>'
        '<li><button data-rail="deck"><span class="n">On deck</span><span class="c">%d</span></button></li>'
        '<li><button data-rail="calendar"><span class="n">Calendar</span><span class="c">not connected</span></button></li>'
        '<li><button data-rail="email"><span class="n">Email</span><span class="c">not connected</span></button></li>'
        '<li><button data-rail="term"><span class="n">Terminal</span><span class="c" id="railTerm">%d</span></button></li>'
        '</ul>'
        '<details class="cap provider-history" open><summary>Connections &amp; capacity &middot; Providers</summary><div id="capList">%s</div></details>'
        '<div id="cave-provider-controls" class="provider-controls" aria-label="Provider and quality for new work">'
        '<div><label for="cave-family">Provider</label><select id="cave-family" aria-label="Provider"></select></div>'
        '<div><label for="cave-account">Account</label><select id="cave-account" aria-label="Account"></select></div>'
        '<div><label for="cave-model">Model</label><select id="cave-model" aria-label="Model"></select></div>'
        '<div><label for="cave-effort">Reasoning</label><select id="cave-effort" aria-label="Reasoning"></select></div>'
        '<button id="cave-provider-apply" type="button">Apply to new work</button><button id="cave-provider-settings" type="button">Provider details / Setup</button>'
        '<p id="cave-provider-message" class="provider-control-message" role="status"></p></div>'
        '</nav>'
    ) % (anchor_mark(ctx["build"]), _brand_img(ctx["build"], "gwl-m-icon.svg"), _brand_img(ctx["build"], "gwl-m-icon.svg"),
         _brand_img(ctx["build"], st["high_seat"], ""), esc(st["high_seat_name"]),
         esc(st["high_seat_name"]), esc(mode_name(st)), (str(n_camp) if ctx.get("campaign") else "not yet"), n_active,
         esc(ctx["week_short"]), int(ctx.get("tasks_open") or 0), n_deck, n_bench, cap_rows)


def anchor_mark(build, px=26):
    """His anchor wherever a page drew the old anchor glyph beside the word Anchor (his word, 2026-10-01 18:5x: "there
    are some anchor icons embedded in the cave of wonder page upper left hand side that need to be updated. Same with
    the Campaign page"): the tab drawing at ``px``, the page's own size for it."""
    return ('<img class="anchor-mark" src="/vendor/brand/anchor-tab-48.png?v=%s" alt="" width="%d" height="%d" '
            'style="border-radius:%dpx;vertical-align:middle;flex:none">'
            % (esc(build), px, px, max(4, px // 4)))


def _masthead(ctx, mode=False):
    """The masthead every High Seat page shares: Anchor, the Ghost World Labs lockup, then — at the very top — the
    steward: its High Seat image, the seat's name, who serves. (The AI Cockpit pill left it on his word, 2026-09-30;
    the footer keeps the tagline.) ``mode``: the Campaign page wears its mode's picture and name instead (the Star
    Chart, the Chart Room, the Beacon - his accepted mockup, 2026-10-03)."""
    b = ctx["build"]
    st = ctx.get("steward") or {}
    if st and mode:
        stew = '<div class="mh-stew" title="your steward in its goals-and-foresight mode">%s<div><b>%s</b><span>%s &middot; goals and foresight</span></div></div>' % (
            _brand_img(b, st.get("campaign_icon") or st.get("high_seat") or "", "mh-seat"), esc(mode_name(st)), esc(st.get("label") or "the steward"))
    else:
        stew = ('<div class="mh-stew" title="your steward">%s<div><b>%s</b><span>%s &middot; your steward</span></div></div>' % (
            _brand_img(b, st.get("high_seat") or "", "mh-seat"), esc(st.get("high_seat_name") or "High Seat"), esc(st.get("label") or "the steward"))) if st else ""
    return (
        '<div class="masthead"><div class="mh-title">%sAnchor</div><div class="mh-div"></div>'
        '<div class="mh-lock">%s<div><div class="mh-w1">Ghost World <span class="gwl-accent">Labs</span></div>'
        '<div class="mh-w2">R&amp;D Mission Control</div></div></div><div class="mh-sp"></div>%s</div>'
    ) % (anchor_mark(b), _brand_img(b, "gwl-m-icon.svg", "mh-mark"), stew)


def _health_banner(ctx):
    """The health banner along the top (his word, 2026-10-02: "the health banner got removed from the Cave of Wonders
    ... I'd like you to have something that shows the health banner so I can do the Anchor Doctor, use Zombie Hunter").
    Shown only when the morning's self-test found issues; the Doctor and the Zombie Hunter one click away."""
    rows = [r for r in ctx.get("rows") or () if r.get("rule") == "health"]
    if not rows:
        return ""
    r = rows[0]
    href = str(r.get("href") or "/doctor")
    plain_list = r.get("plain_issues") or []
    pills_html = ""
    if plain_list:
        pills_html = '<span class="hb-pills">' + "".join(
            '<span class="hb-pill">%s</span>' % esc(str(p)[:110]) for p in plain_list[:3]
        ) + '</span>'
    return ('<div class="healthbar" role="alert"><span class="hb-mark">&#9888;</span>'
            '<span class="hb-t"><b>%s</b> &middot; %s%s</span>'
            '<button type="button" class="tool hb-fix" data-hb-act="resolve-all" title="Probe live endpoints now and auto-verify/clear if passing">&#9889; One-Click Fix &amp; Verify</button>'
            '<a class="tool" href="%s" target="_blank" rel="noopener">Diagnose</a>'
            '<button type="button" class="tool doctor" data-tool="doctor">&#10010; Anchor Doctor</button>'
            '<button type="button" class="tool" data-tool="zombie">%sZombie Hunter</button>'
            '<button type="button" class="tool hb-dismiss" data-hb-act="dismiss" title="Dismiss banner for this report" aria-label="Dismiss health banner">&#10005;</button></div>') % (
        esc(r.get("text") or "Health check found issues"), esc(r.get("why") or ""), pills_html, esc(href), _brand_img(ctx["build"], "zombie-hunter-radar.jpg"))


def _hdr(ctx):
    st = ctx["steward"]
    b = ctx["build"]
    return (
        '<div class="hdr"><h2>%s</h2><span class="who">%s</span>'
        '<button class="tool doctor" data-tool="doctor">&#10010; Anchor Doctor</button>'
        '<button class="tool" data-tool="zombie">%sZombie Hunter</button>'
        '<button class="tool" data-tool="foundry">%sSkill Foundry</button>'
        '<div class="date">%s &middot; %s</div></div>'
    ) % (esc(st["high_seat_name"]), esc(st["label"]), _brand_img(b, "zombie-hunter-radar.jpg"),
         _brand_img(b, "skill-foundry-icon.jpg"), esc(ctx["today_str"]), esc(ctx["week"]))


KIND_WORDS = {"project": "cockpit", "effort": "cockpit within", "task": "desk item", "step": "a step of a project", "deliverable": "deliverable", "calendar": "date"}
SEAT_WORDS = {"active": "active", "deck": "on deck"}
SEAT_NAMES = {"active": "Active", "deck": "On deck"}


def _goal_rows(ctx, live, camp_pid):
    """The goals expanded (W2c, 2026-09-30, his three levels): each goal a row that opens to its components. An
    initiative in its goal (a cockpit, a cockpit within a project, a desk item) drags out to a shelf or takes a button;
    a seated one is marked and comes back; an element (a step, a deliverable, a date) rides inside its goal."""
    working = ctx.get("working") or set()
    rows = []
    for i in goals_only(live):
        comps = [p for p in i["parts"] if not p.get("closed")]
        out = [p for p in comps if p.get("seat")]
        home = [p for p in comps if not p.get("seat")]      # what is still inside the goal: every open component with no seat (Grok's read of W2c)
        light = initiative_light(i, working)
        glyph, word = LIGHTS[light]

        def irow(p):
            kind = KIND_WORDS.get(p["kind"], p["kind"])
            name = esc(part_name(p))
            if p.get("broken"):
                return '<div class="irow broken"><span class="kind">%s</span><span class="nm">%s</span><span class="el">broken reference: %s</span></div>' % (kind, esc(p.get("text") or name), esc(p.get("gap") or ""))
            if not is_initiative(p):      # an element is named for what it is, its project as the suffix
                where = (' <span class="dim">&middot; %s</span>' % esc(p["target"])) if p.get("target") else ""
                return '<div class="irow el"><span class="kind">%s</span><span class="nm">%s%s</span><span class="el">rides inside &mdash; not pulled out on its own</span></div>' % (kind, esc(p.get("text") or name), where)
            if p.get("seat"):
                return ('<div class="irow seated" data-step="%s"><span class="kind">%s</span><span class="nm">%s</span><span class="seat %s">%s</span>'
                        '<button class="mini" data-home="%s" title="back into this goal">back</button></div>') % (
                    esc(p["id"]), kind, name, p["seat"], SEAT_WORDS[p["seat"]], esc(p["id"]))
            need = ' <span class="need">&#9873; needs you</span>' if p.get("needs_you") else ""
            return ('<div class="irow" draggable="true" data-step="%s" data-name="%s"><span class="kind">%s</span><span class="nm">%s%s</span>'
                    '<span class="acts"><button class="mini" data-seat="deck" data-step="%s">&rarr; on deck</button><button class="mini" data-seat="active" data-step="%s">&rarr; active</button></span></div>') % (
                esc(p["id"]), name, kind, name, need, esc(p["id"]), esc(p["id"]))
        tier_word = ("tier %d" % i["tier"]) if i["tier"] in (1, 2) else "seed goal"
        n_act, n_deck = sum(1 for p in out if p["seat"] == "active"), sum(1 for p in out if p["seat"] == "deck")
        summary = "%d in the goal" % len(home) + ((" &middot; out: %s" % ", ".join(x for x in (("%d active" % n_act) if n_act else "", ("%d on deck" % n_deck) if n_deck else "") if x)) if out else "")
        rows.append(
            '<div class="grow%s" data-g="%s"><div class="gh"><b class="gn">%s</b><span class="t">%s</span><span class="ilight %s">%s %s</span><span class="c">%s</span>'
            '<a class="gopen" href="/project/%s?open=%s" target="_blank" rel="noopener" title="its place on the %s">its place &#8599;</a></div>'
            '<div class="inits">%s</div></div>' % (
                " needs" if i["needs"] else "", esc(i["id"]), esc(i["name"]), tier_word, light, glyph, word, summary,
                esc(camp_pid), esc(i["id"]), esc(mode_name(ctx.get("steward"))),
                "".join(irow(p) for p in comps) or '<div class="irow el"><span class="el">no component yet &mdash; add one in its place on the %s</span></div>' % esc(mode_name(ctx.get("steward")))))
    return "".join(rows)


def _campaign_tile(ctx):
    """The goals on the home (W2c, 2026-09-30, his lock of the three levels): ONE thin line — Tier 1 named, Tier 2 and
    the seed goals counted, how many initiatives are out — that expands to the goals and their components (each goal a
    row that opens). The tile is where a seated initiative is dropped to go home, and a goal's row is where a registry
    project is dropped to become its component. Closed by default; the head toggles it."""
    camp = ctx.get("campaign")
    inits = ctx.get("initiatives") or []
    if not camp:
        return ('<section class="camp" id="camp"><div class="camp-h" id="campHead"><span class="k">Goals</span>'
                '<span class="d">&middot; not stood up yet &mdash; the record arrives with the import, after your seed check</span>'
                '<span class="sp"></span></div></section>')
    live = [i for i in inits if i["status"] not in ("done", "parked")]
    t1 = [i for i in goals_only(live) if i["tier"] == 1]
    t2 = [i for i in live if i["tier"] == 2]
    seedy = [i for i in goals_only(live) if i["tier"] not in (1, 2)]
    act = seated(live, "active")
    deck = seated(live, "deck")
    line = ('&middot; <b>Tier 1:</b> %s &middot; <b>Tier 2:</b> %d &middot; <b>seed goals:</b> %d &middot; <b>out:</b> %d active, %d on deck' % (
        esc(" · ".join(i["name"] for i in t1)) if t1 else "none yet", len(t2), len(seedy) + int(ctx.get("seeds") or 0), len(act), len(deck)))      # one seed-goal count (Grok W2c): the goals not in tier 1 or 2, and the seeds
    body = '<div class="grows">%s</div>' % (_goal_rows(ctx, live, camp["pid"]) or '<div class="camp-note">No goal yet &mdash; the %s makes one.</div>' % esc(mode_name(ctx.get("steward"))))
    return (
        '<section class="camp" id="camp" data-drop="home"><div class="camp-h" id="campHead"><span class="k">Goals</span>'
        '<span class="d" id="campLine">%s</span><span class="sp"></span><span class="tog" id="campTog">Expand</span>'
        '<a class="camp-open" href="/project/%s" target="_blank" rel="noopener">Open the %s</a></div>'
        '<div class="camp-body" id="campBody">%s</div></section>'
    ) % (line, esc(camp["pid"]), esc(mode_name(ctx.get("steward"))), body)


def _desk_card(ctx, g, p):
    """A desk item's card (W2c): the item, its goal, its state and date; the × sends it home; it is talked through at the
    Desk — the Campaign's own cockpit in its Desk view (Grok's read of W2c: the door the Desk line already opens)."""
    if p.get("needs_you"):
        line = '<div class="t-line wait"><span class="mk">&#9873; Needs you:</span>%s</div>' % esc(p.get("waiting_on") or p.get("state") or "")
    else:
        line = '<div class="t-line"><span class="k">State</span>%s</div>' % esc(p.get("state") or p.get("status") or "planned")
    date = (' &middot; %s' % esc(_hr.due_label(p["date"], ctx["today"]))) if p.get("date") else ""
    dot = '<span class="tlight %s" title="%s"></span>' % (("orange", "needs you") if p.get("needs_you") else ("gray", "idle"))      # a desk card has a light too (Grok's read of W2e)
    return (
        '<article class="tile desk%s" id="card-%s" data-step="%s" data-name="%s" draggable="true"><div class="t-top">' + dot + '<h3 class="t-name"><span class="t-nm">%s</span><span class="t-eff">at the desk%s</span></h3>'
        '<button class="t-x" data-home="%s" title="back to its goal">&times;</button></div><div class="t-goal">in <b>%s</b></div>%s'
        '<div class="t-acts"><a class="t-talk" href="/project/%s?view=desk" target="_blank" rel="noopener">talk to the desk &#8599;</a></div></article>'
    ) % (" need" if p.get("needs_you") else "", esc(p["id"]), esc(p["id"]), esc(part_name(p)), esc(part_name(p)), date, esc(p["id"]), esc(g["name"]), line,
         esc((ctx.get("campaign") or {}).get("pid") or ""))


def _zone(sid, seat, title, n, note, cards, empty):
    return (
        '<section class="shelf zone" id="%s" data-seat="%s"><div class="shelf-h"><h3>%s</h3><span class="c">%d</span><span class="rule"></span><span class="note">%s</span></div>'
        '<div class="grid">%s</div></section>' % (sid, seat, title, n, note, cards or ('<div class="empty">%s</div>' % empty)))


def _seat_shelves(ctx):
    """ACTIVE and ON DECK (W2c): two shelves of initiative cards in his order — the project card as today (the light,
    what needs him, Status · Next steps · Deliverables · Plan · Resume · the cockpit), a cockpit within a project on
    its own effort, a desk item's card that talks to the desk — each naming its goal, each with a × that sends it home.
    No cap: a wide Active is named, never refused."""
    inits = [i for i in ctx.get("initiatives") or [] if i["status"] not in ("done", "parked")]
    entries = {e.get("id"): e for e in ctx.get("entries") or []}
    facts = ctx["facts"]

    def cards(seat):
        out = []
        for g, p in seated(inits, seat):
            if p["kind"] in ("project", "effort") and entries.get(p["pid"]):
                e = entries[p["pid"]]
                f = facts.get(p["pid"]) or {}
                if p["kind"] == "effort":      # the card reads THAT effort: its directory, its own wait and next (Grok's read of W2c)
                    st_ = str(p.get("state") or "")
                    wait = re.sub(r"^waiting on you[:\s]*", "", st_, flags=re.I).strip(" .") if st_.lower().startswith("waiting on you") else ""
                    f = dict(f, effort=p.get("dir") or f.get("effort") or "", needs_you=wait or ("" if st_ else f.get("needs_you") or ""), needs_you_effort="", other_waits=[],
                             wait_age_days=None, next=p.get("lead") or p.get("text") or f.get("next") or "", repair_proposals=[], efforts_gap="")
                lights = ctx.get("lights") or {}
                lt = lights.get(p["pid"] + "|" + str(p.get("dir") or "")) if p["kind"] == "effort" else lights.get(p["pid"])      # W2e-7: the card's OWN cockpit's light, an effort's keyed by its directory
                out.append(_card(e, f, "", goal=g, step=p, light=lt))
            else:
                out.append(_desk_card(ctx, g, p))
        return "".join(out)
    a, d = cards("active"), cards("deck")
    n_a, n_d = len(seated(inits, "active")), len(seated(inits, "deck"))
    return (
        _zone("shActive", "active", "Active", n_a, "what you are working on now, in your order &mdash; drag an initiative here from a goal above or from On deck", a,
              "nothing active &mdash; pull an initiative out of a goal above, or drag one up from On deck")
        + _zone("shDeck", "deck", "On deck", n_d, "out of its goal, not active &mdash; needs attention; the pick-up reads from here", d, "nothing on deck"))


def _projects_tile(ctx):
    """The Projects tile: the registry as it stands, in the OLD dashboard's own list (John, 2026-09-27: "the same look
    and feel, and all of the folders closed") — `ctx["projects_html"]` is that list, rendered by the old dashboard's
    renderer in `anchor_gui`; the head counts the projects and the folders."""
    groups = ctx.get("groups") or {}
    n = sum(len(v) for v in groups.values())
    quiet_n = int(ctx.get("quiet_n") or 0)
    # R11 (2026-09-28, John: "I do not want to go to the old Anchor Dashboard … just the button that links to the
    # folder creation GUI … with an option to place it in a folder"): ONE control on the tile's own line opens the
    # old dashboard's dialog ALONE in a small window; the folders here feed the composer's confirm card
    named = [g for g in groups.keys() if g and g != "Ungrouped"]
    group_opts = "".join('<option value="%s">%s</option>' % (esc(g), esc(g)) for g in named) + '<option value="" selected>Ungrouped</option>'
    return (
        '<section class="ptile" id="ptile"><div class="ptile-line"><button class="ptile-h" id="ptileToggle"><span class="k">Projects</span>'
        '<span class="n" id="ptileCount">&middot; %d project%s in %d folder%s%s</span><span class="sp"></span>'
        '<span class="tog" id="ptileTog">Show all</span></button>'
        '<button type="button" class="tog np" id="apNew" title="the folder-creation dialog, in a small window">&#65291; New project</button></div>%s'
        '<div class="ptile-body"><div class="addbox"><h4>Add a project</h4>'
        '<div class="addhint" id="apHint">Say it to the steward above (&ldquo;start a new project called &lt;name&gt; at &lt;folder&gt;&rdquo;) and confirm the card, '
        'or press New project: the dialog opens in a small window and puts it in a folder of your choosing.</div>'
        '<select id="apGroups" hidden>%s</select></div>'
        '<div id="folders">%s</div></div></section>'
    ) % (n, "" if n == 1 else "s", len(groups), "" if len(groups) == 1 else "s",
         (" &middot; <b>%d</b> with no steward record yet" % quiet_n) if quiet_n else "",
         _orphans_line(ctx), group_opts, ctx.get("projects_html") or '<p class="ptile-note">No project list was handed to the page.</p>')


def _orphans_line(ctx):
    """W2c (fit 10): a registry project in no goal is visible here only; dragging it onto a goal above makes it a
    component of that goal, and so an initiative he can seat."""
    orphans = ctx.get("orphans") or []
    if not ctx.get("campaign") or not orphans:
        return ""
    chips = "".join('<span class="orphan" draggable="true" data-proj="%s" data-name="%s" title="a registry project in no goal &mdash; drag it onto a goal above">%s</span>' % (
        esc(e.get("id")), esc(e.get("name")), esc(e.get("name"))) for e in orphans)
    return ('<div class="orphans"><span class="ok">In no goal &middot; %d</span>%s<span class="oh">drag one onto a goal above to make it a component of that goal</span></div>'
            % (len(orphans), chips))


_ACTS = (("status", "Status"), ("next", "Next steps"), ("deliverables", "Deliverables"), ("plan", "Plan"))   # the opened tile always carries its brief and its dialogue (W2e-2); the acts add a detail
LIGHT_WORDS = {"green": "working", "orange": "needs you", "red": "a problem", "gray": "idle"}


def _resume_act(pid, rel, r):
    """W5 (2026-09-28): Resume — where he left this record (W0's leave receipt), opened in the cockpit AT that step
    (`?step=` opens the plan's fold that holds it, scrolls to it and marks it once); the act's title says the step
    and when, and "nothing moved since" when the roadmap has not moved (the count itself stays on the fact — a
    number with no decision behind it is not for the card, Grok W5). No receipt, no act."""
    if not isinstance(r, dict) or not r.get("at"):
        return ""
    since = r.get("events_since")
    moved = " &middot; nothing moved since" if since == 0 else ""     # the count stays on the fact; the title says only the zero (Grok W5)
    href = "/project/%s?dir=%s%s" % (pid, esc(rel), ("&amp;step=%s" % esc(r.get("step_id"))) if r.get("step_id") else "")
    return ('<a class="t-resume" href="%s" target="_blank" rel="noopener" title="you left at %s (%s)%s">&#8617; Resume <span class="t-age">%s</span></a>'
            % (href, esc(r.get("step") or "where you were"), esc(r.get("ago") or r.get("at")), moved, esc(r.get("ago") or "")))


def _card(e, f, cls, goal=None, step=None, light=None):
    """A project's one card, compact (John, 2026-09-27: "the tiles still seem larger than needed"): the name with the
    effort it reads as a small suffix, ONE line — the Needs-you sentence when there is one, else the next step —
    clamped to two lines, and the acts on one line, Status first (his word: "there should also be a status option");
    the cockpit link sits by the name. The description and the next step behind a wait show only once the card
    opens (the effort is named by the suffix and again by the Status part — no third line, Grok R7). The name
    ellipsizes; the suffix stays whole (Grok R7: the effort is the datum the suffix exists for). The parts are read
    from the cockpit's own readers on the effort the card names (home_rows.current_effort → ``data-dir``). A project
    with no record is a quiet card: the name, its blurb, the cockpit."""
    pid = esc(e.get("id"))
    rel = esc(f.get("effort") or "")
    name = esc(e.get("name") or (step or {}).get("name"))
    # W2c (2026-09-30): on a shelf the card is a seated initiative — it carries its step, drags, has its × and names
    # its goal; a cockpit within a project is its own card on its own effort
    cid = pid if not (step and step.get("kind") == "effort") else "%s-%s" % (pid, esc(step["id"]))
    attr = (' data-step="%s" data-name="%s" draggable="true"' % (esc(step["id"]), name)) if step else ""
    # W4 of the two-lane plan (2026-10-05, his rule): the light is orange exactly when something waits on him (the
    # engine's one rule), and the edge pulses exactly when the light is orange. Looking does not resolve the request.
    lt = light if isinstance(light, dict) else {}
    lclass = lt.get("light") if lt.get("light") in LIGHT_WORDS else "gray"
    dot = '<span class="tlight %s" title="%s"></span>' % (lclass, esc((LIGHT_WORDS[lclass] + ((": " + lt["why"]) if lt.get("why") else ""))[:200]))
    if lclass == "orange":   # W4 (2026-10-05, his rule): the edge pulses exactly when the light is orange
        import hashlib as _hl
        attr += ' data-ready="%s"' % _hl.sha1((str(lt.get("why") or "") + "|" + str(f.get("needs_you") or "")).encode("utf-8")).hexdigest()[:10]
    xbtn = ('<button class="t-x" data-home="%s" title="back to its goal">&times;</button>' % esc(step["id"])) if step else ""
    goal_line = ('<div class="t-goal">in <b>%s</b> &middot; %s</div>' % (esc(goal["name"]), "a cockpit within the project" if step.get("kind") == "effort" else "the project&rsquo;s cockpit")) if (goal and step) else ""
    if not f.get("has_record"):
        return (
            '<article class="tile quiet%s" id="card-%s" data-tile="%s"%s><div class="t-top">%s<h3 class="t-name">%s</h3>%s</div>%s'
            '<div class="t-desc">%s</div><div class="t-quiet">no steward record yet &middot; <a class="t-open" href="/project/%s" target="_blank" rel="noopener">Open cockpit</a></div></article>'
        ) % (cls, cid, pid, attr, dot, name, xbtn, goal_line, esc((e.get("blurb") or "").strip()[:160]) or "&mdash;", pid)
    wait = " ".join(str(f.get("needs_you") or "").split())[:160]
    nxt = esc((f.get("next") or "")[:160]) or "not stated"
    # W1 (2026-09-28): EVERY effort's wait, each opening its own record (the Status part on that effort) — a
    # project's second effort no longer disappears behind the one touched last. A wait promoted from another
    # effort (the shown one has none) is that effort's line, with its open; the rest follow it.
    promoted = str(f.get("needs_you_effort") or "")
    other_waits = [x for x in (f.get("other_waits") or []) if isinstance(x, dict)]

    def _eff_line(x):
        a = x.get("age_days")
        a_s = (' <span class="t-age">&middot; %d day%s</span>' % (int(a), "" if int(a) == 1 else "s")) if isinstance(a, (int, float)) and a >= 1 else ""
        return ('<div class="t-line wait"><span class="mk">&#9873; %s:</span>%s%s '
                '<button class="t-eff-open" data-part="status" data-pid="%s" data-dir="%s">open</button></div>') % (
            esc(x.get("name")), esc(" ".join(str(x.get("needs_you") or "").split())[:160]), a_s, pid, esc(x.get("rel")))
    lead_x = next((x for x in other_waits if str(x.get("rel") or "") == promoted), None) if (wait and promoted) else None
    if lead_x is not None:
        line = _eff_line(lead_x)
        # the Next line is the SHOWN effort's, named, so a promoted wait never reads as that effort's next (Grok W1)
        more_next = '<div class="t-next"><span class="k">Next &middot; %s</span>%s</div>' % (rel or "root", nxt)
    elif wait:
        # W2 (2026-09-28): the age of the wait, from the record (home_rows._wait_age_days) — nothing when unknown
        age = f.get("wait_age_days")
        age_s = (' <span class="t-age">&middot; %d day%s</span>' % (int(age), "" if int(age) == 1 else "s")) if isinstance(age, (int, float)) and age >= 1 else ""
        line = '<div class="t-line wait"><span class="mk">&#9873; Needs you:</span>%s%s</div>' % (esc(wait), age_s)
        more_next = '<div class="t-next"><span class="k">Next</span>%s</div>' % nxt
    else:
        line = '<div class="t-line"><span class="k">Next</span>%s</div>' % nxt
        more_next = ""
    for x in other_waits:
        if x is lead_x:
            continue
        line += _eff_line(x).replace('class="t-line wait"', 'class="t-line wait other"', 1)
    if f.get("efforts_gap"):
        line += '<div class="t-line dim">&#9888; %s</div>' % esc(f["efforts_gap"])   # never a silent empty list (Grok W1)
    # W4 (2026-09-28): a repair PROPOSED after an acceptance waits on his word — "proposed: N corrections"; the Status
    # part shows the set with accept and dismiss; nothing inside approved work changes before (his Q2)
    props = [p for p in (f.get("repair_proposals") or []) if isinstance(p, dict)]
    if props:
        n = sum(int(p.get("count") or 0) for p in props)
        line += ('<div class="t-line prop"><span class="mk">&#9881; proposed:</span>%d correction%s '
                 '<button class="t-eff-open" data-part="status" data-pid="%s" data-dir="%s">see</button></div>') % (n, "" if n == 1 else "s", pid, rel)
    acts = "".join('<button data-part="%s" data-pid="%s" data-dir="%s">%s</button>' % (part, pid, rel, label) for part, label in _ACTS)
    acts += _resume_act(pid, rel, f.get("resume"))
    # Wave 6b: 1-click Mark Done button on active/seated cards (uses data-mark-done, never data-part or data-dir so card act counts stay exact)
    t_folder = str(f.get("folder") or "")
    if t_folder and f.get("effort"):
        t_folder = str(Path(t_folder) / str(f.get("effort")))
    done_btn = (
        '<button type="button" class="t-done-btn" data-mark-done="1" data-step="%s" data-target-dir="%s" title="Mark current step done in this record">&#10003; Done</button>'
        % (esc((step or {}).get("id") or ""), esc(t_folder))
    )
    # "/project/%s?dir=%s&amp;open=effort"
    cockpit_href = "/steward/v1?pid=%s&amp;dir=%s" % (pid, esc(_quote(str(f.get("effort") or ""))))
    proj_href = "/project/%s%s" % (pid, ("?dir=%s" % rel) if rel else "")
    st_tot = int(f.get("steps_total") or 0)
    st_done = int(f.get("steps_done") or 0)
    prog_html = ""
    if st_tot > 0:
        pct = max(0, min(100, int(round(100.0 * st_done / st_tot))))
        prog_html = ('<div class="t-prog" title="%d of %d plan steps done">'
                     '<span class="t-prog-bar"><i style="width:%d%%"></i></span>'
                     '<span class="t-prog-txt">%d/%d steps</span></div>') % (st_done, st_tot, pct, st_done, st_tot)
    return (
        '<article class="tile%s" id="card-%s" data-tile="%s" data-dir="%s"%s><div class="t-top">%s<h3 class="t-name"><span class="t-nm">%s</span>%s</h3>'
        '%s<a class="t-go" href="%s" data-project-href="%s" target="_blank" rel="noopener" title="Open the cockpit">cockpit &#8599;</a>%s</div><div class="t-face">%s'
        '%s<div class="t-more"><div class="t-desc">%s</div>%s</div>%s</div>'
        '<div class="t-acts">%s</div>'
        '<div class="t-body" hidden></div></article>'
    ) % (cls, cid, pid, rel, attr, dot, name, ('<span class="t-eff">&middot; %s</span>' % rel) if rel else "", done_btn, cockpit_href, proj_href, xbtn, goal_line,
         line, esc((e.get("blurb") or "").strip()[:220]) or "&mdash;", more_next, prog_html, acts)



def _desk_line(ctx):
    """The Desk on the Cave (his word, 2026-10-06): ONE line - the Goals tile's own pattern - that expands in the page
    to a row per cockpit (Small items first) and opens the Desk page with a click. Small items share one small-item
    cockpit; only substantial efforts have their own, and those can be seated On deck / Active like any cockpit."""
    desk = ctx.get("desk")
    pid = ctx.get("desk_pid") or ""
    # the old task list stays reachable from here (moved with the Desk, never dropped)
    tasks = '<button class="dchip" id="chipTasks" data-desk="tasks">Tasks &middot; <span id="taskTotal">%d</span></button>' % int(ctx.get("tasks_open") or 0)
    if not desk or not pid:
        return ('<section class="camp desk" id="deskline"><div class="camp-h" id="deskHead"><span class="k">Desk</span>'
                '<span class="d">&middot; admin, no project &mdash; not set up yet; opening it sets it up</span><span class="sp"></span>' + tasks +
                '<a class="camp-open" href="/desk" target="_blank" rel="noopener">Open the Desk</a></div></section>')
    waits, n_small, n_cock = desk_counts(desk)
    lights = [((desk.get("small") or {}).get("light") or "gray")] + [c.get("light") or "gray" for c in desk.get("cockpits") or ()]
    head_light = next((l for l in ("red", "orange", "green") if l in lights), "gray")
    line = "&middot; %s &middot; Small items %d &middot; %d cockpit%s" % (
        ("<b>%d wait%s on you</b>" % (waits, "" if waits == 1 else "s")) if waits else "nothing waits on you",
        n_small, n_cock, "" if n_cock == 1 else "s")

    def row(name, d, lt, why, seat=""):
        lclass = lt if lt in LIGHT_WORDS else "gray"
        return ('<a class="drow%s" href="/steward/v1?pid=%s&amp;dir=%s" target="_blank" rel="noopener">'
                '<span class="tlight %s" title="%s"></span><span class="drow-n">%s</span><span class="drow-w">%s</span>%s</a>') % (
            " waits" if lclass == "orange" else "", esc(pid), esc(_quote(d)), lclass, esc(LIGHT_WORDS[lclass]), esc(name),
            esc(why or LIGHT_WORDS[lclass]), ('<span class="drow-s">%s</span>' % esc(SEAT_NAMES.get(seat, ""))) if seat else "")
    sm = desk.get("small") or {}
    rows = [row("Small items · %d" % n_small, "Small items", sm.get("light"), sm.get("why"))]
    rows += [row(c["name"], c["dir"], c.get("light"), c.get("why"), c.get("seat") or "") for c in desk.get("cockpits") or ()]
    adhoc_btn = (
        '<button type="button" class="dchip desk-cockpit-btn" data-open-href="/steward/v1?pid=%s&amp;dir=Small%%20items" '
        'title="Open the Desktop Ad-Hoc AI Cockpit for quick admin tasks">&#128421; Ad-Hoc AI Cockpit &#8599;</button>' % esc(pid)
    )
    return (
        '<section class="camp desk%s" id="deskline"><div class="camp-h" id="deskHead"><span class="tlight %s"></span><span class="k">Desk (Desktop)</span>'
        '<span class="d">%s</span><span class="sp"></span>%s%s<span class="tog" id="deskTog">Expand</span>'
        '<a class="camp-open" href="/desk" target="_blank" rel="noopener">Open the Desk</a></div>'
        '<div class="camp-body"><div class="drows">%s</div></div></section>'
    ) % (" ready" if head_light == "orange" else "", head_light, line, adhoc_btn, tasks, "".join(rows))


def _this_week_horizon_html(ctx, weeks, buckets, overdue):
    """Wave 6b/12/15: Two-Horizon Schedule top view — Today & This Week 4-column tactical focus board with
    HTML5 Drag-and-Drop card rescheduling, 1-click Mark Done, Push +3d controls, and recently closed steps."""
    hb = this_week_horizon_buckets(ctx)
    col_overdue = hb["col_overdue"]
    col_today = hb["col_today"]
    col_72h = hb["col_72h"]
    col_week = hb["col_week"]
    closed_today = hb["closed_today"]
    tdates = hb["target_dates"]

    def _tw_item(x, badge_cls=""):
        plus3 = (x["date_obj"] + timedelta(days=3)).isoformat()
        acts = ""
        drag_attrs = ""
        if x.get("folder") and x.get("step_id"):
            acts = (
                '<span class="tw-acts">'
                '<button type="button" class="tw-btn done" data-mark-done="1" data-target-dir="%s" data-target-step="%s" title="Mark step done">&#10003; Done</button>'
                '<button type="button" class="tw-btn push" data-schedule-date="%s" data-target-dir="%s" data-target-step="%s" title="Push due date +3 days">+3d</button>'
                '</span>'
            ) % (esc(x["folder"]), esc(x["step_id"]), esc(plus3), esc(x["folder"]), esc(x["step_id"]))
            drag_attrs = (
                ' draggable="true" data-tw-card="1" data-target-dir="%s" data-target-step="%s" title="Drag across columns to reschedule due date"'
                % (esc(x["folder"]), esc(x["step_id"]))
            )
        return (
            '<div class="tw-card%s"%s><div class="tw-top"><span class="tw-date">%s</span>'
            '<a class="tw-proj" href="/project/%s" target="_blank" rel="noopener">%s</a>%s</div>'
            '<div class="tw-name">%s</div></div>'
        ) % (
            (" " + badge_cls) if badge_cls else "",
            drag_attrs,
            esc(_short(x["due"])),
            esc(x["project_id"]),
            esc(x["project_name"]),
            acts,
            esc(x["name"]),
        )

    done_html = "".join(
        '<div class="tw-card done"><div class="tw-top"><span class="tw-date">&#10003; Done today</span>'
        '<a class="tw-proj" href="/project/%s" target="_blank" rel="noopener">%s</a></div>'
        '<div class="tw-name">%s</div></div>' % (esc(c["project_id"]), esc(c["project_name"]), esc(c["name"]))
        for c in closed_today[:4]
    )

    c1 = "".join(_tw_item(x, "late") for x in col_overdue[:5]) or '<div class="tw-empty">&#10003; Zero overdue items</div>'
    c2 = ("".join(_tw_item(x, "now") for x in col_today[:5]) + done_html) or '<div class="tw-empty">No remaining deadlines today</div>'
    c3 = "".join(_tw_item(x, "soon") for x in col_72h[:5]) or '<div class="tw-empty">Clear for next 72 hours</div>'
    c4 = "".join(_tw_item(x, "") for x in col_week[:5]) or '<div class="tw-empty">Nothing else due within 7 days</div>'

    return (
        '<div class="tw-board" id="thisWeekBoard" data-tw-dnd="1">'
        '<div class="tw-col" data-tw-drop-col="overdue" data-tw-target-date="%s"><div class="tw-col-h"><span class="tw-k">Overdue</span><span class="tw-c">%d</span></div>%s</div>'
        '<div class="tw-col now" data-tw-drop-col="today" data-tw-target-date="%s"><div class="tw-col-h"><span class="tw-k">Today &amp; Done Today</span><span class="tw-c">%d</span></div>%s</div>'
        '<div class="tw-col" data-tw-drop-col="72h" data-tw-target-date="%s"><div class="tw-col-h"><span class="tw-k">Next 72 Hours</span><span class="tw-c">%d</span></div>%s</div>'
        '<div class="tw-col" data-tw-drop-col="week" data-tw-target-date="%s"><div class="tw-col-h"><span class="tw-k">Days 4&ndash;7</span><span class="tw-c">%d</span></div>%s</div>'
        '</div>'
    ) % (
        esc(tdates["overdue"]), len(col_overdue), c1,
        esc(tdates["today"]), len(col_today) + len(closed_today), c2,
        esc(tdates["72h"]), len(col_72h), c3,
        esc(tdates["week"]), len(col_week), c4,
    )


def _ruler(ctx):
    weeks, buckets, beyond, overdue = ruler_markers(list(ctx["facts"].values()), ctx["today"])
    head = "".join('<div%s><b>%s</b><span class="sm">%s</span></div>' % (' class="now"' if k == 0 else "", esc(w["label"]), esc(w["name"])) for k, w in enumerate(weeks))
    head += '<div class="beyond"><b>%s&ndash;</b><span class="sm">beyond the ruler</span></div>' % esc(_hr.short_date((weeks[-1]["end"] + timedelta(days=1)).isoformat()))
    on_board = ctx.get("on_board") or set()

    def marker(m):
        where = ("&#9873; " if m["needs"] else "") + (("seated on %s" % on_board[m["project_id"]]) if m["project_id"] in on_board else "in the Projects tile")      # W2c: the shelves are the seats
        return ('<a class="mkcard%s" href="/project/%s" target="_blank" rel="noopener"><span class="mk-date">%s</span><span class="mk-what">%s%s</span>'
                '<span class="mk-proj">%s</span><span class="mk-where">%s</span></a>' % (
                    " late" if m["overdue"] else "", esc(m["project_id"]), esc(_short(m["date"])), esc(m["name"]),
                    " &middot; overdue" if m["overdue"] else (" &middot; &#9873; needs you" if m["needs"] else ""), esc(m["project_name"]), where))
    cols = []
    for k in range(5):
        inner = "".join(marker(m) for m in buckets[k])
        if k == 0 and not inner:
            nearest = next((m for kk in range(1, 5) for m in buckets[kk]), None) or (beyond[0] if beyond else None)
            inner = '<p class="empty-week"><b>This week, %s</b>No registered delivery this week. %s</p>' % (
                esc(weeks[0]["label"]), ("Nearest: %s, %s." % (esc(nearest["name"]), esc(_short(nearest["date"])))) if nearest else "Nothing carries a date yet.")
        cols.append('<div%s id="week%d">%s</div>' % (' class="now"' if k == 0 else "", k + 1, inner))
    cols.append('<div class="beyond" id="weekBeyond">%s</div>' % "".join(marker(m) for m in beyond[:8]))
    total = sum(len(v) for v in buckets.values()) + len(beyond) + len(overdue)
    late = ('<div class="shelf-foot late">Overdue, before this week: %s.</div>' % "; ".join(
        '<a href="/project/%s" target="_blank" rel="noopener">%s</a> (%s, %s)' % (esc(m["project_id"]), esc(m["name"]), esc(_short(m["date"])), esc(m["project_name"]))
        for m in overdue[:6])) if overdue else ""
    tw_html = _this_week_horizon_html(ctx, weeks, buckets, overdue)
    comms_html = _comms_pulse_html(ctx)
    return (
        '<section class="shelf" id="shDated">'
        '<div class="dated-schedule-wrap" id="datedScheduleWrap" hidden>'
        '<div class="shelf-h"><h3>Dated deliveries &amp; Schedule</h3><span class="c">%d dated step%s</span><span class="rule"></span>'
        '<div class="hz-tabs" role="tablist" aria-label="Schedule horizon">'
        '<button type="button" class="hz-tab on" data-hz="both">Today + 6-Week Compact</button>'
        '<button type="button" class="hz-tab" data-hz="week">Today &amp; This Week Only</button>'
        '<button type="button" class="hz-tab" data-hz="ruler">6-Week Horizon Only</button></div>'
        '<span class="note">Each marker is a dated open step in a project&rsquo;s record. Click one to balloon it open.</span></div>'
        '%s'
        '<div class="ruler compact-ruler" id="ruler"><div class="rl-head">%s</div><div class="rl-marks" id="rlMarks">%s</div></div>'
        '%s<div class="shelf-foot">Each marker points at the one card that owns it &mdash; no project has a second card.</div>'
        '</div>'
        '%s'
        '</section>'
    ) % (total, "" if total == 1 else "s", tw_html, head, "".join(cols), late, comms_html)


def _comms_pulse_html(ctx):
    """Wave 9 & Wave 15: Calendar & Email Pulse on the Cave of Wonders — reconciles configured IMAP/ICS accounts
    and live project roadmaps with background auto-poller status, two-way reply draft generation, 1-click Mark Step Done,
    and direct link to Gear (⚙) Setup Stage 4 (`/setup?section=comms`)."""
    import comms_connector as _cc
    try:
        comms = ctx.get("comms") or _cc.reconcile_comms_with_roadmaps(
            entries=ctx.get("entries") or [],
            facts=ctx.get("facts") or {},
            today=ctx.get("today") or date.today(),
        )
        p_stat = _cc.poller_status()
    except Exception:
        comms = {"accounts_count": 0, "connected_count": 0, "calendar_events": [], "email_threads": [], "last_sync_at": ""}
        p_stat = {"running": False, "interval_sec": 900}

    conn_n = int(comms.get("connected_count") or 0)
    acc_n = int(comms.get("accounts_count") or 0)
    cal_evs = comms.get("calendar_events") or []
    threads = comms.get("email_threads") or []
    last_sync = str(comms.get("last_sync_at") or "").strip()
    poller_min = max(1, int(round(int(p_stat.get("interval_sec") or 900) / 60.0)))

    state_txt = (
        "&middot; %d account%s connected (OS Vault) &middot; %d calendar &middot; %d correspondence track%s"
        % (conn_n, "" if conn_n == 1 else "s", len(cal_evs), len(threads), "" if len(threads) == 1 else "s")
        if acc_n > 0
        else "&middot; roadmap reconciliation active &middot; %d calendar &middot; %d correspondence track%s"
        % (len(cal_evs), len(threads), "" if len(threads) == 1 else "s")
    )
    if last_sync:
        state_txt += " &middot; synced %s" % esc(last_sync)

    cal_rows = []
    for ev in cal_evs[:6]:
        acts = ""
        if ev.get("folder") and ev.get("step_id"):
            acts = (
                '<button type="button" class="tw-btn done" data-mark-done="1" data-target-dir="%s" data-target-step="%s" title="Mark this calendar/roadmap step done">&#10003; Done</button>'
                % (esc(ev["folder"]), esc(ev["step_id"]))
            )
        proj_link = (
            '<a class="tw-proj" href="/project/%s" target="_blank" rel="noopener">%s</a>'
            % (esc(ev["project_id"]), esc(ev.get("project_name") or "Project"))
            if ev.get("project_id")
            else '<span class="tw-proj">%s</span>' % esc(ev.get("project_name") or "Calendar")
        )
        cal_rows.append(
            '<div class="comms-item %s"><div class="comms-item-top">'
            '<span class="comms-badge %s">%s &middot; %s</span>%s%s</div>'
            '<div class="comms-item-title">%s</div></div>'
            % (
                esc(ev.get("tone") or "sky"),
                esc(ev.get("tone") or "sky"),
                esc(_short(ev.get("date")) or ev.get("date") or ""),
                esc(ev.get("time_label") or ""),
                proj_link,
                acts,
                esc(ev.get("title") or ""),
            )
        )
    cal_col_html = "".join(cal_rows) or '<div class="tw-empty">No upcoming calendar or dated delivery items in the next 14 days.</div>'

    mail_rows = []
    for th in threads[:6]:
        acts = []
        acts.append(
            '<button type="button" class="tw-btn" data-comms-draft-reply="1" data-comms-draft-subject="%s" data-comms-draft-to="%s" data-comms-draft-project="%s" data-comms-draft-step="%s" title="Generate a reply draft (.eml + mailto:) for this correspondence track">&#9998; Draft Reply</button>'
            % (
                esc(th.get("subject") or ""),
                esc(th.get("counterparty") or ""),
                esc(th.get("project_name") or ""),
                esc(th.get("step_id") or ""),
            )
        )
        if th.get("can_mark_done") and th.get("folder") and th.get("step_id"):
            acts.append(
                '<button type="button" class="tw-btn done" data-mark-done="1" data-target-dir="%s" data-target-step="%s" title="Mark reconciled roadmap step done">&#10003; Mark Step Done</button>'
                % (esc(th["folder"]), esc(th["step_id"]))
            )
        if th.get("project_id"):
            acts.append(
                '<a class="tw-btn" href="/steward/v1?pid=%s&amp;dir=" target="_blank" rel="noopener">Cockpit &#8599;</a>'
                % esc(th["project_id"])
            )
        mail_rows.append(
            '<div class="comms-item %s"><div class="comms-item-top">'
            '<span class="comms-badge %s">%s</span>'
            '<span class="comms-meta">%s &middot; %s</span>'
            '<span class="comms-acts">%s</span></div>'
            '<div class="comms-item-title">%s</div>'
            '<div class="comms-item-sub">%s</div></div>'
            % (
                esc(th.get("tone") or "sky"),
                esc(th.get("tone") or "sky"),
                esc(th.get("badge") or "Correspondence"),
                esc(th.get("project_name") or th.get("counterparty") or ""),
                esc(th.get("date_label") or ""),
                "".join(acts),
                esc(th.get("subject") or ""),
                esc(th.get("summary") or ""),
            )
        )
    mail_col_html = "".join(mail_rows) or '<div class="tw-empty">No active external counsel or email tracks waiting on reconciliation.</div>'

    conn_note = (
        '<p class="conn-zero">Connected to %d account%s via Windows OS Credential Vault (<code>advapi32</code>) &mdash; background poller + two-way draft composer active.</p>'
        % (acc_n, "" if acc_n == 1 else "s")
        if acc_n > 0
        else '<p class="conn-zero">No external IMAP/ICS account is connected yet, so nothing here is sample data &mdash; items above are reconciled directly from your project roadmaps. '
             'Use <b>&#9881; Calendar &amp; Email Setup</b> to connect Google/Gmail, Microsoft 365/Outlook (OAuth2 PKCE or App Password), or Custom IMAP/ICS (stored in the Windows OS Vault).</p>'
    )

    return (
        '<section class="cal" id="cal" data-comms-pulse="1">'
        '<button class="cal-h" id="calHead"><span class="k">&#128236; Calendar &amp; Email Pulse</span>'
        '<span class="state" id="commsStateBadge">%s</span>'
        '<span class="cal-tab on" id="tabCal" data-cal-tab="cal">&#128197; Calendar &amp; Deadlines (%d)</span>'
        '<span class="cal-tab" id="tabMail" data-cal-tab="mail">&#9993; Email &amp; Counsel (%d)</span>'
        '<span class="sp"></span><span class="tog" id="calTog">Expand</span></button>'
        '<div class="cal-body" id="calBody">'
        '<div class="comms-toolbar" id="caveCommsPulse">'
        '<div class="comms-pills">'
        '<span class="comms-pill emerald">&#9679; OS Vault (advapi32)</span>'
        '<span class="comms-pill sky" id="commsPollerPill">&#8635; Auto-Poller (%dm)</span>'
        '<span class="comms-pill sky">&#9998; Two-Way Drafts (.eml)</span>'
        '</div>'
        '<div class="cal-quick-row">'
        '<button type="button" class="mini comms-sync-btn" id="btnCaveCommsSync" data-comms-sync="1">&#8635; Sync Now</button>'
        '<button type="button" class="mini" id="btnCaveCommsDraftNew" data-comms-draft-reply="1" data-comms-draft-subject="Update on next steps" data-comms-draft-to="" data-comms-draft-project="" data-comms-draft-step="">&#9998; Compose Draft</button>'
        '<a class="mini comms-setup-btn" id="btnCaveCommsSetup" href="/setup?section=comms" data-open-href="/setup?section=comms">&#9881; Calendar &amp; Email Setup</a>'
        '<button type="button" class="mini cal-prefill" data-say-prefill="I just emailed / completed: ">&#9993; Log an Email or External Action with the Steward</button>'
        '<button type="button" class="mini cal-prefill" data-say-prefill="Schedule update for this week: ">&#128197; Update Schedule / Priorities with the Steward</button>'
        '</div></div>'
        '<div class="comms-draft-modal" id="caveCommsDraftModal" hidden style="margin:8px 0;padding:12px;border:1px solid #2b3546;border-radius:8px;background:#121822">'
        '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">'
        '<b>&#9998; Two-Way Reply Draft Composer (Saves .eml to .anchor/drafts/ + Optional IMAP Drafts)</b>'
        '<button type="button" class="mini" id="btnCommsDraftClose">&times; Close</button></div>'
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px">'
        '<input type="text" id="commsDraftTo" placeholder="To (email or counterparty)" style="padding:6px 8px;border-radius:6px;border:1px solid #2b3546;background:#0d1117;color:#e6edf3">'
        '<input type="text" id="commsDraftSubject" placeholder="Subject" style="padding:6px 8px;border-radius:6px;border:1px solid #2b3546;background:#0d1117;color:#e6edf3">'
        '</div>'
        '<textarea id="commsDraftBody" rows="4" placeholder="Draft message body..." style="width:100%%;box-sizing:border-box;padding:8px;border-radius:6px;border:1px solid #2b3546;background:#0d1117;color:#e6edf3;margin-bottom:8px"></textarea>'
        '<div style="display:flex;align-items:center;gap:8px">'
        '<button type="button" class="mini comms-sync-btn" id="btnCommsDraftSave">&#128190; Save Draft (.eml)</button>'
        '<a class="mini" id="btnCommsDraftMailto" href="#" target="_blank" rel="noopener" hidden>&#9993; Open in Mail App (mailto:)</a>'
        '<span id="commsDraftStatus" style="font-size:12px;color:#8b949e"></span>'
        '</div></div>'
        '<div class="comms-grid" id="commsGrid">'
        '<div class="comms-col" id="commsCalCol"><div class="comms-col-h">&#128197; Upcoming Calendar &amp; Roadmap Window</div>%s</div>'
        '<div class="comms-col" id="commsMailCol"><div class="comms-col-h">&#9993; External Correspondence &amp; Counsel Reconciliation</div>%s</div>'
        '</div>'
        '%s'
        '</div></section>'
    ) % (state_txt, len(cal_evs), len(threads), poller_min, cal_col_html, mail_col_html, conn_note)


def _mothership_collab_html(ctx):
    """Wave 11 & Wave 15: Multi-Mothership Collaboration & Shared Cockpits strip on the Cave of Wonders
    with custom peer registration modal, .anchor-cockpit.json packet import/export, and 1-click step lease claim/release."""
    entries = ctx.get("entries") or []
    try:
        import mothership_collab as _mc
        summary = _mc.collab_summary_for_cave(entries=entries, facts=ctx.get("facts"))
    except Exception:
        summary = {"mothership": {"id": "anchor-mothership", "label": "Mother Ship"}, "peers": [], "active_leases": [], "shared_cockpits": []}

    ms = summary.get("mothership") or {}
    peers = summary.get("peers") or []
    leases = summary.get("active_leases") or []
    shared = summary.get("shared_cockpits") or []

    peer_rows = []
    for p in peers[:4]:
        sync_note = str(p.get("sync_note") or p.get("reachability") or "").strip()
        peer_rows.append(
            '<div class="tw-card" data-peer-id="%s">'
            '<div class="tw-top"><span class="tw-due ok">&#9679; %s</span>'
            '<span class="tw-proj">%s%s</span>'
            '<span class="tw-acts"><button type="button" class="tw-act" data-collab-sync-peer="%s">&#8644; Sync Peer</button></span></div>'
            '<div class="tw-name">%s &middot; <code>%s</code></div>'
            '</div>'
            % (esc(p.get("id") or ""), esc(p.get("role") or "collaborator"), esc(p.get("transport") or "git_remote"),
               (" &middot; " + esc(sync_note[:38])) if sync_note else "",
               esc(p.get("id") or ""), esc(p.get("label") or p.get("id") or "Peer Mothership"), esc(p.get("endpoint") or ""))
        )
    if not peer_rows:
        peer_rows.append(
            '<div class="tw-empty">No external collaborator Mothership linked yet &mdash; use <b>+ Link Collaborator Mothership</b> '
            'or <b>&#128230; Export Portable Cockpit Packet</b> to share a project cockpit with zero personal/host path leakage.</div>'
        )

    cockpit_rows = []
    for sc in shared[:4]:
        first_entry = next((e for e in entries if str(e.get("id") or "") == str(sc.get("pid") or "")), None)
        cdir_str = str(sc.get("cdir") or (first_entry or {}).get("folder_path") or "")
        first_step = str(sc.get("first_open_step_id") or "")
        claim_btn = (
            '<button type="button" class="tw-act" data-collab-claim-cdir="%s" data-collab-claim-step="%s" title="Claim a conflict-free lease on the next open step">&#128274; Claim Step</button>'
            % (esc(cdir_str), esc(first_step))
        ) if (cdir_str and first_step) else ""
        cockpit_rows.append(
            '<div class="tw-card" data-shared-pid="%s">'
            '<div class="tw-top"><span class="tw-due soon">&#129309; %d/%d steps</span>'
            '<span class="tw-proj">%d active lease%s</span>'
            '<span class="tw-acts">'
            '%s'
            '<button type="button" class="tw-act done" data-collab-export="%s" data-collab-name="%s">&#128230; Export Packet</button>'
            '<a class="tw-act" href="/steward/v1?pid=%s&amp;dir=" target="_blank" rel="noopener">Cockpit &#8599;</a>'
            '</span></div>'
            '<div class="tw-name">%s</div>'
            '</div>'
            % (esc(sc.get("pid") or ""), int(sc.get("steps_done") or 0), int(sc.get("steps_total") or 0),
               int(sc.get("leases_count") or 0), "" if int(sc.get("leases_count") or 0) == 1 else "s",
               claim_btn, esc(cdir_str), esc(sc.get("name") or "Project"), esc(sc.get("pid") or ""), esc(sc.get("name") or "Project"))
        )
    for ls in leases[:3]:
        cockpit_rows.append(
            '<div class="tw-card" data-lease-step="%s">'
            '<div class="tw-top"><span class="tw-due ok">&#128274; Leased by %s</span>'
            '<span class="tw-proj">%s</span>'
            '<span class="tw-acts">'
            '<button type="button" class="tw-act" data-collab-release-cdir="%s" data-collab-release-step="%s">&#128275; Release</button>'
            '</span></div>'
            '<div class="tw-name">%s &middot; <code>%s</code></div>'
            '</div>'
            % (
                esc(ls.get("step_id") or ""),
                esc(ls.get("holder_label") or ls.get("holder_mothership") or "Mother Ship"),
                esc(ls.get("project_name") or ""),
                esc(ls.get("cdir") or ""),
                esc(ls.get("step_id") or ""),
                esc(ls.get("step_name") or ls.get("step_id") or ""),
                esc(ls.get("step_id") or ""),
            )
        )
    if not cockpit_rows:
        cockpit_rows.append('<div class="tw-empty">No shared project roadmaps detected yet.</div>')

    return (
        '<section class="cal" id="caveCollabStrip" data-mothership-collab="1">'
        '<div class="cal-h" id="collabHead"><span class="k">&#129309; Multi-Mothership Collaboration &amp; Shared Cockpits</span>'
        '<span class="state" id="collabStateBadge">%s &middot; %d peer%s &middot; %d step lease%s</span>'
        '<span class="sp"></span><span class="tog" id="collabTog">Expand</span></div>'
        '<div class="cal-body">'
        '<div class="comms-toolbar">'
        '<div class="comms-pills">'
        '<span class="comms-pill emerald">&#9679; %s (%s)</span>'
        '<span class="comms-pill sky">&#128230; Portable Relative Paths (distro.scan_paths Clean)</span>'
        '</div>'
        '<div class="cal-quick-row">'
        '<button type="button" class="mini comms-sync-btn" id="btnCollabSyncNow" data-collab-sync="1">&#8644; Sync Shared Cockpits</button>'
        '<button type="button" class="mini comms-setup-btn" id="btnCollabAddPeer" data-collab-add-peer="1">+ Link Collaborator Mothership</button>'
        '<button type="button" class="mini" id="btnCollabOpenImport" data-collab-open-import="1">&#128229; Import Cockpit Packet</button>'
        '</div></div>'
        '<div class="collab-modal" id="caveCollabModal" hidden style="margin:8px 0;padding:12px;border:1px solid #2b3546;border-radius:8px;background:#121822">'
        '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">'
        '<b>&#129309; Register Collaborator Mothership / Import Portable Cockpit Packet</b>'
        '<button type="button" class="mini" id="btnCollabModalClose">&times; Close</button></div>'
        '<div style="display:grid;grid-template-columns:1fr 1fr 1fr 2fr auto;gap:6px;margin-bottom:10px">'
        '<input type="text" id="collabPeerId" placeholder="Peer ID (e.g. lab-peer-01)" style="padding:6px 8px;border-radius:6px;border:1px solid #2b3546;background:#0d1117;color:#e6edf3">'
        '<input type="text" id="collabPeerLabel" placeholder="Label (e.g. Lab Partner Mothership)" style="padding:6px 8px;border-radius:6px;border:1px solid #2b3546;background:#0d1117;color:#e6edf3">'
        '<select id="collabPeerTransport" style="padding:6px 8px;border-radius:6px;border:1px solid #2b3546;background:#0d1117;color:#e6edf3">'
        '<option value="tailscale_http">tailscale_http</option><option value="git_remote">git_remote</option><option value="packet_bundle">packet_bundle</option></select>'
        '<input type="text" id="collabPeerEndpoint" placeholder="Endpoint (http://100.x.y.z:8777 or git URL)" style="padding:6px 8px;border-radius:6px;border:1px solid #2b3546;background:#0d1117;color:#e6edf3">'
        '<button type="button" class="mini comms-sync-btn" id="btnCollabPeerSave">Save Peer</button>'
        '</div>'
        '<div style="display:grid;grid-template-columns:1fr 2fr auto;gap:6px;align-items:start">'
        '<input type="text" id="collabImportTargetDir" placeholder="Target folder for Packet Import (relative project path)" style="padding:6px 8px;border-radius:6px;border:1px solid #2b3546;background:#0d1117;color:#e6edf3">'
        '<textarea id="collabImportJson" rows="2" placeholder="Paste .anchor-cockpit.json packet JSON here to merge..." style="padding:6px 8px;border-radius:6px;border:1px solid #2b3546;background:#0d1117;color:#e6edf3"></textarea>'
        '<button type="button" class="mini" id="btnCollabPacketImport">&#128229; Import Packet</button>'
        '</div>'
        '<div id="collabModalStatus" style="margin-top:6px;font-size:12px;color:#8b949e"></div>'
        '</div>'
        '<div class="comms-grid" id="collabGrid">'
        '<div class="comms-col" id="collabPeersCol"><div class="comms-col-h">&#127760; Linked Collaborator Motherships</div>%s</div>'
        '<div class="comms-col" id="collabCockpitsCol"><div class="comms-col-h">&#128230; Shared Cockpits &amp; Step Leases (1-Click Handoff Packet)</div>%s</div>'
        '</div>'
        '<pre class="collab-packet-box" id="collabPacketPreview" hidden></pre>'
        '</div></section>'
    ) % (
        esc(ms.get("label") or "Mother Ship"),
        len(peers), "" if len(peers) == 1 else "s",
        len(leases), "" if len(leases) == 1 else "s",
        esc(ms.get("label") or "Mother Ship"), esc(ms.get("id") or "anchor-mothership"),
        "".join(peer_rows), "".join(cockpit_rows),
    )


TERM_ENGINES = (("claude", "Claude"), ("chatgpt", "ChatGPT"), ("grok", "Grok"), ("gemini", "Gemini"), ("shell", "Shell"))


def _terminal(ctx):
    """The Terminal at the foot of the board (2026-10-02, his word: the Workbench "seems old and not very useful ...
    we'll replace it with just simply a terminal ... you can choose which engine ... the default of the terminal
    engine ... it will open to dev ... more than one terminal opened, kind of like VS Code ... it just doesn't have the
    steward skill running in it ... at the bottom of the Cave of Wonders so it doesn't open a new window"). Tabs of
    plain engine terminals in the workspace root (static/cave-terminal.js, POST /api/cave/terminal). The health and
    failed rows the Workbench carried stay here, under it."""
    dflt = str(ctx.get("default_cli") or "claude")
    opts = "".join('<option value="%s"%s>%s</option>' % (k, " selected" if k == dflt else "", esc(v)) for k, v in TERM_ENGINES)
    sys_rows = [r for r in ctx.get("rows") or () if r.get("rule") == "failed"]     # the health row is the banner at the top
    sys_html = "".join('<a class="bench-row %s" href="%s"%s>%s <span class="dim">&middot; %s</span></a>' % (
        esc(r.get("severity")), esc(r.get("href")), ' target="_blank" rel="noopener"' if str(r.get("href", "")).startswith("/") else "",
        esc(r.get("text")), esc(r.get("why"))) for r in sys_rows[:4])
    return (
        '<section class="shelf" id="shTerm"><div class="shelf-h"><h3>Terminal</h3><span class="c" id="termCount">none open</span><span class="rule"></span>'
        '<label class="sr" for="termEngine">Engine</label><select class="term-eng" id="termEngine" title="the engine the new terminal runs - the Terminal seat by default">%s</select>'
        '<button class="dbtn" id="termNew" title="a plain terminal in C:/dev - no steward">+ Terminal</button></div>'
        '<div class="termdock" id="termDock" hidden><div class="termtabs" id="termTabs" role="tablist"></div>'
        '<div class="termbody" id="termBody"></div></div>%s</section>'
    ) % (opts, ('<div class="bench-sys">%s</div>' % sys_html) if sys_html else "")


KIND_LABEL = {"project": "cockpit", "effort": "cockpit within a project", "task": "desk item"}
_RECORD_FILES = ("ECGBERHT.md", "roadmap.json", "strip.json", ".ecgberht/conversation-log.json", ".ecgberht/status-summary.json")


_DATES_CACHE = {}


def cockpit_dates(folder):
    """Cached a minute (the SLOW samples, 2026-10-02: every candidate's record files stat'ed on every load)."""
    import time as _time
    hit = _DATES_CACHE.get(folder)
    if hit and _time.time() - hit[0] < 60:
        return hit[1]
    out = _cockpit_dates(folder)
    _DATES_CACHE[folder] = (_time.time(), out)
    return out


def _cockpit_dates(folder):
    """(created, last worked) of a cockpit's record, as dates: its Face's birth, and the newest of its record files.
    Read-only stats; (None, None) when the folder holds no record."""
    import os as _os
    from datetime import datetime as _dt
    born, last = None, None
    for rel in _RECORD_FILES:
        try:
            st = _os.stat(_os.path.join(folder, rel))
        except OSError:
            continue
        b = getattr(st, "st_birthtime", None) or st.st_ctime
        if rel == "ECGBERHT.md":
            born = b
        last = max(last or 0, st.st_mtime)
    d = lambda t: _dt.fromtimestamp(t).date().isoformat() if t else ""
    return d(born), d(last)


def candidates(ctx):
    """Everything he could put on deck or make active — delegated to high_seat_core.candidates_model (Wave 12)."""
    return candidates_model(ctx, dates_fn=cockpit_dates)


def _candidates_tile(ctx):
    in_goal, loose = candidates(ctx)
    n = len(in_goal) + len(loose)
    if not n:
        return ""

    def acts_step(sid):
        return ('<span class="acts"><button class="mini" data-seat="deck" data-step="%s">&rarr; on deck</button>'
                '<button class="mini" data-seat="active" data-step="%s">&rarr; active</button></span>') % (esc(sid), esc(sid))

    def acts_new(c):
        return ('<span class="acts"><button class="mini" data-cand-seat="deck" data-ref="%s" data-name="%s">&rarr; on deck</button>'
                '<button class="mini" data-cand-seat="active" data-ref="%s" data-name="%s">&rarr; active</button></span>') % (
            esc(c["ref"]), esc(c["name"]), esc(c["ref"]), esc(c["name"]))
    def meta(score, why, created, worked):
        return ('data-score="%d" data-created="%s" data-worked="%s"' % (score, esc(created or ""), esc(worked or "")),
                '<span class="cs" title="%s">%d</span>' % (esc(why), score),
                '<span class="cd">%s%s</span>' % (("worked " + esc(worked)) if worked else "not worked yet", (" &middot; made " + esc(created)) if created else ""))

    def row(attrs, score_html, dates_html, name_html, where, acts):
        return '<li class="cand" %s>%s<span class="cn">%s</span><span class="cw">%s</span>%s%s</li>' % (attrs, score_html, name_html, where, dates_html, acts)
    rows_a = "".join(row(*meta(p.get("c_score", 0), p.get("c_why", ""), p.get("c_created"), p.get("c_worked"))[:1],
                         meta(p.get("c_score", 0), p.get("c_why", ""), p.get("c_created"), p.get("c_worked"))[1],
                         meta(p.get("c_score", 0), p.get("c_why", ""), p.get("c_created"), p.get("c_worked"))[2],
                         ('<span class="wm">&#9873;</span> ' if p.get("needs_you") else "") + esc(part_name(p)),
                         "%s &middot; in %s" % (esc(KIND_LABEL.get(p.get("kind"), "")), esc(i.get("name") or "")), acts_step(p.get("id") or ""))
                     for i, p in sorted(in_goal, key=lambda t: -t[1].get("c_score", 0)))
    rows_b = "".join(row(*meta(c["score"], c["why"], c["created"], c["worked"])[:1], meta(c["score"], c["why"], c["created"], c["worked"])[1],
                         meta(c["score"], c["why"], c["created"], c["worked"])[2],
                         ('<span class="wm">&#9873;</span> ' if c["needs"] else "") + esc(c["name"]), "%s &middot; in no goal" % esc(c["where"]), acts_new(c))
                     for c in sorted(loose, key=lambda c: -c["score"]))
    return (
        '<section class="shelf cands" id="shCands"><details class="cands-tile" id="candsTile"><summary class="shelf-h">'
        '<h3>Candidates</h3><span class="c">%d</span><span class="rule"></span>'
        '<span class="sub">every cockpit and desk item you could put on deck or make active</span></summary>'
        '<div class="cand-tools"><input type="search" id="candSearch" placeholder="search the candidates&hellip;" aria-label="search the candidates" autocomplete="off">'
        '<label class="cand-sort">sort <select id="candSort"><option value="score" selected>the steward&rsquo;s relevance</option><option value="worked">last worked on</option>'
        '<option value="created">date created</option><option value="name">name</option></select></label>'
        '<span class="cand-note" id="candNote"></span></div>'
        '%s%s</details></section>'
    ) % (n,
         ('<div class="cand-group"><div class="k">In a goal, not on the desk &middot; %d</div><ul>%s</ul></div>' % (len(in_goal), rows_a)) if in_goal else "",
         ('<div class="cand-group"><div class="k">AI cockpits in no goal &middot; %d</div><ul>%s</ul></div>' % (len(loose), rows_b)) if loose else "")


def _seed_panel(ctx):
    """What the Seeds button opens (John, 2026-09-27: "nothing happens. Something should happen"): the Campaign's
    seeds, each with Make it an initiative — which puts the steward's own verb into the composer ("make <seed> an
    initiative in tier 3"), his Send being the word — and the way to the Campaign, where the tier and the life area
    are asked on the card. Nothing here writes."""
    rows = ctx.get("seed_rows") or []
    camp = ctx.get("campaign") or {}
    if not camp:
        body = '<div class="sd"><span class="st dim">The %s is not stood up yet; seeds arrive with it.</span></div>' % esc(mode_name(ctx.get("steward")))
    elif not rows:
        body = '<div class="sd"><span class="st dim">No seeds yet.<em>Tell the steward &ldquo;seed: &hellip;&rdquo; here, or in a cockpit&rsquo;s grasscatcher.</em></span></div>'
    else:
        body = "".join(
            '<div class="sd" data-seed="%s"><span class="st">%s<em>%s</em></span>'
            '<button class="go" data-seed-text="%s" title="puts the verb in the composer; Send is the word">Make it a goal</button></div>' % (
                esc(r.get("id")), esc(r.get("text")), ("caught " + esc(_hr.short_date(r.get("at")))) if r.get("at") else "from the grasscatcher", esc(r.get("text")))
            for r in rows)
    foot = ('<div class="hint">A seed becomes a goal in tier 3 unless you say the tier and the life area &mdash; '
            '<a href="/project/%s" target="_blank" rel="noopener">the %s</a> asks both on the card.</div>' % (esc(camp.get("pid")), esc(mode_name(ctx.get("steward"))))) if camp else ""
    return '<section class="seedpanel" id="seedPanel"><h4>Seeds &middot; %d</h4>%s%s</section>' % (len(rows), body, foot)


def _head_li(ctx):
    """W2 (2026-09-28): the head — ONE act as the lead, rendered from the head itself (so the sentence can never
    diverge from its button): the sentence, then the act that opens its record (the Status part on that project's
    card — on the card's own effort unless the act names one), marked when it is the exception. Under it, only the
    week's dates, folded and named for what they hold (Grok W2: the old count brief is gone)."""
    import home_attention as _ha
    head = ctx.get("head") if isinstance(ctx.get("head"), dict) else None
    pickup = ctx.get("pickup") if isinstance(ctx.get("pickup"), dict) else None   # W1 of the active set: while the set runs, what to pick up
    lead = esc(_ha.head_sentence(head, overnight=ctx.get("overnight") or (), pickup=pickup))
    cls = "lead exc" if head and head.get("kind") == "exception" else "lead"
    act = ""
    if head and head.get("pid"):
        dir_attr = (' data-dir="%s"' % esc(head["dir"])) if head.get("dir") else ""   # only an act that names its effort
        act = ' <button class="h-open" data-part="status" data-pid="%s"%s>open</button>' % (esc(head["pid"]), dir_attr)
    elif head is None and pickup and pickup.get("pid"):
        act = ' <button class="h-open" data-part="status" data-pid="%s">open</button>' % esc(pickup["pid"])   # the pick-up opens its project
    week = [b for b in (ctx.get("bullets") or [])[1:] if str(b).startswith(("This week", "Nothing is due this week", "Nothing carries a date"))]
    more = ('<details class="brief-more"><summary>this week</summary><ul>%s</ul></details>' % "".join('<li>%s</li>' % esc(b) for b in week)) if week else ""
    return '<li class="%s">%s%s</li>%s' % (cls, lead, act, ('<li class="fold">%s</li>' % more) if more else "")


CAVE_EFFORT = "Cave of Wonders"   # the Cave's own steward conversation, an effort of the Campaign (2026-10-02)


def conversation_view(label, camp_pid, inst="main", dir_="", title="the conversation"):
    """A steward conversation as the AI Cockpit renders it - its blocks, its markdown, its live flow - and nothing else
    of the cockpit (his word, 2026-10-02: "I just want the steward dialogue from an AI Cockpit, maybe have the status
    bar available but thinner, and the plan is not something that we have to worry about in those pages"): the view
    /steward/v1?view=talk under a thin status line; the page's own box below carries the verbs, receipts and undo.
    ``dir_`` names the conversation: "" the Campaign's, CAVE_EFFORT the Cave of Wonders' own. The Deliverables bar
    lists what that conversation made."""
    src = "/steward/v1?embed=1&amp;view=talk&amp;inst=%s&amp;pid=%s&amp;dir=%s" % (esc(inst), esc(camp_pid), esc(_quote(dir_)))
    foundry_bar = ""
    head_ico = ""
    if inst == "cave":
        foundry_bar = (
            '<div class="cos-foundry-bar" id="cosFoundryBar" aria-label="Steward quick actions">'
            '<button type="button" class="cos-fbtn" data-foundry-action="new_cockpit" title="Ask Steward to create and place a new AI Cockpit">'
            '<img src="/vendor/brand/new-cockpit-icon.jpg" alt=""><span>+ New AI Cockpit</span></button>'
            '<button type="button" class="cos-fbtn" data-foundry-action="brainstorm" title="Start a structured brainstorm with the Steward">'
            '<img src="/vendor/brand/brainstorm-icon.jpg" alt=""><span>Brainstorm</span></button>'
            '<button type="button" class="cos-fbtn" data-foundry-action="modify_today" title="Rebalance Today priorities or move a cockpit status">'
            '<img src="/vendor/brand/crucible-icon.svg" alt=""><span>Modify Today / Status</span></button>'
            '<button type="button" class="cos-fbtn" data-foundry-action="desk_calendar" title="Add an admin item to the Desk or schedule a deadline">'
            '<img src="/vendor/brand/desk-tab-aladdin.png" alt=""><span>+ Desk / Calendar</span></button>'
            '</div>'
        )
    elif inst == "campaign":
        head_ico = '<img class="w20-mini-ico" src="/vendor/brand/campaign-aladdin-star-chart.jpg" alt="">'
        foundry_bar = (
            '<div class="cos-foundry-bar" id="cosFoundryBar" aria-label="Star Chart Steward quick actions">'
            '<button type="button" class="cos-fbtn" data-foundry-action="diamond" title="Run a Don Hambrick Strategy Diamond alignment audit">'
            '<img src="/vendor/brand/campaign-aladdin-star-chart.jpg" alt=""><span>Strategy Diamond</span></button>'
            '<button type="button" class="cos-fbtn" data-foundry-action="new_goal" title="Create a new Goal or AI Cockpit">'
            '<img src="/vendor/brand/new-cockpit-icon.jpg" alt=""><span>+ New Goal / Cockpit</span></button>'
            '<button type="button" class="cos-fbtn" data-foundry-action="brainstorm" title="Brainstorm strategy &amp; resource timing with the Steward">'
            '<img src="/vendor/brand/brainstorm-icon.jpg" alt=""><span>Brainstorm</span></button>'
            '<button type="button" class="cos-fbtn" data-foundry-action="rebalance" title="Rebalance Star Chart tiers &amp; Cave of Wonders shelves">'
            '<img src="/vendor/brand/crucible-icon.svg" alt=""><span>Rebalance Tiers</span></button>'
            '</div>'
        )
    return (
        '<section class="exwrap cview" id="dialogue" data-dir="%s"><div class="exhead">%s<h3>%s &mdash; %s</h3><span class="exstate" id="exState" data-state="">&hellip;</span>'
        '<a class="note" href="/steward/v1?pid=%s&amp;dir=%s" target="_blank" rel="noopener" title="this conversation in its cockpit, full size">open in the cockpit &#8599;</a></div>'
        '<iframe class="cview-frame" src="%s" title="%s &mdash; %s"></iframe>'
        '<ul class="ex" id="exList" hidden></ul>%s</section>'
        '<section class="delivbar" id="delivBar" data-pid="%s" data-dir="%s"><button class="db-h" id="delivToggle" type="button" aria-expanded="false" aria-controls="delivList">'
        '<span class="db-t">Deliverables</span><span class="db-c" id="delivCount">&hellip;</span><span class="db-caret">&#9662;</span></button>'
        '<ul class="db-list" id="delivList" hidden></ul></section>'
    ) % (esc(dir_), head_ico, esc(label), esc(title), esc(camp_pid), esc(_quote(dir_)),
         src, esc(label), esc(title), foundry_bar, esc(camp_pid), esc(dir_))


def _dialogue(ctx):
    """The steward's dialogue on the Cave of Wonders: the Cave's OWN conversation (2026-10-02, his word: one for the Cave,
    one for the Campaign), shown as the cockpit renders it (conversation_view). Nothing here without a Campaign."""
    if not ctx.get("campaign"):
        return ""
    return conversation_view(ctx["steward"]["label"], (ctx.get("campaign") or {}).get("pid") or "", "cave", CAVE_EFFORT, "the Cave of Wonders")


def lane_html(n, resume_from=""):
    """The interrupt lane (John, 2026-10-03: on the Cave of Wonders, "seen more regularly ... the main day to day work
    page"): a dated item within three days, at the top of the board, once. Opening it keeps a ready-to-resume note of
    what he is on (the active initiatives); 'not now' is the nudge's own receipt."""
    if not n:
        return ""
    acts = []
    for a in n.get("acts") or []:
        if a.get("act") == "open" and a.get("href"):
            acts.append('<a class="mini lane-open" data-lane-open="1" data-switched="%s" href="%s">%s</a>' % (esc(re.sub(r"^Excuse me:\s*", "", n.get("text") or ""))[:160], esc(a["href"]), esc(a.get("label") or "open")))
    acts.append('<button class="mini" data-nudge-act="not_now" data-key="%s" data-fact="%s" data-text="%s">not now</button>' % (esc(n.get("key") or ""), esc(n.get("fact") or ""), esc((n.get("text") or "")[:200])))
    note = ('<span class="lnote">If you switch now, a note of what you were on is kept: &ldquo;%s&rdquo;</span>' % esc(resume_from)) if resume_from else ""
    return ('<section class="lane" id="lane" data-nudge="%s" data-note="%s"><span class="lk">&#9873; interrupt lane</span><span class="ltext">%s</span>'
            '<span class="nacts">%s</span><span class="nwhy">read from %s</span>%s</section>') % (
        esc(n.get("key") or ""), esc(resume_from), esc(n.get("text") or ""), "".join(acts), esc(n.get("why") or "the record"), note)


def resume_html(r):
    """The ready-to-resume note, at the top of the panel until he clears it (or two days pass)."""
    if not isinstance(r, dict) or not r.get("note"):
        return ""
    return ('<div class="nudge resume" id="resumeNote"><span class="nk">&#8617; ready to resume</span><span class="ntext">You were on %s%s</span>'
            '<span class="nacts"><button class="mini" data-nudge-act="resume_done">done</button></span><span class="nwhy">kept %s</span></div>') % (
        esc(r["note"]), (" when you opened: %s" % esc(r["switched_to"])) if r.get("switched_to") else ".", esc(r.get("at") or ""))


def nudge_html(n, where="brief"):
    """W3 (2026-10-01, fits 8-9): the steward stepping in - ONE line in his words with its reason, the fact it read (the
    receipt), and the acts in one click: make it active · put it on deck · make it a goal · open · not now. Nothing
    moves without the click; 'not now' is a receipt with undo."""
    if not n:
        return ""
    acts = []
    for a in n.get("acts") or []:
        if a.get("act") == "open" and a.get("href"):
            acts.append('<a class="mini" href="%s">%s</a>' % (esc(a["href"]), esc(a.get("label") or "open")))
        elif a.get("act") == "seat":
            acts.append('<button class="mini" data-nudge-act="seat" data-step="%s" data-seat="%s">%s</button>' % (esc(a.get("step") or ""), esc(a.get("seat") or ""), esc(a.get("label") or "seat")))
        elif a.get("act") == "promote":
            acts.append('<button class="mini" data-nudge-act="promote" data-seed="%s" data-tier="%s" data-done-when="%s">%s</button>' % (esc(a.get("seed") or ""), esc(str(a.get("tier") or 2)), esc(a.get("done_when") or ""), esc(a.get("label") or "make it a goal")))
    acts.append('<button class="mini" data-nudge-act="not_now" data-key="%s" data-fact="%s" data-text="%s">not now</button>' % (esc(n.get("key") or ""), esc(n.get("fact") or ""), esc((n.get("text") or "")[:200])))
    return ('<div class="nudge %s" data-nudge="%s" data-kind="%s"><span class="nk">&#9873; the steward</span><span class="ntext">%s</span>'
            '<span class="nacts">%s</span><span class="nwhy">read from %s</span></div>') % (
        esc(where), esc(n.get("key") or ""), esc(n.get("kind") or ""), esc(n.get("text") or ""), "".join(acts), esc(n.get("why") or "the record"))


def _panel(ctx):
    st = ctx["steward"]
    seeds = int(ctx.get("seeds") or 0)
    return (
        '<aside class="panel"><div class="seedbar"><button class="seedbtn" id="seedBtn" aria-expanded="false" aria-controls="seedPanel"><span>Seeds</span><span class="cnt" id="seedCount">%d</span></button><span class="lbl" id="seedLbl">%s</span></div>%s'
        # the brief is gone (John, 2026-10-03: "I'm not sure it helps on the cave of wonders page either"); the
        # steward's nudge and the ready-to-resume note keep their place at the top of the panel (Grok R1 F1)
        '<section class="nudgeslot" id="nudgeSlot" aria-label="The steward steps in">%s%s</section>'
        # R14 (2026-09-29): the token is pasted INTO the page — a browser pop-up (window.prompt) is what his desktop
        # browser suppressed ("I click that button and nothing happens"); the box is hidden until it is needed
        '<div class="loginbox" id="loginBox" hidden><span class="lb-t">This browser is not logged in to Anchor.</span>'
        '<input id="loginTok" type="password" placeholder="paste the token here" autocomplete="off" spellcheck="false">'
        '<button class="mini" id="loginGo">Log in</button><span class="lb-msg" id="loginMsg"></span></div>'
        '%s'
        '<button id="cave-provider-capacity" class="provider-capacity" type="button" aria-label="Provider capacity and details"><strong>Provider capacity</strong><span>Unknown · reading host settings</span></button>'
        '<section class="composer"><label class="sr" for="say">Tell the steward what to do</label>'
        '<textarea id="say" rows="2" placeholder="Ask %s, discuss, or tell it what to do &mdash; it answers above as it writes; a %s verb applies on the record"></textarea>'
        '<div class="comp-row"><span class="hint">Enter sends &middot; Shift+Enter new line &middot; the Cave&rsquo;s steward answers above &middot; start a new project called &lt;name&gt; at &lt;folder&gt;</span><button class="send" id="sendBtn">Send</button></div>'
        '<div class="receipt" id="receipt" hidden><span class="r-mark">&#10003;</span><span id="receiptText"></span> <button class="mini" id="undoBtn" hidden>undo</button></div></section></aside>'
    ) % (seeds, "ideas that could start a project" if seeds else "no seeds yet", _seed_panel(ctx),
         resume_html(ctx.get("resume")), nudge_html(ctx.get("nudge"), "brief"), _dialogue(ctx), esc(st["label"]), esc(mode_name(st)))


def render_locked_html(ctx) -> str:
    """The Cave with no login (his word, 2026-10-03: "lock the Cave too"): over Tailscale the page showed the whole
    portfolio before any token, only the steward's words were refused. Now a request with neither the login cookie nor
    a valid token sees the anchor and a token box, nothing of the record. A token this device already saved logs in by
    itself; a pasted one is checked by POST /api/auth/login (which mints the 30-day cookie) and the page reloads into
    the Cave. PUTER's own browser and program are logged in by the server (the loopback cookie), so they never see it."""
    b = ctx.get("build") or ""
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>Anchor - locked</title>%s'
        '<style>:root{color-scheme:dark}body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0f141c;color:#e6ebf2;'
        'font:15px/1.5 "Segoe UI Variable Text","Segoe UI",system-ui,-apple-system,sans-serif;padding:16px;box-sizing:border-box}'
        '.card{width:min(440px,100%%);background:#161d29;border:1px solid #2b3546;border-radius:12px;padding:26px 28px;text-align:center}'
        '.card img{width:56px;height:56px;border-radius:12px}h1{font-size:19px;margin:12px 0 4px}p{color:#98a4b8;margin:0 0 16px}'
        'input{width:100%%;box-sizing:border-box;font:15px system-ui;padding:9px 11px;border-radius:8px;border:1px solid #3a4658;background:#0f141c;color:#e6ebf2}'
        'input:focus{outline:2px solid #e0a836;outline-offset:1px}button{margin-top:12px;font:600 14px system-ui;padding:8px 18px;border-radius:8px;'
        'border:1px solid #e0a836;background:#e0a836;color:#1a1a1a;cursor:pointer}#msg{min-height:22px;margin-top:10px;color:#e0a836;font-size:14px}</style>'
        '</head><body><div class="card"><img src="/vendor/brand/anchor-icon-180.png?v=%s" alt="">'
        '<h1>Anchor is locked</h1><p>Paste your Anchor token to open the Cave of Wonders on this device. You only do this once.</p>'
        '<input id="tok" type="password" autocomplete="off" placeholder="paste the token here" aria-label="Anchor token">'
        '<button id="go" type="button">Open the Cave</button><div id="msg" role="status"></div></div>'
        '<script>(function(){var tok=document.getElementById("tok"),go=document.getElementById("go"),msg=document.getElementById("msg");'
        'function login(t,quiet){go.disabled=true;if(!quiet)msg.textContent="Checking…";'
        'return fetch("/api/auth/login",{method:"POST",headers:{"Content-Type":"application/json","X-Anchor-Token":t},body:JSON.stringify({token:t})})'
        '.then(function(r){go.disabled=false;if(r.ok){try{localStorage.setItem("anchor_token",t)}catch(e){}location.reload();return}'
        'try{localStorage.removeItem("anchor_token")}catch(e){}msg.textContent=r.status===401?(quiet?"The token saved here is out of date - paste the current one.":"That token was refused - it is not the current one."):"That did not go through; try again."})'
        '.catch(function(){go.disabled=false;msg.textContent="Anchor did not answer; try again."})}'
        'go.addEventListener("click",function(){var t=tok.value.trim();if(!t){msg.textContent="Paste the token first.";return}login(t)});'
        'tok.addEventListener("keydown",function(e){if(e.key==="Enter"){e.preventDefault();go.click()}});'
        'var saved="";try{saved=localStorage.getItem("anchor_token")||""}catch(e){}if(saved)login(saved,true);else tok.focus();})();</script>'
        '</body></html>'
    ) % (tab_icon_link(None, b), esc(b))


def _tile_names(ctx):
    """The names and pictures the app's tiles carry (his rule, 2026-10-03): the Cave, the Campaign board in its mode
    (Star Chart / Chart Room / Beacon) and the two conversations' cockpits are named for what they show."""
    import json as _json
    st = ctx.get("steward") or {}
    b = ctx.get("build") or ""
    pic = lambda name: ("/vendor/brand/%s?v=%s" % (name, b)) if name else ""
    return "seat_name: %s, seat_icon: %s, mode_name: %s, mode_icon: %s" % (
        _json.dumps(st.get("high_seat_name") or "Cave of Wonders"), _json.dumps(pic(st.get("high_seat"))),
        _json.dumps(mode_name(st)), _json.dumps(pic(st.get("campaign_icon"))))


def _proactive_triage_strip(ctx):
    """Wave 6b, Wave 15 & Wave 19: Compact 5-Horizon Chief-of-Staff Triage Strip at the top of the Cave of Wonders board
    (Today · This Week · This Month · This Quarter · This Year) with expandable Level-2/Level-3 drawers,
    1-click Synthesize Executive Brief button, and live folder/commitment cards."""
    cards = proactive_triage_cards(ctx)
    desk_pid = str(ctx.get("desk_pid") or "")
    desk_href = ("/steward/v1?pid=%s&amp;dir=Small%%20items" % esc(desk_pid)) if desk_pid else "/desk"

    # Build Today drawer items (preserving .triage-card, data-mark-done, and Desktop Ad-Hoc AI Cockpit links)
    today_items_html = []
    for c in cards:
        acts = []
        if c.get("is_desk"):
            acts.append('<a class="tc-btn primary" href="%s" target="_blank" rel="noopener">&#128421; Open Ad-Hoc Cockpit &#8599;</a>' % desk_href)
            acts.append('<a class="tc-btn" href="/desk" target="_blank" rel="noopener">Desk Board</a>')
        else:
            if c.get("folder"):
                acts.append(
                    '<button type="button" class="tc-btn done" data-mark-done="1" data-target-dir="%s" data-target-step="%s" title="Mark this step done">&#10003; Mark Done</button>'
                    % (esc(c["folder"]), esc(c.get("step_id") or ""))
                )
            if c.get("pid"):
                acts.append(
                    '<a class="tc-btn" href="/steward/v1?pid=%s&amp;dir=" target="_blank" rel="noopener">Cockpit &#8599;</a>'
                    % esc(c["pid"])
                )
        badge_cls = "q2" if c.get("tone") == "focus" else ("q1" if c.get("tone") in ("warn", "urgent") else "q3")
        today_items_html.append(
            '<div class="hz-item triage-card %s" id="%s">'
            '<div class="hz-item-row">'
            '<span class="hz-qbadge %s tc-rule">%s</span>'
            '<span class="hz-item-title tc-title">%s</span>'
            '<span class="hz-item-meta">%s</span>'
            '<div class="tc-acts">%s</div>'
            '</div>'
            '<div class="hz-detail"><div class="tc-why">%s</div></div>'
            '</div>'
            % (esc(c["tone"]), esc(c["id"]), badge_cls, esc(c["rule"]), esc(c["title"]), esc(c["rule"]), "".join(acts), esc(c["why"]))
        )

    # Build This Week drawer items from this_week_horizon_buckets(ctx)
    hb = this_week_horizon_buckets(ctx)
    week_items_html = []
    week_total = 0
    week_labels = []
    for bucket_lbl, bucket_cls, items_list in (
        ("Overdue", "q1", hb.get("col_overdue") or []),
        ("Today", "q2", hb.get("col_today") or []),
        ("Next 72h", "q2", hb.get("col_72h") or []),
        ("Days 4-7", "q3", hb.get("col_week") or []),
    ):
        for it in items_list:
            week_total += 1
            nm = it.get("name") or "Step"
            pnm = it.get("project_name") or ""
            pid = it.get("project_id") or ""
            due_s = _short(it.get("due") or "")
            if len(week_labels) < 3:
                week_labels.append(nm)
            act_btn = ('<a class="tc-btn" href="/project/%s" target="_blank" rel="noopener">Project &#8599;</a>' % esc(pid)) if pid else ""
            week_items_html.append(
                '<div class="hz-item">'
                '<div class="hz-item-row">'
                '<span class="hz-qbadge %s">%s</span>'
                '<span class="hz-item-title">%s</span>'
                '<span class="hz-item-meta">%s &middot; %s</span>'
                '<div class="tc-acts">%s</div>'
                '</div>'
                '<div class="hz-detail">%s &mdash; due %s (%s)</div>'
                '</div>'
                % (bucket_cls, esc(bucket_lbl), esc(nm), esc(due_s), esc(pnm), act_btn, esc(nm), esc(due_s), esc(pnm))
            )
    if not week_items_html:
        week_items_html.append(
            '<div class="hz-item"><div class="hz-item-row"><span class="hz-qbadge q2">This Week</span>'
            '<span class="hz-item-title">Clear 7-Day Horizon &mdash; Deep Work Focus</span><span class="hz-item-meta">0 due</span>'
            '<div class="tc-acts"><button type="button" class="tc-btn" data-toggle-dated="1">Dated Ruler</button></div></div>'
            '<div class="hz-detail">No open dated steps due within the next 7 days.</div></div>'
        )

    # Build This Month, This Quarter, This Year drawers from initiatives & goals
    inits = ctx.get("initiatives") or []
    goals = goals_only(inits)
    active_or_deck = [i for i in inits if (i.get("seat") in ("active", "on_deck") or i.get("status") in ("in_progress", "active"))]
    month_items_html = []
    for i in (active_or_deck or inits)[:6]:
        nm = i.get("title") or i.get("name") or i.get("id") or "Initiative"
        why = i.get("done_when") or i.get("summary") or "Monthly deliverable target"
        month_items_html.append(
            '<div class="hz-item"><div class="hz-item-row"><span class="hz-qbadge q2">Month</span>'
            '<span class="hz-item-title">%s</span><span class="hz-item-meta">%s</span>'
            '<div class="tc-acts"><a class="tc-btn" href="/campaign">Star Chart &#8599;</a></div></div>'
            '<div class="hz-detail">%s</div></div>' % (esc(nm), esc(i.get("seat") or "deliverable"), esc(why))
        )
    if not month_items_html:
        month_items_html.append(
            '<div class="hz-item"><div class="hz-item-row"><span class="hz-qbadge q2">Month</span>'
            '<span class="hz-item-title">Monthly Campaign Deliverables &amp; System Hardening</span><span class="hz-item-meta">Month arc</span>'
            '<div class="tc-acts"><a class="tc-btn" href="/campaign">Star Chart &#8599;</a></div></div>'
            '<div class="hz-detail">Click into Star Chart to review monthly campaign milestones.</div></div>'
        )

    quarter_items_html = []
    for g in (goals or inits)[:6]:
        nm = g.get("title") or g.get("name") or g.get("id") or "Quarter Goal"
        why = g.get("done_when") or g.get("summary") or "Quarterly campaign milestone"
        quarter_items_html.append(
            '<div class="hz-item"><div class="hz-item-row"><span class="hz-qbadge q2">&#9733; Quarter</span>'
            '<span class="hz-item-title">%s</span><span class="hz-item-meta">Star Chart Goal</span>'
            '<div class="tc-acts"><a class="tc-btn" href="/campaign">Star Chart &#8599;</a></div></div>'
            '<div class="hz-detail">%s</div></div>' % (esc(nm), esc(why))
        )
    if not quarter_items_html:
        quarter_items_html.append(
            '<div class="hz-item"><div class="hz-item-row"><span class="hz-qbadge q2">&#9733; Quarter</span>'
            '<span class="hz-item-title">Quarterly Star Chart Campaign Objectives</span><span class="hz-item-meta">Star Chart</span>'
            '<div class="tc-acts"><a class="tc-btn" href="/campaign">Star Chart &#8599;</a></div></div>'
            '<div class="hz-detail">Ties directly into Star Chart quarterly rocks and milestones.</div></div>'
        )

    year_items_html = [
        '<div class="hz-item"><div class="hz-item-row"><span class="hz-qbadge q2">&#9733; Year Vision</span>'
        '<span class="hz-item-title">%s</span><span class="hz-item-meta">Annual North Star</span>'
        '<div class="tc-acts"><a class="tc-btn" href="/campaign">Star Chart &#8599;</a></div></div>'
        '<div class="hz-detail">%s</div></div>'
        % (esc((g.get("title") or g.get("name") or "Annual Flagship Goal")), esc(g.get("done_when") or "Annual academic & deep-work vision on the Star Chart."))
        for g in (goals[:4] if goals else [{"title": "Academic Deep-Work & Anchor Collaboration Platform", "done_when": "Full year research, book/manuscript creation, and Anchor + Skill Foundry release."}])
    ]

    today_sum = " &middot; ".join(esc(c.get("title") or "")[:36] for c in cards[:2]) or "Deep Work &amp; Priority Triage"
    week_sum = " &middot; ".join(esc(lbl)[:32] for lbl in week_labels[:2]) or "Weekly Sprints &amp; Deadlines"
    month_cnt = max(len(active_or_deck), len(month_items_html))
    quarter_cnt = max(len(goals), len(quarter_items_html))
    year_cnt = max(len(goals), 1)
    mode_lbl = esc(mode_name(ctx.get("steward") or {}))

    return (
        '<section class="triage-strip compact-horizons" id="shTriage">'
        '<div class="ts-head chz-head">'
        '<div class="ts-title chz-title"><span class="ts-badge chz-badge">&#9733; Proactive Chief-of-Staff Triage</span>'
        '<span class="ts-sub chz-sub">Newport Deep Work &middot; Covey Q2 &middot; Eisenhower &mdash; click any horizon to expand</span></div>'
        '<div class="ts-quick chz-quick">'
        '<button type="button" class="ts-pill" id="btnTriageSynthesize" data-triage-synthesize="1" title="Synthesize a cross-portfolio Chief-of-Staff Executive Brief">&#10022; Synthesize Brief</button>'
        '<a class="ts-pill desk" href="%s" target="_blank" rel="noopener" title="Run ad-hoc admin tasks in the Desktop AI Cockpit">&#128421; Desktop (Ad-Hoc AI Cockpit)</a>'
        '<button type="button" class="ts-pill" data-toggle-dated="1" title="Toggle Dated Schedule Ruler">&#128197; Dated Ruler</button>'
        '<button type="button" class="ts-pill" data-jump="#cal">&#9993; Email &amp; Counsel</button>'
        '</div></div>'
        '<div class="triage-exec-brief" id="triageExecBrief" hidden style="margin:0 0 8px;padding:8px 12px;border-radius:8px;border:1px solid #2b3546;background:#121822;font-size:12px;color:#e6edf3"></div>'
        '<div class="chz-grid ts-grid">'
        '<button type="button" class="chz-card today" data-hz-toggle="today" aria-expanded="false" aria-controls="hzDrawer-today">'
        '<div class="chz-top"><span class="chz-name">Today</span><span class="chz-cnt">%d items &#9662;</span></div>'
        '<div class="chz-sum">%s</div>'
        '<div class="chz-tag"><span class="dot g"></span>Deep Work + Q1/Desk</div></button>'
        '<button type="button" class="chz-card week" data-hz-toggle="week" aria-expanded="false" aria-controls="hzDrawer-week">'
        '<div class="chz-top"><span class="chz-name">This Week</span><span class="chz-cnt">%d items &#9662;</span></div>'
        '<div class="chz-sum">%s</div>'
        '<div class="chz-tag"><span class="dot b"></span>7-Day Horizon</div></button>'
        '<button type="button" class="chz-card" data-hz-toggle="month" aria-expanded="false" aria-controls="hzDrawer-month">'
        '<div class="chz-top"><span class="chz-name">This Month</span><span class="chz-cnt">%d items &#9662;</span></div>'
        '<div class="chz-sum">Active &amp; On-Deck Deliverables</div>'
        '<div class="chz-tag"><span class="dot p"></span>30-Day Milestones</div></button>'
        '<button type="button" class="chz-card star" data-hz-toggle="quarter" aria-expanded="false" aria-controls="hzDrawer-quarter">'
        '<div class="chz-top"><span class="chz-name">This Quarter</span><span class="chz-cnt">%d goals &#9662;</span></div>'
        '<div class="chz-sum">Quarterly Rocks &amp; Campaign Arcs</div>'
        '<div class="chz-tag">&#9733; %s</div></button>'
        '<button type="button" class="chz-card star" data-hz-toggle="year" aria-expanded="false" aria-controls="hzDrawer-year">'
        '<div class="chz-top"><span class="chz-name">This Year</span><span class="chz-cnt">%d pillars &#9662;</span></div>'
        '<div class="chz-sum">Annual Vision &amp; Flagship Research</div>'
        '<div class="chz-tag">&#9733; %s</div></button>'
        '</div>'
        '<div class="chz-drawer" id="hzDrawer-today" hidden>'
        '<div class="chz-drawer-head"><span><strong>Today &mdash; Chief-of-Staff Priority Stack</strong> (click any item for detail or action)</span>'
        '<button type="button" class="mini" data-hz-close="1">Close &#10005;</button></div>'
        '<div class="hz-list">%s</div></div>'
        '<div class="chz-drawer" id="hzDrawer-week" hidden>'
        '<div class="chz-drawer-head"><span><strong>This Week &mdash; 7-Day Sprints &amp; Commitments</strong></span>'
        '<button type="button" class="mini" data-hz-close="1">Close &#10005;</button></div>'
        '<div class="hz-list">%s</div></div>'
        '<div class="chz-drawer" id="hzDrawer-month" hidden>'
        '<div class="chz-drawer-head"><span><strong>This Month &mdash; 30-Day Deliverables</strong></span>'
        '<button type="button" class="mini" data-hz-close="1">Close &#10005;</button></div>'
        '<div class="hz-list">%s</div></div>'
        '<div class="chz-drawer" id="hzDrawer-quarter" hidden>'
        '<div class="chz-drawer-head"><span><strong>This Quarter &mdash; %s Quarterly Rocks</strong></span>'
        '<button type="button" class="mini" data-hz-close="1">Close &#10005;</button></div>'
        '<div class="hz-list">%s</div></div>'
        '<div class="chz-drawer" id="hzDrawer-year" hidden>'
        '<div class="chz-drawer-head"><span><strong>This Year &mdash; Annual %s Vision</strong></span>'
        '<button type="button" class="mini" data-hz-close="1">Close &#10005;</button></div>'
        '<div class="hz-list">%s</div></div>'
        '</section>'
    ) % (
        desk_href,
        len(cards), today_sum,
        week_total, week_sum,
        month_cnt,
        quarter_cnt, mode_lbl,
        year_cnt, mode_lbl,
        "".join(today_items_html),
        "".join(week_items_html),
        "".join(month_items_html),
        mode_lbl, "".join(quarter_items_html),
        mode_lbl, "".join(year_items_html),
    )



def render_high_seat_html(ctx) -> str:
    """The whole page from the context dict (see the module docstring)."""
    if ctx.get("auth_required") and not ctx.get("logged_in"):
        return render_locked_html(ctx)                  # no login, no record (2026-10-03)
    facts = ctx["facts"]
    entries = ctx.get("entries") or []
    by_id = {e.get("id"): e for e in entries}
    parked = ctx.get("parked") or []
    parked_ids = {e.get("id") for e in parked}
    inits = ctx.get("initiatives") or []
    live_inits = [i for i in inits if i.get("status") not in ("done", "parked")]
    # W2c (2026-09-30, his three levels): the goals as a thin tile, then ACTIVE and ON DECK as shelves of initiative
    # cards; the Projects tile (the registry) with its projects in no goal; the Desk, the ruler and the Workbench as
    # before. The old shelves (Needs you · Continuing · Parked) are gone: a project is on a shelf because he seated
    # it, and every project is in the Projects tile.
    in_goal = {p["pid"] for i in inits for p in i.get("parts") or () if p.get("kind") in ("project", "effort") and p.get("pid")}
    camp_pid = (ctx.get("campaign") or {}).get("pid")
    ctx["orphans"] = [e for e in entries if e.get("id") and e["id"] not in in_goal and e["id"] != camp_pid and e["id"] not in parked_ids]
    ctx["quiet_n"] = sum(1 for e in entries if not (facts.get(e.get("id")) or {}).get("has_record") and e.get("id") not in parked_ids)
    ctx["on_board"] = {p["pid"]: SEAT_NAMES[seat] for seat in ("deck", "active") for g, p in seated(live_inits, seat) if p.get("pid")}      # Active wins when a project has cards on both (Grok's read of W2c)
    board = ('<div class="board">' + lane_html(ctx.get("lane"), ctx.get("resume_from") or "") + _proactive_triage_strip(ctx) + _campaign_tile(ctx) + _seat_shelves(ctx) + _candidates_tile(ctx) + _projects_tile(ctx)
             + _desk_line(ctx) + _ruler(ctx) + _mothership_collab_html(ctx) + _terminal(ctx) + '</div>')
    page = (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>%s</title>%s'
        '<link rel="stylesheet" href="/static/steward-dialogue.css?v=%s"><link rel="stylesheet" href="/static/high-seat-page.css?v=%s">'
        '<script>window.ANCHOR_BOOT = {build_id: "%s", campaign_pid: "%s", auth_required: %s, logged_in: %s, steward: "%s", stamp: "%s", you: "%s", health: "%s"};window.ANCHOR_TILES = {%s};</script></head>'
        '<body><div class="app">%s<div class="main">%s%s%s<div class="prefs">%s</div><div class="canvas">%s%s</div>'
        '<div class="foot">%s<span>A <b class="gwl-accent">Ghost World Labs</b> tool &middot; Powered by NextGen Nuclear &middot; AI Cockpit &middot; J.C. Liechty</span>'
        '<span>&mdash; every row on this page is read from a record; where nothing is connected or measured, it says so.</span></div></div></div>'
        '<link rel="stylesheet" href="/vendor/xterm/xterm.css"><script src="/vendor/xterm/xterm.js"></script>'
        '<script src="/steward-static/md.js?v=%s"></script><script src="/static/steward-dialogue.js?v=%s"></script><script src="/static/high-seat-page.js?v=%s"></script><script src="/static/cave-terminal.js?v=%s"></script></body></html>'
    ) % (esc(ctx["steward"]["high_seat_name"]), tab_icon_link(ctx["steward"].get("high_seat"), ctx["build"], anchor=False), esc(ctx["build"]), esc(ctx["build"]), esc(ctx["build"]), esc((ctx.get("campaign") or {}).get("pid") or ""), "true" if ctx.get("auth_required") else "false", "true" if ctx.get("logged_in") else "false",
         esc(ctx["steward"]["label"]), esc(str(ctx.get("stamp") or "")), esc(HIS_NAME), esc(str(ctx.get("health_sig") or "")), _tile_names(ctx), _rail(ctx), _masthead(ctx), _health_banner(ctx), _hdr(ctx),
         ctx.get("prefs_html") or "", board, _panel(ctx), _brand_img(ctx["build"], "gwl-m-icon.svg"), esc(ctx["build"]), esc(ctx["build"]), esc(ctx["build"]), esc(ctx["build"]))
    return page.replace('</head>', '<link rel="stylesheet" href="/static/provider-setup.css?v=%s"></head>' % esc(ctx["build"])).replace('</body>',
        '<script src="/static/provider-controls.js?v=%s"></script></body>' % esc(ctx["build"]))


try:
    import sys as _sys_mod
    import importlib as _il_mod
    for _mname in ("desk", "desk_page", "mothership_collab", "steward_cockpit.campaign_say"):
        if _mname in _sys_mod.modules:
            _il_mod.reload(_sys_mod.modules[_mname])
except Exception:
    pass

