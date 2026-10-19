"""LIVE laptop verification of the landed provider assurance (plan v2, live wave).

This file is deliberately different from its isolated siblings
(test_provider_setup*.py): it drives the ACTUAL Anchor service on this
laptop — the NSSM-owned process on ``http://127.0.0.1:8777`` — through a
fresh, NORMALLY AUTHENTICATED Chromium, and verifies the Setup/Cave provider
surface the reboot activated. A passing isolated test does not prove this
machine; a passing run here does not prove John's already-open client window
(that distinction is reported explicitly in the receipt, never silently).

Rules this file enforces on itself:

* REQUIRED live criteria FAIL the gate when unverified — there is no skip.
  Unreachable service, no working token, missing Playwright: all RED.
* READ-ONLY: every non-GET request from the driven pages is intercepted and
  aborted; the steward event stream / status-ack (a soft-wake seam on the
  real server) is aborted too. No model work is submitted, no enrollment is
  launched, no refresh=1 native probe is triggered. Accounts, secrets,
  preferences, drafts, conversations and running sessions are preserved —
  proven by a before/after snapshot of the live settings projection.
* Evidence (receipt + screenshots) lands in this effort's existing
  verification area: ``Setup and Mother Ship/assurance-2026-10-05/evidence``.
  The receipt names token SOURCES only — never a token value.
"""
import json
import os
import re
import socket
import time
from pathlib import Path
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError

import pytest
from playwright.sync_api import expect, sync_playwright

ORIGIN = "http://127.0.0.1:8777"
VIEWPORT = {"width": 1440, "height": 1050}
ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "Setup and Mother Ship" / "assurance-2026-10-05" / "evidence"
#: Soft-wake / dialogue seams on the real server, aborted at the browser; the
#: fire-and-forget status acks (both spellings) are guarded too — aborting one
#: preserves John's nudge state and must never read as a mutation attempt.
STEWARD_STREAMS = re.compile(
    r"/api/steward/(events|status-ack|say|wake|start)|/api/status-ack")
REQUIRED_FACTS = (
    "Native sign-in", "Connection test", "Subscription allowance",
    "Allowance source / observed", "Exact tokens remaining",
    "Provider account token activity", "Token activity source / observed",
    "Anchor-observed consumption", "Anchor source / observed",
    "API spend", "Subscription price")

#: Cross-test accumulator for the receipt the final test writes + asserts.
RESULTS = {"criteria": {}, "blocked": [], "unexpected": [], "errors": [],
           "defects": [], "timings": {}}


# ── live-service access (stdlib only; never logs a token value) ─────────────
def _http(method, path, token=None, body=None, timeout=20):
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        # Belt and braces: the standard header, the legacy header and the
        # browser cookie spelling — all read-only senders of the same secret.
        headers["Authorization"] = "Bearer " + token
        headers["X-Anchor-Token"] = token
        headers["Cookie"] = "anchor_auth=" + token
    opener = build_opener(ProxyHandler({}))  # loopback — never a proxy
    request = Request(ORIGIN + path, data=data, headers=headers, method=method)
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")


def _main_checkout_root():
    """The main Anchor checkout this worktree was cut from (git metadata)."""
    dotgit = ROOT / ".git"
    try:
        text = dotgit.read_text(encoding="utf-8", errors="replace") if dotgit.is_file() else ""
    except OSError:
        return None
    match = re.search(r"gitdir:\s*(.+)", text)
    if not match:
        return None
    gitdir = Path(match.group(1).strip())
    for parent in (gitdir, *gitdir.parents):
        if parent.name == ".git":
            return parent.parent
    return None


