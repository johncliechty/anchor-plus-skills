"""Wave 2 oracle: streamlined Cave Email Modal, multi-recipient To/CC/BCC + autocomplete,
pure Calendar + locked Watchlist migration, open-by-default reactive Living *The List*,
and the Wave 2 5-state failure contract (`unknown != empty`)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import textwrap

import pytest

import comms_connector as comms
import distro
import high_seat_core
import high_seat_page
import paths
from steward_cockpit import steward_engine
from tools import steward_comms


REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_COMMS_HERMETIC", "1")
    monkeypatch.setattr(comms, "_CAVE_STEWARD_DISPATCH_HOOK", None)
    monkeypatch.setattr(comms, "_SEND_TRANSPORT_HOOK", None)
    return tmp_path


def _minimal_cave_ctx(**overrides) -> dict:
    ctx = {
        "build": "w2-test",
        "today": date(2026, 11, 13),
        "today_str": "Fri, Nov 13, 2026",
        "week": "Week of Nov 9",
        "week_short": "Nov 9-15",
        "auth_required": False,
        "logged_in": True,
        "steward": {
            "label": "Ecgberht",
            "high_seat_name": "Cave of Wonders",
            "high_seat": "cave-of-wonders.jpg",
            "campaign_icon": "campaign-aladdin-star-chart.jpg",
            "mode_name": "Star Chart",
        },
        "campaign": {"pid": "proj-camp"},
        "entries": [],
        "facts": {},
        "groups": {},
        "initiatives": [],
        "parked": [],
        "rows": [],
        "bullets": [],
        "counts": {},
        "tasks_open": 0,
        "seeds": 0,
        "seed_rows": [],
        "terms_open": 0,
        "capacity": [],
    }
    ctx.update(overrides)
    return ctx


def test_streamlined_email_modal_and_inbox_tabs_contract(isolated_data):
    html = high_seat_page.render_high_seat_html(_minimal_cave_ctx())
    js_src = (REPO_ROOT / "static" / "high-seat-page.js").read_text(encoding="utf-8")
    css_src = (REPO_ROOT / "static" / "high-seat-page.css").read_text(encoding="utf-8")

    # 1) Inbox UI tabs renamed to Prime / Irrational / All
    assert 'id="btnCaveMailFolderPrime"' in html
    assert 'data-cave-mail-folder="prime"' in html
    assert 'id="btnCaveMailFolderIrrational"' in html
    assert 'data-cave-mail-folder="irrational"' in html
    assert 'id="btnCaveShowAllEmails"' in html
    assert 'data-cave-mail-folder="all"' in html

    # 2) Streamlined top modal action bar: 5 triage actions + attachments, Prime/Irrational move, Float, Close
    m_top = re.search(
        r'<div class="cave-dlg-top-actions"[^>]*>(.*?)</div>\s*</div>',
        html,
        flags=re.S,
    )
    assert m_top is not None
    top_bar = m_top.group(1)
    for required_label in (
        "Mull Over w/ Steward",
        "Seen &amp; Important",
        "Looked At / Ignore",
        "Done",
        "Answered",
        "Save Attachments",
        "Irrational",
        "Prime",
        "Close",
    ):
        assert required_label in top_bar
    for retired_label in (
        "Quick Reply Here",
        "Put in Speed Racer",
        "Add to Calendar &amp; Done",
        "Add to Calendar & Done",
    ):
        assert retired_label not in html
        assert retired_label not in js_src

    # 3) 1-line modal header + suppressed duplicate single-message inner header
    assert 'id="caveDlgHeaderOneLine"' in html
    assert 'class="cave-dlg-header-1line"' in html
    assert "msgs.length <= 1" in js_src
    assert "cave-single-msg-card" in js_src

    # 4) Shrink-to-fit short email body box
    assert "min-height: 0" in css_src
    assert "height: auto" in css_src
    assert "max-height: min(62vh, 620px)" in css_src

    # 5) Auto-growing <textarea rows="1"> with per-UID localStorage auto-save for Steward & Speed Racer inputs
    assert '<textarea id="caveDlgStewardDirectionsInput" rows="1"' in html
    assert '<textarea id="caveSrFeedbackInput" rows="1"' in js_src
    assert "_autoGrowTextarea" in js_src
    assert "localStorage.setItem" in js_src
    assert "localStorage.removeItem" in js_src

    # 6) Consolidated single Send to Steward button + zero duplicate Steward bar inside Direct Reply drawer
    assert html.count("Send to Steward") == 1
    assert "Steward Task + Scribe Draft" not in html
    assert "Steward Task + Scribe Draft" not in js_src
    m_reply = re.search(
        r'<details id="caveDlgDirectReplyDrawer"[^>]*>(.*?)</details>',
        html,
        flags=re.S,
    )
    assert m_reply is not None
    reply_drawer_html = m_reply.group(1)
    assert "caveDlgStewardDirectionsInput" not in reply_drawer_html
    assert "Send to Steward" not in reply_drawer_html

    # 7) Speed Racer auto-open + 60s sync refresh hook
    assert "_syncSpeedRacerFromServer(d.speed_racer)" in js_src
    assert "openCaveSpeedRacer" in js_src


def test_single_send_to_steward_dispatch_and_503_queue_fallback(isolated_data, monkeypatch):
    full_body = (
        "Paragraph one: Vendor proposes a revised liability cap for Q4 hardware delivery.\n\n"
        "Paragraph two: Clause 7.4 requires written sign-off before Friday 17:00 ET."
    )
    comms.save_comms_sync({
        "synced_at": "2026-11-13 09:00",
        "calendar_events": [],
        "sent_email_headers": [],
        "email_headers": [
            {
                "uid": "uid-steward-503",
                "account_id": "acc-1",
                "account_badge": "Commercial 365",
                "from": "Alex Counsel <counsel@example.org>",
                "sender_email": "counsel@example.org",
                "subject": "Clause 7.4 Liability Cap",
                "date": "2026-11-13 08:45",
                "body": full_body,
                "snippet": full_body[:90],
                "body_preloaded": True,
            },
            {
                "uid": "uid-steward-live",
                "account_id": "acc-1",
                "account_badge": "Commercial 365",
                "from": "Alex Counsel <counsel@example.org>",
                "sender_email": "counsel@example.org",
                "subject": "Clause 7.4 Sign-Off",
                "date": "2026-11-13 08:50",
                "body": full_body,
                "snippet": full_body[:90],
                "body_preloaded": True,
            },
        ],
    })

    # Part A: Steward engine unavailable -> HTTP 503 + durable on-disk queue fallback
    monkeypatch.setattr(comms, "_CAVE_STEWARD_DISPATCH_HOOK", lambda _cave_dir: None)
    res_503, code_503 = comms.handle_comms_post({
        "action": "email_steward_action",
        "uid": "uid-steward-503",
        "subject": "Clause 7.4 Liability Cap",
        "from": "Alex Counsel <counsel@example.org>",
        "sender_email": "counsel@example.org",
        "comment": "Evaluate Clause 7.4 risk and recommend counter-language.",
    })
    assert code_503 == 503
    assert res_503["ok"] is False
    assert res_503["failure_state"] == "dependency-missing"
    assert res_503["message"] == "Cave Steward engine unavailable — message queued safely"

    queued_file = isolated_data / ".anchor" / "cave-steward-queued.json"
    assert queued_file.is_file()
    queued_doc = json.loads(queued_file.read_text(encoding="utf-8"))
    queued_items = queued_doc.get("queued") or queued_doc.get("items") or []
    assert any(
        it.get("uid") == "uid-steward-503" and "Clause 7.4 requires written sign-off" in str(it.get("prompt") or it.get("body") or "")
        for it in queued_items
    )

    # Part B: Live Steward engine -> single eng.say(prompt, human=True), zero fabricated assistant turn, zero unconditional List tile
    class FakeStewardEngine:
        def __init__(self):
            self.calls: list[tuple[str, bool]] = []

        def say(self, prompt: str, human: bool = False):
            self.calls.append((prompt, human))
            return {"ok": True}

    fake_eng = FakeStewardEngine()
    monkeypatch.setattr(comms, "_CAVE_STEWARD_DISPATCH_HOOK", lambda _cave_dir: fake_eng)

    res_ok, code_ok = comms.handle_comms_post({
        "action": "email_steward_action",
        "uid": "uid-steward-live",
        "subject": "Clause 7.4 Sign-Off",
        "from": "Alex Counsel <counsel@example.org>",
        "sender_email": "counsel@example.org",
        "comment": "Compare Clause 7.4 against our standard cap.",
    })
    assert code_ok == 200
    assert res_ok["ok"] is True
    assert len(fake_eng.calls) == 1
    sent_prompt, sent_human = fake_eng.calls[0]
    assert sent_human is True
    assert "Paragraph two: Clause 7.4 requires written sign-off" in sent_prompt
    assert "Compare Clause 7.4 against our standard cap." in sent_prompt

    wl_after = comms.load_working_list_spine()
    assert wl_after["tiles"] == []
    assert any(p.get("source_key") == "steward-dispatch:uid-steward-live" for p in wl_after["proposals"])


def test_parse_recipient_list_and_multi_recipient_bcc_end_to_end(isolated_data, monkeypatch):
    html = high_seat_page.render_high_seat_html(_minimal_cave_ctx())
    js_src = (REPO_ROOT / "static" / "high-seat-page.js").read_text(encoding="utf-8")
    assert 'id="caveReplyBcc"' in html
    assert 'id="commsDraftBcc"' in html
    assert 'id="caveSrBccInput"' in js_src

    # 1) _parse_recipient_list: quoted semicolons/commas, case-insensitive dedup, strict validation
    parsed = comms._parse_recipient_list(
        '"Finance; Audit, Ops" <finance@example.org>; Alice Example <ALICE@example.com>, alice@example.com'
    )
    assert [r["email"].lower() for r in parsed] == ["finance@example.org", "alice@example.com"]
    assert "Finance; Audit, Ops" in parsed[0]["name"]

    with pytest.raises(comms.InvalidPayloadError):
        comms._parse_recipient_list("not-a-valid-email", strict=True)
    with pytest.raises(comms.InvalidPayloadError):
        comms._parse_recipient_list("valid@example.com\r\nBcc: spy@example.org", strict=True)

    # 2) >100 total recipients across To + CC + BCC refused with HTTP 400 contract message
    many_to = ", ".join(f"user{i}@example.com" for i in range(45))
    many_cc = ", ".join(f"cc{i}@example.org" for i in range(35))
    many_bcc = ", ".join(f"bcc{i}@example.net" for i in range(25))
    over_res, over_code = comms.handle_comms_post({
        "action": "send_email",
        "to": many_to,
        "cc": many_cc,
        "bcc": many_bcc,
        "subject": "Cap test",
        "body": "Testing >100 recipient refusal.",
    })
    assert over_code == 400
    assert over_res["ok"] is False
    assert over_res["message"] == "Invalid recipient or proposal payload rejected"

    # 3) Contact autocomplete merges unified address book + Scribe proper_names on trailing comma/semicolon token
    comms.save_comms_sync({
        "synced_at": "2026-11-13 09:00",
        "calendar_events": [],
        "sent_email_headers": [],
        "email_headers": [
            {
                "uid": "u-c1",
                "from": "mcbride@example.org",
                "sender_email": "mcbride@example.org",
                "to": "Jordan Partner <jordan@example.com>",
                "subject": "Board deck",
            }
        ],
    })
    scribe_mem_path = isolated_data / ".anchor" / "scribe-memory.json"
    paths.atomic_write_json(
        scribe_mem_path,
        {
            "proper_names": {"mcbride": "McBride"},
            "sender_profiles": {
                "taylor@example.net": {"email": "taylor@example.net", "display_name": "Taylor Counsel"}
            },
        },
    )
    ac_get, ac_get_code = comms.handle_comms_get({"view": "contacts", "q": "jordan@example.com; mcb"})
    assert ac_get_code == 200 and ac_get["ok"] is True
    assert ac_get["token"] == "mcb"
    assert any(
        c["email"].lower() == "mcbride@example.org" and "McBride" in c["formatted"]
        for c in ac_get["contacts"]
    )
    ac_post, ac_post_code = comms.handle_comms_post({"action": "contacts", "query": "jordan@example.com, tay"})
    assert ac_post_code == 200
    assert any(c["email"].lower() == "taylor@example.net" for c in ac_post["contacts"])

    # 4) create_reply_draft strips Bcc header from .eml while preserving bcc in mailto_url and Speed Racer queue
    draft_res = comms.create_reply_draft({
        "to": "lead@example.com",
        "cc": "team@example.org",
        "bcc": "blind1@example.net; blind2@example.net",
        "subject": "Quarterly Review",
        "body": "Hi Lead,\n\nAttached are the updated numbers for the quarterly review.\n\nBest regards,",
    })
    assert draft_res["ok"] is True
    eml_text = Path(draft_res["eml_path"]).read_text(encoding="utf-8")
    assert "Cc: team@example.org" in eml_text
    assert "Bcc:" not in eml_text and "blind1@example.net" not in eml_text
    assert "bcc=" in draft_res["mailto_url"] and "blind1%40example.net" in draft_res["mailto_url"]

    # 5) Live SMTP transport: envelope includes To+CC+BCC while MIME message strips Bcc header
    comms.save_comms_config({
        "accounts": [
            {
                "id": "acc-smtp",
                "family": "gmail",
                "label": "Work Mail",
                "email": "sender@example.com",
                "auth_mode": "app_password",
                "smtp_host": "smtp.example.com",
                "smtp_port": 465,
                "status": "connected",
            },
            {
                "id": "acc-graph",
                "family": "outlook",
                "label": "Institutional 365",
                "email": "faculty@example.org",
                "auth_mode": "oauth_token",
                "smtp_host": "smtp.example.org",
                "smtp_port": 587,
                "status": "connected",
            },
        ],
        "preferences": {},
    })
    monkeypatch.setattr(comms, "get_account_secret", lambda _aid: "tok-123")
    monkeypatch.setattr(comms, "_get_valid_oauth_access_token", lambda *_a, **_kw: "tok-123")
    monkeypatch.setattr(comms, "_SEND_TRANSPORT_HOOK", comms._transmit_email_live)

    smtp_captured: dict = {}

    class FakeSmtpSsl:
        def __init__(self, host, port, context=None, timeout=None):
            smtp_captured["host"] = host
            smtp_captured["port"] = port

        def login(self, user, secret_val):
            smtp_captured["login"] = (user, secret_val)

        def send_message(self, msg, from_addr=None, to_addrs=None):
            smtp_captured["bcc_header"] = msg["Bcc"]
            smtp_captured["to_header"] = msg["To"]
            smtp_captured["cc_header"] = msg["Cc"]
            smtp_captured["raw_headers"] = str(msg)
            smtp_captured["envelope"] = list(to_addrs or [])

        def quit(self):
            return None

    monkeypatch.setattr(comms.smtplib, "SMTP_SSL", FakeSmtpSsl)
    smtp_send = comms.send_email_message({
        "account_id": "acc-smtp",
        "to": "to1@example.com; to2@example.com",
        "cc": "cc1@example.org",
        "bcc": "audit@example.net, archive@example.net",
        "subject": "SMTP Blind Copy Verification",
        "body": "Confirming multi-recipient blind copy behavior.",
    })
    assert smtp_send["ok"] is True and smtp_send["sent"] is True
    assert smtp_captured["bcc_header"] is None
    assert "audit@example.net" not in smtp_captured["raw_headers"]
    assert smtp_captured["envelope"] == [
        "to1@example.com",
        "to2@example.com",
        "cc1@example.org",
        "audit@example.net",
        "archive@example.net",
    ]

    # 6) Speed Racer queue + edit + approve_send over Microsoft Graph with toRecipients / ccRecipients / bccRecipients
    graph_captured: dict = {}

    class FakeGraphResp:
        status = 202

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b""

    def fake_urlopen(req, timeout=None):
        graph_captured["url"] = req.full_url
        graph_captured["payload"] = json.loads(req.data.decode("utf-8"))
        return FakeGraphResp()

    monkeypatch.setattr(comms.urllib.request, "urlopen", fake_urlopen)

    sr_q = comms.queue_speed_racer_draft({
        "account_id": "acc-graph",
        "to": "dean@example.org",
        "cc": "chair@example.org",
        "bcc": "records@example.net",
        "subject": "Committee Sign-Off",
        "draft_body": (
            "Hi Dean,\n\nI have reviewed the committee packet and approve moving forward on Monday.\n\nBest regards,"
        ),
        "preserve_manual_draft": True,
    })
    assert sr_q["ok"] is True and sr_q["open_speed_racer"] is True
    sr_id = sr_q["draft_id"]

    sr_edit = comms.act_speed_racer_draft({
        "sr_action": "edit",
        "draft_id": sr_id,
        "to": "dean@example.org, provost@example.org",
        "cc": "chair@example.org",
        "bcc": "records@example.net; compliance@example.net",
        "draft_body": "Hi Dean,\n\nApproved for Monday's agenda.\n\nBest regards,",
    })
    assert sr_edit["ok"] is True
    assert "compliance@example.net" in sr_edit["draft"]["bcc"]

    sr_approve = comms.act_speed_racer_draft({
        "sr_action": "approve_send",
        "draft_id": sr_id,
    })
    assert sr_approve["ok"] is True
    assert graph_captured["url"] == "https://graph.microsoft.com/v1.0/me/sendMail"
    g_msg = graph_captured["payload"]["message"]
    assert [r["emailAddress"]["address"] for r in g_msg["toRecipients"]] == [
        "dean@example.org",
        "provost@example.org",
    ]
    assert [r["emailAddress"]["address"] for r in g_msg["ccRecipients"]] == ["chair@example.org"]
    assert [r["emailAddress"]["address"] for r in g_msg["bccRecipients"]] == [
        "records@example.net",
        "compliance@example.net",
    ]


def test_pure_calendar_and_watchlist_idempotent_migration(isolated_data, capsys):
    html = high_seat_page.render_high_seat_html(_minimal_cave_ctx())
    js_src = (REPO_ROOT / "static" / "high-seat-page.js").read_text(encoding="utf-8")
    assert "caveUpcomingPrepStrip" not in html
    assert "caveUpcomingPrepStrip" not in js_src
    assert "Upcoming Calendar Prep & Linked Emails" not in html

    # 1) Verify all 4 non-meeting Calendar injectors are stopped while genuine timed meetings remain
    # (a) Roadmap milestones (`rm-*`), (b) `_ensure_email_logged_on_calendar`, (c) 08:30-17:00 synthetic workday block, (d) follow-up markers
    sync_probe = {"calendar_events": []}
    log_lbl = comms._ensure_email_logged_on_calendar(
        {"uid": "u-mail-1", "subject": "Invitation: Contract follow-up", "date": "2026-11-18"},
        sync_probe,
        user_requested=True,
    )
    assert isinstance(log_lbl, str)
    assert sync_probe["calendar_events"] == []
    assert list((isolated_data / ".anchor" / "calendar").glob("*.ics")) == []

    marker_ev = comms.create_calendar_event({
        "uid": "anc-ev-followup-1",
        "title": "Follow-up: Submit revised budget",
        "date": "2026-11-18",
        "is_followup_marker": True,
    })
    assert marker_ev["ok"] is True
    assert marker_ev["redirected_to_watchlist"] is True
    assert marker_ev["ics_path"] == ""

    real_ev = comms.create_calendar_event({
        "uid": "anc-ev-real-1",
        "title": "Research Advisory Board Call",
        "date": "2026-11-18",
        "time": "14:00",
        "end_time": "15:00",
        "location": "Room 210",
    })
    assert real_ev["ok"] is True
    assert not real_ev.get("redirected_to_watchlist")
    real_ics = Path(real_ev["ics_path"])
    assert real_ics.is_file()
    assert "TRANSP:OPAQUE" in real_ics.read_text(encoding="utf-8")

    # Inject a synthetic 08:30-17:00 workday block into sync cache and verify reconcile_comms_with_roadmaps strips it
    sync_doc = comms.load_comms_sync()
    sync_doc["calendar_events"] = list(sync_doc.get("calendar_events") or []) + [
        {
            "uid": "syn-workday-block",
            "title": "Focus Task Block",
            "date": "2026-11-18",
            "start_time": "08:30",
            "end_time": "17:00",
            "time_label": "08:30–17:00",
        }
    ]
    comms.save_comms_sync(sync_doc)

    reconciled = comms.reconcile_comms_with_roadmaps(
        entries=[{"id": "proj-1", "name": "Alpha", "group": "Research"}],
        facts={
            "proj-1": {
                "steps": [
                    {"id": "rm-step-1", "name": "Draft Milestone Paper", "due": "2026-11-18", "status": "active"}
                ]
            }
        },
        today=date(2026, 11, 13),
    )
    cal_titles = [e.get("title") for e in (reconciled.get("calendar_events_all") or [])]
    assert "Research Advisory Board Call" in cal_titles
    assert "Follow-up: Submit revised budget" not in cal_titles
    assert "Focus Task Block" not in cal_titles
    assert "Draft Milestone Paper" not in cal_titles
    assert not any(str(e.get("id") or "").startswith("rm-") for e in (reconciled.get("calendar_events_all") or []))

    # 2) Seed legacy synthetic marker .ics file on disk and verify atomic idempotent migration before .ics unlink
    cal_dir = isolated_data / ".anchor" / "calendar"
    cal_dir.mkdir(parents=True, exist_ok=True)
    legacy_marker_ics = cal_dir / "legacy-deadline-marker.ics"
    legacy_marker_ics.write_text(
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
        "UID:legacy-deadline-marker\r\nDTSTART:20261119T090000\r\n"
        "SUMMARY:Follow-up: File patent provisional\r\nTRANSP:TRANSPARENT\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n",
        encoding="utf-8",
    )

    mig1 = comms.migrate_calendar_markers_to_watchlist()
    assert mig1["ok"] is True
    assert mig1["migrated_added"] >= 1
    assert not legacy_marker_ics.exists()
    assert real_ics.is_file()

    mig2 = comms.migrate_calendar_markers_to_watchlist()
    assert mig2["ok"] is True
    assert mig2["migrated_added"] == 0
    wl_resp, wl_code = comms.get_watchlist_response(include_done=True)
    assert wl_code == 200
    assert sum(1 for it in wl_resp["items"] if it.get("source_key") == "ics:legacy-deadline-marker") == 1

    # 3) Verify tools/steward_comms.py watchlist-add | watchlist-list | watchlist-done CLI
    capsys.readouterr()
    assert steward_comms.main(["watchlist-add", "--title", "Send referee report", "--due", "2026-11-20"]) == 0
    added_cli = json.loads(capsys.readouterr().out)
    assert added_cli["ok"] is True
    wl_cli_id = added_cli["item"]["id"]

    assert steward_comms.main(["watchlist-list"]) == 0
    listed_cli = json.loads(capsys.readouterr().out)
    assert any(it["id"] == wl_cli_id for it in listed_cli["items"])

    assert steward_comms.main(["watchlist-done", "--id", wl_cli_id]) == 0
    done_cli = json.loads(capsys.readouterr().out)
    assert done_cli["ok"] is True and done_cli["item"]["status"] == "done"


def test_two_process_concurrent_watchlist_migration_and_list_mutation(isolated_data):
    cal_dir = isolated_data / ".anchor" / "calendar"
    cal_dir.mkdir(parents=True, exist_ok=True)
    for idx in range(6):
        (cal_dir / f"conc-marker-{idx}.ics").write_text(
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
            f"UID:conc-marker-{idx}\r\nDTSTART:2026112{idx}T090000\r\n"
            f"SUMMARY:Follow-up: Concurrent deadline {idx}\r\nTRANSP:TRANSPARENT\r\n"
            "END:VEVENT\r\nEND:VCALENDAR\r\n",
            encoding="utf-8",
        )
    comms.save_working_list_spine(comms._default_working_list_state())

    worker_script = textwrap.dedent(
        """
        import sys
        import time
        import comms_connector as comms

        wid = sys.argv[1]
        comms.migrate_calendar_markers_to_watchlist()
        for i in range(12):
            res_w = comms.add_watchlist_item({
                "title": f"Worker {wid} item {i}",
                "due": "2026-11-22",
                "source_key": f"worker:{wid}:{i}",
            })
            assert res_w.get("ok") is True, f"watchlist_add failed: {res_w}"
            res_l = comms.mutate_working_list_spine("propose_change", {
                "proposal_op": "add_tile",
                "title": f"Worker {wid} proposal {i}",
                "source_key": f"prop:{wid}:{i}",
                "priority": 2,
                "category": "Research",
            })
            assert res_l.get("ok") is True, f"propose_change failed: {res_l}"
            time.sleep(0.002)
        """
    )
    child_env = dict(os.environ)
    child_env["ANCHOR_DATA_DIR"] = str(isolated_data)
    child_env["ANCHOR_COMMS_HERMETIC"] = "1"

    procs = [
        subprocess.Popen(
            [sys.executable, "-c", worker_script, f"p{idx}"],
            cwd=str(REPO_ROOT),
            env=child_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for idx in range(2)
    ]
    for p in procs:
        out, err = p.communicate(timeout=25)
        assert p.returncode == 0, f"Concurrent worker failed: {out} {err}"

    for idx in range(6):
        assert not (cal_dir / f"conc-marker-{idx}.ics").exists()

    wl_doc, wl_code = comms.get_watchlist_response(include_done=True)
    assert wl_code == 200
    src_keys = [it["source_key"] for it in wl_doc["items"]]
    for idx in range(6):
        assert src_keys.count(f"ics:conc-marker-{idx}") == 1
    for wid in ("p0", "p1"):
        for i in range(12):
            assert src_keys.count(f"worker:{wid}:{i}") == 1

    spine = comms.load_working_list_spine()
    prop_keys = {p["source_key"] for p in spine["proposals"]}
    assert len(prop_keys) == 24


def test_retired_cos_mockups_and_open_by_default_living_list_ui(isolated_data, monkeypatch):
    core_src = (REPO_ROOT / "high_seat_core.py").read_text(encoding="utf-8")
    js_src = (REPO_ROOT / "static" / "high-seat-page.js").read_text(encoding="utf-8")
    monkeypatch.setattr(
        comms,
        "build_live_cockpits_and_goals_catalogs",
        lambda: {
            "cockpits_dropdown_catalog": [],
            "goals_dropdown_catalog": [],
            "project_folders_catalog": ["Business", "Research", "Teaching"],
        },
    )

    # 1) Retire static #cosExpandableBody & Nov-2 mockup literals while keeping dynamic #shTriage
    assert "cosExpandableBody" not in core_src
    today_d = date.today()
    comms.mutate_working_list_spine("add_tile", {
        "title": "Finalize Quantum Paper Figures",
        "category": "Research",
        "priority": 1,
        "due": today_d.isoformat(),
        "goalName": "Tier 1 Goal: Quantum Paper",
        "steps": [{"id": "st-q1", "text": "Verify Figure 2 curves", "done": False}],
    })
    comms.mutate_working_list_spine("add_tile", {
        "title": "Prepare Lecture Deck",
        "category": "Teaching",
        "priority": 2,
        "due": (today_d + timedelta(days=3)).isoformat(),
        "steps": [{"id": "st-l1", "text": "Update lecture slides", "done": False}],
    })
    comms.add_watchlist_item({
        "title": "Monthly Trust Review",
        "due": (today_d + timedelta(days=15)).isoformat(),
    })

    html = high_seat_page.render_high_seat_html(_minimal_cave_ctx(today=today_d))
    assert "cosExpandableBody" not in html
    assert 'id="shTriage"' in html

    # 2) #caveWorkingListSpine (*The List*) renders collapsed-by-default with top 2-3 items in #theListCompactRow + dynamic horizon counts
    assert 'id="caveWorkingListSpine"' in html
    assert 'id="wlSpineBody" hidden' in html
    assert '<div id="theListCompactRow" class="cos-compact-summary-row"' in html
    assert "Finalize Quantum Paper Figures" in html
    assert "Prepare Lecture Deck" in html
    assert 'id="wlHzToday">1<' in html
    assert 'id="wlHzWeek">1<' in html
    assert 'id="wlHzMonth">1<' in html
    assert 'id="wlHzStarChart">1<' in html

    # 3) Parable-of-the-Oranges skill pre-staging + Open/Create AI Cockpit controls
    for sk in comms.ORANGES_SKILLS:
        assert f'data-wl-prestage-skill="{sk}"' in html
    assert "Open AI Cockpit" in html
    assert "+ Create AI Cockpit" in html

    # 4) Single-open client-ephemeral accordion (_wlExpandedIds clears siblings; balanced <details> tags)
    assert "_wlExpandedIds" in js_src
    assert "_wlExpandedIds.clear()" in js_src
    assert len(re.findall(r"<details\b", html)) == len(re.findall(r"</details>", html))
    saved_spine = json.loads(comms._working_list_path().read_text(encoding="utf-8"))
    assert all(t.get("expanded") is False for t in saved_spine["tiles"])


def test_reconcile_working_list_4_sources_proposals_autocheck_and_remit(isolated_data, capsys):
    now_ref = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
    today_ref = date(2026, 11, 13)

    # Seed 2 tiles on The List
    t1_res = comms.mutate_working_list_spine("add_tile", {
        "title": "Series B Financing",
        "category": "Business",
        "priority": 3,
        "cockpitName": "Financing Cockpit",
        "steps": [
            {"id": "st-fin-1", "text": "Reply to counsel on Series B term sheet", "done": False, "email_uid": "uid-term-1"},
            {"id": "st-fin-2", "text": "Model cap table waterfall", "done": False},
        ],
    })
    t2_res = comms.mutate_working_list_spine("add_tile", {
        "title": "Course Syllabus Refresh",
        "category": "Teaching",
        "priority": 2,
        "cockpitName": "Syllabus Cockpit",
        "steps": [
            {"id": "st-syl-1", "text": "Publish final syllabus PDF", "done": False, "deliverable_id": "deliv-syl-final"},
        ],
    })
    t1_id = t1_res["tile"]["id"]
    t2_id = t2_res["tile"]["id"]

    # Seed Watchlist items: one tied to email reply (Source 2) + three crossing 7d / 48h / 24h windows (Source 4)
    wl_email = comms.add_watchlist_item({
        "title": "Series B term sheet response",
        "due": "2026-11-25",
        "email_uid": "uid-term-1",
    })["item"]
    comms.add_watchlist_item({
        "id": "wl-7d",
        "title": "Series B Financing",
        "tile_id": t1_id,
        "due": (now_ref + timedelta(days=5)).date().isoformat(),
    })
    comms.add_watchlist_item({
        "id": "wl-48h",
        "title": "NSF Panel Review Upload",
        "due": (now_ref + timedelta(hours=36)).isoformat(),
    })
    comms.add_watchlist_item({
        "id": "wl-24h",
        "title": "File Tax Extension Form",
        "due": (now_ref + timedelta(hours=12)).isoformat(),
    })

    # Run 4-source reconcile_working_list_activity
    rec = comms.reconcile_working_list_activity(
        cockpit_events=[
            {
                "kind": "deliverable_final",
                "cockpit_name": "Syllabus Cockpit",
                "deliverable_id": "deliv-syl-final",
                "title": "Publish final syllabus PDF",
            },
            {
                "kind": "deliverable_for_review",
                "cockpit_name": "Financing Cockpit",
                "deliverable_id": "deliv-cap-v1",
                "title": "Cap Table Model v1",
            },
        ],
        sent_event={
            "uid": "uid-term-1",
            "subject": "Re: Series B term sheet",
            "to": "counsel@example.org",
        },
        dispatch_event={
            "uid": "uid-disp-9",
            "subject": "Board Observer Seat Request",
            "from": "Investor <investor@example.com>",
            "comment": "Evaluate observer rights clause",
        },
        important_emails=[
            {
                "uid": "uid-prime-7",
                "from": "Dean Office <dean@example.org>",
                "subject": "Action required: Sign accreditation memo",
                "snippet": "Please sign by Friday.",
                "action_required": True,
                "steward_score": 85,
            }
        ],
        now_dt=now_ref,
        today=today_ref,
    )
    assert rec["ok"] is True and rec["mutated"] is True
    wl_state = rec["working_list"]

    # Source 1 + Source 2 auto-checks recorded in #wlAutoCheckedStrip (`auto_checked`)
    ac_step_ids = {a["step_id"] for a in wl_state["auto_checked"]}
    assert {"st-syl-1", "st-fin-1"} <= ac_step_ids

    # Source 2 also marked matching Watchlist item done
    wl_all, _ = comms.get_watchlist_response(include_done=True)
    matched_wl = next(x for x in wl_all["items"] if x["id"] == wl_email["id"])
    assert matched_wl["status"] == "done"

    # Sources 1, 3, 4 queued deduplicated proposals
    prop_by_key = {p["source_key"]: p for p in wl_state["proposals"]}
    assert prop_by_key["cockpit-review:Financing Cockpit:deliv-cap-v1"]["proposal_op"] == "add_step"
    assert prop_by_key[f"tile-all-steps-done:{t2_id}"]["proposal_op"] == "archive_tile"
    assert prop_by_key["steward-dispatch:uid-disp-9"]["proposal_op"] == "add_tile"
    assert prop_by_key["prime-email:uid-prime-7"]["proposal_op"] == "add_tile"
    assert prop_by_key["watchlist:wl-7d:7d"]["proposal_op"] == "reprioritize"
    assert prop_by_key["watchlist:wl-48h:48h"]["proposal_op"] == "add_tile"
    assert prop_by_key["watchlist:wl-24h:24h"]["proposal_op"] == "add_tile"

    # Repeat invocation with identical inputs does not duplicate any proposal
    rec_repeat = comms.reconcile_working_list_activity(
        dispatch_event={"uid": "uid-disp-9", "subject": "Board Observer Seat Request", "comment": "Evaluate"},
        important_emails=[{"uid": "uid-prime-7", "subject": "Action required: Sign accreditation memo", "action_required": True}],
        now_dt=now_ref,
        today=today_ref,
    )
    assert rec_repeat["added_proposals"] == []

    # Undo auto-check via autocheck_id (`#wlAutoCheckedStrip` ↺ Undo)
    syl_ac_id = next(a["id"] for a in wl_state["auto_checked"] if a["step_id"] == "st-syl-1")
    undo_res, undo_code = comms.handle_working_list_request(
        {"op": "undo_autocheck", "autocheck_id": syl_ac_id},
        method="POST",
    )
    assert undo_code == 200 and undo_res["ok"] is True
    syl_tile = next(t for t in undo_res["working_list"]["tiles"] if t["id"] == t2_id)
    assert syl_tile["steps"][0]["done"] is False

    # CLI list-propose | list-proposals | list-accept | list-dismiss + Edit & Accept All
    capsys.readouterr()
    assert steward_comms.main([
        "list-propose",
        "--op", "add_tile",
        "--title", "Draft Annual Shareholder Letter",
        "--priority", "1",
        "--category", "Business",
        "--reason", "Q4 reporting milestone",
    ]) == 0
    cli_prop = json.loads(capsys.readouterr().out)["proposal"]

    assert steward_comms.main(["list-proposals"]) == 0
    cli_list = json.loads(capsys.readouterr().out)
    assert any(p["id"] == cli_prop["id"] for p in cli_list["proposals"])

    # Dismiss one proposal via CLI and confirm its source_key stays suppressed on subsequent reconcile
    dismiss_id = prop_by_key["prime-email:uid-prime-7"]["id"]
    assert steward_comms.main(["list-dismiss", "--id", dismiss_id]) == 0
    capsys.readouterr()
    rec_after_dismiss = comms.reconcile_working_list_activity(
        important_emails=[{"uid": "uid-prime-7", "subject": "Action required: Sign accreditation memo", "action_required": True}],
        now_dt=now_ref,
        today=today_ref,
    )
    assert not any(p["source_key"] == "prime-email:uid-prime-7" for p in rec_after_dismiss["working_list"]["proposals"])

    # Accept with inline Edit (`✎ Edit` -> `accept_proposal`), CLI `list-accept`, and `accept_all_proposals`
    edit_acc, edit_code = comms.handle_working_list_request(
        {
            "op": "accept_proposal",
            "proposal_id": cli_prop["id"],
            "edits": {"title": "Draft 2026 Shareholder Letter (Edited)", "priority": 1},
        },
        method="POST",
    )
    assert edit_code == 200 and edit_acc["tile"]["title"] == "Draft 2026 Shareholder Letter (Edited)"

    disp_prop_id = prop_by_key["steward-dispatch:uid-disp-9"]["id"]
    assert steward_comms.main(["list-accept", "--id", disp_prop_id]) == 0
    capsys.readouterr()

    # Cave Steward capsule & remit reflect live List, pending proposals, and Watchlist counts
    capsule = steward_engine._list_state_capsule()
    remit = steward_engine.cave_mode_remit("Ecgberht")
    assert "[CAVE LIVING LIST & WATCHLIST CAPSULE]" in capsule
    assert "Draft 2026 Shareholder Letter (Edited)" in capsule
    assert "#wlProposalTray" in capsule
    assert "Steward Watchlist" in capsule
    assert "PROACTIVE 2–3 LINE CAVE CHECK-INS" in remit
    assert capsule in remit

    # Accept All clears remaining proposals cleanly; also verify <=50 proposal cap refusal
    acc_all, acc_all_code = comms.handle_working_list_request({"op": "accept_all_proposals"}, method="POST")
    assert acc_all_code == 200 and acc_all["working_list"]["proposals"] == []

    for i in range(comms.MAX_WORKING_LIST_PROPOSALS):
        r_p = comms.mutate_working_list_spine("propose_change", {
            "proposal_op": "add_tile",
            "title": f"Bounded proposal {i}",
            "source_key": f"cap-test:{i}",
        })
        assert r_p["ok"] is True
    cap_refused = comms.mutate_working_list_spine("propose_change", {
        "proposal_op": "add_tile",
        "title": "Proposal 51 over cap",
        "source_key": "cap-test:overflow",
    })
    assert cap_refused["ok"] is False
    assert cap_refused["status_code"] == 400
    assert cap_refused["message"] == "Invalid recipient or proposal payload rejected"


def test_wave2_five_state_failure_contract_and_distro_cleanliness(isolated_data, monkeypatch):
    # Verify canonical 2.0s lock timeout constant
    assert comms.STORE_LOCK_TIMEOUT_SEC == 2.0

    # State 5: `empty-but-valid` -> HTTP 200 distinct empty messages
    empty_wl, code_empty_wl = comms.handle_working_list_request(method="GET")
    assert code_empty_wl == 200 and empty_wl["ok"] is True
    assert empty_wl["state"] == "empty"
    assert empty_wl["message"] == "The List is clear (0 active items)"

    empty_watch, code_empty_watch = comms.get_watchlist_response()
    assert code_empty_watch == 200 and empty_watch["ok"] is True
    assert empty_watch["state"] == "empty"
    assert empty_watch["message"] == "No Watchlist deadlines due"

    # State 3: `dependency-returns-garbage` -> HTTP 400
    bad_mut, code_bad_mut = comms.handle_working_list_request({"op": "nonexistent_op"}, method="POST")
    assert code_bad_mut == 400 and bad_mut["ok"] is False
    assert bad_mut["message"] == "Invalid recipient or proposal payload rejected"

    # State 1: `dependency-missing` -> HTTP 503
    monkeypatch.setattr(comms, "_CAVE_STEWARD_DISPATCH_HOOK", lambda _d: None)
    miss_res, code_miss = comms.handle_comms_post({
        "action": "email_steward_action",
        "uid": "u-miss",
        "subject": "Ping",
        "comment": "Review this",
    })
    assert code_miss == 503 and miss_res["ok"] is False
    assert miss_res["message"] == "Cave Steward engine unavailable — message queued safely"

    # State 2: `dependency-slow-or-killed` -> HTTP 504 when cross_process_lock is held by another process
    lock_holder = textwrap.dedent(
        """
        import sys
        import time
        from pathlib import Path
        import paths

        lp = Path(sys.argv[1])
        ready = Path(sys.argv[2])
        with paths.cross_process_lock(lp, timeout_sec=2.0):
            ready.write_text("locked", encoding="utf-8")
            time.sleep(1.5)
        """
    )
    ready_flag = isolated_data / "holder.ready"
    holder_proc = subprocess.Popen(
        [sys.executable, "-c", lock_holder, str(comms._working_list_lock_path()), str(ready_flag)],
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = datetime.now(timezone.utc) + timedelta(seconds=5)
        while not ready_flag.exists() and datetime.now(timezone.utc) < deadline:
            pass
        assert ready_flag.exists()
        monkeypatch.setattr(comms, "STORE_LOCK_TIMEOUT_SEC", 0.12)
        busy_res, code_busy = comms.handle_working_list_request(method="GET")
        assert code_busy == 504 and busy_res["ok"] is False
        assert busy_res["message"] == "List/Watchlist lock busy (>2.0s) — retry"
    finally:
        holder_proc.communicate(timeout=10)

    # State 4: `backing-store-unreadable` -> HTTP 500 `unknown != empty` + preserves corrupt bytes untouched
    corrupt_bytes = "{corrupt-working-list-json"
    wl_path = comms._working_list_path()
    wl_path.write_text(corrupt_bytes, encoding="utf-8")

    unk_res, code_unk = comms.handle_working_list_request(method="GET")
    assert code_unk == 500 and unk_res["ok"] is False
    assert unk_res["state"] == "unknown"
    assert unk_res["message"] == "The List / Watchlist unreadable (unknown) — inspect Doctor"
    assert wl_path.read_text(encoding="utf-8") == corrupt_bytes

    capsule_unk = steward_engine._list_state_capsule()
    assert "UNKNOWN" in capsule_unk
    assert "0 active items" not in capsule_unk

    cave_unk_html = high_seat_page.render_high_seat_html(_minimal_cave_ctx())
    assert "The List / Watchlist unreadable (unknown) — inspect Doctor" in cave_unk_html
    assert "The List is clear (0 active items)" not in cave_unk_html

    # Distro & hygiene scan across shippable Wave 2 files + zero hardcoded contact/lexicon PII in comms_connector
    assert comms._KNOWN_CONTACT_EMAILS == {}
    assert comms._PROPER_NAME_LEXICON == {}
    shippable_w2 = (
        "high_seat_page.py",
        "high_seat_core.py",
        "static/high-seat-page.js",
        "static/high-seat-page.css",
        "tools/steward_comms.py",
        "steward_cockpit/steward_engine.py",
        "tests/test_w2_cave_email_list_overhaul_2026_11_13.py",
    )
    hits = []
    for rel in shippable_w2:
        txt = (REPO_ROOT / rel).read_text(encoding="utf-8")
        hits.extend(distro._scan_text(rel, txt))
        hits.extend(distro._scan_registry_artifact(rel, txt))
    assert hits == [], f"Unexpected distro PII/secret/host-path hits in Wave 2 files: {hits}"
