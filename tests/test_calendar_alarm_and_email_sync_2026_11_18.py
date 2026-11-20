# -*- coding: utf-8 -*-
"""Regression tests for 2026-11-18 Anchor upgrades:
1. Calendar Event Alarm (Anchor top-bar & Cave flash, chime, system Notification + popup window, Exit & Go to).
2. Cave of Wonders left-rail dynamic `Email (N)` count in parentheses.
3. Email inclusion & upstream basic-email-service mark-as-read durability fixes.
"""
from __future__ import annotations

from datetime import date, timedelta
import io
import json
from pathlib import Path
import urllib.parse

import pytest

import comms_connector as cc
import distro
import high_seat_page as hsp
import paths


@pytest.fixture()
def isolated_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_COMMS_HERMETIC", "1")
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    (tmp_path / ".anchor").mkdir(parents=True, exist_ok=True)
    cc._RECONCILE_COMMS_CACHE.clear()
    cc.reset_provider_breakers()
    yield tmp_path
    cc._RECONCILE_COMMS_CACHE.clear()
    cc.reset_provider_breakers()


def test_same_day_followup_and_cross_account_or_multisender_unread_emails_are_included(isolated_env: Path) -> None:
    today_iso = date.today().isoformat()
    acted = {
        "mail-a:100": {
            "uid": "100",
            "account_id": "mail-a",
            "message_id": "<msg-100@example.com>",
            "sender_email": "colleague@example.com",
            "subject": "Project Schedule",
            "date": f"{today_iso} 09:00",
            "at_utc": f"{today_iso}T14:05:00Z",
            "status": "✓ Replied & Sent",
        },
        "sr-synthetic-1": {
            "uid": "sr-synthetic-1",
            "account_id": "mail-a",
            "sender_email": "colleague@example.com",
            "subject": "Separate Topic",
            "date": f"{today_iso} 09:10",
            "status": "✓ Replied · Answered",
        },
    }
    headers = [
        # Original acted-upon message
        {
            "uid": "100",
            "account_id": "mail-a",
            "account_badge": "Gmail",
            "message_id": "<msg-100@example.com>",
            "from": "Colleague One <colleague@example.com>",
            "sender_email": "colleague@example.com",
            "subject": "Project Schedule",
            "date": f"{today_iso} 09:00",
            "snippet": "Can we meet Tuesday?",
            "is_read": True,
        },
        # Same-day unread follow-up reply with distinct UID & Message-ID: MUST NOT be hidden by ssd
        {
            "uid": "105",
            "account_id": "mail-a",
            "account_badge": "Gmail",
            "message_id": "<msg-105@example.com>",
            "from": "Colleague One <colleague@example.com>",
            "sender_email": "colleague@example.com",
            "subject": "Re: Project Schedule",
            "date": f"{today_iso} 15:30",
            "snippet": "Action required: Tuesday at 2 PM works — please confirm deadline.",
            "is_read": False,
        },
        # Unread message on a DIFFERENT account sharing the subject: MUST NOT be suppressed
        {
            "uid": "graph-200",
            "account_id": "mail-b",
            "account_badge": "Institutional 365",
            "message_id": "<msg-200@example.org>",
            "from": "Colleague One <colleague@example.com>",
            "sender_email": "colleague@example.com",
            "subject": "Re: Project Schedule",
            "date": f"{today_iso} 08:55",
            "snippet": "Action required: institutional copy needing review.",
            "inference_classification": "focused",
            "is_read": False,
        },
        # Unread message from a DIFFERENT sender on the same thread: MUST NOT be suppressed
        {
            "uid": "106",
            "account_id": "mail-a",
            "account_badge": "Gmail",
            "message_id": "<msg-106@example.com>",
            "from": "Partner Two <partner2@example.com>",
            "sender_email": "partner2@example.com",
            "subject": "Re: Project Schedule",
            "date": f"{today_iso} 08:50",
            "snippet": "Action required: here are my comments on the schedule.",
            "has_attachments": True,
            "is_read": False,
        },
        # Unread real message matching synthetic sr-* sender+subject+day: synthetic entry MUST NOT collide via ssd
        {
            "uid": "107",
            "account_id": "mail-a",
            "account_badge": "Gmail",
            "message_id": "<msg-107@example.com>",
            "from": "Colleague One <colleague@example.com>",
            "sender_email": "colleague@example.com",
            "subject": "Separate Topic",
            "date": f"{today_iso} 11:00",
            "snippet": "Action required: please review attached agreement.",
            "has_attachments": True,
            "is_read": False,
        },
    ]

    prefs = {"acted_upon_emails": acted, "upgraded_senders": ["colleague@example.com", "partner2@example.com"]}
    prime, irrational = cc.classify_inbox_emails(headers, prefs)
    active_items = prime + irrational
    active_uids = {e["uid"] for e in active_items}
    all_thread_uids = {
        str(m.get("uid") or "")
        for e in active_items
        for m in (e.get("thread_messages") or [])
    } | active_uids
    # Cross-account graph-200, same-day follow-up 105, and non-synthetic 107 are separate active cards;
    # same-account thread participant 106 is preserved inside 105's thread_messages AND stands alone when 105 is absent.
    assert {"105", "graph-200", "107"}.issubset(active_uids)
    assert "106" in all_thread_uids
    assert "100" not in active_uids

    headers_without_105 = [h for h in headers if h["uid"] != "105"]
    prime2, irrational2 = cc.classify_inbox_emails(headers_without_105, {"acted_upon_emails": acted, "upgraded_senders": ["partner2@example.com"]})
    assert "106" in {e["uid"] for e in (prime2 + irrational2)}


