"""Terminal-path orchestration shares producer identity and preserves failures."""

from pathlib import Path
import threading
from unittest.mock import Mock

import pytest

from steward_cockpit import producer_handoff


@pytest.mark.parametrize("status", ["done", "failed", "cancelled", "interrupted"])
def test_terminal_statuses_use_the_same_job_identity(monkeypatch, status):
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    result = {"ok": True, "handoff": {"status": "pending_steward_review"}}
    record = Mock(return_value=result)
    monkeypatch.setattr(producer_handoff, "record_handoff", record)
    context = {"step_id": "foundation", "round": 2}

    assert producer_handoff.record_terminal({
        "job_id": "job-attempt-42",
        "status": status,
        "refinement_dir": "campaign",
        "effort_dir": "other-effort",
        "folder_path": "other-project",
        "refinement_context": context,
    }) is result
    record.assert_called_once_with(
        "campaign",
        producer_kind="job",
        producer_id="job-attempt-42",
        source_ref="Anchor job job-attempt-42",
        context=context,
        terminal=status,
    )


@pytest.mark.parametrize("status", ["running", "queued", "waiting", None])
def test_nonterminal_status_does_not_record(monkeypatch, status):
    record = Mock()
    monkeypatch.setattr(producer_handoff, "record_handoff", record)
    assert producer_handoff.record_terminal({
        "job_id": "job-attempt-42", "status": status, "folder_path": "campaign",
    }) is None
    record.assert_not_called()


def test_missing_campaign_does_not_search_parents_or_fallback(monkeypatch):
    inspected = []

    def is_file(path):
        inspected.append(path)
        return False

    monkeypatch.setattr(Path, "is_file", is_file)
    record = Mock()
    monkeypatch.setattr(producer_handoff, "record_handoff", record)
    assert producer_handoff.record_terminal({
        "job_id": "job-attempt-42",
        "status": "done",
        "refinement_dir": "campaign/child",
        "effort_dir": "campaign",
    }) is None
    assert inspected == [Path("campaign/child") / "roadmap.json"]
    record.assert_not_called()


@pytest.mark.parametrize("root_key", ["effort_dir", "folder_path"])
def test_terminal_uses_available_exact_root(monkeypatch, root_key):
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    record = Mock(return_value={"ok": True})
    monkeypatch.setattr(producer_handoff, "record_handoff", record)
    producer_handoff.record_terminal({
        "job_id": "job-attempt-42", "status": "failed", root_key: "campaign",
    })
    assert record.call_args.args == ("campaign",)


def test_terminal_preserves_structured_failure(monkeypatch):
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    failure = {"ok": False, "error": "ledger-unavailable"}
    monkeypatch.setattr(producer_handoff, "record_handoff", Mock(return_value=failure))
    assert producer_handoff.record_terminal({
        "job_id": "job-attempt-42", "status": "cancelled", "folder_path": "campaign",
    }) is failure


@pytest.mark.parametrize("unrecorded", [
    {"ok": True, "skipped": True},
    {"ok": True, "managed": False},
])
def test_terminal_does_not_report_an_unrecorded_handoff_as_success(monkeypatch, unrecorded):
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    monkeypatch.setattr(producer_handoff, "record_handoff", Mock(return_value=unrecorded))
    result = producer_handoff.record_terminal({
        "job_id": "job-attempt-42", "status": "done", "folder_path": "campaign",
    })
    assert result["ok"] is False
    assert result["error"] == "campaign-not-managed"
    assert result["skipped"] is True
    assert unrecorded["ok"] is True


def test_terminal_normalizes_unexpected_exception(monkeypatch):
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    monkeypatch.setattr(producer_handoff, "record_handoff", Mock(side_effect=RuntimeError("ledger unavailable")))
    result = producer_handoff.record_terminal({
        "job_id": "job-attempt-42", "status": "interrupted", "folder_path": "campaign",
    })
    assert result["ok"] is False
    assert result["error"] == "job-handoff-failed"
    assert "ledger unavailable" in result["message"]


def test_capture_dispatch_uses_exact_root(monkeypatch):
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    context = {"step_id": "foundation", "round": 2}
    capture = Mock(return_value=context)
    monkeypatch.setattr(producer_handoff, "capture_context", capture)
    assert producer_handoff.capture_dispatch("campaign") is context
    capture.assert_called_once_with("campaign")


