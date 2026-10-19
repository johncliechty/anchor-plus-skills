"""desk_page - the Desk page (John 2026-10-06, his mockup notes): "Small items" - one small-item cockpit working a
list - beside the Desk's substantial cockpits, each seatable On deck / Active in the Cave. Wears the Cave's own
stylesheet and masthead (his word: "comparable to the style of the entire Anchor project"); desk-page.css adds only
what the Cave has no class for. Pure render from the context ``anchor_gui.render_desk_page`` builds."""
from __future__ import annotations

from urllib.parse import quote as _quote

import high_seat_page as _hsp

esc = _hsp.esc
LIGHT_WORDS = {"orange": "needs you", "green": "working", "red": "a problem", "gray": "idle"}
STATE_LIGHT = {"waits": "orange", "working": "green", "quiet": "gray"}


def desk_icon(st):
    """The Desk's TAB picture for this persona - its pen (his pick, 2026-10-06: "single objects for the tab (pens)")."""
    return (st or {}).get("desk_icon") or (st or {}).get("high_seat") or ""


def desk_scene(st):
    """The Desk PAGE's picture for this persona - its working desk ("scenes for the page")."""
    return (st or {}).get("desk_scene") or desk_icon(st)


def _cockpit_href(pid, d):
    return "/steward/v1?pid=%s&amp;dir=%s" % (esc(pid), esc(_quote(d)))


def _small(ctx):
    pid = ctx["entry"]["id"]
    sm = ctx["desk"]["small"]
    rows = []
    for it in sm["items"]:
        lt = STATE_LIGHT.get(it.get("state"), "gray")
        rows.append((
            '<li class="ditem%s" data-item="%s"><span class="tlight %s" title="%s"></span>'
            '<label class="dtxt"><input type="checkbox" class="ddone" aria-label="done: %s"> %s%s</label>'
            '<button class="dbtn dpromote" title="this one is substantial - give it its own cockpit">Own cockpit &rarr;</button></li>'
        ) % (" waits" if lt == "orange" else "", esc(it["id"]), lt, esc(LIGHT_WORDS[lt]), esc(it["text"]), esc(it["text"]),
             ('<span class="dnote"> &middot; %s</span>' % esc(it["note"])) if it.get("note") else ""))
    body = "".join(rows) or '<li class="dempty">No small items. Add one above.</li>'
    lclass = sm["light"] if sm["light"] in LIGHT_WORDS else "gray"
    return (
        '<section class="dsec dsmall%s"><div class="dsec-h"><span class="tlight %s" title="%s"></span><h2>Small items</h2>'
        '<span class="dsub">one small-item cockpit for all of them</span><span class="sp"></span>'
        '<a class="t-go" href="%s" target="_blank" rel="noopener" title="Open the Small items cockpit">cockpit &#8599;</a></div>'
        '<div class="dstatus"><b>Status</b> &middot; %s</div>'
        '<form class="dadd" id="deskAdd"><label for="deskAddText">Add</label><input id="deskAddText" autocomplete="off" '
        'placeholder="a small admin item"><button class="dbtn primary" type="submit">Add</button></form>'
        '<ul class="dlist">%s</ul><div class="dfoot">Done %d &middot; one steward works the whole list; an item that grows '
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
            '<article class="dcard%s" data-dir="%s" data-ref="effort:%s/%s"><div class="dsec-h"><span class="tlight %s" title="%s"></span>'
            '<h3>%s</h3><span class="sp"></span><a class="t-go" href="%s" target="_blank" rel="noopener" title="Open the cockpit">cockpit &#8599;</a></div>'
            '<div class="dstatus"><b>Status</b> &middot; %s</div><div class="dacts">%s</div></article>'
        ) % (" ready" if lclass == "orange" else "", esc(c["dir"]), esc(pid), esc(c["dir"]), lclass, esc(LIGHT_WORDS[lclass]),
             esc(c["name"]), _cockpit_href(pid, c["dir"]), esc(c.get("why") or LIGHT_WORDS[lclass]), acts))
    body = "".join(cards) or '<p class="dempty">No cockpits yet. Start one for a substantial admin effort, or move a small item up.</p>'
    return (
        '<section class="dsec dcocks"><div class="dsec-h"><h2>Cockpits</h2><span class="dsub">substantial efforts only</span>'
        '<span class="sp"></span><form class="dadd inline" id="deskNew"><label for="deskNewName">New cockpit</label>'
        '<input id="deskNewName" autocomplete="off" placeholder="name the effort"><button class="dbtn primary" type="submit">+ Start</button></form></div>'
        '%s</section>'
    ) % body


def render_desk_html(ctx) -> str:
    b = ctx["build"]
    st = ctx.get("steward") or {}
    head = (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Desk</title>%s'
        '<link rel="stylesheet" href="/static/high-seat-page.css?v=%s"><link rel="stylesheet" href="/static/desk-page.css?v=%s">'
        '<script>window.ANCHOR_BOOT = {build_id: "%s", campaign_pid: "%s", desk_pid: "%s", auth_required: %s, logged_in: %s};</script></head>'
    ) % (_hsp.tab_icon_link(desk_icon(st), b, anchor=False), esc(b), esc(b), esc(b), esc(ctx.get("campaign_pid") or ""),
         esc(ctx["entry"]["id"]), "true" if ctx.get("auth_required") else "false", "true" if ctx.get("logged_in") else "false")
    if ctx.get("auth_required") and not ctx.get("logged_in"):
        return head + ('<body><div class="desk-wrap"><p class="dempty">The Desk opens once you are logged in: '
                       '<a href="/">log in on the Cave of Wonders</a>, then come back.</p></div></body></html>')
    desk = ctx["desk"]
    line = "%s &middot; Small items %d &middot; %d cockpit%s" % (
        ("%d wait%s on you" % (desk["waits"], "" if desk["waits"] == 1 else "s")) if desk["waits"] else "nothing waits on you",
        len(desk["small"]["items"]), len(desk["cockpits"]), "" if len(desk["cockpits"]) == 1 else "s")
    return head + (
        '<body><div class="desk-wrap">%s'
        '<div class="desk-h"><a class="desk-back" href="/">&larr; the Cave</a>%s<h1>Desk</h1><span class="dsub">admin, no project &middot; %s</span></div>'
        '<div class="desk-grid">%s%s</div>'
        '<div class="foot"><span>A <b class="gwl-accent">Ghost World Labs</b> tool &middot; Powered by NextGen Nuclear &middot; AI Cockpit &middot; J.C. Liechty</span></div>'
        '</div><script src="/static/desk-page.js?v=%s"></script></body></html>'
    ) % (_hsp._masthead({"build": b, "steward": st}), _hsp._brand_img(b, desk_scene(st), "desk-scene"), line,
         _small(ctx), _cockpits(ctx), esc(b))