def test_sync_comms_now_preserves_live_unread_and_capped_backfill_headers(isolated_env: Path, monkeypatch) -> None:
    today_d = date(2026, 11, 18)
    account = {
        "id": "acct-1",
        "email": "owner@example.com",
        "family": "outlook",
        "label": "Work 365",
        "status": "connected",
        "auth_mode": "oauth_token",
        "imap_host": "outlook.office365.com",
    }
    prev_sync = {
        "synced_at": "2026-11-18 09:00",
        "calendar_events": [],
        "sent_email_headers": [],
        "email_headers": [
            # Previously falsely marked is_read=True in cache, but NOT acted-upon in Anchor:
            {
                "uid": "u-live-unread",
                "account_id": "acct-1",
                "account_badge": "Work 365",
                "subject": "Important question",
                "from": "Alice <alice@example.com>",
                "sender_email": "alice@example.com",
                "date": "2026-11-18 08:30",
                "is_read": True,
            },
            # Retained unread message beyond page cap when _rest_unread_capped is True:
            {
                "uid": "u-retained-unread",
                "account_id": "acct-1",
                "account_badge": "Work 365",
                "subject": "Backlog unread item",
                "from": "Bob <bob@example.com>",
                "sender_email": "bob@example.com",
                "date": "2026-11-15 14:00",
                "is_read": False,
            },
            # Older >14d unread message: must NOT be dropped or marked read!
            {
                "uid": "u-older-unread",
                "account_id": "acct-1",
                "account_badge": "Work 365",
                "subject": "Older unread contract",
                "from": "Carol <carol@example.com>",
                "sender_email": "carol@example.com",
                "date": "2026-10-25 11:00",
                "is_read": False,
            },
        ],
    }
    cc.save_comms_sync(prev_sync)

    def fake_fetch_headers(acc, _secret, max_messages=50, timeout=8.0):
        acc["_rest_unread_capped"] = True
        return True, "ok", [
            {
                "uid": "u-live-unread",
                "account_id": "acct-1",
                "account_badge": "Work 365",
                "subject": "Important question",
                "from": "Alice <alice@example.com>",
                "sender_email": "alice@example.com",
                "date": "2026-11-18 08:30",
                "is_read": False,
            }
        ]

    monkeypatch.setattr(cc, "load_comms_config", lambda: {"accounts": [account], "preferences": {}})
    monkeypatch.setattr(cc, "save_comms_config", lambda cfg: cfg)
    monkeypatch.setattr(cc, "get_account_secret", lambda _aid: '{"access_token":"tok"}')
    monkeypatch.setattr(cc, "fetch_imap_headers", fake_fetch_headers)
    monkeypatch.setattr(cc, "fetch_sent_headers", lambda *_a, **_kw: (True, "ok", []))
    monkeypatch.setattr(cc, "fetch_google_caldav_events", lambda *_a, **_kw: (True, "ok", []))

    cc.sync_comms_now(entries=[], facts={}, today=today_d)
    saved = cc.load_comms_sync()
    by_uid = {h["uid"]: h for h in saved["email_headers"]}
    assert by_uid["u-live-unread"]["is_read"] is False
    assert by_uid["u-retained-unread"]["is_read"] is False
    assert by_uid["u-older-unread"]["is_read"] is False


