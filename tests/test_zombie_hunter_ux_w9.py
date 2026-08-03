"""W9 / SC7 — Clickable health + reaper-health banners → Doctor seed.

Named tests from IMPLEMENTATION-PLAN Wave 9:
  - test_health_banner_doctor_seed (1:1 fields + async start attempted)
  - cross-surface fail-SAFE with dual-write rule (banner seed ≠ scare RED)

Hermetic: tmp ANCHOR_DATA_DIR; never touches live :8777 / real CLIs.
"""
from __future__ import annotations

import importlib
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest


@pytest.fixture
def w9env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.setenv("ANCHOR_CLAUDE_AVAILABLE", "1")
    monkeypatch.setenv("ANCHOR_GEMINI_AVAILABLE", "1")
    monkeypatch.setenv("ANCHOR_GROK_AVAILABLE", "1")
    import paths
    importlib.reload(paths)
    paths.ensure_data_dirs()
    import lanes
    importlib.reload(lanes)
    import terminal_session
    importlib.reload(terminal_session)
    import session_registry
    importlib.reload(session_registry)
    import anchor_gui
    gui = importlib.reload(anchor_gui)
    yield {
        "gui": gui,
        "lanes": lanes,
        "termsess": terminal_session,
        "reg": session_registry,
        "data": tmp_path,
    }


