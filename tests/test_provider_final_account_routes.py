"""Exercise the retained findings through enrollment and a warm account cache."""
import json
import os

import model_policy
import provider_native as native
import provider_settings as metadata
import provider_setup as setup
from tests.test_provider_setup import authenticated, http_request, server, stack
from tests.test_provider_review_followup import (
    FOLLOWUP_DISCOVER, followup_grok_service, followup_registered_grok,
)


def test_setup_login_http_reuses_discovery_and_reaches_isolated_browser(server, monkeypatch):
    origin, _ = server
    connection = followup_registered_grok()
    service, commands, probes = followup_grok_service(
        monkeypatch, connection, signed=False, transient=True,
    )
    original = native.run_command
    signed = set()

    def command(argv, env, cancel=None, timeout=None, progress=None, **kwargs):
        if argv[1:] == ["auth", "login", "--browser"]:
            commands.append((argv[1:], dict(env)))
            signed.add(env["GROK_HOME"])
            progress("https://grok.com/login")
            return 0, ""
        code, text = original(argv, env, **kwargs)
        if argv[1:] == ["auth", "status", "--json"] and env["GROK_HOME"] in signed:
            account = json.loads(text)
            account["loggedIn"] = True
            text = json.dumps(account)
        return code, text

    monkeypatch.setattr(native, "run_command", command)
    opener = authenticated(origin)
    status, text = http_request(opener, origin, "/api/provider-setup/login", {
        "connection_id": connection["id"],
    })
    assert status == 200, text
    attempt = json.loads(text)
    service.logins[attempt["id"]]["thread"].join(5)
    assert not service.logins[attempt["id"]]["thread"].is_alive()
    result = service.login_status(attempt["id"])
    assert result["state"] == "completed", result
    assert probes == ["grok"]
    browser_homes = [env["GROK_HOME"] for tail, env in commands
                     if tail == ["auth", "login", "--browser"]]
    assert browser_homes == [str(native.account_home(connection))]
    assert "must-not-export" not in json.dumps(result)


def test_warm_inherited_gemini_catalog_cannot_replace_selected_account_discovery(stack, monkeypatch):
    calls = []
    monkeypatch.setenv("ANCHOR_PROVIDER_CONNECTION", "chatgpt-default")
    monkeypatch.setattr(model_policy.shutil, "which", lambda *args, **kwargs: "agy-fixture")

    def runner(argv, env):
        assert argv == ["agy-fixture", "models"]
        calls.append(env["ANCHOR_PROVIDER_CONNECTION"])
        return ("gemini-frontier-high\tGemini frontier\n"
                "gemini-frontier-max\tGemini frontier\n"
                "gemini-older-low\tGemini older\n")

    def discover(family, **kwargs):
        return FOLLOWUP_DISCOVER(family, env=kwargs.get("env"), runner=runner)

    monkeypatch.setattr(model_policy, "discover", discover)
    # Seed the actual cache as unqualified switch/terminal discovery does.
    model_policy.resolve("gemini", force=True)
    assert calls == ["chatgpt-default"]
    config = setup.anchor_settings.load_settings()
    selected = metadata.find_connection(config, "gemini-default")
    result = setup.resolve_quality("gemini", config, selected)
    assert result["model"] == "gemini-frontier" and result["effort"] == "max"
    assert calls == ["chatgpt-default", "gemini-default"]
    assert os.environ["ANCHOR_PROVIDER_CONNECTION"] == "chatgpt-default"
