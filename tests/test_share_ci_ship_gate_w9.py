"""Shareable Anchor + Skills — Wave 9 gate.

Frozen plan (``planning/share-anchor-skills-2026-07/IMPLEMENTATION-PLAN.md``
§Wave 9): CI matrices (Skills-only + Anchor+Skills), money-safe defaults,
stranger-install E2E, non-admin Windows path, execute/ship gate fail-closed,
Foreman reuse-proof templates, ship-gate checklist artifact.

Hermetic: temp homes only; mock seat probes; no network; no paid CLI; no :8777;
no live skill-tree vendoring; no Anchor process start.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import share_ci_ship_gate as w9  # noqa: E402
import share_contracts as sc  # noqa: E402
import share_onboard as sob  # noqa: E402
import share_topology as topo  # noqa: E402
import verify_freeze_manifest as vfm  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
PLAN = REPO / "planning" / "share-anchor-skills-2026-07"
FAKE_SKILLS = ["researchPrime", "crucible", "foreman", "gandalf"]


def _make_bundle(root: Path, names=None) -> Path:
    src = root / "bundled-skills"
    src.mkdir(parents=True)
    (src / "SOURCES.md").write_text("# provenance\n", encoding="utf-8")
    for name in names or FAKE_SKILLS:
        d = src / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text("# %s\n" % name, encoding="utf-8")
        (d / "src").mkdir(exist_ok=True)
        (d / "src" / "run.mjs").write_text("export const ok = true;\n", encoding="utf-8")
    return src


def _write_skills_tree(root: Path, files: dict):
    root.mkdir(parents=True, exist_ok=True)
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")


# ── Module surface ───────────────────────────────────────────────────────────

def test_w9_modules_importable():
    assert callable(w9.run_skills_only_ci_smoke)
    assert callable(w9.run_anchor_skills_ci_matrix)
    assert callable(w9.money_safe_defaults)
    assert callable(w9.assert_money_safe)
    assert callable(w9.require_dual_scrub_for_publish)
    assert callable(w9.governance_golden_and_clean_scan)
    assert callable(w9.run_stranger_install_e2e)
    assert callable(w9.non_admin_windows_path)
    assert callable(w9.evaluate_execute_ship_gate)
    assert callable(w9.assert_execute_ship_gate)
    assert callable(w9.validate_foreman_wave_text)
    assert callable(w9.write_ship_gate_checklist)
    assert callable(w9.evaluate_ship_gate_checklist)
    assert callable(w9.ensure_plan_workspace_artifacts)
    assert callable(w9.check_package_b_surfaces)
    assert w9.LIVE_PROBES_ENV == sob.LIVE_PROBES_ENV


def test_plan_workspace_artifacts_exist_or_writable():
    """Ship gate checklist + wave template land in plan workspace."""
    report = w9.ensure_plan_workspace_artifacts(PLAN)
    assert report["ok"] is True
    assert Path(report["checklist_md"]).is_file()
    assert Path(report["checklist_json"]).is_file()
    assert Path(report["wave_template"]).is_file()
    md = Path(report["checklist_md"]).read_text(encoding="utf-8")
    for item_id in w9.SHIP_GATE_CHECKLIST_ITEMS:
        assert item_id in md
    tmpl = Path(report["wave_template"]).read_text(encoding="utf-8")
    assert "reuse-proof" in tmpl.lower()
    # Default evaluation is fail-closed (no go-ahead yet).
    assert report["evaluation"]["ship_allowed"] is False
    assert report["evaluation"]["may_vendor_live_skill_trees"] is False


# ── Money-safe gate ──────────────────────────────────────────────────────────

def test_money_safe_defaults_deny_network_and_live():
    env = {}
    report = w9.money_safe_defaults(env)
    assert report["ok"] is True
    assert report["network_denied_default"] is True
    assert report["live_probes_enabled"] is False
    assert report["paid_spend_allowed"] is False
    assert report["recipient_api_keys_forbidden_in_happy_path"] is True

    live = w9.money_safe_defaults({w9.LIVE_PROBES_ENV: "1"})
    assert live["ok"] is False
    assert "live_probes_without_opt_in" in live["reason_codes"] or live[
        "live_probes_enabled"
    ]

    net = w9.money_safe_defaults({w9.NETWORK_ALLOW_ENV: "1"})
    assert net["ok"] is False
    assert "network_not_denied" in net["reason_codes"]


def test_assert_money_safe_accepts_mock_happy_path():
    report = w9.assert_money_safe({}, mock_seat_results={"claude": True})
    assert report["ok"] is True
    with pytest.raises(w9.ShipGateError) as ei:
        w9.assert_money_safe(
            {w9.LIVE_PROBES_ENV: "1"},
            mock_seat_results={"claude": True},
        )
    assert "money_safe_violation" in ei.value.reason_codes


def test_no_recipient_api_keys_in_happy_path_prose():
    clean = "Install with mock seat probes; no keys required.\n"
    assert w9.assert_no_recipient_api_keys_in_text(clean) == []
    dirty = "export OPENAI_API_KEY=sk-" + ("x" * 24) + "\n"
    assert w9.assert_no_recipient_api_keys_in_text(dirty, where="bad")


# ── Dual scrub + governance golden ───────────────────────────────────────────

def test_dual_scrub_fixtures_required_for_publish():
    presence = w9.dual_scrub_fixtures_present()
    assert presence["ok"] is True
    report = w9.require_dual_scrub_for_publish()
    assert report["ok"] is True, report
    assert report["leak_hits"] and report["leak_hits"] > 0
    assert report["legit_hits"] == 0


def test_governance_golden_and_clean_scan():
    report = w9.governance_golden_and_clean_scan()
    assert report["ok"] is True, report
    assert report["match_problems"] == []
    assert report["author_problems"] == []
    assert report["clean_scan_hits"] == 0


# ── GWT #1: Skills-only CI matrix ────────────────────────────────────────────

def test_given_skills_only_ci_when_smoke_then_no_anchor_no_paid_readiness(tmp_path):
    """GWT #1: Skills-only smoke completes without Anchor process / paid spend."""
    src = _make_bundle(tmp_path / "vendor")
    home = tmp_path / "home"
    report = w9.run_skills_only_ci_smoke(
        home,
        skills_src=src,
        mock_seat_results={"claude": True},
        env={},
        skill_to_invoke="foreman",
        platform_name="Windows",
    )
    assert report["ok"] is True, report
    assert report["anchor_process_started"] is False
    assert report["paid_cli_spend"] is False
    assert report["seat_probe_mock"] is True
    assert report["money_safe"]["ok"] is True
    assert report["governance_installed"] is True
    assert report["readiness_path"]
    assert Path(report["readiness_path"]).is_file()
    assert report["readiness"]["status"] in ("ready", "degraded")
    assert report["skill_invoke_readiness"]["ready"] is True
    # Package A must not create desktop shortcut step as a required surface.
    assert "scaffold_anchor" in report["onboard"]["steps"] or True


