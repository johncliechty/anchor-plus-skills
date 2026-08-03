"""zombie-hunter v2 — pure verdict core + sweeper + daemon.

Locks the zombie-hunter contract WITHOUT touching any real process:

  - :func:`zombie_hunter.classify` returns each exact verdict string for the
    six cases (skip / abstain / reap_dead / reap_recycled / alive / kill),
    using a FAKE probe (a tiny pid->creation_time dict).
  - :func:`zombie_hunter.sweep` acts on a temp registry: killer is called ONLY
    for the orphan ("kill") case (exactly once, right pid); killed+reaped
    records become STATUS_IDLE; "alive"/"abstain" records are UNCHANGED; a
    dry-run (``apply=False``) classifies but mutates nothing and calls no killer.
  - the daemon is OFF unless armed: ``start_hunter(enabled=False)`` returns None
    and starts no thread; ``enabled=True`` starts one thread that ``stop_hunter``
    ends.
  - a Windows integration test exercises the REAL ``proc_probe`` on this process.

Hermetic: a temp ``ANCHOR_DATA_DIR`` so it never touches the live ``.anchor``
store or any real process. Stdlib + pytest only.
"""
import importlib
import os
import sys
import time

import pytest


# ── Fakes (no real process needed) ───────────────────────────────────────────

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
def zh():
    """The freshly-imported zombie_hunter + session_registry modules."""
    import zombie_hunter
    import session_registry
    return zombie_hunter, session_registry


# ── classify: one test per verdict (exact string) ────────────────────────────

def _running(**over):
    """A minimal RUNNING normalized-shape record with identity present."""
    import session_registry
    rec = {
        "session_id": "s1",
        "status": session_registry.STATUS_RUNNING,
        "pid": 1000,
        "proc_create_time": 5000.0,
        "crypt_token": "tok",
    }
    rec.update(over)
    return rec


def test_classify_skip(zh):
    zhmod, reg = zh
    rec = _running(status=reg.STATUS_IDLE)
    assert zhmod.classify(rec, set(), probe=FakeProbe()) == "skip"


def test_classify_abstain_missing_token(zh):
    zhmod, _ = zh
    rec = _running(crypt_token="")
    assert zhmod.classify(rec, set(), probe=FakeProbe({1000: 5000.0})) == "abstain"


def test_classify_abstain_missing_pid(zh):
    zhmod, _ = zh
    rec = _running(pid=None)
    assert zhmod.classify(rec, set(), probe=FakeProbe()) == "abstain"


def test_classify_abstain_ctime_none(zh):
    zhmod, _ = zh
    rec = _running(proc_create_time=None)
    assert zhmod.classify(rec, set(), probe=FakeProbe({1000: 5000.0})) == "abstain"


def test_classify_reap_dead(zh):
    zhmod, _ = zh
    rec = _running()
    # Probe has no entry for the pid -> creation_time None -> process gone.
    assert zhmod.classify(rec, set(), probe=FakeProbe({})) == "reap_dead"


def test_classify_reap_recycled(zh):
    zhmod, _ = zh
    rec = _running()
    # Live pid but a DIFFERENT creation time (> tol) -> recycled.
    probe = FakeProbe({1000: 9999.0})
    assert zhmod.classify(rec, set(), probe=probe) == "reap_recycled"


def test_classify_alive(zh):
    zhmod, _ = zh
    rec = _running()
    probe = FakeProbe({1000: 5000.0})
    # Identity matches AND session is attached -> alive.
    assert zhmod.classify(rec, {"s1"}, probe=probe) == "alive"


def test_classify_kill(zh):
    zhmod, _ = zh
    rec = _running()
    probe = FakeProbe({1000: 5000.0})
    # Identity matches but NOT attached -> orphan -> kill. (within tol)
    probe.times[1000] = 5000.0 + 1.0
    assert zhmod.classify(rec, set(), probe=probe) == "kill"


# ── sweep over a temp registry ───────────────────────────────────────────────

