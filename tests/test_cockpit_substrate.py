"""v4 Wave 1 — the cockpit lane-launch uses the SEEDED v3 substrate.

Locks the Wave-1 Done-when at the RENDER level: the project-window's lane
"+ New <lane> run" affordance must launch the seeded ConPTY path
(``newTermSession`` → ``POST /api/rnd/term_start`` →
``terminal_session.start_session``), NOT the v2 unseeded stream-json REPL
(``openTerminal`` → ``POST /api/rnd/start_terminal`` → ``rnd_terminal``) that
caused the repeating-prompt bug.

String-level assertions over ``render_project_window_html`` (no browser),
mirroring the project-window render tests in ``tests/test_project_window.py``.
The seed substrate itself (``terminal_session`` / ``session_registry``) is
covered by ``tests/test_terminal_seed.py`` and is intentionally not touched here.
"""
import importlib
import re

import pytest


@pytest.fixture
def gui(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
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


def _make_window_html(gui, tmp_path, name="Cockpit"):
    folder = tmp_path / "P"
    folder.mkdir()
    pid = gui.select_existing_project(name, str(folder))["entry"]["id"]
    return gui.render_project_window_html(pid)


def test_lane_launch_uses_seeded_term_start_not_start_terminal(gui, tmp_path):
    """(a) Session launch uses the seeded path (newTermSession / term_start).
    (b) NO launch affordance wires the v2 unseeded openTerminal / start_terminal
    path.

    v12 Wave 2 Layout-D: the per-lane "+ New <lane> run" launchers are retired —
    the masthead "Open terminal" wires the live general-session start and the
    "+ New effort" control (inert this wave, wired in W10) is the effort-start
    entry — but the seeded ConPTY start path is unchanged."""
    html = _make_window_html(gui, tmp_path)

    # (a) The seeded ConPTY start path is defined + wired; the surviving live
    #     launch affordance (masthead general session) routes through it.
    assert "function newTermSession" in html
    # General launch uses settings-backed default_cli (newEffort('general') → newGeneral()).
    assert "newEffort('general')" in html or "newGeneral(" in html
    # (2026-08-07, John's simple workbench) only the general starter remains.
    assert "id='newGeneralBtn'" in html
    assert "id='newResearchBtn'" not in html
    assert "id='newPlanBuildBtn'" not in html
    # The seeded endpoint is the launch target.
    assert "/api/rnd/term_start" in html

    # (b) The launch must NOT invoke the v2 unseeded REPL: openTerminal(...) must
    #     not appear as a launch onclick handler, and no launch affordance may
    #     reference the v2 start_terminal endpoint. (The v2 function/endpoint may
    #     still exist on disk for the legacy console drawer, but the cockpit
    #     launch no longer routes through it.)
    assert "onclick=\"openTerminal(" not in html
    assert "onclick='openTerminal(" not in html
    # No live-launch button wires the v2 path. The v12 launch affordances are
    # newGeneral(...) (masthead general → W10 dock) + newEffort(...) (+ New research
    # / + New plan/build); none may route through the v2 openTerminal/start_terminal.
    launch_onclicks = re.findall(
        r"onclick=\"((?:newGeneral|newEffort)[^\"]*)\"", html)
    assert launch_onclicks, "no seeded launch affordance (newGeneral/newEffort) rendered"
    for handler in launch_onclicks:
        assert "openTerminal" not in handler
        assert "start_terminal" not in handler


def test_seeded_lane_launch_brace_hygiene(gui, tmp_path):
    """The repointed affordance must not leak doubled braces into the served
    HTML (the surrounding render is f-string-generated)."""
    html = _make_window_html(gui, tmp_path)
    assert "{{" not in html
    assert "}}" not in html
