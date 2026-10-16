"""v10 Wave 2 — Playwright UI: advance → next panel shows the prompt PASTED-but-UNSENT.

The visual contract (mockup ``planning/rnd-v10/_mockups/advance_paste.html``):
clicking **Advance to Planning →** opens a NEW linked planning panel; the trio
skill greets, then the generated next-stage prompt is delivered as a v10 *pending
paste* — it appears in the terminal input line UNSENT (no trailing newline, no
model response). The user reviews and presses Enter to run; nothing is submitted
on their behalf.

DEV-ONLY (``pytest.importorskip("playwright.sync_api")``); never imported by
product code. Hermetic: stub PTY + fake runner + temp git repo + tmp data/worktree
dirs; the server binds a FREE port (asserted != 8777). No real claude/:8777/network.

Because the stub PTY + fake runner never produce a *real* model greet (the v10
flush requires the greet-marker count to exceed the echoed-seed base — Master-Plan
R1), this test injects the model greet onto the new planning session's PTY from
Python (same process as the server) so the transport's next read flushes the
pending paste — exactly what a real model greet would do in production.
"""
import importlib
import subprocess
import threading
import time
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()
_DEVTEST = Path(__file__).resolve().parent.parent / "_devtest"
GREET_LINE = "✓ Crucible loaded — what would you like to do?"


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
    bundle = {"gui": gui, "pid": proj["id"], "repo": repo}
    yield bundle
    try:
        import pty_manager
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


def _build_research_session(bundle):
    """Start a LIVE research session with a real persisted report doc tagged to
    the session, so the advance's NEXT-PROMPT names a real path. Returns its id.

    NOTE (v11): this PRE-PERSISTS the research doc via ``eh.record_effort`` — so
    this is PROMPT-BUILDING-GIVEN-PERSISTED-DOCS coverage, NOT live-flow coverage.
    The live worktree-only flow (the actual advance, where the doc lives ONLY in
    the session's worktree until the advance persists it — the path the original
    bug broke) is covered by ``tests/test_advance_research_to_plan_live_v11.py`` +
    ``tests/test_handoff_unified_v11.py`` +
    ``anchor_healthcheck.check_rnd_v11_surface``. Do NOT make a pre-persisted test
    the SOLE coverage of an advance path (the v11 lesson)."""
    pid, repo = bundle["pid"], bundle["repo"]
    import terminal_session as ts
    import effort_history as eh
    rec = ts.start_session(pid, "research")
    sid = rec["session_id"]
    rel = "research/run-1/REPORT.md"
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# Cooling report\n## Findings\nAdequate.\n", encoding="utf-8")
    jid = eh.discovered_job_id("research", rel)
    eh.record_effort(repo, pid, "research", jid, skill="researchPrime",
                     extra={"source": eh.SOURCE_DISCOVERED, "kind": "report",
                            "title": "Cooling report", "artifact_path": rel,
                            "status": "imported", "session_id": sid})
    return sid


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
        # Robust teardown: the Playwright browser/page (and thus its WS/SSE
        # client sockets) is already closed by the test's ``with
        # sync_playwright()`` block exiting BEFORE this finalizer runs. Give any
        # still-draining stream handler thread a brief grace, then shut the
        # server down GUARDED so a benign teardown race can't fail the test.
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


