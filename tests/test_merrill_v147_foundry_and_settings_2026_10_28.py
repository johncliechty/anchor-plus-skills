"""Regression tests for v1.4.7 collaborator Skill Foundry & conversational steward settings/reboot."""
from pathlib import Path
import pytest

import foundry_api as api
import foundry_page as page
from steward_cockpit import steward_engine as se
from steward_cockpit import steward_routes as sr


def test_collaborator_skill_foundry_lists_all_19_skills_with_icons_and_maps(monkeypatch):
    """When C:/dev/Skill Foundry and C:/dev/trio do not exist (collaborator PC),
    /foundry falls back to vendor/bundled-skills and vendor/foundry-page-maps and
    lists all 19 skills with icons, Library resources, Process Maps, Knowledge Maps, and Anvil Maps."""
    bundled = page.CODE_ROOT / "vendor" / "bundled-skills"
    monkeypatch.setattr(api, "FOUNDRY_ROOT", "C:/nonexistent/Skill Foundry")
    monkeypatch.setattr(api, "SKILLS_ROOT", "C:/nonexistent/Skill Foundry/skills")
    monkeypatch.setattr(page, "_is_default_foundry_root", lambda: True)
    monkeypatch.setattr(api, "_is_default_foundry_root", lambda: True)
    monkeypatch.delenv("FOUNDRY_PAGE_CONTENT_ROOT", raising=False)
    monkeypatch.setattr(
        page,
        "discovery_roots",
        lambda: (bundled, bundled, bundled, bundled / "ecgberht"),
    )

    cat = page.catalog()
    skills = cat["skills"]
    assert len(skills) == 19
    for s in skills:
        assert s["icon"], f"Missing icon for {s['id']}"
        assert s["walkthrough"] == "source-anchored draft", f"Unfinished walkthrough for {s['id']}"
        assert s["anvilMapped"] is True, f"Missing anvilMapped for {s['id']}"
        detail = page.skill_detail(s["id"])
        assert detail["resources"], f"No resources for {s['id']}"
        assert not detail["libraryIssues"], f"Library issues for {s['id']}: {detail['libraryIssues']}"
        assert detail["processMap"]["status"] == "source-anchored draft", f"Process map status for {s['id']}: {detail['processMap']}"
        assert not detail["processMap"]["issues"], f"Process map issues for {s['id']}: {detail['processMap']['issues']}"
        assert detail["knowledgeMap"]["status"] == "seeded draft", f"Knowledge map status for {s['id']}: {detail['knowledgeMap']}"
        assert not detail["knowledgeMap"]["issues"], f"Knowledge map issues for {s['id']}: {detail['knowledgeMap']['issues']}"
        anvil = page.anvil_detail(s["id"])
        assert anvil.get("status") == "verified", f"Anvil status for {s['id']}: {anvil.get('status')}"


def test_claude_defaults_to_yolo_and_conversational_settings_reboot_session(tmp_path, monkeypatch):
    """STEWARD_FENCE defaults to False (YOLO bypassPermissions), and conversational
    commands update permissions/fence/model/effort and reboot the underlying session."""
    assert se.STEWARD_FENCE is False

    # Check natural language parser
    cmd1 = se.Engine._parse_runtime_setting_command("Please run in yolo mode and bypass permissions")
    assert cmd1 and cmd1["permission_mode"] == "bypassPermissions" and cmd1["fence"] == "off" and cmd1["reboot"] is True

    cmd2 = se.Engine._parse_runtime_setting_command("Turn on the write fence")
    assert cmd2 and cmd2["fence"] == "on" and cmd2["permission_mode"] == "default" and cmd2["reboot"] is True

    cmd3 = se.Engine._parse_runtime_setting_command("Switch Claude model to opus and set effort to max")
    assert cmd3 and cmd3["model"] == "opus" and cmd3["effort"] == "max" and cmd3["reboot"] is True

    cmd4 = se.Engine._parse_runtime_setting_command("Reboot Claude Code")
    assert cmd4 and cmd4["reboot"] is True

    # Ordinary prose does not trigger runtime settings reboot
    assert se.Engine._parse_runtime_setting_command("Can you draft the syllabus for Week 3?") is None

    # Test Engine.configure_session & POST /api/steward/configure_session
    monkeypatch.setattr(se, "STATE_FILE", tmp_path / "state.json")
    cdir = tmp_path / "effort"
    cdir.mkdir()
    eng = se.Engine(str(cdir), fake=True)
    eng.cli = "claude"
    wakes = []
    stops = []
    monkeypatch.setattr(eng, "alive", lambda: True)
    monkeypatch.setattr(eng, "stop", lambda: stops.append(True))
    monkeypatch.setattr(eng, "wake", lambda fresh=False, seed=None: (wakes.append(fresh) or True, "awake"))

    res = eng.configure_session(
        action="apply",
        permission_mode="default",
        fence="on",
        model="sonnet",
        effort="max",
        reboot=True,
    )
    assert res["ok"] is True
    assert res["rebooted"] is True
    assert eng.permission_mode == "default"
    assert eng.fenced_override is True
    assert eng.effort_override == "max"
    assert eng.model_selection["model"] == "sonnet"
    assert len(stops) == 1 and len(wakes) == 1

    # Switch back to YOLO via say()
    monkeypatch.setattr(eng, "_send_locked", lambda *a, **kw: True)
    say_res = eng.say("Turn off the fence and use yolo mode")
    assert say_res["ok"] is True
    assert eng.permission_mode == "bypassPermissions"
    assert eng.fenced_override is False
    assert len(stops) == 2 and len(wakes) == 2

    # Route handler check
    monkeypatch.setattr(sr, "get_engine", lambda *a, **kw: eng)
    r_out, r_code = sr.handle_post(str(cdir), "configure_session", {"action": "show"})
    assert r_code == 200 and r_out["ok"] is True
    assert r_out["permission_mode"] == "bypassPermissions"
    assert r_out["fenced"] is False
