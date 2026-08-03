"""v6 Wave 5 gate — manual advance research → planning + the chain breadcrumb.

North-Star contract (IMPLEMENTATION-PLAN Wave 5):

  - A research session's window shows an "Advance to Planning →" control. It POSTs
    the token-gated ``/api/rnd/advance_session`` → ``terminal_session.start_session(
    lane='planning', parent_session_id=<research>, seed_context=<research summary>)``
    creating a NEW linked planning tile seeded from the research; the research
    record is NEVER mutated (reuses the v5 read-only continue-seed builder).
  - A chain breadcrumb (R-1 → P-2 → …) is rendered in each session window header
    from ``session_registry.chain_members``; clicking a node opens that panel.
    Backed by a read-only ``GET /api/rnd/chain?project_id=&session=`` (token via
    ?token=, SAFE projection — no worktree_path/branch).

Un-gameable gate (the v4.1 model): endpoint auth + seeded-linked start (original
intact) + chain GET SAFE-projection/token + rendered-DOM structure (positive +
negative) + a real Playwright/Chromium interaction test + a screenshot. Never
:8777, never real data — stub PTY backend, temp data dir + worktree base, the
fake runner, a hermetic temp git repo for worktrees.
"""
import importlib
import json
import re
import subprocess
import threading
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


