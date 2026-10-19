"""campaign_page + campaign_acts + campaign_seeds — the Campaign page renders from the record; the acts write only the
Campaign's record through the engine (W3c, High Seat; trimmed by its Rabbit read). The acts run the real engine CLI
on a temp record that carries a strip with one seed."""
import json
import os
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import campaign_page as cpg  # noqa: E402
import high_seat_page as hsp  # noqa: E402
from steward_cockpit import campaign_acts as acts  # noqa: E402
from steward_cockpit import campaign_seeds as seeds_mod  # noqa: E402

TODAY = date(2026, 9, 26)
MBA = "6765ece4b3bc43b0b0b0907b92b17280"


def _steps():
    return [
        {"id": "mba-teaching", "name": "MBA Teaching, Fall 2026", "status": "proposed", "tier": 1, "area": "professional", "done_when": "HMBA lectures 3-4 taught Oct 10",
         "navigation": {"path": ["mba-teaching"], "groups": [{"id": "mba-teaching", "label": "MBA Teaching, Fall 2026", "order": 0, "parent_id": None}]}},
        {"id": "mba-project", "name": "MBA Teaching AI (the project)", "status": "proposed", "ref": "project:" + MBA, "navigation": {"path": ["mba-teaching"]}},
        {"id": "lectures-3-4", "name": "Lectures 3 + 4", "status": "proposed", "ref": "step:%s/lectures-3-4-revision" % MBA, "navigation": {"path": ["mba-teaching"]}},
        {"id": "hw", "name": "retool homework 2", "status": "planned", "due": "2026-10-27", "navigation": {"path": ["mba-teaching"]}},
        {"id": "syllabus", "name": "post the syllabus", "status": "done", "due": "2026-09-18", "navigation": {"path": ["mba-teaching"]}},
        {"id": "roster", "name": "check the roster", "status": "waiting", "waiting_on": "John", "due": "2026-09-19", "navigation": {"path": ["mba-teaching"]}},
        {"id": "trusts", "name": "The trusts", "status": "proposed", "tier": 2, "area": "family",
         "navigation": {"path": ["trusts"], "groups": [{"id": "trusts", "label": "The trusts", "order": 0, "parent_id": None}]}},
        {"id": "trust-call", "name": "call the trustee", "status": "parked", "waiting_on": "January", "due": "2026-10-02", "navigation": {"path": ["trusts"]}},
    ]


def _resolved():
    return {
        "mba-project": {"kind": "project", "name": "MBA Teaching AI", "what": "", "state": "waiting on you: approve the supplement", "date": "2026-10-10", "href": "/project/" + MBA, "broken": False, "gap": ""},
        "lectures-3-4": {"kind": "step", "name": "MBA Teaching AI", "what": "Lectures 3 + 4 revised, with AI supplements", "state": "waiting", "date": "2026-10-10", "href": "/project/" + MBA, "broken": False, "gap": ""},
    }


def _ctx():
    return {"pid": "df56", "name": "Campaign", "today": TODAY, "today_str": "Saturday, September 26, 2026", "brief_when": "19:00 · Saturday 26 September",
            "build": "test", "steward": {"key": "jarvis", "label": "Jarvis", "high_seat": "jarvis-high-seat-hat.jpg", "seal": "jarvis-seal-salver.jpg", "high_seat_name": "Tip of the Hat", "seal_name": "Server", "campaign_name": "Chart Room", "campaign_icon": "campaign-jarvis-chart-room.jpg"},
            "prefs_html": "<span id='prefs-here'></span>", "initiatives": hsp.campaign_initiatives(_steps(), _resolved()),
            "seeds": [{"id": "s3", "text": "An AI mechanics class with the group", "at": "2026-09-26"}], "turns": [{"you": True, "text": "what does the Campaign say?", "at": "18:50"}, {"you": False, "text": "Tier 1 holds the teaching.", "at": "18:51"}],
            "projects": [{"id": MBA, "name": "MBA Teaching AI"}], "tick_allowed": False}


