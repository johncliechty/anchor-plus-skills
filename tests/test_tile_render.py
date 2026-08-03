"""Wave 3 — first-class imported history: tile per-lane summary line + blurb.

Covers the Wave 3 contract changes:
  - ``rnd_registry.status_line`` returns per-lane SESSION counts + provenance
    (``{lane: {count, imported, running}}``), built from ``sessions.list_sessions``
    so N discovered files that group into 1 session count as 1 — not N.
  - The dashboard tile renders a real per-lane summary line
    ("Research: 1 · Planning: 2 (1 imported) · ...") and NEVER renders the old
    "import" / "none-yet" lane state when sessions exist.
  - A per-project blurb field: seeded once from CLAUDE.md/README/Anchor.md,
    user-editable via ``set_blurb`` / ``POST /api/rnd/set_blurb``, rendered on
    the tile + project window.

Hermetic: temp ANCHOR_DATA_DIR, no live claude, no network.
"""
import importlib
import json
import threading
import urllib.error
import urllib.request

import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    import paths
    importlib.reload(paths)
    paths.ensure_data_dirs()
    import rnd_registry
    importlib.reload(rnd_registry)
    import effort_history
    importlib.reload(effort_history)
    import sessions
    importlib.reload(sessions)
    import anchor_gui
    importlib.reload(anchor_gui)
    return anchor_gui, rnd_registry, effort_history, sessions


# ── status_line shape ─────────────────────────────────────────────────────

def test_status_line_returns_per_lane_counts(env, tmp_path):
    gui, rnd, eh, _sess = env
    folder = tmp_path / "proj"
    folder.mkdir()
    pid = rnd.add_project("P", str(folder))["id"]

    line = rnd.status_line(pid)
    # Every lane present with the count/imported/running shape, all zero.
    for lane in rnd.STATUS_LANES:
        assert set(line[lane].keys()) == {"count", "imported", "running"}
        assert line[lane] == {"count": 0, "imported": 0, "running": 0}


def test_status_line_counts_sessions_not_raw_efforts(env, tmp_path):
    """7 discovered planning files in 2 dirs → 2 planning SESSIONS, not 7."""
    gui, rnd, eh, _sess = env
    folder = tmp_path / "proj"
    folder.mkdir()
    pid = rnd.add_project("P", str(folder))["id"]

    # Two discovered "sessions" (two parent dirs) under planning.
    for i in range(4):
        eh.record_effort(folder, pid, "planning", f"d-bf-{i}",
                         skill="crucible",
                         extra={"source": "discovered",
                                "artifact_path": f"planning/brownfield/{i}.md"})
    for i in range(3):
        eh.record_effort(folder, pid, "planning", f"d-v1-{i}",
                         skill="crucible",
                         extra={"source": "discovered",
                                "artifact_path": f"planning/rnd-v1/{i}.md"})

    line = rnd.status_line(pid)
    assert line["planning"]["count"] == 2          # sessions, not 7 efforts
    assert line["planning"]["imported"] == 2       # both discovered
    assert line["planning"]["running"] == 0


def test_status_line_run_vs_imported(env, tmp_path):
    gui, rnd, eh, _sess = env
    folder = tmp_path / "proj"
    folder.mkdir()
    pid = rnd.add_project("P", str(folder))["id"]
    # A real run effort (no source:discovered) → one non-imported session.
    eh.record_effort(folder, pid, "research", "job-1", skill="researchPrime")
    line = rnd.status_line(pid)
    assert line["research"]["count"] == 1
    assert line["research"]["imported"] == 0


# ── tile + status-line rendering ───────────────────────────────────────────

