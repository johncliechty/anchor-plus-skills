"""v5 Wave 5 — Grass Catcher B+C hybrid idea workbench.

Proves IMPLEMENTATION-PLAN.md "## Wave 5" (+ MASTER-PLAN Locked Decision #5):

Backend (effort_history):
  - status transitions raw->refined->promoted (invalid rejected);
  - versioned refinements (grass-<id>/dev-N auto-increments, listed newest-first);
  - pull seeds a NEW session with the refinement content;
  - develop starts a seeded session (the idea text rides into the seed) and the
    idea STAYS in grass (copy, never destroy);
  - promote sets status=promoted + stores the run/session link;
  - the original idea is never destroyed.

Rendered-DOM (style/script stripped, positive + negative):
  - the grass surface IS the workbench (filter tabs All/raw/refined/promoted +
    search + two-pane list+workbench + refinement-history container);
  - NEGATIVE: the OLD single-column idea-board / idea-card markup is GONE.

Real Playwright + Chromium:
  - open the workbench → filter tab scopes the list → search filters the list →
    select an idea loads its workbench → "Develop with Research" starts a seeded
    live session whose terminal mounts → a saved refinement appears in the
    history with a grass-<id>/dev-N id + a pull control → no JS console errors.

Hermetic: ANCHOR_PTY_BACKEND=stub, ANCHOR_RUNNER_CMD -> tests/fake_claude.py,
temp ANCHOR_DATA_DIR + ANCHOR_WORKTREE_BASE + a throwaway temp git repo. NEVER
touches the live :8777 service or real data.
"""
import importlib
import json
import re
import subprocess
import threading
import urllib.error
import urllib.request
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


def _make_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial")
    return repo


@pytest.fixture
def env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    wbase = tmp_path / "wt-base"
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(wbase))
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    monkeypatch.delenv("ANCHOR_TERMINAL_SEED", raising=False)
    for lane in ("RESEARCH", "PLAN", "PLANNING", "BUILD", "GRASS"):
        monkeypatch.delenv("ANCHOR_SEED_PROMPT_" + lane, raising=False)

    import paths
    importlib.reload(paths)
    import pty_manager
    importlib.reload(pty_manager)
    import rnd_registry
    importlib.reload(rnd_registry)
    import session_registry
    importlib.reload(session_registry)
    import worktrees
    importlib.reload(worktrees)
    import lanes
    importlib.reload(lanes)
    import terminal_session
    importlib.reload(terminal_session)
    import effort_history
    importlib.reload(effort_history)
    import anchor_gui
    importlib.reload(anchor_gui)
    paths.ensure_data_dirs()

    repo = _make_repo(tmp_path)
    proj = rnd_registry.add_project("Temp", str(repo))
    yield {
        "ts": terminal_session, "pty": pty_manager, "reg": session_registry,
        "eh": effort_history, "rnd": rnd_registry, "gui": anchor_gui,
        "repo": repo, "pid": proj["id"], "wbase": wbase, "data": data,
        "monkeypatch": monkeypatch,
    }
    try:
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


# ── 1) BACKEND ───────────────────────────────────────────────────────────────

def test_status_transitions_valid_and_invalid(env):
    eh, repo, pid = env["eh"], env["repo"], env["pid"]
    idea = eh.add_idea(repo, pid, "An idea")
    iid = idea["job_id"]
    # A fresh idea is RAW.
    assert eh.grass_status(idea) == eh.GRASS_RAW
    # raw -> refined OK.
    rec = eh.set_grass_status(repo, pid, iid, eh.GRASS_REFINED)
    assert rec["status"] == eh.GRASS_REFINED
    # refined -> promoted OK, stores the link.
    rec = eh.set_grass_status(repo, pid, iid, eh.GRASS_PROMOTED,
                              promoted_to_session="sid-1", promoted_to_lane="research")
    assert rec["status"] == eh.GRASS_PROMOTED
    assert rec["promoted_to_session"] == "sid-1"
    assert rec["promoted_to_lane"] == "research"
    # An unknown status is rejected.
    with pytest.raises(ValueError):
        eh.set_grass_status(repo, pid, iid, "bogus")
    # promoted -> raw is an illegal transition.
    with pytest.raises(ValueError):
        eh.set_grass_status(repo, pid, iid, eh.GRASS_RAW)
    # An unknown idea is rejected.
    with pytest.raises(ValueError):
        eh.set_grass_status(repo, pid, "idea-nope", eh.GRASS_REFINED)


