"""Gandalf v1 Wave 3 — the white-wizard Gandalf tab: real Chromium interaction.

Machine-checkable falsifiable conditions:
  1. The Gandalf panel renders ABOVE the Grass panel (bounding-box top compared).
  2. Clicking a run row makes its executive-summary body VISIBLE (the .gbody goes
     from display:none to visible AND is populated with the exec-summary fetched
     via the traversal-safe /artifact route).
  3. Clicking "Re-run" fires POST /api/rnd/gandalf_run (intercepted by a page
     route, asserting the request method + URL + the project_id payload).

DEV-ONLY: gated by pytest.importorskip("playwright.sync_api") so the suite skips
cleanly where Playwright is absent. Playwright is NEVER imported by product code.

Hermetic: temp data/project dirs, stub PTY, an OS-assigned port (asserted
!= 8777), the Gandalf seams stubbed, never real data / model / node / network.
"""
import importlib
import sys
import threading
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
FAKE = (_TESTS / "fake_claude.py").as_posix()
DRAFT_STUB = (_TESTS / "stub_gandalf_draft.py").as_posix()
HOST_STUB = (_TESTS / "stub_gandalf_host.py").as_posix()


@pytest.fixture
def gui_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    monkeypatch.setenv("ANCHOR_PROACTIVE_SUMMARY", "")  # OFF
    monkeypatch.setenv("ANCHOR_GANDALF_HOST_CMD", f"{sys.executable} {HOST_STUB}")
    monkeypatch.setenv("ANCHOR_GANDALF_SKILL_DIR", str(tmp_path / "no-skill"))
    for mod in ("paths", "job_runner", "rnd_registry", "lanes",
                "effort_history", "summarizer", "gandalf"):
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


def _mkproject(folder, name="P"):
    import rnd_registry
    folder.mkdir(parents=True, exist_ok=True)
    return rnd_registry.add_project(name, str(folder))


def _seed_ok_run(folder, pid, run_id="run-1700000000000",
                 verdict="Sound core, the build handoff is the real risk."):
    """Seed one OK Gandalf run: the index record + the on-disk exec-summary the
    /artifact route serves on click."""
    import gandalf
    run_dir = Path(folder) / "gandalf" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "exec-summary.md").write_text(
        "# Gandalf — executive summary\n\nThe diagnosis is sound; the handoff "
        "seam is still in flight.\n", encoding="utf-8")
    (run_dir / "report.md").write_text("# Gandalf read\n", encoding="utf-8")
    (run_dir / "advisor-output.json").write_text("{}\n", encoding="utf-8")
    gandalf._append_index(str(folder), pid, {
        "schema_version": gandalf.GANDALF_INDEX_SCHEMA_VERSION,
        "run_id": run_id,
        "ts": 1700000000.0,
        "ok": True,
        "verdict": verdict,
        "degraded": True,
        "cross_model": False,
        "report_rel": f"gandalf/{run_id}/report.md",
        "exec_rel": f"gandalf/{run_id}/exec-summary.md",
        "advisor_rel": f"gandalf/{run_id}/advisor-output.json",
    })


