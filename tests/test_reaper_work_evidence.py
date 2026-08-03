"""reaper Wave 2 — positive, liveness-corroborated KILL predicate.

Locks the *positive-proof-of-death* contract of the zombie-hunter → safe-to-arm
build:

  * KILL rests on POSITIVE proof of death (a confirmed-dead OWNER) + NO
    corroborated positive signal + a fresh in-lock re-validation — never on the
    mere ABSENCE of an owner, and never on a stale artifact masquerading as life;
  * a legitimately-working sub-agent BLOCKED on an AskUserQuestion gate stays
    OWNED (its owning job keeps ``_holder_is_active`` true) — proven TWICE:
    once via ownership, once with ownership forcibly stripped from the snapshot
    (KEEP still holds via the process-alive probe);
  * a QUIET-but-alive session is KEPT;
  * a STALE ``index.lock`` / a FORGED heartbeat whose owner is DEAD is NOT
    protective (``has_corroborated_positive`` gates every signal on owner-alive);
  * the pre-execution re-validation ABORTS a kill the instant life re-appears;
  * the ``paths.py`` env knobs are read at call time with safe defaults.

Hermetic: a temp ``ANCHOR_DATA_DIR`` + explicit records/probes — never touches
the live ``.anchor`` store or any real process. Stdlib + pytest only.
"""
import importlib

import pytest


# ── Fakes ────────────────────────────────────────────────────────────────────

class FakeProbe:
    """Stand-in for ``proc_probe``: pid -> creation_time lookup."""

    def __init__(self, times=None):
        self.times = dict(times or {})

    def creation_time(self, pid):
        return self.times.get(pid)


def _running(session_id, **over):
    """A minimal RUNNING normalized-shape record with identity present."""
    rec = {
        "session_id": session_id,
        "status": "running",
        "pid": 1000,
        "proc_create_time": 5.0,
        "crypt_token": "tok",
    }
    rec.update(over)
    return rec


@pytest.fixture
def reaper_mod(tmp_path, monkeypatch):
    """The freshly-imported reaper module against a temp ANCHOR_DATA_DIR."""
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    import paths
    importlib.reload(paths)
    import session_registry
    importlib.reload(session_registry)
    import reaper
    importlib.reload(reaper)
    return reaper


# ── GWT 1: gate-blocked sub-agent KEPT — via ownership (run 1) ───────────────

def test_gate_blocked_kept_via_ownership(reaper_mod):
    """A gate-blocked sub-agent whose owning JOB is active is OWNED → classify
    alive → kill NOT authorized."""
    r = reaper_mod
    gb = _running("gb", pid=100)
    probe = FakeProbe({100: 5.0})  # process alive, identity matches
    snap = r.build_snapshot(attached_pty_ids=set(), records=[gb],
                            job_active=lambda s: s == "gb", probe=probe)
    assert "gb" in r.live_owner_ids(snap)
    assert r.classify_record(gb, snap) == r.VERDICT_ALIVE
    assert r.kill_authorized(gb, snap) is False


# ── GWT 1: gate-blocked KEPT — ownership stripped, process-alive (run 2) ─────

def test_gate_blocked_kept_ownership_stripped_process_alive(reaper_mod):
    """The SAME session with ownership forcibly stripped from the snapshot (no
    attach, no active job, no parent) is STILL kept: the kill predicate fails at
    positive-proof-of-death because the owning process is alive."""
    r = reaper_mod
    gb = _running("gb", pid=100)
    probe = FakeProbe({100: 5.0})  # process still alive
    snap = r.build_snapshot(attached_pty_ids=set(), records=[gb],
                            job_active=lambda _s: False, probe=probe)
    assert "gb" not in r.live_owner_ids(snap)          # ownership stripped
    assert r.classify_record(gb, snap) == r.VERDICT_KILL   # flagged as candidate
    # …but the destructive gate refuses: process alive ⇒ no proof of death.
    assert r.kill_authorized(gb, snap) is False
    sig = snap.positive_liveness["gb"]
    assert sig.owner_alive is True
    assert sig.owner_confirmed_dead is False


def test_gate_blocked_job_stays_owned_in_job_runner(tmp_path, monkeypatch):
    """Investigation proof: a gate-blocked / API-waiting job stays RUNNING with
    ``_holder_is_active`` true — so NO ``blocked_but_owned`` job state was needed;
    the existing state model already keeps it in ``job_owned_ids``."""
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    import paths
    importlib.reload(paths)
    import session_registry
    importlib.reload(session_registry)
    import reaper
    importlib.reload(reaper)
    import job_runner
    importlib.reload(job_runner)

    # A gate-blocked job: RUNNING, process alive, state awaiting-input.
    monkeypatch.setattr(job_runner, "_pid_alive", lambda _pid: True)
    job_runner._write_record({
        "job_id": "j1", "status": "running", "pid": 4321,
        "state": "awaiting-input", "lane": "swarm",
    })
    assert job_runner.is_gate_blocked("j1") is True
    assert job_runner._holder_is_active("j1") is True
    assert job_runner.blocked_but_owned("j1") is True

    # And the reaper's owner enumeration keeps it via the owning-job predicate.
    sess = _running("j1", pid=4321)
    snap = reaper.build_snapshot(attached_pty_ids=set(), records=[sess],
                                 job_active=job_runner._holder_is_active,
                                 probe=FakeProbe({4321: 5.0}))
    assert "j1" in reaper.live_owner_ids(snap)
    assert reaper.kill_authorized(sess, snap) is False


