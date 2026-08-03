"""Durability (2026-07-07) — incremental session autosave + restart artifacts.

The gap this closes: a session's produced docs + transcript were only ever
persisted into the MAIN project at a BOUNDARY event (kill / close / finish /
advance / suspend / boot-recover). A long-running session — notably a bare
``general`` session (``effort_managed=False``, which boot-recovery skips) — that
HUNG lost everything it generated: reconcile and the zombie sweep flip it
RUNNING→IDLE WITHOUT persisting, so the work survived only as orphaned worktree
files ("found and manually saved later").

This wave adds:
  - ``terminal_session.autosave_session`` / ``autosave_running_sessions`` — a
    heartbeat that snapshots each RUNNING session's transcript + copies its
    produced docs into MAIN + refreshes a mechanical ``RESTART.md`` resume aid;
  - the ``general`` lane is now a persistable doc dir (was stranded);
  - the boot reconcile PERSISTS a stale RUNNING session's worktree docs into MAIN
    BEFORE flipping it to IDLE.

Hermetic: NO real claude/gemini, NO real PTY — ``ANCHOR_PTY_BACKEND=stub``, a
temp git repo for the worktree, a tmp data dir + tmp worktree base. NEVER binds
``:8777``; NEVER a worktree off the real ``C:\\dev\\Anchor`` repo; NEVER real
push / gh / network. The daemon is left OFF (``ANCHOR_SESSION_AUTOSAVE=0``); the
autosave body is exercised DIRECTLY (synchronously).
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


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Tmp data dir + tmp worktree base + stub PTY + the fake runner + a temp git
    repo + a registered project. The autosave DAEMON is disabled — tests drive the
    autosave body directly."""
    data = tmp_path / "data"
    data.mkdir()
    wbase = tmp_path / "wt-base"
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(wbase))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.setenv("ANCHOR_SESSION_AUTOSAVE", "0")  # daemon OFF for tests
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
        "pid": proj["id"], "wbase": wbase, "data": data,
    }
    yield bundle
    try:
        import pty_manager
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


def _write_doc(worktree_path, rel, body="# generated\ncontent\n"):
    p = Path(worktree_path) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return rel


# ════════════════════════════════════════════════════════════════════════════
# (1) autosave persists a RUNNING session's produced docs + a RESTART.md
# ════════════════════════════════════════════════════════════════════════════

def test_autosave_persists_running_session_docs(env):
    ts, repo, pid = env["ts"], env["repo"], env["pid"]

    sess = ts.start_session(pid, "research", backend="claude")
    sid = sess["session_id"]
    wt = sess["worktree_path"]
    _write_doc(wt, "research/NOTES.md")

    res = ts.autosave_session(sid)
    assert res["ok"] is True
    assert "research/NOTES.md" in res["persisted"]

    # The doc + the RESTART.md resume aid now exist in the MAIN folder.
    assert (repo / "research/NOTES.md").is_file()
    assert (repo / "research/RESTART.md").is_file()
    restart = (repo / "research/RESTART.md").read_text(encoding="utf-8")
    assert sid in restart
    assert "To resume" in restart

    ts.kill(sid)


# ════════════════════════════════════════════════════════════════════════════
# (2) a bare `general` session is covered (John's runaway case)
# ════════════════════════════════════════════════════════════════════════════

def test_autosave_covers_general_session(env):
    ts, repo, pid = env["ts"], env["repo"], env["pid"]

    sess = ts.start_session(pid, "general", backend="claude")
    sid = sess["session_id"]
    wt = sess["worktree_path"]
    # A general session running e.g. a heavy skill writes a report into general/.
    _write_doc(wt, "general/GANDALF-HEAVY.md", "# heavy read\nfindings\n")

    res = ts.autosave_session(sid)
    assert res["ok"] is True, "general-session docs must persist (were stranded)"
    assert "general/GANDALF-HEAVY.md" in res["persisted"]
    assert (repo / "general/GANDALF-HEAVY.md").is_file()
    assert (repo / "general/RESTART.md").is_file()

    ts.kill(sid)


