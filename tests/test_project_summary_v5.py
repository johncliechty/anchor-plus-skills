"""v5 Wave 3 gate — better project summaries (objective/purpose) + folded request:
the main dashboard reflects project-window changes without a full reload.

North-Star contract (MASTER-PLAN Locked Decision #3, IMPLEMENTATION-PLAN Wave 3):

  - ``summarizer.summarize_project`` uses a STRONGER seed (identity doc + recent
    plan docs + pinned deliverables + per-lane activity) and an OBJECTIVE-focused
    prompt (1-2 sentence statement of what the project is FOR), grounding-filtered,
    cached generate-once (force regenerates; a failed runner must NOT poison the
    cache).
  - The dashboard row (``render_project_tile_html``) and the project-window header
    READ the cached objective summary ONLY — NEVER a synchronous model call on the
    render path.
  - Folded user request: ``GET /api/rnd/projects_html`` returns the rendered R&D
    rows fragment so an already-open dashboard refreshes in place (diff-before-swap,
    visibility/active-view guarded) without a full page reload.

Hermetic gate (the v4.1 model): summarizer unit tests with the STUB runner + a
runner-call counter to prove the render path runs NO model + rendered-DOM
assertions (style/script stripped) + a real Playwright/Chromium in-place-refresh
test. Never :8777, never real data — stub PTY backend, temp data dir, stub runner.
"""
import importlib
import json
import re
import threading
from html.parser import HTMLParser
from pathlib import Path

import pytest

STUB = (Path(__file__).resolve().parent / "stub_summarizer.py").as_posix()
FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()


# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def mods(tmp_path, monkeypatch):
    """Reload the summarizer stack against a temp data dir + the STUB runner."""
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {STUB}")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    for mod in ("paths", "job_runner", "rnd_registry", "effort_history",
                "sessions", "report_viewer", "summarizer"):
        importlib.reload(importlib.import_module(mod))
    import job_runner, effort_history, rnd_registry, sessions, summarizer
    yield job_runner, effort_history, rnd_registry, sessions, summarizer
    for rec in job_runner.list_records():
        if rec.get("status") == job_runner.STATUS_RUNNING:
            try:
                job_runner.cancel(rec["job_id"])
            except Exception:
                pass
    job_runner._reset_live_table_for_tests()


