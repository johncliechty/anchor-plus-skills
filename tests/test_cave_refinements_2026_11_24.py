"""Regression tests for the 5 Cave of Wonders Tidy Refinements (2026-11-24):
1. Left-panel subscription card turns RED (.is-error / .ec-dot.error / .ec-mode.is-error) when disconnected/unready (e.g., Grok).
2. AI Cockpits summary tile (#caveCockpitsTile) shows Active, On Deck, and In Reserve counts, is CLOSED by default,
   and expands on click to reveal Active (#shActive), On Deck (#shDeck), and the expandable In Reserve bar (#candsTile).
3. Open Email/Calendar section (#cal) summarizes Email & Calendar service status in an expandable Services bar (#caveCommsServicesBar).
4. Unused Seeds bar/panel (#seedBtn / #seedPanel) is removed cleanly with zero console errors.
5. Upper-right Light vs. Dark toggle (#caveThemeToggle beside .mh-stew) switches to the Skill Foundry light color scheme
   (#f8fafc app bg, #ffffff cards/rail, #0f172a ink) and persists across reloads.
"""
from __future__ import annotations

from datetime import date
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import high_seat_page as hsp  # noqa: E402


def _sample_ctx() -> dict:
    steps = [
        {
            "id": "g1",
            "name": "Foundational Architecture",
            "status": "active",
            "tier": 1,
            "navigation": {"groups": [{"id": "g1", "parent_id": None}]},
        },
        {
            "id": "s-act",
            "name": "Alpha Cockpit",
            "status": "active",
            "seat": "active",
            "seat_order": 0,
            "ref": "project:p-alpha",
            "navigation": {"path": ["g1"]},
        },
        {
            "id": "s-deck",
            "name": "Beta Cockpit",
            "status": "active",
            "seat": "deck",
            "seat_order": 0,
            "ref": "project:p-beta",
            "navigation": {"path": ["g1"]},
        },
        {
            "id": "s-res",
            "name": "Gamma Reserve Cockpit",
            "status": "planned",
            "ref": "project:p-gamma",
            "navigation": {"path": ["g1"]},
        },
    ]
    resolved = {
        "s-act": {"kind": "project", "pid": "p-alpha", "name": "Alpha Cockpit"},
        "s-deck": {"kind": "project", "pid": "p-beta", "name": "Beta Cockpit"},
        "s-res": {"kind": "project", "pid": "p-gamma", "name": "Gamma Reserve Cockpit"},
    }
    inits = hsp.campaign_initiatives(steps, resolved)
    entries = [
        {"id": "p-alpha", "name": "Alpha Cockpit", "folder_path": "/workspace/alpha", "group": "Research"},
        {"id": "p-beta", "name": "Beta Cockpit", "folder_path": "/workspace/beta", "group": "Research"},
        {"id": "p-gamma", "name": "Gamma Reserve Cockpit", "folder_path": "/workspace/gamma", "group": "Research"},
        {"id": "p-loose", "name": "Delta Loose Cockpit", "folder_path": "/workspace/delta", "group": "Research"},
    ]
    facts = {
        "p-alpha": {"name": "Alpha Cockpit", "has_record": True, "efforts": [{"rel": "", "name": "Alpha Cockpit"}]},
        "p-beta": {"name": "Beta Cockpit", "has_record": True, "efforts": [{"rel": "", "name": "Beta Cockpit"}]},
        "p-gamma": {"name": "Gamma Reserve Cockpit", "has_record": True, "efforts": [{"rel": "", "name": "Gamma Reserve Cockpit"}]},
        "p-loose": {"name": "Delta Loose Cockpit", "has_record": True, "efforts": [{"rel": "", "name": "Delta Loose Cockpit"}]},
    }
    comms = {
        "accounts": [
            {
                "id": "acc-gmail",
                "family": "gmail",
                "label": "Primary Mail & Calendar",
                "email": "user@example.com",
                "status": "connected",
                "auth_mode": "app_password",
                "ics_url": "https://calendar.example.com/basic.ics",
            },
            {
                "id": "acc-outlook",
                "family": "outlook",
                "label": "Work Outlook & Calendar",
                "email": "work@example.org",
                "status": "auth_error",
                "auth_mode": "oauth_token",
                "ics_url": "",
            },
        ],
        "poller": {"interval_sec": 300},
        "calendar_events": [],
        "important_emails": [],
        "other_emails": [],
        "sent_emails": [],
        "acted_emails": [],
        "threads": [],
    }
    return {
        "build": "testbuild20261124",
        "today": date(2026, 11, 24),
        "today_str": "Tuesday, Nov 24",
        "week": "Nov 23 – Nov 29",
        "week_short": "0 due",
        "steward": {
            "id": "aladdin",
            "label": "Aladdin",
            "high_seat_name": "Cave of Wonders",
            "high_seat": "aladdin-cave-of-wonders.jpg",
            "campaign_icon": "campaign-aladdin-star-chart.jpg",
        },
        "campaign": {"pid": "camp-1"},
        "initiatives": inits,
        "entries": entries,
        "facts": facts,
        "groups": {"Research": entries},
        "projects_html": "",
        "comms": comms,
        "_resolved_comms": comms,
        "auth_required": False,
        "logged_in": True,
    }