@pytest.fixture
def registry_env(tmp_path, monkeypatch):
    """A temp ANCHOR_DATA_DIR with one record of each verdict kind seeded."""
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))

    import paths
    importlib.reload(paths)
    import session_registry
    importlib.reload(session_registry)
    import zombie_hunter
    importlib.reload(zombie_hunter)

    R = session_registry.STATUS_RUNNING
    # kill: identity matches, NOT attached.
    session_registry.register_session(
        "p", "build", status=R, session_id="kill",
        pid=1001, proc_create_time=5000.0, crypt_token="tok")
    # reap_dead: probe returns None for its pid.
    session_registry.register_session(
        "p", "build", status=R, session_id="dead",
        pid=1002, proc_create_time=6000.0, crypt_token="tok")
    # reap_recycled: live pid, mismatched creation time.
    session_registry.register_session(
        "p", "build", status=R, session_id="recyc",
        pid=1003, proc_create_time=7000.0, crypt_token="tok")
    # abstain: missing token.
    session_registry.register_session(
        "p", "build", status=R, session_id="abst",
        pid=1004, proc_create_time=8000.0, crypt_token="")
    # alive: identity matches AND attached.
    session_registry.register_session(
        "p", "build", status=R, session_id="alive",
        pid=1005, proc_create_time=8500.0, crypt_token="tok")
    # A non-running record must be ignored entirely.
    session_registry.register_session(
        "p", "build", status=session_registry.STATUS_IDLE, session_id="parked",
        pid=1006, proc_create_time=1.0, crypt_token="tok")

    probe = FakeProbe({
        1001: 5000.0,   # kill: matches
        # 1002 absent      -> reap_dead
        1003: 9999.0,   # recyc: mismatch
        1004: 8000.0,   # abstain (but no token -> never reaches probe)
        1005: 8500.0,   # alive: matches
    })
    return {
        "reg": session_registry, "zh": zombie_hunter, "probe": probe,
        "data": data, "live": {"alive"},
    }


def test_sweep_applies_actions(registry_env):
    reg = registry_env["reg"]
    zhmod = registry_env["zh"]
    killer = FakeKiller()

    report = zhmod.sweep(registry_env["live"], probe=registry_env["probe"],
                         killer=killer, apply=True)

    # killer called EXACTLY once, on the orphan's pid.
    assert killer.calls == [1001]

    # Report buckets are exactly right.
    assert report["killed"] == ["kill"]
    assert report["reaped_dead"] == ["dead"]
    assert report["reaped_recycled"] == ["recyc"]
    assert report["abstained"] == ["abst"]
    assert report["alive"] == ["alive"]
    assert report["total"] == 5          # the parked/idle one is not counted
    assert isinstance(report["swept_at"], float)

    # Killed + reaped records are now IDLE.
    assert reg.get_session("kill")["status"] == reg.STATUS_IDLE
    assert reg.get_session("dead")["status"] == reg.STATUS_IDLE
    assert reg.get_session("recyc")["status"] == reg.STATUS_IDLE
    # Abstain + alive are UNCHANGED (still running).
    assert reg.get_session("abst")["status"] == reg.STATUS_RUNNING
    assert reg.get_session("alive")["status"] == reg.STATUS_RUNNING

    # The report was persisted for the dashboard.
    persisted = registry_env["data"] / ".anchor" / "zombie_hunter_last.json"
    assert persisted.exists()


def test_sweep_dry_run_no_mutation_no_kill(registry_env):
    reg = registry_env["reg"]
    zhmod = registry_env["zh"]
    killer = FakeKiller()

    report = zhmod.sweep(registry_env["live"], probe=registry_env["probe"],
                         killer=killer, apply=False)

    # No kills, no mutations.
    assert killer.calls == []
    for sid in ("kill", "dead", "recyc", "abst", "alive"):
        assert reg.get_session(sid)["status"] == reg.STATUS_RUNNING

    # But the report still classifies correctly.
    assert report["killed"] == ["kill"]
    assert report["reaped_dead"] == ["dead"]
    assert report["reaped_recycled"] == ["recyc"]
    assert report["abstained"] == ["abst"]
    assert report["alive"] == ["alive"]

    # Dry-run does NOT persist a report.
    persisted = registry_env["data"] / ".anchor" / "zombie_hunter_last.json"
    assert not persisted.exists()


# ── daemon: OFF by default; armed starts/stops one thread ─────────────────────

def test_start_hunter_disabled_returns_none(registry_env):
    zhmod = registry_env["zh"]
    import threading
    n_before = threading.active_count()
    t = zhmod.start_hunter(lambda: set(), interval_sec=0.01, enabled=False)
    assert t is None
    assert threading.active_count() == n_before


def test_start_hunter_enabled_starts_and_stops(registry_env):
    zhmod = registry_env["zh"]
    zhmod.stop_hunter()  # ensure clean global state
    try:
        t = zhmod.start_hunter(lambda: set(), interval_sec=0.02, enabled=True)
        assert t is not None
        assert t.is_alive()
        # A second call is a no-op returning the SAME running thread.
        t2 = zhmod.start_hunter(lambda: set(), interval_sec=0.02, enabled=True)
        assert t2 is t
    finally:
        zhmod.stop_hunter()
    t.join(timeout=5)
    assert not t.is_alive()


