"""Regressions for each retained provider and exact native-run review finding."""
from pathlib import Path

import pytest

from shell import connect


@pytest.mark.parametrize("override,reason", [
    ("http://remote-host.tailnet.test", "https"),
    ("https://user:password@remote-host.tailnet.test", "embedded credentials"),
    ("https://user@remote-host.tailnet.test", "embedded credentials"),
    ("https://@remote-host.tailnet.test", "embedded credentials"),
    ("https://:@remote-host.tailnet.test", "embedded credentials"),
    ("https://remote-host.tailnet.test:invalid", "invalid"),
    ("ftp://remote-host.tailnet.test", "address"),
])
def test_command_line_override_rejects_invalid_address_before_network(tmp_path, monkeypatch, override, reason):
    calls = []
    monkeypatch.setattr(connect, "reachable", lambda *a, **kw: calls.append(a))
    monkeypatch.setattr(connect.urllib.request, "urlopen", lambda *a, **kw: pytest.fail("Invalid override made a network request"))
    with pytest.raises(ValueError, match=reason):
        connect.choose(tmp_path, override)
    assert not calls


@pytest.mark.parametrize("override,expected", [
    ("https://remote-host.tailnet.test/static/app.html?view=setup", "https://remote-host.tailnet.test"),
    ("remote-host.tailnet.test/path", "https://remote-host.tailnet.test"),
    ("http://127.0.0.1:8777/static/app.html", "http://127.0.0.1:8777"),
    ("http://localhost:8777/", "http://localhost:8777"),
    ("http://[::1]:8777/", "http://[::1]:8777"),
])
def test_command_line_override_uses_typed_address_normalization(tmp_path, override, expected):
    assert connect.choose(tmp_path, override) == expected


def test_executable_rejects_invalid_url_before_window_or_probe(tmp_path, monkeypatch, capsys):
    import ctypes
    import importlib.util
    import sys
    from types import SimpleNamespace

    class Dll:
        def __init__(self):
            self.functions = {}
        def __getattr__(self, name):
            return self.functions.setdefault(name, SimpleNamespace())

    monkeypatch.setattr(ctypes, "WinDLL", lambda *a, **kw: Dll(), raising=False)
    monkeypatch.setattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE, raising=False)
    source = Path(__file__).resolve().parents[1] / "shell" / "anchor_shell.py"
    spec = importlib.util.spec_from_file_location("review_followup_executable", source)
    executable = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(executable)
    monkeypatch.setitem(sys.modules, "connect", connect)
    monkeypatch.setattr(executable, "DATA", tmp_path)
    monkeypatch.setattr(executable, "ensure_shortcut", lambda: pytest.fail("Invalid override initialized the window"))
    monkeypatch.setattr(connect, "reachable", lambda *a, **kw: pytest.fail("Invalid override probed the address"))
    with pytest.raises(SystemExit) as error:
        executable.main(["--url", "http://remote-host.tailnet.test"])
    assert error.value.code == 2
    assert "Invalid --url" in capsys.readouterr().err


from copy import deepcopy
import json
from urllib.request import build_opener

import anchor_settings as settings
import provider_setup as setup
from tests.test_provider_setup import (
    stack, server, add, row, authenticated, http_request,
)
from tests.test_provider_setup_browser import cave_server


@pytest.mark.parametrize("action", [
    "initialize", "accounts", "rename", "remove", "apply", "login", "cancel", "api-key",
])
def test_query_bearing_provider_mutations_reach_the_real_action(server, monkeypatch, action):
    origin, (service, backend, _, _) = server
    opener = authenticated(origin)
    account = None
    vault, validated = {}, []
    if action in ("rename", "remove", "apply", "login", "cancel", "api-key"):
        account = add(service, mode="api" if action == "api-key" else "subscription")
    revision = settings.load_settings()["settings_revision"]
    body = {"expected_revision": revision}
    if action == "accounts":
        body.update(family="chatgpt", name="Query account", mode="subscription")
    elif action == "rename":
        body.update(connection_id=account["id"], name="Renamed through query")
    elif action == "remove":
        body.update(connection_id=account["id"])
    elif action == "apply":
        backend.signed.add(account["id"])
        service.refresh(account)
        preferences = deepcopy(service.snapshot()["preferences"])
        preferences["family"] = "chatgpt"
        preferences["accounts"]["chatgpt"] = account["id"]
        body["preferences"] = preferences
    elif action == "login":
        body = {"connection_id": account["id"]}
    elif action == "cancel":
        attempt = service.start_login(account["id"])
        assert backend.login_started.wait(2)
        body = {"id": attempt["id"]}
    elif action == "api-key":
        monkeypatch.setattr(setup.provider_secrets, "available", lambda: True)
        monkeypatch.setattr(setup.provider_secrets, "put", lambda identity, value: vault.update({identity: value}))
        monkeypatch.setattr(setup.provider_secrets, "get", lambda identity: vault.get(identity))
        monkeypatch.setattr(setup, "validate_api", lambda family, value: validated.append((family, value)))
        body = {"connection_id": account["id"], "api_key": "query-vault-disposable-canary"}
    try:
        code, raw = http_request(opener, origin, "/api/provider-setup/" + action + "?view=setup&context=retained-review", body)
        assert code == 200, raw
        result = json.loads(raw)
        assert result["ok"]
        if action == "initialize":
            assert result["host"]["configured"]
        elif action == "accounts":
            assert row(result["snapshot"], result["connection_id"])["name"] == "Query account"
        elif action == "rename":
            assert row(result, account["id"])["name"] == "Renamed through query"
        elif action == "remove":
            assert account["id"] not in {c["id"] for c in result["connections"]}
        elif action == "apply":
            assert result["preferences"] == preferences
            assert setup.selected_for_launch(settings.load_settings(), "chatgpt")["id"] == account["id"]
        elif action == "login":
            assert backend.login_started.wait(2)
            assert result["connection_id"] == account["id"] and result["id"] in service.logins
        elif action == "cancel":
            service.logins[attempt["id"]]["thread"].join(5)
            assert service.login_status(attempt["id"])["state"] == "cancelled"
        else:
            assert vault == {account["id"]: body["api_key"]}
            assert validated and validated[0] == ("chatgpt", body["api_key"])
            assert body["api_key"] not in raw
            assert not row(result, account["id"])["execution"]["ready"]
    finally:
        for attempt in list(service.logins.values()):
            attempt["cancel"].set()
            attempt["thread"].join(5)
            assert not attempt["thread"].is_alive()


