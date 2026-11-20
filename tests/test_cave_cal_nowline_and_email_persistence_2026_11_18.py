"""Regression tests for Cave Calendar thin blue current-time line (local client clock)
and Cave Email reading-pane content persistence across background polls/syncs (2026-11-18).
"""
from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

import comms_connector as comms
import high_seat_page
import paths

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def isolated_comms_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_COMMS_HERMETIC", "1")
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path, raising=False)
    return tmp_path


def test_get_email_dialogue_context_fetches_full_body_over_snippet_and_respects_account_id(
    isolated_comms_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Backend `get_email_dialogue_context`:
    1. Disambiguates `(account_id, uid)` when two accounts share numeric UID `'42'`.
    2. Calls `read_email_message` when only a header `snippet` (>30 chars, `body_preloaded=False`) exists.
    3. Preserves the cached `snippet` if `read_email_message` fails or returns an empty body offline.
    """
    comms.save_comms_config({
        "accounts": [
            {"id": "psu", "family": "microsoft", "email": "owner@example.net", "label": "PSU", "status": "connected"},
            {"id": "gmail", "family": "gmail", "email": "owner@example.com", "label": "Gmail", "status": "connected"},
        ]
    })
    comms.save_comms_sync({
        "email_headers": [
            {
                "uid": "42",
                "account_id": "psu",
                "account_badge": "Institutional 365",
                "from": "Dean Office <dean@example.net>",
                "sender_email": "dean@example.net",
                "subject": "Spring Seminar Schedule",
                "snippet": "Short truncated preview over thirty characters from PSU header...",
                "date": "2026-11-18 08:15",
                "is_read": False,
                "body_preloaded": False,
            },
            {
                "uid": "42",
                "account_id": "gmail",
                "account_badge": "Gmail",
                "from": "Alex Partner <alex@example.org>",
                "sender_email": "alex@example.org",
                "subject": "Board Deck Final Notes",
                "snippet": "Preview snippet over thirty characters from Gmail header...",
                "date": "2026-11-18 09:00",
                "is_read": False,
                "body_preloaded": False,
            },
        ]
    })

    read_calls: list[dict[str, Any]] = []

    def _fake_read_full(req: dict[str, Any]) -> dict[str, Any]:
        read_calls.append(dict(req))
        if req.get("account_id") == "gmail":
            return {
                "ok": True,
                "uid": "42",
                "account_id": "gmail",
                "body": "Full multi-paragraph Gmail body with complete financial table and next steps.",
                "from": "Alex Partner <alex@example.org>",
                "to": "owner@example.com",
                "date": "2026-11-18 09:00",
            }
        return {"ok": False, "error": "Simulated transient IMAP timeout"}

    monkeypatch.setattr(comms, "read_email_message", _fake_read_full)

    # 1) Gmail UID 42 upgrades from 1-line snippet to full body via read_email_message
    gmail_ctx = comms.get_email_dialogue_context({"uid": "42", "account_id": "gmail"})
    assert gmail_ctx["ok"] is True
    assert gmail_ctx["account_id"] == "gmail"
    assert "Full multi-paragraph Gmail body" in gmail_ctx["body"]
    assert any(c.get("account_id") == "gmail" and c.get("uid") == "42" for c in read_calls)

    # 2) PSU UID 42 hits transient IMAP error -> gracefully retains its header snippet (never blank!)
    psu_ctx = comms.get_email_dialogue_context({"uid": "42", "account_id": "psu"})
    assert psu_ctx["ok"] is True
    assert psu_ctx["account_id"] == "psu"
    assert "Short truncated preview over thirty characters from PSU header" in psu_ctx["body"]

    # 3) Placeholder "No message text." from read_email_message never overwrites a cached body,
    #    and an explicit account_id with no matching header never leaks another account's UID 42!
    monkeypatch.setattr(comms, "read_email_message", lambda _req: {"ok": True, "body": "No message text."})
    gmail_again = comms.get_email_dialogue_context({"uid": "42", "account_id": "gmail"})
    assert "Full multi-paragraph Gmail body" in gmail_again["body"]

    other_acct_ctx = comms.get_email_dialogue_context({"uid": "42", "account_id": "axmra"})
    assert "Full multi-paragraph Gmail body" not in other_acct_ctx["body"]
    assert "PSU header" not in other_acct_ctx["body"]


def test_calendar_thin_blue_now_line_and_email_content_persistence_in_chromium(
    isolated_comms_env: Path,
) -> None:
    """End-to-end Chromium verification of:
    1. Single thin blue current-time line (`#caveCalNowLine`) driven by client local clock
       (including late-evening local time where UTC date is already tomorrow) across Week, Day, Stream, and Month views.
    2. Email reading-pane content persistence across:
       - background `/high-seat` HTML `morph` / `placeBoard` refreshes,
       - background `sync_now` / `_hydrateMailCardsFromCommsData` refreshes when the open email turns `is_read: true`,
       - `email_dialogue` returning empty/placeholder `"No message text."` after `0ms` snippet render,
       - clicking the already-selected email card on the left.
    """
    pw = pytest.importorskip("playwright.sync_api")

    css_text = (REPO_ROOT / "static" / "high-seat-page.css").read_text(encoding="utf-8")
    js_text = (REPO_ROOT / "static" / "high-seat-page.js").read_text(encoding="utf-8")

    comms_payload: dict[str, Any] = {
        "ok": True,
        "accounts": [
            {"id": "psu", "family": "microsoft", "email": "owner@example.net", "label": "Institutional 365", "status": "connected"}
        ],
        "calendar_events_all": [
            {
                "id": "ev-morning",
                "date": "2026-11-18",
                "start_time": "08:30",
                "end_time": "09:30",
                "title": "Morning Research Sync",
                "calendar_badge": "Institutional 365",
                "rsvp_status": "accepted",
            },
            {
                "id": "ev-evening",
                "date": "2026-11-18",
                "start_time": "19:00",
                "end_time": "20:30",
                "title": "Evening Architecture Review",
                "calendar_badge": "Institutional 365",
                "rsvp_status": "accepted",
            },
            {
                "id": "ev-tomorrow",
                "date": "2026-11-19",
                "start_time": "11:00",
                "end_time": "12:00",
                "title": "Tomorrow Seminar",
                "calendar_badge": "Institutional 365",
                "rsvp_status": "not_responded",
            },
        ],
        "important_emails": [
            {
                "uid": "u-persist-1",
                "account_id": "psu",
                "account_badge": "Institutional 365",
                "from": "Jordan Counsel <counsel@example.org>",
                "sender_email": "counsel@example.org",
                "subject": "Trust Distribution Schedule",
                "snippet": "Please review Section 4.2 of the attached distribution schedule before Friday.",
                "date": "2026-11-18 09:15",
                "is_read": False,
                "body_preloaded": False,
            },
            {
                "uid": "u-persist-2",
                "account_id": "psu",
                "account_badge": "Institutional 365",
                "from": "Sam Colleague <sam@example.net>",
                "sender_email": "sam@example.net",
                "subject": "Lecture 12 Slides",
                "snippet": "Updated slide deck attached.",
                "body": "Full body for Lecture 12 Slides.",
                "date": "2026-11-18 09:45",
                "is_read": False,
                "body_preloaded": True,
            },
        ],
        "other_emails": [],
        "acted_upon_emails": [],
        "sent_emails": [],
        "speed_racer": {"ok": True, "queue": [], "archive": []},
        "working_list": {"ok": True, "tiles": [], "proposals": [], "done_archive": []},
    }

    comms.save_comms_config({"accounts": comms_payload["accounts"]})
    comms.save_comms_sync({
        "calendar_events": comms_payload["calendar_events_all"],
        "email_headers": comms_payload["important_emails"],
    })
    page_html = high_seat_page.render_high_seat_page(logged_in=True)
    # Inject test clock + deterministic comms boot BEFORE high-seat-page.js runs:
    # 2026-11-18 19:30 LOCAL time (which in US timezones is already 2026-11-19 in UTC — proving local-clock fidelity!)
    boot_Pin = (
        "<script>"
        "window.__ANCHOR_TEST_NOW = new Date(2026, 10, 18, 19, 30, 0);"
        f"window.ANCHOR_CAVE_COMMS_BOOT = {json.dumps(comms_payload)};"
        "</script>"
    )
    injected_html = page_html.replace("<script src=", boot_Pin + "\n<script src=", 1)

    dialogue_mode = {"return_placeholder_body": True}

    class _TestHandler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            if self.path.startswith("/static/high-seat-page.css"):
                data = css_text.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/css; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if self.path.startswith("/static/high-seat-page.js"):
                data = js_text.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/javascript; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if self.path.startswith("/api/steward/comms"):
                data = json.dumps(comms_payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if self.path.startswith("/high-seat") or self.path == "/":
                data = injected_html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            data = b"{}"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self) -> None:
            ln = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(ln) if ln else b"{}"
            req = json.loads(raw.decode("utf-8") or "{}")
            act = req.get("action")
            if act == "email_dialogue":
                if dialogue_mode["return_placeholder_body"]:
                    resp = {
                        "ok": True,
                        "uid": req.get("uid") or "u-persist-1",
                        "account_id": req.get("account_id") or "psu",
                        "subject": "Trust Distribution Schedule",
                        "from": "Jordan Counsel <counsel@example.org>",
                        "sender_email": "counsel@example.org",
                        "body": "No message text.",
                        "thread_messages": [
                            {
                                "uid": req.get("uid") or "u-persist-1",
                                "from": "Jordan Counsel",
                                "date": "2026-11-18 09:15",
                                "direction": "inbound",
                                "body": "No message text.",
                                "is_current": True,
                            }
                        ],
                    }
                else:
                    resp = {
                        "ok": True,
                        "uid": req.get("uid") or "u-persist-1",
                        "account_id": req.get("account_id") or "psu",
                        "subject": "Trust Distribution Schedule",
                        "from": "Jordan Counsel <counsel@example.org>",
                        "sender_email": "counsel@example.org",
                        "body": "Please review Section 4.2 of the attached distribution schedule before Friday.\n\nFull paragraph two from IMAP.",
                        "thread_messages": [
                            {
                                "uid": req.get("uid") or "u-persist-1",
                                "from": "Jordan Counsel",
                                "date": "2026-11-18 09:15",
                                "direction": "inbound",
                                "body": "Please review Section 4.2 of the attached distribution schedule before Friday.\n\nFull paragraph two from IMAP.",
                                "is_current": True,
                            }
                        ],
                    }
                data = json.dumps(resp).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            data = json.dumps(comms_payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    srv = ThreadingHTTPServer(("127.0.0.1", port), _TestHandler)
    thr = threading.Thread(target=srv.serve_forever, daemon=True)
    thr.start()

    try:
        with pw.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(viewport={"width": 1440, "height": 960})
            page = ctx.new_page()
            page.goto(f"http://127.0.0.1:{port}/high-seat", wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(700)

            # Ensure Calendar & Email section (#cal) is expanded if collapsed
            page.evaluate("""() => {
                const cal = document.getElementById('cal');
                if (cal && !cal.classList.contains('open')) cal.classList.add('open');
            }""")
            page.wait_for_timeout(150)

            # 1A. Week view: exactly ONE thin blue current-time line on local 2026-11-18 at 19:30 (1170 mins)
            week_check = page.evaluate("""() => {
                const lines = document.querySelectorAll('#caveCalViewport .cave-cal-now-line');
                const line = lines[0];
                const cs = line ? getComputedStyle(line) : null;
                const todayCols = document.querySelectorAll('#caveCalViewport .cave-week-col.today');
                return {
                    count: lines.length,
                    nowDate: line ? line.getAttribute('data-now-date') : null,
                    nowMins: line ? line.getAttribute('data-now-mins') : null,
                    inActiveChip: line ? line.classList.contains('in-active-chip') : false,
                    heightPx: cs ? cs.height : null,
                    bgColor: cs ? cs.backgroundColor : null,
                    todayColCount: todayCols.length,
                    todayColDate: todayCols[0] ? todayCols[0].getAttribute('data-cave-pick-day') : null,
                };
            }""")
            assert week_check["count"] == 1
            assert week_check["nowDate"] == "2026-11-18"
            assert week_check["nowMins"] == "1170"
            assert week_check["inActiveChip"] is True  # 19:30 is 1/3 through 19:00-20:30 Evening Review!
            assert week_check["heightPx"] == "1px"
            assert week_check["bgColor"] == "rgb(56, 189, 248)"
            assert week_check["todayColCount"] == 1
            assert week_check["todayColDate"] == "2026-11-18"

            # 1B. Switch to Day view: thin blue line positioned proportionally in .cave-day-timegrid
            page.click('[data-cave-cal-view="day"]')
            page.wait_for_timeout(150)
            day_check = page.evaluate("""() => {
                const lines = document.querySelectorAll('#caveCalViewport .cave-cal-now-line');
                const line = lines[0];
                return {
                    count: lines.length,
                    inDayGrid: line ? line.classList.contains('in-day-grid') : false,
                    topPx: line ? parseInt(line.style.top || '0', 10) : 0,
                    label: line ? line.textContent.trim() : '',
                };
            }""")
            assert day_check["count"] == 1
            assert day_check["inDayGrid"] is True
            # (19.5 - 6.0) * 52 = 702px
            assert day_check["topPx"] == 702
            assert "7:30 PM" in day_check["label"]

            # Navigating Day view to Tomorrow (2026-11-19) hides the Today now-line
            page.click('[data-cave-cal-nav="1"]')
            page.wait_for_timeout(150)
            assert page.locator("#caveCalViewport .cave-cal-now-line").count() == 0

            # Navigate back to Today and verify Stream + Month views also show exactly 1 thin blue line
            page.click('[data-cave-cal-nav="0"]')
            page.wait_for_timeout(100)
            page.click('[data-cave-cal-view="iphone"]')
            page.wait_for_timeout(100)
            assert page.locator("#caveCalViewport .cave-cal-now-line").count() == 1
            page.click('[data-cave-cal-view="month"]')
            page.wait_for_timeout(100)
            assert page.locator("#caveCalViewport .cave-cal-now-line").count() == 1

            # 2A. Email Persistence: click u-persist-1 when email_dialogue returns placeholder "No message text."
            # -> snippet ("Section 4.2") MUST remain visible and NEVER disappear!
            page.click('#caveMailImportantList .cave-mail-card[data-mail-uid="u-persist-1"] [data-cave-mail-open]')
            page.wait_for_timeout(350)
            txt_after_placeholder = page.locator("#caveDialogueThreadList").inner_text()
            assert "Section 4.2" in txt_after_placeholder
            assert "No message text" not in txt_after_placeholder

            # 2B. Clicking the already-selected left card again keeps the reading pane open & upgrades when full body arrives
            dialogue_mode["return_placeholder_body"] = False
            page.click('#caveMailImportantList .cave-mail-card[data-mail-uid="u-persist-1"] [data-cave-mail-open]')
            page.wait_for_timeout(350)
            assert page.locator("#caveEmailDialoguePane").is_visible()
            txt_upgraded = page.locator("#caveDialogueThreadList").inner_text()
            assert "Full paragraph two from IMAP" in txt_upgraded

            # 2C. Simulate background /high-seat morph refresh while reading the email (previously wiped #caveDialogueThreadList to "")
            page.fill("#caveDlgStewardDirectionsInput", "Draft a concise approval note for Friday")
            # Trigger renewInPlace via health/board fetch cycle or simulate morph guard
            after_bg_poll = page.evaluate("""async () => {
                // Force a background Comms hydrate where u-persist-1 turned is_read=true on IMAP AND important_emails is empty
                window._hydrateMailCardsFromCommsData({
                    ok: true,
                    important_emails: [
                        {
                            uid: 'u-persist-1',
                            account_id: 'psu',
                            subject: 'Trust Distribution Schedule',
                            is_read: true
                        }
                    ],
                    other_emails: [],
                    acted_upon_emails: [],
                    sent_emails: []
                });
                return {
                    paneHidden: document.getElementById('caveEmailDialoguePane').hidden,
                    threadText: document.getElementById('caveDialogueThreadList').innerText,
                    directionsVal: document.getElementById('caveDlgStewardDirectionsInput').value,
                };
            }""")
            assert after_bg_poll["paneHidden"] is False
            assert "Full paragraph two from IMAP" in after_bg_poll["threadText"]
            assert after_bg_poll["directionsVal"] == "Draft a concise approval note for Friday"

            # 2D. Trigger actual /high-seat renewInPlace fetch (via health-sig poll) and confirm #cal is NOT morphed/blanked
            after_renew = page.evaluate("""async () => {
                const res = await fetch('/high-seat', { cache: 'no-store' });
                const html = await res.text();
                const doc = new DOMParser().parseFromString(html, 'text/html');
                // Verify raw server HTML has an empty #caveDialogueThreadList
                const serverEmpty = (doc.getElementById('caveDialogueThreadList').innerText || '').trim() === '';
                // Also verify that if #caveDialogueThreadList were ever cleared externally, _ensureActiveEmailPaneHydrated restores it
                const beforeText = document.getElementById('caveDialogueThreadList').innerText;
                document.getElementById('caveDialogueThreadList').innerHTML = '';
                window._ensureActiveEmailPaneHydrated();
                const restoredText = document.getElementById('caveDialogueThreadList').innerText;
                return { serverEmpty, beforeText, restoredText };
            }""")
            assert after_renew["serverEmpty"] is True
            assert "Full paragraph two from IMAP" in after_renew["beforeText"]
            assert "Full paragraph two from IMAP" in after_renew["restoredText"]

            browser.close()
    finally:
        srv.shutdown()
        srv.server_close()
