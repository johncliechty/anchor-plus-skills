"""Tests for Wave 12 (Anvil Core Extraction + Hypothesis Differential Equivalence)
and Wave 15 (Deep Hardening of Waves 6b, 7, 9, and 11).
"""
from __future__ import annotations

import hashlib
import base64
import json
from datetime import date, timedelta
from pathlib import Path

from hypothesis import given, settings, strategies as st

import campaign_page
import comms_connector
import high_seat_core
import high_seat_page
import mothership_collab


# ── Wave 12: Hypothesis Property-Based & Differential Equivalence Tests ────────────────────────

@settings(max_examples=40, deadline=None)
@given(
    score_override=st.one_of(st.none(), st.integers(min_value=-20, max_value=150)),
    needs=st.booleans(),
    tier=st.sampled_from([None, 1, 2, 3]),
    days_offset=st.integers(min_value=-30, max_value=60),
    worked_ago=st.integers(min_value=0, max_value=90),
)
def test_hypothesis_relevance_bounds_and_determinism(score_override, needs, tier, days_offset, worked_ago):
    today = date(2026, 10, 16)
    cand = {
        "needs": needs,
        "tier": tier,
        "due": (today + timedelta(days=days_offset)).isoformat(),
        "worked": (today - timedelta(days=worked_ago)).isoformat(),
    }
    ov = {"score": score_override, "why": "custom"} if score_override is not None else None
    sc1, why1 = high_seat_core.relevance(cand, today, ov)
    sc2, why2 = high_seat_page.relevance(cand, today, ov)
    assert sc1 == sc2
    assert why1 == why2
    assert 0 <= sc1 <= 100
    assert isinstance(why1, str) and len(why1) > 0


@settings(max_examples=30, deadline=None)
@given(
    day_offsets=st.lists(st.integers(min_value=-14, max_value=60), min_size=0, max_size=15),
)
def test_hypothesis_ruler_markers_conservation(day_offsets):
    today = date(2026, 10, 16)
    dated = [
        {"due": (today + timedelta(days=off)).isoformat(), "name": f"Step {idx}"}
        for idx, off in enumerate(day_offsets)
    ]
    facts = [{"id": "proj-1", "name": "Project 1", "needs_you": True, "dated": dated}]
    weeks, buckets, beyond, overdue = high_seat_core.ruler_markers(facts, today)
    assert len(weeks) == 5
    total_placed = sum(len(v) for v in buckets.values()) + len(beyond) + len(overdue)
    assert total_placed == len(day_offsets)


@settings(max_examples=30, deadline=None)
@given(
    day_offsets=st.lists(st.integers(min_value=-10, max_value=14), min_size=1, max_size=12),
)
def test_hypothesis_this_week_horizon_buckets_disjoint(day_offsets):
    today = date(2026, 10, 16)
    dated = [
        {"step_id": f"s-{idx}", "due": (today + timedelta(days=off)).isoformat(), "name": f"Item {idx}"}
        for idx, off in enumerate(day_offsets)
    ]
    ctx = {
        "today": today,
        "facts": {"p1": {"id": "p1", "name": "P1", "folder": "C:/dev/P1", "dated": dated}},
        "entries": [{"id": "p1", "folder_path": "C:/dev/P1"}],
        "closed_today": [],
    }
    hb = high_seat_core.this_week_horizon_buckets(ctx)
    for x in hb["col_overdue"]:
        assert x["date_obj"] < today
    for x in hb["col_today"]:
        assert x["date_obj"] == today
    for x in hb["col_72h"]:
        assert today < x["date_obj"] <= today + timedelta(days=3)
    for x in hb["col_week"]:
        assert today + timedelta(days=3) < x["date_obj"] <= today + timedelta(days=7)


def test_wave12_campaign_initiatives_and_seated_equivalence():
    steps = [
        {
            "id": "goal-1",
            "name": "Ship Anchor Refactoring",
            "tier": 1,
            "area": "tools",
            "status": "active",
            "if_then": "If Wave 15 passes, then extract Wave 12 core",
            "pace": "2026-10-23",
            "navigation": {"groups": [{"id": "goal-1", "parent_id": None, "order": 1}]},
        },
        {
            "id": "part-1",
            "name": "Anchor Refactoring Cockpit",
            "ref": "project:pid-anchor",
            "status": "active",
            "seat": "active",
            "seat_order": 1,
            "navigation": {"path": ["goal-1"]},
        },
        {
            "id": "part-2",
            "name": "Star Chart Foresight",
            "ref": "effort:pid-anchor/star",
            "status": "planned",
            "seat": "",
            "navigation": {"path": ["goal-1"]},
        },
    ]
    resolved = {
        "part-1": {"name": "Anchor Refactoring", "what": "Wave 12 Anvil", "pid": "pid-anchor", "state": "working"},
        "part-2": {"name": "Star Chart", "what": "Inline seat actions", "pid": "pid-anchor", "state": "planned"},
    }
    inits = high_seat_core.campaign_initiatives(steps, resolved)
    assert inits == high_seat_page.campaign_initiatives(steps, resolved)
    assert len(inits) == 1
    assert high_seat_core.initiative_light(inits[0], working={"pid-anchor"}) == "working"
    active_seated = high_seat_core.seated(inits, "active")
    assert len(active_seated) == 1
    assert active_seated[0][1]["id"] == "part-1"


