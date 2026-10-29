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

_OPEN = ("proposed", "planned", "active", "waiting")
_TIER_WORDS = {1: "do first", 2: "next in line", 3: "when there is room"}


HIS_NAME = "John"   # how a dialogue row names him on both pages, as the AI Cockpit does (his word, 2026-10-01)


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def _short(d):
    return _hr.short_date(d) if d else ""


# ── the Campaign record → initiatives with their parts ─────────────────────────────────────────

def campaign_initiatives(steps, resolved=None):
    """The Campaign's heading steps (each defines its own root group) with their parts.

    An initiative = a step that defines a root navigation group whose id is its own id (PLAN §3);
    its parts = the steps whose navigation path starts with that id. A part's kind comes from its
    ``ref`` prefix (project · step · deliverable · calendar) or is a native task; its text, state,
    date and link come from the resolver when it points at another record."""
    resolved = resolved or {}
    steps = [s for s in (steps or ()) if isinstance(s, dict)]
    heads = []
    for s in steps:
        nav = s.get("navigation") if isinstance(s.get("navigation"), dict) else {}
        groups = nav.get("groups") or []
        own = next((g for g in groups if isinstance(g, dict) and g.get("id") == s.get("id") and g.get("parent_id") is None), None)
        if own is not None:
            heads.append((s, own))
    out = []
    for s, own in heads:
        sid = s.get("id")
        parts = []
        for p in steps:
            if p is s:
                continue
            nav = p.get("navigation") if isinstance(p.get("navigation"), dict) else {}
            path = nav.get("path") or []
            if path and path[0] == sid:
                r = resolved.get(str(p.get("id"))) or {}
                ref = str(p.get("ref") or "")
                kind = ref.split(":", 1)[0] if ref else "task"
                state = r.get("state") or ("" if r.get("broken") else str(p.get("status") or ""))
                parts.append({
                    "id": p.get("id"), "kind": kind, "name": p.get("name") or "", "text": r.get("what") or p.get("name") or "",
                    "target": r.get("name") or "", "state": state, "date": r.get("date") or p.get("due") or "",
                    "pid": str(r.get("pid") or ""), "lead": str(r.get("lead") or ""), "dir": str(r.get("dir") or ""),
                    "href": r.get("href") or "", "status": str(p.get("status") or ""),
                    "target_status": str(r.get("target_status") or ""),
                    "broken": bool(r.get("broken")) if ref else False, "gap": r.get("gap") or "",
                    "waiting_on": str(p.get("waiting_on") or "") if not ref else "",
                    "needs_you": "waiting on you" in str(state).lower() or (
                        not ref and str(p.get("status") or "") == "waiting"
                        and bool(re.search(r"\b(john|you|me)\b", str(p.get("waiting_on") or "").lower()))),
                    # the seat (2026-09-30, his three levels): a component he works interactively — a cockpit, an
                    # effort, a desk item — sits in its goal (""), on deck, or active, in his order
                    "seat": str(p.get("seat")) if p.get("seat") in ("active", "deck") else "",
                    "seat_order": int(p["seat_order"]) if isinstance(p.get("seat_order"), int) else None,
                    "goal": sid, "goal_name": s.get("name") or sid,
                })
        # W1 (2026-09-28): a referenced part is closed when its RESOLVED target is — done, cancelled, dropped or
        # parked — not only when the wrapper's own status says so (Grok's live replay, 2026-09-27: a done target
        # stayed the open "next" part while its wrapper was planned). An unavailable target is broken: named, never
        # next. Every reader of a part (the light, the rows, the board's chips and ticks) reads these two flags,
        # never the wrapper's status alone (Grok W1).
        for p in parts:
            p["done"] = p["status"] == "done" or p["target_status"] == "done"
            p["closed"] = p["status"] in ("done", "parked") or p["target_status"] in ("done", "cancelled", "dropped", "parked")
        open_parts = [p for p in parts if not p["closed"] and not p["broken"]]
        dates = sorted(p["date"] for p in open_parts if p["date"])
        out.append({
            "id": sid, "name": s.get("name") or sid, "tier": int(s["tier"]) if s.get("tier") in (1, 2, 3) else None,
            "order": int((own or {}).get("order") or 0), "area": str(s.get("area") or ""),
            "done_when": s.get("done_when") or "", "status": s.get("status") or "",
            "if_then": str(s.get("if_then") or ""),      # the Star Chart's one if-then step, in his words (2026-10-03)
            "parts": parts, "next": open_parts[0] if open_parts else None,
            "needs": [p for p in parts if p["needs_you"]], "next_deadline": dates[0] if dates else "",
            "done_count": sum(1 for p in parts if p["done"]),
            # the pace he drives the goal toward (2026-09-29); the parts' progress. The goal itself has no seat: its
            # components do (his three levels, 2026-09-30)
            "pace": str(s.get("pace") or ""),
            "open_count": len(open_parts), "part_count": sum(1 for p in parts if not p["broken"]),
        })
    out.sort(key=lambda i: (i["tier"] or 9, i["order"], i["name"]))   # an untiered initiative sorts last, its tier shown as missing
    for n, i in enumerate(out, 1):
        i["number"] = n
    return out


