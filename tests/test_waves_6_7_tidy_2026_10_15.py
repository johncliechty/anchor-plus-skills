"""Regression tests for Wave 6 (Cave of Wonders Tidy-Up) and Wave 7 (Star Chart Tidy-Up)."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import campaign_page


def test_wave6_talkview_hides_duplicate_topbar_and_preserves_cave_selectors():
    css = (ROOT / "steward_cockpit" / "static" / "shared.css").read_text(encoding="utf-8")
    assert ".app.talkview .bar" in css
    assert "display: none !important" in css
    # Existing Cave of Wonders contract selectors must remain intact
    for sel in (
        ".app.talkview .leftcol",
        ".app.talkview .goalbar",
        ".app.talkview .rightcol",
        ".app.talkview .composer",
        ".app.talkview [data-drive]",
    ):
        assert sel in css


def test_wave6_md_js_links_internal_cockpit_and_campaign_routes():
    md_js = (ROOT / "steward_cockpit" / "static" / "md.js").read_text(encoding="utf-8")
    for route in ("/steward/v1", "/high-seat", "/desk", "/doctor"):
        assert route in md_js
    assert r"\/project\/" in md_js


def test_wave6_provider_setup_hides_duplicate_right_rail_capacity_visually():
    css = (ROOT / "static" / "provider-setup.css").read_text(encoding="utf-8")
    assert ".panel>#cave-provider-capacity" in css
    assert "clip:rect(0,0,0,0)" in css


def test_wave7_campaign_cockpits_keeps_overflow_count_inside_gcock():
    parts = [
        {"kind": "project", "broken": False, "state": "idle", "status": "", "target": f"Proj {idx}", "text": f"Proj {idx}"}
        for idx in range(7)
    ]
    html = campaign_page._cockpits({"parts": parts}, {"working": set()})
    assert html.startswith('<div class="gcock">')
    assert html.endswith('</div>')
    assert '<span class="dim">+3</span></div>' in html


def test_wave7_campaign_css_placed_grid_and_facts_layout():
    css = (ROOT / "static" / "campaign-page.css").read_text(encoding="utf-8")
    assert ".board.placed .band .tiles{grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:6px}" in css
    assert ".board.placed .gtile .gcock" in css
    assert "grid-template-columns:minmax(110px,auto) minmax(0,1fr)" in css
