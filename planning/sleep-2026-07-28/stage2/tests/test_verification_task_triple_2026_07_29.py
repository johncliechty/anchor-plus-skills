"""W1 — the John verification task triple and the shared-artifact ledger.

The load-bearing assertion in this file is a refusal: an unconfirmed task
triple HALTs with

    live-John item — no E5 available on the task triple

and **no number of passing tests changes that**. Everything below is structure;
structure cannot sign for John. The same rule governs the shared-artifact
ledger, whose sign-off is a live-John item too.

The ledger tests live in this file deliberately — the W1 gate-command in the
frozen plan names exactly two test files, so a third would leave
``tools/artifact_ledger.py`` unexercised under the plan's own gate.
"""
import copy
import json
import re
from pathlib import Path

import pytest

from tools import artifact_ledger as ledger
from tools import containment_smoke as cs
from tools import verification_task_triple as triple


ROOT = cs.containment_root()

# A shipped W1 file may not carry a host absolute path — neither a Windows
# drive-letter path nor a POSIX home path. The two patterns below are the test;
# no example of either is written out here, because this file is itself one of
# the shipped files the check reads.
_DRIVE_ABS = re.compile(r"[A-Za-z]:\\")
_POSIX_HOME = re.compile(r"/(?:Users|home)/[A-Za-z0-9._-]+/")

W1_SHIPPED = (
    "tools/__init__.py",
    "tools/containment_smoke.py",
    "tools/coverage_toolchain_probe.py",
    "tools/verification_task_triple.py",
    "tools/artifact_ledger.py",
    "tests/conftest.py",
    "tests/test_containment_smoke_2026_07_29.py",
    "tests/test_verification_task_triple_2026_07_29.py",
    "artifacts/verification-task-triple.json",
    "artifacts/shared-artifact-ledger.md",
)


@pytest.fixture()
def shipped_triple():
    return triple.load_triple(root=ROOT)


def _confirm(task, date="2026-07-29"):
    task["john_confirmation"] = {
        "confirmed": True,
        "confirmed_by": "John",
        "date": date,
        "line": "ran it on v1.2 and saw the expected observable",
    }
    return task


# --------------------------------------------------------------------------
# The triple itself
# --------------------------------------------------------------------------


def test_the_triple_ships_three_reproducible_tasks(shipped_triple):
    kinds = [t["kind"] for t in shipped_triple["tasks"]]
    assert sorted(kinds) == sorted(triple.REQUIRED_KINDS)
    for task in shipped_triple["tasks"]:
        assert task["id"]
        assert [s for s in task["invocation"]["steps"] if s.strip()], task["id"]
        assert task["expected_observable"].strip(), task["id"]


def test_the_triple_is_structurally_well_formed(shipped_triple):
    assert triple._structural_problems(shipped_triple) == []


def test_no_shipped_w1_file_carries_a_host_absolute_path():
    for rel in W1_SHIPPED:
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert not _DRIVE_ABS.search(text), "%s carries a drive-letter absolute path" % rel
        assert not _POSIX_HOME.search(text), "%s carries a home-directory path" % rel


# --------------------------------------------------------------------------
# The live-John HALT — the whole point of Phase 0
# --------------------------------------------------------------------------


def test_an_unconfirmed_triple_halts_with_the_exact_live_john_reason(shipped_triple):
    doc = copy.deepcopy(shipped_triple)
    for task in doc["tasks"]:
        task["john_confirmation"] = triple.confirmation_template()

    result = triple.validate_triple(doc)
    assert result.status == triple.HALT
    assert result.reason == "live-John item — no E5 available on the task triple"
    assert result.reason == triple.HALT_REASON_NO_E5
    assert not result.is_go
    assert sorted(result.unconfirmed) == sorted(t["id"] for t in doc["tasks"])


def test_a_partly_confirmed_triple_still_halts_and_names_the_gaps(shipped_triple):
    # Shipped artifact may already be fully John-confirmed (Phase-0 GO). Always
    # wipe confirmations first so this case stays a *partial* confirm, not GO.
    doc = copy.deepcopy(shipped_triple)
    for task in doc["tasks"]:
        task["john_confirmation"] = triple.confirmation_template()
    _confirm(doc["tasks"][0])
    result = triple.validate_triple(doc)
    assert result.status == triple.HALT
    assert result.reason == triple.HALT_REASON_NO_E5
    assert result.confirmed == [doc["tasks"][0]["id"]]
    assert result.unconfirmed == [t["id"] for t in doc["tasks"][1:]]


def test_a_fully_confirmed_triple_is_go(shipped_triple):
    doc = copy.deepcopy(shipped_triple)
    for task in doc["tasks"]:
        _confirm(task)
    result = triple.validate_triple(doc)
    assert result.status == triple.GO
    assert result.is_go
    assert len(result.confirmed) == 3


