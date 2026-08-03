"""v4 Wave 6 — Grass Catcher idea board + promote-to-lane.

Proves IMPLEMENTATION-PLAN.md "## Wave 6":
  (a) The grass lane renders as an IDEA BOARD — idea cards (text + source chip),
      each with → Research / → Plan promote actions (string-level over the render).
  (b) ``effort_history.promote_grass_to_lane(pid, idea_id, 'research')`` with the
      stub PTY backend starts a NEW Research session SEEDED with the idea text
      (the idea text appears in the session's seed/opening turn), the session is
      registered RUNNING with lane=research, and the idea REMAINS in grass
      (promotion copies, never moves).
  (c) The POST /api/rnd/promote_grass endpoint is token-gated and rejects an
      invalid lane with 400.

Hermetic: ANCHOR_PTY_BACKEND=stub (no real ConPTY), ANCHOR_RUNNER_CMD →
tests/fake_claude.py (no live claude), a temp ANCHOR_DATA_DIR + temp
ANCHOR_WORKTREE_BASE + a throwaway temp git repo. NEVER touches the live :8777
service or real data, and no worktree is ever created off the real C:\\dev\\Anchor
repo.
"""
import importlib
import json
import subprocess
import threading
import urllib.error
import urllib.request
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
    """Tmp data dir + tmp worktree base + stub PTY backend + a temp git repo."""
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


# ── (a) The grass lane renders an idea board with promote actions ────────────

def test_grass_renders_workbench_with_ideas(env):
    # v5 Wave 5: the grass surface is now the B+C hybrid two-pane WORKBENCH (the
    # old single-column idea-board/idea-card markup is gone — see the negative
    # assertions in test_grass_workbench.py). Both ideas appear as .gli rows; the
    # workbench carries the filter tabs + two-pane structure + add affordance.
    eh, gui, repo, pid = env["eh"], env["gui"], env["repo"], env["pid"]
    eh.add_idea(repo, pid, "Voice control via local Whisper", notes="someday")
    eh.add_idea(repo, pid, "Energy-aware scene scheduling")

    html = gui.render_project_window_html(pid)
    assert "grass-workbench" in html
    assert "gtabs" in html
    assert "gwrap" in html
    assert "Voice control via local Whisper" in html
    assert "Energy-aware scene scheduling" in html
    # The two idea rows carry the workbench .gli markup + status chips.
    assert "class='gli" in html or 'class="gli' in html
    assert "stchip raw" in html
    # The promote action survives — now inside the workbench (per-idea Promote
    # button is JS-wired) AND the column tile opens the workbench.
    assert "openGrassWorkbench" in html
    # "+ Add idea" affordance is still present.
    assert "Add idea" in html


def test_grass_source_chip_reflects_provenance(env):
    eh, gui, repo, pid = env["eh"], env["gui"], env["repo"], env["pid"]
    inbox_items = [{"text": "Promote me", "date": "2026-06-11", "domain": "x"}]
    eh.promote_inbox(repo, pid, "Promote me", inbox_items=inbox_items)
    html = gui.render_project_window_html(pid)
    assert "Promote me" in html
    # source chip "inbox" rendered in the workbench .gli row
    assert "srcchip" in html
    assert "inbox" in html


def test_empty_grass_board_renders_placeholder(env):
    gui, pid = env["gui"], env["pid"]
    html = gui.render_project_window_html(pid)
    # v12 Wave 2 Layout-D: grass is the persistent right-column mini-panel
    # ("Grass Catcher") + the retained hidden #grassWorkbenchTpl (opened via
    # openGrassWorkbench). No empty project → both show honest empty states.
    assert "Grass Catcher" in html
    assert "openGrassWorkbench()" in html
    # The Grass mini-panel's honest empty state + the workbench's "No ideas yet".
    assert "No ideas captured yet" in html
    assert "No ideas yet" in html


# ── (b) promote_grass_to_lane → seeded RUNNING session; idea stays in grass ──

