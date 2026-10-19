"""W1 — containment smoke + coverage-toolchain probe.

Two claims are exercised here, not asserted:

* **Containment.** Every write target this build declares resolves under
  ``planning/sleep-2026-07-28/stage2/``, the repository-root foreign Foreman
  artifacts are byte-identical before and after a run, and the three escapes
  (``..`` traversal, absolute path, symlink/junction) are each REFUSED BY NAME
  — the rule name, not a prose substring, is what the assertions read.
* **A protected set that is real, not decorative.** Every protected artifact
  that exists on disk is genuinely hashed, and a drift guard catches a *new*
  root-level Foreman document that the protected set does not yet cover.
* **Coverage toolchain.** ``delta-coverage unavailable`` is recorded as a fact
  when the tooling is absent, and availability is never defaulted to true.

The coverage-probe tests live in this file deliberately: the W1 gate-command in
the frozen plan names exactly two test files
(``test_containment_smoke_2026_07_29.py`` and
``test_verification_task_triple_2026_07_29.py``), so a third file would leave
``tools/coverage_toolchain_probe.py`` unexercised under the plan's own gate.
"""
import json
import os
from pathlib import Path

import pytest

from tools import containment_smoke as cs
from tools import coverage_toolchain_probe as probe


ROOT = cs.containment_root()
REPO = cs.repo_root()


# --------------------------------------------------------------------------
# The root itself
# --------------------------------------------------------------------------


def test_the_containment_root_is_the_stage2_folder():
    assert cs.root_is_canonical(ROOT), (
        "containment root %s does not end in %s" % (ROOT, "/".join(cs.CONTAINMENT_ROOT_TAIL))
    )
    assert tuple(p.lower() for p in ROOT.parts[-3:]) == cs.CONTAINMENT_ROOT_TAIL


def test_the_repo_root_is_the_parent_that_carries_the_foreign_doc_trio():
    assert cs.is_within(ROOT, REPO)
    assert not cs.is_within(REPO, ROOT)


# --------------------------------------------------------------------------
# Write-target containment
# --------------------------------------------------------------------------


def test_a_relative_target_inside_the_root_is_allowed():
    verdict = cs.check_write_target(os.path.join("artifacts", "traces", "open-e2e.json"))
    assert verdict.allowed
    assert verdict.rule == cs.RULE_INSIDE


def test_an_absolute_target_inside_the_root_is_allowed():
    verdict = cs.check_write_target(str(ROOT / "artifacts" / "x.json"))
    assert verdict.allowed
    assert verdict.rule == cs.RULE_INSIDE


def test_dotdot_traversal_is_refused_by_name():
    target = os.path.join("..", "..", "..", "DESCRIPTION.md")
    verdict = cs.check_write_target(target)
    assert not verdict.allowed
    assert verdict.rule == cs.RULE_TRAVERSAL


def test_an_absolute_path_outside_the_root_is_refused_by_name():
    verdict = cs.check_write_target(str(REPO / "DESCRIPTION.md"))
    assert not verdict.allowed
    assert verdict.rule == cs.RULE_ABSOLUTE_OUTSIDE


def test_a_symlink_or_junction_escape_is_refused_by_name(tmp_path):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "clobbered.md").write_text("real file on the far side\n", encoding="utf-8")
    kind = cs._make_link(root / "escape", outside)
    if not kind:
        pytest.skip("this host offers neither os.symlink nor CreateJunction")
    try:
        verdict = cs.check_write_target(os.path.join("escape", "clobbered.md"), root=root)
        assert not verdict.allowed, "a %s out of the root was allowed" % kind
        assert verdict.rule == cs.RULE_SYMLINK_ESCAPE
        # the lexical path looked contained; only the resolved path told the truth
        assert cs.is_within(root / "escape" / "clobbered.md", root)
        assert not cs.is_within(verdict.resolved, root)
    finally:
        cs._remove_link(root / "escape")


def test_assert_write_target_raises_naming_the_path():
    offender = str(REPO / "DESCRIPTION.md")
    with pytest.raises(cs.ContainmentViolation) as excinfo:
        cs.assert_write_target(offender)
    assert offender in str(excinfo.value)
    assert cs.RULE_ABSOLUTE_OUTSIDE in str(excinfo.value)


