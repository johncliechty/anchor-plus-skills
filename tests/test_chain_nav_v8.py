"""v8 Wave 7 — Full chain navigation on the now-durable artifacts.

From ANY session's panel/tile, the linked chain (research↔plan↔build via
``session_registry.chain_members``) renders as clickable breadcrumb nodes; clicking
a sibling opens THAT session's detail (the W5 read-only summary + produced docs +
"Continue the dialog") if it is done/historical, or focuses/attaches it if it is
live. Works for partial chains — a research session with no downstream, or a build
with no upstream, shows only the records that actually exist (no fabricated nodes).
A single-session chain renders no misleading breadcrumb.

This wave is UI-only: it builds on the v6 breadcrumb (``_loadChainBreadcrumb`` +
``cc-node``), the v6 chain GET (``/api/rnd/chain``, SAFE projection, ``?token=``),
``openPanel`` (live→attach / done→W5 detail), and the now-durable W2/W5 records —
nothing is forked.

Un-gameable gate (the v4.1 model): backend chain truth (ordered members + SAFE
projection + honest partial chains) + rendered-DOM structure (positive + negative)
+ a real Playwright/Chromium back-and-forth navigation test + a screenshot. NEVER
:8777, NEVER real data — stub PTY backend, temp data dir + worktree base, the fake
runner, a hermetic temp git repo for worktrees.
"""
import importlib
import json
import re
import subprocess
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()
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


def _build_chain(gui_env):
    """Start a 3-session linked chain research→plan→build via the real
    start_session(parent_session_id=…) path (stub PTY). Returns the ids."""
    import terminal_session as ts
    pid = gui_env["pid"]
    r = ts.start_session(pid, "research", backend="claude")
    rid = r["session_id"]
    p = ts.start_session(pid, "planning", backend="claude",
                         parent_session_id=rid)
    pid_sid = p["session_id"]
    b = ts.start_session(pid, "build", backend="claude",
                         parent_session_id=pid_sid)
    bid = b["session_id"]
    return {"research": rid, "plan": pid_sid, "build": bid}


def _js(html):
    return "\n".join(re.findall(r"<script[^>]*>([\s\S]*?)</script>", html))


# ════════════════════════════════════════════════════════════════════════════
# (1) BACKEND: chain_members ordered + chain GET SAFE projection + partial chains
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.skipif(not _have_git(), reason="git not on PATH")
def test_chain_members_ordered_for_3_session_chain(gui_env):
    """chain_members returns the ordered linked siblings research→plan→build for a
    3-session chain (the breadcrumb's data source)."""
    import session_registry as reg
    ids = _build_chain(gui_env)
    chain = reg.chain_for(ids["build"])
    members = reg.chain_members(chain)
    assert [m["lane"] for m in members] == ["research", "planning", "build"]
    assert [m["session_id"] for m in members] == \
        [ids["research"], ids["plan"], ids["build"]]
    # Every member shares the one chain; each child links to its parent.
    assert all(m.get("chain_id") == chain for m in members)
    plan = reg.get_session(ids["plan"])
    build = reg.get_session(ids["build"])
    assert plan["parent_session_id"] == ids["research"]
    assert build["parent_session_id"] == ids["plan"]
    import terminal_session as ts
    for sid in ids.values():
        ts.kill(sid)


@pytest.mark.skipif(not _have_git(), reason="git not on PATH")
def test_chain_get_carries_lane_label_status_safe(gui_env, monkeypatch):
    """GET /api/rnd/chain emits, for EACH of the 3 nodes, lane + label + status
    (so a node renders its lane + a short label/status) and NEVER leaks
    worktree_path / branch. Token-gated (?token=)."""
    gui = gui_env["gui"]
    pid = gui_env["pid"]
    ids = _build_chain(gui_env)

    monkeypatch.setenv("ANCHOR_TOKEN", "sekret")
    import paths
    importlib.reload(paths)
    import anchor_gui
    gui2 = importlib.reload(anchor_gui)
    srv = gui2.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        url = (f"http://127.0.0.1:{port}/api/rnd/chain"
               f"?project_id={pid}&session={ids['build']}")
        # Unauthed → 401.
        try:
            urllib.request.urlopen(url, timeout=5)
            status = 200
        except urllib.error.HTTPError as e:
            status = e.code
        assert status == 401, f"chain GET must 401 unauthed, got {status}"

        with urllib.request.urlopen(url + "&token=sekret", timeout=5) as r:
            payload = json.loads(r.read().decode())
        assert payload.get("ok") is True
        members = payload.get("members") or []
        assert [m["session_id"] for m in members] == \
            [ids["research"], ids["plan"], ids["build"]]
        for m in members:
            # lane + status present so the node can show them; label key carried.
            assert "lane" in m and m["lane"]
            assert "status" in m
            assert "label" in m
            # SAFE: no worktree_path / branch leak.
            assert "worktree_path" not in m, "chain leaked worktree_path"
            assert "branch" not in m, "chain leaked branch"
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=5)
        monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
        importlib.reload(paths)
        import terminal_session as ts
        for sid in ids.values():
            try:
                ts.kill(sid)
            except Exception:
                pass