def test_capture_dispatch_without_campaign_is_skipped(monkeypatch):
    monkeypatch.setattr(Path, "is_file", lambda self: False)
    capture = Mock()
    monkeypatch.setattr(producer_handoff, "capture_context", capture)
    assert producer_handoff.capture_dispatch("campaign/child") is None
    assert producer_handoff.capture_dispatch(None) is None
    capture.assert_not_called()


def test_capture_dispatch_preserves_structured_failure(monkeypatch):
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    failure = {"ok": False, "error": "context-unavailable"}
    monkeypatch.setattr(producer_handoff, "capture_context", Mock(return_value=failure))
    assert producer_handoff.capture_dispatch("campaign") is failure


def test_capture_dispatch_normalizes_unexpected_exception(monkeypatch):
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    monkeypatch.setattr(producer_handoff, "capture_context", Mock(side_effect=RuntimeError("context unavailable")))
    result = producer_handoff.capture_dispatch("campaign")
    assert result["ok"] is False
    assert result["error"] == "dispatch-context-failed"
    assert "context unavailable" in result["message"]


def test_startup_does_not_backfill_historical_terminal_jobs(monkeypatch):
    import job_runner

    historical = {
        "job_id": "historical-job-42", "status": "done", "folder_path": "campaign",
    }
    record = Mock()
    monkeypatch.setattr(job_runner, "list_records", lambda: [historical])
    monkeypatch.setattr(job_runner, "_record_terminal_handoff", record)
    monkeypatch.setattr(job_runner, "gc_old_job_logs", lambda: None)

    assert job_runner.reconcile_on_startup() == []
    record.assert_not_called()
    assert "refinement_handoff" not in historical


@pytest.mark.parametrize("prior_attempt", [
    {"refinement_context": None},
    {"refinement_handoff": None},
    {"refinement_context": {"step_id": "foundation", "round": 2}},
    {"refinement_handoff": {"ok": False, "error": "ledger-unavailable"}},
    {"refinement_handoff": {"ok": True, "skipped": True, "reason": "unmanaged"}},
    {"refinement_handoff": {"ok": True, "managed": False}},
])
def test_startup_retries_attempted_unrecorded_handoffs_with_same_job_id(monkeypatch, prior_attempt):
    import job_runner

    rec = {
        "job_id": "post-code-job-42", "status": "done", "folder_path": "campaign",
        **prior_attempt,
    }
    attempts = []

    def record_terminal(attempted_rec):
        attempts.append(attempted_rec["job_id"])
        attempted_rec["refinement_handoff"] = {"ok": True, "handoff": {"id": "recorded"}}

    monkeypatch.setattr(job_runner, "list_records", lambda: [rec])
    monkeypatch.setattr(job_runner, "_record_terminal_handoff", record_terminal)
    monkeypatch.setattr(job_runner, "gc_old_job_logs", lambda: None)

    assert job_runner.reconcile_on_startup() == []
    assert attempts == ["post-code-job-42"]
    assert rec["job_id"] == "post-code-job-42"
    assert job_runner.reconcile_on_startup() == []
    assert attempts == ["post-code-job-42"]


@pytest.mark.parametrize("prior_attempt, should_record", [
    ({}, False),
    ({"refinement_context": None}, True),
])
def test_startup_interrupts_dead_jobs_without_backfilling_historical_outputs(
    monkeypatch, prior_attempt, should_record,
):
    import job_runner

    rec = {
        "job_id": "dead-at-startup-42",
        "status": job_runner.STATUS_RUNNING,
        "pid": 12345,
        **prior_attempt,
    }
    terminal = {**rec, "status": job_runner.STATUS_INTERRUPTED}
    update = Mock(return_value=terminal)
    mirror = Mock()
    record = Mock()
    monkeypatch.setattr(job_runner, "list_records", lambda: [rec])
    monkeypatch.setattr(job_runner, "_LIVE", {})
    monkeypatch.setattr(job_runner, "_pid_alive", lambda pid: False)
    monkeypatch.setattr(job_runner, "_update_record", update)
    monkeypatch.setattr(job_runner, "_mirror_session_status", mirror)
    monkeypatch.setattr(job_runner, "_record_terminal_handoff", record)
    monkeypatch.setattr(job_runner, "gc_old_job_logs", lambda: None)

    assert job_runner.reconcile_on_startup() == ["dead-at-startup-42"]
    update.assert_called_once()
    assert update.call_args.args == ("dead-at-startup-42",)
    assert update.call_args.kwargs["status"] == job_runner.STATUS_INTERRUPTED
    assert "finished_at" in update.call_args.kwargs
    mirror.assert_called_once_with("dead-at-startup-42", job_runner.STATUS_INTERRUPTED)
    if should_record:
        record.assert_called_once_with(terminal)
    else:
        record.assert_not_called()


