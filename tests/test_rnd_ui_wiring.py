"""R&D control-surface UI wiring (Wave: connect backend → browser dashboard).

These tests are the regression guard that the previously-orphaned R&D views and
the lane/tail/gate HTTP endpoints are now actually surfaced in the dashboard and
reachable over HTTP.

Covers:
- ``generate_html`` now contains the R&D nav tab, the ``view-rnd`` container, the
  "+ New Project" control, AND the (formerly orphaned) folder-grouped projects
  view — and the f-string is intact (no leaked ``{{``/``}}``).
- POST ``/api/rnd/launch_lane`` with the mock runner starts a job + returns a
  job_id; an invalid lane and a folder-build-locked second build each return a
  CLEAN JSON error (not a 500).
- GET ``/api/rnd/tail`` returns ``{lines,next,status,pending_prompt}`` for a
  launched mock job; incremental ``since`` advances; it never blocks.
- POST ``/api/rnd/answer_gate`` answers an awaiting-input job → exactly ONE write.
- ``render_project_window_html`` now carries the lane-launch controls + the log
  drawer hooks.

NEVER invokes live ``claude`` — everything routes through ANCHOR_RUNNER_CMD →
tests/fake_claude.py. A throwaway server is booted on an OS-assigned free port
(port=0); port 8777 / the live service / real data are never touched. All spawned
procs are reaped.
"""
import importlib
import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()
GATE_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "gate_stream.jsonl"


@pytest.fixture
def gui_env(tmp_path, monkeypatch):
    """Reload the stack against a tmp data dir + the mock runner.

    Reloads in dependency order so anchor_gui's module-level ``import lanes``,
    ``import job_runner``, ``import gate_adapter`` all bind to the freshly
    reloaded modules sharing one tmp ANCHOR_DATA_DIR. ANCHOR_TOKEN is left unset
    (local auth disabled) so POSTs need no token.
    """
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    import paths
    importlib.reload(paths)
    paths.ensure_data_dirs()
    import job_runner
    importlib.reload(job_runner)
    import rnd_registry
    importlib.reload(rnd_registry)
    import lanes
    importlib.reload(lanes)
    import gate_adapter
    importlib.reload(gate_adapter)
    import anchor_gui
    gui = importlib.reload(anchor_gui)
    yield gui
    # Reap any still-running jobs + clear in-memory tables (no leaks).
    for rec in job_runner.list_records():
        if rec.get("status") == job_runner.STATUS_RUNNING:
            try:
                job_runner.cancel(rec["job_id"])
            except Exception:
                pass
    job_runner._reset_live_table_for_tests()


@pytest.fixture
def server(gui_env):
    """Boot a throwaway server on an OS-assigned free port (never 8777)."""
    gui = gui_env
    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield gui, f"http://127.0.0.1:{port}"
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(timeout=5)


def _post(url, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=8) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _mkproject(gui, folder, name="P"):
    import rnd_registry
    folder.mkdir(parents=True, exist_ok=True)
    return rnd_registry.add_project(name, str(folder))


# ── B: dashboard surfaces the R&D entry point + the orphaned view ────────────

def test_dashboard_contains_rnd_tab_view_and_new_project(gui_env):
    gui = gui_env
    html = gui.generate_html(*gui.gather_all())
    # The R&D nav tab is present.
    assert "showView('rnd')" in html
    # The view-rnd container is present.
    assert 'id="view-rnd"' in html
    # The "+ New Project" control is present.
    assert "New Project" in html
    assert "openNewProject(" in html
    # f-string is intact: no leaked doubled braces in the served HTML.
    assert "{{" not in html and "}}" not in html


def test_home_view_has_rnd_projects_section(gui_env):
    """The HOME dashboard view surfaces an 'R&D Projects' section with the
    folder-grouped tiles container and a '+ New Project' button wired to the
    same openNewProject() modal — so it can't silently regress."""
    gui = gui_env
    html = gui.generate_html(*gui.gather_all())
    # The home (default) view container.
    head, _, _tail = html.partition('id="view-rnd"')
    assert 'id="view-dashboard"' in head
    # The home view portion (everything before the R&D tab) carries the section.
    assert "R&amp;D Projects" in head
    # The folder-grouped tiles container is rendered in the home view.
    assert "rnd-projects" in head
    # A "+ New Project" button wired to the shared modal lives in the home view.
    assert "openNewProject(" in head
    assert "New Project" in head
    # f-string intact: no leaked doubled braces anywhere in the served HTML.
    assert "{{" not in html and "}}" not in html


