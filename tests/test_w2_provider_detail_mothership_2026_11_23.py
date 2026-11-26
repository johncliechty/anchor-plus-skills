"""Wave 2 — Single-Provider Detail, Mothership Subscription Auto-Discovery & Usage Page."""
from __future__ import annotations

import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import build_opener

import pytest

import anchor_settings as settings
import distro
import paths
import provider_detail_view as pdv
import provider_native as native
import provider_secrets
import provider_settings as metadata
import provider_setup as setup
import route_table
import usage_index
from tests.test_provider_setup import authenticated, http_request, server, stack

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def detail_server(server, monkeypatch):
    origin, stk = server
    if route_table.match("GET", "/api/provider-setup/detail") is None:
        extra = [
            route_table._r("GET", "/api/provider-setup/detail", route_table.AUTH_TOKEN, handler="handle_provider_setup_get", migrated=True),
            route_table._r("POST", "/api/provider-setup/probe-mothership", route_table.AUTH_TOKEN, handler="handle_provider_setup_post", migrated=True),
            route_table._r("POST", "/api/provider-setup/adopt-mothership", route_table.AUTH_TOKEN, handler="handle_provider_setup_post", migrated=True),
            route_table._r("POST", "/api/provider-setup/billing-mode", route_table.AUTH_TOKEN, handler="handle_provider_setup_post", migrated=True),
        ]
        monkeypatch.setattr(route_table, "ROUTES", list(route_table.ROUTES) + extra)
    return origin, stk


def _concurrent_store_worker(data_dir_str: str, family: str, mode: str) -> None:
    os.environ["ANCHOR_DATA_DIR"] = data_dir_str
    for i in range(6):
        pdv._update_detail_store(family, {"billing_mode": mode, "iter": i})


def test_line_budgets_and_distro_zero_pii_and_stdlib_only():
    ps_js = (REPO_ROOT / "static" / "provider-setup.js").read_text(encoding="utf-8")
    pdv_py = (REPO_ROOT / "provider_detail_view.py").read_text(encoding="utf-8")
    pdp_js = (REPO_ROOT / "static" / "provider-detail-page.js").read_text(encoding="utf-8")
    assert len(ps_js.splitlines()) <= 1497
    assert len(pdv_py.splitlines()) < 340
    assert len(pdp_js.splitlines()) < 360
    assert native.COMMAND_TIMEOUT == 15

    touched = [
        "provider_detail_view.py",
        "provider_native.py",
        "static/provider-detail-page.js",
        "provider_setup.py",
        "static/provider-setup.html",
        "static/provider-setup.js",
        "static/provider-controls.js",
    ]
    for rel in touched:
        txt = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert list(distro._scan_text(rel, txt)) == [], f"PII scan hit in {rel}"
    tp_hits = distro.scan_third_party_imports(
        [(r, REPO_ROOT / r) for r in ("provider_detail_view.py", "provider_native.py", "provider_setup.py")],
        REPO_ROOT,
    )
    assert tp_hits == []


def test_routing_contract_usage_banner_vs_provider_tiles_and_stage2_cards():
    controls_js = (REPO_ROOT / "static" / "provider-controls.js").read_text(encoding="utf-8")
    setup_js = (REPO_ROOT / "static" / "provider-setup.js").read_text(encoding="utf-8")
    setup_html = (REPO_ROOT / "static" / "provider-setup.html").read_text(encoding="utf-8")
    detail_js = (REPO_ROOT / "static" / "provider-detail-page.js").read_text(encoding="utf-8")

    # 1. .cave-usage-banner stays routed to Setup Stage 2 (section=providers)
    assert "banner.onclick = e => open(e.currentTarget,{section:'providers'});" in controls_js
    # 2. .cave-account-summary routes to Single-Provider Detail (section=provider-detail&family=<fam>)
    assert "row.onclick=e=>open(e.currentTarget,{section:'provider-detail',family:connection.family});" in controls_js
    # 3. Stage 2 matrix cards delegate to window.AnchorProviderDetail.open(key, section)
    assert "window.AnchorProviderDetail.open(key,section)" in setup_js
    assert 'id="setup-section-provider-detail"' in setup_html
    assert 'id="provider-detail-root"' in setup_html
    assert '/static/provider-detail-page.js' in setup_html
    assert '← Setup Stage 2 (All Providers)' in detail_js


