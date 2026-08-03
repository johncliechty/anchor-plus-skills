"""Wave 7 — type-aware deliverable launch.

Every Foreman run auto-pins one deliverable; clicking *launch* adapts to the
deliverable TYPE (canonical UI: the "📦 Deliverable" Extras card):

  - skill / tool → VERIFY status (available | loaded | missing); NO process.
  - service      → launch a PERSISTENT preview (free port != 8777, isolated temp
                   ANCHOR_DATA_DIR, loopback, health-check); a SECOND launch
                   PULLS UP the running one instead of double-spawning.
  - program      → run-to-result via the per-type contract.
  - doc          → return the rendered-view href (the /artifact route).

HARD: never bind / touch :8777 or real data. The service/program paths are
exercised with a STUBBED preview_server (injected) so the gate never spawns a
real long-running server on a real port — the never-8777 guard is asserted via
``preview_server.pick_free_port`` directly + an injected dead-pid record (the v3
preview-test pattern). Endpoint is token-gated + 404 on unknown deliverable.
"""
import importlib
import json
import threading
import time
from pathlib import Path

import pytest

CODE_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture
def deliv(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    monkeypatch.delenv("ANCHOR_BIND", raising=False)
    # Verify skills/tools against TEMP dirs — never the live ~/.claude/skills.
    monkeypatch.setenv("ANCHOR_SKILLS_DIR", str(tmp_path / "skills"))
    monkeypatch.setenv("ANCHOR_TOOLS_DIR", str(tmp_path / "tools"))
    import paths
    importlib.reload(paths)
    paths.ensure_data_dirs()
    import rnd_registry
    importlib.reload(rnd_registry)
    import job_runner
    importlib.reload(job_runner)
    import effort_history
    importlib.reload(effort_history)
    import report_viewer
    importlib.reload(report_viewer)
    import deliverables
    importlib.reload(deliverables)
    return deliverables


def _pin(deliverables, folder, pid, rel, dtype, **kw):
    """Pin a deliverable and return its content-addressed id (job_id)."""
    rec = deliverables.pin_deliverable(folder, pid, rel, dtype=dtype, **kw)
    return rec["job_id"], rec


# ── skill / tool → verify status, NO spawn ──────────────────────────────────

def test_skill_launch_reports_available_no_spawn(deliv, tmp_path):
    folder = tmp_path / "proj"
    folder.mkdir()
    (folder / "myskill.py").write_text("# skill\n", encoding="utf-8")
    # Present skill under the temp skills root → available.
    skills = tmp_path / "skills"
    (skills / "myskill").mkdir(parents=True)
    did, _ = _pin(deliv, str(folder), "p1", "myskill.py", deliv.TYPE_SKILL,
                  name="myskill")
    res = deliv.launch_deliverable(str(folder), "p1", did)
    assert res["ok"] is True
    assert res["type"] == "skill"
    assert res["kind"] == "skill"
    assert res["status"] == deliv.VERIFY_AVAILABLE
    # No process key — verification never spawns.
    assert "url" not in res and "record" not in res


def test_skill_launch_missing_when_absent(deliv, tmp_path):
    folder = tmp_path / "proj"
    folder.mkdir()
    (folder / "ghost.py").write_text("# x\n", encoding="utf-8")
    did, _ = _pin(deliv, str(folder), "p1", "ghost.py", deliv.TYPE_SKILL,
                  name="ghost")
    res = deliv.launch_deliverable(str(folder), "p1", did)
    assert res["ok"] is True
    assert res["status"] == deliv.VERIFY_MISSING


def test_tool_launch_verifies_against_tools_root_no_spawn(deliv, tmp_path):
    folder = tmp_path / "proj"
    folder.mkdir()
    (folder / "mytool.py").write_text("# tool\n", encoding="utf-8")
    tools = tmp_path / "tools"
    tools.mkdir(parents=True)
    (tools / "mytool.py").write_text("# tool entry\n", encoding="utf-8")
    did, _ = _pin(deliv, str(folder), "p1", "mytool.py", deliv.TYPE_TOOL,
                  name="mytool")
    res = deliv.launch_deliverable(str(folder), "p1", did)
    assert res["ok"] is True
    assert res["kind"] == "tool"
    assert res["status"] == deliv.VERIFY_AVAILABLE
    assert "url" not in res and "record" not in res


# ── doc → rendered-view href (no process) ───────────────────────────────────

def test_doc_launch_returns_rendered_href(deliv, tmp_path):
    folder = tmp_path / "proj"
    folder.mkdir()
    (folder / "README.md").write_text("# Hello\n", encoding="utf-8")
    did, _ = _pin(deliv, str(folder), "p1", "README.md", deliv.TYPE_DOC)
    res = deliv.launch_deliverable(str(folder), "p1", did)
    assert res["ok"] is True
    assert res["type"] == "doc"
    href = res["href"]
    assert href.startswith("/artifact/p1?path=")
    assert "README.md" in href
    assert "url" not in res  # no process / no preview


# ── never-8777: the free-port guard holds ───────────────────────────────────

def test_pick_free_port_guard_never_8777(deliv):
    import preview_server
    importlib.reload(preview_server)
    port = preview_server.pick_free_port()
    assert port != 8777 == preview_server.LIVE_PORT
    assert 1 <= port <= 65535


# ── service → persistent preview, pull-up-if-running (STUBBED, no real spawn) ─

class _StubPreview:
    """A stub preview_server: records start calls, never spawns a real server.

    Models the contract launch_deliverable depends on: ``start_preview`` returns
    an ``ok`` record on an OS-assigned port asserted != 8777 (via the REAL
    pick_free_port guard), and ``list_previews`` reflects what was started so the
    pull-up path can find a RUNNING preview for the same target.
    """
    STATUS_RUNNING = "running"
    LIVE_PORT = 8777

    def __init__(self):
        import preview_server as _real
        self._pick = _real.pick_free_port  # the REAL never-8777 guard
        self.records = {}
        self.start_calls = 0

    def list_previews(self, project_id=None):
        return [r for r in self.records.values()
                if project_id is None or r.get("project_id") == project_id]

    def start_preview(self, folder_path, project_id, target=None, **kw):
        self.start_calls += 1
        port = self._pick()                 # OS-assigned, hard-guarded != 8777
        assert port != self.LIVE_PORT
        pvid = f"stub-{self.start_calls}"
        rec = {"preview_id": pvid, "project_id": project_id, "target": target,
               "port": port, "url": f"http://127.0.0.1:{port}/",
               "status": self.STATUS_RUNNING}
        self.records[pvid] = rec
        return {"ok": True, "preview_id": pvid, "url": rec["url"], "port": port}


def test_service_launch_starts_preview_on_free_port_then_pulls_up(deliv,
                                                                  tmp_path):
    folder = tmp_path / "proj"
    folder.mkdir()
    (folder / "scene-engine.py").write_text("# server\n", encoding="utf-8")
    did, _ = _pin(deliv, str(folder), "p1", "scene-engine.py",
                  deliv.TYPE_SERVICE, name="scene-engine.py")
    stub = _StubPreview()

    # First launch → starts a NEW preview on a free port != 8777.
    res = deliv.launch_deliverable(str(folder), "p1", did, preview_mod=stub)
    assert res["ok"] is True
    assert res["type"] == "service"
    assert res["pulled_up"] is False
    assert res["port"] != 8777
    assert stub.start_calls == 1
    first_url = res["url"]

    # Second launch → PULLS UP the running one (no second spawn).
    res2 = deliv.launch_deliverable(str(folder), "p1", did, preview_mod=stub)
    assert res2["ok"] is True
    assert res2["pulled_up"] is True
    assert res2["url"] == first_url
    assert stub.start_calls == 1  # NOT double-spawned


def test_service_launch_clean_failure_when_preview_does_not_start(deliv,
                                                                  tmp_path):
    folder = tmp_path / "proj"
    folder.mkdir()
    (folder / "svc.py").write_text("# server\n", encoding="utf-8")
    did, _ = _pin(deliv, str(folder), "p1", "svc.py", deliv.TYPE_SERVICE)

    class _DeadStub(_StubPreview):
        def start_preview(self, *a, **k):
            return {"ok": False, "reason": "preview did not become reachable",
                    "port": 65000}

    res = deliv.launch_deliverable(str(folder), "p1", did,
                                   preview_mod=_DeadStub())
    assert res["ok"] is False
    assert res["type"] == "service"
    assert "reachable" in res["reason"]
    assert res["port"] != 8777


# ── never-8777 with an injected dead-pid record (v3 preview pattern) ─────────

def test_service_pullup_ignores_dead_preview_record(deliv, tmp_path):
    """A non-running (dead/stopped) preview record for the target must NOT be
    pulled up — only a RUNNING preview is reused (else a fresh start happens)."""
    folder = tmp_path / "proj"
    folder.mkdir()
    (folder / "svc.py").write_text("# server\n", encoding="utf-8")
    did, _ = _pin(deliv, str(folder), "p1", "svc.py", deliv.TYPE_SERVICE)
    stub = _StubPreview()
    # Inject a DEAD (stopped) record for the same target — must be skipped.
    stub.records["dead"] = {
        "preview_id": "dead", "project_id": "p1", "target": "svc.py",
        "port": 65111, "url": "http://127.0.0.1:65111/", "status": "stopped"}
    res = deliv.launch_deliverable(str(folder), "p1", did, preview_mod=stub)
    assert res["ok"] is True
    assert res["pulled_up"] is False     # dead record not pulled up
    assert stub.start_calls == 1         # a fresh preview was started
    assert res["port"] != 8777


# ── program → run-to-result (real tiny script, never a long-running server) ──

def test_program_launch_runs_to_result(deliv, tmp_path):
    folder = tmp_path / "proj"
    folder.mkdir()
    # A trivial program that exits 0 immediately (program contract = exit 0).
    (folder / "ok.py").write_text("import sys; sys.exit(0)\n", encoding="utf-8")
    did, _ = _pin(deliv, str(folder), "p1", "ok.py", deliv.TYPE_PROGRAM)
    res = deliv.launch_deliverable(str(folder), "p1", did, timeout=30.0)
    assert res["ok"] is True
    assert res["type"] == "program"
    assert res["status"] == deliv.STATUS_SUCCESS
    assert res["record"]["exit_code"] == 0


# ── unknown deliverable id → clean refusal ──────────────────────────────────

def test_unknown_deliverable_id_is_clean_refusal(deliv, tmp_path):
    folder = tmp_path / "proj"
    folder.mkdir()
    res = deliv.launch_deliverable(str(folder), "p1", "no-such-id")
    assert res["ok"] is False
    assert res["reason"] == "unknown deliverable"


# ── Endpoint: token-gated + 404 on unknown deliverable ──────────────────────

def _post(url, payload, token=None):
    import urllib.error
    import urllib.request
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if token is not None:
        req.add_header("X-Anchor-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_launch_endpoint_token_gated_and_404(monkeypatch, tmp_path):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    # Placeholder token on the distro-scan allowlist.
    monkeypatch.setenv("ANCHOR_TOKEN", "tok-123")
    monkeypatch.delenv("ANCHOR_BIND", raising=False)
    monkeypatch.setenv("ANCHOR_SKILLS_DIR", str(tmp_path / "skills"))
    import paths
    importlib.reload(paths)
    paths.ensure_data_dirs()
    import rnd_registry
    importlib.reload(rnd_registry)
    import deliverables
    importlib.reload(deliverables)
    import anchor_gui
    gui = importlib.reload(anchor_gui)

    # Register a real project so the handler resolves the folder.
    folder = tmp_path / "proj"
    folder.mkdir()
    (folder / "README.md").write_text("# x\n", encoding="utf-8")
    proj = rnd_registry.add_project("Demo", str(folder))
    pid = proj["id"]
    rec = deliverables.pin_deliverable(str(folder), pid, "README.md",
                                       dtype=deliverables.TYPE_DOC)
    did = rec["job_id"]

    server = gui.make_server("127.0.0.1", 0)
    port = server.server_address[1]
    assert port != 8777
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{port}"
        # No token → 401 (before any dispatch).
        code, _ = _post(base + "/api/rnd/launch_deliverable",
                        {"project_id": pid, "deliverable_id": did})
        assert code == 401

        # Right token, unknown project → 404.
        code, _ = _post(base + "/api/rnd/launch_deliverable",
                        {"project_id": "no-such", "deliverable_id": did},
                        token="tok-123")
        assert code == 404

        # Right token, known project, unknown deliverable id → 404.
        code, raw = _post(base + "/api/rnd/launch_deliverable",
                          {"project_id": pid, "deliverable_id": "nope"},
                          token="tok-123")
        assert code == 404
        body = json.loads(raw)
        assert body["ok"] is False
        assert body["reason"] == "unknown-deliverable"

        # Right token, real doc deliverable → 200 with a rendered href.
        code, raw = _post(base + "/api/rnd/launch_deliverable",
                          {"project_id": pid, "deliverable_id": did},
                          token="tok-123")
        assert code == 200
        body = json.loads(raw)
        assert body["ok"] is True
        assert body["type"] == "doc"
        assert body["href"].startswith("/artifact/")
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=5)
