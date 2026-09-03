"""Gandalf AGENTIC engine — STUB GATE (2026-07-07).

The tile now runs the CANONICAL skill agentically instead of the homegrown Python
map-reduce: ONE background Claude job runs `gandalf`/`gandalf-heavy` over the folder
(the skill decides map-reduce + runs its own 5:1 + writes the report); Anchor
captures the report + a printed summary/verdict into the SAME index/artifact
contract the tile reads. The legacy map-reduce stays behind ANCHOR_GANDALF_MODE.

Locked acceptance:
  - agentic (default) launches exactly ONE job, NOT sharded, with write permission
    (acceptEdits, not read-only plan), the tier env, and a prompt that names the
    skill + objective + the report path;
  - the produced report + VERDICT: line are captured (report_rel/exec_rel/verdict),
    record shape intact;
  - heavy → prompt says "gandalf-heavy" + env ANTHROPIC_MODEL=claude-fable-5,
    TRIO_TIER=heavy, CRUCIBLE_AGENT_LIVE=1;
  - no report + empty output → honest ok=false (never fabricated);
  - a skill-emitted advisor-output.json is honored (cross_model chip);
  - ANCHOR_GANDALF_MODE=mapreduce falls back to the legacy path.

Hermetic + fully stubbed: temp data dir, ANCHOR_RUNNER_CMD → stub_gandalf_agentic.
NEVER real claude / node / :8777.
"""
import importlib
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
AGENTIC_STUB = (_TESTS / "stub_gandalf_agentic.py").as_posix()
DRAFT_STUB = (_TESTS / "stub_gandalf_draft.py").as_posix()
HOST_STUB = (_TESTS / "stub_gandalf_host.py").as_posix()


@pytest.fixture
def gandalf(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data_dir))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"{sys.executable} {AGENTIC_STUB}")
    monkeypatch.setenv("ANCHOR_PROACTIVE_SUMMARY", "")
    monkeypatch.setenv("ANCHOR_GANDALF_SKILL_DIR", str(tmp_path / "no-skill"))
    monkeypatch.delenv("ANCHOR_GANDALF_MODE", raising=False)  # default = agentic
    monkeypatch.delenv("STUB_GANDALF_AGENTIC_NOREPORT", raising=False)
    monkeypatch.delenv("STUB_GANDALF_AGENTIC_ADVISOR", raising=False)
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
    (folder / "src").mkdir(parents=True)
    (folder / "src" / "a.py").write_text("print('a')\n", encoding="utf-8")
    (folder / "docs").mkdir()
    (folder / "docs" / "x.md").write_text("# doc\n", encoding="utf-8")
    return folder, "pid-ag"


def _spy(gandalf, monkeypatch):
    calls = []
    orig = gandalf._jr.launch

    def spy(*a, **k):
        calls.append({"args": a, "kwargs": k})
        return orig(*a, **k)

    monkeypatch.setattr(gandalf._jr, "launch", spy)
    return calls


# ── ONE agentic job, not sharded, write-capable, skill-named prompt ──────────

def test_agentic_launches_one_job_named_skill(gandalf, project, monkeypatch):
    folder, pid = project
    calls = _spy(gandalf, monkeypatch)
    out = gandalf.run_gandalf(str(folder), pid, tier="heavy")
    assert out["ok"] is True
    # Exactly ONE launch — the canonical single agentic run, not per-shard fan-out.
    assert len(calls) == 1, f"expected ONE agentic job, got {len(calls)}"
    k = calls[0]["kwargs"]
    assert k.get("permission_mode") == "bypassPermissions", "must be write-capable, not read-only"
    prompt = k.get("prompt") or ""
    assert "gandalf-heavy" in prompt, "heavy run must invoke the gandalf-heavy skill"
    assert str(folder) in prompt and "exact path:" in prompt
    # A regular run names the plain skill.
    calls2 = _spy(gandalf, monkeypatch)
    gandalf.run_gandalf(str(folder), pid, tier="standard")
    p2 = calls2[0]["kwargs"].get("prompt") or ""
    assert "gandalf-heavy" not in p2 and "gandalf" in p2


def test_agentic_captures_report_and_verdict(gandalf, project):
    folder, pid = project
    out = gandalf.run_gandalf(str(folder), pid, tier="standard")
    assert out["ok"] is True
    assert out["report_rel"] and out["report_rel"].endswith("report.md")
    assert out["exec_rel"] and out["exec_rel"].endswith("exec-summary.md")
    assert "durability gap" in out["verdict"].lower()
    # The report the skill wrote is on disk under the run dir.
    run_dir = gandalf._runs_dir(str(folder)) / out["run_id"]
    assert (run_dir / "report.md").is_file()
    assert (run_dir / "exec-summary.md").is_file()


def test_agentic_tier_env(gandalf, project, monkeypatch):
    folder, pid = project
    calls = _spy(gandalf, monkeypatch)
    gandalf.run_gandalf(str(folder), pid, tier="heavy")
    env = calls[0]["kwargs"].get("env") or {}
    assert env.get("ANTHROPIC_MODEL") == "claude-fable-5"
    assert env.get("TRIO_TIER") == "heavy"
    assert env.get("CRUCIBLE_AGENT_LIVE") == "1", "the skill's live 5:1 must be enabled"


def test_agentic_done_with_prose_but_no_report_is_honest_failure(gandalf, project,
                                                                 monkeypatch):
    """A finished run that printed a full summary + VERDICT but wrote NO report is
    an HONEST failure — a green tile REQUIRES a real report (swarm finding)."""
    folder, pid = project
    monkeypatch.setenv("STUB_GANDALF_AGENTIC_NOREPORT", "1")
    out = gandalf.run_gandalf(str(folder), pid, tier="standard")
    assert out["ok"] is False
    assert out.get("reason") == "no-report-produced"
    runs = gandalf.list_runs(str(folder), pid)
    assert runs and runs[0]["ok"] is False and runs[0]["status"] == "failed"


