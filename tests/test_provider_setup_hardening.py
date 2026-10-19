"""Wave 2 of the provider-integration assurance: the hardening proofs.

Six required ids (one test each, bound as the test's pytest parameter id so the
gate's ``-v`` output names it literally) establish the failure paths the frozen
plan lists for this wave: a native timeout that keeps the cached state, a
cancelled device login whose owned process tree is reaped, invalid or changed
settings that are never overwritten, credentials that reach no response or
artifact, an account change that leaves a running conversation bound, and
cached reads that never wait on native work.

Every test runs against isolated temporary data/home directories, the ordinary
cookie login through the real server, and native commands substituted at their
documented interfaces: the ``NativeFixture`` backend, or a REAL hidden process
(a ``.cmd`` stand-in for a native CLI written to a temp dir and returned by a
monkeypatched ``provider_native.executable``, speaking the documented
app-server stdio protocol). Nothing touches the live service, global
preferences, the host vault or a real credential.
"""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
from urllib.parse import quote
import uuid

import pytest

import anchor_settings as settings
import proc_probe
import provider_native as native
import provider_settings as metadata
import provider_setup as setup
from tests.test_provider_setup import (AUTH, NativeFixture, stack, server, add, row,  # noqa: F401 (fixtures)
                                       authenticated, http_request)
from tests.test_provider_setup_rigor import (browser_login, guarded_page, public_rows,
                                             start_refresh_request, timed_get)

REQUIRED_IDS = ("native-timeout-retains-cached-state", "cancelled-owned-process-cleanup",
                "invalid-settings-do-not-overwrite", "credentials-not-in-responses-or-artifacts",
                "account-selection-preserves-running-conversation", "cached-state-does-not-wait-for-refresh")

GENERIC_ERROR = "Host provider action failed; existing setup is retained"


def required(identity):
    assert identity in REQUIRED_IDS
    return pytest.mark.parametrize("required_id", [pytest.param(identity, id=identity)])


def wait_until(predicate, timeout=15, step=0.05):
    deadline = time.monotonic() + timeout
    while True:
        value = predicate()
        if value:
            return value
        if time.monotonic() >= deadline:
            return value
        time.sleep(step)


def wait_dead(pid, timeout=10):
    assert wait_until(lambda: not proc_probe.is_alive(pid), timeout), f"pid {pid} is still alive"


def cave_context(monkeypatch):
    """The real Cave page served with frozen display fixtures (the browser tests' seam)."""
    import anchor_gui
    from tests.test_high_seat_page_2026_09_26 import _ctx
    context = _ctx()
    context.update(auth_required=True, logged_in=True, build=anchor_gui.BUILD_ID, capacity=[])
    context["steward"] = {"key": "aladdin", "label": "Aladdin", "high_seat": "aladdin-high-seat-cave.jpg",
                          "high_seat_name": "Cave of Wonders", "seal_name": "Lamp", "campaign_name": "Star Chart",
                          "campaign_icon": "campaign-aladdin-star-chart.jpg"}
    monkeypatch.setattr(anchor_gui, "_high_seat_context", lambda: deepcopy(context))


# ── a REAL hidden process standing in for a native CLI ───────────────────────

CODEX_STANDIN = r'''
import json, os, subprocess, sys, time
CONTROL = __CONTROL__


def mode():
    try:
        with open(os.path.join(CONTROL, "mode.json"), encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, ValueError):
        return {}


def note(**event):
    event.update(pid=os.getpid(), home=os.environ.get("CODEX_HOME"))
    with open(os.path.join(CONTROL, "events.log"), "a", encoding="utf-8") as stream:
        stream.write(json.dumps(event) + "\n")


def sleeper():
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def emit(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def main():
    args, knobs = sys.argv[1:], mode()
    if knobs.get("hang"):
        child = sleeper()
        note(argv=args, hang=True, grandchild=child.pid)
        time.sleep(120)
        return 0
    if args == ["--version"]:
        print("codex-cli 2.1.300")
        return 0
    if args == ["app-server", "--help"]:
        print("Usage: codex app-server --listen <addr>")
        return 0
    if args[:3] == ["app-server", "generate-json-schema", "--out"]:
        os.makedirs(args[3], exist_ok=True)
        with open(os.path.join(args[3], "LoginAccountParams.json"), "w", encoding="utf-8") as stream:
            json.dump({"oneOf": [{"properties": {"type": {"enum": ["chatgptDeviceCode"]}}}]}, stream)
        return 0
    if args != ["app-server", "--listen", "stdio://"]:
        return 2
    note(argv=args)
    home = os.environ.get("CODEX_HOME") or ""
    while True:
        line = sys.stdin.readline()
        if not line:
            return 0
        try:
            message = json.loads(line)
        except ValueError:
            continue
        identity, method = message.get("id"), message.get("method")
        note(method=method)
        if identity is None:
            continue
        if method == "account/read":
            if knobs.get("error"):
                emit({"id": identity, "error": {"code": -32000, "message": knobs["error"]}})
                continue
            signed = os.path.isfile(os.path.join(home, "auth.json"))
            emit({"id": identity, "result": {"account": {"type": "chatgpt"} if signed else None}})
        elif method == "account/rateLimits/read":
            emit({"id": identity, "result": {"rateLimits": {"primary": {"usedPercent": 25, "windowDurationMins": 300,
                                                                        "resetsAt": time.time() + 3600}}}})
        elif method == "account/usage/read":
            emit({"id": identity, "result": {"summary": {"lifetimeTokens": 4321}}})
        elif method == "account/login/start":
            child = sleeper()
            note(grandchild=child.pid)
            emit({"id": identity, "result": {"loginId": "standin-login", "verificationUrl": "https://auth.openai.com/codex/device",
                                             "userCode": "WXYZ-1234"}})
            if knobs.get("login") == "complete":
                os.makedirs(home, exist_ok=True)
                with open(os.path.join(home, "auth.json"), "w", encoding="utf-8") as stream:
                    stream.write(knobs.get("credential", "standin-credential"))
                emit({"method": "account/login/completed", "params": {"loginId": "standin-login", "success": True}})
        elif method == "account/login/cancel" and knobs.get("ignore_cancel"):
            continue   # a wedged native child never answers the cancel
        else:
            emit({"id": identity, "result": {}})


sys.exit(main())
'''

CLAUDE_STANDIN = r'''
import json, os, sys
CONTROL = __CONTROL__


def mode():
    try:
        with open(os.path.join(CONTROL, "mode.json"), encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, ValueError):
        return {}


args, knobs = sys.argv[1:], mode()
if knobs.get("stderr"):
    sys.stderr.write(knobs["stderr"] + "\n")
    sys.stderr.flush()
if args == ["--version"]:
    print("2.1.300 (Claude Code)")
elif args == ["auth", "login", "--help"]:
    print("claude auth login --claudeai")
elif args == ["auth", "status"]:
    home = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    signed = os.path.isfile(os.path.join(home, ".credentials.json"))
    print(json.dumps({"loggedIn": signed, "authMethod": "claude.ai" if signed else None, "configDirectory": home}))
else:
    sys.exit(2)
'''


