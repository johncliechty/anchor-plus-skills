"""Tests for Variable Strength model routing + Unified Anvil Zero-Flash alignment (2026-11-28)."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

import anchor_settings
import high_seat_core
import model_policy
from steward_cockpit import (
    aegis_session,
    anvil_comprehension_engine,
    anvil_session,
    code_jobs,
    skill_jobs,
    steward_engine,
    steward_routes,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
TRIO_POLICY_MJS = Path("C:/dev/trio/drivers/model-policy.mjs")

CATALOGS = {
    "claude": [
        {"model": "claude-fable-5-2", "rank": 0, "efforts": ["low", "medium", "high", "max"]},
        {"model": "claude-opus-5-5", "rank": 1, "efforts": ["low", "medium", "high", "max"]},
        {"model": "claude-sonnet-4-6", "rank": 2, "efforts": ["low", "medium", "high"]},
        {"model": "claude-haiku-4-5", "rank": 3, "efforts": ["low", "medium"]},
        {"model": "best", "rank": 4, "efforts": ["low", "medium", "high", "max"]},
        {"model": "opus", "rank": 5, "efforts": ["low", "medium", "high", "max"]},
    ],
    "chatgpt": [
        {"model": "gpt-6-luna", "rank": 0, "efforts": ["low", "medium", "high", "max"]},
        {"model": "gpt-5.6-spark", "rank": 1, "efforts": ["low", "medium"]},
        {"model": "gpt-5.6-terra", "rank": 2, "efforts": ["low", "medium", "high", "xhigh"]},
        {"model": "gpt-5.6-mini", "rank": 3, "efforts": ["low", "medium"]},
    ],
    "gemini": [
        {"model": "gemini-4-neon", "rank": 0, "efforts": ["low", "medium", "high", "xhigh"]},
        {"model": "gemini-4-flash", "rank": 1, "efforts": ["low", "medium", "high"]},
        {"model": "gemini-4-orchestrator", "rank": 2, "efforts": ["high"]},
        {"model": "gemini-4-carbon", "rank": 3, "efforts": ["low", "medium", "high", "xhigh"]},
    ],
    "grok": [
        {"model": "grok-4.7", "rank": 0, "efforts": ["low", "medium", "high", "xhigh"]},
    ],
}


def test_python_and_node_select_strength_exact_parity():
    assert TRIO_POLICY_MJS.is_file(), f"Missing {TRIO_POLICY_MJS}"
    mjs_url = TRIO_POLICY_MJS.resolve().as_uri()
    script = f"""
