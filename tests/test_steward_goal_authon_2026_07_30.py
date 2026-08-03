"""Setting a project goal in the steward chamber, with auth ON — the exact
path John walked (2026-07-30).

WHY THIS FILE EXISTS. Two independent faults made "set a goal" impossible on a
token-authed dashboard, and BOTH were invisible to the whole existing suite
because virtually every test runs with auth OFF:

  1. the steward POSTs sent the token as ``?token=`` only, which the do_POST
     middleware never reads → 401 → the global fetch wrapper re-prompted for a
     token the window already had;
  2. ``handle_ecgberht_stand_up`` was declared ``migrated=True`` but was never
     registered in ``_MIGRATED_HANDLERS``, and do_POST dispatched on the raw
     request line (query included) so an exact row could not match anyway →
     404 → "Couldn't do that: Unknown endpoint — nothing was created."

With ANCHOR_TOKEN unset, ``_tokenQ()`` is empty and every one of those faults
disappears — which is exactly why a green suite sat on top of a broken
dashboard. So these cases run with auth **ON** and assert the OUTCOME (the Face
and Strip exist on disk, the chamber says it saved) rather than the plumbing.

Hermetic: temp data dir, stub PTY, a throwaway git project, an OS-assigned port
(never :8777), no network. Playwright is DEV-ONLY (importorskip).
"""
import importlib
import json
import subprocess
import threading
import time
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

#: The distro secret-scanner allowlists this exact placeholder
#: (distro._PLACEHOLDER_VALUES) — the same one the sibling token suite uses.
TOKEN = "s3cret"


@pytest.fixture
def authed(tmp_path, monkeypatch):
    """A running, TOKEN-AUTHED server + an empty registered project.

    Auth is ON for the whole fixture — the condition the bugs needed.
    """
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.setenv("ANCHOR_TOKEN", TOKEN)

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

    pid = rnd_registry.add_project("AuthOnSteward", str(repo),
                                   scaffold=False)["id"]

    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777, "a test server must never bind the live Anchor port"
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        yield {"gui": gui, "repo": repo, "pid": pid,
               "base": f"http://127.0.0.1:{port}", "port": port}
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
        th.join(timeout=5)
        try:
            import pty_manager
            pty_manager._reset_live_table_for_tests()
        except Exception:
            pass


def test_set_a_goal_in_the_browser_with_auth_on(authed):
    """THE user path: open the project window, expand the steward chamber, type
    a goal, press [Set the goal] — and it is SAVED.

    Asserts the two failure signatures by name (a token re-prompt, and the
    "Unknown endpoint" refusal) plus the real outcome on disk.
    """
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    repo, pid, base = authed["repo"], authed["pid"], authed["base"]
    goal = "Prove a goal can be set with auth on."

    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        # A window that ALREADY holds a good token — John's window. Any prompt
        # from here is the bug, so record calls and cancel (never reload).
        pg.add_init_script(
            "window.localStorage.setItem('anchor_token', '%s');"
            "window.__promptCalls = [];"
            "window.prompt = function(){ window.__promptCalls.push(1); "
            "return null; };" % TOKEN)
        try:
            # domcontentloaded, NOT networkidle: an authed project window keeps
            # long-lived streams open, so "network idle" never arrives.
            pg.goto(f"{base}/project/{pid}", wait_until="domcontentloaded")
            pg.wait_for_selector("#tile-ecgseal", timeout=15000)

            # The chamber tile mounts its content on expand.
            pg.click("#tile-ecgseal > summary")
            pg.wait_for_selector("#ecgStandUpGoal", timeout=15000)

            pg.fill("#ecgStandUpGoal", goal)
            pg.click("#ecgSealHost button.gold")

            # The steward answers in the conversation. Wait for EITHER outcome
            # so a failure reports the real message instead of timing out.
            pg.wait_for_function(
                "() => {var c = document.getElementById('ecgConvo');"
                "return c && /saved|Couldn't do that|didn't answer/i"
                ".test(c.textContent);}", timeout=30000)
            said = pg.evaluate(
                "document.getElementById('ecgConvo').textContent")

            assert "Unknown endpoint" not in said, (
                "the stand-up POST did not reach its handler: %r" % said[-300:])
            assert "Couldn't do that" not in said, said[-300:]
            assert pg.evaluate("window.__promptCalls.length") == 0, (
                "a window holding a valid token must never be re-prompted")
            assert "saved" in said.lower(), said[-300:]
        finally:
            b.close()

    # The outcome, not the plumbing: the Face carries John's words verbatim.
    face = repo / "ECGBERHT.md"
    assert face.is_file(), "ECGBERHT.md must be created on confirm"
    assert goal in face.read_text(encoding="utf-8"), \
        "the North Star must be the user's own words, verbatim"
    assert (repo / "strip.json").is_file(), "the Strip must be created too"


