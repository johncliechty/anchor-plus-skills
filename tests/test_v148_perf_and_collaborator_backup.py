"""Tests for Anchor v1.4.8 Track A (GET / performance & Aegis SSRF hardening)
and Track B (Collaborator Git/GitHub auto-backup & upgrade state snapshots).
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest


def test_assert_loopback_http_url_blocks_non_loopback() -> None:
    import anchor_gui

    assert anchor_gui._assert_loopback_http_url("http://127.0.0.1:8791/status") == "http://127.0.0.1:8791/status"
    assert anchor_gui._assert_loopback_http_url("http://localhost:8777/api/version") == "http://localhost:8777/api/version"
    with pytest.raises(ValueError, match="Loopback HTTP/HTTPS URL required"):
        anchor_gui._assert_loopback_http_url("http://169.254.169.254/latest/meta-data")
    with pytest.raises(ValueError, match="URL must start with http:// or https://"):
        anchor_gui._assert_loopback_http_url("file:///C:/Windows/win.ini")


def test_scaffold_starter_cockpit_creates_gitignore_and_bak1(tmp_path: Path) -> None:
    import onboard_wizard

    proj = tmp_path / "collab_proj"
    res = onboard_wizard.scaffold_starter_ai_cockpit(proj, "Collaborator Project", user_display_name="Merrill")
    assert res["ok"] is True
    assert (proj / ".gitignore").is_file()
    assert ".anchor/" in (proj / ".gitignore").read_text(encoding="utf-8")
    assert (proj / "ECGBERHT.md.bak-1").is_file()
    assert (proj / "roadmap.json.bak-1").is_file()
    assert (proj / "strip.json.bak-1").is_file()
    assert (proj / "DELIVERABLES.md.bak-1").is_file()


def test_provision_live_project_bootstraps_git_and_optional_github(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import onboard_wizard
    import paths
    import project_bootstrap
    import project_remote
    import rnd_registry

    data_root = tmp_path / "data"
    data_root.mkdir(parents=True)
    monkeypatch.setattr(paths, "data_dir", lambda: data_root)
    monkeypatch.setattr(rnd_registry, "registry_path", lambda: data_root / "rnd_registry.json")

    boot_calls: list[tuple[str, str]] = []
    link_calls: list[tuple[str, str, str, str | None]] = []

    def fake_bootstrap(folder_path: str | Path, project_name: str = "") -> dict:
        fp = Path(folder_path)
        (fp / ".git").mkdir(parents=True, exist_ok=True)
        boot_calls.append((str(fp), project_name))
        return {"git_initialized": True, "claude_md_created": True, "committed": True, "reason": "ok"}

    def fake_link_github(folder_path: str | Path, mode: str, repo_or_url: str, *, project_id: str | None = None) -> dict:
        link_calls.append((str(folder_path), mode, repo_or_url, project_id))
        return {"ok": True, "remote_url": f"https://github.com/merrill/{repo_or_url}.git", "pushed": True, "error": None}

    monkeypatch.setattr(project_bootstrap, "bootstrap_project", fake_bootstrap)
    monkeypatch.setattr(project_remote, "link_github", fake_link_github)

    proj_dir = tmp_path / "merrill_study"
    proj_dir.mkdir(parents=True)

    out = onboard_wizard.provision_projects_and_cockpits(
        [{"name": "Merrill Study", "folder_path": str(proj_dir), "seat": "active"}],
        auto_github_backup=True,
        sandbox=False,
        base_dir=data_root,
    )
    assert out["ok"] is True
    assert out["count"] == 1
    p0 = out["provisioned"][0]
    assert p0["git_initialized"] is True
    assert p0["github_backup"]["ok"] is True
    assert p0["github_backup"]["auto_push"] is True
    assert project_remote.get_auto_push(p0["id"]) is True
    assert any(name == "Merrill Study" for _, name in boot_calls)
    assert any(name == "Campaign" for _, name in boot_calls)
    assert len(link_calls) == 1


def test_shell_connect_migrates_and_snapshots_collaborator_state(tmp_path: Path) -> None:
    from shell import connect

    ws_home = tmp_path / "ws"
    old_anchor = ws_home / "Anchor-old"
    new_anchor = ws_home / "Anchor"
    (old_anchor / "domains").mkdir(parents=True)
    (old_anchor / ".anchor" / "projects" / "p1").mkdir(parents=True)
    (new_anchor).mkdir(parents=True)

    (old_anchor / "rnd_registry.json").write_text('{"version":1,"projects":[{"id":"p1","name":"KeepMe"}]}', encoding="utf-8")
    (old_anchor / "steward-cockpit-state.json").write_text('{"saved":true}', encoding="utf-8")
    (old_anchor / "domains" / "academic.md").write_text("# My Academic Tasks\n", encoding="utf-8")
    (old_anchor / ".anchor" / "projects" / "p1" / "meta.json").write_text('{"id":"p1"}', encoding="utf-8")

    # New anchor has starter smaller academic.md
    (new_anchor / "domains").mkdir(parents=True)
    (new_anchor / "domains" / "academic.md").write_text("# My Academic Tasks\n- [ ] extra task\n", encoding="utf-8")
    # Make old_anchor's academic.md larger so it wins migration
    (old_anchor / "domains" / "academic.md").write_text("# My Academic Tasks\n" + ("- [ ] user task\n" * 10), encoding="utf-8")

    connect._migrate_user_data_if_needed(old_anchor, new_anchor)
    assert (new_anchor / "rnd_registry.json").is_file()
    assert "KeepMe" in (new_anchor / "rnd_registry.json").read_text(encoding="utf-8")
    assert (new_anchor / "steward-cockpit-state.json").is_file()
    assert (new_anchor / ".anchor" / "projects" / "p1" / "meta.json").is_file()
    assert "user task" in (new_anchor / "domains" / "academic.md").read_text(encoding="utf-8")

    snap = connect._snapshot_collaborator_state_before_upgrade(new_anchor, ws_home)
    assert snap is not None
    assert (snap / "rnd_registry.json").is_file()
    assert (snap / "steward-cockpit-state.json").is_file()
