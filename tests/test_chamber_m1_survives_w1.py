# chamber-m1 W1 — THE SURVIVAL TEST: opening the Seal leaves the painted M1
# chamber on screen AFTER the successor hydrate settles, on every branch —
# plus the drawn say box wired to /api/ecgberht/converse, the E1 refusal
# painted VISIBLE in the slice, and the abort-ban CI rule.
#
# AUTH-ON: enforced
#
# The defect this file exists to make impossible again: for twelve waves
# ecgSealMountInline painted M1, then hydrated v0 and dropped the slice on
# every branch — and every automated gate stayed green, because the one
# Playwright paint test aborted the /api/ecgberht/chamber hydrate route in
# the page. This test is the recurrence instrument (frozen plan, chamber-m1
# 2026-08-13): it opens the Seal in a REAL browser, lets BOTH the W6
# seal_open paint AND the successor hydrate settle, pierces the slice's
# shadow root, and asserts the M1 skeleton is still in the document. It is
# REQUIRED — Playwright is imported at module level, never importorskip'd —
# and it may NOT abort the chamber route (the abort-ban rule below fails any
# chamber paint test that does).
#
# Hermetic: the Ecgberht bridge is a stub .mjs under a temp ECGBERHT_ROOT
# (one JSON line on stdout, branch-switched by ANCHOR_TEST_CHAMBER_MODE);
# E1 enforcement still runs FOR REAL — it lives Anchor-side at the bridge
# boundary (chamber_e1_hook.enforce_bridge_result on the committed, signed
# F7 artifact), so a direct question genuinely blocks the turn close.
import json
import os
import sys
from pathlib import Path

import pytest

ANCHOR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ANCHOR))

# REQUIRED, never skipped: a missing Playwright fails this file loudly. The
# survival test is the real recurrence instrument for the slice-delete
# defect (frozen plan W2 notes) — a skip here would be the defect's cover.
from playwright.sync_api import sync_playwright  # noqa: E402

from tests.chamber_harness import TEST_TOKEN, boot_server  # noqa: E402

import chamber_coldopen as co  # noqa: E402
import chamber_dom_law as cdl  # noqa: E402
import chamber_e1_bound as e1b  # noqa: E402
import chamber_enforcement as ce  # noqa: E402
import chamber_mockup_diff as cmd  # noqa: E402
import chamber_open as copen  # noqa: E402
import chamber_reconcile as cr  # noqa: E402

_MODE_ENV = "ANCHOR_TEST_CHAMBER_MODE"

#: The hermetic stand-in for the Ecgberht seal-chamber bridge: one JSON line
#: on stdout, exactly like the real bridge. The bare chamber verb answers per
#: ANCHOR_TEST_CHAMBER_MODE (chamber | stand_up | error) so one server can
#: drive all three mount branches; --converse answers a deterministic
#: conversational turn (lane 'converse', no answer_references — so the
#: ANCHOR-side E1 bridge-boundary leg blocks a direct question for real).
_STUB_BRIDGE = """\
const args = process.argv.slice(2);
const val = (f) => { const i = args.indexOf(f); return i >= 0 ? args[i + 1] : null; };
let out;
if (args.includes('--converse')) {
  out = { ok: true, lane: 'converse',
          say: 'Stub steward: heard "' + (val('--converse') || '') + '".' };
} else {
  const mode = process.env.ANCHOR_TEST_CHAMBER_MODE || 'chamber';
  if (mode === 'stand_up') {
    out = { ok: true, mode: 'stand_up', stand_up: { greeting: 'stub stand-up' } };
  } else if (mode === 'error') {
    out = { ok: false, error: 'stub_chamber_error' };
  } else {
    out = { ok: true, chamber: { footer_stamp: 'stub-chamber' } };
  }
}
process.stdout.write(JSON.stringify(out) + '\\n');
"""


# ── campaign builder (the W6 suites' real-campaign shape, kept in sync) ──────

