"""v11.1 Wave 2 — Grass advance ALWAYS proceeds (the CONVERSATION-only fix).

THE BUG John reported: advancing a GRASS research session that was a CONVERSATION
(the model answered in the terminal, wrote NO file) returned "no materials to
advance" and opened NOTHING. The culprit was the ``no-research-material`` hard-
refusal in ``effort_history.advance_grass_research_to_plan`` (it required the
keystone's prompt to name a written, document-classified file, else it returned
``{"ok": False, "reason": "no-research-material"}`` BEFORE any ``start_session``).

v11.1 Wave 1 made the keystone (``terminal_session.prepare_stage_handoff``) ALWAYS
produce material: when no file was written it SNAPSHOTS the source session's PTY
transcript to ``research/<short-sid>-transcript.md`` (persisted + session-tagged)
and names it in the prompt. Wave 2 REMOVES the grass hard-refusal so the advance
falls through to the (UNCHANGED) v10 W5 contained-grass mint/focus/link machinery
and OPENS the plan session — exactly like the non-grass path.

THE v11 LESSON, HARDENED (see IMPLEMENTATION-PLAN.md Conventions): this is a
CONVERSATION-ONLY test. We develop a grass RESEARCH dev session and seed its STUB
PTY read buffer with simulated transcript content — writing NOTHING to its
worktree, NO ``record_effort``. The advance must then snapshot + persist the
transcript and OPEN the contained grass plan dev session naming it.

NON-VACUITY: the (a) truth test below FAILS against the pre-W2 code — the
``no-research-material`` guard fires on a conversation-only session (no written
doc), returns ``ok:False`` with NO plan session minted. With W2 the guard is gone
→ the plan session opens.

Hermetic: ``ANCHOR_PTY_BACKEND=stub`` + the fake runner + a temp git repo + a tmp
data dir + tmp worktree base; ``ANCHOR_PROACTIVE_SUMMARY`` OFF. NEVER binds
``:8777`` / touches real data / network.
"""
import importlib
import json as _json
import re
import subprocess
import threading
import urllib.request as _req
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()

#: A simulated MODEL greet line — writing it onto the stub PTY echoes it into the
#: read buffer, the "model actually greeted" signal the pending-paste flush needs.
GREET_LINE = "✓ Crucible loaded — what would you like to do?"