def _service_env_token():
    """ANCHOR_TOKEN from the installed service's own configured environment.

    Read-only registry read of the NSSM ``anchor`` service's
    ``AppEnvironmentExtra`` — the authoritative value the live process was
    started with. Guarded: any failure just skips this source."""
    try:
        import winreg
    except ImportError:
        return None
    try:
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Services\anchor\Parameters")
        value, _kind = winreg.QueryValueEx(key, "AppEnvironmentExtra")
        winreg.CloseKey(key)
    except OSError:
        return None
    lines = value if isinstance(value, list) else [value]
    for line in lines:
        if isinstance(line, str) and line.startswith("ANCHOR_TOKEN="):
            token = line.split("=", 1)[1].strip()
            if token:
                return token
    return None


def _candidate_tokens():
    """(source-name, token) candidates, each verified by a real login below."""
    candidates = []
    env = (os.environ.get("ANCHOR_TOKEN") or "").strip()
    if env:
        candidates.append(("environment ANCHOR_TOKEN", env))
    service = _service_env_token()
    if service:
        candidates.append(("anchor service AppEnvironmentExtra", service))
    for name, root in (("main-checkout onboard-token", _main_checkout_root()),
                       ("worktree onboard-token", ROOT)):
        if root is None:
            continue
        token_file = root / ".anchor" / "onboard-token"
        try:
            if token_file.is_file():
                token = token_file.read_text(encoding="utf-8").strip()
                if token:
                    candidates.append((name, token))
        except OSError:
            pass
    seen, unique = set(), []
    for name, token in candidates:
        if token not in seen:
            seen.add(token)
            unique.append((name, token))
    return unique


def _preservation_view(report):
    """The slice of the live settings projection a read-only walk must not move."""
    return {
        "settings_revision": report.get("settings_revision"),
        "preferences": report.get("preferences"),
        "connections": sorted(
            [c.get("id"), c.get("family"), c.get("name"), c.get("mode")]
            for c in report.get("connections") or []),
        "data_directory": (report.get("host") or {}).get("data_directory"),
    }


@pytest.fixture(scope="module")
def live():
    """Reach + normally authenticate the actual laptop service. FAIL, never skip."""
    probe = socket.socket()
    probe.settimeout(3)
    try:
        probe.connect(("127.0.0.1", 8777))
    except OSError as exc:
        pytest.fail("REQUIRED LIVE CRITERION UNVERIFIED: the Anchor service did not "
                    "answer on 127.0.0.1:8777 (%s). Nothing about the live laptop was "
                    "proven; start/restart the anchor service and rerun." % exc)
    finally:
        probe.close()

    tried = []
    source = token = None
    for name, candidate in _candidate_tokens():
        status, body = _http("POST", "/api/auth/login", token=candidate,
                             body={"token": candidate})
        try:
            auth = json.loads(body).get("auth")
        except ValueError:
            auth = None
        tried.append("%s -> HTTP %s" % (name, status))
        if status == 200 and auth in ("cookie-set", "disabled"):
            source, token = name, candidate
            assert auth == "cookie-set", (
                "the live service answered auth:disabled — the locked Cave "
                "requires a configured ANCHOR_TOKEN; this is a genuine live defect")
            break
    if token is None:
        pytest.fail("REQUIRED LIVE CRITERION UNVERIFIED: no token source "
                    "authenticated against the live service (tried: %s). Set "
                    "ANCHOR_TOKEN in the gate environment and rerun." %
                    ("; ".join(tried) or "no token source was available"))

    status, body = _http("GET", "/api/provider-setup", token=token)
    assert status == 200, "authenticated GET /api/provider-setup answered HTTP %s" % status
    report = json.loads(body)
    assert report.get("ok") is True, "live provider report refused: %s" % report.get("error")
    host = report.get("host") or {}
    assert str(host.get("name", "")).lower() == socket.gethostname().lower(), (
        "the service on :8777 reports host %r, not this laptop (%r) — not the "
        "actual laptop service" % (host.get("name"), socket.gethostname()))
    assert report.get("connections"), "live service reports no provider connections"

    RESULTS["service"] = {
        "origin": ORIGIN, "reachable": True, "auth": "cookie-set",
        "token_source": source, "host": {k: host.get(k) for k in
                                         ("name", "runtime", "configured", "first_setup")},
        "settings_revision": report.get("settings_revision"),
        "connection_ids": sorted(c.get("id") for c in report["connections"]),
    }
    RESULTS["_pre"] = _preservation_view(report)
    RESULTS["criteria"]["live-service-reachable-and-normally-authenticated"] = {
        "passed": True,
        "detail": "loopback :8777 answered; token source '%s' minted the HttpOnly "
                  "cookie; the report names this host (%s)" % (source, host.get("name"))}
    return {"origin": ORIGIN, "token": token, "report": report}