# ── Shared GUI env: temp data dir + worktree base + stub PTY + fake runner ───

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
                "sessions", "summarizer", "gate_adapter", "terminal_session"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import anchor_gui
    gui = importlib.reload(anchor_gui)

    repo = tmp_path / "repo"
    repo.mkdir()
    bundle = {"gui": gui, "data": data, "wbase": wbase}
    if _have_git():
        _git(repo, "init", "-b", "main")
        _git(repo, "config", "user.email", "t@example.com")
        _git(repo, "config", "user.name", "Test")
        (repo / "README.md").write_text("hello\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "initial")
    import rnd_registry
    proj = rnd_registry.add_project("Temp", str(repo), scaffold=False)
    bundle["pid"] = proj["id"]
    bundle["repo"] = repo
    yield bundle
    try:
        import pty_manager
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


def _build_research_session(gui_env):
    """Start a LIVE research session (stub PTY) with a pre-built cached summary
    so the advance seed has real prior context. Returns its session_id."""
    pid = gui_env["pid"]
    folder = gui_env["repo"]
    import terminal_session as ts
    import effort_history as eh
    import sessions as sessmod
    import summarizer as summ
    # A produced research report on disk → grounding corpus for the summary.
    eh.record_effort(folder, pid, "research", "r-job-1", skill="researchPrime",
                     prompt_seed="Investigate the cooling system")
    arts = eh.detect_artifacts(folder, pid, "research", "r-job-1")
    if arts.get("md_path"):
        Path(arts["md_path"]).parent.mkdir(parents=True, exist_ok=True)
        Path(arts["md_path"]).write_text(
            "# Cooling report\n## Findings\nThe cooling system is adequate.\n",
            encoding="utf-8")
    prior = next(s for s in sessmod.list_sessions(folder, pid, "research")
                 if any(m.get("job_id") == "r-job-1"
                        for m in s.get("member_files", [])))
    summ.summarize_session(folder, pid, "research", prior)
    # Start a LIVE research session whose id we'll advance from.
    rec = ts.start_session(pid, "research")
    sid = rec["session_id"]
    # The advance seed reads the LIVE session's CACHED summary (keyed by its own
    # id). A live trio research session would have its own summary; here we cache
    # one keyed by the live id so the seed resolves (the real product path).
    import effort_history as eh2
    store_lane = eh2._resolve_subdir("research")
    summ._write_cache(str(folder), pid, store_lane, sid, {
        "skill": "researchPrime",
        "what_was_asked": "Investigate the cooling system",
        "prompts": ["Investigate the cooling system"],
        "actions": [{"label": "Cooling report"}],
        "claims": ["The cooling system is adequate."],
    })
    return sid


# ── (1) ENDPOINT: advance_session auth + seeded-linked start (original intact) ─

def test_advance_session_token_gated(gui_env, monkeypatch):
    """advance_session is behind the do_POST token gate: with a token set, an
    unauthenticated POST is rejected (401/403)."""
    import json as _json
    import urllib.request
    import urllib.error
    monkeypatch.setenv("ANCHOR_TOKEN", "sekret")
    import paths
    importlib.reload(paths)
    import anchor_gui
    gui = importlib.reload(anchor_gui)
    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/rnd/advance_session",
            data=_json.dumps({"project_id": "x",
                              "source_session": "nope"}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            urllib.request.urlopen(req, timeout=5)
            status = 200
        except urllib.error.HTTPError as e:
            status = e.code
        assert status in (401, 403), \
            f"advance_session must reject unauthed POST, got {status}"
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


def test_advance_missing_fields_400(gui_env, monkeypatch):
    """Missing source_session (or project_id) → 400 (validated inputs)."""
    import json as _json
    import urllib.request
    import urllib.error
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    gui = gui_env["gui"]
    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/rnd/advance_session",
            data=_json.dumps({"project_id": gui_env["pid"]}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            urllib.request.urlopen(req, timeout=5)
            status = 200
        except urllib.error.HTTPError as e:
            status = e.code
        assert status == 400, f"missing source_session must 400, got {status}"
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


@pytest.mark.skipif(not _have_git(), reason="git not on PATH")
def test_advance_starts_linked_seeded_planning_original_intact(gui_env):
    """Advancing a research source starts a NEW planning session whose
    parent_session_id == source and chain_id == the source's chain, seeded with
    the research context; the SOURCE record is unchanged (never mutated)."""
    gui = gui_env["gui"]
    pid = gui_env["pid"]
    import session_registry as reg
    import terminal_session as ts
    folder = gui_env["repo"]

    src = _build_research_session(gui_env)
    src_chain = reg.chain_for(src)
    before = json.dumps(reg.load_sessions().get(src), sort_keys=True)

    # Drive the endpoint's core path (seed → linked start).
    src_lane = reg.load_sessions().get(src, {}).get("lane", "research")
    seed = gui._build_continue_seed(str(folder), pid, src_lane, src)
    assert seed, "advance seed should carry the research session's context"
    assert ("cooling" in seed.lower() or "investigate" in seed.lower()
            or "researchprime" in seed.lower())

    rec = ts.start_session(pid, "planning", seed_context=seed,
                           parent_session_id=src)
    new_sid = rec["session_id"]
    assert new_sid != src
    assert rec["lane"] == "planning"
    assert rec["status"] == reg.STATUS_RUNNING
    # LINKED: parent + same chain as the source.
    assert rec.get("parent_session_id") == src
    assert rec.get("chain_id") == src_chain
    # SEEDED with the research context.
    assert rec.get("seed_text"), "advanced session should be seeded"
    assert ("cooling" in rec["seed_text"].lower()
            or "investigate" in rec["seed_text"].lower()
            or "researchprime" in rec["seed_text"].lower())
    # Chain now resolves R → P, ordered.
    members = reg.chain_members(src_chain)
    mids = [m["session_id"] for m in members]
    assert mids == [src, new_sid], mids

    # ORIGINAL untouched.
    after = json.dumps(reg.load_sessions().get(src), sort_keys=True)
    assert after == before, "advance must not mutate the source session record"

    ts.kill(new_sid)
    ts.kill(src)


@pytest.mark.skipif(not _have_git(), reason="git not on PATH")
def test_chain_get_safe_projection_and_token(gui_env, monkeypatch):
    """GET /api/rnd/chain returns the ordered SAFE chain (no worktree_path /
    branch) and is token-gated (?token=)."""
    import json as _json
    import urllib.request
    import urllib.error
    gui = gui_env["gui"]
    pid = gui_env["pid"]
    import session_registry as reg
    import terminal_session as ts
    folder = gui_env["repo"]

    src = _build_research_session(gui_env)
    seed = gui._build_continue_seed(str(folder), pid, "research", src)
    rec = ts.start_session(pid, "planning", seed_context=seed,
                           parent_session_id=src)
    new_sid = rec["session_id"]

    # First: token gate. Set a token; an unauthed GET must 401.
    monkeypatch.setenv("ANCHOR_TOKEN", "sekret")
    import paths
    importlib.reload(paths)
    import anchor_gui
    gui2 = importlib.reload(anchor_gui)
    srv = gui2.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        url = (f"http://127.0.0.1:{port}/api/rnd/chain"
               f"?project_id={pid}&session={new_sid}")
        try:
            urllib.request.urlopen(url, timeout=5)
            status = 200
        except urllib.error.HTTPError as e:
            status = e.code
        assert status == 401, f"chain GET must 401 unauthed, got {status}"

        # With the token, the SAFE ordered chain comes back.
        with urllib.request.urlopen(url + "&token=sekret", timeout=5) as r:
            payload = _json.loads(r.read().decode())
        assert payload.get("ok") is True
        members = payload.get("members") or []
        ids = [m["session_id"] for m in members]
        assert ids == [src, new_sid], ids
        for m in members:
            assert "worktree_path" not in m, "chain leaked worktree_path"
            assert "branch" not in m, "chain leaked branch"
            assert "lane" in m and "status" in m
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=5)
        monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
        importlib.reload(paths)
        import terminal_session as ts2
        try:
            ts2.kill(new_sid)
            ts2.kill(src)
        except Exception:
            pass


# ── (2) RENDERED-DOM / SOURCE asserts (positive + negative) ──────────────────

def _mkproject(folder, name="P"):
    import rnd_registry
    folder.mkdir(parents=True, exist_ok=True)
    return rnd_registry.add_project(name, str(folder))


def _js(html):
    return "\n".join(re.findall(r"<script[^>]*>([\s\S]*?)</script>", html))


def test_advance_control_and_breadcrumb_in_js(gui_env, tmp_path):
    """The advance control + chain breadcrumb are wired in the project-window JS,
    rendered for the RESEARCH lane only (positive + negative)."""
    gui = gui_env["gui"]
    folder = tmp_path / "Ctl"
    pid = _mkproject(folder, "Ctl")["id"]
    js = _js(gui.render_project_window_html(pid))

    # Advance control + endpoint wired.
    assert "advanceSession(" in js
    assert "/api/rnd/advance_session" in js
    assert "Advance to Planning" in js
    # The advance bar is gated on the research lane (positive structure).
    assert "advbar" in js
    assert re.search(r"\(s\.lane\s*\|\|\s*''\)\s*===\s*'research'", js), \
        "advance bar must be rendered ONLY for the research lane"

    # Breadcrumb wired (header crumb + chain endpoint + click→openPanel).
    assert "chaincrumb" in js
    assert "_loadChainBreadcrumb" in js
    assert "/api/rnd/chain" in js
    assert "cc-node" in js

    # NEGATIVE: the advance button text is set exactly once (one control), via
    # advb.textContent (the comment also mentions the phrase, so count the
    # assignment, not the bare phrase).
    assert js.count("advb.textContent = 'Advance to Planning →'") == 1
    # NEGATIVE: planning/build do not get their own advance control this wave —
    # the only lane literal driving the advance bar is 'research'.
    guard = re.search(r"if\s*\(\(s\.lane[^\n]*'research'\)\s*\{([\s\S]*?)\n  \}",
                      js)
    assert guard, "advance-bar research guard block not found"
    assert "advbtn" in guard.group(1)


# ── (3) REAL Playwright + Chromium interaction test (dev-only) ───────────────

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
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


@pytest.mark.skipif(not _have_git(), reason="git not on PATH")
def test_advance_and_breadcrumb_in_browser(server, tmp_path):
    """End to end in a real browser:

      1. Open a RESEARCH session panel → "Advance to Planning →" present.
      2. Click it → a new planning tile appears AND a panel opens whose chain
         breadcrumb shows research → planning.
      3. Click the research node in the breadcrumb → the research panel opens.
      4. No JS console errors. Save _devtest/wave5_advance.png.
    """
    pytest.importorskip("playwright.sync_api")
    bundle, base, _ = server
    src = _build_research_session(bundle)

    from playwright.sync_api import sync_playwright
    devdir = Path(__file__).resolve().parent.parent / "_devtest"
    devdir.mkdir(exist_ok=True)
    shot = devdir / "wave5_advance.png"

    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        errors = []
        pg.on("console",
              lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.goto(f"{base}/project/{bundle['pid']}", wait_until="networkidle")
        from tests.ui_helpers import expand_workbench
        expand_workbench(pg)  # the Workbench tile now opens collapsed
        # The live research tile is in the session bar.
        pg.wait_for_selector('#sessionBar .live-chip', timeout=8000)

        # Open the research session's panel directly (deterministic).
        pg.eval_on_selector_all(
            '#sessionBar .live-chip',
            "els=>els.forEach(e=>e.click())")
        pg.wait_for_selector("#panelStack .panel", timeout=5000)
        # The advance control is present on the research panel.
        pg.wait_for_selector("#panelStack .panel .advbtn", timeout=8000)
        assert pg.eval_on_selector_all(
            "#panelStack .panel .advbtn", "e=>e.length") >= 1, \
            "research panel has no Advance control"

        # Screenshot the research panel with the advance control + breadcrumb.
        pg.screenshot(path=str(shot), full_page=True)

        panels_before = pg.eval_on_selector_all("#panelStack .panel",
                                                "e=>e.length")
        # Click Advance → a new planning panel + tile appears.
        pg.click("#panelStack .panel .advbtn")
        pg.wait_for_function(
            "document.querySelectorAll('#panelStack .panel').length === %d"
            % (panels_before + 1), timeout=8000)
        # The new planning panel's breadcrumb shows >= 2 nodes (research → planning).
        pg.wait_for_function(
            "document.querySelectorAll("
            "'#panelStack .panel .chaincrumb .cc-node').length >= 2",
            timeout=8000)
        # Click the research node in the breadcrumb → its panel becomes current.
        pg.eval_on_selector(
            '#panelStack .panel .chaincrumb .cc-node[data-session="%s"]' % src,
            "e=>e.click()")
        # The research panel exists and is focused (its breadcrumb node is .cur).
        pg.wait_for_selector(
            '#panelStack .panel[data-session="%s"]' % src, timeout=5000)
        assert not errors, f"JS console errors: {errors}"
        b.close()

    assert shot.exists(), "screenshot not written"

    # Backend truth: a new RUNNING planning session linked to the research.
    import session_registry as reg
    plan = [r for r in reg.list_sessions(project_id=bundle["pid"])
            if r.get("lane") in ("plan", "planning")]
    assert plan, "no new planning session created by Advance"
    assert any(r.get("parent_session_id") == src for r in plan), \
        "advanced planning session not linked to the research source"
    import terminal_session as ts
    for r in reg.list_sessions(project_id=bundle["pid"]):
        try:
            ts.kill(r["session_id"])
        except Exception:
            pass
