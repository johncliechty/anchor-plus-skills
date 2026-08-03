"""v8 Wave 4 — Handoff that carries the documents.

Now that produced docs are DURABLE (Wave 2), the handoff is made real:

  - The plan→build seed (``_build_seed_for_plan``) and the research→plan seed
    (``_build_seed_for_research``) list the ACTUAL persisted document paths +
    a "read these first" instruction + name the correct trio skill
    (build→Foreman, plan→Crucible). They are wired as ``seed_context`` into the
    advance/auto-advance paths.
  - The build's HANDOFF.md (``handoff.prime_worktree``) references plan-doc paths
    that GENUINELY EXIST in the build checkout (off main HEAD, after Wave-2's
    commit-to-main).
  - ``term_kill`` ordering: kill() PERSISTS the planning session's freshly-produced
    docs into the main folder BEFORE the plan set is captured, so the auto-opened
    build actually gets the real plan.
  - Skill clarity: ``LANE_SKILL`` maps build→Foreman / plan→Crucible /
    research→researchPrime (build NEVER loads Crucible), and the panel header
    surfaces the loaded skill.

Hermetic: NO real claude/gemini, NO real PTY — ``ANCHOR_PTY_BACKEND=stub``, a
temp git repo for the worktree, a tmp data dir + tmp worktree base. NEVER binds
``:8777``; NEVER a worktree off the real ``C:\\dev\\Anchor`` repo; NEVER real
push / gh / network.
"""
import importlib
import json as _json
import re
import subprocess
import threading
import urllib.request as _req
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


