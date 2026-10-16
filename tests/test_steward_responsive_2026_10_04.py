"""Steward responsiveness (Ecgberht/planning/steward-responsiveness-2026-10-04, John 2026-10-04, PLAN v0.2 approved):
R1 the queued receipt and Take this now; R2 small by default (the contract split, the effort switch, the step cap);
R3 the code job (a coder in its own worktree, best model at full effort, lands when clean, wakes the steward; one
writer; stop). Hermetic: temp folders, a temp git repo, fake engines; never the live server or a real model."""
import json
import sys
import subprocess
import time
from pathlib import Path

import pytest

from steward_cockpit import code_jobs, steward_engine


@pytest.fixture
def eng(monkeypatch, tmp_path):
    monkeypatch.setattr(steward_engine, "STATE_FILE", tmp_path / "state.json")
    return steward_engine.Engine(str(tmp_path), fake=True)


# ---------- R2: the contract ----------
def test_small_duty_comes_first_and_the_effort_rules_ride_only_with_an_effort(eng, tmp_path, monkeypatch):
    c = eng._contract()
    assert c.startswith("SIZE THE REQUEST FIRST") and "tools/steward_code_job.py start" in c
    assert "(13) SLICE LOOP" not in c, "no effort here: the heavy rules stay off"
    # 2026-10-07 (execution minimum item 4): the register/link rule is in the BASE contract; small work finishes in
    # the turn; code goes to a reviewed code job; no forced hand-off, no Foreman, no invented validator
    assert "THE DELIVERABLES REGISTER" in c and "Do not invent a validator" in c and "Crucible is on hold" in c
    assert "Commission it now" not in c and "Do not finish the work inline" not in c
    d = tmp_path / "mid-effort"; d.mkdir()
    (d / "roadmap.json").write_text(json.dumps({"roadmap_projection": [{"id": "a", "status": "active"}]}), encoding="utf-8")
    e2 = steward_engine.Engine(str(d), fake=True)
    c2 = e2._contract()
    assert e2.effort_on() and c2.startswith("THIS IS AN EFFORT") and "(13) SLICE LOOP" in c2 and "SIZE THE REQUEST FIRST" not in c2,         "a cockpit mid-effort keeps its rules, and the small-change prohibitions do not ride with them (Grok code F5)"
    steward_engine._update_state(e2.skey(), {"effort_mode": False})
    assert not e2.effort_on(), "his word wins"
    d3 = tmp_path / "proposed"; d3.mkdir()
    (d3 / "roadmap.json").write_text(json.dumps({"roadmap_projection": [{"id": "a", "status": "proposed"}]}), encoding="utf-8")
    assert not steward_engine.Engine(str(d3), fake=True).effort_on(), "a merely proposed step is not an effort"
    eng.code_job = {"cdir": "x", "id": "j"}
    assert eng._contract() == steward_engine.CODER_CONTRACT


def test_the_cave_and_the_star_chart_are_small_by_default(eng, tmp_path):
    (tmp_path / "roadmap.json").write_text(json.dumps({"roadmap_projection": [{"id": "g", "status": "active"}]}), encoding="utf-8")
    eng.one_conversation = True
    assert not eng.effort_on()


def test_his_words_switch_the_mode():
    assert steward_engine._EFFORT_ON.search("ok, make this an effort please")
    assert steward_engine._EFFORT_OFF.search("back to small")
    assert steward_engine._STOP_CODER.match("Stop the coder") and not steward_engine._STOP_CODER.match("stop")


