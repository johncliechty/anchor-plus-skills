"""v6 Wave 6 — auto advance planning → build (gated on a real plan).

When a PLANNING session reaches a terminal/DONE state via a DELIBERATE hard-kill
or a RECONCILE-DEAD transition (NOT a keep-alive close, NOT process self-exit),
and a real MASTER+IMPL plan set is discoverable, the cockpit AUTOMATICALLY opens
exactly ONE linked build session: ``parent_session_id`` == the planning session,
inherited ``chain_id``, a primed ``HANDOFF.md`` referencing the real plan docs
(captured BEFORE the planning worktree is reaped), and a recorded stage edge.

Locked semantics (MASTER-PLAN Risks R1/R2, IMPLEMENTATION-PLAN Wave 6):
  - fires ONLY on planning + terminal/DONE (kill / reconcile-dead);
  - exactly ONE build per planning session — IDEMPOTENT on ``parent_session_id``
    (a second reconcile/kill never duplicates);
  - no plan set ⇒ no advance;
  - works with NO upstream research (planning is the chain root);
  - a keep-alive CLOSE never triggers an advance.

Hermetic: NO real claude/gemini, NO real PTY — ``ANCHOR_PTY_BACKEND=stub``, a
temp git repo for the worktree, a tmp data dir + tmp worktree base. NEVER binds
``:8777``; NEVER a worktree off the real ``C:\\dev\\Anchor`` repo.
"""
import importlib
import re
import subprocess
import threading
from html.parser import HTMLParser
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
    """Tmp data dir + tmp worktree base + stub PTY + the fake runner + a temp git
    repo + a registered project. Reloads the full stack against the isolated env
    so start_session creates a real worktree off the TEMP repo (never C:\\dev)."""
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
    import anchor_gui
    gui = importlib.reload(anchor_gui)

    import effort_history
    import handoff
    import terminal_session
    import session_registry
    import anchor_marker
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
        "gui": gui, "ts": terminal_session, "reg": session_registry,
        "handoff": handoff, "eh": effort_history, "marker": anchor_marker,
        "rnd": rnd_registry, "repo": repo, "pid": proj["id"],
        "wbase": wbase, "data": data,
    }
    yield bundle
    try:
        import pty_manager
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


def _add_plan_session(eh, repo, pid, plan_dir="planning/rnd-x",
                      created_at=2000.0):
    """Record a discovered planning session (one parent dir = one session) with a
    REAL MASTER+IMPL plan set committed into the repo so discovery finds it."""
    master_rel = f"{plan_dir}/MASTER-PLAN.md"
    impl_rel = f"{plan_dir}/IMPLEMENTATION-PLAN.md"
    log_rel = f"{plan_dir}/EXECUTION-LOG.md"
    for rel, body in [(master_rel, "# Master Plan\n"),
                      (impl_rel, "# Implementation Plan\n"),
                      (log_rel, "# Execution Log\n")]:
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    specs = [(master_rel, "Master Plan"), (impl_rel, "Implementation Plan"),
             (log_rel, "Execution Log")]
    for i, (rel, title) in enumerate(specs):
        jid = eh.discovered_job_id("planning", rel)
        eh.record_effort(
            repo, pid, "planning", jid, skill="Crucible",
            extra={"source": eh.SOURCE_DISCOVERED, "kind": "plan-doc",
                   "title": title, "artifact_path": rel, "status": "imported",
                   "created_at": created_at + i * 0.001})
    return {"master_rel": master_rel, "impl_rel": impl_rel, "log_rel": log_rel}


# ════════════════════════════════════════════════════════════════════════════
# (A) BACKEND — the kill / reconcile-dead trigger semantics
# ════════════════════════════════════════════════════════════════════════════

