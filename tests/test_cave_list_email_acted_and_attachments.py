# -*- coding: utf-8 -*-
import json
from pathlib import Path
import comms_connector
import high_seat_page


def test_the_list_starts_collapsed_and_items_start_as_single_line_tiles():
    html = high_seat_page._working_list_spine_html({})
    # 1. The List section starts collapsed as a single tile
    assert 'id="caveWorkingListSpine"' in html
    assert 'id="wlSpineBody" hidden' in html
    assert 'Items on The List' in html or 'Item on The List' in html

    # 2. Catalogs for AI Cockpits (Active -> On Deck -> Project) and Star Chart Goals/Initiatives are present
    wl = comms_connector.load_working_list_spine()
    ck_cat = wl.get("cockpits_dropdown_catalog") or []
    goals_cat = wl.get("goals_dropdown_catalog") or []
    folders_cat = wl.get("project_folders_catalog") or []
    assert isinstance(ck_cat, list) and len(ck_cat) > 0
    assert isinstance(goals_cat, list) and len(goals_cat) > 0
    assert isinstance(folders_cat, list) and len(folders_cat) > 0

    # Verify ordering of cockpits_dropdown_catalog: active first, on_deck second, project third
    seats = [c.get("seat") for c in ck_cat]
    if "active" in seats and "on_deck" in seats:
        assert seats.index("active") < seats.index("on_deck")
    if "on_deck" in seats and "project" in seats:
        assert seats.index("on_deck") < seats.index("project")


def test_hollie_meyer_and_replied_emails_auto_move_to_acted_upon():
    sync_path = Path(r"C:\dev\Anchor\.anchor\comms-sync.json")
    sync_data = json.loads(sync_path.read_text(encoding="utf-8"))
    prefs = comms_connector.load_triage_prefs()
    imp, oth = comms_connector.classify_inbox_emails(
        sync_data.get("email_headers") or [],
        prefs=prefs,
        sent_headers=sync_data.get("sent_email_headers") or [],
    )
    acted = prefs.get("_acted_upon_resolved") or comms_connector.gather_acted_upon_emails()

    # Hollie Meyer email must not be in Active Inbox (important or other)
    active_froms = [str(e.get("from") or "") for e in (imp + oth)]
    assert not any("Meyer, Hollie" in f for f in active_froms), "Hollie Meyer should be moved out of Active Inbox"

    # Hollie Meyer must be in Acted Upon with ✓ Replied status
    hollie_acted = [e for e in acted if "Meyer, Hollie" in str(e.get("from") or "")]
    assert len(hollie_acted) >= 1
    assert "Replied" in str(hollie_acted[0].get("acted_status") or "")


def test_attachment_preview_docx_and_pdf():
    res = comms_connector.preview_email_attachment(
        {
            "name": "Axmra-Request-for-Consent-to-Transfer-John-Liechty-Holding-Company-2026-11-04.docx",
            "path": r"/workspace/Campaign\Cave of Wonders\teaching-reminders\Axmra-Request-for-Consent-to-Transfer-John-Liechty-Holding-Company-2026-11-04.docx",
        }
    )
    assert res.get("ok") is True
    assert res.get("kind") == "docx"
    assert len(res.get("preview_text") or "") > 500
    assert "<p" in (res.get("preview_html") or "")