def test_tile_renders_per_lane_summary_no_import_state(env, tmp_path):
    gui, rnd, eh, _sess = env
    folder = tmp_path / "proj"
    folder.mkdir()
    entry = rnd.add_project("P", str(folder))
    pid = entry["id"]
    # 1 research run + 2 planning imported sessions + 1 build run.
    eh.record_effort(folder, pid, "research", "r1", skill="researchPrime")
    eh.record_effort(folder, pid, "planning", "p-a-0", skill="crucible",
                     extra={"source": "discovered",
                            "artifact_path": "planning/a/0.md"})
    eh.record_effort(folder, pid, "planning", "p-b-0", skill="crucible",
                     extra={"source": "discovered",
                            "artifact_path": "planning/b/0.md"})
    eh.record_effort(folder, pid, "build", "b1", skill="foreman")

    line_html = gui.render_status_line_html(pid)
    assert "Research: 1" in line_html
    assert "Planning: 2" in line_html
    assert "(2 imported)" in line_html
    assert "Build: 1" in line_html
    # The old masquerade states must be gone when sessions exist.
    assert "none-yet" not in line_html
    assert ">import<" not in line_html
    assert "Planning: import" not in line_html

    tile = gui.render_project_tile_html(rnd.get_project(pid))
    assert "Research: 1" in tile
    assert "Planning: 2" in tile


# ── blurb seeding + editing ────────────────────────────────────────────────

def test_blurb_seeds_from_claude_md(env, tmp_path):
    gui, rnd, eh, _sess = env
    folder = tmp_path / "proj"
    folder.mkdir()
    (folder / "CLAUDE.md").write_text(
        "# My Project\n\nThis project is a control tower for trio R&D.\n",
        encoding="utf-8")
    pid = rnd.add_project("P", str(folder))["id"]

    seeded = rnd.seed_blurb(pid)
    assert "control tower for trio R&D" in seeded["blurb"]
    # Idempotent: a second seed does not overwrite (no force).
    rnd.set_blurb(pid, "user-edited blurb")
    again = rnd.seed_blurb(pid)
    assert again["blurb"] == "user-edited blurb"


def test_blurb_seed_source_order_readme_fallback(env, tmp_path):
    gui, rnd, eh, _sess = env
    folder = tmp_path / "proj"
    folder.mkdir()
    # No CLAUDE.md; README.md is next in BLURB_SEED_FILES.
    (folder / "README.md").write_text(
        "# Readme Title\n\nReadme paragraph describing the thing.\n",
        encoding="utf-8")
    pid = rnd.add_project("P", str(folder))["id"]
    seeded = rnd.seed_blurb(pid)
    assert "Readme paragraph describing the thing." in seeded["blurb"]


def test_blurb_seed_missing_folder_no_crash(env, tmp_path):
    gui, rnd, eh, _sess = env
    # Folder does not exist on disk → best-effort no-op, no exception.
    pid = rnd.add_project("P", str(tmp_path / "gone"), scaffold=False)["id"]
    seeded = rnd.seed_blurb(pid)
    assert seeded is not None
    assert seeded.get("blurb", "") == ""


def test_set_blurb_persists_and_renders(env, tmp_path):
    gui, rnd, eh, _sess = env
    folder = tmp_path / "proj"
    folder.mkdir()
    pid = rnd.add_project("P", str(folder))["id"]
    rnd.set_blurb(pid, "A crisp one-line blurb.")
    assert rnd.get_project(pid)["blurb"] == "A crisp one-line blurb."
    tile = gui.render_project_tile_html(rnd.get_project(pid))
    assert "A crisp one-line blurb." in tile
    # v3 Wave 5 (IMPLEMENTATION-PLAN lines 124-141): the square tile is REPLACED
    # by a thin full-width row. With no cached project summary yet, the blurb is
    # the row's summary text (rendered in .rnd-row-summary, not the old
    # .rnd-blurb block). This is an intentional plan requirement, not a weakening.
    assert "rnd-row-summary" in tile
    assert "rnd-row" in tile


def test_blurb_renders_in_project_window(env, tmp_path):
    gui, rnd, eh, _sess = env
    folder = tmp_path / "proj"
    folder.mkdir()
    pid = rnd.add_project("ShinyProj", str(folder))["id"]
    rnd.set_blurb(pid, "Window blurb text.")
    html = gui.render_project_window_html(pid)
    assert "Window blurb text." in html
    # No lane masquerade in the window status line.
    assert "none-yet" not in html


def test_blurb_is_html_escaped_in_tile_and_window(env, tmp_path):
    """A blurb with a <script> payload must be HTML-escaped in BOTH renders."""
    gui, rnd, eh, _sess = env
    folder = tmp_path / "proj"
    folder.mkdir()
    pid = rnd.add_project("XSSProj", str(folder))["id"]
    payload = "<script>alert('xss')</script>"
    rnd.set_blurb(pid, payload)

    tile = gui.render_project_tile_html(rnd.get_project(pid))
    assert payload not in tile
    assert "&lt;script&gt;" in tile

    window = gui.render_project_window_html(pid)
    assert payload not in window
    assert "&lt;script&gt;" in window