def test_kill_planning_with_plan_set_auto_starts_one_primed_linked_build(env):
    """Hard-killing a planning session WITH a plan set auto-starts EXACTLY ONE
    build session with parent==planning, inherited chain, a primed HANDOFF.md
    referencing the REAL plan docs (prime-before-reap), and a recorded edge."""
    ts, reg, eh, repo, pid = (env["ts"], env["reg"], env["eh"],
                              env["repo"], env["pid"])
    ho = env["handoff"]
    plan = _add_plan_session(eh, repo, pid)

    # Start a managed PLANNING terminal session (the one we will hard-kill).
    plan_sess = ts.start_session(pid, "planning", backend="claude")
    psid = plan_sess["session_id"]

    # Capture the plan set BEFORE reap (mirrors the term_kill handler), kill the
    # planning session (→ STATUS_DONE + reaps its worktree), then auto-advance.
    pre = ts.capture_plan_set(pid, psid)
    assert pre is not None and pre["plan_dir"] == "planning/rnd-x"
    ts.kill(psid)
    assert reg.get_session(psid)["status"] in reg.TERMINAL_STATUSES

    build = ts.auto_advance_planning_to_build(pid, psid, plan_set=pre)
    assert build is not None, "a plan set was present — a build must auto-open"
    bsid = build["session_id"]

    # Exactly ONE build, parented + chained to the planning session.
    builds = [s for s in reg.list_sessions(project_id=pid)
              if s.get("lane") == "build"]
    assert len(builds) == 1
    assert build["parent_session_id"] == psid
    assert build["chain_id"] == plan_sess["chain_id"]
    members = reg.chain_members(plan_sess["chain_id"])
    assert psid in [m["session_id"] for m in members]
    assert bsid in [m["session_id"] for m in members]

    # The build worktree has a primed HANDOFF.md referencing the REAL plan docs —
    # proving prime-before-reap (the build worktree is fresh + never reaped).
    wt = Path(build["worktree_path"])
    assert str(env["wbase"]) in str(wt) and str(repo) not in str(wt)
    hf = wt / ho.HANDOFF_FILENAME
    assert hf.exists(), "build worktree was not primed with HANDOFF.md"
    text = hf.read_text(encoding="utf-8")
    assert plan["master_rel"] in text
    assert plan["impl_rel"] in text

    # The plan→build stage edge was recorded (rescan-durable).
    links = ho.list_stage_links(repo, pid)
    assert any(l["from_session_id"] == psid and l["to_session_id"] == bsid
               and l["kind"] == "plan->build" for l in links)

    ts.kill(bsid)


def test_idempotent_no_duplicate_build_on_second_advance(env):
    """A second reconcile/kill-style advance for the SAME planning session must
    NOT create a duplicate build (idempotent on parent_session_id)."""
    ts, reg, eh, repo, pid = (env["ts"], env["reg"], env["eh"],
                              env["repo"], env["pid"])
    _add_plan_session(eh, repo, pid)
    plan_sess = ts.start_session(pid, "planning", backend="claude")
    psid = plan_sess["session_id"]
    ts.kill(psid)

    first = ts.auto_advance_planning_to_build(pid, psid)
    assert first is not None
    # Re-run (simulating a second reconcile pass / restart) → NO new build.
    second = ts.auto_advance_planning_to_build(pid, psid)
    assert second is None, "a second advance must not duplicate the build"
    builds = [s for s in reg.list_sessions(project_id=pid)
              if s.get("lane") == "build"]
    assert len(builds) == 1
    ts.kill(first["session_id"])


def test_no_plan_set_no_build(env):
    """A planning session with NO discoverable plan set opens NO build."""
    ts, reg, pid = env["ts"], env["reg"], env["pid"]
    plan_sess = ts.start_session(pid, "planning", backend="claude")
    psid = plan_sess["session_id"]
    ts.kill(psid)
    out = ts.auto_advance_planning_to_build(pid, psid)
    assert out is None, "no plan set ⇒ no advance"
    assert [s for s in reg.list_sessions(project_id=pid)
            if s.get("lane") == "build"] == []


def test_no_upstream_research_planning_is_chain_root(env):
    """The auto-advance works when planning is the CHAIN ROOT (no research)."""
    ts, reg, eh, repo, pid = (env["ts"], env["reg"], env["eh"],
                              env["repo"], env["pid"])
    _add_plan_session(eh, repo, pid)
    # Planning started with NO parent → it is its own chain root.
    plan_sess = ts.start_session(pid, "planning", backend="claude")
    psid = plan_sess["session_id"]
    assert plan_sess["parent_session_id"] == ""
    assert plan_sess["chain_id"] == psid
    ts.kill(psid)
    build = ts.auto_advance_planning_to_build(pid, psid)
    assert build is not None
    assert build["parent_session_id"] == psid
    assert build["chain_id"] == psid  # joins the planning-rooted chain
    ts.kill(build["session_id"])


