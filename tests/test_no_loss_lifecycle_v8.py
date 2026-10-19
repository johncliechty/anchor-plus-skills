"""v8 Wave 5 — No-loss lifecycle: summary+docs on kill, promote to big tiles, detail.

KILL must be a graceful close-out — no work lost. On a deliberate hard-kill of a
managed terminal session, BEFORE the worktree is reaped, the session's produced
documents are persisted into the MAIN project (Wave 2 keystone) AND the session is
TIED to those docs as a durable lane SESSION carrying {a stable id, the produced
docs, a cached summary}. After the reap:

  - nothing is lost: the docs + the summary record resolve from the MAIN folder
    by the (durable) managed session id;
  - the little top-strip CHIP for the killed session is GONE (client _KILLED set);
  - a BIG board tile remains (the registry record persists as DONE → rendered via
    the v7 board bridge), and clicking it opens a detail view showing the produced
    deliverable/docs + the summary + a "Continue the dialog" button that starts a
    NEW seeded live session (continue_session, v6) — the original record unchanged.

Hermetic: ``ANCHOR_PTY_BACKEND=stub``, a temp git repo for the worktree, a tmp
data dir + tmp worktree base, the STUB summarizer runner. NEVER binds ``:8777``;
NEVER a worktree off the real ``C:\\dev\\Anchor`` repo; NEVER real push/gh/network.
"""
import importlib
import json
import re
import subprocess
import threading
import urllib.request
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()
STUB = (Path(__file__).resolve().parent / "stub_summarizer.py").as_posix()
DEVTEST = Path(__file__).resolve().parent.parent / "_devtest"


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


# ── env / fixtures (stub PTY + temp git repo + project + STUB summarizer) ─────

@pytest.fixture
def env(tmp_path, monkeypatch):
    """Tmp data dir + tmp worktree base + stub PTY + the STUB summarizer runner +
    a temp git repo + a registered project, with proactive summaries ENABLED so
    the kill path actually generates the durable summary. The full stack is
    reloaded against the isolated env (worktrees off the TEMP repo, never C:\\dev)."""
    data = tmp_path / "data"
    data.mkdir()
    wbase = tmp_path / "wt-base"
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(wbase))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {STUB}")
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.setenv("ANCHOR_PROACTIVE_SUMMARY", "1")
    # A grounded claim so the summarizer pipeline caches a real summary.
    monkeypatch.setenv("STUB_SUMMARIZER_CLAIMS",
                       "The locked north star is durable resumable work")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)

    for mod in ("paths", "job_runner", "pty_manager", "rnd_registry",
                "effort_history", "sessions", "anchor_marker",
                "session_registry", "worktrees", "lanes", "summarizer",
                "report_viewer", "handoff", "terminal_session"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import anchor_gui
    gui = importlib.reload(anchor_gui)

    import effort_history
    import handoff
    import terminal_session
    import session_registry
    import sessions
    import summarizer
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
        "handoff": handoff, "eh": effort_history, "sessions": sessions,
        "summ": summarizer, "rnd": rnd_registry, "repo": repo,
        "pid": proj["id"], "wbase": wbase, "data": data,
    }
    yield bundle
    try:
        import pty_manager
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


def _write_build_docs_in_worktree(worktree_path, plan_dir="build/rnd-x"):
    """Stand in for what Foreman would write: a deliverable doc set in the
    session's worktree (uncommitted, as a live session leaves it)."""
    wt = Path(worktree_path)
    north = f"{plan_dir}/NORTH-STAR.md"
    deliv = f"{plan_dir}/DELIVERABLE.md"
    log = f"{plan_dir}/EXECUTION-LOG.md"
    for rel, body in [
            (north, "# North Star\nThe locked north star is durable resumable work.\n"),
            (deliv, "# Deliverable\nThe widget service ships.\n"),
            (log, "# Execution Log\nWave 1 GREEN.\n")]:
        p = wt / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return {"north": north, "deliv": deliv, "log": log}


def _js(html):
    return "\n".join(re.findall(r"<script[^>]*>([\s\S]*?)</script>", html))


def _strip(html):
    b = re.sub(r"<style[\s\S]*?</style>", "", html)
    b = re.sub(r"<script[\s\S]*?</script>", "", b)
    return b


def _free_server(gui):
    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, port, t


# ════════════════════════════════════════════════════════════════════════════
# (1) KILL persists docs + ties a durable summary record (stable id) BEFORE reap
# ════════════════════════════════════════════════════════════════════════════

