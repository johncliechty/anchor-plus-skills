"""Wave 2 — durable managed-session registry acceptance (hermetic, stdlib only).

Locks the v3 session registry (MASTER-PLAN §D/§I): a DURABLE registry of managed
terminal sessions persisted under ``.anchor/`` that survives a restart, with
register/get/list(filter)/update/remove, a recovery reconcile against live
processes + worktrees, and a corrupt/missing store that degrades to empty.

Hermetic: ``ANCHOR_DATA_DIR`` is pointed at a tmp dir and the module is reloaded
so it reads that tmp store — NO real ``claude``, NO network, no touching the live
``C:\\dev\\Anchor`` store.
"""
import importlib

import pytest


@pytest.fixture
def reg(tmp_path, monkeypatch):
    """Reload session_registry rooted at a tmp ANCHOR_DATA_DIR."""
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    import paths
    importlib.reload(paths)
    import session_registry as sr
    importlib.reload(sr)
    return sr


# ── CRUD ──────────────────────────────────────────────────────────────────

def test_register_get_list_update_remove(reg):
    rec = reg.register_session("proj-1", "plan", backend="claude",
                               worktree_path="/tmp/wt", branch="anchor/x",
                               label="plan 1")
    sid = rec["session_id"]
    assert sid
    assert rec["project_id"] == "proj-1"
    assert rec["lane"] == "plan"
    assert rec["backend"] == "claude"
    assert rec["status"] == reg.STATUS_IDLE
    assert isinstance(rec["created_at"], float)

    got = reg.get_session(sid)
    assert got["session_id"] == sid
    assert got["label"] == "plan 1"

    # list + filter by project and status
    reg.register_session("proj-2", "research", backend="gemini")
    assert len(reg.list_sessions()) == 2
    assert len(reg.list_sessions(project_id="proj-1")) == 1
    assert reg.list_sessions(project_id="proj-1")[0]["session_id"] == sid

    updated = reg.update_session(sid, status=reg.STATUS_RUNNING)
    assert updated["status"] == reg.STATUS_RUNNING
    assert len(reg.list_sessions(status=reg.STATUS_RUNNING)) == 1

    # created_at is immutable; only allow-listed fields change.
    created_before = reg.get_session(sid)["created_at"]
    reg.update_session(sid, created_at=0.0, lane="build")
    after = reg.get_session(sid)
    assert after["session_id"] == sid
    assert after["created_at"] == created_before
    assert after["lane"] == "build"

    assert reg.remove_session(sid) is True
    assert reg.get_session(sid) is None
    assert reg.remove_session(sid) is False


def test_update_unknown_raises(reg):
    with pytest.raises(KeyError):
        reg.update_session("nope", status=reg.STATUS_DONE)


def test_explicit_session_id_accepted(reg):
    rec = reg.register_session("p", "plan", session_id="fixed-123")
    assert rec["session_id"] == "fixed-123"
    assert reg.get_session("fixed-123") is not None


# ── Durability: round-trip across a simulated restart ─────────────────────

def test_roundtrip_survives_restart(reg, tmp_path, monkeypatch):
    a = reg.register_session("proj-1", "plan", branch="anchor/a",
                             worktree_path=str(tmp_path / "wt-a"))
    b = reg.register_session("proj-1", "build", branch="anchor/b")
    reg.update_session(b["session_id"], status=reg.STATUS_RUNNING)

    # Simulate a server restart: reload the module fresh, same ANCHOR_DATA_DIR.
    import session_registry as sr2
    importlib.reload(sr2)

    sessions = {s["session_id"]: s for s in sr2.list_sessions()}
    assert set(sessions) == {a["session_id"], b["session_id"]}
    assert sessions[a["session_id"]]["branch"] == "anchor/a"
    assert sessions[b["session_id"]]["status"] == sr2.STATUS_RUNNING

    # The store actually lives under .anchor/
    assert sr2.sessions_path().exists()
    assert sr2.sessions_path().parent.name == ".anchor"


# ── Recovery / reconcile ──────────────────────────────────────────────────

def test_reconcile_marks_dead_session_not_running(reg, tmp_path):
    live = reg.register_session("p", "plan", worktree_path=str(tmp_path / "lwt"))
    dead = reg.register_session("p", "build", worktree_path=str(tmp_path / "dwt"))
    (tmp_path / "lwt").mkdir()
    (tmp_path / "dwt").mkdir()
    reg.update_session(live["session_id"], status=reg.STATUS_RUNNING)
    reg.update_session(dead["session_id"], status=reg.STATUS_RUNNING)

    # Only the "live" session id has a live process.
    report = reg.reconcile(live_session_ids={live["session_id"]})
    assert dead["session_id"] in report["stale"]
    assert live["session_id"] not in report["stale"]
    assert dead["session_id"] in report["marked"]
    # The dead one is now not-running; the live one untouched.
    assert reg.get_session(dead["session_id"])["status"] == reg.STATUS_IDLE
    assert reg.get_session(live["session_id"])["status"] == reg.STATUS_RUNNING


def test_reconcile_reports_orphan_worktrees(reg, tmp_path):
    present = reg.register_session("p", "plan",
                                   worktree_path=str(tmp_path / "present"))
    orphan = reg.register_session("p", "build",
                                  worktree_path=str(tmp_path / "gone"))
    (tmp_path / "present").mkdir()  # exists on disk; "gone" does not

    report = reg.reconcile(live_session_ids=set())
    assert orphan["session_id"] in report["orphaned_worktrees"]
    assert present["session_id"] not in report["orphaned_worktrees"]


def test_reconcile_injectable_worktree_predicate(reg):
    s = reg.register_session("p", "plan", worktree_path="/somewhere/wt")
    report = reg.reconcile(live_session_ids=set(),
                           worktree_exists=lambda sid: False)
    assert s["session_id"] in report["orphaned_worktrees"]


def test_reconcile_dry_run_does_not_mutate(reg):
    s = reg.register_session("p", "plan")
    reg.update_session(s["session_id"], status=reg.STATUS_RUNNING)
    report = reg.reconcile(live_session_ids=set(), apply=False)
    assert s["session_id"] in report["stale"]
    assert report["marked"] == []
    # Status unchanged because apply=False.
    assert reg.get_session(s["session_id"])["status"] == reg.STATUS_RUNNING


def test_reconcile_cold_start_all_running_are_stale(reg):
    s = reg.register_session("p", "plan")
    reg.update_session(s["session_id"], status=reg.STATUS_RUNNING)
    # live_session_ids=None → no session is live (cold start).
    report = reg.reconcile(live_session_ids=None)
    assert s["session_id"] in report["stale"]
    assert reg.get_session(s["session_id"])["status"] == reg.STATUS_IDLE


# ── Corrupt / missing store → empty, never crash ──────────────────────────

def test_missing_store_is_empty(reg):
    assert reg.load_sessions() == {}
    assert reg.list_sessions() == []
    assert reg.get_session("x") is None


def test_corrupt_store_is_empty_no_crash(reg):
    reg.register_session("p", "plan")  # creates the store
    p = reg.sessions_path()
    p.write_text("{ this is not valid json ", encoding="utf-8")
    # Best-effort: corrupt → empty, no exception.
    assert reg.load_sessions() == {}
    assert reg.list_sessions() == []
    # And reconcile over a corrupt store is also safe.
    rep = reg.reconcile(live_session_ids=set())
    assert rep["stale"] == [] and rep["orphaned_worktrees"] == []