@pytest.mark.parametrize("action", [
    "initialize", "accounts", "rename", "remove", "apply", "login", "cancel", "api-key",
])
def test_query_bearing_provider_mutations_keep_normal_authorization(server, action):
    origin, (service, _, _, _) = server
    before = settings.settings_path().read_bytes()
    path = "/api/provider-setup/" + action + "?view=setup"
    assert http_request(build_opener(), origin, path, {})[0] in (401, 403)
    opener = authenticated(origin)
    assert http_request(opener, origin, path, {}, {
        "Sec-Fetch-Site": "cross-site", "Origin": "https://elsewhere.invalid",
    })[0] == 403
    assert settings.settings_path().read_bytes() == before and not service.logins


def test_query_bearing_api_key_keeps_host_only_secret_entry(server, monkeypatch):
    origin, _ = server
    writes = []
    monkeypatch.setattr(setup.provider_secrets, "put", lambda *args: writes.append(args))
    code, raw = http_request(authenticated(origin), origin, "/api/provider-setup/api-key?view=setup",
                             {"api_key": "query-host-only-canary"},
                             {"X-Forwarded-For": "100.64.0.10"})
    assert code == 403 and not writes
    assert "query-host-only-canary" not in raw

from tests.test_status_code_job_eta import (
    effort as surface_effort, compose as surface_compose,
    save_record as surface_save_record, write_json as surface_write_json,
)


def test_native_worker_and_exact_run_are_composed_for_the_status_surface(surface_effort):
    root, worktree, record, now = surface_effort
    record["worker"] = "foreman"
    surface_save_record(surface_effort)
    status = surface_compose(surface_effort)
    assert status["running"]["skill"] == "Foreman"
    assert status["running"]["worker"] == "foreman"
    assert status["running"]["job_id"] == "job-1"
    assert status["running"]["phase"] == "execute"
    assert "Foreman" in status["running"]["label"]
    assert "execute" in status["running"]["label"]
    assert "Foreman" in next(f["value"] for f in status["compact"]["facts"] if f["label"] == "Doing")
    assert status["evidence"]["eta"]["job_id"] == "job-1"
    record["steward_dir"] = str(root.parent / "another-effort")
    surface_save_record(surface_effort)
    assert surface_compose(surface_effort)["running"]["kind"] != "code_job"


