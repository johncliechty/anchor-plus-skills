"""Pure unit tests for ``anchor_settings`` (no network, no live CLI).

Covers load defaults, save merge, invalid rejection, mirror write, cross_model
flag, and export_env. Uses tmp_path + ANCHOR_DATA_DIR / HOME monkeypatches.
"""
import json
from pathlib import Path

import pytest


@pytest.fixture
def settings_env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    # pathlib.Path.home() on Windows prefers USERPROFILE; pin both + the
    # Path.home method so the mirror always lands under our tmp home.
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    import paths
    import importlib
    importlib.reload(paths)
    import anchor_settings
    importlib.reload(anchor_settings)
    return {
        "mod": anchor_settings,
        "data": data,
        "home": home,
        "paths": paths,
    }


def test_load_defaults_when_missing(settings_env):
    s = settings_env["mod"]
    out = s.load_settings()
    assert out["default_cli"] == "grok"
    assert out["coding_family"] == "claude"
    assert out["review_family"] == "gemini"
    assert "updated_at" in out
    assert out["default_cli"] in s.VALID_CLIS
    assert s.VALID_FAMILIES is s.VALID_CLIS or s.VALID_FAMILIES == s.VALID_CLIS


def test_load_defaults_when_corrupt(settings_env):
    s = settings_env["mod"]
    p = s.settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json", encoding="utf-8")
    out = s.load_settings()
    assert out["default_cli"] == "grok"
    assert out["coding_family"] == "claude"
    assert out["review_family"] == "gemini"


def test_save_merge_partial(settings_env):
    s = settings_env["mod"]
    first = s.save_settings(default_cli="claude")
    assert first["default_cli"] == "claude"
    assert first["coding_family"] == "claude"
    assert first["review_family"] == "gemini"

    second = s.save_settings(review_family="grok")
    assert second["default_cli"] == "claude"  # preserved
    assert second["review_family"] == "grok"
    assert second["coding_family"] == "claude"

    reloaded = s.load_settings()
    assert reloaded == second or (
        reloaded["default_cli"] == "claude"
        and reloaded["review_family"] == "grok"
    )


def test_save_rejects_invalid(settings_env):
    s = settings_env["mod"]
    with pytest.raises(ValueError):
        s.save_settings(default_cli="chatgpt")
    with pytest.raises(ValueError):
        s.save_settings(coding_family="not-a-family")
    # Nothing persisted on rejection.
    assert not s.settings_path().exists() or s.load_settings()["default_cli"] == "grok"


def test_mirror_write(settings_env):
    s = settings_env["mod"]
    out = s.save_settings(default_cli="gemini", coding_family="grok")
    primary = s.settings_path()
    mirror = s.mirror_path()
    assert primary.is_file()
    assert mirror.is_file()
    assert mirror == settings_env["home"] / ".anchor" / "model_prefs.json"

    primary_data = json.loads(primary.read_text(encoding="utf-8"))
    mirror_data = json.loads(mirror.read_text(encoding="utf-8"))
    assert primary_data["default_cli"] == "gemini"
    assert primary_data["coding_family"] == "grok"
    assert "source" not in primary_data
    assert mirror_data["source"] == "anchor"
    assert mirror_data["primary_path"] == str(primary.resolve())
    assert mirror_data["default_cli"] == out["default_cli"]
    assert mirror_data["coding_family"] == out["coding_family"]
    assert mirror_data["review_family"] == out["review_family"]


def test_cross_model_flag(settings_env):
    s = settings_env["mod"]
    # Defaults: coding=claude, review=gemini → cross-model
    assert s.families_are_cross_model() is True
    s.save_settings(coding_family="gemini", review_family="gemini")
    assert s.families_are_cross_model() is False
    s.save_settings(review_family="grok")
    assert s.families_are_cross_model() is True


def test_export_env(settings_env):
    s = settings_env["mod"]
    s.save_settings(
        default_cli="grok",
        coding_family="claude",
        review_family="gemini",
    )
    env = s.export_env_overrides()
    assert env["ANCHOR_DEFAULT_CLI"] == "grok"
    assert env["ANCHOR_CODING_FAMILY"] == "claude"
    assert env["ANCHOR_REVIEW_FAMILY"] == "gemini"
    assert env["CODING_FAMILY"] == "claude"
    assert env["REVIEW_FAMILY"] == "gemini"
    assert env["CROSS_MODEL"] == "true"

    s.save_settings(coding_family="gemini", review_family="gemini")
    env2 = s.export_env_overrides()
    assert env2["CROSS_MODEL"] == "false"


def test_resolve_tier_label(settings_env):
    s = settings_env["mod"]
    assert "frontier" in s.resolve_tier_label("claude", "heavy")
    assert s.resolve_tier_label("claude", "heavy").startswith("claude:")
    assert "one-notch-below-frontier" in s.resolve_tier_label("gemini", "standard")
    assert "one-notch-below-frontier" in s.resolve_tier_label("grok", "regular")


def test_getters(settings_env):
    s = settings_env["mod"]
    s.save_settings(
        default_cli="claude",
        coding_family="grok",
        review_family="claude",
    )
    assert s.get_default_cli() == "claude"
    assert s.get_coding_family() == "grok"
    assert s.get_review_family() == "claude"


def test_defaults_constant_and_valid_sets(settings_env):
    s = settings_env["mod"]
    assert s.DEFAULTS["default_cli"] == "grok"
    assert s.DEFAULTS["coding_family"] == "claude"
    assert s.DEFAULTS["review_family"] == "gemini"
    assert s.VALID_CLIS == frozenset({"claude", "gemini", "grok"})
