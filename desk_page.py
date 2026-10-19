"""desk_page - the Desk page (John 2026-10-06, his mockup notes; Wave 21 2026-10-19 polish):
"Small items" - one small-item cockpit working a list - beside the Desk's substantial cockpits, each seatable
On deck / Active in the Cave, plus the Unified Desk <-> Cave <-> Star Chart Triage & Cross-Mothership Collaboration
Strip and the embedded Aladdin - The Desk Steward panel with real Foundry icons.
Wears the Cave's own stylesheet and masthead; desk-page.css adds only what the Cave has no class for."""
from __future__ import annotations

from urllib.parse import quote as _quote

import high_seat_page as _hsp

esc = _hsp.esc
LIGHT_WORDS = {"orange": "needs you", "green": "working", "red": "a problem", "gray": "idle"}
STATE_LIGHT = {"waits": "orange", "working": "green", "quiet": "gray"}


def desk_icon(st):
    """The Desk's TAB picture for this persona - its pen (his pick, 2026-10-06: "single objects for the tab (pens)")."""
    return (st or {}).get("desk_icon") or "desk-tab-aladdin.png"


def desk_scene(st):
    """The Desk PAGE's picture for this persona - its working desk ("scenes for the page")."""
    return (st or {}).get("desk_scene") or "desk-scene-aladdin.jpg"


def _cockpit_href(pid, d):
    return "/steward/v1?pid=%s&amp;dir=%s" % (esc(pid), esc(_quote(d)))


def _desk_triage_and_mothership_strip(ctx):
    """Wave 21: Unified Ad-Hoc Triage & Cross-Mothership Collaboration strip at the top of the Desk."""
    desk = ctx["desk"]
    sm_items = desk["small"]["items"]
    sm_done = int(desk["small"].get("done") or 0)
    cocks = desk["cockpits"]
    seated_cnt = sum(1 for c in cocks if c.get("seat") in ("active", "deck"))
    waits_cnt = int(desk.get("waits") or 0)
    camp_pid = ctx.get("campaign_pid") or ""
    star_href = ("/project/%s" % esc(camp_pid)) if camp_pid else "/high-seat"

    ms = ctx.get("mothership") or {}
    ident = ms.get("identity") or {"id": "anchor-mothership", "label": "Local Mother Ship", "role": "lead"}
    peers = ms.get("peers") or []
    peer_summary = (
        "%d collaborator peer(s) registered (%s)"
        % (len(peers), ", ".join(esc(p.get("label") or p.get("id") or "Peer") for p in peers[:3]))
        if peers
        else "Ghost World Labs GitHub release synced (ghostworldlabs-anchor &middot; anchor-plus-skills)"
    )

    return (
        '<section class="desk-triage-strip" id="deskTriage" aria-label="Desk Triage and Cross-Mothership Collaboration">'
        '<!-- Row 1: Ad-Hoc & Admin Triage Cascade -->'
        '<div class="dt-row">'
        '<div class="dt-left">'
        '<img src="/vendor/brand/desk-tab-aladdin.png" class="dt-ico" alt="">'
        '<span class="dt-badge">AD-HOC &amp; ADMIN TRIAGE</span>'
        '<span class="dt-text">Small admin items stay in one fast list; substantial efforts promote to their own AI Cockpit and seat in the <a href="/high-seat">Cave of Wonders</a> or align with the <a href="%s">Star Chart</a>.</span>'
        '</div>'
        '<div class="dt-pills">'
        '<span class="dt-stat %s">Waiting on You <b>%d</b></span>'
        '<span class="dt-stat">Open Small Items <b>%d</b></span>'
        '<span class="dt-stat">Completed <b>%d</b></span>'
        '<span class="dt-stat">Substantial Cockpits <b>%d</b> (%d seated)</span>'
        '<button type="button" class="dbtn mini-act" id="btnDeskFilterAll" data-desk-filter="all">All</button>'
        '<button type="button" class="dbtn mini-act" id="btnDeskFilterWaits" data-desk-filter="waits">Needs You</button>'
        '<button type="button" class="dbtn mini-act" id="btnDeskDoneAll" title="Mark all open small items done">&#10003; Mark All Done</button>'
        '</div>'
        '</div>'
        '<!-- Row 2: Cross-Mothership Collaboration & Handoff Strip -->'
        '<div class="dt-row dt-mothership" id="deskMothershipStrip">'
        '<div class="dt-left">'
        '<img src="/vendor/brand/skill-foundry-icon.jpg" class="dt-ico" alt="">'
        '<span class="dt-badge ms">&#8644; MOTHERSHIP COLLABORATION</span>'
        '<span class="dt-text"><b>%s</b> &middot; %s &middot; Portable host-path-free cockpit handoff packets ready.</span>'
        '</div>'
        '<div class="dt-pills">'
        '<button type="button" class="dbtn mini-act" id="btnToggleMothershipDrawer">&#9881; Collaborators &amp; Handoff &#9662;</button>'
        '<a class="dbtn mini-act" href="/high-seat#mothershipCollab">Open Cave Mothership Hub &rarr;</a>'
        '</div>'
        '</div>'
        '<div class="dt-ms-drawer" id="deskMothershipDrawer" hidden>'
        '<div class="dt-ms-head">'
        '<strong>Cross-Mothership Collaboration &amp; Clean Release Channels</strong>'
        '<button type="button" class="dbtn mini-act" id="btnCloseMothershipDrawer">Close &#10005;</button>'
        '</div>'
        '<div class="dt-ms-grid">'
        '<div class="dt-ms-card">'
        '<div class="dt-ms-k">1. Clean GitHub Distribution</div>'
        '<div class="dt-ms-v"><code>johncliechty/ghostworldlabs-anchor</code> &amp; <code>johncliechty/anchor-plus-skills</code></div>'
        '<div class="dt-ms-sub">Data-free, PII-scrubbed Mother Ship code + Foundry skills ready for collaborator onboarding (<code>Anchor.exe</code>).</div>'
        '</div>'
        '<div class="dt-ms-card">'
        '<div class="dt-ms-k">2. Register Collaborator Mothership</div>'
        '<form class="dt-ms-form" id="deskPeerForm">'
        '<input id="deskPeerLabel" placeholder="Collaborator name (e.g. Merrill Mother Ship)" autocomplete="off">'
        '<input id="deskPeerEndpoint" placeholder="Git remote or Tailscale URL" autocomplete="off">'
        '<button type="submit" class="dbtn primary">+ Register Peer</button>'
        '</form>'
        '</div>'
        '</div>'
        '</div>'
        '</section>'
    ) % (
        star_href,
        "waits" if waits_cnt else "",
        waits_cnt,
        len(sm_items),
        sm_done,
        len(cocks),
        seated_cnt,
        esc(ident.get("label") or "Local Mother Ship"),
        peer_summary,
    )


