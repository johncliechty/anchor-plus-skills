# W9 gate — the F5 DOM injection law: the REGISTERED slot inventory, its
# growth rule (both directions, both layers), and the hostile-string fixture
# suite driven through EVERY registered agent-influenced DOM slot.
#
# AUTH-ON: not-a-surface
#
# What is proven here, per the wave contract:
#   * the slot inventory (chamber/dom-slot-inventory.json) is versioned,
#     owned, structurally valid, and records the href law verbatim;
#   * the GROWTH RULE is green on the committed code AND bites in every
#     direction it exists for: a new render function without a row, a moved
#     placeholder count inside an existing render, a stale row, an
#     unregistered innerHTML-class sink inside the JS sentinel region, and a
#     stale registered sink marker — each a NAMED failure;
#   * hostile-string fixtures (markup / script / event-handler / scheme
#     payloads) drive EVERY registered slot and ZERO markup executes — the
#     structural injection detector finds no forbidden element, no on*
#     handler attribute, and no link target outside the fixed internal
#     prefixes; the fixture map itself is COMPLETE against the inventory
#     (a registered slot without a hostile-fixture row fails here);
#   * the F5 link-scheme law holds at the render layer: a yield's report
#     link renders as an anchor ONLY for the fixed internal prefixes
#     (chamber_open._REPORT_LINK_PREFIXES, pinned in sync with
#     chamber_dom_law.INTERNAL_HREF_PREFIXES), and the browser-side
#     validator (_ecgSealHrefAllowed) names the same prefixes.
#
# Pure module/artifact tests — no server, no network, no spawn.
import copy
import json
import sys
from pathlib import Path

import pytest

ANCHOR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ANCHOR))

import chamber_deliverable as cdeliv  # noqa: E402
import chamber_dom_law as cdl  # noqa: E402
import chamber_e1_hook as ce1h  # noqa: E402  (steward-e1 W2: blocked turn)
import chamber_gates as cgates  # noqa: E402  (W10 row: gate-queue render)
import chamber_open as copen  # noqa: E402
import chamber_rail as crail  # noqa: E402
import chamber_refine as crefine  # noqa: E402  (W11 rows: REFINE overlay)
import chamber_status_overlay as cso  # noqa: E402


# ── the artifact: versioned, owned, valid, law recorded ─────────────────────

def test_slot_inventory_is_versioned_owned_and_valid():
    inv = cdl.load_slot_inventory()
    problems = cdl.validate_slot_inventory(inv)
    assert not problems, "dom-slot-inventory.json invalid:\n" + \
        "\n".join(problems)
    assert inv["schema_version"] == cdl.SCHEMA_VERSION
    assert inv["owner_file"] == "chamber_dom_law.py"
    assert (ANCHOR / inv["owner_file"]).is_file(), \
        "the named owner file must exist (living-registry law)"
    assert tuple(inv["href_law"]["internal_prefixes"]) == \
        cdl.INTERNAL_HREF_PREFIXES


# ── the growth rule: green on the committed code ────────────────────────────

def test_growth_rule_green_on_committed_renders_and_sinks():
    assert cdl.python_render_problems() == []
    assert cdl.js_sink_problems() == []


# ── the growth rule BITES: every direction, named ───────────────────────────

def _tmp_registered_module(tmp_path, source):
    (tmp_path / "reg_mod.py").write_text(source, encoding="utf-8")
    return {
        "schema_version": cdl.SCHEMA_VERSION,
        "owner_file": "chamber_dom_law.py",
        "href_law": {"internal_prefixes": list(cdl.INTERNAL_HREF_PREFIXES)},
        "python_renders": [
            {"module": "reg_mod",
             "functions": [{"name": "render_known_html", "placeholders": 2}]}],
        "js_sinks": {"file": "static/pw.js", "registered": []},
    }


