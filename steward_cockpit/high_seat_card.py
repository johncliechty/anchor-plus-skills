"""high_seat_card — a project card's parts on the High Seat, from the cockpit's own readers.

W2 of the High Seat plan (2026-09-26; trimmed by its Rabbit read). A card on the home opens in place
to what the cockpit shows for that project's root effort — Status (the same branch the cockpit's
status verb takes: a live engine's state into compose_status, else the persisted record), Next steps
(the live decision — the persisted decision record's question with its recommendation, else the
engine's open question, else the strip's wait — what it depends on as the record names it, the acts,
and the next three open steps sliced the way the tile slices them), Deliverables (the register, each
openable row linked through the deliverable-file route), Plan (the steps with the cockpit's mark
order and its Not done set) — composed here from the same Python readers the cockpit uses, so the
card and the cockpit cannot disagree. No model call, no bridge spawn; every open fetches afresh; an
effort without a steward record yields an honest line, never a blank.
"""
from __future__ import annotations

import html
import os
import re
import time
from urllib.parse import quote as _quote
from pathlib import Path

from . import steward_campaign as campaign

PARTS = ("status", "next", "deliverables", "plan", "brief")   # brief (W2e-2): the decision brief the tile opens to


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def _effort_dir(folder, rel=""):
    """The effort the card names, resolved ONLY through the cockpit's own discovery (``discover_efforts``: the project
    root when it carries a Face, plus one level of subfolders with their own Face, none retired in place) — the same
    guard the cockpit's routes use. Anything discovery does not list (a path, a dot-name, a foreign drive such as
    ``D:foo``, a plain subfolder) is None, and the card says "No steward record"."""
    folder = str(folder or "")
    rel = str(rel or "").strip()
    if not folder:
        return None
    try:
        efforts = campaign.discover_efforts(folder) or []
    except Exception:
        return None
    for e in efforts:
        if str((e or {}).get("rel") or "") == rel:
            return str(Path(folder) / rel) if rel else str(Path(folder))
    return None


def _no_record(pid, name):
    return ('<div class="cp-quiet">No steward record for %s yet &mdash; open the cockpit and stand it up. '
            '<a href="/project/%s" target="_blank" rel="noopener">Open cockpit</a></div>' % (esc(name), esc(pid)))


def _live_engine(cdir):
    """The engine the cockpit would use — the same map the status verb consults; None when none is awake."""
    try:
        from . import steward_routes as routes
        return routes.ENGINES.get(cdir)
    except Exception:
        return None


def _decision(cdir):
    """The effort's live decision, as the cockpit's panel reads it: the persisted decision record (question,
    recommendation, depends_on), else the engine's open question; ``found`` says whether a state entry existed."""
    try:
        from .steward_engine import _read_state_entry
        from .question_context import normalize_question_context
        entry = _read_state_entry(str(cdir))
    except Exception:
        entry = {}
    found = bool(entry)
    rec = normalize_question_context(entry.get("question_context")) if entry.get("question_context") else None
    if rec:
        return {"found": True, "question": rec.get("question") or "", "recommendation": rec.get("recommendation") or "",
                "depends_on": list(rec.get("depends_on") or [])}
    q = str(entry.get("open_question") or "").strip() if entry else ""
    return {"found": found, "question": q, "recommendation": "", "depends_on": []}


def _step_label(s):
    return (s.get("navigation") or {}).get("label") or s.get("name") or s.get("id") or ""


def _waits(s):
    """The cockpit's stepWaitsOnJohn, from structured facts only."""
    r = s.get("refinement") if isinstance(s.get("refinement"), dict) else None
    if r and r.get("phase") == "awaiting_review":
        return "awaiting your review"
    if r and r.get("phase") == "blocked":
        return "blocked"
    if s.get("status") == "blocked":
        return "blocked"
    if s.get("status") == "waiting":
        w = s.get("waiting_on")
        return (" ".join(str(w).split())[:90]) if w else "waiting"
    return ""


def _done(s):
    r = s.get("refinement") if isinstance(s.get("refinement"), dict) else None
    if r:
        return r.get("phase") == "done"
    return s.get("status") == "done"