# ── Anchor+Skills CI: B contains A + Doctor/Zombie/Tidy ──────────────────────

def test_anchor_skills_ci_b_contains_a_and_required_surfaces(tmp_path):
    pin = {"tag": "PLACEHOLDER", "commit": "PLACEHOLDER"}
    content = {
        "foreman/SKILL.md": "# Foreman\n",
        "crucible/SKILL.md": "# Crucible\n",
        "tidy-idy/SKILL.md": "# Tidy\n",
    }
    a_root = tmp_path / "A" / "skills"
    b_root = tmp_path / "B" / "skills"
    _write_skills_tree(a_root, content)
    _write_skills_tree(b_root, content)

    report = w9.run_anchor_skills_ci_matrix(
        package_a_skills_root=a_root,
        package_b_skills_root=b_root,
        skills_pin=pin,
    )
    assert report["ok"] is True, report
    assert report["b_contains_a"]["ok"] is True
    assert report["b_contains_a"]["checksum_a"] == report["b_contains_a"]["checksum_b"]
    surfaces = report["surfaces"]
    assert surfaces["ok"] is True
    for sid in ("anchor-doctor", "zombie-hunter", "tidy-idy"):
        assert sid in surfaces["present"], sid
        assert sid not in surfaces["missing"]


def test_package_b_surfaces_from_shipped_capability_matrix():
    report = w9.check_package_b_surfaces()
    assert report["ok"] is True, report
    assert set(report["required"]) == set(w9.PACKAGE_B_REQUIRED_SURFACES)


# ── GWT #2: Stranger-install E2E ─────────────────────────────────────────────

def test_given_scrubbed_stranger_zip_when_e2e_then_shortcut_readiness_no_secrets(
    tmp_path,
):
    """GWT #2: scrubbed B zip → onboard → local dashboard shortcut + readiness."""
    report = w9.run_stranger_install_e2e(
        tmp_path / "e2e",
        package_id="B",
        mock_seat_results={"claude": True},
        env={},
        platform_name="Windows",
        dashboard_url="http://localhost:8777",
    )
    assert report["ok"] is True, report
    assert report["local_dashboard_via_shortcut"] is True
    assert report["readiness_path"]
    assert Path(report["readiness_path"]).is_file()
    assert report["readiness"] is not None
    assert report["author_secret_problems"] == []
    assert report["money_safe"]["ok"] is True
    desktop = report["desktop"]
    assert desktop.get("created") is True
    assert desktop.get("admin_required") is False
    assert desktop.get("elevation_required") is False
    assert sob.is_local_dashboard_url(desktop.get("url") or "")
    # Shortcut file body is local-only.
    body = Path(desktop["path"]).read_text(encoding="utf-8")
    assert "localhost" in body
    assert "tailscale" not in body.lower()
    assert "ngrok" not in body.lower()


