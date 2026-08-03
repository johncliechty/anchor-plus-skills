"""Wave 3 gate — bridge job cost onto the effort record.

crucible-improve-followup (2026-07-01), Wave 3.

Per-project / per-effort rollups read a `cost` block off the effort
pointer-record. The ONLY writer of that block (`finalize_effort` ->
`attach_cost`) had no production caller, so the runner captured cost onto the
JOB record but never bridged it to the EFFORT record — hence all-zero rollups.
`job_runner._finalize` now bridges the captured cost onto the effort record for
launch_lane jobs (those carrying project_id + folder_path) that captured a
result envelope.
"""
import importlib

import pytest

ENVELOPE = {
    "type": "result",
    "total_cost_usd": 0.42,
    "duration_ms": 5000,
    "usage": {"input_tokens": 100, "output_tokens": 200},
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    for mod in ("paths", "job_runner", "rnd_registry", "session_registry",
                "sessions", "effort_history", "summarizer", "effort_view"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import rnd_registry
    folder = tmp_path / "proj"
    folder.mkdir()
    pid = rnd_registry.add_project("Cost", str(folder), scaffold=False)["id"]
    return {"pid": pid, "folder": str(folder)}


def _job_rec(jid, **over):
    rec = {"job_id": jid, "lane": "research", "status": "running",
           "started_at": 1.0, "exit_code": None, "session_id": None,
           "backend": "claude", "cost": None}
    rec.update(over)
    return rec


def test_finalize_bridges_cost_onto_effort_record(env):
    """The direct fix: a finished launch_lane job stamps its captured cost onto
    the effort pointer-record (previously never written)."""
    import effort_history as eh
    import job_runner as jr
    pid, folder = env["pid"], env["folder"]
    jid = "job-cost-1"
    jr._write_record(_job_rec(jid, project_id=pid, folder_path=folder))
    jr._finalize(jid, 0, result_envelope=ENVELOPE)

    eff = eh.load_effort(folder, pid, "research", jid)
    assert eff is not None, "bridge must create/update the effort record"
    cost = eff.get("cost") or {}
    assert cost.get("total_cost_usd") == 0.42
    assert cost.get("duration_ms") == 5000
    assert (cost.get("total_tokens") or 0) > 0, "tokens must be bridged"


def test_no_project_identity_skips_bridge_without_error(env):
    """A job with no project_id/folder_path (a bare launch()) finalizes exactly
    as before: no bridge, no effort record, no error."""
    import effort_history as eh
    import job_runner as jr
    pid, folder = env["pid"], env["folder"]
    jid = "job-nobridge"
    jr._write_record(_job_rec(jid))  # no project_id / folder_path
    jr._finalize(jid, 0, result_envelope=ENVELOPE)  # must not raise
    assert eh.load_effort(folder, pid, "research", jid) is None


def test_no_cost_envelope_writes_no_effort(env):
    """No result envelope (no captured cost) -> the bridge does not fire (guard
    on rec['cost']); a launch job with no cost is not fabricated as zero-cost."""
    import effort_history as eh
    import job_runner as jr
    pid, folder = env["pid"], env["folder"]
    jid = "job-nocost"
    jr._write_record(_job_rec(jid, project_id=pid, folder_path=folder))
    jr._finalize(jid, 0)  # no envelope -> rec['cost'] stays falsy
    assert eh.load_effort(folder, pid, "research", jid) is None


def test_rollup_nonzero_after_bridge(env):
    """End-to-end, faithful to production: `launch_guarded` stamps
    project_id/folder_path on the job record, then `_finalize` bridges cost onto
    a fresh effort record. That record is RUN-provenance (no source=discovered),
    so `project_effort_rollup` — the real reader — reports non-zero (was always
    0). No pre-seeded effort: the bridge ALONE lights up the rollup."""
    import effort_history as eh
    import job_runner as jr
    pid, folder = env["pid"], env["folder"]
    jid = "job-cost-2"
    jr._write_record(_job_rec(jid, project_id=pid, folder_path=folder))
    jr._finalize(jid, 0, result_envelope=ENVELOPE)

    roll = eh.project_effort_rollup(pid)
    assert roll["tokens"] > 0 and roll["cost_usd"] > 0.0, \
        f"rollup still zero after bridge alone: {roll}"
