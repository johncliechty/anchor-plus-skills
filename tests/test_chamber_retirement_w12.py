# W12 — tile retirement on SIGNED rail+STATUS parity (C11).
#
# AUTH-ON: not-a-surface
#
# The plan's law, verbatim targets:
#   * "every row maps to a live rail/STATUS equivalent or an explicit
#     John-signed accepted loss, and no tile is removed before rail+STATUS
#     parity is SIGNED"
#   * "tile removal code gated on signed rail+STATUS parity (C11)"
#
# This suite also gives W9's parity-map CI gate
# (chamber_status_overlay.tile_affordance_problems) its first named test —
# the file its law cited (test_chamber_close_ci_w9.py) is a ghost the
# audit report records; exercising the gate here is the W12 reconciliation.
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import chamber_retirement as ret  # noqa: E402
import chamber_status_overlay as cso  # noqa: E402

ANCHOR = Path(__file__).resolve().parents[1]


def _live_inventory():
    return cso.load_tile_affordance_inventory()


# ── the committed state: parity resolved, UNSIGNED, tiles stand ─────────────

def test_w9_parity_gate_is_green_on_the_committed_inventory():
    # The living-registry law: stale source markers / dead equivalent
    # claims / undecided rows fail by name. Green on the committed map.
    assert cso.tile_affordance_problems() == []


def test_every_row_is_resolved_equivalent_or_carries_decision_material():
    st = ret.parity_state()
    assert st["problems"] == []
    assert st["row_count"] >= 8, "the W9 map covers the tile affordances"
    assert st["undecided"] == []
    # Every pending row carries its decision material for John's signing.
    by_id = {r["id"]: r for r in st["rows"]}
    for rid in st["pending_john"]:
        assert by_id[rid]["decision_material"] is True, rid


def test_retirement_is_refused_by_name_while_unsigned():
    verdict = ret.retirement_allowed()
    assert verdict["allowed"] is False
    # Three rows await John's ruling -> the row gate fires first; were they
    # ruled, the signature gate (FINDING_UNSIGNED) would still refuse.
    assert verdict["finding"] in (ret.FINDING_UNRESOLVED_ROWS,
                                  ret.FINDING_UNSIGNED)
    st = ret.retirement_state()
    assert st["tiles_stand"] is True


def test_no_tile_code_was_deleted_before_the_signature():
    # The no-premature-deletion law, mechanically: every row's SOURCE marker
    # still present in the tile code while the gate stands unsigned.
    inv = _live_inventory()
    sig = ret.signature_state(inv)
    if not sig["signed"]:
        for row in inv["rows"]:
            src = ANCHOR / row["source_file"]
            assert src.is_file(), row["id"]
            assert row["source_marker"] in src.read_text(
                encoding="utf-8", errors="replace"), (
                "tile affordance %r lost its source marker while parity is "
                "UNSIGNED — tile code was deleted before the signature "
                "(C11 violation)" % row["id"])


def test_gate_record_is_committed_unsigned_with_all_three_decisions():
    text = ret.load_gate_record()
    assert text.splitlines()[0].endswith("UNSIGNED")
    for row_id in ("full-transcript-log-link", "rearm-watch",
                   "dismiss-finished-tile"):
        assert row_id in text, "the signable record presents %s" % row_id
    # The rearm-watch audit outcome is recorded honestly: the W9 re-arm
    # claim was verified NOT wired.
    assert "rearm_watch" in text
    # No absolute host paths ride the committed record or the inventory.
    inv_raw = json.dumps(_live_inventory())
    for shipped in (text, inv_raw):
        assert "C:\\Users" not in shipped and "/Users/" not in shipped


def test_signature_state_fails_closed_on_disagreement(tmp_path):
    inv = copy.deepcopy(_live_inventory())
    inv["signed_by_john"] = True  # flag flipped, record still unsigned
    sig = ret.signature_state(inv)
    assert sig["signed"] is False
    assert "disagrees" in sig["reason"]


# ── the mechanism John's signing unlocks (proven on fixtures, not live) ─────

def _signed_fixture(tmp_path):
    inv = copy.deepcopy(_live_inventory())
    inv["signed_by_john"] = True
    for row in inv["rows"]:
        if row["parity"]["kind"] in ("proposed-equivalent", "proposed-loss"):
            row["parity"]["john_ruling"] = ret.RULING_ACCEPTED_LOSS
    record = tmp_path / "TILE-RETIREMENT-GATE.md"
    record.write_text(
        "# W12 tile-retirement parity gate — SIGNED\n\n"
        "**Signed by:** John (fixture signing for the mechanism test)\n",
        encoding="utf-8")
    return inv, record


def test_signed_fixture_with_all_rows_ruled_unlocks_retirement(tmp_path):
    inv, record = _signed_fixture(tmp_path)
    verdict = ret.retirement_allowed(inv, gate_record_path=record)
    assert verdict["allowed"] is True
    ruled = [r for r in verdict["rows"] if r["state"] == "ruled"]
    assert len(ruled) == 3
    assert all(r["ruling"] == ret.RULING_ACCEPTED_LOSS for r in ruled)


def test_signed_fixture_with_an_unruled_row_still_refuses(tmp_path):
    inv, record = _signed_fixture(tmp_path)
    # One proposal loses its ruling -> the row gate refuses DESPITE the
    # signature (every row resolved is a conjunct, not a vibe).
    for row in inv["rows"]:
        if row["id"] == "rearm-watch":
            row["parity"].pop("john_ruling", None)
    verdict = ret.retirement_allowed(inv, gate_record_path=record)
    assert verdict["allowed"] is False
    assert verdict["finding"] == ret.FINDING_UNRESOLVED_ROWS
    assert verdict["pending_john"] == ["rearm-watch"]


def test_missing_gate_record_fails_closed(tmp_path):
    inv, _ = _signed_fixture(tmp_path)
    verdict = ret.retirement_allowed(
        inv, gate_record_path=tmp_path / "absent.md")
    assert verdict["allowed"] is False
    assert verdict["finding"] == ret.FINDING_GATE_RECORD_MISSING


# ── W9's checker still refuses drift, by name (the living-registry law) ─────

def test_stale_source_marker_and_dead_equivalent_fail_by_name(tmp_path):
    inv = copy.deepcopy(_live_inventory())
    inv["rows"][0]["source_marker"] = "marker-that-never-existed"
    problems = cso.tile_affordance_problems(inv)
    assert any("stale source row" in p for p in problems), problems

    inv2 = copy.deepcopy(_live_inventory())
    for row in inv2["rows"]:
        if row["parity"]["kind"] == "equivalent":
            row["parity"]["target_marker"] = "vanished-target-marker"
            break
    problems2 = cso.tile_affordance_problems(inv2)
    assert any("dead equivalent claim" in p for p in problems2), problems2

    inv3 = copy.deepcopy(_live_inventory())
    inv3["rows"][0]["parity"] = {"kind": "shrug"}
    problems3 = cso.tile_affordance_problems(inv3)
    assert any("undecided row cannot land" in p for p in problems3), problems3
    # And the retirement gate folds those problems into its refusal.
    verdict = ret.retirement_allowed(inv3)
    assert verdict["allowed"] is False
    assert verdict["finding"] == ret.FINDING_PARITY_PROBLEMS