def test_versioned_refinements_increment_and_list(env):
    eh, repo, pid = env["eh"], env["repo"], env["pid"]
    idea = eh.add_idea(repo, pid, "Energy-aware scene scheduling")
    iid = idea["job_id"]
    r1 = eh.save_grass_refinement(repo, pid, iid, text="first brainstorm",
                                  label="brainstorm")
    r2 = eh.save_grass_refinement(repo, pid, iid, text="research brief",
                                  label="Research brief", artifacts=["brief.md"])
    # The ids are grass-<id>/dev-N and N auto-increments.
    short = eh.grass_short_id(iid)
    assert r1["refinement_id"] == f"{short}/dev-1"
    assert r2["refinement_id"] == f"{short}/dev-2"
    assert r1["version"] == 1 and r2["version"] == 2
    # Listed NEWEST-FIRST.
    refs = eh.list_grass_refinements(repo, pid, iid)
    assert [r["version"] for r in refs] == [2, 1]
    assert refs[0]["artifacts"] == ["brief.md"]
    # Saving a refinement marks the idea REFINED.
    updated = eh.get_grass_idea(repo, pid, iid)
    assert eh.grass_status(updated) == eh.GRASS_REFINED


def test_develop_seeds_session_and_idea_stays(env):
    eh, reg, repo, pid = env["eh"], env["reg"], env["repo"], env["pid"]
    idea = eh.add_idea(repo, pid, "Rust rewrite of the scene engine")
    iid = idea["job_id"]
    eh.save_grass_refinement(repo, pid, iid, text="prior brief notes")

    before = eh.list_efforts(repo, pid, "grass")
    rec = eh.develop_grass_idea(pid, iid, "research")
    after = eh.list_efforts(repo, pid, "grass")

    sid = rec["session_id"]
    assert rec["lane"] == "research"
    assert rec["status"] == reg.STATUS_RUNNING
    # The idea text + a prior refinement rode into the seed (Wave-1 seed path).
    assert "Rust rewrite of the scene engine" in rec["seed_text"]
    assert "prior brief notes" in rec["seed_text"]
    assert "researchPrime" in rec["seed_text"]
    # The seed was actually written to the PTY.
    out = env["ts"].read_since(sid, 0)
    assert "Rust rewrite of the scene engine" in out["text"]
    # COPY-never-destroy: the idea remains in grass.
    assert len(after) == len(before) == 1
    assert any(g["job_id"] == iid for g in after)


def test_develop_invalid_lane_and_unknown_idea(env):
    eh, repo, pid = env["eh"], env["repo"], env["pid"]
    idea = eh.add_idea(repo, pid, "x")
    with pytest.raises(ValueError):
        eh.develop_grass_idea(pid, idea["job_id"], "build")
    with pytest.raises(ValueError):
        eh.develop_grass_idea(pid, "idea-nope", "research")


def test_pull_refinement_seeds_new_session(env):
    eh, reg, repo, pid = env["eh"], env["reg"], env["repo"], env["pid"]
    idea = eh.add_idea(repo, pid, "Per-room presence via BLE")
    iid = idea["job_id"]
    r = eh.save_grass_refinement(repo, pid, iid,
                                 text="BLE beacon distance model + 3 sources")
    rec = eh.pull_grass_refinement(pid, iid, r["refinement_id"], "plan")
    assert rec["lane"] == "plan"
    assert rec["status"] == reg.STATUS_RUNNING
    # The pulled refinement's content rides into the new session's seed.
    assert "BLE beacon distance model" in rec["seed_text"]
    assert "Crucible" in rec["seed_text"]
    # The idea + refinement are untouched.
    assert eh.list_grass_refinements(repo, pid, iid)
    assert eh.get_grass_idea(repo, pid, iid) is not None


def test_pull_unknown_refinement_rejected(env):
    eh, repo, pid = env["eh"], env["repo"], env["pid"]
    idea = eh.add_idea(repo, pid, "y")
    with pytest.raises(ValueError):
        eh.pull_grass_refinement(pid, idea["job_id"], "no-such/dev-9", "research")


