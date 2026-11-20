"""End-to-end tests for Standard Setup Homebase Registration, Push-Update Capability
Authentication, and Collaborator Journal/Error Telemetry Sync (2026-11-20, v1.5.3).
"""
from __future__ import annotations

from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import urllib.error
import urllib.request

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import anchor_gui  # noqa: E402
import distro  # noqa: E402
import mothership_updater  # noqa: E402
import onboard_wizard  # noqa: E402


class _QuietAnchorHandler(anchor_gui.AnchorHandler):
    def log_message(self, fmt, *args):  # noqa: D401
        return


@pytest.fixture
def live_anchor_server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _QuietAnchorHandler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        srv.shutdown()
        srv.server_close()


def _post_json(url: str, payload: dict, headers: dict[str, str] | None = None) -> tuple[int, dict]:
    hdrs = {"Content-Type": "application/json", "User-Agent": "Anchor-Test-Client/1.5.3"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=hdrs,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw.decode("utf-8")) if raw else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            doc = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            doc = {"raw": raw.decode("utf-8", errors="replace")}
        return exc.code, doc


def test_live_http_homebase_registration_push_update_and_telemetry_sync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    live_anchor_server: str,
):
    hb_root = tmp_path / "homebase_data"
    hb_root.mkdir(parents=True)
    (hb_root / "VERSION").write_text("1.5.3\n", encoding="utf-8")

    ws_parent = tmp_path / "collab_ws"
    collab_root = ws_parent / "Anchor"
    collab_root.mkdir(parents=True)
    (collab_root / "VERSION").write_text("1.5.1\n", encoding="utf-8")

    hb_admin_secret = "hb-admin-auth-9988776655443322"
    monkeypatch.setenv("ANCHOR_TOKEN", hb_admin_secret)
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(hb_root))

    # 1. Collaborator registers with Homebase over live HTTP
    reg_res = mothership_updater.register_with_homebase(
        owner="Collaborator Alpha",
        contact_email="alpha@example.org",
        pseudonym="Aladdin",
        hostname="oakley-box",
        tailscale_url=live_anchor_server,
        tailscale_ip="100.124.49.37",
        homebase_url=live_anchor_server,
        telemetry_enabled=True,
        anchor_root=collab_root,
    )
    assert reg_res["ok"] is True
    assert reg_res["registered"] is True
    mid = reg_res["mothership_id"]
    assert mid == "collaborator-alpha-oakley-box"
    assert "node_capability" not in reg_res["link"]
    assert reg_res["link"]["has_capability"] is True

    # Verify Homebase stored capability privately and NOT in mothership_registry.json
    peer_caps_file = hb_root / ".anchor" / "homebase_peer_capabilities.json"
    assert peer_caps_file.is_file()
    peer_caps_doc = json.loads(peer_caps_file.read_text(encoding="utf-8"))
    assert len(peer_caps_doc["peers"][mid]) == 48

    hb_reg_file = hb_root / ".anchor" / "mothership_registry.json"
    assert hb_reg_file.is_file()
    assert "node_capability" not in hb_reg_file.read_text(encoding="utf-8")

    # 1b. TOFU capability pinning & reserved ID defense (B2):
    # - Impersonator attempting to overwrite existing peer id with a different capability -> 409
    code_hijack, hijack_doc = _post_json(
        f"{live_anchor_server}/api/onboard-wizard/action",
        {
            "action": "register_homebase",
            "mothership": {
                "id": mid,
                "owner": "Impersonator",
                "hostname": "rogue",
                "tailscale_url": "http://127.0.0.1:9",
                "node_capability": "a" * 48,
            },
        },
        headers={"X-Forwarded-For": "100.124.49.99"},
    )
    assert code_hijack == 409
    assert hijack_doc["error"] == "peer_already_registered_capability_mismatch"

    # - Reserved lead ID registration attempt -> 403
    code_lead_hijack, _ = _post_json(
        f"{live_anchor_server}/api/onboard-wizard/action",
        {
            "action": "register_homebase",
            "mothership": {
                "id": "gwl-server-lead",
                "owner": "Rogue",
                "hostname": "rogue",
                "node_capability": "b" * 48,
            },
        },
        headers={"X-Forwarded-For": "100.124.49.99"},
    )
    assert code_lead_hijack == 403

    # - Legitimate re-registration by the same collaborator (same capability) -> 200 idempotent
    reg_res_idemp = mothership_updater.register_with_homebase(
        owner="Collaborator Alpha",
        contact_email="alpha@example.org",
        pseudonym="Aladdin",
        hostname="oakley-box",
        tailscale_url=live_anchor_server,
        tailscale_ip="100.124.49.37",
        homebase_url=live_anchor_server,
        telemetry_enabled=True,
        anchor_root=collab_root,
    )
    assert reg_res_idemp["ok"] is True
    assert reg_res_idemp["registered"] is True

    # 2. Switch live server data_dir to collaborator to test Homebase -> Collaborator push_update
    pull_invocations: list[dict] = []

    def _stub_pull(*, target_version=None, sync_skills=True, **kwargs):
        pull_invocations.append({"target_version": target_version, "sync_skills": sync_skills})
        return {"ok": True, "before_version": "1.5.1", "after_version": target_version or "1.5.3", "updated": True}

    monkeypatch.setattr(mothership_updater, "pull_latest_update", _stub_pull)
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(collab_root))
    monkeypatch.setenv("ANCHOR_TOKEN", "collab-private-secret-11223344")

    # 2a-0. Unauthenticated remote attempt to redirect collaborator's homebase_url (B1) -> 401
    code_unauth_reg_out, _ = _post_json(
        f"{live_anchor_server}/api/onboard-wizard/action",
        {"action": "register_with_homebase", "homebase_url": "http://127.0.0.1:9"},
        headers={"X-Forwarded-For": "100.124.49.99"},
    )
    assert code_unauth_reg_out == 401
    assert mothership_updater.read_homebase_link(collab_root)["homebase_url"] == live_anchor_server

    # 2a. Missing capability and wrong capability must be rejected with 401
    code_no_cap, _ = _post_json(
        f"{live_anchor_server}/api/system/pull_update",
        {"target_version": "1.5.3"},
        headers={"X-Forwarded-For": "100.69.215.4"},
    )
    assert code_no_cap == 401

    code_bad_cap, _ = _post_json(
        f"{live_anchor_server}/api/system/pull_update",
        {"target_version": "1.5.3"},
        headers={
            "X-Forwarded-For": "100.69.215.4",
            "X-Anchor-Node-Capability": "0" * 48,
        },
    )
    assert code_bad_cap == 401
    assert pull_invocations == []

    # 2b. Authentic push from Homebase using stored peer capability succeeds with 200
    push_res = mothership_updater.push_update_to_motherships(
        target_id=mid,
        notes="v1.5.3 speed & homebase update",
        push_git=False,
        anchor_root=hb_root,
    )
    assert push_res["ok"] is True
    assert len(push_res["results"]) == 1
    assert push_res["results"][0]["pushed_live"] is True
    assert push_res["results"][0]["queued_bulletin"] is False
    assert len(pull_invocations) == 1
    assert pull_invocations[0]["target_version"] == "1.5.3"

    # 3. Switch live server back to Homebase and verify Collaborator -> Homebase journal & error sync
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(hb_root))
    monkeypatch.setenv("ANCHOR_TOKEN", hb_admin_secret)

    err_dir = collab_root / "logs"
    err_dir.mkdir(parents=True, exist_ok=True)
    secret_marker = "sk-" + "liveSecretKey9876543210abcd"
    query_tok = "abcdef0123456789abcdef0123456789"
    (err_dir / "errors.log").write_text(
        f"2026-11-20 10:15:00 ERROR upstream call failed with {secret_marker} and GET /api/status?token={query_tok} for alpha@example.org in C:\\Users\\example\\secret.py\n"
        "  Traceback: ValueError: sample diagnostic error\n",
        encoding="utf-8",
    )

    (collab_root / ".anchor" / "install_journal.md").write_text(
        "# Install Journal\nCompleted Step 2 Tailscale and Homebase registration.\n",
        encoding="utf-8",
    )

    sk_j_dir = ws_parent / "skills" / "foreman" / "journal"
    sk_j_dir.mkdir(parents=True, exist_ok=True)
    (sk_j_dir / "0001-collab-lesson.md").write_text(
        "# 0001 Collaborator Lesson\nObserved Windows path quoting issue during build gate.\n",
        encoding="utf-8",
    )

    hc_dir = collab_root / "health_reports"
    hc_dir.mkdir(parents=True, exist_ok=True)
    (hc_dir / "2026-11-20.md").write_text(
        "# Anchor Health Report\nStatus: ISSUES FOUND\n- Sample check timed out.\n",
        encoding="utf-8",
    )

    tel_res = mothership_updater.sync_telemetry_to_homebase(anchor_root=collab_root)
    assert tel_res["ok"] is True
    assert tel_res["sent_count"] == 4

    # Second immediate sync is idempotent (watermarks prevent duplicate transmission)
    tel_res_again = mothership_updater.sync_telemetry_to_homebase(anchor_root=collab_root)
    assert tel_res_again["ok"] is True
    assert tel_res_again["sent_count"] == 0

    # Forged capability on telemetry submission -> 401
    code_forged_tel, _ = _post_json(
        f"{live_anchor_server}/api/onboard-wizard/action",
        {"action": "submit_homebase_telemetry", "mothership_id": mid, "events": [{"kind": "error", "title": "fake"}]},
        headers={"X-Anchor-Node-Capability": "f" * 48, "X-Forwarded-For": "100.124.49.37"},
    )
    assert code_forged_tel == 401

    # Unauthenticated list_homebase_telemetry (even trying to spoof _req_auth_ok) -> 401
    code_unauth_list, _ = _post_json(
        f"{live_anchor_server}/api/onboard-wizard/action",
        {"action": "list_homebase_telemetry", "_req_auth_ok": True},
        headers={"X-Forwarded-For": "100.124.49.37"},
    )
    assert code_unauth_list == 401

    # Authenticated Homebase admin reads all 4 scrubbed events
    code_ok_list, list_doc = _post_json(
        f"{live_anchor_server}/api/onboard-wizard/action",
        {"action": "list_homebase_telemetry", "mothership_id": mid},
        headers={"Authorization": f"Bearer {hb_admin_secret}"},
    )
    assert code_ok_list == 200
    assert list_doc["ok"] is True
    assert list_doc["count"] == 4
    kinds = {ev["kind"] for ev in list_doc["events"]}
    assert kinds == {"error", "health_issue", "journal"}
    combined_json = json.dumps(list_doc["events"])
    assert secret_marker not in combined_json
    assert query_tok not in combined_json
    assert "alpha@example.org" not in combined_json
    assert "<redacted>" in combined_json
    assert "<redacted-email>" in combined_json
    assert (hb_root / ".anchor" / "homebase_telemetry" / mid / "LATEST.md").is_file()


def test_onboard_wizard_step2_html_receipt_and_distro_gate(tmp_path: Path):
    html = onboard_wizard.render_onboard_wizard_html(sandbox=True, base_dir=tmp_path)
    assert "btnRegisterHomebase" in html
    assert "chkHomebaseTelemetry" in html
    assert "https://gwl-server.tailb49f65.ts.net" in html
    assert "Anchor Homebase Registration" in html

    receipt = onboard_wizard.build_readiness_receipt(sandbox=False, base_dir=tmp_path)
    chk_ids = [c["id"] for c in receipt["checks"]]
    assert "homebase_registration" in chk_ids

    selected = distro.select_shippable(root=REPO_ROOT)
    pairs = [(rel, REPO_ROOT / rel) for rel in selected]
    hits = distro.scan_paths(pairs, root=REPO_ROOT)
    assert hits == [], f"distro gate must remain completely clean: {hits!r}"
