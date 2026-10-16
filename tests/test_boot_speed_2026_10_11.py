"""John 2026-10-11 (#5 speed): Anchor took 90-130 s to answer after a restart because the boot read every job
record (20k+ files, cold from disk) several times. A boot now reads only the records written since the last boot
looked, plus the ones that boot left running; the log clean-up opens only records whose log is old enough."""
import json
import os
import time

import pytest

import job_runner as jr
import supervisor as sup


@pytest.fixture
def jobs(tmp_path, monkeypatch):
    monkeypatch.setattr(jr, "jobs_dir", lambda: tmp_path)
    monkeypatch.setattr(jr, "_jobs_dir_for", lambda jid: tmp_path)
    monkeypatch.setattr(jr, "_attribute_job", lambda *a, **k: None)
    monkeypatch.setattr(jr, "_mirror_session_status", lambda *a, **k: None)
    return tmp_path


def _rec(d, jid, age_days=0.0, **fields):
    p = d / f"{jid}.json"
    p.write_text(json.dumps(dict({"job_id": jid}, **fields)), encoding="utf-8")
    t = time.time() - age_days * 86400
    os.utime(p, (t, t))
    return p


def test_first_boot_reads_everything_then_later_boots_read_only_what_changed(jobs):
    _rec(jobs, "old_done", age_days=30, status="done")
    _rec(jobs, "dead_run", status="running", pid=None)
    assert jr.reconcile_on_startup(defer_handoffs=True, at_boot=True) == ["dead_run"], "no mark yet: every record, as before"
    assert (jobs / jr.BOOT_MARK).exists()
    assert json.loads((jobs / "dead_run.json").read_text(encoding="utf-8"))["status"] == jr.STATUS_INTERRUPTED

    _rec(jobs, "new_run", status="running", pid=None)
    seen = [r["job_id"] for r in jr._boot_records()]
    assert "new_run" in seen and "old_done" not in seen, "an old settled record is not read again"


def test_a_job_left_running_by_the_last_boot_is_looked_at_again_however_old(jobs, monkeypatch):
    _rec(jobs, "survivor", age_days=10, status="running", pid=4242)
    monkeypatch.setattr(jr, "_pid_alive", lambda pid: True)
    assert jr.reconcile_on_startup(defer_handoffs=True, at_boot=True) == []
    monkeypatch.setattr(jr, "_pid_alive", lambda pid: False)
    assert jr.reconcile_on_startup(defer_handoffs=True, at_boot=True) == ["survivor"], "carried by the mark, though its file is old"


def test_a_record_that_cannot_be_read_is_read_again_at_the_next_boot(jobs, monkeypatch):
    # ChatGPT review: an old running record unreadable for one boot must not drop out of the mark for good.
    _rec(jobs, "survivor", age_days=10, status="running", pid=4242)
    monkeypatch.setattr(jr, "_pid_alive", lambda pid: True)
    jr.reconcile_on_startup(defer_handoffs=True, at_boot=True)
    real = jr.Path.read_text
    monkeypatch.setattr(jr.Path, "read_text", lambda self, *a, **k: (_ for _ in ()).throw(OSError("busy"))
                        if self.name == "survivor.json" else real(self, *a, **k))
    jr.reconcile_on_startup(defer_handoffs=True, at_boot=True)
    monkeypatch.setattr(jr.Path, "read_text", real)
    monkeypatch.setattr(jr, "_pid_alive", lambda pid: False)
    assert jr.reconcile_on_startup(defer_handoffs=True, at_boot=True) == ["survivor"]


def test_only_a_boot_writes_the_mark(jobs):
    _rec(jobs, "done", status="done")
    jr.reconcile_on_startup()
    jr.reconcile_on_startup(defer_handoffs=True)
    assert not (jobs / jr.BOOT_MARK).exists(), "only the dashboard's own boot marks (tests, other callers: no mark)"


def test_the_log_clean_up_opens_only_records_whose_log_is_old(jobs, monkeypatch):
    old = time.time() - 60 * 86400
    for jid, status, fin in (("gone", "done", old), ("live", "running", old), ("fresh", "done", time.time())):
        _rec(jobs, jid, status=status, finished_at=fin)
        (jobs / f"{jid}.log").write_text("x", encoding="utf-8")
    for jid in ("gone", "live"):
        os.utime(jobs / f"{jid}.log", (old, old))
    opened = []
    real = jr.load_record
    monkeypatch.setattr(jr, "load_record", lambda jid: opened.append(jid) or real(jid))
    assert jr.gc_old_job_logs() == 1
    assert not (jobs / "gone.log").exists() and (jobs / "live.log").exists() and (jobs / "fresh.log").exists()
    assert sorted(opened) == ["gone", "live"], "a recent log's record is never opened"


def test_the_boot_rebuild_reads_no_full_list_once_a_mark_exists(jobs, monkeypatch):
    _rec(jobs, "survivor", age_days=10, status="running", pid=4242, lane="build", folder_path="C:/x")
    monkeypatch.setattr(jr, "_pid_alive", lambda pid: True)
    jr.reconcile_on_startup(defer_handoffs=True, at_boot=True)                      # the boot's first look writes the mark
    monkeypatch.setattr(jr, "list_records", lambda: pytest.fail("a boot rebuild read every record"))
    monkeypatch.setattr(jr, "_FOLDER_BUILD", {})
    out = sup.InlineSupervisor().rebuild(at_boot=True)
    assert out["running_jobs"] == ["survivor"] and jr._FOLDER_BUILD == {"C:/x": "survivor"}