import {{ selectStrength }} from {json.dumps(mjs_url)};
const catalogs = {json.dumps(CATALOGS)};
const out = {{}};
for (const [fam, rows] of Object.entries(catalogs)) {{
  out[fam] = {{}};
  for (const tier of ['standard', 'heavy', 'light']) {{
    const s = selectStrength(fam, rows, tier);
    out[fam][tier] = {{ model: s.model, effort: s.effort }};
  }}
}}
process.stdout.write(JSON.stringify(out));
"""
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=20,
    )
    node_out = json.loads(proc.stdout)

    expected = {
        "claude": {
            "standard": {"model": "claude-opus-5-5", "effort": "medium"},
            "light": {"model": "claude-opus-5-5", "effort": "medium"},
            "heavy": {"model": "claude-fable-5-2", "effort": "max"},
        },
        "chatgpt": {
            "standard": {"model": "gpt-5.6-terra", "effort": "medium"},
            "light": {"model": "gpt-5.6-terra", "effort": "medium"},
            "heavy": {"model": "gpt-6-luna", "effort": "max"},
        },
        "gemini": {
            "standard": {"model": "gemini-4-carbon", "effort": "medium"},
            "light": {"model": "gemini-4-carbon", "effort": "medium"},
            "heavy": {"model": "gemini-4-neon", "effort": "xhigh"},
        },
        "grok": {
            "standard": {"model": "grok-4.7", "effort": "medium"},
            "light": {"model": "grok-4.7", "effort": "medium"},
            "heavy": {"model": "grok-4.7", "effort": "xhigh"},
        },
    }

    for fam, tiers in expected.items():
        for tier_name, exp in tiers.items():
            py_sel = model_policy.select_strength(fam, CATALOGS[fam], tier_name)
            assert {"model": py_sel["model"], "effort": py_sel["effort"]} == exp
            assert node_out[fam][tier_name] == exp


def test_five_level_skill_precedence_and_spelling_aliases():
    assert model_policy.canonical_skill_name("Checkov") == "chekhov"
    assert model_policy.canonical_skill_name("Agies") == "aegis"
    assert model_policy.canonical_skill_name("SuperJump") == "superjump"
    assert model_policy.canonical_skill_name("ResearchPrime") == "researchprime"

    # Regular skills default to standard
    for sk in ("gandalf", "researchPrime", "crucible", "foreman", "einstein", "scribe"):
        assert model_policy.resolve_skill_strength(skill=sk) == "standard"
        assert model_policy.resolve_skill_strength(skill=sk, cockpit_strength="heavy") == "heavy"

    # 4 Heavy-by-default skills
    for sk in ("Anvil", "Checkov", "Agies", "SuperJump"):
        assert model_policy.resolve_skill_strength(skill=sk) == "heavy"
        assert model_policy.resolve_skill_strength(skill=sk, cockpit_strength="standard") == "heavy"
        assert model_policy.resolve_skill_strength(skill=sk, explicit_strength="light") == "light"
        assert model_policy.resolve_skill_strength(skill=sk, inherited_strength="light") == "light"

    # Leading qualifiers
    q_hvy = model_policy.parse_leading_skill_qualifier("ResearchPrime Heavy: investigate latency")
    assert q_hvy["skill"] == "researchprime"
    assert q_hvy["strength"] == "heavy"

    q_lgt = model_policy.parse_leading_skill_qualifier("Checkov Light — check chapter 4 continuity")
    assert q_lgt["skill"] == "chekhov"
    assert q_lgt["strength"] == "light"


def test_claude_variable_strength_verification_attestation():
    ok_std = model_policy.attest_claude_fable_receipt(
        {
            "ok": True,
            "requested_model": "claude-opus-5-5",
            "model_served": "claude-opus-5-5-20261001",
            "model_attested": True,
        },
        role="review",
        label="review:code-job",
        tier="standard",
    )
    assert ok_std["ok"] is True
    assert ok_std["model_served"] == "claude-opus-5-5"

    bad_haiku = model_policy.attest_claude_fable_receipt(
        {
            "ok": True,
            "requested_model": "claude-opus-5-5",
            "model_served": "claude-haiku-4-5",
            "model_attested": True,
        },
        role="review",
        label="review:code-job",
        tier="light",
    )
    assert bad_haiku["ok"] is False
    assert bad_haiku["status"] == "attestation_mismatch"

    bad_heavy = model_policy.attest_claude_fable_receipt(
        {
            "ok": True,
            "requested_model": "claude-fable-5-2",
            "model_served": "claude-opus-5-5",
            "model_attested": True,
        },
        role="review",
        label="review:code-job",
        tier="heavy",
    )
    assert bad_heavy["ok"] is False

    ok_stepdown = model_policy.attest_claude_fable_receipt(
        {
            "ok": True,
            "requested_model": "claude-fable-5-2",
            "model_served": "claude-opus-5-5",
            "model_attested": True,
            "allow_quota_stepdown": True,
            "quota_stepdown_from": "claude-fable-5-2",
        },
        role="review",
        label="review:code-job",
        tier="heavy",
    )
    assert ok_stepdown["ok"] is True
    assert ok_stepdown["model_served"] == "claude-opus-5-5"


def test_cockpit_aegis_and_anvil_strength_persistence_and_oranges_labels(tmp_path, monkeypatch):
    cdir = tmp_path / "effort"
    cdir.mkdir()

    # Cockpit strength defaults to standard and toggles to heavy
    assert steward_engine.read_cockpit_strength(cdir) == "standard"
    res, code = steward_routes.handle_post(str(cdir), "strength", {"strength": "heavy"})
    assert code == 200 and res["cockpit_strength"] == "heavy"
    get_res, get_code = steward_routes.handle_get(str(cdir), "strength", {})
    assert get_code == 200 and get_res["cockpit_strength"] == "heavy"

    # Anvil defaults to heavy and toggles to light
    assert anvil_comprehension_engine.read_anvil_strength(cdir) == "heavy"
    anvil_comprehension_engine.write_anvil_strength(cdir, "light")
    assert anvil_comprehension_engine.read_anvil_strength(cdir) == "light"
    anvil_seat_light = anvil_session._read_model_seating_info(cdir=cdir)
    assert anvil_seat_light["strength"] == "light"

    # Aegis defaults to heavy and toggles to light
    assert aegis_session.read_aegis_strength(cdir) == "heavy"
    aeg_res = aegis_session.set_aegis_strength(cdir, "light")
    assert aeg_res["ok"] is True
    assert aeg_res["strength"] == "light"
    assert aegis_session.read_aegis_strength(cdir) == "light"

    # Chief-of-Staff Oranges pre-staging stamps ⚡ Heavy on Superjump/Chekhov and Standard on Gandalf/researchPrime
    assert high_seat_core._oranges_default_strength("Superjump") == "heavy"
    assert high_seat_core._oranges_default_strength("Chekhov") == "heavy"
    assert high_seat_core._oranges_default_strength("Gandalf") == "standard"
    assert high_seat_core._oranges_default_strength("researchPrime") == "standard"


def test_skill_and_code_job_strength_inference(tmp_path, monkeypatch):
    cdir = tmp_path / "cockpit"
    cdir.mkdir()
    settings_dir = tmp_path / "settings"
    settings_dir.mkdir()
    monkeypatch.setenv("ANCHOR_SETTINGS_DIR", str(settings_dir))
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(settings_dir))
    anchor_settings.save_settings(
        coding_family="claude",
        review_family="gemini",
        default_cli="claude",
        model_policy={"mode": "variable_strength", "default_strength": "standard"},
    )

    # Regular code job defaults to standard
    assert code_jobs._resolve_code_job_strength(cdir, brief="Fix parser bug", worker="coder") == "standard"
    # Leading Foreman Heavy upgrades to heavy
    assert code_jobs._resolve_code_job_strength(cdir, brief="Foreman Heavy: run full build", worker="foreman") == "heavy"
    # Heavy-default skill Anvil defaults to heavy, Anvil Light steps down to light
    assert code_jobs._resolve_code_job_strength(cdir, brief="Map repository", skill="Anvil", worker="coder") == "heavy"
    assert code_jobs._resolve_code_job_strength(cdir, brief="Anvil Light: quick scan", skill="Anvil", worker="coder") == "light"

    # Skill jobs CLI inference
    sk_g, tr_g = skill_jobs._infer_skill_and_cli_tier(["node", "C:/dev/Skill Foundry/skills/gandalf/runtime/gandalf-run.mjs", "--tier", "Heavy"], "")
    assert sk_g == "gandalf" and tr_g == "heavy"
    sk_sj, tr_sj = skill_jobs._infer_skill_and_cli_tier(["node", "C:/dev/Skill Foundry/skills/superjump/bin/superjump-run.mjs"], "")
    assert sk_sj == "superjump" and tr_sj is None


def test_unified_anvil_zero_v5_boot_flash_and_foundry_gui_labels():
    body, _mime = steward_routes.serve_static("anvil.html")
    assert body is not None
    html_txt = body.decode("utf-8", errors="replace")
    assert 'data-anvil-v6-enabled="1"' in html_txt
    assert "Anvil · Process Workbench &amp; Scientific IDE" in html_txt
    assert "Anvil v5 · B3 Workbench" not in html_txt
    assert 'id="btnAnvilStrengthPill"' in html_txt

    # Zero inline script lines in anvil.html
    scripts = re.findall(r"<script\b[^>]*>(.*?)</script>", html_txt, flags=re.S | re.I)
    assert all(not s.strip() for s in scripts)

    # Foundry GUI JSX components + built bundle use plain "Anvil" without stale UI version labels
    jsx_tab = (REPO_ROOT / "foundry-gui" / "src" / "components" / "v3" / "AnvilWorkbenchTab.jsx").read_text(encoding="utf-8")
    jsx_studio = (REPO_ROOT / "foundry-gui" / "src" / "FoundryStudioV3.jsx").read_text(encoding="utf-8")
    assert "Anvil v4" not in jsx_tab and "Anvil v5" not in jsx_tab
    assert "Anvil v4" not in jsx_studio and "Anvil v5" not in jsx_studio
    assert "⚒️ Anvil" in jsx_tab

    dist_assets = list((REPO_ROOT / "foundry-gui" / "dist" / "assets").glob("index-*.js"))
    assert dist_assets, "Expected built foundry-gui dist bundle"
    bundle_txt = dist_assets[0].read_text(encoding="utf-8", errors="replace")
    assert ("⚒️ Anvil v4" not in bundle_txt), "Found stale ⚒️ Anvil v4 tab label in built bundle"
    assert ("Maps · Swarm Flow · Anvil →" in bundle_txt), "Expected updated plain Anvil card link in built bundle"
    assert ("Process Workbench & Scientific IDE" in bundle_txt), "Expected Unified Anvil subtitle in built bundle"


def test_configurable_relative_steps_and_subscription_tier_parity():
    custom_policy = model_policy.validate_policy({
        "mode": "variable_strength",
        "default_strength": "standard",
        "top_effort": "max",
        "heavy": {"model_steps_below": 1, "effort_steps_below": 0},
        "light": {"model_steps_below": 2, "effort_steps_below": 2},
        "heavy_skills": ["anvil", "gandalf"],
    })
    assert custom_policy["top_effort"] == "max"
    assert custom_policy["heavy"] == {"model_steps_below": 1, "effort_steps_below": 0}
    assert custom_policy["light"] == {"model_steps_below": 2, "effort_steps_below": 2}
    assert custom_policy["heavy_skills"] == ["anvil", "gandalf"]

    mjs_url = TRIO_POLICY_MJS.resolve().as_uri()
    script = f"""
