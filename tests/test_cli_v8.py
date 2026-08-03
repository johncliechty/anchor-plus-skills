"""Wave 8 — CLI mirror of the v8 "Durable Artifacts" read seams (anchor.py rnd ...).

Proves IMPLEMENTATION-PLAN.md "## Wave 8 — CLI mirror": the new read subcommands
DELEGATE to the shared v8 seams (no forked logic):

  - rnd remote <pid>                       → project_remote.remote_status
  - rnd docs <pid> --session <id> [--lane] → effort_history.efforts_for_session_id

Both are READ-ONLY (never run the model / start a PTY / hit the network / push)
and HONEST when absent (an unlinked project; a session with no persisted docs).
Hermetic: tmp ANCHOR_DATA_DIR, stub PTY backend, ANCHOR_RUNNER_CMD →
tests/fake_claude.py (NEVER live claude / real PTY / :8777 / real gh / network).
The remote state + persisted doc efforts are seeded DIRECTLY via the shared
modules so the test needs no live session — it exercises the read mirror only.
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
    monkeypatch.delenv("ANCHOR_GH_CMD", raising=False)
    import paths
    importlib.reload(paths)
    paths.ensure_data_dirs()
    for name in ("job_runner", "rnd_registry", "effort_history", "sessions",
                 "session_registry", "worktrees", "pty_manager",
                 "terminal_session", "summarizer", "anchor_marker",
                 "project_remote", "anchor"):
        importlib.reload(importlib.import_module(name))
    import anchor
    import rnd_registry
    import effort_history
    import project_remote
    yield {"tmp": tmp_path, "anchor": anchor, "rnd": rnd_registry,
           "eh": effort_history, "remote": project_remote}
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


def _seed_persisted_doc(env, folder, pid, lane, session_id, rel, title):
    """Record a persisted DISCOVERED doc effort tagged with ``session_id`` —
    exactly the shape the v8 keystone (persist_session_docs) produces — so the
    `rnd docs` read mirror has something to resolve, with no live session."""
    eh = env["eh"]
    store_lane = eh._resolve_subdir(lane)
    (folder / rel).parent.mkdir(parents=True, exist_ok=True)
    (folder / rel).write_text("# doc\n", encoding="utf-8")
    jid = eh.discovered_job_id(store_lane, rel)
    eh.record_effort(folder, pid, store_lane, jid, skill=None,
                     extra={"source": eh.SOURCE_DISCOVERED, "kind": "plan",
                            "title": title, "artifact_path": rel,
                            "status": "imported", "session_id": session_id})


# ── rnd_remote mirror ──────────────────────────────────────────────────────────

def test_rnd_remote_unlinked_is_honest(env):
    """An unlinked project → linked=False, empty url, auto_push False (no network)."""
    anchor = env["anchor"]
    proj, _ = _mkproject(env)
    st = anchor.rnd_remote(proj["id"])
    assert st["linked"] is False
    assert st["remote_url"] == ""
    assert st["auto_push"] is False


def test_rnd_remote_reflects_persisted_link_and_optin(env):
    """After set_remote + set_auto_push the mirror reflects the persisted state."""
    anchor, rnd = env["anchor"], env["rnd"]
    proj, _ = _mkproject(env)
    pid = proj["id"]
    rnd.set_remote(pid, "https://github.com/johncliechty/x")
    rnd.set_auto_push(pid, True)
    st = anchor.rnd_remote(pid)
    assert st["linked"] is True
    assert st["remote_url"] == "https://github.com/johncliechty/x"
    assert st["auto_push"] is True
    # Agrees with the shared seam directly.
    assert st == env["remote"].remote_status(pid)


def test_rnd_remote_unknown_project_raises_keyerror(env):
    anchor = env["anchor"]
    with pytest.raises(KeyError):
        anchor.rnd_remote("deadbeef-not-real")


# ── rnd_docs mirror ─────────────────────────────────────────────────────────────

def test_rnd_docs_lists_persisted_docs(env):
    anchor = env["anchor"]
    proj, folder = _mkproject(env)
    pid = proj["id"]
    sid = "sess-docs"
    _seed_persisted_doc(env, folder, pid, "plan", sid,
                        "planning/rnd-x/MASTER-PLAN.md", "Master Plan")
    _seed_persisted_doc(env, folder, pid, "plan", sid,
                        "planning/rnd-x/IMPLEMENTATION-PLAN.md", "Impl Plan")
    docs = anchor.rnd_docs(pid, "plan", sid)
    paths = {d["path"] for d in docs}
    assert "planning/rnd-x/MASTER-PLAN.md" in paths
    assert "planning/rnd-x/IMPLEMENTATION-PLAN.md" in paths
    assert all(d.get("title") for d in docs)


def test_rnd_docs_honest_absent_when_none(env):
    """A session that persisted nothing → empty list (never fabricated)."""
    anchor = env["anchor"]
    proj, _ = _mkproject(env)
    assert anchor.rnd_docs(proj["id"], "plan", "no-such-session") == []


def test_rnd_docs_unknown_project_raises_keyerror(env):
    anchor = env["anchor"]
    with pytest.raises(KeyError):
        anchor.rnd_docs("deadbeef-not-real", "plan", "x")


# ── the _rnd_cli dispatcher (argv path) ──────────────────────────────────────

def test_cli_remote_unlinked_prints_not_linked(env, capsys):
    anchor = env["anchor"]
    proj, _ = _mkproject(env)
    anchor._rnd_cli(["remote", proj["id"]])
    out = capsys.readouterr().out
    assert "NOT LINKED" in out
    assert "auto_push:  off" in out


def test_cli_remote_linked_prints_url(env, capsys):
    anchor, rnd = env["anchor"], env["rnd"]
    proj, _ = _mkproject(env)
    pid = proj["id"]
    rnd.set_remote(pid, "https://github.com/johncliechty/x")
    rnd.set_auto_push(pid, True)
    anchor._rnd_cli(["remote", pid])
    out = capsys.readouterr().out
    assert "LINKED" in out
    assert "https://github.com/johncliechty/x" in out
    assert "auto_push:  on" in out


def test_cli_docs_prints_persisted(env, capsys):
    anchor = env["anchor"]
    proj, folder = _mkproject(env)
    pid = proj["id"]
    sid = "sess-cli-docs"
    _seed_persisted_doc(env, folder, pid, "plan", sid,
                        "planning/rnd-x/IMPLEMENTATION-PLAN.md", "Impl Plan")
    anchor._rnd_cli(["docs", pid, "--session", sid, "--lane", "plan"])
    out = capsys.readouterr().out
    assert "1 persisted document" in out
    assert "IMPLEMENTATION-PLAN.md" in out


def test_cli_docs_honest_absent(env, capsys):
    anchor = env["anchor"]
    proj, _ = _mkproject(env)
    anchor._rnd_cli(["docs", proj["id"], "--session", "nope", "--lane", "plan"])
    out = capsys.readouterr().out
    assert "No persisted documents" in out


def test_cli_remote_usage_when_missing_args(env, capsys):
    anchor = env["anchor"]
    anchor._rnd_cli(["remote"])
    out = capsys.readouterr().out
    assert "Usage: anchor.py rnd remote" in out


def test_cli_docs_usage_when_missing_args(env, capsys):
    anchor = env["anchor"]
    proj, _ = _mkproject(env)
    anchor._rnd_cli(["docs", proj["id"]])
    out = capsys.readouterr().out
    assert "Usage: anchor.py rnd docs" in out


def test_cli_remote_unknown_project_clean(env, capsys):
    anchor = env["anchor"]
    anchor._rnd_cli(["remote", "deadbeef-not-real"])
    out = capsys.readouterr().out
    assert "Unknown project" in out


def test_cli_rnd_usage_lists_remote_and_docs(env, capsys):
    anchor = env["anchor"]
    anchor._rnd_cli([])
    out = capsys.readouterr().out
    assert "remote" in out
    assert "docs" in out