@pytest.mark.skipif(not _have_git(), reason="git not on PATH")
def test_partial_chain_research_only_has_one_node(gui_env):
    """A research session with NO downstream is a singleton chain → chain_members
    returns ONLY that node (no fabricated plan/build siblings)."""
    import session_registry as reg
    import terminal_session as ts
    pid = gui_env["pid"]
    r = ts.start_session(pid, "research", backend="claude")
    rid = r["session_id"]
    members = reg.chain_members(reg.chain_for(rid))
    assert [m["session_id"] for m in members] == [rid]
    assert [m["lane"] for m in members] == ["research"]
    ts.kill(rid)


@pytest.mark.skipif(not _have_git(), reason="git not on PATH")
def test_partial_chain_build_no_upstream_has_one_node(gui_env):
    """A build started with NO parent (no research/plan upstream) is its own
    singleton chain → only the build node exists (honest, no fabricated upstream)."""
    import session_registry as reg
    import terminal_session as ts
    pid = gui_env["pid"]
    b = ts.start_session(pid, "build", backend="claude")
    bid = b["session_id"]
    members = reg.chain_members(reg.chain_for(bid))
    assert [m["session_id"] for m in members] == [bid]
    assert [m["lane"] for m in members] == ["build"]
    ts.kill(bid)


# ════════════════════════════════════════════════════════════════════════════
# (2) RENDERED-DOM / SOURCE asserts (positive + negative)
# ════════════════════════════════════════════════════════════════════════════

def test_breadcrumb_nav_wired_in_js(gui_env):
    """The chain breadcrumb is wired in the project-window JS: a node per linked
    sibling, each clickable → openPanel(thatId) (which routes live→attach,
    done→W5 detail), and it renders unconditionally for EVERY panel."""
    gui = gui_env["gui"]
    pid = gui_env["pid"]
    js = _js(gui.render_project_window_html(pid))

    # The breadcrumb seam + the chain GET + the clickable node class are present.
    assert "_loadChainBreadcrumb" in js
    assert "/api/rnd/chain" in js
    assert "cc-node" in js
    # Each node is clickable → openPanel(thatId) (live→focus / done→W5 detail).
    assert re.search(r"openPanel\(theId\)", js), \
        "a chain node must open/focus that session's panel"
    # v8 W7: each node shows a status LIGHT (lane+status visible per node).
    assert "cc-light" in js
    assert "_statusColor(m.status" in js, \
        "each node's light must reflect that member's status"

    # openPanel calls _loadChainBreadcrumb UNCONDITIONALLY (so done/historical
    # panels get the breadcrumb too, not only live ones).
    op = re.search(r"function openPanel\(sessionId\)\s*\{([\s\S]*?)\n  renderSessionBar\(\);\n\}",
                   js)
    assert op, "openPanel body not found"
    assert "_loadChainBreadcrumb(sessionId, crumb)" in op.group(1), \
        "openPanel must load the breadcrumb for every panel (live + historical)"

    # openPanel synthesizes a record for a NON-live tile (so a done/historical
    # tile still opens a panel with the breadcrumb).
    assert "_synthSessionRecord(sessionId)" in op.group(1)


