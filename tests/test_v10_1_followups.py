"""v10.1 follow-up bug fixes — four adversarially-verified fixes in anchor_gui.py.

FIX 1 — Restart (Continue-in-a-live-session) opens a NEW stacked panel instead of
        reusing the open one. ``continueSession`` now carries the source panel's
        geometry onto the new session id and ``_closePanel``s the SOURCE (DOM/
        transport teardown only — the source MANAGED record + lane tile survive,
        so it stays reopenable).
FIX 2 — Deleting a grass idea reappears on reopen. ``deleteGrassIdea`` now also
        prunes the matching ``.gli`` row from the hidden ``#grassWorkbenchTpl``
        source template so later clones are clean.
FIX 3 — Home-dashboard far-left status DOT not green when a managed (registry)
        session is running but has no job_runner record. ``_project_status_dot``
        takes ``registry_running`` (from the SAME single registry read the
        activity line already does) and greens on it.
FIX 4 — Grass terminal doesn't reflow when enlarged. ``_mountTerminal`` now
        attaches its OWN ResizeObserver (``w.fitRo``) on the inner ``.term-host``
        so the board-only ``_wirePanelResize`` wiring is no longer required; a
        collapse/zero-size guard keeps ``_fitPanelTerminal`` from spamming
        term_resize on a hidden host.

Hermetic: stub PTY + fake runner + temp dirs; Playwright is DEV-ONLY
(``pytest.importorskip``); never binds :8777 / touches real data.
"""
import importlib
import re
import subprocess
import threading
import time
from html.parser import HTMLParser
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()
_DEVTEST = Path(__file__).resolve().parent.parent / "_devtest"


# ── Source helpers (RAW _PROJECT_WINDOW_JS string introspection) ───────────────

def _project_window_js():
    import anchor_gui
    return anchor_gui._PROJECT_WINDOW_JS


def _fn_body(js, name, arglist):
    m = re.search(r"function " + re.escape(name) + r"\(" + re.escape(arglist) +
                  r"\)\s*\{([\s\S]*?)\n\}\n", js)
    assert m, f"{name}({arglist}) not found in _PROJECT_WINDOW_JS"
    return m.group(1)


# ══════════════════════════════════════════════════════════════════════════════
# FIX 1 — continueSession closes the source panel (DOM/source-level unit checks)
# ══════════════════════════════════════════════════════════════════════════════

def test_fix1_continue_session_closes_source_panel_source():
    """continueSession must (a) open the NEW panel AND (b) _closePanel the SOURCE
    (never killPanel/term_kill — those would reap the worktree/record), and carry
    the source panel geometry onto the new id."""
    js = _project_window_js()
    body = _fn_body(js, "continueSession", "sessionId, lane")
    # Opens the new panel.
    assert "openPanel(sid)" in body
    # Closes the SOURCE panel (the open-window-slot reuse) — guarded against the
    # degenerate sid===sessionId case.
    assert "_closePanel(sessionId)" in body, \
        "continueSession must _closePanel the source session"
    # Geometry carry-over so the restart lands in the old window's slot.
    assert "_panelRects[sessionId]" in body and "_panelRects[sid]" in body
    assert "_panelHeights[sessionId]" in body and "_panelHeights[sid]" in body
    # MUST NOT reap: never killPanel/term_kill on the source (strip // comments
    # first so prose mentioning them doesn't false-positive).
    code = "\n".join(re.sub(r"//.*$", "", ln) for ln in body.splitlines())
    assert "killPanel(sessionId)" not in code, \
        "continueSession must NOT killPanel the source (would reap the record)"
    assert "term_kill" not in code, \
        "continueSession must NOT term_kill the source"


def test_fix1_closepanel_is_nondestructive_to_record_and_tile():
    """_closePanel tears down DOM/transport/observers + deletes PANELS[id] ONLY —
    it must NOT touch MANAGED/FINISHED or remove the lane tile (so the source
    session stays reopenable as a tile)."""
    js = _project_window_js()
    body = _fn_body(js, "_closePanel", "sessionId")
    assert "delete PANELS[sessionId]" in body
    # Non-destructive guarantees:
    assert "MANAGED" not in body, "_closePanel must not mutate MANAGED"
    assert "_removeSessionTile" not in body, "_closePanel must not remove the tile"
    assert "term_kill" not in body, "_closePanel must not kill the session"


