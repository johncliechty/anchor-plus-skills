"""Wave 7 Star Chart unit & integration tests (2026-10-15).

Covers:
1. Strategic Foresight & Portfolio Alignment strip (#starForesight, star_foresight_cards) pure-context rendering.
2. Quick-navigation links to Cave of Wonders (.tool.cave) and Desktop Ad-Hoc AI Cockpit (.tool.desk) without class="back".
3. Live cockpit step progress badges (.psteps) on Star Chart goal tiles when ctx["facts"] provides steps_done/steps_total.
4. 1-click completion button (.mchip.done-act[data-act="mark_done"]) on open task/step parts while preserving .tick close-law invariant.
5. read_map preservation of goal pace ("pace" field) in steward_campaign.py.
6. Universal "Working = Green Light" (#3fb950) consistency in static/campaign-page.css.
"""
from datetime import date
from pathlib import Path
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import campaign_page as cpg  # noqa: E402
import high_seat_page as hsp  # noqa: E402
from steward_cockpit import steward_campaign as sc  # noqa: E402

TODAY = date(2026, 10, 15)
MBA = "6765ece4b3bc43b0b0b0907b92b17280"
TRUSTS = "9405abe06dc84b749d4ece0bda1cb45c"


def _sample_ctx():
    steps = [
        {"id": "trusts", "name": "Family finances", "status": "proposed", "tier": 1, "area": "family",
         "pace": "2026-10-31",
         "if_then": "If Merrill confirms the Exmera LP -> Holding Co transfer wording, then roll out the transfer template to all brothers",
         "done_when": "Family trusts and Exmera LP Holding Co transfers complete",
         "navigation": {"path": ["trusts"], "groups": [{"id": "trusts", "label": "Family finances", "order": 0, "parent_id": None}]}},
        {"id": "ft-proj", "name": "Family Trusts", "status": "proposed", "ref": "project:" + TRUSTS, "navigation": {"path": ["trusts"]}},
        {"id": "merrill-step", "name": "Verify Merrill Exmera LP -> Holding Co transfer wording", "status": "active",
         "ref": "step:%s/october-transfer-prerequisites" % TRUSTS, "navigation": {"path": ["trusts"]}},
        {"id": "mba-teaching", "name": "MBA Teaching, Fall 2026", "status": "proposed", "tier": 1, "area": "professional",
         "pace": "2026-10-27",
         "if_then": "If tonight's Lecture 4 session concludes, then finalize Lecture 5 paired and two-sample deck for Oct 17",
         "done_when": "Fall 2026 lectures and AI supplements delivered",
         "navigation": {"path": ["mba-teaching"], "groups": [{"id": "mba-teaching", "label": "MBA Teaching, Fall 2026", "order": 1, "parent_id": None}]}},
        {"id": "mba-proj", "name": "MBA Teaching AI", "status": "proposed", "ref": "project:" + MBA, "navigation": {"path": ["mba-teaching"]}},
        {"id": "lec-5", "name": "Lecture 5 — Paired and two-sample comparison", "status": "active",
         "ref": "step:%s/lecture-5" % MBA, "navigation": {"path": ["mba-teaching"]}},
        {"id": "anchor-steward", "name": "Ghost World Labs", "status": "proposed", "tier": 2, "area": "tools",
         "pace": "2026-10-25",
         "done_when": "Anchor + Steward multi-wave build complete",
         "navigation": {"path": ["anchor-steward"], "groups": [{"id": "anchor-steward", "label": "Ghost World Labs", "order": 0, "parent_id": None}]}},
        {"id": "gwl-done", "name": "Wave 6 Cave of Wonders", "status": "done", "navigation": {"path": ["anchor-steward"]}},
        {"id": "gwl-open", "name": "Wave 7 Star Chart", "status": "active", "due": "2026-10-16", "navigation": {"path": ["anchor-steward"]}},
    ]
    resolved = {
        "ft-proj": {"kind": "project", "pid": TRUSTS, "name": "Family Trusts", "what": "", "state": "", "date": "2026-10-16", "href": "/project/" + TRUSTS, "broken": False, "gap": ""},
        "merrill-step": {"kind": "step", "pid": TRUSTS, "name": "Family Trusts", "what": "Verify Merrill Exmera LP -> Holding Co transfer wording", "state": "active", "target_status": "active", "date": "2026-10-17", "href": "/project/" + TRUSTS, "broken": False, "gap": ""},
        "mba-proj": {"kind": "project", "pid": MBA, "name": "MBA Teaching AI", "what": "", "state": "", "date": "2026-10-17", "href": "/project/" + MBA, "broken": False, "gap": ""},
        "lec-5": {"kind": "step", "pid": MBA, "name": "MBA Teaching AI", "what": "Lecture 5 — Paired and two-sample comparison", "state": "active", "target_status": "active", "date": "2026-10-17", "href": "/project/" + MBA, "broken": False, "gap": ""},
    }
    facts = {
        TRUSTS: {"id": TRUSTS, "name": "Family Trusts", "steps_done": 8, "steps_total": 17},
        MBA: {"id": MBA, "name": "MBA Teaching AI", "steps_done": 32, "steps_total": 87},
    }
    return {
        "pid": "df56",
        "name": "Campaign",
        "today": TODAY,
        "today_str": "Thursday, October 15, 2026",
        "brief_when": "14:45 · Thursday 15 October",
        "build": "test-w7",
        "steward": {
            "key": "aladdin",
            "label": "Aladdin",
            "high_seat": "aladdin-cave-of-wonders.jpg",
            "seal": "aladdin-carpet.jpg",
            "high_seat_name": "Cave of Wonders",
            "seal_name": "Magic Carpet",
            "campaign_name": "Star Chart",
            "campaign_icon": "campaign-aladdin-star-chart.jpg",
        },
        "prefs_html": "<span id='prefs-here'></span>",
        "initiatives": hsp.campaign_initiatives(steps, resolved),
        "seeds": [],
        "turns": [],
        "projects": [{"id": MBA, "name": "MBA Teaching AI"}, {"id": TRUSTS, "name": "Family Trusts"}],
        "facts": facts,
        "desk_pid": "desk123",
        "tick_allowed": False,
        "working": {MBA},
    }


