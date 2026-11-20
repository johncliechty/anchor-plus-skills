"""Wave 2 regression suite: Cave Working-List Spine Pruning & Reversible Sender-Normalized Spam Engine."""
from __future__ import annotations

import copy
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

import comms_connector as comms
import paths
import scribe_engine as scribe


REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_COMMS_HERMETIC", "1")
    monkeypatch.setattr(comms, "_CAVE_STEWARD_DISPATCH_HOOK", None)
    monkeypatch.setattr(comms, "_SEND_TRANSPORT_HOOK", None)
    comms._WORKING_LIST_SPINE_CACHE.clear()
    scribe._SCRIBE_MEMORY_CACHE.clear()
    return tmp_path


def _build_50_noisy_auto_proposals_fixture() -> dict:
    """Build a deterministic spine dict with 50 noisy auto-proposals and 2 explicit propose_change entries."""
    proposals: list[dict] = []
    sources = (
        ("prime_inbox", "prime-email:uid-auto-{i}"),
        ("watchlist_24h", "watchlist:wl-auto-{i}:24h"),
        ("watchlist_48h", "watchlist:wl-auto-{i}:48h"),
        ("watchlist_7d", "watchlist:wl-auto-{i}:7d"),
        ("cockpit_all_steps_done", "tile-all-steps-done:tile-auto-{i}"),
        ("cockpit_for_review", "cockpit-review:proj-auto:deliv-{i}"),
    )
    for i in range(50):
        src_name, key_tpl = sources[i % len(sources)]
        sk = key_tpl.format(i=i)
        proposals.append({
            "id": f"prop-auto-{i:02d}",
            "source_key": sk,
            "proposal_op": "add_tile",
            "kind": "add_tile",
            "tile_id": "",
            "title": f"Noisy Auto Proposal {i}",
            "step_text": f"Auto step {i}",
            "priority": 1 if (i % 2 == 0) else 2,
            "category": "Business",
            "due": "2026-11-18",
            "email_uid": f"uid-auto-{i}" if src_name == "prime_inbox" else "",
            "cockpitName": "",
            "cockpitUrl": "",
            "source": src_name,
            "reason": f"Auto generated from {src_name}",
            "created_at": "2026-11-16 12:00 UTC",
        })
    explicit_entries = [
        {
            "id": "prop-explicit-1",
            "source_key": "manual:add_tile:explicit strategic initiative alpha",
            "proposal_op": "add_tile",
            "kind": "add_tile",
            "tile_id": "",
            "title": "Explicit Strategic Initiative Alpha",
            "step_text": "Complete Phase 1 milestone",
            "priority": 1,
            "category": "Research",
            "due": "2026-11-20",
            "cockpitName": "Alpha Cockpit",
            "cockpitUrl": "/steward/v1",
            "source": "steward_cli",
            "reason": "Explicit propose_change entry",
            "created_at": "2026-11-16 14:00 UTC",
        },
        {
            "id": "prop-explicit-2",
            "source_key": "prop:explicit:beta",
            "explicit_propose": True,
            "proposal_op": "archive_tile",
            "kind": "archive_tile",
            "tile_id": "tile-beta",
            "title": "Archive completed effort: Beta",
            "step_text": "",
            "priority": 2,
            "category": "Business",
            "due": "",
            "cockpitName": "",
            "cockpitUrl": "",
            "source": "propose_change",
            "reason": "Explicit user/CLI archive proposal",
            "created_at": "2026-11-16 15:00 UTC",
        },
    ]
    spine = comms._default_working_list_state()
    spine["proposals"] = proposals + explicit_entries
    spine["dismissed_proposal_keys"] = ["prime-email:already-dismissed-0"]
    return spine


