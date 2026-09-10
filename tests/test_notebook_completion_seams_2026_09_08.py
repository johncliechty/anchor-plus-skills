"""Hermetic completion-boundary tests; no Git, subprocesses or real sessions.

Production modules are imported only after the temporary Anchor/profile paths
are installed. notebook_completion is intentionally imported at fixture time so
this test file can be collected while that independently implemented module is
still being added.
"""
import importlib
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest


PROJECT_ID = "synthetic-completion-project"
SESSION_ID = "synthetic-completion-session"
LANE = "synthetic-classroom-lane"
NOTEBOOK_PATHS = [
    "lessons/lesson.py",
    "lessons/lesson.ipynb",
    "lessons/lesson.py.anchor-notebook.json",
    "DELIVERABLES.md",
]


def _forbidden(*args, **kwargs):
    raise AssertionError("A notebook completion seam attempted an unstubbed process, Git action, registry lookup, or deletion.")


@pytest.fixture
def seam(tmp_path, monkeypatch):
    main = tmp_path / "main"
    managed = tmp_path / "managed-worktrees"
    worktree = managed / SESSION_ID
    data = tmp_path / "anchor-data"
    profile = tmp_path / "profile"
    for directory in (main, worktree, data, profile):
        directory.mkdir(parents=True)
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("HOME", str(profile))
    monkeypatch.setenv("USERPROFILE", str(profile))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: profile))
    monkeypatch.setattr(subprocess, "run", _forbidden)
    monkeypatch.setattr(subprocess, "Popen", _forbidden)
    monkeypatch.setattr(subprocess, "check_output", _forbidden)
    paths = importlib.import_module("paths")
    monkeypatch.setattr(paths, "data_dir", lambda *args, **kwargs: data)
    history = importlib.import_module("effort_history")
    completion = importlib.import_module("notebook_completion")
    terminal = importlib.import_module("terminal_session")
    worktrees = importlib.import_module("worktrees")
    monkeypatch.setattr(history, "_commit_session_docs", _forbidden)
    monkeypatch.setattr(completion, "persist_to_main", _forbidden)
    monkeypatch.setattr(completion, "verify_main_copy", _forbidden)
    monkeypatch.setattr(terminal._rnd, "get_project", _forbidden)
    return SimpleNamespace(
        main=main, managed=managed, worktree=worktree, data=data, profile=profile,
        history=history, completion=completion, terminal=terminal, worktrees=worktrees,
    )


def _record(seam, **overrides):
    result = {
        "session_id": SESSION_ID,
        "project_id": PROJECT_ID,
        "worktree_path": str(seam.worktree),
        "lane": LANE,
        "backend": "chatgpt",
    }
    result.update(overrides)
    return result


def _notebook_result(*, ok=True, required=True, reason="synthetic-persisted"):
    return {
        "ok": ok,
        "persisted": list(NOTEBOOK_PATHS) if ok and required else [],
        "products": 1 if required else 0,
        "reason": reason,
        "completion_receipt": None,
        "notebooks_required": required,
    }


def _legacy_docs(**overrides):
    result = {
        "ok": True, "persisted": ["PLAN.md"],
        "committed": True, "commit": "synthetic-docs-commit", "reason": "committed",
    }
    result.update(overrides)
    return result


def _persist(seam, callback):
    return seam.history._persist_notebooks_and_docs(
        str(seam.main), PROJECT_ID, LANE, SESSION_ID, str(seam.worktree), callback,
    )


def test_failed_notebook_persistence_blocks_docs_callback_and_commit(seam, monkeypatch):
    calls = []

    def persist(main, worktree):
        calls.append((main, worktree))
        return _notebook_result(ok=False, reason="synthetic-destination-conflict")

    monkeypatch.setattr(seam.completion, "persist_to_main", persist)
    result = _persist(seam, _forbidden)
    assert len(calls) == 1
    assert Path(calls[0][0]) == seam.main
    assert Path(calls[0][1]) == seam.worktree
    assert result["notebooks_required"] is True
    assert result["notebooks_ok"] is False


