"""v11 Wave 2 — Playwright UI: research→plan advance, the WORKTREE-ONLY live flow.

THE user-facing fix, verified in a real browser. We start a LIVE research session
and PRODUCE the report LIVE in its WORKTREE (write the file under the session
worktree — NOT via ``record_effort``, NO kill), open the project window, click
**Advance to Planning →**, wait for the new planning panel/terminal, and assert the
planning terminal's pasted-unsent prompt shows the REAL ``research/run-1/REPORT.md``.

DISCRIMINATING token (the v4 lesson): the asserted token is the REAL persisted doc
path ``research/run-1/REPORT.md``. It appears in the pasted prompt ONLY if the
keystone PERSISTED the live worktree doc (the v11 fix). It is ABSENT from the bare
"load Crucible" fallback the pre-W2 code produced, and ABSENT from the phase-1
load+greet seed the stub PTY echoes — so its presence PROVES persist+keystone
worked. ("Crucible" alone is NOT discriminating — it is also in the echoed seed.)

DEV-ONLY (``pytest.importorskip("playwright.sync_api")``); never imported by
product code. Hermetic: stub PTY + fake runner + temp git repo + tmp data/worktree
dirs; the server binds a FREE port (asserted != 8777). ``ANCHOR_PROACTIVE_SUMMARY``
OFF. No real claude/:8777/network.

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
    bundle = {"gui": gui, "pid": proj["id"], "repo": repo}
    yield bundle
    try:
        import pty_manager
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


def _build_live_research_with_worktree_doc(bundle):
    """Start a LIVE research session and PRODUCE the report LIVE in its WORKTREE
    ONLY (NOT via record_effort, NO kill) — the v11 WORKTREE-ONLY live flow.

    Returns (research_session_id, rel). The doc is intentionally NOT persisted /
    NOT recorded as an effort: the advance keystone must persist it.
    """
    pid = bundle["pid"]
    import terminal_session as ts
    rec = ts.start_session(pid, "research")
    sid = rec["session_id"]
    rel = "research/run-1/REPORT.md"
    p = Path(rec["worktree_path"]) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# Cooling report\n## Findings\nAdequate.\n", encoding="utf-8")
    return sid, rel


def test_advance_live_research_shows_real_doc_in_browser(server):
    """Open a research panel, click Advance → a new planning panel opens; after the
    (injected) greet the pasted prompt names the REAL research/run-1/REPORT.md (the
    discriminating token, absent from the bare fallback + the echoed seed) and was
    NOT auto-submitted. Screenshot → _devtest/wave_v11_research_to_plan.png. No JS
    console errors."""
    pytest.importorskip("playwright.sync_api")
    bundle, base, _ = server
    pid = bundle["pid"]
    src, rel = _build_live_research_with_worktree_doc(bundle)

    import session_registry as reg
    import pty_manager

    from playwright.sync_api import sync_playwright
    _DEVTEST.mkdir(exist_ok=True)
    shot = _DEVTEST / "wave_v11_research_to_plan.png"

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

        # A new planning session is minted server-side; find its id. The session
        # row is registered by start_session a beat BEFORE its pending_paste is
        # written, so wait until the paste is populated to avoid a register-vs-
        # paste-write race (the discriminating assert below reads pending_paste).
        new_sid = None
        for _ in range(160):  # ~8s at 50ms
            now = [r for r in reg.list_sessions(project_id=pid)
                   if r.get("lane") in ("plan", "planning")
                   and r["session_id"] not in before]
            if now and (now[0].get("pending_paste") or ""):
                new_sid = now[0]["session_id"]
                break
            time.sleep(0.05)
        assert new_sid, \
            "advance did not create a planning session with a pending paste"

        # Backend truth (the v11 fix): the LIVE research doc was PERSISTED into the
        # project AND named in the new planning session's pending paste — the path
        # is the discriminating token, ABSENT from the bare fallback + the seed.
        assert (bundle["repo"] / rel).is_file(), \
            "live research doc was NOT persisted into the project"
        prec = reg.get_session(new_sid)
        prompt = prec.get("pending_paste") or ""
        assert rel in prompt, \
            "pending paste should reference the real persisted research doc"
        assert rel not in (prec.get("seed_text") or ""), \
            "test invariant: the doc path must be paste-only (not in the seed)"
        assert prec.get("paste_flushed") is False

        # The pending-paste hint banner appeared.
        pg.wait_for_selector(".pendpaste-hint", timeout=6000)

        # Wait for THIS panel's transport to attach + complete one read (the stub
        # PTY echoes the one-time skill-load seed) BEFORE injecting the greet.
        pg.wait_for_function(
            "document.querySelector('#panelStack .panel[data-session=\"%s\"] "
            ".term-host') && document.querySelector('#panelStack .panel"
            "[data-session=\"%s\"] .term-host').textContent.indexOf("
            "'Load the Crucible') >= 0"
            % (new_sid, new_sid),
            timeout=10000)

        # Inject the MODEL greet so the transport's next read flushes the paste.
        pty_manager.write(new_sid, GREET_LINE)

        # Wait for the flush at the source of truth first.
        flushed = False
        for _ in range(160):  # ~8s at 50ms
            r = reg.get_session(new_sid)
            if r and r.get("paste_flushed") is True:
                flushed = True
                break
            time.sleep(0.05)
        assert flushed, "pending paste was not flushed (paste_flushed never True)"

        # POSITIVE — the DISCRIMINATING real doc path is rendered in the terminal.
        pg.wait_for_function(
            "document.querySelector('#panelStack .panel[data-session=\"%s\"] "
            ".term-host') && document.querySelector('#panelStack .panel"
            "[data-session=\"%s\"] .term-host').textContent.indexOf('%s') >= 0"
            % (new_sid, new_sid, rel),
            timeout=10000)
        term_txt = pg.eval_on_selector(
            '#panelStack .panel[data-session="%s"] .term-host' % new_sid,
            "e => e.textContent")
        assert rel in term_txt, "the pasted prompt (real doc) is not visible"

        # RENDERED NEGATIVE — the prompt landed UNSENT (nothing on a row below it).
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
        assert neg["sawSubmittedAfter"] is False, \
            "content rendered AFTER the paste row — the prompt was auto-submitted"
        assert neg["cursorRow"] == neg["pasteRow"], \
            "cursor is below the paste row — a newline was submitted (auto-run)"

        # Backend corroboration: pending cleared, flushed once.
        assert reg.get_session(new_sid)["paste_flushed"] is True
        assert reg.get_session(new_sid)["pending_paste"] == ""

        pg.screenshot(path=str(shot), full_page=True)
        assert not errors, f"JS console errors: {errors}"
        b.close()

    assert shot.exists(), "screenshot not written"

    # Backend truth: the planning session is linked to the research source AND a
    # HANDOFF.md exists in its worktree referencing the real doc.
    plan = [r for r in reg.list_sessions(project_id=pid)
            if r.get("lane") in ("plan", "planning")
            and r["session_id"] == new_sid]
    assert plan and plan[0].get("parent_session_id") == src
    ho = Path(plan[0]["worktree_path"]) / "HANDOFF.md"
    assert ho.is_file() and rel in ho.read_text(encoding="utf-8")

    import terminal_session as ts
    for r in reg.list_sessions(project_id=pid):
        try:
            ts.kill(r["session_id"])
        except Exception:
            pass