class NativeStandIn:
    """A REAL hidden process per native command: a ``.cmd`` wrapper in a temp
    dir (returned by the monkeypatched ``provider_native.executable``) running a
    Python script that speaks the documented interface. Behaviour knobs live in
    ``mode.json``; every process notes its pid and requests in ``events.log``."""
    def __init__(self, root, monkeypatch, families=("chatgpt",)):
        self.root = root / "standin"
        self.root.mkdir()
        self.events, self.mode_path = self.root / "events.log", self.root / "mode.json"
        self.set_mode()
        scripts = {"chatgpt": ("codex", CODEX_STANDIN), "claude": ("claude", CLAUDE_STANDIN)}
        self.binaries = {}
        for family in families:
            name, source = scripts[family]
            script = self.root / (name + "_standin.py")
            script.write_text(source.replace("__CONTROL__", repr(str(self.root))), encoding="utf-8")
            wrapper = self.root / (name + ".cmd")
            wrapper.write_bytes(f'@echo off\r\n"{sys.executable}" -u "{script}" %*\r\nexit /b %ERRORLEVEL%\r\n'.encode("utf-8"))
            self.binaries[family] = str(wrapper)
        monkeypatch.setattr(native, "executable", lambda family: self.binaries.get(family))

    def set_mode(self, **knobs):
        self.mode_path.write_text(json.dumps(knobs), encoding="utf-8")

    def records(self):
        out = []
        if self.events.exists():
            for line in self.events.read_text(encoding="utf-8").splitlines():
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue   # a line still being appended by a live stand-in
        return out

    def wait_for(self, predicate, timeout=20):
        found = wait_until(lambda: [r for r in self.records() if predicate(r)], timeout)
        assert found, "the stand-in never reported: " + str(self.records()[-5:])
        return found


def record_sends(monkeypatch):
    """Every JSON-RPC message the product writes onto a hidden process's stdin."""
    sent, original = [], native.HiddenProcess.send
    def send(self, value):
        sent.append(deepcopy(value))
        return original(self, value)
    monkeypatch.setattr(native.HiddenProcess, "send", send)
    return sent


# ── required ids ──────────────────────────────────────────────────────────────


@required("native-timeout-retains-cached-state")
def test_native_timeout_retains_cached_state(server, monkeypatch, tmp_path, required_id):
    origin, (service, _, _, home) = server
    standin = NativeStandIn(tmp_path, monkeypatch)
    (home / ".codex").mkdir()
    (home / ".codex" / "auth.json").write_text("existing-native-sign-in", encoding="utf-8")
    service.native = native.NativeProviders()
    connection = metadata.find_connection(settings.load_settings(), "chatgpt-default")
    service.refresh(connection)   # the real adapter: capability probes + account reads through the stand-in
    opener = authenticated(origin)
    status, body = http_request(opener, origin, "/api/provider-setup")
    assert status == 200
    before = public_rows(json.loads(body))["chatgpt-default"]
    assert before["auth"] == "signed_in" and before["allowance"]["state"] == "fresh" and before["allowance"]["windows"]
    assert before["catalog"]["state"] == "fresh"
    primary, mirror = settings.settings_path().read_bytes(), settings.mirror_path().read_bytes()
    monkeypatch.setattr(native, "COMMAND_TIMEOUT", 3)
    standin.set_mode(hang=True)
    started = time.monotonic()
    worker, result = start_refresh_request(origin, "/api/provider-setup?refresh=1&connection_id=chatgpt-default")
    hung = standin.wait_for(lambda r: r.get("hang"))[0]
    pids = [hung["pid"], hung["grandchild"]]
    assert all(proc_probe.is_alive(pid) for pid in pids) and worker.is_alive()
    status, body, _ = timed_get(opener, origin, "/api/provider-setup", 2)
    assert status == 200 and worker.is_alive(), "the cached read did not overlap the timed-out refresh"
    assert public_rows(json.loads(body))["chatgpt-default"] == before
    worker.join(native.COMMAND_TIMEOUT + 10)
    elapsed = time.monotonic() - started
    assert not worker.is_alive() and result.get("status") == 200, result
    assert elapsed < native.COMMAND_TIMEOUT + 8, f"the timed-out refresh took {elapsed:.1f}s"
    published = row(json.loads(result["body"]), "chatgpt-default")
    assert published["auth"] == "timeout" and published["test"] == "failed"
    assert published["allowance"] == {**before["allowance"], "state": "stale", "attempted_at": published["attempted_at"], "error": "timeout"}
    assert published["catalog"] == before["catalog"]
    status, body = http_request(opener, origin, "/api/provider-setup")
    after = row(json.loads(body), "chatgpt-default")
    assert status == 200 and after["auth"] == "timeout" and after["allowance"] == published["allowance"]
    hangs = [r for r in standin.records() if r.get("hang")]
    assert hangs, "the account read ran no hidden process: " + str(hangs)   # the capability probe is served from its TTL cache here
    for record in hangs:   # R3-B: every hung process and its grandchild is reaped, not only the first
        wait_dead(record["pid"])
        wait_dead(record["grandchild"])
    assert settings.settings_path().read_bytes() == primary and settings.mirror_path().read_bytes() == mirror
    assert (home / ".codex" / "auth.json").read_text(encoding="utf-8") == "existing-native-sign-in"


@required("cancelled-owned-process-cleanup")
def test_cancelled_owned_process_cleanup(stack, monkeypatch, tmp_path, required_id):
    service, _, _, _ = stack
    standin = NativeStandIn(tmp_path, monkeypatch)
    service.native = native.NativeProviders()
    sent = record_sends(monkeypatch)
    connection = add(service, name="Device login")   # the real capability probe proves the isolated device flow
    home = native.account_home(connection)
    attempt = service.start_login(connection["id"])
    awaiting = wait_until(lambda: (lambda s: s if s["state"] == "awaiting_browser" else None)(service.login_status(attempt["id"])))
    assert awaiting and awaiting["url"] == "https://auth.openai.com/codex/device" and awaiting["user_code"] == "WXYZ-1234"
    server_pid = [r for r in standin.records() if r.get("argv") == ["app-server", "--listen", "stdio://"] and r.get("home") == str(home)][-1]["pid"]
    grandchild = standin.wait_for(lambda r: "grandchild" in r and r["pid"] == server_pid)[0]["grandchild"]
    assert proc_probe.is_alive(server_pid) and proc_probe.is_alive(grandchild)
    assert sent[-1] == {"id": 2, "method": "account/login/start", "params": {"type": "chatgptDeviceCode"}}
    cancelling = service.login_status(attempt["id"], cancel=True)
    assert cancelling["state"] == "cancelling"
    thread = service.logins[attempt["id"]]["thread"]
    thread.join(20)
    assert not thread.is_alive(), "the login thread did not finish after cancel"
    final = service.login_status(attempt["id"])
    assert final["state"] == "cancelled" and "url" not in final and "user_code" not in final
    assert any(v.get("method") == "account/login/cancel" and v.get("params") == {"loginId": "standin-login"} for v in sent)
    wait_dead(server_pid)
    wait_dead(grandchild)
    assert "WXYZ-1234" not in json.dumps(service.snapshot()) and "auth.openai.com" not in json.dumps(service.snapshot())
    assert [p for p in home.rglob("*") if p.is_file()] == [], "the cancelled login left a file in the isolated home"
    retry = service.start_login(connection["id"])
    assert retry["id"] != attempt["id"] and retry["state"] in ("starting", "awaiting_browser")
    try:
        assert wait_until(lambda: service.login_status(retry["id"])["state"] == "awaiting_browser")
    finally:
        service.login_status(retry["id"], cancel=True)
        service.logins[retry["id"]]["thread"].join(20)
    assert service.login_status(retry["id"])["state"] == "cancelled"
    assert [p for p in home.rglob("*") if p.is_file()] == []