def test_star_foresight_cards_renders_three_strategic_cards_from_ctx():
    ctx = _sample_ctx()
    cards = cpg.star_foresight_cards(ctx)
    assert len(cards) == 3
    kinds = [c["kind"] for c in cards]
    assert kinds == ["tier1", "chain", "portfolio"]
    assert "Family finances" in cards[0]["body_html"] and "MBA Teaching, Fall 2026" in cards[0]["body_html"]
    assert "Exmera LP" in cards[1]["body_html"]
    assert "40 of 104" in cards[2]["body_html"]  # 8+32 = 40 of 17+87 = 104 linked cockpit steps
    assert "Ghost World Labs" in cards[2]["body_html"]


def test_star_chart_html_includes_foresight_strip_and_quick_nav_without_back_class():
    html = cpg.render_campaign_html(_sample_ctx())
    assert 'id="starForesight"' in html
    assert "Strategic Foresight &amp; Portfolio Alignment" in html
    assert 'class="tool cave" href="/high-seat"' in html
    assert 'class="tool desk" href="/steward/v1?pid=desk123&amp;dir=Small%20items"' in html
    assert 'class="back"' not in html


def test_star_chart_cockpit_chips_show_live_step_progress_and_parts_have_done_button():
    html = cpg.render_campaign_html(_sample_ctx())
    assert 'class="psteps" title="Live cockpit roadmap progress">8/17 steps</b>' in html
    assert 'class="psteps" title="Live cockpit roadmap progress">32/87 steps</b>' in html
    assert 'class="mchip done-act" data-act="mark_done" data-part="merrill-step"' in html
    assert 'class="mchip done-act" data-act="mark_done" data-part="gwl-open"' in html
    # Done part does not render mark_done button
    assert 'data-act="mark_done" data-part="gwl-done"' not in html
    # Close-law tick remains disabled
    assert 'disabled title="a tick waits on your word on the close law"' in html


def test_steward_campaign_read_map_preserves_pace_field(tmp_path):
    rm = {
        "schema": "ecgberht-roadmap-v1",
        "roadmap_events": [],
        "roadmap_projection": [
            {"id": "trusts", "name": "Family finances", "status": "proposed", "tier": 1, "pace": "2026-10-31", "if_then": "If X, then Y"}
        ],
    }
    (tmp_path / "roadmap.json").write_text(json.dumps(rm), encoding="utf-8")
    (tmp_path / "ECGBERHT.md").write_text("# North Star\nTest\n", encoding="utf-8")
    (tmp_path / "strip.json").write_text(json.dumps({"phase": "executing"}), encoding="utf-8")
    m = sc.read_map(str(tmp_path))
    assert m["steps"][0]["pace"] == "2026-10-31"
    assert m["steps"][0]["if_then"] == "If X, then Y"


def test_campaign_css_working_status_uses_green_light():
    css = (Path(__file__).resolve().parent.parent / "static" / "campaign-page.css").read_text(encoding="utf-8")
    assert ".ilight.working,.gcock .gpc.working,.lg.working{color:#3fb950}" in css
