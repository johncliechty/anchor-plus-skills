"""Regression guard: the summarizer must extract text from REAL stream-json.

This closes the test gap that shipped the v5 summary bug. Production runs
``claude -p --output-format stream-json``, whose stdout is NDJSON envelopes —
the model's text lives in ``{"type":"assistant",...}`` frames + the terminal
``{"type":"result","result":...}`` envelope, NOT as bare lines. The old
summarizer parser skipped every ``{"type":...}`` line and so produced an EMPTY
summary for every real project (every cached ``project-summary.json`` on disk had
``claims: []`` / ``no_grounded_claims: true``). The bug was invisible because the
existing stubs emit BARE lines, which the old parser happened to keep.

Two layers:
  1. unit tests of ``job_runner.extract_assistant_text`` (envelope shapes +
     bare-line back-compat) — fast, no subprocess.
  2. an end-to-end ``summarize_project`` driven through ``stub_streamjson.py``
     (real envelope shape) asserting a NON-EMPTY grounded objective — this test
     is RED against the pre-fix parser.

Hermetic: temp ANCHOR_DATA_DIR, the stream-json STUB runner, never :8777 / real
data. Stdlib only.
"""
import importlib
from pathlib import Path

import pytest

STREAMJSON = (Path(__file__).resolve().parent / "stub_streamjson.py").as_posix()


# ── (1) unit: extract_assistant_text against real envelope shapes ────────────

@pytest.fixture
def jr(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    import paths
    importlib.reload(paths)
    import job_runner
    yield importlib.reload(job_runner)


def _assistant(text):
    return ('{"type":"assistant","message":{"role":"assistant","content":'
            '[{"type":"text","text":%s}]},"session_id":"s"}' % _json(text))


def _json(s):
    import json
    return json.dumps(s)


def test_extract_prefers_result_envelope(jr):
    lines = [
        '{"type":"system","subtype":"init","session_id":"s"}',
        _assistant("partial streamed text"),
        '{"type":"result","subtype":"success","result":'
        '"Final line one\\nFinal line two","total_cost_usd":0.1,'
        '"usage":{"input_tokens":3,"output_tokens":5},"session_id":"s"}',
    ]
    out = jr.extract_assistant_text(lines)
    assert out == ["Final line one", "Final line two"]


def test_extract_falls_back_to_assistant_frames(jr):
    # No result envelope → assemble the assistant text blocks.
    lines = [
        '{"type":"system","subtype":"init"}',
        _assistant("Objective sentence about the project."),
    ]
    out = jr.extract_assistant_text(lines)
    assert out == ["Objective sentence about the project."]


def test_extract_ignores_non_text_envelopes(jr):
    lines = [
        '{"type":"system","subtype":"init"}',
        '{"type":"tool_use","name":"Read","input":{"path":"x"}}',
        '{"type":"result","subtype":"success","result":"Only real text"}',
    ]
    assert jr.extract_assistant_text(lines) == ["Only real text"]


def test_extract_bare_lines_back_compat(jr):
    # The existing stubs emit bare lines — those must still come through verbatim
    # (minus blank lines), so all the legacy stub-driven tests keep working.
    lines = ["claim one", "", "  claim two  "]
    assert jr.extract_assistant_text(lines) == ["claim one", "claim two"]


def test_extract_empty_on_no_text(jr):
    assert jr.extract_assistant_text([]) == []
    assert jr.extract_assistant_text(['{"type":"system","subtype":"init"}']) == []


# ── (2) end-to-end: summarize_project through REAL stream-json output ────────

@pytest.fixture
def mods(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {STREAMJSON}")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    for mod in ("paths", "job_runner", "rnd_registry", "effort_history",
                "sessions", "report_viewer", "summarizer"):
        importlib.reload(importlib.import_module(mod))
    import job_runner, effort_history, rnd_registry, sessions, summarizer
    yield job_runner, effort_history, rnd_registry, sessions, summarizer
    for rec in job_runner.list_records():
        if rec.get("status") == job_runner.STATUS_RUNNING:
            try:
                job_runner.cancel(rec["job_id"])
            except Exception:
                pass
    job_runner._reset_live_table_for_tests()


def _project(rnd, folder):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "CLAUDE.md").write_text(
        "# Anchor\n\n## What this project is\n"
        "Anchor is a productivity system that manages markdown task files for a "
        "researcher, tracking projects, deadlines, and captured ideas.\n",
        encoding="utf-8")
    return rnd.add_project("Anchor", str(folder))["id"]


