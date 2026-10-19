"""Wave 1 of the provider-integration assurance: rigor tests + reproduced findings.

Five required ids (one test each, bound as the test's pytest parameter id so the
gate's ``-v`` output names it literally) establish the behaviours the frozen
plan lists for this wave. Each reproduced finding (H1-H6 from the driver's
pre-read, W1-E1 from this review) was carried as a strict-xfail reproduction:
the body is the honest failing test, the marker is removed by the wave that
fixes it, and strict mode fails the gate the moment the code changes. Wave 2
landed every fix and removed the markers, so those tests are now the passing
proofs; each keeps its finding id in its name and docstring.

Every test runs against isolated temporary data/home directories, the ordinary
cookie login through the real server, and native commands substituted at their
documented interfaces (the ``NativeFixture`` backend, or counting stand-ins for
``provider_native.run_command``/``HiddenProcess``). Nothing touches the live
service, global preferences or a real credential.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import builtins
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sys
import threading
import time
from urllib.parse import quote
import warnings

import pytest

import anchor_settings as settings
import model_policy
import provider_native as native
import provider_settings as metadata
import provider_setup as setup
from tests.test_provider_setup import (AUTH, NativeFixture, stack, server, add, row,  # noqa: F401 (fixtures)
                                       authenticated, http_request)

REQUIRED_IDS = ("cached-read-during-native-refresh", "repeated-cached-page-load",
                "separate-account-allowance-attribution", "unsupported-is-not-usable",
                "failure-keeps-existing-session-and-quality")

# The genuine catalog discovery, captured before any fixture substitutes it.
REAL_DISCOVER = model_policy.discover


def required(identity):
    assert identity in REQUIRED_IDS
    return pytest.mark.parametrize("required_id", [pytest.param(identity, id=identity)])


class MeasurementRecord(UserWarning):
    """A measured figure, surfaced in the gate's warnings summary for the execution log."""


def measured(text):
    warnings.warn(MeasurementRecord(text), stacklevel=2)


class BlockedObserve:
    """Hold every native ``observe`` inside the backend until released.

    Entries are counted on ``backend.reads`` like the fixture's own reads, so a
    cached request that issued a native read would move the count.
    """
    def __init__(self, backend, failure="timeout"):
        self.backend, self.failure = backend, failure
        self.release, self.lock = threading.Event(), threading.Lock()
        self.entered, self.two_in_flight = 0, threading.Event()

    def __call__(self, connection):
        with self.lock:
            self.backend.reads.append((connection["id"], native.account_env(connection)))
            self.entered += 1
            if self.entered >= 2:
                self.two_in_flight.set()
        assert self.release.wait(60), "Test left a native observe blocked"
        raise native.NativeError(self.failure)


def timed_get(opener, origin, path, bound):
    started = time.monotonic()
    status, body = http_request(opener, origin, path)
    elapsed = time.monotonic() - started
    assert elapsed < bound, f"{path} took {elapsed:.2f}s (bound {bound}s)"
    return status, body, elapsed


def start_refresh_request(origin, path="/api/provider-setup?refresh=1"):
    """Issue the native refresh through the real server on a worker thread."""
    result, opener = {}, authenticated(origin)
    def request():
        try:
            result["status"], result["body"] = http_request(opener, origin, path)
        except Exception as exc:  # surfaced by the caller's assertions
            result["error"] = repr(exc)
    worker = threading.Thread(target=request, name="rigor-native-refresh")
    worker.start()
    return worker, result


def public_rows(snapshot):
    """The per-connection fields a cached read must serve unchanged."""
    return {c["id"]: {k: c[k] for k in ("auth", "allowance", "catalog", "capacity", "anchor_observed")}
            for c in snapshot["connections"]}


def guarded_page(context):
    """A page whose soft-wake streams and any unrelated work start are aborted."""
    page = context.new_page()
    errors, launched, streams = [], [], []
    page.on("pageerror", lambda error: errors.append(str(error)))
    def guard(route):
        req = route.request
        if re.search(r"/api/steward/(events|status-ack)", req.url):
            streams.append((req.url, req.frame.url))
            route.abort()
            return
        if ((req.method == "POST" and "/api/provider-setup/" not in req.url and "/api/auth/login" not in req.url)
                or re.search(r"/api/steward/(say|wake|start)", req.url)):
            launched.append((req.method, req.url))
            route.abort()
            return
        route.continue_()
    page.route("**/*", guard)
    return page, errors, launched, streams


def browser_login(context, origin):
    login = context.request.post(origin + "/api/auth/login", data={"token": AUTH})
    assert login.ok and any(cookie.get("httpOnly") for cookie in context.cookies(origin))


# ── required ids ──────────────────────────────────────────────────────────────


@required("cached-read-during-native-refresh")
def test_cached_read_during_native_refresh(server, monkeypatch, required_id):
    origin, (service, backend, _, _) = server
    service.snapshot(True)
    opener = authenticated(origin)
    status, body = http_request(opener, origin, "/api/provider-setup")
    assert status == 200
    before = public_rows(json.loads(body))
    assert before["chatgpt-default"]["allowance"]["windows"], "the pre-refresh state carries a fresh report"
    blocked = BlockedObserve(backend, "timeout")
    monkeypatch.setattr(backend, "observe", blocked)
    worker, result = start_refresh_request(origin)
    try:
        assert blocked.two_in_flight.wait(5), "the refresh never reached the native backend"
        reads = len(backend.reads)
        unknown_login = "/api/provider-setup/login?id=" + "f" * 32
        answered = {}
        for path in ("/api/provider-setup", "/setup", unknown_login):
            answered[path] = timed_get(opener, origin, path, 2)
            assert worker.is_alive(), "the cached read did not overlap the native refresh"
        status, body, _ = answered["/api/provider-setup"]
        assert status == 200 and public_rows(json.loads(body)) == before
        status, page, _ = answered["/setup"]
        assert status == 200 and 'id="setup-family"' in page
        status, body, _ = answered[unknown_login]
        assert status == 400 and json.loads(body) == {"ok": False, "error": "Host provider status is unavailable; existing setup is retained"}
        assert len(backend.reads) == reads, "a cached read issued a native read"
        assert "status" not in result, "the refresh completed while its native read was still blocked"
    finally:
        blocked.release.set()
        worker.join(30)
    assert not worker.is_alive() and result.get("status") == 200, result
    published = row(json.loads(result["body"]), "chatgpt-default")
    assert published["auth"] == "timeout" and published["test"] == "failed"
    assert published["allowance"] == {**before["chatgpt-default"]["allowance"], "state": "stale",
                                      "attempted_at": published["attempted_at"], "error": "timeout"}
    assert public_rows(service.snapshot())["chatgpt-default"]["allowance"] == published["allowance"]


