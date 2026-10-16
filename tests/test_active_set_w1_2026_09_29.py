"""W1 of the active set (2026-09-29), as it stands after W2b-2 (2026-09-30, his three levels): the goals carry the
pace, the goal and the parts' progress; the pace act with undo; the spoken pace verb and the bare "X by <date>"
read against the goals' names; the page's lead takes the pick-up. The goal-level active set of W1 is superseded by
the seats on a goal's components (test_active_set_w2b_2026_09_30.py)."""
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import high_seat_page as hsp  # noqa: E402
import home_attention as ha  # noqa: E402
from steward_cockpit import campaign_acts as acts  # noqa: E402
from steward_cockpit import campaign_say as say  # noqa: E402

TODAY = date(2026, 9, 29)


def _steps():
    def head(sid, name, tier, order, **more):
        return dict({"id": sid, "name": name, "status": "proposed", "tier": tier, "done_when": name + " done",
                     "navigation": {"path": [sid], "groups": [{"id": sid, "label": name, "order": order, "parent_id": None}]}}, **more)

    def part(sid, head_id, name, **more):
        return dict({"id": sid, "name": name, "status": "planned", "navigation": {"path": [head_id]}}, **more)
    return [
        head("magi", "Artificial Magi", 1, 1, pace="2026-12-15"),
        part("magi-ch2", "magi", "Chapter 2 scenes", ref="project:p-magi"),
        head("mba", "MBA Teaching, Fall 2026", 1, 2, pace="2026-10-10"),
        part("mba-lec", "mba", "Lectures 3 + 4", ref="project:p-mba", due="2026-10-10"),
        head("trusts", "The trusts and the holding company", 1, 0),
        part("trusts-pkg", "trusts", "Send the Stanford package", status="waiting", waiting_on="John to send it", due="2026-10-08"),
        head("paper", "Paper 1", 2, 0),
        part("paper-draft", "paper", "Draft the paper"),
    ]


def _inits(resolved=None):
    return hsp.campaign_initiatives(_steps(), resolved or {
        "magi-ch2": {"what": "Chapter 2 scenes", "state": "active", "pid": "p-magi"},
        "mba-lec": {"what": "Lectures 3 + 4", "state": "active", "pid": "p-mba", "date": "2026-10-10"},
    })


def test_the_goals_carry_the_pace_the_goal_and_the_progress():
    inits = _inits()
    by = {i["id"]: i for i in inits}
    assert by["magi"]["pace"] == "2026-12-15" and by["mba"]["pace"] == "2026-10-10" and by["trusts"]["pace"] == ""
    assert by["magi"]["done_when"] == "Artificial Magi done" and by["magi"]["open_count"] == 1 and by["magi"]["part_count"] == 1
    assert "active" not in by["magi"], "a goal has no seat (W2b-2): its components do"
    # with nothing seated, the head reads the tiers: the Tier-1 part that needs him
    act = ha.head_act(inits, [], today=TODAY)
    assert act is not None and act["kind"] == "tier1" and act["initiative"].startswith("The trusts")
    assert ha.pick_up(inits, [], working={"p-magi", "p-mba"}, today=TODAY) is None, "nothing active: nothing to be while of"


def _record(tmp_path):
    d = tmp_path / "Campaign"; d.mkdir()
    (d / "roadmap.json").write_text(json.dumps({"schema": "x", "roadmap_events": [], "roadmap_projection": _steps()}), encoding="utf-8")
    return str(d)


def _fake_cli(tmp_path):
    def fake_cli(project, *args):
        steps = json.loads((tmp_path / "Campaign" / "roadmap.json").read_text(encoding="utf-8"))
        sid = args[args.index("--step") + 1]
        for s in steps["roadmap_projection"]:
            if s["id"] == sid:
                if "--pace" in args:
                    v = args[args.index("--pace") + 1]
                    if v == "none": s.pop("pace", None)
                    else: s["pace"] = v
        (tmp_path / "Campaign" / "roadmap.json").write_text(json.dumps(steps), encoding="utf-8")
        return {"ok": True}
    return fake_cli


