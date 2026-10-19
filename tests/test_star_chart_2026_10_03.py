"""The Star Chart (the Steward's Campaign mode, 2026-10-03; Skill Foundry planning/foundry-page-2026-10-02/campaign-skill
PLAN v0.3, mockups accepted by John): the Campaign page takes the mode's name per persona (Aladdin the Star Chart,
Jarvis the Chart Room, Ecgberht the Beacon) while the steward keeps its own name in the conversation; the brief is gone
from the Star Chart and the Cave of Wonders; the look-ahead takes its place on the Star Chart; a dated item within three
days is the Cave's interrupt lane, once, with a ready-to-resume note; a Tier-1 goal carries one if-then step in his
words; a new goal or a slipped pace asks a premortem whose answer goes into the goal's guide."""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import anchor_settings as aset  # noqa: E402
import campaign_page as cpg  # noqa: E402
import high_seat_page as hsp  # noqa: E402
from steward_cockpit import campaign_acts as acts  # noqa: E402
from steward_cockpit import campaign_say as say  # noqa: E402
from steward_cockpit import nudges as N  # noqa: E402
from steward_cockpit import steward_engine as se  # noqa: E402
import test_active_set_w2_2026_09_29 as w2  # noqa: E402
import test_active_set_w2c_2026_09_30 as w2c  # noqa: E402
from test_active_set_w3_2026_10_01 import part, goal, TODAY  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_each_persona_names_its_campaign_mode_and_its_picture_ships():
    names = {k: (v["campaign_name"], v["campaign_icon"]) for k, v in aset.STEWARDS.items()}
    assert names == {"aladdin": ("Star Chart", "campaign-aladdin-star-chart.jpg"), "jarvis": ("Chart Room", "campaign-jarvis-chart-room.jpg"),
                     "ecgberht": ("Beacon", "campaign-ecgberht-beacon.jpg")}
    for _n, icon in names.values():
        assert os.path.isfile(os.path.join(HERE, "vendor", "brand", icon)), icon
        assert "vendor/brand/" + icon in open(os.path.join(HERE, "dist_manifest.txt"), encoding="utf-8").read(), "the picture ships"
    assert hsp.mode_name({"campaign_name": "Beacon"}) == "Beacon" and hsp.mode_name({}) == "Campaign"


def _star(ctx):
    ctx["steward"] = dict(ctx["steward"], label="Aladdin", high_seat_name="Cave of Wonders", campaign_name="Star Chart", campaign_icon="campaign-aladdin-star-chart.jpg")
    return ctx


def test_the_campaign_page_is_the_star_chart_and_aladdin_keeps_his_name():
    html = cpg.render_campaign_html(_star(w2._ctx()))
    assert "<title>Star Chart</title>" in html and 'aria-label="The Star Chart"' in html      # the tile reads "Star Chart" (2026-10-03)
    assert '<h2 class="modeh">Star Chart</h2>' in html and 'class="back"' not in html, "no back link to the Cave (his word)"
    mh = html[html.index('class="mh-stew"'):]
    assert 'src="/vendor/brand/campaign-aladdin-star-chart.jpg' in mh[:400] and "<b>Star Chart</b><span>Aladdin &middot; goals and foresight</span>" in mh, "the masthead wears the mode (his accepted mockup)"
    assert 'placeholder="Ask Aladdin, discuss, or tell it what to do &mdash; it runs the Star Chart:' in html, "the steward keeps his name; the page is the Star Chart"
    assert 'id="brief"' not in html and "The brief" not in html, "his word: the brief is gone"
    assert html.index('id="lookAhead"') < html.index('id="dialogue"'), "the look-ahead takes its place at the top of the panel"