INITIATIVE_KINDS = ("project", "effort", "task")   # a component he works interactively: a cockpit, an effort, a desk item


def is_initiative(part):
    return part.get("kind") in INITIATIVE_KINDS and not part.get("broken")


def part_name(part):
    """An initiative's own name: the project or effort it points at, else the desk item's words."""
    return str(part.get("target") or part.get("text") or "")


NOGOAL_ID = "__nogoal__"


def loose_initiative(steps, resolved=None):
    """The components with no goal yet - a cockpit or an effort put on the desk from the Candidates (2026-10-02) -
    as ONE hidden initiative (nogoal=True) so the shelves, the head and the pick-up see them; it is never drawn or
    counted as a goal. None when there are none."""
    steps = [s for s in (steps or ()) if isinstance(s, dict)]
    heads = {s.get("id") for s in steps for g in ((s.get("navigation") or {}).get("groups") or []) if isinstance(g, dict) and g.get("id") == s.get("id") and g.get("parent_id") is None}
    loose = []
    for s in steps:
        nav = s.get("navigation") if isinstance(s.get("navigation"), dict) else {}
        ref = str(s.get("ref") or "")
        if s.get("id") in heads or (nav.get("path") or []) or ref.split(":", 1)[0] not in ("project", "effort"):
            continue
        x = dict(s); x["navigation"] = {"path": [NOGOAL_ID]}
        loose.append(x)
    if not loose:
        return None
    head = {"id": NOGOAL_ID, "name": "no goal yet", "status": "active", "tier": 9, "order": 999,
            "navigation": {"groups": [{"id": NOGOAL_ID, "parent_id": None}]}}
    out = campaign_initiatives([head] + loose, resolved)
    if not out:
        return None
    out[0]["nogoal"] = True
    return out[0]


def goals_only(initiatives):
    """The goals - never the hidden no-goal group."""
    return [i for i in initiatives or () if not i.get("nogoal")]


def seated(initiatives, seat):
    """The components sitting in a seat — (goal, part) pairs in his order (seat_order; then the goal's tier and
    order; then the name). The one sort for Active and On deck (the head, the pick-up, the shelves)."""
    out = []
    for i in initiatives or ():
        for p in i.get("parts") or ():
            if p.get("seat") == seat and not p.get("closed"):
                out.append((i, p))
    return sorted(out, key=lambda t: (t[1].get("seat_order") if isinstance(t[1].get("seat_order"), int) else 999, t[0].get("tier") or 9, int(t[0].get("order") or 0), part_name(t[1]).lower()))


# ── an initiative's light, its one line, its status (the home's Campaign tile and the Campaign page share these) ──

