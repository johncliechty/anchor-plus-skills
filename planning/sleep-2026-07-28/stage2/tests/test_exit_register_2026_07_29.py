"""W2 — Exit register engine + terminal status-string generator.

Exercises ``anchor.build.exit_register`` under the frozen plan contract:

* unsigned rows HALT (not written)
* E2 illegal on cost / dollars (verbatim IllegalExit message)
* E1 cannot be justified by a STUB (Doctor Diagnose GWT)
* E6 closed for the four North-Star violation classes
* no exit justified by another exit (E3←E1, free-text chains)
* conjunction: 2 per criterion or 4 across build → HALT_REBASELINE
* terminal_status cannot emit unqualified ``ten criteria met`` while any
  exit is signed or while S1 has no recorded PASS
* EXIT-REGISTER.md starts with zero signed exits

Gate: pytest -v tests/test_exit_register_2026_07_29.py
"""
from __future__ import annotations

from pathlib import Path

import pytest

from anchor.build import exit_register as er
from anchor.build.exit_register import (
    E1_STUB_MESSAGE,
    E2_DOLLARS_MESSAGE,
    E2_UNPROVEN_ACCESSOR_MESSAGE,
    E3_UPSTREAM_E1_MESSAGE,
    E6_CLOSED_MESSAGE,
    EXIT_JUSTIFIED_BY_EXIT_MESSAGE,
    HALT_REBASELINE,
    OK,
    STATUS_CANDIDATE_MET_PREFIX,
    STATUS_UNQUALIFIED,
    ExitId,
    ExitRegister,
    ExitRegisterRow,
    IllegalExit,
    UnsignedExit,
    empty_register_markdown,
    is_cost_criterion,
    load_signed_count_from_markdown,
    make_row,
    may_start_subsequent_wave,
    score_conjunction,
    terminal_status,
    unqualified_status_reachable,
    validate,
    validate_justification,
)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _signed(
    exit_id: str,
    criterion: str,
    *,
    evidence: str = "forcing evidence transcript",
    user_sees: str = "named disabled state",
    date: str = "2026-07-29",
    john: str = "John confirms this exit",
    **kwargs,
) -> ExitRegisterRow:
    return make_row(
        exit_id,
        criterion=criterion,
        forcing_evidence=evidence,
        user_sees_instead=user_sees,
        date=date,
        john_confirmation=john,
        **kwargs,
    )


# --------------------------------------------------------------------------
# ExitId + schema
# --------------------------------------------------------------------------


def test_exit_id_enum_is_exactly_e1_through_e6():
    assert [e.value for e in ExitId] == ["E1", "E2", "E3", "E4", "E5", "E6"]
    assert ExitId.E1.label == "not available on this build"
    assert ExitId.E2.label == "provisional data"
    assert ExitId.E6.label == "S1 finding routed to follow-on"


def test_make_row_parses_exit_id_string():
    row = _signed("e2", "usage-count", accessor_proven=True)
    assert row.exit_id is ExitId.E2
    assert row.criterion == "usage-count"


def test_unknown_exit_id_is_illegal():
    with pytest.raises(IllegalExit, match="unknown exit id"):
        make_row(
            "E9",
            criterion="x",
            forcing_evidence="e",
            user_sees_instead="u",
            date="2026-07-29",
            john_confirmation="John",
        )


# --------------------------------------------------------------------------
# Unsigned = HALT
# --------------------------------------------------------------------------


def test_unsigned_row_raises_and_is_not_written():
    reg = ExitRegister()
    row = _signed("E4", "instrumentation", john="")
    with pytest.raises(UnsignedExit, match="unsigned exit is a HALT"):
        validate(row)
    with pytest.raises(IllegalExit):
        reg.try_sign(row)
    assert reg.signed_count() == 0


def test_missing_date_is_unsigned():
    row = _signed("E4", "instrumentation", date="not-a-date")
    with pytest.raises(UnsignedExit):
        validate(row)


def test_missing_criterion_or_evidence_rejected():
    with pytest.raises(IllegalExit, match="criterion"):
        validate(
            make_row(
                "E4",
                criterion="",
                forcing_evidence="e",
                user_sees_instead="u",
                date="2026-07-29",
                john_confirmation="John",
            )
        )
    with pytest.raises(IllegalExit, match="forcing evidence"):
        validate(
            make_row(
                "E4",
                criterion="c",
                forcing_evidence="",
                user_sees_instead="u",
                date="2026-07-29",
                john_confirmation="John",
            )
        )