def test_partial_chain_renders_no_fabricated_nodes_in_js(gui_env):
    """NEGATIVE: a registry chain of fewer than 2 members renders NO fabricated
    sibling nodes — the guard `members.length < 2` short-circuits BEFORE the
    server-members loop. (The short-circuit branch now falls back to the
    build→planning *static tie*, which is a real, doc-grounded link read off the
    tile — not a synthesized registry sibling; its honesty is asserted below.)"""
    gui = gui_env["gui"]
    pid = gui_env["pid"]
    js = _js(gui.render_project_window_html(pid))
    fn = re.search(r"function _loadChainBreadcrumb\(sessionId, host\)\s*\{"
                   r"([\s\S]*?)\n}\n", js)
    assert fn, "_loadChainBreadcrumb not found"
    body = fn.group(1)
    # The < 2 guard still exists and short-circuits to a return (no server nodes).
    assert "if (members.length < 2)" in body, \
        "a lone/partial registry chain must not build server sibling nodes"
    guard = re.search(r"if \(members\.length < 2\) \{([\s\S]*?)\}", body)
    assert guard and "return;" in guard.group(1), \
        "the < 2 branch must return before the members loop"
    # The ONLY thing the short-circuit branch renders is the static tie helper.
    assert "_renderStaticTieCrumb(sessionId, host)" in guard.group(1)
    # The registry nodes are built ONLY from the server's `members` list.
    assert "members.forEach" in body

    # HONESTY of the static-tie fallback: it renders nothing unless the tile
    # actually carries a data-linked-planning target (no fabricated tie).
    tie = re.search(r"function _renderStaticTieCrumb\(sessionId, host\)\s*\{"
                    r"([\s\S]*?)\n}\n", js)
    assert tie, "_renderStaticTieCrumb not found"
    assert "data-linked-planning" in tie.group(1)
    assert "if (!planSid) return;" in tie.group(1), \
        "no tie on the tile → render nothing"


# ════════════════════════════════════════════════════════════════════════════
# (3) REAL Playwright + Chromium — back-and-forth chain navigation
# ════════════════════════════════════════════════════════════════════════════

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
def test_chain_navigation_in_browser(server):
    """End to end in a real browser:

      1. Build a 3-session chain research→plan→build (linked sessions).
      2. Open the BUILD session panel → its breadcrumb shows 3 nodes
         (research + plan + build).
      3. Click the RESEARCH node → the research session's panel opens/focuses
         (its detail/terminal), and that panel exists.
      4. Click back to the BUILD node → the build panel is focused again.
      5. No JS console errors. Screenshot _devtest/wave7_chain.png.
    """
    pytest.importorskip("playwright.sync_api")
    bundle, base, _ = server
    ids = _build_chain(bundle)

    from playwright.sync_api import sync_playwright
    DEVTEST.mkdir(exist_ok=True)
    shot = DEVTEST / "wave7_chain.png"

    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1280, "height": 1000})
            errors = []
            pg.on("console",
                  lambda m: errors.append(m.text) if m.type == "error" else None)
            pg.goto(f"{base}/project/{bundle['pid']}", wait_until="networkidle")
            from tests.ui_helpers import expand_workbench
            expand_workbench(pg)  # the Workbench tile now opens collapsed

            # The 3 live chips are present; open the BUILD session's panel.
            build_chip = '#sessionBar .live-chip[data-session="%s"]' % ids["build"]
            pg.wait_for_selector(build_chip, timeout=8000)
            pg.click(build_chip)
            build_panel = '#panelStack .panel[data-session="%s"]' % ids["build"]
            pg.wait_for_selector(build_panel, timeout=5000)

            # The build panel's breadcrumb shows 3 linked nodes (R → P → B).
            pg.wait_for_function(
                "document.querySelectorAll('%s .chaincrumb .cc-node').length === 3"
                % build_panel, timeout=8000)
            # Each node carries a status light (lane+status visible per node).
            assert pg.eval_on_selector_all(
                "%s .chaincrumb .cc-node .cc-light" % build_panel,
                "e=>e.length") == 3, "each chain node must show a status light"

            pg.screenshot(path=str(shot), full_page=True)

            # Click the RESEARCH node in the build panel's breadcrumb → its panel
            # opens/focuses (back-navigation build→research).
            res_node = ('%s .chaincrumb .cc-node[data-session="%s"]'
                        % (build_panel, ids["research"]))
            pg.eval_on_selector(res_node, "e=>e.click()")
            res_panel = '#panelStack .panel[data-session="%s"]' % ids["research"]
            pg.wait_for_selector(res_panel, timeout=5000)

            # Forward-navigate again: click the BUILD node in the research panel's
            # breadcrumb → the build panel is focused again.
            build_node = ('%s .chaincrumb .cc-node[data-session="%s"]'
                          % (res_panel, ids["build"]))
            pg.wait_for_selector(build_node, timeout=5000)
            pg.eval_on_selector(build_node, "e=>e.click()")
            pg.wait_for_selector(build_panel, timeout=5000)

            assert not errors, f"JS console errors: {errors}"
            b.close()

        assert shot.exists(), "screenshot not written"
    finally:
        import terminal_session as ts
        for sid in ids.values():
            try:
                ts.kill(sid)
            except Exception:
                pass
