# W5 stub gate — cold-open rebuild path (brownfield derivation + reconcile).
#
# AUTH-ON: not-a-surface
#
# Names + exercises the W5 modules chamber_brownfield.py and
# chamber_reconcile.py: the honest degraded-rail routes (missing vs
# unreadable roadmap are DISTINCT reasons), the real derived route from a
# roadmap_projection fixture, deterministic re-derivation, the persisted
# manifest, and the reconcile -> precompute_brief -> load_brief round trip.
# Pure sidecar logic — no server is ever booted here.
import json
import sys
from pathlib import Path

import pytest

ANCHOR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ANCHOR))

import chamber_brownfield as cb  # noqa: E402
import chamber_manifest as cm  # noqa: E402
import chamber_reconcile as cr  # noqa: E402

ROADMAP = {
    "project_id": "proj-x",
    "roadmap_projection": [
        {"id": "s1", "name": "Draft memo", "status": "done",
         "commissioned_as": "gandalf"},
        {"id": "s2", "name": "Verify memo", "status": None},
    ],
    "roadmap_events": [
        {"kind": "scaffold_proposal", "proposal_id": "prop-9"},
    ],
}


def _write_roadmap(folder, doc):
    (Path(folder) / "roadmap.json").write_text(
        json.dumps(doc) if isinstance(doc, dict) else doc, encoding="utf-8")


def test_missing_roadmap_is_degraded_rail_with_named_reason(tmp_path):
    out = cb.derive_brownfield_manifest(tmp_path)
    assert out["route"] == cb.ROUTE_DEGRADED
    assert out["reason"] == cb.REASON_ROADMAP_MISSING
    assert out["amendment_ref"] == cb.DEGRADED_AMENDMENT_REF


def test_unreadable_roadmap_is_a_distinct_degraded_reason(tmp_path):
    _write_roadmap(tmp_path, "{nope")
    out = cb.derive_brownfield_manifest(tmp_path)
    assert out["route"] == cb.ROUTE_DEGRADED
    # missing vs unreadable never collapse (the failure-table law)
    assert out["reason"] == cb.REASON_ROADMAP_UNREADABLE


def test_derived_route_yields_valid_deterministic_manifest(tmp_path):
    _write_roadmap(tmp_path, ROADMAP)
    out = cb.derive_brownfield_manifest(tmp_path)
    assert out["route"] == cb.ROUTE_DERIVED and out["ok"]
    manifest = out["manifest"]
    assert cm.validate_manifest(manifest) == []
    assert [s["id"] for s in manifest["steps"]] == ["s1", "s2"]
    again = cb.derive_brownfield_manifest(tmp_path)
    assert cm.compute_manifest_hash(manifest) == \
        cm.compute_manifest_hash(again["manifest"])


def test_apply_persists_the_derived_manifest(tmp_path):
    _write_roadmap(tmp_path, ROADMAP)
    out = cb.apply_brownfield_derivation(tmp_path)
    assert out["route"] == cb.ROUTE_DERIVED
    assert cm.load_manifest(tmp_path) is not None


def test_reconcile_reads_steps_and_counts_statuses(tmp_path):
    _write_roadmap(tmp_path, ROADMAP)
    rec = cr.reconcile(tmp_path)
    assert [s["id"] for s in rec["steps"]] == ["s1", "s2"]
    assert rec["step_status_counts"] == {"done": 1, "unknown": 1}


def test_precompute_brief_persists_and_loads_back(tmp_path):
    _write_roadmap(tmp_path, ROADMAP)
    brief = cr.precompute_brief(tmp_path, persist=True)
    assert brief["schema"] == cr.SCHEMA
    assert (Path(tmp_path) / cr.BRIEF_REL).exists()
    assert cr.load_brief(tmp_path) == brief


def test_empty_folder_reconcile_and_brief_are_honest_not_fabricated(tmp_path):
    rec = cr.reconcile(tmp_path)
    assert rec["steps"] == [] and rec["runs"] == []
    brief = cr.precompute_brief(tmp_path, persist=False)
    assert brief["schema"] == cr.SCHEMA
    assert cr.load_brief(tmp_path) is None
