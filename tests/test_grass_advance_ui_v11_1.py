"""v11.1 Wave 2 — Grass "Advance to Plan" opens on a CONVERSATION (Playwright).

DEV-ONLY (``pytest.importorskip("playwright.sync_api")``; SKIPs cleanly where
Playwright/Chromium is absent — never imported by product code).

The behavior under test (the failure John reported, now fixed): in the grass
workbench the user develops a RESEARCH dev session that is a CONVERSATION (content
appears in the terminal, NO file is written), then clicks "➜ Advance to Plan". The
contained grass PLAN terminal must OPEN (no "no materials" toast) and its
pasted-but-UNSENT prompt must NAME the snapshotted ``research/<sid>-transcript.md``.

DISCRIMINATING TOKEN: the transcript path ``research/<sid>-transcript.md`` appears
in the plan terminal's pasted prompt ONLY if the W1 snapshot + W2 advance worked.
Pre-W2 the empty/conversation advance refused → no plan terminal, no token.

Hermetic: ``ANCHOR_PTY_BACKEND=stub`` + fake runner + temp git repo + tmp data +
tmp worktree base; a free port != 8777; ``ANCHOR_PROACTIVE_SUMMARY`` OFF. NEVER
binds ``:8777`` / touches real data / network.
"""
import importlib
import subprocess
import threading
import time
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()
_DEVTEST = Path(__file__).resolve().parent.parent / "_devtest"

#: A simulated MODEL greet line — writing it onto the stub PTY echoes it into the
#: read buffer, the "model greeted" signal the pending-paste flush requires.
GREET_LINE = "✓ Crucible loaded — what would you like to do?"

#: Simulated research CONVERSATION — written LIVE onto the research session's PTY
#: read buffer (no file, no record_effort), the exact conversation-only path.
TRANSCRIPT = (
    "\nResearcher: Which coolant loop maximizes thermal margin?\n"
    "Assistant: The molten-salt loop wins — a 40C transient tolerance with no\n"
    "scram and the simplest pump topology. Prototype the pump seal.\n"
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
        "eh": effort_history, "rnd": rnd_registry, "pty": pty_manager,
        "repo": repo, "pid": pid, "idea_id": idea.get("job_id") or idea.get("id"),
    }
    yield bundle
    try:
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


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


def test_grass_advance_conversation_opens_plan_over_http(server):
    """v12 Wave 11 (MIGRATED). The retired two-terminal ``data-dev``/``data-advance``
    grass UI is gone (research→plan now advances IN-SESSION for v12 efforts). The
    v11.1 CONVERSATION-ONLY advance contract is RETAINED for LEGACY ideas and is
    asserted here over HTTP (server truth), exactly as the retired UI exercised it:
    a research dev session that is a CONVERSATION (transcript in the PTY buffer, NO
    file) advances → a linked grass PLAN dev session OPENS (no "no materials"
    refusal) whose pending paste NAMES the snapshotted
    ``research/<sid>-transcript.md`` (the discriminating W1 token), held UNSENT.

    DISCRIMINATING TOKEN: the transcript path appears in the plan session's pasted
    prompt ONLY if the W1 snapshot + W2 advance worked. Pre-W2 the conversation
    advance refused → no plan session, no token."""
    import json
    import urllib.request
    env, base, _ = server
    pid, idea_id = env["pid"], env["idea_id"]
    ts, eh, reg, pty = env["ts"], env["eh"], env["reg"], env["pty"]

    # A LEGACY research dev session seeded with a CONVERSATION (no file written).
    rrec = eh.develop_grass_idea(pid, idea_id, "research", backend="claude")
    rsid = rrec["session_id"]
    assert not rrec.get("effort_managed"), "legacy develop must be effort_managed False"
    pty.write(rsid, TRANSCRIPT)
    transcript_token = f"research/{rsid[:12]}-transcript.md"

    # Advance over HTTP (no token set in this fixture → 200). It must NOT refuse on
    # the conversation-only case (v11.1 D1) — the plan session opens.
    payload = json.dumps({"project_id": pid, "idea_id": idea_id}).encode("utf-8")
    req = urllib.request.Request(base + "/api/rnd/grass_advance", data=payload,
                                 method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    assert data["ok"] is True, f"conversation advance must NOT refuse: {data}"
    psid = data["session"]["session_id"]
    assert psid != rsid, "the plan dev session must be distinct"

    # Server truth: linked + grass_origin + the pending paste NAMES the snapshotted
    # transcript (the discriminating token), held UNSENT.
    prec = reg.get_session(psid)
    assert prec["parent_session_id"] == rsid
    assert prec["grass_origin"] == idea_id
    assert prec["pending_paste"], "the plan session must carry a pending paste"
    assert transcript_token in prec["pending_paste"], \
        "the prompt must name the snapshotted transcript (W1+W2 token)"
    assert prec["paste_flushed"] is False

    # Drive the greet so the pending paste flushes UNSENT, then confirm the token
    # lands in the PTY but is NOT auto-submitted. The flush is wired into
    # terminal_session.read_since (the greet-marker guard) — read via the terminal
    # session, not the raw pty, so the flush fires.
    pty.write(psid, GREET_LINE)
    full = ""
    for _ in range(8):
        ts.read_since(psid, 0)         # triggers _flush_pending_paste after greet
        full = pty.read_since(psid, 0)["text"]
        if transcript_token in full:
            break
        time.sleep(0.1)
    assert transcript_token in full, "the pending paste must flush into the PTY"
    assert prec["pending_paste"] + "\n" not in full, \
        "the advance paste must NOT be auto-submitted"

    for r in reg.list_sessions(project_id=pid):
        try:
            ts.kill(r["session_id"])
        except Exception:
            pass
