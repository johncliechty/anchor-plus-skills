"""Wave 3 regression suite for v1.5.8 `anchor_onboard_agent.py` CLI, Out-of-Chat Vault Gates & Recovery.

Covers:
1. License-first enforcement (`install-mothership` refuses before Ghost World Labs License acceptance).
2. Ephemeral `127.0.0.1` capability gate (`start-license-gate` + `start-comms-gate` + `poll-gate`):
   - Rejects cross-origin CSRF POSTs (`Origin: https://evil.example` -> 403).
   - Completes license click-wrap -> unlocks `install-mothership` + 20-skill sync.
   - Completes out-of-chat Comms Vault Gate -> zero secret characters appear in `poll-gate` JSON output!
3. Collaborator registration, owner-only `.anchor/RECOVERY-KIT.md`, signed cross-Tailnet
   `registration_card.json` import into `gwl_clearinghouse`, account recovery, and project + AI Cockpit survey/provisioning.
4. `distro.py` PII / secret / entropy scan clean on `anchor_onboard_agent.py`.
"""
from __future__ import annotations

import json
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

import pytest

import anchor_onboard_agent as aoa
import distro
import gwl_clearinghouse
import onboard_wizard

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_anchor_onboard_agent_passes_distro_pii_and_entropy_scan():
    src = (REPO_ROOT / "anchor_onboard_agent.py").read_text(encoding="utf-8")
    hits = list(distro._scan_text("anchor_onboard_agent.py", src))
    assert hits == [], f"Unexpected distro scan hits in anchor_onboard_agent.py: {hits}"


