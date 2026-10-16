"""Observe real bounded command children without imposing a runtime deadline."""

import copy
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from steward_cockpit import code_job_handoff as ch
from steward_cockpit import code_jobs as cj


def test_unreadable_registry_never_overwrites_saved_jobs(tmp_path):
    registry = tmp_path / cj.JOBS_FILE
    registry.parent.mkdir()
    original = b'{"saved-job":'
    registry.write_bytes(original)
    with pytest.raises(ValueError):
        cj._write_job(tmp_path, {"id": "new-job", "status": "running"})
    assert registry.read_bytes() == original


@pytest.fixture
def command_env(tmp_path, monkeypatch):
    cdir = tmp_path / "cockpit"
    repo = tmp_path / "repo"
    tree = tmp_path / "tree"
    for directory in (cdir, repo, tree):
        directory.mkdir()
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.setattr(cj, "COMMAND_OBSERVE_S", 0.01)
    job = {
        "id": "j", "status": "finishing", "attempt": 1,
        "phase": "checking", "steward_dir": str(cdir), "repo": str(repo),
        "worktree": str(tree), "started": "2026-10-10 00:00:00",
        "worker_completed_at": 1,
    }
    cj._write_job(cdir, job)
    runs = []
    threads = []
    observations = []
    original_spawn = cj._popen_contained
    original_transition = cj._transition

    def capture_spawn(*args, **kwargs):
        run = original_spawn(*args, **kwargs)
        runs.append(run)
        return run

    def capture_transition(*args, **kwargs):
        result = original_transition(*args, **kwargs)
        if isinstance(kwargs.get("command"), dict):
            observations.append(copy.deepcopy(kwargs["command"]))
        return result

    monkeypatch.setattr(cj, "_popen_contained", capture_spawn)
    monkeypatch.setattr(cj, "_transition", capture_transition)

    def start(script, **kwargs):
        outcome = {}

        def invoke():
            try:
                outcome["result"] = cj.run_command(
                    job, tree, [sys.executable, "-u", "-c", script], **kwargs,
                )
            except BaseException as exc:
                outcome["error"] = exc

        thread = threading.Thread(target=invoke, daemon=True)
        threads.append(thread)
        thread.start()
        return thread, outcome

    env = SimpleNamespace(
        cdir=cdir, repo=repo, tree=tree, job=job, runs=runs,
        observations=observations, start=start,
    )
    try:
        yield env
    finally:
        # Always terminate the contained process tree, even when a test assertion
        # or the normal command cancellation path failed.
        cleanup_errors = []
        try:
            original_transition(cdir, "j", ("finishing",), stop_requested="test cleanup")
        except Exception as exc:
            cleanup_errors.append(exc)
        for run in runs:
            try:
                run.end(wait_s=5)
            except Exception as exc:
                cleanup_errors.append(exc)
        for thread in threads:
            thread.join(timeout=5)
        assert not any(thread.is_alive() for thread in threads), "Command runner survived contained cleanup"
        assert not cleanup_errors, f"Command cleanup failed: {cleanup_errors}"


def _completed(thread, outcome, timeout=10):
    thread.join(timeout=timeout)
    assert not thread.is_alive(), "Observed command did not complete within the test's safety bound"
    if "error" in outcome:
        raise outcome["error"]
    return outcome["result"]


def test_quiet_command_outlives_observation_ticks_and_persists_output(command_env):
    env = command_env
    started = time.monotonic()
    thread, outcome = env.start(
        "import time; print('started', flush=True); time.sleep(0.25); print('finished', flush=True)"
    )
    result = _completed(thread, outcome)
    elapsed = time.monotonic() - started

    assert result.returncode == 0
    assert "finished" in result.stdout
    assert elapsed >= 0.20  # Many 10 ms observations are not a command deadline.
    saved = cj.read_jobs(env.cdir)["j"]
    assert saved["status"] == "finishing"
    command = saved["command"]
    assert command["state"] == "completed"
    assert command["returncode"] == 0
    assert command["output_bytes"] > 0
    log = Path(command["log"])
    assert not log.resolve().is_relative_to(env.tree.resolve())
    assert "started" in log.read_text(encoding="utf-8")
    assert any(row.get("state") == "active" and row.get("output_bytes", 0) > 0
               for row in env.observations)


