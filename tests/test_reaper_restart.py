"""reaper Wave 7 — restart-durable, PROTECT-ONLY freeze state.

Locks criteria (9) + (14) of the zombie-hunter → safe-to-arm plan:

  - The persisted frozen-set (``.anchor/reaper_frozen.json``) is written
    atomically BEFORE any arming and is re-read + re-honored after a simulated
    NSSM ``anchor`` restart: a frozen session stays frozen across the process
    boundary via re-probe-and-reconcile, relying on NO cross-restart OS
    containment.
  - The persisted state can only PROTECT (keep-frozen / thaw). A persisted
    ``would-kill`` marker is INERT on restart — reconcile never kills from it; any
    destructive action is re-derived IN-PROCESS from a fresh live probe
    (``freeze_state.rederive_kill_authorized`` → ``reaper.kill_authorized``).
  - Per-PID suspend/resume is the FLOOR: freeze works with zero OS-containment
    support, and no ``tree_kill`` (mass-kill-on-handle-close) ever fires during a
    freeze or a reconcile.
  - The identity-tuple reuse guard: a dead PID drops the entry, and a RECYCLED PID
    (a different process now holds it) drops the entry and NEVER touches the new
    owner.

Hermetic: a temp ``ANCHOR_DATA_DIR`` + explicit records + injected fake
probe/suspend/resume spies — never touches the live ``.anchor`` store or any real
process. Stdlib + pytest only.
"""
import importlib
import json

import pytest


# A fixed epoch so freeze/age math is deterministic (never real wall-clock).
NOW = 2_000_000.0


class FakeProbe:
    """A creation-time-only probe (the seam reconcile + reaper snapshots use).

    An empty / missing entry ⇒ that PID probes DEAD (gone). A present entry ⇒ the
    PID resolves to a live process with that creation time (identity match iff it
    equals the stored ``proc_create_time`` within tol).
    """

    def __init__(self, times=None):
        self.times = dict(times or {})

    def creation_time(self, pid):
        return self.times.get(pid)


class Spy:
    """Records every call so a test can assert what a primitive was invoked on."""

    def __init__(self, ret=True):
        self.calls = []
        self.ret = ret

    def __call__(self, pid):
        self.calls.append(pid)
        return self.ret


@pytest.fixture
def mod(tmp_path, monkeypatch):
    """Temp data dir + freshly-reloaded ``paths`` / ``session_registry`` /
    ``reaper`` / ``freeze_state`` (so ``ANCHOR_DATA_DIR`` is honored)."""
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    import paths
    importlib.reload(paths)
    import session_registry
    importlib.reload(session_registry)
    import reaper
    importlib.reload(reaper)
    import freeze_state
    importlib.reload(freeze_state)
    return freeze_state


def _rec(session_id, *, pid, ct, status="running"):
    """A minimal session record with a process identity tuple."""
    return {
        "session_id": session_id,
        "status": status,
        "pid": pid,
        "proc_create_time": ct,
        "crypt_token": "tok",
        "worktree_path": "",
    }


# ── Persistence: atomic, protect-only, crash-safe ordering ───────────────────

def test_freeze_persists_atomically_before_suspend(mod):
    """freeze_session writes a valid JSON frozen-set BEFORE suspending — so a
    crash between the two steps still leaves a re-establishable record."""
    fz = mod
    suspend = Spy(ret=True)
    rec = _rec("s1", pid=100, ct=50.0)

    out = fz.freeze_session(rec, suspend=suspend, now=NOW)
    assert out == {"ok": True, "suspended": True}

    # The frozen-set is on disk, valid JSON, and correctly shaped.
    p = fz.frozen_path()
    assert p.exists()
    data = json.loads(p.read_text(encoding="utf-8"))
    assert isinstance(data, list) and len(data) == 1
    entry = data[0]
    assert entry["session_id"] == "s1"
    assert entry["pid"] == 100
    assert entry["proc_create_time"] == 50.0
    assert entry["state"] == fz.STATE_FROZEN
    # The suspend happened AFTER the persist, on the right PID.
    assert suspend.calls == [100]
    assert fz.is_frozen("s1")


def test_persist_survives_a_suspend_that_raises(mod):
    """Even if the suspend primitive throws, the entry is already persisted —
    persist-before-suspend guarantees no un-recorded suspended process."""
    fz = mod

    def boom(_pid):
        raise OSError("suspend failed")

    out = fz.freeze_session(_rec("s1", pid=100, ct=50.0), suspend=boom, now=NOW)
    assert out["ok"] is True
    assert out["suspended"] is False
    assert fz.is_frozen("s1")  # recorded despite the suspend failure


