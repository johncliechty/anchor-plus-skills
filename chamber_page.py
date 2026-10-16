"""The steward chamber as a PAGE — the full-height surface, not a dock.

(2026-08-15, John) The chamber was drawn as a page, shipped as a tile, then
promoted to a section inside the legacy cockpit. Measured on his screen at
1600x1000, that left **446px of conversation** out of 1000: 231px of cockpit
header above the stage, and ~300px more of seal bar + progress bar + North Star
bar inside it. His words: *"it can't be little tiny windows… it's got to be
right there, and the content moves up to the top as it fills in."*

So this module renders the whole viewport. The chrome budget is **68px**:

    ┌ command bar ................................. 40px  (seal · steward ·
    │   project · progress · what's running · ETA · ⋯ · ←)
    ├ north-star line ............................. 28px
    ├ chamber ..................................... 1fr
    │   ├ flow rail .......... 300px, own scroll, collapsible
    │   └ conversation ....... 1fr
    │        ├ msgs .......... 1fr, own scroll, PINNED TO NEWEST
    │        ├ ⏱ strip ....... 32px  (the 10-minute status he says is missing)
    │        └ say box ....... 52px
    └──────────────────────────────────────────────────────

WHAT IS REUSED, DELIBERATELY: the rail, the steps, the run card, the
deliverable box and the message shapes are the SIGNED mockup's elements,
rendered by ``chamber_rail`` / ``chamber_open`` exactly as before — this module
only replaces the chrome around them and the page they sit on. The class
vocabulary the C9 differ knows is preserved throughout.

Pure string render: no IO, no spawn, no model, no write. Every interpolated
value is escaped through ``chamber_open._esc``.
"""
from __future__ import annotations

import chamber_open as copen
import chamber_rail as crail

SCHEMA = "chamber-page-v1"

_esc = copen._esc


# ── the command bar (dbar + progress, merged) ────────────────────────────────

def _cbar_html(view: dict, steward: dict | None, project: dict,
               fresh_state: dict | None = None) -> str:
    """One 40px row carrying what three bars carried: who the steward is, what
    campaign this is, how far along, what is running now, and the way out."""
    stw = steward or {}
    name = stw.get("label") or "Ecgberht"
    glyph = stw.get("glyph") or "\U0001f9ff"
    seat = stw.get("seat") or "claude"
    prog = view.get("progress") or {}
    done, total = prog.get("done") or 0, prog.get("total") or 0
    pct = int(round(100.0 * done / total)) if total else 0

    live = view.get("live_run")
    if live:
        run_now = "▶ %s · %s" % (live.get("skill") or "a run",
                                           live.get("step_id") or "a step")
        run_cls = "run-now live"
    else:
        nxt = copen._first_not_done(view.get("steps") or [])
        run_now = ("— idle · next: %s" % nxt.get("name")) if nxt \
            else "— idle · nothing queued"
        run_cls = "run-now"

    camp = (view.get("eta") or {}).get("campaign") or {}
    eta_label = camp.get("label") or ""
    eta_html = ('<span class="eta">%s</span>' % _esc(eta_label)) if eta_label else ""

    # (2026-08-15, John) He could not tell whether the page was showing him
    # today or last week, and there was no way to make it look again. Now the
    # bar says which, and the refresh is one click.
    fr = fresh_state or {}
    if fr.get("live"):
        fresh = ('<span class="fresh live" title="Someone appended to this '
                 'campaign %s — a steward session is running somewhere, '
                 'here or in a terminal">● live · talked %s</span>'
                 % (_esc(copen.humanize_age(fr.get("last_activity_s"))),
                    _esc(copen.humanize_age(fr.get("talked_s")))))
    else:
        fresh = ('<span class="fresh" title="Newest steward write to this '
                 'campaign">talked %s · plan %s</span>'
                 % (_esc(copen.humanize_age(fr.get("talked_s"))),
                    _esc(copen.humanize_age(fr.get("plan_s")))))
    stale = ('<button class="cbtn warn" data-refresh="1" title="What is drawn '
             'is older than the ledger on disk — recompute it">stale · '
             'refresh</button>') if fr.get("sidecar_stale") else (
        '<button class="cbtn" data-refresh="1" title="Recompute this '
        'campaign\'s view from the ledger on disk">↻</button>')
    # (2026-08-15, John: "some things from the M1 mockup — the very top line —
    # are not showing.") Checked against the signed drawing (mockups.html
    # §m1 dbar): the merged bar had dropped the "· steward of this project"
    # subtitle, the visible seat pill, and the "everything receipted" stamp,
    # demoting all three to a tooltip. They are drawn elements; they render.
    return (
        '<div class="cbar">'
        '%s'
        '<span class="ti">%s <small>· steward of this project</small></span>'
        '<span class="pill">seat: %s</span>'
        '<span class="proj" title="%s">%s</span>'
        '<div class="bar" title="%d of %d steps done">'
        '<b style="width:%d%%"></b></div>'
        '<span class="cnt">%d/%d</span>'
        '<span class="%s">%s</span>'
        '%s'
        '<span class="sp"></span>'
        '<span class="stamp">everything receipted</span>'
        '<button class="cbtn" data-status-overlay="1" title="The latest '
        '10-minute status table — or the honest idle state">⏱ status</button>'
        '<button class="cbtn" data-catch-up="1" title="Work happened outside '
        'this chamber? One steward turn: compare the record against reality '
        'and propose the roadmap updates — you confirm before anything is '
        'written">⟳ catch up</button>'
        '%s%s'
        '<span class="build" title="Server build serving this page — if this '
        'does not change after a restart, the browser is showing a cached '
        'page, not the server">%s</span>'
        '<button class="cbtn" data-page-menu="1" title="Project actions">⋯</button>'
        '<a class="cbtn" href="/" title="Back to the High Seat">←</a>'
        '</div>'
    ) % (_seal_html(stw), _esc(name), _esc(seat),
         _esc(project.get("folder_path") or ""), _esc(project.get("name") or ""),
         done, total, pct, done, total,
         run_cls, _esc(run_now), eta_html, fresh, stale,
         _esc((project.get('build') or 'chamber')))


