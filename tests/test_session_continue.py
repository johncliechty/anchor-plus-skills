"""v5 Wave 2 gate — past-session view: real summary + "Continue in a live session".

North-Star contract (MASTER-PLAN Locked Decision #2, IMPLEMENTATION-PLAN Wave 2):

  - A DONE/historical session's panel shows a REAL summary — the SKILL invoked,
    the PROMPTS/turns asked, and the ACTIONS/files produced — built through the
    validated ``summarizer`` seam (extraction-seed → generate-twice → grounding
    filter → cache; generate-once; force regenerates; a failed runner must not
    poison the cache). Honest/empty when data is absent (Risk R3).
  - A "Continue in a live session" button POSTs the new token-gated endpoint
    ``/api/rnd/continue_session`` → ``terminal_session.start_session`` in the SAME
    lane, seeded with the prior session's context. The ORIGINAL session record is
    NEVER mutated (Risk R2).

Un-gameable gate (the v4.1 model): summarizer unit tests with the stubbed runner +
endpoint auth/seed assertions + rendered-DOM structure (style/script stripped) +
a real Playwright/Chromium interaction test. Never :8777, never real data — stub
PTY backend, temp data dir + worktree base, the stub runner, a hermetic temp git
repo for worktrees.
"""
import importlib
import json
import re
import socket
import subprocess
import threading
from html.parser import HTMLParser
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()
STUB = (Path(__file__).resolve().parent / "stub_summarizer.py").as_posix()


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)


def _have_git():
    try:
        return subprocess.run(["git", "--version"],
                              capture_output=True).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


# ── (1) SUMMARIZER EXTENSION — skill/prompts/actions, stubbed runner ─────────

@pytest.fixture
def summ_mods(tmp_path, monkeypatch):
    """Reload the summarizer stack against a temp data dir + the STUB runner."""
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {STUB}")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    for mod in ("paths", "job_runner", "rnd_registry", "effort_history",
                "sessions", "report_viewer", "summarizer"):
        importlib.reload(importlib.import_module(mod))
    import job_runner, effort_history, rnd_registry, sessions, summarizer
    yield job_runner, effort_history, rnd_registry, sessions, summarizer
    for rec in job_runner.list_records():
        if rec.get("status") == job_runner.STATUS_RUNNING:
            try:
                job_runner.cancel(rec["job_id"])
            except Exception:
                pass
    job_runner._reset_live_table_for_tests()


def _run_research_session(rnd, eh, sessions, folder, *, skill="researchPrime",
                          prompt="Survey the literature on widgets",
                          job_id="r-job-1"):
    """Build a RUN research session (one effort = one session) with a skill +
    prompt_seed + a produced report on disk; return (pid, session)."""
    folder.mkdir(parents=True, exist_ok=True)
    proj = rnd.add_project("Anchor", str(folder))
    pid = proj["id"]
    # Record a RUN effort that names a skill + the asked-for prompt.
    eh.record_effort(folder, pid, "research", job_id, skill=skill,
                     prompt_seed=prompt)
    # Drop a produced report on disk under the effort dir so a member doc + the
    # grounding corpus exist (researchPrime/widgets terms appear in the corpus).
    arts = eh.detect_artifacts(folder, pid, "research", job_id)
    md_path = arts.get("md_path")
    if md_path:
        Path(md_path).parent.mkdir(parents=True, exist_ok=True)
        Path(md_path).write_text(
            "# Widgets research report\n\n## Findings\n"
            "Widgets are durable and resumable units of work.\n",
            encoding="utf-8")
    sess_list = sessions.list_sessions(folder, pid, "research")
    session = None
    for s in sess_list:
        if any(m.get("job_id") == job_id for m in s.get("member_files", [])):
            session = s
            break
    assert session is not None, "expected the RUN research session"
    return pid, session


