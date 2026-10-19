"""v8 Wave 6 — Grass: self-contained, cumulative, exportable.

Proves IMPLEMENTATION-PLAN.md "## Wave 6 — Grass: self-contained, cumulative,
exportable" + the LOCKED decision:

  (a) ONE contained session per (idea, lane): a second ``develop_grass_idea(idea,
      'research')`` while the first is still LIVE returns/focuses the SAME session
      (not a new one).
  (b) CONTAINED — a develop session is NOT in the board lane columns
      (``_gather_project_sessions``/the board bridge EXCLUDE its registry record
      via the ``[grass-dev]`` label marker) AND the JS does NOT add it to
      ``MANAGED``/``renderSessionBar`` (source asserts).
  (c) CUMULATIVE — multiple saved refinements per idea are listed; a develop
      session can resume from one (the seed carries prior refinements).
  (d) NO Build develop control in grass (negative).
  (e) EXPORT (Option B) — ``export_grass_to_project`` creates REAL lane tiles
      carrying the develop docs + marks the idea "promoted" (still present in
      grass) with a link; the board shows the promoted lane tiles.

Plus rendered-DOM (positive + negative) + a real Playwright/Chromium flow:
open an idea workbench, click "Develop with Research" twice → one contained
session (no top-strip chip, no board tile), click "Export to project" → a
promoted lane tile appears + the idea is marked promoted; no JS console errors.
Screenshot → ``_devtest/wave6_grass.png``.

Hermetic: ANCHOR_PTY_BACKEND=stub, ANCHOR_RUNNER_CMD -> tests/fake_claude.py,
temp ANCHOR_DATA_DIR + ANCHOR_WORKTREE_BASE + a throwaway temp git repo. NEVER
touches the live :8777 service or real data.
"""
import importlib
import json
import re
import subprocess
import threading
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()
_GUI_SRC = Path(__file__).resolve().parent.parent / "anchor_gui.py"
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


pytestmark = pytest.mark.skipif(not _have_git(), reason="git not on PATH")


def _make_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial")
    return repo


@pytest.fixture
def env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    wbase = tmp_path / "wt-base"
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(wbase))
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    monkeypatch.delenv("ANCHOR_TERMINAL_SEED", raising=False)
    for lane in ("RESEARCH", "PLAN", "PLANNING", "BUILD", "GRASS"):
        monkeypatch.delenv("ANCHOR_SEED_PROMPT_" + lane, raising=False)

    import paths
    importlib.reload(paths)
    import pty_manager
    importlib.reload(pty_manager)
    import rnd_registry
    importlib.reload(rnd_registry)
    import session_registry
    importlib.reload(session_registry)
    import worktrees
    importlib.reload(worktrees)
    import lanes
    importlib.reload(lanes)
    import terminal_session
    importlib.reload(terminal_session)
    import effort_history
    importlib.reload(effort_history)
    import anchor_gui
    importlib.reload(anchor_gui)
    paths.ensure_data_dirs()

    repo = _make_repo(tmp_path)
    proj = rnd_registry.add_project("Temp", str(repo))
    yield {
        "ts": terminal_session, "pty": pty_manager, "reg": session_registry,
        "eh": effort_history, "rnd": rnd_registry, "gui": anchor_gui,
        "repo": repo, "pid": proj["id"], "wbase": wbase, "data": data,
        "monkeypatch": monkeypatch,
    }
    try:
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


# ── helpers ──────────────────────────────────────────────────────────────────

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
    """v12 Wave 2 Layout-D: tiles carry their lane on ``data-lane`` (the 5-col
    ``#cards_<lane>`` grid is retired). ``plan`` matches ``planning`` too."""
    aliases = {"plan": {"plan", "planning"}}.get(trio_lane, {trio_lane})
    tiles = []
    for tag, classes, attrs in _parse(body):
        if (tag == "div" and "tile" in classes
                and (attrs.get("data-lane") or "") in aliases):
            tiles.append((classes, attrs))
    return tiles


# ── 1) DEDUPE / FOCUS — one contained session per (idea, lane) ────────────────