class CountingChild:
    """A stand-in for ``provider_native.HiddenProcess`` speaking the app-server
    JSON-RPC protocol over an in-memory queue. One instance = one hidden process."""
    def __init__(self, counter, argv, env, *, timeout=native.COMMAND_TIMEOUT):
        counter.append(tuple(argv[1:]))
        self.env, self.lines = env, []

    def send(self, value):
        identity, method = value.get("id"), value.get("method")
        if identity is None:
            return
        if method == "account/read":
            probe = ".provider-schema-" in str(self.env.get("CODEX_HOME", ""))
            result = {"account": None if probe else {"type": "chatgpt"}}
        elif method == "account/rateLimits/read":
            result = {"rateLimits": {"primary": {"usedPercent": 10, "windowDurationMins": 300, "resetsAt": time.time() + 3600}}}
        elif method == "account/usage/read":
            result = {"summary": {"lifetimeTokens": 5}}
        else:
            result = {}
        self.lines.append(json.dumps({"id": identity, "result": result}) + "\n")

    def next(self, cancel=None, deadline=None):
        if not self.lines:
            raise native.NativeError()
        return "stdout", self.lines.pop(0)

    def close(self):
        pass


def counting_native_substrate(patch, commands):
    """All four native CLIs installed; every hidden command answers at its
    documented interface and is counted on ``commands`` (argv minus the binary)."""
    patch.setattr(native, "executable", lambda family: family + "-native-stub")
    patch.setattr(shutil, "which", lambda name, mode=os.F_OK | os.X_OK, path=None: name + "-stub")
    patch.setattr(model_policy, "discover", REAL_DISCOVER)
    catalog = json.dumps({"models": [{"slug": "gpt-5", "supported_reasoning_levels": ["low", "high"], "priority": 1}]})
    def run_command(argv, env, cancel=None, timeout=native.COMMAND_TIMEOUT, progress=None):
        tail = tuple(argv[1:])
        if tail[:2] == ("app-server", "generate-json-schema"):
            schema = {"oneOf": [{"properties": {"type": {"enum": ["chatgptDeviceCode"]}}}]}
            (Path(argv[-1]) / "LoginAccountParams.json").write_text(json.dumps(schema), encoding="utf-8")
            commands.append(tail[:3])
            return 0, ""
        commands.append(tail)
        if tail == ("--version",):
            return 0, "2.1.300\n"
        if tail == ("app-server", "--help"):
            return 0, "Usage: codex app-server --listen <addr>\n"
        if tail == ("auth", "login", "--help"):
            return 0, "claude auth login --claudeai\n"
        if tail == ("auth", "status"):
            return 0, json.dumps({"loggedIn": True, "authMethod": "claude.ai", "configDirectory": env.get("CLAUDE_CONFIG_DIR", "")})
        if tail == ("--help",):
            return 0, "  --effort <level>  Reasoning effort (low, medium, high)\n"
        if tail[:2] == ("debug", "models"):
            return 0, catalog
        if tail == ("models",):
            assert argv[0].startswith("agy") and env["ANCHOR_PROVIDER_CONNECTION"] == "gemini-default"
            return 0, "gemini-frontier-high\tGemini frontier\n"
        return 1, ""
    patch.setattr(native, "run_command", run_command)
    patch.setattr(native, "HiddenProcess", lambda argv, env, **kw: CountingChild(commands, argv, env, **kw))


