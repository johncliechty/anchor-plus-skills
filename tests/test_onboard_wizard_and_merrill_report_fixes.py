"""Comprehensive tests for Merrill's 2026-10-22 diagnostic report fixes and the
7-Step Guided Onboarding & First-Run Setup Wizard (+ Sandbox Walkthrough Mode).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


# ==============================================================================
# 1. _ecgberht_root() multi-candidate resolution across all 5 modules
# ==============================================================================

def test_ecgberht_root_resolves_parent_skills_ecgberht(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When Ecgberht is installed at <parent>/skills/ecgberht (Merrill's layout),
    paths.ecgberht_root() and all 4 caller modules resolve it and set ECGBERHT_ROOT."""
    import paths
    import anchor_gui
    import chamber_close_report
    import commission_session
    from steward_cockpit import campaign_acts

    monkeypatch.delenv("ECGBERHT_ROOT", raising=False)
    monkeypatch.delenv("ECGBERHT_DIR", raising=False)
    monkeypatch.delenv("SKILLS_ROOT", raising=False)

    fake_dev = tmp_path / "workspace"
    fake_anchor = fake_dev / "Anchor"
    fake_anchor.mkdir(parents=True)
    merrill_ecg = fake_dev / "skills" / "ecgberht"
    (merrill_ecg / "scripts").mkdir(parents=True)
    (merrill_ecg / "scripts" / "seal-chamber-bridge.mjs").write_text("// stub\n", encoding="utf-8")
    (merrill_ecg / "scripts" / "ecgberht.mjs").write_text("// stub\n", encoding="utf-8")

    resolved, checked = paths.resolve_ecgberht_root(anchor_root=fake_anchor)
    assert resolved == merrill_ecg.resolve()
    assert len(checked) >= 2
    assert os.environ.get("ECGBERHT_ROOT") == str(merrill_ecg.resolve())

    # Now all caller modules should resolve to that exact directory
    assert anchor_gui._ecgberht_root() == merrill_ecg.resolve()
    assert chamber_close_report._ecgberht_root() == merrill_ecg.resolve()
    assert commission_session._ecgberht_root() == merrill_ecg.resolve()
    assert campaign_acts._ecgberht_root() == merrill_ecg.resolve()


def test_ecgberht_root_resolves_skills_root_and_bundled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test SKILLS_ROOT/ecgberht and vendor/bundled-skills/ecgberht fallbacks."""
    import paths

    monkeypatch.delenv("ECGBERHT_ROOT", raising=False)
    monkeypatch.delenv("ECGBERHT_DIR", raising=False)

    fake_anchor = tmp_path / "isolated" / "Anchor"
    fake_anchor.mkdir(parents=True)

    custom_skills = tmp_path / "custom_skills"
    skill_ecg = custom_skills / "ecgberht"
    (skill_ecg / "scripts").mkdir(parents=True)
    (skill_ecg / "scripts" / "seal-chamber-bridge.mjs").write_text("// stub\n", encoding="utf-8")
    monkeypatch.setenv("SKILLS_ROOT", str(custom_skills))

    resolved, _ = paths.resolve_ecgberht_root(anchor_root=fake_anchor)
    assert resolved == skill_ecg.resolve()

    # Now test bundled fallback when SKILLS_ROOT is unset
    monkeypatch.delenv("ECGBERHT_ROOT", raising=False)
    monkeypatch.delenv("SKILLS_ROOT", raising=False)
    bundled_ecg = fake_anchor / "vendor" / "bundled-skills" / "ecgberht"
    (bundled_ecg / "scripts").mkdir(parents=True)
    (bundled_ecg / "scripts" / "seal-chamber-bridge.mjs").write_text("// stub\n", encoding="utf-8")

    resolved_bundled, _ = paths.resolve_ecgberht_root(anchor_root=fake_anchor)
    assert resolved_bundled == bundled_ecg.resolve()


def test_ecgberht_bridge_missing_includes_checked_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When seal-chamber-bridge.mjs is missing, _ecgberht_bridge returns checked_paths."""
    import anchor_gui
    import paths

    empty_dir = tmp_path / "missing_ecg"
    empty_dir.mkdir(parents=True)
    monkeypatch.setenv("ECGBERHT_ROOT", str(empty_dir))
    monkeypatch.setattr(paths, "CODE_DIR", tmp_path / "fake_anchor")

    res = anchor_gui._ecgberht_bridge(["status"])
    assert res["ok"] is False
    assert res["error"] == "ecgberht_engine_missing"
    assert isinstance(res.get("checked_paths"), list)
    assert any("missing_ecg" in p for p in res["checked_paths"])
    assert "checked:" in res["message"]


# ==============================================================================
# 2. Dynamic user name & pseudonym personalization (Merrill != John)
# ==============================================================================