def test_pure_prune_stale_auto_proposals_50_noisy_vs_explicit_and_idempotence(isolated_data):
    live_spine_path = REPO_ROOT / ".anchor" / "working-list-spine.json"
    live_before_bytes = live_spine_path.read_bytes() if live_spine_path.exists() else None

    fixture_spine = _build_50_noisy_auto_proposals_fixture()
    original_snapshot = copy.deepcopy(fixture_spine)

    # 1) Pure function performs zero I/O, does not mutate input in-place, moves 50 noisy auto-proposals to dismissed_proposal_keys,
    #    and preserves explicit propose_change entries.
    pruned_spine, pruned_keys = comms.prune_stale_auto_proposals(fixture_spine)
    assert fixture_spine == original_snapshot, "prune_stale_auto_proposals must be pure and not mutate its input dict"
    assert len(pruned_keys) == 50
    assert all(
        k.startswith(("prime-email:", "watchlist:", "tile-all-steps-done:", "cockpit-review:"))
        for k in pruned_keys
    )
    surviving = pruned_spine["proposals"]
    assert [p["id"] for p in surviving] == ["prop-explicit-1", "prop-explicit-2"]
    assert all(p["status"] == "pending" for p in surviving)
    for k in pruned_keys:
        assert k in pruned_spine["dismissed_proposal_keys"]
    assert "prime-email:already-dismissed-0" in pruned_spine["dismissed_proposal_keys"]
    assert not (isolated_data / ".anchor" / "working-list-spine.json").exists(), "Pure function must perform zero disk I/O"

    # 2) Repeat-invocation test proving pure idempotence
    pruned_again, pruned_keys_again = comms.prune_stale_auto_proposals(pruned_spine)
    assert pruned_keys_again == []
    assert pruned_again == pruned_spine

    # 3) Non-pending status entries are also pruned into dismissed/accepted keys
    mixed_status_spine = copy.deepcopy(pruned_spine)
    mixed_status_spine["proposals"].append({
        "id": "prop-stale-dismissed",
        "source_key": "manual:add_tile:already dismissed item",
        "status": "dismissed",
        "source": "steward_cli",
        "title": "Already Dismissed",
    })
    mixed_cleaned, mixed_pruned = comms.prune_stale_auto_proposals(mixed_status_spine)
    assert mixed_pruned == ["manual:add_tile:already dismissed item"]
    assert [p["id"] for p in mixed_cleaned["proposals"]] == ["prop-explicit-1", "prop-explicit-2"]

    if live_before_bytes is not None:
        assert live_spine_path.read_bytes() == live_before_bytes, "Live .anchor/working-list-spine.json must never be modified by tests"


def test_imperative_shell_write_lock_dated_bak_persistence_and_repeat_idempotence(isolated_data):
    spine_path = isolated_data / ".anchor" / "working-list-spine.json"
    spine_path.parent.mkdir(parents=True, exist_ok=True)
    fixture_spine = _build_50_noisy_auto_proposals_fixture()
    raw_pre_prune = json.dumps(fixture_spine, indent=2)
    spine_path.write_text(raw_pre_prune, encoding="utf-8")

    # Trigger via load_working_list_spine() -> prune_and_persist_working_list_spine()
    loaded = comms.load_working_list_spine()
    assert [p["id"] for p in loaded["proposals"]] == ["prop-explicit-1", "prop-explicit-2"]
    assert comms.count_pending_proposals(loaded) == 2

    # Verify dated .bak backup was created with original pre-prune content
    bak_files = list(spine_path.parent.glob("working-list-spine.json.*.bak"))
    assert len(bak_files) == 1
    assert date.today().isoformat() in bak_files[0].name
    bak_doc = json.loads(bak_files[0].read_text(encoding="utf-8"))
    assert len(bak_doc["proposals"]) == 52

    # Verify on-disk spine was atomically updated
    persisted_doc = json.loads(spine_path.read_text(encoding="utf-8"))
    assert [p["id"] for p in persisted_doc["proposals"]] == ["prop-explicit-1", "prop-explicit-2"]
    assert len(persisted_doc["dismissed_proposal_keys"]) == 51

    # Repeat invocation is idempotent (0 newly pruned keys, no extra .bak files, bytes unchanged)
    bytes_after_first = spine_path.read_bytes()
    bak_bytes_after_first = bak_files[0].read_bytes()
    _, second_keys = comms.prune_and_persist_working_list_spine(spine_path)
    assert second_keys == []
    assert spine_path.read_bytes() == bytes_after_first
    assert bak_files[0].read_bytes() == bak_bytes_after_first


