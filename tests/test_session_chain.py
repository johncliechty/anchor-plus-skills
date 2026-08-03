"""v6 Wave 2 — durable session lineage backbone (hermetic, stdlib only).

Locks the v6 "Linked Pipeline" session-chain backbone (Implementation-Plan
Wave 2): the ``session_registry`` record gains ``parent_session_id`` + ``chain_id``
(``_normalize`` defaults + ``register_session`` params + ``update_session``
allow-list), with a parentless session starting its OWN chain and a child
inheriting its parent's chain. ``chain_for`` / ``chain_members`` resolve and order
a chain (research→plan→build). ``terminal_session.start_session(...,
parent_session_id=…)`` threads both fields through. ``handoff.record_stage_link`` /
``list_stage_links`` persist a generic stage edge in ``discovery.json``,
rescan-durable like the existing ``handoffs`` list.

Hermetic: NO real claude/gemini and NO real PTY — ``ANCHOR_PTY_BACKEND=stub``, a
TEMP git repo for the worktree, a tmp data dir + tmp worktree base. NO worktree is
ever created off the real ``C:\\dev\\Anchor`` repo; never binds ``:8777``.
"""
import importlib
import json
import subprocess

import pytest


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)


def _have_git():
    try:
        return subprocess.run(["git", "--version"],
                              capture_output=True).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


# ── Registry-only fixture (no PTY needed) ────────────────────────────────────

@pytest.fixture
def reg(tmp_path, monkeypatch):
    """Reload session_registry rooted at a tmp ANCHOR_DATA_DIR."""
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    import paths
    importlib.reload(paths)
    import session_registry as sr
    importlib.reload(sr)
    return sr


# ── Full stack fixture (stub PTY + temp git repo + project) ──────────────────

@pytest.fixture
def env(tmp_path, monkeypatch):
    """Tmp data dir + tmp worktree base + stub PTY + a temp git repo + project."""
    if not _have_git():
        pytest.skip("git not on PATH")
    data = tmp_path / "data"
    data.mkdir()
    wbase = tmp_path / "wt-base"
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(wbase))
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)

    import paths
    importlib.reload(paths)
    import pty_manager
    importlib.reload(pty_manager)
    import rnd_registry
    importlib.reload(rnd_registry)
    import effort_history
    importlib.reload(effort_history)
    import sessions
    importlib.reload(sessions)
    import anchor_marker
    importlib.reload(anchor_marker)
    import session_registry
    importlib.reload(session_registry)
    import worktrees
    importlib.reload(worktrees)
    import lanes
    importlib.reload(lanes)
    import terminal_session
    importlib.reload(terminal_session)
    import handoff
    importlib.reload(handoff)

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
        "ts": terminal_session, "reg": session_registry, "handoff": handoff,
        "marker": anchor_marker, "rnd": rnd_registry, "pty": pty_manager,
        "repo": repo, "pid": proj["id"], "wbase": wbase, "data": data,
    }
    try:
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


# ── Field defaults + back-compat ─────────────────────────────────────────────

def test_normalize_defaults_for_old_record(reg):
    """An old record with NEITHER field normalizes to parent='' + chain=own-id."""
    norm = reg._normalize({"session_id": "old-1", "project_id": "p", "lane": "research"})
    assert norm["parent_session_id"] == ""
    assert norm["chain_id"] == "old-1"  # singleton chain keyed on its own id


def test_register_parentless_starts_own_chain(reg):
    rec = reg.register_session("p", "research")
    assert rec["parent_session_id"] == ""
    assert rec["chain_id"] == rec["session_id"]


def test_register_with_chain_and_parent(reg):
    root = reg.register_session("p", "research")
    child = reg.register_session("p", "plan",
                                 parent_session_id=root["session_id"],
                                 chain_id=root["chain_id"])
    assert child["parent_session_id"] == root["session_id"]
    assert child["chain_id"] == root["chain_id"]
    assert child["chain_id"] != child["session_id"]