def _seal_html(stw: dict) -> str:
    """The persona's seal — the lamp, the salver — not a generic glyph.
    (2026-08-15, John: "I missed having the seal… that logo icon.")"""
    src = (stw or {}).get("seal_src") or ""
    if src:
        return ('<img class="seal sealimg" src="%s" alt="" '
                "onerror=\"this.style.display='none'\"/>" % _esc(src))
    return '<div class="seal">%s</div>' % _esc((stw or {}).get("glyph") or "🧿")


# ── the seal strip — one tile per effort thread ─────────────────────────────

def _effstrip_html(efforts: dict | None, stw: dict) -> str:
    """(2026-08-15, John, third ask) One tile per seal. Click a tile, that
    effort's dialog opens; start a new one and work on something different in
    the same project. Threads over ONE campaign: the flow rail and the run
    queue stay shared, and the page warns before a second seal commissions
    while a run is live."""
    store = efforts or {}
    rows = [e for e in store.get("efforts") or []
            if isinstance(e, dict) and e.get("status") != "done"]
    active = store.get("active") or "campaign"
    tiles = []
    for e in rows:
        eid = str(e.get("id") or "")
        cls = "efftile"
        if eid == active:
            cls += " on"
        if e.get("status") == "parked":
            cls += " parked"
        tiles.append(
            '<button class="%s" data-effort="%s" title="%s">%s'
            '<span class="enm">%s</span></button>'
            % (cls, _esc(eid),
               _esc("Open this seal — its own conversation, the shared flow"
                    if eid != "campaign" else
                    "The project's own thread — every seal's turns also land "
                    "here (it is the audit trail)"),
               _seal_html(stw), _esc(e.get("name") or eid)))
    return (
        '<div class="effstrip">'
        '%s'
        '<button class="efftile new" data-effort-new="1" '
        'title="A new seal — its own conversation thread in this project">'
        '＋ new effort</button>'
        '</div>'
    ) % "".join(tiles)


# ── the north-star line ──────────────────────────────────────────────────────