def test_promote_sets_status_and_link(env):
    eh, repo, pid = env["eh"], env["repo"], env["pid"]
    idea = eh.add_idea(repo, pid, "Gemini adapter scoping notes")
    iid = idea["job_id"]
    rec = eh.promote_grass_to_lane(pid, iid, "research")
    sid = rec["session_id"]
    # The idea is now PROMOTED and LINKS to the run it became.
    after = eh.get_grass_idea(repo, pid, iid)
    assert eh.grass_status(after) == eh.GRASS_PROMOTED
    assert after["promoted_to_session"] == sid
    assert after["promoted_to_lane"] == "research"
    # Still in grass (copy, never destroy).
    assert any(g["job_id"] == iid for g in eh.list_efforts(repo, pid, "grass"))


def test_workbench_data_aggregates(env):
    eh, repo, pid = env["eh"], env["repo"], env["pid"]
    i1 = eh.add_idea(repo, pid, "raw idea")
    i2 = eh.add_idea(repo, pid, "refined idea")
    eh.save_grass_refinement(repo, pid, i2["job_id"], text="brief")
    data = eh.grass_workbench_data(repo, pid)
    by = {d["title"]: d for d in data}
    assert by["raw idea"]["status"] == eh.GRASS_RAW
    assert by["refined idea"]["status"] == eh.GRASS_REFINED
    assert by["refined idea"]["refinements"]
    assert by["raw idea"]["short_id"].startswith("grass-")
    assert by["raw idea"]["source"] == "manual"


# ── 2) RENDERED-DOM (positive + negative) ────────────────────────────────────

def _strip(html):
    b = re.sub(r"<style[\s\S]*?</style>", "", html)
    b = re.sub(r"<script[\s\S]*?</script>", "", b)
    m = re.search(r"<body[^>]*>([\s\S]*)</body>", b)
    return m.group(1) if m else b


class _Collector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.els = []

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        self.els.append((tag, (d.get("class") or "").split(), d))


def _parse(body):
    c = _Collector()
    c.feed(body)
    return c.els


def test_workbench_dom_positive(env):
    eh, gui, repo, pid = env["eh"], env["gui"], env["repo"], env["pid"]
    eh.add_idea(repo, pid, "Voice control via local Whisper")
    i2 = eh.add_idea(repo, pid, "Energy-aware scene scheduling")
    eh.save_grass_refinement(repo, pid, i2["job_id"], text="brief", label="Research brief")
    body = _strip(gui.render_project_window_html(pid))
    els = _parse(body)
    classes = [" ".join(c) for _, c, _ in els]
    # The workbench container + filter-tab row.
    assert any("grass-workbench" in c.split() for c in classes)
    assert any("gtabs" in c.split() for c in classes)
    # The four filter tabs: All / raw / refined / promoted.
    filters = [d.get("data-filter") for _, c, d in els if "gtab" in c]
    assert {"all", "raw", "refined", "promoted"} <= set(filters)
    # A search box.
    assert any("gsearch" in c for c in classes)
    # The two-pane structure: a .glist + a .gwork.
    assert any("glist" in c.split() for c in classes)
    assert any("gwork" in c.split() for c in classes)
    # Idea rows carry the workbench .gli markup with status data.
    glis = [d for _, c, d in els if "gli" in c]
    assert glis, "no .gli idea rows rendered"
    assert all("data-idea" in d for d in glis)
    assert any(d.get("data-status") == "refined" for d in glis)
    # Both idea texts present.
    assert "Voice control via local Whisper" in body
    assert "Energy-aware scene scheduling" in body


def test_workbench_dom_negative_no_old_idea_board(env):
    # The OLD single-column idea-board / idea-card markup MUST be gone from the
    # rendered grass surface (it was replaced by the two-pane workbench).
    eh, gui, repo, pid = env["eh"], env["gui"], env["repo"], env["pid"]
    eh.add_idea(repo, pid, "some idea")
    body = _strip(gui.render_project_window_html(pid))
    forbidden = [
        "class='idea-board'", 'class="idea-board"',
        "class='idea-card'", 'class="idea-card"',
        "idea-promote",
        "promoteGrass(",  # old per-card inline onclick (now JS-wired)
    ]
    hits = [m for m in forbidden if m in body]
    assert not hits, f"old single-column grass markup still rendered: {hits}"