# --------------------------------------------------------------------------
# The escape-attempt suite (hardening gate: containment is exercised)
# --------------------------------------------------------------------------


def test_the_escape_suite_attempts_all_three_named_escapes():
    rows = cs.escape_attempt_suite(root=ROOT, repo=REPO)
    assert [r["name"] for r in rows] == list(cs.ESCAPE_ATTEMPT_NAMES)


def test_every_attempted_escape_is_refused_with_its_expected_rule():
    rows = cs.escape_attempt_suite(root=ROOT, repo=REPO)
    for row in rows:
        if not row["attempted"]:
            assert row["rule"] == cs.RULE_UNAVAILABLE, (
                "an un-attempted escape must record why, not pass silently"
            )
            continue
        assert row["refused"], "escape %s was NOT refused" % row["name"]
        assert row["rule"] == row["expected_rule"], (
            "escape %s refused under %s, expected %s"
            % (row["name"], row["rule"], row["expected_rule"])
        )


def test_the_escape_suite_leaves_no_scratch_directory_behind():
    before = {p.name for p in ROOT.iterdir()}
    cs.escape_attempt_suite(root=ROOT, repo=REPO)
    after = {p.name for p in ROOT.iterdir()}
    assert after == before


# --------------------------------------------------------------------------
# The smoke run
# --------------------------------------------------------------------------


def test_a_write_to_a_root_foreign_artifact_fails_naming_path_and_hashes():
    offender = str(REPO / "DESCRIPTION.md")
    result = cs.run_smoke(write_targets=[offender], root=ROOT, repo=REPO)

    assert not result.ok
    assert len(result.refusals) == 1
    refusal = result.refusals[0]
    assert refusal.target == offender
    assert refusal.rule == cs.RULE_ABSOLUTE_OUTSIDE
    assert refusal.foreign_artifact == "DESCRIPTION.md"
    # pre == post is the proof it was never clobbered (both None when absent).
    assert refusal.pre_hash == refusal.post_hash
    if (REPO / "DESCRIPTION.md").is_file():
        assert refusal.pre_hash == cs.sha256_of(REPO / "DESCRIPTION.md")

    report = result.report()
    assert offender in report
    assert "pre_hash" in report and "post_hash" in report
    assert "DESCRIPTION.md" in report
    assert any(offender in p for p in result.problems)


def test_the_declared_write_targets_all_resolve_inside_the_root():
    targets = cs.ledger_write_targets(ROOT)
    assert targets, "the shared-artifact ledger declares no write targets"
    for target in targets:
        verdict = cs.check_write_target(target, root=ROOT)
        assert verdict.allowed, "ledger write target %r escapes (%s)" % (target, verdict.rule)


def test_the_smoke_passes_and_root_foreign_artifacts_are_byte_identical():
    result = cs.run_smoke(root=ROOT, repo=REPO)
    assert result.changed_foreign == [], result.report()
    assert result.foreign_before == result.foreign_after
    assert result.ok, result.report()
    assert set(result.foreign_before) == set(cs.ROOT_FOREIGN_ARTIFACTS)


def test_every_protected_artifact_that_exists_is_actually_hashed():
    """The protected set is real, not decorative.

    A name in ROOT_FOREIGN_ARTIFACTS that exists on disk must contribute a
    hash to the snapshot; a name that does not exist contributes ``None``,
    which is the honest record of *absent* (and an absent file that stays
    absent is still byte-identical across the run).
    """
    snapshot = cs.snapshot_foreign_artifacts(REPO)
    assert set(snapshot) == set(cs.ROOT_FOREIGN_ARTIFACTS)
    present = [n for n in cs.ROOT_FOREIGN_ARTIFACTS if (REPO / n).is_file()]
    assert present, "no protected root artifact exists — the set is decorative"
    for name in present:
        assert snapshot[name] == cs.sha256_of(REPO / name)
        assert len(snapshot[name]) == 64


