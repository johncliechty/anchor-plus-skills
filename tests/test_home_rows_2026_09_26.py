"""home_rows + the W1a rules — every row on the home is a fact from a project's steward record (High Seat).

Hermetic: temp project folders carry a strip, a roadmap projection and a persisted status summary.
"""
import json
import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import home_attention as ha  # noqa: E402
import home_rows as hr  # noqa: E402

TODAY = date(2026, 9, 26)
NOW = datetime(2026, 9, 26, 17, 30)


def _project(tmp_path, pid, name, steps=(), wait=None, lead="", nxt="", why=""):
    d = tmp_path / name.replace(" ", "_")
    d.mkdir()
    (d / "strip.json").write_text(json.dumps({"human_wait": wait, "next_recommended": nxt, "why_next": why}), encoding="utf-8")
    (d / "roadmap.json").write_text(json.dumps({"schema": "x", "roadmap_events": [], "roadmap_projection": list(steps)}), encoding="utf-8")
    if lead:
        (d / ".ecgberht").mkdir()
        (d / ".ecgberht" / "status-summary.json").write_text(json.dumps({"at": "2026-09-26T17:00", "lead_line": lead, "plan": {}}), encoding="utf-8")
    return {"id": pid, "name": name, "folder_path": str(d)}


def _world(tmp_path):
    mba = _project(tmp_path, "6765ece4", "MBA Teaching AI", steps=[
        {"id": "lec3", "name": "Lecture 3 AI supplement", "status": "waiting", "due": "2026-10-10"},
        {"id": "hw2", "name": "retool homework 2", "status": "planned", "due": "2026-10-27"},
        {"id": "syl", "name": "Syllabus", "status": "done", "due": "2026-09-01"},
        {"id": "old", "name": "Block 1 quiz", "status": "planned", "due": "2026-09-20"},
    ], wait="approve the Lecture 3 AI supplement", lead="Next: Lecture 3 — the interface lesson is final.")
    trusts = _project(tmp_path, "9405abe0", "Family Trusts", steps=[
        {"id": "val", "name": "Company valuations into the package", "status": "active", "due": "2026-10-08"},
        {"id": "mon", "name": "Sign the engagement letter", "status": "planned", "due": "2026-09-21"},   # the Monday of the test week
    ], nxt="Send the three valuation figures", why="the package closes on them")
    empty = _project(tmp_path, "aaaaaaaa", "Quiet project")
    return mba, trusts, empty


def test_project_facts_read_the_record_and_never_the_done_steps(tmp_path):
    mba, trusts, empty = _world(tmp_path)
    f = hr.project_facts(mba, TODAY)
    assert f["has_record"] and f["href"] == "/project/6765ece4"
    assert f["needs_you"] == "approve the Lecture 3 AI supplement"
    assert f["summary"]["lead_line"].startswith("Next: Lecture 3") and f["summary_age_s"] is not None
    assert [s["due"] for s in f["dated"]] == ["2026-09-20", "2026-10-10", "2026-10-27"]   # soonest first; the done syllabus is out
    assert f["nearest_due"] == "2026-09-20"
    t = hr.project_facts(trusts, TODAY)
    assert t["needs_you"] == ""
    assert t["next"] == "Send the three valuation figures" and t["why"] == "the package closes on them" and t["summary"] is None
    assert [s["due"] for s in t["dated"]] == ["2026-09-21", "2026-10-08"]
    e = hr.project_facts(empty, TODAY)
    assert e["has_record"] and e["dated"] == [] and e["nearest_due"] == "" and e["next"] == ""
    nothing = hr.project_facts({"id": "x", "name": "no folder"}, TODAY)
    assert nothing["has_record"] is False and nothing["dated"] == []