@required("repeated-cached-page-load")
def test_repeated_cached_page_load(server, monkeypatch, required_id):
    origin, (service, backend, data, _) = server
    # (a) The causal mechanism behind a slow cold refresh: count the hidden
    # native commands a cold ``?refresh=1`` issues when all four CLIs are
    # installed, through the REAL adapter with counting stand-ins.
    commands = []
    with monkeypatch.context() as patch:
        counting_native_substrate(patch, commands)
        cold_snapshot = setup.ProviderService(native.NativeProviders()).snapshot(True)
    assert row(cold_snapshot, "chatgpt-default")["auth"] == "signed_in"
    assert row(cold_snapshot, "claude-default")["auth"] == "signed_in"
    assert row(cold_snapshot, "chatgpt-default")["capability"]["isolated"] is True
    agy = row(cold_snapshot, "gemini-default")
    assert agy["auth"] == "unknown" and agy["execution"]["ready"]
    assert agy["catalog"]["selection"] == {"model": "gemini-frontier", "effort": "high"}
    breakdown = {}
    for tail in commands:
        # Display refresh stays passive, including the existing Google Ultra
        # connection. Installed Grok help is a separate capability probe.
        assert "-p" not in tail and "--output-format" not in tail, "Status refresh submitted inference"
        key = " ".join(tail)
        breakdown[key] = breakdown.get(key, 0) + 1
    assert breakdown == {"--version": 4, "app-server --help": 1, "app-server generate-json-schema --out": 1,
                         "app-server --listen stdio://": 2, "auth login --help": 1, "auth status": 1,
                         "--help": 2, "debug models": 1, "debug models --bundled": 1, "models": 1}, breakdown
    assert len(commands) == 15
    measured(f"[{required_id}] cold ?refresh=1 with four native CLIs installed issued {len(commands)} hidden native "
             f"commands on the request thread: {breakdown}")

    # A realistic ledger (thousands of account-qualified documents), created
    # AFTER the warm refresh so the first cached load is the one that parses it.
    account = add(service)
    service.snapshot(True)
    ledger = data / ".anchor" / "usage_ledger"
    ledger.mkdir(parents=True)
    count = 3000
    when = "2026-10-05T12:00:00+00:00"
    for i in range(count):
        (ledger / f"{i}.json").write_text(json.dumps({"entries": {
            "default": {"provider_connection_id": "chatgpt-default", "tokens": 2, "recorded_at": when},
            "named": {"provider_connection_id": account["id"], "tokens": 3, "recorded_at": when},
            "claude": {"provider_connection_id": "claude-default", "tokens": 1, "recorded_at": when},
            "legacy": {"tokens": 999, "recorded_at": when}}}), encoding="utf-8")
    blocked = BlockedObserve(backend, "unsupported")
    monkeypatch.setattr(backend, "observe", blocked)
    native_calls = []
    def no_native(*args, **kwargs):
        native_calls.append(args)
        raise native.NativeError()
    monkeypatch.setattr(native, "run_command", no_native)
    monkeypatch.setattr(native, "HiddenProcess", no_native)
    worker, result = start_refresh_request(origin)
    opener = authenticated(origin)
    original_open, opens = builtins.open, []
    def tracked_open(path, *args, **kwargs):
        if isinstance(path, (str, os.PathLike)) and Path(path).parent == ledger:
            opens.append(Path(path).name)
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(builtins, "open", tracked_open)
    timings, figures = [], []
    try:
        assert blocked.two_in_flight.wait(5)
        reads = len(backend.reads)
        for _ in range(5):
            before_load = len(opens)
            status, page, page_time = timed_get(opener, origin, "/setup", 15)
            assert status == 200 and 'id="setup-family"' in page
            status, body, api_time = timed_get(opener, origin, "/api/provider-setup", 15)
            assert status == 200 and worker.is_alive()
            timings.append((page_time, api_time, len(opens) - before_load))
            figures.append({c["id"]: c["anchor_observed"] for c in json.loads(body)["connections"]})
        assert len(backend.reads) == reads and native_calls == [], "a cached load ran native work"
    finally:
        blocked.release.set()
        worker.join(30)
    assert result.get("status") == 200, result
    assert sorted(opens) == sorted(f"{i}.json" for i in range(count)), "each ledger file is opened at most once across the loads"
    assert timings[0][2] == count and all(t[2] == 0 for t in timings[1:]), timings
    assert all(f == figures[0] for f in figures)
    assert figures[0]["chatgpt-default"]["tokens"] == 2 * count
    assert figures[0][account["id"]]["tokens"] == 3 * count
    assert figures[0]["claude-default"]["tokens"] == count
    assert figures[0]["grok-default"] == {"state": "unknown", "tokens": None, "source": "Anchor account-qualified usage ledger",
                                          "observed_at": None, "period": "Recorded Anchor work only; other native work is outside this total"}
    # (b) The capacity rail's reader, which paid one open per file per load until W7 (2026-10-10, the live home
    # page took 35-170 s): it now opens each unchanged file once, like the account reader above.
    import usage_capacity
    usage_capacity._ROWS.clear()
    per_call = []
    for _ in range(2):
        before_call = len(opens)
        usage_capacity._seen(str(ledger), datetime.now(timezone.utc))
        per_call.append(len(opens) - before_call)
    assert per_call == [count, 0]
    measured(f"[{required_id}] {count} ledger files: loads 1-5 opened {[t[2] for t in timings]} files "
             f"(page, api seconds: {[(round(p, 2), round(a, 2)) for p, a, _ in timings]}); "
             f"a per-call full read (usage_capacity._seen) opened {per_call} per call")


class AccountedFixture(NativeFixture):
    """Per-connection allowance reports keyed only by connection id."""
    def __init__(self):
        super().__init__()
        self.remaining = {}

    def observe(self, connection):
        self.reads.append((connection["id"], native.account_env(connection)))
        if connection["id"] in self.failed:
            raise native.NativeError(self.failed[connection["id"]])
        percent = self.remaining.get(connection["id"])
        signed = percent is not None
        return {"auth": "signed_in" if signed else "signed_out", "test": "passed" if signed else "not_tested",
                "auth_source": "Fixture native account/read",
                "allowance": {"state": "fresh" if signed else "unknown", "source": "Fixture native rateLimits/read",
                              "windows": [{"label": "5 hour", "remaining_percent": percent, "resets_at": time.time() + 3600,
                                           "window_minutes": 300}] if signed else []},
                "provider_usage": {"state": "unsupported", "source": "Fixture native usage/read", "tokens": None}}


def write_limit_job(jobs, name, utilization, connection_id=None):
    """A Claude job log carrying a rate_limit_event, beside its record when qualified."""
    event = {"type": "rate_limit_event", "rate_limit_info": {"unifiedWindows": {
        "five_hour": {"utilization": utilization, "resetsAt": int(time.time()) + 3600},
        "seven_day": {"utilization": utilization / 2, "resetsAt": int(time.time()) + 7 * 86400}}}}
    (jobs / f"{name}.log").write_text('{"type":"system"}\n' + json.dumps(event) + "\n", encoding="utf-8")
    if connection_id is not None:
        (jobs / f"{name}.json").write_text(json.dumps({"job_id": name, "provider_connection": {"id": connection_id}}), encoding="utf-8")


