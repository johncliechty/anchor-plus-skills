"""Regression & Health-Check Suite for Mother Ship Performance Fix Pack (2026-11-19).

Covers:
1. Zero `distro.scan_paths` findings across all modified server, JS, shell & healthcheck files.
2. `GET /api/steward/comms?slim=1` strips multi-KB archived bodies while keeping unread Prime bodies & snippets.
3. IMAP RFC-2822 header dates normalize to local `YYYY-MM-DD HH:MM` (matching Microsoft Graph local timestamps).
4. `anchor_gui._send_json` negotiates lossless `gzip` compression (`Content-Encoding: gzip`) when `Accept-Encoding: gzip` is sent, while preserving raw JSON for plain `urllib` callers.
5. `/api/steward/deliverable-file?...&download=1&filename=...` honors the clean resolved `.docx` filename in `Content-Disposition`.
6. `anvil_session.get_session_status(..., summary_only=True)` skips expensive AST bucket clustering & `SyntaxWarning` spam.
7. `anchor_healthcheck.check_mothership_slowdown_and_polling_health` passes hard invariants cleanly and emits non-blocking `report.warn` (never false-red) on simulated `SLOW` Cave stalls / request storms per the 2026-07-07 Severity Rule.
"""
from __future__ import annotations

import gzip
import json
import os
import threading
import urllib.request
import warnings
from datetime import datetime, timezone
from pathlib import Path

import anchor_gui
import anchor_healthcheck
import comms_connector
import distro
import rnd_registry
from steward_cockpit import anvil_session

ANCHOR_ROOT = Path(__file__).resolve().parent.parent


def test_distro_scan_clean_on_mothership_perf_files() -> None:
    targets = [
        ("anchor_gui.py", ANCHOR_ROOT / "anchor_gui.py"),
        ("usage_capacity.py", ANCHOR_ROOT / "usage_capacity.py"),
        ("comms_connector.py", ANCHOR_ROOT / "comms_connector.py"),
        ("anchor_healthcheck.py", ANCHOR_ROOT / "anchor_healthcheck.py"),
        ("steward_cockpit/steward_routes.py", ANCHOR_ROOT / "steward_cockpit" / "steward_routes.py"),
        ("steward_cockpit/anvil_session.py", ANCHOR_ROOT / "steward_cockpit" / "anvil_session.py"),
        ("static/high-seat-page.js", ANCHOR_ROOT / "static" / "high-seat-page.js"),
    ]
    findings = distro.scan_paths(targets)
    assert findings == [], f"Unexpected distro findings: {findings}"


def test_imap_header_date_normalizes_to_local_matching_graph() -> None:
    utc_dt = datetime(2026, 11, 19, 14, 37, tzinfo=timezone.utc)
    expected_local = utc_dt.astimezone().strftime("%Y-%m-%d %H:%M")
    hdr = comms_connector._parse_imap_header_block(
        "Subject: Sync Check\r\nFrom: Alice <alice@example.org>\r\nDate: Thu, 19 Nov 2026 14:37:00 +0000\r\n"
    )
    assert hdr["date"] == expected_local


