import importlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


@pytest.fixture
def settings(tmp_path, monkeypatch):
    data, home = tmp_path / "data", tmp_path / "home"
    data.mkdir(); home.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    import paths
    import anchor_settings
    importlib.reload(paths)
    return importlib.reload(anchor_settings)


def test_policy_has_intent_not_a_model_name(settings):
    saved = settings.save_settings(default_cli="chatgpt", coding_family="chatgpt", review_family="grok")
    assert saved["model_policy"] == {"mode": "latest_supported", "effort": "highest_supported"}
    assert saved["settings_revision"] == 1
    assert settings.get_launch_settings() == saved
    assert json.loads(settings.mirror_path().read_text())["settings_revision"] == 1


def test_primary_wins_over_stale_mirror(settings, monkeypatch):
    settings.save_settings(default_cli="chatgpt", coding_family="chatgpt", review_family="grok")
    mirror = json.loads(settings.mirror_path().read_text())
    mirror["coding_family"] = "claude"
    settings.mirror_path().write_text(json.dumps(mirror))
    monkeypatch.delenv("ANCHOR_DATA_DIR")
    monkeypatch.setattr(settings, "settings_path", lambda: Path(mirror["primary_path"]))
    assert settings.load_settings()["coding_family"] == "chatgpt"
    assert settings.load_settings()["mirror_out_of_sync"]


def test_corrupt_primary_cannot_launch_or_partial_save(settings):
    settings.save_settings(default_cli="chatgpt", coding_family="chatgpt", review_family="grok")
    settings.settings_path().write_text("{broken")
    assert settings.load_settings()["settings_error"]
    with pytest.raises(settings.SettingsInvalid, match="invalid"):
        settings.get_launch_settings()
    with pytest.raises(settings.SettingsInvalid):
        settings.save_settings(default_cli="grok")
    assert settings.settings_path().read_text() == "{broken"


def test_missing_store_requires_setup_for_launch_but_can_save(settings):
    assert settings.load_settings()["settings_error"]
    with pytest.raises(settings.SettingsInvalid, match="not configured"):
        settings.get_launch_settings()
    settings.save_settings(default_cli="chatgpt", coding_family="chatgpt", review_family="grok")
    assert settings.get_launch_settings()["coding_family"] == "chatgpt"


def test_missing_primary_uses_valid_mirror_without_following_redirect(settings):
    settings.save_settings(default_cli="chatgpt", coding_family="chatgpt", review_family="grok")
    settings.settings_path().unlink()
    mirror = json.loads(settings.mirror_path().read_text())
    mirror["primary_path"] = "untrusted-redirect/settings.json"
    settings.mirror_path().write_text(json.dumps(mirror))
    assert settings.get_launch_settings()["coding_family"] == "chatgpt"
    assert settings.read_settings_state()["source"] == str(settings.mirror_path())


def test_invalid_policy_does_not_become_a_display_default_for_launch(settings):
    settings.save_settings(default_cli="chatgpt", coding_family="chatgpt", review_family="grok")
    raw = json.loads(settings.settings_path().read_text())
    raw["model_policy"] = {"mode": "pinned", "model": "historical-name"}
    settings.settings_path().write_text(json.dumps(raw))
    assert settings.load_settings()["settings_error"]
    with pytest.raises(settings.SettingsInvalid):
        settings.get_launch_settings()


def test_revision_conflict_and_persona_preservation(settings):
    first = settings.save_settings(default_cli="chatgpt", coding_family="chatgpt", review_family="grok", steward_type="jarvis")
    settings.save_settings(default_cli="grok", expected_revision=first["settings_revision"])
    with pytest.raises(settings.SettingsInvalid, match="changed"):
        settings.save_settings(coding_family="claude", expected_revision=first["settings_revision"])
    current = settings.get_launch_settings()
    assert current["steward_type"] == "jarvis"
    assert current["coding_family"] == "chatgpt"


def test_concurrent_disjoint_saves_do_not_lose_fields(settings):
    settings.save_settings(default_cli="chatgpt", coding_family="chatgpt", review_family="grok")
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = [workers.submit(settings.save_settings, steward_type="jarvis"),
                   workers.submit(settings.save_settings, default_cli="grok")]
        for result in results:
            result.result()
    current = settings.get_launch_settings()
    assert current["steward_type"] == "jarvis"
    assert current["default_cli"] == "grok"
    assert current["settings_revision"] == 3


def test_mirror_failure_does_not_undo_primary(settings, monkeypatch):
    settings.save_settings(default_cli="chatgpt", coding_family="chatgpt", review_family="grok")
    original = settings._atomic_write_json
    def fail_mirror(path, obj):
        if path == settings.mirror_path():
            raise OSError("synthetic mirror failure")
        original(path, obj)
    monkeypatch.setattr(settings, "_atomic_write_json", fail_mirror)
    result = settings.save_settings(default_cli="grok")
    assert result["default_cli"] == "grok"
    assert result["mirror_out_of_sync"]
    assert settings.get_launch_settings()["default_cli"] == "grok"
    assert settings.export_env_overrides()["ANCHOR_DATA_DIR"] == str(settings.settings_path().parent)