def test_the_look_ahead_reads_the_record():
    ctx = w2._ctx()
    ctx["today"] = date(2026, 10, 5)
    ctx["initiatives"] = [
        goal("trusts", "Family finances", 1, [part("pkg", "Stanford's next drafts", date="2026-10-07")], area="family", done_when="x", pace="", part_count=1, done_count=0, needs=[], next_deadline="2026-10-07"),
        goal("mkt", "Marketing papers", 1, [part("d", "draft", date="2026-12-01")], area="academic", done_when="x", pace="", part_count=1, done_count=0, needs=[], next_deadline=""),
        goal("mba", "MBA Teaching", 1, [part("a", "a", done=True, status="done"), part("b", "b"), part("c", "c")], area="academic", done_when="x", pace="2026-10-10", part_count=3, done_count=0, needs=[], next_deadline="")]
    ctx["nudges"] = {"tech": {"kind": "starving", "key": "starving:tech:1", "fact": "2", "text": "Technical papers is a Tier-2 goal untouched for 16 days", "acts": []}}
    la = cpg.look_ahead(ctx)
    assert "the next seven days, from Monday 5 October" in la
    assert "<b>Coming up:</b> Oct 7 Stanford&#x27;s next drafts (Family finances) <span class=\"dim\">its alert is on the" in la or "Stanford" in la and "its alert is on the" in la
    assert "Marketing papers has no pace set" in la and "MBA Teaching paces to Oct 10 with 0 of 3 parts done" in la
    assert "<b>Starving:</b> Technical papers is a Tier-2 goal untouched for 16 days" in la and 'data-look-park="tech"' in la and 'data-nudge-act="not_now" data-key="starving:tech:1"' in la
    assert "<b>One preparation:</b> the nearest date is Stanford" in la


def test_a_tier_one_goal_carries_its_if_then_and_a_premortem_ask():
    ctx = w2._ctx()
    g = ctx["initiatives"][0]
    assert g["tier"] == 1
    g["if_then"] = "If it is Monday 9:00, then I send the trust questions"
    ctx["premortems"] = {g["id"]: {"at": "2026-10-03 10:00", "reason": "its pace moved from 2026-10-10 to 2026-10-24"}}
    html = cpg.render_campaign_html(ctx)
    tile = html[html.index('data-lane="%s"' % g["id"]):]
    tile = tile[:tile.index("</article>")]
    assert 'class="gift" data-ifthen="%s"' % g["id"] in tile and "&#8627; If it is Monday 9:00, then I send the trust questions" in tile
    assert 'class="gpm" data-pm="%s"' % g["id"] in tile and "its pace moved from 2026-10-10 to 2026-10-24" in tile and 'data-pm-answer="%s"' % g["id"] in tile
    opened = cpg.render_campaign_html(ctx, open_id=g["id"])
    place = opened[opened.index('id="place-%s"' % g["id"]):]
    place = place[:place.index("</article>")]
    assert 'data-ifthen="%s"' % g["id"] in place and 'data-pm-answer="%s"' % g["id"] in place, "an open goal carries both (Grok code R1 F2)"
    g["if_then"] = ""
    assert "If-then step not written yet &middot; add one in your words" in cpg.render_campaign_html(ctx), "unwritten, it asks in his words"
    t2 = next(i for i in ctx["initiatives"] if i["tier"] == 2)
    assert 'data-ifthen="%s"' % t2["id"] not in cpg.render_campaign_html(ctx), "only Tier 1 carries the line"


def test_the_cave_has_no_brief_its_nudge_keeps_the_top_and_its_labels_say_the_mode():
    ctx = w2c._ctx()
    ctx["steward"] = dict(ctx["steward"], campaign_name="Star Chart")
    ctx["nudge"] = {"kind": "starving", "key": "starving:t:1", "fact": "1", "text": "Technical papers is untouched", "why": "the strip", "acts": []}
    html = hsp.render_high_seat_html(ctx)
    assert 'id="brief"' not in html and 'class="lead"' not in html
    panel = html[html.index('<aside class="panel"'):]
    assert panel.index('id="nudgeSlot"') < panel.index('data-nudge="starving:t:1"') < panel.index('id="dialogue"')
    assert ">Open the Star Chart</a>" in html and '<span class="n">Star Chart</span>' in html and "Open the Campaign" not in html
    assert 'title="its place on the Star Chart"' in html and "a Star Chart verb applies on the record" in html
    assert '<span class="c">nudges</span>' in html
    js = open(os.path.join(HERE, "static", "high-seat-page.js"), encoding="utf-8").read()
    assert "seat: '#nudgeSlot'" in js and "$('#brief')" not in js


