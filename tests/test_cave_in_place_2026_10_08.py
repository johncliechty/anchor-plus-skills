"""W4 of the night of 2026-10-08 (John, that morning: "It seems that Anchor is rebuilding AI Cockpits, I thought that
was not supposed to happen for the open ones"): the Cave never rebuilds an open card. Every change to the record - the
steward's own (the stamp), an act, its undo, an act refused in part, a verb from the composer, a verb said in the Cave's
dialogue (whole or in part), a project made either way, a card that leaves the shelves, the health banner - is placed in
the page as it stands. The open card's frame (its window), the words he left in it, its focus and its stream survive
each one; a stale page (build mismatch) waits until the card closes.

Painted proof on the real page and its real scripts, in a real browser, against a scripted origin (no server, never
:8777). Shown to FAIL on the scripts before W4: set ANCHOR_W4_STATIC to a folder holding the old high-seat-page.js and
steward-dialogue.js (git show <old>:static/...)."""
import json
import os
import sys
from urllib.parse import parse_qs, urlparse

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import high_seat_page as hsp  # noqa: E402
import test_high_seat_page_2026_09_26 as base  # noqa: E402

ORIGIN = "http://cave.test"
MBA = "6765ece4b3bc43b0b0b0907b92b17280"
TRUSTS = "9405abe0"
THIRD = "p3abc"
STATIC = os.environ.get("ANCHOR_W4_STATIC") or ""

FRAME = """<!doctype html><html><body><textarea id="box"></textarea><script>
window.__ident = Math.random().toString(36).slice(2);
window.__stream = 0; setInterval(function () { window.__stream++; }, 100);
var q = new URLSearchParams(location.search), inst = q.get('inst');
function say(m) { m.proto = 'anchor-tile'; m.inst = inst; parent.postMessage(m, location.origin); }
say({ kind: 'ready' }); say({ kind: 'state', light: 'quiet', alive: true, busy: false, word: 'listening' });
</script></body></html>"""


