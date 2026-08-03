"""Gandalf v1 Wave 3 — the white-wizard Gandalf tab (render-smoke + DOM pos/neg).

Asserts the RENDERED BODY STRUCTURE of the right-column Gandalf panel
(_mockups/gandalf_tab.html): the panel header (icon + "Gandalf" + Re-run), the
newest-first run rows with verdict + ts + grade chips + report/raw-JSON links,
clicking-row markup (the expandable exec body), an honest error row (reason text
+ NO /artifact link), and the honest empty state. The panel must render BEFORE
the Grass panel in the right column (decision #5).

The render reads the index ONLY (never a model call). To seed runs hermetically
we write the index directly through gandalf's internal store (no stubs needed for
a pure read test).

Hermetic: temp data/project dirs, stub PTY, never :8777, never real data / model.
"""
import importlib
import json
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
                "effort_history", "summarizer", "gandalf"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import anchor_gui
    yield importlib.reload(anchor_gui)


def _mkproject(folder, name="P"):
    import rnd_registry
    folder.mkdir(parents=True, exist_ok=True)
    return rnd_registry.add_project(name, str(folder))


def _seed_run(folder, pid, **over):
    """Append one index record directly through gandalf's store (a pure read
    test needs no model/host stub)."""
    import gandalf
    rec = {
        "schema_version": gandalf.GANDALF_INDEX_SCHEMA_VERSION,
        "run_id": over.get("run_id", "run-1700000000000"),
        "ts": over.get("ts", 1700000000.0),
        "ok": over.get("ok", True),
        "verdict": over.get("verdict", "Sound core, build handoff is the risk."),
        "degraded": over.get("degraded", True),
        "cross_model": over.get("cross_model", False),
        "report_rel": over.get("report_rel", "gandalf/run-1700000000000/report.md"),
        "exec_rel": over.get("exec_rel",
                             "gandalf/run-1700000000000/exec-summary.md"),
        "advisor_rel": over.get("advisor_rel",
                                "gandalf/run-1700000000000/advisor-output.json"),
    }
    if "reason" in over:
        rec["reason"] = over["reason"]
    gandalf._append_index(str(folder), pid, rec)


def _strip(html):
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


# ── 1. RENDER-SMOKE ─────────────────────────────────────────────────────────

def test_render_smoke_brace_balanced_and_panel_present(gui_env, tmp_path):
    gui = gui_env
    folder = tmp_path / "Smoke"
    pid = _mkproject(folder, "Smoke")["id"]
    _seed_run(folder, pid)
    html = gui.render_project_window_html(pid)
    assert isinstance(html, str) and html.strip()
    assert html.count("{") == html.count("}"), (
        f"brace imbalance: {html.count('{')} open vs {html.count('}')} close")
    for landmark in ("id='gandalfPanel'", "gandalf-icon-v5.jpg", "gandalfRun(",
                     "gandalfToggleRun", "toggleGandalfRuns", "id='gandalfRunsTog'"):
        assert landmark in html, f"missing Gandalf landmark: {landmark!r}"


# ── 2. DOM POSITIVE — panel present, ABOVE grass, rows/chips/links ──────────

