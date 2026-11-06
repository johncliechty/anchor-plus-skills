"""Regression tests for the 2026-10-31 wave:
1. Persistent Gmail & Outlook credentials, live-vs-hermetic separation, and two-way Steward comms (read/send/event).
2. Unfreezing token & dollar counts (additive cache_read_input_tokens pricing + code-jobs.json rollup join).
3. Deliverable opening/downloading fixes (subdirectory resolution, on-the-fly .docx/.html compilation, ../figures inline).
4. Taking down the AI Cockpit red flag (reconcile_review_on_feedback on ★ / START HERE / chapter ranges / viewed items).
"""
import base64
import json
from pathlib import Path

import comms_connector
from steward_cockpit import steward_campaign as campaign
from steward_cockpit import steward_engine as engine
from steward_cockpit import steward_routes as routes
from tools import reading_copy


def test_estimate_list_price_usd_prices_cached_tokens_additively():
    # Previously, cached_in was clamped to min(cache_read, inp), discarding 94%+ of cached tokens on typical Claude turns.
    u = {
        "input_tokens": 5_000,
        "output_tokens": 2_000,
        "cache_read_input_tokens": 500_000,
        "cache_creation_input_tokens": 20_000,
    }
    usd = engine.estimate_list_price_usd("claude-opus-5-5", u)
    # (5k + 20k) * $15/M ($0.375) + 500k * $1.50/M ($0.75) + 2k * $75/M ($0.15) = $1.275
    assert usd is not None
    assert abs(usd - 1.275) < 1e-4


def test_usage_rollup_joins_code_jobs_json(tmp_path):
    effort_dir = tmp_path / "Book 1"
    ecg = effort_dir / ".ecgberht"
    ecg.mkdir(parents=True)
    job_id = "20261031-120000-abc123"
    (ecg / "code-jobs.json").write_text(
        json.dumps({job_id: {"id": job_id, "skill": "chekhov", "status": "done"}}),
        encoding="utf-8",
    )
    estate = {
        f"C:\\Users\\example\\AppData\\Local\\Temp\\anchor-code-jobs\\{job_id}": {
            "cli": "claude",
            "model_policy": {"model": "claude-opus-5-5", "model_served": "claude-opus-5-5"},
            "usage": {
                "turns": 1,
                "tokens": 114_000,
                "reported_spend": 0.60,
                "cost_complete": True,
            },
        }
    }
    rollup = routes._usage_rollup_fresh(str(effort_dir), estate=estate)
    assert rollup["jobs"]["count"] >= 1
    assert rollup["jobs"]["tokens"] == 114_000
    assert rollup["jobs"]["reported_spend"] == 0.60


def test_reconcile_review_on_feedback_handles_star_and_chapter_ranges_and_viewed(tmp_path):
    cdir = tmp_path / "Book 1"
    ch_dir = cdir / "chapters"
    ch_dir.mkdir(parents=True)
    (ch_dir / "CHAPTERS-01-TO-05-MANUSCRIPT-v9.docx").write_bytes(b"PK\x03\x04dummy")
    (cdir / "DELIVERABLES.md").write_text(
        "# Deliverables — Book 1\n\n"
        "| What | Where | Date | Step |\n"
        "|---|---|---|---|\n"
        "| ★ Ch 1–5 Manuscript v9 (Editable .docx) | `chapters/CHAPTERS-01-TO-05-MANUSCRIPT-v9.docx` | 2026-10-31 | setup-chapters |\n",
        encoding="utf-8",
    )
    ecg = cdir / ".ecgberht"
    ecg.mkdir(parents=True, exist_ok=True)
    (ecg / "strip.json").write_text(
        json.dumps({"human_wait": "Review Chapters 1-5 v9", "next_recommended": "Draft Ch 6"}),
        encoding="utf-8",
    )
    # 1. Verify _cockpit_review_candidates sees the ★ item
    cands = campaign._cockpit_review_candidates(cdir)
    assert len(cands) == 1
    # 2. Verify feedback mentioning "chapter 5" or after viewing reconciles the ★ item and clears human_wait
    campaign.record_deliverable_viewed(cdir, "chapters/CHAPTERS-01-TO-05-MANUSCRIPT-v9.docx")
    res = campaign.reconcile_review_on_feedback(cdir, "Here are my notes on Chapter 5 pacing and dialogue.")
    assert res["ok"] is True
    assert res["reconciled"] == 1
    strip_after = json.loads((ecg / "strip.json").read_text(encoding="utf-8"))
    assert strip_after.get("human_wait") == "none"


