"""Wave 6a & 6b (2026-10-15): Proactive Cave of Wonders, Two-Horizon Schedule, Desk Ad-Hoc AI Cockpit,
1-click Mark Done, conversational plan drift, and MBA Teaching AI Steward status-bar & artifact-job fixes."""
import json
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import high_seat_page as hsp  # noqa: E402
from steward_cockpit import campaign_acts as acts  # noqa: E402
from steward_cockpit import campaign_parts as parts  # noqa: E402
from steward_cockpit import steward_campaign as sc  # noqa: E402
import test_high_seat_page_2026_09_26 as base  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def test_status_bar_no_sentence_clipping_and_artifact_job_nouns(tmp_path):
    # 1. _compact_line preserves sentences past the first period up to max_len
    long_doing = "Running einstein — Lecture 4 deck. 3 files changed (+410 -12 lines)."
    assert sc._compact_line(long_doing, 180) == long_doing

    # 2. _brief_title extracts the real objective when a brief starts with FULL BRIEF FILE
    compacted = (
        "FULL BRIEF FILE (read first): .ecgberht/code-jobs/cj-123/brief.md\n"
        "SUMMARY: Build Quiz 1 Draft 4 paired JSON and Markdown study bank\n"
    )
    assert sc._brief_title(compacted) == "Build Quiz 1 Draft 4 paired JSON and Markdown study bank"

    # 3. job_noun and is_artifact_job retire 'code job' for named skills and document deliverables
    skill_job = {"skill": "einstein", "brief": "Generate Lecture 4 slides", "outputs": ["slides.pptx"]}
    doc_job = {"skill": "", "brief": "Draft trust transfer memo", "outputs": ["memo.docx", "notes.md"]}
    code_job = {"skill": "", "brief": "Refactor parser", "outputs": ["parser.py"]}
    assert sc.is_artifact_job(skill_job) is True
    assert sc.job_noun(skill_job) == "einstein job"
    assert sc.is_artifact_job(doc_job) is True
    assert sc.job_noun(doc_job) == "deliverable job"
    assert sc.is_artifact_job(code_job) is False
    assert sc.job_noun(code_job) == "code job"

    # 4. steward_review.mjs MAX_DIFF raised to 800,000
    rev_src = (ROOT / "tools" / "steward_review.mjs").read_text(encoding="utf-8")
    assert "const MAX_DIFF = 800_000;" in rev_src


def test_conversational_plan_drift_marker_detected_by_plan_drift(tmp_path):
    (tmp_path / "ECGBERHT.md").write_text("# Face\n\n## North Star\nGoal.\n", encoding="utf-8")
    (tmp_path / "roadmap.json").write_text(
        json.dumps({"roadmap_projection": [{"id": "s1", "name": "Step 1", "status": "active"}]}),
        encoding="utf-8",
    )
    assert sc.plan_drift(str(tmp_path))["drift"] is False
    marker = tmp_path / ".ecgberht" / "conversational-plan-drift.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps({"drift": True, "at": 1700000000.0, "reason": "John discussed a plan change in chat"}),
        encoding="utf-8",
    )
    d = sc.plan_drift(str(tmp_path))
    assert d["drift"] is True
    assert "John discussed a plan change" in d["reason"]
    assert "PLAN DRIFT:" in sc.plan_drift_suffix(str(tmp_path))


def test_campaign_parts_filters_human_wait_none(tmp_path):
    proj = tmp_path / "Trusts"
    proj.mkdir()
    (proj / "ECGBERHT.md").write_text("# Trusts\n", encoding="utf-8")
    (proj / "roadmap.json").write_text(
        json.dumps({"roadmap_projection": [{"id": "s1", "name": "Confirm Merrill template", "status": "active", "due": "2026-10-17"}]}),
        encoding="utf-8",
    )
    (proj / "strip.json").write_text(
        json.dumps({"current_step_id": "s1", "human_wait": "none", "next_recommended": "Confirm Merrill template"}),
        encoding="utf-8",
    )
    lookup = lambda pid: {"id": "p-trusts", "name": "Family Trusts", "folder_path": str(proj)} if pid == "p-trusts" else None
    res = parts.resolve_ref("project:p-trusts", lookup=lookup)
    assert "waiting on you: none" not in str(res.get("state") or "").lower()


def test_wave6b_proactive_triage_two_horizon_schedule_and_desk_cockpit():
    ctx = base._ctx(campaign=True)
    ctx["desk_pid"] = "desk-123"
    ctx["desk"] = {
        "waits": 0,
        "small": {"light": "gray", "why": "idle", "items": [{"id": "i1", "text": "Admin item", "status": "open"}]},
        "cockpits": [{"name": "Tax prep", "dir": "Tax prep", "light": "gray", "why": "idle", "seat": ""}],
    }
    html = hsp.render_high_seat_html(ctx)
    # 1. Proactive Triage Strip at top of board before #camp
    assert 'id="shTriage"' in html
    assert html.index('id="shTriage"') < html.index('id="camp"')
    assert "Proactive Chief-of-Staff Triage" in html
    assert "Desktop (Ad-Hoc AI Cockpit)" in html

    # 2. Two-Horizon Schedule (#thisWeekBoard + compact #ruler + horizon tabs)
    assert 'id="thisWeekBoard"' in html
    assert 'data-hz="both"' in html and 'data-hz="week"' in html and 'data-hz="ruler"' in html
    assert 'class="ruler compact-ruler" id="ruler"' in html

    # 3. 1-click Mark Done and Ad-Hoc AI Cockpit controls
    assert 'data-mark-done="1"' in html
    assert "Ad-Hoc AI Cockpit" in html
    assert "mark_done" in acts.ACTS and "reopen_step" in acts.ACTS and "schedule_date" in acts.ACTS