def test_not_done_planning_does_not_advance(env):
    """A LIVE (not terminal/DONE) planning session never advances — the gate is
    the DONE transition, not merely being a planning session with a plan set."""
    ts, reg, eh, repo, pid = (env["ts"], env["reg"], env["eh"],
                              env["repo"], env["pid"])
    _add_plan_session(eh, repo, pid)
    plan_sess = ts.start_session(pid, "planning", backend="claude")
    psid = plan_sess["session_id"]
    assert reg.get_session(psid)["status"] == reg.STATUS_RUNNING
    # NOT killed → still RUNNING → no advance.
    out = ts.auto_advance_planning_to_build(pid, psid)
    assert out is None
    assert [s for s in reg.list_sessions(project_id=pid)
            if s.get("lane") == "build"] == []
    ts.kill(psid)


def test_non_planning_done_session_does_not_advance(env):
    """A DONE session in a NON-planning lane (e.g. research) does not advance."""
    ts, reg, eh, repo, pid = (env["ts"], env["reg"], env["eh"],
                              env["repo"], env["pid"])
    _add_plan_session(eh, repo, pid)
    rsess = ts.start_session(pid, "research", backend="claude")
    rsid = rsess["session_id"]
    ts.kill(rsid)
    assert ts.auto_advance_planning_to_build(pid, rsid) is None
    assert [s for s in reg.list_sessions(project_id=pid)
            if s.get("lane") == "build"] == []


# ── reconcile-dead path ──────────────────────────────────────────────────────

def test_reconcile_dead_planning_advances_and_is_idempotent(env):
    """reconcile_and_advance: a planning session whose process is gone is marked
    DONE by reconcile and auto-advances to ONE build; a second reconcile does not
    duplicate it."""
    ts, reg, eh, repo, pid = (env["ts"], env["reg"], env["eh"],
                              env["repo"], env["pid"])
    _add_plan_session(eh, repo, pid)
    plan_sess = ts.start_session(pid, "planning", backend="claude")
    psid = plan_sess["session_id"]
    # No live ids → the running planning session is stale → reconcile marks it
    # DONE → auto-advance fires.
    out1 = ts.reconcile_and_advance(live_session_ids=[])
    assert psid in out1["reconcile"]["marked"]
    assert reg.get_session(psid)["status"] == reg.STATUS_DONE
    assert len(out1["auto_builds"]) == 1
    build = out1["auto_builds"][0]
    assert build["parent_session_id"] == psid

    # A SECOND reconcile pass must not create a duplicate build (idempotent). The
    # build itself is RUNNING; exclude it from the "live" set so reconcile would
    # try to re-status it, but the planning session is already DONE (not running)
    # so it is not re-marked, and even if re-advanced the idempotency holds.
    out2 = ts.reconcile_and_advance(live_session_ids=[build["session_id"]])
    builds = [s for s in reg.list_sessions(project_id=pid)
              if s.get("lane") == "build"]
    assert len(builds) == 1, "reconcile re-run duplicated the build"
    assert out2["auto_builds"] == []
    ts.kill(build["session_id"])


# ── NEGATIVE: a keep-alive close never advances ──────────────────────────────