@required("invalid-settings-do-not-overwrite")
def test_invalid_settings_do_not_overwrite(server, monkeypatch, required_id):
    import job_runner
    origin, (service, _, _, _) = server
    named = add(service, name="Named")
    service.snapshot(True)
    opener = authenticated(origin)
    monkeypatch.setattr(setup.provider_secrets, "available", lambda: True)
    monkeypatch.setattr(setup.provider_secrets, "put", lambda identity, secret: pytest.fail("the vault was written on invalid settings"))
    monkeypatch.setattr(setup, "validate_api", lambda family, secret: None)
    valid = settings.settings_path().read_bytes()
    document = json.loads(valid)
    revision = document["settings_revision"]
    prefs = deepcopy(document["provider_preferences"])
    prefs["warning_threshold"] = 30
    leaky = {**metadata.new_connection("chatgpt", "Leaky"), "api_key": "never-stored-by-a-settings-entry"}
    corruptions = {
        "malformed JSON": b'{"default_cli": "claude",',
        "unknown default_cli": json.dumps({**document, "default_cli": "excel"}).encode("utf-8"),
        "account of another family": json.dumps({**document, "provider_preferences": {**document["provider_preferences"],
                                                                                        "accounts": {"claude": named["id"]}}}).encode("utf-8"),
        "secret-like connection field": json.dumps({**document, "provider_connections": document["provider_connections"] + [leaky]}).encode("utf-8"),
    }
    posts = [("/api/provider-setup/apply", {"preferences": prefs, "expected_revision": revision}),
             ("/api/provider-setup/accounts", {"family": "chatgpt", "name": "Another", "mode": "subscription", "expected_revision": revision}),
             ("/api/provider-setup/rename", {"connection_id": named["id"], "name": "Renamed", "expected_revision": revision}),
             ("/api/provider-setup/initialize", {"expected_revision": revision}),
             ("/api/provider-setup/api-key", {"connection_id": named["id"], "api_key": "x" * 24})]
    jobs = job_runner.jobs_dir()
    for label, corrupt in corruptions.items():
        settings.settings_path().write_bytes(corrupt)
        mirror = settings.mirror_path().read_bytes()
        records = sorted(jobs.glob("*.json")) if jobs.exists() else []
        status, body = http_request(opener, origin, "/api/provider-setup")
        assert status == 200, (label, body)
        snapshot = json.loads(body)
        assert snapshot["settings_error"] and "invalid" in snapshot["settings_error"], label
        assert [c["id"] for c in snapshot["connections"]] == [c["id"] for c in metadata.default_connections()], label
        assert "never-stored" not in body and "excel" not in body, label   # R4-C: the display read echoes nothing from the bad document
        for path, payload in posts:
            status, body = http_request(opener, origin, path, payload)
            assert status in (400, 409), (label, path, status, body)
            assert "never-stored" not in body and "excel" not in body, (label, path)
        with pytest.raises(settings.SettingsInvalid):
            settings.get_launch_settings()
        with pytest.raises(settings.SettingsInvalid):
            job_runner.launch("research", backend="claude")
        assert (sorted(jobs.glob("*.json")) if jobs.exists() else []) == records, label
        assert settings.settings_path().read_bytes() == corrupt and settings.mirror_path().read_bytes() == mirror, label
    settings.settings_path().write_bytes(valid)
    assert settings.get_launch_settings()["settings_revision"] == revision
    mirror = settings.mirror_path().read_bytes()
    status, body = http_request(opener, origin, "/api/provider-setup/apply", {"preferences": prefs, "expected_revision": revision + 7})
    assert status == 409 and json.loads(body) == {"ok": False, "error": "Settings changed or are invalid; reload before saving"}
    assert settings.settings_path().read_bytes() == valid and settings.mirror_path().read_bytes() == mirror
    assert settings.load_settings()["provider_preferences"]["warning_threshold"] == document["provider_preferences"]["warning_threshold"]