def _at(i):
    return "2026-08-13T%02d:%02d:%02dZ" % (i // 3600, (i // 60) % 60, i % 60)


def _write_roadmap(folder, steps, events, as_of):
    (Path(folder) / "roadmap.json").write_text(json.dumps(
        {"project_id": "proj-m1-w1", "as_of": as_of,
         "roadmap_projection": steps, "roadmap_events": events}),
        encoding="utf-8")


def _write_run_record(folder, sid, *, step_id, outcome, at, skill="gandalf"):
    root = Path(folder) / cr.RUN_RECORDS_REL
    root.mkdir(parents=True, exist_ok=True)
    rec = {"session_id": sid, "commission_id": "c-" + sid, "step_id": step_id,
           "skill": skill, "lane": "research", "outcome": outcome, "at": at,
           "elapsed_s": 12.5, "report": {"say": "did the thing"},
           "reflection": {"say": "did the thing", "at": at}}
    (root / (sid + ".json")).write_text(json.dumps(rec), encoding="utf-8")


def _healthy_campaign(root, name):
    """A campaign whose seal_open paints the HEALTHY face — the drawn convo
    column with the say box (the degraded rail draws no saybox)."""
    folder = root / name
    folder.mkdir()
    steps = [{"id": "s1", "name": "Draft memo", "status": "done",
              "skill": "gandalf"},
             {"id": "s2", "name": "Verify memo", "status": None,
              "skill": "researchPrime"}]
    events = [{"kind": "scaffold_proposal", "proposal_id": "prop-1",
               "goal": "A verified memo.", "at": _at(10)},
              {"kind": "step_done", "step_id": "s1", "at": _at(20)}]
    _write_roadmap(folder, steps, events, as_of=_at(20))
    _write_run_record(folder, "sess-done", step_id="s1", outcome="done",
                      at=_at(15))
    co.cold_open_rebuild(folder)
    return folder


# ── fixtures: stub-bridge server + one shared browser ────────────────────────

@pytest.fixture(scope="module")
def m1_srv(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("m1-survives")
    ecg_root = tmp / "ecgberht-stub"
    (ecg_root / "scripts").mkdir(parents=True)
    (ecg_root / "scripts" / "seal-chamber-bridge.mjs").write_text(
        _STUB_BRIDGE, encoding="utf-8")
    saved = {k: os.environ.get(k) for k in ("ECGBERHT_ROOT", _MODE_ENV)}
    os.environ["ECGBERHT_ROOT"] = str(ecg_root)
    srv = boot_server(tmp, token=TEST_TOKEN, auth_mode="enforce")
    try:
        import rnd_registry
        folder = _healthy_campaign(tmp, "camp-m1")
        pid = rnd_registry.add_project("M1 Survives (chamber-m1 W1)",
                                      str(folder), scaffold=False)["id"]
        yield {"srv": srv, "pid": pid, "folder": folder}
    finally:
        srv["stop"]()
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _open_seal(browser, h, mode):
    """Open the Seal for one branch and wait for BOTH the W6 seal_open paint
    AND the successor /api/ecgberht/chamber hydrate to settle — NEVER by
    aborting either (the abort-ban rule). Returns (context, page)."""
    os.environ[_MODE_ENV] = mode
    ctx = browser.new_context()
    ctx.add_init_script(
        "try{localStorage.setItem('anchor_token','%s')}catch(e){}"
        % TEST_TOKEN)
    pg = ctx.new_page()
    with pg.expect_response(lambda r: "/api/ecgberht/seal_open" in r.url,
                            timeout=20000):
        with pg.expect_response(lambda r: "/api/ecgberht/chamber?" in r.url,
                                timeout=20000):
            # (2026-08-15) ?classic=1 — this file is the recurrence instrument
            # for the CLASSIC chamber (the mounted #ecgSealSlice and its shadow
            # root). /project/<id> now serves the chamber PAGE, which renders
            # server-side with no slice to mount; its own real-browser gate is
            # tests/test_chamber_page_w1.py. Both surfaces stay guarded.
            pg.goto("%s/project/%s?classic=1&token=%s#seal"
                    % (h["srv"]["base"], h["pid"], TEST_TOKEN),
                    wait_until="domcontentloaded")
    # The paint-mark law says the slice mounted; the settle above says the
    # hydrate answered. The short wait lets the hydrate's then-handlers (the
    # microtasks that USED to drop the slice) run before the DOM is judged.
    pg.wait_for_function("window.ECG_SEAL_PAINT_MS != null", timeout=20000)
    pg.wait_for_timeout(400)
    return ctx, pg


#: Shadow-piercing probe: does the slice (shadow root or light-DOM fallback)
#: still carry a node matching the selector?
_IN_SLICE = ("(function(){var s=document.getElementById('ecgSealSlice');"
             "if(!s)return false;var r=s.shadowRoot||s;"
             "return !!r.querySelector(%r);})()")


def _assert_m1_still_up(pg):
    assert pg.evaluate(_IN_SLICE % ".dock"), \
        "the M1 skeleton is GONE from the slice after hydration"
    assert pg.evaluate(_IN_SLICE % ".saybox"), \
        "the drawn say box is gone from the slice"
    # And no v0 surface mounted beside/instead of it (chamber, stand-up and
    # error docks all carried id=ecgSealDock).
    assert pg.evaluate("document.getElementById('ecgSealDock') === null"), \
        "a v0 dock mounted after hydration — the replaced surface returned"


# ── the survival rows: all three hydrate branches ────────────────────────────

def test_m1_survives_the_chamber_success_branch(m1_srv, browser):
    ctx, pg = _open_seal(browser, m1_srv, "chamber")
    try:
        _assert_m1_still_up(pg)
    finally:
        ctx.close()


def test_m1_survives_the_stand_up_branch(m1_srv, browser):
    ctx, pg = _open_seal(browser, m1_srv, "stand_up")
    try:
        _assert_m1_still_up(pg)
    finally:
        ctx.close()


def test_m1_survives_the_error_branch(m1_srv, browser):
    ctx, pg = _open_seal(browser, m1_srv, "error")
    try:
        _assert_m1_still_up(pg)
    finally:
        ctx.close()


# ── the say box: send → /api/ecgberht/converse → mockup-class paint ──────────

def test_say_box_posts_to_converse_and_reply_paints_in_mockup_classes(
        m1_srv, browser):
    ctx, pg = _open_seal(browser, m1_srv, "chamber")
    try:
        box = pg.locator("#ecgSealSlice [data-say-input]")
        box.fill("hello there steward")  # a statement — no direct question
        with pg.expect_response(lambda r: "/api/ecgberht/converse" in r.url,
                                timeout=30000) as ri:
            pg.locator("#ecgSealSlice [data-say-send]").click()
        assert ri.value.status == 200
        # The reply paints into the drawn .msgs as .msg.steward — and it is
        # the SERVER's text, not a client invention.
        pg.wait_for_function(
            "(function(){var s=document.getElementById('ecgSealSlice');"
            "if(!s)return false;var r=s.shadowRoot||s;"
            "var ms=r.querySelectorAll('.msgs .msg.steward');"
            "if(!ms.length)return false;"
            "return (ms[ms.length-1].textContent||'')"
            ".indexOf('Stub steward: heard')>=0;})()", timeout=15000)
        assert pg.evaluate(_IN_SLICE % ".msgs .msg.john"), \
            "John's turn did not paint as the drawn .msg.john"
        # Never v0's painter classes: page CSS does not cross the shadow
        # boundary, so .ecg-msg inside the slice would be invisible chrome.
        assert not pg.evaluate(_IN_SLICE % ".ecg-msg")
    finally:
        ctx.close()


# ── E1: engine-enforced AND visible — the refusal is pixels, not a field ─────

def test_e1_refusal_paints_visible_as_the_drawn_blocked_state(
        m1_srv, browser):
    ctx, pg = _open_seal(browser, m1_srv, "chamber")
    try:
        box = pg.locator("#ecgSealSlice [data-say-input]")
        # The ratified in-bound imperative (V1's form of record, no '?').
        box.fill(e1b.T15_TRIGGER_TEXT)
        with pg.expect_response(lambda r: "/api/ecgberht/converse" in r.url,
                                timeout=30000) as ri:
            box.press("Enter")  # the Enter leg of the delegation
        body = ri.value.json()
        assert body.get("turn_blocked") is True, \
            "E1 did not block the turn engine-side (the enforcement seam moved?)"
        # ENGINE-GREEN ALONE DOES NOT SATISFY THIS ROW: the refusal must be
        # visible in the slice, in the signed AG-BLOCKED-TURN shape.
        pg.wait_for_function(
            _IN_SLICE % ".msgs .msg.steward.blocked", timeout=15000)
        info = pg.evaluate(
            "(function(){var s=document.getElementById('ecgSealSlice');"
            "if(!s)return null;var r=s.shadowRoot||s;"
            "var el=r.querySelector('.msgs .msg.steward.blocked');"
            "if(!el)return null;var b=el.getBoundingClientRect();"
            "var w=el.querySelector('.who');var f=el.querySelector('.bfind');"
            "var q=el.querySelector('.bqid');"
            "return {w:b.width,h:b.height,"
            "who:w?w.textContent:'',bfind:f?f.textContent:'',"
            "qid:q?q.textContent:''};})()")
        assert info, "the blocked state vanished between wait and probe"
        assert info["w"] > 0 and info["h"] > 0, \
            "the E1 refusal is in the DOM but renders ZERO pixels"
        assert "turn blocked" in info["who"]
        assert "E1-TURN-CLOSE-BLOCKED" in info["bfind"]
        assert info["qid"].strip(), "the unanswered question id is not shown"
    finally:
        ctx.close()


# ── the C9 pin: data-* hooks ride the served render; the hash pin holds ──────

def test_say_hooks_ride_the_served_render_and_the_c9_pin_holds(tmp_path):
    folder = _healthy_campaign(tmp_path, "camp-c9")
    view = copen.seal_open_view(folder)
    assert view["degraded"] is None
    html = copen.render_seal_slice_html(view)
    assert "data-say-input" in html and "data-say-send" in html
    # ATTRIBUTES ONLY: the C9 signature is (tag, sorted-classes), so the
    # signed-mockup diff still pins green — no amendment was needed.
    spec = cmd.slice_spec()
    assert cmd.verify_slice_render(html, spec, mode="healthy") == []


# ── the mount: no drop, no v0 mount — and v0 itself is DELETED (W2) ──────────

def test_mount_never_drops_the_slice_and_v0_is_deleted():
    js = (ANCHOR / "static" / "project-window.js").read_text(
        encoding="utf-8", errors="replace")
    mount = js[js.index("function ecgSealMountInline()"):]
    mount = mount[:mount.index("F5-CHAMBER-DOM-END")]
    assert "_ecgSealDropSlice(" not in mount
    assert "_ecgRenderChamber(" not in mount
    assert "_ecgRenderStandUp(" not in mount
    assert "ecg-dock" not in mount, "the error-path dock is minted again"
    assert "_ecgSealPaintSlice(host)" in mount
    # The hydrate still settles (the route is KEPT as a data API — W2).
    assert "/api/ecgberht/chamber?project_id=" in mount
    # (chamber-m1 W2) v0 is DELETED from the tree — no definition and no
    # call site anywhere in the file, the W1 "functions remain" state
    # inverted exactly as the frozen plan scheduled. The by-name/by-tree
    # recurrence grep lives in tests/test_chamber_v0_is_gone_w2.py; THIS
    # file's Playwright survival test above stays the real recurrence
    # instrument (a name grep cannot see a future slice.remove() — only
    # the surviving pixels can).
    assert "_ecgSealDropSlice" not in js
    assert "_ecgRenderChamber" not in js
    assert "_ecgRenderStandUp" not in js
    assert "_ecgHydrateDispatchV0" not in js
    # The say wiring is delegation on the slice, textContent-only (F5): the
    # sentinel-bounded sink scan must still be green after this wave's code.
    assert "_ecgSliceSay(root)" in js
    assert cdl.js_sink_problems() == []


# ── the abort-ban CI rule: active, green, and it BITES by name ───────────────

def test_abort_ban_rule_is_active_and_green():
    """No chamber paint test aborts a successor-hydrate route — including
    tests/test_chamber_first_paint_w6.py, whose abort of the chamber route
    is how the slice-delete defect stayed green for twelve waves."""
    assert ce.scan_chamber_paint_aborts() == []


def test_abort_ban_rule_bites_by_name(tmp_path):
    """Negative proof: the rule catches a hydrate abort and names the file,
    while fulfil-style mocks and aborts of unrelated routes pass."""
    d = tmp_path / "tests"
    d.mkdir()
    # Needles assembled by concatenation so THIS file never carries a live
    # interception literal (the real scanner scans this very file too).
    reg = ".rou" + "te("
    hydrate = "/api/ecgberht/" + "chamber"
    kill = "abo" + "rt"
    (d / "test_chamber_aborts_hydrate.py").write_text(
        'def test_paint(pg):\n'
        '    pg' + reg + '"**' + hydrate + '?*",\n'
        '             lambda r: r.' + kill + '())\n',
        encoding="utf-8")
    (d / "test_chamber_mocks_other.py").write_text(
        'def test_paint(pg):\n'
        '    pg' + reg + '"**' + hydrate + '?*",\n'
        '             lambda r: r.fulfill(json={"ok": True}))\n',
        encoding="utf-8")
    (d / "test_chamber_aborts_unrelated.py").write_text(
        'def test_paint(pg):\n'
        '    pg' + reg + '"**/api/rnd/tail?*",\n'
        '             lambda r: r.' + kill + '())\n',
        encoding="utf-8")
    hits = ce.scan_chamber_paint_aborts(tests_dir=d)
    assert [h["file"] for h in hits] == ["test_chamber_aborts_hydrate.py"]
    assert "successor-hydrate" in hits[0]["problem"]
