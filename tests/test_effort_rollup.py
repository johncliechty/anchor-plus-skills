"""v4 Wave 3 — project cost/tokens/time rollup
(``effort_history.project_effort_rollup``).

Sums ``job_runner`` cost records for the project's RUN-provenance sessions only;
imported/discovered sessions contribute 0 (never fabricated). ``window='30d'``
excludes records older than 30 days relative to an injected ``now`` (deterministic).

Temp ANCHOR_DATA_DIR; no live claude, no real data, never :8777.
"""
import importlib

import pytest


@pytest.fixture
def mods(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    import paths
    importlib.reload(paths)
    import rnd_registry
    importlib.reload(rnd_registry)
    import effort_history
    importlib.reload(effort_history)
    import sessions
    importlib.reload(sessions)
    return rnd_registry, effort_history, sessions


def _project(rnd, folder, name="P"):
    folder.mkdir(parents=True, exist_ok=True)
    return rnd.add_project(name, str(folder))


def _run_effort(eh, folder, pid, lane, job_id, *, tokens, cost, dur_ms, when):
    """Create a RUN effort and stamp a cost record + a finish timestamp.

    ``when`` (epoch float) is written as the effort's finished_at + created_at so
    the 30d window is deterministic.
    """
    eh.record_effort(folder, pid, lane, job_id, skill="researchPrime")
    job_record = {
        "status": "done",
        "finished_at": when,
        "cost": {
            "total_cost_usd": cost,
            "duration_ms": dur_ms,
            "input_tokens": tokens // 2,
            "output_tokens": tokens - tokens // 2,
            "total_tokens": tokens,
        },
    }
    eh.attach_cost(folder, pid, lane, job_id, job_record)
    eh._set_created_at(folder, pid, lane, job_id, when)


def _discovered(eh, folder, pid, lane, rel):
    jid = eh.discovered_job_id(lane, rel)
    eh.record_effort(folder, pid, lane, jid, extra={
        "source": eh.SOURCE_DISCOVERED, "artifact_path": rel,
        "title": rel, "status": "imported"})


NOW = 1_900_000_000.0
DAY = 24 * 60 * 60.0


# ── lifetime: sums every run session ────────────────────────────────────────

def test_lifetime_sums_run_sessions(mods, tmp_path):
    rnd, eh, sess = mods
    folder = tmp_path / "proj"
    pid = _project(rnd, folder)["id"]
    _run_effort(eh, folder, pid, "research", "r1", tokens=100, cost=0.01,
                dur_ms=1000, when=NOW - 5 * DAY)
    _run_effort(eh, folder, pid, "build", "b1", tokens=42, cost=0.02,
                dur_ms=500, when=NOW - 40 * DAY)

    out = eh.project_effort_rollup(pid, "lifetime", now=NOW, folder_path=folder)
    assert out["tokens"] == 142
    assert out["cost_usd"] == pytest.approx(0.03)
    assert out["wall_clock_ms"] == 1500
    assert out["sessions"] == 2


def test_30d_excludes_old_records(mods, tmp_path):
    rnd, eh, sess = mods
    folder = tmp_path / "proj"
    pid = _project(rnd, folder)["id"]
    # Recent (in window) + old (>30 days, excluded).
    _run_effort(eh, folder, pid, "research", "recent", tokens=100, cost=0.01,
                dur_ms=1000, when=NOW - 5 * DAY)
    _run_effort(eh, folder, pid, "build", "old", tokens=42, cost=0.02,
                dur_ms=500, when=NOW - 40 * DAY)

    out = eh.project_effort_rollup(pid, "30d", now=NOW, folder_path=folder)
    assert out["tokens"] == 100
    assert out["cost_usd"] == pytest.approx(0.01)
    assert out["wall_clock_ms"] == 1000
    assert out["sessions"] == 1  # only the recent run session contributed


def test_30d_boundary_inclusive(mods, tmp_path):
    rnd, eh, sess = mods
    folder = tmp_path / "proj"
    pid = _project(rnd, folder)["id"]
    # Exactly at the 30-day cutoff is included (>= cutoff).
    _run_effort(eh, folder, pid, "research", "edge", tokens=10, cost=0.0,
                dur_ms=10, when=NOW - 30 * DAY)
    out = eh.project_effort_rollup(pid, "30d", now=NOW, folder_path=folder)
    assert out["tokens"] == 10
    assert out["sessions"] == 1
    # Just past the cutoff is excluded.
    _run_effort(eh, folder, pid, "research", "past", tokens=99, cost=0.0,
                dur_ms=10, when=NOW - 30 * DAY - 1)
    out2 = eh.project_effort_rollup(pid, "30d", now=NOW, folder_path=folder)
    assert out2["tokens"] == 10  # 'past' excluded


# ── imported/discovered contribute ZERO ─────────────────────────────────────

def test_imported_sessions_contribute_zero(mods, tmp_path):
    rnd, eh, sess = mods
    folder = tmp_path / "proj"
    pid = _project(rnd, folder)["id"]
    # One real run session.
    _run_effort(eh, folder, pid, "research", "r1", tokens=100, cost=0.01,
                dur_ms=1000, when=NOW - 1 * DAY)
    # A discovered (imported) planning session — must add nothing.
    _discovered(eh, folder, pid, "planning", "planning/old/MASTER-PLAN.md")
    _discovered(eh, folder, pid, "planning", "planning/old/IMPLEMENTATION-PLAN.md")

    # Sanity: that planning session is imported-provenance.
    psess = sess.list_sessions(folder, pid, "planning")
    assert psess and all(s["provenance"] == sess.PROV_IMPORTED for s in psess)

    out = eh.project_effort_rollup(pid, "lifetime", now=NOW, folder_path=folder)
    assert out["tokens"] == 100
    assert out["cost_usd"] == pytest.approx(0.01)
    assert out["sessions"] == 1  # only the run session counted


def test_zero_when_no_run_metrics(mods, tmp_path):
    rnd, eh, sess = mods
    folder = tmp_path / "proj"
    pid = _project(rnd, folder)["id"]
    # Only discovered (imported) content — no run cost anywhere.
    _discovered(eh, folder, pid, "research", "research/x/report.pdf")
    _discovered(eh, folder, pid, "planning", "planning/y/MASTER-PLAN.md")
    out = eh.project_effort_rollup(pid, "lifetime", now=NOW, folder_path=folder)
    assert out == {"tokens": 0, "cost_usd": 0.0, "wall_clock_ms": 0, "sessions": 0}


def test_empty_project_zero(mods, tmp_path):
    rnd, eh, sess = mods
    folder = tmp_path / "proj"
    pid = _project(rnd, folder)["id"]
    out = eh.project_effort_rollup(pid, "lifetime", now=NOW, folder_path=folder)
    assert out["tokens"] == 0 and out["sessions"] == 0


def test_folder_path_resolved_from_registry(mods, tmp_path):
    rnd, eh, sess = mods
    folder = tmp_path / "proj"
    pid = _project(rnd, folder)["id"]
    _run_effort(eh, folder, pid, "research", "r1", tokens=7, cost=0.0,
                dur_ms=1, when=NOW - DAY)
    # Omit folder_path → resolved from the registry by pid.
    out = eh.project_effort_rollup(pid, "lifetime", now=NOW)
    assert out["tokens"] == 7
