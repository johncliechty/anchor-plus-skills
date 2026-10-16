import copy
import json

import effort_history as eh
import rnd_registry
from steward_cockpit import steward_routes


def _project(project_id, folder, name=None):
    return {"id": project_id, "name": name or project_id, "folder_path": str(folder)}


def _run(identity, tokens=100, dollars=0, **extra):
    return {
        "job_id": "job-" + identity,
        "session_id": "session-" + identity,
        "engine_session_uuid": identity,
        "kind": "run-cost", "provenance": "run", "usage_state": "measured",
        "label": "Saved run " + identity, "created_at": 1789068000,
        "cost": {
            "total_tokens": tokens, "input_tokens": 30, "output_tokens": 20,
            "cache_read_input_tokens": 50, "cache_creation_input_tokens": 0,
            "total_cost_usd": dollars,
        },
        **extra,
    }


def _sources(monkeypatch, projects, records, lanes=("steward", "general")):
    calls = []
    monkeypatch.setattr(rnd_registry, "list_projects", lambda: copy.deepcopy(projects))
    monkeypatch.setattr(eh, "ROLLUP_LANES", lanes)
    monkeypatch.setattr(eh, "is_discovered", lambda record: record.get("_discovered") is True)

    def list_efforts(cdir, project_id, lane):
        calls.append((cdir, project_id, lane))
        return copy.deepcopy(records.get((project_id, lane), []))

    monkeypatch.setattr(eh, "list_efforts", list_efforts)
    return calls


def test_same_folder_aliases_deduplicate_identical_engine_cost_payloads(monkeypatch, tmp_path):
    project = tmp_path / "project"
    first = _run("engine-shared", tokens=12660105)
    alias = copy.deepcopy(first)
    alias["session_id"] = "different-alias-session"
    alias["job_id"] = "different-alias-job"
    _sources(monkeypatch, [
        _project("b", project / "."),
        _project("a", project),
    ], {
        ("a", "steward"): [first],
        ("b", "steward"): [alias],
    })
    result = steward_routes._other_recorded_usage(str(project))
    assert result["status"] == "available"
    assert result["scope"] == "separate run records; may overlap cockpit history"
    assert result["duplicate_count"] == 1
    assert result["conflict_count"] == 0
    assert len(result["records"]) == 1
    row = result["records"][0]
    assert row["tokens"] == 12660105
    assert row["project_ids"] == ["a", "b"]
    assert row["identity_type"] == "engine_session_uuid"
    assert row["identity"] == "engine-shared"
    assert row["conflict"] is False
    assert "total_tokens" not in result
    assert "total_cost_usd" not in result
    assert "total" not in result


def test_scope_matches_exact_registered_folder_not_children_or_prefixes(monkeypatch, tmp_path):
    project = tmp_path / "project"
    calls = _sources(monkeypatch, [
        _project("exact", project),
        _project("child", project / "nested"),
        _project("prefix", tmp_path / "project-other"),
        _project("parent", tmp_path),
    ], {
        ("exact", "steward"): [_run("exact")],
        ("child", "steward"): [_run("child", tokens=9200529)],
        ("prefix", "steward"): [_run("prefix")],
    })
    result = steward_routes._other_recorded_usage(str(project))
    assert {call[1] for call in calls} == {"exact"}
    assert [row["identity"] for row in result["records"]] == ["exact"]
    assert [alias["id"] for alias in result["project_aliases"]] == ["exact"]


def test_conflicting_identity_keeps_both_payloads_and_marks_each_row(monkeypatch, tmp_path):
    first = _run("conflicted", tokens=100, dollars=1)
    second = _run("conflicted", tokens=200, dollars=2)
    _sources(monkeypatch, [
        _project("a", tmp_path), _project("b", tmp_path),
    ], {
        ("a", "steward"): [first, second],
        ("b", "steward"): [copy.deepcopy(second)],
    })
    result = steward_routes._other_recorded_usage(str(tmp_path))
    assert len(result["records"]) == 2
    assert {row["tokens"] for row in result["records"]} == {100, 200}
    assert {row["saved_usd"] for row in result["records"]} == {1, 2}
    assert all(row["conflict"] for row in result["records"])
    assert result["conflict_count"] == 1
    assert result["duplicate_count"] == 1
    assert "total" not in result


def test_different_zero_cost_context_is_preserved_as_an_identity_conflict(monkeypatch, tmp_path):
    legacy = _run("same-run")
    explicit = copy.deepcopy(legacy)
    explicit["cost_complete"] = True
    _sources(monkeypatch, [_project("p", tmp_path)], {
        ("p", "steward"): [legacy, explicit],
    })
    result = steward_routes._other_recorded_usage(str(tmp_path))
    assert len(result["records"]) == 2
    assert result["duplicate_count"] == 0
    assert result["conflict_count"] == 1
    assert all(row["conflict"] for row in result["records"])
    assert {row["cost_status"] for row in result["records"]} == {"recorded", "zero_requires_verification"}