def test_develop_dedupes_to_one_live_session(env):
    """Two develop_grass_idea(idea, 'research') calls → ONE session: the second
    returns/focuses the first (same session_id), not a second session."""
    eh, reg, repo, pid = env["eh"], env["reg"], env["repo"], env["pid"]
    idea = eh.add_idea(repo, pid, "Energy-aware scene scheduling")
    iid = idea["job_id"]

    rec1 = eh.develop_grass_idea(pid, iid, "research")
    rec2 = eh.develop_grass_idea(pid, iid, "research")
    # Same session — the re-click focused the live one.
    assert rec1["session_id"] == rec2["session_id"]
    # Exactly ONE running research session exists in the registry.
    running = [s for s in reg.list_sessions(project_id=pid, status=reg.STATUS_RUNNING)
               if s["lane"] == "research"]
    assert len(running) == 1, "a second develop session was started"
    # A DIFFERENT lane (plan) starts a distinct contained session.
    rec3 = eh.develop_grass_idea(pid, iid, "plan")
    assert rec3["session_id"] != rec1["session_id"]


def test_dead_develop_session_starts_fresh(env):
    """When the mapped develop session is no longer LIVE (killed), a re-click
    starts a NEW one (dedupe only reuses a still-running session)."""
    eh, reg, ts, repo, pid = (env["eh"], env["reg"], env["ts"],
                              env["repo"], env["pid"])
    idea = eh.add_idea(repo, pid, "Rust rewrite")
    iid = idea["job_id"]
    rec1 = eh.develop_grass_idea(pid, iid, "research")
    ts.kill(rec1["session_id"], project_id=pid)
    assert reg.get_session(rec1["session_id"])["status"] != reg.STATUS_RUNNING
    rec2 = eh.develop_grass_idea(pid, iid, "research")
    assert rec2["session_id"] != rec1["session_id"]
    assert rec2["status"] == reg.STATUS_RUNNING


# ── 2) CONTAINED — not in the board / top strip ───────────────────────────────

def test_develop_session_excluded_from_board_columns(env):
    """A contained develop session does NOT render as a tile in the research/plan
    board columns (the board bridge excludes its [grass-dev]-labelled record)."""
    eh, gui, repo, pid = env["eh"], env["gui"], env["repo"], env["pid"]
    idea = eh.add_idea(repo, pid, "Voice control via local Whisper")
    iid = idea["job_id"]
    rec = eh.develop_grass_idea(pid, iid, "research")
    sid = rec["session_id"]
    # Its label carries the containment marker.
    assert eh.is_grass_dev_label(rec.get("label"))
    body = _strip(gui.render_project_window_html(pid))
    for lane in ("research", "plan", "build", "deliverables"):
        present = [a for c, a in _col_tiles(body, lane)
                   if a.get("data-session") == sid]
        assert present == [], \
            "contained develop session leaked into the %s column" % lane


def test_gather_project_sessions_excludes_develop(env):
    """_gather_project_sessions never surfaces a develop session in a trio lane."""
    eh, gui, repo, pid = env["eh"], env["gui"], env["repo"], env["pid"]
    idea = eh.add_idea(repo, pid, "contained idea")
    rec = eh.develop_grass_idea(pid, idea["job_id"], "research")
    sid = rec["session_id"]
    by_lane = gui._gather_project_sessions(repo, pid)
    for lane, views in by_lane.items():
        ids = {v.get("session_id") for v in views}
        assert sid not in ids, "develop session present in %s sessions" % lane


def test_js_does_not_leak_develop_into_strip_or_board():
    """SOURCE ASSERT: developGrass() must NOT add the develop session to MANAGED
    nor call renderSessionBar()/refreshBoard() (containment in the JS path)."""
    # C1 (2026-07-05): the app JS is EXTRACTED to static/project-window.js —
    # developGrass and the session-bar/board fns live there now, not in anchor_gui.py.
    src = (_GUI_SRC.parent / "static" / "project-window.js").read_text(encoding="utf-8")
    m = re.search(r"async function developGrass\([\s\S]*?\n\}\n", src)
    assert m, "developGrass() not found"
    fn = m.group(0)
    assert "MANAGED[sid]" not in fn, "developGrass still writes the session to MANAGED"
    assert "renderSessionBar(" not in fn, "developGrass still calls renderSessionBar()"
    assert "refreshBoard(" not in fn, "developGrass still calls refreshBoard()"
    # It DOES mount into the workbench term-host (contained pane).
    assert "data-grass-term" in fn


