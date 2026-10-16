"""v12 Wave 9 — effort view-layer: group chains into efforts (NEW effort_view.py).

Covers the Wave-9 Given/When/Then EXACTLY as written in the frozen plan
(``planning/rnd-v12/IMPLEMENTATION-PLAN.md`` §Wave 9):

  - a research→plan→build chain (3 registry records) + ONE new single-session
    effort (carrying ``stage_history``) → ``build_effort_view`` → EXACTLY 2
    efforts; the chain effort ``current_stage=='build'`` with 3 stages
    referencing each member's docs; the new effort passes through;
  - dedup (Shark SK-6): a chain whose build member is ALSO present as a live
    record carrying ``stage_history`` → EXACTLY ONE effort (len==1; live wins);
  - idempotent: build twice → equal results;
  - guard: the Anchor repo (``paths.CODE_DIR``) is never mutated; the view is
    READ-ONLY (no reap of a live member);
  - backfill: a single-session R→P→B effort backfilled pins ONLY the build
    product, never MASTER-PLAN.md.

Hermetic: NO real claude/gemini, NO real PTY — a temp git repo for the
worktree, tmp data + tmp worktree base, ``ANCHOR_PROACTIVE_SUMMARY`` OFF. NEVER
binds ``:8777`` / touches real data / network.
"""
import importlib
import subprocess
import time
from pathlib import Path

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


pytestmark = pytest.mark.skipif(not _have_git(), reason="git not on PATH")