def test_one_lane_per_item_the_dated_one_is_the_caves_interrupt_lane():
    inits = [goal("trusts", "Family finances", 1, [part("pkg", "Stanford package", date="2026-10-02")]),
             goal("mba", "MBA Teaching", 1, [part("hw", "retool homework 2", kind="project", pid="p-mba", seat="deck", needs_you=True, state="waiting on you: approve")])]
    lane = N.derive(inits, {}, [], working=set(), today=TODAY, campaign_pid="c1", kinds={"dated"})
    panel = N.derive(inits, {}, [], working=set(), today=TODAY, campaign_pid="c1", kinds=N.NOT_DATED)
    assert lane["kind"] == "dated" and panel["kind"] == "deck_wait", "the dated item is the lane; the panel takes the next kind"
    assert N.derive(inits, {}, [], working=set(), today=TODAY, scope_goal="trusts", kinds=N.NOT_DATED) is None, "the goal's place never repeats the lane"
    ctx = w2c._ctx()
    ctx["lane"] = lane
    ctx["resume_from"] = "retool homework 2 (MBA Teaching)"
    html = hsp.render_high_seat_html(ctx)
    board = html[html.index('<div class="board">'):]
    assert board.index('<section class="lane" id="lane"') < board.index('<section class="camp"'), "the lane at the top of the board"
    ln = board[:board.index("</section>")]
    assert "Excuse me: Stanford package is due tomorrow (Family finances)." in ln and 'data-lane-open="1"' in ln and 'href="/project/c1?open=trusts"' in ln
    assert "a note of what you were on is kept: &ldquo;retool homework 2 (MBA Teaching)&rdquo;" in ln and 'data-note="retool homework 2 (MBA Teaching)"' in ln
    assert html.count(">Excuse me: Stanford package is due tomorrow (Family finances).</span>") == 1, "shown once (its attributes carry it for the acts)"
    src = open(os.path.join(HERE, "anchor_gui.py"), encoding="utf-8").read()
    assert 'lane = _nudge_or_log("high-seat-lane", lambda: _derive_nudge({"dated"}))' in src


def test_the_ready_to_resume_note_is_kept_shown_and_cleared(tmp_path):
    assert N.read_resume(str(tmp_path)) is None
    r = acts.resume(str(tmp_path), "retool homework 2 (MBA Teaching)", "Excuse me: Stanford package is due tomorrow")
    assert r["ok"] and r["undo"] == {"act": "resume_done"}
    note = N.read_resume(str(tmp_path))
    assert note["note"] == "retool homework 2 (MBA Teaching)"
    html = hsp.resume_html(note)
    assert 'id="resumeNote"' in html and "You were on retool homework 2 (MBA Teaching) when you opened: Excuse me: Stanford package is due tomorrow</span>" in html and 'data-nudge-act="resume_done"' in html
    assert N.read_resume(str(tmp_path), today=date.today().replace(year=date.today().year + 1)) is None, "two days and it is gone"
    d = acts.resume_done(str(tmp_path))
    assert d["ok"] and d["undo"]["act"] == "resume" and N.read_resume(str(tmp_path)) is None
    assert {"resume", "resume_done", "if_then", "premortem", "premortem_skip", "premortem_ask"} <= acts.ACTS


def test_the_premortem_asks_are_kept_and_closed(tmp_path):
    assert N.ask_premortem(str(tmp_path), "mba", "a new goal") and N.read_premortems(str(tmp_path))["mba"]["reason"] == "a new goal"
    assert not N.ask_premortem(str(tmp_path), "../x", "bad")
    assert N.close_premortem(str(tmp_path), "mba")["reason"] == "a new goal" and N.read_premortems(str(tmp_path)) == {}
    src = open(os.path.join(HERE, "steward_cockpit", "campaign_acts.py"), encoding="utf-8").read()
    assert 'if old != "none" and when != "none" and when > old:' in src and '_n.ask_premortem(project, sid, "a new goal")' in src, "a slipped pace and a new goal ask it"


def test_the_if_then_verb_inside_a_goal():
    rx = dict(say._SCOPED)["campaign_if_then"]
    assert rx.match("if-then: if it is Monday 9:00, then I send the trust questions").group(1) == "if it is Monday 9:00, then I send the trust questions"
    assert rx.match("next step: If a lecture is 3 days out, then I finish its supplement").group(1).startswith("If a lecture")
    assert rx.match("if it rains then stay home") is None, "only the named form; plain words go to the steward"


def test_the_remit_rides_only_the_campaign_conversation():
    r = se.campaign_mode_remit("Aladdin")
    assert "THIS CONVERSATION IS THE STAR CHART" in r and "keep your own name, Aladdin" in r and "in John's own words" in r and "interrupt lane" in r
    assert "THE CHART ROOM" in se.campaign_mode_remit("Jarvis") and "THE BEACON" in se.campaign_mode_remit("Ecgberht")
    src = open(os.path.join(HERE, "steward_cockpit", "steward_engine.py"), encoding="utf-8").read()
    assert "if not self.general and _is_campaign_dir(self.dir) and not _is_cave_dir(self.dir):\n                persona += campaign_mode_remit(self.steward)" in src


