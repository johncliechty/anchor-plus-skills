"""Shareable Anchor + Skills — Wave 8 gate.

Frozen plan (``planning/share-anchor-skills-2026-07/IMPLEMENTATION-PLAN.md``
§Wave 8): dual-audience topology, CONTRIBUTING, package READMEs, collaborator
invite checklist, mirror lag alert, release captain fail-closed gate.

Hermetic: no network, no paid CLI, no :8777, no live git remotes. Mirror lag
and captain status are pure functions over injected tag/status maps.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import share_topology as topo  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


# ── Module surface ───────────────────────────────────────────────────────────

def test_w8_modules_importable():
    assert callable(topo.topology_policy)
    assert callable(topo.check_public_write_identity)
    assert callable(topo.assert_public_write_allowed)
    assert callable(topo.check_mirror_lag)
    assert callable(topo.mirror_lag_badge)
    assert callable(topo.evaluate_captain_checklist)
    assert callable(topo.render_contributing)
    assert callable(topo.render_package_readme)
    assert callable(topo.validate_contributing_text)
    assert callable(topo.validate_readme_text)
    assert callable(topo.collaborator_invite_checklist)
    assert callable(topo.write_topology_docs)
    assert callable(topo.captain_checklist_item_ids)
    assert topo.HUMAN_PUBLIC_WRITE_FORBIDDEN is True
    assert set(topo.CAPTAIN_CHECKLIST_ITEMS) == set(
        topo.captain_checklist_item_ids()
    )


def test_captain_checklist_items_complete():
    """Captain checklist presence: freeze / clean-scan / matrix / smoke / red-team."""
    ids = topo.captain_checklist_item_ids()
    required = {
        "freeze_tags",
        "clean_scan_green",
        "sources_complete",
        "package_matrix_green",
        "stranger_install_smoke",
        "sanitizer_red_team_green",
    }
    assert set(ids) == required
    for item_id in required:
        assert item_id in topo.CAPTAIN_ITEM_LABELS


def test_shipped_assets_exist_and_pass_section_checks():
    paths = topo.shipped_pack_paths(REPO)
    assert paths["contributing"].is_file()
    assert paths["readme_a"].is_file()
    assert paths["readme_b"].is_file()
    assert paths["codeowners"].is_file()
    assert paths["invite_checklist"].is_file()
    assert paths["topology_ops"].is_file()
    assert paths["captain_doc"].is_file()
    assert paths["feedback_intake_docs"].is_file()

    contrib = paths["contributing"].read_text(encoding="utf-8")
    assert topo.validate_contributing_text(contrib) == []
    for key in ("readme_a", "readme_b"):
        text = paths[key].read_text(encoding="utf-8")
        assert topo.validate_readme_text(text) == [], key

    captain_doc = paths["captain_doc"].read_text(encoding="utf-8")
    for item_id in topo.CAPTAIN_CHECKLIST_ITEMS:
        assert item_id in captain_doc


def test_topology_policy_one_way_bot_only():
    policy = topo.topology_policy()
    assert policy["private_source_of_truth"] == "*-dev"
    assert policy["public_mirror"]["bot_only_write"] is True
    assert policy["public_mirror"]["human_hand_edit_forbidden"] is True
    assert policy["public_mirror"]["direction"] == "private-to-public-one-way"
    assert policy["consumers"]["pin_to"] == "release_artifacts"
    assert policy["consumers"]["not_pin_to"] == "floating_main"
    assert policy["feedback"]["is_code_contribution"] is False
    assert "share-feedback-intake" in policy["feedback"]["docs"]
    assert topo.is_private_sot_name("anchor-skills-dev")
    assert not topo.is_private_sot_name("anchor-skills-public")


def test_public_write_bot_ok_human_forbidden():
    assert topo.check_public_write_identity("release-bot") == []
    assert topo.check_public_write_identity("mirror-bot") == []
    assert topo.check_public_write_identity("github-actions[bot]") == []
    codes = topo.check_public_write_identity("alice")
    assert "human_public_write_forbidden" in codes
    with pytest.raises(topo.TopologyError) as ei:
        topo.assert_public_write_allowed("alice")
    assert ei.value.reason == "human_public_write_forbidden"
    assert topo.check_public_write_identity("") == ["unknown_public_writer"]


def test_branch_protection_and_invite_checklist():
    assert topo.validate_branch_protection(topo.BRANCH_PROTECTION_POLICY) == []
    weak = dict(topo.BRANCH_PROTECTION_POLICY)
    weak["allow_force_push"] = True
    weak["allow_direct_push_to_main"] = True
    problems = topo.validate_branch_protection(weak)
    assert "force_push_allowed" in problems
    assert "direct_main_push_allowed" in problems

    rows = topo.collaborator_invite_checklist()
    ids = {r["id"] for r in rows}
    assert "branch_protection_no_force_push" in ids
    assert "codeowners" in ids
    assert "pr_only" in ids
    assert "uninvited_pr_misroute" in ids
    guide = topo.uninvited_pr_misroute_guidance().lower()
    assert "not" in guide and "code contribution" in guide
    assert "invite" in guide


# ── GWT #1: private tag without public publish → alert; pin last public ──────

def test_given_private_tag_without_public_when_mirror_lag_then_alert_and_pin():
    """GWT #1: private release tag missing public publish → alert; pin last public."""
    report = topo.check_mirror_lag(
        private_tags=["v1.0.0", "v1.1.0"],
        public_publishes=["v1.0.0"],
    )
    assert report["ok"] is False
    assert report["alert"] is True
    assert "v1.1.0" in report["missing_public"]
    assert "private_tag_missing_public_publish" in report["reason_codes"]
    assert report["last_public_release"] == "v1.0.0"
    assert report["consumers_pin_to"] == "v1.0.0"
    assert report["consumers_must_not_pin_to"] == "floating_main"
    assert report["failed_checklist_item"]
    badge = topo.mirror_lag_badge(report)
    assert "LAG" in badge or "lag" in badge.lower()
    assert "v1.0.0" in badge
    assert "floating main" in badge.lower() or "not floating" in badge.lower()

    # Alias kwargs work the same.
    report2 = topo.check_mirror_lag(
        private_release_tags=["v2.0.0"],
        public_release_tags=[],
    )
    assert report2["alert"] is True
    assert report2["last_public_release"] is None
    assert "floating-main" in report2["consumers_pin_to"] or (
        report2["consumers_must_not_pin_to"] == "floating_main"
    )


