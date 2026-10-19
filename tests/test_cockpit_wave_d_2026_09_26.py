"""Wave D (2026-09-26): the collaborator's printable brief is token-less, read-only and honest; the project
page itself stays locked without a token."""
import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from steward_cockpit import steward_routes
from tests.test_steward_refinement_browser import campaign_server


def _campaign(tmp_path):
    root = tmp_path / "Brief campaign"
    root.mkdir()
    (root / "ECGBERHT.md").write_text("# Brief campaign\n\n## North star\nA usable weekly tracker for the team.\n", encoding="utf-8")
    (root / "roadmap.json").write_text(json.dumps({"roadmap_events": [], "roadmap_projection": [
        {"id": "plan", "name": "Plan the tracker", "status": "done"},
        {"id": "build", "name": "Build the tracker", "status": "waiting", "waiting_on": "your read", "navigation": {"current": True}},
        {"id": "later", "name": "Field test", "status": "parked"}]}), encoding="utf-8")
    (root / "DELIVERABLES.md").write_text("| What | Where | Date | Step |\n| --- | --- | --- | --- |\n"
        "| Tracker draft | `tracker.html` | 2026-09-13 | build |\n", encoding="utf-8")
    (root / "tracker.html").write_text("<h1>tracker</h1>", encoding="utf-8")
    d = root / ".ecgberht"; d.mkdir()
    (d / "status-summary.json").write_text(json.dumps({"at": "2026-09-25 17:40", "status_id": "1", "effort": "Brief campaign",
        "lead_line": "Next: your read of the tracker draft", "now": ["nothing running - waiting on you"],
        "plan": {"step": "build", "steps_done": 1, "steps_total": 3, "waiting_on_you": "your read", "next": "read", "attention": "needs_you"},
        "map": [], "swarm": []}), encoding="utf-8")
    return root


def test_the_brief_carries_the_six_things_and_nothing_private(tmp_path):
    root = _campaign(tmp_path)
    html = steward_routes.render_brief(str(tmp_path), "Brief campaign")
    assert html.startswith("<!doctype html>")
    assert "<title>Brief campaign \u00b7 brief</title>" in html
    assert "A usable weekly tracker for the team." in html                     # goal
    assert "1 of 2 steps done" in html and "now: Build the tracker" in html    # path, counted over the steps shown
    assert "\u2713 Plan the tracker" in html and "\u2691 Build the tracker" in html and "waiting on your read" in html
    assert "Field test" not in html                                            # parked steps stay out
    assert "Next: your read of the tracker draft" in html                      # lead line
    assert "last status 2026-09-25 17:40" in html                            # the time once, under Last change
    assert "waiting on your read" in html                                      # waiting on
    assert "none open" in html                                                 # no pending decision recorded
    for private in ("token", "tracker.html", "/api/", "data-say", "<script"):
        assert private not in html, private


def test_an_unknown_effort_is_none(tmp_path):
    _campaign(tmp_path)
    assert steward_routes.render_brief(str(tmp_path), "nope") is None


def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode("utf-8", "replace")


def test_the_brief_route_is_token_less_and_the_project_page_stays_locked(campaign_server):
    origin, pid = campaign_server.origin, campaign_server.project_id
    code, body = _get(f"{origin}/project/{pid}/brief?dir=foundation%20campaign")
    assert code == 200 and "foundation campaign" in body and "<h2>Goal</h2>" in body
    assert campaign_server.token not in body
    code, body = _get(f"{origin}/project/{pid}")
    assert code == 200 and "token-locked" in body                             # the cockpit itself still needs the token
    code, _ = _get(f"{origin}/project/{pid}/brief?dir=nope")
    assert code == 404
    code, _ = _get(f"{origin}/project/not-a-project/brief?dir=")
    assert code == 404