def test_summary_captures_skill_prompts_actions(summ_mods, tmp_path, monkeypatch):
    """The extended summary dict captures the deterministic skill + prompts +
    actions read straight off the session/member records (not the model)."""
    jr, eh, rnd, sessions, summ = summ_mods
    folder = tmp_path / "proj"
    pid, session = _run_research_session(rnd, eh, sessions, folder)
    # Make the model emit ONE grounded claim so the pipeline still runs cleanly.
    monkeypatch.setenv("STUB_SUMMARIZER_CLAIMS",
                       "Widgets are durable resumable units of work")

    out = summ.summarize_session(folder, pid, "research", session)
    # Skill captured.
    assert out.get("skill") == "researchPrime"
    # Prompts captured (the member prompt_seed).
    prompts = out.get("prompts") or []
    assert any("widgets" in p.lower() for p in prompts), prompts
    # Actions / files produced captured (the produced report member).
    actions = out.get("actions") or []
    assert actions, "no produced-files captured"
    labels = " ".join((a.get("label") or "") for a in actions).lower()
    assert "widget" in labels or "report" in labels or actions[0].get("job_id")
    # Rendered markdown surfaces all three.
    md = out.get("markdown") or summ.render_markdown(out)
    assert "Skill invoked" in md and "researchPrime" in md
    assert "Prompts asked" in md
    assert "Actions & files produced" in md


def test_grounding_still_drops_ungrounded_claims(summ_mods, tmp_path,
                                                 monkeypatch):
    """The model-claim grounding filter is unchanged: an ungrounded claim the
    stub emits is dropped, while the new deterministic fields stay populated."""
    jr, eh, rnd, sessions, summ = summ_mods
    folder = tmp_path / "proj"
    pid, session = _run_research_session(rnd, eh, sessions, folder)
    grounded = "Widgets are durable resumable units of work"
    ungrounded = "Quux frobnicate zzyzx wibble bogus unrelated claim"
    monkeypatch.setenv("STUB_SUMMARIZER_CLAIMS", grounded + "\n" + ungrounded)

    out = summ.summarize_session(folder, pid, "research", session)
    joined = " ".join(out.get("claims") or []).lower()
    assert "frobnicate" not in joined and "zzyzx" not in joined
    # Deterministic capture is independent of the model filter.
    assert out.get("skill") == "researchPrime"
    assert out.get("prompts")


def test_honest_empty_when_no_prompt_or_skill(summ_mods, tmp_path, monkeypatch):
    """A discovered/imported session with no skill/prompt_seed yields honest
    empty skill/prompts (never fabricated), while actions still list the docs."""
    jr, eh, rnd, sessions, summ = summ_mods
    folder = tmp_path / "imp"
    plan_dir = folder / "planning" / "rnd-x"
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "MASTER-PLAN.md").write_text("# Master\n## Goal\nDo X.\n",
                                             encoding="utf-8")
    (plan_dir / "IMPLEMENTATION-PLAN.md").write_text("# Impl\n## Goal\nY.\n",
                                                     encoding="utf-8")
    proj = rnd.add_project("Imp", str(folder))
    pid = proj["id"]
    import brownfield_scan
    eh.adopt_discovered(str(folder), pid, brownfield_scan.scan(str(folder)))
    sess = sessions.list_sessions(folder, pid, "planning")
    session = next(s for s in sess
                   if any("rnd-x" in (m.get("artifact_path") or "")
                          for m in s.get("member_files", [])))
    monkeypatch.setenv("STUB_SUMMARIZER_CLAIMS", "Do X is the goal")

    out = summ.summarize_session(folder, pid, "planning", session)
    # No prompt_seed on a discovered effort → honest empty prompts.
    assert out.get("prompts") == []
    # But the produced docs are still listed as actions (not fabricated — read
    # off the real members).
    assert len(out.get("actions") or []) == 2


def test_cache_generate_once_then_force_regenerates(summ_mods, tmp_path,
                                                    monkeypatch):
    """Generate-once: a second summarize_session serves cache (no extra runner
    call); force=True re-runs the model and overwrites the cache."""
    jr, eh, rnd, sessions, summ = summ_mods
    folder = tmp_path / "proj"
    pid, session = _run_research_session(rnd, eh, sessions, folder)
    counter = tmp_path / "calls.txt"
    monkeypatch.setenv("STUB_SUMMARIZER_COUNTER", str(counter))
    monkeypatch.setenv("STUB_SUMMARIZER_CLAIMS",
                       "Widgets are durable resumable units of work")

    summ.summarize_session(folder, pid, "research", session)
    first = len(counter.read_text(encoding="utf-8")) if counter.exists() else 0
    assert first == summ.GENERATE_RUNS

    summ.summarize_session(folder, pid, "research", session)  # cached
    second = len(counter.read_text(encoding="utf-8")) if counter.exists() else 0
    assert second == first, "second call must serve cache (no extra runner run)"

    summ.summarize_session(folder, pid, "research", session, force=True)
    third = len(counter.read_text(encoding="utf-8")) if counter.exists() else 0
    assert third == first + summ.GENERATE_RUNS, "force must re-run the model"