def test_server_html_cockpits_tile_services_bar_no_seeds_and_theme_toggle():
    html = hsp.render_high_seat_html(_sample_ctx())

    # 1. Seeds bar & panel are completely removed from Cave of Wonders
    assert 'id="seedBtn"' not in html
    assert 'id="seedPanel"' not in html
    assert 'class="seedbar"' not in html

    # 2. Upper-right Light vs Dark toggle sits right next to .mh-stew in .masthead
    mh = html[html.index('<div class="masthead">'):html.index('<div class="hdr">')]
    assert 'class="mh-stew"' in mh
    assert 'id="caveThemeToggle"' in mh
    assert mh.index('class="mh-stew"') < mh.index('id="caveThemeToggle"')
    assert "/static/cave-foundry-light.css" in html
    assert "/static/cave-tidy-controls.js" in html

    # 3. AI Cockpits tile has Active (1), On Deck (1), In Reserve (2), closed by default, wrapping shelves + In Reserve
    assert 'id="caveCockpitsTile"' in html
    assert 'id="caveCockpitsToggle"' in html and 'aria-expanded="false"' in html
    assert '<b id="ckCntActive">1</b> Active' in html
    assert '<b id="ckCntDeck">1</b> On Deck' in html
    assert '<b id="ckCntReserve">2</b> In Reserve' in html
    assert 'id="caveCockpitsBody" hidden' in html
    assert (
        html.index('id="camp"')
        < html.index('id="caveCockpitsTile"')
        < html.index('id="shActive"')
        < html.index('id="shDeck"')
        < html.index('id="shCands"')
        < html.index('id="ptile"')
    )
    assert '<h3>In Reserve</h3>' in html

    # 4. Email & Calendar expandable Services status bar inside #calBody
    assert 'id="caveCommsServicesBar"' in html
    assert '1/2 Connected' in html
    assert 'Primary Mail &amp; Calendar' in html
    assert 'Work Outlook &amp; Calendar' in html
    assert 'Email: Connected' in html
    assert 'Email: Needs Sign-In' in html

    # 5. Projects tile (#ptile) folder presentation + archived projects render without NameError
    import anchor_gui as ag
    ctx0 = _sample_ctx()
    archived_sample = [{"id": "p-arch", "name": "Archived Legacy Cockpit", "state": "archived", "folder_path": "/workspace/arch"}]
    ptile_html = ag._high_seat_projects_html(ctx0["groups"], ctx0["facts"], inactive=archived_sample)
    assert "could not be rendered" not in ptile_html
    assert 'class="rnd-folder rnd-collapsed"' in ptile_html
    assert 'data-group="Research"' in ptile_html
    assert 'data-open-folder-wizard="folder"' in ptile_html
    assert 'id="ptileArchived"' in ptile_html
    assert 'id="apAddFolder"' in html

    # Also exercise handle_high_seat_projects directly under Python 3.12+/3.13 PEP-709 scoping
    captured = {}

    class _DummyH:
        headers = {}

        def _send_json(self, data, code=200):
            captured["code"] = code
            captured["data"] = data

    ag.handle_high_seat_projects(_DummyH(), "/api/high-seat/projects", None)
    assert captured.get("code") == 200
    assert captured["data"]["ok"] is True
    assert 'class="rnd-folder-list"' in captured["data"]["html"]