def test_next_steps_retains_exact_foreman_run_through_horizon_and_status_repaint(cave_server, surface_effort):
    """Only a fresh fixture browser is driven; both soft-wake GETs and work POSTs are intercepted."""
    import json
    from pathlib import Path
    from urllib.parse import urlsplit
    from playwright.sync_api import expect, sync_playwright
    from steward_cockpit import steward_campaign as campaign
    from tests.test_provider_setup import AUTH

    origin, _, _ = cave_server
    root, worktree, record, now = surface_effort
    record["worker"] = "foreman"
    surface_save_record(surface_effort)
    initial = surface_compose(surface_effort)
    initial["status_id"] = "surface-0001"
    checkpoint = json.loads((worktree / "foreman-checkpoint.json").read_text())
    checkpoint["intra_wave_step"] = "review"
    surface_write_json(worktree / "foreman-checkpoint.json", checkpoint, now)
    reviewing = surface_compose(surface_effort)
    reviewing["status_id"] = "surface-0002"
    record["status"] = "done"
    surface_save_record(surface_effort)
    finished = surface_compose(surface_effort)
    finished["status_id"] = "surface-0003"
    current_map = campaign.read_map(str(root))
    state = {"alive": False, "busy": False, "stamp": current_map["stamp"]}
    pending, guarded, starts, errors = [], [], [], []
    static = Path(__file__).resolve().parents[1] / "steward_cockpit" / "static"

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context(viewport={"width": 1440, "height": 1050})
            login = context.request.post(origin + "/api/auth/login", data={"token": AUTH})
            assert login.ok and any(c.get("httpOnly") for c in context.cookies(origin))
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))

            def guard(route):
                request = route.request
                path = urlsplit(request.url).path
                if request.method == "POST":
                    guarded.append(path)
                    if not path.endswith("status-ack"):
                        starts.append(path)
                    route.abort()
                elif path == "/steward/v1":
                    route.fulfill(path=str(static / "v1.html"))
                elif path.startswith("/static/") and (static / Path(path).name).is_file():
                    route.fulfill(path=str(static / Path(path).name))
                elif path in ("/api/events", "/api/steward/events"):
                    guarded.append(path)
                    if pending:
                        route.fulfill(json={"events": pending[:], "state": state})
                        pending.clear()
                    else:
                        route.abort()
                elif path == "/api/status":
                    route.fulfill(json=initial)
                elif path == "/api/map":
                    route.fulfill(json=current_map)
                elif path == "/api/history":
                    route.fulfill(json={"turns": []})
                elif path == "/api/deliverables":
                    route.fulfill(json={"items": [], "roots": []})
                elif path == "/api/state":
                    route.fulfill(json=state)
                elif path.startswith("/api/"):
                    route.abort()
                else:
                    route.continue_()

            page.route("**/*", guard)
            page.goto(origin + "/steward/v1?dir=surface-fixture")
            doing = page.locator('.blk.status.latest [data-status-fact="doing"]')
            expect(doing).to_contain_text("Foreman")
            expect(doing).to_contain_text("execute")
            tile = page.locator("[data-delivmount] .blk.next")
            tile.locator(".who").click()
            tag = tile.locator("[data-run-tag]")
            expect(tag).to_be_visible()
            expect(tag).to_have_text("Foreman run job-1 \u00b7 execute")
            assert tag.get_attribute("data-job-id") == "job-1"
            tag.evaluate("e=>e._runIdentity='preserved'")
            draft = page.locator("[data-say]")
            draft.fill("Keep this unfinished draft")
            draft.evaluate("e=>e._draftIdentity='preserved'")

            with page.expect_request(lambda req: urlsplit(req.url).path == "/api/map", timeout=10000):
                current_map["stamp"] = "surface-horizon-refreshed"
                current_map["next_in_plan"] = [{"id": "review", "name": "Review isolated accounts"}]
                state["stamp"] = current_map["stamp"]
            expect(tile).to_contain_text("Review isolated accounts")
            expect(tag).to_have_text("Foreman run job-1 \u00b7 execute")
            assert tag.evaluate("e=>e._runIdentity") == "preserved"

            pending.append({"t": "status", "seq": 1, "status": reviewing})
            expect(tag).to_have_text("Foreman run job-1 \u00b7 review", timeout=10000)
            expect(doing).to_contain_text("review")
            with page.expect_request(lambda req: "/api/events?since=2" in req.url, timeout=10000):
                pending.append({"t": "status", "seq": 2, "status": initial})
            expect(tag).to_have_text("Foreman run job-1 \u00b7 review")
            assert tag.evaluate("e=>e._runIdentity") == "preserved"
            assert tile.locator(".body").evaluate(
                "e=>e.lastElementChild.hasAttribute('data-run-tag')")

            pending.append({"t": "status", "seq": 3, "status": finished})
            expect(tag).to_have_count(0, timeout=10000)
            expect(page.locator('.blk.status.latest [data-status-fact="eta"]')).not_to_contain_text("Provisional")
            expect(draft).to_have_value("Keep this unfinished draft")
            assert draft.evaluate("e=>e._draftIdentity") == "preserved"
            assert page.locator(".blk.status.latest tr").count() == 10
            assert not errors and not starts
            assert "/api/events" in guarded
        finally:
            browser.close()

import json
import os
import time

from steward_cockpit import steward_campaign as followup_campaign
from tests.test_status_code_job_eta import (
    effort as status_effort, compose as status_compose,
    save_record as status_save_record, write_json as status_write_json,
)


@pytest.mark.parametrize("state", ["done", "failed", "paused", "budget_stopped"])
def test_complete_large_native_checkpoint_clears_lagging_owner_forecast(status_effort, state):
    _, worktree, _, now = status_effort
    plan = worktree / ".foreman-job" / "IMPLEMENTATION-PLAN.md"
    plan.write_text("# Code job job-1 - Implementation Plan\n" + "Retained plan detail.\n" * 2000, encoding="utf-8")
    os.utime(plan, (now - 600, now - 600))
    checkpoint = json.loads((worktree / "foreman-checkpoint.json").read_text())
    checkpoint.update(status=state, open_findings=[{"message": "Retained finding " * 2000}])
    status_write_json(worktree / "foreman-checkpoint.json", checkpoint, now)
    assert (worktree / "foreman-checkpoint.json").stat().st_size > 20000
    status = status_compose(status_effort)
    assert status["evidence"]["eta"]["state"] == "unavailable"
    assert "Provisional" not in status["eta"]
    assert followup_campaign.running_code_jobs(str(status_effort[0]))[0]["native"]["stopped"]
    assert status["running"]["phase"] == state
    assert state in status["running"]["label"]


def test_complete_large_checkpoint_keeps_bound_phase_and_relative_plan_identity(status_effort):
    _, worktree, _, now = status_effort
    checkpoint = json.loads((worktree / "foreman-checkpoint.json").read_text())
    checkpoint.update(plan_path=".foreman-job/IMPLEMENTATION-PLAN.md", intra_wave_step="review",
                      open_findings=[{"message": "Retained review " * 2000}])
    status_write_json(worktree / "foreman-checkpoint.json", checkpoint, now)
    status = status_compose(status_effort)
    assert status["evidence"]["eta"]["phase"] == "review"
    assert status["running"]["skill"] == "Foreman"
    assert status["running"]["job_id"] == "job-1"
    checkpoint["plan_path"] = str(worktree.parent / "another-job" / ".foreman-job" / "IMPLEMENTATION-PLAN.md")
    status_write_json(worktree / "foreman-checkpoint.json", checkpoint, now)
    foreign = status_compose(status_effort)
    assert foreign["evidence"]["eta"]["phase"] == "build"
    assert foreign["running"]["skill"] == "coder"


