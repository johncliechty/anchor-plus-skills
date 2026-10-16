"""v7 Wave 2 — summarize each session on finish (#3): proactive cache + blurb.

Backend-only. When a session reaches a terminal state — a deliberate hard-kill
(``POST /api/rnd/term_kill``), an explicit finish→build
(``POST /api/rnd/finish_to_build``), or a reconcile-dead transition (the
``GET /api/rnd/term_sessions`` refresh path) — Anchor schedules a BACKGROUND
session-summary so the finished tile opens to a real summary and the session is
restartable. The wiring MUST be:

  - NON-BLOCKING: the finish (kill / finish / reconcile) HTTP response returns
    immediately; generation runs on a daemon thread;
  - IDEMPOTENT: a session that already has a CACHED summary is skipped (a second
    finish / a repeated reconcile poll never re-runs the model);
  - NO-CACHE-POISON: a FAILED generation leaves NO cache (retryable), per the
    summarizer FIX 2.

Plus ``summarizer.session_blurb(folder, pid, lane, session_id)`` — a short, clean
(Wave-1 normalizer) one-liner from the CACHED session summary, or an honest ``""``
when uncached. PURE cache read — NEVER a synchronous model call.

Hermetic, like the Wave-6 polish tests: stub PTY backend
(``ANCHOR_PTY_BACKEND=stub``), the PRODUCTION-shaped stream-json stub runner
(``tests/stub_streamjson.py`` via ``ANCHOR_RUNNER_CMD``), a temp ``ANCHOR_DATA_DIR``
+ ``ANCHOR_WORKTREE_BASE`` + a throwaway temp git repo. Proactive generation is
enabled ONLY within a test (the live server's behavior). Never ``:8777``, never
real data. Stdlib only.
"""
import importlib
import json as _json
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

import pytest

STREAMJSON = (Path(__file__).resolve().parent / "stub_streamjson.py").as_posix()
FAILRUNNER = (Path(__file__).resolve().parent / "stub_fail_runner.py").as_posix()


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


# ── env / fixtures (stub PTY + stream-json runner + temp git repo + project) ──

@pytest.fixture
def env(tmp_path, monkeypatch):
    """Tmp data dir + tmp worktree base + stub PTY + the STREAM-JSON runner + a
    temp git repo + a registered project. start_session creates real worktrees off
    the TEMP repo (never C:\\dev\\Anchor); summaries flow through the production
    envelope parser; nothing binds :8777."""
    data = tmp_path / "data"
    data.mkdir()
    wbase = tmp_path / "wt-base"
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(wbase))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {STREAMJSON}")
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)

    for mod in ("paths", "job_runner", "pty_manager", "rnd_registry",
                "effort_history", "sessions", "anchor_marker",
                "session_registry", "worktrees", "lanes", "summarizer",
                "handoff", "terminal_session", "brownfield_scan"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import anchor_gui
    gui = importlib.reload(anchor_gui)
    # Proactive generation ON (the live server's behavior) so the finish hooks
    # actually schedule the background summary.
    monkeypatch.setattr(gui, "_PROACTIVE_SUMMARY_ENABLED", True, raising=False)

    import effort_history
    import sessions
    import terminal_session
    import session_registry
    import summarizer
    import rnd_registry
    import brownfield_scan

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
        "gui": gui, "ts": terminal_session, "reg": session_registry,
        "eh": effort_history, "sessions": sessions, "summ": summarizer,
        "rnd": rnd_registry, "bscan": brownfield_scan, "repo": repo,
        "pid": proj["id"], "wbase": wbase, "data": data,
    }
    yield bundle
    try:
        import pty_manager
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


