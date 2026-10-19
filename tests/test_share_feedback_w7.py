"""Shareable Anchor + Skills — Wave 7 gate.

Frozen plan (``planning/share-anchor-skills-2026-07/IMPLEMENTATION-PLAN.md``
§Wave 7): feedback transport intake partition, edge validation, intake-scoped
credentials, no auto-merge, R14 no cross-skill blob rollup, dogfood harness.

Hermetic: temp intake roots only; no network, no paid CLI, no :8777.
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import share_feedback as fb  # noqa: E402
import share_feedback_intake as intake  # noqa: E402
import share_skill_journal as sjournal  # noqa: E402
import share_skill_seal as seal  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs" / "share-feedback-intake.md"


# ── Module surface ───────────────────────────────────────────────────────────

def test_w7_modules_importable():
    assert callable(intake.deliver_to_intake)
    assert callable(intake.validate_intake_edge)
    assert callable(intake.validate_recipient_config)
    assert callable(intake.transport_drain)
    assert callable(intake.pull_review_stub)
    assert callable(intake.cross_skill_blob_rollup)
    assert callable(intake.run_dogfood_harness)
    assert callable(intake.measure_export_yield)
    assert intake.auto_merge_allowed() is False
    assert DOCS.is_file()
    text = DOCS.read_text(encoding="utf-8").lower()
    assert "not" in text and "code contribution" in text


def test_hard_line_policy_constant():
    assert "NOT a code contribution" in intake.FEEDBACK_IS_NOT_CODE_CONTRIBUTION
    assert "auto-merge" in intake.FEEDBACK_IS_NOT_CODE_CONTRIBUTION.lower() or (
        "auto-merges" in intake.FEEDBACK_IS_NOT_CODE_CONTRIBUTION.lower()
    )


# ── Helpers ──────────────────────────────────────────────────────────────────

def _seed_sealed_skills(tmp_path):
    skills = tmp_path / "skills"
    skills.mkdir()
    for name in ("crucible", "foreman"):
        d = skills / name
        d.mkdir()
        (d / "SKILL.md").write_text("# %s\n" % name, encoding="utf-8")
    seal.write_seal(skills)
    return skills


def _clean_export(skill_id, install_key, **overrides):
    base = {
        "schema": fb.FEEDBACK_SCHEMA,
        "schema_version": fb.FEEDBACK_SCHEMA_VERSION,
        "export_id": "ex-" + uuid.uuid4().hex[:12],
        "skill_id": skill_id,
        "skill_version": "1.2.0",
        "install_key": install_key,
        "outcome": "friction",
        "structural_failure_codes": ["timeout"],
        "duration_band": "5_30m",
        "complexity_band": "medium",
        "os_class": "windows",
        "model_family_seats": ["claude"],
        "workaround_codes": ["retry"],
        "workaround_tokens": ["seat_retry"],
    }
    base.update(overrides)
    clean = fb.sanitize_for_export(base)
    assert clean is not None, "fixture must be sanitizer-clean"
    return clean


# ── GWT #1: per-skill partitions + shared install key ────────────────────────

def test_given_two_skills_when_transport_then_separate_partitions_same_key(
    tmp_path,
):
    """GWT #1: Crucible + Foreman land in separate skill_id partitions; same key."""
    home = tmp_path / "home"
    home.mkdir()
    skills = _seed_sealed_skills(tmp_path)
    fb.set_feedback_opt_in(home, True)
    key = fb.load_install_key(home)
    assert key is not None

    intake_root = tmp_path / "feedback-intake"
    cfg = intake.default_transport_config(intake_root=intake_root)

    for skill_id in ("crucible", "foreman"):
        rec = sjournal.build_record(
            skill_id=skill_id,
            skill_version="1.2.0",
            outcome="friction",
            structural_failure_codes=["timeout"],
            duration_band="5_30m",
            complexity_band="medium",
            os_class="windows",
            model_family_seats=["claude"],
            workaround_codes=["retry"],
        )
        assert fb.try_export_journal_record(
            home, rec, skills_root=skills
        )["enqueued"] is True

    result = intake.transport_drain(
        home,
        intake_root,
        credentials_config=cfg,
        skills_root=skills,
    )
    assert result["drain"]["transmitted"] == 2

    crucible_dir = intake.skill_partition_dir(intake_root, "crucible")
    foreman_dir = intake.skill_partition_dir(intake_root, "foreman")
    assert crucible_dir.is_dir()
    assert foreman_dir.is_dir()
    assert crucible_dir != foreman_dir
    assert list(crucible_dir.glob("*.json")) or list(crucible_dir.glob("*.ndjson"))
    assert list(foreman_dir.glob("*.json")) or list(foreman_dir.glob("*.ndjson"))

    c_recs = intake.list_partition_records(intake_root, "crucible")
    f_recs = intake.list_partition_records(intake_root, "foreman")
    assert len(c_recs) == 1
    assert len(f_recs) == 1
    assert c_recs[0]["skill_id"] == "crucible"
    assert f_recs[0]["skill_id"] == "foreman"
    assert c_recs[0]["install_key"] == key
    assert f_recs[0]["install_key"] == key
    assert c_recs[0]["install_key"] == f_recs[0]["install_key"]