def test_explicit_stop_ends_child_and_preserves_work(command_env):
    env = command_env
    artifact = env.tree / "preserved-product.txt"
    thread, outcome = env.start(
        "import os, pathlib, time\n"
        "pathlib.Path('preserved-product.txt').write_text('retained work', encoding='utf-8')\n"
        "print('child ' + str(os.getpid()), flush=True)\n"
        "while True:\n"
        "    print('still working', flush=True)\n"
        "    time.sleep(0.02)\n"
    )
    deadline = time.monotonic() + 8
    command = {}
    while time.monotonic() < deadline and thread.is_alive():
        command = cj.read_jobs(env.cdir)["j"].get("command") or {}
        if artifact.exists() and command.get("pid") and command.get("output_bytes", 0) > 0:
            break
        time.sleep(0.01)
    assert artifact.exists(), "The child must produce work before cancellation"
    assert command.get("pid"), "Command identity must be recorded before cancellation"

    stopped_at = time.monotonic()
    cj._transition(env.cdir, "j", ("finishing",), stop_requested="explicit test stop")
    result = _completed(thread, outcome, timeout=8)

    assert result.returncode == 130
    assert time.monotonic() - stopped_at < 8
    assert artifact.read_text(encoding="utf-8") == "retained work"
    saved = cj.read_jobs(env.cdir)["j"]["command"]
    assert saved["cancelled"] is True
    assert ch.process_state(command["pid"], command.get("birth")) in {"dead", "completed"}


def test_large_output_keeps_full_log_and_returns_bounded_tail(command_env):
    env = command_env
    thread, outcome = env.start(
        "import sys; sys.stdout.write('0123456789' * 65536 + '\\nTAIL-MARKER\\n'); sys.stdout.flush()",
        output_limit=4096,
    )
    result = _completed(thread, outcome)

    assert result.returncode == 0
    assert "TAIL-MARKER" in result.stdout
    assert len(result.stdout.encode("utf-8")) <= 4096
    saved = cj.read_jobs(env.cdir)["j"]["command"]
    log = Path(saved["log"])
    assert log.stat().st_size > 655360
    assert saved["output_bytes"] == log.stat().st_size
    assert log.read_text(encoding="utf-8").endswith("TAIL-MARKER\n")


def test_active_check_remains_live_after_worker_completed(command_env, monkeypatch):
    env = command_env
    job = dict(env.job)
    job["worker_completed_at"] = 1
    job["command"] = {
        "phase": "checking", "state": "active", "pid": 4242,
        "birth": "test-birth", "started_at": 100, "activity_at": 102,
        "output_bytes": 14, "log": str(env.cdir / "check.log"),
    }
    monkeypatch.setattr(ch, "process_state", lambda pid, birth, completed_at=None: "active")

    observed = ch.supervise(job, now=105)

    assert observed["liveness"] == "active"


def test_controller_between_commands_is_observed_by_its_own_identity(command_env, monkeypatch):
    env = command_env
    job = {**env.job, "finalizer_active": True, "phase_at": 100,
           "claim": {"pid": 99, "birth": 90},
           "command": {"state": "completed", "phase": "checking", "ended_at": 101, "log": "check.log"}}
    monkeypatch.setattr(ch, "process_state", lambda pid, birth, completed_at=None: "active" if (pid, birth) == (99, 90) else "unknown")
    observed = ch.supervise(job, now=102)
    assert observed["liveness"] == "active" and observed["state"] == "progressing"