class Cave:
    """The scripted origin: the record (who sits where, the banner, the stamp) and the answers the routes give."""

    def __init__(self):
        self.seats = {"mba-project": ("active", 0), "trusts-project": ("active", 1), "third-project": ("", None)}
        self.banner = None
        self.stamp = "s1"
        self.next_campaign = None      # the answer POST /api/high-seat/campaign gives next, and the seats it leaves
        self.next_say = None           # the answer /api/ecgberht/high_seat_say gives next
        self.next_steward = None       # the answer /api/steward/say gives next
        self.loads = 0
        self.names = {}                # step id -> a new name (a rename)
        self.refuse = False            # the events stream answers 401 (a rotated token)
        self.health = "h1"             # /api/version's fingerprint of the banner's facts (W3)
        self.hold = False              # hold the next answers until release() (ChatGPT W4 r3: focus restored first)
        self.held = []
        self.projects = []             # projects made in this run: they join the registry (the "in no goal" row)

    def steps(self):
        out = [s for s in base._steps() if s["id"] not in ("mba-project",)]
        out.append({"id": "mba-project", "name": "MBA Teaching AI (the project)", "status": "proposed", "ref": "project:" + MBA, "navigation": {"path": ["mba-teaching"]}})
        out.append({"id": "trusts-project", "name": "The trusts' cockpit", "status": "proposed", "ref": "project:" + TRUSTS, "navigation": {"path": ["trusts"]}})
        out.append({"id": "third-project", "name": "The third cockpit", "status": "proposed", "ref": "project:" + THIRD, "navigation": {"path": ["trusts"]}})
        for s in out:
            if s["id"] in self.names:
                s["name"] = self.names[s["id"]]
            seat = self.seats.get(s["id"])
            if seat and seat[0]:
                s["seat"], s["seat_order"] = seat
        return out

    def html(self):
        ctx = base._ctx()
        ctx["entries"] = ctx["entries"] + [{"id": THIRD, "name": "Third", "folder_path": "C:/x/third", "blurb": "", "group": "Ungrouped", "state": "active"}] \
            + [{"id": "made-%d" % i, "name": n, "folder_path": "C:/x/" + n, "blurb": "", "group": "Ungrouped", "state": "active"} for i, n in enumerate(self.projects)]
        for i, n in enumerate(self.projects):
            ctx["facts"]["made-%d" % i] = {"id": "made-%d" % i, "name": n, "href": "", "needs_you": "", "next": "", "why": "", "summary": None, "summary_age_s": None, "dated": [], "nearest_due": "", "has_record": False}
        ctx["facts"][THIRD] = {"id": THIRD, "name": "Third", "href": "/project/" + THIRD, "needs_you": "", "next": "the third's next", "why": "", "summary": None, "summary_age_s": None, "dated": [], "nearest_due": "", "has_record": True}
        resolved = dict(base._resolved())
        resolved["trusts-project"] = {"kind": "project", "pid": TRUSTS, "name": "Family <Trusts>", "what": "", "state": "", "date": "", "href": "/project/" + TRUSTS, "broken": False, "gap": ""}
        resolved["third-project"] = {"kind": "project", "pid": THIRD, "name": "Third", "what": "", "state": "", "date": "", "href": "/project/" + THIRD, "broken": False, "gap": ""}
        ctx["initiatives"] = hsp.campaign_initiatives(self.steps(), resolved)
        ctx["rows"] = list(ctx["rows"]) + ([{"rule": "health", "text": self.banner, "why": "the morning self-test", "href": "/doctor"}] if self.banner else [])
        ctx["stamp"] = self.stamp
        ctx["auth_required"] = False
        return hsp.render_high_seat_html(ctx)

    def serve(self, route):
        req = route.request
        u = urlparse(req.url)
        path, q = u.path, parse_qs(u.query)

        def js(obj, status=200):
            route.fulfill(status=status, content_type="application/json", body=json.dumps(obj))

        if self.hold and path in ("/api/high-seat/campaign", "/high-seat", "/api/ecgberht/high_seat_say", "/api/steward/say",
                                  "/api/rnd/new_project") and req.resource_type != "document":
            self.held.append(route)
            return None
        if path in ("/", "/high-seat"):
            if req.resource_type == "document":
                self.loads += 1
            return route.fulfill(status=200, content_type="text/html", body=self.html())
        if path == "/steward/v1" and q.get("embed"):
            return route.fulfill(status=200, content_type="text/html", body=FRAME)
        for prefix, folder in (("/static/", os.path.join(ROOT, "static")), ("/steward-static/", os.path.join(ROOT, "steward_cockpit", "static")), ("/vendor/", os.path.join(ROOT, "vendor"))):
            if path.startswith(prefix):
                name = path[len(prefix):]
                src = os.path.join(folder, *name.split("/"))
                if STATIC and prefix == "/static/" and name in ("high-seat-page.js", "steward-dialogue.js"):
                    src = os.path.join(STATIC, name)
                if not os.path.isfile(src):
                    return route.fulfill(status=404, body="")
                ctype = "text/css" if name.endswith(".css") else "application/javascript" if name.endswith(".js") else "application/octet-stream"
                with open(src, "rb") as fh:
                    return route.fulfill(status=200, content_type=ctype, body=fh.read())
        if path == "/api/version":
            return js({"version": "test", "health": self.health})
        if path == "/api/auth/login":
            self.refuse = False
            return js({"ok": True})
        if path == "/api/steward/events":
            if self.refuse:
                return js({"error": "not logged in"}, status=401)
            return js({"events": [], "state": {"epoch": 1, "alive": True, "busy": False}, "stamp": self.stamp})
        if path == "/api/high-seat/card":
            return js({"html": '<div class="cbrief"><div class="cp-quiet">the brief</div></div>'})
        if path == "/api/high-seat/projects":
            return js({"html": ""})
        if path == "/api/high-seat/campaign":
            answer, seats = self.next_campaign or ({"ok": False, "receipt": "unscripted"}, None)
            self.next_campaign = None
            if seats:
                self.seats.update(seats)
            return js(answer)
        if path == "/api/ecgberht/high_seat_say":
            answer, seats = self.next_say or ({"ok": True, "talk": True}, None)
            self.next_say = None
            if seats:
                self.seats.update(seats)
            return js(answer)
        if path == "/api/steward/say":
            answer, seats = self.next_steward or ({"ok": True}, None)
            self.next_steward = None
            if seats:
                self.seats.update(seats)
            return js(answer)
        if path == "/api/rnd/new_project":
            self.projects.append("New2")
            return js({"ok": True, "message": "Project \u201cNew\u201d created."})
        return js({}, status=404)


def _release(world):
    world.hold = False
    held, world.held = world.held, []
    for r in held:
        world.serve(r)


@pytest.fixture()
def cave():
    world = Cave()
    with sync_api.sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1500, "height": 1000})
        page.route("**/*", world.serve)
        page.goto(ORIGIN + "/high-seat")
        page.evaluate("window.__page = Math.random().toString(36).slice(2)")
        page.wait_for_timeout(4500)   # the Active cards' views preload (one every 1.5 s) before he opens one
        yield world, page
        b.close()


