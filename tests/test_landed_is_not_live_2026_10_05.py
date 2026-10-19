"""Landed is not live (his word, 2026-10-05): a job landed in Anchor's own repository tells the steward it waits for a
restart."""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from steward_cockpit import code_jobs as cj  # noqa: E402


def test_an_anchor_landing_says_it_waits_for_a_restart():
    assert "NOT LIVE YET" in cj.live_note({"landed": True, "repo": HERE})
    assert cj.live_note({"landed": False, "repo": HERE}) == ""
    assert cj.live_note({"landed": True, "repo": os.path.dirname(HERE)}) == "", "another repository is not the service"
    src = open(cj.__file__, encoding="utf-8").read()
    assert "live = live_note(job)" in src


def test_live_is_observed_against_the_running_build(monkeypatch):
    import subprocess
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=HERE, capture_output=True, text=True).stdout.strip()
    parent = subprocess.run(["git", "rev-parse", "HEAD~1"], cwd=HERE, capture_output=True, text=True).stdout.strip()
    monkeypatch.setenv("ANCHOR_RUNNING_HEAD", parent)
    job = {"landed": True, "repo": HERE, "landed_commit": head}
    assert cj.live_state(job) == "waits for a restart" and "NOT LIVE YET" in cj.live_note(job)
    monkeypatch.setenv("ANCHOR_RUNNING_HEAD", head)
    assert cj.live_state(job) == "live" and cj.live_note(job) == ""
    assert cj.live_state({"landed": False, "repo": HERE}) == ""
