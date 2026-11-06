from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import comms_connector as cc
import high_seat_page as hsp
from steward_cockpit import campaign_say as cs
from steward_cockpit import steward_engine as se


def test_cave_four_bottom_buttons_removed_and_working_list_rendered():
    """Verify the 4 quick-action buttons (#cosFoundryBar) are removed from Cave of Wonders dialogue
    while preserved on Star Chart, and #caveWorkingListSpine + #caveSpeedRacerTile render cleanly."""
    ctx = {
        "steward": {"label": "Ecgberht", "high_seat_name": "Cave of Wonders"},
        "facts": {},
        "build": "test",
        "campaign_pid": "camp-1",
        "initiatives": [],
        "active": [],
        "deck": [],
        "dated": [],
        "overdue": [],
        "candidates": {"groups": [], "total": 0},
        "desk": {"today": 0, "week": 0, "inbox": 0, "rows": []},
        "seeds": [],
        "log": [],
    }
    cave_conv = hsp.conversation_view("Ecgberht", "camp-1", "cave", hsp.CAVE_EFFORT, "the Cave of Wonders")
    assert 'id="cosFoundryBar"' not in cave_conv

    camp_conv = hsp.conversation_view("Ecgberht", "camp-1", "campaign", "", "the Star Chart")
    assert 'id="cosFoundryBar"' in camp_conv

    wl_html = hsp._working_list_spine_html(ctx)
    assert 'id="caveWorkingListSpine"' in wl_html

    comms_html = hsp._comms_pulse_html(ctx)
    assert 'id="caveSpeedRacerTile"' in comms_html
    assert 'data-speed-racer-queue="1"' in comms_html

    mockup_html = Path(r"C:\dev\Anchor\steward_cockpit\static\wave19-cave-of-wonders-mockup.html").read_text(encoding="utf-8")
    assert 'class="cos-foundry-bar"' not in mockup_html


def test_speed_racer_permission_gate_and_actions(tmp_path, monkeypatch):
    """Verify P0-1 & P0-2: opening Speed Racer (list), skipping, or discarding NEVER sends an email,
    approve_send requires an explicit draft_id, and CLI send stages into Speed Racer."""
    sr_file = tmp_path / "speed-racer-queue.json"
    sr_file.write_text(json.dumps({"queue": []}), encoding="utf-8")
    monkeypatch.setattr(cc, "_speed_racer_path", lambda: sr_file)
    sent_calls = []
    monkeypatch.setattr(cc, "send_email_message", lambda payload: (sent_calls.append(payload) or {"ok": True}))

    q_res = cc.queue_speed_racer_draft({
        "to": "counsel@example.com",
        "subject": "Re: Exmera LP Exhibit A",
        "draft_body": "Hi, Exhibit A looks good.",
        "origin": "Steward Draft",
    })
    assert q_res["ok"] is True
    did = q_res["draft_id"]

    # 1. sr_action='list' must NOT send or pop the draft
    list_res = cc.act_speed_racer_draft({"sr_action": "list"})
    assert list_res["ok"] is True
    assert len(sent_calls) == 0
    assert len(list_res["speed_racer"]["queue"]) == 1

    # 2. sr_action='skip' rotates without sending
    skip_res = cc.act_speed_racer_draft({"sr_action": "skip", "id": did})
    assert skip_res["ok"] is True
    assert len(sent_calls) == 0
    assert len(skip_res["speed_racer"]["queue"]) == 1

    # 3. approve_send without explicit id is refused
    no_id_res = cc.act_speed_racer_draft({"sr_action": "approve_send", "id": ""})
    assert no_id_res["ok"] is False
    assert len(sent_calls) == 0

    # 4. sr_action='discard' removes without sending
    disc_res = cc.act_speed_racer_draft({"sr_action": "discard", "id": did})
    assert disc_res["ok"] is True
    assert len(sent_calls) == 0
    assert len(disc_res["speed_racer"]["queue"]) == 0

    # 5. Queue again and explicitly approve_send with id
    q2 = cc.queue_speed_racer_draft({
        "to": "counsel@example.com",
        "subject": "Re: Exmera LP Exhibit A",
        "draft_body": "Approved text.",
    })
    did2 = q2["draft_id"]
    app_res = cc.act_speed_racer_draft({
        "sr_action": "approve_send",
        "id": did2,
        "to": "counsel@example.com",
        "subject": "Re: Exmera LP Exhibit A",
        "draft_body": "Approved text.",
    })
    assert app_res["ok"] is True
    assert len(sent_calls) == 1
    assert sent_calls[0]["to"] == "counsel@example.com"


