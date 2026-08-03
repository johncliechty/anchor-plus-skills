"""v6 Wave 3 gate — first-class session windows: maximize + free resize.

The North-Star contract (IMPLEMENTATION-PLAN Wave 3, mockup Step 2): every
session panel header carries the v5 controls (minimize / close-to-tile /
hard-kill) UNCHANGED **plus** a new MAXIMIZE (▢) toggle, and the WHOLE panel is
freely resizable (drag any edge/corner — not only the terminal sub-pane).

  - "▢"  maximize — fills the cockpit viewport (.panel.maxd) and a second click
        restores the panel to its prior size. Maximize/restore re-fit the xterm.
  - free resize — the .pin body is the resize box (CSS resize:both), so the user
        drags the panel corner to any width+height; size persists per session
        (_panelRects). Resizing re-fits the xterm.

This file follows the un-gameable v4.1 / v5 gate model (``test_run_lifecycle``):
rendered-DOM structure assertions (style/script stripped so CSS/JS strings can't
fake a pass) for the DOM half PLUS a JS-source half (the controls are built in
the RAW _PROJECT_WINDOW_JS string) PLUS a real Playwright/Chromium interaction
test that clicks the live controls and asserts geometry + terminal re-fit + no
console errors, and saves screenshots for the orchestrator. Never :8777, never
real data — stub PTY backend, temp data dir + worktree base, a throwaway git repo.
"""
import importlib
import re
import subprocess
import threading
from html.parser import HTMLParser
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


# ── env / fixtures (stub PTY, temp data+worktree, hermetic git repo) ─────────

@pytest.fixture
def gui_env(tmp_path, monkeypatch):
    """Reload the stack against an isolated temp data dir + worktree base + the
    stub PTY backend + the fake runner, with a registered project rooted at a
    hermetic temp git repo (so start_session creates a real worktree off it —
    NEVER off C:\\dev\\Anchor)."""
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
                "summarizer", "gate_adapter", "terminal_session"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import anchor_gui
    gui = importlib.reload(anchor_gui)

    repo = tmp_path / "repo"
    repo.mkdir()
    bundle = {"gui": gui, "data": data, "wbase": wbase}
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
    bundle["repo"] = repo
    yield bundle
    try:
        import pty_manager
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


def _mkproject(folder, name="P"):
    import rnd_registry
    folder.mkdir(parents=True, exist_ok=True)
    return rnd_registry.add_project(name, str(folder))


def _strip(html):
    """Return the served HTML with <style>/<script> removed, so CSS class
    definitions and JS strings can't satisfy a structural assertion."""
    b = re.sub(r"<style[\s\S]*?</style>", "", html)
    b = re.sub(r"<script[\s\S]*?</script>", "", b)
    return b


def _js(html):
    """Return ONLY the concatenated <script> bodies (the panel-manager JS)."""
    return "\n".join(re.findall(r"<script[^>]*>([\s\S]*?)</script>", html))


def _css(html):
    """Return ONLY the concatenated <style> bodies (the panel CSS)."""
    return "\n".join(re.findall(r"<style[^>]*>([\s\S]*?)</style>", html))


class _Collector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.els = []
    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        self.els.append((tag, (d.get("class") or "").split(), d))


def _parse(body):
    c = _Collector()
    c.feed(body)
    return c.els


# ── (1) RENDERED-DOM / JS-source structure assertions (positive + negative) ──

def test_panel_stack_container_rendered(gui_env, tmp_path):
    """The panel stack (where session windows live) is a real BODY element."""
    gui = gui_env["gui"]
    pid = _mkproject(tmp_path / "Ps", "Ps")["id"]
    body = _strip(gui.render_project_window_html(pid))
    ids = [d.get("id") for _, _, d in _parse(body)]
    assert "panelStack" in ids, "no #panelStack container in body"


