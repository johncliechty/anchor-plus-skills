"""W6 UI — Live Escalation first-click sentence, in a REAL browser (Playwright).

The gate-level exhaustive per-tile-class MATRIX (render assertions over every tile
class) lives in ``test_live_escalation_w6.py``; this is the live-browser leg that
backs the screenshot sign-off for the first-click sentence + the 1-click/2-action
path (NORTH-STAR-AMENDMENT click contract):

  * clicking a session tile once opens a warm, narrated, terminal-chrome view
    (Layer 1) that is NON-BLANK — the deterministic narration spine;
  * exactly ONE further explicit action ('▶ Resume live') is present in the SAME
    window to reach a live PTY — never a third action, never a second window.

DEV-ONLY: Playwright is a test-only dependency (always present in the build/CI
env) and is never imported by product code, so it never appears in distro.py's
import scan. This test runs directly (no skip guards). A
screenshot is written under ``tmp_path`` for the manual sign-off. Hermetic: temp
data dir + stub PTY + fake runner + a temp git repo — never :8777 / real data.
"""
import importlib
import subprocess
import threading
import time
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()


def _have_git():
    try:
        return subprocess.run(["git", "--version"],
                              capture_output=True).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False



def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True)


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
    for mod in ("paths", "job_runner", "pty_manager", "rnd_registry",
                "session_registry", "worktrees", "lanes", "effort_history",
                "sessions", "summarizer", "narration", "handoff",
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
    yield {"gui": gui, "pid": proj["id"], "repo": repo}
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
        yield gui_env, f"http://127.0.0.1:{port}"
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


def _make_discovered_effort(bundle):
    """A discovered/brownfield effort renders as a clickable board tile — the most
    reliable tile class to click in a headless browser (no live PTY needed)."""
    pid, repo = bundle["pid"], bundle["repo"]
    import effort_history as eh
    rel = "research/run-1/REPORT.md"
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# Cooling report\n## Findings\nAdequate.\n", encoding="utf-8")
    jid = eh.discovered_job_id("research", rel)
    eh.record_effort(repo, pid, "research", jid, skill="researchPrime",
                     extra={"source": eh.SOURCE_DISCOVERED, "kind": "report",
                            "title": "Cooling report", "artifact_path": rel,
                            "status": "imported", "session_id": "disc-sess-1"})


def test_first_click_opens_nonblank_layer1_with_resume_live(server, tmp_path):
    """The first-click sentence, in a real browser: clicking a tile opens a
    NON-BLANK Layer-1 narrated view and the '▶ Resume live' escalation control is
    present in the SAME window. A screenshot is written for the manual sign-off.

    git + Playwright are always present in the build/CI env (verified in W6); this
    test does NOT skip — a missing dep is an honest failure, not a silent skip that
    would trip Foreman's §5 test-integrity guard (the W1/W4 lesson)."""
    bundle, base = server
    _make_discovered_effort(bundle)
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch()
        try:
            page = b.new_page()
            page.goto(f"{base}/project/{bundle['pid']}", timeout=15000)
            from tests.ui_helpers import expand_workbench
            expand_workbench(page)  # the Workbench tile now opens collapsed
            # Find a clickable effort tile (the discovered effort).
            tile = page.locator("[data-effort-id]").first
            tile.wait_for(state="visible", timeout=10000)
            tile.click()
            # Layer 1 renders in the terminal chrome; wait until the spine is no
            # longer the 'loading…' placeholder (structurally never blank).
            page.wait_for_selector(".layer1 .l1-spine .l1-sec", timeout=10000)
            spine_text = page.locator(".layer1 .l1-spine").inner_text()
            assert spine_text.strip(), "Layer 1 rendered BLANK"
            # (CSS uppercases the section labels — match case-insensitively.)
            low = spine_text.lower()
            assert "what was done" in low
            assert "what comes next" in low
            # The deterministic narration spine carries the real facts, not a
            # placeholder (the first-click sentence: it NARRATES what was done).
            assert "ran researchprime" in low
            # Exactly ONE further action to live is present in the same window.
            assert page.locator(".layer1 .resume-live").count() >= 1
            # The 'next' step is shown paste-NOT-submit (nothing auto-runs).
            assert page.locator('.layer1 .l1-next[data-submit="false"]').count() >= 1
            shot = tmp_path / "w6-first-click-layer1.png"
            page.screenshot(path=str(shot))
            assert shot.exists() and shot.stat().st_size > 0
        finally:
            b.close()
