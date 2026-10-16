"""v12 Wave 2 — Layout-D static skeleton render gate (render-smoke + DOM pos/neg).

Asserts the RENDERED BODY STRUCTURE of the approved Layout-D shell
(_mockups/dashboard_D_headline_shelf.html), driven by the EXISTING data
(_gather_project_sessions). The bottom dock is present but INERT; the live
effort-view + transport wiring is deferred to W10.

The render-smoke test runs BEFORE any Playwright: it asserts the page imports +
renders to a non-empty, BRACE-BALANCED string (so a leaked single `{`/`}` from
the f-string region fails fast) and carries the Layout-D landmarks.

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
    eh.record_effort(fp, pid, "research", "r3", skill="researchPrime",
                     prompt_seed="Passive decay-heat removal")
    eh.record_effort(fp, pid, "plan", "p1", skill="crucible",
                     prompt_seed="Control-stack architecture plan")
    eh.record_effort(fp, pid, "build", "b1", skill="foreman",
                     prompt_seed="Fuel-handling controller")
    # (2026-08-07) The board is the GENERAL zone now — give it sessions so the
    # positive DOM assertions (headline + shelf) have something real to pin.
    eh.record_effort(fp, pid, "general", "g1", skill="",
                     prompt_seed="General terminal session one")
    eh.record_effort(fp, pid, "general", "g2", skill="",
                     prompt_seed="General terminal session two")
    return pid, fp


def _strip(html):
    """Return the <body> with <style>/<script> removed, so CSS class definitions
    and JS function names can't satisfy a structural assertion."""
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
        cls = (d.get("class") or "").split()
        self.els.append((tag, cls, d))


def _parse(body):
    c = _Collector()
    c.feed(body)
    return c.els


# ── 1. RENDER-SMOKE (runs before any Playwright) ────────────────────────────

def test_render_smoke_balanced_braces_and_landmarks(gui_env, tmp_path):
    """render_project_window_html imports + returns a non-empty, brace-balanced
    string (no stray single `{`/`}` leaked from the f-string region) carrying the
    Layout-D landmarks."""
    gui = gui_env
    pid, _ = _multi(gui, tmp_path)
    html = gui.render_project_window_html(pid)
    assert isinstance(html, str) and html.strip(), "empty / non-str render"
    # Balance check on the RENDERED output: an f-string brace leak shows up as an
    # imbalance between literal `{` and `}` in the final page.
    assert html.count("{") == html.count("}"), (
        "brace imbalance in rendered HTML (likely an f-string `{`/`}` leak): "
        f"{html.count('{')} open vs {html.count('}')} close")
    # (2026-08-07, John's simple workbench) The trio zones are GONE server-side;
    # the General zone is the board. The landmark set pins the NEW shape.
    for landmark in ("Latest General session", "class='sectionlbl'",
                     "class='headline", "rightcol", "Grass Catcher",
                     "Deliverables", "effortDock"):
        assert landmark in html, f"missing Layout-D landmark: {landmark!r}"


# ── 2. DOM POSITIVE: the Layout-D shell IS rendered ─────────────────────────