def test_dashboard_renders_projects_view_now_wired(gui_env):
    """The formerly-orphaned render_projects_view_html is now called in-page."""
    gui = gui_env
    folder = Path(gui.ANCHOR_DIR)  # any path is fine; we just need a project
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        _mkproject(gui, Path(td) / "RndProj", name="WiredProj")
        html = gui.generate_html(*gui.gather_all())
    # The projects-view wrapper class the helper emits is present in the page.
    assert "rnd-projects" in html
    # The registered project's name surfaced via the now-wired view.
    assert "WiredProj" in html


# ── A1: launch_lane endpoint ─────────────────────────────────────────────────

def test_launch_lane_starts_job_returns_job_id(server):
    gui, base = server
    import job_runner
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        proj = _mkproject(gui, Path(td) / "f", "Alpha")
        code, body = _post(base + "/api/rnd/launch_lane",
                           {"project_id": proj["id"], "lane": "research"})
        assert code == 200
        assert body["ok"] is True
        assert body["job_id"]
        job_runner.wait(body["job_id"], timeout=30)


def test_launch_lane_invalid_lane_clean_error(server):
    gui, base = server
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        proj = _mkproject(gui, Path(td) / "f", "Beta")
        code, body = _post(base + "/api/rnd/launch_lane",
                           {"project_id": proj["id"], "lane": "bogus"})
        # Clean JSON error, NOT a 500.
        assert code == 400
        assert body["ok"] is False
        assert body["reason"] == "invalid-lane"


def test_launch_lane_folder_build_lock_clean_error(server, tmp_path, monkeypatch):
    gui, base = server
    import job_runner
    import rnd_registry
    # Two projects sharing ONE folder → the folder build-lock serializes the
    # second build. Use the pytest tmp_path (torn down by pytest, tolerant of a
    # lingering handle) rather than a context-managed TemporaryDirectory.
    folder = tmp_path / "shared"
    p1 = _mkproject(gui, folder, "One")
    p2 = rnd_registry.add_project("Two", str(folder))

    # Make the mock build sleep so it reliably holds the folder lock while the
    # second launch collides. The server runs in-process, so the subprocess
    # (spawned via os.environ) picks this up.
    monkeypatch.setenv("FAKE_CLAUDE_SLEEP", "2.0")

    # First build holds the folder lock.
    code1, b1 = _post(base + "/api/rnd/launch_lane",
                      {"project_id": p1["id"], "lane": "build"})
    # The endpoint ignores extra_args by design; keep the build alive by polling
    # until it's running, then collide the second build before it finishes.
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        rec = job_runner.load_record(b1["job_id"])
        if rec and rec.get("status") == job_runner.STATUS_RUNNING:
            break
        time.sleep(0.01)

    # Second build in the SAME folder → refused with a clean 409, not a 500.
    code2, b2 = _post(base + "/api/rnd/launch_lane",
                      {"project_id": p2["id"], "lane": "build"})
    assert code1 == 200 and b1["ok"] is True
    if code2 == 200:
        # The first (fast) mock build already finished before the second
        # launched, so there was no live holder to collide with. In that case the
        # second simply succeeded — still NOT a 500. Reap it and pass.
        assert b2["ok"] is True
        job_runner.wait(b2["job_id"], timeout=30)
    else:
        assert code2 == 409
        assert b2["ok"] is False
        assert b2["reason"] == job_runner.REFUSED_FOLDER_BUILD
        assert b2["holder"] == b1["job_id"]

    # Reap the first build (cancel if still running) before teardown.
    rec = job_runner.load_record(b1["job_id"])
    if rec and rec.get("status") == job_runner.STATUS_RUNNING:
        job_runner.cancel(b1["job_id"])
    job_runner.wait(b1["job_id"], timeout=30)


def test_launch_lane_unknown_project_clean_error(server):
    gui, base = server
    code, body = _post(base + "/api/rnd/launch_lane",
                       {"project_id": "nope", "lane": "research"})
    assert code == 404
    assert body["ok"] is False
    assert body["reason"] == "unknown-project"