# ══════════════════════════════════════════════════════════════════════════════
# FIX 2 — deleteGrassIdea prunes the hidden source template (DOM/source check)
# ══════════════════════════════════════════════════════════════════════════════

def test_fix2_delete_grass_idea_prunes_source_template():
    """deleteGrassIdea must, after a successful delete, remove the matching .gli
    row from the hidden #grassWorkbenchTpl source template so a later clone
    (close→reopen) does not resurrect the deleted idea."""
    js = _project_window_js()
    body = _fn_body(js, "deleteGrassIdea", "ideaId")
    assert "grassWorkbenchTpl" in body, \
        "deleteGrassIdea must reference the hidden source template"
    # It queries the template for the deleted idea's row and removes it.
    assert re.search(r"\.querySelector\('\.gli\[data-idea=\"' \+ _cssEsc\(ideaId\)",
                     body), "deleteGrassIdea must select the template's .gli row by idea"
    assert "trow.remove()" in body or ".remove()" in body.split("grassWorkbenchTpl")[1]
    # v10.1 FIX 2 follow-up — after the row prune, the stale .gtabs filter-count
    # chips must be recomputed on BOTH the live panel AND the source template
    # (else the re-clone shows e.g. "All 1" over an empty list).
    assert "_refreshGrassCounts(panel)" in body, \
        "deleteGrassIdea must refresh the live panel's .gtabs counts"
    assert "_refreshGrassCounts(stpl)" in body, \
        "deleteGrassIdea must refresh the template's .gtabs counts (re-clone path)"


def test_fix2_refresh_grass_counts_derives_from_rows():
    """_refreshGrassCounts(root) must recompute the .gtab .n counts from the
    REMAINING .gli[data-status] rows under root (all = total, raw/refined/promoted
    by status) — derive-from-rows, never an arithmetic decrement (can't drift) —
    writing into .gtab[data-filter] .n, guarded for missing elements."""
    js = _project_window_js()
    body = _fn_body(js, "_refreshGrassCounts", "root")
    assert "querySelectorAll('.gli[data-status]')" in body, \
        "must count the remaining idea rows"
    assert "data-filter=" in body and ".n" in body, \
        "must write into the .gtab[data-filter] .n chip spans"
    # Guarded: bails on a missing root (no throw).
    assert "if (!root) return" in body or "if(!root)return" in body.replace(" ", "")


# ══════════════════════════════════════════════════════════════════════════════
# FIX 4 — _mountTerminal wires a fitRo observer + collapse guard (source checks)
# ══════════════════════════════════════════════════════════════════════════════

def test_fix4_mount_terminal_attaches_fitRo_observer():
    js = _project_window_js()
    # v12 W10: _mountTerminal gained an optional `rec` param (the bottom dock
    # passes its own panel record; default = PANELS[sessionId]).
    body = _fn_body(js, "_mountTerminal", "sessionId, body, rec")
    assert "w.fitRo" in body, "_mountTerminal must store its observer on w.fitRo"
    assert "new ResizeObserver" in body, "_mountTerminal must create a ResizeObserver"
    assert "fro.observe(body)" in body, \
        "_mountTerminal must observe the INNER host (body = .term-host)"
    # Disconnect a prior fitRo first (re-develop must not leak observers), and
    # NOT clobber the board's p.ro observer.
    assert "w.fitRo.disconnect" in body, "must disconnect any prior fitRo first"
    assert "w.fitRo = fro" in body


def test_fix4_fit_panel_terminal_has_collapse_guard():
    js = _project_window_js()
    # v12 W10: _fitPanelTerminal gained an optional `rec` param (defaults to
    # PANELS[sessionId]; the dock passes its DOCK record).
    body = _fn_body(js, "_fitPanelTerminal", "sessionId, rec")
    # The manual (no-fit-addon) branch bails on a collapsed/hidden/zero host.
    assert "offsetParent === null" in body
    assert "clientHeight === 0" in body and "clientWidth === 0" in body


