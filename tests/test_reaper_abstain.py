"""reaper Wave 2 — the ABSTAIN-not-kill invariant (defensive boundary).

Locks criterion (1): when the liveness inputs are missing, stale, partial, or
the owner-set computation THROWS, every one of the five call sites treats the
session as OWNED/alive and takes ZERO freeze/kill actions.

The five sites all funnel through the ONE shared provider (Wave 1): the three
per-record display sites (banner / Swarm & Owner View freeze / brief) via
:func:`reaper.classify_record`, the armed kill-daemon via
:func:`reaper.owner_ids_or_abstain`, and the boot reconcile via
:func:`reaper.live_pid_ids` over an EXPLICIT-records snapshot. Proving the shared
provider is abstain-safe — and that no site still carries a fail-deadly
``"kill" if … not in live_ids`` fallback — proves all five.

Hermetic: a temp ``ANCHOR_DATA_DIR`` + explicit records — never touches the live
``.anchor`` store or any real process. Stdlib + pytest only.
"""
import importlib
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent


class FakeProbe:
    def __init__(self, times=None):
        self.times = dict(times or {})

    def creation_time(self, pid):
        return self.times.get(pid)


def _running(session_id, **over):
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
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    import paths
    importlib.reload(paths)
    import session_registry
    importlib.reload(session_registry)
    import reaper
    importlib.reload(reaper)
    return reaper


# ── classify_record: every fault → a NON-kill sentinel ───────────────────────

def test_classify_record_none_snapshot_abstains(reaper_mod):
    r = reaper_mod
    rec = _running("a")
    assert r.classify_record(rec, None) == r.VERDICT_ABSTAIN
    assert r.classify_record(rec, None) != r.VERDICT_KILL


def test_classify_record_degraded_snapshot_abstains(reaper_mod, monkeypatch):
    """A DEGRADED snapshot (a default fetch of the running records threw) →
    abstain, never kill — even for a record that would otherwise classify kill."""
    r = reaper_mod
    import session_registry
    def _boom(*a, **k):
        raise RuntimeError("registry unavailable")
    monkeypatch.setattr(session_registry, "list_sessions", _boom)
    snap = r.build_snapshot(attached_pty_ids=None, records=None)
    assert snap.degraded is True
    orphan = _running("orphan", pid=2)  # would be kill against a good snapshot
    assert r.classify_record(orphan, snap) == r.VERDICT_ABSTAIN


def test_classify_record_owner_computation_throws_abstains(reaper_mod, monkeypatch):
    """If the owner-set computation itself THROWS, classify_record catches it and
    abstains (never a kill)."""
    r = reaper_mod
    def _boom(_snap):
        raise RuntimeError("owner enumeration blew up")
    monkeypatch.setattr(r, "live_owner_ids", _boom)
    orphan = _running("orphan", pid=2)
    snap = r.build_snapshot(attached_pty_ids=set(), records=[orphan],
                            job_active=lambda _s: False, probe=FakeProbe({2: 5.0}))
    assert r.classify_record(orphan, snap) == r.VERDICT_ABSTAIN


def test_classify_record_partial_map_never_kills(reaper_mod):
    """A record absent from the positive-liveness map is never classified kill —
    the missing identity resolves to a non-destructive verdict."""
    r = reaper_mod
    ghost = _running("ghost", pid=9)
    # A snapshot built WITHOUT this record → its entry is missing (partial).
    snap = r.build_snapshot(attached_pty_ids=set(), records=[_running("other", pid=1)],
                            job_active=lambda _s: False, probe=FakeProbe({1: 5.0}))
    assert r.classify_record(ghost, snap) != r.VERDICT_KILL


# ── kill_authorized: every fault → NOT authorized ────────────────────────────

def test_kill_authorized_none_snapshot_not_authorized(reaper_mod):
    r = reaper_mod
    assert r.kill_authorized(_running("a"), None) is False


def test_kill_authorized_degraded_snapshot_not_authorized(reaper_mod, monkeypatch):
    r = reaper_mod
    import session_registry
    monkeypatch.setattr(session_registry, "list_sessions",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError()))
    snap = r.build_snapshot(records=None)
    assert snap.degraded is True
    assert r.kill_authorized(_running("dead", pid=2), snap) is False


