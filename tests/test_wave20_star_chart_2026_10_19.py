"""Wave 20 Star Chart & Fast Steward Command unit tests (2026-10-19).

Covers:
1. Classic Star Chart Livery + Governing Life Mission (#missionBar) with full mission statement and Edit Mission box (#missionEditBox).
2. Don Hambrick & James Fredrickson (2001) 5-Part Strategy Diamond (#diamondGrid, .d-cell, #w20DiamondDrawer) and resource deployment alignment pills.
3. Bidirectional Star Chart <-> Cave of Wonders 5-Horizon Cascade (#starHorizons, .hz-cell, #w20HzDrawer, #btnSyncHorizons).
4. Dedicated Star Chart & Foundry icons across header, masthead, Steward conversation header, and 4 quick-action buttons (#cosFoundryBar).
5. 1-click Goal Tile actions (.w20-tile-acts: Open Goal, Next Step Done, Seat in Active, On Deck, Unseat).
6. Fast deterministic Steward command parser (campaign_say.fast_steward_command) for sub-20ms Cave of Wonders & AI Cockpit rearrange/create/mark-done requests.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import campaign_page as cpg  # noqa: E402
from steward_cockpit import campaign_say as cs  # noqa: E402
from tests.test_wave7_star_chart_2026_10_15 import _sample_ctx  # noqa: E402


def test_wave20_star_chart_renders_mission_diamond_horizons_and_brand_icons():
    ctx = _sample_ctx()
    html = cpg.render_campaign_html(ctx)

    # 1. Governing Life Mission statement (full, untruncated)
    assert 'id="missionBar"' in html
    assert "Governing Life Mission" in html
    assert (
        "To create really high-quality work product and thought product based on deep thinking "
        "and profound insights that help people improve their lives."
    ) in html
    assert 'id="btnEditMission"' in html
    assert 'id="missionEditBox"' in html

    # 2. Don Hambrick 5-Part Strategy Diamond + Resource Deployment Alignment
    assert 'id="diamondGrid"' in html
    assert 'data-diamond="arenas"' in html
    assert 'data-diamond="vehicles"' in html
    assert 'data-diamond="differentiators"' in html
    assert 'data-diamond="staging"' in html
    assert 'data-diamond="economic"' in html
    assert 'id="w20DiamondDrawer"' in html
    assert 'id="btnAuditDiamond"' in html

    # 3. 5-Horizon Bidirectional Cascade (Star Chart <-> Cave of Wonders)
    assert 'id="starHorizons"' in html
    assert 'data-hz="year"' in html
    assert 'data-hz="quarter"' in html
    assert 'data-hz="month"' in html
    assert 'data-hz="week"' in html
    assert 'data-hz="today"' in html
    assert 'id="btnSyncHorizons"' in html
    assert 'id="w20HzDrawer"' in html

    # 4. Real Star Chart & Foundry icons (never gandalf-icon.jpg for Star Chart identity)
    assert "/vendor/brand/campaign-aladdin-star-chart.jpg" in html
    assert ("/vendor/brand/aladdin-cave-of-wonders.jpg" in html) or ("/vendor/brand/aladdin-high-seat.jpg" in html)
    assert "/vendor/brand/desk-tab-aladdin.png" in html
    assert "/vendor/brand/new-cockpit-icon.jpg" in html
    assert "/vendor/brand/brainstorm-icon.jpg" in html
    assert "/vendor/brand/crucible-icon.svg" in html
    assert 'id="cosFoundryBar"' in html

    # 5. 1-Click Goal Tile Actions on live .gtile cards
    assert 'class="w20-tile-acts"' in html
    assert "Next Step Done" in html
    assert 'data-seat="active"' in html
    assert 'data-seat="deck"' in html


def test_fast_steward_command_parses_cave_and_cockpit_actions_deterministically(tmp_path):
    proj_dir = tmp_path / "Campaign"
    proj_dir.mkdir(parents=True, exist_ok=True)
    rm_path = proj_dir / "roadmap.json"
    rm_path.write_text(
        json.dumps(
            {
                "schema": "ecgberht-roadmap-v0",
                "project_id": "Campaign",
                "roadmap_events": [],
                "roadmap_projection": [
                    {
                        "id": "g1",
                        "name": "Write Book 1",
                        "status": "proposed",
                        "tier": 2,
                        "navigation": {
                            "path": ["g1"],
                            "groups": [{"id": "g1", "label": "Write Book 1", "order": 0, "parent_id": None}],
                        },
                    },
                    {
                        "id": "s1",
                        "name": "Draft Chapter 4",
                        "status": "active",
                        "seat": "active",
                        "navigation": {"path": ["g1"], "current": True},
                    },
                    {
                        "id": "s2",
                        "name": "Polish dialogue",
                        "status": "proposed",
                        "navigation": {"path": ["g1"]},
                    },
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # 1. Rearrange goal to Tier 1
    res_tier = cs.fast_steward_command(
        str(proj_dir),
        "Move Write Book 1 to Tier 1",
        from_cave=True,
    )
    assert res_tier is not None and res_tier.get("ok") is True and res_tier.get("model_called") is False
    rm1 = json.loads(rm_path.read_text(encoding="utf-8"))
    g1 = next(s for s in rm1["roadmap_projection"] if s["id"] == "g1")
    assert g1.get("tier") == 1

    # 2. Mark next step done
    res_done = cs.fast_steward_command(
        str(proj_dir),
        "Mark next step done for Write Book 1",
        from_cave=True,
    )
    assert res_done is not None and res_done.get("ok") is True and res_done.get("model_called") is False
    rm2 = json.loads(rm_path.read_text(encoding="utf-8"))
    s1 = next(s for s in rm2["roadmap_projection"] if s["id"] == "s1")
    assert s1.get("status") == "done"

    # 3. Create new AI Cockpit
    res_create = cs.fast_steward_command(
        str(proj_dir),
        "Create a new AI Cockpit for Chapter 5 Revision under Write Book 1",
        from_cave=True,
    )
    assert res_create is not None and res_create.get("ok") is True and res_create.get("act") == "create_cockpit"
    assert "/steward?dir=" in res_create.get("open_url", "")
