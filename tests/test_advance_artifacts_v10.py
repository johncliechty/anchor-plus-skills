"""v10 Wave 2 — Both-artifact handoff + advance routed through PASTE.

Every advance (research→plan and plan→build) now:
  - writes BOTH durable artifacts into the next stage's worktree: the structural
    ``HANDOFF.md`` (when a plan-set context applies) AND the reviewable
    ``NEXT-PROMPT.md`` (the ready-to-run prompt);
  - links the sessions (``parent_session_id`` / shared ``chain_id`` +
    ``record_stage_link``);
  - delivers the task prompt as a v10 **PENDING PASTE** (Wave 1) — held in the new
    PTY input UNSENT until the user presses Enter — on the ATTENDED click paths AND
    on the UNATTENDED reconcile-dead auto-advance (nothing auto-submitted).

Covers the Wave-2 Given/When/Then:
  (a) research→plan advance — both artifacts referencing the REAL doc paths, the
      planning record linked (parent + chain), pending_paste == the NEXT-PROMPT body;
  (b) plan→build finish — ONE linked build with both artifacts + pending paste,
      idempotent on parent_session_id;
  (c) reconcile-dead UNATTENDED — the build greets and holds the prompt PENDING
      (paste_flushed False until the first attach flushes it unsent).

Hermetic: ``ANCHOR_PTY_BACKEND=stub`` + the fake runner + a temp git repo + a tmp
data dir + tmp worktree base. NEVER binds ``:8777``; NEVER a worktree off the real
``C:\\dev\\Anchor`` repo; no network.
"""
import importlib
import re
import subprocess
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()


def _js(html):
    return "\n".join(re.findall(r"<script[^>]*>([\s\S]*?)</script>", html))

#: A simulated MODEL greet line — writing it onto the stub PTY echoes it into the
#: read buffer, pushing the greet-marker count past the echoed-seed base, which is
#: the "model actually greeted" signal the v10 pending-paste flush requires.
GREET_LINE = "✓ Skill loaded — what would you like to do?"


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
    """Tmp data dir + worktree base + stub PTY + fake runner + a temp git repo +
    a registered project. The full stack is reloaded against the isolated env so
    every worktree is off the TEMP repo (never C:\\dev\\Anchor)."""
    data = tmp_path / "data"
    data.mkdir()
    wbase = tmp_path / "wt-base"
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(wbase))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    monkeypatch.delenv("ANCHOR_TERMINAL_SEED", raising=False)

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


def _inject_greet(sid):
    import pty_manager
    pty_manager.write(sid, GREET_LINE)


def _add_research_doc(eh, repo, pid, rel="research/run-1/REPORT.md",
                      research_session_id=""):
    """Record a research effort whose artifact is a REAL committed report doc,
    tagged with ``research_session_id`` so research_set_for_session resolves it.

    NOTE (v11): this PRE-PERSISTS the research doc via ``eh.record_effort`` — so
    these tests are PROMPT-BUILDING-GIVEN-PERSISTED-DOCS coverage, NOT live-flow
    coverage. The live worktree-only flow (the actual advance, where the doc lives
    ONLY in the session's worktree until the advance persists it — the path the
    original bug broke) is covered by
    ``tests/test_advance_research_to_plan_live_v11.py`` +
    ``tests/test_handoff_unified_v11.py`` +
    ``anchor_healthcheck.check_rnd_v11_surface``. Do NOT make a pre-persisted test
    the SOLE coverage of an advance path (the v11 lesson)."""
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# Cooling report\n## Findings\nAdequate.\n", encoding="utf-8")
    jid = eh.discovered_job_id("research", rel)
    extra = {"source": eh.SOURCE_DISCOVERED, "kind": "report",
             "title": "Cooling report", "artifact_path": rel,
             "status": "imported"}
    if research_session_id:
        extra["session_id"] = research_session_id
    eh.record_effort(repo, pid, "research", jid, skill="researchPrime",
                     extra=extra)
    return rel