def _kind_in_words(c, names):
    """One correction as a sentence he can judge: the step, what changes, why."""
    sid = str(c.get("step_id") or "")
    name = names.get(sid) or sid
    was = ((c.get("was") or {}).get("waiting_on") if isinstance(c.get("was"), dict) else None) or ""
    kind = str(c.get("kind") or "")
    if kind == "clear_wait":
        what = "clear its wait" + (' ("%s")' % esc(str(was)[:80]) if was else "")
    elif kind == "second_look":
        what = esc(str(c.get("note") or "needs a second look — its foundation changed"))   # shown, never written (Grok W4)
    else:
        fields = c.get("fields") if isinstance(c.get("fields"), dict) else {}
        what = "set " + ", ".join("%s = %s" % (esc(k), esc(str(v))) for k, v in fields.items()) if fields else esc(kind or "a correction")
    why = str(c.get("why") or "")
    return '<li><b>%s</b>: %s%s</li>' % (esc(name), what, (" &mdash; " + esc(why)) if why else "")


def repairs_html(cdir, pid, rel=""):
    """W4 (2026-09-28): the correction sets PROPOSED on this record and still waiting on his word — each set in
    words with accept and dismiss. Nothing inside approved work changes before he accepts the set (his Q2). Empty
    when none is open."""
    try:
        from steward_cockpit.repair import open_proposals as _open
        rm, _ = campaign._read_json(Path(cdir) / "roadmap.json")
        props = _open((rm or {}).get("roadmap_events"))
    except Exception:
        return ""
    if not props:
        return ""
    names = {str(st.get("id")): str(st.get("name") or st.get("id")) for st in ((rm or {}).get("roadmap_projection") or []) if isinstance(st, dict)}
    out = []
    for e in props:
        pid_ = str(e.get("proposal_id") or "")
        after = e.get("after") if isinstance(e.get("after"), dict) else {}
        corrections = [c for c in (e.get("corrections") or []) if isinstance(c, dict)]
        n = len(corrections)
        after_name = names.get(str(after.get("step_id") or ""), str(after.get("step_id") or "the acceptance"))
        pres = str(after.get("presentation_id") or "")
        out.append(
            '<div class="cp-repair" data-proposal="%s"><div class="cp-lead">&#9881; Proposed after %s%s: %d correction%s &mdash; nothing changes until your word</div>'
            '<ul class="cp-repair-list">%s</ul>'
            '<div class="cp-act"><button class="mini t-repair" data-disposition="accepted" data-proposal="%s" data-pid="%s" data-dir="%s">accept the set</button>'
            '<button class="mini t-repair" data-disposition="dismissed" data-proposal="%s" data-pid="%s" data-dir="%s">dismiss</button></div></div>'
            % (esc(pid_), esc(after_name), (" (%s)" % esc(pres)) if pres else "", n, "" if n == 1 else "s",
               "".join(_kind_in_words(c, names) for c in corrections) or "<li>an empty set</li>",
               esc(pid_), esc(pid), esc(rel), esc(pid_), esc(pid), esc(rel)))
    return "".join(out)


def _question(cdir, eng):
    """The open question as the cockpit shows it: from the live engine's state when one is awake, else the persisted
    question context; the fields the brief needs (question, recommendation, why, id, scope, reversible, undo)."""
    q = None
    try:
        if eng is not None:
            qs = (eng.state() or {}).get("pending_questions") or []
            q = qs[0] if qs else None
    except Exception:
        q = None
    if q is None:
        try:
            from .steward_engine import _read_state_entry
            from .question_context import normalize_question_context
            entry = _read_state_entry(str(cdir))
            q = normalize_question_context(entry.get("question_context")) if entry.get("question_context") else None
            if q is None and entry.get("open_question"):
                q = {"question": str(entry.get("open_question"))}
        except Exception:
            q = None
    return q if isinstance(q, dict) and q.get("question") else None


