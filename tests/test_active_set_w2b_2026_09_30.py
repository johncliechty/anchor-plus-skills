"""W2b-2 of the active set (2026-09-30, PLAN v1.3.1 - his three levels): a goal's components carry their SEAT (active ·
deck · none); the acts seat and home with undo, the seat's order kept; the head reads Active, then On deck, then the
tiers; the pick-up is the top of On deck; the verbs name components and a goal comes from words; the effort:
reference resolves one cockpit within a project; the goal's place shows each component's seat with its buttons."""
import json
import os
import re
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import campaign_page as cpg  # noqa: E402
import high_seat_page as hsp  # noqa: E402
import home_attention as ha  # noqa: E402
import test_campaign_page_2026_09_26 as base  # noqa: E402
from steward_cockpit import campaign_acts as acts  # noqa: E402
from steward_cockpit import campaign_parts as parts  # noqa: E402
from steward_cockpit import campaign_say as say  # noqa: E402

TODAY = date(2026, 9, 30)
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _steps(seats=None):
    """Two goals: the trusts (two cockpits, a desk task) and MBA (a cockpit); seats as given {part id: (seat, order)}."""
    seats = seats or {}

    def head(sid, name, tier, order):
        return {"id": sid, "name": name, "status": "proposed", "tier": tier, "done_when": name + " done",
                "navigation": {"path": [sid], "groups": [{"id": sid, "label": name, "order": order, "parent_id": None}]}}

    def part(sid, head_id, name, **more):
        d = dict({"id": sid, "name": name, "status": "planned", "navigation": {"path": [head_id]}}, **more)
        if sid in seats:
            d["seat"], d["seat_order"] = seats[sid]
        return d
    return [
        head("trusts", "The trusts and the holding company", 1, 0),
        part("ft", "trusts", "Family Trusts (the project)", ref="project:p-ft"),
        part("hc", "trusts", "Holding Company (the project)", ref="project:p-hc"),
        part("pkg", "trusts", "Send the Stanford package", status="waiting", waiting_on="John", due="2026-10-08"),
        head("mba", "MBA Teaching, Fall 2026", 1, 1),
        part("mba-ai", "mba", "MBA Teaching AI (the project)", ref="project:p-mba"),
        part("lec", "mba", "Lectures 3 + 4", ref="step:p-mba/lec34", due="2026-10-10"),
    ]


RESOLVED = {
    "ft": {"kind": "project", "name": "Family Trusts", "what": "the package", "state": "waiting on you: send the package to Stanford", "pid": "p-ft", "href": "/project/p-ft", "broken": False},
    "hc": {"kind": "project", "name": "Holding Company", "what": "", "state": "", "pid": "p-hc", "href": "/project/p-hc", "broken": False},
    "mba-ai": {"kind": "project", "name": "MBA Teaching AI", "what": "the supplements", "state": "waiting", "pid": "p-mba", "href": "/project/p-mba", "broken": False},
    "lec": {"kind": "step", "name": "MBA Teaching AI", "what": "Lectures 3 + 4 revised", "state": "waiting", "pid": "p-mba", "href": "/project/p-mba", "date": "2026-10-10", "broken": False},
}


def test_the_components_carry_their_seats_and_the_one_sort_orders_them():
    inits = hsp.campaign_initiatives(_steps({"ft": ("active", 1), "mba-ai": ("active", 0), "pkg": ("deck", 0)}), RESOLVED)
    by = {p["id"]: p for i in inits for p in i["parts"]}
    assert by["ft"]["seat"] == "active" and by["ft"]["seat_order"] == 1 and by["hc"]["seat"] == "" and by["pkg"]["seat"] == "deck"
    assert by["ft"]["goal"] == "trusts" and by["ft"]["goal_name"].startswith("The trusts")
    assert [(g["id"], p["id"]) for g, p in hsp.seated(inits, "active")] == [("mba", "mba-ai"), ("trusts", "ft")], "his order, not the goals'"
    assert [(g["id"], p["id"]) for g, p in hsp.seated(inits, "deck")] == [("trusts", "pkg")]
    assert hsp.is_initiative(by["ft"]) and hsp.is_initiative(by["pkg"]) and not hsp.is_initiative(by["lec"]), "a cockpit and a desk item take seats; a step of a project rides inside"
    assert hsp.part_name(by["ft"]) == "Family Trusts" and hsp.part_name(by["pkg"]) == "Send the Stanford package"
    assert "active" not in inits[0] and "active_order" not in inits[0], "the goal has no seat (W0's goal-level set is superseded)"


