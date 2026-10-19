"""Saved Campaign placements must reach the rendered Active and On deck shelves."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from high_seat_page import _seat_shelves, campaign_initiatives, seated
from steward_cockpit.campaign_parts import resolve_parts
from steward_cockpit.steward_campaign import read_map


def test_saved_seats_survive_reader_and_render_in_requested_order(tmp_path):
    goal = {
        "id": "work", "name": "Work", "status": "proposed", "tier": 1,
        "navigation": {"path": ["work"], "groups": [
            {"id": "work", "label": "Work", "parent_id": None, "order": 0}
        ]},
    }
    entries = [
        {"id": key, "name": title, "folder_path": str(tmp_path)}
        for key, title in [("a", "Alpha"), ("b", "Beta"), ("c", "Gamma")]
    ]
    steps = [goal] + [
        {"id": key, "name": title, "status": "proposed", "ref": "project:" + key,
         "seat": seat, "seat_order": order, "navigation": {"path": ["work"]}}
        for key, title, seat, order in [
            ("a", "Alpha", "active", 1), ("b", "Beta", "active", 0),
            ("c", "Gamma", "deck", 0)
        ]
    ]
    roadmap = tmp_path / "roadmap.json"
    roadmap.write_text(json.dumps({"roadmap_projection": steps}), encoding="utf-8")
    original = roadmap.read_bytes()
    registry = {entry["id"]: entry for entry in entries}

    for _ in range(2):  # A fresh read and render must preserve the same seats.
        loaded = read_map(str(tmp_path))["steps"]
        resolved = resolve_parts(loaded, lookup=registry.get)
        goals = campaign_initiatives(loaded, resolved)
        assert [part["id"] for _, part in seated(goals, "active")] == ["b", "a"]
        assert [part["id"] for _, part in seated(goals, "deck")] == ["c"]
        html = _seat_shelves({"initiatives": goals, "entries": entries, "facts": {}})
        active_html, deck_html = html.split('id="shDeck"', 1)
        assert active_html.index('id="card-b"') < active_html.index('id="card-a"')
        assert 'id="card-c"' not in active_html
        assert 'id="card-c"' in deck_html
    assert roadmap.read_bytes() == original
