"""Wave 1 — the two-stage Gandalf engine + store + index.

Hermetic: temp ANCHOR_DATA_DIR (job records), a temp project folder (the
artifacts live at PROJECT ROOT ``gandalf/run-<ts>/``; the index under
``.anchor/projects/<id>/gandalf/index.json``), BOTH seams stubbed —
``ANCHOR_RUNNER_CMD`` → ``stub_gandalf_draft.py`` (a canned RAW draft in a
result envelope) and ``ANCHOR_GANDALF_HOST_CMD`` → ``stub_gandalf_host.py`` (a
canned GRADED advisor-output.json). NEVER real claude / real node / :8777.
Stdlib only.
"""
import importlib
import json
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
DRAFT_STUB = (_TESTS / "stub_gandalf_draft.py").as_posix()
HOST_STUB = (_TESTS / "stub_gandalf_host.py").as_posix()


@pytest.fixture
def gandalf(tmp_path, monkeypatch):
    """A fresh gandalf module wired to the two stubs + a temp data dir."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data_dir))
    # Stage A: the runner stub emits a canned RAW draft.
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"{sys.executable} {DRAFT_STUB}")
    # Stage B: the host stub reads stdin, emits a canned GRADED output.
    monkeypatch.setenv("ANCHOR_GANDALF_HOST_CMD",
                       f"{sys.executable} {HOST_STUB}")
    # Proactive summary OFF; no real skill dir needed (SKILL.md is read
    # best-effort and degrades to a bare protocol when absent).
    monkeypatch.setenv("ANCHOR_PROACTIVE_SUMMARY", "")
    monkeypatch.setenv("ANCHOR_GANDALF_SKILL_DIR", str(tmp_path / "no-skill"))
    # This suite exercises the LEGACY map-reduce/grade path (the retained
    # fallback); the DEFAULT is now the agentic canonical-skill run.
    monkeypatch.setenv("ANCHOR_GANDALF_MODE", "mapreduce")
    import paths
    importlib.reload(paths)
    import job_runner
    importlib.reload(job_runner)
    import summarizer
    importlib.reload(summarizer)
    import gandalf
    yield importlib.reload(gandalf)


@pytest.fixture
def project(tmp_path):
    folder = tmp_path / "proj"
    folder.mkdir()
    (folder / "README.md").write_text("# A project\n", encoding="utf-8")
    return folder, "pid-1"


# ── happy path ───────────────────────────────────────────────────────────────

def test_run_creates_artifacts_and_index(gandalf, project):
    folder, pid = project
    out = gandalf.run_gandalf(str(folder), pid)
    assert out["ok"] is True
    run_id = out["run_id"]

    run_dir = folder / "gandalf" / run_id
    assert (run_dir / "report.md").is_file()
    assert (run_dir / "exec-summary.md").is_file()
    advisor = run_dir / "advisor-output.json"
    assert advisor.is_file()
    graded = json.loads(advisor.read_text(encoding="utf-8"))
    # The 9 required top-level keys survived the host → store round-trip.
    for k in ("schema_version", "cross_model", "degraded", "reasoning",
              "verdict", "findings", "nitpicks", "elevations", "risk_labels"):
        assert k in graded

    # The internal index lives under .anchor (NOT served) and has one record.
    idx = folder / ".anchor" / "projects" / pid / "gandalf" / "index.json"
    assert idx.is_file()
    runs = json.loads(idx.read_text(encoding="utf-8"))
    assert isinstance(runs, list) and len(runs) == 1
    assert runs[0]["run_id"] == run_id

    listed = gandalf.list_runs(str(folder), pid)
    assert len(listed) == 1
    rec = listed[0]
    assert rec["ok"] is True
    assert rec["verdict"]  # cleaned top-level verdict, non-empty
    assert rec["report_rel"] == f"gandalf/{run_id}/report.md"
    assert rec["exec_rel"] == f"gandalf/{run_id}/exec-summary.md"


def test_list_runs_safe_projection_no_absolute_paths(gandalf, project):
    folder, pid = project
    gandalf.run_gandalf(str(folder), pid)
    for rec in gandalf.list_runs(str(folder), pid):
        for v in rec.values():
            if isinstance(v, str):
                # No absolute paths leak (no drive prefix / leading slash).
                assert not v.startswith("/")
                assert ":\\" not in v
                assert str(folder) not in v


def test_one_line_verdict_is_cleaned_top_level_verdict(gandalf, project):
    folder, pid = project
    out = gandalf.run_gandalf(str(folder), pid)
    # The stub host's default verdict text, cleaned by short_summary_text.
    assert "broadly sound" in out["verdict"]
    assert out["degraded"] is False  # the stub host did not compute degradation
    assert out["cross_model"] is False


def test_degraded_and_cross_model_carried_from_graded(gandalf, project,
                                                      monkeypatch):
    folder, pid = project
    monkeypatch.setenv("STUB_GANDALF_HOST_DEGRADED", "1")
    monkeypatch.setenv("STUB_GANDALF_HOST_CROSSMODEL", "1")
    out = gandalf.run_gandalf(str(folder), pid)
    assert out["ok"] is True
    assert out["degraded"] is True
    assert out["cross_model"] is True
    rec = gandalf.list_runs(str(folder), pid)[0]
    assert rec["degraded"] is True
    assert rec["cross_model"] is True


# ── accumulation + first-scan idempotence ────────────────────────────────────

def test_second_run_appends_newest_first(gandalf, project):
    folder, pid = project
    first = gandalf.run_gandalf(str(folder), pid)
    second = gandalf.run_gandalf(str(folder), pid)
    runs = gandalf.list_runs(str(folder), pid)
    assert len(runs) == 2
    # Newest-first: the second run is index 0.
    assert runs[0]["run_id"] == second["run_id"]
    assert runs[1]["run_id"] == first["run_id"]


def test_if_absent_noops_when_a_run_exists(gandalf, project):
    folder, pid = project
    gandalf.run_gandalf(str(folder), pid)
    out = gandalf.run_gandalf_if_absent(str(folder), pid)
    assert out.get("skipped") is True
    assert len(gandalf.list_runs(str(folder), pid)) == 1


def test_if_absent_runs_when_none_exist(gandalf, project):
    folder, pid = project
    out = gandalf.run_gandalf_if_absent(str(folder), pid)
    assert out["ok"] is True
    assert out.get("skipped") is not True
    assert len(gandalf.list_runs(str(folder), pid)) == 1


# ── honest degrade paths ─────────────────────────────────────────────────────

def test_stage_a_unparseable_draft_is_error_run(gandalf, project, monkeypatch):
    folder, pid = project
    monkeypatch.setenv("STUB_GANDALF_DRAFT", "UNPARSEABLE")
    out = gandalf.run_gandalf(str(folder), pid)
    assert out["ok"] is False
    assert out.get("reason")
    assert "unparseable" in out["reason"]
    # An honest error row is still recorded so the tab can show it.
    runs = gandalf.list_runs(str(folder), pid)
    assert len(runs) == 1
    assert runs[0]["ok"] is False
    assert runs[0]["report_rel"] is None  # no dead links
    assert runs[0]["verdict"] == ""       # no fabricated verdict


def test_stage_b_host_failure_is_error_run(gandalf, project, monkeypatch):
    folder, pid = project
    monkeypatch.setenv("STUB_GANDALF_HOST_FAIL", "1")
    out = gandalf.run_gandalf(str(folder), pid)
    assert out["ok"] is False
    assert "host-nonzero-exit" in (out.get("reason") or "")
    runs = gandalf.list_runs(str(folder), pid)
    assert runs[0]["ok"] is False
    assert runs[0]["report_rel"] is None


def test_stage_b_unparseable_output_is_error_run(gandalf, project, monkeypatch):
    folder, pid = project
    monkeypatch.setenv("STUB_GANDALF_HOST_BADJSON", "1")
    out = gandalf.run_gandalf(str(folder), pid)
    assert out["ok"] is False
    assert "unparseable" in (out.get("reason") or "")


def test_absent_host_is_honest_error(gandalf, project, monkeypatch):
    folder, pid = project
    # Point the host seam at a nonexistent executable → host-unavailable.
    monkeypatch.setenv("ANCHOR_GANDALF_HOST_CMD",
                       "this-binary-does-not-exist-anchor-gandalf")
    out = gandalf.run_gandalf(str(folder), pid)
    assert out["ok"] is False
    assert out.get("reason") in ("host-unavailable", "host-spawn-failed")


def test_run_gandalf_never_raises(gandalf, project, monkeypatch):
    folder, pid = project
    # Even a totally broken runner cmd must degrade, not raise.
    monkeypatch.setenv("ANCHOR_RUNNER_CMD",
                       "this-runner-does-not-exist-anchor-gandalf")
    out = gandalf.run_gandalf(str(folder), pid)
    assert out["ok"] is False


# ── balanced-JSON extraction unit ────────────────────────────────────────────

def test_last_balanced_json_picks_last_object(gandalf):
    text = ('Some preamble {"a": 1} and then the real draft '
            '{"reasoning": "r", "verdict": "v", "findings": [], '
            '"nitpicks": [], "elevations": []}')
    obj = gandalf._last_balanced_json(text)
    assert obj["verdict"] == "v"


def test_last_balanced_json_ignores_braces_in_strings(gandalf):
    text = '{"verdict": "a } brace inside a string", "ok": true}'
    obj = gandalf._last_balanced_json(text)
    assert obj["verdict"] == "a } brace inside a string"


def test_last_balanced_json_none_on_no_object(gandalf):
    assert gandalf._last_balanced_json("no json here at all") is None


# ── Wave 1 ContextSizer & Dynamic Router ──────────────────────────────────────

def test_scan_project_context_respects_anchorignore(gandalf, tmp_path):
    folder = tmp_path / "context_proj"
    folder.mkdir()
    
    # Create some files with known content size
    (folder / "file1.txt").write_text("12345678", encoding="utf-8") # 8 bytes
    (folder / "file2.log").write_text("1234567890", encoding="utf-8") # 10 bytes
    
    # Create ignored files
    (folder / ".git").mkdir()
    (folder / ".git" / "gitfile").write_text("1234567890", encoding="utf-8")
    
    (folder / "node_modules").mkdir()
    (folder / "node_modules" / "modfile").write_text("1234567890", encoding="utf-8")
    
    # Create .anchorignore
    (folder / ".anchorignore").write_text("*.log\n# comment\n", encoding="utf-8")
    
    # Total non-ignored bytes = 8 bytes (file1.txt). file2.log is ignored by .anchorignore.
    # .git/gitfile and node_modules/modfile are ignored by default skip logic.
    val = gandalf.scan_project_context(str(folder))
    assert val == 8 / 4.0 # 2.0


def test_dynamic_router_overrides_when_exceeds_max(gandalf, project, monkeypatch):
    folder, pid = project
    
    # Set ANCHOR_FRONTIER_MAX to a very small value to force override
    monkeypatch.setenv("ANCHOR_FRONTIER_MAX", "1")
    
    # Let's inspect the launched environment in test by monkeypatching job_runner.launch
    launched_envs = []
    orig_launch = gandalf._jr.launch
    def mock_launch(*args, **kwargs):
        # Capture env
        launched_envs.append(kwargs.get("env"))
        return orig_launch(*args, **kwargs)
    
    monkeypatch.setattr(gandalf._jr, "launch", mock_launch)
    
    out = gandalf.run_gandalf(str(folder), pid)
    assert out["ok"] is True
    
    assert len(launched_envs) == 1
    env = launched_envs[0]
    assert env is not None
    # 2026-07-02: the over-cap tier is the CURRENT strong long-context model
    # (gemini-1.5-pro is retired — a dead id that failed every over-cap shard).
    assert env.get("GEMINI_MODEL") == "gemini-3.1-pro"
    assert env.get("TRIO_MODEL") == "gemini-3.1-pro"


def test_dynamic_router_no_override_under_max(gandalf, project, monkeypatch):
    folder, pid = project
    
    # Set ANCHOR_FRONTIER_MAX to a very large value to prevent override
    monkeypatch.setenv("ANCHOR_FRONTIER_MAX", "1000000")
    
    launched_envs = []
    orig_launch = gandalf._jr.launch
    def mock_launch(*args, **kwargs):
        launched_envs.append(kwargs.get("env"))
        return orig_launch(*args, **kwargs)
        
    monkeypatch.setattr(gandalf._jr, "launch", mock_launch)
    
    out = gandalf.run_gandalf(str(folder), pid)
    assert out["ok"] is True
    
    assert len(launched_envs) == 1
    env = launched_envs[0]
    if env is not None:
        assert env.get("GEMINI_MODEL") is None
        assert env.get("TRIO_MODEL") is None


def test_gandalf_finally_reset(gandalf, project, monkeypatch):
    """An exception inside run_gandalf still leaves the registry record failed (finally-reset)."""
    folder, pid = project
    # Mock scan_project_context to raise an exception
    def broken_scan(*args, **kwargs):
        raise RuntimeError("Simulated crash")
    monkeypatch.setattr(gandalf, "scan_project_context", broken_scan)
    
    import session_registry
    
    # Execute
    with pytest.raises(RuntimeError):
        gandalf.run_gandalf(str(folder), pid)
        
    # Verify that the session registered was updated off STATUS_RUNNING
    runs = session_registry.list_sessions(project_id=pid)
    assert len(runs) == 1
    assert runs[0]["status"] == session_registry.STATUS_FAILED


def test_gandalf_index_cap(gandalf, project):
    """_append_index enforces the cap (newest N)."""
    folder, pid = project
    # Run 25 times
    for i in range(25):
        gandalf.run_gandalf(str(folder), pid)
    # Verify only 20 runs remain in list
    runs = gandalf.list_runs(str(folder), pid)
    assert len(runs) == 20


def test_gandalf_cancel(gandalf, project, monkeypatch):
    """cancel_run terminates the in-flight run and updates registry + index to cancelled."""
    folder, pid = project
    import time
    import threading
    import job_runner
    import session_registry
    
    # Mock wait to sleep to simulate long Stage A execution
    def slow_wait(jid, timeout=None):
        time.sleep(10)
        return {"status": "done"}
    monkeypatch.setattr(job_runner, "wait", slow_wait)
    
    run_id_holder = []
    
    def run_thread():
        out = gandalf.run_gandalf(str(folder), pid)
        run_id_holder.append(out)
        
    # daemon=True so this thread can NEVER block interpreter shutdown: cancel_run
    # cannot interrupt the mocked uninterruptible time.sleep, so the thread is
    # still alive after the 5s join; a non-daemon thread would then hang the
    # interpreter at exit until the gate's wall timeout killed it (exit_code null,
    # not green). The assertions read the registry (updated synchronously by
    # cancel_run on the main thread), so abandoning the thread is sound.
    t = threading.Thread(target=run_thread, daemon=True)
    t.start()
    
    # Wait for the run_id to be registered and active
    active_id = None
    for _ in range(50):
        time.sleep(0.05)
        with gandalf._ACTIVE_RUNS_LOCK:
            if gandalf._ACTIVE_RUNS:
                active_id = list(gandalf._ACTIVE_RUNS.keys())[0]
                break
    assert active_id is not None
    
    # Call cancel
    assert gandalf.cancel_run(active_id) is True
    
    # Wait for the thread to finish
    t.join(timeout=5)
    
    # Verify status in session_registry is cancelled
    rec = session_registry.get_session(active_id)
    assert rec["status"] == "cancelled"
    
    # Verify index record is cancelled
    runs = gandalf.list_runs(str(folder), pid)
    assert len(runs) == 1
    assert runs[0]["ok"] is False
    assert "cancelled" in runs[0]["reason"]