# ── the acts against a real record (Grok code R1 F6: not source substrings) ──────────────────────────────────────────
import pytest  # noqa: E402
import test_campaign_page_2026_09_26 as cp  # noqa: E402
import test_active_set_w1_2026_09_29 as w1  # noqa: E402
from steward_cockpit import campaign_seeds as seeds_mod  # noqa: E402

record = cp.record      # the throwaway Campaign record the engine CLI writes (skips when the engine is absent)
BRANCH_SPINE = "file:///C:/dev/Ecgberht-starchart-wt/engine/ledger-spine.mjs"


def test_a_promoted_seed_asks_its_premortem(record):
    seed = seeds_mod.read_seeds(record)[0]
    pr = acts.act(record, {"act": "promote", "seed": seed["id"], "tier": "1", "area": "professional"})
    assert pr["ok"], pr
    assert N.read_premortems(record)[pr["step"]]["reason"] == "a new goal"
    skip = acts.act(record, {"act": "premortem_skip", "step": pr["step"]})
    assert skip["ok"] and pr["step"] not in N.read_premortems(record) and skip["undo"]["act"] == "premortem_ask"
    assert acts.act(record, skip["undo"])["ok"] and pr["step"] in N.read_premortems(record), "its undo asks it again"


def test_the_premortem_answer_goes_into_the_guide_before_its_history(record):
    from steward_cockpit.steward_campaign import read_guide, write_guide
    assert write_guide(record, "a", "# Initiative A\n\nWhat done looks like.\n\n## History\n- 2026-10-01 - written", who="the steward")["ok"]
    N.ask_premortem(record, "a", "a new goal")
    r = acts.act(record, {"act": "premortem", "step": "a", "text": "the counsel never answered and I did not chase"})
    assert r["ok"], r
    g = read_guide(record, "a")["text"]
    assert g.index("## Premortem, ") < g.index("## History"), "the answer sits above the history"
    assert "It is three months on and this goal fell short: what went wrong?\nthe counsel never answered and I did not chase" in g
    assert "What done looks like." in g and "- 2026-10-01 - written" in g, "nothing he wrote is lost"
    assert "a" not in N.read_premortems(record)
    assert acts.act(record, {"act": "premortem", "step": "a", "text": " "})["ok"] is False


def test_a_slipped_pace_asks_the_premortem_and_an_earlier_one_does_not(tmp_path, monkeypatch):
    d = w1._record(tmp_path)
    monkeypatch.setattr(acts, "_cli", w1._fake_cli(tmp_path))
    assert acts.act(d, {"act": "pace", "step": "magi", "when": "2026-12-01"})["ok"]      # earlier than Dec 15
    assert "magi" not in N.read_premortems(d)
    assert acts.act(d, {"act": "pace", "step": "magi", "when": "2027-01-31"})["ok"]      # later: it slipped
    assert N.read_premortems(d)["magi"]["reason"] == "its pace moved from 2026-12-01 to 2027-01-31"


def test_the_if_then_is_written_on_the_record_and_read_back(record, monkeypatch):
    if not os.path.isfile(r"C:\dev\Ecgberht-starchart-wt\engine\ledger-spine.mjs"):
        pytest.skip("the engine branch carrying if_then is not on this machine")
    monkeypatch.setattr(acts, "SPINE", BRANCH_SPINE)
    words = "If it is Monday 9:00, then I send the trust questions"
    r = acts.act(record, {"act": "if_then", "step": "a", "text": words})
    assert r["ok"], r
    a = {i["id"]: i for i in hsp.campaign_initiatives(acts._projection(record))}["a"]
    assert a["if_then"] == words, "the projection carries it to the page"
    assert acts.act(record, {"act": "if_then", "step": "a", "text": words})["ok"] is False, "already reads so"
    u = acts.act(record, r["undo"])
    assert u["ok"] and {i["id"]: i for i in hsp.campaign_initiatives(acts._projection(record))}["a"]["if_then"] == ""


def test_the_remit_rides_every_bridge_turn_of_the_campaign_only():
    src = open(os.path.join(HERE, "steward_cockpit", "steward_engine.py"), encoding="utf-8").read()
    i = src.index('msg["standing_rules"] = self._contract()')
    assert 'msg["standing_rules"] = campaign_mode_remit(self.steward) + self._contract()' in src[i:i + 500]
    assert "_is_campaign_dir(self.dir) and not _is_cave_dir(self.dir)" in src[i:i + 500]