def _add_plan_session(eh, repo, pid, plan_dir="planning/rnd-x"):
    """Record a discovered planning session (one parent dir = one session) with a
    REAL MASTER+IMPL plan set committed into the repo so discovery finds it."""
    master_rel = f"{plan_dir}/MASTER-PLAN.md"
    impl_rel = f"{plan_dir}/IMPLEMENTATION-PLAN.md"
    for rel, body in [(master_rel, "# Master Plan\n"),
                      (impl_rel, "# Implementation Plan\n")]:
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    for i, (rel, title) in enumerate(
            [(master_rel, "Master Plan"), (impl_rel, "Implementation Plan")]):
        jid = eh.discovered_job_id("planning", rel)
        eh.record_effort(
            repo, pid, "planning", jid, skill="Crucible",
            extra={"source": eh.SOURCE_DISCOVERED, "kind": "plan-doc",
                   "title": title, "artifact_path": rel, "status": "imported",
                   "created_at": 2000.0 + i * 0.001})
    return {"master_rel": master_rel, "impl_rel": impl_rel}


# ════════════════════════════════════════════════════════════════════════════
# (UI) NON-Playwright rendered-DOM leg — the pending-paste affordance + advance
# control render POSITIVELY; the unsent guarantee is wired NEGATIVELY (no auto-run)
# ════════════════════════════════════════════════════════════════════════════

def test_render_pending_paste_affordance_and_advance_control(env):
    """Rendered-DOM leg (the v4 standard's non-Playwright half).

    POSITIVE: the rendered project window carries the v10 pending-paste affordance
    — the ``.pendpaste-hint`` CSS class, the ``_flashPendingPasteHint`` helper, and
    the advance control ("Advance to Planning →") — and the advance path CALLS the
    hint helper. NEGATIVE: the hint advertises the prompt is UNSENT ("review &
    press Enter", "nothing was submitted") and the advance JS does NOT auto-run the
    paste — it never POSTs a term_input(2) / writes a submitting newline for the new
    session as part of the advance (the prompt is delivered as a pending paste, not
    submitted on the user's behalf)."""
    gui, pid = env["gui"], env["pid"]
    html = gui.render_project_window_html(pid)
    js = _js(html)

    # POSITIVE — the affordance + advance control render.
    assert ".pendpaste-hint" in html, "pending-paste hint CSS class missing"
    assert "function _flashPendingPasteHint(" in js, "hint helper missing"
    assert "Advance to Planning" in js, "research advance control missing"
    assert "advbtn" in js
    # The advance path calls the hint helper (so the user is told it is unsent).
    assert "_flashPendingPasteHint(sid)" in js, \
        "advance must flash the pending-paste hint"

    # NEGATIVE — the hint advertises UNSENT, and the advance does NOT auto-submit.
    assert re.search(r"review\s*&\s*press\s*Enter", js, re.I), \
        "hint must tell the user to review & press Enter (unsent)"
    assert re.search(r"nothing was submitted", js, re.I), \
        "hint must state nothing was submitted on the user's behalf"
    # The advanceSession body must NOT write/submit the prompt itself — i.e. it has
    # no term_input call that would auto-run the paste for the new session. Isolate
    # the advanceSession function body and assert the auto-run wiring is absent.
    m = re.search(r"async function advanceSession\(([\s\S]*?)\n\}", js)
    assert m, "advanceSession not found in rendered JS"
    body = m.group(1)
    assert "term_input" not in body, \
        "advance must NOT auto-submit the prompt via term_input (it is a paste)"
    assert "_flashPendingPasteHint" in body, \
        "advance body must flash the unsent hint"


# ════════════════════════════════════════════════════════════════════════════
# build_next_stage_prompt — sources REAL doc paths per direction (honest)
# ════════════════════════════════════════════════════════════════════════════

def test_build_next_stage_prompt_plan_lists_research_docs(env):
    """For to_lane=planning the prompt names Crucible + the REAL research report
    path ("read these first, then plan") — no fabricated paths."""
    ts, eh, repo, pid, ho = (env["ts"], env["eh"], env["repo"], env["pid"],
                             env["handoff"])
    rsess = ts.start_session(pid, "research", backend="claude")
    rsid = rsess["session_id"]
    rel = _add_research_doc(eh, repo, pid, research_session_id=rsid)
    prompt = ho.build_next_stage_prompt(repo, pid, rsid, "planning")
    assert "Crucible" in prompt
    assert rel in prompt
    assert "plan" in prompt.lower()
    assert not prompt.endswith("\n"), "a reviewable prompt must not end in newline"
    ts.kill(rsid)


