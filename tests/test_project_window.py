"""Wave 3 — single-instance project window.

Opening project id X twice returns the same instance id (no duplicate window).
"""
import importlib

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


def _record_discovered(eh, folder, pid, lane, rel, ts, title="", kind=""):
    """Helper: record one DISCOVERED planning effort under ``rel`` (folder-rel)."""
    jid = eh.discovered_job_id(lane, rel)
    eh.record_effort(
        folder, pid, lane, jid,
        skill="crucible",
        extra={
            "source": eh.SOURCE_DISCOVERED,
            "artifact_path": rel,
            "created_at": ts,
            "title": title or rel,
            "kind": kind,
        },
    )
    return jid


def test_single_instance_returns_same_id(gui, tmp_path):
    folder = tmp_path / "P"
    folder.mkdir()
    e = gui.select_existing_project("P", str(folder))
    pid = e["entry"]["id"]

    first = gui.open_project_instance(pid)
    assert first["reused"] is False
    second = gui.open_project_instance(pid)
    assert second["reused"] is True
    assert second["instance_id"] == first["instance_id"]


def test_distinct_projects_distinct_instances(gui, tmp_path):
    (tmp_path / "A").mkdir()
    (tmp_path / "B").mkdir()
    a = gui.select_existing_project("A", str(tmp_path / "A"))["entry"]["id"]
    b = gui.select_existing_project("B", str(tmp_path / "B"))["entry"]["id"]
    ia = gui.open_project_instance(a)["instance_id"]
    ib = gui.open_project_instance(b)["instance_id"]
    assert ia != ib


def test_close_then_reopen_is_fresh(gui, tmp_path):
    folder = tmp_path / "P"
    folder.mkdir()
    pid = gui.select_existing_project("P", str(folder))["entry"]["id"]
    first = gui.open_project_instance(pid)["instance_id"]
    assert gui.close_project_instance(pid) is True
    second = gui.open_project_instance(pid)["instance_id"]
    assert second != first


def test_project_window_html_renders(gui, tmp_path):
    folder = tmp_path / "P"
    folder.mkdir()
    pid = gui.select_existing_project("ShinyProj", str(folder))["entry"]["id"]
    html = gui.render_project_window_html(pid)
    assert "ShinyProj" in html
    # Wave 3 contract: empty lanes read "Lane: 0", NOT the old "none-yet" state.
    assert "none-yet" not in html
    assert "Research: 0" in html


def test_project_window_unknown_id_no_crash(gui):
    html = gui.render_project_window_html("nonexistent-id")
    assert "not found" in html.lower()


def test_project_window_css_has_single_braces(gui, tmp_path):
    """F1 regression guard: the /project/<id> <style> block must serve valid
    CSS with single braces — no literal ``{{``/``}}`` leaked from non-f-string
    literals that were wrongly brace-doubled."""
    folder = tmp_path / "P"
    folder.mkdir()
    pid = gui.select_existing_project("ShinyProj", str(folder))["entry"]["id"]
    html = gui.render_project_window_html(pid)
    # No literal doubled braces anywhere in the served HTML.
    assert "{{" not in html
    assert "}}" not in html
    # Known CSS rules render with correct single braces.
    assert "body{font-family" in html
    assert ".rnd-lane{" in html


def test_project_field_only_from_trailing_metadata(gui, tmp_path):
    """F2 regression guard (anchor_gui.py): "Project:" in the task body must NOT
    create a project link; a real trailing ``— Project: <id>`` field must parse
    AND round-trip unchanged through serialize_task_line."""
    md = tmp_path / "proj.md"
    md.write_text(
        "- [ ] Plan Project: Apollo milestones\n"
        "- [ ] Wire dashboard — Priority: 1 — energy: high — [academic] "
        "— Project: abc123\n",
        encoding="utf-8",
    )

    tasks = gui.parse_tasks_from_md(md)
    assert len(tasks) == 2

    # Body mention → no project link.
    assert not tasks[0]["project"]
    assert "Plan Project: Apollo milestones" in tasks[0]["text"]

    # Real trailing field → parsed and preserved on re-serialization.
    assert tasks[1]["project"] == "abc123"
    line = gui.serialize_task_line(tasks[1])
    assert "— Project: abc123" in line
    # Round-trip: parse the serialized line back, project survives unchanged.
    md2 = tmp_path / "proj2.md"
    md2.write_text(line + "\n", encoding="utf-8")
    assert gui.parse_tasks_from_md(md2)[0]["project"] == "abc123"