@required("separate-account-allowance-attribution")
def test_separate_account_allowance_attribution(stack, monkeypatch, required_id):
    import job_runner
    import usage_capacity
    import usage_capture
    service, _, data, home = stack
    backend = AccountedFixture()
    service.native = backend
    monkeypatch.setenv("CODEX_HOME", str(home / "stray-codex-home"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home / "stray-claude-home"))
    first, second = add(service, name="Work ChatGPT"), add(service, name="Personal ChatGPT")
    third, fourth = add(service, family="claude", name="Work Claude"), add(service, family="claude", name="Personal Claude")
    decoy = "e" * 32
    backend.remaining.update({"chatgpt-default": 75, first["id"]: 12, second["id"]: 55,
                              "claude-default": 60, third["id"]: 60, fourth["id"]: 60})
    jobs = job_runner.jobs_dir()
    jobs.mkdir(parents=True, exist_ok=True)
    write_limit_job(jobs, "third", 0.3, third["id"])
    write_limit_job(jobs, "fourth", 0.9, fourth["id"])
    write_limit_job(jobs, "legacy", 0.99)
    for identity in ("claude-default", decoy, first["id"]):
        assert usage_capacity.latest_limit_signal(connection_id=identity) is None, identity
    assert usage_capacity.latest_limit_signal(connection_id=third["id"])["five_hour"]["utilization"] == 0.3
    assert usage_capacity.latest_limit_signal(connection_id=fourth["id"])["five_hour"]["utilization"] == 0.9
    for identity, tokens in (("chatgpt-default", 100), (first["id"], 11), (second["id"], 22), (third["id"], 33), (fourth["id"], 44)):
        usage_capture.ingest_usage("fixture-session", "row-" + identity, source=usage_capture.SOURCE_STEWARD_TURN,
                                   native_id=identity, tokens=tokens, cli="chatgpt", provider_connection_id=identity)
    usage_capture.ingest_usage("fixture-session", "legacy-row", source=usage_capture.SOURCE_STEWARD_TURN,
                               native_id="legacy", tokens=999, cli="chatgpt")
    fresh = service.snapshot(True)
    expected = {"chatgpt-default": ([75], "usable", None, 100), first["id"]: ([12], "near_limit", "Low allowance", 11),
                second["id"]: ([55], "usable", None, 22), "claude-default": ([], "unknown", None, None),
                third["id"]: ([70, 85], "usable", None, 33), fourth["id"]: ([10, 55], "near_limit", "Low allowance", 44)}
    for identity, (remaining, capacity, warning, tokens) in expected.items():
        report = row(fresh, identity)
        assert [round(w["remaining_percent"], 6) for w in report["allowance"]["windows"]] == remaining, identity
        assert report["capacity"] == capacity, identity
        assert (report["warning"] is None) if warning is None else (warning in report["warning"]), identity
        assert report["anchor_observed"]["tokens"] == tokens, identity
    assert row(fresh, "claude-default")["allowance"]["state"] == "unsupported"
    assert row(fresh, third["id"])["allowance"]["source"] == "Account-qualified Claude rate_limit_event"
    assert setup.observed_tokens(decoy)["tokens"] is None
    assert setup.claude_allowance(decoy, setup.stamp())["windows"] == []
    assert setup.claude_allowance("claude-default", setup.stamp())["windows"] == []
    current = settings.load_settings()
    for identity in (first["id"], second["id"], "chatgpt-default"):
        connection = metadata.find_connection(current, identity)
        env = native.account_env(connection)
        assert env["ANCHOR_PROVIDER_CONNECTION"] == identity and "CLAUDE_CONFIG_DIR" not in env
        assert env["CODEX_HOME"] == str(native.account_home(connection))
    for identity in (third["id"], fourth["id"], "claude-default"):
        connection = metadata.find_connection(current, identity)
        env = native.account_env(connection)
        assert env["ANCHOR_PROVIDER_CONNECTION"] == identity and "CODEX_HOME" not in env
        assert env["CLAUDE_CONFIG_DIR"] == str(native.account_home(connection))
    homes = [native.account_home(metadata.find_connection(current, identity)) for identity in expected]
    assert len(set(homes)) == len(homes)
    assert native.account_env(first)["CODEX_HOME"] != str(home / "stray-codex-home")
    assert native.account_env(third)["CLAUDE_CONFIG_DIR"] != str(home / "stray-claude-home")
    assert all(env["ANCHOR_PROVIDER_CONNECTION"] == identity for identity, env in backend.reads)
    # One connection's failure leaves every other connection's fresh report untouched.
    untouched = {identity: {k: row(fresh, identity)[k] for k in ("auth", "allowance", "capacity", "warning", "anchor_observed", "catalog")}
                 for identity in expected}
    failed_so_far = set()
    for failing, failure in ((first["id"], "timeout"), (fourth["id"], "expired")):
        backend.failed[failing] = failure
        service.refresh(metadata.find_connection(current, failing))
        failed_so_far.add(failing)
        after = service.snapshot()
        failed = row(after, failing)
        assert failed["auth"] == failure and failed["allowance"]["state"] == "stale" and failed["allowance"]["error"] == failure
        assert failed["allowance"]["windows"] == untouched[failing]["allowance"]["windows"]
        assert failed["capacity"] == "unknown" and failed["anchor_observed"] == untouched[failing]["anchor_observed"]
        for identity, before in untouched.items():
            if identity not in failed_so_far:
                assert {k: row(after, identity)[k] for k in before} == before, identity


