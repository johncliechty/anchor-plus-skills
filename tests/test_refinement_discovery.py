"""Distribution discovery without consulting any installed host skill."""

import os
from pathlib import Path

import pytest

from steward_cockpit import refinement_client as client


def present(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("// Discovery fixture; never executed.\n", encoding="utf-8")
    return path


@pytest.fixture
def locations(tmp_path, monkeypatch):
    home = tmp_path / "profile"
    anchor = tmp_path / "anchor-installation"
    module_file = anchor / "steward_cockpit" / "refinement_client.py"
    monkeypatch.delenv(client.CLI_ENV, raising=False)
    monkeypatch.delenv(client.SKILLS_ROOT_ENV, raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(client, "__file__", str(module_file))
    monkeypatch.setattr(client.shutil, "which", lambda executable: "node-in-test")

    bundled = anchor / "vendor" / "bundled-skills" / "ecgberht" / "bin" / "ecgberht.mjs"
    agents = home / ".agents" / "skills" / "ecgberht" / "bin" / "ecgberht.mjs"
    claude = home / ".claude" / "skills" / "ecgberht" / "bin" / "ecgberht.mjs"
    legacy = tmp_path / "legacy-development-checkout" / "bin" / "ecgberht.mjs"

    # Assert the real discovery order, then substitute its only absolute host
    # fallback before any dependency resolution can inspect that path.
    defaults = client._default_cli_candidates()
    assert defaults[:3] == [bundled, agents, claude]
    if os.name == "nt":
        assert defaults[3:] == [Path("C:/dev/Ecgberht/bin/ecgberht.mjs")]
    else:
        assert defaults[3:] == []
    monkeypatch.setattr(client, "_default_cli_candidates", lambda: defaults[:3] + [legacy])
    return {"bundled": bundled, "agents": agents, "claude": claude, "legacy": legacy,
            "explicit_root": tmp_path / "configured-skills", "root": tmp_path}


def chosen(expected):
    assert client._resolve_dependencies(None, None) == ("node-in-test", str(expected.resolve()))


def test_bundled_installation_precedes_both_profiles_and_development_checkout(locations):
    for name in ("bundled", "agents", "claude", "legacy"):
        present(locations[name])
    chosen(locations["bundled"])


def test_explicit_cli_argument_precedes_environment_and_installation_root(locations, monkeypatch):
    argument_cli = present(locations["root"] / "argument" / "ecgberht.mjs")
    env_cli = present(locations["root"] / "environment" / "ecgberht.mjs")
    root_cli = present(locations["explicit_root"] / "ecgberht" / "bin" / "ecgberht.mjs")
    present(locations["bundled"])
    monkeypatch.setenv(client.CLI_ENV, str(env_cli))
    monkeypatch.setenv(client.SKILLS_ROOT_ENV, str(root_cli.parents[2]))
    assert client._resolve_dependencies(argument_cli, None) == ("node-in-test", str(argument_cli.resolve()))


def test_explicit_cli_environment_precedes_installation_root(locations, monkeypatch):
    env_cli = present(locations["root"] / "environment" / "ecgberht.mjs")
    present(locations["explicit_root"] / "ecgberht" / "bin" / "ecgberht.mjs")
    present(locations["bundled"])
    monkeypatch.setenv(client.CLI_ENV, str(env_cli))
    monkeypatch.setenv(client.SKILLS_ROOT_ENV, str(locations["explicit_root"]))
    chosen(env_cli)


def test_explicit_skills_root_precedes_bundled_and_profile_skills(locations, monkeypatch):
    expected = present(locations["explicit_root"] / "ecgberht" / "bin" / "ecgberht.mjs")
    for name in ("bundled", "agents", "claude", "legacy"):
        present(locations[name])
    monkeypatch.setenv(client.SKILLS_ROOT_ENV, str(locations["explicit_root"]))
    chosen(expected)


@pytest.mark.parametrize("configured", ["missing", "empty"])
def test_missing_or_empty_explicit_root_never_uses_a_default(locations, monkeypatch, configured):
    for name in ("bundled", "agents", "claude", "legacy"):
        present(locations[name])
    monkeypatch.setenv(client.SKILLS_ROOT_ENV, str(locations["explicit_root"]) if configured == "missing" else "")
    failure = client._resolve_dependencies(None, None)
    assert failure["ok"] is False
    assert failure["error"] == "dependency-missing"
    assert failure["component"] == "cli"
    assert failure["configured"] is True


def test_existing_explicit_root_without_ecgberht_does_not_fall_back(locations, monkeypatch):
    locations["explicit_root"].mkdir()
    present(locations["bundled"])
    monkeypatch.setenv(client.SKILLS_ROOT_ENV, str(locations["explicit_root"]))
    failure = client._resolve_dependencies(None, None)
    assert failure["error"] == "dependency-missing"
    assert failure["configured"] is True


def test_missing_explicit_cli_stays_authoritative_over_a_valid_root(locations, monkeypatch):
    present(locations["explicit_root"] / "ecgberht" / "bin" / "ecgberht.mjs")
    present(locations["bundled"])
    monkeypatch.setenv(client.SKILLS_ROOT_ENV, str(locations["explicit_root"]))
    monkeypatch.setenv(client.CLI_ENV, str(locations["root"] / "missing-cli.mjs"))
    failure = client._resolve_dependencies(None, None)
    assert failure["error"] == "dependency-missing"
    assert failure["configured"] is True


def test_missing_cli_argument_does_not_use_valid_cli_environment(locations, monkeypatch):
    env_cli = present(locations["root"] / "valid-env-cli.mjs")
    monkeypatch.setenv(client.CLI_ENV, str(env_cli))
    failure = client._resolve_dependencies(locations["root"] / "missing-argument.mjs", None)
    assert failure["error"] == "dependency-missing"
    assert failure["configured"] is True


def test_agents_profile_precedes_claude_and_legacy_fallbacks(locations):
    for name in ("agents", "claude", "legacy"):
        present(locations[name])
    chosen(locations["agents"])


def test_existing_claude_profile_remains_a_fallback(locations):
    present(locations["claude"])
    present(locations["legacy"])
    chosen(locations["claude"])


def test_development_checkout_is_only_the_last_fallback(locations):
    present(locations["legacy"])
    chosen(locations["legacy"])


def test_no_candidates_reports_missing_without_host_installation_leak(locations):
    failure = client._resolve_dependencies(None, None)
    assert failure["error"] == "dependency-missing"
    assert failure["configured"] is False


def test_old_cli_without_handoff_actions_is_explicitly_incompatible():
    from unittest.mock import patch
    from steward_cockpit import refinement_client
    old = {"ok": True, "capabilities": {"schema": refinement_client.PROTOCOL_SCHEMA, "version": 1}}
    with patch.object(refinement_client, "_resolve_dependencies", return_value=("node", "old-cli")), patch.object(refinement_client, "_run", return_value=old) as run:
        result = refinement_client.update("campaign", {"action":"producer_handoff", "operation_id":"owned", "expected_seq":1})
    assert result["error"] == "dependency-incompatible"
    assert run.call_count == 1