def test_growth_rule_names_a_new_render_added_without_a_row(tmp_path):
    inv = _tmp_registered_module(
        tmp_path,
        "def render_known_html(v):\n"
        "    return '<div>%s%s</div>' % (v, v)\n"
        "def render_added_html(v):\n"
        "    return '<b>%s</b>' % v\n")
    problems = cdl.python_render_problems(inv, root=tmp_path)
    assert any("reg_mod.render_added_html" in p and "without an inventory row"
               in p for p in problems), problems


def test_growth_rule_names_a_moved_placeholder_count(tmp_path):
    # The registered function grew a THIRD interpolation slot — a new
    # agent-influenced DOM slot inside an existing render.
    inv = _tmp_registered_module(
        tmp_path,
        "def render_known_html(v):\n"
        "    return '<div>%s%s · %s</div>' % (v, v, v)\n")
    problems = cdl.python_render_problems(inv, root=tmp_path)
    assert any("reg_mod.render_known_html" in p and "slot count moved" in p
               for p in problems), problems


def test_growth_rule_names_a_stale_render_row(tmp_path):
    inv = _tmp_registered_module(
        tmp_path, "def render_other_thing_html(v):\n    return ''\n")
    inv["python_renders"][0]["functions"].append(
        {"name": "render_other_thing_html", "placeholders": 0})
    problems = cdl.python_render_problems(inv, root=tmp_path)
    assert any("stale inventory row: reg_mod.render_known_html" in p
               for p in problems), problems


def _tmp_js(tmp_path, body):
    d = tmp_path / "static"
    d.mkdir(exist_ok=True)
    (d / "pw.js").write_text(
        "// %s\n%s\n// %s\n" % (cdl.JS_REGION_BEGIN, body, cdl.JS_REGION_END),
        encoding="utf-8")


def test_growth_rule_names_an_unregistered_js_sink(tmp_path):
    inv = _tmp_registered_module(
        tmp_path, "def render_known_html(v):\n"
                  "    return '<div>%s%s</div>' % (v, v)\n")
    _tmp_js(tmp_path, "el.innerHTML = evil;")
    problems = cdl.js_sink_problems(inv, root=tmp_path)
    assert any("unregistered DOM sink" in p for p in problems), problems


def test_growth_rule_names_a_stale_js_marker_and_missing_sentinels(tmp_path):
    inv = _tmp_registered_module(
        tmp_path, "def render_known_html(v):\n"
                  "    return '<div>%s%s</div>' % (v, v)\n")
    inv["js_sinks"]["registered"] = [{"marker": "gone.innerHTML = j.html"}]
    _tmp_js(tmp_path, "el.textContent = fine;")
    problems = cdl.js_sink_problems(inv, root=tmp_path)
    assert any("stale registered JS sink marker" in p for p in problems), \
        problems
    # A JS file with no sentinel region is a hard structural failure — the
    # sink scan must never silently scan nothing.
    (tmp_path / "static" / "pw.js").write_text("var x = 1;\n",
                                               encoding="utf-8")
    with pytest.raises(AssertionError):
        cdl.js_sink_problems(inv, root=tmp_path)


# ── the injection detector itself BITES (named findings) ────────────────────

def test_injection_detector_names_each_violation_class():
    assert any("forbidden element" in p for p in
               cdl.dom_injection_problems("<script>window.x=1</script>"))
    assert any("event-handler attribute" in p for p in
               cdl.dom_injection_problems('<img src=x onerror=alert(1)>'))
    assert any("link target outside" in p for p in
               cdl.dom_injection_problems('<a href="javascript:alert(1)">x</a>'))
    assert any("forbidden element" in p for p in
               cdl.dom_injection_problems('<iframe src="//evil.invalid">'))
    # Clean chamber markup passes.
    assert cdl.dom_injection_problems(
        '<div class="dock"><a href="/report/p/l/j">report ▸</a></div>') == []