def test_get_detail_spawns_zero_subprocesses_redacts_home_and_hits_warm_memo(detail_server, monkeypatch):
    origin, (service, _, data, home) = detail_server
    opener = authenticated(origin)

    # Seed usage_index rows to verify 7d/30d attribution + top cockpits
    usage_index.append_rows("quantum-paper", [
        {"key": "t1", "cli": "claude", "tokens": 400_000, "recorded_at": pdv.datetime.now(pdv.timezone.utc).isoformat()},
    ])
    usage_index.append_rows("cave-steward", [
        {"key": "t2", "cli": "claude", "tokens": 600_000, "recorded_at": pdv.datetime.now(pdv.timezone.utc).isoformat()},
    ])

    fake_user_exe = str(home / ".local" / "bin" / "claude.exe")
    monkeypatch.setattr(native, "executable", lambda fam: fake_user_exe if fam == "claude" else f"/usr/local/bin/{fam}")
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: pytest.fail("GET spawned subprocess.Popen!"))
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: pytest.fail("GET spawned subprocess.run!"))

    code, raw = http_request(opener, origin, "/api/provider-setup/detail?family=claude")
    assert code == 200
    doc = json.loads(raw)
    assert doc["ok"] is True and doc["family"] == "claude"
    assert doc["subscription"]["cli"]["path"] == "~/.local/bin/claude.exe"
    assert str(home) not in raw
    assert doc["usage"]["window_7d"]["tokens"] == 1_000_000
    assert doc["usage"]["top_cockpits"][0]["project_id"] == "cave-steward"
    assert doc["usage"]["top_cockpits"][0]["share_pct"] == 60

    # Repeat invocation warm check (< 15 ms, 0 Popen)
    t0 = time.perf_counter()
    for _ in range(5):
        c2, r2 = http_request(opener, origin, "/api/provider-setup/detail?family=claude")
        assert c2 == 200
    avg_ms = ((time.perf_counter() - t0) / 5.0) * 1000.0
    assert avg_ms < 50.0  # loopback HTTP + <1ms server memo

    # Pure in-process warm memo check strictly < 15 ms
    t1 = time.perf_counter()
    out_mem, code_mem = pdv.get_provider_detail(service, "claude")
    assert code_mem == 200 and out_mem["family"] == "claude"
    assert (time.perf_counter() - t1) * 1000.0 < 15.0

    # Invalid family -> HTTP 400
    bad_code, _ = http_request(opener, origin, "/api/provider-setup/detail?family=not-a-provider")
    assert bad_code == 400


def test_post_auth_csrf_and_32kb_body_cap_refusal(detail_server):
    origin, _ = detail_server
    # Unauthenticated -> 401
    for path in ("/api/provider-setup/detail?family=claude", "/api/provider-setup/probe-mothership",
                 "/api/provider-setup/adopt-mothership", "/api/provider-setup/billing-mode"):
        method_body = None if "detail" in path else {"family": "claude"}
        st, _ = http_request(build_opener(), origin, path, method_body)
        assert st in (401, 403)

    opener = authenticated(origin)
    # Cross-origin CSRF -> 403
    csrf_code, _ = http_request(
        opener, origin, "/api/provider-setup/probe-mothership", {"family": "claude"},
        headers={"Origin": "https://evil.invalid", "Sec-Fetch-Site": "cross-site"},
    )
    assert csrf_code == 403

    # > 32 KB payload -> 413 refusal
    huge = {"family": "claude", "padding": "x" * (pdv.MAX_POST_BODY_BYTES + 512)}
    cap_code, cap_raw = http_request(opener, origin, "/api/provider-setup/probe-mothership", huge)
    assert cap_code == 413
    assert json.loads(cap_raw)["status_kind"] == "payload-too-large"