def test_the_pace_act_writes_through_the_engine_with_undo(tmp_path, monkeypatch):
    d = _record(tmp_path)
    monkeypatch.setattr(acts, "_cli", _fake_cli(tmp_path))
    r = acts.act(d, {"act": "pace", "step": "magi", "when": "2027-01-31"})
    assert r["ok"] and r["receipt"] == "Artificial Magi: the pace is now 2027-01-31" and r["undo"] == {"act": "pace", "step": "magi", "when": "2026-12-15"}
    r = acts.act(d, {"act": "pace", "step": "magi", "when": "none"})
    assert r["ok"] and r["receipt"].endswith("cleared")
    assert "activate" not in acts.ACTS and "bench" not in acts.ACTS and "order" not in acts.ACTS, "the goal-level set acts are gone (W2b-2)"


def test_the_spoken_pace_and_the_bare_by_read_against_the_goals(tmp_path, monkeypatch):
    d = _record(tmp_path)
    monkeypatch.setattr(acts, "_cli", lambda project, *args: {"ok": True})
    monkeypatch.setattr(say, "compile_utterance", lambda text, dialogue=None: {"ok": True, "campaign": True, "act": "campaign_pace", "args": {"initiative": "mba teaching", "pace": "Oct 10"}})
    r = say.say_campaign(d, "set the pace of mba teaching to Oct 10", today=TODAY)
    assert r and r["ok"] and r["act"] == "campaign_pace" and "2026-10-10" in r["receipt"]
    # the bare "<name> by <date>" is read by the applier against the goals' names: the whole name or the start of
    # exactly one; an interior word, no name or no date goes to the steward
    monkeypatch.setattr(say, "compile_utterance", lambda text, dialogue=None: {"ok": False, "campaign": False})
    written = []
    monkeypatch.setattr(acts, "_cli", lambda project, *args: (written.append(list(args)), {"ok": True})[1])
    r = say.say_campaign(d, "MBA by Oct 10", today=TODAY)
    assert r and r["ok"] and r["act"] == "campaign_pace" and written[-1] == ["roadmap-set", "--step", "mba", "--pace", "2026-10-10"]
    r = say.say_campaign(d, "the trusts by Oct 8.", today=TODAY)
    assert r and r["ok"] and written[-1][2] == "trusts"
    n = len(written)
    assert say.say_campaign(d, "teaching by Monday", today=TODAY) is None, "an interior word names nothing"
    assert say.say_campaign(d, "review the draft by tuesday", today=TODAY) is None, "no goal named: the steward takes the words"
    assert say.say_campaign(d, "MBA by the end of the world", today=TODAY) is None, "not a date: the steward takes the words"
    assert len(written) == n, "nothing written for any of them"
    monkeypatch.setattr(say, "compile_utterance", lambda text, dialogue=None: {"ok": True, "campaign": True, "act": "campaign_pace", "args": {"initiative": "nothing here", "pace": "tuesday"}})
    r = say.say_campaign(d, "set the pace of nothing here to tuesday", today=TODAY)
    assert r and not r["ok"], "an explicit pace verb that names no goal is refused with the names"


def test_the_page_leads_with_the_pick_up_while_active_runs():
    """The High Seat's lead is rendered by the page from the head itself; with no head and a pick-up, the pick-up leads
    and its button opens the picked project."""
    import os as _os, sys as _s; _s.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    import test_high_seat_page_2026_09_26 as t
    ctx = t._ctx(); ctx["head"] = None
    ctx["pickup"] = {"initiative": "Holding Company", "goal": "The trusts and the holding company", "id": "hc", "why": "on deck", "text": "", "pid": "p-hc",
                     "active": ["MBA Teaching AI"], "running": ["MBA Teaching AI"], "waiting": []}
    html = hsp.render_high_seat_html(ctx)
    # his word 2026-10-03: the brief is gone from the Cave and the Star Chart: the head's sentence no longer leads a brief on the page
    assert 'class="lead"' not in html and 'id="brief"' not in html
