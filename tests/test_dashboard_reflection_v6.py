"""v6 Wave 7 — main dashboard reflects project activity (UI).

Upgrade each home-dashboard R&D project row from a bare status dot to a TIMELY
reflection sourced from CACHE/REGISTRY ONLY (never a synchronous model call on
the render path):
  - the running-session presence/count (a live indicator + "running: N");
  - the latest grounded objective project summary (Wave-1 cache via
    ``summarizer.load_cached_project``);
  - a "what's happening" line — the newest session's lane/title/status.

The gate (the v4 lesson):
  (a) rendered-DOM assertions, positive + negative — the new reflection structure
      is present AND the old "just a status dot" row is upgraded; a project with
      no cached summary shows the honest placeholder, not fabricated text;
  (b) render-path asserts NO model call — the summarizer generate function is
      spied and rendering the row / projects_html must NOT call it (cache-only);
  (c) a real Playwright + Chromium test — boot a throwaway server + stub PTY + a
      project with a cached objective + a running session; the home row shows the
      objective + the running/activity reflection (not just a dot); a simulated
      background summary update + projects_html refresh updates the row in place;
      no JS console errors; a screenshot is saved to ``_devtest/wave7_dashboard.png``.

Hermetic: temp ANCHOR_DATA_DIR + reload, stub PTY, no live claude, no :8777.
"""
import importlib
import json
import re
import threading
from html.parser import HTMLParser
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()
SUMMARY_VER = None  # filled from summarizer.SUMMARY_SCHEMA_VERSION at fixture time


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    for mod in ("paths", "job_runner", "rnd_registry", "lanes",
                "effort_history", "summarizer", "session_registry",
                "sessions"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import anchor_gui
    importlib.reload(anchor_gui)
    import rnd_registry
    import summarizer
    import session_registry
    return anchor_gui, rnd_registry, summarizer, session_registry


def _mkproject(rnd, folder, name="P"):
    folder.mkdir(parents=True, exist_ok=True)
    return rnd.add_project(name, str(folder))


def _write_cached_project_summary(summarizer, folder, pid, text):
    """Write a valid cached PROJECT summary (Wave-1 objective) directly, so the
    render path has a real cache to READ — without running the model."""
    import paths
    p = summarizer._project_summary_json_path(str(folder), pid)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "schema_version": summarizer.SUMMARY_SCHEMA_VERSION,
        "summary_text": text,
        "summary": text,
        "no_grounded_claims": False,
    }
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


# ── helpers: parse the rendered body, style/script stripped ──────────────────

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


# ── (a) rendered-DOM assertions: positive + negative ─────────────────────────

def test_row_shows_running_count_and_activity_when_active(env, tmp_path):
    """A project with a RUNNING session + a cached objective summary renders the
    objective text + a running indicator + a recent-activity line."""
    gui, rnd, summ, sreg = env
    folder = tmp_path / "Active"
    pid = _mkproject(rnd, folder, "Active")["id"]
    _write_cached_project_summary(
        summ, folder, pid, "Anchor is a single-folder productivity system.")
    sreg.register_session(pid, "planning", status=sreg.STATUS_RUNNING,
                          label="Crucible pipeline plan")

    row = gui.render_project_tile_html(rnd.get_project(pid))
    # The objective summary text (Wave-1 cache) shows on the row.
    assert "single-folder productivity system" in row
    # The new activity-reflection structure is present (not just a dot).
    assert "rnd-row-activity" in row
    assert "running: 1" in row
    assert "rnd-act-pulse" in row                 # live indicator
    assert "rnd-act-latest" in row
    assert "Planning" in row                      # newest session's lane
    assert "Crucible pipeline plan" in row        # its title/label
    assert "(running)" in row                     # its status
    # The existing status dot + lifecycle controls are kept.
    assert "rnd-dot" in row
    assert "rnd-kebab" in row


def test_row_negative_is_more_than_a_status_dot(env, tmp_path):
    """Negative: the row is no longer just a status dot — the new reflection
    structure must be present in addition to the dot."""
    gui, rnd, summ, sreg = env
    folder = tmp_path / "Active"
    pid = _mkproject(rnd, folder, "Active")["id"]
    sreg.register_session(pid, "research", status=sreg.STATUS_RUNNING,
                          label="researchPrime sweep")
    body = _strip(
        '<body>' + gui.render_project_tile_html(rnd.get_project(pid)) + '</body>')
    els = _parse(body)
    classes = {c for _, cs, _ in els for c in cs}
    # New reflection structure present...
    assert "rnd-row-activity" in classes
    assert "rnd-act-running" in classes
    assert "rnd-act-latest" in classes
    # ...alongside (not replacing) the dot.
    assert "rnd-dot" in classes


