"""W1 of the steward revision (2026-09-28): complete facts — every effort's wait reaches the card; a referenced
part's open/next reads the RESOLVED target; ONE next-in-the-plan rule for the card, the cockpit and the status."""
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import high_seat_page as hsp  # noqa: E402
import home_rows as hr  # noqa: E402
from steward_cockpit import high_seat_card as card  # noqa: E402
from steward_cockpit import steward_campaign as campaign  # noqa: E402

PID = "6765ece4b3bc43b0b0b0907b92b17280"


def _record(d, wait, steps, current=None):
    d.mkdir(parents=True, exist_ok=True)
    (d / "ECGBERHT.md").write_text("# Ecgberht\n\n## North star\n\n> x\n\n## Active effort\n\nx\n", encoding="utf-8")
    strip = {"human_wait": wait, "next_recommended": "next", "why_next": "why"}
    if current:
        strip["current_step_id"] = current
    (d / "strip.json").write_text(json.dumps(strip), encoding="utf-8")
    (d / "roadmap.json").write_text(json.dumps({"schema": "x", "roadmap_events": [], "roadmap_projection": list(steps)}), encoding="utf-8")


def test_every_efforts_wait_reaches_the_card_and_opens_its_own_record(tmp_path):
    root = tmp_path / "mba"
    _record(root, "none", [{"id": "s1", "name": "Lecture 4", "status": "active"}])
    _record(root / "peter", "review Draft 4 of Supplement 3", [{"id": "d4", "name": "Draft 4", "status": "waiting"}])
    now = time.time()
    os.utime(root / "strip.json", (now + 100, now + 100))          # the root is the effort touched last
    os.utime(root / "peter" / "strip.json", (now, now))
    f = hr.project_facts({"id": PID, "name": "MBA Teaching AI", "folder_path": str(root)})
    assert f["effort"] == "", "the shown effort is the root (touched last)"
    assert [e["rel"] for e in f["efforts"]] == ["", "peter"]
    assert f["other_waits"][0]["needs_you"] == "review Draft 4 of Supplement 3"
    assert f["needs_you"] == "peter: review Draft 4 of Supplement 3", "the second effort's wait puts the project on Needs you"
    assert f["needs_you_effort"] == "peter"
    html = hsp._card({"id": PID, "name": "MBA Teaching AI"}, f, "")
    assert "review Draft 4 of Supplement 3" in html
    assert 'data-part="status" data-pid="%s" data-dir="peter"' % PID in html, "the wait opens ITS effort's record"


def test_a_shown_efforts_wait_is_not_repeated_as_an_other_wait(tmp_path):
    root = tmp_path / "mba"
    _record(root, "approve the outline", [{"id": "s1", "name": "Lecture 4", "status": "active"}])
    f = hr.project_facts({"id": PID, "name": "MBA Teaching AI", "folder_path": str(root)})
    assert f["needs_you"] == "approve the outline" and f["other_waits"] == []
    assert hsp._card({"id": PID, "name": "MBA Teaching AI"}, f, "").count("&#9873;") == 1


def test_a_done_target_is_never_the_next_part_and_counts_as_done():
    steps = [
        {"id": "mba", "name": "MBA Teaching", "status": "active", "tier": 1,
         "navigation": {"path": ["mba"], "groups": [{"id": "mba", "label": "MBA", "order": 0, "parent_id": None}]}},
        {"id": "p1", "name": "Supplement 3", "status": "planned", "ref": "step:%s/supp-3" % PID, "navigation": {"path": ["mba"]}},
        {"id": "p2", "name": "Supplement 4", "status": "planned", "ref": "step:%s/supp-4" % PID, "navigation": {"path": ["mba"]}},
        {"id": "p3", "name": "Supplement 5", "status": "planned", "ref": "step:%s/supp-5" % PID, "navigation": {"path": ["mba"]}},
    ]
    resolved = {
        "p1": {"kind": "step", "pid": PID, "name": "MBA Teaching AI", "what": "Supplement 3", "state": "done", "target_status": "done", "href": "/project/" + PID, "broken": False},
        "p2": {"kind": "step", "pid": PID, "name": "MBA Teaching AI", "what": "Supplement 4", "state": "parked · after 5", "target_status": "parked", "href": "/project/" + PID, "broken": False},
        "p3": {"kind": "step", "pid": PID, "name": "MBA Teaching AI", "what": "Supplement 5", "state": "active", "target_status": "active", "href": "/project/" + PID, "broken": False},
    }
    inits = hsp.campaign_initiatives(steps, resolved)
    i = inits[0]
    assert i["next"]["id"] == "p3", "the done and the parked targets are closed although their wrappers say planned"
    assert i["done_count"] == 1
    # every reader of a part reads the flags, not the wrapper's status (Grok W1): the light, the row, the board
    import campaign_page as cp
    p1, p2, p3 = i["parts"]
    assert p1["done"] and p1["closed"] and p2["closed"] and not p2["done"] and not p3["closed"]
    assert cp._part_state(p1) == "done" and cp._part_state(p2) == "parked"
    assert hsp.initiative_light(dict(i, parts=[p1, p2])) == "idle", "a done and a parked target leave nothing open"
    # an unavailable target is broken: named, never next
    resolved["p3"] = {"kind": "step", "name": "MBA Teaching AI", "what": "", "state": "", "target_status": "", "href": "", "broken": True, "gap": "no step"}
    assert hsp.campaign_initiatives(steps, resolved)[0]["next"] is None