def test_startup_does_not_retry_a_recorded_handoff(monkeypatch):
    import job_runner

    rec = {
        "job_id": "recorded-job-42",
        "status": "done",
        "refinement_context": {"step_id": "foundation", "round": 2},
        "refinement_handoff": {"ok": True, "handoff": {"id": "recorded"}},
    }
    record = Mock()
    monkeypatch.setattr(job_runner, "list_records", lambda: [rec])
    monkeypatch.setattr(job_runner, "_record_terminal_handoff", record)
    monkeypatch.setattr(job_runner, "gc_old_job_logs", lambda: None)

    assert job_runner.reconcile_on_startup() == []
    record.assert_not_called()


def test_launch_guarded_captures_context_without_holding_write_lock(monkeypatch, tmp_path):
    import job_runner
    import pty_manager

    capturing = threading.Event()
    release_capture = threading.Event()
    acquired_write_lock = threading.Event()
    context = {"step_id": "foundation", "round": 2}
    results = {}
    errors = []
    project_id = "handoff-lock-test"
    lane = "research"
    lane_key = (project_id, lane)

    def capture(cwd):
        assert cwd == str(tmp_path)
        capturing.set()
        if not release_capture.wait(10):
            raise RuntimeError("test did not release dispatch capture")
        return context

    def launch(_lane, **kwargs):
        return {
            "job_id": "unique-handoff-lock-test",
            "refinement_context": kwargs["refinement_context"],
        }

    def launch_in_thread():
        try:
            results["record"] = job_runner.launch_guarded(
                lane=lane,
                project_id=project_id,
                folder_path=str(tmp_path),
                cwd=str(tmp_path),
            )
        except BaseException as exc:
            errors.append(exc)

    def acquire_in_thread():
        with job_runner._paths.WRITE_LOCK:
            acquired_write_lock.set()

    monkeypatch.setattr(producer_handoff, "capture_dispatch", capture)
    monkeypatch.setattr(pty_manager, "count_live_for_spawn_cap", lambda *args, **kwargs: (0, 0, 0, 100))
    monkeypatch.setattr(job_runner, "_gc_lane_slot", lambda *args, **kwargs: None)
    monkeypatch.setattr(job_runner, "_gc_folder_build", lambda *args, **kwargs: None)
    monkeypatch.setattr(job_runner, "launch", launch)
    monkeypatch.setattr(job_runner, "_update_record", lambda *args, **kwargs: {})

    launch_thread = threading.Thread(target=launch_in_thread, daemon=True)
    lock_thread = threading.Thread(target=acquire_in_thread, daemon=True)
    capture_started = False
    progressed_during_capture = False
    try:
        launch_thread.start()
        capture_started = capturing.wait(5)
        if capture_started:
            lock_thread.start()
            progressed_during_capture = acquired_write_lock.wait(5)
    finally:
        release_capture.set()
        launch_thread.join(5)
        if lock_thread.ident is not None:
            lock_thread.join(5)
        cleanup_acquired = job_runner._paths.WRITE_LOCK.acquire(timeout=5)
        if cleanup_acquired:
            try:
                job_runner._ACTIVE_LANE.pop(lane_key, None)
            finally:
                job_runner._paths.WRITE_LOCK.release()

    assert capture_started, f"dispatch capture was not reached: {errors!r}"
    assert progressed_during_capture, "dispatch capture held the shared job write lock"
    assert not launch_thread.is_alive()
    assert not lock_thread.is_alive()
    assert cleanup_acquired, "could not acquire the job write lock for fixture cleanup"
    assert not errors
    assert results["record"]["refinement_context"] is context
def test_metadata_summary_does_not_create_work_handoff(monkeypatch, tmp_path):
    from steward_cockpit import producer_handoff
    (tmp_path / 'roadmap.json').write_text('{}')
    def unexpected(*args, **kwargs):
        raise AssertionError('Summary metadata must not enter the product ledger')
    monkeypatch.setattr(producer_handoff, 'record_handoff', unexpected)
    assert producer_handoff.record_terminal({'status': 'done', 'job_id': 'summary',
        'refinement_dir': str(tmp_path), 'metadata_only': True}) is None