@pytest.mark.parametrize("bad", [
    {"confirmed": True, "confirmed_by": "John", "date": "yesterday", "line": "worked"},
    {"confirmed": True, "confirmed_by": "John", "date": "", "line": "worked"},
    {"confirmed": True, "confirmed_by": "", "date": "2026-07-29", "line": "worked"},
    {"confirmed": True, "confirmed_by": "John", "date": "2026-07-29", "line": "   "},
    {"confirmed": "yes", "confirmed_by": "John", "date": "2026-07-29", "line": "worked"},
    {"confirmed": True, "confirmed_by": "John", "date": "07/29/2026", "line": "worked"},
    None,
])
def test_a_half_written_confirmation_is_not_a_confirmation(shipped_triple, bad):
    assert triple.confirmation_is_valid(bad) is False
    doc = copy.deepcopy(shipped_triple)
    for task in doc["tasks"]:
        _confirm(task)
    doc["tasks"][1]["john_confirmation"] = bad
    result = triple.validate_triple(doc)
    assert result.status == triple.HALT
    assert result.reason == triple.HALT_REASON_NO_E5


def test_a_malformed_triple_halts_for_a_different_reason_than_no_confirmation(shipped_triple):
    doc = copy.deepcopy(shipped_triple)
    doc["tasks"] = doc["tasks"][:2]
    result = triple.validate_triple(doc)
    assert result.status == triple.HALT
    assert result.reason.startswith(triple.HALT_REASON_MALFORMED)
    assert result.reason != triple.HALT_REASON_NO_E5, (
        "'the triple is broken' and 'John has not confirmed it' are different facts"
    )


def test_a_missing_triple_is_a_halt_not_a_pass(tmp_path):
    result = triple.gate(path=tmp_path / "nope.json")
    assert result.status == triple.HALT
    assert not result.is_go


# --------------------------------------------------------------------------
# No exit substitutes for John
# --------------------------------------------------------------------------


def test_e5_cannot_be_signed_against_the_task_triple():
    with pytest.raises(triple.ExitNotAvailable) as excinfo:
        triple.assert_no_exit_substitute("E5")
    assert str(excinfo.value) == triple.HALT_REASON_NO_E5


@pytest.mark.parametrize("exit_id", ["E1", "E2", "E3", "E4", "E6", "e5", ""])
def test_no_other_exit_closes_the_triple_either(exit_id):
    with pytest.raises(triple.ExitNotAvailable) as excinfo:
        triple.assert_no_exit_substitute(exit_id)
    assert triple.HALT_REASON_NO_E5 in str(excinfo.value)


def test_the_triple_declares_that_no_exit_is_available(shipped_triple):
    assert triple.available_exits() == ()
    assert shipped_triple["exit_policy"]["available_exits"] == []
    assert shipped_triple["exit_policy"]["no_e5"] == triple.HALT_REASON_NO_E5


# --------------------------------------------------------------------------
# The shipped state, reported honestly
# --------------------------------------------------------------------------


def test_the_shipped_triple_reports_its_state_honestly():
    """Total over both worlds: signed => GO, unsigned => the live-John HALT.

    Nothing here asserts that John *has* confirmed — that would be a claim this
    build has no right to make. It asserts the report matches the file.
    """
    result = triple.gate(root=ROOT)
    doc = triple.load_triple(root=ROOT)
    every_task_confirmed = all(
        triple.confirmation_is_valid(t.get("john_confirmation")) for t in doc["tasks"]
    )
    if every_task_confirmed:
        assert result.status == triple.GO
    else:
        assert result.status == triple.HALT
        assert result.reason == triple.HALT_REASON_NO_E5
        assert doc["status"] == "AWAITING_JOHN_CONFIRMATION"


def test_the_phase0_decision_ignores_the_test_suite_entirely():
    """'regardless of how many tests pass' — the decision reads files, not results."""
    source = Path(triple.__file__).read_text(encoding="utf-8")
    body = source[source.index("def phase0_go_decision"):]
    for forbidden in ("pytest", "tests_passed", "test_count", "green"):
        assert forbidden not in body, "the Phase-0 decision consults %r" % forbidden

    decision = triple.phase0_go_decision(root=ROOT)
    triple_result = triple.gate(root=ROOT)
    ledger_result = ledger.gate(root=ROOT)
    if triple_result.is_go and ledger_result.is_go:
        assert decision.status in (triple.GO, triple.HALT)
    else:
        assert decision.status == triple.HALT
        assert decision.problems


# --------------------------------------------------------------------------
# The shared-artifact ledger
# --------------------------------------------------------------------------


def test_the_ledger_parses_into_rows_and_a_signoff_block():
    doc = ledger.load_ledger(root=ROOT)
    assert len(doc["rows"]) >= len(cs.ROOT_FOREIGN_ARTIFACTS) + 10
    for row in doc["rows"]:
        assert set(row) == set(ledger.COLUMNS)
        assert row["mode"] in ledger.MODES, row
    assert set(doc["signoff"]) >= {"status", "signed_by", "date", "line"}


def test_every_ledger_write_row_resolves_inside_the_containment_root():
    doc = ledger.load_ledger(root=ROOT)
    writes = [r for r in doc["rows"] if r["mode"] in ledger.WRITING_MODES]
    assert writes
    for row in writes:
        verdict = cs.check_write_target(row["path"], root=ROOT)
        assert verdict.allowed, "%s: %s escapes (%s)" % (row["id"], row["path"], verdict.rule)


