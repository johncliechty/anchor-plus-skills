"""Skill-job lifetime parity with code jobs (2026-10-10): the skill runs contained with no clock on it, Stop ends the
whole tree and SEES it gone before the record says stopped, quiet means inspect (never failed), a restart surfaces an
interruption under the same job id (never a success, never a new run), and the result is durable and collectable.
Hermetic: throwaway skill roots and effort folders, python stand-ins for skill scripts, a result collector that cannot
launch anything; never a model, never :8777."""
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from steward_cockpit import code_jobs, skill_jobs as sj  # noqa: E402

WINDOWS = pytest.mark.skipif(sys.platform != "win32", reason="process identity and the Job Object are Windows")

SLEEPER = "import time\ntime.sleep(120)\n"
PARENT = ("import subprocess, sys, time\n"
          "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
          "print('child', child.pid, flush=True)\n"
          "time.sleep(120)\n")
TALKER = "import os\nprint('hello from', os.path.basename(os.getcwd()), flush=True)\n"
SOURCE = Path(sj.__file__).read_text(encoding="utf-8")


class Collector:
    """A result recipient that cannot launch anything (the engine's job-result queue contract)."""
    general = False
    job_results_paused = False

    def __init__(self, cdir):
        self.dir = str(cdir)
        self.received, self.emitted = {}, []

    def enqueue_job_result(self, identity, text):
        self.received.setdefault(identity, text)
        return {"ok": True}

    def alive(self):
        return True

    def _emit(self, ev):
        self.emitted.append(ev)


@pytest.fixture()
def effort(tmp_path, monkeypatch):
    from steward_cockpit import maintenance
    root = tmp_path / "skills"
    (root / "gandalf").mkdir(parents=True)
    for name, text in (("sleeper.py", SLEEPER), ("parent.py", PARENT), ("talker.py", TALKER),
                       ("failer.py", "raise SystemExit(3)\n")):
        (root / "gandalf" / name).write_text(text, encoding="utf-8")
    monkeypatch.setenv("ANCHOR_SKILL_ROOTS", str(root))
    monkeypatch.setattr(maintenance, "is_active", lambda: False)
    reported = []
    monkeypatch.setattr(sj, "_report", lambda cdir, job: reported.append(job["id"]))    # no engine is woken here
    cdir = tmp_path / "effort"
    cdir.mkdir()
    return root / "gandalf", str(cdir), reported


def _until(cond, s=15):
    for _ in range(int(s * 20)):
        if cond():
            return True
        time.sleep(0.05)
    return False


def _job(cdir, jid):
    return sj.read_jobs(cdir).get(jid) or {}


def _alive(pid):
    if sys.platform == "win32":
        import proc_probe
        return proc_probe.is_alive(pid)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


# ---- contained, identified, no clock ----

def test_a_skill_runs_contained_with_its_identity_persisted_and_no_clock_on_it(effort):
    skills, cdir, _ = effort
    out = sj.start(cdir, [sys.executable, str(skills / "sleeper.py")], "Gandalf read", actor="the steward")
    assert out["ok"], out
    try:
        job = _job(cdir, out["job"])
        p = job["process"]
        assert job["status"] == "running" and job["phase"] == "running" and job["attempt"] == 1
        assert job["started_by"] == "the steward" and job["cwd"] == cdir and job["label"] == "Gandalf read"
        assert p["pid"] == out["pid"] and p["state"] == "active" and _alive(p["pid"])
        if sys.platform == "win32":
            assert p["contained"] is True and isinstance(p["birth"], (int, float))
        assert isinstance(sj._PROCS[out["job"]], code_jobs._Run)
        assert not hasattr(sj, "TIMEOUT_S") and "ANCHOR_SKILL_JOB_TIMEOUT_S" not in SOURCE, "no age-only termination"
        assert "taskkill" not in SOURCE and not hasattr(sj, "_kill_tree")
    finally:
        stopped = sj.stop(cdir, out["job"], actor="John")
    assert stopped["ok"], stopped
    job = _job(cdir, out["job"])
    assert job["status"] == "stopped" and job["stopped_by"] == "John" and job["process"]["state"] == "ended"
    assert _until(lambda: not _alive(p["pid"])) and _until(lambda: out["job"] not in sj._PROCS)


