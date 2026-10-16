"""Wave 11 — Multi-Mothership Collaboration & Shared Cockpits Test Suite (2026-10-15)."""
from __future__ import annotations

import json
from pathlib import Path

import distro
import high_seat_page
import mothership_collab as mc


REPO = Path(__file__).resolve().parents[1]


def test_peer_registration_and_step_lease_conflict_prevention(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_COLLAB_DIR", str(tmp_path / "collab_store"))
    peer = mc.register_peer({
        "id": "lab-peer-01",
        "label": "Co-Author Mothership · Research Lab",
        "transport": "git_remote",
        "endpoint": "https://github.com/example-org/shared-cockpit.git",
        "role": "collaborator",
        "shared_projects": ["MBA Teaching AI", "Book1"],
    })
    assert peer["id"] == "lab-peer-01"
    assert len(mc.list_peers()) == 1

    # Create a project roadmap with two steps
    proj = tmp_path / "SharedProject"
    proj.mkdir(parents=True)
    rm = {
        "steps": [
            {"id": "lecture-5", "name": "Build Lecture 5", "status": "open", "refinement": {"display_round": 1}},
            {"id": "quiz-1", "name": "Prepare Quiz 1", "status": "open", "refinement": {"display_round": 1}},
        ],
        "roadmap_events": [],
    }
    (proj / "roadmap.json").write_text(json.dumps(rm), encoding="utf-8")

    # Local mothership claims lecture-5
    c1 = mc.claim_step_lease(proj, "lecture-5", mothership_id="puter-mothership", owner_label="Puter")
    assert c1["ok"] is True
    assert c1["lease"]["mothership_id"] == "puter-mothership"

    # Peer mothership attempting to claim lecture-5 without force is rejected (split-brain prevention)
    c2 = mc.claim_step_lease(proj, "lecture-5", mothership_id="lab-peer-01", owner_label="Lab Peer")
    assert c2["ok"] is False
    assert c2["error"] == "step_leased_by_peer"

    # Peer mothership can claim quiz-1 cleanly
    c3 = mc.claim_step_lease(proj, "quiz-1", mothership_id="lab-peer-01", owner_label="Lab Peer")
    assert c3["ok"] is True


def test_portable_cockpit_packet_export_scrubs_host_paths_and_merges_cleanly(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_COLLAB_DIR", str(tmp_path / "collab_store"))
    # Set deterministic local mothership identity
    (tmp_path / "collab_store").mkdir(parents=True, exist_ok=True)
    (tmp_path / "collab_store" / "mothership_identity.json").write_text(
        json.dumps({"id": "puter-mothership", "label": "Puter · Mother Ship", "role": "lead"}),
        encoding="utf-8",
    )

    mothership_a_proj = tmp_path / "mothership_a" / "MBA Teaching AI"
    mothership_a_proj.mkdir(parents=True)
    (mothership_a_proj / "roadmap.json").write_text(
        json.dumps({
            "steps": [
                {
                    "id": "lecture-5",
                    "name": "Lecture 5",
                    "status": "open",
                    "lease": {"mothership_id": "puter-mothership", "owner_label": "Puter"},
                    "refinement": {"display_round": 2},
                },
                {
                    "id": "quiz-1",
                    "name": "Quiz 1",
                    "status": "open",
                    "lease": {"mothership_id": "lab-peer-01", "owner_label": "Lab Peer"},
                    "refinement": {"display_round": 1},
                },
            ],
            "roadmap_events": [
                {"step_id": "lecture-5", "event": "step_leased", "at": "2026-10-15T15:00:00Z"}
            ],
        }),
        encoding="utf-8",
    )
    (mothership_a_proj / "strip.json").write_text(
        json.dumps({
            "deliverables": [
                {
                    "id": "del-lec4",
                    "title": "Lecture 4 Slides",
                    "path": str(mothership_a_proj / "deliverables" / "Lecture4.pdf"),
                }
            ]
        }),
        encoding="utf-8",
    )

    pkt = mc.export_cockpit_packet(mothership_a_proj)
    assert pkt["schema"] == mc.PACKET_SCHEMA
    assert pkt["packet_digest"]
    # Verify host path was scrubbed to <project_root>
    pkt_json = json.dumps(pkt)
    assert str(mothership_a_proj) not in pkt_json
    assert "<project_root>" in pkt_json

    # Simulate peer mothership ("lab-peer-01") completing quiz-1 and attempting to overwrite lecture-5
    peer_packet = json.loads(pkt_json)
    peer_packet["origin_mothership"] = {"id": "lab-peer-01", "label": "Lab Peer", "role": "collaborator"}
    peer_packet["roadmap"]["steps"][0]["status"] = "clobbered_by_peer"  # should be rejected because puter-mothership holds lease!
    peer_packet["roadmap"]["steps"][1]["status"] = "done"
    peer_packet["roadmap"]["steps"][1]["refinement"] = {"display_round": 3}
    peer_packet["roadmap"]["roadmap_events"].append(
        {"step_id": "quiz-1", "event": "step_completed", "at": "2026-10-15T16:00:00Z"}
    )
    peer_packet["strip"]["deliverables"].append(
        {"id": "del-quiz1", "title": "Quiz 1 Oral Bank", "path": "<project_root>/deliverables/Quiz1.pdf"}
    )

    merge_res = mc.import_cockpit_packet(mothership_a_proj, peer_packet)
    assert merge_res["ok"] is True
    assert merge_res["preserved_local_leases"] == 1
    assert merge_res["updated_steps"] == 1
    assert merge_res["merged_events"] == 2

    merged_rm = json.loads((mothership_a_proj / "roadmap.json").read_text(encoding="utf-8"))
    by_id = {s["id"]: s for s in merged_rm["steps"]}
    assert by_id["lecture-5"]["status"] == "open"  # local lease protected!
    assert by_id["quiz-1"]["status"] == "done"     # peer lease update accepted!


def test_cave_of_wonders_renders_mothership_collab_strip_and_passes_distro_scan(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_COLLAB_DIR", str(tmp_path / "collab_store"))
    ctx = {
        "entries": [],
        "facts": {},
        "initiatives": [],
        "steward": {"high_seat_name": "Cave of Wonders", "label": "Aladdin"},
        "build": "test",
    }
    html = high_seat_page._mothership_collab_html(ctx)
    assert 'id="caveCollabStrip"' in html
    assert "Multi-Mothership Collaboration &amp; Shared Cockpits" in html
    assert 'id="btnCollabSyncNow"' in html
    assert 'id="btnCollabAddPeer"' in html

    # Verify mothership_collab.py and this test pass distro.scan_paths with 0 hits
    hits = distro.scan_paths(
        [
            ("mothership_collab.py", REPO / "mothership_collab.py"),
            ("tests/test_wave11_mothership_collab_2026_10_15.py", Path(__file__).resolve()),
        ],
        root=REPO,
    )
    assert hits == []