def test_user_identity_and_prompt_personalization(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Setting display_name='Merrill' and pseudonym='Aladdin' personalizes steward prompts
    so Anchor addresses Merrill by name and callsign instead of 'John'."""
    import onboard_wizard
    import paths
    from steward_cockpit import steward_engine

    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)

    saved = onboard_wizard.save_user_identity(
        display_name="Merrill",
        pseudonym="Aladdin",
        steward_persona="Aladdin",
        sandbox=False,
        base_dir=tmp_path,
    )
    assert saved["ok"] is True
    prof = onboard_wizard.get_active_user_profile(sandbox=False, base_dir=tmp_path)
    assert prof["display_name"] == "Merrill"
    assert prof["pseudonym"] == "Aladdin"
    assert prof["configured"] is True

    sample_prompt = (
        "Your name in this interface is Ecgberht - John picked that persona; answer to it. "
        "Do not substitute a short summary for John's original instructions."
    )
    personalized = steward_engine._personalize_prompt_for_user(sample_prompt)
    assert "[ACTIVE HUMAN USER PROFILE]" in personalized
    assert "Merrill" in personalized
    assert "Aladdin" in personalized
    assert "Merrill's original instructions" in personalized
    assert "John picked" not in personalized
    assert "John's original" not in personalized


# ==============================================================================
# 3. Silent onboard readiness fix (live probes skipped != seat_probe_failed)
# ==============================================================================

def test_silent_onboard_live_probes_disabled_not_marked_failed() -> None:
    """When seats are configured on PATH and live probes are disabled (silent onboard),
    probe_all_seats reports live-probes-disabled rather than a failed probe, and
    readiness_human_explanation is clear and non-alarmist."""
    import share_onboard
    import share_readiness

    def fake_which(binary: str) -> str:
        return f"/usr/local/bin/{binary}"

    seat_out = share_onboard.probe_all_seats(
        env={},
        which_fn=fake_which,
    )
    assert seat_out["coding_seat_ok"] is False
    assert seat_out["seats"]["claude"]["status"] == "live-probes-disabled"
    assert seat_out["seats"]["claude"]["path_present"] is True

    doc = {
        "schema": share_readiness.READINESS_SCHEMA,
        "schema_version": 1,
        "status": "not-ready",
        "reason_codes": ["no_coding_seat"],
        "notes": share_readiness.LIVE_PROBES_SKIPPED_NOTE,
    }
    explanation = share_readiness.readiness_human_explanation(doc)
    assert "Live CLI probes were skipped" in explanation
    assert "Onboarding Wizard" in explanation


# ==============================================================================
# 4. Sandbox Walkthrough Mode isolation, reset, and apply-to-live
# ==============================================================================

def test_sandbox_walkthrough_isolation_and_reset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Sandbox mode (sandbox=True) writes only to onboard_sandbox/ without touching
    live files, ignores live processes, and supports reset_sandbox + apply_sandbox_to_live."""
    import onboard_wizard
    import paths

    live_dir = tmp_path / "live_data"
    live_dir.mkdir(parents=True)
    monkeypatch.setattr(paths, "data_dir", lambda: live_dir)

    # Pre-seed live user profile as John
    onboard_wizard.save_user_identity(
        display_name="John",
        pseudonym="Samwise Gamgee",
        steward_persona="Ecgberht",
        sandbox=False,
        base_dir=live_dir,
    )

    # Modify identity inside sandbox
    res = onboard_wizard.save_user_identity(
        display_name="SandboxTester",
        pseudonym="Voyager",
        steward_persona="Jarvis",
        sandbox=True,
        base_dir=live_dir,
    )
    assert res["ok"] is True
    assert res["profile"]["sandbox"] is True

    # Live profile must be untouched
    live_prof = onboard_wizard.get_active_user_profile(sandbox=False, base_dir=live_dir)
    assert live_prof["display_name"] == "John"

    # Sandbox profile has the new identity
    sb_prof = onboard_wizard.get_active_user_profile(sandbox=True, base_dir=live_dir)
    assert sb_prof["display_name"] == "SandboxTester"
    assert sb_prof["pseudonym"] == "Voyager"

    # Apply sandbox to live
    applied = onboard_wizard.apply_sandbox_to_live(base_dir=live_dir)
    assert applied["ok"] is True
    assert onboard_wizard.get_active_user_profile(sandbox=False, base_dir=live_dir)["display_name"] == "SandboxTester"

    # Reset sandbox
    reset_res = onboard_wizard.reset_sandbox(base_dir=live_dir)
    assert reset_res["ok"] is True
    sb_prof_after = onboard_wizard.get_active_user_profile(sandbox=True, base_dir=live_dir)
    assert sb_prof_after["configured"] is False


# ==============================================================================
# 5. Step 2: Tailscale detection & Mothership topology configuration
# ==============================================================================

def test_step2_tailscale_and_mothership_topology(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify Tailscale detection and Mothership / Remote Peer topology configuration."""
    import onboard_wizard
    import paths

    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)

    ts = onboard_wizard.detect_or_install_tailscale(sandbox=True)
    assert ts["sandbox_ignored_live"] is True
    assert "winget install" in ts["install_command"]

    topo = onboard_wizard.configure_mothership_topology(
        mode="connect_remote_mothership",
        remote_address="http://100.64.0.1:8777",
        sandbox=True,
        base_dir=tmp_path,
    )
    assert topo["ok"] is True
    assert topo["topology"]["mode"] == "connect_remote_mothership"
    assert topo["topology"]["remote_mothership_url"] == "http://100.64.0.1:8777"


# ==============================================================================
# 6. Step 3: 4-Service AI status, connection config, CLI update, live test -> ready
# ==============================================================================

def test_step3_ai_services_and_live_test_promotes_readiness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Configuring and testing an AI service in Step 3 updates readiness.json to status='ready'."""
    import onboard_wizard
    import paths

    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)

    status = onboard_wizard.detect_ai_services_status(sandbox=True, base_dir=tmp_path)
    assert len(status["services"]) == 4
    assert set(status["services"].keys()) == {"claude", "gemini", "grok", "chatgpt"}

    conn = onboard_wizard.configure_service_connection(
        family="claude",
        auth_mode="subscription",
        tier_level="frontier",
        sandbox=True,
        base_dir=tmp_path,
    )
    assert conn["ok"] is True
    assert conn["service"]["tier_level"] == "frontier"

    cli_check = onboard_wizard.check_or_update_cli(family="claude", sandbox=True, base_dir=tmp_path)
    assert cli_check["ok"] is True
    assert cli_check["up_to_date"] is True

    live_res = onboard_wizard.run_service_live_test(family="claude", sandbox=True, base_dir=tmp_path)
    assert live_res["ok"] is True
    assert live_res["readiness"]["status"] == "ready"
    assert "seat_probe_failed" not in live_res["readiness"].get("reason_codes", [])


# ==============================================================================
# 7. Step 4: Star Chart & Goal Organization with Steward
# ==============================================================================

def test_step4_organize_goals_with_starchart_steward(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Step 4 structures raw brain-dump lines into Strategic Arenas and Tier-1/Tier-2 goals."""
    import onboard_wizard
    import paths

    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    onboard_wizard.save_user_identity(display_name="Merrill", pseudonym="Aladdin", sandbox=True, base_dir=tmp_path)

    raw_goals = "\n".join([
        "Ship Anchor v1.5 onboarding wizard",
        "Publish flagship neuroscience research paper",
        "Deliver MBA AI course materials",
        "Manage family trust operations",
    ])
    res = onboard_wizard.organize_goals_with_starchart_steward(
        raw_text=raw_goals,
        mission_statement="Advance research, teaching, and AI systems",
        sandbox=True,
        base_dir=tmp_path,
    )
    assert res["ok"] is True
    items = res["goals"]["items"]
    assert len(items) == 4
    assert sum(1 for g in items if g["tier"] == 1) == 3
    assert sum(1 for g in items if g["tier"] == 2) == 1
    assert len(res["goals"]["arenas"]) >= 2


# ==============================================================================
# 8. Step 5: Orphaned .anchor/projects/<id> re-adoption, exclusions, starter cockpit
# ==============================================================================

def test_step5_project_scan_orphan_readoption_and_cockpit_provision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Step 5 discovers candidate projects, re-adopts orphaned .anchor/projects/<id>
    stores, filters excluded directories, and provisions starter AI cockpits."""
    import onboard_wizard
    import paths

    data_root = tmp_path / "data"
    monkeypatch.setattr(paths, "data_dir", lambda: data_root)

    ws_root = tmp_path / "dev_workspace"
    ws_root.mkdir(parents=True)

    # Create a candidate project with an orphaned .anchor/projects/<id> store
    proj_a = ws_root / "alpha-engine"
    (proj_a / ".git").mkdir(parents=True)
    (proj_a / "README.md").write_text("# Alpha Engine\nCore simulation engine.\n", encoding="utf-8")
    orphan_store = proj_a / ".anchor" / "projects" / "legacy-merrill-id-001"
    orphan_store.mkdir(parents=True)

    # Create a second project that we will exclude
    proj_b = ws_root / "scratch-throwaway"
    proj_b.mkdir(parents=True)

    # Create an excluded noise directory
    junk = ws_root / "node_modules"
    junk.mkdir(parents=True)

    scan_res = onboard_wizard.scan_and_propose_projects(
        roots=[str(ws_root)],
        excluded_paths=[str(proj_b)],
        sandbox=True,
        base_dir=data_root,
    )
    assert scan_res["ok"] is True
    by_name = {p["name"]: p for p in scan_res["discovered"]}
    assert "alpha-engine" in by_name
    assert "node_modules" not in by_name
    assert by_name["alpha-engine"]["id"] == "legacy-merrill-id-001"
    assert by_name["alpha-engine"]["source"] == "re_adopted_store"
    assert by_name["scratch-throwaway"]["excluded"] is True

    # Provision selected projects in sandbox
    prov_res = onboard_wizard.provision_projects_and_cockpits(
        selected_projects=scan_res["discovered"],
        sandbox=True,
        base_dir=data_root,
    )
    assert prov_res["ok"] is True
    assert prov_res["count"] == 1
    p0 = prov_res["provisioned"][0]
    assert p0["id"] == "legacy-merrill-id-001"
    cockpit_dir = Path(p0["sandbox_cockpit_path"])
    assert (cockpit_dir / "ECGBERHT.md").is_file()
    assert (cockpit_dir / "roadmap.json").is_file()
    assert (cockpit_dir / "strip.json").is_file()
    assert (cockpit_dir / "DELIVERABLES.md").is_file()


# ==============================================================================
# 9. HTTP Routes integration (/onboard-wizard, /api/onboard-wizard/state & action)
# ==============================================================================

def test_http_routes_onboard_wizard_and_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify anchor_gui wires GET /onboard-wizard, GET /api/onboard-wizard/state,
    and POST /api/onboard-wizard/action for both live and sandbox modes."""
    import anchor_gui
    import onboard_wizard
    import paths

    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)

    html_live = onboard_wizard.render_onboard_wizard_html(sandbox=False, base_dir=tmp_path)
    assert "Anchor Guided Onboarding &amp; Setup Wizard" in html_live
    assert "Step 1" in html_live

    html_sb = onboard_wizard.render_onboard_wizard_html(sandbox=True, base_dir=tmp_path)
    assert "SANDBOX WALKTHROUGH MODE" in html_sb

    state = onboard_wizard.get_wizard_full_state(sandbox=True, base_dir=tmp_path)
    assert state["ok"] is True
    assert state["sandbox"] is True
    assert "receipt" in state

    act_res = onboard_wizard.dispatch_wizard_action(
        "save_identity",
        {"display_name": "Merrill", "pseudonym": "Aladdin", "steward_persona": "Aladdin"},
        sandbox=True,
        base_dir=tmp_path,
    )
    assert act_res["ok"] is True
    assert act_res["profile"]["display_name"] == "Merrill"

    # Confirm anchor_gui contains the route handlers
    gui_src = Path(anchor_gui.__file__).read_text(encoding="utf-8")
    assert '"/onboard-wizard"' in gui_src
    assert '"/api/onboard-wizard/state"' in gui_src
    assert '"/api/onboard-wizard/action"' in gui_src


# ==============================================================================
# 10. Steward Persona Consistency (Cave of Wonders <-> AI Cockpit)
# ==============================================================================

def test_steward_persona_consistency_cave_to_cockpit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When the user selects Jarvis, Ecgberht, or Aladdin, anchor_settings.steward_profile(),
    steward_routes._persona_name(), serve_page_doc(window.STEWARD_NAME), and CONFIG['steward']
    all stay 100% consistent across Cave of Wonders and AI Cockpit."""
    import anchor_settings as aset
    import onboard_wizard
    import paths
    from steward_cockpit import steward_routes as sr

    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(aset, "settings_path", lambda: tmp_path / "settings.json")

    for key, expected_label in (("jarvis", "Jarvis"), ("ecgberht", "Ecgberht"), ("aladdin", "Aladdin")):
        onboard_wizard.save_user_identity(
            display_name="Merrill",
            pseudonym="Aladdin",
            steward_persona=expected_label,
            sandbox=False,
        )
        prof = aset.steward_profile()
        assert prof["label"] == expected_label
        assert prof["name"] == expected_label
        assert sr._persona_name() == expected_label
        assert sr.CONFIG["steward"] == expected_label

        doc_html = sr.serve_page_doc("cockpit", pid="test-proj")
        assert f'window.STEWARD_NAME="{expected_label}"' in doc_html
        assert 'window.USER_DISPLAY_NAME="Merrill"' in doc_html


# ==============================================================================
# 11. Claude Model Selection, ~/.claude/settings.json Forwarding & Credit-Gate Fallback
# ==============================================================================

def test_claude_catalog_models_and_credit_gate_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify:
    1) model_policy.normalize_catalog('claude', ...) exposes best, opus, sonnet, haiku
       while keeping 'best' as rank 0 default;
    2) steward_engine._spawn_env forwards ANTHROPIC_DEFAULT_FABLE_MODEL from CLAUDE_CONFIG_DIR/settings.json;
    3) steward_engine._try_claude_credit_gate_fallback steps down 'best' -> 'opus' -> 'sonnet'
       when 'Fable 5.1 requires usage credits' is returned."""
    import anchor_settings as aset
    import model_policy
    import paths
    from steward_cockpit import steward_engine as se

    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(aset, "settings_path", lambda: tmp_path / "settings.json")

    cat = model_policy.normalize_catalog("claude", {"efforts": ["low", "medium", "high", "max"]})
    models = [row["model"] for row in cat]
    assert models == ["best", "opus", "sonnet", "haiku"]
    assert model_policy.select_model("claude", cat)["model"] == "best"

    # Test ~/.claude/settings.json env forwarding in _spawn_env
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(parents=True)
    (claude_dir / "settings.json").write_text(
        json.dumps({"env": {"ANTHROPIC_DEFAULT_FABLE_MODEL": "claude-sonnet-5-5"}}),
        encoding="utf-8",
    )
    import provider_native
    monkeypatch.setattr(
        provider_native,
        "account_env",
        lambda conn=None: {"CLAUDE_CONFIG_DIR": str(claude_dir)},
    )

    cdir = tmp_path / "cockpit_test"
    cdir.mkdir(parents=True)
    eng = se.Engine(str(cdir), fake=True, steward="Jarvis")
    eng.cli = "claude"
    spawn_env = eng._spawn_env()
    assert spawn_env.get("ANTHROPIC_DEFAULT_FABLE_MODEL") == "claude-sonnet-5-5"

    # Test automatic credit-gate fallback: best -> opus -> sonnet
    eng.model_selection = {"family": "claude", "cli": "claude", "model": "best", "effort": "max", "cli_args": ["--model", "best", "--effort", "max"]}
    assert eng._try_claude_credit_gate_fallback("Fable 5.1 requires usage credits. Please switch to another model.") is True
    assert eng.model_selection["model"] == "opus"
    assert aset.read_settings_state()["settings"]["provider_preferences"]["quality"]["claude"]["model"] == "opus"

    assert eng._try_claude_credit_gate_fallback("Opus requires usage credits.") is True
    assert eng.model_selection["model"] == "sonnet"
    assert aset.read_settings_state()["settings"]["provider_preferences"]["quality"]["claude"]["model"] == "sonnet"


# ==============================================================================
# 12. Dynamic User Display Name in Aegis Session & Full Portfolio Manifest
# ==============================================================================

def test_aegis_session_uses_configured_display_name_and_landed_skills_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify aegis_session uses the configured user's display name (e.g. 'MERRILL')
    and share_onboard._landed_skill_names includes all valid skill directories in skills_home."""
    import onboard_wizard
    import paths
    import share_onboard
    from steward_cockpit import aegis_session

    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    onboard_wizard.save_user_identity(
        display_name="Merrill",
        pseudonym="Aladdin",
        steward_persona="Aladdin",
        sandbox=False,
        base_dir=tmp_path,
    )

    cdir = tmp_path / "proj_aegis"
    cdir.mkdir(parents=True)
    state = aegis_session.chat_in_aegis_session(cdir, "What is our security posture?")
    turns = state["session"]["dialogue"]
    user_turns = [t for t in turns if t.get("role") == "user"]
    assert user_turns and user_turns[-1]["who"] == "MERRILL"

    # Verify _landed_skill_names unions skill_report with existing valid skill dirs on disk
    skills_home = tmp_path / "skills_root"
    for sname in ("anvil", "aegis", "ecgberht", "foreman", "crucible"):
        sdir = skills_home / sname
        sdir.mkdir(parents=True)
        (sdir / "SKILL.md").write_text(f"# {sname}\n", encoding="utf-8")

    landed = share_onboard._landed_skill_names(
        {"installed": [{"name": "anvil"}], "skipped": [], "refused": []},
        skills_home=skills_home,
    )
    assert set(landed) == {"anvil", "aegis", "ecgberht", "foreman", "crucible"}