def test_build_next_stage_prompt_build_lists_plan_docs(env):
    """For to_lane=build the prompt names Foreman + the REAL plan doc paths."""
    ts, eh, repo, pid, ho = (env["ts"], env["eh"], env["repo"], env["pid"],
                             env["handoff"])
    plan = _add_plan_session(eh, repo, pid)
    psess = ts.start_session(pid, "planning", backend="claude")
    psid = psess["session_id"]
    prompt = ho.build_next_stage_prompt(repo, pid, psid, "build")
    assert "Foreman" in prompt
    assert plan["master_rel"] in prompt
    assert plan["impl_rel"] in prompt
    assert not prompt.endswith("\n")
    ts.kill(psid)


def test_build_next_stage_prompt_honest_minimal_when_no_docs(env):
    """With NO resolvable docs the prompt is minimal + skill-correct and references
    NO fabricated paths.

    v11.1 D2 update: the no-docs fallback no longer makes the false "the research
    report is in this worktree; see HANDOFF.md" claim (it misled the planner into
    looking for a report that was never written). It now HONESTLY states no written
    research artifact exists and instructs Crucible to CREATE the planning
    materials. So this asserts the NEW honest+actionable contract (NOT a weakening:
    the old "HANDOFF.md is the pointer" assertion encoded the misleading behavior
    v11.1 fixes)."""
    ts, repo, pid, ho = env["ts"], env["repo"], env["pid"], env["handoff"]
    rsess = ts.start_session(pid, "research", backend="claude")
    rsid = rsess["session_id"]
    prompt = ho.build_next_stage_prompt(repo, pid, rsid, "planning")
    assert "Crucible" in prompt
    # Honest + actionable: instruct the planner to CREATE the materials.
    import re as _re
    assert _re.search(r"create the", prompt, _re.I), prompt
    # No false "report is in this worktree" claim.
    assert "the research report is in this worktree" not in prompt
    # No fabricated doc path — there is no real research/run-*/ doc to name.
    assert ".md" not in prompt
    ts.kill(rsid)


def test_write_next_prompt_writes_into_worktree(env):
    """write_next_prompt drops NEXT-PROMPT.md into the worktree root containing the
    prompt body; traversal-safe; ok=True."""
    ts, repo, pid, ho = env["ts"], env["repo"], env["pid"], env["handoff"]
    sess = ts.start_session(pid, "planning", backend="claude")
    wt = sess["worktree_path"]
    out = ho.write_next_prompt(wt, "PLAN FROM THE RESEARCH")
    assert out["ok"] is True
    npf = Path(wt) / ho.NEXT_PROMPT_FILENAME
    assert npf.exists()
    assert "PLAN FROM THE RESEARCH" in npf.read_text(encoding="utf-8")
    ts.kill(sess["session_id"])


# ════════════════════════════════════════════════════════════════════════════
# (a) research → plan advance: both artifacts + linkage + pending paste
# ════════════════════════════════════════════════════════════════════════════