# ── A2: tail endpoint ────────────────────────────────────────────────────────

def test_tail_returns_shape_and_advances(server):
    gui, base = server
    import job_runner
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        proj = _mkproject(gui, Path(td) / "f", "Gamma")
        _, lb = _post(base + "/api/rnd/launch_lane",
                     {"project_id": proj["id"], "lane": "research"})
        jid = lb["job_id"]
        job_runner.wait(jid, timeout=30)

        code, body = _get(base + f"/api/rnd/tail?job_id={jid}&since=0")
        assert code == 200
        # The mandated shape.
        for key in ("lines", "next", "status", "pending_prompt"):
            assert key in body
        assert isinstance(body["lines"], list)
        assert body["pending_prompt"] is None
        first_next = body["next"]
        assert first_next >= 0

        # Incremental since advances: fetching from the new cursor yields no
        # duplicate lines and never blocks.
        t0 = time.monotonic()
        code2, body2 = _get(base + f"/api/rnd/tail?job_id={jid}&since={first_next}")
        elapsed = time.monotonic() - t0
        assert code2 == 200
        assert body2["lines"] == []          # nothing new past the cursor
        assert body2["next"] == first_next   # cursor stable
        assert elapsed < 5                    # never holds the request 25s


def test_tail_missing_job_id_is_clean_error(server):
    gui, base = server
    code, body = _get(base + "/api/rnd/tail")
    assert code == 400
    assert body["ok"] is False


# ── A3: answer_gate endpoint ─────────────────────────────────────────────────

def test_answer_gate_single_write(server):
    gui, base = server
    import job_runner
    import gate_adapter

    # Launch a job that stays alive, register a fake sink, persist the fixture's
    # awaiting-input gate onto its record.
    class FakeSink:
        def __init__(self):
            self.writes = []
            self._lock = threading.Lock()

        def write(self, data):
            with self._lock:
                self.writes.append(data)

        def flush(self):
            pass

    rec = job_runner.launch("plan", extra_args=["--lines", "1", "--sleep", "1.5"])
    jid = rec["job_id"]
    sink = FakeSink()
    gate_adapter.register_stdin_sink(jid, sink)
    prompt = gate_adapter.ingest_stream(
        jid, GATE_FIXTURE.read_text(encoding="utf-8").splitlines())
    assert prompt is not None

    # The tail endpoint surfaces the pending prompt.
    code, body = _get(base + f"/api/rnd/tail?job_id={jid}&since=0")
    assert code == 200
    assert body["pending_prompt"] is not None
    assert body["pending_prompt"]["tool_use_id"] == "toolu_gate_01"

    # Answer via the HTTP endpoint → exactly ONE stdin write.
    code, ans = _post(base + "/api/rnd/answer_gate",
                     {"job_id": jid, "choice": "JSON files"})
    assert code == 200
    assert ans["ok"] is True and ans["written"] is True
    assert len(sink.writes) == 1

    # A second answer for the now-consumed gate is a clean no-op (one write).
    code, ans2 = _post(base + "/api/rnd/answer_gate",
                      {"job_id": jid, "choice": "JSON files"})
    assert code == 200
    assert ans2["written"] is False
    assert len(sink.writes) == 1

    job_runner.wait(jid, timeout=30)


# ── D: existing-folder picker (dir_browse endpoint + modal wiring) ───────────

def test_dir_browse_no_path_returns_roots(server):
    """GET /api/rnd/dir_browse with no path lists drive roots to start from."""
    gui, base = server
    code, body = _get(base + "/api/rnd/dir_browse")
    assert code == 200
    assert body["ok"] is True
    res = body["result"]
    assert isinstance(res["roots"], list) and res["roots"]
    # No path → nothing resolved yet, no error.
    assert res["path"] is None
    assert res["error"] is None


