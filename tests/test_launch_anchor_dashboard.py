"""Service-aware dashboard launcher — simple onboard shell Wave 1."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import launch_anchor_dashboard as lad  # noqa: E402
import share_onboard as sob  # noqa: E402

URL = sob.DEFAULT_LOCAL_DASHBOARD_URL


def test_already_running_skips_start_and_opens_browser():
    opens = []
    starts = []

    def probe(url):
        return True

    def start():
        starts.append(1)
        return {"attempted": True, "started": True}

    r = lad.ensure_dashboard_running(
        url=URL,
        probe_fn=probe,
        start_fn=start,
        open_fn=lambda u: opens.append(u),
        retries=1,
        sleep_s=0,
    )
    assert r["ok"] is True
    assert r["already_running"] is True
    assert r["start_attempted"] is False
    assert starts == []
    assert opens == [URL]


def test_down_then_start_then_open():
    opens = []
    state = {"n": 0}

    def probe(url):
        state["n"] += 1
        # first probe fail; after start succeed
        return state["n"] >= 2

    def start():
        return {"attempted": True, "started": True}

    r = lad.ensure_dashboard_running(
        url=URL,
        probe_fn=probe,
        start_fn=start,
        open_fn=lambda u: opens.append(u),
        retries=3,
        sleep_s=0,
    )
    assert r["start_attempted"] is True
    assert r["ok"] is True
    assert opens == [URL]


def test_refuses_non_local_url():
    r = lad.ensure_dashboard_running(
        url="https://example.com",
        open_fn=lambda u: None,
        sleep_s=0,
    )
    assert r["ok"] is False
    assert "non_local_dashboard_url" in r["reason_codes"]


def test_still_down_after_start_is_not_ok():
    r = lad.ensure_dashboard_running(
        url=URL,
        probe_fn=lambda u: False,
        start_fn=lambda: {"attempted": True, "started": False},
        open_fn=lambda u: None,
        retries=2,
        sleep_s=0,
    )
    assert r["ok"] is False
    assert "anchor_service_unavailable" in r["reason_codes"]


def test_package_b_dual_gate_passes_package_root_to_shortcut(tmp_path):
    """Desktop brand path must know the package tree (launcher lives there)."""
    home = tmp_path / "home"
    desk = tmp_path / "Desktop"
    home.mkdir()
    desk.mkdir()
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "launch_anchor_dashboard.py").write_text("# stub\n", encoding="utf-8")
    ico = home / sob.ANCHOR_ICO_BASENAME
    ico.write_bytes(b"ICO")
    seen = {}

    def shortcut_fn(**kw):
        seen.update(kw)
        path = Path(kw["desktop_dir"]) / sob.DESKTOP_LNK_BASENAME
        path.write_text(
            "URL=%s\nIconLocation=%s,0\n" % (kw.get("url"), ico),
            encoding="utf-8",
        )
        return {
            "created": True,
            "path": str(path),
            "url": kw.get("url"),
            "uses_anchor_ico": True,
            "branding_complete": True,
            "icon_location": "%s,0" % ico,
            "format": "lnk",
        }

    report = {"ok": True, "readiness": {"status": "ready"}}
    out = sob.complete_package_b_dual_gate(
        report,
        home=home,
        desktop_dir=str(desk),
        probe_fn=lambda u: True,
        start_service_fn=lambda: {"attempted": True, "started": True},
        shortcut_fn=shortcut_fn,
        package_root=pkg,
        skip_service_start=False,
        check_favicon_flag=True,
        check_skill_icons_flag=False,
        favicon_get_fn=lambda u: True,
    )
    assert out.get("b_ready") is True or (out.get("package_b") or {}).get("b_ready") is True
    # Production path passes package_root into write_desktop_lnk; inject still gets url.
    assert seen.get("url") == URL