@pytest.mark.parametrize("committed,reason", [
    (True, "committed"),
    (False, "no-staged-changes"),
    (False, "not-a-git-repo"),
])
def test_notebook_persistence_excludes_and_commits_only_its_exact_owned_paths(seam, monkeypatch, committed, reason):
    unrelated = seam.main / "unrelated-user-change.txt"
    unrelated.write_text("Synthetic unrelated user work must remain untouched.\n", encoding="utf-8", newline="")
    excluded = []
    commits = []
    monkeypatch.setattr(seam.completion, "persist_to_main", lambda main, worktree: _notebook_result())

    def persist_docs(excluded_set):
        assert isinstance(excluded_set, set)
        excluded.append(set(excluded_set))
        return _legacy_docs()

    def commit(main, project_id, lane, session_id, committed_paths, final_paths):
        commits.append((main, project_id, lane, session_id, list(committed_paths), final_paths))
        return {"committed": committed, "commit": "synthetic-notebook-commit" if committed else None, "reason": reason}

    monkeypatch.setattr(seam.history, "_commit_session_docs", commit)
    result = _persist(seam, persist_docs)
    assert excluded == [set(NOTEBOOK_PATHS)]
    assert len(commits) == 1
    main, project_id, lane, session_id, committed_paths, final_paths = commits[0]
    assert isinstance(main, Path) and main == seam.main
    assert (project_id, lane, session_id) == (PROJECT_ID, LANE, SESSION_ID)
    assert set(committed_paths) == set(NOTEBOOK_PATHS)
    assert len(committed_paths) == len(NOTEBOOK_PATHS)
    assert final_paths == []
    assert "PLAN.md" not in committed_paths
    assert "unrelated-user-change.txt" not in committed_paths
    assert unrelated.read_text(encoding="utf-8") == "Synthetic unrelated user work must remain untouched.\n"
    assert result["notebooks_required"] is True
    assert result["notebooks_ok"] is True


def test_failed_notebook_commit_blocks_notebook_completion_even_if_docs_succeeded(seam, monkeypatch):
    monkeypatch.setattr(seam.completion, "persist_to_main", lambda main, worktree: _notebook_result())
    monkeypatch.setattr(seam.history, "_commit_session_docs", lambda *args: {
        "committed": False, "commit": None, "reason": "synthetic-commit-failed",
    })
    result = _persist(seam, lambda excluded_set: _legacy_docs())
    assert result["notebooks_required"] is True
    assert result["notebooks_ok"] is False


def test_no_notebooks_preserves_the_legacy_docs_result_and_does_not_commit_again(seam, monkeypatch):
    legacy = _legacy_docs(ok=False, committed=False, commit=None, reason="synthetic-existing-docs-result")
    exclusions = []
    monkeypatch.setattr(seam.completion, "persist_to_main", lambda main, worktree: _notebook_result(required=False, reason="no-notebooks"))

    def persist_docs(excluded_set):
        exclusions.append(excluded_set)
        return legacy

    result = _persist(seam, persist_docs)
    assert exclusions == [set()]
    assert result == legacy


@pytest.mark.parametrize("notebooks_ok", [False, None, 0, 1, "true"])
def test_terminal_gate_fails_closed_on_required_but_not_explicitly_successful_persistence(seam, monkeypatch, notebooks_ok):
    monkeypatch.setattr(seam.terminal, "_is_shell_record", lambda record: False)
    result = seam.terminal._notebook_completion_gate(
        _record(seam), {"notebooks_required": True, "notebooks_ok": notebooks_ok},
    )
    assert result["ok"] is False
    # get_project and verify_main_copy remain forbidden: failed persistence is decisive.


def test_terminal_gate_verifies_the_main_copy_even_after_a_successful_persist_report(seam, monkeypatch):
    calls = []
    monkeypatch.setattr(seam.terminal, "_is_shell_record", lambda record: False)
    monkeypatch.setattr(seam.terminal._rnd, "get_project", lambda project_id: {"folder_path": str(seam.main)})

    def verify(main, worktree):
        calls.append((main, worktree))
        return {"ok": False, "reason": "synthetic-main-copy-mismatch", "notebooks_required": True}

    monkeypatch.setattr(seam.completion, "verify_main_copy", verify)
    result = seam.terminal._notebook_completion_gate(
        _record(seam), {"notebooks_required": True, "notebooks_ok": True},
    )
    assert len(calls) == 1
    assert Path(calls[0][0]) == seam.main
    assert Path(calls[0][1]) == seam.worktree
    assert result["ok"] is False
    assert result["reason"] == "synthetic-main-copy-mismatch"


def test_terminal_gate_passes_a_verified_main_copy(seam, monkeypatch):
    monkeypatch.setattr(seam.terminal, "_is_shell_record", lambda record: False)
    monkeypatch.setattr(seam.terminal._rnd, "get_project", lambda project_id: {"folder_path": str(seam.main)})
    monkeypatch.setattr(seam.completion, "verify_main_copy", lambda main, worktree: {
        "ok": True, "reason": "synthetic-main-copy-verified", "notebooks_required": True,
    })
    result = seam.terminal._notebook_completion_gate(_record(seam))
    assert result["ok"] is True


