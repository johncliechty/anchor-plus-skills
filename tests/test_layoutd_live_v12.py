"""v12 Wave 10 — Layout-D LIVE wiring gate (render-smoke + DOM pos/neg).

Asserts the RENDERED BODY STRUCTURE of the wired Layout-D bottom dock
(_mockups/dashboard_D_headline_shelf.html, dock OPEN): the single bottom dock
renders summary ON TOP of the terminal (DOM order), the dock carries the 3-node
stage track + the Advance -> / Kill -> Boneyard / context-full warn controls, and
the effort tiles are BOUND to the effort view (data-effort-id +
data-current-stage). The dock starts UNBOUND (no effort selected → no dock body
bound — negative case).

The render-smoke test runs BEFORE any Playwright: it asserts the page imports +
renders to a non-empty, BRACE-BALANCED string (so a leaked single `{`/`}` from
the f-string region fails fast) and carries the wired Layout-D dock landmarks.

Hermetic: temp data/project dirs, stub PTY, never :8777, never real data.
"""
import importlib
import re
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
    monkeypatch.delenv("ANCHOR_PROACTIVE_SUMMARY", raising=False)
    for mod in ("paths", "job_runner", "rnd_registry", "lanes",
                "effort_history", "summarizer", "session_registry",
                "effort_view", "gate_adapter"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import anchor_gui
    yield importlib.reload(anchor_gui)


def _mkproject(folder, name="P"):
    import rnd_registry
    folder.mkdir(parents=True, exist_ok=True)
    return rnd_registry.add_project(name, str(folder))


def _multi(gui, tmp_path, name="Multi"):
    """A project with >=1 research + >=1 plan/build session."""
    import effort_history as eh
    folder = tmp_path / name
    pid = _mkproject(folder, name)["id"]
    fp = str(folder)
    eh.record_effort(fp, pid, "research", "r1", skill="researchPrime",
                     prompt_seed="Cooling-loop coolant trade study")
    eh.record_effort(fp, pid, "research", "r2", skill="researchPrime",
                     prompt_seed="Fuel-cladding alloy survey")
    eh.record_effort(fp, pid, "plan", "p1", skill="crucible",
                     prompt_seed="Control-stack architecture plan")
    eh.record_effort(fp, pid, "build", "b1", skill="foreman",
                     prompt_seed="Fuel-handling controller")
    return pid, fp


def _strip(html):
    b = re.sub(r"<style[\s\S]*?</style>", "", html)
    b = re.sub(r"<script[\s\S]*?</script>", "", b)
    m = re.search(r"<body[^>]*>([\s\S]*)</body>", b)
    return m.group(1) if m else b


class _Collector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.els = []         # (tag, classes, attrs)
        self.order = []       # ids/classes in document START order

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        cls = (d.get("class") or "").split()
        self.els.append((tag, cls, d))
        self.order.append((d.get("id") or "", cls))


def _parse(body):
    c = _Collector()
    c.feed(body)
    return c


# ── 1. RENDER-SMOKE (runs before any Playwright) ────────────────────────────

def test_render_smoke_balanced_braces_and_dock_landmarks(gui_env, tmp_path):
    gui = gui_env
    pid, _ = _multi(gui, tmp_path)
    html = gui.render_project_window_html(pid)
    assert isinstance(html, str) and html.strip(), "empty / non-str render"
    assert html.count("{") == html.count("}"), (
        "brace imbalance in rendered HTML (likely an f-string `{`/`}` leak): "
        f"{html.count('{')} open vs {html.count('}')} close")
    # The wired dock landmarks (chrome + JS attach points).
    for landmark in ("effortDock", "dockTrack", "dockSummary", "dockSplit",
                     "dockTermHost", "dockAdvance", "dockKill", "dockWarn",
                     "dockMetrics",
                     "Advance ", "Kill ", "function openEffortDock",
                     "function dockAdvance", "function dockHandoffToFresh",
                     "function _loadDockMetrics",
                     "data-effort-id"):
        assert landmark in html, f"missing wired Layout-D landmark: {landmark!r}"


# ── 1b. John change #1 — the dock is EMBEDDED in flow (NOT a fixed overlay) ───

def test_dock_embedded_in_flow_not_fixed(gui_env, tmp_path):
    """John change #1: the dock renders as a normal in-flow section inside the
    content column (NOT a position:fixed overlay). Assert the dock's DEFAULT/
    restored rule is position:relative (and never position:fixed at base), and
    that the dock element lives inside the .dash content container in the DOM."""
    gui = gui_env
    pid, _ = _multi(gui, tmp_path)
    html = gui.render_project_window_html(pid)
    # The dock's BASE rule embeds it in flow — position:relative, not fixed. (The
    # only fixed rule is the deliberate maximize blow-up: .dock.maxd.)
    style_m = re.search(r"<style[\s\S]*?</style>", html)
    style = style_m.group(0) if style_m else ""
    base_m = re.search(r"\.dock\{([^}]*)\}", style)
    assert base_m, "no .dock base CSS rule found"
    base_rule = base_m.group(1).replace(" ", "")
    assert "position:relative" in base_rule, (
        "the dock base rule must be position:relative (embedded in flow), "
        f"got: {base_rule!r}")
    assert "position:fixed" not in base_rule, (
        "the dock base rule must NOT be position:fixed (no floating overlay)")
    # The ONLY position:fixed on the dock is the maximize state (.dock.maxd).
    fixed_rules = re.findall(r"(\.dock(?:\.\w+)?)\{[^}]*position:fixed", style)
    assert all(r == ".dock.maxd" for r in fixed_rules), (
        f"position:fixed on the dock is only allowed for .dock.maxd, got {fixed_rules}")
    # DOM: the dock element is INSIDE the .dash content container (in-flow), not a
    # top-level overlay sibling of <body>.
    body = _strip(html)
    dash_m = re.search(r"<div class='dash'[\s\S]*?</body>", html)
    # Simpler structural check: #effortDock appears before the closing </div> of
    # the dash content and after the panel-stack (i.e. it is part of the content).
    assert "id='effortDock'" in html or 'id="effortDock"' in html
    assert "panelStack" in body and "effortDock" in body, \
        "dock not rendered within the project content body"


# ── 1c. John change #2 — TWO new-session controls (research + plan/build) ────

def test_two_new_session_controls(gui_env, tmp_path):
    """(2026-08-07, John's simple workbench) ONE start control: the general
    terminal. The research/plan starters are gone — trio work is commissioned
    through the steward."""
    gui = gui_env
    pid, _ = _multi(gui, tmp_path)
    html = gui.render_project_window_html(pid)
    assert "+ New general terminal" in html, "missing '+ New general terminal'"
    assert "+ New research" not in html, "'+ New research' must be gone"
    assert "+ New plan/build" not in html, "'+ New plan/build' must be gone"
    assert "newEffort('general')" in html, \
        "the general control must call newEffort('general')"
    body = _strip(html)
    c = _parse(body)
    btn_ids = {d.get("id") for _, _, d in c.els}
    assert "newGeneralBtn" in btn_ids, "no #newGeneralBtn"
    assert "newResearchBtn" not in btn_ids, "#newResearchBtn must be gone"
    assert "newPlanBuildBtn" not in btn_ids, "#newPlanBuildBtn must be gone"


# ── 1d. John change #3 — per-effort metrics line in the dock summary ─────────

def test_dock_summary_metrics_line(gui_env, tmp_path):
    """John change #3: the dock summary header carries the per-effort metrics
    line (Σ tokens · time · $) — #dockMetrics — populated from
    /api/rnd/effort_rollup by _loadDockMetrics."""
    gui = gui_env
    pid, _ = _multi(gui, tmp_path)
    html = gui.render_project_window_html(pid)
    body = _strip(html)
    c = _parse(body)
    metrics = [d for _, cl, d in c.els
               if d.get("id") == "dockMetrics" or "dock-metrics" in cl]
    assert metrics, "no #dockMetrics line in the dock summary"
    # The metrics line lives inside the dock summary region (#dockTop), above the
    # terminal — its DOM index precedes the terminal host.
    ids = [i for i, _ in c.order]
    assert "dockMetrics" in ids, "metrics line not in the document"
    assert ids.index("dockMetrics") < ids.index("dockTermHost"), \
        "metrics line must be in the summary region (above the terminal)"
    # The JS fetches the per-effort rollup endpoint.
    assert "/api/rnd/effort_rollup" in html, \
        "the dock must fetch the per-effort rollup (/api/rnd/effort_rollup)"
    assert "function _loadDockMetrics" in html


# ── 1e. backend: per-effort rollup endpoint + effort_view.effort_rollup ──────

def test_effort_rollup_sums_cost_numbers_only(gui_env, tmp_path):
    """effort_view.effort_rollup sums the effort's per-stage job_runner cost
    records (numbers-only shape; deduped; honest zeros for unknown/imported)."""
    import effort_history as eh
    import effort_view
    gui = gui_env
    folder = tmp_path / "Roll"
    pid = _mkproject(folder, "Roll")["id"]
    fp = str(folder)
    sid = "sess-roll-1"
    # A research-stage effort record tagged to the session, carrying a cost block.
    eh.record_effort(fp, pid, "research", "j-research", skill="researchPrime",
                     extra={"session_id": sid,
                            "cost": {"total_tokens": 1200, "duration_ms": 5000,
                                     "total_cost_usd": 0.34}})
    # A plan-stage effort record (store_lane 'planning') for the same session.
    eh.record_effort(fp, pid, "planning", "j-plan", skill="crucible",
                     extra={"session_id": sid,
                            "cost": {"total_tokens": 800, "duration_ms": 3000,
                                     "total_cost_usd": 0.16}})
    # A hand-built effort dict (the shape build_effort_view emits) referencing
    # both stages via stage_history + members.
    effort = {
        "effort_id": sid,
        "stage_history": [
            {"stage": "research", "session_id": sid, "store_lane": "research"},
            {"stage": "plan", "session_id": sid, "store_lane": "planning"},
        ],
        "members": [{"session_id": sid, "stage": "plan", "lane": "planning"}],
    }
    roll = effort_view.effort_rollup(fp, pid, effort)
    assert set(roll.keys()) == {"tokens", "cost_usd", "wall_clock_ms"}
    assert isinstance(roll["tokens"], int)
    assert isinstance(roll["wall_clock_ms"], int)
    assert isinstance(roll["cost_usd"], float)
    # Summed across the two stages (deduped — the plan stage referenced from both
    # stage_history AND members counts once).
    assert roll["tokens"] == 2000, roll
    assert roll["wall_clock_ms"] == 8000, roll
    assert abs(roll["cost_usd"] - 0.50) < 1e-6, roll
    # Unknown effort → honest zeros (never fabricated).
    z = effort_view.effort_rollup(fp, pid, "no-such-effort")
    assert z == {"tokens": 0, "cost_usd": 0.0, "wall_clock_ms": 0}


# ── 2. DOM POSITIVE: the dock renders summary ABOVE terminal + controls ──────

def test_dock_summary_above_terminal_dom_order(gui_env, tmp_path):
    gui = gui_env
    pid, _ = _multi(gui, tmp_path)
    body = _strip(gui.render_project_window_html(pid))
    c = _parse(body)

    # The single bottom dock is present (#effortDock).
    dock_els = [d for t, cl, d in c.els if d.get("id") == "effortDock"]
    assert len(dock_els) == 1, "expected exactly one bottom dock (#effortDock)"

    # DOM ORDER: the summary-on-top region (#dockTop / #dockSummary) precedes the
    # draggable splitter (#dockSplit) which precedes the terminal host
    # (#dockTermHost) — summary ABOVE terminal.
    ids = [i for i, _ in c.order]
    i_top = ids.index("dockTop")
    i_split = ids.index("dockSplit")
    i_term = ids.index("dockTermHost")
    assert i_top < i_split < i_term, (
        "dock DOM order must be summary-on-top -> splitter -> terminal "
        f"(got top={i_top}, split={i_split}, term={i_term})")

    # The 3-node stage track host is in the dock bar.
    assert any(d.get("id") == "dockTrack" for _, _, d in c.els), \
        "no dock stage-track host"
    # The distinct controls: Advance -> , Kill -> Boneyard, the warn banner.
    assert any(d.get("id") == "dockAdvance" for _, _, d in c.els), \
        "no Advance control"
    assert any(d.get("id") == "dockKill" for _, _, d in c.els), \
        "no Kill -> Boneyard control"
    assert any("dock-warn" in cl for _, cl, _ in c.els), \
        "no context-full warn banner"
    # The draggable splitter chrome.
    assert any("dsplit" in cl for _, cl, _ in c.els), "no draggable dock splitter"


def test_effort_tiles_bound_to_effort_view(gui_env, tmp_path):
    """Each Layout-D effort tile carries data-effort-id + data-current-stage
    from the effort view (W10 binding / EV-2 stage source).

    (2026-08-07, John's simple workbench) The board is the GENERAL zone now —
    the binding contract is asserted on general-session tiles; trio sessions
    have no board zone (they surface via the session bar + the run ledger)."""
    import effort_history as eh
    gui = gui_env
    pid, fp = _multi(gui, tmp_path)
    eh.record_effort(fp, pid, "general", "g1", skill="",
                     prompt_seed="General terminal session")
    body = _strip(gui.render_project_window_html(pid))
    c = _parse(body)
    tiles = [d for t, cl, d in c.els if "lane-tile" in cl]
    assert tiles, "no Layout-D effort tiles rendered (general zone)"
    # Every effort tile is bound to an effort_id (the dock-open contract).
    assert all(d.get("data-effort-id") is not None for d in tiles), \
        "an effort tile is not bound to data-effort-id"
    # And carries a current-stage attr (the EV-2 stage-track source).
    assert all("data-current-stage" in d for d in tiles), \
        "an effort tile is missing data-current-stage"


# ── 3. DOM NEGATIVE: no effort selected → dock UNBOUND, no body bound ────────

def test_dock_starts_unbound(gui_env, tmp_path):
    """With no effort selected, the dock is hidden + UNBOUND: it has NO
    data-effort-id and is display:none (no dock body bound)."""
    gui = gui_env
    pid, _ = _multi(gui, tmp_path)
    html = gui.render_project_window_html(pid)
    body = _strip(html)
    c = _parse(body)
    dock = next(d for t, cl, d in c.els if d.get("id") == "effortDock")
    # Hidden by default.
    assert "display:none" in (dock.get("style") or "").replace(" ", ""), \
        "dock must start hidden (display:none) when no effort is selected"
    # UNBOUND: no data-effort-id stamped server-side (bound only by the JS click).
    assert dock.get("data-effort-id") is None, \
        "dock must start UNBOUND (no data-effort-id until an effort is clicked)"
    # The term host is empty server-side (no transcript/terminal pre-bound).
    term_hosts = [d for t, cl, d in c.els if d.get("id") == "dockTermHost"]
    assert len(term_hosts) == 1


def test_zero_session_project_dock_unbound(gui_env, tmp_path):
    """A zero-session project still renders the dock chrome, UNBOUND, no crash."""
    gui = gui_env
    folder = tmp_path / "Fresh"
    pid = _mkproject(folder, "Fresh")["id"]
    html = gui.render_project_window_html(pid)        # must not raise
    body = _strip(html)
    c = _parse(body)
    dock = next(d for t, cl, d in c.els if d.get("id") == "effortDock")
    assert dock.get("data-effort-id") is None
    # No effort tiles → no data-effort-id tiles either.
    tiles = [d for t, cl, d in c.els if "lane-tile" in cl]
    assert tiles == [], "zero-session project rendered effort tiles"


# ── 4. backend binding helpers ──────────────────────────────────────────────

def test_effort_index_binds_session_to_stage(gui_env, tmp_path):
    """_build_effort_index maps each effort's session ids to its effort dict
    (current_stage source for the tile + dock)."""
    gui = gui_env
    pid, fp = _multi(gui, tmp_path)
    idx = gui._build_effort_index(pid)
    assert isinstance(idx, dict)
    # The discovered efforts surface; every value carries a current_stage.
    for sid, eff in idx.items():
        assert isinstance(eff, dict)
        assert "current_stage" in eff
    # The data-attr helper emits both effort-id + current-stage for a known sid.
    if idx:
        sid = next(iter(idx))
        attrs = gui._effort_data_attrs(sid, idx)
        assert "data-effort-id=" in attrs
        assert "data-current-stage=" in attrs
    # Unknown sid → falls back to the sid as a singleton effort id, empty stage.
    attrs2 = gui._effort_data_attrs("nope-sid", idx)
    assert 'data-effort-id="nope-sid"' in attrs2
    assert 'data-current-stage=""' in attrs2
    # Empty sid → empty attrs.
    assert gui._effort_data_attrs("", idx) == ""
