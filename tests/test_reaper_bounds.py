"""reaper Wave 4 — bounded blast radius + boot grace + conservative age + safe
lineage walk.

Locks criterion (3): a sweep freezes/kills at most the configured cap per cycle,
never touches a session inside the boot-grace window or of unknown age, and walks
the transitive-parent lineage with a bounded visited-set that abstains on cycles.

Every fixture here is a *would-be-killed* orphan — a RUNNING record whose PID
probes DEAD (no live process), no live owner, no corroborated positive signal —
so :func:`reaper.kill_authorized` is TRUE for it and ONLY a Wave-4 bound can spare
it. That isolates each bound: the cap, the grace window, the unknown-age
protection, and the lineage-cycle integrity check.

Hermetic: a temp ``ANCHOR_DATA_DIR`` + explicit records + a fake probe — never
touches the live ``.anchor`` store or any real process. Stdlib + pytest only.
"""
import importlib
import logging

import pytest


# A fixed epoch so age math is deterministic (never real wall-clock).
NOW = 1_000_000.0


class FakeProbe:
    """A creation-time-only probe. An empty map ⇒ every PID probes DEAD (gone)."""

    def __init__(self, times=None):
        self.times = dict(times or {})

    def creation_time(self, pid):
        return self.times.get(pid)


