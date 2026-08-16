"""Self-service access-token controls — the 🔑 button + the global 401
auto-reprompt fetch wrapper, in BOTH the project window and the home dashboard.

THE PROBLEM (root cause, pre-fixed): ``ANCHOR_TOKEN`` gates the read-API GETs.
The browser supplies it from ``localStorage['anchor_token']`` (PER-ORIGIN). On a
fresh origin (a laptop hitting the tailnet IP) localStorage has no/stale token →
every panel-loading GET returns 401 → the dynamic panels come up EMPTY → looks
like a "different/broken layout." This adds (A) a VISIBLE 🔑 token control in
each page's header that re-prompts + reloads, and (B) a global ``window.fetch``
wrapper that auto-re-prompts on a 401 read (when auth is on) so a stale token
self-heals.

Coverage:
  * Rendered-DOM: the 🔑 token control is present in BOTH pages, wired to
    setAnchorToken()+reload, and its initial visibility tracks
    ``_paths.expected_token()`` (visible when auth is on, hidden when off).
  * The fetch wrapper source is present in BOTH pages, guarded by
    ``window.__anchorFetchWrapped``, only reloads on a 401 when auth is on.
  * Playwright (DEV-ONLY): on BOTH pages ``window.__anchorFetchWrapped === true``,
    and a fetch that returns 401 (forced via a route intercept) invokes the
    token-prompt path (``window.prompt`` stubbed).

Hermetic: temp data dir + a registered stub project; the Playwright cases set
``ANCHOR_TOKEN`` so auth is ON. NEVER binds :8777; no network.
"""
import importlib
import re
import subprocess
import threading
import time
from html.parser import HTMLParser
from pathlib import Path

import pytest


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)


def _have_git():
    try:
        return subprocess.run(["git", "--version"],
                              capture_output=True).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


pytestmark = pytest.mark.skipif(not _have_git(), reason="git not on PATH")


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Tmp data dir + a registered project; the stack reloaded against the env.

    ``token`` (an ANCHOR_TOKEN value or None) is parametrized by the auth-on/off
    cases via ``request.param`` indirection where needed; the base fixture is
    auth-OFF (no token), and individual tests reload paths with a token set."""
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)

    for mod in ("paths", "job_runner", "pty_manager", "rnd_registry",
                "effort_history", "sessions", "anchor_marker",
                "session_registry", "worktrees", "lanes", "summarizer",
                "report_viewer", "handoff", "boneyard", "terminal_session"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import anchor_gui
    gui = importlib.reload(anchor_gui)
    import rnd_registry

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial")

    proj = rnd_registry.add_project("TokenTemp", str(repo), scaffold=False)
    pid = proj["id"]

    bundle = {"gui": gui, "repo": repo, "pid": pid, "data": data,
              "monkeypatch": monkeypatch}
    yield bundle
    try:
        import pty_manager
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


def _reload_with_token(env, token):
    """Reload paths + anchor_gui with ANCHOR_TOKEN set/cleared; return the gui."""
    if token is None:
        env["monkeypatch"].delenv("ANCHOR_TOKEN", raising=False)
    else:
        env["monkeypatch"].setenv("ANCHOR_TOKEN", token)
    import paths
    importlib.reload(paths)
    gui = importlib.reload(env["gui"])
    env["gui"] = gui
    return gui


def _home_html(gui):
    projects, tasks, inbox = gui.gather_all()
    return gui.generate_html(projects, tasks, inbox)


# ════════════════════════════════════════════════════════════════════════════
# Rendered-DOM: the 🔑 token control present in BOTH pages
# ════════════════════════════════════════════════════════════════════════════

class _Collector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.els = []

    def handle_starttag(self, tag, attrs):
        self.els.append((tag, dict(attrs)))


def _token_button(html):
    """Return the parsed (tag, attrs) for #tokenBtn, or None."""
    c = _Collector()
    c.feed(html)
    for tag, attrs in c.els:
        if attrs.get("id") == "tokenBtn":
            return (tag, attrs)
    return None