def test_identity_fallbacks_do_not_merge_distinct_engine_invocations(monkeypatch, tmp_path):
    session_first = _run("first")
    session_first.pop("engine_session_uuid")
    session_second = copy.deepcopy(session_first)
    session_second["job_id"] = "another-job"
    job_first = _run("job-only")
    job_first.pop("engine_session_uuid")
    job_first.pop("session_id")
    job_second = copy.deepcopy(job_first)
    engine_first = _run("engine-a")
    engine_second = _run("engine-b")
    engine_first["session_id"] = engine_second["session_id"] = "shared-long-session"
    _sources(monkeypatch, [_project("p", tmp_path)], {
        ("p", "steward"): [
            session_first, session_second, job_first, job_second, engine_first, engine_second,
        ],
    })
    result = steward_routes._other_recorded_usage(str(tmp_path))
    assert len(result["records"]) == 4
    assert result["duplicate_count"] == 2
    assert result["conflict_count"] == 0
    assert {row["identity_type"] for row in result["records"]} == {
        "engine_session_uuid", "session_id", "job_id",
    }


def test_zero_cost_needs_explicit_context_and_invalid_values_remain_unavailable(monkeypatch, tmp_path):
    legacy = _run("legacy-zero")
    explicit = _run("explicit-zero")
    explicit["cost"]["cost_complete"] = True
    incomplete = _run("incomplete-zero")
    incomplete["cost"]["cost_complete"] = False
    invalid_context = _run("invalid-context")
    invalid_context["cost"].update({"cost_complete": "true", "cost_state": "", "billing_mode": 0})
    invalid = _run("invalid", tokens=-1, dollars=float("nan"), label={"invalid": "label"}, created_at="yesterday")
    fractional = _run("fractional", tokens=1.5, dollars=float("inf"))
    boolean = _run("boolean", tokens=True, dollars=False)
    discovered = _run("discovered", _discovered=True)
    not_run_cost = _run("planned", kind="plan")
    not_run_cost.pop("cost")  # An unmeasured plan is not a usage record.
    _sources(monkeypatch, [_project("p", tmp_path)], {
        ("p", "steward"): [
            legacy, explicit, incomplete, invalid_context, invalid, fractional, boolean,
            discovered, not_run_cost,
        ],
    })
    result = steward_routes._other_recorded_usage(str(tmp_path))
    rows = {row["identity"]: row for row in result["records"]}
    assert len(rows) == 7
    assert rows["legacy-zero"]["saved_usd"] == 0
    assert rows["legacy-zero"]["cost_zero_requires_verification"] is True
    assert rows["legacy-zero"]["cost_status"] == "zero_requires_verification"
    assert rows["explicit-zero"]["cost_zero_requires_verification"] is False
    assert rows["explicit-zero"]["cost_status"] == "recorded"
    assert rows["incomplete-zero"]["cost_status"] == "partial"
    assert rows["invalid-context"]["cost_zero_requires_verification"] is True
    for identity in ("invalid", "fractional", "boolean"):
        assert rows[identity]["tokens"] is None
        assert rows[identity]["saved_usd"] is None
        assert rows[identity]["cost_status"] == "unavailable"
    assert rows["invalid"]["title"] == "steward run"
    assert "created_at" not in rows["invalid"]
    assert rows["legacy-zero"]["created_at"] == 1789068000


def test_titles_are_readable_bounded_and_missing_identity_is_not_guessed(monkeypatch, tmp_path):
    record = _run("no-identity", label="  A useful\nrun label " + "x" * 200)
    for field in ("engine_session_uuid", "session_id", "job_id"):
        record.pop(field)
    _sources(monkeypatch, [_project("p", tmp_path)], {
        ("p", "steward"): [record, copy.deepcopy(record)],
    })
    result = steward_routes._other_recorded_usage(str(tmp_path))
    assert len(result["records"]) == 2
    assert result["duplicate_count"] == 0
    assert result["records"][0]["identity"] is None
    assert result["records"][0]["title"].startswith("A useful run label")
    assert len(result["records"][0]["title"]) == 160


def test_registry_failure_is_explicit_unavailable_without_exception_details(monkeypatch, tmp_path):
    def unreadable():
        raise OSError("private-path-secret")

    monkeypatch.setattr(rnd_registry, "list_projects", unreadable)
    result = steward_routes._other_recorded_usage(str(tmp_path))
    assert result["status"] == "unavailable"
    assert result["records"] == []
    assert result["unavailable_sources"] == [{"source": "project-registry", "status": "unavailable"}]
    assert "private-path-secret" not in json.dumps(result)


def test_unreadable_lane_keeps_readable_rows_and_marks_partial_coverage(monkeypatch, tmp_path):
    _sources(monkeypatch, [_project("p", tmp_path)], {})

    def partially_unreadable(cdir, project_id, lane):
        if lane == "steward":
            raise OSError("private-lane-path")
        return [_run("readable")]

    monkeypatch.setattr(eh, "list_efforts", partially_unreadable)
    result = steward_routes._other_recorded_usage(str(tmp_path))
    assert result["status"] == "partial"
    assert [row["identity"] for row in result["records"]] == ["readable"]
    assert result["unavailable_sources"] == [{
        "source": "effort-history", "status": "unavailable", "project_id": "p", "lane": "steward",
    }]
    assert "private-lane-path" not in json.dumps(result)
