"""A finalizer owns process identities, not whichever process now has its PID."""

import copy

import proc_probe
import pytest

from steward_cockpit import code_job_handoff as ch


@pytest.fixture
def controller_job(tmp_path):
    return {
        "id": "original",
        "status": "finishing",
        "phase": "checking",
        "attempt": 1,
        "phase_at": 1,
        "worker": "coder",
        "repo": str(tmp_path / "repo"),
        "worktree": str(tmp_path / "worktree"),
        "steward_dir": str(tmp_path / "steward"),
        "finalizer_active": True,
        "claim": {"pid": 101, "birth": 10},
        "command": {
            "pid": 202,
            "birth": 20,
            "state": "active",
            "phase": "checking",
            "contained": True,
        },
    }


def _probes(monkeypatch, controller, child):
    """Evidence rows are (probe state, current birth, PID present in enumeration)."""
    evidence = {101: controller, 202: child}

    def probe_status(pid):
        state, birth, _ = evidence[int(pid)]
        code = {
            "running": proc_probe.PROBE_RUNNING,
            "exited": proc_probe.PROBE_EXITED,
            "unknown": getattr(proc_probe, "PROBE_UNKNOWN", "unknown"),
        }[state]
        return code, birth, "synthetic process identity evidence"

    def pid_alive_via_enum(pid):
        return evidence[int(pid)][2]

    monkeypatch.setattr(proc_probe, "probe_status", probe_status)
    monkeypatch.setattr(proc_probe, "pid_alive_via_enum", pid_alive_via_enum)


def test_recycled_finalizer_identities_are_dead_but_worker_stays_unknown(
    monkeypatch, controller_job
):
    _probes(monkeypatch, ("running", 11, True), ("running", 21, True))

    assert ch.process_state(101, 10) == "unknown"
    assert ch.process_state(202, 20) == "unknown"
    assert ch.orphaned_finalizer(controller_job) is True


@pytest.mark.parametrize(
    "controller,child,missing_birth,expected",
    [
        (("running", 11, True), ("running", 21, True), None, True),
        (("running", 11, True), ("exited", 20, False), None, True),
        (("exited", 10, False), ("running", 21, True), None, True),
        (("running", 10, True), ("running", 21, True), None, False),
        (("running", 11, True), ("running", 20, True), None, False),
        (("running", 11, True), ("running", 21, True), "claim", False),
        (("running", 11, True), ("running", 21, True), "command", False),
        (("unknown", None, True), ("running", 21, True), None, False),
        (("running", 11, True), ("unknown", None, True), None, False),
        (("running", None, True), ("running", 21, True), None, False),
        (("running", 11, True), ("running", None, True), None, False),
    ],
    ids=[
        "both-recycled",
        "recycled-controller-exited-child",
        "exited-controller-recycled-child",
        "matching-live-controller",
        "matching-live-child",
        "missing-controller-birth",
        "missing-child-birth",
        "unknown-controller-probe",
        "unknown-child-probe",
        "unavailable-current-controller-birth",
        "unavailable-current-child-birth",
    ],
)
def test_orphan_requires_positive_evidence_for_both_owned_identities(
    monkeypatch, controller_job, controller, child, missing_birth, expected
):
    _probes(monkeypatch, controller, child)
    if missing_birth:
        controller_job[missing_birth].pop("birth")

    assert ch.orphaned_finalizer(controller_job) is expected


def test_recycled_uncontained_child_does_not_authorize_orphan_recovery(
    monkeypatch, controller_job
):
    _probes(monkeypatch, ("running", 11, True), ("running", 21, True))
    controller_job["command"]["contained"] = False

    assert ch.orphaned_finalizer(controller_job) is False


@pytest.mark.parametrize(
    "child",
    [("exited", 20, False), ("unknown", None, False)],
    ids=["child-exit-observed", "child-absent-from-enumeration"],
)
def test_finished_child_does_not_make_matching_live_controller_dead(
    monkeypatch, controller_job, child
):
    _probes(monkeypatch, ("running", 10, True), child)
    before = copy.deepcopy(controller_job)

    observation = ch.supervise(controller_job, now=1000)

    assert observation["state"] != "dead"
    assert observation["liveness"] in {"completed", "active"}
    assert ch.orphaned_finalizer(controller_job) is False
    assert controller_job == before


def test_dead_controller_and_dead_child_remain_dead_observation(
    monkeypatch, controller_job
):
    _probes(monkeypatch, ("exited", 10, False), ("exited", 20, False))

    observation = ch.supervise(controller_job, now=1000)

    assert observation["liveness"] == "dead"
    assert observation["state"] == "dead"
    assert ch.orphaned_finalizer(controller_job) is True


def test_unknown_controller_and_dead_child_do_not_invent_active_owner(
    monkeypatch, controller_job
):
    _probes(monkeypatch, ("unknown", None, True), ("exited", 20, False))

    observation = ch.supervise(controller_job, now=1000)

    assert observation["liveness"] != "active"
    assert observation["state"] != "active"
    assert ch.orphaned_finalizer(controller_job) is False
