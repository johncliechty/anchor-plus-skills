"""Shareable Anchor + Skills — Wave 4 gate.

Frozen plan (``planning/share-anchor-skills-2026-07/IMPLEMENTATION-PLAN.md``
§Wave 4): governance pack generator + host-personal denylist + golden;
Foundry journal layout/append hooks; skills immutability seal; machine-local
home config; readiness stamp compute (ready requires governance + seat OR
user-accepted degraded; refuse false green).

Hermetic: temp dirs only; no network, no paid CLI, no :8777, no live onboard.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import share_contracts as sc  # noqa: E402
import share_governance as gov  # noqa: E402
import share_home_config as home  # noqa: E402
import share_readiness as ready  # noqa: E402
import share_skill_journal as sjournal  # noqa: E402
import share_skill_seal as seal  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "share_governance"
GOLDEN = FIXTURE / "golden"
SOURCE = FIXTURE / "source_AGENTS.md"


# ── Modules importable ───────────────────────────────────────────────────────

def test_w4_modules_importable():
    assert callable(gov.build_pack_files)
    assert callable(gov.write_governance_pack)
    assert callable(gov.apply_host_personal_denylist)
    assert callable(sjournal.append_structured_run)
    assert callable(sjournal.validate_record)
    assert callable(seal.build_seal_manifest)
    assert callable(seal.verify_seal)
    assert callable(seal.feedback_export_allowed)
    assert callable(ready.compute_readiness)
    assert callable(ready.write_readiness_stamp)
    assert callable(home.build_home_config_doc)
    assert callable(home.write_home_config)


# ── GWT #1: author paths → denylist → golden match + no author paths ────────

def test_given_author_paths_when_generate_then_matches_golden_and_no_author_paths():
    """GWT #1: canonical sources with author host paths scrub clean + match golden spine."""
    raw = SOURCE.read_text(encoding="utf-8")
    # Fixture must actually contain author-shaped paths to scrub.
    assert "Users" in raw and "john" in raw
    assert "@" in raw

    # Dirty sources scrub to no author paths.
    dirty_pack = gov.build_pack_files([raw])
    for name, text in dirty_pack.items():
        problems = gov.assert_no_author_paths(text)
        assert problems == [], "%s: %s" % (name, problems)
    assert "Users\\john" not in dirty_pack["AGENTS.md"]
    assert "Users/john" not in dirty_pack["AGENTS.md"]
    assert "john@example.com" not in dirty_pack["AGENTS.md"]
    assert gov.PATH_PLACEHOLDER in dirty_pack["AGENTS.md"]
    assert gov.EMAIL_PLACEHOLDER in dirty_pack["AGENTS.md"]

    # Spine-only pack matches committed golden (CI golden fixture).
    spine = gov.build_pack_files(None)
    problems = gov.pack_matches_golden(spine, GOLDEN)
    assert problems == [], problems
    for text in spine.values():
        assert gov.assert_no_author_paths(text) == []

    # Dirty pack still carries required operating-rule markers + pointers equal spine.
    for marker in gov.REQUIRED_SECTION_MARKERS:
        assert marker in dirty_pack["AGENTS.md"]
    assert dirty_pack["CLAUDE.md"] == spine["CLAUDE.md"]
    assert dirty_pack["GEMINI.md"] == spine["GEMINI.md"]


def test_stranger_machine_pack_has_no_author_paths():
    """Stranger-machine assertion: written pack tree embeds no author paths."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        written = gov.write_governance_pack(
            td,
            source_paths=[SOURCE],
        )
        for path in written.values():
            text = path.read_text(encoding="utf-8")
            assert gov.assert_no_author_paths(text) == []
            assert "C:\\Users\\john" not in text
            assert "/Users/john" not in text


# ── GWT #2: structured run append → journal file with mandatory fields ──────

def test_given_structured_run_when_append_then_journal_has_mandatory_fields(tmp_path):
    """GWT #2: append hook writes skill_id, skill_version, outcome, structural codes."""
    skill = tmp_path / "skills" / "crucible"
    skill.mkdir(parents=True)
    path = sjournal.append_structured_run(
        skill,
        skill_id="crucible",
        skill_version="1.2.0",
        outcome="friction",
        structural_failure_codes=["timeout", "seat_failover"],
        notes="smoke",
    )
    assert path.is_file()
    assert path.parent.name == "runs"
    assert path.parent.parent.name == "journal"

    records = sjournal.list_records(skill)
    assert len(records) == 1
    rec = records[0]
    assert sjournal.validate_record(rec) == []
    assert rec["skill_id"] == "crucible"
    assert rec["skill_version"] == "1.2.0"
    assert rec["outcome"] == "friction"
    assert rec["structural_failure_codes"] == ["timeout", "seat_failover"]
    assert rec["schema_version"] == sjournal.SCHEMA_VERSION
    assert sjournal.journal_contract_proven(skill) is True


def test_journal_refuses_missing_mandatory_fields():
    with pytest.raises(sjournal.SkillJournalError) as ei:
        sjournal.build_record(
            skill_id="",
            skill_version="1.0.0",
            outcome="worked",
        )
    assert any("skill_id" in p for p in ei.value.problems)

    with pytest.raises(sjournal.SkillJournalError):
        sjournal.build_record(
            skill_id="x",
            skill_version="1.0.0",
            outcome="not-an-outcome",
        )


