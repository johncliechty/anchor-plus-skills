"""Foreman as a code job's worker (John 2026-10-09: "route Foreman through the code-job path"). The final review of
the night of 2026-10-10 held Foreman because, started as a skill job, it wrote the project directly. Now it builds
inside the job's own worktree and its work goes through the code job's finish: the job's check, a review by a family
that wrote none of it, and the locked, verified landing. Its writing seats are pinned to Claude (a private copy of the
settings), and it runs inside a kill-on-close Windows Job Object, so Stop - or Anchor's own end - takes every process
it started. Foreman is never a skill job. Several jobs may share one repository (John 2026-10-09). Hermetic: a fake
run-live.mjs (tests/fake_foreman.mjs) and the fake reviewer (tests/fake_review.py); throwaway repositories only."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from steward_cockpit import code_jobs, skill_jobs  # noqa: E402

FAKE = ROOT / "tests" / "fake_foreman.mjs"
PASS = [sys.executable, "-c", "pass"]
PLAN = "# Plan\n\n## Wave 1 - change a.txt\n\nWrite two.\n"
WINDOWS = pytest.mark.skipif(sys.platform != "win32", reason="the Job Object is Windows containment")


def _repo(root, files=None):
    root.mkdir(parents=True)
    for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(root), *args], check=True)
    for name, text in (files or {"a.txt": "one\n"}).items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "start"], check=True)
    return root


@pytest.fixture
def env(tmp_path, monkeypatch):
    import anchor_settings
    monkeypatch.setattr(code_jobs, "_report", lambda cdir, job: None)
    monkeypatch.setattr(code_jobs, "FOREMAN_RUN_LIVE", FAKE)
    monkeypatch.setattr(anchor_settings, "get_launch_settings",       # the dashboard: ChatGPT codes, ChatGPT reviews
                        lambda: dict(anchor_settings.DEFAULTS, coding_family="chatgpt", review_family="chatgpt",
                                     default_cli="codex"))
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.setenv("ANCHOR_REVIEW_CMD", json.dumps([sys.executable, str(ROOT / "tests" / "fake_review.py")]))
    monkeypatch.setenv("FAKE_REVIEW_LOG", str(tmp_path / "review.log"))
    monkeypatch.setenv("FAKE_FOREMAN_LOG", str(tmp_path / "foreman.log"))
    monkeypatch.setenv("TRIO_DRIVER_EXECUTE", "chatgpt-cli")              # never reaches Foreman
    monkeypatch.delenv("ANCHOR_FOREMAN_CODE_JOBS", raising=False)
    monkeypatch.delenv("ANCHOR_UNCONFINED_CODERS", raising=False)
    repo, cdir = _repo(tmp_path / "repo"), tmp_path / "steward"
    cdir.mkdir()
    return repo, cdir, tmp_path


def _wait(cdir, job_id):
    for _ in range(600):
        j = code_jobs.read_jobs(str(cdir)).get(job_id) or {}
        if j.get("status") in ("done", "failed", "stopped"):
            return j
        time.sleep(0.1)
    raise AssertionError("the job never finished")


def _start(repo, cdir, **kw):
    kw.setdefault("check", PASS)
    return code_jobs.start(str(cdir), str(repo), "Change a.txt to two.", kw.pop("check"), worker="foreman", **kw)


def _tracked(repo):
    return subprocess.run(["git", "-C", str(repo), "ls-files"], capture_output=True, text=True, check=True).stdout.split()


def _log(tmp):
    return [json.loads(x) for x in (tmp / "foreman.log").read_text(encoding="utf-8").splitlines()]


def _alive(pid):
    out = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid, "/NH"], capture_output=True, text=True).stdout
    return str(pid) in out


def _until(cond, s=10):
    for _ in range(int(s * 10)):
        if cond():
            return True
        time.sleep(0.1)
    return False


# ---- the protected lifecycle ----

def test_foreman_builds_in_the_worktree_and_lands_only_through_check_and_review(env):
    repo, cdir, tmp = env
    out = _start(repo, cdir)
    assert out["ok"] and out["worker"] == "foreman", out
    job = _wait(cdir, out["job"])
    assert job["landed"] is True, job["land_note"]
    assert job["worker"] == "foreman" and job["skill"] == "Foreman" and job["foreman_profile"] == "slim"
    assert job["files"] == ["a.txt"] and job["authors"] == ["claude"] and job["coder_family"] == "claude"
    assert job["check_ok"] is True and job["review"]["verdict"] == "PASS"
    assert (repo / "a.txt").read_text(encoding="utf-8") == "two\n"
    assert _tracked(repo) == ["a.txt"]                                   # Anchor's documents and config never land
    call = _log(tmp)[0]
    assert call["argv"][0] == job["worktree"] and call["argv"][1:] == ["--profile", "slim"]    # never --git
    assert call["docs"]["plan"] == ".foreman-job/IMPLEMENTATION-PLAN.md" and call["profile"] == "slim"
    assert "## Wave 1" in call["plan"] and "test-command:" in call["plan"]
    review = json.loads((tmp / "review.log").read_text(encoding="utf-8").splitlines()[0])
    assert review[review.index("--author-family") + 1] == "claude"


def test_foremans_writers_are_pinned_to_claude_whatever_the_dashboard_says(env):
    # fcj review r2 BLOCKER 1: a private copy of the settings - its Coder seat and terminal are Claude, the
    # Reviewer seat stays the dashboard's; the dashboard's own settings are only read
    repo, cdir, tmp = env
    _wait(cdir, _start(repo, cdir)["job"])
    s = _log(tmp)[0]["settings"]
    assert s["coding_family"] == "claude" and s["default_cli"] == "claude" and s["review_family"] == "chatgpt"


def test_a_claude_reviewer_seat_means_no_foreman_job(env, monkeypatch):
    repo, cdir, _ = env
    import anchor_settings
    monkeypatch.setattr(anchor_settings, "get_launch_settings", lambda: dict(anchor_settings.DEFAULTS, review_family="claude"))
    out = _start(repo, cdir)
    assert not out["ok"] and "Reviewer seat is Claude" in out["error"]


def test_the_reviewer_is_told_every_new_file_foreman_added(env, monkeypatch):
    # fcj r2 MAJOR 5, John's call: no per-file record from Foreman, so the landing reviewer checks each new file
    repo, cdir, tmp = env
    monkeypatch.setenv("FAKE_FOREMAN_MODE", "new-file")
    job = _wait(cdir, _start(repo, cdir)["job"])
    assert job["landed"] is True and sorted(job["files"]) == ["a.txt", "b.py"], job["land_note"]
    review = json.loads((tmp / "review.log").read_text(encoding="utf-8").splitlines()[0])
    brief = Path(review[review.index("--brief-file") + 1]).read_text(encoding="utf-8")
    assert "base): b.py." in brief and "byproduct" in brief


def test_an_approved_plan_is_used_as_written_with_the_check_as_its_gate(env):
    repo, cdir, tmp = env
    job = _wait(cdir, _start(repo, cdir, plan=PLAN, profile="standard")["job"])
    assert job["landed"] is True and job["plan_given"] is True, job["land_note"]
    call = _log(tmp)[0]
    plan = call["plan"].replace(chr(13), "")
    assert plan.endswith(PLAN) and plan.startswith("test-command: `")
    assert call["argv"][1:] == ["--profile", "standard"]


def test_a_halted_run_never_lands_and_its_work_is_kept(env, monkeypatch):
    repo, cdir, _ = env
    monkeypatch.setenv("FAKE_FOREMAN_MODE", "halt")
    job = _wait(cdir, _start(repo, cdir)["job"])
    assert job["landed"] is False and job["status"] == "failed"
    assert "Foreman HALT" in job["error"] and "no-progress" in job["error"]
    assert (repo / "a.txt").read_text(encoding="utf-8") == "one\n"
    assert (Path(job["kept_worktree"]) / "a.txt").read_text(encoding="utf-8") == "two\n"


def test_a_review_by_the_writing_family_never_lands(env, monkeypatch):
    repo, cdir, _ = env
    monkeypatch.setenv("FAKE_REVIEW_FAMILY", "claude")
    job = _wait(cdir, _start(repo, cdir)["job"])
    assert job["landed"] is False and "author's own family" in job["land_note"]


def test_a_failing_check_never_lands(env):
    repo, cdir, _ = env
    job = _wait(cdir, _start(repo, cdir, check=[sys.executable, "-c", "raise SystemExit(1)"])["job"])
    assert job["landed"] is False and "check failed" in job["land_note"]


def test_a_write_into_the_source_repository_blocks_the_landing(env, monkeypatch):
    repo, cdir, _ = env
    monkeypatch.setenv("FAKE_FOREMAN_MODE", "stray")
    monkeypatch.setenv("FAKE_FOREMAN_STRAY", str(repo / "stray.py"))
    job = _wait(cdir, _start(repo, cdir)["job"])
    assert job["landed"] is False and "stray.py" in job["land_note"]


def test_several_jobs_run_on_one_repository_and_each_lands(env, monkeypatch):
    # John 2026-10-09: no one-job-per-repository rule; landings take the commit lock one at a time
    repo, cdir, _ = env
    monkeypatch.setenv("FAKE_FOREMAN_MODE", "own")
    a, b = _start(repo, cdir), _start(repo, cdir)
    assert a["ok"] and b["ok"], (a, b)
    ja, jb = _wait(cdir, a["job"]), _wait(cdir, b["job"])
    assert ja["landed"] is True and jb["landed"] is True, (ja["land_note"], jb["land_note"])
    assert sorted(_tracked(repo)) == sorted(["a.txt", "out-%s.txt" % a["job"], "out-%s.txt" % b["job"]])


# ---- containment: Stop, stragglers, restarts ----

@WINDOWS
def test_stop_ends_every_process_foreman_started_and_sees_them_gone(env, monkeypatch):
    repo, cdir, _ = env
    monkeypatch.setenv("FAKE_FOREMAN_MODE", "sleep")
    out = _start(repo, cdir)
    wt = Path(out["worktree"])
    assert _until(lambda: (wt / ".foreman" / "child.pid").exists())
    child = int((wt / ".foreman" / "child.pid").read_text())
    run = code_jobs._FOREMAN_PROCS[out["job"]]
    from steward_cockpit import steward_routes
    assert "foreman:" + out["job"] in steward_routes._running_job_ids()
    res = code_jobs.stop(str(cdir), out["job"], actor="John")
    assert res["ok"], res
    assert run.proc.poll() is not None and not _alive(child)             # the grandchild too
    job = code_jobs.read_jobs(str(cdir))[out["job"]]
    assert job["status"] == "stopped" and not job.get("landed")
    assert not (wt / "foreman.config.json").exists()                    # Anchor's file goes; the work is kept
    assert _until(lambda: "foreman:" + out["job"] not in steward_routes._running_job_ids())


@WINDOWS
def test_what_foreman_leaves_running_is_ended_before_its_work_is_inspected(env, monkeypatch):
    # fcj r2 BLOCKER 2: the root's exit is not the tree's
    repo, cdir, _ = env
    monkeypatch.setenv("FAKE_FOREMAN_MODE", "straggler")
    out = _start(repo, cdir)
    wt = Path(out["worktree"])
    job = _wait(cdir, out["job"])
    assert job["landed"] is True, job["land_note"]
    if (wt / ".foreman" / "child.pid").exists():
        assert not _alive(int((wt / ".foreman" / "child.pid").read_text()))


def test_a_stop_that_cannot_see_foreman_end_keeps_the_job_and_its_claim(env, monkeypatch):
    repo, cdir, _ = env
    monkeypatch.setenv("FAKE_FOREMAN_MODE", "sleep")
    out = _start(repo, cdir)
    real = code_jobs.end_foreman
    monkeypatch.setattr(code_jobs, "end_foreman", lambda job, wait_s=60: (False, "Foreman did not end when asked"))
    res = code_jobs.stop(str(cdir), out["job"], actor="John")
    assert not res["ok"] and "did not end" in res["error"]
    assert code_jobs._norm(str(repo)) in code_jobs.busy_repos()
    assert code_jobs.read_jobs(str(cdir))[out["job"]]["status"] == "running"
    monkeypatch.setattr(code_jobs, "end_foreman", real)
    assert code_jobs.stop(str(cdir), out["job"], actor="John")["ok"]


def test_a_stop_before_the_launch_means_no_launch(env, monkeypatch):
    # fcj r2 BLOCKER 2/MAJOR 6: Stop and the launch never cross - one sees the other under the lock
    repo, cdir, tmp = env
    real = code_jobs._start_foreman

    def stop_first(cdir_, job, *a):
        assert code_jobs.stop(str(cdir_), job["id"], actor="John")["ok"]
        return real(cdir_, job, *a)
    monkeypatch.setattr(code_jobs, "_start_foreman", stop_first)
    out = _start(repo, cdir)
    assert out["ok"]
    assert not (tmp / "foreman.log").exists() and out["job"] not in code_jobs._FOREMAN_PROCS
    assert code_jobs.read_jobs(str(cdir))[out["job"]]["status"] == "stopped"


@WINDOWS
def test_a_foreman_job_this_anchor_does_not_hold_was_lost_to_a_restart(env, monkeypatch):
    # fcj r2 BLOCKER 3/MAJOR 4: Foreman cannot outlive the Anchor that held its Job Object; a running record no live
    # Anchor holds is marked interrupted (its work kept) - and a job this Anchor holds is never touched
    repo, cdir, _ = env
    monkeypatch.setenv("FAKE_FOREMAN_MODE", "sleep")
    out = _start(repo, cdir)
    code_jobs.busy_repos()
    assert code_jobs.read_jobs(str(cdir))[out["job"]]["status"] == "running"      # held here: untouched
    run = code_jobs._FOREMAN_PROCS[out["job"]]
    code_jobs._FOREMAN_STOPPING.add(out["job"])                       # play the restart: the old Anchor's Job closes
    assert run.end(30)
    code_jobs._FOREMAN_PROCS.pop(out["job"])
    assert code_jobs._norm(str(repo)) not in code_jobs.busy_repos()
    job = code_jobs.read_jobs(str(cdir))[out["job"]]
    assert job["status"] == "failed" and "restarted" in job["error"] and job["kept_worktree"] == out["worktree"]


# ---- refusals before anything starts ----

@pytest.mark.parametrize("kw, why", [
    ({"check": ""}, "test command"),
    ({"plan": "no waves here"}, "Wave N"),
    ({"profile": "huge"}, "slim or standard"),
])
def test_refused_before_a_worktree_is_made(env, kw, why):
    repo, cdir, tmp = env
    out = _start(repo, cdir, **kw)
    assert not out["ok"] and why in out["error"]
    assert not (tmp / "jobs").exists() or not [p for p in (tmp / "jobs").iterdir() if p.name != "checks"]


def test_switched_off_by_hand(env, monkeypatch):
    repo, cdir, _ = env
    monkeypatch.setenv("ANCHOR_FOREMAN_CODE_JOBS", "0")
    assert "are off" in _start(repo, cdir)["error"]


@pytest.mark.parametrize("files, named", [
    ({"a.txt": "one\n", "foreman.config.json": "{}"}, "foreman.config.json"),
    ({"a.txt": "one\n", ".foreman-job/DESCRIPTION.md": "theirs"}, ".foreman-job/DESCRIPTION.md"),
])
def test_a_repository_tracking_foremans_own_files_is_refused(tmp_path, env, files, named):
    _, cdir, _ = env
    repo = _repo(tmp_path / "own", files)
    out = _start(repo, cdir)
    assert not out["ok"] and "tracks files a Foreman code job writes" in out["error"] and named in out["error"]


def test_foremans_own_files_never_land_whatever_git_ignores():
    for p in (".foreman-job/DESCRIPTION.md", ".foreman/run-record.json", "_foreman-status.log",
              "foreman-checkpoint.json", "FOREMAN.CONFIG.JSON", "sub/foreman.config.json"):
        assert code_jobs.never_lands(p), p
    assert not code_jobs.never_lands("src/foreman/x.py") and not code_jobs.never_lands("docs/.foreman-job.md")


def test_anchors_own_code_is_refused(env, monkeypatch):
    repo, cdir, _ = env
    import anchor_next
    monkeypatch.setattr(anchor_next, "is_served_repo", lambda path: True)
    monkeypatch.setenv("ANCHOR_UNCONFINED_CODERS", "1")              # no switch opens Anchor's own code (2026-10-12)
    out = _start(repo, cdir)
    assert not out["ok"] and "never changed from a cockpit" in out["error"]


# ---- never a skill job, never the job runner; the steward is told ----

def test_foreman_is_never_a_skill_job_and_crucible_keeps_its_hold(tmp_path, monkeypatch):
    root = tmp_path / "skills"
    for name in ("foreman", "crucible", "gandalf"):
        (root / name / "bin").mkdir(parents=True)
        (root / name / "bin" / "run.mjs").write_text("", encoding="utf-8")
    monkeypatch.setattr(skill_jobs, "skill_roots", lambda: [root])
    for hold in ("1", "0"):
        monkeypatch.setenv("ANCHOR_FOREMAN_CRUCIBLE_HOLD", hold)
        ok, why = skill_jobs.validate(["node", str(root / "foreman" / "bin" / "run.mjs")])
        assert not ok and "--worker foreman" in why
    monkeypatch.setenv("ANCHOR_FOREMAN_CRUCIBLE_HOLD", "1")
    assert not skill_jobs.validate(["node", str(root / "crucible" / "bin" / "run.mjs")])[0]
    monkeypatch.setenv("ANCHOR_FOREMAN_CRUCIBLE_HOLD", "0")
    assert skill_jobs.validate(["node", str(root / "crucible" / "bin" / "run.mjs")]) == (True, "")


def test_the_job_runner_never_starts_foreman_whatever_the_hold(tmp_path, monkeypatch):
    import job_runner
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", "claude")                 # a real runner: "lanes" lifts nothing
    for hold in ("1", "0", "lanes"):
        monkeypatch.setenv("ANCHOR_FOREMAN_CRUCIBLE_HOLD", hold)
        with pytest.raises(ValueError, match="foreman-code-job-only"):
            job_runner.launch("build", cwd=str(tmp_path), prompt="x")
        with pytest.raises(ValueError, match="foreman-code-job-only"):
            job_runner.launch("general", cwd=str(tmp_path), command=["node", "C:/dev/trio/foreman/bin/run-live.mjs"])
    monkeypatch.setenv("ANCHOR_FOREMAN_CRUCIBLE_HOLD", "1")
    with pytest.raises(ValueError, match="foreman-crucible-hold"):
        job_runner.launch("plan", cwd=str(tmp_path), prompt="x")


def test_the_steward_sizes_the_work_and_starts_foreman_as_a_code_job(monkeypatch):
    import importlib
    import steward_cockpit.steward_engine as se
    monkeypatch.delenv("ANCHOR_FOREMAN_CRUCIBLE_HOLD", raising=False)
    se = importlib.reload(se)
    try:
        for text in (se.CONTRACT, se.EFFORT_DUTY, se.EFFORT_RULES):
            assert "SIZE THE WORK" in text and "--worker foreman" in text
        assert "Crucible is on hold" in se.SIZE_OR_HOLD and "run-live.mjs" not in se.SIZE_OR_HOLD
    finally:
        monkeypatch.delenv("ANCHOR_FOREMAN_CRUCIBLE_HOLD", raising=False)
        importlib.reload(se)


# ---- fcj review r3 ----

def test_the_reviewer_reads_the_new_file_list_first_and_staged_additions_are_on_it(env, monkeypatch):
    # MAJOR 3 and 5: the disclosure goes before the brief (the adapter reads its first 8000 characters), and an
    # addition a script staged is a new file too
    repo, cdir, tmp = env
    monkeypatch.setenv("FAKE_FOREMAN_MODE", "staged")
    job = _wait(cdir, _start(repo, cdir)["job"])
    review = json.loads((tmp / "review.log").read_text(encoding="utf-8").splitlines()[0])
    brief = Path(review[review.index("--brief-file") + 1]).read_text(encoding="utf-8")
    assert brief.startswith("FOREMAN BUILT THIS") and "report.json" in brief.split("BRIEF:")[0]
    assert "report.json" in job["files"]




def test_an_end_that_cannot_be_seen_keeps_the_job_running_and_registered(env, monkeypatch):
    # MAJOR 2: never released on a failed end - whoever asked
    repo, cdir, _ = env
    monkeypatch.setattr(code_jobs._Run, "end", lambda self, wait_s=60: False)
    out = _start(repo, cdir)
    assert _until(lambda: (code_jobs.read_jobs(str(cdir))[out["job"]]).get("stuck"))
    job = code_jobs.read_jobs(str(cdir))[out["job"]]
    assert job["status"] == "running" and out["job"] in code_jobs._FOREMAN_PROCS
    assert code_jobs._norm(str(repo)) in code_jobs.busy_repos()                     # the reconcile leaves it alone
    res = code_jobs.stop(str(cdir), out["job"], actor="John")
    assert not res["ok"] and code_jobs.read_jobs(str(cdir))[out["job"]]["status"] == "running"
    monkeypatch.undo()
    code_jobs._FOREMAN_PROCS.pop(out["job"], None)


@WINDOWS
def test_a_failure_after_the_launch_ends_foreman_before_anything_is_released(env, monkeypatch):
    # BLOCKER 1
    repo, cdir, _ = env
    monkeypatch.setenv("FAKE_FOREMAN_MODE", "sleep")
    seen = {}
    real_thread = code_jobs.threading.Thread

    class Boom(real_thread):
        def start(self):
            if self.name.startswith("foreman-job-"):
                seen["run"] = next(r for r in code_jobs._FOREMAN_PROCS.values() if isinstance(r, code_jobs._Run))
                raise RuntimeError("no thread")
            return super().start()
    monkeypatch.setattr(code_jobs.threading, "Thread", Boom)
    out = _start(repo, cdir)
    assert not out["ok"] and "no thread" in out["error"]
    assert seen["run"].proc.poll() is not None and seen["run"].ended                  # ended, and seen gone
    assert code_jobs._norm(str(repo)) not in code_jobs.busy_repos()
    job = code_jobs.read_jobs(str(cdir))[out["job"]]                                  # fcj r4: it ran - its work is kept
    assert job["kept_worktree"] and Path(job["kept_worktree"]).is_dir()


def test_the_source_audit_reads_under_the_repository_lock(env, monkeypatch):
    # MAJOR 4: another job's landing is never seen half-placed
    repo, cdir, _ = env
    import git_safety
    held = []
    monkeypatch.setattr(code_jobs, "_served_tree_changes",
                        lambda job: held.append(git_safety._lock_path(str(repo)).exists()) or [])
    assert code_jobs._locked_served_changes({"id": "x", "repo": str(repo)}) == [] and held == [True]


# ---- fcj review r4 ----

def test_a_drain_that_began_during_the_start_is_honoured_after_the_job_is_counted(env, monkeypatch):
    # MAJOR 7
    repo, cdir, tmp = env
    from steward_cockpit import maintenance
    monkeypatch.setattr(maintenance, "is_active", lambda: True)
    out = _start(repo, cdir)
    assert not out["ok"] and "restarting" in out["error"]
    assert out["job"] not in code_jobs._FOREMAN_PROCS and not code_jobs._busy_read()
    assert not (tmp / "foreman.log").exists()


def test_a_worktree_that_cannot_be_prepared_leaves_no_reservation(tmp_path, env):
    # MAJOR 8: a repository whose .anchor is a FILE
    _, cdir, tmp = env
    repo = _repo(tmp_path / "odd", {"a.txt": "one\n", ".anchor": "not a folder"})
    out = _start(repo, cdir)
    assert not out["ok"] and "could not be prepared" in out["error"]
    assert out["job"] not in code_jobs._FOREMAN_PROCS and not code_jobs._busy_read()


def test_a_stop_of_a_foreman_that_never_launched_removes_its_reservation(env, monkeypatch):
    repo, cdir, _ = env
    monkeypatch.setattr(code_jobs, "_start_foreman", lambda *a: None)          # reserved, never launched
    out = _start(repo, cdir)
    assert isinstance(code_jobs._FOREMAN_PROCS.get(out["job"]), code_jobs._Starting)
    assert code_jobs.stop(str(cdir), out["job"], actor="John")["ok"]
    assert out["job"] not in code_jobs._FOREMAN_PROCS


def test_the_review_brief_is_whole_or_the_review_fails(tmp_path, monkeypatch):
    # MAJOR 2 and 3
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))
    long = {"id": "x", "base": "HEAD", "brief": "b" * (code_jobs.REVIEW_BRIEF_READ + 1)}
    assert "too long" in code_jobs.run_review(long, str(tmp_path), "HEAD")["error"]
    (tmp_path / "jobs").mkdir(exist_ok=True)
    (tmp_path / "jobs" / "checks").write_text("a file where the folder should be", encoding="utf-8")
    assert "could not be written" in code_jobs.run_review({"id": "y", "base": "HEAD", "brief": "b"}, str(tmp_path), "HEAD")["error"]


def test_the_new_file_list_comes_from_the_candidate_with_what_the_check_added(env, monkeypatch):
    # MAJOR 4: a declared output the final check makes is on the reviewer's list
    repo, cdir, tmp = env
    check = [sys.executable, "-c", "open('report.json','w').write('{}')"]
    job = _wait(cdir, _start(repo, cdir, check=check, outputs=["report.json"])["job"])
    assert job["landed"] is True, job["land_note"]
    review = json.loads((tmp / "review.log").read_text(encoding="utf-8").splitlines()[0])
    brief = Path(review[review.index("--brief-file") + 1]).read_text(encoding="utf-8")
    assert "report.json" in brief.split("BRIEF:")[0]


# ---- fcj review r5 ----

def test_a_foreman_that_may_run_uncontained_stays_counted_and_stop_ends_it(env, monkeypatch):
    # MAJOR 1: never dropped - registered, counted, its worktree kept, and Stop ends it
    repo, cdir, _ = env
    held = {}

    def uncontained(argv, cwd, env_, out):
        proc = subprocess.Popen(["node", "-e", "setTimeout(()=>{},600000)"], stdout=subprocess.DEVNULL)
        held["run"] = code_jobs._Run(proc, None)
        raise code_jobs._Uncontained(held["run"], "Foreman could not be contained (test)")
    monkeypatch.setattr(code_jobs, "_popen_contained", uncontained)
    out = _start(repo, cdir)
    assert not out["ok"] and "keeps its place" in out["error"]
    job = code_jobs.read_jobs(str(cdir))[out["job"]]
    assert job["status"] == "running" and job.get("stuck") and Path(job["worktree"]).is_dir()
    assert code_jobs._FOREMAN_PROCS[out["job"]] is held["run"] and code_jobs._norm(str(repo)) in code_jobs.busy_repos()
    from steward_cockpit import steward_routes
    assert "foreman:" + out["job"] in steward_routes._running_job_ids()
    assert code_jobs.stop(str(cdir), out["job"], actor="John")["ok"]
    assert held["run"].proc.poll() is not None
    code_jobs._FOREMAN_PROCS.pop(out["job"], None)


def test_a_record_that_cannot_be_written_leaves_no_reservation_and_no_worktree(env, monkeypatch):
    # MAJOR 2
    repo, cdir, tmp = env

    def broken(cdir_, job):
        raise OSError("the steward's folder is read-only")
    monkeypatch.setattr(code_jobs, "_write_job", broken)
    out = _start(repo, cdir)
    assert not out["ok"] and "record could not be written" in out["error"]
    assert not [k for k, v in code_jobs._FOREMAN_PROCS.items() if isinstance(v, code_jobs._Starting)]
    assert not [p for p in (tmp / "jobs").iterdir() if p.name not in ("checks", "busy.json", "locks")]


def test_the_brief_is_written_exactly_and_the_adapter_never_slices_it(tmp_path, monkeypatch):
    # MAJOR 3: no newline translation, and the adapter refuses a long brief instead of cutting it
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.setenv("ANCHOR_REVIEW_CMD", json.dumps([sys.executable, "-c", "print('{}')"]))
    code_jobs.run_review({"id": "nl", "base": "HEAD", "brief": "a\nb\n"}, str(tmp_path), "HEAD")
    assert (tmp_path / "jobs" / "checks" / "nl-brief.md").read_bytes() == b"a\nb\n"
    src = (ROOT / "tools" / "steward_review.mjs").read_text(encoding="utf-8")
    assert ".slice(0, 16000)" not in src and "longer than the reviewer reads whole" in src


# ---- fcj review r6 ----

def test_a_note_that_cannot_be_written_never_lets_a_running_foreman_go(env, monkeypatch):
    repo, cdir, _ = env
    held = {}

    def uncontained(argv, cwd, env_, out):
        proc = subprocess.Popen(["node", "-e", "setTimeout(()=>{},600000)"], stdout=subprocess.DEVNULL)
        held["run"] = code_jobs._Run(proc, None)
        raise code_jobs._Uncontained(held["run"], "Foreman could not be contained (test)")
    real = code_jobs._transition

    def no_stuck_note(cdir_, jid, expect, **u):
        if "stuck" in u:
            raise OSError("the record is locked")
        return real(cdir_, jid, expect, **u)
    monkeypatch.setattr(code_jobs, "_popen_contained", uncontained)
    monkeypatch.setattr(code_jobs, "_transition", no_stuck_note)
    out = _start(repo, cdir)
    assert not out["ok"] and "keeps its place" in out["error"]
    assert code_jobs._FOREMAN_PROCS[out["job"]] is held["run"]
    assert code_jobs.read_jobs(str(cdir))[out["job"]]["status"] == "running" and Path(out["worktree"] if "worktree" in out else code_jobs.read_jobs(str(cdir))[out["job"]]["worktree"]).is_dir()
    monkeypatch.setattr(code_jobs, "_transition", real)
    assert code_jobs.stop(str(cdir), out["job"], actor="John")["ok"] and held["run"].proc.poll() is not None
    code_jobs._FOREMAN_PROCS.pop(out["job"], None)


# ---- fcj review r7 ----

def test_a_list_check_a_shell_would_misread_reaches_foremans_gate_unchanged(env, monkeypatch):
    repo, cdir, tmp = env
    monkeypatch.setenv("FAKE_FOREMAN_MODE", "halt")                       # keeps the worktree to run the gate in
    check = [sys.executable, "-c", "import sys; sys.exit(0 if sys.argv[1] == 'a|b' else 3)", "a|b"]
    job = _wait(cdir, _start(repo, cdir, check=check)["job"])
    plan = _log(tmp)[0]["plan"].replace(chr(13), "")
    gate = next(ln for ln in plan.splitlines() if ln.startswith("test-command:")).split(":", 1)[1].strip().strip("`")
    assert "run_check.py" in gate
    assert subprocess.run(gate, shell=True, cwd=job["kept_worktree"]).returncode == 0   # as Foreman runs it
    assert code_jobs.check_text([sys.executable, "-m", "pytest", "tests"]).endswith("-m pytest tests")


def test_a_finished_jobs_busy_entry_is_pruned(env):
    repo, cdir, _ = env
    job = _wait(cdir, _start(repo, cdir)["job"])
    b = code_jobs._busy_read()
    b[job["id"]] = {"job": job["id"], "cdir": str(cdir), "repo": code_jobs._norm(str(repo))}   # the crash's leftover
    b["unreadable"] = {"job": "x", "cdir": str(cdir / "nowhere"), "repo": "r"}
    code_jobs._busy_write(b)
    code_jobs.busy_repos()
    left = code_jobs._busy_read()
    assert job["id"] not in left and "unreadable" in left                 # an unreadable record is kept


def test_foreman_waits_out_its_writers_usage_limit(env, monkeypatch):
    repo, cdir, _ = env
    monkeypatch.setattr(code_jobs, "exhausted_families", lambda: {"claude"})
    out = _start(repo, cdir)
    assert not out["ok"] and "usage limit" in out["error"]


# ---- fcj reviews r8-r10: pytest behind the wrapper is made verbose by pytest's own setting, never by guessing ----

def test_behind_the_wrapper_any_pytest_reached_is_verbose_and_the_final_check_is_exact(env, monkeypatch, tmp_path):
    repo, cdir, _ = env
    monkeypatch.setenv("FAKE_FOREMAN_MODE", "halt")
    check = [sys.executable, "-u", "-c", "import os, sys; print('ADDOPTS=' + os.environ.get('PYTEST_ADDOPTS', ''))",
             "a b"]
    job = _wait(cdir, _start(repo, cdir, check=check)["job"])
    assert job["check"] == check                                              # the final check: exactly as given
    wt = Path(job["kept_worktree"])
    assert json.loads((wt / ".foreman-job" / "run_check.json").read_text(encoding="utf-8")) == check
    out = subprocess.run([sys.executable, ".foreman-job/run_check.py"], cwd=wt, capture_output=True, text=True).stdout
    assert "ADDOPTS=-vv" in out                                               # what any pytest under it reads