def test_a_launch_failure_leaves_an_honest_failed_record_under_the_same_id_with_a_collectable_result(effort, tmp_path):
    skills, cdir, reported = effort
    bogus = tmp_path / "python.exe"                                 # a python that does not exist: the launch fails
    out = sj.start(cdir, [str(bogus), str(skills / "talker.py")], "Gandalf read")
    assert out["ok"] is False and "could not start" in out["error"] and out["job"], out
    job = _job(cdir, out["job"])
    assert job["status"] == "failed" and "could not start" in job["error"] and job["process"]["state"] == "dead"
    assert out["job"] not in sj._PROCS and reported == [out["job"]]
    assert list(sj.read_jobs(cdir)) == [out["job"]], "the same job, no new producer"
    got = sj.collect(cdir, out["job"])
    assert got["ok"] and got["handoff"]["state"] == "collected" and got["label"] == "Gandalf read"
    text = got["handoff"]["text"]
    assert "could not start" in text and job["log"] in text and "Anchor landed, reviewed and committed nothing" in text


def test_a_failing_skill_is_failed_with_its_exit_code_not_a_hang(effort):
    skills, cdir, _ = effort
    out = sj.start(cdir, [sys.executable, str(skills / "failer.py")], "failer")
    assert out["ok"], out
    assert _until(lambda: _job(cdir, out["job"]).get("status") == "failed")
    job = _job(cdir, out["job"])
    assert job["rc"] == 3 and "exited 3" in job["error"] and sj.stage_line(job) == "failed (the skill exited 3)"
    assert job["process"]["returncode"] == 3 and _until(lambda: out["job"] not in sj._PROCS)


# ---- Stop ----

@WINDOWS
def test_stop_ends_every_process_the_skill_started_and_sees_them_gone(effort):
    skills, cdir, _ = effort
    out = sj.start(cdir, [sys.executable, str(skills / "parent.py")], "parent")
    assert out["ok"], out
    log = Path(cdir) / out["log"]
    assert _until(lambda: log.exists() and "child" in log.read_text(encoding="utf-8", errors="replace"))
    child = int(log.read_text(encoding="utf-8", errors="replace").split()[1])
    assert _alive(out["pid"]) and _alive(child)
    stopped = sj.stop(cdir, out["job"], actor="John")
    assert stopped["ok"], stopped
    assert not _alive(out["pid"]) and not _alive(child), "the whole tree, not only the root"
    job = _job(cdir, out["job"])
    assert job["status"] == "stopped" and job["stopped_by"] == "John" and job["stop_requested"]
    assert _until(lambda: out["job"] not in sj._PROCS)


def test_a_stop_that_cannot_see_the_tree_end_keeps_the_job_and_its_claim(effort):
    skills, cdir, _ = effort
    out = sj.start(cdir, [sys.executable, str(skills / "sleeper.py")], "sleeper")
    assert out["ok"], out
    run = sj._PROCS[out["job"]]
    run.end = lambda *a, **k: False                                 # the tree cannot be seen to end
    refused = sj.stop(cdir, out["job"], actor="John")
    assert refused["ok"] is False and "keeps its claim" in refused["error"] and refused["stop_requested"]
    job = _job(cdir, out["job"])
    assert job["status"] == "running" and job["stop_requested"] and job["stop_requested_by"] == "John"
    assert job["process"]["state"] == "cleanup_wait" and "keeps its claim" in job["stuck"]
    assert out["job"] in sj._PROCS and _alive(out["pid"]), "nothing released, nothing killed blind"
    del run.end                                                     # the tree can be ended now
    again = sj.stop(cdir, out["job"], actor="John")
    assert again["ok"] or "no skill job is running" in again.get("error", ""), again
    assert _until(lambda: _job(cdir, out["job"])["status"] == "stopped")
    job = _job(cdir, out["job"])
    assert job["stopped_by"] == "John" and job["process"]["state"] == "ended" and not job.get("stuck")
    assert _until(lambda: not _alive(out["pid"])) and _until(lambda: out["job"] not in sj._PROCS)


def test_a_stop_before_the_launch_means_no_launch(effort, monkeypatch):
    skills, cdir, _ = effort
    real_write, launched = sj._write_job, []

    def write_then_stop(c, job):                                    # John's Stop lands between the record and the launch
        real_write(c, job)
        if job.get("status") == "running" and not job.get("stop_requested"):
            assert sj.stop(c, job["id"], actor="John")["ok"]

    def never(*a, **k):
        launched.append(a)
        raise AssertionError("a skill was launched after its Stop")
    monkeypatch.setattr(sj, "_write_job", write_then_stop)
    monkeypatch.setattr(code_jobs, "_popen_contained", never)
    out = sj.start(cdir, [sys.executable, str(skills / "sleeper.py")], "sleeper")
    assert out["ok"] is False and "stopped before it launched" in out["error"] and launched == []
    job = _job(cdir, out["job"])
    assert job["status"] == "stopped" and job["stopped_by"] == "John" and out["job"] not in sj._PROCS


