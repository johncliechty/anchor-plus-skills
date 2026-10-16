"""v5 Wave 4 gate — deliverable PER FOREMAN BUILD (resolve · backfill · render).

North-Star contract (MASTER-PLAN Locked Decision #4 / Risk R4, IMPLEMENTATION-PLAN
Wave 4):

  - ``deliverables.resolve_build_deliverable(folder, pid, build_session)`` resolves
    the artifact a build produced from EXPLICIT signals only (doc-role / product
    member / pinned-or-declared / Anchor.md marker / [opt-in] foreman.config). When
    NO explicit signal exists, or the signal is AMBIGUOUS, it returns
    ``resolved=False`` with an honest reason — NEVER a fabricated path (Risk R4).
  - ``deliverables.backfill_build_deliverables`` scans a project's build sessions,
    auto-pins the unambiguously resolved ones (idempotent / content-addressed), and
    leaves unresolvable builds unpinned.
  - The Deliverables LANE lists backfilled build deliverables; a BUILD session's
    PANEL shows its resolved deliverable (or an honest "none yet" placeholder).

Hermetic gate (the v4.1 model): unit tests + rendered-DOM (style/script stripped,
positive + negative) + a real Playwright/Chromium interaction test. Never :8777,
never real data — stub PTY backend, temp data dir, stub runner. NEVER fabricates a
deliverable.
"""
import importlib
import json
import re
import threading
from html.parser import HTMLParser
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()


# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def mods(tmp_path, monkeypatch):
    """Reload the deliverables stack against a temp data dir + stub runner."""
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    for mod in ("paths", "job_runner", "rnd_registry", "effort_history",
                "sessions", "report_viewer", "summarizer", "deliverables"):
        importlib.reload(importlib.import_module(mod))
    import rnd_registry, effort_history, sessions, deliverables
    return rnd_registry, effort_history, sessions, deliverables