def test_update_session_allows_lineage_fields(reg):
    rec = reg.register_session("p", "research")
    sid = rec["session_id"]
    updated = reg.update_session(sid, parent_session_id="parent-x",
                                 chain_id="chain-y")
    assert updated["parent_session_id"] == "parent-x"
    assert updated["chain_id"] == "chain-y"


def test_lineage_survives_registry_reload(reg, tmp_path, monkeypatch):
    """Fields persist across a simulated restart (reload the module)."""
    root = reg.register_session("p", "research")
    child = reg.register_session("p", "plan",
                                 parent_session_id=root["session_id"],
                                 chain_id=root["chain_id"])
    # Simulate a restart: reload the module so it re-reads the on-disk store.
    import session_registry as sr2
    importlib.reload(sr2)
    got = sr2.get_session(child["session_id"])
    assert got["parent_session_id"] == root["session_id"]
    assert got["chain_id"] == root["chain_id"]


# ── chain_for / chain_members ────────────────────────────────────────────────

def test_chain_for(reg):
    rec = reg.register_session("p", "research")
    assert reg.chain_for(rec["session_id"]) == rec["chain_id"]
    assert reg.chain_for("does-not-exist") is None


def test_chain_members_ordered_research_plan_build(reg):
    """chain_members returns research → plan → build, then by created_at asc."""
    # Register out of lane-order with explicit created_at to lock the ordering.
    r = reg.register_session("p", "research", session_id="r1")
    chain = r["chain_id"]
    b = reg.register_session("p", "build", session_id="b1",
                             parent_session_id="p1", chain_id=chain)
    p = reg.register_session("p", "plan", session_id="p1",
                             parent_session_id="r1", chain_id=chain)
    members = reg.chain_members(chain)
    lanes_in_order = [m["lane"] for m in members]
    assert lanes_in_order == ["research", "plan", "build"]
    assert [m["session_id"] for m in members] == ["r1", "p1", "b1"]
    # planning (dir-name) sorts the same slot as plan.
    pl = reg.register_session("p", "planning", session_id="pl2",
                              chain_id="other-chain")
    assert reg.chain_members("other-chain")[0]["lane"] == "planning"


def test_chain_members_empty_for_unknown_chain(reg):
    assert reg.chain_members("nope") == []
    assert reg.chain_members("") == []


def test_chain_members_tiebreak_by_created_at(reg, monkeypatch):
    """Two same-lane members order by created_at ascending."""
    import time as _t
    chain = "c-tie"
    monkeypatch.setattr(_t, "time", lambda: 100.0)
    a = reg.register_session("p", "research", session_id="a", chain_id=chain)
    monkeypatch.setattr(_t, "time", lambda: 200.0)
    b = reg.register_session("p", "research", session_id="b", chain_id=chain)
    members = reg.chain_members(chain)
    assert [m["session_id"] for m in members] == ["a", "b"]


# ── terminal_session.start_session(parent_session_id=…) through the stub PTY ──

def test_start_session_parentless_starts_own_chain(env):
    ts, reg = env["ts"], env["reg"]
    rec = ts.start_session(env["pid"], "research", backend="claude")
    assert rec["parent_session_id"] == ""
    assert rec["chain_id"] == rec["session_id"]


def test_start_session_with_parent_inherits_chain(env):
    ts, reg = env["ts"], env["reg"]
    parent = ts.start_session(env["pid"], "research", backend="claude")
    child = ts.start_session(env["pid"], "plan", backend="claude",
                             parent_session_id=parent["session_id"])
    assert child["parent_session_id"] == parent["session_id"]
    assert child["chain_id"] == parent["chain_id"]
    # The ORIGINAL parent record is never mutated.
    again = reg.get_session(parent["session_id"])
    assert again["parent_session_id"] == ""
    assert again["chain_id"] == parent["session_id"]
    # chain_members resolves the ordered chain [R, P].
    members = reg.chain_members(parent["chain_id"])
    assert [m["session_id"] for m in members] == \
        [parent["session_id"], child["session_id"]]
    assert [m["lane"] for m in members] == ["research", "plan"]