def test_campaign_acts_mark_done_reopen_and_schedule_date(tmp_path):
    camp = tmp_path / "Campaign"
    camp.mkdir()
    proj = tmp_path / "Trusts"
    proj.mkdir()
    (proj / "ECGBERHT.md").write_text("# Family Trusts\n\n## North Star\nTrust transfers.\n", encoding="utf-8")
    (proj / "roadmap.json").write_text(
        json.dumps(
            {
                "roadmap_events": [],
                "roadmap_projection": [
                    {"id": "merrill-template", "name": "Confirm Merrill LP transfer template", "status": "active", "due": "2026-10-17"},
                    {"id": "brothers-transfers", "name": "Execute brothers holding co transfers", "status": "pending", "due": "2026-10-22"},
                ],
            }
        ),
        encoding="utf-8",
    )
    (proj / "strip.json").write_text(
        json.dumps({"current_step_id": "merrill-template", "active_effort": "Confirm Merrill LP transfer template"}),
        encoding="utf-8",
    )
    # 1. mark_done closes merrill-template and advances strip.json to brothers-transfers
    res = acts.mark_done(str(camp), {"target_dir": str(proj), "step_id": "merrill-template", "note": "Confirmed with Stanford"})
    assert res["ok"] is True
    assert res["closed_step"] == "merrill-template"
    rm = json.loads((proj / "roadmap.json").read_text(encoding="utf-8"))
    by_id = {s["id"]: s for s in rm["roadmap_projection"]}
    assert by_id["merrill-template"]["status"] == "done"
    st = json.loads((proj / "strip.json").read_text(encoding="utf-8"))
    assert st["current_step_id"] == "brothers-transfers"

    # 2. schedule_date updates due date on brothers-transfers
    res_sched = acts.schedule_date(str(camp), {"target_dir": str(proj), "step_id": "brothers-transfers", "due": "2026-10-25"})
    assert res_sched["ok"] is True
    rm2 = json.loads((proj / "roadmap.json").read_text(encoding="utf-8"))
    by_id2 = {s["id"]: s for s in rm2["roadmap_projection"]}
    assert by_id2["brothers-transfers"]["due"] == "2026-10-25"

    # 3. reopen_step reopens merrill-template
    res_reopen = acts.reopen_step(str(camp), {"target_dir": str(proj), "step_id": "merrill-template"})
    assert res_reopen["ok"] is True
    rm3 = json.loads((proj / "roadmap.json").read_text(encoding="utf-8"))
    by_id3 = {s["id"]: s for s in rm3["roadmap_projection"]}
    assert by_id3["merrill-template"]["status"] == "active"


def test_working_status_always_green_across_cockpit_and_cave(tmp_path):
    """John (2026-10-15): whenever a cockpit/effort is working, its light must be green across AI Cockpit,
    Cave of Wonders, App Header Strip, and Star Chart — never yellow/orange."""
    import anchor_gui as ag
    import campaign_page as cp
    from steward_cockpit import steward_engine as se
    from types import SimpleNamespace

    # 1. Engine.light returns green when busy, queued, running_code_jobs, or state=='working', even with open_question or needs_you
    eng = SimpleNamespace(
        dir=str(tmp_path),
        broken=False,
        busy=True,
        queue=[],
        last_output=1e12,
        last_say=0,
        woke_at=0,
        open_question="Approve draft?",
        alive=lambda: True,
        _question_contexts=lambda att: [],
    )
    assert se.Engine.light(eng, {"state": "needs_you"}) == "green"

    # 2. _light_words in anchor_gui returns green when working_here or state == 'working', even if needs_you is present
    proj = tmp_path / "WorkProj"
    (proj / ".ecgberht").mkdir(parents=True)
    (proj / ".ecgberht" / "attention.json").write_text(json.dumps({"state": "working", "reason": "Running Crucible round 2"}), encoding="utf-8")
    lw = ag._light_words(str(proj), {"needs_you": "Old review note"}, working_here=False, with_engine=False)
    assert lw["light"] == "green" and lw["word"] == "working"

    # 3. initiative_light and _part_light return 'working' ahead of 'needs' when pid is in working set
    init = {"needs": ["approve"], "parts": [{"pid": "p1", "status": "active", "needs_you": "approve"}]}
    assert hsp.initiative_light(init, working={"p1"}) == "working"
    assert cp._part_light({"pid": "p1", "needs_you": "approve"}, working={"p1"}) == "working"

    # 4. JS stateColor and AnchorCockpitFeedback.color prioritize green when working
    shared_js = (ROOT / "steward_cockpit" / "static" / "shared.js").read_text(encoding="utf-8")
    assert 'st.light === "red" ? "red" : (working || st.light === "green") ? "green" : needsHuman ? "orange" : "quiet"' in shared_js
    fb_js = (ROOT / "static" / "cockpit-feedback.js").read_text(encoding="utf-8")
    assert "light === 'red' ? 'red' : light === 'green' ? 'green' : ready ? 'orange' : 'gray'" in fb_js

