"""2026-10-05 made Foreman the code-job worker; 2026-10-07 (execution minimum item 3, John's binding) HOLDS Foreman and
Crucible at Anchor's managed entries until their best-in-class review. A code job is a coder in its own worktree. These
tests pin the hold: every managed entry refuses before anything starts, and lifting it is one explicit switch."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from steward_cockpit import code_jobs as cj  # noqa: E402


@pytest.fixture
def held(monkeypatch):
    monkeypatch.setenv("ANCHOR_FOREMAN_CRUCIBLE_HOLD", "1")


def test_no_regex_dispatch_picks_foreman_by_itself():
    # 2026-10-09: Foreman is a code job's worker only when the steward asks for it (--worker foreman), never chosen by
    # matching the check (the 2026-10-05 regex dispatch stays gone)
    for gone in ("is_test_gate", "_TEST_GATE", "FOREMAN_ON"):
        assert not hasattr(cj, gone), gone


def test_job_runner_refuses_build_and_plan_before_anything_starts(held, tmp_path):
    import job_runner
    for lane in ("plan", "planning"):
        with pytest.raises(ValueError, match="foreman-crucible-hold"):
            job_runner.launch(lane, cwd=str(tmp_path), prompt="x")
    with pytest.raises(ValueError, match="foreman-code-job-only"):     # 2026-10-09: Foreman only as a code job
        job_runner.launch("build", cwd=str(tmp_path), prompt="x")
    with pytest.raises(ValueError, match="foreman-code-job-only"):
        job_runner.launch("general", cwd=str(tmp_path), command=["node", "C:/dev/trio/foreman/bin/run-live.mjs"])


def test_skill_jobs_refuse_a_foreman_or_crucible_script(held, tmp_path, monkeypatch):
    from steward_cockpit import skill_jobs
    root = tmp_path / "skills"
    for name in ("foreman", "crucible", "gandalf"):
        (root / name / "bin").mkdir(parents=True)
        (root / name / "bin" / "run.mjs").write_text("", encoding="utf-8")
    monkeypatch.setattr(skill_jobs, "skill_roots", lambda: [root])
    ok, why = skill_jobs.validate(["node", str(root / "crucible" / "bin" / "run.mjs")])
    assert not ok and "on hold" in why
    ok, why = skill_jobs.validate(["node", str(root / "foreman" / "bin" / "run.mjs")])
    assert not ok and "only as a code job" in why
    assert skill_jobs.validate(["node", str(root / "gandalf" / "bin" / "run.mjs")]) == (True, "")


def test_lifting_the_hold_is_one_explicit_switch(monkeypatch):
    monkeypatch.setenv("ANCHOR_FOREMAN_CRUCIBLE_HOLD", "1")
    assert cj.foreman_crucible_held()
    monkeypatch.delenv("ANCHOR_FOREMAN_CRUCIBLE_HOLD")
    assert cj.foreman_crucible_held(), "Crucible stays held by default (Foreman runs only as a code job, 2026-10-09)"
    monkeypatch.setenv("ANCHOR_FOREMAN_CRUCIBLE_HOLD", "0")
    assert not cj.foreman_crucible_held()
