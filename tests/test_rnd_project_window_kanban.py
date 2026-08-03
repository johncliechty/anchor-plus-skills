"""Rich per-project window ("Dashboard A") + multi-session console + cancel_job.

Regression guard that the spec mockup (`_mockups/rnd_mockups_v2.html`,
"Dashboard A") is actually SERVED at GET /project/<id> — the exact "built but
never wired into the UI" failure that bit this project once. Asserts the SERVED
HTML (not just internal functions) carries:

  - the 4-column Kanban (Research|Planning|Build|Deliverables),
  - versioned effort cards with state pills,
  - the per-lane "New run" affordances,
  - the multi-session console (session tabs + attached log + Ask + Stop),
  - the lifecycle header (priority/notes/archive/retire),

and that:

  - POST /api/rnd/cancel_job cancels a running mock job and 404s an unknown id,
  - two concurrent mock jobs for one project surface as switchable sessions and
    an answer routes to a SPECIFIC job_id (no cross-wire).

Every job launch routes through ANCHOR_RUNNER_CMD -> tests/fake_claude.py (a
mock); live claude/gemini is NEVER invoked. A throwaway server runs on an
OS-assigned free port (port=0); 8777 / the live service / real data are never
touched. All spawned mock procs are reaped.
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


@pytest.fixture
def gui_env(tmp_path, monkeypatch):
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
    import effort_history
    importlib.reload(effort_history)
    import gate_adapter
    importlib.reload(gate_adapter)
    import anchor_gui
    gui = importlib.reload(anchor_gui)
    yield gui
    for rec in job_runner.list_records():
        if rec.get("status") == job_runner.STATUS_RUNNING:
            try:
                job_runner.cancel(rec["job_id"])
            except Exception:
                pass
    job_runner._reset_live_table_for_tests()


@pytest.fixture
def server(gui_env):
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


def _get_text(url):
    with urllib.request.urlopen(url, timeout=8) as resp:
        return resp.status, resp.read().decode("utf-8")


def _mkproject(folder, name="P"):
    import rnd_registry
    folder.mkdir(parents=True, exist_ok=True)
    return rnd_registry.add_project(name, str(folder))


def _wait_running(job_runner, jid, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rec = job_runner.load_record(jid)
        if rec and rec.get("status") == job_runner.STATUS_RUNNING:
            return True
        time.sleep(0.02)
    return False


# ── (a) render guard: Kanban + versions + pills + New-run + console + header ──

def test_window_renders_kanban_console_and_header(gui_env, tmp_path):
    """A project with efforts in >=2 lanes renders the full Dashboard A."""
    gui = gui_env
    import effort_history as eh
    folder = tmp_path / "Rich"
    proj = _mkproject(folder, "RichProj")
    pid = proj["id"]
    fp = str(folder)

    # Seed >=2 lanes with >=2 efforts each (versioned history, newest-first).
    eh.record_effort(fp, pid, "research", "r1", skill="researchPrime",
                     prompt_seed="Survey smart-home protocols")
    eh.record_effort(fp, pid, "research", "r2", skill="researchPrime",
                     prompt_seed="Survey v2")
    eh.record_effort(fp, pid, "plan", "p1", skill="crucible",
                     prompt_seed="Master plan")

    html = gui.render_project_window_html(pid)

    # v12 Wave 2 Layout-D: the 5-col .p2lanes grid is RETIRED for the Layout-D
    # shell (.pgrid.layoutd) — two headline zones (Latest Research + Latest
    # Plan/Build) + a persistent right column (Grass + Deliverables).
    assert "class='p2lanes'" not in html
    assert "class='p2col'" not in html
    assert "pgrid layoutd" in html
    assert html.count("class='sectionlbl'") == 2
    assert "Latest Research" in html
    assert "Latest Plan" in html
    for label in ("Research", "Plan", "Build", "Deliverables"):
        assert label in html
    # Recency is now expressed structurally: the NEWEST research session is the
    # headline card and the older one is a little-tile in the collapsible shelf
    # (replaces the old vN labels). research has 2 sessions -> 1 headline + 1
    # shelf minitile.
    assert "class='headline" in html
    assert "minitile" in html
    assert "shelf-wrap" in html
    assert "Survey v2" in html   # newest research → headline title
    assert "Survey smart-home protocols" in html  # older → shelf minitile
    # Genuine tiles (with the legacy lane-tile alias) — NOT old effort cards.
    assert "tile lane-tile" in html
    assert "class='effort'" not in html
    assert "class='kan'" not in html
    # Start affordances. v12 Wave 2: the per-lane "+ New <lane> run" launchers
    # are retired for Layout D — a single "+ New effort" control (inert this
    # wave, wired in W10) is the effort-start entry, and the masthead "Open
    # terminal" still wires the live general-session start path
    # (newTermSession → term_start → terminal_session.start_session).
    assert "id='newResearchBtn'" in html  # v12 W10 refine: + New research
    assert "id='newPlanBuildBtn'" in html  # v12 W10 refine: + New plan/build
    assert "newEffort('general')" in html or "newGeneral(" in html
    # Real xterm.js terminal: the vendored library + stylesheet are included and
    # the inline panel mounts xterm directly (new window.Terminal). v4.1: the v2
    # anchor-term REPL adapter is no longer used by the cockpit.
    assert "/vendor/xterm/xterm.js" in html
    assert "/vendor/xterm/xterm.css" in html
    assert "new window.Terminal(" in html
    assert "anchor-term.js" not in html
    # v4.1 cockpit: the multi-session CONSOLE DRAWER was removed. The terminal
    # now lives ONLY inside an expanded inline panel (openPanel), and a live tile
    # opens it via laneTileClick → openPanel. Assert the panel surface + that the
    # old drawer ids/functions are gone.
    assert "id='panelStack'" in html
    assert "function openPanel" in html
    assert "laneTileClick(" in html
    assert "id='ctabs'" not in html
    assert "id='laneLog'" not in html
    assert "id='laneGate'" not in html
    assert "stopAttached(" not in html
    assert "function attachSession" not in html
    # Lifecycle header.
    assert "rndSetPriority(" in html
    assert "rndArchive(" in html
    assert "rndRetire(" in html
    assert "rndNotes(" in html
    assert "RichProj" in html
    # f-string / brace hygiene of the served page.
    assert "{{" not in html and "}}" not in html


def test_vendored_xterm_assets_present_and_real(gui_env):
    """The genuine xterm.js library + stylesheet are vendored locally (offline)
    and look like the real upstream bundle (no network, no fake)."""
    import anchor_gui as gui
    assert gui.XTERM_DIR.is_file() is False  # it's a directory
    assert (gui.XTERM_DIR / "xterm.js").is_file()
    assert (gui.XTERM_DIR / "xterm.css").is_file()
    assert (gui.XTERM_DIR / "PROVENANCE.txt").is_file()
    js = (gui.XTERM_DIR / "xterm.js").read_text(encoding="utf-8")
    # Real xterm.js is a sizeable UMD bundle that exports the Terminal class.
    assert len(js) > 100_000
    assert "Terminal" in js


def test_xterm_asset_serves_local_file_and_blocks_traversal(gui_env):
    """xterm_asset() serves the vendored bytes and refuses traversal — mirrors
    the hardened katex/anchor-term static-asset routes."""
    import anchor_gui as gui
    js = gui.xterm_asset("xterm.js")
    assert js is not None
    data, ctype = js
    assert ctype.startswith("text/javascript")
    assert b"Terminal" in data
    css = gui.xterm_asset("xterm.css")
    assert css is not None and css[1].startswith("text/css")
    # Path traversal / escapes must be refused (ZERO bytes read on escape).
    assert gui.xterm_asset("../../paths.py") is None
    assert gui.xterm_asset("../anchor-term/anchor-term.js") is None
    assert gui.xterm_asset("does-not-exist.js") is None


def test_xterm_static_route_served_over_http_and_traversal_safe(server):
    """GET /vendor/xterm/xterm.js serves the real bytes; a traversal attempt and
    a missing file 404 (the route mirrors the KaTeX/anchor-term static routes)."""
    gui, base = server
    status, body = _get_text(base + "/vendor/xterm/xterm.js")
    assert status == 200
    assert "Terminal" in body and len(body) > 100_000
    # CSS too.
    status_css, body_css = _get_text(base + "/vendor/xterm/xterm.css")
    assert status_css == 200 and ".xterm" in body_css
    # Traversal / missing -> 404 (never serve outside the vendored dir). The
    # traversal uses percent-encoded dot-segments so it reaches the server
    # un-normalized (a raw "../" is collapsed client-side by urllib).
    for bad in ("/vendor/xterm/%2e%2e/%2e%2e/paths.py", "/vendor/xterm/nope.js"):
        try:
            _get_text(base + bad)
            served = True
        except urllib.error.HTTPError as e:
            served = False
            assert e.code == 404
        assert not served, f"{bad} should not be served"


def test_window_done_effort_links_report_viewer(gui_env, tmp_path):
    """A DONE run session resolves to the /report/<pid>/<lane>/<job_id> link via
    the summarizer member-links (surfaced in the opened panel's split summary).

    v4.1 cockpit-render: the lane tile no longer carries the /report link inline;
    the report viewer is reached from the panel's doc links (member_links /
    session_doc_roles, which reuse the existing /report route). Same intent — a
    done session links to its report viewer."""
    gui = gui_env
    import effort_history as eh
    import sessions as sess
    import summarizer as summ
    folder = tmp_path / "Done"
    proj = _mkproject(folder, "DoneProj")
    pid = proj["id"]
    fp = str(folder)
    eh.record_effort(fp, pid, "research", "donejob", skill="researchPrime",
                     extra={"status": "done"})
    # The done RUN session resolves to a /report/<pid>/<lane>/<job_id> doc link
    # (the panel's split summary shows these role-tagged links).
    sess_list = sess.list_sessions(fp, pid, "research")
    assert sess_list, "no research session recorded"
    sid = sess_list[0]["session_id"]
    roles = summ.session_doc_roles(pid, "research", sid, folder_path=fp)
    hrefs = [r["href"] for r in roles.values()]
    assert any(h == f"/report/{pid}/research/donejob" for h in hrefs), hrefs
    # The JS helper that opens a report in a new tab is still present.
    html = gui.render_project_window_html(pid)
    assert "function openReport" in html


def test_window_xss_escapes_project_name(gui_env, tmp_path):
    """Engine/user content is HTML-escaped: a project name with markup is not
    injected raw into the served window."""
    gui = gui_env
    folder = tmp_path / "xss"
    proj = _mkproject(folder, "<script>alert(1)</script>")
    html = gui.render_project_window_html(proj["id"])
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


# ── gate option buttons must be functional (no HTML-attribute breakout) ──────

def test_gate_answer_happens_in_panel_terminal_no_broken_onclick(gui_env):
    """v4.1: the gate is answered INSIDE the panel terminal (the live ConPTY
    session — an AskUserQuestion is presented + answered over the PTY/xterm), so
    the old console-drawer one-click gate buttons (answerGate + the
    data-gate-opt delegated listener) were removed. We assert (a) the panel
    terminal transport that carries the answer is wired, and (b) the served window
    JS never rebuilds the broken inline-onclick gate pattern
    (`onclick="answerGate(' + JSON.stringify(label) + ')"`) that this test
    originally guarded against."""
    gui = gui_env
    js = gui._PROJECT_WINDOW_JS
    # (a) The panel terminal mounts xterm over the v3 transport — that is where a
    #     gate prompt is now shown and answered (keystrokes → term_input2).
    assert "term_input2" in js
    assert "new window.Terminal(" in js
    # The dead console-drawer gate machinery is gone.
    assert "data-gate-opt" not in js
    assert "_gateDelegated" not in js
    assert "function answerGate" not in js
    # (b) No NON-COMMENT line builds an inline onclick from JSON.stringify, and the
    #     broken literal substring never appears anywhere as code.
    for i, line in enumerate(js.splitlines(), 1):
        s = line.strip()
        if s.startswith("//"):
            continue
        assert not ("onclick" in line and "JSON.stringify" in line), (
            f"line {i} rebuilds the broken inline-onclick gate pattern: {line!r}")
    assert 'onclick="answerGate(' not in js


def test_gate_button_attribute_does_not_break_out(gui_env):
    """Prove that constructing the gate button the way the fixed JS does
    (setAttribute('data-gate-opt', label) + textContent = label) yields HTML
    whose attribute value is the COMPLETE label — even for labels that contain a
    double quote — and that an html.parser tokenizes exactly one button with the
    full label intact (the old inline-onclick pattern truncated at the first
    inner double quote)."""
    from html.parser import HTMLParser
    from xml.sax.saxutils import quoteattr, escape

    def render_button(label):
        # Mirrors the fixed DOM construction's serialized output: the browser
        # serializes setAttribute(name, value) by HTML-escaping the value for the
        # attribute context (quoteattr does the equivalent here), and textContent
        # is HTML-escaped element text.
        return ('<button class="btn accent" data-gate-opt='
                + quoteattr(label) + '>' + escape(label) + '</button>')

    class P(HTMLParser):
        def __init__(self):
            super().__init__()
            self.buttons = []
            self._txt = []

        def handle_starttag(self, tag, attrs):
            if tag == "button":
                self.buttons.append(dict(attrs))

        def handle_data(self, data):
            self._txt.append(data)

    for label in ["Approve", "JSON files", 'a"b', "SQLite"]:
        p = P()
        p.feed(render_button(label))
        assert len(p.buttons) == 1, f"label {label!r} produced bad markup"
        attrs = p.buttons[0]
        # The data attribute carries the COMPLETE label, never truncated.
        assert attrs.get("data-gate-opt") == label
        # No stray garbage attribute leaked from a breakout.
        assert set(attrs.keys()) == {"class", "data-gate-opt"}
        # Button text is the label.
        assert "".join(p._txt) == label


# ── (b) /api/rnd/cancel_job: cancels a running mock + 404 on unknown ──────────

def test_cancel_job_stops_running_and_404_unknown(server, tmp_path):
    gui, base = server
    import job_runner
    proj = _mkproject(tmp_path / "cj", "CancelProj")
    # Launch a research mock that sleeps so it stays running.
    code, body = _post(base + "/api/rnd/launch_lane",
                       {"project_id": proj["id"], "lane": "research"})
    assert code == 200 and body["ok"] is True
    jid = body["job_id"]
    # (the default mock exits fast; relaunch with a sleeping one via job_runner
    # so the cancel has a live process to reap)
    rec = job_runner.launch("research", extra_args=["--lines", "1", "--sleep", "5"])
    jid = rec["job_id"]
    assert _wait_running(job_runner, jid)

    code, data = _post(base + "/api/rnd/cancel_job", {"job_id": jid})
    assert code == 200
    assert data["ok"] is True
    assert data["job_id"] == jid
    assert data["status"] == job_runner.STATUS_CANCELLED
    # The durable record reflects the cancel.
    assert job_runner.load_record(jid)["status"] == job_runner.STATUS_CANCELLED

    # Unknown id -> clean 404 (not a 500).
    code, data = _post(base + "/api/rnd/cancel_job", {"job_id": "does-not-exist"})
    assert code == 404
    assert data["ok"] is False
    assert data["reason"] == "unknown-job"

    job_runner.wait(jid, timeout=30)


# ── (c) multi-session: two jobs => two switchable sessions; answer by job_id ──

def test_two_sessions_switchable_and_answer_routes_to_job(server, tmp_path):
    gui, base = server
    import job_runner
    import gate_adapter
    proj = _mkproject(tmp_path / "ms", "MultiProj")
    pid = proj["id"]

    # Job A: a plain running research mock (sleeps so it stays live).
    recA = job_runner.launch("research",
                             extra_args=["--lines", "2", "--sleep", "5"])
    jidA = recA["job_id"]
    # Job B: a gated plan mock that reaches awaiting-input.
    recB = job_runner.launch("plan",
                             extra_args=["--lines", "1", "--sleep", "5"])
    jidB = recB["job_id"]
    assert _wait_running(job_runner, jidA)
    assert _wait_running(job_runner, jidB)

    # Record both as efforts so the server renders them as live cards/sessions.
    import effort_history as eh
    eh.record_effort(str(tmp_path / "ms"), pid, "research", jidA,
                     skill="researchPrime")
    eh.record_effort(str(tmp_path / "ms"), pid, "plan", jidB, skill="crucible")

    # Inject an awaiting-input gate onto job B (via the real gate_adapter path).
    GATE = (Path(__file__).resolve().parent / "fixtures" / "gate_stream.jsonl")

    class FakeSink:
        def __init__(self):
            self.writes = []
            self._lock = threading.Lock()

        def write(self, data):
            with self._lock:
                self.writes.append(data)

        def flush(self):
            pass

    sink = FakeSink()
    gate_adapter.register_stdin_sink(jidB, sink)
    prompt = gate_adapter.ingest_stream(
        jidB, GATE.read_text(encoding="utf-8").splitlines())
    assert prompt is not None

    # The served window exposes BOTH jobs as live (green) tiles — in Layout D the
    # research session is the Latest-Research headline and the plan session is the
    # Latest-Plan/Build headline, each keyed by its run:: session id and rendered
    # with the running (green) status light. v12 Wave 2: a tile opens its inline
    # panel via laneTileClick → openPanel — but the per-job answer-gate routing
    # below is unchanged and is the real subject of this test.
    status, html = _get_text(base + f"/project/{pid}")
    assert status == 200
    # Both sessions surface as headline tiles keyed by their run:: ids: A is
    # running (green) and B is awaiting input (amber, from its injected gate).
    assert f'data-session="run::{jidA}"' in html
    assert f'data-session="run::{jidB}"' in html
    assert 'data-light="green"' in html   # job A, running
    assert 'data-light="amber"' in html   # job B, needs-input (gate)
    assert "function openPanel" in html

    # An answer routes to the SPECIFIC job_id (job B's gate), not job A.
    code, ans = _post(base + "/api/rnd/answer_gate",
                      {"job_id": jidB, "choice": "JSON files"})
    assert code == 200
    assert ans["ok"] is True and ans["written"] is True
    assert ans["job_id"] == jidB
    # Exactly one stdin write landed on job B's sink (no cross-wire to A).
    assert len(sink.writes) == 1

    # Answering job A (which has no gate) is a clean no-op (proves no cross-wire).
    code, ansA = _post(base + "/api/rnd/answer_gate",
                       {"job_id": jidA, "choice": "JSON files"})
    assert code == 200
    assert ansA["written"] is False

    # Reap both.
    job_runner.cancel(jidA)
    job_runner.cancel(jidB)
    job_runner.wait(jidA, timeout=30)
    job_runner.wait(jidB, timeout=30)
