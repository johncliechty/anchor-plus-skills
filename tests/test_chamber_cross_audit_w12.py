# W12 — the cross-criterion negative-path audit over the ASSEMBLED chamber
# (steward-chamber W12, Phase-4 Close).
#
# AUTH-ON: not-a-surface
#
# The wave's own words drive this file:
#   * "re-run every landing-wave refusal end-to-end + the interaction cases
#     no landing wave could see (run dies while a gate is held; sweep card
#     vs directive card contend for queue head; re-brief lands during a
#     sweep) each re-blocked with its named finding"
#   * "nothing is first-exercised here — a criterion first exercised here
#     would be a plan defect"
#
# HONESTY LINE (the audit's own reconciliation, chamber/W12-AUDIT-REPORT.md):
# the W11 refusals re-run by IMPORTING the landing wave's own test functions
# (the committed instruments); the W10-co-landed interaction refusals are
# exercised against the W10-landed MACHINERY because the wave's cited test
# files (test_chamber_gate_queue_w10.py etc.) are NOT in the tree — that gap
# is recorded as the named plan defect in the committed audit report, which
# this file asserts stays honest against the tree.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import chamber_audit as ca  # noqa: E402
import chamber_gates as cg  # noqa: E402
import chamber_rebrief as crb  # noqa: E402
import chamber_spine_guard as csg  # noqa: E402

ANCHOR = Path(__file__).resolve().parents[1]


def _project(tmp_path, name="proj"):
    folder = tmp_path / name
    (folder / ".anchor" / "chamber").mkdir(parents=True)
    return folder


# ═════════════════════════════════════════════════════════════════════════════
# Interaction case 1 — a run dies WHILE a gate is held
# ═════════════════════════════════════════════════════════════════════════════

def test_run_dies_while_gate_is_held_keeps_the_gate_and_holds_e2(tmp_path):
    folder = _project(tmp_path)
    held = cg.enqueue_gate(folder, cg.KIND_DIRECTIVE,
                           {"text": "Proceed with the syllabus step?"})
    assert held["ok"]
    held_id = held["gate"]["gate_id"]

    # The death lands WHILE that gate holds the head.
    out = cg.on_run_death(folder, {"session_id": "dead-7", "outcome": "died",
                                   "step_id": "s2", "skill": "foreman"})
    assert out["ok"] and out["registered"]
    # THE HELD GATE IS NEVER TOUCHED — by name, in the transition's answer.
    assert out["held_gate_kept"] == held_id
    state = cg.queue_state(folder)
    assert state["head"]["gate_id"] == held_id
    assert state["head"]["status"] == cg.STATUS_PENDING

    # E2 now holds: a re-commission cannot enqueue, with the NAMED finding.
    blocked = cg.enqueue_gate(folder, cg.KIND_RECOMMISSION,
                              {"text": "re-run the step?"},
                              session_id="dead-7")
    assert not blocked["ok"]
    assert blocked["finding"] == cg.FINDING_E2_BLOCKED
    assert blocked["error"] == cg.E2_ERROR
    # Nothing was written on refusal — the queue still holds ONE gate.
    assert cg.queue_state(folder)["queued_count"] == 1

    # The held gate remains decidable (never dropped by the death).
    assert cg.resolve_gate(folder, held_id, commit=False)["ok"]


# ═════════════════════════════════════════════════════════════════════════════
# Interaction case 2 — sweep card vs directive card contend for the head
# ═════════════════════════════════════════════════════════════════════════════

