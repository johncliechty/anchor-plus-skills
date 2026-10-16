"""v10 Wave 3 — grass workbench terminals — MIGRATED to the v12 Wave 11
ONE-session workbench.

ORIGINAL INTENT (v10): the grass workbench had TWO independently-toggleable
terminals (one research, one plan). v12 Wave 11 RETIRES the Research/Plan split:
the approved ``_mockups/grass_2_workbench.html`` is a ONE-session-per-idea
workbench (the single session advances research→plan IN-SESSION). These tests are
migrated HONESTLY to assert the new one-session structure (the v4 lesson — when
the UI is replaced, its UI tests follow the new UI), preserving the original
intent: the workbench's session terminal is collapsible and its session is NEVER
killed by collapsing.

POSITIVE — the workbench renders ONE labeled, collapsible terminal host (a single
``.gterm`` with a ``[data-grass-term]`` host + a ``.car`` collapse caret), NO
Research/Plan split (no ``data-dev`` develop buttons), and a single Open-session
control.

NEGATIVE — there is exactly ONE terminal host (never two lane hosts), and a
fresh idea renders the single ``.gterm`` collapsed with no bound session.

The Playwright interaction test (real Chromium) lives below, DEV-ONLY via
``pytest.importorskip``.
"""
import importlib
import re
import subprocess
import threading
import time
from html.parser import HTMLParser
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()
_DEVTEST = Path(__file__).resolve().parent.parent / "_devtest"


# ── Extract the selectGrassIdea HTML template from the JS source ────────────────

def _select_grass_idea_html():
    """Reconstruct the static markup selectGrassIdea() emits, by joining the
    single-quoted string literals in its ``var html = '' + ...;`` template."""
    import anchor_gui
    js = anchor_gui._PROJECT_WINDOW_JS
    m = re.search(r"function selectGrassIdea\(ideaId\)\s*\{([\s\S]*?)\n\}\n", js)
    assert m, "selectGrassIdea not found in _PROJECT_WINDOW_JS"
    body = m.group(1)
    hm = re.search(r"var html = ''([\s\S]*?);\n\s*work\.innerHTML = html;", body)
    assert hm, "selectGrassIdea html template not found"
    tmpl = hm.group(1)
    lits = re.findall(r"'((?:\\.|[^'\\])*)'", tmpl)
    joined = "".join(s.replace("\\'", "'") for s in lits)
    return joined


class _Collector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.els = []

    def handle_starttag(self, tag, attrs):
        self.els.append((tag, dict(attrs)))


def _parse(html):
    c = _Collector()
    c.feed(html)
    return c.els


# ── POSITIVE: ONE labeled, collapsible session terminal host ───────────────────

def test_one_session_terminal_host():
    """v12 W11: the workbench renders exactly ONE session terminal host (no
    research/plan split)."""
    html = _select_grass_idea_html()
    els = _parse(html)
    hosts = [d for t, d in els if d.get("data-grass-term")]
    assert len(hosts) == 1, \
        f"the one-session workbench must render ONE terminal host, got {len(hosts)}"
    gterms = [d for t, d in els
              if "gterm" in (d.get("class") or "").split()]
    assert len(gterms) == 1, f"expected one .gterm, got {len(gterms)}"


def test_session_terminal_has_a_collapse_toggle_caret():
    """The single .gterm carries a .car collapse caret + an Open-session control;
    NO Research/Plan develop buttons."""
    html = _select_grass_idea_html()
    els = _parse(html)
    cars = [d for t, d in els if "car" in (d.get("class") or "").split()]
    assert len(cars) >= 1, f"expected a collapse caret on the term bar, got {len(cars)}"
    # No data-dev develop buttons (the retired research/plan split).
    devbtns = [d.get("data-dev") for t, d in els if d.get("data-dev")]
    assert devbtns == [], f"the research/plan develop split must be gone: {devbtns}"
    # A single Open-session control instead.
    assert any("gopen" in (d.get("class") or "").split() for t, d in els), \
        "expected a single Open-session control"


# ── NEGATIVE: fresh idea → single collapsed host, no bound session ─────────────

def test_fresh_idea_single_collapsed_no_mounted_host():
    html = _select_grass_idea_html()
    els = _parse(html)
    gterms = [d for t, d in els
              if "gterm" in (d.get("class") or "").split()]
    assert len(gterms) == 1
    assert "collapsed" in (gterms[0].get("class") or "").split(), \
        "a fresh idea's session terminal should render collapsed"
    hosts = [d for t, d in els if d.get("data-grass-term")]
    assert hosts, "the session term host should exist in the markup"
    for d in hosts:
        assert "data-session" not in d, \
            "a fresh idea must not pre-bind the terminal host to a session"


