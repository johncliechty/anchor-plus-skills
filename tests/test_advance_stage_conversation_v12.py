"""v12 Wave 6 — ``advance_stage`` CONVERSATION-ONLY (the load-bearing case).

THE v11 LESSON, HARDENED. A live research effort whose ONLY output is a terminal
CONVERSATION (the model answered in the PTY, wrote NO file, NO ``record_effort``)
must, on Advance, persist the research stage via the v11.1 transcript-snapshot
path — ``research/<short-sid>-transcript.md`` committed + tagged ``(sid,'research')`` —
flip ``current_stage`` to plan, keep the SAME session-id set, and write ZERO PTY
bytes beyond the seeded transcript.

We seed the STUB PTY read buffer with simulated transcript content via
``pty_manager.write`` (a stub write ECHOES into the readable buffer — no file, no
record_effort, no kill), then call ``advance_stage`` directly.

Hermetic: ``ANCHOR_PTY_BACKEND=stub``, the STUB summarizer runner, a temp git
repo + temp data dir + temp worktree base, ``ANCHOR_PROACTIVE_SUMMARY`` OFF.
NEVER binds ``:8777`` / a worktree off the real repo / real network.
"""
import importlib
import subprocess
from pathlib import Path

import pytest

STUB = (Path(__file__).resolve().parent / "stub_summarizer.py").as_posix()

TRANSCRIPT = (
    "\nResearcher: Summarize the trade study.\n"
    "Assistant: The vanadium-redox flow battery wins on cycle life; the key\n"
    "finding is a 20000-cycle floor at 80% depth-of-discharge. Recommendation:\n"
    "adopt the vanadium chemistry and size the stack for a 4-hour duration.\n"
)


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


@pytest.fixture
def env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    wbase = tmp_path / "wt-base"
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(wbase))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {STUB}")
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.delenv("ANCHOR_PROACTIVE_SUMMARY", raising=False)
    monkeypatch.setenv("STUB_SUMMARIZER_CLAIMS",
                       "The vanadium chemistry wins on cycle life")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    monkeypatch.delenv("ANCHOR_TERMINAL_SEED", raising=False)

    for mod in ("paths", "job_runner", "pty_manager", "rnd_registry",
                "effort_history", "sessions", "anchor_marker",
                "session_registry", "worktrees", "lanes", "summarizer",
                "report_viewer", "handoff", "boneyard", "terminal_session"):
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
        "ts": terminal_session, "reg": session_registry, "eh": effort_history,
        "rnd": rnd_registry, "pty": pty_manager,
        "repo": repo, "pid": proj["id"],
    }
    yield bundle
    try:
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


def _ids(reg, pid):
    return set(r["session_id"] for r in reg.list_sessions(project_id=pid))


def _pty_len(pty, sid):
    try:
        out = pty.read_since(sid, 0)
    except Exception:
        return 0
    return len((out.get("text") or "") if isinstance(out, dict) else "")


def _committed_in_repo(repo, rel):
    return _git(repo, "ls-files", "--error-unmatch", rel).returncode == 0


# ════════════════════════════════════════════════════════════════════════════
# CONVERSATION-ONLY — transcript snapshot, current_stage flips, ZERO new bytes
# ════════════════════════════════════════════════════════════════════════════

def test_advance_conversation_only_snapshots_transcript(env):
    """*Given* a live research effort whose ONLY output is transcript content
    seeded into its stub PTY read buffer (NO file, NO record_effort), *When*
    advance_stage(sid,'plan','manual'), *Then* research persists via the
    transcript-snapshot path (``research/<short-sid>-transcript.md`` committed +
    tagged (sid,'research')), current_stage=='plan', session-id set unchanged,
    PTY buffer delta beyond the seeded transcript == 0."""
    ts, reg, eh, pty, repo, pid = (env["ts"], env["reg"], env["eh"], env["pty"],
                                   env["repo"], env["pid"])

    sess = ts.start_session(pid, "research", backend="claude",
                            effort_managed=True)
    sid = sess["session_id"]
    wt = sess["worktree_path"]
    short_sid = sid[:12]
    rel = f"research/{short_sid}-transcript.md"

    # Seed the PTY read buffer with conversation — echoes into the readable
    # buffer; NO file written, NO record_effort.
    pty.write(sid, TRANSCRIPT)

    # Pre-conditions (proves the conversation-only flow): nothing on disk yet.
    assert not (repo / rel).is_file()
    store_lane = eh._resolve_subdir("research")
    assert eh.efforts_for_session_id(repo, pid, store_lane, sid) == []

    ids_before = _ids(reg, pid)
    pty_before = _pty_len(pty, sid)  # the seeded transcript (+ echoed seed)

    out = ts.advance_stage(sid, "plan", mode="manual", project_id=pid)
    assert out["ok"] is True
    assert out["advanced"] is True
    rec = out["record"]

    # (i) the transcript was SNAPSHOTTED + persisted + committed into MAIN.
    assert (repo / rel).is_file(), "transcript was not persisted into the project"
    assert _committed_in_repo(repo, rel), "transcript was not committed"
    assert rel in (out["finished"]["docs"].get("persisted") or [])

    # (ii) it is a research effort tagged with the session id (the keystone).
    tagged = [(e.get("artifact_path") or "").replace("\\", "/")
              for e in eh.efforts_for_session_id(repo, pid, store_lane, sid)]
    assert rel in tagged, f"no research effort tagged with sid: {tagged}"
    # ...and stage-scoped to 'research'.
    stage_tagged = [(e.get("artifact_path") or "").replace("\\", "/")
                    for e in eh.efforts_for_session_stage(repo, pid, sid,
                                                          "research")]
    assert rel in stage_tagged

    # (iii) current_stage flipped; SAME session id; SET unchanged (zero mint).
    assert rec["current_stage"] == "plan"
    assert rec["session_id"] == sid
    assert _ids(reg, pid) == ids_before

    # (iv) ZERO PTY bytes written by the advance BEYOND the seeded transcript.
    #      (advance writes nothing; the only growth would be the transcript file's
    #      contents echoing — but a snapshot is a file write, not a PTY write.)
    assert _pty_len(pty, sid) == pty_before


def test_advance_conversation_only_does_not_inject_pty(env):
    """The advance writes ZERO bytes to the PTY in the conversation-only case —
    the buffer is byte-for-byte unchanged across the advance call."""
    ts, pty, pid = env["ts"], env["pty"], env["pid"]
    sess = ts.start_session(pid, "research", backend="claude",
                            effort_managed=True)
    sid = sess["session_id"]
    pty.write(sid, TRANSCRIPT)

    out_before = pty.read_since(sid, 0)
    text_before = (out_before.get("text") or "")
    ts.advance_stage(sid, "plan", mode="manual", project_id=pid)
    out_after = pty.read_since(sid, 0)
    text_after = (out_after.get("text") or "")
    assert text_after == text_before
