"""Wave 4 — cancel via tree-kill + liveness/startup reconciliation.

AC3: a running job tree (parent + spawned child) cancelled via taskkill /T /F is
     reaped with NO orphan and status → cancelled.
AC4: a job whose process dies → liveness poll / startup reconciliation sets
     status → interrupted.

NO live ``claude`` — everything goes through ANCHOR_RUNNER_CMD → fake_claude.py.
All spawned processes are reaped so the suite leaves no leaked python procs.
"""
import importlib
import os
import subprocess
import time
from types import SimpleNamespace
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()


@pytest.fixture
def runner(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    import paths
    importlib.reload(paths)
    import job_runner
    importlib.reload(job_runner)
    yield job_runner
    job_runner._reset_live_table_for_tests()


def _pid_alive(pid):
    if os.name == "nt":
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {int(pid)}", "/NH"],
            capture_output=True, text=True,
        )
        return str(int(pid)) in (out.stdout or "")
    try:
        os.kill(int(pid), 0)
    except OSError:
        return False
    return True


def test_ac3_cancel_tree_kill_no_orphan(runner, tmp_path):
    child_pid_file = tmp_path / "child.pid"
    rec = runner.launch(
        "build",
        extra_args=[
            "--lines", "1",
            "--spawn-child",
            "--child-pid-file", child_pid_file.as_posix(),
            "--sleep", "60",
        ],
    )
    jid = rec["job_id"]
    parent_pid = rec["pid"]

    # Wait for the grandchild to be spawned (its PID written to the file).
    deadline = time.monotonic() + 15
    while not child_pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert child_pid_file.exists(), "fake runner never spawned a child"
    child_pid = int(child_pid_file.read_text().strip())

    assert _pid_alive(parent_pid)
    assert _pid_alive(child_pid)

    final = runner.cancel(jid)
    assert final["status"] == runner.STATUS_CANCELLED

    # Give the OS a moment to fully reap the tree.
    deadline = time.monotonic() + 15
    while (_pid_alive(parent_pid) or _pid_alive(child_pid)) and \
            time.monotonic() < deadline:
        time.sleep(0.1)

    assert not _pid_alive(parent_pid), "parent process orphaned after cancel"
    assert not _pid_alive(child_pid), "GRANDCHILD orphaned after tree-kill"


def test_ac3_cancel_already_gone_no_crash(runner):
    rec = runner.launch("research", extra_args=["--lines", "1", "--exit-code", "0"])
    jid = rec["job_id"]
    before = runner.wait(jid, timeout=30)  # let it finish naturally first
    # Cancelling an already-terminal job is idempotent: natural completion is
    # historical truth and must never be rewritten as a user cancellation.
    out = runner.cancel(jid)
    assert out is not None
    assert out == before
    assert out["status"] == runner.STATUS_DONE
    assert runner.load_record(jid) == before


def test_ac3_cancel_unknown_job(runner):
    assert runner.cancel("does-not-exist") is None