def test_mirror_in_sync_when_public_matches_private():
    report = topo.check_mirror_lag(
        private_tags=["v1.0.0"],
        public_publishes=["v1.0.0"],
    )
    assert report["ok"] is True
    assert report["alert"] is False
    assert report["missing_public"] == []
    assert report["reason_codes"] == []
    assert "in-sync" in topo.mirror_lag_badge(report)


# ── GWT #2: README + CONTRIBUTING required three-path sections ───────────────

def test_given_generated_docs_when_required_sections_then_three_paths_present():
    """GWT #2: consumer read-only, collaborator PR, separate feedback; not code push."""
    contrib = topo.render_contributing()
    problems = topo.validate_contributing_text(contrib)
    assert problems == [], problems
    low = contrib.lower()
    assert "download & use" in low
    assert "collaborat" in low
    assert "sanitized" in low
    assert "not" in low and "code push" in low
    assert "pull request" in low
    assert "release artifact" in low
    assert "backlog" in low
    assert "feedback intake" in low
    # Must not claim feedback is how you push code to main.
    assert "not" in low and "code push to main" in low

    for pid in ("A", "B"):
        readme = topo.render_package_readme(pid)
        rprob = topo.validate_readme_text(readme)
        assert rprob == [], (pid, rprob)
        rlow = readme.lower()
        assert "download & use" in rlow
        assert "invited to collaborate" in rlow
        assert "friction" in rlow
        assert "contributing" in rlow
        assert "release artifact" in rlow
        assert "not floating main" in rlow
        assert "privacy" in rlow
        assert "sanitized" in rlow