def test_close_does_not_advance(env):
    """A keep-alive CLOSE is a pure client-side DOM teardown — it hits NO backend,
    so no advance is even attempted: the planning session stays RUNNING and no
    build appears. (close → closePanel never POSTs term_kill; auto-advance is
    invoked ONLY from kill/reconcile, never from close.)"""
    ts, reg, eh, repo, pid = (env["ts"], env["reg"], env["eh"],
                              env["repo"], env["pid"])
    _add_plan_session(eh, repo, pid)
    plan_sess = ts.start_session(pid, "planning", backend="claude")
    psid = plan_sess["session_id"]
    # Simulate close-to-tile: NOTHING is called server-side. The session is still
    # RUNNING and resolvable, and auto_advance (which requires DONE) is a no-op
    # even if it WERE called.
    assert reg.get_session(psid)["status"] == reg.STATUS_RUNNING
    assert ts.auto_advance_planning_to_build(pid, psid) is None
    assert [s for s in reg.list_sessions(project_id=pid)
            if s.get("lane") == "build"] == []
    # And the closePanel JS path never references term_kill / advance.
    gui = env["gui"]
    js = "\n".join(re.findall(r"<script[^>]*>([\s\S]*?)</script>",
                              gui.render_project_window_html(pid)))
    cp = re.search(r"function closePanel\(sessionId\)\s*\{([\s\S]*?)\n\}", js)
    assert cp, "closePanel not found"
    body = cp.group(1)
    assert "term_kill" not in body
    assert "auto_build" not in body
    assert "advance_session" not in body
    ts.kill(psid)


# ════════════════════════════════════════════════════════════════════════════
# (B) HTTP — term_kill returns auto_build for a planning kill
# ════════════════════════════════════════════════════════════════════════════

def _free_server(gui):
    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, port, t


def test_http_term_kill_planning_returns_auto_build(env):
    """POST /api/rnd/term_kill on a PLANNING session with a plan set returns an
    ``auto_build`` record; the build worktree is primed; the edge recorded."""
    import json as _json
    import urllib.request as _req
    ts, eh, repo, pid, gui = (env["ts"], env["eh"], env["repo"], env["pid"],
                              env["gui"])
    ho = env["handoff"]
    _add_plan_session(eh, repo, pid)
    plan_sess = ts.start_session(pid, "planning", backend="claude")
    psid = plan_sess["session_id"]

    srv, port, t = _free_server(gui)
    bsid = None
    try:
        payload = _json.dumps({"session": psid}).encode("utf-8")
        req = _req.Request(f"http://127.0.0.1:{port}/api/rnd/term_kill",
                           data=payload,
                           headers={"Content-Type": "application/json"},
                           method="POST")
        with _req.urlopen(req, timeout=20) as r:
            data = _json.loads(r.read().decode("utf-8"))
        assert data["ok"] is True
        assert data.get("auto_build"), "term_kill did not surface auto_build"
        ab = data["auto_build"]
        bsid = ab["session_id"]
        assert ab["parent_session_id"] == psid
        assert ab["lane"] == "build"
        wt = Path(ab["worktree_path"])
        assert (wt / ho.HANDOFF_FILENAME).exists()
        assert any(l["to_session_id"] == bsid and l["kind"] == "plan->build"
                   for l in ho.list_stage_links(repo, pid))
    finally:
        if bsid:
            try:
                ts.kill(bsid)
            except Exception:
                pass
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


def test_http_term_kill_nonplanning_no_auto_build(env):
    """Killing a NON-planning (research) session never carries an auto_build."""
    import json as _json
    import urllib.request as _req
    ts, eh, repo, pid, gui = (env["ts"], env["eh"], env["repo"], env["pid"],
                              env["gui"])
    _add_plan_session(eh, repo, pid)
    rsess = ts.start_session(pid, "research", backend="claude")
    rsid = rsess["session_id"]
    srv, port, t = _free_server(gui)
    try:
        payload = _json.dumps({"session": rsid}).encode("utf-8")
        req = _req.Request(f"http://127.0.0.1:{port}/api/rnd/term_kill",
                           data=payload,
                           headers={"Content-Type": "application/json"},
                           method="POST")
        with _req.urlopen(req, timeout=20) as r:
            data = _json.loads(r.read().decode("utf-8"))
        assert data["ok"] is True
        assert data.get("auto_build") is None
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


# ════════════════════════════════════════════════════════════════════════════
# (C) RENDERED-DOM / JS-source assertions (un-gameable: positive + negative)
# ════════════════════════════════════════════════════════════════════════════

def _js(html):
    return "\n".join(re.findall(r"<script[^>]*>([\s\S]*?)</script>", html))


