"""Wave 4 — /artifact/<pid>?path=<rel> file route security + status_line + home.

REQUIRED negative test (mirrors test_report_route_safety.py): the /artifact
route serves a discovered artifact from the project folder using the proven
report_viewer.katex_asset containment pattern, and REJECTS:
  - ../.. traversal,
  - an absolute rel (/etc/passwd, C:\\Windows\\...),
  - .git/config and .anchor/... ,
  - a symlink-escape,
=> 400/404 with ZERO bytes read.

Also: status_line() reflects adopted+real per lane (no longer hardcoded
none-yet), and the HOME dashboard R&D panel shows imported counts.

No live claude; throwaway server (port=0); never 8777.
"""
import importlib
import json
import os
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

import brownfield_scan as bscan


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


def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=8) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _seed(folder):
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / "planning"
    p.mkdir()
    (p / "MASTER-PLAN.md").write_text("# Master Plan\nSECRET-FREE structure\n",
                                      encoding="utf-8")
    # A real secret file outside the safe set, to prove traversal can't read it.
    (folder.parent / "secret.txt").write_text("TOP-SECRET", encoding="utf-8")
    return folder


def test_artifact_serves_real_file(server, tmp_path):
    gui, base = server
    import rnd_registry as rnd
    import effort_history as eh
    folder = _seed(tmp_path / "proj")
    proj = rnd.add_project("Brown", str(folder))
    pid = proj["id"]
    eh.adopt_discovered(folder, pid, bscan.scan(str(folder)))

    code, body = _get(base + f"/artifact/{pid}?path=planning/MASTER-PLAN.md")
    assert code == 200
    assert b"Master Plan" in body


@pytest.mark.parametrize("badpath", [
    "../../secret.txt",
    "..%2F..%2Fsecret.txt",
    "/etc/passwd",
    ".git/config",
    ".anchor/projects/x/discovery.json",
    "planning/../../secret.txt",
])
def test_artifact_rejects_traversal_and_forbidden(server, tmp_path, badpath):
    gui, base = server
    import rnd_registry as rnd
    folder = _seed(tmp_path / "proj")
    # Plant .git/config so a successful traversal WOULD return bytes.
    git = folder / ".git"
    git.mkdir()
    (git / "config").write_text("[core] secret=yes", encoding="utf-8")
    proj = rnd.add_project("Brown", str(folder))
    pid = proj["id"]

    code, body = _get(base + f"/artifact/{pid}?path={badpath}")
    assert code in (400, 404), (badpath, code)
    # Zero bytes of any secret leaked.
    assert b"TOP-SECRET" not in body
    assert b"secret=yes" not in body


def test_artifact_missing_path_is_400(server, tmp_path):
    gui, base = server
    import rnd_registry as rnd
    folder = _seed(tmp_path / "proj")
    proj = rnd.add_project("Brown", str(folder))
    pid = proj["id"]
    code, _ = _get(base + f"/artifact/{pid}")
    assert code == 400
    code, _ = _get(base + "/artifact/?path=planning/MASTER-PLAN.md")
    assert code in (400, 404)


def test_artifact_symlink_escape_rejected(server, tmp_path):
    gui, base = server
    import rnd_registry as rnd
    folder = _seed(tmp_path / "proj")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "loot.txt").write_text("ESCAPED-SECRET", encoding="utf-8")
    link = folder / "link"
    try:
        os.symlink(str(outside), str(link), target_is_directory=True)
    except (OSError, NotImplementedError, AttributeError):
        pytest.skip("symlink creation not permitted on this host")
    proj = rnd.add_project("Brown", str(folder))
    pid = proj["id"]
    code, body = _get(base + f"/artifact/{pid}?path=link/loot.txt")
    assert code in (400, 404)
    assert b"ESCAPED-SECRET" not in body


def test_resolve_project_artifact_direct_rejections(gui_env, tmp_path):
    gui = gui_env
    import report_viewer as rv
    folder = _seed(tmp_path / "proj")
    # Valid file resolves.
    out = rv.resolve_project_artifact(str(folder), "planning/MASTER-PLAN.md")
    assert out is not None
    data, ctype = out
    assert b"Master Plan" in data
    assert "markdown" in ctype
    # Rejections return None (zero bytes).
    assert rv.resolve_project_artifact(str(folder), "../../secret.txt") is None
    assert rv.resolve_project_artifact(str(folder), "/etc/passwd") is None
    assert rv.resolve_project_artifact(str(folder), ".git/config") is None
    assert rv.resolve_project_artifact(str(folder), "") is None
    assert rv.resolve_project_artifact("", "x") is None


def test_status_line_reflects_adopted_and_real(gui_env, tmp_path):
    gui = gui_env
    import rnd_registry as rnd
    import effort_history as eh
    folder = _seed(tmp_path / "proj")
    proj = rnd.add_project("Brown", str(folder))
    pid = proj["id"]

    # Wave 3 contract: per-lane SESSION counts + provenance, not a state string.
    # Before adoption: every lane is a zeroed counts dict.
    line0 = rnd.status_line(pid)
    for lane in rnd.STATUS_LANES:
        assert line0[lane] == {"count": 0, "imported": 0, "running": 0}

    # Adopt the brownfield planning doc → one IMPORTED planning session.
    eh.adopt_discovered(folder, pid, bscan.scan(str(folder)))
    line1 = rnd.status_line(pid)
    assert line1["planning"]["count"] >= 1
    assert line1["planning"]["imported"] == line1["planning"]["count"]
    assert line1["planning"]["count"] > 0  # never reads "none-yet"

    # A real run in research → one NON-imported (run) research session.
    eh.record_effort(folder, pid, "research", "r1", skill="researchPrime")
    line2 = rnd.status_line(pid)
    assert line2["research"]["count"] == 1
    assert line2["research"]["imported"] == 0


def test_home_dashboard_panel_shows_imported(server, tmp_path):
    gui, base = server
    import rnd_registry as rnd
    import effort_history as eh
    folder = _seed(tmp_path / "proj")
    proj = rnd.add_project("Brown", str(folder))
    pid = proj["id"]
    eh.adopt_discovered(folder, pid, bscan.scan(str(folder)))

    code, body = _get(base + "/")
    assert code == 200
    html = body.decode("utf-8")
    # The home R&D panel tile shows the imported count.
    assert "1 imported" in html