def test_oversized_complete_checkpoint_is_explicitly_unavailable(status_effort):
    _, worktree, _, now = status_effort
    checkpoint = json.loads((worktree / "foreman-checkpoint.json").read_text())
    checkpoint.update(status="done", open_findings=["x" * (4 * 1024 * 1024)])
    status_write_json(worktree / "foreman-checkpoint.json", checkpoint, now)
    status = status_compose(status_effort)
    assert status["evidence"]["eta"]["state"] == "unavailable"
    assert "native checkpoint exceeds safe read limit" in status["eta"]
    assert "Provisional" not in status["eta"]


# Header and rows transcribed from the archived native 20261006-124717-187472
# run's 17:01 table. The periodic header has no t+ suffix. Only the
# observation's clock, owner, phase and supported pace value are varied below.
ARCHIVED_NATIVE_FOREMAN_TABLE = """[17:01:55] [17:01] Foreman build \u00b7 20261006-124717-187472
---------------------------------
Effort   IMPLEMENTATION-PLAN.md (1 waves)
Doing    wave 1 \u00b7 review (iter 0) \u00b7 waiting on agent:review 6m
Status   0/1 waves \u00b7 elapsed 10m
Tests    last verdict -
Blocker  none
Procs    agent_calls 0 \u00b7 est $0.00 (subscription equiv)
---------------------------------
ETA      estimating (no completed wave yet)
To do    waves 1..1
"""


def followup_native_table(status_effort, table_at, eta="~12m to run end (pace estimate)", owner="job-1"):
    _, worktree, record, now = status_effort
    record["started"] = table_at - 600
    status_save_record(status_effort)
    status_write_json(worktree / ".foreman" / "heartbeat.json",
                      {"alive": True, "startedAt": table_at - 600, "ts": now - 1}, now - 1)
    checkpoint = json.loads((worktree / "foreman-checkpoint.json").read_text())
    checkpoint["intra_wave_step"] = "review"
    status_write_json(worktree / "foreman-checkpoint.json", checkpoint, now - 1)
    clock = time.strftime("%H:%M", time.localtime(table_at))
    log = ARCHIVED_NATIVE_FOREMAN_TABLE.replace("17:01", clock).replace("20261006-124717-187472", owner)
    log = log.replace("estimating (no completed wave yet)", eta)
    log += f"[{time.strftime('%H:%M:%S', time.localtime(now))}] waiting on agent:review 29m\n"
    path = worktree / "_foreman-status.log"
    path.write_text(log, encoding="utf-8")
    os.utime(path, (now, now))
    return followup_campaign._job_epoch(time.strftime("%Y-%m-%d", time.localtime(table_at)) + "T" + clock + ":00")


def test_real_periodic_foreman_header_reads_current_pace(status_effort):
    parsed = followup_campaign.parse_status_table(ARCHIVED_NATIVE_FOREMAN_TABLE)
    assert parsed["head"] == {"at": "17:01", "title": "Foreman build \u00b7 20261006-124717-187472", "tick": ""}
    table_at = followup_native_table(status_effort, status_effort[3] - 10)
    status = status_compose(status_effort)
    evidence = status["evidence"]["eta"]
    assert evidence["native"] and evidence["phase"] == "review"
    assert evidence["estimated_at"] == table_at
    assert evidence["latest_at"] == table_at + 17 * 60
    assert status["running"]["native_source"] == "_foreman-status.log"
    assert "Unavailable" in status["tests"], "Native pace is not a test receipt"


@pytest.mark.parametrize("age, pace, reason", [
    (1800, "~40m to run end (pace estimate)", "stale"),
    (600, "~5m to run end (pace estimate)", "exceeded"),
    (24 * 3600 + 300, "~40m to run end (pace estimate)", "stale"),
])
def test_real_table_clock_expires_despite_fresh_waiting_lines(status_effort, age, pace, reason):
    table_at = followup_native_table(status_effort, status_effort[3] - age, eta=pace)
    native = followup_campaign.running_code_jobs(str(status_effort[0]))[0]["native"]
    assert native["estimates"][-1]["estimated_at"] == table_at
    status = status_compose(status_effort)
    assert not status["evidence"]["eta"]["native"]
    assert f"native estimate {reason}" in status["evidence"]["eta"]["qualification"]
    assert "rebased" in status["eta"]


def test_real_table_is_scoped_to_exact_job_and_plan(status_effort):
    followup_native_table(status_effort, status_effort[3] - 10, owner="another-job")
    assert not status_compose(status_effort)["evidence"]["eta"]["native"]
    _, worktree, _, now = status_effort
    followup_native_table(status_effort, now - 10)
    plan = worktree / ".foreman-job" / "IMPLEMENTATION-PLAN.md"
    plan.write_text("# Code job another-job - Implementation Plan\n" + "Foreign detail\n" * 2000, encoding="utf-8")
    os.utime(plan, (now - 600, now - 600))
    status = status_compose(status_effort)
    assert not status["evidence"]["eta"]["native"]
    assert status["running"]["skill"] == "coder"


def test_explicit_non_foreman_worker_keeps_its_identity(status_effort):
    _, _, record, _ = status_effort
    record["worker"] = "coder"
    status_save_record(status_effort)
    assert status_compose(status_effort)["running"]["skill"] == "coder"


from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import anchor_settings as settings
import model_policy
import provider_native as native
import provider_settings as metadata
import provider_setup as setup
from tests.test_provider_setup import stack, row

FOLLOWUP_DISCOVER = model_policy.discover