def _description(q, ask):
    """The sentences the question stands on: the steward's stake lines when it gave them, else the context's own
    sentences with the question and the recommendation left out (they have their own places)."""
    stake = [str(x).strip() for x in (q.get("stake") or []) if str(x).strip()]
    if stake:
        return " ".join(stake)
    ctx = " ".join(str(q.get("context") or "").split())
    if not ctx:
        return ""
    # a sentence is left out only when it IS the ask or the recommendation, verbatim (Grok's read of W2e-3: a prefix
    # match dropped real sentences and kept paraphrases; he opens the banner to read these)
    rec = str(q.get("recommendation") or "").strip().lower().rstrip(".!")
    ask_n = ask.strip().lower().rstrip("?.!")
    keep = []
    for sent in re.split(r"(?<=[.!?])\s+", ctx):
        low = sent.strip().lower().rstrip("?.!")
        if not low or low == ask_n or (rec and low == rec):
            continue
        keep.append(sent.strip())
        if len(keep) >= 3:
            break
    return " ".join(keep)


def brief_html(cdir, pid, rel=""):
    """W2e-2/3 (2026-09-30, his words): the decision brief the tile opens to. The ASK as the cockpit's banner — one
    line, the question the steward put to him (else the wait) — which opens to the description (the sentences the
    question stands on), the recommendation with one Accept and its why, the alternatives, and "talk about it"; under the banner
    the next step; the material to review as links on its own line under the dialogue's strip (W2e-5). The key
    material, never hunted for."""
    eng = _live_engine(cdir)
    m = campaign.read_map(cdir)
    hb = m.get("heartbeat") or {}
    wait = ""
    try:
        wait = campaign._real_wait((hb.get("human_wait") or "").split("\u00b7")[0].strip()) or ""
    except Exception:
        wait = str(hb.get("human_wait") or "").strip()
    q = _question(cdir, eng)
    links = []
    seen = set()
    if q:
        scope = q.get("authorization_scope") or q.get("scope") or {}
        for mem in (scope.get("members") or []) if isinstance(scope, dict) else []:
            path = str(mem.get("path") if isinstance(mem, dict) else mem or "").strip()
            if path and path not in seen:
                seen.add(path); links.append(_item_link({"path": path, "what": path.replace("\\", "/").rsplit("/", 1)[-1]}, pid, rel))
    try:
        items = (campaign.read_deliverables(cdir) or {}).get("items") or []
        for it in campaign.current_review_items(m, items) or []:
            key = str(it.get("path") or it.get("route") or it.get("what") or "")
            if key and key not in seen:
                seen.add(key); links.append(_item_link(it, pid, rel))
    except Exception:
        pass
    nxt = str(hb.get("next_recommended") or hb.get("why_next") or "").strip()
    ask = (str(q.get("question") or "").strip() if q else "") or wait
    out = ['<div class="cbrief%s">' % (" ask" if ask else "")]
    if ask:
        out.append('<button class="cb-ask" type="button" aria-expanded="false"><span class="cb-flag">%s</span><span class="cb-line">%s</span><span class="cb-caret">&#9662;</span></button>' % (
            "decision" if q else "needs you", esc(ask[:220])))
        body = []
        if q:
            desc = _description(q, ask)
            if desc:
                body.append('<div class="cb-desc">%s</div>' % esc(desc[:700]))
            if wait and wait.lower() not in ask.lower():
                body.append('<div class="cb-wait on">&#9873; %s</div>' % esc(wait))
            rec = str(q.get("recommendation") or "").strip()
            why = str(q.get("why") or "").strip()
            if rec:
                body.append('<div class="cb-rec"><button class="cb-accept" type="button" data-qid="%s" data-rec="%s">Accept the recommendation</button><span class="cb-rectext">%s%s</span></div>' % (
                    esc(str(q.get("id") or "")), esc(rec[:240]), esc(rec[:240]), (" &mdash; " + esc(why[:200])) if why else ""))
                if q.get("reversible") is True and q.get("undo"):
                    body.append('<div class="cb-auth">Reversible &middot; undo: %s</div>' % esc(str(q.get("undo"))[:120]))   # no duration the record does not carry (Grok W2e-3)
                elif q.get("reversible") is False:
                    body.append('<div class="cb-auth">Not reversible &middot; waits for you</div>')
            else:
                body.append('<div class="cb-rec dim">No recommendation given &mdash; talk about it below.</div>')
            for alt in (q.get("alternatives") or [])[:3]:
                body.append('<div class="cb-alt">or: %s</div>' % esc(str(alt)[:160]))
            if q.get("authorizes"):
                body.append('<div class="cb-auth">Authorizes: %s</div>' % esc(str(q.get("authorizes"))[:160]))
            if q.get("decide_by"):
                body.append('<div class="cb-auth">Decide by: %s</div>' % esc(str(q.get("decide_by"))[:80]))
        body.append('<a class="cb-talk" href="#" data-ask="%s">talk about it</a>' % esc(ask[:220]))
        out.append('<div class="cb-body" hidden>%s</div>' % "".join(body))
    else:
        out.append('<div class="cb-wait">Nothing waits on you here.</div>')
    if nxt:
        out.append('<div class="cb-next"><span class="k">Next</span>%s</div>' % esc(nxt[:200]))
    out.append('</div>')
    if links:   # W2e-5 (his word, 16:1x): the material to review is its own line under the dialogue's strip, always in view
        out.append('<div class="cmat"><span class="k">To review</span>%s</div>' % "".join('<span class="cb-link">%s</span>' % l for l in links[:6]))
    return "".join(out)