def test_the_page_renders_tiers_parts_seeds_calendar_and_brief_from_the_record():
    html = cpg.render_campaign_html(_ctx())
    assert "<title>Chart Room</title>" in html and hsp.tab_icon_link(_ctx()["steward"].get("high_seat") or _ctx()["steward"].get("seal"), "test", anchor=False) in html   # the tab: the High Seat's picture (his rule, 2026-10-01)
    assert "campaign-page.css" in html and "campaign-page.js" in html and 'class="mh-stew"' in html
    # the goal board (W2 v2 of the active set, 2026-09-29): bands Active then the tiers, Tier 1 first; each goal a
    # compact tile — its light and one line — and its place (the area and tier, the Status, the parts) rendered apart
    board = html[html.index('<div class="bands"'):html.index('id="viewCal"')]
    t1, t2 = board.index("Tier 1 <span"), board.index("Tier 2 <span")
    assert t1 < t2 and board.index('data-lane="mba-teaching"') < t2 < board.index('data-lane="trusts"')
    tile = board[board.index('data-lane="mba-teaching"'):board.index('data-lane="trusts"')]
    assert '<span class="ilight needs"' in tile and 'class="gpc needs"' in tile and "MBA Teaching AI" in tile    # the face: its cockpit with its light
    place = html[html.index('id="place-mba-teaching"'):html.index('id="place-trusts"')]
    assert place.index('class="imore"') < place.index('class="istatus"') < place.index('class="obody"')
    assert "2 goals &middot; Tier 1 1 &middot; Tier 2 1 &middot; seed goals 0 &middot; the boneyard 0" in html
    assert 'data-lane="mba-teaching"' in html and 'data-lane="trusts"' in html and "goal" in html
    assert "retool homework 2" in html and "Oct 27" in html and "Lectures 3 + 4 revised, with AI supplements" in html
    assert 'data-act="date" data-part="hw"' in html                      # a native part's date can be moved here
    assert 'its date lives in its own record' in html                    # a referenced part's cannot
    assert 'disabled title="a tick waits on your word' in html           # the tick waits on his word
    assert 'class="tickpad" href="/project/%s"' % MBA in html            # a referenced part's tick opens its cockpit
    assert 'data-act="pup"' not in html and 'data-act="pdown"' not in html
    assert "An AI mechanics class with the group" in html and 'data-act="promote" data-seed="s3"' in html
    assert '<section class="seedband" id="seedband"' in html and 'id="seedToggle"' in html and "<b>1</b> idea, not yet goals" in html   # the seeds a closed tile with its count
    assert 'data-pickgo="s3"' in html and "Create it in tier 3" in html and 'data-pickarea="family"' in html
    assert 'id="viewCal"' in html and "beyond the ruler" in html and 'class="tierstrip"' in html
    # the brief is gone (2026-10-03): the look-ahead takes its place, read from the record
    assert 'id="brief"' not in html and 'id="lookAhead"' in html and "<b>One preparation:</b> the nearest date is" in html
    assert 'class="cview-frame"' in html and "Sample data" not in html   # the conversation: the cockpit's own view (2026-10-02)
    assert "<span id='prefs-here'></span>" in html                       # the model-prefs row stays (version D carries it)


def test_a_flagged_native_part_reads_as_needs_you_and_the_counts_say_so():
    html = cpg.render_campaign_html(_ctx())
    inits = {i["id"]: i for i in hsp.campaign_initiatives(_steps(), _resolved())}
    roster = next(p for p in inits["mba-teaching"]["parts"] if p["id"] == "roster")
    assert roster["needs_you"] is True and len(inits["mba-teaching"]["needs"]) == 2
    assert 'data-act="unflag" data-part="roster"' in html                # the row offers to clear the flag
    assert "&#9873; 1 goal needs you" in html and "&#9873; 2 parts need you" in html   # the noun said (Grok R8); a goal, his word (W2 v2)
    assert "1 of 5 parts done" in html and "overdue Sep 19" in html         # done over named; a past next date is overdue