# ── env / fixtures (stub PTY + temp git repo + project) ──────────────────────

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

    for mod in ("paths", "job_runner", "pty_manager", "rnd_registry",
                "effort_history", "sessions", "anchor_marker",
                "session_registry", "worktrees", "lanes", "summarizer",
                "handoff", "terminal_session"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import anchor_gui
    gui = importlib.reload(anchor_gui)

    import effort_history
    import handoff
    import terminal_session
    import session_registry
    import rnd_registry

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial")

    proj = rnd_registry.add_project("Temp", str(repo), scaffold=False)
    bundle = {
        "gui": gui, "ts": terminal_session, "reg": session_registry,
        "handoff": handoff, "eh": effort_history, "rnd": rnd_registry,
        "repo": repo, "pid": proj["id"], "wbase": wbase, "data": data,
    }
    yield bundle
    try:
        import pty_manager
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


def _write_plan_docs_in_worktree(worktree_path, plan_dir="planning/rnd-x"):
    """What Crucible would write: a MASTER + IMPL plan set (uncommitted)."""
    wt = Path(worktree_path)
    master = f"{plan_dir}/MASTER-PLAN.md"
    impl = f"{plan_dir}/IMPLEMENTATION-PLAN.md"
    log = f"{plan_dir}/EXECUTION-LOG.md"
    for rel, body in [(master, "# Master Plan\nThe locked north star.\n"),
                      (impl, "# Implementation Plan\nWave-by-wave.\n"),
                      (log, "# Execution Log\n")]:
        p = wt / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return {"master": master, "impl": impl, "log": log}


def _write_research_doc_in_worktree(worktree_path,
                                    rel="research/cooling/REPORT.md"):
    wt = Path(worktree_path)
    p = wt / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# Cooling report\n## Findings\nAdequate.\n", encoding="utf-8")
    return rel


def _js(html):
    return "\n".join(re.findall(r"<script[^>]*>([\s\S]*?)</script>", html))


# ════════════════════════════════════════════════════════════════════════════
# (A) BACKEND — generated seed lists REAL persisted paths + correct skill
# ════════════════════════════════════════════════════════════════════════════

def test_plan_to_build_paste_contains_real_paths_and_names_foreman(env):
    """A finished planning session whose docs are PERSISTED (W2), advanced to
    build, yields a build session whose handoff TASK PROMPT CONTAINS the real
    planning/.../IMPLEMENTATION-PLAN.md path + MASTER-PLAN.md + a read-first
    instruction + names Foreman.

    v10 Wave 2 moved that task prompt OUT of the auto-submitted phase-1 seed
    (which now only loads+greets the Foreman skill, no doc paths) and INTO the
    PENDING PASTE channel — ``pending_paste`` on the record AND the durable,
    reviewable ``NEXT-PROMPT.md`` written into the build worktree (delivered
    UNSENT). This test asserts the SAME guarantee in that new location: the real
    plan-doc paths + Foreman + a read-first instruction are delivered to the
    build via the paste, and HANDOFF.md still references files that EXIST in the
    build checkout."""
    ts, reg, repo, pid, ho = (env["ts"], env["reg"], env["repo"], env["pid"],
                              env["handoff"])

    plan_sess = ts.start_session(pid, "planning", backend="claude")
    psid = plan_sess["session_id"]
    docs = _write_plan_docs_in_worktree(plan_sess["worktree_path"])

    # kill() persists the docs into the main folder + commits to main HEAD, then
    # reaps the worktree (Wave 2 capture-before-reap).
    out = ts.kill(psid)
    assert out["docs"]["ok"] is True
    assert docs["impl"] in out["docs"]["persisted"]

    # Capture AFTER kill (the term_kill ordering fix) → the now-persisted plan
    # set is discoverable from the MAIN folder.
    plan_set = ts.capture_plan_set(pid, psid)
    assert plan_set is not None
    assert plan_set["impl_plan_rel"] == docs["impl"]

    build = ts.auto_advance_planning_to_build(pid, psid, plan_set=plan_set)
    assert build is not None
    bsid = build["session_id"]

    # v10 Wave 2: the TASK PROMPT (real doc paths + read-first) is the PENDING
    # PASTE, not the auto-submitted seed. The phase-1 seed still NAMES Foreman
    # (load+greet), but the doc paths now live in the paste.
    paste = build.get("pending_paste", "") or ""
    assert "Foreman" in paste, paste
    assert docs["impl"] in paste, "paste missing the real IMPLEMENTATION-PLAN path"
    assert docs["master"] in paste, "paste missing the real MASTER-PLAN path"
    assert re.search(r"[Rr]ead these", paste), "no read-first instruction in paste"
    # The build NEVER loads Crucible (the user's confusion).
    assert "Crucible" not in paste
    # The phase-1 seed loads+greets Foreman (names the skill, no doc paths there).
    seed = build.get("seed_text", "") or ""
    assert "Foreman" in seed, seed
    assert "Crucible" not in seed

    # The PENDING PASTE is held UNSENT (not yet flushed) — delivered, not submitted.
    assert build.get("paste_flushed") is not True

    # The build worktree carries the durable, reviewable NEXT-PROMPT.md, and it
    # references the real IMPL + MASTER paths + Foreman + read-first.
    bwt = Path(build["worktree_path"])
    npf = bwt / ho.NEXT_PROMPT_FILENAME
    assert npf.exists(), "build worktree not primed with NEXT-PROMPT.md"
    nptext = npf.read_text(encoding="utf-8")
    assert docs["impl"] in nptext, "NEXT-PROMPT.md missing the real IMPL path"
    assert docs["master"] in nptext, "NEXT-PROMPT.md missing the real MASTER path"
    assert "Foreman" in nptext
    assert re.search(r"[Rr]ead these", nptext)

    # HANDOFF.md exists in the build checkout AND references files that EXIST.
    hf = bwt / ho.HANDOFF_FILENAME
    assert hf.exists(), "build worktree not primed with HANDOFF.md"
    htext = hf.read_text(encoding="utf-8")
    assert docs["master"] in htext and docs["impl"] in htext
    # The referenced plan docs physically exist in the build checkout.
    assert (bwt / docs["master"]).is_file()
    assert (bwt / docs["impl"]).is_file()

    ts.kill(bsid)


def test_research_to_plan_seed_contains_report_and_names_crucible(env):
    """The research→plan seed contains the persisted research report path + a
    read-first instruction + names Crucible (NOT Foreman, NOT researchPrime)."""
    ts, repo, pid = env["ts"], env["repo"], env["pid"]

    rsess = ts.start_session(pid, "research", backend="claude")
    rsid = rsess["session_id"]
    report_rel = _write_research_doc_in_worktree(rsess["worktree_path"])
    # kill() persists + commits the research report into the main folder.
    out = ts.kill(rsid)
    assert out["docs"]["ok"] is True
    assert report_rel in out["docs"]["persisted"]

    seed = ts.build_research_to_plan_seed(pid, rsid)
    assert seed is not None, "research→plan seed should resolve from the docs"
    assert "Crucible" in seed
    assert report_rel in seed, "seed missing the real research report path"
    assert re.search(r"[Rr]ead these", seed)
    assert "Foreman" not in seed


# ════════════════════════════════════════════════════════════════════════════
# (B) term_kill ORDERING — persist docs THEN the auto-advance sees them
# ════════════════════════════════════════════════════════════════════════════

def _free_server(gui):
    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, port, t


def _close_server(srv, t):
    """Race-proof teardown (matches the hardened v10 fixtures): give in-flight
    stream threads a beat, then shut down + close, each guarded so a benign
    client-disconnect teardown race can never fail the test."""
    import time
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


def test_term_kill_persists_then_advances_on_fresh_docs(env):
    """POST /api/rnd/term_kill on a planning session that just produced its plan
    docs (NOT previously persisted) auto-opens a build whose seed/HANDOFF
    reference the EXISTING persisted docs — proving kill persists BEFORE the
    plan-set capture (the ordering fix)."""
    ts, reg, repo, pid, gui, ho = (env["ts"], env["reg"], env["repo"],
                                   env["pid"], env["gui"], env["handoff"])

    plan_sess = ts.start_session(pid, "planning", backend="claude")
    psid = plan_sess["session_id"]
    # The docs exist ONLY in the worktree at kill time — they are NOT yet in the
    # main folder / discovery. If the handler captured the plan set BEFORE kill
    # (the old, broken order), discovery would find NOTHING and no build opens.
    docs = _write_plan_docs_in_worktree(plan_sess["worktree_path"])
    assert ho.discover_recent_plan_set(repo, pid,
                                       source_session_id=psid) is None, \
        "pre-condition: the plan set must not be discoverable BEFORE the kill"

    srv, port, t = _free_server(gui)
    bsid = None
    try:
        payload = _json.dumps({"session": psid}).encode("utf-8")
        req = _req.Request(f"http://127.0.0.1:{port}/api/rnd/term_kill",
                           data=payload,
                           headers={"Content-Type": "application/json"},
                           method="POST")
        with _req.urlopen(req, timeout=20) as r:
            data = _json.loads(r.read().decode("utf-8"))
        assert data["ok"] is True
        ab = data.get("auto_build")
        assert ab, "kill did not persist-then-advance: no auto_build on fresh docs"
        bsid = ab["session_id"]
        assert ab["lane"] == "build"
        assert ab["parent_session_id"] == psid

        # The build's PENDING PASTE + NEXT-PROMPT.md + HANDOFF reference the
        # EXISTING persisted docs. v10 Wave 2: the real doc paths live in the
        # pending paste (delivered unsent), NOT the auto-submitted phase-1 seed;
        # the seed still NAMES Foreman (load+greet).
        paste = ab.get("pending_paste", "") or ""
        assert docs["impl"] in paste and "Foreman" in paste
        assert ab.get("paste_flushed") is not True
        seed = ab.get("seed_text", "") or ""
        assert "Foreman" in seed
        bwt = Path(ab["worktree_path"])
        npf = bwt / ho.NEXT_PROMPT_FILENAME
        assert npf.exists()
        assert docs["impl"] in npf.read_text(encoding="utf-8")
        hf = bwt / ho.HANDOFF_FILENAME
        assert hf.exists()
        assert docs["impl"] in hf.read_text(encoding="utf-8")
        # And they physically exist in the build checkout (off main HEAD).
        assert (bwt / docs["impl"]).is_file()
        assert (bwt / docs["master"]).is_file()
        # The docs survived into the MAIN folder (persisted by kill).
        assert (repo / docs["impl"]).is_file()
    finally:
        if bsid:
            try:
                ts.kill(bsid)
            except Exception:
                pass
        _close_server(srv, t)


# ════════════════════════════════════════════════════════════════════════════
# (C) SKILL MAPPING + the panel-header skill chip (DOM)
# ════════════════════════════════════════════════════════════════════════════

def test_lane_skill_mapping_is_correct(env):
    """build→Foreman, plan/planning→Crucible, research→researchPrime — assert the
    mapping (the user's "build loads Crucible" confusion is impossible)."""
    ts = env["ts"]
    assert ts.LANE_SKILL["build"] == "Foreman"
    assert ts.LANE_SKILL["plan"] == "Crucible"
    assert ts.LANE_SKILL["planning"] == "Crucible"
    assert ts.LANE_SKILL["research"] == "researchPrime"
    # Build must NEVER map to Crucible anywhere.
    assert ts.LANE_SKILL["build"] != "Crucible"


def test_panel_header_surfaces_loaded_skill_in_js(env):
    """The panel header builds a skill chip from a lane→skill map mirroring
    LANE_SKILL, so it is unambiguous which skill a session loaded."""
    gui, pid = env["gui"], env["pid"]
    js = _js(gui.render_project_window_html(pid))
    # The JS skill-map helper exists and maps build→Foreman / plan→Crucible.
    assert "function _skillForLane(" in js
    assert "'Foreman'" in js
    assert "'Crucible'" in js
    assert "'researchPrime'" in js
    # The header builds a .skl chip from _skillForLane(s.lane).
    assert "_skillForLane(s.lane" in js
    assert "skillEl" in js
    assert "'skl'" in js
    # NEGATIVE: build never maps to Crucible in the JS map (the case labels for
    # plan/planning return Crucible; build returns Foreman — assert build's arm).
    assert re.search(r"case 'build':\s*return 'Foreman'", js), \
        "build must map to Foreman in _skillForLane"


# ════════════════════════════════════════════════════════════════════════════
# (D) REAL Playwright + Chromium — advance planning → build, header shows Foreman
# ════════════════════════════════════════════════════════════════════════════

def test_playwright_kill_planning_build_header_shows_foreman(env):
    """End-to-end: open a PLANNING session panel (header shows "planning ·
    Crucible"), hard-kill it → a BUILD tile auto-opens; open it and assert the
    panel header shows "build · Foreman" and the backend record's seed/HANDOFF
    reference the real persisted docs; no JS console errors. Saves
    _devtest/wave4_handoff.png."""
    pytest.importorskip("playwright.sync_api")
    ts, reg, repo, pid, gui, ho = (env["ts"], env["reg"], env["repo"],
                                   env["pid"], env["gui"], env["handoff"])

    plan_sess = ts.start_session(pid, "planning", backend="claude")
    psid = plan_sess["session_id"]
    docs = _write_plan_docs_in_worktree(plan_sess["worktree_path"])

    srv, port, t = _free_server(gui)
    base = f"http://127.0.0.1:{port}"
    from playwright.sync_api import sync_playwright
    devdir = Path(__file__).resolve().parent.parent / "_devtest"
    devdir.mkdir(exist_ok=True)
    shot = devdir / "wave4_handoff.png"
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page()
            errors = []
            pg.on("console",
                  lambda m: errors.append(m.text) if m.type == "error" else None)
            pg.on("dialog", lambda d: d.accept())  # accept the kill confirm()
            pg.goto(f"{base}/project/{pid}", wait_until="networkidle")
            from tests.ui_helpers import expand_workbench
            expand_workbench(pg)  # the Workbench tile now opens collapsed

            chip_sel = '#sessionBar .live-chip[data-session="%s"]' % psid
            pg.wait_for_selector(chip_sel, timeout=8000)
            pg.click(chip_sel)
            pg.wait_for_selector("#panelStack .panel", timeout=5000)
            # The planning panel header shows "planning · Crucible".
            pg.wait_for_selector('#panelStack .panel .pbar .skl', timeout=5000)
            skl_txt = pg.eval_on_selector(
                '#panelStack .panel[data-session="%s"] .pbar .skl' % psid,
                "e => e.textContent")
            assert "Crucible" in skl_txt, skl_txt
            assert "Foreman" not in skl_txt  # planning never loads Foreman

            # Hard-kill the planning panel → a build tile auto-opens. (W6 control-
            # unification renamed the old 🗑 .hardkill button to the single
            # destructive 🪦 Kill→Boneyard .killbone control.)
            pg.click("#panelStack .panel .panelbtn.killbone")
            pg.wait_for_selector('#sessionBar .live-chip[data-lane="build"]',
                                 timeout=8000)
            build_chips = pg.eval_on_selector_all(
                '#sessionBar .live-chip[data-lane="build"]',
                "els => els.map(e => e.getAttribute('data-session'))")
            assert build_chips, "no auto-opened build tile appeared"
            bsid = build_chips[0]

            # Open the build panel and assert its header shows "build · Foreman".
            pg.click('#sessionBar .live-chip[data-session="%s"]' % bsid)
            pg.wait_for_selector(
                '#panelStack .panel[data-session="%s"] .pbar .skl' % bsid,
                timeout=6000)
            bskl = pg.eval_on_selector(
                '#panelStack .panel[data-session="%s"] .pbar .skl' % bsid,
                "e => e.textContent")
            assert "Foreman" in bskl, bskl
            assert "Crucible" not in bskl, "build wrongly shows Crucible"

            pg.screenshot(path=str(shot), full_page=True)
            assert not errors, f"JS console errors: {errors}"

            # Backend truth: the header shows Foreman because the phase-1 seed
            # loads+greets Foreman; v10 Wave 2 puts the real doc paths in the
            # PENDING PASTE + NEXT-PROMPT.md (delivered UNSENT), not the
            # auto-submitted seed. HANDOFF.md still references the real docs.
            brec = reg.get_session(bsid)
            seed = brec.get("seed_text", "") or ""
            assert "Foreman" in seed
            paste = brec.get("pending_paste", "") or ""
            assert "Foreman" in paste and docs["impl"] in paste
            assert brec.get("paste_flushed") is not True
            bwt = Path(brec["worktree_path"])
            assert (bwt / ho.NEXT_PROMPT_FILENAME).exists()
            assert docs["impl"] in (bwt / ho.NEXT_PROMPT_FILENAME).read_text(
                encoding="utf-8")
            assert (bwt / ho.HANDOFF_FILENAME).exists()
            assert docs["impl"] in (bwt / ho.HANDOFF_FILENAME).read_text(
                encoding="utf-8")
            assert (bwt / docs["impl"]).is_file()
            b.close()
            try:
                ts.kill(bsid)
            except Exception:
                pass
    finally:
        _close_server(srv, t)
    assert shot.exists(), "screenshot not written"
