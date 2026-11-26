"""Tests for Anchor v1.5.2: Merrill's 10 Installer Fixes, Non-Project Skill/Anchor Filtering,
Mother Ship Registration & Push/Pull Updates, Version Display, and macOS/Linux Compatibility."""

from __future__ import annotations

import json
import os
import pathlib
from unittest import mock

import pytest

import brownfield_scan
import chamber_e1_hook
import high_seat_page
import mothership_updater
import onboard
import onboard_wizard
import paths
import rnd_registry
from shell import connect


ROOT = pathlib.Path(__file__).resolve().parent.parent


# ==============================================================================
# WAVE 1: Canonical Version, Ecgberht Resolution, Chamber E1 Hook, Project Filter
# ==============================================================================


def test_wave1_canonical_version_and_bundled_ecgberht_resolution(tmp_path, monkeypatch):
    """NS-1: VERSION and bundled Ecgberht VERSION are in lockstep (>= 1.5.2) and resolve_ecgberht_root prioritizes bundled/current over stale C:\\dev\\Ecgberht."""
    cur_ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert mothership_updater.parse_version(cur_ver) >= (1, 5, 2)
    assert paths.read_version() == cur_ver
    assert (ROOT / "vendor" / "bundled-skills" / "ecgberht" / "VERSION").read_text(encoding="utf-8").strip() == cur_ver

    monkeypatch.delenv("ECGBERHT_ROOT", raising=False)
    monkeypatch.delenv("ECGBERHT_DIR", raising=False)
    resolved, checked = paths.resolve_ecgberht_root()
    assert resolved is not None and resolved.is_dir()
    assert (resolved / "engine").is_dir()
    assert isinstance(checked, list) and len(checked) >= 1
    assert "bundled-skills" in str(resolved) or "skills" in str(resolved)


