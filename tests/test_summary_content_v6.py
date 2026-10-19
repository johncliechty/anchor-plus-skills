"""Wave 1 (v6) — summaries that actually work: content + grounding + heal.

Builds on the parse fix (``job_runner.extract_assistant_text`` + the shared
``summarizer._claims_from_job``) already landed on this branch. These tests drive
the summarizer through the PRODUCTION-shaped stream-json stub
(``tests/stub_streamjson.py``, NDJSON envelopes — NOT bare lines) and assert the
summaries are genuinely INFORMATIVE and REGRESSION-PROOF:

  1. a SESSION summary is non-empty AND carries the skill / prompts / actions
     shape (the deterministic, source-grounded session record),
  2. a PROJECT summary is a non-empty grounded 1-2 sentence objective,
  3. a hallucinated / ungrounded claim is DROPPED by the grounding filter,
  4. a ``SUMMARY_SCHEMA_VERSION``-stale empty cache is a MISS and REGENERATES on
     the actual rescan path (``anchor_gui.discover_and_adopt`` → proactive
     ``summarize_project``), not just a manual force, and
  5. bare-line stub back-compat still parses (the legacy stub path is intact).

Hermetic: temp ``ANCHOR_DATA_DIR``, the stream-json STUB runner via
``ANCHOR_RUNNER_CMD`` — never live ``claude``, never ``:8777`` / real data.
Stdlib only.
"""
import importlib
import json as _json
import time
from pathlib import Path

import pytest

STREAMJSON = (Path(__file__).resolve().parent / "stub_streamjson.py").as_posix()
BARE = (Path(__file__).resolve().parent / "stub_summarizer.py").as_posix()


@pytest.fixture
def mods(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {STREAMJSON}")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    for mod in ("paths", "job_runner", "rnd_registry", "effort_history",
                "sessions", "report_viewer", "brownfield_scan", "summarizer"):
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


def _project_with_identity(rnd, folder):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "CLAUDE.md").write_text(
        "# Anchor\n\n## What this project is\n"
        "Anchor is a productivity system that manages markdown task files for a "
        "researcher, tracking projects, deadlines, and captured ideas.\n",
        encoding="utf-8")
    return rnd.add_project("Anchor", str(folder))["id"]


def _planning_session_with_docs(rnd, eh, sessions, folder):
    """A discovered planning session with two real member docs on disk so a
    grounded claim has a corpus (the proven pattern from the streamjson test)."""
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


# ── (1) session summary: non-empty + skill/prompts/actions shape ─────────────

def test_session_summary_carries_skill_prompts_actions(mods, tmp_path,
                                                       monkeypatch):
    """Through real stream-json, a session summary is non-empty AND the structured
    record carries the skill / prompts / actions shape (Wave 1 content)."""
    jr, eh, rnd, sessions, summ = mods
    folder = tmp_path / "proj"
    pid, session = _planning_session_with_docs(rnd, eh, sessions, folder)

    monkeypatch.setenv(
        "STUB_STREAMJSON_CLAIMS",
        "North Star: cache validated summaries for each session.")
    out = summ.summarize_session(folder, pid, "planning", session)

    # non-empty, grounded claims came through the production envelope parser.
    assert out.get("claims"), "session summary empty through real stream-json"
    assert "validated summaries" in " ".join(out["claims"]).lower()

    # the deterministic source-grounded shape is PRESENT (keys always there;
    # actions is non-empty because the discovered session has member docs).
    assert "skill" in out and "prompts" in out and "actions" in out
    assert isinstance(out["prompts"], list)
    assert isinstance(out["actions"], list)
    assert out["actions"], "actions should list the produced member docs"
    labels = " ".join((a.get("label") or "") for a in out["actions"]).lower()
    assert "master plan" in labels or "implementation plan" in labels

    # the rendered markdown surfaces the Actions section (informative, not blank).
    md = (out.get("markdown") or summ.render_markdown(out)).lower()
    assert "actions & files produced" in md


# ── (2) project summary: non-empty grounded objective ────────────────────────

def test_project_summary_is_grounded_objective(mods, tmp_path, monkeypatch):
    jr, eh, rnd, sessions, summ = mods
    folder = tmp_path / "proj"
    pid = _project_with_identity(rnd, folder)

    objective = ("Anchor is a productivity system that manages markdown task "
                 "files for a researcher, tracking projects and deadlines.")
    monkeypatch.setenv("STUB_STREAMJSON_CLAIMS", objective)

    out = summ.summarize_project(str(folder), pid)
    assert out.get("claims"), "project objective empty through real stream-json"
    assert not out.get("no_grounded_claims")
    text = out["summary_text"].lower()
    assert "productivity system" in text
    # an objective is short prose (1-2 sentences), not a long feature dump.
    assert len(out["claims"]) <= 3


