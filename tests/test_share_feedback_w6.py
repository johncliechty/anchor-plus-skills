"""Shareable Anchor + Skills — Wave 6 gate.

Frozen plan (``planning/share-anchor-skills-2026-07/IMPLEMENTATION-PLAN.md``
§Wave 6): opt-in friction schema, fail-closed sanitizer, de-identified install
key, local offline queue; full journals stay local; forked trees block export.

Hermetic: temp homes only; no network, no paid CLI, no :8777.
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import share_contracts as sc  # noqa: E402
import share_feedback as fb  # noqa: E402
import share_onboard as sob  # noqa: E402
import share_skill_journal as sjournal  # noqa: E402
import share_skill_seal as seal  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


# ── Module surface ───────────────────────────────────────────────────────────

def test_w6_modules_importable():
    assert callable(fb.sanitize_for_export)
    assert callable(fb.try_export_journal_record)
    assert callable(fb.mint_install_key)
    assert callable(fb.ensure_install_key)
    assert callable(fb.wipe_install_key)
    assert callable(fb.rotate_install_key)
    assert callable(fb.enqueue_export)
    assert callable(fb.drain_queue)
    assert callable(fb.set_feedback_opt_in)
    assert callable(fb.build_friction_candidate)
    assert callable(fb.detect_string_leaks)
    assert callable(seal.feedback_export_allowed)
    assert (sc.SCHEMA_DIR / "skill_friction.schema.json").is_file()
    assert "skill_friction" in sc.SCHEMA_FILES


def test_skill_friction_schema_loads():
    doc = sc.load_schema("skill_friction")
    assert doc.get("properties")
    assert "install_key" in doc["properties"]
    assert doc["properties"]["outcome"]["enum"] == [
        "friction", "failed", "refused", "workaround",
    ]


# ── Install key: opaque UUID, never identity-derived ─────────────────────────

def test_mint_install_key_is_uuid_not_identity_hash():
    k1 = fb.mint_install_key()
    k2 = fb.mint_install_key()
    assert k1 != k2
    uuid.UUID(k1)
    uuid.UUID(k2)
    # Never a hash of email/username/path-shaped material
    assert "@" not in k1
    assert "\\" not in k1
    assert "/" not in k1


def test_opt_in_mints_key_opt_out_wipe(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    assert fb.load_install_key(home) is None

    r = fb.set_feedback_opt_in(home, True)
    assert r["opted_in"] is True
    assert r["install_key_present"] is True
    assert r["retro_upload"] is False
    key = fb.load_install_key(home)
    assert key is not None
    uuid.UUID(key)

    # ensure is stable
    assert fb.ensure_install_key(home) == key

    rot = fb.rotate_install_key(home)
    assert rot["continuity_break"] is True
    assert "continuity" in rot["warning"].lower() or "break" in rot["warning"].lower()
    assert rot["install_key"] != key
    assert fb.load_install_key(home) == rot["install_key"]

    out = fb.set_feedback_opt_in(
        home, False, wipe_key_on_opt_out=True, clear_queue_on_opt_out=True
    )
    assert out["opted_in"] is False
    assert out["install_key_wiped"] is True
    assert fb.load_install_key(home) is None


def test_onboard_save_consent_mints_key_on_opt_in(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    sob.save_feedback_consent(home, opted_in=True)
    doc = sob.load_feedback_consent(home)
    assert doc["opted_in"] is True
    assert doc["install_key_present"] is True
    assert fb.load_install_key(home) is not None

    sob.save_feedback_consent(home, opted_in=False, wipe_key=True)
    doc2 = sob.load_feedback_consent(home)
    assert doc2["opted_in"] is False
    assert fb.load_install_key(home) is None


# ── Sanitizer fail-closed + red-team ─────────────────────────────────────────

def _clean_candidate(**overrides):
    base = {
        "schema": fb.FEEDBACK_SCHEMA,
        "schema_version": fb.FEEDBACK_SCHEMA_VERSION,
        "export_id": "ex-testdeadbeef",
        "skill_id": "crucible",
        "skill_version": "1.2.0",
        "install_key": str(uuid.uuid4()),
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
    return base


def test_sanitize_clean_record_passes():
    clean = fb.sanitize_for_export(_clean_candidate())
    assert clean is not None
    assert clean["skill_id"] == "crucible"
    assert clean["schema"] == fb.FEEDBACK_SCHEMA
    assert "notes" not in clean
    assert set(clean.keys()).issubset(fb.EXPORT_ALLOWLIST)


def test_sanitize_strips_unknown_and_notes():
    dirty = _clean_candidate()
    dirty["notes"] = "full local journal prose about my secret project"
    dirty["prompt"] = "do the thing"
    dirty["extra_field"] = "should vanish"
    clean = fb.sanitize_for_export(dirty)
    assert clean is not None
    assert "notes" not in clean
    assert "prompt" not in clean
    assert "extra_field" not in clean


def test_redteam_email_hard_drop():
    cand = _clean_candidate(skill_id="user@example.com")  # email as skill_id
    assert fb.sanitize_for_export(cand) is None
    cand2 = _clean_candidate()
    cand2["workaround_tokens"] = ["x"]  # will replace
    # Inject email into a string that would otherwise pass token regex? skill_version
    cand3 = _clean_candidate(skill_version="1.0.0-alice@corp.com")
    # skill_version pattern may already reject; either structural or detector
    assert fb.sanitize_for_export(cand3) is None


def test_redteam_absolute_path_hard_drop():
    cand = _clean_candidate(skill_id="C")  # short ok
    # Force path into skill_id via direct mutate after build-like structure
    cand["skill_id"] = "crucible"
    # Put path in a field that accepts freer strings — source_record_id must be opaque
    # Assembled at runtime — never embed contiguous author host paths in shipped tests.
    cand["source_record_id"] = "C:\\" + "Users\\" + "jane" + "\\projects\\secret"
    assert fb.sanitize_for_export(cand) is None

    cand2 = _clean_candidate()
    cand2["skill_id"] = "crucible"
    # Detector on skill_id with path-like (invalid id pattern)
    cand2["skill_id"] = r"C:\Users\alice\skill"
    assert fb.sanitize_for_export(cand2) is None

    # POSIX home path
    assert fb.detect_string_leaks("/Users/alice/code/secret") != []
    assert fb.detect_string_leaks(r"C:\Users\bob\Anchor") != []


def test_redteam_secret_and_session_purpose_hard_drop():
    assert fb.detect_string_leaks("AKIAIOSFODNN7EXAMPLE") != []
    assert fb.detect_string_leaks(
        "Bearer aaaabbbbccccddddeeeeffffgggghhhh"
    ) != []
    assert fb.detect_string_leaks(
        "working on client project for the paper deadline"
    ) != []
    assert fb.detect_string_leaks(
        "the user prompt said to implement the feature"
    ) != []

    cand = _clean_candidate()
    # high-entropy blob smuggled via skill_version if pattern allowed — pattern
    # blocks most; inject via source_record_id that looks opaque but has email
    cand["source_record_id"] = "jr-" + "a" * 10
    assert fb.sanitize_for_export(cand) is not None
    cand2 = _clean_candidate()
    # structural_failure_codes can't hold free text; use skill_id with purpose
    # words that still match skill_id regex — "working" alone may not trip;
    # use detector path by stuffing session prose into install_key shape fail
    cand2["install_key"] = "not-a-uuid-and-has-secret-sk-" + "x" * 20
    assert fb.sanitize_for_export(cand2) is None


def test_untagged_and_worked_outcomes_dropped():
    assert fb.sanitize_for_export(_clean_candidate(skill_id="")) is None
    no_id = _clean_candidate()
    del no_id["skill_id"]
    assert fb.sanitize_for_export(no_id) is None
    assert fb.sanitize_for_export(_clean_candidate(outcome="worked")) is None


def test_unknown_schema_major_fail_closed():
    cand = _clean_candidate(schema_version="2.0.0")
    # sanitize normalizes only after acceptability check — major 2 refused
    assert fb.schema_version_acceptable("2.0.0") is False
    assert fb.sanitize_for_export(cand) is None
    assert fb.schema_version_acceptable("1.9.0") is True


# ── GWT #1: email + absolute path → drop, nothing enqueued ───────────────────

def _seed_sealed_skills(tmp_path):
    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "crucible").mkdir()
    (skills / "crucible" / "SKILL.md").write_text("# crucible\n", encoding="utf-8")
    seal.write_seal(skills)
    return skills


def test_given_opted_in_dirty_journal_when_sanitize_then_drop_no_enqueue(tmp_path):
    """GWT #1: email + absolute host path → record dropped; queue empty."""
    home = tmp_path / "home"
    home.mkdir()
    skills = _seed_sealed_skills(tmp_path)
    fb.set_feedback_opt_in(home, True)

    dirty = {
        "schema": sjournal.SCHEMA_ID,
        "schema_version": sjournal.SCHEMA_VERSION,
        "record_id": "jr-dirty001",
        "skill_id": "crucible",
        "skill_version": "1.0.0",
        "outcome": "friction",
        "structural_failure_codes": ["timeout"],
        "notes": "contact me at alice@example.com — logs at C:\\Users\\alice\\proj",
        "duration_band": "5_30m",
        "complexity_band": "medium",
        "os_class": "windows",
        "model_family_seats": ["claude"],
        "workaround_codes": ["retry"],
    }
    # notes stay local — candidate builder must not copy them
    cand = fb.build_friction_candidate(
        dirty, install_key=fb.load_install_key(home)
    )
    assert cand is not None
    assert "notes" not in cand
    assert "alice@example.com" not in json.dumps(cand)
    assert "Users" not in json.dumps(cand)

    # Explicitly plant leaks on the export candidate
    cand["source_record_id"] = r"C:\Users\alice\secret"
    assert fb.sanitize_for_export(cand) is None

    # Full path: try_export with a record whose skill_id is an email
    planted = dict(dirty)
    planted["skill_id"] = "alice@example.com"
    planted["notes"] = "also C:\\Users\\alice\\proj"
    result = fb.try_export_journal_record(
        home, planted, skills_root=skills
    )
    assert result["dropped"] is True
    assert result["enqueued"] is False
    assert result["exported"] is False
    assert list(fb.queue_dir(home).glob("*.json")) == [] if fb.queue_dir(home).exists() else True
    # Also plant path in source_record_id via clean skill_id but dirty id
    planted2 = dict(dirty)
    planted2["record_id"] = r"C:\Users\alice\jr-1"
    # record_id only copied if opaque — path-like rejected at candidate
    cand2 = fb.build_friction_candidate(
        planted2, install_key=fb.load_install_key(home)
    )
    assert cand2 is not None
    assert "source_record_id" not in cand2 or "Users" not in cand2.get(
        "source_record_id", ""
    )

    # Direct sanitizer path for email + path combo
    leak = _clean_candidate(
        skill_id="crucible",
        source_record_id="jr-ok",
    )
    # Inject both via detector-bearing skill_version invalidation
    leak["skill_version"] = "1.0.0"
    leak["source_record_id"] = "alice@example.com"
    assert fb.detect_string_leaks("alice@example.com") 
    assert "pii_email" in fb.detect_string_leaks("alice@example.com")
    assert "absolute_path" in fb.detect_string_leaks(r"C:\Users\alice\x")
    assert fb.sanitize_for_export(leak) is None  # email in source_record_id