@pytest.fixture
def reaper_mod(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    # Clear the Wave-4 knobs so each test controls them explicitly.
    for k in ("ANCHOR_REAPER_MAX_ACTIONS_PER_SWEEP",
              "ANCHOR_REAPER_BOOT_GRACE_SECS",
              "ANCHOR_REAPER_LINEAGE_MAX_DEPTH"):
        monkeypatch.delenv(k, raising=False)
    import paths
    importlib.reload(paths)
    import session_registry
    importlib.reload(session_registry)
    import reaper
    importlib.reload(reaper)
    return reaper


_pid_counter = [4000]


def _dead_orphan(session_id, *, created_at, parent="", **over):
    """A RUNNING record that classifies REAP_DEAD (dead PID, no owner, no signal)
    and so is kill_authorized — sparing it must come from a Wave-4 bound alone."""
    _pid_counter[0] += 1
    rec = {
        "session_id": session_id,
        "status": "running",
        "pid": _pid_counter[0],
        "proc_create_time": 5.0,
        "crypt_token": "tok",
        "created_at": created_at,
        "parent_session_id": parent,
        "worktree_path": "",
    }
    rec.update(over)
    return rec


def _snapshot(reaper, records):
    """A healthy snapshot: nobody attached, no owning jobs, every PID dead."""
    return reaper.build_snapshot(
        attached_pty_ids=set(), records=records,
        job_active=lambda _s: False, probe=FakeProbe({}), now=NOW,
    )


# ── sanity: the fixture really IS kill-authorized without the bounds ─────────

def test_fixture_is_kill_authorized(reaper_mod):
    r = reaper_mod
    rec = _dead_orphan("solo", created_at=NOW - 10_000)
    snap = _snapshot(r, [rec])
    assert r.kill_authorized(rec, snap) is True


# ── (1) the blast cap halts a runaway sweep ──────────────────────────────────

def test_blast_cap_halts_runaway_sweep(reaper_mod):
    r = reaper_mod
    recs = [_dead_orphan(f"z{i}", created_at=NOW - 10_000) for i in range(10)]
    snap = _snapshot(r, recs)
    plan = r.plan_sweep(recs, snap, now=NOW, max_actions=3)
    assert plan.cap == 3
    assert len(plan.to_act) == 3
    assert len(plan.deferred) == 7
    # Nothing was spared by a bound — every candidate is either acted-on or
    # deferred, and together they cover the whole runaway.
    assert plan.protected == ()
    assert set(plan.to_act) | set(plan.deferred) == {r_["session_id"] for r_ in recs}


def test_blast_cap_reads_env_knob(reaper_mod, monkeypatch):
    r = reaper_mod
    monkeypatch.setenv("ANCHOR_REAPER_MAX_ACTIONS_PER_SWEEP", "2")
    import paths
    importlib.reload(paths)
    importlib.reload(r)
    recs = [_dead_orphan(f"z{i}", created_at=NOW - 10_000) for i in range(5)]
    snap = _snapshot(r, recs)
    plan = r.plan_sweep(recs, snap, now=NOW)  # cap resolved from env
    assert plan.cap == 2
    assert len(plan.to_act) == 2
    assert len(plan.deferred) == 3


def test_deferred_remainder_is_logged(reaper_mod, caplog):
    r = reaper_mod
    recs = [_dead_orphan(f"z{i}", created_at=NOW - 10_000) for i in range(6)]
    snap = _snapshot(r, recs)
    with caplog.at_level(logging.WARNING, logger="anchor.reaper"):
        r.plan_sweep(recs, snap, now=NOW, max_actions=1)
    assert any("deferr" in rec.message.lower() for rec in caplog.records)


# ── (2) a fresh session inside the boot-grace window survives ────────────────

def test_fresh_session_inside_grace_survives(reaper_mod):
    r = reaper_mod
    # Would be killed (dead orphan) but it was created 5s ago — inside grace.
    fresh = _dead_orphan("fresh", created_at=NOW - 5)
    snap = _snapshot(r, [fresh])
    plan = r.plan_sweep([fresh], snap, now=NOW, grace=300.0, max_actions=5)
    assert "fresh" in plan.protected
    assert "fresh" not in plan.to_act
    assert plan.deferred == ()


def test_boot_grace_boundary_and_env(reaper_mod, monkeypatch):
    r = reaper_mod
    inside = _dead_orphan("inside", created_at=NOW - 100)   # age 100 < 300
    outside = _dead_orphan("outside", created_at=NOW - 500)  # age 500 > 300
    assert r.age_protected(inside, now=NOW, grace=300.0) is True
    assert r.age_protected(outside, now=NOW, grace=300.0) is False
    # Same call resolving the window from the env knob.
    monkeypatch.setenv("ANCHOR_REAPER_BOOT_GRACE_SECS", "600")
    import paths
    importlib.reload(paths)
    importlib.reload(r)
    assert r.age_protected(outside, now=NOW) is True   # now 500 < 600 → protected


# ── (3) unknown-age is never reaped; created_at is required for eligibility ───

def test_unknown_age_never_reaped(reaper_mod):
    r = reaper_mod
    # No registered created_at AND a dead PID (no probeable start) → unknown age.
    ghost = _dead_orphan("ghost", created_at=None)
    ghost.pop("created_at", None)
    snap = _snapshot(r, [ghost])
    assert r.session_age_secs(ghost, snap, now=NOW) is None
    assert r.age_protected(ghost, snap, now=NOW) is True
    plan = r.plan_sweep([ghost], snap, now=NOW, max_actions=5)
    assert "ghost" in plan.protected
    assert "ghost" not in plan.to_act


def test_created_at_required_for_kill_eligibility(reaper_mod):
    r = reaper_mod
    # A live PID start exists (probe returns a time) but NO registered created_at
    # → still PROTECTED: a registered created_at is required for eligibility.
    rec = _dead_orphan("nocreate", created_at=None, pid=7777)
    rec.pop("created_at", None)
    # PID start is available and OLD, but that alone must not make it eligible.
    assert r.age_protected(rec, now=NOW, probe=FakeProbe({7777: NOW - 9999})) is True


def test_age_uses_conservative_youngest_signal(reaper_mod):
    r = reaper_mod
    # created_at is old (age 9999) but the live PID started 10s ago: the youngest
    # defensible signal wins, so the session is treated as YOUNG (age ~10).
    rec = _dead_orphan("recycled", created_at=NOW - 9999, pid=8888)
    age = r.session_age_secs(rec, now=NOW, probe=FakeProbe({8888: NOW - 10}))
    assert age == pytest.approx(10.0, abs=0.5)
    # And so it is protected inside a 300s grace even though created_at looks old.
    assert r.age_protected(rec, now=NOW, grace=300.0,
                           probe=FakeProbe({8888: NOW - 10})) is True


# ── (4) a lineage cycle is flagged by the integrity check and abstained ──────

def test_lineage_cycle_flagged_and_abstained(reaper_mod):
    r = reaper_mod
    a = _dead_orphan("A", created_at=NOW - 10_000, parent="B")
    b = _dead_orphan("B", created_at=NOW - 10_000, parent="A")
    recs = [a, b]
    snap = _snapshot(r, recs)
    plan = r.plan_sweep(recs, snap, now=NOW, max_actions=5)
    # Registry-integrity check flags both members of the cycle …
    assert set(plan.lineage_cycles) == {"A", "B"}
    # … and neither is acted on — the whole branch is PROTECTED (abstain).
    assert "A" not in plan.to_act and "B" not in plan.to_act
    assert set(plan.protected) == {"A", "B"}


def test_find_lineage_cycles_direct(reaper_mod):
    r = reaper_mod
    # A self-loop, a 2-cycle, and a clean chain that must NOT be flagged.
    recs = [
        _dead_orphan("self", created_at=NOW, parent="self"),
        _dead_orphan("x", created_at=NOW, parent="y"),
        _dead_orphan("y", created_at=NOW, parent="x"),
        _dead_orphan("root", created_at=NOW, parent=""),
        _dead_orphan("child", created_at=NOW, parent="root"),
    ]
    flagged = r.find_lineage_cycles(recs)
    assert flagged == {"self", "x", "y"}


def test_lineage_depth_cap_protects_overdeep_chain(reaper_mod):
    r = reaper_mod
    # A long clean chain n0<-n1<-...<-n9 with a depth cap of 3 → over-deep branch
    # is flagged (protected), never walked forever.
    recs = []
    for i in range(10):
        parent = f"n{i-1}" if i > 0 else ""
        recs.append(_dead_orphan(f"n{i}", created_at=NOW, parent=parent))
    flagged = r.find_lineage_cycles(recs, max_depth=3)
    assert flagged, "an over-deep chain must be flagged by the depth cap"


def test_lineage_max_depth_env_knob(reaper_mod, monkeypatch):
    r = reaper_mod
    monkeypatch.setenv("ANCHOR_REAPER_LINEAGE_MAX_DEPTH", "5")
    import paths
    importlib.reload(paths)
    assert paths.reaper_lineage_max_depth() == 5


# ── degraded / None snapshot yields an empty plan (uncertainty never acts) ───

def test_plan_sweep_degraded_snapshot_empty(reaper_mod, monkeypatch):
    r = reaper_mod
    import session_registry
    monkeypatch.setattr(session_registry, "list_sessions",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError()))
    recs = [_dead_orphan("z", created_at=NOW - 10_000)]
    snap = r.build_snapshot(records=None)
    assert snap.degraded is True
    plan = r.plan_sweep(recs, snap, now=NOW, max_actions=5)
    assert plan.to_act == ()
    assert plan.deferred == ()


def test_plan_sweep_none_snapshot_empty(reaper_mod):
    r = reaper_mod
    recs = [_dead_orphan("z", created_at=NOW - 10_000)]
    plan = r.plan_sweep(recs, None, now=NOW, max_actions=5)
    assert plan.to_act == ()
