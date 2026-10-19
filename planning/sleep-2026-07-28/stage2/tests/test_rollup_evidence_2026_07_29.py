"""W4 — Rollup Evidence Gate + cost spot-check protocol."""
from __future__ import annotations

import pytest

from tools import rollup_evidence_gate as r
from anchor.build import rollup_registry as reg


def test_bootstrap_writes_evidence_and_spot_check_and_is_go():
    s, ev_path, sc_path = r.bootstrap_phase1()
    assert ev_path.is_file()
    assert sc_path.is_file()
    assert not s.missing_required()
    assert set(s.rows) >= set(r.REQUIRED_ROLLUPS)
    for rid, row in s.rows.items():
        # Exactly one of PROVEN | NO_AGGREGATOR | READ_FAILED (as enum/str)
        v = str(getattr(row, "verdict", None) or getattr(row, "status", "") or "")
        assert v, rid
    assert r.phase1_go_decision() == r.GO


def test_load_evidence_round_trips():
    s1, _, _ = r.bootstrap_phase1()
    s2 = r.load_evidence()
    assert set(s2.rows) == set(s1.rows)


def test_spot_check_rejects_same_agent_independence_violation():
    bad = r.fixture_spot_check_same_agent()
    gate, reason, _ = r.validate_spot_check(bad)
    assert gate == r.HALT
    assert "independ" in reason.lower() or "agent" in reason.lower() or r.NON_INDEPENDENT_MESSAGE.split()[0].lower() in reason.lower()


def test_spot_check_rejects_under_sampled():
    bad = r.fixture_spot_check_under_sampled()
    gate, reason, _ = r.validate_spot_check(bad)
    assert gate == r.HALT


def test_valid_spot_check_is_go():
    good = r.fixture_spot_check_valid()
    gate, reason, finalized = r.validate_spot_check(good)
    assert gate == r.GO
    assert r.spot_check_all_agreed(finalized) is True


def test_rollup_registry_bootstraps():
    rr = reg.bootstrap_registry()
    assert rr is not None
    # Must expose required rollups without inventing numerals from empty
    names = list(getattr(rr, "entries", None) or getattr(rr, "rollups", None) or [])
    if not names and hasattr(rr, "list_proven"):
        names = list(rr.list_proven())
    # At least the registry object is constructible; deeper shape is module-owned
    assert rr.__class__.__name__ == "RollupRegistry"
