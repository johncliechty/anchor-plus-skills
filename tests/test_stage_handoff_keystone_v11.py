"""v11 Wave 1 — The shared stage-handoff keystone + the live-flow truth test.

THE BUG v11 fixes: ``advance_session`` (research→plan) never persisted the LIVE
source research session's produced docs. Persistence
(``effort_history.persist_session_docs`` via ``terminal_session.capture_session_docs``)
ran ONLY in ``terminal_session.kill`` and in ``finish_to_build`` (plan→build). So
advancing a still-LIVE research session left its reports in the worktree,
unpersisted → ``research_set_for_session`` (reads only session-tagged persisted
efforts) returned None → ``handoff.build_next_stage_prompt`` fell to the bare
fallback with no doc paths, and no HANDOFF.md was written.

``terminal_session.prepare_stage_handoff`` is the ONE shared keystone that fixes
this: it PERSISTS the source stage's docs FIRST (best-effort, idempotent, does
NOT reap the worktree — works whether the source is live or done), THEN builds
the real handoff prompt, resolves the materials (doc_rels + skill + summary), and
kicks off a non-blocking background summary.

THE v11 LESSON (non-negotiable, see IMPLEMENTATION-PLAN.md Conventions): these
tests are WORKTREE-ONLY. We start a LIVE session, write produced docs into the
session's WORKTREE ONLY (NO ``eh.record_effort`` pre-persist, NO ``kill``), then
call ``prepare_stage_handoff``, then assert the docs were PERSISTED into the
project AND referenced in the prompt. A test that pre-persists the effort (the
masking pattern in ``test_advance_artifacts_v10.py``) is prompt-building coverage,
NOT live-flow coverage. The truth test below FAILS against the pre-fix code
(``prepare_stage_handoff`` did not exist; with the ``capture_session_docs`` call
commented out it falls to the bare prompt — verified non-vacuous).

Hermetic: NO real claude/gemini, NO real PTY — ``ANCHOR_PTY_BACKEND=stub``, a
temp git repo for the worktree, a tmp data dir + tmp worktree base. NEVER binds
``:8777``; NEVER a worktree off the real repo; NEVER real push/gh/network.
"""
import importlib
import subprocess
import re
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


pytestmark = pytest.mark.skipif(not _have_git(), reason="git not on PATH")


# ── env / fixtures (stub PTY + temp git repo + project) ──────────────────────

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

    for mod in ("paths", "job_runner", "pty_manager", "rnd_registry",
                "effort_history", "sessions", "anchor_marker",
                "session_registry", "worktrees", "lanes", "summarizer",
                "handoff", "terminal_session"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()

    import effort_history
    import handoff
    import terminal_session
    import session_registry
    import rnd_registry

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
        "ts": terminal_session, "reg": session_registry, "handoff": handoff,
        "eh": effort_history, "rnd": rnd_registry, "repo": repo,
        "pid": proj["id"], "wbase": wbase, "data": data,
    }
    yield bundle
    try:
        import pty_manager
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


def _write_in_worktree(worktree_path, rel, body="# Report\n## Findings\nOK.\n"):
    """Write a produced doc into the session's WORKTREE ONLY (no record_effort)."""
    wt = Path(worktree_path)
    p = wt / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return rel


def _committed_in_repo(repo, rel):
    """True iff ``rel`` is tracked/committed in the repo at HEAD."""
    r = _git(repo, "ls-files", "--error-unmatch", rel)
    return r.returncode == 0


# ════════════════════════════════════════════════════════════════════════════
# (a) THE TRUTH TEST — a LIVE research session, docs in WORKTREE ONLY
#     This MUST fail pre-fix (no persist → bare prompt, no doc in main folder).
# ════════════════════════════════════════════════════════════════════════════