def test_the_rows_are_facts_from_the_records_in_rule_order(tmp_path):
    facts = hr.all_project_facts(_world(tmp_path), TODAY)
    rows = ha.build_attention(projects=facts, today=TODAY, now=NOW, limit=10)
    assert [r["rule"] for r in rows] == ["needs-you", "overdue", "overdue", "due-soon", "due-soon", "due-soon"]
    assert rows[0]["text"] == "MBA Teaching AI is waiting on you" and rows[0]["why"] == "approve the Lecture 3 AI supplement"
    assert rows[0]["rule_label"] == "the steward's record waits on you"
    assert rows[1]["text"] == "Block 1 quiz" and rows[1]["why"] == "due Sep 20 (6 days ago) · MBA Teaching AI"
    assert rows[1]["href"] == "/project/6765ece4" and rows[1]["kind"] == "step"
    assert rows[2]["text"] == "Sign the engagement letter"
    assert [r["text"] for r in rows[3:]] == ["Company valuations into the package", "Lecture 3 AI supplement", "retool homework 2"]
    assert rows[3]["why"] == "due Oct 8 · Family Trusts"
    assert all(r["rule_label"] for r in rows)


def test_a_session_row_for_the_same_project_is_not_repeated_and_far_dates_stay_out(tmp_path):
    facts = hr.all_project_facts(_world(tmp_path), TODAY)
    sess = [{"status": "needs-attention", "project_id": "6765ece4", "lane": "plan", "label": "",
             "updated_at": NOW.timestamp(), "created_at": NOW.timestamp()}]
    rows = ha.build_attention(sessions=sess, projects=facts, today=TODAY, now=NOW,
                              project_names={"6765ece4": "MBA Teaching AI"}, limit=10)
    waits = [r for r in rows if r["rule"] == "needs-you"]
    assert len(waits) == 1                                   # one row per project
    assert waits[0]["why"] == "approve the Lecture 3 AI supplement"   # the record's wait is the fact
    assert waits[0]["rule_label"] == "the steward's record waits on you"
    only_session = ha.build_attention(sessions=sess, today=TODAY, now=NOW, project_names={"6765ece4": "MBA Teaching AI"})
    assert only_session[0]["why"] == "plan session needs an answer" and only_session[0]["rule_label"] == "a session is waiting on you"
    # a step dated beyond five weeks does not raise a row
    far = date(2026, 12, 1)
    facts2 = hr.all_project_facts(_world(tmp_path / "later"), far) if (tmp_path / "later").mkdir() is None else []
    rows_far = ha.build_attention(projects=facts2, today=date(2026, 8, 1), now=datetime(2026, 8, 1, 9), limit=10)
    assert [r["rule"] for r in rows_far] == ["needs-you"]


def test_the_brief_is_bullets_of_facts(tmp_path):
    facts = hr.all_project_facts(_world(tmp_path), TODAY)
    rows = ha.build_attention(projects=facts, today=TODAY, now=NOW, limit=10)
    b = ha.brief_bullets(rows, facts, today=TODAY, seat_name="High Seat")
    assert b == ["MBA Teaching AI is waiting on you — approve the Lecture 3 AI supplement.",
                 "This week: Sign the engagement letter (overdue since Sep 21, Family Trusts).",   # the header's Monday-Sunday; a past date named
                 "You can act from here. Opening the High Seat is optional."]
    quiet = ha.brief_bullets([], [], today=TODAY)
    assert quiet == ["Nothing is waiting on you.", "Nothing carries a date yet.", "You can act from here. Opening the High Seat is optional."]
    # the Due today card sees the roadmap steps beside the tasks
    due, more = ha.due_rows([], today=TODAY, projects=facts)
    assert [d["text"] for d in due] == ["Block 1 quiz · MBA Teaching AI", "Sign the engagement letter · Family Trusts"]
    assert all(d["overdue"] for d in due) and more == 0


def test_a_wait_that_says_none_is_not_a_wait(tmp_path):
    """The cockpit's rule (steward_campaign._real_wait) on the home: a strip whose human_wait says "none" puts no card
    on Needs you; a real sentence does; the status summary's waiting_on_you follows the same rule."""
    none = _project(tmp_path, "n1", "Says none", wait="none")
    assert hr.project_facts(none, TODAY)["needs_you"] == ""
    dash = _project(tmp_path, "n2", "Says dash", wait="—")
    assert hr.project_facts(dash, TODAY)["needs_you"] == ""
    expl = _project(tmp_path, "n5", "Says none dash", wait="none — the run is still going")
    assert hr.project_facts(expl, TODAY)["needs_you"] == ""                          # the cockpit's clause, not a local list (Grok R7)
    real = _project(tmp_path, "n3", "Says a thing", wait="John: sign the engagement letter")
    assert hr.project_facts(real, TODAY)["needs_you"] == "John: sign the engagement letter"
    summ = _project(tmp_path, "n4", "Summary none", lead="Next: x")
    (tmp_path / "Summary_none" / ".ecgberht" / "status-summary.json").write_text(
        json.dumps({"at": "2026-09-26T17:00", "lead_line": "Next: x", "plan": {"waiting_on_you": "nothing"}}), encoding="utf-8")
    assert hr.project_facts(summ, TODAY)["needs_you"] == ""