def test_pending_only_counting_live_reconcile_cap_3_vs_explicit_cap_50_refusal(isolated_data):
    now_ref = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
    today_ref = date(2026, 11, 17)

    # 1) Pending proposal counting filters strictly by status == 'pending'
    sample_props = [
        {"id": "p1", "status": "pending"},
        {"id": "p2", "status": "dismissed"},
        {"id": "p3", "status": "accepted"},
        {"id": "p4", "status": "done"},
        {"id": "p5", "status": "pending"},
    ]
    assert comms.count_pending_proposals(sample_props) == 2
    assert comms.count_pending_proposals({"proposals": sample_props}) == 2

    # 2) Automatic live reconcile caps suggestions at <=3 pending items sourced exclusively from
    #    explicit steward_dispatch or active-effort P1 milestones (ignoring noisy prime_inbox / watchlist / archive_tile)
    t_active = comms.mutate_working_list_spine("add_tile", {
        "title": "Core Architecture Overhaul",
        "category": "Research",
        "priority": 1,
        "cockpitName": "Core Cockpit",
        "steps": [{"id": "st-c1", "text": "Complete theorem proof", "done": False}],
    })["tile"]
    t_done_steps = comms.mutate_working_list_spine("add_tile", {
        "title": "Completed Side Task",
        "category": "Business",
        "priority": 2,
        "steps": [{"id": "st-s1", "text": "Already finished step", "done": True}],
    })["tile"]

    noisy_emails = [
        {
            "uid": f"uid-noisy-{i}",
            "from": f"Sender {i} <sender{i}@example.org>",
            "subject": f"Action required: Noisy request {i}",
            "snippet": "Please review by Friday.",
            "action_required": True,
            "steward_score": 88,
        }
        for i in range(8)
    ]
    noisy_watchlist = [
        {
            "id": f"wl-noisy-{i}",
            "title": f"Noisy Watchlist Deadline {i}",
            "due": (now_ref + timedelta(hours=12)).isoformat(),
            "status": "open",
        }
        for i in range(6)
    ]
    cockpit_events = [
        {
            "kind": "deliverable_for_review",
            "cockpit_name": "Core Cockpit",
            "deliverable_id": f"deliv-p1-{i}",
            "title": f"P1 Milestone Deliverable {i}",
            "priority": 1,
        }
        for i in range(5)
    ] + [
        {
            "kind": "deliverable_for_review",
            "cockpit_name": "Low Priority Cockpit",
            "deliverable_id": "deliv-p3",
            "title": "Non-P1 Deliverable",
            "priority": 3,
        }
    ]

    live_rec = comms.reconcile_working_list_activity(
        cockpit_events=cockpit_events,
        dispatch_event={
            "uid": "uid-disp-live-1",
            "subject": "Critical Counsel Dispatch",
            "from": "Counsel <counsel@example.com>",
            "comment": "Prepare immediate response packet",
            "priority": 1,
        },
        important_emails=noisy_emails,
        watchlist_items=noisy_watchlist,
        now_dt=now_ref,
        today=today_ref,
        live_reconcile=True,
    )
    assert live_rec["ok"] is True
    live_props = live_rec["working_list"]["proposals"]
    assert len(live_props) == comms.MAX_LIVE_RECONCILE_PROPOSALS == 3
    assert comms.count_pending_proposals(live_props) == 3
    assert any(p["source"] == "steward_dispatch" for p in live_props)
    assert any(p["source"] == "active_p1_milestone" for p in live_props)
    for p in live_props:
        assert p["status"] == "pending"
        assert p["source"] in ("steward_dispatch", "active_p1_milestone")
        assert not p["source_key"].startswith(("prime-email:", "watchlist:", "tile-all-steps-done:"))
        assert "explicit_kwarg" not in p
    assert t_active["id"] and t_done_steps["id"]

    # Orphan P1 cockpit events (no active effort on The List) are excluded in live_reconcile mode,
    # and the working_list_reconcile HTTP route defaults to live_reconcile=True without noisy watchlist floods
    comms.save_working_list_spine(comms._default_working_list_state())
    orphan_rec = comms.reconcile_working_list_activity(
        cockpit_events=[{
            "kind": "deliverable_for_review",
            "cockpit_name": "Orphan Cockpit",
            "deliverable_id": "deliv-orphan-1",
            "title": "Orphan P1 Deliverable",
            "priority": 1,
        }],
        watchlist_items=[],
        important_emails=[],
        now_dt=now_ref,
        today=today_ref,
        live_reconcile=True,
    )
    assert orphan_rec["added_proposals"] == []
    comms.add_watchlist_item({"title": "Route Watchlist Probe", "due": (today_ref + timedelta(days=1)).isoformat()})
    route_rec, route_code = comms.handle_comms_post({"action": "working_list_reconcile"})
    assert route_code == 200 and route_rec["ok"] is True
    assert comms.load_working_list_spine()["proposals"] == []

    # 3) Explicit mutate_working_list_spine('propose_change') honors MAX_WORKING_LIST_PROPOSALS = 50 and refuses #51
    comms.save_working_list_spine(comms._default_working_list_state())
    for i in range(comms.MAX_WORKING_LIST_PROPOSALS):
        res_p = comms.mutate_working_list_spine("propose_change", {
            "proposal_op": "add_tile",
            "title": f"Explicit Proposal {i}",
            "source_key": f"explicit:cap:{i}",
            "priority": 2,
            "category": "Business",
        })
        assert res_p["ok"] is True
    assert comms.count_pending_proposals(comms.load_working_list_spine()) == 50

    refused_51 = comms.mutate_working_list_spine("propose_change", {
        "proposal_op": "add_tile",
        "title": "Explicit Proposal 51 Over Cap",
        "source_key": "explicit:cap:51",
    })
    assert refused_51["ok"] is False
    assert refused_51["status_code"] == 400
    assert refused_51["failure_state"] == "dependency-returns-garbage"