def _open(page, pid):
    page.click("#card-%s .t-name" % pid)
    page.wait_for_selector("#card-%s.open iframe.cframe" % pid)
    frame = page.wait_for_function("() => { var f = document.querySelector('#card-%s.open iframe.cframe'); return f && f.contentWindow && f.contentWindow.__ident; }" % pid)
    return frame.json_value()


def _frame_state(page, pid):
    return page.evaluate("""(pid) => {
        var f = document.querySelector('#card-' + pid + '.open iframe.cframe'); if (!f) return null;
        var w = f.contentWindow;
        return { page: window.__page || null, ident: w.__ident, stream: w.__stream, draft: w.document.getElementById('box').value,
                 focus: document.activeElement === f && w.document.activeElement === w.document.getElementById('box') };
    }""", pid)


def _type_into(page, pid, words):
    frame = page.query_selector("#card-%s iframe.cframe" % pid).content_frame()
    frame.click("#box")
    frame.fill("#box", words)


def _survived(page, pid, ident, before, focus=True, what=""):
    page.wait_for_timeout(300)
    now = _frame_state(page, pid)
    assert now is not None, "%s: the open card is gone" % what
    assert now["page"] == before["page"], "%s: the page was reloaded" % what
    assert now["ident"] == ident, "%s: the open card's frame was rebuilt" % what
    assert now["draft"] == before["draft"], "%s: his words in the card were lost" % what
    assert now["stream"] > before["stream"], "%s: the card's stream stopped" % what
    if focus:
        assert now["focus"], "%s: the focus left his box" % what
    return now


def _receipt(page, text):
    page.wait_for_function("(t) => { var r = document.getElementById('receiptText'); return r && r.textContent.indexOf(t) >= 0; }", arg=text, timeout=8000)


def _held(world, page, pid, action):
    """ChatGPT W4 r3-r4: the answers are HELD while he goes back to his box; then released - focus must survive."""
    world.hold = True
    action()
    page.wait_for_timeout(250)
    frame = page.query_selector("#card-%s iframe.cframe" % pid).content_frame()
    frame.focus("#box")
    assert _frame_state(page, pid)["focus"]
    for _ in range(12):                       # the act, then the fresh render it asks for (and any after)
        page.wait_for_timeout(250)
        _release(world)
    world.hold = False


