"""Normally authenticated production Setup/Cave and executable first-launch regressions."""
from copy import deepcopy
import json
from pathlib import Path
import re
import threading

from playwright.sync_api import expect, sync_playwright
import pytest

import anchor_settings as settings
import provider_settings as metadata
import provider_setup as setup
from shell import connect
import onboard_bootstrap
from tests.test_provider_setup import AUTH, stack, row
from tests.test_provider_setup_browser import cave_server


def guarded_page(context):
    page = context.new_page()
    errors, work, provider_requests = [], [], []
    page.on("pageerror", lambda error: errors.append(str(error)))
    def guard(route):
        request = route.request
        if re.search(r"/api/steward/(events|status-ack|say|wake|start)", request.url):
            work.append(request.url)
            route.abort()
        elif request.method == "POST" and "/api/provider-setup/" not in request.url and "/api/auth/login" not in request.url:
            work.append(request.url)
            route.abort()
        else:
            if "/api/provider-setup" in request.url:
                provider_requests.append(request.url)
            route.continue_()
    page.route("**/*", guard)
    return page, errors, work, provider_requests


def login(context, origin):
    response = context.request.post(origin + "/api/auth/login", data={"token": AUTH})
    assert response.ok and any(cookie.get("httpOnly") for cookie in context.cookies(origin))


def test_first_executable_launch_chooses_host_before_provider_controls(cave_server, monkeypatch, tmp_path):
    origin, _, _ = cave_server
    shell_data = tmp_path / "client"
    monkeypatch.setattr(connect, "LOCAL", origin)
    assert connect.choose(shell_data) == ""
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context()
            login(context, origin)
            page, errors, work, requests = guarded_page(context)
            def choose_host():
                return connect.select_mother_ship(shell_data, tmp_path, probe_fn=lambda address: address == origin)
            page.expose_function("chooseHost", choose_host)
            page.add_init_script("window.pywebview={api:{select_mother_ship:()=>window.chooseHost().then(r=>{if(r.ok)location.href=r.address+r.path;return '';})}}")
            page.goto("about:blank")
            page.set_content(connect.first_launch_page())
            expect(page.locator("#choose-mother-ship")).to_be_visible()
            expect(page.locator("#choose-existing-host")).to_be_visible()
            assert not requests and not page.locator("#provider-detail").count()
            page.locator("#choose-mother-ship").click()
            expect(page).to_have_url(origin + "/setup")
            expect(page.locator("#provider-tabs button")).to_have_count(4)
            assert connect.choose(shell_data) == origin
            assert not errors and not work
        finally:
            browser.close()


def test_existing_host_choice_requires_https_and_reuses_saved_host(tmp_path, monkeypatch):
    shell_data = tmp_path / "client"
    probes = []
    monkeypatch.setattr(connect, "reachable", lambda *a, **k: probes.append(a) or True)
    address, why = connect.normalize("https://personal-host.tailnet.test")
    assert not why
    connect.save_address(shell_data, address)
    assert connect.choose(shell_data) == address
    assert probes == [], "Returning clients must not switch to a reachable local host"
    assert connect.normalize("http://personal-host.tailnet.test")[0] is None
    assert connect.normalize("https://person:password@personal-host.tailnet.test")[0] is None


def test_interrupted_host_install_does_not_save_a_false_ready_choice(tmp_path, monkeypatch):
    shell_data, package = tmp_path / "client", tmp_path / "package"
    package.mkdir()
    monkeypatch.setattr(onboard_bootstrap.shutil, "which", lambda _: None)
    failed = connect.select_mother_ship(shell_data, package, probe_fn=lambda _: False)
    assert not failed["ok"] and not failed["installation"]["ready"]
    assert not connect.settings_file(shell_data).exists()
    assert {"onboard.cmd", "onboard.ps1", "share_onboard.py"} <= set(failed["installation"]["package"]["missing"])
    assert failed["installation"]["bootstrap"]["action"] == "fail_manual"
    assert "onboard.cmd" in failed["installation"]["resume"]
    # Resumption rechecks the same established host; it never installs another
    # transport, stamps a partial install ready, or copies provider credentials.
    resumed = connect.select_mother_ship(shell_data, package, probe_fn=lambda _: True)
    assert resumed["ok"] and resumed["path"] == "/setup" and not resumed["installed"]
    assert connect.load_address(shell_data) == connect.LOCAL