def test_the_fifteenth_step_says_progress_and_the_turn_goes_on(eng, monkeypatch):
    """2026-10-07 (execution minimum item 4, Grok ruling): at the 15th tool call of a turn John started, ONE progress
    line - the turn is never ended and no job is started because of the count (in small mode or an effort)."""
    eng.fake = False
    eng.busy = True
    eng._turn_origin = "human"
    calls, said = [], []
    monkeypatch.setattr(eng, "_interrupt_turn_locked", lambda reason: calls.append(reason) or {"ok": True})
    monkeypatch.setattr(eng, "_wake_locked", lambda *a, **k: calls.append("wake") or (True, ""))
    monkeypatch.setattr(eng, "_emit", lambda ev: said.append(ev))
    for n in range(1, steward_engine.STEP_CAP + 8):
        eng._turn_tools = n
        assert eng._guard_turn({"name": "exec_command", "input": {}}) is False
    assert calls == [] and not eng.queue, "never ended, never handed off"
    progress = [ev for ev in said if ev.get("t") == "sys" and ev.get("text", "").startswith("still working")]
    assert len(progress) == 1 and ("%d steps" % steward_engine.STEP_CAP) in progress[0]["text"]
    steward_engine._update_state(eng.skey(), {"effort_mode": True})
    eng._progress_said, said[:] = False, []
    eng._turn_tools = steward_engine.STEP_CAP
    assert eng._guard_turn({"name": "exec_command", "input": {}}) is False and calls == []


def test_a_skill_job_report_queued_is_never_delivered_as_johns(eng, monkeypatch):
    eng.busy = True
    monkeypatch.setattr(eng, "_persist_queue", lambda: True)
    eng.say("Here is a plain report with no marker", human=False)
    assert steward_engine._is_machine_text(eng.queue[-1]), "the machine flag rides in the persisted entry"
    assert steward_engine._is_machine_text("(skill job 7 finished - not John) gandalf: done (exit 0).")


# ---------- R1: the receipt ----------
def test_the_queued_receipt_names_what_the_steward_is_on_and_since_when(eng):
    eng.steward = "Aladdin"
    eng.turn_started = time.time() - 34 * 60
    eng.turn_text = "I'll make the tile border thinner and pulse it. Then I check it."
    eng.queue = ["his message"]
    r = eng._queued_receipt()
    assert r.startswith("Aladdin is on: I'll make the tile border thinner and pulse it., since ") and "(34 min)" in r and r.endswith("Your message is next.")
    eng.turn_text = ""
    eng._turn_words = "fix the dots on the tiles"      # 2026-10-08: the receipt quotes his recorded words, not the sent text
    assert "your message “fix the dots on the tiles”" in eng._queued_receipt()


def test_take_now_interrupts_then_wakes_on_the_queue(eng, monkeypatch):
    calls = []
    eng.busy = True
    eng.queue = ["his words"]
    monkeypatch.setattr(eng, "_interrupt_turn_locked", lambda reason: calls.append(reason) or {"ok": True})
    monkeypatch.setattr(eng, "_wake_locked", lambda fresh, seed: calls.append(("wake", fresh)) or (True, "awake"))
    assert eng.take_now()["ok"] and calls == ["John: take this now", ("wake", False)]
    eng.busy = False
    assert eng.take_now()["ok"] is False


def test_the_page_shows_the_button():
    js = (Path(__file__).resolve().parent.parent / "steward_cockpit" / "static" / "shared.js").read_text(encoding="utf-8")
    assert "if (ev.take_now)" in js and 'post("/api/engine", { action: "take_now" })' in js


