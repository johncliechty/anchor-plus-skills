"""Wave 7 — cost rollup (AC3) + per-effort auto-commit (AC4).

AC3: Given a completed job's result envelope, when recorded, then
     total_cost_usd / tokens / duration_ms are stored on the effort and
     aggregated per-lane and per-project. Uses tests/fake_claude.py to emit a
     fake result envelope (--result) with total_cost_usd / usage / duration_ms.

AC4: Given a completed effort, when finalized, then its .anchor/ pointer-record
     is auto-committed (one commit per effort), reconciled with .gitignore.
     The auto-commit runs on a TEMP git repo in a tmp dir — NEVER C:\\dev\\Anchor.

NO live claude (ANCHOR_RUNNER_CMD → fake_claude.py). All procs reaped. The real
Anchor repo is never touched.
"""
import importlib
import shutil
import subprocess
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()
GIT = shutil.which("git")


@pytest.fixture
def mods(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    import paths
    importlib.reload(paths)
    import job_runner
    importlib.reload(job_runner)
    import rnd_registry
    importlib.reload(rnd_registry)
    import effort_history
    importlib.reload(effort_history)
    yield job_runner, effort_history, rnd_registry
    for rec in job_runner.list_records():
        if rec.get("status") == job_runner.STATUS_RUNNING:
            job_runner.cancel(rec["job_id"])
    job_runner._reset_live_table_for_tests()


def _project(rnd, folder):
    folder.mkdir(parents=True, exist_ok=True)
    return rnd.add_project("P", str(folder))


# ── AC3: cost captured from the result envelope, stored + aggregated ────────

def test_result_envelope_captured_onto_job_record(mods, tmp_path):
    jr, eh, rnd = mods
    # Launch the fake runner with --result so it emits a result envelope.
    rec = jr.launch("research", cwd=str(tmp_path),
                    extra_args=["--lines", "2", "--result"])
    final = jr.wait(rec["job_id"], timeout=30)
    assert final["status"] == jr.STATUS_DONE
    cost = final.get("cost")
    assert cost is not None, "result envelope cost not captured on job record"
    assert cost["total_cost_usd"] == pytest.approx(0.0123)
    assert cost["duration_ms"] == 4567
    assert cost["input_tokens"] == 100
    assert cost["output_tokens"] == 42
    assert cost["total_tokens"] == 142
    assert final.get("session_id") == "fake-session-0001"


def test_cost_stored_on_effort_and_rolled_up_lane_and_project(mods, tmp_path):
    jr, eh, rnd = mods
    folder = tmp_path / "proj"
    proj = _project(rnd, folder)
    pid = proj["id"]

    # Two research efforts, each completing with a result envelope.
    for jid in ("e1", "e2"):
        rec = jr.launch("research", cwd=str(folder), job_id=jid,
                        extra_args=["--lines", "1", "--result"])
        final = jr.wait(jid, timeout=30)
        # Record + finalize the effort (no auto-commit: folder isn't a repo).
        eh.record_effort(folder, pid, "research", jid, skill="researchPrime")
        res = eh.finalize_effort(folder, pid, "research", jid, final,
                                 auto_commit=False)
        stored = res["effort"]["cost"]
        assert stored["total_cost_usd"] == pytest.approx(0.0123)
        assert stored["total_tokens"] == 142

    # One build effort too, so the project rollup spans lanes.
    rec = jr.launch("build", cwd=str(folder), job_id="b1",
                    extra_args=["--lines", "1", "--result"])
    final = jr.wait("b1", timeout=30)
    eh.record_effort(folder, pid, "build", "b1", skill="foreman")
    eh.finalize_effort(folder, pid, "build", "b1", final, auto_commit=False)

    # Per-lane rollup: research = 2 efforts aggregated.
    lr = eh.lane_rollup(folder, pid, "research")
    assert lr["effort_count"] == 2
    assert lr["total_cost_usd"] == pytest.approx(0.0246)
    assert lr["total_tokens"] == 284
    assert lr["duration_ms"] == 4567 * 2

    # Per-project rollup: research (2) + build (1) = 3 efforts.
    pr = eh.project_rollup(pid, folder)
    assert pr["total"]["effort_count"] == 3
    assert pr["total"]["total_cost_usd"] == pytest.approx(0.0369)
    assert pr["total"]["total_tokens"] == 426
    assert pr["lanes"]["research"]["effort_count"] == 2
    assert pr["lanes"]["build"]["effort_count"] == 1


# ── AC4: per-effort auto-commit on a TEMP git repo (never the real repo) ─────

@pytest.mark.skipif(GIT is None, reason="git not available")
def test_auto_commit_one_commit_per_effort_on_temp_repo(mods, tmp_path):
    jr, eh, rnd = mods
    # A TEMP git repo standing in for the project's own folder repo.
    folder = tmp_path / "tmprepo"
    folder.mkdir(parents=True, exist_ok=True)
    subprocess.run([GIT, "-C", str(folder), "init"], capture_output=True,
                   check=True, text=True)
    proj = rnd.add_project("P", str(folder))
    pid = proj["id"]
    # Scaffold writes .anchor/.gitignore (tracking policy).
    rnd.scaffold_project_store(folder, pid)

    def commit_count():
        r = subprocess.run([GIT, "-C", str(folder), "rev-list",
                            "--count", "HEAD"], capture_output=True, text=True)
        return int((r.stdout or "0").strip()) if r.returncode == 0 else 0

    assert commit_count() == 0  # fresh repo, no commits yet

    # Finalize effort #1 → exactly ONE commit.
    rec = jr.launch("research", cwd=str(folder), job_id="c1",
                    extra_args=["--lines", "1", "--result"])
    final = jr.wait("c1", timeout=30)
    eh.record_effort(folder, pid, "research", "c1", skill="researchPrime")
    res1 = eh.finalize_effort(folder, pid, "research", "c1", final,
                              auto_commit=True)
    assert res1["commit"]["committed"] is True
    assert commit_count() == 1

    # Finalize effort #2 → exactly ONE more commit (two total).
    rec = jr.launch("research", cwd=str(folder), job_id="c2",
                    extra_args=["--lines", "1", "--result"])
    final = jr.wait("c2", timeout=30)
    eh.record_effort(folder, pid, "research", "c2", skill="researchPrime")
    res2 = eh.finalize_effort(folder, pid, "research", "c2", final,
                              auto_commit=True)
    assert res2["commit"]["committed"] is True
    assert commit_count() == 2

    # The pointer-record IS tracked; ignored artifacts (jobs/, logs) are NOT.
    tracked = subprocess.run([GIT, "-C", str(folder), "ls-files"],
                             capture_output=True, text=True).stdout
    assert "c1.pointer.json" in tracked
    assert "c2.pointer.json" in tracked
    assert "index.json" in tracked
    # Nothing under jobs/ or any .log got committed (gitignore policy).
    assert ".log" not in tracked
    assert "/jobs/" not in tracked.replace("\\", "/")


@pytest.mark.skipif(GIT is None, reason="git not available")
def test_auto_commit_refuses_non_repo_folder(mods, tmp_path):
    jr, eh, rnd = mods
    folder = tmp_path / "plainfolder"  # NOT a git repo
    proj = _project(rnd, folder)
    pid = proj["id"]
    eh.record_effort(folder, pid, "research", "x1", skill="researchPrime")
    out = eh.auto_commit_effort(folder, pid, "research", "x1")
    assert out["committed"] is False
    assert out["reason"] == "not-a-git-repo"


# ── MINOR-1: auto-commit MUST refuse the Anchor code repo (dogfood guard) ────

@pytest.mark.skipif(GIT is None, reason="git not available")
def test_auto_commit_refuses_anchor_code_repo(mods, tmp_path, monkeypatch):
    """If the project folder resolves to paths.CODE_DIR (the Anchor repo), the
    auto-commit must refuse — no stage, no commit. We NEVER touch the real
    C:\\dev\\Anchor: we monkeypatch paths.CODE_DIR to a stand-in tmp git repo
    and register a project whose folder_path == that stand-in code dir.
    """
    import paths

    jr, eh, rnd = mods

    # Stand-in "Anchor code repo": a real git repo in a tmp dir.
    fake_code = tmp_path / "fake_anchor_code"
    fake_code.mkdir(parents=True, exist_ok=True)
    subprocess.run([GIT, "-C", str(fake_code), "init"], capture_output=True,
                   check=True, text=True)
    # Point the guard's notion of the Anchor code dir at the stand-in.
    monkeypatch.setattr(paths, "CODE_DIR", fake_code.resolve())

    def commit_count():
        r = subprocess.run([GIT, "-C", str(fake_code), "rev-list",
                            "--count", "HEAD"], capture_output=True, text=True)
        return int((r.stdout or "0").strip()) if r.returncode == 0 else 0

    def status_porcelain():
        return subprocess.run([GIT, "-C", str(fake_code), "status",
                               "--porcelain"], capture_output=True,
                              text=True).stdout

    assert commit_count() == 0
    before_status = status_porcelain()

    # Register the project with folder_path == the (stand-in) Anchor code dir.
    proj = rnd.add_project("AnchorSelf", str(fake_code))
    pid = proj["id"]
    rnd.scaffold_project_store(fake_code, pid)
    eh.record_effort(fake_code, pid, "research", "self1", skill="researchPrime")

    # Direct guard call: must refuse.
    out = eh.auto_commit_effort(fake_code, pid, "research", "self1",
                                allow_init=True)
    assert out["committed"] is False
    assert out["reason"] == "refused-anchor-repo"

    # finalize_effort (auto_commit defaults True) must ALSO refuse.
    final = {"status": "done", "cost": {}}
    res = eh.finalize_effort(fake_code, pid, "research", "self1", final,
                             auto_commit=True, allow_init=True)
    assert res["commit"]["committed"] is False
    assert res["commit"]["reason"] == "refused-anchor-repo"

    # No commit was created and nothing the guard staged (HEAD/index unchanged).
    assert commit_count() == 0
    # Whatever was staged must be the same as before the guarded calls
    # (the guard returns before any `git add`).
    staged = subprocess.run([GIT, "-C", str(fake_code), "diff", "--cached",
                             "--name-only"], capture_output=True, text=True)
    assert (staged.stdout or "").strip() == ""
