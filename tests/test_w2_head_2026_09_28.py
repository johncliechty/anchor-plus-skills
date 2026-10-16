"""W2 of the steward revision (2026-09-28): his tiers order the day; the head is ONE act; the urgent lower-tier
exception (his Q3); the age of a wait from the record; the page-open boundary and "since you last opened"."""
import importlib
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import high_seat_page as hsp  # noqa: E402
import home_attention as ha  # noqa: E402
import home_rows as hr  # noqa: E402

TODAY = date(2026, 9, 28)


def _init(name, tier, order, parts):
    return {"id": name.lower(), "name": name, "tier": tier, "order": order, "done_when": "the %s outcome" % name,
            "parts": parts, "needs": [p for p in parts if p.get("needs_you")]}


def _part(text, **kw):
    p = {"id": text.lower(), "kind": "step", "text": text, "target": "MBA Teaching AI", "pid": "p1", "href": "/project/p1",
         "state": "", "date": "", "status": "planned", "target_status": "planned", "broken": False, "needs_you": False}
    p.update(kw)
    return p


def test_the_head_is_the_first_tier_one_part_that_needs_him_in_his_order():
    inits = [
        _init("Trusts", 1, 0, [_part("Sign the letter"), _part("Valuations", needs_you=True, state="waiting on you")]),
        _init("MBA", 1, 1, [_part("Supplement 4", needs_you=True, state="waiting on you")]),
        _init("Magi", 2, 0, [_part("Chapter 2", needs_you=True, state="waiting on you")]),
    ]
    act = ha.head_act(inits, [], today=TODAY)
    assert act["kind"] == "tier1" and act["initiative"] == "Trusts" and act["text"] == "Valuations"
    s = ha.head_sentence(act)
    assert s.startswith("Tier 1 · Trusts: Valuations (MBA Teaching AI) — waiting on you")
    # a done target is never the pick even when its wrapper is flagged
    inits[0]["parts"][1]["target_status"] = "done"
    assert ha.head_act(inits, [], today=TODAY)["initiative"] == "MBA"


def test_a_lower_tier_part_that_needs_him_and_is_due_leads_as_the_marked_exception():
    inits = [
        _init("Trusts", 1, 0, [_part("Valuations", needs_you=True, state="waiting on you")]),
        _init("Magi", 3, 0, [_part("Send the chapter", date="2026-09-28", needs_you=True, state="waiting on you"), _part("Later", date="2026-10-20")]),
    ]
    act = ha.head_act(inits, [], today=TODAY)
    assert act["kind"] == "exception" and act["text"] == "Send the chapter" and act["due"] == "2026-09-28" and act["overdue"] is False
    s = ha.head_sentence(act)
    assert s == "Exception, due today: Send the chapter (Magi, tier 3). Then: Later.", s
    # overdue reads as overdue
    inits[1]["parts"][0]["date"] = "2026-09-20"
    assert ha.head_sentence(ha.head_act(inits, [], today=TODAY)).startswith("Exception, overdue since Sep 20: Send the chapter (Magi, tier 3).")
    # a Tier-1 part due today that does NOT need him suppresses nothing
    inits[0]["parts"][0]["date"] = "2026-09-28"; inits[0]["parts"][0]["needs_you"] = False; inits[0]["needs"] = []
    assert ha.head_act(inits, [], today=TODAY)["kind"] == "exception"
    # a Tier-1 part that needs him AND is due today is the head
    inits[0]["parts"][0]["needs_you"] = True; inits[0]["needs"] = [inits[0]["parts"][0]]
    assert ha.head_act(inits, [], today=TODAY)["kind"] == "tier1"
    # a lower-tier part due today that does not need him is no exception; an untiered initiative never is
    inits[0]["parts"][0]["date"] = ""
    inits[1]["parts"][0]["needs_you"] = False; inits[1]["needs"] = []
    assert ha.head_act(inits, [], today=TODAY)["kind"] == "tier1"
    inits.append(_init("Loose", None, 0, [_part("Overdue thing", date="2026-01-01", needs_you=True, state="waiting on you")]))
    inits[0]["parts"][0]["needs_you"] = False; inits[0]["needs"] = []
    assert ha.head_act(inits, [], today=TODAY) is None, "an untiered initiative's part is never the exception"
    # among several exceptions: the earliest date, then his tier and order
    inits = [_init("B", 3, 0, [_part("b-part", date="2026-09-20", needs_you=True)]), _init("A", 2, 0, [_part("a-part", date="2026-09-27", needs_you=True)]),
             _init("C", 2, 1, [_part("c-part", date="2026-09-20", needs_you=True)])]
    assert ha.head_act(inits, [], today=TODAY)["text"] == "c-part", "earliest date, then tier 2 before tier 3"