def test_the_head_reads_active_then_on_deck_then_the_tiers_and_the_pick_up_is_the_top_of_on_deck():
    # Family Trusts needs him and is active: it leads, whatever the goals' order
    inits = hsp.campaign_initiatives(_steps({"mba-ai": ("active", 0), "ft": ("active", 1), "pkg": ("deck", 0)}), RESOLVED)
    act = ha.head_act(inits, [], today=TODAY)
    assert act["kind"] == "active" and act["part"] == "Family Trusts" and act["initiative"].startswith("The trusts")
    assert ha.head_sentence(act).startswith("Active · Family Trusts (The trusts and the holding company): send the package to Stanford — waiting on you.")
    # nothing active needs him: the one on deck that needs him leads, with its date
    inits = hsp.campaign_initiatives(_steps({"mba-ai": ("active", 0), "pkg": ("deck", 0)}), {k: v for k, v in RESOLVED.items() if k != "ft"} | {"ft": dict(RESOLVED["ft"], state="")})
    act = ha.head_act(inits, [], today=TODAY)
    assert act["kind"] == "deck" and act["part"] == "Send the Stanford package" and act["due"] == "" , "the package is dated Oct 8, not yet due"
    assert ha.head_sentence(act).startswith("On deck · Send the Stanford package (The trusts and the holding company) — waiting on you."), "a wait on John alone adds no middle (Grok: no restatement)"
    # nothing seated needs him: the tiers as before
    inits = hsp.campaign_initiatives(_steps({"mba-ai": ("active", 0)}), {k: v for k, v in RESOLVED.items() if k != "ft"} | {"ft": dict(RESOLVED["ft"], state="")})
    act = ha.head_act(inits, [], today=TODAY)
    assert act["kind"] == "tier1" and act["text"] == "Send the Stanford package"
    # the pick-up: Active runs (a session on MBA) and nothing needs him; the top of On deck is the pick-up
    quiet = {k: dict(v, state="") for k, v in RESOLVED.items()}
    inits = hsp.campaign_initiatives([dict(s, status="planned", waiting_on=None) if s["id"] == "pkg" else s for s in _steps({"mba-ai": ("active", 0), "hc": ("deck", 0), "ft": ("deck", 1)})], quiet)
    pk = ha.pick_up(inits, [], working={"p-mba"}, today=TODAY)
    assert pk and pk["initiative"] == "Holding Company" and pk["goal"].startswith("The trusts") and pk["why"] == "on deck" and pk["running"] == ["MBA Teaching AI"]
    assert ha.head_sentence(None, pickup=pk).startswith("Active: MBA Teaching AI is running. While it runs: pick up Holding Company (The trusts and the holding company) (on deck).")
    assert ha.pick_up(inits, [], working=set(), today=TODAY) is None, "an active initiative with a free hand is his next act"
    assert ha.pick_up(hsp.campaign_initiatives(_steps({"mba-ai": ("active", 0)}), quiet), [], working={"p-mba"}, today=TODAY) is None, "an empty deck offers nothing"
    assert ha.pick_up(hsp.campaign_initiatives(_steps({"hc": ("deck", 0)}), quiet), [], working=set(), today=TODAY) is None, "nothing active: nothing to be while of"


def _record(tmp_path, seats=None):
    d = tmp_path / "Campaign"; d.mkdir()
    (d / "roadmap.json").write_text(json.dumps({"schema": "x", "roadmap_events": [], "roadmap_projection": _steps(seats)}), encoding="utf-8")
    return str(d)


