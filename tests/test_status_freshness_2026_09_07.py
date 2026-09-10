"""John, 2026-09-07: status updates "not in tune with what is happening". The cockpit's share, made
mechanical: a mid-turn steward is said aloud with its start time; the effort line carries its age and a
line a day or more behind the newest work is shouted; the PLAN DRIFT line is computed at delivery."""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from steward_cockpit import steward_campaign as campaign  # noqa: E402


def _effort(tmp, effort_as_of, roadmap_age_days=0):
    d = Path(tmp)
    (d / "ECGBERHT.md").write_text("# Face\n\n## North Star\nA goal.\n", encoding="utf-8")
    (d / "strip.json").write_text(json.dumps({
        "active_effort": "Week 1 - built", "active_effort_as_of": effort_as_of,
        "human_wait": "", "next_recommended": "next", "phase": "building"}), encoding="utf-8")
    (d / "roadmap.json").write_text(json.dumps({"roadmap_projection": [
        {"id": "s1", "name": "Week 1", "status": "done"}, {"id": "s2", "name": "Week 2", "status": "active"}]}), encoding="utf-8")
    t = time.time() - roadmap_age_days * 86400
    os.utime(d / "roadmap.json", (t, t))
    return str(d)


def test_effort_line_two_days_behind_the_newest_work_is_stale_and_shouted():
    with tempfile.TemporaryDirectory() as tmp:
        two_days_ago = time.strftime("%Y-%m-%d", time.localtime(time.time() - 2 * 86400))
        d = _effort(tmp, two_days_ago)
        fl = campaign.effort_line_freshness(d)
        assert fl["stale"] is True and fl["behind_days"] >= 1 and fl["as_of"] == two_days_ago
        s = campaign.compose_status(d)
        assert s["effort_line"]["stale"] is True
        assert any("effort line as of " + two_days_ago in line and "not restamped" in line for line in s["now"]), s["now"]


def test_effort_line_stamped_today_is_fresh():
    with tempfile.TemporaryDirectory() as tmp:
        today = time.strftime("%Y-%m-%d")
        d = _effort(tmp, today)
        fl = campaign.effort_line_freshness(d)
        assert fl["stale"] is False and fl["behind_days"] == 0
        assert not any("not restamped" in line for line in campaign.compose_status(d)["now"])


def test_mid_turn_steward_is_said_with_its_start_time():
    with tempfile.TemporaryDirectory() as tmp:
        d = _effort(tmp, time.strftime("%Y-%m-%d"))
        started = time.time() - 7 * 60
        s = campaign.compose_status(d, engine_state={"busy": True, "turn_started": started, "queued": 1})
        line = next(l for l in s["now"] if l.startswith("steward mid-turn"))
        assert "since " + time.strftime("%H:%M", time.localtime(started)) in line
        assert "(7 min)" in line and "1 queued" in line
        assert s["running"]["kind"] == "steward"


def test_drift_line_is_computed_at_delivery_not_at_queue_time():
    from steward_cockpit import steward_engine as eng
    src = Path(eng.__file__).read_text(encoding="utf-8")
    assert "self.queue.append(text)" in src
    assert "text = text + self._plan_drift_suffix()" not in src          # never at queue time
    assert 'suffix = "" if self.general else self._plan_drift_suffix()' in src   # at delivery from the queue
    assert 'self._send_locked(text + (self._plan_drift_suffix() if (human and not self.general) else ""))' in src
    assert '"turn_started": self.turn_started if self.busy else 0.0' in src
