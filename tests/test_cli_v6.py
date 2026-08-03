"""Wave 8 — CLI mirror of the v6 "Linked Pipeline" data seam (anchor.py rnd ...).

Proves IMPLEMENTATION-PLAN.md "## Wave 8 — CLI mirror": the new read subcommand
DELEGATES to the shared v6 modules (no forked logic):

  - rnd chain <pid> --session <id>  → session_registry.chain_for + chain_members

It is read-only (never runs the model / starts a PTY) and HONEST when the chain /
session is absent. Hermetic: tmp ANCHOR_DATA_DIR, stub PTY backend,
ANCHOR_RUNNER_CMD → tests/fake_claude.py (NEVER live claude / real PTY / :8777).
The chain rows are registered directly via ``session_registry.register_session``
so the test needs no git worktree — it exercises the ordering + projection seam.
"""
import importlib
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(tmp_path / "wt"))
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    import paths
    importlib.reload(paths)
    paths.ensure_data_dirs()
    for name in ("job_runner", "rnd_registry", "effort_history", "sessions",
                 "session_registry", "worktrees", "pty_manager",
                 "terminal_session", "anchor_marker", "anchor"):
        importlib.reload(importlib.import_module(name))
    import anchor
    import rnd_registry
    import session_registry
    yield {"tmp": tmp_path, "anchor": anchor, "rnd": rnd_registry,
           "reg": session_registry}
    try:
        import pty_manager
        for sid in list(pty_manager.live_sessions()):
            try:
                pty_manager.kill(sid)
            except Exception:
                pass
    except Exception:
        pass


def _mkproject(env, name="Anchor"):
    folder = env["tmp"] / "proj"
    folder.mkdir(parents=True, exist_ok=True)
    return env["rnd"].add_project(name, str(folder)), folder


def _chain(env, pid):
    """Register a research → planning → build chain DIRECTLY (no PTY/git)."""
    reg = env["reg"]
    r = reg.register_session(pid, "research", session_id="r1")
    p = reg.register_session(pid, "planning", session_id="p1",
                             parent_session_id="r1", chain_id=r["chain_id"])
    b = reg.register_session(pid, "build", session_id="b1",
                             parent_session_id="p1", chain_id=r["chain_id"])
    return r, p, b


# ── rnd_chain mirror ─────────────────────────────────────────────────────────

def test_rnd_chain_returns_ordered_members(env):
    anchor, reg = env["anchor"], env["reg"]
    proj, _ = _mkproject(env)
    pid = proj["id"]
    r, p, b = _chain(env, pid)

    out = anchor.rnd_chain(pid, "p1")
    assert out["chain_id"] == r["chain_id"]
    members = out["members"]
    # ordered research → planning → build.
    assert [m["session_id"] for m in members] == ["r1", "p1", "b1"]
    assert [m["lane"] for m in members] == ["research", "planning", "build"]
    # lineage fields present + correct.
    assert members[1]["parent_session_id"] == "r1"
    assert members[2]["parent_session_id"] == "p1"
    # SAFE projection: no worktree_path / branch ever exposed.
    for m in members:
        assert "worktree_path" not in m and "branch" not in m

    # Mirror agrees with the shared registry seam directly.
    cid = reg.chain_for("p1")
    assert cid == out["chain_id"]
    assert [x["session_id"] for x in reg.chain_members(cid)] == \
        ["r1", "p1", "b1"]


def test_rnd_chain_resolves_from_any_member(env):
    """Asking from the build node returns the SAME ordered chain (chain is
    resolved by chain_id, not by which member you ask from)."""
    anchor = env["anchor"]
    proj, _ = _mkproject(env)
    pid = proj["id"]
    _chain(env, pid)
    a = anchor.rnd_chain(pid, "r1")
    c = anchor.rnd_chain(pid, "b1")
    assert [m["session_id"] for m in a["members"]] == \
        [m["session_id"] for m in c["members"]] == ["r1", "p1", "b1"]


def test_rnd_chain_unknown_session_honest_absent(env):
    """An unknown session has no chain → honest {chain_id: None, members: []}."""
    anchor = env["anchor"]
    proj, _ = _mkproject(env)
    out = anchor.rnd_chain(proj["id"], "no-such-session")
    assert out["chain_id"] is None
    assert out["members"] == []


def test_rnd_chain_singleton_is_its_own_chain(env):
    """A parentless session is its own singleton chain (chain_id == its id)."""
    anchor, reg = env["anchor"], env["reg"]
    proj, _ = _mkproject(env)
    pid = proj["id"]
    reg.register_session(pid, "research", session_id="solo")
    out = anchor.rnd_chain(pid, "solo")
    assert out["chain_id"] == "solo"
    assert [m["session_id"] for m in out["members"]] == ["solo"]
    assert out["members"][0]["parent_session_id"] == ""


# ── the _rnd_cli dispatcher (argv path) ──────────────────────────────────────

def test_cli_chain_prints_ordered_chain(env, capsys):
    anchor = env["anchor"]
    proj, _ = _mkproject(env)
    pid = proj["id"]
    _chain(env, pid)
    anchor._rnd_cli(["chain", pid, "--session", "p1"])
    out = capsys.readouterr().out
    assert "3 session(s)" in out
    assert "[research]" in out and "[planning]" in out and "[build]" in out
    # the queried session is marked.
    assert "id=p1 *" in out
    # research → planning → build ordering in the printed lines.
    i_r = out.index("[research]")
    i_p = out.index("[planning]")
    i_b = out.index("[build]")
    assert i_r < i_p < i_b


def test_cli_chain_unknown_session_honest(env, capsys):
    anchor = env["anchor"]
    proj, _ = _mkproject(env)
    anchor._rnd_cli(["chain", proj["id"], "--session", "nope"])
    out = capsys.readouterr().out
    assert "No chain for session" in out


def test_cli_chain_usage_when_missing_session(env, capsys):
    anchor = env["anchor"]
    proj, _ = _mkproject(env)
    anchor._rnd_cli(["chain", proj["id"]])
    out = capsys.readouterr().out
    assert "Usage: anchor.py rnd chain" in out


def test_cli_chain_unknown_project_clean(env, capsys):
    anchor = env["anchor"]
    anchor._rnd_cli(["chain", "deadbeef-not-real", "--session", "p1"])
    out = capsys.readouterr().out
    assert "Unknown project" in out


def test_cli_rnd_usage_lists_chain(env, capsys):
    anchor = env["anchor"]
    anchor._rnd_cli([])
    out = capsys.readouterr().out
    assert "chain" in out
