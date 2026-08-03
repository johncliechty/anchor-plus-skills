"""zombie-hunter v2 — swarm-job session coverage (DESIGN.md gap closure).

Locks the functional fix for the known coverage gap: ``job_runner`` swarm jobs
historically wrote their identity (pid / proc_create_time / crypt_token) ONLY to
the job store, so ``zombie_hunter.sweep`` — which reads
``session_registry.load_sessions()`` — could not see them. The fix registers a
RUNNING ``session_registry`` record (lane ``"swarm"``) at spawn carrying that
same identity, and clears it out of RUNNING when the job exits (the gandalf
finally-reset analog).

Asserts, end-to-end through the real ``job_runner.launch`` (driven by the mock
runner, never live ``claude``):

  1. a launched swarm job registers a session with the EXACT identity the
     hunter's ``classify`` requires (lane=swarm, RUNNING, pid, proc_create_time,
     crypt_token);
  2. on completion the session is mirrored OUT of RUNNING (done / failed);
  3. a cancel mirrors the session to cancelled;
  4. the hunter's ``sweep`` reaps a registered-but-orphaned swarm session
     (verdict kill → killer called once on the right pid → record → idle);
  5. the hunter ABSTAINS on a swarm session whose identity is missing — it
     NEVER kills the wrong thing.

Hermetic: a temp ``ANCHOR_DATA_DIR`` so it never touches the live ``.anchor``
store or any real process beyond the deterministic mock. Stdlib + pytest only.
"""
import importlib
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()


# ── Fakes (no real process needed for the pure classify/sweep path) ──────────

class FakeProbe:
    """Stand-in for ``proc_probe``: pid -> creation_time lookup."""

    def __init__(self, times=None):
        self.times = dict(times or {})

    def creation_time(self, pid):
        return self.times.get(pid)