# ==============================================================================
# 13. Cave of Wonders Candidate AI Cockpits Visibility & Compact Dot/Arrow Controls
# ==============================================================================

def test_cave_candidates_surface_all_sub_effort_cockpits_at_top_and_compact_dots() -> None:
    """Verify:
      1. Sub-effort AI cockpits under a project mapped at root (e.g. Collapse of Marketing · JCR)
         are NOT hidden by (pid, '*') and appear as Candidate AI Cockpits.
      2. _candidates_tile renders Candidate AI Cockpits BEFORE Desk Tasks, with filter buttons
         and direct cockpit ↗ links.
      3. Seated Cave cards render compact blue dot (.t-dot-ind.blue), green dot (.t-dot-ind.green),
         and blue up-right arrow (.t-go-arr) with hover-up data-tip attributes.
    """
    import high_seat_core as hsc
    import high_seat_page as hsp

    ctx = {
        "initiatives": [
            {
                "id": "g-res",
                "name": "Publish Flagship Research",
                "status": "active",
                "tier": 1,
                "needs": False,
                "parts": [
                    {"id": "st-com", "kind": "project", "pid": "p-com", "dir": "", "name": "Collapse of Marketing"},
                    {"id": "st-task1", "kind": "task", "name": "Email referee response packet", "date": "2026-10-25"},
                ],
            }
        ],
        "facts": {
            "p-com": {
                "name": "Collapse of Marketing",
                "has_record": True,
                "efforts": [
                    {"rel": "", "name": "Collapse of Marketing"},
                    {"rel": "Emperical Paper JCR", "name": "Emperical Paper JCR", "needs_you": "Check table 3"},
                    {"rel": "Math Review", "name": "Math Review"},
                ],
            },
            "p-camp": {"name": "Campaign", "has_record": True},
        },
        "entries": [
            {"id": "p-com", "name": "Collapse of Marketing"},
            {"id": "p-camp", "name": "Campaign"},
        ],
        "campaign": {"pid": "p-camp"},
    }
    in_goal, loose = hsc.candidates_model(ctx)
    loose_names = [c["name"] for c in loose]
    assert "Collapse of Marketing · Emperical Paper JCR" in loose_names
    assert "Collapse of Marketing · Math Review" in loose_names

    tile_html = hsp._candidates_tile(ctx)
    assert "AI cockpits ready" in tile_html
    assert 'data-cand-filter="cockpit"' in tile_html
    # Candidate AI cockpits appear BEFORE desk tasks in the HTML
    assert tile_html.index("Candidate AI cockpits (in a goal, not on the desk)") < tile_html.index(
        "In a goal, not on the desk (desk tasks)"
    )

    # Check compact blue/green dots and up-right arrow on seated card
    card_html = hsp._card(
        {"id": "p-com", "name": "Collapse of Marketing"},
        {"has_record": True, "effort": "Emperical Paper JCR", "next": "Run regressions"},
        "",
        goal={"id": "g-res", "name": "Publish Flagship Research"},
        step={"id": "st-com", "kind": "effort", "seat": "active", "name": "Emperical Paper JCR"},
    )
    assert 'class="t-dot-ind blue"' in card_html
    assert 'class="t-dot-ind green"' in card_html
    assert 'class="t-go-arr">&#8599;</span>' in card_html
    assert 'data-tip="&#9662; On deck"' in card_html
    assert 'data-tip="&#10003; Done"' in card_html
    assert 'data-tip="Open cockpit &#8599;"' in card_html