# ---------- R3: the code job ----------
def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(repo), *args], check=True)
    (repo / "a.txt").write_text("one\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "start"], check=True)
    return repo


@pytest.fixture(autouse=True)
def _code_job_seats(monkeypatch):
    """2026-10-07 (execution minimum item 3): a code job lands only after another family's review of the exact
    candidate; here the reviewer is tests/fake_review.py (ANCHOR_REVIEW_CMD) and the coder's family is fixed."""
    monkeypatch.setenv("ANCHOR_REVIEW_CMD", json.dumps([sys.executable, str(Path(__file__).with_name("fake_review.py"))]))
    monkeypatch.setattr(code_jobs, "choose_coder", lambda requested="": ((requested or "claude"), None))


class FakeCoder:
    """Stands in for the workbench engine: on wake it does the brief (writes a file with its file tool, so the
    file is in its manifest) and ends its turn."""
    def __init__(self, wt, content="two\n"):
        self.wt, self.content, self.on_turn_done, self.code_job, self.seed = wt, content, None, None, None
        self.files, self.written_ok, self.cli = [], [], "claude"   # completed writes + the family that served it

    def wake(self, fresh=False, seed=None):
        self.seed = seed
        Path(self.wt, "a.txt").write_text(self.content, encoding="utf-8")
        self.written_ok.append(str(Path(self.wt, "a.txt")))
        self.on_turn_done({"text": "Changed a.txt to two; checked it.", "error": ""})
        return True, "awake"

    def stop(self):
        pass


def _wait(cdir, job, status=("done", "failed", "stopped"), s=20):
    for _ in range(int(s * 10)):
        j = code_jobs.read_jobs(cdir).get(job) or {}
        if j.get("status") in status:
            return j
        time.sleep(0.1)
    raise AssertionError(code_jobs.read_jobs(cdir))


def test_a_code_job_runs_in_its_worktree_lands_when_clean_and_wakes_the_steward(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))
    reports = []
    monkeypatch.setattr(code_jobs, "_report", lambda cdir, job: reports.append(job))
    repo, cdir = _repo(tmp_path), tmp_path / "steward"
    cdir.mkdir()
    coders = []
    out = code_jobs.start(str(cdir), str(repo), "Change a.txt to say two.", "python -c \"import sys; sys.exit(0 if open('a.txt').read()=='two\\n' else 1)\"",
                          engine_factory=lambda wt: coders.append(FakeCoder(wt)) or coders[-1])
    assert out["ok"], out
    job = _wait(str(cdir), out["job"])
    assert job["status"] == "done" and job["check_ok"] is True and job["landed"] is True and job["files"] == ["a.txt"]
    assert (repo / "a.txt").read_text(encoding="utf-8") == "two\n", "landed in the repository"
    assert "Change a.txt to say two." in coders[0].seed and "Do not commit" in coders[0].seed
    assert job["review"]["verdict"] == "PASS" and job["review"]["family"] == "chatgpt"   # another family passed it
    for _ in range(50):
        if reports:
            break
        time.sleep(0.1)
    assert reports and reports[0]["id"] == out["job"], "the steward is woken with the result"
    assert not Path(job["worktree"]).exists(), "the worktree goes once landed"


def test_one_writer_and_a_dirty_repository_is_not_overwritten(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.setattr(code_jobs, "_report", lambda cdir, job: None)
    repo, cdir = _repo(tmp_path), tmp_path / "steward"
    cdir.mkdir()
    (repo / "a.txt").write_text("his own edit\n", encoding="utf-8")       # uncommitted work in the repository
    out = code_jobs.start(str(cdir), str(repo), "Change a.txt.", [sys.executable, "-c", "pass"], engine_factory=lambda wt: FakeCoder(wt))
    job = _wait(str(cdir), out["job"])
    assert job["landed"] is False and "has uncommitted edits in" in job["land_note"]
    assert (repo / "a.txt").read_text(encoding="utf-8") == "his own edit\n", "his work is untouched"


def test_a_second_job_on_the_same_repository_runs_too_and_stop_keeps_the_branch(tmp_path, monkeypatch):
    # John 2026-10-09: several jobs may run on one repository (own worktrees; landings one at a time under the lock)
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))

    class Slow(FakeCoder):
        def wake(self, fresh=False, seed=None):
            return True, "awake"                                          # still working
    repo, cdir = _repo(tmp_path), tmp_path / "steward"
    cdir.mkdir()
    first = code_jobs.start(str(cdir), str(repo), "Long work.", [sys.executable, "-c", "pass"], engine_factory=lambda wt: Slow(wt))
    assert first["ok"] and code_jobs.active_repos(str(cdir)) == [code_jobs._norm(repo)]
    again = code_jobs.start(str(cdir), str(repo), "More.", [sys.executable, "-c", "pass"], engine_factory=lambda wt: Slow(wt))
    assert again["ok"] and again["worktree"] != first["worktree"]
    assert code_jobs.active_repos(str(cdir)) == [code_jobs._norm(repo)]
    assert code_jobs.stop(str(cdir), first["job"])["ok"] and code_jobs.read_jobs(str(cdir))[first["job"]]["status"] == "stopped"
    assert code_jobs.active_repos(str(cdir)) == [code_jobs._norm(repo)], "the second job still works there"
    assert code_jobs.stop(str(cdir), again["job"])["ok"] and not code_jobs.active_repos(str(cdir))