def status_html(cdir, pid, rel=""):
    eng = _live_engine(cdir)
    data = campaign.status_for_pane(cdir, eng.state() if eng is not None else None, live=eng is not None)   # W3c: the record NOW when no run is live
    facts = ((data.get("compact") or {}).get("facts") if isinstance(data.get("compact"), dict) else None) or []
    rows = "".join('<tr><th>%s</th><td>%s</td></tr>' % (esc(f.get("label")), esc(f.get("value")))
                   for f in facts if isinstance(f, dict) and f.get("label"))
    lead = data.get("lead_line") or campaign.lead_line(data.get("plan"))
    at = str(data.get("at") or "")
    stale = (" &middot; live" if eng is not None else
             ((" &middot; the record now; the last run %s" % esc(str(data.get("last_run_at"))[-16:])) if data.get("last_run_at") else " &middot; the record now; no run yet"))
    raw_wmap = [st for st in (data.get("work_map") or []) if isinstance(st, dict)]
    wmap = []
    for entry in raw_wmap:
        if isinstance(entry.get("steps"), list):
            wmap.extend(s for s in entry["steps"] if isinstance(s, dict))
        else:
            wmap.append(entry)
    raw_proj = data.get("project")
    if isinstance(raw_proj, dict):
        proj = "%d/%d steps done%s" % (
            int(raw_proj.get("steps_done") or 0),
            int(raw_proj.get("steps_total") or len(wmap)),
            (" · " + str(raw_proj["parts"])) if raw_proj.get("parts") else "",
        )
    else:
        proj = str(raw_proj or "")
    smap_html = ""
    if wmap or proj:
        items = []
        for st in wmap:
            st_status = str(st.get("status") or "").lower()
            wait_t = str(st.get("waiting_on_you") or st.get("waiting_on") or "").strip()
            is_done = st_status in ("done", "completed")
            is_wait = (not is_done) and (bool(wait_t) or st_status in ("waiting", "blocked"))
            is_act = (not is_done) and (not is_wait) and st_status in ("active", "in_progress")
            mark = "&#10003;" if is_done else ("&#9873;" if is_wait else ("&#9679;" if is_act else "&#9675;"))
            cls = "s-done" if is_done else ("s-waiting" if is_wait else ("s-active" if is_act else "s-planned"))
            name = esc(_step_label(st))
            note = (" &mdash; %s" % esc(wait_t[:60])) if (is_wait and wait_t and wait_t != "waiting") else (" (active)" if is_act else "")
            items.append('<li class="cp-step %s"><span class="cp-mark">%s</span> %s%s</li>' % (cls, mark, name, note))
        smap_html = ('<div class="cp-smap"><div class="cp-when"><b>Steward Map Status</b>%s</div>'
                     '<ul class="cp-steps">%s</ul></div>' % ((" &middot; " + esc(proj)) if proj else "", "".join(items)))
    return ('<div class="cp-status"><div class="cp-lead">%s</div><div class="cp-when">last update %s%s</div>'
            '<table class="cp-facts">%s</table>%s%s'
            '<div class="cp-foot"><a href="/project/%s" target="_blank" rel="noopener">Open cockpit</a></div></div>'
            % (esc(lead), esc(at[-16:]) if at else "unknown", stale, rows or '<tr><td>No status recorded yet.</td></tr>',
               smap_html, repairs_html(cdir, pid, rel), esc(pid)))


