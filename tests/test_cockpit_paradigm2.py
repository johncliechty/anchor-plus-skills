"""HARDENED gate for the v4.1 "Project Cockpit" render (the un-gameable one).

Why this file exists: the original v4 build passed its tests by GREP — it asserted
the *strings* ``lane-tile``/``panel-stack``/``openPanel`` existed (in CSS/JS) and
that ``termwin`` was gone, while the rendered BODY was still the old v3 effort-card
kanban and the inline panel was unreachable. A user opening any normal/new project
saw the old UI. These tests assert the RENDERED BODY STRUCTURE (style+script
stripped, so CSS/JS occurrences can't create a false pass) and — via Playwright —
that clicking a HISTORICAL tile actually OPENS the inline panel.

Covers the exact failing cases: a multi-lane project, a discovered/imported-only
project, and a brand-new zero-session project. Never touches :8777 or real data.
"""
import importlib
import json
import re
import threading
from html.parser import HTMLParser
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()


@pytest.fixture
def gui_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    for mod in ("paths", "job_runner", "rnd_registry", "lanes",
                "effort_history", "summarizer", "gate_adapter"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import anchor_gui
    yield importlib.reload(anchor_gui)


def _mkproject(folder, name="P"):
    import rnd_registry
    folder.mkdir(parents=True, exist_ok=True)
    return rnd_registry.add_project(name, str(folder))


def _strip(html):
    """Return the <body>, with <style>/<script> removed, so CSS class
    definitions and JS function names can't satisfy a structural assertion."""
    b = re.sub(r"<style[\s\S]*?</style>", "", html)
    b = re.sub(r"<script[\s\S]*?</script>", "", b)
    m = re.search(r"<body[^>]*>([\s\S]*)</body>", b)
    return m.group(1) if m else b


class _Collector(HTMLParser):
    """Collect (tag, classes, attrs) for every element, in document order."""
    def __init__(self):
        super().__init__()
        self.els = []
    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        cls = (d.get("class") or "").split()
        self.els.append((tag, cls, d))


def _parse(body):
    c = _Collector()
    c.feed(body)
    return c.els


# ── POSITIVE: the lane board IS Paradigm 2 (parsed DOM, not grep) ───────────

def test_lane_board_is_layoutd(gui_env, tmp_path):
    """v12 Wave 2: the 5-col .p2lanes grid is RETIRED for Layout D — two headline
    cards + collapsible shelves of little-tiles + a persistent right column. Each
    headline/little-tile still carries the legacy ``tile lane-tile`` click hook so
    the W10 panel wiring binds."""
    gui = gui_env
    import effort_history as eh
    folder = tmp_path / "Multi"
    pid = _mkproject(folder, "Multi")["id"]
    fp = str(folder)
    eh.record_effort(fp, pid, "research", "r1", skill="researchPrime",
                     prompt_seed="Survey")
    eh.record_effort(fp, pid, "research", "r2", skill="researchPrime",
                     prompt_seed="Survey v2")
    eh.record_effort(fp, pid, "plan", "p1", skill="crucible",
                     prompt_seed="Plan it")
    els = _parse(_strip(gui.render_project_window_html(pid)))
    classes = [" ".join(c) for _, c, _ in els]
    # the old grid is gone
    assert sum("p2lanes" in c.split() for c in classes) == 0
    assert sum("p2col" in c.split() for c in classes) == 0
    # Layout-D: two section labels + two headline cards
    assert sum("sectionlbl" in c.split() for c in classes) == 2
    assert sum("headline" in c.split() for c in classes) == 2
    # genuine tiles exist as elements (not just CSS): headline + little-tiles
    tiles = [d for t, c, d in els if "tile" in c]
    assert tiles, "no .tile elements rendered in the Layout-D board"
    # each tile carries the legacy click hook + a status light
    lit = [d for t, c, d in els if "lane-tile" in c]
    assert lit, "no .lane-tile click targets"
    assert all("onclick" in d for d in lit), "tiles missing click hook"
    light_classes = [c for t, c, d in els if "lt" in c or "dot" in c]
    assert any(set(c) & {"green", "amber", "red", "grey"} for c in light_classes)


# ── NEGATIVE: the OLD v3 kanban is GONE from the rendered lane board ─────────

def _assert_no_old_lane_markers(body):
    """The old effort-card kanban must not appear in the rendered body."""
    forbidden = [
        "class='kan'", 'class="kan"',
        "col-cards",
        "class='effort'", 'class="effort"', "effort discovered",
        "session-summary-link",          # old in-lane summary accordion
        "openReport(",                   # old report-viewer link on the card
        "class='termwin'", "windowLayer",  # old floating window manager
    ]
    hits = [m for m in forbidden if m in body]
    assert not hits, f"old v3 lane markers still rendered in body: {hits}"


def test_no_old_kanban_multi_lane(gui_env, tmp_path):
    gui = gui_env
    import effort_history as eh
    folder = tmp_path / "Neg"
    pid = _mkproject(folder, "Neg")["id"]
    fp = str(folder)
    eh.record_effort(fp, pid, "research", "r1", skill="researchPrime",
                     prompt_seed="x")
    eh.record_effort(fp, pid, "build", "b1", skill="foreman", prompt_seed="y")
    _assert_no_old_lane_markers(_strip(gui.render_project_window_html(pid)))


def test_zero_session_project_is_layoutd_not_old(gui_env, tmp_path):
    """A brand-new project (the user's exact failing case) renders the empty
    Layout-D shell, never the old kanban — and never the retired .p2lanes grid."""
    gui = gui_env
    folder = tmp_path / "Fresh"
    pid = _mkproject(folder, "Fresh")["id"]
    body = _strip(gui.render_project_window_html(pid))
    assert "p2lanes" not in body
    assert "class='p2col'" not in body and 'class="p2col"' not in body
    # two Layout-D zones still render (honest empty headline placeholders)
    assert body.count("class='sectionlbl'") == 2
    _assert_no_old_lane_markers(body)


def test_imported_only_project_is_layoutd_not_old(gui_env, tmp_path):
    """A project whose only sessions are DISCOVERED (imported) — the case that
    looked 100% old before — renders Layout-D tiles, no old kanban."""
    gui = gui_env
    folder = tmp_path / "Imp"
    # a discovered planning artifact pair → a discovered session
    plan_dir = folder / "planning" / "rnd-x"
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "MASTER-PLAN.md").write_text("# Master\n", encoding="utf-8")
    (plan_dir / "IMPLEMENTATION-PLAN.md").write_text("# Impl\n", encoding="utf-8")
    pid = _mkproject(folder, "Imp")["id"]
    # discover brownfield artifacts the same way the rescan/register path does
    import brownfield_scan, effort_history as eh
    eh.adopt_discovered(str(folder), pid, brownfield_scan.scan(str(folder)))
    body = _strip(gui.render_project_window_html(pid))
    assert "p2lanes" not in body
    _assert_no_old_lane_markers(body)
    els = _parse(body)
    assert any("tile" in c for _, c, _ in els), "imported session not a tile"


