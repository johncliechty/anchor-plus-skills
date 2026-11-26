"""Wave 1 — Canonical Claude Fable 5.2 Routing, Positive Attestation & Gemini Write-Progress Pilot.

Exercises:
1. Anchor `model_policy` & `provider_setup` discovery, selection, and positive `claude-fable-5-2` attestation
   (refusing silent `claude-opus-5-5` substitution fail-closed).
2. `steward_cockpit.gemini_turn_bridge` live `write_file` / `edit_file` `Path` extraction (`tool_use` + `tool_result`
   + `made_progress` tracking).
3. `/api/provider-setup` 5-row surface failure-state contract (`dependency-missing` 503,
   `dependency-slow-or-killed` 504, `dependency-returns-garbage` 502, `backing-store-unreadable` 500 UNKNOWN,
   `empty-but-valid` 200 EMPTY — keeping UNKNOWN and EMPTY strictly separate) + `ft.py look` verification on
   `w1-provider-setup.html` and an ephemeral loopback `/setup` server (`port != 8777`).
4. Cross-repo `shell=False` subprocess wrappers for Trio drivers (`node --test`), Gandalf (`node --test`),
   and Skill Foundry Anvil (`pytest`).
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
from urllib.parse import urlsplit

import pytest

import anchor_settings as settings
import model_policy
import provider_setup as setup
from steward_cockpit import gemini_turn_bridge as gbridge
from tests.test_provider_setup import (  # noqa: F401 (fixtures)
    AUTH,
    NativeFixture,
    authenticated,
    http_request,
    server,
    stack,
)

ANCHOR_ROOT = Path(__file__).resolve().parents[1]
DEV_ROOT = ANCHOR_ROOT.parent
TRIO_DRIVERS_TEST_DIR = DEV_ROOT / "trio" / "drivers" / "test"
GANDALF_DIR = DEV_ROOT / "Skill Foundry" / "skills" / "gandalf"
ANVIL_TESTS_DIR = DEV_ROOT / "Skill Foundry" / "skills" / "anvil" / "tests"
FT_CLI = DEV_ROOT / "foundry-tools" / "ft.py"
W1_MOCKUP = ANCHOR_ROOT / "planning" / "cross-system-upgrade-2026-11-20" / "mockups" / "w1-provider-setup.html"
W1_LOOK_OUT = ANCHOR_ROOT / "planning" / "cross-system-upgrade-2026-11-20" / "looks" / "w1"

REAL_DISCOVER = model_policy.discover


def _parse_node_pass_count(output: str) -> int:
    tap_matches = re.findall(r"(?m)^(?:#\s+|\u2139\s+)pass\s+(\d+)\b", output)
    if tap_matches:
        return sum(int(n) for n in tap_matches)
    ok_lines = re.findall(r"(?m)^(?:ok\s+\d+\s+-|\u2714\s+)", output)
    return len(ok_lines)


def _parse_pytest_pass_count(output: str) -> int:
    matches = re.findall(r"\b(\d+)\s+passed\b", output)
    return int(matches[-1]) if matches else 0


def test_w1_fable_policy_and_attestation(monkeypatch, tmp_path):
    model_policy._MEMORY.clear()
    calls: list[list[str]] = []

    def stub_runner(argv, _env):
        calls.append(list(argv))
        return "Usage: claude [options]\n  --effort <level>  Effort level (low, medium, high, max)\n"

    monkeypatch.setattr(shutil, "which", lambda cmd, path=None: "claude-stub" if "claude" in str(cmd) else None)
    rows, command = REAL_DISCOVER("claude", env={"PATH": "stub"}, runner=stub_runner)
    assert command == "claude-stub"
    assert len(calls) == 1 and calls[0] == ["claude-stub", "--help"]
    assert [r["model"] for r in rows] == [
        "claude-fable-5-2",
        "claude-opus-5-5",
        "best",
        "opus",
        "sonnet",
        "haiku",
    ]
    assert rows[0]["rank"] == 0

    selected = model_policy.select_model("claude", rows)
    assert selected["model"] == "claude-fable-5-2"
    assert selected["effort"] == "max"
    assert model_policy.launch_args(selected) == ["--model", "claude-fable-5-2", "--effort", "max"]

    resolved = model_policy.resolve(
        "claude",
        force=True,
        env={"PATH": "stub"},
        discoverer=lambda fam, env=None: (rows, "claude-stub"),
    )
    assert resolved["model"] == "claude-fable-5-2"
    assert resolved["effort"] == "max"

    # Positive served-model attestation succeeds ONLY when claude-fable-5-2 is attested
    verified = model_policy.attest_claude_fable_receipt(
        {
            "ok": True,
            "requested_model": "claude-fable-5-2",
            "model_served": "claude-fable-5-2",
            "model_attested": True,
        }
    )
    assert verified["ok"] is True
    assert verified["status"] == "success"
    assert verified["model_served"] == "claude-fable-5-2"
    assert verified["model_attested"] is True

    # Silent substitution to claude-opus-5-5 MUST fail closed
    substituted = model_policy.attest_claude_fable_receipt(
        {
            "ok": True,
            "requested_model": "claude-fable-5-2",
            "model_served": "claude-opus-5-5",
            "model_attested": True,
        }
    )
    assert substituted["ok"] is False
    assert substituted["status"] == "attestation_mismatch"
    assert "claude-opus-5-5" in substituted["error"]

    # Unattested receipt MUST also fail closed
    unattested = model_policy.attest_claude_fable_receipt(
        {
            "ok": True,
            "requested_model": "claude-fable-5-2",
            "model_served": None,
            "model_attested": False,
        }
    )
    assert unattested["ok"] is False
    assert unattested["status"] == "attestation_mismatch"

    # Dated Fable suffix normalizes cleanly; receipt.requested_model is honored when arg omitted;
    # fallback_from_model bypass is strictly restricted to non-verification roles
    dated_fable = model_policy.attest_claude_fable_receipt(
        {
            "ok": True,
            "requested_model": "claude-fable-5-2",
            "model_served": "claude-fable-5-2-20261120",
            "model_attested": True,
        },
        role="shark",
    )
    assert dated_fable["ok"] is True
    assert dated_fable["model_served"] == "claude-fable-5-2"

    non_fable_conversational = model_policy.attest_claude_fable_receipt(
        {
            "ok": True,
            "requested_model": "sonnet",
            "model_served": "sonnet",
            "model_attested": True,
        }
    )
    assert non_fable_conversational["ok"] is True

    forged_verify_fallback = model_policy.attest_claude_fable_receipt(
        {
            "ok": True,
            "requested_model": "claude-fable-5-2",
            "fallback_from_model": "claude-fable-5-2",
            "model_served": "sonnet",
            "model_attested": True,
        },
        role="review",
    )
    assert forged_verify_fallback["ok"] is False
    assert forged_verify_fallback["status"] == "attestation_mismatch"

    legit_exec_fallback = model_policy.attest_claude_fable_receipt(
        {
            "ok": True,
            "requested_model": "claude-fable-5-2",
            "fallback_from_model": "claude-fable-5-2",
            "model_served": "sonnet",
            "model_attested": True,
        },
        role="execute",
    )
    assert legit_exec_fallback["ok"] is True

    # Heavy / verification role in model_policy.resolve & provider_setup.resolve_quality pins claude-fable-5-2
    # even when provider_preferences.quality.claude holds sonnet
    monkeypatch.setattr(model_policy, "discover", lambda fam, env=None, **kw: (rows, "claude-stub"))
    pinned_qual = setup.resolve_quality(
        "claude",
        {
            "model_policy": dict(model_policy.DEFAULT_POLICY),
            "settings_revision": 2,
            "provider_preferences": {"quality": {"claude": {"model": "sonnet", "effort": "max"}}},
        },
        {"id": "claude-default", "family": "claude", "mode": "subscription", "native_default": True},
        role="review",
    )
    assert pinned_qual["model"] == "claude-fable-5-2"
    assert pinned_qual["effort"] == "max"
    assert pinned_qual["selection_evidence"] == "heavy_review_fable_pin"

    # Provider setup routing summary surfaces claude-fable-5-2 (never claude-fable-5-1), even if conversational quality is sonnet
    summary = setup._build_services_and_routing_summary(
        {
            "default_cli": "gemini",
            "coding_family": "gemini",
            "review_family": "claude",
            "provider_preferences": {"quality": {"claude": {"model": "sonnet", "effort": "max"}}},
        },
        [{"id": "claude-default", "family": "claude", "auth": "signed_in", "mode": "subscription"}],
        {"claude": {"installed": True}, "gemini": {"installed": True}},
    )
    assert summary["review_routing"]["family"] == "claude"
    assert summary["review_routing"]["effective_model_id"] == "claude-fable-5-2"
    assert "claude-fable-5-2" in summary["review_routing"]["model_display"]
    assert "claude-fable-5-1" not in json.dumps(summary)
    assert summary["catalog_defaults"]["claude"]["frontier_model"] == "claude-fable-5-2"

    # Production receipt wiring: steward_engine._handle fails closed on Claude verification seat substitution
    import paths as _paths
    from steward_cockpit import steward_engine as se

    isolated_data = tmp_path / "isolated_anchor_data"
    isolated_data.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(_paths, "data_dir", lambda: isolated_data)
    monkeypatch.setattr(settings, "settings_path", lambda: isolated_data / "settings.json")
    monkeypatch.setattr(settings, "mirror_path", lambda: tmp_path / "isolated_mirror" / "model_prefs.json")
    settings.save_settings(default_cli="claude", coding_family="claude", review_family="claude", steward_type="aladdin")

    tmp_eng_dir = tmp_path / "eng_w1_attest_check"
    tmp_eng_dir.mkdir(parents=True, exist_ok=True)
    eng = se.Engine(str(tmp_eng_dir), fake=True, steward="Aladdin")
    eng.fake = False
    eng.cli = "claude"
    eng.role = "review"
    sentinel_proc = object()
    eng.proc = sentinel_proc
    eng.model_selection = {
        "family": "claude",
        "cli": "claude",
        "model": "claude-fable-5-2",
        "effort": "max",
    }
    emitted_events: list[dict] = []
    eng._emit = lambda payload: emitted_events.append(dict(payload))
    eng._record_usage_result = lambda _ev: None
    eng._handle(
        {
            "type": "result",
            "is_error": False,
            "result": "SILENT_DOWNGRADE",
            "modelUsage": {"claude-opus-5-5": {"inputTokens": 10, "outputTokens": 5}},
        },
        sentinel_proc,
    )
    assert eng.model_selection["model_served"] == "claude-opus-5-5"
    assert eng.model_selection["model_attested"] is False
    assert any("Claude positive attestation failed" in str(e.get("text") or "") for e in emitted_events)


def test_w1_gemini_write_edit_progress():
    for tool_name in ("write_file", "edit_file", "multi_replace_file_content"):
        assert tool_name in gbridge._WRITE_TOOLS
        assert tool_name in gbridge._PROGRESS_TOOL_NAMES

    cid = "11111111-2222-3333-4444-555555555555"
    norm = gbridge.GeminiNormalizer("gemini-3.1-pro", "high")

    init_ev = {"event": "init", "conversation_id": cid, "init": {"model": "gemini-3.1-pro-high"}}
    init_out = norm.accept(init_ev)
    assert init_out[0]["type"] == "system"

    # 1) write_file carrying parameters.Path on RUNNING -> DONE
    write_running = {
        "event": "step_update",
        "step_update": {
            "conversation_id": cid,
            "step_index": 1,
            "step_type": "tool",
            "tool_name": "write_file",
            "state": "RUNNING",
            "tool_info": {"name": "write_file", "parameters": {"Path": "/repo/src/module_a.py"}},
        },
    }
    out_wr = norm.accept(write_running)
    assert len(out_wr) == 1
    assert out_wr[0]["type"] == "assistant"
    block_wr = out_wr[0]["message"]["content"][0]
    assert block_wr["type"] == "tool_use"
    assert block_wr["name"] == "write_file"
    assert block_wr["input"]["file_path"] == "/repo/src/module_a.py"
    assert norm.made_progress(write_running, out_wr) is True

    # Duplicate identical RUNNING heartbeat does not count as new progress
    out_wr_dup = norm.accept(write_running)
    assert out_wr_dup == []
    assert norm.made_progress(write_running, out_wr_dup) is False

    write_done = {
        "event": "step_update",
        "step_update": {
            "conversation_id": cid,
            "step_index": 1,
            "step_type": "tool",
            "tool_name": "write_file",
            "state": "DONE",
            "tool_info": {"name": "write_file", "parameters": {"Path": "/repo/src/module_a.py"}},
        },
    }
    out_wd = norm.accept(write_done)
    assert len(out_wd) == 1
    assert out_wd[0]["type"] == "user"
    res_wd = out_wd[0]["message"]["content"][0]
    assert res_wd == {"type": "tool_result", "tool_use_id": f"{cid}:1", "is_error": False}
    assert norm.made_progress(write_done, out_wd) is True

    # 2) edit_file where RUNNING arrives before parameters.Path, then ERROR arrives with Path:
    #    must defer initial tool_use so each step_index emits AT MOST ONE tool_use block (no duplicate IDs)
    edit_start = {
        "event": "step_update",
        "step_update": {
            "conversation_id": cid,
            "step_index": 2,
            "step_type": "tool",
            "tool_name": "edit_file",
            "state": "RUNNING",
            "tool_info": {"name": "edit_file", "parameters": {}},
        },
    }
    out_es = norm.accept(edit_start)
    assert out_es == []
    assert norm.made_progress(edit_start, out_es) is True

    edit_err = {
        "event": "step_update",
        "step_update": {
            "conversation_id": cid,
            "step_index": 2,
            "step_type": "tool",
            "tool_name": "edit_file",
            "state": "ERROR",
            "tool_info": {"name": "edit_file", "parameters": {"Path": "/repo/src/module_b.py"}},
        },
    }
    out_ee = norm.accept(edit_err)
    assert len(out_ee) == 2
    assert out_ee[0]["type"] == "assistant"
    assert out_ee[0]["message"]["content"][0]["id"] == f"{cid}:2"
    assert out_ee[0]["message"]["content"][0]["input"]["file_path"] == "/repo/src/module_b.py"
    assert out_ee[1]["type"] == "user"
    assert out_ee[1]["message"]["content"][0] == {
        "type": "tool_result",
        "tool_use_id": f"{cid}:2",
        "is_error": True,
    }
    assert norm.made_progress(edit_err, out_ee) is True

    # 3) write_file where no Path ever arrives still emits a single tool_use + matching tool_result on DONE
    pathless_start = {
        "event": "step_update",
        "step_update": {
            "conversation_id": cid,
            "step_index": 3,
            "step_type": "tool",
            "tool_name": "write_file",
            "state": "RUNNING",
            "tool_info": {"name": "write_file", "parameters": {}},
        },
    }
    out_ps = norm.accept(pathless_start)
    assert out_ps == []
    assert norm.made_progress(pathless_start, out_ps) is True

    pathless_done = {
        "event": "step_update",
        "step_update": {
            "conversation_id": cid,
            "step_index": 3,
            "step_type": "tool",
            "tool_name": "write_file",
            "state": "DONE",
            "tool_info": {"name": "write_file", "parameters": {}},
        },
    }
    out_pd = norm.accept(pathless_done)
    assert len(out_pd) == 2
    assert out_pd[0]["type"] == "assistant"
    assert out_pd[0]["message"]["content"][0]["id"] == f"{cid}:3"
    assert "file_path" not in out_pd[0]["message"]["content"][0]["input"]
    assert out_pd[1]["type"] == "user"
    assert out_pd[1]["message"]["content"][0] == {
        "type": "tool_result",
        "tool_use_id": f"{cid}:3",
        "is_error": False,
    }
    assert norm.made_progress(pathless_done, out_pd) is True


def _run_look_gate(target_url_or_path: str, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            sys.executable,
            str(FT_CLI),
            "look",
            target_url_or_path,
            "--check",
            "[data-provider-model='claude-fable-5-2']",
            "--out",
            str(out_dir),
            "--json",
        ],
        cwd=str(ANCHOR_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
        shell=False,
    )
    assert proc.returncode == 0, f"ft.py look failed ({proc.returncode}): {proc.stderr}\n{proc.stdout}"
    verdict = json.loads(proc.stdout)
    results = verdict.get("results", [])
    assert len(results) >= 2, f"ft.py look expected phone+desktop results: {verdict}"
    for vp in results:
        assert vp.get("errors") == [], f"page/console errors on {vp.get('size')}: {vp.get('errors')}"
        shot_path = Path(vp["screenshot"])
        assert shot_path.is_file() and shot_path.stat().st_size > 0
        checks_map = vp.get("checks", {})
        checks = checks_map.get("[data-provider-model='claude-fable-5-2']", [])
        assert len(checks) >= 1, f"no elements matched selector on viewport {vp.get('size')}: {vp}"
        for chk in checks:
            assert chk.get("painted") is True, f"unpainted element on {vp.get('size')}: {chk}"
            assert chk.get("coveredBy") is None, f"covered element on {vp.get('size')}: {chk}"
    return verdict


def test_w1_provider_setup_5_failure_states(server, monkeypatch, tmp_path):
    origin, (service, _backend, data_dir, _home_dir) = server
    parsed_origin = urlsplit(origin)
    assert parsed_origin.port is not None and parsed_origin.port != 8777

    # Verify table schema keeps UNKNOWN and EMPTY as distinct rows
    table = setup.PROVIDER_SETUP_FAILURE_STATE_TABLE
    assert set(table) == {
        "dependency-missing",
        "dependency-slow-or-killed",
        "dependency-returns-garbage",
        "backing-store-unreadable",
        "empty-but-valid",
    }
    assert table["backing-store-unreadable"]["badge"] == "UNKNOWN"
    assert table["backing-store-unreadable"]["unknown_state"] is True
    assert table["empty-but-valid"]["badge"] == "EMPTY"
    assert table["empty-but-valid"]["unknown_state"] is False
    assert table["backing-store-unreadable"]["badge"] != table["empty-but-valid"]["badge"]

    opener = authenticated(origin)

    # Authenticated /setup HTML must NOT hardcode [data-provider-model]; JS sets it dynamically from live state
    st_html, raw_html = http_request(opener, origin, "/setup?section=providers")
    assert st_html == 200
    assert "data-provider-model=" not in raw_html

    # Row 1: dependency-missing -> 503 (cli_missing, auth_required, and wrapped FileNotFoundError)
    def _raise_missing(family, **kwargs):
        raise model_policy.PolicyUnavailable(family, "CLI is not installed", code="cli_missing")

    monkeypatch.setattr(model_policy, "discover", _raise_missing)
    code_503, body_503 = http_request(opener, origin, "/api/provider-setup?catalog_probe=claude")
    doc_503 = json.loads(body_503)
    assert code_503 == 503
    assert doc_503["status_kind"] == "dependency-missing"
    assert doc_503["badge"] == "DEPENDENCY_MISSING"
    assert doc_503["unknown_state"] is False

    def _raise_auth_required(family, **kwargs):
        raise model_policy.PolicyUnavailable(
            family, "CLI discovery exited 1; subscription login required", code="auth_required"
        )

    monkeypatch.setattr(model_policy, "discover", _raise_auth_required)
    code_503_auth, body_503_auth = http_request(opener, origin, "/api/provider-setup?catalog_probe=claude")
    doc_503_auth = json.loads(body_503_auth)
    assert code_503_auth == 503
    assert doc_503_auth["status_kind"] == "dependency-missing"

    def _raise_wrapped_fnf(family, **kwargs):
        raise model_policy.PolicyUnavailable(family, "CLI discovery FileNotFoundError")

    monkeypatch.setattr(model_policy, "discover", _raise_wrapped_fnf)
    code_503_fnf, body_503_fnf = http_request(opener, origin, "/api/provider-setup?catalog_probe=claude")
    doc_503_fnf = json.loads(body_503_fnf)
    assert code_503_fnf == 503
    assert doc_503_fnf["status_kind"] == "dependency-missing"

    # Row 2: dependency-slow-or-killed -> 504
    def _raise_timeout(family, **kwargs):
        raise subprocess.TimeoutExpired(cmd=[family, "--help"], timeout=25)

    monkeypatch.setattr(model_policy, "discover", _raise_timeout)
    code_504, body_504 = http_request(opener, origin, "/api/provider-setup?catalog_probe=claude")
    doc_504 = json.loads(body_504)
    assert code_504 == 504
    assert doc_504["status_kind"] == "dependency-slow-or-killed"
    assert doc_504["badge"] == "TIMEOUT"
    assert doc_504["unknown_state"] is False

    # Row 3: dependency-returns-garbage -> 502
    def _raise_garbage(family, **kwargs):
        raise model_policy.PolicyUnavailable(family, "invalid capability catalog")

    monkeypatch.setattr(model_policy, "discover", _raise_garbage)
    code_502, body_502 = http_request(opener, origin, "/api/provider-setup?catalog_probe=claude")
    doc_502 = json.loads(body_502)
    assert code_502 == 502
    assert doc_502["status_kind"] == "dependency-returns-garbage"
    assert doc_502["badge"] == "REJECTED_GARBAGE"
    assert doc_502["unknown_state"] is False

    # Row 4: backing-store-unreadable -> 500 UNKNOWN (unknown_state=True) on DEFAULT /api/provider-setup route
    settings_file = settings.settings_path()
    saved_bytes = settings_file.read_bytes()
    try:
        settings_file.write_text("{corrupt-json-unreadable", encoding="utf-8")
        for endpoint in ("/api/provider-setup", "/api/provider-setup?surface_probe=1"):
            code_500, body_500 = http_request(opener, origin, endpoint)
            doc_500 = json.loads(body_500)
            assert code_500 == 500
            assert doc_500["status_kind"] == "backing-store-unreadable"
            assert doc_500["badge"] == "UNKNOWN"
            assert doc_500["unknown_state"] is True

        # Row 5: empty-but-valid -> 200 EMPTY (unknown_state=False, distinct from UNKNOWN) on DEFAULT route
        settings_file.write_text(
            json.dumps({"provider_connections": [], "settings_revision": 1}),
            encoding="utf-8",
        )
        for endpoint in ("/api/provider-setup", "/api/provider-setup?surface_probe=1"):
            code_200, body_200 = http_request(opener, origin, endpoint)
            doc_200 = json.loads(body_200)
            assert code_200 == 200
            assert doc_200["ok"] is True
            assert doc_200["status_kind"] == "empty-but-valid"
            assert doc_200["badge"] == "EMPTY"
            assert doc_200["unknown_state"] is False
            assert doc_200["connections"] == []
    finally:
        settings_file.write_bytes(saved_bytes)

    # L3 Gate Part A: hermetic mockup HTML (writes phone + desktop PNGs + verdict JSON into looks/w1)
    assert W1_MOCKUP.is_file(), f"Missing Wave 1 mockup: {W1_MOCKUP}"
    mockup_text = W1_MOCKUP.read_text(encoding="utf-8")
    assert "127.0.0.1:8777" not in mockup_text and "localhost:8777" not in mockup_text
    verdict_mockup = _run_look_gate(str(W1_MOCKUP), W1_LOOK_OUT)
    (W1_LOOK_OUT / "verdict.json").write_text(json.dumps(verdict_mockup, indent=2), encoding="utf-8")

    # L3 Gate Part B: ephemeral loopback /setup server on port != 8777 serving real static/provider-setup.html
    fable_rows = [
        {"model": "claude-fable-5-2", "efforts": ["low", "medium", "high", "max"], "rank": 0, "upgrade": None, "evidence": "provider_moving_alias"},
        {"model": "claude-opus-5-5", "efforts": ["low", "medium", "high", "max"], "rank": 1, "upgrade": None, "evidence": "provider_moving_alias"},
    ]
    monkeypatch.setattr(model_policy, "discover", lambda fam, **kw: (list(fable_rows), "claude-stub"))
    live_snap = service.snapshot(True)
    state_holder = {"snap": live_snap}

    class _HermeticSetupPreviewHandler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def do_GET(self):
            req_path = urlsplit(self.path).path
            if req_path == "/setup":
                body = (ANCHOR_ROOT / "static" / "provider-setup.html").read_bytes()
                self._reply(200, "text/html; charset=utf-8", body)
                return
            if req_path == "/api/provider-setup":
                self._reply(200, "application/json", json.dumps(state_holder["snap"]).encode("utf-8"))
                return
            if req_path.startswith("/api/"):
                self._reply(200, "application/json", b'{"ok": true, "accounts": []}')
                return
            if req_path.startswith("/static/") or req_path.startswith("/vendor/"):
                rel = req_path.lstrip("/")
                candidate = (ANCHOR_ROOT / rel).resolve()
                if candidate.is_file() and ANCHOR_ROOT in candidate.parents:
                    ctype = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
                    self._reply(200, ctype, candidate.read_bytes())
                    return
            self._reply(404, "text/plain; charset=utf-8", b"not found")

        def _reply(self, code: int, ctype: str, payload: bytes):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    preview_srv = ThreadingHTTPServer(("127.0.0.1", 0), _HermeticSetupPreviewHandler)
    preview_port = preview_srv.server_address[1]
    assert preview_port != 8777
    preview_thread = threading.Thread(target=preview_srv.serve_forever, daemon=True)
    preview_thread.start()
    try:
        loopback_out = tmp_path / "looks_loopback_setup"
        _run_look_gate(f"http://127.0.0.1:{preview_port}/setup?section=providers", loopback_out)

        # Negative dynamic check: when discovery fails / effective_model_id is None, JS must NOT forge data-provider-model
        monkeypatch.setattr(model_policy, "discover", _raise_missing)
        unavail_snap = service.snapshot(True)
        assert unavail_snap["active_routing"]["adversarial_reviewer"]["effective_model_id"] is None
        state_holder["snap"] = unavail_snap
        neg_out = tmp_path / "looks_loopback_setup_unavail"
        neg_out.mkdir(parents=True, exist_ok=True)
        neg_proc = subprocess.run(
            [
                sys.executable,
                str(FT_CLI),
                "look",
                f"http://127.0.0.1:{preview_port}/setup?section=providers",
                "--check",
                "[data-provider-model='claude-fable-5-2']",
                "--out",
                str(neg_out),
                "--json",
            ],
            cwd=str(ANCHOR_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
            shell=False,
        )
        neg_verdict = json.loads(neg_proc.stdout)
        for vp in neg_verdict.get("results", []):
            assert vp.get("checks", {}).get("[data-provider-model='claude-fable-5-2']", []) == []
    finally:
        preview_srv.shutdown()
        preview_srv.server_close()
        preview_thread.join(timeout=5)


def test_w1_trio_drivers_node_suite():
    node_exe = shutil.which("node")
    assert node_exe, "node executable is required for Trio driver suite"
    fable_test = TRIO_DRIVERS_TEST_DIR / "fable-5-2-policy.test.mjs"
    assert fable_test.is_file(), f"Missing {fable_test}"
    test_files = sorted(str(p) for p in TRIO_DRIVERS_TEST_DIR.glob("*.test.mjs"))
    assert str(fable_test) in test_files

    proc = subprocess.run(
        [node_exe, "--test", "--test-concurrency=4", *test_files],
        cwd=str(DEV_ROOT / "trio"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        shell=False,
    )
    combined = f"{proc.stdout}\n{proc.stderr}"
    assert proc.returncode == 0, f"Trio node --test failed ({proc.returncode}):\n{combined}"
    passed = _parse_node_pass_count(combined)
    assert passed > 0, f"Expected >0 passing Trio driver tests, got 0:\n{combined}"


def test_w1_gandalf_node_suite():
    node_exe = shutil.which("node")
    assert node_exe, "node executable is required for Gandalf suite"
    attest_test = GANDALF_DIR / "test" / "fable-5-2-attest.test.mjs"
    assert attest_test.is_file(), f"Missing {attest_test}"
    test_files = sorted(
        [*(str(p) for p in (GANDALF_DIR / "test").glob("*.test.mjs")), *(str(p) for p in (GANDALF_DIR / "test" / "mapreduce").glob("*.test.mjs"))]
    )
    assert str(attest_test) in test_files

    proc = subprocess.run(
        [node_exe, "--test", "--test-concurrency=1", *test_files],
        cwd=str(GANDALF_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        shell=False,
    )
    combined = f"{proc.stdout}\n{proc.stderr}"
    assert proc.returncode == 0, f"Gandalf node --test failed ({proc.returncode}):\n{combined}"
    passed = _parse_node_pass_count(combined)
    assert passed > 0, f"Expected >0 passing Gandalf tests, got 0:\n{combined}"


def test_w1_anvil_foundry_pytest_suite(tmp_path):
    assert ANVIL_TESTS_DIR.is_dir(), f"Missing {ANVIL_TESTS_DIR}"
    basetemp = tmp_path / "anvil_pytest_tmp"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-v",
            str(ANVIL_TESTS_DIR),
            f"--basetemp={basetemp}",
            "-p",
            "no:cacheprovider",
        ],
        cwd=str(ANVIL_TESTS_DIR.parent),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=240,
        shell=False,
    )
    combined = f"{proc.stdout}\n{proc.stderr}"
    assert proc.returncode == 0, f"Skill Foundry Anvil pytest failed ({proc.returncode}):\n{combined}"
    passed = _parse_pytest_pass_count(combined)
    assert passed > 0, f"Expected >0 passing Anvil tests, got 0:\n{combined}"