def test_with_no_tier_one_need_the_oldest_wait_leads_with_its_age_and_effort_and_nothing_is_a_list():
    facts = [{"id": "a", "name": "Bread", "href": "/project/a", "needs_you": "approve the loaf", "wait_age_days": 2, "effort": ""},
             {"id": "b", "name": "DARPA", "href": "/project/b", "needs_you": "sign the form", "wait_age_days": 9, "needs_you_effort": "phase2", "next": "file it"}]
    act = ha.head_act([], facts, today=TODAY)
    assert act["kind"] == "oldest-wait" and act["pid"] == "b" and act["dir"] == "phase2"
    assert ha.head_sentence(act) == "DARPA · phase2: sign the form · waiting 9 days. Then: file it."
    assert ha.head_act([], [], today=TODAY) is None
    assert ha.head_sentence(None) == "Nothing is waiting on you."
    assert ha.head_sentence(None, overnight=[{"name": "Draft 5"}, {"name": "Outline v7"}]) == \
        "Nothing is waiting on you. Since you last opened: 2 steps closed — Draft 5, Outline v7."


def test_the_panel_leads_with_the_head_rendered_from_it_and_folds_only_the_week(tmp_path):
    head = {"kind": "exception", "tier": 3, "initiative": "Magi", "text": "Send the chapter", "target": "", "pid": "p1",
            "href": "", "date": "2026-09-28", "due": "2026-09-28", "overdue": False, "then": "", "age_days": None, "effort": "", "dir": None}
    ctx = {"steward": {"label": "Ecgberht", "high_seat_name": "High Seat"}, "brief_when": "10:00", "rows": [], "facts": {},
           "bullets": ["(an old lead that must not render)", "2 wait on you: A, B.", "This week: nothing.", "You can act from here."],
           "head": head, "overnight": [], "seed_rows": [], "seeds": 0, "campaign": None, "initiatives": [],
           "live": [], "counts": {"open": 0, "running": 0, "need_you": 0, "folders": 0}, "capacity": [], "today": TODAY}
    html = hsp._head_li(ctx)
    assert html.startswith('<li class="lead exc">Exception, due today: Send the chapter (Magi, tier 3).')
    assert 'class="h-open" data-part="status" data-pid="p1">' in html, "no data-dir: the card's own effort"
    assert '<details class="brief-more"><summary>this week</summary><ul><li>This week: nothing.</li></ul></details>' in html
    assert "2 wait on you" not in html and "You can act" not in html and "old lead" not in html
    head["kind"] = "oldest-wait"; head["dir"] = "phase2"; head["target"] = "DARPA"; head["effort"] = "phase2"
    assert 'data-pid="p1" data-dir="phase2">' in hsp._head_li(ctx), "only an act that names its effort carries one"


def test_the_wait_age_comes_from_the_record_never_the_strips_last_touch(tmp_path):
    d = tmp_path / "p"
    d.mkdir()
    strip = {"human_wait": "approve Draft 5", "instruments": [
        {"as_of": "2026-09-20", "human_wait": "approve Draft 4"},
        {"as_of": "2026-09-24", "human_wait": "approve Draft 5"},
        {"as_of": "2026-09-27", "human_wait": "approve Draft 5"}]}
    (d / "strip.json").write_text(json.dumps(strip), encoding="utf-8")
    f = hr.project_facts({"id": "p", "name": "P", "folder_path": str(d)}, TODAY)
    assert f["wait_age_days"] == 4, "since the earliest instrument of the current wait's run, not the last"
    strip2 = {"human_wait": "approve Draft 5", "instruments": []}
    (d / "strip.json").write_text(json.dumps(strip2), encoding="utf-8")
    (d / ".ecgberht").mkdir()
    (d / ".ecgberht" / "status-summary.json").write_text(json.dumps({"at": "2026-09-28T10:00", "plan": {"waiting_on_you": "approve Draft 5", "waiting_since": "2026-09-26T09:00"}}), encoding="utf-8")
    assert hr.project_facts({"id": "p", "name": "P", "folder_path": str(d)}, TODAY)["wait_age_days"] == 2, "the composer's waiting_since, not the summary's own time"
    (d / ".ecgberht" / "status-summary.json").write_text(json.dumps({"at": "2026-09-26T09:00", "plan": {"waiting_on_you": "approve Draft 5"}}), encoding="utf-8")
    assert hr.project_facts({"id": "p", "name": "P", "folder_path": str(d)}, TODAY)["wait_age_days"] is None, "no number without a reader: the summary's at is a ten-minute clock"
    html = hsp._card({"id": "p", "name": "P"}, dict(f, wait_age_days=4), "")
    assert "&middot; 4 days" in html


