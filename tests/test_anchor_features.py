"""Anchor UX + Zombie-Hunter feature tests (Foreman build: feat/anchor-ux-zombie).

Each wave's EXECUTE phase APPENDS its hermetic tests to this file. The baseline
test below keeps the gate non-vacuous from wave 1 (the module under change,
anchor_gui, must import) and proves the packaged Zombie-Hunter engine is wired.

Rules for agents:
- Tests are EXECUTE's deliverable; the FIX phase may NOT edit this file.
- Hermetic only: NO live :8777 server, NO real long-lived child processes,
  use tmp_path / monkeypatch. Stdlib only.
"""
import importlib


def test_baseline_anchor_gui_imports():
    # The features under change live in anchor_gui; importing must not start a
    # server (server start is gated under __main__). This anchors the gate file.
    mod = importlib.import_module("anchor_gui")
    assert mod is not None


def test_baseline_zombie_engine_packaged():
    # Refinement #2: the Zombie-Hunter engine ships WITH Anchor (packaged).
    import proc_probe  # noqa: F401
    import zombie_hunter  # noqa: F401
    import session_registry
    assert session_registry.STATUS_CANCELLED == "cancelled"


import pytest
from pathlib import Path


@pytest.fixture
def gui(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    import paths
    importlib.reload(paths)
    import rnd_registry
    importlib.reload(rnd_registry)
    import anchor_gui
    importlib.reload(anchor_gui)
    return anchor_gui


def test_resolve_project_dir_normal(gui):
    # Returns <parent>/<name> normally
    parent = Path("C:/dev")
    name = "myproj"
    resolved = gui.resolve_project_dir(parent, name)
    assert resolved == Path("C:/dev/myproj")


def test_resolve_project_dir_prevents_double_nesting(gui):
    # Does NOT double-nest when parent already ends in name
    
    # Case-insensitive check
    parent1 = Path("C:/dev/MyProj")
    resolved1 = gui.resolve_project_dir(parent1, "myproj")
    assert resolved1 == Path("C:/dev/MyProj")
    
    # Separator/trailing slash check
    parent2 = Path("C:\\dev\\myproj\\")
    resolved2 = gui.resolve_project_dir(parent2, "myproj")
    assert resolved2 == Path("C:\\dev\\myproj")

    # Normal case where last component differs slightly
    parent3 = Path("C:/dev/myproj-suffix")
    resolved3 = gui.resolve_project_dir(parent3, "myproj")
    assert resolved3 == Path("C:/dev/myproj-suffix/myproj")


def test_render_project_window_html_back_link(gui, tmp_path):
    # Register a project first
    parent = tmp_path / "dev"
    parent.mkdir()
    res = gui.create_new_folder_project("TestProjectLink", str(parent))
    entry = res["entry"]
    pid = entry["id"]
    
    html = gui.render_project_window_html(pid)
    # (2026-08-07, John) The back-to-dashboard link is GONE from project pages.
    assert 'Back to dashboard' not in html


def test_render_project_window_html_not_found(gui):
    html = gui.render_project_window_html("nonexistent")
    assert '<a href="/" target="_top">' in html
    assert 'Back to dashboard' in html


def test_upload_batch_success(gui, tmp_path):
    # Setup project
    project_dir = tmp_path / "TestProject"
    project_dir.mkdir()
    res = gui.create_new_folder_project("TestProjUpload", str(project_dir))
    pid = res["entry"]["id"]

    import base64
    f1_content = b"Content of file 1"
    f2_content = b"Content of file 2"
    f1_b64 = base64.b64encode(f1_content).decode()
    f2_b64 = base64.b64encode(f2_content).decode()

    # Mutating /api/* POSTs are token-gated when ANCHOR_TOKEN is configured
    # (Wave 2 / D4). Supply the expected token so the test is hermetic against
    # the ambient env: expected_token() is None (auth disabled) -> token None is
    # ignored; otherwise it matches exactly.
    import paths as _paths
    body = {
        "project_id": pid,
        "token": _paths.expected_token(),
        "files": [
            {"path": "file1.txt", "content_b64": f1_b64},
            {"path": "subdir/file2.txt", "content_b64": f2_b64}
        ]
    }

    class FakeHandler(gui.AnchorHandler):
        def __init__(self, path, body_dict):
            self.path = path
            self.headers = {}
            import io
            import json
            body_bytes = json.dumps(body_dict).encode("utf-8")
            self.rfile = io.BytesIO(body_bytes)
            self.headers["Content-Length"] = str(len(body_bytes))
            self.wfile = io.BytesIO()
            self.response_code = None
            self.response_headers = {}

        def send_response(self, code):
            self.response_code = code

        def send_header(self, keyword, value):
            self.response_headers[keyword] = value

        def end_headers(self):
            pass

        def log_message(self, format, *args):
            pass

    handler = FakeHandler("/api/rnd/upload_batch", body)
    handler.do_POST()

    import json
    res_data = json.loads(handler.wfile.getvalue().decode())
    assert res_data.get("ok") is True

    # Verify files created at correct location
    resolved_project_dir = Path(res["entry"]["folder_path"])
    file1 = resolved_project_dir / "file1.txt"
    file2 = resolved_project_dir / "subdir" / "file2.txt"
    assert file1.exists()
    assert file2.exists()
    assert file1.read_bytes() == f1_content
    assert file2.read_bytes() == f2_content


def test_upload_batch_traversal_rejection(gui, tmp_path):
    project_dir = tmp_path / "TestProject"
    project_dir.mkdir()
    res = gui.create_new_folder_project("TestProjUpload", str(project_dir))
    pid = res["entry"]["id"]

    import base64
    f_b64 = base64.b64encode(b"malicious").decode()

    # Case 1: Traversal using ..
    body1 = {
        "project_id": pid,
        "files": [{"path": "../escaped.txt", "content_b64": f_b64}]
    }

    class FakeHandler(gui.AnchorHandler):
        def __init__(self, path, body_dict):
            self.path = path
            self.headers = {}
            import io
            import json
            body_bytes = json.dumps(body_dict).encode("utf-8")
            self.rfile = io.BytesIO(body_bytes)
            self.headers["Content-Length"] = str(len(body_bytes))
            self.wfile = io.BytesIO()
            self.response_code = None
            self.response_headers = {}

        def send_response(self, code):
            self.response_code = code

        def send_header(self, keyword, value):
            self.response_headers[keyword] = value

        def end_headers(self):
            pass

        def log_message(self, format, *args):
            pass

    handler = FakeHandler("/api/rnd/upload_batch", body1)
    handler.do_POST()

    import json
    res_data = json.loads(handler.wfile.getvalue().decode())
    assert res_data.get("ok") is False
    resolved_project_dir = Path(res["entry"]["folder_path"])
    assert not (resolved_project_dir.parent / "escaped.txt").exists()

    # Case 2: Absolute path
    body2 = {
        "project_id": pid,
        "files": [{"path": "/absolute_escaped.txt", "content_b64": f_b64}]
    }
    handler2 = FakeHandler("/api/rnd/upload_batch", body2)
    handler2.do_POST()
    res_data2 = json.loads(handler2.wfile.getvalue().decode())
    assert res_data2.get("ok") is False
    assert not Path("/absolute_escaped.txt").exists()


def test_project_files_listing_normal_and_gitignore(gui, tmp_path):
    import json
    parent_dir = tmp_path / "MyProject"
    parent_dir.mkdir()
    res = gui.create_new_folder_project("TestProjFiles", str(parent_dir))
    pid = res["entry"]["id"]
    # Write the fixtures INTO the actual resolved project root (not the parent),
    # so the listing of the project sees them.
    project_dir = Path(res["entry"]["folder_path"])
    (project_dir / "sub").mkdir(parents=True, exist_ok=True)
    (project_dir / "file1.txt").write_text("Hello file1", encoding="utf-8")
    (project_dir / "sub" / "file2.txt").write_text("Hello file2", encoding="utf-8")
    (project_dir / "sub" / "ignored.log").write_text("ignored", encoding="utf-8")
    (project_dir / ".gitignore").write_text("*.log\n", encoding="utf-8")

    class FakeGetHandler(gui.AnchorHandler):
        def __init__(self, path):
            self.path = path
            self.headers = {}
            import io
            self.rfile = io.BytesIO()
            self.wfile = io.BytesIO()
            self.response_code = None
            self.response_headers = {}

        def send_response(self, code):
            self.response_code = code

        def send_header(self, keyword, value):
            self.response_headers[keyword] = value

        def end_headers(self):
            pass

        def log_message(self, format, *args):
            pass

        def _term_token_ok(self):
            return True

    # 1. Test root listing
    handler = FakeGetHandler(f"/api/rnd/project_files?project_id={pid}")
    handler.do_GET()
    res_data = json.loads(handler.wfile.getvalue().decode())
    assert res_data.get("ok") is True
    assert "file1.txt" in [f["name"] for f in res_data["files"]]
    assert ".gitignore" in [f["name"] for f in res_data["files"]]
    assert "sub" in res_data["dirs"]

    # 2. Test sub listing
    handler = FakeGetHandler(f"/api/rnd/project_files?project_id={pid}&path=sub")
    handler.do_GET()
    res_data = json.loads(handler.wfile.getvalue().decode())
    assert res_data.get("ok") is True
    assert "file2.txt" in [f["name"] for f in res_data["files"]]
    assert "ignored.log" not in [f["name"] for f in res_data["files"]]


def test_project_files_traversal_rejection(gui, tmp_path):
    import json
    project_dir = tmp_path / "MyProject"
    project_dir.mkdir()
    res = gui.create_new_folder_project("TestProjTraversal", str(project_dir))
    pid = res["entry"]["id"]

    class FakeGetHandler(gui.AnchorHandler):
        def __init__(self, path):
            self.path = path
            self.headers = {}
            import io
            self.rfile = io.BytesIO()
            self.wfile = io.BytesIO()
            self.response_code = None
            self.response_headers = {}

        def send_response(self, code):
            self.response_code = code

        def send_header(self, keyword, value):
            self.response_headers[keyword] = value

        def end_headers(self):
            pass

        def log_message(self, format, *args):
            pass

        def _term_token_ok(self):
            return True

    # Traversal using ..
    handler = FakeGetHandler(f"/api/rnd/project_files?project_id={pid}&path=../")
    handler.do_GET()
    res_data = json.loads(handler.wfile.getvalue().decode())
    assert res_data.get("ok") is False
    assert handler.response_code == 400

    # Absolute path traversal
    handler2 = FakeGetHandler(f"/api/rnd/project_files?project_id={pid}&path=/absolute")
    handler2.do_GET()
    res_data2 = json.loads(handler2.wfile.getvalue().decode())
    assert res_data2.get("ok") is False
    assert handler2.response_code == 400


def test_project_files_symlink_escape_rejection(gui, tmp_path, monkeypatch):
    import json
    project_dir = tmp_path / "MyProject"
    project_dir.mkdir()
    res = gui.create_new_folder_project("TestProjSymlink", str(project_dir))
    pid = res["entry"]["id"]

    class FakeGetHandler(gui.AnchorHandler):
        def __init__(self, path):
            self.path = path
            self.headers = {}
            import io
            self.rfile = io.BytesIO()
            self.wfile = io.BytesIO()
            self.response_code = None
            self.response_headers = {}

        def send_response(self, code):
            self.response_code = code

        def send_header(self, keyword, value):
            self.response_headers[keyword] = value

        def end_headers(self):
            pass

        def log_message(self, format, *args):
            pass

        def _term_token_ok(self):
            return True

    outside_file = tmp_path / "secret.txt"
    outside_file.write_text("secret content", encoding="utf-8")

    original_iterdir = Path.iterdir
    original_resolve = Path.resolve

    def mock_iterdir(self):
        if self.resolve() == project_dir.resolve():
            return [project_dir / "escaped_symlink.txt"]
        return original_iterdir(self)

    def mock_resolve(self, strict=False):
        if self.name == "escaped_symlink.txt":
            return outside_file.resolve()
        return original_resolve(self, strict=strict)

    monkeypatch.setattr(Path, "iterdir", mock_iterdir)
    monkeypatch.setattr(Path, "resolve", mock_resolve)

    handler = FakeGetHandler(f"/api/rnd/project_files?project_id={pid}")
    handler.do_GET()
    res_data = json.loads(handler.wfile.getvalue().decode())
    assert res_data.get("ok") is True
    assert "escaped_symlink.txt" not in [f["name"] for f in res_data["files"]]


def test_project_file_content_normal_and_ignored_and_size_capped(gui, tmp_path):
    import json
    parent_dir = tmp_path / "MyProject"
    parent_dir.mkdir()
    res = gui.create_new_folder_project("TestProjContent", str(parent_dir))
    pid = res["entry"]["id"]
    # Write the fixtures INTO the actual resolved project root (not the parent).
    project_dir = Path(res["entry"]["folder_path"])

    (project_dir / "normal.txt").write_text("normal file content", encoding="utf-8")
    (project_dir / "ignored.log").write_text("ignored file content", encoding="utf-8")
    (project_dir / ".gitignore").write_text("*.log\n", encoding="utf-8")

    large_content = "X" * (1 * 1024 * 1024 + 1024)
    (project_dir / "large.txt").write_text(large_content, encoding="utf-8")

    class FakeGetHandler(gui.AnchorHandler):
        def __init__(self, path):
            self.path = path
            self.headers = {}
            import io
            self.rfile = io.BytesIO()
            self.wfile = io.BytesIO()
            self.response_code = None
            self.response_headers = {}

        def send_response(self, code):
            self.response_code = code

        def send_header(self, keyword, value):
            self.response_headers[keyword] = value

        def end_headers(self):
            pass

        def log_message(self, format, *args):
            pass

        def _term_token_ok(self):
            return True

    # 1. Normal file read
    handler = FakeGetHandler(f"/api/rnd/project_file_content?project_id={pid}&path=normal.txt")
    handler.do_GET()
    res_data = json.loads(handler.wfile.getvalue().decode())
    assert res_data.get("ok") is True
    assert res_data["content"] == "normal file content"
    assert res_data["size"] == len("normal file content")

    # 2. Ignored file read (should be denied)
    handler2 = FakeGetHandler(f"/api/rnd/project_file_content?project_id={pid}&path=ignored.log")
    handler2.do_GET()
    res_data2 = json.loads(handler2.wfile.getvalue().decode())
    assert res_data2.get("ok") is False
    assert handler2.response_code == 403

    # 3. Large file read (should exceed size limit)
    handler3 = FakeGetHandler(f"/api/rnd/project_file_content?project_id={pid}&path=large.txt")
    handler3.do_GET()
    res_data3 = json.loads(handler3.wfile.getvalue().decode())
    assert res_data3.get("ok") is False
    assert handler3.response_code == 400
    assert "exceeds size limit" in res_data3["error"]

    # 4. Traversal file read (should be rejected)
    handler4 = FakeGetHandler(f"/api/rnd/project_file_content?project_id={pid}&path=../escaped.txt")
    handler4.do_GET()
    res_data4 = json.loads(handler4.wfile.getvalue().decode())
    assert res_data4.get("ok") is False
    assert handler4.response_code == 400


def test_zombie_hunter_button_name_and_icon(gui):
    # Retrieve the dashboard HTML
    html = gui.generate_html([], [], [])
    
    # 1. Assert that the button contains the text "Zombie Hunter"
    assert "Zombie Hunter" in html
    # 2. Assert that the button does NOT contain the text "Zombie Radar"
    assert "Zombie Radar" not in html
    # 3. Assert that the button img points to the zombie-hunter-radar.jpg icon path
    assert "/vendor/brand/zombie-hunter-radar.jpg" in html


def test_zombie_hunter_report_renders_cached(gui, tmp_path):
    import json
    import time
    
    class FakeGetHandler(gui.AnchorHandler):
        def __init__(self, path):
            self.path = path
            self.headers = {}
            import io
            self.rfile = io.BytesIO()
            self.wfile = io.BytesIO()
            self.response_code = None
            self.response_headers = {}

        def send_response(self, code):
            self.response_code = code

        def send_header(self, keyword, value):
            self.response_headers[keyword] = value

        def end_headers(self):
            pass

        def log_message(self, format, *args):
            pass

        def _term_token_ok(self):
            return True

    # Mock zombie_hunter_last.json in the tmp_path-based anchor_dir
    import zombie_hunter
    anchor_dir = tmp_path / ".anchor"
    anchor_dir.mkdir(parents=True, exist_ok=True)
    report_file = anchor_dir / "zombie_hunter_last.json"
    
    report_data = {
        "killed": ["session_orphaned_123"],
        "reaped_dead": [],
        "reaped_recycled": [],
        "abstained": [],
        "alive": ["session_active_456"],
        "swept_at": time.time(),
        "total": 2
    }
    report_file.write_text(json.dumps(report_data), encoding="utf-8")

    handler = FakeGetHandler("/api/rnd/zombie_hunter_report")
    handler.do_GET()

    response_html = handler.wfile.getvalue().decode("utf-8")
    assert "Zombie Hunter" in response_html
    assert "Cached Sweep Report" in response_html
    assert "session_orphaned_123" in response_html
    assert "session_active_456" in response_html
    assert "Live Process Query Fallback" not in response_html


def test_zombie_hunter_report_renders_fallback_when_absent(gui, monkeypatch):
    import subprocess
    from unittest.mock import MagicMock

    class FakeGetHandler(gui.AnchorHandler):
        def __init__(self, path):
            self.path = path
            self.headers = {}
            import io
            self.rfile = io.BytesIO()
            self.wfile = io.BytesIO()
            self.response_code = None
            self.response_headers = {}

        def send_response(self, code):
            self.response_code = code

        def send_header(self, keyword, value):
            self.response_headers[keyword] = value

        def end_headers(self):
            pass

        def log_message(self, format, *args):
            pass

        def _term_token_ok(self):
            return True

    # Mock subprocess.run to simulate tasklist/ps output
    mock_run = MagicMock()
    mock_run.return_value.stdout = "FakeTaskListProcess123   Console  0   10,240 K"
    monkeypatch.setattr(subprocess, "run", mock_run)

    handler = FakeGetHandler("/api/rnd/zombie_hunter_report")
    handler.do_GET()

    response_html = handler.wfile.getvalue().decode("utf-8")
    assert "Zombie Hunter" in response_html
    assert "Live Process Query Fallback" in response_html
    assert "FakeTaskListProcess123" in response_html
    assert "Cached Sweep Report" not in response_html


def test_zombie_hunter_no_kill_or_start_hunter(gui, monkeypatch):
    import zombie_hunter
    import proc_probe
    from unittest.mock import MagicMock

    class FakeGetHandler(gui.AnchorHandler):
        def __init__(self, path):
            self.path = path
            self.headers = {}
            import io
            self.rfile = io.BytesIO()
            self.wfile = io.BytesIO()
            self.response_code = None
            self.response_headers = {}

        def send_response(self, code):
            self.response_code = code

        def send_header(self, keyword, value):
            self.response_headers[keyword] = value

        def end_headers(self):
            pass

        def log_message(self, format, *args):
            pass

        def _term_token_ok(self):
            return True

    # Spy/Mock start_hunter and tree_kill to ensure they are NOT called
    mock_start_hunter = MagicMock()
    mock_tree_kill = MagicMock()
    monkeypatch.setattr(zombie_hunter, "start_hunter", mock_start_hunter)
    monkeypatch.setattr(proc_probe, "tree_kill", mock_tree_kill)

    handler = FakeGetHandler("/api/rnd/zombie_hunter_report")
    handler.do_GET()

    assert mock_start_hunter.call_count == 0
    assert mock_tree_kill.call_count == 0





def test_zombie_hunter_report_auth_gated(gui, monkeypatch):
    # Defense-in-depth (Claude-review hardening): when a token IS configured
    # (remote mode), the radar report route must reject an unauthenticated GET
    # with 401 — it leaks process metadata otherwise. _term_token_ok reads
    # ANCHOR_TOKEN live via paths.expected_token(), so no reload is needed.
    import json
    monkeypatch.setenv("ANCHOR_TOKEN", "secret-tok")

    class FakeGetHandler(gui.AnchorHandler):
        def __init__(self, path):
            self.path = path
            self.headers = {}
            import io
            self.rfile = io.BytesIO()
            self.wfile = io.BytesIO()
            self.response_code = None
            self.response_headers = {}

        def send_response(self, code):
            self.response_code = code

        def send_header(self, keyword, value):
            self.response_headers[keyword] = value

        def end_headers(self):
            pass

        def log_message(self, format, *args):
            pass

    # No token provided -> 401 (gate enforced).
    h = FakeGetHandler("/api/rnd/zombie_hunter_report")
    h.do_GET()
    assert h.response_code == 401
    body = json.loads(h.wfile.getvalue().decode())
    assert body.get("ok") is False