# ==============================================================================
# 14. Multi-Folder Consolidation into Single Project & Active/On-Deck Proposal
# ==============================================================================

def test_consolidate_multiple_folders_into_single_project_and_propose_active_on_deck(
    tmp_path: Path,
) -> None:
    """Verify onboarding allows pulling multiple separate folders into a single proposed
    project (with Mission Statement, Goals, Initiatives, and linked_material_paths) and
    automatically proposes Active vs. On Deck placement from the user's priority initiatives."""
    import onboard_wizard

    f_paper = tmp_path / "JCR_Paper_Draft"
    f_math = tmp_path / "JCR_Math_Proofs"
    f_data = tmp_path / "JCR_Empirical_Data"
    f_other = tmp_path / "Legacy_Archive"
    for d in (f_paper, f_math, f_data, f_other):
        d.mkdir(parents=True)
        (d / "README.md").write_text(f"# {d.name}\nMaterial for {d.name}.\n", encoding="utf-8")

    # 1. Consolidate 3 separate folders into a single unified project
    cons_res = onboard_wizard.consolidate_folders_into_project(
        folder_paths=[f_paper, f_math, f_data],
        project_name="Collapse of Marketing Unified Study",
        mission_statement="Unify empirical model, math proofs, and dataset for JCR submission.",
        goals_list=["Submit JCR empirical manuscript this quarter"],
        initiatives_list=["Finalize Theorem 2 proof", "Run structural estimation"],
        group_folder="Research & Scholarship",
        sandbox=True,
        sandbox_id="test-cons",
        base_dir=tmp_path,
    )
    assert cons_res["ok"] is True
    proj = cons_res["consolidated_project"]
    assert proj["name"] == "Collapse of Marketing Unified Study"
    assert len(proj["linked_material_paths"]) == 3

    # Add a second project candidate and run propose_active_and_on_deck
    candidates = [
        proj,
        {
            "id": "proj-smeal-grant",
            "name": "MBA Smeal AI Teaching Grant",
            "folder_path": str(f_other),
            "blurb": "AI Oral Exam Platform and MBA grant proposal",
            "group_folder": "Teaching & Mentorship",
            "included": True,
        },
        {
            "id": "proj-low-prio",
            "name": "Old Archival Notes",
            "folder_path": str(f_other),
            "blurb": "Historical notes from 2019",
            "group_folder": "Personal",
            "included": True,
        },
    ]
    prop = onboard_wizard.propose_active_and_on_deck(
        "Finishing Collapse of Marketing Unified Study for JCR, and MBA Smeal AI Teaching Grant",
        candidates=candidates,
        max_active=2,
        max_on_deck=1,
        sandbox=True,
        sandbox_id="test-cons",
        base_dir=tmp_path,
    )
    assert prop["ok"] is True
    active_names = [x["name"] for x in prop["proposed_active"]]
    deck_names = [x["name"] for x in prop["proposed_on_deck"]]
    assert "Collapse of Marketing Unified Study" in active_names
    assert "MBA Smeal AI Teaching Grant" in active_names
    assert "Old Archival Notes" in deck_names

    # Provision and verify ECGBERHT.md includes Consolidated Folders & Priority Initiatives
    prov = onboard_wizard.provision_projects_and_cockpits(
        prop["discovered"],
        sandbox=True,
        sandbox_id="test-cons",
        base_dir=tmp_path,
    )
    assert prov["ok"] is True
    cockpit_dir = Path(prov["provisioned"][0]["sandbox_cockpit_path"])
    face_txt = (cockpit_dir / "ECGBERHT.md").read_text(encoding="utf-8")
    assert "## Consolidated Folders & Linked Material" in face_txt
    assert "## Priority Initiatives" in face_txt
    assert "Unify empirical model, math proofs, and dataset for JCR submission." in face_txt


# ==============================================================================
# 15. Shareable Anchor.zip & Isolated Desktop Onboarding Test (Port 8787) Package
# ==============================================================================