def _fake_engine(tmp_path, monkeypatch):
    def fake_cli(project, *args):
        steps = json.loads((tmp_path / "Campaign" / "roadmap.json").read_text(encoding="utf-8"))
        if args[0] == "roadmap-propose":
            sid = args[args.index("--step") + 1]
            steps["roadmap_projection"].append({"id": sid, "name": args[args.index("--name") + 1], "status": "proposed", "tier": int(args[args.index("--tier") + 1]), "done_when": args[args.index("--done-when") + 1]})
        else:
            sid = args[args.index("--step") + 1]
            for s in steps["roadmap_projection"]:
                if s["id"] == sid:
                    if "--seat-in" in args:
                        v = args[args.index("--seat-in") + 1]
                        if v == "none": s.pop("seat", None); s.pop("seat_order", None)
                        else: s["seat"] = v
                    if "--seat-order" in args: s["seat_order"] = int(args[args.index("--seat-order") + 1])
                    if "--tier" in args: s["tier"] = int(args[args.index("--tier") + 1])
        (tmp_path / "Campaign" / "roadmap.json").write_text(json.dumps(steps), encoding="utf-8")
        return {"ok": True}
    monkeypatch.setattr(acts, "_cli", fake_cli)

    def fake_spine(project, step_id, fields):
        steps = json.loads((tmp_path / "Campaign" / "roadmap.json").read_text(encoding="utf-8"))
        for s in steps["roadmap_projection"]:
            if s["id"] == step_id:
                s.update(fields)
        (tmp_path / "Campaign" / "roadmap.json").write_text(json.dumps(steps), encoding="utf-8")
        return {"ok": True}
    monkeypatch.setattr(acts, "_spine_set", fake_spine)


def test_seat_and_home_are_one_act_each_with_undo_and_the_seat_s_order_kept(tmp_path, monkeypatch):
    d = _record(tmp_path)
    _fake_engine(tmp_path, monkeypatch)
    ids = lambda s: acts._seat_ids(d, s)
    r = acts.act(d, {"act": "seat", "step": "ft", "seat": "active"})
    assert r["ok"] and r["receipt"] == "Family Trusts (the project) (The trusts and the holding company) is active — active: Family Trusts (the project)" and r["undo"] == {"act": "home", "step": "ft"}
    r = acts.act(d, {"act": "seat", "step": "mba-ai", "seat": "active", "position": 0})
    assert r["ok"] and ids("active") == ["mba-ai", "ft"], "at the position he dropped it; the others close up"
    r = acts.act(d, {"act": "seat", "step": "pkg", "seat": "deck"})
    assert r["ok"] and r["receipt"].endswith("is on deck — on deck: Send the Stanford package") and ids("deck") == ["pkg"]
    # active → deck: the seat changes; the undo carries the old seat and place
    r = acts.act(d, {"act": "seat", "step": "ft", "seat": "deck", "position": 0})
    assert r["ok"] and ids("active") == ["mba-ai"] and ids("deck") == ["ft", "pkg"] and r["undo"] == {"act": "seat", "step": "ft", "seat": "active", "position": 1}
    r = acts.act(d, r["undo"])
    assert r["ok"] and ids("active") == ["mba-ai", "ft"] and ids("deck") == ["pkg"]
    # home: back into its goal; the seat closes up; the undo re-seats it
    r = acts.act(d, {"act": "home", "step": "mba-ai"})
    assert r["ok"] and r["receipt"].startswith("MBA Teaching AI (the project) back in MBA Teaching, Fall 2026 — active: Family Trusts") and ids("active") == ["ft"] and acts._step(d, "ft")["seat_order"] == 0
    assert r["undo"] == {"act": "seat", "step": "mba-ai", "seat": "active", "position": 0}
    r = acts.act(d, r["undo"])
    assert r["ok"] and ids("active") == ["mba-ai", "ft"]
    # refusals: a goal has no seat (it names its components); an element rides inside; already there; in its goal already
    r = acts.act(d, {"act": "seat", "step": "trusts", "seat": "active"})
    assert not r["ok"] and "a goal has no seat" in r["receipt"] and "Family Trusts (the project)" in r["receipt"]
    assert "rides inside its goal" in acts.act(d, {"act": "seat", "step": "lec", "seat": "active"})["receipt"]
    assert not acts.act(d, {"act": "seat", "step": "ft", "seat": "active"})["ok"] and not acts.act(d, {"act": "home", "step": "hc"})["ok"]
    assert not acts.act(d, {"act": "seat", "step": "ft", "seat": "bench"})["ok"]
    # no cap: a fourth active is named, never refused
    for sid in ("hc", "pkg"):
        acts.act(d, {"act": "seat", "step": sid, "seat": "active"})
    assert "4 active is wider than three" in acts.act(d, {"act": "seat", "step": "lec2", "seat": "active"}).get("receipt", "") or len(ids("active")) == 4
    # the drop of a goal on the board is the tier only
    r = acts.act(d, {"act": "place", "step": "mba", "band": "2"})
    assert r["ok"] and acts._step(d, "mba")["tier"] == 2 and r["undo"] == {"act": "place", "step": "mba", "band": "1", "position": 0}
    assert not acts.act(d, {"act": "place", "step": "mba", "band": "2"})["ok"]


