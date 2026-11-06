"""Regression tests for the 2026-11-04 Cockpit Steward Retool (Anvil + Gandalf + Cross-Family Adversarial Review)
and Cave of Wonders Sent Emails view."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import comms_connector as cc
import high_seat_page as hsp
from steward_cockpit import steward_campaign as sc
from steward_cockpit import steward_engine as se


def test_steward_prompt_deduplicated_and_4_pillar_spine_present():
    """Verify SIZE_OR_HOLD is not duplicated 3x in full across CONTRACT/EFFORT_DUTY/EFFORT_RULES,
    while all required contract tokens and the unified 4-Pillar Steward Spine remain intact."""
    full_size_block = se.SIZE_OR_HOLD.strip()
    assert full_size_block in se.SMALL_DUTY
    assert full_size_block in se.EFFORT_DUTY
    # CONTRACT and EFFORT_RULES use the concise 1-sentence _size_summary() instead of repeating 2,600 chars
    assert full_size_block not in se.CONTRACT
    assert full_size_block not in se.EFFORT_RULES

    for required_token in (
        "SIZE THE WORK",
        "--worker foreman",
        "Crucible slim",
        "Crucible is on hold",
        "producing a plan does not approve it",
    ):
        assert required_token in se.CONTRACT
        assert required_token in se.EFFORT_DUTY
        assert required_token in se.EFFORT_RULES

    assert "(12b) IMMEDIATE RESPONSIVENESS & COCKPIT SYNC — THE 4-PILLAR STEWARD SPINE" in se.CONTRACT
    assert "turn-end reconciler" in se.CONTRACT


def test_revision_requested_does_not_promote_to_final_deliverable(tmp_path: Path):
    """Cross-family defeater e-2: requesting revisions on a For Review item dismisses the pending review
    dot without promoting the unapproved draft to Final Deliverables."""
    cdir = tmp_path / "campaign"
    cdir.mkdir(parents=True)
    draft_file = cdir / "draft_slides.md"
    draft_file.write_text("# Lecture 1 Draft\n", encoding="utf-8")
    gandalf_file = cdir / "gandalf_read.md"
    gandalf_file.write_text("# Gandalf Deep-Think Read\n", encoding="utf-8")

    (cdir / "roadmap.json").write_text(
        json.dumps(
            {
                "goal": "Create MIT AI Lecture Slides",
                "roadmap_projection": [
                    {"id": "1", "name": "Draft Lecture 1 Slides", "status": "active"},
                    {"id": "2", "name": "Reopened Step", "status": "proposed"},
                ],
            }
        ),
        encoding="utf-8",
    )
    (cdir / "strip.json").write_text(
        json.dumps({"current_step_id": "1", "active_effort": "Draft Lecture 1 Slides"}),
        encoding="utf-8",
    )
    (cdir / "DELIVERABLES.md").write_text(
        "# Deliverables\n\n"
        "| What | Where | Date | Step |\n"
        "|---|---|---|---|\n"
        "| START HERE — FOR REVIEW: Lecture 1 Slide Deck | `draft_slides.md` | 2026-11-04 | 1 |\n"
        "| Gandalf read on Lecture 1 | `gandalf_read.md` | 2026-11-04 | 1 |\n",
        encoding="utf-8",
    )

    # 1. Before feedback: draft_slides.md is in for_review, gandalf_read.md is supporting/intermediate
    items_before = sc.read_deliverables(str(cdir)).get("items") or []
    by_path_before = {it["path"]: it for it in items_before}
    assert by_path_before["draft_slides.md"]["is_current"] is True
    assert by_path_before["draft_slides.md"]["tier"] == "for_review"
    assert by_path_before["gandalf_read.md"]["is_intermediate"] is True
    assert by_path_before["gandalf_read.md"]["tier"] == "supporting"

    # 2. User asks for revisions ("please revise slide 3 and fix the chart")
    res_rev = sc.reconcile_review_on_feedback(str(cdir), "Please revise slide 3 and fix the chart.")
    assert res_rev["reconciled"] == 1
    assert res_rev["kind"] == "revision_requested"

    items_after_rev = sc.read_deliverables(str(cdir)).get("items") or []
    by_path_rev = {it["path"]: it for it in items_after_rev}
    assert by_path_rev["draft_slides.md"]["is_current"] is False
    assert by_path_rev["draft_slides.md"]["final_promoted"] is False
    assert by_path_rev["draft_slides.md"]["tier"] == "supporting"

    # 3. Publish v2 for review and approve it ("looks good, ship it")
    draft_v2 = cdir / "draft_slides_v2.md"
    draft_v2.write_text("# Lecture 1 Final Slide Deck v2\n", encoding="utf-8")
    (cdir / "DELIVERABLES.md").write_text(
        "# Deliverables\n\n"
        "| What | Where | Date | Step |\n"
        "|---|---|---|---|\n"
        "| START HERE — FOR REVIEW: Lecture 1 Slide Deck v2 | `draft_slides_v2.md` | 2026-11-04 | 1 |\n"
        "| Gandalf read on Lecture 1 | `gandalf_read.md` | 2026-11-04 | 1 |\n",
        encoding="utf-8",
    )
    res_app = sc.reconcile_review_on_feedback(str(cdir), "Looks good, ship it!")
    assert res_app["reconciled"] == 1
    assert res_app["kind"] == "approved"

    items_after_app = sc.read_deliverables(str(cdir)).get("items") or []
    by_path_app = {it["path"]: it for it in items_after_app}
    assert by_path_app["draft_slides_v2.md"]["is_current"] is False
    assert by_path_app["draft_slides_v2.md"]["final_promoted"] is True
    assert by_path_app["draft_slides_v2.md"]["tier"] == "final"


def test_reconcile_cockpit_turn_state_preserves_fresh_status_card_and_syncs_overview(tmp_path: Path):
    """Verify reconcile_cockpit_turn_state updates overview.json and backfills status_card.json only when stale."""
    cdir = tmp_path / "campaign_sync"
    cdir.mkdir(parents=True)
    (cdir / "roadmap.json").write_text(
        json.dumps(
            {
                "goal": "Retool Cockpit Steward",
                "steps": [
                    {"id": "1", "name": "Run Anvil & Gandalf review", "status": "done"},
                    {"id": "2", "name": "Wire turn-end reconciler", "status": "active"},
                ],
            }
        ),
        encoding="utf-8",
    )
    (cdir / "strip.json").write_text(
        json.dumps({"current_step_id": "2", "active_effort": "Wiring turn-end reconciler"}),
        encoding="utf-8",
    )

    # First run: no status_card.json exists -> backfills it and writes overview.json
    res1 = sc.reconcile_cockpit_turn_state(
        str(cdir),
        user_text="Let's check progress on the turn-end reconciler",
        turn_text="Working on wiring reconcile_cockpit_turn_state.",
    )
    assert res1["ok"] is True
    assert isinstance(res1.get("overview"), dict)
    assert (cdir / ".ecgberht" / "overview.json").exists()
    assert (cdir / ".ecgberht" / "status_card.json").exists()

    # Second run immediately after Steward wrote an explicit status card: must NOT clobber fresh card
    custom_sc_path = cdir / ".ecgberht" / "status_card.json"
    custom_sc = {
        "updated_at": "2026-11-04T12:00:00Z",
        "doing": "Custom Steward Doing Line",
    }
    custom_sc_path.write_text(json.dumps(custom_sc), encoding="utf-8")
    now_ts = time.time()
    os.utime(custom_sc_path, (now_ts, now_ts))

    res2 = sc.reconcile_cockpit_turn_state(
        str(cdir),
        user_text="",
        turn_text="Completed custom status update.",
    )
    assert res2["ok"] is True
    saved_sc = json.loads(custom_sc_path.read_text(encoding="utf-8"))
    assert saved_sc["doing"] == "Custom Steward Doing Line"


def test_sent_emails_backend_and_cave_ui(monkeypatch, tmp_path: Path):
    """Verify gather_sent_emails, read_email_message for log-* sent items, and Cave of Wonders Sent Emails UI."""
    fake_cfg = {
        "accounts": [
            {"id": "acc-gmail", "email": "sender@example.com", "label": "Primary Gmail", "family": "gmail", "status": "connected"},
            {"id": "acc-psu", "email": "faculty@example.org", "label": "Penn State 365", "family": "outlook", "status": "connected"},
        ],
        "manual_logs": [
            {
                "id": "log-test1234",
                "direction": "sent",
                "account_id": "acc-gmail",
                "account_badge": "Gmail",
                "from": "sender@example.com",
                "to": "collaborator@example.com",
                "subject": "MIT Lecture Slides Ready",
                "body": "Attached are the final MIT AI lecture slides.",
                "at": "2026-11-04 10:15",
            }
        ],
    }
    fake_sync = {
        "synced_at": "2026-11-04 12:00",
        "calendar_events": [],
        "email_headers": [],
        "sent_email_headers": [
            {
                "uid": "sent-psu-001",
                "subject": "Re: MBA Curriculum Update",
                "from": "faculty@example.org",
                "sender_email": "faculty@example.org",
                "to": "dean@example.org",
                "counterparty": "dean@example.org",
                "date": "2026-11-04 09:30",
                "snippet": "Here is the updated syllabus for Spring 2027.",
                "direction": "sent",
                "folder": "SENT",
                "account_id": "acc-psu",
                "account_badge": "PSU 365",
            }
        ],
    }
    monkeypatch.setattr(cc, "load_comms_config", lambda: fake_cfg)
    monkeypatch.setattr(cc, "load_comms_sync", lambda: fake_sync)

    sent_list = cc.gather_sent_emails(fake_sync, fake_cfg)
    assert len(sent_list) == 2
    uids = {s["uid"] for s in sent_list}
    assert "log-test1234" in uids
    assert "sent-psu-001" in uids

    # Verify read_email_message resolves manual_logs sent item directly
    msg = cc.read_email_message({"uid": "log-test1234"})
    assert msg["ok"] is True
    assert msg["subject"] == "MIT Lecture Slides Ready"
    assert msg["to"] == "collaborator@example.com"
    assert "Attached are the final MIT AI lecture slides." in msg["body"]

    # Verify Cave of Wonders _comms_pulse_html renders Sent Emails controls and cards
    html = hsp._comms_pulse_html({"entries": [], "facts": {}, "today": None})
    assert 'id="caveMailSentCol"' in html
    assert 'id="caveMailSentList"' in html
    assert 'data-cave-mail-folder="sent"' in html
    assert 'data-cave-open-sent="1"' in html
    assert "MIT Lecture Slides Ready" in html
    assert "Re: MBA Curriculum Update" in html
