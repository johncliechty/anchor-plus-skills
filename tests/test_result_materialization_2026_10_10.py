"""Durable result recovery without rerunning completed delegated work."""

import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from steward_cockpit import code_job_handoff as ch, code_jobs as cj

from tests.test_delegation_workflow_2026_10_10 import PASS, project


def _await_terminal_without_receipt(cdir, jid):
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        job = cj.read_jobs(cdir).get(jid) or {}
        if (
            job
            and job.get("status") not in cj.LIVE
            and not job.get("finalizer_active")
        ):
            return job
        time.sleep(0.03)
    raise AssertionError(cj.read_jobs(cdir))


class Collector:
    """A non-autonomous result recipient; it cannot launch a worker."""

    general = False
    job_results_paused = False

    def __init__(self, cdir):
        self.dir = str(cdir)
        self.received = {}

    def enqueue_job_result(self, result_id, text):
        self.received.setdefault(result_id, text)
        return {"ok": True}

    def alive(self):
        return True


def test_reconciliation_materializes_result_after_terminal_report_crash(
    project, monkeypatch
):
    root, workers, factory = project
    cdir = root / "A"
    original_report = cj._report

    def crash_after_terminal_save(*_args, **_kwargs):
        raise OSError("crash after terminal save")

    monkeypatch.setattr(cj, "_report", crash_after_terminal_save)
    started = cj.start(
        cdir,
        root / "B",
        "Produce only B/result.py",
        PASS,
        outputs=["B/result.py"],
        engine_factory=factory,
    )
    assert started["ok"], started
    jid = started["job"]
    produced = "answer = 42\n"
    workers[0].produce({"B/result.py": produced})
    saved = _await_terminal_without_receipt(cdir, jid)
    assert saved["landed"] and saved["verified"], saved
    assert not (saved.get("handoff") or {}).get("id"), saved
    assert (root / "B/result.py").read_text() == produced
    outcome = {
        key: saved.get(key)
        for key in ("id", "attempt", "status", "landed", "landed_commit")
    }
    monkeypatch.setattr(cj, "_report", original_report)

    def unexpected_execution(*_args, **_kwargs):
        raise AssertionError("result recovery must not rerun completed work")

    for name in ("run_check", "run_review", "land", "start"):
        monkeypatch.setattr(cj, name, unexpected_execution)

    # The shared fixture disables notify; this checks durable result creation
    # without asking an actual steward or provider to run another turn.
    collector = Collector(cdir)
    ch.retry_pending(cdir, engine=collector)
    ch.retry_pending(cdir, engine=collector)
    reconciled = cj.read_jobs(cdir)[jid]
    assert reconciled.get("handoff"), reconciled
    first = ch.collect(cdir, jid)
    second = ch.collect(cdir, jid)
    assert first["ok"], first
    assert second["ok"], second
    assert first["handoff"]["id"] == second["handoff"]["id"]
    final = cj.read_jobs(cdir)[jid]
    assert {key: final.get(key) for key in outcome} == outcome
    assert (root / "B/result.py").read_text() == produced
    assert len(workers) == 1


def test_reconciliation_leaves_legacy_rows_quiet_until_explicit_collection(project):
    root, workers, _factory = project
    cdir = root / "A"
    for jid in ("legacy-selected", "legacy-other"):
        cj._write_job(
            cdir,
            {
                "id": jid,
                "attempt": 1,
                "status": "done",
                "repo": str(root),
                "worktree": str(root),
                "steward_dir": str(cdir),
                "landed": False,
                "files": [],
                "manifest": [],
                "check": None,
                "summary": "Historical completed job",
                "land_note": "No work was landed by this historical record.",
            },
        )
    before = cj.read_jobs(cdir)
    collector = Collector(cdir)
    ch.retry_pending(cdir, engine=collector)
    ch.retry_pending(cdir, engine=collector)
    assert cj.read_jobs(cdir) == before

    selected = ch.collect(cdir, "legacy-selected")
    assert selected["ok"], selected
    assert selected["handoff"]["id"]
    after = cj.read_jobs(cdir)
    assert after["legacy-selected"].get("handoff"), after
    assert after["legacy-other"] == before["legacy-other"]
    assert workers == []


def test_collection_does_not_materialize_a_result_for_a_live_job(project):
    root, workers, factory = project
    cdir = root / "A"
    started = cj.start(
        cdir,
        root / "B",
        "Produce only B/result.py",
        PASS,
        outputs=["B/result.py"],
        engine_factory=factory,
    )
    assert started["ok"], started
    jid = started["job"]
    try:
        assert cj.read_jobs(cdir)[jid]["status"] in cj.LIVE
        result = ch.collect(cdir, jid)
        assert not result["ok"], result
        assert not cj.read_jobs(cdir)[jid].get("handoff")
        assert len(workers) == 1
    finally:
        cj.stop(cdir, jid, actor="human")


