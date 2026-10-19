"""Literal protected candidate bytes remain identifiable during activation rollback."""

import subprocess
from pathlib import Path

import pytest

import anchor_next


BASELINE = b"var build = 'one';\r\n"
CANDIDATE = b"var build = 'two';\r\n"


def _git(repo, *args, data=None):
    result = subprocess.run(
        ["git", "-C", str(repo), *args], input=data, capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    return result.stdout.decode("utf-8").strip()


@pytest.fixture
def literal_candidate(tmp_path, monkeypatch):
    repo = tmp_path / "Anchor"
    repo.mkdir()
    _git(repo, "init", "-b", "master")
    _git(repo, "config", "user.name", "Activation fixture")
    _git(repo, "config", "user.email", "activation@example.invalid")
    _git(repo, "config", "commit.gpgsign", "false")
    _git(repo, "config", "core.autocrlf", "true")
    (repo / "page.js").write_bytes(BASELINE)
    _git(repo, "add", "page.js")
    _git(repo, "commit", "-m", "baseline")
    baseline_head = _git(repo, "rev-parse", "HEAD")
    baseline_blob = _git(repo, "rev-parse", "HEAD:page.js")
    assert baseline_blob == _git(repo, "hash-object", "--stdin", data=BASELINE.replace(b"\r\n", b"\n"))

    _git(repo, "checkout", "-b", anchor_next.BRANCH)
    candidate_blob = _git(repo, "hash-object", "-w", "--stdin", data=CANDIDATE)
    _git(repo, "update-index", "--add", "--cacheinfo", "100644," + candidate_blob + ",page.js")
    _git(repo, "commit", "-m", "literal protected candidate")
    candidate_head = _git(repo, "rev-parse", "HEAD")
    assert _git(repo, "rev-parse", "HEAD:page.js") == candidate_blob
    _git(repo, "checkout", "-f", "master")
    assert (repo / "page.js").read_bytes() == BASELINE
    assert _git(repo, "status", "--porcelain") == ""
    served = tmp_path / "Anchor-served"                # the running Anchor is never activated (2026-10-12): elsewhere
    served.mkdir()
    _git(served, "init", "-b", "master")
    monkeypatch.setenv("ANCHOR_SERVED_ROOT", str(served))
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))
    return repo, baseline_head, candidate_head, candidate_blob


def _activate_with_locked_master(repo):
    lock = repo / ".git" / "refs" / "heads" / "master.lock"
    lock.write_bytes(b"activation fixture owns this lock\n")
    try:
        return anchor_next.activate(repo)
    finally:
        lock.unlink()


def test_refused_activation_never_adopts_preexisting_literal_candidate_bytes(literal_candidate):
    repo, baseline_head, candidate_head, candidate_blob = literal_candidate
    (repo / "page.js").write_bytes(CANDIDATE)
    before = anchor_next._dirty(repo)
    assert "page.js" in before
    assert anchor_next._on_disk(repo, "page.js", raw=True) == candidate_blob
    result = _activate_with_locked_master(repo)
    assert result["ok"] is False and result["blockers"] == ["page.js"]
    # The defensive rollback itself also cannot acquire ownership just because
    # those pre-existing dirty bytes happen to equal the candidate object.
    unverified = anchor_next._restore(repo, baseline_head, candidate_head, ["page.js"], before)
    assert any("pre-existing" in item for item in unverified)
    assert (repo / "page.js").read_bytes() == CANDIDATE
    assert _git(repo, "rev-parse", "HEAD") == baseline_head


def test_refused_activation_restores_literal_crlf_candidate_without_false_external_edit(literal_candidate, monkeypatch):
    repo, baseline_head, _, candidate_blob = literal_candidate
    real_git = anchor_next._git
    failed_merges = []

    def observe_failed_merge(root, *args, **kwargs):
        result = real_git(root, *args, **kwargs)
        if Path(root).resolve() == repo.resolve() and args and args[0] == "merge" and "--ff-only" in args and result[0] != 0:
            assert (repo / "page.js").read_bytes() == CANDIDATE
            assert _git(repo, "hash-object", "--no-filters", "--", "page.js") == candidate_blob
            assert _git(repo, "hash-object", "--path=page.js", "--", "page.js") != candidate_blob
            failed_merges.append(True)
        return result

    monkeypatch.setattr(anchor_next, "_git", observe_failed_merge)
    result = _activate_with_locked_master(repo)
    assert failed_merges == [True]
    assert result["ok"] is False
    assert result.get("unverified", []) == []
    assert _git(repo, "rev-parse", "HEAD") == baseline_head
    assert (repo / "page.js").read_bytes() == BASELINE
    assert _git(repo, "status", "--porcelain") == ""


def test_later_byte_edit_is_preserved_even_if_it_only_changes_candidate_line_endings(literal_candidate, monkeypatch):
    repo, baseline_head, _, candidate_blob = literal_candidate
    external_bytes = CANDIDATE.replace(b"\r\n", b"\n")
    real_git = anchor_next._git
    races = []

    def edit_after_failed_merge(root, *args, **kwargs):
        result = real_git(root, *args, **kwargs)
        if Path(root).resolve() == repo.resolve() and args and args[0] == "merge" and "--ff-only" in args and result[0] != 0:
            assert (repo / "page.js").read_bytes() == CANDIDATE
            assert _git(repo, "hash-object", "--no-filters", "--", "page.js") == candidate_blob
            (repo / "page.js").write_bytes(external_bytes)
            races.append(True)
        return result

    monkeypatch.setattr(anchor_next, "_git", edit_after_failed_merge)
    result = _activate_with_locked_master(repo)
    assert races == [True]
    assert result["ok"] is False
    assert any(item.startswith("page.js") for item in result["unverified"])
    assert _git(repo, "rev-parse", "HEAD") == baseline_head
    assert (repo / "page.js").read_bytes() == external_bytes