def test_prepare_persists_worktree_docs_and_builds_real_prompt(env):
    """Given a LIVE research session that wrote research/run-1/REPORT.md into its
    WORKTREE ONLY (no record_effort, no kill), When prepare_stage_handoff(pid,
    rsid, 'planning') runs, Then:
      (i)   research/run-1/REPORT.md is now a FILE in the MAIN project AND
            committed AND recorded as a research effort tagged with rsid;
      (ii)  the returned prompt CONTAINS research/run-1/REPORT.md + a "read these"
            instruction + names Crucible;
      (iii) doc_rels contains the real path;
      (iv)  persisted includes it.

    NON-VACUITY: pre-fix (or with the capture_session_docs call commented out
    inside prepare_stage_handoff) the docs are NEVER persisted →
    research_set_for_session returns None → build_next_stage_prompt falls to the
    bare "...plan from the upstream research session's findings... see HANDOFF.md"
    fallback WITHOUT the real path, efforts_for_session_id is empty, and the file
    never reaches the main folder. Verified by temporarily commenting out the
    persist step and confirming this test FAILS, then restoring it.
    """
    ts, repo, pid, eh = env["ts"], env["repo"], env["pid"], env["eh"]

    rsess = ts.start_session(pid, "research", backend="claude")
    rsid = rsess["session_id"]
    rel = _write_in_worktree(rsess["worktree_path"], "research/run-1/REPORT.md")

    # Pre-condition (proves the live flow): the doc lives ONLY in the worktree,
    # NOT in the main folder, NOT recorded as an effort.
    assert not (repo / rel).is_file(), "pre-condition: doc must NOT be in main yet"
    store_lane = eh._resolve_subdir("research")
    assert eh.efforts_for_session_id(repo, pid, store_lane, rsid) == [], \
        "pre-condition: no research effort tagged with rsid yet"

    out = ts.prepare_stage_handoff(pid, rsid, "planning")

    # (i) persisted + committed into the MAIN project + recorded as a research
    #     effort tagged with rsid.
    assert out["ok"] is True
    assert (repo / rel).is_file(), "REPORT.md was not persisted into the main project"
    assert _committed_in_repo(repo, rel), "REPORT.md was not committed to the repo"
    tagged = eh.efforts_for_session_id(repo, pid, store_lane, rsid)
    tagged_rels = [(e.get("artifact_path") or "").replace("\\", "/")
                   for e in tagged]
    assert rel in tagged_rels, f"no research effort tagged with rsid: {tagged_rels}"

    # (ii) the real prompt names the path + read-first + Crucible (NOT the bare
    #      fallback).
    prompt = out["prompt"]
    assert rel in prompt, f"prompt missing the real report path: {prompt!r}"
    assert re.search(r"[Rr]ead these", prompt), f"no read-first in prompt: {prompt!r}"
    assert "Crucible" in prompt
    assert "Foreman" not in prompt

    # (iii) + (iv)
    assert rel in out["doc_rels"], out["doc_rels"]
    assert rel in out["persisted"], out["persisted"]
    assert out["skill"] == "Crucible"


def test_prepare_persists_multiple_worktree_docs(env):
    """Two produced docs in the worktree only → both persisted + at least the
    report named in the prompt + both in doc_rels."""
    ts, repo, pid, eh = env["ts"], env["repo"], env["pid"], env["eh"]

    rsess = ts.start_session(pid, "research", backend="claude")
    rsid = rsess["session_id"]
    rel1 = _write_in_worktree(rsess["worktree_path"], "research/run-1/REPORT.md")
    rel2 = _write_in_worktree(rsess["worktree_path"],
                              "research/run-1/EXEC-SUMMARY.md",
                              body="# Exec\nSummary.\n")

    out = ts.prepare_stage_handoff(pid, rsid, "planning")
    assert out["ok"] is True
    assert (repo / rel1).is_file() and (repo / rel2).is_file()
    assert rel1 in out["persisted"] and rel2 in out["persisted"]
    assert rel1 in out["doc_rels"] and rel2 in out["doc_rels"]
    assert "Crucible" in out["prompt"]


# ════════════════════════════════════════════════════════════════════════════
# (b) HONEST EMPTY — no produced docs → honest minimal prompt, no fabrication
# ════════════════════════════════════════════════════════════════════════════

def test_prepare_no_docs_is_honest_minimal(env):
    """A source session with genuinely NO produced docs → the prompt is the honest
    minimal one (no fabricated .md paths), persisted == [], doc_rels == [], no
    crash."""
    ts, repo, pid = env["ts"], env["repo"], env["pid"]

    rsess = ts.start_session(pid, "research", backend="claude")
    rsid = rsess["session_id"]
    # Write NOTHING into the worktree.

    out = ts.prepare_stage_handoff(pid, rsid, "planning")
    assert out["ok"] is True
    assert out["persisted"] == []
    assert out["doc_rels"] == []
    # Honest minimal: names Crucible, references HANDOFF.md, fabricates NO path.
    prompt = out["prompt"]
    assert "Crucible" in prompt
    assert not re.search(r"\S+\.md", prompt) or "HANDOFF.md" in prompt
    # No fabricated research/.../REPORT.md style path.
    assert not re.search(r"research/\S+\.md", prompt), \
        f"fabricated research doc path in honest-empty prompt: {prompt!r}"