#: Simulated research CONVERSATION content — plausibly named so the snapshot text
#: is non-trivial. NO file is written; this goes onto the PTY read buffer only.
TRANSCRIPT = (
    "\nResearcher: Which coolant loop maximizes thermal margin?\n"
    "Assistant: The molten-salt loop wins — a 40C transient tolerance with no\n"
    "scram and the simplest pump topology. Recommendation: prototype the pump\n"
    "seal and pursue the molten-salt design.\n"
)


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
    """Tmp data dir + worktree base + stub PTY + fake runner + a temp git repo +
    a registered project + a seeded grass idea, full stack reloaded against the
    isolated env so every worktree is off the TEMP repo (never C:\\dev\\Anchor)."""
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
    import anchor_gui
    gui = importlib.reload(anchor_gui)

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
    pid = proj["id"]
    idea = effort_history.add_idea(str(repo), pid,
                                   "Passive autonomous cooling loop",
                                   notes="A natural-circulation decay-heat loop.")
    bundle = {
        "gui": gui, "ts": terminal_session, "reg": session_registry,
        "handoff": handoff, "eh": effort_history, "rnd": rnd_registry,
        "pty": pty_manager, "repo": repo, "pid": pid, "wbase": wbase,
        "data": data, "idea_id": idea.get("job_id") or idea.get("id"),
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


# ════════════════════════════════════════════════════════════════════════════
# (a) THE TRUTH TEST — a grass research CONVERSATION (transcript in the PTY
#     buffer, NO file) → the contained grass PLAN dev session OPENS, naming the
#     snapshotted transcript. MUST FAIL pre-W2 (the guard refuses → no session).
# ════════════════════════════════════════════════════════════════════════════

def test_grass_advance_conversation_only_opens_contained_linked(env):
    ts, eh, reg, repo, pid, idea_id, pty = (
        env["ts"], env["eh"], env["reg"], env["repo"], env["pid"],
        env["idea_id"], env["pty"])

    # Develop the contained (idea, 'research') dev session. Seed its PTY buffer
    # with a CONVERSATION — write NO file to its worktree, NO record_effort.
    rrec = eh.develop_grass_idea(pid, idea_id, "research", backend="claude")
    rsid = rrec["session_id"]
    _seed_transcript(pty, rsid)

    # Pre-condition: nothing persisted for the research session yet.
    store_lane = eh._resolve_subdir("research")
    assert eh.efforts_for_session_id(repo, pid, store_lane, rsid) == []

    out = eh.advance_grass_research_to_plan(pid, idea_id)

    # (a) ok:True + a grass PLAN dev session OPENS — the bug is gone (no refusal).
    assert out["ok"] is True, out
    assert out["reason"] != "no-research-material", \
        "the removed guard must no longer fire on a conversation-only session"
    assert out["research_session_id"] == rsid
    prec = out["session"]
    assert prec is not None
    psid = prec["session_id"]
    assert prec["lane"] == "plan"
    assert psid != rsid

    short_sid = rsid[:12]
    rel = f"research/{short_sid}-transcript.md"

    # (b) the transcript was snapshotted + persisted into the MAIN project +
    #     committed + tagged with rsid; the plan session's pending_paste NAMES it
    #     and instructs to create the plan.
    assert (repo / rel).is_file(), "transcript was not snapshotted into the project"
    assert _committed_in_repo(repo, rel), "transcript was not committed"
    body = (repo / rel).read_text(encoding="utf-8")
    assert "molten-salt" in body, "transcript content was lost"
    tagged = [(e.get("artifact_path") or "").replace("\\", "/")
              for e in eh.efforts_for_session_id(repo, pid, store_lane, rsid)]
    assert rel in tagged, f"no research effort tagged with rsid: {tagged}"

    full = reg.get_session(psid)
    paste = full["pending_paste"]
    assert paste, "the plan dev session must carry a pending paste"
    assert "Crucible" in paste
    assert rel in paste, f"the prompt must name the transcript path: {paste!r}"
    assert re.search(r"[Rr]ead these|[Cc]reate", paste), \
        f"the prompt must be actionable (read/create): {paste!r}"
    assert not paste.endswith("\n"), "a reviewable paste must not auto-submit"
    assert full["paste_flushed"] is False

    # (b2) v11.1 W2 — the transcript the prompt NAMES is ON DISK in the plan dev
    #      session's worktree (the v8/v11 standard: Crucible can READ it, not just
    #      see it named). For the fresh-mint case the worktree is cut off main HEAD
    #      AFTER the commit, but we assert the on-disk presence regardless + the
    #      durable HANDOFF.md/NEXT-PROMPT.md the non-grass path writes.
    plan_wt = full["worktree_path"]
    assert plan_wt, "the plan dev session must have a worktree"
    assert (Path(plan_wt) / rel).is_file(), \
        "the snapshotted transcript must be ON DISK in the plan worktree"
    assert "molten-salt" in (Path(plan_wt) / rel).read_text(encoding="utf-8")
    assert (Path(plan_wt) / "HANDOFF.md").is_file(), \
        "the plan worktree must carry the durable HANDOFF.md"
    assert (Path(plan_wt) / "NEXT-PROMPT.md").is_file(), \
        "the plan worktree must carry the durable NEXT-PROMPT.md"
    assert rel in (Path(plan_wt) / "HANDOFF.md").read_text(encoding="utf-8")

    # (c) CONTAINED (GRASS_DEV_LABEL_PREFIX → excluded from board/top strip) +
    #     LINKED (parent_session_id=rsid, shared chain) + carries grass_origin.
    assert full["label"].startswith(eh.GRASS_DEV_LABEL_PREFIX)
    assert eh.is_grass_dev_label(full["label"]) is True
    assert full["parent_session_id"] == rsid
    assert full["chain_id"] == reg.chain_for(rsid)
    assert full["grass_origin"] == idea_id

    # (d) the v10 W5 invariants preserved: the idea STAYS in grass; the
    #     (idea, 'plan') dedupe map is persisted; the stage edge is recorded.
    assert eh.get_grass_idea(repo, pid, idea_id) is not None
    idea_rec = eh.get_grass_idea(repo, pid, idea_id)
    assert eh._grass_dev_sessions(idea_rec).get("plan") == psid
    links = env["handoff"].list_stage_links(repo, pid)
    assert any(l["from_session_id"] == rsid and l["to_session_id"] == psid
               and l["kind"] == "research->plan" for l in links)

    # Re-advance FOCUSES the same plan dev session (dedupe — v10 W5 preserved).
    out2 = eh.advance_grass_research_to_plan(pid, idea_id)
    assert out2["ok"] is True
    assert out2["session"]["session_id"] == psid
    assert out2["reason"] == "focused-existing"
    plans = [s for s in reg.list_sessions(project_id=pid)
             if s.get("lane") == "plan"]
    assert len(plans) == 1, "re-advance must not mint a second plan session"

    # After the greet, the pending paste flushes UNSENT.
    pty.write(psid, GREET_LINE)
    ts.read_since(psid, 0)
    buf = pty.read_since(psid, 0)["text"]
    assert paste in buf
    assert paste + "\n" not in buf, "paste must NOT auto-submit"

    ts.kill(psid)
    ts.kill(rsid)


# ════════════════════════════════════════════════════════════════════════════
# (a2) THE BLOCKER TEST — develop-plan-FIRST. The user develops the grass PLAN
#      dev session FIRST (bare), THEN seeds the research session as a CONVERSATION
#      and advances. The advance FOCUSES the existing plan session (dedupe — no
#      2nd mint) and delivers the transcript-backed prompt via queue_paste — but
#      the plan worktree was created BEFORE the transcript commit, so the named
#      doc is ABSENT from its checkout. This test PROVES the fix: the transcript
#      is NOW materialized ON DISK in the pre-existing plan worktree.
#
#      NON-VACUITY: against the pre-this-fix W2 code the on-disk assert FAILS —
#      ``advance_grass_research_to_plan``'s focused-existing branch did NOT write
#      any durable artifact into the plan worktree, so the named transcript was
#      absent from the checkout and Crucible would hit file-not-found.
# ════════════════════════════════════════════════════════════════════════════

def test_grass_advance_develop_plan_first_materializes_transcript(env):
    ts, eh, reg, repo, pid, idea_id, pty = (
        env["ts"], env["eh"], env["reg"], env["repo"], env["pid"],
        env["idea_id"], env["pty"])

    # 1) Develop the contained (idea, 'plan') dev session FIRST — BARE (no handoff,
    #    pending_paste == '' / paste_flushed False). Its worktree is created NOW,
    #    BEFORE any research transcript is committed.
    prec0 = eh.develop_grass_idea(pid, idea_id, "plan", backend="claude")
    psid = prec0["session_id"]
    plan_wt = prec0["worktree_path"]
    assert plan_wt
    full0 = reg.get_session(psid)
    assert not (full0.get("pending_paste") or "")
    assert full0.get("paste_flushed") is False

    # 2) THEN develop the (idea, 'research') dev session as a CONVERSATION — seed
    #    its PTY buffer, write NO file to its worktree.
    rrec = eh.develop_grass_idea(pid, idea_id, "research", backend="claude")
    rsid = rrec["session_id"]
    _seed_transcript(pty, rsid)

    short_sid = rsid[:12]
    rel = f"research/{short_sid}-transcript.md"

    # Pre-condition: the transcript named-to-be is NOT yet in the plan worktree.
    assert not (Path(plan_wt) / rel).is_file()

    out = eh.advance_grass_research_to_plan(pid, idea_id)

    # (a) the plan session is FOCUSED (dedupe — NOT a 2nd mint).
    assert out["ok"] is True, out
    assert out["reason"] == "focused-existing"
    assert out["session"]["session_id"] == psid
    plans = [s for s in reg.list_sessions(project_id=pid)
             if s.get("lane") == "plan"]
    assert len(plans) == 1, "develop-plan-first advance must not mint a 2nd plan"

    # (b) the transcript-backed prompt is delivered (queue_paste onto the bare
    #     plan session).
    assert out["paste_delivered"] is True
    full = reg.get_session(psid)
    paste = full["pending_paste"]
    assert paste and "Crucible" in paste
    assert rel in paste, f"the delivered prompt must name the transcript: {paste!r}"
    assert not paste.endswith("\n"), "a reviewable paste must not auto-submit"

    # (c) THE FIX — the transcript is NOW present ON DISK in the PRE-EXISTING plan
    #     worktree (FAILS against pre-this-fix W2 code: the file was absent).
    assert (Path(plan_wt) / rel).is_file(), \
        "the transcript must be materialized into the pre-existing plan worktree"
    assert "molten-salt" in (Path(plan_wt) / rel).read_text(encoding="utf-8")
    # The durable handoff artifacts are written into the plan worktree too.
    assert (Path(plan_wt) / "HANDOFF.md").is_file()
    assert (Path(plan_wt) / "NEXT-PROMPT.md").is_file()
    assert rel in (Path(plan_wt) / "HANDOFF.md").read_text(encoding="utf-8")

    # (d) the contained-grass invariants are preserved: the focused-existing plan
    #     session stays CONTAINED (the develop-first session was bare, so it keeps
    #     its develop label + carries no grass_origin — v10 W5 wiring untouched;
    #     focus must NOT re-stamp the record); the idea stays in grass.
    assert full["label"].startswith(eh.GRASS_DEV_LABEL_PREFIX)
    assert eh.get_grass_idea(repo, pid, idea_id) is not None

    ts.kill(psid)
    ts.kill(rsid)


# ════════════════════════════════════════════════════════════════════════════
# (b) NEGATIVE — a grass idea with NO research dev session at all → honest
#     no-research-session (there is legitimately nothing to advance FROM).
# ════════════════════════════════════════════════════════════════════════════

def test_grass_advance_no_research_session_is_honest(env):
    eh, reg, pid, idea_id = env["eh"], env["reg"], env["pid"], env["idea_id"]
    out = eh.advance_grass_research_to_plan(pid, idea_id)
    assert out["ok"] is False
    assert out["session"] is None
    assert out["reason"] == "no-research-session"
    plans = [s for s in reg.list_sessions(project_id=pid)
             if s.get("lane") == "plan"]
    assert not plans, "no plan session may be minted with nothing to advance FROM"


# ════════════════════════════════════════════════════════════════════════════
# (b2) EMPTY SESSION (the W2 guard-removal discriminator) — a grass research dev
#      session with genuinely NO output (no file, no conversation) NO LONGER
#      refuses; it opens the plan session with the honest-minimal prompt. This
#      case FAILS pre-W2: W1's keystone yields doc_rels=[] for an empty session →
#      the removed ``no-research-material`` guard fired → no plan session minted.
# ════════════════════════════════════════════════════════════════════════════

def test_grass_advance_empty_research_opens_honest_minimal(env):
    ts, eh, reg, repo, pid, idea_id = (
        env["ts"], env["eh"], env["reg"], env["repo"], env["pid"],
        env["idea_id"])
    rrec = eh.develop_grass_idea(pid, idea_id, "research", backend="claude")
    rsid = rrec["session_id"]
    # NO file AND NO conversation seeded → genuinely empty.

    out = eh.advance_grass_research_to_plan(pid, idea_id)
    assert out["ok"] is True, out  # FAILS pre-W2 (guard refuses)
    assert out["reason"] != "no-research-material"
    prec = out["session"]
    assert prec is not None and prec["lane"] == "plan"
    psid = prec["session_id"]
    full = reg.get_session(psid)
    assert full["parent_session_id"] == rsid
    assert full["grass_origin"] == idea_id
    assert full["label"].startswith(eh.GRASS_DEV_LABEL_PREFIX)
    paste = full["pending_paste"]
    assert paste and "Crucible" in paste
    assert re.search(r"create the", paste, re.I), paste
    # No fabricated transcript path for a genuinely empty session.
    assert not re.search(r"research/\S+-transcript\.md", paste), paste
    ts.kill(psid)
    ts.kill(rsid)


# ════════════════════════════════════════════════════════════════════════════
# (c) HTTP — the same conversation-only flow through POST /api/rnd/grass_advance.
# ════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def server(env):
    gui = env["gui"]
    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield env, f"http://127.0.0.1:{port}", port
    finally:
        try:
            srv.shutdown()
        except Exception:
            pass
        try:
            srv.server_close()
        except Exception:
            pass
        t.join(timeout=5)


def _post(base, path, payload):
    data = _json.dumps(payload).encode("utf-8")
    req = _req.Request(base + path, data=data,
                       headers={"Content-Type": "application/json"})
    with _req.urlopen(req, timeout=8) as resp:
        return resp.status, _json.loads(resp.read().decode("utf-8"))


def test_grass_advance_conversation_only_over_http(server):
    env, base, _ = server
    eh, reg, repo, pid, idea_id, pty = (
        env["eh"], env["reg"], env["repo"], env["pid"], env["idea_id"],
        env["pty"])

    rrec = eh.develop_grass_idea(pid, idea_id, "research", backend="claude")
    rsid = rrec["session_id"]
    _seed_transcript(pty, rsid)

    status, data = _post(base, "/api/rnd/grass_advance",
                         {"project_id": pid, "idea_id": idea_id})
    assert status == 200
    assert data["ok"] is True, data
    assert data["reason"] != "no-research-material"
    psid = data["session"]["session_id"]
    short_sid = rsid[:12]
    rel = f"research/{short_sid}-transcript.md"
    full = reg.get_session(psid)
    assert full["parent_session_id"] == rsid
    assert full["grass_origin"] == idea_id
    assert rel in (full["pending_paste"] or ""), \
        "the HTTP advance must name the snapshotted transcript"
    assert (repo / rel).is_file()

    import terminal_session
    terminal_session.kill(psid)
    terminal_session.kill(rsid)