# ── (3) the grounding filter drops a hallucinated / ungrounded claim ──────────

def test_grounding_drops_hallucinated_claim(mods, tmp_path, monkeypatch):
    """Two candidate lines: one grounded in the CLAUDE.md corpus, one a pure
    hallucination whose content terms never appear in the project. The grounding
    filter must KEEP the first and DROP the second (never fabricated)."""
    jr, eh, rnd, sessions, summ = mods
    folder = tmp_path / "proj"
    pid = _project_with_identity(rnd, folder)

    grounded = ("Anchor is a productivity system managing markdown task files "
                "for a researcher.")
    hallucination = ("Quantum cryptocurrency blockchain mining rig overclocks "
                     "gpu hashrate nonces.")
    monkeypatch.setenv("STUB_STREAMJSON_CLAIMS",
                       grounded + "\n" + hallucination)

    out = summ.summarize_project(str(folder), pid)
    joined = " ".join(out.get("claims") or []).lower()
    assert "productivity system" in joined, "grounded claim should survive"
    assert "blockchain" not in joined and "hashrate" not in joined, (
        "ungrounded hallucination must be dropped by the grounding filter")


# ── (4) schema-version-stale empty cache regenerates on the REAL rescan path ──

def test_stale_cache_regenerates_on_rescan(mods, tmp_path, monkeypatch):
    """A pre-fix empty cache (no/old ``schema_version``) is a MISS, and the actual
    rescan path (``anchor_gui.discover_and_adopt`` → proactive
    ``summarize_project``) HEALS it into a real grounded objective — no manual
    force. Confirms the background rescan helper regenerates project summaries."""
    jr, eh, rnd, sessions, summ = mods
    folder = tmp_path / "proj"
    pid = _project_with_identity(rnd, folder)

    # Hand-write the broken legacy cache shape (no schema_version, empty claims).
    d = summ._project_store_dir(str(folder), pid)
    d.mkdir(parents=True, exist_ok=True)
    (d / summ.PROJECT_SUMMARY_JSON).write_text(_json.dumps({
        "project_id": pid, "kind": "project", "claims": [],
        "summary_text": "", "no_grounded_claims": True}), encoding="utf-8")

    # The loader treats the unversioned cache as a MISS (not a stale blank).
    assert summ.load_cached_project(str(folder), pid) is None

    objective = ("Anchor is a productivity system that manages markdown task "
                 "files for a researcher.")
    monkeypatch.setenv("STUB_STREAMJSON_CLAIMS", objective)

    # Drive the REAL rescan path with proactive generation enabled (the live
    # server's behavior) and wait for the background daemon to land the cache.
    import anchor_gui
    importlib.reload(anchor_gui)
    monkeypatch.setattr(anchor_gui, "_PROACTIVE_SUMMARY_ENABLED", True,
                        raising=False)
    report = anchor_gui.discover_and_adopt(pid)
    assert report.get("ok") is not False

    cached = None
    deadline = time.time() + 30
    while time.time() < deadline:
        cached = summ.load_cached_project(str(folder), pid)
        if cached is not None and cached.get("claims"):
            break
        time.sleep(0.1)

    assert cached is not None, "stale cache was not regenerated on rescan"
    assert cached.get("schema_version") == summ.SUMMARY_SCHEMA_VERSION
    assert cached.get("claims"), "rescan healed cache should be non-empty"
    assert not cached.get("no_grounded_claims")
    assert "productivity system" in cached["summary_text"].lower()


# ── (5) bare-line stub back-compat still parses ──────────────────────────────

def test_bare_line_back_compat_still_parses(mods, tmp_path, monkeypatch):
    """The legacy bare-line stub (``stub_summarizer.py`` — verbatim text lines,
    NOT stream-json envelopes) still flows through the shared ``_claims_from_job``
    / ``extract_assistant_text`` parser, so the old non-stream-json stub path
    keeps producing a non-empty grounded summary."""
    jr, eh, rnd, sessions, summ = mods
    folder = tmp_path / "proj"
    pid = _project_with_identity(rnd, folder)

    # Swap to the bare-line stub runner (emits verbatim lines, not envelopes).
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {BARE}")
    monkeypatch.setenv(
        "STUB_SUMMARIZER_CLAIMS",
        "Anchor is a productivity system that manages markdown task files.")

    out = summ.summarize_project(str(folder), pid, force=True)
    assert out.get("claims"), "bare-line back-compat produced an empty summary"
    assert "productivity system" in out["summary_text"].lower()
