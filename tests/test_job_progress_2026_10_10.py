"""Progress evidence is descriptive and never authorizes a deadline kill."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from steward_cockpit.code_job_progress import note_event, sample


def job(**changes):
    value = {"attempt": 1, "phase": "coder", "phase_at": 10.0, "status": "running"}
    value.update(changes)
    return value


def test_productive_job_survives_all_former_deadlines_and_sampling_is_pure():
    original = job()
    worker = {"state": "active", "last_activity": 30000.0, "progress_at": 29990.0, "progress_token": 9}
    before = deepcopy((original, worker))
    result = sample(original, worker, now=30001)
    assert result["state"] == "progressing"
    assert result["liveness"] == "active"
    assert "kill" not in result["action"] and "restart" not in result["action"]
    assert (original, worker) == before


def test_quiet_live_job_requires_inspection_not_a_hang_verdict():
    result = sample(job(), {"state": "active", "last_activity": 20}, now=10000)
    assert result["state"] == "needs_inspection"
    assert result["liveness"] == "active"
    assert "does not establish a hang" in result["action"]


def test_heartbeat_does_not_renew_checkpoint_progress_after_reload():
    current = job()
    native = {"observed_at": 100, "progress_token": "checkpoint-1", "progress_at": 80}
    first = sample(current, {"state": "active"}, native, now=100)
    current["supervision"] = deepcopy(first)
    native.update(observed_at=1000, progress_at=1000)
    second = sample(current, {"state": "active"}, native, now=1000)
    assert second["progress_at"] == 80
    assert second["activity_at"] == 1000
    assert second["state"] == "needs_inspection"
    assert "Activity continues" in second["reason"]


def test_worker_progress_time_survives_repeated_observation():
    current = job()
    worker = {"state": "active", "last_activity": 90, "progress_at": 80}
    current["supervision"] = sample(current, worker, now=100)
    worker["last_activity"] = 1000
    result = sample(current, worker, now=1000)
    assert result["progress_at"] == 80
    assert result["state"] == "needs_inspection"


def test_explicit_wait_is_preserved_and_can_be_cleared():
    current = job()
    first = sample(current, {"state": "active", "waiting": "Approval needed for an external action"}, now=10000)
    assert first["state"] == "waiting"
    assert first["reason"] == "Approval needed for an external action"
    current["supervision"] = first
    assert sample(current, {"state": "active"}, now=20000)["state"] == "waiting"
    cleared = sample(current, {"state": "active", "waiting": "", "last_activity": 20000}, now=20000)
    assert cleared["state"] == "needs_inspection"  # resuming activity is not proof the task advanced
    assert not cleared["waiting"]


def test_phase_advance_clears_prior_wait_unless_reported_again():
    current = job()
    current["supervision"] = sample(current, {"state": "active", "waiting": "Coder needs approval"}, now=100)
    current.update(phase="check", phase_at=200)
    result = sample(current, {"state": "active"}, now=210)
    assert result["state"] == "progressing"
    assert not result["waiting"]
    explicit = sample(current, {"state": "active", "waiting": "Check needs its dependency"}, now=210)
    assert explicit["state"] == "waiting"
    assert explicit["waiting"] == "Check needs its dependency"


def test_resumed_foreman_checkpoint_explicitly_clears_pause():
    current = job()
    current["supervision"] = sample(current, {"state": "active"}, {
        "observed_at": 100, "progress_token": "checkpoint-1", "progress_at": 90,
        "waiting": "Foreman paused for review",
    }, now=100)
    assert current["supervision"]["state"] == "waiting"
    resumed = sample(current, {"state": "active"}, {
        "observed_at": 200, "progress_token": "checkpoint-2", "progress_at": 195,
        "waiting": "",
    }, now=200)
    assert resumed["state"] == "progressing"
    assert not resumed["waiting"]


@pytest.mark.parametrize(("liveness", "expected"), [("unknown", "visibility_lost"), ("dead", "dead")])
def test_missing_identity_and_verified_exit_are_distinct(liveness, expected):
    result = sample(job(), {"state": liveness, "last_activity": 9999}, now=10000)
    assert result["state"] == expected
    assert result["liveness"] == liveness


def test_repeated_failure_needs_attention_and_advancement_clears_it():
    current = job()
    current["supervision"] = sample(current, {"state": "active"}, now=20)
    worker = {"state": "active", "last_activity": 100, "error": "disk full", "repeat_errors": 3}
    failed = sample(current, worker, now=100)
    assert failed["state"] == "needs_attention"
    assert "disk full" in failed["reason"]
    current["supervision"] = failed
    recovered = sample(current, worker, {"progress_token": "checkpoint-2", "progress_at": 110}, now=110)
    assert recovered["state"] == "progressing"
    assert recovered["repeat_errors"] == 0
    assert recovered["error"] == ""


def test_repolling_one_error_does_not_invent_repeated_failures():
    current = job()
    current["supervision"] = sample(current, {"state": "active"}, now=20)
    worker = {"state": "active", "error": "one tool failure", "last_activity": 30}
    for now in (30, 40, 50, 60):
        current["supervision"] = sample(current, worker, now=now)
    assert current["supervision"]["repeat_errors"] == 1
    assert current["supervision"]["state"] != "needs_attention"


def test_first_observation_does_not_erase_new_failures_with_older_progress():
    worker = {
        "state": "active", "last_activity": 100, "progress_at": 50,
        "error": "disk full", "repeat_errors": 3,
    }
    result = sample(job(), worker, now=100)
    assert result["state"] == "needs_attention"
    assert result["repeat_errors"] == 3


def test_attempt_reset_discards_previous_suspicion_and_progress():
    current = job(attempt=2, phase_at=500)
    current["supervision"] = {
        "attempt": 1, "phase": "review", "progress_at": 400,
        "progress_token": "old", "error": "old failure", "repeat_errors": 5,
        "waiting": "old wait", "activity_at": 450,
    }
    result = sample(current, {"state": "active"}, now=510)
    assert result["attempt"] == 2
    assert result["progress_at"] == 500
    assert result["progress_token"] is None
    assert result["error"] == result["waiting"] == ""
    assert result["repeat_errors"] == 0


def test_real_phase_transition_is_progress_and_completed_worker_is_not_job_success():
    current = job()
    current["supervision"] = sample(current, {"state": "active"}, now=20)
    current.update(phase="check", phase_at=1000)
    result = sample(current, {"state": "active"}, now=1010)
    assert result["progress_at"] == 1000
    assert result["state"] == "progressing"
    result = sample(current, {"state": "completed"}, now=1010)
    assert result["state"] == "observing"


@pytest.mark.parametrize(
    ("status", "landed", "expected"),
    [("done", True, "complete"), ("done", False, "kept"), ("failed", False, "failed"), ("stopped", False, "stopped")],
)
def test_terminal_outcomes_override_old_waits(status, landed, expected):
    result = sample(job(status=status, landed=landed), {"state": "unknown", "waiting": "old wait"}, now=10000)
    assert result["state"] == expected


def tool_use(engine, identity, name, now=100, **tool_input):
    note_event(engine, {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": identity, "name": name, "input": tool_input},
    ]}}, now=now)


def tool_result(engine, identity, now=110, error=False, content="done"):
    note_event(engine, {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": identity, "is_error": error, "content": content},
    ]}}, now=now)


@pytest.fixture
def engine(tmp_path):
    return SimpleNamespace(code_job={"worktree": str(tmp_path), "work_dir": "", "outputs": ["report.md"]})


def test_only_successful_write_result_establishes_progress(engine):
    note_event(engine, {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {
        "type": "text_delta", "text": "I wrote the file and am done.",
    }}}, now=90)
    assert engine.job_observation["last_activity"] == 90
    assert "progress_at" not in engine.job_observation
    tool_use(engine, "r", "Read", file_path="report.md")
    tool_result(engine, "r")
    assert "progress_at" not in engine.job_observation
    tool_use(engine, "w", "Write", now=120, file_path="report.md")
    assert engine.job_observation["pending_tools"]["w"] == {"id": "w", "name": "Write", "qualified": True}
    assert "progress_at" not in engine.job_observation
    tool_result(engine, "w", now=130)
    assert engine.job_observation["progress_at"] == 130
    assert engine.job_observation["progress_token"] == 1
    tool_result(engine, "w", now=140)
    assert engine.job_observation["progress_token"] == 1


@pytest.mark.parametrize("path", [".ecgberht/strip.json", "foreman.config.json", ".foreman/status.json", "foreman-checkpoint.json"])
def test_runtime_and_never_landed_writes_do_not_count_even_when_declared(engine, path):
    engine.code_job["outputs"] = [path]
    tool_use(engine, "runtime", "Write", file_path=path)
    tool_result(engine, "runtime")
    assert "progress_at" not in engine.job_observation
    assert engine.job_observation["last_activity"] == 110


@pytest.mark.parametrize("path", ["notes.md", "worker.log", "scratch.tmp", "scratch.temp"])
def test_undeclared_documents_and_scratch_writes_are_activity_only(engine, path):
    tool_use(engine, "scratch", "Write", file_path=path)
    tool_result(engine, "scratch")
    assert "progress_at" not in engine.job_observation


def test_out_of_scope_and_outside_worktree_writes_do_not_count(engine, tmp_path):
    (tmp_path / "src").mkdir()
    engine.code_job["work_dir"] = "src"
    for identity, path in [("scope", "elsewhere.py"), ("escape", str(tmp_path.parent / "outside.py"))]:
        tool_use(engine, identity, "Edit", file_path=path)
        tool_result(engine, identity)
    assert "progress_at" not in engine.job_observation
    tool_use(engine, "source", "Edit", now=120, file_path="src/main.py")
    tool_result(engine, "source", now=130)
    assert engine.job_observation["progress_token"] == 1


def test_source_and_declared_document_writes_count_as_observed_progress(engine):
    for identity, path in [("source", "main.py"), ("document", "report.md")]:
        tool_use(engine, identity, "Write", file_path=path)
        tool_result(engine, identity)
    assert engine.job_observation["progress_token"] == 2
    assert "state" not in engine.job_observation


def test_explicit_nonruntime_log_output_can_count(engine):
    engine.code_job["outputs"] = ["result.log"]
    tool_use(engine, "output", "Write", file_path="result.log")
    tool_result(engine, "output")
    assert engine.job_observation["progress_token"] == 1


@pytest.mark.parametrize("missing", ["binding", "directory"])
def test_missing_binding_or_worktree_gives_no_progress_credit(tmp_path, missing):
    engine = SimpleNamespace()
    if missing == "directory":
        engine.code_job = {"worktree": str(tmp_path / "missing"), "work_dir": "", "outputs": ["report.md"]}
    tool_use(engine, "write", "Write", file_path="report.md")
    tool_result(engine, "write")
    assert "progress_at" not in engine.job_observation


def test_completed_file_change_requires_at_least_one_qualifying_path(engine):
    tool_use(engine, "ignored", "file_change", paths=[".ecgberht/strip.json", "scratch.tmp", "notes.md"], status="completed")
    assert "progress_at" not in engine.job_observation
    tool_use(engine, "source", "file_change", paths=["scratch.tmp", "main.py"], status="completed")
    assert engine.job_observation["progress_token"] == 1
    note_event(engine, {"type": "item.completed", "item": {
        "type": "file_change", "id": "direct", "status": "completed", "changes": [{"path": "another.py"}],
    }}, now=120)
    assert engine.job_observation["progress_token"] == 2


def test_event_errors_are_normalized_bounded_counted_and_cleared_by_write(engine):
    for index in range(3):
        tool_use(engine, str(index), "Write", now=100 + index, file_path="report.md")
        tool_result(engine, str(index), now=110 + index, error=True, content=" disk\n full " + "x" * 500)
    assert engine.job_observation["repeat_errors"] == 3
    assert len(engine.job_observation["error"]) == 300
    assert engine.job_observation["error"].startswith("disk full ")
    assert "progress_at" not in engine.job_observation
    tool_use(engine, "read", "Read", now=120)
    tool_result(engine, "read", now=121)
    assert engine.job_observation["repeat_errors"] == 3
    tool_use(engine, "edit", "Edit", now=130, file_path="report.md")
    tool_result(engine, "edit", now=140)
    assert engine.job_observation["repeat_errors"] == 0
    assert not engine.job_observation["error"]
    assert engine.job_observation["progress_at"] == 140


def test_pending_tools_are_bounded_and_completed_file_changes_are_counted_once(engine):
    for index in range(70):
        tool_use(engine, str(index), "Read", now=index, content="x" * 10000)
    assert len(engine.job_observation["pending_tools"]) == 64
    assert "0" not in engine.job_observation["pending_tools"]
    assert all("input" not in item for item in engine.job_observation["pending_tools"].values())
    tool_use(engine, "change", "file_change", now=100, paths=["report.md"], status="completed")
    assert engine.job_observation["progress_token"] == 1
    tool_use(engine, "change", "file_change", now=110, paths=["report.md"], status="completed")
    assert engine.job_observation["progress_token"] == 1
    assert len(engine.job_observation["pending_tools"]) <= 64


def test_replayed_error_result_does_not_inflate_failure_count_and_ids_are_bounded(engine):
    tool_use(engine, "failure-1", "Write")
    for now in (110, 120, 130):
        tool_result(engine, "failure-1", now=now, error=True, content="disk full")
    assert engine.job_observation["repeat_errors"] == 1
    for identity in ("failure-2", "failure-3"):
        tool_use(engine, identity, "Write", now=140)
        tool_result(engine, identity, now=150, error=True, content="disk full")
    assert engine.job_observation["repeat_errors"] == 3
    for index in range(70):
        identity = f"read-{index}"
        tool_use(engine, identity, "Read", now=200 + index)
        tool_result(engine, identity, now=300 + index)
    assert len(engine.job_observation["completed_results"]) == 64
    assert engine.job_observation["repeat_errors"] == 3


def test_only_explicit_provider_wait_changes_wait_state(engine):
    note_event(engine, {"type": "text_delta", "text": "Please approve this; waiting for permission."}, now=100)
    assert not engine.job_observation.get("waiting")
    note_event(engine, {"type": "job_wait", "reason": "Provider requests approval"}, now=110)
    assert engine.job_observation["waiting"] == "Provider requests approval"
    note_event(engine, {"type": "job_wait", "reason": ""}, now=120)
    assert not engine.job_observation["waiting"]