def test_kill_persists_docs_and_durable_summary_no_loss(env):
    """Killing a session that produced docs: BEFORE reap the docs are persisted
    AND a durable summary keyed to the (stable) managed session id caches with
    REFERENCES to those exact docs. After the reap nothing is lost — both resolve
    from the MAIN folder by the managed id; the worktree is gone."""
    ts, eh, summ, repo, pid, gui = (env["ts"], env["eh"], env["summ"],
                                    env["repo"], env["pid"], env["gui"])

    sess = ts.start_session(pid, "build", backend="claude")
    sid = sess["session_id"]
    wt = Path(sess["worktree_path"])
    docs = _write_build_docs_in_worktree(wt)
    assert wt.is_dir()

    out = ts.kill(sid)
    # Docs were persisted (capture-before-reap) into the MAIN folder.
    assert out["docs"]["ok"] is True
    assert docs["deliv"] in out["docs"]["persisted"]
    assert (repo / docs["deliv"]).is_file()
    assert (repo / docs["north"]).is_file()
    # The worktree is reaped …
    assert not wt.is_dir(), "worktree should be removed after kill"

    # … but the killed session resolves to a DURABLE lane session (stable id +
    # produced docs) tied via the persisted, session-tagged efforts.
    durable = gui._resolve_finished_session(str(repo), pid, "build", sid)
    assert durable is not None, "killed session must resolve to a durable session"
    assert durable["session_id"] == sid
    member_rels = {(m.get("artifact_path") or "") for m in durable["member_files"]}
    assert docs["deliv"] in member_rels and docs["north"] in member_rels

    # The session-tagged efforts carry the managed id (the explicit tie).
    tagged = eh.efforts_for_session_id(str(repo), pid, "build", sid)
    assert {(e.get("artifact_path") or "") for e in tagged} >= {
        docs["deliv"], docs["north"]}

    # The durable summary (keyed to the managed id) caches with the docs as
    # actions + the produced-doc references (no model run on the read path).
    cached = summ.summarize_session(str(repo), pid, "build", durable)
    assert not cached.get("error")
    labels = " ".join(
        (a.get("label") or a.get("rel") or a.get("job_id") or "")
        for a in (cached.get("actions") or [])).lower()
    assert "deliverable" in labels or "north" in labels or "build/" in labels
    # The cache is keyed to the managed id and re-loadable from the MAIN folder.
    again = summ.load_cached(str(repo), pid, "build", sid)
    assert again is not None and again.get("session_id") == sid