def _attach_doc_to_session(eh, repo, pid, sid, lane="planning", n=0):
    """Give a LIVE session a member document of its own.

    Without this, a freshly started session owns no documents, so the seed's
    grounding corpus is member TITLES alone and `summarize_session` correctly
    short-circuits WITHOUT calling the model (2026-07-26 hardening) — which
    would make these scheduling tests assert against a summary that is never
    generated. Attaching a real doc keeps them testing what they claim to.
    """
    rel = f"{lane}/live-{sid[:8]}-{n}/NOTES.md"
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "# Session notes\n\n## What was done\n"
        "Grouped trio efforts into sessions and cached validated summaries "
        "so the surface is a truthful memory of the work.\n",
        encoding="utf-8")
    eh.record_effort(
        repo, pid, lane, eh.discovered_job_id(lane, rel), skill="Crucible",
        extra={"source": eh.SOURCE_DISCOVERED, "kind": "plan-doc",
               "title": "Session notes", "artifact_path": rel,
               "status": "imported", "session_id": sid})
    return rel


def _add_plan_session(eh, sessions, repo, pid, plan_dir="planning/rnd-x",
                      created_at=2000.0):
    """Record a discovered planning session with REAL member docs on disk so the
    grounding corpus exists (and handoff discovery finds a MASTER+IMPL set). Returns
    the effort-history session dict."""
    master_rel = f"{plan_dir}/MASTER-PLAN.md"
    impl_rel = f"{plan_dir}/IMPLEMENTATION-PLAN.md"
    log_rel = f"{plan_dir}/EXECUTION-LOG.md"
    bodies = {
        master_rel: ("# Master Plan\n\n## North Star\n"
                     "Make the surface a truthful memory of trio work.\n\n"
                     "## Key decisions\nGroup efforts into sessions and cache "
                     "validated summaries.\n"),
        impl_rel: ("# Implementation Plan\n\n## Goal\nRender the most-recent "
                   "session with an expander.\n"),
        log_rel: "# Execution Log\n",
    }
    for rel, body in bodies.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "plan docs")
    specs = [(master_rel, "Master Plan"), (impl_rel, "Implementation Plan"),
             (log_rel, "Execution Log")]
    for i, (rel, title) in enumerate(specs):
        jid = eh.discovered_job_id("planning", rel)
        eh.record_effort(
            repo, pid, "planning", jid, skill="Crucible",
            extra={"source": eh.SOURCE_DISCOVERED, "kind": "plan-doc",
                   "title": title, "artifact_path": rel, "status": "imported",
                   "created_at": created_at + i * 0.001})
    for s in sessions.list_sessions(repo, pid, "planning"):
        rels = [m.get("artifact_path", "") for m in s.get("member_files", [])]
        if any("rnd-x" in r for r in rels):
            return s
    raise AssertionError("expected a discovered planning session")


def _free_server(gui):
    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, port, t


def _post(port, path, payload):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=_json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status, _json.loads(r.read().decode("utf-8"))


def _wait_cache(summ, repo, pid, lane, sid, deadline_s=30):
    """Poll for a cached session summary (the background daemon lands it)."""
    store_lane = summ._eh._resolve_subdir(lane)
    deadline = time.time() + deadline_s
    while time.time() < deadline:
        c = summ.load_cached(repo, pid, store_lane, sid)
        if c is not None:
            return c
        time.sleep(0.1)
    return None


# ════════════════════════════════════════════════════════════════════════════
# (1) KILL → background summary scheduled, non-blocking, idempotent
# ════════════════════════════════════════════════════════════════════════════