class ShapedFixture(NativeFixture):
    """The real adapters' unsupported shapes at the fixture seam."""
    def __init__(self):
        super().__init__()
        self.shapes = {}

    def observe(self, connection):
        self.reads.append((connection["id"], native.account_env(connection)))
        if connection["family"] in ("grok", "gemini"):
            raise native.NativeError("unsupported")
        shape = self.shapes.get(connection["id"])
        if shape == "unknown":
            return {"auth": "signed_in", "test": "passed", "auth_source": "Fixture native account/read",
                    "allowance": {"state": "unknown", "source": "Fixture native rateLimits/read", "windows": []},
                    "provider_usage": {"state": "unknown", "source": "Fixture native usage/read", "tokens": None}}
        if isinstance(shape, tuple) and shape[0] == "invalid":
            windows = native.allowance_windows({"rateLimits": {"primary": {"usedPercent": shape[1], "windowDurationMins": 300}}})
            return {"auth": "signed_in", "test": "passed", "auth_source": "Fixture native account/read",
                    "allowance": {"state": "fresh" if windows else "unknown", "source": "Fixture native rateLimits/read", "windows": windows},
                    "provider_usage": {"state": "unsupported", "source": "Fixture native usage/read", "tokens": None}}
        return super().observe(connection)


@required("unsupported-is-not-usable")
def test_unsupported_is_not_usable(server, monkeypatch, required_id):
    from playwright.sync_api import expect, sync_playwright
    origin, (service, _, _, _) = server
    backend = ShapedFixture()
    service.native = backend
    monkeypatch.setattr(setup.provider_secrets, "get", lambda identity: None)
    monkeypatch.setattr(model_policy, "_MEMORY", {})
    unknown_account = add(service, name="Unknown allowance")
    backend.shapes[unknown_account["id"]] = "unknown"
    invalid = {}
    for bad in (True, -1, 101, float("nan"), float("inf"), "75"):
        assert native.allowance_windows({"rateLimits": {"primary": {"usedPercent": bad}}}) == []
        account = add(service, name="Invalid percent " + repr(bad))
        backend.shapes[account["id"]] = ("invalid", bad)
        invalid[account["id"]] = bad
    api_account = add(service, mode="api")
    current = settings.load_settings()
    named_grok, named_gemini = metadata.new_connection("grok", "Named Grok"), metadata.new_connection("gemini", "Named Gemini")
    settings.save_settings(provider_connections=current["provider_connections"] + [named_grok, named_gemini])
    snapshot = service.snapshot(True)
    unsupported = {"claude-default": "unsupported", "grok-default": "unsupported", "gemini-default": "unavailable",
                   named_grok["id"]: "unsupported", named_gemini["id"]: "unavailable", api_account["id"]: "unsupported",
                   unknown_account["id"]: "unknown", **{identity: "unknown" for identity in invalid}}
    for identity, state in unsupported.items():
        report = row(snapshot, identity)
        assert report["capacity"] == "unknown" and report["warning"] is None, identity
        assert report["allowance"]["state"] == state and report["allowance"]["windows"] == [], identity
        assert isinstance(report["allowance"]["source"], str) and report["allowance"]["source"], identity
        assert isinstance(report["provider_usage"]["state"], str) and report["provider_usage"]["state"], identity
    assert row(snapshot, "claude-default")["auth"] == "signed_in" and row(snapshot, unknown_account["id"])["auth"] == "signed_in"
    for identity in (api_account["id"], named_grok["id"], named_gemini["id"], "grok-default", "gemini-default"):
        assert not row(snapshot, identity)["execution"]["ready"], identity
    config = settings.load_settings()
    for family, identity in (("chatgpt", api_account["id"]), ("grok", named_grok["id"]), ("gemini", named_gemini["id"])):
        refused = deepcopy(config)
        refused["provider_preferences"]["accounts"][family] = identity
        with pytest.raises(ValueError, match="no subscription execution adapter"):
            setup.selected_for_launch(refused, family)
    for policy in ("warn", "manual"):
        config["provider_preferences"]["warning_policy"] = policy
        for identity in unsupported:
            setup.require_capacity_choice(config, metadata.find_connection(config, identity))
    saved = settings.load_settings()
    assert saved["model_policy"] == model_policy.DEFAULT_POLICY and saved["provider_preferences"]["quality"] == {}
    strength = setup.resolve_quality("claude", saved, metadata.find_connection(saved, "claude-default"))
    assert (strength["model"], strength["effort"]) == ("frontier", "ultra")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context()
            browser_login(context, origin)
            page, errors, launched, streams = guarded_page(context)
            page.goto(origin + "/setup", wait_until="domcontentloaded")
            detail = page.locator("#provider-detail")
            expect(detail).to_contain_text("Native sign-in", timeout=5000)
            rendered = {}
            for family in metadata.FAMILIES:
                page.locator("#provider-tabs button", has_text=metadata.LABELS[family]).click()
                buttons = page.locator("#provider-accounts .provider-account")
                for index in range(buttons.count()):
                    button = buttons.nth(index)
                    name = button.evaluate("b=>b.firstChild.textContent")
                    button.click()
                    expect(detail).to_contain_text(metadata.LABELS[family] + " · " + name)
                    rendered[(family, name)] = detail.inner_text()
            assert not errors and not launched and not streams, (errors, launched, streams)
        finally:
            browser.close()
    assert len(rendered) == len(saved["provider_connections"])
    for identity, state in unsupported.items():
        connection = metadata.find_connection(saved, identity)
        text = rendered[(connection["family"], connection["name"])]
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        allowance_line = lines[lines.index("Subscription allowance") + 1]
        assert allowance_line.endswith("allowance " + state + " · Not reported"), (identity, allowance_line)
        assert not re.search(r"\d+(\.\d+)?% remaining", text), (identity, text)


