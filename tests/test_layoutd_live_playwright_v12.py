"""v12 Wave 10 — Layout-D LIVE: real Chromium interaction test (machine-checkable).

The W10 falsifiable interactions, each with MACHINE-CHECKABLE pass conditions
(NOT "element exists"):

  (a) click an effort tile -> the SINGLE bottom dock opens BOUND to that effort_id
      AND the terminal attaches (the transport readyState is OPEN);
  (b) drag the splitter -> the xterm element stays in the DOM AND its transport
      readyState===OPEN AND a typed char round-trips into the terminal buffer
      after the drag AND terminal.cols/rows changed (the debounced fit ran);
  (c) Advance -> calls /api/rnd/advance_stage and the stage track / zone updates
      with the session-id SET unchanged (no new session minted);
  (d) when context_status.over_threshold the warn banner renders and one click
      calls /api/rnd/handoff_to_fresh.

DEV-ONLY: gated by pytest.importorskip("playwright.sync_api"); Playwright is NEVER
imported by product code. Hermetic: temp data/project dirs, stub PTY, an
OS-assigned port (asserted != 8777), never real data / network,
ANCHOR_PROACTIVE_SUMMARY off.
"""
import importlib
import threading
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()


@pytest.fixture
def gui_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    monkeypatch.delenv("ANCHOR_PROACTIVE_SUMMARY", raising=False)
    for mod in ("paths", "job_runner", "rnd_registry", "lanes",
                "effort_history", "summarizer", "session_registry",
                "worktrees", "pty_manager", "terminal_session",
                "effort_view", "gate_adapter"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import anchor_gui
    yield importlib.reload(anchor_gui)


@pytest.fixture
def server(gui_env):
    gui = gui_env
    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield gui, f"http://127.0.0.1:{port}", port
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(timeout=5)


def _git_init(folder):
    """A minimal git repo so terminal_session.start_session can create a worktree
    (stub PTY, never a real terminal)."""
    import subprocess
    folder.mkdir(parents=True, exist_ok=True)
    for args in (["init"], ["config", "user.email", "t@t"],
                 ["config", "user.name", "t"]):
        subprocess.run(["git"] + args, cwd=str(folder),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    (folder / "README.md").write_text("# test\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(folder),
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(folder),
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _mkproject(folder, name="P"):
    import rnd_registry
    return rnd_registry.add_project(name, str(folder))


def _live_effort(tmp_path, name="Live", lane="research"):
    """Create a project + ONE live effort_managed trio session (stub PTY)."""
    import terminal_session as ts
    folder = tmp_path / name
    _git_init(folder)
    pid = _mkproject(folder, name)["id"]
    rec = ts.start_session(pid, lane, effort_managed=True)
    return pid, str(folder), rec


def test_layoutd_dock_live(server, tmp_path):
    pytest.importorskip("playwright.sync_api")
    gui, base, _ = server
    import session_registry as reg

    pid, fp, rec = _live_effort(tmp_path, "Live", "research")
    sid = rec["session_id"]
    # Pre-state: the live-session id SET (for the Advance no-mint assertion).
    sset0 = {r["session_id"] for r in reg.list_sessions(project_id=pid)}

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        errors = []
        pg.on("console",
              lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.goto(f"{base}/project/{pid}", wait_until="networkidle")
        from tests.ui_helpers import expand_workbench
        expand_workbench(pg)  # the Workbench tile now opens collapsed

        # The live effort renders as a clickable lane tile bound to an effort_id.
        pg.wait_for_selector(".lane-tile[data-effort-id]", timeout=8000)
        # the dock starts hidden (no effort selected — negative case).
        assert pg.eval_on_selector(
            "#effortDock", "e=>e.style.display") == "none"

        # ── (a) click the live tile -> the dock opens BOUND + the terminal attaches
        pg.click(f'.lane-tile[data-session="{sid}"]')
        pg.wait_for_function(
            "() => document.getElementById('effortDock').style.display === 'flex'",
            timeout=6000)
        eff_id = pg.eval_on_selector(
            "#effortDock", "e=>e.getAttribute('data-effort-id')")
        assert eff_id, "dock opened but not bound to an effort_id"
        bound_sid = pg.eval_on_selector(
            "#effortDock", "e=>e.getAttribute('data-session')")
        assert bound_sid == sid, "dock bound to the wrong session"
        # xterm mounts in the dock terminal host.
        pg.wait_for_selector("#dockTermHost .xterm", timeout=8000)
        # the transport (WS or SSE) reaches an OPEN/connected state.
        pg.wait_for_function(
            "() => { var d = window.DOCK; if (!d || !d.transport) return false;"
            "  var t = d.transport;"
            # WebSocket.OPEN === 1 ; EventSource.OPEN === 1
            "  return t.readyState === 1; }",
            timeout=8000)

        # the 3-node stage track reflects current_stage (research → 1 reached node).
        reached0 = pg.eval_on_selector_all(
            "#dockTrack .node.reached", "e=>e.length")
        assert reached0 == 1, f"research effort must light 1 node, got {reached0}"

        # ── (b) drag the splitter — terminal stays attached + fits + char round-trips
        cols0 = pg.evaluate("() => window.DOCK.term.cols")
        rows0 = pg.evaluate("() => window.DOCK.term.rows")
        # v12 W10 change #1: the dock is now EMBEDDED in flow, so scroll it into
        # view before grabbing the splitter (viewport-coordinate drag).
        pg.eval_on_selector("#dockSplit", "e=>e.scrollIntoView({block:'center'})")
        pg.wait_for_timeout(100)
        split = pg.query_selector("#dockSplit")
        box = split.bounding_box()
        # Drag the splitter DOWN ~180px — for an embedded (top-anchored) dock this
        # grows the dock height → the terminal pane gets TALLER (more rows). (The
        # direction is the natural one for the in-flow dock; the fit must still run
        # and the transport must stay OPEN regardless of direction.)
        pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        pg.mouse.down()
        pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + 180, steps=12)
        pg.mouse.up()
        # the xterm element is STILL in the DOM after the drag.
        assert pg.eval_on_selector_all("#dockTermHost .xterm", "e=>e.length") == 1, \
            "xterm element vanished during the splitter drag"
        # the transport is STILL OPEN (readyState 1).
        assert pg.evaluate(
            "() => window.DOCK && window.DOCK.transport "
            "&& window.DOCK.transport.readyState === 1"), \
            "transport closed during the splitter drag"
        # the fit ran: cols OR rows changed (a taller terminal → more rows).
        pg.wait_for_function(
            "a => { var t = window.DOCK.term;"
            "  return t.cols !== a[0] || t.rows !== a[1]; }",
            arg=[cols0, rows0], timeout=6000)
        # a typed char ROUND-TRIPS into the terminal buffer (stub echoes input).
        pg.evaluate("() => window.DOCK.term.focus()")
        pg.keyboard.type("Zq")
        pg.wait_for_function(
            "() => { var t = window.DOCK.term; var buf = t.buffer.active;"
            "  for (var i = 0; i < buf.length; i++) {"
            "    var ln = buf.getLine(i);"
            "    if (ln && ln.translateToString(true).indexOf('Zq') >= 0) return true;"
            "  } return false; }",
            timeout=8000)

        # ── (c) Advance -> calls /api/rnd/advance_stage, no new session minted
        advanced = {"ok": False}
        def _on_resp(resp):
            if "/api/rnd/advance_stage" in resp.url:
                advanced["ok"] = True
        pg.on("response", _on_resp)
        pg.click("#dockAdvance")
        pg.wait_for_function("() => true", timeout=500)
        # the stage track relabels to plan (2 reached nodes) IN PLACE.
        pg.wait_for_function(
            "() => document.querySelectorAll('#dockTrack .node.reached').length === 2",
            timeout=8000)
        assert advanced["ok"], "Advance did not call /api/rnd/advance_stage"
        # session-id SET is UNCHANGED (in-session advance — no new session minted).
        sset1 = {r["session_id"] for r in reg.list_sessions(project_id=pid)}
        assert sset1 == sset0, (
            f"Advance minted/dropped a session: {sset1 ^ sset0}")

        assert not errors, f"JS console errors during the dock interactions: {errors}"
        b.close()

    # backend cleanup: reap the stub session.
    import terminal_session as ts
    try:
        ts.kill(sid)
    except Exception:
        pass


def test_layoutd_new_plan_build_starts_plan_effort_and_metrics(server, tmp_path):
    """John changes #2 + #3 (machine-checkable):
      (#2) clicking '+ New plan/build' starts a PLAN-stage effort — a NEW live
           session appears (session-id SET grows) and the dock opens bound to it
           with the stage track at plan (2 reached nodes);
      (#3) the dock summary metrics line (#dockMetrics) renders 'Σ … tok · … · $…'
           (fetched from /api/rnd/effort_rollup)."""
    pytest.importorskip("playwright.sync_api")
    gui, base, _ = server
    import session_registry as reg
    # A project with a git repo so a new effort's worktree can be created (stub PTY).
    folder = tmp_path / "NewPB"
    _git_init(folder)
    pid = _mkproject(folder, "NewPB")["id"]
    fp = str(folder)
    sset0 = {r["session_id"] for r in reg.list_sessions(project_id=pid)}

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        errors = []
        pg.on("console",
              lambda m: errors.append(m.text) if m.type == "error" else None)
        # capture the rollup endpoint call (the metrics fetch).
        rollup_called = {"ok": False}
        def _on_resp(resp):
            if "/api/rnd/effort_rollup" in resp.url:
                rollup_called["ok"] = True
        pg.on("response", _on_resp)
        pg.goto(f"{base}/project/{pid}", wait_until="networkidle")
        from tests.ui_helpers import expand_workbench
        expand_workbench(pg)  # the Workbench tile now opens collapsed

        # Both new-session controls are present.
        pg.wait_for_selector("#newResearchBtn", timeout=8000)
        pg.wait_for_selector("#newPlanBuildBtn", timeout=8000)

        # ── (#2) click '+ New plan/build' → a new plan-stage live session appears.
        pg.click("#newPlanBuildBtn")
        # the dock opens bound to a brand-new effort.
        pg.wait_for_function(
            "() => document.getElementById('effortDock').style.display === 'flex'",
            timeout=8000)
        bound_sid = pg.eval_on_selector(
            "#effortDock", "e=>e.getAttribute('data-session')")
        assert bound_sid, "the new plan/build effort did not bind the dock"
        assert bound_sid not in sset0, "expected a NEW session id"
        # the new session is in the registry (the SET grew by the new id).
        sset1 = {r["session_id"] for r in reg.list_sessions(project_id=pid)}
        assert bound_sid in sset1, "the new plan/build session was not registered"
        # it is a PLAN-stage effort → the stage track shows 2 reached nodes.
        pg.wait_for_function(
            "() => document.querySelectorAll('#dockTrack .node.reached').length === 2",
            timeout=8000)
        # confirm the registry record's stage/lane is plan.
        new_rec = reg.get_session(bound_sid) or {}
        stage = (new_rec.get("current_stage") or new_rec.get("lane") or "")
        assert stage in ("plan", "planning"), \
            f"new effort is not at the plan stage: {stage!r}"

        # ── (#3) the dock metrics line renders 'Σ … tok · … · $…'.
        pg.wait_for_selector("#dockMetrics", timeout=8000)
        # the metrics fetch fired …
        for _ in range(40):
            if rollup_called["ok"]:
                break
            pg.wait_for_timeout(100)
        assert rollup_called["ok"], "the dock did not fetch /api/rnd/effort_rollup"
        # … and the line shows the Σ tokens · time · $ shape (honest zeros for a
        # fresh effort — never fabricated).
        pg.wait_for_function(
            "() => { var m = document.getElementById('dockMetrics');"
            "  if (!m) return false; var t = m.textContent || '';"
            "  return t.indexOf('\\u03a3') >= 0 && t.indexOf('tok') >= 0"
            "      && t.indexOf('$') >= 0; }",
            timeout=8000)
        assert not errors, f"JS console errors: {errors}"
        b.close()

    import terminal_session as ts
    try:
        ts.kill(bound_sid)
    except Exception:
        pass


def test_layoutd_dock_warn_banner_handoff(server, tmp_path, monkeypatch):
    """(d) When context_status.over_threshold, the warn banner renders; one click
    calls /api/rnd/handoff_to_fresh."""
    pytest.importorskip("playwright.sync_api")
    gui, base, _ = server
    # Force the context-fullness heuristic over threshold via its env knob so the
    # banner appears deterministically (no need to fill a real buffer).
    import terminal_session as ts

    pid, fp, rec = _live_effort(tmp_path, "Warn", "research")
    sid = rec["session_id"]
    # Drive context_fullness over threshold: a tiny budget so any output trips it.
    monkeypatch.setenv("ANCHOR_CONTEXT_FULL_BUDGET", "1")
    # Sanity (deterministic, W10-R2-04): the stub PTY's seed output may not have
    # landed in the read buffer the instant after start_session — POLL until the
    # backend reports over_threshold rather than asserting on the first read (a
    # flaky precondition, not a behavior check). A byte nudge guarantees output.
    import time as _t
    cf = None
    for _ in range(50):  # up to ~5s
        cf = ts.context_fullness(sid)
        if cf.get("over_threshold") is True:
            break
        try:
            ts.input(sid, "x\n")  # nudge the stub buffer so observed_bytes > 0
        except Exception:
            pass
        _t.sleep(0.1)
    assert cf and cf.get("over_threshold") is True, (
        f"precondition: context not over threshold after polling ({cf})")

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        errors = []
        pg.on("console",
              lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.goto(f"{base}/project/{pid}", wait_until="networkidle")
        from tests.ui_helpers import expand_workbench
        expand_workbench(pg)  # the Workbench tile now opens collapsed
        pg.wait_for_selector(f'.lane-tile[data-session="{sid}"]', timeout=8000)
        pg.click(f'.lane-tile[data-session="{sid}"]')
        pg.wait_for_function(
            "() => document.getElementById('effortDock').style.display === 'flex'",
            timeout=6000)
        # the warn banner becomes visible (the poll observes over_threshold).
        pg.wait_for_function(
            "() => { var w = document.getElementById('dockWarn');"
            "  return w && w.style.display !== 'none'; }",
            timeout=10000)
        # one click calls /api/rnd/handoff_to_fresh.
        called = {"ok": False}
        def _on_resp(resp):
            if "/api/rnd/handoff_to_fresh" in resp.url:
                called["ok"] = True
        pg.on("response", _on_resp)
        pg.click("#dockWarn")
        pg.wait_for_function("() => true", timeout=500)
        # wait for the call to land.
        for _ in range(40):
            if called["ok"]:
                break
            pg.wait_for_timeout(100)
        assert called["ok"], "warn-banner click did not call /api/rnd/handoff_to_fresh"
        assert not errors, f"JS console errors: {errors}"
        b.close()

    try:
        ts.kill(sid)
    except Exception:
        pass


def test_layoutd_dock_no_double_mount_from_chip(server, tmp_path):
    """F1 (W10 Reviewer): a live session is reachable from BOTH its board effort
    tile (→ dock) and its session-bar chip (→ openPanel). Clicking the chip while
    the session is already in the dock must NOT stack a second floating panel /
    second terminal — openPanel routes it back to the dock."""
    pytest.importorskip("playwright.sync_api")
    gui, base, _ = server
    pid, fp, rec = _live_effort(tmp_path, "Dbl", "research")
    sid = rec["session_id"]
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.goto(f"{base}/project/{pid}", wait_until="networkidle")
        from tests.ui_helpers import expand_workbench
        expand_workbench(pg)  # the Workbench tile now opens collapsed
        pg.wait_for_selector(f'.lane-tile[data-session="{sid}"]', timeout=8000)
        # open the dock from the board effort tile
        pg.click(f'.lane-tile[data-session="{sid}"]')
        pg.wait_for_function(
            "() => document.getElementById('effortDock').style.display === 'flex'",
            timeout=6000)
        pg.wait_for_selector("#dockTermHost .xterm", timeout=8000)
        # The live-session-bar chip for this session routes a click through
        # openPanel(sid) (laneTileClick → openPanel for a non-effort chip). With the
        # dock fixed over the bottom strip a real chip click is visually covered, so
        # invoke the SAME code path directly — this is exactly what the chip's
        # onclick does, and it is the path the F1 guard lives on.
        assert pg.evaluate("() => typeof window.openPanel === 'function'"), \
            "openPanel not reachable in page scope"
        pg.evaluate("(s) => window.openPanel(s)", sid)
        pg.wait_for_function("() => true", timeout=400)
        # NO second floating panel was stacked for this session.
        panels = pg.eval_on_selector_all(
            f'#panelStack .panel[data-session="{sid}"]', "e=>e.length")
        assert panels == 0, "chip-click stacked a second panel on a docked session"
        # the dock still owns the single live terminal surface for this session.
        assert pg.eval_on_selector(
            "#effortDock", "e=>e.getAttribute('data-session')") == sid
        assert pg.eval_on_selector_all("#dockTermHost .xterm", "e=>e.length") == 1
        b.close()
    import terminal_session as ts
    try:
        ts.kill(sid)
    except Exception:
        pass


def test_layoutd_dock_advance_hidden_at_build(server, tmp_path):
    """W10-R2-01: an effort already at the BUILD stage (no next stage) shows NO
    Advance → control in the dock (honest disable)."""
    pytest.importorskip("playwright.sync_api")
    gui, base, _ = server
    import terminal_session as ts
    pid, fp, rec = _live_effort(tmp_path, "AtBuild", "research")
    sid = rec["session_id"]
    # advance research → plan → build so current_stage == 'build'
    ts.advance_stage(sid, "plan", mode="manual", project_id=pid)
    ts.advance_stage(sid, "build", mode="manual", project_id=pid)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.goto(f"{base}/project/{pid}", wait_until="networkidle")
        from tests.ui_helpers import expand_workbench
        expand_workbench(pg)  # the Workbench tile now opens collapsed
        pg.wait_for_selector(f'.lane-tile[data-session="{sid}"]', timeout=8000)
        pg.click(f'.lane-tile[data-session="{sid}"]')
        pg.wait_for_function(
            "() => document.getElementById('effortDock').style.display === 'flex'",
            timeout=6000)
        # the 3-node track is fully lit (build → 3 reached nodes)
        pg.wait_for_function(
            "() => document.querySelectorAll('#dockTrack .node.reached').length === 3",
            timeout=8000)
        # Advance → is hidden (display:none) — no next stage past build.
        disp = pg.eval_on_selector(
            "#dockAdvance", "e=>getComputedStyle(e).display")
        assert disp == "none", f"Advance should be hidden at build, got {disp!r}"
        b.close()
    try:
        ts.kill(sid)
    except Exception:
        pass


def test_grass_mini_panel_collapse_toggle(server, tmp_path):
    """John tweak (machine-checkable): clicking the Grass Catcher panel's caret
    collapses/expands its idea list IN THE TILE (#grassMiniList gets .collapsed),
    while Open-workbench stays present."""
    pytest.importorskip("playwright.sync_api")
    gui, base, _ = server
    pid, fp, rec = _live_effort(tmp_path, "GrassTog", "research")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.goto(f"{base}/project/{pid}", wait_until="networkidle")
        from tests.ui_helpers import expand_workbench
        expand_workbench(pg)  # the Workbench tile now opens collapsed
        pg.wait_for_selector("#grassMiniTog", timeout=8000)
        # John tweak: starts COLLAPSED on first load (minimal dashboard).
        assert pg.eval_on_selector(
            "#grassMiniList", "e=>e.classList.contains('collapsed')") is True, \
            "grass idea list must start COLLAPSED by default"
        # Open-workbench stays reachable even when collapsed.
        assert pg.eval_on_selector_all(".grass-open", "e=>e.length") >= 1
        pg.click("#grassMiniTog")
        assert pg.eval_on_selector(
            "#grassMiniList", "e=>e.classList.contains('collapsed')") is False, \
            "caret did not expand the grass idea list"
        pg.click("#grassMiniTog")
        assert pg.eval_on_selector(
            "#grassMiniList", "e=>e.classList.contains('collapsed')") is True, \
            "second click did not collapse"
        b.close()
    import terminal_session as ts
    try: ts.kill(rec["session_id"])
    except Exception: pass