def test_kill_schedules_one_background_summary_non_blocking(env, monkeypatch):
    """Killing a session schedules a background summarize_session (the kill HTTP
    response returns promptly, never waiting on the model) and, once landed, the
    cache is present. A second finish is idempotent (no re-run / no error)."""
    ts, eh, sessions, summ, repo, pid, gui = (
        env["ts"], env["eh"], env["sessions"], env["summ"], env["repo"],
        env["pid"], env["gui"])
    # A planning session that maps onto a discovered effort-history session so the
    # summarizer has real member docs to ground claims against.
    plan_session = _add_plan_session(eh, sessions, repo, pid)
    sid = plan_session["session_id"]
    # Start a live PTY session under the SAME session_id is not possible (start
    # mints a new id) — instead start a fresh planning session and use its id; the
    # summary still grounds against the lane's discovered docs via the seed corpus.
    live = ts.start_session(pid, "planning", backend="claude")
    live_sid = live["session_id"]
    _attach_doc_to_session(eh, repo, pid, live_sid)

    monkeypatch.setenv(
        "STUB_STREAMJSON_CLAIMS",
        "North Star: cache validated summaries for each session.")

    # Spy: count how many times summarize_session is invoked through the trigger.
    calls = []
    real_summarize = summ.summarize_session

    def _spy(folder, project_id, lane, session, force=False):
        calls.append((project_id, lane,
                      (session or {}).get("session_id"), force))
        return real_summarize(folder, project_id, lane, session, force=force)

    monkeypatch.setattr(summ, "summarize_session", _spy)

    srv, port, t = _free_server(gui)
    try:
        t0 = time.time()
        status, data = _post(port, "/api/rnd/term_kill", {"session": live_sid})
        elapsed = time.time() - t0
        assert status == 200 and data["ok"] is True
        # NON-BLOCKING: the response is not gated on a model run.
        assert elapsed < 10, f"kill response blocked ({elapsed:.1f}s)"

        # The killed session is DONE.
        assert env["reg"].get_session(live_sid)["status"] == \
            env["reg"].STATUS_DONE

        # Exactly ONE background summary was scheduled FOR THE KILLED SESSION and
        # the cache lands.
        cached = _wait_cache(summ, repo, pid, "planning", live_sid)
        assert cached is not None, "kill did not schedule a session summary"
        kill_calls = [c for c in calls if c[2] == live_sid]
        assert len(kill_calls) == 1, \
            f"expected exactly one summary for the killed session, got {kill_calls}"

        # IDEMPOTENT: a second finish for the now-cached, DONE session does NOT
        # schedule another model run (the cache is honored). We invoke the finish
        # hook directly (the session is already terminal, so a real second kill is
        # a 404 — the hook is what must stay idempotent).
        before = len(kill_calls)
        gui._trigger_session_summary_on_finish(pid, "planning", live_sid)
        time.sleep(0.5)
        kill_calls2 = [c for c in calls if c[2] == live_sid]
        assert len(kill_calls2) == before, \
            "a second finish re-ran the model for an already-cached session"
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


def test_kill_handler_returns_even_if_summary_trigger_raises(env, monkeypatch):
    """A failure inside the summary scheduling must NEVER break the kill response
    (best-effort wiring). Force the trigger to raise and assert kill still 200s."""
    ts, gui = env["ts"], env["gui"]
    live = ts.start_session(env["pid"], "research", backend="claude")
    sid = live["session_id"]

    def _boom(*a, **k):
        raise RuntimeError("scheduling blew up")

    monkeypatch.setattr(gui, "_trigger_session_summary_on_finish", _boom)

    srv, port, t = _free_server(gui)
    try:
        status, data = _post(port, "/api/rnd/term_kill", {"session": sid})
        assert status == 200 and data["ok"] is True, \
            "a summary-scheduling error broke the kill response"
        assert env["reg"].get_session(sid)["status"] == env["reg"].STATUS_DONE
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


# ════════════════════════════════════════════════════════════════════════════
# (2) FAILED generation leaves NO cache (retryable, never poisoned)
# ════════════════════════════════════════════════════════════════════════════

def test_failed_generation_leaves_no_cache(env, monkeypatch):
    """When the runner FAILS (non-zero exit), the finish hook must NOT cache a
    poisoned summary — load_cached stays None so a later run/Regenerate retries."""
    ts, eh, sessions, summ, repo, pid, gui = (
        env["ts"], env["eh"], env["sessions"], env["summ"], env["repo"],
        env["pid"], env["gui"])
    _add_plan_session(eh, sessions, repo, pid)
    live = ts.start_session(pid, "planning", backend="claude")
    live_sid = live["session_id"]
    _attach_doc_to_session(eh, repo, pid, live_sid)

    # Point the runner at a stub that exits non-zero → RUN_FAILED → no cache.
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAILRUNNER}")

    srv, port, t = _free_server(gui)
    try:
        status, data = _post(port, "/api/rnd/term_kill", {"session": live_sid})
        assert status == 200 and data["ok"] is True
        # Give the background daemon time to run-and-fail.
        deadline = time.time() + 8
        store_lane = summ._eh._resolve_subdir("planning")
        while time.time() < deadline:
            if summ.load_cached(repo, pid, store_lane, live_sid) is not None:
                break
            time.sleep(0.1)
        assert summ.load_cached(repo, pid, store_lane, live_sid) is None, \
            "a FAILED generation poisoned the cache (must be retryable)"
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


