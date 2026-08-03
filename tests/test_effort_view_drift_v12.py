"""v12 Wave 9 — effort view-layer drift safety: deleting a member drops its stage.

Covers the Wave-9 drift Given/When/Then EXACTLY:

  - Given the chain's plan member is deleted from the registry, When the view is
    rebuilt, Then that effort shows research + build only (NO ghost plan stage),
    no crash.

The view is a DERIVED CACHE rebuilt from the registry on EVERY call, so a member
that no longer exists in the registry simply DROPS — there is no stored stage to
go stale. Hermetic (temp data + temp git repo); never binds ``:8777``.
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
    import rnd_registry, effort_history, session_registry, effort_view

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
        "repo": repo, "pid": proj["id"],
    }


def _commit(repo, rel, body, msg):
    p = Path(repo) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    _git(repo, "add", "--", rel)
    _git(repo, "commit", "-m", msg)


def _make_chain(env):
    reg, eh, repo, pid = env["reg"], env["eh"], env["repo"], env["pid"]
    r = reg.register_session(pid, "research", status=reg.STATUS_DONE,
                             worktree_path=str(repo), label="research")
    cid = r["chain_id"]
    time.sleep(0.01)
    p = reg.register_session(pid, "planning", status=reg.STATUS_DONE,
                             worktree_path=str(repo), label="plan",
                             parent_session_id=r["session_id"], chain_id=cid)
    time.sleep(0.01)
    b = reg.register_session(pid, "build", status=reg.STATUS_DONE,
                             worktree_path=str(repo), label="build",
                             parent_session_id=p["session_id"], chain_id=cid)

    b0 = eh.record_stage_baseline(repo)
    _commit(repo, "research/r.md", "# research\n", "r")
    eh.persist_session_stage_docs(repo, pid, r["session_id"], "research",
                                  "research", repo, b0)
    b1 = eh.record_stage_baseline(repo)
    _commit(repo, "planning/MASTER-PLAN.md", "# mp\n", "mp")
    eh.persist_session_stage_docs(repo, pid, p["session_id"], "plan",
                                  "planning", repo, b1)
    b2 = eh.record_stage_baseline(repo)
    _commit(repo, "build/app.py", "print('hi')\n", "app")
    eh.persist_session_stage_docs(repo, pid, b["session_id"], "build",
                                  "build", repo, b2)
    return {"cid": cid, "rsid": r["session_id"], "psid": p["session_id"],
            "bsid": b["session_id"]}


def test_deleting_plan_member_drops_only_that_stage_no_ghost(env):
    """Delete the plan member from the registry → the effort shows research+build
    only (no ghost plan stage), no crash."""
    reg, ev, repo, pid = env["reg"], env["ev"], env["repo"], env["pid"]
    chain = _make_chain(env)

    # Sanity: 3 stages before the delete.
    before = ev.build_effort_view(str(repo), pid)
    eff_before = next(e for e in before if e["chain_id"] == chain["cid"])
    assert [s["stage"] for s in eff_before["stage_history"]] == \
        ["research", "plan", "build"]

    # Delete the PLAN member from the registry.
    assert reg.remove_session(chain["psid"]) is True

    # Rebuild from the (now drifted) registry — plan stage simply drops.
    after = ev.build_effort_view(str(repo), pid)
    eff_after = next(e for e in after if e["chain_id"] == chain["cid"])
    stages = [s["stage"] for s in eff_after["stage_history"]]
    assert stages == ["research", "build"]
    assert "plan" not in stages  # NO ghost stage
    # The effort is still coherent (members reduced to 2; build still resolves).
    assert {m["session_id"] for m in eff_after["members"]} == \
        {chain["rsid"], chain["bsid"]}
    assert eff_after["current_stage"] == "build"


def test_deleting_all_members_drops_the_effort(env):
    """Deleting every member of a chain drops the whole effort (no ghost effort)."""
    reg, ev, repo, pid = env["reg"], env["ev"], env["repo"], env["pid"]
    chain = _make_chain(env)
    for sid in (chain["rsid"], chain["psid"], chain["bsid"]):
        reg.remove_session(sid)
    efforts = ev.build_effort_view(str(repo), pid)
    assert [e for e in efforts if e["chain_id"] == chain["cid"]] == []


def test_empty_project_no_crash(env):
    """A project with zero registry records → empty view, no crash."""
    ev, repo, pid = env["ev"], env["repo"], env["pid"]
    assert ev.build_effort_view(str(repo), pid) == []