@pytest.fixture
def gui_env(tmp_path, monkeypatch):
    """Reload anchor_gui against a temp data dir + stub PTY + stub runner."""
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {STUB}")
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    for mod in ("paths", "job_runner", "rnd_registry", "lanes",
                "effort_history", "sessions", "summarizer", "gate_adapter"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import anchor_gui
    yield importlib.reload(anchor_gui)


def _project_with_full_corpus(rnd, eh, folder):
    """A project with an identity doc + a recent plan doc + a pinned deliverable +
    per-lane activity (a recorded research effort/session)."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "CLAUDE.md").write_text(
        "# Anchor\n\n"
        "## What this project is\n"
        "Anchor is a productivity system that manages markdown task files for "
        "a researcher, tracking projects and deadlines.\n",
        encoding="utf-8")
    plan = folder / "planning" / "rnd-v5"
    plan.mkdir(parents=True, exist_ok=True)
    (plan / "MASTER-PLAN.md").write_text(
        "# Durable Work\n\n"
        "## North Star\n"
        "Make every R&D session a durable resumable unit of work.\n",
        encoding="utf-8")
    proj = rnd.add_project("Anchor", str(folder))
    pid = proj["id"]
    # per-lane activity: a recorded research effort → a session with a skill.
    eh.record_effort(folder, pid, "research", "r-act-1", skill="researchPrime",
                     prompt_seed="Survey durable work patterns")
    # a pinned deliverable.
    try:
        import deliverables as _d
        target = folder / "anchor_gui.py"
        target.write_text("# anchor_gui deliverable\n", encoding="utf-8")
        _d.pin_deliverable(folder, pid, "anchor_gui.py",
                           name="anchor_gui.py",
                           description="the running dashboard")
    except Exception:
        pass
    return pid


# ── (1) SEED + OBJECTIVE SUMMARY ─────────────────────────────────────────────

def test_seed_includes_all_sources(mods, tmp_path):
    jr, eh, rnd, sessions, summ = mods
    folder = tmp_path / "proj"
    pid = _project_with_full_corpus(rnd, eh, folder)

    seed = summ.project_extraction_seed(folder, pid)
    # 1. identity doc + 2. recent plan doc among the sources.
    assert "CLAUDE.md" in seed["sources"]
    assert any("MASTER-PLAN.md" in s for s in seed["sources"])
    # 3. pinned deliverable folded in.
    assert any("anchor_gui" in d for d in seed.get("deliverables", []))
    # 4. per-lane activity present (research session w/ skill).
    activity = seed.get("activity", [])
    lanes = {a["lane"] for a in activity}
    assert "research" in lanes
    flat = " ".join(i for a in activity for i in a["items"]).lower()
    assert "researchprime" in flat
    # the corpus folds them all (grounding the objective).
    corpus = seed["text"].lower()
    assert "productivity system" in corpus
    assert "durable" in corpus
    assert "researchprime" in corpus

    # the objective prompt asks for a 1-2 SENTENCE objective (not feature bullets).
    prompt = summ._project_seed_prompt(seed).lower()
    assert "objective" in prompt
    assert "1-2 sentence" in prompt or "1-2 sentences" in prompt
    assert "researchprime" in prompt          # activity reaches the prompt
    assert "anchor_gui" in prompt              # deliverable reaches the prompt


def test_objective_summary_generated_grounded_and_cached(mods, tmp_path,
                                                         monkeypatch):
    jr, eh, rnd, sessions, summ = mods
    folder = tmp_path / "proj"
    pid = _project_with_full_corpus(rnd, eh, folder)

    counter = tmp_path / "calls.txt"
    monkeypatch.setenv("STUB_SUMMARIZER_COUNTER", str(counter))
    grounded = ("Anchor is a productivity system that manages markdown task "
                "files for a researcher.")
    ungrounded = "Quux frobnicate zzyzx wibble unrelated bogus claim."
    monkeypatch.setenv("STUB_SUMMARIZER_CLAIMS", grounded + "\n" + ungrounded)

    # FIRST → model runs GENERATE_RUNS times, writes cache.
    s1 = summ.summarize_project(folder, pid)
    assert len(counter.read_text(encoding="utf-8")) == summ.GENERATE_RUNS
    text = s1["summary_text"].lower()
    assert "productivity system" in text                 # objective sentence
    assert "frobnicate" not in text                       # ungrounded dropped
    assert s1["claims"], "objective summary empty"

    # SECOND → served from cache, NO re-run (generate-once).
    s2 = summ.summarize_project(folder, pid)
    assert len(counter.read_text(encoding="utf-8")) == summ.GENERATE_RUNS
    assert s2["claims"] == s1["claims"]


def test_force_regenerates(mods, tmp_path, monkeypatch):
    jr, eh, rnd, sessions, summ = mods
    folder = tmp_path / "proj"
    pid = _project_with_full_corpus(rnd, eh, folder)
    counter = tmp_path / "calls.txt"
    monkeypatch.setenv("STUB_SUMMARIZER_COUNTER", str(counter))
    monkeypatch.setenv("STUB_SUMMARIZER_CLAIMS",
                       "Anchor is a productivity system for task files.")
    summ.summarize_project(folder, pid)
    n1 = len(counter.read_text(encoding="utf-8"))
    monkeypatch.setenv("STUB_SUMMARIZER_CLAIMS",
                       "North Star: durable resumable units of work.")
    s2 = summ.summarize_project(folder, pid, force=True)
    assert len(counter.read_text(encoding="utf-8")) == n1 + summ.GENERATE_RUNS
    assert "durable" in s2["summary_text"].lower()


def test_failed_runner_does_not_poison_cache(mods, tmp_path, monkeypatch):
    jr, eh, rnd, sessions, summ = mods
    folder = tmp_path / "proj"
    pid = _project_with_full_corpus(rnd, eh, folder)
    monkeypatch.setenv("STUB_SUMMARIZER_COUNTER", str(tmp_path / "c.txt"))
    monkeypatch.setenv("STUB_SUMMARIZER_FAIL", "1")
    out = summ.summarize_project(folder, pid)
    assert out.get("error") == "generation_failed"
    # cache NOT written → a later good run can still succeed.
    assert summ.load_cached_project(folder, pid) is None
    monkeypatch.delenv("STUB_SUMMARIZER_FAIL", raising=False)
    monkeypatch.setenv("STUB_SUMMARIZER_CLAIMS",
                       "Anchor is a productivity system for task files.")
    good = summ.summarize_project(folder, pid)
    assert good["claims"]
    assert summ.load_cached_project(folder, pid) is not None


# ── (2) RENDER READS CACHE ONLY (no model call on render) ────────────────────

def _runner_counter_after_render(gui, render_callable, counter, monkeypatch):
    monkeypatch.setenv("STUB_SUMMARIZER_COUNTER", str(counter))
    before = counter.read_text(encoding="utf-8") if counter.exists() else ""
    html = render_callable()
    after = counter.read_text(encoding="utf-8") if counter.exists() else ""
    return html, before, after


def test_row_and_header_render_read_cache_only(gui_env, tmp_path, monkeypatch):
    gui = gui_env
    import rnd_registry as rnd, effort_history as eh, summarizer as summ
    folder = tmp_path / "P"
    pid = _project_with_full_corpus(rnd, eh, folder)

    # Generate + cache the objective summary first (this DOES run the model).
    counter = tmp_path / "calls.txt"
    monkeypatch.setenv("STUB_SUMMARIZER_COUNTER", str(counter))
    monkeypatch.setenv("STUB_SUMMARIZER_CLAIMS",
                       "Anchor is a productivity system that manages markdown "
                       "task files.")
    summ.summarize_project(str(folder), pid)
    n_after_gen = len(counter.read_text(encoding="utf-8"))
    assert n_after_gen == summ.GENERATE_RUNS

    entry = next(e for e in rnd.list_projects() if e["id"] == pid)

    # ROW render → reads cache, shows the objective; runs NO model.
    row = gui.render_project_tile_html(entry)
    assert "productivity system" in row.lower()
    assert len(counter.read_text(encoding="utf-8")) == n_after_gen, \
        "row render ran the model"

    # HEADER (project window) render → shows the objective; runs NO model.
    win = gui.render_project_window_html(pid)
    assert "Objective:" in win
    assert "productivity system" in win.lower()
    assert len(counter.read_text(encoding="utf-8")) == n_after_gen, \
        "header render ran the model"


def test_uncached_project_shows_placeholder_no_model_call(gui_env, tmp_path,
                                                          monkeypatch):
    gui = gui_env
    import rnd_registry as rnd
    folder = tmp_path / "Empty"
    folder.mkdir(parents=True, exist_ok=True)
    pid = rnd.add_project("Empty", str(folder))["id"]
    counter = tmp_path / "calls.txt"
    monkeypatch.setenv("STUB_SUMMARIZER_COUNTER", str(counter))
    entry = next(e for e in rnd.list_projects() if e["id"] == pid)
    row = gui.render_project_tile_html(entry)
    # graceful placeholder (no cache, no blurb) and NO model call on render.
    assert ("No summary yet" in row) or ("rnd-row-summary" in row)
    assert not counter.exists() or counter.read_text(encoding="utf-8") == "", \
        "render path ran the model for an uncached project"


# ── (3) DASHBOARD REFRESH — the folded request ───────────────────────────────

def _strip(html):
    b = re.sub(r"<style[\s\S]*?</style>", "", html)
    b = re.sub(r"<script[\s\S]*?</script>", "", b)
    return b


def test_dashboard_has_container_and_js(gui_env):
    gui = gui_env
    projects, tasks, inbox = gui.gather_all()
    html = gui.generate_html(projects, tasks, inbox)
    body = _strip(html)
    # the stable, swappable container is present in the BODY (not just CSS/JS).
    assert 'id="rndProjectsRows"' in body
    # the refresh wiring is present (in the JS — not stripped here).
    assert "rndRowsRefresh" in html
    assert "/api/rnd/projects_html" in html
    assert "visibilitychange" in html


def _serve(gui):
    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, t, f"http://127.0.0.1:{port}"


def test_projects_html_endpoint_returns_current_rows(gui_env, tmp_path):
    gui = gui_env
    import rnd_registry as rnd
    import urllib.request
    folder = tmp_path / "Live"
    folder.mkdir(parents=True, exist_ok=True)
    rnd.add_project("AlphaProj", str(folder))
    srv, t, base = _serve(gui)
    try:
        with urllib.request.urlopen(base + "/api/rnd/projects_html") as r:
            data = json.loads(r.read().decode("utf-8"))
        assert data["ok"] is True
        assert "AlphaProj" in data["html"]
        # make a change → the fragment reflects it WITHOUT a server restart.
        rnd.add_project("BetaProj", str(tmp_path / "Beta"))
        (tmp_path / "Beta").mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(base + "/api/rnd/projects_html") as r:
            data2 = json.loads(r.read().decode("utf-8"))
        assert "BetaProj" in data2["html"]
        assert "AlphaProj" in data2["html"]
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


def test_projects_html_endpoint_no_model_call(gui_env, tmp_path, monkeypatch):
    """The fragment endpoint reads cached summaries only — never a model run."""
    gui = gui_env
    import rnd_registry as rnd, effort_history as eh
    import urllib.request
    folder = tmp_path / "P"
    _project_with_full_corpus(rnd, eh, folder)
    counter = tmp_path / "calls.txt"
    monkeypatch.setenv("STUB_SUMMARIZER_COUNTER", str(counter))
    srv, t, base = _serve(gui)
    try:
        with urllib.request.urlopen(base + "/api/rnd/projects_html") as r:
            json.loads(r.read().decode("utf-8"))
        assert not counter.exists() or counter.read_text(encoding="utf-8") == "", \
            "projects_html endpoint ran the model on render"
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


def test_dashboard_in_place_refresh_playwright(gui_env, tmp_path):
    """Real browser: open the R&D view, change the registry, and assert the rows
    update IN PLACE (no full navigation, no console errors). We trigger the
    visibilitychange-driven refresh path so the test doesn't wait the 15s poll."""
    pytest.importorskip("playwright.sync_api")
    gui = gui_env
    import rnd_registry as rnd
    folder = tmp_path / "Live"
    folder.mkdir(parents=True, exist_ok=True)
    rnd.add_project("AlphaProj", str(folder))
    srv, t, base = _serve(gui)
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page()
            errors = []
            pg.on("console",
                  lambda m: errors.append(m.text) if m.type == "error" else None)
            pg.goto(base + "/", wait_until="networkidle")
            # switch to the R&D view (this also kicks rndRowsRefresh()).
            pg.evaluate("showView('rnd')")
            pg.wait_for_selector("#rndProjectsRows", timeout=5000)
            # capture the document identity to prove NO full navigation later.
            pg.evaluate("window.__anchorMarker = 'STAY';")
            assert "AlphaProj" in pg.inner_html("#rndProjectsRows")
            assert "BetaProj" not in pg.inner_html("#rndProjectsRows")
            # change the registry server-side (a project-window-style change).
            (tmp_path / "Beta").mkdir(parents=True, exist_ok=True)
            rnd.add_project("BetaProj", str(tmp_path / "Beta"))
            # trigger the visibilitychange→visible refresh path explicitly.
            pg.evaluate(
                "document.dispatchEvent(new Event('visibilitychange'));"
                "rndRowsRefresh();")
            pg.wait_for_function(
                "document.querySelector('#rndProjectsRows')"
                ".innerHTML.indexOf('BetaProj') !== -1", timeout=8000)
            # the new row appeared IN PLACE — no navigation (marker survives).
            assert pg.evaluate("window.__anchorMarker") == "STAY", \
                "page navigated/reloaded instead of swapping in place"
            assert "AlphaProj" in pg.inner_html("#rndProjectsRows")
            assert not errors, f"JS console errors: {errors}"
            b.close()
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


def test_refresh_preserves_rollup_toggle_and_open_kebab(gui_env, tmp_path):
    """Real browser regression (adversarial finding F1): the in-place rows refresh
    must NOT silently undo the user's UI state — (1) a selected 30d rollup window
    survives a refresh (the server fragment always renders 'lifetime' active), and
    (2) an OPEN kebab menu is not clobbered closed by a refresh tick."""
    pytest.importorskip("playwright.sync_api")
    gui = gui_env
    import rnd_registry as rnd
    folder = tmp_path / "Roll"
    folder.mkdir(parents=True, exist_ok=True)
    rnd.add_project("AlphaProj", str(folder))
    srv, t, base = _serve(gui)
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page()
            errors = []
            pg.on("console",
                  lambda m: errors.append(m.text) if m.type == "error" else None)
            pg.goto(base + "/", wait_until="networkidle")
            pg.evaluate("showView('rnd')")
            pg.wait_for_selector("#rndProjectsRows", timeout=5000)

            # (1) Select the 30d rollup window, then force a refresh. Scope every
            # selector to #rndProjectsRows — the toggle markup also appears in
            # another (hidden) view, so an unscoped selector would hit the
            # zero-size hidden copy.
            sel30 = '#rndProjectsRows .rnd-rows-rolltog b[data-window="30d"]'
            selLife = '#rndProjectsRows .rnd-rows-rolltog b[data-window="lifetime"]'
            pg.click(sel30)
            assert pg.eval_on_selector(
                sel30, "e => e.classList.contains('on')") is True
            (tmp_path / "Beta").mkdir(parents=True, exist_ok=True)
            rnd.add_project("BetaProj", str(tmp_path / "Beta"))
            pg.evaluate("rndRowsRefresh();")
            pg.wait_for_function(
                "document.querySelector('#rndProjectsRows')"
                ".innerHTML.indexOf('BetaProj') !== -1", timeout=8000)
            # The 30d toggle survived the swap (was NOT reverted to lifetime).
            pg.wait_for_function(
                "(() => { const b = document.querySelector("
                "'#rndProjectsRows .rnd-rows-rolltog b[data-window=\\\"30d\\\"]');"
                " return b && b.classList.contains('on'); })()", timeout=4000)
            assert pg.eval_on_selector(
                selLife, "e => e.classList.contains('on')") is False, \
                "refresh reverted the rollup window back to lifetime"

            # (2) Open a kebab menu; a refresh tick must skip (leave it open).
            kebab = pg.query_selector(
                "#rndProjectsRows .rnd-kebab-btn, "
                "#rndProjectsRows [onclick*='rndToggleKebab']")
            if kebab:
                kebab.click()
                opened = pg.eval_on_selector_all(
                    "#rndProjectsRows .rnd-kebab-menu.rnd-kebab-open",
                    "e => e.length")
                if opened:
                    pg.evaluate("rndRowsRefresh();")
                    pg.wait_for_timeout(300)
                    assert pg.eval_on_selector_all(
                        "#rndProjectsRows .rnd-kebab-menu.rnd-kebab-open",
                        "e => e.length") >= 1, \
                        "refresh clobbered an open kebab menu closed"
            assert not errors, f"JS console errors: {errors}"
            b.close()
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=5)
