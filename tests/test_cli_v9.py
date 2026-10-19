"""Wave 5 — CLI mirror of the v9 "Tidy" read seams (anchor.py rnd ...).

Proves IMPLEMENTATION-PLAN.md "## Wave 5 — CLI mirror": the new read subcommands
DELEGATE to the shared v9 seams (no forked logic):

  - rnd folders                  → rnd_registry.group_by_group
  - rnd ghost-sessions <pid>     → the empty/ghost sessions cleanup_ghost_sessions
                                   WOULD remove (session_registry + effort_history)

Both are READ-ONLY (never delete/kill/move anything / start a PTY / hit the
network) and HONEST when absent (a project with no group → Ungrouped; a project
with no ghosts → []). Hermetic: tmp ANCHOR_DATA_DIR, stub PTY backend,
ANCHOR_RUNNER_CMD → tests/fake_claude.py (NEVER live claude / real PTY / :8777 /
real move). The registry/session rows are seeded DIRECTLY via the shared modules
so the test needs no live session — it exercises the read mirror only.
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
                 "terminal_session", "summarizer", "anchor_marker",
                 "project_move", "anchor"):
        importlib.reload(importlib.import_module(name))
    import anchor
    import rnd_registry
    import effort_history
    import session_registry
    yield {"tmp": tmp_path, "anchor": anchor, "rnd": rnd_registry,
           "eh": effort_history, "sreg": session_registry}
    try:
        import pty_manager
        for sid in list(pty_manager.live_sessions()):
            try:
                pty_manager.kill(sid)
            except Exception:
                pass
    except Exception:
        pass


def _mkproject(env, name="Anchor", group=None):
    folder = env["tmp"] / f"proj-{name.lower().replace(' ', '-')}"
    folder.mkdir(parents=True, exist_ok=True)
    proj = env["rnd"].add_project(name, str(folder))
    if group is not None:
        env["rnd"].set_group(proj["id"], group)
    return proj, folder


# ── rnd_folders mirror ──────────────────────────────────────────────────────────

def test_rnd_folders_buckets_grouped_and_ungrouped(env):
    """Named groups (alpha) first, Ungrouped always last; members under each."""
    anchor, rnd = env["anchor"], env["rnd"]
    a, _ = _mkproject(env, "Alpha", group="Research")
    b, _ = _mkproject(env, "Beta", group="Research")
    c, _ = _mkproject(env, "Gamma")  # ungrouped
    groups = anchor.rnd_folders()
    assert "Research" in groups
    assert "Ungrouped" in groups
    # Ungrouped is always last.
    assert list(groups.keys())[-1] == "Ungrouped"
    research_ids = {e["id"] for e in groups["Research"]}
    assert research_ids == {a["id"], b["id"]}
    ungrouped_ids = {e["id"] for e in groups["Ungrouped"]}
    assert c["id"] in ungrouped_ids


def test_rnd_folders_honest_ungrouped_only_when_no_groups(env):
    """With no groups set, every project buckets under Ungrouped (back-compat)."""
    anchor = env["anchor"]
    p, _ = _mkproject(env, "Solo")
    groups = anchor.rnd_folders()
    assert list(groups.keys()) == ["Ungrouped"]
    assert {e["id"] for e in groups["Ungrouped"]} == {p["id"]}


def test_rnd_folders_agrees_with_shared_seam(env):
    """The mirror returns exactly group_by_group (no forked logic)."""
    anchor, rnd = env["anchor"], env["rnd"]
    _mkproject(env, "X", group="Q")
    assert anchor.rnd_folders() == rnd.group_by_group()


# ── rnd_ghost_sessions mirror ────────────────────────────────────────────────────

def test_rnd_ghost_sessions_lists_empty_done_records(env):
    """A non-running session with NO efforts is a ghost; one WITH efforts is not."""
    anchor, sreg, eh = env["anchor"], env["sreg"], env["eh"]
    proj, folder = _mkproject(env, "GhostProj")
    pid = proj["id"]
    ghost = sreg.register_session(pid, "research", label="empty ghost",
                                  status=sreg.STATUS_DONE)
    keeper = sreg.register_session(pid, "research", label="has work",
                                   status=sreg.STATUS_DONE)
    eh.record_effort(str(folder), pid, "research", "keeper-eff",
                     extra={"source": eh.SOURCE_RUN,
                            "session_id": keeper["session_id"],
                            "title": "a real effort"})
    ghosts = anchor.rnd_ghost_sessions(pid)
    ids = {g["session_id"] for g in ghosts}
    assert ghost["session_id"] in ids
    assert keeper["session_id"] not in ids
    # SAFE projection shape.
    g0 = [g for g in ghosts if g["session_id"] == ghost["session_id"]][0]
    assert set(g0.keys()) == {"session_id", "lane", "status", "label"}
    assert g0["status"] == sreg.STATUS_DONE


def test_rnd_ghost_sessions_excludes_running(env):
    """A RUNNING session is never a ghost (even with no efforts)."""
    anchor, sreg = env["anchor"], env["sreg"]
    proj, _ = _mkproject(env, "LiveProj")
    pid = proj["id"]
    live = sreg.register_session(pid, "build", label="live",
                                 status=sreg.STATUS_RUNNING)
    ghosts = anchor.rnd_ghost_sessions(pid)
    assert live["session_id"] not in {g["session_id"] for g in ghosts}


def test_rnd_ghost_sessions_honest_absent(env):
    """A project with no ghost sessions → empty list (never fabricated)."""
    anchor = env["anchor"]
    proj, _ = _mkproject(env, "Clean")
    assert anchor.rnd_ghost_sessions(proj["id"]) == []


def test_rnd_ghost_sessions_is_read_only(env):
    """Listing ghosts NEVER removes them (read-only mirror; delete is interactive)."""
    anchor, sreg = env["anchor"], env["sreg"]
    proj, _ = _mkproject(env, "Persist")
    pid = proj["id"]
    ghost = sreg.register_session(pid, "research", status=sreg.STATUS_DONE)
    anchor.rnd_ghost_sessions(pid)
    # The ghost record is STILL there — the mirror only listed it.
    assert sreg.get_session(ghost["session_id"]) is not None


def test_rnd_ghost_sessions_unknown_project_raises_keyerror(env):
    anchor = env["anchor"]
    with pytest.raises(KeyError):
        anchor.rnd_ghost_sessions("deadbeef-not-real")


# ── the _rnd_cli dispatcher (argv path) ──────────────────────────────────────

def test_cli_folders_prints_groups(env, capsys):
    anchor = env["anchor"]
    _mkproject(env, "Alpha", group="Research")
    _mkproject(env, "Gamma")
    anchor._rnd_cli(["folders"])
    out = capsys.readouterr().out
    assert "[Research]" in out
    assert "[Ungrouped]" in out
    assert "Alpha" in out


def test_cli_folders_only_ungrouped(env, capsys):
    anchor = env["anchor"]
    _mkproject(env, "Solo")
    anchor._rnd_cli(["folders"])
    out = capsys.readouterr().out
    assert "[Ungrouped]" in out
    assert "Solo" in out


def test_cli_ghost_sessions_prints_ghosts(env, capsys):
    anchor, sreg = env["anchor"], env["sreg"]
    proj, _ = _mkproject(env, "GP")
    sreg.register_session(proj["id"], "research", label="phantom",
                          status=sreg.STATUS_DONE)
    anchor._rnd_cli(["ghost-sessions", proj["id"]])
    out = capsys.readouterr().out
    assert "ghost (empty) session" in out
    assert "phantom" in out


def test_cli_ghost_sessions_honest_absent(env, capsys):
    anchor = env["anchor"]
    proj, _ = _mkproject(env, "CleanP")
    anchor._rnd_cli(["ghost-sessions", proj["id"]])
    out = capsys.readouterr().out
    assert "No ghost (empty) sessions" in out


def test_cli_ghost_sessions_usage_when_missing_args(env, capsys):
    anchor = env["anchor"]
    anchor._rnd_cli(["ghost-sessions"])
    out = capsys.readouterr().out
    assert "Usage: anchor.py rnd ghost-sessions" in out


def test_cli_ghost_sessions_unknown_project_clean(env, capsys):
    anchor = env["anchor"]
    anchor._rnd_cli(["ghost-sessions", "deadbeef-not-real"])
    out = capsys.readouterr().out
    assert "Unknown project" in out


def test_cli_rnd_usage_lists_folders_and_ghost_sessions(env, capsys):
    anchor = env["anchor"]
    anchor._rnd_cli([])
    out = capsys.readouterr().out
    assert "folders" in out
    assert "ghost-sessions" in out
