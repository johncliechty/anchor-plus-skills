"""v11.1 Wave 1 — CONVERSATION-only transcript snapshot keystone (the core fix).

THE BUG v11.1 fixes: a research session whose work lived ONLY as a terminal
CONVERSATION (the model answered in the PTY, wrote NO file) produced no
document-classified doc → the keystone's ``doc_rels`` was empty → grass hard-
refused and the non-grass advance opened with a MISLEADING prompt. The
conversation was never captured → research lost.

``terminal_session.prepare_stage_handoff`` now, when the initial persist yields
ZERO docs (D4 — only the gap case), SYNCHRONOUSLY snapshots the source session's
PTY transcript into ``<lane>/<short-sid>-transcript.md`` (cleaned of the
seed/greet boilerplate + ANSI control sequences, capped to the tail), re-persists
it (session-tagged), and THEN builds the real doc-referencing prompt.

THE v11 LESSON, HARDENED (see IMPLEMENTATION-PLAN.md Conventions): these tests
are CONVERSATION-ONLY. We start a LIVE session and write NOTHING to its worktree;
instead we seed the STUB PTY read buffer with simulated transcript content (a
``pty_manager.write`` ECHOES into the readable buffer — no file, no record_effort,
no kill), then call ``prepare_stage_handoff``, then assert the transcript was
SNAPSHOTTED + persisted + named in the prompt. A pre-written-file test is
prompt-building coverage, NOT conversation-only coverage.

NON-VACUITY: the truth test below FAILS against the pre-fix code (no snapshot →
``doc_rels=[]`` → the misleading minimal prompt; no transcript in the main
folder). Verified by temporarily disabling the snapshot block and confirming the
test goes RED, then restoring it.

Hermetic: NO real claude/gemini, NO real PTY — ``ANCHOR_PTY_BACKEND=stub``, a
temp git repo for the worktree, tmp data + tmp worktree base,
``ANCHOR_PROACTIVE_SUMMARY`` OFF. NEVER binds ``:8777`` / touches real data /
network.
"""
import importlib
import re
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


pytestmark = pytest.mark.skipif(not _have_git(), reason="git not on PATH")


# A chunk of simulated research "conversation" — plausibly named entities so the
# snapshot text is non-trivial. NO file is written; this goes onto the PTY buffer.
TRANSCRIPT = (
    "\nResearcher: What is the best cooling approach for the reactor?\n"
    "Assistant: I evaluated three coolant loops. The molten-salt loop has the\n"
    "highest thermal margin and the simplest pump topology. Key finding: the\n"
    "salt loop tolerates a 40C transient without scram. Recommendation: pursue\n"
    "the molten-salt design and prototype the pump seal.\n"
)


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
    monkeypatch.delenv("ANCHOR_PROACTIVE_SUMMARY", raising=False)

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
        "ts": terminal_session, "reg": session_registry, "handoff": handoff,
        "eh": effort_history, "rnd": rnd_registry, "repo": repo,
        "pty": pty_manager, "pid": proj["id"], "wbase": wbase, "data": data,
    }
    yield bundle
    try:
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


def _seed_transcript(pty, sid, text=TRANSCRIPT):
    """Put simulated transcript content in the SOURCE session's read buffer.

    The stub PTY ECHOES a write into its readable output buffer, so writing here
    makes ``read_since(sid, 0)`` return this content AFTER the start seed — WITHOUT
    writing any file to the worktree (the exact conversation-only live path)."""
    pty.write(sid, text)


def _committed_in_repo(repo, rel):
    return _git(repo, "ls-files", "--error-unmatch", rel).returncode == 0


def _write_in_worktree(worktree_path, rel, body="# Report\n## Findings\nOK.\n"):
    """Write a produced doc into the session's WORKTREE ONLY (no record_effort)."""
    wt = Path(worktree_path)
    p = wt / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return rel


# ════════════════════════════════════════════════════════════════════════════
# (a) THE TRUTH TEST — a CONVERSATION-only research session (transcript in the
#     PTY buffer, NO file). MUST FAIL pre-fix (no snapshot → doc_rels=[] →
#     misleading minimal prompt; no transcript in main).
# ════════════════════════════════════════════════════════════════════════════