def test_actual_add_two_claude_accounts_detail_reload_switch_and_usage_only_cave(cave_server, monkeypatch):
    origin, service, _ = cave_server
    backend = service.native
    browser_visited = threading.Event()
    enrollments = []
    def enroll(connection, cancel, progress):
        enrollments.append(connection["id"])
        browser_visited.clear()
        progress({"state": "awaiting_browser", "url": "https://claude.ai/login", "message": "Disposable provider-owned browser flow"})
        assert browser_visited.wait(15), "Add account never opened the provider-owned sign-in"
        assert not cancel.is_set()
        backend.signed.add(connection["id"])
    monkeypatch.setattr(backend, "login", enroll)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context(viewport={"width": 1440, "height": 1050})
            login(context, origin)
            def provider_browser(route):
                browser_visited.set()
                route.fulfill(status=200, content_type="text/html", body="<title>Disposable official provider flow</title>")
            context.route("https://claude.ai/**", provider_browser)
            page, errors, work, _ = guarded_page(context)
            page.goto(origin + "/high-seat")
            composer = page.locator("#say")
            expect(composer).to_be_visible()
            composer.fill("Keep this unfinished draft while switching accounts")
            composer.evaluate("e=>e._accountProof='same composer'")
            page.locator("#setup-gear").click()
            surface = page.frame_locator(".provider-dialog iframe")
            expect(surface.locator("#provider-tabs button")).to_have_count(4)
            surface.locator("#provider-tabs button", has_text="Claude").click()
            identities = []
            for nickname in ("Claude one", "Claude two"):
                surface.locator("#new-account-name").fill(nickname)
                surface.locator("#add-account").click()
                expect(surface.locator("#provider-detail")).to_contain_text("signed in", timeout=20000)
                connection = next(c for c in service.snapshot()["connections"] if c["name"] == nickname)
                identities.append(connection["id"])
                assert connection["execution"]["ready"]
                surface.locator("#provider-accounts .provider-account", has_text=nickname).click()
                expect(surface.locator("#provider-detail")).to_contain_text("isolated native account")
            assert len(set(identities)) == 2 and enrollments == identities
            surface.locator("#account-nickname").fill("Claude teaching")
            surface.get_by_role("button", name="Save nickname", exact=True).click()
            expect(surface.locator("#provider-detail h2")).to_contain_text("Claude teaching")
            surface.locator("#setup-account").select_option(identities[0])
            surface.locator("#setup-apply").click()
            expect(surface.locator("#apply-message")).to_contain_text("Saved for new work")
            surface.locator("#setup-return").click()
            expect(page.locator("#cave-account")).to_have_value(identities[0])
            summaries = page.locator("#cave-provider-controls #cave-account-summaries")
            expect(summaries).to_contain_text("Claude one")
            expect(summaries).to_contain_text("Claude teaching")
            expect(summaries).to_contain_text("allowance unsupported")
            assert not summaries.locator("input,button,a").count()
            assert not re.search(r"sign.?up|credential|install|password|API key", summaries.inner_text(), re.I)
            page.locator("#cave-account").select_option(identities[1])
            page.locator("#cave-provider-apply").click()
            expect(page.locator("#cave-provider-message")).to_contain_text("Saved for new work")
            assert setup.selected_for_launch(settings.load_settings(), "claude")["id"] == identities[1]
            expect(composer).to_have_value("Keep this unfinished draft while switching accounts")
            assert composer.evaluate("e=>e._accountProof") == "same composer"
            page.locator("#setup-gear").click()
            expect(surface.locator("#provider-accounts")).to_contain_text("Claude teaching")
            expect(surface.locator("#setup-account")).to_have_value(identities[1])
            surface.locator("#provider-tabs button", has_text="Grok").click()
            expect(surface.locator("#add-account")).to_be_enabled()
            surface.locator("#new-account-name").fill("Unsupported Grok account")
            surface.locator("#add-account").click()
            expect(surface.locator("#setup-message")).to_contain_text("isolated")
            assert len(service.snapshot()["connections"]) == 6
            surface.locator("#setup-return").click()
            expect(composer).to_have_value("Keep this unfinished draft while switching accounts")
            assert not errors
            # Cave's own display soft-wakes were blocked. No work-start POST
            # reached the service; Setup never creates a steward event stream.
            assert all("/api/steward/events" in url or "/api/steward/status-ack" in url for url in work)
            refreshed = setup.ProviderService(backend).snapshot()
            assert row(refreshed, identities[1])["name"] == "Claude teaching"
        finally:
            browser.close()


def test_executable_host_api_keeps_failed_install_unsaved_and_resumes_same_host(tmp_path, monkeypatch):
    """Import the actual executable bridge; substitute only Windows UI calls."""
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
    spec = importlib.util.spec_from_file_location("provider_executable_bridge", source)
    executable = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(executable)
    monkeypatch.setitem(sys.modules, "connect", connect)
    data, package = tmp_path / "shell-client", tmp_path / "missing-package"
    package.mkdir()
    monkeypatch.setattr(executable, "DATA", data)
    monkeypatch.setattr(executable, "ROOT", package)
    monkeypatch.setattr(executable, "ZOOM_FILE", data / "zoom.txt")
    monkeypatch.setattr(connect, "reachable", lambda _: False)
    host = executable.HostApi()
    urls, pages = [], []
    host.bind(SimpleNamespace(load_url=urls.append, load_html=pages.append))
    assert host.select_mother_ship() == ""
    assert pages and "Install your mother ship" in pages[0] and not urls
    assert not connect.settings_file(data).exists()
    monkeypatch.setattr(connect, "reachable", lambda _: True)
    assert host.select_mother_ship() == ""
    assert urls == [connect.LOCAL + "/setup"]
    assert connect.load_address(data) == connect.LOCAL and host._html == ""