def test_terminal_gate_delegates_missing_main_to_verification_and_fails_closed(seam, monkeypatch):
    seen = []
    monkeypatch.setattr(seam.terminal, "_is_shell_record", lambda record: False)
    monkeypatch.setattr(seam.terminal._rnd, "get_project", lambda project_id: None)

    def verify(main, worktree):
        seen.append((main, worktree))
        assert not main
        return {"ok": False, "reason": "synthetic-main-project-unavailable", "notebooks_required": True}

    monkeypatch.setattr(seam.completion, "verify_main_copy", verify)
    result = seam.terminal._notebook_completion_gate(_record(seam))
    assert len(seen) == 1
    assert Path(seen[0][1]) == seam.worktree
    assert result["ok"] is False


@pytest.mark.parametrize("worktree_value", [None, "", "missing-directory"])
def test_terminal_gate_without_an_existing_worktree_is_a_no_op(seam, monkeypatch, worktree_value):
    monkeypatch.setattr(seam.terminal, "_is_shell_record", lambda record: False)
    if worktree_value == "missing-directory":
        worktree_value = str(seam.managed / "does-not-exist")
    result = seam.terminal._notebook_completion_gate(_record(seam, worktree_path=worktree_value))
    assert result["ok"] is True


def test_terminal_gate_for_a_shell_session_does_not_resolve_or_verify_notebooks(seam, monkeypatch):
    monkeypatch.setattr(seam.terminal, "_is_shell_record", lambda record: True)
    result = seam.terminal._notebook_completion_gate(_record(seam, backend="shell"))
    assert result["ok"] is True


def test_finish_stage_reports_notebook_persistence_required_after_persisting_docs(seam, monkeypatch):
    record = _record(seam)
    expected_docs = {"ok": True, "notebooks_required": True, "notebooks_ok": False}
    verdict = {"ok": False, "reason": "synthetic-notebook-persistence-conflict", "notebooks_required": True}
    calls = []
    monkeypatch.setattr(seam.terminal._reg, "get_session", lambda session_id: record)

    def persist(session_id, *, project_id=None, record=None):
        calls.append("persist")
        assert session_id == SESSION_ID and project_id == PROJECT_ID
        assert record is not None
        return expected_docs

    def gate(current_record, docs=None):
        calls.append("gate")
        assert current_record is record
        assert docs is expected_docs
        return verdict

    monkeypatch.setattr(seam.terminal, "_persist_current_stage", persist)
    monkeypatch.setattr(seam.terminal, "_notebook_completion_gate", gate)
    result = seam.terminal.finish_stage(SESSION_ID, project_id=PROJECT_ID)
    assert calls == ["persist", "gate"]
    assert result["ok"] is False
    assert result["reason"] == "notebook-persistence-required"
    assert result["session_id"] == SESSION_ID
    assert result["docs"] == expected_docs
    assert result["notebooks"] == verdict


@pytest.mark.parametrize("main_available", [True, False])
def test_worktree_removal_verifies_notebooks_before_any_git_or_recursive_delete(seam, monkeypatch, main_available):
    retained = seam.worktree / "must-remain.txt"
    retained.write_text("Synthetic worktree data must survive the failed guard.\n", encoding="utf-8", newline="")
    verify_calls = []
    monkeypatch.setattr(seam.worktrees, "worktree_path_for", lambda session_id, base=None: seam.worktree)
    monkeypatch.setattr(seam.worktrees, "managed_base", lambda base=None: seam.managed)
    monkeypatch.setattr(seam.worktrees, "_repo_for_project", lambda project_id: seam.main if main_available else None)
    monkeypatch.setattr(seam.worktrees, "_git", _forbidden)
    monkeypatch.setattr(seam.worktrees.shutil, "rmtree", _forbidden)

    def verify(main, worktree):
        verify_calls.append((main, worktree))
        if main_available:
            assert Path(main) == seam.main
        else:
            assert not main
        assert Path(worktree) == seam.worktree
        return {"ok": False, "reason": "synthetic-unpersisted-notebook", "notebooks_required": True}

    monkeypatch.setattr(seam.completion, "verify_main_copy", verify)
    result = seam.worktrees.remove_worktree(SESSION_ID, project_id=PROJECT_ID, base=seam.managed, force=True)
    assert result["ok"] is False
    assert result["removed"] is False
    assert len(verify_calls) == 1
    assert retained.read_text(encoding="utf-8") == "Synthetic worktree data must survive the failed guard.\n"
    assert seam.worktree.is_dir()
