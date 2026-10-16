"""v12 Wave 3 — Keystone A: per-stage baseline commit + stage-scoped persist.

The doc-attribution BLOCKER (Risk R1; Shark B1/B2): when research, plan and build
all run in ONE shared worktree, the LEGACY whole-worktree diff
(``_produced_doc_rels`` = ``git diff --name-only HEAD`` ∪ ``git status
--porcelain``) attributes EVERY produced file to EVERY stage. v12 fixes this with
a per-stage **baseline commit** + EXACT git commands measured against that
baseline:

    committed = git diff --name-only <baseline>..HEAD
    working   = git diff --name-only <baseline> --
    untracked = git status --porcelain -uall  (additions)
    produced  = (committed ∪ working ∪ untracked) MINUS prior CLOSED-stage paths

The CRITICAL falsification (Shark B1) is in ``test_plan_persist_is_strict_subset
_of_legacy``: in the SAME worktree state, the legacy whole-tree set is proven to
be a SUPERSET containing BOTH ``r.md`` and ``MASTER-PLAN.md`` — so the
stage-scoped result is a STRICT SUBSET. A "porcelain since baseline" /
``diff HEAD`` persist would FAIL this.

Hermetic + WORKTREE-ONLY: a temp git repo for the worktree, a temp data dir,
``git`` via the module's own ``-C`` seam. No ``eh.record_effort`` pre-persist of
the produced docs — real files are written into the worktree and persisted from
there. Never binds ``:8777``; never touches real data.
"""
import importlib
import subprocess
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
    """Temp data dir + a temp git repo registered as the project (the worktree).

    The whole effort runs in ONE worktree (the repo itself) — exactly the
    shared-worktree case the keystone must attribute per stage."""
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    for mod in ("paths", "rnd_registry", "effort_history", "sessions",
                "report_viewer", "summarizer", "deliverables"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import rnd_registry, effort_history, sessions, deliverables

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    # Keep the throwaway repo hermetic: a host with global commit.gpgsign=true
    # (no key) or a blocking commit hook would otherwise fail this initial commit,
    # leaving the repo with no HEAD -> record_stage_baseline() -> "" -> the
    # baseline assert fails. Disable signing/hooks for this temp-repo commit only.
    _git(repo, "config", "commit.gpgsign", "false")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "--no-verify", "-m", "initial")

    proj = rnd_registry.add_project("Stage", str(repo), scaffold=False)
    return {
        "eh": effort_history, "rnd": rnd_registry, "sessions": sessions,
        "deliv": deliverables, "repo": repo, "pid": proj["id"], "data": data,
    }


def _commit(repo, rel, body, msg):
    p = Path(repo) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    _git(repo, "add", "--", rel)
    _git(repo, "commit", "-m", msg)


def _write(repo, rel, body):
    """Write a file into the worktree WITHOUT committing (a live session leaves
    its produced work uncommitted — the realistic state the keystone attributes)."""
    p = Path(repo) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


# ── (1) plan stage attributes ONLY MASTER-PLAN.md — NOT research's r.md ───────