import {{ selectStrength, validatePolicy }} from {json.dumps(mjs_url)};
const pol = validatePolicy({json.dumps(custom_policy)});
const catalogs = {json.dumps(CATALOGS)};
const out = {{}};
for (const [fam, rows] of Object.entries(catalogs)) {{
  out[fam] = {{
    heavy: selectStrength(fam, rows, 'heavy', pol),
    light: selectStrength(fam, rows, 'light', pol),
  }};
}}
process.stdout.write(JSON.stringify(out));
"""
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True, text=True, encoding="utf-8", check=True, timeout=20,
    )
    node_out = json.loads(proc.stdout)

    # Heavy = 1 step below top model @ 0 steps below max effort; Light = 2 steps below top model @ medium
    expected_custom = {
        "claude": {
            "heavy": ("claude-opus-5-5", "max"),
            "light": ("claude-sonnet-4-6", "medium"),
        },
        "chatgpt": {
            "heavy": ("gpt-5.6-terra", "xhigh"),
            "light": ("gpt-5.6-terra", "medium"),
        },
        "gemini": {
            "heavy": ("gemini-4-carbon", "xhigh"),
            "light": ("gemini-4-carbon", "medium"),
        },
        "grok": {
            "heavy": ("grok-4.7", "xhigh"),
            "light": ("grok-4.7", "medium"),
        },
    }
    for fam, pairs in expected_custom.items():
        for tier_name, (exp_m, exp_e) in pairs.items():
            py_s = model_policy.select_strength(fam, CATALOGS[fam], tier_name, policy=custom_policy)
            assert (py_s["model"], py_s["effort"]) == (exp_m, exp_e)
            assert (node_out[fam][tier_name]["model"], node_out[fam][tier_name]["effort"]) == (exp_m, exp_e)

    # High ceiling cap: top_effort="high" makes 0 steps = high, 1 step = medium, 2 steps = low
    high_cap_pol = model_policy.validate_policy({
        "mode": "variable_strength",
        "default_strength": "standard",
        "top_effort": "high",
        "heavy": {"model_steps_below": 0, "effort_steps_below": 0},
        "light": {"model_steps_below": 1, "effort_steps_below": 1},
    })
    assert model_policy.select_strength("claude", CATALOGS["claude"], "heavy", policy=high_cap_pol)["effort"] == "high"
    assert model_policy.select_strength("claude", CATALOGS["claude"], "light", policy=high_cap_pol)["effort"] == "medium"

    # Claude Pro subscription catalog (no claude-fable-5-2): 0 steps = claude-opus-5-5, 1 step = sonnet
    pro_rows = model_policy.normalize_catalog("claude", {
        "models": list(model_policy.CLAUDE_PRO_CATALOG_MODELS),
        "efforts": ["low", "medium", "high", "max"],
    })
    pro_heavy = model_policy.select_strength("claude", pro_rows, "heavy")
    pro_light = model_policy.select_strength("claude", pro_rows, "light")
    assert pro_heavy["model"] == "claude-opus-5-5" and pro_heavy["effort"] == "max"
    assert pro_light["model"] == "sonnet" and pro_light["effort"] == "medium"


def test_setup_apply_and_onboard_variable_strength_roundtrip(tmp_path, monkeypatch):
    import onboard_wizard
    import provider_setup

    settings_dir = tmp_path / "anchor_data"
    settings_dir.mkdir()
    monkeypatch.setenv("ANCHOR_SETTINGS_DIR", str(settings_dir))
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(settings_dir))
    saved0 = anchor_settings.save_settings(
        coding_family="claude",
        review_family="gemini",
        default_cli="claude",
        model_policy={"mode": "variable_strength", "default_strength": "standard"},
    )

    svc = provider_setup.ProviderService()
    snap0 = svc.snapshot()
    assert snap0["variable_strength"]["enabled"] is True
    assert snap0["variable_strength"]["config"]["heavy"] == {"model_steps_below": 0, "effort_steps_below": 0}
    assert snap0["variable_strength"]["config"]["light"] == {"model_steps_below": 1, "effort_steps_below": 2}
    assert set(snap0["variable_strength"]["config"]["heavy_skills"]) == {"anvil", "chekhov", "aegis", "superjump"}

    # User updates Heavy/Light definitions & toggles Gandalf into Heavy defaults via /setup
    snap1 = svc.apply({
        "expected_revision": saved0["settings_revision"],
        "variable_strength": {
            "top_effort": "max",
            "heavy": {"model_steps_below": 0, "effort_steps_below": 1},
            "light": {"model_steps_below": 2, "effort_steps_below": 2},
            "heavy_skills": ["anvil", "chekhov", "gandalf"],
        },
    })
    assert snap1["variable_strength"]["config"]["top_effort"] == "max"
    assert snap1["variable_strength"]["config"]["heavy"] == {"model_steps_below": 0, "effort_steps_below": 1}
    assert snap1["variable_strength"]["config"]["light"] == {"model_steps_below": 2, "effort_steps_below": 2}
    assert snap1["variable_strength"]["config"]["heavy_skills"] == ["anvil", "chekhov", "gandalf"]

    # Both Python and Node resolveSkillStrength honor saved heavy_skills (Gandalf -> heavy, Aegis -> standard)
    assert model_policy.resolve_skill_strength(skill="gandalf") == "heavy"
    assert model_policy.resolve_skill_strength(skill="aegis") == "standard"

    mjs_url = TRIO_POLICY_MJS.resolve().as_uri()
    node_check = subprocess.run(
        [
            "node", "--input-type=module", "-e",
            f"import {{ resolveSkillStrength }} from {json.dumps(mjs_url)};"
            f"const env = {{ ANCHOR_SETTINGS_DIR: {json.dumps(str(settings_dir))} }};"
            f"process.stdout.write(JSON.stringify({{"
            f"  gandalf: resolveSkillStrength({{ skill: 'gandalf', env }}),"
            f"  aegis: resolveSkillStrength({{ skill: 'aegis', env }})"
            f"}}));",
        ],
        capture_output=True, text=True, encoding="utf-8", check=True, timeout=20,
    )
    assert json.loads(node_check.stdout) == {"gandalf": "heavy", "aegis": "standard"}

    # Onboarding Wizard sandbox Variable Strength save round-trip
    wiz_res = onboard_wizard.dispatch_wizard_action(
        "save_variable_strength",
        {
            "variable_strength": {
                "top_effort": "high",
                "heavy": {"model_steps_below": 1, "effort_steps_below": 0},
                "light": {"model_steps_below": 1, "effort_steps_below": 1},
                "heavy_skills": ["anvil", "superjump"],
            }
        },
        sandbox=True,
        sandbox_id="vs-test",
        base_dir=tmp_path / "wiz_sb",
    )
    assert wiz_res["ok"] is True
    assert wiz_res["variable_strength"]["config"]["top_effort"] == "high"
    assert wiz_res["variable_strength"]["config"]["heavy_skills"] == ["anvil", "superjump"]