def test_the_week_in_words_and_the_short_date():
    assert hr.week_in_words(date(2026, 9, 26)) == "this week Sep 21–27"
    assert hr.week_in_words(date(2026, 9, 30)) == "this week Sep 28 – Oct 4"
    assert hr.short_date("2026-10-08") == "Oct 8"
    assert hr.short_date("junk") == "junk"


def test_the_project_row_shows_the_next_step_and_the_date(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path / "data"))
    import anchor_gui
    mba, trusts, empty = _world(tmp_path)
    facts = {f["id"]: f for f in hr.all_project_facts([mba, trusts, empty], TODAY)}
    row = anchor_gui.render_project_tile_html(trusts, facts[trusts["id"]])
    assert "next: Send the three valuation figures" in row          # probe 3: no persisted status, so the strip's next
    assert "overdue since Sep 21" in row                            # the chip says it against today
    quiet = anchor_gui.render_project_tile_html(empty, facts[empty["id"]])
    assert "rnd-row-due" not in quiet and "next:" not in quiet


def test_the_facts_come_from_the_effort_touched_last_one_folder_down_and_name_it(tmp_path):
    import os, time
    d = tmp_path / "Skill_Foundry"; d.mkdir()
    (d / "Anchor.md").write_text("a project with no record at its root", encoding="utf-8")
    eff = d / "steward-refinement"; eff.mkdir()
    (eff / "ECGBERHT.md").write_text("# Ecgberht\n", encoding="utf-8")
    (eff / "strip.json").write_text(json.dumps({"human_wait": "", "next_recommended": "Fold the handback", "why_next": "it is the open step"}), encoding="utf-8")
    (eff / "roadmap.json").write_text(json.dumps({"schema": "x", "roadmap_events": [], "roadmap_projection": [{"id": "s1", "name": "Fold the handback", "status": "active", "due": "2026-10-02"}]}), encoding="utf-8")
    e = {"id": "sf01", "name": "Skill Foundry", "folder_path": str(d)}
    f = hr.project_facts(e, TODAY)
    assert f["has_record"] and f["effort"] == "steward-refinement" and f["next"] == "Fold the handback" and f["nearest_due"] == "2026-10-02"
    assert f["projection"] is None and "touched_s" not in f and "effort_dir" not in f   # the root record's projection only is cached for the resolver; no private age
    assert hr.current_effort(str(d)) == "steward-refinement"
    # a root record touched later wins; an untouched sibling effort does not
    (d / "ECGBERHT.md").write_text("# Ecgberht\n", encoding="utf-8")
    (d / "strip.json").write_text(json.dumps({"human_wait": "John: sign it", "next_recommended": "Root next", "why_next": ""}), encoding="utf-8")
    later = time.time() + 60
    os.utime(d / "strip.json", (later, later))
    f2 = hr.project_facts(e, TODAY)
    assert f2["effort"] == "" and f2["next"] == "Root next" and f2["needs_you"] == "John: sign it"
    # the cockpit's own clock (steward_campaign.last_touched): a conversation in the sub-effort newer than the root's
    # strip makes it the card's effort again — the same sort the cockpit's efforts row uses
    (eff / ".ecgberht").mkdir()
    (eff / ".ecgberht" / "conversation-log.json").write_text("[]", encoding="utf-8")
    os.utime(eff / ".ecgberht" / "conversation-log.json", (later + 60, later + 60))
    assert hr.current_effort(str(d)) == "steward-refinement"
    # no record anywhere: honest, and the effort is empty
    q = tmp_path / "Quiet"; q.mkdir()
    fq = hr.project_facts({"id": "q1", "name": "Quiet", "folder_path": str(q)}, TODAY)
    assert fq["has_record"] is False and fq["effort"] == ""
