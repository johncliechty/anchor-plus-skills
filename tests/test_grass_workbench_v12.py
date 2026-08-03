"""v12 Wave 11 — Grass two-pane ONE-session workbench (DOM pos/neg + back-compat
+ grass second-advance retirement).

The approved target is ``_mockups/grass_2_workbench.html``: a LEFT idea list
(capture + search + filter chips All/raw/refined/promoted + a ✕→Boneyard control
per idea) and a RIGHT workbench for the selected idea — a header (auto-saved
indicator + **Migrate to project ↑** + **Archive snapshot**), the idea text, an
auto-gathered **History** panel (prior dev work + linked deliverables), and ONE
session terminal + a Claude/Gemini engine toggle. There is NO Research/Plan split:
the single workbench session advances research→plan IN-SESSION.

Verification (the v4 lesson):
  * DOM POSITIVE — the server renders the two-pane workbench (filter tabs + search
    + left ``.glist`` of ``.gli`` rows + right ``.gwork``); the client-side
    ``selectGrassIdea`` template builds a ONE-session right pane (a single
    ``.gterm`` host, a Migrate control, an Archive control, an engine toggle, a
    History panel) and carries NO Research/Plan develop buttons / NO Advance-to-
    Plan control.
  * DOM NEGATIVE — the OLD two-terminal markup (two ``.gterm`` lanes, ``data-dev``,
    ``data-advance``, per-lane ``data-save-lane``/``data-archive-lane``) is GONE.
  * BACK-COMPAT — a pre-v12 idea carrying ``dev_sessions={research,plan}`` surfaces
    ONE workbench session (the most-advanced live one) with a stage history; no
    orphan (``grass_workbench_data`` ``workbench_session`` shape).
  * RETIREMENT — ``advance_grass_research_to_plan`` early-returns for an
    ``effort_managed`` idea (in-session ``advance_stage`` is used instead) AND
    stays live for a legacy (``effort_managed==False``) idea.
  * BONEYARD — the per-project Boneyard tab renders its list + an honest empty
    state (reuses the W10 ``boneyard.py`` backend + ``GET /api/rnd/boneyard``).
  * GENERAL — the "Open terminal" masthead button routes to the dock
    (``newGeneral`` → ``openEffortDock``), not a floating panel.

Hermetic: ``ANCHOR_PTY_BACKEND=stub`` + a temp git repo + tmp data dir + tmp
worktree base; never binds ``:8777``; never touches real data / network.
"""
import importlib
import re
import subprocess
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

    repo = _make_repo(tmp_path)
    proj = rnd_registry.add_project("Temp", str(repo), scaffold=False)
    yield {
        "gui": gui, "eh": effort_history, "rnd": rnd_registry,
        "reg": session_registry, "ts": terminal_session, "bone": boneyard,
        "repo": repo, "pid": proj["id"],
    }
    try:
        import pty_manager
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


# ── helpers ──────────────────────────────────────────────────────────────────

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


def _select_grass_idea_html(gui):
    """Reconstruct the static markup selectGrassIdea() emits, by joining the
    single-quoted string literals in its ``var html = '' + ...;`` template (the
    v10 test convention — structure, not a string grep)."""
    js = gui._PROJECT_WINDOW_JS
    m = re.search(r"function selectGrassIdea\(ideaId\)\s*\{([\s\S]*?)\n\}\n", js)
    assert m, "selectGrassIdea not found in _PROJECT_WINDOW_JS"
    body = m.group(1)
    hm = re.search(r"var html = ''([\s\S]*?);\n\s*work\.innerHTML = html;", body)
    assert hm, "selectGrassIdea html template not found"
    tmpl = hm.group(1)
    lits = re.findall(r"'((?:\\.|[^'\\])*)'", tmpl)
    return "".join(s.replace("\\'", "'") for s in lits)


# ════════════════════════════════════════════════════════════════════════════
# (1) DOM POSITIVE — two-pane, one-session right workbench
# ════════════════════════════════════════════════════════════════════════════

