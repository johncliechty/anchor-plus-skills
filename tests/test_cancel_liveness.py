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
    runner.wait(jid, timeout=30)  # let it finish naturally first
    # Cancelling an already-exited job must not crash; status becomes cancelled.
    out = runner.cancel(jid)
    assert out is not None
    assert out["status"] == runner.STATUS_CANCELLED


def test_ac3_cancel_unknown_job(runner):
    assert runner.cancel("does-not-exist") is None


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