class FakeKiller:
    """Records every ``killer(pid)`` call; reports success."""

    def __init__(self, ok=True):
        self.calls = []
        self.ok = ok

    def __call__(self, pid):
        self.calls.append(pid)
        return self.ok


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A temp ANCHOR_DATA_DIR + mock runner; reload the stack in dependency order."""
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    import paths
    importlib.reload(paths)
    import session_registry
    importlib.reload(session_registry)
    import job_runner
    importlib.reload(job_runner)
    import zombie_hunter
    importlib.reload(zombie_hunter)
    yield {"jr": job_runner, "reg": session_registry, "zh": zombie_hunter}
    job_runner._reset_live_table_for_tests()


# ── 1. spawn registers a sweepable session with the hunter's identity ────────

def test_swarm_launch_registers_session_with_identity(env):
    jr, reg = env["jr"], env["reg"]
    # Keep the job alive briefly so the session is observably RUNNING at spawn.
    rec = jr.launch("build", extra_args=["--lines", "1", "--sleep", "1.0"])
    jid = rec["job_id"]

    sess = reg.get_session(jid)
    assert sess is not None, "swarm job did not register a session"
    assert sess["lane"] == jr.SWARM_LANE == "swarm"
    assert sess["status"] == reg.STATUS_RUNNING
    # The EXACT identity fields the hunter's classify needs, equal to the job's.
    assert sess["pid"] == rec["pid"]
    assert sess["crypt_token"] == rec["crypt_token"]
    assert sess["crypt_token"]  # non-empty
    assert sess["proc_create_time"] == rec["proc_create_time"]

    jr.wait(jid, timeout=30)


# ── 2. completion mirrors the session out of RUNNING (finally-reset) ─────────

def test_swarm_completion_clears_running(env):
    jr, reg = env["jr"], env["reg"]
    rec = jr.launch("research", extra_args=["--lines", "2", "--exit-code", "0"])
    jid = rec["job_id"]
    jr.wait(jid, timeout=30)
    assert reg.get_session(jid)["status"] == reg.STATUS_DONE


def test_swarm_failure_mirrors_failed(env):
    jr, reg = env["jr"], env["reg"]
    rec = jr.launch("plan", extra_args=["--lines", "1", "--exit-code", "5"])
    jid = rec["job_id"]
    jr.wait(jid, timeout=30)
    assert reg.get_session(jid)["status"] == reg.STATUS_FAILED


# ── 3. cancel mirrors the session to cancelled ───────────────────────────────

def test_swarm_cancel_mirrors_cancelled(env):
    jr, reg = env["jr"], env["reg"]
    rec = jr.launch("build", extra_args=["--lines", "1", "--sleep", "5.0"])
    jid = rec["job_id"]
    jr.cancel(jid)
    assert reg.get_session(jid)["status"] == reg.STATUS_CANCELLED


# ── 4. the hunter reaps a registered-but-orphaned swarm session ──────────────

def test_hunter_reaps_orphaned_swarm_session(env):
    reg, zh = env["reg"], env["zh"]
    # Simulate a swarm child orphaned by a server crash: a RUNNING swarm session
    # whose process is still alive (identity matches) but is NOT attached.
    reg.register_session(
        "", "swarm", status=reg.STATUS_RUNNING,
        session_id="orphan", pid=4242, proc_create_time=1234.0,
        crypt_token="tok")
    probe = FakeProbe({4242: 1234.0})  # alive, creation-time matches → ours
    killer = FakeKiller()

    report = zh.sweep(set(), probe=probe, killer=killer, apply=True)

    assert killer.calls == [4242]              # killed exactly the orphan's pid
    assert report["killed"] == ["orphan"]
    assert reg.get_session("orphan")["status"] == reg.STATUS_IDLE  # reaped


# ── 5. the hunter ABSTAINS on a swarm session with missing identity ──────────

def test_hunter_abstains_on_swarm_session_missing_identity(env):
    reg, zh = env["reg"], env["zh"]
    # A swarm session whose crypt_token never got stamped → unidentifiable.
    reg.register_session(
        "", "swarm", status=reg.STATUS_RUNNING, session_id="noid",
        pid=4243, proc_create_time=1234.0, crypt_token="")
    probe = FakeProbe({4243: 1234.0})
    killer = FakeKiller()

    report = zh.sweep(set(), probe=probe, killer=killer, apply=True)

    assert killer.calls == []                    # NEVER kills the wrong thing
    assert report["abstained"] == ["noid"]
    assert reg.get_session("noid")["status"] == reg.STATUS_RUNNING  # untouched


# ── Wave 2 (#1) STUB GATE — the live-owner orphan discriminator ───────────────
# A registered-RUNNING session is an orphan ONLY if identity-alive AND it has NO
# LIVE OWNER (not attached, not job-owned, not parent-owned). These lock the
# safety-critical fix: a legit, work-doing session with no OPEN browser stream is
# never classed an orphan.

def _running(session_id, **extra):
    """A minimal normalized-shape running record for the discriminator."""
    rec = {"session_id": session_id, "status": "running",
           "pid": 100, "proc_create_time": 1.0, "crypt_token": "t"}
    rec.update(extra)
    return rec


def test_live_owner_ids_is_superset_of_attached(env):
    zh = env["zh"]
    out = zh.live_owner_ids({"a", "b"}, records=[], job_active=lambda _s: False)
    assert {"a", "b"} <= out


def test_live_owner_job_owned_session_not_flagged(env):
    """(a) running + alive-PID + has a live owner (owning JOB active) ⇒ NOT flagged."""
    zh = env["zh"]
    recs = [_running("worker")]
    # No attached stream, but an actively-running owning job backs it.
    live = zh.live_owner_ids(set(), records=recs, job_active=lambda sid: sid == "worker")
    assert "worker" in live
    probe = FakeProbe({100: 1.0})              # alive, identity matches → ours
    assert zh.classify(recs[0], live, probe=probe) == zh.VERDICT_ALIVE


def test_live_owner_parent_owned_child_not_flagged(env):
    """A child whose live parent owns it is itself owned (transitive)."""
    zh = env["zh"]
    parent = _running("parent")
    child = _running("child", parent_session_id="parent")
    # Parent has the only direct live owner (an active job); child inherits it.
    live = zh.live_owner_ids(set(), records=[parent, child],
                             job_active=lambda sid: sid == "parent")
    assert {"parent", "child"} <= live
    probe = FakeProbe({100: 1.0})
    assert zh.classify(child, live, probe=probe) == zh.VERDICT_ALIVE


def test_live_owner_no_owner_session_is_orphan(env):
    """(b) running + alive-PID + NO live owner ⇒ kill (the hunter is NOT neutered)."""
    zh = env["zh"]
    rec = _running("lonely")
    live = zh.live_owner_ids(set(), records=[rec], job_active=lambda _s: False)
    assert "lonely" not in live
    probe = FakeProbe({100: 1.0})              # alive PID, but no owner
    assert zh.classify(rec, live, probe=probe) == zh.VERDICT_KILL


def test_live_owner_dead_pid_reaps_no_banner(env):
    """(c) dead PID ⇒ reap_dead (not kill) ⇒ no banner, regardless of ownership."""
    zh = env["zh"]
    rec = _running("gone", pid=999)
    live = zh.live_owner_ids(set(), records=[rec], job_active=lambda _s: False)
    probe = FakeProbe({})                       # PID 999 resolves to nothing → dead
    assert zh.classify(rec, live, probe=probe) == zh.VERDICT_REAP_DEAD


def test_legit_swarm_job_session_never_an_orphan(env):
    """A real launched lane-job session (alive, job-owned) is never flagged kill.

    Drives the real ``job_runner.launch`` (mock runner) so the session carries
    the hunter's identity AND a genuinely-active owning job, then asserts the
    live-owner discriminator keeps it OUT of the orphan set.
    """
    jr, reg, zh = env["jr"], env["reg"], env["zh"]
    rec = jr.launch("build", extra_args=["--lines", "1", "--sleep", "1.5"])
    jid = rec["job_id"]
    try:
        running = reg.list_sessions(status="running")
        # No attached PTY stream at all — the owner is the live JOB.
        live = zh.live_owner_ids(set(), records=running)
        assert jid in live, "a live job-owned session must count as owned"
        sess = reg.get_session(jid)
        # With the real probe its identity resolves; owned ⇒ alive, never kill.
        assert zh.classify(sess, live) != zh.VERDICT_KILL
    finally:
        jr.wait(jid, timeout=30)
