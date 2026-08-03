"""v11.1 Wave 1 — the NON-grass HTTP advance, CONVERSATION-only end-to-end.

THE user-facing fix at the project level. Clicking **Advance to Planning** on a
LIVE research session whose work is ONLY a terminal CONVERSATION (the model
answered in the PTY, wrote NO file) must (a) SNAPSHOT + PERSIST the transcript
into the MAIN project, (b) open the planning session with a REAL prompt naming
the transcript path, (c) ride the transcript into the PLANNING worktree on disk,
and (d) link the sessions.

THE v11 LESSON, HARDENED: this test is CONVERSATION-ONLY. We start a LIVE research
session and write NOTHING to its worktree; instead we seed the STUB PTY read
buffer with simulated transcript content (a ``pty_manager.write`` ECHOES into the
readable buffer — no file, no record_effort, no kill), then POST
``/api/rnd/advance_session`` (research→plan), then assert the transcript was
captured + named + rode into the planning worktree.

NON-VACUITY: this MUST FAIL against the pre-fix code — no snapshot →
``research_set_for_session`` returns None → ``build_next_stage_prompt`` falls to
the honest-minimal fallback with NO transcript path, and the transcript is never
written into main / the planning worktree.

Hermetic: NO real claude/gemini, NO real PTY — ``ANCHOR_PTY_BACKEND=stub``, a
temp git repo, tmp data + tmp worktree base, the server binds a FREE port
(asserted != 8777). ``ANCHOR_PROACTIVE_SUMMARY`` OFF. NEVER binds ``:8777`` /
touches real data / network.
"""
import importlib
import json
import re
import subprocess
import threading
import time
import urllib.request
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


TRANSCRIPT = (
    "\nResearcher: Summarize the trade study.\n"
    "Assistant: The vanadium-redox flow battery wins on cycle life; the key\n"
    "finding is a 20000-cycle floor at 80% depth-of-discharge. Recommendation:\n"
    "adopt the vanadium chemistry and size the stack for a 4-hour duration.\n"
)


@pytest.fixture
def gui_env(tmp_path, monkeypatch):
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
                "session_registry", "worktrees", "lanes", "effort_history",
                "sessions", "summarizer", "gate_adapter", "handoff",
                "terminal_session"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import anchor_gui
    gui = importlib.reload(anchor_gui)

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial")

    import rnd_registry
    proj = rnd_registry.add_project("Temp", str(repo), scaffold=False)
    import terminal_session
    import session_registry
    import effort_history
    import handoff
    import pty_manager
    bundle = {
        "gui": gui, "ts": terminal_session, "reg": session_registry,
        "handoff": handoff, "eh": effort_history, "rnd": rnd_registry,
        "pty": pty_manager, "repo": repo, "pid": proj["id"],
    }
    yield bundle
    try:
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


@pytest.fixture
def server(gui_env):
    gui = gui_env["gui"]
    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield gui_env, f"http://127.0.0.1:{port}", port
    finally:
        time.sleep(0.1)
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
    req = urllib.request.Request(
        base + path, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def _committed_in_repo(repo, rel):
    return _git(repo, "ls-files", "--error-unmatch", rel).returncode == 0


# ════════════════════════════════════════════════════════════════════════════
# THE TRUTH TEST — live research conversation-only, over HTTP. The transcript is
#   snapshotted, named in the prompt, and rides into the PLANNING worktree.
#   MUST FAIL pre-fix.
# ════════════════════════════════════════════════════════════════════════════

def test_advance_conversation_only_snapshots_and_primes_planning(server):
    ts, reg, repo, pid, eh, pty = (server[0]["ts"], server[0]["reg"],
                                   server[0]["repo"], server[0]["pid"],
                                   server[0]["eh"], server[0]["pty"])
    base = server[1]

    # A LIVE research session; seed its PTY read buffer with conversation (no file).
    rsess = ts.start_session(pid, "research", backend="claude")
    rsid = rsess["session_id"]
    pty.write(rsid, TRANSCRIPT)  # echoes into the readable buffer; NO file written

    short_sid = rsid[:12]
    rel = f"research/{short_sid}-transcript.md"

    # Pre-condition (proves the conversation-only flow): nothing in main yet.
    assert not (repo / rel).is_file()
    store_lane = eh._resolve_subdir("research")
    assert eh.efforts_for_session_id(repo, pid, store_lane, rsid) == []

    status, data = _post(base, "/api/rnd/advance_session",
                         {"project_id": pid, "source_session": rsid,
                          "to_lane": "planning"})
    assert status == 200, data
    assert data.get("ok") is True, data
    new_rec = data["session"]
    new_sid = new_rec["session_id"]
    new_wt = new_rec["worktree_path"]

    # (i) the transcript was SNAPSHOTTED + persisted + committed into MAIN.
    assert (repo / rel).is_file(), "transcript was not persisted into the main project"
    assert _committed_in_repo(repo, rel), "transcript was not committed to the repo"
    assert rel in (data.get("persisted") or []), data.get("persisted")

    # (ii) the new planning session's pending_paste names the transcript + Crucible.
    prec = reg.get_session(new_sid)
    paste = prec.get("pending_paste") or ""
    assert paste, "advanced planning session has no pending paste"
    assert rel in paste, f"pending paste missing the transcript path: {paste!r}"
    assert "Crucible" in paste
    assert prec.get("paste_flushed") is False

    # (ii.5) THE LOAD-BEARING ON-DISK CHECK (the v8/v11 standard): the transcript
    #        must exist in the PLANNING CHECKOUT itself — the dir Crucible opens it
    #        from — not merely in main. The planning worktree is created off the
    #        freshly-committed main HEAD (which the keystone just committed the
    #        transcript to), so the file rides into the checkout.
    assert (Path(new_wt) / rel).is_file(), (
        "the snapshotted transcript is NOT present in the PLANNING worktree "
        "checkout (Crucible would hit file-not-found)")

    # (iii) HANDOFF.md references the transcript path.
    handoff_md = Path(new_wt) / "HANDOFF.md"
    assert handoff_md.is_file(), "HANDOFF.md was not written into the planning worktree"
    assert rel in handoff_md.read_text(encoding="utf-8")

    # (iv) NEXT-PROMPT.md exists + names the transcript.
    next_md = Path(new_wt) / "NEXT-PROMPT.md"
    assert next_md.is_file(), "NEXT-PROMPT.md was not written"
    assert rel in next_md.read_text(encoding="utf-8")

    # (v) the sessions are linked (parent + shared chain).
    assert prec.get("parent_session_id") == rsid
    rrec = reg.get_session(rsid)
    assert prec.get("chain_id") == rrec.get("chain_id")

    # The transcript is a research effort tagged with rsid (the keystone).
    tagged = [(e.get("artifact_path") or "").replace("\\", "/")
              for e in eh.efforts_for_session_id(repo, pid, store_lane, rsid)]
    assert rel in tagged, f"no research effort tagged with rsid: {tagged}"

    for r in reg.list_sessions(project_id=pid):
        try:
            ts.kill(r["session_id"])
        except Exception:
            pass
