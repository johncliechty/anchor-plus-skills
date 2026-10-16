"""Persisted Stop requests survive stale finalizer dispositions without losing evidence."""

import pytest

from steward_cockpit import code_jobs as cj


@pytest.fixture
def finishing_job(tmp_path, monkeypatch):
    cdir = tmp_path / "steward"
    repo = tmp_path / "repo"
    tree = tmp_path / "worktree"
    for directory in (cdir, repo, tree):
        directory.mkdir()
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))
    product = tree / "result.py"
    product.write_text("result = 42\n", encoding="utf-8")
    row = {
        "id": "original",
        "attempt": 1,
        "status": "finishing",
        "phase": "checking",
        "repo": str(repo),
        "worktree": str(tree),
        "steward_dir": str(cdir),
        "check": ["python", "-m", "py_compile", "result.py"],
        "check_ok": False,
        "stop_requested": "explicit",
        "stop_requested_by": "human",
        "command": {
            "phase": "checking",
            "state": "completed",
            "cancelled": True,
        },
        "finalizer_active": True,
        "files": ["result.py"],
        "summary": "Prepared the requested result.",
        "land_note": "Final outcome is being recorded.",
    }
    cj._write_job(cdir, row)
    return cdir, row, product


def _terminal(cdir, row, **updates):
    fields = {
        "status": "done",
        "phase": "outcome",
        "kept_worktree": "",
        "check_ok": False,
    }
    fields.update(updates)
    return cj._transition(
        cdir, row["id"], ("finishing",), expect_attempt=1, **fields
    )


def test_persisted_stop_overrides_stale_terminal_disposition(finishing_job):
    cdir, row, product = finishing_job

    outcome = _terminal(cdir, row)

    assert outcome is not None
    assert outcome["id"] == row["id"]
    assert outcome["attempt"] == 1
    assert outcome["status"] == "stopped"
    assert outcome["stopped_by"] == "human"
    assert outcome["kept_worktree"] == row["worktree"]
    assert outcome["check_ok"] is None
    assert outcome["files"] == ["result.py"]
    assert product.read_text(encoding="utf-8") == "result = 42\n"
    saved = cj.read_jobs(cdir)[row["id"]]
    assert saved["status"] == "stopped"
    assert saved["stopped_by"] == "human"
    assert saved["kept_worktree"] == row["worktree"]
    assert saved["check_ok"] is None


def test_stop_does_not_erase_genuine_failed_check(finishing_job):
    cdir, row, product = finishing_job
    row["command"]["cancelled"] = False
    row["command"]["returncode"] = 1
    cj._write_job(cdir, row)

    outcome = _terminal(cdir, row)

    assert outcome["status"] == "stopped"
    assert outcome["stopped_by"] == "human"
    assert outcome["check_ok"] is False
    assert outcome["kept_worktree"] == row["worktree"]
    assert product.exists()
    assert cj.read_jobs(cdir)[row["id"]]["check_ok"] is False


def test_late_stop_preserves_successful_landing_evidence(finishing_job):
    cdir, row, _ = finishing_job
    row.update(
        placed=True,
        landed=True,
        landed_commit="abc",
        check_ok=True,
        land_note="Landed result.py in commit abc before the Stop request.",
    )
    row["command"]["cancelled"] = False
    row["command"]["returncode"] = 0
    cj._write_job(cdir, row)

    outcome = _terminal(cdir, row, check_ok=True)

    assert outcome["placed"] is True
    assert outcome["landed"] is True
    assert outcome["landed_commit"] == "abc"
    assert outcome["check_ok"] is True
    assert "nothing landed" not in str(outcome.get("land_note", "")).lower()
    saved = cj.read_jobs(cdir)[row["id"]]
    assert saved["placed"] is True
    assert saved["landed"] is True
    assert saved["landed_commit"] == "abc"


@pytest.mark.parametrize("terminal_status", ["done", "failed"])
def test_without_stop_terminal_disposition_and_failure_are_unchanged(
    finishing_job, terminal_status
):
    cdir, row, _ = finishing_job
    row.pop("stop_requested")
    row.pop("stop_requested_by")
    row["command"]["cancelled"] = False
    row["command"]["returncode"] = 1
    cj._write_job(cdir, row)

    outcome = _terminal(cdir, row, status=terminal_status)

    assert outcome["status"] == terminal_status
    assert outcome["check_ok"] is False
    assert not outcome.get("stopped_by")
    assert outcome.get("kept_worktree") == ""
    assert cj.read_jobs(cdir)[row["id"]]["status"] == terminal_status