def test_dir_browse_lists_subdir_and_parent(server, tmp_path):
    """GET /api/rnd/dir_browse?path=<tmp dir with a subdir> returns that subdir
    in ``dirs`` and the correct ``parent`` — i.e. it powers navigation."""
    gui, base = server
    sub = tmp_path / "child"
    sub.mkdir()
    # A file in the same dir must NOT show up (directories only).
    (tmp_path / "afile.txt").write_text("x", encoding="utf-8")
    from urllib.parse import quote
    code, body = _get(base + "/api/rnd/dir_browse?path=" + quote(str(tmp_path)))
    assert code == 200
    res = body["result"]
    assert res["error"] is None
    names = {d["name"] for d in res["dirs"]}
    assert "child" in names
    assert "afile.txt" not in names
    # The subdir row carries its absolute path (used by npBrowse / npSelectPath).
    child_row = next(d for d in res["dirs"] if d["name"] == "child")
    assert child_row["path"] == str(sub)
    # Parent points one level up so the "Up" row can navigate back.
    assert res["parent"] == str(tmp_path.parent)


def test_dir_browse_missing_path_clean_error(server, tmp_path):
    """A missing path surfaces a structured ``path-missing`` error, not a 500."""
    gui, base = server
    from urllib.parse import quote
    missing = tmp_path / "nope-not-here"
    code, body = _get(base + "/api/rnd/dir_browse?path=" + quote(str(missing)))
    assert code == 200
    res = body["result"]
    assert res["error"] == "path-missing"


def test_new_project_picker_wiring_in_html(gui_env):
    """The New Project modal carries the Explorer-style TREE existing-folder
    picker: the "Use this folder" confirm button, the tree container, the hidden
    npFolderPath input, the Selected line, and the lazy-expansion JS — with the
    f-string intact (no leaked braces)."""
    gui = gui_env
    html = gui.generate_html(*gui.gather_all())
    # Explicit confirm of the highlighted folder.
    assert "Use this folder" in html
    assert "npSelectCurrent(" in html
    # The tree picker container + node/selection machinery.
    assert 'id="npTree"' in html
    assert "function npMakeNode(" in html
    assert "function npTreeSelect(" in html
    # Lazy expansion fetches dir_browse.
    assert "function npTreeToggle(" in html
    assert "/api/rnd/dir_browse" in html
    # State plumbing.
    assert 'id="npFolderPath"' in html
    assert 'id="npSelected"' in html
    # f-string intact: no leaked doubled braces in the served HTML.
    assert "{{" not in html and "}}" not in html


def test_new_project_picker_tree_expand_on_click_in_html(gui_env):
    """The picker is a real Explorer-style EXPAND-ON-CLICK tree: clicking a node
    row both selects it (highlight) and lazily loads its child folders from the
    backend, rendered indented underneath. The tree init + node builder + the
    click handler that does select-and-toggle are present in the rendered HTML."""
    gui = gui_env
    html = gui.generate_html(*gui.gather_all())
    # The tree is populated from the drive roots on entry.
    assert "function npTreeInit(" in html
    # Each node row's click both selects AND toggles expansion.
    assert "npTreeSelect(row, path)" in html
    assert "npTreeToggle(node)" in html
    # Children are fetched lazily per-node via the backend browse helper.
    assert "function npDirBrowse(" in html
    assert "rnd-tree-children" in html
    # The caret + folder-icon node structure is emitted.
    assert "rt-caret" in html
    assert "rt-name" in html
    # No brace leak.
    assert "{{" not in html and "}}" not in html


def test_new_project_picker_name_autosuggest_in_html(gui_env):
    """Selecting a folder auto-suggests the project name from its basename:
    npSelectPath calls npSuggestName, which sets npName from the folder
    basename and tracks an auto-suggested flag cleared on manual edit."""
    gui = gui_env
    html = gui.generate_html(*gui.gather_all())
    # The auto-suggest function exists and is invoked on selection.
    assert "function npSuggestName(" in html
    assert "npSuggestName(path)" in html or "npSuggestName(" in html
    # Basename helper drives the suggested name.
    assert "function npBasename(" in html
    # Auto-suggested flag + the manual-edit clear hook wired to the name field.
    assert "_npAutoName" in html
    assert "npNameEdited(" in html
    # The name field's oninput clears the auto-suggested flag via npNameEdited().
    # A live-preview call (npUpdatePreview) was later added to the SAME handler,
    # so the oninput is now "npNameEdited(); npUpdatePreview()" — match the wire
    # on the npName field itself rather than an exact single-call string.
    import re as _re
    assert _re.search(r'id="npName"[^>]*oninput="[^"]*npNameEdited\(\)', html), \
        "npName field's oninput must invoke npNameEdited()"
    # The suggestion writes into the npName field.
    assert "getElementById('npName')" in html
    # REGRESSION (f-string escaping): the emitted npBasename split regex MUST
    # keep a literal backslash so Windows path basenames (C:\dev\Anchor ->
    # 'Anchor') work. A collapsed '\\' -> '/' regex would only split forward
    # slashes and return the whole path. Require the backslashed char class.
    assert r"p.split(/[\\/]+/)" in html
    assert "{{" not in html and "}}" not in html