def test_deliver_direct_partition_paths(tmp_path):
    key = str(uuid.uuid4())
    root = tmp_path / "inbox"
    cfg = intake.default_transport_config(intake_root=root)
    a = _clean_export("crucible", key)
    b = _clean_export("foreman", key)
    da = intake.deliver_to_intake(root, a, credentials_config=cfg)
    db = intake.deliver_to_intake(root, b, credentials_config=cfg)
    assert da["accepted"] and db["accepted"]
    assert "crucible" in da["partition"]
    assert "foreman" in db["partition"]
    assert Path(da["path"]).parent != Path(db["path"]).parent


# ── GWT #2: edge rejects unknown fields / free-text overflow ─────────────────

def test_given_unknown_fields_when_edge_then_reject_not_stored(tmp_path):
    """GWT #2a: unknown fields → rejected and not stored."""
    key = str(uuid.uuid4())
    root = tmp_path / "inbox"
    cfg = intake.default_transport_config(intake_root=root)
    dirty = _clean_export("crucible", key)
    dirty["notes"] = "should never land"
    dirty["extra_field"] = "unknown"

    problems = intake.validate_intake_edge(dirty)
    assert any(p.startswith("unknown-fields:") for p in problems)
    assert "notes" in ",".join(problems) or any(
        "notes" in p for p in problems
    )

    out = intake.deliver_to_intake(root, dirty, credentials_config=cfg)
    assert out["accepted"] is False
    assert out["reason"] == "edge_reject"
    part = root / intake.PARTITION_SUBDIR / "crucible"
    assert not part.exists() or list(part.iterdir()) == []


def test_given_free_text_overflow_when_edge_then_reject_not_stored(tmp_path):
    """GWT #2b: free-text overflow → rejected and not stored."""
    key = str(uuid.uuid4())
    root = tmp_path / "inbox"
    cfg = intake.default_transport_config(intake_root=root)
    # Bypass sanitizer path: craft overflow on an allowlisted string field
    # that validate_export_record accepts structurally but edge caps reject.
    overflow = _clean_export("crucible", key)
    # source_record_id max 64 at edge; build a 80-char opaque-looking id
    overflow["source_record_id"] = "a" * 80
    # Structural pattern may already fail; edge must also flag overflow.
    problems = intake.validate_intake_edge(overflow)
    assert problems  # non-empty reject
    assert any(
        "overflow" in p or "invalid" in p or "sanitizer" in p
        for p in problems
    )

    out = intake.deliver_to_intake(root, overflow, credentials_config=cfg)
    assert out["accepted"] is False
    assert not list((root / intake.PARTITION_SUBDIR).rglob("*")) if (
        root / intake.PARTITION_SUBDIR
    ).exists() else True

    # Explicit free-text overflow on workaround_tokens length
    tok_overflow = _clean_export("foreman", key)
    # mutate after clean — edge must catch token longer than cap
    tok_overflow["workaround_tokens"] = ["x" * 40]
    problems2 = intake.validate_intake_edge(tok_overflow)
    assert any("overflow" in p or "token" in p for p in problems2)
    out2 = intake.deliver_to_intake(root, tok_overflow, credentials_config=cfg)
    assert out2["accepted"] is False


# ── GWT #3: intake-scoped credentials only ───────────────────────────────────

def test_given_recipient_config_when_inspected_then_only_intake_scoped():
    """GWT #3: only intake-scoped tokens; product-main write absent."""
    cfg = intake.default_transport_config(intake_root="feedback-intake")
    problems = intake.validate_recipient_config(cfg)
    assert problems == []
    insp = intake.inspect_credentials(cfg)
    assert insp["intake_only"] is True
    assert insp["product_main_credentials_absent"] is True
    assert insp["auto_merge"] is False
    for scope in insp["scopes"]:
        assert scope in intake.INTAKE_CREDENTIAL_SCOPES
        assert scope not in intake.FORBIDDEN_CREDENTIAL_SCOPES


def test_product_main_credentials_fail_closed():
    cfg = intake.default_transport_config()
    cfg["product_main_write"] = True
    assert "product_main_write-forbidden" in intake.validate_recipient_config(cfg)

    cfg2 = intake.default_transport_config()
    cfg2["credentials"] = [
        {
            "id": "evil",
            "scope": "product_main_write",
            "token_env": "GH_MAIN_TOKEN",
        }
    ]
    problems = intake.validate_recipient_config(cfg2)
    assert any("forbidden-credential-scope" in p for p in problems)
    insp = intake.inspect_credentials(cfg2)
    assert insp["product_main_credentials_absent"] is False
    assert insp["intake_only"] is False

    cfg3 = intake.default_transport_config()
    cfg3["credentials"][0]["github_pat_main"] = "ghp_should_not_be_here"
    problems3 = intake.validate_recipient_config(cfg3)
    assert any("product-credential-key-present" in p for p in problems3)