def test_the_calendar_puts_past_dates_before_this_week_and_parked_parts_off_the_ruler():
    html = cpg.render_campaign_html(_ctx())
    cal = html[html.index('id="viewCal"'):]
    assert 'class="scroll has-over"' in html and "<b>Before this week</b>" in cal and "1 overdue" in cal
    over = cal[cal.index('class="cell over"'):]
    assert "check the roster" in over[:600] and "post the syllabus" in over[:1200]   # the open one and the done one, both past
    assert "0 undated &middot; 1 parked" in cal                              # the parked part sits off the ruler
    lane = cal[cal.index('data-lane="trusts"'):]
    first_cell = lane[lane.index('class="cell"'):lane.index('class="cell over"')]   # the trusts lane's No-date cell
    assert "call the trustee" in first_cell and "parked" in first_cell


def test_an_untiered_initiative_gets_its_own_column_and_strip_and_no_number_in_the_tiers():
    steps = _steps()
    steps[6].pop("tier")
    ctx = _ctx(); ctx["initiatives"] = hsp.campaign_initiatives(steps, _resolved())
    html = cpg.render_campaign_html(ctx)
    assert "2 goals &middot; Tier 1 1 &middot; Tier 2 0 &middot; seed goals 1" in html, "an untiered goal is a seed goal on the board (PLAN v1.3)"
    board = html[html.index('<div class="bands"'):html.index('id="viewCal"')]
    assert 'data-lane="trusts" data-band="3"' in board and "No tier yet" not in board
    cal = html[html.index('id="viewCal"'):]
    assert 'class="tn">Seed goals</span>' in cal and 'data-lane="trusts"' in cal and "No tier yet" not in cal


# ── the seed reader ─────────────────────────────────────────────────────────────────────────────

def test_seeds_are_read_by_id_and_spent_or_restored_by_a_later_receipt(tmp_path):
    def g(deferred, why):
        return {"kind": "grasscatch", "deferred": deferred, "grasscatch_why": why, "as_of": "2026-09-26"}
    (tmp_path / "strip.json").write_text(json.dumps({"receipts": [
        {"kind": "heartbeat"}, g("An AI mechanics class", "seed: an idea"), g("An AI mechanics class", "seed: the same words twice"),
        g("A memorization tool", "seed: another"), g("An AI mechanics class", "promoted seed s1 → the initiative an-ai-mechanics-class"),
        g("A memorization tool", "promoted seed s3 → x"), g("A memorization tool", "restored seed s3 — undone"),
        g("not a seed", "parked for later"),
    ]}), encoding="utf-8")
    got = seeds_mod.read_seeds(tmp_path)
    assert [s["id"] for s in got] == ["s2", "s3"]                        # s1 spent; its twin s2 stands; s3 restored
    assert seeds_mod.seed_by_id(tmp_path, "s1") is None and seeds_mod.seed_by_id(tmp_path, "s3")["text"] == "A memorization tool"
    assert seeds_mod.read_seeds(tmp_path / "nowhere") == []


# ── the acts, on a temp record through the real engine ────────────────────────────────────────

ECG = Path(r"C:\dev\Ecgberht\bin\ecgberht.mjs")
STRIP = {"schema": "ecgberht-strip-v0", "project_id": "campaign-test", "face_path": "ECGBERHT.md", "as_of": "2026-09-26", "phase": "planning",
         "active_effort": "the Campaign", "effort_status": "IN_PROGRESS", "tool_depth_cell": "LITE", "human_wait": "none", "capacity": "unknown",
         "negative_heartbeat": {"no_attention_needed": False, "why": None, "until": None}, "anti_starvation_age_days": 0, "grasscatch": [],
         "next_recommended": "run the Campaign", "why_next": "it is the coordinating record", "uncertainty_flags": [], "instruments": [], "receipts": []}