# ---- observation: quiet means inspect ----

def test_quiet_means_inspect_never_failed_and_the_observation_is_said_once(effort, monkeypatch):
    skills, cdir, _ = effort
    out = sj.start(cdir, [sys.executable, str(skills / "sleeper.py")], "sleeper")
    assert out["ok"], out
    try:
        long_ago = time.time() - 1000                               # quiet for longer than the inspection interval
        sj._transition(cdir, out["job"], sj.LIVE, phase_at=long_ago)
        sj._observe(cdir, out["job"], activity_at=long_ago, launched_at=long_ago)
        monkeypatch.setattr(sj, "SUPERVISE_EVERY_S", 0)
        eng = Collector(cdir)
        sj.refresh_supervision(cdir, engine=eng)
        sj.refresh_supervision(cdir, engine=eng)
        job = _job(cdir, out["job"])
        assert job["status"] == "running" and _alive(out["pid"]), "quiet is not failed; nothing was ended"
        assert job["supervision"]["state"] == "needs_inspection" and job["supervision"]["liveness"] == "active"
        assert len(eng.received) == 1 and job["attention_notice"]["id"] in eng.received
        text = next(iter(eng.received.values()))
        assert "not a completion" in text and "does not authorize termination" in text and job["log"] in text
        look = sj.inspect(cdir, out["job"])
        assert look["ok"] and look["held"] and look["stage"] == "running" and look["supervision"]["state"] == "needs_inspection"
    finally:
        sj.stop(cdir, out["job"], actor="John")


# ---- a restart: the same job id, an honest interruption, a durable result ----

def test_a_restart_marks_an_unheld_contained_job_interrupted_under_its_own_id_and_delivers_that(effort):
    skills, cdir, _ = effort
    import proc_probe
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1)"])
    birth = proc_probe.creation_time(proc.pid)
    proc.wait()
    log = Path(cdir) / sj.LOG_DIR / "k-old.log"
    log.parent.mkdir(parents=True)
    log.write_text("Gandalf: reading the plan...\n", encoding="utf-8")
    old = {"id": "k-old", "label": "Gandalf read of the plan", "argv": ["node", str(skills / "run.mjs")],
           "status": "running", "attempt": 1, "started": "2026-10-10 10:00:00", "started_epoch": time.time() - 600,
           "log": sj.LOG_DIR + "/k-old.log", "cwd": cdir, "phase": "running", "phase_at": time.time() - 600,
           "process": {"state": "active", "pid": proc.pid, "birth": birth, "contained": True, "activity_at": None,
                       "output_bytes": 28}}
    sj._write_job(cdir, old)
    assert "k-old" not in sj._PROCS                                  # this Anchor never held it; the one that did ended
    sj.reconcile(cdir)
    job = _job(cdir, "k-old")
    assert job["status"] == "failed" and job["interrupted"] is True and "interrupted" in job["error"]
    assert job["label"] == "Gandalf read of the plan" and job["log"] == sj.LOG_DIR + "/k-old.log" and log.exists()
    assert job["handoff"]["state"] == "needs_report"
    assert list(sj.read_jobs(cdir)) == ["k-old"], "the same job, no new producer"
    eng = Collector(cdir)
    assert sj.retry_pending(cdir, engine=eng) is True
    (identity, text), = eng.received.items()
    assert identity.startswith("skill:k-old:1:") and "interrupted" in text and "Gandalf read of the plan" in text
    assert sj.LOG_DIR + "/k-old.log" in text and "Anchor landed, reviewed and committed nothing" in text
    assert "finished (exit 0)" not in text and "never start another run" in text
    assert _job(cdir, "k-old")["handoff"]["state"] == "queued"
    got = sj.collect(cdir, "k-old")
    assert got["ok"] and got["handoff"]["id"] == identity and got["handoff"]["state"] == "collected"
    assert sj.collect(cdir, "k-old")["handoff"]["id"] == identity, "the same result, the same identity"


