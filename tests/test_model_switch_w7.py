"""Wave 7 STUB GATE — Model-switch handoff (Pillar A/C, crucible-improve #9).

Frozen plan (``planning/crucible-improve-2026-06-30/IMPLEMENTATION-PLAN.md``
§Wave 7):

  - **#9** ``switch_engine`` — BEFORE reaping, generate a best-effort,
    5-second-timeout-bounded session summary; write a git-ignored
    ``SWITCH-HANDOFF.md`` into the worktree and pass it as ``seed_context`` to the
    new engine; fix the hard-coded "promoted from Grass Catchers" seed label. A
    wedged source engine must NOT block the switch (timeout → skip summary,
    proceed).

STUB GATE (verbatim from the plan): a switch with a healthy stub writes
``SWITCH-HANDOFF.md`` (git-ignored) and seeds the new engine with it; a switch
whose summary stub hangs past 5 s still completes the engine swap (summary
skipped); the seed label is not "promoted from Grass Catchers".

Hermetic, mirroring ``tests/test_engine_persist.py``: ``ANCHOR_PTY_BACKEND=stub``
(no real ConPTY), ``ANCHOR_RUNNER_CMD`` → ``tests/fake_claude.py`` (no live
claude), a temp ``ANCHOR_DATA_DIR`` + temp ``ANCHOR_WORKTREE_BASE`` + a throwaway
temp git repo. NEVER touches the live ``:8777`` service or real data, and no
worktree is ever created off the real ``C:\\dev\\Anchor`` repo.
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


def _init_repo(repo):
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial")


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Tmp data dir + tmp worktree base + stub PTY backend + a temp git repo."""
    data = tmp_path / "data"
    data.mkdir()
    wbase = tmp_path / "wt-base"
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(wbase))
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    monkeypatch.delenv("ANCHOR_TERMINAL_SEED", raising=False)
    for lane in ("RESEARCH", "PLAN", "PLANNING", "BUILD", "GRASS"):
        monkeypatch.delenv("ANCHOR_SEED_PROMPT_" + lane, raising=False)

    for mod in ("paths", "pty_manager", "rnd_registry", "session_registry",
                "worktrees", "lanes", "terminal_session"):
        importlib.reload(importlib.import_module(mod))
    import terminal_session, pty_manager, session_registry, worktrees, rnd_registry

    repo = tmp_path / "repo"
    _init_repo(repo)
    proj = rnd_registry.add_project("Temp", str(repo), scaffold=False)
    yield {
        "ts": terminal_session, "pty": pty_manager, "reg": session_registry,
        "wt": worktrees, "rnd": rnd_registry, "repo": repo, "pid": proj["id"],
    }
    try:
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


# ── (1) healthy summary → git-ignored SWITCH-HANDOFF.md + seeded into new engine ─

def test_healthy_switch_writes_gitignored_handoff_and_seeds_new_engine(env, monkeypatch):
    ts, reg = env["ts"], env["reg"]
    rec = ts.start_session(env["pid"], "research", backend="claude")
    sid = rec["session_id"]
    worktree = Path(rec["worktree_path"])

    DIGEST = "PRIOR-ENGINE-CONTEXT: built the stream-json parser; tests green."
    monkeypatch.setattr(ts, "_generate_switch_summary",
                        lambda session_id, record: DIGEST)

    new = ts.switch_engine(sid, "gemini")

    # Swap happened, identity preserved.
    assert new["session_id"] == sid
    assert new["backend"] == "gemini"
    assert new["status"] == reg.STATUS_RUNNING

    # SWITCH-HANDOFF.md written into the worktree, carrying the summary.
    handoff = worktree / ts.SWITCH_HANDOFF_FILENAME
    assert handoff.is_file()
    assert DIGEST in handoff.read_text(encoding="utf-8")

    # It is GIT-IGNORED within the worktree (never tracked/committed).
    ci = _git(worktree, "check-ignore", ts.SWITCH_HANDOFF_FILENAME)
    assert ci.returncode == 0, "SWITCH-HANDOFF.md must be git-ignored"
    st = _git(worktree, "status", "--porcelain")
    assert ts.SWITCH_HANDOFF_FILENAME not in st.stdout

    # The NEW engine is seeded WITH the handoff context — under an accurate label,
    # NOT the old grass wording.
    assert DIGEST in (new["seed_text"] or "")
    assert "promoted from Grass Catchers" not in (new["seed_text"] or "")
    assert new["seeded"] is True