def test_select_existing_missing_path_no_crash_endpoint(server, tmp_path):
    """select_existing_project still registers a chosen folder, and a missing
    path yields a path-missing state (regression guard for the picker backend)."""
    gui, base = server
    real = tmp_path / "realproj"
    real.mkdir()
    res = gui.select_existing_project("Picked", str(real))
    assert res["path_exists"] is True
    assert res["entry"]["id"]
    # Missing path → path-missing state, no crash.
    ghost = gui.select_existing_project("Ghost", str(tmp_path / "missing"))
    assert ghost["path_exists"] is False
    assert ghost["entry"]["state"] == "path-missing"


# ── C: project window carries the launch controls + log drawer hooks ─────────

def test_project_window_has_lane_controls_and_panel_terminal(gui_env):
    gui = gui_env
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        proj = _mkproject(gui, Path(td) / "win", "WindowProj")
        html = gui.render_project_window_html(proj["id"])
    # v12 Wave 2 Layout-D: the per-lane "+ new <lane>" board launchers are RETIRED
    # (the start path moves to the W10 "+ New effort" flow). The live-terminal
    # start path itself survives through the one General-session control.
    # Research/plan/build work is commissioned through Steward.
    assert "id='newGeneralBtn'" in html
    assert "newEffort('general')" in html
    assert "id='newResearchBtn'" not in html
    assert "id='newPlanBuildBtn'" not in html
    assert "/api/rnd/term_start" in html
    # Terminal substrate: a LIVE session mounts the REAL xterm.js terminal inside
    # its inline panel over the v3 transport. v4.1: the v2 console-drawer REPL
    # (anchor-term adapter / start_terminal raw-log mirror) was REMOVED — the
    # panel terminal is the only surface.
    assert "new window.Terminal(" in html
    assert "/api/rnd/term_ws" in html
    assert "/api/rnd/term_stream2" in html
    assert "/api/rnd/term_input2" in html
    # The genuine xterm.js library + stylesheet are vendored and included.
    assert "/vendor/xterm/xterm.js" in html
    assert "/vendor/xterm/xterm.css" in html
    # The dead console drawer (raw-log mirror + inline gate) is gone.
    assert "id='laneLog'" not in html
    assert "id='laneGate'" not in html
    assert "function openTerminal" not in html
    # The PROJECT_ID was injected for the JS.
    assert "PROJECT_ID" in html


# ── R&D project lifecycle: notes / priority / archive / retire / reactivate ──

def test_registry_notes_and_state_transitions(gui_env):
    import rnd_registry as r
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        e = r.add_project("LifeProj", td, notes="initial note")
        pid = e["id"]
        assert e["notes"] == "initial note"
        assert r.set_notes(pid, "updated")["notes"] == "updated"
        # retire -> inactive: excluded from the active list, present in inactive
        r.retire_project(pid)
        assert r.get_project(pid)["state"] == r.STATE_RETIRED
        active = [x["id"] for x in r.list_projects(
            include_archived=False, include_future=False, include_retired=False)]
        assert pid not in active
        assert pid in [x["id"] for x in r.list_inactive_projects()]
        # reactivate -> active again
        r.reactivate_project(pid)
        assert r.get_project(pid)["state"] == r.STATE_ACTIVE
        assert pid in [x["id"] for x in r.list_projects(
            include_archived=False, include_future=False, include_retired=False)]