def test_conversation_only_research_is_snapshotted_and_primes_planning(env):
    """Given a LIVE research session whose work is ONLY a conversation in the PTY
    buffer (no file written), When prepare_stage_handoff(pid, rsid, 'planning')
    runs, Then:
      (i)   research/<short-sid>-transcript.md is a FILE in the MAIN project +
            committed + recorded as a research effort tagged with rsid;
      (ii)  out["prompt"] NAMES research/<short-sid>-transcript.md AND instructs
            to CREATE / plan the materials (Crucible, not Foreman);
      (iii) out["doc_rels"] contains the transcript path;
      (iv)  out["persisted"] is non-empty.
    """
    ts, repo, pid, eh, pty = (env["ts"], env["repo"], env["pid"], env["eh"],
                              env["pty"])

    rsess = ts.start_session(pid, "research", backend="claude")
    rsid = rsess["session_id"]
    # CONVERSATION ONLY: seed the PTY read buffer; write NO file to the worktree.
    _seed_transcript(pty, rsid)

    # Pre-condition (proves the live conversation-only flow): nothing in the
    # worktree, nothing in main, no effort yet.
    store_lane = eh._resolve_subdir("research")
    assert eh.efforts_for_session_id(repo, pid, store_lane, rsid) == []

    out = ts.prepare_stage_handoff(pid, rsid, "planning")

    short_sid = rsid[:12]
    rel = f"research/{short_sid}-transcript.md"

    # (i) snapshotted + persisted + committed into MAIN + tagged with rsid.
    assert out["ok"] is True
    assert (repo / rel).is_file(), "transcript was not snapshotted into the main project"
    assert _committed_in_repo(repo, rel), "transcript was not committed to the repo"
    body = (repo / rel).read_text(encoding="utf-8")
    assert "molten-salt" in body, "transcript content was lost in the snapshot"
    assert "transcript" in body.lower(), "snapshot lacks an honest transcript header"
    tagged = [(e.get("artifact_path") or "").replace("\\", "/")
              for e in eh.efforts_for_session_id(repo, pid, store_lane, rsid)]
    assert rel in tagged, f"no research effort tagged with rsid: {tagged}"

    # (ii) the prompt names the REAL transcript path + Crucible (NOT Foreman),
    #      and is the real doc-referencing prompt (read-first).
    prompt = out["prompt"]
    assert rel in prompt, f"prompt missing the transcript path: {prompt!r}"
    assert "Crucible" in prompt
    assert "Foreman" not in prompt
    assert re.search(r"[Rr]ead these|[Cc]reate", prompt), \
        f"prompt is not actionable: {prompt!r}"

    # (iii) + (iv)
    assert rel in out["doc_rels"], out["doc_rels"]
    assert rel in out["persisted"], out["persisted"]
    assert out["skill"] == "Crucible"

    #
    # NON-VACUITY: pre-fix (snapshot block disabled inside prepare_stage_handoff),
    # the conversation is NEVER captured → persisted/doc_rels stay [] →
    # build_next_stage_prompt falls to the honest-minimal "no written research
    # artifact … CREATE the materials" prompt with NO transcript path, and the
    # file never reaches the main folder. Confirmed RED by temporarily disabling
    # the snapshot, then restored.
    #


# ════════════════════════════════════════════════════════════════════════════
# (b) EMPTY SESSION — genuinely no output → no transcript, honest-minimal prompt.
# ════════════════════════════════════════════════════════════════════════════

def test_empty_session_no_transcript_honest_minimal(env):
    """A session with NO conversation output (only the echoed seed in the buffer)
    → no transcript is written, the prompt is the honest-minimal D2 'create the
    materials' prompt, persisted == [], no crash."""
    ts, repo, pid = env["ts"], env["repo"], env["pid"]

    rsess = ts.start_session(pid, "research", backend="claude")
    rsid = rsess["session_id"]
    # Seed NOTHING beyond the start seed; write NO file.

    out = ts.prepare_stage_handoff(pid, rsid, "planning")
    short_sid = rsid[:12]
    rel = f"research/{short_sid}-transcript.md"

    assert out["ok"] is True
    assert out["persisted"] == []
    assert out["doc_rels"] == []
    assert not (repo / rel).is_file(), "a transcript was written for an empty session"

    prompt = out["prompt"]
    # Honest-minimal (D2): Crucible, instruct to CREATE, no false "report is in
    # this worktree", no fabricated research doc path.
    assert "Crucible" in prompt
    assert re.search(r"[Cc]reate", prompt, re.I), f"no create instruction: {prompt!r}"
    assert not re.search(r"research/\S+\.md", prompt), \
        f"fabricated research doc path in honest-empty prompt: {prompt!r}"


# ════════════════════════════════════════════════════════════════════════════
# (c) REAL-DOC PRESENT (D4) — a written report → the snapshot does NOT fire.
# ════════════════════════════════════════════════════════════════════════════