def test_href_law_prefixes():
    for good in ("/artifact/p?path=x", "/report/p/l/j", "/summary/p/l/s",
                 "#anchor"):
        assert cdl.href_allowed(good), good
    for bad in ("javascript:alert(1)", "data:text/html,x", "//evil.invalid",
                "https://evil.invalid/x", "/evil/route", "", None):
        assert not cdl.href_allowed(bad), bad


# ── the F5 link-scheme law at the render layer + the JS validator, in sync ──

def test_report_link_prefixes_pinned_to_the_code_owned_law():
    assert copen._REPORT_LINK_PREFIXES == tuple(
        p for p in cdl.INTERNAL_HREF_PREFIXES if p != "#")
    js = (ANCHOR / "static" / "project-window.js").read_text(
        encoding="utf-8", errors="replace")
    fn = js[js.index("function _ecgSealHrefAllowed"):]
    fn = fn[:fn.index("}")]
    for prefix in copen._REPORT_LINK_PREFIXES:
        assert "'%s'" % prefix in fn, (
            "the browser-side validator lost the %r prefix" % prefix)


def _done_step(link):
    return {"id": "s1", "name": "Draft", "status": "done", "skill": "gandalf",
            "yield": {"text": "did it", "report_link": link}}


@pytest.mark.parametrize("render", [
    copen._render_fstep,
    lambda s: crail._fstep_html({"eta": {"per_step": {}}}, dict(s, state_class="done")),
])
def test_hostile_report_link_renders_as_text_never_an_anchor(render):
    for hostile in ("javascript:alert(1)", "/evil/route", "//evil.invalid",
                    "https://evil.invalid/x"):
        html_out = render(_done_step(hostile))
        assert "<a " not in html_out, (hostile, html_out)
        assert cdl.dom_injection_problems(html_out) == []
    good = render(_done_step("/report/p1/research/j1"))
    assert '<a href="/report/p1/research/j1">' in good
    assert cdl.dom_injection_problems(good) == []


# ── the hostile-string fixture suite over EVERY registered slot ─────────────
#
# Fixture completeness IS the other half of the growth rule: every inventory
# row maps to a hostile drive below, and every drive maps to a row — a slot
# registered without a fixture (or a fixture for a vanished slot) fails HERE
# by name.

def _hostile_open_view(p):
    return {
        "degraded": None,
        "progress": {"done": 1, "total": 3},
        "goal": {"text": p},
        "brief": {"stand": {"text": p}, "running": {"text": p},
                  "next_move": {"text": p}},
        "live_run": {"skill": p, "step_id": p, "at": p},
        "steps": [
            {"id": "s1", "name": p, "status": "done", "skill": p,
             "yield": {"text": p, "report_link": p}},
            {"id": "s2", "name": p, "status": None, "skill": p,
             "running": {"at": p}},
            {"id": "s3", "name": p, "status": None, "skill": None},
        ],
        "deliverable": {"description": p},
    }


def _hostile_degraded_view(p):
    return {
        "degraded": {"reasons": [p],
                     "rebuild": {"command": p, "label": p}},
        "steps": [{"id": "s1", "name": p, "skill": p}],
    }


def _hostile_rail_view(p):
    return {
        "degraded": None,
        "progress": {"done": 1, "total": 4},
        "goal": {"text": p},
        "brief": {"stand": {"text": p}},
        "live_run": {"skill": p, "step_id": "s2", "at": p, "session_id": p},
        "pulse_slot": {"status_block": p, "session_id": p},
        # steward-e1 W2: a hostile project id must paint inert through the
        # runcard's transcript ▸ link slots too.
        "project_id": p,
        "eta": {
            "campaign": {"state": "no-history", "label": p},
            "per_step": {
                "s2": {"state": "ok", "eta_s": 300.0, "basis": p,
                       "label": p},
                "s3": {"state": "no-history", "label": p},
            },
        },
        "steps": [
            {"id": "s1", "name": p, "status": "done", "skill": p,
             "state_class": "done", "yield": {"text": p, "report_link": p},
             "rides_in": [p]},
            {"id": "s2", "name": p, "status": None, "skill": p,
             "state_class": "run", "running": {"at": p, "session_id": p}},
            {"id": "s3", "name": p, "status": None, "skill": p,
             "rides_in": [p]},
        ],
        "deliverable": {
            "description": p,
            "action": {"state": "inert", "reason": p, "label": p,
                       "output_rel": p},
        },
    }