LIGHTS = {"needs": ("&#9873;", "needs you"), "working": ("&#9679;", "working"), "waiting": ("&#9679;", "waiting"), "idle": ("&#9675;", "idle")}


def initiative_light(i, working=None):
    """One word for an initiative, read from its parts (John, 2026-09-27: "whether action is needed — working, waiting,
    idle"): ``needs`` when a part waits on him; ``working`` when a referenced project has a running session or a busy
    steward (``ctx["working"]``); ``waiting`` when an open part waits on something else; else ``idle``."""
    working = working or set()
    if i.get("needs"):
        return "needs"
    open_parts = [p for p in i.get("parts") or () if not p.get("closed", p.get("status") in ("done", "parked")) and not p.get("broken")]
    if any(p.get("pid") and p["pid"] in working for p in open_parts):
        return "working"
    if any(str(p.get("state") or "").startswith("waiting") or p.get("status") == "waiting" for p in open_parts):
        return "waiting"
    return "idle"


def initiative_line(i):
    """The one sentence a compact initiative tile carries (Grok R8: the action, not the part's name): when a part waits
    on him, the wait itself — a project part's "waiting on you: …" without its prefix, a native part's trigger, else
    the part's text; else the next open part; else what done looks like. Returns (html, kind)."""
    if i.get("needs"):
        p = i["needs"][0]
        state = str(p.get("state") or "")
        low = state.lower()
        if "waiting on you:" in low:
            words = state[low.index("waiting on you:") + len("waiting on you:"):].strip()
        elif p.get("waiting_on") and str(p["waiting_on"]).strip().lower() not in ("john", "you", "me"):
            words = "%s &mdash; %s" % (esc(p.get("text") or ""), esc(p["waiting_on"]))
            return "&#9873; " + words, "wait"
        else:
            words = ""
        text = esc(words) if words else esc(p.get("text") or p.get("target") or "")
        return "&#9873; " + text, "wait"
    nxt = i.get("next")
    if nxt:
        return "Next: " + esc(nxt.get("text") or "") + ((" &middot; " + esc(_short(nxt["date"]))) if nxt.get("date") else ""), "next"
    if i.get("done_when"):
        return "Done looks like: " + esc(i["done_when"]), "done"
    return "nothing open", "none"


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


# ── the ruler ──────────────────────────────────────────────────────────────────────────────────

def ruler_weeks(today):
    mon = today - timedelta(days=today.weekday())
    weeks = []
    for k in range(5):
        a = mon + timedelta(days=7 * k)
        b = a + timedelta(days=6)
        label = "%s–%d" % (_hr.short_date(a.isoformat()), b.day) if a.month == b.month else "%s–%s" % (_hr.short_date(a.isoformat()), _hr.short_date(b.isoformat()))
        weeks.append({"start": a, "end": b, "label": label, "name": "this week" if k == 0 else "week %d" % (k + 1)})
    return weeks


