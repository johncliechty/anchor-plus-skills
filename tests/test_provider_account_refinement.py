"""Account refinement exercises production native, service, registry and engine seams."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

import anchor_settings as settings
import model_policy
import provider_native as native
import provider_secrets
import provider_settings as metadata
import provider_setup as setup
from tests.test_provider_setup import stack, server, add, row, authenticated, http_request


@pytest.mark.parametrize("family", metadata.FAMILIES)
def test_missing_installed_interface_cannot_claim_enrollment(stack, monkeypatch, family):
    monkeypatch.setattr(native, "executable", lambda _: None)
    cap = native.NativeProviders().capabilities(family)
    assert not cap["installed"] and not cap["isolated"] and not cap["login"]
    backend = native.NativeProviders()
    service = setup.ProviderService(backend)
    result = service.snapshot(True)
    assert {c["family"] for c in result["connections"]} == set(metadata.FAMILIES)
    assert all(not c["execution"]["ready"] for c in result["connections"])
    assert not result["product_complete"]
    with pytest.raises(ValueError, match="isolated"):
        add(service, family=family)


def test_gemini_existing_agy_status_never_submits_a_turn(stack, monkeypatch):
    commands = []
    monkeypatch.setattr(native, "executable", lambda _: "agy-fixture")
    def command(argv, env, *args, **kwargs):
        commands.append(argv)
        assert argv == ["agy-fixture", "--version"]
        return 0, "1.3.0"
    monkeypatch.setattr(native, "run_command", command)
    backend = native.NativeProviders()
    cap = backend.capabilities("gemini")
    report = backend.observe(metadata.find_connection(settings.load_settings(), "gemini-default"))
    assert report["auth"] == "unknown" and report["test"] == "not_tested"
    assert report["auth_source"] == "Existing Google Ultra connection via agy CLI"
    assert not cap["isolated"] and not cap["login"]
    assert "passive account/status" in cap["limit"]
    assert commands == [["agy-fixture", "--version"]]
    assert report["allowance"]["state"] == "unsupported"


@pytest.mark.parametrize("supported", [True, False])
def test_grok_advertised_status_isolation_and_browser_branch(stack, monkeypatch, supported):
    commands = []
    signed = set()
    monkeypatch.setattr(native, "executable", lambda _: "grok-fixture")
    def command(argv, env, cancel=None, timeout=None, progress=None):
        commands.append((argv, dict(env)))
        tail = argv[1:]
        if tail == ["--version"]: return 0, "3.0.0"
        if tail == ["--help"]: return 0, "  auth  Account commands\nGROK_HOME" if supported else "  models  List models"
        if tail == ["auth", "--help"]: return 0, "  status  Read account\n  login  Browser enrollment"
        if tail == ["auth", "status", "--help"]: return 0, "--json"
        if tail == ["auth", "login", "--help"]: return 0, "--browser"
        home = env["GROK_HOME"]
        if tail == ["auth", "status", "--json"]:
            return 0, json.dumps({"loggedIn": home in signed, "configDirectory": home,
                                  "billingMode": "subscription", "email": "grok@example.test",
                                  "accessToken": "never-export-grok-credential"})
        if tail == ["auth", "login", "--browser"]:
            progress("https://grok.com/login\n")
            signed.add(home)
            return 0, ""
        pytest.fail("Unexpected native command")
    monkeypatch.setattr(native, "run_command", command)
    backend = native.NativeProviders()
    cap = backend.capabilities("grok")
    assert cap["isolated"] is supported
    if not supported:
        assert "GROK_HOME" in cap["limit"]
        with pytest.raises(native.NativeError, match="support"):
            backend.observe(metadata.new_connection("grok", "Unavailable"))
        assert all("-p" not in argv for argv, _ in commands)
        return
    service = setup.ProviderService(backend)
    monkeypatch.setattr(setup, "SERVICE", service)
    one, two = add(service, "grok", "Grok one"), add(service, "grok", "Grok two")
    for connection in (one, two):
        attempt = service.start_login(connection["id"])
        service.logins[attempt["id"]]["thread"].join(5)
        assert service.login_status(attempt["id"])["state"] == "completed"
        assert row(service.snapshot(), connection["id"])["execution"]["ready"]
    assert str(native.account_home(one)) != str(native.account_home(two))
    assert str(native.account_home(metadata.find_connection(settings.load_settings(), "grok-default"))) not in signed
    assert "never-export-grok-credential" not in json.dumps(service.snapshot())
    prefs = deepcopy(service.snapshot()["preferences"])
    prefs.update(family="grok")
    prefs["accounts"]["grok"] = two["id"]
    service.apply({"preferences": prefs, "expected_revision": settings.load_settings()["settings_revision"]})
    assert setup.selected_for_launch(settings.load_settings(), "grok")["id"] == two["id"]


def test_grok_ignoring_native_home_cannot_enroll(stack, monkeypatch):
    monkeypatch.setattr(native, "executable", lambda _: "grok-fixture")
    def command(argv, env, *args, **kwargs):
        tail = argv[1:]
        if tail == ["--version"]: return 0, "3.0.0"
        if tail == ["--help"]: return 0, "  auth  Commands\nGROK_HOME"
        if tail == ["auth", "--help"]: return 0, "  status  Account\n  login  Browser"
        if tail[-1] == "--help": return 0, "--json --browser"
        return 0, json.dumps({"loggedIn": False, "configDirectory": str(Path(env["GROK_HOME"]).parent)})
    monkeypatch.setattr(native, "run_command", command)
    assert not native.NativeProviders().capabilities("grok")["isolated"]


@pytest.mark.parametrize("family", ["claude", "chatgpt"])
def test_two_native_subscriptions_enroll_without_default_replacement(stack, monkeypatch, family):
    signed, calls = set(), []
    monkeypatch.setattr(native, "executable", lambda _: "native-fixture")
    def command(argv, env, cancel=None, timeout=None, progress=None):
        calls.append((argv, dict(env)))
        if argv[1:] == ["--version"]: return 0, "2.1.268"
        if argv[1:] == ["auth", "login", "--help"]: return 0, "--claudeai"
        home = env["CLAUDE_CONFIG_DIR"]
        if argv[1:] == ["auth", "status"]:
            return 0, json.dumps({"loggedIn": home in signed, "authMethod": "claude.ai",
                                  "configDirectory": home, "email": "claude@example.test",
                                  "accessToken": "never-export-claude-credential"})
        assert argv[1:] == ["auth", "login", "--claudeai"]
        progress("https://claude.ai/login\n")
        signed.add(home)
        return 0, ""
    monkeypatch.setattr(native, "run_command", command)
    class Client:
        def __init__(self, connection, timeout=None):
            self.home = str(native.account_home(connection))
            self.notifications = [{"method": "account/login/completed", "params": {"loginId": "disposable", "success": True}}]
            self.child = SimpleNamespace()
        def rpc(self, method, params=None, cancel=None):
            calls.append((method, params))
            if method == "account/read":
                return {"account": {"type": "chatgpt", "email": "codex@example.test", "accessToken": "never-export-codex-credential"} if self.home in signed else None}
            if method == "account/login/start":
                assert params == {"type": "chatgptDeviceCode"}
                signed.add(self.home)
                return {"loginId": "disposable", "verificationUrl": "https://auth.openai.com/codex/device", "userCode": "TEST-1234"}
            return {}
        def close(self): pass
    monkeypatch.setattr(native, "CodexAccount", Client)
    backend = native.NativeProviders()
    # Codex capability schema proof is separately exercised below. Here the
    # real native login/account protocol is driven through a disposable client.
    if family == "chatgpt":
        monkeypatch.setattr(backend, "capabilities", lambda _: {"installed": True, "state": "available", "isolated": True, "login": "device", "version": "1.0.0"})
    service = setup.ProviderService(backend)
    one, two = add(service, family, "Personal"), add(service, family, "Teaching")
    before = native.account_home(metadata.find_connection(settings.load_settings(), family + "-default"))
    for connection in (one, two):
        attempt = service.start_login(connection["id"])
        service.logins[attempt["id"]]["thread"].join(5)
        assert service.login_status(attempt["id"])["state"] == "completed"
        report = row(service.snapshot(), connection["id"])
        assert report["auth"] == "signed_in" and report["execution"]["ready"]
        assert report["account_identity"] and "@example.test" not in report["account_identity"]
        assert "isolated native account" in report["connection_source"]
    assert len(signed) == 2 and str(before) not in signed
    assert one["id"] != two["id"] and native.account_home(one) != native.account_home(two)
    assert "never-export" not in json.dumps(service.snapshot())


def test_codex_installed_schema_and_empty_account_prove_isolation(stack, monkeypatch):
    commands = []
    monkeypatch.setattr(native, "executable", lambda _: "codex-fixture")
    def command(argv, env, *args, **kwargs):
        commands.append(argv)
        if argv[1:] == ["--version"]: return 0, "1.0.0"
        if argv[1:] == ["app-server", "--help"]: return 0, "--listen"
        assert argv[1:3] == ["app-server", "generate-json-schema"]
        Path(argv[-1], "LoginAccountParams.json").write_text(json.dumps({"oneOf": [{"properties": {"type": {"enum": ["chatgptDeviceCode"]}}}]}))
        return 0, ""
    class Child:
        def __init__(self, argv, env, timeout=None):
            self.events = []
            assert Path(env["CODEX_HOME"]).is_dir()
        def send(self, message):
            if "id" in message:
                result = {"account": None} if message["method"] == "account/read" else {}
                self.events.append(("stdout", json.dumps({"id": message["id"], "result": result})))
        def next(self, cancel=None): return self.events.pop(0)
        def close(self): pass
    monkeypatch.setattr(native, "run_command", command)
    monkeypatch.setattr(native, "HiddenProcess", Child)
    cap = native.NativeProviders().capabilities("chatgpt")
    assert cap["isolated"] and cap["login"] == "device"
    assert all("-p" not in argv for argv in commands)


def test_named_accounts_reload_summaries_and_first_launch_binding(stack, monkeypatch, tmp_path):
    from steward_cockpit import steward_engine
    service, backend, _, _ = stack
    one, two = add(service, "claude", "Claude one"), add(service, "claude", "Claude two")
    backend.signed.update((one["id"], two["id"]))
    service.snapshot(True)
    service.rename({"connection_id": two["id"], "name": "Claude Teaching", "expected_revision": settings.load_settings()["settings_revision"]})
    monkeypatch.setattr(steward_engine, "STATE_FILE", tmp_path / "engine-state.json")
    directory = tmp_path / "existing"
    directory.mkdir()
    steward_engine._update_state(str(directory), {"cli": "claude", "session_id": "owned-session", "provider_connection": one})
    existing = steward_engine.Engine(str(directory), fake=True)
    existing.session_id = "owned-session"
    existing.proc = SimpleNamespace(poll=lambda: None)
    idle = steward_engine.Engine(str(tmp_path / "new-work"), fake=True)
    prefs = deepcopy(service.snapshot()["preferences"])
    prefs.update(family="claude")
    prefs["accounts"]["claude"] = two["id"]
    service.apply({"preferences": prefs, "expected_revision": settings.load_settings()["settings_revision"]})
    assert idle._desired_policy()[1] == "claude" and idle.provider_connection["id"] == two["id"]
    assert existing._desired_policy()[1] == "claude" and existing.provider_connection["id"] == one["id"]
    monkeypatch.setattr(importlib.util, "spec_from_file_location", lambda *args, **kwargs: None)
    assert existing._spawn_env()["CLAUDE_CONFIG_DIR"] == str(native.account_home(one))
    assert idle._spawn_env()["CLAUDE_CONFIG_DIR"] == str(native.account_home(two))
    reloaded = setup.ProviderService(backend).snapshot()
    assert row(reloaded, two["id"])["name"] == "Claude Teaching"
    assert reloaded["preferences"]["accounts"]["claude"] == two["id"]
    assert existing.session_id == "owned-session"


def test_inactive_family_account_selection_is_also_guarded(stack):
    service, _, _, _ = stack
    unready = add(service, "claude", "Not connected")
    prefs = deepcopy(service.snapshot()["preferences"])
    prefs.update(family="chatgpt")
    prefs["accounts"]["claude"] = unready["id"]
    with pytest.raises(ValueError, match="unready"):
        service.apply({"preferences": prefs, "expected_revision": settings.load_settings()["settings_revision"]})


def test_expired_bound_account_cannot_replace_conversation_credentials(stack, monkeypatch, tmp_path):
    from steward_cockpit import steward_engine
    service, backend, _, _ = stack
    connection = add(service, "claude", "Bound")
    monkeypatch.setattr(steward_engine, "STATE_FILE", tmp_path / "bound.json")
    steward_engine._update_state("owned", {"session_id": "owned-session", "provider_connection": connection})
    monkeypatch.setattr(backend, "observe", lambda c: {**setup.empty_observation(), "auth": "expired", "test": "failed"})
    with pytest.raises(ValueError, match="bound to a conversation"):
        service.start_login(connection["id"])
    assert not backend.login_started.is_set()


def test_missing_model_catalog_disables_execution(stack, monkeypatch):
    service, _, _, _ = stack
    def missing(*args, **kwargs): raise ValueError("Catalog unavailable")
    monkeypatch.setattr(model_policy, "discover", missing)
    service.snapshot(True)
    assert not row(service.snapshot(), "claude-default")["execution"]["ready"]


def test_protected_api_credentials_remain_explicit_separate_billing(server, monkeypatch):
    origin, (service, _, _, _) = server
    vault = {}
    secret = "fake-private-api-credential"
    connection = add(service, "chatgpt", "Optional paid API", mode="api")
    monkeypatch.setattr(provider_secrets, "available", lambda: True)
    monkeypatch.setattr(provider_secrets, "put", lambda identity, value: vault.update({identity: value}))
    monkeypatch.setattr(provider_secrets, "get", lambda identity: vault.get(identity))
    monkeypatch.setattr(setup, "validate_api", lambda family, key: None)
    status, response = http_request(authenticated(origin), origin, "/api/provider-setup/api-key",
                                    {"connection_id": connection["id"], "api_key": secret})
    assert status == 200 and vault == {connection["id"]: secret}
    assert secret not in response and secret not in settings.settings_path().read_text()
    account = row(json.loads(response), connection["id"])
    assert not account["execution"]["ready"] and "no explicit API execution adapter" in account["execution"]["reason"]
    assert account["allowance"]["state"] == "unsupported" and account["api_spend"]["amount"] is None
    prefs = deepcopy(service.snapshot()["preferences"])
    prefs["accounts"]["chatgpt"] = connection["id"]
    with pytest.raises(ValueError, match="API execution"):
        service.apply({"preferences": prefs, "expected_revision": settings.load_settings()["settings_revision"]})


def test_remove_connection_uses_existing_registry_and_retains_native_home(server):
    origin, (service, _, _, _) = server
    connection = add(service, "claude", "Remove from choices")
    home = native.account_home(connection)
    home.mkdir(parents=True)
    disposable = home / "disposable-native-state"
    disposable.write_text("disposable account continuity")
    status, response = http_request(authenticated(origin), origin, "/api/provider-setup/remove",
                                    {"connection_id": connection["id"], "expected_revision": settings.load_settings()["settings_revision"]})
    assert status == 200
    assert connection["id"] not in {c["id"] for c in json.loads(response)["connections"]}
    assert disposable.read_text() == "disposable account continuity"
    assert len(settings.load_settings()["provider_connections"]) == 4


@pytest.mark.parametrize("raw", [[], None, True, {"configDirectory": []}, {"configDirectory": ""}])
def test_malformed_claude_identity_report_fails_closed(stack, monkeypatch, raw):
    connection = metadata.new_connection("claude", "Untrusted account report")
    monkeypatch.setattr(native, "run_command", lambda *a, **kw: (0, json.dumps(raw)))
    with pytest.raises(native.NativeError):
        native.NativeProviders().observe(connection)


@pytest.mark.parametrize("url", ["https://claude.ai:invalid/login", "https://claude.ai:99999/login",
                                 "https://[invalid/login"])
def test_malformed_native_login_url_cannot_open_or_expose_credentials(url):
    assert native.safe_auth_url(url, "claude") is None


def test_malformed_installed_schema_never_enables_an_account(stack, monkeypatch):
    monkeypatch.setattr(native, "executable", lambda _: "codex-fixture")
    def command(argv, env, *args, **kwargs):
        if argv[1:] == ["--version"]:
            return 0, "1.0.0"
        if argv[1:] == ["app-server", "--help"]:
            return 0, "--listen"
        assert argv[1:3] == ["app-server", "generate-json-schema"]
        Path(argv[-1], "LoginAccountParams.json").write_text("[]", encoding="utf-8")
        return 0, ""
    monkeypatch.setattr(native, "run_command", command)
    service = setup.ProviderService(native.NativeProviders())
    cap = service.capability("chatgpt", refresh=True)
    assert cap["state"] == "error" and not cap["isolated"] and not cap["login"]
    assert "Existing sign-in is retained" in cap["limit"]
    assert not row(service.snapshot(), "chatgpt-default")["execution"]["ready"]
