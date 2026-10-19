# The chamber PAGE — the real-browser gate for the surface John actually opens.
#
# AUTH-ON: enforced
#
# WHY THIS FILE EXISTS. Every automated gate stayed green for twelve waves
# while the chamber deleted itself on open, because the gates compared markup
# STRINGS. The law that came out of that (Skill Foundry/ELEGANCE.md): *a gate
# that cannot see what the user sees is not a gate.* So this one opens a real
# browser against a real server and measures the things John complained about,
# in the units he complained in:
#
#   "it can't be little tiny windows"        -> the conversation gets the screen
#   "you have to scroll down"                -> it opens on the newest turn
#   "I need the scaffolding shown"           -> proposed steps RENDER
#   "where's the 10-minute status window?"   -> the strip is always present
#
# Each assertion here failed against the surface that shipped on 2026-08-14.
#
# (2026-08-25 cutover) The COCKPIT is the default /project/<id> page now; the
# chamber lives behind ?chamber=1 as the escape hatch until John retires it.
# This file keeps gating the CHAMBER surface, so its navigations carry
# ?chamber=1; the tokenless-lock gate also asserts the default (cockpit)
# document never inlines the transcript.
import json
import os
import sys
from pathlib import Path

import pytest

ANCHOR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ANCHOR))

# REQUIRED, never importorskip'd — a missing Playwright must fail loudly, or
# the pixels stop being checked and we are back where we started.
from playwright.sync_api import sync_playwright  # noqa: E402

from tests.chamber_harness import TEST_TOKEN, boot_server  # noqa: E402

import chamber_coldopen as co  # noqa: E402

VIEWPORT = {"width": 1600, "height": 1000}

#: The measured budget. The surface that shipped on 08-14 gave him 446px of
#: conversation out of 1000 and spent 762px on chrome. If chrome ever creeps
#: back past this line, that regression is the defect, not a style preference.
MAX_CHROME_PX = 90
MIN_CONVERSATION_PX = 700


def _at(i):
    return "2026-08-10T%02d:00:00Z" % (i % 24)


def _campaign(root, name):
    """A campaign shaped like his real one: a scaffolding that was FRAMED but
    never batch-confirmed (every step still `proposed`), plus a transcript long
    enough that opening at the top would bury the newest turn."""
    folder = root / name
    folder.mkdir()
    steps = [{"id": "s%d" % i, "name": "Stage %d" % i, "status": "proposed",
              "skill": "gandalf"} for i in range(1, 11)]
    events = [{"kind": "scaffold_proposal", "proposal_id": "prop-1",
               "goal": "Ship the thing.", "at": _at(10)}]
    (folder / "roadmap.json").write_text(json.dumps({
        "project_id": "proj-chamber-page", "as_of": _at(20),
        "roadmap_projection": steps, "roadmap_events": events,
    }), encoding="utf-8")
    ecg = folder / ".ecgberht"
    ecg.mkdir(exist_ok=True)
    (ecg / "conversation-log.json").write_text(json.dumps({
        "schema": "ecgberht-conversation-log-v0",
        "turns": [{"role": "john" if i % 2 == 0 else "steward",
                   "text": ("turn %d — " % i) + ("lorem ipsum " * 40)}
                  for i in range(30)],
    }), encoding="utf-8")
    co.cold_open_rebuild(folder)
    return folder


