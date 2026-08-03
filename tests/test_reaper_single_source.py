"""reaper Wave 1 — one canonical liveness snapshot + single-source stub-gate.

Locks the structural foundation of the *zombie-hunter → safe-to-arm* build:

  * :mod:`reaper` exists with a FROZEN :class:`reaper.LivenessSnapshot` (the five
    contract fields) built EXACTLY ONCE per sweep by :func:`reaper.build_snapshot`;
  * :func:`reaper.live_owner_ids` is a PURE function of the snapshot (rebuilt
    fresh each sweep, no drift), and :func:`reaper.classify` takes the live-owner
    set AND the positive-liveness map as its ONLY inputs (compile-forced);
  * the OWNER-ENUMERATION CONTRACT: a re-parented grandchild recorded at launch
    stays OWNED after its parent exits (ownership is enumerated from the recorded
    launch-time identity/job, never from live OS parentage);
  * a STUB-GATE grep proving every ``classify``/owner call site in
    ``anchor_gui.py`` consumes the single shared snapshot/provider — the build
    FAILS if a sixth consumer bypasses it.

Hermetic: a temp ``ANCHOR_DATA_DIR`` and explicit records/probes — never touches
the live ``.anchor`` store or any real process. Stdlib + pytest only.
"""
import dataclasses
import importlib
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent


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


# ── The frozen snapshot + its five contract fields ───────────────────────────

def test_liveness_snapshot_is_frozen_with_contract_fields(reaper_mod):
    r = reaper_mod
    snap = r.build_snapshot(attached_pty_ids={"a"}, records=[], probe=r.NO_PROBE)
    assert dataclasses.is_dataclass(snap)
    for f in ("attached_pty_ids", "job_owned_ids", "parent_owned_ids",
              "pid_identity", "positive_liveness"):
        assert hasattr(snap, f), f"snapshot missing contract field {f!r}"
    # Frozen: attributes cannot be reassigned.
    with pytest.raises(dataclasses.FrozenInstanceError):
        snap.attached_pty_ids = frozenset()
    # The id-sets are immutable frozensets.
    assert isinstance(snap.attached_pty_ids, frozenset)
    assert isinstance(snap.job_owned_ids, frozenset)
    assert isinstance(snap.parent_owned_ids, frozenset)
    # The maps are read-only (MappingProxyType).
    with pytest.raises(TypeError):
        snap.positive_liveness["x"] = None
    with pytest.raises(TypeError):
        snap.pid_identity[1] = None


# ── live_owner_ids: pure union over the snapshot ─────────────────────────────

def test_live_owner_ids_pure_union(reaper_mod):
    r = reaper_mod
    snap = r.LivenessSnapshot(
        attached_pty_ids=frozenset({"a"}),
        job_owned_ids=frozenset({"b"}),
        parent_owned_ids=frozenset({"c"}),
    )
    out = r.live_owner_ids(snap)
    assert out == {"a", "b", "c"}
    # A fresh set each call — mutating the result never touches the snapshot.
    out.add("intruder")
    assert "intruder" not in r.live_owner_ids(snap)


def test_live_owner_ids_superset_of_attached(reaper_mod):
    r = reaper_mod
    snap = r.build_snapshot(attached_pty_ids={"a", "b"}, records=[],
                            job_active=lambda _s: False, probe=r.NO_PROBE)
    assert {"a", "b"} <= r.live_owner_ids(snap)


# ── OWNER-ENUMERATION CONTRACT (GWT 1): re-parented grandchild stays owned ────

def test_reparented_grandchild_stays_owned_after_parent_exit(reaper_mod):
    """A session whose backend PID was re-parented to PID 1 after its launcher
    exited stays OWNED via its recorded launch-time identity/job — never orphaned
    merely because its OS parent exited."""
    r = reaper_mod
    # The launcher/parent session has exited: it is not among the running records
    # at all. The grandchild carries its recorded launch identity (pid) and its
    # owning JOB is still active. Ownership is enumerated from that job, NOT from
    # live OS parentage, so the grandchild remains owned.
    gc = _running("gc", pid=4242)
    snap = r.build_snapshot(attached_pty_ids=set(), records=[gc],
                            job_active=lambda s: s == "gc", probe=r.NO_PROBE)
    assert "gc" in r.live_owner_ids(snap)


def test_child_of_live_parent_stays_owned(reaper_mod):
    """Transitive parent ownership: a child whose live parent owns it is owned."""
    r = reaper_mod
    parent = _running("p", pid=10)
    child = _running("ch", pid=11, parent_session_id="p")
    snap = r.build_snapshot(attached_pty_ids=set(), records=[parent, child],
                            job_active=lambda s: s == "p", probe=r.NO_PROBE)
    assert {"p", "ch"} <= r.live_owner_ids(snap)


# ── OWNER-ENUMERATION CONTRACT (GWT 3): set rebuilt fresh each sweep ──────────

def test_owner_set_rebuilt_fresh_each_sweep(reaper_mod):
    r = reaper_mod
    recs = [_running("w", pid=7)]
    ja = lambda s: s == "w"
    snap1 = r.build_snapshot(attached_pty_ids=set(), records=recs,
                             job_active=ja, probe=r.NO_PROBE)
    snap2 = r.build_snapshot(attached_pty_ids=set(), records=recs,
                             job_active=ja, probe=r.NO_PROBE)
    o1 = r.live_owner_ids(snap1)
    o2 = r.live_owner_ids(snap2)
    assert o1 == o2 == {"w"}
    # Each sweep's snapshot is independent + immutable: mutating one derived set
    # never drifts into the other snapshot's owner computation.
    o1.add("intruder")
    assert "intruder" not in r.live_owner_ids(snap1)
    assert "intruder" not in r.live_owner_ids(snap2)
    assert isinstance(snap1.parent_owned_ids, frozenset)