def test_advance_research_to_plan_writes_both_artifacts_and_pending_paste(env):
    """Driving the advance core path (the same calls /api/rnd/advance_session
    makes): the new planning worktree has HANDOFF.md (when a plan-set applies) +
    NEXT-PROMPT.md, the record is linked (parent + chain), and pending_paste equals
    the NEXT-PROMPT body (modulo the trailing-newline strip)."""
    ts, eh, reg, repo, pid, ho = (env["ts"], env["eh"], env["reg"], env["repo"],
                                  env["pid"], env["handoff"])
    rsess = ts.start_session(pid, "research", backend="claude")
    rsid = rsess["session_id"]
    rel = _add_research_doc(eh, repo, pid, research_session_id=rsid)

    # The reviewable prompt (the pending paste) + the planning session.
    prompt = ho.build_next_stage_prompt(repo, pid, rsid, "planning")
    assert rel in prompt
    plan_rec = ts.start_session(pid, "planning", seed_context="ctx",
                                paste_prompt=prompt, parent_session_id=rsid)
    psid = plan_rec["session_id"]
    new_wt = plan_rec["worktree_path"]
    ho.write_next_prompt(new_wt, prompt)
    ho.record_stage_link(repo, pid, rsid, psid, kind="research->plan")

    # NEXT-PROMPT.md written, referencing the REAL research doc path.
    npf = Path(new_wt) / ho.NEXT_PROMPT_FILENAME
    assert npf.exists()
    assert rel in npf.read_text(encoding="utf-8")

    # Linked: parent + shared chain.
    assert plan_rec["parent_session_id"] == rsid
    assert plan_rec["chain_id"] == reg.chain_for(rsid)

    # pending_paste == the prompt (newline-stripped); NOT yet flushed.
    rec = reg.get_session(psid)
    assert rec["pending_paste"] == prompt.rstrip("\r\n")
    assert rec["paste_flushed"] is False
    # Phase-1 seed (load+greet) still fired + auto-submits (ends in newline).
    assert rec["seeded"] is True
    assert rec["seed_text"].endswith("\n")

    # The stage edge was recorded (rescan-durable).
    links = ho.list_stage_links(repo, pid)
    assert any(l["from_session_id"] == rsid and l["to_session_id"] == psid
               and l["kind"] == "research->plan" for l in links)

    # After the greet, the pending paste flushes UNSENT (no trailing newline).
    import pty_manager
    _inject_greet(psid)
    ts.read_since(psid, 0)
    full = pty_manager.read_since(psid, 0)["text"]
    assert prompt.rstrip("\r\n") in full
    assert prompt.rstrip("\r\n") + "\n" not in full, "paste must NOT auto-submit"
    assert reg.get_session(psid)["paste_flushed"] is True

    ts.kill(psid)
    ts.kill(rsid)


def test_advance_endpoint_research_to_plan_end_to_end(env):
    """The HTTP /api/rnd/advance_session handler itself: a research source advances
    to a linked planning session with pending_paste + both artifacts written."""
    import json as _json
    import threading
    import time
    import urllib.request as _req
    ts, eh, reg, repo, pid, gui, ho = (
        env["ts"], env["eh"], env["reg"], env["repo"], env["pid"],
        env["gui"], env["handoff"])
    rsess = ts.start_session(pid, "research", backend="claude")
    rsid = rsess["session_id"]
    rel = _add_research_doc(eh, repo, pid, research_session_id=rsid)

    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    psid = None
    try:
        payload = _json.dumps({"project_id": pid, "source_session": rsid,
                               "to_lane": "planning"}).encode("utf-8")
        req = _req.Request(f"http://127.0.0.1:{port}/api/rnd/advance_session",
                           data=payload,
                           headers={"Content-Type": "application/json"},
                           method="POST")
        with _req.urlopen(req, timeout=20) as r:
            data = _json.loads(r.read().decode("utf-8"))
        assert data["ok"] is True
        rec = data["session"]
        psid = rec["session_id"]
        assert rec["lane"] == "planning"
        assert rec["parent_session_id"] == rsid
        # pending_paste set + referencing the real research doc path.
        full = reg.get_session(psid)
        assert full["pending_paste"], "advance must set a pending paste"
        assert rel in full["pending_paste"]
        assert full["paste_flushed"] is False
        # both artifacts written into the new worktree (NEXT-PROMPT.md always).
        npf = Path(rec["worktree_path"]) / ho.NEXT_PROMPT_FILENAME
        assert npf.exists()
        # stage edge recorded.
        assert any(l["from_session_id"] == rsid and l["to_session_id"] == psid
                   and l["kind"] == "research->plan"
                   for l in ho.list_stage_links(repo, pid))
    finally:
        if psid:
            try:
                ts.kill(psid)
            except Exception:
                pass
        ts.kill(rsid)
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