def test_maximize_control_built_in_panel_header(gui_env, tmp_path):
    """The panel header builds a FOURTH distinct control — a maximize button
    (class 'panelbtn max', glyph '▢') wired to maximizePanel — appended to the
    bar ALONGSIDE the unchanged minimize/close/kill. (The button is created in
    the RAW _PROJECT_WINDOW_JS string; the real wiring is also asserted via
    Playwright below — this is the JS-source half, not a grep-only gate.)"""
    gui = gui_env["gui"]
    pid = _mkproject(tmp_path / "Mx", "Mx")["id"]
    js = _js(gui.render_project_window_html(pid))
    assert "'panelbtn max'" in js or '"panelbtn max"' in js, \
        "no 'panelbtn max' maximize button class in the panel header builder"
    assert "maxBtn.onclick" in js and "maximizePanel(sessionId)" in js, \
        "maximize button not wired to maximizePanel"
    assert "maxBtn.textContent = '\\u25a2'" in js \
        or "maxBtn.textContent = '▢'" in js, "maximize glyph (▢) missing"
    assert "bar.appendChild(maxBtn)" in js, "maximize button not added to the bar"
    # The function itself exists and toggles the .maxd class.
    mp = re.search(r"function maximizePanel\(sessionId\)\s*\{([\s\S]*?)\n\}", js)
    assert mp, "maximizePanel function not found"
    mbody = mp.group(1)
    assert "'maxd'" in mbody, "maximizePanel must toggle the .maxd class"
    assert "_fitPanelTerminal(sessionId)" in mbody, \
        "maximize/restore must re-fit the terminal"


def test_v5_controls_unchanged(gui_env, tmp_path):
    """The minimize / close-to-tile / kill controls are intact — maximize is
    purely additive, it does not touch the others. (W6 later unified the panel's
    destructive controls: the kill control is now the single '🪦' Kill -> Boneyard
    'panelbtn killbone', replacing the old 🗑 'panelbtn hardkill'.)"""
    gui = gui_env["gui"]
    pid = _mkproject(tmp_path / "V5", "V5")["id"]
    js = _js(gui.render_project_window_html(pid))
    assert "minBtn.onclick" in js and "minimizePanel(sessionId)" in js
    assert "'panelbtn close'" in js and "closePanel(sessionId)" in js
    assert "'panelbtn killbone'" in js and "killPanel(sessionId)" in js
    assert "closeBtn.textContent = '×'" in js
    # The whole control row appends min, max, close, kill (all four present).
    assert "bar.appendChild(minBtn)" in js
    assert "bar.appendChild(closeBtn)" in js
    assert "bar.appendChild(killBtn)" in js


def test_free_panel_resize_affordance_present(gui_env, tmp_path):
    """The WHOLE panel body (.pin) is the free-resize box — CSS resize:both — so
    the panel resizes in width AND height, not just the terminal pane."""
    gui = gui_env["gui"]
    pid = _mkproject(tmp_path / "Rz", "Rz")["id"]
    html = gui.render_project_window_html(pid)
    css = _css(html)
    # The .pin body carries resize:both (free corner resize of the panel).
    pin_rule = re.search(r"\.panel \.pin\{([^}]*)\}", css)
    assert pin_rule, ".panel .pin CSS rule not found"
    assert "resize:both" in pin_rule.group(1), \
        ".pin must be freely resizable (resize:both) — the whole panel resizes"
    # A maxd overlay rule exists (fixed fill + high z-index).
    assert re.search(r"\.panel\.maxd\{[^}]*position:fixed", css), \
        ".panel.maxd must be a fixed full-viewport overlay"
    assert re.search(r"\.panel\.maxd\{[^}]*z-index:\d", css), \
        ".panel.maxd must have a high z-index"
    js = _js(html)
    assert "_panelRects" in js, "free-resize size must persist per session"


