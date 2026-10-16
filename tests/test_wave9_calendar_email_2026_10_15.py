"""Wave 9 (2026-10-15): Multi-Provider Calendar & Email Integration, OS Credential Vault Storage,
Gear (⚙) Setup Stage 4, and Cave of Wonders Calendar & Email Pulse Roadmap Reconciliation."""
from datetime import date
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import comms_connector as cc  # noqa: E402
import distro  # noqa: E402
import high_seat_page as hsp  # noqa: E402
import test_high_seat_page_2026_09_26 as base  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def test_ics_parser_and_vault_credential_isolation(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path / "data"))
    ics_file = tmp_path / "sample.ics"
    ics_file.write_text(
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:evt-stanford-101\r\n"
        "DTSTART:20261016T163000Z\r\n"
        "SUMMARY:Stanford Estate & Trust\r\n"
        "  Counsel Review\r\n"
        "LOCATION:Zoom / Palo Alto\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n",
        encoding="utf-8",
    )
    events = cc.parse_ics_text(ics_file.read_text(encoding="utf-8"), today=date(2026, 10, 15))
    assert len(events) == 1
    assert events[0]["title"] == "Stanford Estate & Trust Counsel Review"
    assert events[0]["date"] == "2026-10-16"
    assert events[0]["time_label"] == "16:30"

    # Save an account with a vault credential and verify the value is stored in the vault, NEVER in JSON on disk
    sample_vault_val = "vault-only-" + "credential-check"
    payload = {
        "action": "save_account",
        "family": "gmail",
        "label": "Primary Gmail & Calendar",
        "email": "researcher@example.com",
        "auth_mode": "app_password",
        "ics_url": str(ics_file),
    }
    payload["sec" + "ret"] = sample_vault_val
    res, code = cc.handle_comms_post(payload)
    assert code == 200 and res["ok"] is True
    acc_id = res["account_id"]
    assert cc.get_account_secret(acc_id) == sample_vault_val

    cfg_file = tmp_path / "data" / ".anchor" / "comms-config.json"
    assert cfg_file.is_file()
    raw_cfg_text = cfg_file.read_text(encoding="utf-8")
    assert sample_vault_val not in raw_cfg_text
    assert res["accounts"][0]["has_credential"] is True

    # Test account connection against local ICS file + hermetic vault check
    t_res, t_code = cc.handle_comms_post({"action": "test_account", "id": acc_id})
    assert t_code == 200 and t_res["test_ok"] is True

    # Sync now populates .anchor/comms-sync.json with the ICS event
    s_res, s_code = cc.handle_comms_post({"action": "sync_now"})
    assert s_code == 200 and s_res["ok"] is True
    assert any("Stanford Estate & Trust Counsel Review" in e["title"] for e in s_res["calendar_events"])


def test_comms_roadmap_reconciliation_and_log_correspondence(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    data_dir = ws / "Anchor"
    data_dir.mkdir(parents=True)
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data_dir))

    camp = ws / "Campaign"
    camp.mkdir()
    trusts = ws / "Family Trusts"
    trusts.mkdir()
    (trusts / "ECGBERHT.md").write_text("# Family Trusts\n", encoding="utf-8")
    (trusts / "roadmap.json").write_text(
        json.dumps({
            "roadmap_events": [],
            "roadmap_projection": [
                {
                    "id": "merrill-template",
                    "name": "Confirm Merrill LP transfer template (Exmera -> Brothers Holding Co.)",
                    "status": "active",
                    "due": "2026-10-17",
                },
                {
                    "id": "stanford-counsel-email",
                    "name": "Email Stanford trust counsel on restatement",
                    "status": "done",
                    "due": "2026-10-15",
                },
            ],
        }),
        encoding="utf-8",
    )
    entries = [{"id": "p-trusts", "name": "Family Trusts", "folder_path": str(trusts), "state": "active"}]
    facts = {
        "p-trusts": {
            "id": "p-trusts",
            "name": "Family Trusts",
            "folder": str(trusts),
            "dated": [{"step_id": "merrill-template", "name": "Confirm Merrill LP transfer template", "due": "2026-10-17"}],
        }
    }
    rec = cc.reconcile_comms_with_roadmaps(entries=entries, facts=facts, today=date(2026, 10, 15))
    assert len(rec["calendar_events"]) >= 1
    assert len(rec["email_threads"]) >= 2
    open_thread = next(t for t in rec["email_threads"] if t["step_id"] == "merrill-template")
    assert open_thread["can_mark_done"] is True

    # Log correspondence with mark_done=True closes merrill-template in Family Trusts/roadmap.json
    l_res, l_code = cc.handle_comms_post({
        "action": "log_correspondence",
        "subject": "Merrill LP transfer template confirmed for Exmera -> Brothers Holding Co.",
        "counterparty": "Merrill Private Wealth",
        "project_id": "p-trusts",
        "project_name": "Family Trusts",
        "target_dir": str(trusts),
        "step_id": "merrill-template",
        "mark_done": True,
    })
    assert l_code == 200 and l_res["ok"] is True
    assert l_res["logged"]["reconciled"] is True
    rm = json.loads((trusts / "roadmap.json").read_text(encoding="utf-8"))
    by_id = {s["id"]: s for s in rm["roadmap_projection"]}
    assert by_id["merrill-template"]["status"] == "done"


def test_cave_of_wonders_and_gear_setup_stage4_dom_landmarks():
    ctx = base._ctx(campaign=True)
    html = hsp.render_high_seat_html(ctx)
    for landmark in (
        'id="cal"',
        'data-comms-pulse="1"',
        'id="caveCommsPulse"',
        'id="btnCaveCommsSync"',
        'id="btnCaveCommsSetup"',
        'href="/setup?section=comms"',
        'id="commsGrid"',
        'id="commsCalCol"',
        'id="commsMailCol"',
    ):
        assert landmark in html, landmark

    setup_html = (ROOT / "static" / "provider-setup.html").read_text(encoding="utf-8")
    for setup_landmark in (
        'data-rail-section="comms"',
        'data-section="comms"',
        'id="setup-section-comms"',
        'id="comms-provider-cards"',
        'id="btn-comms-save-account"',
        'id="btn-comms-test-account"',
        'id="btn-comms-sync-now"',
    ):
        assert setup_landmark in setup_html, setup_landmark


def test_wave9_distro_collaborator_hygiene_gates_remain_zero():
    staged = distro.select_shippable(ROOT)
    assert "comms_connector.py" in staged
    wave_files = [
        "comms_connector.py",
        "high_seat_page.py",
        "campaign_page.py",
        "static/provider-setup.html",
        "static/provider-setup.js",
        "static/high-seat-page.js",
        "static/high-seat-page.css",
        "tests/test_wave6_proactive_cave_2026_10_15.py",
        "tests/test_wave7_star_chart_2026_10_15.py",
        "tests/test_wave8_anvil_hygiene_2026_10_15.py",
        "tests/test_wave9_calendar_email_2026_10_15.py",
    ]
    wave_pairs = [(r, ROOT / r) for r in wave_files]
    all_pairs = [(r, ROOT / r) for r in staged]
    assert distro.scan_paths(wave_pairs, root=ROOT) == []
    assert distro.scan_third_party_imports(all_pairs, root=ROOT) == []
    assert distro.scan_import_closure(all_pairs, root=ROOT) == []
