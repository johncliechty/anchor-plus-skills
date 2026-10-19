"""Behavioral coverage for deferred startup recovery and compact durable receipts."""

from copy import deepcopy
from unittest.mock import Mock

import pytest

import job_runner


@pytest.mark.parametrize("deferred", [True, False])
def test_dead_job_status_recovery_does_not_depend_on_deferred_handoff(monkeypatch, deferred):
    rec = {
        "job_id": "dead-at-startup-42", "status": job_runner.STATUS_RUNNING,
        "pid": 12345, "refinement_context": None,
    }
    terminal = {**rec, "status": job_runner.STATUS_INTERRUPTED}
    update = Mock(return_value=terminal)
    mirror = Mock()
    handoff = Mock()
    monkeypatch.setattr(job_runner, "list_records", lambda: [rec])
    monkeypatch.setattr(job_runner, "_LIVE", {})
    monkeypatch.setattr(job_runner, "_pid_alive", lambda pid: False)
    monkeypatch.setattr(job_runner, "_update_record", update)
    monkeypatch.setattr(job_runner, "_mirror_session_status", mirror)
    monkeypatch.setattr(job_runner, "_record_terminal_handoff", handoff)
    monkeypatch.setattr(job_runner, "gc_old_job_logs", lambda: None)

    result = (job_runner.reconcile_on_startup(defer_handoffs=True)
              if deferred else job_runner.reconcile_on_startup())

    assert result == [rec["job_id"]]
    update.assert_called_once()
    assert update.call_args.args == (rec["job_id"],)
    assert update.call_args.kwargs["status"] == job_runner.STATUS_INTERRUPTED
    assert "finished_at" in update.call_args.kwargs
    mirror.assert_called_once_with(rec["job_id"], job_runner.STATUS_INTERRUPTED)
    if deferred:
        handoff.assert_not_called()
    else:
        handoff.assert_called_once_with(terminal)


def test_retry_scans_once_and_preserves_unknown_product_eligibility(monkeypatch):
    records = [
        {"job_id": "unknown-product", "status": "done", "refinement_context": None},
        {"job_id": "metadata-summary", "status": "done",
         "refinement_context": None, "metadata_only": True},
        {"job_id": "historical-unattempted", "status": "done"},
        {"job_id": "delivered", "status": "failed",
         "refinement_handoff": {"ok": True, "handoff_id": "h-delivered"}},
        {"job_id": "still-running", "status": "running", "refinement_context": {}},
        {"job_id": "skipped", "status": "cancelled",
         "refinement_handoff": {"ok": True, "skipped": True}},
        {"job_id": "unmanaged", "status": "interrupted",
         "refinement_handoff": {"ok": True, "managed": False}},
        {"job_id": "failed-receipt", "status": "failed",
         "refinement_handoff": {"ok": False}},
        {"job_id": "legacy-receipt", "status": "done",
         "refinement_handoff": "unrecognized-old-shape"},
    ]
    before = deepcopy(records)
    scan = Mock(return_value=records)
    handoff = Mock()
    monkeypatch.setattr(job_runner, "list_records", scan)
    monkeypatch.setattr(job_runner, "_record_terminal_handoff", handoff)

    job_runner.retry_terminal_handoffs()

    scan.assert_called_once_with()
    assert [entry.args[0]["job_id"] for entry in handoff.call_args_list] == [
        "unknown-product", "skipped", "unmanaged", "failed-receipt", "legacy-receipt",
    ]
    assert records == before


def test_one_record_failure_does_not_block_later_handoffs_or_log_its_body(monkeypatch, caplog):
    records = [
        {"job_id": "first-fails", "status": "done", "refinement_context": None},
        {"job_id": "second-recovers", "status": "done", "refinement_context": None},
    ]
    attempted = []
    private_detail = "synthetic exception body must remain absent from logs"

    def record(rec):
        attempted.append(rec["job_id"])
        if rec["job_id"] == "first-fails":
            raise ValueError(private_detail)

    monkeypatch.setattr(job_runner, "list_records", lambda: records)
    monkeypatch.setattr(job_runner, "_record_terminal_handoff", record)
    with caplog.at_level("WARNING", logger=job_runner.__name__):
        job_runner.retry_terminal_handoffs()

    assert attempted == ["first-fails", "second-recovers"]
    assert "first-fails" in caplog.text
    assert "ValueError" in caplog.text
    assert private_detail not in caplog.text