def test_the_route_and_the_tool_exist():
    root = Path(__file__).resolve().parent.parent
    routes = (root / "steward_cockpit" / "steward_routes.py").read_text(encoding="utf-8")
    assert 'if verb == "code_job":' in routes and 'if action == "take_now":' in routes
    assert (root / "tools" / "steward_code_job.py").is_file() and (root / "tools" / "turn_profile.py").is_file()


def test_machine_text_gets_no_receipt_and_is_delivered_as_control(eng, monkeypatch):
    sent = []
    eng.busy = True
    monkeypatch.setattr(eng, "_persist_queue", lambda: True)
    eng.say("(code job 1 finished - not John) Status: done.", human=False)
    assert not any(ev.get("take_now") for ev in getattr(eng, "events", [])), "no receipt or button for machine text"
    eng.busy = False
    monkeypatch.setattr(eng, "_send_locked", lambda text, origin="human", **kw: sent.append(origin) or True)
    eng._deliver_next_queued_locked()
    assert sent == ["control"], "a job report never counts as his turn (no cap, no receipt)"


def test_a_coder_that_commits_its_own_work_is_kept_and_landed(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.setattr(code_jobs, "_report", lambda cdir, job: None)

    class Committer(FakeCoder):
        def wake(self, fresh=False, seed=None):
            Path(self.wt, "a.txt").write_text("committed by the coder\n", encoding="utf-8")
            self.written_ok.append(str(Path(self.wt, "a.txt")))
            subprocess.run(["git", "-C", self.wt, "commit", "-qam", "coder"], check=True)
            self.on_turn_done({"text": "done", "error": ""})
            return True, "awake"
    repo, cdir = _repo(tmp_path), tmp_path / "steward"
    cdir.mkdir()
    out = code_jobs.start(str(cdir), str(repo), "Change a.txt.", [sys.executable, "-c", "pass"], engine_factory=lambda wt: Committer(wt))
    job = _wait(str(cdir), out["job"])
    assert job["files"] == ["a.txt"] and job["landed"] is True, "the coder's own commit is the change (Grok code F1)"
    assert (repo / "a.txt").read_text(encoding="utf-8") == "committed by the coder\n"


def test_stop_keeps_the_branch_and_the_report_wakes_the_real_steward(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))

    class Slow(FakeCoder):
        def wake(self, fresh=False, seed=None):
            Path(self.wt, "a.txt").write_text("half done\n", encoding="utf-8")
            return True, "awake"
    repo, cdir = _repo(tmp_path), tmp_path / "steward"
    cdir.mkdir()
    out = code_jobs.start(str(cdir), str(repo), "Long work.", [sys.executable, "-c", "pass"], engine_factory=lambda wt: Slow(wt))
    assert code_jobs.stop(str(cdir))["ok"]
    branches = subprocess.run(["git", "-C", str(repo), "branch", "--list", "steward-job-*"], capture_output=True, text=True).stdout
    assert out["branch"] in branches, "his stop keeps the work on its branch"
    assert code_jobs.finish(str(cdir), out["job"], {"text": "late", "error": ""}) is None and         code_jobs.read_jobs(str(cdir))[out["job"]]["status"] == "stopped", "a late result never finishes a stopped job"
    said = []

    class Steward:
        dir = str(cdir)
        general = False
        def alive(self): return True
        def enqueue_job_result(self, identity, text):
            said.append((text, identity))
            return {"ok": True}
    from steward_cockpit import steward_routes
    monkeypatch.setattr(steward_routes, "get_engine", lambda cdir, *a, **k: Steward())
    job = {"id": "j1", "status": "done", "repo": str(repo), "steward_dir": str(cdir), "files": ["a.txt"],
           "land_note": "landed on x", "summary": "did it"}
    code_jobs._write_job(cdir, job)
    code_jobs._report(str(cdir), job)
    assert said and said[0][1].startswith("j1:1:") and said[0][0].startswith("(code job j1, attempt 1 result - not John)")
    assert code_jobs.read_jobs(cdir)["j1"]["handoff"]["state"] == "queued"