@required("failure-keeps-existing-session-and-quality")
def test_failure_keeps_existing_session_and_quality(server, monkeypatch, tmp_path, required_id):
    from playwright.sync_api import expect, sync_playwright
    from types import SimpleNamespace
    import anchor_gui
    import job_runner
    from steward_cockpit import steward_engine
    from tests.test_high_seat_page_2026_09_26 import _ctx
    origin, (service, backend, _, _) = server
    account = add(service, family="claude", name="Bound Claude")
    pending = add(service, name="Pending ChatGPT")
    backend.signed.add(account["id"])
    service.snapshot(True)
    prefs = deepcopy(service.snapshot()["preferences"])
    prefs.update(family="claude")
    prefs["accounts"]["claude"] = account["id"]
    prefs["quality"]["claude"] = {"model": "frontier", "effort": "high"}
    service.apply({"preferences": prefs, "expected_revision": settings.load_settings()["settings_revision"]})
    monkeypatch.setattr(steward_engine, "STATE_FILE", tmp_path / "engines.json")
    directory = tmp_path / "conversation"
    directory.mkdir()
    selection = {"family": "claude", "model": "frontier", "effort": "high", "selection_evidence": "explicit_setup_choice"}
    steward_engine._update_state(str(directory), {"cli": "claude", "session_id": "owned-session", "provider_connection": account,
                                                  "model_policy": selection, "provider_quality": prefs["quality"]["claude"]})
    engine = steward_engine.Engine(str(directory), fake=True)
    engine.session_id, engine.proc = "owned-session", SimpleNamespace(poll=lambda: None)

    def spawn_env():
        # Block gitguard installation; capture the actual engine environment seam.
        with monkeypatch.context() as patch:
            patch.setattr(importlib.util, "spec_from_file_location", lambda *a, **kw: None)
            return engine._spawn_env()

    home = str(native.account_home(account))
    primary, mirror = settings.settings_path().read_bytes(), settings.mirror_path().read_bytes()
    baseline = settings.load_settings()
    assert setup.selected_for_launch(baseline, "claude")["id"] == account["id"]
    assert spawn_env()["CLAUDE_CONFIG_DIR"] == home
    opener = authenticated(origin)

    def unchanged(label):
        assert settings.settings_path().read_bytes() == primary and settings.mirror_path().read_bytes() == mirror, label
        current = settings.load_settings()
        assert current["provider_preferences"] == baseline["provider_preferences"] == prefs, label
        assert current["model_policy"] == model_policy.DEFAULT_POLICY, label
        assert (engine.session_id, engine.provider_connection, engine.model_selection) == ("owned-session", account, selection), label
        env = spawn_env()
        assert env["CLAUDE_CONFIG_DIR"] == home and env["ANCHOR_PROVIDER_CONNECTION"] == account["id"], label
        assert engine._desired_policy()[1] == "claude", label
        assert setup.selected_for_launch(current, "claude", check_capacity=True)["id"] == account["id"], label
        assert setup.selected_for_launch(current, "claude", surface="jobs", check_capacity=True)["id"] == account["id"], label

    for failure in ("timeout", "expired", "unavailable", "error"):
        backend.failed[account["id"]] = failure
        service.refresh(account)
        report = row(service.snapshot(), account["id"])
        assert report["auth"] == failure and report["test"] == "failed" and not report["execution"]["ready"]
        unchanged(failure)
        status, body = http_request(opener, origin, "/api/provider-setup?refresh=1&connection_id=" + account["id"])
        assert status == 200 and row(json.loads(body), account["id"])["auth"] == failure
        unchanged(failure + " over http")
    backend.failed[pending["id"]], backend.timeout = "timeout", True
    # A failed refresh inside start_login: since the W1-E1 fix (Wave 2) the
    # sign-in is refused outright instead of running a native login against a
    # home whose status could not be read; the failed read is still published
    # and, as before, changes nothing else.
    with pytest.raises(ValueError, match="could not be read"):
        service.start_login(pending["id"])
    assert not backend.login_started.is_set(), "a native login ran against a home whose status could not be read"
    assert row(service.snapshot(), pending["id"])["auth"] == "timeout"
    unchanged("failed refresh inside start_login")
    canary = tmp_path / "native_env_canary.py"
    canary.write_text("import json, os\nprint(json.dumps({'home': os.getenv('CLAUDE_CONFIG_DIR'), "
                      "'account': os.getenv('ANCHOR_PROVIDER_CONNECTION'), 'api': bool(os.getenv('ANTHROPIC_API_KEY'))}))\n")
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"{Path(sys.executable).as_posix()} {canary.as_posix()}")
    record = job_runner.launch("research", backend="claude",
                               env={"CLAUDE_CONFIG_DIR": "wrong-account", "ANTHROPIC_API_KEY": "billing-canary-never-print"})
    final = job_runner.wait(record["job_id"], timeout=20)
    assert final["status"] == job_runner.STATUS_DONE and record["provider_connection"]["id"] == account["id"]
    assert json.loads(Path(final["log_path"]).read_text()) == {"home": home, "account": account["id"], "api": False}
    unchanged("after a job launch")
    # In the browser: the Cave composer draft and the open Setup dialog survive
    # a refresh whose native read fails (a new failure state proves it ran).
    backend.failed[account["id"]] = "expired"
    context_data = _ctx()
    context_data.update(auth_required=True, logged_in=True, build=anchor_gui.BUILD_ID, capacity=[])
    context_data["steward"] = {"key": "aladdin", "label": "Aladdin", "high_seat": "aladdin-high-seat-cave.jpg", "high_seat_name": "Cave of Wonders",
                               "seal_name": "Lamp", "campaign_name": "Star Chart", "campaign_icon": "campaign-aladdin-star-chart.jpg"}
    monkeypatch.setattr(anchor_gui, "_high_seat_context", lambda: deepcopy(context_data))
    draft = "Keep this unfinished Cave draft through the failed refresh"
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context(viewport={"width": 1440, "height": 1050})
            browser_login(context, origin)
            page, errors, launched, streams = guarded_page(context)
            page.goto(origin + "/high-seat")
            expect(page.locator("#cave-account")).to_have_value(account["id"])
            say = page.locator("#say")
            expect(say).to_be_visible()
            say.fill(draft)
            page.locator("#setup-gear").click()
            dialog = page.locator(".provider-dialog")
            expect(dialog).to_be_visible()
            surface = page.frame_locator(".provider-dialog iframe")
            expect(surface.locator("#setup-account")).to_have_value(account["id"])
            surface.locator("#provider-accounts .provider-account", has_text="Bound Claude").click()
            expect(surface.locator("#provider-detail")).to_contain_text("Bound Claude")
            surface.locator("#provider-refresh").click()
            expect(surface.locator("#refresh-message")).to_contain_text("Host reads completed", timeout=15000)
            expect(surface.locator("#provider-detail")).to_contain_text("expired")
            expect(dialog).to_be_visible()
            expect(surface.locator("#setup-section-providers")).to_be_visible()
            expect(surface.locator("#setup-account")).to_have_value(account["id"])
            expect(surface.locator("#setup-model")).to_have_value("frontier")
            expect(say).to_have_value(draft)
            surface.locator("#setup-return").click()
            expect(dialog).not_to_be_visible()
            expect(say).to_have_value(draft)
            expect(page.locator("#cave-account")).to_have_value(account["id"])
            assert not errors and not launched, (errors, launched)
            assert all("/setup" not in frame for _, frame in streams)
        finally:
            browser.close()
    assert row(service.snapshot(), account["id"])["auth"] == "expired"
    unchanged("after the browser refresh")


