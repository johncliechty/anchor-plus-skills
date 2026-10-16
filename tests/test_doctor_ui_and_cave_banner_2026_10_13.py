"""Tests for the upgraded Anchor Doctor Detailed Page and Cave of Wonders Health Banner (2026-10-13)."""
import importlib
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

import high_seat_page
from tests.test_app_header_attention import ReadOnlyUI, cave_html, ORIGIN


def _write_red_report(data_dir: Path, name: str = "2026-10-13.md") -> None:
    rd = data_dir / "health_reports"
    rd.mkdir(parents=True, exist_ok=True)
    body = (
        "# Anchor Health Check — 2026-10-13\n"
        "Status: ISSUES FOUND\n\n"
        "## Issues\n"
        "- [GET /api/doctor/status] unreachable (timed out after 8.0s)\n"
        "- [Steward cockpit surface] Injected correctness failure\n\n"
        "## Warnings\n"
        "(none)\n"
    )
    (rd / name).write_text(body, encoding="utf-8")


def test_health_state_banner_includes_plain_english_issues(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    import paths
    importlib.reload(paths)
    import health_state
    importlib.reload(health_state)

    _write_red_report(data)
    b = health_state.banner()
    assert b is not None
    assert b["status"] == "red"
    assert len(b["issues"]) == 2
    assert len(b["plain_issues"]) == 2
    assert any("doctor/status" in p or "Steward" in p for p in b["plain_issues"])


def test_high_seat_health_banner_renders_pills_and_one_click_actions():
    ctx = {
        "build": "test",
        "rows": [{
            "rule": "health",
            "text": "Health check found issues",
            "why": "2026-10-13 — Doctor can diagnose it",
            "href": "/doctor?issueId=ZH_HEALTH_CHECK_ISSUES&diagnose=1",
            "plain_issues": [
                "GET /api/doctor/status did not answer during the 5 AM check",
                "Steward cockpit surface: Injected correctness failure",
            ],
        }],
    }
    html = high_seat_page._health_banner(ctx)
    assert 'class="healthbar"' in html
    assert 'class="hb-pills"' in html
    assert "GET /api/doctor/status did not answer" in html
    assert 'data-hb-act="resolve-all"' in html
    assert "One-Click Fix &amp; Verify" in html
    assert 'data-hb-act="dismiss"' in html
    # Exactly one <a> link inside .healthbar to preserve strict-mode locators
    assert html.count("<a ") == 1


def test_doctor_page_renders_left_rail_subsystem_cards_and_terminal_composer(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    import paths
    importlib.reload(paths)
    import anchor_gui as gui

    _write_red_report(data)
    html = gui.render_doctor_page_html()

    # Left rail + navigation + 4-engine CLI readiness cards
    assert 'class="doc-rail"' in html
    assert 'id="railEngines"' in html
    for eng in ("claude", "chatgpt", "gemini", "grok"):
        assert f'data-rail-eng="{eng}"' in html

    # Structured issue banner, filters, and remediation guidance
    assert 'class="card panel doc-issue-banner"' in html
    assert 'id="resolveAllBtn"' in html
    assert 'onclick="manualProbeNow()"' in html
    assert 'onclick="dismissDoctorBanner()"' in html
    assert 'class="issue-comp-badge"' in html
    assert 'class="issue-remedy"' in html
    assert 'onclick="resolveIssue(0)"' in html

    # Right-hand Doctor AI Terminal & Repair Cockpit controls
    assert 'id="doctorModelSelect"' in html
    assert 'class="quick-chips"' in html
    assert 'id="termPromptInput"' in html
    assert 'id="termSendBtn"' in html


class InteractiveCaveHealthUI(ReadOnlyUI):
    def __init__(self, context):
        self.health = {
            "ok": True,
            "status": "red",
            "last_run": "2026-10-13",
            "issues": [{"component": "GET /api/status", "detail": "unreachable (timed out)"}],
            "warnings": [],
        }
        self.resolve_calls = 0
        super().__init__(context)

    def route(self, route):
        path = urlsplit(route.request.url).path
        if path == "/api/doctor/status" and route.request.method == "GET":
            return route.fulfill(status=200, json=self.health)
        if path == "/api/doctor/resolve_all" and route.request.method == "POST":
            self.resolve_calls += 1
            # Simulate verification completing and clearing the red report
            self.health = {
                "ok": True,
                "status": "green",
                "last_run": "2026-10-13",
                "issues": [],
                "warnings": [],
            }
            return route.fulfill(
                status=200,
                json={"ok": True, "decision": "rerun", "rerun": {"ok": True}, "issues": [], "probe": []},
            )
        if path in ("/", "/high-seat"):
            old = high_seat_page._health_banner({
                "rows": [{
                    "rule": "health",
                    "text": "Health check found issues",
                    "why": "2026-10-13 — Doctor can diagnose it",
                    "href": "/doctor?issueId=ZH_HEALTH_CHECK_ISSUES&diagnose=1",
                }],
                "build": "test",
            })
            html = cave_html().replace("<body>", '<body><div class="main"><div class="masthead">Cave of Wonders</div>' + old)
            return route.fulfill(body=html.replace("</body>", "</div></body>"), content_type="text/html")
        return super().route(route)


def test_cave_banner_pills_one_click_fix_and_dismiss():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        fixture = InteractiveCaveHealthUI(context)
        page = context.new_page()
        page.goto(ORIGIN + "/static/app.html")
        page.wait_for_function("() => document.querySelector('#stage iframe')?.contentWindow?.AnchorCaveHealth")
        frame = next(f for f in page.frames if f != page.main_frame and f.url.rstrip("/") == ORIGIN)

        expect(frame.locator(".healthbar")).to_have_count(1)
        expect(frame.locator(".healthbar .hb-pill")).to_have_count(1)
        expect(frame.locator(".healthbar .hb-pill")).to_contain_text("GET /api/status")

        # Clicking One-Click Fix & Verify calls /api/doctor/resolve_all and clears the banner when green
        frame.locator('.healthbar [data-hb-act="resolve-all"]').click()
        expect(frame.locator(".healthbar")).to_have_count(0)
        assert fixture.resolve_calls == 1

        # Re-inject red status, refresh, then test Dismiss button
        fixture.health = {
            "ok": True,
            "status": "red",
            "last_run": "2026-10-14",
            "issues": [{"component": "Auth check", "detail": "401 unauthorized"}],
            "warnings": [],
        }
        frame.evaluate("window.AnchorCaveHealth.refresh()")
        expect(frame.locator(".healthbar")).to_have_count(1)
        frame.locator('.healthbar [data-hb-act="dismiss"]').click()
        expect(frame.locator(".healthbar")).to_have_count(0)

        assert not fixture.forbidden, fixture.forbidden
        assert not fixture.errors, fixture.errors
        browser.close()