def test_every_mutating_steward_endpoint_answers_with_auth_on(authed):
    """Every steward POST reaches its handler when auth is ON.

    A cheap, no-browser guard over the same class: not 401 (token transport)
    and not 404 (dispatch/registration). It says nothing about the engine's
    answer — only that the endpoint is REACHABLE, which is what broke.
    """
    import http.client

    pid, port = authed["pid"], authed["port"]

    def _post(path, payload):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=180)
        c.request("POST", path, body=json.dumps(payload).encode(), headers={
            "Content-Type": "application/json", "X-Anchor-Token": TOKEN})
        r = c.getresponse()
        r.read()
        c.close()
        return r.status

    calls = [
        ("/api/ecgberht/stand_up",
         {"project_id": pid, "north_star": "Reachability probe.",
          "who": "john"}),
        ("/api/ecgberht/speak",
         {"project_id": pid, "kind": "speak", "text": "where is this project"}),
        ("/api/ecgberht/high_seat_act", {"kind": "speak", "text": "where are we"}),
    ]
    for path, payload in calls:
        status = _post(path, payload)
        assert status != 401, "%s: token transport broken (401)" % path
        assert status != 404, (
            "%s: unreachable (404 'Unknown endpoint') — check the route row is "
            "registered in _MIGRATED_HANDLERS" % path)


def test_read_endpoints_answer_with_the_query_token_with_auth_on(authed):
    """The GET side of the same surface, over the transport the browser uses.

    NOTE (documented asymmetry, deliberately NOT changed here): a GET gates on
    ``?token=`` and does NOT accept the X-Anchor-Token header, while a POST
    accepts the header and NOT the query. The browser sends the right one on
    each, but the mismatch is a real trap for anyone writing a new call site —
    widening either side is an auth-surface decision, not a drive-by fix.
    """
    import http.client

    pid, port = authed["pid"], authed["port"]

    def _get(path, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=120)
        c.request("GET", path, headers=headers or {})
        r = c.getresponse()
        r.read()
        c.close()
        return r.status

    for path in ("/api/ecgberht/chamber?project_id=%s&token=%s" % (pid, TOKEN),
                 "/api/ecgberht/high_seat?token=%s" % TOKEN,
                 "/api/ecgberht/high_seat_badge?token=%s" % TOKEN,
                 "/api/rnd/friction?limit=3&token=%s" % TOKEN):
        assert _get(path) == 200, path

    # The asymmetry, pinned so a future change to it is deliberate.
    assert _get("/api/ecgberht/high_seat", {"X-Anchor-Token": TOKEN}) == 401


# ── The chamber's buttons must DO something (2026-07-31) ────────────────────
# John: "when I try to click the refine button nothing would happen". The goal
# bar's [Still the goal] / [Refine it] and the opening message's two actions
# were appended with no onclick — four dead buttons. Each declares a closed act
# in the engine view model, so each now speaks its canonical utterance through
# the existing /api/ecgberht/speak compiler; refine_goal, which needs the new
# goal text as an argument, prefills the say line instead of auto-sending.

def _chamber_with_goal(pg, base, pid, goal="Original goal for the chamber."):
    """Stand a project up (so the FULL chamber renders, not the stand-up
    screen) and return the page sitting in the open chamber."""
    pg.goto(f"{base}/project/{pid}", wait_until="domcontentloaded")
    pg.wait_for_selector("#tile-ecgseal", timeout=15000)
    pg.click("#tile-ecgseal > summary")
    pg.wait_for_selector("#ecgStandUpGoal", timeout=15000)
    pg.fill("#ecgStandUpGoal", goal)
    pg.click("#ecgSealHost button.gold")
    pg.wait_for_function(
        "() => {var c = document.getElementById('ecgConvo');"
        "return c && /saved/i.test(c.textContent);}", timeout=30000)
    # Re-open: the chamber now renders the goal bar + roadmap rail.
    pg.reload(wait_until="domcontentloaded")
    pg.click("#tile-ecgseal > summary")
    pg.wait_for_selector("#ecgGoalBar", timeout=15000)