@WINDOWS
@pytest.mark.parametrize("contained,birth_missing", [(False, False), (True, True), (True, False)])
def test_an_unheld_record_is_left_running_until_its_process_is_seen_gone_never_by_age(effort, contained, birth_missing):
    skills, cdir, _ = effort
    import proc_probe
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        birth = proc_probe.creation_time(proc.pid)
        sj._write_job(cdir, {"id": "k-unheld", "label": "unheld", "argv": ["node", "x.mjs"], "status": "running",
                             "started": "2026-10-10 10:00:00", "log": sj.LOG_DIR + "/k-unheld.log",
                             "process": {"pid": proc.pid, "birth": None if birth_missing else birth,
                                         "contained": contained, "state": "active"}})
        sj._write_job(cdir, {"id": "k-flat", "label": "legacy", "argv": ["node", "x.mjs"], "status": "running",
                             "started": "2026-10-10 10:00:00", "log": sj.LOG_DIR + "/k-flat.log", "pid": proc.pid})
        sj.reconcile(cdir)
        for jid in ("k-unheld", "k-flat"):
            job = _job(cdir, jid)
            assert job["status"] == "running" and job["unheld"] is True and "cannot be stopped from here" in job["stuck"]
        assert proc.poll() is None, "never killed by age or by a guess"
        refused = sj.stop(cdir, "k-unheld", actor="John")
        assert refused["ok"] is False and "does not hold" in refused["error"] and proc.poll() is None
        eng = Collector(cdir)
        sj.refresh_supervision(cdir, engine=eng)
        assert _job(cdir, "k-unheld")["supervision"]["liveness"] == ("unknown" if birth_missing else "active")
        assert _job(cdir, "k-flat")["supervision"]["liveness"] == "unknown", "no identity, no claim about it"
    finally:
        proc.kill()
        proc.wait()
    sj.reconcile(cdir)
    job = _job(cdir, "k-unheld")
    assert job["status"] == "failed" and job["interrupted"] is True


@pytest.mark.parametrize("evidence,phrase", [
    ({"stopped_before_launch": True}, "stopped before launch"),
    ({"pid_seen_gone": True}, "recorded pid was already gone"),
    ({"tree_seen": True}, "process tree was seen to end"),
])
def test_stopped_result_only_claims_its_observed_evidence(evidence, phrase):
    job = {"id": "evidence", "status": "stopped", "process": evidence,
           "argv": ["python", "gandalf/run.py"], "label": "Gandalf", "stopped_by": "John"}
    text = sj._result_text(job)
    assert phrase in text
    assert ("process tree was seen to end" in text) == bool(evidence.get("tree_seen"))


# ---- the durable result of a finished run ----

def test_a_finished_skill_delivers_a_durable_result_naming_its_label_and_log_and_no_landing(effort):
    skills, cdir, reported = effort
    out = sj.start(cdir, [sys.executable, str(skills / "talker.py")], "Gandalf read of the plan")
    assert out["ok"], out
    assert _until(lambda: _job(cdir, out["job"]).get("status") == "done")
    job = _job(cdir, out["job"])
    assert job["rc"] == 0 and job["process"]["state"] == "ended" and job["process"]["returncode"] == 0
    assert "hello from effort" in (Path(cdir) / job["log"]).read_text(encoding="utf-8")
    assert job["process"]["output_bytes"] > 0 and job["handoff"]["state"] == "needs_report" and reported == [out["job"]]
    assert _until(lambda: out["job"] not in sj._PROCS)
    eng = Collector(cdir)
    assert sj.retry_pending(cdir, engine=eng) is True
    (identity, text), = eng.received.items()
    assert identity.startswith("skill:%s:1:" % out["job"]) and "Gandalf read of the plan" in text and job["log"] in text
    assert "finished (exit 0)" in text and "Anchor landed, reviewed and committed nothing" in text
    assert "landed on" not in text and "collect --job %s" % out["job"] in text
    assert sj.retry_pending(cdir, engine=eng) is False and len(eng.received) == 1, "said once"
    assert any("skill job %s done" % out["job"] in str(ev.get("text")) for ev in eng.emitted)
    got = sj.collect(cdir, out["job"])
    assert got["ok"] and got["handoff"]["id"] == identity and got["log"] == job["log"]
    assert got["label"] == "Gandalf read of the plan" and got["cwd"] == cdir
    assert sj.collect(cdir, out["job"])["handoff"]["state"] == "collected"


# ---- the consumers: the steward's tick, the route, the tool ----

def test_the_steward_tick_the_route_and_the_tool_carry_the_skill_job_lifecycle():
    eng = (ROOT / "steward_cockpit" / "steward_engine.py").read_text(encoding="utf-8")
    assert "_skj.refresh_supervision(self.dir, engine=self)" in eng and "_skj.retry_pending(self.dir, engine=self)" in eng
    routes = (ROOT / "steward_cockpit" / "steward_routes.py").read_text(encoding="utf-8")
    assert "_sj.inspect(cdir, jid)" in routes and "_sj.collect(cdir, jid, body.get(\"handoff_id\"))" in routes
    assert 'actor=str(body.get("actor") or "the steward"))' in routes.split('if verb == "skill_job"')[1]
    tool = (ROOT / "tools" / "steward_skill.py").read_text(encoding="utf-8")
    assert '"inspect", "collect"' in tool and "--handoff-id" in tool
