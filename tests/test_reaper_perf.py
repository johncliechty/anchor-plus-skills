"""reaper Wave 9 — the sweep-cost PERF GATE.

Locks the plan's Wave-9 done-when: *"the perf gate holds"* — sweep time stays
FLAT as ``rnd_jobs/`` grows, because the reaper builds ONE immutable snapshot per
sweep whose ownership is derived from a TARGETED per-session ``job_active`` probe
(a per-``job_id`` ``load_record``), never a global ``rnd_jobs/`` full-scan.

The primary assertions are DETERMINISTIC (not wall-clock): ``build_snapshot``
calls the ownership predicate exactly once per non-attached record (O(records),
independent of how many total jobs exist on disk) and never invokes
``job_runner.list_records`` (the O(all-jobs) scan). A lenient wall-clock ceiling
+ near-linear-scaling sanity guards against an accidental O(N²) regression.

Hermetic: a temp ``ANCHOR_DATA_DIR`` + injected probes/predicates — never a real
process, never the live store. Stdlib + pytest only.
"""
import importlib
import time

import pytest


NOW = 2_000_000.0


class CountingJobActive:
    """An ownership predicate that records how many times it is consulted."""

    def __init__(self, owned=None):
        self.owned = set(owned or ())
        self.calls = 0
        self.seen = []

    def __call__(self, sid):
        self.calls += 1
        self.seen.append(sid)
        return sid in self.owned


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


def _records(n, *, attached_count=0):
    recs = []
    for i in range(n):
        recs.append({
            "session_id": f"s{i}",
            "status": "running",
            "pid": 5000 + i,
            "proc_create_time": 5.0,
            "crypt_token": "tok",
            "created_at": NOW - 100_000,
            "parent_session_id": "",
            "worktree_path": "",
        })
    return recs


# ── (1) ownership probe is O(records), never O(all-jobs) ─────────────────────

def test_job_active_called_once_per_non_attached_record(reaper_mod):
    r = reaper_mod
    recs = _records(300)
    attached = {"s0", "s1", "s2"}          # attached sessions skip the job probe
    ja = CountingJobActive(owned=set())
    r.build_snapshot(attached_pty_ids=attached, records=recs,
                     job_active=ja, probe=r.NO_PROBE, now=NOW)
    # Exactly one probe per record NOT already known-owned via an attached PTY.
    assert ja.calls == len(recs) - len(attached)
    # Never probed the same session twice (no accidental O(records²) re-probe).
    assert len(ja.seen) == len(set(ja.seen))


def test_probe_count_is_flat_as_job_corpus_grows(reaper_mod):
    """The per-sweep ownership-probe count depends ONLY on the record set — it
    does not grow with a large simulated ``rnd_jobs/`` population (build_snapshot
    never enumerates the jobs dir; ownership is a targeted per-session probe)."""
    r = reaper_mod
    recs = _records(150)
    # "rnd_jobs/ grows" is modeled by a job_active whose backing corpus is huge;
    # the probe is still consulted exactly once per record, never per job.
    big_corpus = {f"s{i}" for i in range(150)} | {f"junk{i}" for i in range(50_000)}
    ja = CountingJobActive(owned=big_corpus)
    r.build_snapshot(attached_pty_ids=set(), records=recs,
                     job_active=ja, probe=r.NO_PROBE, now=NOW)
    assert ja.calls == len(recs)           # O(records), NOT O(corpus)


def test_build_snapshot_never_full_scans_rnd_jobs(reaper_mod, monkeypatch):
    """build_snapshot must not call job_runner.list_records (the global scan)."""
    r = reaper_mod
    import job_runner
    scans = {"n": 0}

    def _boom(*a, **k):
        scans["n"] += 1
        raise AssertionError("build_snapshot must not full-scan rnd_jobs/")

    monkeypatch.setattr(job_runner, "list_records", _boom, raising=False)
    recs = _records(200)
    ja = CountingJobActive(owned=set())
    r.build_snapshot(attached_pty_ids=set(), records=recs,
                     job_active=ja, probe=r.NO_PROBE, now=NOW)
    assert scans["n"] == 0


# ── (2) wall-clock: flat/near-linear, generous ceiling (anti-O(N²)) ──────────

def _time_build(r, n):
    recs = _records(n)
    ja = CountingJobActive(owned=set())
    t0 = time.perf_counter()
    r.build_snapshot(attached_pty_ids=set(), records=recs,
                     job_active=ja, probe=r.NO_PROBE, now=NOW)
    return time.perf_counter() - t0


def test_sweep_time_scales_sub_quadratically(reaper_mod):
    r = reaper_mod
    # Warm the code path so the first-call import/JIT cost is not attributed.
    _time_build(r, 50)
    t_small = _time_build(r, 250)
    t_large = _time_build(r, 1000)          # 4× the records
    # Absolute ceiling: even 1000 sessions build well under a second on any host.
    assert t_large < 2.0, f"snapshot build too slow: {t_large:.3f}s for 1000 recs"
    # Near-linear: 4× the records must not cost ~16× (an O(N²) tell). Allow a
    # generous 8× to absorb timer noise while still failing a quadratic blowup.
    # (Guard against a ~0 small-timer with a floor.)
    baseline = max(t_small, 1e-4)
    assert t_large < baseline * 8.0, (
        f"sweep cost scales super-linearly: {t_small:.4f}s -> {t_large:.4f}s")
