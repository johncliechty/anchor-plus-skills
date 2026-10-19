"""Disposable Git projects, actual controller/check/review/lander, fake subscription producer/reviewer."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import threading

import pytest

from steward_cockpit import code_jobs as cj, code_job_handoff as ch, steward_routes as sr, maintenance

PASS = [sys.executable, "-c", "pass"]
FAIL = [sys.executable, "-c", "raise SystemExit(1)"]


def test_dead_controller_recovery_requires_evidence_and_reuses_original_job(project, monkeypatch):
    root, workers, factory = project
    cdir = root / "A"
    out = cj.start(cdir, root / "B", "Produce result", FAIL, engine_factory=factory)
    workers[0].produce({"B/result.py": "x = 1"})
    await_job(cdir, out["job"])
    cj._transition(cdir, out["job"], ("done", "failed"), status="finishing", finalizer_active=True,
                   finished="", finishing_at=1, claim={"pid": 999999, "birth": 10})
    monkeypatch.setattr(ch, "process_state", lambda *a, **kw: "active")
    assert not ch.recover(cdir, out["job"], check=PASS)["ok"]  # old age releases nothing
    monkeypatch.setattr(ch, "process_state", lambda *a, **kw: "unknown")
    assert not ch.recover(cdir, out["job"], check=PASS)["ok"]
    monkeypatch.setattr(ch, "process_state", lambda *a, **kw: "dead")
    assert ch.inspect(cdir, out["job"])["recovery"]["available"]
    assert ch.recover(cdir, out["job"], check=PASS)["ok"]
    done = await_job(cdir, out["job"], attempt=2)
    assert done["landed"] and len(workers) == 1
    assert done["attempts"][0]["claim"]["pid"] == 999999


def test_supervision_notice_is_durable_deduplicated_and_never_relaunches(tmp_path, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(ch.time, "time", lambda: now[0])
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))
    job = {"id": "quiet", "status": "running", "attempt": 1, "phase": "producing", "phase_at": 1,
           "steward_dir": str(tmp_path), "worktree": str(tmp_path / "wt"), "repo": str(tmp_path)}
    cj._write_job(tmp_path, job)
    monkeypatch.setattr(ch, "observe", lambda job: {"state": "active", "last_activity": 2})
    accepted, calls = {}, []
    class Engine:
        def enqueue_job_result(self, identity, text):
            calls.append(identity)
            accepted.setdefault(identity, text)
            if len(calls) == 1:
                raise OSError("lost acknowledgement after durable acceptance")
            return {"ok": True}
    eng = Engine()
    with pytest.raises(OSError, match="lost acknowledgement"):
        ch.refresh_supervision(tmp_path, engine=eng)
    now[0] += 31
    ch.refresh_supervision(tmp_path, engine=eng)
    now[0] += 31
    ch.refresh_supervision(tmp_path, engine=eng)
    assert len(calls) == 2 and len(accepted) == 1
    saved = cj.read_jobs(tmp_path)["quiet"]
    assert saved["status"] == "running" and saved["supervision"]["state"] == "needs_inspection"
    assert saved["attention_notice"]["id"] in accepted
    assert "does not authorize termination" in next(iter(accepted.values()))


def test_packaging_check_can_be_only_producer_and_recovered(project):
    root, workers, factory = project
    cdir = root / "A"
    out = cj.start(cdir, root / "B", "Render existing source as B/report.pdf", FAIL,
                   outputs=["B/report.pdf"], engine_factory=factory)
    workers[0].produce({})
    first = await_job(cdir, out["job"])
    assert first["check_ok"] is False and not first["landed"]
    render = [sys.executable, "-c", "from pathlib import Path; Path('B/report.pdf').write_text('%PDF fixture')"]
    assert ch.recover(cdir, out["job"], check=render)["ok"]
    done = await_job(cdir, out["job"], attempt=2)
    assert done["landed"] and done["check_ok"] is True and len(workers) == 1
    assert (root / "B/report.pdf").read_text() == "%PDF fixture"


def test_recovery_history_preserves_handoff_saved_during_validation(project, monkeypatch):
    root, workers, factory = project
    cdir = root / "A"
    out = cj.start(cdir, root / "B", "Produce result", FAIL, engine_factory=factory)
    workers[0].produce({"B/result.py": "x = 1"})
    done = await_job(cdir, out["job"])
    validate = ch.recovery_error
    def late_handoff(job, worker=None):
        why = validate(job, worker)
        ch.save_result(cdir, job, "new result saved during recovery validation")
        return why
    monkeypatch.setattr(ch, "recovery_error", late_handoff)
    assert ch.recover(cdir, out["job"], check=PASS)["ok"]
    final = await_job(cdir, out["job"], attempt=2)
    assert final["attempts"][0]["handoff"]["text"] == "new result saved during recovery validation"
    assert done["handoff"]["text"] != final["attempts"][0]["handoff"]["text"]


def test_missing_reading_output_after_integration_blocks_placement(project, monkeypatch):
    root, workers, factory = project
    cdir = root / "A"
    (root / "B/report.pdf").write_text("existing report")
    git(root, "add", "B/report.pdf")
    git(root, "commit", "-qm", "existing required report")
    first = cj.start(cdir, root / "B", "First change; preserve report", PASS,
                     outputs=["B/report.pdf"], engine_factory=factory)
    second = cj.start(cdir, root / "B", "Sibling change", PASS, engine_factory=factory)
    workers[1].produce({"B/sibling.py": "x = 2"})
    assert await_job(cdir, second["job"])["landed"]
    original = cj.run_check
    calls = []
    def check(job, tree):
        calls.append(job["id"])
        if len(calls) == 2:
            Path(tree, "B/report.pdf").unlink()
        return original(job, tree)
    monkeypatch.setattr(cj, "run_check", check)
    workers[0].produce({"B/first.py": "x = 1"})
    done = await_job(cdir, first["job"])
    assert len(calls) == 2 and not done["landed"]
    assert done["integration_check_ok"] is False
    assert ch.collect(cdir, first["job"])["handoff"]["check_state"] == "failed"
    assert (root / "B/report.pdf").read_text() == "existing report"
    assert not (root / "B/first.py").exists()


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True,
                          text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip()


class Worker:
    def __init__(self, wt):
        self.wt, self.written_ok, self.cli = Path(wt), [], "claude"
        self.code_job, self.on_turn_done, self.policy_override = None, None, None
        self.busy, self.queue, self.last_output = True, [], time.time()
        self.proc = None

    def wake(self, **kw):
        self.seed = kw["seed"]
        return True, "awake"

    def alive(self):
        return True

    def produce(self, files):
        for name, data in files.items():
            path = self.wt / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(data, encoding="utf-8")
            self.written_ok.append(str(path))
        self.busy = False
        self.on_turn_done({"text": "produced requested files"})


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "test@invalid")
    for part in ("A", "B"):
        (root / part).mkdir()
        (root / part / "original.py").write_text("value = 1\n", encoding="utf-8")
    git(root, "add", "A/original.py", "B/original.py")
    git(root, "commit", "-qm", "initial")
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.setenv("ANCHOR_REVIEW_CMD", json.dumps([sys.executable, str(Path(__file__).with_name("fake_review.py"))]))
    monkeypatch.setattr(cj, "choose_coder", lambda requested="": ("claude", None))
    monkeypatch.setattr(maintenance, "is_active", lambda: False)
    monkeypatch.setattr(ch, "notify", lambda *a, **k: False)
    workers = []
    def engine(wt):
        w = Worker(wt)
        workers.append(w)
        return w
    monkeypatch.setattr(sr, "get_engine", lambda folder, **kw: next((w for w in workers if w.wt == Path(folder)), None))
    return root, workers, engine


def await_job(cdir, jid, attempt=1):
    until = time.monotonic() + 25
    while time.monotonic() < until:
        job = cj.read_jobs(cdir).get(jid) or {}
        if (job.get("attempt", 1) == attempt and job.get("status") not in cj.LIVE and job.get("handoff")
                and not job.get("finalizer_active")):
            return job
        time.sleep(0.03)
    raise AssertionError(cj.read_jobs(cdir))


def test_fail_then_recover_same_job_into_other_effort_without_new_worker(project, monkeypatch):
    root, workers, factory = project
    cdir = root / "A"
    phases = []
    original = cj.phase
    def capture(job, value, **kw):
        phases.append(value)
        return original(job, value, **kw)
    monkeypatch.setattr(cj, "phase", capture)
    launched = cj.start(cdir, root / "B", "Only produce B/result.py", FAIL,
                        outputs=["B/result.py"], engine_factory=factory)
    assert launched["ok"] and launched["work_dir"] == "B" and Path(launched["repo"]) == root
    assert "repository-relative" in workers[0].seed and "B/result.py" in workers[0].seed
    workers[0].produce({"B/result.py": "answer = 42\n"})
    first = await_job(cdir, launched["job"])
    assert first["check_ok"] is False and not first["landed"]
    assert first["recovery_snapshot"]["files"]["B/result.py"]["sha256"]
    assert ch.inspect(cdir, first["id"])["recovery"]["available"]
    fixed = ch.recover(cdir, first["id"], check=PASS)
    assert fixed["ok"] and fixed["worker_restarted"] is False
    final = await_job(cdir, first["id"], attempt=2)
    assert final["landed"] and final["verified"] and len(workers) == 1
    assert final["review"]["family"] == "chatgpt" and final["authors"] == ["claude"]
    assert (root / "B/result.py").read_text() == "answer = 42\n" and not (root / "A/result.py").exists()
    assert final["attempts"][0]["check"] == FAIL
    assert {"checking", "reviewing", "landing"} <= set(phases)
    assert final["phase"] == "outcome"
    collected = ch.collect(cdir, first["id"])
    assert collected["handoff"]["check_state"] == "passed" and collected["handoff"]["products"][0]["path"] == "B/result.py"
    assert ch.collect(cdir, first["id"])["handoff"]["id"] == collected["handoff"]["id"]
    assert not ch.collect(cdir, first["id"], first["handoff"]["id"])["ok"]


def test_full_brief_boundary_scope_and_temporary_destination(project):
    root, workers, factory = project
    brief = "a" * 7998 + "終%"
    out = cj.start(root / "A", root / "B", brief, PASS, engine_factory=factory)
    assert out["ok"] and cj.read_jobs(root / "A")[out["job"]]["brief"] == brief
    assert workers[0].seed.endswith(brief)
    refused = cj.start(root / "A", out["worktree"], "repair", PASS, engine_factory=factory)
    assert not refused["ok"] and "worktree" in refused["error"] and len(workers) == 1
    wrong = cj.start(root / "A", root / "B", "task", PASS, outputs=["A/no.py"], engine_factory=factory)
    assert not wrong["ok"] and len(workers) == 1
    workers[0].produce({"A/wrong.py": "bad = True"})
    done = await_job(root / "A", out["job"])
    assert not done["landed"] and "A/wrong.py" in done["unexpected"]


def test_recovery_refuses_changed_bytes_foreign_effort_and_unknown_liveness(project, monkeypatch):
    root, workers, factory = project
    out = cj.start(root / "A", root, "Produce file", FAIL, engine_factory=factory)
    assert not ch.recover(root / "A", out["job"], check=PASS)["ok"]  # live
    workers[0].produce({"B/result.py": "x = 1"})
    done = await_job(root / "A", out["job"])
    assert not ch.recover(root / "B", out["job"], check=PASS)["ok"]
    monkeypatch.setattr(ch, "observe", lambda job: {"state": "unknown"})
    assert "liveness" in ch.recover(root / "A", out["job"], check=PASS)["error"]
    monkeypatch.setattr(ch, "observe", lambda job: {"state": "completed"})
    Path(out["worktree"], "B/result.py").write_text("edited later", encoding="utf-8")
    assert "changed after completion" in ch.recover(root / "A", out["job"], check=PASS)["error"]
    assert len(workers) == 1 and not (root / "B/result.py").exists()


def test_second_job_can_finish_during_first_recovery_check(project, monkeypatch):
    root, workers, factory = project
    cdir = root / "A"
    a = cj.start(cdir, root, "first", FAIL, engine_factory=factory)
    workers[0].produce({"B/first.py": "first = 1"})
    await_job(cdir, a["job"])
    b = cj.start(cdir, root, "second", PASS, engine_factory=factory)
    checking, release = threading.Event(), threading.Event()
    run = cj.run_check
    def held(job, tree):
        if job["id"] == a["job"] and job.get("attempt") == 2:
            checking.set()
            assert release.wait(20)
        return run(job, tree)
    monkeypatch.setattr(cj, "run_check", held)
    assert ch.recover(cdir, a["job"], check=PASS)["ok"]
    assert checking.wait(5)
    assert not ch.recover(cdir, a["job"], check=PASS)["ok"]  # claim is exclusive
    try:
        workers[1].produce({"B/second.py": "second = 2"})
        second = await_job(cdir, b["job"])
        assert second["landed"] and not (root / "B/first.py").exists()
    finally:
        release.set()
    first = await_job(cdir, a["job"], attempt=2)
    assert first["landed"] and first["delta_review"]["verdict"] == "PASS"
    assert len(workers) == 2


def test_missing_reading_output_blocks_review_but_check_can_generate_it(project, monkeypatch):
    root, workers, factory = project
    monkeypatch.setattr(cj, "announce_kept", lambda *a: [])
    out = cj.start(root / "A", root / "B", "package B/report.pdf", PASS,
                   outputs=["B/report.pdf"], engine_factory=factory)
    workers[0].produce({"B/source.py": "x = 1"})
    done = await_job(root / "A", out["job"])
    assert done["check_ok"] is True and done["review"] is None and not done["landed"]
    assert done["missing_outputs"] == ["B/report.pdf"]
    # Exact existing missing declaration is pinned as absent; the corrected check may produce it.
    make = [sys.executable, "-c", "from pathlib import Path; Path('B/report.pdf').write_bytes(b'%PDF fixture')"]
    fixed = ch.recover(root / "A", out["job"], check=make)
    assert fixed["ok"]
    final = await_job(root / "A", out["job"], attempt=2)
    assert final["landed"] and (root / "B/report.pdf").read_bytes() == b"%PDF fixture"


def test_inspect_collect_routes_never_create_or_wake_engine(project, monkeypatch):
    root, workers, factory = project
    out = cj.start(root / "A", root, "task", FAIL, engine_factory=factory)
    workers[0].produce({"B/result.py": "x = 1"})
    await_job(root / "A", out["job"])
    def readonly(folder, **kw):
        assert kw.get("create") is False
        return None
    monkeypatch.setattr(sr, "get_engine", readonly)
    monkeypatch.setattr(maintenance, "is_active", lambda: True)
    view, status = sr.handle_post(str(root / "A"), "code_job", {"action": "inspect", "job": out["job"]})
    assert status == 200 and view["check_state"] == "failed"
    result, status = sr.handle_post(str(root / "A"), "code_job", {"action": "collect", "job": out["job"]})
    assert status == 200 and result["handoff"]["state"] == "collected"
    refusal, status = sr.handle_post(str(root / "A"), "code_job", {"action": "recover", "job": out["job"]})
    assert status == 409 and not refusal["ok"]


def test_cli_sends_scope_and_original_job_actions(monkeypatch, tmp_path, capsys):
    from tools import steward_code_job as cli
    sent = []
    monkeypatch.setattr(cli, "project_for", lambda cwd: ("fixture", "A"))
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def read(self):
            return b'{"ok":true}'
    def urlopen(request, **kw):
        sent.append(json.loads(request.data))
        return Response()
    monkeypatch.setattr(cli.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(sys, "argv", ["code_job", "start", "--repo", str(tmp_path), "--work-dir", "B",
                                    "--brief", "repair", "--check-argv", json.dumps(PASS), "--output", "B/result.py"])
    cli.main()
    assert sent[-1]["work_dir"] == "B" and sent[-1]["outputs"] == ["B/result.py"] and sent[-1]["dir"] == "A"
    for action in ("inspect", "recover", "collect"):
        monkeypatch.setattr(sys, "argv", ["code_job", action, "--job", "original"])
        cli.main()
        assert sent[-1]["action"] == action and sent[-1]["job"] == "original" and "repo" not in sent[-1]


@pytest.mark.skipif(os.name != "nt", reason="Windows junction behavior")
def test_actual_windows_junctions_cannot_escape_copy_scope_or_destination(project, tmp_path, monkeypatch):
    root, workers, factory = project
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private.pdf").write_bytes(b"outside")
    alias = root / "B/link"
    subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(alias), str(outside)], check=True,
                   capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    with pytest.raises(ValueError):
        cj._output_path(root, "B/link/private.pdf")
    assert not cj.start(root / "A", root / "B", "task", PASS, outputs=["B/link/private.pdf"], engine_factory=factory)["ok"]
    job = cj.start(root / "A", root, "task", PASS, engine_factory=factory)
    temp_alias = tmp_path / "job-alias"
    subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(temp_alias), job["worktree"]], check=True,
                   capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    assert not cj.start(root / "A", temp_alias, "repair", PASS, engine_factory=factory)["ok"]
    # A kept-copy destination junction must not write to its target either.
    cdir = tmp_path / "receipts"
    cdir.mkdir()
    subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(cdir / "code-job-outputs"), str(outside)],
                   check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    from steward_cockpit import steward_engine as se
    monkeypatch.setattr(se, "_default_record", lambda folder: lambda *args: True)
    source = Path(job["worktree"], "B/reading.pdf")
    source.write_bytes(b"%PDF kept bytes")
    kept = {"id": job["job"], "kept_worktree": job["worktree"], "files": ["B/reading.pdf"], "outputs": ["B/reading.pdf"]}
    assert not cj.announce_kept(cdir, kept)
    assert kept["kept_delivery"]["errors"] and not (outside / job["job"]).exists()


def test_notify_ack_crash_retries_same_durable_result_without_another_turn(tmp_path, monkeypatch):
    from steward_cockpit import steward_engine as se
    cdir = tmp_path / "effort"
    cdir.mkdir()
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.setattr(maintenance, "is_active", lambda: False)
    durable = {}
    def persist(key, patch):
        durable.update(patch)
        return True
    monkeypatch.setattr(se, "_update_state", persist)
    eng = se.Engine.__new__(se.Engine)
    eng.dir, eng.general, eng.tid, eng._lock = str(cdir), False, None, threading.RLock()
    eng.queue, eng.accepted_job_results, eng.job_results_paused, eng.busy = [], {}, False, True
    eng.alive = lambda: True
    eng._emit = lambda *a: None
    job = {"id": "job", "repo": str(tmp_path), "steward_dir": str(cdir), "status": "done", "attempt": 1, "check_ok": None}
    cj._write_job(cdir, job)
    result = ch.save_result(cdir, job, "Check not run; inspect saved artifacts.")
    assert result["check_state"] == "not_run"
    original = ch._handoff_update
    once = [True]
    def lose_ack(*a, **kw):
        if kw.get("state") == "queued" and once and once.pop():
            raise OSError("injected crash after durable accept")
        return original(*a, **kw)
    monkeypatch.setattr(ch, "_handoff_update", lose_ack)
    assert not ch.notify(cdir, "job", engine=eng)
    assert len(eng.queue) == 1 and cj.read_jobs(cdir)["job"]["handoff"]["state"] == "pending"
    # Recreated engine uses the same durable queue and accepted identity.
    eng.queue = list(durable["pending_queue"])
    eng.accepted_job_results = dict(durable["accepted_job_results"])
    assert ch.notify(cdir, "job", engine=eng) and len(eng.queue) == 1
    first = ch.collect(cdir, "job")
    assert ch.collect(cdir, "job") == first
    job["attempt"] = 2
    cj._transition(cdir, "job", ("done",), attempt=2)
    later = ch.save_result(cdir, job, "Later attempt of same job; collect current before acting.")
    assert later["id"] != result["id"] and ch.notify(cdir, "job", engine=eng) and len(eng.queue) == 2
    assert not ch.collect(cdir, "job", result["id"])["ok"]


def test_reused_pid_is_unknown_but_absent_pid_with_completed_receipt_is_recoverable(monkeypatch):
    import proc_probe
    monkeypatch.setattr(sr, "get_engine", lambda *a, **k: None)
    job = {"id": "j", "worktree": "unused", "steward_dir": "unused", "worker_completed_at": 100,
           "worker_pid": 123, "worker_birth": 20}
    monkeypatch.setattr(proc_probe, "probe_status", lambda pid: (proc_probe.PROBE_RUNNING, 30, "different"))
    assert ch.observe(job)["state"] == "unknown"
    monkeypatch.setattr(proc_probe, "probe_status", lambda pid: (proc_probe.PROBE_UNKNOWN, None, None))
    monkeypatch.setattr(proc_probe, "pid_alive_via_enum", lambda pid: None)
    assert ch.observe(job)["state"] == "unknown"
    monkeypatch.setattr(proc_probe, "pid_alive_via_enum", lambda pid: False)
    assert ch.observe(job)["state"] == "completed"
    job.pop("worker_completed_at")
    assert ch.observe(job)["state"] == "dead"
    assert "completed-worker" in ch.recovery_error({**job, "status": "failed"})


def test_controller_phase_overrides_finished_foreman_and_skill_never_hides_failed_check():
    from steward_cockpit import steward_campaign as sc
    job = {"id": "j", "skill": "Foreman", "worker": "foreman", "status": "finishing",
           "phase": "reviewing", "phase_at": 321, "started_epoch": 100}
    native = sc._code_job_native(job, 500)
    assert native["phase"] == "reviewing" and native["phase_at"] == 321 and not native["stopped"]
    assert cj.stage_line(job) == "Foreman: reviewing"
    done = {**job, "status": "done", "phase": "outcome", "files": ["report.pdf"], "check": PASS, "check_ok": False}
    assert "check failed" in cj.stage_line(done) and "finished" not in cj.stage_line(done)
    done["check_ok"] = None
    assert "not checked" in cj.stage_line(done)


def test_stale_controller_cannot_overwrite_a_new_attempt_and_unjoined_finalizer_blocks_recovery(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))
    job = {"id": "j", "status": "finishing", "attempt": 2, "steward_dir": str(tmp_path), "phase": "checking"}
    cj._write_job(tmp_path, job)
    assert cj._transition(tmp_path, "j", ("finishing",), expect_attempt=1, status="done") is None
    assert cj.phase({**job, "attempt": 1}, "landing") is None
    assert cj.read_jobs(tmp_path)["j"]["phase"] == "checking"
    assert "prior controller" in ch.recovery_error({"status": "failed", "finalizer_active": True})


def test_observed_controller_phase_never_invents_or_rebases_a_clock(monkeypatch, tmp_path):
    from steward_cockpit import steward_campaign as sc
    monkeypatch.setattr(sc, "typical_duration_s", lambda *a: None)
    job = {"id": "j", "title": "task", "phase": "checking", "status": "finishing", "minutes": 90,
           "started_epoch": 100, "native": {"phase": "checking", "phase_at": 200, "stopped": False,
           "estimates": [], "liveness": "unknown"}}
    eta, source = sc._code_job_eta(job, 6000)
    assert "no current" in eta and "rebased" not in eta and "earliest_at" not in source
    who, phase, start, tests, finish = sc.who_is_working(tmp_path, {}, [job], None, now=6000)
    assert "liveness is unknown" in who and "no current" in finish
    monkeypatch.setattr(sc, "typical_duration_s", lambda *a: 500)
    first = sc.who_is_working(tmp_path, {}, [job], None, now=6000)[-1]
    later = sc.who_is_working(tmp_path, {}, [job], None, now=7000)[-1]
    assert first == later and "exceeded" in first