def test_real_doc_present_does_not_snapshot(env):
    """A session that DID write research/run-1/REPORT.md (and also has conversation
    in its buffer) → the transcript snapshot does NOT fire (D4): the real report is
    the material, the prompt names REPORT.md, and NO transcript doc is written."""
    ts, repo, pid, eh, pty = (env["ts"], env["repo"], env["pid"], env["eh"],
                              env["pty"])

    rsess = ts.start_session(pid, "research", backend="claude")
    rsid = rsess["session_id"]
    rel = _write_in_worktree(rsess["worktree_path"], "research/run-1/REPORT.md")
    _seed_transcript(pty, rsid)  # there IS conversation too, but a doc was written

    out = ts.prepare_stage_handoff(pid, rsid, "planning")

    short_sid = rsid[:12]
    transcript_rel = f"research/{short_sid}-transcript.md"

    # The real report is the material; the transcript snapshot did not fire (D4).
    assert (repo / rel).is_file()
    assert rel in out["persisted"]
    assert rel in out["prompt"]
    assert transcript_rel not in out["persisted"], \
        "the transcript snapshot fired even though a real doc was produced (D4)"
    assert not (repo / transcript_rel).is_file(), \
        "a transcript doc was written despite a real report (D4 violated)"


# ════════════════════════════════════════════════════════════════════════════
# (d) IDEMPOTENT — calling prepare twice → no duplicate transcript effort.
# ════════════════════════════════════════════════════════════════════════════

def test_conversation_snapshot_is_idempotent(env):
    """prepare_stage_handoff called twice on a conversation-only session →
    deterministic transcript filename + content-addressed persist means no
    duplicate effort and the same real prompt."""
    ts, repo, pid, eh, pty = (env["ts"], env["repo"], env["pid"], env["eh"],
                              env["pty"])

    rsess = ts.start_session(pid, "research", backend="claude")
    rsid = rsess["session_id"]
    _seed_transcript(pty, rsid)

    out1 = ts.prepare_stage_handoff(pid, rsid, "planning")
    store_lane = eh._resolve_subdir("research")
    n1 = len(eh.efforts_for_session_id(repo, pid, store_lane, rsid))
    assert n1 >= 1

    out2 = ts.prepare_stage_handoff(pid, rsid, "planning")
    n2 = len(eh.efforts_for_session_id(repo, pid, store_lane, rsid))

    assert n2 == n1, f"duplicate transcript effort on second prepare: {n1} -> {n2}"
    assert out2["prompt"] == out1["prompt"]
    assert out2["doc_rels"] == out1["doc_rels"]


# ════════════════════════════════════════════════════════════════════════════
# (e) SNAPSHOT-FAILURE BEST-EFFORT — a throwing read_since never propagates.
# ════════════════════════════════════════════════════════════════════════════

def test_snapshot_failure_is_swallowed(env, monkeypatch):
    """If the transcript read raises, prepare_stage_handoff still returns with the
    honest-minimal prompt and NEVER propagates the exception."""
    ts, repo, pid, pty = env["ts"], env["repo"], env["pid"], env["pty"]

    rsess = ts.start_session(pid, "research", backend="claude")
    rsid = rsess["session_id"]
    _seed_transcript(pty, rsid)

    def _boom(*a, **k):
        raise RuntimeError("pty on fire")

    # Patch the read the snapshot uses → the snapshot helper swallows + returns
    # None → prepare degrades to the honest-minimal prompt.
    monkeypatch.setattr(ts._pty, "read_since", _boom)

    out = ts.prepare_stage_handoff(pid, rsid, "planning")  # must NOT raise
    assert out["ok"] is True
    assert out["persisted"] == []
    assert "Crucible" in out["prompt"]
    short_sid = rsid[:12]
    assert not (repo / f"research/{short_sid}-transcript.md").is_file()


# ════════════════════════════════════════════════════════════════════════════
# (f) HONEST PROMPT — the no-docs fallback is honest + actionable (D2).
# ════════════════════════════════════════════════════════════════════════════

def test_no_docs_prompt_is_honest_and_actionable(env):
    """The no-docs fallback prompt does NOT contain the false 'the research report
    is in this worktree' phrasing and DOES instruct the planner to CREATE the
    materials."""
    ts, pid = env["ts"], env["pid"]

    rsess = ts.start_session(pid, "research", backend="claude")
    rsid = rsess["session_id"]
    out = ts.prepare_stage_handoff(pid, rsid, "planning")
    prompt = out["prompt"]

    assert "the research report is in this worktree" not in prompt
    assert re.search(r"create the", prompt, re.I), \
        f"no 'create the materials' instruction: {prompt!r}"
    assert "Master Plan" in prompt and "Implementation Plan" in prompt
