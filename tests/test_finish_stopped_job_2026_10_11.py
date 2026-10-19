"""John 2026-10-11: a job he stopped can be finished later from its kept edits - the same job, no new worker,
with the usual check, review and landing."""
from pathlib import Path

from steward_cockpit import code_jobs as cj, code_job_handoff as ch
from tests.test_delegation_workflow_2026_10_10 import PASS, await_job, project  # noqa: F401  (fixture)


def _stop_midway(root, workers, factory):
    cdir = root / "A"
    out = cj.start(cdir, root / "B", "Produce result", PASS, engine_factory=factory)
    worker = workers[0]
    (worker.wt / "B").mkdir(parents=True, exist_ok=True)
    (worker.wt / "B" / "result.py").write_text("answer = 42\n", encoding="utf-8")   # edited, never finished
    worker.written_ok.append(str(worker.wt / "B" / "result.py"))
    worker.stop = lambda: setattr(worker, "busy", False)
    assert cj.stop(cdir, out["job"], engine_lookup=lambda wt: worker, actor="John")["ok"]
    return cdir, out["job"]


def test_a_stopped_job_is_finished_from_its_kept_edits(project, monkeypatch):
    root, workers, factory = project
    cdir, jid = _stop_midway(root, workers, factory)
    stopped = cj.read_jobs(cdir)[jid]
    assert stopped["status"] == "stopped" and not (root / "B" / "result.py").exists()
    assert stopped["authors"] == ["claude"] and stopped["manifest"] == ["B/result.py"] and "B/result.py" in stopped["recovery_snapshot"]["files"]
    monkeypatch.setattr(ch, "process_state", lambda *a, **kw: "dead")
    assert ch.inspect(cdir, jid)["recovery"]["action"] == "recover only when John asks to finish it"
    assert ch.recover(cdir, jid, check=PASS)["ok"]
    done = await_job(cdir, jid, attempt=2)
    assert done["landed"] and len(workers) == 1, (done.get("land_note"), done.get("error"), done.get("check_ok"), done.get("review"))
    assert (root / "B" / "result.py").read_text(encoding="utf-8") == "answer = 42\n"
    assert done["attempts"][0]["stopped_by"] == "John" and not done.get("stopped_by")
    assert done["worker_completed_at"]                # a later recovery of this job is not refused for want of it


def test_a_job_stopped_before_this_record_existed_is_still_finished(project, monkeypatch):
    root, workers, factory = project
    cdir, jid = _stop_midway(root, workers, factory)
    jobs = cj.read_jobs(cdir)
    for k in ("authors", "recovery_snapshot"):
        jobs[jid].pop(k)
    cj._write_job(cdir, jobs[jid])
    monkeypatch.setattr(ch, "process_state", lambda *a, **kw: "dead")
    assert ch.recover(cdir, jid, check=PASS)["ok"]
    assert await_job(cdir, jid, attempt=2)["landed"]


def test_a_stopped_job_whose_worker_may_still_run_is_not_finished(project, monkeypatch):
    root, workers, factory = project
    cdir, jid = _stop_midway(root, workers, factory)
    monkeypatch.setattr(ch, "process_state", lambda *a, **kw: "unknown")
    assert "liveness" in ch.recover(cdir, jid, check=PASS)["error"]