@pytest.fixture(scope="module")
def ctx(live):
    """One normally authenticated fresh Chromium context against the live service."""
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport=VIEWPORT)
        login = context.request.post(live["origin"] + "/api/auth/login",
                                     data={"token": live["token"]})
        assert login.ok, "browser-context login against the live service failed"
        assert any(c.get("httpOnly") for c in context.cookies(live["origin"])), \
            "no HttpOnly auth cookie was minted for the fresh browser"
        try:
            yield context
        finally:
            context.close()
            browser.close()


def _guard(page):
    """Read-only interception: abort every non-GET and every steward stream."""
    def on_route(route):
        request = route.request
        if request.method != "GET":
            bucket = RESULTS["blocked"] if STEWARD_STREAMS.search(request.url) \
                else RESULTS["unexpected"]
            bucket.append((request.method, request.url))
            route.abort()
        elif STEWARD_STREAMS.search(request.url):
            RESULTS["blocked"].append((request.method, request.url))
            route.abort()
        else:
            route.continue_()
    page.on("pageerror", lambda error: RESULTS["errors"].append(str(error)))
    page.route("**/*", on_route)


def test_live_service_reachable_and_normally_authenticated(live):
    entry = RESULTS["criteria"]["live-service-reachable-and-normally-authenticated"]
    assert entry["passed"], entry["detail"]