def followup_inherited_account_env(monkeypatch, tmp_path, identity="chatgpt-default"):
    # Match a check launched by an existing steward after dashboard preferences
    # change: its account marker and homes still belong to the parent process.
    inherited = {"ANCHOR_PROVIDER_CONNECTION": identity,
                 "CODEX_HOME": str(tmp_path / "parent-codex"),
                 "CLAUDE_CONFIG_DIR": str(tmp_path / "parent-claude"),
                 "GROK_HOME": str(tmp_path / "parent-grok"),
                 "OPENAI_API_KEY": "inherited-account-api-canary"}
    for key, value in inherited.items():
        monkeypatch.setenv(key, value)
    return inherited


def followup_assert_agy_binding(calls, inherited):
    catalogs = [env for argv, env in calls if argv == ["agy-fixture", "models"]]
    assert catalogs, "The selected account must reach native model discovery"
    for env in catalogs:
        assert env["ANCHOR_PROVIDER_CONNECTION"] == "gemini-default"
        assert not any(key in env for key in ("CODEX_HOME", "CLAUDE_CONFIG_DIR", "GROK_HOME"))
        assert not any(key.endswith("API_KEY") for key in env)
    assert {key: os.environ.get(key) for key in inherited} == inherited


def followup_agy_service(monkeypatch):
    calls = []
    monkeypatch.setattr(native, "executable", lambda family: "agy-fixture" if family == "gemini" else None)
    monkeypatch.setattr(model_policy.shutil, "which",
                        lambda name, **kwargs: "agy-fixture" if name.startswith("agy") else None)
    def command(argv, env, **kwargs):
        calls.append((argv, dict(env)))
        if argv == ["agy-fixture", "--version"]:
            return 0, "1.3.0"
        assert argv == ["agy-fixture", "models"]
        assert env["ANCHOR_PROVIDER_CONNECTION"] == "gemini-default"
        assert not any(key.endswith("API_KEY") for key in env)
        return 0, ("gemini-frontier-high\tGemini frontier\n"
                   "gemini-frontier-max\tGemini frontier\n"
                   "gemini-older-low\tGemini older\n")
    monkeypatch.setattr(native, "run_command", command)
    monkeypatch.setattr(model_policy, "discover",
                        lambda family, **kwargs: FOLLOWUP_DISCOVER(
                            family, env=kwargs.get("env"), runner=native.catalog_command))
    service = setup.ProviderService(native.NativeProviders())
    monkeypatch.setattr(setup, "SERVICE", service)
    return service, calls


def test_retained_agy_unknown_observation_can_apply_and_bind_new_work(stack, monkeypatch, tmp_path):
    from steward_cockpit import steward_engine
    inherited = followup_inherited_account_env(monkeypatch, tmp_path)
    service, calls = followup_agy_service(monkeypatch)
    monkeypatch.setattr(steward_engine, "STATE_FILE", tmp_path / "engines.json")
    directory = tmp_path / "retained-conversation"
    directory.mkdir()
    bound = metadata.find_connection(settings.load_settings(), "claude-default")
    steward_engine._update_state(str(directory), {"cli": "claude", "session_id": "owned-session",
                                                  "provider_connection": bound})
    existing = steward_engine.Engine(str(directory), fake=True)
    existing.session_id = "owned-session"
    existing.proc = SimpleNamespace(poll=lambda: None)
    new = steward_engine.Engine(str(tmp_path / "new-work"), fake=True)
    prefs = deepcopy(settings.load_settings()["provider_preferences"])
    prefs.update(family="gemini")
    prefs["quality"]["gemini"] = {"model": "latest_supported", "effort": "highest_supported"}
    result = service.apply({"preferences": prefs, "expected_revision": settings.load_settings()["settings_revision"]})
    report = row(result, "gemini-default")
    assert report["auth"] == "unknown" and report["test"] == "not_tested"
    assert report["allowance"]["state"] == "unsupported" and not report["allowance"]["windows"]
    assert report["execution"]["ready"] and "unreported" in report["execution"]["reason"]
    assert not report["capability"]["isolated"] and not report["capability"]["login"]
    assert not result["product_complete"]
    launch_settings, family = new._desired_policy()
    assert family == "gemini" and new.provider_connection["id"] == "gemini-default"
    selected_family, selected = new._select_available_policy(launch_settings, family)
    assert selected_family == "gemini" and selected["model"] == "gemini-frontier" and selected["effort"] == "max"
    assert model_policy.launch_args(selected) == ["--model", "gemini-frontier-max"]
    assert setup.resolve_quality("gemini", launch_settings, new.provider_connection)["effort"] == "max"
    assert existing._desired_policy()[1] == "claude" and existing.provider_connection == bound
    assert existing.session_id == "owned-session"
    assert calls[1][1]["ANCHOR_PROVIDER_CONNECTION"] == "gemini-default"
    assert all(argv in (["agy-fixture", "--version"], ["agy-fixture", "models"]) for argv, _ in calls)
    followup_assert_agy_binding(calls, inherited)


@pytest.mark.parametrize("failure", ["cli_missing", "auth_required", "capability_unavailable"])
def test_retained_agy_missing_prerequisite_cannot_apply(stack, monkeypatch, failure):
    service, _ = followup_agy_service(monkeypatch)
    def unavailable(*args, **kwargs):
        raise model_policy.PolicyUnavailable("gemini", "Native catalog unavailable", code=failure)
    monkeypatch.setattr(model_policy, "discover", unavailable)
    prefs = deepcopy(settings.load_settings()["provider_preferences"])
    prefs.update(family="gemini")
    before = settings.settings_path().read_bytes()
    with pytest.raises(ValueError, match="unready"):
        service.apply({"preferences": prefs, "expected_revision": settings.load_settings()["settings_revision"]})
    assert settings.settings_path().read_bytes() == before
    report = row(service.snapshot(), "gemini-default")
    assert not report["execution"]["ready"] and "incomplete" in report["execution"]["reason"]
    assert report["auth"] == "unknown" and report["catalog"]["state"] == "unavailable"