@pytest.fixture
def record(tmp_path):
    if not ECG.is_file() or shutil.which("node") is None:
        pytest.skip("the engine CLI is not on this machine")
    d = tmp_path / "Campaign"
    d.mkdir()
    (d / "ECGBERHT.md").write_text("# Ecgberht\n\n## North star\n\n> the Campaign.\n", encoding="utf-8")
    (d / "strip.json").write_text(json.dumps(STRIP, indent=1), encoding="utf-8")

    def cli(*args):
        r = subprocess.run(["node", str(ECG), *args, "--project", str(d)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        return json.loads(r.stdout)
    for sid, name, tier, area, order in (("a", "Initiative A", 1, "family", 0), ("b", "Initiative B", 1, "writing", 1), ("c", "Initiative C", 2, "tools", 0)):
        assert cli("roadmap-propose", "--step", sid, "--name", name, "--tier", str(tier), "--area", area)["ok"]
        assert acts._spine_set(d, sid, {"navigation": {"path": [sid], "groups": [{"id": sid, "label": name, "order": order, "parent_id": None}], "role": "primary"}})["ok"]
    assert cli("roadmap-propose", "--step", "a-part", "--name", "a native part")["ok"]
    assert acts._spine_set(d, "a-part", {"navigation": {"path": ["a"]}})["ok"]
    assert cli("roadmap-propose", "--step", "a-ref", "--name", "a referenced part", "--ref", "project:%s" % MBA)["ok"]
    assert acts._spine_set(d, "a-ref", {"navigation": {"path": ["a"]}})["ok"]
    assert cli("grasscatch", "--deferred", "An AI mechanics class", "--reason", "seed: an idea that could start a project")["ok"]
    return d


def _order(d, sid):
    return acts._own_group(acts._step(d, sid))["order"]


def _events(d):
    return len(json.loads((d / "roadmap.json").read_text(encoding="utf-8"))["roadmap_events"])


def test_move_tier_undo_restores_the_head_of_its_tier_and_each_way_is_two_events(record):
    n0 = _events(record)
    r = acts.act(record, {"act": "move_tier", "step": "a", "tier": 2})            # a is the head of tier 1
    assert r["ok"] and "moved to tier 2" in r["receipt"] and "at its foot" in r["receipt"]
    assert acts._step(record, "a")["tier"] == 2 and _order(record, "a") == 1     # after c
    assert r["undo"] == {"act": "move_tier", "step": "a", "tier": 1, "order": 0}
    assert _events(record) == n0 + 2                                              # the tier, then its place
    back = acts.act(record, r["undo"])
    assert back["ok"] and "back in its place" in back["receipt"]
    assert acts._step(record, "a")["tier"] == 1 and _order(record, "a") == 0 and _order(record, "b") == 1   # the head again, not the foot
    assert acts.act(record, {"act": "move_tier", "step": "a", "tier": 7})["ok"] is False


def test_rank_renumbers_a_collided_tier_then_swaps_and_refuses_at_the_edge(record):
    assert acts._write_nav(record, acts._step(record, "b"), order=0)["ok"]        # a and b both at order 0
    r = acts.act(record, {"act": "rank", "step": "b", "direction": "up"})
    assert r["ok"] and "moved up within tier 1" in r["receipt"]
    assert _order(record, "b") == 0 and _order(record, "a") == 1                  # distinct, b first
    top = acts.act(record, {"act": "rank", "step": "b", "direction": "up"})
    assert top["ok"] is False and "already at the top" in top["receipt"]
    down = acts.act(record, r["undo"])
    assert down["ok"] and _order(record, "a") == 0 and _order(record, "b") == 1


def test_native_parts_take_names_dates_parks_and_flags_and_referenced_parts_refuse(record):
    assert acts.act(record, {"act": "rename", "step": "a-part", "name": "a better name"})["ok"]
    assert acts._step(record, "a-part")["name"] == "a better name"
    d = acts.act(record, {"act": "date", "step": "a-part", "due": "2026-10-08"})
    assert d["ok"] and acts._step(record, "a-part")["due"] == "2026-10-08" and d["undo"]["due"] == "none"
    assert acts.act(record, {"act": "date", "step": "a-ref", "due": "2026-10-08"})["ok"] is False      # its date lives in its own record
    assert acts.act(record, {"act": "park", "step": "a-part", "waiting_on": ""})["ok"] is False        # a park carries its trigger
    p = acts.act(record, {"act": "park", "step": "a-part", "waiting_on": "January"})
    assert p["ok"] and acts._step(record, "a-part")["status"] == "parked" and acts._step(record, "a-part")["waiting_on"] == "January"
    assert acts.act(record, p["undo"])["ok"] and acts._step(record, "a-part")["status"] == "planned"
    f = acts.act(record, {"act": "flag", "step": "a-part"})
    assert f["ok"] and acts._step(record, "a-part")["status"] == "waiting" and acts._step(record, "a-part")["waiting_on"] == "John"
    flagged = {i["id"]: i for i in hsp.campaign_initiatives(acts._projection(record))}["a"]
    assert [p["id"] for p in flagged["needs"]] == ["a-part"]                                             # the page reads the flag as needs-you
    assert acts.act(record, {"act": "tick", "step": "a-part"})["ok"] is False                           # waits on his word
    assert acts.act(record, {"act": "park", "step": "a-ref", "waiting_on": "later"})["ok"] is False


def test_add_and_promote_place_new_steps_and_their_undo_takes_them_off_the_board(record):
    a = acts.act(record, {"act": "add", "initiative": "a", "kind": "task", "text": "Sign the engagement letter", "due": "2026-10-01"})
    assert a["ok"] and "added" in a["receipt"] and a["undo"] == {"act": "withdraw", "step": a["step"]}
    s = acts._step(record, a["step"])
    assert s["due"] == "2026-10-01" and s["navigation"]["path"] == ["a"]
    w = acts.act(record, a["undo"])
    assert w["ok"] and "off the board" in w["receipt"] and acts._step(record, a["step"]).get("navigation") is None
    assert a["step"] not in [p["id"] for p in {i["id"]: i for i in hsp.campaign_initiatives(acts._projection(record))}["a"]["parts"]]
    back = acts.act(record, w["undo"])
    assert back["ok"] and acts._step(record, a["step"])["navigation"]["path"] == ["a"]
    p = acts.act(record, {"act": "add", "initiative": "a", "kind": "project", "text": "", "project_id": "abc123"})
    assert p["ok"] and acts._step(record, p["step"])["ref"] == "project:abc123"
    dup = acts.act(record, {"act": "add", "initiative": "a", "kind": "project", "text": "again", "project_id": MBA})
    assert dup["ok"] is False and "duplicate_ref" in dup["receipt"]
    # the seed, by id
    seed = seeds_mod.read_seeds(record)
    assert [x["text"] for x in seed] == ["An AI mechanics class"]
    assert acts.act(record, {"act": "promote", "seed": "s99", "tier": "3", "area": "professional"})["ok"] is False
    pr = acts.act(record, {"act": "promote", "seed": seed[0]["id"], "tier": "3", "area": "professional"})
    assert pr["ok"] and "tier 3" in pr["receipt"] and "could not be spent" not in pr["receipt"]
    head = acts._step(record, pr["step"])
    assert head["tier"] == 3 and head["area"] == "professional" and acts._own_group(head) is not None
    assert seeds_mod.read_seeds(record) == []                                                          # spent, by id
    assert pr["undo"] == {"act": "withdraw", "step": pr["step"], "seed": seed[0]["id"]}
    u = acts.act(record, pr["undo"])
    assert u["ok"] and "seed is back" in u["receipt"]
    assert [x["id"] for x in seeds_mod.read_seeds(record)] == [seed[0]["id"]]                          # restored, the same id
    assert pr["step"] not in [i["id"] for i in hsp.campaign_initiatives(acts._projection(record))]    # off the board
    again = acts.act(record, u["undo"])
    assert again["ok"] and seeds_mod.read_seeds(record) == [] and pr["step"] in [i["id"] for i in hsp.campaign_initiatives(acts._projection(record))]