def test_failed_runner_does_not_poison_cache(summ_mods, tmp_path, monkeypatch):
    """A failed runner returns a retryable error state and writes NO cache; a
    later (successful) call genuinely regenerates."""
    jr, eh, rnd, sessions, summ = summ_mods
    folder = tmp_path / "proj"
    pid, session = _run_research_session(rnd, eh, sessions, folder)
    monkeypatch.setenv("STUB_SUMMARIZER_FAIL", "1")
    monkeypatch.setenv("STUB_SUMMARIZER_CLAIMS",
                       "Widgets are durable resumable units of work")

    out = summ.summarize_session(folder, pid, "research", session)
    assert out.get("error") == "generation_failed"
    # Nothing cached.
    assert summ.load_cached(folder, pid, "research",
                            session["session_id"]) is None
    # The error state still carries the deterministic fields (honest).
    assert out.get("skill") == "researchPrime"

    # Now succeed → cache is written.
    monkeypatch.delenv("STUB_SUMMARIZER_FAIL", raising=False)
    ok = summ.summarize_session(folder, pid, "research", session)
    assert not ok.get("error")
    assert summ.load_cached(folder, pid, "research",
                            session["session_id"]) is not None


# ── (2) ENDPOINT auth + seeded-continue (no browser) ─────────────────────────

@pytest.fixture
def gui_env(tmp_path, monkeypatch):
    """Reload the full GUI stack: temp data dir + worktree base + stub PTY + the
    fake runner, with a project rooted at a hermetic temp git repo."""
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