@required("credentials-not-in-responses-or-artifacts")
def test_credentials_not_in_responses_or_artifacts(server, monkeypatch, tmp_path, required_id):
    import anchor_gui
    import job_runner
    import report_viewer
    import usage_capture
    from steward_cockpit import steward_engine, steward_routes
    origin, (service, _, data, home) = server
    sentinels = {name: f"{name}-credential-canary-{uuid.uuid4().hex[:10]}"
                 for name in ("isolated", "codex-home", "claude-home", "environment", "vault", "stderr", "native-error", "vault-failure", "vault-write")}
    standin = NativeStandIn(tmp_path, monkeypatch, families=("chatgpt", "claude"))
    standin.set_mode(stderr=sentinels["stderr"])
    planted = {home / ".codex" / "auth.json": sentinels["codex-home"], home / ".claude" / ".credentials.json": sentinels["claude-home"]}
    for path, token in planted.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(token, encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", sentinels["environment"])
    monkeypatch.setenv("ANTHROPIC_API_KEY", sentinels["environment"])
    vault = {}
    monkeypatch.setattr(setup.provider_secrets, "available", lambda: True)
    monkeypatch.setattr(setup.provider_secrets, "get", lambda identity: vault.get(identity, sentinels["vault"]))
    monkeypatch.setattr(setup.provider_secrets, "put", lambda identity, secret: vault.__setitem__(identity, secret))
    monkeypatch.setattr(setup, "validate_api", lambda family, secret: None)
    service.native = native.NativeProviders()
    opener = authenticated(origin)
    bodies = []

    def get(path):
        status, body = http_request(opener, origin, path)
        bodies.append((path, body))
        return status, body

    def post(path, payload):
        status, body = http_request(opener, origin, path, payload)
        bodies.append((path, body))
        return status, body

    def revision():
        return json.loads(get("/api/provider-setup")[1])["settings_revision"]

    # Every provider route, success paths first (through the real adapter + stand-ins).
    status, body = post("/api/provider-setup/accounts", {"family": "chatgpt", "name": "Enrolling", "mode": "subscription", "expected_revision": revision()})
    assert status == 200, body
    enrolling = metadata.find_connection(settings.load_settings(), json.loads(body)["connection_id"])
    status, body = post("/api/provider-setup/accounts", {"family": "chatgpt", "name": "Cancelling", "mode": "subscription", "expected_revision": revision()})
    assert status == 200, body
    cancelling = metadata.find_connection(settings.load_settings(), json.loads(body)["connection_id"])
    status, body = post("/api/provider-setup/accounts", {"family": "claude", "name": "Keyed", "mode": "api", "expected_revision": revision()})
    assert status == 200, body
    keyed = metadata.find_connection(settings.load_settings(), json.loads(body)["connection_id"])
    status, body = get("/api/provider-setup?refresh=1")
    assert status == 200
    fresh = json.loads(body)
    assert row(fresh, "chatgpt-default")["auth"] == "signed_in" and row(fresh, "claude-default")["auth"] == "signed_in"
    assert row(fresh, enrolling["id"])["auth"] == "signed_out" and row(fresh, keyed["id"])["auth"] == "api_key"
    for path in ("/api/provider-setup", "/setup", "/setup/install", "/api/provider-setup/login?id=" + "f" * 32):
        get(path)
    assert post("/api/provider-setup/rename", {"connection_id": enrolling["id"], "name": "Enrolling account", "expected_revision": revision()})[0] == 200
    prefs = deepcopy(fresh["preferences"])
    prefs["warning_threshold"] = 35
    assert post("/api/provider-setup/apply", {"preferences": prefs, "expected_revision": revision()})[0] == 200
    assert post("/api/provider-setup/initialize", {"expected_revision": revision()})[0] == 200
    status, body = post("/api/provider-setup/api-key", {"connection_id": keyed["id"], "api_key": sentinels["vault-write"]})
    assert status == 200 and vault == {keyed["id"]: sentinels["vault-write"]}
    # Failure paths: refused actions, a native error message, a vault read
    # failure, a raised NativeError and a vault write failure.
    for path, payload in (("/api/provider-setup/accounts", {"family": "chatgpt", "name": "X", "expected_revision": revision(), "api_key": "forbidden"}),
                          ("/api/provider-setup/rename", {"connection_id": "e" * 32, "name": "X", "expected_revision": revision()}),
                          ("/api/provider-setup/apply", {"preferences": {**prefs, "family": "grok"}, "expected_revision": revision()}),
                          ("/api/provider-setup/login", {"connection_id": "chatgpt-default"}),
                          ("/api/provider-setup/cancel", {"id": "e" * 32}),
                          ("/api/provider-setup/api-key", {"connection_id": enrolling["id"], "api_key": "x" * 24})):
        status, body = post(path, payload)
        assert status == 400 and json.loads(body)["ok"] is False, (path, body)
    standin.set_mode(stderr=sentinels["stderr"], error=sentinels["native-error"])
    status, body = get("/api/provider-setup?refresh=1&connection_id=chatgpt-default")
    assert status == 200 and row(json.loads(body), "chatgpt-default")["auth"] == "error"
    standin.set_mode(stderr=sentinels["stderr"])
    with monkeypatch.context() as patch:
        def failing_get(identity):
            raise OSError(sentinels["vault-failure"])
        patch.setattr(setup.provider_secrets, "get", failing_get)
        status, body = get("/api/provider-setup?refresh=1&connection_id=" + keyed["id"])
        assert status == 200 and row(json.loads(body), keyed["id"])["auth"] == "error"
    with monkeypatch.context() as patch:
        def native_failure(family, secret):
            raise native.NativeError("error")
        patch.setattr(setup, "validate_api", native_failure)
        status, body = post("/api/provider-setup/api-key", {"connection_id": keyed["id"], "api_key": "y" * 24})
        assert status == 400 and json.loads(body) == {"ok": False, "error": GENERIC_ERROR}
    with monkeypatch.context() as patch:
        def failing_put(identity, secret):
            raise RuntimeError(sentinels["vault-write"] + " " + secret)
        patch.setattr(setup.provider_secrets, "put", failing_put)
        status, body = post("/api/provider-setup/api-key", {"connection_id": keyed["id"], "api_key": "z" * 24})
        assert status == 400 and json.loads(body) == {"ok": False, "error": GENERIC_ERROR}
    # A completed device login (the stand-in saves the isolated credential) and a cancelled one.
    standin.set_mode(stderr=sentinels["stderr"], login="complete", credential=sentinels["isolated"])
    status, body = post("/api/provider-setup/login", {"connection_id": enrolling["id"]})
    assert status == 200, body
    attempt = json.loads(body)
    def poll(identity, states):
        def read():
            status, body = get("/api/provider-setup/login?id=" + identity)
            assert status == 200, body
            value = json.loads(body)
            return value if value["state"] in states else None
        return wait_until(read, 30)
    completed = poll(attempt["id"], ("completed", "failed", "cancelled"))
    assert completed and completed["state"] == "completed", completed
    assert "url" not in completed and "user_code" not in completed
    isolated = native.account_home(enrolling) / "auth.json"
    assert isolated.read_text(encoding="utf-8") == sentinels["isolated"]
    planted[isolated] = sentinels["isolated"]
    standin.set_mode(stderr=sentinels["stderr"])
    status, body = post("/api/provider-setup/login", {"connection_id": cancelling["id"]})
    assert status == 200, body
    attempt = json.loads(body)
    assert poll(attempt["id"], ("awaiting_browser",))
    assert post("/api/provider-setup/cancel", {"id": attempt["id"]})[0] == 200
    cancelled = poll(attempt["id"], ("cancelled", "failed", "completed"))
    assert cancelled and cancelled["state"] == "cancelled" and "url" not in cancelled and "user_code" not in cancelled
    status, body = get("/api/provider-setup?refresh=1&connection_id=" + enrolling["id"])
    assert status == 200 and row(json.loads(body), enrolling["id"])["auth"] == "signed_in"
    # Artifact and project-file routes over registered folders that enclose the
    # native homes (the user's home) and the isolated store (the data dir).
    folders = {"h": str(home), "d": str(data)}
    monkeypatch.setattr(anchor_gui, "_ecgberht_project_folder", lambda pid: (folders[pid], None, 200) if pid in folders else (None, {"ok": False, "error": "Unknown project"}, 404))
    monkeypatch.setattr(anchor_gui._rnd, "get_project", lambda pid: {"id": pid, "folder_path": folders[pid]} if pid in folders else None)
    for path in planted:
        pid, root = ("h", home) if path.resolve().is_relative_to(home.resolve()) else ("d", data)
        rel = path.resolve().relative_to(root.resolve()).as_posix()
        for route in (f"/artifact/{pid}?path=", f"/artifact/{pid}/", f"/api/rnd/project_file_content?project_id={pid}&path=",
                      f"/api/ecgberht/artifact?project_id={pid}&rel=", f"/api/ecgberht/chamber_artifact?project_id={pid}&rel="):
            status, body = get(route + quote(rel, safe="/"))
            assert status in (403, 404), (route, rel, status)
        status, body = get(f"/api/rnd/project_files?project_id={pid}&path=" + quote(Path(rel).parent.as_posix(), safe="/"))
        assert status == 403, (rel, status, body)
        assert report_viewer.resolve_project_artifact(str(root), rel) is None, rel
        result, code = steward_routes.handle_get(str(root), "deliverable-file", {"path": rel})
        bodies.append(("deliverable-file " + rel, json.dumps(result)))
        assert code == 403, rel
    for pid in folders:
        status, body = get(f"/report/{pid}/research/{'a' * 32}")
        assert status == 200
    # The engine state file, its spawn environment, the usage ledger, a job record and the settings files.
    monkeypatch.setattr(steward_engine, "STATE_FILE", tmp_path / "engines.json")
    directory = tmp_path / "conversation"
    directory.mkdir()
    engine = steward_engine.Engine(str(directory), fake=True)
    with monkeypatch.context() as patch:
        patch.setattr(importlib.util, "spec_from_file_location", lambda *a, **kw: None)
        spawn_env = engine._spawn_env()
    assert "ANTHROPIC_API_KEY" not in spawn_env and "OPENAI_API_KEY" not in spawn_env
    assert all(sentinels["environment"] not in str(value) for value in spawn_env.values())
    for connection in (enrolling, keyed, metadata.find_connection(settings.load_settings(), "claude-default")):
        assert all(sentinels["environment"] not in str(value) for value in native.account_env(connection).values())
    assert engine._retain_native_session({"cli": "claude", "session_id": "state-session", "provider_connection": engine.provider_connection})
    usage_capture.ingest_usage("hardening-session", "row-1", source=usage_capture.SOURCE_STEWARD_TURN, native_id="1", tokens=12,
                               cli="chatgpt", provider_connection_id=enrolling["id"])
    assert setup.observed_tokens(enrolling["id"])["tokens"] == 12
    canary = tmp_path / "native_env_canary.py"
    canary.write_text("import json, os\nprint(json.dumps({'home': os.getenv('CLAUDE_CONFIG_DIR'), 'account': os.getenv('ANCHOR_PROVIDER_CONNECTION'), "
                      "'api': bool(os.getenv('ANTHROPIC_API_KEY')), 'openai': bool(os.getenv('OPENAI_API_KEY'))}))\n", encoding="utf-8")
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"{Path(sys.executable).as_posix()} {canary.as_posix()}")
    record = job_runner.launch("research", backend="claude", env={"ANTHROPIC_API_KEY": sentinels["environment"]})
    final = job_runner.wait(record["job_id"], timeout=20)
    assert final["status"] == job_runner.STATUS_DONE and record["provider_connection"]["id"] == "claude-default"
    observed = json.loads(Path(final["log_path"]).read_text(encoding="utf-8"))
    assert observed["api"] is False and observed["openai"] is False and observed["account"] == "claude-default"
    # No sentinel anywhere: every response, every file under the data and home
    # trees (the planted credentials excepted), the engine state and the job record.
    leaks = [(name, where) for where, body in bodies for name, token in sentinels.items() if token in body]
    assert leaks == [], leaks
    skip = {p.resolve() for p in planted} | {standin.root.resolve()}
    for root in (data, home, tmp_path / "engines.json", Path(final["log_path"]).parent):
        for path in ([root] if root.is_file() else root.rglob("*")):
            if not path.is_file() or path.resolve() in skip or any(parent in skip for parent in path.resolve().parents):
                continue
            text = path.read_bytes().decode("utf-8", "replace")
            for name, token in sentinels.items():
                assert token not in text, (name, str(path.relative_to(tmp_path)))
    assert settings.load_settings()["provider_preferences"]["warning_threshold"] == 35


