"""v9 Wave 2 — Grass idea delete (backend + endpoint + UI).

Proves IMPLEMENTATION-PLAN.md "## Wave 2 — Grass idea delete":

  - ``effort_history.delete_grass_idea(folder, pid, idea_id)`` removes the idea
    POINTER-RECORD + its grass index.json entry + its REFINEMENTS dir
    (``refinements/<id>/dev-N``) + cleans its ``dev_sessions`` map (best-effort
    kill/forget the contained develop sessions). ``grass_workbench_data`` no
    longer lists the idea afterward. SIBLING ideas + OTHER projects are
    untouched. Idempotent (second delete is a no-op); an unknown id never raises.
  - ``POST /api/rnd/grass_delete`` is token-gated AND requires an explicit
    ``confirm:true`` (an irreversible removal). Deletes on confirm.
  - Rendered-DOM (positive + negative): the red ✕ delete control is present on
    the idea row, wired to ``deleteGrassIdea`` → POST ``grass_delete``
    ``{confirm:true}``, and is confirm()-gated; it does NOT reuse the row-select
    handler (event.stopPropagation).
  - Real Playwright/Chromium: open the grass workbench with two ideas → click an
    idea's red ✕ → confirm → the idea is removed from the list (and stays gone),
    the sibling remains; no JS console errors. Screenshot →
    ``_devtest/wave2_grass_delete.png``.

Hermetic: ``ANCHOR_PTY_BACKEND=stub``, ``ANCHOR_RUNNER_CMD`` -> fake_claude.py,
a temp data dir + worktree base + a throwaway temp git repo. NEVER binds
``:8777``; NEVER a worktree off the real Anchor repo; NEVER real push/gh/network.
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


def _make_repo(tmp_path, name="repo"):
    repo = tmp_path / name
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
        "tmp_path": tmp_path, "monkeypatch": monkeypatch,
    }
    try:
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


def _ids(folder, pid, eh):
    return {i["idea_id"] for i in eh.grass_workbench_data(folder, pid)}


# ════════════════════════════════════════════════════════════════════════════
# (1) BACKEND — delete clears pointer + index + refinements + dev_sessions
# ════════════════════════════════════════════════════════════════════════════

def test_delete_clears_pointer_index_refinements_and_devmap(env):
    eh, repo, pid = env["eh"], env["repo"], env["pid"]
    idea = eh.add_idea(repo, pid, "Whisper voice control")
    iid = idea["job_id"]
    # Save two refinement versions so the refinements dir + dev-N exist.
    eh.save_grass_refinement(repo, pid, iid, text="v1 notes", label="r1")
    eh.save_grass_refinement(repo, pid, iid, text="v2 notes", label="r2")
    assert len(eh.list_grass_refinements(repo, pid, iid)) == 2
    rdir = eh._refinements_dir(repo, pid, iid)
    assert rdir.is_dir()

    # Pre-conditions: pointer-record + index entry exist; the idea is listed.
    assert eh._pointer_path(repo, pid, "grass", iid).exists()
    assert iid in eh._load_index(repo, pid, "grass")
    assert iid in _ids(repo, pid, eh)

    out = eh.delete_grass_idea(repo, pid, iid)
    assert out["ok"] is True
    assert out["deleted"] is True
    assert out["refinements_removed"] is True

    # Pointer-record gone, index entry gone, refinements dir gone.
    assert not eh._pointer_path(repo, pid, "grass", iid).exists()
    assert iid not in eh._load_index(repo, pid, "grass")
    assert not rdir.exists()
    assert eh.list_grass_refinements(repo, pid, iid) == []
    # The workbench no longer lists it.
    assert iid not in _ids(repo, pid, eh)
    assert eh.get_grass_idea(repo, pid, iid) is None


def test_delete_cleans_dev_sessions_map(env):
    """A develop session is contained in the idea's dev_sessions map; deleting the
    idea best-effort forgets it (the registry record is dropped)."""
    eh, ts, reg, repo, pid = (env["eh"], env["ts"], env["reg"],
                              env["repo"], env["pid"])
    idea = eh.add_idea(repo, pid, "Idea with a develop session")
    iid = idea["job_id"]
    rec = eh.develop_grass_idea(pid, iid, "research")
    sid = rec["session_id"]
    assert reg.get_session(sid) is not None
    # The dev_sessions map now references the contained session.
    idea2 = eh.get_grass_idea(repo, pid, iid)
    assert (eh._grass_dev_sessions(idea2) or {}).get("research") == sid

    out = eh.delete_grass_idea(repo, pid, iid)
    assert out["ok"] is True
    assert sid in out["dev_sessions_cleared"]
    # The contained develop session's registry record is gone.
    assert reg.get_session(sid) is None
    assert iid not in _ids(repo, pid, eh)


def test_delete_leaves_siblings_and_other_projects_untouched(env):
    eh, rnd, repo, pid, tmp_path = (env["eh"], env["rnd"], env["repo"],
                                    env["pid"], env["tmp_path"])
    a = eh.add_idea(repo, pid, "Idea A")["job_id"]
    b = eh.add_idea(repo, pid, "Idea B")["job_id"]
    eh.save_grass_refinement(repo, pid, b, text="keep me", label="b1")

    # A SECOND project with its own grass idea (must be untouched).
    repo2 = _make_repo(tmp_path, name="repo2")
    proj2 = rnd.add_project("Temp2", str(repo2))
    pid2 = proj2["id"]
    c = eh.add_idea(repo2, pid2, "Other project idea")["job_id"]

    eh.delete_grass_idea(repo, pid, a)

    # Sibling B survives, with its refinement intact.
    ids = _ids(repo, pid, eh)
    assert a not in ids
    assert b in ids
    assert len(eh.list_grass_refinements(repo, pid, b)) == 1
    # Other project's idea is untouched.
    assert c in _ids(repo2, pid2, eh)


def test_delete_is_idempotent_and_unknown_no_raise(env):
    eh, repo, pid = env["eh"], env["repo"], env["pid"]
    iid = eh.add_idea(repo, pid, "Once")["job_id"]
    first = eh.delete_grass_idea(repo, pid, iid)
    assert first["deleted"] is True
    # Second delete: clean no-op (already gone), never raises.
    second = eh.delete_grass_idea(repo, pid, iid)
    assert second["ok"] is True
    assert second["deleted"] is False
    # Unknown id: no-op, no raise.
    out = eh.delete_grass_idea(repo, pid, "idea-does-not-exist")
    assert out["ok"] is True
    assert out["deleted"] is False


# ════════════════════════════════════════════════════════════════════════════
# (2) ENDPOINT — grass_delete token-gated + confirm-required + deletes on confirm
# ════════════════════════════════════════════════════════════════════════════

def _free_server(gui):
    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, port, t


def _post(port, path, payload, token=None):
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["X-Anchor-Token"] = token
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode(),
        headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def test_grass_delete_requires_token(env, monkeypatch):
    monkeypatch.setenv("ANCHOR_TOKEN", "s3cret")
    importlib.reload(importlib.import_module("paths"))
    gui = importlib.reload(env["gui"])
    eh, repo, pid = env["eh"], env["repo"], env["pid"]
    iid = eh.add_idea(repo, pid, "Auth me")["job_id"]

    srv, port, t = _free_server(gui)
    try:
        code, data = _post(port, "/api/rnd/grass_delete",
                           {"project_id": pid, "idea_id": iid, "confirm": True})
        assert code == 401
        assert data.get("error") == "unauthorized"
        # Untouched: the unauthed call did nothing.
        assert iid in _ids(repo, pid, eh)
        # With the token it succeeds.
        code, data = _post(port, "/api/rnd/grass_delete",
                           {"project_id": pid, "idea_id": iid, "confirm": True},
                           token="s3cret")
        assert code == 200 and data["ok"] is True and data["deleted"] is True
        assert iid not in _ids(repo, pid, eh)
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


def test_grass_delete_requires_confirm(env):
    gui, eh, repo, pid = env["gui"], env["eh"], env["repo"], env["pid"]
    iid = eh.add_idea(repo, pid, "Confirm me")["job_id"]
    srv, port, t = _free_server(gui)
    try:
        # No confirm → 400, untouched.
        code, data = _post(port, "/api/rnd/grass_delete",
                           {"project_id": pid, "idea_id": iid})
        assert code == 400
        assert data.get("reason") == "confirm-required"
        assert iid in _ids(repo, pid, eh)
        # confirm:false also refused.
        code, data = _post(port, "/api/rnd/grass_delete",
                           {"project_id": pid, "idea_id": iid, "confirm": False})
        assert code == 400
        assert iid in _ids(repo, pid, eh)
        # confirm:true deletes.
        code, data = _post(port, "/api/rnd/grass_delete",
                           {"project_id": pid, "idea_id": iid, "confirm": True})
        assert code == 200 and data["deleted"] is True
        assert iid not in _ids(repo, pid, eh)
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


# ════════════════════════════════════════════════════════════════════════════
# (3) DOM — the red ✕ delete control is present on the idea row + wired/gated
# ════════════════════════════════════════════════════════════════════════════

def _js(html):
    return "\n".join(re.findall(r"<script[^>]*>([\s\S]*?)</script>", html))


class _Collector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.dels = []  # the gli-del controls (tag, attrs)

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        classes = (d.get("class") or "").split()
        if "gli-del" in classes:
            self.dels.append(d)


def test_dom_delete_control_present_on_idea_row(env):
    """POSITIVE: each rendered grass idea row carries a '.gli-del' red ✕ control
    whose onclick stops propagation + calls deleteGrassIdea(idea). NEGATIVE: the
    select handler is NOT what the ✕ triggers (it stopPropagation's)."""
    eh, gui, repo, pid = env["eh"], env["gui"], env["repo"], env["pid"]
    idea = eh.add_idea(repo, pid, "Has a delete control")
    iid = idea["job_id"]

    li = gui._render_grass_idea_li(eh.grass_workbench_data(repo, pid)[0])
    c = _Collector()
    c.feed(li)
    # POSITIVE — exactly one .gli-del control, wired to deleteGrassIdea(this idea).
    assert len(c.dels) == 1, "no .gli-del delete control on the idea row"
    onclick = c.dels[0].get("onclick", "")
    assert "deleteGrassIdea(" in onclick, "✕ not wired to deleteGrassIdea"
    assert iid in onclick, "✕ not wired to THIS idea's id"
    # NEGATIVE — clicking ✕ must NOT also select the idea (stopPropagation guard).
    assert "stopPropagation" in onclick, "✕ does not stop event propagation"
    # The glyph is the ✕ (cross), not a kill 🗑.
    assert ("&#10005;" in li) or ("✕" in li)
    assert "🗑" not in li


def test_dom_delete_js_present_confirm_gated_and_posts_grass_delete(env):
    """POSITIVE: deleteGrassIdea exists, is confirm()-gated, and POSTs grass_delete
    with confirm:true. NEGATIVE: it does NOT post term_delete / grass_export."""
    gui = env["gui"]
    js = _js(gui.render_project_window_html(env["pid"]))
    assert "function deleteGrassIdea(" in js, "deleteGrassIdea() not defined"
    m = re.search(r"async function deleteGrassIdea\([\s\S]*?\n\}", js)
    assert m, "deleteGrassIdea body not found"
    body = m.group(0)
    # confirm()-gated with an early return on cancel.
    assert "confirm(" in body, "deleteGrassIdea is not confirm-gated"
    assert "return" in body.split("confirm(")[1].split("\n")[0] \
        or "if (!confirm(" in body, "no early return on cancel"
    # POSTs grass_delete with confirm:true.
    assert "/api/rnd/grass_delete" in body
    assert ("confirm: true" in body) or ("confirm:true" in body)
    # NEGATIVE — it is NOT the session delete / export endpoint.
    assert "/api/rnd/term_delete" not in body
    assert "/api/rnd/grass_export" not in body


def test_dom_delete_control_absent_when_no_ideas(env):
    """NEGATIVE: with no ideas, the empty workbench renders NO .gli-del control."""
    gui, repo, pid = env["gui"], env["repo"], env["pid"]
    wb = gui._render_grass_workbench(repo, pid)
    c = _Collector()
    c.feed(wb)
    assert c.dels == [], "a delete control rendered with zero ideas"


# ════════════════════════════════════════════════════════════════════════════
# (4) REAL Playwright + Chromium — click ✕ → idea gone; sibling stays
# ════════════════════════════════════════════════════════════════════════════

def test_playwright_delete_idea_removed_sibling_stays(env):
    pytest.importorskip("playwright.sync_api")
    eh, gui, repo, pid = env["eh"], env["gui"], env["repo"], env["pid"]
    victim = eh.add_idea(repo, pid, "DELETE ME idea")["job_id"]
    sibling = eh.add_idea(repo, pid, "KEEP ME idea")["job_id"]

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
            pg.goto(f"{base}/project/{pid}", wait_until="networkidle")
            from tests.ui_helpers import expand_workbench
            expand_workbench(pg)  # the Workbench tile now opens collapsed

            # Open the grass workbench.
            pg.click(".grass-tile")
            pg.wait_for_selector("#grassPanel .grass-workbench", timeout=5000)
            victim_sel = "#grassPanel .gli[data-idea='%s']" % victim
            sibling_sel = "#grassPanel .gli[data-idea='%s']" % sibling
            pg.wait_for_selector(victim_sel, timeout=5000)
            pg.wait_for_selector(sibling_sel, timeout=5000)
            assert pg.eval_on_selector_all(victim_sel, "e=>e.length") == 1
            # The red ✕ is on the row.
            del_sel = victim_sel + " .gli-del"
            pg.wait_for_selector(del_sel, timeout=5000)
            assert pg.eval_on_selector(del_sel, "e=>e.textContent").strip() == "✕"

            _DEVTEST.mkdir(exist_ok=True)
            pg.screenshot(path=str(_DEVTEST / "wave2_grass_delete.png"),
                          full_page=True)

            # Accept the confirm() dialog, click the ✕.
            pg.on("dialog", lambda d: d.accept())
            pg.click(del_sel)
            # The victim row disappears.
            pg.wait_for_function(
                "document.querySelectorAll(\"#grassPanel .gli[data-idea='%s']\")"
                ".length === 0" % victim, timeout=8000)
            # The sibling stays.
            assert pg.eval_on_selector_all(sibling_sel, "e=>e.length") == 1

            assert not errors, f"JS console errors during delete: {errors}"
            b.close()
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=5)

    # And it STAYS gone in the backing store (grass_workbench_data).
    ids = _ids(repo, pid, eh)
    assert victim not in ids
    assert sibling in ids
