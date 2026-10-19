"""campaign_say — a Campaign verb typed in a composer is compiled by the engine's act table, its names resolved on the
Campaign record, and applied by the Campaign's own writer with the same receipts and undo (W5, High Seat); anything
else is left to the steward. Runs the real engine on a temp record."""
import json
import os
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from steward_cockpit import campaign_acts as acts  # noqa: E402
from steward_cockpit import campaign_say as cs  # noqa: E402
from steward_cockpit import campaign_seeds as seeds_mod  # noqa: E402

TODAY = date(2026, 9, 26)
MBA = "6765ece4b3bc43b0b0b0907b92b17280"
ECG = Path(r"C:\dev\Ecgberht\bin\ecgberht.mjs")
# the engine worktree's table while W5 lands, else the live engine's
_WT = Path(r"C:\dev\Ecgberht-highseat-wt\engine\dialogue.mjs")
DIALOGUE = ("file:///" + str(_WT).replace("\\", "/")) if _WT.is_file() else None
STRIP = {"schema": "ecgberht-strip-v0", "project_id": "campaign-test", "face_path": "ECGBERHT.md", "as_of": "2026-09-26", "phase": "planning",
         "active_effort": "the Campaign", "effort_status": "IN_PROGRESS", "tool_depth_cell": "LITE", "human_wait": "none", "capacity": "unknown",
         "negative_heartbeat": {"no_attention_needed": False, "why": None, "until": None}, "anti_starvation_age_days": 0, "grasscatch": [],
         "next_recommended": "run the Campaign", "why_next": "it is the coordinating record", "uncertainty_flags": [], "instruments": [], "receipts": []}


def test_dates_are_read_the_way_the_desk_reads_them():
    p = lambda s: cs.parse_due(s, TODAY)
    assert p("2026-10-03") == "2026-10-03" and p("2026-02-30") is None and p("today") == "2026-09-26" and p("tomorrow") == "2026-09-27"
    assert p("tuesday") == "2026-09-29" and p("tues") == "2026-09-29" and p("Oct 3") == "2026-10-03" and p("3 Oct") == "2026-10-03" and p("October 27") == "2026-10-27"
    assert p("Sep 20") == "2026-09-20" and p("Feb 29") is None and p("nonsense") is None and p("") is None


def test_names_resolve_exactly_then_by_the_one_that_contains_the_words_else_refuse():
    cands = [("mba-teaching", "MBA Teaching, Fall 2026"), ("trusts", "The trusts"), ("trust-call", "call the trustee")]
    assert cs._find(cands, "the trusts", "initiative")[0][0] == "trusts"
    assert cs._find(cands, "MBA Teaching", "initiative")[0][0] == "mba-teaching"
    assert cs._find(cands, "trustee", "part")[0][0] == "trust-call" and cs._find(cands, "the trustee call", "part")[0][0] == "trust-call"
    hit, why = cs._find(cands, "trust", "part")
    assert hit is None and "could be" in why and "say which" in why
    assert cs._find(cands, "teaching", "initiative")[0][0] == "mba-teaching"                 # a whole word of one name selects
    hit, why = cs._find(cands, "teach", "initiative")
    assert hit is None and why.startswith("did you mean") and "MBA Teaching" in why          # a looser match names, never selects
    assert cs._find(cands, "call the trustee about the trusts", "part")[0] is None             # a name inside the phrase never selects
    hit, why = cs._find(cands, "the magi", "goal")
    assert hit is None and why.startswith("no goal named") and "MBA Teaching" in why


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
    for sid, name, tier, area, order in (("mba-teaching", "MBA Teaching, Fall 2026", 1, "professional", 0), ("trusts", "The trusts", 2, "family", 0)):
        assert cli("roadmap-propose", "--step", sid, "--name", name, "--tier", str(tier), "--area", area)["ok"]
        assert acts._spine_set(d, sid, {"navigation": {"path": [sid], "groups": [{"id": sid, "label": name, "order": order, "parent_id": None}], "role": "primary"}})["ok"]
    assert cli("roadmap-propose", "--step", "trust-call", "--name", "call the trustee")["ok"]
    assert acts._spine_set(d, "trust-call", {"navigation": {"path": ["trusts"]}})["ok"]
    assert cli("roadmap-propose", "--step", "mba-project", "--name", "MBA Teaching AI (the project)", "--ref", "project:%s" % MBA)["ok"]
    assert acts._spine_set(d, "mba-project", {"navigation": {"path": ["mba-teaching"]}})["ok"]
    assert cli("grasscatch", "--deferred", "An AI mechanics class with the group", "--reason", "seed: an idea that could start a project")["ok"]
    return d


