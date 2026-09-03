"""home_attention — the deterministic v0 ranking behind the r3 home rail.

Contract (prototype r3 SCORECARD + 2026-08-29 addendum): ranked, explainable
(every row names its rule), no hidden score, quiet when nothing needs you,
never raises on odd input, no I/O.
"""
from datetime import date, datetime, timedelta
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import home_attention as ha  # noqa: E402

TODAY = date(2026, 9, 3)
NOW = datetime(2026, 9, 3, 10, 0, 0)


def _task(text, due, pr=2, done=False):
    return {"text": text, "due": due, "priority": pr, "done": done}


def _sess(status, pid="p1", lane="build", when=None, label=""):
    return {"status": status, "project_id": pid, "lane": lane, "label": label,
            "updated_at": (when or NOW).timestamp(), "created_at": (when or NOW).timestamp()}


def test_rank_order_is_the_rule_order_and_each_row_names_its_rule():
    rows = ha.build_attention(
        tasks=[_task("due today", "2026-09-03", 1), _task("late", "2026-09-01", 2)],
        sessions=[_sess("failed"), _sess("needs-attention", pid="p2", lane="plan")],
        health=("2026-09-03", "ISSUES FOUND"), today=TODAY, now=NOW,
        project_names={"p1": "Alpha", "p2": "Beta"})
    assert [r["rule"] for r in rows] == ["health", "needs-you", "overdue", "due-today", "failed"]
    assert all(r["rule_label"] for r in rows)
    assert rows[1]["text"] == "Beta is waiting on you" and rows[1]["href"] == "/project/p2"
    assert rows[2]["why"].startswith("P2 · due 2026-09-01 (2 days ago)")
    assert rows[4]["text"].startswith("Alpha: a build session failed")


def test_quiet_when_nothing_needs_you_and_the_move_is_honest():
    rows = ha.build_attention(tasks=[_task("later", "2026-09-10")], sessions=[_sess("done")],
                              health=("2026-09-03", "ALL OK"), today=TODAY, now=NOW)
    assert rows == []
    lead, sub = ha.the_move(rows, "Tip of the Hat")
    assert lead == "Nothing is waiting on you."
    lead, sub = ha.the_move(ha.build_attention(tasks=[_task("x", "2026-09-03", 1)], today=TODAY, now=NOW), "High Seat")
    assert lead.startswith("x — P1 · due today") and "High Seat" in sub


def test_within_rule_ordering_is_deterministic():
    rows = ha.build_attention(
        tasks=[_task("b p2 older", "2026-08-30", 2), _task("a p1 newer", "2026-09-01", 1),
               _task("z today p2", "2026-09-03", 2), _task("y today p1", "2026-09-03", 1)],
        today=TODAY, now=NOW)
    assert [r["text"] for r in rows] == ["b p2 older", "a p1 newer", "y today p1", "z today p2"]


def test_failed_window_and_non_actionable_lanes_are_excluded():
    old = NOW - timedelta(days=8)
    rows = ha.build_attention(sessions=[_sess("failed", when=old), _sess("failed", lane="swarm"),
                                        _sess("failed", pid="")], today=TODAY, now=NOW)
    assert rows == []
    rows = ha.build_attention(sessions=[_sess("failed", when=NOW - timedelta(days=6))], today=TODAY, now=NOW)
    assert [r["rule"] for r in rows] == ["failed"]


def test_limit_and_junk_input_never_raise():
    tasks = [_task("t%d" % i, "2026-09-03") for i in range(10)] + [None, "junk", {"due": "??", "text": "x"}]
    rows = ha.build_attention(tasks=tasks, sessions=[None, 3, {"status": "failed", "updated_at": "nope"}],
                              health=("d", None), today=TODAY, now=NOW, limit=4)
    assert len(rows) == 4
    assert ha.build_attention(tasks=None, sessions=None, health=None, today=TODAY, now=NOW) == []


def test_rail_counts_due_rows_and_live_rows():
    sessions = [_sess("running", label="Deck build"), _sess("running", pid="p2"), _sess("done")]
    rows = ha.build_attention(sessions=[_sess("needs-attention", pid="p3")], today=TODAY, now=NOW)
    c = ha.rail_counts(sessions, rows, folders=6, open_projects=15)
    assert c == {"open": 15, "running": 2, "need_you": 1, "folders": 6}
    due, more = ha.due_rows([_task("a", "2026-09-03", 2), _task("b", "2026-09-01", 1), _task("c", "2026-09-04")],
                            today=TODAY, limit=1)
    assert due == [{"text": "b", "priority": 1, "overdue": True}] and more == 1
    live, more = ha.live_rows(sessions, {"p2": "Beta"}, limit=5)
    assert [x["text"] for x in live] == ["Deck build", "Beta"] and more == 0