def test_reversible_parseaddr_spam_unspam_protections_shared_domains_and_side_effects(isolated_data, monkeypatch):
    remote_read_calls: list[dict] = []

    def _track_remote_read(**kw):
        remote_read_calls.append(dict(kw))
        return {"ok": True}

    monkeypatch.setattr(comms, "mark_email_read_remote", _track_remote_read)

    # 1) parseaddr normalization & invalid sender rejection
    assert comms.normalize_spam_sender("Spam Bot <SPAM.BOT@Example.COM>") == "spam.bot@example.com"
    assert scribe.normalize_spam_sender('"Promo, Inc." <Deals@Example.org>') == "deals@example.org"
    assert comms.normalize_spam_sender("Inbox") == ""
    assert comms.normalize_spam_sender("not-an-email") == ""
    assert scribe.normalize_spam_sender("") == ""

    # 2) Configure own account, upgraded sender, replied correspondent, shared-domain colleague, and spammer
    comms.save_comms_config({
        "accounts": [
            {"id": "acc-1", "family": "gmail", "email": "owner@example.com", "label": "Work", "status": "connected"}
        ],
        "manual_logs": [
            {
                "id": "log-sent-1",
                "direction": "sent",
                "to": "Trusted Partner <replied@example.org>",
                "subject": "Re: Partnership terms",
                "body": "Confirmed.",
                "at": "2026-11-16 10:00",
            }
        ],
    })
    prefs_init = comms.load_triage_prefs()
    assert "spam_senders" in prefs_init and prefs_init["spam_senders"] == []
    assert "spam_uids" in prefs_init and prefs_init["spam_uids"] == []
    prefs_init["upgraded_senders"] = ["upgraded@example.net"]
    comms.save_triage_prefs(prefs_init)

    headers = [
        {
            "uid": "u-spam-1",
            "account_id": "acc-1",
            "from": "Flash Promo <spammer@example.com>",
            "sender_email": "spammer@example.com",
            "subject": "Action required: Claim your prize now",
            "snippet": "Deadline today!",
            "date": "2026-11-17 09:00",
            "is_read": False,
        },
        {
            "uid": "u-colleague-1",
            "account_id": "acc-1",
            "from": "Colleague Same Domain <colleague@example.com>",
            "sender_email": "colleague@example.com",
            "subject": "Action required: Review Q4 slides",
            "snippet": "Please review before 3pm.",
            "date": "2026-11-17 09:05",
            "is_read": False,
        },
        {
            "uid": "u-spoof-own",
            "account_id": "acc-1",
            "from": "Owner Spoof <owner@example.com>",
            "sender_email": "owner@example.com",
            "subject": "Spoofed self note",
            "snippet": "Suspicious link",
            "date": "2026-11-17 09:10",
            "is_read": False,
        },
        {
            "uid": "u-spoof-upgraded",
            "account_id": "acc-1",
            "from": "Upgraded Contact <upgraded@example.net>",
            "sender_email": "upgraded@example.net",
            "subject": "Odd message from upgraded contact",
            "snippet": "Check this out",
            "date": "2026-11-17 09:12",
            "is_read": False,
        },
        {
            "uid": "u-spoof-replied",
            "account_id": "acc-1",
            "from": "Trusted Partner <replied@example.org>",
            "sender_email": "replied@example.org",
            "subject": "Unexpected promo forward",
            "snippet": "Forwarding promo",
            "date": "2026-11-17 09:15",
            "is_read": False,
        },
    ]
    comms.save_comms_sync({
        "synced_at": "2026-11-17 09:20",
        "calendar_events": [],
        "email_headers": headers,
        "sent_email_headers": [],
    })

    # Seed Speed Racer draft, Working List proposal, and Watchlist entry for u-spam-1
    comms.queue_speed_racer_draft({
        "uid": "u-spam-1",
        "to": "Flash Promo <spammer@example.com>",
        "subject": "Re: Claim your prize now",
        "draft_body": "Hi,\n\nNo thank you.\n\nBest,",
        "preserve_manual_draft": True,
    })
    comms.mutate_working_list_spine("propose_change", {
        "proposal_op": "add_tile",
        "title": "Follow up on prize email",
        "source_key": "prime-email:u-spam-1",
        "email_uid": "u-spam-1",
    })
    wl_spam_item = comms.add_watchlist_item({
        "title": "Prize deadline follow-up",
        "due": "2026-11-18",
        "email_uid": "u-spam-1",
    })["item"]

    # 3) Mark u-spam-1 as spam (using unnormalized display header)
    spam_res, spam_code = comms.handle_comms_post({
        "action": "email_triage_feedback",
        "uid": "u-spam-1",
        "sender": "Flash Promo <SPAMMER@Example.com>",
        "subject": "Action required: Claim your prize now",
        "feedback": "spam",
    })
    assert spam_code == 200 and spam_res["ok"] is True
    assert spam_res["sender_protected"] is False

    # Verify load_triage_prefs & Scribe memory persisted normalized spam_senders and spam_uids
    prefs_after_spam = comms.load_triage_prefs()
    assert prefs_after_spam["spam_senders"] == ["spammer@example.com"]
    assert "u-spam-1" in prefs_after_spam["spam_uids"]
    scribe_mem_after = scribe.load_scribe_memory()
    assert "spammer@example.com" in scribe_mem_after["spam_senders"]
    assert "u-spam-1" in scribe_mem_after["spam_uids"]

    # Verify Speed Racer draft, proposal, and open Watchlist entry were cleared
    assert all(d.get("uid") != "u-spam-1" for d in (comms.load_speed_racer_queue().get("queue") or []))
    wl_after_spam = comms.load_working_list_spine()
    assert all(p.get("email_uid") != "u-spam-1" for p in wl_after_spam["proposals"])
    assert "prime-email:u-spam-1" in wl_after_spam["dismissed_proposal_keys"]
    open_watchlist, _ = comms.get_watchlist_response(include_done=False)
    assert all(w.get("id") != wl_spam_item["id"] for w in open_watchlist["items"])

    # Repeat spam invocation is idempotent
    spam_res_2 = comms.record_email_triage_feedback({
        "uid": "u-spam-1",
        "sender": "Flash Promo <SPAMMER@Example.com>",
        "feedback": "spam",
    })
    assert spam_res_2["ok"] is True
    assert comms.load_triage_prefs()["spam_senders"].count("spammer@example.com") == 1
    assert comms.load_triage_prefs()["spam_uids"].count("u-spam-1") == 1

    # 4) Future email from spammer@example.com is suppressed across sync_comms_now & classify_inbox_emails
    #    while shared-domain colleague@example.com is untouched
    headers_with_future = [dict(h) for h in headers] + [
        {
            "uid": "u-spam-future-2",
            "account_id": "acc-1",
            "from": "Another Alias <SPAMMER@example.com>",
            "sender_email": "spammer@example.com",
            "subject": "Action required: Second spam wave",
            "snippet": "Urgent deadline!",
            "date": "2026-11-17 10:00",
            "is_read": False,
        }
    ]
    comms.save_comms_config({
        "accounts": [
            {
                "id": "acc-1",
                "family": "gmail",
                "email": "owner@example.com",
                "label": "Work",
                "imap_host": "imap.example.com",
                "status": "connected",
            }
        ],
        "manual_logs": [
            {
                "id": "log-sent-1",
                "direction": "sent",
                "to": "Trusted Partner <replied@example.org>",
                "subject": "Re: Partnership terms",
                "body": "Confirmed.",
                "at": "2026-11-16 10:00",
            }
        ],
    })
    monkeypatch.setattr(comms, "get_account_secret", lambda _aid: "secret-token")
    monkeypatch.setattr(comms, "fetch_google_caldav_events", lambda *_a, **_kw: (True, "ok", []))
    monkeypatch.setattr(comms, "fetch_sent_headers", lambda *_a, **_kw: (True, "ok", []))
    monkeypatch.setattr(
        comms,
        "fetch_imap_headers",
        lambda *_a, **_kw: (True, "ok", [dict(h) for h in headers_with_future]),
    )

    sync_spammed = comms.sync_comms_now(today=date(2026, 11, 17))
    assert sync_spammed["ok"] is True
    stored_spammed = {h["uid"]: h for h in comms.load_comms_sync()["email_headers"]}
    assert stored_spammed["u-spam-1"]["is_spam"] is True
    assert stored_spammed["u-spam-1"]["is_read"] is True
    assert stored_spammed["u-spam-future-2"]["is_spam"] is True
    assert stored_spammed["u-spam-future-2"]["is_read"] is True
    assert stored_spammed["u-colleague-1"]["is_read"] is False

    imp_f, oth_f = comms.classify_inbox_emails(comms.load_comms_sync()["email_headers"], comms.load_triage_prefs())
    visible_uids = {m["uid"] for m in (imp_f + oth_f)}
    assert "u-spam-1" not in visible_uids
    assert "u-spam-future-2" not in visible_uids
    assert "u-colleague-1" in visible_uids, "Shared domain @example.com must never be blackholed"

    # 5) Protected correspondents (own, upgraded, replied) suppress only the single message UID, never the sender
    for spoof_uid, spoof_from, spoof_addr in (
        ("u-spoof-own", "Owner Spoof <owner@example.com>", "owner@example.com"),
        ("u-spoof-upgraded", "Upgraded Contact <upgraded@example.net>", "upgraded@example.net"),
        ("u-spoof-replied", "Trusted Partner <replied@example.org>", "replied@example.org"),
    ):
        prot_res = comms.record_email_triage_feedback({
            "uid": spoof_uid,
            "sender": spoof_from,
            "feedback": "spam",
        })
        assert prot_res["ok"] is True
        assert prot_res["sender_protected"] is True
        cur_prefs = comms.load_triage_prefs()
        assert spoof_uid in cur_prefs["spam_uids"]
        assert spoof_addr not in cur_prefs["spam_senders"]

    # Future email from protected correspondent still classifies normally
    headers_prot_future = [dict(h) for h in headers_with_future] + [
        {
            "uid": "u-replied-legit-2",
            "account_id": "acc-1",
            "from": "Trusted Partner <replied@example.org>",
            "sender_email": "replied@example.org",
            "subject": "Action required: Signed closing packet",
            "snippet": "Please review attached closing packet.",
            "date": "2026-11-17 10:30",
            "is_read": False,
        }
    ]
    imp_p, oth_p = comms.classify_inbox_emails(headers_prot_future, comms.load_triage_prefs())
    prot_visible = {m["uid"] for m in (imp_p + oth_p)}
    assert "u-spoof-replied" not in prot_visible
    assert "u-replied-legit-2" in prot_visible

    # 6) Reversible unspam restores sender, unread status, proposals, Speed Racer draft, and Watchlist cleanly across sync_comms_now
    unspam_res, unspam_code = comms.handle_comms_post({
        "action": "email_triage_feedback",
        "uid": "u-spam-1",
        "sender": "Flash Promo <spammer@example.com>",
        "feedback": "unspam",
    })
    assert unspam_code == 200 and unspam_res["ok"] is True
    prefs_unspammed = comms.load_triage_prefs()
    assert "spammer@example.com" not in prefs_unspammed["spam_senders"]
    assert "u-spam-1" not in prefs_unspammed["spam_uids"]
    assert "spammer@example.com" not in scribe.load_scribe_memory()["spam_senders"]

    sync_unspammed = comms.sync_comms_now(today=date(2026, 11, 17))
    assert sync_unspammed["ok"] is True
    stored_unspammed = {h["uid"]: h for h in comms.load_comms_sync()["email_headers"]}
    assert stored_unspammed["u-spam-1"]["is_read"] is False
    assert "is_spam" not in stored_unspammed["u-spam-1"]
    assert "spam_suppressed" not in stored_unspammed["u-spam-1"]
    assert stored_unspammed["u-spam-future-2"]["is_read"] is False
    assert "is_spam" not in stored_unspammed["u-spam-future-2"]

    imp_u, oth_u = comms.classify_inbox_emails(comms.load_comms_sync()["email_headers"], prefs_unspammed)
    restored_uids = {m["uid"] for m in (imp_u + oth_u)}
    assert "u-spam-1" in restored_uids
    assert "u-spam-future-2" in restored_uids
    wl_after_unspam = comms.load_working_list_spine()
    assert any(p.get("source_key") == "prime-email:u-spam-1" for p in wl_after_unspam["proposals"])
    assert "prime-email:u-spam-1" not in wl_after_unspam["dismissed_proposal_keys"]
    open_wl_after_unspam, _ = comms.get_watchlist_response(include_done=False)
    assert any(w.get("id") == wl_spam_item["id"] for w in open_wl_after_unspam["items"])
    assert any(d.get("uid") == "u-spam-1" for d in (comms.load_speed_racer_queue().get("queue") or []))

    # Repeat unspam is idempotent: if user has since read u-spam-1, repeat unspam keeps is_read=True and makes 0 remote calls
    sync_read_doc = comms.load_comms_sync()
    for _h_r in sync_read_doc["email_headers"]:
        if _h_r.get("uid") == "u-spam-1":
            _h_r["is_read"] = True
    comms.save_comms_sync(sync_read_doc)
    calls_before_repeat = len(remote_read_calls)

    unspam_res_2 = comms.record_email_triage_feedback({
        "uid": "u-spam-1",
        "sender": "Flash Promo <spammer@example.com>",
        "feedback": "unspam",
    })
    assert unspam_res_2["ok"] is True
    assert comms.load_triage_prefs()["spam_senders"] == []
    assert len(remote_read_calls) == calls_before_repeat
    stored_after_repeat = {h["uid"]: h for h in comms.load_comms_sync()["email_headers"]}
    assert stored_after_repeat["u-spam-1"]["is_read"] is True

    # Positive upgrade clears any prior spam_senders / Scribe spam penalty consistently
    assert comms.record_email_triage_feedback({
        "uid": "u-spam-1",
        "account_id": "psu",
        "sender": "Flash Promo <spammer@example.com>",
        "sender_email": "spammer@example.com",
        "subject": "Follow-up Pitch",
        "feedback": "spam",
    })["ok"] is True
    assert "spammer@example.com" in comms.load_triage_prefs()["spam_senders"]

    res_up = comms.record_email_triage_feedback({
        "uid": "u-spam-1",
        "account_id": "psu",
        "sender": "Jordan Counsel <spammer@example.com>",
        "sender_email": "spammer@example.com",
        "subject": "Follow-up Pitch",
        "feedback": "upgrade",
    })
    assert res_up["ok"] is True
    assert "spammer@example.com" not in comms.load_triage_prefs()["spam_senders"]
    sc_after_up = scribe.score_email_interest({
        "uid": "u-spam-3",
        "account_id": "psu",
        "from": "Jordan Counsel <spammer@example.com>",
        "sender_email": "spammer@example.com",
        "subject": "Requested Contract Draft",
    })
    assert sc_after_up["is_spam"] is False
    assert sc_after_up["interest_delta"] > 0