def test_project_window_has_token_control(env):
    """The project window header renders a #tokenBtn 🔑 control wired to
    setAnchorToken()+reload."""
    gui, pid = env["gui"], env["pid"]
    html = gui.render_project_window_html(pid)
    btn = _token_button(html)
    assert btn is not None, "project window must render #tokenBtn"
    tag, attrs = btn
    assert tag == "button"
    assert "setAnchorToken()" in (attrs.get("onclick") or "")
    assert "location.reload()" in (attrs.get("onclick") or "")
    assert "&#128273;" in html or "\U0001f511" in html  # the key glyph 🔑


def test_home_has_token_control(env):
    """The home dashboard masthead renders a #tokenBtn 🔑 control wired to
    setAnchorToken()+reload."""
    gui = env["gui"]
    html = _home_html(gui)
    btn = _token_button(html)
    assert btn is not None, "home page must render #tokenBtn"
    tag, attrs = btn
    assert tag == "button"
    assert "setAnchorToken()" in (attrs.get("onclick") or "")
    assert "location.reload()" in (attrs.get("onclick") or "")
    assert "&#128273;" in html or "\U0001f511" in html  # the key glyph 🔑


def test_token_control_visibility_tracks_auth_project_window(env):
    """The project-window #tokenBtn is hidden (display:none) when auth is OFF and
    visible (inline-block) when ANCHOR_TOKEN is configured."""
    # auth OFF (base fixture has no token)
    gui = _reload_with_token(env, None)
    btn = _token_button(gui.render_project_window_html(env["pid"]))
    assert btn is not None
    assert "display:none" in (btn[1].get("style") or ""), \
        "token control must be hidden when auth is off"
    # auth ON
    gui = _reload_with_token(env, "s3cret")
    btn = _token_button(gui.render_project_window_html(env["pid"]))
    assert btn is not None
    assert "display:inline-block" in (btn[1].get("style") or ""), \
        "token control must be visible when auth is on"
    _reload_with_token(env, None)


def test_token_control_visibility_tracks_auth_home(env):
    """The home #tokenBtn is hidden when auth is OFF and visible when on."""
    gui = _reload_with_token(env, None)
    btn = _token_button(_home_html(gui))
    assert btn is not None
    assert "display:none" in (btn[1].get("style") or ""), \
        "token control must be hidden when auth is off"
    gui = _reload_with_token(env, "s3cret")
    btn = _token_button(_home_html(gui))
    assert btn is not None
    assert "display:inline-block" in (btn[1].get("style") or ""), \
        "token control must be visible when auth is on"
    _reload_with_token(env, None)


# ════════════════════════════════════════════════════════════════════════════
# The global fetch wrapper source is present + guarded in BOTH pages
# ════════════════════════════════════════════════════════════════════════════

# RETRY, DO NOT RELOAD. On a 401 with auth on, BOTH pages re-prompt and then
# RE-ISSUE the original request with the new token. They must NOT reload:
# location.reload() discards whatever the user had typed — the steward chamber's
# goal input, the High Seat saybox draft, the in-flight act — which after a token
# rotation is guaranteed data loss on the first click (John's friction record
# docs/friction/2026-07-28-high-seat-token-reload-loses-input.md). Home was fixed
# 2026-07-28; the project window carried the old reload until 2026-07-30.
def _strip_line_comments(js):
    """Drop ``//`` line comments so the checks below read CODE, not prose.

    Both wrappers carry a comment explaining why they no longer call
    location.reload() — scanning raw source would match that explanation and
    report the very bug it documents.
    """
    out = []
    for line in js.split("\n"):
        i = line.find("//")
        # not inside a string/URL ("https://") — these comments start the line
        if i != -1 and line[:i].strip() in ("", "*"):
            line = line[:i]
        out.append(line)
    return "\n".join(out)


