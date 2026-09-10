"""Settings POST compare-and-swap canaries using isolated real persistence.

No HTTP server, CLI, capability discovery, or author-profile file is touched.
Both primary and mirror paths are validated inside tmp_path before the seed save.
"""

import importlib
from pathlib import Path
import sys

import pytest


POLICY = {"mode": "latest_supported", "effort": "highest_supported"}


class Handler:
    def __init__(self):
        self.responses = []

    def _send_json(self, payload, status=200):
        self.responses.append((status, payload))


@pytest.fixture
def settings_route(monkeypatch, tmp_path):
    # Restore already-imported module dictionaries rather than reloading paths
    # after the sandbox is removed; teardown must not initialize host storage.
    previous = {
        name: (sys.modules[name], dict(sys.modules[name].__dict__))
        for name in ("paths", "anchor_settings") if name in sys.modules
    }
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    data_dir = tmp_path / "anchor-data"
    try:
        with monkeypatch.context() as patch:
            patch.setattr(Path, "home", classmethod(lambda cls: fake_home))
            patch.setenv("HOME", str(fake_home))
            patch.setenv("USERPROFILE", str(fake_home))
            patch.setenv("APPDATA", str(fake_home / "AppData" / "Roaming"))
            patch.setenv("LOCALAPPDATA", str(fake_home / "AppData" / "Local"))
            patch.setenv("ANCHOR_DATA_DIR", str(data_dir))

            paths = importlib.import_module("paths")
            importlib.reload(paths)
            settings = importlib.import_module("anchor_settings")
            importlib.reload(settings)
            gui = importlib.import_module("anchor_gui")
            patch.setattr(gui, "_aset", settings)
            patch.setattr(gui, "_model_capability_fields", lambda *args, **kwargs: {})
            patch.setattr(settings, "export_env_overrides", lambda *args, **kwargs: {})
            patch.setattr(settings, "families_are_cross_model", lambda *args, **kwargs: True)

            primary = Path(settings.settings_path()).resolve()
            mirror = Path(settings.mirror_path()).resolve()
            boundary = tmp_path.resolve()
            assert primary.is_relative_to(boundary), "Primary settings must remain inside the test boundary"
            assert mirror.is_relative_to(boundary), "Preference mirror must remain inside the test boundary"

            settings.save_settings(
                default_cli="chatgpt", coding_family="chatgpt", review_family="grok",
                steward_type="jarvis", model_policy=dict(POLICY),
            )
            assert settings.get_launch_settings()["settings_revision"] == 1
            assert primary.exists() and mirror.exists()
            yield gui, settings, primary, mirror
    finally:
        for module, namespace in previous.values():
            module.__dict__.clear()
            module.__dict__.update(namespace)


def post(gui, body):
    handler = Handler()
    gui.handle_settings_post(handler, "/api/settings", body)
    assert len(handler.responses) == 1
    return handler.responses[0]


def snapshot(primary, mirror):
    return primary.read_bytes(), mirror.read_bytes()


def test_settings_post_advances_revision_then_rejects_stale_update_without_clobbering(settings_route):
    gui, settings, primary, mirror = settings_route
    status, payload = post(gui, {"expected_revision": 1, "default_cli": "grok"})
    assert status == 200 and payload["ok"] is True
    current = settings.get_launch_settings()
    assert current["settings_revision"] == 2
    assert current["default_cli"] == "grok"
    assert current["coding_family"] == "chatgpt" and current["review_family"] == "grok"
    assert current["steward_type"] == "jarvis"
    assert current["model_policy"] == POLICY

    accepted_bytes = snapshot(primary, mirror)
    status, payload = post(gui, {"expected_revision": 1, "coding_family": "claude"})
    assert status == 409 and payload["ok"] is False
    assert payload.get("error")
    assert snapshot(primary, mirror) == accepted_bytes
    current = settings.get_launch_settings()
    assert current["settings_revision"] == 2
    assert current["default_cli"] == "grok" and current["coding_family"] == "chatgpt"


@pytest.mark.parametrize("invalid_revision", [True, False, -1, "1", "latest", 1.5])
def test_settings_post_rejects_invalid_revision_types_without_changing_either_store(
    settings_route, invalid_revision,
):
    gui, settings, primary, mirror = settings_route
    before = snapshot(primary, mirror)
    status, payload = post(gui, {
        "expected_revision": invalid_revision, "default_cli": "claude",
    })
    assert status == 400 and payload["ok"] is False
    assert payload.get("error")
    assert snapshot(primary, mirror) == before
    current = settings.get_launch_settings()
    assert current["settings_revision"] == 1
    assert current["default_cli"] == "chatgpt"


@pytest.mark.parametrize("pinned_policy", [
    {"mode": "pinned", "model": "gpt-synthetic-pin", "effort": "highest_supported"},
    {"mode": "latest_supported", "effort": "highest_supported", "model": "gpt-synthetic-pin"},
])
def test_settings_post_rejects_pinned_policy_intent_and_preserves_current_preferences(
    settings_route, pinned_policy,
):
    gui, settings, primary, mirror = settings_route
    before = snapshot(primary, mirror)
    status, payload = post(gui, {
        "expected_revision": 1, "model_policy": pinned_policy,
    })
    assert status == 400 and payload["ok"] is False
    assert payload.get("error")
    assert snapshot(primary, mirror) == before
    current = settings.get_launch_settings()
    assert current["settings_revision"] == 1
    assert current["model_policy"] == POLICY
    assert "model" not in current["model_policy"]