# ── Wave 4 — most-recent + expander, grass column, linked-tasks strip ────────

def test_kanban_columns_include_grass(gui):
    """The Kanban column set now includes a Grass Catchers column."""
    lanes = [c[0] for c in gui._KANBAN_COLUMNS]
    assert "grass" in lanes
    # Find the grass column tuple: (trio_lane, store_subdir, label, glyph, add).
    grass = next(c for c in gui._KANBAN_COLUMNS if c[0] == "grass")
    assert grass[1] == "grass"
    assert grass[2] == "Grass Catchers"


def test_grass_in_lane_dirs(gui):
    """rnd_registry scaffolds a grass lane dir so the store can hold it."""
    import rnd_registry
    assert "grass" in rnd_registry.LANE_DIRS


def test_grass_column_renders_in_window(gui, tmp_path):
    """v12 Wave 2 Layout-D: Grass is the persistent right-column mini-panel (no
    longer a board lane column), and the two-pane workbench template is retained
    so 'Open workbench' still opens it. The other surfaces (research/plan-build
    zones + Deliverables panel) still render."""
    folder = tmp_path / "P"
    folder.mkdir()
    pid = gui.select_existing_project("Grassy", str(folder))["entry"]["id"]
    html = gui.render_project_window_html(pid)
    # The grass lane column / data-col-lane containers are retired.
    assert "data-col-lane=" not in html
    # Grass is now the right-column mini-panel + the retained workbench template.
    assert "Grass Catcher" in html
    assert "openGrassWorkbench()" in html
    assert "id='grassWorkbenchTpl'" in html
    # The Layout-D zones + the Deliverables panel still render.
    assert html.count("class='sectionlbl'") == 2
    assert "Latest Research" in html
    assert "Latest Plan" in html
    assert "Deliverables" in html


def test_most_recent_plus_previous_sessions_expander(gui, tmp_path):
    """G/W/T: given a zone with >=2 sessions, exactly 1 session is the prominent
    headline and the remainder sit behind the Layout-D collapsible shelf
    (v12 Wave 2 — replaces the old 'previous sessions' expander)."""
    import effort_history as eh
    import re
    folder = tmp_path / "P"
    folder.mkdir()
    pid = gui.select_existing_project("MultiSess", str(folder))["entry"]["id"]
    # Session A (older): two files under brownfield-discovery/.
    _record_discovered(eh, str(folder), pid, "plan",
                       "planning/brownfield-discovery/MASTER-PLAN.md", 1000.0,
                       title="Master Plan", kind="master-plan")
    _record_discovered(eh, str(folder), pid, "plan",
                       "planning/brownfield-discovery/NOTES.md", 1001.0)
    # Session B (newer): one file under rnd-v1/.
    _record_discovered(eh, str(folder), pid, "plan",
                       "planning/rnd-v1/PLAN.md", 2000.0, title="v1 Plan")

    # Two sessions for the planning lane.
    import sessions as sess
    sess_list = sess.list_sessions(str(folder), pid, "plan")
    assert len(sess_list) == 2

    html = gui.render_project_window_html(pid)
    # Strip style/script so CSS/JS occurrences can't satisfy a structural check.
    body = re.sub(r"<style[\s\S]*?</style>", "", html)
    body = re.sub(r"<script[\s\S]*?</script>", "", body)
    # The two plan sessions land in the Plan/Build zone: ONE prominent headline +
    # ONE little-tile in the collapsible shelf. John tweak: the older-runs shelf
    # is COLLAPSED on first load, so the toggle reads "Show all 1 older …" and the
    # wrapper carries .collapsed (the headline card stays visible).
    board = body[body.find("pgrid layoutd"):body.find("grassWorkbenchTpl")]
    assert "Show all 1 older plan/build sessions" in board, \
        "no Plan/Build shelf toggle for the older session (collapsed default)"
    # The shelf div carries the stable `prev-efforts` hook (W4 #3, present iff a
    # zone holds >1 effort) between `shelf-wrap` and `collapsed`; it still renders
    # COLLAPSED by default (the `collapsed` class → CSS display:none).
    assert "shelf-wrap prev-efforts collapsed" in board, \
        "older-runs shelf must render COLLAPSED by default"
    # Exactly two session tiles in the Plan/Build zone (1 headline + 1 minitile) —
    # proving a multi-file session is ONE tile, not N per-file cards.
    pb_tiles = re.findall(
        r"<div class='(?:headline|minitile) tile lane-tile[^>]*"
        r"data-lane=\"(?:plan|planning|build)\"", board)
    assert len(pb_tiles) == 2, \
        "expected exactly 2 Plan/Build session tiles, got %d" % len(pb_tiles)
    # The newest (v1 Plan) is the prominent headline.
    assert re.search(r"<div class='headline tile lane-tile[\s\S]*?v1 Plan", board), \
        "newest session not the prominent headline"


