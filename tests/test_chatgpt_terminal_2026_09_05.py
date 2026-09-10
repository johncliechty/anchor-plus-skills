"""ChatGPT as a first-class Terminal engine (John, 2026-09-05) — the gate for the build.

Hermetic: stub PTY (ANCHOR_PTY_BACKEND=stub) + the ANCHOR_ENGINE_CMD stub from conftest;
no real engine is ever spawned. The seat's whole change: one gate deleted, two truth
tables widened, a Doctor read-only posture, and honest accounting.
"""
import importlib
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import session_registry as _reg  # noqa: E402


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    wbase = tmp_path / "wt-base"
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "profile"))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(wbase))
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    import paths; importlib.reload(paths)
    import pty_manager; importlib.reload(pty_manager)
    import rnd_registry; importlib.reload(rnd_registry)
    import session_registry; importlib.reload(session_registry)
    import worktrees; importlib.reload(worktrees)
    import lanes; importlib.reload(lanes)
    import terminal_session; importlib.reload(terminal_session)
    # Exercise model policy while retaining the in-memory stub transport: the
    # ordinary stub backend deliberately bypasses model resolution.
    class PolicyFixtureBackend(pty_manager.StubBackend):
        name = "policy-fixture"

    policy_backend = PolicyFixtureBackend()
    monkeypatch.setattr(pty_manager, "select_backend", lambda *args, **kwargs: policy_backend)
    import anchor_settings
    anchor_settings.save_settings(default_cli="chatgpt", coding_family="chatgpt", review_family="grok")
    import model_policy
    model_policy._MEMORY.clear()
    def synthetic_catalog(family, **kwargs):
        return [{"model": "fixture-frontier", "efforts": ["high", "ultra"],
                 "rank": 0, "upgrade": None, "evidence": "test_catalog"}], "fixture-cli"
    monkeypatch.setattr(model_policy, "discover", synthetic_catalog)
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial")
    proj = rnd_registry.add_project("Temp", str(repo), scaffold=False)
    yield {"ts": terminal_session, "pty": pty_manager, "reg": session_registry, "pid": proj["id"]}
    try:
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


def test_chatgpt_backend_is_a_registry_backend():
    assert _reg.BACKEND_CHATGPT == "chatgpt"
    assert _reg.BACKEND_CHATGPT in _reg.VALID_BACKENDS


def test_the_gate_is_gone_and_unknown_backends_still_refuse(env):
    ts = env["ts"]
    ts._check_engine_allowed("plan", "chatgpt")          # no raise (was chatgpt-gated-bridge-pending)
    with pytest.raises(ts.TerminalSessionError, match="unknown backend"):
        ts._check_engine_allowed("plan", "not-an-engine")


def test_a_terminal_opens_on_chatgpt_seeded_once(env):
    ts, reg, pid = env["ts"], env["reg"], env["pid"]
    rec = ts.start_session(pid, "plan", backend="chatgpt")
    sid = rec["session_id"]
    assert rec["status"] == reg.STATUS_RUNNING
    assert rec["backend"] == "chatgpt"
    assert rec["seeded"] is True and rec["seed_text"]      # the lane skill seed, delivered exactly once
    assert sid in env["pty"].live_sessions()
    # (seen on the page 2026-09-05) the seed rides Codex's positional PROMPT, not stdin
    cmd = env["pty"]._LIVE[sid].cmd
    assert cmd[-1] == rec["seed_text"].strip()
    assert "check_for_update_on_startup=false" in cmd
    assert cmd[cmd.index("--model") + 1] == "fixture-frontier"
    assert 'model_reasoning_effort="ultra"' in cmd
    assert reg.get_session(sid)["model_policy"]["model"] == "fixture-frontier"
    # honest accounting: a Codex session's segment is unmeasured (RULED Option C)
    assert reg.get_session(sid)["usage_gemini_segment"] is True
    out = ts.read_since(sid, 0)
    assert out["status"] == "running"


def test_launch_argv_has_no_session_pin_and_no_update_menu_for_codex(env):
    ts = env["ts"]
    assert ts._engine_launch_argv("codex", "chatgpt", "0000-uuid") == [
        "codex", "-c", "check_for_update_on_startup=false"]