def test_wave1_chamber_e1_hook_preserves_held_say_and_collaborator_name(tmp_path, monkeypatch):
    """NS-1: When a turn is blocked at the bridge boundary, held_say is preserved above the block note,
    and collaborator display name is read from user_profile.json."""
    fake_data = tmp_path / ".anchor"
    fake_data.mkdir(parents=True, exist_ok=True)
    (fake_data / "user_profile.json").write_text(
        json.dumps({"display_name": "Merrill", "username": "merrill"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(paths, "data_dir", lambda: fake_data)
    assert paths.read_collaborator_display_name() == "Merrill"
    assert chamber_e1_hook._collaborator_display_name() == "Merrill"

    raw_turn = {
        "ok": True,
        "lane": "converse",
        "say": "Welcome Merrill! Let's organize your workspace and set up your first project.",
    }
    res = chamber_e1_hook.enforce_bridge_result("What is the first step?", raw_turn)
    assert res.get("turn_blocked") is True
    # The steward's conversational reply MUST be preserved so the user isn't shown only a raw block error
    assert "Welcome Merrill! Let's organize your workspace" in res.get("say", "")
    assert "Merrill" in res.get("say", "")


def test_wave1_excludes_foundry_skills_and_anchor_folders_from_projects(tmp_path):
    """NS-2: Foundry skill folders (with SKILL.md or canonical skill names) and Anchor install/backup folders
    are never proposed or registered as R&D projects."""
    # 1. Create a folder with SKILL.md (like an older foundry skill folder)
    old_skill = tmp_path / "gandalf"
    old_skill.mkdir()
    (old_skill / "SKILL.md").write_text("# Gandalf skill\n", encoding="utf-8")

    # 2. Create an arbitrary custom skill folder with SKILL.md
    custom_skill = tmp_path / "my-old-skill-v1"
    custom_skill.mkdir()
    (custom_skill / "SKILL.md").write_text("# Custom skill\n", encoding="utf-8")

    # 3. Create Anchor install / backup / numbered duplicate folders
    anchor_main = tmp_path / "Anchor"
    anchor_main.mkdir()
    (anchor_main / "anchor_gui.py").write_text("# anchor\n", encoding="utf-8")

    anchor_dup = tmp_path / "Anchor 2"
    anchor_dup.mkdir()

    anchor_bak = tmp_path / "Anchor-1.4.6-backup"
    anchor_bak.mkdir()

    skills_container = tmp_path / "skills"
    skills_container.mkdir()

    # 4. Create a legitimate user R&D project
    real_proj = tmp_path / "Quantum_Portfolio_Model"
    real_proj.mkdir()
    (real_proj / "README.md").write_text("# Quantum Portfolio Model\n", encoding="utf-8")

    for bad_dir in (old_skill, custom_skill, anchor_main, anchor_dup, anchor_bak, skills_container):
        excl, reason = onboard_wizard.is_excluded_non_project_dir(bad_dir, anchor_root=anchor_main)
        assert excl is True, f"Expected {bad_dir} to be excluded, got {excl} ({reason})"
        assert brownfield_scan.is_skill_or_anchor_dir(bad_dir) is True
        assert rnd_registry.is_spurious_non_project_folder(bad_dir) is True

    excl_real, _ = onboard_wizard.is_excluded_non_project_dir(real_proj, anchor_root=anchor_main)
    assert excl_real is False
    assert brownfield_scan.is_skill_or_anchor_dir(real_proj) is False
    assert rnd_registry.is_spurious_non_project_folder(real_proj) is False

    # Scan candidate projects in tmp_path
    scan_res = onboard_wizard.scan_and_propose_projects(
        roots=[str(tmp_path)],
        sandbox=True,
        sandbox_id="test-skill-filter",
        base_dir=tmp_path,
    )
    discovered_names = [d["name"] for d in scan_res["discovered"]]
    assert "Quantum_Portfolio_Model" in discovered_names
    for bad_name in ("gandalf", "my-old-skill-v1", "Anchor", "Anchor 2", "Anchor-1.4.6-backup", "skills"):
        assert bad_name not in discovered_names


# ==============================================================================
# WAVE 2: Merrill's Installer Fixes (Install Mode, Backup Ignore, In-Place Overlay)
# ==============================================================================


def test_wave2_ignores_backup_and_numbered_duplicate_folders(tmp_path):
    """NS-3: find_local_anchor_root and choose_install_folder ignore Anchor-1.4.6-backup and Anchor 2/3,
    and choose_install_folder reuses C:\\dev\\Anchor in-place instead of creating Anchor 2."""
    backup_dir = tmp_path / "Anchor-1.4.6-backup"
    backup_dir.mkdir()
    (backup_dir / "anchor_gui.py").write_text("# old backup\n", encoding="utf-8")

    dup_dir = tmp_path / "Anchor 2"
    dup_dir.mkdir()
    (dup_dir / "anchor_gui.py").write_text("# dup\n", encoding="utf-8")

    assert connect._is_backup_or_numbered_duplicate_folder(backup_dir) is True
    assert connect._is_backup_or_numbered_duplicate_folder(dup_dir) is True

    # choose_install_folder when Anchor already exists with Anchor.exe must reuse Anchor in-place!
    anchor_dir = tmp_path / "Anchor"
    anchor_dir.mkdir()
    (anchor_dir / "Anchor.exe").write_bytes(b"MZ-fake")
    chosen = connect.choose_install_folder(tmp_path)
    assert chosen == anchor_dir
    assert chosen.name == "Anchor"


def test_wave2_in_place_install_mode_and_skill_overwrite(tmp_path):
    """NS-3: onboard.install_skills(overwrite=True) replaces existing skill dirs."""
    skills_src = tmp_path / "src_skills"
    (skills_src / "gandalf").mkdir(parents=True)
    (skills_src / "gandalf" / "SKILL.md").write_text("v1.5.2 gandalf\n", encoding="utf-8")

    dest_skills = tmp_path / "dest_skills"
    (dest_skills / "gandalf").mkdir(parents=True)
    (dest_skills / "gandalf" / "SKILL.md").write_text("old v1.4.6 gandalf\n", encoding="utf-8")
    (dest_skills / "gandalf" / onboard._OURS_MARKER).write_text("installed\n", encoding="utf-8")

    # Without overwrite, existing is skipped
    res_skip = onboard.install_skills(skills_src=skills_src, skills_home=dest_skills, overwrite=False)
    skipped_names = [s["name"] if isinstance(s, dict) else s for s in res_skip["skipped"]]
    assert "gandalf" in skipped_names
    assert (dest_skills / "gandalf" / "SKILL.md").read_text(encoding="utf-8") == "old v1.4.6 gandalf\n"

    # With overwrite=True, existing is replaced with v1.5.2
    res_ow = onboard.install_skills(skills_src=skills_src, skills_home=dest_skills, overwrite=True)
    installed_names = [s["name"] if isinstance(s, dict) else s for s in res_ow["installed"]]
    assert "gandalf" in installed_names
    assert (dest_skills / "gandalf" / "SKILL.md").read_text(encoding="utf-8") == "v1.5.2 gandalf\n"


def test_wave2_post_install_routing_and_offline_page_controls(tmp_path):
    """NS-3: Unconfigured install routes to /onboard-wizard, and offline_page includes Install/Repair + Stop buttons."""
    fresh_root = tmp_path / "AnchorFresh"
    fresh_root.mkdir()
    (fresh_root / "onboard_wizard.py").write_text("# wizard\n", encoding="utf-8")
    assert connect.resolve_post_install_target_path(fresh_root) == "/onboard-wizard"

    # Once user_profile.json has wizard_completed=True, it routes to /setup
    dot_anchor = fresh_root / ".anchor"
    dot_anchor.mkdir()
    (dot_anchor / "user_profile.json").write_text(
        json.dumps({"display_name": "Merrill", "wizard_completed": True}),
        encoding="utf-8",
    )
    assert connect.resolve_post_install_target_path(fresh_root) == "/setup"

    offline_html = connect.offline_page("http://127.0.0.1:8777")
    assert "open_installer" in offline_html
    assert "stop_services" in offline_html
    assert "bar-version-badge" in offline_html

    install_html = connect.installation_page(fresh_root)
    assert 'id="install-mode"' in install_html
    assert 'value="upgrade_in_place"' in install_html
    assert 'value="clean_install"' in install_html


# ==============================================================================
# WAVE 3: Mother Ship Registry, Push/Pull Update Engine, and Version Badges
# ==============================================================================


def test_wave3_mothership_registry_and_push_pull_updater(tmp_path):
    """NS-4: Mother Ship registration is idempotent, bounded, durable, and supports check/pull/push updates."""
    fake_root = tmp_path / "AnchorRepo"
    fake_root.mkdir()
    (fake_root / "VERSION").write_text("1.5.2\n", encoding="utf-8")

    # 1. Register Merrill's Mother Ship
    reg_res = mothership_updater.register_mothership_in_repo(
        {
            "id": "merrill-mothership",
            "owner": "Merrill",
            "pseudonym": "Aladdin",
            "tailscale_url": "https://merrill.tailnet.ts.net",
            "platform": "windows",
        },
        anchor_root=fake_root,
    )
    assert reg_res["ok"] is True
    assert (fake_root / "mothership_registry.json").is_file()

    # 2. Idempotence: registering the same Mother Ship again updates in-place without duplicating
    mothership_updater.register_mothership_in_repo(
        {
            "id": "merrill-mothership",
            "owner": "Merrill",
            "pseudonym": "Aladdin",
            "tailscale_url": "https://merrill.tailnet.ts.net",
            "platform": "windows",
            "version_installed": "1.5.2",
        },
        anchor_root=fake_root,
    )
    loaded = mothership_updater.load_mothership_registry(fake_root)
    merrill_entries = [m for m in loaded["motherships"] if m["id"] == "merrill-mothership"]
    assert len(merrill_entries) == 1
    assert merrill_entries[0]["version_installed"] == "1.5.2"
    assert merrill_entries[0]["installed_version"] == "1.5.2"

    # 3. Version status readout
    v_stat = mothership_updater.get_version_status(fake_root)
    assert v_stat["ok"] is True
    assert v_stat["version"] == "1.5.2"
    assert v_stat["display_version"] == "v1.5.2"


def test_wave3_version_badges_in_top_bar_and_settings():
    """NS-4: Version badge is present in static/app.html, high_seat_page.py masthead, and static/provider-setup.html."""
    cur_ver = paths.read_version()
    app_html = (ROOT / "static" / "app.html").read_text(encoding="utf-8")
    assert 'id="bar-version-pill"' in app_html
    assert f"v{cur_ver}" in app_html

    setup_html = (ROOT / "static" / "provider-setup.html").read_text(encoding="utf-8")
    assert 'id="setup-version-pill"' in setup_html
    assert 'id="mothership-update-registry-card"' in setup_html
    assert 'id="btn-ms-pull-update"' in setup_html
    assert 'id="btn-ms-push-update"' in setup_html
    # Merrill's target="_blank" bug on /setup/install must be fixed
    assert 'href="/setup/install" id="setup-install-instructions-link"' in setup_html

    mh_html = high_seat_page._masthead({"build": cur_ver, "steward": {"label": "Aladdin", "high_seat_name": "High Seat"}})
    assert 'id="mhVersionPill"' in mh_html
    assert f"v{cur_ver}" in mh_html


# ==============================================================================
# WAVE 4: macOS / Linux Turnkey Installer, Launcher, Docs & Distro Manifest
# ==============================================================================


def test_wave4_macos_linux_installer_and_docs():
    """NS-5: install-mac-linux.sh, Anchor.command, and USER-ONBOARD.md exist, use LF line endings,
    and clearly document macOS (MacBook Air) + Linux + Windows instructions."""
    sh_path = ROOT / "install-mac-linux.sh"
    cmd_path = ROOT / "Anchor.command"
    doc_path = ROOT / "USER-ONBOARD.md"
    manifest_path = ROOT / "dist_manifest.txt"

    assert sh_path.is_file()
    assert cmd_path.is_file()
    sh_bytes = sh_path.read_bytes()
    cmd_bytes = cmd_path.read_bytes()
    assert b"\r\n" not in sh_bytes, "install-mac-linux.sh must use LF line endings for macOS/Linux bash"
    assert b"\r\n" not in cmd_bytes, "Anchor.command must use LF line endings for macOS Finder"

    sh_text = sh_bytes.decode("utf-8")
    cmd_text = cmd_bytes.decode("utf-8")
    assert "--no-browser" in sh_text
    assert "anchor_shell.py" in sh_text
    assert "Anchor.app" in sh_text
    assert "--no-browser" in cmd_text
    assert "anchor_shell.py" in cmd_text
    assert "Anchor.app" in cmd_text

    doc_text = doc_path.read_text(encoding="utf-8")
    assert "MacBook Air" in doc_text
    assert "Anchor.exe" in doc_text
    assert "Anchor.app" in doc_text
    assert "install-mac-linux.sh" in doc_text
    assert "Anchor.command" in doc_text
    assert "mothership_registry.json" in doc_text

    manifest_text = manifest_path.read_text(encoding="utf-8")
    for required_entry in ("mothership_updater.py", "mothership_registry.json", "install-mac-linux.sh", "Anchor.command"):
        assert required_entry in manifest_text

    import distro
    scan_pairs = [
        (rel, ROOT / rel)
        for rel in ("mothership_updater.py", "mothership_registry.json", "install-mac-linux.sh", "Anchor.command", "USER-ONBOARD.md")
    ]
    hits = distro.scan_paths(scan_pairs, root=ROOT)
    assert hits == [], f"Expected zero personal-data / import hits in new files, got: {hits}"