def test_chamber_buttons_are_wired_not_decorative(authed):
    """Every chamber action button carries a click handler and a compiles-to
    hint — none is a bare label."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    pid, base = authed["pid"], authed["base"]
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.add_init_script(
            "window.localStorage.setItem('anchor_token', '%s');"
            "window.prompt = function(){ return null; };" % TOKEN)
        try:
            _chamber_with_goal(pg, base, pid)
            wired = pg.evaluate(
                "() => Array.from(document.querySelectorAll("
                "'#ecgGoalBar button, #ecgConvo .ecg-msg.steward .act button'))"
                ".map(b => ({label: b.textContent, wired: !!b.onclick}))")
            assert wired, "the chamber rendered no action buttons at all"
            dead = [w["label"] for w in wired if not w["wired"]]
            assert not dead, f"decorative (unwired) chamber buttons: {dead}"
        finally:
            b.close()


def test_refine_it_prefills_the_say_line_and_sends_nothing(authed):
    """[Refine it] hands John the cursor — it must NOT auto-send a rewrite."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    repo, pid, base = authed["repo"], authed["pid"], authed["base"]
    original = "Original goal for the chamber."
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.add_init_script(
            "window.localStorage.setItem('anchor_token', '%s');"
            "window.prompt = function(){ return null; };" % TOKEN)
        try:
            _chamber_with_goal(pg, base, pid, original)
            # The goal bar shows the goal WITHOUT its markdown decoration.
            shown = pg.evaluate(
                "document.querySelector('#ecgGoalBar .txt').textContent")
            assert shown.strip() == original, shown
            assert ">" not in shown and "---" not in shown, \
                f"raw markdown leaked into the goal bar: {shown!r}"

            pg.click("#ecgGoalBar button:not(.gold)")   # [Refine it]
            say = pg.input_value("#ecgSayInput")
            assert say.lower().startswith("refine goal to"), say
            assert pg.evaluate(
                "document.activeElement && document.activeElement.id") \
                == "ecgSayInput", "the say line must take focus"
        finally:
            b.close()

    # Nothing was sent, so the Face still carries the ORIGINAL goal.
    assert original in (repo / "ECGBERHT.md").read_text(encoding="utf-8")


def test_still_the_goal_speaks_and_the_steward_answers(authed):
    """[Still the goal] compiles through the real speak path and is answered."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    pid, base = authed["pid"], authed["base"]
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.add_init_script(
            "window.localStorage.setItem('anchor_token', '%s');"
            "window.prompt = function(){ return null; };" % TOKEN)
        try:
            _chamber_with_goal(pg, base, pid)
            before = pg.evaluate(
                "document.querySelectorAll('#ecgConvo .ecg-msg').length")
            pg.click("#ecgGoalBar button.gold")          # [Still the goal]
            # John's line lands, then the steward answers — never silence.
            pg.wait_for_function(
                "n => document.querySelectorAll('#ecgConvo .ecg-msg').length "
                ">= n + 2", arg=before, timeout=30000)
            said = pg.evaluate("document.getElementById('ecgConvo').textContent")
            assert "didn't understand" not in said.lower(), said[-300:]
            assert "didn't answer" not in said.lower(), said[-300:]
        finally:
            b.close()


def test_say_line_grows_with_dictated_text_and_enter_sends(authed):
    """The say line is a GROWING textarea, not a one-line input.

    John dictates paragraphs into the chamber — "it didn't show everything I was
    typing ... the window didn't grow as I spoke". A one-line <input> scrolled
    his own words out of sight before he could read them back. Enter still
    sends; Shift+Enter must make a newline instead (dictation emits newlines).
    """
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    pid, base = authed["pid"], authed["base"]
    para = ("I want this project to stand up a full campaign plan. " * 6).strip()

    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.add_init_script(
            "window.localStorage.setItem('anchor_token', '%s');"
            "window.prompt = function(){ return null; };" % TOKEN)
        try:
            _chamber_with_goal(pg, base, pid)
            assert pg.eval_on_selector("#ecgSayInput", "el => el.tagName") \
                == "TEXTAREA", "the say line must be a growing textarea"

            one_row = pg.eval_on_selector(
                "#ecgSayInput", "el => el.getBoundingClientRect().height")
            pg.fill("#ecgSayInput", para)
            pg.eval_on_selector(
                "#ecgSayInput",
                "el => el.dispatchEvent(new Event('input', {bubbles: true}))")
            grown = pg.eval_on_selector(
                "#ecgSayInput", "el => el.getBoundingClientRect().height")
            assert grown > one_row, (
                "the say line must GROW with dictated text (was %s, now %s)"
                % (one_row, grown))
            # Everything typed is visible, not scrolled out of sight.
            assert pg.eval_on_selector(
                "#ecgSayInput", "el => el.scrollHeight - el.clientHeight <= 2"), \
                "the grown box must show the whole paragraph, not scroll it away"

            # Shift+Enter is a newline (dictation), plain Enter sends.
            pg.click("#ecgSayInput")
            pg.keyboard.press("Shift+Enter")
            assert "\n" in pg.input_value("#ecgSayInput"), \
                "Shift+Enter must insert a newline, not send"
            before = pg.evaluate(
                "document.querySelectorAll('#ecgConvo .ecg-msg').length")
            pg.keyboard.press("Enter")
            pg.wait_for_function(
                "n => document.querySelectorAll('#ecgConvo .ecg-msg').length > n",
                arg=before, timeout=30000)
            assert pg.input_value("#ecgSayInput") == "", \
                "sending must clear the say line"
        finally:
            b.close()