# ── quiet-but-alive KEEP ─────────────────────────────────────────────────────

def test_quiet_but_alive_is_kept(reaper_mod):
    """No file writes, no lock, no heartbeat, no owner — but the process is
    alive: KEPT (never killed on absence of a signal)."""
    r = reaper_mod
    quiet = _running("quiet", pid=200)
    snap = r.build_snapshot(attached_pty_ids=set(), records=[quiet],
                            job_active=lambda _s: False,
                            probe=FakeProbe({200: 5.0}))
    sig = snap.positive_liveness["quiet"]
    assert not (sig.index_lock or sig.heartbeat_fresh or sig.work_mtime_fresh)
    assert sig.owner_alive is True
    assert r.kill_authorized(quiet, snap) is False


# ── GWT 2: stale lock / forged heartbeat NOT protective ──────────────────────

def _worktree_with(tmp_path, *, index_lock=False, heartbeat_age=None):
    wt = tmp_path / "wt"
    (wt / ".git").mkdir(parents=True)
    if index_lock:
        (wt / ".git" / "index.lock").write_text("")
    if heartbeat_age is not None:
        import os
        hb = wt / ".anchor_heartbeat"
        hb.write_text("beat")
        import time
        mt = time.time() - heartbeat_age
        os.utime(hb, (mt, mt))
    return wt


def test_stale_index_lock_not_protective_orphan_reap_eligible(reaper_mod, tmp_path):
    """A git index.lock present but the owning PID confirmed dead is a STALE
    lock: it does NOT grant KEEP, and the orphan is reap-eligible."""
    r = reaper_mod
    wt = _worktree_with(tmp_path, index_lock=True)
    rec = _running("stale", pid=300, worktree_path=str(wt))
    # Owner PID has no live process → confirmed dead.
    snap = r.build_snapshot(attached_pty_ids=set(), records=[rec],
                            job_active=lambda _s: False, probe=FakeProbe({}))
    sig = snap.positive_liveness["stale"]
    assert sig.index_lock is True            # the lock IS detected…
    assert sig.owner_alive is False          # …but its owner is dead
    assert sig.owner_confirmed_dead is True
    assert r.has_corroborated_positive(sig) is False   # not protective
    assert r.classify_record(rec, snap) == r.VERDICT_REAP_DEAD
    assert r.kill_authorized(rec, snap) is True         # reap-eligible


def test_forged_heartbeat_not_protective(reaper_mod, tmp_path):
    """A FRESH heartbeat file whose owning PID is dead is a forged/stale
    heartbeat — it grants no KEEP."""
    r = reaper_mod
    wt = _worktree_with(tmp_path, heartbeat_age=1.0)  # 1s old ⇒ "fresh"
    rec = _running("forged", pid=301, worktree_path=str(wt))
    snap = r.build_snapshot(attached_pty_ids=set(), records=[rec],
                            job_active=lambda _s: False, probe=FakeProbe({}))
    sig = snap.positive_liveness["forged"]
    assert sig.heartbeat_fresh is True
    assert sig.owner_alive is False
    assert r.has_corroborated_positive(sig) is False
    assert r.kill_authorized(rec, snap) is True


def test_live_lock_is_corroborated_positive(reaper_mod, tmp_path):
    """The corroboration gate the other way: a lock WITH a live owner counts as a
    corroborated positive signal."""
    r = reaper_mod
    wt = _worktree_with(tmp_path, index_lock=True)
    rec = _running("busy", pid=302, worktree_path=str(wt))
    snap = r.build_snapshot(attached_pty_ids=set(), records=[rec],
                            job_active=lambda _s: False,
                            probe=FakeProbe({302: 5.0}))  # owner ALIVE
    sig = snap.positive_liveness["busy"]
    assert sig.index_lock is True and sig.owner_alive is True
    assert r.has_corroborated_positive(sig) is True
    assert r.kill_authorized(rec, snap) is False


# ── recycled PID never authorized (kill the new owner) ───────────────────────

def test_recycled_pid_never_authorized(reaper_mod):
    """A PID live but with a MISMATCHED creation time is a recycled PID (a
    different process now owns it): neither alive-ours NOR confirmed-dead → the
    kill is never authorized (we must not kill the new owner)."""
    r = reaper_mod
    rec = _running("recyc", pid=400, proc_create_time=5.0)
    snap = r.build_snapshot(attached_pty_ids=set(), records=[rec],
                            job_active=lambda _s: False,
                            probe=FakeProbe({400: 9999.0}))  # different process
    assert r.classify_record(rec, snap) == r.VERDICT_REAP_RECYCLED
    assert r.kill_authorized(rec, snap) is False


