"""An explicit Stop can finish after its verified controller has exited."""

import copy
import time
from types import SimpleNamespace

import pytest

from steward_cockpit import code_job_handoff as ch
from steward_cockpit import code_jobs as cj


@pytest.fixture
def stopped_env(tmp_path, monkeypatch):
    cdir = tmp_path / "cockpit"
    repo = tmp_path / "repo"
    tree = tmp_path / "tree"
    for directory in (cdir, repo, tree):
        directory.mkdir()
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))
    product = tree / "saved-work.txt"
    product.write_text("Useful work survives an interrupted Stop.", encoding="utf-8")
    job = {
        "id": "stopped-controller", "status": "finishing", "attempt": 2,
        "phase": "checking", "steward_dir": str(cdir), "repo": str(repo),
        "worktree": str(tree), "started": "2000-01-01 00:00:00",
        "stop_requested": "explicit Stop", "stop_requested_by": "human",
        "finalizer_active": True,
        "claim": {"pid": 101, "birth": 1},
        "command": {"phase": "checking", "state": "active", "contained": True,
                    "pid": 202, "birth": 2},
        "files": [], "manifest": ["saved-work.txt"],
        "check_ok": False, "check_log": "Prior check evidence.",
        "review": {"verdict": "PASS", "evidence": "Prior review evidence."},
        # Settlement must happen even when the ordinary sample is not yet due.
        "supervision": {"observed_at": time.time()},
    }
    cj._write_job(cdir, job)
    cj._busy_write({job["id"]: {
        "job": job["id"], "cdir": str(cdir), "repo": cj._norm(repo),
    }})
    reports = []
    handoffs = []

    def report(owner, stopped):
        reports.append(copy.deepcopy(stopped))
        handoffs.append(ch.save_result(owner, stopped, "Explicit Stop completed; saved work retained."))

    monkeypatch.setattr(cj, "_report", report)
    return SimpleNamespace(
        cdir=cdir, repo=repo, tree=tree, job=job, product=product,
        reports=reports, handoffs=handoffs,
    )


def test_interrupted_stop_settles_before_sample_gate_and_records_one_result(stopped_env, monkeypatch):
    env = stopped_env
    monkeypatch.setattr(ch, "orphaned_finalizer", lambda job: True)

    ch.refresh_supervision(env.cdir)

    saved = cj.read_jobs(env.cdir)[env.job["id"]]
    assert saved["status"] == "stopped" and saved["status"] not in cj.LIVE
    assert saved["finalizer_active"] is False
    assert saved["phase"] == "outcome" and saved["finished"]
    assert saved["stopped_by"] == "human"
    assert saved["kept_worktree"] == str(env.tree)
    assert saved["files"] == ["saved-work.txt"]
    assert saved["check_ok"] is False
    assert saved["check_log"] == env.job["check_log"]
    assert saved["review"] == env.job["review"]
    assert env.product.read_text(encoding="utf-8") == "Useful work survives an interrupted Stop."
    assert len(env.reports) == 1 and len(env.handoffs) == 1
    assert env.handoffs[0] is not None
    assert saved["handoff"] == env.handoffs[0]
    assert not any(entry.get("job") == env.job["id"] for entry in cj._busy_read().values())

    ch.refresh_supervision(env.cdir)
    assert ch.settle_stopped_finalizer(env.cdir, env.job) is None
    assert len(env.reports) == 1
    assert len(env.handoffs) == 1
    assert ch.recovery_error(saved), "Stopped work must not enter automatic recovery"


def test_no_proven_exit_leaves_explicit_stop_pending(stopped_env, monkeypatch):
    env = stopped_env
    monkeypatch.setattr(ch, "orphaned_finalizer", lambda job: False)

    assert ch.settle_stopped_finalizer(env.cdir, env.job) is None

    saved = cj.read_jobs(env.cdir)[env.job["id"]]
    assert saved["status"] == "finishing"
    assert saved["finalizer_active"] is True
    assert any(entry.get("job") == env.job["id"] for entry in cj._busy_read().values())
    assert env.reports == []
    assert env.handoffs == []


def test_dead_controller_without_explicit_stop_is_not_settled(stopped_env, monkeypatch):
    env = stopped_env
    job = copy.deepcopy(env.job)
    job.pop("stop_requested")
    cj._write_job(env.cdir, job)
    monkeypatch.setattr(ch, "orphaned_finalizer", lambda job: True)

    assert ch.settle_stopped_finalizer(env.cdir, job) is None
    assert cj.read_jobs(env.cdir)[job["id"]]["status"] == "finishing"
    assert env.reports == []


@pytest.mark.parametrize("changed", ["attempt", "claim", "command", "stop_requested"])
def test_exit_proof_cannot_settle_a_changed_attempt_or_controller(stopped_env, monkeypatch, changed):
    env = stopped_env

    def proof_then_race(_job):
        current = copy.deepcopy(env.job)
        if changed == "attempt":
            current["attempt"] += 1
        elif changed == "claim":
            current["claim"]["birth"] += 1
        elif changed == "command":
            current["command"]["birth"] += 1
        else:
            current.pop("stop_requested")
        cj._write_job(env.cdir, current)
        return True

    monkeypatch.setattr(ch, "orphaned_finalizer", proof_then_race)

    assert ch.settle_stopped_finalizer(env.cdir, env.job) is None
    assert cj.read_jobs(env.cdir)[env.job["id"]]["status"] == "finishing"
    assert any(entry.get("job") == env.job["id"] for entry in cj._busy_read().values())
    assert env.reports == []


@pytest.mark.parametrize("controller,child", [
    ("active", "dead"), ("unknown", "dead"),
    ("dead", "active"), ("dead", "unknown"),
])
def test_record_age_cannot_prove_controller_or_child_exit(stopped_env, monkeypatch, controller, child):
    env = stopped_env
    states = {101: controller, 202: child}
    monkeypatch.setattr(ch, "process_state", lambda pid, birth, completed_at=None: states[pid])

    assert ch.orphaned_finalizer(env.job) is False
    assert ch.settle_stopped_finalizer(env.cdir, env.job) is None
    assert cj.read_jobs(env.cdir)[env.job["id"]]["status"] == "finishing"
    assert env.reports == []


def test_verified_controller_and_contained_child_exit_allow_settlement(stopped_env, monkeypatch):
    env = stopped_env
    monkeypatch.setattr(ch, "process_state", lambda pid, birth, completed_at=None: "dead")

    assert ch.orphaned_finalizer(env.job) is True
    stopped = ch.settle_stopped_finalizer(env.cdir, env.job)
    assert stopped["status"] == "stopped"
    assert len(env.reports) == 1
    assert env.product.exists()