def test_sweep_and_directive_contend_sweep_takes_head_directive_requeues(
        tmp_path):
    folder = _project(tmp_path)
    d = cg.enqueue_gate(folder, cg.KIND_DIRECTIVE,
                        {"text": "Kick off week two?"})
    directive_id = d["gate"]["gate_id"]

    cg.on_run_death(folder, {"session_id": "dead-9", "outcome": "quiet",
                             "step_id": "s3", "skill": "gandalf"})
    swept = cg.run_sweep(folder, {"session_id": "dead-9", "outcome": "quiet",
                                  "step_id": "s3", "skill": "gandalf"})
    bound = cg.bind_sweep_card(folder, swept, session_id="dead-9",
                               commit=False)
    assert bound["ok"]
    # Deterministic resolution, with the NAMED finding: the sweep takes the
    # head; the directive is RE-QUEUED immediately behind — never dropped.
    assert bound["contention"]["finding"] == cg.FINDING_CONTENTION
    assert bound["contention"]["requeued_gate_id"] == directive_id
    state = cg.queue_state(folder)
    assert state["head"]["kind"] == cg.KIND_SWEEP
    assert state["queued_count"] == 2
    requeued = [g for g in state["gates"] if g["gate_id"] == directive_id]
    assert requeued and requeued[0]["requeued"] is True
    assert requeued[0]["status"] == cg.STATUS_PENDING

    # Resolving the sweep RELEASES the directive (E5 hand-over).
    rel = cg.resolve_gate(folder, state["head"]["gate_id"], commit=False)
    assert rel["ok"] and rel["released"]["gate_id"] == directive_id

    # Any double-render is the E5 named finding, never a silent second card.
    finding = cg.double_render_finding([directive_id, "gate-9999"])
    assert finding and finding["finding"] == cg.FINDING_DOUBLE_RENDER
    assert cg.double_render_finding([directive_id]) is None


# ═════════════════════════════════════════════════════════════════════════════
# Interaction case 3 — a re-brief lands DURING an active sweep
# (re-run of the W11 landing instrument, end-to-end)
# ═════════════════════════════════════════════════════════════════════════════

def test_rebrief_during_sweep_reruns_the_w11_landing_refusal(tmp_path):
    from test_chamber_rebrief_w11 import (
        test_rebrief_during_active_sweep_is_queued_with_named_finding,
        test_contention_check_fails_closed_on_unreadable_gates_store,
    )
    test_rebrief_during_active_sweep_is_queued_with_named_finding(
        tmp_path / "case3a")
    test_contention_check_fails_closed_on_unreadable_gates_store(
        tmp_path / "case3b")
    # The named finding the audit registry records is the module's own.
    assert crb.FINDING_REBRIEF_DURING_SWEEP == \
        "W11-REBRIEF-DURING-SWEEP-QUEUED"


# ═════════════════════════════════════════════════════════════════════════════
# Landing-wave refusals re-run end-to-end (the committed instruments)
# ═════════════════════════════════════════════════════════════════════════════

def test_e3_handback_block_reruns_the_w11_landing_refusal(tmp_path):
    from test_chamber_corrections_w11 import (
        test_regressed_predicate_blocks_handback_with_named_finding,
        test_guard_fails_closed_on_unreadable_store_and_open_on_zero,
        test_every_report_carries_the_demoted_remainder,
    )
    test_regressed_predicate_blocks_handback_with_named_finding(
        tmp_path / "e3a")
    test_guard_fails_closed_on_unreadable_store_and_open_on_zero(
        tmp_path / "e3b")
    test_every_report_carries_the_demoted_remainder(tmp_path / "e3c")


def test_e6_preload_diff_reruns_the_w11_landing_refusal(tmp_path):
    from test_chamber_preload_w11 import (
        test_a_missing_entry_is_a_diffable_failure_not_a_vibe,
        test_a_smuggled_unprojected_line_also_diffs,
    )
    test_a_missing_entry_is_a_diffable_failure_not_a_vibe(tmp_path / "e6a")
    test_a_smuggled_unprojected_line_also_diffs(tmp_path / "e6b")


def test_e7_rebrief_reruns_the_w11_landing_instrument(tmp_path):
    from test_chamber_rebrief_w11 import (
        test_rebrief_reaches_the_running_commission_with_receipt_no_relaunch,
        test_dead_session_is_an_honest_named_refusal_never_a_relaunch,
    )
    test_rebrief_reaches_the_running_commission_with_receipt_no_relaunch(
        tmp_path / "e7a")
    test_dead_session_is_an_honest_named_refusal_never_a_relaunch(
        tmp_path / "e7b")


def test_e9_reruns_the_w4_lint_and_w5_died_after_last_reflection(tmp_path):
    from test_chamber_manifest_schema_w4 import (
        test_e9_distinct_stages_enforced_per_step,
        test_schema_version_mismatch_is_rejected,
    )
    from test_chamber_coldopen_w5 import (
        test_died_after_last_reflection_brief_cites_record_not_reflection,
    )
    test_e9_distinct_stages_enforced_per_step()
    test_schema_version_mismatch_is_rejected()
    test_died_after_last_reflection_brief_cites_record_not_reflection(
        tmp_path / "e9")


