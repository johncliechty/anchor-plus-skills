"""The Candidates tile under On deck (his word, 2026-10-02: "a tile that can be expanded, right below the on deck that
shows all of the candidates -- those would be anything with an AI Cockpit as well as any open tasks/efforts"), the
one act that seats a cockpit not yet on the Campaign, and the hidden no-goal group that shows it on the shelves."""
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import high_seat_page as hsp  # noqa: E402
from steward_cockpit import campaign_acts as acts  # noqa: E402
from tests.test_active_set_w2b_2026_09_30 import _steps, RESOLVED  # noqa: E402


def _ctx(steps, facts=None, entries=None):
    inits = hsp.campaign_initiatives(steps, RESOLVED)
    loose = hsp.loose_initiative(steps, RESOLVED)
    if loose:
        inits.append(loose)
    return {"initiatives": inits, "facts": facts or {}, "entries": entries or [], "campaign": {"pid": "camp"}}


def test_the_candidates_are_the_open_components_in_goals_and_the_cockpits_not_on_the_campaign():
    facts = {
        "p-ft": {"name": "Family Trusts", "has_record": True, "efforts": [{"rel": "", "name": "Family Trusts"}]},
        "p-dar": {"name": "DARPA", "has_record": True, "efforts": [{"rel": "DARPA proposal", "name": "DARPA proposal", "needs_you": "a decision"}]},
        "p-quiet": {"name": "Quiet", "has_record": False},
        "camp": {"name": "Campaign", "has_record": True},
    }
    entries = [{"id": "p-ft", "name": "Family Trusts"}, {"id": "p-dar", "name": "DARPA"}, {"id": "p-quiet"}, {"id": "camp"}]
    in_goal, loose = hsp.candidates(_ctx(_steps({"ft": ("active", 0)}), facts, entries))
    names = {hsp.part_name(p) for _i, p in in_goal}
    assert "Family Trusts" not in names, "a seated one is on the desk already"
    assert {"Holding Company", "Send the Stanford package", "MBA Teaching AI"} <= names and "Lectures 3 + 4" not in names, "a step rides in its goal"
    assert [c["ref"] for c in loose] == ["effort:p-dar/DARPA%20proposal"] and loose[0]["needs"], "only cockpits not on the map; no record, no candidate"
    html = hsp._candidates_tile(_ctx(_steps(), facts, entries))
    assert 'id="shCands"' in html and 'data-cand-seat="deck" data-ref="effort:p-dar/DARPA%20proposal"' in html and 'data-seat="active" data-step="hc"' in html


def _record(tmp_path, steps):
    d = tmp_path / "Campaign"; d.mkdir()
    (d / "roadmap.json").write_text(json.dumps({"schema": "x", "roadmap_events": [], "roadmap_projection": steps}), encoding="utf-8")
    return str(d)


def _fake(tmp_path, monkeypatch):
    path = tmp_path / "Campaign" / "roadmap.json"

    def cli(project, *args):
        rec = json.loads(path.read_text(encoding="utf-8"))
        sid = args[args.index("--step") + 1]
        if args[0] == "roadmap-propose":
            rec["roadmap_projection"].append({"id": sid, "name": args[args.index("--name") + 1], "status": "proposed", "ref": args[args.index("--ref") + 1]})
        else:
            for s in rec["roadmap_projection"]:
                if s["id"] == sid:
                    if "--seat-in" in args:
                        v = args[args.index("--seat-in") + 1]
                        if v == "none": s.pop("seat", None); s.pop("seat_order", None)
                        else: s["seat"] = v
                    if "--seat-order" in args: s["seat_order"] = int(args[args.index("--seat-order") + 1])
                    if "--status" in args: s["status"] = args[args.index("--status") + 1]
        path.write_text(json.dumps(rec), encoding="utf-8")
        return {"ok": True}
    monkeypatch.setattr(acts, "_cli", cli)
    monkeypatch.setattr(acts, "_spine_set", lambda project, sid, fields: {"ok": True})