def _small(ctx):
    pid = ctx["entry"]["id"]
    sm = ctx["desk"]["small"]
    rows = []
    for it in sm["items"]:
        lt = STATE_LIGHT.get(it.get("state"), "gray")
        rows.append((
            '<li class="ditem%s" data-item="%s" data-waits="%s"><span class="tlight %s" title="%s"></span>'
            '<label class="dtxt"><input type="checkbox" class="ddone" aria-label="done: %s"> %s%s</label>'
            '<button class="dbtn dpromote" title="this one is substantial - give it its own cockpit">Own cockpit &rarr;</button></li>'
        ) % (" waits" if lt == "orange" else "", esc(it["id"]), "1" if lt == "orange" else "0", lt, esc(LIGHT_WORDS[lt]), esc(it["text"]), esc(it["text"]),
             ('<span class="dnote"> &middot; %s</span>' % esc(it["note"])) if it.get("note") else ""))
    body = "".join(rows) or '<li class="dempty">No small items. Add one above or ask the Desk Steward on the right.</li>'
    lclass = sm["light"] if sm["light"] in LIGHT_WORDS else "gray"
    return (
        '<section class="dsec dsmall%s"><div class="dsec-h"><span class="tlight %s" title="%s"></span><h2>Small items</h2>'
        '<span class="dsub">one small-item cockpit for all of them</span><span class="sp"></span>'
        '<a class="t-go" href="%s" target="_blank" rel="noopener" title="Open the Small items cockpit">cockpit &#8599;</a></div>'
        '<div class="dstatus"><b>Status</b> &middot; %s</div>'
        '<form class="dadd" id="deskAdd"><label for="deskAddText">Add</label><input id="deskAddText" autocomplete="off" '
        'placeholder="a small admin item (e.g. Renew parking permit, Reply to Dean)"><button class="dbtn primary" type="submit">Add</button></form>'
        '<ul class="dlist" id="deskSmallList">%s</ul><div class="dfoot">Done %d &middot; one steward works the whole list; an item that grows '
        'becomes its own cockpit with one click.</div></section>'
    ) % (" ready" if lclass == "orange" else "", lclass, esc(LIGHT_WORDS[lclass]), _cockpit_href(pid, "Small items"),
         esc(sm.get("why") or LIGHT_WORDS[lclass]), body, int(sm.get("done") or 0))


