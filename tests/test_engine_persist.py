"""v4 Wave 2 — engine persistence + toggle (relaunch on the other engine).

Locks the Wave-2 contract:

  (a) a new session with no explicit backend inherits the project's last-used
      engine (and settings ``default_cli`` — currently ``grok`` — when unset);
  (b) starting a session updates the project's persisted ``last_engine``;
  (c) ``switch_engine`` swaps the backend, keeps the SAME session_id + worktree,
      re-registers, and leaves NO orphan PTY / worktree;
  (d) a failed relaunch rolls back to a consistent record (no orphan, worktree
      intact);
  (e) the ``/api/rnd/term_set_engine`` endpoint rejects an unauth'd call and an
      invalid engine, and is token-gated.

Hermetic, mirroring ``tests/test_terminal_seed.py``: ``ANCHOR_PTY_BACKEND=stub``
(no real ConPTY), ``ANCHOR_RUNNER_CMD`` → ``tests/fake_claude.py`` (no live
claude), a temp ``ANCHOR_DATA_DIR`` + temp ``ANCHOR_WORKTREE_BASE`` + a throwaway
temp git repo. NEVER touches the live ``:8777`` service or real data, and no
worktree is ever created off the real ``C:\\dev\\Anchor`` repo.
"""
import importlib
import json
import subprocess
import threading
import urllib.error
import urllib.request
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
    _init_repo(repo)

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


# ── (a) default-from-last (and settings default_cli when unset) ──────────────

def test_unset_last_engine_defaults_to_settings_default_cli(env):
    ts = env["ts"]
    import anchor_settings as _aset
    expected = _aset.get_default_cli()  # machine default: grok
    # No engine.json yet → helper returns the settings-backed default.
    assert ts.last_engine_for_project(env["pid"]) == expected
    # A new session with NO explicit backend inherits that default.
    rec = ts.start_session(env["pid"], "research")
    assert rec["backend"] == expected


def test_new_session_inherits_last_engine(env):
    ts = env["ts"]
    # Persist gemini as the project's last-used engine, then start WITHOUT an
    # explicit backend on the research lane (gemini is allowed there).
    assert ts.set_last_engine_for_project(env["pid"], "gemini") is True
    assert ts.last_engine_for_project(env["pid"]) == "gemini"
    rec = ts.start_session(env["pid"], "research")
    assert rec["backend"] == "gemini"


# ── (b) starting a session updates the project's last_engine ─────────────────

def test_start_session_updates_last_engine(env):
    ts = env["ts"]
    import anchor_settings as _aset
    assert ts.last_engine_for_project(env["pid"]) == _aset.get_default_cli()
    # Explicitly start on gemini (research lane) → project remembers gemini.
    ts.start_session(env["pid"], "research", backend="gemini")
    assert ts.last_engine_for_project(env["pid"]) == "gemini"
    # The pointer survives a fresh module reload (durable on disk).
    importlib.reload(ts)
    assert ts.last_engine_for_project(env["pid"]) == "gemini"


def test_last_engine_persisted_under_project_store(env):
    ts, rnd = env["ts"], env["rnd"]
    ts.start_session(env["pid"], "research", backend="gemini")
    p = (rnd.project_store_dir(str(env["repo"]), env["pid"]) / "engine.json")
    assert p.exists()
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["last_engine"] == "gemini"


# ── (c) switch_engine swaps + re-registers, same id+worktree, no orphan ──────

def test_switch_engine_swaps_keeps_identity_no_orphan(env):
    ts, pty, reg = env["ts"], env["pty"], env["reg"]
    # Start on claude (research lane allows gemini for the swap target).
    rec = ts.start_session(env["pid"], "research", backend="claude")
    sid = rec["session_id"]
    worktree = rec["worktree_path"]
    branch = rec["branch"]
    assert sid in pty.live_sessions()

    new = ts.switch_engine(sid, "gemini")

    # Same identity preserved.
    assert new["session_id"] == sid
    assert new["worktree_path"] == worktree
    assert new["branch"] == branch
    assert new["lane"] == "research"
    # Backend swapped + re-registered RUNNING.
    assert new["backend"] == "gemini"
    assert new["status"] == reg.STATUS_RUNNING
    # The registry on disk reflects the new backend.
    assert reg.get_session(sid)["backend"] == "gemini"
    # Exactly ONE live PTY for this id — no orphan PTY left behind.
    assert pty.live_sessions().count(sid) == 1
    assert len([s for s in pty.live_sessions() if s != sid]) == 0
    # Worktree still on disk (reused, not orphaned/duplicated).
    assert Path(worktree).exists()
    # Seed was re-applied once on the new engine.
    assert new["seeded"] is True
    # last_engine now follows the swap.
    assert ts.last_engine_for_project(env["pid"]) == "gemini"


