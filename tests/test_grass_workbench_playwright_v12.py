"""v12 Wave 11 — Grass one-session workbench: real Chromium interaction test
(machine-checkable).

DEV-ONLY (``pytest.importorskip("playwright.sync_api")``; Playwright is NEVER
imported by product code). The W11 falsifiable interactions, each with
MACHINE-CHECKABLE pass conditions (not "element exists"):

  (a) select an idea on the LEFT list → its RIGHT one-session workbench opens with
      ONE session terminal that ATTACHES (Open session → the xterm mounts + binds a
      session id); NO Research/Plan develop split.
  (b) **Migrate to project ↑** → POST /api/rnd/grass_export is called, the idea
      STAYS in grass marked promoted, and grass_origin is stamped on the exported
      lane effort (server truth).
  (c) ✕ on an idea row → POST /api/rnd/grass_delete; the idea then APPEARS in the
      per-project Boneyard tab (assert GET /api/rnd/boneyard contains it — not just
      that a toast fired).
  (d) the grass second-advance is NOT offered for a v12 idea (no data-advance
      control in the workbench; the single session advances IN-SESSION).

Hermetic: ``ANCHOR_PTY_BACKEND=stub`` + fake runner + a temp git repo + tmp data +
tmp worktree base; a free port != 8777; ``ANCHOR_PROACTIVE_SUMMARY`` OFF. NEVER
binds ``:8777`` / touches real data / network.
"""
import importlib
import json
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()
_DEVTEST = Path(__file__).resolve().parent.parent / "_devtest"


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
    for lane in ("RESEARCH", "PLAN", "PLANNING", "BUILD", "GRASS"):
        monkeypatch.delenv("ANCHOR_SEED_PROMPT_" + lane, raising=False)

    for mod in ("paths", "job_runner", "pty_manager", "rnd_registry",
                "session_registry", "worktrees", "lanes", "effort_history",
                "sessions", "summarizer", "boneyard", "handoff",
                "terminal_session", "effort_view"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import anchor_gui
    gui = importlib.reload(anchor_gui)

    import effort_history
    import rnd_registry
    import session_registry
    import terminal_session
    import boneyard

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
    bundle = {
        "gui": gui, "eh": effort_history, "rnd": rnd_registry,
        "reg": session_registry, "ts": terminal_session, "bone": boneyard,
        "repo": repo, "pid": pid,
    }
    yield bundle
    try:
        import pty_manager
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


def _get_json(url):
    with urllib.request.urlopen(url, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ── (a) select idea → one-session workbench opens + attaches; no R/P split ─────

def test_select_idea_opens_one_session_workbench(server):
    pytest.importorskip("playwright.sync_api")
    env, base, _ = server
    eh, pid = env["eh"], env["pid"]
    idea = eh.add_idea(env["repo"], pid, "Passive decay-heat removal loop")
    iid = idea["job_id"]

    from playwright.sync_api import sync_playwright
    _DEVTEST.mkdir(exist_ok=True)
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
        pg.wait_for_selector(f"#grassPanel .gli[data-idea='{iid}']", timeout=8000)
        pg.click(f"#grassPanel .gli[data-idea='{iid}']")
        # The right one-session workbench renders.
        pg.wait_for_selector("#grassPanel .gwork .gsession", timeout=6000)
        # MACHINE-CHECKABLE: exactly ONE session terminal host (no R/P split) and
        # NO develop buttons.
        assert pg.eval_on_selector_all(
            "#grassPanel .gwork [data-grass-term]", "e=>e.length") == 1
        assert pg.eval_on_selector_all(
            "#grassPanel .gwork [data-dev]", "e=>e.length") == 0, \
            "the one-session workbench must NOT render develop buttons"
        assert pg.eval_on_selector_all(
            "#grassPanel .gwork [data-advance]", "e=>e.length") == 0, \
            "no Advance-to-Plan control (research→plan advances in-session)"
        # Open the single session → its xterm ATTACHES + binds a session id.
        pg.click("#grassPanel .gwork .gopen")
        pg.wait_for_selector("#grassPanel .gwork [data-grass-term] .xterm",
                             timeout=8000)
        sid = pg.eval_on_selector(
            "#grassPanel .gwork [data-grass-term]",
            "e=>e.getAttribute('data-session')")
        assert sid, "the workbench session terminal did not attach a session id"
        # W11-R2-01: the transport actually CONNECTS (not just an xterm shell) —
        # match the W10 machine-checkable standard (WS/SSE readyState OPEN === 1).
        pg.wait_for_function(
            "sid=>window.PANELS && window.PANELS[sid] && window.PANELS[sid].transport"
            " && window.PANELS[sid].transport.readyState === 1",
            arg=sid, timeout=8000)
        pg.screenshot(path=str(_DEVTEST / "w11_grass_select.png"), full_page=True)
        assert not errors, f"JS console errors: {errors}"
        b.close()

    import terminal_session as ts
    for r in env["reg"].list_sessions(project_id=pid):
        try:
            ts.kill(r["session_id"])
        except Exception:
            pass


# ── (b) Migrate to project ↑ → export_grass_to_project (idea stays, grass_origin) ─

def test_migrate_to_project_calls_export(server):
    pytest.importorskip("playwright.sync_api")
    env, base, _ = server
    eh, reg, pid = env["eh"], env["reg"], env["pid"]
    idea = eh.add_idea(env["repo"], pid, "Operator daily-brief generator")
    iid = idea["job_id"]
    # Pre-build a live workbench session + a produced doc so export has material.
    rec = eh.develop_grass_workbench(pid, iid)
    sid = rec["session_id"]
    wt = Path(reg.get_session(sid)["worktree_path"])
    (wt / "research").mkdir(parents=True, exist_ok=True)
    (wt / "research" / "brief.md").write_text("# brief\n", encoding="utf-8")

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        errors = []
        pg.on("console",
              lambda m: errors.append(m.text) if m.type == "error" else None)
        export_called = {"ok": False}

        def _on_resp(resp):
            if "/api/rnd/grass_export" in resp.url:
                export_called["ok"] = True
        pg.on("response", _on_resp)
        pg.on("dialog", lambda d: d.accept())
        pg.goto(f"{base}/project/{pid}", wait_until="networkidle")
        from tests.ui_helpers import expand_workbench
        expand_workbench(pg)  # the Workbench tile now opens collapsed
        pg.click('[data-grass-tile="1"]')
        pg.wait_for_selector(f"#grassPanel .gli[data-idea='{iid}']", timeout=8000)
        pg.click(f"#grassPanel .gli[data-idea='{iid}']")
        pg.wait_for_selector("#grassPanel .gwork .gmigrate", timeout=6000)
        pg.click("#grassPanel .gwork .gmigrate")
        # MACHINE-CHECKABLE: the export endpoint was called.
        for _ in range(50):
            if export_called["ok"]:
                break
            pg.wait_for_timeout(100)
        assert export_called["ok"], "Migrate did not call /api/rnd/grass_export"
        assert not errors, f"JS console errors: {errors}"
        b.close()

    # SERVER TRUTH: the idea STAYS in grass marked promoted; grass_origin is
    # stamped on the exported lane effort.
    after = eh.get_grass_idea(env["repo"], pid, iid)
    assert after is not None, "Migrate must NOT destroy the idea (copy-never-destroy)"
    assert eh.grass_status(after) == eh.GRASS_PROMOTED
    rlane = eh.list_efforts(env["repo"], pid, "research")
    exp = [e for e in rlane if e.get("from_grass_idea") == iid]
    assert exp, "no exported research lane effort"
    assert exp[0].get("grass_origin") == iid, "grass_origin not stamped on export"

    import terminal_session as ts
    for r in reg.list_sessions(project_id=pid):
        try:
            ts.kill(r["session_id"])
        except Exception:
            pass


# ── (c) ✕ → grass_delete → the idea appears in the Boneyard tab ───────────────

def test_delete_idea_lands_in_boneyard_tab(server):
    pytest.importorskip("playwright.sync_api")
    env, base, _ = server
    eh, pid = env["eh"], env["pid"]
    victim = eh.add_idea(env["repo"], pid, "moltensalt buffer tank idea")["job_id"]
    sibling = eh.add_idea(env["repo"], pid, "KEEP ME idea")["job_id"]

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        errors = []
        pg.on("console",
              lambda m: errors.append(m.text) if m.type == "error" else None)
        delete_called = {"ok": False}

        def _on_resp(resp):
            if "/api/rnd/grass_delete" in resp.url:
                delete_called["ok"] = True
        pg.on("response", _on_resp)
        pg.on("dialog", lambda d: d.accept())   # accept the confirm()
        pg.goto(f"{base}/project/{pid}", wait_until="networkidle")
        from tests.ui_helpers import expand_workbench
        expand_workbench(pg)  # the Workbench tile now opens collapsed
        pg.click('[data-grass-tile="1"]')
        victim_sel = f"#grassPanel .gli[data-idea='{victim}']"
        pg.wait_for_selector(victim_sel, timeout=8000)
        # Click the red ✕ on the victim row.
        pg.click(victim_sel + " .gli-del")
        # MACHINE-CHECKABLE: grass_delete was called AND the row disappears.
        for _ in range(50):
            if delete_called["ok"]:
                break
            pg.wait_for_timeout(100)
        assert delete_called["ok"], "✕ did not call /api/rnd/grass_delete"
        pg.wait_for_function(
            "document.querySelectorAll(\"#grassPanel .gli[data-idea='%s']\")"
            ".length === 0" % victim, timeout=8000)
        assert not errors, f"JS console errors: {errors}"
        b.close()

    # MACHINE-CHECKABLE (the real signal, not just a toast): the deleted idea is
    # now in the per-project Boneyard — GET /api/rnd/boneyard contains it.
    data = _get_json(base + "/api/rnd/boneyard?project_id=" + pid + "&q=")
    assert data["ok"] is True
    titles = " ".join((e.get("title", "") + " " + e.get("idea_text", ""))
                      for e in data["entries"]).lower()
    assert "moltensalt" in titles, \
        "the deleted idea must appear in the Boneyard (not just a toast)"
    assert any(e.get("source") == "grass-deleted" for e in data["entries"])
    # The sibling idea is untouched (still in grass).
    assert eh.get_grass_idea(env["repo"], pid, sibling) is not None


# ── (d) second-advance NOT offered for a v12 idea (in-session advance) ─────────

def test_no_grass_second_advance_for_v12_idea(server):
    """The workbench renders NO Advance-to-Plan control for a v12 idea; the single
    workbench session advances IN-SESSION (advance_stage), and the legacy
    grass_advance endpoint early-returns for an effort_managed idea (server truth)."""
    pytest.importorskip("playwright.sync_api")
    env, base, _ = server
    eh, reg, pid = env["eh"], env["reg"], env["pid"]
    idea = eh.add_idea(env["repo"], pid, "Digital-twin drift alarms")
    iid = idea["job_id"]
    rec = eh.develop_grass_workbench(pid, iid)   # effort_managed=True
    sset0 = {r["session_id"] for r in reg.list_sessions(project_id=pid)}

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.goto(f"{base}/project/{pid}", wait_until="networkidle")
        from tests.ui_helpers import expand_workbench
        expand_workbench(pg)  # the Workbench tile now opens collapsed
        pg.click('[data-grass-tile="1"]')
        pg.wait_for_selector(f"#grassPanel .gli[data-idea='{iid}']", timeout=8000)
        pg.click(f"#grassPanel .gli[data-idea='{iid}']")
        pg.wait_for_selector("#grassPanel .gwork .gsession", timeout=6000)
        # NO Advance-to-Plan control in the one-session workbench.
        assert pg.eval_on_selector_all(
            "#grassPanel .gwork [data-advance]", "e=>e.length") == 0, \
            "a v12 idea must not be offered the grass second-advance"
        b.close()

    # SERVER TRUTH: the legacy grass_advance early-returns for the effort_managed
    # idea — no second grass session minted (SET equality).
    payload = json.dumps({"project_id": pid, "idea_id": iid}).encode("utf-8")
    req = urllib.request.Request(base + "/api/rnd/grass_advance", data=payload,
                                 method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=8) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    assert data["ok"] is False
    assert data["reason"] == "effort-managed-use-advance-stage", data
    sset1 = {r["session_id"] for r in reg.list_sessions(project_id=pid)}
    assert sset1 == sset0, "a second grass session was minted for a v12 idea"

    import terminal_session as ts
    for r in reg.list_sessions(project_id=pid):
        try:
            ts.kill(r["session_id"])
        except Exception:
            pass