def test_plan_persist_only_master_plan_strict_subset_of_legacy(env):
    """The headline Wave-3 Given/When/Then + the Shark B1 falsification.

    ONE worktree W: research writes r.md (persisted under baseline B0), then a
    plan baseline B1 is taken and MASTER-PLAN.md is written.
    persist_session_stage_docs('plan', baseline=B1) yields ONLY
    [planning/MASTER-PLAN.md] — because r.md is attributed to the CLOSED research
    stage and subtracted. The legacy whole-tree set, computed in the SAME state,
    is a SUPERSET containing BOTH files (both are uncommitted/working-tree) —
    proving the stage-scoped result is a STRICT SUBSET. A ``diff HEAD`` /
    "porcelain since baseline" persist (no prior-stage subtraction) would wrongly
    return BOTH and FAIL."""
    eh, repo, pid = env["eh"], env["repo"], env["pid"]
    sid = "EFFORT-1"

    # Research stage baseline B0 (== current HEAD: just the initial commit), then
    # write r.md (uncommitted, as a live session leaves it) and persist research.
    b0 = eh.record_stage_baseline(repo)
    _write(repo, "research/r.md", "# research findings\n")
    res_r = eh.persist_session_stage_docs(repo, pid, sid, "research",
                                          "research", repo, b0)
    assert res_r["ok"] is True
    assert res_r["persisted"] == ["research/r.md"]

    # Plan stage baseline B1 == HEAD, then write the master plan (uncommitted).
    b1 = eh.record_stage_baseline(repo)
    _write(repo, "planning/MASTER-PLAN.md", "# master plan\n")

    # ── CRITICAL FALSIFICATION (Shark B1) — must be in the test body ──────────
    # In THIS state (research r.md persisted; MASTER-PLAN.md present), the LEGACY
    # whole-tree set is a SUPERSET of BOTH files: r.md is a working-tree change vs
    # HEAD (the research persist re-copied it, and it differs from the committed
    # state when dirty) OR an untracked add, and MASTER-PLAN.md is untracked. The
    # legacy ``git diff --name-only HEAD`` ∪ ``git status --porcelain`` therefore
    # returns BOTH. We assert the superset BEFORE the plan persist commits, so the
    # state is exactly "both files in the worktree" — the doc-attribution bug's
    # blast radius. A persist measuring this whole-tree set (no prior-stage
    # subtraction) would wrongly grab r.md for the plan stage.
    # To make r.md visible to the legacy whole-tree diff regardless of whether the
    # research persist committed it, touch it so it is a working-tree change.
    _write(repo, "research/r.md", "# research findings (dirty)\n")
    legacy = set(eh._produced_doc_rels(repo))
    assert "research/r.md" in legacy
    assert "planning/MASTER-PLAN.md" in legacy

    res_p = eh.persist_session_stage_docs(repo, pid, sid, "plan", "planning",
                                          repo, b1)
    assert res_p["ok"] is True
    # EXACTLY the plan doc — research/r.md is a CLOSED prior stage → subtracted.
    assert res_p["persisted"] == ["planning/MASTER-PLAN.md"]

    # efforts_for_session_stage recovers each stage's docs; they are DISJOINT.
    research_docs = {e["artifact_path"]
                     for e in eh.efforts_for_session_stage(repo, pid, sid,
                                                            "research")}
    plan_docs = {e["artifact_path"]
                 for e in eh.efforts_for_session_stage(repo, pid, sid, "plan")}
    assert research_docs == {"research/r.md"}
    assert plan_docs == {"planning/MASTER-PLAN.md"}
    assert research_docs.isdisjoint(plan_docs)

    # strict subset: the plan result is contained in, and smaller than, legacy.
    assert plan_docs < legacy


# ── (2) build stage: an UNCOMMITTED product after baseline B2 ────────────────

def test_build_persist_only_uncommitted_product(env):
    """Same W: B2=HEAD (after research+plan committed); write build/app.py
    UNCOMMITTED. persist_session_stage_docs('build', baseline=B2) == [build/app.py];
    MASTER-PLAN.md excluded (it predates B2 and is clean)."""
    eh, repo, pid = env["eh"], env["repo"], env["pid"]
    sid = "EFFORT-1"

    # Drive research + plan exactly as above so the prior-stage exclusion is real.
    b0 = eh.record_stage_baseline(repo)
    _commit(repo, "research/r.md", "# research\n", "r")
    eh.persist_session_stage_docs(repo, pid, sid, "research", "research", repo, b0)
    b1 = eh.record_stage_baseline(repo)
    _commit(repo, "planning/MASTER-PLAN.md", "# mp\n", "mp")
    eh.persist_session_stage_docs(repo, pid, sid, "plan", "planning", repo, b1)

    # Build baseline B2 == HEAD; write the build product UNCOMMITTED.
    b2 = eh.record_stage_baseline(repo)
    (repo / "build").mkdir(parents=True, exist_ok=True)
    (repo / "build" / "app.py").write_text("print('hi')\n", encoding="utf-8")

    res_b = eh.persist_session_stage_docs(repo, pid, sid, "build", "build",
                                          repo, b2)
    assert res_b["ok"] is True
    assert res_b["persisted"] == ["build/app.py"]
    # MASTER-PLAN.md is clean + predates B2 → excluded from the build stage.
    assert "planning/MASTER-PLAN.md" not in res_b["persisted"]

    build_docs = {e["artifact_path"]
                  for e in eh.efforts_for_session_stage(repo, pid, sid, "build")}
    assert build_docs == {"build/app.py"}


# ── (3) idempotent re-persist ────────────────────────────────────────────────