def test_graph_slash_uid_quoting_and_batched_imap_mark_read_upstream(isolated_env: Path, monkeypatch) -> None:
    monkeypatch.setenv("ANCHOR_COMMS_HERMETIC", "0")
    monkeypatch.setattr(cc, "_is_hermetic", lambda: False)
    # Prevent background daemon race so test flushes deterministically
    monkeypatch.setattr(cc, "_schedule_remote_read_flush", lambda: None)

    accounts = [
        {
            "id": "graph-acct",
            "family": "outlook",
            "email": "user@example.org",
            "label": "Campus 365",
            "auth_mode": "oauth_token",
            "imap_host": "outlook.office365.com",
        },
        {
            "id": "imap-acct",
            "family": "gmail",
            "email": "user@example.com",
            "label": "Personal Mail",
            "auth_mode": "app_password",
            "imap_host": "imap.gmail.com",
            "imap_port": 993,
        },
    ]
    cc.save_comms_config({"accounts": accounts, "preferences": {}})

    slash_graph_id = "graph-msg-id-001/slash+part=="
    cc.save_comms_sync({
        "email_headers": [
            {
                "uid": slash_graph_id,
                "account_id": "graph-acct",
                "account_badge": "Campus 365",
                "from": "Dean <dean@example.org>",
                "sender_email": "dean@example.org",
                "subject": "Committee Agenda",
                "date": "2026-11-18 10:00",
                "is_read": False,
            },
            {
                "uid": "15451",
                "account_id": "imap-acct",
                "account_badge": "Personal Mail",
                "from": "Friend <friend@example.com>",
                "sender_email": "friend@example.com",
                "subject": "Trip Itinerary",
                "date": "2026-11-18 09:15",
                "is_read": False,
            },
            {
                "uid": "15452",
                "account_id": "imap-acct",
                "account_badge": "Personal Mail",
                "from": "Friend <friend@example.com>",
                "sender_email": "friend@example.com",
                "subject": "Re: Trip Itinerary",
                "date": "2026-11-18 09:20",
                "is_read": False,
            },
        ],
        "sent_email_headers": [],
        "calendar_events": [],
    })

    monkeypatch.setattr(
        cc,
        "get_account_secret",
        lambda aid: '{"access_token":"placeholder"}' if aid == "graph-acct" else "abcd efgh ijkl mnop",
    )
    monkeypatch.setattr(cc, "_get_valid_oauth_access_token", lambda *_a, **_kw: "placeholder")

    graph_requests: list[tuple[str, str, bytes]] = []

    class _DummyResp:
        def __enter__(self):
            return io.BytesIO(b"{}")

        def __exit__(self, *_args):
            return False

    def fake_urlopen(req, timeout=8.0):
        graph_requests.append((req.get_method(), req.full_url, req.data or b""))
        return _DummyResp()

    imap_store_calls: list[tuple] = []
    imap_connections_opened = [0]

    class FakeImapSsl:
        def __init__(self, *_a, **_kw):
            imap_connections_opened[0] += 1

        def select(self, mbox, readonly=False):
            assert mbox == "INBOX" and readonly is False
            return "OK", [b"2"]

        def uid(self, cmd, uid_set, flag_op, flags):
            imap_store_calls.append((cmd, uid_set, flag_op, flags))
            return "OK", [b"1"]

        def logout(self):
            return "BYE", []

    monkeypatch.setattr(paths, "safe_urlopen", fake_urlopen)
    monkeypatch.setattr(cc.imaplib, "IMAP4_SSL", FakeImapSsl)
    monkeypatch.setattr(cc, "_imap_authenticate", lambda *_a, **_kw: None)

    # 1. Triage feedback on Graph message with '/' in UID
    res_g = cc.record_email_triage_feedback({
        "uid": slash_graph_id,
        "account_id": "graph-acct",
        "sender_email": "dean@example.org",
        "subject": "Committee Agenda",
        "feedback": "seen",
    })
    assert res_g["ok"] is True

    # 2. Triage feedback ('done') on 15452 should also sweep same-account same-sender sibling 15451
    res_i = cc.record_email_triage_feedback({
        "uid": "15452",
        "account_id": "imap-acct",
        "sender_email": "friend@example.com",
        "subject": "Re: Trip Itinerary",
        "date": "2026-11-18 09:20",
        "feedback": "done",
    })
    assert res_i["ok"] is True

    # Verify durable queue has all 3 pending before flush
    pending_before = cc._pending_remote_read_map()
    assert pending_before[("graph-acct", slash_graph_id)] is True
    assert pending_before[("imap-acct", "15452")] is True
    assert pending_before[("imap-acct", "15451")] is True

    flush_res = cc.flush_pending_read_sync()
    assert flush_res["ok"] is True
    assert flush_res["synced"] == 3
    assert flush_res["remaining"] == 0

    # Graph '/' MUST be percent-encoded as %2F in URL path
    assert len(graph_requests) == 1
    method, url, body_bytes = graph_requests[0]
    assert method == "PATCH"
    assert urllib.parse.quote(slash_graph_id, safe="") in url
    assert "Slash+Id" not in url  # '+' is also percent-encoded
    assert json.loads(body_bytes.decode("utf-8")) == {"isRead": True}

    # IMAP batched both UIDs on a SINGLE IMAP4_SSL connection, using +FLAGS (\Seen), zero EXPUNGE
    assert imap_connections_opened[0] == 1
    assert len(imap_store_calls) == 1
    cmd, uid_csv, flag_op, flags = imap_store_calls[0]
    assert cmd == "STORE"
    assert set(uid_csv.split(",")) == {"15451", "15452"}
    assert flag_op == "+FLAGS"
    assert flags == "(\\Seen)"