def test_mothership_probe_timeout_forwarding_adopt_and_gemini_honest_unknown(detail_server, monkeypatch):
    origin, (service, _, data, home) = detail_server
    opener = authenticated(origin)

    # Plant sentinel inside private_homes() to prove zero raw token-file reads
    priv_cred = home / ".claude" / ".credentials.json"
    priv_cred.parent.mkdir(parents=True, exist_ok=True)
    sentinel = "raw-private-credential-never-read-sentinel"
    priv_cred.write_text(sentinel, encoding="utf-8")

    observed_timeouts = []
    real_backend = native.NativeProviders()
    monkeypatch.setattr(service, "native", real_backend)
    monkeypatch.setattr(native, "executable", lambda fam: f"{fam}-fixture")

    def fake_run_command(argv, env, cancel=None, timeout=None, progress=None):
        observed_timeouts.append((argv, timeout))
        if argv[1:] == ["auth", "status"]:
            return 0, json.dumps({
                "loggedIn": True,
                "authMethod": "claude.ai",
                "email": "alice@example.org",
                "accessToken": sentinel,
            })
        pytest.fail(f"Unexpected command {argv}")

    monkeypatch.setattr(native, "run_command", fake_run_command)

    # 1. Probe Claude Mothership -> timeout=2.0 forwarded, masked_identity only
    p_code, p_raw = http_request(opener, origin, "/api/provider-setup/probe-mothership", {"family": "claude"})
    assert p_code == 200
    p_doc = json.loads(p_raw)
    assert observed_timeouts == [(["claude-fixture", "auth", "status"], 2.0)]
    assert p_doc["subscription"]["auth"] == "signed_in"
    assert p_doc["subscription"]["account_identity"] == "a***@e***.o***"
    assert "alice@example.org" not in p_raw and sentinel not in p_raw

    # 2. 1-Click Adopt Mothership Subscription -> persists claude-default in settings
    a_code, a_raw = http_request(opener, origin, "/api/provider-setup/adopt-mothership", {"family": "claude"})
    assert a_code == 200
    a_doc = json.loads(a_raw)
    assert a_doc["subscription"]["mothership_scan"]["adopted"] is True
    assert settings.load_settings()["provider_preferences"]["accounts"]["claude"] == "claude-default"
    assert sentinel not in (data / ".anchor" / pdv.STATE_FILENAME).read_text(encoding="utf-8")

    # 3. Gemini via agy -> honest passive auth unknown, zero subprocess turns spawned
    observed_timeouts.clear()
    g_code, g_raw = http_request(opener, origin, "/api/provider-setup/probe-mothership", {"family": "gemini"})
    assert g_code == 200
    g_doc = json.loads(g_raw)
    assert g_doc["subscription"]["auth"] == "unknown"
    assert g_doc["passive_auth_unknown"] is True
    assert observed_timeouts == []


def test_hung_cli_probe_terminates_within_bound_as_504(stack, monkeypatch):
    service, _, _, _ = stack
    real_backend = native.NativeProviders()
    monkeypatch.setattr(service, "native", real_backend)
    monkeypatch.setattr(native, "executable", lambda fam: sys.executable)

    orig_run = native.run_command
    def sleepy_run(argv, env, cancel=None, timeout=None, progress=None):
        return orig_run([sys.executable, "-c", "import time; time.sleep(10)"], env, cancel=cancel, timeout=0.25)

    monkeypatch.setattr(native, "run_command", sleepy_run)
    t0 = time.monotonic()
    out, code = pdv.handle_detail_post(service, "/api/provider-setup/probe-mothership", {"family": "claude"})
    elapsed = time.monotonic() - t0
    assert code == 504
    assert out["status_kind"] == "dependency-slow-or-killed"
    assert elapsed <= 2.5


def test_vault_masked_only_invariant_and_billing_mode_toggle(detail_server, monkeypatch):
    origin, _ = detail_server
    opener = authenticated(origin)
    vault_store = {}
    raw_secret = "vault-private-key-9f4a"
    monkeypatch.setattr(provider_secrets, "available", lambda: True)
    monkeypatch.setattr(provider_secrets, "put", lambda k, v: vault_store.__setitem__(k, v))
    monkeypatch.setattr(provider_secrets, "get", lambda k: vault_store.get(k))
    monkeypatch.setattr(setup, "validate_api", lambda fam, key: None)

    # Selecting api_key mode before storing key -> 400
    c0, _ = http_request(opener, origin, "/api/provider-setup/billing-mode", {"family": "chatgpt", "billing_mode": "api_key"})
    assert c0 == 400

    # Save key + switch to api_key mode -> 200, masked tail only, zero raw key in response or disk
    c1, r1 = http_request(
        opener, origin, "/api/provider-setup/billing-mode",
        {"family": "chatgpt", "billing_mode": "api_key", "api_key": raw_secret},
    )
    assert c1 == 200
    d1 = json.loads(r1)
    assert d1["billing_mode"] == "api_key"
    assert d1["vault"]["has_api_key"] is True
    assert d1["vault"]["masked_key"] == "••••••9f4a"
    assert raw_secret not in r1
    for p in paths.data_dir().rglob("*.json"):
        assert raw_secret not in p.read_text(encoding="utf-8")

    # Switch back to subscription mode -> 200
    c2, r2 = http_request(opener, origin, "/api/provider-setup/billing-mode", {"family": "chatgpt", "billing_mode": "subscription"})
    assert c2 == 200 and json.loads(r2)["billing_mode"] == "subscription"


