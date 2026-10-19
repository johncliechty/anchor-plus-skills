"""W2c of the active set (2026-09-30, PLAN v1.3.1 fit 3, 4, 6, 10; his lock of MOCKUPS-three-levels.html): the High Seat
opens with the brief; then the goals as ONE thin line (Tier 1 named, Tier 2 and the seed goals counted, how many
initiatives are out) that expands to the goals and their components; then ACTIVE and ON DECK as two shelves of
initiative cards - the project card as today, a cockpit within a project on its own effort, a desk item's card that
talks to the desk - each naming its goal, each with a x that sends it home; a drag out of a goal, between the
shelves, up and down inside one, or back onto the goals tile is ONE act with one line and undo; a registry project in
no goal is in the Projects tile and, dragged onto a goal, becomes its component. The old shelves are gone."""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import high_seat_page as hsp  # noqa: E402
import test_high_seat_page_2026_09_26 as base  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MBA = "6765ece4b3bc43b0b0b0907b92b17280"


def _steps():
    steps = json.loads(json.dumps(base._steps()))
    for s in steps:
        if s["id"] == "mba-project":
            s["seat"], s["seat_order"] = "active", 0
        if s["id"] == "hw":
            s["seat"], s["seat_order"] = "deck", 0
    steps.append({"id": "mba-lectures", "name": "The lectures cockpit", "status": "proposed", "ref": "effort:%s/lectures" % MBA, "seat": "active", "seat_order": 1, "navigation": {"path": ["mba-teaching"]}})
    steps.append({"id": "trusts-pkg", "name": "Send the Stanford package", "status": "waiting", "waiting_on": "John", "navigation": {"path": ["trusts"]}})
    return steps


def _resolved():
    r = base._resolved()
    r["mba-lectures"] = {"kind": "effort", "pid": MBA, "name": "MBA Teaching AI · The lectures", "what": "The lectures", "state": "working: lecture 4", "date": "", "href": "/project/%s?dir=lectures" % MBA, "dir": "lectures", "broken": False, "gap": ""}
    return r


def _ctx():
    ctx = base._ctx(campaign=True)
    ctx.setdefault("lights", {})[MBA + "|lectures"] = {"light": "green", "word": "working", "why": "lecture 4"}      # W2e-7: an effort card's light is its own cockpit's, keyed by its directory
    ctx["initiatives"] = hsp.campaign_initiatives(_steps(), _resolved())
    ctx["seeds"] = 2
    return ctx


def test_the_goals_are_one_thin_line_that_expands_to_the_goals_and_their_components():
    html = hsp.render_high_seat_html(_ctx())
    camp = html[html.index('<section class="camp"'):html.index('id="shActive"')]
    assert 'id="camp" data-drop="home"' in camp and '<span class="k">Goals</span>' in camp and ">Expand<" in camp, "a thin tile, closed by default, the drop that sends a seated initiative home"
    assert "<b>Tier 1:</b> MBA Teaching, Fall 2026 &middot; <b>Tier 2:</b> 1 &middot; <b>seed goals:</b> 2 &middot; <b>out:</b> 2 active, 1 on deck" in camp
    mba = camp[camp.index('data-g="mba-teaching"'):camp.index('data-g="trusts"')]
    assert '<b class="gn">MBA Teaching, Fall 2026</b><span class="t">tier 1</span>' in mba and "2 in the goal &middot; out: 2 active, 1 on deck" in mba
    assert 'href="/project/df56?open=mba-teaching"' in mba, "the goal's place on the Campaign page"
    assert '<div class="irow seated" data-step="mba-project"><span class="kind">cockpit</span>' in mba and 'data-home="mba-project"' in mba and '<span class="seat active">active</span>' in mba
    assert '<span class="kind">a step of a project</span><span class="nm">Lectures 3 + 4 revised, with AI supplements <span class="dim">&middot; MBA Teaching AI</span></span><span class="el">rides inside' in mba, "an element rides inside its goal"
    assert 'class="irow broken"' in mba and "broken reference: no step" in mba
    assert '<span class="kind">desk item</span><span class="nm">retool homework 2</span><span class="seat deck">on deck</span>' in mba
    trusts = camp[camp.index('class="grow needs" data-g="trusts"'):]
    assert '<div class="irow" draggable="true" data-step="trusts-pkg" data-name="Send the Stanford package"><span class="kind">desk item</span><span class="nm">Send the Stanford package <span class="need">&#9873; needs you</span></span>' in trusts
    assert 'data-seat="deck" data-step="trusts-pkg"' in trusts and 'data-seat="active" data-step="trusts-pkg"' in trusts, "an initiative in its goal drags out or takes a button"
    assert "1 in the goal" in trusts and 'class="grow needs"' in trusts
    assert "ini-tile" not in html and "Show Tier 1" not in html and "t1grid" not in html