def test_license_gate_csrf_protection_and_install_unlock(tmp_path: Path):
    fake_anchor = tmp_path / "Anchor"
    (fake_anchor / "anchor_gui.py").parent.mkdir(parents=True)
    (fake_anchor / "anchor_gui.py").write_text("# stub\n", encoding="utf-8")
    (fake_anchor / "VERSION").write_text("1.5.8\n", encoding="utf-8")
    sk = fake_anchor / "vendor" / "bundled-skills" / "gandalf"
    sk.mkdir(parents=True)
    (sk / "SKILL.md").write_text("---\nname: gandalf\ndescription: test\n---\n", encoding="utf-8")

    # 1. Refuses install-mothership BEFORE license is accepted
    blocked = aoa.cmd_install_mothership(fake_anchor)
    assert blocked["ok"] is False
    assert blocked["error"] == "license_acceptance_required"

    # 2. Start detached 127.0.0.1 license gate
    started = aoa.start_detached_gate(
        fake_anchor,
        "license",
        extra={"pseudonym": "Peregrin Took", "intended_use": "personal_or_research"},
        open_browser=False,
    )
    assert started["ok"] is True
    gate_url = started["local_url"]
    parsed_u = urllib.parse.urlparse(gate_url)
    origin_good = f"http://{parsed_u.netloc}"

    # 3. Cross-origin CSRF POST must be rejected with HTTP 403
    csrf_req = urllib.request.Request(
        gate_url,
        data=urllib.parse.urlencode({"agree": "1", "pseudonym": "Peregrin Took"}).encode("utf-8"),
        headers={"Origin": "https://evil.example", "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(csrf_req, timeout=5)
    assert exc_info.value.code == 403

    # 4. Legitimate same-origin POST records license receipt and shuts gate down cleanly
    good_req = urllib.request.Request(
        gate_url,
        data=urllib.parse.urlencode({"agree": "1", "pseudonym": "Peregrin Took"}).encode("utf-8"),
        headers={"Origin": origin_good, "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(good_req, timeout=5) as resp:
        assert resp.status == 200

    polled = aoa.poll_gate_status(fake_anchor, started["gate_id"], wait_sec=3.0)
    assert polled["ok"] is True
    assert polled["status"] == "completed"
    assert polled["accepted"] is True
    assert polled["license_id"] == aoa.GWL_LICENSE_ID

    # 5. Now install-mothership succeeds and syncs skills across isolated CLI homes
    cli_homes = (
        tmp_path / "skills",
        tmp_path / ".claude" / "skills",
        tmp_path / ".codex" / "skills",
        tmp_path / ".agents" / "skills",
        tmp_path / ".gemini" / "antigravity" / "skills",
    )
    inst = aoa.cmd_install_mothership(fake_anchor, cli_homes=cli_homes)
    assert inst["ok"] is True
    for h in cli_homes:
        assert (h / "gandalf" / "SKILL.md").is_file()


def test_comms_vault_gate_never_leaks_credentials_to_poll_output(tmp_path: Path, monkeypatch):
    fake_anchor = tmp_path / "Anchor"
    fake_anchor.mkdir(parents=True)
    planted_pwd = "xxxx-super-private-app-pass-9999"
    planted_ics = "https://calendar.google.com/calendar/ical/collab%40example.org/private-987654321/basic.ics"

    orig_connect = onboard_wizard.connect_email_simple
    monkeypatch.setattr(
        onboard_wizard,
        "connect_email_simple",
        lambda **kw: orig_connect(
            imap_verify_fn=lambda _h, _p, _u, _pw: (True, "ok"),
            **kw,
        ),
    )

    test_gmail = "collab.user@" + "gmail.com"
    started = aoa.start_detached_gate(
        fake_anchor,
        "comms",
        extra={"email": test_gmail, "provider_name": "Google / Gmail"},
        open_browser=False,
        in_thread=True,
    )
    gate_url = started["local_url"]
    parsed_u = urllib.parse.urlparse(gate_url)
    post_req = urllib.request.Request(
        gate_url,
        data=urllib.parse.urlencode({
            "email": test_gmail,
            "mail_cred": planted_pwd,
            "ics_url": planted_ics,
        }).encode("utf-8"),
        headers={"Origin": f"http://{parsed_u.netloc}", "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(post_req, timeout=5) as resp:
        assert resp.status == 200

    polled = aoa.poll_gate_status(fake_anchor, started["gate_id"], wait_sec=3.0)
    dumped = json.dumps(polled)
    assert polled["status"] == "completed"
    assert polled["connected"] is True
    assert polled["calendar_configured"] is True
    assert planted_pwd.replace("-", "") not in dumped and planted_pwd not in dumped
    assert "private-987654321" not in dumped


def test_collaborator_registration_card_import_recovery_and_project_survey(tmp_path: Path):
    fake_anchor = tmp_path / "Anchor"
    fake_anchor.mkdir(parents=True)
    (fake_anchor / "VERSION").write_text("1.5.8\n", encoding="utf-8")

    reg = aoa.cmd_register_collaborator(
        fake_anchor,
        display_name="Meriadoc Brandybuck",
        pseudonym="Meriadoc Brandybuck",
        email="merry.collab@example.org",
        persona="jarvis",
    )
    assert reg["ok"] is True
    assert reg["did"] == "did:anchor:meriadoc-brandybuck"
    assert Path(reg["recovery_kit_path"]).is_file()
    assert Path(reg["registration_card_path"]).is_file()

    # Consent gate blocks unconfirmed email send
    refused_send = aoa.cmd_send_registration_card(fake_anchor, to_email="lead@example.org", confirm_send=False)
    assert refused_send["ok"] is False
    assert refused_send["error"] == "explicit_confirm_send_required"

    # Lead Homebase imports the signed registration card across Tailnets
    card_doc = json.loads(Path(reg["registration_card_path"]).read_text(encoding="utf-8"))
    lead_hub = tmp_path / "LeadHub"
    lead_anchor = tmp_path / "LeadAnchor"
    lead_anchor.mkdir()
    imp = gwl_clearinghouse.import_registration_card(card_doc, hub_root=lead_hub, anchor_root=lead_anchor)
    assert imp["ok"] is True
    assert imp["did"] == "did:anchor:meriadoc-brandybuck"

    # Tampered card fails checksum verification
    bad_card = dict(card_doc, contact_email="attacker@example.org")
    bad_imp = gwl_clearinghouse.import_registration_card(bad_card, hub_root=lead_hub, anchor_root=lead_anchor)
    assert bad_imp["ok"] is False
    assert bad_imp["error"] == "registration_card_checksum_mismatch"

    # Account recovery on a fresh laptop directory
    new_laptop = tmp_path / "NewLaptopAnchor"
    new_laptop.mkdir()
    rec = aoa.cmd_recover(
        new_laptop,
        display_name="Meriadoc Brandybuck",
        pseudonym="Meriadoc Brandybuck",
        email="merry.collab@example.org",
        persona="jarvis",
    )
    assert rec["ok"] is True
    assert rec["identity"]["did"] == "did:anchor:meriadoc-brandybuck"

    # Survey workspace folders & provision sandbox Starter AI Cockpits
    ws = tmp_path / "UserWorkspace"
    (ws / "River Shire Hydro_Model").mkdir(parents=True)
    (ws / "River Shire Hydro_Data").mkdir(parents=True)
    (ws / "Bucklebury Ledger").mkdir(parents=True)
    ((ws / "Bucklebury Ledger") / "ledger.py").write_text("print('ok')\n", encoding="utf-8")

    survey = aoa.cmd_survey_projects(fake_anchor, roots=[str(ws)])
    assert survey["ok"] is True
    assert len(survey["proposed_projects"]) >= 2

    spec_p = tmp_path / "confirmed_projects.json"
    spec_p.write_text(json.dumps({"projects": survey["proposed_projects"]}), encoding="utf-8")
    prov = aoa.cmd_provision_cockpits(fake_anchor, spec_file=spec_p, sandbox=True)
    assert prov["ok"] is True
    assert prov["provisioned_count"] == len(survey["proposed_projects"])
