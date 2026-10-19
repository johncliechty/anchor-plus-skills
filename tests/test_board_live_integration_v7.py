"""v7 Wave 3 gate — LIVE sessions integrated into the board lane columns (#2).

The North-Star contract (IMPLEMENTATION-PLAN Wave 3):

  (a) A started managed session (session_registry) appears as a TILE in its lane
      column immediately (running light) — the v6 board only rendered
      effort-history sessions, so a freshly-started session with no effort rows
      yet was INVISIBLE in the column. v7 bridges the registry sessions in.
  (b) DEDUPE by session_id — a session present as BOTH a live registry record
      AND an effort-history session appears exactly ONCE in the column (the live
      status is adopted onto the richer effort view).
  (c) Newest-first: the most-recent session is the prominent lane tile; older
      ones collapse under the existing ``<details class='prev-sessions'>``.
  (d) Each tile carries a SHORT, clean blurb (summarizer.session_blurb for a
      finished session; the session's own short intent for a running one).
  (e) The render path makes NO model call (cache/registry only).

Un-gameable v4.1 gate model: rendered-DOM assertions (style/script stripped) +
a render-path no-model-call spy + a real Playwright/Chromium interaction test +
a screenshot for orchestrator review. Never :8777, never real data — stub PTY,
temp data dir + worktree base, a throwaway temp git repo.
"""
import importlib
import re
import subprocess
import threading
import urllib.request
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


def _strip(html):
    b = re.sub(r"<style[\s\S]*?</style>", "", html)
    b = re.sub(r"<script[\s\S]*?</script>", "", b)
    m = re.search(r"<body[^>]*>([\s\S]*)</body>", b)
    return m.group(1) if m else b


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


def _col_tiles(body, trio_lane):
    """Return the (classes, attrs) for the Layout-D board tiles routed to the
    given lane (v12 Wave 2).

    The v7 5-col board (``#cards_<lane>``) is RETIRED for Layout D: the Research
    zone holds the research sessions and the Plan/Build zone holds the plan +
    build sessions, each as a ``.headline`` (most-recent) + ``.minitile``s in a
    collapsible shelf. We scope "the X column" to the board tiles carrying
    ``data-session`` whose ``data-lane`` maps to ``trio_lane`` (with the
    ``planning``→``plan`` store-form alias). ``deliverables`` has no session
    tiles (it's the right-column panel), so it returns ``[]``.
    """
    # The board is the .pgrid.layoutd region (before the hidden grass template).
    start = body.find("pgrid layoutd")
    assert start >= 0, "no Layout-D board in body"
    end = body.find("grassWorkbenchTpl", start)
    seg = body[start:(end if end >= 0 else len(body))]
    aliases = {"plan": {"plan", "planning"}}.get(trio_lane, {trio_lane})
    tiles = []
    for tag, classes, attrs in _parse(seg):
        if tag != "div" or "tile" not in classes:
            continue
        if not attrs.get("data-session"):
            continue   # only session tiles (headline/minitile), not deliv rows
        if (attrs.get("data-lane") or "") in aliases:
            tiles.append((classes, attrs))
    return tiles


# ── (1) DOM: a live registry session renders as a lane-column tile ───────────

@pytest.mark.skipif(not _have_git(), reason="git not on PATH")
def test_live_planning_session_appears_in_planning_column(gui_env):
    """(2026-08-07, John's simple workbench) The trio columns are gone; the
    live-session-appears-immediately contract is asserted on the GENERAL zone:
    a started general session (registry only, no effort rows yet) renders as a
    board tile with a running light."""
    gui = gui_env["gui"]
    pid = gui_env["pid"]
    import terminal_session as ts

    # The General zone is EMPTY before any session (no effort rows).
    body0 = _strip(gui.render_project_window_html(pid))
    assert _col_tiles(body0, "general") == [], \
        "general zone should be empty before any session"

    rec = ts.start_session(pid, "general", backend="claude")
    sid = rec["session_id"]
    assert gui._sessreg.get_session(sid)["status"] == gui._sessreg.STATUS_RUNNING

    body = _strip(gui.render_project_window_html(pid))
    tiles = _col_tiles(body, "general")
    # Exactly one tile, for THIS session, with a running light.
    sess_tiles = [(c, a) for c, a in tiles if a.get("data-session") == sid]
    assert len(sess_tiles) == 1, \
        "live general session not rendered as exactly one board tile"
    classes, attrs = sess_tiles[0]
    assert attrs.get("data-light") == "green", "running session not green-lit"
    assert attrs.get("data-lane") == "general", "tile not in the general zone"
    # v12 Wave 2: the Layout-D tile signals "live" via the green status light +
    # the lane-tile click hook (the old data-live re-adoption hook is retired).
    assert "lane-tile" in classes, "live session tile missing the click hook"