def test_health_banner_doctor_seed(w9env):
    gui = w9env["gui"]

    # Closed catalog defaults present (aligned with zombie-hunter reason-catalog).
    assert "ZH_HEALTH_CHECK_ISSUES" in gui._W9_DOCTOR_ISSUE_DEFAULTS
    assert "ZH_REAPER_ABSTAIN_STREAK" in gui._W9_DOCTOR_ISSUE_DEFAULTS
    assert "ZH_REAPER_CHAIN_TAMPERED" in gui._W9_DOCTOR_ISSUE_DEFAULTS

    # Dashboard health banner issue — 1:1 fields, not markdown path.
    health = gui._w9_build_dashboard_health_banner_issue(
        report_date="2099-06-01",
        status="ISSUES FOUND",
        last_error="Status: ISSUES FOUND",
    )
    assert health["issueId"] == "ZH_HEALTH_CHECK_ISSUES"
    assert health["message"] == health["exactMessage"]
    assert health["component"]
    assert health["lastError"]
    assert isinstance(health["suggestedChecks"], list)
    assert health["isMarkdownPath"] is False
    assert health["markdownPath"] is None
    assert health["bannerSurface"] == "dashboard_health"

    seed = gui._w8_build_doctor_short_seed(health)
    one = gui._w9_assert_banner_seed_one_to_one(health, seed)
    assert one["ok"] is True, one["mismatches"]
    for f in gui._W9_BANNER_SEED_FIELDS:
        assert f in gui._w9_extract_banner_seed_fields(health)

    # Navigation opens /doctor with seed query — never health_reports/*.md
    nav = gui._w9_build_doctor_navigation_from_banner(health, auto_diagnose=True)
    assert nav["ok"] is True
    assert nav["path"] == "/doctor"
    assert nav["href"].startswith("/doctor?")
    assert nav["isMarkdownPath"] is False
    assert nav["markdownPath"] is None
    assert not re.search(r"health_reports[/\\].*\.md", nav["href"], re.I)
    assert "issueId=" in nav["href"]
    assert "diagnose=1" in nav["href"]
    qs = parse_qs(urlparse(nav["href"]).query)
    assert qs.get("issueId", [""])[0] == health["issueId"]
    assert qs.get("message", [""])[0] == health["message"]

    # Reaper-health banner
    reaper = gui._w9_build_reaper_health_banner_issue({
        "tripped": True,
        "kind": "abstain-streak",
        "streak": 12,
        "threshold": 5,
        "message": "Reaper has ABSTAINED for 12 consecutive sweeps (> 5) — flying blind.",
    })
    assert reaper["issueId"] == "ZH_REAPER_ABSTAIN_STREAK"
    assert reaper["bannerSurface"] == "reaper_health"
    assert gui._w9_assert_banner_seed_one_to_one(
        reaper, gui._w8_build_doctor_short_seed(reaper)
    )["ok"] is True

    chain = gui._w9_build_reaper_health_banner_issue({"kind": "chain-tampered"})
    assert chain["issueId"] == "ZH_REAPER_CHAIN_TAMPERED"

    # Async diagnose start attempted when engine enabled
    attempt = gui._w9_attempt_async_banner_diagnose_start(health, engine="claude")
    assert attempt["attempted"] is True
    assert attempt["async"] is True
    assert attempt["ok"] is True
    assert attempt["failureNonBlocking"] is True
    assert attempt["uiUsable"] is True
    assert attempt["seed"]["issueId"] == health["issueId"]
    assert attempt["seedOneToOne"]["ok"] is True

    plan = gui._w9_build_banner_diagnose_plan(health, engine="gemini")
    assert plan["canStart"] is True
    assert plan["session"]["async"] is True
    assert plan["session"]["failureNonBlocking"] is True
    assert plan["session"].get("attemptAsyncDiagnose") is True
    assert plan["bannerOneToOne"]["ok"] is True
    assert plan["navigation"]["isMarkdownPath"] is False
    assert plan["p6BannerDoctor"]["version"] == gui._W9_BANNER_DOCTOR_SEED_VERSION

    # Start failure surfaces health; UI usable
    failed = gui._w9_attempt_async_banner_diagnose_start(
        health, engine="claude", force_fail=True, fail_reason="simulated_start_timeout"
    )
    assert failed["ok"] is False
    assert failed["attempted"] is True
    assert failed["uiUsable"] is True
    assert failed["failureNonBlocking"] is True
    assert failed["session"] is None
    assert failed["health"]

    # Clickable banner HTML is not a markdown-only path
    html = gui._w9_render_clickable_banner_html(
        health,
        title="Health check found issues",
        body="on 2099-06-01. Click to diagnose in Doctor.",
        style_kind="health",
    )
    assert "zh-health-banner-doctor" in html
    assert "data-issue-id=" in html
    assert "data-not-markdown-path=" in html
    assert "cursor:pointer" in html
    assert "/doctor?" in html
    # Must not be the old static-only markdown pointer as the sole CTA
    assert "health_reports/" not in html
    assert "See <code" not in html
    assert 'role="button"' in html

    # Doctor page template: parses banner query + auto-diagnose attempt
    src = Path(gui.__file__).read_text(encoding="utf-8", errors="replace")
    assert "BANNER_ISSUE" in src
    assert "parseBannerIssueFromQuery" in src or "Banner seed loaded (W9/SC7)" in src
    assert "fromBanner" in src
    assert "startBody.issue = BANNER_ISSUE" in src or "startBody.issue" in src

    # Route registered
    import route_table as rt
    importlib.reload(rt)
    row = rt.match("GET", "/api/doctor/banner_seed")
    assert row is not None
    assert row.handler == "handle_doctor_banner_seed"
    assert "handle_doctor_banner_seed" in gui._MIGRATED_HANDLERS
    assert callable(gui._MIGRATED_HANDLERS["handle_doctor_banner_seed"])


def test_banner_doctor_fail_safe_not_scare_red(w9env):
    """Cross-surface fail-SAFE: banner→Doctor seed is independent of zombie scare RED."""
    gui = w9env["gui"]
    health = gui._w9_build_dashboard_health_banner_issue(
        report_date="2099-01-01", status="ISSUES FOUND"
    )
    plan = gui._w9_build_banner_diagnose_plan(health, engine="claude")
    assert plan["navigation"]["isMarkdownPath"] is False
    assert plan["bannerOneToOne"]["ok"] is True
    # Doctor seed does not invent actionable RED scare language in seed text
    seed_text = plan.get("seedText") or ""
    assert "SHORT DIAGNOSE" in seed_text or "DOCTOR" in seed_text
    assert "token-spending zombie" not in seed_text.lower()
    # Reaper banner likewise
    reaper = gui._w9_build_reaper_health_banner_issue({
        "kind": "abstain-streak", "streak": 9, "threshold": 3,
        "message": "flying blind",
    })
    rnav = gui._w9_build_doctor_navigation_from_banner(reaper)
    assert rnav["isMarkdownPath"] is False
    assert rnav["path"] == "/doctor"