def test_single_session_lane_has_no_previous_expander(gui, tmp_path):
    """A lane with one session shows the card with no 'previous sessions' toggle."""
    import effort_history as eh
    folder = tmp_path / "P"
    folder.mkdir()
    pid = gui.select_existing_project("OneSess", str(folder))["entry"]["id"]
    _record_discovered(eh, str(folder), pid, "build",
                       "build/foreman-run/report.md", 1000.0, title="Build")
    html = gui.render_project_window_html(pid)
    # Build lane has 1 session → no previous-sessions expander at all.
    assert "previous sessions (" not in html


def test_linked_tasks_strip_renders_with_link_affordance(gui, tmp_path):
    """The linked-tasks strip renders a working 'Link task' affordance and the
    Wave-4 strip replaces the old dead-end message."""
    folder = tmp_path / "P"
    folder.mkdir()
    pid = gui.select_existing_project("Linker", str(folder))["entry"]["id"]
    html = gui.render_project_window_html(pid)
    # Link affordance is present and wired to the existing endpoint via JS.
    assert "Link task" in html
    assert "rndLinkTask(" in html
    # JS function is defined in the project-window script.
    assert "function rndLinkTask" in html
    assert "/api/rnd/link_task" in html


def test_linked_tasks_strip_reflects_a_linked_task(gui, tmp_path):
    """A task carrying ``Project: <id>`` appears in the strip with an Unlink."""
    folder = tmp_path / "P"
    folder.mkdir()
    pid = gui.select_existing_project("HasTasks", str(folder))["entry"]["id"]
    # Write a task linked to this project into a domain markdown file.
    gui.DOMAINS_DIR.mkdir(parents=True, exist_ok=True)
    (gui.DOMAINS_DIR / "academic.md").write_text(
        f"- [ ] Wire the dashboard — Priority: 1 — energy: high — [academic] "
        f"— Project: {pid}\n",
        encoding="utf-8",
    )
    tasks = gui.project_tasks(pid)
    assert any("Wire the dashboard" in t.get("text", "") for t in tasks)
    html = gui.render_project_tasks_html(pid)
    assert "Wire the dashboard" in html
    assert "Unlink" in html
    assert "rndUnlinkTask(" in html


# ── Wave 4 (v4) — Paradigm-2 inline expanding-panel manager markup ───────────
# (Replaces the v3 floating stacking-window manager. Same INTENT — status
# colors, minimize-keeps-running, kill-behind-confirm, repopulate-from-registry,
# seeded launch — re-encoded for the inline panel-stack host DOM.)