# ── pre-execution re-validation ──────────────────────────────────────────────

def test_kill_authorized_confirmed_dead_no_signal(reaper_mod):
    """The clean confirmed-dead orphan (no owner, PID gone, no signal) IS
    authorized when no re-validation is supplied."""
    r = reaper_mod
    rec = _running("dead", pid=500)
    snap = r.build_snapshot(attached_pty_ids=set(), records=[rec],
                            job_active=lambda _s: False, probe=FakeProbe({}))
    assert r.kill_authorized(rec, snap) is True


def test_pre_execution_revalidation_aborts_when_life_reappears(reaper_mod):
    """Immediately before the destructive action (same lock), a re-validation
    that now reports life ABORTS the kill."""
    r = reaper_mod
    rec = _running("flip", pid=501)
    snap = r.build_snapshot(attached_pty_ids=set(), records=[rec],
                            job_active=lambda _s: False, probe=FakeProbe({}))
    # Authorized against the stale snapshot…
    assert r.kill_authorized(rec, snap) is True
    # …but a re-validation reporting life vetoes it.
    assert r.kill_authorized(rec, snap, revalidate=lambda _rec: True) is False


def test_revalidate_target_detects_owner_now_alive(reaper_mod):
    """``revalidate_target`` rebuilds a one-record snapshot from a LIVE probe:
    an owner that has come back alive ⇒ ABORT (True); still-dead ⇒ proceed
    (False)."""
    r = reaper_mod
    rec = _running("t", pid=600)
    # Owner alive now → abort.
    assert r.revalidate_target(rec, attached_pty_ids=set(),
                               job_active=lambda _s: False,
                               probe=FakeProbe({600: 5.0})) is True
    # Owner still dead → do not abort.
    assert r.revalidate_target(rec, attached_pty_ids=set(),
                               job_active=lambda _s: False,
                               probe=FakeProbe({})) is False


def test_revalidate_target_owner_reclaimed_aborts(reaper_mod):
    """A target whose owning job has re-claimed it ⇒ ABORT."""
    r = reaper_mod
    rec = _running("t2", pid=601)
    assert r.revalidate_target(rec, attached_pty_ids=set(),
                               job_active=lambda s: s == "t2",
                               probe=FakeProbe({})) is True


# ── env knobs via paths.py ───────────────────────────────────────────────────

def test_env_knobs_defaults_and_override(monkeypatch):
    import paths
    importlib.reload(paths)
    # Defaults (unset).
    monkeypatch.delenv("ANCHOR_REAPER_WORK_MTIME_SECS", raising=False)
    monkeypatch.delenv("ANCHOR_REAPER_CPU_WINDOW_SECS", raising=False)
    monkeypatch.delenv("ANCHOR_REAPER_HEARTBEAT_STALE_SECS", raising=False)
    assert paths.reaper_work_mtime_secs() == paths.REAPER_WORK_MTIME_SECS_DEFAULT
    assert paths.reaper_cpu_window_secs() == paths.REAPER_CPU_WINDOW_SECS_DEFAULT
    assert (paths.reaper_heartbeat_stale_secs()
            == paths.REAPER_HEARTBEAT_STALE_SECS_DEFAULT)
    # Overrides.
    monkeypatch.setenv("ANCHOR_REAPER_WORK_MTIME_SECS", "42")
    monkeypatch.setenv("ANCHOR_REAPER_HEARTBEAT_STALE_SECS", "7")
    assert paths.reaper_work_mtime_secs() == 42.0
    assert paths.reaper_heartbeat_stale_secs() == 7.0
    # Invalid / non-positive → safe default (never a kill-widening 0).
    monkeypatch.setenv("ANCHOR_REAPER_CPU_WINDOW_SECS", "nonsense")
    assert paths.reaper_cpu_window_secs() == paths.REAPER_CPU_WINDOW_SECS_DEFAULT
    monkeypatch.setenv("ANCHOR_REAPER_WORK_MTIME_SECS", "0")
    assert paths.reaper_work_mtime_secs() == paths.REAPER_WORK_MTIME_SECS_DEFAULT


def test_heartbeat_staleness_window_respected(reaper_mod, tmp_path, monkeypatch):
    """A heartbeat older than the stale window grants no signal."""
    r = reaper_mod
    monkeypatch.setenv("ANCHOR_REAPER_HEARTBEAT_STALE_SECS", "30")
    import paths
    importlib.reload(paths)
    importlib.reload(r)
    wt = _worktree_with(tmp_path, heartbeat_age=1000.0)  # very stale
    rec = _running("hb", pid=700, worktree_path=str(wt))
    snap = r.build_snapshot(attached_pty_ids=set(), records=[rec],
                            job_active=lambda _s: False,
                            probe=FakeProbe({700: 5.0}))
    assert snap.positive_liveness["hb"].heartbeat_fresh is False