def test_workbench_two_pane_server_render_positive(env):
    eh, gui, repo, pid = env["eh"], env["gui"], env["repo"], env["pid"]
    eh.add_idea(repo, pid, "Passive decay-heat removal loop")
    i2 = eh.add_idea(repo, pid, "Digital-twin drift alarms")
    eh.save_grass_refinement(repo, pid, i2["job_id"], text="brief")
    body = _strip(gui.render_project_window_html(pid))
    els = _parse(body)
    classes = [" ".join(c) for _, c, _ in els]
    # Two-pane shell: filter tabs + search + a left .glist + a right .gwork.
    assert any("grass-workbench" in c.split() for c in classes)
    assert any("gtabs" in c.split() for c in classes)
    filters = [d.get("data-filter") for _, c, d in els if "gtab" in c]
    assert {"all", "raw", "refined", "promoted"} <= set(filters)
    assert any("gsearch" in c for c in classes)
    assert any("glist" in c.split() for c in classes)
    assert any("gwork" in c.split() for c in classes)
    # Left idea rows carry the .gli markup + the ✕ delete control (→ Boneyard).
    glis = [d for _, c, d in els if "gli" in c]
    assert glis, "no .gli idea rows rendered"
    assert all("data-idea" in d for d in glis)
    dels = [d for _, c, d in els if "gli-del" in c]
    assert len(dels) == 2, "each idea row must carry a ✕ delete control"
    for d in dels:
        assert "deleteGrassIdea(" in (d.get("onclick") or "")


def test_one_session_right_pane_positive(env):
    """The selectGrassIdea right pane is the ONE-session workbench: a single
    .gterm host, a Migrate control, an Archive control, an engine toggle, a
    History panel + an Open-session control."""
    html = _select_grass_idea_html(env["gui"])
    els = _parse(html)
    # Exactly ONE terminal host (not two lane hosts).
    hosts = [d for t, c, d in els if d.get("data-grass-term")]
    assert len(hosts) == 1, \
        f"the one-session workbench must render ONE terminal host, got {len(hosts)}"
    gterms = [d for t, c, d in els if "gterm" in c]
    assert len(gterms) == 1, f"expected one .gterm, got {len(gterms)}"
    # Migrate to project ↑ + Archive snapshot controls in the header.
    assert any("gmigrate" in c for t, c, d in els), "no Migrate control"
    assert any("garchive-snap" in c for t, c, d in els), "no Archive snapshot"
    # Engine toggle present.
    assert any("gengtog" in c for t, c, d in els), "no engine toggle"
    # Auto-saved indicator (no Save button).
    assert any("gautosave" in c for t, c, d in els), "no auto-saved indicator"
    # An auto-gathered History panel host.
    assert any("ghist-rows" in c for t, c, d in els), "no History panel"
    # An Open-session control (starts the single seeded workbench session).
    assert any("gopen" in c for t, c, d in els), "no Open-session control"


# ════════════════════════════════════════════════════════════════════════════
# (2) DOM NEGATIVE — the OLD two-terminal markup is GONE
# ════════════════════════════════════════════════════════════════════════════

def test_no_research_plan_split_negative(env):
    """The right pane carries NO Research/Plan develop buttons, NO Advance-to-Plan
    control, NO per-lane save/archive controls, and NO second lane terminal."""
    html = _select_grass_idea_html(env["gui"])
    els = _parse(html)
    # No data-dev develop buttons (the old 🔬 Research / 📐 Plan split).
    assert not [d for t, c, d in els if d.get("data-dev")], \
        "the one-session workbench must NOT render data-dev develop buttons"
    # No data-advance Advance-to-Plan control (in-session advance instead).
    assert not [d for t, c, d in els if d.get("data-advance")], \
        "the one-session workbench must NOT render an Advance-to-Plan control"
    # No per-lane save / archive controls.
    assert not [d for t, c, d in els if d.get("data-save-lane")], \
        "no per-lane Save control in the one-session workbench"
    assert not [d for t, c, d in els if d.get("data-archive-lane")], \
        "no per-lane Archive control in the one-session workbench"
    # No two distinct lane terminal hosts.
    lane_hosts = sorted(d.get("data-grass-term") for t, c, d in els
                        if d.get("data-grass-term"))
    assert lane_hosts != ["plan", "research"], \
        "the two-terminal (research+plan) split must be gone"


def test_empty_workbench_dom_negative(env):
    """A project with no ideas renders the two-pane shell + the honest empty state,
    no idea rows, no crash."""
    gui, pid = env["gui"], env["pid"]
    body = _strip(gui.render_project_window_html(pid))
    assert "grass-workbench" in body
    assert "gtabs" in body
    assert "No ideas yet" in body
    els = _parse(body)
    assert not [d for t, c, d in els if "gli" in c and d.get("data-idea")], \
        "an empty project must render no idea rows"