def test_killpanel_surfaces_auto_build_in_js(env):
    """The killPanel JS reads ``data.auto_build`` and mints the new tile (+ note)
    via _addAutoBuildTile; closePanel does NOT (the trigger is kill-only)."""
    gui, pid = env["gui"], env["pid"]
    js = _js(gui.render_project_window_html(pid))
    kp = re.search(r"async function killPanel\(sessionId\)\s*\{([\s\S]*?)\n\}", js)
    assert kp, "killPanel not found"
    kbody = kp.group(1)
    # POSITIVE: killPanel consumes auto_build and mints a tile.
    assert "data.auto_build" in kbody
    assert "_addAutoBuildTile(" in kbody
    # The tile minter + note helper exist and reference the panel/bar.
    assert "function _addAutoBuildTile(" in js
    assert "function _flashAutoBuildNote(" in js
    assert "openPanel(sid)" in js
    assert "autobuild-note" in js
    # NEGATIVE: closePanel must not touch auto_build (kill-only trigger).
    cp = re.search(r"function closePanel\(sessionId\)\s*\{([\s\S]*?)\n\}", js)
    assert cp and "auto_build" not in cp.group(1)


# ════════════════════════════════════════════════════════════════════════════
# (D) REAL Playwright + Chromium — kill planning → auto build tile + note
# ════════════════════════════════════════════════════════════════════════════

def test_playwright_kill_planning_opens_build_tile_with_note(env):
    """End-to-end in a real browser: open a PLANNING session panel, hard-kill it
    (accept the confirm), and assert a NEW BUILD tile appears (linked into the
    chain) plus the "auto-opened … from this plan" note, with no JS console
    errors. Saves _devtest/wave6_autobuild.png for orchestrator review."""
    pytest.importorskip("playwright.sync_api")
    ts, eh, repo, pid, gui = (env["ts"], env["eh"], env["repo"], env["pid"],
                              env["gui"])
    _add_plan_session(eh, repo, pid)
    plan_sess = ts.start_session(pid, "planning", backend="claude")
    psid = plan_sess["session_id"]

    srv, port, t = _free_server(gui)
    base = f"http://127.0.0.1:{port}"
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page()
            errors = []
            pg.on("console",
                  lambda m: errors.append(m.text) if m.type == "error" else None)
            pg.on("dialog", lambda d: d.accept())  # accept the kill confirm()
            pg.goto(f"{base}/project/{pid}", wait_until="networkidle")
            from tests.ui_helpers import expand_workbench
            expand_workbench(pg)  # the Workbench tile now opens collapsed

            chip_sel = '#sessionBar .live-chip[data-session="%s"]' % psid
            pg.wait_for_selector(chip_sel, timeout=8000)
            pg.click(chip_sel)
            pg.wait_for_selector("#panelStack .panel", timeout=5000)
            # Hard-kill the planning panel. (W6 control-unification renamed the old
            # 🗑 .hardkill button to the single destructive 🪦 Kill→Boneyard
            # .killbone control.)
            pg.click("#panelStack .panel .panelbtn.killbone")
            # The planning chip goes away …
            pg.wait_for_function(
                "document.querySelectorAll('%s').length === 0" % chip_sel,
                timeout=6000)
            # … and a NEW BUILD tile appears (a different, live chip whose lane is
            # build), plus the auto-opened note.
            pg.wait_for_selector('#sessionBar .live-chip[data-lane="build"]',
                                 timeout=8000)
            build_chips = pg.eval_on_selector_all(
                '#sessionBar .live-chip[data-lane="build"]',
                "els => els.map(e => e.getAttribute('data-session'))")
            assert build_chips, "no auto-opened build tile appeared"
            bsid = build_chips[0]
            assert bsid != psid
            pg.wait_for_selector(".autobuild-note", timeout=6000)
            note_txt = pg.eval_on_selector(".autobuild-note", "e => e.textContent")
            assert "auto-opened" in note_txt and "plan" in note_txt

            Path("_devtest").mkdir(exist_ok=True)
            pg.screenshot(path="_devtest/wave6_autobuild.png", full_page=True)
            assert not errors, f"JS console errors: {errors}"
            # Backend linkage holds: the build is parented to the planning session.
            import session_registry as reg
            brec = reg.get_session(bsid)
            assert brec["parent_session_id"] == psid
            assert brec["chain_id"] == plan_sess["chain_id"]
            b.close()
            try:
                ts.kill(bsid)
            except Exception:
                pass
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=5)