def _cockpits(ctx):
    pid = ctx["entry"]["id"]
    cards = []
    for c in ctx["desk"]["cockpits"]:
        lclass = c["light"] if c["light"] in LIGHT_WORDS else "gray"
        seat = c.get("seat") or ""
        if seat:
            acts = ('<span class="dseat">%s in the Cave</span><button class="dbtn dback" data-step="%s">Back to the Desk</button>'
                    % ("Active" if seat == "active" else "On deck", esc(c.get("step") or "")))
        else:
            acts = ('<button class="dbtn dseatbtn" data-seat="deck">Seat On deck</button>'
                    '<button class="dbtn dseatbtn" data-seat="active">Seat Active</button>')
        cards.append((
            '<article class="dcard%s" data-dir="%s" data-ref="effort:%s/%s" data-waits="%s"><div class="dsec-h"><span class="tlight %s" title="%s"></span>'
            '<h3>%s</h3><span class="sp"></span><a class="t-go" href="%s" target="_blank" rel="noopener" title="Open the cockpit">cockpit &#8599;</a></div>'
            '<div class="dstatus"><b>Status</b> &middot; %s</div><div class="dacts">%s</div></article>'
        ) % (" ready" if lclass == "orange" else "", esc(c["dir"]), esc(pid), esc(c["dir"]), "1" if lclass == "orange" else "0",
             lclass, esc(LIGHT_WORDS[lclass]), esc(c["name"]), _cockpit_href(pid, c["dir"]), esc(c.get("why") or LIGHT_WORDS[lclass]), acts))
    body = "".join(cards) or '<p class="dempty">No cockpits yet. Start one for a substantial admin effort, or move a small item up.</p>'
    return (
        '<section class="dsec dcocks"><div class="dsec-h"><h2>Cockpits</h2><span class="dsub">substantial efforts only</span>'
        '<span class="sp"></span><form class="dadd inline" id="deskNew"><label for="deskNewName">New cockpit</label>'
        '<input id="deskNewName" autocomplete="off" placeholder="name the effort"><button class="dbtn primary" type="submit">+ Start</button></form></div>'
        '%s</section>'
    ) % body


def _desk_steward_panel(ctx):
    """Wave 21: Right-hand Aladdin - The Desk Steward panel with Foundry icons and sub-20ms deterministic command execution."""
    pid = ctx["entry"]["id"]
    st = ctx.get("steward") or {}
    st_label = esc(st.get("label") or "Aladdin")
    sm = ctx["desk"]["small"]
    cocks = ctx["desk"]["cockpits"]
    open_cnt = len(sm["items"])
    done_cnt = int(sm.get("done") or 0)
    cockpit_href = _cockpit_href(pid, "Small items")

    return (
        '<aside class="desk-steward" id="deskStewardPanel" aria-label="The Desk Steward">'
        '<div class="ds-head">'
        '<img src="/vendor/brand/desk-tab-aladdin.png" class="ds-ico" alt="">'
        '<span class="ds-title">%s &mdash; THE DESK</span>'
        '<a class="ds-open" href="%s" target="_blank" rel="noopener">open in the cockpit &#8599;</a>'
        '</div>'
        '<div class="ds-feed" id="deskStewardFeed">'
        '<div class="ds-msg steward">'
        '<div class="ds-who">%s &middot; Desk Steward</div>'
        '<div class="ds-body">'
        'Standing by on your Desk: <b>%d</b> open small item(s), <b>%d</b> completed, and <b>%d</b> substantial admin cockpit(s). '
        'Tell me to add an item, mark items done, promote an item into its own AI Cockpit, or start a new cockpit &mdash; '
        'I execute Desk actions immediately.'
        '</div>'
        '</div>'
        '</div>'
        '<div class="cos-foundry-bar" id="deskFoundryBar">'
        '<button type="button" class="cos-fbtn" data-desk-quick="Add small item: ">'
        '<img src="/vendor/brand/desk-tab-aladdin.png" alt=""><span>+ Small Item</span></button>'
        '<button type="button" class="cos-fbtn" data-desk-quick="Create a new cockpit for ">'
        '<img src="/vendor/brand/new-cockpit-icon.jpg" alt=""><span>+ New Cockpit</span></button>'
        '<button type="button" class="cos-fbtn" data-desk-quick="Triage my Desk items">'
        '<img src="/vendor/brand/brainstorm-icon.jpg" alt=""><span>Triage Desk</span></button>'
        '<button type="button" class="cos-fbtn" data-desk-quick="Mark all small items done">'
        '<img src="/vendor/brand/crucible-icon.svg" alt=""><span>&#10003; Clear Completed</span></button>'
        '</div>'
        '<form class="ds-composer" id="deskStewardForm">'
        '<textarea id="deskStewardInput" rows="2" placeholder="Tell %s what to do on the Desk: &ldquo;add Renew parking permit&rdquo;, &ldquo;create cockpit Travel November&rdquo;, &ldquo;mark all done&rdquo;&hellip;"></textarea>'
        '<div class="ds-send-row">'
        '<span class="ds-hint">Enter sends &middot; Sub-20ms deterministic Desk actions</span>'
        '<button type="submit" class="dbtn primary" id="deskStewardSend">Send</button>'
        '</div>'
        '</form>'
        '</aside>'
    ) % (st_label.upper(), cockpit_href, st_label, open_cnt, done_cnt, len(cocks), st_label)