# ── Wave 15 Deep Hardening of Wave 9: Poller, OAuth2 PKCE, Two-Way Drafts & Executive Brief ────

def test_wave15_comms_oauth2_pkce_and_reply_drafts(tmp_path, monkeypatch):
    monkeypatch.setattr(comms_connector.paths, "data_dir", lambda: tmp_path)
    vault_store = {}
    monkeypatch.setattr(comms_connector.provider_secrets, "put", lambda k, v: vault_store.__setitem__(k, v))
    monkeypatch.setattr(comms_connector.provider_secrets, "get", lambda k: vault_store.get(k))

    # 1. RFC 7636 OAuth2 PKCE challenge
    pkce = comms_connector.build_oauth2_pkce_challenge("gmail", email="john@example.com")
    assert pkce["ok"] is True
    assert pkce["code_challenge_method"] == "S256"
    expected_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(pkce["code_verifier"].encode("ascii")).digest())
        .decode("ascii")
        .rstrip("=")
    )
    assert pkce["code_challenge"] == expected_challenge
    assert "code_challenge=" + expected_challenge in pkce["authorize_url"]

    # 2. Complete OAuth2 PKCE exchange and store token in OS Vault
    done = comms_connector.complete_oauth2_pkce_exchange(
        state=pkce["state"],
        code="auth-code-xyz123456",
        family="gmail",
        email="john@example.com",
    )
    assert done["ok"] is True
    assert done["account"]["auth_mode"] == "oauth_token"
    assert comms_connector.get_account_secret(done["account"]["id"])

    # 3. Two-way reply draft generation (.eml + mailto:)
    draft = comms_connector.create_reply_draft(
        to_addr="counsel@example.com",
        subject="Family Trusts — Gift Agreement Review",
        body="Hi Counsel,\nPlease find our updated comments attached.\nBest,\nJohn",
        project_name="Family Trusts",
        step_id="step-stanford",
        append_imap=False,
    )
    assert draft["ok"] is True
    eml_path = Path(draft["eml_path"])
    assert eml_path.is_file()
    eml_txt = eml_path.read_text(encoding="utf-8")
    assert "Subject: Re: Family Trusts" in eml_txt
    assert "X-Anchor-Project: Family Trusts" in eml_txt
    assert draft["mailto_url"].startswith("mailto:counsel@example.com?")

    # 4. Background Poller start & stop
    p_start = comms_connector.start_background_poller(interval_sec=300)
    assert p_start["running"] is True
    assert p_start["interval_sec"] == 300
    p_stop = comms_connector.stop_background_poller()
    assert p_stop["running"] is False

    # 5. Chief-of-Staff Executive Brief synthesizer
    brief = comms_connector.synthesize_executive_brief(
        entries=[{"id": "p1", "name": "Family Trusts", "folder_path": str(tmp_path)}],
        facts={
            "p1": {
                "id": "p1",
                "name": "Family Trusts",
                "folder": str(tmp_path),
                "needs_you": "Approve Stanford template",
                "dated": [{"due": date.today().isoformat(), "name": "Send Stanford redline", "step_id": "s1"}],
            }
        },
        today=date.today(),
    )
    assert brief["ok"] is True
    assert "Family Trusts" in brief["summary"]
    assert len(brief["priorities"]) >= 1


# ── Wave 15 Deep Hardening of Wave 11: roadmap_projection Leases, Peer Sync & Collab Modal ─────