# ── classify: live-owner set + positive-liveness map are its ONLY inputs ──────

def test_classify_requires_owner_and_positive_liveness(reaper_mod):
    """GWT 2 (compile-force): a consumer that omits the live-owner set or the
    positive-liveness map is compile-forced to supply them (TypeError)."""
    r = reaper_mod
    rec = _running("a")
    with pytest.raises(TypeError):
        r.classify(rec, set())          # missing positive_liveness
    with pytest.raises(TypeError):
        r.classify(rec)                 # missing both


def test_classify_record_verdicts_from_snapshot(reaper_mod):
    """The single classify entry (classify_record) reaches every verdict against
    the ONE snapshot's live-owner set + positive-liveness map."""
    r = reaper_mod
    alive = _running("a", pid=1)         # owned (attached) + identity matches
    orphan = _running("b", pid=2)        # identity matches, NO live owner
    dead = _running("c", pid=3)          # PID no longer resolves
    recyc = _running("d", pid=4)         # PID live but creation-time mismatch
    absta = _running("e", pid=5, crypt_token="")  # missing identity
    probe = FakeProbe({1: 5.0, 2: 5.0, 4: 9999.0, 5: 5.0})  # 3 absent -> dead
    snap = r.build_snapshot(
        attached_pty_ids={"a"},
        records=[alive, orphan, dead, recyc, absta],
        job_active=lambda _s: False,
        probe=probe,
    )
    assert r.classify_record(alive, snap) == r.VERDICT_ALIVE
    assert r.classify_record(orphan, snap) == r.VERDICT_KILL
    assert r.classify_record(dead, snap) == r.VERDICT_REAP_DEAD
    assert r.classify_record(recyc, snap) == r.VERDICT_REAP_RECYCLED
    assert r.classify_record(absta, snap) == r.VERDICT_ABSTAIN
    # A non-running record is SKIP-ed.
    parked = _running("z", status="idle")
    assert r.classify_record(parked, snap) == r.VERDICT_SKIP


def test_live_pid_ids_is_process_liveness_not_ownership(reaper_mod):
    """live_pid_ids reports PID-alive (identity present) regardless of ownership —
    so the boot reconcile leaves a live-PID orphan RUNNING (only dead PIDs go)."""
    r = reaper_mod
    orphan = _running("orphan", pid=2)   # alive PID but NO owner
    dead = _running("dead", pid=3)       # PID gone
    probe = FakeProbe({2: 5.0})          # 3 absent -> dead
    snap = r.build_snapshot(attached_pty_ids=set(), records=[orphan, dead],
                            job_active=lambda _s: False, probe=probe)
    alive_pids = r.live_pid_ids(snap)
    assert "orphan" in alive_pids        # live PID -> left running at boot
    assert "dead" not in alive_pids      # dead PID -> reconciled
    # The orphan is NOT owned, but IS PID-alive: the two notions are distinct.
    assert "orphan" not in r.live_owner_ids(snap)


# ── STUB-GATE: every call site consumes the single shared provider ───────────

def test_all_call_sites_use_single_shared_provider():
    """Grep gate: fail the build if any classify/owner call site in anchor_gui.py
    bypasses the ONE shared snapshot/provider (a sixth consumer that hand-rolls
    the inputs, or reaches back into the legacy per-site discriminators)."""
    src = (_REPO_ROOT / "anchor_gui.py").read_text(encoding="utf-8")

    # No call site may reach the legacy per-site discriminators directly.
    assert "zombie_hunter.classify(" not in src, \
        "a call site still calls zombie_hunter.classify — migrate to reaper"
    assert "zombie_hunter.live_owner_ids(" not in src, \
        "a call site still calls zombie_hunter.live_owner_ids — migrate to reaper"

    # Every classify goes through the shared snapshot provider (classify_record),
    # never a hand-rolled reaper.classify(...) with per-site args.
    assert "reaper.classify(" not in src, \
        "a call site hand-rolls reaper.classify args — use reaper.classify_record"

    # The three per-record classify call sites: banner, Swarm & Owner View, brief.
    assert src.count("reaper.classify_record(") == 3

    # All FIVE call sites build the ONE snapshot per sweep (banner, view, brief,
    # boot reconcile, armed daemon provider).
    assert src.count("reaper.build_snapshot(") == 5

    # The owner-set + PID-alive derivations come from the snapshot, not per-site.
    assert src.count("reaper.live_owner_ids(") >= 4
    assert src.count("reaper.live_pid_ids(") >= 1


def test_zombie_hunter_shims_delegate_to_reaper(reaper_mod):
    """The legacy zombie_hunter.classify / live_owner_ids stay green but are now
    thin shims over the single reaper source (backward-compatible)."""
    import zombie_hunter
    importlib.reload(zombie_hunter)
    # live_owner_ids delegates: a job-owned session with no stream is owned.
    live = zombie_hunter.live_owner_ids(set(), records=[_running("w")],
                                        job_active=lambda s: s == "w")
    assert "w" in live
    # classify delegates: identity matches + owned -> alive; not owned -> kill.
    rec = _running("w")
    probe = FakeProbe({1000: 5.0})
    assert zombie_hunter.classify(rec, {"w"}, probe=probe) == "alive"
    assert zombie_hunter.classify(rec, set(), probe=probe) == "kill"