def _write_plan_docs_in_worktree(worktree_path, plan_dir="planning/rnd-x"):
    """What Crucible would author LIVE in the planning worktree (uncommitted to
    main): a MASTER + IMPL plan set. Returns the rel paths."""
    wt = Path(worktree_path)
    master = f"{plan_dir}/MASTER-PLAN.md"
    impl = f"{plan_dir}/IMPLEMENTATION-PLAN.md"
    for rel, body in [(master, "# Master Plan\nThe locked north star.\n"),
                      (impl, "# Implementation Plan\nWave-by-wave.\n")]:
        p = wt / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return {"master": master, "impl": impl}


# ════════════════════════════════════════════════════════════════════════════
# (b) plan → build finish: one linked build + both artifacts + pending; idempotent
# ════════════════════════════════════════════════════════════════════════════

def test_finish_to_build_persists_planning_docs_so_build_can_read_them(env):
    """FIX 2 (North-Star hole): /api/rnd/finish_to_build PERSISTS the planning
    session's freshly-authored (live-in-worktree, UNCOMMITTED-to-main) plan docs
    into the main project BEFORE the build advances — so the build worktree (off
    main HEAD) actually CONTAINS the paths NEXT-PROMPT.md/HANDOFF.md reference, and
    the doc is committed to the main project folder. The planning worktree is NOT
    reaped (non-destructive finish — the tile stays a reopenable record).
    """
    import json as _json
    import threading
    import time
    import urllib.request as _req
    ts, reg, repo, pid, gui, ho = (env["ts"], env["reg"], env["repo"], env["pid"],
                                   env["gui"], env["handoff"])

    plan_sess = ts.start_session(pid, "planning", backend="claude")
    psid = plan_sess["session_id"]
    plan_wt = plan_sess["worktree_path"]
    # Author the plan docs LIVE in the planning worktree — NOT in the main folder
    # and NOT committed to main. Pre-condition: discovery must NOT find them yet.
    docs = _write_plan_docs_in_worktree(plan_wt)
    assert ho.discover_recent_plan_set(repo, pid,
                                       source_session_id=psid) is None, \
        "pre-condition: plan set must be undiscoverable BEFORE the finish persists"
    impl_rel = docs["impl"]

    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    bsid = None
    try:
        payload = _json.dumps({"project_id": pid, "session": psid}).encode("utf-8")
        req = _req.Request(f"http://127.0.0.1:{port}/api/rnd/finish_to_build",
                           data=payload,
                           headers={"Content-Type": "application/json"},
                           method="POST")
        with _req.urlopen(req, timeout=30) as r:
            data = _json.loads(r.read().decode("utf-8"))
        assert data["ok"] is True
        ab = data.get("auto_build")
        assert ab, ("finish_to_build did not persist-then-advance: no build on "
                    "fresh planning docs (the North-Star hole)")
        bsid = ab["session_id"]
        assert ab["lane"] == "build"
        assert ab["parent_session_id"] == psid

        build_wt = Path(ab["worktree_path"])
        # FIX 2 — the build can actually READ the handoff doc: it is a real file in
        # the build worktree (which was created off main HEAD AFTER the persist).
        assert (build_wt / impl_rel).is_file(), \
            "build worktree lacks the impl plan doc (cat <buildwt>/<impl> fails)"
        assert (build_wt / docs["master"]).is_file()
        # And the doc was COMMITTED into the main project folder (it survives).
        assert (repo / impl_rel).is_file(), \
            "plan doc was not committed to the main project on finish"

        # The planning worktree was NOT reaped — the tile stays reopenable.
        prec = reg.get_session(psid)
        assert prec is not None, "planning record removed (must stay a finished tile)"
        assert prec["status"] == reg.STATUS_DONE
        assert prec.get("worktree_path") == plan_wt
        assert Path(plan_wt).is_dir(), \
            "planning worktree was reaped (finish must be non-destructive)"
    finally:
        if bsid:
            try:
                ts.kill(bsid)
            except Exception:
                pass
        ts.kill(psid)
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