def test_cancel_fails_closed_on_persisted_pid_creation_time_mismatch(
        runner, monkeypatch):
    job_id = "pid-recycle-mismatch"
    runner._write_record({
        "job_id": job_id,
        "pid": 424242,
        "proc_create_time": 100.0,
        "status": runner.STATUS_RUNNING,
    })
    import proc_probe
    monkeypatch.setattr(runner, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(
        proc_probe, "probe_status",
        lambda _pid: (proc_probe.PROBE_RUNNING, 200.0, "other.exe"),
    )
    monkeypatch.setattr(proc_probe, "pid_alive_via_enum", lambda _pid: True)

    def forbidden_kill(*_args, **_kwargs):
        raise AssertionError("recycled PID must never be killed")

    monkeypatch.setattr(runner, "_tree_kill", forbidden_kill)
    out = runner.cancel(job_id)

    assert out["status"] == runner.STATUS_RUNNING
    assert out["cancel_succeeded"] is False
    assert out["tree_kill_verified"] is False
    assert out["failure_reason"] == "cancel-pid-identity-unverified"


def test_tree_kill_rejects_nonzero_taskkill_exit(runner, monkeypatch):
    class RunningProc:
        pid = 515151

        @staticmethod
        def poll():
            return None

        @staticmethod
        def wait(timeout=0):
            raise subprocess.TimeoutExpired("fake", timeout)

    live = SimpleNamespace(proc=RunningProc(), _h_job=None)
    monkeypatch.setattr(runner, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(
        runner.subprocess, "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1),
    )

    assert runner._tree_kill(515151, live=live, expected_create_time=1.0) is False


def test_cancel_does_not_claim_success_when_reader_drain_is_unverified(
        runner, monkeypatch):
    class RunningProc:
        pid = 616161

        @staticmethod
        def poll():
            return None

        @staticmethod
        def wait(timeout=0):
            raise subprocess.TimeoutExpired("fake", timeout)

    class NeverDrains:
        @staticmethod
        def wait(timeout=0):
            return False

    job_id = "drain-unverified"
    runner._write_record({
        "job_id": job_id,
        "pid": RunningProc.pid,
        "proc_create_time": 100.0,
        "status": runner.STATUS_RUNNING,
    })
    live = SimpleNamespace(
        proc=RunningProc(), done=NeverDrains(), _h_job=None,
        _cancel_requested=False,
    )
    with runner._LIVE_LOCK:
        runner._LIVE[job_id] = live
    monkeypatch.setattr(runner, "_tree_kill", lambda *_args, **_kwargs: True)

    out = runner.cancel(job_id)

    assert out["status"] == runner.STATUS_RUNNING
    assert out["cancel_succeeded"] is False
    assert out["tree_kill_verified"] is False
    assert out["failure_reason"] == "cancel-reader-drain-unverified"
    assert live._cancel_requested is False


def test_cancel_finalize_job_handle_handoff_is_single_owner_and_not_tree_proof(
        runner, monkeypatch):
    class ExitedProc:
        pid = 717171

        @staticmethod
        def poll():
            return 1

        @staticmethod
        def wait(timeout=0):
            return 1

    job_id = "job-handle-handoff"
    runner._write_record({
        "job_id": job_id,
        "pid": ExitedProc.pid,
        "status": runner.STATUS_RUNNING,
        "backend": runner.BACKEND_CLAUDE,
    })
    live = SimpleNamespace(
        proc=ExitedProc(), done=SimpleNamespace(wait=lambda timeout=0: True),
        _h_job="owned-job-handle", _cancel_requested=True,
    )
    with runner._LIVE_LOCK:
        runner._LIVE[job_id] = live

    import proc_probe
    closed = []
    monkeypatch.setattr(proc_probe, "close_handle", lambda handle: closed.append(handle))

    # Finalization observes the pending cancel and must leave the handle for the
    # cancellation owner instead of racing a close.
    runner._finalize(job_id, 1, None)
    assert closed == []
    assert live._h_job == "owned-job-handle"

    monkeypatch.setattr(runner, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(
        runner.subprocess, "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1),
    )
    # _tree_kill detaches/closes exactly once. Because taskkill failed and
    # CloseHandle exposes no success bit, an exited root is not tree proof.
    assert runner._tree_kill(ExitedProc.pid, live=live) is False
    assert closed == ["owned-job-handle"]
    assert live._h_job is None


def test_ac4_liveness_marks_dead_running_job_interrupted(runner):
    # Launch a quick job, let it finish, then forge its record back to "running"
    # with a dead PID to simulate a process that died without finalizing.
    rec = runner.launch("plan", extra_args=["--lines", "1"])
    jid = rec["job_id"]
    runner.wait(jid, timeout=30)

    # Forge: status=running, pid=an impossible/dead pid; drop the live handle so
    # the reconciler treats it as a stale persisted job.
    dead_pid = 999999  # not a real running PID
    runner._update_record(jid, status=runner.STATUS_RUNNING, pid=dead_pid)
    runner._reset_live_table_for_tests()

    out = runner.liveness_check(jid)
    assert out["status"] == runner.STATUS_INTERRUPTED


def test_ac4_startup_reconciliation(runner):
    # Two finished jobs forged back to "running" with dead pids → both become
    # interrupted on startup reconciliation.
    j1 = runner.launch("research", extra_args=["--lines", "1"])["job_id"]
    j2 = runner.launch("build", extra_args=["--lines", "1"])["job_id"]
    runner.wait(j1, timeout=30)
    runner.wait(j2, timeout=30)

    runner._update_record(j1, status=runner.STATUS_RUNNING, pid=999998)
    runner._update_record(j2, status=runner.STATUS_RUNNING, pid=999997)
    runner._reset_live_table_for_tests()

    changed = runner.reconcile_on_startup()
    assert set(changed) == {j1, j2}
    assert runner.load_record(j1)["status"] == runner.STATUS_INTERRUPTED
    assert runner.load_record(j2)["status"] == runner.STATUS_INTERRUPTED


def test_ac4_liveness_leaves_done_job_alone(runner):
    rec = runner.launch("research", extra_args=["--lines", "1"])
    jid = rec["job_id"]
    runner.wait(jid, timeout=30)
    out = runner.liveness_check(jid)
    assert out["status"] == runner.STATUS_DONE  # untouched
