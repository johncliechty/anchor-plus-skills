"""campaign_parts — a Campaign part's ``ref`` resolves against the record it points at (W0b, High Seat).

Hermetic: a dict lookup stands in for the registry; two temp project folders carry a roadmap
projection, a strip and a status summary. Broken references are named, never invented; one
projection read per distinct target per request.
"""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from steward_cockpit import campaign_parts as cp  # noqa: E402


def _project(tmp_path, pid, name, steps, wait="", lead=""):
    d = tmp_path / name.replace(" ", "_")
    d.mkdir()
    (d / "roadmap.json").write_text(json.dumps({"schema": "x", "roadmap_events": [], "roadmap_projection": steps}), encoding="utf-8")
    (d / "strip.json").write_text(json.dumps({"human_wait": wait}), encoding="utf-8")
    (d / ".ecgberht").mkdir()
    (d / ".ecgberht" / "status-summary.json").write_text(json.dumps({"at": "2026-09-26T17:00", "lead_line": lead}), encoding="utf-8")
    return {"id": pid, "name": name, "folder_path": str(d)}


@pytest.fixture
def world(tmp_path):
    mba = _project(tmp_path, "6765ece4b3bc43b0b0b0907b92b17280", "MBA Teaching AI", [
        {"id": "lecture-3", "name": "Lecture 3 AI supplement", "status": "waiting", "waiting_on": "your read", "due": "2026-10-10"},
        {"id": "homework-2", "name": "retool homework 2", "status": "planned", "due": "2026-10-27"},
        {"id": "syllabus", "name": "Syllabus 2026", "status": "done", "due": "2026-09-01"},
    ], wait="approve the Lecture 3 AI supplement", lead="Next: Lecture 3 — the interface lesson is final.")
    trusts = _project(tmp_path, "9405abe06dc84b749d4ece0bda1cb45c", "Family Trusts", [
        {"id": "valuations", "name": "Company valuations into the package", "status": "active"},
    ])
    # the trusts' wait lives only on the persisted status, as a managed campaign's does
    (Path(trusts["folder_path"]) / ".ecgberht" / "status-summary.json").write_text(
        json.dumps({"at": "2026-09-26T17:00", "lead_line": "", "plan": {"waiting_on_you": "the three valuation figures"}}), encoding="utf-8")
    entries = {e["id"]: e for e in (mba, trusts)}

    def lookup(pid):
        return entries.get(pid)
    return {"lookup": lookup, "mba": mba, "trusts": trusts}


def test_parse_ref_knows_the_four_kinds_and_refuses_the_rest():
    assert cp.parse_ref("project:abc") == {"kind": "project", "pid": "abc", "sub": ""}
    assert cp.parse_ref("step:abc/lec3") == {"kind": "step", "pid": "abc", "sub": "lec3"}
    assert cp.parse_ref("deliverable:abc/2") == {"kind": "deliverable", "pid": "abc", "sub": "2"}
    assert cp.parse_ref("calendar:evt-1") == {"kind": "calendar", "pid": "", "sub": "evt-1"}
    for bad in ("step:abc", "task:abc", "project:", "project:a b", "", None, 3):
        assert cp.parse_ref(bad) is None


def test_a_project_part_resolves_to_the_cockpit_with_its_wait_and_nearest_open_date(world):
    r = cp.resolve_ref("project:6765ece4b3bc43b0b0b0907b92b17280", lookup=world["lookup"], with_lead=True)
    assert r["broken"] is False and r["gap"] == ""
    assert r["name"] == "MBA Teaching AI"
    assert r["href"] == "/project/6765ece4b3bc43b0b0b0907b92b17280"
    assert r["state"] == "waiting on you: approve the Lecture 3 AI supplement"
    assert r["date"] == "2026-10-10"          # the nearest OPEN date; the done syllabus does not count
    assert r["lead"].startswith("Next: Lecture 3")