def test_gandalf_panel_above_grass_and_row_expands(server, tmp_path):
    pytest.importorskip("playwright.sync_api")
    pytest.skip("RETIRED FROM PROJECT PAGES (2026-08-07, John): the standalone "
                "Gandalf panel is gone from project windows — commissioned "
                "Gandalf runs live in the Seal's run ledger. The panel remains "
                "only in the dashboard's slim Workbench (/project/__dashboard__), "
                "where it renders from the same _render_layoutd_gandalf_panel.")
    gui, base, _ = server
    folder = tmp_path / "Proj"
    pid = _mkproject(folder, "Proj")["id"]
    _seed_ok_run(folder, pid)

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        errors = []
        pg.on("console",
              lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.goto(f"{base}/project/{pid}", wait_until="domcontentloaded")
        from tests.ui_helpers import expand_workbench
        expand_workbench(pg)  # the Workbench tile now opens collapsed

        # (1) the Gandalf panel renders ABOVE the Grass panel (top coordinate).
        pg.wait_for_selector("#gandalfPanel", timeout=5000)
        gtop = pg.eval_on_selector(
            "#gandalfPanel", "e => e.getBoundingClientRect().top")
        grass = pg.query_selector(".gandalf-panel ~ .panel, #gandalfPanel + .panel")
        # Find the grass panel by its title text.
        grass_top = pg.evaluate(
            """() => {
                const panels = Array.from(document.querySelectorAll('.rightcol .panel'));
                const grass = panels.find(p => p.textContent.indexOf('Grass') >= 0);
                return grass ? grass.getBoundingClientRect().top : null;
            }""")
        assert grass_top is not None, "no Grass panel found"
        assert gtop < grass_top, \
            f"Gandalf panel ({gtop}) must be ABOVE Grass ({grass_top})"

        # John tweak: the run list starts COLLAPSED on first load — assert it,
        # then expand it via the header caret so the run row is interactable.
        assert pg.eval_on_selector(
            "#gandalfRuns",
            "e => e.classList.contains('collapsed')") is True, \
            "Gandalf run list must start COLLAPSED by default"
        # the run row is hidden while the list is collapsed.
        assert pg.eval_on_selector(
            "#gandalfPanel .grun", "e => e.offsetParent !== null") is False, \
            "run rows must be hidden while the list is collapsed"
        pg.click("#gandalfRunsTog")
        pg.wait_for_function(
            "() => { var l = document.getElementById('gandalfRuns');"
            " return l && !l.classList.contains('collapsed'); }", timeout=5000)

        # (2) clicking a run row reveals + populates its exec-summary body.
        row = pg.query_selector("#gandalfPanel .grun")
        assert row is not None, "no Gandalf run row rendered"
        # body hidden before the click
        vis0 = pg.eval_on_selector(
            "#gandalfPanel .grun .gbody",
            "e => e.offsetParent !== null")
        assert vis0 is False, "exec body should start hidden"
        row.click()
        # The row gets .open and the exec body becomes visible + populated.
        pg.wait_for_function(
            """() => {
                const r = document.querySelector('#gandalfPanel .grun');
                const body = r && r.querySelector('.gbody');
                const exec = r && r.querySelector('.gexec');
                return r && r.classList.contains('open')
                  && body && body.offsetParent !== null
                  && exec && exec.textContent.indexOf('diagnosis is sound') >= 0;
            }""", timeout=5000)

        # (3) clicking Re-run fires POST /api/rnd/gandalf_run with the project_id.
        captured = {}

        def _route(route):
            req = route.request
            captured["method"] = req.method
            captured["url"] = req.url
            try:
                captured["post"] = req.post_data
            except Exception:
                captured["post"] = None
            # Fulfill so we don't actually spawn a run during the UI test.
            route.fulfill(status=200,
                          content_type="application/json",
                          body='{"ok": true, "scheduled": true}')

        pg.route("**/api/rnd/gandalf_run", _route)
        pg.click("#gandalfPanel .gandalf-rerun")
        pg.wait_for_function(
            "() => window.__gandalf_rerun_seen === true || true", timeout=1000)
        # Give the click handler a tick to issue the fetch.
        pg.wait_for_timeout(300)
        assert captured.get("method") == "POST", \
            f"Re-run did not POST: {captured!r}"
        assert "/api/rnd/gandalf_run" in (captured.get("url") or "")
        assert pid in (captured.get("post") or ""), \
            f"Re-run POST missing project_id: {captured.get('post')!r}"

        # No console errors broke the panel JS.
        assert not errors, f"console errors: {errors}"
        b.close()


def test_gandalf_empty_state_shows_run_button(server, tmp_path):
    pytest.importorskip("playwright.sync_api")
    pytest.skip("RETIRED FROM PROJECT PAGES (2026-08-07, John): the standalone "
                "Gandalf panel is gone from project windows — commissioned "
                "Gandalf runs live in the Seal's run ledger. The panel remains "
                "only in the dashboard's slim Workbench (/project/__dashboard__), "
                "where it renders from the same _render_layoutd_gandalf_panel.")
    gui, base, _ = server
    folder = tmp_path / "Fresh"
    pid = _mkproject(folder, "Fresh")["id"]  # no runs seeded

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.goto(f"{base}/project/{pid}", wait_until="domcontentloaded")
        from tests.ui_helpers import expand_workbench
        expand_workbench(pg)  # the Workbench tile now opens collapsed
        pg.wait_for_selector("#gandalfPanel", timeout=5000)
        # honest empty state, with a Run button, no run rows.
        empty = pg.query_selector("#gandalfPanel .gandalf-empty")
        assert empty is not None, "no empty-state element"
        assert "No Gandalf read yet" in (empty.text_content() or "")
        rows = pg.query_selector_all("#gandalfPanel .grun")
        assert not rows, "empty state should render zero run rows"
        run_btn = pg.query_selector("#gandalfPanel .gandalf-empty .gandalf-run")
        assert run_btn is not None, "empty state must offer a Run button"
        b.close()


def test_gandalf_panel_absent_from_project_pages(server, tmp_path):
    """(2026-08-07, John) The standalone Gandalf panel is GONE from project
    windows; it renders only for the dashboard's slim Workbench."""
    gui, base, _ = server
    folder = tmp_path / "NoPanel"
    pid = _mkproject(folder, "NoPanel")["id"]
    html = gui.render_project_window_html(pid)
    # assert on the MARKUP (the app JS legitimately mentions #gandalfPanel).
    assert "id='gandalfPanel'" not in html and 'id="gandalfPanel"' not in html,         "Gandalf panel markup leaked onto a project page"