# ── The keystone: a frozen session survives a simulated restart ──────────────

def test_frozen_session_survives_restart_via_reprobe(mod):
    """A frozen session is re-probed and RE-FROZEN across the process boundary —
    relying on no cross-restart OS containment (per-PID re-suspend only)."""
    fz = mod
    # Pre-restart: freeze s1 (pid 100, ct 50.0).
    fz.freeze_session(_rec("s1", pid=100, ct=50.0), suspend=Spy(), now=NOW)

    # ── simulate the NSSM restart ── new process, fresh in-memory state; the ONLY
    # thing that carries over is the on-disk frozen-set. Re-probe says pid 100 is
    # still alive with the SAME creation time (identity matches).
    resuspend = Spy(ret=True)
    result = fz.reconcile_after_restart(
        probe=FakeProbe({100: 50.0}), suspend=resuspend)

    assert result.re_frozen == ("s1",)
    assert result.thawed == ()
    assert result.would_kill_pending == ()
    # Freeze re-established FROM SCRATCH via the per-PID floor mechanism.
    assert resuspend.calls == [100]
    # Still persisted as frozen after reconcile.
    assert fz.is_frozen("s1")


def test_reconcile_drops_dead_pid(mod):
    """A frozen entry whose PID is GONE is dropped (nothing to freeze) and never
    re-suspended."""
    fz = mod
    fz.freeze_session(_rec("s1", pid=100, ct=50.0), suspend=Spy(), now=NOW)

    resuspend = Spy()
    result = fz.reconcile_after_restart(
        probe=FakeProbe({}), suspend=resuspend)  # empty ⇒ pid 100 is dead

    assert result.thawed == ("s1",)
    assert result.re_frozen == ()
    assert resuspend.calls == []           # nothing suspended
    assert not fz.is_frozen("s1")          # entry dropped
    assert fz.load_frozen() == {}


def test_reconcile_drops_recycled_pid_without_touching_new_owner(mod):
    """A frozen entry whose PID is now held by a DIFFERENT process (creation-time
    mismatch) is dropped and the new owner is NEVER suspended/killed."""
    fz = mod
    fz.freeze_session(_rec("s1", pid=100, ct=50.0), suspend=Spy(), now=NOW)

    resuspend = Spy()
    # PID 100 is alive but with a DIFFERENT creation time ⇒ recycled.
    result = fz.reconcile_after_restart(
        probe=FakeProbe({100: 999.0}), suspend=resuspend)

    assert result.thawed == ("s1",)
    assert result.re_frozen == ()
    assert resuspend.calls == []           # the new owner is untouched
    assert not fz.is_frozen("s1")


# ── Protect-only: a would-kill marker can NEVER cause a kill on restart ───────

def test_would_kill_marker_is_inert_on_reconcile(mod):
    """A persisted 'would-kill' marker is recorded but INERT: reconcile keeps it
    pending, suspends nothing, and (structurally) kills nothing."""
    fz = mod
    fz.mark_would_kill(_rec("s1", pid=100, ct=50.0), now=NOW)

    # Recorded honestly with the would-kill state.
    entry = fz.get_entry("s1")
    assert entry is not None and entry.state == fz.STATE_WOULD_KILL
    assert not fz.is_frozen("s1")

    # Reconcile with the marker's PID still alive+matching: kept PENDING, no
    # suspend fired (a would-kill marker is not a freeze), nothing killed.
    resuspend = Spy()
    result = fz.reconcile_after_restart(
        probe=FakeProbe({100: 50.0}), suspend=resuspend)

    assert result.would_kill_pending == ("s1",)
    assert result.re_frozen == ()
    assert resuspend.calls == []            # a marker never suspends/kills
    assert fz.get_entry("s1").state == fz.STATE_WOULD_KILL  # still just a marker


