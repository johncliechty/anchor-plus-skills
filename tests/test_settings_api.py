"""Settings API routes + handlers (no live server).

Hermetic pure tests: route_table rows exist, handlers are registered, and
handle_settings_get/post round-trip through a fake handler against a temp
data dir.
"""
import importlib
import json
from pathlib import Path
from urllib.parse import urlparse

import pytest


@pytest.fixture
def settings_stack(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    monkeypatch.setenv("ANCHOR_CLAUDE_AVAILABLE", "1")
    monkeypatch.setenv("ANCHOR_GEMINI_AVAILABLE", "1")
    monkeypatch.setenv("ANCHOR_GROK_AVAILABLE", "1")
    monkeypatch.setenv("ANCHOR_CHATGPT_AVAILABLE", "1")

    import paths
    importlib.reload(paths)
    paths.ensure_data_dirs()
    import anchor_settings
    importlib.reload(anchor_settings)
    import route_table
    importlib.reload(route_table)
    # Reload gui last so it picks up the reloaded settings module.
    import anchor_gui
    gui = importlib.reload(anchor_gui)
    return {
        "gui": gui,
        "routes": route_table,
        "settings": anchor_settings,
        "data": data,
    }


class _FakeHandler:
    """Minimal stand-in for AnchorHTTPRequestHandler used by unit tests."""

    def __init__(self):
        self.path = "/api/settings"
        self.headers = {}
        self._status = None
        self._payload = None
        self._code = None

    def _send_json(self, obj, code=200):
        self._code = code
        self._payload = obj
        self._status = code


def test_route_table_contains_settings_api(settings_stack):
    rt = settings_stack["routes"]
    rows = [(r.method, r.pattern) for r in rt.ROUTES]
    assert ("GET", "/api/settings") in rows
    assert ("POST", "/api/settings") in rows
    get_r = next(r for r in rt.ROUTES
                 if r.method == "GET" and r.pattern == "/api/settings")
    post_r = next(r for r in rt.ROUTES
                  if r.method == "POST" and r.pattern == "/api/settings")
    assert get_r.handler == "handle_settings_get"
    assert post_r.handler == "handle_settings_post"
    assert get_r.migrated is True
    assert post_r.migrated is True


def test_handlers_registered_in_migrated_map(settings_stack):
    gui = settings_stack["gui"]
    assert "handle_settings_get" in gui._MIGRATED_HANDLERS
    assert "handle_settings_post" in gui._MIGRATED_HANDLERS
    assert gui._MIGRATED_HANDLERS["handle_settings_get"] is gui.handle_settings_get
    assert gui._MIGRATED_HANDLERS["handle_settings_post"] is gui.handle_settings_post


def test_handle_settings_get_returns_defaults(settings_stack):
    gui = settings_stack["gui"]
    h = _FakeHandler()
    gui.handle_settings_get(h, "/api/settings", None)
    assert h._code == 200
    assert h._payload["ok"] is True
    assert h._payload["default_cli"] == "grok"
    assert h._payload["coding_family"] == "claude"
    assert h._payload["review_family"] == "gemini"
    assert h._payload["cross_model"] is True
    assert isinstance(h._payload.get("env"), dict)
    assert h._payload["env"]["ANCHOR_DEFAULT_CLI"] == "grok"
    assert "CROSS_MODEL" in h._payload["env"]
    caps = h._payload["model_capabilities"]
    assert caps["schema"] == "anchor.model-role-capabilities.v1"
    assert caps["roles"]["coder"]["families"]["chatgpt"]["selectable"] is True
    assert caps["roles"]["terminal"]["families"]["chatgpt"]["selectable"] is False
    assert caps["roles"]["reviewer"]["families"]["chatgpt"]["selectable"] is False
    assert caps["roles"]["judge"]["setting"] == "review_family"


def test_handle_settings_post_merge_and_reload(settings_stack):
    gui = settings_stack["gui"]
    h = _FakeHandler()
    gui.handle_settings_post(h, "/api/settings", {"default_cli": "claude"})
    assert h._code == 200
    assert h._payload["ok"] is True
    assert h._payload["default_cli"] == "claude"
    assert h._payload["coding_family"] == "claude"  # preserved default
    assert h._payload["review_family"] == "gemini"

    h2 = _FakeHandler()
    gui.handle_settings_get(h2, "/api/settings", None)
    assert h2._payload["default_cli"] == "claude"

    h3 = _FakeHandler()
    gui.handle_settings_post(h3, "/api/settings",
                             {"coding_family": "grok", "review_family": "grok"})
    assert h3._code == 200
    assert h3._payload["coding_family"] == "grok"
    assert h3._payload["review_family"] == "grok"
    assert h3._payload["cross_model"] is False
    assert h3._payload["default_cli"] == "claude"  # still preserved
    assert "model_capabilities" in h3._payload


def test_handle_settings_post_rejects_invalid(settings_stack):
    gui = settings_stack["gui"]
    h = _FakeHandler()
    gui.handle_settings_post(h, "/api/settings", {"default_cli": "not-a-cli"})
    assert h._code == 400
    assert h._payload["ok"] is False
    assert "invalid" in (h._payload.get("error") or "").lower()


def test_handle_settings_post_noop_returns_current(settings_stack):
    gui = settings_stack["gui"]
    h = _FakeHandler()
    gui.handle_settings_post(h, "/api/settings", {})
    assert h._code == 200
    assert h._payload["ok"] is True
    assert h._payload["default_cli"] == "grok"