# ── 3) CUMULATIVE — multiple refinements; resume from one ─────────────────────

def test_cumulative_refinements_and_resume(env):
    """Multiple saved refinements per idea are listed (newest-first) and a develop
    session resumes from them (its seed carries the prior refinements)."""
    eh, repo, pid = env["eh"], env["repo"], env["pid"]
    idea = eh.add_idea(repo, pid, "Per-room presence via BLE")
    iid = idea["job_id"]
    eh.save_grass_refinement(repo, pid, iid, text="first brief")
    eh.save_grass_refinement(repo, pid, iid, text="second deeper brief")
    refs = eh.list_grass_refinements(repo, pid, iid)
    assert [r["version"] for r in refs] == [2, 1]  # newest-first, cumulative
    # A develop session resumes: the seed carries the idea + the prior refinements.
    rec = eh.develop_grass_idea(pid, iid, "plan")
    assert "Per-room presence via BLE" in rec["seed_text"]
    assert "second deeper brief" in rec["seed_text"]
    # Workbench data surfaces the cumulative history.
    data = eh.grass_workbench_data(repo, pid)
    row = next(d for d in data if d["idea_id"] == iid)
    assert len(row["refinements"]) == 2


# ── 4) NO BUILD develop in grass (negative) ───────────────────────────────────

def test_no_build_develop_control_in_grass(env):
    """v12 Wave 11 (MIGRATED): grass develop is research/plan ONLY — build is
    rejected at the backend. The one-session workbench renders NO build develop
    control (and no research/plan develop split at all — the single session
    advances in-session)."""
    eh, gui, repo, pid = env["eh"], env["gui"], env["repo"], env["pid"]
    idea = eh.add_idea(repo, pid, "an idea")
    with pytest.raises(ValueError):
        eh.develop_grass_idea(pid, idea["job_id"], "build")
    # The one-session workbench template carries NO data-dev develop controls.
    src = _GUI_SRC.read_text(encoding="utf-8")
    assert 'data-dev="build"' not in src, "a build develop control exists in grass"


# ── 5) EXPORT (Option B) — real lane tiles + idea stays promoted+linked ────────

def test_export_creates_lane_tiles_and_idea_stays_promoted(env):
    """export_grass_to_project copies the develop work UP into real research/plan
    lane efforts (board-visible) carrying the docs, marks the idea PROMOTED with a
    link, and LEAVES the idea in grass (copy, never destroy)."""
    eh, ts, repo, pid = env["eh"], env["ts"], env["repo"], env["pid"]
    idea = eh.add_idea(repo, pid, "Exportable scene engine idea")
    iid = idea["job_id"]
    # Develop in research; the session produces a doc in its worktree.
    rec = eh.develop_grass_idea(pid, iid, "research")
    sid = rec["session_id"]
    wt = Path(env["reg"].get_session(sid)["worktree_path"])
    (wt / "research").mkdir(parents=True, exist_ok=True)
    (wt / "research" / "report.md").write_text("# findings\n", encoding="utf-8")

    res = eh.export_grass_to_project(pid, iid)
    assert res["ok"] is True
    assert res["exported"], "no lane work exported"
    ex = res["exported"][0]
    assert ex["lane"] == "research"
    # A REAL research lane effort now exists (a board-visible session), non-discovered.
    rlane = eh.list_efforts(repo, pid, "research")
    exp_eff = next((e for e in rlane
                    if e.get("job_id") == ex["export_effort_id"]), None)
    assert exp_eff is not None, "export did not create a research lane effort"
    assert exp_eff.get("from_grass_idea") == iid
    assert not eh.is_discovered(exp_eff), "export tile must be a real session"
    # The doc rode up.
    assert any("report.md" in a for a in exp_eff.get("artifacts", []))

    # The idea is PROMOTED + linked, and STILL in grass (copy, never destroy).
    after = eh.get_grass_idea(repo, pid, iid)
    assert eh.grass_status(after) == eh.GRASS_PROMOTED
    assert after.get("promoted_to_session") == sid
    assert after.get("exported_to"), "idea missing the export link"
    assert any(g["job_id"] == iid for g in eh.list_efforts(repo, pid, "grass"))