def _north_html(view: dict) -> str:
    """28px. The objective, one ellipsized line — it was three stacked rows
    (goalbar + objective + blurb) saying substantially the same thing."""
    goal = view.get("goal") or {}
    text = (goal.get("text") or goal.get("goal") or "").strip()
    unread = bool(goal.get("unread"))
    if not text:
        # AG-GOAL-UNSET (signed lineage): honest, and it asks for the one thing
        # that unblocks everything else.
        return (
            '<div class="cnorth unset">'
            '<span class="lab">north star</span>'
            '<span class="txt">not set — tell the steward what you want '
            'to get done</span>'
            '<span class="sp"></span>'
            '<button class="cbtn" data-refine-overlay="1">Set the goal</button>'
            '</div>')
    return (
        '<div class="cnorth%s">'
        '<span class="lab">north star</span>'
        '<span class="txt" title="%s">%s</span>'
        '<span class="sp"></span>'
        '<button class="cbtn gold" data-still-goal="1">Still the goal</button>'
        '<button class="cbtn" data-refine-overlay="1">Refine it</button>'
        '</div>'
    ) % (" unread" if unread else "", _esc(text), _esc(text))


# ── the ⏱ status strip — the thing he says is missing ────────────────────────

def _strip_html(view: dict) -> str:
    """32px, always present, directly above the say box.

    THREE STATES, never ambiguous: something is running (and what it last
    said), nothing is running, or something WANTS HIM. The live text is
    refreshed client-side from ``/api/ecgberht/run_pulse``; this is the honest
    server-rendered floor so the strip is never blank on open."""
    live = view.get("live_run") or {}
    if live:
        skill = live.get("skill") or "a run"
        started = live.get("at") or "unknown time"
        latest = (live.get("latest_status") or "").strip()
        if latest:
            body = "%s · %s" % (skill, latest.splitlines()[0][:140])
        else:
            # Pre-emission: a run that has started but not yet emitted its
            # first ⏱ block. Saying so beats an empty strip.
            body = ("%s running · started %s · first ⏱ within 10m"
                    % (skill, started))
        return (
            '<div class="cstrip live" data-status-overlay="1" '
            'title="Open the full status">'
            '<span class="livedot">⏱</span>'
            '<span class="stxt">%s</span>'
            '<span class="sp"></span>'
            '<span class="more">status ›</span>'
            '</div>') % _esc(body)
    nxt = copen._first_not_done(view.get("steps") or [])
    tail = (" · next: %s · say the word to start it" % nxt.get("name")) \
        if nxt else ""
    return (
        '<div class="cstrip idle">'
        '<span class="livedot">—</span>'
        '<span class="stxt">idle · no step running%s</span>'
        '</div>') % _esc(tail)


# ── the conversation column ──────────────────────────────────────────────────

def _convo_html(view: dict, steward: dict | None) -> str:
    """The transcript, the strip and the say box. Messages carry the signed
    ``.msg.john`` / ``.msg.steward`` shapes; older turns fold behind one
    divider so a long campaign does not open on a 7,000px scroll."""
    stw = steward or {}
    name = stw.get("label") or "Ecgberht"
    turns = view.get("dialogue") or []
    recent = turns[-copen.CONVERSATION_RECENT:] if copen.CONVERSATION_RECENT else turns
    older = turns[:len(turns) - len(recent)]

    def _msg(turn) -> str:
        is_john = turn.get("role") == "john"
        return (
            '<div class="msg %s"><div class="who">%s</div>%s</div>'
            % ("john" if is_john else "steward",
               _esc("You" if is_john else name), _esc(turn.get("text"))))

    fold = ""
    if older:
        # Collapsed, not discarded — every turn stays reachable.
        fold = (
            '<div class="foldrow"><button class="foldbtn" data-unfold="1" '
            'data-fold-count="%d">⌃ %d earlier turn%s</button></div>'
            % (len(older), len(older), "" if len(older) == 1 else "s"))
        fold += '<div class="folded" hidden>%s</div>' % "".join(
            _msg(t) for t in older)

    body = "".join(_msg(t) for t in recent)
    if not turns:
        body = ('<div class="msg steward"><div class="who">%s</div>%s</div>'
                % (_esc(name), _esc(copen._brief_prose(view, name))))
    return (
        '<div class="convo">'
        '<div class="msgs">%s%s</div>'
        '%s'
        '<div class="saybox">'
        '<input data-say-input placeholder="Talk to %s — what do you want '
        'to get done?" />'
        '<button class="btn gold" data-say-send>Say it</button>'
        '</div>'
        '</div>'
    ) % (fold, body, _strip_html(view), _esc(name))