def test_dom_positive_panel_above_grass_with_rows(gui_env, tmp_path):
    gui = gui_env
    folder = tmp_path / "Has"
    pid = _mkproject(folder, "Has")["id"]
    # two OK runs (one cross_model=False single-family, one a degraded run)
    _seed_run(folder, pid, run_id="run-2", ts=1700000200.0,
              verdict="This is sound — one promising elevation worth pursuing.")
    _seed_run(folder, pid, run_id="run-1", ts=1700000100.0, degraded=True)
    body = _strip(gui.render_project_window_html(pid))
    els = _parse(body)

    # The panel exists.
    panels = [d for t, c, d in els if d.get("id") == "gandalfPanel"]
    assert len(panels) == 1, "expected exactly one Gandalf panel"

    # The Gandalf panel comes BEFORE the grass panel in the rendered HTML.
    i_g = body.index("id='gandalfPanel'") if "id='gandalfPanel'" in body \
        else body.index('id="gandalfPanel"')
    assert "Grass Catcher" in body
    assert i_g < body.index("Grass Catcher"), \
        "Gandalf panel must render ABOVE the Grass panel"

    # Header: the white-wizard icon + a Re-run button.
    imgs = [d for t, c, d in els if t == "img" and "gicon" in c]
    assert imgs and "gandalf-icon-v5.jpg" in imgs[0].get("src", "")
    reruns = [d for t, c, d in els if "gandalf-rerun" in c]
    assert reruns, "no Re-run button"

    # John tweak: the run list is COLLAPSED on first load (server-rendered
    # .collapsed on #gandalfRuns) with a header caret toggle, so the dashboard is
    # minimal with no flash of expanded content before JS.
    gruns = [d for t, c, d in els if d.get("id") == "gandalfRuns"]
    assert gruns and "collapsed" in (gruns[0].get("class") or "").split(), \
        "Gandalf run list must render COLLAPSED by default"
    togs = [d for t, c, d in els if d.get("id") == "gandalfRunsTog"]
    assert togs and "gmini-tog" in (togs[0].get("class") or "").split(), \
        "Gandalf header collapse toggle missing"

    # Two run rows.
    runs = [(t, c, d) for t, c, d in els if "grun" in c]
    assert len(runs) == 2, f"expected 2 run rows, got {len(runs)}"

    # Grade chips present (Speculative + single-family for cross_model:false).
    chip_classes = [c for t, c, d in els if "chip" in c]
    flat = " ".join(" ".join(c) for c in chip_classes)
    assert "spec" in flat, "no Speculative chip"
    assert "sf" in flat, "no single-family chip"

    # Report + raw-JSON /artifact links present for OK runs.
    links = [d for t, c, d in els if t == "a" and "/artifact/" in (d.get("href") or "")]
    assert len(links) >= 2, "missing Full report / raw JSON /artifact links"


def test_dom_run_row_carries_exec_rel_for_inline_expand(gui_env, tmp_path):
    gui = gui_env
    folder = tmp_path / "Exec"
    pid = _mkproject(folder, "Exec")["id"]
    _seed_run(folder, pid)
    body = _strip(gui.render_project_window_html(pid))
    els = _parse(body)
    runs = [d for t, c, d in els if "grun" in c]
    assert runs and runs[0].get("data-exec-rel"), \
        "OK run row must carry data-exec-rel for the inline exec-summary fetch"


# ── 3. DOM NEGATIVE — honest empty state + honest error row (no dead links) ──

def test_dom_negative_empty_state(gui_env, tmp_path):
    gui = gui_env
    folder = tmp_path / "Empty"
    pid = _mkproject(folder, "Empty")["id"]
    body = _strip(gui.render_project_window_html(pid))
    els = _parse(body)
    # The panel still renders.
    assert any(d.get("id") == "gandalfPanel" for t, c, d in els)
    # An honest empty state, no run rows.
    assert any("gandalf-empty" in c for t, c, d in els), "no empty-state element"
    assert "No Gandalf read yet" in body
    assert not [d for t, c, d in els if "grun" in c], \
        "empty state must render zero run rows"
    # A Run button is offered.
    assert any("gandalf-run" in c for t, c, d in els)