@pytest.mark.skipif(not _have_git(), reason="git not on PATH")
def test_lane_mapping_planning_alias(gui_env):
    """(2026-08-07, John's simple workbench) NEGATIVE: trio-lane sessions have
    NO board zone — a 'planning' registry session renders no board tile (it
    stays reachable via the session bar chips + the run ledger)."""
    gui = gui_env["gui"]
    pid = gui_env["pid"]
    import session_registry as reg
    rec = reg.register_session(pid, "planning", status=reg.STATUS_RUNNING)
    sid = rec["session_id"]
    body = _strip(gui.render_project_window_html(pid))
    for lane in ("plan", "research", "general"):
        hits = [a for c, a in _col_tiles(body, lane)
                if a.get("data-session") == sid]
        assert hits == [], "trio session leaked into the %s zone" % lane


@pytest.mark.skipif(not _have_git(), reason="git not on PATH")
def test_general_and_grass_excluded_from_trio_columns(gui_env):
    """NEGATIVE: a 'general' registry session never appears as a trio board tile."""
    gui = gui_env["gui"]
    pid = gui_env["pid"]
    import session_registry as reg
    rec = reg.register_session(pid, "general", status=reg.STATUS_RUNNING)
    sid = rec["session_id"]
    body = _strip(gui.render_project_window_html(pid))
    for lane in ("research", "plan", "build", "deliverables"):
        present = [a for c, a in _col_tiles(body, lane)
                   if a.get("data-session") == sid]
        assert present == [], "general session leaked into the %s column" % lane


@pytest.mark.skipif(not _have_git(), reason="git not on PATH")
def test_dedupe_one_tile_per_session_id(gui_env):
    """DEDUPE: a session present as BOTH a live registry record AND an effort
    record appears exactly ONCE in its lane column (not duplicated)."""
    gui = gui_env["gui"]
    pid = gui_env["pid"]
    import session_registry as reg
    import effort_history as eh

    rec = reg.register_session(pid, "general", status=reg.STATUS_RUNNING)
    sid = rec["session_id"]
    # Write an effort-history run row keyed on the SAME id (as adoption would),
    # so sessions.list_sessions yields a session for it (keyed ``run::<sid>``).
    eh.record_effort(gui_env["repo"], pid, "general", sid,
                     skill="",
                     prompt_seed="look into cooling loops",
                     extra={"title": "cooling loops"})

    body = _strip(gui.render_project_window_html(pid))
    # The effort session renders under the ``run::<sid>`` key; the live registry
    # row dedupes onto it (prefix-stripped tail == sid) → exactly one tile.
    matches = [a for c, a in _col_tiles(body, "general")
               if _strip_prefix(a.get("data-session", "")) == sid]
    assert len(matches) == 1, \
        "session present as live+effort rendered %d tiles (want 1)" % len(matches)
    # And the live status is adopted onto the (effort) tile → green.
    assert matches[0].get("data-light") == "green", \
        "dedupe lost the live status (tile not green)"


def _strip_prefix(sid):
    i = (sid or "").find("::")
    return sid[i + 2:] if i >= 0 else (sid or "")