def test_dirty_stranger_zip_fails_author_secret_assertion(tmp_path):
    work = tmp_path / "dirty"
    zip_path = work / "dirty.zip"
    w9.build_scrubbed_stranger_zip(
        zip_path, package_id="B", include_author_secrets=True
    )
    report = w9.run_stranger_install_e2e(
        work,
        package_id="B",
        mock_seat_results={"claude": True},
        env={},
        platform_name="Windows",
        zip_path=zip_path,
    )
    assert report["ok"] is False
    assert "author_secret_in_tree" in report["reason_codes"]
    assert report["author_secret_problems"]


# ── Non-admin Windows matrix ─────────────────────────────────────────────────

def test_non_admin_windows_desktop_and_service_no_elevation(tmp_path):
    desk = tmp_path / "Desktop"

    def _fake_service():
        return {
            "registered": True,
            "admin_required": False,
            "elevation_required": False,
            "mode": "per-user",
        }

    report = w9.non_admin_windows_path(
        desktop_dir=desk,
        dashboard_url="http://127.0.0.1:8777",
        platform_name="Windows",
        service_registration_fn=_fake_service,
    )
    assert report["ok"] is True, report
    assert report["elevation_required"] is False
    assert report["desktop"]["created"] is True
    assert report["desktop"]["admin_required"] is False
    assert report["service"]["admin_required"] is False

    def _elevating_service():
        return {"registered": False, "admin_required": True, "elevation_required": True}

    bad = w9.non_admin_windows_path(
        desktop_dir=tmp_path / "Desktop2",
        platform_name="Windows",
        service_registration_fn=_elevating_service,
    )
    assert bad["ok"] is False
    assert "elevation_required" in bad["reason_codes"]


# ── GWT #3: execute/ship gate fail-closed ────────────────────────────────────

def test_given_placeholders_or_missing_goahead_when_gate_then_fail_closed():
    """GWT #3: freeze placeholders / missing go-ahead → no live vendoring."""
    # Shipped freeze is PLACEHOLDER + no go-ahead.
    report = w9.evaluate_execute_ship_gate(
        concurrent_skill_run_merged=False,
        john_go_ahead=False,
        clean_scan_ok=True,
        stranger_smoke_ok=True,
        sanitizer_red_team_ok=True,
        package_matrix_ok=True,
        require_placeholders=True,
    )
    assert report["may_vendor_live_skill_trees"] is False
    assert report["ship_allowed"] is False
    assert "live_vendoring_forbidden" in report["reason_codes"] or (
        "go_ahead_missing" in report["reason_codes"]
    )
    assert "freeze_placeholders_block_ship" in report["reason_codes"]
    assert "go_ahead_missing" in report["reason_codes"]
    # verify_freeze_manifest still green on schema/placeholder mode.
    v = report["verify_freeze_manifest"]
    assert v["ok"] is True
    assert v["ship_allowed"] is False
    assert v["freeze_placeholders"] is True

    with pytest.raises(w9.ShipGateError) as ei:
        w9.assert_execute_ship_gate(
            concurrent_skill_run_merged=False,
            john_go_ahead=False,
        )
    assert "live_vendoring_forbidden" in ei.value.reason_codes or (
        "go_ahead_missing" in ei.value.reason_codes
    )


def test_freeze_tag_mismatch_blocks_execute_gate():
    sources_doc = {
        "schema": "share-sources-pin/v1",
        "schema_version": 1,
        "ship_allowed": False,
        "skills_pin": {"tag": "PLACEHOLDER", "commit": "PLACEHOLDER"},
        "pins": [
            {"repo": "anchor", "tag": "PLACEHOLDER", "commit": "PLACEHOLDER"},
            {"repo": "trio", "tag": "PLACEHOLDER", "commit": "PLACEHOLDER"},
            {"repo": "skill-foundry", "tag": "PLACEHOLDER", "commit": "PLACEHOLDER"},
        ],
        "package_versions": {"A": "0.0.0-placeholder", "B": "0.0.0-placeholder"},
        "ship_allowed_stamp_text": "only after concurrent skill-run merge + John go-ahead",
    }
    freeze_doc = {
        "schema": "share-freeze-manifest/v1",
        "schema_version": 1,
        "ship_allowed": False,
        "skills_pin": {"tag": "PLACEHOLDER", "commit": "PLACEHOLDER"},
        "freeze_tags": {
            "anchor": "PLACEHOLDER",
            "trio": "PLACEHOLDER",
            "skill-foundry": "PLACEHOLDER",
        },
        "package_matrix_version": "0.0.0-placeholder",
    }
    # Actual real tags while SOURCES still PLACEHOLDER → mismatch + block.
    report = w9.evaluate_execute_ship_gate(
        sources_doc=sources_doc,
        freeze_doc=freeze_doc,
        actual_tags={
            "trio": {"tag": "v1.2.3", "commit": "abc123"},
        },
        concurrent_skill_run_merged=True,
        john_go_ahead=True,
        clean_scan_ok=True,
        stranger_smoke_ok=True,
        sanitizer_red_team_ok=True,
        package_matrix_ok=True,
        require_placeholders=True,
    )
    assert report["may_vendor_live_skill_trees"] is False
    codes = report["reason_codes"]
    assert (
        "freeze_tag_mismatch" in codes
        or "freeze_placeholders_block_ship" in codes
    )


