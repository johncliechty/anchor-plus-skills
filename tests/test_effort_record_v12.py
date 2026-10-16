"""v12 Wave 1 — effort record: stage fields + ``effort_managed`` + ``effort_id``
passthrough + back-compat normalize.

Covers the Wave-1 Given/When/Then EXACTLY as written in the frozen plan
(``planning/rnd-v12/IMPLEMENTATION-PLAN.md`` §Wave 1):

  - an OLD record (no new fields) normalizes → ``kind=='trio'``,
    ``current_stage=='research'``, ``stage_history==[]``, ``effort_id==sid``,
    ``effort_managed==False``, no exception;
  - ``start_session(effort_id='E1', effort_managed=True)`` → ``effort_id=='E1'``,
    ``effort_managed==True``; a legacy ``start_session(...)`` →
    ``effort_managed==False``, ``effort_id==own sid``;
  - ``set_current_stage(sid,'plan','planning','abc')`` → prior entry closed
    (``ended_at`` set, ``state=='done'``), new plan entry appended
    (``store_lane=='planning'``, ``baseline_ref=='abc'``, ``state=='active'``),
    ``current_stage=='plan'``, ``lane=='planning'``;
  - ``_effort_zone`` routes research → Research; plan/build → Plan/Build;
    kind in {general, grass-dev} → None.

Hermetic: NO real claude/gemini, NO real PTY — ``ANCHOR_PTY_BACKEND=stub``, a
temp git repo for the worktree, tmp data + tmp worktree base,
``ANCHOR_PROACTIVE_SUMMARY`` OFF. NEVER binds ``:8777`` / touches real data /
network.
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


@pytest.fixture
def env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    wbase = tmp_path / "wt-base"
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(wbase))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    monkeypatch.delenv("ANCHOR_TERMINAL_SEED", raising=False)
    monkeypatch.delenv("ANCHOR_PROACTIVE_SUMMARY", raising=False)

    for mod in ("paths", "job_runner", "pty_manager", "rnd_registry",
                "effort_history", "sessions", "anchor_marker",
                "session_registry", "worktrees", "lanes", "summarizer",
                "handoff", "terminal_session"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()

    import session_registry
    import terminal_session
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
        "reg": session_registry, "ts": terminal_session, "rnd": rnd_registry,
        "pty": pty_manager, "repo": repo, "pid": proj["id"],
    }
    yield bundle
    try:
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


# ════════════════════════════════════════════════════════════════════════════
# 1) Back-compat normalize: an OLD record (no v12 fields) loads cleanly.
# ════════════════════════════════════════════════════════════════════════════

def test_old_record_normalizes_with_effort_defaults():
    """Given an old record {lane:'research'} (no new fields), When normalized,
    Then kind=='trio', current_stage=='research', stage_history==[],
    effort_id==sid, effort_managed==False; no exception."""
    import importlib
    import session_registry as reg
    reg = importlib.reload(reg)

    sid = "old-sid-1234"
    rec = reg._normalize({"session_id": sid, "lane": "research"})

    assert rec["kind"] == "trio"
    assert rec["current_stage"] == "research"
    assert rec["stage_history"] == []
    assert rec["seeded_stages"] == []
    assert rec["effort_id"] == sid
    assert rec["effort_managed"] is False


def test_old_record_kind_derivation_general_and_grass():
    """A non-trio lane derives kind general/grass-dev with current_stage ''."""
    import importlib
    import session_registry as reg
    reg = importlib.reload(reg)

    g = reg._normalize({"session_id": "s-g", "lane": "general"})
    assert g["kind"] == "general"
    assert g["current_stage"] == ""

    gr = reg._normalize({"session_id": "s-gr", "lane": "grass"})
    assert gr["kind"] == "grass-dev"
    assert gr["current_stage"] == ""

    # store-form planning lane derives current_stage 'plan'
    pl = reg._normalize({"session_id": "s-pl", "lane": "planning"})
    assert pl["kind"] == "trio"
    assert pl["current_stage"] == "plan"


# ════════════════════════════════════════════════════════════════════════════
# 2) start_session effort_id / effort_managed passthrough.
# ════════════════════════════════════════════════════════════════════════════

def test_start_session_inherits_effort_id_and_managed_flag(env):
    """Given start_session(pid,'research', effort_id='E1', effort_managed=True),
    Then the new record has effort_id=='E1' and effort_managed==True."""
    ts, pid = env["ts"], env["pid"]
    rec = ts.start_session(pid, "research", backend="claude",
                           effort_id="E1", effort_managed=True)
    assert rec["effort_id"] == "E1"
    assert rec["effort_managed"] is True
    # persists/round-trips unchanged
    persisted = env["reg"].get_session(rec["session_id"])
    assert persisted["effort_id"] == "E1"
    assert persisted["effort_managed"] is True


def test_legacy_start_session_keeps_defaults(env):
    """Given a legacy start_session(pid,'research'), Then effort_managed==False
    and effort_id==own sid (NO behavior change for existing callers)."""
    ts, pid = env["ts"], env["pid"]
    rec = ts.start_session(pid, "research", backend="claude")
    assert rec["effort_managed"] is False
    assert rec["effort_id"] == rec["session_id"]


# ════════════════════════════════════════════════════════════════════════════
# 3) set_current_stage: close prior + append new.
# ════════════════════════════════════════════════════════════════════════════

def test_set_current_stage_closes_prior_and_appends(env):
    """Given set_current_stage(sid,'plan','planning','abc') on a research effort,
    Then the prior research entry is closed (ended_at set, state=='done'), a new
    plan entry is appended (store_lane=='planning', baseline_ref=='abc',
    state=='active'), current_stage=='plan', lane=='planning'."""
    ts, reg, pid = env["ts"], env["reg"], env["pid"]
    rec = ts.start_session(pid, "research", backend="claude",
                           effort_id="E2", effort_managed=True)
    sid = rec["session_id"]

    # Seed an OPEN research stage entry so there is a prior active entry to close.
    reg.set_current_stage(sid, "research", "research", "B0")
    before = reg.get_session(sid)
    research_ent = reg.stage_entry(before, "research")
    assert research_ent is not None
    assert research_ent["state"] == "active"
    assert research_ent["ended_at"] is None

    updated = reg.set_current_stage(sid, "plan", "planning", "abc")

    # Prior research entry closed.
    research_closed = reg.stage_entry(updated, "research")
    assert research_closed["ended_at"] is not None
    assert research_closed["state"] == "done"

    # New plan entry appended + active.
    plan_ent = reg.stage_entry(updated, "plan")
    assert plan_ent is not None
    assert plan_ent["store_lane"] == "planning"
    assert plan_ent["baseline_ref"] == "abc"
    assert plan_ent["state"] == "active"
    assert plan_ent["ended_at"] is None

    # Record-level flip.
    assert updated["current_stage"] == "plan"
    assert updated["lane"] == "planning"
    # Persisted.
    assert reg.get_session(sid)["current_stage"] == "plan"


def test_effort_root_and_stage_entry_helpers(env):
    """effort_root returns the effort_id; stage_entry returns the matching entry
    or None for an unknown stage."""
    ts, reg, pid = env["ts"], env["reg"], env["pid"]
    rec = ts.start_session(pid, "research", backend="claude",
                           effort_id="E3", effort_managed=True)
    sid = rec["session_id"]
    assert reg.effort_root(sid) == "E3"
    assert reg.effort_root("no-such-sid") is None
    # No stage history yet → stage_entry None.
    assert reg.stage_entry(reg.get_session(sid), "plan") is None


# ════════════════════════════════════════════════════════════════════════════
# 4) anchor_gui._effort_zone board-routing accessor.
# ════════════════════════════════════════════════════════════════════════════

def test_effort_zone_routing(env):
    """_effort_zone: research→Research; plan/build→Plan/Build;
    kind in {general,grass-dev}→None."""
    import anchor_gui as gui

    assert gui._effort_zone(
        {"kind": "trio", "current_stage": "research"}) == "Research"
    assert gui._effort_zone(
        {"kind": "trio", "current_stage": "plan"}) == "Plan/Build"
    assert gui._effort_zone(
        {"kind": "trio", "current_stage": "build"}) == "Plan/Build"
    assert gui._effort_zone(
        {"kind": "general", "current_stage": ""}) is None
    assert gui._effort_zone(
        {"kind": "grass-dev", "current_stage": ""}) is None
    # A grass-dev/general record with a stray stage still routes to None (kind wins).
    assert gui._effort_zone(
        {"kind": "grass-dev", "current_stage": "research"}) is None
    # Non-dict / empty → None (defensive).
    assert gui._effort_zone(None) is None
    assert gui._effort_zone({}) is None


def test_normalize_rederives_empty_current_stage():
    """R1-01: a trio record persisted with current_stage=='' must re-derive
    from lane (not stay '')."""
    import importlib
    sr = importlib.import_module("session_registry")
    n = sr._normalize({"session_id": "s1", "lane": "research", "current_stage": ""})
    assert n["current_stage"] == "research"
    n2 = sr._normalize({"session_id": "s2", "lane": "planning", "current_stage": ""})
    assert n2["current_stage"] == "plan"


def test_normalize_deepcopies_stage_history_entries():
    """R2-1: _normalize must NOT alias the caller's stage-entry dicts (W4/W5
    mutate entries in place)."""
    import importlib
    sr = importlib.import_module("session_registry")
    src = [{"stage": "research", "state": "active", "store_lane": "research"}]
    n = sr._normalize({"session_id": "s3", "lane": "research", "stage_history": src})
    n["stage_history"][0]["state"] = "MUTATED"
    assert src[0]["state"] == "active", "normalize aliased the caller's stage entry"