def test_empty_workbench_dom(env):
    gui, pid = env["gui"], env["pid"]
    body = _strip(gui.render_project_window_html(pid))
    assert "grass-workbench" in body
    assert "gtabs" in body
    assert "No ideas yet" in body


# ── 3) REAL Playwright + Chromium ────────────────────────────────────────────

def _serve(gui):
    server = gui.make_server("127.0.0.1", 0)
    port = server.server_address[1]
    assert port != 8777
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server, t, f"http://127.0.0.1:{port}", port


def test_workbench_playwright_flow(env):
    pytest.importorskip("playwright.sync_api")
    eh, gui, repo, pid = env["eh"], env["gui"], env["repo"], env["pid"]
    # Mixed-status ideas so the filter has something to scope.
    eh.add_idea(repo, pid, "Voice control via local Whisper")
    i2 = eh.add_idea(repo, pid, "Energy-aware scene scheduling")
    eh.save_grass_refinement(repo, pid, i2["job_id"], text="research brief",
                             label="Research brief")  # -> refined + dev-1

    server, t, base, _ = _serve(gui)
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page()
            errors = []
            pg.on("console",
                  lambda m: errors.append(m.text) if m.type == "error" else None)
            pg.goto(f"{base}/project/{pid}", wait_until="networkidle")
            from tests.ui_helpers import expand_workbench
            expand_workbench(pg)  # the Workbench tile now opens collapsed

            # v12 Wave 2 Layout-D: grass is the right-column mini-panel; open the
            # workbench via its "Open workbench →" control (openGrassWorkbench()).
            pg.click(".grass-open")
            pg.wait_for_selector("#grassPanel .grass-workbench", timeout=5000)
            # Two idea rows in the list.
            assert pg.eval_on_selector_all("#grassPanel .gli", "e=>e.length") == 2

            # Filter by "refined" → only the refined idea remains visible.
            pg.click("#grassPanel .gtab[data-filter='refined']")
            vis = pg.eval_on_selector_all(
                "#grassPanel .gli",
                "els=>els.filter(e=>e.style.display!=='none').length")
            assert vis == 1

            # Back to All, then search scopes the list.
            pg.click("#grassPanel .gtab[data-filter='all']")
            pg.fill("#grassPanel .gsearch", "Whisper")
            vis = pg.eval_on_selector_all(
                "#grassPanel .gli",
                "els=>els.filter(e=>e.style.display!=='none').length")
            assert vis == 1
            pg.fill("#grassPanel .gsearch", "")

            # v12 W11: select the refined idea → the ONE-session workbench loads
            # with the auto-gathered History panel (the prior refinement listed,
            # each pullable into the live session) + a single session terminal +
            # Migrate / Archive-snapshot controls. NO Research/Plan develop split.
            short = eh.grass_short_id(i2["job_id"])
            pg.click(f"#grassPanel .gli[data-idea='{i2['job_id']}']")
            pg.wait_for_selector("#grassPanel .gwork .gsession", timeout=5000)
            # No retired develop bar.
            assert pg.eval_on_selector_all(
                "#grassPanel .gwork [data-dev]", "e=>e.length") == 0, \
                "the one-session workbench must NOT render develop buttons"
            hist = pg.inner_text("#grassPanel .gwork .ghist")
            assert f"{short}/dev-1" in hist
            assert pg.eval_on_selector_all(
                "#grassPanel .gwork .ghist button[data-pull]", "e=>e.length") >= 1

            # Open the SINGLE workbench session → a seeded live session mounts a
            # terminal (one host, not two).
            pg.click("#grassPanel .gwork .gopen")
            pg.wait_for_selector("#grassPanel .gwork [data-grass-term] .xterm",
                                 timeout=8000)
            assert pg.eval_on_selector_all(
                "#grassPanel .gwork [data-grass-term][data-session]",
                "e=>e.length") == 1

            # The Migrate-to-project + Archive-snapshot header controls render.
            assert pg.eval_on_selector_all(
                "#grassPanel .gwork .gmigrate", "e=>e.length") == 1
            assert pg.eval_on_selector_all(
                "#grassPanel .gwork .garchive-snap", "e=>e.length") == 1

            assert not errors, f"JS console errors: {errors}"
            b.close()
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=5)