@pytest.fixture
def env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    wbase = tmp_path / "wt-base"
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(wbase))
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    monkeypatch.delenv("ANCHOR_PROACTIVE_SUMMARY", raising=False)
    for mod in ("paths", "rnd_registry", "effort_history", "sessions",
                "anchor_marker", "session_registry", "summarizer",
                "deliverables", "effort_view"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import rnd_registry, effort_history, session_registry, effort_view, deliverables

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial")

    proj = rnd_registry.add_project("Temp", str(repo), scaffold=False)
    return {
        "reg": session_registry, "eh": effort_history, "ev": effort_view,
        "rnd": rnd_registry, "deliv": deliverables, "repo": repo,
        "pid": proj["id"], "data": data,
    }


def _commit(repo, rel, body, msg):
    p = Path(repo) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    _git(repo, "add", "--", rel)
    _git(repo, "commit", "-m", msg)


def _write(repo, rel, body):
    p = Path(repo) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


def _make_chain(env):
    """Register a legacy 3-record research→plan→build chain (shared chain_id),
    each stage's docs persisted (worktree-only). Returns the chain_id + sids."""
    reg, eh, repo, pid = env["reg"], env["eh"], env["repo"], env["pid"]
    # Research record = chain root.
    r = reg.register_session(pid, "research", status=reg.STATUS_DONE,
                             worktree_path=str(repo), label="research")
    cid = r["chain_id"]
    rsid = r["session_id"]
    time.sleep(0.01)
    p = reg.register_session(pid, "planning", status=reg.STATUS_DONE,
                             worktree_path=str(repo), label="plan",
                             parent_session_id=rsid, chain_id=cid)
    psid = p["session_id"]
    time.sleep(0.01)
    b = reg.register_session(pid, "build", status=reg.STATUS_DONE,
                             worktree_path=str(repo), label="build",
                             parent_session_id=psid, chain_id=cid)
    bsid = b["session_id"]

    # Persist each stage's docs (worktree-only — written then persisted).
    b0 = eh.record_stage_baseline(repo)
    _commit(repo, "research/r.md", "# research\n", "r")
    eh.persist_session_stage_docs(repo, pid, rsid, "research", "research", repo, b0)
    b1 = eh.record_stage_baseline(repo)
    _commit(repo, "planning/MASTER-PLAN.md", "# mp\n", "mp")
    eh.persist_session_stage_docs(repo, pid, psid, "plan", "planning", repo, b1)
    b2 = eh.record_stage_baseline(repo)
    _write(repo, "build/app.py", "print('hi')\n")
    eh.persist_session_stage_docs(repo, pid, bsid, "build", "build", repo, b2)
    return {"cid": cid, "rsid": rsid, "psid": psid, "bsid": bsid}


def _make_single_session_effort(env):
    """Register ONE v12 single-session effort carrying its own stage_history
    (advanced research→plan in place). Distinct chain_id from the legacy chain."""
    reg, pid = env["reg"], env["pid"]
    rec = reg.register_session(pid, "research", status=reg.STATUS_RUNNING,
                               worktree_path=str(env["repo"]),
                               label="solo", effort_managed=True)
    sid = rec["session_id"]
    # Advance it in place: research → plan (its own stage_history grows).
    reg.set_current_stage(sid, "research", "research", "B0")
    reg.set_current_stage(sid, "plan", "planning", "B1")
    return sid


# ════════════════════════════════════════════════════════════════════════════
# 1) Chain + single-session effort → EXACTLY 2 efforts.
# ════════════════════════════════════════════════════════════════════════════

def test_chain_and_single_effort_yield_exactly_two(env):
    ev, repo, pid = env["ev"], env["repo"], env["pid"]
    chain = _make_chain(env)
    solo_sid = _make_single_session_effort(env)

    efforts = ev.build_effort_view(str(repo), pid)
    assert len(efforts) == 2, [e["effort_id"] for e in efforts]

    by_cid = {e["chain_id"]: e for e in efforts}
    chain_eff = by_cid[chain["cid"]]
    # The chain effort: most-advanced stage == build, 3 stages.
    assert chain_eff["current_stage"] == "build"
    stages = [s["stage"] for s in chain_eff["stage_history"]]
    assert stages == ["research", "plan", "build"]
    # effort_id is the chain ROOT (the research session).
    assert chain_eff["effort_id"] == chain["rsid"]
    # Each stage references its member's docs.
    docs_by_stage = {s["stage"]: {d["rel"] for d in s["docs"]}
                     for s in chain_eff["stage_history"]}
    assert "research/r.md" in docs_by_stage["research"]
    assert "planning/MASTER-PLAN.md" in docs_by_stage["plan"]
    assert "build/app.py" in docs_by_stage["build"]
    # The per-stage doc sets are disjoint (stage-scoped attribution carried through).
    assert docs_by_stage["research"].isdisjoint(docs_by_stage["plan"])
    assert docs_by_stage["plan"].isdisjoint(docs_by_stage["build"])

    # The single-session effort passes through as ITS OWN effort.
    solo_eff = next(e for e in efforts if e["effort_id"] == solo_sid)
    assert solo_eff["chain_id"] == solo_sid
    assert solo_eff["current_stage"] == "plan"
    assert solo_eff["effort_managed"] is True
    assert len(solo_eff["members"]) == 1
    # SAFE projection — never worktree_path/branch.
    for m in solo_eff["members"]:
        assert "worktree_path" not in m
        assert "branch" not in m


# ════════════════════════════════════════════════════════════════════════════
# 2) dedup (Shark SK-6): a chain member also a live record → exactly ONE effort.
# ════════════════════════════════════════════════════════════════════════════

def test_dedup_live_member_renders_once_live_wins(env):
    """A chain whose BUILD member is ALSO a live (RUNNING) record carrying its own
    stage_history. Because grouping is by chain_id, the effort renders exactly
    ONCE — and the live status wins for the effort status."""
    reg, ev, repo, pid = env["reg"], env["ev"], env["repo"], env["pid"]
    # Research + plan DONE, build RUNNING + carrying stage_history.
    r = reg.register_session(pid, "research", status=reg.STATUS_DONE,
                             worktree_path=str(repo), label="research")
    cid = r["chain_id"]
    time.sleep(0.01)
    p = reg.register_session(pid, "planning", status=reg.STATUS_DONE,
                             worktree_path=str(repo), label="plan",
                             parent_session_id=r["session_id"], chain_id=cid)
    time.sleep(0.01)
    b = reg.register_session(pid, "build", status=reg.STATUS_RUNNING,
                             worktree_path=str(repo), label="build",
                             parent_session_id=p["session_id"], chain_id=cid)
    # The build member carries its own stage_history (the migration overlap).
    reg.set_current_stage(b["session_id"], "build", "build", "B2")

    efforts = ev.build_effort_view(str(repo), pid)
    # EXACTLY one effort for that chain_id (len==1 here — only one chain).
    same_chain = [e for e in efforts if e["chain_id"] == cid]
    assert len(same_chain) == 1
    eff = same_chain[0]
    # Live status wins.
    assert eff["live"] is True
    assert eff["status"] == reg.STATUS_RUNNING
    # The build member appears once.
    build_members = [m for m in eff["members"]
                     if m["session_id"] == b["session_id"]]
    assert len(build_members) == 1


# ════════════════════════════════════════════════════════════════════════════
# 3) idempotent: build twice → equal.
# ════════════════════════════════════════════════════════════════════════════

def test_build_effort_view_idempotent(env):
    ev, repo, pid = env["ev"], env["repo"], env["pid"]
    _make_chain(env)
    _make_single_session_effort(env)
    a = ev.build_effort_view(str(repo), pid)
    b = ev.build_effort_view(str(repo), pid)
    assert a == b


# ════════════════════════════════════════════════════════════════════════════
# 4) guard: the Anchor repo is never mutated; the view is read-only.
# ════════════════════════════════════════════════════════════════════════════

def test_view_is_readonly_no_reap_of_live_member(env):
    """A live (RUNNING) member is read, never reaped/mutated by build_effort_view.
    The registry record (status + worktree_path) is unchanged after the build."""
    reg, ev, repo, pid = env["reg"], env["ev"], env["repo"], env["pid"]
    rec = reg.register_session(pid, "research", status=reg.STATUS_RUNNING,
                               worktree_path=str(repo), label="live")
    sid = rec["session_id"]
    before = reg.get_session(sid)
    ev.build_effort_view(str(repo), pid)
    after = reg.get_session(sid)
    assert after["status"] == reg.STATUS_RUNNING
    assert after == before  # no mutation whatsoever


def test_guard_anchor_repo_never_special_cased(env, monkeypatch):
    """Guard like project_move: even when the project folder IS the Anchor repo
    (paths.CODE_DIR pointed at it), build_effort_view still only READS — it never
    mutates the registry or the repo (it performs no writes at all)."""
    import paths
    reg, ev, repo, pid = env["reg"], env["ev"], env["repo"], env["pid"]
    monkeypatch.setattr(paths, "CODE_DIR", Path(repo))
    importlib.reload(importlib.import_module("effort_view"))
    import effort_view as ev2
    rec = reg.register_session(pid, "build", status=reg.STATUS_RUNNING,
                               worktree_path=str(repo), label="b")
    before = reg.load_sessions()
    efforts = ev2.build_effort_view(str(repo), pid)
    after = reg.load_sessions()
    assert before == after  # the registry is untouched
    assert any(e for e in efforts)  # and the view still produced something


# ════════════════════════════════════════════════════════════════════════════
# 5) effort_for_session.
# ════════════════════════════════════════════════════════════════════════════

def test_effort_for_session_resolves_member(env):
    ev, repo, pid = env["ev"], env["repo"], env["pid"]
    chain = _make_chain(env)
    # Any member resolves to the same chain effort.
    e_r = ev.effort_for_session(str(repo), pid, chain["rsid"])
    e_b = ev.effort_for_session(str(repo), pid, chain["bsid"])
    assert e_r is not None and e_b is not None
    assert e_r["chain_id"] == e_b["chain_id"] == chain["cid"]
    # Unknown session → None.
    assert ev.effort_for_session(str(repo), pid, "no-such-sid") is None


# ════════════════════════════════════════════════════════════════════════════
# 6) backfill: a single-session R→P→B effort pins ONLY the build product.
# ════════════════════════════════════════════════════════════════════════════

def test_backfill_pins_build_product_not_master_plan(env):
    """A build-stage product (app.py) resolves + backfills; the plan-stage
    MASTER-PLAN.md decoy is NEVER pinned (W3 stage-filter carried into backfill)."""
    deliv, eh, reg, repo, pid = (env["deliv"], env["eh"], env["reg"],
                                 env["repo"], env["pid"])
    chain = _make_chain(env)
    # Commit the build product so resolve_build_deliverable sees a real signal.
    _git(repo, "add", "--", "build/app.py")
    _git(repo, "commit", "-m", "app")
    deliv.backfill_build_deliverables(str(repo), pid)
    pins = deliv.list_pinned_deliverables(str(repo), pid)
    pinned_rels = {(p.get("artifact_path") or "").replace("\\", "/") for p in pins}
    assert "planning/MASTER-PLAN.md" not in pinned_rels