# ════════════════════════════════════════════════════════════════════════════
# (3) session_blurb — short / clean / honest-absent / no model call
# ════════════════════════════════════════════════════════════════════════════

def test_session_blurb_short_clean_from_cache(env):
    """With a cached summary, session_blurb returns a SHORT, CLEAN one-liner (no
    markdown / decorative glyphs, within the cap) from the most informative short
    field (first grounded claim)."""
    summ, repo, pid = env["summ"], env["repo"], env["pid"]
    store_lane = summ._eh._resolve_subdir("planning")
    sid = "sess-blurb-1"
    # Seed a cache directly (no model call) whose first claim carries markdown +
    # decorative glyphs — the blurb must come out clean and capped.
    summ._write_cache(repo, pid, store_lane, sid, {
        "session_id": sid, "lane": "planning",
        "title": "Planning session",
        "claims": ["**Goal:** ship the integrated board — handle ## edge "
                   "`cases` ✓ and many more words that push beyond the tile cap "
                   "for sure indeed"],
        "what_was_asked": "plan the board",
        "member_links": [], "when_run": "", "north_star": "",
        "skill": "Crucible", "prompts": [], "actions": [],
    })

    blurb = summ.session_blurb(repo, pid, "planning", sid, max_chars=64)
    assert blurb, "expected a non-empty blurb from a cached summary"
    # CLEAN: none of the markdown / decorative glyphs survive.
    for bad in ("**", "##", "`", "✓", "—"):
        assert bad not in blurb, f"blurb still carries {bad!r}: {blurb!r}"
    # SHORT: within the cap (allowing the 1-char ellipsis).
    assert len(blurb) <= 64 + 1, f"blurb exceeds the cap: {blurb!r} ({len(blurb)})"
    assert blurb.endswith("…"), "a too-long source should be word-truncated"
    # The readable content survived the strip.
    assert "ship the integrated board" in blurb.lower()


def test_session_blurb_prefers_asked_then_title(env):
    """With no grounded claims, session_blurb falls back to what_was_asked, then
    title — still clean, never blank when there is real short text."""
    summ, repo, pid = env["summ"], env["repo"], env["pid"]
    store_lane = summ._eh._resolve_subdir("research")
    sid = "sess-blurb-2"
    summ._write_cache(repo, pid, store_lane, sid, {
        "session_id": sid, "lane": "research", "title": "Research session",
        "claims": [], "what_was_asked": "Investigate **the** market sizing",
        "member_links": [], "when_run": "", "north_star": "",
        "skill": "researchPrime", "prompts": [], "actions": [],
        "no_grounded_claims": True,
    })
    blurb = summ.session_blurb(repo, pid, "research", sid, max_chars=64)
    assert blurb == "Investigate the market sizing", blurb


def test_session_blurb_honest_empty_when_uncached(env, monkeypatch):
    """No cache → honest ``""`` (not blank garbage), and NO model call is made
    (pure cache read)."""
    summ, repo, pid = env["summ"], env["repo"], env["pid"]

    # Hard guard: any attempt to run the model from the blurb path is a failure.
    def _no_model(*a, **k):
        raise AssertionError("session_blurb must not run the model")

    monkeypatch.setattr(summ, "summarize_session", _no_model)
    monkeypatch.setattr(summ, "_run_model_once", _no_model)

    blurb = summ.session_blurb(repo, pid, "planning", "never-cached", max_chars=64)
    assert blurb == "", f"uncached blurb must be honest empty, got {blurb!r}"


# ════════════════════════════════════════════════════════════════════════════
# (4) finish_to_build + reconcile-dead also schedule a summary
# ════════════════════════════════════════════════════════════════════════════