def test_an_open_card_survives_every_change_to_the_record(cave):
    world, page = cave
    ident = _open(page, MBA)
    _type_into(page, MBA, "the words I was dictating")
    st = _frame_state(page, MBA)
    assert st["draft"] == "the words I was dictating" and st["focus"] and st["page"]

    # 1. the steward changed the record (the stamp), and the health banner came up - while the card is open
    world.seats["third-project"] = ("deck", 0)
    world.banner = "Health check found issues"
    world.stamp = "s2"
    page.wait_for_selector("#shDeck #card-%s" % THIRD, timeout=8000)
    page.wait_for_selector(".healthbar", timeout=8000)
    assert "Health check found issues" in page.inner_text(".healthbar")
    st = _survived(page, MBA, ident, st, what="the steward's change and the banner")

    # 2. the banner's words change in place
    world.banner = "Health check: fix verified, live after your restart"
    world.stamp = "s3"
    page.wait_for_function("() => (document.querySelector('.healthbar') || {}).textContent.indexOf('fix verified') >= 0", timeout=8000)
    st = _survived(page, MBA, ident, st, what="the banner's new words")

    # 3. an act: the third card's x sends it home; the receipt and its undo stay
    world.next_campaign = ({"ok": True, "receipt": "Sent home.", "undo": {"act": "seat", "step": "third-project", "seat": "deck"}}, {"third-project": ("", None)})
    _held(world, page, MBA, lambda: page.click("#card-%s .t-x" % THIRD))
    _receipt(page, "Sent home.")
    page.wait_for_selector("#card-%s" % THIRD, state="detached", timeout=8000)
    assert page.is_visible("#undoBtn")
    st = _survived(page, MBA, ident, st, what="an act")

    # 4. its undo
    world.next_campaign = ({"ok": True, "receipt": "Undone."}, {"third-project": ("deck", 0)})
    _held(world, page, MBA, lambda: page.click("#undoBtn"))
    _receipt(page, "Undone.")
    page.wait_for_selector("#shDeck #card-%s" % THIRD, timeout=8000)
    st = _survived(page, MBA, ident, st, what="the undo")

    # 5. an act the writer refused in part: the refusal and its undo are his, the part that landed is placed
    world.next_campaign = ({"ok": False, "receipt": "Refused in part.", "undo": {"act": "seat", "step": "third-project", "seat": "deck"}}, {"third-project": ("", None)})
    _held(world, page, MBA, lambda: page.click("#card-%s .t-x" % THIRD))
    _receipt(page, "Refused in part.")
    page.wait_for_selector("#card-%s" % THIRD, state="detached", timeout=8000)
    st = _survived(page, MBA, ident, st, what="an act refused in part")

    # 6. a verb from the composer (the High Seat's own route)
    world.next_say = ({"ok": True, "say": "Seated on deck.", "campaign_act": True, "undo": None}, {"third-project": ("deck", 0)})
    page.fill("#say", "put the third on deck")
    _held(world, page, MBA, lambda: page.click("#sendBtn"))
    _receipt(page, "Seated on deck.")
    page.wait_for_selector("#shDeck #card-%s" % THIRD, timeout=8000)
    st = _survived(page, MBA, ident, st, what="a composer verb")

    # 7. a verb said in the Cave's dialogue (the steward's route) - whole
    world.next_steward = ({"ok": True, "say": "Moved to active.", "campaign_act": True, "undo": None}, {"third-project": ("active", 2)})
    page.fill("#say", "make the third active")
    _held(world, page, MBA, lambda: page.click("#sendBtn"))
    _receipt(page, "Moved to active.")
    page.wait_for_selector("#shActive #card-%s" % THIRD, timeout=8000)
    st = _survived(page, MBA, ident, st, what="a dialogue verb")

    # 8. ... and in part
    world.next_steward = ({"ok": False, "say": "Part of it was refused.", "undo": {"act": "seat", "step": "third-project", "seat": "active"}}, {"third-project": ("", None)})
    page.fill("#say", "send the third home and more")
    _held(world, page, MBA, lambda: page.click("#sendBtn"))
    _receipt(page, "Part of it was refused.")
    page.wait_for_selector("#card-%s" % THIRD, state="detached", timeout=8000)
    st = _survived(page, MBA, ident, st, what="a dialogue verb landed in part")

    # 9. a project made in the small window (it reports back by message) - it joins the registry's "in no goal" row
    world.projects.append("Newly made")
    _held(world, page, MBA, lambda: page.evaluate("window.postMessage({anchor: 'project-created', entry: {name: 'Newly made'}}, location.origin)"))
    _receipt(page, "created")
    page.wait_for_selector("#ptile .orphans .orphan[data-name='Newly made']", state="attached", timeout=8000)
    st = _survived(page, MBA, ident, st, what="a project made in the small window")

    # 10. ... and from the composer's confirm card
    world.next_say = ({"ok": True, "say": "Create it?", "project_create": {"folder": "C:/x/new2", "name": "New2"}}, None)
    page.fill("#say", "start a new project called New2 at C:/x/new2")
    page.click("#sendBtn")
    page.wait_for_selector("#pcCard .pc-go", timeout=8000)
    _held(world, page, MBA, lambda: page.click("#pcCard .pc-go"))
    _receipt(page, "Project \u201cNew\u201d created.")
    page.wait_for_selector("#ptile .orphans .orphan[data-name='New2']", state="attached", timeout=8000)
    st = _survived(page, MBA, ident, st, what="a project made from the confirm card")
    assert world.loads == 1, "the page was loaded again"


def test_nothing_moves_while_he_dictates_and_the_open_card_keeps_its_place_on_screen(cave):
    world, page = cave
    page.set_viewport_size({"width": 1500, "height": 560})
    ident = _open(page, MBA)
    _type_into(page, MBA, "dictating now")
    frame = page.query_selector("#card-%s iframe.cframe" % MBA).content_frame()
    frame.evaluate("say({ kind: 'typing', active: true })")     # the cockpit view reports dictation (Win+H types into it)
    st = _frame_state(page, MBA)
    top0 = page.evaluate("document.querySelector('#card-%s').getBoundingClientRect().top" % MBA)
    world.seats["third-project"] = ("deck", 0)
    world.banner = "Health check found issues"                # a banner ABOVE the open card
    world.stamp = "s2"
    page.wait_for_timeout(4000)
    assert page.query_selector("#shDeck #card-%s" % THIRD) is None and page.query_selector(".healthbar") is None, \
        "nothing is placed while he dictates"
    frame.evaluate("say({ kind: 'typing', active: false })")
    page.wait_for_selector("#shDeck #card-%s" % THIRD, timeout=8000)
    page.wait_for_selector(".healthbar", timeout=8000)
    _survived(page, MBA, ident, st, what="placement after dictation")
    top1 = page.evaluate("document.querySelector('#card-%s').getBoundingClientRect().top" % MBA)
    assert abs(top1 - top0) < 2, "the open card moved on screen: %s -> %s" % (top0, top1)