_EFFORT_DIRS = {}


def _effort_dir_of(pid, rel):
    """(effort dir or None, its registered paths/routes) - the same `registered` set the cockpit passes."""
    key = (pid, rel)
    hit = _EFFORT_DIRS.get(key)
    if hit and time.monotonic() - hit[2] < 30:
        return hit[0], hit[1]
    try:
        import rnd_registry
        folder = (rnd_registry.get_project(pid) or {}).get("folder_path") or ""
    except Exception:
        folder = ""
    d = os.path.join(folder, rel) if folder else None
    reg = set()
    if d:
        try:
            import deliverables_register as dr
            items = campaign.read_deliverables(d).get("items") or []
            reg = {str(i.get("path") or "").replace(chr(92), "/").lower() for i in items if isinstance(i, dict)}
            reg |= {(dr._canonical_route(i["route"]) or "").lower() for i in items if isinstance(i, dict) and i.get("route")}
        except Exception:
            reg = set()
    if len(_EFFORT_DIRS) > 256:
        _EFFORT_DIRS.clear()
    _EFFORT_DIRS[key] = (d, reg, time.monotonic())
    return d, reg


def _reading_href(it, pid, rel):
    """The register's reading URL for a card item: a URL, "" when the item has no reading copy (missing, outside,
    private, a deck still preparing), or None when it cannot be judged (no project folder) - then the caller's own
    link stands."""
    if not pid or not isinstance(it, dict) or not (it.get("path") or it.get("route")):
        return None
    edir, registered = _effort_dir_of(pid, str(rel or ""))
    if not edir:
        return None
    try:
        import deliverables_register as dr
        t = dr.reading_target(it, pid=pid, effort_rel=str(rel or ""), effort_dir=edir, registered=registered)
    except Exception:
        return None
    return t.get("read") or ""


def _item_link(it, pid, rel=""):
    """The cockpit's own link for a register row: a route stays a route; an openable path goes through the
    deliverable-file route IN THE EFFORT'S OWN DIRECTORY (2026-10-01, his "start here" and "review" errors: an effort
    card's links had dropped the directory, so the file was looked for at the project's root) - ``rel`` rides the call
    from the part being rendered (Grok's review: never a thread-local); an office file opens the cockpit's preview
    (view=1); anything else is text."""
    what = esc(it.get("what") or it.get("path") or "")
    route = str(it.get("route") or "")
    path = str(it.get("path") or "")
    # W3 (2026-10-10): the card reads a product the way the cockpit does - its ONE reading target from the register
    # (a deck through its bound PDF, a managed item with its hash, a missing or private file with no link) - before
    # the older hand-built link below
    read = _reading_href(it, pid, rel)
    if read is not None:
        return ('<a href="%s" target="_blank" rel="noopener">%s</a>' % (esc(read), what)) if read else what
    if route.startswith("/"):
        return '<a href="%s" target="_blank" rel="noopener">%s</a>' % (esc(route), what)
    if path and it.get("openable", True) and not path.startswith(("http://", "https://")):
        view = "&amp;view=1" if path.lower().endswith((".docx", ".pptx", ".xlsx")) else ""
        return '<a href="/api/steward/deliverable-file?pid=%s&amp;dir=%s&amp;path=%s%s" target="_blank" rel="noopener">%s</a>' % (
            esc(pid), esc(_quote(str(rel or ""), safe="")), esc(_quote(path, safe="/")), view, what)
    return what