def test_start_hunter_env_arms(registry_env, monkeypatch):
    zhmod = registry_env["zh"]
    zhmod.stop_hunter()
    # When ANCHOR_ZOMBIE_HUNTER is unset, starting is enabled by default (runs in dry-run mode).
    monkeypatch.delenv("ANCHOR_ZOMBIE_HUNTER", raising=False)
    try:
        t = zhmod.start_hunter(lambda: set(), interval_sec=0.02)
        assert t is not None and t.is_alive()
    finally:
        zhmod.stop_hunter()
    if t:
        t.join(timeout=5)

    # When ANCHOR_ZOMBIE_HUNTER is "1", starting is also enabled.
    monkeypatch.setenv("ANCHOR_ZOMBIE_HUNTER", "1")
    try:
        t = zhmod.start_hunter(lambda: set(), interval_sec=0.02)
        assert t is not None and t.is_alive()
    finally:
        zhmod.stop_hunter()
    t.join(timeout=5)
    assert not t.is_alive()


# ── Windows integration: the REAL probe on this process ───────────────────────

@pytest.mark.skipif(sys.platform != "win32", reason="Win32 probe is Windows-only")
def test_proc_probe_real_process():
    import proc_probe
    ct = proc_probe.creation_time(os.getpid())
    assert isinstance(ct, float)
    # Our own process started within the last few hours.
    assert 0 <= (time.time() - ct) < 6 * 3600
    # A PID that cannot exist -> None.
    assert proc_probe.creation_time(999999999) is None
    # We are obviously alive.
    assert proc_probe.is_alive(os.getpid()) is True


# ── Phase 1: spawn captures process identity (so classify stops ABSTAINing) ────
#
# These lock the ONE missing piece of the zombie engine: the spawn path now
# mints a crypt token, injects it into the child env, and (once the child has a
# pid) records that pid's creation time, then persists the triple into the
# registry via terminal_session. Before Phase 1 every RUNNING record had no
# identity, so ``classify`` returned ABSTAIN for everything. Hermetic: a fake
# pid-bearing backend + a faked ``proc_probe.creation_time`` — no real OS spawn,
# no real claude/agy process, no git worktree.


def _reload_identity_stack(data_dir, monkeypatch):
    """Reload the dependency stack against a temp ANCHOR_DATA_DIR (stub PTY)."""
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data_dir))
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    import paths
    importlib.reload(paths)
    import pty_manager
    importlib.reload(pty_manager)
    import rnd_registry
    importlib.reload(rnd_registry)
    import session_registry
    importlib.reload(session_registry)
    import worktrees
    importlib.reload(worktrees)
    import lanes
    importlib.reload(lanes)
    import terminal_session
    importlib.reload(terminal_session)
    import zombie_hunter
    importlib.reload(zombie_hunter)
    return pty_manager, rnd_registry, session_registry, terminal_session, zombie_hunter


def test_pty_start_captures_token_pid_and_create_time(tmp_path, monkeypatch):
    """pty_manager.start mints a token, injects it into the child env, and (with
    a pid) records the create time — all stored on the child object."""
    pty, _rnd, _reg, _ts, _zh = _reload_identity_stack(tmp_path / "data", monkeypatch)
    import proc_probe

    class _PidStubBackend:
        name = "pidstub"

        def start(self, cmd, cwd=None, env=None):
            child = pty._StubChild(cmd, cwd=cwd, env=env)
            child.pid = 4242            # a real backend would carry the OS pid
            child.spawn_env = env       # capture the injected env for assertion
            return child

    monkeypatch.setattr(pty, "select_backend", lambda: _PidStubBackend())
    monkeypatch.setattr(proc_probe, "creation_time", lambda pid: 111222.5)

    sid = pty.start(["claude"], cwd=str(tmp_path))
    child = pty._LIVE[sid]
    # Identity is captured on the child …
    assert child.crypt_token and len(child.crypt_token) == 32
    assert child.pid == 4242
    assert child.proc_create_time == 111222.5
    # … and the SAME token was injected into the spawned child's environment.
    assert child.spawn_env["ANCHOR_SESSION_ID_CRYPT_TOKEN"] == child.crypt_token