def test_export_board_shows_promoted_tile(env):
    """After export, the research board column shows the exported tile."""
    eh, gui, repo, pid = env["eh"], env["gui"], env["repo"], env["pid"]
    idea = eh.add_idea(repo, pid, "Board tile idea")
    iid = idea["job_id"]
    eh.develop_grass_idea(pid, iid, "research")
    res = eh.export_grass_to_project(pid, iid)
    assert res["ok"]
    body = _strip(gui.render_project_window_html(pid))
    tiles = _col_tiles(body, "research")
    assert tiles, "no research column tiles after export"


def test_export_no_work_is_honest(env):
    """An idea with NO develop work exports nothing (honest unresolved)."""
    eh, repo, pid = env["eh"], env["repo"], env["pid"]
    idea = eh.add_idea(repo, pid, "undeveloped idea")
    res = eh.export_grass_to_project(pid, idea["job_id"])
    assert res["ok"] is False
    assert res["reason"] == "no-develop-work"
    # The idea is untouched (still raw, still present).
    after = eh.get_grass_idea(repo, pid, idea["job_id"])
    assert eh.grass_status(after) == eh.GRASS_RAW


def test_export_unknown_idea_rejected(env):
    eh, pid = env["eh"], env["pid"]
    with pytest.raises(ValueError):
        eh.export_grass_to_project(pid, "idea-nope")


# ── 6) RENDERED-DOM (positive + negative) ─────────────────────────────────────

def test_workbench_dom_has_migrate_no_build(env):
    """v12 Wave 11 (MIGRATED) POSITIVE: the one-session workbench renders a Migrate
    -to-project control (export Option B). NEGATIVE: no build develop control."""
    eh, gui, repo, pid = env["eh"], env["gui"], env["repo"], env["pid"]
    eh.add_idea(repo, pid, "dom idea")
    body = gui.render_project_window_html(pid)
    # The one-session workbench JS+template carry a Migrate action (→ exportGrass)
    # and NO build develop control.
    assert "gmigrate" in body, "no Migrate-to-project control rendered"
    assert "exportGrass(" in body, "Migrate must wire to exportGrass"
    assert 'data-dev="build"' not in body
    # The grass workbench surface is present.
    assert "grass-workbench" in body


# ── 7) Endpoint auth + behavior ───────────────────────────────────────────────