@pytest.fixture(scope="module")
def page_srv(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("chamber-page")
    srv = boot_server(tmp, token=TEST_TOKEN, auth_mode="enforce")
    try:
        import rnd_registry
        folder = _campaign(tmp, "camp-page")
        pid = rnd_registry.add_project("Chamber Page", str(folder),
                                       scaffold=False)["id"]
        yield {"srv": srv, "pid": pid, "folder": folder}
    finally:
        srv["stop"]()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture(scope="module")
def opened(page_srv, browser):
    ctx = browser.new_context(viewport=VIEWPORT)
    ctx.add_init_script(
        "try{localStorage.setItem('anchor_token','%s')}catch(e){}" % TEST_TOKEN)
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto("%s/project/%s?chamber=1&token=%s"
            % (page_srv["srv"]["base"], page_srv["pid"], TEST_TOKEN),
            wait_until="load")
    pg.wait_for_selector(".cpage", timeout=15000)
    pg.wait_for_timeout(900)
    yield pg, errors
    ctx.close()


def _metrics(pg):
    return pg.evaluate("""() => {
      const h = (s) => { const e = document.querySelector(s);
        return e ? Math.round(e.getBoundingClientRect().height) : 0; };
      const msgs = document.querySelector('.msgs');
      const say = document.querySelector('.saybox');
      return {
        chrome: h('.cbar') + h('.cnorth'),
        convo: h('.msgs'),
        at_newest: msgs
          ? (msgs.scrollHeight - msgs.scrollTop - msgs.clientHeight) < 60 : null,
        saybox_in_view: say
          ? say.getBoundingClientRect().bottom <= window.innerHeight + 1 : false,
        page_scrolls: document.body.scrollHeight > window.innerHeight + 2,
        steps: document.querySelectorAll('.fstep[data-step]').length,
        drafts: document.querySelectorAll('.fstep[data-draft]').length,
        strip: !!document.querySelector('.cstrip'),
        draft_banner: !!document.querySelector('.draftban'),
        cockpit_js: !!document.querySelector('script[src*="project-window.js"]'),
      };
    }""")


def test_the_conversation_gets_the_screen(opened):
    """"It can't be little tiny windows." 446px was the shipped number."""
    pg, _ = opened
    m = _metrics(pg)
    assert m["chrome"] <= MAX_CHROME_PX, (
        "chrome crept back to %dpx — every pixel of it is a pixel of "
        "conversation he loses" % m["chrome"])
    assert m["convo"] >= MIN_CONVERSATION_PX, (
        "the conversation is only %dpx tall" % m["convo"])


def test_it_opens_on_the_newest_turn_and_the_page_does_not_scroll(opened):
    """"You have all this dialog and you have to scroll down." The shipped
    surface opened at the OLDEST message with 7,215px hidden below."""
    pg, _ = opened
    m = _metrics(pg)
    assert m["at_newest"] is True, "the chamber did not open on the newest turn"
    assert m["saybox_in_view"], "the say box is below the fold"
    assert not m["page_scrolls"], "the page scrolls — it must fit the viewport"


def test_a_proposed_scaffolding_is_shown_not_hidden(opened):
    """"I need the scaffolding shown." R-PROPOSED-EXCLUDED filtered every
    still-proposed step off the rail, so his ten-step campaign rendered as an
    empty column. They render, and they say they are drafts."""
    pg, _ = opened
    m = _metrics(pg)
    assert m["steps"] == 10, "expected 10 rail steps, got %d" % m["steps"]
    assert m["drafts"] == 10, "proposed steps must be marked as drafts"
    assert m["draft_banner"], "an all-draft rail must say it is not confirmed"


def test_the_status_strip_is_always_present(opened):
    """"Where's the window that shows me the 10-minute status?"""
    pg, _ = opened
    assert _metrics(pg)["strip"], "the ⏱ status strip is missing"


def test_the_page_does_not_load_the_cockpit_bundle(opened):
    """Dead code sharing a document with live code is what deleted the M1
    chamber on every open for twelve waves. The page carries its own script."""
    pg, errors = opened
    assert not _metrics(pg)["cockpit_js"], "the page pulled in project-window.js"
    assert errors == [], "the page threw: %r" % (errors[:3],)


def test_the_status_strip_opens_the_status_window(opened):
    """"I thought the M1 dashboard had a status option — something that could
    pop up and show you the status, so I could get that 10-minute status
    update." chamber_status_overlay.py was built and had no caller here."""
    pg, _ = opened
    pg.click(".cstrip")
    pg.wait_for_selector(".ovl .dock", timeout=10000)
    text = pg.eval_on_selector(".ovl", "e => e.textContent")
    assert "Status" in text
    assert pg.query_selector(".ovl .ttable") is not None, (
        "the overlay must carry the latest ⏱ table, not just a title")
    pg.click(".ovl [data-overlay-close]")
    pg.wait_for_timeout(200)
    assert pg.query_selector(".ovl") is None, "the overlay must close"


def test_the_workbench_carries_what_he_kept(opened):
    """"I don't want to have to hit a button that says move me back to the
    cockpit, because then it loses all the functionality I have from the M1
    dashboard… I want Boneyard options, I want to open terminal, nice to have
    the Gandalf summary — basically the workbench."""
    pg, _ = opened
    tabs = pg.eval_on_selector_all(
        ".wtab", "els => els.map(e => e.getAttribute('data-wtab'))")
    assert set(tabs) == {"terminal", "gandalf", "files", "boneyard"}
    # closed by default — it must cost the conversation nothing
    assert not pg.eval_on_selector(
        "#workbench", "e => e.classList.contains('open')")
    pg.click('[data-wtab="boneyard"]')
    pg.wait_for_timeout(900)
    assert pg.eval_on_selector("#workbench", "e => e.classList.contains('open')")
    assert pg.query_selector(".wbody .whead input") is not None, (
        "the boneyard is searchable or it is not the boneyard")
    pg.click('[data-wtab="boneyard"]')          # clicking the live tab closes it
    pg.wait_for_timeout(200)
    assert not pg.eval_on_selector(
        "#workbench", "e => e.classList.contains('open')")


def test_the_page_says_how_fresh_it_is_and_can_be_refreshed(opened):
    """"What you've got there when you open MBA Teaching is out of date and I'm
    not sure why — I don't have a way of updating." """
    pg, _ = opened
    fresh = pg.eval_on_selector(".cbar .fresh", "e => e.textContent")
    # The fixture writes its ledger moments before the page opens, so this
    # campaign is legitimately LIVE — which is itself the signal he asked for:
    # "go look and see if there's a version of the steward process going."
    assert ("ago" in fresh or "never" in fresh or "just now" in fresh), (
        "the bar must say when this campaign was last touched, got %r" % fresh)
    assert pg.eval_on_selector(".cbar .fresh", "e => e.className").find("live") >= 0, (
        "a campaign written seconds ago must read as live, got %r" % fresh)
    assert pg.query_selector("[data-refresh]") is not None, (
        "there must be a way to make it look again without a terminal")


def test_the_page_paints_fast(page_srv, browser):
    """The classic chamber's budget was 2s to first paint, because it fetched
    and mounted after load. This page is rendered server-side, so the whole
    surface is in the first response — hold it to a tighter line, and notice if
    a fetch ever creeps back onto the open path."""
    ctx = browser.new_context(viewport=VIEWPORT)
    ctx.add_init_script(
        "try{localStorage.setItem('anchor_token','%s')}catch(e){}" % TEST_TOKEN)
    pg = ctx.new_page()
    pg.goto("%s/project/%s?chamber=1&token=%s"
            % (page_srv["srv"]["base"], page_srv["pid"], TEST_TOKEN),
            wait_until="load")
    # FCP is not reliably emitted in headless, so measure the navigation
    # itself — and prove the substance directly: the rail and the transcript
    # must arrive IN the document, with no fetch on the open path.
    ready_ms = pg.evaluate("""() => {
      const n = performance.getEntriesByType('navigation')[0];
      return n ? Math.round(n.domContentLoadedEventEnd - n.startTime) : null;
    }""")
    ctx.close()
    assert ready_ms is not None and ready_ms < 2000, "DOM ready %sms" % ready_ms

    import urllib.request
    url = ("%s/project/%s?chamber=1&token=%s"
           % (page_srv["srv"]["base"], page_srv["pid"], TEST_TOKEN))
    body = urllib.request.urlopen(url, timeout=10).read().decode("utf-8")
    assert body.count('data-step="') == 10, (
        "the rail must be in the SERVED HTML — the classic chamber fetched and "
        "mounted after load, which is what made a delete-on-open possible")
    assert 'class="msg ' in body, "the transcript must be served, not fetched"


def test_the_build_id_tracks_the_code_on_disk_not_the_last_commit():
    """The "I restarted and nothing changed" defect, made impossible.

    BUILD_ID was `git rev-parse --short HEAD`. It feeds the asset cache-buster,
    `window.ANCHOR_BUILD`, and `GET /api/version` — which open pages poll and
    reload on. Keyed on HEAD, all three froze for UNCOMMITTED work: the server
    restarted with new code, reported the same version, no page ever reloaded,
    and the only available advice ("refresh the browser") could not help,
    because the page was never told anything was new. A full day of edits
    shipped under one unchanging id that way.
    """
    import anchor_gui

    before = anchor_gui._compute_build_id()
    served = Path(anchor_gui.ANCHOR_DIR) / "static" / "chamber-page.css"
    assert served.is_file(), "the fingerprint must cover a file we actually serve"
    original = served.stat().st_mtime
    try:
        os.utime(served, (original + 5, original + 5))
        after = anchor_gui._compute_build_id()
    finally:
        os.utime(served, (original, original))
    assert after != before, (
        "the build id did not move when a served file changed — the redeploy "
        "signal is blind again, and every restart will look like nothing "
        "happened")
    assert anchor_gui._compute_build_id() == before, "it must be stable, too"


def test_the_page_carries_the_build_and_watches_for_a_redeploy(opened):
    """An open page must heal itself after a restart. Verified end-to-end
    (open page → touch a file → restart → the page reloaded itself in ~5s);
    this gate holds the two halves that make that possible."""
    pg, _ = opened
    build = pg.evaluate("() => window.ANCHOR_BUILD")
    assert build, "the page must know which build rendered it"
    src = (Path(__file__).resolve().parents[1] / "static" / "chamber-page.js"
           ).read_text(encoding="utf-8")
    assert "/api/version" in src and "location.reload" in src, (
        "the chamber page must poll for a redeploy and reload itself — the "
        "cockpit did this and the chamber did not, so an open chamber never "
        "learned the server had restarted")


def test_a_tokenless_viewer_never_reads_the_transcript(page_srv, browser):
    """Security audit P0. The chamber inlines the whole steward conversation
    server-side, and /project/ is historically an open route — so with a token
    configured, a tokenless document GET must receive the LOCK page: no
    transcript, no goal, no steps, no folder path. (This gate could not exist
    before: every prior request in this file carries the token, which is
    exactly why the leak was invisible to it.)"""
    import urllib.error
    import urllib.request
    url = "%s/project/%s" % (page_srv["srv"]["base"], page_srv["pid"])
    # Two acceptable refusal shapes: enforce mode 401s the document at the
    # data-plane gate (this harness); open/warn mode — John's actual host
    # default — serves the LOCK page. Either way the one thing that matters
    # is asserted on the actual bytes: the transcript never leaves.
    try:
        resp = urllib.request.urlopen(url, timeout=10)
        body, status = resp.read().decode("utf-8"), resp.status
    except urllib.error.HTTPError as e:
        body, status = e.read().decode("utf-8", "replace"), e.code
    assert status in (200, 401), "unexpected status %s" % status
    if status == 200:
        assert "token-locked" in body, "tokenless 200 without the lock page"
    assert "lorem ipsum" not in body, "TRANSCRIPT LEAKED to a tokenless viewer"
    assert "Stage 1" not in body, "the scaffolding leaked"
    assert "cpage" not in body, "the chamber itself leaked"
    # And WITH the token, the chamber escape hatch serves the full page…
    body2 = urllib.request.urlopen(url + "?chamber=1&token=" + TEST_TOKEN,
                                   timeout=10).read().decode("utf-8")
    assert "cpage" in body2 and "lorem ipsum" in body2
    # …while the DEFAULT page (the cockpit, since the 2026-08-25 cutover) is a
    # SHELL: it must never inline the transcript server-side — the data rides
    # the token-checked /api/steward routes instead.
    body3 = urllib.request.urlopen(url + "?token=" + TEST_TOKEN,
                                   timeout=10).read().decode("utf-8")
    assert "STEWARD_PID" in body3, "the default page is not the cockpit shell"
    assert "lorem ipsum" not in body3, (
        "the cockpit document inlined the transcript — the P0 class returned")


def test_closing_the_workbench_returns_the_screen(opened):
    """Elegance audit finding 3, second recurrence of the same CSS defect: a
    bare `.wbody.term` rule outranked `.wbody{display:none}`, so closing the
    workbench from the Terminal tab left an empty 34vh panel eating a third
    of the conversation. closeWorkbench must clear the class and the panel
    must actually disappear."""
    pg, _ = opened
    convo_before = pg.evaluate(
        "() => Math.round(document.querySelector('.msgs').getBoundingClientRect().height)")
    # Simulate the terminal tab's layout state without spawning a session,
    # then close — the regression is pure CSS + closeWorkbench.
    pg.evaluate("""() => {
      document.querySelector('#workbench').classList.add('open');
      document.querySelector('#wbody').className = 'wbody term';
    }""")
    pg.click("[data-wclose]")
    pg.wait_for_timeout(150)
    assert pg.evaluate("() => document.querySelector('#wbody').className") == "wbody"
    hidden = pg.evaluate(
        "() => getComputedStyle(document.querySelector('#wbody')).display")
    assert hidden == "none", "the closed panel still renders (display %s)" % hidden
    convo_after = pg.evaluate(
        "() => Math.round(document.querySelector('.msgs').getBoundingClientRect().height)")
    assert convo_after >= convo_before - 4, (
        "closing the workbench cost the conversation %dpx"
        % (convo_before - convo_after))


def test_hostile_strings_never_become_markup(browser):
    """The F5 injection law, applied to the new page.

    Needed because the page renders agent-authored text — steward replies,
    step names, the goal line — straight into HTML; an unescaped slot there is
    a live XSS sink, and it is the one gate class that protects HIM rather than
    a proof obligation. Dropping it costs the only mechanical evidence that
    every slot escapes.
    """
    import chamber_page

    payloads = [
        "<img src=x onerror=alert(1)>",
        "</div><script>window.__pwn=1</script>",
        "\" onmouseover=\"window.__pwn=1\"",
        "javascript:window.__pwn=1",
    ]
    view = {
        "steps": [{"id": p, "name": p, "status": "proposed", "draft": True,
                   "skill": p} for p in payloads],
        "eta": {}, "progress": {"done": 0, "total": len(payloads)},
        "live_run": {"skill": payloads[0], "step_id": payloads[1],
                     "at": payloads[2], "latest_status": payloads[0]},
        "deliverable": None,
        "goal": {"text": payloads[0]},
        "brief": {"stand": {"text": payloads[1]}},
        "dialogue": [{"role": "john", "text": p} for p in payloads]
                    + [{"role": "steward", "text": p} for p in payloads],
        "has_draft_steps": True,
    }
    html = chamber_page.render_chamber_page_html(
        view, steward={"label": payloads[0], "glyph": payloads[1]},
        project={"name": payloads[2], "folder_path": payloads[3]},
        efforts={"active": "campaign", "efforts": [
            {"id": "campaign", "name": payloads[0], "status": "active"},
            {"id": "e-deadbeef01", "name": payloads[1], "status": "active"},
        ]})

    ctx = browser.new_context(viewport=VIEWPORT)
    pg = ctx.new_page()
    alerts = []
    pg.on("dialog", lambda d: (alerts.append(d.message), d.dismiss()))
    pg.set_content(html)
    pg.wait_for_timeout(400)
    pwned = pg.evaluate("() => !!window.__pwn")
    injected = pg.evaluate(
        "() => document.querySelectorAll('img,script,iframe,object').length")
    # The text must SURVIVE, visibly — escaping that silently eats his content
    # would pass an injection test and fail him.
    shown = pg.evaluate("() => document.body.innerText")
    ctx.close()

    assert not pwned, "a payload executed"
    assert not alerts, "a payload opened a dialog: %r" % (alerts,)
    assert injected == 0, "%d injected element(s) reached the DOM" % injected
    assert "onerror" in shown, "the payload should render as visible TEXT"


def test_classic_is_still_reachable(page_srv, browser):
    """The escape hatch is load-bearing: it is the only reason retiring the
    cockpit from the default route is safe."""
    ctx = browser.new_context(viewport=VIEWPORT)
    ctx.add_init_script(
        "try{localStorage.setItem('anchor_token','%s')}catch(e){}" % TEST_TOKEN)
    pg = ctx.new_page()
    pg.goto("%s/project/%s?classic=1&token=%s"
            % (page_srv["srv"]["base"], page_srv["pid"], TEST_TOKEN),
            wait_until="load")
    assert pg.query_selector("#tile-ecgseal") is not None
    assert pg.query_selector(".cpage") is None
    ctx.close()