def test_the_shelves_hold_the_seated_initiatives_as_cards_with_their_goal_and_the_x():
    html = hsp.render_high_seat_html(_ctx())
    assert html.index('id="camp"') < html.index('id="shActive" data-seat="active"') < html.index('id="shDeck" data-seat="deck"') < html.index('id="ptile"') < html.index('id="deskline"')
    assert "shNeeds" not in html and "shCont" not in html and "shPark" not in html, "the old shelves are gone: a card is on a shelf because he seated it"
    active = html[html.index('id="shActive"'):html.index('id="shDeck"')]
    assert '<h3>Active</h3><span class="c">2</span>' in active
    card = active[active.index('id="card-%s"' % MBA):active.index("</article>")]
    assert 'data-step="mba-project" data-name="MBA Teaching AI" draggable="true"' in card and 'data-home="mba-project"' in card and '<div class="t-goal">in <b>MBA Teaching, Fall 2026</b> &middot; the project&rsquo;s cockpit</div>' in card
    assert "&#9873; Needs you:" in card and 'data-part="status"' in card and 'href="/project/%s"' % MBA in card, "the project card as today, with its acts"
    eff = active[active.index('id="card-%s-mba-lectures"' % MBA):]
    assert 'data-dir="lectures"' in eff and 'data-step="mba-lectures"' in eff and "a cockpit within the project" in eff and '<span class="t-eff">&middot; lectures</span>' in eff, "a cockpit within a project is its own card on its own effort"
    assert 'href="/project/%s?dir=lectures"' % MBA in eff and "Needs you:" not in eff and 'class="tlight green" title="working: lecture 4"' in eff and "<span class=\"k\">Next</span>The lectures" in eff, "the effort card opens THAT effort and reads its own state (its light, W2e) — not the project's wait (Grok W2c)"
    assert "camp-note" not in html[html.index('id="camp"'):html.index('id="shActive"')] and "def _shelf" not in open(os.path.join(HERE, "high_seat_page.py"), encoding="utf-8").read()
    assert active.index('id="card-%s"' % MBA) < active.index('id="card-%s-mba-lectures"' % MBA), "his order"
    deck = html[html.index('id="shDeck"'):html.index('id="ptile"')]
    assert '<h3>On deck</h3><span class="c">1</span>' in deck
    assert '<article class="tile desk" id="card-hw" data-step="hw" data-name="retool homework 2" draggable="true">' in deck and 'data-home="hw"' in deck
    assert '<div class="t-goal">in <b>MBA Teaching, Fall 2026</b></div>' in deck and 'href="/project/df56?view=desk"' in deck and "talk to the desk" in deck and "due Oct 27" in deck, "a desk item is talked through at the Desk cockpit (Grok W2c)"
    # the Projects tile: the registry's projects in no goal, draggable onto a goal
    tile = html[html.index('id="ptile"'):html.index('id="deskline"')]
    assert '<span class="ok">In no goal &middot; 2</span>' in tile and 'class="orphan" draggable="true" data-proj="9405abe0" data-name="Family &lt;Trusts&gt;"' in tile and 'data-proj="quiet"' in tile
    assert 'data-proj="%s"' % MBA not in tile, "a project in a goal is not an orphan"
    # the rail and the ruler follow the seats
    assert '<button data-rail="active"><span class="n">Active</span><span class="c">2</span>' in html and '<button data-rail="deck"><span class="n">On deck</span><span class="c">1</span>' in html
    assert "seated on Active" in html and "its card is on" not in html
    # the empty shelves say what to do
    ctx = _ctx(); ctx["initiatives"] = hsp.campaign_initiatives(base._steps(), base._resolved())
    html = hsp.render_high_seat_html(ctx)
    assert "nothing active &mdash; pull an initiative out of a goal above" in html and "nothing on deck" in html and "<b>out:</b> 0 active, 0 on deck" in html


