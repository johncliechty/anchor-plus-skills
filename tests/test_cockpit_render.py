"""v4 Wave 4 — Paradigm-2 project cockpit: lane tiles + lights + inline panels.

Locks the Wave-4 Done-when at the RENDER level (no browser): the project window
re-lays-out to the locked Paradigm 2 — each lane's most-recent session is a TILE
carrying a status-light element (``.lt green/amber/red/grey`` from the
``session_registry`` status→color bucket), a panel-stack container sits below the
board, the JS exposes the accordion panel-manager contract
(``openPanel``/``minimizePanel``/``killPanel``/``repopulate``), the kill control
is confirm-gated, and NO floating-window (``.termwin``) markup remains.

String-level assertions over ``render_project_window_html``, mirroring the
project-window render tests in ``tests/test_project_window.py``. The stub PTY
backend is selected so nothing real is spawned; ``:8777`` / real data are never
touched (these tests render HTML only and never bind a port).
"""
import importlib

import pytest


@pytest.fixture
def gui(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    import paths
    importlib.reload(paths)
    import rnd_registry
    importlib.reload(rnd_registry)
    import effort_history
    importlib.reload(effort_history)
    import sessions
    importlib.reload(sessions)
    import anchor_gui
    importlib.reload(anchor_gui)
    return anchor_gui


def _mkproject(gui, tmp_path, name="Cockpit"):
    folder = tmp_path / "P"
    folder.mkdir(exist_ok=True)
    pid = gui.select_existing_project(name, str(folder))["entry"]["id"]
    return folder, pid


# ── status → light mapping (uses the locked session_registry buckets) ────────

def test_session_light_class_maps_locked_color_buckets(gui):
    """_session_light_class maps an effort view to the LOCKED color bucket:
    running→green, needs-input/done→amber, failed/cancelled/interrupted→red,
    idle/discovered/unknown→grey — the same buckets session_registry defines."""
    import job_runner as jr
    f = gui._session_light_class
    # running → green
    assert f({"is_live": True, "status": jr.STATUS_RUNNING}) == "green"
    # needs-input → amber
    assert f({"is_live": True, "needs_input": True}) == "amber"
    # done → amber
    assert f({"is_done": True, "status": jr.STATUS_DONE}) == "amber"
    assert f({"status": jr.STATUS_DONE}) == "amber"
    # failed / cancelled / interrupted → red
    assert f({"status": jr.STATUS_FAILED}) == "red"
    assert f({"status": jr.STATUS_CANCELLED}) == "red"
    assert f({"status": jr.STATUS_INTERRUPTED}) == "red"
    # discovered / idle / unknown → grey
    assert f({"discovered": True}) == "grey"
    assert f({"status": ""}) == "grey"
    assert f(None) == "grey"


# ── lane tile carries the correct light class for its session's status ───────

def test_running_session_tile_carries_green_light(gui, tmp_path):
    """A lane whose most-recent session is RUNNING renders its tile with a green
    status light + a click-to-expand hook targeting the inline panel."""
    import effort_history as eh
    import job_runner as jr
    folder, pid = _mkproject(gui, tmp_path)
    # A real (non-discovered) running effort → the lane tile is green.
    eh.record_effort(str(folder), pid, "plan", "p_run", skill="crucible",
                     extra={"status": jr.STATUS_RUNNING})
    # Force the live-status join: the job record reports RUNNING.
    html = gui.render_project_window_html(pid)
    # v12 Wave 2 Layout-D: the plan session is the Plan/Build headline card,
    # carrying the legacy lane-tile alias + the status light (a .dot in the
    # mockup) + the openPanel click hook.
    assert "tile lane-tile" in html
    # The headline card carries the GREEN light (running bucket) + the openPanel
    # hook (a non-discovered RUNNING effort → green).
    assert "data-light=\"green\"" in html
    assert "<span class='dot green" in html
    assert "laneTileClick(event," in html
    assert "openPanel(" in html


def test_done_session_tile_carries_amber_light(gui, tmp_path):
    """A DONE session's lane tile carries the amber light (done→amber bucket)."""
    import effort_history as eh
    import job_runner as jr
    folder, pid = _mkproject(gui, tmp_path)
    eh.record_effort(str(folder), pid, "research", "r_done",
                     skill="researchPrime", extra={"status": jr.STATUS_DONE})
    html = gui.render_project_window_html(pid)
    assert "data-light=\"amber\"" in html


def test_discovered_session_tile_is_grey(gui, tmp_path):
    """An imported/discovered session (no run metrics) → a grey lane-tile light
    (never fabricated as running)."""
    import effort_history as eh
    folder, pid = _mkproject(gui, tmp_path)
    jid = eh.discovered_job_id("plan", "planning/rnd-v1/PLAN.md")
    eh.record_effort(
        str(folder), pid, "plan", jid, skill="crucible",
        extra={"source": eh.SOURCE_DISCOVERED,
               "artifact_path": "planning/rnd-v1/PLAN.md",
               "created_at": 1000.0, "title": "v1 Plan"})
    html = gui.render_project_window_html(pid)
    assert "data-light=\"grey\"" in html


# ── panel-stack container present ────────────────────────────────────────────

def test_panel_stack_container_present(gui, tmp_path):
    """A panel-stack container exists below the board (the inline-panel host)."""
    _, pid = _mkproject(gui, tmp_path)
    html = gui.render_project_window_html(pid)
    assert "id='panelStack'" in html
    assert "class='panel-stack'" in html
    # The lane-tile light CSS + the panel CSS classes are served.
    assert ".lt.green{" in html
    assert ".lt.amber{" in html
    assert ".lt.red{" in html
    assert ".lt.grey{" in html
    assert ".panel-stack{" in html
    assert ".panel .pbar{" in html


# ── accordion JS symbols present ─────────────────────────────────────────────

def test_accordion_panel_manager_contract_present(gui, tmp_path):
    """The JS exposes the accordion panel-manager contract: openPanel,
    minimizePanel, killPanel, and a repopulate() reading /api/rnd/term_sessions."""
    _, pid = _mkproject(gui, tmp_path)
    html = gui.render_project_window_html(pid)
    assert "function openPanel" in html
    assert "function minimizePanel" in html
    assert "function killPanel" in html
    assert "async function repopulate" in html
    # repopulate reads the read-only registry endpoint (the repopulate hook).
    assert "/api/rnd/term_sessions" in html
    # The lane-tile click hook is the panel-open entry point.
    assert "function laneTileClick" in html


# ── kill control is gated by a confirm ───────────────────────────────────────

def test_kill_control_is_confirm_gated(gui, tmp_path):
    """killPanel (the panel "×") POSTs term_kill ONLY behind a confirm()."""
    _, pid = _mkproject(gui, tmp_path)
    html = gui.render_project_window_html(pid)
    # killPanel must reference both confirm( and the term_kill endpoint.
    head, _, after = html.partition("async function killPanel")
    assert after, "killPanel function not found"
    body = after.split("\n}", 1)[0]
    assert "confirm(" in body, "kill is not confirm-gated"
    assert "/api/rnd/term_kill" in body
    # minimize is NOT a kill: minimizePanel must not POST term_kill.
    _, _, min_after = html.partition("function minimizePanel")
    min_body = min_after.split("\n}", 1)[0]
    assert "/api/rnd/term_kill" not in min_body


# ── NO floating-window markup remains in the cockpit render ───────────────────

def test_no_floating_window_markup_remains(gui, tmp_path):
    """The v3 floating stacking-window manager is gone: no .termwin class, no
    windowLayer container, no openSessionWindow / drag / resize code."""
    _, pid = _mkproject(gui, tmp_path)
    html = gui.render_project_window_html(pid)
    for needle in ("termwin", "windowLayer", "winlayer", "openSessionWindow",
                   "_toggleMinimize", "_wireDrag", "_wireResize", "_winZ"):
        assert needle not in html, "leftover floating-window token: " + needle


# ── brace hygiene (f-string + RAW string discipline) ─────────────────────────

def test_cockpit_render_no_leaked_braces(gui, tmp_path):
    """The Paradigm-2 CSS/JS (plain + RAW string literals) must not leak doubled
    ``{{``/``}}`` into the served HTML. v4.1: the old v2 console drawer
    (openTerminal / launchLane) was REMOVED — the inline panel stack is the only
    terminal surface — so we assert the seeded panel launch path instead."""
    _, pid = _mkproject(gui, tmp_path)
    html = gui.render_project_window_html(pid)
    assert "{{" not in html
    assert "}}" not in html
    # The seeded launch path is the live affordance; the v2 console drawer is gone.
    assert "function newTermSession" in html
    assert "function openPanel" in html
    assert "function openTerminal" not in html
    assert "function launchLane" not in html