# ── REAL click→panel test (Playwright): the panel must open for a HISTORICAL tile

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
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


def test_clicking_historical_tile_opens_inline_panel(server, tmp_path):
    """The core regression (v12 W10 migration): clicking an EFFORT tile for a
    NON-LIVE (historical) session must open the SINGLE bottom DOCK (replacing the
    inline-panel stack for efforts) bound to that effort AND its summary region
    must POPULATE with real content (>=1 doc link in .slinks) — proving the dock
    is reachable (laneTileClick → openEffortDock no longer dead for historical
    ids) and not an empty shell, with no JS console errors. Uses a discovered
    planning session whose MASTER/IMPL docs resolve to real doc-role links.
    """
    pytest.importorskip("playwright.sync_api")
    gui, base, _ = server
    folder = tmp_path / "Click"
    plan_dir = folder / "planning" / "rnd-x"
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "MASTER-PLAN.md").write_text("# Master Plan\n", encoding="utf-8")
    (plan_dir / "IMPLEMENTATION-PLAN.md").write_text("# Impl Plan\n", encoding="utf-8")
    pid = _mkproject(folder, "Click")["id"]
    import brownfield_scan, effort_history as eh
    eh.adopt_discovered(str(folder), pid, brownfield_scan.scan(str(folder)))

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
        # v12 Wave 2: Layout-D — two headline zones, no .p2col grid.
        assert pg.eval_on_selector_all(".p2col", "e=>e.length") == 0
        assert pg.eval_on_selector_all(".sectionlbl", "e=>e.length") == 2
        assert pg.eval_on_selector_all(".lane-tile", "e=>e.length") >= 1, \
            "no clickable lane tile rendered"
        # the dock starts hidden + UNBOUND (no effort selected → negative case).
        assert pg.eval_on_selector(
            "#effortDock", "e=>e.style.display") == "none"
        pg.click(".lane-tile")
        # the SINGLE bottom dock opens (the W10 surface for efforts).
        pg.wait_for_function(
            "() => document.getElementById('effortDock').style.display === 'flex'",
            timeout=5000)
        # and it is BOUND to a real effort (data-effort-id set).
        assert pg.eval_on_selector(
            "#effortDock", "e=>e.getAttribute('data-effort-id')"), \
            "dock opened but not bound to an effort_id"
        # the summary region (ON TOP) populates with >=1 real doc link.
        pg.wait_for_selector("#dockSummary .slinks a", timeout=8000)
        links = pg.eval_on_selector_all("#dockSummary .slinks a", "e=>e.length")
        assert links >= 1, "dock opened but summary has no doc links (empty shell)"
        assert not errors, f"JS console errors on dock open: {errors}"
        b.close()