# --------------------------------------------------------------------------
# GWT: E2 against cost-labelling → IllegalExit (verbatim message)
# --------------------------------------------------------------------------


def test_e2_against_cost_labelling_raises_verbatim_illegal_exit():
    """Given E2 on cost-labelling with as_of; when validate(); then IllegalExit."""
    row = _signed(
        "E2",
        "cost-labelling",
        evidence="as_of=2026-07-29 provisional stamp present",
        user_sees="provisional $ with as_of",
        accessor_proven=True,
    )
    assert is_cost_criterion(row.criterion)
    with pytest.raises(IllegalExit) as ei:
        validate(row)
    assert ei.value.message == E2_DOLLARS_MESSAGE
    assert str(ei.value) == E2_DOLLARS_MESSAGE


def test_e2_on_cost_is_not_written_to_register():
    reg = ExitRegister()
    row = _signed(
        "E2",
        "cost-labelling criterion",
        evidence="as_of stamp",
        accessor_proven=True,
    )
    with pytest.raises(IllegalExit, match="E2 does not apply to dollars"):
        reg.try_sign(row)
    assert reg.signed_count() == 0
    assert reg.rows == []


def test_e2_is_legal_for_usage_with_proven_accessor():
    row = _signed(
        "E2",
        "usage-count",
        evidence="as_of=2026-07-29 reconciliation wave named",
        user_sees="provisional usage with as_of",
        accessor_proven=True,
    )
    assert validate(row) is row


def test_is_cost_criterion_detects_dollar_surfaces():
    assert is_cost_criterion("cost-labelling")
    assert is_cost_criterion("cost labelling")
    assert is_cost_criterion("session cost")
    assert is_cost_criterion("dollar fabrication ban")
    assert not is_cost_criterion("usage-count")
    assert not is_cost_criterion("time-rollup")


# --------------------------------------------------------------------------
# GWT: E1 justified by STUB for Doctor Diagnose
# --------------------------------------------------------------------------


def test_e1_justified_by_stub_for_doctor_diagnose_is_rejected():
    """STUB for Doctor Diagnose cannot sign E1 'not available on this build'."""
    with pytest.raises(IllegalExit) as ei:
        validate_justification(
            ExitId.E1,
            inventory_verdict="STUB",
            criterion="Doctor Diagnose",
            justification="not available on this build — inventory says STUB",
            forcing_evidence="Phase 1 inventory verdict STUB for Doctor Diagnose",
        )
    assert E1_STUB_MESSAGE in ei.value.message
    assert "build it" in ei.value.message
    assert "ABSENT" in ei.value.message


def test_e1_with_stub_row_is_not_signed():
    reg = ExitRegister()
    row = _signed(
        "E1",
        "Doctor Diagnose",
        evidence="Phase 1 inventory verdict of STUB for Doctor Diagnose",
        user_sees="not available on this build",
        inventory_verdict="STUB",
        justification="citing STUB as not available",
    )
    with pytest.raises(IllegalExit, match="STUB"):
        reg.try_sign(row)
    assert reg.signed_count() == 0


def test_e1_with_absent_and_absence_transcript_is_accepted():
    row = _signed(
        "E1",
        "Doctor Diagnose",
        evidence="independent absence transcript path artifacts/transcripts/diagnose-absent.json",
        user_sees="named cannot-diagnose state",
        inventory_verdict="ABSENT",
    )
    assert validate(row) is row


def test_e1_with_absent_but_no_transcript_rejected():
    with pytest.raises(IllegalExit, match="absence transcript"):
        validate_justification(
            ExitId.E1,
            inventory_verdict="ABSENT",
            forcing_evidence="just missing",
        )


# --------------------------------------------------------------------------
# E2 unproven accessor; E3 upstream E1; exit-justified-by-exit
# --------------------------------------------------------------------------


def test_e2_justified_by_unproven_accessor_rejected():
    with pytest.raises(IllegalExit) as ei:
        validate_justification(
            ExitId.E2,
            criterion="usage-count",
            accessor_proven=False,
            justification="provisional from unproven accessor",
        )
    assert ei.value.message == E2_UNPROVEN_ACCESSOR_MESSAGE


def test_e3_justified_by_upstream_e1_rejected():
    with pytest.raises(IllegalExit) as ei:
        validate_justification(
            ExitId.E3,
            justified_by_exit="E1",
            justification="the wave that would have fixed it took E1",
        )
    assert ei.value.message == E3_UPSTREAM_E1_MESSAGE