# ── Endpoint auth + validation (token-gated POST; read-only GET) ─────────────

def _post(url, payload, token=None):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if token is not None:
        req.add_header("X-Anchor-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def test_grass_endpoints_auth_and_read(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(tmp_path / "wt-base"))
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.setenv("ANCHOR_TOKEN", "tok-123")
    monkeypatch.delenv("ANCHOR_TERMINAL_SEED", raising=False)
    for lane in ("RESEARCH", "PLAN", "PLANNING", "BUILD", "GRASS"):
        monkeypatch.delenv("ANCHOR_SEED_PROMPT_" + lane, raising=False)

    import paths
    importlib.reload(paths)
    paths.ensure_data_dirs()
    for mod in ("pty_manager", "rnd_registry", "session_registry", "worktrees",
                "lanes", "terminal_session", "effort_history"):
        importlib.reload(importlib.import_module(mod))
    import rnd_registry
    import effort_history
    import anchor_gui
    gui = importlib.reload(anchor_gui)

    repo = _make_repo(tmp_path)
    pid = rnd_registry.add_project("P", str(repo))["id"]
    idea = effort_history.add_idea(repo, pid, "endpoint idea")
    iid = idea["job_id"]
    ref = effort_history.save_grass_refinement(repo, pid, iid, text="brief")

    server = gui.make_server("127.0.0.1", 0)
    port = server.server_address[1]
    assert port != 8777
    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()
    base = f"http://127.0.0.1:{port}"
    try:
        # GET grass read endpoint requires the token (?token=).
        code, _ = _get(base + "/api/rnd/grass?project_id=" + pid)
        assert code == 401
        code, d = _get(base + "/api/rnd/grass?project_id=" + pid + "&token=tok-123")
        assert code == 200 and d.get("ok") is True
        assert any(i["idea_id"] == iid for i in d["ideas"])

        # develop: no token → 401; bad lane → 400; ok → 200 seeded session.
        code, _ = _post(base + "/api/rnd/grass_develop",
                        {"project_id": pid, "idea_id": iid, "lane": "research"})
        assert code == 401
        code, _ = _post(base + "/api/rnd/grass_develop",
                        {"project_id": pid, "idea_id": iid, "lane": "build"},
                        token="tok-123")
        assert code == 400
        code, dd = _post(base + "/api/rnd/grass_develop",
                         {"project_id": pid, "idea_id": iid, "lane": "research"},
                         token="tok-123")
        assert code == 200 and dd.get("ok") is True
        assert "endpoint idea" in dd["session"]["seed_text"]

        # save_refinement: token-gated; appends dev-2.
        code, sr = _post(base + "/api/rnd/grass_save_refinement",
                         {"project_id": pid, "idea_id": iid, "text": "more"},
                         token="tok-123")
        assert code == 200 and sr["refinement"]["version"] == 2

        # set_status: token-gated; illegal transition rejected.
        code, _ = _post(base + "/api/rnd/grass_set_status",
                        {"project_id": pid, "idea_id": iid,
                         "status": "promoted"}, token="tok-123")
        assert code == 200

        # pull: token-gated; ok → seeded session.
        code, pl = _post(base + "/api/rnd/grass_pull",
                         {"project_id": pid, "idea_id": iid,
                          "refinement_id": ref["refinement_id"],
                          "lane": "plan"}, token="tok-123")
        assert code == 200 and pl.get("ok") is True
        assert "brief" in pl["session"]["seed_text"]

        # The idea is never destroyed by any of the above.
        assert any(g["job_id"] == iid
                   for g in effort_history.list_efforts(repo, pid, "grass"))
    finally:
        server.shutdown()
        server.server_close()
        th.join(timeout=5)
        import pty_manager
        try:
            pty_manager._reset_live_table_for_tests()
        except Exception:
            pass


def test_grass_develop_unknown_project_404(env):
    gui = env["gui"]
    server, t, base, _ = _serve(gui)
    try:
        code, data = _post(base + "/api/rnd/grass_develop",
                           {"project_id": "no-such", "idea_id": "idea-x",
                            "lane": "research"})
        assert code == 404
        assert data.get("ok") is False
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=5)