def test_finish_to_build_opens_linked_build_with_both_artifacts_and_pending(env):
    """auto_advance_planning_to_build (the finish→build core) opens ONE linked
    build with HANDOFF.md + NEXT-PROMPT.md and the build prompt PENDING (unsent),
    and is idempotent on parent_session_id."""
    ts, eh, reg, repo, pid, ho = (env["ts"], env["eh"], env["reg"], env["repo"],
                                  env["pid"], env["handoff"])
    plan = _add_plan_session(eh, repo, pid)
    psess = ts.start_session(pid, "planning", backend="claude")
    psid = psess["session_id"]
    pre = ts.capture_plan_set(pid, psid)
    assert pre is not None
    ts.kill(psid)

    build = ts.auto_advance_planning_to_build(pid, psid, plan_set=pre)
    assert build is not None
    bsid = build["session_id"]
    assert build["parent_session_id"] == psid
    assert build["chain_id"] == psess["chain_id"]
    bwt = Path(build["worktree_path"])

    # BOTH artifacts in the build worktree, referencing the REAL plan docs.
    assert (bwt / ho.HANDOFF_FILENAME).exists()
    npf = bwt / ho.NEXT_PROMPT_FILENAME
    assert npf.exists()
    np_text = npf.read_text(encoding="utf-8")
    assert plan["master_rel"] in np_text
    assert plan["impl_rel"] in np_text

    # The build prompt is PENDING — held unsent (NOT auto-submitted).
    brec = reg.get_session(bsid)
    assert brec["pending_paste"], "the build prompt must be pending"
    assert plan["impl_rel"] in brec["pending_paste"]
    assert brec["paste_flushed"] is False
    assert "Foreman" in brec["pending_paste"]

    # IDEMPOTENT — a second advance does not duplicate.
    again = ts.auto_advance_planning_to_build(pid, psid, plan_set=pre)
    assert again is None
    builds = [s for s in reg.list_sessions(project_id=pid)
              if s.get("lane") == "build"]
    assert len(builds) == 1

    ts.kill(bsid)


# ════════════════════════════════════════════════════════════════════════════
# (c) reconcile-dead UNATTENDED: build greets + holds the prompt PENDING
# ════════════════════════════════════════════════════════════════════════════

def test_reconcile_dead_unattended_holds_prompt_pending(env):
    """The UNATTENDED reconcile-dead auto-advance: the build greets and holds the
    prompt PENDING (paste_flushed False, nothing auto-submitted) until the first
    attach flushes it UNSENT."""
    ts, eh, reg, repo, pid = (env["ts"], env["eh"], env["reg"], env["repo"],
                              env["pid"])
    _add_plan_session(eh, repo, pid)
    psess = ts.start_session(pid, "planning", backend="claude")
    psid = psess["session_id"]

    # No live ids → the planning session is stale → reconcile marks it DONE → the
    # UNATTENDED auto-advance fires.
    out = ts.reconcile_and_advance(live_session_ids=[])
    assert psid in out["reconcile"]["marked"]
    assert len(out["auto_builds"]) == 1
    build = out["auto_builds"][0]
    bsid = build["session_id"]
    assert build["parent_session_id"] == psid

    # The prompt is held PENDING — NOTHING auto-submitted before anyone attaches.
    brec = reg.get_session(bsid)
    assert brec["pending_paste"], "the build prompt must be held pending"
    assert brec["paste_flushed"] is False
    import pty_manager
    pre_buf = pty_manager.read_since(bsid, 0)["text"]
    assert brec["pending_paste"] not in pre_buf, \
        "nothing should be pasted before the greet/attach (unattended)"

    # The FIRST attach (after a greet) flushes the paste UNSENT.
    _inject_greet(bsid)
    res = ts.attach(bsid)
    assert res["ok"] is True
    full = pty_manager.read_since(bsid, 0)["text"]
    body = reg.get_session(bsid)
    # pending cleared + flushed; the prompt landed without a trailing newline.
    assert body["paste_flushed"] is True
    assert body["pending_paste"] == ""
    prompt = brec["pending_paste"]
    assert prompt in full
    assert prompt + "\n" not in full, "unattended build prompt must NOT auto-submit"

    ts.kill(bsid)