def test_idempotent_re_persist(env):
    """Re-persisting the same stage with byte-identical docs copies nothing new
    and never duplicates the effort (content-addressed id)."""
    eh, repo, pid = env["eh"], env["repo"], env["pid"]
    sid = "EFFORT-1"
    b1 = eh.record_stage_baseline(repo)
    _commit(repo, "planning/MASTER-PLAN.md", "# mp\n", "mp")

    r1 = eh.persist_session_stage_docs(repo, pid, sid, "plan", "planning",
                                       repo, b1)
    assert r1["persisted"] == ["planning/MASTER-PLAN.md"]
    # second call: same content → no new effort, same set.
    r2 = eh.persist_session_stage_docs(repo, pid, sid, "plan", "planning",
                                       repo, b1)
    assert r2["ok"] is True
    assert r2["persisted"] == ["planning/MASTER-PLAN.md"]
    # exactly ONE plan-stage effort recovered (no duplicate).
    plan_efforts = eh.efforts_for_session_stage(repo, pid, sid, "plan")
    assert len(plan_efforts) == 1
    # the second commit is a no-op (no staged changes).
    assert r2["committed"] is False or r2["reason"] in ("no-staged-changes", "ok")


# ── (4) record_stage_baseline degrades gracefully ────────────────────────────

def test_baseline_best_effort(env, tmp_path):
    eh = env["eh"]
    # non-repo dir → ""
    nonrepo = tmp_path / "plain"
    nonrepo.mkdir()
    assert eh.record_stage_baseline(str(nonrepo)) == ""
    # missing path → ""
    assert eh.record_stage_baseline(str(tmp_path / "nope")) == ""
    # a real repo → a non-empty sha.
    ref = eh.record_stage_baseline(env["repo"])
    assert ref and len(ref) >= 7


# ── (5) legacy persist_session_docs behavior is UNCHANGED ────────────────────

def test_legacy_persist_session_docs_unchanged(env):
    """The legacy whole-tree persist still grabs ALL produced docs in the worktree
    (its documented behavior — whole-tree diff, no stage scoping) — proving Wave 3
    did not regress the non-effort path."""
    eh, repo, pid = env["eh"], env["repo"], env["pid"]
    # Uncommitted produced docs (the live-session state the legacy path sees).
    _write(repo, "research/r.md", "# r\n")
    _write(repo, "planning/MASTER-PLAN.md", "# mp\n")
    res = eh.persist_session_docs(repo, pid, "planning", "LEGACY-SID", repo)
    assert res["ok"] is True
    # legacy = whole-tree → BOTH docs persisted (superset behavior, unchanged).
    assert set(res["persisted"]) == {"research/r.md", "planning/MASTER-PLAN.md"}


# ── build-accept fix: root product captured (W3-R2) / junk + bundle dropped (W3-R1) ──

def test_build_accept_predicate_root_and_junk():
    import importlib
    eh = importlib.import_module("effort_history")
    # root-level product (anchor_gui.py = the canonical Anchor deliverable) accepted
    assert eh._is_stage_artifact_rel("anchor_gui.py", "build") is True
    assert eh._is_stage_artifact_rel("build/app.py", "build") is True
    # build intermediates / junk are NEVER swept+committed into the main repo
    for junk in ("build/foo.pyc", "dist/app/python311.dll", "build/x.so",
                 "build/.coverage", "out/cache/tmp.lock", "bin/run.log"):
        assert eh._is_stage_artifact_rel(junk, "build") is False, junk
    # research/plan stay doc-only (a root .py is NOT a research artifact)
    assert eh._is_stage_artifact_rel("anchor_gui.py", "research") is False
    assert eh._is_stage_artifact_rel("report.md", "research") is True


def test_build_stage_captures_root_product(env):
    eh = env["eh"]; repo = env["repo"]
    base = eh.record_stage_baseline(str(repo))
    _write(repo, "anchor_gui.py", "print('the deliverable')\n")
    produced = eh._stage_produced_rels(str(repo), base, "build")
    assert "anchor_gui.py" in produced  # W3-R2: root product captured


def test_build_stage_bundle_sweep_capped(env):
    eh = env["eh"]; repo = env["repo"]
    base = eh.record_stage_baseline(str(repo))
    _write(repo, "build/REPORT.md", "the deliverable doc\n")
    for i in range(eh._MAX_BUILD_PRODUCTS + 5):  # > cap → an artifact tree
        _write(repo, f"dist/bundle/asset_{i}.bin", "x")
    produced = eh._stage_produced_rels(str(repo), base, "build")
    assert "build/REPORT.md" in produced                      # docs kept
    assert not any(p.endswith(".bin") for p in produced)      # bundle dropped (cap)