def test_setup_page_live_responsive_with_explicit_account_reports(live, ctx):
    page = ctx.new_page()
    _guard(page)
    started = time.monotonic()
    page.goto(live["origin"] + "/setup", wait_until="domcontentloaded")
    expect(page.locator("#host-runtime")).to_contain_text("Connected runtime:", timeout=20000)
    settle_ms = int((time.monotonic() - started) * 1000)
    # An existing mother ship, not a first setup — the landed assurance retained it.
    expect(page.locator("#host-runtime")).to_contain_text("existing setup retained", timeout=5000)
    expect(page.locator("#setup-section-providers")).to_be_visible()

    # Responsive AFTER the fetches settle: section navigation answers promptly
    # (pure client-side; no further network round trip).
    started = time.monotonic()
    page.locator('.setup-steps [data-section="host"]').click()
    expect(page.locator("#setup-section-host")).to_be_visible(timeout=3000)
    page.locator('.setup-steps [data-section="providers"]').click()
    expect(page.locator("#setup-section-providers")).to_be_visible(timeout=3000)
    toggle_ms = int((time.monotonic() - started) * 1000)

    # The existing provider/account report, every fact explicit — a missing
    # figure must SAY so (Not reported / unknown / stale), never render blank.
    expect(page.locator("#provider-detail h2")).to_be_visible(timeout=10000)
    facts = {}
    rows = page.locator("#provider-detail .provider-facts div")
    for i in range(rows.count()):
        facts[rows.nth(i).locator("dt").inner_text().strip()] = \
            rows.nth(i).locator("dd").inner_text().strip()
    for label in REQUIRED_FACTS:
        assert label in facts and facts[label], \
            "live account report is missing an explicit %r fact (got: %s)" % (label, sorted(facts))
    assert facts["Exact tokens remaining"] == "Not reported"
    for label in ("API spend", "Subscription price"):
        assert facts[label].startswith("Not reported · ") and \
            len(facts[label]) > len("Not reported · "), \
            "%r must carry an explicit state, got %r" % (label, facts[label])
    assert re.search(r"% remaining|allowance \w+|Not reported",
                     facts["Subscription allowance"]), \
        "allowance is neither a figure nor an explicit state: %r" % facts["Subscription allowance"]

    # Retained settings: the controls equal the service's SAVED preferences
    # (read-only cross-check against the authenticated JSON projection).
    report = json.loads(ctx.request.get(live["origin"] + "/api/provider-setup").text())
    prefs = report["preferences"]
    expect(page.locator("#setup-family")).not_to_have_value("", timeout=10000)
    family = page.locator("#setup-family").input_value()
    assert family == (prefs.get("family") or report["default_family"])
    expected_account = (prefs.get("accounts") or {}).get(family) or family + "-default"
    options = page.locator("#setup-account option").evaluate_all("els => els.map(e => e.value)")
    account = page.locator("#setup-account").input_value()
    assert account == (expected_account if expected_account in options else options[0])
    quality = (prefs.get("quality") or {}).get(family) or {}
    model = page.locator("#setup-model").input_value()
    effort = page.locator("#setup-effort").input_value()
    assert model == (quality.get("model") or "latest_supported")
    assert effort == (quality.get("effort") or "highest_supported")
    threshold = page.locator("#setup-threshold").input_value()
    assert threshold == str(prefs.get("warning_threshold"))
    assert page.locator("#setup-warning").input_value() == prefs.get("warning_policy")

    message = page.locator("#setup-message").inner_text().strip()
    if message:
        RESULTS["defects"].append("live /setup #setup-message: %s" % message)
    if "· stale" in facts.get("Native sign-in", ""):
        RESULTS["defects"].append("live native sign-in is labelled stale: %r"
                                  % facts["Native sign-in"])

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(EVIDENCE / "live-setup-1440.png"))
    assert not RESULTS["errors"], "browser errors on live /setup: %s" % RESULTS["errors"]
    assert not RESULTS["unexpected"], \
        "live /setup attempted non-GET work on a read-only walk: %s" % RESULTS["unexpected"]

    RESULTS["timings"].update(setup_settle_ms=settle_ms, section_toggle_ms=toggle_ms)
    RESULTS["setup"] = {"family": family, "account": account, "model": model,
                        "effort": effort, "threshold": threshold, "facts": facts}
    RESULTS["criteria"]["setup-responsive-after-fetches-settle"] = {
        "passed": True, "detail": "settled in %d ms; section toggle %d ms; no page "
                                  "errors" % (settle_ms, toggle_ms)}
    RESULTS["criteria"]["provider-account-reports-explicit-states"] = {
        "passed": True, "detail": "all %d facts present and explicit; allowance %r"
                                  % (len(REQUIRED_FACTS), facts["Subscription allowance"])}
    RESULTS["criteria"]["retained-settings"] = {
        "passed": True, "detail": "Setup controls equal saved preferences "
                                  "(family=%s account=%s model=%s effort=%s warn@%s)"
                                  % (family, account, model, effort, threshold)}
    page.close()


