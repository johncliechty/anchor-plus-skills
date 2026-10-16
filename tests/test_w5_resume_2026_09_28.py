"""W5 of the steward revision (2026-09-28): Resume on every card — where he left (W0's leave receipt), re-read
against the record now, opened in the cockpit at that step; and the folds (a quiet Workbench is one line; the
Desk shows no menu of unconnected things)."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import home_rows  # noqa: E402
import high_seat_page as hsp  # noqa: E402

PID = "6765ece4b3bc43b0b0b0907b92b17280"


def _record(d, receipts, events_n=5):
    d.mkdir(parents=True, exist_ok=True)
    (d / "ECGBERHT.md").write_text("# Ecgberht\n\n## North star\n\n> x\n", encoding="utf-8")
    (d / "strip.json").write_text(json.dumps({"human_wait": "none", "current_step_id": "lec4", "next_recommended": "Lecture 4", "why_next": "it follows",
                                             "instruments": [], "receipts": receipts}), encoding="utf-8")
    (d / "roadmap.json").write_text(json.dumps({"roadmap_events": [{"seq": i, "kind": "step_create", "step_id": "s%d" % i} for i in range(1, events_n + 1)],
                                               "roadmap_projection": [{"id": "lec3", "name": "Lecture 3 AI supplement", "status": "done"},
                                                                      {"id": "lec4", "name": "Lecture 4 AI supplement", "status": "active"}]}), encoding="utf-8")


def test_the_facts_carry_where_he_left_re_read_against_the_roadmap_now(tmp_path, monkeypatch):
    d = tmp_path / "mba"
    leave = {"kind": "leave", "at": "2026-09-28T15:00:00Z", "current_step_id": "lec4", "last_event_seq": 3, "last_event_kind": "status_flip",
             "last_event_step_id": "lec3", "presentation_id": "p2", "active_effort": "mba", "wait_ref": "none", "human_wait": "none"}
    _record(d, [{"kind": "heartbeat"}, leave], events_n=5)
    import datetime as _dt
    monkeypatch.setattr(home_rows.time, "time", lambda: _dt.datetime(2026, 9, 28, 17, 30, tzinfo=_dt.timezone.utc).timestamp())
    f = home_rows.project_facts({"id": PID, "name": "MBA Teaching AI", "folder_path": str(d)})
    r = f["resume"]
    assert r["step_id"] == "lec4" and r["step"] == "Lecture 4 AI supplement" and r["step_status"] == "active"
    assert r["at"] == "2026-09-28T15:00:00Z" and r["ago"] == "2 h ago"
    assert r["events_since"] == 2, "five events now, three when he left"
    assert r["presentation_id"] == "p2"
    # no receipt: no Resume
    _record(tmp_path / "quiet", [])
    assert home_rows.project_facts({"id": "q", "name": "Q", "folder_path": str(tmp_path / "quiet")})["resume"] is None
    # a receipt naming a step the roadmap no longer lists: the id stands in for the name
    _record(tmp_path / "gone", [dict(leave, current_step_id="zz", last_event_seq=5)])
    r2 = home_rows.project_facts({"id": "g", "name": "G", "folder_path": str(tmp_path / "gone")})["resume"]
    assert r2["step"] == "zz" and r2["events_since"] == 0


def test_ago_in_words():
    now = 1_000_000.0
    assert home_rows._ago(now - 30, now) == "just now"
    assert home_rows._ago(now - 12 * 60, now) == "12 min ago"
    assert home_rows._ago(now - 3 * 3600, now) == "3 h ago"
    assert home_rows._ago(now - 86400, now) == "1 day ago"
    assert home_rows._ago(now - 5 * 86400, now) == "5 days ago"
    assert home_rows._ago(None) == ""


def test_the_card_offers_resume_at_that_step_with_its_age_and_what_moved(tmp_path):
    f = {"has_record": True, "effort": "mba", "needs_you": "", "next": "Lecture 4", "why": "", "efforts": [], "other_waits": [],
         "resume": {"at": "2026-09-28T15:00:00Z", "ago": "2 h ago", "step_id": "lec4", "step": "Lecture 4 AI supplement", "events_since": 2}}
    html = hsp._card({"id": PID, "name": "MBA Teaching AI"}, f, "")
    assert 'class="t-resume" href="/project/%s?dir=mba&amp;step=lec4"' % PID in html
    assert 'title="you left at Lecture 4 AI supplement (2 h ago)"' in html, "no numeral on the card (Grok W5)"
    assert "&#8617; Resume <span class=\"t-age\">2 h ago</span>" in html
    quiet = hsp._card({"id": PID, "name": "MBA Teaching AI"}, dict(f, resume=None), "")
    assert "t-resume" not in quiet
    still = hsp._card({"id": PID, "name": "MBA Teaching AI"}, dict(f, resume=dict(f["resume"], events_since=0)), "")
    assert "nothing moved since" in still


def test_lint_the_cockpit_reads_the_step_parameter_and_opens_the_fold_above_the_row():
    """A LINT, not the landing: it reads the source for the parameter, the row lookup, the fold-opening walk and the
    class mark. Whether the row is on the plan he can see is proved only on his screen (the exit gate, scenario 4)."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    js = open(os.path.join(root, "steward_cockpit", "static", "shared.js"), encoding="utf-8").read()
    assert 'PARAMS.get("step")' in js and 'li[data-step-id="' in js and "_stepShown" in js
    assert 'anc.tagName === "DETAILS" && !anc.open' in js and 'classList.add("navstep-land")' in js and "style.boxShadow" not in js
    css = open(os.path.join(root, "steward_cockpit", "static", "shared.css"), encoding="utf-8").read()
    assert ".navstep-land{" in css
    # the project page (the chamber) is what /project/<pid> serves; it must open the effort's plan cockpit in its
    # frame and forward the step — the live look of 11:54 found it ignoring ?dir= and ?step= entirely
    chamber = open(os.path.join(root, "steward_cockpit", "static", "cockpit.html"), encoding="utf-8").read()
    assert "function openEffort(rel, step)" in chamber and '"&step=" + encodeURIComponent(step)' in chamber
    assert 'if (!q.has("step") && q.get("open") !== "effort") return;' in chamber and "openEffort(q.get(\"dir\") || \"\", q.get(\"step\") || \"\")" in chamber


def test_the_folds_a_quiet_workbench_is_one_line_and_the_desk_lists_nothing_unconnected():
    # the Workbench retired 2026-10-02 (his word): the Terminal stands in its place and keeps its failed rows
    assert not hasattr(hsp, "_workbench")
    failed = hsp._terminal({"rows": [{"rule": "failed", "severity": "bad", "href": "/x", "text": "a failed run", "why": "exit 1"}]})
    assert "a failed run" in failed and 'id="termNew"' in failed
    desk = hsp._desk_line({"tasks_open": 3, "campaign": {"pid": "c"}})
    assert 'data-desk="cal"' not in desk and 'data-desk="mail"' not in desk and 'data-desk="tasks"' in desk