def test_autosave_snapshots_general_transcript(env):
    """The heartbeat must capture a bare `general` session's LIVE scrollback —
    not only files it happens to write to the worktree. This is the durability
    of a plain interactive terminal (John, 2026-07-08): even a session that
    never writes a .md has its transcript snapshotted + persisted into MAIN, so a
    later resume is warm (has the log of what was going on)."""
    import pty_manager
    ts, repo, pid = env["ts"], env["repo"], env["pid"]

    sess = ts.start_session(pid, "general", backend="claude")
    sid = sess["session_id"]
    # Seed simulated interactive scrollback onto the live PTY (stub echoes a
    # write into its read buffer) — NO file written to the worktree.
    pty_manager.write(sid, "\n$ what were we doing here\n"
                           "We were triaging the molten-salt cooling loop.\n")

    res = ts.autosave_session(sid)
    assert res["ok"] is True

    rel = f"general/{sid[:12]}-transcript.md"
    persisted = repo / rel
    assert persisted.is_file(), (
        "a general session's live transcript must be autosaved into MAIN")
    body = persisted.read_text(encoding="utf-8")
    assert "molten-salt" in body, "the actual scrollback content must survive"
    assert rel in res["persisted"]

    ts.kill(sid)


# ════════════════════════════════════════════════════════════════════════════
# (3) autosave_running_sessions sweeps every RUNNING session; skips terminal ones
# ════════════════════════════════════════════════════════════════════════════

def test_autosave_running_sweeps_all_and_skips_non_running(env):
    ts, reg, repo, pid = env["ts"], env["reg"], env["repo"], env["pid"]

    s1 = ts.start_session(pid, "research", backend="claude")
    s2 = ts.start_session(pid, "planning", backend="claude")
    _write_doc(s1["worktree_path"], "research/A.md")
    _write_doc(s2["worktree_path"], "planning/B.md")

    n = ts.autosave_running_sessions()
    assert n >= 2
    assert (repo / "research/A.md").is_file()
    assert (repo / "planning/B.md").is_file()

    # A non-running session is a no-op for autosave_session.
    reg.update_session(s1["session_id"], status=reg.STATUS_DONE)
    out = ts.autosave_session(s1["session_id"])
    assert out["ok"] is False and out.get("reason") == "not-running"

    ts.kill(s2["session_id"])


# ════════════════════════════════════════════════════════════════════════════
# (4) boot reconcile PERSISTS a stale running session's docs BEFORE idle
# ════════════════════════════════════════════════════════════════════════════

def test_boot_persist_before_reconcile_to_idle(env):
    """A RUNNING record whose process is gone (a hang across restart): its
    worktree docs are persisted into MAIN before reconcile flips it to IDLE — so
    the work is never stranded as orphaned worktree files."""
    ts, reg, repo, pid = env["ts"], env["reg"], env["repo"], env["pid"]

    sess = ts.start_session(pid, "general", backend="claude")
    sid = sess["session_id"]
    _write_doc(sess["worktree_path"], "general/HUNG-OUTPUT.md", "# hung\nwork\n")

    # Simulate boot: this sid has NO live process. Mirror the boot caller —
    # persist stale docs first, then reconcile → IDLE.
    dry = reg.reconcile(live_session_ids=set(), apply=False)
    assert sid in dry["stale"]
    for stale_sid in dry["stale"]:
        ts.capture_session_docs(stale_sid)
    reg.reconcile(live_session_ids=set())

    # The hung session's output survived into MAIN, and the record is parked.
    assert (repo / "general/HUNG-OUTPUT.md").is_file()
    rec = reg.get_session(sid)
    assert rec["status"] != reg.STATUS_RUNNING


# ════════════════════════════════════════════════════════════════════════════
# (5) autosave is idempotent — a re-run with no changes copies nothing new
# ════════════════════════════════════════════════════════════════════════════

def test_autosave_idempotent(env):
    ts, repo, pid = env["ts"], env["repo"], env["pid"]

    sess = ts.start_session(pid, "research", backend="claude")
    sid = sess["session_id"]
    _write_doc(sess["worktree_path"], "research/NOTES.md")

    ts.autosave_session(sid)
    head1 = _git(repo, "rev-parse", "HEAD").stdout.strip()
    # A second autosave with nothing changed must not create a new commit.
    ts.autosave_session(sid)
    head2 = _git(repo, "rev-parse", "HEAD").stdout.strip()
    assert head1 == head2, "an unchanged re-autosave must be a true no-op"

    ts.kill(sid)


# ════════════════════════════════════════════════════════════════════════════
# (6) the daemon respects the disable seam
# ════════════════════════════════════════════════════════════════════════════

def test_autosave_daemon_disabled_by_env(env, monkeypatch):
    ts = env["ts"]
    monkeypatch.setenv("ANCHOR_SESSION_AUTOSAVE", "0")
    assert ts.start_autosave_daemon() is False
    monkeypatch.setenv("ANCHOR_SESSION_AUTOSAVE", "1")
    assert ts.start_autosave_daemon() is True
    # Single-start guard: a second start is a no-op even when enabled.
    assert ts.start_autosave_daemon() is False