def _post(url, payload, token=None):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if token is not None:
        req.add_header("X-Anchor-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def test_grass_export_endpoint_auth_and_behavior(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(tmp_path / "wt-base"))
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.setenv("ANCHOR_TOKEN", "tok-123")
    monkeypatch.delenv("ANCHOR_TERMINAL_SEED", raising=False)
    for lane in ("RESEARCH", "PLAN", "PLANNING", "BUILD", "GRASS"):
        monkeypatch.delenv("ANCHOR_SEED_PROMPT_" + lane, raising=False)

    import paths
    importlib.reload(paths)
    paths.ensure_data_dirs()
    for mod in ("pty_manager", "rnd_registry", "session_registry", "worktrees",
                "lanes", "terminal_session", "effort_history"):
        importlib.reload(importlib.import_module(mod))
    import rnd_registry
    import effort_history
    import anchor_gui
    gui = importlib.reload(anchor_gui)

    repo = _make_repo(tmp_path)
    pid = rnd_registry.add_project("P", str(repo))["id"]
    iid = effort_history.add_idea(repo, pid, "endpoint export idea")["job_id"]
    effort_history.develop_grass_idea(pid, iid, "research", backend=None)

    server = gui.make_server("127.0.0.1", 0)
    port = server.server_address[1]
    assert port != 8777
    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()
    base = f"http://127.0.0.1:{port}"
    try:
        # No token → 401.
        code, _ = _post(base + "/api/rnd/grass_export",
                        {"project_id": pid, "idea_id": iid})
        assert code == 401
        # Unknown project → 404.
        code, _ = _post(base + "/api/rnd/grass_export",
                        {"project_id": "no-such", "idea_id": iid}, token="tok-123")
        assert code == 404
        # OK → exports + marks promoted.
        code, d = _post(base + "/api/rnd/grass_export",
                        {"project_id": pid, "idea_id": iid}, token="tok-123")
        assert code == 200 and d.get("ok") is True
        assert d["exported"] and d["exported"][0]["lane"] == "research"
        after = effort_history.get_grass_idea(repo, pid, iid)
        assert effort_history.grass_status(after) == effort_history.GRASS_PROMOTED
    finally:
        server.shutdown()
        server.server_close()
        th.join(timeout=5)
        import pty_manager
        try:
            pty_manager._reset_live_table_for_tests()
        except Exception:
            pass


# ── 8) REAL Playwright + Chromium (containment focus + export) ─────────────────

def _serve(gui):
    server = gui.make_server("127.0.0.1", 0)
    port = server.server_address[1]
    assert port != 8777
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server, t, f"http://127.0.0.1:{port}", port


def test_grass_contained_export_playwright(env):
    pytest.importorskip("playwright.sync_api")
    eh, gui, repo, pid = env["eh"], env["gui"], env["repo"], env["pid"]
    idea = eh.add_idea(repo, pid, "Whisper voice control")
    iid = idea["job_id"]

    server, t, base, _ = _serve(gui)
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page()
            errors = []
            pg.on("console",
                  lambda m: errors.append(m.text) if m.type == "error" else None)
            pg.goto(f"{base}/project/{pid}", wait_until="networkidle")
            from tests.ui_helpers import expand_workbench
            expand_workbench(pg)  # the Workbench tile now opens collapsed

            # Open the workbench, select the idea.
            pg.click(".grass-tile")
            pg.wait_for_selector("#grassPanel .grass-workbench", timeout=5000)
            pg.click(f"#grassPanel .gli[data-idea='{iid}']")
            pg.wait_for_selector("#grassPanel .gwork .gterm", timeout=5000)

            # v12 W11: Open the SINGLE workbench session → ONE contained session
            # mounts a terminal.
            pg.click("#grassPanel .gwork .gopen")
            pg.wait_for_selector("#grassPanel .gwork [data-grass-term] .xterm",
                                 timeout=8000)
            sid1 = pg.eval_on_selector(
                "#grassPanel .gwork [data-grass-term]",
                "e=>e.getAttribute('data-session')")
            assert sid1

            # CONTAINED: no top-strip chip, no board research tile for it.
            strip_chips = pg.eval_on_selector_all(
                "#sessionBar [data-session='%s']" % sid1, "e=>e.length")
            assert strip_chips == 0, "develop session leaked into the top strip"
            board_tiles = pg.eval_on_selector_all(
                ".tile[data-lane='research'][data-session='%s']" % sid1,
                "e=>e.length")
            assert board_tiles == 0, "develop session leaked into the board"

            # Re-open (toggle the bar) → FOCUSES the same session (no second one).
            pg.eval_on_selector("#grassPanel .gwork .gterm .tbar", "e=>e.click()")
            pg.wait_for_timeout(200)
            pg.eval_on_selector("#grassPanel .gwork .gterm .tbar", "e=>e.click()")
            pg.wait_for_timeout(400)
            sid2 = pg.eval_on_selector(
                "#grassPanel .gwork [data-grass-term]",
                "e=>e.getAttribute('data-session')")
            assert sid2 == sid1, "a second develop session was started"

            # Migrate to project → a promoted research lane tile appears + the
            # idea is marked promoted.
            pg.click("#grassPanel .gwork .gmigrate")
            pg.wait_for_function(
                "document.querySelectorAll(\".tile[data-lane='research']\")"
                ".length >= 1",
                timeout=8000)
            assert pg.eval_on_selector_all(
                ".tile[data-lane='research']", "e=>e.length") >= 1
            chip = pg.inner_text("#grassPanel .gwork h3 .stchip")
            assert "promoted" in chip.lower()

            _DEVTEST.mkdir(exist_ok=True)
            pg.screenshot(path=str(_DEVTEST / "wave6_grass.png"), full_page=True)

            assert not errors, f"JS console errors: {errors}"
            b.close()
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=5)