# ── the page ─────────────────────────────────────────────────────────────────

def render_chamber_page_html(view: dict, steward: dict | None = None,
                             project: dict | None = None,
                             freshness: dict | None = None,
                             efforts: dict | None = None) -> str:
    """The whole surface. Degraded projects get the SAME page — a missing
    projection makes the rail unreliable, it says nothing about whether he can
    hold a conversation, and a chamber he cannot talk to is worse than one with
    an honest rail."""
    project = project or {}
    deg = view.get("degraded")
    if deg:
        rail = (
            '<aside class="flow">'
            '<div class="railhd"><h3>The flow</h3></div>'
            '<div class="degrail">'
            '<span class="lab">first open</span>'
            '<span>This page has not been drawn for this project yet '
            '(%s). Rebuild reads what is on disk — no model calls, a few '
            'seconds.</span>'
            '<button class="btn gold" data-rebuild-command="%s">%s</button>'
            '</div>'
            '%s'
            '</aside>'
        ) % (_esc(", ".join(deg.get("reasons") or []) or "projections not built"),
             _esc((deg.get("rebuild") or {}).get("command") or ""),
             _esc((deg.get("rebuild") or {}).get("label") or "Rebuild"),
             copen._empty_rail_html())
    else:
        rail = crail._flow_html(view)
        if view.get("has_draft_steps"):
            # A scaffolding framed but never confirmed used to render as an
            # EMPTY rail (R-PROPOSED-EXCLUDED). It renders now — and says what
            # it is, which is the distinction that rule was actually for.
            n = sum(1 for s in view.get("steps") or [] if s.get("draft"))
            banner = (
                '<div class="draftban">'
                '<span class="lab">draft</span>'
                '<span>%d step%s proposed and not yet confirmed — '
                'say the word and they become the campaign</span>'
                '</div>'
            ) % (n, "" if n == 1 else "s")
            rail = rail.replace('<aside class="flow">',
                                '<aside class="flow">' + banner, 1)
    return (
        '<div class="cpage">'
        '%s%s%s'
        '<div class="chamber">%s%s</div>'
        '%s'
        '</div>'
    ) % (_cbar_html(view, steward, project, freshness), _north_html(view),
         _effstrip_html(efforts, steward or {}),
         rail, _convo_html(view, steward), _workbench_html())


# ── the workbench — the cockpit parts he actually uses, on THIS page ────────

def _workbench_html() -> str:
    """(2026-08-15, John) "I don't want to have to hit a button that says move
    me back to the cockpit, because then it loses all the functionality I have
    from the M1 dashboard."

    So the four things he named — a terminal he can drive himself instead of the
    steward, the Gandalf reads, the Boneyard, the files — live here, collapsed
    to a 30px strip until he opens one. Closed, it costs the conversation
    nothing; open, it takes the bottom third and the conversation keeps its
    scroll. Everything else the cockpit carried stays behind ?classic=1 until
    it earns a place or is deleted.
    """
    tabs = (
        ("terminal", "▮ Terminal", "A bare general session in this project — "
         "drive it yourself instead of the steward"),
        ("gandalf", "🧙 Gandalf", "Deep reads on this project"),
        ("files", "🗀 Files", "What this project has produced"),
        ("boneyard", "🪦 Boneyard", "Discarded material, searchable"),
    )
    btns = "".join(
        '<button class="wtab" data-wtab="%s" title="%s">%s</button>'
        % (_esc(key), _esc(tip), _esc(label)) for key, label, tip in tabs)
    return (
        '<div class="workbench" id="workbench">'
        '<div class="wbar">%s<span class="sp"></span>'
        '<button class="wclose" data-wclose="1" title="Close">▾</button></div>'
        '<div class="wbody" id="wbody"></div>'
        '</div>'
    ) % btns