@required("account-selection-preserves-running-conversation")
def test_account_selection_preserves_running_conversation(server, monkeypatch, tmp_path, required_id):
    from playwright.sync_api import expect, sync_playwright
    from steward_cockpit import steward_engine
    origin, (service, backend, _, _) = server
    a, b = add(service, family="claude", name="Account A"), add(service, family="claude", name="Account B")
    backend.signed.update({a["id"], b["id"]})
    service.snapshot(True)
    prefs = deepcopy(service.snapshot()["preferences"])
    prefs.update(family="claude")
    prefs["accounts"]["claude"] = a["id"]
    service.apply({"preferences": prefs, "expected_revision": settings.load_settings()["settings_revision"]})
    monkeypatch.setattr(steward_engine, "STATE_FILE", tmp_path / "engines.json")
    directory = tmp_path / "conversation"
    directory.mkdir()
    selection = {"family": "claude", "model": "frontier", "effort": "high", "selection_evidence": "explicit_setup_choice"}
    queue = ["Finish the ledger note once the figures arrive"]
    steward_engine._update_state(str(directory), {"cli": "claude", "session_id": "owned-session", "provider_connection": a,
                                                  "model_policy": selection, "pending_queue": list(queue)})
    engine = steward_engine.Engine(str(directory), fake=True)
    engine.session_id, engine.proc = "owned-session", SimpleNamespace(poll=lambda: None)
    assert engine.queue == queue and engine.provider_connection == a
    home_a = str(native.account_home(a))

    def spawn_env():
        with monkeypatch.context() as patch:
            patch.setattr(importlib.util, "spec_from_file_location", lambda *a, **kw: None)
            return engine._spawn_env()

    opener = authenticated(origin)

    def select(family, identity):
        status, body = http_request(opener, origin, "/api/provider-setup")
        current = json.loads(body)
        chosen = deepcopy(current["preferences"])
        chosen["family"] = family
        chosen["accounts"][family] = identity
        status, body = http_request(opener, origin, "/api/provider-setup/apply", {"preferences": chosen, "expected_revision": current["settings_revision"]})
        assert status == 200, body
        assert json.loads(body)["preferences"]["accounts"][family] == identity

    def bound(label):
        assert engine._desired_policy()[1] == "claude", label
        env = spawn_env()
        assert env["CLAUDE_CONFIG_DIR"] == home_a and env["ANCHOR_PROVIDER_CONNECTION"] == a["id"], label
        assert (engine.provider_connection, engine.model_selection, engine.session_id, engine.queue) == (a, selection, "owned-session", queue), label
        assert engine._account_policy_kwargs("claude")["env"]["CLAUDE_CONFIG_DIR"] == home_a, label
        entry = steward_engine._read_state_entry(str(directory))
        assert entry["provider_connection"] == a and entry["session_id"] == "owned-session" and entry["pending_queue"] == queue, label
        assert engine._retain_native_session(entry), label
        archive = steward_engine._read_state_entry(str(directory))["provider_sessions"]
        assert archive[-1]["provider_connection"]["id"] == a["id"] and archive[-1]["session_id"] == "owned-session", label
        assert all(r["provider_connection"]["id"] == a["id"] for r in archive), label

    bound("before any change")
    select("claude", b["id"])
    bound("account B of the same family selected")
    new_b = tmp_path / "new-conversation-b"
    new_b.mkdir()
    fresh = steward_engine.Engine(str(new_b), fake=True)
    assert fresh.provider_connection["id"] == b["id"] and fresh._desired_policy()[1] == "claude" and fresh.session_id is None
    assert native.account_env(fresh.provider_connection)["CLAUDE_CONFIG_DIR"] == str(native.account_home(b))
    select("chatgpt", "chatgpt-default")
    bound("another family selected")
    new_other = tmp_path / "new-conversation-chatgpt"
    new_other.mkdir()
    other = steward_engine.Engine(str(new_other), fake=True)
    assert other.provider_connection["id"] == "chatgpt-default" and other._desired_policy()[1] == "chatgpt"
    # In the browser: the Cave keeps its composer draft and its selected-but-
    # unsaved controls across a provider state reload.
    cave_context(monkeypatch)
    draft = "Keep this unfinished Cave draft across the provider reload"
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context(viewport={"width": 1440, "height": 1050})
            browser_login(context, origin)
            page, errors, launched, streams = guarded_page(context)
            page.goto(origin + "/high-seat")
            expect(page.locator("#cave-family")).to_have_value("chatgpt")
            expect(page.locator("#cave-account")).to_have_value("chatgpt-default")
            say = page.locator("#say")
            expect(say).to_be_visible()
            say.fill(draft)
            page.locator("#cave-family").select_option("claude")
            expect(page.locator("#cave-account")).to_have_value(b["id"])
            page.locator("#cave-account").select_option(a["id"])
            page.locator("#cave-model").select_option("balanced")
            page.locator("#cave-effort").select_option("high")
            # A provider state reload (the page's own visibility hook) re-fetches
            # the state and re-renders the controls: the old option nodes are
            # gone, yet the unsaved draft choices and the composer text survive.
            page.evaluate("() => { document.querySelector('#cave-account option')._before_reload = true; }")
            with page.expect_response(lambda r: r.url.endswith("/api/provider-setup") and r.status == 200):
                page.evaluate("() => document.dispatchEvent(new Event('visibilitychange'))")
            assert wait_until(lambda: not page.evaluate("() => !!document.querySelector('#cave-account option')._before_reload"), 10), \
                "the reload did not re-render the provider controls"
            expect(page.locator("#cave-provider-message")).to_contain_text("conversations keep their source")
            expect(page.locator("#cave-family")).to_have_value("claude")
            expect(page.locator("#cave-account")).to_have_value(a["id"])
            expect(page.locator("#cave-model")).to_have_value("balanced")
            expect(page.locator("#cave-effort")).to_have_value("high")
            expect(say).to_have_value(draft)
            assert not errors and not launched, (errors, launched)
            assert all("/setup" not in frame for _, frame in streams)
        finally:
            browser.close()
    saved = service.snapshot()["preferences"]
    assert saved["family"] == "chatgpt" and saved["accounts"] == {"claude": b["id"], "chatgpt": "chatgpt-default"}
    bound("after the browser reload")


