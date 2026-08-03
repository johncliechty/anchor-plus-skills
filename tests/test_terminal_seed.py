"""v4 Wave 1 — cockpit terminal skill auto-load-once + greet-once seed.

Locks the fix for the repeating-prompt bug: ``terminal_session.start_session``
writes the lane's skill-seed turn **exactly once** at start, records
``seeded=True`` + ``seed_text`` on the durable session record, and NEVER re-emits
that seed on any later ``read_since`` / ``input``. Also pins the lane→skill map
and proves a kill reaps the PTY + worktree with no orphan.

Hermetic, mirroring ``tests/test_terminal_session.py``: ``ANCHOR_PTY_BACKEND=stub``
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
    # Ensure no stray seed-override env bleeds in from the host.
    monkeypatch.delenv("ANCHOR_TERMINAL_SEED", raising=False)
    for lane in ("RESEARCH", "PLAN", "PLANNING", "BUILD", "GRASS"):
        monkeypatch.delenv("ANCHOR_SEED_PROMPT_" + lane, raising=False)

    import paths
    importlib.reload(paths)
    import pty_manager
    importlib.reload(pty_manager)
    import rnd_registry
    importlib.reload(rnd_registry)
    import session_registry
    importlib.reload(session_registry)
    import worktrees
    importlib.reload(worktrees)
    import lanes
    importlib.reload(lanes)
    import terminal_session
    importlib.reload(terminal_session)

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial")

    proj = rnd_registry.add_project("Temp", str(repo), scaffold=False)
    yield {
        "ts": terminal_session, "pty": pty_manager, "reg": session_registry,
        "wt": worktrees, "rnd": rnd_registry, "repo": repo, "pid": proj["id"],
        "wbase": wbase, "data": data, "monkeypatch": monkeypatch,
    }
    try:
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


# ── (d) The lane→skill map is correct ────────────────────────────────────────

def test_lane_skill_map_is_correct(env):
    ts = env["ts"]
    assert ts.LANE_SKILL["research"] == "researchPrime"
    assert ts.LANE_SKILL["plan"] == "Crucible"
    assert ts.LANE_SKILL["planning"] == "Crucible"
    assert ts.LANE_SKILL["build"] == "Foreman"


# ── (a) Each lane writes the correct skill seed exactly once ─────────────────

@pytest.mark.parametrize("lane,skill", [
    ("research", "researchPrime"),
    ("plan", "Crucible"),
    ("build", "Foreman"),
])
def test_start_session_seeds_correct_skill_once(env, lane, skill):
    ts, reg = env["ts"], env["reg"]
    rec = ts.start_session(env["pid"], lane, backend="claude")
    sid = rec["session_id"]

    # The seed turn is present in the stub backend's echoed buffer exactly once.
    out = ts.read_since(sid, 0)
    buf = out["text"]
    assert skill in buf
    # The seed line is written exactly ONCE (no duplicate emission at start).
    assert buf.count("loaded — what would you like to do?") == 1

    # The record carries seeded=True + the persisted seed_text mentioning skill.
    assert rec["seeded"] is True
    assert skill in rec["seed_text"]


def test_planning_dirname_lane_also_seeds_crucible(env):
    """The on-disk lane name 'planning' maps to Crucible too (either convention)."""
    ts = env["ts"]
    rec = ts.start_session(env["pid"], "planning", backend="claude")
    assert rec["seeded"] is True
    assert "Crucible" in rec["seed_text"]
    assert "Crucible" in ts.read_since(rec["session_id"], 0)["text"]


# ── (b) The seed is NOT re-emitted across N reads or a later input ───────────

def test_seed_not_reemitted_across_reads_and_input(env):
    ts = env["ts"]
    rec = ts.start_session(env["pid"], "plan", backend="claude")
    sid = rec["session_id"]

    # First read drains the seed turn.
    first = ts.read_since(sid, 0)
    assert first["text"].count("loaded — what would you like to do?") == 1
    cursor = first["next"]

    # Subsequent cursor-stable reads return no new seed text (no re-emit).
    for _ in range(3):
        nxt = ts.read_since(sid, cursor)
        assert "loaded — what would you like to do?" not in nxt["text"]
        cursor = nxt["next"]

    # A subsequent user turn echoes ONLY the user's bytes — no second seed.
    ts.input(sid, "do the thing\n")
    after = ts.read_since(sid, cursor)
    assert "do the thing" in after["text"]
    assert "loaded — what would you like to do?" not in after["text"]

    # Across the WHOLE cumulative buffer the seed greeting appears exactly once.
    whole = ts.read_since(sid, 0)["text"]
    assert whole.count("loaded — what would you like to do?") == 1


# ── (c) record.seeded persists and reloads from the durable registry ─────────

def test_seeded_flag_persists_and_reloads(env):
    ts, reg = env["ts"], env["reg"]
    rec = ts.start_session(env["pid"], "research", backend="claude")
    sid = rec["session_id"]

    # Reload the registry module from disk → the persisted record still carries
    # seeded=True + the seed_text (durability across a restart).
    importlib.reload(reg)
    reloaded = reg.get_session(sid)
    assert reloaded is not None
    assert reloaded["seeded"] is True
    assert "researchPrime" in reloaded["seed_text"]


# ── Seed override env (deterministic test hook) ──────────────────────────────

def test_global_seed_override_env_wins(env):
    ts = env["ts"]
    env["monkeypatch"].setenv("ANCHOR_TERMINAL_SEED", "DETERMINISTIC-SEED-XYZ\n")
    rec = ts.start_session(env["pid"], "plan", backend="claude")
    assert rec["seed_text"] == "DETERMINISTIC-SEED-XYZ\n"
    assert "DETERMINISTIC-SEED-XYZ" in ts.read_since(rec["session_id"], 0)["text"]


def test_per_lane_seed_override_env_wins(env):
    ts = env["ts"]
    env["monkeypatch"].setenv("ANCHOR_SEED_PROMPT_BUILD", "BUILD-LANE-SEED\n")
    # A different lane is unaffected by the per-lane override.
    env["monkeypatch"].setenv("ANCHOR_TERMINAL_SEED", "GLOBAL-SEED\n")
    rb = ts.start_session(env["pid"], "build", backend="claude")
    assert rb["seed_text"] == "BUILD-LANE-SEED\n"
    rp = ts.start_session(env["pid"], "plan", backend="claude")
    assert rp["seed_text"] == "GLOBAL-SEED\n"


# ── grass lane is a bare shell (no mapped skill → no seed) ────────────────────

def test_grass_lane_is_bare_no_seed(env):
    ts = env["ts"]
    rec = ts.start_session(env["pid"], "grass", backend="claude")
    assert rec["seeded"] is False
    assert rec["seed_text"] == ""
    # Nothing was written at start.
    assert ts.read_since(rec["session_id"], 0)["text"] == ""


# ── (e) Killing the session reaps PTY + worktree with no orphan ──────────────

def test_kill_reaps_pty_and_worktree_no_orphan(env):
    ts, reg = env["ts"], env["reg"]
    rec = ts.start_session(env["pid"], "plan", backend="claude")
    sid = rec["session_id"]
    wt_path = Path(rec["worktree_path"])
    assert wt_path.exists()
    assert sid in env["pty"].live_sessions()
    # Worktree is under the managed base, OUTSIDE the real repo.
    assert str(env["wbase"]) in rec["worktree_path"]
    assert str(env["repo"]) not in rec["worktree_path"]

    out = ts.kill(sid)
    assert out["ok"] is True
    # PTY reaped (no live id), registry record terminal, worktree gone.
    assert sid not in env["pty"].live_sessions()
    assert reg.get_session(sid)["status"] in reg.TERMINAL_STATUSES
    assert not wt_path.exists()
    # No orphan session worktree left registered against the repo.
    listing = _git(env["repo"], "worktree", "list", "--porcelain")
    assert "anchor/session/" not in listing.stdout