def test_agentic_empty_report_is_honest_failure(gandalf, project, monkeypatch):
    """A zero-byte report.md cannot count as a successful read."""
    folder, pid = project
    monkeypatch.setenv("STUB_GANDALF_AGENTIC_EMPTY_REPORT", "1")
    out = gandalf.run_gandalf(str(folder), pid, tier="standard")
    assert out["ok"] is False and out.get("reason") == "no-report-produced"


def test_agentic_timeout_treekills_and_fails_honestly(gandalf, project, monkeypatch):
    """SWARM SAFETY: a non-terminal (timed-out / still-running) job is TREE-KILLED
    and recorded as an honest failure — never ok=true, never an orphaned swarm."""
    folder, pid = project
    killed = []
    monkeypatch.setattr(gandalf._jr, "cancel",
                        lambda jid: killed.append(jid) or {"ok": True})
    # Force the post-wait status to look still-running (a timeout that _jr.wait
    # bounded but did not kill).
    orig_load = gandalf._jr.load_record
    monkeypatch.setattr(gandalf._jr, "load_record",
                        lambda jid: {**(orig_load(jid) or {}), "status": "running"})
    # This test intentionally holds the synthetic job in a non-terminal state.
    # Bound that simulated timeout explicitly instead of inheriting the
    # production Heavy ceiling (900s x 2.5).
    monkeypatch.setenv("ANCHOR_GANDALF_TIMEOUT_HEAVY", "0.05")
    out = gandalf.run_gandalf(str(folder), pid, tier="heavy")
    assert out["ok"] is False
    assert str(out.get("reason") or "").startswith("agentic-run-incomplete")
    assert killed, "a non-terminal agentic job MUST be tree-killed (no orphan swarm)"


def test_agentic_launch_failure_falls_back_to_mapreduce(gandalf, project, monkeypatch):
    """On a Claude-absent host the agentic launch fails; run_gandalf falls back to
    the legacy map-reduce path so a read is still produced (honest degrade)."""
    folder, pid = project
    monkeypatch.setattr(gandalf, "_run_stage_agentic",
                        lambda *a, **k: {"ok": False, "reason": "launch-failed"})
    # Provide the map-reduce stubs so the fallback path can complete.
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"{sys.executable} {DRAFT_STUB}")
    monkeypatch.setenv("ANCHOR_GANDALF_HOST_CMD", f"{sys.executable} {HOST_STUB}")
    monkeypatch.setenv("ANCHOR_GANDALF_FUSION", "0")
    import job_runner
    importlib.reload(job_runner)
    g = importlib.reload(gandalf)
    g._run_stage_agentic = lambda *a, **k: {"ok": False, "reason": "launch-failed"}
    out = g.run_gandalf(str(folder), pid, tier="standard")
    assert out["ok"] is True, "must fall back to map-reduce when Claude is unavailable"


def test_inline_verdict_is_parsed(gandalf):
    v, s = gandalf._parse_agentic_summary(
        "The project is sound. VERDICT: broadly healthy.")
    assert v == "broadly healthy."
    assert "VERDICT" not in s and "The project is sound." in s
    # markdown-bolded, on its own line
    v2, _ = gandalf._parse_agentic_summary("prose\n**VERDICT:** ship it")
    assert v2 == "ship it"


def test_agentic_honors_skill_advisor_json(gandalf, project, monkeypatch):
    folder, pid = project
    monkeypatch.setenv("STUB_GANDALF_AGENTIC_ADVISOR", "1")
    out = gandalf.run_gandalf(str(folder), pid, tier="heavy")
    assert out["ok"] is True
    assert out["cross_model"] is True, "a graded envelope's cross_model must be honored"
    assert out["advisor_rel"] and out["advisor_rel"].endswith("advisor-output.json")


def test_record_shape_and_tier_intact(gandalf, project):
    folder, pid = project
    gandalf.run_gandalf(str(folder), pid, tier="heavy")
    runs = gandalf.list_runs(str(folder), pid)
    r = runs[0]
    for key in ("run_id", "ts", "ok", "verdict", "report_rel", "exec_rel",
                "status", "in_progress", "tier"):
        assert key in r
    assert r["tier"] == "heavy" and r["status"] == "done"


# ── legacy fallback still works ──────────────────────────────────────────────

def test_mapreduce_fallback(gandalf, project, monkeypatch):
    folder, pid = project
    monkeypatch.setenv("ANCHOR_GANDALF_MODE", "mapreduce")
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"{sys.executable} {DRAFT_STUB}")
    monkeypatch.setenv("ANCHOR_GANDALF_HOST_CMD", f"{sys.executable} {HOST_STUB}")
    monkeypatch.setenv("ANCHOR_GANDALF_FUSION", "0")
    import importlib
    import job_runner
    importlib.reload(job_runner)
    g = importlib.reload(gandalf)
    out = g.run_gandalf(str(folder), pid, tier="standard")
    assert out["ok"] is True, "legacy map-reduce fallback must still produce a read"
    # The fallback must produce the SAME record contract the tile reads (finding #8).
    assert out["report_rel"] and out["report_rel"].endswith("report.md")
    assert out["exec_rel"] and out["exec_rel"].endswith("exec-summary.md")
    runs = g.list_runs(str(folder), pid)
    assert runs and runs[0]["status"] == "done" and runs[0]["tier"] == "standard"
    run_dir = g._runs_dir(str(folder)) / out["run_id"]
    assert (run_dir / "report.md").is_file()