def test_window_manager_markup_present(gui, tmp_path):
    """The project window carries the inline PANEL-STACK container, the locked
    status-light color classes, the accordion panel manager contract
    (open/minimize/kill/repopulate), and the kill-confirm wiring (a confirm() + a
    term_kill reference). v4.1 removed the old v3 floating-window "Live terminals"
    bar; v5 Wave 1 reintroduces a #sessionBar — but as the close-to-tile REOPEN
    vector (clickable live-session chips), NOT the old floating-window manager.
    Status colors ride the .lt light classes (green/amber/red/grey)."""
    folder = tmp_path / "P"
    folder.mkdir()
    pid = gui.select_existing_project("WMProj", str(folder))["entry"]["id"]
    html = gui.render_project_window_html(pid)
    # v5 Wave 1: the #sessionBar is back as the live-session reopen vector (chips),
    # alongside the inline panel stack (the terminal surface). The OLD floating
    # window-manager markup stays gone (asserted further below).
    assert "id='sessionBar'" in html
    assert "class='live-session-bar'" in html
    assert "id='panelStack'" in html
    assert "class='panel-stack'" in html
    # All four LOCKED status-color CSS classes (the .lt status-light variants).
    for cls in (".lt.green", ".lt.amber", ".lt.red", ".lt.grey"):
        assert cls in html, "missing status class: " + cls
    # Accordion panel manager contract: open / minimize / kill / repopulate.
    assert "function openPanel" in html
    assert "function minimizePanel" in html
    assert "function killPanel" in html
    assert "async function repopulate" in html
    # Minimize keeps the session running (no kill on collapse).
    assert "minimizePanel" in html
    # Kill = X gated behind a confirm() that POSTs term_kill.
    assert "function killPanel" in html
    assert "confirm(" in html
    assert "/api/rnd/term_kill" in html
    # Repopulate keeps MANAGED in sync from the registry (loadSessions alias kept).
    assert "loadSessions = repopulate" in html
    assert "/api/rnd/term_sessions" in html
    # The per-lane "new session" affordance calls term_start.
    assert "newTermSession(" in html
    assert "/api/rnd/term_start" in html
    # The per-panel engine toggle flips engines via term_set_engine.
    assert "function _buildEngineToggle" in html
    assert "/api/rnd/term_set_engine" in html
    # NO v3 floating-window markup/code remains in the cockpit.
    assert "termwin" not in html
    assert "windowLayer" not in html
    assert "openSessionWindow" not in html


def test_window_manager_wires_wave3_transport_endpoints(gui, tmp_path):
    """Each terminal panel mounts xterm.js over the Wave-3 transport: WS first
    (term_ws), SSE-out + POST-in fallback (term_stream2 / term_input2), plus
    term_resize. xterm.js (window.Terminal) is vendored + loaded."""
    folder = tmp_path / "P"
    folder.mkdir()
    pid = gui.select_existing_project("Wired", str(folder))["entry"]["id"]
    html = gui.render_project_window_html(pid)
    for ep in ("/api/rnd/term_ws", "/api/rnd/term_stream2",
               "/api/rnd/term_input2", "/api/rnd/term_resize"):
        assert ep in html, "missing endpoint: " + ep
    # xterm.js terminal is instantiated for the window body.
    assert "new window.Terminal(" in html
    assert "/vendor/xterm/xterm.js" in html
    # Token is appended to the WS/SSE URL from localStorage.
    assert "token=" in html


def test_window_manager_no_leaked_braces(gui, tmp_path):
    """Brace hygiene: the Wave-4 window-manager CSS/JS (added in plain + RAW
    string literals) must NOT leak doubled ``{{``/``}}`` into the served HTML."""
    folder = tmp_path / "P"
    folder.mkdir()
    pid = gui.select_existing_project("Braces", str(folder))["entry"]["id"]
    html = gui.render_project_window_html(pid)
    assert "{{" not in html
    assert "}}" not in html
    # Sanity: the inline panel surface is present; the v2 console drawer is gone.
    assert "function openPanel" in html
    assert "function openTerminal" not in html
    assert "function launchLane" not in html


# ── Wave 6 (v3) — in-place expandable session summaries ──────────────────────

