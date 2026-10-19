"""v10 Wave 4 — Grass archive + grass→project lineage back-reference.

Proves IMPLEMENTATION-PLAN.md "## Wave 4 — Grass archive + grass→project lineage
back-reference" + MASTER-PLAN.md Pillar 2 items 3-4 (D7 archive verb, D8
grass_origin):

  (a) ``effort_history.archive_grass_session(pid, idea_id, lane)`` — persists the
      idea's (idea, lane) develop session's PRODUCED docs into the MAIN project
      (the v8 keystone, committed → survives kill) and records a per-idea ARCHIVE
      BUNDLE (``archives: [{lane, session_id, docs, summary_ref, when}]``) on the
      idea record. The idea STAYS in grass. HONEST-empty when nothing produced.
      Distinct from ``save_grass_refinement`` (a text snapshot).
  (b) ``export_grass_to_project`` stamps ``grass_origin == idea_id`` on the
      exported lane efforts AND on the dev session's registry record, so a NEW
      session started with that session as ``parent_session_id`` INHERITS the
      ``grass_origin`` (the whole chain traces back). The SAFE chain projection
      carries ``grass_origin`` but NEVER ``worktree_path`` / ``branch``.
  (c) NEGATIVE — a non-grass session has ``grass_origin == ""``.

Hermetic: ``ANCHOR_PTY_BACKEND=stub``, ``ANCHOR_RUNNER_CMD`` -> fake_claude.py, a
temp data dir + worktree base + a throwaway temp git repo. NEVER binds ``:8777``;
NEVER a worktree off the real Anchor repo; NEVER real push/gh/network.
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
    import summarizer
    importlib.reload(summarizer)
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


def _write_research_doc(worktree_path, rel="research/run-x/report.md",
                        body="# Report\nA grounded finding.\n"):
    """Stand in for what a research dev session writes: a report in its worktree."""
    wt = Path(worktree_path)
    p = wt / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return rel


# ════════════════════════════════════════════════════════════════════════════
# (a) ARCHIVE — persist dev docs + summary ref into a per-idea bundle
# ════════════════════════════════════════════════════════════════════════════

def test_archive_grass_research_session_records_bundle_with_doc(env):
    eh, ts, reg, repo, pid = (env["eh"], env["ts"], env["reg"],
                              env["repo"], env["pid"])
    idea = eh.add_idea(repo, pid, "Passive autonomous cooling loop")
    iid = idea["job_id"]
    # Develop a research session (contained) and write a produced doc in its worktree.
    dev = eh.develop_grass_idea(pid, iid, "research")
    sid = dev["session_id"]
    wt = reg.get_session(sid)["worktree_path"]
    rel = _write_research_doc(wt)

    out = eh.archive_grass_session(pid, iid, "research", folder_path=repo)
    assert out["ok"] is True, out
    bundle = out["archive"]
    assert bundle is not None
    assert bundle["lane"] == "research"
    assert bundle["session_id"] == sid
    # The doc is referenced in the bundle AND persisted on disk in the main project.
    assert rel in bundle["docs"]
    assert (repo / rel).is_file()
    # Summary reference shape (links /summary/<pid>/<lane>/<sid>); read-only — a
    # cache need not exist yet (no model run blocked on).
    assert bundle["summary_ref"]["session_id"] == sid
    assert bundle["summary_ref"]["lane"] == "research"
    assert "when" in bundle

    # The bundle rides the idea record + the workbench projection (newest-first).
    arch = eh.list_grass_archives(repo, pid, iid)
    assert len(arch) == 1 and arch[0]["session_id"] == sid
    wb = {i["idea_id"]: i for i in eh.grass_workbench_data(repo, pid)}
    assert wb[iid]["archives"] and wb[iid]["archives"][0]["session_id"] == sid

    # The idea STAYS in grass (copy, never destroy).
    assert eh.get_grass_idea(repo, pid, iid) is not None
    assert iid in {i["idea_id"] for i in eh.grass_workbench_data(repo, pid)}

    ts.kill(sid)


def test_archive_is_committed_so_it_survives_kill(env):
    """The persisted doc is committed to the MAIN repo, so a later session kill
    (which reaps the worktree) does NOT lose it."""
    eh, ts, reg, repo, pid = (env["eh"], env["ts"], env["reg"],
                              env["repo"], env["pid"])
    idea = eh.add_idea(repo, pid, "Idea to archive then kill")
    iid = idea["job_id"]
    dev = eh.develop_grass_idea(pid, iid, "research")
    sid = dev["session_id"]
    rel = _write_research_doc(reg.get_session(sid)["worktree_path"])

    head_before = _git(repo, "rev-parse", "HEAD").stdout.strip()
    out = eh.archive_grass_session(pid, iid, "research", folder_path=repo)
    assert out["ok"] is True
    head_after = _git(repo, "rev-parse", "HEAD").stdout.strip()
    assert head_after != head_before  # the persisted doc was committed

    # Kill reaps the worktree; the archived doc remains in the main project.
    ts.kill(sid)
    assert (repo / rel).is_file()
    arch = eh.list_grass_archives(repo, pid, iid)
    assert arch and rel in arch[0]["docs"]


def test_archive_honest_empty_when_nothing_produced(env):
    """No produced docs (a freshly-started dev session) → honest unresolved, no
    fabricated bundle, no archive recorded."""
    eh, ts, repo, pid = env["eh"], env["ts"], env["repo"], env["pid"]
    idea = eh.add_idea(repo, pid, "Idea with no output yet")
    iid = idea["job_id"]
    dev = eh.develop_grass_idea(pid, iid, "research")
    sid = dev["session_id"]
    # No doc written into the worktree.
    out = eh.archive_grass_session(pid, iid, "research", folder_path=repo)
    assert out["ok"] is False
    assert out["archive"] is None
    assert out["reason"] == "no-docs"
    assert eh.list_grass_archives(repo, pid, iid) == []
    ts.kill(sid)


def test_archive_honest_when_no_dev_session(env):
    """No (idea, lane) dev session at all → honest no-dev-session."""
    eh, repo, pid = env["eh"], env["repo"], env["pid"]
    idea = eh.add_idea(repo, pid, "Never developed")
    iid = idea["job_id"]
    out = eh.archive_grass_session(pid, iid, "plan", folder_path=repo)
    assert out["ok"] is False
    assert out["archive"] is None
    assert out["reason"] == "no-dev-session"


def test_archive_distinct_from_save_refinement(env):
    """Archive (docs + summary bundle) is a DIFFERENT store than save_refinement
    (a versioned text snapshot) — they do not collide."""
    eh, ts, reg, repo, pid = (env["eh"], env["ts"], env["reg"],
                              env["repo"], env["pid"])
    idea = eh.add_idea(repo, pid, "Distinct stores idea")
    iid = idea["job_id"]
    dev = eh.develop_grass_idea(pid, iid, "research")
    sid = dev["session_id"]
    _write_research_doc(reg.get_session(sid)["worktree_path"])

    # A text-snapshot refinement → grass-<id>/dev-N (a refinement, NOT an archive).
    eh.save_grass_refinement(repo, pid, iid, text="snapshot text", label="r1")
    # An archive bundle → docs + summary.
    eh.archive_grass_session(pid, iid, "research", folder_path=repo)

    refs = eh.list_grass_refinements(repo, pid, iid)
    arch = eh.list_grass_archives(repo, pid, iid)
    assert len(refs) == 1 and "refinement_id" in refs[0]
    assert len(arch) == 1 and "docs" in arch[0]
    # The two are separate fields on the workbench projection.
    wb = {i["idea_id"]: i for i in eh.grass_workbench_data(repo, pid)}[iid]
    assert wb["refinements"] and wb["archives"]
    assert wb["refinements"][0].get("refinement_id")
    assert wb["archives"][0].get("session_id") == sid
    ts.kill(sid)


# ════════════════════════════════════════════════════════════════════════════
# (b) LINEAGE — export stamps grass_origin; the chain inherits it; SAFE projection
# ════════════════════════════════════════════════════════════════════════════

def test_export_stamps_grass_origin_and_chain_inherits(env):
    eh, ts, reg, repo, pid = (env["eh"], env["ts"], env["reg"],
                              env["repo"], env["pid"])
    idea = eh.add_idea(repo, pid, "Idea to export and trace")
    iid = idea["job_id"]
    dev = eh.develop_grass_idea(pid, iid, "research")
    dsid = dev["session_id"]
    _write_research_doc(reg.get_session(dsid)["worktree_path"])

    res = eh.export_grass_to_project(pid, iid, folder_path=repo)
    assert res["ok"] is True, res
    # The exported lane effort carries from_grass_idea + grass_origin == idea id.
    exp = res["exported"][0]
    eff = eh.load_effort(repo, pid, exp["lane"], exp["export_effort_id"])
    assert eff["grass_origin"] == iid
    assert eff["from_grass_idea"] == iid

    # The dev session's registry record is now stamped with grass_origin, so a
    # NEW session started with it as parent INHERITS the origin (chain traces back).
    assert reg.get_session(dsid)["grass_origin"] == iid
    child = ts.start_session(pid, "plan", backend="claude",
                             parent_session_id=dsid)
    csid = child["session_id"]
    assert reg.get_session(csid)["grass_origin"] == iid, \
        "a downstream project session in the chain must inherit grass_origin"
    # And the grandchild inherits too (origin rides the whole chain).
    gchild = ts.start_session(pid, "build", backend="claude",
                              parent_session_id=csid)
    assert reg.get_session(gchild["session_id"])["grass_origin"] == iid

    ts.kill(csid)
    ts.kill(gchild["session_id"])
    ts.kill(dsid)


def test_grass_origin_inheritance_reaches_chain_root(env):
    """FIX 1 (D8): the stamp must reach the CHAIN ROOT, not just one level.

    Build a chain root (research) carrying grass_origin, a middle (plan) child
    whose OWN record's grass_origin is CLEARED (empty), then a grandchild (build)
    whose direct parent (the middle) has NO stamp but a chain ANCESTOR (the root)
    does. The grandchild's OWN record must carry the origin.

    NON-VACUOUS: against the pre-fix one-level code
    (``origin = parent_rec.get('grass_origin')``) the middle's empty stamp would
    leave the grandchild with ``grass_origin == ''`` → this asserts FAILs pre-fix.
    """
    ts, reg, pid = env["ts"], env["reg"], env["pid"]
    iid = "grass-root-origin"
    # Root research session explicitly stamped with the grass origin.
    root = ts.start_session(pid, "research", backend="claude",
                            grass_origin=iid)
    rsid = root["session_id"]
    assert reg.get_session(rsid)["grass_origin"] == iid

    # Middle plan child — it WOULD inherit, but we forcibly CLEAR its stamp to
    # simulate a record whose own grass_origin is empty while an ancestor's isn't.
    mid = ts.start_session(pid, "plan", backend="claude", parent_session_id=rsid)
    msid = mid["session_id"]
    reg.update_session(msid, grass_origin="")
    # Guard the construction: the middle's OWN record is now empty.
    assert reg.get_session(msid)["grass_origin"] == ""
    # It still shares the root's chain (so a chain walk can find the root's stamp).
    assert reg.chain_for(msid) == reg.chain_for(rsid)

    # Grandchild build whose DIRECT parent (middle) has empty grass_origin.
    gchild = ts.start_session(pid, "build", backend="claude",
                              parent_session_id=msid)
    gsid = gchild["session_id"]
    assert reg.get_session(gsid)["grass_origin"] == iid, \
        ("the grandchild must adopt the grass_origin carried by a CHAIN ANCESTOR "
         "even when its direct parent's own record is empty (FIX 1)")

    ts.kill(gsid)
    ts.kill(msid)
    ts.kill(rsid)


def test_archive_idempotent_on_identical_content(env):
    """FIX 4: archiving the same UNCHANGED session twice yields exactly ONE
    bundle (content-addressed on lane+session_id+sorted(docs)); a genuinely-new
    doc set appends a distinct bundle (append-only history preserved)."""
    eh, ts, reg, repo, pid = (env["eh"], env["ts"], env["reg"],
                              env["repo"], env["pid"])
    idea = eh.add_idea(repo, pid, "Idempotent archive idea")
    iid = idea["job_id"]
    dev = eh.develop_grass_idea(pid, iid, "research")
    sid = dev["session_id"]
    wt = reg.get_session(sid)["worktree_path"]
    _write_research_doc(wt, rel="research/run-x/report.md")

    out1 = eh.archive_grass_session(pid, iid, "research", folder_path=repo)
    assert out1["ok"] is True
    out2 = eh.archive_grass_session(pid, iid, "research", folder_path=repo)
    assert out2["ok"] is True
    arch = eh.list_grass_archives(repo, pid, iid)
    assert len(arch) == 1, f"double-archive must not duplicate, got {len(arch)}"

    # A genuinely-different doc set (a second produced doc) is a NEW archive.
    _write_research_doc(wt, rel="research/run-x/extra.md", body="# Extra\nMore.\n")
    out3 = eh.archive_grass_session(pid, iid, "research", folder_path=repo)
    assert out3["ok"] is True
    arch2 = eh.list_grass_archives(repo, pid, iid)
    assert len(arch2) == 2, "a different doc set should append a new bundle"

    ts.kill(sid)


def test_archive_after_kill_is_honest(env):
    """FIX/coverage: archiving a session AFTER it was killed (worktree reaped) is
    honest. The kill-time persist already committed the docs into the main repo,
    so they are recovered (efforts_for_session_id) and the archive succeeds; if
    nothing was persisted it returns honest no-docs — never a crash."""
    eh, ts, reg, repo, pid = (env["eh"], env["ts"], env["reg"],
                              env["repo"], env["pid"])
    idea = eh.add_idea(repo, pid, "Archive after kill idea")
    iid = idea["job_id"]
    dev = eh.develop_grass_idea(pid, iid, "research")
    sid = dev["session_id"]
    rel = _write_research_doc(reg.get_session(sid)["worktree_path"])

    # Kill FIRST (reaps the worktree; kill persists produced docs before reap).
    ts.kill(sid)
    assert (repo / rel).is_file()  # kill-time persist committed the doc

    # Now archive — the worktree is gone, but the docs were persisted at kill.
    out = eh.archive_grass_session(pid, iid, "research", folder_path=repo)
    assert out["ok"] in (True, False)  # never crashes
    if out["ok"]:
        assert rel in out["archive"]["docs"]
        assert eh.list_grass_archives(repo, pid, iid)
    else:
        # Honest unresolved is acceptable only as no-docs (never a fabrication).
        assert out["reason"] in ("no-docs", "no-dev-session")


def test_safe_chain_projection_carries_grass_origin_not_worktree(env):
    """The SAFE chain projection (the same shape /api/rnd/chain emits) carries
    grass_origin but NEVER worktree_path / branch."""
    eh, ts, reg, repo, pid = (env["eh"], env["ts"], env["reg"],
                              env["repo"], env["pid"])
    idea = eh.add_idea(repo, pid, "Idea projected safely")
    iid = idea["job_id"]
    dev = eh.develop_grass_idea(pid, iid, "research")
    dsid = dev["session_id"]
    _write_research_doc(reg.get_session(dsid)["worktree_path"])
    eh.export_grass_to_project(pid, iid, folder_path=repo)
    child = ts.start_session(pid, "plan", backend="claude",
                             parent_session_id=dsid)
    csid = child["session_id"]

    # Build the SAFE projection the server emits (mirror the /api/rnd/chain handler).
    chain_id = reg.chain_for(csid)
    members = reg.chain_members(chain_id)
    safe = []
    for r in members:
        safe.append({
            "session_id": r.get("session_id"),
            "lane": r.get("lane", ""),
            "label": r.get("label", ""),
            "status": r.get("status", ""),
            "parent_session_id": r.get("parent_session_id", ""),
            "chain_id": r.get("chain_id", ""),
            "grass_origin": r.get("grass_origin", ""),
        })
    # The child carries the origin in the projection.
    child_proj = [m for m in safe if m["session_id"] == csid][0]
    assert child_proj["grass_origin"] == iid
    # NO leak of worktree_path / branch anywhere in the projection.
    for m in safe:
        assert "worktree_path" not in m
        assert "branch" not in m

    ts.kill(csid)
    ts.kill(dsid)


# ════════════════════════════════════════════════════════════════════════════
# (c) NEGATIVE — a non-grass session has grass_origin == ""
# ════════════════════════════════════════════════════════════════════════════

def test_non_grass_session_has_empty_grass_origin(env):
    ts, reg, pid = env["ts"], env["reg"], env["pid"]
    sess = ts.start_session(pid, "research", backend="claude")
    sid = sess["session_id"]
    rec = reg.get_session(sid)
    assert rec["grass_origin"] == ""
    # Its child also inherits empty (no contamination of non-grass chains).
    child = ts.start_session(pid, "plan", backend="claude",
                             parent_session_id=sid)
    assert reg.get_session(child["session_id"])["grass_origin"] == ""
    ts.kill(child["session_id"])
    ts.kill(sid)


def test_back_compat_record_normalizes_grass_origin(env):
    """A pre-v10 record with no grass_origin normalizes to ""."""
    reg = env["reg"]
    rec = reg._normalize({"session_id": "old1", "project_id": env["pid"],
                          "lane": "research"})
    assert rec["grass_origin"] == ""


# ════════════════════════════════════════════════════════════════════════════
# DOM — the "Archived material" list + the "from grass:" lineage chip
# ════════════════════════════════════════════════════════════════════════════

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


def _selectgrass_html(gui):
    """Reconstruct the static markup selectGrassIdea() emits (string literals
    joined), mirroring tests/test_grass_two_terminals_v10.py."""
    js = gui._PROJECT_WINDOW_JS
    m = re.search(r"function selectGrassIdea\(ideaId\)\s*\{([\s\S]*?)\n\}\n", js)
    assert m, "selectGrassIdea not found"
    body = m.group(1)
    hm = re.search(r"var html = ''([\s\S]*?);\n\s*work\.innerHTML = html;", body)
    assert hm, "selectGrassIdea html template not found"
    tmpl = hm.group(1)
    lits = re.findall(r"'((?:\\.|[^'\\])*)'", tmpl)
    return "".join(s.replace("\\'", "'") for s in lits)


def test_dom_workbench_has_archive_snapshot_control_v12(env):
    """v12 Wave 11 (MIGRATED): the one-session workbench renders a SINGLE
    "Archive snapshot" control in its header (.garchive-snap) — not the retired
    per-lane (research/plan) archive controls. (The backend archive bundle path is
    unchanged + covered by the backend tests above.)"""
    html = _selectgrass_html(env["gui"])
    els = _parse(html)
    # ONE Archive snapshot control (header), not per-lane.
    snaps = [d for t, d in els if "garchive-snap" in (d.get("class") or "").split()]
    assert len(snaps) == 1, \
        f"expected one Archive-snapshot control, got {len(snaps)}"
    # The retired per-lane archive controls are gone.
    assert not [d for t, d in els if d.get("data-archive-lane")], \
        "the retired per-lane Archive controls must be gone (v12 W11)"


def test_dom_archive_distinct_from_migrate_v12(env):
    """v12 Wave 11 (MIGRATED): the Archive snapshot control is DISTINCT from the
    Migrate-to-project control — different classes, neither is a per-lane save."""
    html = _selectgrass_html(env["gui"])
    els = _parse(html)
    snaps = [d for t, d in els if "garchive-snap" in (d.get("class") or "").split()]
    migs = [d for t, d in els if "gmigrate" in (d.get("class") or "").split()]
    assert len(snaps) == 1 and len(migs) == 1
    assert snaps[0] is not migs[0]
    # No retired per-lane save controls remain.
    assert not [d for t, d in els if d.get("data-save-lane")], \
        "the retired per-lane Save controls must be gone (v12 W11)"


def _lineage_chip_js(gui):
    """Extract the _loadGrassOriginChip function body (the lineage back-link)."""
    js = gui._PROJECT_WINDOW_JS
    m = re.search(r"function _loadGrassOriginChip\([\s\S]*?\n\}\n", js)
    assert m, "_loadGrassOriginChip not found in _PROJECT_WINDOW_JS"
    return m.group(0)


def test_dom_lineage_chip_function_present_and_honest(env):
    """POSITIVE: a _loadGrassOriginChip helper renders a 'from grass:' chip from a
    session's grass_origin. NEGATIVE: it renders NOTHING when grass_origin is empty
    (honest — no fabricated back-link)."""
    fn = _lineage_chip_js(env["gui"])
    # Positive: the chip text + a class to target it.
    assert "from grass" in fn
    assert "grassorigin" in fn.lower()
    # Negative: an empty origin returns early (no chip). The function must guard on
    # a falsy grass_origin.
    assert re.search(r"if\s*\(\s*!\s*(origin|go|gid)\b", fn), \
        "the chip must early-return on an empty grass_origin (honest, no fake link)"
    # openPanel wires it (called with the session id).
    assert "_loadGrassOriginChip(" in env["gui"]._PROJECT_WINDOW_JS


# ════════════════════════════════════════════════════════════════════════════
# FIX 2/3 — the BOARD-TILE "from grass" chip (server render + JS dead-chip path)
# ════════════════════════════════════════════════════════════════════════════

def _reg_sv(gui, session_id, lane="plan", grass_origin="", status="running"):
    """A registry-shaped session view the board-tile renderer consumes."""
    return gui._registry_session_view({
        "session_id": session_id, "lane": lane, "status": status,
        "label": "Plan — cooling loop", "created_at": 1.0,
        "grass_origin": grass_origin,
        # The renderer must NEVER read these — proves the SAFE field is used.
        "worktree_path": "/secret/worktree/path", "branch": "secret-branch",
    })


def test_board_tile_renders_grass_origin_chip_positive(env):
    """POSITIVE: a board plan/build tile whose session carries grass_origin emits
    the 'from grass' chip stub keyed by the SAFE idea id (data-grass-origin), and
    NEVER leaks worktree_path/branch onto the tile."""
    gui = env["gui"]
    iid = "grass-abc123"
    sv = {"session_id": "sess-plan-1",
          "members": [_reg_sv(gui, "sess-plan-1", "plan", grass_origin=iid)]}
    html = gui._render_lane_tile(sv, "plan", env["pid"])
    els = _parse(html)
    chips = [d for t, d in els if "grassorigin" in (d.get("class") or "").split()]
    assert chips, "a grass_origin plan tile must render a 'from grass' chip"
    assert chips[0].get("data-grass-origin") == iid
    assert chips[0].get("data-grass-pending") == "1", \
        "the tile chip is a stub resolved client-side"
    assert "from grass" in html.lower()
    # SAFE: the secret worktree/branch never leak into the tile markup.
    assert "/secret/worktree/path" not in html
    assert "secret-branch" not in html


def test_board_tile_no_chip_for_non_grass_session(env):
    """NEGATIVE: a non-grass session (empty grass_origin) renders NO chip."""
    gui = env["gui"]
    sv = {"session_id": "sess-plan-2",
          "members": [_reg_sv(gui, "sess-plan-2", "plan", grass_origin="")]}
    html = gui._render_lane_tile(sv, "plan", env["pid"])
    els = _parse(html)
    chips = [d for t, d in els if "grassorigin" in (d.get("class") or "").split()]
    assert not chips, "a non-grass tile must show NO 'from grass' chip"


def _grass_chip_js(gui):
    """Extract the _loadGrassOriginChip (panel) + _resolveGrassOriginChips (tile)
    helpers — both share the dead-chip path."""
    js = gui._PROJECT_WINDOW_JS
    m1 = re.search(r"function _loadGrassOriginChip\([\s\S]*?\n\}\n", js)
    m2 = re.search(r"function _resolveGrassOriginChips\([\s\S]*?\n\}\n", js)
    assert m1, "_loadGrassOriginChip not found"
    assert m2, "_resolveGrassOriginChips not found"
    return m1.group(0) + m2.group(0)


def test_dom_dead_chip_path_present(env):
    """FIX 3: the chip resolvers render a GREYED/disabled 'idea removed' state
    (no live link) when the origin idea is not in _grassData — honest, not an
    inert live link. Asserted on BOTH the panel + tile helpers."""
    fn = _grass_chip_js(env["gui"])
    # A 'removed' class is applied + a distinct 'idea removed' label.
    assert fn.count("removed") >= 2  # both helpers apply the removed class
    assert fn.lower().count("idea removed") >= 2
    # The tile dead path clears the click link (onclick = null); the panel dead
    # path simply omits the onclick (returns before assigning one).
    assert re.search(r"onclick\s*=\s*null", fn), \
        "the tile dead chip must clear its live click link"
    # Both helpers branch on whether the idea exists in _grassData.
    assert "_grassData" in fn


# ════════════════════════════════════════════════════════════════════════════
# ENDPOINT — POST /api/rnd/grass_archive (token-gated)
# ════════════════════════════════════════════════════════════════════════════

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
        time.sleep(0.05)
        try:
            srv.shutdown()
        except Exception:
            pass
        try:
            srv.server_close()
        except Exception:
            pass
        t.join(timeout=5)


def test_endpoint_grass_archive(server):
    import json
    import urllib.request
    env, base, _ = server
    eh, ts, reg, repo, pid = (env["eh"], env["ts"], env["reg"],
                              env["repo"], env["pid"])
    idea = eh.add_idea(repo, pid, "Endpoint archive idea")
    iid = idea["job_id"]
    dev = eh.develop_grass_idea(pid, iid, "research")
    sid = dev["session_id"]
    _write_research_doc(reg.get_session(sid)["worktree_path"])

    payload = json.dumps({"project_id": pid, "idea_id": iid,
                          "lane": "research"}).encode()
    req = urllib.request.Request(base + "/api/rnd/grass_archive", data=payload,
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read().decode())
    assert data["ok"] is True
    assert data["archive"]["session_id"] == sid
    # The idea record now carries the bundle.
    assert eh.list_grass_archives(repo, pid, iid)
    ts.kill(sid)


# ════════════════════════════════════════════════════════════════════════════
# Playwright (DEV-ONLY): Archive → bundle list; lineage chip on a tile
# ════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def pw_server(env):
    """A hardened Playwright server fixture (mirrors W3's robust teardown)."""
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


def test_archive_button_and_lineage_chip_in_browser(pw_server):
    """v12 Wave 11 (MIGRATED). In the one-session grass workbench: Open the single
    session → write a doc in its worktree → click the header **Archive snapshot**
    control → assert the History panel shows the archived bundle (no JS console
    error). Then export the idea (stamping grass_origin), start a downstream linked
    session, open its panel → assert the '🌱 from grass:' lineage chip renders.
    Screenshot → _devtest/wave4_grass_archive_lineage.png."""
    pytest.importorskip("playwright.sync_api")
    env, base, _ = pw_server
    eh, ts, reg, repo, pid = (env["eh"], env["ts"], env["reg"],
                              env["repo"], env["pid"])

    from playwright.sync_api import sync_playwright
    _DEVTEST.mkdir(exist_ok=True)
    shot = _DEVTEST / "wave4_grass_archive_lineage.png"

    # Seed an idea for the workbench to select.
    idea = eh.add_idea(repo, pid, "Passive autonomous cooling loop",
                       notes="A natural-circulation decay-heat loop.")
    iid = idea["job_id"]

    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        errors = []
        pg.on("console",
              lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.goto(f"{base}/project/{pid}", wait_until="networkidle")
        from tests.ui_helpers import expand_workbench
        expand_workbench(pg)  # the Workbench tile now opens collapsed

        # Open the grass workbench + select the idea.
        pg.wait_for_selector('[data-grass-tile="1"]', timeout=8000)
        pg.click('[data-grass-tile="1"]')
        pg.wait_for_selector('#grassPanel .gli', timeout=8000)
        pg.eval_on_selector('#grassPanel .gli', "e=>e.click()")
        pg.wait_for_selector('#grassPanel .gwork .gterm[data-lane="research"]',
                             timeout=8000)

        # Open the SINGLE workbench session → it binds; write a doc in its worktree
        # so there IS material to archive.
        pg.click('#grassPanel .gwork .gopen')
        pg.wait_for_function(
            "document.querySelector('#grassPanel .gwork [data-grass-term]') && "
            "document.querySelector('#grassPanel .gwork [data-grass-term]')"
            ".getAttribute('data-session')", timeout=10000)
        rsid = pg.eval_on_selector(
            '#grassPanel .gwork [data-grass-term]',
            "e=>e.getAttribute('data-session')")
        assert rsid
        _write_research_doc(reg.get_session(rsid)["worktree_path"])

        # Click the header Archive snapshot control.
        pg.click('#grassPanel .gwork .garchive-snap')
        # The History panel now shows the archived bundle (an .hitem.arch row).
        pg.wait_for_selector('#grassPanel .gwork .ghist .hitem.arch', timeout=10000)
        ar_count = pg.eval_on_selector_all(
            '#grassPanel .gwork .ghist .hitem.arch', "els=>els.length")
        assert ar_count >= 1, "the History panel should show the archived bundle"
        assert not errors, f"JS console errors on archive: {errors}"

        pg.screenshot(path=str(shot), full_page=True)
        b.close()

    assert shot.exists()

    # ── Lineage chip: export the idea (stamps grass_origin), start a downstream
    #    linked session, open its panel → the '🌱 from grass:' chip renders. ────
    eh.export_grass_to_project(pid, iid, folder_path=repo)
    child = ts.start_session(pid, "plan", backend="claude",
                             parent_session_id=rsid)
    csid = child["session_id"]
    assert reg.get_session(csid)["grass_origin"] == iid

    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        cerrors = []
        pg.on("console",
              lambda m: cerrors.append(m.text) if m.type == "error" else None)
        pg.goto(f"{base}/project/{pid}", wait_until="networkidle")
        from tests.ui_helpers import expand_workbench
        expand_workbench(pg)  # the Workbench tile now opens collapsed
        # Open the downstream session's panel (it appears in the plan lane column
        # as a live tile). Use openPanel directly for determinism.
        pg.wait_for_function("typeof openPanel === 'function'", timeout=8000)
        pg.evaluate("sid => openPanel(sid)", csid)
        # The lineage chip renders into the panel header (filled async from
        # /api/rnd/chain which carries grass_origin).
        pg.wait_for_selector('.panel .grassorigin', timeout=10000)
        chip_txt = pg.eval_on_selector('.panel .grassorigin', "e=>e.textContent")
        assert "from grass" in chip_txt, f"chip should read 'from grass:', got {chip_txt}"
        origin = pg.eval_on_selector('.panel .grassorigin',
                                     "e=>e.getAttribute('data-grass-origin')")
        assert origin == iid
        assert not cerrors, f"JS console errors on lineage chip: {cerrors}"
        b.close()

    # Teardown: reap all sessions.
    for r in reg.list_sessions(project_id=pid):
        try:
            ts.kill(r["session_id"])
        except Exception:
            pass


def test_board_tile_chip_and_dead_chip_in_browser(pw_server):
    """FIX 2/3 in a real browser: a downstream plan session whose chain carries
    grass_origin shows the 'from grass' chip ON ITS BOARD TILE (not only the
    panel). Then DELETE the originating idea and reload → the SAME tile chip
    resolves to the GREYED/disabled 'idea removed' dead state with no live link
    and no JS console error."""
    pytest.importorskip("playwright.sync_api")
    env, base, _ = pw_server
    eh, ts, reg, repo, pid = (env["eh"], env["ts"], env["reg"],
                              env["repo"], env["pid"])
    from playwright.sync_api import sync_playwright

    # An exported idea + a downstream linked plan session (carries grass_origin).
    idea = eh.add_idea(repo, pid, "Tile lineage idea")
    iid = idea["job_id"]
    dev = eh.develop_grass_idea(pid, iid, "research")
    rsid = dev["session_id"]
    _write_research_doc(reg.get_session(rsid)["worktree_path"])
    eh.export_grass_to_project(pid, iid, folder_path=repo)
    child = ts.start_session(pid, "plan", backend="claude",
                             parent_session_id=rsid)
    csid = child["session_id"]
    assert reg.get_session(csid)["grass_origin"] == iid

    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        errs = []
        pg.on("console",
              lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.goto(f"{base}/project/{pid}", wait_until="networkidle")
        from tests.ui_helpers import expand_workbench
        expand_workbench(pg)  # the Workbench tile now opens collapsed
        # The plan lane column tile for csid resolves its chip (label, live link).
        sel = ('.tile[data-session="' + csid + '"] .grassorigin')
        pg.wait_for_function(
            "(s)=>{var c=document.querySelector(s);"
            "return c && !c.hasAttribute('data-grass-pending');}",
            arg=sel, timeout=10000)
        txt = pg.eval_on_selector(sel, "e=>e.textContent")
        assert "from grass" in txt
        is_removed = pg.eval_on_selector(
            sel, "e=>e.classList.contains('removed')")
        assert not is_removed, "a live idea must NOT render the removed dead-chip"
        assert not errs, f"JS console errors on tile chip: {errs}"
        b.close()

    # DELETE the originating idea → the chip must go dead on reload.
    eh.delete_grass_idea(repo, pid, iid)
    assert eh.get_grass_idea(repo, pid, iid) is None

    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        errs2 = []
        pg.on("console",
              lambda m: errs2.append(m.text) if m.type == "error" else None)
        pg.goto(f"{base}/project/{pid}", wait_until="networkidle")
        from tests.ui_helpers import expand_workbench
        expand_workbench(pg)  # the Workbench tile now opens collapsed
        sel = ('.tile[data-session="' + csid + '"] .grassorigin')
        pg.wait_for_function(
            "(s)=>{var c=document.querySelector(s);"
            "return c && c.classList.contains('removed');}",
            arg=sel, timeout=10000)
        txt2 = pg.eval_on_selector(sel, "e=>e.textContent")
        assert "idea removed" in txt2.lower(), \
            f"deleted origin must render a dead chip, got {txt2}"
        # No live link on the dead chip.
        has_handler = pg.eval_on_selector(sel, "e=>!!e.onclick")
        assert not has_handler, "the dead chip must not carry a live click handler"
        assert not errs2, f"JS console errors on dead chip: {errs2}"
        b.close()

    for r in reg.list_sessions(project_id=pid):
        try:
            ts.kill(r["session_id"])
        except Exception:
            pass