# ── reproduced findings (Wave 1 strict-xfail reproductions; Wave 2 removed ───
# ── each marker when its fix landed, so the same bodies are the proofs) ──────


@pytest.mark.parametrize("condition", ["aged", "failed", "cold"])
def test_h1_threshold_only_save_does_not_need_a_fresh_ready_account(stack, condition):
    """H1 (fixed Wave 2): apply refused a threshold-only save while the selected
    account's observation was aged, failed or absent; readiness now gates only a
    change of the executing account."""
    service, backend, _, _ = stack
    if condition == "cold":
        service = setup.ProviderService(backend)   # a fresh service start: no observation yet
    else:
        service.snapshot(True)
        if condition == "aged":
            key = service._key("claude-default")
            service.observations[key]["observed_at"] = (datetime.now(timezone.utc) - timedelta(seconds=setup.TTL + 1)).isoformat()
        else:
            backend.failed["claude-default"] = "timeout"
            service.refresh(metadata.find_connection(settings.load_settings(), "claude-default"))
    before = settings.load_settings()
    prefs = deepcopy(before["provider_preferences"])
    prefs["warning_threshold"] = 30
    assert prefs["family"] is None and prefs["accounts"] == {} and prefs["quality"] == {}
    service.apply({"preferences": prefs, "expected_revision": before["settings_revision"]})
    assert settings.load_settings()["provider_preferences"]["warning_threshold"] == 30


def test_h2_threshold_only_save_does_not_revalidate_unchanged_quality(stack):
    """H2 (fixed Wave 2): apply re-validated an unchanged saved exact quality
    against a stale catalog and refused a threshold-only save; only a changed
    quality choice is checked against a fresh catalog now."""
    service, _, _, _ = stack
    service.snapshot(True)
    before = settings.load_settings()
    prefs = deepcopy(before["provider_preferences"])
    prefs.update(family="claude")
    prefs["quality"]["claude"] = {"model": "balanced", "effort": "high"}
    saved = service.apply({"preferences": prefs, "expected_revision": before["settings_revision"]})
    assert saved["preferences"]["quality"]["claude"] == {"model": "balanced", "effort": "high"}
    key = service._key("claude-default")
    service.catalogs[key]["observed_at"] = (datetime.now(timezone.utc) - timedelta(seconds=setup.TTL + 1)).isoformat()
    assert row(service.snapshot(), "claude-default")["catalog"]["state"] == "stale"
    threshold_only = deepcopy(saved["preferences"])
    threshold_only["warning_threshold"] = 30
    service.apply({"preferences": threshold_only, "expected_revision": saved["settings_revision"]})
    assert settings.load_settings()["provider_preferences"] == threshold_only


def test_h3_never_supported_report_is_not_relabelled_stale(stack, monkeypatch):
    """H3 (fixed Wave 2): a report that was never supported was stamped
    observed_at and relabelled stale by a later failed refresh; a report without
    figures now carries no observation time."""
    service, backend, _, _ = stack
    observe = backend.observe
    def unknown_reports(connection):
        out = observe(connection)
        out["allowance"] = {"state": "unknown", "source": "Fixture native rateLimits/read", "windows": []}
        out["provider_usage"] = {"state": "unsupported", "source": "Fixture native usage/read", "tokens": None}
        return out
    monkeypatch.setattr(backend, "observe", unknown_reports)
    connection = metadata.find_connection(settings.load_settings(), "chatgpt-default")
    service.refresh(connection)
    first = row(service.snapshot(), "chatgpt-default")
    assert first["allowance"]["state"] == "unknown" and first["provider_usage"]["state"] == "unsupported"
    backend.failed["chatgpt-default"] = "timeout"
    service.refresh(connection)
    after = row(service.snapshot(), "chatgpt-default")
    assert after["auth"] == "timeout"
    assert after["allowance"]["state"] != "stale", "a report that never existed is shown as a retained stale report"
    assert after["provider_usage"]["state"] != "stale"
    # R3-E: the honest label is the last attempt's own failure, with no invented observation time.
    assert after["allowance"]["state"] == "timeout" and after["provider_usage"]["state"] == "timeout"
    assert after["allowance"]["observed_at"] is None and after["provider_usage"]["observed_at"] is None