def test_fix4_closepanel_disconnects_fitRo():
    js = _project_window_js()
    body = _fn_body(js, "_closePanel", "sessionId")
    assert "p.fitRo" in body and "p.fitRo.disconnect" in body, \
        "_closePanel must disconnect the fitRo observer too (board cleanup)"


# ══════════════════════════════════════════════════════════════════════════════
# FIX 3 — home-row status dot greens on a running MANAGED registry session
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def tile_env(tmp_path, monkeypatch):
    """Hermetic env: temp data dir + reloaded modules so the session_registry
    reads/writes a throwaway .anchor/sessions.json under tmp_path."""
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(tmp_path / "wt"))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    for mod in ("paths", "job_runner", "rnd_registry", "session_registry",
                "effort_history", "sessions", "summarizer"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import anchor_gui
    gui = importlib.reload(anchor_gui)
    import session_registry as reg
    return gui, reg


def _entry(pid, repo):
    return {"id": pid, "name": "TileProj", "priority": 2, "state": "active",
            "folder_path": str(repo)}


def test_fix3_running_managed_session_greens_the_dot(tile_env, tmp_path):
    """A project with a RUNNING managed (registry) session but NO job_runner
    record must render the green ``rnd-dot-running`` dot. Pre-fix the dot read
    ONLY status_line.running (job_runner-only) → grey."""
    gui, reg = tile_env
    pid = "proj-fix3"
    repo = tmp_path / "repo"
    repo.mkdir()
    # A managed running session with NO effort/job_runner record → status_line
    # running stays 0; only the registry knows it's live.
    reg.register_session(pid, "research", status=reg.STATUS_RUNNING,
                         label="research 1")
    html = gui.render_project_tile_html(_entry(pid, repo))
    assert "rnd-dot-running" in html, \
        "a running MANAGED registry session must green the home-row dot"


def test_fix3_no_running_session_dot_idle(tile_env, tmp_path):
    """Negative: a project with NO running managed session → idle dot, not green."""
    gui, reg = tile_env
    pid = "proj-fix3-idle"
    repo = tmp_path / "repo2"
    repo.mkdir()
    # A DONE session is not running.
    reg.register_session(pid, "research", status=reg.STATUS_DONE, label="done 1")
    html = gui.render_project_tile_html(_entry(pid, repo))
    assert "rnd-dot-running" not in html, \
        "a project with no running managed session must not green the dot"
    assert "rnd-dot-idle" in html


def test_fix3_status_dot_param_is_backcompat(tile_env):
    """_project_status_dot's new registry_running param is optional (single call
    site) — the old two-arg call still works and defaults to 0."""
    gui, _reg = tile_env
    entry = {"id": "x", "state": "active"}
    # Two-arg (legacy) form: no registry signal, empty status line → idle.
    assert gui._project_status_dot(entry, {}) == "rnd-dot-idle"
    # registry_running > 0 greens it without any status_line lane.
    assert gui._project_status_dot(entry, {}, registry_running=1) == "rnd-dot-running"
    # status_line.running still greens it (back-compat path preserved).
    assert gui._project_status_dot(
        entry, {"research": {"running": 2}}) == "rnd-dot-running"
    # Inactive projects stay idle even with a running session.
    assert gui._project_status_dot(
        {"id": "x", "state": "archived"}, {}, registry_running=5) == "rnd-dot-idle"


# ══════════════════════════════════════════════════════════════════════════════
# Playwright (DEV-ONLY): FIX 1 + FIX 2 + FIX 4 real-browser interaction
# ══════════════════════════════════════════════════════════════════════════════

def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)


def _have_git():
    try:
        return subprocess.run(["git", "--version"],
                              capture_output=True).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


