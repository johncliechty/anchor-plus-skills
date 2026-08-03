"""Shareable Anchor + Skills — Wave 1 contracts gate.

Frozen plan (``planning/share-anchor-skills-2026-07/IMPLEMENTATION-PLAN.md``
§Wave 1): package matrix, capability matrix, readiness/SOURCES/freeze
schemas + validators; brownfield inventory + SUPERSEDES/REUSE markers;
Anchor-only hard-fail; B requires skills_pin; Skills-only roster excludes
or degrades Anchor-required surfaces without crashing.

Hermetic: pure data + local JSON/schema files. No network, no paid CLI,
no :8777, no live git publish.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import share_capability_matrix as cap
import share_contracts as sc
import share_package_matrix as pm

REPO = Path(__file__).resolve().parent.parent


# ── Schema files exist + enums load ──────────────────────────────────────────

def test_all_schema_files_present_and_parse():
    for name, path in sc.SCHEMA_FILES.items():
        assert path.is_file(), name
        doc = sc.load_schema(name)
        assert "$schema" in doc or "properties" in doc or "const" in doc.get(
            "properties", {}
        ).get("schema", {}) or doc.get("properties")


def test_shipped_data_files_present():
    for name, path in sc.DATA_FILES.items():
        assert path.is_file(), name
        assert isinstance(sc.load_data(name), dict)


# ── Shipped contracts validate clean ─────────────────────────────────────────

def test_shipped_package_matrix_validates():
    assert sc.validate_package_matrix_doc(sc.load_data("package_matrix")) == []


def test_shipped_capability_matrix_validates():
    assert sc.validate_capability_matrix_doc(
        sc.load_data("capability_matrix")
    ) == []


def test_shipped_sources_pin_placeholders_only():
    problems = sc.validate_sources_pin_doc(
        sc.load_data("sources_pin"), require_placeholders=True
    )
    assert problems == []
    doc = sc.load_data("sources_pin")
    assert doc["ship_allowed"] is False


def test_shipped_freeze_manifest_placeholders_only():
    problems = sc.validate_freeze_manifest_doc(
        sc.load_data("freeze_manifest"), require_placeholders=True
    )
    assert problems == []
    doc = sc.load_data("freeze_manifest")
    assert doc["ship_allowed"] is False
    for repo, tag in doc["freeze_tags"].items():
        assert sc.is_placeholder(tag), repo


def test_validate_shipped_contracts_all_green():
    report = sc.validate_shipped_contracts(require_placeholders=True)
    for name, problems in report.items():
        assert problems == [], "%s: %s" % (name, problems)


# ── Capability enum coverage ─────────────────────────────────────────────────

def test_capability_enum_coverage_complete():
    cov = cap.enum_coverage()
    assert cov["complete"] is True
    assert set(cov["present"]) == set(sc.CAPABILITY_ENUM)


def test_capability_enum_rejects_unknown():
    doc = copy.deepcopy(sc.load_data("capability_matrix"))
    doc["skills"][0]["capability"] = "works-maybe"
    problems = sc.validate_capability_matrix_doc(doc)
    assert any("capability-out-of-enum" in p for p in problems)


def test_anchor_required_cannot_include_on_package_a():
    doc = copy.deepcopy(sc.load_data("capability_matrix"))
    # force a bad policy on zombie-hunter
    for s in doc["skills"]:
        if s["skill_id"] == "zombie-hunter":
            s["package_a_policy"] = "include"
    problems = sc.validate_capability_matrix_doc(doc)
    assert any("anchor-required-cannot-include-on-A" in p for p in problems)


# ── GWT: Anchor-only artifact hard-fail (no package emitted) ─────────────────

def test_anchor_only_name_detected():
    assert pm.is_anchor_only_name("anchor-only") is True
    assert pm.is_anchor_only_name("anchor") is True
    assert pm.is_anchor_only_name("Anchor_Only") is True
    # dual package names are not Anchor-only
    assert pm.is_anchor_only_name("anchor-skills") is False
    assert pm.is_anchor_only_name("skills-only") is False


def test_given_anchor_only_publish_when_validator_then_fail_closed_no_emit():
    """GWT #1: Anchor-only artifact → fail closed; no package emitted."""
    request = {
        "artifact_name": "anchor-only",
        "skills_subtree_present": True,
    }
    codes = pm.validate_publish_request(request)
    assert "anchor_only_forbidden" in codes

    with pytest.raises(pm.PackageMatrixError) as ei:
        pm.assert_emit_allowed(request)
    assert "anchor_only_forbidden" in ei.value.reason_codes
    # Contract: caller must not emit after exception — decision has no emit True
    assert not hasattr(ei.value, "emit") or getattr(ei.value, "emit", None) is not True