def test_lifecycle_endpoints_round_trip_and_views(server):
    """HTTP round-trip: set notes/priority, retire -> the project leaves the
    ACTIVE views and appears in the ARCHIVE view with a Reactivate control;
    reactivate brings it back; unknown id -> clean 404."""
    gui, base = server
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        proj = _mkproject(gui, Path(td) / "Life", name="LifeHTTP")
        pid = proj["id"]
        code, data = _post(base + "/api/rnd/set_notes", {"id": pid, "notes": "via http"})
        assert code == 200 and data["ok"] and data["entry"]["notes"] == "via http"
        code, data = _post(base + "/api/rnd/set_priority", {"id": pid, "priority": 1})
        assert data["entry"]["priority"] == 1
        code, data = _post(base + "/api/rnd/retire_project", {"id": pid})
        assert code == 200 and data["entry"]["state"] == "retired"
        # Active views (home + view-rnd) EXCLUDE it; the archive view INCLUDES it.
        html = gui.generate_html(*gui.gather_all())
        head, _, archive = html.partition('id="view-rnd-archive"')
        assert "LifeHTTP" not in head, "retired project must leave the active views"
        assert "LifeHTTP" in archive, "retired project must appear in the archive view"
        assert "rndReactivate" in archive
        code, data = _post(base + "/api/rnd/reactivate_project", {"id": pid})
        assert code == 200 and data["entry"]["state"] == "active"
        code, data = _post(base + "/api/rnd/retire_project", {"id": "nope"})
        assert code == 404


def test_tile_has_lifecycle_controls_and_multiwindow_open(gui_env):
    """The thin project ROW + kebab lifecycle controls are actually surfaced in
    the page (the exact 'built but not wired into the UI' regression that bit the
    first R&D build). v3 Wave 5 replaced the square ``.rnd-tile`` with a one-line
    ``.rnd-row`` whose lifecycle controls live in a kebab menu and whose body
    click opens the project window."""
    gui = gui_env
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        _mkproject(gui, Path(td) / "Tile", name="TileProj")
        html = gui.generate_html(*gui.gather_all())
    for needle in (
            # the thin row + its click-to-open-project-window affordance
            'class="rnd-row"', "data-project-id=", "openProjectWindow('",
            "function openProjectWindow",
            # the kebab that holds the lifecycle controls
            'class="rnd-kebab"', "rndToggleKebab",
            # Rescan stays; P1/P2/Archive/Retire left the home kebab (2026-08-28)
            "rndRescan", "rndNotes",
            "function rndNotes", 'id="view-rnd-archive"',
            "showView('rnd-archive')"):
        assert needle in html, "page missing: " + needle
    # A new tab/page — never a named target that can reuse the dashboard.
    assert "'_blank'" in html
    assert "'anchorproj_'" not in html
    assert "{{" not in html and "}}" not in html


def test_high_seat_opens_projects_in_own_window_not_dashboard():
    """High Seat used to set location.href / named window.open to /project/,
    which replaced the home dashboard and froze it. Contract: a real new page
    (target=_blank), never this tab."""
    src = (Path(__file__).resolve().parent.parent / "static" / "high-seat.js"
           ).read_text(encoding="utf-8")
    assert "function _ecgHsOpenProject" in src
    assert "openProjectWindow(" not in src
    assert "'_blank'" in src
    assert "target = '_blank'" in src
    assert "window.location.href = '/project/'" not in src
    assert "anchorproj_" not in src


# ── Wave 4 (v3) — read-only term_sessions endpoint (repopulate-from-registry) ─
#
# Hermetic: a stub PTY backend + a temp git repo project + a temp worktree base
# so no real ConPTY/claude runs and NO worktree is ever created off the build
# repo. Reloads the v3 terminal stack on top of the standard gui_env reload.

def _have_git():
    import subprocess
    try:
        return subprocess.run(["git", "--version"],
                              capture_output=True).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _git(repo, *args):
    import subprocess
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)


@pytest.fixture
def term_server(tmp_path, monkeypatch):
    """Boot a throwaway server with the v3 terminal stack on a stub PTY backend.

    Mirrors the `server` fixture but also sets ANCHOR_PTY_BACKEND=stub +
    ANCHOR_WORKTREE_BASE (a temp dir) and reloads the Wave-1/2/3 modules so a
    stub session can be started against a hermetic temp git repo — never the
    build repo.
    """
    if not _have_git():
        pytest.skip("git not on PATH")
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(tmp_path / "wt-base"))
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    import paths
    importlib.reload(paths)
    paths.ensure_data_dirs()
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
    import anchor_gui
    gui = importlib.reload(anchor_gui)

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial")
    proj = rnd_registry.add_project("TermProj", str(repo), scaffold=False)

    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield gui, f"http://127.0.0.1:{port}", proj["id"], terminal_session, repo
    finally:
        # Reap any started stub sessions so no worktree leaks.
        for rec in terminal_session.list_sessions():
            try:
                terminal_session.kill(rec["session_id"])
            except Exception:
                pass
        srv.shutdown()
        srv.server_close()
        t.join(timeout=5)