def test_next_in_plan_follows_the_focus_skips_parked_and_says_why_without_a_focus():
    steps = [{"id": "a", "name": "A", "status": "done"}, {"id": "b", "name": "B", "status": "active"},
             {"id": "c", "name": "C", "status": "parked"}, {"id": "d", "name": "D", "status": "planned"},
             {"id": "e", "name": "E", "status": "planned"}, {"id": "f", "name": "F", "status": "planned"}]
    plan, why = campaign.next_in_plan({"steps": steps, "heartbeat": {"current_step_id": "b"}}, 3)
    assert [s["id"] for s in plan] == ["b", "d", "e"] and why == ""
    plan, why = campaign.next_in_plan({"steps": steps, "heartbeat": {"current_step_id": "d"}}, 3)
    assert [s["id"] for s in plan] == ["d", "e", "f"], "the focus, not the first active, starts the horizon"
    plan, why = campaign.next_in_plan({"steps": steps, "heartbeat": {}}, 3)
    assert [s["id"] for s in plan] == ["b", "d", "e"], "one active step is the focus"
    two = [dict(s, status="active") if s["id"] in ("b", "d") else s for s in steps]
    plan, why = campaign.next_in_plan({"steps": two, "heartbeat": {}}, 3)
    assert plan == [] and "2 steps are active" in why, "never a guess among several"
    plan, why = campaign.next_in_plan({"steps": steps, "heartbeat": {"current_step_id": "zz"}}, 3)
    assert plan == [] and "does not match" in why


def test_the_cards_next_in_the_plan_reads_the_one_rule(tmp_path):
    d = tmp_path / "mba"
    _record(d, "approve the Lecture 3 AI supplement", [
        {"id": "syl", "name": "Syllabus", "status": "done"},
        {"id": "lec3", "name": "Lecture 3 AI supplement", "status": "waiting", "waiting_on": "your read"},
        {"id": "lec4", "name": "Lecture 4 AI supplement", "status": "planned"},
        {"id": "lec5", "name": "Lecture 5 AI supplement", "status": "parked"},
        {"id": "lec6", "name": "Lecture 6 AI supplement", "status": "planned"},
    ], current="lec4")
    html = card.next_html(str(d), PID)
    block = re.search(r'<div class="cp-plan">.*?</div></div>', html, re.S)
    assert block, html
    names = re.findall(r'<div class="cp-step">([^<]*)', block.group(0))
    assert names[0].startswith("Lecture 4") and names[1].startswith("Lecture 6") and len(names) == 2, names
    assert "Lecture 3" not in block.group(0) and "Lecture 5" not in block.group(0), "before the focus and parked: not in the horizon"
    # the cockpit renders the SAME list from the map (one horizon, computed once — Grok W1)
    m = campaign.read_map(str(d))
    assert [s["id"] for s in m["next_in_plan"]] == ["lec4", "lec6"]
    # no focus and several actives: an empty horizon on his surfaces — never a guess, never the steward's reason
    _record(d, "approve", [{"id": "a", "name": "A", "status": "active"}, {"id": "b", "name": "B", "status": "active"}])
    html = card.next_html(str(d), PID)
    assert 'class="cp-step">' not in html and "cp-plan" not in html and "must pin" not in html
    assert campaign.read_map(str(d))["next_in_plan"] == []


def test_the_cockpit_reads_the_maps_horizon_and_computes_none_of_its_own():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "steward_cockpit", "static", "shared.js"), encoding="utf-8").read()
    assert "_lastMap.next_in_plan" in src
    assert "function nextInPlan(" not in src, "one selector, on the server"
    assert 'open.findIndex(st => st.status === "active")' not in src, "the array-order guess is gone from the cockpit"