def test_a_goal_from_his_words_when_no_seed_matches(tmp_path, monkeypatch):
    d = _record(tmp_path)
    _fake_engine(tmp_path, monkeypatch)
    monkeypatch.setattr(acts, "seed_by_id", lambda project, sid: None)
    monkeypatch.setattr(say, "compile_utterance", lambda text, dialogue=None: {"ok": True, "campaign": True, "act": "campaign_promote_seed", "args": {"seed": "Get OpX working again", "tier": 2}})
    monkeypatch.setattr(say, "seeds_of", lambda folder: [], raising=False)
    r = say.say_campaign(d, "make Get OpX working again a goal in tier 2", today=TODAY)
    assert r and r["ok"] and r["receipt"] == "Get OpX working again is now a goal in tier 2" and r["undo"]["act"] == "withdraw"
    g = acts._step(d, r["step"])
    assert g["tier"] == 2 and g["navigation"]["groups"][0]["parent_id"] is None


def test_the_verbs_name_components_and_inside_a_goal_they_need_no_goal(tmp_path, monkeypatch):
    d = _record(tmp_path)
    _fake_engine(tmp_path, monkeypatch)
    monkeypatch.setattr(say, "compile_utterance", lambda text, dialogue=None: {"ok": True, "campaign": True, "act": "campaign_activate", "args": {"initiative": "family trusts"}})
    r = say.say_campaign(d, "make family trusts active", today=TODAY)
    assert r and r["ok"] and acts._step(d, "ft")["seat"] == "active"
    monkeypatch.setattr(say, "compile_utterance", lambda text, dialogue=None: {"ok": True, "campaign": True, "act": "campaign_deck", "args": {"initiative": "holding company"}})
    r = say.say_campaign(d, "put holding company on deck", today=TODAY)
    assert r and r["ok"] and acts._step(d, "hc")["seat"] == "deck"
    monkeypatch.setattr(say, "compile_utterance", lambda text, dialogue=None: {"ok": True, "campaign": True, "act": "campaign_home", "args": {"initiative": "family trusts"}})
    r = say.say_campaign(d, "send family trusts back", today=TODAY)
    assert r and r["ok"] and not acts._step(d, "ft").get("seat")
    monkeypatch.setattr(say, "compile_utterance", lambda text, dialogue=None: {"ok": True, "campaign": True, "act": "campaign_activate", "args": {"initiative": "the trusts"}})
    r = say.say_campaign(d, "make the trusts active", today=TODAY)
    assert r and not r["ok"] and "a goal has no seat" in r["say"] and "Family Trusts (the project)" in r["say"], "a goal's name refuses and names its components"
    # inside a goal's place: no goal name needed; a goal itself cannot be seated
    monkeypatch.setattr(say, "compile_utterance", lambda text, dialogue=None: {"ok": False, "campaign": False})
    r = say.say_campaign(d, "put the Stanford package on deck", today=TODAY, goal="trusts")
    assert r and r["ok"] and acts._step(d, "pkg")["seat"] == "deck"
    r = say.say_campaign(d, "make Family Trusts active", today=TODAY, goal="trusts")
    assert r and r["ok"] and acts._step(d, "ft")["seat"] == "active"
    r = say.say_campaign(d, "send Family Trusts back", today=TODAY, goal="trusts")
    assert r and r["ok"] and not acts._step(d, "ft").get("seat")
    r = say.say_campaign(d, "make it active", today=TODAY, goal="trusts")
    assert r and not r["ok"] and "a goal has no seat" in r["say"]