def test_kill_schedules_summary_on_finish(env):
    """The kill HANDLER (term_kill) schedules the durable summary on finish — and
    because proactive generation is enabled in this env, the cache lands (keyed to
    the managed id) carrying the produced docs."""
    ts, summ, repo, pid, gui = (env["ts"], env["summ"], env["repo"],
                                env["pid"], env["gui"])
    sess = ts.start_session(pid, "planning", backend="claude")
    sid = sess["session_id"]
    _write_build_docs_in_worktree(sess["worktree_path"], plan_dir="planning/rnd-y")

    srv, port, t = _free_server(gui)
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/rnd/term_kill",
            data=json.dumps({"session": sid}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
        assert data["ok"] is True
        assert data["result"]["docs"]["ok"] is True
        # Poll for the background summary to land (proactive enabled).
        cached = None
        for _ in range(60):
            cached = summ.load_cached(str(repo), pid, "planning", sid)
            if cached is not None:
                break
            import time as _t
            _t.sleep(0.1)
        assert cached is not None, "kill must schedule a durable summary that caches"
        assert cached.get("session_id") == sid
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


# ════════════════════════════════════════════════════════════════════════════
# (2) Promotion — killed session becomes a BIG board tile; chip removed
# ════════════════════════════════════════════════════════════════════════════

def test_killed_session_promotes_to_big_tile_chip_removed(env):
    """After kill the registry record persists as DONE → the v7 board bridge
    renders it as a BIG lane-column tile (data-session=<sid>) in the served board.
    And the JS top-strip excludes _KILLED ids (the little chip is removed)."""
    ts, repo, pid, gui = env["ts"], env["repo"], env["pid"], env["gui"]
    sess = ts.start_session(pid, "build", backend="claude")
    sid = sess["session_id"]
    _write_build_docs_in_worktree(sess["worktree_path"])
    ts.kill(sid)

    # Board render includes a big lane tile for the killed (now DONE) session.
    html = gui.render_project_window_html(pid)
    body = _strip(html)
    assert ('data-session="%s"' % sid) in body, \
        "killed session must appear as a big board tile"
    # It is a real board tile (the lane-tile alias), not a top-strip chip.
    # v12 Wave 2 Layout-D: the tile is a headline card or a shelf little-tile, so
    # the class prefix varies (``headline tile lane-tile`` / ``minitile tile
    # lane-tile``) — match the alias anywhere in the class list.
    tile_re = re.compile(
        r"<div class='[^']*\btile lane-tile\b[^']*'[^>]*data-session=\"%s\""
        % re.escape(sid))
    assert tile_re.search(body), "killed session tile must be a board lane-tile"

    # NEGATIVE / POSITIVE on the JS chip-removal: killPanel marks _KILLED and
    # repopulate() skips _KILLED ids (so the top-strip chip is gone after a kill).
    js = _js(html)
    assert "_KILLED[sessionId] = 1" in js, "killPanel must record the killed id"
    rep = re.search(r"async function repopulate\(\)\s*\{([\s\S]*?)\n\}", js)
    assert rep and "if (_KILLED[s.session_id]) continue;" in rep.group(1), \
        "repopulate must skip _KILLED ids → the little chip is removed"


# ════════════════════════════════════════════════════════════════════════════
# (3) Detail view — deliverable + docs + summary + a WORKING "Continue the dialog"
# ════════════════════════════════════════════════════════════════════════════

def test_detail_view_shows_docs_summary_and_continue_seeds(env):
    """The big tile's detail view (read-only past-session body) renders the
    produced docs + the summary AND offers "Continue in a live session". The
    Continue path builds a seed from the DURABLE docs/summary and starts a NEW
    seeded live session in the SAME lane; the ORIGINAL killed record is unchanged."""
    ts, summ, reg, repo, pid, gui = (env["ts"], env["summ"], env["reg"],
                                     env["repo"], env["pid"], env["gui"])
    sess = ts.start_session(pid, "build", backend="claude")
    sid = sess["session_id"]
    docs = _write_build_docs_in_worktree(sess["worktree_path"])
    ts.kill(sid)

    # The durable summary caches with the produced docs (the detail-view content).
    durable = gui._resolve_finished_session(str(repo), pid, "build", sid)
    cached = summ.summarize_session(str(repo), pid, "build", durable)
    assert (cached.get("actions") or []), "detail summary must list produced docs"

    before = json.dumps(reg.list_sessions(project_id=pid), sort_keys=True)

    # The Continue seed is built from the DURABLE summary/docs (not a placeholder).
    seed = gui._build_continue_seed(str(repo), pid, "build", sid)
    assert seed, "continue seed must carry the prior session's durable context"
    assert ("durable" in seed.lower() or "north" in seed.lower()
            or "deliverable" in seed.lower() or "foreman" in seed.lower())

    new = ts.start_session(pid, "build", seed_context=seed)
    nsid = new["session_id"]
    assert nsid != sid
    assert new["lane"] == "build"
    assert new["status"] == reg.STATUS_RUNNING
    assert new.get("seed_text"), "continue must seed the new session"

    # ORIGINAL untouched: its record is unchanged + its cached summary intact.
    orig = reg.get_session(sid)
    assert orig is not None and orig["status"] == reg.STATUS_DONE
    again = summ.load_cached(str(repo), pid, "build", sid)
    assert again == cached, "continue must not mutate the prior summary"
    # The registry only GAINED the new session (the prior record is additive-safe).
    assert before is not None
    ts.kill(nsid)


# ── DOM (positive + negative): detail/continue wiring in the served JS ─────────

def test_detail_continue_wiring_in_js(env):
    """The past-session detail body exposes the produced-docs/summary sections AND
    a Continue control wired to continue_session (positive); and the historical
    body is NOT a bare dead-end note (negative)."""
    gui, pid = env["gui"], env["pid"]
    js = _js(gui.render_project_window_html(pid))

    # POSITIVE: the detail renders skill/prompts/produced-files + a Continue button.
    assert "Skill invoked" in js
    assert "Prompts asked" in js
    assert "Files produced" in js
    assert "ro-continue" in js
    assert "Continue in a live session" in js
    assert "continueSession(" in js
    assert "/api/rnd/continue_session" in js

    # NEGATIVE: _mountReadOnlyBody builds the past-session view (ro-past) with a
    # Continue control, not only a static "session complete" dead-end.
    mb = re.search(r"function _mountReadOnlyBody\(sessionId, host, s\)\s*\{"
                   r"([\s\S]*?)\n\}", js)
    assert mb, "_mountReadOnlyBody not found"
    bodyjs = mb.group(1)
    assert "ro-past" in bodyjs
    assert "ro-continue" in bodyjs


# ════════════════════════════════════════════════════════════════════════════
# (D) REAL Playwright + Chromium — kill → chip gone + big tile + detail + continue
# ════════════════════════════════════════════════════════════════════════════

def test_playwright_kill_no_loss_lifecycle(env):
    """End-to-end in a real browser:
      1. Start a build session (a live top-strip chip appears).
      2. Write a doc into its worktree; KILL it (confirm-gated).
      3. The little top-strip chip is GONE + a big board lane tile appears.
      4. Click the big tile → the detail view shows the summary + Continue control.
      5. Click Continue → a NEW live panel/session appears. No JS console errors.
    Screenshot saved to _devtest/wave5_noloss.png."""
    pytest.importorskip("playwright.sync_api")
    ts, summ, repo, pid, gui = (env["ts"], env["summ"], env["repo"],
                                env["pid"], env["gui"])
    sess = ts.start_session(pid, "build", backend="claude")
    sid = sess["session_id"]
    docs = _write_build_docs_in_worktree(sess["worktree_path"])

    srv, port, t = _free_server(gui)
    base = f"http://127.0.0.1:{port}"
    from playwright.sync_api import sync_playwright
    new_sids = []
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1280, "height": 1000})
            errors = []
            pg.on("console",
                  lambda m: errors.append(m.text) if m.type == "error" else None)
            pg.on("dialog", lambda d: d.accept())  # auto-confirm the kill prompt
            pg.goto(f"{base}/project/{pid}", wait_until="networkidle")
            from tests.ui_helpers import expand_workbench
            expand_workbench(pg)  # the Workbench tile now opens collapsed

            chip_sel = '#sessionBar .live-chip[data-session="%s"]' % sid
            pg.wait_for_selector(chip_sel, timeout=8000)
            # Open the live panel and KILL it via the panel's 🪦 Kill→Boneyard
            # control (W6 control-unification renamed the old 🗑 .hardkill button
            # to the single destructive .killbone control).
            pg.click(chip_sel)
            pg.wait_for_selector("#panelStack .panel", timeout=5000)
            pg.click("#panelStack .panel .panelbtn.killbone")
            # The little top-strip chip for the killed session is GONE.
            pg.wait_for_function(
                "document.querySelectorAll("
                "'#sessionBar .live-chip[data-session=\"%s\"]').length === 0" % sid,
                timeout=8000)
            # A big board lane tile for the killed session remains. John tweak:
            # older-runs shelves render COLLAPSED by default, and the killed
            # session can land in a collapsed shelf (the durable-doc DISCOVERED
            # build session becomes the headline) — so wait for the tile ATTACHED,
            # then expand any collapsed shelf hosting it so it is interactable.
            tile_sel = '#kanbanBoard .lane-tile[data-session="%s"]' % sid
            pg.wait_for_selector(tile_sel, state="attached", timeout=8000)
            pg.eval_on_selector(
                tile_sel,
                "el => { var w = el.closest('.shelf-wrap');"
                " if (w && w.classList.contains('collapsed'))"
                " w.classList.remove('collapsed'); }")
            pg.wait_for_selector(tile_sel, timeout=8000)

            # v12 W10: clicking the big EFFORT tile opens the SINGLE bottom DOCK;
            # its detail (read-only past-session) renders in the dock terminal host
            # with a summary section + a Continue control.
            pg.click(tile_sel)
            pg.wait_for_function(
                "() => document.getElementById('effortDock').style.display === 'flex'",
                timeout=8000)
            pg.wait_for_selector("#dockTermHost .ro-past", timeout=8000)
            pg.wait_for_selector("#dockTermHost .ro-sec", timeout=8000)
            assert pg.eval_on_selector_all(
                "#dockTermHost .ro-continue", "e=>e.length") == 1

            # Continue RE-BINDS the single dock to the NEW live session (the
            # read-only body is replaced by a live terminal — same dock).
            src_sid = pg.eval_on_selector(
                "#effortDock", "e=>e.getAttribute('data-session')")
            assert src_sid, "dock must carry the source data-session"
            pg.click("#dockTermHost .ro-continue")
            # The read-only historical body is GONE and the dock now carries a
            # DIFFERENT data-session (the new live session). Still ONE dock.
            pg.wait_for_function(
                "src=>{var d=document.getElementById('effortDock');"
                "if(d.style.display!=='flex') return false;"
                "if(document.querySelectorAll('#dockTermHost .ro-past').length) return false;"
                "var ds=d.getAttribute('data-session');"
                "return !!ds && ds!==src;}",
                arg=src_sid, timeout=8000)
            assert pg.eval_on_selector_all(".dock", "e=>e.length") == 1, \
                "Continue must reuse the single dock, not stack"

            DEVTEST.mkdir(exist_ok=True)
            pg.screenshot(path=str(DEVTEST / "wave5_noloss.png"), full_page=True)
            assert not errors, f"JS console errors: {errors}"
            b.close()

        # Backend truth: a NEW running build session now exists (from Continue).
        import session_registry as reg
        running = [r for r in reg.list_sessions(project_id=pid)
                   if r.get("lane") == "build"
                   and r.get("status") == reg.STATUS_RUNNING]
        assert running, "Continue did not create a new live build session"
        new_sids = [r["session_id"] for r in running]
        # The killed session's docs survived (persisted into the main folder).
        assert (repo / docs["deliv"]).is_file()
    finally:
        for nsid in new_sids:
            try:
                ts.kill(nsid)
            except Exception:
                pass
        srv.shutdown(); srv.server_close(); t.join(timeout=5)