def test_e5_head_only_serialization_refusals_at_the_w10_seam(tmp_path):
    folder = _project(tmp_path)
    a = cg.enqueue_gate(folder, cg.KIND_DECISION, {"text": "first?"})
    b = cg.enqueue_gate(folder, cg.KIND_DECISION, {"text": "second?"})
    # Only the HEAD may resolve — a deeper gate refuses BY NAME.
    refused = cg.resolve_gate(folder, b["gate"]["gate_id"], commit=False)
    assert not refused["ok"] and refused["error"] == cg.ERROR_NOT_HEAD
    # The render is HEAD-ONLY: one card, the depth as text.
    html = cg.render_gate_queue_html(cg.queue_state(folder))
    assert html.count("gq-card") == 1
    assert "first?" in html and "second?" not in html
    assert cg.resolve_gate(folder, a["gate"]["gate_id"], commit=False)["ok"]


def test_e4_template_law_refuses_a_bare_option_dialog():
    import chamber_directive as cd
    bare = "1. Option A\n2. Option B\n3. Option C"
    findings = cd.template_findings(bare)
    assert findings, "a bare option dialog must fail the E4 template law"
    composed = (
        "The syllabus step finished and its yield is on the rail.\n"
        "Nothing is running; the next concrete move is commissioning the "
        "orals rubric step, which serves the north star by closing week "
        "one.\nCommission the orals rubric step now?")
    assert cd.template_findings(composed) == []


def test_e8_zero_spine_writes_deny_scan_is_green_on_both_trees():
    # W4's roadmap_events DENY assertion, re-run at the seam: no chamber /
    # bridge source appends roadmap events outside the named sole writer.
    problems = csg.deny_problems()
    assert problems == [], problems
    sole = csg.sole_writer_present()
    assert sole.get("ok") and not sole.get("missing_symbols"), sole


# ═════════════════════════════════════════════════════════════════════════════
# The ledger's W12 re-verify column stays HONEST against the tree
# ═════════════════════════════════════════════════════════════════════════════

def test_criteria_ledger_statuses_match_the_tree():
    rows = {r["id"]: r for r in ca.criteria_rows()}
    assert set(rows) == {"E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8",
                         "E9"}
    # E1: the instrument scan and the ledger row must agree — while no leg
    # of the stack is in the tree the row is instrument-missing, and the
    # named plan defect rides it. (If the stack ever lands, the regenerated
    # report flips and the committed one fails the equality gate below.)
    import chamber_close_report as ccr
    scan = ccr.e1_instrument_scan()
    if scan["stack_complete"]:
        assert rows["E1"]["status"] == "reverified"
    else:
        assert rows["E1"]["status"] == "instrument-missing"
        assert rows["E1"]["finding"] == ca.FINDING_PLAN_DEFECT
    # W11 rows re-run their committed instruments.
    for rid in ("E3", "E6", "E7"):
        assert rows[rid]["status"] == "reverified", rows[rid]
    # W10 rows: machinery re-verified here; the ghost instruments are named.
    for rid in ("E2", "E4", "E5"):
        assert rows[rid]["status"] in ("reverified", "reverified-in-W12")
        if rows[rid]["status"] == "reverified-in-W12":
            assert "absent" in rows[rid]["note"]


def test_interaction_case_registry_findings_are_the_modules_own():
    cases = {c["case"]: c for c in ca.interaction_cases()}
    assert cases["run dies WHILE a gate is held"]["named_finding"] \
        == cg.FINDING_E2_BLOCKED
    assert cases["sweep card vs directive card contend for the queue head"][
        "named_finding"] == cg.FINDING_CONTENTION
    assert cases["re-brief lands during an active sweep"]["named_finding"] \
        == crb.FINDING_REBRIEF_DURING_SWEEP


def test_committed_audit_report_equals_a_fresh_regeneration():
    assert ca.committed_matches_regenerated() == []


def test_audit_report_names_every_ghost_instrument():
    text = ca.AUDIT_REPORT_PATH.read_text(encoding="utf-8")
    for ghost in ca.missing_cited_instruments():
        assert ghost.split("/")[-1] in text, (
            "the audit report must name the absent cited instrument %s"
            % ghost)
    # No absolute host paths ride the committed report.
    assert "C:\\Users" not in text and "/Users/" not in text