def _terminal_job(cdir, root, jid):
    cj._write_job(
        cdir,
        {
            "id": jid,
            "attempt": 1,
            "status": "finishing",
            "repo": str(root),
            "worktree": str(root),
            "steward_dir": str(cdir),
            "summary": "Completed fixture job",
            "land_note": "No changes required landing.",
            "files": [],
            "manifest": [],
            "check": None,
        },
    )
    terminal = cj._transition(
        cdir,
        jid,
        ("finishing",),
        expect_attempt=1,
        status="done",
        phase="outcome",
        finalizer_active=False,
        landed=False,
    )
    assert terminal is not None
    return terminal


def _forbid_execution(monkeypatch):
    def unexpected_execution(*_args, **_kwargs):
        raise AssertionError("result recovery must not rerun completed work")

    for name in ("run_check", "run_review", "land", "start"):
        monkeypatch.setattr(cj, name, unexpected_execution)


def test_concurrent_collection_and_reconciliation_build_one_stable_result(
    project, monkeypatch
):
    root, workers, _factory = project
    cdir = root / "A"
    jid = "concurrent-terminal-result"
    _terminal_job(cdir, root, jid)
    _forbid_execution(monkeypatch)
    original_materialize = cj._materialize_report
    materializations = []

    def track_materialization(*args, **kwargs):
        materializations.append(True)
        return original_materialize(*args, **kwargs)

    monkeypatch.setattr(cj, "_materialize_report", track_materialization)
    barrier = Barrier(2, timeout=5)
    collector = Collector(cdir)

    def collect():
        barrier.wait()
        return ch.collect(cdir, jid)

    def reconcile():
        barrier.wait()
        return ch.retry_pending(cdir, engine=collector)

    with ThreadPoolExecutor(max_workers=2) as pool:
        collection = pool.submit(collect)
        reconciliation = pool.submit(reconcile)
        result = collection.result(timeout=10)
        reconciliation.result(timeout=10)

    assert result["ok"], result
    current = cj.read_jobs(cdir)[jid]
    assert current["handoff"]["id"] == result["handoff"]["id"]
    assert current["handoff"]["state"] == "collected", current
    assert len(materializations) == 1
    repeated = ch.collect(cdir, jid)
    ch.retry_pending(cdir, engine=collector)
    assert repeated["ok"], repeated
    assert repeated["handoff"]["id"] == result["handoff"]["id"]
    assert cj.read_jobs(cdir)[jid]["handoff"]["state"] == "collected"
    assert len(materializations) == 1
    assert workers == []


def test_failed_result_and_pending_notification_do_not_starve_other_results(
    project, monkeypatch
):
    root, workers, _factory = project
    cdir = root / "A"
    failing_id = "fairness-a-failing"
    next_id = "fairness-b-next"
    pending_id = "fairness-c-pending"
    for jid in (failing_id, next_id, pending_id):
        _terminal_job(cdir, root, jid)
    ch.materialize(cdir, pending_id)
    pending = cj.read_jobs(cdir)[pending_id]
    assert pending["handoff"]["state"] == "pending", pending
    _forbid_execution(monkeypatch)

    original_materialize = cj._materialize_report
    report_attempts = []
    notifications = []

    def fail_one_report(folder, job, **kwargs):
        report_attempts.append(job["id"])
        if job["id"] == failing_id:
            raise OSError("injected report construction failure")
        return original_materialize(folder, job, **kwargs)

    def record_unacknowledged_notification(*_args, **_kwargs):
        notifications.append(True)
        return False

    monkeypatch.setattr(cj, "_materialize_report", fail_one_report)
    monkeypatch.setattr(ch, "notify", record_unacknowledged_notification)
    collector = Collector(cdir)
    ch.retry_pending(cdir, engine=collector)
    failed = cj.read_jobs(cdir)[failing_id]
    assert "injected report construction failure" in str(failed["handoff"])
    assert report_attempts == [failing_id]
    assert notifications

    ch.retry_pending(cdir, engine=collector)
    after = cj.read_jobs(cdir)
    assert after[next_id]["handoff"].get("id"), after[next_id]
    assert "injected report construction failure" in str(after[failing_id]["handoff"])
    assert report_attempts == [failing_id, next_id]
    assert len(notifications) >= 2
    collected = ch.collect(cdir, next_id)
    assert collected["ok"], collected
    assert collected["handoff"]["id"] == after[next_id]["handoff"]["id"]
    assert workers == []