def test_the_effort_reference_resolves_one_cockpit_within_a_project(tmp_path):
    proj = tmp_path / "Magi"; eff = proj / "book-one"; (eff / ".ecgberht").mkdir(parents=True)
    (proj / "roadmap.json").write_text(json.dumps({"roadmap_projection": []}), encoding="utf-8")
    (eff / "ECGBERHT.md").write_text("# Book one, the draft\n\nthe Face\n", encoding="utf-8")
    (eff / "roadmap.json").write_text(json.dumps({"roadmap_projection": [{"id": "ch2", "name": "Chapter 2", "status": "active", "due": "2026-10-20"}]}), encoding="utf-8")
    (eff / ".ecgberht" / "attention.json").write_text(json.dumps({"state": "needs_you", "reason": "the chapter 2 scenes wait on your read"}), encoding="utf-8")
    lookup = lambda pid: {"id": "p-magi", "name": "Artificial Magi", "folder_path": str(proj)} if pid == "p-magi" else None
    r = parts.resolve_ref("effort:p-magi/book-one", lookup=lookup)
    assert r["kind"] == "effort" and not r["broken"] and r["name"] == "Artificial Magi · Book one, the draft" and r["what"] == "Book one, the draft"
    assert r["state"] == "waiting on you: the chapter 2 scenes wait on your read" and r["href"] == "/project/p-magi?dir=book-one" and r["date"] == "2026-10-20"
    assert parts.resolve_ref("effort:p-magi/nowhere", lookup=lookup)["broken"] and parts.parse_ref("effort:p-magi") is None


def test_the_place_shows_each_component_s_seat_with_its_buttons_and_the_face_marks_them():
    ctx = base._ctx(); ctx["today"] = TODAY
    ctx["initiatives"] = hsp.campaign_initiatives(_steps({"ft": ("active", 0), "pkg": ("deck", 0)}), RESOLVED)
    html = cpg.render_campaign_html(ctx, open_id="trusts")
    place = html[html.index('id="place-trusts"'):html.index('id="place-mba"')]
    assert '<span class="seat active">active</span>' in place and 'data-seat="deck" data-step="ft"' in place and 'data-home="ft"' in place
    assert '<span class="seat deck">on deck</span>' in place and 'data-seat="active" data-step="pkg"' in place
    assert 'data-seat="deck" data-step="hc"' in place and 'data-seat="active" data-step="hc"' in place, "a component in its goal offers both seats"
    assert 'data-step="lec"' not in html, "a step of a project rides inside: no seat buttons"
    board = html[html.index('<div class="bands"'):html.index('id="viewCal"')]
    trusts = board[board.index('data-lane="trusts"'):board.index('data-lane="mba"')]
    assert 'Family Trusts <i>&#9873;</i><b class="seat active">active</b>' in trusts, "the face marks the seat"
    js = open(os.path.join(HERE, "static", "campaign-page.js"), encoding="utf-8").read()
    assert "act({ act: 'seat', step: b.getAttribute('data-step'), seat: b.getAttribute('data-seat') })" in js and "act({ act: 'home', step: b.getAttribute('data-home') })" in js


# ── Grok's read of W2b (2026-09-30, RABBIT-W2B): the holes it named ──────────────────────────────────────────────

def _slug_steps(seats=None):
    """The same record with the trusts goal under a slug id (Grok: 'make the trusts active' refused only because the id
    was the word)."""
    out = []
    for s in _steps(seats):
        s = json.loads(json.dumps(s))
        if s["id"] == "trusts":
            s["id"] = "g1"; s["navigation"]["path"] = ["g1"]; s["navigation"]["groups"][0]["id"] = "g1"
        elif s["navigation"].get("path") == ["trusts"]:
            s["navigation"]["path"] = ["g1"]
        out.append(s)
    return out


def test_the_start_of_a_goal_s_name_refuses_the_seat_verbs_and_a_component_s_words_still_seat(tmp_path, monkeypatch):
    d = tmp_path / "Campaign"; d.mkdir()
    (d / "roadmap.json").write_text(json.dumps({"schema": "x", "roadmap_events": [], "roadmap_projection": _slug_steps()}), encoding="utf-8")
    d = str(d); _fake_engine(tmp_path, monkeypatch)
    monkeypatch.setattr(say, "compile_utterance", lambda text, dialogue=None: {"ok": True, "campaign": True, "act": "campaign_activate", "args": {"initiative": "the trusts"}})
    r = say.say_campaign(d, "make the trusts active", today=TODAY)
    assert r and not r["ok"] and "a goal has no seat" in r["say"] and "Family Trusts (the project)" in r["say"], "the start of one goal's name (the pace rule) is the goal, whatever its id"
    assert not acts._step(d, "ft").get("seat") and not acts._step(d, "hc").get("seat")
    monkeypatch.setattr(say, "compile_utterance", lambda text, dialogue=None: {"ok": True, "campaign": True, "act": "campaign_deck", "args": {"initiative": "holding company"}})
    r = say.say_campaign(d, "put holding company on deck", today=TODAY)
    assert r and r["ok"] and acts._step(d, "hc")["seat"] == "deck", "words inside a goal's name that are one component's words seat the component"