def test_h4_default_native_credential_homes_are_not_project_artifacts(server, monkeypatch):
    """H4 (fixed Wave 2): private_account_path covered only isolated homes, so
    the default native credential homes were servable through authenticated
    project routes; the fixed dotfile homes and the documented redirects are
    private now."""
    import anchor_gui
    import report_viewer
    from steward_cockpit import steward_routes
    origin, (_, _, _, home) = server
    sentinel = "default-home-credential-canary"
    monkeypatch.setenv("CODEX_HOME", str(home / "codex-redirected"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home / "claude-redirected"))
    planted = [home / ".codex" / "auth.json", home / ".claude" / ".credentials.json", home / ".grok" / "credentials.json",
               home / "codex-redirected" / "auth.json", home / "claude-redirected" / ".credentials.json"]
    for path in planted:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(sentinel, encoding="utf-8")
    # A registered project folder that encloses the native homes (the user's home itself).
    monkeypatch.setattr(anchor_gui, "_ecgberht_project_folder", lambda pid: (str(home), None, 200))
    monkeypatch.setattr(anchor_gui._rnd, "get_project", lambda pid: {"id": pid, "folder_path": str(home)})
    opener = authenticated(origin)
    for path in planted:
        rel = path.relative_to(home).as_posix()
        # The authenticated artifact route first: a MAJOR needs a served credential.
        for route in ("/artifact/p?path=", "/api/rnd/project_file_content?project_id=p&path=",
                      "/api/ecgberht/artifact?project_id=p&rel=", "/api/ecgberht/chamber_artifact?project_id=p&rel="):
            code, body = http_request(opener, origin, route + quote(rel))
            assert code in (403, 404) and sentinel not in body, (route, rel, code)
        assert report_viewer.resolve_project_artifact(str(home), rel) is None, rel
        result, code = steward_routes.handle_get(str(home), "deliverable-file", {"path": rel})
        assert code == 403 and sentinel not in json.dumps(result), rel
        assert native.private_account_path(path), rel


def test_h6_completed_login_with_failed_status_read_is_reported_honestly(stack, monkeypatch):
    """H6 (fixed Wave 2): a completed native sign-in whose follow-up status read
    failed was reported as failed, then a retry was refused as already signed
    in; the completed sign-in is now reported honestly."""
    service, backend, _, _ = stack
    connection = add(service)
    observe, reads = backend.observe, []
    def flaky(candidate):
        if candidate["id"] == connection["id"]:
            reads.append(candidate["id"])
            if len(reads) == 2:   # only the status read right after the native login fails
                raise native.NativeError("timeout")
        return observe(candidate)
    def completed_login(candidate, cancel, progress):
        progress({"state": "awaiting_browser", "url": "https://auth.openai.com/codex/device", "user_code": "DEMO-1234",
                  "message": "Native device login on host"})
        backend.signed.add(candidate["id"])   # the native CLI saved the credentials in the isolated home
    monkeypatch.setattr(backend, "observe", flaky)
    monkeypatch.setattr(backend, "login", completed_login)
    attempt = service.start_login(connection["id"])
    service.logins[attempt["id"]]["thread"].join(10)
    status = service.login_status(attempt["id"])
    with pytest.raises(ValueError, match="already signed in"):
        service.start_login(connection["id"])   # the account IS signed in: the retry says so
    assert status["state"] == "completed", status
    assert "failed" not in status["message"].lower(), status


def test_w1e1_failed_status_read_does_not_disarm_the_signed_in_guard(stack):
    """W1-E1 (fixed Wave 2): a failed pre-login status read disabled
    start_login's already-signed-in guard, so a native login could run against
    a signed-in (possibly bound) home; an unreadable status now refuses the
    sign-in."""
    service, backend, _, _ = stack
    connection = add(service)
    backend.signed.add(connection["id"])
    service.refresh(connection)
    assert row(service.snapshot(), connection["id"])["auth"] == "signed_in"
    with pytest.raises(ValueError, match="already signed in"):
        service.start_login(connection["id"])
    backend.failed[connection["id"]], backend.timeout = "timeout", True
    try:
        with pytest.raises(ValueError):
            service.start_login(connection["id"])
        assert not backend.login_started.is_set(), "a native login ran against a signed-in home"
    finally:
        for login in list(service.logins.values()):
            thread = login.get("thread")
            if thread is not None:
                thread.join(10)


def test_apply_still_refuses_an_unready_account_change_and_a_new_exact_model_on_a_stale_catalog(stack):
    """R3-D (Grok seat 1, Wave-2 re-review): the H1/H2 relaxation keeps both refusals — selecting an unready account,
    and choosing a NEW exact model without a fresh catalog — and a refused save changes nothing."""
    service, backend, _, _ = stack
    unready = add(service, family="claude", name="Never signed in")
    service.snapshot(True)
    before = settings.load_settings()
    assert not row(service.snapshot(), unready["id"])["execution"]["ready"]
    switch = deepcopy(before["provider_preferences"])
    switch.update(family="claude")
    switch["accounts"]["claude"] = unready["id"]
    with pytest.raises(ValueError, match="unready"):
        service.apply({"preferences": switch, "expected_revision": before["settings_revision"]})
    key = service._key("claude-default")
    service.catalogs[key]["observed_at"] = (datetime.now(timezone.utc) - timedelta(seconds=setup.TTL + 1)).isoformat()
    assert row(service.snapshot(), "claude-default")["catalog"]["state"] == "stale"
    exact = deepcopy(before["provider_preferences"])
    exact.update(family="claude")
    exact["quality"]["claude"] = {"model": "balanced", "effort": "high"}
    with pytest.raises(ValueError, match="Refresh native model capabilities"):
        service.apply({"preferences": exact, "expected_revision": before["settings_revision"]})
    assert settings.load_settings()["provider_preferences"] == before["provider_preferences"]
    assert settings.load_settings()["settings_revision"] == before["settings_revision"]