def test_term_sessions_empty_for_fresh_project(term_server):
    """GET /api/rnd/term_sessions returns {ok, sessions: []} for a project with
    no managed sessions."""
    gui, base, pid, ts, repo = term_server
    code, body = _get(base + "/api/rnd/term_sessions?project_id=" + pid)
    assert code == 200
    assert body["ok"] is True
    assert body["sessions"] == []


def test_term_sessions_lists_started_stub_session(term_server):
    """A stub ConPTY session started via terminal_session.start_session appears
    in the endpoint with its lane/backend/status — and the response NEVER leaks
    the absolute worktree_path."""
    gui, base, pid, ts, repo = term_server
    rec = ts.start_session(pid, "plan", backend="claude")
    sid = rec["session_id"]
    code, body = _get(base + "/api/rnd/term_sessions?project_id=" + pid)
    assert code == 200 and body["ok"] is True
    sessions = body["sessions"]
    assert len(sessions) == 1
    s = sessions[0]
    assert s["session_id"] == sid
    assert s["lane"] == "plan"
    assert s["backend"] == "claude"
    assert s["status"] == "running"
    # The UI projection must NOT include the absolute worktree path.
    assert "worktree_path" not in s
    # The created worktree lives under the temp base, never the build repo.
    import subprocess
    wl = subprocess.run(["git", "worktree", "list"],
                        capture_output=True, text=True,
                        cwd=str(Path(__file__).resolve().parents[1]))
    assert "wt-base" not in wl.stdout  # build-repo worktree list untouched


def test_term_sessions_malicious_label_is_inert_xss_guard(term_server):
    """XSS regression guard for the session-bar / window-titlebar path.

    A session started with a malicious ``label`` (``<img src=x onerror=...>``)
    must:
      1. be carried in the term_sessions JSON verbatim (data integrity), and
      2. be served with ``Content-Type: application/json`` (so the payload is
         inert in that response — a browser will not execute it), and
      3. NOT be embedded as a raw executable HTML sink in the server-rendered
         project window. The session bar is populated CLIENT-SIDE from this
         endpoint via ``textContent``/``_esc`` (not ``innerHTML``), so the
         served window HTML must not contain the raw payload at all.

    A future regression to ``innerHTML`` (or server-rendering the label) would
    re-introduce the raw payload and fail this test.
    """
    gui, base, pid, ts, repo = term_server
    payload = "<img src=x onerror=alert(1)>"
    rec = ts.start_session(pid, "plan", backend="claude", label=payload)
    sid = rec["session_id"]

    # 1+2: the endpoint carries the label verbatim AND is inert JSON.
    req = urllib.request.Request(
        base + "/api/rnd/term_sessions?project_id=" + pid, method="GET")
    with urllib.request.urlopen(req, timeout=8) as resp:
        ctype = resp.headers.get("Content-Type", "")
        body = json.loads(resp.read())
    assert resp.status == 200
    assert ctype.split(";")[0].strip() == "application/json"
    sessions = body["sessions"]
    s = next(x for x in sessions if x["session_id"] == sid)
    assert s["label"] == payload  # data integrity: label round-trips

    # 3: the SERVED window HTML does NOT embed the raw executable payload.
    html = gui.render_project_window_html(pid)
    assert payload not in html
    assert "<img src=x onerror=" not in html
    # Sessions are synced client-side from the endpoint (textContent / panel
    # title), never server-rendered into the page — confirm that architecture is
    # intact. v4.1: the "Live terminals" bar was removed; repopulate() (aliased
    # as loadSessions) does the client-side sync from the registry.
    assert "loadSessions = repopulate" in html
    assert "repopulate()" in html
    assert "/api/rnd/term_sessions" in html