def test_assert_emit_allowed_skills_only_a():
    decision = pm.assert_emit_allowed({
        "artifact_name": "skills-only",
        "package_id": "A",
        "skills_subtree_present": True,
    })
    assert decision["emit"] is True
    assert decision["package_id"] == "A"
    assert decision["reason_codes"] == []


def test_assert_emit_allowed_package_b_with_pin():
    decision = pm.assert_emit_allowed({
        "artifact_name": "anchor-skills",
        "package_id": "B",
        "skills_subtree_present": True,
        "skills_pin": {"tag": "PLACEHOLDER", "commit": "PLACEHOLDER"},
    })
    assert decision["emit"] is True
    assert decision["package_id"] == "B"


# ── GWT: package B without skills_pin → skills_pin_required ──────────────────

def test_given_b_without_skills_pin_when_check_then_skills_pin_required():
    """GWT #2: package B declared without skills_pin → reason code."""
    request = {
        "artifact_name": "anchor-skills",
        "package_id": "B",
        "skills_subtree_present": True,
        # skills_pin omitted
    }
    codes = pm.validate_publish_request(request)
    assert "skills_pin_required" in codes
    assert "anchor_only_forbidden" not in codes

    with pytest.raises(pm.PackageMatrixError) as ei:
        pm.assert_emit_allowed(request)
    assert "skills_pin_required" in ei.value.reason_codes


def test_b_with_empty_skills_pin_fails():
    codes = pm.validate_publish_request({
        "artifact_name": "anchor-skills",
        "package_id": "B",
        "skills_subtree_present": True,
        "skills_pin": {"tag": "", "commit": ""},
    })
    assert "skills_pin_required" in codes


def test_freeze_manifest_missing_skills_pin_reason_code():
    """Freeze-manifest / package_matrix coupling: B needs skills_pin fields."""
    freeze = copy.deepcopy(sc.load_data("freeze_manifest"))
    del freeze["skills_pin"]
    # schema validation flags structure
    problems = sc.validate_freeze_manifest_doc(
        freeze, require_placeholders=True
    )
    assert any("skills_pin" in p for p in problems)
    # package matrix coupling helper
    codes = pm.check_freeze_skills_pin(freeze, package_id="B")
    assert codes == ["skills_pin_required"]


def test_freeze_manifest_empty_skills_pin_reason_code():
    freeze = copy.deepcopy(sc.load_data("freeze_manifest"))
    freeze["skills_pin"] = {"tag": "", "commit": ""}
    codes = pm.check_freeze_skills_pin(freeze, package_id="B")
    assert "skills_pin_required" in codes


# ── GWT: Zombie Hunter + Anchor Doctor excluded/degraded on Skills-only ──────

def test_zombie_hunter_and_doctor_in_matrix_as_anchor_required():
    by_id = cap.skills_by_id()
    assert "zombie-hunter" in by_id
    assert "anchor-doctor" in by_id
    assert by_id["zombie-hunter"]["capability"] == "Anchor-required"
    assert by_id["anchor-doctor"]["capability"] == "Anchor-required"
    assert by_id["zombie-hunter"]["package_a_policy"] == "exclude"
    assert by_id["anchor-doctor"]["package_a_policy"] == "exclude"
    assert by_id["zombie-hunter"]["degraded_label"].strip()
    assert by_id["anchor-doctor"]["degraded_label"].strip()


def test_given_skills_only_roster_when_resolved_then_anchor_required_excluded():
    """GWT #3: Skills-only excludes Anchor-required; no crash; labels present."""
    roster = cap.resolve_skills_only_roster()
    assert roster["validation_problems"] == []

    surface_ids = {e["skill_id"] for e in roster["surface"]}
    excluded_ids = {e["skill_id"] for e in roster["excluded"]}

    assert "zombie-hunter" in excluded_ids
    assert "anchor-doctor" in excluded_ids
    assert "zombie-hunter" not in surface_ids
    assert "anchor-doctor" not in surface_ids

    # excluded carry plain-English labels (docs/UI) without being runnable
    for skill_id in ("zombie-hunter", "anchor-doctor"):
        entry = next(e for e in roster["excluded"] if e["skill_id"] == skill_id)
        assert entry["degraded_label"]
        assert cap.skills_only_safe(skill_id) is False

    # package B still includes them
    b_ids = {s["skill_id"] for s in cap.resolve_package_b_roster()}
    assert "zombie-hunter" in b_ids
    assert "anchor-doctor" in b_ids

    # tidy-idy is degraded stub — on surface with label, not crash
    stub_ids = {e["skill_id"] for e in roster["stubbed"]}
    assert "tidy-idy" in stub_ids
    tidy_surface = next(
        e for e in roster["surface"] if e["skill_id"] == "tidy-idy"
    )
    assert tidy_surface["status"] == "degraded-stub"
    assert tidy_surface["degraded_label"]


