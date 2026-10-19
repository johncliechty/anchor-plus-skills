"""John 2026-10-11 (#7): the small fixes rescued from the shelved WIP 283fc40 (minus its self-update framework), on
plain git: a failed land puts each file back to its exact bytes (a CRLF checkout stays CRLF), and says so when a file
could not be put back instead of claiming nothing changed."""
import json
import subprocess
from pathlib import Path

import pytest

import git_safety as gs
from tests.test_git_safety_2026_10_05 import _job_commit, g, repo  # noqa: F401  (repo is a fixture)


def _fail_commit(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("commit failed")
    monkeypatch.setattr(gs, "_commit_blobs", boom)


def test_a_failed_land_puts_a_crlf_checkout_back_byte_for_byte(repo, monkeypatch):
    g(repo, "config", "core.autocrlf", "true")
    src = _job_commit(repo, {"a.txt": "two\n"})
    (repo / "a.txt").write_bytes(b"one\r\n")              # the checkout convention: clean, same content as HEAD
    _fail_commit(monkeypatch)
    ok, note = gs.land(repo, src, ["a.txt"], "job")
    assert not ok and "nothing changed" in note, note
    assert (repo / "a.txt").read_bytes() == b"one\r\n", "not HEAD's LF blob: the bytes that were there"


def test_a_failed_land_that_cannot_put_a_file_back_says_so(repo, monkeypatch):
    src = _job_commit(repo, {"a.txt": "two\n"})
    real = gs._git

    def racing(r, *args, **kw):
        if args[:1] == ("write-tree",) and "anchor-land" in ((kw.get("env") or {}).get("GIT_INDEX_FILE") or ""):
            (Path(r) / "a.txt").write_bytes(b"his fresh edit\n")
            raise RuntimeError("boom")
        return real(r, *args, **kw)
    monkeypatch.setattr(gs, "_git", racing)
    ok, note = gs.land(repo, src, ["a.txt"], "job")
    monkeypatch.setattr(gs, "_git", real)
    assert not ok and "rollback unverified for a.txt" in note and "nothing changed" not in note, note
    assert (repo / "a.txt").read_bytes() == b"his fresh edit\n", "his bytes are still left alone"


REVIEW_DIFF = (Path(__file__).resolve().parent.parent / "tools" / "review_diff.mjs").as_uri()


def _review_input(repo, base, head):
    script = ("import {reviewDiff} from %s; try { console.log(JSON.stringify({ok: true, diff: reviewDiff(%s, %s, %s)})) }"
              " catch (e) { console.log(JSON.stringify({ok: false, error: e.message})) }"
              % tuple(json.dumps(x) for x in (REVIEW_DIFF, str(repo), base, head)))
    r = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    return json.loads(r.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("content, refused", [
    (b"text\n", None),
    (b"caf\xe9 latin-1\n", "not valid UTF-8"),
])
def test_the_reviewer_is_given_exact_text_or_nothing(repo, content, refused):
    base = g(repo, "rev-parse", "HEAD").stdout.strip()
    (repo / "c.dat").write_bytes(content)
    g(repo, "add", "-A"); g(repo, "commit", "-qm", "change")
    out = _review_input(repo, base, "HEAD")
    if refused:
        assert not out["ok"] and refused in out["error"], out
    else:
        assert out["ok"] and "+text" in out["diff"], out


def test_a_binary_file_is_listed_for_the_reviewer_not_refused(repo):
    """Book 1 v2 (2026-10-12): a job with a PDF reading copy could not land - the reviewer refused the whole change.
    Now the text goes as its exact diff and the binary file is listed by name and size, said plainly to be unread."""
    base = g(repo, "rev-parse", "HEAD").stdout.strip()
    (repo / "spine.md").write_text("# Spine\n", encoding="utf-8")
    (repo / "reading copy.pdf").write_bytes(b"%PDF-1.7\n\x00\x00binary")
    g(repo, "add", "-A"); g(repo, "commit", "-qm", "change")
    out = _review_input(repo, base, "HEAD")
    assert out["ok"], out
    diff = out["diff"]
    assert "+# Spine" in diff and "Binary files" not in diff, diff
    assert "BINARY FILES" in diff and "NOT read by you" in diff, diff
    assert "- reading copy.pdf: added, 17 bytes, blob " in diff, diff


def test_a_binary_only_change_is_still_listed(repo):
    base = g(repo, "rev-parse", "HEAD").stdout.strip()
    (repo / "c.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00binary")
    g(repo, "add", "-A"); g(repo, "commit", "-qm", "change")
    out = _review_input(repo, base, "HEAD")
    assert out["ok"] and out["diff"].startswith("BINARY FILES") and "- c.png: added" in out["diff"], out


def test_a_binary_file_replaced_by_a_folder_of_text_is_refused_not_hidden(repo):
    (repo / "foo").write_bytes(b"\x00\x01binary")
    g(repo, "add", "-A"); g(repo, "commit", "-qm", "binary foo")
    base = g(repo, "rev-parse", "HEAD").stdout.strip()
    (repo / "foo").unlink(); (repo / "foo").mkdir(); (repo / "foo" / "main.py").write_text("x = 1\n", encoding="utf-8")
    g(repo, "add", "-A"); g(repo, "commit", "-qm", "folder foo")
    out = _review_input(repo, base, "HEAD")
    assert not out["ok"] and "share a path" in out["error"], out


def test_a_text_file_moved_under_a_deleted_binary_is_refused_not_hidden(repo):
    (repo / "foo").write_bytes(b"\x00\x01binary")
    (repo / "bar.py").write_text("".join("line %d\n" % i for i in range(40)), encoding="utf-8")
    g(repo, "add", "-A"); g(repo, "commit", "-qm", "binary foo, text bar")
    base = g(repo, "rev-parse", "HEAD").stdout.strip()
    (repo / "foo").unlink(); (repo / "foo").mkdir()
    (repo / "bar.py").rename(repo / "foo" / "main.py")
    g(repo, "add", "-A"); g(repo, "commit", "-qm", "move bar under foo")
    out = _review_input(repo, base, "HEAD")
    assert not out["ok"] and "share a path" in out["error"], out


def test_a_binary_file_replaced_by_a_folder_of_binaries_is_listed_as_deleted(repo):
    (repo / "foo").write_bytes(b"\x00\x01binary")
    g(repo, "add", "-A"); g(repo, "commit", "-qm", "binary foo")
    base = g(repo, "rev-parse", "HEAD").stdout.strip()
    (repo / "foo").unlink(); (repo / "foo").mkdir(); (repo / "foo" / "x.png").write_bytes(b"\x89PNG\x00other")
    g(repo, "add", "-A"); g(repo, "commit", "-qm", "folder of binaries")
    out = _review_input(repo, base, "HEAD")
    assert out["ok"] and "- foo: deleted (was 8 bytes, blob " in out["diff"] and "- foo/x.png: added" in out["diff"], out


def test_a_review_that_exits_with_an_error_is_never_a_pass(repo, tmp_path, monkeypatch):
    from steward_cockpit import code_jobs
    fake = tmp_path / "half_review.py"
    fake.write_text("import json, sys\nprint(json.dumps({'ok': True, 'family': 'chatgpt', 'verdict': 'PASS',"
                    " 'findings': []}))\nsys.exit(3)\n", encoding="utf-8")
    monkeypatch.setenv("ANCHOR_REVIEW_CMD", json.dumps([__import__("sys").executable, str(fake)]))
    head = g(repo, "rev-parse", "HEAD").stdout.strip()
    rec = code_jobs.run_review({"id": "rv1", "brief": "b", "base": head, "authors": ["claude"]}, repo, head)
    assert rec["ok"] is False and "exit 3" in rec["error"], rec


@pytest.mark.skipif(__import__("os").name != "nt", reason="the check script is a .cmd on Windows only")
def test_the_windows_check_script_has_plain_crlf_line_ends(repo, monkeypatch):
    from steward_cockpit import code_jobs
    seen = {}

    def capture(job, tree, argv, **kw):
        seen["bytes"] = Path(argv[-1]).read_bytes()
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
    monkeypatch.setattr(code_jobs, "run_command", capture)
    ok, _ = code_jobs.run_check({"id": "ck1", "check": "echo one\necho two"}, repo)
    assert ok and seen["bytes"] == b"@echo off\r\necho one\r\necho two\r\n", seen