def ruler_markers(facts, today):
    """Every open dated step across the records, bucketed into the five weeks and beyond; a date
    already past sits in this week and says overdue."""
    weeks = ruler_weeks(today)
    buckets = {k: [] for k in range(5)}
    beyond, overdue = [], []
    for f in facts or ():
        if not isinstance(f, dict):
            continue
        for st in f.get("dated") or ():
            d = _hr._iso(st.get("due"))
            if d is None:
                continue
            m = {"date": st["due"], "name": st.get("name", ""), "project_id": f.get("id", ""),
                 "project_name": f.get("name", ""), "needs": bool(f.get("needs_you")),
                 "overdue": d < today, "label": _hr.due_label(st["due"], today)}
            if d < weeks[0]["start"]:
                overdue.append(m)          # before this Monday: overdue, not this week's delivery
                continue
            placed = False
            for k, w in enumerate(weeks):
                if w["start"] <= d <= w["end"]:
                    buckets[k].append(m); placed = True; break
            if not placed:
                beyond.append(m)
    for k in buckets:
        buckets[k].sort(key=lambda m: (m["date"], m["name"]))
    beyond.sort(key=lambda m: (m["date"], m["name"]))
    overdue.sort(key=lambda m: (m["date"], m["name"]))
    return weeks, buckets, beyond, overdue


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
        '<div id="cave-provider-controls" class="provider-controls" aria-label="Provider and quality for new work">'
        '<div><label for="cave-family">Provider</label><select id="cave-family" aria-label="Provider"></select></div>'
        '<div><label for="cave-account">Account</label><select id="cave-account" aria-label="Account"></select></div>'
        '<div><label for="cave-model">Model</label><select id="cave-model" aria-label="Model"></select></div>'
        '<div><label for="cave-effort">Reasoning</label><select id="cave-effort" aria-label="Reasoning"></select></div>'
        '<button id="cave-provider-apply" type="button">Apply to new work</button><button id="cave-provider-settings" type="button">Provider details / Setup</button>'
        '<p id="cave-provider-message" class="provider-control-message" role="status"></p></div>'
        '<details class="cap provider-history"><summary>Provider-wide Anchor observations</summary><div id="capList">%s</div></details>'
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
    return ('<div class="healthbar" role="alert"><span class="hb-mark">&#9888;</span><span class="hb-t"><b>%s</b> &middot; %s</span>'
            '<a class="tool" href="%s" target="_blank" rel="noopener">Diagnose</a>'
            '<button class="tool doctor" data-tool="doctor">&#10010; Anchor Doctor</button>'
            '<button class="tool" data-tool="zombie">%sZombie Hunter</button></div>') % (
        esc(r.get("text") or "Health check found issues"), esc(r.get("why") or ""), esc(href), _brand_img(ctx["build"], "zombie-hunter-radar.jpg"))


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
    # A seated component has its own Campaign name; the project is context, not its title.
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
    cockpit_href = "/steward/v1?pid=%s&amp;dir=%s" % (pid, esc(_quote(str(f.get("effort") or ""))))
    return (
        '<article class="tile%s" id="card-%s" data-tile="%s" data-dir="%s"%s><div class="t-top">%s<h3 class="t-name"><span class="t-nm">%s</span>%s</h3>'
        '<a class="t-go" href="%s" target="_blank" rel="noopener" title="Open the cockpit">cockpit &#8599;</a>%s</div><div class="t-face">%s'
        '%s<div class="t-more"><div class="t-desc">%s</div>%s</div></div>'
        '<div class="t-acts">%s</div>'
        '<div class="t-body" hidden></div></article>'
    ) % (cls, cid, pid, rel, attr, dot, name, ('<span class="t-eff">&middot; %s</span>' % esc(e.get("name"))) if step else (('<span class="t-eff">&middot; %s</span>' % rel) if rel else ""), cockpit_href, xbtn, goal_line,
         line, esc((e.get("blurb") or "").strip()[:220]) or "&mdash;", more_next, acts)



