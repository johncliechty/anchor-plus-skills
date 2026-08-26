"""Wave 6 — wiring: register + open + Rescan populate from disk (no dupes, prune).

Proves IMPLEMENTATION-PLAN.md "## Wave 6":
GIVEN a folder with prior trio docs, WHEN a project is registered on it, THEN its
tile immediately shows imported counts and its Kanban is non-empty; opening it
re-syncs; Rescan re-syncs with no dupes and prunes deletions.

Throwaway server (port=0); never 8777; no live claude.
"""
import importlib
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest


@pytest.fixture
def gui_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    import paths
    importlib.reload(paths)
    paths.ensure_data_dirs()
    import rnd_registry
    importlib.reload(rnd_registry)
    import effort_history
    importlib.reload(effort_history)
    import report_viewer
    importlib.reload(report_viewer)
    import lanes
    importlib.reload(lanes)
    import anchor_marker
    importlib.reload(anchor_marker)
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


def _seed(folder):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "foreman-checkpoint.json").write_text("{}", encoding="utf-8")
    p = folder / "planning"
    p.mkdir()
    (p / "MASTER-PLAN.md").write_text("# Master Plan\n", encoding="utf-8")
    r = folder / "research" / "s"
    r.mkdir(parents=True)
    (r / "report.md").write_text("# Survey\n", encoding="utf-8")
    return folder


def test_register_populates_tile_and_kanban(server, tmp_path):
    gui, base = server
    folder = _seed(tmp_path / "proj")

    # Register a project on the brownfield folder via the real endpoint.
    code, body = _post(base + "/api/rnd/new_project",
                       {"mode": "existing", "name": "Brown",
                        "folder_path": str(folder)})
    assert code == 200 and body["ok"]
    pid = body["entry"]["id"]

    # Tile (home view) immediately shows imported counts.
    code, home = _get_text(base + "/")
    assert "imported" in home

    # Project window board is non-empty: the 3 discovered artifacts adopted
    # (build/planning/research) render as 3 "imported" Layout-D tiles (grey
    # light, no run metrics). v12 Wave 2 Layout-D: a discovered session is a
    # headline card or a shelf little-tile — both carry the legacy
    # ``tile lane-tile`` alias + ``data-session``/``data-lane``/``data-light``.
    # (2026-08-25) The Layout-D board lives on the CLASSIC window (?classic=1);
    # the default /project/ page is the cockpit since the cutover.
    code, win = _get_text(base + f"/project/{pid}?classic=1")
    assert "imported" in win
    # One imported (grey) tile per discovered lane (3 total). Class order varies
    # by Layout-D variant (``headline tile lane-tile`` / ``minitile tile lane-tile``)
    # so match the alias anywhere in the class list.
    import re as _re
    grey_tiles = _re.findall(
        r"<div class='[^']*\btile lane-tile\b[^']*' data-session=\"[^\"]+\" "
        r"data-lane=\"[^\"]+\" data-light=\"grey\"", win)
    assert len(grey_tiles) == 3, grey_tiles
    # Anchor.md was written at the folder root.
    assert (folder / "Anchor.md").exists()


def test_open_resyncs_and_rescan_idempotent_and_prunes(server, tmp_path):
    gui, base = server
    import effort_history as eh
    folder = _seed(tmp_path / "proj")
    code, body = _post(base + "/api/rnd/new_project",
                       {"mode": "existing", "name": "Brown",
                        "folder_path": str(folder)})
    pid = body["entry"]["id"]

    def disc_count():
        n = 0
        for lane in ("research", "planning", "build", "deliverables"):
            n += sum(1 for e in eh.list_efforts(folder, pid, lane)
                     if eh.is_discovered(e))
        return n

    assert disc_count() == 3

    # Opening the project re-syncs (no dupes).
    _get_text(base + f"/project/{pid}")
    assert disc_count() == 3

    # Rescan endpoint is idempotent.
    code, r = _post(base + "/api/rnd/rescan", {"id": pid})
    assert code == 200 and r["ok"]
    assert disc_count() == 3

    # Delete an artifact on disk, Rescan prunes its discovered card.
    (folder / "planning" / "MASTER-PLAN.md").unlink()
    code, r = _post(base + "/api/rnd/rescan", {"id": pid})
    assert code == 200 and r["ok"]
    assert disc_count() == 2
    assert all(not eh.is_discovered(e)
               for e in eh.list_efforts(folder, pid, "planning"))


def test_rescan_unknown_project_clean_404(server):
    gui, base = server
    code, r = _post(base + "/api/rnd/rescan", {"id": "nope-does-not-exist"})
    assert code == 404
    assert r["ok"] is False
