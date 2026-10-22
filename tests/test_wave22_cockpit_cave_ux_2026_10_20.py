"""Wave 22 (2026-10-20): Cockpit Approval Bar, Instant Deliverables Move on Done,
Live Milestone ETA / Step Name Sanitization, and Cave of Wonders Tile Done / Move / Fast Steward."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import high_seat_page as hsp  # noqa: E402
from steward_cockpit import campaign_acts as acts  # noqa: E402
from steward_cockpit import campaign_say as say  # noqa: E402
from steward_cockpit import steward_campaign as sc  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def test_issue1_cockpit_single_approval_bar_no_phantom_pending_and_clickable_links():
    """1. Only the top approval bar remains (no duplicate .right-approval-flag),
    hb.next_recommended does not trigger a phantom approval alert when human_wait is 'none',
    and the approval bar renders clickable deliverable links + structured options."""
    shared_js = (ROOT / "steward_cockpit" / "static" / "shared.js").read_text(encoding="utf-8")

    # Duplicate right-rail flag removed from JS
    assert "staleRightFlag.remove()" in shared_js

    # hb.next_recommended no longer triggers rawNeedsApproval when human_wait is "none"
    assert "const rawNeedsApproval = Boolean((q && q.question) || cleanWait || reviewItems.length > 0 || hasStepWait);" in shared_js
    assert "_approvalResolvedSig" in shared_js

    # Approval bar renders clickable deliverable links
    assert "approvalLinkedItems" in shared_js
    assert "ard-item-title" in shared_js


def test_issue2_deliverables_move_immediately_from_for_review_to_all_deliverables_on_done(tmp_path):
    """2. Clicking Done on an item in For Review immediately moves it out of For Review (is_current=False)
    and into All Deliverables with reviewed_done=True, without promoting older deliverables into For Review."""
    (tmp_path / "roadmap.json").write_text(
        json.dumps(
            {
                "roadmap_projection": [
                    {"id": "step-1", "name": "Draft Chapter 1", "status": "done"},
                    {"id": "step-2", "name": "Draft Chapter 2", "status": "waiting", "waiting_on": "John review"},
                ]
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "OLD-NOTES.md").write_text("# Old Notes\n", encoding="utf-8")
    (tmp_path / "CHAPTER-2-FINAL.md").write_text("# Chapter 2 Final\n", encoding="utf-8")
    (tmp_path / "DELIVERABLES.md").write_text(
        "# Deliverables\n\n"
        "| What | Where | Date | Step |\n"
        "| --- | --- | --- | --- |\n"
        "| Old Notes | `OLD-NOTES.md` | 2026-10-18 | step-1 |\n"
        "| FOR REVIEW: Chapter 2 Final | `CHAPTER-2-FINAL.md` | 2026-10-20 | step-2 |\n",
        encoding="utf-8",
    )

    before = sc.read_deliverables(str(tmp_path))["items"]
    by_path = {d["path"]: d for d in before}
    assert by_path["CHAPTER-2-FINAL.md"]["is_current"] is True
    assert by_path["OLD-NOTES.md"]["is_current"] is False

    # Mark CHAPTER-2-FINAL.md Done
    res = sc.dismiss_deliverable(str(tmp_path), "CHAPTER-2-FINAL.md")
    assert res["ok"] is True

    after = sc.read_deliverables(str(tmp_path))["items"]
    by_path_after = {d["path"]: d for d in after}
    # Moved out of For Review, kept in All Deliverables with reviewed_done=True
    assert "CHAPTER-2-FINAL.md" in by_path_after
    assert by_path_after["CHAPTER-2-FINAL.md"]["is_current"] is False
    assert by_path_after["CHAPTER-2-FINAL.md"]["reviewed_done"] is True
    # Older item is NOT promoted into For Review when the designated review item is marked Done!
    assert by_path_after["OLD-NOTES.md"]["is_current"] is False


def test_issue3_sync_steward_projections_sanitizes_overwritten_step_names_and_stale_clock_etas(tmp_path):
    """3. sync_steward_projections repairs step names overwritten with long 'Ready for Review: ...' status prose
    (like Step 19 in Book 1), and shared.js suppresses stale historical clock ETAs ('about 12:18') when idle."""
    (tmp_path / "ECGBERHT.md").write_text(
        "# Book 1\n\n## Roadmap\n\n- [x] **step-19** — Full-Manuscript Integration & Continuity Pass\n",
        encoding="utf-8",
    )
    (tmp_path / "roadmap.json").write_text(
        json.dumps(
            {
                "roadmap_projection": [
                    {
                        "id": "step-19",
                        "name": "Ready for Review: Full-manuscript integration pass complete across all 24 chapters with continuity fixes",
                        "status": "waiting",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "strip.json").write_text(
        json.dumps(
            {
                "current_step_id": "step-19",
                "active_effort": "Ready for Review: Full-manuscript integration pass complete across all 24 chapters with continuity fixes",
            }
        ),
        encoding="utf-8",
    )
    res = sc.sync_steward_projections(str(tmp_path))
    assert res["ok"] is True
    rm = json.loads((tmp_path / "roadmap.json").read_text(encoding="utf-8"))
    step19 = rm["roadmap_projection"][0]
    assert not step19["name"].lower().startswith("ready for review:")
    assert "Full-Manuscript Integration" in step19["name"]

    shared_js = (ROOT / "steward_cockpit" / "static" / "shared.js").read_text(encoding="utf-8")
    assert "(!isRunningNow && /\\b(?:about|around|by|at)\\s+\\d{1,2}:\\d{2}\\b/i.test(str))" in shared_js


def test_issue4_cave_tile_done_unseats_off_board_and_fast_steward_handles_conversational_commands(tmp_path):
    """4. Clicking Done on a seated Cave of Wonders tile removes it from Active/On deck (with Undo),
    every seated tile renders 1-click tier move buttons (On deck / Active), and fast_steward_command
    executes conversational archive/elevate/move-down/create-new-one commands in <50ms."""
    camp = tmp_path / "Campaign"
    camp.mkdir()
    proj_dir = tmp_path / "Book1"
    proj_dir.mkdir()
    (proj_dir / "roadmap.json").write_text(
        json.dumps(
            {
                "roadmap_events": [],
                "roadmap_projection": [
                    {"id": "step-1", "name": "Polish Chapter 1", "status": "active"},
                ],
            }
        ),
        encoding="utf-8",
    )
    (camp / "roadmap.json").write_text(
        json.dumps(
            {
                "roadmap_events": [],
                "roadmap_projection": [
                    {
                        "id": "writing",
                        "name": "Artificial Magi",
                        "status": "active",
                        "tier": 1,
                        "navigation": {"path": ["writing"], "groups": [{"id": "writing", "label": "Artificial Magi", "order": 0, "parent_id": None}]},
                    },
                    {
                        "id": "book-1",
                        "name": "Book 1 Cockpit",
                        "status": "active",
                        "seat": "active",
                        "seat_order": 0,
                        "effort_dir": str(proj_dir),
                        "navigation": {"path": ["writing"]},
                    },
                    {
                        "id": "book-2",
                        "name": "Book 2 Notes",
                        "status": "planned",
                        "seat": "deck",
                        "seat_order": 0,
                        "navigation": {"path": ["writing"]},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    # Clicking Done on seated tile 'book-1' unseats it off the Active board AND marks step-1 done
    r_done = acts.mark_done(str(camp), step="book-1", target_dir=str(proj_dir))
    assert r_done["ok"] is True
    assert r_done.get("unseated") == "book-1"
    rm_after = json.loads((camp / "roadmap.json").read_text(encoding="utf-8"))
    b1 = next(x for x in rm_after["roadmap_projection"] if x["id"] == "book-1")
    assert b1.get("seat") is None

    # Undo restores 'book-1' back onto Active
    r_undo = acts.act(str(camp), r_done["undo"])
    assert r_undo["ok"] is True
    rm_restored = json.loads((camp / "roadmap.json").read_text(encoding="utf-8"))
    b1_restored = next(x for x in rm_restored["roadmap_projection"] if x["id"] == "book-1")
    assert b1_restored.get("seat") == "active"

    # Conversational multi-clause Steward commands execute in <50ms
    t0 = time.perf_counter()
    r_conv = say.fast_steward_command(
        str(camp),
        "hey you can archive Book 1 Cockpit and let's elevate Book 2 Notes, and let's create a new one for Book 3 Outline",
        from_cave=True,
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    assert r_conv is not None and r_conv["ok"] is True
    assert elapsed_ms < 50.0, f"Expected <50ms, took {elapsed_ms:.1f}ms"

    rm_conv = json.loads((camp / "roadmap.json").read_text(encoding="utf-8"))
    by_id = {x["id"]: x for x in rm_conv["roadmap_projection"]}
    assert by_id["book-1"].get("seat") is None
    assert by_id["book-2"].get("seat") == "active"
    assert any("Book 3 Outline" in (x.get("name") or "") and x.get("seat") == "active" for x in rm_conv["roadmap_projection"])


def test_wave23_native_windows11_spellcheck_and_popup():
    """5. Native Windows 11 spellcheck engine returns recommended replacement words for misspelled words,
    and both shared.js and steward-dialogue.js wire left-click and right-click spellcheck popups."""
    from steward_cockpit import spellcheck_engine as se

    r_bad = se.check_word("delivrable")
    assert r_bad["ok"] is True
    assert r_bad["correct"] is False
    assert any(s.lower() == "deliverable" for s in r_bad["suggestions"])

    r_good = se.check_word("deliverable")
    assert r_good["ok"] is True
    assert r_good["correct"] is True

    shared_js = (ROOT / "steward_cockpit" / "static" / "shared.js").read_text(encoding="utf-8")
    dlg_js = (ROOT / "static" / "steward-dialogue.js").read_text(encoding="utf-8")
    assert "wireSpellcheckOnTextarea" in shared_js
    assert "anchor-spell-popup" in shared_js
    assert "wireSpellcheckOnTextarea" in dlg_js
    assert "anchor-spell-popup" in dlg_js


def test_wave23_status_table_routed_to_right_tile_and_live_eta():
    """6. Status tables in Steward chat are intercepted by extractAndRouteStatusTable and pushed to renderStatus,
    and computeMilestoneEtaParts computes a real Expected Time of Arrival (ETA) when running or idle."""
    shared_js = (ROOT / "steward_cockpit" / "static" / "shared.js").read_text(encoding="utf-8")
    assert "function extractAndRouteStatusTable(rawText)" in shared_js
    assert "routed-to-status" in shared_js
    assert "min left \\u00b7 est. finish" in shared_js


def test_wave23_youtube_links_open_in_second_window_with_close_button():
    """7. YouTube links rewrite to /steward-static/video.html and open in the 2nd split-screen window
    with a prominent Close Video button."""
    video_html = (ROOT / "steward_cockpit" / "static" / "video.html").read_text(encoding="utf-8")
    md_js = (ROOT / "steward_cockpit" / "static" / "md.js").read_text(encoding="utf-8")
    frame_js = (ROOT / "static" / "app-frame.js").read_text(encoding="utf-8")

    assert "Close Video" in video_html
    assert "exitSecondWindowMode" in video_html
    assert "/steward-static/video.html?v=" in md_js
    assert "/steward-static/video.html?v=" in frame_js


def test_wave23_talk_mode_and_cave_cross_cockpit_coordination(tmp_path):
    """8. Cave of Wonders Steward coordinates across seated cockpits: answers fleet status briefings,
    opens deliverables on command, relays feedback/approvals to target cockpits, and returns concise spoken_summary."""
    camp = tmp_path / "Campaign"
    camp.mkdir()
    b1_dir = tmp_path / "Book1"
    b1_dir.mkdir()
    (b1_dir / "CHAPTER-1.md").write_text("# Chapter 1\n", encoding="utf-8")
    (b1_dir / "DELIVERABLES.md").write_text(
        "# Deliverables\n\n| What | Where | Date | Step |\n| --- | --- | --- | --- |\n"
        "| FOR REVIEW: Chapter 1 Draft | `CHAPTER-1.md` | 2026-10-20 | step-1 |\n",
        encoding="utf-8",
    )
    (b1_dir / "roadmap.json").write_text(
        json.dumps(
            {
                "roadmap_projection": [
                    {"id": "step-1", "name": "Draft Chapter 1", "status": "waiting", "waiting_on_you": "Review Chapter 1 Draft"}
                ]
            }
        ),
        encoding="utf-8",
    )
    (camp / "roadmap.json").write_text(
        json.dumps(
            {
                "roadmap_projection": [
                    {
                        "id": "book-1",
                        "name": "Book 1 Cockpit",
                        "status": "waiting",
                        "seat": "active",
                        "seat_order": 0,
                        "effort_dir": str(b1_dir),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    # 1. Fleet brief ("what is ready for my input?")
    r_brief = say.fast_steward_command(str(camp), "what is ready for my input?", from_cave=True)
    assert r_brief is not None and r_brief["ok"] is True
    assert r_brief["act"] == "fleet_brief"
    assert "Book 1 Cockpit" in r_brief["say"]
    assert len(r_brief["spoken_summary"]) < 260

    # 2. Open deliverable from Cave ("open the deliverable for Book 1 Cockpit")
    r_open = say.fast_steward_command(str(camp), "open the deliverable for Book 1 Cockpit", from_cave=True)
    assert r_open is not None and r_open["ok"] is True
    assert r_open["act"] == "open_deliverable"
    assert "CHAPTER-1.md" in r_open["open_deliverable_url"]

    # 3. Relay feedback from Cave ("my feedback on Book 1 Cockpit is tighten the opening paragraph")
    r_fb = say.fast_steward_command(str(camp), "my feedback on Book 1 Cockpit is tighten the opening paragraph", from_cave=True)
    assert r_fb is not None and r_fb["ok"] is True
    assert r_fb["act"] == "relay_feedback"
    assert "tighten the opening paragraph" in r_fb["say"]


def test_wave23_steward_send_button_and_return_key_never_disabled():
    """9. Send button is never disabled in v1.html/v3.html markup, Return/Enter stops active dictation
    and sends immediately with optimistic rendering, and hot-reload preserves CONFIG['build']."""
    v1_html = (ROOT / "steward_cockpit" / "static" / "v1.html").read_text(encoding="utf-8")
    v3_html = (ROOT / "steward_cockpit" / "static" / "v3.html").read_text(encoding="utf-8")
    shared_js = (ROOT / "steward_cockpit" / "static" / "shared.js").read_text(encoding="utf-8")

    assert "data-send disabled" not in v1_html
    assert "data-send disabled" not in v3_html
    assert 'composerHost = (send && send.parentElement) || ta.parentElement' in shared_js
    assert "_isDictatingFn()" in shared_js
    assert "_skipNextJohnEcho" in shared_js


def test_wave24_continuous_dictation_scroll_filetypes_and_all_deliverables_search_sort():
    """10. Continuous dictation engine + dual-engine respawn, non-focus-stealing PDF/deliverable scrollview
    for Win+H, explicit file-type badges/extensions on all review links, full untruncated review tile titles,
    and All Deliverables search + sort (default date-desc, newest at top)."""
    from steward_cockpit import dictation_engine

    shared_js = (ROOT / "steward_cockpit" / "static" / "shared.js").read_text(encoding="utf-8")
    shared_css = (ROOT / "steward_cockpit" / "static" / "shared.css").read_text(encoding="utf-8")
    md_js = (ROOT / "steward_cockpit" / "static" / "md.js").read_text(encoding="utf-8")
    v1_html = (ROOT / "steward_cockpit" / "static" / "v1.html").read_text(encoding="utf-8")
    app_html = (ROOT / "static" / "app.html").read_text(encoding="utf-8")
    app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    steward_routes_py = (ROOT / "steward_cockpit" / "steward_routes.py").read_text(encoding="utf-8")

    # 1. Continuous dictation backend + frontend respawn loop
    assert hasattr(dictation_engine, "start_session")
    assert hasattr(dictation_engine, "poll_session")
    assert hasattr(dictation_engine, "stop_session")
    assert 'if verb == "dictate":' in steward_routes_py
    assert "spawnBrowserRecog()" in shared_js
    assert "/api/steward/dictate" in shared_js

    # 2. Scrollable deliverable window while dictating with Win+H (scrollview=1 + non-focus-stealing Page Up/Down)
    assert "_serve_pdf_scrollview" in steward_routes_py
    assert "_serve_pdf_page_png" in steward_routes_py
    assert "toScrollableDeliverableHref" in v1_html
    assert "data-dv-scroll-up" in v1_html
    assert "data-dv-scroll-down" in v1_html
    assert "pane-scroll" in app_html
    assert "scrollPane" in app_js

    # 3. File types preserved & displayed on review links and markdown links
    assert "inferDeliverableFormat" in shared_js
    assert "file-fmt-badge" in shared_js
    assert "file-fmt-badge" in shared_css
    assert "mdFileTypeBadge" in md_js

    # 4. Full untruncated titles in review tiles
    assert "stripDeliverableLeadPrefixes" in shared_js
    assert 'let fullTitle = desc.title || "Deliverable"' in shared_js
    assert "text-overflow: clip;" in shared_css

    # 5. All Deliverables search + sort by date (default newest first) & name + type filter
    assert '_allDelivSort = "date-desc"' in shared_js
    assert "allDelivSearch" in shared_js
    assert "allDelivSort" in shared_js
    assert "allDelivType" in shared_js
    assert "isRawUnaliasedManagedHash" in shared_js


def test_wave25_steward_run_completion_summary_and_organized_deliverables():
    """11. When long runs finish, Steward dialogue folds working-step chatter into .steward-working-steps,
    highlights the completion summary with badged clickable file links, coalesces consecutive receipt turns
    into a topic-organized .steward-run-deliverables-card, and pairs + groups For Review deliverables by topic."""
    shared_js = (ROOT / "steward_cockpit" / "static" / "shared.js").read_text(encoding="utf-8")
    shared_css = (ROOT / "steward_cockpit" / "static" / "shared.css").read_text(encoding="utf-8")
    md_js = (ROOT / "steward_cockpit" / "static" / "md.js").read_text(encoding="utf-8")
    code_jobs_py = (ROOT / "steward_cockpit" / "code_jobs.py").read_text(encoding="utf-8")
    skill_jobs_py = (ROOT / "steward_cockpit" / "skill_jobs.py").read_text(encoding="utf-8")

    # 1. Dialogue working-step folding + coalesced Run Deliverables Card
    assert "isReceiptTurnText" in shared_js
    assert "isWorkingNarrationLine" in shared_js
    assert "renderStewardTurnBody" in shared_js
    assert "steward-working-steps" in shared_js
    assert "steward-run-deliverables-card" in shared_js
    assert "rebuildRunDeliverablesCard" in shared_js
    assert "appendReceiptToDialogue" in shared_js

    # 2. Format pairing + topic grouping in For Review & Top Approval Bar
    assert "pairDeliverableFormats" in shared_js
    assert "classifyReviewTopicGroup" in shared_js
    assert "groupDeliverablesByTopic" in shared_js
    assert "getStewardCompletionSummaryText" in shared_js
    assert "steward-review-summary-banner" in shared_js
    assert "review-topic-group" in shared_js
    assert "companion-fmt-badge" in shared_js
    assert "companion-open-btn" in shared_js

    # 3. CSS & Markdown backticked file badges + backend job completion handoff guidance
    assert ".steward-run-deliverables-card" in shared_css
    assert ".srd-topics-grid" in shared_css
    assert ".review-topic-group" in shared_css
    assert "mdFileTypeBadge(inner, href, inner)" in md_js
    assert "links to the key deliverables grouped by topic/step" in code_jobs_py
    assert "organize clickable links to the key deliverables by topic/step" in skill_jobs_py






def test_review_point_does_not_auto_open_deliverable_or_review_tabs(tmp_path):
    """12. At a review point inside an AI Cockpit, neither the Deliverables tab (.blk.deliv) nor the
    For Review tab (details.tier-review) auto-opens; both stay collapsed by default and the status
    update notes that there is material to review."""
    shared_js = (ROOT / "steward_cockpit" / "static" / "shared.js").read_text(encoding="utf-8")
    shared_css = (ROOT / "steward_cockpit" / "static" / "shared.css").read_text(encoding="utf-8")

    # Deliverables hub and For Review sub-tab stay collapsed by default unless clicked by user
    assert "const defaultHubOpen = false;" in shared_js
    assert 'bindSubTileToggle(revFold, "deliv:v3:review");' in shared_js
    assert ": ((mainPairedReview.length > 0 || suppPairedReview.length > 0) && !isLegacyNavTest)" not in shared_js

    # Status update notes that there is material to review
    assert "renderStatus._syncReviewNote" in shared_js
    assert "status-review-note" in shared_js
    assert "Material to review" in shared_js
    assert ".status-review-note" in shared_css

    # Backend compose_status includes review_deliverables_count
    (tmp_path / "CHAPTER-1.md").write_text("# Chapter 1\n", encoding="utf-8")
    (tmp_path / "DELIVERABLES.md").write_text(
        "# Deliverables\n\n| What | Where | Date | Step |\n| --- | --- | --- | --- |\n"
        "| FOR REVIEW: Chapter 1 Draft | `CHAPTER-1.md` | 2026-10-21 | step-1 |\n",
        encoding="utf-8",
    )
    (tmp_path / "roadmap.json").write_text(
        json.dumps({"roadmap_projection": [{"id": "step-1", "name": "Draft Chapter 1", "status": "waiting"}]}),
        encoding="utf-8",
    )
    st = sc.compose_status(str(tmp_path), {"busy": False})
    assert st.get("review_deliverables_count") == 1


def test_wave26_orchestrator_reviewer_roles_deliverables_plan_refresh_and_usage_commas(tmp_path):
    """13. Simplified 2-role model policy (Orchestrator + Reviewer), deliverables click-to-open & sort/search,
    plan refresh proposal with Accept/Revert, feedback review reconciliation, and comma-formatted usage numbers."""
    import anchor_settings as aset
    import usage_allowance_monitor as uam

    shared_js = (ROOT / "steward_cockpit" / "static" / "shared.js").read_text(encoding="utf-8")
    md_js = (ROOT / "steward_cockpit" / "static" / "md.js").read_text(encoding="utf-8")
    anchor_gui_py = (ROOT / "anchor_gui.py").read_text(encoding="utf-8")

    # 1. Simplified 2-role model selectors (Orchestrator + Reviewer)
    assert ">Orchestrator " in anchor_gui_py
    assert ">Reviewer " in anchor_gui_py
    assert hasattr(aset, "save_settings")

    # 2. Deliverables: no Editing badge on click, expand only on .file-exp-btn, Final Deliverables search+sort & 0047 date sort
    assert 'if (false && stPill)' in shared_js
    assert 'if (false && tier === "review")' in shared_js
    assert 'if (!ev.target.closest(".file-exp-btn")) return;' in shared_js
    assert 'finalApproved.sort((a, b) => String(b.date || "").localeCompare(String(a.date || "")))' in shared_js
    assert 'fSearchInput.dataset.finalDelivSearch = "1"' in shared_js
    assert "r|py|sql|sh|ps1" in md_js

    # 3. Commas in token/dollar formatting
    assert "," in uam._fmt_tokens_short(14500)
    assert "14,500" in uam._fmt_tokens_short(14500)

    # 4. Plan refresh proposal (Accept New Plan / Revert to Old Plan) + Feedback review reconciliation
    (tmp_path / "ECGBERHT.md").write_text("# Test Campaign\n", encoding="utf-8")
    (tmp_path / "PLAN.md").write_text("# Plan\n\n## Wave 1: Core Build\n\n## Wave 2: Verification\n", encoding="utf-8")
    (tmp_path / "roadmap.json").write_text(
        json.dumps({"roadmap_projection": [{"id": "s1", "name": "Old Step", "status": "active"}], "roadmap_events": []}),
        encoding="utf-8",
    )
    (tmp_path / "strip.json").write_text(
        json.dumps({"human_wait": "Waiting for review of Chapter 1", "current_step_id": "s1"}),
        encoding="utf-8",
    )
    (tmp_path / "CHAPTER-1.md").write_text("# Chapter 1\n", encoding="utf-8")
    (tmp_path / "DELIVERABLES.md").write_text(
        "# Deliverables\n\n| What | Where | Date | Step |\n| --- | --- | --- | --- |\n"
        "| FOR REVIEW: Chapter 1 Draft | `CHAPTER-1.md` | 2026-10-22 | s1 |\n",
        encoding="utf-8",
    )
    ec = tmp_path / ".ecgberht"
    ec.mkdir(exist_ok=True)
    (ec / "plan-proposal.json").write_text(
        json.dumps({
            "id": "prop-1",
            "status": "pending",
            "title": "Refreshed Plan After Wave 1 Deliverables",
            "reason": "Added Wave 2 verification step.",
            "proposed_steps": [
                {"id": "s1", "name": "Wave 1: Core Build", "status": "done"},
                {"id": "s2", "name": "Wave 2: Verification", "status": "active"},
            ],
        }),
        encoding="utf-8",
    )
    m0 = sc.read_map(str(tmp_path))
    assert m0.get("plan_proposal") is not None
    assert m0["plan_proposal"]["id"] == "prop-1"

    acc = sc.resolve_plan_proposal(str(tmp_path), action="accept", proposal_id="prop-1")
    assert acc["ok"] is True and acc["action"] == "accepted" and acc["steps_count"] == 2

    rev = sc.resolve_plan_proposal(str(tmp_path), action="revert", proposal_id="prop-1")
    assert rev["ok"] is True and rev["action"] == "reverted" and rev["steps_count"] == 1

    rec = sc.reconcile_review_on_feedback(str(tmp_path), "Please do another round and tighten the opening section.")
    assert rec["ok"] is True and rec["reconciled"] == 1
    st_after = json.loads((tmp_path / "strip.json").read_text(encoding="utf-8"))
    assert st_after["human_wait"] == "none"


def test_wave27_plan_refresh_and_historical_plans_timeline(tmp_path):
    """14. Deliverable-driven plan refresh auto-detects completed/active steps from DELIVERABLES.md,
    reconstructs dated historical plans from roadmap_events + .ecgberht/plan-history.json,
    allows browsing/restoring any historical plan by date, and fixes isStepNow on done steps."""
    from steward_cockpit import steward_routes as sr

    shared_js = (ROOT / "steward_cockpit" / "static" / "shared.js").read_text(encoding="utf-8")
    shared_css = (ROOT / "steward_cockpit" / "static" / "shared.css").read_text(encoding="utf-8")

    # 1. Frontend Plan History Timeline & Fix for Done Steps with Stale Pin
    assert "let _planHistoryOpen = false;" in shared_js
    assert 'let _selectedPlanHistoryId = "";' in shared_js
    assert "const isStepNow = !isStepDone && !activeHistorySnap && isNow(st, map);" in shared_js
    assert 'btnHist.dataset.planHistoryToggle = "1";' in shared_js
    assert 'btnRefresh.dataset.planRefresh = "1";' in shared_js
    assert 'histPanel.dataset.planHistoryPanel = "1";' in shared_js
    assert "course:lec-1-4" in shared_js and "course:ai-supplements" in shared_js
    assert ".plan-history-panel" in shared_css
    assert ".plan-history-row" in shared_css
    assert ".plan-history-banner" in shared_css

    # 2. Backend chronological plan history reconstruction & deliverable-driven refresh
    (tmp_path / "ECGBERHT.md").write_text("# MBA Course\n", encoding="utf-8")
    (tmp_path / "LECTURE-1-FINAL.md").write_text("# Lecture 1 Final\n", encoding="utf-8")
    (tmp_path / "LECTURE-2-REVIEW.md").write_text("# Lecture 2 For Review\n", encoding="utf-8")
    (tmp_path / "DELIVERABLES.md").write_text(
        "# Deliverables\n\n| What | Where | Date | Step |\n| --- | --- | --- | --- |\n"
        "| FINAL: Lecture 1 Final Deck | `LECTURE-1-FINAL.md` | 2026-10-10 | lec-1 |\n"
        "| FOR REVIEW: Lecture 2 Deck | `LECTURE-2-REVIEW.md` | 2026-10-22 | lec-2 |\n",
        encoding="utf-8",
    )
    (tmp_path / "roadmap.json").write_text(
        json.dumps({
            "roadmap_projection": [
                {"id": "lec-1", "name": "Lecture 1", "status": "waiting"},
                {"id": "lec-2", "name": "Lecture 2", "status": "planned"},
                {"id": "lec-3", "name": "Lecture 3", "status": "planned"},
            ],
            "roadmap_events": [
                {"ts": "2026-10-01T10:00:00Z", "action": "add", "step": {"id": "lec-1", "name": "Lecture 1", "status": "planned"}},
                {"ts": "2026-10-01T10:01:00Z", "action": "add", "step": {"id": "lec-2", "name": "Lecture 2", "status": "planned"}},
                {"ts": "2026-10-10T15:00:00Z", "action": "update", "id": "lec-1", "patch": {"status": "waiting"}},
            ],
        }),
        encoding="utf-8",
    )

    m = sc.read_map(str(tmp_path))
    prop = m.get("plan_proposal")
    assert prop is not None and prop["status"] == "pending"
    assert len(prop.get("changes") or []) == 2

    hist = m.get("plan_history") or []
    dates = [h["date"] for h in hist]
    assert "2026-10-01" in dates and "2026-10-10" in dates

    # Accept deliverable refresh -> lec-1 becomes done, lec-2 becomes active, snapshot saved
    res_acc, code_acc = sr.handle_post(str(tmp_path), "plan-proposal", {"action": "accept"})
    assert code_acc == 200 and res_acc["ok"] is True
    m_after = sc.read_map(str(tmp_path))
    by_id = {s["id"]: s for s in m_after["steps"]}
    assert by_id["lec-1"]["status"] == "done"
    assert by_id["lec-2"]["status"] == "active"

    # Restore historical plan from 2026-10-01 -> restores the earlier snapshot
    snap_oct1 = next(h for h in m_after["plan_history"] if h["date"] == "2026-10-01")
    res_rest, code_rest = sr.handle_post(str(tmp_path), "plan-proposal", {"action": "restore", "version_id": snap_oct1["id"]})
    assert code_rest == 200 and res_rest["ok"] is True
    m_restored = sc.read_map(str(tmp_path))
    by_id_rest = {s["id"]: s for s in m_restored["steps"]}
    assert by_id_rest["lec-1"]["status"] == "planned"