def _discovered_planning_session(gui, folder, pid):
    """Record a 2-file brownfield-discovery planning session (one session)."""
    import effort_history as eh
    _record_discovered(eh, str(folder), pid, "plan",
                       "planning/brownfield-discovery/MASTER-PLAN.md", 1000.0,
                       title="Master Plan", kind="master-plan")
    _record_discovered(eh, str(folder), pid, "plan",
                       "planning/brownfield-discovery/NOTES.md", 1001.0)


def test_session_card_inline_expand_wiring_not_navigation(gui, tmp_path):
    """G/W/T: clicking a lane TILE EXPANDS an inline panel in place (openPanel →
    _loadPanelSummary, which fetches /api/rnd/session_summary) — NOT a window.open
    to a /summary page.

    v4.1 cockpit-render: the per-card "summary" accordion was removed; the summary
    now renders INSIDE the opened inline panel (same intent — inline, no nav). The
    tile carries data-session/data-lane and an openPanel hook; the panel fetch
    keys on (pid, lane, session)."""
    folder = tmp_path / "P"
    folder.mkdir()
    pid = gui.select_existing_project("InlineSumm", str(folder))["entry"]["id"]
    _discovered_planning_session(gui, folder, pid)
    html = gui.render_project_window_html(pid)

    # The tile is the inline-expand entry point (no /summary navigation).
    assert "laneTileClick(event," in html
    assert "function openPanel" in html
    assert "function _loadPanelSummary" in html
    # The tile must NOT navigate to a separate /summary page, and the old per-card
    # accordion toggle is gone (detail moved into the opened panel).
    assert "openSummary('/summary" not in html
    assert "window.open('/summary" not in html
    assert "toggleSessionSummary(this)" not in html
    assert "class='session-summary-panel'" not in html
    # The tile carries data-session/data-lane for the panel's summary fetch.
    assert "data-session=" in html
    assert "data-lane=" in html
    # The panel loads the summary from the read-only JSON endpoint (no page nav).
    assert "/api/rnd/session_summary" in html


def test_summary_panel_renders_doc_links_and_effort(gui, tmp_path):
    """The opened inline panel renders the split summary: document links
    (report/artifact routes that open in a NEW TAB) and an effort line (imported →
    'no run metrics').

    v4.1 cockpit-render: the split summary is built by _renderSplitSummary from
    /api/rnd/session_summary + /api/rnd/session_doc_roles, replacing the old
    per-card _renderSessionSummary accordion (same intent — doc links + honest
    effort line)."""
    folder = tmp_path / "P"
    folder.mkdir()
    pid = gui.select_existing_project("PanelRender", str(folder))["entry"]["id"]
    _discovered_planning_session(gui, folder, pid)
    html = gui.render_project_window_html(pid)

    # The split renderer wires doc links to the existing routes, opening them in
    # the UNIFIED named report window (v13 W1 — report links go to
    # target="anchor_report_window" so they refresh ONE tab instead of spawning
    # endless new tabs). The role links resolve from session_doc_roles.
    assert "function _renderSplitSummary" in html
    assert ('target="anchor_report_window"' in html
            or 'target=\\"anchor_report_window\\"' in html)
    assert "/api/rnd/session_doc_roles" in html
    # Effort rendering: tokens + wall-clock; imported honestly shows no metrics.
    assert "wall-clock" in html
    assert "no run metrics" in html
    assert "imported" in html.lower()