def test_switch_to_and_from_chatgpt_leaves_no_orphan_pty(env):
    ts, reg, pid = env["ts"], env["reg"], env["pid"]
    rec = ts.start_session(pid, "research", backend="claude")
    sid = rec["session_id"]
    swapped = ts.switch_engine(sid, "chatgpt")
    assert (swapped.get("backend") or reg.get_session(sid)["backend"]) == "chatgpt"
    assert len(env["pty"].live_sessions()) == 1, "the swap reaps the old PTY"
    assert "check_for_update_on_startup=false" in env["pty"]._LIVE[sid].cmd
    back = ts.switch_engine(sid, "claude")
    assert (back.get("backend") or reg.get_session(sid)["backend"]) == "claude"
    assert len(env["pty"].live_sessions()) == 1
    # the mixed session stays honestly marked even after returning to claude
    assert reg.get_session(sid)["usage_gemini_segment"] is True


def test_doctor_posture_on_chatgpt_is_read_only(env):
    ts = env["ts"]
    assert ts.DOCTOR_READONLY_CLI_ARGS[ts._reg.BACKEND_CHATGPT] == ("-s", "read-only")


def test_default_terminal_uses_dashboard_not_sticky_project_engine(env):
    ts, pid = env["ts"], env["pid"]
    ts.start_session(pid, "research", backend="claude")
    assert ts.start_session(pid, "research")["backend"] == "chatgpt"


def test_failed_capability_switch_preserves_live_session(env, monkeypatch):
    import model_policy
    ts, reg = env["ts"], env["reg"]
    rec = ts.start_session(env["pid"], "research", backend="chatgpt")
    sid = rec["session_id"]
    old_child = env["pty"]._LIVE[sid]
    model_policy._MEMORY.clear()
    def unavailable(*args, **kwargs):
        raise model_policy.PolicyUnavailable("claude", "fixture unavailable")
    monkeypatch.setattr(model_policy, "discover", unavailable)
    with pytest.raises(ts.TerminalSessionError, match="fixture unavailable"):
        ts.switch_engine(sid, "claude")
    assert env["pty"]._LIVE[sid] is old_child
    assert reg.get_session(sid)["backend"] == "chatgpt"


def test_live_codex_spawn_is_still_refused_under_pytest(env, monkeypatch):
    ts = env["ts"]
    monkeypatch.delenv("ANCHOR_TESTS_ALLOW_LIVE", raising=False)
    with pytest.raises(ts.TerminalSessionError, match="live-engine-spawn-refused"):
        ts.assert_not_live_engine_under_test([r"C:\\Users\\x\\codex.exe"])


def test_rollup_treats_a_codex_session_as_an_unmeasured_segment():
    import rollup_honesty as rh
    assert rh.has_gemini_segment({"backend": "chatgpt"}) is True
    assert rh.has_gemini_segment({"backend": "claude"}) is False


def test_doctor_diagnose_on_chatgpt_gets_the_read_only_fence_and_grok_still_refuses(env):
    """Doctor Diagnose fails closed for any backend without a tested read-only argv
    contract; chatgpt now has one (-s read-only overrides John's full-access Codex
    config), grok still has none."""
    ts = env["ts"]
    with pytest.raises(ts.TerminalSessionError, match="no explicitly tested read-only argv contract"):
        ts.start_doctor_session(backend="grok")
    try:
        rec, reused = ts.start_doctor_session(backend="chatgpt")
    except ts.TerminalSessionError as exc:
        # a hermetic registry may lack the Doctor project; the fence itself must not be the refusal
        assert "read-only argv contract" not in str(exc), str(exc)
    else:
        assert rec["backend"] == "chatgpt"
        assert reused is False
        # the fence is on the SPAWN, not just in the table (Grok's diff review)
        cmd = env["pty"]._LIVE[rec["session_id"]].cmd
        assert cmd.count("-s") == 1 and cmd[cmd.index("-s") + 1] == "read-only", cmd