def test_agy_transient_catalog_keeps_bound_source_and_last_full_quality(stack, monkeypatch, tmp_path):
    from steward_cockpit import steward_engine
    inherited = followup_inherited_account_env(monkeypatch, tmp_path)
    service, calls = followup_agy_service(monkeypatch)
    connection = metadata.find_connection(settings.load_settings(), "gemini-default")
    service.refresh(connection)
    config = settings.load_settings()
    selection = setup.resolve_quality("gemini", config, connection)
    monkeypatch.setattr(steward_engine, "STATE_FILE", tmp_path / "bound-engines.json")
    directory = tmp_path / "agy-conversation"
    directory.mkdir()
    steward_engine._update_state(str(directory), {"cli": "gemini", "session_id": "owned-agy-session",
        "provider_connection": connection, "model_policy": selection})
    engine = steward_engine.Engine(str(directory), fake=True)
    engine.cli, engine.model_selection, engine.session_id = "gemini", selection, "owned-agy-session"
    engine.provider_connection = connection
    monkeypatch.setattr(model_policy, "cached_selection", lambda *args, **kwargs: None)
    requested = []
    monkeypatch.setattr(engine, "_refresh_catalog_async", lambda config: requested.append("gemini"))
    family, kept = engine._current_selection_uncapped(config, "gemini")
    assert family == "gemini" and kept == selection and kept["effort"] == "max"
    assert engine.provider_connection == connection and engine.session_id == "owned-agy-session"
    assert requested == ["gemini"]
    mismatched = deepcopy(config)
    mismatched["provider_preferences"]["accounts"]["gemini"] = "claude-default"
    with pytest.raises(ValueError, match="different provider"):
        setup.selected_for_launch(mismatched, "gemini")
    monkeypatch.setattr(native, "executable", lambda _: None)
    with pytest.raises(ValueError, match="unavailable"):
        setup.selected_for_launch(config, "gemini")
    followup_assert_agy_binding(calls, inherited)


def test_default_agy_selection_cache_and_background_refresh_use_bound_account(stack, monkeypatch, tmp_path):
    from steward_cockpit import steward_engine

    parent = metadata.new_connection("chatgpt", "Parent named account")
    config = settings.load_settings()
    settings.save_settings(provider_connections=config["provider_connections"] + [parent],
                           expected_revision=config["settings_revision"])
    inherited = followup_inherited_account_env(monkeypatch, tmp_path, identity=parent["id"])
    _, calls = followup_agy_service(monkeypatch)
    monkeypatch.setattr(model_policy, "_MEMORY", {})
    monkeypatch.setattr(steward_engine, "STATE_FILE", tmp_path / "default-agy-engines.json")
    config = settings.load_settings()
    saved = settings.settings_path().read_bytes()
    connection = metadata.find_connection(config, "gemini-default")
    directory = tmp_path / "default-agy-conversation"
    directory.mkdir()
    steward_engine._update_state(str(directory), {"cli": "gemini", "session_id": "owned-agy-session",
        "provider_connection": connection, "pending_queue": ["Keep this unsent turn"]})
    engine = steward_engine.Engine(str(directory), fake=True)
    engine.session_id = "owned-agy-session"
    assert engine.provider_quality is None and engine.provider_connection["native_default"]
    family, selection = engine._select_available_policy(config, "gemini")
    assert family == "gemini" and selection["model"] == "gemini-frontier" and selection["effort"] == "max"
    assert model_policy.launch_args(selection) == ["--model", "gemini-frontier-max"]
    engine.model_selection = selection
    cached_environments = []
    cached_selection = model_policy.cached_selection

    def qualified_cached_selection(family, **kwargs):
        cached_environments.append(dict(kwargs["env"]))
        return cached_selection(family, **kwargs)

    monkeypatch.setattr(model_policy, "cached_selection", qualified_cached_selection)
    before = len(calls)
    cached_family, cached = engine._current_selection_uncapped(config, "gemini")
    assert cached_family == "gemini" and cached == selection and len(calls) == before
    assert cached_environments[0]["ANCHOR_PROVIDER_CONNECTION"] == connection["id"]
    engine._refresh_catalog_async(config)
    engine._catalog_refresh_thread.join(5)
    assert not engine._catalog_refresh_thread.is_alive()
    assert len(calls) == before + 1 and calls[-1][0] == ["agy-fixture", "models"]
    assert engine.provider_connection == connection and engine.session_id == "owned-agy-session"
    assert engine.model_selection == selection and engine.model_selection["effort"] == "max"
    assert engine.queue == ["Keep this unsent turn"]
    retained = steward_engine._read_state_entry(str(directory))
    assert retained["session_id"] == "owned-agy-session" and retained["provider_connection"] == connection
    assert retained["pending_queue"] == engine.queue
    assert settings.settings_path().read_bytes() == saved
    followup_assert_agy_binding(calls, inherited)