def test_launch_new_session_button_wired_to_wave4_path(gui, tmp_path):
    """A new session can still be launched via the Wave-3/4 path (newTermSession →
    term_start). v12 Wave 2 Layout-D: the per-lane "+ New <lane> run" launchers
    are retired — the masthead "Open terminal" wires the live general-session
    start, and the "+ New effort" control (inert this wave, wired in W10) is the
    effort-start entry. The seeded ConPTY start path + the seed-session seam
    (Wave 7's handoff base) are unchanged."""
    folder = tmp_path / "P"
    folder.mkdir()
    pid = gui.select_existing_project("LaunchPanel", str(folder))["entry"]["id"]
    _discovered_planning_session(gui, folder, pid)
    html = gui.render_project_window_html(pid)

    # The seeded ConPTY start path is still defined + wired.
    assert "function newTermSession" in html
    assert "/api/rnd/term_start" in html
    # The surviving live start affordance (masthead general session) + the W10
    # effort-start entry both render.
    assert "newEffort('general')" in html or "newGeneral(" in html
    assert "id='newResearchBtn'" in html  # v12 W10 refine: + New research
    assert "id='newPlanBuildBtn'" in html  # v12 W10 refine: + New plan/build
    # The dead in-lane "Launch new session" button is gone.
    assert "summ-launch-btn" not in html
    assert "_wireLaunchFromPanel" not in html
    # newTermSession still forwards the seed hint into the term_start payload (seam
    # Wave 7 builds the handoff on).
    assert "payload.seed_session = opts.seed_session" in html


def test_summary_panel_no_leaked_braces(gui, tmp_path):
    """Brace hygiene: the Wave-6 accordion JS/CSS must not leak doubled braces."""
    folder = tmp_path / "P"
    folder.mkdir()
    pid = gui.select_existing_project("W6Braces", str(folder))["entry"]["id"]
    _discovered_planning_session(gui, folder, pid)
    html = gui.render_project_window_html(pid)
    assert "{{" not in html
    assert "}}" not in html


def test_session_summary_endpoint_returns_cached(gui, tmp_path, monkeypatch):
    """GET /api/rnd/session_summary returns the cached structured summary for a
    stub session (hermetic: generate via the stub runner first, then fetch the
    cache). Exercises the read-only endpoint over a throwaway server."""
    import json as _json
    import threading as _threading
    import urllib.request as _urlreq
    from pathlib import Path as _Path

    stub = (_Path(__file__).resolve().parent / "stub_summarizer.py").as_posix()
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {stub}")
    monkeypatch.setenv("STUB_SUMMARIZER_CLAIMS",
                       "North Star: cache validated summaries for each session")

    import importlib
    import job_runner
    importlib.reload(job_runner)
    import summarizer
    importlib.reload(summarizer)
    importlib.reload(gui)

    folder = tmp_path / "P"
    folder.mkdir()
    # Real on-disk planning docs so the discovered session has a grounding corpus.
    bd = folder / "planning" / "brownfield-discovery"
    bd.mkdir(parents=True, exist_ok=True)
    (bd / "MASTER-PLAN.md").write_text(
        "# Master Plan\n\n## North Star\n"
        "Make the surface a truthful memory of trio work.\n\n"
        "## Key decisions\n"
        "Cache validated summaries for each session.\n", encoding="utf-8")
    pid = gui.select_existing_project("EndpointProj", str(folder))["entry"]["id"]

    import effort_history as eh
    import brownfield_scan
    eh = importlib.reload(eh)
    scan = brownfield_scan.scan(str(folder))
    eh.adopt_discovered(folder, pid, scan)

    import sessions as sess
    sess = importlib.reload(sess)
    sess_list = sess.list_sessions(folder, pid, "planning")
    session = next(s for s in sess_list
                   if any("brownfield-discovery" in m.get("artifact_path", "")
                          for m in s.get("member_files", [])))
    sid = session["session_id"]

    # Pre-generate + cache the summary (run-once, through the stub seam).
    summarizer.summarize_session(folder, pid, "planning", session)

    server = gui.make_server("127.0.0.1", 0)
    port = server.server_address[1]
    t = _threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        from urllib.parse import quote as _q
        url = (f"http://127.0.0.1:{port}/api/rnd/session_summary?"
               f"pid={_q(pid)}&lane=planning&session={_q(sid)}")
        with _urlreq.urlopen(url, timeout=10) as r:
            data = _json.loads(r.read().decode("utf-8"))
        assert data["ok"] is True
        assert data["status"] == "ready"
        summ = data["summary"]
        # Cached structured summary carries the Wave-6 fields.
        assert "when_run" in summ
        assert "north_star" in summ
        assert "effort" in summ
        # Imported session → effort honestly null.
        assert summ["effort"] is None
        assert "validated summaries" in " ".join(summ.get("claims", [])).lower()
    finally:
        server.shutdown()
        server.server_close()

    # Reset the live job table so leaked runner state can't bleed across tests.
    try:
        job_runner._reset_live_table_for_tests()
    except Exception:
        pass