def next_html(cdir, pid, rel=""):
    m = campaign.read_map(cdir)
    d = _decision(cdir)
    question, rec = d["question"], d["recommendation"]
    if not question:
        question = str((m.get("heartbeat") or {}).get("human_wait") or m.get("human_wait_face") or "").strip()
    try:
        items = (campaign.read_deliverables(cdir) or {}).get("items") or []
    except Exception:
        items = []
    current = campaign.current_review_items(m, items)
    acts = campaign.review_acts(m, current, cdir)
    by_what = {str(it.get("what") or "").strip().lower(): it for it in items}
    # W1 (2026-09-28): the ONE next-in-the-plan horizon (the cockpit renders the same list from the map) — the
    # declared focus, then what follows it; never a guess from the first active step; with no focus, empty (the
    # steward's reason is not his line — Grok W1)
    plan, _plan_why = campaign.next_in_plan(m, 3)
    out = ['<div class="cp-next">']
    if question:
        out.append('<div class="cp-q"><span class="k">Decide</span>%s%s</div>' % (
            esc(" ".join(str(question).split())[:400]),
            ('<div class="cp-rec"><span class="k">Recommended</span>%s</div>' % esc(" ".join(str(rec).split())[:240])) if rec else ""))
        if d["depends_on"]:
            out.append('<div class="cp-dep"><span class="k">Depends on</span>%s</div>' % " &middot; ".join(
                _item_link(by_what.get(n.lower()) or {"what": n, "route": "", "path": ""}, pid, rel) for n in d["depends_on"]))
    elif not acts:
        out.append('<div class="cp-quiet">Nothing waits on your word here%s.</div>' % ("" if d["found"] else " &mdash; no decision record for this effort"))
    if acts:
        out.append('<div class="cp-acts"><span class="k">Acts</span>%s</div>' % "".join(
            '<div class="cp-act"><b>%s</b> %s</div>' % (esc(a.get("act")), _item_link(a.get("item"), pid, rel) if a.get("item") else esc(a.get("label")))
            for a in acts[:6]))
    if plan:
        out.append('<div class="cp-plan"><span class="k">Next in the plan</span>%s</div>' % "".join(
            '<div class="cp-step">%s%s</div>' % (esc(_step_label(s)), (' <span class="dim">&middot; due %s</span>' % esc(s.get("due"))) if s.get("due") else "")
            for s in plan))
    out.append('<div class="cp-foot"><a href="/project/%s" target="_blank" rel="noopener">Open cockpit</a></div></div>' % esc(pid))
    return "".join(out)


def _node_html(node, pid, depth=0, current_ids=(), rel=""):
    """One work-stream node as the cockpit's Deliverables panel groups it: its mark, its label, its items (each openable
    through the deliverable-file route), then its children; a node whose work is all done folds closed."""
    mark = node.get("mark") or {}
    items = [it for it in node.get("items") or [] if it]
    rows = "".join('<div class="cp-deliv%s">%s<span class="dim">%s%s</span></div>' % (
        " current" if id(it) in current_ids or it.get("is_current") else "", _item_link(it, pid, rel),
        (" &middot; " + esc(campaign._item_summary(it))) if campaign._item_summary(it) else "",
        " &middot; awaiting your review" if (id(it) in current_ids or it.get("is_current")) else "") for it in items)
    more = ""
    kids = "".join(_node_html(c, pid, depth + 1, current_ids, rel) for c in node.get("children") or [])
    done = mark.get("cls") == "done"
    return ('<details class="cp-node d%d %s"%s><summary><span class="mk %s">%s</span>%s<span class="dim"> &middot; %d</span></summary>%s%s%s</details>' % (
        depth, esc(mark.get("cls") or "todo"), "" if done else " open", esc(mark.get("cls") or "todo"), esc(mark.get("glyph") or "&#9655;"),
        esc(node.get("label") or node.get("id") or "work"), len(items), rows or ('<div class="dim">nothing registered here yet</div>' if not kids else ""), more, kids))