def test_reading_copy_embeds_parent_sibling_figures(tmp_path):
    proj = tmp_path / "Paper 1"
    (proj / ".ecgberht").mkdir(parents=True)
    fig_dir = proj / "figures"
    fig_dir.mkdir(parents=True)
    png_1x1 = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQ"
        + "AAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUB"
        + "AScY42YAAAAASUVORK5CYII="
    )
    (fig_dir / "fig1.png").write_bytes(png_1x1)
    deliv_dir = proj / "deliverables"
    deliv_dir.mkdir(parents=True)
    md = deliv_dir / "draft.md"
    md.write_text("# Draft\n\n![Figure 1](../figures/fig1.png)\n", encoding="utf-8")
    html_str = reading_copy.page(md, for_print=False)
    assert "data:image/png;base64," in html_str


def test_comms_two_way_actions_hermetic(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_COMMS_HERMETIC", "1")
    r_save, code_save = comms_connector.handle_comms_post(
        {
            "action": "save_account",
            "provider": "gmail",
            "email": "john@example.com",
            "secret": "abcd efgh ijkl mnop",
        }
    )
    assert code_save == 200 and r_save["ok"] is True

    r_send, code_send = comms_connector.handle_comms_post(
        {
            "action": "send_email",
            "to": "colleague@example.com",
            "subject": "Anchor Update",
            "body": "Testing two-way send.",
        }
    )
    assert code_send == 200 and r_send["ok"] is True and r_send["transport"] == "hermetic_smtp"

    r_ev, code_ev = comms_connector.handle_comms_post(
        {
            "action": "create_event",
            "title": "Research Sync",
            "start": "2026-11-02T10:00:00",
            "end": "2026-11-02T10:30:00",
        }
    )
    assert code_ev == 200 and r_ev["ok"] is True


def test_microsoft_device_code_2fa_and_steward_history_attachments(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_COMMS_HERMETIC", "1")

    # 1. Start Microsoft 365 + 2FA Device Code Flow for Penn State Outlook
    r_start, c_start = comms_connector.handle_comms_post(
        {
            "action": "oauth_device_start",
            "email": "faculty@example.org",
            "label": "Penn State Outlook",
        }
    )
    assert c_start == 200 and r_start["ok"] is True
    assert r_start["user_code"] == "ANCHOR2FA"
    assert "login.microsoft.com/device" in r_start["verification_uri"]

    # 2. Poll Device Code Flow to completion -> stores JSON token bundle in Vault & marks connected
    r_poll, c_poll = comms_connector.handle_comms_post(
        {
            "action": "oauth_device_poll",
            "state": r_start["state"],
            "account_id": r_start["account_id"],
        }
    )
    assert c_poll == 200 and r_poll["ok"] is True and r_poll["status"] == "connected"
    tok = comms_connector._get_valid_oauth_access_token(r_start["account_id"], family="outlook")
    assert tok.startswith("hermetic-msgraph-tok-")

    # 3. Search email history & download attachments locally via Steward CLI
    from tools import steward_comms

    att_dir = tmp_path / "saved_attachments"
    rc_att = steward_comms.main(
        [
            "attachments",
            "--subject",
            "Exmera LP Transfer",
            "--save-dir",
            str(att_dir),
            "--filename",
            "transfer-template.docx",
        ]
    )
    assert rc_att == 0
    saved = list(att_dir.glob("*"))
    assert len(saved) == 1 and saved[0].name == "transfer-template.docx"

    rc_hist = steward_comms.main(["history", "--query", "Anchor"])
    assert rc_hist == 0


def test_honest_account_status_pills_and_four_mockups(tmp_path, monkeypatch):
    import high_seat_page

    ctx = {
        "comms": {
            "accounts": [
                {
                    "id": "comms-01fd25fe",
                    "family": "outlook",
                    "label": "Microsoft Outlook & Calendar",
                    "email": "faculty@example.org",
                    "status": "auth_error",
                    "last_imap_note": "Basic authentication is disabled.",
                },
                {
                    "id": "comms-3a9bfa74",
                    "family": "gmail",
                    "label": "Primary Gmail & Calendar",
                    "email": "primary@example.com",
                    "status": "connected",
                },
            ],
            "calendar_events": [],
            "email_threads": [],
            "poller": {"running": True, "interval_minutes": 15},
        }
    }
    html = high_seat_page._comms_pulse_html(ctx)
    assert "Needs Sign-In / 2FA" in html
    assert 'data-comms-ms-device-auth="comms-01fd25fe"' in html
    assert "Sign In with Microsoft 365 (2FA)" in html
    assert 'href="/comms-mockups"' in html
    # Verify Option 1 + Click-to-Full (Mockup 3) layout controls on the Cave of Wonders page
    assert 'data-comms-layout="split"' in html
    assert 'data-comms-layout="cal"' in html
    assert 'data-comms-layout="mail"' in html
    assert 'data-comms-layout-toggle="cal"' in html
    assert 'data-comms-layout-toggle="mail"' in html
    assert "Full Calendar 100% (Mockup 3)" in html
    assert "Full Email 100% (Mockup 3)" in html

    mockups_file = Path(__file__).resolve().parent.parent / "static" / "comms-mockups.html"
    m_html = mockups_file.read_text(encoding="utf-8")
    for mid in ("mockup-1", "mockup-2", "mockup-3"):
        assert mid in m_html
    assert "iPhone Rolling Stream" in m_html
    assert "Emails to Address" in m_html
    assert "Not Interested" in m_html


def test_multi_calendar_merge_and_steward_triage_learning(tmp_path, monkeypatch):
    import comms_connector
    import paths

    monkeypatch.setenv("ANCHOR_COMMS_HERMETIC", "1")
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)

    # 1. Multi-calendar duplicate merging
    raw_evs = [
        {"uid": "1", "date": "2026-10-26", "start_time": "18:30", "end_time": "20:00", "title": "Dinner Adam Smith", "calendar_badge": "PSU 365"},
        {"uid": "2", "date": "2026-10-26", "start_time": "18:30", "end_time": "20:00", "title": "Dinner with A. Smith - Quant", "location": "American Ale House", "calendar_badge": "Axmra 365"},
    ]
    merged = comms_connector.merge_multi_calendar_events(raw_evs)
    assert len(merged) == 1
    assert merged[0]["calendar_count"] == 2
    assert "PSU 365" in merged[0]["calendars"] and "Axmra 365" in merged[0]["calendars"]
    assert "2 Calendars" in merged[0]["merged_badge"]

    # 2. Steward 2-Bucket Email Triage & Learning (Seen unopened = negative, Downgrade, Upgrade)
    comms_connector.save_comms_sync({
        "synced_at": "2026-11-01 14:20",
        "calendar_events": merged,
        "email_headers": [
            {"uid": "m1", "subject": "Class Absences - Big Ten Tournament", "from": "Camryn Standish", "sender_email": "crs@example.org", "date": "2026-11-01 17:39", "has_attachments": True, "account_badge": "PSU 365", "folder": "INBOX"},
            {"uid": "m2", "subject": "Special Newsletter", "from": "Digest Bot", "sender_email": "bot@example.org", "date": "2026-11-01 12:00", "has_attachments": False, "account_badge": "PSU 365", "folder": "INBOX"},
        ],
    })
    imp, oth = comms_connector.classify_inbox_emails(comms_connector.load_comms_sync()["email_headers"])
    assert any(x["uid"] == "m1" for x in imp)
    assert any(x["uid"] == "m2" for x in imp)

    # Tap 'Seen' WITHOUT opening m2 -> demotes to other_emails & lowers sender score
    r_seen = comms_connector.record_email_triage_feedback({"uid": "m2", "feedback": "seen", "was_opened": False, "sender_email": "bot@example.org"})
    assert r_seen["ok"] is True
    assert any(x["uid"] == "m2" for x in r_seen["other_emails"])

    # Upgrade m2 back to important_emails
    r_up = comms_connector.record_email_triage_feedback({"uid": "m2", "feedback": "upgrade", "sender_email": "bot@example.org"})
    assert r_up["ok"] is True
    assert any(x["uid"] == "m2" for x in r_up["important_emails"])

    # Downgrade m2 explicitly
    r_down = comms_connector.record_email_triage_feedback({"uid": "m2", "feedback": "downgrade", "sender_email": "bot@example.org"})
    assert r_down["ok"] is True
    assert any(x["uid"] == "m2" for x in r_down["other_emails"])
