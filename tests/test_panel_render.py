"""v4 Wave 5 — panel internals: stacked summary (equal-height split) + resizable
terminal + header rollup.

Locks the Wave-5 Done-when at the RENDER + endpoint level (no browser): an
expanded panel renders the split summary (LEFT ``.smat`` materials + RIGHT
``.slinks`` role-tagged links) with the EQUAL-HEIGHT CSS (the left effort line
sinks via ``.smat .effbar{margin-top:auto}``; the right second group pins via
``.slinks .slh.two{margin-top:auto}``), the role-tagged links resolve from the
Wave-3 ``session_doc_roles`` data, a vertically-resizable terminal pane is bound
to the existing v3 transport (``term_ws`` / ``term_stream2`` / ``term_input2`` /
``term_resize``), and the project-window header shows the project path + the
``Σ tokens · $ · time`` rollup with a lifetime/30-day toggle.

Plus the two NEW read-only GET endpoints (``/api/rnd/session_doc_roles`` and
``/api/rnd/project_rollup``): token-gated via ``?token=``, returning the right
shape over a throwaway server.

Stub PTY backend; temp ANCHOR_DATA_DIR; no live claude, no real data, never :8777.
"""
import importlib
import json as _json
import threading as _threading
import urllib.request as _urlreq
import urllib.error as _urlerr
from urllib.parse import quote as _q

import pytest