@pytest.mark.skipif(not _have_git(), reason="git not on PATH")
def test_newest_prominent_older_under_expander(gui_env):
    """Two registry sessions in the same lane: the newest is the prominent tile
    (the Layout-D ``.headline``); the older sits inside the collapsible shelf
    (``.shelf-wrap`` → ``.minitile``)."""
    gui = gui_env["gui"]
    pid = gui_env["pid"]
    import session_registry as reg
    import time as _t
    older = reg.register_session(pid, "general", status=reg.STATUS_DONE)
    _t.sleep(0.02)
    newer = reg.register_session(pid, "general", status=reg.STATUS_RUNNING)

    body = _strip(gui.render_project_window_html(pid))
    # The Research zone: the prominent tile is the .headline (newest); the older
    # one is a .minitile inside the #shelf_research collapsible shelf.
    start = body.find("pgrid layoutd")
    assert start >= 0, "no Layout-D board in body"
    shelf_at = body.find("id='shelf_general'", start)
    if shelf_at < 0:
        shelf_at = body.find('id="shelf_general"', start)
    assert shelf_at >= 0, "no general shelf when 2 sessions exist"
    prominent = body[start:shelf_at]          # headline region (before the shelf)
    shelf = body[shelf_at:body.find("grassWorkbenchTpl", shelf_at)]
    assert ('data-session="%s"' % newer["session_id"]) in prominent, \
        "newest session not the prominent headline tile"
    # the newest is a headline; the older is a minitile in the shelf
    assert "class='headline" in prominent
    assert ('data-session="%s"' % older["session_id"]) in shelf, \
        "older session not under the collapsible shelf"
    assert "minitile" in shelf


@pytest.mark.skipif(not _have_git(), reason="git not on PATH")
def test_tile_carries_a_short_clean_blurb(gui_env):
    """A finished session's tile shows a SHORT, CLEAN blurb from the cached
    summary (no markdown/decorative glyphs, capped). Running/uncached falls back
    to the session's short intent."""
    gui = gui_env["gui"]
    pid = gui_env["pid"]
    import session_registry as reg
    import summarizer
    # (2026-08-07) The general zone is the board; the blurb contract is
    # asserted there.
    store_lane = "general"
    rec = reg.register_session(pid, "general", status=reg.STATUS_DONE)
    sid = rec["session_id"]
    # Seed a CACHED session summary whose claim carries markdown + glyphs.
    cached = {
        "claims": ["**Goal:** ship X — handle ## edge `cases` ✓ over a "
                   "very long objective that must be cut on a word boundary"],
        "what_was_asked": "",
        "title": "",
        "schema_version": summarizer.SUMMARY_SCHEMA_VERSION,
    }
    _write_cached_summary(summarizer, gui_env["repo"], pid, store_lane, sid, cached)

    blurb = summarizer.session_blurb(gui_env["repo"], pid, store_lane, sid)
    assert blurb, "session_blurb returned empty for a cached summary"
    for bad in ("**", "##", "`", "✓", "—"):
        assert bad not in blurb, "blurb still contains %r" % bad
    assert len(blurb) <= 70, "blurb not capped: %r" % blurb

    body = _strip(gui.render_project_window_html(pid))
    # v12 Wave 2: the blurb appears on the Layout-D headline card (.hblurb). The
    # single DONE research session is the Latest-Research headline.
    assert "class='hblurb'" in body, \
        "no .hblurb element rendered on the headline tile"
    # and it carries the clean (glyph/markdown-stripped) blurb text.
    assert blurb in body, "the clean blurb text is not on the rendered tile"


def _write_cached_summary(summarizer, folder, pid, store_lane, sid, structured):
    """Write a cached session summary.json the same way the summarizer would, so
    load_cached / session_blurb pick it up (cache read; no model run)."""
    import effort_history as eh
    import json as _json
    d = (eh.lane_dir(folder, pid, store_lane) / "summaries" / sid)
    d.mkdir(parents=True, exist_ok=True)
    (d / "summary.json").write_text(
        _json.dumps(structured, ensure_ascii=False), encoding="utf-8")


# ── (2) render path makes NO model call ──────────────────────────────────────