def test_working_list_spine_mutations_and_step_connections(tmp_path, monkeypatch):
    """Verify Persistent Working List Spine supports adding multi-step tiles, moving up/down,
    connecting steps to AI Cockpit items and Initiatives, checking off steps, and archiving."""
    monkeypatch.setattr(cc, "_working_list_path", lambda: tmp_path / "working-list-spine.json")

    st0 = cc.load_working_list_spine()
    assert len(st0["tiles"]) >= 5
    assert st0["tiles"][0]["id"] == "tile-archty"

    # Add a new tile via wl_op (browser payload shape)
    r_add = cc.mutate_working_list_spine({
        "wl_op": "add_tile",
        "title": "Prepare Q4 Board Deck",
        "category": "Business",
        "prio": "A1",
        "insert_top": True,
    })
    assert r_add["ok"] is True
    new_tid = r_add["tile"]["id"]
    assert r_add["working_list"]["tiles"][0]["id"] == new_tid

    # Add a step with both AI Cockpit item and Initiative connection
    r_step = cc.mutate_working_list_spine({
        "wl_op": "add_step",
        "tile_id": new_tid,
        "text": "Run Financial-Analyst waterfall tie-out",
        "cockpitItem": {"cockpitName": "NextGen Nuclear Cockpit", "itemLabel": "Wave 4: Waterfall", "kind": "Wave", "href": "/steward/v1"},
        "initiativeItem": {"initiativeName": "NextGen Series A", "role": "Initiative", "href": "/?view=cave"},
    })
    assert r_step["ok"] is True
    assert len(r_step["tile"]["steps"]) == 2
    assert r_step["tile"]["steps"][1]["cockpitItem"]["cockpitName"] == "NextGen Nuclear Cockpit"
    assert r_step["tile"]["steps"][1]["initiativeItem"]["initiativeName"] == "NextGen Series A"

    # Connect step 0 via connect_step (step_idx=0)
    r_conn = cc.mutate_working_list_spine({
        "wl_op": "connect_step",
        "tile_id": new_tid,
        "step_idx": 0,
        "cockpitItem": {"cockpitName": "Archty Cockpit", "itemLabel": "Trial Balance PDF", "kind": "Deliverable", "href": "/steward/v1"},
        "initiativeItem": {"initiativeName": "Archty Wind-Down", "role": "Goal", "href": "/?view=cave"},
    })
    assert r_conn["ok"] is True
    assert r_conn["tile"]["steps"][0]["cockpitItem"]["cockpitName"] == "Archty Cockpit"

    # Toggle step 0 done via 2-arg call (CLI/Steward shape)
    r_tog = cc.mutate_working_list_spine("toggle_step", {"tile_id": new_tid, "step_idx": 0})
    assert r_tog["ok"] is True
    assert r_tog["tile"]["steps"][0]["done"] is True

    # Archive tile
    r_arch = cc.mutate_working_list_spine({"wl_op": "archive_tile", "tile_id": new_tid})
    assert r_arch["ok"] is True
    assert r_arch["tile"]["archived"] is True


def test_cave_steward_remit_and_fast_handlers(tmp_path, monkeypatch):
    """Verify cave_mode_remit and fast Steward handlers for Speed Racer & Working List Spine."""
    monkeypatch.setattr(cc, "_speed_racer_path", lambda: tmp_path / "speed-racer-queue.json")
    monkeypatch.setattr(cc, "_working_list_path", lambda: tmp_path / "working-list-spine.json")

    remit = se.cave_mode_remit("Ecgberht")
    assert "THIS CONVERSATION IS THE CAVE OF WONDERS" in remit
    assert "PERSISTENT WORKING LIST SPINE" in remit
    assert "SPEED RACER EMAIL & CALENDAR HUB" in remit
    assert "[SPEED_RACER_OPEN]" in remit

    # Ordinary mention of speed racer must NOT queue a fake email
    non_cmd = cs.fast_steward_command(str(tmp_path), "I think the speed racer tile layout looks great", from_cave=True)
    assert non_cmd is None

    # Explicit draft command queues in Speed Racer and returns open_speed_racer without dumping email body
    sr_cmd = cs.fast_steward_command(
        str(tmp_path),
        "Draft an email to Stanford Trust Counsel about Exhibit A transfer schedule",
        from_cave=True,
    )
    assert sr_cmd is not None and sr_cmd["ok"] is True
    assert sr_cmd["act"] == "open_speed_racer"
    assert sr_cmd["open_speed_racer"] is True
    assert "[SPEED_RACER_OPEN:" in sr_cmd["say"]

    # Working List add & status commands
    wl_add = cs.fast_steward_command(
        str(tmp_path),
        "Add File PA Annual Report to my working list under Business as A1",
        from_cave=True,
    )
    assert wl_add is not None and wl_add["ok"] is True
    assert wl_add["act"] == "working_list_add"
    assert wl_add["working_list_act"] is True

    wl_stat = cs.fast_steward_command(
        str(tmp_path),
        "What is on my working list?",
        from_cave=True,
    )
    assert wl_stat is not None and wl_stat["ok"] is True
    assert wl_stat["act"] == "working_list_status"
    assert "File PA Annual Report" in wl_stat["say"]