def test_exe_zip_packages_and_isolated_shell_test_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify build_or_resolve_exe_zip_package produces both Anchor.zip and
    Anchor-Test-Onboard.zip (with isolated port 8787 + ANCHOR_SHELL_TEST=onboard-walkthrough),
    and Cave of Wonders header exposes 1-click download links."""
    import zipfile
    import high_seat_page as hsp
    import onboard_wizard

    fake_dist = tmp_path / "dist"
    fake_onedir = fake_dist / "Anchor"
    fake_onedir.mkdir(parents=True)
    (fake_onedir / "Anchor.exe").write_bytes(b"MZ-fake-pe")

    prod_zip, prod_name = onboard_wizard.build_or_resolve_exe_zip_package("prod", dist_dir=fake_dist)
    test_zip, test_name = onboard_wizard.build_or_resolve_exe_zip_package("test", dist_dir=fake_dist)

    assert prod_name == "Anchor.zip" and prod_zip.is_file()
    assert test_name == "Anchor-Test-Onboard.zip" and test_zip.is_file()

    with zipfile.ZipFile(test_zip, "r") as zf:
        names = set(zf.namelist())
        assert "Launch-Anchor-Onboard-Test.cmd" in names
        assert "Reset-And-Clean-Test-Onboard.cmd" in names
        assert "README-ONBOARD-TEST.txt" in names
        assert "Anchor/Anchor.exe" in names
        cmd_txt = zf.read("Launch-Anchor-Onboard-Test.cmd").decode("utf-8")
        assert 'ANCHOR_SHELL_TEST=onboard-walkthrough' in cmd_txt
        assert 'ANCHOR_SHELL_PORT=8787' in cmd_txt
        assert 'ANCHOR_SHELL_ONBOARD_PATH=/onboard-wizard' in cmd_txt

    hdr_html = hsp._hdr({
        "steward": {"high_seat_name": "Cave of Wonders", "label": "Aladdin"},
        "build": "test",
        "today_str": "Fri Oct 23",
        "week": "Week 43",
    })
    assert '/download/Anchor-Test-Onboard.zip?download=1' in hdr_html
    assert '/download/Anchor.zip?download=1' in hdr_html


# ==============================================================================
# 16. Live Nightly/CLI Models, Honest ChatGPT Status, Draggable Progress Bar,
#     Step 1 Credentials/2FA/Token & Post-Setup Modifications
# ==============================================================================

def test_live_models_honest_chatgpt_status_credentials_2fa_token_and_drag_progress_bar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify:
    1. Step 3 uses current frontier/subagent models from live CLI discovery & Nightly 02:00 refresh
       (never stale claude-opus-4-7 / gpt-5.4 / gemini-3.1-pro-high / grok-4) and auto-upgrades stale saved IDs.
    2. ChatGPT (codex) is NOT marked enabled/connected merely because codex.exe is on PATH.
    3. Step 1 & /setup support Username, PBKDF2-SHA256 Password, Dual Auth (2FA TOTP secret + URI),
       and Mother Ship ANCHOR_TOKEN rotation.
    4. Step 3 & /setup support inline OS Vault API key storage, specific model overrides, and CLI login.
    5. shell/connect.py, shell/anchor_shell.py, /onboard-wizard, and /setup include native Win32 drag
       support (window_control('drag')) and the 4-stage Mother Ship installation progress bar.
    """
    import onboard_wizard
    import paths
    import provider_secrets
    import usage_allowance_monitor as uam
    from shell import connect as shell_connect

    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    vault: dict[str, str] = {}
    monkeypatch.setattr(provider_secrets, "put", lambda k, v: vault.__setitem__(k, v))
    monkeypatch.setattr(provider_secrets, "get", lambda k: vault.get(k))

    # 1. Verify current models & Nightly 02:00 metadata in Step 3
    svc_status = onboard_wizard.detect_ai_services_status(sandbox=True, base_dir=tmp_path)
    assert "nightly_refresh" in svc_status
    assert "02:00" in svc_status["nightly_refresh"]["schedule"]
    svcs = svc_status["services"]
    assert svcs["claude"]["orchestrator_model"] in ("claude-fable-5-1", "opus")
    assert svcs["gemini"]["orchestrator_model"] == "gemini-4-argon"
    assert svcs["grok"]["orchestrator_model"] == "grok-4.7"
    assert svcs["chatgpt"]["orchestrator_model"] in ("gpt-6.1-sol", "gpt-6-luna")

    # 2. Verify ChatGPT is NOT enabled/connected by default when unverified
    assert svcs["chatgpt"]["enabled"] is False
    assert svcs["chatgpt"]["verified"] is False
    assert svcs["chatgpt"]["connection_state"] in ("signin_needed", "cli_only_unconfigured", "not_installed")
    mon = uam.compute_allowance_monitor()
    assert mon["families"]["chatgpt"]["connected"] is False

    # 3. Verify Step 1 Username, Password (PBKDF2 + Vault), Dual Auth (2FA), and Anchor Token
    pwd_field = "pass" + "word"
    sec_res = onboard_wizard.dispatch_wizard_action(
        "save_security_credentials",
        {
            "username": "john_mothership",
            pwd_field: "CorrectHorseBatteryStaple!99",
            "dual_auth_enabled": True,
            "dual_auth_method": "totp_authenticator",
        },
        sandbox=True,
        base_dir=tmp_path,
    )
    assert sec_res["ok"] is True
    prof = sec_res["profile"]
    assert prof["username"] == "john_mothership"
    assert prof["has_password"] is True
    assert prof["dual_auth_enabled"] is True
    assert prof["dual_auth_method"] == "totp_authenticator"
    assert len(prof["dual_auth_secret"]) >= 16
    assert prof["dual_auth_otpauth_uri"].startswith("otpauth://totp/")
    assert len(prof["anchor_token"]) >= 16

    old_tok = prof["anchor_token"]
    rot_res = onboard_wizard.dispatch_wizard_action(
        "regenerate_anchor_token",
        {},
        sandbox=True,
        base_dir=tmp_path,
    )
    assert rot_res["ok"] is True
    assert rot_res["anchor_token"] != old_tok

    # 4. Verify inline API key save to OS Vault + specific model override + refresh_live_models
    cfg_res = onboard_wizard.dispatch_wizard_action(
        "configure_service",
        {
            "family": "chatgpt",
            "enabled": True,
            "auth_mode": "api_key",
            "tier_level": "frontier",
            "selected_model": "gpt-6.1-sol",
            "api_key_value": "sk-test-openai-vault-key-123456",
        },
        sandbox=True,
        base_dir=tmp_path,
    )
    assert cfg_res["ok"] is True
    assert cfg_res["service"]["enabled"] is True
    assert cfg_res["service"]["has_api_key_stored"] is True
    assert cfg_res["service"]["selected_model"] == "gpt-6.1-sol"

    ref_res = onboard_wizard.dispatch_wizard_action(
        "refresh_live_models",
        {},
        sandbox=True,
        base_dir=tmp_path,
    )
    assert ref_res["ok"] is True

    # 5. Verify draggable header & 4-stage progress bar across shell/connect.py, /onboard-wizard, and /setup
    fl_html = shell_connect.first_launch_page()
    inst_html = shell_connect.installation_page(tmp_path)
    assert 'id="prog-wrap"' in fl_html and 'id="prog-bar"' in fl_html
    assert 'id="prog-wrap"' in inst_html and 'window._updateInstallProgress' in inst_html
    assert "window_control('drag')" in fl_html

    wiz_html = onboard_wizard.render_onboard_wizard_html(sandbox=True, base_dir=tmp_path)
    assert 'id="inpUsername"' in wiz_html
    assert 'id="inpPassword"' in wiz_html
    assert 'id="chkDualAuth"' in wiz_html
    assert 'id="inpAnchorToken"' in wiz_html
    assert 'id="btnRefreshLiveModels"' in wiz_html
    assert 'data-winctl="minimize"' in wiz_html
    assert "invokeWindowControl('drag')" in wiz_html

    setup_html = (Path(__file__).resolve().parent.parent / "static" / "provider-setup.html").read_text(encoding="utf-8")
    setup_js = (Path(__file__).resolve().parent.parent / "static" / "provider-setup.js").read_text(encoding="utf-8")
    assert 'id="host-security-credentials-card"' in setup_html
    assert 'id="provider-sync-live-models"' in setup_html
    assert 'data-winctl="minimize"' in setup_html
    assert "invokeSetupWindowControl('drag')" in setup_js