def test_session_summary_endpoint_generating_fallback(gui, tmp_path,
                                                      monkeypatch):
    """When NOT cached, the endpoint returns {status:'generating'} (it must NOT
    block on a synchronous model run)."""
    import json as _json
    import threading as _threading
    import urllib.request as _urlreq

    folder = tmp_path / "P"
    folder.mkdir()
    pid = gui.select_existing_project("GenProj", str(folder))["entry"]["id"]
    _discovered_planning_session(gui, folder, pid)
    import sessions as sess
    sess_list = sess.list_sessions(str(folder), pid, "plan")
    sid = sess_list[0]["session_id"]

    server = gui.make_server("127.0.0.1", 0)
    port = server.server_address[1]
    t = _threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        from urllib.parse import quote as _q
        url = (f"http://127.0.0.1:{port}/api/rnd/session_summary?"
               f"pid={_q(pid)}&lane=planning&session={_q(sid)}")
        with _urlreq.urlopen(url, timeout=10) as r:
            data = _json.loads(r.read().decode("utf-8"))
        # Proactive generation is OFF in unit tests, so an uncached summary
        # returns the 'generating' fallback WITHOUT blocking on a model run.
        assert data["ok"] is True
        assert data["status"] == "generating"
    finally:
        server.shutdown()
        server.server_close()


def test_session_summary_endpoint_unknown_session_is_terminal(gui, tmp_path,
                                                              monkeypatch):
    """FIX 3: an UNKNOWN session id (or an unregistered pid) returns a TERMINAL
    status (status='unknown'), NOT an endless {status:'generating'} — so a
    polling UI panel STOPS instead of spinning forever."""
    import json as _json
    import threading as _threading
    import urllib.request as _urlreq

    folder = tmp_path / "P"
    folder.mkdir()
    pid = gui.select_existing_project("UnkProj", str(folder))["entry"]["id"]
    # A real session exists, but we ask for a DIFFERENT (non-existent) session id.
    _discovered_planning_session(gui, folder, pid)

    server = gui.make_server("127.0.0.1", 0)
    port = server.server_address[1]
    t = _threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        from urllib.parse import quote as _q
        # (a) Known project, MISSING session id → terminal 'unknown'.
        url = (f"http://127.0.0.1:{port}/api/rnd/session_summary?"
               f"pid={_q(pid)}&lane=planning&session={_q('no::such::session')}")
        with _urlreq.urlopen(url, timeout=10) as r:
            data = _json.loads(r.read().decode("utf-8"))
        assert data["status"] == "unknown", (
            "missing session must be terminal, not endless 'generating'")
        assert data["status"] != "generating"

        # (b) UNKNOWN (unregistered) project id → terminal 'unknown'.
        url2 = (f"http://127.0.0.1:{port}/api/rnd/session_summary?"
                f"pid={_q('no-such-pid')}&lane=planning&session={_q('whatever')}")
        with _urlreq.urlopen(url2, timeout=10) as r:
            data2 = _json.loads(r.read().decode("utf-8"))
        assert data2["status"] == "unknown"
        assert data2["status"] != "generating"
    finally:
        server.shutdown()
        server.server_close()