def test_any_exit_justified_by_another_exit_rejected():
    with pytest.raises(IllegalExit) as ei:
        validate_justification(
            ExitId.E4,
            justified_by_exit="E5",
            justification="because we already took E5",
        )
    assert ei.value.message == EXIT_JUSTIFIED_BY_EXIT_MESSAGE


def test_free_text_exit_chain_in_justification_rejected():
    with pytest.raises(IllegalExit, match="upstream E1|justified by another exit"):
        validate_justification(
            ExitId.E3,
            justification="documented because E1 already closed the parent control",
        )


# --------------------------------------------------------------------------
# E6 closed for four North-Star violation classes
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "finding_class",
    [
        "dead_control",
        "dead control",
        "silent_zero",
        "silent zero",
        "mislabelled_empty",
        "mislabelled empty",
        "raw_binary",
        "raw-binary preview",
        "raw binary",
    ],
)
def test_e6_closed_for_north_star_violation_classes(finding_class):
    with pytest.raises(IllegalExit) as ei:
        validate_justification(
            ExitId.E6,
            finding_class=finding_class,
            justification="route to follow-on",
        )
    assert ei.value.message == E6_CLOSED_MESSAGE


def test_e6_row_with_dead_control_evidence_not_written():
    reg = ExitRegister()
    row = _signed(
        "E6",
        "S1 findings",
        evidence="S1 reproduced a dead control on Diagnose",
        user_sees="follow-on ticket",
        finding_class="dead_control",
    )
    with pytest.raises(IllegalExit, match="E6 is closed"):
        reg.try_sign(row)
    assert reg.signed_count() == 0


def test_e6_legal_for_non_ns_finding():
    row = _signed(
        "E6",
        "S1 findings",
        evidence="cosmetic copy nit outside North-Star classes",
        user_sees="follow-on backlog item",
        finding_class="copy_nit",
    )
    assert validate(row) is row


# --------------------------------------------------------------------------
# GWT: conjunction — three distinct + fourth → HALT_REBASELINE
# --------------------------------------------------------------------------


def test_fourth_exit_across_build_returns_halt_rebaseline():
    """Three signed across three criteria; fourth being signed → HALT_REBASELINE."""
    existing = [
        _signed("E1", "criterion-open", inventory_verdict="ABSENT",
                evidence="absence transcript for open"),
        _signed("E2", "usage-count", accessor_proven=True),
        _signed("E4", "instrumentation-budget"),
    ]
    for r in existing:
        validate(r)

    pending = _signed("E5", "john-wait-item")
    score = score_conjunction(existing, pending=pending)
    assert score == HALT_REBASELINE


def test_try_sign_fourth_does_not_write_and_blocks_waves():
    reg = ExitRegister()
    for row in (
        _signed("E1", "criterion-open", inventory_verdict="ABSENT",
                evidence="absence transcript path artifacts/transcripts/open-absent.json"),
        _signed("E2", "usage-count", accessor_proven=True),
        _signed("E4", "instrumentation-budget"),
    ):
        reg.try_sign(row)
    assert reg.signed_count() == 3
    assert score_conjunction(reg.rows) == OK

    fourth = _signed("E5", "john-wait-item")
    with pytest.raises(IllegalExit, match="HALT_REBASELINE"):
        reg.try_sign(fourth)
    assert reg.signed_count() == 3
    assert score_conjunction(reg.rows, pending=fourth) == HALT_REBASELINE
    assert not may_start_subsequent_wave(reg.rows + [fourth])
    # No subsequent wave until John records an explicit re-baseline.
    assert not may_start_subsequent_wave(
        reg.rows + [fourth], rebaseline_recorded=False
    )
    assert may_start_subsequent_wave(
        reg.rows + [fourth], rebaseline_recorded=True
    )


def test_two_exits_on_same_criterion_halt_rebaseline():
    a = _signed("E1", "attach-honesty", inventory_verdict="ABSENT",
                evidence="absence transcript for attach")
    b = _signed("E5", "attach-honesty")
    assert score_conjunction([a], pending=b) == HALT_REBASELINE


def test_three_exits_on_distinct_criteria_are_ok():
    rows = [
        _signed("E1", "c1", inventory_verdict="ABSENT",
                evidence="absence transcript c1"),
        _signed("E2", "c2-usage", accessor_proven=True),
        _signed("E4", "c3"),
    ]
    assert score_conjunction(rows) == OK
    assert may_start_subsequent_wave(rows) is True


