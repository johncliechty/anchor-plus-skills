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
import json
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
    chief_of_staff_horizon_efforts,
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
    try:
        import comms_connector as _cc_rail
        _rail_accs = len((_cc_rail.load_comms_config().get("accounts") or []))
    except Exception:
        _rail_accs = 0
    _rail_comms_lbl = ("%d connected" % _rail_accs) if _rail_accs > 0 else "not connected"
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
        '<li><button data-rail="calendar"><span class="n">Calendar</span><span class="c">%s</span></button></li>'
        '<li><button data-rail="email"><span class="n">Email</span><span class="c">%s</span></button></li>'
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
         esc(ctx["week_short"]), int(ctx.get("tasks_open") or 0), n_deck, _rail_comms_lbl, _rail_comms_lbl, n_bench, cap_rows)


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
    import paths as _paths
    st = ctx["steward"]
    b = ctx["build"]
    is_admin = bool(ctx.get("admin_edition", _paths.is_anchor_admin_edition()))
    admin_links = (
        '<a class="tool" href="/gwl-admin" target="_blank" rel="noopener" title="Anchor Collaboration System Admin GUI (Review, Manual Edits, Account &amp; 2FA Resets, Shared Docs)">%sAnchor Admin</a>'
        '<a class="tool" href="/static/downloads/Anchor-Test-Onboard.zip?download=1" data-alt-href="/download/Anchor-Test-Onboard.zip?download=1" title="Download isolated Desktop Onboarding Test (Port 8787 + separate profile; never touches your working Anchor.exe)">&#129514; Test Onboard .zip</a>'
        '<a class="tool" href="/static/downloads/Anchor.zip?download=1" data-alt-href="/download/Anchor.zip?download=1" title="Download clean shareable Collaborator Anchor.exe (.zip) for Merrill &amp; collaborators">&#11015; Anchor.exe .zip</a>'
        '<a class="tool" href="/static/downloads/Anchor-Admin.zip?download=1" data-alt-href="/download/Anchor-Admin.zip?download=1" title="Download Anchor Admin.exe (.zip) with Admin &amp; Packaging controls">%sAnchor Admin.exe</a>'
        % (_brand_img(b, "anchor-admin-key.jpg"), _brand_img(b, "anchor-admin-key.png"))
    ) if is_admin else ""
    return (
        '<div class="hdr"><h2>%s</h2><span class="who">%s</span>'
        '<button class="tool doctor" data-tool="doctor">&#10010; Anchor Doctor</button>'
        '<button class="tool" data-tool="zombie">%sZombie Hunter</button>'
        '<button class="tool" data-tool="foundry">%sSkill Foundry</button>'
        '%s'
        '<div class="date">%s &middot; %s</div></div>'
    ) % (esc(st["high_seat_name"]), esc(st["label"]), _brand_img(b, "zombie-hunter-radar.jpg"),
         _brand_img(b, "skill-foundry-icon.jpg"), admin_links, esc(ctx["today_str"]), esc(ctx["week"]))


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


def _seat_move_btn(step):
    """1-click tier move button on seated Cave of Wonders cards (Active <-> On deck)."""
    if not isinstance(step, dict):
        return ""
    sid = esc(step.get("id") or "")
    st = step.get("seat")
    if not sid or st not in ("active", "deck"):
        return ""
    if st == "active":
        return '<button type="button" class="t-seat-btn" data-seat="deck" data-step="%s" data-tip="&#9662; On deck" aria-label="On deck" title="Move down to On deck"><span class="t-dot-ind blue"></span><span class="t-btn-txt">&#9662; On deck</span></button>' % sid
    return '<button type="button" class="t-seat-btn" data-seat="active" data-step="%s" data-tip="&#9652; Active" aria-label="Active" title="Elevate to Active"><span class="t-dot-ind blue"></span><span class="t-btn-txt">&#9652; Active</span></button>' % sid