def test_speed_racer_dismiss_marks_read_upstream_and_sync_self_heals_stuck_unread(isolated_env: Path, monkeypatch) -> None:
    read_calls: list[dict] = []
    monkeypatch.setattr(cc, "mark_email_read_remote", lambda **kw: read_calls.append(kw) or {"ok": True})

    cc.save_comms_sync({
        "email_headers": [
            {
                "uid": "u-sr-drop",
                "account_id": "acct-g",
                "account_badge": "Gmail",
                "from": "Sender <s@example.com>",
                "sender_email": "s@example.com",
                "subject": "FYI Report",
                "date": "2026-11-18 08:00",
                "is_read": False,
            }
        ],
        "sent_email_headers": [],
        "calendar_events": [],
    })
    cc.save_speed_racer_queue({
        "queue": [
            {
                "id": "sr-drop-1",
                "uid": "u-sr-drop",
                "account_id": "acct-g",
                "to": "Sender <s@example.com>",
                "subject": "Re: FYI Report",
                "draft_body": "Thanks!",
            }
        ],
        "archive": [],
    })
    dis_res = cc.act_speed_racer_draft({"action": "dismiss", "id": "sr-drop-1"})
    assert dis_res["ok"] is True
    assert any(c.get("uid") == "u-sr-drop" and c.get("account_id") == "acct-g" and c.get("is_read") is True for c in read_calls)
    acted_after = cc.load_triage_prefs()["acted_upon_emails"]
    assert "u-sr-drop" in acted_after
    assert acted_after["u-sr-drop"].get("at_utc")


def test_cave_left_rail_renders_email_count_in_parentheses() -> None:
    base_ctx = {
        "build": "testbuild",
        "steward": {
            "label": "Aladdin",
            "high_seat": "aladdin-high-seat-cave.png",
            "high_seat_name": "Cave of Wonders",
            "mode_name": "Star Chart",
        },
        "campaign": {"pid": "camp-1"},
        "initiatives": [],
        "entries": [],
        "facts": {},
        "week_short": "Nov 18",
        "tasks_open": 2,
        "terms_open": 0,
        "capacity": [],
        "comms": {
            "important_emails": [
                {"uid": "e1", "is_read": False, "acted_upon": False},
                {"uid": "e2", "is_read": False, "acted_upon": False},
                {"uid": "e3", "is_read": False, "acted_upon": False},
                {"uid": "e4", "is_read": True, "acted_upon": False},
            ]
        },
    }
    rail_html = hsp._rail(base_ctx)
    assert 'id="railEmailLabel">Email (3)<' in rail_html
    assert 'data-rail="email" class="has-unread"' in rail_html

    zero_ctx = dict(base_ctx, comms={"important_emails": []})
    rail_zero = hsp._rail(zero_ctx)
    assert 'id="railEmailLabel">Email (0)<' in rail_zero
    assert 'data-rail="email" class="has-unread"' not in rail_zero