def test_cave_gear_opens_same_setup_with_lower_left_controls(live, ctx):
    page = ctx.new_page()
    _guard(page)
    started = time.monotonic()
    page.goto(live["origin"] + "/high-seat", wait_until="domcontentloaded")
    # Normally authenticated: the cookie logs this browser in — no token box.
    expect(page.locator("#loginBox")).to_be_hidden()
    capacity = page.locator("#cave-provider-capacity")
    expect(capacity).not_to_contain_text("reading host settings", timeout=20000)
    paint_ms = int((time.monotonic() - started) * 1000)
    capacity_text = capacity.inner_text().strip()
    assert re.search(r"% remaining|allowance \w+", capacity_text), \
        "live capacity tile is not an explicit figure/state: %r" % capacity_text

    # The gear sits at the top-left of the rail and is the one Setup entry.
    gear = page.locator("#setup-gear")
    assert page.locator(".provider-rail-head #setup-gear").count() == 1
    box = gear.bounding_box()
    assert box and 0 <= box["x"] <= 60 and 0 <= box["y"] <= 60, \
        "gear not at the top-left of the rail: %s" % box

    # Lower-LEFT provider/model controls, with capacity as a SEPARATE control.
    assert page.locator("nav.rail #cave-provider-controls").count() == 1
    assert page.locator("#cave-provider-controls #cave-provider-capacity").count() == 0
    assert page.evaluate(
        "() => !!(document.getElementById('railNav').compareDocumentPosition("
        "document.getElementById('cave-provider-controls')) & "
        "Node.DOCUMENT_POSITION_FOLLOWING)"), \
        "provider controls are not below the Destinations nav in the rail"
    controls = page.locator("#cave-provider-controls")
    controls.scroll_into_view_if_needed()
    cbox = controls.bounding_box()
    assert cbox and cbox["x"] + cbox["width"] <= VIEWPORT["width"] / 3, \
        "provider controls are not in the left rail: %s" % cbox
    for control in ("cave-family", "cave-account", "cave-model", "cave-effort"):
        expect(page.locator("#" + control)).not_to_have_value("", timeout=10000)
    assert page.locator("#cave-family").input_value() == RESULTS["setup"]["family"]
    assert page.locator("#cave-account").input_value() == RESULTS["setup"]["account"]
    assert page.locator("#cave-model").input_value() == RESULTS["setup"]["model"]
    assert page.locator("#cave-effort").input_value() == RESULTS["setup"]["effort"]

    # The gear opens the SAME Setup page (same route, same retained settings),
    # and the Cave composer draft survives the dialog — all in OUR fresh
    # browser; John's client and its drafts are never driven.
    say = page.locator("#say")
    expect(say).to_be_visible()
    say.fill("Live verification draft — never sent")
    gear.click()
    dialog = page.locator(".provider-dialog")
    expect(dialog).to_be_visible(timeout=10000)
    dbox = dialog.bounding_box()
    assert dbox and dbox["x"] >= -1 and dbox["y"] >= -1 and \
        dbox["x"] + dbox["width"] <= VIEWPORT["width"] + 1 and \
        dbox["y"] + dbox["height"] <= VIEWPORT["height"] + 1
    src = page.locator(".provider-dialog iframe").get_attribute("src") or ""
    assert src.startswith("/setup"), "gear did not open the Setup route: %r" % src
    surface = page.frame_locator(".provider-dialog iframe")
    expect(surface.locator("#setup-section-providers")).to_be_visible(timeout=20000)
    expect(surface.locator("#setup-family")).to_have_value(
        RESULTS["setup"]["family"], timeout=10000)
    assert surface.locator("#setup-threshold").input_value() == \
        RESULTS["setup"]["threshold"]
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(EVIDENCE / "live-cave-dialog-1440.png"))
    surface.locator("#setup-return").click()
    expect(dialog).not_to_be_visible(timeout=5000)
    expect(say).to_have_value("Live verification draft — never sent")
    page.evaluate("() => window.scrollTo(0, 0)")
    page.screenshot(path=str(EVIDENCE / "live-cave-1440.png"))

    assert not RESULTS["errors"], "browser errors on live /high-seat: %s" % RESULTS["errors"]
    assert not RESULTS["unexpected"], \
        "live Cave attempted non-GET work on a read-only walk: %s" % RESULTS["unexpected"]

    build = page.evaluate(
        "() => { const i = document.querySelector('img.anchor-mark');"
        "const m = i && /[?&]v=([^&]+)/.exec(i.src); return m ? m[1] : null; }")
    RESULTS["service"]["live_build"] = build
    RESULTS["timings"]["cave_paint_ms"] = paint_ms
    RESULTS["criteria"]["cave-gear-opens-same-setup"] = {
        "passed": True, "detail": "gear at %s opened %r; dialog shows the same "
                                  "retained settings; composer draft survived" % (box, src)}
    RESULTS["criteria"]["lower-left-provider-model-controls-separate-capacity"] = {
        "passed": True, "detail": "controls below Destinations in the left rail at %s; "
                                  "capacity is its own control reading %r"
                                  % (cbox, capacity_text)}
    page.close()


