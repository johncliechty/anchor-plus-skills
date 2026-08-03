"""v6 Wave 9 — final polish: explicit Finish→Build · vertical-resize grows the
terminal · reconcile_and_advance wired into the live refresh path.

Three small, distinct follow-ups (all approved):

  (1) A PLANNING panel gets a dedicated, NON-destructive "Finish → Build" control.
      POST /api/rnd/finish_to_build {project_id, session}: capture the plan set,
      mark the planning session DONE via session_registry.update_session WITHOUT
      reaping its worktree (it stays a reopenable finished tile), then
      auto_advance_planning_to_build → {ok, auto_build:<record|null>, reason?}.
      No plan set ⇒ auto_build:null + a reason (never fabricated). Token-gated.

  (2) Dragging a panel taller grows the TERMINAL (more rows), not the summary:
      .tpane flexes (flex:1 1 auto) to fill the .pin flex-column's remaining
      vertical space; the summary keeps its natural height on top.

  (3) terminal_session.reconcile_and_advance is wired into GET /api/rnd/term_sessions
      (the project-window refresh/poll path), guarded, with the LIVE PTY set — so a
      planning session whose process DIED auto-advances to a build on the next
      refresh, not only on an explicit hard-kill. Idempotent → repeated polls no-op.

Un-gameable gate model (v4.1 / v5): rendered-DOM + JS-source structural asserts
(style/script stripped) PLUS hermetic backend asserts PLUS real Playwright/Chromium
interaction tests + screenshots. Never :8777, never real data — stub PTY backend,
temp data dir + worktree base, a throwaway temp git repo.
"""
import importlib
import json as _json
import re
import subprocess
import threading
import urllib.request
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()
DEVTEST = Path(__file__).resolve().parent.parent / "_devtest"


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)


def _have_git():
    try:
        return subprocess.run(["git", "--version"],
                              capture_output=True).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


pytestmark = pytest.mark.skipif(not _have_git(), reason="git not on PATH")


# ── env / fixtures (stub PTY + temp git repo + project) ──────────────────────