def test_closed_recent_carries_each_closures_instant_one_per_step(tmp_path):
    d = tmp_path / "p"
    d.mkdir()
    (d / "strip.json").write_text(json.dumps({"human_wait": "none"}), encoding="utf-8")
    (d / "roadmap.json").write_text(json.dumps({"roadmap_projection": [{"id": "s1", "name": "Draft 5", "status": "done"}, {"id": "s2", "name": "Old", "status": "done"}],
        "roadmap_events": [{"kind": "status_flip", "step_id": "s1", "to": "done", "at": "2026-09-27T15:04:00Z", "receipt": {"who": "john", "when": "2026-09-27"}},
                           {"kind": "status_flip", "step_id": "s2", "to": "done", "receipt": {"who": "john", "when": "2026-09-01"}},
                           {"kind": "status_flip", "step_id": "s1", "to": "parked", "receipt": {"who": "john", "when": "2026-09-27"}},
                           {"kind": "status_flip", "step_id": "s1", "to": "done", "at": "2026-09-28T09:30:00Z", "receipt": {"who": "john", "when": "2026-09-28"}}]}), encoding="utf-8")
    f = hr.project_facts({"id": "p", "name": "P", "folder_path": str(d)}, TODAY)
    assert [x["name"] for x in f["closed_recent"]] == ["Old", "Draft 5"], "sorted by instant; the latest flip per step"
    assert f["closed_recent"][1]["at"] == hr._instant("2026-09-28T09:30:00Z")
    assert f["closed_recent"][0]["at"] == hr._instant("2026-09-01"), "a date-only receipt is that day's midnight"
    # the gate the page applies: only closures after the real instant of his previous open
    prev_open = hr._instant("2026-09-28T09:00:00Z")
    assert [x["name"] for x in f["closed_recent"] if x["at"] > prev_open] == ["Draft 5"]
    assert [x["name"] for x in f["closed_recent"] if x["at"] > hr._instant("2026-09-28T09:31:00Z")] == [], "a second open repeats nothing"


def test_every_efforts_wait_carries_its_own_age_and_a_promoted_wait_keeps_it(tmp_path):
    root = tmp_path / "mba"
    root.mkdir()
    (root / "ECGBERHT.md").write_text("# E\n\n## North star\n\n> x\n", encoding="utf-8")
    (root / "strip.json").write_text(json.dumps({"human_wait": "none"}), encoding="utf-8")
    (root / "peter").mkdir()
    (root / "peter" / "ECGBERHT.md").write_text("# E\n\n## North star\n\n> x\n", encoding="utf-8")
    (root / "peter" / "strip.json").write_text(json.dumps({"human_wait": "review Draft 4", "instruments": [
        {"as_of": "2026-09-22", "human_wait": "review Draft 4"}, {"as_of": "2026-09-27", "human_wait": "review Draft 4"}]}), encoding="utf-8")
    import os as _os, time as _time
    now = _time.time()
    _os.utime(root / "strip.json", (now + 100, now + 100))
    f = hr.project_facts({"id": "p", "name": "MBA", "folder_path": str(root)}, TODAY)
    assert f["effort"] == "" and f["needs_you_effort"] == "peter"
    assert f["other_waits"][0]["age_days"] == 6 and f["wait_age_days"] == 6, "the promoted wait's own age"
    html = hsp._card({"id": "p", "name": "MBA"}, f, "")
    assert "&middot; 6 days" in html


def test_the_page_open_boundary_returns_the_previous_open(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    import paths
    importlib.reload(paths)
    from steward_cockpit import presence
    importlib.reload(presence)
    assert presence.note_page_open(now=100.0) is None
    assert presence.note_page_open(now=200.0) == 100.0
    presence.note_open("mba", now=250.0)
    assert presence.read_presence()["high_seat_at"] == 200.0, "a project open keeps the page-open time"
