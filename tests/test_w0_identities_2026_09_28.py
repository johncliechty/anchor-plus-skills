"""W0 of the steward revision (2026-09-28): a session bound to its step — the registry carries ``step_id``; a
spawned job's record names the project and the step from its dispatch context; a pre-W0 record normalizes to ""."""
import importlib

import pytest


@pytest.fixture
def reg(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    import paths
    importlib.reload(paths)
    import session_registry as sr
    importlib.reload(sr)
    return sr


def test_register_carries_step_id_and_normalizes_absent_to_empty(reg):
    rec = reg.register_session("proj-1", "general", status=reg.STATUS_RUNNING, step_id="lecture-4")
    assert rec["step_id"] == "lecture-4"
    assert reg.get_session(rec["session_id"])["step_id"] == "lecture-4"
    plain = reg.register_session("proj-1", "general")
    assert plain["step_id"] == ""
    # a pre-W0 record on disk (no step_id key) normalizes to "" without a crash
    legacy = reg._normalize({"session_id": "old-1", "project_id": "proj-1", "lane": "plan", "status": "idle"})
    assert legacy["step_id"] == ""
    assert reg._normalize({"session_id": "s", "step_id": 12})["step_id"] == "12"


def test_dispatch_step_id_reads_the_captured_context():
    import job_runner
    assert job_runner._dispatch_step_id({"step_id": "supplement-3", "ok": True}) == "supplement-3"
    assert job_runner._dispatch_step_id({"step_id": "supplement-3"}) == "supplement-3"
    assert job_runner._dispatch_step_id({"ok": False, "error": "dispatch-context-failed"}) is None
    assert job_runner._dispatch_step_id({"step_id": None}) is None
    assert job_runner._dispatch_step_id(None) is None
    assert job_runner._dispatch_step_id("not a dict") is None


def test_swarm_registration_binds_project_and_step(monkeypatch):
    import job_runner
    import session_registry as sr
    seen = {}

    def fake_register(**kw):
        seen.update(kw)
        return dict(kw)
    monkeypatch.setattr(sr, "register_session", fake_register)
    job_runner._register_swarm_session("job-1", 4242, 1.5, "tok", cwd="C:/x", backend="claude",
                                       project_id="proj-9", step_id="lecture-4")
    assert seen["session_id"] == "job-1"
    assert seen["project_id"] == "proj-9"
    assert seen["step_id"] == "lecture-4"
    assert seen["status"] == sr.STATUS_RUNNING
    # the pre-W0 call shape still works (no project, no step)
    seen.clear()
    job_runner._register_swarm_session("job-2", 1, 1.0, "", cwd=None, backend="claude")
    assert seen["project_id"] == "" and seen["step_id"] is None