class BlockedBackend(NativeFixture):
    """Every native observe blocks until released (a pass-through set keeps
    chosen connections answering); a login waits for its cancel."""
    def __init__(self):
        super().__init__()
        self.release, self.entered, self.lock, self.passing = threading.Event(), [], threading.Lock(), set()

    def observe(self, connection):
        with self.lock:
            self.entered.append(connection["id"])
        if connection["id"] not in self.passing:
            assert self.release.wait(60), "Test left a native observe blocked"
        if connection["id"] in self.passing:
            return super().observe(connection)
        raise native.NativeError("timeout")

    def login(self, connection, cancel, progress):
        self.login_started.set()
        progress({"state": "awaiting_browser", "url": "https://auth.openai.com/codex/device", "user_code": "DEMO-1234",
                  "message": "Native device login on host"})
        assert cancel.wait(60), "Test left an uncancelled native login"
        raise native.NativeError("cancelled")


@required("cached-state-does-not-wait-for-refresh")
def test_cached_state_does_not_wait_for_refresh(server, monkeypatch, required_id):
    origin, (service, _, _, _) = server
    first, second = add(service, name="First"), add(service, name="Second")
    service.snapshot(True)
    cave_context(monkeypatch)
    opener = authenticated(origin)
    assert http_request(opener, origin, "/high-seat")[0] == 200   # warm the page route before timing it
    blocked = BlockedBackend()
    service.native = blocked
    blocked.passing.add(first["id"])
    pending = service.start_login(first["id"])   # its pre-login status read passes; its native login waits for cancel
    assert wait_until(lambda: service.login_status(pending["id"])["state"] == "awaiting_browser")
    status, body = http_request(opener, origin, "/api/provider-setup")
    assert status == 200
    before = public_rows(json.loads(body))
    current = settings.load_settings()
    refresh_worker, refresh_result = start_refresh_request(origin)
    login_worker, login_result = {}, {}
    def start_second():
        login_opener = authenticated(origin)
        try:
            login_result["status"], login_result["body"] = http_request(login_opener, origin, "/api/provider-setup/login", {"connection_id": second["id"]})
        except Exception as exc:  # surfaced by the caller's assertions
            login_result["error"] = repr(exc)
    login_worker = threading.Thread(target=start_second, name="hardening-start-login")
    login_worker.start()
    try:
        # Three native reads are now blocked: the refresh pool's two workers
        # (claude-default, chatgpt-default) and the second account's pre-login read.
        assert wait_until(lambda: {"claude-default", "chatgpt-default", second["id"]} <= set(blocked.entered), 10), blocked.entered
        assert refresh_worker.is_alive() and login_worker.is_alive()
        entered = len(blocked.entered)
        answered = {}
        for path in ("/api/provider-setup", "/high-seat", "/api/provider-setup/login?id=" + pending["id"]):
            answered[path] = timed_get(opener, origin, path, 1)
            assert refresh_worker.is_alive() and login_worker.is_alive(), "the cached read did not overlap the blocked native work"
        status, body, _ = answered["/api/provider-setup"]
        assert status == 200 and public_rows(json.loads(body)) == before
        status, page, _ = answered["/high-seat"]
        assert status == 200 and 'id="cave-provider-controls"' in page
        status, body, _ = answered["/api/provider-setup/login?id=" + pending["id"]]
        assert status == 200 and json.loads(body)["state"] == "awaiting_browser"
        connection = metadata.find_connection(current, first["id"])
        for label, call in (("require_capacity_choice", lambda: setup.require_capacity_choice(current, connection)),
                            ("selected_for_launch", lambda: setup.selected_for_launch(current, "claude", check_capacity=True)),
                            ("resolve_quality", lambda: setup.resolve_quality("claude", current, metadata.find_connection(current, "claude-default")))):
            started = time.monotonic()
            value = call()
            assert time.monotonic() - started < 1, label
            assert refresh_worker.is_alive() and login_worker.is_alive(), label
            if label != "require_capacity_choice":
                assert value, label
        assert (setup.resolve_quality("claude", current, metadata.find_connection(current, "claude-default"))["model"],
                setup.selected_for_launch(current, "claude", check_capacity=True)["id"]) == ("frontier", "claude-default")
        assert len(blocked.entered) == entered, "a cached read or a launch-time check issued a native read"
        for name, lock in (("AccountUsageReader", service.usage.lock), ("service", service.lock)):
            acquired = lock.acquire(timeout=1)
            if acquired:
                lock.release()
            assert acquired, name + " lock is held by blocked native work"
        assert "status" not in refresh_result and "status" not in login_result
    finally:
        blocked.passing.add(second["id"])
        blocked.release.set()
        refresh_worker.join(30)
        login_worker.join(30)
    assert not refresh_worker.is_alive() and not login_worker.is_alive()
    assert refresh_result.get("status") == 200, refresh_result
    published = row(json.loads(refresh_result["body"]), "chatgpt-default")
    assert published["auth"] == "timeout" and published["test"] == "failed"
    assert published["allowance"] == {**before["chatgpt-default"]["allowance"], "state": "stale", "attempted_at": published["attempted_at"], "error": "timeout"}
    assert public_rows(service.snapshot())["chatgpt-default"]["allowance"] == published["allowance"]
    assert login_result.get("status") == 200, login_result
    started = json.loads(login_result["body"])
    assert started["connection_id"] == second["id"] and started["state"] in ("starting", "awaiting_browser")
    try:
        assert wait_until(lambda: service.login_status(started["id"])["state"] == "awaiting_browser")
    finally:
        for identity in (pending["id"], started["id"]):
            service.login_status(identity, cancel=True)
            service.logins[identity]["thread"].join(20)
    assert {service.login_status(identity)["state"] for identity in (pending["id"], started["id"])} == {"cancelled"}


# -- findings raised by the independent Wave-1 panel (two fresh Grok seats, driver-run) ---------------------------