def render_desk_html(ctx) -> str:
    b = ctx["build"]
    st = ctx.get("steward") or {}
    pid = ctx["entry"]["id"]
    camp_pid = ctx.get("campaign_pid") or ""
    star_href = ("/project/%s" % esc(camp_pid)) if camp_pid else "/high-seat"
    head = (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Desk</title>%s'
        '<link rel="stylesheet" href="/static/steward-dialogue.css?v=%s">'
        '<link rel="stylesheet" href="/static/high-seat-page.css?v=%s"><link rel="stylesheet" href="/static/desk-page.css?v=%s">'
        '<script>window.ANCHOR_BOOT = {build_id: "%s", campaign_pid: "%s", desk_pid: "%s", auth_required: %s, logged_in: %s};</script></head>'
    ) % (_hsp.tab_icon_link(desk_icon(st), b, anchor=False), esc(b), esc(b), esc(b), esc(b), esc(camp_pid),
         esc(pid), "true" if ctx.get("auth_required") else "false", "true" if ctx.get("logged_in") else "false")
    if ctx.get("auth_required") and not ctx.get("logged_in"):
        return head + ('<body><div class="desk-wrap"><p class="dempty">The Desk opens once you are logged in: '
                       '<a href="/">log in on the Cave of Wonders</a>, then come back.</p></div></body></html>')
    desk = ctx["desk"]
    line = "%s &middot; Small items %d &middot; %d cockpit%s" % (
        ("%d wait%s on you" % (desk["waits"], "" if desk["waits"] == 1 else "s")) if desk["waits"] else "nothing waits on you",
        len(desk["small"]["items"]), len(desk["cockpits"]), "" if len(desk["cockpits"]) == 1 else "s")
    nav_tools = (
        '<div class="desk-nav-tools">'
        '<a class="tool cave" href="/high-seat" title="Open the Cave of Wonders">'
        '<img src="/vendor/brand/aladdin-high-seat-cave.jpg?v=%s" class="w20-btn-ico" alt="">Cave of Wonders</a>'
        '<a class="tool star" href="%s" title="Open the Star Chart">'
        '<img src="/vendor/brand/campaign-aladdin-star-chart.jpg?v=%s" class="w20-btn-ico" alt="">Star Chart</a>'
        '<a class="tool doc" href="/doctor" title="Open Anchor Doctor">+ Anchor Doctor</a>'
        '<a class="tool zmb" href="/zombie-hunter" title="Open Zombie Hunter">'
        '<img src="/vendor/brand/zombie-hunter-reaper.jpg?v=%s" class="w20-btn-ico" alt="">Zombie Hunter</a>'
        '<a class="tool fnd" href="/foundry" title="Open Skill Foundry">'
        '<img src="/vendor/brand/skill-foundry-icon.jpg?v=%s" class="w20-btn-ico" alt="">Skill Foundry</a>'
        '<a class="tool cock" href="%s" target="_blank" rel="noopener" title="Open Small Items AI Cockpit">'
        '<img src="/vendor/brand/desk-tab-aladdin.png?v=%s" class="w20-btn-ico" alt="">Small Items &mdash; AI Cockpit</a>'
        '</div>'
    ) % (esc(b), star_href, esc(b), esc(b), esc(b), _cockpit_href(pid, "Small items"), esc(b))
    return head + (
        '<body><div class="desk-wrap">%s'
        '<div class="desk-h"><a class="desk-back" href="/">&larr; the Cave</a>%s<h1>Desk</h1>'
        '<span class="dsub">admin, no project &middot; %s</span>%s</div>'
        '%s'
        '<div class="desk-workspace">'
        '<div class="desk-grid">%s%s</div>'
        '%s'
        '</div>'
        '<div class="foot"><span>A <b class="gwl-accent">Ghost World Labs</b> tool &middot; Powered by NextGen Nuclear &middot; AI Cockpit &middot; J.C. Liechty</span></div>'
        '</div><script src="/static/desk-page.js?v=%s"></script></body></html>'
    ) % (_hsp._masthead({"build": b, "steward": st}), _hsp._brand_img(b, desk_scene(st), "desk-scene"), line,
         nav_tools, _desk_triage_and_mothership_strip(ctx), _small(ctx), _cockpits(ctx), _desk_steward_panel(ctx), esc(b))