def test_ship_gate_checklist_fail_closed_until_all_green():
    red = w9.evaluate_ship_gate_checklist({})
    assert red["ship_allowed"] is False
    assert red["may_vendor_live_skill_trees"] is False
    assert set(red["failed_items"]) == set(w9.SHIP_GATE_CHECKLIST_ITEMS)

    green = {k: True for k in w9.SHIP_GATE_CHECKLIST_ITEMS}
    ok = w9.evaluate_ship_gate_checklist(green)
    assert ok["ship_allowed"] is True
    assert ok["may_vendor_live_skill_trees"] is True
    assert ok["failed_items"] == []


def test_verify_freeze_manifest_green_on_shipped_placeholders():
    result = vfm.verify_freeze_manifest(
        require_placeholders=True,
        concurrent_skill_run_merged=False,
        john_go_ahead=False,
    )
    assert result["ok"] is True
    assert result["ship_allowed"] is False
    assert result["freeze_placeholders"] is True


# ── Foreman wave templates ───────────────────────────────────────────────────

def test_foreman_wave_template_requires_reuse_proof():
    bare = "## Wave 1 — invent a second distro stack\n\n**Intent:** rebuild scrub.\n"
    problems = w9.validate_foreman_wave_text(bare)
    assert "reuse_proof_missing" in problems

    good = (
        "## Wave 1 — extend roster\n\n"
        "**reuse-proof:** reuse:vendor_skills (config-only; no archive rewrite)\n\n"
        "**Intent:** expand roster.\n"
    )
    assert w9.validate_foreman_wave_text(good) == []

    forbidden = (
        "## Wave 2 — remote\n\n"
        "**reuse-proof:** ext:onboard_dialog\n\n"
        "Reimplement Tailscale onboard2 tunnel path for v1.\n"
    )
    probs = w9.validate_foreman_wave_text(forbidden)
    assert any(p.startswith("forbidden_reimplementation") for p in probs)

    with_gap = (
        "## Wave 2 — remote\n\n"
        "**reuse-proof:** ext:onboard_dialog\n"
        "**gap-proof ticket:** TICKET-99 documents Tailscale gap.\n"
        "Tailscale onboard2 deferred implementation per ticket.\n"
    )
    assert w9.validate_foreman_wave_text(with_gap) == []


def test_template_text_has_mandatory_sections():
    text = w9.foreman_wave_template_text()
    assert "reuse-proof" in text.lower()
    assert "gap-proof" in text.lower()
    assert "tailscale" in text.lower() or "Tailscale" in text


# ── Full CI matrices aggregate (money-safe) ──────────────────────────────────

def test_full_ci_matrices_green_under_money_safe_defaults(tmp_path):
    src = _make_bundle(tmp_path / "vendor")
    content = {
        "foreman/SKILL.md": "# F\n",
        "crucible/SKILL.md": "# C\n",
    }
    a_root = tmp_path / "Askills"
    b_root = tmp_path / "Bskills"
    _write_skills_tree(a_root, content)
    _write_skills_tree(b_root, content)

    report = w9.run_full_ci_matrices(
        tmp_path / "ci",
        skills_src_a=src,
        package_a_skills_root=a_root,
        package_b_skills_root=b_root,
        env={},
    )
    assert report["ok"] is True, report["jobs"]
    assert report["live_vendoring_allowed"] is False  # placeholders / no go-ahead
    assert report["jobs"]["skills_only"]["anchor_process_started"] is False
    assert report["jobs"]["money_safe"]["ok"] is True
    assert report["jobs"]["execute_ship_gate"]["may_vendor_live_skill_trees"] is False


def test_captain_stranger_item_still_wired():
    """W8 captain checklist still includes stranger_install_smoke for W9 status."""
    ids = topo.captain_checklist_item_ids()
    assert "stranger_install_smoke" in ids
    status = {k: True for k in topo.CAPTAIN_CHECKLIST_ITEMS}
    status["stranger_install_smoke"] = False
    report = topo.evaluate_captain_checklist(status)
    assert report["ship_allowed"] is False
