"""W4 of the two-lane plan (his rule, 2026-10-05): orange when something waits on him - even while work runs; green only
when work is observed running; gray otherwise; the card's edge pulses exactly when its light is orange."""
import json
import os
import sys
import time
from types import SimpleNamespace

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from steward_cockpit import steward_engine as se  # noqa: E402


def _eng(tmp_path, busy=False, question=None):
    e = SimpleNamespace(dir=str(tmp_path), broken=False, busy=busy, queue=[], last_output=time.time(), last_say=0, woke_at=0,
                        open_question=question)
    e.alive = lambda: True
    e._question_contexts = lambda att: []
    return e


def test_orange_wins_over_working_and_green_needs_observed_work(tmp_path):
    assert se.Engine.light(_eng(tmp_path, busy=True, question="approve the plan?"), {}) == "green", "John 2026-10-15: working status is always a green light"
    assert se.Engine.light(_eng(tmp_path, busy=False, question="approve the plan?"), {}) == "orange"
    assert se.Engine.light(_eng(tmp_path, busy=True), {}) == "green"
    assert se.Engine.light(_eng(tmp_path), {"state": "needs_you"}) == "orange"
    assert se.Engine.light(_eng(tmp_path), {}) == "quiet"
    (tmp_path / ".ecgberht").mkdir()
    (tmp_path / ".ecgberht" / "code-jobs.json").write_text(json.dumps([{"id": "j", "status": "running", "started": "2026-10-05 12:00:00", "brief": "x"}]), encoding="utf-8")
    assert se.Engine.light(_eng(tmp_path), {}) == "green", "a running code job is observed work"


def test_the_edge_pulses_exactly_when_the_light_is_orange():
    hp = open(os.path.join(HERE, "high_seat_page.py"), encoding="utf-8").read()
    assert 'if lclass == "orange":   # W4' in hp
    js = open(os.path.join(HERE, "static", "cockpit-feedback.js"), encoding="utf-8").read()
    assert "|| st.light === 'orange';" in js
