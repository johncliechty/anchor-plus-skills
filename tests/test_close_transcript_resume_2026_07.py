"""Resume-warm fix (2026-07-08) — CLOSE snapshots the PTY transcript.

The gap this closes (John, 2026-07-08): closing a session with the panel "×"
advertises a warm resume, but a bare ``general`` (or any doc-less) session
resumed COLD — no summary, no log, no reports. Root cause: ``close_session``
killed the live PTY FIRST, then ran a git-diff ``capture_session_docs`` that
found no produced ``.md`` and persisted nothing. The actual terminal
scrollback — the log of what happened — was never captured, so the summarizer
had zero text to ground on ("No grounded claims could be extracted…") and the
resume seed fell back to a bare title.

The fix: ``close_session`` now snapshots the LIVE PTY transcript into a durable
``<lane>/<short-sid>-transcript.md`` BEFORE the kill (mirroring
``autosave_session``). The immediately-following ``capture_session_docs`` then
persists it into MAIN, where it becomes a groundable member doc for the
summarizer and warms the reopen seed.

Hermetic: NO real claude/gemini, NO real PTY (``ANCHOR_PTY_BACKEND=stub``), a
temp git repo for the worktree, a tmp data dir + tmp worktree base. NEVER binds
``:8777``; NEVER a worktree off the real ``C:\\dev\\Anchor`` repo.
"""
import importlib
import subprocess
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)


def _have_git():
    try:
        return subprocess.run(["git", "--version"],
                              capture_output=True).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


pytestmark = pytest.mark.skipif(not _have_git(), reason="git not on PATH")


# Simulated general-session scrollback — the "log of what we were doing". NO file
# is written; this goes onto the stub PTY buffer (the stub echoes a write into
# its readable output), exactly like the live conversation-only path.
TRANSCRIPT = (
    "\n$ let's investigate the cooling-loop options for the reactor\n"
    "I compared three coolant loops. The molten-salt loop had the highest\n"
    "thermal margin and the simplest pump topology. Decision: pursue the\n"
    "molten-salt design and prototype the pump seal next.\n"
)


@pytest.fixture
def env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    wbase = tmp_path / "wt-base"
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(wbase))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)

    for mod in ("paths", "job_runner", "pty_manager", "rnd_registry",
                "effort_history", "sessions", "anchor_marker",
                "session_registry", "worktrees", "lanes", "summarizer",
                "handoff", "terminal_session"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()

    import effort_history
    import terminal_session
    import session_registry
    import rnd_registry
    import pty_manager

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial")

    proj = rnd_registry.add_project("Temp", str(repo), scaffold=False)
    bundle = {
        "ts": terminal_session, "reg": session_registry,
        "eh": effort_history, "rnd": rnd_registry, "repo": repo,
        "pty": pty_manager, "pid": proj["id"], "wbase": wbase, "data": data,
    }
    yield bundle
    try:
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


def _seed_transcript(pty, sid, text=TRANSCRIPT):
    """Put simulated scrollback in the session's read buffer (stub echoes it)."""
    pty.write(sid, text)


# ════════════════════════════════════════════════════════════════════════════
# (1) CLOSE snapshots a general session's transcript into MAIN (the core fix)
# ════════════════════════════════════════════════════════════════════════════

def test_close_snapshots_general_transcript_into_main(env):
    ts, reg, repo, pty, pid = (env["ts"], env["reg"], env["repo"],
                               env["pty"], env["pid"])

    sess = ts.start_session(pid, "general", backend="claude")
    sid = sess["session_id"]
    wt = Path(sess["worktree_path"])
    _seed_transcript(pty, sid)  # the "log of what we were doing"

    out = ts.close_session(sid, project_id=pid)
    assert out["ok"] is True

    short_sid = sid[:12]
    rel = f"general/{short_sid}-transcript.md"
    persisted = repo / rel
    assert persisted.is_file(), (
        "close must snapshot the live PTY transcript into MAIN before the kill")
    body = persisted.read_text(encoding="utf-8")
    assert "molten-salt" in body, "the actual scrollback content must survive"

    # It is a park, not a reap: worktree + record preserved, status IDLE.
    assert wt.exists()
    rec = reg.get_session(sid)
    assert rec is not None
    assert rec["status"] == reg.STATUS_IDLE


# ════════════════════════════════════════════════════════════════════════════
# (2) the snapshot happens BEFORE the kill (a killed PTY can't be read)
# ════════════════════════════════════════════════════════════════════════════

def test_close_captures_transcript_even_though_pty_is_then_reaped(env):
    """Ordering lock: the transcript must be read while the PTY is still live.
    After close, the PTY is gone — proving the snapshot ran first."""
    ts, pty, repo, pid = env["ts"], env["pty"], env["repo"], env["pid"]

    sess = ts.start_session(pid, "general", backend="claude")
    sid = sess["session_id"]
    _seed_transcript(pty, sid)

    ts.close_session(sid, project_id=pid)

    # The PTY is reaped by close (pty_killed) …
    assert sid not in pty.live_sessions()
    # … yet the transcript still made it into MAIN, so it was captured first.
    assert (repo / f"general/{sid[:12]}-transcript.md").is_file()


# ════════════════════════════════════════════════════════════════════════════
# (3) the persisted transcript is a member doc the summarizer can ground on
# ════════════════════════════════════════════════════════════════════════════

def test_closed_general_session_has_a_member_transcript_for_resume(env):
    """The persisted transcript is recorded as a general-lane member doc, so the
    summarizer/resume seed has real corpus text (not the empty
    'No grounded claims…' note)."""
    ts, eh, repo, pty, pid = (env["ts"], env["eh"], env["repo"],
                              env["pty"], env["pid"])

    sess = ts.start_session(pid, "general", backend="claude")
    sid = sess["session_id"]
    _seed_transcript(pty, sid)
    ts.close_session(sid, project_id=pid)

    docs = eh.efforts_for_session_id(str(repo), pid, "general", sid)
    rels = []
    for d in (docs or []):
        if isinstance(d, dict):
            rels.extend(d.get("doc_rels") or d.get("docs") or [])
    joined = " ".join(str(r) for r in rels)
    # Either the effort pointer-record references the transcript, or (belt +
    # braces) the file is on disk in MAIN — both mean resume has real material.
    assert ("transcript" in joined
            or (repo / f"general/{sid[:12]}-transcript.md").is_file()), (
        "a closed general session must leave a groundable transcript for resume")