@pytest.mark.skipif(not _have_git(), reason="git not on PATH")
def test_board_render_makes_no_model_call(gui_env, monkeypatch):
    """Spy the summarizer's generate functions: rendering the board (with a live
    session present) must NOT trigger any synchronous summary generation."""
    gui = gui_env["gui"]
    pid = gui_env["pid"]
    import terminal_session as ts
    import summarizer
    ts.start_session(pid, "research", backend="claude")

    calls = []
    for name in ("summarize_session", "summarize_project", "_run_summary_job",
                 "_generate_once"):
        if hasattr(summarizer, name):
            monkeypatch.setattr(
                summarizer, name,
                (lambda *a, _n=name, **k: calls.append(_n)),
                raising=True)

    gui.render_project_window_html(pid)
    assert calls == [], "board render triggered a model/summary call: %s" % calls


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
def test_playwright_started_session_appears_in_column_and_strip(server):
    """End to end in a real browser:

      1. Start a planning session server-side (registry) BEFORE loading → the
         board renders a tile in the PLANNING column (running light) AND the
         session shows in the top active strip — exactly ONE tile in the column.
      2. Finish it (registry re-status) and reload → the column tile STAYS (grey)
         and, when a newer planning session exists, older ones collapse under
         "previous sessions".
      3. No JS console errors.

    Screenshot saved to _devtest/wave3_board.png for orchestrator review.
    """
    pytest.importorskip("playwright.sync_api")
    bundle, base, _ = server
    import terminal_session as ts
    import session_registry as reg
    pid = bundle["pid"]

    sid1 = ts.start_session(pid, "general", backend="claude")["session_id"]

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

        # 1) Exactly one Layout-D tile for sid1 in the Plan/Build zone, running.
        #    Initially the sole plan session is the Latest-Plan/Build headline.
        plan_sel = '.pgrid.layoutd .tile[data-session="%s"][data-lane="general"]' % sid1
        pg.wait_for_selector(plan_sel, timeout=8000)
        assert pg.eval_on_selector_all(plan_sel, "e=>e.length") == 1, \
            "expected exactly one General-zone tile for the session"
        assert pg.eval_on_selector(
            plan_sel, "e=>e.getAttribute('data-light')") == "green", \
            "General tile not green (running)"
        # The session also shows in the top active strip.
        pg.wait_for_selector(
            '#sessionBar .live-chip[data-session="%s"]' % sid1, timeout=8000)

        _DEVTEST.mkdir(exist_ok=True)
        pg.screenshot(path=str(_DEVTEST / "wave3_board.png"))

        # 2) Start a SECOND planning session, finish the FIRST, reload.
        sid2 = ts.start_session(pid, "general", backend="claude")["session_id"]
        reg.update_session(sid1, status=reg.STATUS_DONE)
        pg.goto(f"{base}/project/{pid}", wait_until="networkidle")
        from tests.ui_helpers import expand_workbench
        expand_workbench(pg)  # the Workbench tile now opens collapsed
        # The newer (sid2) is the prominent .headline; the finished sid1 is a
        # .minitile inside the Plan/Build collapsible shelf (#shelf_plan_build),
        # greyed/amber, and still present.
        pg.wait_for_selector(
            '.pgrid.layoutd .headline[data-session="%s"]' % sid2, timeout=8000)
        assert pg.eval_on_selector_all(
            '#shelf_general .minitile[data-session="%s"]' % sid1,
            "e=>e.length") == 1, "finished general session not under the shelf"
        assert pg.eval_on_selector(
            '.pgrid.layoutd .tile[data-session="%s"]' % sid1,
            "e=>e.getAttribute('data-light')") == "amber", \
            "finished (done) session tile not amber/grey"
        # Still exactly ONE tile per session id in the board (no dupes).
        assert pg.eval_on_selector_all(
            '.pgrid.layoutd .tile[data-session="%s"]' % sid1,
            "e=>e.length") == 1

        assert not errors, f"JS console errors during board integration: {errors}"
        b.close()