def test_deliver_refuses_invalid_credentials(tmp_path):
    key = str(uuid.uuid4())
    root = tmp_path / "inbox"
    bad = intake.default_transport_config(intake_root=root)
    bad["auto_merge_to_skill_sources"] = True
    clean = _clean_export("crucible", key)
    out = intake.deliver_to_intake(root, clean, credentials_config=bad)
    assert out["accepted"] is False
    assert "credentials-invalid" in (out["reason"] or "")


# ── No auto-merge + R14 ──────────────────────────────────────────────────────

def test_no_auto_merge_path(tmp_path):
    root = tmp_path / "inbox"
    intake.ensure_intake_layout(root)
    key = str(uuid.uuid4())
    intake.deliver_to_intake(
        root,
        _clean_export("crucible", key),
        credentials_config=intake.default_transport_config(intake_root=root),
    )
    review = intake.pull_review_stub(root)
    assert review["auto_merge"] is False
    assert review["auto_merge_allowed"] is False
    assert review["action"] == "pull_review_only"
    assert "crucible" in review["skill_ids"]
    assert intake.auto_merge_allowed() is False
    refused = intake.attempt_auto_merge_to_skill_sources(root, "/skills")
    assert refused["merged"] is False
    assert refused["reason"] == "auto_merge_forbidden"


def test_r14_no_cross_skill_blob_rollup(tmp_path):
    root = tmp_path / "inbox"
    cfg = intake.default_transport_config(intake_root=root)
    key = str(uuid.uuid4())
    intake.deliver_to_intake(root, _clean_export("crucible", key), credentials_config=cfg)
    intake.deliver_to_intake(root, _clean_export("foreman", key), credentials_config=cfg)

    blob = intake.cross_skill_blob_rollup(root)
    assert blob["ok"] is False
    assert blob["refused"] is True
    assert blob["reason"] == "cross_skill_blob_rollup_forbidden"
    assert blob["r14"] is True
    # Metrics-only ok; must not return a merged list of raw records
    assert "records" not in blob
    assert blob["metrics_only"]["crucible"]["count"] == 1
    assert blob["metrics_only"]["foreman"]["count"] == 1

    # Per-skill list still works
    assert len(intake.list_partition_records(root, "crucible")) == 1
    assert len(intake.list_partition_records(root, "foreman")) == 1


# ── Dogfood harness ──────────────────────────────────────────────────────────

def test_dogfood_harness_measures_yield_no_marketing(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    skills = _seed_sealed_skills(tmp_path)
    fb.set_feedback_opt_in(home, True)
    intake_root = tmp_path / "dogfood-intake"
    cfg = intake.default_transport_config(intake_root=intake_root)

    records = [
        sjournal.build_record(
            skill_id="crucible",
            skill_version="1.0.0",
            outcome="friction",
            structural_failure_codes=["timeout"],
            duration_band="1_5m",
            complexity_band="small",
            os_class="windows",
            model_family_seats=["claude"],
            workaround_codes=["none"],
        ),
        sjournal.build_record(
            skill_id="foreman",
            skill_version="1.0.0",
            outcome="failed",
            structural_failure_codes=["gate_red"],
            duration_band="5_30m",
            complexity_band="medium",
            os_class="windows",
            model_family_seats=["claude"],
            workaround_codes=["retry"],
        ),
    ]
    report = intake.run_dogfood_harness(
        home,
        intake_root,
        records,
        skills_root=skills,
        credentials_config=cfg,
    )
    assert report["ok"] is True
    y = report["yield"]
    assert y["public_marketing_allowed"] is False
    assert y["attempted"] == 2
    assert y["accepted"] >= 1
    assert y["zero_yield"] is False
    assert report["auto_merge_allowed"] is False
    assert "crucible" in report["partitions"] or "foreman" in report["partitions"]


def test_dogfood_zero_yield_kill_channel_note():
    y = intake.measure_export_yield(attempted=5, accepted=0)
    assert y["zero_yield"] is True
    assert y["kill_channel_recommended"] is True
    assert y["public_marketing_allowed"] is False
    assert y["kill_channel_note"] is not None
    assert "kill" in y["kill_channel_note"].lower()
    assert intake.KILL_CHANNEL_IF_ZERO_YIELD_NOTE in y["kill_channel_note"] or (
        y["kill_channel_note"] == intake.KILL_CHANNEL_IF_ZERO_YIELD_NOTE
    )


def test_intake_layout_readme_has_hard_line(tmp_path):
    root = tmp_path / "inbox"
    intake.ensure_intake_layout(root)
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert "NOT a code contribution" in readme or "not a code contribution" in readme.lower()
    layout = json.loads((root / "INTAKE-LAYOUT.json").read_text(encoding="utf-8"))
    assert layout["auto_merge_to_skill_sources"] is False


def test_config_roundtrip(tmp_path):
    path = tmp_path / "transport.json"
    root = tmp_path / "intake"
    intake.write_recipient_transport_config(path, intake_root=root)
    loaded = intake.load_recipient_transport_config(path)
    assert loaded["schema"] == intake.TRANSPORT_SCHEMA
    assert intake.validate_recipient_config(loaded) == []