# ── GWT #3: readiness without seat → not green ready ────────────────────────

def test_given_governance_no_seat_when_readiness_then_not_green_ready():
    """GWT #3: governance installed, no coding seat, no accepted degraded → not-ready."""
    doc = ready.compute_readiness(
        package_id="A",
        governance_installed=True,
        coding_seat_ok=False,
        user_accepted_degraded=False,
        journal_proven=False,
    )
    # Canonical zero-seat matrix: not-ready (distinct from degraded-with-seat).
    assert doc["status"] == "not-ready"
    assert "no_coding_seat" in doc["reason_codes"]
    assert "journal_contract_unproven" in doc["reason_codes"]
    assert ready.is_green_ready(doc) is False
    assert sc.validate_readiness_doc(doc) == []


def test_readiness_ready_with_governance_and_seat_may_warn_journal():
    doc = ready.compute_readiness(
        package_id="A",
        governance_installed=True,
        coding_seat_ok=True,
        journal_proven=False,
    )
    assert doc["status"] == "ready"
    assert "journal_contract_unproven" in doc["reason_codes"]
    assert ready.is_green_ready(doc) is True


def test_readiness_refuses_false_green():
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
    problems = ready.refuse_false_green(bad)
    assert any("ready-without" in p for p in problems)

    with pytest.raises(ready.ReadinessError):
        ready.compute_readiness(
            package_id="A",
            governance_installed=False,
            coding_seat_ok=False,
            force_status="ready",
        )


def test_readiness_user_accepted_degraded_is_ready():
    doc = ready.compute_readiness(
        package_id="B",
        governance_installed=True,
        coding_seat_ok=False,
        user_accepted_degraded=True,
    )
    assert doc["status"] == "ready"
    assert "user_accepted_degraded" in doc["reason_codes"]
    assert ready.is_green_ready(doc) is True


def test_write_and_load_readiness_stamp(tmp_path):
    doc = ready.compute_readiness(
        package_id="A",
        governance_installed=True,
        coding_seat_ok=True,
        journal_proven=True,
    )
    # journal_proven True → no journal_contract_unproven
    assert "journal_contract_unproven" not in doc["reason_codes"]
    path = ready.write_readiness_stamp(tmp_path, doc)
    assert path.name == "readiness.json"
    loaded = ready.load_readiness_stamp(tmp_path)
    assert loaded["status"] == "ready"


# ── Immutability seal ───────────────────────────────────────────────────────

def test_immutability_seal_detects_local_edits_and_blocks_feedback(tmp_path):
    skills = tmp_path / "skills"
    skill = skills / "foreman"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# foreman\n", encoding="utf-8")

    manifest = seal.build_seal_manifest(skills)
    seal_path = seal.write_seal(skills, manifest)
    assert seal_path.is_file()
    assert seal.verify_seal(skills, seal_path=seal_path)["ok"] is True
    assert seal.feedback_export_allowed(skills, seal_path=seal_path) is True

    # Local edit → forked.
    (skill / "SKILL.md").write_text("# foreman FORKED\n", encoding="utf-8")
    result = seal.verify_seal(skills, seal_path=seal_path)
    assert result["ok"] is False
    assert result["status"] == "forked"
    assert "skill_tree_forked" in result["reason_codes"]
    assert seal.feedback_export_allowed(skills, seal_path=seal_path) is False

    # Readiness picks up forked code.
    doc = ready.compute_readiness(
        package_id="A",
        governance_installed=True,
        coding_seat_ok=True,
        skill_tree_forked=True,
    )
    assert doc["status"] == "degraded"
    assert "skill_tree_forked" in doc["reason_codes"]


# ── Machine-local home config ────────────────────────────────────────────────

def test_home_config_relative_layout_has_no_baked_author_paths(tmp_path):
    layout = home.ensure_home_layout(tmp_path)
    assert Path(layout["home"]) == tmp_path.resolve()
    for key in ("projects", "skills", "anchor", "governance", "skill_journals"):
        assert key in layout["relative"]
        assert not Path(layout["relative"][key]).is_absolute()

    doc = home.build_home_config_doc(tmp_path)
    assert home.validate_home_config_doc(doc) == []
    path = home.write_home_config(tmp_path)
    text = path.read_text(encoding="utf-8")
    # Shipped relative layout must never bake author host paths.
    assert "C:\\Users\\john" not in text
    assert "/Users/john" not in text
    for v in doc["relative_layout"].values():
        assert not Path(v).is_absolute()
        assert "Users" not in v
        assert "john" not in v


def test_governance_installed_detection(tmp_path):
    assert gov.is_governance_installed(tmp_path) is False
    gov.write_governance_pack(tmp_path)
    assert gov.is_governance_installed(tmp_path) is True
    assert gov.governance_pack_version_of(tmp_path) == gov.GOVERNANCE_PACK_VERSION


# ── Schema registration smoke ───────────────────────────────────────────────

def test_skill_journal_schema_file_present():
    path = REPO / "share_schemas" / "skill_journal.schema.json"
    assert path.is_file()
    doc = sc.load_json(path)
    assert doc.get("properties", {}).get("skill_id") is not None