def test_disconnected_provider_rules_and_foundry_light_tokens_present():
    pc_js = (ROOT / "static" / "provider-controls.js").read_text(encoding="utf-8")
    ps_css = (ROOT / "static" / "provider-setup.css").read_text(encoding="utf-8")
    light_css = (ROOT / "static" / "cave-foundry-light.css").read_text(encoding="utf-8")

    # Grok / disconnected subscription turns red (.is-error, .ec-dot.error, .ec-mode.is-error), never green via mon.connected alone
    assert "mon.connected" not in pc_js.split("const isReady =")[1].split(";")[0]
    assert "isDisconnected?' is-error':''" in pc_js
    assert "isReady ? 'active' : 'error'" in pc_js
    assert ".cave-account-summary.is-error" in ps_css
    assert ".cave-account-summary .ec-dot.error" in ps_css
    assert ".cave-account-summary .ec-mode.is-error" in ps_css

    # Skill Foundry Light Mode exact color tokens (#f8fafc, #ffffff, #f1f5f9, #0f172a, #cbd5e1, #1d4ed8)
    for tok in ("#f8fafc", "#ffffff", "#f1f5f9", "#0f172a", "#cbd5e1", "#1d4ed8"):
        assert tok in light_css


def test_playwright_cave_five_refinements_e2e(tmp_path):
    pw = pytest.importorskip("playwright.sync_api")
    html = hsp.render_high_seat_html(_sample_ctx())

    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import json
    import threading

    fake_provider_setup = {
        "ok": True,
        "settings_revision": 1,
        "default_family": "claude",
        "coding_family": "claude",
        "review_family": "gemini",
        "preferences": {
            "family": "claude",
            "accounts": {
                "claude": "claude-default",
                "chatgpt": "chatgpt-default",
                "gemini": "gemini-default",
                "grok": "grok-default",
            },
            "quality": {
                "claude": {"model": "latest_supported", "effort": "highest_supported"},
                "chatgpt": {"model": "latest_supported", "effort": "highest_supported"},
                "gemini": {"model": "latest_supported", "effort": "highest_supported"},
                "grok": {"model": "latest_supported", "effort": "highest_supported"},
            },
        },
        "connections": [
            {
                "id": "claude-default",
                "family": "claude",
                "name": "Existing native sign-in",
                "mode": "subscription",
                "native_default": True,
                "auth": "signed_in",
                "test": "passed",
                "execution": {"ready": True},
                "allowance": {"state": "reported", "windows": [{"label": "5h", "remaining_percent": 92}]},
                "catalog": {"state": "fresh", "selection": {"model": "claude-fable-5-2", "effort": "max"}, "rows": []},
                "anchor_observed": {"tokens": 1200, "state": "observed"},
                "api_spend": {"state": "n/a"},
                "capacity": "usable",
            },
            {
                "id": "grok-default",
                "family": "grok",
                "name": "Existing native sign-in",
                "mode": "subscription",
                "native_default": True,
                "auth": "unsupported",
                "test": "failed",
                "execution": {"ready": False},
                "allowance": {"state": "unavailable", "windows": []},
                "catalog": {"state": "unavailable", "selection": None, "rows": []},
                "anchor_observed": {"tokens": 0, "state": "observed"},
                "api_spend": {"state": "n/a"},
                "capacity": "unavailable",
            },
        ],
        "logged_in_services": {
            "ai_providers": [
                {"family": "claude", "signed_in_or_ready": True, "effective_ready": True},
                {"family": "grok", "signed_in_or_ready": False, "effective_ready": False},
            ],
            "comms_accounts": [],
        },
        "usage_summary": {
            "windows": {
                "7d": {"hypothetical_usd": 12.5, "total_tokens": 50000, "by_family": {}},
                "30d": {"hypothetical_usd": 45.0, "total_tokens": 200000, "by_family": {}},
            },
            "allowance_monitor": {
                "families": {
                    "claude": {"connected": True, "short_allowance": "92% left"},
                    "grok": {"connected": True, "short_allowance": "CLI Ready"},
                }
            },
        },
    }

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def do_GET(self):
            clean = self.path.split("?", 1)[0]
            if clean in ("/", "/high-seat"):
                body = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if clean == "/api/provider-setup":
                body = json.dumps(fake_provider_setup).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
                return
            if clean == "/api/high-seat/projects":
                import anchor_gui as ag
                c0 = _sample_ctx()
                phtml = ag._high_seat_projects_html(c0["groups"], c0["facts"], inactive=[])
                body = json.dumps({"ok": True, "html": phtml}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
                return
            if clean == "/api/rnd/dir_browse":
                body = json.dumps({"ok": True, "result": {"roots": [str(tmp_path)], "path": str(tmp_path), "dirs": []}}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
                return
            if clean.startswith("/api/"):
                body = json.dumps({"ok": True, "accounts": _sample_ctx()["comms"]["accounts"]}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
                return
            if clean.startswith("/steward/v1"):
                body = b"<!doctype html><html><body></body></html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(body)
                return
            rel = clean.lstrip("/")
            if rel.startswith("steward-static/"):
                fp = ROOT / "steward_cockpit" / "static" / rel[len("steward-static/"):]
            else:
                fp = ROOT / rel
            if fp.is_file():
                data = fp.read_bytes()
                ctype = (
                    "text/css" if fp.suffix == ".css"
                    else ("application/javascript" if fp.suffix == ".js" else "application/octet-stream")
                )
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.end_headers()
                self.wfile.write(data)
                return
            self.send_response(404)
            self.end_headers()

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0") or 0)
            _ = self.rfile.read(length) if length > 0 else b""
            body = json.dumps({"ok": True, "message": "ok"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        with pw.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 960})
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(f"http://127.0.0.1:{port}/high-seat", wait_until="networkidle")

            # 1. Grok card on left rail is RED (.is-error, .ec-dot.error), while Claude is GREEN (.is-ready, .ec-dot.active)
            page.wait_for_selector('.cave-account-summary[data-provider-family="grok"].is-error', timeout=5000)
            grok_dot_bg = page.eval_on_selector(
                '.cave-account-summary[data-provider-family="grok"] .ec-dot',
                "el => getComputedStyle(el).backgroundColor",
            )
            claude_dot_bg = page.eval_on_selector(
                '.cave-account-summary[data-provider-family="claude"] .ec-dot',
                "el => getComputedStyle(el).backgroundColor",
            )
            assert grok_dot_bg == "rgb(239, 68, 68)", f"Expected red Grok dot, got {grok_dot_bg}"
            assert claude_dot_bg == "rgb(16, 185, 129)", f"Expected green Claude dot, got {claude_dot_bg}"

            # 2. AI Cockpits tile is CLOSED by default, then reveals Active, On Deck, and closed In Reserve bar on click
            assert page.locator("#caveCockpitsBody").is_hidden()
            assert not page.locator("#shActive").is_visible()
            page.click("#caveCockpitsToggle")
            assert page.locator("#shActive").is_visible()
            assert page.locator("#shDeck").is_visible()
            assert page.locator("#candsTile").is_visible()
            assert page.eval_on_selector("#candsTile", "el => el.open") is False
            page.click("#candsTile > summary")
            assert page.eval_on_selector("#candsTile", "el => el.open") is True
            assert page.locator("#candsTile .cand-group").first.is_visible()

            # 3. Email & Calendar open view shows expandable Services bar
            page.click("#cosEmailTile")
            assert page.locator("#caveCommsServicesBar").is_visible()
            assert page.eval_on_selector("#caveCommsServicesBar", "el => el.open") is False
            page.click("#caveCommsServicesSummary")
            assert page.eval_on_selector("#caveCommsServicesBar", "el => el.open") is True
            assert page.locator("#caveCommsServicesBar .cave-svc-row").count() == 2

            # 4. Seeds button/panel absent and zero JS page errors
            assert page.locator("#seedBtn").count() == 0
            assert errors == []

            # 4b. Projects tile (#ptile) opens collapsible folders (closed by default), expands folder on click,
            #     and Guided Add-Folder GUI walks through creating & expanding a new folder!
            page.click("#ptileToggle")
            page.wait_for_selector('#folders .rnd-folder[data-group="Research"]', timeout=5000)
            assert page.eval_on_selector('#folders .rnd-folder[data-group="Research"]', "el => el.classList.contains('rnd-collapsed')") is True
            page.click('#folders .rnd-folder[data-group="Research"] > .rnd-folder-head')
            assert page.eval_on_selector('#folders .rnd-folder[data-group="Research"]', "el => el.classList.contains('rnd-collapsed')") is False
            assert page.locator('#folders .rnd-folder[data-group="Research"] .rnd-row').first.is_visible()

            page.click("#apAddFolder")
            page.wait_for_selector("#caveFolderWizardModal:not([hidden])", timeout=3000)
            page.fill("#caveFwFolderName", "Teaching")
            page.click("#caveFwCreateFolderBtn")
            page.wait_for_selector('#folders .rnd-folder[data-group="Teaching"]', timeout=4000)
            assert page.eval_on_selector('#folders .rnd-folder[data-group="Teaching"]', "el => el.classList.contains('rnd-collapsed')") is False

            # 5. Light vs Dark toggle switches to Skill Foundry Light scheme (#f8fafc) and persists on reload
            assert page.eval_on_selector("body", "el => getComputedStyle(el).backgroundColor") == "rgb(15, 17, 23)"
            page.click("#caveThemeToggle")
            assert page.eval_on_selector("html", "el => el.getAttribute('data-cave-theme')") == "light"
            assert page.eval_on_selector("body", "el => getComputedStyle(el).backgroundColor") == "rgb(248, 250, 252)"
            assert page.eval_on_selector(".rail", "el => getComputedStyle(el).backgroundColor") == "rgb(255, 255, 255)"

            # 6. Light mode covers all Calendar & Email dialogues, cards, views, and Speed Racer (never left dark)
            page.click('[data-comms-layout="split"]')
            light_surface_RGBs = {"rgb(255, 255, 255)", "rgb(248, 250, 252)", "rgb(241, 245, 249)", "rgb(255, 251, 235)", "rgb(239, 246, 255)"}
            # Calendar header & Add-Event Dialogue (#caveCommsDialogueTile / #caveCalDialoguePane)
            page.click("#btnCaveAddCalEventTop")
            page.wait_for_selector("#caveCommsDialogueTile:not([hidden])", timeout=3000)
            assert page.eval_on_selector("#caveCommsDialogueTile", "el => getComputedStyle(el).backgroundColor") in light_surface_RGBs
            assert page.eval_on_selector("#caveCalDialoguePane .cave-dlg-split > div", "el => getComputedStyle(el).backgroundColor") in light_surface_RGBs
            assert page.eval_on_selector("#caveCalEvTitle", "el => getComputedStyle(el).backgroundColor") == "rgb(255, 255, 255)"
            assert page.eval_on_selector("#caveCalEvTitle", "el => getComputedStyle(el).color") == "rgb(15, 23, 42)"
            assert page.eval_on_selector("#caveCalEvRsvpBar", "el => getComputedStyle(el).backgroundColor") == "rgb(255, 255, 255)"

            # Day Time-Block View (#caveCalViewport .cave-day-timegrid)
            page.click('[data-cave-cal-view="day"]')
            if page.locator(".cave-day-timegrid").count() > 0:
                assert page.eval_on_selector(".cave-day-timegrid", "el => getComputedStyle(el).backgroundColor") == "rgb(255, 255, 255)"

            # Email Reading Dialogue (#caveEmailDialoguePane, floating & docked), Scribe Bar, Thread Box & Direct Reply
            page.evaluate("""() => {
                const pane = document.getElementById('caveEmailDialoguePane');
                const split = document.getElementById('caveOutlookMailSplit');
                if (pane) pane.hidden = false;
                if (split) split.classList.remove('email-dlg-closed');
                const th = document.getElementById('caveDialogueThreadList');
                if (th) {
                    th.innerHTML = '<div class="cave-single-msg-card" style="background:#111827"><div style="color:#f1f5f9">Sample email body in light mode</div></div>';
                }
            }""")
            assert page.eval_on_selector("#caveEmailDialoguePane", "el => getComputedStyle(el).backgroundColor") == "rgb(255, 255, 255)"
            assert page.eval_on_selector("#caveDlgStewardDirectionsBar", "el => getComputedStyle(el).backgroundColor") in light_surface_RGBs
            assert page.eval_on_selector("#caveDlgStewardDirectionsInput", "el => getComputedStyle(el).backgroundColor") == "rgb(255, 255, 255)"
            assert page.eval_on_selector("#caveDialogueThreadScrollBox", "el => getComputedStyle(el).backgroundColor") in light_surface_RGBs
            assert page.eval_on_selector(".cave-single-msg-card", "el => getComputedStyle(el).backgroundColor") == "rgb(255, 255, 255)"
            assert page.eval_on_selector(".cave-single-msg-card > div", "el => getComputedStyle(el).color") == "rgb(15, 23, 42)"
            page.click("#caveDlgDirectReplyDrawer > summary")
            assert page.eval_on_selector("#caveDlgDirectReplyDrawer", "el => getComputedStyle(el).backgroundColor") in light_surface_RGBs
            assert page.eval_on_selector("#caveReplyBody", "el => getComputedStyle(el).backgroundColor") == "rgb(255, 255, 255)"
            assert page.eval_on_selector("#caveReplyBody", "el => getComputedStyle(el).color") == "rgb(15, 23, 42)"

            # Speed Racer Dialogue (#caveSpeedRacerTile, floating & docked) + Quick-Connect Modal
            page.click("#btnCaveOpenSpeedRacer")
            assert page.eval_on_selector("#caveSpeedRacerTile", "el => getComputedStyle(el).backgroundColor") == "rgb(255, 255, 255)"
            assert page.eval_on_selector("#caveSpeedRacerHead", "el => getComputedStyle(el).backgroundColor") in light_surface_RGBs
            assert page.eval_on_selector("#caveSpeedRacerBody", "el => getComputedStyle(el).backgroundColor") == "rgb(255, 255, 255)"
            assert page.eval_on_selector("#caveCommsConnectModal", "el => getComputedStyle(el).backgroundColor") in light_surface_RGBs
            assert page.eval_on_selector("#caveCommsEmail", "el => getComputedStyle(el).backgroundColor") == "rgb(255, 255, 255)"

            page.reload(wait_until="networkidle")
            assert page.eval_on_selector("html", "el => el.getAttribute('data-cave-theme')") == "light"
            assert page.eval_on_selector("body", "el => getComputedStyle(el).backgroundColor") == "rgb(248, 250, 252)"
            browser.close()
    finally:
        srv.shutdown()
