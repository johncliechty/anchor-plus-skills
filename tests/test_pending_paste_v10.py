"""v10 Wave 1 — Paste-NOT-submit handoff substrate (backend only).

Splits seed delivery: the trio skill auto-loads/greets (phase-1, SUBMITTED, ends
``\\n``), then the task prompt sits in the PTY input UNSENT (phase-2, NO trailing
newline) until the user presses Enter. The pending prompt is delivered exactly
ONCE, after the greet is observed, by the first ``read_since``/``attach`` —
never re-emitted.

Covers the three Wave-1 Given/When/Then cases:
  (a) started with paste_prompt → after the greet, the PTY input buffer holds the
      prompt with NO trailing newline; pending_paste cleared + paste_flushed=True;
  (b) a second read/attach does NOT re-emit the paste (idempotent);
  (c) a session started WITHOUT paste_prompt behaves exactly as v9 (regression).

Hermetic: ``ANCHOR_PTY_BACKEND=stub`` (the stub child echoes written bytes into
its read buffer — see ``pty_manager._StubChild.write``), a temp git repo for the
worktree, a tmp data dir + tmp worktree base, the fake runner. NEVER binds
``:8777``; NEVER a worktree off the real ``C:\\dev\\Anchor`` repo; no network.
"""
import importlib
import subprocess
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()

#: A simulated MODEL greet line. Writing it onto the stub PTY echoes it into the
#: read buffer (see ``pty_manager._StubChild.write``), pushing the GREET_MARKER
#: occurrence count to base+1 — i.e. ONE more than the echoed seed contributes —
#: which is exactly the "model actually greeted" signal the flush now requires.
GREET_LINE = "✓ Skill loaded — what would you like to do?"