def test_r0a_retained_claude_window_survives_a_vanished_signal_as_stale(stack):
    """R0-A (Grok seat 0, MAJOR; driver-reproduced): a SUCCESSFUL refresh must not drop a retained Claude
    window when the account-qualified rate-limit signal has gone; it stays, labelled stale."""
    import usage_capacity
    service, _, _, _ = stack
    jobs = Path(usage_capacity.jobs_dir())
    jobs.mkdir(parents=True, exist_ok=True)
    event = {"type": "rate_limit_event", "rate_limit_info": {"unifiedWindows": {"five_hour": {"utilization": .4, "resetsAt": time.time() + 3600}}}}
    (jobs / "claude-run.log").write_text(json.dumps(event), encoding="utf-8")
    (jobs / "claude-run.json").write_text(json.dumps({"provider_connection": {"id": "claude-default"}}), encoding="utf-8")
    connection = metadata.find_connection(settings.load_settings(), "claude-default")
    service.refresh(connection)
    first = row(service.snapshot(), "claude-default")["allowance"]
    assert first["state"] == "fresh" and len(first["windows"]) == 1
    (jobs / "claude-run.log").unlink()
    (jobs / "claude-run.json").unlink()
    service.refresh(connection)
    report = row(service.snapshot(), "claude-default")
    second = report["allowance"]
    assert second["state"] == "stale" and second["error"] == "unsupported"
    assert second["windows"] == first["windows"] and second["observed_at"] == first["observed_at"]
    assert report["capacity"] == "unknown" and report["auth"] == "signed_in"


def test_r0b_account_env_never_inherits_another_familys_grok_home(stack, monkeypatch):
    """R0-B (Grok seat 0, MINOR; driver-reproduced): GROK_HOME from the process environment must not ride
    into a Claude or ChatGPT connection's native environment; the Grok family keeps its own home."""
    service, _, data, _ = stack
    monkeypatch.setenv("GROK_HOME", str(data / "someone-elses-grok-home"))
    named = add(service, family="claude")
    for identity in ("claude-default", "chatgpt-default", named["id"]):
        env = native.account_env(metadata.find_connection(settings.load_settings(), identity))
        assert "GROK_HOME" not in env, identity
    assert native.account_env(metadata.find_connection(settings.load_settings(), "grok-default"))["GROK_HOME"] == os.environ["GROK_HOME"]
    # R3-C: the Grok redirect is one documented home — honoured by account_home and private to every artifact route.
    grok_home = Path(os.environ["GROK_HOME"])
    grok_home.mkdir(parents=True, exist_ok=True)
    assert native.account_home(metadata.find_connection(settings.load_settings(), "grok-default")) == grok_home
    assert native.private_account_path(grok_home / "credentials.json")
    assert not native.private_account_path(data / "ordinary-project" / "notes.md")


def test_r1b_failed_capability_probe_is_retried_on_explicit_refresh(stack, monkeypatch):
    """R1-B (Grok seat 1, MINOR): a transient capability-probe failure is not served from the cache for the
    whole TTL on an explicit refresh; the next refresh re-probes, so adding an account recovers at once."""
    service, backend, _, _ = stack
    calls = []

    def flaky(family):
        calls.append(family)
        if len(calls) == 1:
            raise native.NativeError("timeout")
        return NativeFixture.capabilities(backend, family)

    monkeypatch.setattr(backend, "capabilities", flaky)
    first = service.capability("chatgpt", True)
    assert first["state"] == "error" and not first["isolated"] and calls == ["chatgpt"]
    assert service.capability("chatgpt")["state"] == "error" and len(calls) == 1   # a plain read is still served from the cache
    second = service.capability("chatgpt", True)
    assert second["state"] == "available" and second["isolated"] and len(calls) == 2
    assert add(service)["family"] == "chatgpt" and len(calls) == 2
    assert service.capability("chatgpt", True)["state"] == "available" and len(calls) == 2   # a good probe stays cached for the TTL
    # R5-A (confirmation seat 1): a missing CLI is cached as "unavailable"; installing it mid-TTL must be seen by an explicit refresh.
    service.capabilities.clear()
    absent = {"installed": False, "state": "unavailable", "version": None, "isolated": False, "login": None}
    probes = iter([absent, NativeFixture.capabilities(backend, "chatgpt")])
    monkeypatch.setattr(backend, "capabilities", lambda family: next(probes))
    assert service.capability("chatgpt", True)["state"] == "unavailable"
    assert service.capability("chatgpt")["state"] == "unavailable"   # a plain read keeps the cached answer
    assert service.capability("chatgpt", True)["state"] == "available" and service.capability("chatgpt", True)["isolated"]


def test_r2a_cancel_reap_is_bounded_when_the_native_child_ignores_the_cancel(stack, monkeypatch, tmp_path):
    """R2-A (engine Grok reviewer, Wave 2, MINOR): the account/login/cancel RPC carries its own short deadline,
    so a wedged native child cannot hold the cancelled login (and its process tree) for the 300 s login timeout."""
    service, _, _, _ = stack
    standin = NativeStandIn(tmp_path, monkeypatch)
    standin.set_mode(ignore_cancel=True)
    service.native = native.NativeProviders()
    sent = record_sends(monkeypatch)
    connection = add(service, name="Wedged cancel")
    home = native.account_home(connection)
    attempt = service.start_login(connection["id"])
    assert wait_until(lambda: service.login_status(attempt["id"])["state"] == "awaiting_browser")
    server_pid = [r for r in standin.records() if r.get("argv") == ["app-server", "--listen", "stdio://"] and r.get("home") == str(home)][-1]["pid"]
    grandchild = standin.wait_for(lambda r: "grandchild" in r and r["pid"] == server_pid)[0]["grandchild"]
    assert proc_probe.is_alive(server_pid) and proc_probe.is_alive(grandchild)
    started = time.monotonic()
    cancelling = service.login_status(attempt["id"], cancel=True)
    assert cancelling["state"] == "cancelling" and "url" not in cancelling and "user_code" not in cancelling   # R6-C
    thread = service.logins[attempt["id"]]["thread"]
    thread.join(native.CANCEL_TIMEOUT + 15)
    assert not thread.is_alive(), "a native child that ignored the cancel held the login thread"
    assert time.monotonic() - started < native.CANCEL_TIMEOUT + 15
    assert service.login_status(attempt["id"])["state"] == "cancelled"
    wait_dead(server_pid)
    wait_dead(grandchild)   # R3-F
    assert any(v.get("method") == "account/login/cancel" and v.get("params") == {"loginId": "standin-login"} for v in sent)   # R4-D
    assert [p for p in home.rglob("*") if p.is_file()] == []


def test_r3a_failed_probe_on_an_isolated_account_is_reported_as_its_failure_not_unsupported(stack, monkeypatch):
    """R3-A (Grok seat 1, Wave-2 re-review): a capability probe that times out on an isolated account must surface as
    `timeout` with the prior figures retained stale, never as `unsupported` (which means the CLI answered and refused)."""
    service, backend, _, _ = stack
    account = add(service)
    backend.signed.add(account["id"])
    service.refresh(account)
    before = row(service.snapshot(), account["id"])
    assert before["auth"] == "signed_in" and before["allowance"]["state"] == "fresh"
    def hung(family):
        raise native.NativeError("timeout")
    monkeypatch.setattr(backend, "capabilities", hung)
    service.capabilities.clear()   # the cached good probe has expired
    service.refresh(account)
    after = row(service.snapshot(), account["id"])
    assert after["auth"] == "timeout" and after["test"] == "failed", after["auth"]
    assert after["allowance"] == {**before["allowance"], "state": "stale", "attempted_at": after["attempted_at"], "error": "timeout"}
    assert after["capability"]["state"] == "error" and after["capability"]["error"] == "timeout"