def test_every_root_foreign_artifact_is_declared_must_not_touch():
    doc = ledger.load_ledger(root=ROOT)
    declared = {r["path"] for r in doc["rows"] if r["mode"] == ledger.MODE_MUST_NOT_TOUCH}
    expected = {ledger.REPO_ROOT_TOKEN + name for name in cs.ROOT_FOREIGN_ARTIFACTS}
    assert declared == expected


def test_the_ledger_lists_every_file_w1_ships():
    doc = ledger.load_ledger(root=ROOT)
    listed = {r["path"].replace("\\", "/") for r in doc["rows"]}
    for rel in W1_SHIPPED:
        assert rel in listed, "W1 ships %s but the ledger does not declare it" % rel
    assert "artifacts/coverage-toolchain-probe.json" in listed


def test_every_declared_w1_path_exists_on_disk():
    doc = ledger.load_ledger(root=ROOT)
    w1_rows = [r for r in doc["rows"] if r["owner"] == "W1"]
    assert w1_rows
    for row in w1_rows:
        path = ROOT / row["path"]
        if row["id"] == "coverage-probe-record":
            continue  # written by the probe when the gate runs
        assert path.exists(), "ledger declares %s but it does not exist" % row["path"]


def test_the_shipped_ledger_is_unsigned_or_signed_and_says_so_honestly():
    doc = ledger.load_ledger(root=ROOT)
    result = ledger.validate_ledger(doc, root=ROOT)
    if ledger.signoff_is_valid(doc["signoff"]):
        assert result.status == ledger.GO
    else:
        assert result.status == ledger.HALT
        assert result.reason == ledger.HALT_REASON_UNSIGNED
        assert doc["signoff"]["status"].upper() != "SIGNED"


def test_a_signed_ledger_validates(tmp_path):
    text = (ROOT / ledger.ARTIFACT_RELPATH).read_text(encoding="utf-8")
    signed = (text
              .replace("- **status:** UNSIGNED", "- **status:** SIGNED")
              .replace("- **signed_by:** (pending — John)", "- **signed_by:** John")
              .replace("- **date:** (pending — ISO YYYY-MM-DD)", "- **date:** 2026-07-29")
              .replace("- **line:** (pending — John writes what he reviewed and approved here)",
                       "- **line:** reviewed the artifact list and approved it"))
    doc = ledger.parse_ledger(signed)
    assert ledger.signoff_is_valid(doc["signoff"])
    assert ledger.validate_ledger(doc, root=ROOT).status == ledger.GO


@pytest.mark.parametrize("field,value", [
    ("status", "UNSIGNED"),
    ("date", "soon"),
    ("signed_by", ""),
    ("line", ""),
])
def test_a_half_written_signoff_is_not_a_signature(field, value):
    signoff = {"status": "SIGNED", "signed_by": "John",
               "date": "2026-07-29", "line": "approved"}
    signoff[field] = value
    assert ledger.signoff_is_valid(signoff) is False


def test_a_ledger_row_that_escapes_the_root_is_rejected():
    doc = ledger.load_ledger(root=ROOT)
    doc["rows"].append({"id": "rogue", "path": "../../../DESCRIPTION.md", "owner": "W1",
                        "mode": "write", "consumed_by": "nobody", "notes": "escape"})
    result = ledger.validate_ledger(doc, root=ROOT)
    assert result.status == ledger.HALT
    assert any("rogue" in p and cs.RULE_TRAVERSAL in p for p in result.problems)


def test_a_must_not_touch_row_the_smoke_does_not_protect_is_rejected():
    doc = ledger.load_ledger(root=ROOT)
    doc["rows"].append({"id": "unprotected", "path": ledger.REPO_ROOT_TOKEN + "README.md",
                        "owner": "another effort", "mode": "must-not-touch",
                        "consumed_by": "nobody", "notes": "not in the smoke's list"})
    result = ledger.validate_ledger(doc, root=ROOT)
    assert result.status == ledger.HALT
    assert any("unprotected" in p for p in result.problems)


def test_dropping_a_protected_artifact_from_the_ledger_is_rejected():
    doc = ledger.load_ledger(root=ROOT)
    doc["rows"] = [r for r in doc["rows"]
                   if r["path"] != ledger.REPO_ROOT_TOKEN + "DESCRIPTION.md"]
    result = ledger.validate_ledger(doc, root=ROOT)
    assert result.status == ledger.HALT
    assert any("DESCRIPTION.md" in p for p in result.problems)


def test_a_missing_ledger_is_a_halt_not_a_pass(tmp_path):
    result = ledger.gate(path=tmp_path / "nope.md")
    assert result.status == ledger.HALT
    assert not result.is_go


def test_parsing_the_ledger_twice_gives_the_same_document():
    """Repeat-invocation: the ledger read is pure."""
    assert ledger.load_ledger(root=ROOT) == ledger.load_ledger(root=ROOT)


def test_the_triple_json_round_trips():
    raw = (ROOT / triple.ARTIFACT_RELPATH).read_text(encoding="utf-8")
    assert json.loads(raw) == triple.load_triple(root=ROOT)
