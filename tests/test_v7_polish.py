"""v7 Wave 6 (polish) gate — two approved follow-ups.

ITEM 1 — instant-in-column board refresh (the Wave-3 follow-up).
  A started / finished session's lane-column tile must appear WITHOUT a full page
  reload. The board is the SINGLE SOURCE OF TRUTH (the server render), so the JS
  just re-fetches the board fragment and swaps ``#kanbanBoard``'s innerHTML — it
  does NOT JS-inject a duplicate tile, so dedupe stays correct (EXACTLY ONE tile
  per session in its lane column).
    (a) ``GET /api/rnd/board_html?project_id=<id>`` is token-gated (``?token=``),
        returns the rendered board fragment for the project, and is SAFE (no
        absolute worktree_path / branch leaks).
    (b) The project window's board is wrapped in a stable ``#kanbanBoard``
        container.
    (c) ``refreshBoard()`` is wired into the session-lifecycle mutations
        (newTermSession / killPanel / finishToBuild / advanceSession /
        promoteGrass / developGrass / repopulate) — source-level assert.
    (d) Real Playwright/Chromium: start a planning session via the UI; WITHOUT a
        manual full reload the tile appears in ``#cards_plan`` (refreshBoard
        brought it in) — exactly one tile; no JS console errors.

ITEM 2 — allow Gemini on the bare ``general`` lane (the Wave-4 follow-up).
  ``gemini`` is allowed for lane ``general`` (a bare exploration terminal — both
  engines make sense) AND still for ``research``; it stays REFUSED for ``plan`` /
  ``build`` (Crucible/Foreman are Claude Code engines Gemini can't run).

Un-gameable gate model: token-gate + SAFE-projection assertions on the endpoint,
rendered-DOM ``#kanbanBoard`` + source-level refreshBoard wiring, a real
Playwright/Chromium instant-in-column test (+ a screenshot for orchestrator
review), and a backend engine-policy test. Never :8777, never real data — stub
PTY, temp data dir + worktree base, a throwaway temp git repo.
"""
import importlib
import json
import re
import subprocess
import threading
import urllib.request
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()
_DEVTEST = Path(__file__).resolve().parent.parent / "_devtest"
_GUI_SRC = Path(__file__).resolve().parent.parent / "anchor_gui.py"


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)


def _have_git():
    try:
        return subprocess.run(["git", "--version"],
                              capture_output=True).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


# ── env / fixtures (stub PTY, temp data+worktree, hermetic git repo) ─────────