def _hostile_overlay_view(p):
    return {
        "degraded": False,
        "live_run": {"skill": p, "step_id": "s2", "at": p},
        "pulse_slot": {"status_block": p},
        "eta": {
            "campaign": {"state": "no-history", "label": p},
            "per_step": {"s3": {"state": "no-history", "label": p}},
        },
        "steps": [
            {"id": "s2", "name": p, "skill": p, "running": True,
             "status": None},
            {"id": "s3", "name": p, "skill": None, "status": None},
        ],
        "deliverable": {"description": p, "landed": False, "action": {}},
    }


def _hostile_deliv_views(p):
    return [
        {"deliverable": {"description": p,
                         "action": {"state": "armed", "kind": "href",
                                    "href": p, "output_rel": p, "label": p,
                                    "landed": True}}},
        {"deliverable": {"description": p,
                         "action": {"state": "armed", "kind": "spawn",
                                    "output_rel": p, "label": p,
                                    "landed": True}}},
        {"deliverable": {"description": p,
                         "action": {"state": "inert",
                                    "reason": cdeliv.INERT_NOT_LANDED,
                                    "label": p, "output_rel": p}}},
        {"deliverable": {"description": p,
                         "action": {"state": "inert", "reason": p,
                                    "label": p}}},
    ]


_STEWARD = {"label": None, "glyph": None, "seat": None}


def _drive_open(p):
    stw = {"label": p, "glyph": p, "seat": p}
    return [copen.render_seal_slice_html(_hostile_open_view(p), stw),
            copen.render_seal_slice_html(_hostile_degraded_view(p), stw)]


def _drive_rail(p):
    stw = {"label": p, "glyph": p, "seat": p}
    return [crail.render_seal_rail_html(_hostile_rail_view(p), stw)]


def _drive_overlay(p):
    return [cso.render_status_overlay_html(_hostile_overlay_view(p))]


def _drive_deliv_box(p):
    return [cdeliv.render_deliv_box(v) for v in _hostile_deliv_views(p)]


def _drive_gate_queue(p):
    # (steward-chamber W10) The gate-queue render's agent-influenced slots:
    # card prose (incl. swept paths from git status), kind, gate id, and the
    # unreadable-store error string.
    return [
        cgates.render_gate_queue_html({
            "ok": True, "queued_count": 3,
            "head": {"gate_id": p, "kind": p,
                     "text": "line one %s\nline two" % p,
                     "card": {"text": p}}}),
        cgates.render_gate_queue_html(
            {"ok": True, "queued_count": 0, "head": None}),
        cgates.render_gate_queue_html({"ok": False, "error": p}),
    ]


def _drive_blocked_turn(p):
    # (steward-e1 W2) The V5 blocked-turn refusal's agent-influenced slots:
    # the steward label, the named finding, and each unanswered question's
    # text + deterministic id — every one must paint inert.
    return [ce1h.render_blocked_turn(
        {"finding": p, "unanswered": [{"question_id": p, "text": p}]},
        steward_name=p)]


def _drive_refine(p):
    # (steward-chamber W11) The REFINE overlay's agent-influenced slots:
    # message who/text, steward label, draft summary, and the 'plan moved'
    # card's finding/title/prose/diff rows (diff rows are TEXT, never
    # markup — a hostile diff line must paint inert).
    return [
        crefine.render_refine_overlay_html({
            "steward_label": p,
            "summary": p,
            "messages": [{"who": "john", "text": p},
                         {"who": p, "text": p}],
            "plan_moved": {"finding": p, "title": p, "section_id": p,
                           "prose": p,
                           "diff": ["-" + p, "+" + p, " " + p]},
        }),
        crefine.render_plan_moved_card_html(
            {"finding": p, "title": p, "prose": p,
             "diff": ["-" + p, "+" + p]}),
        crefine.render_refine_overlay_html({}),
    ]