def _assert_retry_not_reload(src, where):
    assert "window.__anchorFetchWrapped" in src, where
    assert "if (window.__anchorFetchWrapped) return;" in src, where
    code = _strip_line_comments(src)
    m = re.search(r"status === 401", code)
    assert m, "%s: wrapper must check status === 401" % where
    seg = code[m.start():m.start() + 1200]
    assert "ANCHOR_AUTH_REQUIRED" in seg, where
    assert "setAnchorToken(" in seg, where
    retry = seg.find("_origFetch(")
    assert retry != -1, (
        "%s: a 401 must RE-ISSUE the original request with the new token" %
        where)
    # A reload still exists as the HONEST LAST RESORT (a genuinely wrong token,
    # or a Request whose body is already consumed). What must never happen is
    # reloading INSTEAD of retrying — that is the data-loss path.
    reload_at = seg.find("location.reload()")
    assert reload_at == -1 or retry < reload_at, (
        "%s: the retry must come BEFORE any reload — reloading first discards "
        "the user's typed input (goal / saybox draft) on the first click "
        "after a token rotation" % where)


def test_fetch_wrapper_present_project_window(env):
    """Project window: wrapper installed, and a 401 RETRIES (never reloads)."""
    _assert_retry_not_reload(env["gui"]._PROJECT_WINDOW_JS, "project window")


def test_fetch_wrapper_present_home(env):
    """Home dashboard: wrapper installed, and a 401 RETRIES (never reloads)."""
    _assert_retry_not_reload(_home_html(env["gui"]), "home")


# ════════════════════════════════════════════════════════════════════════════
# Playwright (DEV-ONLY): wrapper installed + a 401 triggers the prompt path
# ════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def server_authed(env):
    """A running server with ANCHOR_TOKEN set (auth ON), on a free port != 8777."""
    gui = _reload_with_token(env, "s3cret")
    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield env, f"http://127.0.0.1:{port}", port
    finally:
        try:
            srv.shutdown()
        except Exception:
            pass
        time.sleep(0.15)
        try:
            srv.server_close()
        except Exception:
            pass
        t.join(timeout=5)
        _reload_with_token(env, None)