# ── (2) a summary that hangs past the timeout still completes the swap ────────

def test_wedged_source_summary_does_not_block_switch(env, monkeypatch):
    ts, reg, pty = env["ts"], env["reg"], env["pty"]
    rec = ts.start_session(env["pid"], "research", backend="claude")
    sid = rec["session_id"]
    worktree = Path(rec["worktree_path"])

    # Shrink the bound + make the summary hang well past it.
    monkeypatch.setattr(ts, "SWITCH_SUMMARY_TIMEOUT", 0.3)

    import time

    def _hang(session_id, record):
        time.sleep(2.0)
        return "SHOULD-NOT-APPEAR"

    monkeypatch.setattr(ts, "_generate_switch_summary", _hang)

    new = ts.switch_engine(sid, "gemini")

    # The engine swap completed despite the wedged summary.
    assert new["backend"] == "gemini"
    assert new["status"] == reg.STATUS_RUNNING
    assert sid in pty.live_sessions()

    # Summary was SKIPPED: no handoff doc, and the hung text never reached the seed.
    assert not (worktree / ts.SWITCH_HANDOFF_FILENAME).exists()
    assert "SHOULD-NOT-APPEAR" not in (new["seed_text"] or "")
    assert "promoted from Grass Catchers" not in (new["seed_text"] or "")


# ── (3) the seed label is no longer the hard-coded grass wording ─────────────

def test_seed_label_is_not_grass_wording(env):
    ts = env["ts"]
    # A folded seed_context now carries the neutral default label, not the old
    # "promoted from Grass Catchers" wording.
    seeded = ts.seed_for_lane("research", seed_context="work on the widget idea")
    assert "promoted from Grass Catchers" not in seeded
    assert ts.DEFAULT_SEED_CONTEXT_LABEL in seeded
    assert "work on the widget idea" in seeded

    # A caller-supplied label is honored verbatim.
    labelled = ts.seed_for_lane(
        "research", seed_context="carry this", context_label="Custom framing")
    assert "Custom framing: carry this" in labelled
    assert "promoted from Grass Catchers" not in labelled

    # No seed_context → no suffix at all (back-compat).
    assert ts.seed_for_lane("research") is not None
    assert ts.DEFAULT_SEED_CONTEXT_LABEL not in ts.seed_for_lane("research")


# ── (4) the real generator is honest + bounded; the git-ignore helper is safe ─

def test_generate_switch_summary_no_live_pty_returns_empty(env):
    ts = env["ts"]
    # No such live session → no transcript → honest empty (never raises).
    assert ts._generate_switch_summary("no-such-session", {"seed_text": ""}) == ""


def test_switch_handoff_summary_times_out_to_empty(env, monkeypatch):
    ts = env["ts"]
    import time
    monkeypatch.setattr(ts, "_generate_switch_summary",
                        lambda s, r: (time.sleep(1.0), "late")[1])
    # Bounded at 0.2s → the slow generator is abandoned, "" returned.
    assert ts._switch_handoff_summary("sid", {}, timeout=0.2) == ""


def test_gitignore_helper_marks_file_ignored(env):
    ts = env["ts"]
    rec = ts.start_session(env["pid"], "research", backend="claude")
    worktree = Path(rec["worktree_path"])
    (worktree / "EPHEMERAL.tmp").write_text("scratch\n", encoding="utf-8")
    ts._gitignore_in_worktree(worktree, "EPHEMERAL.tmp")
    ci = _git(worktree, "check-ignore", "EPHEMERAL.tmp")
    assert ci.returncode == 0