def test_given_opted_in_clean_friction_when_export_then_enqueued(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    skills = _seed_sealed_skills(tmp_path)
    fb.set_feedback_opt_in(home, True)

    rec = sjournal.build_record(
        skill_id="crucible",
        skill_version="1.2.0",
        outcome="friction",
        structural_failure_codes=["timeout", "seat_failover"],
        notes="LOCAL ONLY — never export this path C:\\Users\\secret or me@x.com",
        duration_band="5_30m",
        complexity_band="medium",
        os_class="windows",
        model_family_seats=["claude", "gemini"],
        workaround_codes=["seat_switch"],
        workaround_tokens=["retry_once"],
    )
    # notes present locally
    assert "notes" in rec
    result = fb.try_export_journal_record(home, rec, skills_root=skills)
    assert result["exported"] is True
    assert result["enqueued"] is True
    assert result["dropped"] is False
    export = result["export_record"]
    assert export is not None
    assert "notes" not in export
    assert fb.export_payload_contains_full_journal(export) is False
    assert export["install_key"] == fb.load_install_key(home)
    assert export["skill_id"] == "crucible"
    qfiles = list(fb.queue_dir(home).glob("*.json"))
    assert len(qfiles) == 1


# ── GWT #2: decline / opt-out → no transmission; key wipe ────────────────────

def test_given_opt_out_with_queue_when_drain_then_no_transmit(tmp_path):
    """GWT #2: opt-out with non-empty queue → drain sends nothing; wipe removes key."""
    home = tmp_path / "home"
    home.mkdir()
    skills = _seed_sealed_skills(tmp_path)
    fb.set_feedback_opt_in(home, True)

    rec = sjournal.build_record(
        skill_id="foreman",
        skill_version="2.0.0",
        outcome="failed",
        structural_failure_codes=["gate_red"],
        duration_band="1_5m",
        complexity_band="small",
        os_class="windows",
        model_family_seats=["claude"],
        workaround_codes=["none"],
    )
    assert fb.try_export_journal_record(
        home, rec, skills_root=skills
    )["enqueued"] is True
    assert len(list(fb.queue_dir(home).glob("*.json"))) == 1

    # Opt out + wipe key (queue intentionally left for drain check)
    fb.set_feedback_opt_in(home, False, wipe_key_on_opt_out=True)

    sent = []
    drain = fb.drain_queue(home, transmitter=lambda r: sent.append(r) or True)
    assert drain["transmitted"] == 0
    assert drain["consent_valid"] is False
    assert drain["reason"] == "consent_off"
    assert sent == []
    assert fb.load_install_key(home) is None


def test_mid_queue_opt_out_stops_remaining_sends(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    skills = _seed_sealed_skills(tmp_path)
    fb.set_feedback_opt_in(home, True)
    key = fb.load_install_key(home)

    for i, skill in enumerate(("crucible", "foreman", "gandalf")):
        rec = sjournal.build_record(
            skill_id=skill,
            skill_version="1.0.0",
            outcome="friction",
            structural_failure_codes=["timeout"],
            duration_band="lt_1m",
            complexity_band="trivial",
            os_class="windows",
            model_family_seats=["claude"],
            workaround_codes=["retry"],
        )
        assert fb.try_export_journal_record(
            home, rec, skills_root=skills
        )["enqueued"]

    sent = []
    n = {"i": 0}

    def tx(record):
        n["i"] += 1
        sent.append(record["skill_id"])
        if n["i"] == 1:
            # Revoke consent mid-drain
            fb.set_feedback_opt_in(home, False, wipe_key_on_opt_out=False)
        return True

    drain = fb.drain_queue(home, transmitter=tx)
    assert drain["transmitted"] == 1
    assert len(sent) == 1
    assert drain["reason"] == "consent_revoked_mid_drain"
    assert len(drain["held"]) >= 1


def test_forked_tree_blocks_export(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    skills = _seed_sealed_skills(tmp_path)
    fb.set_feedback_opt_in(home, True)

    # Mutate skill tree → forked
    (skills / "crucible" / "SKILL.md").write_text("# FORKED\n", encoding="utf-8")
    assert seal.feedback_export_allowed(skills) is False

    rec = sjournal.build_record(
        skill_id="crucible",
        skill_version="1.0.0",
        outcome="friction",
        structural_failure_codes=["timeout"],
        duration_band="lt_1m",
        complexity_band="small",
        os_class="windows",
        model_family_seats=["claude"],
        workaround_codes=["none"],
    )
    result = fb.try_export_journal_record(home, rec, skills_root=skills)
    assert result["dropped"] is True
    assert "skill_tree_forked" in (result["reason"] or "")
    assert result["enqueued"] is False


def test_no_retro_upload_on_later_opt_in(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    skills = _seed_sealed_skills(tmp_path)
    skill = skills / "crucible"

    # Journal while opted out
    sjournal.append_structured_run(
        skill,
        skill_id="crucible",
        skill_version="1.0.0",
        outcome="friction",
        structural_failure_codes=["timeout"],
        notes="pre-consent local only",
        duration_band="1_5m",
        complexity_band="small",
        os_class="windows",
        model_family_seats=["claude"],
        workaround_codes=["none"],
    )
    records = sjournal.list_records(skill)
    assert len(records) == 1

    # Opt in later — does not auto-export prior journals
    r = fb.set_feedback_opt_in(home, True)
    assert r["retro_upload"] is False
    assert not fb.queue_dir(home).exists() or list(
        fb.queue_dir(home).glob("*.json")
    ) == []

    # Explicit export of old record still works only if caller asks — and
    # notes still stripped. Queue only fills on explicit try_export.
    # Policy: no automatic retro path in set_feedback_opt_in.
    assert fb.list_queue_entries(home) == []


def test_optional_encrypted_queue_roundtrip(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    skills = _seed_sealed_skills(tmp_path)
    fb.set_feedback_opt_in(home, True)
    rec = sjournal.build_record(
        skill_id="crucible",
        skill_version="1.0.0",
        outcome="friction",
        structural_failure_codes=["timeout"],
        duration_band="lt_1m",
        complexity_band="trivial",
        os_class="windows",
        model_family_seats=["claude"],
        workaround_codes=["none"],
    )
    result = fb.try_export_journal_record(
        home, rec, skills_root=skills, encrypt_at_rest=True
    )
    assert result["enqueued"] is True
    entries = fb.list_queue_entries(home)
    assert len(entries) == 1
    assert entries[0].get("encrypted") is True
    assert "payload" not in entries[0] or entries[0].get("payload") is None
    assert "ciphertext_b64" in entries[0]

    sent = []
    drain = fb.drain_queue(
        home, transmitter=lambda r: sent.append(r) or True
    )
    assert drain["transmitted"] == 1
    assert sent[0]["skill_id"] == "crucible"
    assert "notes" not in sent[0]


def test_journal_friction_fields_at_append(tmp_path):
    skill = tmp_path / "skills" / "crucible"
    skill.mkdir(parents=True)
    path = sjournal.append_structured_run(
        skill,
        skill_id="crucible",
        skill_version="1.0.0",
        outcome="workaround",
        structural_failure_codes=["seat_failover"],
        duration_band="30m_2h",
        complexity_band="large",
        os_class="linux",
        model_family_seats=["grok"],
        workaround_codes=["reduce_scope"],
        workaround_tokens=["cut_wave"],
    )
    assert path.is_file()
    rec = sjournal.list_records(skill)[0]
    assert rec["duration_band"] == "30m_2h"
    assert rec["workaround_tokens"] == ["cut_wave"]
    assert sjournal.validate_record(rec) == []