def test_the_page_script_moves_by_one_act_with_undo_and_drops_where_the_mock_up_said():
    js = open(os.path.join(HERE, "static", "high-seat-page.js"), encoding="utf-8").read()
    block = js[js.index("// W2c"):js.index("// the Projects tile and its folders")]
    assert "act({ act: 'seat', step: s.getAttribute('data-step'), seat: s.getAttribute('data-seat') })" in block, "the buttons"
    assert "act({ act: 'home', step: h.getAttribute('data-home') })" in block, "the x and back"
    assert "act({ act: 'seat', step: drag.step, seat: z.getAttribute('data-seat'), position: k })" in block, "a drop on a shelf at its place among the cards"
    assert "act({ act: 'add', initiative: g.getAttribute('data-g'), kind: 'project', text: drag.name, project_id: drag.proj })" in block, "a registry project onto a goal"
    assert "if (seatedSource()) act({ act: 'home', step: drag.step });" in block, "a seated initiative dropped on the goals tile goes home"
    assert "else receipt('Open the goals (Expand), then drop it on one goal.', true)" in block, "an orphan dropped on the closed head gets one line (Grok W2c)"
    assert "'/api/high-seat/campaign'" in block and "if (acting || !CAMPAIGN) return; acting = true;" in block and "renewInPlace(j.receipt, j.undo || null);" in block and "location.reload()" not in block   # W4: placed, never reloaded
    assert "e.dataTransfer.setData('text/plain'" in block and "'Collapse' : 'Expand'" in block
    assert "ini-tile" not in js and "active: '#shActive'" in js and "deck: '#shDeck'" in js and "#shNeeds" not in js
    r = subprocess.run(["node", "--check", os.path.join(HERE, "static", "high-seat-page.js")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    css = open(os.path.join(HERE, "static", "high-seat-page.css"), encoding="utf-8").read()
    assert ".ini-tile" not in css and ".t1grid" not in css and ".zone.over{" in css and ".t-x{" in css and ".orphan{" in css and ".grow.open .inits{display:block}" in css


def test_the_effort_part_names_its_directory(tmp_path):
    from steward_cockpit import campaign_parts as parts
    proj = tmp_path / "Magi"; eff = proj / "book-one"; (eff / ".ecgberht").mkdir(parents=True)
    (proj / "roadmap.json").write_text(json.dumps({"roadmap_projection": []}), encoding="utf-8")
    (eff / "ECGBERHT.md").write_text("# Book one\n", encoding="utf-8")
    (eff / "roadmap.json").write_text(json.dumps({"roadmap_projection": []}), encoding="utf-8")
    lookup = lambda pid: {"id": "p-magi", "name": "Artificial Magi", "folder_path": str(proj)} if pid == "p-magi" else None
    r = parts.resolve_ref("effort:p-magi/book-one", lookup=lookup)
    assert r["dir"] == "book-one"
    inits = hsp.campaign_initiatives([{"id": "g", "name": "G", "status": "proposed", "tier": 1, "navigation": {"path": ["g"], "groups": [{"id": "g", "label": "G", "order": 0, "parent_id": None}]}},
                                      {"id": "e", "name": "E", "status": "proposed", "ref": "effort:p-magi/book-one", "navigation": {"path": ["g"]}}], {"e": r})
    assert inits[0]["parts"][0]["dir"] == "book-one"