def test_a_step_part_carries_the_targets_name_state_and_date_and_links_to_its_plan(world):
    r = cp.resolve_ref("step:6765ece4b3bc43b0b0b0907b92b17280/lecture-3", lookup=world["lookup"])
    assert r["broken"] is False
    assert r["what"] == "Lecture 3 AI supplement"
    assert r["state"] == "waiting · your read"
    assert r["date"] == "2026-10-10"
    assert r["href"] == "/project/6765ece4b3bc43b0b0b0907b92b17280"   # the cockpit page has no plan anchor
    assert r["lead"] == ""                   # a lead line only when asked for (a row on screen)


def test_broken_references_are_named_never_invented(world):
    unknown = cp.resolve_ref("project:00000000deadbeef", lookup=world["lookup"])
    assert unknown["broken"] is True and unknown["gap"] == "no project with id 00000000deadbeef"
    nostep = cp.resolve_ref("step:9405abe06dc84b749d4ece0bda1cb45c/valuation-x", lookup=world["lookup"])
    assert nostep["broken"] is True and nostep["gap"] == "no step 'valuation-x' in Family Trusts"
    cal = cp.resolve_ref("calendar:evt-1", lookup=world["lookup"])
    assert cal["broken"] is True and cal["gap"] == "calendar not connected"
    junk = cp.resolve_ref("task:x", lookup=world["lookup"])
    assert junk["broken"] is True and "not a reference" in junk["gap"]
    for r in (unknown, nostep, cal, junk):
        assert r["href"] == "" and r["date"] == "" and r["what"] == ""


def test_resolve_parts_reads_each_target_once_per_request_and_skips_native_steps(world):
    steps = [
        {"id": "a", "ref": "project:6765ece4b3bc43b0b0b0907b92b17280"},
        {"id": "b", "ref": "step:6765ece4b3bc43b0b0b0907b92b17280/homework-2"},
        {"id": "c", "ref": "step:9405abe06dc84b749d4ece0bda1cb45c/valuations"},
        {"id": "d", "name": "a native task", "due": "2026-10-01"},
        {"id": "e", "ref": "project:nobody-here-00"},
    ]
    cache = {}
    out = cp.resolve_parts(steps, cache=cache, lookup=world["lookup"])
    assert set(out) == {"a", "b", "c", "e"}
    assert out["b"]["what"] == "retool homework 2" and out["b"]["date"] == "2026-10-27"
    assert out["c"]["state"] == "active"
    assert out["e"]["broken"] is True
    # the MBA folder was read once for a and b together; the trusts once; the unknown project never;
    # a second pass over the same request opens nothing new
    opened = [k for k in cache if k[0] == "projection"]
    assert len(opened) == 2
    before = set(cache)
    cp.resolve_parts(steps, cache=cache, lookup=world["lookup"])
    assert set(cache) == before


def test_a_deliverable_part_resolves_by_row_number_only(world):
    d = Path(world["mba"]["folder_path"])
    (d / "DELIVERABLES.md").write_text(
        "| What | Where | Date | Step |\n|---|---|---|---|\n| Lecture 3 AI supplement, draft 2 | `drafts/lec3.md` | 2026-09-26 | lec3 |\n",
        encoding="utf-8")
    pid = world["mba"]["id"]
    r = cp.resolve_ref("deliverable:%s/1" % pid, lookup=world["lookup"])
    assert r["broken"] is False and r["what"] == "Lecture 3 AI supplement, draft 2"
    by_title = cp.resolve_ref("deliverable:%s/lecture" % pid, lookup=world["lookup"])
    assert by_title["broken"] is True and "row number" in by_title["gap"]
    missing = cp.resolve_ref("deliverable:%s/9" % pid, lookup=world["lookup"])
    assert missing["broken"] is True and missing["gap"].startswith("no row 9")
    short = cp.resolve_ref("project:6765ece4", lookup=world["lookup"])
    assert short["broken"] is True                       # the full id only; a prefix never binds


def test_a_project_part_reads_the_wait_from_the_last_status_when_the_strip_has_none(world):
    r = cp.resolve_ref("project:9405abe06dc84b749d4ece0bda1cb45c", lookup=world["lookup"])
    assert r["state"] == "waiting on you: the three valuation figures"
