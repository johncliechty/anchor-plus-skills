"""Wave 21 Desktop Ad-Hoc AI Cockpit & Cross-Mothership Collaboration unit tests (2026-10-19).

Covers:
1. Classic Anchor navigation bar on /desk with real Foundry/Brand icons (Cave of Wonders, Star Chart, Anchor Doctor, Zombie Hunter, Skill Foundry, Small Items AI Cockpit).
2. Unified Ad-Hoc & Admin Triage + Cross-Mothership Collaboration strip (#deskTriage, #deskMothershipStrip, #deskMothershipDrawer).
3. Embedded Aladdin - The Desk Steward panel (#deskStewardPanel, #deskFoundryBar, #deskStewardForm) with 4 Foundry quick-action buttons.
4. Sub-20ms deterministic Desk Steward command parser (desk.steward_command) for adding items, marking items done, marking all done, promoting an item to a cockpit, and creating substantial cockpits.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import desk  # noqa: E402
import desk_page  # noqa: E402

GRAY = lambda f: {"light": "gray", "word": "idle", "why": ""}  # noqa: E731


def test_wave21_desk_page_renders_triage_mothership_steward_and_foundry_icons(tmp_path):
    root = tmp_path / "Desk"
    desk.add_item("Renew parking permit", root=root)
    desk.new_cockpit("October Expense Audit", root=root)
    ctx = {
        "build": "w21-test",
        "steward": {"label": "Aladdin", "high_seat": "aladdin-cave-of-wonders.jpg"},
        "entry": {"id": "desk1"},
        "desk": desk.summary(GRAY, root=root),
        "campaign_pid": "df56",
        "logged_in": True,
        "mothership": {
            "identity": {"id": "john-mothership", "label": "John · Mother Ship", "role": "lead"},
            "peers": [{"id": "merrill-ms", "label": "Merrill Mother Ship", "status": "ready"}],
        },
    }
    html = desk_page.render_desk_html(ctx)

    # 1. Navigation bar with real Foundry & Brand icons
    assert "/vendor/brand/aladdin-high-seat-cave.jpg" in html
    assert "/vendor/brand/campaign-aladdin-star-chart.jpg" in html
    assert "/vendor/brand/zombie-hunter-reaper.jpg" in html
    assert "/vendor/brand/skill-foundry-icon.jpg" in html
    assert "/vendor/brand/desk-tab-aladdin.png" in html
    assert "/vendor/brand/new-cockpit-icon.jpg" in html
    assert "/vendor/brand/brainstorm-icon.jpg" in html
    assert "/vendor/brand/crucible-icon.svg" in html

    # 2. Unified Ad-Hoc Triage & Cross-Mothership Strip
    assert 'id="deskTriage"' in html
    assert 'id="deskMothershipStrip"' in html
    assert 'id="deskMothershipDrawer"' in html
    assert "John &middot; Mother Ship" in html or "John · Mother Ship" in html
    assert "Merrill Mother Ship" in html

    # 3. Embedded Desk Steward Panel
    assert 'id="deskStewardPanel"' in html
    assert 'id="deskFoundryBar"' in html
    assert 'id="deskStewardForm"' in html
    assert "ALADDIN &mdash; THE DESK" in html


def test_wave21_desk_steward_command_executes_deterministically(tmp_path):
    root = tmp_path / "Desk"
    desk.ensure_small_items(root)

    # 1. Add item
    r1 = desk.steward_command("Add small item: Order replacement monitor cable", root=root)
    assert r1["ok"] and r1["mutated"] is True
    items = desk.read_items(root)
    assert len(items) == 1 and "monitor cable" in items[0]["text"]

    # 2. Add second item and promote it to its own cockpit
    desk.steward_command("Add: Prepare November Travel Itinerary", root=root)
    r2 = desk.steward_command("Promote November Travel Itinerary to cockpit", root=root)
    assert r2["ok"] and r2["mutated"] is True
    assert "Prepare November Travel Itinerary" in desk.cockpit_dirs(root)

    # 3. Create new substantial cockpit directly
    r3 = desk.steward_command("Create a new cockpit for Tax Filing 2026", root=root)
    assert r3["ok"] and r3["dir"] == "Tax Filing 2026"
    assert "Tax Filing 2026" in desk.cockpit_dirs(root)

    # 4. Mark all remaining small items done
    r4 = desk.steward_command("Mark all small items done", root=root)
    assert r4["ok"] and r4["mutated"] is True
    open_left = [i for i in desk.read_items(root) if i.get("status") == "open"]
    assert len(open_left) == 0