def test_row_honest_placeholder_when_no_activity_or_summary(env, tmp_path):
    """A project with NO sessions and NO cached summary shows honest
    placeholders — never fabricated text."""
    gui, rnd, summ, sreg = env
    folder = tmp_path / "Empty"
    pid = _mkproject(rnd, folder, "Empty")["id"]
    row = gui.render_project_tile_html(rnd.get_project(pid))
    # No fabricated objective: the summary falls back to "No summary yet"
    # (blurb may seed; the key is no invented activity).
    assert "rnd-row-activity" in row
    assert "idle — no sessions yet" in row
    assert "running:" not in row          # no fabricated running count
    assert "rnd-act-pulse" not in row     # no live indicator when idle


def test_row_no_running_indicator_when_only_done_sessions(env, tmp_path):
    """A project whose newest session is DONE shows the activity line (latest:
    ... (done)) but NO live running indicator/count."""
    gui, rnd, summ, sreg = env
    folder = tmp_path / "Done"
    pid = _mkproject(rnd, folder, "Done")["id"]
    sreg.register_session(pid, "build", status=sreg.STATUS_DONE,
                          label="Foreman wave run")
    row = gui.render_project_tile_html(rnd.get_project(pid))
    assert "rnd-row-activity" in row
    assert "Foreman wave run" in row
    assert "(done)" in row
    assert "rnd-act-pulse" not in row
    assert "running:" not in row


def test_projects_view_renders_activity_for_each_row(env, tmp_path):
    """The full projects view (and thus the in-place projects_html fragment)
    renders the upgraded row for every project."""
    gui, rnd, summ, sreg = env
    for i in range(2):
        folder = tmp_path / f"proj{i}"
        pid = _mkproject(rnd, folder, f"P{i}")["id"]
        sreg.register_session(pid, "research", status=sreg.STATUS_RUNNING,
                              label=f"run {i}")
    view = gui.render_projects_view_html()
    assert view.count("rnd-row-activity") == 2
    assert view.count("running: 1") == 2


def test_no_leaked_fstring_braces(env, tmp_path):
    """f-string brace discipline: no doubled braces leak into the served
    rows/home (the home dashboard CSS/JS is f-string-generated)."""
    gui, rnd, summ, sreg = env
    folder = tmp_path / "proj"
    pid = _mkproject(rnd, folder, "P")["id"]
    sreg.register_session(pid, "planning", status=sreg.STATUS_RUNNING,
                          label="x")
    view = gui.render_projects_view_html()
    assert "{{" not in view and "}}" not in view
    home = gui.generate_html(*gui.gather_all())
    assert "{{" not in home and "}}" not in home
    # The new CSS classes are shipped on the home page.
    assert ".rnd-row-activity" in home
    assert ".rnd-act-pulse" in home


# ── (b) render path performs NO model call (cache only) ──────────────────────

def test_render_row_makes_no_model_call(env, tmp_path, monkeypatch):
    """Rendering a row reads the cached objective only — the summarizer's
    candidate-generation (runner-invoking) functions must NOT be called."""
    gui, rnd, summ, sreg = env
    folder = tmp_path / "NoModel"
    pid = _mkproject(rnd, folder, "NoModel")["id"]
    _write_cached_project_summary(summ, folder, pid, "Cached objective text.")
    sreg.register_session(pid, "planning", status=sreg.STATUS_RUNNING,
                          label="plan")

    calls = []
    for fn in ("_generate_candidates", "_generate_project_candidates",
               "summarize_project", "summarize_session"):
        if hasattr(summ, fn):
            monkeypatch.setattr(summ, fn,
                                lambda *a, _n=fn, **k: calls.append(_n))

    row = gui.render_project_tile_html(rnd.get_project(pid))
    assert "Cached objective text." in row      # served from cache
    assert calls == [], f"render path invoked the model: {calls}"