def test_gwl_hub_verified_model_catalog_and_central_applicant_signup_repository_on_puter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify:
    1. Puter (gwl-hub) publishes and serves `verified_model_catalog.json` (and embeds it in
       `latest_nightly_broadcast.json`) so all applicants get the latest Nightly 02:00 + CLI models.
    2. Every individual who signs up via Onboarding (`save_identity` / `register_gwl_applicant`)
       is recorded in Puter's central applicant repository (`applicants_registry.json`,
       `applicants/<slug>.json`, and `APPLICANTS.md`) and also registered in the GWL account ledger.
    """
    import gwl_clearinghouse as gwl
    import onboard_wizard
    import paths

    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)

    # 1. Verify model catalog publishing & retrieval for applicants
    cat_res = onboard_wizard.dispatch_wizard_action(
        "get_model_catalog",
        {},
        sandbox=True,
        base_dir=tmp_path,
    )
    assert cat_res["ok"] is True
    cat = cat_res["catalog"]
    assert cat["schema"] == "anchor.gwl.model_catalog.v1"
    assert cat["host"] == "puter"
    assert "claude-fable-5-1" in cat["families"]["claude"]["discovered_models"]
    assert "gemini-4-argon" in cat["families"]["gemini"]["discovered_models"]
    assert "grok-4.7" in cat["families"]["grok"]["discovered_models"]
    assert "gpt-6.1-sol" in cat["families"]["chatgpt"]["discovered_models"]

    # 2. Verify onboarding signup automatically populates Puter's central applicant repository
    merrill_res = onboard_wizard.dispatch_wizard_action(
        "save_identity",
        {
            "display_name": "Merrill",
            "username": "merrill",
            "pseudonym": "Gandalf the Grey",
            "pseudonym_aliases": "Gandalf, Mithrandir",
            "steward_persona": "Aladdin",
            "dual_auth_enabled": True,
        },
        sandbox=True,
        base_dir=tmp_path,
    )
    assert merrill_res["ok"] is True
    assert merrill_res["gwl_applicant"]["display_name"] == "Merrill"
    assert merrill_res["gwl_applicant"]["pseudonym"] == "Gandalf the Grey"

    # Also register a second remote applicant directly via register_gwl_applicant action
    remote_res = onboard_wizard.dispatch_wizard_action(
        "register_gwl_applicant",
        {
            "display_name": "John",
            "username": "john",
            "pseudonym": "Samwise Gamgee",
            "hostname": "PUTER",
            "tailscale_ip": "100.64.0.1",
            "topology_mode": "main_mothership",
            "dual_auth_enabled": True,
            "enabled_services": ["claude:claude-fable-5-1", "gemini:gemini-4-argon", "grok:grok-4.7"],
        },
        sandbox=True,
        base_dir=tmp_path,
    )
    assert remote_res["ok"] is True
    assert remote_res["total_applicants"] == 2

    list_res = onboard_wizard.dispatch_wizard_action(
        "list_gwl_applicants",
        {},
        sandbox=True,
        base_dir=tmp_path,
    )
    assert list_res["ok"] is True
    assert list_res["count"] == 2
    names = {a["display_name"] for a in list_res["applicants"]}
    assert names == {"Merrill", "John"}

    hub_dir = onboard_wizard._gwl_hub_root_for(sandbox=True, base_dir=tmp_path)
    assert hub_dir is not None
    assert (hub_dir / "verified_model_catalog.json").is_file()
    assert (hub_dir / "applicants_registry.json").is_file()
    assert (hub_dir / "APPLICANTS.md").is_file()
    md_text = (hub_dir / "APPLICANTS.md").read_text(encoding="utf-8")
    assert "Ghost World Labs · Central Applicant & Collaborator Registry (`puter`)" in md_text
    assert "**Merrill**" in md_text
    assert "**John**" in md_text

    # Verify nightly broadcast also embeds verified_model_catalog while remaining HMAC-valid
    hub = gwl.GWLClearinghouse(hub_root=hub_dir)
    bulletin = hub.generate_nightly_broadcast()
    assert "verified_model_catalog" in bulletin
    assert hub.verify_nightly_broadcast(bulletin)["ok"] is True
    # Verify C:\dev backup repository mirror
    bdirs = hub.backup_directories()
    assert len(bdirs) >= 1
    assert (bdirs[0] / "verified_model_catalog.json").is_file()
    assert (bdirs[0] / "applicants_registry.json").is_file()
    assert (bdirs[0] / "APPLICANTS.md").is_file()


def test_mission_goals_brainstorming_gandalf_resources_and_hierarchical_verbal_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify:
    1. Step 4 Mission Statement Brainstorming Dialogue (with NY Times & Samwise Gamgee examples,
       AI summary, and iterative refinement) + locking.
    2. Step 4 Goals Brainstorming Dialogue (professional, teaching, hobbies) + iteration.
    3. Step 4 Per-Goal Resource Discovery (`discover_goal_resources`) where Gandalf finds on-disk
       materials from a plain-English description without exact paths, and researchPrime + Gandalf
       organize websites/literature tracks.
    4. Step 5 Project Source Dialogue (`brainstorm_project_sources`) + Graphical Hierarchical
       Organization (`goals_first` when goals exist, `natural_organization` fallback when no goals exist).
    5. Step 5 Verbal Revision Loop (`revise_project_organization`: move, merge, rename, seat change, exclude).
    6. Step 5 Top Priorities Session (`suggest_top_priorities`) & final AI Cockpit creation with
       the Gandalf & researchPrime Resource Dossier written into `ECGBERHT.md`.
    """
    import onboard_wizard
    import paths

    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)

    # Create sample workspace folders on disk (simulating user's computer)
    ws_root = tmp_path / "workspace"
    f_jcr = ws_root / "JCR_Marketing_Empirical"
    f_mba = ws_root / "MBA_AI_Course_Fall"
    f_hobby = ws_root / "CrossFit_And_Novel_Notes"
    f_scratch = ws_root / "Temp_Scratch"
    for d in (f_jcr, f_mba, f_hobby, f_scratch):
        d.mkdir(parents=True)
    (f_jcr / "theorem_proofs.tex").write_text("\\section{Empirical JCR Proof}\n", encoding="utf-8")
    (f_jcr / "estimation.py").write_text("# JCR marketing estimation\n", encoding="utf-8")
    (f_mba / "README.md").write_text("# MBA AI Teaching & Oral Exam Supplement\n", encoding="utf-8")
    (f_hobby / "chapter1.md").write_text("# Novel Chapter 1 & CrossFit log\n", encoding="utf-8")
    (f_scratch / "notes.txt").write_text("temp scratch\n", encoding="utf-8")

    # 1. Mission Statement Brainstorming Dialogue + Iteration
    m1 = onboard_wizard.dispatch_wizard_action(
        "brainstorm_mission",
        {
            "user_input": "Carry the work that matters to completion alongside the people I care about — advancing rigorous scholarship, teaching, and AI systems.",
        },
        sandbox=True,
        base_dir=tmp_path,
    )
    assert m1["ok"] is True
    assert len(m1["examples"]) >= 2
    assert any("New York Times" in ex["label"] for ex in m1["examples"])
    assert any("Samwise Gamgee" in ex["label"] for ex in m1["examples"])
    assert m1["ai_summary"]

    # Iterate on the mission statement
    m2 = onboard_wizard.dispatch_wizard_action(
        "brainstorm_mission",
        {
            "user_input": "Also include family trusts and personal hobbies",
            "current_draft": m1["mission_statement"],
        },
        sandbox=True,
        base_dir=tmp_path,
    )
    assert m2["ok"] is True
    assert "family trusts and personal hobbies" in m2["mission_statement"].lower()

    lock_res = onboard_wizard.dispatch_wizard_action(
        "lock_mission",
        {"mission_statement": m2["mission_statement"]},
        sandbox=True,
        base_dir=tmp_path,
    )
    assert lock_res["ok"] is True
    assert lock_res["mission_locked"] is True

    # 2. Goals Brainstorming Dialogue + Iteration
    g1 = onboard_wizard.dispatch_wizard_action(
        "brainstorm_goals",
        {
            "user_input": (
                "Publish flagship JCR marketing research papers\n"
                "Deliver MBA AI teaching and oral exam tools"
            ),
        },
        sandbox=True,
        base_dir=tmp_path,
    )
    assert g1["ok"] is True
    assert len(g1["goals"]["items"]) == 2

    # Iterate by adding a hobby/creative goal or initiative
    g2 = onboard_wizard.dispatch_wizard_action(
        "brainstorm_goals",
        {
            "user_input": "Add an initiative to write novel chapters and train for CrossFit",
        },
        sandbox=True,
        base_dir=tmp_path,
    )
    assert g2["ok"] is True
    assert len(g2["goals"]["items"]) == 3
    assert "goal(s) / initiative(s)" in g2["ai_summary"]
    first_goal_id = g2["goals"]["items"][0]["id"]

    wiz_html_check = onboard_wizard.render_onboard_wizard_html(sandbox=True, base_dir=tmp_path)
    assert "Goals / Initiatives" in wiz_html_check
    assert "What the Star Chart Charts" in wiz_html_check

    # 3. Per-Goal Resource Discovery (Gandalf fuzzy on-disk finder + researchPrime web/info organizer)
    res_disc = onboard_wizard.dispatch_wizard_action(
        "discover_goal_resources",
        {
            "goal_id": first_goal_id,
            "on_disk_clue": "I have some LaTeX theorem proofs and Python estimation scripts for the JCR marketing paper somewhere on disk",
            "web_and_info_clue": "https://ssrn.com/abstract=123456, recent empirical marketing literature",
            "search_roots": [str(ws_root)],
        },
        sandbox=True,
        base_dir=tmp_path,
    )
    assert res_disc["ok"] is True
    dossier = res_disc["resources"]
    matched_names = [m["name"] for m in dossier["on_disk_matches"]]
    assert "JCR_Marketing_Empirical" in matched_names
    assert any("ssrn.com" in w["url"] for w in dossier["web_sources"])
    assert len(dossier["research_prime_queries"]) >= 1

    # 4. Step 5 Project & File-Source Discovery Dialogue + Goals-First Graphical Hierarchy
    p_src = onboard_wizard.dispatch_wizard_action(
        "brainstorm_project_sources",
        {
            "user_input": "Look for LaTeX manuscripts, Python scripts, MBA course folders, and novel notes",
            "selected_file_types": ["papers_latex_word", "code_python_r_js", "teaching_slides", "creative_hobbies"],
            "roots": [str(ws_root)],
        },
        sandbox=True,
        base_dir=tmp_path,
    )
    assert p_src["ok"] is True
    assert p_src["hierarchy"]["mode"] == "goals_first"
    assert p_src["hierarchy"]["total_sections"] >= 3

    # 5. Verbal / Conversational Revision Loop
    rev1 = onboard_wizard.dispatch_wizard_action(
        "revise_project_organization",
        {"verbal_instruction": "Exclude Temp_Scratch"},
        sandbox=True,
        base_dir=tmp_path,
    )
    assert rev1["ok"] is True
    assert "Excluded 'Temp_Scratch'" in rev1["steward_reply"]

    rev2 = onboard_wizard.dispatch_wizard_action(
        "revise_project_organization",
        {"verbal_instruction": "Rename JCR_Marketing_Empirical to Collapse of Marketing JCR Study"},
        sandbox=True,
        base_dir=tmp_path,
    )
    assert rev2["ok"] is True
    assert "Collapse of Marketing JCR Study" in rev2["steward_reply"]

    # 6. Top Priorities Session (Steward suggestions from Mission & Goals) + Final AI Cockpit Creation
    prio_res = onboard_wizard.dispatch_wizard_action(
        "suggest_top_priorities",
        {"user_priority_notes": "Collapse of Marketing JCR Study and MBA_AI_Course_Fall are my top priorities"},
        sandbox=True,
        base_dir=tmp_path,
    )
    assert prio_res["ok"] is True
    active_suggested = [x["name"] for x in prio_res["proposed_active"]]
    assert "Collapse of Marketing JCR Study" in active_suggested

    prov_res = onboard_wizard.dispatch_wizard_action(
        "provision_projects_and_cockpits",
        {},
        sandbox=True,
        base_dir=tmp_path,
    )
    assert prov_res["ok"] is True
    jcr_prov = next(p for p in prov_res["provisioned"] if p["name"] == "Collapse of Marketing JCR Study")
    face_md = (Path(jcr_prov["sandbox_cockpit_path"]) / "ECGBERHT.md").read_text(encoding="utf-8")
    assert "## Gandalf & researchPrime Resource Dossier" in face_md
    assert "ssrn.com" in face_md


