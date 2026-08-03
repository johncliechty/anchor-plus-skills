"""R&D v13 Wave 1 — Gandalf markdown rendering & unified report-link target.

Asserts the two user-facing contracts of the wave:
  1. Report links open in ONE named window (target="anchor_report_window")
     instead of spawning endless new tabs — checked on the Gandalf "Full report"
     + raw-JSON links AND on the JS link helpers (no stray target="_blank" on
     report/artifact/summary links; the external-URL autolink is exempt).
  2. The full report.md renders as RICH HTML via the EXISTING report_viewer
     markdown logic when the link carries ?render=1 — the /artifact route serves
     a rendered Reader page for markdown (and still raw bytes without the flag,
     so the inline exec-summary fetch keeps getting raw md to render client-side
     via the marked.parse shim). Non-markdown stays raw even with render=1.

The inline exec-summary client render (marked.parse → innerHTML) is exercised
end-to-end by tests/test_gandalf_ui_playwright_v1.py (real Chromium); here we
assert the JS landmarks (the marked shim + the innerHTML render path) are wired.

Hermetic: temp data/project dirs, throwaway server (port=0), never :8777, never
real data / model.
"""
import importlib
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest


@pytest.fixture
def gui_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    monkeypatch.delenv("ANCHOR_PROACTIVE_SUMMARY", raising=False)
    for mod in ("paths", "report_viewer", "rnd_registry", "lanes",
                "effort_history", "summarizer", "gandalf"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import anchor_gui
    return importlib.reload(anchor_gui)


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


def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=8) as resp:
            return resp.status, resp.read(), resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers.get("Content-Type", "")


def _mkproject(folder, name="P"):
    import rnd_registry
    folder.mkdir(parents=True, exist_ok=True)
    return rnd_registry.add_project(name, str(folder))


def _seed_run(folder, pid):
    import gandalf
    run_id = "run-1700000000000"
    run_dir = Path(folder) / "gandalf" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "exec-summary.md").write_text(
        "# Exec\n\n**Bold** finding.\n\n- one\n- two\n", encoding="utf-8")
    (run_dir / "report.md").write_text(
        "# Gandalf read\n\n## Diagnosis\n\nThe core is **sound**.\n\n"
        "- risk one\n- risk two\n", encoding="utf-8")
    (run_dir / "advisor-output.json").write_text("{}\n", encoding="utf-8")
    gandalf._append_index(str(folder), pid, {
        "schema_version": gandalf.GANDALF_INDEX_SCHEMA_VERSION,
        "run_id": run_id, "ts": 1700000000.0, "ok": True,
        "verdict": "Sound.", "degraded": True, "cross_model": False,
        "report_rel": f"gandalf/{run_id}/report.md",
        "exec_rel": f"gandalf/{run_id}/exec-summary.md",
        "advisor_rel": f"gandalf/{run_id}/advisor-output.json",
    })
    return run_id


# ── 1. Unified tab target on the Gandalf panel links ────────────────────────

def test_gandalf_links_use_named_window_and_render(gui_env, tmp_path):
    gui = gui_env
    folder = tmp_path / "Proj"
    pid = _mkproject(folder, "Proj")["id"]
    _seed_run(folder, pid)
    html = gui.render_project_window_html(pid)

    # The Full report link: named window + the &render=1 rendered-Reader flag.
    assert "target='anchor_report_window'" in html
    assert "&render=1" in html, "Full report link must request the rendered page"
    # The Gandalf report/JSON links must NOT use _blank any more.
    import re
    # isolate the gandalf panel block to avoid matching unrelated markup
    seg = html[html.index("id='gandalfPanel'"):]
    seg = seg[:seg.index("Grass Catcher")] if "Grass Catcher" in seg else seg
    assert "target='_blank'" not in seg, \
        "no Gandalf report link may open in a throwaway _blank tab"
    assert "Full report" in seg and "raw JSON" in seg


def test_no_blank_target_on_report_links_in_js(gui_env):
    """The project-window JS link helpers must route report/artifact/summary
    links to the named window (the only surviving _blank is the external-URL
    autolink in notes, which is NOT a report link)."""
    gui = gui_env
    js = gui._PROJECT_WINDOW_JS
    # Every report-ish JS link uses the named window.
    assert 'target="anchor_report_window"' in js
    # The marked shim + the innerHTML inline-render path are wired.
    assert "marked.parse" in js, "marked.parse shim must be present"
    assert "host.innerHTML = marked.parse" in js, \
        "the inline exec-summary must render via marked.parse → innerHTML"
    # No report/artifact/summary JS link still uses _blank. The notes autolink
    # lives in the Python handler (notes_popover), not in _PROJECT_WINDOW_JS,
    # so the JS block should be free of _blank entirely.
    assert 'target="_blank"' not in js, \
        "no JS report/artifact/summary link may open a throwaway _blank tab"


# ── 2. render=1 serves a rendered Reader page; raw without it ───────────────

def test_artifact_render_flag_returns_rendered_html(server, tmp_path):
    gui, base = server
    folder = tmp_path / "Proj"
    pid = _mkproject(folder, "Proj")["id"]
    run_id = _seed_run(folder, pid)
    rel = f"gandalf/{run_id}/report.md"

    # With render=1 → a rendered HTML Reader page (headings/bold became tags).
    code, body, ctype = _get(base + f"/artifact/{pid}?path={rel}&render=1")
    assert code == 200
    assert "text/html" in ctype, f"render=1 must serve HTML, got {ctype!r}"
    text = body.decode("utf-8")
    assert "<h1>" in text and "Gandalf read" in text
    assert "<strong>sound</strong>" in text, "bold must render to <strong>"
    assert "<li>risk one</li>" in text, "list items must render to <li>"

    # Without the flag → the RAW markdown bytes (unchanged behavior), so the
    # inline exec fetch + every other consumer still gets raw md.
    code, body, ctype = _get(base + f"/artifact/{pid}?path={rel}")
    assert code == 200
    assert "markdown" in ctype, f"raw .md must keep markdown ctype, got {ctype!r}"
    raw = body.decode("utf-8")
    assert raw.startswith("# Gandalf read"), "raw md must be served verbatim"
    assert "<strong>" not in raw, "raw path must NOT render markdown"


def test_artifact_render_flag_non_markdown_stays_raw(server, tmp_path):
    """render=1 only renders markdown — a .json artifact is served raw even with
    the flag (the raw-JSON link relies on this)."""
    gui, base = server
    folder = tmp_path / "Proj"
    pid = _mkproject(folder, "Proj")["id"]
    run_id = _seed_run(folder, pid)
    rel = f"gandalf/{run_id}/advisor-output.json"
    code, body, ctype = _get(base + f"/artifact/{pid}?path={rel}&render=1")
    assert code == 200
    assert "html" not in ctype, "non-markdown must not be rendered as HTML"
    assert body.decode("utf-8").strip() == "{}"