def test_prepare_unknown_session_is_clean(env):
    """An unknown source session id → ok False, empty fields, no crash."""
    ts, pid = env["ts"], env["pid"]
    out = ts.prepare_stage_handoff(pid, "does-not-exist", "planning")
    assert out["ok"] is False
    assert out["persisted"] == [] and out["doc_rels"] == []


# ════════════════════════════════════════════════════════════════════════════
# (c) IDEMPOTENT — calling twice does not duplicate efforts; same real prompt
# ════════════════════════════════════════════════════════════════════════════

def test_prepare_is_idempotent(env):
    """prepare_stage_handoff called twice → persistence is idempotent (no dup
    efforts, byte-identical skip) and the second call returns the same real
    prompt."""
    ts, repo, pid, eh = env["ts"], env["repo"], env["pid"], env["eh"]

    rsess = ts.start_session(pid, "research", backend="claude")
    rsid = rsess["session_id"]
    rel = _write_in_worktree(rsess["worktree_path"], "research/run-1/REPORT.md")

    out1 = ts.prepare_stage_handoff(pid, rsid, "planning")
    store_lane = eh._resolve_subdir("research")
    n1 = len(eh.efforts_for_session_id(repo, pid, store_lane, rsid))
    assert n1 >= 1

    out2 = ts.prepare_stage_handoff(pid, rsid, "planning")
    n2 = len(eh.efforts_for_session_id(repo, pid, store_lane, rsid))

    assert n2 == n1, f"duplicate efforts on second prepare: {n1} -> {n2}"
    assert out2["prompt"] == out1["prompt"]
    assert rel in out2["prompt"]
    assert out2["doc_rels"] == out1["doc_rels"]


# ════════════════════════════════════════════════════════════════════════════
# (d) write_handoff_md — real paths + read-first + skill + optional summary
# ════════════════════════════════════════════════════════════════════════════

def test_write_handoff_md_lists_paths_skill_and_summary(env, tmp_path):
    """Given doc_rels + skill + summary, write_handoff_md writes a HANDOFF.md in
    the worktree containing the real paths + a "read these" instruction + the
    skill name + an Upstream summary section."""
    ho = env["handoff"]
    wt = tmp_path / "wt"
    wt.mkdir()

    res = ho.write_handoff_md(
        str(wt), ["research/run-1/REPORT.md", "research/run-1/EXEC.md"],
        "Crucible", "The cooling design is adequate.")
    assert res["ok"] is True
    text = (wt / ho.HANDOFF_FILENAME).read_text(encoding="utf-8")
    assert "research/run-1/REPORT.md" in text
    assert "research/run-1/EXEC.md" in text
    assert "Crucible" in text
    assert re.search(r"[Rr]ead these", text)
    assert "Upstream summary" in text
    assert "cooling design is adequate" in text


def test_write_handoff_md_honest_when_no_summary(env, tmp_path):
    """No summary → no Upstream summary section, but still lists the docs + skill."""
    ho = env["handoff"]
    wt = tmp_path / "wt"
    wt.mkdir()
    res = ho.write_handoff_md(str(wt), ["planning/x/IMPLEMENTATION-PLAN.md"],
                             "Foreman", "")
    assert res["ok"] is True
    text = (wt / ho.HANDOFF_FILENAME).read_text(encoding="utf-8")
    assert "planning/x/IMPLEMENTATION-PLAN.md" in text
    assert "Foreman" in text
    assert "Upstream summary" not in text


def test_write_handoff_md_honest_when_no_docs(env, tmp_path):
    """No doc_rels → honest "no upstream documents" note, no fabricated path, no
    crash."""
    ho = env["handoff"]
    wt = tmp_path / "wt"
    wt.mkdir()
    res = ho.write_handoff_md(str(wt), [], "Crucible", "")
    assert res["ok"] is True
    text = (wt / ho.HANDOFF_FILENAME).read_text(encoding="utf-8")
    assert "Crucible" in text
    assert not re.search(r"\S+\.md", text.replace("HANDOFF.md", "")), \
        f"fabricated doc path with empty doc_rels: {text!r}"