def test_session_summary_endpoint_rejects_traversal_pid(gui, tmp_path):
    """FIX 2: a traversal pid is rejected with 400 (symmetric with the existing
    lane guard) before it can reach load_cached's path interpolation."""
    import json as _json
    import threading as _threading
    import urllib.request as _urlreq
    import urllib.error as _urlerr

    server = gui.make_server("127.0.0.1", 0)
    port = server.server_address[1]
    t = _threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        from urllib.parse import quote as _q
        url = (f"http://127.0.0.1:{port}/api/rnd/session_summary?"
               f"pid={_q('../../etc')}&lane=planning&session={_q('s')}")
        try:
            with _urlreq.urlopen(url, timeout=10) as r:
                code = r.getcode()
                body = _json.loads(r.read().decode("utf-8"))
        except _urlerr.HTTPError as e:
            code = e.code
            body = _json.loads(e.read().decode("utf-8"))
        assert code == 400
        assert body["ok"] is False
        assert body["error"] == "bad pid"
    finally:
        server.shutdown()
        server.server_close()


# ── Wave 7 (v3) — build-launch offer→confirm wiring ──────────────────────────

def test_build_launch_offers_handoff_proposal_with_confirm(gui, tmp_path):
    """FIX 3: when launching a BUILD lane, newTermSession first fetches
    /api/rnd/handoff_proposal and, if has_plan_set, shows a confirm() before
    priming. Non-build lanes skip the proposal."""
    folder = tmp_path / "P"
    folder.mkdir()
    pid = gui.select_existing_project("HandoffUI", str(folder))["entry"]["id"]
    html = gui.render_project_window_html(pid)
    # The build-launch path references the proposal endpoint and a confirm gate.
    assert "/api/rnd/handoff_proposal" in html
    assert "has_plan_set" in html
    assert "Execute on this plan set?" in html
    # The proposal is only consulted for the build lane.
    assert "lane === 'build'" in html
    # Brace hygiene preserved (JS lives in the RAW string).
    assert "{{" not in html
    assert "}}" not in html


def test_linked_task_with_quote_and_apostrophe_roundtrips(gui, tmp_path):
    """Regression (Wave 4 fix): a task whose text contains BOTH an apostrophe
    AND a double-quote (e.g. ``Fix it's "weird" bug``) must (a) render in the
    strip with its text HTML-escaped and the identity carried in data-
    attributes — NOT as an inline JS string literal — and (b) round-trip
    cleanly through the link/unlink backend that the endpoint calls."""
    import html as html_lib

    folder = tmp_path / "P"
    folder.mkdir()
    pid = gui.select_existing_project("Tricky", str(folder))["entry"]["id"]

    task_text = 'Fix it\'s "weird" bug'

    # Write the task into a domain file already linked to this project.
    gui.DOMAINS_DIR.mkdir(parents=True, exist_ok=True)
    (gui.DOMAINS_DIR / "academic.md").write_text(
        f"- [ ] {task_text} — Priority: 2 — energy: med — [academic] "
        f"— Project: {pid}\n",
        encoding="utf-8",
    )

    # (a) Render: text appears HTML-escaped and rides in a data- attribute.
    html = gui.render_project_tasks_html(pid)
    # The Unlink button reads identity from the DOM (no inline string arg).
    assert "rndUnlinkTask(this)" in html
    # No inline onclick smuggles the raw breaking chars as a JS string arg.
    assert "rndUnlinkTask('" not in html
    assert f"rndUnlinkTask(\"{task_text}" not in html
    # The raw text travels via a data-task attribute, HTML-escaped.
    esc = html_lib.escape(task_text, quote=True)
    assert f'data-task="{esc}"' in html
    # Quotes/apostrophes are escaped in display — no raw breaking chars leak
    # into an attribute or inline string.
    assert "data-task=\"Fix it's" not in html  # apostrophe must be escaped

    # (b) Backend round-trip via the SAME function the endpoint calls.
    #   Already linked from the markdown above:
    assert any(t.get("text", "") == task_text for t in gui.project_tasks(pid))
    #   Unlink with the RAW (entity-decoded) text → empty project_id.
    assert gui.link_task(task_text, "") is True
    assert not any(t.get("text", "") == task_text for t in gui.project_tasks(pid))
    #   Re-link the same tricky text → it comes back.
    assert gui.link_task(task_text, pid) is True
    assert any(t.get("text", "") == task_text for t in gui.project_tasks(pid))