def test_a_new_foreman_artifact_at_the_root_is_detected_as_unprotected(tmp_path):
    """The drift guard on the hand-written protected set.

    Another effort dropping a report at the repository root would otherwise
    leave that file unhashed and therefore unproven.
    """
    (tmp_path / "WAVE9-EXECUTE-SUMMARY.md").write_text("another run\n", encoding="utf-8")
    (tmp_path / "FOREMAN-EXECUTION-LOG-OTHER.md").write_text("another log\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("not a foreman artifact\n", encoding="utf-8")
    (tmp_path / "DESCRIPTION.md").write_text("already protected\n", encoding="utf-8")

    drift = cs.unprotected_foreign_candidates(repo=tmp_path)
    assert drift == ["FOREMAN-EXECUTION-LOG-OTHER.md", "WAVE9-EXECUTE-SUMMARY.md"]
    assert "README.md" not in drift, "an ordinary repo doc is not a Foreman artifact"
    assert "DESCRIPTION.md" not in drift, "an already-protected artifact is not drift"


def test_the_drift_guard_is_advisory_and_never_fails_the_smoke(tmp_path):
    """Drift is reported; it does not decide THIS build's containment."""
    (tmp_path / "WAVE9-EXECUTE-SUMMARY.md").write_text("another run\n", encoding="utf-8")
    result = cs.run_smoke(write_targets=["artifacts/x.json"], root=tmp_path,
                          repo=tmp_path, run_escape_suite=False)
    assert result.ok, "an unprotected neighbour must not fail our own containment"
    assert result.unprotected_candidates == ["WAVE9-EXECUTE-SUMMARY.md"]
    assert "ADVISORY" in result.report()
    assert "WAVE9-EXECUTE-SUMMARY.md" in result.report()
    assert result.as_dict()["unprotected_candidates"] == ["WAVE9-EXECUTE-SUMMARY.md"]


def test_the_shipped_protected_set_covers_todays_repository_root():
    """No foreign Foreman artifact sits unprotected at the real repo root.

    If this fails, another effort added a root-level Foreman document and
    ROOT_FOREIGN_ARTIFACTS (and the ledger's must-not-touch rows) must be
    extended to cover it before this build writes anything.
    """
    drift = cs.unprotected_foreign_candidates(repo=REPO)
    assert drift == [], (
        "unprotected root Foreman artifact(s): %s — add them to "
        "ROOT_FOREIGN_ARTIFACTS and to the ledger's must-not-touch rows"
        % ", ".join(drift)
    )


def test_a_changed_foreign_artifact_is_reported_with_both_hashes():
    before = {"DESCRIPTION.md": "a" * 64}
    after = {"DESCRIPTION.md": "b" * 64}
    changed = cs.compare_snapshots(before, after)
    assert changed == [{"artifact": "DESCRIPTION.md",
                        "pre_hash": "a" * 64, "post_hash": "b" * 64}]


def test_more_write_targets_than_the_named_bound_are_refused(tmp_path):
    targets = ["artifacts/f%d.json" % i for i in range(cs.MAX_WRITE_TARGETS + 1)]
    result = cs.run_smoke(write_targets=targets, root=tmp_path, repo=tmp_path)
    assert not result.ok
    assert result.bound_exceeded
    assert result.refusals[0].rule == cs.RULE_BOUND_EXCEEDED
    assert str(cs.MAX_WRITE_TARGETS) in result.problems[0]


def test_exactly_the_bound_is_still_accepted(tmp_path):
    targets = ["artifacts/f%d.json" % i for i in range(cs.MAX_WRITE_TARGETS)]
    result = cs.run_smoke(write_targets=targets, root=tmp_path, repo=tmp_path,
                          run_escape_suite=False)
    assert not result.bound_exceeded
    assert result.ok


def test_running_the_smoke_twice_gives_the_same_verdicts():
    """Repeat-invocation: the smoke is a read, and reading twice changes nothing."""
    first = cs.run_smoke(root=ROOT, repo=REPO)
    second = cs.run_smoke(root=ROOT, repo=REPO)
    shape = lambda r: [(v.target, v.allowed, v.rule) for v in r.verdicts]
    assert shape(first) == shape(second)
    assert first.ok == second.ok
    assert first.foreign_before == second.foreign_after
    assert second.changed_foreign == []


def test_main_returns_zero_when_contained_and_one_when_not(capsys):
    assert cs.main([]) == 0
    capsys.readouterr()
    assert cs.main([str(REPO / "DESCRIPTION.md")]) == 1
    out = capsys.readouterr().out
    assert "DESCRIPTION.md" in out


# --------------------------------------------------------------------------
# Coverage toolchain probe — truth, not assumption
# --------------------------------------------------------------------------


def _finder(found, version="9.9.9", only=None):
    def finder(import_name, dist_name):
        hit = found and (only is None or import_name in only)
        return {"import_name": import_name, "distribution": dist_name,
                "found": hit, "version": version if hit else None, "error": None}
    return finder


def test_delta_coverage_is_unavailable_unless_positively_found():
    record = probe.probe(finder=_finder(False))
    assert record["delta_coverage"]["available"] is False
    assert record["delta_coverage"]["fact"] == probe.FACT_UNAVAILABLE
    assert record["delta_coverage"]["tool"] is None
    assert record["e4_enumerated_list_required"] is True


def test_a_delta_tool_without_a_coverage_engine_is_still_unavailable():
    record = probe.probe(finder=_finder(True, only={"diff_cover"}))
    assert record["delta_coverage"]["available"] is False
    assert record["delta_coverage"]["fact"] == probe.FACT_UNAVAILABLE


def test_availability_is_recorded_only_with_a_real_tool_and_engine():
    record = probe.probe(finder=_finder(True, version="7.1.0"))
    assert record["delta_coverage"]["available"] is True
    assert record["delta_coverage"]["fact"] == "delta-coverage available via diff-cover 7.1.0"
    assert record["coverage_tool"]["name"] == "coverage"
    assert record["e4_enumerated_list_required"] is False


def test_the_default_finder_reports_a_missing_module_as_not_found():
    finding = probe.default_finder("no_such_module_for_anchor_w1", "no-such-dist")
    assert finding["found"] is False
    assert finding["version"] is None


def test_the_probe_is_deterministic_for_one_box():
    assert probe.probe(finder=_finder(False)) == probe.probe(finder=_finder(False))
    assert probe.fingerprint(probe.probe()) == probe.fingerprint(probe.probe())


def test_writing_the_record_twice_leaves_the_file_byte_identical(tmp_path):
    """Repeat-invocation: an unchanged toolchain must not churn the artifact."""
    first = probe.write_record(root=tmp_path, finder=_finder(False), now="2026-07-29T00:00:00+00:00")
    path = Path(first["path"])
    assert first["changed"] is True
    payload = path.read_bytes()

    second = probe.write_record(root=tmp_path, finder=_finder(False), now="2026-07-30T00:00:00+00:00")
    assert second["changed"] is False
    assert path.read_bytes() == payload
    assert second["fingerprint"] == first["fingerprint"]


def test_a_changed_toolchain_rewrites_the_record(tmp_path):
    probe.write_record(root=tmp_path, finder=_finder(False), now="2026-07-29T00:00:00+00:00")
    changed = probe.write_record(root=tmp_path, finder=_finder(True), now="2026-07-29T01:00:00+00:00")
    assert changed["changed"] is True
    assert changed["record"]["delta_coverage"]["available"] is True


def test_the_probe_records_this_boxs_ground_truth_into_artifacts():
    """The W1 deliverable: the real toolchain on this box, written down."""
    target = probe.artifact_path()
    assert cs.check_write_target(str(target), root=ROOT).allowed

    outcome = probe.write_record()
    record = outcome["record"]
    assert record["schema"] == probe.SCHEMA

    delta = record["delta_coverage"]
    assert isinstance(delta["available"], bool)
    if delta["available"]:
        assert delta["tool"] and delta["fact"].startswith("delta-coverage available via")
        assert record["e4_enumerated_list_required"] is False
    else:
        assert delta["fact"] == probe.FACT_UNAVAILABLE
        assert record["e4_enumerated_list_required"] is True

    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["fingerprint"] == probe.fingerprint(record)
    assert on_disk["delta_coverage"] == delta
    assert probe.summary_line(record)