def test_set_blurb_endpoint(env, tmp_path):
    """POST /api/rnd/set_blurb persists the blurb (mirrors set_notes wiring)."""
    gui, rnd, eh, _sess = env
    folder = tmp_path / "proj"
    folder.mkdir()
    pid = rnd.add_project("P", str(folder))["id"]

    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/rnd/set_blurb",
            data=json.dumps({"id": pid, "blurb": "via endpoint"}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
        assert data["ok"] is True
        assert data["entry"]["blurb"] == "via endpoint"
        assert rnd.get_project(pid)["blurb"] == "via endpoint"
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(timeout=5)


# ─────────────────────────────────────────────────────────────────────────────
# v3 Wave 5 — thin full-width project ROWS replace the square tile.
# IMPLEMENTATION-PLAN lines 124-141: "Replace the square tile with a thin
# full-width row (name · summary · per-lane mini-counts · status dot;
# click→window; lifecycle controls in a kebab/hover menu)."
# These tests assert the NEW row markup and explicitly assert the OLD square-tile
# markup is gone — this is the plan's "replace the tile" requirement, NOT a
# test-weakening.
# ─────────────────────────────────────────────────────────────────────────────

def test_projects_view_renders_thin_rows_not_square_tiles(env, tmp_path):
    gui, rnd, eh, _sess = env
    folder = tmp_path / "proj"
    folder.mkdir()
    rnd.add_project("RowProj", str(folder))
    view = gui.render_projects_view_html()
    # New thin-row markup is present.
    assert "rnd-row" in view
    assert 'data-project-id="' in view
    # The OLD square-tile container class is gone (replaced by the row).
    assert '"rnd-tile"' not in view
    assert "rnd-tile-head" not in view
    # Brace hygiene: served fragment has no leaked f-string braces.
    assert "{{" not in view and "}}" not in view


def test_row_click_opens_window_and_has_status_dot(env, tmp_path):
    gui, rnd, eh, _sess = env
    folder = tmp_path / "proj"
    folder.mkdir()
    pid = rnd.add_project("RowProj", str(folder))["id"]
    row = gui.render_project_tile_html(rnd.get_project(pid))
    # Click the row → opens the project window (existing navigation, keeps id).
    assert "openProjectWindow(" in row
    assert f'data-project-id="{pid}"' in row
    # A status dot is present.
    assert "rnd-dot" in row


def test_row_shows_cached_project_summary_when_present(env, tmp_path,
                                                       monkeypatch):
    """The row's summary text is the cached PROJECT summary when present, else
    the blurb (graceful fallback). We stub the cached project summary on disk."""
    gui, rnd, eh, _sess = env
    folder = tmp_path / "proj"
    folder.mkdir()
    pid = rnd.add_project("RowProj", str(folder))["id"]
    rnd.set_blurb(pid, "weak first-paragraph blurb")

    # Without a cached project summary → row falls back to the blurb.
    row_blurb = gui.render_project_tile_html(rnd.get_project(pid))
    assert "weak first-paragraph blurb" in row_blurb

    # Write a cached project summary the way summarizer would.
    import summarizer as summ
    importlib_reload(summ)
    summ._write_project_cache(folder, pid, {
        "project_id": pid, "kind": "project", "title": "RowProj",
        "claims": ["An accurate cached project summary of what this is"],
    })
    row_summary = gui.render_project_tile_html(rnd.get_project(pid))
    # The accurate cached summary REPLACES the weak blurb as the VISIBLE row
    # summary text (the .rnd-row-summary span). The blurb survives only as the
    # data-blurb attr that seeds the kebab "Blurb" edit prompt.
    import re as _re
    m = _re.search(r'<span class="rnd-row-summary"[^>]*>(.*?)</span>', row_summary)
    assert m is not None
    assert "accurate cached project summary" in m.group(1)
    assert "weak first-paragraph blurb" not in m.group(1)


def test_row_lifecycle_controls_in_kebab(env, tmp_path):
    gui, rnd, eh, _sess = env
    folder = tmp_path / "proj"
    folder.mkdir()
    pid = rnd.add_project("RowProj", str(folder))["id"]
    row = gui.render_project_tile_html(rnd.get_project(pid))
    # Lifecycle controls moved OFF the row into a kebab menu.
    assert "rnd-kebab" in row
    assert f'id="rnd-kebab-{pid}"' in row
    assert "rndToggleKebab(" in row
    # The actual lifecycle endpoints are still wired (inside the kebab menu).
    for fn in ("rndSetPriority(", "rndRescan(", "rndBlurb(", "rndNotes(",
               "rndArchive(", "rndRetire("):
        assert fn in row


def test_row_per_lane_mini_counts_present(env, tmp_path):
    gui, rnd, eh, _sess = env
    folder = tmp_path / "proj"
    folder.mkdir()
    pid = rnd.add_project("RowProj", str(folder))["id"]
    eh.record_effort(folder, pid, "research", "r1", skill="researchPrime")
    row = gui.render_project_tile_html(rnd.get_project(pid))
    # Per-lane mini-counts come from the (compact) status line.
    assert "rnd-row-counts" in row
    assert "Research: 1" in row


def test_row_summary_is_html_escaped(env, tmp_path):
    """A cached summary / blurb with a <script> payload must be HTML-escaped."""
    gui, rnd, eh, _sess = env
    folder = tmp_path / "proj"
    folder.mkdir()
    pid = rnd.add_project("XSSRow", str(folder))["id"]
    payload = "<script>alert('xss')</script>"
    rnd.set_blurb(pid, payload)
    row = gui.render_project_tile_html(rnd.get_project(pid))
    assert payload not in row
    assert "&lt;script&gt;" in row


def importlib_reload(mod):
    import importlib
    return importlib.reload(mod)


def test_rescan_triggers_proactive_project_summary(tmp_path, monkeypatch):
    """POST /api/rnd/rescan proactively generates the cached project summary
    (Wave 5, IMPLEMENTATION-PLAN lines 124-141) WITHOUT blocking the response,
    through the runner seam (stub → never live claude). The render path only
    READS the cache; here we verify the rescan PRODUCES it."""
    import importlib
    import time
    from pathlib import Path as _P
    stub = (_P(__file__).resolve().parent / "stub_summarizer.py").as_posix()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {stub}")
    monkeypatch.setenv("ANCHOR_PROACTIVE_SUMMARY", "1")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    monkeypatch.setenv("STUB_SUMMARIZER_CLAIMS",
                       "Anchor is a productivity system for markdown task files")
    import paths
    importlib.reload(paths)
    paths.ensure_data_dirs()
    import job_runner
    importlib.reload(job_runner)
    import rnd_registry
    importlib.reload(rnd_registry)
    import effort_history
    importlib.reload(effort_history)
    import sessions
    importlib.reload(sessions)
    import summarizer
    importlib.reload(summarizer)
    import anchor_gui
    importlib.reload(anchor_gui)
    assert anchor_gui._PROACTIVE_SUMMARY_ENABLED is True

    folder = tmp_path / "proj"
    folder.mkdir()
    (folder / "CLAUDE.md").write_text(
        "# Anchor\n\nAnchor is a productivity system for markdown task files.\n",
        encoding="utf-8")
    pid = rnd_registry.add_project("Anchor", str(folder))["id"]

    srv = anchor_gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/rnd/rescan",
            data=json.dumps({"id": pid}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=8) as resp:
            assert json.loads(resp.read())["ok"] is True
        # Generation runs in a background thread; poll briefly for the cache.
        jp = summarizer._project_summary_json_path(folder, pid)
        for _ in range(100):
            if jp.exists():
                break
            time.sleep(0.1)
        assert jp.exists(), "rescan should proactively generate the project summary"
        cached = summarizer.load_cached_project(folder, pid)
        assert "productivity system" in " ".join(cached["claims"]).lower()
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(timeout=5)
        for rec in job_runner.list_records():
            if rec.get("status") == job_runner.STATUS_RUNNING:
                try:
                    job_runner.cancel(rec["job_id"])
                except Exception:
                    pass