def test_project_summary_nonempty_through_stream_json(mods, tmp_path, monkeypatch):
    """The whole point: with PRODUCTION-shaped stream-json output, the project
    summary is NON-EMPTY and grounded. RED against the old skip-all-envelopes
    parser (which yielded claims:[] / no_grounded_claims:true)."""
    jr, eh, rnd, sessions, summ = mods
    folder = tmp_path / "proj"
    pid = _project(rnd, folder)

    objective = ("Anchor is a productivity system that manages markdown task "
                 "files for a researcher, tracking projects and deadlines.")
    monkeypatch.setenv("STUB_STREAMJSON_CLAIMS", objective)

    out = summ.summarize_project(str(folder), pid)
    assert out.get("claims"), "objective summary empty through real stream-json"
    assert not out.get("no_grounded_claims")
    assert "productivity system" in out["summary_text"].lower()
    # and it is cached (read path serves it without re-running the model).
    cached = summ.load_cached_project(str(folder), pid)
    assert cached and cached["summary_text"] == out["summary_text"]


def test_old_version_cache_is_a_miss_and_regenerates(mods, tmp_path, monkeypatch):
    """A stale, EMPTY, unversioned cache (exactly the on-disk state the parser bug
    left behind) is treated as a MISS so it regenerates into a real summary
    instead of being served forever as a blank."""
    import json as _json
    jr, eh, rnd, sessions, summ = mods
    folder = tmp_path / "proj"
    pid = _project(rnd, folder)
    # Hand-write the broken legacy cache shape (no schema_version, empty claims).
    d = summ._project_store_dir(str(folder), pid)
    d.mkdir(parents=True, exist_ok=True)
    (d / summ.PROJECT_SUMMARY_JSON).write_text(_json.dumps({
        "project_id": pid, "kind": "project", "claims": [],
        "summary_text": "", "no_grounded_claims": True}), encoding="utf-8")

    # The loader ignores the unversioned cache → a miss (not a stale blank).
    assert summ.load_cached_project(str(folder), pid) is None

    # summarize_project therefore regenerates a real, versioned summary.
    monkeypatch.setenv("STUB_STREAMJSON_CLAIMS",
                       "Anchor is a productivity system that manages markdown "
                       "task files for a researcher.")
    out = summ.summarize_project(str(folder), pid)
    assert out.get("claims")
    cached = summ.load_cached_project(str(folder), pid)
    assert cached and cached.get("schema_version") == summ.SUMMARY_SCHEMA_VERSION


def _planning_session_with_docs(rnd, eh, sessions, folder):
    """A discovered planning session with two real member docs on disk (the
    proven pattern from test_summarizer) so a grounded claim has a corpus."""
    folder.mkdir(parents=True, exist_ok=True)
    bd = folder / "planning" / "brownfield-discovery"
    bd.mkdir(parents=True, exist_ok=True)
    (bd / "MASTER-PLAN.md").write_text(
        "# Brownfield Master Plan\n\n## North Star\n"
        "Make the surface a truthful memory of trio work.\n\n"
        "## Key decisions\nGroup efforts into sessions and cache validated "
        "summaries.\n", encoding="utf-8")
    (bd / "IMPLEMENTATION-PLAN.md").write_text(
        "# Implementation Plan\n\n## Goal\nRender the most-recent session with an "
        "expander.\n", encoding="utf-8")
    pid = rnd.add_project("Anchor", str(folder))["id"]
    import brownfield_scan
    eh.adopt_discovered(folder, pid, brownfield_scan.scan(str(folder)))
    for s in sessions.list_sessions(folder, pid, "planning"):
        rels = [m.get("artifact_path", "") for m in s.get("member_files", [])]
        if any("brownfield-discovery" in r for r in rels):
            return pid, s
    raise AssertionError("expected a discovered planning session")


def test_session_summary_nonempty_through_stream_json(mods, tmp_path, monkeypatch):
    """The same parser repairs session summaries (shared ``_claims_from_job``)."""
    jr, eh, rnd, sessions, summ = mods
    folder = tmp_path / "proj"
    pid, session = _planning_session_with_docs(rnd, eh, sessions, folder)

    monkeypatch.setenv("STUB_STREAMJSON_CLAIMS",
                       "North Star: cache validated summaries for each session.")
    out = summ.summarize_session(folder, pid, "planning", session)
    assert out.get("claims"), "session summary empty through real stream-json"
    assert "validated summaries" in " ".join(out["claims"]).lower()