def test_explicit_rebaseline_clears_conjunction_halt():
    rows = [
        _signed("E1", "c1", inventory_verdict="ABSENT",
                evidence="absence transcript c1"),
        _signed("E2", "c2-usage", accessor_proven=True),
        _signed("E4", "c3"),
        _signed("E5", "c4"),
    ]
    assert score_conjunction(rows) == HALT_REBASELINE
    assert score_conjunction(rows, rebaseline_recorded=True) == OK
    reg = ExitRegister(rows=list(rows[:3]))
    reg.record_rebaseline()
    reg.try_sign(rows[3])
    assert reg.signed_count() == 4


# --------------------------------------------------------------------------
# terminal_status
# --------------------------------------------------------------------------


def test_terminal_status_with_signed_exits_is_candidate_met_not_unqualified():
    rows = [
        _signed("E2", "usage-count", accessor_proven=True),
        _signed("E4", "instrumentation"),
    ]
    status = terminal_status(rows)
    assert STATUS_CANDIDATE_MET_PREFIX in status
    assert "2 signed exits" in status
    assert "E2" in status and "E4" in status
    assert "North Star pending S1" in status
    assert STATUS_UNQUALIFIED not in status or "CANDIDATE-MET" in status
    # Unqualified exact phrase must not be the whole status.
    assert status != STATUS_UNQUALIFIED
    assert not status.startswith(STATUS_UNQUALIFIED + ";")
    assert not status.startswith(STATUS_UNQUALIFIED + " ")


def test_terminal_status_zero_exits_without_s1_pass_is_still_candidate():
    status = terminal_status([])
    assert STATUS_CANDIDATE_MET_PREFIX in status
    assert "0 signed exits" in status
    assert "North Star pending S1" in status
    assert status != STATUS_UNQUALIFIED


def test_terminal_status_unqualified_only_when_zero_exits_and_s1_pass():
    status = terminal_status([], s1_verdict="PASS")
    assert status == STATUS_UNQUALIFIED
    assert unqualified_status_reachable([], s1_verdict="PASS") is True


def test_unqualified_unreachable_while_any_exit_signed_even_with_s1_pass():
    rows = [_signed("E4", "instrumentation")]
    status = terminal_status(rows, s1_verdict="PASS")
    assert status != STATUS_UNQUALIFIED
    assert STATUS_CANDIDATE_MET_PREFIX in status
    assert unqualified_status_reachable(rows, s1_verdict="PASS") is False


def test_unqualified_unreachable_without_s1_pass_even_at_zero_exits():
    assert unqualified_status_reachable([], s1_verdict=None) is False
    assert unqualified_status_reachable([], s1_verdict="PENDING") is False
    assert terminal_status([], s1_verdict=None) != STATUS_UNQUALIFIED


def test_register_status_reflects_signed_set():
    reg = ExitRegister()
    assert "0 signed exits" in reg.status()
    reg.try_sign(_signed("E4", "instrumentation"))
    assert "1 signed exits" in reg.status()
    assert "E4" in reg.status()
    reg.s1_verdict = "PASS"
    # Still not unqualified — an exit is signed.
    assert reg.status() != STATUS_UNQUALIFIED


# --------------------------------------------------------------------------
# EXIT-REGISTER.md — zero signed exits
# --------------------------------------------------------------------------


def test_empty_register_markdown_declares_zero_signed_exits():
    text = empty_register_markdown()
    assert "Zero signed exits" in text
    assert load_signed_count_from_markdown(text) == 0


def test_artifacts_exit_register_md_starts_with_zero_signed_exits():
    path = Path(__file__).resolve().parents[1] / "artifacts" / "EXIT-REGISTER.md"
    assert path.is_file(), "artifacts/EXIT-REGISTER.md must ship with W2"
    text = path.read_text(encoding="utf-8")
    assert "Zero signed exits" in text
    assert load_signed_count_from_markdown(text) == 0
    # No absolute host paths.
    assert "C:\\Users\\" not in text
    assert "/Users/" not in text


def test_module_is_importable_under_gate_path():
    # Acceptance checklist: the new module is imported by this test file.
    assert er.ExitId.E1.value == "E1"
    assert callable(er.score_conjunction)
    assert callable(er.terminal_status)
    assert callable(er.validate_justification)
    assert callable(er.validate)
