"""v6 Wave 4 gate — tile lifecycle: new-session=new-tile + keep finished
(newest-prominent + "previously done").

The North-Star contract (IMPLEMENTATION-PLAN Wave 4):

  (a) EVERY session-start front-end path (newTermSession / continueSession /
      promoteGrass / developGrass / pullGrass) appends a DISTINCT new tile to the
      tiles row — none reuse/replace an existing tile (each keys on a fresh
      server-minted session_id → a new MANAGED entry → renderSessionBar).

  (b) FINISHED (done/failed) sessions are KEPT in the tiles row as greyed,
      reopenable tiles (v5 dropped them). Per lane the most-recent finished
      session is the prominent tile; older ones collapse under a "previously
      done (N)" expander. Clicking a finished tile opens its (read-only) summary
      panel. Closing keeps the tile (v5); only a deliberate hard-kill removes it.

This follows the un-gameable v4.1 gate model: rendered-DOM / JS-source structure
assertions (style/script handled explicitly so a CSS/JS string can't fake a
structural pass) PLUS a real Playwright/Chromium interaction test PLUS hermetic
backend assertions on the term_sessions projection. Never :8777, never real data
— stub PTY backend, temp data dir + worktree base, a throwaway temp git repo.
"""
import importlib
import json as _json
import re
import subprocess
import threading
import urllib.request
import urllib.error
from html.parser import HTMLParser
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()
_DEVTEST = Path(__file__).resolve().parent.parent / "_devtest"


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
    registered project rooted at a hermetic temp git repo."""
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
    b = re.sub(r"<style[\s\S]*?</style>", "", html)
    b = re.sub(r"<script[\s\S]*?</script>", "", b)
    return b


def _js(html):
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


# ── (1) JS-source / DOM structure assertions (positive + negative) ───────────

def test_every_start_path_mints_a_distinct_tile(gui_env, tmp_path):
    """POSITIVE: each PROJECT-level session-start front-end path appends a new
    MANAGED entry keyed on the server's fresh session_id and re-renders the bar —
    so each start mints a DISTINCT tile, never reusing/replacing one. We assert each
    function sets MANAGED[<new id>] = {...} and calls renderSessionBar().

    NOTE (v8 Wave 6): ``developGrass`` is intentionally EXCLUDED — a grass-idea
    develop session is CONTAINED in the workbench pane and must NOT mint a top-strip
    chip; it is asserted separately below."""
    gui = gui_env["gui"]
    js = _js(gui.render_project_window_html(gui_env["pid"]))
    for fn, sidvar in (
        ("newTermSession", "sid"),
        ("continueSession", "sid"),
        ("promoteGrass", "sid"),
        ("pullGrass", "sid"),
    ):
        m = re.search(
            r"(?:async )?function %s\([^)]*\)\s*\{([\s\S]*?)\n\}" % fn, js)
        assert m, "%s not found in panel JS" % fn
        body = m.group(1)
        # The id is the server-minted session_id (rec.session_id / data.session...).
        assert ("session_id" in body), \
            "%s does not key the tile on the server session_id" % fn
        assert ("MANAGED[%s]" % sidvar) in body or "MANAGED[sid]" in body, \
            "%s does not register a new MANAGED tile" % fn
        assert "renderSessionBar()" in body, \
            "%s does not re-render the tiles row" % fn


def test_grass_develop_is_contained_no_top_strip_chip(gui_env, tmp_path):
    """NEGATIVE (v8 Wave 6): a grass-idea develop session is CONTAINED in the
    workbench pane — it must NOT mint a top-strip chip, so ``developGrass`` does NOT
    call renderSessionBar(); it mounts the terminal into the workbench host instead."""
    gui = gui_env["gui"]
    js = _js(gui.render_project_window_html(gui_env["pid"]))
    m = re.search(r"(?:async )?function developGrass\([^)]*\)\s*\{([\s\S]*?)\n\}", js)
    assert m, "developGrass not found in panel JS"
    body = m.group(1)
    assert "renderSessionBar()" not in body, \
        "developGrass must NOT re-render the top strip (it is contained)"
    assert "data-grass-term" in body, \
        "developGrass must mount the terminal in the workbench pane"


def test_finished_sessions_no_longer_excluded_from_bar(gui_env, tmp_path):
    """NEGATIVE vs v5: the old repopulate() skipped terminal-status sessions
    (`if (_isTerminalStatus(s.status)) continue;` straight to the next loop iter,
    dropping done/failed from the row). In v6 a terminal session is KEPT — routed
    into the FINISHED map — so that bare unconditional skip is gone."""
    gui = gui_env["gui"]
    js = _js(gui.render_project_window_html(gui_env["pid"]))
    rp = re.search(r"async function repopulate\(\)\s*\{([\s\S]*?)\n\}", js)
    assert rp, "repopulate() not found"
    body = rp.group(1)
    # v6 keeps finished sessions in a FINISHED map (the new keep-tile vector).
    assert "FINISHED[" in body, "repopulate no longer tracks FINISHED sessions"
    # The OLD bare 'continue' that dropped every terminal session must be gone:
    # the terminal branch now KEEPS the session (adds to FINISHED) before any
    # continue, rather than skipping it outright.
    assert not re.search(
        r"if\s*\(\s*_isTerminalStatus\(s\.status\)\s*\)\s*continue\s*;", body), \
        "the v5 'drop every terminal session' skip is still present"


def test_finished_tiles_render_greyed_and_grouped(gui_env, tmp_path):
    """POSITIVE: renderSessionBar renders FINISHED sessions as greyed tiles and
    builds a 'previously done (N)' expander for older same-lane finished ones."""
    gui = gui_env["gui"]
    js = _js(gui.render_project_window_html(gui_env["pid"]))
    rb = re.search(r"function renderSessionBar\(\)\s*\{([\s\S]*?)\n\}", js)
    assert rb, "renderSessionBar not found"
    body = rb.group(1)
    # It iterates FINISHED and builds tiles for them.
    assert "FINISHED" in body, "renderSessionBar ignores FINISHED sessions"
    # The 'previously done' grouping affordance exists (a <details> expander).
    assert "prevdone" in body, "no 'previously done' grouping affordance"
    assert "previously done" in body, "no 'previously done (N)' label"
    # Tiles for finished sessions are greyed (_buildBarTile passes finished=true).
    bt = re.search(r"function _buildBarTile\([^)]*\)\s*\{([\s\S]*?)\n\}", js)
    assert bt, "_buildBarTile helper not found"
    btb = bt.group(1)
    assert "done" in btb and "grey" in btb, \
        "_buildBarTile does not grey finished tiles"


def test_prevdone_css_present(gui_env, tmp_path):
    """The 'previously done' expander + greyed-chip styling exist (rendered CSS)."""
    gui = gui_env["gui"]
    html = gui.render_project_window_html(gui_env["pid"])
    style = "\n".join(re.findall(r"<style[^>]*>([\s\S]*?)</style>", html))
    assert ".prevdone" in style, "no .prevdone expander styling"
    assert ".live-chip.done" in style, "no greyed finished-chip styling"


def test_session_bar_container_present(gui_env, tmp_path):
    gui = gui_env["gui"]
    body = _strip(gui.render_project_window_html(gui_env["pid"]))
    ids = [d.get("id") for _, _, d in _parse(body)]
    assert "sessionBar" in ids and "panelStack" in ids


# ── (2) BACKEND: term_sessions projection includes terminal sessions, SAFE ───

@pytest.mark.skipif(not _have_git(), reason="git not on PATH")
def test_term_sessions_projection_includes_done_and_is_safe(gui_env):
    """The /api/rnd/term_sessions projection now INCLUDES a terminal (done)
    session AND stays SAFE — it MUST NOT leak worktree_path or branch, and it
    carries the Wave-2 lineage fields (parent_session_id / chain_id)."""
    gui = gui_env["gui"]
    pid = gui_env["pid"]
    import terminal_session as ts
    import session_registry as reg

    rec = ts.start_session(pid, "research", backend="claude")
    sid = rec["session_id"]
    # Naturally finish it (NOT a client-side kill): re-status the registry record.
    reg.update_session(sid, status=reg.STATUS_DONE)
    assert reg.get_session(sid)["status"] in reg.TERMINAL_STATUSES

    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        url = ("http://127.0.0.1:%d/api/rnd/term_sessions?project_id=%s"
               % (port, pid))
        with urllib.request.urlopen(url, timeout=5) as r:
            data = _json.loads(r.read().decode())
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=5)

    assert data["ok"] is True
    rows = {s["session_id"]: s for s in data["sessions"]}
    assert sid in rows, "term_sessions DROPPED the terminal (done) session"
    row = rows[sid]
    assert row["status"] in ("done", "failed"), \
        "terminal session present but status not terminal"
    # SAFE: no worktree_path / branch leaked.
    assert "worktree_path" not in row, "worktree_path LEAKED in projection"
    assert "branch" not in row, "branch LEAKED in projection"
    # Carries the Wave-2 lineage fields.
    assert "chain_id" in row and "parent_session_id" in row, \
        "projection missing the Wave-2 lineage fields"


# ── (3) REAL Playwright + Chromium interaction test (dev-only) ───────────────

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
def test_new_tiles_finish_keeps_greyed_and_grouped(server):
    """End to end in a real browser:

      1. Start THREE research sessions → THREE DISTINCT research tiles (earlier
         ones are NOT replaced by later starts).
      2. Naturally finish the TWO oldest → both tiles REMAIN (greyed); the newer
         of the two finished is the prominent finished tile and the OLDEST tucks
         under a "previously done (N)" expander. The live (newest) session stays
         a prominent colored tile.
      3. Click the oldest (grouped, finished) tile → its read-only summary panel
         opens.
      4. No JS console errors throughout.

    A screenshot (multiple tiles incl. greyed finished ones + the "previously
    done" grouping) is saved to _devtest/wave4_tiles.png for orchestrator review.
    """
    pytest.importorskip("playwright.sync_api")
    bundle, base, _ = server
    import terminal_session as ts
    import session_registry as reg
    pid = bundle["pid"]
    # Start THREE research sessions up front (created oldest → newest).
    sid1 = ts.start_session(pid, "research", backend="claude")["session_id"]
    sid2 = ts.start_session(pid, "research", backend="claude")["session_id"]
    sid3 = ts.start_session(pid, "research", backend="claude")["session_id"]
    assert len({sid1, sid2, sid3}) == 3

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

        def sel(s):
            return '#sessionBar .live-chip[data-session="%s"]' % s
        pg.wait_for_selector(sel(sid1), timeout=8000)
        pg.wait_for_selector(sel(sid2), timeout=8000)
        pg.wait_for_selector(sel(sid3), timeout=8000)
        # 1) THREE distinct research tiles (no start replaced an earlier tile).
        assert pg.eval_on_selector_all(
            '#sessionBar .live-chip[data-lane="research"]', "e=>e.length") == 3

        # 2) Naturally finish the TWO oldest (sid1, sid2) — registry re-status,
        #    NOT a client-side kill — then repopulate from the client.
        reg.update_session(sid1, status=reg.STATUS_DONE)
        reg.update_session(sid2, status=reg.STATUS_DONE)
        pg.evaluate("repopulate()")
        pg.wait_for_function(
            "document.querySelectorAll('#sessionBar .prevdone').length >= 1",
            timeout=8000)
        # Both finished tiles REMAIN, both greyed.
        assert pg.eval_on_selector_all(sel(sid1) + '.done', "e=>e.length") == 1
        assert pg.eval_on_selector_all(sel(sid2) + '.done', "e=>e.length") == 1
        # The live (newest) session is still a prominent direct-child tile.
        assert pg.eval_on_selector_all(
            '#sessionBar > .live-chip[data-session="%s"]' % sid3,
            "e=>e.length") == 1, "the live session left the prominent row"
        # The NEWER finished (sid2) is the prominent finished tile (direct child),
        # the OLDEST (sid1) is inside the "previously done" cluster.
        assert pg.eval_on_selector_all(
            '#sessionBar > .live-chip[data-session="%s"]' % sid2,
            "e=>e.length") == 1, "newest finished not prominent"
        assert pg.eval_on_selector_all(
            '#sessionBar .prevdone-tiles .live-chip[data-session="%s"]' % sid1,
            "e=>e.length") == 1, "oldest finished not under previously-done"

        # Open the expander so the grouped tile is visible/clickable, screenshot.
        pg.eval_on_selector("#sessionBar .prevdone", "e=>{e.open=true;}")
        _DEVTEST.mkdir(exist_ok=True)
        pg.screenshot(path=str(_DEVTEST / "wave4_tiles.png"))

        # 3) Click the grouped finished tile → its summary panel opens.
        assert pg.eval_on_selector_all("#panelStack .panel", "e=>e.length") == 0
        pg.click(sel(sid1))
        pg.wait_for_selector("#panelStack .panel", timeout=5000)
        assert pg.eval_on_selector_all(
            '#panelStack .panel[data-session="%s"]' % sid1,
            "e=>e.length") == 1, "wrong/no panel opened for the finished tile"

        assert not errors, f"JS console errors during tile lifecycle: {errors}"
        b.close()