def test_a_change_that_moves_the_open_card_waits_until_it_closes(cave):
    world, page = cave
    ident = _open(page, MBA)
    _type_into(page, MBA, "half a sentence")
    st = _frame_state(page, MBA)
    # the record takes the open card off the shelves and puts the third on deck: the third is placed, the open card stays
    world.seats["mba-project"] = ("", None)
    world.seats["third-project"] = ("deck", 0)
    world.stamp = "s2"
    page.wait_for_selector("#shDeck #card-%s" % THIRD, timeout=8000)
    _survived(page, MBA, ident, st, what="a change that removes the open card")
    # he closes the card: the held change lands
    page.click("#card-%s .t-name" % MBA)
    page.wait_for_selector("#card-%s" % MBA, state="detached", timeout=8000)
    assert world.loads == 1


def test_a_stale_page_waits_for_the_open_card_then_reloads(cave):
    world, page = cave
    ident = _open(page, TRUSTS)
    _type_into(page, TRUSTS, "kept words")
    st = _frame_state(page, TRUSTS)
    world.next_steward = ({"ok": False, "error": "build-mismatch"}, None)
    page.fill("#say", "a question for the steward")
    page.click("#sendBtn")
    _receipt(page, "older than the server")
    page.wait_for_timeout(6000)   # the held reload's own five-second check passes while the card is open
    _survived(page, TRUSTS, ident, st, focus=False, what="a build mismatch while the card is open")
    assert world.loads == 1
    page.click("#card-%s .t-name" % TRUSTS)   # closed: now the page renews once
    page.wait_for_function("() => !window.__page", timeout=10000)
    assert world.loads == 2


def test_focus_survives_an_act_and_a_renamed_card_is_made_again(cave):
    world, page = cave
    ident = _open(page, MBA)
    _type_into(page, MBA, "keep my place")
    st = _frame_state(page, MBA)
    world.next_campaign = ({"ok": True, "receipt": "Seated.", "undo": None}, {"third-project": ("deck", 0)})
    world.names["trusts-project"] = "The trusts, renamed"
    page.evaluate("document.querySelector('#camp').classList.add('open')")
    page.click("#camp .grow[data-g='trusts'] .gh")
    world.hold = True                         # the act's answer and the fresh page wait ...
    page.click("#camp [data-seat='deck'][data-step='third-project']")
    page.wait_for_timeout(300)
    assert world.held, "the act is held"
    frame = page.query_selector("#card-%s iframe.cframe" % MBA).content_frame()
    frame.focus("#box")                       # ... while he goes back to his box
    assert _frame_state(page, MBA)["focus"]
    _release(world)
    page.wait_for_timeout(300)
    _release(world)                           # the fresh render the act asked for
    _receipt(page, "Seated.")
    page.wait_for_selector("#shDeck #card-%s" % THIRD, timeout=8000)
    page.wait_for_function("() => (document.querySelector('#card-%s .t-nm') || {}).textContent === 'The trusts, renamed'" % TRUSTS, timeout=8000)
    _survived(page, MBA, ident, st, focus=True, what="an act, his focus back in the box")
    assert world.loads == 1


def test_a_login_taken_in_place_resumes_the_dialogue(cave):
    world, page = cave
    world.refuse = True
    page.wait_for_function("() => (document.getElementById('exState') || {}).getAttribute && document.getElementById('exState').getAttribute('data-state') === 'auth'", timeout=10000)
    ident = _open(page, MBA)
    st = _frame_state(page, MBA)
    page.evaluate("document.getElementById('loginBox').hidden = false")
    page.fill("#loginTok", "a-token")
    page.click("#loginGo")
    _receipt(page, "Logged in")
    world.seats["third-project"] = ("deck", 0)
    world.stamp = "s9"                          # heard only through the resumed stream
    page.wait_for_selector("#shDeck #card-%s" % THIRD, timeout=10000)
    _survived(page, MBA, ident, st, focus=False, what="a login")
    assert world.loads == 1


def test_a_banner_that_changes_with_no_record_change_is_placed_in_place(cave):
    """W3: a report or a verified candidate changes the banner while nothing in the record moves - the version poll's
    fingerprint brings it in, the open card untouched (two 30-second polls: the first learns the fingerprint)."""
    world, page = cave
    ident = _open(page, MBA)
    _type_into(page, MBA, "reading")
    st = _frame_state(page, MBA)
    page.wait_for_timeout(31000)
    world.banner = "Health check found issues"
    world.health = "h2"
    page.wait_for_selector(".healthbar", timeout=40000)
    _survived(page, MBA, ident, st, what="a banner from the health fingerprint")
    assert world.loads == 1