def test_kill_is_rederived_in_process_not_from_the_marker(mod):
    """The kill decision comes from a FRESH in-process live probe, never from the
    persisted marker: an alive owner ⇒ NOT authorized; a confirmed-dead owner ⇒
    authorized — proving the marker itself authorizes nothing."""
    fz = mod
    import reaper

    fz.mark_would_kill(_rec("s1", pid=100, ct=50.0), now=NOW)
    rec = _rec("s1", pid=100, ct=50.0)

    # (a) Fresh probe says the owner is ALIVE (identity matches) → an alive,
    # unowned session is a CANDIDATE ('kill') but is NOT kill-authorized: the
    # positive-proof-of-death predicate requires the owner CONFIRMED DEAD.
    snap_alive = reaper.build_snapshot(
        attached_pty_ids=set(), records=[rec],
        job_active=lambda _s: False, probe=FakeProbe({100: 50.0}))
    assert fz.rederive_kill_authorized(rec, snap_alive) is False

    # (b) Fresh probe says the owner is GONE (dead) → REAP_DEAD, no owner, no
    # corroborated signal → NOW authorized. The authorization came from the live
    # probe, not from the persisted 'would-kill' marker.
    snap_dead = reaper.build_snapshot(
        attached_pty_ids=set(), records=[rec],
        job_active=lambda _s: False, probe=FakeProbe({}))
    assert fz.rederive_kill_authorized(rec, snap_dead) is True

    # A degraded snapshot never authorizes (uncertainty → keep).
    assert fz.rederive_kill_authorized(rec, None) is False


# ── No OS containment: no mass-kill-on-handle-close ──────────────────────────

def test_freeze_and_reconcile_never_tree_kill(mod, monkeypatch):
    """On a host WITHOUT the optional Job Object enhancement, neither freezing nor
    a restart reconcile ever calls tree_kill — freeze is per-PID suspend/resume
    only, so a closing handle can never mass-kill a tree."""
    fz = mod
    import proc_probe

    kill_spy = Spy()
    monkeypatch.setattr(proc_probe, "tree_kill", kill_spy, raising=False)

    fz.freeze_session(_rec("s1", pid=100, ct=50.0), suspend=Spy(), now=NOW)
    fz.reconcile_after_restart(probe=FakeProbe({100: 50.0}), suspend=Spy())

    assert kill_spy.calls == []   # no kill fired anywhere in the freeze path


def test_thaw_resumes_and_drops(mod):
    """thaw_session resumes the PID (reversible) and removes the persisted entry."""
    fz = mod
    fz.freeze_session(_rec("s1", pid=100, ct=50.0), suspend=Spy(), now=NOW)

    resume = Spy(ret=True)
    out = fz.thaw_session("s1", resume=resume)
    assert out == {"ok": True, "resumed": True}
    assert resume.calls == [100]
    assert not fz.is_frozen("s1")
    assert fz.load_frozen() == {}


# ── Mixed pass + corrupt-store resilience ────────────────────────────────────

def test_reconcile_mixed_set(mod):
    """One live-frozen (re-froze), one dead (dropped), one recycled (dropped), one
    live would-kill (kept pending) — all in a single reconcile pass."""
    fz = mod
    fz.freeze_session(_rec("live", pid=100, ct=50.0), suspend=Spy(), now=NOW)
    fz.freeze_session(_rec("dead", pid=200, ct=60.0), suspend=Spy(), now=NOW)
    fz.freeze_session(_rec("recyc", pid=300, ct=70.0), suspend=Spy(), now=NOW)
    fz.mark_would_kill(_rec("mark", pid=400, ct=80.0), now=NOW)

    resuspend = Spy()
    result = fz.reconcile_after_restart(
        probe=FakeProbe({100: 50.0, 300: 999.0, 400: 80.0}),  # 200 absent=dead
        suspend=resuspend)

    assert set(result.re_frozen) == {"live"}
    assert set(result.thawed) == {"dead", "recyc"}
    assert set(result.would_kill_pending) == {"mark"}
    assert resuspend.calls == [100]                    # only the live-frozen one
    assert fz.is_frozen("live")
    assert not fz.is_frozen("dead") and not fz.is_frozen("recyc")
    assert fz.get_entry("mark").state == fz.STATE_WOULD_KILL


def test_corrupt_store_is_empty_not_crash(mod):
    """A corrupt frozen-set reads as empty (never crashes boot reconcile)."""
    fz = mod
    fz.anchor_dir().mkdir(parents=True, exist_ok=True)
    fz.frozen_path().write_text("{ not json", encoding="utf-8")
    assert fz.load_frozen() == {}
    # Reconcile over a corrupt store is a clean, empty, non-throwing pass.
    result = fz.reconcile_after_restart(probe=FakeProbe({}), suspend=Spy())
    assert result == fz.ReconcileResult()