def test_kill_authorized_revalidation_fault_aborts(reaper_mod):
    """A re-validation callable that itself throws is uncertainty → NOT
    authorized (a failed recheck can never green-light a kill)."""
    r = reaper_mod
    rec = _running("dead", pid=500)
    snap = r.build_snapshot(attached_pty_ids=set(), records=[rec],
                            job_active=lambda _s: False, probe=FakeProbe({}))
    def _boom(_rec):
        raise RuntimeError("recheck failed")
    assert r.kill_authorized(rec, snap, revalidate=_boom) is False


def test_revalidate_target_fault_aborts(reaper_mod, monkeypatch):
    """If the fresh re-probe snapshot cannot be built, revalidate_target returns
    True (ABORT) — never proceed on a failed recheck."""
    r = reaper_mod
    def _boom(*a, **k):
        raise RuntimeError("cannot rebuild snapshot")
    monkeypatch.setattr(r, "build_snapshot", _boom)
    assert r.revalidate_target(_running("x", pid=1)) is True


# ── the armed-daemon site: owner_ids_or_abstain keeps everything on a fault ──

def test_owner_ids_or_abstain_degraded_keeps_all(reaper_mod, monkeypatch):
    """The most dangerous site: on a DEGRADED snapshot the provider returns EVERY
    running id as owned so the sweep classifies them all alive → kills nothing."""
    r = reaper_mod
    import session_registry
    monkeypatch.setattr(session_registry, "list_sessions",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError()))
    running = [_running("s1", pid=1), _running("s2", pid=2)]
    snap = r.build_snapshot(records=None)
    assert snap.degraded is True
    owned = r.owner_ids_or_abstain(snap, running)
    assert owned == {"s1", "s2"}


def test_owner_ids_or_abstain_none_keeps_all(reaper_mod):
    r = reaper_mod
    running = [_running("s1", pid=1), _running("s2", pid=2)]
    assert r.owner_ids_or_abstain(None, running) == {"s1", "s2"}


def test_owner_ids_or_abstain_good_snapshot_is_canonical(reaper_mod):
    """When the snapshot is healthy, the provider returns the CANONICAL owner set
    (an orphan is NOT force-owned — the hunter is not neutered)."""
    r = reaper_mod
    owned_rec = _running("owned", pid=1)
    orphan = _running("orphan", pid=2)
    snap = r.build_snapshot(attached_pty_ids={"owned"}, records=[owned_rec, orphan],
                            job_active=lambda _s: False,
                            probe=FakeProbe({1: 5.0, 2: 5.0}))
    assert snap.degraded is False
    owned = r.owner_ids_or_abstain(snap, [owned_rec, orphan])
    assert owned == {"owned"}       # the orphan is NOT protected here


# ── STUB-GATE: no call site carries a fail-deadly fallback ───────────────────

def test_no_fail_deadly_fallback_at_call_sites():
    """Grep gate: fail the build if any of the five call sites still resolves a
    classify FAULT to a "kill"/freeze (the fail-deadly fallback #1 this wave
    fixes). Every fault must resolve to OWNED/alive."""
    src = (_REPO_ROOT / "anchor_gui.py").read_text(encoding="utf-8")
    # The exact fail-deadly fallback patterns that used to live at the banner,
    # the Swarm & Owner View freeze, and the brief.
    assert '"kill" if (sid and sid not in live_ids)' not in src, \
        "banner still has a fail-deadly classify fallback"
    assert '"kill" if sid not in live_ids' not in src, \
        "brief still has a fail-deadly classify fallback"
    assert "is_orphaned = (sid not in live_ids)" not in src, \
        "Swarm & Owner View still freezes on a classify fault"
    # The armed daemon provider must abstain via owner_ids_or_abstain, never the
    # bare narrower attached set on a fault.
    assert "reaper.owner_ids_or_abstain(" in src, \
        "the armed daemon provider must route through owner_ids_or_abstain"
    # The boot reconcile builds its snapshot from EXPLICIT records (so a default
    # fetch can never degrade it into a spurious mass-reconcile).
    assert "reaper.live_pid_ids(" in src


def test_boot_reconcile_uses_explicit_records():
    """The boot-reconcile snapshot passes records= explicitly (no default fetch
    inside build_snapshot), so it cannot silently degrade."""
    src = (_REPO_ROOT / "anchor_gui.py").read_text(encoding="utf-8")
    # The reconcile block builds the snapshot with an explicit records= kwarg.
    idx = src.find("_snap_boot = reaper.build_snapshot(")
    assert idx != -1
    window = src[idx:idx + 400]
    assert "records=" in window
