"""v5 Wave 1 gate — run lifecycle: CLOSE-to-tile vs. deliberate hard-KILL.

The North-Star contract (MASTER-PLAN Locked Decision #1, IMPLEMENTATION-PLAN
Wave 1): the project-window panel header has THREE visually + behaviorally
distinct controls:

  - "–"  minimize  — collapse to a header strip; the session keeps running.
  - "×"  CLOSE     — close-to-tile: tear down the panel DOM + transport ONLY.
        It must NOT kill the PTY / remove the worktree / drop the registry record
        / remove the tile. The session stays reopenable.
  - "🗑" KILL      — a SEPARATE, confirm-gated control. On confirm POSTs
        /api/rnd/term_kill (reap PTY + remove worktree + mark registry terminal),
        then removes the MANAGED record AND the tile so it's gone.

This file follows the un-gameable v4.1 gate model (``test_cockpit_paradigm2``):
rendered-DOM structure assertions (style/script stripped so CSS/JS strings can't
fake a pass) PLUS a real Playwright/Chromium interaction test PLUS hermetic
backend (registry/PTY) assertions. Never :8777, never real data — stub PTY
backend, temp data dir + worktree base, a throwaway temp git repo.
"""
import importlib
import re
import socket
import subprocess
import threading
from html.parser import HTMLParser
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()


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
    stub PTY backend + the fake runner. Returns the reloaded anchor_gui plus a
    registered project rooted at a hermetic temp git repo (so start_session can
    create a real worktree off it — NEVER off C:\\dev\\Anchor)."""
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


# ── (1) RENDERED-DOM / structure assertions (positive + negative) ────────────

def test_session_bar_container_rendered_in_body(gui_env, tmp_path):
    """The live-session bar (the reopen vector for closed-to-tile live sessions)
    is a real element in the served BODY, distinct from the panel stack."""
    gui = gui_env["gui"]
    folder = tmp_path / "Sb"
    pid = _mkproject(folder, "Sb")["id"]
    body = _strip(gui.render_project_window_html(pid))
    els = _parse(body)
    ids = [d.get("id") for _, _, d in els]
    assert "sessionBar" in ids, "no #sessionBar live-session container in body"
    assert "panelStack" in ids, "panel stack missing"


def test_three_distinct_panel_controls_defined_in_js(gui_env, tmp_path):
    """The panel header builds two DISTINCT lifecycle controls (W6 unification):
    a '×' CLOSE button (class 'close', routing to the non-killing closePanel) and
    a single '🪦' Kill -> Boneyard button (class 'killbone', routing to the
    confirm-gated killPanel). They are different elements/classes — close and kill
    are NOT the same control. (W6 collapsed the old redundant close/hardkill/delete
    trio into these two; the panel no longer has a 'hardkill' or a 'delete'.)

    (The controls are created in the RAW _PROJECT_WINDOW_JS string; the real
    button wiring is also asserted via Playwright below — this is the JS-source
    half, not a grep-only gate.)"""
    gui = gui_env["gui"]
    folder = tmp_path / "Ctl"
    pid = _mkproject(folder, "Ctl")["id"]
    js = _js(gui.render_project_window_html(pid))
    # close control: a 'panelbtn close' whose handler is closePanel (non-killing).
    assert "'panelbtn close'" in js or '"panelbtn close"' in js
    assert "closeBtn.onclick" in js and "closePanel(sessionId)" in js
    # kill control: a SEPARATE 'panelbtn killbone' (Kill -> Boneyard) whose handler
    # is the confirm-gated killPanel.
    assert "'panelbtn killbone'" in js or '"panelbtn killbone"' in js
    assert "killBtn.onclick" in js and "killPanel(sessionId)" in js
    # NEGATIVE — the old redundant panel controls are gone (W6 unification): the
    # panel builds no 'panelbtn hardkill' and no 'panelbtn delete'.
    assert "'panelbtn hardkill'" not in js and '"panelbtn hardkill"' not in js
    assert "'panelbtn delete'" not in js and '"panelbtn delete"' not in js
    # they are distinct buttons appended both to the bar.
    assert "bar.appendChild(closeBtn)" in js
    assert "bar.appendChild(killBtn)" in js


def test_kill_is_confirm_gated_and_close_is_not(gui_env, tmp_path):
    """killPanel guards with confirm() and only then POSTs term_kill; closePanel
    NEVER calls confirm and NEVER POSTs term_kill (it just tears down the DOM)."""
    gui = gui_env["gui"]
    folder = tmp_path / "Cf"
    pid = _mkproject(folder, "Cf")["id"]
    js = _js(gui.render_project_window_html(pid))
    # Isolate each function body.
    kp = re.search(r"async function killPanel\(sessionId\)\s*\{([\s\S]*?)\n\}", js)
    cp = re.search(r"function closePanel\(sessionId\)\s*\{([\s\S]*?)\n\}", js)
    assert kp, "killPanel not found"
    assert cp, "closePanel not found"
    kbody, cbody = kp.group(1), cp.group(1)
    # KILL: confirm-gated AND reaps via term_kill AND removes the tile.
    assert "confirm(" in kbody, "kill must be confirm-gated"
    assert "/api/rnd/term_kill" in kbody, "kill must reap via term_kill"
    assert "_removeSessionTile(sessionId)" in kbody, "kill must drop the tile"
    # CLOSE: NOT confirm-gated AND does NOT reap (the old '× == kill' is gone).
    assert "confirm(" not in cbody, "close must NOT prompt-to-kill"
    assert "term_kill" not in cbody, "close must NOT reap the session"
    assert "_removeSessionTile" not in cbody, "close must NOT remove the tile"
    assert "_closePanel(sessionId)" in cbody, "close must tear down the panel DOM"


def test_old_x_equals_kill_for_live_is_gone(gui_env, tmp_path):
    """NEGATIVE: the replaced behavior — the panel '×' wired straight to killPanel
    for a live session — must be absent. The '×' button (closeBtn) now routes to
    closePanel; only the SEPARATE Kill -> Boneyard button routes to killPanel."""
    gui = gui_env["gui"]
    folder = tmp_path / "Neg"
    pid = _mkproject(folder, "Neg")["id"]
    js = _js(gui.render_project_window_html(pid))
    # The old single kill-or-close button name + branching is gone.
    assert "killBtn.textContent = '×'" not in js, \
        "the × glyph must no longer be the kill control"
    # closeBtn carries the × glyph and routes to the non-killing path.
    assert "closeBtn.textContent = '×'" in js
    # The Kill -> Boneyard button uses a DISTINCT glyph — the headstone 🪦
    # (U+1FAA6), never × (and no longer the old 🗑 U+1F5D1).
    assert "killBtn.textContent = '\\U0001faa6'" in js \
        or "killBtn.textContent = '🪦'" in js, "kill glyph must be the headstone 🪦"
    assert "killBtn.textContent = '\\U0001f5d1'" not in js \
        and "killBtn.textContent = '🗑'" not in js, \
        "the old 🗑 kill glyph must be gone (W6)"


# ── (3) BACKEND registry/PTY assertions (no browser) ─────────────────────────

@pytest.mark.skipif(not _have_git(), reason="git not on PATH")
def test_term_kill_reaps_pty_and_removes_worktree(gui_env):
    """The KILL backend (term_kill → terminal_session.kill) reaps the live PTY,
    marks the registry record terminal, and removes the worktree (no orphan)."""
    import terminal_session as ts
    import session_registry as reg
    import pty_manager
    pid = gui_env["pid"]
    rec = ts.start_session(pid, "plan", backend="claude")
    sid = rec["session_id"]
    wt = Path(rec["worktree_path"])
    assert wt.exists()
    assert sid in pty_manager.live_sessions()
    assert reg.get_session(sid)["status"] == reg.STATUS_RUNNING

    out = ts.kill(sid)
    assert out["ok"] is True
    assert sid not in pty_manager.live_sessions(), "PTY not reaped"
    assert reg.get_session(sid)["status"] in reg.TERMINAL_STATUSES, \
        "registry record not marked terminal"
    assert not wt.exists(), "worktree not removed (orphan left behind)"


@pytest.mark.skipif(not _have_git(), reason="git not on PATH")
def test_close_does_not_reap_only_kill_does(gui_env):
    """CLOSE keeps the work: there is no server endpoint that close hits (it is a
    pure client-side DOM teardown), so the registry record + the live PTY persist
    after a close. Only the explicit kill reaps. This locks Risk R1 (close must
    never leak into a reap)."""
    import terminal_session as ts
    import session_registry as reg
    import pty_manager
    pid = gui_env["pid"]
    rec = ts.start_session(pid, "research", backend="claude")
    sid = rec["session_id"]
    wt = Path(rec["worktree_path"])
    # Simulate a close-to-tile: the client tears down the panel DOM only; it does
    # NOT call any backend. So the registry + PTY are untouched.
    assert sid in pty_manager.live_sessions()
    assert reg.get_session(sid)["status"] == reg.STATUS_RUNNING
    assert wt.exists()
    # The session is still resolvable + attachable (i.e. reopenable).
    att = ts.attach(sid)
    assert att["ok"] is True
    assert att["status"] == "running"
    # Now the deliberate kill reaps it.
    ts.kill(sid)
    assert sid not in pty_manager.live_sessions()
    assert not wt.exists()


def test_term_kill_endpoint_is_token_gated(gui_env, tmp_path, monkeypatch):
    """The term_kill endpoint stays behind the do_POST token gate (mutating /
    terminal). With a token set, an unauthenticated POST is rejected."""
    import importlib
    import json as _json
    import urllib.request
    import urllib.error
    monkeypatch.setenv("ANCHOR_TOKEN", "sekret")
    import paths
    importlib.reload(paths)
    import anchor_gui
    gui = importlib.reload(anchor_gui)
    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/rnd/term_kill",
            data=_json.dumps({"session": "nope"}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            urllib.request.urlopen(req, timeout=5)
            unauth_status = 200
        except urllib.error.HTTPError as e:
            unauth_status = e.code
        assert unauth_status in (401, 403), \
            f"term_kill must reject unauthed POST, got {unauth_status}"
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


# ── (2) REAL Playwright + Chromium interaction test (dev-only) ───────────────

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
def test_close_keeps_tile_reopen_then_kill_removes_it(server):
    """The core lifecycle, end to end in a real browser:

      1. Start a live stub-PTY session (the panel + a reopenable live chip).
      2. Click × (CLOSE) → the panel is gone BUT the chip/tile remains AND the
         registry record PERSISTS (W6 graceful park: the PTY is stopped and the
         record is re-statused STATUS_IDLE, reopenable WARM — never dropped).
      3. Click the chip → the panel REOPENS.
      4. Click 🪦 (Kill -> Boneyard), accept the confirm → the panel is gone, the
         chip is gone, and the registry record is reaped (status terminal).

    No JS console errors throughout.
    """
    pytest.importorskip("playwright.sync_api")
    bundle, base, _ = server
    import terminal_session as ts
    import session_registry as reg
    import pty_manager
    pid = bundle["pid"]
    # Start a live session up front; the page's repopulate() pulls it into the
    # session bar as a reopenable chip on load.
    rec = ts.start_session(pid, "research", backend="claude")
    sid = rec["session_id"]

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        errors = []
        pg.on("console",
              lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.on("dialog", lambda d: d.accept())   # accept the kill confirm()
        pg.goto(f"{base}/project/{pid}", wait_until="networkidle")
        from tests.ui_helpers import expand_workbench
        expand_workbench(pg)  # the Workbench tile now opens collapsed

        # The live session surfaces as a reopenable chip in the session bar.
        chip_sel = '#sessionBar .live-chip[data-session="%s"]' % sid
        pg.wait_for_selector(chip_sel, timeout=8000)
        assert pg.eval_on_selector_all("#panelStack .panel",
                                       "e=>e.length") == 0
        # Open the panel.
        pg.click(chip_sel)
        pg.wait_for_selector("#panelStack .panel", timeout=5000)
        assert pg.eval_on_selector_all("#panelStack .panel",
                                       "e=>e.length") == 1
        # The panel header has a CLOSE (.panelbtn.close) AND a distinct Kill ->
        # Boneyard (.panelbtn.killbone) — two different controls (W6 unified).
        assert pg.eval_on_selector_all(
            "#panelStack .panel .panelbtn.close", "e=>e.length") == 1
        assert pg.eval_on_selector_all(
            "#panelStack .panel .panelbtn.killbone", "e=>e.length") == 1
        # The old redundant panel controls are gone.
        assert pg.eval_on_selector_all(
            "#panelStack .panel .panelbtn.hardkill", "e=>e.length") == 0
        assert pg.eval_on_selector_all(
            "#panelStack .panel .panelbtn.delete", "e=>e.length") == 0

        # 2) CLOSE (×): panel gone, chip remains, record PERSISTS (parked idle).
        #    W6 graceful park — the PTY is STOPPED and the record is re-statused
        #    STATUS_IDLE, but the record + tile stay (reopenable WARM). Only KILL
        #    reaps + removes the tile.
        pg.click("#panelStack .panel .panelbtn.close")
        pg.wait_for_function(
            "document.querySelectorAll('#panelStack .panel').length === 0",
            timeout=5000)
        assert pg.eval_on_selector_all(chip_sel, "e=>e.length") == 1, \
            "close removed the chip (work lost) — must keep it reopenable"
        assert sid not in pty_manager.live_sessions(), \
            "close should STOP the PTY (graceful park)"
        assert reg.get_session(sid) is not None, "close must KEEP the record"
        assert reg.get_session(sid)["status"] == reg.STATUS_IDLE

        # 3) Reopen from the chip → panel comes back.
        pg.click(chip_sel)
        pg.wait_for_selector("#panelStack .panel", timeout=5000)
        assert pg.eval_on_selector_all("#panelStack .panel",
                                       "e=>e.length") == 1

        # 4) KILL (🪦 Kill -> Boneyard): confirm accepted → panel gone, chip gone,
        #    session reaped.
        pg.click("#panelStack .panel .panelbtn.killbone")
        pg.wait_for_function(
            "document.querySelectorAll('#panelStack .panel').length === 0",
            timeout=5000)
        pg.wait_for_function(
            "document.querySelectorAll('%s').length === 0" % chip_sel,
            timeout=5000)
        assert pg.eval_on_selector_all(chip_sel, "e=>e.length") == 0, \
            "kill did not remove the tile"
        # REGRESSION GUARD (Wave 1 adversarial finding): killPanel ends with
        # setTimeout(repopulate, 400); a killed session is marked 'done' (terminal)
        # in the registry, so term_sessions still reports it. Wait PAST that
        # repopulate and re-assert the chip stays gone — a terminal session must
        # NEVER re-enter the live bar (else the killed tile reappears ~400ms later).
        pg.wait_for_timeout(900)
        assert pg.eval_on_selector_all(chip_sel, "e=>e.length") == 0, \
            "killed chip REAPPEARED after repopulate() (terminal session re-synced)"
        assert pg.eval_on_selector_all("#panelStack .panel", "e=>e.length") == 0, \
            "a panel reappeared after the post-kill repopulate"
        assert not errors, f"JS console errors during lifecycle: {errors}"
        b.close()

    # Backend truth after the browser kill: PTY reaped, record terminal.
    assert sid not in pty_manager.live_sessions(), "kill left an orphan PTY"
    assert reg.get_session(sid)["status"] in reg.TERMINAL_STATUSES
