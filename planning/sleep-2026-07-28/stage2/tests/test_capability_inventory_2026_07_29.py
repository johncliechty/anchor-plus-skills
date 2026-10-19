"""W3 — Capability Inventory harness (PRESENT / STUB / ABSENT + transcripts).

Locks the frozen-plan rules:
- STUB is never auto-downgraded to ABSENT
- every verdict needs transcript + source hash (else verdict without evidence)
- age > 14 days or hash mismatch → STALE / fail-closed
- PRESENT from replay does not authorize shipping a live control
- re-probe against unchanged source hash is idempotent
"""
from __future__ import annotations

import copy
from datetime import date, timedelta
from pathlib import Path

import pytest

from tools import capability_inventory as ci


@pytest.fixture()
def root(tmp_path, monkeypatch):
    """Hermetic containment root with a minimal inventory tree."""
    # Prefer real stage2 root for bootstrap paths; tests that mutate use tmp.
    return ci.containment_root()


def test_bootstrap_inventory_covers_all_required_controls_and_gates_go():
    inv, path = ci.bootstrap_phase1()
    assert path.is_file()
    assert set(inv.rows) == set(ci.REQUIRED_CONTROLS)
    for cid, row in inv.rows.items():
        assert row.transcript_path, cid
        assert row.source_hash, cid
        assert row.probe_date, cid
        assert Path(ci.containment_root() / row.transcript_path).is_file(), cid
    assert inv.missing_required() == []
    assert inv.gate() == ci.GO


def test_stub_cannot_be_auto_downgraded_to_absent():
    with pytest.raises(ci.IllegalReclassification) as ei:
        ci.refuse_stub_to_absent(ci.Verdict.STUB, ci.Verdict.ABSENT)
    assert "STUB" in str(ei.value)
    assert "ABSENT" in str(ei.value)
    # same-direction / upgrade is fine
    ci.refuse_stub_to_absent(ci.Verdict.STUB, ci.Verdict.STUB)
    ci.refuse_stub_to_absent(ci.Verdict.ABSENT, ci.Verdict.PRESENT)


def test_verdict_without_evidence_is_refused():
    with pytest.raises(ci.VerdictWithoutEvidence) as ei:
        ci.make_row(
            "open",
            ci.Verdict.PRESENT,
            transcript_path="",
            source_paths=("x.py",),
            source_hash="abc",
            probe_date="2026-07-29",
        )
    assert ci.VERDICT_WITHOUT_EVIDENCE in str(ei.value).lower() or "evidence" in str(ei.value).lower()


def test_canned_diagnose_classifies_as_stub():
    obs = ci.ProbeObservation(
        control_id="diagnose",
        handler_bound=True,
        returns_canned_seed=True,
        notes="seed",
        output_excerpt="canned seed output",
    )
    assert ci.classify_observation(obs) == ci.Verdict.STUB


def test_stale_by_age_and_hash_fail_closed():
    row = ci.make_row(
        "open",
        ci.Verdict.PRESENT,
        transcript_path="artifacts/transcripts/open.json",
        source_paths=("artifacts/inventory-sources/open.probe",),
        source_hash="deadbeef" * 8,
        probe_date=(date.today() - timedelta(days=15)).isoformat(),
        evidence_mode=ci.EVIDENCE_LIVE,
    )
    assert ci.is_stale_by_age(row) is True
    # hash mismatch against different content
    assert ci.is_stale_by_hash(
        row,
        content_overrides={row.source_paths[0]: b"not-the-same"},
    ) is True
    # live authorization denied when stale
    assert ci.may_authorize_live_control(row) is False


def test_replay_present_does_not_authorize_live_shipping():
    # Replay-only PRESENT must never authorize shipping a live control
    # (documentation path is allowed by policy; live path is hard-refused).
    body = b"replay-source-body-for-run"
    h = ci.sha256_bytes(body)
    row = ci.make_row(
        "run",
        ci.Verdict.PRESENT,
        transcript_path="artifacts/transcripts/run.json",
        source_paths=("artifacts/inventory-sources/run.probe",),
        source_hash=h,
        probe_date=date.today().isoformat(),
        evidence_mode=ci.EVIDENCE_REPLAY,
    )
    overrides = {row.source_paths[0]: body}
    assert ci.may_authorize_live_control(
        row, content_overrides=overrides) is False
    with pytest.raises(Exception) as ei:
        ci.authorize_live_control_or_raise(row, content_overrides=overrides)
    msg = str(ei.value).lower()
    assert "replay" in msg or "live" in msg or "documentation" in msg or "shipping" in msg


def test_reprobe_idempotent_on_unchanged_source_hash():
    inv1, _ = ci.bootstrap_phase1()
    inv2, _ = ci.bootstrap_phase1()
    for cid in ci.REQUIRED_CONTROLS:
        r1, r2 = inv1.rows[cid], inv2.rows[cid]
        assert r1.verdict == r2.verdict
        assert r1.source_hash == r2.source_hash
        assert r1.transcript_path == r2.transcript_path


def test_shipped_inventory_markdown_loads():
    inv = ci.load_inventory()
    assert len(inv.rows) >= len(ci.REQUIRED_CONTROLS)
    assert inv.gate() == ci.GO