def test_pty_start_stub_without_pid_is_abstain_safe(tmp_path, monkeypatch):
    """A child with no pid still gets a token, but proc_create_time stays None —
    so classify ABSTAINs (never kills). This is the safe default for the stub."""
    pty, _rnd, _reg, _ts, zh = _reload_identity_stack(tmp_path / "data", monkeypatch)
    sid = pty.start(["claude"], cwd=str(tmp_path))
    child = pty._LIVE[sid]
    assert child.crypt_token                       # token always minted
    assert getattr(child, "pid", None) is None     # stub has no OS pid
    assert child.proc_create_time is None
    rec = {"session_id": sid, "status": _reg_status_running(),
           "pid": None, "proc_create_time": child.proc_create_time,
           "crypt_token": child.crypt_token}
    assert zh.classify(rec, {sid}, probe=FakeProbe()) == "abstain"


def _reg_status_running():
    import session_registry
    return session_registry.STATUS_RUNNING


def test_start_session_persists_identity_and_classify_is_non_abstain(tmp_path, monkeypatch):
    """End-to-end glue: start_session → register_session persists the spawn
    identity, and zombie_hunter.classify on that record is NON-ABSTAIN
    (ALIVE when attached, KILL when orphaned)."""
    pty, rnd, reg, ts, zh = _reload_identity_stack(tmp_path / "data", monkeypatch)
    import proc_probe

    # Fake pid-bearing backend + deterministic create-time (no real spawn).
    class _PidStubBackend:
        name = "pidstub"

        def start(self, cmd, cwd=None, env=None):
            child = pty._StubChild(cmd, cwd=cwd, env=env)
            child.pid = 5150
            child.spawn_env = env
            return child

    monkeypatch.setattr(pty, "select_backend", lambda: _PidStubBackend())
    monkeypatch.setattr(proc_probe, "creation_time", lambda pid: 777000.0)

    # Fake the worktree so the test needs no git (identity capture is the SUT).
    wt = tmp_path / "wt"
    wt.mkdir()
    monkeypatch.setattr(ts._wt, "create_worktree",
                        lambda project_id, sid: {"ok": True, "path": str(wt), "branch": "b"})
    monkeypatch.setattr(ts._wt, "remove_worktree", lambda *a, **k: None)

    proj = rnd.add_project("Temp", str(tmp_path / "repo"), scaffold=False)
    record = ts.start_session(proj["id"], "plan", backend="claude")
    sid = record["session_id"]

    # The PERSISTED registry record now carries the full identity triple.
    stored = reg.get_session(sid)
    assert stored["crypt_token"] and len(stored["crypt_token"]) == 32
    assert stored["pid"] == 5150
    assert stored["proc_create_time"] == 777000.0

    # classify is no longer forced to ABSTAIN: attached -> alive, orphaned -> kill.
    probe = FakeProbe({5150: 777000.0})
    assert zh.classify(stored, {sid}, probe=probe) == "alive"
    assert zh.classify(stored, set(), probe=probe) == "kill"


# ── v13 Wave 1 (#12a): zombie radar page emits a bounded auto-refresh hook ───

def test_zombie_report_emits_bounded_auto_refresh_hook(tmp_path, monkeypatch):
    """``GET /api/rnd/zombie_hunter_report`` must embed a BOUNDED live
    auto-refresh hook so the radar updates during a sweep WITHOUT a manual
    reload. Before #12a the page was static (no setInterval/SSE)."""
    import importlib as _il
    import threading as _threading
    import time as _time
    import urllib.request as _ureq

    _reload_identity_stack(tmp_path / "data", monkeypatch)
    import zombie_hunter as _zh
    import anchor_gui as _gui
    _gui = _il.reload(_gui)

    # Seed a FRESH sweep report so the endpoint serves the cached view and skips
    # the live-process (tasklist/ps) fallback — keeps the test fast + hermetic.
    _zh._persist_report({
        "swept_at": _time.time(), "total": 0,
        "killed": [], "alive": [], "abstained": [],
        "reaped_dead": [], "reaped_recycled": [],
    })

    srv = _gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777
    t = _threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        with _ureq.urlopen(
                f"http://127.0.0.1:{port}/api/rnd/zombie_hunter_report",
                timeout=10) as resp:
            assert resp.status == 200
            body = resp.read().decode("utf-8")
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(timeout=5)

    # The auto-refresh hook is present …
    assert "zombie-auto-refresh" in body
    assert "setInterval" in body
    assert "location.reload" in body
    # … and it is BOUNDED (a max-tick guard, not infinite churn).
    assert "ZOMBIE_MAX_TICKS" in body