# ════════════════════════════════════════════════════════════════════════════
# (3) BACK-COMPAT — a pre-v12 two-dev_session idea surfaces ONE session
# ════════════════════════════════════════════════════════════════════════════

def test_back_compat_two_dev_sessions_one_workbench_session(env):
    """A pre-v12 idea carrying dev_sessions={research, plan} surfaces ONE workbench
    session — the MOST-ADVANCED live one (plan) — with no orphan. ✕/Migrate still
    work (the idea record is intact)."""
    eh, ts, reg, pid = env["eh"], env["ts"], env["reg"], env["pid"]
    repo = env["repo"]
    idea = eh.add_idea(repo, pid, "Legacy two-session idea")
    iid = idea["job_id"]
    # Simulate a pre-v12 idea: two contained dev sessions (research + plan), both
    # LIVE (the legacy develop path; effort_managed defaults False).
    r = eh.develop_grass_idea(pid, iid, "research")
    p = eh.develop_grass_idea(pid, iid, "plan")
    assert r["session_id"] != p["session_id"]

    data = eh.grass_workbench_data(repo, pid)
    rec = next(d for d in data if d["idea_id"] == iid)
    # The single-session shape resolves the MOST-ADVANCED live one (plan).
    ws = rec.get("workbench_session")
    assert ws is not None, "back-compat idea must surface ONE workbench session"
    assert ws["session_id"] == p["session_id"], \
        "the most-advanced (plan) live session must be surfaced as THE session"
    # SAFE projection — never worktree/branch.
    assert "worktree_path" not in ws and "branch" not in ws
    # The idea is intact (✕/Migrate paths still resolve it).
    assert eh.get_grass_idea(repo, pid, iid) is not None


def test_workbench_session_none_when_no_live_dev(env):
    """An idea with no live dev session surfaces workbench_session == None
    (honest; no orphan)."""
    eh, repo, pid = env["eh"], env["repo"], env["pid"]
    eh.add_idea(repo, pid, "Untouched idea")
    data = eh.grass_workbench_data(repo, pid)
    assert data[0]["workbench_session"] is None


# ════════════════════════════════════════════════════════════════════════════
# (4) RETIREMENT — grass second-advance gated for effort_managed; live for legacy
# ════════════════════════════════════════════════════════════════════════════

def test_grass_second_advance_retired_for_effort_managed(env):
    """A v12 effort_managed grass workbench idea: advance_grass_research_to_plan
    early-returns (no second grass session minted) — the in-session advance_stage
    is used instead. The session-id SET is unchanged."""
    eh, ts, reg, pid = env["eh"], env["ts"], env["reg"], env["pid"]
    repo = env["repo"]
    idea = eh.add_idea(repo, pid, "Effort-managed idea")
    iid = idea["job_id"]
    rec = eh.develop_grass_workbench(pid, iid)   # effort_managed=True, single
    assert rec.get("effort_managed") is True
    sset0 = {r["session_id"] for r in reg.list_sessions(project_id=pid)}

    out = eh.advance_grass_research_to_plan(pid, iid)
    assert out["ok"] is False, out
    assert out["reason"] == "effort-managed-use-advance-stage", out
    assert out["session"] is None
    # SET equality — no second grass session minted.
    sset1 = {r["session_id"] for r in reg.list_sessions(project_id=pid)}
    assert sset1 == sset0, f"a grass session was minted: {sset1 ^ sset0}"


def test_grass_second_advance_live_for_legacy(env):
    """A legacy idea (effort_managed==False — the v10/v11.1 walks) still mints a
    second grass plan session via advance_grass_research_to_plan (unchanged)."""
    eh, ts, reg, pid = env["eh"], env["ts"], env["reg"], env["pid"]
    repo = env["repo"]
    idea = eh.add_idea(repo, pid, "Legacy idea")
    iid = idea["job_id"]
    r = eh.develop_grass_idea(pid, iid, "research")   # legacy: effort_managed False
    assert not r.get("effort_managed")
    # Produce a research transcript so the advance has material.
    import pty_manager as pty
    pty.write(r["session_id"], "\nResearcher: which loop?\nAssistant: molten-salt.\n")
    out = eh.advance_grass_research_to_plan(pid, iid)
    assert out["ok"] is True, out
    assert out["session"] is not None
    assert out["session"]["session_id"] != r["session_id"], \
        "legacy advance must mint a SECOND grass plan session"