def followup_grok_service(monkeypatch, connection, *, signed=True, wrong_home=False, transient=False):
    commands = []
    capability_calls = []
    target = str(native.account_home(connection))
    monkeypatch.setattr(native, "executable", lambda family: "grok-fixture" if family == "grok" else None)
    def command(argv, env, **kwargs):
        tail = argv[1:]
        commands.append((tail, dict(env)))
        if tail == ["--version"]: return 0, "3.0.0"
        if tail == ["--help"]: return 0, "  auth  Account commands\nGROK_HOME"
        if tail == ["auth", "--help"]: return 0, "  status  Account report\n  login  Browser enrollment"
        if tail == ["auth", "status", "--help"]: return 0, "--json"
        if tail == ["auth", "login", "--help"]: return 0, "--browser"
        assert tail == ["auth", "status", "--json"]
        home = env["GROK_HOME"]
        account_home = str(Path(home).parent) if wrong_home and home == target else home
        return 0, json.dumps({"loggedIn": signed if home == target else False,
                              "configDirectory": account_home, "billingMode": "subscription",
                              "email": "grok@example.test", "accessToken": "must-not-export"})
    class Backend(native.NativeProviders):
        def capabilities(self, family):
            capability_calls.append(family)
            if transient and capability_calls.count(family) > 1:
                raise native.NativeError("timeout")
            return super().capabilities(family)
    monkeypatch.setattr(native, "run_command", command)
    service = setup.ProviderService(Backend())
    monkeypatch.setattr(setup, "SERVICE", service)
    return service, commands, capability_calls


def followup_registered_grok():
    connection = metadata.new_connection("grok", "Retained isolated Grok")
    config = settings.load_settings()
    settings.save_settings(provider_connections=config["provider_connections"] + [connection],
                           expected_revision=config["settings_revision"])
    return connection


def test_grok_refresh_reuses_one_capability_probe_and_qualifies_account(stack, monkeypatch):
    connection = followup_registered_grok()
    service, commands, probes = followup_grok_service(monkeypatch, connection, transient=True)
    service.refresh(connection)
    report = row(service.snapshot(), connection["id"])
    assert probes == ["grok"]
    assert report["auth"] == "signed_in" and report["execution"]["ready"]
    status_homes = [env["GROK_HOME"] for tail, env in commands if tail == ["auth", "status", "--json"]]
    assert len(status_homes) == 2 and status_homes[0] != status_homes[1]
    assert status_homes[1] == str(native.account_home(connection))
    assert sum(tail == ["--help"] for tail, _ in commands) == 1
    assert sum(tail == ["auth", "status", "--help"] for tail, _ in commands) == 1
    assert "must-not-export" not in json.dumps(report)
    assert report["catalog"]["state"] == "fresh"


def test_grok_login_reuses_verified_capability_before_browser_enrollment(stack, monkeypatch):
    import threading

    connection = followup_registered_grok()
    service, commands, probes = followup_grok_service(monkeypatch, connection, signed=False, transient=True)
    native_command = native.run_command
    progress = []

    def command(argv, env, cancel=None, timeout=None, line_progress=None, **kwargs):
        if argv[1:] == ["auth", "login", "--browser"]:
            commands.append((argv[1:], dict(env)))
            assert env["GROK_HOME"] == str(native.account_home(connection))
            line_progress("https://grok.com/login")
            return 0, ""
        return native_command(argv, env, **kwargs)

    monkeypatch.setattr(native, "run_command", command)
    service.native.login(connection, threading.Event(), progress.append)
    assert probes == ["grok"]
    assert commands[-1][0] == ["auth", "login", "--browser"]
    status_homes = [env["GROK_HOME"] for tail, env in commands if tail == ["auth", "status", "--json"]]
    assert len(status_homes) == 2 and status_homes[0] != status_homes[1]
    assert status_homes[-1] == str(native.account_home(connection))
    assert progress[0]["state"] == "awaiting_browser"
    assert progress[0]["url"] == "https://grok.com/login"
    assert "must-not-export" not in json.dumps(progress)


def test_cold_grok_apply_reconciles_retained_account_and_new_work(stack, monkeypatch, tmp_path):
    from steward_cockpit import steward_engine
    connection = followup_registered_grok()
    prior, _, _ = followup_grok_service(monkeypatch, connection)
    prior.refresh(connection)
    assert row(prior.snapshot(), connection["id"])["execution"]["ready"]
    cold, commands, probes = followup_grok_service(monkeypatch, connection, transient=True)
    assert not row(cold.snapshot(), connection["id"])["execution"]["ready"]
    assert commands == [] and probes == []
    prefs = deepcopy(settings.load_settings()["provider_preferences"])
    prefs.update(family="grok")
    prefs["accounts"]["grok"] = connection["id"]
    applied = cold.apply({"preferences": prefs, "expected_revision": settings.load_settings()["settings_revision"]})
    assert row(applied, connection["id"])["execution"]["ready"]
    assert probes == ["grok"]
    monkeypatch.setattr(steward_engine, "STATE_FILE", tmp_path / "cold-engines.json")
    engine = steward_engine.Engine(str(tmp_path / "new-grok"), fake=True)
    assert engine._desired_policy()[1] == "grok" and engine.provider_connection == connection
    assert setup.selected_for_launch(settings.load_settings(), "grok") == connection
    assert probes == ["grok"]


@pytest.mark.parametrize("wrong_home,signed", [(False, True), (True, True), (False, False)])
def test_cold_isolated_grok_launch_reads_exact_native_account(stack, monkeypatch, wrong_home, signed):
    connection = followup_registered_grok()
    config = settings.load_settings()
    config["provider_preferences"]["accounts"]["grok"] = connection["id"]
    cold, commands, probes = followup_grok_service(monkeypatch, connection, wrong_home=wrong_home,
                                                  signed=signed, transient=True)
    if wrong_home or not signed:
        with pytest.raises(ValueError, match="authentication"):
            setup.selected_for_launch(config, "grok")
    else:
        assert setup.selected_for_launch(config, "grok") == connection
    assert probes == ["grok"]
    homes = [env["GROK_HOME"] for tail, env in commands if tail == ["auth", "status", "--json"]]
    assert len(homes) == 2 and homes[-1] == str(native.account_home(connection))