def deliverables_html(cdir, pid, rel=""):
    """The cockpit's Deliverables organisation (John, 2026-09-11): current work and review first, a folded Approved list
    below it, then the whole work hierarchy by domain — the same view the cockpit's panel paints
    (steward_campaign.effort_deliverable_view)."""
    try:
        view = campaign.effort_deliverable_view(cdir)
    except Exception as e:
        return '<div class="cp-quiet">The register could not be read: %s</div>' % esc("%s: %s" % (type(e).__name__, e))
    items = view.get("items") or []
    if not items and not view.get("approved"):
        return '<div class="cp-quiet">No deliverables registered yet.</div>'
    current = view.get("current") or []
    cur_ids = {id(it) for it in current}
    out = ['<div class="cp-delivs">']
    out.append('<div class="cp-sec"><span class="k">Current work and review &middot; %d</span>%s</div>' % (
        len(current), "".join('<div class="cp-deliv current">%s<span class="dim">%s &middot; awaiting your review</span></div>' % (
            _item_link(it, pid, rel), (" &middot; " + esc(campaign._item_summary(it))) if campaign._item_summary(it) else "") for it in current)
        or '<div class="dim">Nothing is pinned for your review.</div>'))
    approved = view.get("approved") or []
    out.append('<details class="cp-fold"><summary><span class="k">Approved &middot; %d</span></summary>%s</details>' % (
        len(approved), "".join('<div class="cp-deliv">%s<span class="dim">%s</span></div>' % (
            _item_link(it, pid, rel), (" &middot; " + esc(it.get("date"))) if it.get("date") else "") for it in approved)
        or '<div class="dim">Nothing accepted yet.</div>'))
    streams = view.get("streams") or []
    out.append('<div class="cp-sec"><span class="k">All the work, by domain</span>%s</div>' % (
        "".join(_node_html(n, pid, 0, cur_ids, rel) for n in streams) or '<div class="dim">The plan has no domains yet.</div>'))
    out.append('<div class="cp-foot"><a href="/project/%s" target="_blank" rel="noopener">Open the register in the cockpit</a></div></div>' % esc(pid))
    return "".join(out)


def _why(s):
    """The words beside a flag: the cockpit's wait phrase, else the step's own waiting_on (an active step can carry one)."""
    return _waits(s) or " ".join(str(s.get("waiting_on") or "").split())[:90]


def _step_row(s, now_id):
    """A step as the cockpit marks it: ✓ done, ⚑ needs attention (the cockpit's own rule — a wait, a block, a review
    handoff, even on an active step), ● the current step, ▷ otherwise; the wait's words beside the flag."""
    if _done(s):
        g, cls = "&#10003;", "s-done"
    elif campaign._step_needs_attention(s):
        g, cls = "&#9873;", "s-waiting"
    elif s.get("id") == now_id:
        g, cls = "&#9679;", "now"
    else:
        g, cls = "&#9655;", "s-" + esc(s.get("status") or "planned")
    return '<div class="cp-step %s"><span class="mk">%s</span>%s%s%s</div>' % (
        cls, g, esc(_step_label(s)), (' <span class="dim">&middot; due %s</span>' % esc(s.get("due"))) if s.get("due") else "",
        (' <span class="dim">&middot; %s</span>' % esc(_why(s))) if _why(s) else "")


def _plan_node_html(node, now_id, depth=0):
    mark = node.get("mark") or {}
    steps = [s for s in node.get("steps") or [] if s.get("status") not in ("cancelled", "dropped")]
    done_n = sum(1 for s in steps if _done(s))
    kids = "".join(_plan_node_html(c, now_id, depth + 1) for c in node.get("children") or [])
    done = mark.get("cls") == "done"
    return ('<details class="cp-node d%d %s"%s><summary><span class="mk %s">%s</span>%s<span class="dim"> &middot; %d of %d done</span></summary>%s%s</details>' % (
        depth, esc(mark.get("cls") or "todo"), "" if done else " open", esc(mark.get("cls") or "todo"), esc(mark.get("glyph") or "&#9655;"),
        esc(node.get("label") or node.get("id") or "work"), done_n, len(steps), "".join(_step_row(s, now_id) for s in steps), kids))