def test_switch_engine_unknown_session_and_backend(env):
    ts = env["ts"]
    with pytest.raises(ts.TerminalSessionError):
        ts.switch_engine("nope-no-such-id", "gemini")
    rec = ts.start_session(env["pid"], "research", backend="claude")
    with pytest.raises(ts.TerminalSessionError):
        ts.switch_engine(rec["session_id"], "not-an-engine")


def test_switch_engine_policy_refusal_leaves_session_intact(env):
    """gemini on a plan lane is now allowed and does not raise an error."""
    ts, pty, reg = env["ts"], env["pty"], env["reg"]
    rec = ts.start_session(env["pid"], "plan", backend="claude")
    sid = rec["session_id"]
    # Switch is allowed
    new = ts.switch_engine(sid, "gemini")
    assert new["backend"] == "gemini"
    after = reg.get_session(sid)
    assert after["backend"] == "gemini"
    assert after["status"] == reg.STATUS_RUNNING
    assert sid in pty.live_sessions()


# ── (d) a failed relaunch rolls back to a consistent record ──────────────────

def test_failed_relaunch_rolls_back_consistent(env, monkeypatch):
    ts, pty, reg = env["ts"], env["pty"], env["reg"]
    rec = ts.start_session(env["pid"], "research", backend="claude")
    sid = rec["session_id"]
    worktree = rec["worktree_path"]

    # Force the NEW PTY launch to fail. The old PTY is reaped first, so after a
    # failure the record must be consistent (no orphan PTY, worktree intact).
    def _boom(*a, **k):
        raise RuntimeError("relaunch boom")
    monkeypatch.setattr(pty, "start", _boom)

    with pytest.raises(ts.TerminalSessionError):
        ts.switch_engine(sid, "gemini")

    # Record left consistent: prior backend kept, marked non-running (idle), and
    # NO live PTY orphaned for this id.
    after = reg.get_session(sid)
    assert after is not None
    assert after["backend"] == "claude"           # prior engine preserved
    assert after["status"] == reg.STATUS_IDLE     # no live process now
    assert sid not in pty.live_sessions()         # old PTY reaped, none orphaned
    assert Path(worktree).exists()                # worktree untouched


# ── (e) the endpoint: token-gated + invalid-engine rejected ──────────────────

@pytest.fixture
def server(tmp_path, monkeypatch):
    """A live anchor_gui server with ANCHOR_TOKEN set (auth ON), stub PTY."""
    data = tmp_path / "data"
    data.mkdir()
    wbase = tmp_path / "wt-base"
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(wbase))
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.setenv("ANCHOR_TOKEN", "sekret")
    monkeypatch.delenv("ANCHOR_TERMINAL_SEED", raising=False)

    import paths
    importlib.reload(paths)
    paths.ensure_data_dirs()
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
    import anchor_gui
    gui = importlib.reload(anchor_gui)

    repo = tmp_path / "repo"
    _init_repo(repo)
    proj = rnd_registry.add_project("Temp", str(repo), scaffold=False)

    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield {"gui": gui, "ts": terminal_session, "base": f"http://127.0.0.1:{port}",
               "pid": proj["id"], "token": "sekret"}
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(timeout=5)
        try:
            pty_manager._reset_live_table_for_tests()
        except Exception:
            pass


def _post(url, payload, token=None):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if token is not None:
        req.add_header("X-Anchor-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_endpoint_rejects_unauthed(server):
    base, ts, pid = server["base"], server["ts"], server["pid"]
    rec = ts.start_session(pid, "research", backend="claude")
    # No token → 401, the session is NOT touched.
    code, body = _post(base + "/api/rnd/term_set_engine",
                       {"session": rec["session_id"], "engine": "gemini"})
    assert code == 401
    assert body["ok"] is False
    assert ts.get_session(rec["session_id"])["backend"] == "claude"


def test_endpoint_rejects_invalid_engine(server):
    base, ts, pid, token = (server["base"], server["ts"], server["pid"],
                            server["token"])
    rec = ts.start_session(pid, "research", backend="claude")
    code, body = _post(base + "/api/rnd/term_set_engine",
                       {"session": rec["session_id"], "engine": "bogus"},
                       token=token)
    assert code == 400
    assert body["ok"] is False
    assert body["reason"] == "invalid-engine"


def test_endpoint_unknown_session_404(server):
    base, token = server["base"], server["token"]
    code, body = _post(base + "/api/rnd/term_set_engine",
                       {"session": "no-such", "engine": "gemini"}, token=token)
    assert code == 404
    assert body["reason"] == "unknown-session"


def test_endpoint_switches_engine_ok(server):
    base, ts, pid, token = (server["base"], server["ts"], server["pid"],
                            server["token"])
    rec = ts.start_session(pid, "research", backend="claude")
    sid = rec["session_id"]
    code, body = _post(base + "/api/rnd/term_set_engine",
                       {"session": sid, "engine": "gemini"}, token=token)
    assert code == 200
    assert body["ok"] is True
    assert body["session"]["session_id"] == sid
    assert body["session"]["backend"] == "gemini"
    assert ts.get_session(sid)["backend"] == "gemini"
