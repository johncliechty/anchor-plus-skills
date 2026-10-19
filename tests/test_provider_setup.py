"""Provider Setup's real account, authentication and execution boundaries.

Native commands are substituted at their documented interfaces. HTTP tests use
the application's ordinary login/cookie flow, never privileged test headers.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import http.cookiejar
import builtins
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, build_opener, HTTPCookieProcessor

import pytest

import anchor_settings as settings
import model_policy
import provider_native as native
import provider_settings as metadata
import provider_setup as setup

AUTH = '-'.join(('provider', 'disposable', 'test', 'token'))


class NativeFixture:
    def __init__(self):
        self.reads = []
        self.failed = {}
        self.signed = set()
        self.login_started = threading.Event()
        self.login_stopped = threading.Event()
        self.timeout = False

    def capabilities(self, family):
        return {"installed": family != "gemini", "state": "available" if family != "gemini" else "unavailable",
                "version": "1.2.3", "isolated": family in ("claude", "chatgpt"),
                "login": "device" if family == "chatgpt" else "browser" if family == "claude" else None}

    def observe(self, connection):
        self.reads.append((connection["id"], native.account_env(connection)))
        if connection["id"] in self.failed:
            raise native.NativeError(self.failed[connection["id"]])
        signed = connection["native_default"] or connection["id"] in self.signed
        return {"auth": "signed_in" if signed else "signed_out", "test": "passed" if signed else "not_tested",
                "auth_source": "Fixture native account/read",
                "allowance": {"state": "fresh", "source": "Fixture native rateLimits/read",
                              "windows": [{"label": "5 hour", "remaining_percent": 75 if connection["native_default"] else 12,
                                           "resets_at": time.time() + 3600, "window_minutes": 300}] if signed else []},
                "provider_usage": {"state": "unsupported", "source": "Fixture native usage/read", "tokens": None}}

    def login(self, connection, cancel, progress):
        self.login_started.set()
        try:
            progress({"state": "awaiting_browser", "url": "https://auth.openai.com/codex/device", "user_code": "DEMO-1234",
                      "message": "Native device login on host"})
            if self.timeout:
                raise native.NativeError("timeout")
            assert cancel.wait(3), "Test left an uncancelled native login"
            raise native.NativeError("cancelled")
        finally:
            self.login_stopped.set()


@pytest.fixture
def stack(tmp_path, monkeypatch):
    data, home = tmp_path / "data", tmp_path / "home"
    data.mkdir(); home.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("HOME", str(home)); monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(settings, "mirror_path", lambda: home / "model_prefs.json")
    monkeypatch.delenv("CODEX_HOME", raising=False); monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setenv("ANCHOR_TOKEN", AUTH)
    settings.save_settings(default_cli="claude", coding_family="claude", review_family="claude", steward_type="aladdin")
    backend = NativeFixture()
    service = setup.ProviderService(backend)
    monkeypatch.setattr(setup, "SERVICE", service)
    monkeypatch.setattr(native, "executable", lambda family: "native-fixture" if family != "gemini" else None)
    rows = [{"model": "frontier", "efforts": ["high", "ultra"], "rank": 0, "upgrade": None, "evidence": "provider_moving_alias"},
            {"model": "balanced", "efforts": ["low", "high"], "rank": 1, "upgrade": None, "evidence": "provider_catalog_order"}]
    monkeypatch.setattr(model_policy, "discover", lambda family, **kwargs: (deepcopy(rows), "native-fixture"))
    return service, backend, data, home


def add(service, family="chatgpt", name="Work", mode="subscription"):
    result = service.add({"family": family, "name": name, "mode": mode,
                          "expected_revision": settings.load_settings()["settings_revision"]})
    return metadata.find_connection(settings.load_settings(), result["connection_id"])


def row(snapshot, identity):
    return next(c for c in snapshot["connections"] if c["id"] == identity)


def test_snapshot_is_credential_free_and_does_not_enroll_or_write(stack, monkeypatch):
    service, backend, data, home = stack
    sentinel = "private-native-credential-sentinel"
    auth = home / ".codex" / "auth.json"
    auth.parent.mkdir(); auth.write_text(sentinel)
    before = settings.settings_path().read_bytes()
    monkeypatch.setenv("OPENAI_API_KEY", sentinel)
    snapshot = service.snapshot(True)
    assert sentinel not in json.dumps(snapshot)
    assert auth.read_text() == sentinel
    assert settings.settings_path().read_bytes() == before
    assert row(snapshot, "chatgpt-default")["auth"] == "signed_in"
    assert "OPENAI_API_KEY" not in backend.reads[0][1]
    assert list(data.glob("**/auth.json")) == []


def test_native_codex_response_redacts_unknown_and_token_fields(stack, monkeypatch):
    secret = '-'.join(('credential', 'redaction', 'sentinel'))
    methods = []
    class Client:
        def __init__(self, connection): pass
        def rpc(self, method, params=None):
            methods.append((method, params))
            if method == "account/read":
                return {"account": {"type": "chatgpt", "email": secret, "accessToken": secret}, "secret": secret}
            if method == "account/rateLimits/read":
                return {"rateLimits": {"primary": {"usedPercent": 23, "windowDurationMins": 300, "resetsAt": 1900000000}, "token": secret}}
            return {"summary": {"lifetimeTokens": 99, "secret": secret}, "dailyUsageBuckets": [{"secret": secret}]}
        def close(self): pass
    monkeypatch.setattr(native, "CodexAccount", Client)
    out = native.NativeProviders().observe(metadata.default_connections()[1])
    assert secret not in json.dumps(out)
    assert out["allowance"]["windows"][0]["remaining_percent"] == 77
    assert methods[0] == ("account/read", {"refreshToken": False})
    assert {m for m, _ in methods} == {"account/read", "account/rateLimits/read", "account/usage/read"}


@pytest.mark.parametrize("bad", [True, -1, 101, float("nan"), float("inf"), "75"])
def test_invalid_native_percent_never_becomes_capacity(bad):
    assert native.allowance_windows({"rateLimits": {"primary": {"usedPercent": bad}}}) == []


def test_codex_api_login_is_not_a_subscription(stack, monkeypatch):
    calls=[]
    class Client:
        def __init__(self, connection): pass
        def rpc(self, method, params):
            calls.append(method)
            return {"account": {"type": "apiKey", "apiKey": '-'.join(('redacted','test','sentinel'))}}
        def close(self): pass
    monkeypatch.setattr(native, "CodexAccount", Client)
    out = native.NativeProviders().observe(metadata.default_connections()[1])
    assert out["auth"] == "different_billing_mode"
    assert out["allowance"]["windows"] == []
    assert calls == ["account/read"]
    assert "redacted-test-sentinel" not in json.dumps(out)


def test_isolated_accounts_do_not_copy_or_replace_default(stack):
    service, backend, _, home = stack
    default = home / ".codex"; default.mkdir(); (default / "auth.json").write_text("existing-native-sign-in")
    one, two = add(service), add(service, name="Other subscription")
    assert one["id"] != two["id"]
    assert native.account_home(one) != native.account_home(two)
    assert native.account_home(one) != default
    assert not native.account_home(one).exists()
    assert (default / "auth.json").read_text() == "existing-native-sign-in"
    backend.signed.add(one["id"])
    service.refresh(one)
    actual = backend.reads[-1][1]
    assert actual["CODEX_HOME"] == str(native.account_home(one))
    assert actual["ANCHOR_PROVIDER_CONNECTION"] == one["id"]
    assert not row(service.snapshot(), two["id"])["execution"]["ready"]


def test_unverified_isolation_is_refused_and_default_login_retained(stack):
    service, _, _, _ = stack
    with pytest.raises(ValueError, match="isolated"):
        add(service, family="grok")
    with pytest.raises(ValueError, match="existing default"):
        service.start_login("chatgpt-default")
    assert len(settings.load_settings()["provider_connections"]) == 4


def test_login_cancel_retry_is_account_scoped_and_ephemeral(stack):
    service, backend, _, _ = stack
    connection = add(service)
    attempt = service.start_login(connection["id"])
    assert backend.login_started.wait(2)
    service.login_status(attempt["id"], cancel=True)
    assert backend.login_stopped.wait(2)
    thread = service.logins[attempt["id"]]["thread"]; thread.join(2)
    status = service.login_status(attempt["id"])
    assert status["state"] == "cancelled"
    assert "url" not in status and "user_code" not in status
    assert "DEMO-1234" not in json.dumps(service.snapshot())
    backend.timeout = True
    retry = service.start_login(connection["id"])
    service.logins[retry["id"]]["thread"].join(2)
    assert service.login_status(retry["id"])["state"] == "failed"
    assert native.account_home(connection).is_relative_to(setup.paths.data_dir())


def test_native_hidden_process_timeout_and_cancel_terminate_only_owned_child(stack):
    _, _, _, _ = stack
    env=dict(os.environ)
    child=native.HiddenProcess([sys.executable, "-c", "import time; time.sleep(5)"], env, timeout=.15)
    try:
        with pytest.raises(native.NativeError) as caught:
            child.next()
        assert caught.value.state == "timeout"
    finally:
        child.close()
    assert child.proc.poll() is not None
    child=native.HiddenProcess([sys.executable, "-c", "import time; time.sleep(5)"], env)
    cancelled=threading.Event(); cancelled.set()
    try:
        with pytest.raises(native.NativeError) as caught:
            child.next(cancelled)
        assert caught.value.state == "cancelled"
    finally:
        child.close()
    assert child.proc.poll() is not None


def test_native_stdio_status_is_not_corrupted_by_stderr(stack):
    code, result = native.run_command([sys.executable, "-c", "import sys; print('{\"loggedIn\":true}'); print('sensitive diagnostic',file=sys.stderr)"], dict(os.environ))
    assert code == 0 and json.loads(result)["loggedIn"]
    assert "sensitive diagnostic" not in result


def test_allowance_and_usage_remain_separately_attributed(stack):
    service, backend, _, _ = stack
    connection = add(service)
    backend.signed.add(connection["id"])
    service.snapshot(True)
    default = row(service.snapshot(), "chatgpt-default")
    other = row(service.snapshot(), connection["id"])
    assert default["allowance"]["windows"][0]["remaining_percent"] == 75
    assert other["allowance"]["windows"][0]["remaining_percent"] == 12
    assert other["capacity"] == "near_limit" and other["warning"]
    assert default["capacity"] == "usable"
    assert other["api_spend"]["amount"] is None
    assert other["subscription_price"]["amount"] is None
    assert other["anchor_observed"]["tokens"] is None


def test_stale_failed_refresh_retains_last_known_time_and_unsupported_is_explicit(stack):
    service, backend, _, _ = stack
    service.snapshot(True)
    before=row(service.snapshot(), "chatgpt-default")
    backend.failed["chatgpt-default"]="expired"
    service.refresh(metadata.default_connections()[1])
    after=row(service.snapshot(), "chatgpt-default")
    assert after["auth"] == "expired" and after["test"] == "failed"
    assert after["allowance"]["state"] == "stale"
    assert after["allowance"]["observed_at"] == before["allowance"]["observed_at"]
    assert after["allowance"]["windows"] == before["allowance"]["windows"]
    assert after["capacity"] == "unknown" and not after["execution"]["ready"]
    assert row(service.snapshot(), "gemini-default")["auth"] == "unavailable"
    assert row(service.snapshot(), "claude-default")["allowance"]["state"] == "unsupported"


def test_old_and_reset_reports_are_visibly_stale(stack):
    service, _, _, _ = stack
    service.snapshot(True)
    key=service._key("chatgpt-default")
    service.observations[key]["allowance"]["observed_at"]=(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()
    assert row(service.snapshot(), "chatgpt-default")["allowance"]["state"] == "stale"
    service.observations[key]["allowance"]["observed_at"]=setup.stamp()
    service.observations[key]["allowance"]["windows"][0]["resets_at"]=time.time()-1
    assert row(service.snapshot(), "chatgpt-default")["capacity"] == "unknown"


def test_claude_legacy_meter_is_never_borrowed(stack, tmp_path):
    import usage_capacity
    jobs=tmp_path / "jobs";jobs.mkdir()
    event={"type":"rate_limit_event","rate_limit_info":{"unifiedWindows":{"five_hour":{"utilization":.8,"resetsAt":time.time()+3600}}}}
    (jobs/"one.log").write_text(json.dumps(event))
    assert usage_capacity.latest_limit_signal(directory=str(jobs),connection_id="claude-default") is None
    (jobs/"one.json").write_text(json.dumps({"provider_connection":{"id":"a"*32}}))
    assert usage_capacity.latest_limit_signal(directory=str(jobs),connection_id="claude-default") is None
    signal=usage_capacity.latest_limit_signal(directory=str(jobs),connection_id="a"*32)
    assert signal["five_hour"]["utilization"] == .8


def test_observed_ledger_rows_are_account_qualified(stack):
    import usage_capture
    usage_capture.ingest_usage("fixture-session", "row-1", source=usage_capture.SOURCE_STEWARD_TURN,native_id="1",tokens=123,
                               cli="chatgpt",provider_connection_id="chatgpt-default")
    usage_capture.ingest_usage("fixture-session", "legacy-row", source=usage_capture.SOURCE_STEWARD_TURN,native_id="2",tokens=999,cli="chatgpt")
    assert setup.observed_tokens("chatgpt-default")["tokens"] == 123
    assert setup.observed_tokens("a"*32)["tokens"] is None


def test_account_usage_reads_each_ledger_once_and_reuses_unchanged_files(stack, monkeypatch, tmp_path):
    service, _, data, _ = stack
    account = add(service)
    ledger = data / ".anchor" / "usage_ledger"
    ledger.mkdir(parents=True)
    count = 257
    when = "2026-10-05T12:00:00+00:00"
    def write(path, tokens):
        path.write_text(json.dumps({"entries": {
            "default": {"provider_connection_id": "chatgpt-default", "tokens": tokens, "recorded_at": when},
            "named": {"provider_connection_id": account["id"], "tokens": 3, "recorded_at": when},
            "zero": {"provider_connection_id": "claude-default", "tokens": 0},
            "legacy": {"tokens": 999},
            "invalid": {"provider_connection_id": account["id"], "tokens": True},
            "malformed": None,
        }}), encoding="utf-8")
    for i in range(count):
        suffix = ".JSON" if os.name == "nt" and i == count - 1 else ".json"
        write(ledger / f"{i}{suffix}", 2)
    original_open, reads = builtins.open, []
    def tracked_open(path, *args, **kwargs):
        if Path(path).parent == ledger:
            reads.append(Path(path).name)
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(builtins, "open", tracked_open)
    first = service.snapshot()
    assert len(reads) == count and len(set(reads)) == count
    assert row(first, "chatgpt-default")["anchor_observed"]["tokens"] == count * 2
    assert row(first, account["id"])["anchor_observed"]["tokens"] == count * 3
    assert row(first, "claude-default")["anchor_observed"]["tokens"] == 0
    assert row(first, "grok-default")["anchor_observed"]["state"] == "unknown"
    assert service.snapshot() == first and len(reads) == count
    # Match the ledger writer's atomic replacement, including a same-size update.
    replacement = ledger / "replace.tmp"
    write(replacement, 7)
    os.replace(replacement, ledger / "0.json")
    second = service.snapshot()
    assert len(reads) == count + 1
    assert row(second, "chatgpt-default")["anchor_observed"]["tokens"] == count * 2 + 5
    write(ledger / "new.json", 11)
    (ledger / "1.json").unlink()
    third = service.snapshot()
    assert len(reads) == count + 2
    assert row(third, "chatgpt-default")["anchor_observed"]["tokens"] == count * 2 + 14
    assert row(third, account["id"])["anchor_observed"]["tokens"] == count * 3
    # Returned rows cannot mutate the cache, and another data root cannot borrow it.
    row(third, account["id"])["anchor_observed"]["tokens"] = -1
    assert setup.observed_tokens(account["id"])["tokens"] == count * 3
    other = tmp_path / "other" / ".anchor" / "usage_ledger"
    other.mkdir(parents=True)
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(other.parent.parent))
    assert setup.observed_tokens(account["id"])["tokens"] is None
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    assert setup.observed_tokens(account["id"])["tokens"] == count * 3


def test_account_usage_failed_read_retains_prior_totals_and_retries(stack, monkeypatch):
    service, _, data, _ = stack
    ledger = data / ".anchor" / "usage_ledger"
    ledger.mkdir(parents=True)
    path = ledger / "one.json"
    doc = {"entries": {"one": {"provider_connection_id": "chatgpt-default", "tokens": 123,
                              "recorded_at": "2026-10-05T12:00:00+00:00"}}}
    path.write_text(json.dumps(doc), encoding="utf-8")
    before = setup.observed_tokens("chatgpt-default")
    path.write_text("invalid", encoding="utf-8")
    failed = setup.observed_tokens("chatgpt-default")
    assert failed == {**before, "state": "stale"}
    original_scandir = os.scandir
    def unavailable(root):
        if str(root) == str(ledger):
            raise PermissionError()
        return original_scandir(root)
    monkeypatch.setattr(os, "scandir", unavailable)
    assert setup.observed_tokens("chatgpt-default") == failed
    monkeypatch.setattr(os, "scandir", original_scandir)
    doc["entries"]["one"]["tokens"] = 456
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert setup.observed_tokens("chatgpt-default") == {**before, "tokens": 456}


def test_ledger_io_does_not_hold_native_observation_lock(stack, monkeypatch):
    service, _, data, _ = stack
    ledger = data / ".anchor" / "usage_ledger"
    ledger.mkdir(parents=True)
    (ledger / "one.json").write_text('{"entries":{}}', encoding="utf-8")
    entered, release, completed = threading.Event(), threading.Event(), threading.Event()
    original_open = builtins.open
    def slow_open(path, *args, **kwargs):
        if Path(path).parent == ledger:
            entered.set()
            assert release.wait(5)
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(builtins, "open", slow_open)
    results = []
    def read():
        try:
            results.append(service.snapshot())
        finally:
            completed.set()
    worker = threading.Thread(target=read)
    worker.start()
    try:
        assert entered.wait(2)
        acquired = service.lock.acquire(timeout=1)
        if acquired:
            service.lock.release()
        assert acquired, "Cached ledger I/O blocked native state publication"
    finally:
        release.set(); worker.join(5)
    assert completed.is_set() and not worker.is_alive() and results[0]["ok"]


def test_apply_is_explicit_and_does_not_change_global_policy_or_live_engine(stack, monkeypatch, tmp_path):
    service, backend, _, _=stack
    from steward_cockpit import steward_engine
    monkeypatch.setattr(steward_engine,"STATE_FILE",tmp_path/"engines.json")
    target=tmp_path/"conversation";target.mkdir()
    # The native source existed before this settings revision.
    steward_engine._update_state(str(target), {"cli":"claude","session_id":"source-native-session","model_policy":None})
    engine=steward_engine.Engine(str(target), fake=True)
    original=(engine.cli,engine.session_id,deepcopy(engine.provider_connection))
    one=add(service)
    backend.signed.add(one["id"]);service.snapshot(True)
    prefs=deepcopy(service.snapshot()["preferences"])
    prefs["family"]="chatgpt";prefs["accounts"]["chatgpt"]=one["id"]
    prefs["quality"]["chatgpt"]={"model":"balanced","effort":"high"}
    before=settings.load_settings()
    result=service.apply({"preferences":prefs,"expected_revision":before["settings_revision"]})
    assert result["preferences"] == prefs
    after=settings.load_settings()
    for key in ("default_cli","coding_family","review_family","model_policy","steward_type"):
        assert after[key] == before[key]
    assert (engine.cli,engine.session_id,engine.provider_connection) == original
    assert engine._desired_policy()[1] == "claude"
    new_target=tmp_path/"new-conversation";new_target.mkdir()
    new_engine=steward_engine.Engine(str(new_target),fake=True)
    assert new_engine.provider_connection["id"] == one["id"]
    assert new_engine._desired_policy()[1] == "chatgpt"
    assert native.account_env(new_engine.provider_connection)["CODEX_HOME"] == str(native.account_home(one))


def test_apply_requires_fresh_advertised_model_and_current_settings_revision(stack):
    service, _, _, _=stack
    service.snapshot(True)
    before=settings.load_settings();prefs=deepcopy(before["provider_preferences"])
    prefs["family"]="claude";prefs["quality"]["claude"]={"model":"invented-model","effort":"ultra"}
    with pytest.raises(ValueError,match="advertised"):
        service.apply({"preferences":prefs,"expected_revision":before["settings_revision"]})
    prefs["quality"]={}
    service.apply({"preferences":prefs,"expected_revision":before["settings_revision"]})
    with pytest.raises(settings.SettingsInvalid):
        service.apply({"preferences":prefs,"expected_revision":before["settings_revision"]})


def test_isolated_chatgpt_is_refused_by_fixed_home_oneshot_adapter(stack, monkeypatch):
    service, _, _, _=stack
    connection=add(service)
    snapshot=settings.load_settings()
    snapshot["provider_preferences"]["accounts"]["chatgpt"]=connection["id"]
    assert setup.selected_for_launch(snapshot,"chatgpt")["id"] == connection["id"]
    with pytest.raises(ValueError,match="one-shot"):
        setup.selected_for_launch(snapshot,"chatgpt",surface="jobs")
    import codex_adapter
    monkeypatch.setattr(codex_adapter, "_windows_known_folder", lambda identity: stack[3])
    clean=codex_adapter.subscription_only_env({"CODEX_HOME":"untrusted", "OPENAI_API_KEY":"credential-test-sentinel"})
    assert clean["CODEX_HOME"] != "untrusted"
    assert "OPENAI_API_KEY" not in clean


def test_api_mode_cannot_change_subscription_or_claim_allowance(stack, monkeypatch):
    service, _, _, _=stack
    connection=add(service,mode="api")
    calls=[]
    monkeypatch.setattr(setup.provider_secrets,"get",lambda identity:"api-key-test-sentinel")
    monkeypatch.setattr(setup,"validate_api",lambda family,secret:calls.append((family,secret)))
    service.refresh(connection)
    account=row(service.snapshot(),connection["id"])
    assert account["auth"] == "api_key" and account["test"] == "passed"
    assert account["allowance"]["windows"] == [] and account["allowance"]["state"] == "unsupported"
    assert not account["execution"]["ready"] and account["api_spend"]["amount"] is None
    assert "api-key-test-sentinel" not in json.dumps(service.snapshot())
    prefs=deepcopy(settings.load_settings()["provider_preferences"]);prefs["accounts"]["chatgpt"]=connection["id"]
    with pytest.raises(ValueError,match="API execution"):
        metadata.validate_preferences(prefs,settings.load_settings()["provider_connections"])


@pytest.fixture
def server(stack):
    import anchor_gui
    http=anchor_gui.make_server("127.0.0.1",0)
    thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
    try:
        yield f"http://127.0.0.1:{http.server_address[1]}", stack
    finally:
        http.shutdown();http.server_close();thread.join(3)
        assert not thread.is_alive()


def http_request(opener, origin, path, body=None, headers=None):
    req=Request(origin+path,data=json.dumps(body).encode() if body is not None else None,
                headers={"Content-Type":"application/json", **(headers or {})})
    try:
        with opener.open(req,timeout=10) as response:
            return response.status,response.read().decode()
    except HTTPError as exc:
        return exc.code,exc.read().decode()


def authenticated(origin):
    cookies=http.cookiejar.CookieJar()
    opener=build_opener(HTTPCookieProcessor(cookies))
    code,_=http_request(opener,origin,"/api/auth/login",{"token":AUTH})
    assert code == 200 and any(cookie.has_nonstandard_attr("HttpOnly") for cookie in cookies)
    return opener


@pytest.mark.parametrize("failure", ["timeout", "unsupported"])
def test_cached_http_state_is_responsive_during_native_refresh(server, monkeypatch, failure):
    origin, (service, backend, _, _) = server
    before = row(service.snapshot(True), "chatgpt-default")
    entered, release = threading.Event(), threading.Event()
    def busy(connection):
        entered.set()
        assert release.wait(5)
        raise native.NativeError(failure)
    monkeypatch.setattr(backend, "observe", busy)
    connection = metadata.find_connection(settings.load_settings(), "chatgpt-default")
    worker = threading.Thread(target=service.refresh, args=(connection,))
    opener = authenticated(origin)
    worker.start()
    try:
        assert entered.wait(2)
        started = time.monotonic()
        with opener.open(origin + "/api/provider-setup", timeout=2) as response:
            assert response.status == 200
            cached = row(json.load(response), "chatgpt-default")
        assert time.monotonic() - started < 2
        assert worker.is_alive(), "Read did not overlap the native refresh"
        assert cached["auth"] == before["auth"]
        assert cached["allowance"] == before["allowance"]
        assert cached["catalog"] == before["catalog"]
    finally:
        release.set(); worker.join(5)
    assert not worker.is_alive()
    after = row(service.snapshot(), "chatgpt-default")
    assert after["auth"] == failure
    assert after["allowance"] == {**before["allowance"], "state": "stale",
                                 "attempted_at": after["attempted_at"], "error": failure}


@pytest.mark.parametrize("method,path",[("GET","/setup"),("GET","/api/provider-setup"),("GET","/api/provider-setup/login"),
    ("GET","/setup/install"),("POST","/api/provider-setup/initialize"),
    ("POST","/api/provider-setup/accounts"),("POST","/api/provider-setup/rename"),("POST","/api/provider-setup/apply"),
    ("POST","/api/provider-setup/login"),("POST","/api/provider-setup/cancel"),("POST","/api/provider-setup/api-key")])
def test_every_setup_route_requires_normal_authentication(server,method,path):
    origin,_=server
    status,_=http_request(build_opener(),origin,path,{} if method=="POST" else None)
    assert status in (401,403)
    import route_table
    route=route_table.match(method,path)
    assert route.auth == route_table.AUTH_TOKEN and route.migrated


def test_authenticated_http_page_reads_preferences_and_no_hidden_launches(server,monkeypatch):
    origin,(service,backend,_,_)=server
    import job_runner
    monkeypatch.setattr(job_runner,"launch",lambda *a,**kw:pytest.fail("Provider GET launched work"))
    opener=authenticated(origin)
    status,page=http_request(opener,origin,"/setup")
    assert status == 200 and 'id="setup-family"' in page
    status,body=http_request(opener,origin,"/api/provider-setup?refresh=1")
    assert status == 200 and json.loads(body)["host"]["runtime"] == "mother_ship"
    assert json.loads(body)["client_can_enter_api"] is True
    before=settings.settings_path().read_bytes()
    assert http_request(opener,origin,"/api/provider-setup")[0] == 200
    assert settings.settings_path().read_bytes() == before
    assert http_request(opener,origin,"/api/provider-setup/login",{"connection_id":"claude-default"})[0] == 400


def test_cross_origin_and_client_credential_actions_are_refused(server,monkeypatch):
    origin,_=server
    opener=authenticated(origin)
    status,_=http_request(opener,origin,"/api/provider-setup/accounts",{}, {"Sec-Fetch-Site":"cross-site","Origin":"https://elsewhere.invalid"})
    assert status == 403
    class Handler:
        headers={"Host":"host.example:8777","Origin":"https://host.example"}
        client_address=("100.64.0.10",1234)
        def _steward_same_origin(self):return True
        def _send_json(self,data,code=200):self.code,self.data=code,data
    handler=Handler()
    setup.handle_post(handler,"/api/provider-setup/api-key",{"api_key":'-'.join(('never','return','this','sentinel'))})
    assert handler.code == 403 and "never-return-this-sentinel" not in json.dumps(handler.data)
    # Reverse proxy loopback alone does not authorize client secret entry.
    handler.client_address=("127.0.0.1",1234)
    assert setup.local_request(handler) is False


def test_metadata_endpoint_cannot_accept_keys_or_paths(server):
    origin,_=server;opener=authenticated(origin)
    for forbidden in ("api_key","access_token","home","env"):
        status,body=http_request(opener,origin,"/api/provider-setup/accounts",{"family":"chatgpt","name":"Work", "expected_revision":1,forbidden:"credential-secret-sentinel"})
        assert status == 400 and "credential-secret-sentinel" not in body


def test_native_oauth_artifacts_only_allow_documented_provider_hosts():
    assert native.safe_auth_url("https://auth.openai.com/codex/device","chatgpt")
    for url in ("https://evil.invalid/login","http://auth.openai.com/login","https://auth.openai.com"+'@'+"evil.invalid/login","https://auth.openai.com:444/login"):
        assert native.safe_auth_url(url,"chatgpt") is None


def test_api_validation_uses_public_get_and_never_follows_redirects(monkeypatch):
    requests=[]
    class Response:
        status=200
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,size):return b'{"data":[]}'
    class Opener:
        def open(self,req,timeout):requests.append((req,timeout));return Response()
    monkeypatch.setattr(setup,"build_opener",lambda handler:Opener())
    setup.validate_api("chatgpt","api-validation-test-sentinel")
    req,timeout=requests[0]
    assert req.get_method() == "GET" and req.full_url == "https://api.openai.com/v1/models"
    assert req.data is None and timeout == 10
    assert setup.NoRedirect().redirect_request(None,None,302,None,None,None) is None


def test_first_setup_uses_existing_settings_only_on_explicit_action(stack):
    service, backend, data, home=stack
    settings.settings_path().unlink(); settings.mirror_path().unlink()
    before=service.snapshot()
    assert before['host']['first_setup'] and not before['host']['configured']
    assert not settings.settings_path().exists()
    assert backend.reads == []
    defaults=deepcopy(before['preferences'])
    after=service.initialize({'expected_revision':0})
    assert after['host']['configured'] and not after['host']['first_setup']
    assert after['preferences'] == defaults
    saved=settings.settings_path().read_bytes()
    assert settings.load_settings()['steward_type'] == 'aladdin'
    service.initialize({'expected_revision':0})
    assert settings.settings_path().read_bytes() == saved
    assert not (data/'Campaign').exists() and not list(data.rglob('*pair*'))


def test_existing_settings_and_steward_survive_first_setup_request(stack):
    service, _, _, _=stack
    settings.save_settings(steward_type='ecgberht')
    before=settings.settings_path().read_bytes()
    service.initialize({'expected_revision':0})
    assert settings.settings_path().read_bytes() == before


def test_installer_documentation_route_is_real_and_authenticated(server):
    origin,_=server
    code,content=http_request(authenticated(origin),origin,'/setup/install')
    assert code == 200 and 'Return to Setup' in content and 'onboard' in content.lower()


def test_new_claude_job_reaches_selected_isolated_home_without_api_billing(stack, monkeypatch, tmp_path):
    import job_runner
    service, backend, _, _=stack
    account=add(service,family='claude')
    backend.signed.add(account['id']);service.snapshot(True)
    prefs=deepcopy(service.snapshot()['preferences'])
    prefs.update(family='claude');prefs['accounts']['claude']=account['id']
    service.apply({'preferences':prefs,'expected_revision':settings.load_settings()['settings_revision']})
    child=tmp_path/'native_env_canary.py'
    child.write_text("import json, os\nprint(json.dumps({'home':os.getenv('CLAUDE_CONFIG_DIR'),'account':os.getenv('ANCHOR_PROVIDER_CONNECTION'),'api':bool(os.getenv('ANTHROPIC_API_KEY'))}))\n")
    monkeypatch.setenv('ANCHOR_RUNNER_CMD',f'{Path(sys.executable).as_posix()} {child.as_posix()}')
    record=job_runner.launch('research',backend='claude',env={'CLAUDE_CONFIG_DIR':'wrong-account','ANTHROPIC_API_KEY':'billing-canary-never-print'})
    final=job_runner.wait(record['job_id'],timeout=10)
    assert final['status'] == job_runner.STATUS_DONE
    assert record['provider_connection']['id'] == account['id']
    raw=Path(final['log_path']).read_text()
    observation=json.loads(raw)
    assert observation == {'home':str(native.account_home(account)), 'account':account['id'], 'api':False}
    assert 'billing-canary-never-print' not in raw


def test_running_engine_uses_bound_home_and_catalog_after_setup_change(stack,monkeypatch,tmp_path):
    from steward_cockpit import steward_engine
    service, backend, _, _=stack
    a,b=add(service,family='claude'),add(service,family='claude',name='Second subscription')
    monkeypatch.setattr(steward_engine,'STATE_FILE',tmp_path/'engines.json')
    directory=tmp_path/'conversation';directory.mkdir()
    steward_engine._update_state(str(directory),{'cli':'claude','session_id':'owned-session','provider_connection':a})
    engine=steward_engine.Engine(str(directory),fake=True)
    from types import SimpleNamespace
    engine.session_id='owned-session';engine.proc=SimpleNamespace(poll=lambda:None)
    backend.signed.add(b['id']);service.snapshot(True)
    prefs=deepcopy(service.snapshot()['preferences']);prefs['family']='claude';prefs['accounts']['claude']=b['id']
    service.apply({'preferences':prefs,'expected_revision':settings.load_settings()['settings_revision']})
    # Block gitguard installation; capture the actual engine environment seam.
    import importlib.util
    monkeypatch.setattr(importlib.util,'spec_from_file_location',lambda *a,**kw:None)
    env=engine._spawn_env()
    assert env['CLAUDE_CONFIG_DIR'] == str(native.account_home(a))
    assert env['ANCHOR_PROVIDER_CONNECTION'] == a['id']
    assert engine._account_policy_kwargs('claude')['env']['CLAUDE_CONFIG_DIR'] == str(native.account_home(a))
    assert engine.session_id == 'owned-session'
    assert engine._retain_native_session(steward_engine._read_state_entry(str(directory)))
    archive=steward_engine._read_state_entry(str(directory))['provider_sessions']
    assert archive[-1]['provider_connection']['id'] == a['id']


@pytest.mark.parametrize('cancelled',[False,True])
def test_documented_codex_device_login_protocol_and_cancel(stack,monkeypatch,cancelled):
    connection=metadata.new_connection('chatgpt','Device protocol')
    cancel=threading.Event();calls=[];progress=[]
    class Child:
        def next(self,event):
            if event.is_set():raise native.NativeError('cancelled')
            return 'stdout',json.dumps({'method':'account/login/completed','params':{'loginId':'native-login-id','success':True}})
    class Client:
        def __init__(self,connection,timeout):
            assert timeout == native.LOGIN_TIMEOUT
            self.child=Child();self.notifications=[]
        def rpc(self,method,params=None,event=None):
            calls.append((method,params))
            if method=='account/login/start':return {'loginId':'native-login-id','verificationUrl':'https://auth.openai.com/codex/device','userCode':'TEST-1234'}
            return {}
        def close(self):calls.append(('close',None))
    monkeypatch.setattr(native,'CodexAccount',Client)
    def receive(value):
        progress.append(value)
        if cancelled:cancel.set()
    if cancelled:
        with pytest.raises(native.NativeError,match='cancelled'):native.NativeProviders().login(connection,cancel,receive)
        assert ('account/login/cancel',{'loginId':'native-login-id'}) in calls
    else:native.NativeProviders().login(connection,cancel,receive)
    assert calls[0] == ('account/login/start',{'type':'chatgptDeviceCode'})
    assert calls[-1] == ('close',None) and progress[0]['state']=='awaiting_browser'


def test_claude_isolated_login_refuses_wrong_native_config_directory(stack,monkeypatch):
    connection=metadata.new_connection('claude','Isolated proof');calls=[]
    def run(argv,env,*args):
        calls.append(argv)
        return 1,json.dumps({'loggedIn':False,'configDirectory':'wrong-home'})
    monkeypatch.setattr(native,'run_command',run)
    with pytest.raises(native.NativeError) as failure:
        native.NativeProviders().login(connection,threading.Event(),lambda value:None)
    assert failure.value.state == 'unsupported'
    assert len(calls)==1 and calls[0][-2:] == ['auth','status']


def test_public_catalog_strips_provider_private_metadata(stack,monkeypatch):
    service, _, _, _=stack
    private='catalog-private-canary'
    catalog=[{'model':'frontier','efforts':['high'],'rank':0,'upgrade':None,'evidence':'provider_catalog_order','access_token':private}]
    monkeypatch.setattr(model_policy,'discover',lambda *a,**kw:(deepcopy(catalog),'safe-command'))
    service.snapshot(True)
    result=service.snapshot()
    assert private not in json.dumps(result)
    assert row(result,'chatgpt-default')['catalog']['rows']==[{'model':'frontier','efforts':['high']}]


def test_host_api_vault_validation_never_returns_or_persists_keys(server,monkeypatch):
    origin,(service, _, data, _)=server
    connection=add(service,mode='api');opener=authenticated(origin)
    vault={};checks=[];key='host-api-private-canary'
    monkeypatch.setattr(setup.provider_secrets,'available',lambda:True)
    monkeypatch.setattr(setup.provider_secrets,'put',lambda identity,secret:vault.update({identity:secret}))
    monkeypatch.setattr(setup.provider_secrets,'get',lambda identity:vault.get(identity))
    monkeypatch.setattr(setup,'validate_api',lambda family,secret:checks.append((family,secret)))
    status,body=http_request(opener,origin,'/api/provider-setup/api-key',{'connection_id':connection['id'],'api_key':key})
    assert status==200 and vault=={connection['id']:key} and checks
    assert key not in body and not row(json.loads(body),connection['id'])['execution']['ready']
    assert key not in settings.settings_path().read_text()
    status,body=http_request(opener,origin,'/api/provider-setup/api-key',{'connection_id':'chatgpt-default','api_key':key})
    assert status==400 and key not in body
    for filename in data.rglob('*.json'):assert key not in filename.read_text()


def test_loopback_proxy_cannot_accept_host_api_secret():
    class Request:
        headers={'Host':'127.0.0.1:8777','X-Forwarded-For':'100.64.0.10'}
        client_address=('127.0.0.1',5000)
    assert not setup.local_request(Request())


def test_engine_created_by_display_before_apply_binds_first_launch_choice(stack,monkeypatch,tmp_path):
    from steward_cockpit import steward_engine
    service, backend, _, _=stack
    monkeypatch.setattr(steward_engine,'STATE_FILE',tmp_path/'engine-state.json')
    engine=steward_engine.Engine(str(tmp_path/'not-yet-started'),fake=True)
    account=add(service)
    backend.signed.add(account['id']);service.snapshot(True)
    prefs=deepcopy(service.snapshot()['preferences']);prefs['family']='chatgpt';prefs['accounts']['chatgpt']=account['id']
    service.apply({'preferences':prefs,'expected_revision':settings.load_settings()['settings_revision']})
    assert engine._desired_policy()[1] == 'chatgpt'
    assert engine.provider_connection['id'] == account['id'] and engine.session_id is None


def test_warning_keeps_quality_until_explicit_manual_choice_and_survives_staleness(stack):
    service, backend, _, _=stack
    account=add(service);backend.signed.add(account['id']);service.snapshot(True)
    config=settings.load_settings();config['provider_preferences']['accounts']['chatgpt']=account['id']
    # Warning alone keeps the chosen subscription and maximum-quality policy.
    assert setup.selected_for_launch(config,'chatgpt',check_capacity=True)['id'] == account['id']
    config['provider_preferences']['warning_policy']='manual'
    with pytest.raises(ValueError,match='explicit route choice'):
        setup.selected_for_launch(config,'chatgpt',check_capacity=True)
    backend.failed[account['id']]='timeout';service.refresh(account)
    report=row(service.snapshot(),account['id'])
    assert report['capacity']=='unknown' and report['allowance']['state']=='stale'
    assert report['warning'] and 'now stale' in report['warning']
    assert config['model_policy']==model_policy.DEFAULT_POLICY


def test_partial_report_failure_keeps_last_allowance_when_authentication_succeeds(stack,monkeypatch):
    service, backend, _, _=stack
    service.snapshot(True);before=row(service.snapshot(),'chatgpt-default')
    observe=backend.observe
    def partial(connection):
        result=observe(connection)
        result['allowance']={'state':'timeout','source':'Fixture native rateLimits/read','windows':[]}
        return result
    monkeypatch.setattr(backend,'observe',partial)
    service.refresh(metadata.default_connections()[1])
    after=row(service.snapshot(),'chatgpt-default')
    assert after['auth']=='signed_in' and after['test']=='passed'
    assert after['allowance']['state']=='stale' and after['allowance']['error']=='timeout'
    assert after['allowance']['windows']==before['allowance']['windows']
    assert after['allowance']['observed_at']==before['allowance']['observed_at']


def test_native_credentials_cannot_be_downloaded_through_project_routes(server,monkeypatch):
    import anchor_gui
    import report_viewer
    from urllib.parse import quote
    origin,(service, _, data, _)=server
    account=add(service)
    home=native.account_home(account);home.mkdir(parents=True)
    private=home/'auth.json';private.write_text('private-download-canary')
    relative=private.relative_to(data).as_posix()
    monkeypatch.setattr(anchor_gui,'_ecgberht_project_folder',lambda pid:(str(data),None,200))
    monkeypatch.setattr(anchor_gui._rnd,'get_project',lambda pid:{'id':pid,'folder_path':str(data)})
    opener=authenticated(origin)
    for route in ('/api/ecgberht/artifact?project_id=p&rel=', '/api/ecgberht/chamber_artifact?project_id=p&rel=',
                  '/api/rnd/project_file_content?project_id=p&path=','/artifact/p?path='):
        code,body=http_request(opener,origin,route+quote(relative))
        assert code in (403,404) and 'private-download-canary' not in body
    # Even registering the native home itself does not make it an artifact.
    assert report_viewer.resolve_project_artifact(str(home),'auth.json') is None
    from steward_cockpit import steward_routes
    result,code=steward_routes.handle_get(str(data),'deliverable-file',{'path':relative})
    assert code==403 and 'private-download-canary' not in json.dumps(result)


def test_native_report_authentication_failure_marks_expired_subscription(stack,monkeypatch):
    class Client:
        def __init__(self,connection):pass
        def rpc(self,method,params=None):
            if method=='account/read':return {'account':{'type':'chatgpt'}}
            raise native.NativeError('expired')
        def close(self):pass
    monkeypatch.setattr(native,'CodexAccount',Client)
    result=native.NativeProviders().observe(metadata.default_connections()[1])
    assert result['auth']=='expired' and result['test']=='failed'
    assert result['allowance']['state']=='expired'


def test_wave3_setup_chart_api_and_dom_contracts(server):
    origin, (_, _, data, _) = server
    opener = authenticated(origin)

    # Unauthenticated requests to /api/steward/setup_chart are rejected
    unauth_code, _ = http_request(build_opener(), origin, "/api/steward/setup_chart")
    assert unauth_code in (401, 403)
    unauth_post, _ = http_request(build_opener(), origin, "/api/steward/setup_chart", {"action": "set_root", "path": "D:\\dev"})
    assert unauth_post in (401, 403)

    # /setup page includes Wave 1, Wave 2, and Wave 3 DOM landmarks
    code, html = http_request(opener, origin, "/setup")
    assert code == 200
    for required_id in (
        'id="setup-section-host"',
        'id="setup-section-providers"',
        'id="setup-section-chart"',
        'id="wave2-provider-matrix"',
        'id="panel-workspace-root"',
        'id="folder-list-container"',
        'id="projects-grid-container"',
        'id="goals-grid-container"',
        'id="tab-mode-projects"',
        'id="tab-mode-starchart"',
        'id="tab-mode-guide"',
    ):
        assert required_id in html, required_id

    # GET /api/steward/setup_chart is read-only and does not create state file on disk
    state_file = data / ".anchor" / "setup-chart-state.json"
    assert not state_file.exists()
    code, raw = http_request(opener, origin, "/api/steward/setup_chart")
    assert code == 200
    chart = json.loads(raw)
    assert chart["ok"] is True
    assert chart["primary_root"] == r"C:\dev"
    assert len(chart["folders"]) >= 8
    assert len(chart["project_groups"]) >= 4
    assert len(chart["goal_tiles"]) >= 3
    assert not state_file.exists()

    # POST set_root persists primary_root
    code, raw = http_request(opener, origin, "/api/steward/setup_chart", {
        "action": "set_root",
        "path": r"D:\MotherShipDev",
        "create_if_missing": True,
    })
    assert code == 200
    res = json.loads(raw)
    assert res["ok"] is True and res["state"]["primary_root"] == r"D:\MotherShipDev"
    assert state_file.exists()

    # POST set_folder_role updates 3-state role & subordinate parent linkage
    code, raw = http_request(opener, origin, "/api/steward/setup_chart", {
        "action": "set_folder_role",
        "folderId": "f-fin",
        "role": "subordinate",
        "parentId": "f-anchor",
    })
    assert code == 200
    folders_by_id = {f["id"]: f for f in json.loads(raw)["state"]["folders"]}
    assert folders_by_id["f-fin"]["role"] == "subordinate"
    assert folders_by_id["f-fin"]["parentId"] == "f-anchor"
    assert folders_by_id["f-fin"]["groupId"] == folders_by_id["f-anchor"]["groupId"]

    # POST add_external and unlink_external
    code, raw = http_request(opener, origin, "/api/steward/setup_chart", {
        "action": "add_external",
        "path": r"E:\BioComputeVault",
        "mode": "read_only",
    })
    assert code == 200
    st = json.loads(raw)["state"]
    assert any(e["path"] == r"E:\BioComputeVault" for e in st["external_roots"])
    assert any(f["path"] == r"E:\BioComputeVault" and f["source"] == "external" for f in st["folders"])

    code, raw = http_request(opener, origin, "/api/steward/setup_chart", {
        "action": "unlink_external",
        "path": r"E:\BioComputeVault",
    })
    assert code == 200
    st = json.loads(raw)["state"]
    assert not any(e["path"] == r"E:\BioComputeVault" for e in st["external_roots"])

    # POST add_cockpit and shape_goals
    code, raw = http_request(opener, origin, "/api/steward/setup_chart", {
        "action": "add_cockpit",
        "folderId": "f-anchor",
        "name": "Wave 3 Verification Shark",
        "engine": "Gemini 3.1 Pro",
    })
    assert code == 200
    anchor_folder = next(f for f in json.loads(raw)["state"]["folders"] if f["id"] == "f-anchor")
    assert any(cp["name"] == "Wave 3 Verification Shark" for cp in anchor_folder["cockpits"])

    code, raw = http_request(opener, origin, "/api/steward/setup_chart", {
        "action": "shape_goals",
        "rawText": "Ship Star Chart Wave 3\n- Wire 3-state folders\n- Persist goal tiles",
        "linkedGroup": "grp-core",
    })
    assert code == 200
    shaped = json.loads(raw)["shaped"]
    assert shaped["title"] == "Ship Star Chart Wave 3"
    assert len(shaped["milestones"]) == 2

    # POST search_pull_copy and search_pull_undo
    code, raw = http_request(opener, origin, "/api/steward/setup_chart", {
        "action": "search_pull_copy",
        "name": "Quant-Alpha-Notebook",
        "src": r"C:\Users\john\Downloads\Quant-Alpha-Notebook",
        "destSubpath": r"imported\Quant-Alpha-Notebook",
        "files": 17,
        "size": "1.9 MB",
        "groupId": "grp-quant",
    })
    assert code == 200
    pull_res = json.loads(raw)
    pull_id = pull_res["manifest"]["id"]
    assert (data / ".anchor" / "pulls" / f"{pull_id}.json").exists()
    assert any(f.get("pullId") == pull_id for f in pull_res["state"]["folders"])

    code, raw = http_request(opener, origin, "/api/steward/setup_chart", {
        "action": "search_pull_undo",
        "pullId": pull_id,
    })
    assert code == 200
    undone_state = json.loads(raw)["state"]
    assert not any(f.get("pullId") == pull_id for f in undone_state["folders"])