def _desk_line(ctx):
    return (
        '<section class="deskline" id="deskline"><div class="dl-row"><span class="dl-k">Desk</span><span class="dl-d">&middot; admin, no project</span>'
        '<button class="dchip" id="chipTasks" data-desk="tasks">Tasks &middot; <span id="taskTotal">%d</span></button>'
        '<span class="dl-sp"></span>%s</div>'
        '<div class="dl-body" id="deskBody"><p class="ptile-note">%s</p></div></section>'
    ) % (int(ctx.get("tasks_open") or 0),
         ('<a class="dl-open" href="/project/%s?view=desk" target="_blank" rel="noopener" title="the Desk view of the Campaign record">Open the Desk cockpit &rarr;</a>' % esc((ctx.get("campaign") or {}).get("pid")))
         if ctx.get("campaign") else '<span class="dl-open muted" title="The Desk reads the Campaign record, which is not stood up yet">Open the Desk cockpit &mdash; after the Campaign exists</span>',
         "The Desk reads the Campaign record&rsquo;s tasks; this old task list stays on the old dashboard until your word." if ctx.get("campaign")
         else "The task list still lives on the old dashboard until the Campaign exists.")


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
    return (
        '<section class="shelf" id="shDated"><div class="shelf-h"><h3>Dated deliveries</h3><span class="c">%d dated step%s</span><span class="rule"></span>'
        '<span class="note">Each marker is a dated open step in a project&rsquo;s record. Click one to balloon it open.</span></div>'
        '<div class="ruler" id="ruler"><div class="rl-head">%s</div><div class="rl-marks" id="rlMarks">%s</div></div>'
        '%s<div class="shelf-foot">Each marker points at the one card that owns it &mdash; no project has a second card.</div>'
        '<section class="cal" id="cal"><button class="cal-h" id="calHead"><span class="k">Calendar</span><span class="state">&middot; not connected</span>'
        '<span class="cal-tab" id="tabCal">Calendar</span><span class="cal-tab" id="tabMail">Email</span><span class="sp"></span><span class="tog" id="calTog">Open</span></button>'
        '<div class="cal-body" id="calBody"><p class="conn-zero">No account is connected, so there is nothing to show &mdash; nothing here is sample data. '
        'Connecting means two app registrations (Google, Microsoft) and a sign-in per account; Anchor would read before it ever writes, and every send or calendar change would ask you first.</p></div></section>'
        '</section>'
    ) % (total, "" if total == 1 else "s", head, "".join(cols), late)


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


def relevance(c, today, override=None):
    """The steward's relevance score (0-100) for a candidate, with its reasons (his word, 2026-10-02: "how likely the
    user is to want to/need to work on the project"). The steward's own score, when it has written one for this
    candidate (Campaign/.ecgberht/relevance.json), stands; else the record's: what waits on him, how near its date,
    its goal's tier, how recently it was worked, how long it has lain still."""
    if isinstance(override, dict) and isinstance(override.get("score"), (int, float)):
        return max(0, min(100, int(override["score"]))), str(override.get("why") or "the steward's own score")
    from datetime import date as _date
    score, why = 20, []
    if c.get("needs"):
        score += 35; why.append("waits on you")
    due = str(c.get("due") or "")
    if due:
        try:
            days = (_date.fromisoformat(due[:10]) - today).days
            if days < 0:
                score += 30; why.append("overdue")
            elif days <= 7:
                score += 22; why.append("due in %d day%s" % (days, "" if days == 1 else "s"))
            elif days <= 21:
                score += 10; why.append("due %s" % due[:10])
        except ValueError:
            pass
    tier = c.get("tier")
    if tier == 1:
        score += 15; why.append("a tier-1 goal")
    elif tier == 2:
        score += 7; why.append("a tier-2 goal")
    worked = str(c.get("worked") or "")
    if worked:
        try:
            ago = (today - _date.fromisoformat(worked[:10])).days
            if ago <= 3:
                score += 12; why.append("worked %s" % ("today" if ago == 0 else "%d day%s ago" % (ago, "" if ago == 1 else "s")))
            elif ago <= 14:
                score += 5; why.append("worked %d days ago" % ago)
            elif ago > 45:
                score -= 10; why.append("still for %d days" % ago)
        except ValueError:
            pass
    return max(0, min(100, score)), (", ".join(why) or "nothing presses")