#: module.function -> the composed hostile drive that exercises it. The
#: top-level renders call every registered helper, so each drive covers its
#: module's rows; the completeness assertion keeps this map equal to the
#: inventory as either side grows.
HOSTILE_FIXTURES = {
    "chamber_open._render_dbar": _drive_open,
    "chamber_open._render_progress": _drive_open,
    "chamber_open._render_goalbar": _drive_open,
    "chamber_open._render_fstep": _drive_open,
    "chamber_open._render_deliv": _drive_open,
    "chamber_open._render_flow": _drive_open,
    "chamber_open._render_convo": _drive_open,
    "chamber_open._render_degraded": _drive_open,
    # (2026-08-15) The honest empty rail. It takes NO input and carries no
    # interpolation slot, so the hostile strings cannot reach it — it is
    # driven through the same open fixture anyway, so the registry and the
    # fixture map cannot drift apart and a future slot added here is caught.
    "chamber_open._empty_rail_html": _drive_open,
    "chamber_open.render_seal_slice_html": _drive_open,
    "chamber_rail._skillch_html": _drive_rail,
    "chamber_rail._yield_html": _drive_rail,
    "chamber_rail._edge_html": _drive_rail,
    "chamber_rail._runcard_html": _drive_rail,
    "chamber_rail._fstep_html": _drive_rail,
    "chamber_rail._progress_html": _drive_rail,
    "chamber_rail._flow_html": _drive_rail,
    "chamber_rail.render_seal_rail_html": _drive_rail,
    "chamber_status_overlay.render_status_overlay_html": _drive_overlay,
    "chamber_deliverable.render_deliv_box": _drive_deliv_box,
    "chamber_gates.render_gate_queue_html": _drive_gate_queue,
    "chamber_refine.render_refine_overlay_html": _drive_refine,
    "chamber_refine.render_plan_moved_card_html": _drive_refine,
    "chamber_e1_hook.render_blocked_turn": _drive_blocked_turn,
}


def test_hostile_fixture_map_is_complete_against_the_inventory():
    inv = cdl.load_slot_inventory()
    registered = {
        "%s.%s" % (row["module"], fn["name"])
        for row in inv["python_renders"] for fn in row["functions"]}
    assert registered == set(HOSTILE_FIXTURES), (
        "the hostile-fixture map and the slot inventory moved apart — a "
        "registered slot without a hostile fixture (or a fixture for a "
        "vanished slot):\nmissing fixtures: %s\nstale fixtures: %s"
        % (sorted(registered - set(HOSTILE_FIXTURES)),
           sorted(set(HOSTILE_FIXTURES) - registered)))


_RAW_MARKUP = ("<script", "<iframe", "<svg", "<img")


@pytest.mark.parametrize("payload", cdl.HOSTILE_PAYLOADS)
def test_every_registered_slot_is_inert_under_hostile_strings(payload):
    drives = {id(fn): fn for fn in HOSTILE_FIXTURES.values()}
    for drive in drives.values():
        for html_out in drive(payload):
            problems = cdl.dom_injection_problems(html_out)
            assert problems == [], (payload, problems)
            low = html_out.lower()
            for raw in _RAW_MARKUP:
                assert raw not in low, (payload, raw)


def test_the_deliv_box_never_paints_a_hostile_href_as_a_link_target():
    # The armed href rides a data-* attribute the browser wiring re-validates
    # (_ecgSealHrefAllowed) before ANY navigation; the render itself must
    # never emit it as a real href/src the DOM would act on.
    for p in cdl.HOSTILE_PAYLOADS:
        for html_out in _drive_deliv_box(p):
            assert 'href="javascript' not in html_out.lower()
            assert cdl.dom_injection_problems(html_out) == []