def test_in_session_advance_for_grass_workbench_effort(env):
    """The single workbench session ADVANCES research→plan IN-SESSION via
    advance_stage — same session id, current_stage flips, no new session."""
    eh, ts, reg, pid = env["eh"], env["ts"], env["reg"], env["pid"]
    repo = env["repo"]
    idea = eh.add_idea(repo, pid, "In-session advance idea")
    iid = idea["job_id"]
    rec = eh.develop_grass_workbench(pid, iid)
    sid = rec["session_id"]
    sset0 = {r["session_id"] for r in reg.list_sessions(project_id=pid)}
    out = ts.advance_stage(sid, "plan", mode="manual", project_id=pid)
    assert out.get("ok") is True, out
    after = reg.get_session(sid)
    assert after["current_stage"] == "plan", after
    sset1 = {r["session_id"] for r in reg.list_sessions(project_id=pid)}
    assert sset1 == sset0, "in-session advance must NOT mint a new session"


# ════════════════════════════════════════════════════════════════════════════
# (5) BONEYARD per-project tab — list + empty state
# ════════════════════════════════════════════════════════════════════════════

def test_boneyard_tab_list_positive(env):
    """With discarded material, the per-project Boneyard tab renders the open
    button + the panel template + a row per entry (the W10 backend reused)."""
    gui, bone, repo, pid = env["gui"], env["bone"], env["repo"], env["pid"]
    bone.record_entry(str(repo), pid, {
        "source": bone.SOURCE_GRASS_DELETED, "idea_id": "grass-x", "lane": "grass",
        "title": "discarded moltensalt idea", "idea_text": "a moltensalt buffer",
        "doc_rels": [], "when": 1000.0,
    })
    html = gui.render_project_window_html(pid)
    assert "openBoneyard()" in html
    assert "id='boneyardTpl'" in html or 'id="boneyardTpl"' in html
    els = _parse(html)
    entries = [d for t, c, d in els if "byentry" in c]
    assert entries, "the Boneyard tab must render a row per discarded entry"
    assert any(d.get("data-source") == "grass-deleted" for d in entries)


def test_boneyard_tab_empty_state_negative(env):
    """A project with NO discarded material shows the honest empty state."""
    gui, pid = env["gui"], env["pid"]
    html = gui.render_project_window_html(pid)
    assert "openBoneyard()" in html
    els = _parse(html)
    assert [d for t, c, d in els if "byempty" in c], \
        "an empty Boneyard must render the honest empty-state row"
    assert not [d for t, c, d in els if "byentry" in c], \
        "an empty Boneyard must render no fabricated entries"


# ════════════════════════════════════════════════════════════════════════════
# (6) GENERAL routes to the dock (not a floating panel)
# ════════════════════════════════════════════════════════════════════════════

def test_open_terminal_routes_general_to_dock(env):
    """The masthead "Open terminal" button calls newGeneral (→ openEffortDock),
    NOT the floating-panel newTermSession; newGeneral starts a bare general session
    and opens the bottom dock."""
    gui = env["gui"]
    html = gui.render_project_window_html(env["pid"])
    # The button is wired to newGeneral, not newTermSession('general').
    assert "newGeneral(" in html, "Open terminal must call newGeneral"
    assert "newTermSession('general'" not in html, \
        "Open terminal must NOT open a floating panel (newTermSession)"
    js = gui._PROJECT_WINDOW_JS
    assert "async function newGeneral(" in js
    m = re.search(r"async function newGeneral\(([\s\S]*?)\n\}", js)
    assert m, "newGeneral body not found"
    nbody = m.group(1)
    # It starts a general session and opens the dock.
    assert "lane: 'general'" in nbody
    assert "openEffortDock(" in nbody, "newGeneral must open the dock"


def test_dock_suppresses_track_and_advance_for_general(env):
    """openEffortDock hides the stage track + Advance for a general session (it is
    NOT a trio effort) — assert the JS guards on lane === 'general'."""
    gui = env["gui"]
    js = gui._PROJECT_WINDOW_JS
    m = re.search(r"function openEffortDock\(sessionId, tile\)\s*\{([\s\S]*?)\n\}\n",
                  js)
    assert m, "openEffortDock not found"
    obody = m.group(1)
    assert "isGeneral" in obody, "openEffortDock must branch on a general session"
    assert "lane === 'general'" in obody