def test_calendar_alarm_endpoints_and_ui_wiring(isolated_env: Path) -> None:
    today_iso = date.today().isoformat()
    cc.save_comms_sync({
        "calendar_events": [
            {
                "uid": "ev-standup-1",
                "title": "Research Team Sync",
                "date": today_iso,
                "start_time": "14:30",
                "end_time": "15:00",
                "location": "https://zoom.us/j/123456789",
                "calendar_badge": "Institutional 365",
                "rsvp_status": "responded",
            }
        ],
        "email_headers": [],
        "sent_email_headers": [],
    })

    # 1. GET view=calendar_alarms returns default prefs + today's event
    get_res, status_get = cc.handle_comms_get({"view": "calendar_alarms"})
    assert status_get == 200
    assert get_res["ok"] is True
    assert get_res["calendar_alarms"]["enabled"] is True
    assert get_res["calendar_alarms"]["lead_minutes"] == 5
    assert any(e.get("uid") == "ev-standup-1" for e in get_res["calendar_events"])

    # 2. POST calendar_alarm_prefs updates lead_minutes & persists to .anchor/calendar-alarms.json
    pref_res, status_pref = cc.handle_comms_post({
        "action": "calendar_alarm_prefs",
        "enabled": True,
        "lead_minutes": 10,
        "sound_enabled": True,
        "popup_enabled": True,
    })
    assert status_pref == 200 and pref_res["ok"] is True
    assert pref_res["calendar_alarms"]["lead_minutes"] == 10

    # 3. POST calendar_alarm_ack records dismissal / goto key
    ack_key = f"ev-standup-1@{today_iso}T14:30"
    ack_res, status_ack = cc.handle_comms_post({
        "action": "calendar_alarm_ack",
        "alarm_key": ack_key,
        "uid": "ev-standup-1",
        "title": "Research Team Sync",
        "date": today_iso,
        "start_time": "14:30",
        "via": "goto",
    })
    assert status_ack == 200 and ack_res["ok"] is True
    assert ack_res["calendar_alarms"]["acknowledged"][ack_key]["via"] == "goto"

    # 4. Static assets & shell wiring exist
    repo_root = Path(__file__).resolve().parent.parent
    alarm_js = (repo_root / "static" / "calendar-alarm.js").read_text(encoding="utf-8")
    alarm_html = (repo_root / "static" / "calendar-alarm.html").read_text(encoding="utf-8")
    app_html = (repo_root / "static" / "app.html").read_text(encoding="utf-8")
    app_js = (repo_root / "static" / "app.js").read_text(encoding="utf-8")
    hsp_js = (repo_root / "static" / "high-seat-page.js").read_text(encoding="utf-8")

    assert "AnchorCalendarAlarm" in alarm_js
    assert "new Notification(" in alarm_js
    assert 'id="btnGoto"' in alarm_html and 'id="btnExit"' in alarm_html
    assert '/static/calendar-alarm.js' in app_html
    assert "goToCalendarEvent" in app_js
    assert "_focusCaveCalendarEvent" in hsp_js
    assert "_syncRailEmailCount" in hsp_js


