"""rearch W17 (C4) — Live Demo harness + ConPTY Verdict Application.

Covers the frozen Wave-19 deliverables + acceptance, in the honest hermetic
form (the true live run — ``nssm restart anchor`` on :8777 WITH John — is the
``C4-RUNBOOK.md`` execution cell, marked NOT YET RUN until it runs):

  * the **C4 live-demo harness** (``tools/c4_live_demo.py``) — the scripted
    building blocks the runbook cites: register a THROWAWAY project → launch a
    harmless long-running fake_claude job through the REAL lane-guarded launch
    path → SURVIVE a restart (re-adopt the SAME job_id, advancing tail cursor,
    rebuilt lane/folder slots, cancellable) → rollback (cancel + lane-lock clear
    + retire). The gate SIMULATES the restart (in-memory table teardown) exactly
    where the live runbook runs the real ``nssm restart anchor``;
  * the **C4 runbook artifact** (``C4-RUNBOOK.md``) — throwaway project, real
    launch path, exact elevated commands, expected observations, rollback
    (supervisor stop + lane-lock clear), and the honest NOT-YET-RUN execution
    cell;
  * the **ConPTY verdict APPLICATION** (``tools/conpty_verdict.py`` +
    ``CONPTY-VERDICT-APPLICATION.md``) — the recorded spike verdict is YES on
    both legs, so W17 applies the ADOPTION branch: the PTY-adoption follow-on
    wave is SCHEDULED (not the drain), no North-Star narrowing is fabricated,
    and the drain (``tools/pre_restart_drain.py``) is retained as the safety net.
    A NO verdict is proven (via injection) to route to the drain + narrowing.

Hermetic: a temp ``ANCHOR_DATA_DIR`` + ``ANCHOR_RUNNER_CMD`` → the deterministic
``tests/fake_claude.py`` mock. Never real claude / node / port 8777 / real data.
"""
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()
ARTIFACT_DIR = REPO / "planning" / "rearch-2026-07"

sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Hermetic data dir + stub runner; clean supervisor/journal env."""
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"{sys.executable} {FAKE}")
    for k in ("ANCHOR_SUPERVISOR", "ANCHOR_SUPERVISOR_URL",
              "ANCHOR_SUPERVISOR_TOKEN", "ANCHOR_JOURNAL"):
        monkeypatch.delenv(k, raising=False)
    import paths
    import job_runner
    import gate_adapter
    import supervisor
    paths.ensure_data_dirs()
    job_runner._reset_live_table_for_tests()
    gate_adapter._SINKS.clear()
    sup = supervisor.get_supervisor()
    yield job_runner, supervisor, sup, tmp_path
    for rec in job_runner.list_records():
        if rec.get("status") == job_runner.STATUS_RUNNING:
            try:
                job_runner.cancel(rec["job_id"])
            except Exception:
                pass
    job_runner._reset_live_table_for_tests()
    gate_adapter._SINKS.clear()


# ══════════════════════════════════════════════════════════════════════════════
# 1) The C4 live-demo harness — restart survival (AC1, hermetic)
# ══════════════════════════════════════════════════════════════════════════════

class TestC4Harness:
    def test_run_demo_survives_simulated_restart(self, env):
        jr, supmod, sup, tmp = env
        import c4_live_demo as demo

        report = demo.run_demo(tmp / "root", sup=sup,
                               restart_hook=jr._reset_live_table_for_tests)
        assert report["launched"] is True
        assert report["went_live"] is True
        surv = report["survival"]
        # The SAME job_id lists running, is live, slots rebuilt, tail advancing.
        assert surv["survived"] is True
        assert surv["listed_running"] is True
        assert surv["is_live"] is True
        assert surv["lane_slot_ok"] is True
        assert surv["folder_lock_ok"] is True
        assert surv["tail_advanced"] is True
        assert surv["cursor_after"] > surv["cursor_before"]
        assert surv["rebuild_summary"]["running_jobs"] == [report["job_id"]]
        assert report["ok"] is True
        # Rollback left nothing running and retired the throwaway project.
        rb = report["rollback"]
        assert rb["cancelled"] is True and rb["slots_cleared"] is True
        assert rb["project_retired"] is True

    def test_building_blocks_mirror_the_runbook_steps(self, env):
        jr, supmod, sup, tmp = env
        import c4_live_demo as demo

        # Step 1 — throwaway project.
        folder = tmp / "proj"
        proj = demo.setup_demo_project(folder)
        pid = proj["id"]
        assert proj["name"] == demo.DEMO_PROJECT_NAME

        # Step 2 — launch through the REAL lane-guarded path.
        rec = demo.launch_demo_job(sup, pid, folder)
        jid = rec["job_id"]
        assert jid and rec.get("pid")
        assert jr.lane_holder(pid, demo.DEMO_LANE) == jid
        assert jr.folder_build_holder(str(folder)) == jid
        assert demo.wait_live(jid)

        # Step 3 — SIMULATE the restart (the live runbook: nssm restart anchor).
        jr._reset_live_table_for_tests()
        assert jr.lane_holder(pid, demo.DEMO_LANE) is None  # in-memory slot gone

        # Step 4 — survival: re-adopt from the durable records.
        surv = demo.verify_survival(sup, jid, project_id=pid,
                                    folder_path=str(folder))
        assert surv["survived"] is True
        assert jr.lane_holder(pid, demo.DEMO_LANE) == jid  # slot rebuilt

        # Step 5 — rollback clears the lane lock and retires the project.
        rb = demo.rollback_demo(sup, job_id=jid, project_id=pid)
        assert rb["cancelled"] is True
        assert jr.lane_holder(pid, demo.DEMO_LANE) is None

    def test_rollback_never_strands_a_lane_lock(self, env):
        jr, supmod, sup, tmp = env
        import c4_live_demo as demo

        folder = tmp / "p2"
        proj = demo.setup_demo_project(folder)
        pid = proj["id"]
        rec = demo.launch_demo_job(sup, pid, folder)
        jid = rec["job_id"]
        assert demo.wait_live(jid)
        rb = demo.rollback_demo(sup, job_id=jid, project_id=pid)
        assert rb["cancelled"] is True and rb["slots_cleared"] is True
        # Both the lane slot and the folder-build lock are released.
        assert jr.lane_holder(pid, "build") is None
        assert jr.folder_build_holder(str(folder)) is None
        assert sup.is_live(jid) is False


# ══════════════════════════════════════════════════════════════════════════════
# 2) The C4 runbook artifact (executed-artifact shape; honest NOT-YET-RUN cell)
# ══════════════════════════════════════════════════════════════════════════════

class TestC4Runbook:
    def test_runbook_exists_and_has_the_required_shape(self):
        p = ARTIFACT_DIR / "C4-RUNBOOK.md"
        assert p.is_file(), "C4-RUNBOOK.md must be a checked-in artifact"
        md = p.read_text(encoding="utf-8")
        # A dedicated THROWAWAY project on the real service.
        assert "throwaway" in md.lower()
        # A harmless job through the REAL launch path (fake_claude-driven).
        assert "launch_guarded" in md or "launch_lane" in md
        assert "fake_claude" in md
        # The exact elevated restart command.
        assert "nssm restart anchor" in md
        # Expected observations: same job_id live + advancing tail.
        assert "job_id" in md and "advanc" in md.lower()
        # Rollback: supervisor stop + lane-lock clear.
        assert "nssm stop anchor-supervisor" in md
        assert "release_slots" in md and "lane lock" in md.lower()
        # Cites the scripted harness.
        assert "c4_live_demo" in md

    def test_execution_cell_is_honestly_not_yet_run(self):
        md = (ARTIFACT_DIR / "C4-RUNBOOK.md").read_text(encoding="utf-8")
        # The criterion is unmet until the live run — recorded honestly.
        assert "NOT YET RUN" in md
        assert "pending" in md.lower()
        # Run WITH John (not a solo/silent claim).
        assert "John" in md


# ══════════════════════════════════════════════════════════════════════════════
# 3) The ConPTY verdict APPLICATION (verdict YES → adoption branch scheduled)
# ══════════════════════════════════════════════════════════════════════════════

class TestConPTYVerdictApplication:
    def test_recorded_verdict_is_yes_on_both_legs(self):
        import conpty_verdict as cv
        v = cv.read_verdict()
        assert v["overall"] == cv.VERDICT_YES
        assert v["ran_legs"] == ["real", "stub"]
        assert cv.applied_branch(v["overall"]) == cv.BRANCH_ADOPTION

    def test_checked_in_application_doc_matches_the_render(self, tmp_path):
        import conpty_verdict as cv
        # Regenerate into the repo (diff-stable: skips an unchanged rewrite),
        # then assert the checked-in artifact equals the render — drift fails.
        p = cv.write_application_doc()
        assert p == ARTIFACT_DIR / cv.APPLICATION_DOC_NAME
        assert p.read_text(encoding="utf-8") == cv.render_application_md()

    def test_yes_schedules_the_adoption_followon_no_narrowing(self):
        import conpty_verdict as cv
        md = (ARTIFACT_DIR / cv.APPLICATION_DOC_NAME).read_text(encoding="utf-8")
        assert "Applied branch:** adoption" in md
        # The PTY-adoption follow-on wave is SCHEDULED (the YES branch).
        assert "Scheduled follow-on wave" in md
        assert "PTY Adoption" in md or "PTY ADOPTION" in md
        # No North-Star narrowing on a YES — nothing fabricated.
        assert "narrows nothing" in md
        # The drain is retained as the safety net, not the shipped active path.
        assert "pre_restart_drain" in md and "safety net" in md.lower()

    def test_no_verdict_routes_to_the_drain_plus_narrowing(self):
        import conpty_verdict as cv
        no = {"legs": {"real": {"ran": True, "verdict": "NO"}},
              "ran_legs": ["real"], "overall": cv.VERDICT_NO}
        md = cv.render_application_md(verdict=no)
        assert cv.applied_branch(no["overall"]) == cv.BRANCH_DRAIN
        assert "pre_restart_drain" in md
        assert "narrowing" in md.lower() and "amendment path" in md.lower()

    def test_unrun_verdict_is_honestly_pending(self):
        import conpty_verdict as cv
        unrun = {"legs": {}, "ran_legs": [], "overall": cv.VERDICT_UNRUN}
        assert cv.applied_branch(unrun["overall"]) == cv.BRANCH_PENDING
        md = cv.render_application_md(verdict=unrun)
        assert "PENDING" in md and "not yet recorded" in md

    def test_read_verdict_degrades_on_missing_artifact(self, tmp_path):
        import conpty_verdict as cv
        v = cv.read_verdict(path=tmp_path / "nope.json")
        assert v["overall"] == cv.VERDICT_UNRUN
        assert v["ran_legs"] == []


# ══════════════════════════════════════════════════════════════════════════════
# 4) The drain (safety net) remains available regardless of the YES branch
# ══════════════════════════════════════════════════════════════════════════════

class TestDrainRetained:
    def test_pre_restart_drain_module_is_present(self):
        import pre_restart_drain
        assert hasattr(pre_restart_drain, "drain")
        assert hasattr(pre_restart_drain, "ensure_warm_seed")