def test_the_verbs_move_add_park_unpark_and_promote_through_the_campaign_writer(record):
    say = lambda t: cs.say_campaign(record, t, dialogue=DIALOGUE, today=TODAY)
    assert say("what a lovely evening it has been, thinking about the trusts") is None          # not a verb: the steward's
    assert say("carry on") is None                                                              # an older act, not the Campaign's
    r = say("move the trusts to tier 1")
    assert r["ok"] and r["campaign_act"] and r["act"] == "campaign_move_tier" and "moved to tier 1" in r["say"]
    assert acts._step(record, "trusts")["tier"] == 1 and r["undo"]["act"] == "move_tier"
    assert acts.act(record, r["undo"])["ok"]
    a = say("add a part to MBA Teaching: retool homework 2 due Oct 27")
    assert a["ok"] and a["act"] == "campaign_add_part" and "added" in a["say"] and acts._step(record, a["step"])["due"] == "2026-10-27"
    assert acts._step(record, a["step"])["navigation"]["path"] == ["mba-teaching"]
    bad = say("add a part to MBA Teaching: something by Feb 30")
    assert bad["ok"] is False and "could not read" in bad["say"]
    p = say("park the trustee call until January")
    assert p["ok"] and p["act"] == "campaign_park" and acts._step(record, "trust-call")["status"] == "parked" and acts._step(record, "trust-call")["waiting_on"] == "January"
    assert say("park the trustee call")["ok"] is False and "until" in say("park the trustee call")["say"]
    u = say("unpark the trustee call")
    assert u["ok"] and acts._step(record, "trust-call")["status"] == "planned"
    refused = say("park the MBA project until Monday")
    assert refused["ok"] is False and "own record" in refused["say"]                              # a referenced part is refused by the writer
    amb = say("move the teaching to tier 3")
    assert amb["ok"] and acts._step(record, "mba-teaching")["tier"] == 3                          # one initiative contains the words
    none = say("move the magi to tier 3")
    assert none["ok"] is False and none["say"].startswith("no goal named")
    n_before = len(json.loads((record / "roadmap.json").read_text(encoding="utf-8"))["roadmap_events"])
    loose = say("move teach to tier 1")                                                        # inside one name only: named, never written
    assert loose["ok"] is False and loose["say"].startswith("did you mean") and acts._step(record, "mba-teaching")["tier"] == 3
    assert len(json.loads((record / "roadmap.json").read_text(encoding="utf-8"))["roadmap_events"]) == n_before
    broken = cs.say_campaign(record, "move the trusts to tier 2", dialogue="file:///C:/nowhere/dialogue.mjs", today=TODAY)
    assert broken["ok"] is False and broken["campaign_act"] and "grammar could not be read" in broken["say"]        # never the steward's
    s = say("make the AI mechanics class an initiative in tier 2 under writing")
    assert s["ok"] and s["act"] == "campaign_promote_seed" and "tier 2" in s["say"] and seeds_mod.read_seeds(record) == []
    head = acts._step(record, s["step"])
    assert head["tier"] == 2 and head["area"] == "writing"
    made = say("make nothing here an initiative")
    assert made["ok"] and "nothing here is now a goal in tier 3" in made["say"], "no seed by that name: a goal from his words (W2b-2)"
    assert say("make the trusts an initiative under moonlight")["ok"] is False


def test_what_needs_me_reads_the_record_and_writes_nothing(record):
    n0 = len(json.loads((record / "roadmap.json").read_text(encoding="utf-8"))["roadmap_events"])
    acts.act(record, {"act": "flag", "step": "trust-call"})
    n1 = len(json.loads((record / "roadmap.json").read_text(encoding="utf-8"))["roadmap_events"])
    r = cs.say_campaign(record, "what needs me this week?", dialogue=DIALOGUE, today=TODAY)
    assert r["ok"] and r["read_only"] and "need" in r["say"] and "call the trustee (The trusts, tier 2)" in r["say"]   # the referenced MBA part reads its live state
    assert "nothing on the Campaign is dated inside this week" in r["say"]
    assert acts.act(record, {"act": "add", "initiative": "trusts", "kind": "task", "text": "an old one", "due": "2026-09-18"})["ok"]
    r2 = cs.say_campaign(record, "what needs me this week?", dialogue=DIALOGUE, today=TODAY)
    assert "an old one" not in r2["say"]                                                        # Monday to Sunday only
    assert n1 == n0 + 2
    t = cs.say_campaign(record, "What needs me today", dialogue=DIALOGUE, today=TODAY)
    assert t["ok"] and "today or earlier" in t["say"]