def test_seat_new_puts_a_cockpit_on_the_desk_in_one_act_and_the_shelf_shows_it(tmp_path, monkeypatch):
    d = _record(tmp_path, _steps())
    _fake(tmp_path, monkeypatch)
    r = acts.act(d, {"act": "seat_new", "ref": "effort:p-dar/DARPA%20proposal", "name": "DARPA · DARPA proposal", "seat": "deck"})
    assert r["ok"] and "on deck" in r["receipt"] and r["undo"] == {"act": "withdraw", "step": r["undo"]["step"]}
    steps = json.loads((tmp_path / "Campaign" / "roadmap.json").read_text(encoding="utf-8"))["roadmap_projection"]
    new = [s for s in steps if s.get("ref") == "effort:p-dar/DARPA%20proposal"]
    assert len(new) == 1 and new[0]["seat"] == "deck"
    # a second ask seats the same component again, never a second card
    r2 = acts.act(d, {"act": "seat_new", "ref": "effort:p-dar/DARPA%20proposal", "name": "DARPA · DARPA proposal", "seat": "active"})
    steps = json.loads((tmp_path / "Campaign" / "roadmap.json").read_text(encoding="utf-8"))["roadmap_projection"]
    assert r2["ok"] and len([s for s in steps if s.get("ref") == "effort:p-dar/DARPA%20proposal"]) == 1
    # the hidden no-goal group carries it to the shelves; it is never drawn or counted as a goal
    loose = hsp.loose_initiative(steps, {})
    assert loose and loose["nogoal"] and [p["seat"] for p in loose["parts"]] == ["active"]
    inits = hsp.campaign_initiatives(steps, {}) + [loose]
    assert len(hsp.goals_only(inits)) == 2 and len(hsp.seated(inits, "active")) == 1
    assert acts.act(d, {"act": "seat_new", "ref": "step:p/x", "name": "x", "seat": "deck"})["ok"] is False
    assert acts.act(d, {"act": "seat_new", "ref": "project:p-x", "name": "x", "seat": "sideways"})["ok"] is False


def test_the_tile_shows_the_plan_tab_and_the_goal_bar_like_the_cockpit():
    css = open(os.path.join(HERE, "steward_cockpit", "static", "shared.css"), encoding="utf-8").read()
    assert ".app.tileview [data-boneyard],.app.tileview [data-min]{display:none !important}" in css
    assert ".app.tileview .goalbar" not in css and ".app.tileview .railtab" not in css and ".app3.tileview{" not in css


def test_the_relevance_score_reads_the_record_and_the_steward_s_own_score_stands():
    from datetime import date
    today = date(2026, 10, 2)
    s, why = hsp.relevance({"needs": True, "due": "2026-10-05", "tier": 1, "worked": "2026-10-02"}, today)
    assert s == 100 and "waits on you" in why and "due in 3 days" in why and "worked today" in why
    s2, why2 = hsp.relevance({"worked": "2026-07-01"}, today)
    assert s2 == 10 and "still for" in why2
    assert hsp.relevance({}, today, {"score": 88, "why": "the steward thinks so"}) == (88, "the steward thinks so")


def test_the_tile_searches_and_sorts_by_the_steward_s_score_the_last_work_and_the_birth():
    facts = {"p-dar": {"name": "DARPA", "has_record": True, "folder": "", "efforts": [{"rel": "DARPA proposal", "name": "DARPA proposal"}]}}
    html = hsp._candidates_tile(_ctx(_steps(), facts, [{"id": "p-dar"}]))
    assert 'id="candSearch"' in html and 'id="candSort"' in html and '<option value="score" selected>' in html
    assert '<option value="worked">' in html and '<option value="created">' in html and 'data-score="' in html and 'class="cs" title="' in html
    js = open(os.path.join(HERE, "static", "high-seat-page.js"), encoding="utf-8").read()
    assert "r.hidden = !hit;" in js and "sessionStorage.setItem('hs_cands_sort', key)" in js


def test_two_conversations_the_cave_s_and_the_campaign_s_each_the_steward_s_dialogue_alone():
    # his word 2026-10-02: one conversation for the Cave of Wonders, one for the Campaign; the steward's dialogue from an
    # AI Cockpit with a thinner status line, no plan
    cave = hsp.conversation_view("Aladdin", "camp", "cave", hsp.CAVE_EFFORT, "the Cave of Wonders")
    camp = hsp.conversation_view("Aladdin", "camp", "campaign", "", "the Campaign")
    assert "view=talk" in cave and "dir=Cave%20of%20Wonders" in cave and 'data-dir="Cave of Wonders"' in cave and "Aladdin &mdash; the Cave of Wonders" in cave
    assert "view=talk" in camp and "dir=\"" in camp and "Aladdin &mdash; the Campaign" in camp
    css = open(os.path.join(HERE, "steward_cockpit", "static", "shared.css"), encoding="utf-8").read()
    for hidden in (".app.talkview .leftcol", ".app.talkview .goalbar", ".app.talkview .rightcol", ".app.talkview .composer", ".app.talkview [data-drive]"):
        assert hidden in css, hidden
    from steward_cockpit import campaign_say
    from steward_cockpit.steward_engine import _is_cave_dir
    assert campaign_say.CAVE_EFFORT == hsp.CAVE_EFFORT and _is_cave_dir(str(campaign_say.campaign_dir() / hsp.CAVE_EFFORT))
    js = open(os.path.join(HERE, "static", "high-seat-page.js"), encoding="utf-8").read()
    assert "pid: CAMPAIGN, dir: CAVE_DIR, headers: headers," in js