def candidates(ctx):
    """Everything he could put on deck or make active (his word, 2026-10-02: "a tile that can be expanded, right below
    the on deck that shows all of the candidates -- those would be anything with an AI Cockpit as well as any open
    tasks/efforts, e.g. of an admin nature in the desk"): (1) the open components inside a goal with no seat yet - a
    cockpit, an effort, a desk item; (2) every AI cockpit (a project, or one of its efforts, with a steward record)
    that is not on the Campaign at all. Read from the page's own context; nothing new is read from disk."""
    inits = [i for i in ctx.get("initiatives") or () if i.get("status") not in ("done", "parked")]
    in_goal = []
    on_map = set()
    for i in ctx.get("initiatives") or ():
        for p in i.get("parts") or ():
            if p.get("kind") in ("project", "effort") and p.get("pid"):
                on_map.add((p["pid"], p.get("dir") or ""))
                if p.get("kind") == "project":
                    on_map.add((p["pid"], "*"))
    facts = ctx.get("facts") or {}
    today = ctx.get("today")
    if today is None:
        from datetime import date as _date
        today = _date.today()
    ev = ctx.get("campaign_step_dates") or {}
    over = ctx.get("relevance_override") or {}
    for i in goals_only(inits):
        for p in i.get("parts") or ():
            if p.get("kind") in KIND_LABEL and not p.get("seat") and not p.get("closed") and not p.get("broken"):
                made, touched = (ev.get(p.get("id")) or ("", ""))
                if p.get("pid") and facts.get(p["pid"], {}).get("folder"):
                    import os as _os
                    b, l = cockpit_dates(_os.path.join(facts[p["pid"]]["folder"], p.get("dir") or ""))
                    touched = max(touched or "", l or "")
                p["c_created"], p["c_worked"] = made, touched
                p["c_score"], p["c_why"] = relevance({"needs": p.get("needs_you"), "due": p.get("date"), "tier": i.get("tier"), "worked": touched},
                                                     today, over.get(p.get("id")))
                in_goal.append((i, p))
    camp = (ctx.get("campaign") or {}).get("pid")
    loose = []
    for e in ctx.get("entries") or ():
        pid = e.get("id")
        f = facts.get(pid) or {}
        if not pid or pid == camp or not f.get("has_record") or (pid, "*") in on_map:
            continue
        effs = [x for x in (f.get("efforts") or []) if isinstance(x, dict)]
        if not effs:
            if (pid, "") not in on_map:
                loose.append({"ref": "project:%s" % pid, "name": f.get("name") or e.get("name") or pid[:8], "where": "a project", "needs": bool(f.get("needs_you")), "folder": f.get("folder") or ""})
            continue
        for x in effs:
            rel = str(x.get("rel") or "")
            if (pid, rel) in on_map:
                continue
            nm = f.get("name") or e.get("name") or pid[:8]
            loose.append({"ref": ("effort:%s/%s" % (pid, _quote(rel))) if rel else ("project:%s" % pid),
                          "name": ("%s · %s" % (nm, x.get("name") or rel)) if rel else nm,
                          "where": ("an effort of %s" % nm) if rel else "a project", "needs": bool(x.get("needs_you")),
                          "folder": (f.get("folder") or "") + (("/" + rel) if rel else "")})
    for c in loose:
        c["created"], c["worked"] = cockpit_dates(c["folder"]) if c.get("folder") else ("", "")
        c["score"], c["why"] = relevance({"needs": c["needs"], "worked": c["worked"]}, today, over.get(c["ref"]))
    return in_goal, loose


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
    return (
        '<section class="exwrap cview" id="dialogue" data-dir="%s"><div class="exhead"><h3>%s &mdash; %s</h3><span class="exstate" id="exState" data-state="">&hellip;</span>'
        '<a class="note" href="/steward/v1?pid=%s&amp;dir=%s" target="_blank" rel="noopener" title="this conversation in its cockpit, full size">open in the cockpit &#8599;</a></div>'
        '<iframe class="cview-frame" src="%s" title="%s &mdash; %s"></iframe>'
        '<ul class="ex" id="exList" hidden></ul></section>'
        '<section class="delivbar" id="delivBar" data-pid="%s" data-dir="%s"><button class="db-h" id="delivToggle" type="button" aria-expanded="false" aria-controls="delivList">'
        '<span class="db-t">Deliverables</span><span class="db-c" id="delivCount">&hellip;</span><span class="db-caret">&#9662;</span></button>'
        '<ul class="db-list" id="delivList" hidden></ul></section>'
    ) % (esc(dir_), esc(label), esc(title), esc(camp_pid), esc(_quote(dir_)),
         src, esc(label), esc(title), esc(camp_pid), esc(dir_))