@pytest.fixture
def gui_env(tmp_path, monkeypatch):
    """Reload anchor_gui against a temp data dir + stub PTY + stub runner."""
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    for mod in ("paths", "job_runner", "rnd_registry", "lanes",
                "effort_history", "sessions", "summarizer", "deliverables",
                "gate_adapter"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import anchor_gui
    yield importlib.reload(anchor_gui)


def _mkproject(rnd, folder, name="Build"):
    folder.mkdir(parents=True, exist_ok=True)
    return rnd.add_project(name, str(folder))["id"]


def _build_session_with_product(eh, sessions, folder, pid,
                                 product="dist/app.exe"):
    """A discovered BUILD session whose members are a north-star (plan/log doc)
    PLUS a single product artifact → resolves via the build-output signal."""
    (folder / Path(product)).parent.mkdir(parents=True, exist_ok=True)
    (folder / Path(product)).write_text("binary-ish", encoding="utf-8")
    base = "build/run-A"
    eh.record_effort(folder, pid, "build", eh.discovered_job_id("build",
                     f"{base}/NORTH-STAR.md"),
                     skill="foreman",
                     extra={"source": eh.SOURCE_DISCOVERED,
                            "artifact_path": f"{base}/NORTH-STAR.md",
                            "title": "North Star", "kind": "northstar"})
    eh.record_effort(folder, pid, "build", eh.discovered_job_id("build",
                     product),
                     skill="foreman",
                     extra={"source": eh.SOURCE_DISCOVERED,
                            "artifact_path": product,
                            "title": Path(product).name, "kind": "deliverable"})
    # the session id == the discovered group key for parent dir "build/run-A"
    # only if the product shares that dir; here the product lives elsewhere so the
    # two efforts form two sessions. Use the parent-dir session for the build.
    for s in sessions.list_sessions(folder, pid, "build"):
        for m in s.get("member_files", []):
            if (m.get("artifact_path") or "") == product:
                return s
    return None


# ── (1) resolve_build_deliverable — per signal, honest when none ─────────────

def test_resolve_from_pinned(mods, tmp_path):
    rnd, eh, sessions, deliv = mods
    folder = tmp_path / "P"
    pid = _mkproject(rnd, folder)
    (folder / "anchor_gui.py").write_text("# app\n", encoding="utf-8")
    deliv.pin_deliverable(folder, pid, "anchor_gui.py", name="anchor_gui.py",
                          dtype=deliv.TYPE_PROGRAM)
    # a build session with only a plan/log doc (no product member) → falls
    # through to the existing pinned deliverable.
    eh.record_effort(folder, pid, "build",
                     eh.discovered_job_id("build", "build/r/NORTH-STAR.md"),
                     skill="foreman",
                     extra={"source": eh.SOURCE_DISCOVERED,
                            "artifact_path": "build/r/NORTH-STAR.md",
                            "title": "North Star", "kind": "northstar"})
    bs = sessions.list_sessions(folder, pid, "build")[0]
    res = deliv.resolve_build_deliverable(folder, pid, bs)
    assert res["resolved"] is True
    assert res["signal"] in ("pinned", "doc-role")
    assert "anchor_gui" in res["deliverable"]["path"]


def test_multi_build_does_not_misattribute_project_pin(mods, tmp_path):
    """REGRESSION (adversarial Wave-4 BLOCKER): with MORE THAN ONE build session,
    a project-level pin must NOT be attributed to a build that did not produce it
    (the old code claimed the project's newest pin / doc-role for EVERY build).
    Build A produces widgetA.py (its own member); build B produces only a log doc.
    B must resolve to NOTHING (honest), never to widgetA.py or the project pin."""
    rnd, eh, sessions, deliv = mods
    folder = tmp_path / "P"
    pid = _mkproject(rnd, folder)
    # Build A: a real product member under build/run-A.
    (folder / "build" / "run-A").mkdir(parents=True, exist_ok=True)
    (folder / "build" / "run-A" / "NORTH-STAR.md").write_text("ns\n", "utf-8")
    (folder / "build" / "run-A" / "widgetA.py").write_text("# A\n", "utf-8")
    for fn, kind in (("NORTH-STAR.md", "northstar"), ("widgetA.py", "build")):
        eh.record_effort(folder, pid, "build",
                         eh.discovered_job_id("build", f"build/run-A/{fn}"),
                         skill="foreman",
                         extra={"source": eh.SOURCE_DISCOVERED,
                                "artifact_path": f"build/run-A/{fn}",
                                "title": fn, "kind": kind})
    # Build B: ONLY a log doc — no product.
    eh.record_effort(folder, pid, "build",
                     eh.discovered_job_id("build", "build/run-B/EXECUTION-LOG.md"),
                     skill="foreman",
                     extra={"source": eh.SOURCE_DISCOVERED,
                            "artifact_path": "build/run-B/EXECUTION-LOG.md",
                            "title": "Execution Log", "kind": "execlog"})
    # Also a project-level pin that belongs to NEITHER specific build.
    (folder / "anchor_gui.py").write_text("# app\n", encoding="utf-8")
    deliv.pin_deliverable(folder, pid, "anchor_gui.py", name="anchor_gui.py",
                          dtype=deliv.TYPE_PROGRAM)
    sess = sessions.list_sessions(folder, pid, "build")
    by_member = {}
    for s in sess:
        for m in s.get("member_files", []):
            by_member[(m.get("artifact_path") or "")] = s
    bsA = by_member["build/run-A/widgetA.py"]
    bsB = by_member["build/run-B/EXECUTION-LOG.md"]
    resA = deliv.resolve_build_deliverable(folder, pid, bsA)
    resB = deliv.resolve_build_deliverable(folder, pid, bsB)
    # A resolves to ITS OWN product; B is honestly unresolved (NOT widgetA / pin).
    assert resA["resolved"] is True
    assert resA["deliverable"]["path"] == "build/run-A/widgetA.py"
    assert resB["resolved"] is False
    assert resB["deliverable"] is None
    assert "anchor_gui" not in (resB.get("reason") or "")


def test_single_build_resolves_from_project_pin(mods, tmp_path):
    """A SINGLE-build project may attribute the project pin to that lone build
    (unambiguous) — the plan's 'pinned path' signal, kept for the common case."""
    rnd, eh, sessions, deliv = mods
    folder = tmp_path / "P"
    pid = _mkproject(rnd, folder)
    (folder / "anchor_gui.py").write_text("# app\n", encoding="utf-8")
    deliv.pin_deliverable(folder, pid, "anchor_gui.py", name="anchor_gui.py",
                          dtype=deliv.TYPE_PROGRAM)
    eh.record_effort(folder, pid, "build",
                     eh.discovered_job_id("build", "build/r/EXECUTION-LOG.md"),
                     skill="foreman",
                     extra={"source": eh.SOURCE_DISCOVERED,
                            "artifact_path": "build/r/EXECUTION-LOG.md",
                            "title": "Execution Log", "kind": "execlog"})
    bs = sessions.list_sessions(folder, pid, "build")[0]
    res = deliv.resolve_build_deliverable(folder, pid, bs)
    assert res["resolved"] is True
    assert res["signal"] == "pinned"
    assert "anchor_gui" in res["deliverable"]["path"]


def test_resolve_from_build_output_member(mods, tmp_path):
    rnd, eh, sessions, deliv = mods
    folder = tmp_path / "P"
    pid = _mkproject(rnd, folder)
    (folder / "build" / "run-A").mkdir(parents=True, exist_ok=True)
    (folder / "build" / "run-A" / "NORTH-STAR.md").write_text("ns\n",
                                                              encoding="utf-8")
    (folder / "build" / "run-A" / "widget.py").write_text("# widget\n",
                                                           encoding="utf-8")
    for fn, kind in (("NORTH-STAR.md", "northstar"), ("widget.py", "build")):
        eh.record_effort(folder, pid, "build",
                         eh.discovered_job_id("build", f"build/run-A/{fn}"),
                         skill="foreman",
                         extra={"source": eh.SOURCE_DISCOVERED,
                                "artifact_path": f"build/run-A/{fn}",
                                "title": fn, "kind": kind})
    bs = sessions.list_sessions(folder, pid, "build")[0]
    res = deliv.resolve_build_deliverable(folder, pid, bs)
    assert res["resolved"] is True
    assert res["signal"] == "build-output"
    assert res["deliverable"]["path"] == "build/run-A/widget.py"


def test_resolve_from_anchor_md_marker(mods, tmp_path):
    rnd, eh, sessions, deliv = mods
    folder = tmp_path / "P"
    pid = _mkproject(rnd, folder)
    (folder / "myapp.py").write_text("# app\n", encoding="utf-8")
    (folder / "Anchor.md").write_text(
        "# Anchor\n\n## Deliverables\n\n- `myapp.py` — program — the app\n",
        encoding="utf-8")
    eh.record_effort(folder, pid, "build",
                     eh.discovered_job_id("build", "build/r/NORTH-STAR.md"),
                     skill="foreman",
                     extra={"source": eh.SOURCE_DISCOVERED,
                            "artifact_path": "build/r/NORTH-STAR.md",
                            "title": "North Star", "kind": "northstar"})
    bs = sessions.list_sessions(folder, pid, "build")[0]
    res = deliv.resolve_build_deliverable(folder, pid, bs)
    assert res["resolved"] is True
    assert res["signal"] == "marker"
    assert res["deliverable"]["path"] == "myapp.py"


def test_unresolved_when_no_signal_does_not_fabricate(mods, tmp_path):
    rnd, eh, sessions, deliv = mods
    folder = tmp_path / "P"
    pid = _mkproject(rnd, folder)
    # a build session with ONLY plan/log docs → nothing to deliver, nothing
    # pinned, no marker → honest unresolved (never a fabricated path).
    for fn, kind in (("NORTH-STAR.md", "northstar"),
                     ("EXECUTION-LOG.md", "execlog")):
        eh.record_effort(folder, pid, "build",
                         eh.discovered_job_id("build", f"build/r/{fn}"),
                         skill="foreman",
                         extra={"source": eh.SOURCE_DISCOVERED,
                                "artifact_path": f"build/r/{fn}",
                                "title": fn, "kind": kind})
    bs = sessions.list_sessions(folder, pid, "build")[0]
    res = deliv.resolve_build_deliverable(folder, pid, bs)
    assert res["resolved"] is False
    assert res["deliverable"] is None
    assert res["reason"]                       # an honest reason is present
    assert "fabricat" not in res["reason"].lower()


def test_ambiguous_is_unresolved_not_guessed(mods, tmp_path):
    rnd, eh, sessions, deliv = mods
    folder = tmp_path / "P"
    pid = _mkproject(rnd, folder)
    # TWO unrelated product members in one session, nothing pinned/declared →
    # ambiguous → unresolved (NOT a guess between them).
    for fn, kind in (("alpha.py", "build"), ("beta.py", "build")):
        eh.record_effort(folder, pid, "build",
                         eh.discovered_job_id("build", f"build/r/{fn}"),
                         skill="foreman",
                         extra={"source": eh.SOURCE_DISCOVERED,
                                "artifact_path": f"build/r/{fn}",
                                "title": fn, "kind": kind})
    bs = sessions.list_sessions(folder, pid, "build")[0]
    res = deliv.resolve_build_deliverable(folder, pid, bs)
    assert res["resolved"] is False
    assert res["signal"] == "ambiguous"
    assert res["deliverable"] is None


# ── (2) backfill — auto-pin unambiguous; leave unresolved alone; idempotent ──

def test_backfill_auto_pins_resolvable_idempotent(mods, tmp_path):
    rnd, eh, sessions, deliv = mods
    folder = tmp_path / "P"
    pid = _mkproject(rnd, folder)
    (folder / "build" / "run-A").mkdir(parents=True, exist_ok=True)
    (folder / "build" / "run-A" / "NORTH-STAR.md").write_text("ns\n",
                                                              encoding="utf-8")
    (folder / "build" / "run-A" / "widget.py").write_text("# w\n",
                                                          encoding="utf-8")
    for fn, kind in (("NORTH-STAR.md", "northstar"), ("widget.py", "build")):
        eh.record_effort(folder, pid, "build",
                         eh.discovered_job_id("build", f"build/run-A/{fn}"),
                         skill="foreman",
                         extra={"source": eh.SOURCE_DISCOVERED,
                                "artifact_path": f"build/run-A/{fn}",
                                "title": fn, "kind": kind})
    out1 = deliv.backfill_build_deliverables(folder, pid)
    assert out1["scanned"] >= 1
    assert len(out1["pinned"]) == 1
    pins1 = deliv.list_pinned_deliverables(folder, pid)
    assert any((p.get("artifact_path") or "") == "build/run-A/widget.py"
               for p in pins1)

    # IDEMPOTENT: a second backfill adds NO new pin (content-addressed).
    deliv.backfill_build_deliverables(folder, pid)
    pins2 = deliv.list_pinned_deliverables(folder, pid)
    widget_pins = [p for p in pins2
                   if (p.get("artifact_path") or "") == "build/run-A/widget.py"]
    assert len(widget_pins) == 1, "backfill duplicated the pin"


def test_backfill_leaves_unresolvable_unpinned(mods, tmp_path):
    rnd, eh, sessions, deliv = mods
    folder = tmp_path / "P"
    pid = _mkproject(rnd, folder)
    for fn, kind in (("NORTH-STAR.md", "northstar"),
                     ("EXECUTION-LOG.md", "execlog")):
        eh.record_effort(folder, pid, "build",
                         eh.discovered_job_id("build", f"build/r/{fn}"),
                         skill="foreman",
                         extra={"source": eh.SOURCE_DISCOVERED,
                                "artifact_path": f"build/r/{fn}",
                                "title": fn, "kind": kind})
    out = deliv.backfill_build_deliverables(folder, pid)
    assert out["pinned"] == []
    assert out["unresolved"]                   # the build is reported unresolved
    assert deliv.list_pinned_deliverables(folder, pid) == []


# ── (3) rendered-DOM (style/script stripped, positive + negative) ────────────

def _strip(html):
    """Remove <style>/<script> so CSS class definitions and JS function names
    can't satisfy a structural assertion. We keep the WHOLE stripped document
    (not a <body> slice) because the cockpit page emits multiple <script> blocks
    and a body-slice would truncate the lane board out of view."""
    b = re.sub(r"<style[\s\S]*?</style>", "", html)
    b = re.sub(r"<script[\s\S]*?</script>", "", b)
    return b


def _setup_build_with_output(gui, rnd, eh, folder, name="WithDeliv"):
    pid = rnd.add_project(name, str(folder))["id"]
    (folder / "build" / "run-A").mkdir(parents=True, exist_ok=True)
    (folder / "build" / "run-A" / "NORTH-STAR.md").write_text("ns\n",
                                                              encoding="utf-8")
    (folder / "build" / "run-A" / "widget.py").write_text("# w\n",
                                                          encoding="utf-8")
    for fn, kind in (("NORTH-STAR.md", "northstar"), ("widget.py", "build")):
        eh.record_effort(folder, pid, "build",
                         eh.discovered_job_id("build", f"build/run-A/{fn}"),
                         skill="foreman",
                         extra={"source": eh.SOURCE_DISCOVERED,
                                "artifact_path": f"build/run-A/{fn}",
                                "title": fn, "kind": kind})
    return pid


def test_deliverables_lane_lists_backfilled_build_deliverable(gui_env, tmp_path):
    gui = gui_env
    import rnd_registry as rnd, effort_history as eh
    folder = tmp_path / "P"
    folder.mkdir(parents=True, exist_ok=True)
    pid = _setup_build_with_output(gui, rnd, eh, folder)
    body = _strip(gui.render_project_window_html(pid))
    # the window render runs backfill → the widget is now a pinned deliverable
    # tile in the Deliverables lane.
    assert "deliv-pinned" in body
    assert "widget.py" in body
    # the "no deliverables" placeholder must NOT be the lane content.
    assert "No deliverables pinned yet" not in body


def test_build_panel_endpoint_resolves_and_honest_placeholder(gui_env, tmp_path):
    gui = gui_env
    import rnd_registry as rnd, effort_history as eh
    import sessions as _sessions
    import deliverables as deliv
    # (a) a build with a product → resolved.
    folder = tmp_path / "P1"
    folder.mkdir(parents=True, exist_ok=True)
    pid = _setup_build_with_output(gui, rnd, eh, folder)
    bs = next(s for s in _sessions.list_sessions(folder, pid, "build")
              for m in s.get("member_files", [])
              if (m.get("artifact_path") or "") == "build/run-A/widget.py")
    res = deliv.resolve_build_deliverable(folder, pid, bs)
    assert res["resolved"] and res["deliverable"]["path"] == "build/run-A/widget.py"

    # (b) a build with ONLY plan docs → honest placeholder (unresolved).
    folder2 = tmp_path / "P2"
    folder2.mkdir(parents=True, exist_ok=True)
    pid2 = rnd.add_project("NoDeliv", str(folder2))["id"]
    eh.record_effort(folder2, pid2, "build",
                     eh.discovered_job_id("build", "build/r/NORTH-STAR.md"),
                     skill="foreman",
                     extra={"source": eh.SOURCE_DISCOVERED,
                            "artifact_path": "build/r/NORTH-STAR.md",
                            "title": "North Star", "kind": "northstar"})
    bs2 = _sessions.list_sessions(folder2, pid2, "build")[0]
    res2 = deliv.resolve_build_deliverable(folder2, pid2, bs2)
    assert res2["resolved"] is False and res2["deliverable"] is None


def test_no_resolvable_build_lane_shows_placeholder(gui_env, tmp_path):
    gui = gui_env
    import rnd_registry as rnd, effort_history as eh
    folder = tmp_path / "Empty"
    folder.mkdir(parents=True, exist_ok=True)
    pid = rnd.add_project("Empty", str(folder))["id"]
    eh.record_effort(folder, pid, "build",
                     eh.discovered_job_id("build", "build/r/NORTH-STAR.md"),
                     skill="foreman",
                     extra={"source": eh.SOURCE_DISCOVERED,
                            "artifact_path": "build/r/NORTH-STAR.md",
                            "title": "North Star", "kind": "northstar"})
    body = _strip(gui.render_project_window_html(pid))
    # No pinned/declared/marker/product → the lane shows the honest placeholder,
    # never a fabricated deliverable tile.
    assert "No deliverables pinned yet" in body
    assert "deliv-pinned" not in body


# ── (4) real Playwright + Chromium (skips cleanly when absent) ───────────────

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


def _discovered_build_project(rnd, folder, name, product=None):
    """A project whose BUILD session is DISCOVERED the real way (a
    ``foreman.config.json`` → the brownfield scanner classifies it into the build
    lane), so it SURVIVES the ``/project/<id>`` discover-and-adopt rescan. When
    ``product`` is given, that real product file is PINNED as a deliverable (a
    ``.anchor`` pin record survives the rescan, unlike a hand-written Anchor.md
    marker which ``write_anchor_md`` rewrites) → the build deliverable resolves
    via the pinned / doc-role signal (the realistic "what this build produced"
    path)."""
    import brownfield_scan, effort_history as eh, deliverables as deliv
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "foreman.config.json").write_text(
        '{"project": "%s", "docs": {}}' % name, encoding="utf-8")
    pid = rnd.add_project(name, str(folder))["id"]
    eh.adopt_discovered(str(folder), pid, brownfield_scan.scan(str(folder)))
    if product:
        (folder / product).write_text("# product\n", encoding="utf-8")
        deliv.pin_deliverable(str(folder), pid, product, name=product,
                              dtype=deliv.TYPE_PROGRAM)
    return pid