@pytest.mark.parametrize("family", ["gemini", "grok"])
def test_cold_native_choice_is_usable_in_cave_and_apply_verifies_before_new_work(cave_server, monkeypatch, tmp_path, family):
    from urllib.parse import urlsplit
    from playwright.sync_api import expect, sync_playwright
    from steward_cockpit import steward_engine
    from tests.test_provider_setup import AUTH

    origin, _, _ = cave_server
    if family == "gemini":
        inherited = followup_inherited_account_env(monkeypatch, tmp_path)
        service, commands = followup_agy_service(monkeypatch)
        connection = metadata.find_connection(settings.load_settings(), "gemini-default")
        probes = None
    else:
        connection = followup_registered_grok()
        prior, _, _ = followup_grok_service(monkeypatch, connection)
        prior.refresh(connection)
        assert row(prior.snapshot(), connection["id"])["execution"]["ready"]
        service, commands, probes = followup_grok_service(monkeypatch, connection, transient=True)
    assert not row(service.snapshot(), connection["id"])["execution"]["ready"]
    assert not commands
    monkeypatch.setattr(steward_engine, "STATE_FILE", tmp_path / "cave-new-work.json")
    pending = steward_engine.Engine(str(tmp_path / "pending-new-work"), fake=True)
    errors, forbidden, guarded_events = [], [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context(viewport={"width": 1440, "height": 1050})
            assert context.request.post(origin + "/api/auth/login", data={"token": AUTH}).ok
            assert any(c.get("httpOnly") for c in context.cookies(origin))
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            def guard(route):
                request = route.request
                path = urlsplit(request.url).path
                if path in ("/api/events", "/api/steward/events"):
                    guarded_events.append(path)
                    route.abort()
                elif request.method == "POST" and not path.startswith("/api/provider-setup/"):
                    if not path.endswith("status-ack"):
                        forbidden.append(path)
                    route.abort()
                else:
                    route.continue_()
            page.route("**/*", guard)
            page.goto(origin + "/high-seat")
            composer = page.locator("#say")
            expect(composer).to_be_visible()
            composer.fill("Keep this unfinished draft while applying a checked native account")
            composer.evaluate("e=>e._coldAccountIdentity='same composer'")
            family_control = page.locator("#cave-family")
            expect(family_control).to_be_visible()
            family_control.select_option(family)
            option = page.locator('#cave-account option[value="' + connection["id"] + '"]')
            expect(option).to_be_enabled()
            expect(option).to_contain_text("Apply verifies")
            assert not commands, "Cache-only Cave display must not probe the native CLI"
            assert not row(service.snapshot(), connection["id"])["execution"]["ready"]
            page.locator("#cave-account").select_option(connection["id"])
            page.locator("#cave-provider-apply").click()
            expect(page.locator("#cave-provider-message")).to_contain_text("Saved for new work")
            applied = row(service.snapshot(), connection["id"])
            assert applied["execution"]["ready"]
            assert setup.selected_for_launch(settings.load_settings(), family)["id"] == connection["id"]
            assert pending._desired_policy()[1] == family
            assert pending.provider_connection == connection and pending.session_id is None
            if family == "gemini":
                assert applied["auth"] == "unknown" and applied["test"] == "not_tested"
                assert applied["allowance"]["state"] == "unsupported"
                selected_family, selection = pending._select_available_policy(settings.load_settings(), family)
                assert selected_family == family and selection["effort"] == "max"
                followup_assert_agy_binding(commands, inherited)
            else:
                assert probes == ["grok"]
                assert pending._account_policy_kwargs(family)["env"]["GROK_HOME"] == str(native.account_home(connection))
            expect(composer).to_have_value("Keep this unfinished draft while applying a checked native account")
            assert composer.evaluate("e=>e._coldAccountIdentity") == "same composer"
            assert not errors and not forbidden
            assert guarded_events
        finally:
            browser.close()


def test_grok_transient_account_status_retains_identity_and_recovers_without_another_probe(stack, monkeypatch):
    connection = followup_registered_grok()
    service, commands, probes = followup_grok_service(monkeypatch, connection, transient=True)
    service.refresh(connection)
    before = row(service.snapshot(), connection["id"])
    saved = settings.settings_path().read_bytes()
    original = native.run_command
    def timeout_for_owned_status(argv, env, **kwargs):
        if argv[1:] == ["auth", "status", "--json"] and env["GROK_HOME"] == str(native.account_home(connection)):
            raise native.NativeError("timeout")
        return original(argv, env, **kwargs)
    monkeypatch.setattr(native, "run_command", timeout_for_owned_status)
    service.refresh(connection)
    failed = row(service.snapshot(), connection["id"])
    assert failed["auth"] == "timeout" and failed["test"] == "failed"
    assert not failed["execution"]["ready"]
    assert failed["account_identity"] == before["account_identity"]
    assert probes == ["grok"] and settings.settings_path().read_bytes() == saved
    monkeypatch.setattr(native, "run_command", original)
    service.refresh(connection)
    assert row(service.snapshot(), connection["id"])["execution"]["ready"]
    assert setup.selected_for_launch(settings.load_settings() | {
        "provider_preferences": {**settings.load_settings()["provider_preferences"],
                                 "accounts": {"grok": connection["id"]}},
    }, "grok") == connection
    assert probes == ["grok"] and settings.settings_path().read_bytes() == saved