def test_two_process_concurrent_spine_prune_and_propose(isolated_data):
    spine_path = isolated_data / ".anchor" / "working-list-spine.json"
    spine_path.parent.mkdir(parents=True, exist_ok=True)
    spine_path.write_text(json.dumps(_build_50_noisy_auto_proposals_fixture(), indent=2), encoding="utf-8")

    worker_code = textwrap.dedent(
        """
        import sys
        import time
        import comms_connector as comms

        wid = sys.argv[1]
        comms.prune_and_persist_working_list_spine()
        for i in range(10):
            res = comms.mutate_working_list_spine("propose_change", {
                "proposal_op": "add_tile",
                "title": f"Concurrent Worker {wid} Proposal {i}",
                "source_key": f"manual:conc:{wid}:{i}",
                "priority": 1,
                "category": "Research",
            })
            assert res.get("ok") is True, f"propose_change failed: {res}"
            time.sleep(0.002)
        """
    )
    env = dict(os.environ)
    env["ANCHOR_DATA_DIR"] = str(isolated_data)
    env["ANCHOR_COMMS_HERMETIC"] = "1"

    procs = [
        subprocess.Popen(
            [sys.executable, "-c", worker_code, f"w{idx}"],
            cwd=str(REPO_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for idx in range(2)
    ]
    for p in procs:
        out, err = p.communicate(timeout=25)
        assert p.returncode == 0, f"Concurrent worker failed: {out} {err}"

    final_spine = comms.load_working_list_spine()
    surviving_keys = {p["source_key"] for p in final_spine["proposals"]}
    # 2 initial explicit + 20 concurrent explicit = 22 total pending explicit proposals, 0 noisy auto-proposals
    assert len(surviving_keys) == 22
    assert comms.count_pending_proposals(final_spine) == 22
    for wid in ("w0", "w1"):
        for i in range(10):
            assert f"manual:conc:{wid}:{i}" in surviving_keys
    assert len(final_spine["dismissed_proposal_keys"]) == 51
    bak_files = list(spine_path.parent.glob("working-list-spine.json.*.bak"))
    assert len(bak_files) == 1