@pytest.fixture
def env(tmp_path, monkeypatch):
    """Tmp data dir + tmp worktree base + stub PTY + the fake runner + a temp git
    repo + a registered project — the SAME isolated harness the Wave-6 auto-advance
    tests use, so start_session creates real worktrees off the TEMP repo (never
    C:\\dev\\Anchor) and nothing binds :8777."""
    data = tmp_path / "data"
    data.mkdir()
    wbase = tmp_path / "wt-base"
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(wbase))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)

    for mod in ("paths", "job_runner", "pty_manager", "rnd_registry",
                "effort_history", "sessions", "anchor_marker",
                "session_registry", "worktrees", "lanes", "summarizer",
                "handoff", "terminal_session"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import anchor_gui
    gui = importlib.reload(anchor_gui)

    import effort_history
    import handoff
    import terminal_session
    import session_registry
    import anchor_marker
    import rnd_registry

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial")

    proj = rnd_registry.add_project("Temp", str(repo), scaffold=False)
    bundle = {
        "gui": gui, "ts": terminal_session, "reg": session_registry,
        "handoff": handoff, "eh": effort_history, "marker": anchor_marker,
        "rnd": rnd_registry, "repo": repo, "pid": proj["id"],
        "wbase": wbase, "data": data,
    }
    yield bundle
    try:
        import pty_manager
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


def _add_plan_session(eh, repo, pid, plan_dir="planning/rnd-x",
                      created_at=2000.0):
    """Record a discovered planning session with a REAL MASTER+IMPL plan set
    committed into the repo so handoff discovery finds it (mirrors the Wave-6
    test helper)."""
    master_rel = f"{plan_dir}/MASTER-PLAN.md"
    impl_rel = f"{plan_dir}/IMPLEMENTATION-PLAN.md"
    log_rel = f"{plan_dir}/EXECUTION-LOG.md"
    for rel, body in [(master_rel, "# Master Plan\n"),
                      (impl_rel, "# Implementation Plan\n"),
                      (log_rel, "# Execution Log\n")]:
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    specs = [(master_rel, "Master Plan"), (impl_rel, "Implementation Plan"),
             (log_rel, "Execution Log")]
    for i, (rel, title) in enumerate(specs):
        jid = eh.discovered_job_id("planning", rel)
        eh.record_effort(
            repo, pid, "planning", jid, skill="Crucible",
            extra={"source": eh.SOURCE_DISCOVERED, "kind": "plan-doc",
                   "title": title, "artifact_path": rel, "status": "imported",
                   "created_at": created_at + i * 0.001})
    return {"master_rel": master_rel, "impl_rel": impl_rel, "log_rel": log_rel}


def _js(html):
    return "\n".join(re.findall(r"<script[^>]*>([\s\S]*?)</script>", html))


def _css(html):
    return "\n".join(re.findall(r"<style[^>]*>([\s\S]*?)</style>", html))


def _free_server(gui):
    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, port, t


def _post(port, path, payload):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=_json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status, _json.loads(r.read().decode("utf-8"))


# ════════════════════════════════════════════════════════════════════════════
# (1) FINISH → BUILD — backend (non-destructive + honest-on-no-plan + idempotent)
# ════════════════════════════════════════════════════════════════════════════

def test_finish_to_build_marks_done_keeps_worktree_one_linked_build(env):
    """finish_to_build on a PLANNING session WITH a plan set: marks the planning
    session DONE WITHOUT reaping its worktree (still on disk; record present, not
    removed) and returns EXACTLY ONE linked build (parent==planning, inherited
    chain). A second call is idempotent (no duplicate build)."""
    ts, reg, eh, repo, pid, gui = (env["ts"], env["reg"], env["eh"],
                                   env["repo"], env["pid"], env["gui"])
    ho = env["handoff"]
    plan = _add_plan_session(eh, repo, pid)
    plan_sess = ts.start_session(pid, "planning", backend="claude")
    psid = plan_sess["session_id"]
    plan_wt = Path(plan_sess["worktree_path"])
    assert plan_wt.exists()

    srv, port, t = _free_server(gui)
    bsid = None
    try:
        status, data = _post(port, "/api/rnd/finish_to_build",
                             {"project_id": pid, "session": psid})
        assert status == 200 and data["ok"] is True
        assert data.get("auto_build"), "a plan set was present — a build must open"
        ab = data["auto_build"]
        bsid = ab["session_id"]
        assert ab["lane"] == "build"
        assert ab["parent_session_id"] == psid
        assert ab["chain_id"] == plan_sess["chain_id"]

        # NON-DESTRUCTIVE: the planning session is DONE but its record + worktree
        # SURVIVE (it stays a reopenable finished tile — close-to-tile).
        prec = reg.get_session(psid)
        assert prec is not None, "finish must NOT remove the planning record"
        assert prec["status"] == reg.STATUS_DONE
        assert plan_wt.exists(), "finish→build must NOT reap the planning worktree"

        # Exactly ONE build, primed (HANDOFF.md → the real plan docs) + edge.
        builds = [s for s in reg.list_sessions(project_id=pid)
                  if s.get("lane") == "build"]
        assert len(builds) == 1
        wt = Path(ab["worktree_path"])
        hf = wt / ho.HANDOFF_FILENAME
        assert hf.exists()
        text = hf.read_text(encoding="utf-8")
        assert plan["master_rel"] in text and plan["impl_rel"] in text
        assert any(l["from_session_id"] == psid and l["to_session_id"] == bsid
                   and l["kind"] == "plan->build"
                   for l in ho.list_stage_links(repo, pid))

        # IDEMPOTENT: a second finish→build does not duplicate the build.
        status2, data2 = _post(port, "/api/rnd/finish_to_build",
                               {"project_id": pid, "session": psid})
        assert status2 == 200 and data2["ok"] is True
        assert data2.get("auto_build") is None
        builds2 = [s for s in reg.list_sessions(project_id=pid)
                   if s.get("lane") == "build"]
        assert len(builds2) == 1, "a second finish duplicated the build"
    finally:
        if bsid:
            try:
                ts.kill(bsid)
            except Exception:
                pass
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


def test_finish_to_build_no_plan_set_is_honest(env):
    """finish_to_build with NO discoverable plan set returns auto_build:null + a
    reason, creates NO build, and does NOT mark the planning session done (it stays
    exactly as it was — nothing to advance to)."""
    ts, reg, pid, gui = env["ts"], env["reg"], env["pid"], env["gui"]
    plan_sess = ts.start_session(pid, "planning", backend="claude")
    psid = plan_sess["session_id"]
    srv, port, t = _free_server(gui)
    try:
        status, data = _post(port, "/api/rnd/finish_to_build",
                             {"project_id": pid, "session": psid})
        assert status == 200 and data["ok"] is True
        assert data.get("auto_build") is None
        assert data.get("reason"), "no-plan-set must carry an honest reason"
        assert [s for s in reg.list_sessions(project_id=pid)
                if s.get("lane") == "build"] == []
        # No plan ⇒ nothing advanced ⇒ the session is untouched (still RUNNING).
        assert reg.get_session(psid)["status"] == reg.STATUS_RUNNING
    finally:
        try:
            ts.kill(psid)
        except Exception:
            pass
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


def test_finish_to_build_token_gated(env, monkeypatch):
    """With ANCHOR_TOKEN set, finish_to_build is rejected (401) without the token
    and accepted with it — it rides the do_POST token middleware."""
    import urllib.error
    ts, eh, repo, pid = env["ts"], env["eh"], env["repo"], env["pid"]
    gui = env["gui"]
    _add_plan_session(eh, repo, pid)
    plan_sess = ts.start_session(pid, "planning", backend="claude")
    psid = plan_sess["session_id"]

    # Reload paths + gui with a token configured so auth_ok enforces it.
    monkeypatch.setenv("ANCHOR_TOKEN", "sekret")
    import paths
    importlib.reload(paths)
    gui2 = importlib.reload(gui)

    srv, port, t = _free_server(gui2)
    bsid = None
    try:
        # Unauthed → 401.
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/rnd/finish_to_build",
            data=_json.dumps({"project_id": pid, "session": psid}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with pytest.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(req, timeout=20)
        assert ei.value.code == 401

        # Authed (token in body) → 200 + a build.
        req2 = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/rnd/finish_to_build",
            data=_json.dumps({"project_id": pid, "session": psid,
                              "token": "sekret"}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req2, timeout=20) as r:
            data = _json.loads(r.read().decode("utf-8"))
        assert data["ok"] is True and data.get("auto_build")
        bsid = data["auto_build"]["session_id"]
    finally:
        if bsid:
            try:
                ts.kill(bsid)
            except Exception:
                pass
        srv.shutdown(); srv.server_close(); t.join(timeout=5)
        monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
        importlib.reload(paths)


# ── (1) RENDERED-DOM / JS-source asserts (positive + negative) ───────────────

def test_finish_bar_in_js_planning_only(env):
    """The "Finish → Build" bar + finishToBuild endpoint are wired in the project
    window JS, gated on the plan/planning lane (positive), and NOT on research /
    build (negative). It does NOT collide with the research advance-bar gate."""
    gui, pid = env["gui"], env["pid"]
    js = _js(gui.render_project_window_html(pid))

    # POSITIVE: the finish control + its endpoint + the non-destructive helpers.
    assert "finishToBuild(" in js
    assert "/api/rnd/finish_to_build" in js
    assert "Finish → Build" in js or "Finish → Build" in js
    assert "fbbar" in js
    assert "_finishPlanningTile(" in js   # moves planning → finished tile (kept)
    assert "_addAutoBuildTile(" in js     # reuses the auto-build tile minter
    assert "_flashNoPlanNote(" in js      # honest no-plan note
    # The finish bar is gated on the plan/planning lane.
    assert re.search(r"\(s\.lane\s*\|\|\s*''\)\s*===\s*'plan'", js), \
        "finish bar must be gated on the plan/planning lane"

    # The finish-bar button text is set exactly once (one control).
    assert js.count("fbbtn.textContent = 'Finish → Build →'") == 1

    # NEGATIVE: the research advance-bar gate is untouched (still research-only,
    # still exactly one advance control) — proves no collision with follow-up 1.
    assert js.count("advb.textContent = 'Advance to Planning →'") == 1
    guard = re.search(r"if\s*\(\(s\.lane[^\n]*'research'\)\s*\{([\s\S]*?)\n  \}",
                      js)
    assert guard and "advbtn" in guard.group(1)

    # NEGATIVE: closePanel never references finish_to_build (close ≠ advance).
    cp = re.search(r"function closePanel\(sessionId\)\s*\{([\s\S]*?)\n\}", js)
    assert cp and "finish_to_build" not in cp.group(1)


# ════════════════════════════════════════════════════════════════════════════
# (2) VERTICAL RESIZE GROWS THE TERMINAL — CSS/structure (positive + negative)
# ════════════════════════════════════════════════════════════════════════════

def test_tpane_flexes_to_fill_panel_height(env):
    """The terminal pane now FLEXES to fill the .pin flex-column's remaining
    vertical space (flex:1 1 auto) instead of a fixed height — so growing the
    panel taller grows the terminal, not the summary. Positive + negative."""
    gui, pid = env["gui"], env["pid"]
    css = _css(gui.render_project_window_html(pid))

    tpane = re.search(r"\.panel \.tpane\{([^}]*)\}", css)
    assert tpane, ".panel .tpane CSS rule not found"
    rule = tpane.group(1)
    # POSITIVE: the tpane flexes to fill remaining height + keeps a usable min.
    assert "flex:1 1 auto" in rule, \
        ".tpane must flex to fill the panel's remaining vertical space"
    assert "min-height" in rule, ".tpane needs a min-height to stay usable"
    # NEGATIVE: it is no longer pinned to a single fixed height (the old
    # `height:240px`), which is what forced extra height into the summary.
    assert "height:240px" not in rule, \
        ".tpane must not be fixed-height-only anymore (it must flex)"

    # The .pin body is a flex column (so the flex distributes), and the summary
    # keeps its natural height on top (flex:0 0 auto) — the terminal absorbs the
    # extra, not the summary.
    pin = re.search(r"\.panel \.pin\{([^}]*)\}", css)
    assert pin and "flex-direction:column" in pin.group(1)
    summ = re.search(r"\.panel \.summary\{([^}]*)\}", css)
    assert summ and "flex:0 0 auto" in summ.group(1), \
        "the summary must keep its natural height so the terminal grows instead"


# ════════════════════════════════════════════════════════════════════════════
# (3) reconcile_and_advance WIRED into the live term_sessions refresh path
# ════════════════════════════════════════════════════════════════════════════

def test_term_sessions_handler_calls_reconcile_and_advance(env):
    """The GET /api/rnd/term_sessions handler calls reconcile_and_advance with the
    LIVE PTY set, guarded — the wiring exists in the served source."""
    import inspect
    gui = env["gui"]
    # After the rearch W7/C2 route migration the GET /api/rnd/term_sessions logic
    # moved OUT of the inline do_GET chain into the module-level handle_term_sessions
    # handler; the wiring invariant is unchanged.
    src = inspect.getsource(gui.handle_term_sessions)
    # The wiring is present and passes live_session_ids (NOT the default None,
    # which would mark live sessions stale).
    assert "reconcile_and_advance(" in src
    assert "live_sessions()" in src
    assert "live_session_ids=" in src


def test_dead_planning_auto_advances_on_term_sessions_fetch(env):
    """A planning session whose PTY died is auto-advanced to ONE build when
    /api/rnd/term_sessions is fetched; a second fetch is idempotent (no dup)."""
    ts, reg, eh, repo, pid, gui = (env["ts"], env["reg"], env["eh"],
                                   env["repo"], env["pid"], env["gui"])
    import pty_manager
    _add_plan_session(eh, repo, pid)
    plan_sess = ts.start_session(pid, "planning", backend="claude")
    psid = plan_sess["session_id"]

    # Simulate the PTY dying: drop it from the live table so reconcile (driven by
    # the handler with the now-empty live set) marks the planning session DONE.
    pty_manager._reset_live_table_for_tests()
    assert pty_manager.live_sessions() == []

    srv, port, t = _free_server(gui)
    bsid = None
    try:
        url = (f"http://127.0.0.1:{port}/api/rnd/term_sessions"
               f"?project_id={pid}")
        with urllib.request.urlopen(url, timeout=20) as r:
            data = _json.loads(r.read().decode("utf-8"))
        assert data["ok"] is True
        # The dead planning session was reconciled to DONE …
        assert reg.get_session(psid)["status"] == reg.STATUS_DONE
        # … and auto-advanced to exactly one linked build.
        builds = [s for s in reg.list_sessions(project_id=pid)
                  if s.get("lane") == "build"]
        assert len(builds) == 1, "dead planning did not auto-advance to a build"
        bsid = builds[0]["session_id"]
        assert builds[0]["parent_session_id"] == psid

        # Second fetch → idempotent (still one build).
        with urllib.request.urlopen(url, timeout=20) as r:
            _json.loads(r.read().decode("utf-8"))
        builds2 = [s for s in reg.list_sessions(project_id=pid)
                   if s.get("lane") == "build"]
        assert len(builds2) == 1, "second term_sessions fetch duplicated the build"
    finally:
        if bsid:
            try:
                ts.kill(bsid)
            except Exception:
                pass
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


# ════════════════════════════════════════════════════════════════════════════
# (D) REAL Playwright + Chromium — interaction tests + screenshots
# ════════════════════════════════════════════════════════════════════════════

def test_playwright_finish_to_build(env):
    """End-to-end: open a PLANNING panel (project WITH a plan set) → click
    "Finish → Build" → a linked BUILD tile appears + the auto-opened note + the
    planning tile goes finished/greyed; no JS console errors. Screenshot saved."""
    pytest.importorskip("playwright.sync_api")
    ts, eh, repo, pid, gui = (env["ts"], env["eh"], env["repo"], env["pid"],
                              env["gui"])
    _add_plan_session(eh, repo, pid)
    plan_sess = ts.start_session(pid, "planning", backend="claude")
    psid = plan_sess["session_id"]

    srv, port, t = _free_server(gui)
    base = f"http://127.0.0.1:{port}"
    from playwright.sync_api import sync_playwright
    bsid = None
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            pg.on("console",
                  lambda m: errors.append(m.text) if m.type == "error" else None)
            pg.goto(f"{base}/project/{pid}", wait_until="networkidle")
            from tests.ui_helpers import expand_workbench
            expand_workbench(pg)  # the Workbench tile now opens collapsed

            chip_sel = '#sessionBar .live-chip[data-session="%s"]' % psid
            pg.wait_for_selector(chip_sel, timeout=8000)
            pg.click(chip_sel)
            pg.wait_for_selector("#panelStack .panel", timeout=5000)
            # The Finish→Build bar is present on the planning panel.
            pg.wait_for_selector("#panelStack .panel .fbbar .fbbtn", timeout=6000)
            assert pg.eval_on_selector_all(
                "#panelStack .panel .fbbar .fbbtn", "e=>e.length") == 1

            pg.click("#panelStack .panel .fbbar .fbbtn")
            # A NEW BUILD tile appears (a live chip whose lane is build) + the note.
            pg.wait_for_selector('#sessionBar .live-chip[data-lane="build"]',
                                 timeout=8000)
            build_chips = pg.eval_on_selector_all(
                '#sessionBar .live-chip[data-lane="build"]',
                "els => els.map(e => e.getAttribute('data-session'))")
            assert build_chips, "no linked build tile appeared"
            bsid = build_chips[0]
            assert bsid != psid
            pg.wait_for_selector(".autobuild-note", timeout=6000)

            # The planning tile goes FINISHED/greyed (kept + reopenable, NOT gone):
            # its chip now carries data-finished='1' + .done (the Wave-4 finished
            # tile), proving the non-destructive close-to-tile move.
            fin_sel = ('#sessionBar .live-chip.done[data-finished="1"]'
                       '[data-session="%s"]' % psid)
            pg.wait_for_selector(fin_sel, timeout=6000)
            assert pg.eval_on_selector_all(
                '#sessionBar .live-chip[data-live="1"][data-session="%s"]' % psid,
                "e=>e.length") == 0, "planning tile should no longer be LIVE"

            DEVTEST.mkdir(exist_ok=True)
            pg.screenshot(path=str(DEVTEST / "wave9_finish_build.png"),
                          full_page=True)
            assert not errors, f"JS console errors: {errors}"
            # Backend linkage holds.
            import session_registry as reg
            brec = reg.get_session(bsid)
            assert brec["parent_session_id"] == psid
            b.close()
    finally:
        if bsid:
            try:
                ts.kill(bsid)
            except Exception:
                pass
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


def test_playwright_vertical_resize_grows_terminal_rows(env):
    """End-to-end: open a panel, record terminal ROWS, grow the .pin panel HEIGHT,
    and assert the terminal rows INCREASED (re-fit) — the terminal grows, not the
    summary. No console errors. Screenshot of a tall panel saved."""
    pytest.importorskip("playwright.sync_api")
    ts, pid, gui = env["ts"], env["pid"], env["gui"]
    rec = ts.start_session(pid, "research", backend="claude")
    sid = rec["session_id"]

    srv, port, t = _free_server(gui)
    base = f"http://127.0.0.1:{port}"
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1280, "height": 1000})
            errors = []
            pg.on("console",
                  lambda m: errors.append(m.text) if m.type == "error" else None)
            pg.goto(f"{base}/project/{pid}", wait_until="networkidle")
            from tests.ui_helpers import expand_workbench
            expand_workbench(pg)  # the Workbench tile now opens collapsed

            chip_sel = '#sessionBar .live-chip[data-session="%s"]' % sid
            pg.wait_for_selector(chip_sel, timeout=8000)
            pg.click(chip_sel)
            pg.wait_for_selector("#panelStack .panel .term-host .xterm",
                                 timeout=8000)
            pg.wait_for_timeout(200)

            def term_rows():
                return pg.evaluate(
                    "(()=>{var k=Object.keys(PANELS)[0];"
                    "var t=PANELS[k]&&PANELS[k].term;return t?t.rows:null;})()")
            before = term_rows()
            assert before, "no live terminal in PANELS"

            # Grow the panel body (.pin) taller — the extra height must flow into
            # the flexing terminal pane, adding ROWS.
            pg.evaluate(
                "(()=>{var k=Object.keys(PANELS)[0];var pin=PANELS[k].pin;"
                "pin.style.height='760px';})()")
            pg.wait_for_timeout(350)
            after = term_rows()
            assert after, "no terminal after vertical resize"
            assert after > before, \
                ("dragging the panel taller did not add terminal rows "
                 "(before=%s after=%s)" % (before, after))

            DEVTEST.mkdir(exist_ok=True)
            pg.screenshot(path=str(DEVTEST / "wave9_vresize.png"), full_page=True)
            assert not errors, f"JS console errors: {errors}"
            b.close()
    finally:
        try:
            ts.kill(sid)
        except Exception:
            pass
        srv.shutdown(); srv.server_close(); t.join(timeout=5)