def test_terminal_pane_only_resize_is_no_longer_the_only_resize(gui_env, tmp_path):
    """NEGATIVE vs v5: in v5 the ONLY resizable thing was the terminal sub-pane
    (.tpane{resize:vertical}). Now the PANEL itself (.pin) is freely resizable, so
    the resize affordance is no longer terminal-pane-only. We assert the .pin
    free-resize box is present AND the wiring observes the .pin (not just tpane)."""
    gui = gui_env["gui"]
    pid = _mkproject(tmp_path / "Ng", "Ng")["id"]
    html = gui.render_project_window_html(pid)
    css = _css(html)
    # The panel body is resizable (the new free-resize), not only the tpane.
    assert re.search(r"\.panel \.pin\{[^}]*resize:both", css)
    js = _js(html)
    # _wirePanelResize now also observes the .pin body (free resize) and persists
    # _panelRects — proving resize is no longer terminal-pane-height-only.
    wr = re.search(r"function _wirePanelResize\([\s\S]*?\n\}\n", js)
    assert wr, "_wirePanelResize not found"
    wbody = wr.group(0)
    assert "p.pin" in wbody, "_wirePanelResize must observe the .pin free-resize box"
    assert "_panelRects[sessionId]" in wbody, \
        "panel rect (w+h) must be persisted on a .pin resize"


# ── (2) REAL Playwright + Chromium interaction test (dev-only) + screenshots ──

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
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