def test_promote_grass_starts_seeded_research_session(env):
    eh, reg, repo, pid = env["eh"], env["reg"], env["repo"], env["pid"]
    idea = eh.add_idea(repo, pid, "Try a Rust rewrite of the scene engine")
    idea_id = idea["job_id"]

    rec = eh.promote_grass_to_lane(pid, idea_id, "research")

    # A NEW session in the research lane, registered RUNNING.
    sid = rec["session_id"]
    assert rec["lane"] == "research"
    assert rec["status"] == reg.STATUS_RUNNING
    assert reg.get_session(sid)["status"] == reg.STATUS_RUNNING

    # The idea text rode into the session's seed/opening turn (Wave-1 seed path),
    # alongside the lane skill (researchPrime).
    assert "Try a Rust rewrite of the scene engine" in rec["seed_text"]
    assert "researchPrime" in rec["seed_text"]
    assert rec["seeded"] is True
    # And the seed was actually written to the PTY exactly once.
    out = env["ts"].read_since(sid, 0)
    assert "Try a Rust rewrite of the scene engine" in out["text"]


def test_promote_grass_copies_not_moves(env):
    eh, repo, pid = env["eh"], env["repo"], env["pid"]
    idea = eh.add_idea(repo, pid, "Matter bridge fallback")
    idea_id = idea["job_id"]

    before = eh.list_efforts(repo, pid, "grass")
    eh.promote_grass_to_lane(pid, idea_id, "plan")
    after = eh.list_efforts(repo, pid, "grass")

    # The idea REMAINS in grass — promotion copies, never destroys.
    assert len(after) == len(before) == 1
    assert any(g["job_id"] == idea_id for g in after)
    assert after[0]["title"] == "Matter bridge fallback"


def test_promote_grass_plan_seeds_crucible(env):
    eh, repo, pid = env["eh"], env["repo"], env["pid"]
    idea = eh.add_idea(repo, pid, "Local LLM router")
    rec = eh.promote_grass_to_lane(pid, idea["job_id"], "plan")
    assert rec["lane"] == "plan"
    assert "Crucible" in rec["seed_text"]
    assert "Local LLM router" in rec["seed_text"]


def test_promote_grass_invalid_lane_raises(env):
    eh, repo, pid = env["eh"], env["repo"], env["pid"]
    idea = eh.add_idea(repo, pid, "x")
    with pytest.raises(ValueError):
        eh.promote_grass_to_lane(pid, idea["job_id"], "build")
    with pytest.raises(ValueError):
        eh.promote_grass_to_lane(pid, idea["job_id"], "deliverables")


def test_promote_grass_unknown_idea_raises(env):
    eh, pid = env["eh"], env["pid"]
    with pytest.raises(ValueError):
        eh.promote_grass_to_lane(pid, "idea-nope", "research")


# ── (c) Endpoint: token-gated + rejects an invalid lane ─────────────────────

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


def _serve(gui):
    server = gui.make_server("127.0.0.1", 0)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server, t, f"http://127.0.0.1:{port}"


def test_promote_grass_endpoint_auth_gated_and_validates(tmp_path, monkeypatch):
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
    gui = importlib.reload(anchor_gui)

    repo = _make_repo(tmp_path)
    pid = rnd_registry.add_project("P", str(repo))["id"]
    idea = effort_history.add_idea(repo, pid, "endpoint idea")
    idea_id = idea["job_id"]

    server, t, base = _serve(gui)
    try:
        # No token → 401 BEFORE any promote logic runs.
        code, _ = _post(base + "/api/rnd/promote_grass",
                        {"project_id": pid, "idea_id": idea_id,
                         "lane": "research"})
        assert code == 401

        # Correct token + an INVALID lane → 400 (validation).
        code, d = _post(base + "/api/rnd/promote_grass",
                        {"project_id": pid, "idea_id": idea_id, "lane": "build"},
                        token="tok-123")
        assert code == 400
        assert d.get("ok") is False

        # Correct token + a valid lane → 200 + the seeded session record.
        code, d = _post(base + "/api/rnd/promote_grass",
                        {"project_id": pid, "idea_id": idea_id,
                         "lane": "research"},
                        token="tok-123")
        assert code == 200 and d.get("ok") is True
        sess = d["session"]
        assert sess["lane"] == "research"
        assert "endpoint idea" in sess["seed_text"]
        # The idea is still in grass (copy, not move).
        grass = effort_history.list_efforts(repo, pid, "grass")
        assert any(g["job_id"] == idea_id for g in grass)
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=5)
        try:
            pty_manager._reset_live_table_for_tests()
        except Exception:
            pass


def test_promote_grass_unknown_project_clean_404(env):
    gui = env["gui"]
    server, t, base = _serve(gui)
    try:
        code, data = _post(base + "/api/rnd/promote_grass",
                           {"project_id": "no-such", "idea_id": "idea-x",
                            "lane": "research"})
        assert code == 404
        assert data.get("ok") is False
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=5)