def test_write_topology_docs_to_temp_passes_validators(tmp_path):
    report = topo.write_topology_docs(tmp_path)
    assert report["ok"] is True
    contrib = (tmp_path / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert topo.validate_contributing_text(contrib) == []
    for pid in ("A", "B"):
        text = (
            tmp_path / "share_topology_pack" / ("README-package-%s.md" % pid)
        ).read_text(encoding="utf-8")
        assert topo.validate_readme_text(text) == []
    assert (tmp_path / "docs" / "share-topology.md").is_file()
    assert (tmp_path / "docs" / "share-release-captain-checklist.md").is_file()
    assert (tmp_path / "share_topology_pack" / "CODEOWNERS").is_file()


def test_incomplete_contributing_fails_section_check():
    bad = "# Hello\n\nNo dual-audience content here.\n"
    problems = topo.validate_contributing_text(bad)
    assert problems
    assert any(p.startswith("missing_section:") for p in problems)


# ── GWT #3: captain checklist fail-closed on any red item ────────────────────

def test_given_red_captain_item_when_evaluated_then_not_ship_allowed():
    """GWT #3: freeze/clean-scan/sanitizer red → checklist fails closed."""
    # All green → ship allowed.
    green = {k: True for k in topo.CAPTAIN_CHECKLIST_ITEMS}
    ok_report = topo.evaluate_captain_checklist(green)
    assert ok_report["ok"] is True
    assert ok_report["ship_allowed"] is True
    assert ok_report["failed_items"] == []
    assert topo.may_mark_ship_allowed(ok_report) is True

    # Each critical red alone blocks ship.
    for red_key in (
        "freeze_tags",
        "clean_scan_green",
        "sanitizer_red_team_green",
        "sources_complete",
        "package_matrix_green",
        "stranger_install_smoke",
    ):
        status = dict(green)
        status[red_key] = False
        report = topo.evaluate_captain_checklist(status)
        assert report["ok"] is False, red_key
        assert report["ship_allowed"] is False, red_key
        assert red_key in report["failed_items"]
        assert "ship_not_allowed" in report["reason_codes"]
        assert "captain_item_red" in report["reason_codes"]
        assert topo.may_mark_ship_allowed(report) is False

    # Missing items (incomplete) also fail closed.
    incomplete = topo.evaluate_captain_checklist({})
    assert incomplete["ship_allowed"] is False
    assert set(incomplete["failed_items"]) == set(topo.CAPTAIN_CHECKLIST_ITEMS)
    assert "captain_incomplete" in incomplete["reason_codes"]


def test_captain_accepts_green_string_status():
    status = {k: "green" for k in topo.CAPTAIN_CHECKLIST_ITEMS}
    status["freeze_tags"] = {"ok": True}
    status["clean_scan_green"] = "pass"
    report = topo.evaluate_captain_checklist(status)
    assert report["ship_allowed"] is True


def test_build_captain_status_from_placeholder_sources():
    # Shipped freeze still PLACEHOLDER → freeze_tags not green from docs alone.
    sources = {
        "pins": [{"repo": "anchor", "tag": "PLACEHOLDER", "commit": "PLACEHOLDER"}],
        "skills_pin": {"tag": "PLACEHOLDER", "commit": "PLACEHOLDER"},
    }
    status = topo.build_captain_status_from_gates(
        sources_doc=sources,
        clean_scan_ok=True,
        package_matrix_ok=True,
        stranger_smoke_ok=True,
        sanitizer_red_team_ok=True,
    )
    report = topo.evaluate_captain_checklist(status)
    assert report["ship_allowed"] is False
    assert "freeze_tags" in report["failed_items"] or (
        "sources_complete" in report["failed_items"]
    )


def test_release_cadence_checklist_present():
    rows = topo.release_cadence_checklist()
    ids = {r["id"] for r in rows}
    assert "mirror_lag_check" in ids
    assert "pin_release_artifacts" in ids
    assert "captain_signoff" in ids
    assert "one_way_mirror" in ids