def _desk_card(ctx, g, p):
    """A desk item's card (W2c): the item, its goal, its state and date; the × sends it home; it is talked through at the
    Desk — the Campaign's own cockpit in its Desk view (Grok's read of W2c: the door the Desk line already opens)."""
    if p.get("needs_you"):
        line = '<div class="t-line wait"><span class="mk">&#9873; Needs you:</span>%s</div>' % esc(p.get("waiting_on") or p.get("state") or "")
    else:
        line = '<div class="t-line"><span class="k">State</span>%s</div>' % esc(p.get("state") or p.get("status") or "planned")
    date = (' &middot; %s' % esc(_hr.due_label(p["date"], ctx["today"]))) if p.get("date") else ""
    dot = '<span class="tlight %s" title="%s"></span>' % (("orange", "needs you") if p.get("needs_you") else ("gray", "idle"))      # a desk card has a light too (Grok's read of W2e)
    s_btn = _seat_move_btn(p)
    d_btn = '<button type="button" class="t-done-btn" data-mark-done="1" data-step="%s" data-tip="&#10003; Done" aria-label="Done" title="Done for now — move off the board"><span class="t-dot-ind green"></span><span class="t-btn-txt">&#10003; Done</span></button>' % esc(p["id"])
    return (
        '<article class="tile desk%s" id="card-%s" data-step="%s" data-name="%s" draggable="true"><div class="t-top">' + dot + '<h3 class="t-name"><span class="t-nm">%s</span><span class="t-eff">at the desk%s</span></h3>'
        '%s%s<button class="t-x" data-home="%s" title="back to its goal">&times;</button></div><div class="t-goal">in <b>%s</b></div>%s'
        '<div class="t-acts"><a class="t-talk" href="/project/%s?view=desk" target="_blank" rel="noopener">talk to the desk &#8599;</a></div></article>'
    ) % (" need" if p.get("needs_you") else "", esc(p["id"]), esc(p["id"]), esc(part_name(p)), esc(part_name(p)), date, s_btn, d_btn, esc(p["id"]), esc(g["name"]), line,
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
    name = esc((step or {}).get("name") or e.get("name"))
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
    seat_btn = _seat_move_btn(step) if step else ""
    xbtn = ('<button class="t-x" data-home="%s" title="back to its goal">&times;</button>' % esc(step["id"])) if step else ""
    goal_line = ('<div class="t-goal">in <b>%s</b> &middot; %s</div>' % (esc(goal["name"]), "a cockpit within the project" if step.get("kind") == "effort" else "the project&rsquo;s cockpit")) if (goal and step) else ""
    if not f.get("has_record"):
        q_done = ('<button type="button" class="t-done-btn" data-mark-done="1" data-step="%s" data-tip="&#10003; Done" aria-label="Done" title="Done for now — move off the board"><span class="t-dot-ind green"></span><span class="t-btn-txt">&#10003; Done</span></button>' % esc(step["id"])) if step else ""
        return (
            '<article class="tile quiet%s" id="card-%s" data-tile="%s"%s><div class="t-top">%s<h3 class="t-name">%s</h3>%s%s%s</div>%s'
            '<div class="t-desc">%s</div><div class="t-quiet">no steward record yet &middot; <a class="t-open" href="/project/%s" target="_blank" rel="noopener">Open cockpit</a></div></article>'
        ) % (cls, cid, pid, attr, dot, name, seat_btn, q_done, xbtn, goal_line, esc((e.get("blurb") or "").strip()[:160]) or "&mdash;", pid)
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
    done_btn = seat_btn + (
        '<button type="button" class="t-done-btn" data-mark-done="1" data-step="%s" data-target-dir="%s" data-tip="&#10003; Done" aria-label="Done" title="Done for now — move off the board and mark current step done"><span class="t-dot-ind green"></span><span class="t-btn-txt">&#10003; Done</span></button>'
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
        '%s<a class="t-go" href="%s" data-project-href="%s" target="_blank" rel="noopener" data-tip="Open cockpit &#8599;" title="Open the cockpit"><span class="t-btn-txt">cockpit </span><span class="t-go-arr">&#8599;</span></a>%s</div><div class="t-face">%s'
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
    """Wave 9, Wave 15 & Option 1+3 (2026-11-01): Unified 2-Line Summary Tile on the Cave of Wonders
    that expands into Option 1 (50/50 Side-by-Side Split) or 1-click Full Width Calendar / Full Width Email (Mockup 3),
    with 4 Calendar views (iPhone Rolling Stream, Day, Week, Month), Smart Multi-Calendar Merging,
    Steward 2-Bucket Inbox Triage (Emails to Address vs Not Important, Seen/Downgrade/Upgrade learning),
    and 1-click Microsoft 365 + Gmail 2FA."""
    import comms_connector as _cc
    today = ctx.get("today") or date.today()
    try:
        comms = ctx.get("comms") or _cc.reconcile_comms_with_roadmaps(
            entries=ctx.get("entries") or [],
            facts=ctx.get("facts") or {},
            today=today,
        )
        p_stat = _cc.poller_status()
    except Exception:
        comms = {
            "accounts_count": 0,
            "connected_count": 0,
            "calendar_events": [],
            "calendar_events_all": [],
            "important_emails": [],
            "other_emails": [],
            "sent_emails": [],
            "email_threads": [],
            "last_sync_at": "",
        }
        p_stat = {"running": False, "interval_sec": 300}

    conn_n = int(comms.get("connected_count") or 0)
    acc_n = int(comms.get("accounts_count") or 0)
    cal_evs = comms.get("calendar_events") or []
    all_cal_evs = comms.get("calendar_events_all") or cal_evs
    imp_emails = comms.get("important_emails") or []
    oth_emails = comms.get("other_emails") or []
    acted_emails = comms.get("acted_upon_emails") or []
    sent_emails = comms.get("sent_emails") or []
    sr_state = comms.get("speed_racer") or _cc.load_speed_racer_queue()
    sr_queue = sr_state.get("queue") or []
    sr_json_boot = json.dumps(sr_state).replace("</", "<\\/")
    threads = comms.get("email_threads") or []
    last_sync = str(comms.get("last_sync_at") or "").strip()
    poller_min = max(1, int(round(int(p_stat.get("interval_sec") or 300) / 60.0)))

    state_txt = (
        "&middot; %d account%s connected (OS Vault) &middot; %d calendar &middot; %d correspondence track%s"
        % (conn_n, "" if conn_n == 1 else "s", len(all_cal_evs), len(imp_emails) or len(threads), "" if (len(imp_emails) or len(threads)) == 1 else "s")
        if acc_n > 0
        else "&middot; roadmap reconciliation active &middot; %d calendar &middot; %d correspondence track%s"
        % (len(cal_evs), len(threads), "" if len(threads) == 1 else "s")
    )
    if last_sync:
        state_txt += " &middot; synced %s" % esc(last_sync)

    # Build 2-Line Summary Tile previews for #calHead
    next_cal_bits = []
    for ev in cal_evs[:3]:
        dt_lbl = _short(ev.get("date")) or str(ev.get("date") or "")[5:]
        tm_lbl = str(ev.get("start_time") or ev.get("time_label") or "")
        m_tag = " [2 Cals]" if int(ev.get("calendar_count") or 1) > 1 else ""
        next_cal_bits.append("%s %s %s%s" % (esc(dt_lbl), esc(tm_lbl), esc(str(ev.get("title") or "")[:34]), esc(m_tag)))
    cal_line_summary = " &middot; ".join(next_cal_bits) if next_cal_bits else "No upcoming events in immediate window"
    merged_dup_count = sum(1 for e in all_cal_evs if int(e.get("calendar_count") or 1) > 1)

    top_mail_bits = []
    for em in imp_emails[:3]:
        frm_short = str(em.get("from") or "Inbox").split("<")[0].strip().strip('"')[:20]
        att_ico = " &#128206;" if em.get("has_attachments") else ""
        top_mail_bits.append("<b>%s</b>: %s%s" % (esc(frm_short), esc(str(em.get("subject") or "")[:34]), att_ico))
    if not top_mail_bits:
        for th in threads[:2]:
            top_mail_bits.append("<b>%s</b>: %s" % (esc(str(th.get("counterparty") or "Track")[:20]), esc(str(th.get("subject") or "")[:34])))
    mail_line_summary = " &middot; ".join(top_mail_bits) if top_mail_bits else "All inbox correspondence triaged"

    # Initial server-rendered Calendar rows (iPhone Rolling Stream + Roadmap Mark-Done items)
    cal_rows = []
    for ev in cal_evs[:10]:
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
            else '<span class="tw-proj">%s</span>' % esc(ev.get("calendar_badge") or ev.get("project_name") or "Calendar")
        )
        merged_pill = (
            '<span class="comms-badge amber" title="Smart-merged across multiple calendars">%s</span>'
            % esc(ev.get("merged_badge"))
            if ev.get("merged_badge")
            else ""
        )
        rsvp_st = str(ev.get("rsvp_status") or "responded")
        rsvp_lbl = esc(str(ev.get("rsvp_label") or ("✓ Responded · Attending" if rsvp_st == "responded" else "⏳ Not Responded")))
        rsvp_tone = esc(str(ev.get("rsvp_tone") or ("emerald" if rsvp_st == "responded" else "amber")))
        rsvp_pill = (
            '<button type="button" class="tw-btn comms-badge %s" data-cal-rsvp-toggle="%s" data-cal-rsvp-status="%s" data-cal-title="%s" data-cal-date="%s" '
            'style="cursor:pointer;font-weight:750" title="Click to toggle your response status (Responded / Attending vs Not Responded)">%s</button>'
            % (
                rsvp_tone,
                esc(ev.get("id") or ev.get("uid") or ""),
                esc(rsvp_st),
                esc(ev.get("title") or ""),
                esc(ev.get("date") or ""),
                rsvp_lbl,
            )
        )
        loc_html = (
            '<div class="comms-item-sub">&#128205; %s</div>' % esc(str(ev.get("location") or "")[:90])
            if ev.get("location")
            else ""
        )
        cal_rows.append(
            '<div class="comms-item %s cave-cal-card" data-cave-cal-open="%s" data-cal-title="%s" data-cal-date="%s" data-cal-start="%s" data-cal-end="%s" data-cal-loc="%s" data-cal-source="%s" data-cal-rsvp="%s" style="cursor:pointer" title="Click to open Calendar Event Dialogue Tile">'
            '<div class="comms-item-top">'
            '<span class="comms-badge %s">%s &middot; %s</span>%s%s%s%s</div>'
            '<div class="comms-item-title">%s</div>%s</div>'
            % (
                esc(ev.get("tone") or "sky"),
                esc(ev.get("id") or ev.get("uid") or ""),
                esc(ev.get("title") or ""),
                esc(ev.get("date") or ""),
                esc(ev.get("start_time") or ""),
                esc(ev.get("end_time") or ""),
                esc(ev.get("location") or ""),
                esc(ev.get("calendar_badge") or ev.get("project_name") or "Calendar"),
                esc(rsvp_st),
                esc(ev.get("tone") or "sky"),
                esc(_short(ev.get("date")) or ev.get("date") or ""),
                esc(ev.get("time_label") or ""),
                rsvp_pill,
                proj_link,
                merged_pill,
                acts,
                esc(ev.get("title") or ""),
                loc_html,
            )
        )
    cal_col_html = "".join(cal_rows) or '<div class="tw-empty">No upcoming calendar or dated delivery items in the next 14 days.</div>'

    # Initial server-rendered Steward 2-Bucket Email Triage rows
    imp_mail_rows = []
    for em in imp_emails[:30]:
        uid = esc(em.get("uid") or "")
        frm_raw = str(em.get("from") or "Inbox")
        frm_clean = esc(frm_raw.split("<")[0].strip().strip('"') or frm_raw)
        s_email = esc(em.get("sender_email") or frm_raw)
        subj = esc(em.get("subject") or "(No Subject)")
        acct_b = esc(em.get("account_badge") or "Inbox")
        score = int(em.get("steward_score") or 75)
        att_badge = '<span class="comms-badge amber">&#128206; Attachment</span>' if em.get("has_attachments") else ""
        t_cnt = int(em.get("thread_count") or 1)
        cnt_badge = ('<span class="comms-badge sky">%d msgs</span>' % t_cnt) if t_cnt > 1 else ""
        linked_ev = str(em.get("linked_calendar_event") or "").strip()
        prep_badge = (
            '<span class="comms-badge emerald" title="Steward linked this email to upcoming calendar event: %s">&#128197; Prep: %s</span>'
            % (esc(linked_ev), esc(linked_ev[:38]))
            if linked_ev
            else ""
        )
        imp_mail_rows.append(
            '<div class="comms-item amber cave-mail-card" data-mail-uid="%s" data-mail-sender="%s" data-mail-source="%s" data-mail-opened="%s" data-cave-mail-open="%s" style="cursor:pointer" title="Click to blow up Email Interaction &amp; Steward Reply Dialogue Tile">'
            '<div class="comms-item-top">'
            '<span class="comms-badge sky">%s</span>'
            '<b class="cave-mail-from" data-cave-mail-open="%s" style="cursor:pointer;color:#f8fafc">%s</b>'
            '<span class="comms-badge emerald" title="%s">&#9733; %d</span>'
            '%s%s%s'
            '<span class="comms-meta" style="text-align:right">%s</span>'
            '<span class="comms-acts">'
            '<button type="button" class="tw-btn" data-speed-racer-queue="1" data-mail-uid="%s" data-mail-sender="%s" data-mail-subject="%s" data-mail-source="%s" style="border-color:rgba(245,158,11,0.55);background:rgba(245,158,11,0.16);color:#fde68a;font-weight:700" title="Put this email into the Speed Racer Tile for rapid Steward reply &amp; approval">&#127950;&#65039; &rarr; Speed Racer</button>'
            '<button type="button" class="tw-btn" data-cave-mail-open="%s" title="Open Email Dialogue Tile (Thread History + Steward Suggested Reply)">&#128172; Open &amp; Reply</button>'
            '<button type="button" class="tw-btn" data-cave-mail-triage="seen" data-mail-uid="%s" data-mail-sender="%s" title="Tap Seen: if you have not opened this email, Steward learns it is Not Interesting and downgrades it">&#128065; Seen</button>'
            '<button type="button" class="tw-btn" data-cave-mail-triage="downgrade" data-mail-uid="%s" data-mail-sender="%s" title="Downgrade to Not Important &amp; teach Steward">&#11015; Not Interested</button>'
            '</span></div>'
            '<div class="comms-item-title" data-cave-mail-open="%s" style="cursor:pointer">%s</div>'
            '<div class="cave-mail-body" id="caveMailBody-%s" hidden style="margin-top:6px;padding-top:6px;border-top:1px dashed #283548">'
            '<div class="comms-item-sub" style="white-space:pre-wrap;color:#cbd5e1">%s</div>'
            '<div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:6px">'
            '<button type="button" class="tw-btn" data-comms-draft-reply="1" data-comms-draft-subject="%s" data-comms-draft-to="%s" data-comms-draft-project="%s" data-comms-draft-step="">&#9998; Draft Reply</button>'
            '<button type="button" class="tw-btn" data-comms-download-att="%s" data-comms-att-subject="%s">&#11015; Save Attachment Locally</button>'
            '<button type="button" class="tw-btn" data-cave-mail-triage="downgrade" data-mail-uid="%s" data-mail-sender="%s">&#11015; Downgrade / Not Interested</button>'
            '</div></div></div>'
            % (
                uid,
                s_email,
                acct_b,
                "1" if em.get("was_opened") else "0",
                uid,
                acct_b,
                uid,
                frm_clean,
                esc(em.get("steward_reason") or "Steward Priority"),
                score,
                prep_badge,
                att_badge,
                cnt_badge,
                esc(str(em.get("date") or "")[:16]),
                uid,
                s_email,
                subj,
                acct_b,
                uid,
                uid,
                s_email,
                uid,
                s_email,
                uid,
                subj,
                uid,
                esc(em.get("snippet") or "Click to read full message body from account inbox."),
                subj,
                s_email,
                acct_b,
                uid,
                subj,
                uid,
                s_email,
            )
        )
    imp_mail_html = "".join(imp_mail_rows) or '<div class="tw-empty">No unaddressed high-priority inbox emails right now.</div>'

    oth_mail_rows = []
    for em in oth_emails[:16]:
        uid = esc(em.get("uid") or "")
        frm_raw = str(em.get("from") or "Inbox")
        frm_clean = esc(frm_raw.split("<")[0].strip().strip('"') or frm_raw)
        s_email = esc(em.get("sender_email") or frm_raw)
        subj = esc(em.get("subject") or "(No Subject)")
        acct_b = esc(em.get("account_badge") or "Inbox")
        oth_mail_rows.append(
            '<div class="comms-item sky cave-mail-card" data-mail-uid="%s" data-mail-sender="%s" data-mail-source="%s" data-cave-mail-open="%s" style="opacity:0.86;cursor:pointer" title="Click to open Email Dialogue Tile">'
            '<div class="comms-item-top">'
            '<span class="comms-badge">%s</span>'
            '<span class="comms-meta"><b>%s</b> &middot; %s</span>'
            '<span class="comms-acts">'
            '<button type="button" class="tw-btn" data-speed-racer-queue="1" data-mail-uid="%s" data-mail-sender="%s" data-mail-subject="%s" data-mail-source="%s" style="border-color:rgba(245,158,11,0.45);color:#fde68a" title="Put this email into the Speed Racer Tile">&#127950;&#65039; &rarr; Speed Racer</button>'
            '<button type="button" class="tw-btn" data-cave-mail-open="%s">&#128172; Open</button>'
            '<button type="button" class="tw-btn done" data-cave-mail-triage="upgrade" data-mail-uid="%s" data-mail-sender="%s" title="Upgrade to Emails to Address &amp; teach Steward this sender is important">&#11014; Upgrade</button>'
            '</span></div>'
            '<div class="comms-item-sub">%s</div></div>'
            % (
                uid,
                s_email,
                acct_b,
                uid,
                acct_b,
                frm_clean,
                esc(em.get("steward_reason") or "Low Priority"),
                uid,
                s_email,
                subj,
                acct_b,
                uid,
                uid,
                s_email,
                subj,
            )
        )
    oth_mail_html = "".join(oth_mail_rows) or '<div class="tw-empty">No downgraded or promotional items in this bucket.</div>'

    sent_mail_rows = []
    for em in sent_emails[:25]:
        uid = esc(em.get("uid") or "")
        to_raw = str(em.get("to") or em.get("counterparty") or "Recipient")
        to_clean = esc(to_raw.split("<")[0].strip().strip('"') or to_raw)
        to_email = esc(em.get("to") or em.get("sender_email") or to_raw)
        subj = esc(em.get("subject") or "(No Subject)")
        acct_b = esc(em.get("account_badge") or "Sent")
        att_badge = '<span class="comms-badge amber">&#128206; Attachment</span>' if em.get("has_attachments") else ""
        dt_short = esc(str(em.get("date") or "")[:16])
        snip = esc(em.get("snippet") or em.get("body") or "Click to view full sent email and thread history.")
        sent_mail_rows.append(
            '<div class="comms-item emerald cave-mail-card cave-sent-card" data-mail-uid="%s" data-mail-sender="%s" data-mail-source="%s" data-mail-direction="sent" data-cave-mail-open="%s" style="cursor:pointer;border-left:3px solid #10b981" title="Click to open Sent Email &amp; Thread History">'
            '<div class="comms-item-top">'
            '<span class="comms-badge emerald">&#128228; %s</span>'
            '<b class="cave-mail-from" data-cave-mail-open="%s" style="cursor:pointer;color:#6ee7b7">To: %s</b>'
            '%s'
            '<span class="comms-meta" style="text-align:right">%s</span>'
            '<span class="comms-acts">'
            '<button type="button" class="tw-btn" data-cave-mail-open="%s" title="Open Sent Email &amp; Thread History">&#128172; View / Follow Up</button>'
            '<button type="button" class="tw-btn" data-comms-draft-reply="1" data-comms-draft-subject="%s" data-comms-draft-to="%s" data-comms-draft-project="%s" data-comms-draft-step="">&#9998; Follow-Up Draft</button>'
            '</span></div>'
            '<div class="comms-item-title" data-cave-mail-open="%s" style="cursor:pointer">%s</div>'
            '<div class="comms-item-sub" style="color:#cbd5e1">%s</div></div>'
            % (
                uid,
                to_email,
                acct_b,
                uid,
                acct_b,
                uid,
                to_clean,
                att_badge,
                dt_short,
                uid,
                subj,
                to_email,
                acct_b,
                uid,
                subj,
                snip,
            )
        )
    sent_mail_html = "".join(sent_mail_rows) or '<div class="tw-empty">No recent sent emails recorded yet &mdash; click <b>&#8635; Sync Now</b> or send a reply from any email thread.</div>'

    acted_mail_rows = []
    for em in acted_emails[:30]:
        uid = esc(em.get("uid") or "")
        frm_raw = str(em.get("from") or "Inbox")
        frm_clean = esc(frm_raw.split("<")[0].strip().strip('"') or frm_raw)
        s_email = esc(em.get("sender_email") or frm_raw)
        subj = esc(em.get("subject") or "(No Subject)")
        acct_b = esc(em.get("account_badge") or "Inbox")
        act_st = esc(em.get("acted_status") or "✓ Acted Upon")
        act_tone = esc(em.get("acted_tone") or "emerald")
        act_rsn = esc(em.get("acted_reason") or "Handled")
        dt_short = esc(str(em.get("date") or "")[:16])
        acted_mail_rows.append(
            '<div class="comms-item %s cave-mail-card cave-acted-card" data-mail-uid="%s" data-mail-sender="%s" data-mail-source="%s" data-cave-mail-open="%s" style="cursor:pointer;opacity:0.92;border-left:3px solid #38bdf8" title="Click to open Email Dialogue Tile">'
            '<div class="comms-item-top">'
            '<span class="comms-badge %s" style="font-weight:750">%s</span>'
            '<span class="comms-badge sky">%s</span>'
            '<b class="cave-mail-from" data-cave-mail-open="%s" style="cursor:pointer;color:#f8fafc">%s</b>'
            '<span class="comms-meta" style="text-align:right">%s</span>'
            '<span class="comms-acts">'
            '<button type="button" class="tw-btn" data-cave-mail-open="%s" title="Open Email Dialogue Tile">&#128172; Open</button>'
            '<button type="button" class="tw-btn" data-cave-mail-triage="unact" data-mail-uid="%s" data-mail-sender="%s" title="Move back to Active Inbox">&#8617; Back to Active Inbox</button>'
            '</span></div>'
            '<div class="comms-item-title" data-cave-mail-open="%s" style="cursor:pointer">%s</div>'
            '<div class="comms-item-sub" style="color:#94a3b8;font-size:11px">%s</div></div>'
            % (act_tone, uid, s_email, acct_b, uid, act_tone, act_st, acct_b, uid, frm_clean, dt_short, uid, uid, s_email, uid, subj, act_rsn)
        )
    acted_mail_html = "".join(acted_mail_rows) or '<div class="tw-empty">No acted-upon emails yet. Emails you reply to, mark Seen, or send to Speed Racer appear here.</div>'

    mail_rows = []
    for th in [t for t in threads if t.get("can_mark_done") or str(t.get("id") or "").startswith(("corr-", "log-"))][:4]:
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
    roadmap_corr_html = (
        '<div id="caveMailRoadmapSection" style="margin-top:8px;padding-top:8px;border-top:1px solid var(--line)">'
        '<div style="font-size:10px;font-weight:750;text-transform:uppercase;letter-spacing:.06em;color:var(--text-dim);margin-bottom:5px">'
        '&#128203; Reconciled Project Roadmap Correspondence Tracks</div>%s</div>'
        % "".join(mail_rows)
        if mail_rows
        else ""
    )

    acc_pills = []
    for a in (comms.get("accounts") or []):
        if not isinstance(a, dict):
            continue
        aid = esc(a.get("id") or "")
        albl = esc(a.get("label") or a.get("family") or "Account")
        aem = esc(a.get("email") or "Calendar ICS")
        astat = str(a.get("status") or "configured").strip().lower()
        afam = str(a.get("family") or "gmail").strip().lower()
        note_tip = esc(str(a.get("last_imap_note") or a.get("last_ics_note") or "")[:180])
        if astat == "paused_safety":
            acc_pills.append(
                '<span class="comms-pill amber" title="%s" style="display:inline-flex;align-items:center;gap:6px;border:1px solid rgba(56,189,248,0.55);background:rgba(56,189,248,0.12);color:#bae6fd">'
                '&#128737; %s (%s) &middot; <span style="font-size:10.5px;opacity:0.95">Paused for PSU Safety</span> '
                '<button type="button" class="mini" data-comms-ms-device-auth="%s" data-comms-ms-email="%s" data-comms-ms-label="%s" '
                'title="Sign in safely with your new PSU password + Duo 2FA in browser (never sends raw password over IMAP)" '
                'style="border-color:#fbbf24;color:#fde68a;background:rgba(245,158,11,0.18);padding:1px 8px;font-size:11px;font-weight:700">'
                '&#128273; Sign In with Microsoft 365 (Duo 2FA)</button> '
                '<button type="button" class="mini" data-comms-auto-outlook="1" '
                'title="Or read calendar &amp; inbox from your signed-in Windows Desktop Outlook app" '
                'style="border-color:#38bdf8;color:#7dd3fc;background:rgba(56,189,248,0.14);padding:1px 7px;font-size:11px;font-weight:700">'
                '&#128187; Local Outlook</button> '
                '<button type="button" class="mini" data-comms-remove-id="%s" title="Remove this account" style="padding:0 5px;font-size:11px;line-height:1.2">&times;</button>'
                '</span>' % (note_tip, albl, aem, aid, aem, albl, aid)
            )
        elif astat == "auth_error":
            if afam == "outlook":
                fix_btn = (
                    '<button type="button" class="mini" data-comms-ms-device-auth="%s" data-comms-ms-email="%s" data-comms-ms-label="%s" '
                    'title="Sign in with Microsoft 365 + 2FA (Duo / Authenticator) using Device Code" '
                    'style="border-color:#fbbf24;color:#fde68a;background:rgba(245,158,11,0.15);padding:1px 7px;font-size:11px;font-weight:700">'
                    '&#128273; Sign In with Microsoft 365 (2FA)</button>'
                    % (aid, aem, albl)
                )
            else:
                fix_btn = (
                    '<button type="button" class="mini" data-comms-gmail-2fa="%s" data-comms-edit-account="%s" data-comms-edit-email="%s" data-comms-edit-label="%s" data-comms-edit-family="%s" '
                    'title="Uses your stored OS Vault password to trigger the Google 2FA prompt on your phone (no password typing needed)" '
                    'style="border-color:#38bdf8;color:#7dd3fc;background:rgba(56,189,248,0.15);padding:1px 7px;font-size:11px;font-weight:700">'
                    '&#128273; Authenticate 2FA (Phone Prompt)</button>'
                    % (aid, aid, aem, albl, esc(afam))
                )
            acc_pills.append(
                '<span class="comms-pill amber" title="%s" style="display:inline-flex;align-items:center;gap:6px;border:1px solid rgba(245,158,11,0.5);background:rgba(245,158,11,0.1);color:#fde68a">'
                '&#9888; %s (%s) &middot; <span style="font-size:10.5px;opacity:0.9">Needs Sign-In / 2FA</span> %s '
                '<button type="button" class="mini" data-comms-remove-id="%s" title="Remove this account" style="padding:0 5px;font-size:11px;line-height:1.2">&times;</button>'
                '</span>' % (note_tip, albl, aem, fix_btn, aid)
            )
        else:
            acc_pills.append(
                '<span class="comms-pill emerald" title="%s" style="display:inline-flex;align-items:center;gap:6px">'
                '&#10003; %s (%s) '
                '<button type="button" class="mini" data-comms-edit-account="%s" data-comms-edit-email="%s" data-comms-edit-label="%s" data-comms-edit-family="%s" '
                'title="Open box to change/update password for %s" '
                'style="border-color:#94a3b8;color:#e2e8f0;background:rgba(148,163,184,0.14);padding:1px 7px;font-size:11px;font-weight:650">'
                '&#9999;&#65039; Change Password</button> '
                '<button type="button" class="mini" data-comms-remove-id="%s" title="Disconnect this account" style="padding:0 5px;font-size:11px;line-height:1.2">&times;</button>'
                '</span>' % (note_tip, albl, aem, aid, aem, albl, esc(afam), aem, aid)
            )
    acc_bar_html = (
        '<div style="display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin:2px 0 6px" id="caveConnectedAccountsBar">%s</div>'
        % "".join(acc_pills)
        if acc_pills
        else ""
    )

    # Build Calendar-Driven Upcoming Prep Radar (links today/upcoming classes & meetings to their preparation emails)
    prep_cards = []
    for p in (comms.get("upcoming_prep_items") or [])[:4]:
        if not isinstance(p, dict):
            continue
        rel_ems = p.get("related_emails") or []
        if not rel_ems and str(p.get("date") or "") != today.isoformat():
            continue
        ev_id = esc(str(p.get("event_id") or ""))
        ev_title = esc(str(p.get("title") or "Event"))
        ev_dt = esc(str(p.get("date") or ""))
        ev_dt_short = esc(_short(p.get("date")) or str(p.get("date") or ""))
        ev_tm = esc(str(p.get("time_label") or p.get("start_time") or ""))
        ev_st = esc(str(p.get("start_time") or "09:00"))
        ev_et = esc(str(p.get("end_time") or "10:00"))
        ev_src = esc(str(p.get("calendar_badge") or "Calendar"))
        p_rsvp_st = str(p.get("rsvp_status") or "responded")
        p_rsvp_lbl = esc(str(p.get("rsvp_label") or ("✓ Responded" if p_rsvp_st == "responded" else "⏳ Not Responded")))
        p_rsvp_tone = "emerald" if p_rsvp_st == "responded" else "amber"
        rsvp_prep_badge = ' <span class="comms-badge %s" style="font-size:9.5px;font-weight:750">%s</span>' % (p_rsvp_tone, p_rsvp_lbl)
        m_badge = rsvp_prep_badge + ((' <span class="comms-badge amber" style="font-size:9.5px">%s</span>' % esc(str(p.get("merged_badge")))) if p.get("merged_badge") else "")
        em_chips = []
        for rem in rel_ems[:2]:
            r_uid = esc(str(rem.get("uid") or ""))
            r_from = esc(str(rem.get("from") or "Inbox").split("<")[0].strip().strip('"')[:22])
            r_subj = esc(str(rem.get("subject") or "")[:40])
            r_snip = esc(str(rem.get("snippet") or "")[:95])
            em_chips.append(
                '<button type="button" class="mini" data-cave-mail-open="%s" title="%s" '
                'style="display:inline-flex;align-items:center;gap:5px;border-color:#fbbf24;background:rgba(245,158,11,0.14);color:#fde68a;font-size:11px;padding:3px 8px;text-align:left">'
                '&#9993; <b>%s</b>: %s</button>' % (r_uid, r_snip, r_from, r_subj)
            )
        em_chips_html = (
            '<div style="display:flex;flex-wrap:wrap;gap:5px;margin-top:5px">%s</div>' % "".join(em_chips)
            if em_chips
            else '<div style="font-size:10.5px;color:#94a3b8;margin-top:3px">Click event to inspect agenda or attach notes</div>'
        )
        prep_cards.append(
            '<div class="cave-prep-card" data-cal-source="%s" style="flex:1 1 250px;padding:7px 10px;border-radius:8px;border:1px solid rgba(56,189,248,0.38);background:rgba(15,23,42,0.85)">'
            '<div style="display:flex;align-items:center;justify-content:space-between;gap:6px;flex-wrap:wrap;cursor:pointer" '
            'data-cave-cal-open="%s" data-cal-title="%s" data-cal-date="%s" data-cal-start="%s" data-cal-end="%s" data-cal-loc="" data-cal-source="%s">'
            '<span class="comms-badge sky">&#128197; %s &middot; %s</span>'
            '<span style="font-size:10px;color:#7dd3fc">%s%s</span>'
            '</div>'
            '<div style="font-weight:750;font-size:12px;color:#f8fafc;margin-top:4px;cursor:pointer" '
            'data-cave-cal-open="%s" data-cal-title="%s" data-cal-date="%s" data-cal-start="%s" data-cal-end="%s" data-cal-loc="" data-cal-source="%s">%s</div>'
            '%s</div>'
            % (
                ev_src,
                ev_id, ev_title, ev_dt, ev_st, ev_et, ev_src,
                ev_dt_short, ev_tm,
                ev_src, m_badge,
                ev_id, ev_title, ev_dt, ev_st, ev_et, ev_src, ev_title,
                em_chips_html,
            )
        )
    upcoming_prep_html = (
        '<div id="caveUpcomingPrepStrip" style="margin:6px 0 8px;padding:8px 10px;border-radius:9px;border:1px solid rgba(245,158,11,0.4);background:linear-gradient(90deg,rgba(245,158,11,0.09),rgba(56,189,248,0.07))">'
        '<div style="display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:6px;flex-wrap:wrap">'
        '<span style="font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:.05em;color:#fbbf24">'
        '&#9889; Upcoming Calendar Prep &amp; Linked Emails (What&#39;s Driving Your Day Now)</span>'
        '<span style="font-size:10.5px;color:#94a3b8">Click an event or linked email chip to open its interaction tile</span>'
        '</div>'
        '<div style="display:flex;flex-wrap:wrap;gap:8px">%s</div></div>' % "".join(prep_cards)
        if prep_cards
        else ""
    )

    conn_note = (
        '<p class="conn-zero">Connected to %d account%s via Windows OS Credential Vault (<code>advapi32</code>) &mdash; auto-syncing every %d minutes.</p>'
        % (acc_n, "" if acc_n == 1 else "s", poller_min)
        if acc_n > 0
        else '<p class="conn-zero">No external IMAP/ICS account is connected yet, so nothing here is sample data &mdash; items above are reconciled directly from your project roadmaps.</p>'
    )

    return (
        '<section class="cal" id="cal" data-comms-pulse="1" data-connected-count="%d">'
        '<div class="cal-h cal-two-line" id="calHead">'
        '<span class="sr" id="commsStateBadge">%s</span>'
        '<div class="cal-2line-rows">'
        '<div class="cal-sline" id="tabCal" data-cal-tab="cal" data-comms-layout="cal" title="Click to open Calendar Full Width (or use Split 50/50 on the right)">'
        '<span class="cal-stag sky">&#128197; Calendar (%d)</span>'
        '<span class="comms-pill sky" style="padding:1px 7px;font-size:10px">%d Merged%s</span>'
        '<span class="cal-sprimary" id="caveCalLineSummary">%s</span>'
        '<span class="sp"></span>'
        '<span class="cal-sfull-chip" data-comms-layout="cal">&#10530; Full Calendar</span>'
        '</div>'
        '<div class="cal-sline" id="tabMail" data-cal-tab="mail" data-comms-layout="mail" title="Click to open Email Triage &amp; Speed Racer Full Width (or use Split 50/50 on the right)">'
        '<span class="cal-stag amber">&#9993; Inbox, Speed Racer &amp; Sent</span>'
        '<span class="comms-pill amber" data-cave-open-speed-racer="1" style="padding:1px 7px;font-size:10px;cursor:pointer;border-color:#f59e0b;background:rgba(245,158,11,0.22);color:#fef08a" title="Click to open Speed Racer Rapid Email Review &amp; Approval Tile">&#127950;&#65039; Speed Racer (<span id="caveHdrSrCount">%d</span>)</span>'
        '<span class="comms-pill amber" style="padding:1px 7px;font-size:10px">&#9889; %d to Address</span>'
        '<span class="comms-pill emerald" data-cave-open-sent="1" style="padding:1px 7px;font-size:10px;cursor:pointer" title="Click to view Sent Emails">&#128228; %d Sent</span>'
        '<span class="comms-pill" style="padding:1px 7px;font-size:10px">&#128229; %d Not Important</span>'
        '<span class="cal-sprimary" id="caveMailLineSummary">%s</span>'
        '<span class="sp"></span>'
        '<span class="cal-sfull-chip" data-comms-layout="mail">&#10530; Full Email</span>'
        '</div>'
        '</div>'
        '<div class="cal-head-actions">'
        '<button type="button" class="cal-tab on" data-comms-layout="split" title="Expand Side-by-Side 50/50 Split View (Option 1)">&#9707; Split 50/50</button>'
        '<button type="button" class="tog" id="calTog">Expand</button>'
        '</div>'
        '</div>'
        '<div class="cal-body" id="calBody">'
        '<!-- Row 1: Connected Account Tiles + Collapsed Setup Material Drawer -->'
        '<div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-bottom:4px">'
        '%s'
        '<details id="caveCommsSetupDrawer"%s style="margin-left:auto">'
        '<summary class="mini" style="cursor:pointer;list-style:none;border:1px solid #334155;border-radius:6px;padding:3px 9px;background:#0f172a;color:#94a3b8;font-size:11px;font-weight:600">'
        '&#9881; Setup Material &amp; Account Connections &#9662;</summary>'
        '<div style="margin-top:6px;padding:10px 12px;border-radius:9px;border:1px solid #283548;background:#0b1120;display:flex;flex-wrap:wrap;gap:6px;align-items:center">'
        '<span class="comms-pill emerald">&#9679; OS Vault (advapi32)</span>'
        '<button type="button" class="mini comms-sync-btn" id="btnCaveCommsQuickConnect" data-open-comms-connect="1" style="border-color:#10b981;color:#6ee7b7;font-weight:700">+ Connect Gmail / Google Calendar / Outlook</button>'
        '<button type="button" class="mini comms-sync-btn" id="btnCaveCommsAutoOutlook" data-comms-auto-outlook="1" title="Auto-connect local Windows Desktop Outlook via MAPI COM (no OAuth tokens needed)" style="border-color:#38bdf8;color:#7dd3fc;font-weight:700">&#128187; Auto-Connect Local Desktop Outlook</button>'
        '<button type="button" class="mini comms-sync-btn" id="btnCaveCommsMs2FAQuick" data-comms-ms-device-auth="" title="Sign in to Microsoft 365 / Outlook with 2FA (Duo / Authenticator)" style="border-color:#a78bfa;color:#c4b5fd;font-weight:700">&#128273; Microsoft 365 + 2FA Sign-In</button>'
        '<a class="mini comms-setup-btn" id="btnCaveCommsMockups" href="/comms-mockups" target="_blank" rel="noopener" style="border-color:#38bdf8;color:#7dd3fc;font-weight:600">&#127912; Compare 4 Display Mockups &#8599;</a>'
        '<a class="mini comms-setup-btn" id="btnCaveCommsSetup" href="/setup?section=comms" data-open-href="/setup?section=comms">&#9881; Calendar &amp; Email Setup</a>'
        '</div>'
        '</details>'
        '</div>'
        '<!-- Row 2: Source Subset Checkmarks & Sync Bar right below Account Tiles and right above Calendar & Email -->'
        '<div class="comms-toolbar" id="caveCommsPulse" style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;padding:6px 10px;margin:4px 0 8px;border-radius:8px;border:1px solid #283548;background:#0d1424">'
        '<div class="cave-source-filter-bar" id="caveSourceFilterBar" style="display:inline-flex;align-items:center;flex-wrap:wrap;gap:8px">'
        '<span style="font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:.04em;color:#cbd5e1">&#128269; Show Sources:</span>'
        '<label class="cave-src-chk" style="display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border-radius:6px;border:1px solid rgba(245,158,11,0.45);background:rgba(245,158,11,0.1);font-size:11.5px;font-weight:700;color:#fde68a;cursor:pointer" title="Show/hide Primary Gmail &amp; Google Calendar items"><input type="checkbox" data-comms-source-filter="gmail" checked style="accent-color:#f59e0b;cursor:pointer"> Google (Gmail + Cal)</label>'
        '<label class="cave-src-chk" style="display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border-radius:6px;border:1px solid rgba(56,189,248,0.45);background:rgba(56,189,248,0.1);font-size:11.5px;font-weight:700;color:#7dd3fc;cursor:pointer" title="Show/hide Penn State 365 emails &amp; calendar items"><input type="checkbox" data-comms-source-filter="psu" checked style="accent-color:#38bdf8;cursor:pointer"> Penn State (PSU 365)</label>'
        '<label class="cave-src-chk" style="display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border-radius:6px;border:1px solid rgba(16,185,129,0.45);background:rgba(16,185,129,0.1);font-size:11.5px;font-weight:700;color:#6ee7b7;cursor:pointer" title="Show/hide Axmra 365 emails &amp; calendar items"><input type="checkbox" data-comms-source-filter="axmra" checked style="accent-color:#10b981;cursor:pointer"> Axmra 365</label>'
        '<button type="button" class="mini" data-comms-source-all="1" style="padding:2px 7px;font-size:10.5px;font-weight:700" title="Check all sources">Show All</button>'
        '</div>'
        '<div style="display:inline-flex;align-items:center;flex-wrap:wrap;gap:6px">'
        '<span class="comms-pill sky" id="commsPollerPill" title="Background poller syncs all accounts every 5 minutes">&#8635; Auto-Sync (%dm)</span>'
        '<button type="button" class="mini comms-sync-btn" id="btnCaveCommsSync" data-comms-sync="1" style="font-weight:700">&#8635; Sync Now</button>'
        '<div class="comms-layout-switch" id="commsLayoutBar" style="display:inline-flex;gap:4px;margin-left:2px">'
        '<button type="button" class="mini on" data-comms-layout="split" title="Split 50/50 (Option 1)" style="font-weight:700">&#9707; Split 50/50</button>'
        '<button type="button" class="mini" data-comms-layout="cal" title="Full Calendar 100%% (Mockup 3)" style="font-weight:700">&#128197; Full Calendar</button>'
        '<button type="button" class="mini" data-comms-layout="mail" title="Full Email 100%% (Mockup 3)" style="font-weight:700">&#9993; Full Email</button>'
        '</div>'
        '</div>'
        '</div>'
        '%s'
        '<div id="caveCommsDeviceFlowBox" hidden style="margin:8px 0;padding:12px 14px;border:1px solid rgba(167,139,250,0.65);border-radius:10px;background:#131b2e;color:#e6edf3"></div>'
        '<div class="comms-connect-modal" id="caveCommsConnectModal"%s style="margin:8px 0;padding:14px;border:1px solid rgba(16,185,129,0.45);border-radius:10px;background:#0f172a">'
        '<div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-bottom:10px">'
        '<div><b style="color:#6ee7b7;font-size:13.5px">&#128279; Quick-Connect Gmail, Google Calendar &amp; Microsoft Outlook (Multiple Accounts Supported)</b>'
        '<div style="font-size:11.5px;color:#94a3b8;margin-top:2px">Credentials are stored in your Windows OS Credential Vault (<code>advapi32</code>) &mdash; never in JSON files. Spaces in 16-letter App Passwords are stripped automatically.</div></div>'
        '<div style="display:flex;gap:6px;flex-wrap:wrap">'
        '<button type="button" class="mini" data-cave-comms-preset="gmail" style="border-color:#38bdf8;color:#38bdf8">&#128231; Gmail + Google Calendar</button>'
        '<button type="button" class="mini" data-cave-comms-preset="outlook" style="border-color:#a78bfa;color:#c4b5fd">&#128197; Microsoft 365 / Outlook</button>'
        '<button type="button" class="mini" data-cave-comms-preset="ics_only" style="border-color:#fbbf24;color:#fde68a">&#128198; Calendar ICS Link Only (No Password)</button>'
        '<button type="button" class="mini" id="btnCaveCommsConnectClose">&times; Hide</button>'
        '</div></div>'
        '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:8px;margin-bottom:10px">'
        '<div><label style="display:block;font-size:11px;color:#94a3b8;margin-bottom:3px">Provider</label>'
        '<select id="caveCommsFamily" style="width:100%%;padding:6px 8px;border-radius:6px;border:1px solid #2b3546;background:#0d1117;color:#e6edf3">'
        '<option value="gmail">Google / Gmail + Google Calendar</option>'
        '<option value="outlook">Microsoft 365 / Outlook + Calendar</option>'
        '<option value="custom">Custom / Institutional IMAP + ICS</option>'
        '</select></div>'
        '<div><label style="display:block;font-size:11px;color:#94a3b8;margin-bottom:3px">Account Nickname (add as many as you like)</label>'
        '<input type="text" id="caveCommsLabel" value="Primary Gmail &amp; Calendar" placeholder="e.g. Work Gmail, Personal Gmail, PSU Outlook" style="width:100%%;box-sizing:border-box;padding:6px 8px;border-radius:6px;border:1px solid #2b3546;background:#0d1117;color:#e6edf3"></div>'
        '<div><label style="display:block;font-size:11px;color:#94a3b8;margin-bottom:3px">Email Address</label>'
        '<input type="email" id="caveCommsEmail" placeholder="you@example.com or you@example.org" autocomplete="off" style="width:100%%;box-sizing:border-box;padding:6px 8px;border-radius:6px;border:1px solid #2b3546;background:#0d1117;color:#e6edf3"></div>'
        '<div><label style="display:block;font-size:11px;color:#94a3b8;margin-bottom:3px">Auth Mode</label>'
        '<select id="caveCommsAuthMode" style="width:100%%;padding:6px 8px;border-radius:6px;border:1px solid #2b3546;background:#0d1117;color:#e6edf3">'
        '<option value="app_password">16-Char App Password (Recommended)</option>'
        '<option value="oauth_token">OAuth2 Token</option>'
        '<option value="ics_only">Calendar ICS Link Only (No Password)</option>'
        '</select></div>'
        '</div>'
        '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:8px;margin-bottom:10px">'
        '<div><div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:3px">'
        '<label style="font-size:11px;color:#94a3b8">App Password / OAuth Token (spaces stripped automatically)</label>'
        '<span style="display:inline-flex;gap:8px;font-size:11px">'
        '<a href="https://myaccount.google.com/apppasswords" target="_blank" rel="noopener" style="color:#38bdf8;text-decoration:none" title="Open Google Account App Passwords page in browser">&#128273; Get Google App Password &#8599;</a>'
        '<a href="https://account.live.com/proofs/AppPassword" target="_blank" rel="noopener" style="color:#c4b5fd;text-decoration:none" title="Open Microsoft App Password page">&#128273; Microsoft App Password &#8599;</a>'
        '</span></div>'
        '<input type="password" id="caveCommsSecret" placeholder="Paste 16-char Google/Outlook App Password (e.g. xxxx xxxx xxxx xxxx)" autocomplete="off" style="width:100%%;box-sizing:border-box;padding:6px 8px;border-radius:6px;border:1px solid #2b3546;background:#0d1117;color:#e6edf3"></div>'
        '<div><div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:3px">'
        '<label style="font-size:11px;color:#94a3b8">Calendar Secret ICS URL (Google Calendar or Outlook ICS)</label>'
        '<span style="display:inline-flex;gap:8px;font-size:11px">'
        '<a href="https://calendar.google.com/calendar/u/0/r/settings" target="_blank" rel="noopener" style="color:#38bdf8;text-decoration:none" title="Settings for my calendars -> Integrate calendar -> Secret address in iCal format">&#128197; Google Calendar ICS Settings &#8599;</a>'
        '<a href="https://outlook.office.com/calendar" target="_blank" rel="noopener" style="color:#c4b5fd;text-decoration:none" title="Publish a calendar -> Copy ICS link">&#128197; Outlook Calendar ICS &#8599;</a>'
        '</span></div>'
        '<input type="text" id="caveCommsIcsUrl" placeholder="https://calendar.google.com/calendar/ical/.../basic.ics (or Outlook .ics URL)" autocomplete="off" style="width:100%%;box-sizing:border-box;padding:6px 8px;border-radius:6px;border:1px solid #2b3546;background:#0d1117;color:#e6edf3"></div>'
        '</div>'
        '<div style="display:flex;align-items:center;flex-wrap:wrap;gap:8px">'
        '<button type="button" class="mini comms-sync-btn" id="btnCaveCommsSaveAccount" style="border-color:#10b981;color:#6ee7b7;font-weight:700">&#128190; Save to OS Vault, Test &amp; Sync</button>'
        '<button type="button" class="mini" id="btnCaveCommsMsDeviceAuth" data-comms-ms-device-auth="" style="border-color:#a78bfa;color:#c4b5fd;font-weight:700">&#128273; Sign In with Microsoft 365 + 2FA (Device Code)</button>'
        '<button type="button" class="mini" id="btnCaveCommsOauthPkce" data-cave-comms-oauth="1">&#128273; Start OAuth2 Browser Sign-In</button>'
        '<button type="button" class="mini" data-comms-auto-outlook="1">&#9889; 1-Click Connect Running Windows Outlook</button>'
        '<span id="caveCommsConnectStatus" style="font-size:12px;color:#94a3b8"></span>'
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
        '<!-- Interactive Blow-Up Dialogue Tile for Email Thread + Steward Reply OR Calendar Event + Multi-Cal Sync -->'
        '<div id="caveCommsDialogueTile" hidden style="margin:10px 0 12px;padding:14px 16px;border:2px solid #38bdf8;border-radius:12px;background:linear-gradient(180deg,#0f172a 0%%,#0b1120 100%%);box-shadow:0 12px 32px rgba(0,0,0,0.55)">'
        '  <!-- EMAIL DIALOGUE PANE -->'
        '  <div id="caveEmailDialoguePane" hidden>'
        '    <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:10px;flex-wrap:wrap;padding-bottom:10px;border-bottom:1px solid #283548">'
        '      <div>'
        '        <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">'
        '          <span class="comms-badge sky" id="caveDlgMailBadge">PSU 365</span>'
        '          <b id="caveDlgMailSubject" style="font-size:14.5px;color:#f8fafc">Email Subject</b>'
        '        </div>'
        '        <div id="caveDlgMailMeta" style="font-size:11.5px;color:#94a3b8;margin-top:3px">From: &mdash;</div>'
        '      </div>'
        '      <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">'
        '        <button type="button" class="mini" id="btnCaveDlgSeen" style="border-color:#38bdf8;background:rgba(56,189,248,0.18);color:#7dd3fc;font-weight:800" title="Mark as Seen (no response needed right now) and move out of Active Inbox into Acted Upon">&#128065; Seen (&rarr; Acted Upon)</button>'
        '        <button type="button" class="mini" id="btnCaveDlgToSpeedRacer" style="border-color:#f59e0b;background:rgba(245,158,11,0.22);color:#fef08a;font-weight:800" title="Have the Steward craft a response in Speed Racer and move this email out of Active Inbox into Acted Upon">&#127950;&#65039; Speed Racer (Craft Response)</button>'
        '        <button type="button" class="mini" id="btnCaveDlgAlreadyReplied" style="border-color:#10b981;background:rgba(16,185,129,0.16);color:#6ee7b7;font-weight:750" title="Tell Steward you already answered this email — removes any draft and moves to Acted Upon">&#10003; Already Replied</button>'
        '        <button type="button" class="mini" id="btnCaveDlgDownloadAtt" hidden style="border-color:#38bdf8;color:#7dd3fc">&#11015; Save Attachments</button>'
        '        <button type="button" class="mini" id="btnCaveDlgDowngrade" title="Downgrade to Not Important &amp; teach Steward">&#11015; Not Interested</button>'
        '        <button type="button" class="mini" id="btnCaveDlgUpgrade" title="Promote to Emails to Address">&#11014; Upgrade</button>'
        '        <button type="button" class="mini" data-cave-dlg-close="1" style="border-color:#f43f5e;color:#fda4af;font-weight:700">&times; Close</button>'
        '      </div>'
        '    </div>'
        '    <!-- Steward Directions Bar for Open Email (Giving instructions moves email from Active Inbox -> Acted Upon & queues in Speed Racer) -->'
        '    <div id="caveDlgStewardDirectionsBar" style="margin-top:10px;padding:8px 11px;border-radius:8px;border:1px solid rgba(245,158,11,0.45);background:rgba(245,158,11,0.09);display:flex;align-items:center;gap:8px;flex-wrap:wrap">'
        '      <span style="font-size:11px;font-weight:800;color:#fef08a">&#127950;&#65039; Give Steward Directions for This Email:</span>'
        '      <input type="text" id="caveDlgStewardDirectionsInput" placeholder="e.g. Confirm Wednesday 3-5 PM proctoring and ask Hollie to assign 2 TAs (then move out of Active Inbox)..." style="flex:1;min-width:240px;padding:5px 9px;border-radius:6px;border:1px solid #334155;background:#070b12;color:#f8fafc;font-size:11.5px">'
        '      <button type="button" class="tw-btn" id="btnCaveDlgSendDirectionsToSr" style="border-color:#f59e0b;background:rgba(245,158,11,0.24);color:#fef08a;font-weight:800;padding:4px 10px" title="Steward crafts response per your directions in Speed Racer and moves this email to Acted Upon">&#127950;&#65039; Send Directions &rarr; Speed Racer (&amp; Move to Acted Upon)</button>'
        '    </div>'
        '    <!-- Clickable Attachments Bar + Inline Attachment Viewer inside Expanded Email Tile -->'
        '    <div id="caveDlgAttachmentsBar" hidden style="margin-top:8px;padding:7px 10px;border-radius:8px;border:1px solid rgba(56,189,248,0.4);background:rgba(15,23,42,0.9);display:flex;align-items:center;gap:6px;flex-wrap:wrap"></div>'
        '    <div id="caveDlgAttachmentPreviewHost" hidden style="margin-top:8px;padding:10px;border-radius:8px;border:1px solid #38bdf8;background:#070b12"></div>'
        '    <div style="display:grid;grid-template-columns:1.05fr 1fr;gap:14px;margin-top:12px" class="cave-dlg-split">'
        '      <!-- Left: Conversation & Past Messages History -->'
        '      <div style="background:#090d16;border:1px solid #283548;border-radius:10px;padding:10px 12px;max-height:420px;overflow-y:auto">'
        '        <div style="font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:.05em;color:#7dd3fc;margin-bottom:8px">&#128172; Interaction &amp; Past Messages / Responses</div>'
        '        <div id="caveDialogueThreadList" style="display:flex;flex-direction:column;gap:8px"></div>'
        '      </div>'
        '      <!-- Right: Steward Suggested Draft Generator + Editable Reply & Send -->'
        '      <div style="background:#111827;border:1px solid #283548;border-radius:10px;padding:10px 12px;display:flex;flex-direction:column;gap:8px">'
        '        <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:6px">'
        '          <span style="font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:.05em;color:#6ee7b7">&#10024; Steward Suggested Response &amp; Direct Reply</span>'
        '          <span id="caveDlgStewardNote" style="font-size:10.5px;color:#a78bfa">Ready to draft or edit</span>'
        '        </div>'
        '        <div style="display:flex;flex-wrap:wrap;gap:5px">'
        '          <button type="button" class="tw-btn done" data-steward-draft-intent="default">&#10024; Steward Draft</button>'
        '          <button type="button" class="tw-btn" data-steward-draft-intent="confirm">&#10003; Confirm / Approve</button>'
        '          <button type="button" class="tw-btn" data-steward-draft-intent="meeting">&#128197; Propose Free Calendar Times</button>'
        '          <button type="button" class="tw-btn" data-steward-draft-intent="details">&#128203; Ask for Details / Docs</button>'
        '        </div>'
        '        <div style="display:flex;gap:6px">'
        '          <input type="text" id="caveStewardCustomPrompt" placeholder="Or tell Steward what to say (e.g. Excuse absence and wish the team luck)..." style="flex:1;padding:5px 8px;border-radius:6px;border:1px solid #283548;background:#0b0f17;color:#f1f5f9;font-size:11.5px">'
        '          <button type="button" class="mini" id="btnCaveStewardCustomDraft" style="border-color:#a78bfa;color:#c4b5fd;font-weight:700">&#10024; Draft</button>'
        '        </div>'
        '        <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px">'
        '          <div><label style="font-size:10px;color:#94a3b8;display:block">To</label><input type="text" id="caveReplyTo" style="width:100%%;box-sizing:border-box;padding:5px 7px;border-radius:6px;border:1px solid #283548;background:#0b0f17;color:#f1f5f9;font-size:11.5px"></div>'
        '          <div><label style="font-size:10px;color:#94a3b8;display:block">Cc (optional)</label><input type="text" id="caveReplyCc" placeholder="cc@example.org" style="width:100%%;box-sizing:border-box;padding:5px 7px;border-radius:6px;border:1px solid #283548;background:#0b0f17;color:#f1f5f9;font-size:11.5px"></div>'
        '        </div>'
        '        <div><label style="font-size:10px;color:#94a3b8;display:block">Subject</label><input type="text" id="caveReplySubject" style="width:100%%;box-sizing:border-box;padding:5px 7px;border-radius:6px;border:1px solid #283548;background:#0b0f17;color:#f1f5f9;font-size:11.5px"></div>'
        '        <textarea id="caveReplyBody" rows="7" placeholder="Steward suggested response appears here — edit freely before sending..." style="width:100%%;box-sizing:border-box;padding:8px;border-radius:7px;border:1px solid #3b4f6b;background:#0b0f17;color:#f8fafc;font-size:12px;line-height:1.45"></textarea>'
        '        <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px">'
        '          <div style="display:flex;gap:6px;flex-wrap:wrap">'
        '            <button type="button" class="mini comms-sync-btn" id="btnCaveSendReplyNow" style="border-color:#10b981;background:rgba(16,185,129,0.18);color:#6ee7b7;font-weight:800">&#128228; Send Reply Now</button>'
        '            <button type="button" class="mini" id="btnCaveSaveReplyDraft">&#128190; Save Draft (.eml)</button>'
        '          </div>'
        '          <span id="caveReplyStatusMsg" style="font-size:11.5px;color:#94a3b8"></span>'
        '        </div>'
        '      </div>'
        '    </div>'
        '  </div>'
        '  <!-- CALENDAR EVENT DIALOGUE PANE (Inspect / Edit / Add Event & Sync Back to Selected Calendars) -->'
        '  <div id="caveCalDialoguePane" hidden>'
        '    <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;padding-bottom:10px;border-bottom:1px solid #283548">'
        '      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">'
        '        <span class="comms-badge emerald" id="caveDlgCalModeBadge">&#128197; Calendar Event</span>'
        '        <b id="caveDlgCalHeaderTitle" style="font-size:14.5px;color:#f8fafc">Event Details &amp; Multi-Calendar Sync</b>'
        '      </div>'
        '      <button type="button" class="mini" data-cave-dlg-close="1" style="border-color:#f43f5e;color:#fda4af;font-weight:700">&times; Close Dialogue</button>'
        '    </div>'
        '    <div style="display:grid;grid-template-columns:1.1fr 0.9fr;gap:14px;margin-top:12px" class="cave-dlg-split">'
        '      <div style="background:#111827;border:1px solid #283548;border-radius:10px;padding:12px;display:flex;flex-direction:column;gap:8px">'
        '        <div><label style="font-size:10.5px;color:#94a3b8;display:block;margin-bottom:2px">Event Title</label><input type="text" id="caveCalEvTitle" placeholder="e.g. Research Sync / LP Transfer Review" style="width:100%%;box-sizing:border-box;padding:6px 8px;border-radius:6px;border:1px solid #3b4f6b;background:#0b0f17;color:#f8fafc;font-weight:700"></div>'
        '        <div style="display:grid;grid-template-columns:1.2fr 1fr 1fr;gap:8px">'
        '          <div><label style="font-size:10.5px;color:#94a3b8;display:block;margin-bottom:2px">Date (YYYY-MM-DD)</label><input type="date" id="caveCalEvDate" style="width:100%%;box-sizing:border-box;padding:5px 7px;border-radius:6px;border:1px solid #283548;background:#0b0f17;color:#f1f5f9"></div>'
        '          <div><label style="font-size:10.5px;color:#94a3b8;display:block;margin-bottom:2px">Start Time</label><input type="time" id="caveCalEvStart" value="10:00" style="width:100%%;box-sizing:border-box;padding:5px 7px;border-radius:6px;border:1px solid #283548;background:#0b0f17;color:#f1f5f9"></div>'
        '          <div><label style="font-size:10.5px;color:#94a3b8;display:block;margin-bottom:2px">End Time</label><input type="time" id="caveCalEvEnd" value="10:30" style="width:100%%;box-sizing:border-box;padding:5px 7px;border-radius:6px;border:1px solid #283548;background:#0b0f17;color:#f1f5f9"></div>'
        '        </div>'
        '        <div><label style="font-size:10.5px;color:#94a3b8;display:block;margin-bottom:2px">Location / Zoom Link</label><input type="text" id="caveCalEvLocation" placeholder="Zoom / 217 Business Building" style="width:100%%;box-sizing:border-box;padding:5px 8px;border-radius:6px;border:1px solid #283548;background:#0b0f17;color:#f1f5f9"></div>'
        '        <div><label style="font-size:10.5px;color:#94a3b8;display:block;margin-bottom:2px">Agenda / Notes</label><textarea id="caveCalEvNotes" rows="3" placeholder="Meeting agenda, attendees, or context..." style="width:100%%;box-sizing:border-box;padding:6px 8px;border-radius:6px;border:1px solid #283548;background:#0b0f17;color:#f1f5f9"></textarea></div>'
        '        <div id="caveCalEvRsvpBar" style="padding:8px 10px;border-radius:8px;background:#090d16;border:1px solid #283548;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:6px">'
        '          <span style="font-size:10.5px;font-weight:700;color:#cbd5e1">&#9989; Your Response / Attendance Status:</span>'
        '          <div style="display:inline-flex;gap:5px;flex-wrap:wrap">'
        '            <button type="button" class="tw-btn done" data-cave-cal-rsvp-set="responded" style="font-weight:750">&#10003; Responded &middot; Attending</button>'
        '            <button type="button" class="tw-btn" data-cave-cal-rsvp-set="not_responded" style="border-color:rgba(245,158,11,0.55);color:#fde68a;font-weight:700">&#9203; Not Responded</button>'
        '            <button type="button" class="tw-btn" data-cave-cal-rsvp-set="tentative">? Tentative</button>'
        '            <button type="button" class="tw-btn" data-cave-cal-rsvp-set="declined" style="border-color:rgba(244,63,94,0.45);color:#fda4af">&#10005; Declined</button>'
        '          </div>'
        '        </div>'
        '        <div style="padding:8px 10px;border-radius:8px;background:#090d16;border:1px solid #283548">'
        '          <div style="font-size:10.5px;font-weight:700;color:#cbd5e1;margin-bottom:5px">&#128197; Reflect &amp; Sync Back into Calendar(s):</div>'
        '          <div style="display:flex;gap:12px;flex-wrap:wrap">'
        '            <label style="display:inline-flex;align-items:center;gap:4px;font-size:11.5px;color:#7dd3fc;cursor:pointer"><input type="checkbox" data-cave-cal-target="psu" checked style="accent-color:#38bdf8"> PSU 365 (Outlook)</label>'
        '            <label style="display:inline-flex;align-items:center;gap:4px;font-size:11.5px;color:#6ee7b7;cursor:pointer"><input type="checkbox" data-cave-cal-target="axmra" style="accent-color:#10b981"> Axmra 365 (Outlook)</label>'
        '            <label style="display:inline-flex;align-items:center;gap:4px;font-size:11.5px;color:#fde68a;cursor:pointer"><input type="checkbox" data-cave-cal-target="gmail" style="accent-color:#f59e0b"> Primary Gmail Calendar</label>'
        '          </div>'
        '        </div>'
        '        <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px">'
        '          <button type="button" class="mini comms-sync-btn" id="btnCaveSaveCalEvent" style="border-color:#10b981;background:rgba(16,185,129,0.18);color:#6ee7b7;font-weight:800">&#128197; Save &amp; Sync to Checked Calendar(s)</button>'
        '          <span id="caveCalSaveStatus" style="font-size:11.5px;color:#94a3b8"></span>'
        '        </div>'
        '      </div>'
        '      <div style="background:#090d16;border:1px solid #283548;border-radius:10px;padding:12px;max-height:360px;overflow-y:auto">'
        '        <div style="font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:.05em;color:#fbbf24;margin-bottom:8px">&#128231; Related Emails &amp; Past Interactions</div>'
        '        <div id="caveCalDialogueEmails" style="display:flex;flex-direction:column;gap:7px"></div>'
        '      </div>'
        '    </div>'
        '  </div>'
        '</div>'
        '<div class="comms-grid" id="commsGrid" data-layout="split">'
        '<div class="comms-col" id="commsCalCol">'
        '<div class="comms-col-h" style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:6px">'
        '<span>&#128197; Multi-Calendar Schedule (<span id="caveCalVisibleCount">%d</span> Events)</span>'
        '<div style="display:inline-flex;align-items:center;gap:4px;flex-wrap:wrap">'
        '<button type="button" class="tw-btn done" id="btnCaveAddCalEventTop" data-cave-add-event="1" title="Add a new Calendar Event directly to your schedule and sync back to PSU 365 / Axmra 365 / Google Calendar" style="font-weight:800">&#10133; Add Calendar Event</button>'
        '<button type="button" class="tw-btn on" data-cave-cal-view="week" title="7-Day Week Grid (Desktop Default — shows full event duration blocks)">&#128198; Week</button>'
        '<button type="button" class="tw-btn" data-cave-cal-view="day" title="Full-Duration Day Time-Block Schedule">&#128197; Day</button>'
        '<button type="button" class="tw-btn" data-cave-cal-view="month" title="Monthly Calendar Grid">&#128467; Month</button>'
        '<button type="button" class="tw-btn" data-cave-cal-view="iphone" title="Apple iPhone Rolling Stream anchored at NOW">&#128241; Rolling Stream</button>'
        '<button type="button" class="tw-btn" data-comms-layout-toggle="cal" title="Click to toggle Calendar between 100%% Full Width (Mockup 3) and 50/50 Split">&#10530; Full Calendar</button>'
        '</div></div>'
        '<div class="cave-cal-nav" style="display:flex;align-items:center;justify-content:space-between;gap:6px;padding:2px 0 4px;font-size:11px;color:var(--text-dim);flex-wrap:wrap">'
        '<div style="display:inline-flex;gap:4px;align-items:center;flex-wrap:wrap">'
        '<button type="button" class="tw-btn" data-cave-cal-nav="-1">&#9664; Prev</button>'
        '<button type="button" class="tw-btn" data-cave-cal-nav="0">Today / Now</button>'
        '<button type="button" class="tw-btn" data-cave-cal-nav="1">Next &#9654;</button>'
        '<span style="margin-left:4px;display:inline-flex;gap:4px;align-items:center" id="caveCalRsvpFilterBar">'
        '<button type="button" class="tw-btn on" data-cal-rsvp-filter="all" title="Show all calendar items">All (<span id="caveCalRsvpAllCnt">0</span>)</button>'
        '<button type="button" class="tw-btn" data-cal-rsvp-filter="responded" style="border-color:rgba(16,185,129,0.55);color:#6ee7b7;font-weight:700" title="Show items you have responded to / are attending">&#10003; Responded (<span id="caveCalRsvpYesCnt">0</span>)</button>'
        '<button type="button" class="tw-btn" data-cal-rsvp-filter="not_responded" style="border-color:rgba(245,158,11,0.55);color:#fde68a;font-weight:700" title="Show invitations you have NOT responded to yet">&#9203; Not Responded (<span id="caveCalRsvpNoCnt">0</span>)</button>'
        '</span>'
        '</div>'
        '<span id="caveCalDateLabel" style="font-weight:700;color:var(--text-warm)">7-Day Week Schedule</span>'
        '</div>'
        '<div id="caveCalViewport" class="cave-cal-viewport">%s</div>'
        '</div>'
        '<div class="comms-col" id="commsMailCol">'
        '<script>window.ANCHOR_SPEED_RACER_INIT = %s;</script>'
        '<div class="comms-col-h" style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:6px">'
        '<div style="display:inline-flex;align-items:center;gap:6px;flex-wrap:wrap">'
        '<span>&#9993; Steward Email Hub: Speed Racer, Inbox &amp; Sent</span>'
        '<div class="cave-mail-folder-bar" id="caveMailFolderBar" style="display:inline-flex;gap:4px;margin-left:2px;flex-wrap:wrap">'
        '<button type="button" class="tw-btn" id="btnCaveOpenSpeedRacer" data-cave-open-speed-racer="1" style="border-color:rgba(245,158,11,0.65);background:rgba(245,158,11,0.18);color:#fef08a;font-weight:800" title="Toggle the expandable Speed Racer Rapid Email Review &amp; Approval Tile">&#127950;&#65039; Speed Racer (<span id="caveSrBtnCount">%d</span>)</button>'
        '<button type="button" class="tw-btn" id="btnCaveMailFolderSrArchive" data-sr-archive-toggle="1" style="border-color:rgba(16,185,129,0.55);background:rgba(16,185,129,0.14);color:#6ee7b7;font-weight:750" title="Pull up the Speed Racer Archive of emails you have approved &amp; sent">&#128220; Speed Racer Archive (<span id="caveMailBarSrArchCount">0</span>)</button>'
        '<button type="button" class="tw-btn on" data-cave-mail-folder="all" title="Show Active Inbox + Acted Upon + Sent Emails">&#128203; All Mail</button>'
        '<button type="button" class="tw-btn" data-cave-mail-folder="inbox" title="Show Active Inbox only (Emails you have not yet replied to, marked Seen, or queued in Speed Racer)">&#128229; Active Inbox (<span id="caveActiveInboxCountBadge">%d</span>)</button>'
        '<button type="button" class="tw-btn" id="btnCaveMailFolderActed" data-cave-mail-folder="acted" style="border-color:rgba(56,189,248,0.55);background:rgba(56,189,248,0.12);color:#7dd3fc;font-weight:750" title="View emails you have already replied to (auto-detected from Sent Items), marked Seen, or given Steward instructions for Speed Racer">&#9745; Acted Upon (<span id="caveActedCountBadge">%d</span>)</button>'
        '<button type="button" class="tw-btn" id="btnCaveMailFolderSent" data-cave-mail-folder="sent" style="border-color:rgba(16,185,129,0.55);color:#6ee7b7;font-weight:700" title="View emails you have sent across your connected accounts &amp; Anchor">&#128228; Sent List (<span id="caveSentCountBadge">%d</span>)</button>'
        '</div></div>'
        '<div style="display:inline-flex;align-items:center;gap:5px;flex-wrap:wrap">'
        '<span class="comms-badge amber" id="caveImpCountBadge">&#9889; %d to Address</span>'
        '<span class="comms-badge" id="caveOthCountBadge">&#128229; %d Not Important</span>'
        '<button type="button" class="tw-btn" id="btnCaveCommsDraftNew" data-comms-draft-reply="1" data-comms-draft-subject="Update on next steps" data-comms-draft-to="" data-comms-draft-project="" data-comms-draft-step="" title="Compose a new email draft">&#9998; Compose</button>'
        '<button type="button" class="tw-btn" data-comms-layout-toggle="mail" title="Click to toggle Email between 100%% Full Width (Mockup 3) and 50/50 Split">&#10530; Full Email</button>'
        '</div></div>'
        '<!-- EXPANDABLE SPEED RACER TILE INSIDE EMAIL HUB -->'
        '<div class="cave-sr-tile open" id="caveSpeedRacerTile" style="margin:6px 0 10px;border:1px solid rgba(245,158,11,0.55);border-radius:9px;background:linear-gradient(180deg,rgba(245,158,11,0.09) 0%%,rgba(15,23,42,0.96) 100%%);overflow:hidden">'
        '  <div class="cave-sr-head" id="caveSpeedRacerHead" style="padding:8px 12px;background:rgba(15,23,42,0.92);display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;cursor:pointer;user-select:none">'
        '    <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">'
        '      <b style="font-size:12.5px;color:#fef08a">&#127950;&#65039; Speed Racer Tile &mdash; Rapid Email Review &amp; Approval Queue</b>'
        '      <span class="comms-badge amber" id="caveSrTileBadge" style="font-weight:700">%d Drafts Awaiting Approval</span>'
        '      <span style="font-size:10.5px;color:#6ee7b7;font-weight:600">&#128274; Steward NEVER sends without your explicit approval</span>'
        '    </div>'
        '    <div style="display:inline-flex;align-items:center;gap:8px;flex-wrap:wrap">'
        '      <button type="button" class="tw-btn" id="btnCaveSrArchiveToggle" data-sr-archive-toggle="1" style="border-color:rgba(16,185,129,0.55);color:#6ee7b7;font-weight:700" title="View all emails approved &amp; sent through Speed Racer">&#128220; Speed Racer Archive (<span id="caveSrArchiveCount">0</span>)</button>'
        '      <span id="caveSrToggleHint" style="font-size:11px;color:#fde68a;font-weight:700">Click Header to Expand / Collapse &#9662;</span>'
        '    </div>'
        '  </div>'
        '  <div class="cave-sr-body" id="caveSpeedRacerBody" style="padding:10px 12px;border-top:1px solid rgba(245,158,11,0.3);display:flex;flex-direction:column;gap:8px">'
        '    <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;background:rgba(167,139,250,0.1);border:1px solid rgba(167,139,250,0.35);padding:6px 10px;border-radius:7px;font-size:11px">'
        '      <span>&#128172; <b>Steward Queue:</b> Click <code>[&#127950;&#65039; &rarr; Speed Racer]</code> on any Inbox email below, or tell the Steward what to draft:</span>'
        '      <div style="display:flex;gap:5px;flex:1;min-width:230px;max-width:480px">'
        '        <input type="text" id="caveSrStewardPromptInput" placeholder="e.g. Draft email to Archty CPA requesting final dissolution tax clearance..." style="flex:1;padding:4px 8px;border-radius:6px;border:1px solid #334155;background:#080d16;color:#f1f5f9;font-size:11px">'
        '        <button type="button" class="tw-btn" id="btnCaveSrStewardDraft" style="border-color:rgba(245,158,11,0.55);color:#fde68a;font-weight:700">&#128172; Draft &rarr; Speed Racer</button>'
        '      </div>'
        '    </div>'
        '    <div id="caveSpeedRacerUndoBar" hidden style="padding:6px 10px;border-radius:7px;border:1px solid #10b981;background:rgba(16,185,129,0.14);color:#ecfdf5;font-size:11.5px;display:flex;align-items:center;justify-content:space-between;gap:8px">'
        '      <span id="caveSpeedRacerUndoText">&#10003; Approved &amp; Sent</span>'
        '      <button type="button" class="tw-btn" id="btnCaveSrUndoSend" style="border-color:#fde68a;color:#fde68a;font-weight:700">&#8617; Undo Send</button>'
        '    </div>'
        '    <div id="caveSpeedRacerArchiveDrawer" hidden style="padding:10px;border-radius:8px;border:1px solid rgba(16,185,129,0.45);background:#070b12"></div>'
        '    <div id="caveSrAttachmentPreviewHost" hidden style="padding:10px;border-radius:8px;border:1px solid #38bdf8;background:#070b12"></div>'
        '    <div id="caveSpeedRacerDeckHost"></div>'
        '  </div>'
        '</div>'
        '<div class="cave-mail-buckets" id="caveMailBucketsGrid" data-mail-folder-mode="all">'
        '<div class="cave-mail-bucket-col" id="caveMailImportantCol">'
        '<div style="font-size:10.5px;font-weight:750;color:#fbbf24;margin-bottom:5px;display:flex;align-items:center;justify-content:space-between">'
        '<span>&#9889; Active Inbox — Emails to Address (Already-Replied &amp; Seen Emails Auto-Moved to Acted Upon)</span>'
        '<span style="font-size:10px;color:var(--text-dim);font-weight:500">Open &rarr; &#128065; Seen or &#127950;&#65039; Speed Racer moves to Acted Upon</span>'
        '</div>'
        '<div id="caveMailImportantList" class="cave-mail-list">%s</div>'
        '</div>'
        '<div class="cave-mail-bucket-col" id="caveMailActedCol" style="margin-top:8px;padding-top:8px;border-top:1px solid rgba(56,189,248,0.35)">'
        '<div style="font-size:10.5px;font-weight:750;color:#7dd3fc;margin-bottom:5px;display:flex;align-items:center;justify-content:space-between">'
        '<span>&#9745; Acted Upon List (Already Replied in Sent Items, Queued in Speed Racer, or Marked Seen)</span>'
        '<span style="font-size:10px;color:var(--text-dim);font-weight:500">Auto-detects your Sent replies (e.g. Hollie Meyer)</span>'
        '</div>'
        '<div id="caveMailActedList" class="cave-mail-list">%s</div>'
        '</div>'
        '<div class="cave-mail-bucket-col" id="caveMailSentCol" style="margin-top:8px;padding-top:8px;border-top:1px solid rgba(16,185,129,0.35)">'
        '<div style="font-size:10.5px;font-weight:750;color:#6ee7b7;margin-bottom:5px;display:flex;align-items:center;justify-content:space-between">'
        '<span>&#128228; Sent Emails (Messages You Have Sent Across Gmail, PSU 365, Axmra 365 &amp; Anchor)</span>'
        '<span style="font-size:10px;color:var(--text-dim);font-weight:500">Click any sent email to view full message or follow up</span>'
        '</div>'
        '<div id="caveMailSentList" class="cave-mail-list">%s</div>'
        '</div>'
        '<div class="cave-mail-bucket-col" id="caveMailOtherCol" style="margin-top:8px;padding-top:8px;border-top:1px dashed var(--line)">'
        '<div style="font-size:10.5px;font-weight:750;color:var(--text-dim);margin-bottom:5px;display:flex;align-items:center;justify-content:space-between">'
        '<span>&#128229; Not Important / Downgraded (Promos &amp; Seen-Unopened)</span>'
        '<span style="font-size:10px;color:var(--text-dim2);font-weight:500">Click &#11014; Upgrade to promote</span>'
        '</div>'
        '<div id="caveMailOtherList" class="cave-mail-list">%s</div>'
        '</div>'
        '</div>'
        '%s'
        '</div>'
        '</div>'
        '%s'
        '</div></section>'
    ) % (
        acc_n,
        state_txt,
        len(all_cal_evs),
        len(all_cal_evs),
        (" &middot; %d Dual-Cal" % merged_dup_count) if merged_dup_count else "",
        cal_line_summary,
        len(sr_queue),
        len(imp_emails),
        len(sent_emails),
        len(oth_emails),
        mail_line_summary,
        acc_bar_html,
        (" open" if acc_n == 0 else ""),
        poller_min,
        upcoming_prep_html,
        (" hidden" if acc_n > 0 else ""),
        len(all_cal_evs),
        cal_col_html,
        sr_json_boot,
        len(sr_queue),
        len(imp_emails) + len(oth_emails),
        len(acted_emails),
        len(sent_emails),
        len(imp_emails),
        len(oth_emails),
        len(sr_queue),
        imp_mail_html,
        acted_mail_html,
        sent_mail_html,
        oth_mail_html,
        roadmap_corr_html,
        conn_note,
    )


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
        '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;flex-wrap:wrap;gap:6px">'
        '<b>&#129309; Register Collaborator Mothership / Import Portable Cockpit Packet</b>'
        '<div style="display:flex;gap:6px;align-items:center">'
        '<button type="button" class="mini comms-setup-btn" id="btnCollabPresetMerrill" data-collab-preset-merrill="1">&#9889; Pre-Fill Merrill Liechty</button>'
        '<button type="button" class="mini" id="btnCollabModalClose">&times; Close</button></div></div>'
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
    in_goal_cockpits = [(i, p) for i, p in in_goal if p.get("kind") in ("project", "effort")]
    in_goal_tasks = [(i, p) for i, p in in_goal if p.get("kind") not in ("project", "effort")]
    n_cockpits = len(in_goal_cockpits) + len(loose)

    def cockpit_link(pid, rel):
        if not pid:
            return ""
        href = "/steward/v1?pid=%s&amp;dir=%s" % (esc(pid), esc(_quote(str(rel or ""))))
        return '<a class="t-go cand-go" href="%s" target="_blank" rel="noopener" data-tip="Open cockpit &#8599;" title="Open the AI cockpit"><span class="t-btn-txt">cockpit </span><span class="t-go-arr">&#8599;</span></a>' % href

    def acts_step(sid, pid="", rel=""):
        return ('<span class="acts">%s<button class="mini" data-seat="deck" data-step="%s">&rarr; on deck</button>'
                '<button class="mini" data-seat="active" data-step="%s">&rarr; active</button></span>') % (cockpit_link(pid, rel), esc(sid), esc(sid))

    def acts_new(c):
        return ('<span class="acts">%s<button class="mini" data-cand-seat="deck" data-ref="%s" data-name="%s">&rarr; on deck</button>'
                '<button class="mini" data-cand-seat="active" data-ref="%s" data-name="%s">&rarr; active</button></span>') % (
            cockpit_link(c.get("pid") or "", c.get("dir") or ""), esc(c["ref"]), esc(c["name"]), esc(c["ref"]), esc(c["name"]))

    def meta(score, why, created, worked, ckind="cockpit"):
        return ('data-score="%d" data-created="%s" data-worked="%s" data-cand-kind="%s"' % (score, esc(created or ""), esc(worked or ""), esc(ckind)),
                '<span class="cs" title="%s">%d</span>' % (esc(why), score),
                '<span class="cd">%s%s</span>' % (("worked " + esc(worked)) if worked else "not worked yet", (" &middot; made " + esc(created)) if created else ""))

    def row(attrs, score_html, dates_html, name_html, where, acts):
        return '<li class="cand" %s>%s<span class="cn">%s</span><span class="cw">%s</span>%s%s</li>' % (attrs, score_html, name_html, where, dates_html, acts)

    rows_cockpits_goal = "".join(
        row(*meta(p.get("c_score", 0), p.get("c_why", ""), p.get("c_created"), p.get("c_worked"), "cockpit")[:1],
            meta(p.get("c_score", 0), p.get("c_why", ""), p.get("c_created"), p.get("c_worked"), "cockpit")[1],
            meta(p.get("c_score", 0), p.get("c_why", ""), p.get("c_created"), p.get("c_worked"), "cockpit")[2],
            ('<span class="wm">&#9873;</span> ' if p.get("needs_you") else "") + esc(part_name(p)),
            "%s &middot; in %s" % (esc(KIND_LABEL.get(p.get("kind"), "")), esc(i.get("name") or "")),
            acts_step(p.get("id") or "", p.get("pid") or "", p.get("dir") or ""))
        for i, p in sorted(in_goal_cockpits, key=lambda t: -t[1].get("c_score", 0))
    )
    rows_b = "".join(
        row(*meta(c["score"], c["why"], c["created"], c["worked"], "cockpit")[:1],
            meta(c["score"], c["why"], c["created"], c["worked"], "cockpit")[1],
            meta(c["score"], c["why"], c["created"], c["worked"], "cockpit")[2],
            ('<span class="wm">&#9873;</span> ' if c["needs"] else "") + esc(c["name"]),
            "%s &middot; in no goal" % esc(c["where"]), acts_new(c))
        for c in sorted(loose, key=lambda c: -c["score"])
    )
    rows_tasks_goal = "".join(
        row(*meta(p.get("c_score", 0), p.get("c_why", ""), p.get("c_created"), p.get("c_worked"), "task")[:1],
            meta(p.get("c_score", 0), p.get("c_why", ""), p.get("c_created"), p.get("c_worked"), "task")[1],
            meta(p.get("c_score", 0), p.get("c_why", ""), p.get("c_created"), p.get("c_worked"), "task")[2],
            ('<span class="wm">&#9873;</span> ' if p.get("needs_you") else "") + esc(part_name(p)),
            "%s &middot; in %s" % (esc(KIND_LABEL.get(p.get("kind"), "")), esc(i.get("name") or "")),
            acts_step(p.get("id") or ""))
        for i, p in sorted(in_goal_tasks, key=lambda t: -t[1].get("c_score", 0))
    )
    return (
        '<section class="shelf cands" id="shCands"><details class="cands-tile" id="candsTile"><summary class="shelf-h">'
        '<h3>Candidates</h3><span class="c">%d</span><span class="cand-cockpit-pill">%d AI cockpit%s ready</span><span class="rule"></span>'
        '<span class="sub">every AI cockpit and desk item you could put on deck or make active</span></summary>'
        '<div class="cand-tools"><input type="search" id="candSearch" placeholder="search the candidates&hellip;" aria-label="search the candidates" autocomplete="off">'
        '<div class="cand-filter" id="candFilter" role="group" aria-label="filter candidates">'
        '<button type="button" class="cand-flt on" data-cand-filter="all">All (%d)</button>'
        '<button type="button" class="cand-flt" data-cand-filter="cockpit">AI Cockpits (%d)</button>'
        '<button type="button" class="cand-flt" data-cand-filter="task">Desk Tasks (%d)</button>'
        '</div>'
        '<label class="cand-sort">sort <select id="candSort"><option value="score" selected>the steward&rsquo;s relevance</option><option value="worked">last worked on</option>'
        '<option value="created">date created</option><option value="name">name</option></select></label>'
        '<span class="cand-note" id="candNote"></span></div>'
        '%s%s%s</details></section>'
    ) % (n, n_cockpits, "" if n_cockpits == 1 else "s", n, n_cockpits, len(in_goal_tasks),
         ('<div class="cand-group" data-cand-group="cockpit"><div class="k">Candidate AI cockpits (in a goal, not on the desk) &middot; %d</div><ul>%s</ul></div>' % (len(in_goal_cockpits), rows_cockpits_goal)) if in_goal_cockpits else "",
         ('<div class="cand-group" data-cand-group="cockpit"><div class="k">AI cockpits in no goal &middot; %d</div><ul>%s</ul></div>' % (len(loose), rows_b)) if loose else "",
         ('<div class="cand-group" data-cand-group="task"><div class="k">In a goal, not on the desk (desk tasks) &middot; %d</div><ul>%s</ul></div>' % (len(in_goal_tasks), rows_tasks_goal)) if in_goal_tasks else "")


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
        foundry_bar = ""
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
    """Wave 6b, Wave 15, Wave 19 & Wave 21 (2026-11-02): Asymmetric Horizon Chief-of-Staff Next-Effort Engine
    at the top of the Cave of Wonders board (Today 44% · This Week 28% · This Month 14% · Star Chart Q2 Goals 14%)
    co-populated by the Cave of Wonders Steward and Star Chart Steward with:
      - Break-Between-Cockpits Filter (All · 15m Break · 30m Prep · 60m+ Q2 Deep Work · Family & Relationships)
      - Live Q1 -> Q2 Deep-Work Unlock Meter (clearing Urgent items unlocks protected Quadrant II Deep Work)
      - Parable-of-the-Oranges Skill Pre-Staging (Einstein, researchPrime, Superjump, Gandalf, Chekhov, Legal-Beagle, Financial-Analyst)
      - 1-click Open AI Cockpit, Create AI Cockpit, Mark Cleared, and Rotate / Next Suggestion."""
    cards = proactive_triage_cards(ctx)
    cos = chief_of_staff_horizon_efforts(ctx)
    desk_pid = str(ctx.get("desk_pid") or "")
    desk_href = ("/steward/v1?pid=%s&amp;dir=Small%%20items" % esc(desk_pid)) if desk_pid else "/desk"

    # Build Today asymmetric effort cards (Widest column 44%)
    cos_today_html = []
    for ef in cos.get("today_efforts") or ():
        done_btn = ""
        list_tid = str(ef.get("list_tile_id") or "")
        if list_tid:
            done_btn = (
                '<button type="button" class="cos-act-btn done-unlock" data-wl-cos-complete="%s" data-mark-done="1" data-cos-clear-id="%s" '
                'data-target-dir="%s" data-target-step="%s" title="Check off this item on The List and move it to Things Done">&#10003; Check Off The List (&rarr; Things Done)</button>'
                '<button type="button" class="cos-act-btn" data-wl-focus-tile="%s" title="Open this item inside The List tile below">&#128203; Open in The List</button>'
                % (esc(list_tid), esc(ef["id"]), esc(ef.get("folder") or ""), esc(ef.get("step_id") or ""), esc(list_tid))
            )
        elif ef.get("unlock_note"):
            done_btn = (
                '<button type="button" class="cos-act-btn done-unlock" data-mark-done="1" data-cos-clear-id="%s" '
                'data-target-dir="%s" data-target-step="%s" title="Mark cleared and unlock Q2 Deep Work">&#10003; Mark Cleared (%s)</button>'
                % (esc(ef["id"]), esc(ef.get("folder") or ""), esc(ef.get("step_id") or ""), esc(ef["unlock_note"]))
            )
        oranges_cls = "cos-oranges q2" if ef.get("tier_cls") == "q2-deep" else "cos-oranges"
        cos_today_html.append(
            '<div class="cos-effort-card %s" id="%s" data-cos-card="1" data-break="%s">'
            '<div class="cos-ef-top">'
            '<span class="cos-ef-name" data-cos-modal-open="1" data-cos-title="%s" data-cos-tier="%s" '
            'data-cos-driver="%s" data-cos-oranges="%s" data-cos-href="%s" data-cos-prompt="%s">%s</span>'
            '<div class="cos-ef-badges">'
            '<span class="cos-pill %s">%s</span>'
            '<span class="cos-pill sky">%s</span>'
            '</div></div>'
            '<div class="cos-ef-driver"><strong>Driver:</strong> %s</div>'
            '<div class="%s">&#127818; <strong>Parable of the Oranges (Pre-Staged &middot; %s):</strong> %s</div>'
            '<div class="cos-ef-actions">'
            '<a class="cos-act-btn cockpit-open" href="%s" target="_blank" rel="noopener">%s</a>'
            '<button type="button" class="cos-act-btn skill-prestage" data-cos-prestage-prompt="%s" data-cos-skill="%s">%s</button>'
            '%s'
            '<button type="button" class="cos-act-btn" data-cos-rotate="%s" title="Rotate to next Steward suggestion">&#9197; Rotate</button>'
            '</div></div>'
            % (
                esc(ef["tier_cls"]),
                esc(ef["id"]),
                esc(ef["break_tags"]),
                esc(ef["title"]),
                esc(ef["tier_badge"]),
                esc(ef["driver"]),
                esc(ef["oranges_text"]),
                esc(ef["href"]),
                esc(ef["skill_prompt"]),
                esc(ef["title"]),
                esc(ef["tier_pill_cls"]),
                esc(ef["tier_badge"]),
                esc(ef["break_badge"]),
                esc(ef["driver"]),
                oranges_cls,
                esc(ef["oranges_skill"]),
                esc(ef["oranges_text"]),
                esc(ef["href"]),
                esc(ef["open_label"]),
                esc(ef["skill_prompt"]),
                esc(ef["oranges_skill"]),
                esc(ef["skill_btn_label"]),
                done_btn,
                esc(ef["id"]),
            )
        )

    # Build This Week asymmetric effort cards (Medium column 28% — Soon-to-Be Urgent + Family & Relationships)
    cos_week_html = []
    for ef in cos.get("week_efforts") or ():
        open_cls = "cockpit-create" if ef.get("is_create") else "cockpit-open"
        cos_week_html.append(
            '<div class="cos-effort-card %s" id="%s" data-cos-card="1" data-break="%s">'
            '<div class="cos-ef-top">'
            '<span class="cos-ef-name" data-cos-modal-open="1" data-cos-title="%s" data-cos-tier="%s" '
            'data-cos-driver="%s" data-cos-oranges="%s" data-cos-href="%s" data-cos-prompt="%s">%s</span>'
            '<span class="cos-pill %s">%s</span>'
            '</div>'
            '<div class="cos-ef-driver"><strong>Driver:</strong> %s</div>'
            '<div class="cos-ef-actions">'
            '<a class="cos-act-btn %s" href="%s" target="_blank" rel="noopener">%s</a>'
            '<button type="button" class="cos-act-btn skill-prestage" data-cos-prestage-prompt="%s" data-cos-skill="%s">%s</button>'
            '<button type="button" class="cos-act-btn" data-cos-rotate="%s" title="Rotate suggestion">&#9197;</button>'
            '</div></div>'
            % (
                esc(ef["tier_cls"]),
                esc(ef["id"]),
                esc(ef["break_tags"]),
                esc(ef["title"]),
                esc(ef["tier_badge"]),
                esc(ef["driver"]),
                esc(ef["oranges_skill"]),
                esc(ef["href"]),
                esc(ef["skill_prompt"]),
                esc(ef["title"]),
                esc(ef["tier_pill_cls"]),
                esc(ef["tier_badge"]),
                esc(ef["driver"]),
                open_cls,
                esc(ef["href"]),
                esc(ef["open_label"]),
                esc(ef["skill_prompt"]),
                esc(ef["oranges_skill"]),
                esc(ef["skill_btn_label"]),
                esc(ef["id"]),
            )
        )

    # Build This Month compact expandable cards (14% default -> widens on click)
    cos_month_html = []
    for ef in cos.get("month_efforts") or ():
        open_cls = "cockpit-create" if ef.get("is_create") else "cockpit-open"
        cos_month_html.append(
            '<div class="cos-compact-effort" id="%s" data-cos-card="1" data-break="%s" data-cos-expand-col="month">'
            '<div class="cos-ce-title"><span>%s</span><span class="cos-pill %s">%s</span></div>'
            '<div class="cos-ce-meta">%s</div>'
            '<div class="cos-ce-detail">'
            '<div class="cos-oranges">&#127818; %s</div>'
            '<div class="cos-ef-actions">'
            '<a class="cos-act-btn %s" href="%s" target="_blank" rel="noopener">%s</a>'
            '<button type="button" class="cos-act-btn skill-prestage" data-cos-prestage-prompt="%s">%s</button>'
            '</div></div></div>'
            % (
                esc(ef["id"]),
                esc(ef["break_tags"]),
                esc(ef["title"]),
                esc(ef["pill_cls"]),
                esc(ef["badge"]),
                esc(ef["meta"]),
                esc(ef["oranges_text"]),
                open_cls,
                esc(ef["href"]),
                esc(ef["open_label"]),
                esc(ef["skill_prompt"]),
                esc(ef["skill_btn_label"]),
            )
        )

    # Build Quarter / Star Chart Q2 compact expandable cards (14% default -> widens on click)
    cos_qtr_html = []
    for ef in cos.get("quarter_efforts") or ():
        open_cls = "cockpit-create" if ef.get("is_create") else "cockpit-open"
        cos_qtr_html.append(
            '<div class="cos-compact-effort" id="%s" data-cos-card="1" data-break="%s" data-cos-expand-col="quarter">'
            '<div class="cos-ce-title"><span>%s</span><span class="cos-pill %s">%s</span></div>'
            '<div class="cos-ce-meta">%s</div>'
            '<div class="cos-ce-detail">'
            '<div class="cos-oranges q2">&#127818; %s</div>'
            '<div class="cos-ef-actions">'
            '<a class="cos-act-btn %s" href="%s" target="_blank" rel="noopener">%s</a>'
            '<button type="button" class="cos-act-btn skill-prestage" data-cos-prestage-prompt="%s">%s</button>'
            '</div></div></div>'
            % (
                esc(ef["id"]),
                esc(ef["break_tags"]),
                esc(ef["title"]),
                esc(ef["pill_cls"]),
                esc(ef["badge"]),
                esc(ef["meta"]),
                esc(ef["oranges_text"]),
                open_cls,
                esc(ef["href"]),
                esc(ef["open_label"]),
                esc(ef["skill_prompt"]),
                esc(ef["skill_btn_label"]),
            )
        )

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
        '<section class="triage-strip compact-horizons is-collapsed" id="shTriage">'
        '<div class="ts-head chz-head" style="margin-bottom:4px;gap:6px">'
        '<div class="ts-title chz-title" data-cos-toggle-body="1" style="cursor:pointer;gap:5px" title="Click to expand or collapse Chief-of-Staff Recommendations &amp; Parable-of-the-Oranges Skill Pre-Staging">'
        '<span class="ts-badge chz-badge">&#9733; Chief of Staff</span>'
        '<span class="cos-pill sky">&#128994; %d Running</span>'
        '<span class="cos-pill orange">&#127818; %d Pre-Staged</span>'
        '<span class="cos-pill emerald" id="cosListLinkBadge">&#128203; Populated from The List (#1 &rarr; #2 &rarr; #3)</span><span class="ts-sub chz-sub" style="font-size:10.5px">&#127818; Parable of the Oranges &middot; 1) You set Priority on <strong>The List</strong> &rarr; 2) Chief of Staff populates <strong>Things To Do</strong></span>'
        '</div>'
        '<div class="ts-quick chz-quick" style="gap:4px">'
        '<button type="button" class="ts-pill cos-expand-toggle" id="btnCosToggleExpand" data-cos-toggle-body="1" aria-expanded="false" title="Click to drill down and expand Chief-of-Staff Next-Effort Recommendations &amp; Parable-of-the-Oranges Skill Pre-Staging">&#9662; Expand Recommendations (%d)</button>'
        '<button type="button" class="ts-pill" data-open-the-list="1" style="border-color:rgba(56,189,248,0.55);color:#7dd3fc" title="Open or expand The List tile right below Chief of Staff">&#128203; The List</button><button type="button" class="ts-pill" data-wl-populate-cos="1" style="border-color:rgba(16,185,129,0.55);color:#6ee7b7" title="Steward (in Chief of Staff mode) populates Things To Do from your priority order on The List">&#9889; Populate from The List</button><button type="button" class="ts-pill" id="btnTriageSynthesize" data-triage-synthesize="1" title="Synthesize a cross-portfolio Chief-of-Staff Executive Brief">&#10022; Brief</button>'
        '<a class="ts-pill desk" href="%s" target="_blank" rel="noopener" title="Run ad-hoc admin tasks in the Desktop AI Cockpit">&#128421; Ad-Hoc Cockpit</a>'
        '<button type="button" class="ts-pill" data-toggle-dated="1" title="Toggle Dated Schedule Ruler">&#128197; Dated Ruler</button>'
        '<button type="button" class="ts-pill" data-jump="#cal">&#9993; Email &amp; Counsel</button>'
        '<button type="button" class="ts-pill" id="btnTriageConnectComms" data-open-comms-connect="1" style="border-color:rgba(16,185,129,0.55);color:#6ee7b7" title="Connect Gmail, Google Calendar &amp; Microsoft Outlook right on the Cave of Wonders">&#128197;+&#9993; Connect</button>'
        '</div></div>'
        '<div class="cos-compact-summary-row" id="cosCompactSummaryRow">'
        '<button type="button" class="cos-cs-pill today" data-cos-drill="today" title="Click to drill down into Today recommendations &amp; pre-staged skills">'
        '<span class="cos-cs-tag red">&#128293; Today (3)</span>'
        '<span class="cos-cs-text">1:00 PM AI Club Slides &middot; Family Trusts &rarr; <strong>2:15 PM Q2 Deep Work</strong></span>'
        '<span class="cos-cs-caret">&#9662;</span></button>'
        '<button type="button" class="cos-cs-pill week" data-cos-drill="week" title="Click to drill down into This Week recommendations (Soon-Urgent &amp; Family)">'
        '<span class="cos-cs-tag amber">&#128992; Week (4)</span>'
        '<span class="cos-cs-text">Tue 8 AM MBA Teaching &middot; Sun Team Teach w/ Jane</span>'
        '<span class="cos-cs-caret">&#9662;</span></button>'
        '<button type="button" class="cos-cs-pill month" data-cos-drill="month" title="Click to drill down into This Month &amp; Family Lead-Time Radar">'
        '<span class="cos-cs-tag pink">&#128197; Month (3)</span>'
        '<span class="cos-cs-text">&#127873; Family Trips &amp; Birthdays &middot; Normalizing Flows</span>'
        '<span class="cos-cs-caret">&#9662;</span></button>'
        '<button type="button" class="cos-cs-pill quarter" data-cos-drill="quarter" title="Click to drill down into Star Chart Quadrant II Deep-Work Goals">'
        '<span class="cos-cs-tag emerald">&#127775; Q2 Goals (3)</span>'
        '<span class="cos-cs-text">&#128214; Artificial Magi &middot; &#128300; 3D Phenomics</span>'
        '<span class="cos-cs-caret">&#9662;</span></button>'
        '</div>'
        '<div class="triage-exec-brief" id="triageExecBrief" hidden style="margin:6px 0 0;padding:8px 12px;border-radius:8px;border:1px solid #2b3546;background:#121822;font-size:12px;color:#e6edf3"></div>'
        '<div class="cos-expandable-body" id="cosExpandableBody" hidden>'
        '<div class="cos-command-bar" id="cosCommandBar">'
        '<div class="cos-break-selector">'
        '<span class="cos-break-label">&#127818; Break Between Cockpits:</span>'
        '<button type="button" class="cos-break-btn active" data-cos-break="all">All Next Efforts (%d)</button>'
        '<button type="button" class="cos-break-btn" data-cos-break="15m">&#9889; 15m Break (Quick Clear / Triage)</button>'
        '<button type="button" class="cos-break-btn" data-cos-break="30m">&#127818; 30m Break (Pre-Staged Cockpit Prep)</button>'
        '<button type="button" class="cos-break-btn" data-cos-break="deep">&#129504; 60m+ Q2 Deep Work (Star Chart Value)</button>'
        '<button type="button" class="cos-break-btn" data-cos-break="family">&#127968; Family &amp; Relationships Radar</button>'
        '</div>'
        '<div class="cos-q2-meter-box">'
        '<span><strong>Q1 &rarr; Q2 Deep-Work Unlock:</strong> <span id="cosQ2UnlockLabel">Clear 2 Urgent efforts &rarr; Unlocks <strong>2.5 hrs</strong> uninterrupted Q2 Deep Work (2:15&ndash;4:45 PM)</span></span>'
        '<div class="cos-q2-track" title="Red = Urgent Now | Amber = Soon-Urgent | Green = Unlocked Q2 Deep Work">'
        '<div class="cos-q2-seg-urg" id="cosSegUrg" style="width:28%%"></div>'
        '<div class="cos-q2-seg-soon" id="cosSegSoon" style="width:27%%"></div>'
        '<div class="cos-q2-seg-deep" id="cosSegDeep" style="width:45%%"></div>'
        '</div>'
        '<button type="button" class="cos-act-btn" data-cos-toggle-body="1" title="Collapse Chief of Staff recommendations">&#9652; Collapse</button>'
        '</div></div>'
        '<div class="cos-horizon-strip" id="cosHorizonStrip">'
        '<div class="cos-hz-col cos-hz-today is-wide" id="cosCol-today">'
        '<div class="cos-hz-head" data-cos-expand-col="today">'
        '<div class="cos-hz-title"><span>&#128203; Things To Do &mdash; Populated by Chief of Staff from The List (#1 &rarr; #2 &rarr; #3)</span>'
        '<span class="cos-pill red">2 Urgent</span><span class="cos-pill emerald">1 Q2 Deep Slot</span></div>'
        '<button type="button" class="cos-hz-exp-btn" data-cos-expand-col="today">Widest (Default)</button>'
        '</div>%s</div>'
        '<div class="cos-hz-col is-wide" id="cosCol-week">'
        '<div class="cos-hz-head" data-cos-expand-col="week">'
        '<div class="cos-hz-title"><span>&#128992; This Week &mdash; Soon-Urgent &amp; Family</span>'
        '<span class="cos-pill amber">4 Efforts</span></div>'
        '<button type="button" class="cos-hz-exp-btn" data-cos-expand-col="week">&#10530; Focus Week</button>'
        '</div>%s</div>'
        '<div class="cos-hz-col" id="cosCol-month">'
        '<div class="cos-hz-head" data-cos-expand-col="month">'
        '<div class="cos-hz-title"><span>&#128197; This Month</span><span class="cos-pill pink">3</span></div>'
        '<button type="button" class="cos-hz-exp-btn" data-cos-expand-col="month">&#10530; Expand</button>'
        '</div>%s</div>'
        '<div class="cos-hz-col" id="cosCol-quarter">'
        '<div class="cos-hz-head" data-cos-expand-col="quarter">'
        '<div class="cos-hz-title"><span>&#127775; Star Chart Q2 Goals</span><span class="cos-pill emerald">3</span></div>'
        '<button type="button" class="cos-hz-exp-btn" data-cos-expand-col="quarter">&#10530; Expand</button>'
        '</div>%s</div>'
        '</div>'
        '<div class="chz-grid ts-grid" style="margin-top:8px;display:none">'
        '<button type="button" class="chz-card today" data-hz-toggle="today" aria-expanded="false" aria-controls="hzDrawer-today">'
        '<div class="chz-top"><span class="chz-name">Today Drawer</span><span class="chz-cnt">%d items &#9662;</span></div>'
        '<div class="chz-sum">%s</div>'
        '<div class="chz-tag"><span class="dot g"></span>Deep Work + Q1/Desk</div></button>'
        '<button type="button" class="chz-card week" data-hz-toggle="week" aria-expanded="false" aria-controls="hzDrawer-week">'
        '<div class="chz-top"><span class="chz-name">This Week Drawer</span><span class="chz-cnt">%d items &#9662;</span></div>'
        '<div class="chz-sum">%s</div>'
        '<div class="chz-tag"><span class="dot b"></span>7-Day Horizon</div></button>'
        '<button type="button" class="chz-card" data-hz-toggle="month" aria-expanded="false" aria-controls="hzDrawer-month">'
        '<div class="chz-top"><span class="chz-name">This Month Drawer</span><span class="chz-cnt">%d items &#9662;</span></div>'
        '<div class="chz-sum">Family Lead-Time &amp; Deliverables</div>'
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
        '</div>'
        '<div class="cos-modal-backdrop" id="cosOrangesModal" hidden>'
        '<div class="cos-modal-card">'
        '<div class="cos-modal-head"><h3 id="cosModalTitle">Effort Details</h3>'
        '<button type="button" class="cos-act-btn" id="btnCosModalClose">&#10005; Close</button></div>'
        '<div style="margin-bottom:6px"><span class="cos-pill orange" id="cosModalTier">Next-Best Effort</span></div>'
        '<p style="font-size:12px;color:#9da7b6;margin:6px 0" id="cosModalDriver"></p>'
        '<div class="cos-oranges" style="margin:8px 0;padding:8px 10px" id="cosModalOranges"></div>'
        '<div style="font-size:11.5px;font-weight:700;margin-top:10px;color:#e6edf3">&#127818; Pre-Stage or Dispatch Foundry Skills into This AI Cockpit:</div>'
        '<div class="cos-skill-chip-row">'
        '<button type="button" class="cos-act-btn skill-prestage" data-cos-dispatch-skill="researchPrime">&#128300; researchPrime</button>'
        '<button type="button" class="cos-act-btn skill-prestage" data-cos-dispatch-skill="Superjump">&#128640; Superjump</button>'
        '<button type="button" class="cos-act-btn skill-prestage" data-cos-dispatch-skill="Gandalf">&#129497; Gandalf</button>'
        '<button type="button" class="cos-act-btn skill-prestage" data-cos-dispatch-skill="Einstein">&#127891; Einstein</button>'
        '<button type="button" class="cos-act-btn skill-prestage" data-cos-dispatch-skill="Chekhov">&#127917; Chekhov</button>'
        '<button type="button" class="cos-act-btn skill-prestage" data-cos-dispatch-skill="Legal-Beagle">&#9878; Legal-Beagle</button>'
        '<button type="button" class="cos-act-btn skill-prestage" data-cos-dispatch-skill="Financial-Analyst">&#128202; Financial-Analyst</button>'
        '</div>'
        '<div style="display:flex;justify-content:flex-end;gap:8px;margin-top:12px;padding-top:8px;border-top:1px solid #26354d">'
        '<button type="button" class="cos-act-btn cockpit-create" data-foundry-action="new_cockpit">+ Create New AI Cockpit</button>'
        '<a class="cos-act-btn cockpit-open" id="cosModalOpenBtn" href="/steward/v1" target="_blank" rel="noopener">&#8599; Open Ready AI Cockpit</a>'
        '</div></div></div>'
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
        int(cos.get("running_cockpits") or 2),
        int(cos.get("skills_prestaged") or 6),
        int(cos.get("total_efforts") or 13),
        desk_href,
        int(cos.get("total_efforts") or 13),
        "".join(cos_today_html),
        "".join(cos_week_html),
        "".join(cos_month_html),
        "".join(cos_qtr_html),
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

def _working_list_spine_html(ctx) -> str:
    """Variation A + The List (2026-11-06):
    - The List starts as a single collapsed tile showing the number of items on it; click to expand.
    - Inside The List, every item starts as a single-line tile showing its Order (#1, #2...), Title, and Category of Sub-List (plus assigned AI Cockpit & Star Chart Goal/Initiative badges), which expands when clicked on."""
    try:
        import comms_connector as _cc
        wl_state = _cc.load_working_list_spine()
    except Exception:
        wl_state = {"tiles": [], "cockpit_items_catalog": [], "initiative_items_catalog": [], "cockpits_dropdown_catalog": [], "goals_dropdown_catalog": [], "project_folders_catalog": [], "cos_recommendations": []}

    tiles = [t for t in (wl_state.get("tiles") or []) if isinstance(t, dict)]
    # Ensure all items start collapsed as single-line tiles on initial render
    for _t in tiles:
        _t["expanded"] = False
    active_tiles = [t for t in tiles if not t.get("archived")]
    arch_tiles = [t for t in tiles if t.get("archived")]
    cnt_bus = sum(1 for t in active_tiles if t.get("category") == "Business")
    cnt_tch = sum(1 for t in active_tiles if t.get("category") == "Teaching")
    cnt_res = sum(1 for t in active_tiles if t.get("category") == "Research")
    cnt_per = sum(1 for t in active_tiles if t.get("category") == "Personal")
    wl_json = json.dumps(wl_state).replace("</", "<\/")

    def _ord_lbl(n: int) -> str:
        n = max(1, int(n or 1))
        suf = "th" if 10 <= (n % 100) <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return f"#{n} ({n}{suf})"

    init_rows = []
    for t in active_tiles:
        tid = esc(str(t.get("id") or ""))
        title = esc(str(t.get("title") or "Effort Tile"))
        cat = esc(str(t.get("category") or "Business"))
        p_num = int(t.get("priority") or 1)
        ord_txt = esc(_ord_lbl(p_num))
        steps = [s for s in (t.get("steps") or []) if isinstance(s, dict)]
        done_n = sum(1 for s in steps if s.get("done"))
        tot_n = len(steps)
        ck_name = esc(str(t.get("cockpitName") or ""))
        goal_name = esc(str(t.get("goalName") or ""))
        ck_chip = ('<span class="wl-pill sky" title="Assigned AI Cockpit">&#128760; %s</span>' % ck_name) if ck_name else ""
        goal_chip = ('<span class="wl-pill purple" title="Assigned Star Chart Goal / Initiative">&#127775; %s</span>' % goal_name[:34]) if goal_name else ""
        p_cls = "prio-a" if p_num == 1 else ("prio-b" if p_num == 2 else "prio-c")
        init_rows.append(
            '<article class="wl-tile %s" data-wl-tile-id="%s" data-wl-priority="%d">'
            '<div class="wl-summary" data-wl-toggle-expand="%s" style="padding:7px 10px;align-items:center">'
            '<span class="wl-prio" data-wl-cycle-prio="%s" title="Order %s on The List">%s</span>'
            '<div class="wl-main" style="display:flex;align-items:center;justify-content:space-between;gap:8px;flex:1;min-width:0">'
            '<div class="wl-title-line" style="margin:0;flex-wrap:nowrap;overflow:hidden"><b class="wl-title" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">%s</b>'
            '<span class="wl-pill">%s</span>'
            '%s%s'
            '<span class="wl-pill sky">&#10003; %d/%d</span></div>'
            '</div>'
            '<div class="wl-acts">'
            '<button type="button" class="mini" data-wl-archive="%s" title="Check off and move to Things Done">&#10003; Done</button>'
            '<button type="button" class="mini" data-wl-toggle-expand="%s">&#9662; Expand</button>'
            '</div></div></article>'
            % (p_cls, tid, p_num, tid, tid, ord_txt, ord_txt, title, cat, ck_chip, goal_chip, done_n, tot_n, tid, tid)
        )

    return (
        '<section class="wl-spine-sec is-collapsed" id="caveWorkingListSpine" data-the-list-tile="1" aria-label="The List">'
        '<script>window.ANCHOR_WORKING_LIST_INIT = %s;</script>'
        '<div class="wl-head" id="wlSpineHead" style="cursor:pointer" title="Click to expand or collapse The List">'
        '  <div class="wl-head-left" id="wlSpineToggleBar" data-wl-toggle-spine="1" style="cursor:pointer;display:flex;align-items:center;gap:10px;flex-wrap:wrap;flex:1">'
        '    <span class="ts-badge chz-badge" style="background:rgba(56,189,248,0.18);border-color:rgba(56,189,248,0.55);color:#7dd3fc;font-size:12.5px;padding:3px 10px">&#128203; The List</span>'
        '    <span class="comms-pill sky" id="wlHeaderCounts" style="font-family:var(--mono);font-size:11.5px;font-weight:800;padding:2px 9px">%d Items on The List</span>'
        '    <span id="wlHeaderSubSummary" style="font-size:11.5px;color:#cbd5e1">%d Business &middot; %d Teaching &middot; %d Research &middot; %d Personal &middot; <span style="color:#6ee7b7">%d in Things Done</span></span>'
        '  </div>'
        '  <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">'
        '    <button type="button" class="tw-btn" id="btnWlPopulateCos" data-wl-populate-cos="1" style="border-color:rgba(16,185,129,0.55);color:#6ee7b7;font-weight:700" title="Steward (in Chief of Staff mode) populates What Is To Be Done in the Chief of Staff tile above directly from your priority order on The List">&#9889; Populate Chief of Staff</button>'
        '    <button type="button" class="ts-pill cos-expand-toggle" id="wlSpineCollapseBtn" aria-expanded="false" title="Click to open/expand or collapse The List tile">&#9662; Click to Expand (%d items)</button>'
        '  </div>'
        '</div>'
        '<div class="wl-body" id="wlSpineBody" hidden style="margin-top:8px;padding-top:8px;border-top:1px solid rgba(56,189,248,0.28)">'
        '  <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;margin-bottom:8px">'
        '    <div class="wl-cat-tabs" id="wlCatTabs" style="display:inline-flex;gap:4px;flex-wrap:wrap">'
        '      <button type="button" class="tw-btn on" data-wl-cat="all">All Active (<span id="wlCntAll">%d</span>)</button>'
        '      <button type="button" class="tw-btn" data-wl-cat="Business">&#128188; Business (<span id="wlCntBusiness">%d</span>)</button>'
        '      <button type="button" class="tw-btn" data-wl-cat="Teaching">&#127891; Teaching (<span id="wlCntTeaching">%d</span>)</button>'
        '      <button type="button" class="tw-btn" data-wl-cat="Research">&#128300; Research (<span id="wlCntResearch">%d</span>)</button>'
        '      <button type="button" class="tw-btn" data-wl-cat="Personal">&#127968; Personal (<span id="wlCntPersonal">%d</span>)</button>'
        '      <button type="button" class="tw-btn" data-wl-cat="archived">&#10003; Things Done (<span id="wlCntArchived">%d</span>)</button>'
        '    </div>'
        '    <span style="font-size:11px;color:#94a3b8">Click any single-line item below to expand its AI Cockpit &amp; Star Chart Goal dropdowns and steps</span>'
        '  </div>'
        '  <div class="wl-add-bar">'
        '    <input type="text" id="wlNewTileTitle" placeholder="Add a new item to The List (starts as a single-line tile)..." style="flex:1;min-width:210px;padding:5px 9px;border-radius:6px;border:1px solid #283548;background:#080d16;color:#f1f5f9;font-size:12px">'
        '    <select id="wlNewTileCat" style="padding:5px 8px;border-radius:6px;border:1px solid #283548;background:#080d16;color:#f1f5f9;font-size:11.5px" title="Category of sub-list">'
        '      <option value="Business">&#128188; Business</option>'
        '      <option value="Teaching">&#127891; Teaching</option>'
        '      <option value="Research">&#128300; Research</option>'
        '      <option value="Personal">&#127968; Personal &amp; Family</option>'
        '    </select>'
        '    <select id="wlNewTilePrio" style="padding:5px 8px;border-radius:6px;border:1px solid #283548;background:#080d16;color:#f1f5f9;font-size:11.5px" title="Order / Priority number on The List">'
        '      <option value="1">Order #1 (1st)</option>'
        '      <option value="2" selected>Order #2 (2nd)</option>'
        '      <option value="3">Order #3 (3rd)</option>'
        '      <option value="4">Order #4 (4th)</option>'
        '      <option value="5">Order #5 (5th)</option>'
        '    </select>'
        '    <button type="button" class="tw-btn" id="btnWlAddTopA1" style="border-color:rgba(244,63,94,0.55);background:rgba(244,63,94,0.18);color:#fda4af;font-weight:700">&#9889; Add as #1 (1st)</button>'
        '    <button type="button" class="tw-btn done" id="btnWlAddTile" style="font-weight:700">+ Add to The List</button>'
        '  </div>'
        '  <div class="wl-tiles-stack" id="wlTilesContainer">%s</div>'
        '</div>'
        '</section>'
    ) % (
        wl_json,
        len(active_tiles),
        cnt_bus,
        cnt_tch,
        cnt_res,
        cnt_per,
        len(arch_tiles),
        len(active_tiles),
        len(active_tiles),
        cnt_bus,
        cnt_tch,
        cnt_res,
        cnt_per,
        len(arch_tiles),
        "".join(init_rows),
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
    board = ('<div class="board">' + lane_html(ctx.get("lane"), ctx.get("resume_from") or "") + _proactive_triage_strip(ctx) + _working_list_spine_html(ctx) + _campaign_tile(ctx) + _seat_shelves(ctx) + _candidates_tile(ctx) + _projects_tile(ctx)
             + _desk_line(ctx) + _ruler(ctx) + _mothership_collab_html(ctx) + _terminal(ctx) + '</div>')
    page = (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>%s</title>%s'
        '<link rel="stylesheet" href="/static/steward-dialogue.css?v=%s"><link rel="stylesheet" href="/static/high-seat-page.css?v=%s">'
        '<script>window.ANCHOR_BOOT = {build_id: "%s", campaign_pid: "%s", auth_required: %s, logged_in: %s, steward: "%s", stamp: "%s", you: "%s", health: "%s"};window.ANCHOR_BOOT_META = {steward: "%s", stamp: "%s", you: "%s"};window.ANCHOR_TILES = {%s};</script></head>'
        '<body><div class="app">%s<div class="main">%s%s%s<div class="prefs">%s</div><div class="canvas">%s%s</div>'
        '<div class="foot">%s<span>A <b class="gwl-accent">Ghost World Labs</b> tool &middot; Powered by NextGen Nuclear &middot; AI Cockpit &middot; J.C. Liechty</span>'
        '<span>&mdash; every row on this page is read from a record; where nothing is connected or measured, it says so.</span></div></div></div>'
        '<link rel="stylesheet" href="/vendor/xterm/xterm.css"><script src="/vendor/xterm/xterm.js"></script>'
        '<script src="/steward-static/md.js?v=%s"></script><script src="/static/steward-dialogue.js?v=%s"></script><script src="/static/high-seat-page.js?v=%s"></script><script src="/static/cave-terminal.js?v=%s"></script></body></html>'
    ) % (esc(ctx["steward"]["high_seat_name"]), tab_icon_link(ctx["steward"].get("high_seat"), ctx["build"], anchor=False), esc(ctx["build"]), esc(ctx["build"]), esc(ctx["build"]), esc((ctx.get("campaign") or {}).get("pid") or ""), "true" if ctx.get("auth_required") else "false", "true" if ctx.get("logged_in") else "false",
         esc(ctx["steward"]["label"]), esc(str(ctx.get("stamp") or "")), esc(str(ctx.get("you") or HIS_NAME)), esc(str(ctx.get("health_sig") or "")), esc(ctx["steward"]["label"]), esc(str(ctx.get("stamp") or "")), esc(str(ctx.get("you") or HIS_NAME)), _tile_names(ctx), _rail(ctx), _masthead(ctx), _health_banner(ctx), _hdr(ctx),
         ctx.get("prefs_html") or "", board, _panel(ctx), _brand_img(ctx["build"], "gwl-m-icon.svg"), esc(ctx["build"]), esc(ctx["build"]), esc(ctx["build"]), esc(ctx["build"]))
    return page.replace('</head>', '<script src="/static/app-frame.js?v=%s"></script><link rel="stylesheet" href="/static/provider-setup.css?v=%s"></head>' % (esc(ctx["build"]), esc(ctx["build"]))).replace('</body>',
        '<script src="/static/provider-controls.js?v=%s"></script></body>' % esc(ctx["build"]))


try:
    import sys as _sys_mod
    import importlib as _il_mod
    for _mname in ("high_seat_core", "onboard_wizard", "website_portal", "desk", "desk_page", "mothership_collab", "steward_cockpit.campaign_say"):
        if _mname in _sys_mod.modules:
            _il_mod.reload(_sys_mod.modules[_mname])
    if "high_seat_core" in _sys_mod.modules:
        from high_seat_core import candidates_model as _cm_new
        candidates = _cm_new
except Exception:
    pass