def test_preservation_and_receipt_with_actual_client_distinction(live):
    # Preservation: the before/after settings projection is byte-equal.
    status, body = _http("GET", "/api/provider-setup", token=live["token"])
    assert status == 200
    after = _preservation_view(json.loads(body))
    assert after == RESULTS["_pre"], (
        "the read-only walk moved live settings:\nbefore=%s\nafter=%s"
        % (RESULTS["_pre"], after))
    RESULTS["criteria"]["preservation-read-only"] = {
        "passed": True, "detail": "settings_revision, preferences, connections and "
                                  "data directory unchanged; %d guarded steward "
                                  "stream/ack requests aborted before the server"
                                  % len(RESULTS["blocked"])}

    # John's client vs this fresh browser — the distinction, stated explicitly.
    johns_client = {
        "inspected": False,
        "surface_driven": "fresh Playwright Chromium, normal cookie login, same "
                          "origin, this laptop",
        "reason": "John's already-open Anchor client (the desktop WebView2 shell / "
                  "his signed-in browser) exposes no automation endpoint, so it was "
                  "not driven; a passing isolated test does not prove his window, "
                  "and neither does this fresh-browser run.",
        "remaining_human_step": "open the Cave gear in his own client and confirm "
                                "the same Setup page and lower-left controls",
    }
    RESULTS["criteria"]["actual-client-distinction-reported"] = {
        "passed": True, "detail": johns_client["reason"]}

    required = (
        "live-service-reachable-and-normally-authenticated",
        "setup-responsive-after-fetches-settle",
        "provider-account-reports-explicit-states",
        "retained-settings",
        "cave-gear-opens-same-setup",
        "lower-left-provider-model-controls-separate-capacity",
        "preservation-read-only",
        "actual-client-distinction-reported")
    for criterion in required:
        entry = RESULTS["criteria"].get(criterion)
        assert entry and entry.get("passed"), (
            "REQUIRED LIVE CRITERION UNVERIFIED: %r has no passing record — an "
            "earlier walk did not complete" % criterion)

    blocked = sorted({(method, url.split("&since=")[0]) for method, url in RESULTS["blocked"]})
    receipt = {
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "gate": "python -m pytest -v tests/test_provider_setup_live.py",
        "service": RESULTS["service"],
        "criteria": {k: RESULTS["criteria"][k] for k in required},
        "timings": RESULTS["timings"],
        "account_facts": RESULTS["setup"]["facts"],
        "johns_client": johns_client,
        "guarded_requests_aborted": ["%s %s" % pair for pair in blocked],
        "unexpected_mutation_attempts": RESULTS["unexpected"],
        "defects_for_later_bounded_repair": RESULTS["defects"],
        "limitations": [
            "Desktop viewport (1440x1050) only; the phone layout keeps its isolated coverage.",
            "The steward event stream and status-ack were aborted at the browser, so the "
            "live dialogue stream itself was deliberately not exercised (soft-wake seam).",
            "No refresh=1 native probe was triggered: the walk reads the cached projection "
            "only, so native sign-in freshness was observed, not re-measured.",
            johns_client["reason"],
        ],
        "screenshots": ["live-setup-1440.png", "live-cave-dialog-1440.png",
                        "live-cave-1440.png"],
    }
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "live-laptop-check.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    assert receipt["johns_client"]["inspected"] is False
    assert "does not prove his window" in " ".join(receipt["limitations"])
    assert not receipt["unexpected_mutation_attempts"]