def test_wave15_mothership_collab_roadmap_projection_and_peer_sync(tmp_path, monkeypatch):
    monkeypatch.setattr(mothership_collab.paths, "data_dir", lambda: tmp_path)

    # Create a cockpit with Ecgberht's `roadmap_projection` schema (not `steps`)
    cockpit_dir = tmp_path / "SharedProject"
    cockpit_dir.mkdir(parents=True)
    (cockpit_dir / "ECGBERHT.md").write_text("# Shared Project\n", encoding="utf-8")
    (cockpit_dir / "roadmap.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "roadmap_projection": [
                    {"step_id": "wave-15", "name": "Deep Hardening", "status": "in_progress"},
                    {"step_id": "wave-12", "name": "Anvil Core Extraction", "status": "planned"},
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # Claim lease on `roadmap_projection` step
    claim_res = mothership_collab.claim_step_lease(cockpit_dir, "wave-12", holder_label="John's Mothership")
    assert claim_res["ok"] is True
    assert claim_res["lease"]["step_id"] == "wave-12"

    # Summary detects both `roadmap_projection` steps and active lease
    entries = [{"id": "shared-1", "name": "Shared Project", "folder_path": str(cockpit_dir)}]
    summary = mothership_collab.collab_summary_for_cave(entries=entries)
    assert len(summary["shared_cockpits"]) == 1
    assert summary["shared_cockpits"][0]["steps_total"] == 2
    assert summary["shared_cockpits"][0]["first_open_step_id"] == "wave-15"
    assert len(summary["active_leases"]) == 1

    # Export portable packet and sync via `packet_bundle` peer
    exp = mothership_collab.export_cockpit_packet(cockpit_dir, project_name="Shared Project")
    assert exp["ok"] is True
    bundle_file = tmp_path / "peer-bundle.anchor-cockpit.json"
    bundle_file.write_text(json.dumps(exp["packet"], indent=2), encoding="utf-8")

    mothership_collab.register_peer_mothership(
        {
            "id": "peer-bundle-01",
            "label": "Lab Bundle Peer",
            "transport": "packet_bundle",
            "endpoint": str(bundle_file),
            "role": "collaborator",
        }
    )
    target_dir = tmp_path / "ImportedProject"
    sync_res = mothership_collab.sync_peer_mothership("peer-bundle-01", cdir=target_dir, entries=entries)
    assert sync_res["ok"] is True
    assert sync_res["reachability"] == "reachable"
    assert "Imported packet bundle" in sync_res["sync_note"]

    # Release lease
    rel_res = mothership_collab.release_step_lease(cockpit_dir, "wave-12")
    assert rel_res["ok"] is True


# ── Wave 15 UI Controls Verification on Cave of Wonders & Star Chart ───────────────────────────

def test_wave15_ui_controls_in_cave_and_star_chart(tmp_path, monkeypatch):
    monkeypatch.setattr(comms_connector.paths, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(mothership_collab.paths, "data_dir", lambda: tmp_path)

    today = date(2026, 10, 16)
    steps = [
        {
            "id": "g-tier1",
            "name": "Anchor 2.0",
            "tier": 1,
            "area": "tools",
            "status": "active",
            "if_then": "If Wave 15 completes, then run Wave 12",
            "pace": "2026-10-25",
            "navigation": {"groups": [{"id": "g-tier1", "parent_id": None, "order": 1}]},
        },
        {
            "id": "p-cockpit",
            "name": "Anchor Refactoring",
            "ref": "project:pid-1",
            "status": "active",
            "seat": "deck",
            "navigation": {"path": ["g-tier1"]},
        },
    ]
    inits = high_seat_core.campaign_initiatives(
        steps,
        {"p-cockpit": {"name": "Anchor Refactoring", "what": "Wave 12 Anvil", "pid": "pid-1", "state": "working"}},
    )
    ctx = {
        "today": today,
        "today_str": "Friday, Oct 16",
        "week": "Oct 12–18",
        "week_short": "1 due",
        "build": "test-build",
        "steward": {
            "label": "Aladdin",
            "high_seat": "aladdin-cave.jpg",
            "high_seat_name": "Cave of Wonders",
            "campaign_name": "Star Chart",
            "campaign_icon": "aladdin-starchart.jpg",
        },
        "campaign": {"pid": "camp-pid"},
        "pid": "camp-pid",
        "entries": [{"id": "pid-1", "name": "Anchor Refactoring", "folder_path": str(tmp_path)}],
        "facts": {
            "pid-1": {
                "id": "pid-1",
                "name": "Anchor Refactoring",
                "folder": str(tmp_path),
                "has_record": True,
                "steps_done": 1,
                "steps_total": 3,
                "dated": [{"step_id": "w12", "due": today.isoformat(), "name": "Wave 12 Anvil Core"}],
            }
        },
        "initiatives": inits,
        "working": {"pid-1"},
    }

    cave_html = high_seat_page.render_high_seat_html(ctx)
    # 1. HTML5 Drag-and-Drop on Today & This Week board
    assert 'data-tw-dnd="1"' in cave_html
    assert 'data-tw-drop-col="today"' in cave_html
    assert 'data-tw-card="1"' in cave_html
    # 2. Chief-of-Staff Synthesize Brief button & banner
    assert 'data-triage-synthesize="1"' in cave_html
    assert 'id="triageExecBrief"' in cave_html
    # 3. Two-Way Reply Draft modal & Auto-Poller pill
    assert 'id="caveCommsDraftModal"' in cave_html
    assert 'id="commsPollerPill"' in cave_html
    # 4. Collaborator registration & Packet Import modal
    assert 'id="caveCollabModal"' in cave_html
    assert 'id="btnCollabOpenImport"' in cave_html

    star_html = campaign_page.render_campaign_html(ctx)
    # 5. Inline Seat in Active / On Deck buttons on Star Chart Foresight strip
    assert 'id="starForesight"' in star_html
    assert '&#9654; Seat in Active' in star_html
    assert 'data-seat="active" data-step="p-cockpit"' in star_html