@pytest.mark.parametrize("interrupted", [False, True])
def test_missing_receipt_remains_recoverable_after_failure_or_interruption(monkeypatch, interrupted):
    durable = {"job_id": "recover-later", "status": "done", "refinement_context": None}
    monkeypatch.setattr(job_runner, "list_records", lambda: [deepcopy(durable)])

    def fail_before_receipt(rec):
        if interrupted:
            raise KeyboardInterrupt()
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(job_runner, "_record_terminal_handoff", fail_before_receipt)
    if interrupted:
        with pytest.raises(KeyboardInterrupt):
            job_runner.retry_terminal_handoffs()
    else:
        job_runner.retry_terminal_handoffs()
    assert "refinement_handoff" not in durable
    assert "refinement_context" in durable

    def persist_receipt(rec):
        durable["refinement_handoff"] = {"ok": True, "handoff_id": "h-recovered"}

    recovery = Mock(side_effect=persist_receipt)
    monkeypatch.setattr(job_runner, "_record_terminal_handoff", recovery)
    job_runner.retry_terminal_handoffs()
    job_runner.retry_terminal_handoffs()
    recovery.assert_called_once()
    assert durable["refinement_handoff"]["handoff_id"] == "h-recovered"


def test_start_reuses_one_live_worker_and_allows_a_later_single_pass(monkeypatch):
    created = []
    recovery = Mock()

    class FakeWorker:
        def __init__(self, *, target, name, daemon):
            self.target, self.name, self.daemon = target, name, daemon
            self.alive = False
            created.append(self)

        def start(self):
            self.alive = True

        def is_alive(self):
            return self.alive

    monkeypatch.setattr(job_runner, "_terminal_handoff_recovery_thread", None)
    monkeypatch.setattr(job_runner, "retry_terminal_handoffs", recovery)
    monkeypatch.setattr(job_runner.threading, "Thread", FakeWorker)

    first = job_runner.start_terminal_handoff_recovery()
    assert job_runner.start_terminal_handoff_recovery() is first
    assert created == [first]
    assert first.name == "anchor-terminal-handoff-recovery"
    assert first.daemon is True
    first.target()
    recovery.assert_called_once_with()
    first.alive = False
    second = job_runner.start_terminal_handoff_recovery()
    assert second is not first
    assert created == [first, second]


def test_failed_worker_start_does_not_leave_a_stale_worker_reference(monkeypatch):
    worker = Mock()
    worker.start.side_effect = RuntimeError("synthetic start failure")
    factory = Mock(return_value=worker)
    monkeypatch.setattr(job_runner, "_terminal_handoff_recovery_thread", None)
    monkeypatch.setattr(job_runner.threading, "Thread", factory)

    with pytest.raises(RuntimeError, match="synthetic start failure"):
        job_runner.start_terminal_handoff_recovery()

    assert job_runner._terminal_handoff_recovery_thread is None
    worker.start.assert_called_once_with()


def test_compaction_removes_nested_state_without_losing_identity_or_error_flags():
    receipt = {
        "ok": False, "idempotent": True, "handoff_id": "h-42", "sequence": 7,
        "managed": True, "skipped": False, "error": "synthetic failure",
        "state": {"campaign": "large top-level fixture"},
        "handoff": {"producer_id": "job-42", "state": {"private": "fixture"}},
        "reconciliation": {
            "state": {"campaign": "nested fixture"},
            "items": [
                {"state": {"campaign": "another fixture"}, "label": "keep"},
                ["state", {"state": ["fixture"], "identity": "nested-42"}],
            ],
        },
    }
    original = deepcopy(receipt)

    compacted = job_runner._compact_handoff_receipt(receipt)

    assert compacted == {
        "ok": False, "idempotent": True, "handoff_id": "h-42", "sequence": 7,
        "managed": True, "skipped": False, "error": "synthetic failure",
        "handoff": {"producer_id": "job-42"},
        "reconciliation": {
            "items": [{"label": "keep"}, ["state", {"identity": "nested-42"}]],
        },
    }
    assert receipt == original