def test_a_refused_close_up_still_carries_the_undo(tmp_path, monkeypatch):
    d = _record(tmp_path, {"mba-ai": ("active", 0)})
    _fake_engine(tmp_path, monkeypatch)
    real = acts._cli

    def failing_second(project, *args):
        # the moved step lands; the close-up of the others is refused by the engine
        sid = args[args.index("--step") + 1]
        if sid != "ft" and "--seat-order" in args:
            return {"ok": False, "error": "a fake refusal"}
        return real(project, *args)
    monkeypatch.setattr(acts, "_cli", failing_second)
    r = acts.act(d, {"act": "seat", "step": "ft", "seat": "active", "position": 0})
    assert not r["ok"] and "undo puts it back" in r["receipt"] and r["undo"] == {"act": "home", "step": "ft"}, "the seat landed; the refusal says so and carries the way back"
    assert acts._step(d, "ft")["seat"] == "active"


def test_a_near_seed_is_answered_and_nothing_is_written(tmp_path, monkeypatch):
    d = _record(tmp_path)
    _fake_engine(tmp_path, monkeypatch)
    import steward_cockpit.campaign_seeds as seeds
    monkeypatch.setattr(seeds, "read_seeds", lambda folder: [{"id": "s1", "text": "Get OpX code working again"}, {"id": "s2", "text": "Get OpX docs written"}])
    monkeypatch.setattr(say, "compile_utterance", lambda text, dialogue=None: {"ok": True, "campaign": True, "act": "campaign_promote_seed", "args": {"seed": "Get OpX", "tier": 2}})
    n = len(acts._projection(d))
    r = say.say_campaign(d, "make Get OpX a goal in tier 2", today=TODAY)
    assert r and not r["ok"] and "could be" in r["say"] and "Get OpX code working again" in r["say"] and "Get OpX docs written" in r["say"], "a tie among the seeds is answered with the names"
    assert len(acts._projection(d)) == n, "a near miss writes nothing; only 'no seed named' makes a goal from the words"
    monkeypatch.setattr(say, "compile_utterance", lambda text, dialogue=None: {"ok": True, "campaign": True, "act": "campaign_promote_seed", "args": {"seed": "OpX cod", "tier": 2}})
    r = say.say_campaign(d, "make OpX cod a goal in tier 2", today=TODAY)
    assert r and not r["ok"] and "did you mean" in r["say"] and len(acts._projection(d)) == n, "a near seed is answered, not made a goal"


def test_a_working_effort_stays_working_and_an_effort_is_one_directory_inside_its_project(tmp_path):
    proj = tmp_path / "Magi"; eff = proj / "book-one"; (eff / ".ecgberht").mkdir(parents=True)
    (proj / "roadmap.json").write_text(json.dumps({"roadmap_projection": []}), encoding="utf-8")
    (eff / "ECGBERHT.md").write_text("# Book one\n", encoding="utf-8")
    (eff / "roadmap.json").write_text(json.dumps({"roadmap_projection": []}), encoding="utf-8")
    (eff / ".ecgberht" / "attention.json").write_text(json.dumps({"state": "working", "reason": "waiting on you to read chapter 2"}), encoding="utf-8")
    lookup = lambda pid: {"id": "p-magi", "name": "Artificial Magi", "folder_path": str(proj)} if pid == "p-magi" else None
    r = parts.resolve_ref("effort:p-magi/book-one", lookup=lookup)
    assert r["state"].startswith("working") and not r.get("needs_you"), "a working flag with a stale sentence is not a wait"
    # a sibling of the project, or the project itself, is not one of its efforts
    other = tmp_path / "Other"; (other / ".ecgberht").mkdir(parents=True); (other / "ECGBERHT.md").write_text("# Other\n", encoding="utf-8")
    for bad in ("effort:p-magi/..", "effort:p-magi/.", "effort:p-magi/..\\Other"):
        rr = parts.resolve_ref(bad, lookup=lookup)
        assert rr["broken"] and ("one directory inside" in rr["gap"] or "not a reference" in rr["gap"]), bad
