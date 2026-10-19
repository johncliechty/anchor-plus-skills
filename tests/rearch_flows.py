"""W2 — the five permanent Playwright regression flows (re-architecture 2026-07).

These are the **top-5 stateful browser flows** the frozen plan (W2 — Regression
Rails) manufactures as PERMANENT regression assets. They are plain callables —
each drives a real Chromium page against a live hermetic Anchor server and
asserts MACHINE-CHECKABLE pass conditions — so the W2 gate, the C1 extraction
gate (W4–W6), and every later pillar can re-run the SAME flows unchanged:

  1. ``flow_terminal_open_and_type``  — terminal open + typed-char round-trip
     via the stub PTY (session chip → inline panel → xterm echo);
  2. ``flow_pending_paste_flush``     — v10 advance delivers the next-stage
     prompt as a pending paste, flushed after the greet, PASTED-but-UNSENT;
  3. ``flow_drag_to_group``           — v9 drag a project row onto a dashboard
     folder → Option-C dialog → "Just group" (grouped, NO disk move);
  4. ``flow_maximize_restore``        — v6 panel ▢ maximize (fills viewport +
     terminal re-fit) then restore (re-fit back);
  5. ``flow_dock_click``              — v12 Layout-D effort-tile click → the
     bottom dock opens BOUND to that effort/session with the transport OPEN.

Conventions (identical to the proven per-wave Playwright tests these flows are
distilled from — test_window_controls_v6 / test_advance_paste_ui_v10 /
test_project_move_v9 / test_layoutd_live_playwright_v12):

- DEV-ONLY. Playwright is NEVER imported by product code; callers gate with
  ``pytest.importorskip("playwright.sync_api")`` and own the browser/page.
- Hermetic. Callers own the server fixture (tmp ANCHOR_DATA_DIR, stub PTY,
  fake runner, OS-assigned port != 8777) — the flows only DRIVE and ASSERT.
- Product modules are imported LAZILY inside each function so the callers'
  module-reload fixtures always win (never a stale module binding).
"""
import time

# The model greet the stub PTY never produces on its own (the fake runner is
# not a real model): flow 2 injects it, exactly like production's real greet,
# to trigger the one-time pending-paste flush. Same line the v10 UI test uses.
GREET_LINE = "✓ Crucible loaded — what would you like to do?"


# ──────────────────────────────────────────────────────────────────────────
# backend prep helpers (used by the flow callers to stage hermetic state)
# ──────────────────────────────────────────────────────────────────────────

