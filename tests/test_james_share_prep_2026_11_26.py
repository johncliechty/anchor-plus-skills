"""Hermetic regression tests for v1.5.5 Collaborator Share Prep:
1. Ghost World Labs License (`GHOST-WORLD-LAB-NON-RESALE-v1`) click-wrap gate across
   Setup Wizard Step 1, shell/connect.py installer, onboard.py, and /setup, while
   preserving the NO-root-LICENSE-file law (`share_ci_ship_gate`).
2. Signed Website-Watched Automatic Version Updates (`release-signal.json` RFC 8032 Ed25519
   sign/verify, tamper rejection, busy-host deferral, Tailscale-free auto-pull + skill sync).
3. Free-Tier AI Provider Accounts preset & per-provider `free_tier` capability mode.
4. Older Windows Laptop / Low-Memory Mothership Mode (`detect_host_hardware_profile`,
   `low_spec_mode` persistence, `/api/system/version` exposure, JS frame cap & warm skip).
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import mothership_updater as mu
import onboard
import onboard_wizard as ow
import paths
import share_ci_ship_gate as ship_gate
import website_portal as wp
from shell import connect as shell_connect


class _BytesResp:
    def __init__(self, body: bytes, status: int = 200):
        self._buf = io.BytesIO(body)
        self.status = status

    def read(self, n: int = -1) -> bytes:
        return self._buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_no_root_license_file_and_user_onboard_gate_green():
    rep = ship_gate.check_docs_and_rights_reserved(REPO_ROOT)
    assert rep["ok"] is True, rep
    assert rep["no_oss_license"]["ok"] is True
    assert rep["user_onboard"]["ok"] is True
    doc_txt = (REPO_ROOT / "USER-ONBOARD.md").read_text(encoding="utf-8")
    assert "GHOST-WORLD-LAB-NON-RESALE-v1" in doc_txt
    assert "release-signal.json" in doc_txt
    assert "Free-Tier" in doc_txt


def test_wizard_step1_requires_and_records_gwl_license_receipt(tmp_path):
    base = tmp_path / "collab_ws"
    base.mkdir()

    # Without accepting license when require_license_ack=True -> fails closed (400)
    denied = ow.dispatch_wizard_action(
        "save_identity",
        {
            "display_name": "Collaborator",
            "pseudonym": "Peregrin Took",
            "require_license_ack": True,
            "accepted_gwl_license": False,
        },
        base_dir=base,
    )
    assert denied["ok"] is False
    assert denied["error"] == "license_acceptance_required"
    assert ow.get_wizard_license_status(base_dir=base)["accepted"] is False

    # Accepting Ghost World Labs License mints HMAC-verified receipt in .anchor/license_acceptances.json
    accepted = ow.dispatch_wizard_action(
        "save_identity",
        {
            "display_name": "Collaborator",
            "pseudonym": "Peregrin Took",
            "contact_email": "collab@example.org",
            "require_license_ack": True,
            "accepted_gwl_license": True,
        },
        base_dir=base,
    )
    assert accepted["ok"] is True
    assert accepted["license_status"]["accepted"] is True
    assert accepted["license_status"]["license_id"] == "GHOST-WORLD-LAB-NON-RESALE-v1"

    bundle = ow.get_full_wizard_bundle(base_dir=base)
    assert bundle["license_status"]["accepted"] is True
    assert bundle["license_spec"]["not_open_source"] is True
    assert len(bundle["license_spec"]["operative_clauses"]) == 10


def test_shell_connect_installer_license_gate_and_author_clean_pages(tmp_path):
    first_html = shell_connect.first_launch_page()
    inst_html = shell_connect.installation_page(tmp_path)
    assert "Ghost World Labs License" in first_html
    assert "No Resale or Commercialization" in first_html
    assert "chk-gwl-license" in inst_html

    # Requiring license without acceptance refuses install cleanly
    refused = shell_connect.pull_and_install_mothership(
        target_dir=tmp_path / "Anchor",
        require_license=True,
        license_accepted=False,
    )
    assert refused["ok"] is False
    assert refused["error"] == "license_acceptance_required"

    # Shell settings persistence for license acceptance
    shell_data = tmp_path / "shell_settings"
    assert shell_connect.load_license_acceptance(shell_data) is False
    shell_connect.save_license_acceptance(shell_data, True)
    assert shell_connect.load_license_acceptance(shell_data) is True


def test_ed25519_release_signal_sign_verify_and_tamper_rejection():
    # RFC 8032 Section 7.1 Official Test Vector 1 (empty message)
    rfc_seed1 = bytes.fromhex(
        "9d:61:b1:9d:ef:fd:5a:60:ba:84:4a:f4:92:ec:2c:c4:"
        "44:49:c5:69:7b:32:69:19:70:3b:ac:03:1c:ae:7f:60".replace(":", "")
    )
    rfc_pub1 = bytes.fromhex(
        "d7:5a:98:01:82:b1:0a:b7:d5:4b:fe:d3:c9:64:07:3a:"
        "0e:e1:72:f3:da:a6:23:25:af:02:1a:68:f7:07:51:1a".replace(":", "")
    )
    rfc_sig1 = bytes.fromhex(
        "e5:56:43:00:c3:60:ac:72:90:86:e2:cc:80:6e:82:8a:"
        "84:87:7f:1e:b8:e5:d9:74:d8:73:e0:65:22:49:01:55:"
        "5f:b8:82:15:90:a3:3b:ac:c6:1e:39:70:1c:f9:b4:6b:"
        "d2:5b:f5:f0:59:5b:be:24:65:51:41:43:8e:7a:10:0b".replace(":", "")
    )
    assert mu._ed25519_pubkey(rfc_seed1) == rfc_pub1
    assert mu._ed25519_sign(rfc_seed1, b"") == rfc_sig1
    assert mu._ed25519_verify(rfc_pub1, b"", rfc_sig1) is True
    # Reject malleable S >= L
    bad_s_sig = rfc_sig1[:32] + (mu._ED_L).to_bytes(32, "little")
    assert mu._ed25519_verify(rfc_pub1, b"", bad_s_sig) is False

    seed = bytes(range(1, 33))
    pub = mu._ed25519_pubkey(seed)
    sig_doc = mu.build_signed_release_signal(
        version="1.5.5",
        private_seed_bytes=seed,
        notes="Signed collaborator release test.",
    )
    ok, reason = mu.verify_release_signal(sig_doc, pubkey_bytes=pub)
    assert ok is True and reason == "verified"

    # Tampering with version, channel, or repo_url must fail verification
    tampered_ver = dict(sig_doc, version="9.9.9")
    ok_tv, why_tv = mu.verify_release_signal(tampered_ver, pubkey_bytes=pub)
    assert ok_tv is False and why_tv == "invalid_ed25519_signature"

    tampered_ch = dict(sig_doc, channel="beta")
    ok_tc, why_tc = mu.verify_release_signal(tampered_ch, pubkey_bytes=pub)
    assert ok_tc is False and why_tc == "channel_mismatch"

    tampered_url = dict(sig_doc, repo_url="https://evil.example.com/anchor.git")
    ok_tu, why_tu = mu.verify_release_signal(tampered_url, pubkey_bytes=pub)
    assert ok_tu is False and why_tu == "untrusted_repo_url"

    # Non-root full Ghost World Labs License doc exists and ships
    lic_doc = REPO_ROOT / "docs" / "GHOST-WORLD-LAB-NON-RESALE-v1.md"
    assert lic_doc.is_file()
    assert "Separate Written Permission" in lic_doc.read_text(encoding="utf-8")


def test_website_watched_auto_updater_tailscale_free_and_busy_deferral(tmp_path):
    # Set up an isolated v1.5.4 collaborator install with NO Tailscale registration
    anchor_dir = tmp_path / "Anchor"
    (anchor_dir / "vendor" / "bundled-skills" / "gandalf").mkdir(parents=True)
    (anchor_dir / "vendor" / "bundled-skills" / "gandalf" / "SKILL.md").write_text("# Gandalf\n", encoding="utf-8")
    (anchor_dir / ".git").mkdir()
    (anchor_dir / "VERSION").write_text("1.5.4\n", encoding="utf-8")
    (anchor_dir / "DASHBOARD.md").write_text("# My Personal Tasks\n- [ ] Keep safe\n", encoding="utf-8")

    mu.load_or_init_homebase_link(anchor_dir, auto_pull_updates=True, low_spec_mode=True)
    assert mu.read_homebase_link(anchor_dir)["registered"] is False

    seed = bytes(range(11, 43))
    pub = mu._ed25519_pubkey(seed)
    signed_155 = mu.build_signed_release_signal(
        version="1.5.5",
        private_seed_bytes=seed,
        notes="Automatic website-watched push update.",
    )

    # 1. Tampered website signal is rejected without running git pull
    bad_doc = dict(signed_155, version="1.5.9")
    git_calls = []

    def fake_runner(cmd, cwd=None, timeout=120):
        git_calls.append(cmd)
        if "pull" in cmd:
            (anchor_dir / "VERSION").write_text("1.5.5\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    tamper_res = mu.poll_website_release_signal(
        anchor_dir,
        watch_url="https://raw.githubusercontent.com/johncliechty/ghostworldlabs-anchor/main/release-signal.json",
        opener_fn=lambda u, timeout=5.0: _BytesResp(json.dumps(bad_doc).encode("utf-8")),
        runner_fn=fake_runner,
        pubkey_bytes=pub,
    )
    assert tamper_res["ok"] is False
    assert tamper_res["tamper_rejected"] is True
    assert git_calls == []
    assert (anchor_dir / "VERSION").read_text(encoding="utf-8").strip() == "1.5.4"

    # 2. Busy host defers auto-update cleanly so active Steward/Foreman work is never interrupted
    busy_res = mu.poll_website_release_signal(
        anchor_dir,
        watch_url="https://raw.githubusercontent.com/johncliechty/ghostworldlabs-anchor/main/release-signal.json",
        opener_fn=lambda u, timeout=5.0: _BytesResp(json.dumps(signed_155).encode("utf-8")),
        runner_fn=fake_runner,
        busy_check_fn=lambda _r: (True, "steward_turn_active"),
        pubkey_bytes=pub,
    )
    assert busy_res["ok"] is True
    assert busy_res["deferred_busy"] is True
    assert busy_res["auto_pulled"] is False
    assert git_calls == []

    # 3. Code-binding check (B1): if signed core_sha256 mismatches pulled tree, auto-updater rolls back & rejects
    wrong_core_doc = mu.build_signed_release_signal(
        version="1.5.5",
        private_seed_bytes=seed,
        core_sha256="aa:" * 31 + "bb",
        notes="Mismatched core digest.",
    )
    mismatch_res = mu.poll_website_release_signal(
        anchor_dir,
        watch_url="https://raw.githubusercontent.com/johncliechty/ghostworldlabs-anchor/main/release-signal.json",
        opener_fn=lambda u, timeout=5.0: _BytesResp(json.dumps(wrong_core_doc).encode("utf-8")),
        runner_fn=fake_runner,
        busy_check_fn=lambda _r: (False, ""),
        pubkey_bytes=pub,
    )
    assert mismatch_res["ok"] is False
    assert mismatch_res["error"] == "core_sha256_mismatch"
    assert mismatch_res["rolled_back"] is True
    assert (anchor_dir / "VERSION").read_text(encoding="utf-8").strip() == "1.5.4"

    # 4. Idle host automatically pulls v1.5.5, syncs skills, preserves user DASHBOARD.md, and flags reload ready
    ok_res = mu.poll_website_release_signal(
        anchor_dir,
        watch_url="https://raw.githubusercontent.com/johncliechty/ghostworldlabs-anchor/main/release-signal.json",
        opener_fn=lambda u, timeout=5.0: _BytesResp(json.dumps(signed_155).encode("utf-8")),
        runner_fn=fake_runner,
        busy_check_fn=lambda _r: (False, ""),
        pubkey_bytes=pub,
    )
    assert ok_res["ok"] is True
    assert ok_res["auto_pulled"] is True
    assert ok_res["after_version"] == "1.5.5"
    assert ok_res["update_ready_for_reload"] is True
    assert (anchor_dir / "VERSION").read_text(encoding="utf-8").strip() == "1.5.5"
    assert "Keep safe" in (anchor_dir / "DASHBOARD.md").read_text(encoding="utf-8")
    assert (tmp_path / "skills" / "gandalf" / "SKILL.md").is_file()


def test_free_tier_provider_preset_and_low_spec_laptop_mode(tmp_path):
    base = tmp_path / "laptop_ws"
    base.mkdir()

    # Hardware detection returns positive cores & boolean recommendation
    hw = paths.detect_host_hardware_profile()
    assert hw["cpu_cores"] >= 1
    assert isinstance(hw["low_spec_recommended"], bool)

    # Configure Older Laptop Low-Memory Mode + Website Auto-Updater in Step 2
    topo_out = ow.dispatch_wizard_action(
        "configure_topology",
        {
            "mode": "main_mothership",
            "auto_pull_updates": True,
            "low_spec_mode": True,
            "telemetry_enabled": False,
        },
        base_dir=base,
    )
    assert topo_out["ok"] is True
    ver_st = mu.get_version_status(anchor_root=base)
    assert ver_st["low_spec_mode"] is True
    assert ver_st["auto_pull_updates"] is True

    # Apply Free-Account AI Provider Preset in Step 3
    free_out = ow.dispatch_wizard_action("apply_free_tier_preset", {}, base_dir=base)
    assert free_out["ok"] is True
    assert free_out["free_tier_pacing"] is True
    svcs = ow.detect_ai_services_status(base_dir=base)["services"]
    assert svcs["gemini"]["tier_level"] == "free_tier"
    assert svcs["gemini"]["single_seat_pacing"] is True
    assert "aistudio.google.com" in svcs["gemini"]["free_tier_guide"]

    # Static JS enforces low-spec bounds
    app_js = (REPO_ROOT / "static" / "app.js").read_text(encoding="utf-8")
    cave_js = (REPO_ROOT / "static" / "high-seat-page.js").read_text(encoding="utf-8")
    assert "applyLowSpecMode" in app_js
    assert "KEEP_LIVE = 2" in app_js
    assert "isLowSpecMode()" in cave_js