def test_gzip_slim_comms_and_clean_docx_download_roundtrip(tmp_path: Path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    (data_dir / ".anchor").mkdir(parents=True, exist_ok=True)
    ephem_tok = os.urandom(12).hex()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data_dir))
    monkeypatch.setenv("ANCHOR_TOKEN", ephem_tok)

    heavy_text = "Long archived email body line for compression test. " * 600
    (data_dir / ".anchor" / "comms-config.json").write_text(
        json.dumps({"version": 1, "accounts": [], "preferences": {"sync_interval_minutes": 1}}),
        encoding="utf-8",
    )
    (data_dir / ".anchor" / "comms-sync.json").write_text(
        json.dumps({
            "synced_at": "2026-11-19 12:30",
            "calendar_events": [],
            "email_headers": [
                {
                    "uid": "u-prime",
                    "subject": "Action Needed Today",
                    "from": "Colleague <colleague@example.org>",
                    "sender_email": "colleague@example.org",
                    "date": "2026-11-19 12:20",
                    "body": "Unread body preserved.",
                    "snippet": "Unread body preserved.",
                    "is_read": False,
                    "account_id": "a1",
                    "account_badge": "Work",
                },
                {
                    "uid": "u-archived",
                    "subject": "Old Handled Thread",
                    "from": "Newsletter <news@example.org>",
                    "sender_email": "news@example.org",
                    "date": "2026-11-18 09:00",
                    "body": heavy_text,
                    "quoted_history": heavy_text,
                    "snippet": "Compact snippet.",
                    "is_read": True,
                    "account_id": "a1",
                    "account_badge": "Work",
                },
            ],
            "sent_email_headers": [],
            "notes": [],
            "provider_states": {},
        }),
        encoding="utf-8",
    )

    proj_dir = tmp_path / "proj"
    eff_dir = proj_dir / "Book 1"
    eff_dir.mkdir(parents=True, exist_ok=True)
    (eff_dir / "rev_hash_99.docx").write_bytes(b"PK\x03\x04test-word-doc-bytes" * 60)
    proj = rnd_registry.add_project("Book Test", str(proj_dir))
    pid = proj["id"]

    srv = anchor_gui.make_server("127.0.0.1", 0)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        # 1. With Accept-Encoding: gzip -> gzipped & slimmed
        req_gz = urllib.request.Request(
            f"{base}/api/steward/comms?slim=1",
            headers={"Authorization": f"Bearer {ephem_tok}", "Accept-Encoding": "gzip"},
        )
        with urllib.request.urlopen(req_gz, timeout=15) as r_gz:
            wire_gz = r_gz.read()
            assert r_gz.headers.get("Content-Encoding") == "gzip"
        payload = json.loads(gzip.decompress(wire_gz).decode("utf-8"))
        assert payload["ok"] is True and payload["slim"] is True
        archived = [x for x in payload["all_emails"] if x.get("uid") == "u-archived"]
        assert archived and "body" not in archived[0] and "thread_messages" not in archived[0]
        assert 0 < len(archived[0]["snippet"]) <= 200

        # 2. Without Accept-Encoding: gzip -> raw JSON preserved for legacy urllib callers
        req_plain = urllib.request.Request(
            f"{base}/api/steward/comms",
            headers={"Authorization": f"Bearer {ephem_tok}"},
        )
        with urllib.request.urlopen(req_plain, timeout=15) as r_pl:
            wire_pl = r_pl.read()
            assert r_pl.headers.get("Content-Encoding") is None
        full_payload = json.loads(wire_pl.decode("utf-8"))
        full_arch = [x for x in full_payload["all_emails"] if x.get("uid") == "u-archived"]
        assert full_arch and "body" in full_arch[0]

        # 3. Clean .docx download=1 filename preserved in Content-Disposition
        dl_req = urllib.request.Request(
            f"{base}/api/steward/deliverable-file?pid={pid}&dir=Book+1&path=rev_hash_99.docx&download=1&filename=Manuscript_Ch7_8_v5.docx",
            headers={"Authorization": f"Bearer {ephem_tok}"},
        )
        with urllib.request.urlopen(dl_req, timeout=15) as r_dl:
            dl_body = r_dl.read()
            cd = r_dl.headers.get("Content-Disposition") or ""
        assert len(dl_body) > 100
        assert 'attachment; filename="Manuscript_Ch7_8_v5.docx"' == cd
    finally:
        srv.shutdown()
        srv.server_close()
        th.join(timeout=5)


def test_anvil_summary_only_skips_ast_syntax_warnings(tmp_path: Path) -> None:
    eff = tmp_path / "Paper 1"
    eff.mkdir(parents=True, exist_ok=True)
    (eff / "grid.py").write_text('formula = "\\m + \\,"\n', encoding="utf-8")
    av_dir = eff / ".anvil"
    av_dir.mkdir(parents=True, exist_ok=True)
    (av_dir / "session.json").write_text(
        json.dumps({
            "active": True,
            "updated_at": "2026-11-19T12:00:00Z",
            "software": {"path": str(eff)},
            "code_map": {"conceptual_buckets": [{"id": f"b{i}"} for i in range(11)]},
        }),
        encoding="utf-8",
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", SyntaxWarning)
        st = anvil_session.get_session_status(eff, summary_only=True)
    assert st["ok"] is True and st["summary_only"] is True
    assert st["v4_stamp"]["updated_at"] == "2026-11-19T12:00:00Z"
    assert [w for w in caught if issubclass(w.category, SyntaxWarning)] == []


def test_healthcheck_mothership_slowdown_criteria_pass_and_warn(tmp_path: Path, monkeypatch) -> None:
    # 1. Clean DATA_DIR -> passes with zero issues and zero warnings
    clean_data = tmp_path / "clean_data"
    (clean_data / "logs").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(anchor_healthcheck, "DATA_DIR", clean_data)
    rep_clean = anchor_healthcheck.Report()
    anchor_healthcheck.check_mothership_slowdown_and_polling_health(rep_clean)
    assert not rep_clean.has_issues, f"Unexpected hard issues: {rep_clean.issues}"
    assert rep_clean.warnings == []

    # 2. Simulated 36.7s Cave stall in nssm-stdout.log -> emits non-blocking warn (never false-red)
    (clean_data / "logs" / "nssm-stdout.log").write_text(
        "  [12:10:24] SLOW the Cave of Wonders took 36.7s\n",
        encoding="utf-8",
    )
    rep_slow = anchor_healthcheck.Report()
    anchor_healthcheck.check_mothership_slowdown_and_polling_health(rep_slow)
    assert not rep_slow.has_issues
    assert any("36.7s" in w for w in rep_slow.warnings)