def test_dom_negative_error_run_has_reason_no_dead_links(gui_env, tmp_path):
    gui = gui_env
    folder = tmp_path / "Err"
    pid = _mkproject(folder, "Err")["id"]
    _seed_run(folder, pid, run_id="run-err", ok=False, verdict="",
              report_rel=None, exec_rel=None, advisor_rel=None,
              reason="host-unavailable")
    body = _strip(gui.render_project_window_html(pid))
    els = _parse(body)
    # One run row, marked an error verdict.
    runs = [(t, c, d) for t, c, d in els if "grun" in c]
    assert len(runs) == 1
    err_verdicts = [c for t, c, d in els if "verdict" in c and "err" in c]
    assert err_verdicts, "error run must render the .verdict.err one-liner"
    assert "host-unavailable" in body, "the honest reason text must be shown"
    # An Error chip, and NO /artifact links (no dead links on an error run).
    chip_flat = " ".join(" ".join(c) for t, c, d in els if "chip" in c)
    assert "deg" in chip_flat, "error run must carry an Error chip"
    links = [d for t, c, d in els
             if t == "a" and "/artifact/" in (d.get("href") or "")]
    assert not links, "error run must have NO /artifact links (no dead links)"
    # The row also carries no exec-rel (nothing to fetch).
    assert not runs[0][2].get("data-exec-rel"), \
        "error run row must not carry data-exec-rel"
    # John tweak: an error run is NON-EXPANDABLE — it carries the .err-row class,
    # NO expand caret, NO gandalfToggleRun onclick, and NO empty body box.
    assert "err-row" in runs[0][1], "error run must carry the .err-row class"
    assert not any("gcaret" in c for t, c, d in els), \
        "error run must NOT render an expand caret"
    assert not any("gbody" in c for t, c, d in els), \
        "error run must NOT render an (empty) expandable body box"
    # the error row markup must not wire the row-expand click handler.
    import re as _re
    err_seg = _re.search(
        r"<div class='grun err-row'[\s\S]*?</div></div>", _strip(
            gui.render_project_window_html(pid)))
    assert err_seg, "error row markup not found"
    assert "onclick='gandalfToggleRun" not in err_seg.group(0), \
        "error run row must NOT wire gandalfToggleRun"
    assert "gcaret" not in err_seg.group(0), \
        "error run row must NOT render an expand caret"


# ── 4. DASHBOARD CARD — Gandalf in-flight badge + bulk poller wiring ─────────

def _sample_project(name="Alpha", **over):
    p = {"name": name, "domain": "academic", "priority": 1, "status": "active",
         "effort": "high", "due": "", "next": "", "collabs": "", "notes": ""}
    p.update(over)
    return p


def test_dashboard_card_has_gandalf_badge_and_controller(gui_env):
    """The dashboard project card carries the (hidden) Gandalf status badge and
    the page wires the bulk-status poller against the new endpoint."""
    gui = gui_env
    html = gui.generate_html([_sample_project()], [], [])
    assert isinstance(html, str) and html.strip()
    # Brace balance — the giant f-string must stay balanced after the edit.
    assert html.count("{") == html.count("}"), "brace imbalance in generate_html"
    # The badge element is present on the card (hidden until a run is in-flight).
    assert "gandalf-card-status" in html
    assert "gcs-text" in html and "gcs-spin" in html
    # The JS controller + the bulk endpoint are wired into the page.
    assert "/api/rnd/gandalf_status_all" in html
    for fn in ("_gandalfCardStart", "_gandalfCardStop", "_gandalfCardTick",
               "_gandalfCardApply"):
        assert fn in html, f"missing dashboard Gandalf controller fn: {fn}"


def test_dashboard_card_carries_project_id_for_registered_project(gui_env, tmp_path):
    """A dashboard project whose NAME matches a registered R&D project gets a
    data-project-id on its card so the poller can target it; an unknown name
    gets none."""
    gui = gui_env
    proj = _mkproject(tmp_path / "Bridged", "Bridged")
    pid = proj["id"]
    html = gui.generate_html(
        [_sample_project("Bridged"), _sample_project("Unregistered-XYZ")], [], [])
    assert f'data-project-id="{pid}"' in html, \
        "registered project card must carry its R&D project_id"
    # The unknown project gets a card but no data-project-id attribute.
    assert "Unregistered-XYZ" in html


def test_list_runs_safe_projection_no_abs_paths(gui_env, tmp_path):
    """Guard: list_runs (the data the panel renders) never leaks an absolute
    path."""
    import gandalf
    folder = tmp_path / "Safe"
    pid = _mkproject(folder, "Safe")["id"]
    _seed_run(folder, pid)
    for r in gandalf.list_runs(str(folder), pid):
        for v in r.values():
            if isinstance(v, str):
                assert ":\\" not in v
                assert str(folder) not in v