@pytest.mark.skipif(not _have_git(), reason="git not on PATH")
def test_maximize_resize_refit_end_to_end(server):
    """The Wave-3 window controls, end to end in a real browser:

      1. Start a live stub-PTY session; open its panel (the xterm mounts).
      2. Click ▢ (MAXIMIZE) → the panel gets .maxd, (approx) fills the viewport,
         and the terminal re-fits (cols/rows grow vs the normal size).
      3. Click ▢ again (RESTORE) → .maxd is gone and the panel returns to its
         prior rect; the terminal re-fits back.
      4. Resize the panel body (.pin) larger → the panel grows AND the terminal
         re-fits (cols/rows change); the size persists in _panelRects.
      5. NO JS console errors throughout.

    Saves _devtest/wave3_normal.png + wave3_maxed.png for orchestrator review.
    """
    pytest.importorskip("playwright.sync_api")
    bundle, base, _ = server
    import terminal_session as ts
    pid = bundle["pid"]
    rec = ts.start_session(pid, "research", backend="claude")
    sid = rec["session_id"]
    DEVTEST.mkdir(exist_ok=True)

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1280, "height": 900})
        errors = []
        pg.on("console",
              lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.on("dialog", lambda d: d.accept())
        pg.goto(f"{base}/project/{pid}", wait_until="networkidle")
        from tests.ui_helpers import expand_workbench
        expand_workbench(pg)  # the Workbench tile now opens collapsed

        # The live session surfaces as a reopenable chip; open its panel.
        chip_sel = '#sessionBar .live-chip[data-session="%s"]' % sid
        pg.wait_for_selector(chip_sel, timeout=8000)
        pg.click(chip_sel)
        pg.wait_for_selector("#panelStack .panel", timeout=5000)
        # The xterm terminal mounts (a .xterm canvas/host appears).
        pg.wait_for_selector("#panelStack .panel .term-host .xterm", timeout=8000)

        # The header has the new MAXIMIZE control alongside the v5 trio.
        assert pg.eval_on_selector_all(
            "#panelStack .panel .panelbtn.max", "e=>e.length") == 1
        assert pg.eval_on_selector_all(
            "#panelStack .panel .panelbtn.min", "e=>e.length") == 1
        assert pg.eval_on_selector_all(
            "#panelStack .panel .panelbtn.close", "e=>e.length") == 1
        # W6 unified the kill control into the single '🪦' Kill -> Boneyard.
        assert pg.eval_on_selector_all(
            "#panelStack .panel .panelbtn.killbone", "e=>e.length") == 1

        pg.wait_for_timeout(150)
        # Record the normal-state terminal dimensions (cols×rows).
        def term_dims():
            return pg.evaluate(
                "(()=>{var k=Object.keys(PANELS)[0];var t=PANELS[k]&&PANELS[k].term;"
                "return t?{cols:t.cols,rows:t.rows}:null;})()")
        normal = term_dims()
        assert normal, "no live terminal in PANELS"
        pg.screenshot(path=str(DEVTEST / "wave3_normal.png"))

        # 2) MAXIMIZE → .maxd present + fills (most of) the viewport.
        pg.click("#panelStack .panel .panelbtn.max")
        pg.wait_for_function(
            "document.querySelector('#panelStack .panel.maxd') !== null",
            timeout=5000)
        pg.wait_for_timeout(200)
        box = pg.eval_on_selector("#panelStack .panel.maxd",
                                  "e=>{var r=e.getBoundingClientRect();"
                                  "return {w:r.width,h:r.height};}")
        vp = pg.evaluate("({w:window.innerWidth,h:window.innerHeight})")
        assert box["w"] >= vp["w"] * 0.9, "maximized panel does not fill the width"
        assert box["h"] >= vp["h"] * 0.9, "maximized panel does not fill the height"
        maxed = term_dims()
        # The terminal re-fit: maximized cols are larger than normal (the panel is
        # much wider than its stacked width). Be tolerant — assert non-shrink + a
        # real grow in at least one dimension.
        assert maxed, "no terminal after maximize"
        assert maxed["cols"] >= normal["cols"] and maxed["rows"] >= normal["rows"]
        assert (maxed["cols"] > normal["cols"]) or (maxed["rows"] > normal["rows"]), \
            "terminal did not re-fit on maximize (cols/rows unchanged)"
        pg.screenshot(path=str(DEVTEST / "wave3_maxed.png"))

        # 3) RESTORE → .maxd gone, panel back, terminal re-fits back.
        pg.click("#panelStack .panel .panelbtn.max")
        pg.wait_for_function(
            "document.querySelector('#panelStack .panel.maxd') === null",
            timeout=5000)
        pg.wait_for_timeout(200)
        restored = term_dims()
        assert restored, "no terminal after restore"
        assert restored["cols"] <= maxed["cols"], \
            "terminal did not re-fit back smaller on restore"

        # 4) FREE RESIZE the panel body — the WHOLE panel (width) is resizable, not
        #    just the terminal sub-pane. Shrink it first (the stacked column is
        #    already full-width, so narrowing is the headroom), capture the smaller
        #    fit, then grow it back and assert the terminal re-fit each way + the
        #    size persists in _panelRects.
        pg.evaluate(
            "(()=>{var k=Object.keys(PANELS)[0];var pin=PANELS[k].pin;"
            "pin.style.width='520px';})()")
        pg.wait_for_timeout(250)
        narrow = term_dims()
        assert narrow, "no terminal after narrow resize"
        assert narrow["cols"] < restored["cols"], \
            "terminal did not re-fit smaller when the panel was narrowed"
        narrow_rect = pg.evaluate(
            "(()=>{var k=Object.keys(PANELS)[0];return _panelRects[k]||null;})()")
        assert narrow_rect and narrow_rect.get("w"), \
            "panel rect (w) not persisted in _panelRects after a free resize"

        pg.evaluate(
            "(()=>{var k=Object.keys(PANELS)[0];var pin=PANELS[k].pin;"
            "pin.style.width='1000px';})()")
        pg.wait_for_timeout(250)
        wider = term_dims()
        assert wider, "no terminal after wider resize"
        assert wider["cols"] > narrow["cols"], \
            "terminal did not re-fit wider when the panel was grown"

        assert not errors, f"JS console errors during window controls: {errors}"
        b.close()

    assert (DEVTEST / "wave3_normal.png").exists()
    assert (DEVTEST / "wave3_maxed.png").exists()
