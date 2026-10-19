"""W22 — S1 post-build validation session + terminal status emission.

Exercises:

* ``anchor.build.s1_findings`` — the four NS violation classes are
  BUILD_BLOCKING and cannot route to E6
* ``exit_register.terminal_status`` — default is CANDIDATE-MET + North Star
  pending S1; unqualified ``ten criteria met`` only at zero exits + S1 PASS
  (injected verdict for tests; live S1 ships PENDING)
* ``tools.release_guard`` — nothing from this effort publishable to v1.1.x

Gate: pytest -v tests/test_s1_and_status_2026_07_29.py

S1 is a live session with John — these tests do **not** fake that S1 already
passed. The shipping S1-VALIDATION.md verdict is PENDING; PASS paths inject
a verdict explicitly.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from anchor.build import exit_register as er
from anchor.build import s1_findings as s1
from anchor.build.exit_register import (
    STATUS_CANDIDATE_MET_PREFIX,
    STATUS_NORTH_STAR_MET,
    STATUS_UNQUALIFIED,
    ExitRegister,
    make_row,
    terminal_status,
    terminal_status_with_s1_attachment,
    emit_terminal_status,
    unqualified_status_reachable,
)
from tools import release_guard as rg


ROOT = Path(__file__).resolve().parents[1]


def _signed(exit_id: str, criterion: str, **kwargs):
    return make_row(
        exit_id,
        criterion=criterion,
        forcing_evidence=kwargs.pop("evidence", "forcing evidence transcript"),
        user_sees_instead=kwargs.pop("user_sees", "named disabled state"),
        date=kwargs.pop("date", "2026-07-29"),
        john_confirmation=kwargs.pop("john", "John confirms this exit"),
        **kwargs,
    )


# --------------------------------------------------------------------------
# S1-VALIDATION.md — live script, not pre-passed
# --------------------------------------------------------------------------


def test_s1_validation_md_ships_with_pending_not_fake_pass():
    path = ROOT / "artifacts" / "S1-VALIDATION.md"
    assert path.is_file(), "artifacts/S1-VALIDATION.md is a W22 deliverable"
    text = path.read_text(encoding="utf-8")
    assert "PENDING" in text
    assert "S1_VERDICT: PENDING" in text
    # Six North-Star controls present as live steps.
    for control in (
        "open",
        "run",
        "stop",
        "restart",
        "Doctor diagnose",
        "session attach",
    ):
        assert control.lower() in text.lower(), control
    assert "v1.2" in text
    # Must not claim S1 already passed.
    assert "S1_VERDICT: PASS" not in text
    # No absolute host paths.
    assert "C:\\Users\\" not in text
    assert "/Users/" not in text


def test_read_s1_verdict_default_is_pending():
    assert s1.read_s1_verdict(root=ROOT) == s1.S1_PENDING
    assert s1.parse_s1_verdict_from_validation_md(
        (ROOT / "artifacts" / "S1-VALIDATION.md").read_text(encoding="utf-8")
    ) == s1.S1_PENDING


# --------------------------------------------------------------------------
# Finding classification — four classes BUILD_BLOCKING, never E6
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "finding_class,token",
    [
        ("dead_control", s1.DEAD_CONTROL),
        ("dead control", s1.DEAD_CONTROL),
        ("silent_zero", s1.SILENT_ZERO),
        ("silent zero", s1.SILENT_ZERO),
        ("mislabelled_empty", s1.MISLABELLED_EMPTY),
        ("mislabelled empty", s1.MISLABELLED_EMPTY),
        ("raw_binary_preview", s1.RAW_BINARY_PREVIEW),
        ("raw-binary preview", s1.RAW_BINARY_PREVIEW),
        ("raw binary", s1.RAW_BINARY_PREVIEW),
    ],
)
def test_four_ns_classes_are_build_blocking(finding_class, token):
    result = s1.classify_finding(
        "observed on Diagnose",
        finding_class=finding_class,
        control="Doctor diagnose",
    )
    assert result.severity == s1.BUILD_BLOCKING
    assert result.finding_class == token
    assert result.may_route_to_e6 is False


def test_dead_diagnose_control_from_description_is_build_blocking():
    """GWT: S1 reproduces a dead Diagnose control → BUILD_BLOCKING, no E6."""
    result = s1.classify_finding(
        "S1 reproduced a dead control on Diagnose — click does nothing",
        control="Doctor diagnose",
        source_step="step-5-doctor-diagnose",
    )
    assert result.severity == s1.BUILD_BLOCKING
    assert result.finding_class == s1.DEAD_CONTROL
    assert result.may_route_to_e6 is False

    with pytest.raises(s1.E6RoutingForbidden, match="BUILD_BLOCKING"):
        s1.route_to_e6(result)

    # North Star not met while BUILD_BLOCKING is open.
    session = s1.build_session_result(
        verdict="PASS",  # attempted stamp
        findings=[result],
    )
    assert session.verdict == s1.S1_FAIL or session.has_build_blocking()
    assert s1.north_star_met(session=session) is False
    status = s1.emit_terminal_status_for_s1([], session=session)
    assert status != STATUS_UNQUALIFIED
    assert STATUS_CANDIDATE_MET_PREFIX in status
    assert "North Star pending S1" in status


@pytest.mark.parametrize(
    "phrase,token",
    [
        ("silent zero in the usage tile", s1.SILENT_ZERO),
        ("mislabelled empty where unknown belongs", s1.MISLABELLED_EMPTY),
        ("raw-binary preview dumped as text", s1.RAW_BINARY_PREVIEW),
    ],
)
def test_description_phrases_detect_blocking_classes(phrase, token):
    result = s1.classify_finding(phrase)
    assert result.severity == s1.BUILD_BLOCKING
    assert result.finding_class == token
    assert s1.may_route_to_e6(result) is False


def test_non_ns_finding_may_route_to_e6():
    result = s1.classify_finding(
        "cosmetic copy nit outside North-Star classes",
        finding_class="copy_nit",
    )
    assert result.severity == s1.FOLLOW_ON
    assert result.may_route_to_e6 is True
    assert s1.route_to_e6(result) is result


def test_e6_routing_of_dead_control_raises():
    with pytest.raises(s1.E6RoutingForbidden) as ei:
        s1.assert_e6_routing_allowed(
            {"description": "dead control on restart", "finding_class": "dead_control"}
        )
    assert s1.E6_ROUTING_FORBIDDEN_MESSAGE in ei.value.message


# --------------------------------------------------------------------------
# Terminal status — CANDIDATE-MET until S1; unqualified only at 0 exits + PASS
# --------------------------------------------------------------------------


def test_default_status_is_candidate_met_north_star_pending():
    """GWT: S1 not yet run, structural gates green → CANDIDATE-MET pending S1."""
    status = terminal_status([])
    assert STATUS_CANDIDATE_MET_PREFIX in status
    assert "0 signed exits" in status
    assert "North Star pending S1" in status
    assert status != STATUS_UNQUALIFIED
    assert not unqualified_status_reachable([], s1_verdict=None)


def test_status_with_signed_exits_stays_candidate_even_if_s1_pass_injected():
    rows = [
        _signed("E2", "usage-count", accessor_proven=True),
        _signed("E4", "instrumentation"),
    ]
    status = terminal_status(rows, s1_verdict="PASS")
    assert STATUS_CANDIDATE_MET_PREFIX in status
    assert "2 signed exits" in status
    assert "E2" in status and "E4" in status
    assert "North Star pending S1" in status
    assert status != STATUS_UNQUALIFIED


def test_unqualified_only_when_zero_exits_and_injected_s1_pass():
    """GWT: S1 PASS + zero exits → unqualified 'ten criteria met' (+ attachment)."""
    # Default terminal_status keeps the exact W2 phrase.
    status = terminal_status([], s1_verdict="PASS")
    assert status == STATUS_UNQUALIFIED
    assert unqualified_status_reachable([], s1_verdict="PASS") is True

    # W22 display form attaches S1's PASS verdict.
    attached = terminal_status_with_s1_attachment([], s1_verdict="PASS")
    assert STATUS_UNQUALIFIED in attached
    assert STATUS_NORTH_STAR_MET in attached
    assert attached == "%s; %s" % (STATUS_UNQUALIFIED, STATUS_NORTH_STAR_MET)


def test_emit_terminal_status_reads_pending_from_s1_validation_by_default():
    status = emit_terminal_status([], root=ROOT)
    assert STATUS_CANDIDATE_MET_PREFIX in status
    assert "North Star pending S1" in status
    assert status != STATUS_UNQUALIFIED


def test_emit_terminal_status_injected_pass_unlocks_unqualified():
    status = emit_terminal_status([], root=ROOT, s1_verdict="PASS")
    assert status == STATUS_UNQUALIFIED
    attached = emit_terminal_status(
        [], root=ROOT, s1_verdict="PASS", attach_s1_pass=True
    )
    assert STATUS_NORTH_STAR_MET in attached


def test_register_status_default_pending_not_unqualified():
    reg = ExitRegister()
    assert "0 signed exits" in reg.status()
    assert "North Star pending S1" in reg.status()
    assert reg.status() != STATUS_UNQUALIFIED
    # Injected PASS on empty register → unqualified.
    reg.s1_verdict = "PASS"
    assert reg.status() == STATUS_UNQUALIFIED


def test_s1_fail_does_not_emit_unqualified():
    status = s1.emit_terminal_status_for_s1([], s1_verdict="FAIL")
    assert status != STATUS_UNQUALIFIED
    assert "North Star pending S1" in status or STATUS_CANDIDATE_MET_PREFIX in status


# --------------------------------------------------------------------------
# Traceability — S1 alone converts CANDIDATE-MET → MET; fail → OPEN
# --------------------------------------------------------------------------


def test_s1_status_transition_pending_never_promotes_to_met():
    assert (
        s1.s1_status_transition("CANDIDATE-MET", s1_verdict=None) == "CANDIDATE-MET"
    )
    assert (
        s1.s1_status_transition("CANDIDATE-MET", s1_verdict="PENDING")
        == "CANDIDATE-MET"
    )


def test_s1_status_transition_pass_promotes_to_met():
    assert s1.s1_status_transition("CANDIDATE-MET", s1_verdict="PASS") == "MET"


def test_s1_status_transition_fail_reverts_to_open():
    assert s1.s1_status_transition("CANDIDATE-MET", s1_verdict="FAIL") == "OPEN"
    assert (
        s1.s1_status_transition(
            "CANDIDATE-MET", s1_verdict="PASS", criterion_passed=False
        )
        == "OPEN"
    )


def test_apply_s1_to_matrix_rows_fail_opens_all_when_no_list():
    rows = [
        {"criterion": "1", "status": "CANDIDATE-MET"},
        {"criterion": "2", "status": "CANDIDATE-MET"},
    ]
    out = s1.apply_s1_to_matrix_rows(rows, s1_verdict="FAIL")
    assert all(r["status"] == "OPEN" for r in out)


def test_apply_s1_to_matrix_rows_pass_promotes():
    rows = [{"criterion": "1", "status": "CANDIDATE-MET"}]
    out = s1.apply_s1_to_matrix_rows(rows, s1_verdict="PASS")
    assert out[0]["status"] == "MET"


# --------------------------------------------------------------------------
# Release guard — not publishable to v1.1.x
# --------------------------------------------------------------------------


def test_release_guard_refuses_v11_branch():
    result = rg.check_publish(branch="v1.1.2", source_branch="v1.2")
    assert result.status == rg.REFUSE
    assert result.publishable is False
    assert "v1.1.x" in result.message


def test_release_guard_refuses_v11_channel():
    result = rg.guard_effort_release(channel="collaborators-v1.1")
    assert result.publishable is False
    with pytest.raises(rg.ReleaseGuardError, match="v1.1.x"):
        rg.assert_not_publishable_to_v11(channel="v1.1.x")


def test_release_guard_allows_v12_destination():
    result = rg.check_publish(branch="v1.2", channel="internal-v1.2")
    assert result.status == rg.GO
    assert result.publishable is True
    rg.assert_publish_allowed(branch="v1.2", channel="internal-v1.2")


def test_release_guard_refuses_v11_x_label():
    assert rg.is_v11_line("v1.1.x") is True
    assert rg.is_v11_line("release/1.1") is True
    assert rg.is_forbidden_publish_target(branch="v1.1.0") is True
    assert rg.is_v12_line("v1.2") is True
    assert rg.is_v11_line("v1.2") is False


def test_release_guard_source_must_be_v12():
    result = rg.check_publish(
        branch="staging",
        source_branch="v1.1.5",
        require_source_v12=True,
    )
    assert result.publishable is False
    assert result.status == rg.REFUSE


# --------------------------------------------------------------------------
# Module surface
# --------------------------------------------------------------------------


def test_w22_modules_importable():
    assert callable(s1.classify_finding)
    assert callable(s1.route_to_e6)
    assert callable(er.terminal_status)
    assert callable(er.emit_terminal_status)
    assert callable(rg.guard_effort_release)
    assert s1.BUILD_BLOCKING_CLASSES == frozenset(
        {
            s1.DEAD_CONTROL,
            s1.SILENT_ZERO,
            s1.MISLABELLED_EMPTY,
            s1.RAW_BINARY_PREVIEW,
        }
    )