def test_speed_racer_drafts_for_corporate_last_first_and_prompt_bar_lookup(
    isolated_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify corporate 'SURNAME, GIVEN' + truncated Graph '<email' headers never reject Speed Racer drafting."""
    import scribe_engine as se

    monkeypatch.setattr(cc, "mark_email_read_remote", lambda **_kw: {"ok": True})
    scribe_calls: list[dict] = []

    def _fake_scribe_hook(*, prompt: str = "", bundle: dict | None = None, **_kw):
        scribe_calls.append({"prompt": prompt, "bundle": bundle or {}})
        return "Hi Rowan,\n\nThank you so much for the thoughtful feedback and support.\n\nBest regards,\nAlex"

    se.set_scribe_llm_hook(_fake_scribe_hook)
    try:
        # 1. _format_graph_recipient preserves '>' and quotes comma-containing names
        fmt_rec = cc._format_graph_recipient("VANCE, ROWAN", "rowan@example.org")
        assert fmt_rec.endswith("<rowan@example.org>")
        assert '"VANCE, ROWAN"' in fmt_rec

        # Garbage recipients still fail strict validation
        with pytest.raises(cc.InvalidPayloadError):
            cc._parse_recipient_list("not-a-valid-email", strict=True)
        with pytest.raises(cc.InvalidPayloadError):
            cc._parse_recipient_list("not-an-email, alice@example.com", strict=True)

        cc.save_comms_config({
            "accounts": [{"id": "acct-365", "family": "outlook", "email": "owner@example.org", "label": "Inst 365"}]
        })
        cc.save_comms_sync({
            "email_headers": [
                {
                    "uid": "u-corp-followup",
                    "account_id": "acct-365",
                    "account_badge": "Inst 365",
                    "from": "VANCE, ROWAN",
                    "sender_email": "rowan@example.org",
                    "to": "Owner, Alex <owner@example.org",
                    "cc": "Mercer, Jordan Lee <jordan@example.org, VANCE, ROWAN <rowan@example.org",
                    "subject": "Re: Course Module Feedback",
                    "body": "Thank you for receiving the module comments with such supportive sentiments.\n\nWarm regards,\nRowan",
                    "snippet": "Thank you for receiving the module comments",
                    "date": "2026-11-18 11:56",
                    "direction": "inbound",
                    "is_read": False,
                }
            ],
            "sent_email_headers": [],
            "calendar_events": [],
        })

        # 2. Inbox card [-> Speed Racer] button with unquoted 'VANCE, ROWAN <rowan@example.org>' succeeds
        res_card, code_card = cc.handle_comms_post({
            "action": "speed_racer_queue",
            "uid": "u-corp-followup",
            "account_id": "acct-365",
            "from": "VANCE, ROWAN",
            "sender_email": "rowan@example.org",
            "to": "VANCE, ROWAN <rowan@example.org>",
            "subject": "Re: Course Module Feedback",
        })
        assert code_card == 200 and res_card["ok"] is True
        q1 = cc.load_speed_racer_queue()["queue"]
        assert len(q1) == 1
        assert "Rowan Vance <rowan@example.org>" == q1[0]["to"]
        assert "Jordan Lee Mercer <jordan@example.org>" == q1[0]["reply_all_cc"]
        assert "Thank you so much for the thoughtful feedback" in q1[0]["draft_body"]

        # 3. Reading Pane [Scribe -> Speed Racer] with legacy raw corporate cc + 'include anyone in the cc' succeeds
        res_dlg, code_dlg = cc.handle_comms_post({
            "action": "speed_racer_queue",
            "uid": "u-corp-followup",
            "account_id": "acct-365",
            "to": "rowan@example.org",
            "cc": "Mercer, Jordan Lee <jordan@example.org, VANCE, ROWAN <rowan@example.org",
            "subject": "Re: Course Module Feedback",
            "steward_directions": "Write a polite response and include anyone in the cc.",
        })
        assert code_dlg == 200 and res_dlg["ok"] is True
        q2 = cc.load_speed_racer_queue()["queue"]
        assert "jordan@example.org" in q2[0]["cc"].lower()

        # 4. Speed Racer prompt bar without uid/subject resolves 'Rowan' from address book & binds latest inbound email
        cc.save_speed_racer_queue({"queue": [], "archive": []})
        res_prompt, code_prompt = cc.handle_comms_post({
            "action": "speed_racer_queue",
            "uid": "",
            "to": "",
            "subject": "",
            "steward_directions": "Write a polite response to my email from Rowan",
        })
        assert code_prompt == 200 and res_prompt["ok"] is True
        q3 = cc.load_speed_racer_queue()["queue"]
        assert len(q3) == 1
        assert q3[0]["uid"] == "u-corp-followup"
        assert "Course Module Feedback" in q3[0]["subject"]
        assert "supportive sentiments" in q3[0]["incoming_body"]
        assert len(scribe_calls) >= 3
    finally:
        se.set_scribe_llm_hook(None)


def test_distro_stdlib_import_and_pii_gate_clean() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    shippable = [(rel, repo_root / rel) for rel in distro.select_shippable(repo_root)]
    assert distro.scan_third_party_imports(shippable, root=repo_root) == []
    touched = [
        "comms_connector.py",
        "high_seat_page.py",
        "static/calendar-alarm.js",
        "static/calendar-alarm.html",
        "static/high-seat-page.js",
        "static/high-seat-page.css",
        "static/app.html",
        "static/app.js",
        "static/app.css",
        "static/app-frame.js",
        "tests/test_calendar_alarm_and_email_sync_2026_11_18.py",
    ]
    touched_pairs = [(rel, repo_root / rel) for rel in touched]
    assert distro.scan_paths(touched_pairs, root=repo_root) == []