def test_five_row_failure_state_table_separates_unknown_from_empty(stack, monkeypatch):
    service, backend, data, _ = stack

    # 1. empty-but-valid -> 200 EMPTY (unknown_state=False)
    raw_s = json.loads(settings.settings_path().read_text(encoding="utf-8"))
    raw_s["provider_connections"] = []
    settings.settings_path().write_text(json.dumps(raw_s), encoding="utf-8")
    out_empty, code_empty = pdv.get_provider_detail(service, "claude")
    assert code_empty == 200 and out_empty["status_kind"] == "empty-but-valid"
    assert out_empty["badge"] == "EMPTY" and out_empty["unknown_state"] is False

    # 2. backing-store-unreadable -> 500 UNKNOWN (unknown_state=True)
    settings.settings_path().write_text("{corrupt-json", encoding="utf-8")
    out_unk, code_unk = pdv.get_provider_detail(service, "claude")
    assert code_unk == 500 and out_unk["status_kind"] == "backing-store-unreadable"
    assert out_unk["badge"] == "UNKNOWN" and out_unk["unknown_state"] is True

    # Restore valid settings for dependency POST rows
    settings.settings_path().unlink()
    settings.save_settings(default_cli="claude", coding_family="claude", review_family="gemini", steward_type="aladdin")

    # 3. dependency-missing -> 503
    monkeypatch.setattr(backend, "observe", lambda c, **kw: (_ for _ in ()).throw(native.NativeError("unavailable")))
    o_miss, c_miss = pdv.handle_detail_post(service, "/api/provider-setup/probe-mothership", {"family": "claude"})
    assert c_miss == 503 and o_miss["status_kind"] == "dependency-missing" and o_miss["unknown_state"] is False

    # 4. dependency-slow-or-killed -> 504
    monkeypatch.setattr(backend, "observe", lambda c, **kw: (_ for _ in ()).throw(native.NativeError("timeout")))
    o_slow, c_slow = pdv.handle_detail_post(service, "/api/provider-setup/probe-mothership", {"family": "claude"})
    assert c_slow == 504 and o_slow["status_kind"] == "dependency-slow-or-killed" and o_slow["unknown_state"] is False

    # 5. dependency-returns-garbage -> 502
    monkeypatch.setattr(backend, "observe", lambda c, **kw: (_ for _ in ()).throw(native.NativeError("error")))
    o_garb, c_garb = pdv.handle_detail_post(service, "/api/provider-setup/probe-mothership", {"family": "claude"})
    assert c_garb == 502 and o_garb["status_kind"] == "dependency-returns-garbage" and o_garb["unknown_state"] is False


def test_containment_escape_attempts_and_multiprocess_concurrency(stack, tmp_path):
    _, _, data, _ = stack
    for bad in ("../escape", "..\\escape", "/etc/passwd", "C:\\Windows\\win.ini", "claude\x00", "claude/../../x"):
        with pytest.raises(ValueError):
            pdv.validate_family(bad)
        with pytest.raises(ValueError):
            pdv.resolve_contained_anchor_file(bad, base_dir=data)

    # Symlink escape inside .anchor -> refused
    anchor_dir = data / ".anchor"
    anchor_dir.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    link_file = anchor_dir / "linked.json"
    try:
        link_file.symlink_to(outside)
        symlink_created = True
    except OSError:
        symlink_created = False
    if symlink_created:
        with pytest.raises(ValueError, match="symlink|escape"):
            pdv.resolve_contained_anchor_file("linked.json", base_dir=data)

    # Two real processes concurrently updating provider_detail_state.json
    ctx = multiprocessing.get_context("spawn")
    p1 = ctx.Process(target=_concurrent_store_worker, args=(str(data), "claude", "subscription"))
    p2 = ctx.Process(target=_concurrent_store_worker, args=(str(data), "chatgpt", "api_key"))
    p1.start(); p2.start()
    p1.join(15); p2.join(15)
    assert p1.exitcode == 0 and p2.exitcode == 0
    doc = pdv._read_detail_store()
    assert doc["families"]["claude"]["billing_mode"] == "subscription"
    assert doc["families"]["chatgpt"]["billing_mode"] == "api_key"
    assert doc["families"]["claude"]["iter"] == 5 and doc["families"]["chatgpt"]["iter"] == 5


def test_playwright_provider_detail_navigation_and_back_button(detail_server):
    from playwright.sync_api import sync_playwright
    origin, _ = detail_server
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        try:
            page.request.post(origin + "/api/auth/login", data=json.dumps({"token": os.environ["ANCHOR_TOKEN"]}), headers={"Content-Type": "application/json"})
            page.goto(origin + "/setup?section=providers", wait_until="networkidle")
            card = page.locator("#wave2-provider-matrix .wave2-matrix-card").first
            card.wait_for(state="visible", timeout=5000)
            card.click()
            page.locator("#setup-section-provider-detail #btnBackStage2").wait_for(state="visible", timeout=5000)
            assert page.locator("#setup-section-provider-detail").is_visible()
            assert "section=provider-detail" in page.url
            page.locator("#btnAdoptMothership").click()
            page.locator("#pd-toast-notice").wait_for(state="visible", timeout=5000)
            page.locator("#btnBackStage2").click()
            assert page.locator("#setup-section-providers").is_visible()
            assert "section=providers" in page.url
        finally:
            context.close()
            browser.close()