def test_start_session_unknown_parent_starts_fresh_chain(env):
    ts = env["ts"]
    rec = ts.start_session(env["pid"], "plan", backend="claude",
                           parent_session_id="ghost-id")
    # Unknown parent → its own chain, no dangling parent link.
    assert rec["parent_session_id"] == ""
    assert rec["chain_id"] == rec["session_id"]


# ── Generic stage edge: persistence across reload + rescan ───────────────────

def test_stage_link_record_and_list(env):
    ho, repo, pid = env["handoff"], env["repo"], env["pid"]
    res = ho.record_stage_link(repo, pid, "r1", "p1", kind="research->plan")
    assert res["ok"] is True
    assert res["entry"]["from_session_id"] == "r1"
    assert res["entry"]["to_session_id"] == "p1"
    assert res["entry"]["kind"] == "research->plan"
    links = ho.list_stage_links(repo, pid)
    assert len(links) == 1
    assert links[0]["from_session_id"] == "r1"


def test_stage_link_idempotent_upsert(env):
    ho, repo, pid = env["handoff"], env["repo"], env["pid"]
    ho.record_stage_link(repo, pid, "r1", "p1", kind="k1")
    ho.record_stage_link(repo, pid, "r1", "p1", kind="k2")  # same pair → upsert
    links = ho.list_stage_links(repo, pid)
    assert len(links) == 1
    assert links[0]["kind"] == "k2"
    # A different pair appends a second edge.
    ho.record_stage_link(repo, pid, "p1", "b1", kind="plan->build")
    assert len(ho.list_stage_links(repo, pid)) == 2


def test_stage_link_missing_id_rejected(env):
    ho, repo, pid = env["handoff"], env["repo"], env["pid"]
    assert ho.record_stage_link(repo, pid, "", "p1")["ok"] is False
    assert ho.record_stage_link(repo, pid, "r1", "")["ok"] is False
    assert ho.list_stage_links(repo, pid) == []


def test_stage_link_survives_fresh_load(env):
    """The edge is on disk; a fresh read of discovery.json still sees it."""
    ho, repo, pid, marker = (env["handoff"], env["repo"], env["pid"],
                             env["marker"])
    ho.record_stage_link(repo, pid, "r1", "p1", kind="research->plan")
    sidecar = marker.sidecar_path(repo, pid)
    fresh = json.loads(sidecar.read_text(encoding="utf-8"))
    assert isinstance(fresh.get("stage_links"), list)
    assert fresh["stage_links"][0]["to_session_id"] == "p1"


def test_stage_link_survives_rescan(env):
    """A rescan (write_anchor_md merge) preserves the stage edge, like handoffs."""
    ho, repo, pid, marker = (env["handoff"], env["repo"], env["pid"],
                             env["marker"])
    ho.record_stage_link(repo, pid, "r1", "p1", kind="research->plan")
    # Rescan rewrites the brownfield-scan keys but must preserve stage_links.
    marker.write_anchor_md(str(repo))
    links = ho.list_stage_links(repo, pid)
    assert len(links) == 1
    assert links[0]["from_session_id"] == "r1"
    assert links[0]["to_session_id"] == "p1"


def test_stage_link_coexists_with_handoffs(env):
    """record_handoff (plan→build) and record_stage_link don't interfere."""
    ho, repo, pid = env["handoff"], env["repo"], env["pid"]
    ho.record_stage_link(repo, pid, "r1", "p1", kind="research->plan")
    plan_set = {"plan_session_id": "p1", "plan_dir": "planning/x",
                "doc_rels": ["planning/x/MASTER-PLAN.md"]}
    ho.record_handoff(repo, pid, "b1", plan_set)
    assert len(ho.list_stage_links(repo, pid)) == 1
    assert len(ho.list_handoffs(repo, pid)) == 1