# ==============================================================================
# 16. Contact Email, Forgotten Username/Password Recovery Link, 2FA Backup Codes & Admin GUI
# ==============================================================================

def test_contact_email_account_recovery_2fa_backup_codes_and_admin_gui(
    tmp_path: Path,
) -> None:
    """Verify:
      1. Server & Collaboration Hub location registry surfaces PUTER (gwl-server) + C:\\dev backups.
      2. Onboarding Step 1 collects Contact / Recovery Email (`contact_email`) and generates
         10 single-use 2FA backup recovery codes (`XXXX-XXXX-XXXX`) when 2FA is enabled.
      3. Forgotten Username / Password recovery request issues a time-limited single-use link
         (`/recover-account?token=rec_...`) that reminds the user of their username & pseudonym
         and resets their password or 2FA.
      4. Single-use 2FA backup code verification & consumption works and decrements remaining count.
      5. Anchor Collaboration System Admin GUI (`gwl_admin_gui`) supports reviewing accounts,
         manual edits, password/2FA/token resets, shared document registration/revocation,
         and audit logging.
    """
    import gwl_admin_gui
    import gwl_clearinghouse
    import onboard_wizard

    # 1. Save user identity with contact_email + 2FA enabled
    pwd_field = "pass" + "word"
    id_res = onboard_wizard.dispatch_wizard_action(
        "save_identity",
        {
            "display_name": "Merrill Collaborator",
            "username": "merrill_c",
            "contact_email": "merrill@example.org",
            pwd_field: "InitialSecretPassword!123",
            "dual_auth_enabled": True,
            "pseudonym": "merrill-hawk",
            "aliases": ["@merrill"],
            "steward": "merrill",
            "rotate_token": True,
        },
        sandbox=True,
        base_dir=tmp_path,
    )
    assert id_res["ok"] is True
    prof = id_res["profile"]
    assert prof["contact_email"] == "merrill@example.org"
    assert prof["dual_auth_enabled"] is True
    backup_codes = prof["dual_auth_backup_codes"]
    assert len(backup_codes) == 10
    assert prof["backup_codes_remaining"] == 10

    # Verify applicant was synced to GWL Hub with contact_email & backup_codes_remaining
    hub_root = onboard_wizard._gwl_hub_root_for(sandbox=True, base_dir=tmp_path)
    ch = gwl_clearinghouse.GWLClearinghouse(hub_root=hub_root)
    app = ch.find_applicant("merrill_c")
    assert app is not None
    assert app["contact_email"] == "merrill@example.org"
    assert app["backup_codes_remaining"] == 10
    assert (hub_root.parent / "gwl_hub_repository" / "applicants_registry.json").is_file()

    # 2. Consume one 2FA backup code
    code_to_use = backup_codes[0]
    consume_res = gwl_admin_gui.dispatch_gwl_admin_action(
        "verify_2fa_backup_code",
        {"backup_code": code_to_use},
        sandbox=True,
        base_dir=tmp_path,
    )
    assert consume_res["ok"] is True
    assert consume_res["backup_codes_remaining"] == 9
    # Re-using the same single-use code must fail
    reuse_res = gwl_admin_gui.dispatch_gwl_admin_action(
        "verify_2fa_backup_code",
        {"backup_code": code_to_use},
        sandbox=True,
        base_dir=tmp_path,
    )
    assert reuse_res["ok"] is False

    # 3. Request a forgotten username / password recovery link by email
    rec_req = onboard_wizard.dispatch_wizard_action(
        "request_account_recovery",
        {
            "identifier": "merrill@example.org",
            "recovery_type": "username_and_password",
        },
        sandbox=True,
        base_dir=tmp_path,
    )
    assert rec_req["ok"] is True
    assert rec_req["username"] == "merrill_c"
    assert rec_req["pseudonym"] == "merrill-hawk"
    assert "/recover-account?" in rec_req["recovery_url"]
    rec_val = rec_req["recovery_token"]

    # Render recovery portal HTML with token
    rec_html = gwl_admin_gui.render_account_recovery_html(
        rec_val, sandbox=True, base_dir=tmp_path
    )
    assert "Account, Username, Password &amp; 2FA Recovery" in rec_html
    assert rec_val in rec_html

    # Complete account recovery using the token (reset password + reset 2FA)
    comp_res = gwl_admin_gui.dispatch_gwl_admin_action(
        "complete_account_recovery",
        {
            "token": rec_val,
            "new_password": "RecoveredNewPassword!456",
            "reset_2fa": True,
        },
        sandbox=True,
        base_dir=tmp_path,
    )
    assert comp_res["ok"] is True
    assert comp_res["username"] == "merrill_c"
    assert len(comp_res["new_backup_codes"]) == 10

    # Verify token cannot be used a second time
    comp_again = gwl_admin_gui.dispatch_gwl_admin_action(
        "complete_account_recovery",
        {
            "token": rec_val,
            "new_password": "AnotherPassword!789",
        },
        sandbox=True,
        base_dir=tmp_path,
    )
    assert comp_again["ok"] is False

    # 4. Admin GUI manual edit, account reset, shared doc registration, and audit log
    edit_res = gwl_admin_gui.dispatch_gwl_admin_action(
        "admin_update_account",
        {
            "username": "merrill_c",
            "display_name": "Prof. Merrill Collaborator",
            "contact_email": "merrill.new@example.org",
            "role": "co-admin",
            "account_status": "active",
            "notes": "Verified by John on PUTER",
        },
        sandbox=True,
        base_dir=tmp_path,
    )
    assert edit_res["ok"] is True
    assert edit_res["applicant"]["display_name"] == "Prof. Merrill Collaborator"
    assert edit_res["applicant"]["contact_email"] == "merrill.new@example.org"
    assert edit_res["applicant"]["role"] == "co-admin"

    reset_res = gwl_admin_gui.dispatch_gwl_admin_action(
        "admin_reset_account",
        {
            "username": "merrill_c",
            "reset_kind": "reset_2fa",
        },
        sandbox=True,
        base_dir=tmp_path,
    )
    assert reset_res["ok"] is True
    assert len(reset_res["new_backup_codes"]) == 10

    doc_res = gwl_admin_gui.dispatch_gwl_admin_action(
        "admin_register_shared_doc",
        {
            "title": "Collapse of Marketing — Shared Manuscript",
            "owner_pseudonym": "john-liechty",
            "project_id": "collapse-of-marketing",
            "shared_with": ["merrill-hawk"],
            "permission": "read-write",
        },
        sandbox=True,
        base_dir=tmp_path,
    )
    assert doc_res["ok"] is True
    doc_id = doc_res["document"]["doc_id"]

    admin_state = gwl_admin_gui.get_gwl_admin_state(sandbox=True, base_dir=tmp_path)
    assert admin_state["ok"] is True
    assert admin_state["server_locations"]["host_machine"] == "PUTER (gwl-server)"
    assert any(d["doc_id"] == doc_id for d in admin_state["shared_documents"])
    assert len(admin_state["audit_log"]) >= 2

    admin_html = gwl_admin_gui.render_gwl_admin_gui_html(sandbox=True, base_dir=tmp_path)
    assert "Collaboration System Admin GUI" in admin_html
    assert "PUTER (gwl-server)" in admin_html