def _drive_browser(base, path):
    """Open ``base+path`` with window.prompt stubbed, assert the fetch wrapper is
    installed, force a 401 on a token-gated read via a route intercept, and assert
    the prompt path fired. Returns nothing; raises on failure."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        # Pre-seed a token so the DOMContentLoaded one-time prompt does NOT fire
        # (we want to observe ONLY the 401-triggered re-prompt). Also stub
        # window.prompt to record calls and return null (cancel) so the wrapper
        # does NOT reload (which would detach the page).
        pg.add_init_script(
            "window.localStorage.setItem('anchor_token','s3cret');"
            "window.__promptCalls = [];"
            "window.prompt = function(){ window.__promptCalls.push(1); "
            "return null; };")
        errors = []
        # The forced 401 (below) intentionally logs a benign "Failed to load
        # resource ... 401" network console error — that is the condition we are
        # FORCING, not a JS fault. Exclude it; keep every other console error.
        def _record_error(m):
            if m.type != "error":
                return
            if "401" in m.text and "load resource" in m.text.lower():
                return
            errors.append(m.text)
        pg.on("console", _record_error)
        pg.goto(base + path, wait_until="domcontentloaded")

        # (A) the wrapper is installed.
        assert pg.evaluate("window.__anchorFetchWrapped === true"), \
            "the global fetch wrapper must be installed on this page"

        # (B) a 401 read triggers the prompt path. Force ANY fetch from inside the
        # page to a sentinel URL to return 401, then call fetch and assert the
        # stubbed prompt fired (the wrapper saw 401 + auth-on → setAnchorToken →
        # window.prompt). The stub returns null (cancel) so no reload happens.
        pg.route("**/__force401__", lambda route: route.fulfill(
            status=401, content_type="application/json",
            body='{"error":"unauthorized"}'))
        before = pg.evaluate("window.__promptCalls.length")
        pg.evaluate(
            "() => fetch('/__force401__').catch(function(){})")
        # The wrapper's .then runs after the response resolves; poll briefly.
        pg.wait_for_function(
            "window.__promptCalls.length > %d" % before, timeout=5000)
        after = pg.evaluate("window.__promptCalls.length")
        assert after > before, \
            "a 401 read must trigger the token re-prompt (window.prompt)"

        assert not errors, f"JS console errors: {errors}"
        b.close()


def test_fetch_wrapper_401_prompts_project_window(server_authed):
    """Project window: wrapper installed + a forced 401 triggers window.prompt."""
    pytest.importorskip("playwright.sync_api")
    env, base, _ = server_authed
    _drive_browser(base, f"/project/{env['pid']}")


def test_fetch_wrapper_401_prompts_home(server_authed):
    """Home dashboard: wrapper installed + a forced 401 triggers window.prompt."""
    pytest.importorskip("playwright.sync_api")
    _env, base, _ = server_authed
    _drive_browser(base, "/")


# ── Steward (Ecgberht/Jarvis/Aladdin) POSTs must send the token as a HEADER ──
# (2026-07-30) John: "I tried to enter a goal into a project level steward and
# it asked for a token again (which it had stored in the window)."
#
# ROOT CAUSE: the three steward MUTATING endpoints were called with the token in
# the QUERY STRING only (``?token=``). The do_POST middleware reads the token
# from the X-Anchor-Token header, the Authorization header, or a JSON body
# ``token`` field — never from the query string (only GET transports gate via
# ?token=). So every steward act 401'd, and the global fetch wrapper above turns
# a 401 into a fresh window.prompt — a window with a perfectly good stored token
# kept asking for it again, and the goal could never be saved.

# (chamber-m1 W2, 2026-08-14) The LIST MOVED WITH THE SURFACE, and the
# regression law did not change. ``speak`` and ``stand_up`` were the v0
# chamber's mutating POSTs; both call sites lived inside `_ecgRenderChamber` /
# `_ecgRenderStandUp`, which this wave DELETED. Both remain live SERVER routes
# (the chamber route is kept as a data API and the stand_up engine verb is
# untouched) — they simply have no client call site to scan any more, so
# leaving them here would have failed the floor assertion below forever, and
# the cheap "fix" would have been to delete the floor.
#
# What replaced them is M1's own mutating set, and every one of them is held to
# the same law: the token rides in a HEADER (all four go through ``_postJson``).
_STEWARD_POST_ENDPOINTS = ("converse", "refine_confirm", "deliverable_action",
                           "high_seat_act")


def _asset(name):
    return (Path(__file__).resolve().parents[1] / "static" / name).read_text(
        encoding="utf-8")


def test_steward_post_call_sites_send_token_header():
    """Every steward POST call site carries the token in a HEADER.

    Either it goes through ``_postJson`` (which sets X-Anchor-Token +
    X-Anchor-Build) or it sets X-Anchor-Token itself. A query-only POST is the
    exact regression that made the steward re-prompt for a stored token.
    """
    sources = {n: _asset(n) for n in ("project-window.js", "high-seat.js")}
    seen = set()
    for name, src in sources.items():
        for ep in _STEWARD_POST_ENDPOINTS:
            for m in re.finditer(r"/api/ecgberht/" + ep, src):
                # A CALL site is one whose invocation opens just before the
                # endpoint literal; anything else (a comment, a docstring
                # mention) is prose and is skipped.
                before = src[max(0, m.start() - 120):m.start()]
                if "_postJson(" not in before and "fetch(" not in before:
                    continue
                # The call window: the endpoint literal through the options
                # object (generous, still call-local).
                seg = src[m.start():m.start() + 400]
                seen.add((name, ep))
                assert ("_postJson(" in before
                        or "X-Anchor-Token" in seg
                        or "_ecgHsHeaders()" in seg), (
                    "%s: POST %s must send the token as X-Anchor-Token "
                    "(a query-only ?token= POST 401s → token re-prompt)" %
                    (name, ep))
    # All three mutating endpoints must actually be exercised by the scan —
    # otherwise a rename would silently empty this test.
    assert {ep for _n, ep in seen} == set(_STEWARD_POST_ENDPOINTS), seen


def test_steward_post_rejects_query_only_token_but_accepts_header(server_authed):
    """The server contract this fix is built on, pinned.

    Query-only ``?token=`` on a POST is UNAUTHORIZED; the same call with the
    X-Anchor-Token header is not. If this ever flips, the client fix above can
    be simplified — until then, a query-only steward POST is a real 401.
    """
    import http.client
    import json as _json

    _env, base, port = server_authed
    payload = _json.dumps({}).encode()

    def _post(path, headers):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        c.request("POST", path, body=payload,
                  headers=dict({"Content-Type": "application/json"}, **headers))
        r = c.getresponse()
        r.read()
        c.close()
        return r.status

    assert _post("/api/ecgberht/high_seat_act?token=s3cret", {}) == 401
    assert _post("/api/ecgberht/high_seat_act",
                 {"X-Anchor-Token": "s3cret"}) != 401


def test_steward_post_urls_carry_no_query():
    """A steward POST URL must be a BARE path — no ?token=, no query at all.

    ``route_table.match`` compares an EXACT row with ``path == pattern``, so a
    POST carrying a query string missed its row, fell through the strangler and
    answered 404 "Unknown endpoint" — John's "Couldn't do that: Unknown
    endpoint - nothing was created" when setting a goal. Belt: the client sends
    a bare path (asserted here); braces: do_POST now dispatches on the path-only
    string (asserted in the next test), so a query can never misroute again.
    """
    for name in ("project-window.js", "high-seat.js"):
        src = _asset(name)
        for ep in _STEWARD_POST_ENDPOINTS:
            for m in re.finditer(r"/api/ecgberht/" + ep, src):
                before = src[max(0, m.start() - 120):m.start()]
                if "_postJson(" not in before and "fetch(" not in before:
                    continue
                tail = src[m.start() + len("/api/ecgberht/") + len(ep):]
                # Step over the string literal's CLOSING QUOTE before looking
                # for a concatenated/inline query — without this the check
                # silently passes on the very pattern it exists to catch.
                tail = tail[:80].lstrip("'\" ")
                assert not tail.startswith(("+", "?")), (
                    "%s: POST %s must use a BARE path (a query string misses "
                    "the exact route row -> 404 Unknown endpoint); got %r" %
                    (name, ep, tail[:60]))


def test_post_dispatch_tolerates_a_query_string(server_authed):
    """do_POST dispatches on the PATH, so a query can never 404 a real route.

    The regression: do_GET passed ``_path_only`` but do_POST passed the raw
    request line, so ANY exact-row POST carrying a query answered 404 "Unknown
    endpoint" instead of running its handler.
    """
    import http.client
    import json as _json

    _env, base, port = server_authed
    payload = _json.dumps({}).encode()

    def _post(path):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        c.request("POST", path, body=payload, headers={
            "Content-Type": "application/json", "X-Anchor-Token": "s3cret"})
        r = c.getresponse()
        r.read()
        c.close()
        return r.status

    bare = _post("/api/ecgberht/high_seat_act")
    withq = _post("/api/ecgberht/high_seat_act?token=s3cret&x=1")
    assert bare != 404, "the bare route must dispatch"
    assert withq != 404, (
        "a query string must not misroute an exact POST row (404 Unknown "
        "endpoint was the steward's 'Couldn't do that')")
    assert withq == bare, (bare, withq)


def test_every_migrated_route_has_a_registered_handler():
    """Every ``migrated=True`` route row must resolve to a real handler.

    THE CLASS OF BUG (2026-07-30): ``/api/ecgberht/stand_up`` was defined and
    declared migrated, but its name was missing from ``_MIGRATED_HANDLERS``.
    ``_strangler_dispatch`` treats that as "not migrated" and falls through to
    the legacy chain, which answers 404 "Unknown endpoint" — a declared, live,
    fully-implemented endpoint silently unreachable, with no startup warning.
    A route row is a PROMISE; this test makes the promise checkable.
    """
    import anchor_gui
    import route_table as _rt

    registry = anchor_gui._MIGRATED_HANDLERS
    missing = sorted({r.handler for r in _rt.migrated_routes()
                      if r.handler not in registry})
    assert not missing, (
        "route rows declared migrated=True whose handler is not registered in "
        "_MIGRATED_HANDLERS (they 404 as 'Unknown endpoint'): %s" % missing)