def test_write_handoff_md_missing_worktree(env):
    """A missing worktree path → ok False, reason, no crash."""
    ho = env["handoff"]
    res = ho.write_handoff_md("/no/such/worktree/path", ["a.md"], "Crucible", "")
    assert res["ok"] is False
    assert res.get("reason")


# ════════════════════════════════════════════════════════════════════════════
# (e) PERSIST-FAILURE BEST-EFFORT — a throwing persist never propagates
# ════════════════════════════════════════════════════════════════════════════

def test_prepare_persist_failure_is_swallowed(env, monkeypatch):
    """If capture_session_docs raises, prepare_stage_handoff still returns
    (degraded, honest minimal prompt) and NEVER propagates the exception."""
    ts, pid = env["ts"], env["pid"]

    rsess = ts.start_session(pid, "research", backend="claude")
    rsid = rsess["session_id"]
    _write_in_worktree(rsess["worktree_path"], "research/run-1/REPORT.md")

    def _boom(*a, **k):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(ts, "capture_session_docs", _boom)

    # Must NOT raise.
    out = ts.prepare_stage_handoff(pid, rsid, "planning")
    # Source resolved, so ok stays True; persistence failed → degrade honestly.
    assert out["ok"] is True
    assert out["persisted"] == []
    # The prompt falls to the honest minimal one (no real path persisted/found).
    assert "Crucible" in out["prompt"]


# ════════════════════════════════════════════════════════════════════════════
# (f) BACKGROUND SUMMARY IS GATED (Reviewer-A hardening)
#     The background source-stage summary must be a NO-OP when proactive summary
#     is DISABLED (the default in every test/healthcheck env), and the function
#     must NEVER mutate the process-global runner env.
# ════════════════════════════════════════════════════════════════════════════

def test_background_summary_gated_off_does_not_summarize(env, monkeypatch):
    """With proactive summary DISABLED (the default test env), prepare_stage_handoff
    must NOT spawn a background summarizer run: the gate hard no-ops, so no daemon
    thread starts and summarize_session is never invoked. The keystone still
    persists docs + builds the real prompt (unchanged)."""
    import os
    import summarizer as _sm
    ts, repo, pid, eh = env["ts"], env["repo"], env["pid"], env["eh"]

    # Default test env leaves proactive summary OFF; assert that explicitly.
    monkeypatch.delenv("ANCHOR_PROACTIVE_SUMMARY", raising=False)
    assert os.environ.get("ANCHOR_PROACTIVE_SUMMARY", "") == ""

    # Tripwire: if the gate ever lets a summary through, this records it.
    calls = []
    real = _sm.summarize_session
    monkeypatch.setattr(_sm, "summarize_session",
                        lambda *a, **k: calls.append(1) or real(*a, **k))

    rsess = ts.start_session(pid, "research", backend="claude")
    rsid = rsess["session_id"]
    rel = _write_in_worktree(rsess["worktree_path"], "research/run-1/REPORT.md")

    out = ts.prepare_stage_handoff(pid, rsid, "planning")

    # Keystone behavior is UNCHANGED by the gate: docs persisted + real prompt.
    assert out["ok"] is True
    assert (repo / rel).is_file()
    assert rel in out["prompt"]

    # The gate no-ops: no background summary ran, so nothing was cached.
    store_lane = eh._resolve_subdir("research")
    assert _sm.load_cached(repo, pid, store_lane, rsid) is None, \
        "gate failed: a session summary was generated/cached while proactive OFF"
    assert calls == [], "gate failed: summarize_session was invoked while proactive OFF"


def test_prepare_does_not_mutate_runner_env(env):
    """prepare_stage_handoff must NOT mutate the process-global ANCHOR_RUNNER_CMD
    (the old daemon-thread os.environ write was removed)."""
    import os
    ts, pid = env["ts"], env["pid"]

    before = os.environ.get("ANCHOR_RUNNER_CMD")
    rsess = ts.start_session(pid, "research", backend="claude")
    rsid = rsess["session_id"]
    _write_in_worktree(rsess["worktree_path"], "research/run-1/REPORT.md")

    ts.prepare_stage_handoff(pid, rsid, "planning")

    assert os.environ.get("ANCHOR_RUNNER_CMD") == before, \
        "prepare_stage_handoff mutated the global ANCHOR_RUNNER_CMD"
