"""Unit tests for the tidy-idy thin caller (no live job spawn)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import tidy_idy_runner as tidy


def test_resolve_entry_finds_worktree_or_env(tmp_path, monkeypatch):
    fake = tmp_path / "tidy-idy.mjs"
    fake.write_text("// entry\n", encoding="utf-8")
    monkeypatch.setenv(tidy.ENTRY_ENV, str(fake))
    assert tidy.resolve_entry() == fake.resolve()


def test_build_command_shape(tmp_path, monkeypatch):
    fake = tmp_path / "tidy-idy.mjs"
    fake.write_text("// entry\n", encoding="utf-8")
    root = tmp_path / "proj"
    root.mkdir()
    monkeypatch.setenv(tidy.ENTRY_ENV, str(fake))
    cmd = tidy.build_command(root, nonce_file=tmp_path / "nonce.json")
    assert cmd[0] == "node"
    assert cmd[1] == str(fake.resolve())
    assert cmd[2] == str(root.resolve())
    assert "--environment=anchor" in cmd
    assert "--json" in cmd
    assert any(a.startswith("--nonce-file=") for a in cmd)


def test_parse_panel_ready():
    log = (
        'noise\n'
        '{"event":"panel-ready","baseUrl":"http://127.0.0.1:9/","bootstrapFile":"C:/n.json"}\n'
        'more\n'
    )
    got = tidy.parse_panel_ready(log)
    assert got is not None
    assert got["event"] == "panel-ready"
    assert got["bootstrapFile"].endswith("n.json")


def test_read_bootstrap_file(tmp_path):
    p = tmp_path / "boot.json"
    p.write_text(json.dumps({"url": "http://127.0.0.1:9/?n=abc"}), encoding="utf-8")
    got = tidy.read_bootstrap_file(p)
    assert got["url"].startswith("http://127.0.0.1:9/")


def test_launch_refuses_missing_folder(tmp_path, monkeypatch):
    fake = tmp_path / "tidy-idy.mjs"
    fake.write_text("// entry\n", encoding="utf-8")
    monkeypatch.setenv(tidy.ENTRY_ENV, str(fake))
    out = tidy.launch_tidy_idy("proj", tmp_path / "nope")
    assert out["ok"] is False
    assert out["code"] == "no-folder"


def test_launch_refuses_missing_entry(tmp_path, monkeypatch):
    monkeypatch.delenv(tidy.ENTRY_ENV, raising=False)
    monkeypatch.setattr(tidy, "_DEFAULT_CANDIDATES", (tmp_path / "missing.mjs",))
    out = tidy.launch_tidy_idy("proj", tmp_path)
    assert out["ok"] is False
    assert out["code"] == "no-entry"


def test_route_table_registers_tidy_idy_run_and_status():
    import route_table
    keys = {(r.method, r.pattern) for r in route_table.ROUTES}
    assert ("POST", "/api/rnd/tidy_idy_run") in keys
    assert ("GET", "/api/rnd/tidy_idy_status") in keys
    assert ("GET", "/api/rnd/tidy_idy_proxy/") in keys
    assert ("POST", "/api/rnd/tidy_idy_proxy/") in keys


def test_migrated_handlers_include_tidy_idy_status():
    import anchor_gui
    assert "handle_tidy_idy_run" in anchor_gui._MIGRATED_HANDLERS
    assert "handle_tidy_idy_status" in anchor_gui._MIGRATED_HANDLERS
    assert "handle_tidy_idy_proxy" in anchor_gui._MIGRATED_HANDLERS


def test_tidy_idy_status_reads_query_from_handler_path(tmp_path, monkeypatch):
    """Strangler passes query-stripped path; handler must read handler.path."""
    import anchor_gui

    report = tmp_path / ".tidy-idy"
    report.mkdir()
    (report / "status.json").write_text(
        json.dumps({"phase": "analyzing", "progress": 42, "step": "save",
                    "message": "Running save…", "statusUrl": "http://127.0.0.1:9/"}),
        encoding="utf-8",
    )
    pid = "proj-status-query"
    monkeypatch.setattr(
        anchor_gui._rnd, "get_project",
        lambda p: {"folder_path": str(tmp_path)} if p == pid else None,
    )
    monkeypatch.setattr(
        tidy, "live_tool_endpoints",
        lambda _f: {
            "status": {}, "status_live": False, "panel_live": False,
            "any_live": False, "status_url": None, "panel_base": None, "open_url": None,
        },
    )
    # Avoid mark_status_stale rewriting our fixture mid-call when pid is dead.
    monkeypatch.setattr(tidy, "_pid_alive", lambda _p: True)
    monkeypatch.setattr(tidy, "mark_status_stale", lambda *_a, **_k: None)

    sent = {}

    class Handler:
        path = f"/api/rnd/tidy_idy_status?project_id={pid}&token=sekrit"

        def _send_json(self, obj, code=200):
            sent["code"] = code
            sent["obj"] = obj

    # Strangler path is query-stripped — this is what used to drop project_id.
    anchor_gui.handle_tidy_idy_status(Handler(), "/api/rnd/tidy_idy_status", None)
    assert sent.get("code") == 200, sent
    assert sent["obj"].get("ok") is True
    assert sent["obj"].get("progress") == 42

    # Without handler.path query, must still 400 (not silently invent a project).
    class Bare:
        path = "/api/rnd/tidy_idy_status"
        headers = {}

        def _send_json(self, obj, code=200):
            sent["code"] = code
            sent["obj"] = obj

    anchor_gui.handle_tidy_idy_status(Bare(), "/api/rnd/tidy_idy_status", None)
    assert sent.get("code") == 400
    assert "project_id" in (sent["obj"].get("error") or "")

    # Header-only project id (query stripped) must still succeed.
    class HdrOnly:
        path = "/api/rnd/tidy_idy_status"
        headers = {"X-Project-Id": pid}

        def _send_json(self, obj, code=200):
            sent["code"] = code
            sent["obj"] = obj

    anchor_gui.handle_tidy_idy_status(HdrOnly(), "/api/rnd/tidy_idy_status", None)
    assert sent.get("code") == 200, sent
    assert sent["obj"].get("ok") is True


def test_is_loopback_and_browser_open_url():
    assert tidy.is_loopback_url("http://127.0.0.1:55410/") is True
    assert tidy.is_loopback_url("http://example.com/") is False
    path = tidy.browser_open_url(
        "abc123",
        "http://127.0.0.1:55614/bootstrap/deadbeef",
    )
    assert path == "/api/rnd/tidy_idy_proxy/abc123/bootstrap/deadbeef"


def test_rewrite_proxied_body_rewrites_base():
    html = b'const BASE = "http://127.0.0.1:55614"; fetch(BASE + "/api/x")'
    out = tidy.rewrite_proxied_body(
        html,
        content_type="text/html",
        upstream_base="http://127.0.0.1:55614",
        public_base="/api/rnd/tidy_idy_proxy/pid",
    )
    assert b"127.0.0.1" not in out
    assert b"/api/rnd/tidy_idy_proxy/pid" in out


def test_proxy_ssrf_guard_refuses_non_loopback(tmp_path, monkeypatch):
    report = tmp_path / ".tidy-idy"
    report.mkdir()
    (report / "status.json").write_text(
        json.dumps({"panelBaseUrl": "http://evil.example:9", "phase": "panel-ready"}),
        encoding="utf-8",
    )
    # resolve uses status; is_loopback fails → no upstream
    out = tidy.proxy_to_loopback(tmp_path, method="GET", rel_path="/api/health")
    assert out["ok"] is False


def test_status_for_folder_reads_status_json(tmp_path, monkeypatch):
    report = tmp_path / ".tidy-idy"
    report.mkdir()
    (report / "status.json").write_text(
        json.dumps({
            "phase": "analyzing",
            "message": "Analyzing…",
            "statusUrl": "http://127.0.0.1:9/",
            "projectName": "demo",
            "progress": 55,
            "step": "analyze",
            "stepLabel": "Running analyze…",
            "stepIndex": 8,
            "stepTotal": 13,
            "startedAt": "2026-07-22T00:00:00.000Z",
        }),
        encoding="utf-8",
    )
    # Pretend the status server is still listening (unit test — no real port).
    monkeypatch.setattr(
        tidy,
        "live_tool_endpoints",
        lambda _folder: {
            "status": json.loads((report / "status.json").read_text(encoding="utf-8")),
            "status_live": True,
            "panel_live": False,
            "any_live": True,
            "status_url": "http://127.0.0.1:9/",
            "panel_base": None,
            "open_url": None,
        },
    )
    out = tidy.status_for_folder(tmp_path)
    assert out["ok"] is True
    assert out["phase"] == "analyzing"
    assert out["statusUrl"] == "http://127.0.0.1:9/"
    assert "Analyzing" in out["message"]
    assert out["progress"] == 55
    assert out["step"] == "analyze"
    assert out["stepIndex"] == 8


def test_launch_short_circuits_live_status(tmp_path, monkeypatch):
    """Second click: live status.json short-circuits without job_runner."""
    report = tmp_path / ".tidy-idy"
    report.mkdir()
    (report / "status.json").write_text(
        json.dumps({
            "phase": "scanning",
            "message": "Scanning…",
            "statusUrl": "http://127.0.0.1:60890/",
            "openUrl": "http://127.0.0.1:60890/?n=abc",
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(tidy, "resolve_entry", lambda: tmp_path / "never.mjs")
    monkeypatch.setattr(
        tidy,
        "live_tool_endpoints",
        lambda _folder: {
            "status": {},
            "status_live": True,
            "panel_live": False,
            "any_live": True,
            "status_url": "http://127.0.0.1:60890/",
            "panel_base": None,
            "open_url": None,
        },
    )

    def _boom(*_a, **_k):
        raise AssertionError("job_runner must not be called when a run is live")

    monkeypatch.setattr(tidy.job_runner, "launch_guarded", _boom)
    out = tidy.launch_tidy_idy("proj", tmp_path)
    assert out["ok"] is True
    assert out["already_running"] is True
    assert out["status_url"] == "http://127.0.0.1:60890/"


def test_launch_restarts_when_status_ports_are_dead(tmp_path, monkeypatch):
    """Stale panel-ready + dead ports must NOT short-circuit — start a new run."""
    report = tmp_path / ".tidy-idy"
    report.mkdir()
    (report / "status.json").write_text(
        json.dumps({
            "phase": "panel-ready",
            "message": "Triage Panel is ready.",
            "statusUrl": "http://127.0.0.1:1/",
            "panelBaseUrl": "http://127.0.0.1:1",
            "openUrl": "http://127.0.0.1:1/bootstrap/dead",
        }),
        encoding="utf-8",
    )
    entry = tmp_path / "tidy-idy.mjs"
    entry.write_text("// entry\n", encoding="utf-8")
    monkeypatch.setenv(tidy.ENTRY_ENV, str(entry))
    monkeypatch.setattr(
        tidy,
        "live_tool_endpoints",
        lambda _folder: {
            "status": {},
            "status_live": False,
            "panel_live": False,
            "any_live": False,
            "status_url": None,
            "panel_base": None,
            "open_url": None,
        },
    )
    launched = {}

    def _fake_launch(*_a, **_k):
        launched["yes"] = True
        return {
            "job_id": "job-test",
            "status": "running",
            "log_path": str(tmp_path / "x.log"),
        }

    monkeypatch.setattr(tidy.job_runner, "launch_guarded", _fake_launch)
    monkeypatch.setattr(tidy, "wait_for_event", lambda *_a, **_k: None)
    monkeypatch.setattr(tidy.job_runner, "_update_record", lambda *_a, **_k: None)
    out = tidy.launch_tidy_idy("proj", tmp_path, wait_for_status_s=0.1)
    assert launched.get("yes") is True
    assert out["ok"] is True
    assert out.get("already_running") is not True


def test_probe_loopback_alive_false_for_closed_port():
    assert tidy.probe_loopback_alive("http://127.0.0.1:1/api/health", timeout_s=0.2) is False


def test_probe_loopback_never_gets_bootstrap_path(monkeypatch):
    """Liveness must hit /api/health only — GET /bootstrap/<nonce> burns SC4 Option 1."""
    import urllib.request as ur

    seen = []

    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _urlopen(req, timeout=None):  # noqa: ARG001
        full = req.full_url if hasattr(req, "full_url") else req.get_full_url()
        seen.append(full)
        return _Resp()

    monkeypatch.setattr(ur, "urlopen", _urlopen)

    assert tidy.probe_loopback_alive(
        "http://127.0.0.1:58132/bootstrap/deadbeefcafebabe",
        timeout_s=0.5,
    ) is True
    assert seen == ["http://127.0.0.1:58132/api/health"]


def test_proxy_timeout_for_bootstrap_is_long():
    assert tidy._proxy_timeout_for("/bootstrap/abc") >= 180
    assert tidy._proxy_timeout_for("/api/heartbeat") == 30


def test_strip_anchor_auth_query():
    assert "token=" not in tidy._strip_anchor_auth_query("token=secret&x=1")
    assert "x=1" in tidy._strip_anchor_auth_query("token=secret&x=1")


def test_proxy_timeout_does_not_mark_status_stale(tmp_path, monkeypatch):
    """Soft timeouts must not kill a live Tailscale handoff (remote stuck-at-42% root cause)."""
    report = tmp_path / ".tidy-idy"
    report.mkdir()
    (report / "status.json").write_text(
        json.dumps({
            "phase": "panel-ready",
            "panelBaseUrl": "http://127.0.0.1:9",
            "openUrl": "http://127.0.0.1:9/bootstrap/abc",
            "progress": 100,
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        tidy,
        "resolve_proxy_upstream",
        lambda *_a, **_k: "http://127.0.0.1:9",
    )
    import urllib.request as ur

    def _boom(*_a, **_k):
        raise TimeoutError("timed out")

    monkeypatch.setattr(ur, "urlopen", _boom)
    marked = {"n": 0}
    monkeypatch.setattr(
        tidy,
        "mark_status_stale",
        lambda *_a, **_k: marked.__setitem__("n", marked["n"] + 1),
    )
    out = tidy.proxy_to_loopback(tmp_path, method="GET", rel_path="/bootstrap/abc")
    assert out.get("ok") is False
    assert out.get("code") == "proxy-timeout"
    assert marked["n"] == 0
    # status.json must still say panel-ready
    st = json.loads((report / "status.json").read_text(encoding="utf-8"))
    assert st.get("phase") == "panel-ready"