def test_build_deliverable_in_lane_and_panel_playwright(server, tmp_path):
    """Real browser: a build that produced an artifact shows the deliverable in
    the Deliverables LANE and, on opening the build session's panel, INSIDE the
    panel; and a build with no resolvable deliverable shows the honest
    placeholder in its panel. No JS console errors. Uses discovery-surviving
    build sessions (foreman.config.json) so the server's discover-and-adopt
    rescan keeps them."""
    pytest.importorskip("playwright.sync_api")
    gui, base, _ = server
    import rnd_registry as rnd

    # project A: a discovered build session + a pinned product deliverable → the
    # build deliverable resolves (pinned/doc-role) and the lane lists it.
    folderA = tmp_path / "HasDeliv"
    pidA = _discovered_build_project(rnd, folderA, "HasDeliv",
                                     product="myapp.py")

    # project B: a discovered build session with NO marker/pin/product →
    # honest "no deliverable pinned yet" placeholder.
    folderB = tmp_path / "NoDeliv"
    pidB = _discovered_build_project(rnd, folderB, "NoDeliv")

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        errors = []
        pg.on("console",
              lambda m: errors.append(m.text) if m.type == "error" else None)

        # ── project A: deliverables panel lists it + panel shows it ──
        pg.goto(f"{base}/project/{pidA}", wait_until="networkidle")
        from tests.ui_helpers import expand_workbench
        expand_workbench(pg)  # the Workbench tile now opens collapsed
        # v12 Wave 2: the Deliverables panel lives in the Layout-D right column;
        # the board grid is .pgrid.layoutd (covers left + right columns).
        lane_html = pg.inner_html(".pgrid.layoutd")
        assert "myapp.py" in lane_html, \
            "build deliverable missing from the Deliverables panel"
        # v12 W10: clicking the build effort tile opens the SINGLE bottom DOCK
        # (its tile is the Plan/Build headline); the resolved deliverable surfaces
        # in the dock summary (ON TOP), which reuses _renderSplitSummary.
        build_tile = pg.query_selector('.lane-tile[data-lane="build"]')
        assert build_tile, "no build lane tile"
        build_tile.click()
        pg.wait_for_function(
            "() => document.getElementById('effortDock').style.display === 'flex'",
            timeout=5000)
        pg.wait_for_selector("#dockSummary .bdeliv.resolved", timeout=8000)
        bd_html = pg.inner_html("#dockSummary .bdeliv.resolved")
        assert "myapp.py" in bd_html

        # ── project B: dock shows the honest placeholder ──
        pg.goto(f"{base}/project/{pidB}", wait_until="networkidle")
        from tests.ui_helpers import expand_workbench
        expand_workbench(pg)  # the Workbench tile now opens collapsed
        bt2 = pg.query_selector('.lane-tile[data-lane="build"]')
        assert bt2, "no build lane tile (B)"
        bt2.click()
        pg.wait_for_function(
            "() => document.getElementById('effortDock').style.display === 'flex'",
            timeout=5000)
        pg.wait_for_selector("#dockSummary .bdeliv.none", timeout=8000)
        none_html = pg.inner_html("#dockSummary .bdeliv.none")
        assert "pin one" in none_html.lower()
        # nothing fabricated: no spurious .resolved deliverable for B.
        assert pg.eval_on_selector_all(
            "#dockSummary .bdeliv.resolved", "e=>e.length") == 0

        assert not errors, f"JS console errors: {errors}"
        b.close()