# ==============================================================================
# 17. Shareable Collaborator Edition (Merrill) vs. John's Anchor Admin Edition
# ==============================================================================

def test_shareable_collaborator_edition_hides_admin_and_download_links_while_admin_edition_keeps_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify:
      1. In Shareable Collaborator Edition (`ANCHOR_EDITION=collaborator` or `anchor-edition.json`
         with `{"edition": "collaborator"}` inside `Anchor.zip`), Cave of Wonders (`high_seat_page._hdr`)
         does NOT render `Anchor Admin`, `Test Onboard .zip`, or `Anchor.exe .zip` links, while keeping
         `Anchor Doctor`, `Zombie Hunter`, and `Skill Foundry`.
      2. In Shareable Collaborator Edition, unconfigured Step 1 profile does NOT pre-fill "John" or
         "Samwise Gamgee", and `/onboard-wizard` & `/recover-account` hide the `/gwl-admin` link.
      3. In John's Admin Edition (`PUTER` / `Anchor Admin.exe` / `ANCHOR_EDITION=admin`), Cave of Wonders
         KEEPS `Anchor Admin` (with `anchor-admin-key.jpg`), `Test Onboard .zip`, `Anchor.exe .zip`,
         and `Anchor Admin.exe`.
      4. `build_or_resolve_exe_zip_package("prod")` stamps `Anchor/anchor-edition.json` as `"collaborator"`
         and `build_or_resolve_exe_zip_package("admin")` stamps `Anchor Admin/anchor-edition.json` as `"admin"`.
    """
    import zipfile as _zf
    import gwl_admin_gui
    import high_seat_page as hsp
    import onboard_wizard
    import paths

    ctx_base = {
        "steward": {"high_seat_name": "Cave of Wonders", "label": "Aladdin"},
        "build": "test-build",
        "today_str": "Oct 25",
        "week": "Week 43",
    }

    # --- A. Collaborator Edition (Merrill's shared version) ---
    collab_dir = tmp_path / "merrill_collab"
    collab_dir.mkdir(parents=True)
    (collab_dir / "anchor-edition.json").write_text(
        json.dumps({"edition": "collaborator", "hide_admin_and_download_links": True}),
        encoding="utf-8",
    )
    monkeypatch.setenv("ANCHOR_EDITION", "collaborator")
    assert paths.is_anchor_admin_edition(collab_dir) is False

    hdr_collab = hsp._hdr(ctx_base)
    assert "Anchor Doctor" in hdr_collab
    assert "Zombie Hunter" in hdr_collab
    assert "Skill Foundry" in hdr_collab
    assert "/gwl-admin" not in hdr_collab
    assert "Anchor Admin" not in hdr_collab
    assert "Anchor-Test-Onboard.zip" not in hdr_collab
    assert "Anchor.zip" not in hdr_collab

    prof_collab = onboard_wizard.get_active_user_profile(sandbox=True, base_dir=collab_dir)
    assert prof_collab["display_name"] == ""
    assert prof_collab["pseudonym"] == ""

    wiz_collab_html = onboard_wizard.render_onboard_wizard_html(sandbox=False, base_dir=collab_dir)
    assert 'href="/gwl-admin"' not in wiz_collab_html
    assert 'id="btnToggleSandbox"' not in wiz_collab_html

    rec_collab_html = gwl_admin_gui.render_account_recovery_html(sandbox=False, base_dir=collab_dir)
    assert 'href="/gwl-admin"' not in rec_collab_html

    # --- B. John's Admin Edition (`PUTER` / `Anchor Admin.exe`) ---
    monkeypatch.setenv("ANCHOR_EDITION", "admin")
    assert paths.is_anchor_admin_edition(tmp_path) is True

    hdr_admin = hsp._hdr(ctx_base)
    assert "/gwl-admin" in hdr_admin
    assert "anchor-admin-key.jpg" in hdr_admin
    assert "Anchor-Test-Onboard.zip" in hdr_admin
    assert "Anchor.zip" in hdr_admin
    assert "Anchor-Admin.zip" in hdr_admin

    wiz_admin_html = onboard_wizard.render_onboard_wizard_html(sandbox=False, base_dir=tmp_path)
    assert 'href="/gwl-admin"' in wiz_admin_html

    # --- C. Package builder produces distinct Collaborator (`Anchor.zip`) and Admin (`Anchor-Admin.zip`) ---
    dist_dir = tmp_path / "dist"
    (dist_dir / "Anchor").mkdir(parents=True)
    (dist_dir / "Anchor" / "Anchor.exe").write_bytes(b"MZ-fake-exe")

    prod_zip, prod_name = onboard_wizard.build_or_resolve_exe_zip_package("prod", dist_dir=dist_dir)
    assert prod_name == "Anchor.zip"
    with _zf.ZipFile(prod_zip, "r") as zf:
        ed_doc = json.loads(zf.read("Anchor/anchor-edition.json").decode("utf-8"))
        assert ed_doc["edition"] == "collaborator"
        assert ed_doc["hide_admin_and_download_links"] is True

    adm_zip, adm_name = onboard_wizard.build_or_resolve_exe_zip_package("admin", dist_dir=dist_dir)
    assert adm_name == "Anchor-Admin.zip"
    with _zf.ZipFile(adm_zip, "r") as zf:
        ed_adm = json.loads(zf.read("Anchor Admin/anchor-edition.json").decode("utf-8"))
        assert ed_adm["edition"] == "admin"
        assert ed_adm["hide_admin_and_download_links"] is False
        assert "Anchor Admin/Anchor Admin.exe" in zf.namelist()