@pytest.fixture
def gui_env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    wbase = tmp_path / "wt-base"
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(wbase))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    monkeypatch.delenv("ANCHOR_TERMINAL_SEED", raising=False)
    for mod in ("paths", "job_runner", "pty_manager", "rnd_registry",
                "session_registry", "worktrees", "lanes", "effort_history",
                "sessions", "summarizer", "gate_adapter", "handoff",
                "terminal_session"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import anchor_gui
    gui = importlib.reload(anchor_gui)

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial")

    import rnd_registry
    proj = rnd_registry.add_project("Temp", str(repo), scaffold=False)
    pid = proj["id"]
    import effort_history as eh
    idea = eh.add_idea(str(repo), pid, "Passive autonomous cooling loop",
                       notes="A natural-circulation decay-heat loop.")
    bundle = {"gui": gui, "pid": pid, "repo": repo,
              "idea_id": idea.get("job_id") or idea.get("id")}
    yield bundle
    try:
        import pty_manager
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


@pytest.fixture
def server(gui_env):
    gui = gui_env["gui"]
    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield gui_env, f"http://127.0.0.1:{port}", port
    finally:
        time.sleep(0.1)
        try:
            srv.shutdown()
        except Exception:
            pass
        try:
            srv.server_close()
        except Exception:
            pass
        t.join(timeout=5)


def _kill_all(pid):
    import session_registry as reg
    import terminal_session as ts
    for r in reg.list_sessions(project_id=pid):
        try:
            ts.kill(r["session_id"])
        except Exception:
            pass


@pytest.mark.skipif(not _have_git(), reason="git not on PATH")
def test_fix1_restart_reuses_window_in_browser(server):
    """Start a research session, CLOSE it to a reopenable tile, then Continue →
    the NEW session's panel must be the ONLY terminal panel in #panelStack (the
    source panel was _closePanel'd — no second stacked panel), AND the source
    session record still exists in the registry (reopenable). No JS console error.
    """
    pytest.importorskip("playwright.sync_api")
    bundle, base, _ = server
    pid = bundle["pid"]

    import session_registry as reg
    from playwright.sync_api import sync_playwright
    _DEVTEST.mkdir(exist_ok=True)
    shot = _DEVTEST / "wave_v10_1_fix1_restart.png"

    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        errors = []
        pg.on("console",
              lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.goto(f"{base}/project/{pid}", wait_until="networkidle")
        from tests.ui_helpers import expand_workbench
        expand_workbench(pg)  # the Workbench tile now opens collapsed

        # Start a research session (newTermSession → term_start). Invoked directly
        # (it's the same path the "+ new" control calls) for selector robustness.
        pg.evaluate("()=>newTermSession('research','claude')")
        # Its panel appears in #panelStack.
        pg.wait_for_selector('#panelStack .panel[data-session]', timeout=10000)
        src_sid = pg.eval_on_selector('#panelStack .panel[data-session]',
                                      "e=>e.getAttribute('data-session')")
        assert src_sid

        # CLOSE it to a tile (the × close-to-tile → _closePanel). The session
        # record stays in the registry, reopenable.
        pg.eval_on_selector_all(
            '#panelStack .panel[data-session] .pbar',
            "els=>els.forEach(b=>{})")  # noop to ensure the bar exists
        # Invoke the close handler directly (the × button calls closePanel).
        pg.evaluate("sid=>window.closePanel ? closePanel(sid) : null", src_sid)
        pg.wait_for_function(
            "sid=>!document.querySelector('#panelStack .panel[data-session=\"'+sid+'\"]')",
            arg=src_sid, timeout=6000)
        # Source record still present in the registry.
        assert any(r["session_id"] == src_sid
                   for r in reg.list_sessions(project_id=pid)), \
            "close-to-tile must keep the source session record (reopenable)"

        # Reopen the source as a panel (its tile → openPanel) so Continue has an
        # OPEN source window to reuse — this is the restart scenario.
        pg.evaluate("sid=>openPanel(sid)", src_sid)
        pg.wait_for_selector(
            '#panelStack .panel[data-session="' + src_sid + '"]', timeout=6000)
        # Exactly one panel open now.
        n0 = pg.eval_on_selector_all('#panelStack .panel[data-session]',
                                     "els=>els.length")
        assert n0 == 1, f"expected one open panel before Continue, got {n0}"

        # Continue-in-a-live-session → continueSession(src, 'research').
        pg.evaluate("sid=>continueSession(sid, 'research')", src_sid)
        # Wait for the NEW session's panel to appear AND the source to be gone.
        pg.wait_for_function(
            "src=>{var ps=document.querySelectorAll('#panelStack .panel[data-session]');"
            "return ps.length===1 && ps[0].getAttribute('data-session')!==src;}",
            arg=src_sid, timeout=12000)
        panels = pg.eval_on_selector_all('#panelStack .panel[data-session]',
                                         "els=>els.map(e=>e.getAttribute('data-session'))")
        assert len(panels) == 1, \
            f"restart must reuse the window slot — one panel, got {panels}"
        new_sid = panels[0]
        assert new_sid != src_sid, "Continue mints a NEW session"

        # The SOURCE session record still exists (reopenable as a tile — not reaped).
        assert any(r["session_id"] == src_sid
                   for r in reg.list_sessions(project_id=pid)), \
            "continueSession must NOT reap the source session record"

        pg.screenshot(path=str(shot), full_page=True)
        assert not errors, f"JS console errors: {errors}"
        b.close()

    assert shot.exists()
    _kill_all(pid)


@pytest.mark.skipif(not _have_git(), reason="git not on PATH")
def test_fix2_deleted_grass_idea_stays_gone_after_reopen(server):
    """Open the grass workbench, DELETE the idea (confirm), CLOSE the workbench
    panel (the × that does panel.remove), REOPEN the workbench → the deleted
    idea's .gli row is ABSENT (pre-fix it re-clones from the stale template).
    """
    pytest.importorskip("playwright.sync_api")
    bundle, base, _ = server
    pid = bundle["pid"]
    idea_id = bundle["idea_id"]

    from playwright.sync_api import sync_playwright
    _DEVTEST.mkdir(exist_ok=True)
    shot = _DEVTEST / "wave_v10_1_fix2_grass_delete.png"

    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        errors = []
        pg.on("console",
              lambda m: errors.append(m.text) if m.type == "error" else None)
        # Auto-accept the delete confirm() dialog.
        pg.on("dialog", lambda d: d.accept())
        pg.goto(f"{base}/project/{pid}", wait_until="networkidle")
        from tests.ui_helpers import expand_workbench
        expand_workbench(pg)  # the Workbench tile now opens collapsed

        pg.wait_for_selector('[data-grass-tile="1"]', timeout=8000)
        pg.click('[data-grass-tile="1"]')
        pg.wait_for_selector('#grassPanel .gli[data-idea]', timeout=8000)
        # Sanity: the idea row is present.
        assert pg.eval_on_selector_all('#grassPanel .gli[data-idea]',
                                       "els=>els.length") >= 1

        # Delete the idea (its red ✕ → deleteGrassIdea).
        pg.evaluate("id=>deleteGrassIdea(id)", idea_id)
        # The live row disappears.
        pg.wait_for_function(
            "id=>!document.querySelector('#grassPanel .gli[data-idea=\"'+id+'\"]')",
            arg=idea_id, timeout=8000)

        # CLOSE the workbench panel (the × → panel.remove()).
        pg.evaluate(
            "()=>{var pn=document.getElementById('grassPanel');"
            "if(pn) pn.remove();}")
        pg.wait_for_function("()=>!document.getElementById('grassPanel')",
                             timeout=6000)

        # REOPEN the workbench (re-clones from #grassWorkbenchTpl).
        pg.click('[data-grass-tile="1"]')
        pg.wait_for_selector('#grassPanel', timeout=8000)
        # The deleted idea must NOT be back.
        pg.wait_for_timeout(300)
        n = pg.eval_on_selector_all(
            '#grassPanel .gli[data-idea="' + idea_id + '"]', "els=>els.length")
        assert n == 0, \
            "the deleted grass idea must STAY gone after a close→reopen re-clone"

        # v10.1 FIX 2 follow-up — the .gtabs filter-count chips must match the now-
        # EMPTY list: all/raw/refined/promoted all read "0". Pre-fix they were
        # server-rendered once ("All 1 / raw 1 / …") and never updated, so they
        # stayed stale over the empty list on the re-clone. Derives from rows so
        # it can't drift. (This was the reported symptom.)
        def _count(flt):
            return pg.eval_on_selector(
                '#grassPanel .gtab[data-filter="' + flt + '"] .n',
                "e=>e.textContent.trim()")
        assert _count("all") == "0", "the 'All' chip must read 0 over an empty list"
        assert _count("raw") == "0", "the 'raw' chip must read 0 over an empty list"
        assert _count("refined") == "0", \
            "the 'refined' chip must read 0 over an empty list"
        assert _count("promoted") == "0", \
            "the 'promoted' chip must read 0 over an empty list"

        pg.screenshot(path=str(shot), full_page=True)
        assert not errors, f"JS console errors: {errors}"
        b.close()

    assert shot.exists()
    _kill_all(pid)


@pytest.mark.skipif(not _have_git(), reason="git not on PATH")
def test_fix4_grass_terminal_reflows_on_enlarge_in_browser(server):
    """Mount a grass terminal, assert window.PANELS-equivalent observer wiring
    exists (the grass term host's panel carries a fitRo observer via _mountTerminal),
    enlarge the host, and assert the terminal reflowed (rows increased) — the
    structural + behavioral proof the board path had and grass lacked.
    """
    pytest.importorskip("playwright.sync_api")
    bundle, base, _ = server
    pid = bundle["pid"]

    import session_registry as reg
    from playwright.sync_api import sync_playwright
    _DEVTEST.mkdir(exist_ok=True)
    shot = _DEVTEST / "wave_v10_1_fix4_grass_reflow.png"

    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        errors = []
        pg.on("console",
              lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.goto(f"{base}/project/{pid}", wait_until="networkidle")
        from tests.ui_helpers import expand_workbench
        expand_workbench(pg)  # the Workbench tile now opens collapsed

        pg.wait_for_selector('[data-grass-tile="1"]', timeout=8000)
        pg.click('[data-grass-tile="1"]')
        pg.wait_for_selector('#grassPanel .gli', timeout=8000)
        pg.eval_on_selector('#grassPanel .gli', "e=>e.click()")
        # v12 W11: ONE workbench session per idea (the two-terminal research/plan
        # grass is retired). Open the single session; the FIX-4 reflow intent now
        # applies to it.
        pg.wait_for_selector('#grassPanel .gwork .gsession', timeout=8000)
        pg.click('#grassPanel .gwork .gopen')
        pg.wait_for_selector(
            '#grassPanel .gwork [data-grass-term] .xterm', timeout=10000)
        sid = pg.eval_on_selector(
            '#grassPanel .gwork [data-grass-term]',
            "e=>e.getAttribute('data-session')")
        assert sid

        # The session's panel must carry a fitRo observer (structural proof the
        # board-only _wirePanelResize is no longer required for reflow).
        pg.wait_for_function(
            "sid=>window.PANELS && window.PANELS[sid] && !!window.PANELS[sid].fitRo",
            arg=sid, timeout=8000)
        assert pg.evaluate("sid=>!!(window.PANELS[sid] && window.PANELS[sid].fitRo)",
                           sid) is True, "grass terminal must have a fitRo observer"

        # Capture current rows, ENLARGE the host substantially, wait for the
        # observer to re-fit, assert rows grew. The .term-host is flex:1 inside the
        # resizable .gterm, so we grow the .gterm container; the inner host (body,
        # the box _fitPanelTerminal measures) grows with it and the fitRo fires.
        rows0 = pg.evaluate("sid=>window.PANELS[sid].term.rows", sid)
        pg.evaluate(
            "sid=>{var h=window.PANELS[sid].body;"
            "var g=h.closest('.gterm')||h.parentElement;"
            "if(g){g.style.height='620px'; g.style.minHeight='620px';}"
            "h.style.minHeight='560px';}", sid)
        # Give the ResizeObserver + fit a beat.
        pg.wait_for_function(
            "args=>window.PANELS[args.sid].term.rows > args.r0",
            arg={"sid": sid, "r0": rows0}, timeout=8000)
        rows1 = pg.evaluate("sid=>window.PANELS[sid].term.rows", sid)
        assert rows1 > rows0, \
            f"enlarging the grass terminal host must reflow xterm rows ({rows0}→{rows1})"

        pg.screenshot(path=str(shot), full_page=True)
        assert not errors, f"JS console errors: {errors}"
        b.close()

    assert shot.exists()
    _kill_all(pid)