def test_projects_html_fragment_makes_no_model_call(env, tmp_path, monkeypatch):
    """The /api/rnd/projects_html in-place fragment (render_projects_view_html)
    must also be cache-only — no model call when re-rendering rows."""
    gui, rnd, summ, sreg = env
    folder = tmp_path / "Frag"
    pid = _mkproject(rnd, folder, "Frag")["id"]
    _write_cached_project_summary(summ, folder, pid, "Frag objective.")
    sreg.register_session(pid, "research", status=sreg.STATUS_RUNNING)

    calls = []
    for fn in ("_generate_candidates", "_generate_project_candidates",
               "summarize_project", "summarize_session"):
        if hasattr(summ, fn):
            monkeypatch.setattr(summ, fn,
                                lambda *a, _n=fn, **k: calls.append(_n))

    frag = gui.render_projects_view_html()
    assert "Frag objective." in frag
    assert calls == [], f"projects_html invoked the model: {calls}"


# ── (c) real Playwright/Chromium test ────────────────────────────────────────

@pytest.fixture
def server(env):
    gui = env[0]
    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield env, f"http://127.0.0.1:{port}", port
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


def test_home_dashboard_reflects_activity_and_refreshes_in_place(server, tmp_path, monkeypatch):
    """Real browser: the home R&D row shows the objective + running/activity
    reflection (not just a dot); then a background summary update + a
    projects_html refresh updates the row in place; no JS console errors. Saves
    _devtest/wave7_dashboard.png for orchestrator review."""
    import terminal_session as ts
    monkeypatch.setattr(ts, "reconcile_and_advance", lambda *args, **kwargs: {})
    pytest.importorskip("playwright.sync_api")
    (gui, rnd, summ, sreg), base, _ = server
    folder = tmp_path / "Live"
    pid = _mkproject(rnd, folder, "LiveProj")["id"]
    _write_cached_project_summary(
        summ, folder, pid, "Objective: build the linked pipeline cockpit.")
    sreg.register_session(pid, "planning", status=sreg.STATUS_RUNNING,
                          label="Crucible plan run")

    from playwright.sync_api import sync_playwright
    devtest = Path(__file__).resolve().parents[1] / "_devtest"
    devtest.mkdir(exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        errors = []
        pg.on("console",
              lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.goto(f"{base}/", wait_until="networkidle")
        # Reveal the R&D view (the rows live under #rndProjectsRows, inside
        # #view-rnd which showView() displays). _rndViewActive() gates the
        # in-place refresh on this view being visible.
        pg.evaluate("() => showView && showView('rnd')")
        # Scope to #rndProjectsRows (the view-rnd container) — the same row
        # markup also appears in the main dashboard section, so an unscoped
        # selector is ambiguous.
        row_sel = f'#rndProjectsRows .rnd-row[data-project-id="{pid}"]'
        pg.wait_for_selector(row_sel, timeout=8000)
        # The row reflects activity (not just a dot).
        assert pg.eval_on_selector_all(
            f"{row_sel} .rnd-row-activity", "e=>e.length") == 1
        assert pg.eval_on_selector_all(
            f"{row_sel} .rnd-act-pulse", "e=>e.length") == 1
        txt = pg.eval_on_selector(row_sel, "e=>e.innerText")
        assert "running: 1" in txt
        assert "linked pipeline cockpit" in txt
        assert "Crucible plan run" in txt
        pg.screenshot(path=str(devtest / "wave7_dashboard.png"), full_page=True)

        # Simulate a background summary landing: update the cache, then drive the
        # in-place refresh (rndRowsRefresh fetches /api/rnd/projects_html).
        _write_cached_project_summary(
            summ, folder, pid, "Objective UPDATED by the background summarizer.")
        pg.evaluate("() => rndRowsRefresh && rndRowsRefresh()")
        pg.wait_for_function(
            "() => { const r = document.querySelector("
            f"'#rndProjectsRows .rnd-row[data-project-id=\"{pid}\"]');"
            " return r && r.innerText.includes('UPDATED by the background'); }",
            timeout=8000)
        txt2 = pg.eval_on_selector(row_sel, "e=>e.innerText")
        assert "UPDATED by the background" in txt2
        # The activity reflection survives the in-place swap.
        assert pg.eval_on_selector_all(
            f"{row_sel} .rnd-row-activity", "e=>e.length") == 1
        assert not errors, f"JS console errors: {errors}"
        b.close()