def test_single_host_not_two_lane_hosts():
    """Guard the retired two-terminal regression: the workbench must render exactly
    ONE [data-grass-term] host, never a research + plan pair."""
    html = _select_grass_idea_html()
    hosts = [d for t, d in _parse(html) if d.get("data-grass-term")]
    assert len(hosts) == 1, f"expected ONE host, got {len(hosts)}"
    # The retired two-lane markers must be gone.
    seen = sorted(d.get("data-grass-term") for d in hosts)
    assert seen != ["plan", "research"], "the two-lane host split must be gone"


# ── Playwright (DEV-ONLY): the single session opens, collapse keeps it live ─────

def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)


def _have_git():
    try:
        return subprocess.run(["git", "--version"],
                              capture_output=True).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


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
    pid = proj["id"]
    import effort_history as eh
    idea = eh.add_idea(str(repo), pid, "Passive autonomous cooling loop",
                       notes="A natural-circulation decay-heat loop.")
    bundle = {"gui": gui, "pid": pid, "repo": repo,
              "idea_id": idea.get("job_id") or idea.get("id")}
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


@pytest.mark.skipif(not _have_git(), reason="git not on PATH")
def test_grass_single_session_toggle_in_browser(server):
    """v12 W11: open the grass workbench, select the idea, click Open session → the
    single terminal host mounts + a session binds; collapse the terminal → only the
    host hides while the session stays LIVE (collapse never kills). Screenshot →
    _devtest/wave3_grass_two_terminals.png. No JS console errors."""
    pytest.importorskip("playwright.sync_api")
    bundle, base, _ = server
    pid = bundle["pid"]

    import session_registry as reg
    from playwright.sync_api import sync_playwright
    _DEVTEST.mkdir(exist_ok=True)
    shot = _DEVTEST / "wave3_grass_two_terminals.png"

    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        errors = []
        pg.on("console",
              lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.goto(f"{base}/project/{pid}", wait_until="networkidle")
        from tests.ui_helpers import expand_workbench
        expand_workbench(pg)  # the Workbench tile now opens collapsed

        pg.wait_for_selector('[data-grass-tile="1"]', timeout=8000)
        pg.click('[data-grass-tile="1"]')
        pg.wait_for_selector('#grassPanel', timeout=8000)
        pg.wait_for_selector('#grassPanel .gli', timeout=8000)
        pg.eval_on_selector('#grassPanel .gli', "e=>e.click()")
        pg.wait_for_selector('#grassPanel .gwork .gterm[data-lane="research"]',
                             timeout=8000)

        # The single session terminal starts collapsed.
        assert pg.eval_on_selector(
            '#grassPanel .gterm[data-lane="research"]',
            "e=>e.classList.contains('collapsed')") is True

        # Click Open session → the host expands + a session binds.
        pg.click('#grassPanel .gwork .gopen')
        pg.wait_for_function(
            "document.querySelector('#grassPanel .gwork [data-grass-term]') && "
            "document.querySelector('#grassPanel .gwork [data-grass-term]')"
            ".getAttribute('data-session')", timeout=10000)
        sid = pg.eval_on_selector(
            '#grassPanel .gwork [data-grass-term]',
            "e=>e.getAttribute('data-session')")
        assert sid, "session terminal did not bind a session"

        # Exactly ONE host element (never two).
        one = pg.eval_on_selector_all(
            '#grassPanel .gwork [data-grass-term]', "els=>els.length")
        assert one == 1, f"expected ONE term host, got {one}"

        # The session is live in the registry.
        live = {r["session_id"] for r in reg.list_sessions(project_id=pid)
                if r.get("status") == "running"}
        assert sid in live, "the workbench session should be live"

        # Collapse the terminal (click its bar) → host hides, session stays live.
        pg.eval_on_selector('#grassPanel .gterm[data-lane="research"] .tbar',
                            "e=>e.click()")
        pg.wait_for_function(
            "document.querySelector('#grassPanel .gterm[data-lane=\"research\"]')"
            ".classList.contains('collapsed')", timeout=6000)
        live2 = {r["session_id"] for r in reg.list_sessions(project_id=pid)
                 if r.get("status") == "running"}
        assert sid in live2, "collapsing must NOT kill the session"

        pg.screenshot(path=str(shot), full_page=True)
        assert not errors, f"JS console errors: {errors}"
        b.close()

    assert shot.exists(), "screenshot not written"

    import terminal_session as ts
    for r in reg.list_sessions(project_id=pid):
        try:
            ts.kill(r["session_id"])
        except Exception:
            pass