def test_finish_to_build_schedules_summary_for_planning_session(env, monkeypatch):
    """finish_to_build marks the planning session DONE and schedules a background
    summary for it (end-to-end: the cache lands)."""
    ts, eh, sessions, summ, repo, pid, gui = (
        env["ts"], env["eh"], env["sessions"], env["summ"], env["repo"],
        env["pid"], env["gui"])
    _add_plan_session(eh, sessions, repo, pid)
    plan = ts.start_session(pid, "planning", backend="claude")
    psid = plan["session_id"]
    _attach_doc_to_session(eh, repo, pid, psid)
    monkeypatch.setenv("STUB_STREAMJSON_CLAIMS",
                       "Cache validated summaries for each session.")

    srv, port, t = _free_server(gui)
    bsid = None
    try:
        status, data = _post(port, "/api/rnd/finish_to_build",
                             {"project_id": pid, "session": psid})
        assert status == 200 and data["ok"] is True
        if data.get("auto_build"):
            bsid = data["auto_build"]["session_id"]
        # The finished planning session gets a background summary.
        cached = _wait_cache(summ, repo, pid, "planning", psid)
        assert cached is not None, \
            "finish_to_build did not schedule a planning-session summary"
    finally:
        if bsid:
            try:
                ts.kill(bsid)
            except Exception:
                pass
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


def test_reconcile_dead_schedules_summary(env, monkeypatch):
    """A planning session whose PTY died is re-statused DONE on the term_sessions
    refresh AND gets a background summary scheduled (the cache lands)."""
    ts, eh, sessions, summ, repo, pid, gui = (
        env["ts"], env["eh"], env["sessions"], env["summ"], env["repo"],
        env["pid"], env["gui"])
    import pty_manager
    _add_plan_session(eh, sessions, repo, pid)
    plan = ts.start_session(pid, "planning", backend="claude")
    psid = plan["session_id"]
    _attach_doc_to_session(eh, repo, pid, psid)
    monkeypatch.setenv("STUB_STREAMJSON_CLAIMS",
                       "Cache validated summaries for each session.")

    # Simulate the PTY dying so reconcile (driven by the now-empty live set) marks
    # the planning session DONE → schedules the summary.
    pty_manager._reset_live_table_for_tests()
    assert pty_manager.live_sessions() == []

    srv, port, t = _free_server(gui)
    bsid = None
    try:
        url = (f"http://127.0.0.1:{port}/api/rnd/term_sessions"
               f"?project_id={pid}")
        with urllib.request.urlopen(url, timeout=20) as r:
            data = _json.loads(r.read().decode("utf-8"))
        assert data["ok"] is True
        assert env["reg"].get_session(psid)["status"] == env["reg"].STATUS_DONE
        builds = [s for s in env["reg"].list_sessions(project_id=pid)
                  if s.get("lane") == "build"]
        if builds:
            bsid = builds[0]["session_id"]

        cached = _wait_cache(summ, repo, pid, "planning", psid)
        assert cached is not None, \
            "reconcile-dead did not schedule a planning-session summary"
    finally:
        if bsid:
            try:
                ts.kill(bsid)
            except Exception:
                pass
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


def test_finish_hooks_wired_in_handlers(env):
    """Source-level guard: the three finish transitions all call the Wave-2 finish
    hook (best-effort) so the wiring can't silently regress."""
    import inspect
    gui = env["gui"]
    # After the rearch W7/C2 route migration the finish transitions moved OUT of
    # the inline do_POST/do_GET chains into their own module-level migrated
    # handlers. The invariant is unchanged: every finish transition still calls the
    # Wave-2 finish hook (best-effort) so the wiring can't silently regress.
    kill_src = inspect.getsource(gui.handle_term_kill)
    finish_src = inspect.getsource(gui.handle_finish_to_build)
    sessions_src = inspect.getsource(gui.handle_term_sessions)
    # The hook is referenced from the kill + finish_to_build POST handlers.
    assert "_trigger_session_summary_on_finish(" in kill_src, \
        "expected the finish hook in the term_kill handler"
    assert "_trigger_session_summary_on_finish(" in finish_src, \
        "expected the finish hook in the finish_to_build handler"
    # And from the reconcile-dead term_sessions (GET) handler.
    assert "_trigger_session_summary_on_finish(" in sessions_src, \
        "expected the finish hook in the reconcile-dead term_sessions path"