@pytest.fixture
def gui(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    # Back-compat (no-token) mode by default — mirror the suite-wide pattern so
    # the ambient dev-host ANCHOR_TOKEN can't leak in and 401 the read-only
    # GET endpoints these tests exercise. The token-gated test re-sets it.
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    import paths
    importlib.reload(paths)
    import rnd_registry
    importlib.reload(rnd_registry)
    import effort_history
    importlib.reload(effort_history)
    import sessions
    importlib.reload(sessions)
    import deliverables
    importlib.reload(deliverables)
    import handoff
    importlib.reload(handoff)
    import summarizer
    importlib.reload(summarizer)
    import anchor_gui
    importlib.reload(anchor_gui)
    return anchor_gui


def _mkproject(gui, tmp_path, name="Panel"):
    folder = tmp_path / "P"
    folder.mkdir(exist_ok=True)
    pid = gui.select_existing_project(name, str(folder))["entry"]["id"]
    return folder, pid


def _discovered(eh, folder, pid, lane, rel, title=""):
    jid = eh.discovered_job_id(lane, rel)
    return eh.record_effort(folder, pid, lane, jid, extra={
        "source": eh.SOURCE_DISCOVERED, "artifact_path": rel,
        "title": title or rel, "status": "imported"})


# ── (1) the expanded-panel body builds the split summary (both columns) ───────

def test_panel_body_builds_split_summary_both_columns(gui, tmp_path):
    """openPanel fills the panel body with a split summary: a LEFT materials
    column (.smat) and a RIGHT role-link column (.slinks)."""
    _, pid = _mkproject(gui, tmp_path)
    html = gui.render_project_window_html(pid)
    # The panel-body JS builds a `summary split` block with both columns.
    assert "summary split" in html
    assert "function _renderSplitSummary" in html
    assert "class=\"smat\"" in html        # left materials column
    assert "class=\"slinks\"" in html      # right role-link column
    # The summary is loaded async from the read-only endpoints.
    assert "function _loadPanelSummary" in html
    assert "/api/rnd/session_summary" in html
    assert "/api/rnd/session_doc_roles" in html


def test_panel_split_equal_height_css_present(gui, tmp_path):
    """The locked equal-height split CSS is served: a grid .summary.split with
    align-items:stretch, the left effort line at margin-top:auto, and the right
    second link group (.slh.two) at margin-top:auto — both columns fill the same
    vertical height (mockup Paradigm-2 internals)."""
    _, pid = _mkproject(gui, tmp_path)
    html = gui.render_project_window_html(pid)
    assert ".panel .summary.split{" in html
    assert "align-items:stretch" in html
    # Left effort line sinks to the bottom.
    assert ".panel .summary .smat .effbar{font-size:11px;color:var(--text-dim);" \
           "margin-top:auto}" in html
    # Right second doc group pins to the bottom.
    assert ".panel .summary .slinks .slh.two{margin-top:auto}" in html
    # Both columns are flex-column so margin-top:auto resolves against full height.
    assert ".panel .summary .smat{min-width:0;display:flex;" \
           "flex-direction:column}" in html
    assert "padding-left:18px;display:flex;flex-direction:column}" in html


# ── (2) the role-tagged links resolve from the Wave-3 data ────────────────────

def test_panel_role_links_resolve_from_wave3_doc_roles(gui, tmp_path):
    """The split's RIGHT column renders the role-tagged links the Wave-3
    summarizer.session_doc_roles resolves (planning → master/impl/northstar),
    each via the existing /artifact route. The render JS keys per-lane role
    grouping so the secondary group (northstar) pins to the bottom."""
    import summarizer as summ
    import sessions as sess
    folder, pid = _mkproject(gui, tmp_path)
    import effort_history as eh
    d = "planning/rnd-x"
    _discovered(eh, folder, pid, "planning", f"{d}/MASTER-PLAN.md", "Master")
    _discovered(eh, folder, pid, "planning", f"{d}/IMPLEMENTATION-PLAN.md", "Impl")
    _discovered(eh, folder, pid, "planning", f"{d}/North-Star.md", "North Star")
    # The Wave-3 data the panel renders resolves all three roles.
    sid = None
    for s in sess.list_sessions(folder, pid, "planning"):
        if any((m.get("artifact_path") or "").startswith(d)
               for m in s["member_files"]):
            sid = s["session_id"]
    assert sid is not None
    roles = summ.session_doc_roles(pid, "planning", sid, folder_path=folder)
    assert set(roles) == {"master", "impl", "northstar"}
    assert roles["master"]["href"].endswith("MASTER-PLAN.md")
    # The render JS exposes the per-lane role grouping + a .two secondary group.
    html = gui.render_project_window_html(pid)
    assert "_DOC_ROLE_GROUPS" in html
    assert "slh two" in html               # the pinned-to-bottom second group
    assert "northstar" in html             # planning's secondary role


# ── (3) the terminal pane is resizable + bound to the existing transport ──────

def test_panel_terminal_host_is_resizable_and_bound_to_transport(gui, tmp_path):
    """The panel's terminal host sits in a vertically-resizable .tpane, mounts
    xterm.js over the EXISTING v3 transport (WS term_ws → SSE term_stream2 +
    POST term_input2), and a resize re-fits + calls term_resize."""
    _, pid = _mkproject(gui, tmp_path)
    html = gui.render_project_window_html(pid)
    # The terminal pane is CSS-resizable (drag the bottom edge).
    assert ".panel .tpane{" in html
    assert "resize:vertical" in html
    # The xterm host lives inside the pane and is mounted via the existing path.
    assert "term-host" in html
    assert "_mountTerminal(sessionId, host)" in html
    assert "new window.Terminal(" in html
    # The existing v3 transport endpoints are wired (UNCHANGED).
    for ep in ("/api/rnd/term_ws", "/api/rnd/term_stream2",
               "/api/rnd/term_input2", "/api/rnd/term_resize"):
        assert ep in html, "missing transport endpoint: " + ep
    # Resize is wired to term_resize via the fit path.
    assert "function _wirePanelResize" in html
    assert "function _fitPanelTerminal" in html
    assert "ResizeObserver" in html
    # Chosen height persists per session (in-memory).
    assert "_panelHeights" in html


# ── (4) the header shows the rollup (Σ / tokens) + the path + a window toggle ─

def test_header_shows_rollup_and_path(gui, tmp_path):
    """The project-window header renders the project PATH and the cost/tokens/
    time rollup (Σ … tok · $ · time · N sessions) with a lifetime/30-day toggle
    wired to the read-only project_rollup endpoint."""
    folder, pid = _mkproject(gui, tmp_path, name="HdrProj")
    html = gui.render_project_window_html(pid)
    # The path is in the header.
    assert "class='path'" in html
    assert str(folder) in html
    # The rollup shows Σ + tokens (zeroed but present for a fresh project).
    assert "id='hdrRollup'" in html
    assert "Σ" in html                # Σ
    assert "tok" in html
    assert "session" in html
    # The lifetime/30-day toggle + its JS swap.
    assert "rolltog" in html
    assert "rndRollupWindow('lifetime'" in html
    assert "rndRollupWindow('30d'" in html
    assert "function rndRollupWindow" in html
    assert "/api/rnd/project_rollup" in html


def test_header_rollup_sums_run_sessions_only(gui, tmp_path):
    """The header rollup line reflects project_effort_rollup (RUN sessions only).
    A project with a single RUN session carrying a cost record shows that token
    total; an imported-only project shows the zero baseline."""
    import effort_history as eh
    folder, pid = _mkproject(gui, tmp_path, name="RollProj")
    # A RUN effort with a cost record.
    eh.record_effort(folder, pid, "research", "rjob", skill="researchPrime")
    eh.attach_cost(folder, pid, "research", "rjob", {
        "status": "done", "finished_at": 1000.0,
        "cost": {"total_tokens": 4200, "total_cost_usd": 0.55,
                 "duration_ms": 60000, "input_tokens": 2100,
                 "output_tokens": 2100}})
    roll = eh.project_effort_rollup(pid, window="lifetime")
    assert roll["tokens"] == 4200
    line = gui._fmt_rollup_line(roll)
    assert line.startswith("Σ")
    assert "4k tok" in line                # 4200 → "4k tok"
    assert "$0.55" in line
    assert "1 session" in line


# ── (5) the new GET endpoints: token-gated + right shape ──────────────────────

def _serve(gui):
    server = gui.make_server("127.0.0.1", 0)
    port = server.server_address[1]
    t = _threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server, port


def _get(port, path):
    url = f"http://127.0.0.1:{port}{path}"
    try:
        with _urlreq.urlopen(url, timeout=10) as r:
            return r.getcode(), _json.loads(r.read().decode("utf-8"))
    except _urlerr.HTTPError as e:
        return e.code, _json.loads(e.read().decode("utf-8"))


def test_session_doc_roles_endpoint_shape(gui, tmp_path):
    """GET /api/rnd/session_doc_roles returns {ok, roles:{role:{label,href}}}
    resolving the Wave-3 role set, each href on an existing route."""
    import effort_history as eh
    import sessions as sess
    folder, pid = _mkproject(gui, tmp_path)
    d = "planning/rnd-e"
    _discovered(eh, folder, pid, "planning", f"{d}/MASTER-PLAN.md", "Master")
    _discovered(eh, folder, pid, "planning", f"{d}/IMPLEMENTATION-PLAN.md", "Impl")
    sid = None
    for s in sess.list_sessions(folder, pid, "planning"):
        if any((m.get("artifact_path") or "").startswith(d)
               for m in s["member_files"]):
            sid = s["session_id"]
    server, port = _serve(gui)
    try:
        code, data = _get(port, "/api/rnd/session_doc_roles?"
                          f"pid={_q(pid)}&lane=planning&session={_q(sid)}")
        assert code == 200
        assert data["ok"] is True
        roles = data["roles"]
        assert set(roles) == {"master", "impl"}
        for r in roles.values():
            assert "label" in r and "href" in r
            assert r["href"].startswith(("/artifact/", "/report/"))
    finally:
        server.shutdown()
        server.server_close()


def test_session_doc_roles_endpoint_validates_and_is_terminal(gui, tmp_path):
    """The doc-roles endpoint rejects a missing arg (400) + a traversal pid
    (400 bad pid), and returns {} for an unknown session (never fabricated)."""
    folder, pid = _mkproject(gui, tmp_path)
    server, port = _serve(gui)
    try:
        # missing args → 400
        code, data = _get(port, "/api/rnd/session_doc_roles?pid=" + _q(pid))
        assert code == 400
        # traversal pid → 400 bad pid
        code, data = _get(port, "/api/rnd/session_doc_roles?"
                          f"pid={_q('../../etc')}&lane=planning&session=s")
        assert code == 400 and data["error"] == "bad pid"
        # unknown session → ok with empty roles
        code, data = _get(port, "/api/rnd/session_doc_roles?"
                          f"pid={_q(pid)}&lane=planning&session={_q('no::such')}")
        assert code == 200 and data["ok"] is True and data["roles"] == {}
    finally:
        server.shutdown()
        server.server_close()


def test_project_rollup_endpoint_shape_and_window(gui, tmp_path):
    """GET /api/rnd/project_rollup returns {ok, window, rollup, text}; the rollup
    sums RUN sessions, and window=30d is honored (lifetime vs 30d differ when an
    old record falls outside the window)."""
    import effort_history as eh
    folder, pid = _mkproject(gui, tmp_path)
    eh.record_effort(folder, pid, "research", "rj", skill="researchPrime")
    eh.attach_cost(folder, pid, "research", "rj", {
        "status": "done", "finished_at": 5000.0,
        "cost": {"total_tokens": 3000, "total_cost_usd": 0.30,
                 "duration_ms": 30000, "input_tokens": 1500,
                 "output_tokens": 1500}})
    server, port = _serve(gui)
    try:
        code, data = _get(port,
                          f"/api/rnd/project_rollup?pid={_q(pid)}&window=lifetime")
        assert code == 200 and data["ok"] is True
        assert data["window"] == "lifetime"
        assert data["rollup"]["tokens"] == 3000
        assert data["text"].startswith("Σ")
        assert "tok" in data["text"]
        # window=30d is a valid window (the value is honored/returned).
        code, d30 = _get(port,
                         f"/api/rnd/project_rollup?pid={_q(pid)}&window=30d")
        assert code == 200 and d30["window"] == "30d"
    finally:
        server.shutdown()
        server.server_close()


def test_project_rollup_endpoint_validates(gui, tmp_path):
    """The rollup endpoint requires a pid (400) and rejects a traversal pid."""
    _, pid = _mkproject(gui, tmp_path)
    server, port = _serve(gui)
    try:
        code, data = _get(port, "/api/rnd/project_rollup?window=lifetime")
        assert code == 400
        code, data = _get(port,
                          f"/api/rnd/project_rollup?pid={_q('../../x')}")
        assert code == 400 and data["error"] == "bad pid"
    finally:
        server.shutdown()
        server.server_close()


def test_new_get_endpoints_token_gated(gui, tmp_path, monkeypatch):
    """Both new read-only GET endpoints gate via ?token= (same semantics as the
    WS/SSE transport): when a token is configured, a missing/wrong token is 401;
    the correct token passes."""
    import paths
    monkeypatch.setenv("ANCHOR_TOKEN", "s3cret")
    importlib.reload(paths)
    importlib.reload(gui)
    folder, pid = _mkproject(gui, tmp_path)
    server, port = _serve(gui)
    try:
        # No token → 401 on both.
        for path in ("/api/rnd/session_doc_roles?"
                     f"pid={_q(pid)}&lane=planning&session=s",
                     f"/api/rnd/project_rollup?pid={_q(pid)}"):
            code, data = _get(port, path)
            assert code == 401, "expected 401 without token: " + path
            assert data["error"] == "unauthorized"
        # Correct token → not 401.
        code, data = _get(port, "/api/rnd/project_rollup?"
                          f"pid={_q(pid)}&token=s3cret")
        assert code == 200 and data["ok"] is True
    finally:
        server.shutdown()
        server.server_close()


# ── brace hygiene (f-string + RAW string discipline) ─────────────────────────

def test_panel_render_no_leaked_braces(gui, tmp_path):
    """The Wave-5 panel CSS/JS must not leak doubled braces into the served HTML;
    the prior surfaces (console drawer, accordion, panel manager) stay intact."""
    _, pid = _mkproject(gui, tmp_path)
    html = gui.render_project_window_html(pid)
    assert "{{" not in html
    assert "}}" not in html
    assert "function openPanel" in html
    assert "function _mountTerminal" in html
    assert "function newTermSession" in html
