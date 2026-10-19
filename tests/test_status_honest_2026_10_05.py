"""The 10-minute status says what is running, observed (his word, 2026-10-05: the updates "don't seem to be congruent
with what's actually happening")."""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from steward_cockpit import steward_campaign as c  # noqa: E402


def test_a_running_code_job_is_read_from_the_steward_s_own_record(tmp_path):
    (tmp_path / ".ecgberht").mkdir()
    started = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 600))
    (tmp_path / ".ecgberht" / "code-jobs.json").write_text(json.dumps([
        {"id": "a", "status": "done", "brief": "# Work order: old"},
        {"id": "b", "status": "running", "started": started, "brief": "# Work order: the tile borders\nmore"}]), encoding="utf-8")
    jobs = c.running_code_jobs(str(tmp_path))
    assert [j["id"] for j in jobs] == ["b"] and jobs[0]["title"] == "the tile borders" and 9 <= jobs[0]["minutes"] <= 11
    assert c.running_code_jobs(str(tmp_path / "nowhere")) == []


def test_the_composer_leads_with_the_job_and_names_a_stale_working_note():
    src = open(c.__file__, encoding="utf-8").read()
    assert 'running = {"kind": "code_job"' in src and "but nothing is running now" in src
    from steward_cockpit import steward_engine as se
    assert "running_code_jobs(self.dir)" in open(se.__file__, encoding="utf-8").read(), "the cadence narrates a running job"