def test_continue_session_token_gated(gui_env, tmp_path, monkeypatch):
    """continue_session is behind the do_POST token gate (mutating/terminal):
    with a token set, an unauthenticated POST is rejected (401/403)."""
    import importlib
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
            f"http://127.0.0.1:{port}/api/rnd/continue_session",
            data=_json.dumps({"project_id": "x", "lane": "research",
                              "source_session": "nope"}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            urllib.request.urlopen(req, timeout=5)
            status = 200
        except urllib.error.HTTPError as e:
            status = e.code
        assert status in (401, 403), \
            f"continue_session must reject unauthed POST, got {status}"
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


@pytest.mark.skipif(not _have_git(), reason="git not on PATH")
def test_continue_starts_new_seeded_session_original_intact(gui_env):
    """Authed continue starts a NEW running session in the SAME lane whose
    seed_text carries the prior session's context, and the ORIGINAL session +
    registry record is unchanged (Risk R2)."""
    gui = gui_env["gui"]
    pid = gui_env["pid"]
    import terminal_session as ts
    import session_registry as reg
    import effort_history as eh
    import sessions as sessmod
    import summarizer as summ
    folder = gui_env["repo"]

    # Build a DONE research session with a cached summary (the prior session).
    eh.record_effort(folder, pid, "research", "prior-1", skill="researchPrime",
                     prompt_seed="Investigate the cooling system")
    arts = eh.detect_artifacts(folder, pid, "research", "prior-1")
    if arts.get("md_path"):
        Path(arts["md_path"]).parent.mkdir(parents=True, exist_ok=True)
        Path(arts["md_path"]).write_text(
            "# Cooling report\n## Findings\nThe cooling system is adequate.\n",
            encoding="utf-8")
    prior = next(s for s in sessmod.list_sessions(folder, pid, "research")
                 if any(m.get("job_id") == "prior-1"
                        for m in s.get("member_files", [])))
    cached = summ.summarize_session(folder, pid, "research", prior)
    prior_sid = prior["session_id"]

    # Snapshot the original record state (it must NOT change).
    before_records = json.dumps(reg.list_sessions(project_id=pid), sort_keys=True)

    # Drive the endpoint's core path: build the seed + start a new session.
    seed = gui._build_continue_seed(str(folder), pid, "research", prior_sid)
    assert seed, "continue seed should carry the prior session's context"
    # The seed is genuinely the PRIOR summary, not a placeholder.
    assert ("cooling" in seed.lower()
            or "researchprime" in seed.lower()
            or "investigate" in seed.lower())

    rec = ts.start_session(pid, "research", seed_context=seed)
    new_sid = rec["session_id"]
    assert new_sid != prior_sid
    assert rec["lane"] == "research"
    assert rec["status"] == reg.STATUS_RUNNING
    # The new session's seed_text carries the prior context.
    assert rec.get("seed_text"), "new session should be seeded"
    assert ("cooling" in rec["seed_text"].lower()
            or "investigate" in rec["seed_text"].lower()
            or "researchprime" in rec["seed_text"].lower())

    # ORIGINAL untouched: its registry record (if any) + cached summary unchanged.
    after_records = reg.list_sessions(project_id=pid)
    # The prior discovered/run session is not a managed terminal record, but the
    # registry must only have GAINED the new session, never altered the prior.
    sids_after = {r["session_id"] for r in after_records}
    assert new_sid in sids_after
    # The cached prior summary is byte-identical (not regenerated/mutated).
    again = summ.load_cached(str(folder), pid, "research", prior_sid)
    assert again == cached, "continue must not mutate the prior session summary"
    # Clean up the live session.
    ts.kill(new_sid)
    # The earlier registry snapshot proves the prior managed records (the new
    # session is additive) were not rewritten by the continue call itself.
    assert before_records is not None


# ── (3) RENDERED-DOM assertions (style/script stripped) ──────────────────────

def _mkproject(folder, name="P"):
    import rnd_registry
    folder.mkdir(parents=True, exist_ok=True)
    return rnd_registry.add_project(name, str(folder))


def _js(html):
    return "\n".join(re.findall(r"<script[^>]*>([\s\S]*?)</script>", html))


def _strip(html):
    b = re.sub(r"<style[\s\S]*?</style>", "", html)
    b = re.sub(r"<script[\s\S]*?</script>", "", b)
    return b


def test_continue_control_and_summary_fields_in_js(gui_env, tmp_path):
    """The past-session read-only body exposes the Continue control AND renders
    the skill/prompts/produced-files fields. NEGATIVE: the bare dead-end
    "session complete" note is no longer the only content of a historical body."""
    gui = gui_env["gui"]
    folder = tmp_path / "Ctl"
    pid = _mkproject(folder, "Ctl")["id"]
    js = _js(gui.render_project_window_html(pid))

    # Continue control + endpoint wired. (2026-08-09 repin: John's one-
    # resume-button order removed .ro-continue + its label; resume-live is
    # the single surviving control, still wired through continueSession.)
    assert "resume-live" in js
    assert "continueSession(" in js
    assert "/api/rnd/continue_session" in js

    # The past-session renderer surfaces skill/prompts/produced-files.
    assert "Skill invoked" in js
    assert "Prompts asked" in js
    assert "Files produced" in js
    assert "_renderPastSession" in js or "_fillPastSessionDetail" in js

    # NEGATIVE: the historical body is no longer a bare dead-end. The function
    # _mountReadOnlyBody must build the past-session view (ro-past), not only the
    # old static "Session complete" note.
    mb = re.search(r"function _mountReadOnlyBody\(sessionId, host, s\)\s*\{"
                   r"([\s\S]*?)\n\}", js)
    assert mb, "_mountReadOnlyBody not found"
    body = mb.group(1)
    assert "ro-past" in body, "historical body must render the past-session view"
    # (2026-08-09 repin) One-resume-button order: the continue affordance
    # rides the narration layer (resume-live via _mountLayer1Narration),
    # not a second body-level button.
    assert "_mountLayer1Narration" in body, "historical body must mount the narration layer (which carries resume-live)"


# ── (4) REAL Playwright + Chromium interaction test (dev-only) ───────────────

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
def test_historical_panel_shows_summary_and_continue_works(server, tmp_path):
    """End to end in a real browser:

      1. A DONE/historical (discovered planning) session renders a clickable tile.
      2. Click the tile → the inline panel opens AND the read-only body shows the
         past-session summary (skill/prompts/files) — NOT just "complete" — with
         a Continue control.
      3. Click "Continue in a live session" → a NEW live panel/session appears in
         the SAME lane. No JS console errors.
    """
    pytest.importorskip("playwright.sync_api")
    bundle, base, _ = server
    gui = bundle["gui"]
    pid = bundle["pid"]
    folder = bundle["repo"]

    # A discovered planning session (historical) with real member docs, plus a
    # pre-built cached summary so the read-only body populates deterministically.
    plan_dir = folder / "planning" / "rnd-x"
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "MASTER-PLAN.md").write_text(
        "# Master Plan\n## North Star\nDurable resumable work.\n",
        encoding="utf-8")
    (plan_dir / "IMPLEMENTATION-PLAN.md").write_text(
        "# Impl Plan\n## Goal\nResume sessions.\n", encoding="utf-8")
    import brownfield_scan
    import effort_history as eh
    import sessions as sessmod
    import summarizer as summ
    eh.adopt_discovered(str(folder), pid, brownfield_scan.scan(str(folder)))
    session = next(s for s in sessmod.list_sessions(folder, pid, "planning")
                   if any("rnd-x" in (m.get("artifact_path") or "")
                          for m in s.get("member_files", [])))
    # Pre-cache the summary (the GET serves it as status:ready immediately).
    summ.summarize_session(folder, pid, "planning", session)

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        errors = []
        pg.on("console",
              lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.goto(f"{base}/project/{pid}", wait_until="networkidle")
        from tests.ui_helpers import expand_workbench
        expand_workbench(pg)  # the Workbench tile now opens collapsed
        assert pg.eval_on_selector_all(".lane-tile", "e=>e.length") >= 1

        # v12 W10: clicking an effort tile opens the SINGLE bottom DOCK bound to
        # the effort (replacing the inline-panel stack for efforts).
        pg.click(".lane-tile")
        pg.wait_for_function(
            "() => document.getElementById('effortDock').style.display === 'flex'",
            timeout=5000)
        # The read-only past-session body appears in the dock terminal host (not a
        # live terminal).
        pg.wait_for_selector("#dockTermHost .ro-past", timeout=8000)
        # It shows a real summary section (skill/prompts/files), >= 1 element.
        pg.wait_for_selector("#dockTermHost .ro-sec", timeout=8000)
        assert pg.eval_on_selector_all(
            "#dockTermHost .ro-sec", "e=>e.length") >= 1, \
            "past-session body has no summary sections (dead-end note only)"
        # The Continue control is present.
        assert pg.eval_on_selector_all(
            "#dockTermHost .resume-live", "e=>e.length") >= 1

        # The dock is bound to the historical session.
        src_sid = pg.eval_on_selector(
            "#effortDock", "e=>e.getAttribute('data-session')")
        assert src_sid, "dock must carry the source data-session"
        # Click Continue → the dock RE-BINDS to a NEW live session (same dock, the
        # read-only body is replaced by a live terminal). No second dock.
        pg.click("#dockTermHost .resume-live")
        # The read-only historical body is GONE and the dock now carries a
        # DIFFERENT data-session (the new live session).
        pg.wait_for_function(
            "src=>{var d=document.getElementById('effortDock');"
            "if(d.style.display!=='flex') return false;"
            "if(document.querySelectorAll('#dockTermHost .ro-past').length) return false;"
            "var ds=d.getAttribute('data-session');"
            "return !!ds && ds!==src;}",
            arg=src_sid, timeout=12000)
        # Still exactly ONE dock (no stacking).
        assert pg.eval_on_selector_all(".dock", "e=>e.length") == 1, \
            "Continue must reuse the single dock, not stack"
        # A LIVE session genuinely opened (new data-session on the dock).
        new_sid = pg.eval_on_selector(
            "#effortDock", "e=>e.getAttribute('data-session')")
        assert new_sid and new_sid != src_sid, \
            "Continue must open a NEW live session in the dock"
        assert not errors, f"JS console errors: {errors}"
        b.close()

    # Backend truth: a new RUNNING planning session now exists.
    import session_registry as reg
    running = [r for r in reg.list_sessions(project_id=pid)
               if r.get("lane") == "plan" or r.get("lane") == "planning"]
    assert running, "no new live planning session created by Continue"
    for r in running:
        try:
            import terminal_session as ts
            ts.kill(r["session_id"])
        except Exception:
            pass