def test_jobs_from_two_stewards_share_a_repository_and_the_path_boundary_holds(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))

    class Slow(FakeCoder):
        def wake(self, fresh=False, seed=None):
            return True, "awake"
    repo = _repo(tmp_path)
    a, b = tmp_path / "cave", tmp_path / "star"
    a.mkdir(); b.mkdir()
    assert code_jobs.start(str(a), str(repo), "One.", [sys.executable, "-c", "pass"], engine_factory=lambda wt: Slow(wt))["ok"]
    other = code_jobs.start(str(b), str(repo), "Two.", [sys.executable, "-c", "pass"], engine_factory=lambda wt: Slow(wt))
    assert other["ok"], "another steward may start a job on the same repository (John 2026-10-09)"
    assert code_jobs.inside(str(repo / "x.py"), str(repo)) and not code_jobs.inside(str(repo) + "-wt/x.py", str(repo))


# ---------- Grok code review R2 ----------
def test_four_stewards_starting_at_once_each_get_their_own_worktree(tmp_path, monkeypatch):
    import threading as _th
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))

    class Slow(FakeCoder):
        def wake(self, fresh=False, seed=None):
            return True, "awake"
    repo = _repo(tmp_path)
    outs = []
    dirs = [tmp_path / ("s%d" % k) for k in range(4)]
    for d in dirs:
        d.mkdir()
    ts = [_th.Thread(target=lambda d=d: outs.append(code_jobs.start(str(d), str(repo), "Go.", [sys.executable, "-c", "pass"], engine_factory=lambda wt: Slow(wt)))) for d in dirs]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sum(1 for o in outs if o.get("ok")) == 4, outs
    assert len({o["worktree"] for o in outs}) == 4 and len(code_jobs._busy_read()) == 4


def test_effort_mode_follows_the_current_roadmap_unless_he_said(eng, tmp_path):
    rm = tmp_path / "roadmap.json"
    rm.write_text(json.dumps({"roadmap_projection": [{"id": "a", "status": "proposed"}]}), encoding="utf-8")
    assert not eng.effort_on()
    rm.write_text(json.dumps({"roadmap_projection": [{"id": "a", "status": "active"}]}), encoding="utf-8")
    assert eng.effort_on(), "read fresh, never a stale first guess"
    rm.write_text(json.dumps({"roadmap_projection": [{"id": "a", "status": "done"}]}), encoding="utf-8")
    assert not eng.effort_on(), "the cap returns when the effort is done"


def test_reads_are_not_writes():
    W = steward_engine._WRITE_VERBS
    for read in ("git status 2>&1", "x >= 3", "rg -n 'a->b' f", "cat a.txt"):
        assert not W.search(read), read
    for write in ("echo hi > C:/dev/Anchor/x.txt", "Path(p).write_text(s)", "git commit -m x"):
        assert W.search(write), write


# ---------- Grok code review R3 ----------
def test_a_git_failure_in_finish_keeps_the_work(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.setattr(code_jobs, "_report", lambda cdir, job: None)
    real = code_jobs._git

    def flaky(repo, *args, **kw):
        if tuple(args[:2]) == ("--literal-pathspecs", "add"):   # the job staging its own files
            return 1, "", "git add timed out after 600s"
        return real(repo, *args, **kw)
    monkeypatch.setattr(code_jobs, "_git", flaky)
    repo, cdir = _repo(tmp_path), tmp_path / "steward"
    cdir.mkdir()
    out = code_jobs.start(str(cdir), str(repo), "Change a.txt.", [sys.executable, "-c", "pass"], engine_factory=lambda wt: FakeCoder(wt))
    job = _wait(str(cdir), out["job"])
    assert job["status"] == "failed" and "git add failed" in job["error"] and job["landed"] is False
    assert Path(job["worktree"], "a.txt").read_text(encoding="utf-8") == "two\n", "the coder's uncommitted work is kept"


def test_numbered_redirects_are_writes():
    W = steward_engine._WRITE_VERBS
    assert W.search("python x.py 2>err.txt") and W.search("cmd 1>out.txt")
    assert not W.search("git status 2>&1") and not W.search("ls >&2")