def test_skills_only_roster_does_not_crash_on_missing_anchor():
    # Pure resolution: no Anchor process, no import of anchor_gui
    roster = cap.resolve_skills_only_roster()
    assert isinstance(roster["surface"], list)
    assert all("skill_id" in e for e in roster["surface"])
    # Trio core skills included
    surface_ids = {e["skill_id"] for e in roster["surface"]}
    assert "crucible" in surface_ids
    assert "foreman" in surface_ids
    assert "researchprime" in surface_ids


# ── Readiness schema (contract freeze; compute later) ────────────────────────

def test_readiness_ready_requires_governance_and_seat_or_accepted():
    bad = {
        "schema": "share-readiness/v1",
        "schema_version": 1,
        "status": "ready",
        "reason_codes": [],
        "package_id": "A",
        "governance_installed": False,
        "coding_seat_ok": False,
        "user_accepted_degraded": False,
    }
    problems = sc.validate_readiness_doc(bad)
    assert any("ready-without" in p for p in problems)

    good = dict(bad)
    good["governance_installed"] = True
    good["coding_seat_ok"] = True
    assert sc.validate_readiness_doc(good) == []

    degraded_ok = {
        "schema": "share-readiness/v1",
        "schema_version": 1,
        "status": "degraded",
        "reason_codes": ["no_coding_seat"],
        "package_id": "A",
        "governance_installed": True,
        "coding_seat_ok": False,
        "user_accepted_degraded": False,
        "feedback_opt_in": False,
    }
    assert sc.validate_readiness_doc(degraded_ok) == []


def test_readiness_unknown_reason_code_fails():
    doc = {
        "schema": "share-readiness/v1",
        "schema_version": 1,
        "status": "degraded",
        "reason_codes": ["not_a_real_code"],
        "package_id": "A",
    }
    problems = sc.validate_readiness_doc(doc)
    assert any("reason_code-out-of-enum" in p for p in problems)


# ── Brownfield inventory + NS gap map + reuse markers ────────────────────────

def test_brownfield_inventory_validates_and_maps_all_ns():
    doc = sc.load_data("brownfield_inventory")
    assert sc.validate_brownfield_inventory(doc) == []
    assert sc.every_ns_criterion_mapped(doc) is True
    for n in range(1, 10):
        assert str(n) in doc["ns_gap_map"]


def test_all_reuse_markers_point_at_real_paths():
    problems = sc.all_reuse_markers_present(repo_root=REPO)
    assert problems == [], problems


def test_supersedes_markers_present():
    assert "share-distro-4-skill-roster" in sc.SUPERSEDES
    assert "ship-anchor-tailscale-v1" in sc.SUPERSEDES
    assert "ship-anchor-tidy-idy-exclusion" in sc.SUPERSEDES


def test_supersedes_reuse_md_exists():
    path = REPO / "planning" / "share-anchor-skills-2026-07" / "SUPERSEDES-REUSE.md"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "reuse:distro" in text
    assert "forbid" in text.lower() or "Forbid" in text


def test_brownfield_inventory_md_exists():
    path = REPO / "planning" / "share-anchor-skills-2026-07" / "BROWNFIELD-INVENTORY.md"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "distro.py" in text
    assert "vendor_skills.py" in text


# ── Placeholder freeze rejection of real-looking tags in W1 mode ─────────────

def test_sources_pin_rejects_non_placeholder_when_required():
    doc = copy.deepcopy(sc.load_data("sources_pin"))
    doc["pins"][0]["tag"] = "v1.2.3"
    problems = sc.validate_sources_pin_doc(doc, require_placeholders=True)
    assert any("not-placeholder" in p for p in problems)


def test_freeze_rejects_ship_allowed_true_with_placeholders():
    doc = copy.deepcopy(sc.load_data("freeze_manifest"))
    doc["ship_allowed"] = True
    problems = sc.validate_freeze_manifest_doc(
        doc, require_placeholders=True
    )
    assert any("ship_allowed-true-while-placeholders" in p for p in problems)


# ── Package matrix structural invariants ─────────────────────────────────────

def test_package_matrix_a_and_b_coupling_invariants():
    doc = sc.load_data("package_matrix")
    by_id = {p["id"]: p for p in doc["packages"]}
    assert by_id["A"]["includes_anchor"] is False
    assert by_id["A"]["includes_skills"] is True
    assert by_id["B"]["includes_anchor"] is True
    assert by_id["B"]["includes_skills"] is True
    assert by_id["B"]["requires_skills_pin"] is True
    assert by_id["B"]["requires_skills_subtree"] is True


def test_b_missing_skills_subtree_fails():
    codes = pm.validate_publish_request({
        "artifact_name": "anchor-skills",
        "package_id": "B",
        "skills_subtree_present": False,
        "skills_pin": {"tag": "PLACEHOLDER", "commit": "PLACEHOLDER"},
    })
    assert "skills_subtree_required" in codes