def git_init(folder):
    """A minimal committed git repo so start_session can mint a worktree."""
    import subprocess
    folder.mkdir(parents=True, exist_ok=True)
    for args in (["init", "-b", "main"], ["config", "user.email", "t@t"],
                 ["config", "user.name", "t"]):
        subprocess.run(["git"] + args, cwd=str(folder),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    (folder / "README.md").write_text("# w2 flows\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(folder),
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(folder),
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return folder


def mkproject(folder, name, scaffold=False):
    """Register a throwaway R&D project rooted at ``folder``."""
    import rnd_registry
    return rnd_registry.add_project(name, str(folder), scaffold=scaffold)


def start_live_session(pid, lane="research", effort_managed=False):
    """Start a live stub-PTY session; returns its registry record."""
    import terminal_session as ts
    return ts.start_session(pid, lane, effort_managed=effort_managed)


def research_session_with_doc(pid, repo):
    """A LIVE research session + a persisted report doc tagged to it.

    Flow 2's staging: the doc gives the advance's NEXT-PROMPT a real path to
    name (the discriminating paste-only token). This is the v10 UI test's
    prompt-building-given-persisted-docs staging; the worktree-only LIVE
    advance path keeps its own dedicated coverage
    (test_advance_research_to_plan_live_v11 + the v11 healthcheck walk — the
    v11 lesson), which this regression rail does not replace.
    """
    import terminal_session as ts
    import effort_history as eh
    rec = ts.start_session(pid, "research")
    sid = rec["session_id"]
    rel = "research/run-1/REPORT.md"
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# W2 flow report\n## Findings\nAdequate.\n",
                 encoding="utf-8")
    jid = eh.discovered_job_id("research", rel)
    eh.record_effort(repo, pid, "research", jid, skill="researchPrime",
                     extra={"source": eh.SOURCE_DISCOVERED, "kind": "report",
                            "title": "W2 flow report", "artifact_path": rel,
                            "status": "imported", "session_id": sid})
    return sid, rel


def kill_quietly(session_id):
    """Best-effort stub-session reap for flow teardown."""
    import terminal_session as ts
    try:
        ts.kill(session_id)
    except Exception:
        pass


def open_workbench(pg):
    """Expand the project window's Workbench tile (2026-07-30: it now opens
    COLLAPSED, so a project window lands on the summary, not a wall of lanes).
    Clicks the summary's click-to-expand affordance — the same gesture a user
    makes — so the lane board / session bar / panel stack become visible. A
    no-op when the tile is already open (or absent, e.g. an older shell)."""
    from tests.ui_helpers import expand_workbench
    expand_workbench(pg)


def _panel_term_dims(pg, sid):
    return pg.evaluate(
        "(sid)=>{var w=window.PANELS&&window.PANELS[sid];"
        "var t=w&&w.term;return t?{cols:t.cols,rows:t.rows}:null;}", sid)


# ──────────────────────────────────────────────────────────────────────────
# flow 1 — terminal open + type (stub PTY round-trip)
# ──────────────────────────────────────────────────────────────────────────

def flow_terminal_open_and_type(pg, base, pid, sid, text="Zq"):
    """Open a live session's inline panel from its session-bar chip, type into
    the terminal, and prove the typed chars ROUND-TRIP through the stub PTY
    (echo) back into the xterm scrollback buffer."""
    pg.goto(f"{base}/project/{pid}", wait_until="networkidle")
    open_workbench(pg)  # the workbench tile now opens collapsed
    chip = f'#sessionBar .live-chip[data-session="{sid}"]'
    pg.wait_for_selector(chip, timeout=8000)
    pg.click(chip)
    panel = f'#panelStack .panel[data-session="{sid}"]'
    pg.wait_for_selector(panel, timeout=6000)
    # the xterm mounts inside the panel's terminal host.
    pg.wait_for_selector(f"{panel} .term-host .xterm", timeout=8000)
    # type into the focused terminal; the stub PTY echoes the input, so the
    # chars must appear in the xterm buffer (a full client→PTY→client trip).
    pg.evaluate(
        "(sid)=>{var w=window.PANELS&&window.PANELS[sid];"
        "if(w&&w.term)w.term.focus();}", sid)
    pg.keyboard.type(text)
    pg.wait_for_function(
        "a=>{var w=window.PANELS&&window.PANELS[a[0]];"
        "if(!w||!w.term)return false;var b=w.term.buffer.active;"
        "for(var i=0;i<b.length;i++){var l=b.getLine(i);"
        "if(l&&l.translateToString(true).indexOf(a[1])>=0)return true;}"
        "return false;}",
        arg=[sid, text], timeout=8000)


# ──────────────────────────────────────────────────────────────────────────
# flow 2 — pending-paste flush (advance → pasted-but-UNSENT)
# ──────────────────────────────────────────────────────────────────────────

def flow_pending_paste_flush(pg, base, pid, doc_rel):
    """Advance a research session → the new linked planning panel receives the
    generated next-stage prompt as a v10 PENDING PASTE: held until the model
    greet, then flushed into the input line UNSENT (no trailing newline, no
    auto-submitted turn). Returns the new planning session id.

    ``doc_rel`` is the persisted research doc path (the paste-only
    discriminating token — it never appears in the echoed phase-1 seed).
    """
    import session_registry as reg
    import pty_manager

    pg.goto(f"{base}/project/{pid}", wait_until="networkidle")
    open_workbench(pg)  # the workbench tile now opens collapsed
    pg.wait_for_selector("#sessionBar .live-chip", timeout=8000)
    pg.eval_on_selector_all("#sessionBar .live-chip",
                            "els=>els.forEach(e=>e.click())")
    pg.wait_for_selector("#panelStack .panel .advbtn", timeout=8000)

    before = {r["session_id"] for r in reg.list_sessions(project_id=pid)
              if r.get("lane") in ("plan", "planning")}
    pg.click("#panelStack .panel .advbtn")

    # the advance mints the linked planning session server-side. The advance
    # POST runs concurrently with this poll and does REAL git work before the
    # planning session registers — two commits (persist the source docs into
    # main so they ride into the new worktree off HEAD) plus a `git worktree
    # add`. Under a loaded gate (Chromium up, hundreds of prior tests, a hot
    # Windows box with AV file-scanning) that can outrun a 4s budget, so poll
    # for ~12s. The session IS created server-side before the POST responds;
    # this only widens the wait, it does not relax any assertion.
    new_sid = None
    for _ in range(240):
        fresh = [r["session_id"] for r in reg.list_sessions(project_id=pid)
                 if r.get("lane") in ("plan", "planning")
                 and r["session_id"] not in before]
        if fresh:
            new_sid = fresh[0]
            break
        time.sleep(0.05)
    assert new_sid, "advance did not create a planning session"

    # the record HOLDS the prompt (registered first, paste set in a follow-up
    # update — poll for it; the intent is unchanged: held, not sent).
    prompt = ""
    for _ in range(240):
        prec = reg.get_session(new_sid) or {}
        prompt = prec.get("pending_paste") or ""
        if prompt:
            break
        time.sleep(0.05)
    assert prompt, "advanced planning session has no pending paste"
    assert doc_rel in prompt, "paste should reference the persisted doc"
    assert prec.get("paste_flushed") is False
    # test invariant: the doc path is PASTE-ONLY (absent from the echoed seed),
    # so its later appearance in the terminal PROVES the flush, not the seed.
    assert doc_rel not in (prec.get("seed_text") or "")

    # the pending-paste hint banner renders on the new panel.
    pg.wait_for_selector(".pendpaste-hint", timeout=6000)

    # inject the greet ONLY once the new panel's transport is attached and
    # pumping reads (the echoed skill-load seed visible in the SCROLLBACK
    # buffer proves a completed read cycle) — the flush fires on the next read
    # AFTER the greet, so this ordering is what de-flakes the flow.
    pg.wait_for_function(
        "sid=>{var w=window.PANELS&&window.PANELS[sid];"
        "if(!w||!w.term)return false;var b=w.term.buffer.active;"
        "for(var i=0;i<b.length;i++){var l=b.getLine(i);"
        "if(l&&l.translateToString(true).indexOf('Load the Crucible')>=0)"
        "return true;}return false;}",
        arg=new_sid, timeout=10000)
    pty_manager.write(new_sid, GREET_LINE)

    # source of truth first: the flush CLAIMS the paste (paste_flushed=True)
    # before writing bytes — poll the registry, then assert the render.
    flushed = False
    for _ in range(160):  # ~8s
        r = reg.get_session(new_sid)
        if r and r.get("paste_flushed") is True:
            flushed = True
            break
        time.sleep(0.05)
    assert flushed, "pending paste was not flushed (paste_flushed never True)"

    # POSITIVE: the paste-only token is visible in the terminal.
    pg.wait_for_function(
        "a=>{var h=document.querySelector('#panelStack .panel[data-session=\"'"
        "+a[0]+'\"] .term-host');return !!h&&h.textContent.indexOf(a[1])>=0;}",
        arg=[new_sid, doc_rel], timeout=10000)

    # NEGATIVE (UNSENT): nothing rendered on a row after the paste, and the
    # cursor rests ON the paste row — a submit would have advanced it below.
    neg = pg.evaluate(
        """(a) => {
          var sid = a[0], token = a[1];
          var w = window.PANELS && window.PANELS[sid];
          if (!w || !w.term) return {ok:false, reason:'no-term'};
          var buf = w.term.buffer.active;
          var cy = buf.baseY + buf.cursorY;
          var lastPaste = -1, sawSubmittedAfter = false;
          for (var i = 0; i < buf.length; i++) {
            var line = buf.getLine(i);
            if (!line) continue;
            if (line.translateToString(true).indexOf(token) >= 0) lastPaste = i;
          }
          for (var j = lastPaste + 1; j < buf.length; j++) {
            var ln = buf.getLine(j);
            if (ln && ln.translateToString(true).trim().length > 0)
              sawSubmittedAfter = true;
          }
          return {ok:true, cursorRow:cy, pasteRow:lastPaste,
                  sawSubmittedAfter:sawSubmittedAfter};
        }""", [new_sid, "REPORT.md"])
    assert neg.get("ok"), f"could not read xterm buffer: {neg}"
    assert neg["pasteRow"] >= 0, "pasted prompt row not found in xterm"
    assert neg["sawSubmittedAfter"] is False, \
        "content rendered AFTER the paste row — the prompt was auto-submitted"
    assert neg["cursorRow"] == neg["pasteRow"], \
        "cursor below the paste row — a newline was submitted (auto-run)"

    # backend corroboration: flushed once, pending cleared.
    final = reg.get_session(new_sid)
    assert final["paste_flushed"] is True
    assert final["pending_paste"] == ""
    return new_sid


# ──────────────────────────────────────────────────────────────────────────
# flow 3 — drag-to-group (Option-C dialog → "Just group", no disk move)
# ──────────────────────────────────────────────────────────────────────────

def flow_drag_to_group(pg, base, pid, group="Research"):
    """Home dashboard: create a folder, drop a project row onto its header →
    the Option-C dialog appears → "Just group" → the project is grouped in the
    registry AND its folder_path is UNCHANGED on disk (no move)."""
    import rnd_registry as rnd
    from pathlib import Path

    folder_before = rnd.get_project(pid)["folder_path"]

    pg.goto(f"{base}/", wait_until="networkidle")
    pg.evaluate("() => showView && showView('rnd')")
    list_sel = "#rndProjectsRows .rnd-folder-list"
    pg.wait_for_selector(list_sel, timeout=8000)
    pg.wait_for_selector(
        f'{list_sel} .rnd-row[data-project-id="{pid}"]', timeout=5000)

    # "+ New folder" prompts for a name — answer with the target group.
    pg.on("dialog", lambda d: d.accept(group))
    pg.evaluate("() => rndNewFolder()")
    pg.wait_for_selector(
        f'{list_sel} .rnd-folder[data-group="{group}"]', timeout=5000)

    # synthetic drop of the project row onto the folder header (the same
    # handler the UI wires for a real drag).
    pg.evaluate(
        """(a) => {
            const head = document.querySelector(
              '#rndProjectsRows .rnd-folder[data-group="' + a[1] +
              '"] .rnd-folder-head');
            const dt = new DataTransfer();
            dt.setData('text/plain', a[0]);
            const ev = new DragEvent('drop',
              {bubbles: true, cancelable: true, dataTransfer: dt});
            head.dispatchEvent(ev);
        }""", [pid, group])

    # the Option-C dialog appears with both distinct choices. (Generous timeout:
    # the overlay is shown after a JS-async handler; under full-suite load the
    # render can lag, so wait well past the machine-busy window rather than flake.)
    pg.wait_for_function(
        "() => { const o = document.getElementById('rndMoveOverlay');"
        " return o && getComputedStyle(o).display !== 'none'; }",
        timeout=20000)
    assert "Move on disk" in pg.eval_on_selector("#rndMoveGo",
                                                 "e => e.textContent")
    assert "Just group" in pg.eval_on_selector("#rndMoveJust",
                                               "e => e.textContent")

    # "Just group" → grouped in the DOM, registry updated, NO disk move. The
    # click fires an async set_group POST + a projects re-render; the poll below
    # re-renders the rnd view each tick and waits for the row to land in the
    # target folder. Use a generous timeout so a busy machine (full-suite /
    # concurrent swarm) can't trip the previous tight 10s window — the CONDITION
    # (row inside the correctly-grouped folder) is unchanged, only the patience is.
    pg.click("#rndMoveJust")
    pg.wait_for_function(
        """(a) => {
            showView && showView('rnd');
            const row = document.querySelector(
              '#rndProjectsRows .rnd-row[data-project-id="' + a[0] + '"]');
            if (!row) return false;
            const f = row.closest('.rnd-folder');
            return f && f.getAttribute('data-group') === a[1];
        }""", arg=[pid, group], timeout=30000)

    assert rnd.get_project(pid)["group"] == group
    assert rnd.get_project(pid)["folder_path"] == folder_before
    assert Path(folder_before).is_dir()


# ──────────────────────────────────────────────────────────────────────────
# flow 4 — maximize / restore (panel ▢ + terminal re-fit)
# ──────────────────────────────────────────────────────────────────────────

def flow_maximize_restore(pg, base, pid, sid):
    """Open a live session panel, ▢-maximize it (fills ≥90% of the viewport +
    the terminal re-fits larger), then ▢ again to restore (.maxd gone + the
    terminal re-fits back down)."""
    pg.goto(f"{base}/project/{pid}", wait_until="networkidle")
    open_workbench(pg)  # the workbench tile now opens collapsed
    chip = f'#sessionBar .live-chip[data-session="{sid}"]'
    pg.wait_for_selector(chip, timeout=8000)
    pg.click(chip)
    panel = f'#panelStack .panel[data-session="{sid}"]'
    pg.wait_for_selector(f"{panel} .term-host .xterm", timeout=8000)
    pg.wait_for_timeout(150)

    normal = _panel_term_dims(pg, sid)
    assert normal, "no live terminal in PANELS"

    # ▢ MAXIMIZE → .maxd + (approx) viewport-filling + terminal re-fit.
    pg.click(f"{panel} .panelbtn.max")
    pg.wait_for_selector(f"{panel}.maxd", timeout=5000)
    pg.wait_for_timeout(200)
    box = pg.eval_on_selector(
        f"{panel}.maxd",
        "e=>{var r=e.getBoundingClientRect();return {w:r.width,h:r.height};}")
    vp = pg.evaluate("({w:window.innerWidth,h:window.innerHeight})")
    assert box["w"] >= vp["w"] * 0.9, "maximized panel does not fill the width"
    assert box["h"] >= vp["h"] * 0.9, "maximized panel does not fill the height"
    maxed = _panel_term_dims(pg, sid)
    assert maxed["cols"] >= normal["cols"] and maxed["rows"] >= normal["rows"]
    assert maxed["cols"] > normal["cols"] or maxed["rows"] > normal["rows"], \
        "terminal did not re-fit on maximize (cols/rows unchanged)"

    # ▢ RESTORE → .maxd gone + terminal re-fits back.
    pg.click(f"{panel} .panelbtn.max")
    pg.wait_for_function(
        "sel=>document.querySelector(sel)===null", arg=f"{panel}.maxd",
        timeout=5000)
    pg.wait_for_timeout(200)
    restored = _panel_term_dims(pg, sid)
    assert restored, "no terminal after restore"
    assert restored["cols"] <= maxed["cols"], \
        "terminal did not re-fit back smaller on restore"


# ──────────────────────────────────────────────────────────────────────────
# flow 5 — v12 dock click (effort tile → bound dock, transport OPEN)
# ──────────────────────────────────────────────────────────────────────────

def flow_dock_click(pg, base, pid, sid):
    """Click a live effort tile on the Layout-D board → the single bottom dock
    opens BOUND to that effort/session, the xterm mounts in the dock host, and
    the transport (WS or SSE) reaches the OPEN state (readyState === 1)."""
    pg.goto(f"{base}/project/{pid}", wait_until="networkidle")
    open_workbench(pg)  # the workbench tile now opens collapsed
    pg.wait_for_selector(".lane-tile[data-effort-id]", timeout=8000)
    # the dock starts hidden (no effort selected — negative case).
    assert pg.eval_on_selector("#effortDock", "e=>e.style.display") == "none"

    pg.click(f'.lane-tile[data-session="{sid}"]')
    pg.wait_for_function(
        "() => document.getElementById('effortDock').style.display === 'flex'",
        timeout=6000)
    assert pg.eval_on_selector(
        "#effortDock", "e=>e.getAttribute('data-effort-id')"), \
        "dock opened but not bound to an effort_id"
    assert pg.eval_on_selector(
        "#effortDock", "e=>e.getAttribute('data-session')") == sid, \
        "dock bound to the wrong session"
    pg.wait_for_selector("#dockTermHost .xterm", timeout=8000)
    # WebSocket.OPEN === 1 ; EventSource.OPEN === 1
    pg.wait_for_function(
        "() => { var d = window.DOCK; if (!d || !d.transport) return false;"
        "  return d.transport.readyState === 1; }",
        timeout=8000)