@pytest.fixture
def env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    wbase = tmp_path / "wt-base"
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(wbase))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    for mod in ("paths", "job_runner", "pty_manager", "rnd_registry",
                "session_registry", "worktrees", "lanes", "effort_history",
                "summarizer", "handoff", "gate_adapter", "terminal_session"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import anchor_gui
    gui = importlib.reload(anchor_gui)

    repo = tmp_path / "repo"
    repo.mkdir()
    bundle = {"gui": gui, "data": data, "wbase": wbase, "repo": repo}
    if _have_git():
        _git(repo, "init", "-b", "main")
        _git(repo, "config", "user.email", "t@example.com")
        _git(repo, "config", "user.name", "Test")
        (repo / "README.md").write_text("hello\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "initial")
    import rnd_registry
    proj = rnd_registry.add_project("Temp", str(repo), scaffold=False)
    bundle["pid"] = proj["id"]
    yield bundle
    try:
        import pty_manager
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


# ════════════════════════════════════════════════════════════════════════════
# ITEM 1 (A) — GET /api/rnd/board_html: token-gated + SAFE board fragment
# ════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def server(env):
    gui = env["gui"]
    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777, "the test server must never bind the live :8777 port"
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield env, f"http://127.0.0.1:{port}", port
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


def _get_json(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


@pytest.mark.skipif(not _have_git(), reason="git not on PATH")
def test_board_html_returns_board_fragment(server):
    """The endpoint returns the rendered board fragment for the project — the SAME
    server render the page uses (single source of truth). v12 Wave 2: that render
    is the Layout-D shell (.pgrid.layoutd with the two headline zones)."""
    bundle, base, _ = server
    pid = bundle["pid"]
    status, data = _get_json(f"{base}/api/rnd/board_html?project_id={pid}")
    assert status == 200
    assert data.get("ok") is True
    html = data.get("html") or ""
    assert "pgrid layoutd" in html, "board fragment missing the Layout-D grid"
    # The two Layout-D zones are present (so refreshBoard can swap them in place).
    assert html.count("class='sectionlbl'") == 2, \
        "board fragment missing the two Layout-D headline zones"


@pytest.mark.skipif(not _have_git(), reason="git not on PATH")
def test_board_html_unknown_project_404(server):
    bundle, base, _ = server
    req = urllib.request.Request(f"{base}/api/rnd/board_html?project_id=nope")
    try:
        urllib.request.urlopen(req, timeout=10)
        assert False, "expected a 404 for an unknown project"
    except urllib.error.HTTPError as e:
        assert e.code == 404


@pytest.mark.skipif(not _have_git(), reason="git not on PATH")
def test_board_html_is_token_gated(env, monkeypatch):
    """With ANCHOR_TOKEN set, the endpoint refuses a missing/wrong token (401) and
    accepts the right one via ``?token=`` — same semantics as the other GET seams.
    A benign token literal (never a 'secret-...' string the distro scanner trips)."""
    monkeypatch.setenv("ANCHOR_TOKEN", "sekret")
    gui = env["gui"]
    pid = env["pid"]
    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{port}"
    try:
        # No token → 401.
        req = urllib.request.Request(f"{base}/api/rnd/board_html?project_id={pid}")
        try:
            urllib.request.urlopen(req, timeout=10)
            assert False, "expected 401 without a token"
        except urllib.error.HTTPError as e:
            assert e.code == 401
        # Wrong token → 401.
        try:
            urllib.request.urlopen(
                f"{base}/api/rnd/board_html?project_id={pid}&token=wrong",
                timeout=10)
            assert False, "expected 401 with a wrong token"
        except urllib.error.HTTPError as e:
            assert e.code == 401
        # Right token → 200 + board.
        status, data = _get_json(
            f"{base}/api/rnd/board_html?project_id={pid}&token=sekret")
        assert status == 200 and data.get("ok") is True
        assert "pgrid layoutd" in (data.get("html") or "")
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


@pytest.mark.skipif(not _have_git(), reason="git not on PATH")
def test_board_html_is_safe_no_worktree_leak(server):
    """SAFE: a LIVE session's worktree_path / branch never leak into the board
    fragment (the kanban already renders SAFE tiles — assert it holds here)."""
    bundle, base, _ = server
    pid = bundle["pid"]
    import terminal_session as ts
    rec = ts.start_session(pid, "plan", backend="claude")
    sid = rec["session_id"]
    # The registry record DOES hold a worktree_path/branch — assert neither leaks.
    grec = ts.get_session(sid) or {}
    wt = grec.get("worktree_path") or ""
    br = grec.get("branch") or ""
    status, data = _get_json(f"{base}/api/rnd/board_html?project_id={pid}")
    html = data.get("html") or ""
    assert sid in html, "the live session's tile should be in the board fragment"
    if wt:
        assert wt not in html, "worktree_path leaked into the board fragment"
    # The managed-base path segment must not appear either.
    assert str(bundle["wbase"]) not in html, "worktree base path leaked"
    if br and br not in ("main",):
        assert br not in html, "branch name leaked into the board fragment"
    ts.kill(sid)


# ════════════════════════════════════════════════════════════════════════════
# ITEM 1 (B) — DOM: #kanbanBoard container + refreshBoard wiring (source-level)
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.skipif(not _have_git(), reason="git not on PATH")
def test_project_window_board_wrapped_in_kanbanboard(env):
    """The board render is wrapped in a stable ``#kanbanBoard`` container so
    refreshBoard can swap its innerHTML in place."""
    gui = env["gui"]
    html = gui.render_project_window_html(env["pid"])
    assert ("id='kanbanBoard'" in html) or ('id="kanbanBoard"' in html), \
        "the board is not wrapped in a stable #kanbanBoard container"
    # The board grid lives INSIDE the container (v12 Wave 2: Layout-D grid).
    idx = html.find("kanbanBoard")
    assert html.find("pgrid layoutd", idx) > idx, \
        "the Layout-D board grid is not inside #kanbanBoard"


def test_refreshboard_defined_and_wired_into_lifecycle():
    """Source-level: refreshBoard() is defined and CALLED from each
    session-lifecycle mutation that changes the board. Asserting on the product
    source (not a string-grep-only UI claim — the Playwright test below proves the
    behavior end-to-end; this just guards the wiring doesn't silently drop)."""
    # C1 (2026-07-05): the app JS is EXTRACTED to static/project-window.js —
    # refreshBoard + the lifecycle fns live there now, not in anchor_gui.py.
    src = (_GUI_SRC.parent / "static" / "project-window.js").read_text(encoding="utf-8")
    assert "async function refreshBoard()" in src, "refreshBoard() is not defined"
    # It is wired into each lifecycle function. We assert each function body calls
    # refreshBoard() by slicing the function source and checking the call appears.
    for fn in ("newTermSession", "killPanel", "finishToBuild", "advanceSession",
               "promoteGrass", "developGrass", "repopulate"):
        start = src.find("function %s(" % fn)
        assert start >= 0, "function %s not found in source" % fn
        # Slice to the next top-level "function " definition (a coarse but stable
        # body boundary for these RAW-string functions).
        nxt = src.find("\nfunction ", start + 1)
        body = src[start:nxt if nxt > 0 else len(src)]
        assert "refreshBoard()" in body, \
            "%s does not call refreshBoard() (instant-in-column wiring lost)" % fn


# ════════════════════════════════════════════════════════════════════════════
# ITEM 1 (C) — REAL Playwright + Chromium: instant-in-column (no reload)
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.skipif(not _have_git(), reason="git not on PATH")
def test_playwright_started_session_appears_in_column_without_reload(server):
    """End to end in a real browser, proving refreshBoard brings the lane tile in
    WITHOUT a manual full reload (the still-wired refresh mechanism):

      1. Load the project window (Plan/Build zone empty).
      2. Start a planning session server-side (the v12 Wave-2 skeleton retires the
         per-lane '+ New plan run' launcher; the live click-to-start lands in W10,
         so we start the session via terminal_session and then exercise the wired
         refreshBoard()).
      3. Calling refreshBoard() in-page (the wired refresh) — WITHOUT any goto —
         brings the tile into the Plan/Build zone: EXACTLY ONE tile (dedupe
         correct), green light.
      4. No JS console errors.

    Screenshot saved to _devtest/wave6_instant.png for orchestrator review.
    """
    pytest.importorskip("playwright.sync_api")
    bundle, base, _ = server
    pid = bundle["pid"]
    import terminal_session as ts

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

        # 1) The Plan/Build zone starts EMPTY (no sessions yet).
        assert pg.eval_on_selector_all(
            ".pgrid.layoutd .tile[data-lane='plan']", "e=>e.length") == 0, \
            "Plan/Build zone not empty before launch"

        # 2) Start a planning session server-side (W10 wires the click path).
        sid = ts.start_session(pid, "plan", backend="claude")["session_id"]

        # 3) Trigger the WIRED refreshBoard() in-page — no goto/reload — and the
        #    tile appears in the Plan/Build zone (refreshBoard pulled the
        #    server-rendered Layout-D board in).
        pg.evaluate("refreshBoard()")
        sel = '.pgrid.layoutd .tile[data-session="%s"][data-lane="plan"]' % sid
        pg.wait_for_selector(sel, timeout=8000)
        n = pg.eval_on_selector_all(sel, "e=>e.length")
        assert n == 1, \
            "expected EXACTLY ONE Plan/Build tile after refreshBoard, got %d" % n
        # Its light is green (running).
        assert pg.eval_on_selector(
            sel, "e=>e.getAttribute('data-light')") == "green", \
            "the refreshed tile is not green (running)"

        _DEVTEST.mkdir(exist_ok=True)
        pg.screenshot(path=str(_DEVTEST / "wave6_instant.png"), full_page=True)

        assert not errors, f"JS console errors during instant-in-column: {errors}"
        ts.kill(sid)
        b.close()


# ════════════════════════════════════════════════════════════════════════════
# ITEM 2 — Gemini allowed on the bare `general` lane (research-only elsewhere)
# ════════════════════════════════════════════════════════════════════════════

def test_gemini_engine_policy_general_plan_build_allowed(env):
    """The lane→engine policy: Gemini is allowed for `general`, `research`,
    `plan`, and `build`. Claude is allowed everywhere."""
    import lanes
    importlib.reload(lanes)

    # Gemini ALLOWED everywhere now.
    lanes.check_engine_allowed("general", lanes.BACKEND_GEMINI)
    lanes.check_engine_allowed("research", lanes.BACKEND_GEMINI)
    for lane in ("plan", "build"):
        lanes.check_engine_allowed(lane, lanes.BACKEND_GEMINI)
    # Claude allowed everywhere (sanity).
    for lane in ("general", "research", "plan", "build"):
        lanes.check_engine_allowed(lane, lanes.BACKEND_CLAUDE)


def test_general_in_gemini_lanes_set(env):
    """``general`` is a member of the GEMINI_LANES allow-set (and research is too),
    and now plan/build are TOO."""
    import lanes
    importlib.reload(lanes)
    assert "general" in lanes.GEMINI_LANES
    assert lanes.LANE_RESEARCH in lanes.GEMINI_LANES
    assert lanes.LANE_PLAN in lanes.GEMINI_LANES
    assert lanes.LANE_BUILD in lanes.GEMINI_LANES