def _inject_greet(sid):
    """Surface a real model greet on a session's stub PTY (marker count > base)."""
    import pty_manager
    pty_manager.write(sid, GREET_LINE)


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
    a registered project. The full stack is reloaded against the isolated env so
    every worktree is off the TEMP repo (never C:\\dev\\Anchor)."""
    data = tmp_path / "data"
    data.mkdir()
    wbase = tmp_path / "wt-base"
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(wbase))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    # Don't pin a global seed override — we rely on the built-in greet line so
    # GREET_MARKER appears in the (stub-echoed) seed output buffer.
    monkeypatch.delenv("ANCHOR_TERMINAL_SEED", raising=False)

    for mod in ("paths", "job_runner", "pty_manager", "rnd_registry",
                "effort_history", "sessions", "anchor_marker",
                "session_registry", "worktrees", "lanes", "handoff",
                "terminal_session"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()

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
        "ts": terminal_session, "reg": session_registry, "rnd": rnd_registry,
        "repo": repo, "pid": proj["id"],
    }
    yield bundle
    try:
        import pty_manager
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


# ════════════════════════════════════════════════════════════════════════════
# (a) started with paste_prompt → pasted UNSENT after the greet, fields cleared
# ════════════════════════════════════════════════════════════════════════════

def test_paste_prompt_recorded_pending_not_written_at_start(env):
    """At start, the seed (phase-1) is written + submitted, but the paste_prompt
    is held as ``pending_paste`` (paste_flushed=False) and is NOT yet in the PTY
    output buffer."""
    ts, reg, pid = env["ts"], env["reg"], env["pid"]
    prompt = "PLAN FROM X"
    sess = ts.start_session(pid, "planning", backend="claude",
                            paste_prompt=prompt)
    sid = sess["session_id"]

    rec = reg.get_session(sid)
    assert rec["pending_paste"] == prompt
    assert rec["paste_flushed"] is False
    # Phase-1 seed WAS submitted (the lane has a skill seed, recorded seeded).
    assert rec["seeded"] is True
    assert rec["seed_text"].endswith("\n")  # phase-1 ends in newline (submitted)

    # The prompt is NOT in the buffer yet (we haven't read/attached past it).
    buf, _next = __import__("pty_manager").read_since(sid, 0)["text"], None
    assert prompt not in buf, "paste_prompt must NOT be written at start"


def test_no_premature_flush_on_echoed_seed_only(env):
    """SOUNDNESS GUARD (fails against the pre-fix logic): with ONLY the echoed
    seed in the buffer — and NO real model greet injected — read_since/attach must
    NOT flush. The seed text itself quotes the greet line, so a naive substring
    test would (wrongly) see the marker and flush prematurely (Master-Plan R1)."""
    ts, reg, pid = env["ts"], env["reg"], env["pid"]
    import pty_manager
    prompt = "PLAN FROM X"
    sess = ts.start_session(pid, "planning", backend="claude",
                            paste_prompt=prompt)
    sid = sess["session_id"]

    # The buffer holds ONLY the echoed seed (which DOES contain the greet marker).
    # No model greet has been injected, so marker_count == base → no flush.
    ts.read_since(sid, 0)
    ts.attach(sid)

    rec = reg.get_session(sid)
    assert rec["paste_flushed"] is False, \
        "must NOT flush on the echoed seed alone (premature-flush bug)"
    assert rec["pending_paste"] == prompt, "paste must still be pending"
    buf = pty_manager.read_since(sid, 0)["text"]
    assert prompt not in buf, "paste must NOT be in the PTY input before the greet"


def test_paste_flushed_unsent_after_greet_via_read_since(env):
    """*Given* a stub session started with paste_prompt, *When* a real model greet
    is injected (marker count > base) and we read, *Then* the PTY input buffer
    contains the prompt with NO trailing newline and pending_paste is cleared +
    paste_flushed=True."""
    ts, reg, pid = env["ts"], env["reg"], env["pid"]
    import pty_manager
    prompt = "PLAN FROM X"
    sess = ts.start_session(pid, "planning", backend="claude",
                            paste_prompt=prompt)
    sid = sess["session_id"]

    # Inject the MODEL's real greet so the marker count exceeds the echoed-seed
    # base → the flush fires on the next read.
    _inject_greet(sid)
    out = ts.read_since(sid, 0)
    assert isinstance(out, dict) and "text" in out

    # The paste landed in the PTY input buffer (the stub echoes writes).
    full, _next = pty_manager.read_since(sid, 0)["text"], None
    assert prompt in full, "paste_prompt must be delivered after the greet"
    # CRITICAL: delivered WITHOUT a trailing newline (unsent). The prompt is the
    # tail of the buffer (written last) and is not followed by a newline.
    assert full.rstrip("\r") .endswith(prompt), \
        "paste must be the last thing written, with NO trailing newline"
    assert prompt + "\n" not in full, "paste must NOT be auto-submitted"

    rec = reg.get_session(sid)
    assert rec["paste_flushed"] is True
    assert rec["pending_paste"] == "", "pending_paste must be cleared after flush"


def test_paste_with_trailing_newline_is_stripped(env):
    """A pending prompt that itself ends in a newline (e.g. a NEXT-PROMPT.md body)
    is delivered with the trailing newline STRIPPED so it can never auto-submit."""
    ts, reg, pid = env["ts"], env["reg"], env["pid"]
    import pty_manager
    prompt = "PLAN FROM X\r\n"
    sess = ts.start_session(pid, "planning", backend="claude",
                            paste_prompt=prompt)
    sid = sess["session_id"]

    _inject_greet(sid)
    ts.read_since(sid, 0)

    full = pty_manager.read_since(sid, 0)["text"]
    assert "PLAN FROM X" in full
    assert "PLAN FROM X\r\n" not in full, "trailing newline must be stripped"
    assert "PLAN FROM X\n" not in full, "trailing newline must be stripped"
    assert full.endswith("PLAN FROM X"), "paste lands UNSENT (no trailing newline)"


def test_paste_flushed_via_attach(env):
    """``attach`` also triggers the flush (the reattach path)."""
    ts, reg, pid = env["ts"], env["reg"], env["pid"]
    import pty_manager
    prompt = "EXECUTE THE PLAN"
    sess = ts.start_session(pid, "build", backend="claude",
                            paste_prompt=prompt)
    sid = sess["session_id"]

    _inject_greet(sid)
    res = ts.attach(sid)
    assert res["ok"] is True

    full = pty_manager.read_since(sid, 0)["text"]
    assert prompt in full
    assert prompt + "\n" not in full
    rec = reg.get_session(sid)
    assert rec["paste_flushed"] is True
    assert rec["pending_paste"] == ""


# ════════════════════════════════════════════════════════════════════════════
# (b) idempotent — a second read/attach does NOT re-emit the paste
# ════════════════════════════════════════════════════════════════════════════

def test_paste_not_re_emitted_on_subsequent_reads(env):
    """*Given* the same session, *When* read_since/attach is called again, *Then*
    the paste is NOT re-emitted (delivered exactly once)."""
    ts, pid = env["ts"], env["pid"]
    import pty_manager
    prompt = "PLAN FROM X"
    sess = ts.start_session(pid, "planning", backend="claude",
                            paste_prompt=prompt)
    sid = sess["session_id"]

    _inject_greet(sid)
    ts.read_since(sid, 0)  # first read → flush
    after_first = pty_manager.read_since(sid, 0)["text"]
    n1 = after_first.count(prompt)
    assert n1 == 1, "paste should appear exactly once after the first flush"

    # Repeated reads + an attach must not write it again.
    ts.read_since(sid, 0)
    ts.read_since(sid, len(after_first))
    ts.attach(sid)
    after_more = pty_manager.read_since(sid, 0)["text"]
    assert after_more.count(prompt) == 1, "paste was re-emitted (not idempotent)"


def test_flush_pending_paste_direct_is_idempotent(env):
    """Calling the flush helper directly twice returns True then False and writes
    the paste exactly once."""
    ts, reg, pid = env["ts"], env["pid"], env["pid"]
    reg = env["reg"]
    import pty_manager
    prompt = "ONCE ONLY"
    sess = ts.start_session(pid, "planning", backend="claude",
                            paste_prompt=prompt)
    sid = sess["session_id"]

    _inject_greet(sid)
    first = ts._flush_pending_paste(sid)
    assert first is True
    second = ts._flush_pending_paste(sid)
    assert second is False
    assert pty_manager.read_since(sid, 0)["text"].count(prompt) == 1
    assert reg.get_session(sid)["paste_flushed"] is True


def test_concurrent_flush_writes_paste_exactly_once(env):
    """Defect 2 (TOCTOU): driving the flush from two threads on the same greeted
    session writes the paste EXACTLY ONCE — the WRITE_LOCK compare-and-set claims
    it before the PTY write so only one thread proceeds. (Best-effort threaded
    assertion; the deterministic CAS is also covered by the direct-twice test.)"""
    import threading
    ts, reg, pid = env["ts"], env["reg"], env["pid"]
    import pty_manager
    prompt = "CONCURRENT ONCE"
    sess = ts.start_session(pid, "planning", backend="claude",
                            paste_prompt=prompt)
    sid = sess["session_id"]

    _inject_greet(sid)

    results = []
    barrier = threading.Barrier(2)

    def _worker():
        barrier.wait()  # maximize the overlap window
        results.append(ts._flush_pending_paste(sid))

    threads = [threading.Thread(target=_worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Exactly one thread wins the CAS and writes; the paste appears exactly once.
    assert results.count(True) == 1, "exactly one thread should win the CAS"
    assert pty_manager.read_since(sid, 0)["text"].count(prompt) == 1, \
        "paste must be written exactly once under concurrency"
    assert reg.get_session(sid)["paste_flushed"] is True
    assert reg.get_session(sid)["pending_paste"] == ""


# ════════════════════════════════════════════════════════════════════════════
# (c) regression — no paste_prompt behaves exactly as v9
# ════════════════════════════════════════════════════════════════════════════

def test_no_paste_prompt_behaves_as_v9(env):
    """*Given* a session started WITHOUT paste_prompt, *Then* there is no
    pending_paste, the normal seed is auto-submitted, and reads/attach do not
    write anything extra (regression guard)."""
    ts, reg, pid = env["ts"], env["reg"], env["pid"]
    import pty_manager
    sess = ts.start_session(pid, "planning", backend="claude")
    sid = sess["session_id"]

    rec = reg.get_session(sid)
    assert rec["pending_paste"] == ""
    assert rec["paste_flushed"] is False
    assert rec["seeded"] is True
    assert rec["seed_text"].endswith("\n")  # phase-1 still auto-submitted

    # The buffer holds exactly the seed echo; a read does not add anything.
    before = pty_manager.read_since(sid, 0)["text"]
    assert before == rec["seed_text"], "only the seed should be in the buffer"
    ts.read_since(sid, 0)
    ts.attach(sid)
    after = pty_manager.read_since(sid, 0)["text"]
    assert after == before, "no paste should be written when none is pending"


def test_seed_context_path_unchanged_back_compat(env):
    """A seed_context (v4/v6 promote/advance) WITHOUT paste_prompt still folds
    onto the seed and is auto-submitted — no pending_paste is created."""
    ts, reg, pid = env["ts"], env["reg"], env["pid"]
    sess = ts.start_session(pid, "planning", backend="claude",
                            seed_context="work on the widget idea")
    sid = sess["session_id"]
    rec = reg.get_session(sid)
    assert rec["pending_paste"] == ""
    assert rec["paste_flushed"] is False
    assert "widget idea" in rec["seed_text"]
    assert rec["seed_text"].endswith("\n")  # folded seed_context is submitted


# ════════════════════════════════════════════════════════════════════════════
# back-compat normalization of the two new registry fields
# ════════════════════════════════════════════════════════════════════════════

def test_registry_normalizes_new_fields_back_compat(env):
    """A pre-v10 record (no pending_paste/paste_flushed) normalizes to ''/False
    and the fields round-trip through update_session."""
    reg, pid = env["reg"], env["pid"]
    rec = reg.register_session(pid, "planning", status=reg.STATUS_RUNNING)
    sid = rec["session_id"]
    # Fresh record defaults.
    assert rec["pending_paste"] == ""
    assert rec["paste_flushed"] is False

    # Round-trip through update_session + a reload.
    reg.update_session(sid, pending_paste="HOLD ME", paste_flushed=False)
    again = reg.get_session(sid)
    assert again["pending_paste"] == "HOLD ME"
    assert again["paste_flushed"] is False

    reg.update_session(sid, paste_flushed=True, pending_paste="")
    final = reg.get_session(sid)
    assert final["paste_flushed"] is True
    assert final["pending_paste"] == ""