def test_dom_positive_layoutd_shell(gui_env, tmp_path):
    gui = gui_env
    pid, _ = _multi(gui, tmp_path)
    body = _strip(gui.render_project_window_html(pid))
    els = _parse(body)
    classes = [c for _, c, _ in els]

    # exactly ONE section label: Latest General session (simple workbench)
    sectionlbls = [d for t, c, d in els if "sectionlbl" in c]
    assert len(sectionlbls) == 1, "expected one Layout-D section label (general)"

    # exactly ONE headline card (the general zone).
    headlines = [(t, c, d) for t, c, d in els if "headline" in c]
    assert len(headlines) == 1, f"expected 1 headline card, got {len(headlines)}"
    # neither headline is the empty-state placeholder (this project has sessions)
    assert all("data-empty" not in d for _, _, d in headlines)

    # the collapsible shelves: research has >1 session here so a shelf exists;
    # there are two shelf wrappers (toggle target) — at least one with minitiles.
    shelves = [d for t, c, d in els if "shelf-wrap" in c]
    assert shelves, "no collapsible shelf rendered"
    # John tweak: the older-runs shelves render COLLAPSED on first load (the
    # headline cards stay visible). Every shelf-wrap carries .collapsed, and its
    # toggle caption reads "Show all" (not "Hide").
    assert all("collapsed" in (d.get("class") or "").split() for d in shelves), \
        "older-runs shelves must render COLLAPSED by default"
    showall = [d for t, c, d in els if "showall" in c]
    assert showall, "no shelf 'Hide/Show all' toggle control"
    # collapsed default → the toggle caption reads "Show all", never "Hide".
    assert "Show all" in body, "collapsed shelf toggle must read 'Show all'"
    assert "Hide" not in body, \
        "no shelf toggle should read 'Hide' when collapsed by default"
    minitiles = [d for t, c, d in els if "minitile" in c]
    assert minitiles, "no shelf little-tiles rendered"

    # a persistent right column with a Grass mini-panel + a Deliverables panel.
    rightcols = [d for t, c, d in els if "rightcol" in c]
    assert len(rightcols) == 1, "expected one right column"
    panels = [d for t, c, d in els if "panel" in c and "panel-stack" not in c]
    # at least the Grass + Deliverables panels
    assert len(panels) >= 2, "expected Grass + Deliverables right-column panels"
    assert any("ptitle" in c for _, c, _ in els), "panels missing titles"

    # a "+ New effort" control (may be inert/labeled this wave).
    new_effort = [d for t, c, d in els if "neweffort" in " ".join(c)]
    assert new_effort, "no '+ New effort' control"

    # an INERT bottom dock region (chrome present; transport deferred to W10).
    dock = [d for t, c, d in els if "dock" in c]
    assert dock, "no bottom dock region"
    assert any(d.get("id") == "effortDock" for _, _, d in els), \
        "dock not the #effortDock element"
    # the dock carries the summary-on-top region + the draggable splitter chrome.
    assert any("dsplit" in c for _, c, _ in els), "no draggable dock splitter"
    assert any("dtop" in c for _, c, _ in els), "no dock summary-on-top region"


# ── 3. DOM NEGATIVE: zero sessions → honest empty states, no shelf, no crash ─

def test_dom_negative_zero_sessions(gui_env, tmp_path):
    gui = gui_env
    folder = tmp_path / "Fresh"
    pid = _mkproject(folder, "Fresh")["id"]
    # must not raise
    html = gui.render_project_window_html(pid)
    body = _strip(html)
    els = _parse(body)
    # still the one general zone / section label
    assert sum("sectionlbl" in c for _, c, _ in els) == 1
    # honest empty headline placeholder (no sessions) — the one general zone
    headlines = [d for t, c, d in els if "headline" in c]
    assert len(headlines) == 1
    assert all(d.get("data-empty") == "1" for d in headlines), \
        "zero-session zones must render honest empty headline placeholders"
    # NO shelf + NO little tiles when there are no older sessions
    assert not any("shelf-wrap" in c for _, c, _ in els), \
        "zero-session project rendered a shelf"
    assert not any("minitile" in c for _, c, _ in els), \
        "zero-session project rendered little-tiles"
    assert not any("showall" in c for _, c, _ in els), \
        "zero-session project rendered a Show-all toggle"
    # the right column + dock chrome still render (persistent)
    assert sum("rightcol" in c for _, c, _ in els) == 1
    assert any(d.get("id") == "effortDock" for _, _, d in els)