def _dialogue(ctx):
    """The steward's dialogue on the Cave of Wonders: the Cave's OWN conversation (2026-10-02, his word: one for the Cave,
    one for the Campaign), shown as the cockpit renders it (conversation_view). Nothing here without a Campaign."""
    if not ctx.get("campaign"):
        return ""
    return conversation_view(ctx["steward"]["label"], (ctx.get("campaign") or {}).get("pid") or "", "cave", CAVE_EFFORT, "the Cave of Wonders")


def mode_name(st):
    """The Campaign page's name in the steward's goals-and-foresight mode, per persona (John, 2026-10-03: Aladdin
    the Star Chart, Jarvis the Chart Room, Ecgberht the Beacon); every label that names that page says it."""
    return str((st or {}).get("campaign_name") or "Campaign")


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
        '<div class="comp-row"><span class="hint">Ctrl+Enter sends &middot; the Cave&rsquo;s steward answers above &middot; start a new project called &lt;name&gt; at &lt;folder&gt;</span><button class="send" id="sendBtn">Send</button></div>'
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
    board = ('<div class="board">' + lane_html(ctx.get("lane"), ctx.get("resume_from") or "") + _campaign_tile(ctx) + _seat_shelves(ctx) + _candidates_tile(ctx) + _projects_tile(ctx)
             + _desk_line(ctx) + _ruler(ctx) + _terminal(ctx) + '</div>')
    page = (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>%s</title>%s'
        '<link rel="stylesheet" href="/static/steward-dialogue.css?v=%s"><link rel="stylesheet" href="/static/high-seat-page.css?v=%s">'
        '<script>window.ANCHOR_BOOT = {build_id: "%s", campaign_pid: "%s", auth_required: %s, logged_in: %s, steward: "%s", stamp: "%s", you: "%s"};window.ANCHOR_TILES = {%s};</script></head>'
        '<body><div class="app">%s<div class="main">%s%s%s<div class="prefs">%s</div><div class="canvas">%s%s</div>'
        '<div class="foot">%s<span>A <b class="gwl-accent">Ghost World Labs</b> tool &middot; Powered by NextGen Nuclear &middot; AI Cockpit &middot; J.C. Liechty</span>'
        '<span>&mdash; every row on this page is read from a record; where nothing is connected or measured, it says so.</span></div></div></div>'
        '<link rel="stylesheet" href="/vendor/xterm/xterm.css"><script src="/vendor/xterm/xterm.js"></script>'
        '<script src="/steward-static/md.js?v=%s"></script><script src="/static/steward-dialogue.js?v=%s"></script><script src="/static/high-seat-page.js?v=%s"></script><script src="/static/cave-terminal.js?v=%s"></script></body></html>'
    ) % (esc(ctx["steward"]["high_seat_name"]), tab_icon_link(ctx["steward"].get("high_seat"), ctx["build"], anchor=False), esc(ctx["build"]), esc(ctx["build"]), esc(ctx["build"]), esc((ctx.get("campaign") or {}).get("pid") or ""), "true" if ctx.get("auth_required") else "false", "true" if ctx.get("logged_in") else "false",
         esc(ctx["steward"]["label"]), esc(str(ctx.get("stamp") or "")), esc(HIS_NAME), _tile_names(ctx), _rail(ctx), _masthead(ctx), _health_banner(ctx), _hdr(ctx),
         ctx.get("prefs_html") or "", board, _panel(ctx), _brand_img(ctx["build"], "gwl-m-icon.svg"), esc(ctx["build"]), esc(ctx["build"]), esc(ctx["build"]), esc(ctx["build"]))
    return page.replace('</head>', '<link rel="stylesheet" href="/static/provider-setup.css"></head>').replace('</body>',
        '<script src="/static/provider-controls.js"></script></body>')