def test_r4a_claude_signal_without_a_finite_window_is_no_report_and_never_goes_stale(stack):
    """R4-A (Grok seat 0, Wave-2 re-review): an account-qualified rate_limit_event whose windows carry no finite
    utilization is no report — it gets no observation time, and a later failed refresh cannot relabel it stale."""
    import usage_capacity
    service, backend, _, _ = stack
    jobs = Path(usage_capacity.jobs_dir())
    jobs.mkdir(parents=True, exist_ok=True)
    event = {"type": "rate_limit_event", "rate_limit_info": {"unifiedWindows": {"five_hour": {"utilization": "not-a-number", "resetsAt": time.time() + 3600}}}}
    (jobs / "claude-odd.log").write_text(json.dumps(event), encoding="utf-8")
    (jobs / "claude-odd.json").write_text(json.dumps({"provider_connection": {"id": "claude-default"}}), encoding="utf-8")
    connection = metadata.find_connection(settings.load_settings(), "claude-default")
    service.refresh(connection)
    first = row(service.snapshot(), "claude-default")["allowance"]
    assert first["state"] == "unsupported" and first["windows"] == [] and first["observed_at"] is None
    backend.failed["claude-default"] = "timeout"
    service.refresh(connection)
    after = row(service.snapshot(), "claude-default")
    assert after["auth"] == "timeout" and after["allowance"]["state"] == "timeout" and after["allowance"]["observed_at"] is None
    assert after["capacity"] == "unknown"


def test_r4b_catalog_discovery_failure_never_fails_a_stored_refresh(stack, monkeypatch):
    """R4-B (Grok seat 0, Wave-2 re-review): an OSError from catalog discovery (a spawn failure) after the
    observation is stored must not escape refresh — the sign-in state stays published and the catalog is
    reported unavailable."""
    import model_policy
    service, _, _, _ = stack
    def spawn_failure(family, **kwargs):
        raise OSError("spawn failed")
    monkeypatch.setattr(model_policy, "discover", spawn_failure)
    connection = metadata.find_connection(settings.load_settings(), "chatgpt-default")
    service.refresh(connection)   # must not raise
    report = row(service.snapshot(), "chatgpt-default")
    assert report["auth"] == "signed_in" and report["allowance"]["state"] == "fresh"
    assert report["catalog"]["state"] == "unavailable" and report["catalog"]["rows"] == []


def test_r6a_spawned_children_never_inherit_another_familys_home(stack, monkeypatch, tmp_path):
    """R6-A (confirmation seat 0): the engine's and the job runner's spawn environments start from the process
    environment; a home key account_env removed (another family's home) must not survive into the child."""
    import job_runner
    from steward_cockpit import steward_engine
    service, backend, data, _ = stack
    monkeypatch.setenv("CODEX_HOME", str(data / "parent-codex-home"))
    monkeypatch.setenv("GROK_HOME", str(data / "parent-grok-home"))
    account = add(service, family="claude", name="Spawn home")
    backend.signed.add(account["id"])
    service.snapshot(True)
    prefs = deepcopy(service.snapshot()["preferences"])
    prefs.update(family="claude")
    prefs["accounts"]["claude"] = account["id"]
    service.apply({"preferences": prefs, "expected_revision": settings.load_settings()["settings_revision"]})
    monkeypatch.setattr(steward_engine, "STATE_FILE", tmp_path / "engines.json")
    engine = steward_engine.Engine(str(tmp_path / "conversation"), fake=True)
    with monkeypatch.context() as patch:
        patch.setattr(importlib.util, "spec_from_file_location", lambda *a, **kw: None)
        env = engine._spawn_env()
    assert env["CLAUDE_CONFIG_DIR"] == str(native.account_home(account)) and env["ANCHOR_PROVIDER_CONNECTION"] == account["id"]
    assert "CODEX_HOME" not in env and "GROK_HOME" not in env
    canary = tmp_path / "home_canary.py"
    canary.write_text("import json, os\nprint(json.dumps({k: os.getenv(k) for k in ('CLAUDE_CONFIG_DIR', 'CODEX_HOME', 'GROK_HOME', 'ANCHOR_PROVIDER_CONNECTION')}))\n", encoding="utf-8")
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"{Path(sys.executable).as_posix()} {canary.as_posix()}")
    record = job_runner.launch("research", backend="claude", env={"CODEX_HOME": "wrong-family-home", "GROK_HOME": "wrong-family-home"})
    final = job_runner.wait(record["job_id"], timeout=15)
    observed = json.loads(Path(final["log_path"]).read_text(encoding="utf-8"))
    assert observed == {"CLAUDE_CONFIG_DIR": str(native.account_home(account)), "CODEX_HOME": None, "GROK_HOME": None,
                        "ANCHOR_PROVIDER_CONNECTION": account["id"]}


def test_r6b_a_status_read_that_answers_expired_after_login_is_a_failed_sign_in(stack, monkeypatch):
    """R6-B (confirmation seat 0): after a native login returns, a follow-up read that ANSWERED (expired, so
    test failed without a read error) is a failed sign-in; only a read that could not be made is reported as
    completed-with-caveat (H6)."""
    service, backend, _, _ = stack
    connection = add(service)
    def login(connection_, cancel, progress):
        progress({"state": "awaiting_browser", "url": "https://auth.openai.com/codex/device", "user_code": "DEMO-1234"})
    monkeypatch.setattr(backend, "login", login)
    observe = backend.observe
    def expired(connection_):
        out = observe(connection_)
        out.update(auth="expired", test="failed")
        return out
    monkeypatch.setattr(backend, "observe", expired)
    attempt = service.start_login(connection["id"])
    service.logins[attempt["id"]]["thread"].join(10)
    final = service.login_status(attempt["id"])
    assert final["state"] == "failed" and "url" not in final and "user_code" not in final
    assert row(service.snapshot(), connection["id"])["auth"] == "expired"


def test_r6e_project_file_listings_never_name_credential_files(server, monkeypatch, tmp_path):
    """R6-E (confirmation seat 0): the recursive and plain project-files listings skip private credential homes,
    so a project rooted at the user home lists neither the Codex nor the Claude credential file."""
    import anchor_gui
    origin, (service, _, data, home) = server
    (home / ".codex").mkdir(exist_ok=True)
    (home / ".codex" / "auth.json").write_text("listing-canary", encoding="utf-8")
    (home / ".claude").mkdir(exist_ok=True)
    (home / ".claude" / ".credentials.json").write_text("listing-canary", encoding="utf-8")
    (home / "notes.md").write_text("ordinary project material", encoding="utf-8")
    monkeypatch.setattr(anchor_gui._rnd, "get_project", lambda pid: {"id": pid, "folder_path": str(home)})
    opener = authenticated(origin)
    for query in ("&path=.&recursive=true", "&path=.", "&path=.codex&recursive=true", "&path=.codex"):
        status, body = http_request(opener, origin, "/api/rnd/project_files?project_id=p" + query)
        assert status in (200, 403), (query, status, body)
        assert "auth.json" not in body and ".credentials.json" not in body and ".codex" not in body and ".claude" not in body, (query, body[:300])
    status, body = http_request(opener, origin, "/api/rnd/project_files?project_id=p&path=.&recursive=true")
    assert status == 200 and "notes.md" in body