def test_old_p2lanes_grid_retired(gui_env, tmp_path):
    """W2 retires the 5-col .p2lanes grid in favor of Layout-D — assert the old
    board grid is gone from the rendered body."""
    gui = gui_env
    pid, _ = _multi(gui, tmp_path)
    body = _strip(gui.render_project_window_html(pid))
    els = _parse(body)
    assert not any("p2lanes" in c for _, c, _ in els), \
        "old .p2lanes grid still rendered (W2 should replace it with Layout-D)"


def test_layoutd_plan_build_headline_is_newest_effort():
    """Reviewer F1: the Plan/Build headline must be the NEWEST effort across the
    merged plan+build lanes — not 'all plans then all builds'. Fails against the
    pre-fix code where effort views had no epoch (_sv_created_at→0.0)."""
    import importlib
    ag = importlib.import_module("anchor_gui")
    # older plan (100) + newer build (200) → the build is the headline
    sbl = {
        "research": [],
        "plan":  [{"session_id": "p1", "members": [{"_eff_created_at": 100.0, "trio_lane": "plan"}]}],
        "build": [{"session_id": "b1", "members": [{"_eff_created_at": 200.0, "trio_lane": "build"}]}],
    }
    z = ag._layoutd_zones("/x", "pid", sessions_by_lane=sbl)
    assert z["plan_build"][0]["session_id"] == "b1", "newest (build) must be headline"
    # reverse: newer plan (300) + older build (50) → the plan is the headline
    sbl2 = {
        "research": [],
        "plan":  [{"session_id": "p2", "members": [{"_eff_created_at": 300.0, "trio_lane": "plan"}]}],
        "build": [{"session_id": "b2", "members": [{"_eff_created_at": 50.0, "trio_lane": "build"}]}],
    }
    z2 = ag._layoutd_zones("/x", "pid", sessions_by_lane=sbl2)
    assert z2["plan_build"][0]["session_id"] == "p2", "newest (plan) must be headline"


def test_minitile_emits_effort_managed_attr():
    """W7-R2-01: a Layout-D tile for an effort_managed session carries
    data-effort-managed="1" so the JS advance-bar retirement guard goes live; a
    legacy session omits it."""
    import importlib
    ag = importlib.import_module("anchor_gui")
    rv = ag._registry_session_view({"session_id": "s1", "lane": "research",
                                    "status": "running", "label": "x",
                                    "effort_managed": True})
    assert rv["effort_managed"] is True
    html = ag._render_layoutd_minitile({"session_id": "s1", "members": [rv]},
                                       "research", "pid", "/x", "research")
    assert 'data-effort-managed="1"' in html
    rv2 = ag._registry_session_view({"session_id": "s2", "lane": "research",
                                     "status": "running", "label": "y",
                                     "effort_managed": False})
    html2 = ag._render_layoutd_minitile({"session_id": "s2", "members": [rv2]},
                                        "research", "pid", "/x", "research")
    assert "data-effort-managed" not in html2


def test_grass_mini_panel_has_collapse_toggle():
    """John tweak: the right-column Grass Catcher panel can COLLAPSE its idea list
    in the tile (a caret toggle) while keeping +capture / Open-workbench reachable."""
    import importlib
    ag = importlib.import_module("anchor_gui")
    html = ag._render_layoutd_grass_panel(".", "no-such-project")
    assert "id='grassMiniTog'" in html and "toggleGrassMini(" in html, \
        "grass panel missing the collapse toggle"
    assert "id='grassMiniList'" in html, "grass idea list not in a collapsible container"
    # John tweak: the Grass idea list is COLLAPSED on first load (server-rendered
    # .collapsed + the ▸ caret) so the dashboard is minimal with no flash.
    assert "grass-mini-list collapsed" in html, \
        "grass idea list must render COLLAPSED by default"
    assert "&#9656;</span>" in html, "collapsed grass caret (▸) missing"
    assert "openGrassWorkbench()" in html, "Open-workbench must stay reachable"
    assert "function toggleGrassMini" in ag._PROJECT_WINDOW_JS, "toggle JS missing"