def test_advance_shows_prompt_pasted_unsent_in_browser(server):
    """Open a research panel, click Advance → a new planning panel opens; after the
    (injected) greet, the generated prompt appears in the terminal UNSENT (the
    NEXT-PROMPT text is visible and was NOT auto-submitted). Screenshot saved to
    _devtest/wave2_advance_paste.png. No JS console errors."""
    pytest.importorskip("playwright.sync_api")
    bundle, base, _ = server
    pid = bundle["pid"]
    src = _build_research_session(bundle)

    import session_registry as reg
    import pty_manager

    from playwright.sync_api import sync_playwright
    _DEVTEST.mkdir(exist_ok=True)
    shot = _DEVTEST / "wave2_advance_paste.png"

    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        errors = []
        pg.on("console",
              lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.goto(f"{base}/project/{pid}", wait_until="networkidle")
        from tests.ui_helpers import expand_workbench
        expand_workbench(pg)  # the Workbench tile now opens collapsed
        pg.wait_for_selector('#sessionBar .live-chip', timeout=8000)

        # Open the research panel + find the Advance control.
        pg.eval_on_selector_all('#sessionBar .live-chip',
                                "els=>els.forEach(e=>e.click())")
        pg.wait_for_selector("#panelStack .panel .advbtn", timeout=8000)

        before = set(r["session_id"] for r in reg.list_sessions(project_id=pid)
                     if r.get("lane") in ("plan", "planning"))
        pg.click("#panelStack .panel .advbtn")

        # A new planning session is minted server-side; find its id.
        new_sid = None
        for _ in range(80):
            now = [r["session_id"] for r in reg.list_sessions(project_id=pid)
                   if r.get("lane") in ("plan", "planning")
                   and r["session_id"] not in before]
            if now:
                new_sid = now[0]
                break
            time.sleep(0.05)
        assert new_sid, "advance did not create a planning session"

        # The new planning record carries the pending paste (the NEXT-PROMPT body).
        # NOTE (race): terminal_session.start_session registers the record FIRST
        # (so it appears in list_sessions) and then sets pending_paste in a SEPARATE
        # update_session call — so there is a brief window where the record exists
        # but pending_paste is not yet written. Poll for the pending_paste to land
        # rather than reading once (intent unchanged: the advance HOLDS the prompt).
        prompt = ""
        for _ in range(80):
            prec = reg.get_session(new_sid)
            prompt = prec.get("pending_paste") or ""
            if prompt:
                break
            time.sleep(0.05)
        assert prompt, "advanced planning session has no pending paste"
        assert "research/run-1/REPORT.md" in prompt, \
            "pending paste should reference the real research doc"
        assert prec.get("paste_flushed") is False

        # The pending-paste hint banner appeared.
        pg.wait_for_selector(".pendpaste-hint", timeout=6000)

        # DETERMINISM (flake fix): the pending-paste flush only fires on the panel
        # transport's NEXT read_since/attach AFTER the greet is in the buffer. So we
        # must inject the greet ONLY ONCE the new panel's transport (WS/SSE) is
        # actually ATTACHED and pumping reads — otherwise the greet can land before
        # any read loop exists and the flush is left to chance/timeout. The stub PTY
        # ECHOES the one-time skill-load seed ("Load the Crucible skill now…"), so the
        # seed appearing in THIS panel's xterm proves the transport has attached
        # and completed at least one read cycle. Wait for that BEFORE the greet.
        # NOTE: the advance seed now carries the full upstream research summary
        # (v8+ "handoff carries docs"), so the "Load the Crucible" opener scrolls
        # OUT of the small visible viewport almost immediately — checking the
        # rendered `.term-host` textContent (xterm only keeps VISIBLE rows in the
        # DOM) would time out. So we read the xterm SCROLLBACK BUFFER (the same
        # source of truth the UNSENT negative assertion below uses), where the
        # echoed seed is retained regardless of scroll position.
        pg.wait_for_function(
            "sid=>{var w=window.PANELS&&window.PANELS[sid];"
            "if(!w||!w.term)return false;var b=w.term.buffer.active;"
            "for(var i=0;i<b.length;i++){var l=b.getLine(i);"
            "if(l&&l.translateToString(true).indexOf('Load the Crucible')>=0)"
            "return true;}return false;}",
            arg=new_sid, timeout=10000)

        # Inject the MODEL greet onto the new planning PTY so the transport's next
        # read flushes the pending paste UNSENT (production: the real greet does it).
        pty_manager.write(new_sid, GREET_LINE)

        # DETERMINISM (flake fix): wait for the flush to complete at the SOURCE OF
        # TRUTH first. _flush_pending_paste CLAIMS the paste (sets paste_flushed=True
        # + clears pending_paste under WRITE_LOCK) BEFORE writing the bytes to the
        # PTY, and it only fires on a transport read cycle that observes the greet —
        # which is several poll ticks out. Poll the registry until the claim lands
        # (generous timeout, fast cadence) so the subsequent DOM/xterm assertions run
        # AGAINST a guaranteed-flushed session, never a pre-flush snapshot. This
        # orders greet → flush-confirmed → render-confirmed.
        flushed = False
        for _ in range(160):  # ~8s at 50ms
            r = reg.get_session(new_sid)
            if r and r.get("paste_flushed") is True:
                flushed = True
                break
            time.sleep(0.05)
        assert flushed, "pending paste was not flushed (paste_flushed never True)"

        # POSITIVE — DISCRIMINATING token. We assert a token that appears ONLY in
        # the PASTE body and NOT in the phase-1 load+greet seed the stub PTY echoes:
        # the REAL persisted research doc path. ("Crucible" is NOT usable — it ALSO
        # appears in the echoed phase-1 seed "Load the Crucible skill now…", so it
        # would pass even if the paste never flushed.) The doc path is generated
        # only by the NEXT-PROMPT builder, so its presence PROVES the paste landed.
        crumb = "research/run-1/REPORT.md"
        assert crumb in prompt and crumb not in (prec.get("seed_text") or ""), \
            "test invariant: the doc path must be paste-only (not in the seed)"
        pg.wait_for_function(
            "document.querySelector('#panelStack .panel[data-session=\"%s\"] "
            ".term-host') && document.querySelector('#panelStack .panel"
            "[data-session=\"%s\"] .term-host').textContent.indexOf('%s') >= 0"
            % (new_sid, new_sid, crumb),
            timeout=10000)

        term_txt = pg.eval_on_selector(
            '#panelStack .panel[data-session="%s"] .term-host' % new_sid,
            "e => e.textContent")
        assert crumb in term_txt, "the pasted prompt is not visible in the terminal"

        # RENDERED NEGATIVE — the prompt landed UNSENT. We read the live xterm
        # buffer for this panel and assert the CURSOR sits on the SAME row as the
        # pasted prompt's tail — i.e. NO newline was submitted after the paste.
        # If the product had auto-submitted (written paste + "\n"), the cursor row
        # would be BELOW the paste row and this assertion FAILS. (We match on the
        # paste-only doc-path token "REPORT.md", which the builder emits last.)
        neg = pg.evaluate(
            """(sid) => {
              var w = window.PANELS && window.PANELS[sid];
              if (!w || !w.term) return {ok:false, reason:'no-term'};
              var buf = w.term.buffer.active;
              var cy = buf.baseY + buf.cursorY;
              var lastPaste = -1, sawSubmittedAfter = false;
              for (var i = 0; i < buf.length; i++) {
                var line = buf.getLine(i);
                if (!line) continue;
                var s = line.translateToString(true);
                if (s.indexOf('REPORT.md') >= 0) lastPaste = i;
              }
              // Any NON-EMPTY rendered row strictly BELOW the paste row would mean
              // the prompt was submitted and produced a following line.
              for (var j = lastPaste + 1; j < buf.length; j++) {
                var ln = buf.getLine(j);
                if (ln && ln.translateToString(true).trim().length > 0)
                  sawSubmittedAfter = true;
              }
              return {ok:true, cursorRow:cy, pasteRow:lastPaste,
                      sawSubmittedAfter:sawSubmittedAfter};
            }""", new_sid)
        assert neg.get("ok"), f"could not read xterm buffer: {neg}"
        assert neg["pasteRow"] >= 0, "the pasted prompt row was not found in xterm"
        # UNSENT: nothing rendered on a row after the paste (no submitted turn), and
        # the cursor rests on the paste row (a submit would have advanced it below).
        assert neg["sawSubmittedAfter"] is False, \
            "content rendered AFTER the paste row — the prompt was auto-submitted"
        assert neg["cursorRow"] == neg["pasteRow"], \
            "cursor is below the paste row — a newline was submitted (auto-run)"

        # Backend corroboration: pending cleared, flushed once; nothing re-emitted.
        assert reg.get_session(new_sid)["paste_flushed"] is True
        assert reg.get_session(new_sid)["pending_paste"] == ""

        pg.screenshot(path=str(shot), full_page=True)
        assert not errors, f"JS console errors: {errors}"
        b.close()

    assert shot.exists(), "screenshot not written"

    # Backend truth: the planning session is linked to the research source.
    plan = [r for r in reg.list_sessions(project_id=pid)
            if r.get("lane") in ("plan", "planning")]
    assert any(r.get("parent_session_id") == src for r in plan), \
        "advanced planning session not linked to the research source"

    import terminal_session as ts
    for r in reg.list_sessions(project_id=pid):
        try:
            ts.kill(r["session_id"])
        except Exception:
            pass