def plan_html(cdir, pid):
    """The cockpit's Plan organisation (John, 2026-09-11): the domain hierarchy, each domain with the cockpit's mark
    (✓ all done · ▷ unfinished · ⚑ something waits on you), its steps marked the same way, done domains folded; then
    the Not-done list as the cockpit holds it, what waits on you first."""
    m = campaign.read_map(cdir)
    steps = [s for s in m.get("steps") or [] if s.get("status") not in ("cancelled", "dropped")]
    now_id = m.get("now_step_id")
    try:
        items = (campaign.read_deliverables(cdir) or {}).get("items") or []
    except Exception:
        items = []
    try:
        roots = (campaign.work_stream_model(m, items) or {}).get("roots") or []
    except Exception:
        roots = []
    tree = "".join(_plan_node_html(n, now_id) for n in roots) or "".join(_step_row(s, now_id) for s in steps)

    # Not done, as the cockpit holds it: not done and not held out (parked or supporting, unless it is the current step)
    def supporting(s):
        return ((s.get("navigation") or {}).get("role") == "support")

    def held_out(s):
        return (not _done(s)) and s.get("id") != now_id and (s.get("status") == "parked" or supporting(s))
    open_rows = [(i, s) for i, s in enumerate(steps) if not _done(s) and not held_out(s)]

    def rank(pair):
        i, s = pair
        return (0 if campaign._step_needs_attention(s) else 1 if s.get("id") == now_id else 2 if s.get("status") == "active" else 3, i)
    open_rows.sort(key=rank)
    notdone = "".join('<div class="cp-step"><span class="mk">%s</span>%s%s</div>' % (
        "&#9873;" if campaign._step_needs_attention(s) else ("&#9679;" if s.get("id") == now_id else "&middot;"), esc(_step_label(s)),
        (' <span class="dim">&middot; %s</span>' % esc(_why(s))) if _why(s) else "") for i, s in open_rows)
    done_n = sum(1 for s in steps if _done(s))
    return ('<div class="cp-planpane"><div class="cp-when">%d of %d steps done &middot; &#10003; done &middot; &#9655; unfinished &middot; &#9873; waits on you &middot; &#9679; now</div>'
            '<div class="cp-sec"><span class="k">The plan, by domain</span>%s</div>'
            '<div class="cp-notdone"><span class="k">Not done &middot; %d</span>%s</div>'
            '<div class="cp-foot"><a href="/project/%s" target="_blank" rel="noopener">Open the plan in the cockpit</a></div></div>'
            % (done_n, len(steps), tree, len(open_rows), notdone, esc(pid)))


def card_part(pid, part, folder, name="", rel=""):
    """One card part as HTML — ``{"ok", "pid", "part", "html"}``; unknown parts and missing records answer honestly.
    ``rel`` names the effort one folder down when the card reads one (home_rows.current_effort)."""
    part = str(part or "").strip().lower()
    if part not in PARTS:
        return {"ok": False, "pid": pid, "part": part, "error": "unknown part", "html": ""}
    cdir = _effort_dir(folder, rel)
    if cdir is None:
        return {"ok": True, "pid": pid, "part": part, "html": _no_record(pid, name or pid[:8])}
    try:
        fn = {"status": status_html, "next": next_html, "deliverables": deliverables_html, "plan": plan_html, "brief": brief_html}[part]
        return {"ok": True, "pid": pid, "part": part, "html": fn(cdir, pid, rel) if part in ("status", "brief", "next", "deliverables") else fn(cdir, pid)}
    except Exception as e:  # never a blank on the page
        return {"ok": True, "pid": pid, "part": part,
                "html": '<div class="cp-quiet">This part could not be read: %s</div>' % esc("%s: %s" % (type(e).__name__, e))}
