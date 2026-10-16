"""reaper Wave 3 — Win32 correctness of the liveness/identity probe.

Locks the *provably-correct probe* contract the positive-proof-of-death kill
predicate and the identity registry lean on (zombie-hunter → safe-to-arm):

  * **Full-width handles** — the ``kernel32`` surface is declared with
    ``HANDLE`` as :data:`ctypes.c_void_p` (never an implicit ``c_int`` that
    truncates a 64-bit handle), and ``proc_probe``'s own code passes a
    high-value handle through unchanged.
  * **STILL_ACTIVE / 259 disambiguation** — death is decided by
    ``WaitForSingleObject`` (``WAIT_OBJECT_0`` = exited vs ``WAIT_TIMEOUT`` =
    running), NEVER inferred from a bare ``GetExitCodeProcess`` == 259.
  * **Denied-open → abstain** — an open failure / ACCESS_DENIED yields
    ``PROBE_UNKNOWN`` so the kill predicate abstains.
  * **Stable identity tuple** — ``(pid, creation_time, image_path)``; a
    creation-time mismatch (recycled PID) forces an abstain, and the reaper
    snapshot carries the image path.
  * **WRITE_LOCK reentrancy** — ``session_registry._save_sessions`` never
    re-acquires ``paths.WRITE_LOCK`` when called under a held lock (proven with
    a plain, NON-reentrant ``threading.Lock``), and a parallel-sweep + user-write
    stress leaves the store intact.

Hermetic: a fake ``proc_probe._win`` seam + a temp ``ANCHOR_DATA_DIR`` — never
touches a real process or the live ``.anchor`` store. Stdlib + pytest only.
"""
import importlib
import json
import sys
import threading

import pytest

import proc_probe


# ── A pure-Python stand-in for the ctypes I/O seam (proc_probe._win) ──────────

class FakeWin:
    """Drives the probe decision logic without a real process.

    ``table`` maps ``pid -> cfg`` where ``cfg`` may set: ``handle`` (default the
    pid), ``want_sync_ok`` (False ⇒ the SYNCHRONIZE-bearing open is denied),
    ``ct`` (creation time), ``img`` (image path), ``wait`` (the
    WaitForSingleObject code), ``exit`` (the GetExitCodeProcess value). A pid
    absent from the table means OpenProcess fails entirely.
    """

    def __init__(self, table):
        self.table = table
        self.opened = []   # (pid, want_sync)
        self.waited = []   # handles passed to wait()
        self.closed = []   # handles passed to close()

    def open(self, pid, want_sync=False):
        self.opened.append((pid, want_sync))
        cfg = self.table.get(pid)
        if cfg is None:
            return None
        if want_sync and not cfg.get("want_sync_ok", True):
            return None  # SYNCHRONIZE denied → open fails
        return cfg.get("handle", pid)

    def _cfg_for_handle(self, handle):
        for pid, cfg in self.table.items():
            if cfg.get("handle", pid) == handle:
                return cfg
        return None

    def creation_time(self, handle):
        cfg = self._cfg_for_handle(handle)
        return cfg.get("ct") if cfg else None

    def image_path(self, handle):
        cfg = self._cfg_for_handle(handle)
        return cfg.get("img") if cfg else None

    def wait(self, handle, ms=0):
        self.waited.append(handle)
        cfg = self._cfg_for_handle(handle)
        return cfg.get("wait", proc_probe._WAIT_FAILED) if cfg else proc_probe._WAIT_FAILED

    def exit_code(self, handle):
        cfg = self._cfg_for_handle(handle)
        return cfg.get("exit") if cfg else None

    def close(self, handle):
        self.closed.append(handle)


@pytest.fixture
def fake_win(monkeypatch):
    """Install a configurable FakeWin as ``proc_probe._win`` for one test."""
    def _install(table):
        fw = FakeWin(table)
        monkeypatch.setattr(proc_probe, "_win", fw)
        return fw
    return _install


# ── Pure decision logic (no ctypes, no process) ──────────────────────────────

def test_status_from_wait_pure():
    """WAIT_OBJECT_0 ⇒ EXITED, WAIT_TIMEOUT ⇒ RUNNING, anything else ⇒ UNKNOWN."""
    assert proc_probe._status_from_wait(proc_probe._WAIT_OBJECT_0) == proc_probe.PROBE_EXITED
    assert proc_probe._status_from_wait(proc_probe._WAIT_TIMEOUT) == proc_probe.PROBE_RUNNING
    assert proc_probe._status_from_wait(proc_probe._WAIT_FAILED) == proc_probe.PROBE_UNKNOWN
    assert proc_probe._status_from_wait(0xDEAD) == proc_probe.PROBE_UNKNOWN


def test_identity_matches_pure():
    assert proc_probe._identity_matches(5.0, 5.0) is True
    assert proc_probe._identity_matches(5.5, 5.0, tol=1.0) is True
    assert proc_probe._identity_matches(9999.0, 5.0) is False
    assert proc_probe._identity_matches(None, 5.0) is False
    assert proc_probe._identity_matches(5.0, None) is False


# ── Full-width handle surface ────────────────────────────────────────────────

@pytest.mark.skipif(not sys.platform.startswith("win"),
                    reason="the ctypes kernel32 surface only exists on Windows")
def test_kernel32_surface_is_full_width():
    """Every probe entry point declares HANDLE as c_void_p (never implicit
    c_int) and WaitForSingleObject is present + full-width."""
    import ctypes
    from ctypes import wintypes
    k = proc_probe._kernel32
    assert k.OpenProcess.restype is ctypes.c_void_p
    assert k.CloseHandle.argtypes[0] is ctypes.c_void_p
    assert k.GetProcessTimes.argtypes[0] is ctypes.c_void_p
    assert k.GetExitCodeProcess.argtypes[0] is ctypes.c_void_p
    # WaitForSingleObject (the 259 disambiguator) is declared full-width.
    assert k.WaitForSingleObject.restype is wintypes.DWORD
    assert k.WaitForSingleObject.argtypes[0] is ctypes.c_void_p
    # ntdll (un)freeze surface replaces the old implicit-int windll probing.
    assert proc_probe._ntdll.NtSuspendProcess.argtypes[0] is ctypes.c_void_p


def test_high_value_handle_not_truncated(fake_win):
    """A 64-bit handle value flows through proc_probe's code unchanged — no
    truncation to 32 bits anywhere in the probe path."""
    HIGH = 0x00007FF6_12345678  # a plausible 64-bit pointer > 2**32
    fw = fake_win({1234: {"handle": HIGH, "want_sync_ok": True,
                          "ct": 100.0, "wait": proc_probe._WAIT_TIMEOUT}})
    status, ct, _img = proc_probe.probe_status(1234)
    assert status == proc_probe.PROBE_RUNNING
    assert ct == 100.0
    # The exact high handle was passed to wait() and close() — never truncated.
    assert fw.waited == [HIGH]
    assert fw.closed == [HIGH]


# ── STILL_ACTIVE / 259 disambiguation ────────────────────────────────────────

def test_exit_259_running_is_alive_not_dead(fake_win):
    """A running process whose GetExitCodeProcess would return 259 is RUNNING
    (WAIT_TIMEOUT) — alive, never confirmed dead."""
    fake_win({100: {"want_sync_ok": True, "ct": 100.0,
                    "wait": proc_probe._WAIT_TIMEOUT, "exit": 259}})
    assert proc_probe.probe_status(100)[0] == proc_probe.PROBE_RUNNING
    assert proc_probe.is_alive(100) is True
    assert proc_probe.confirmed_dead(100, 100.0) is False


def test_exit_259_exited_is_dead_via_wait(fake_win):
    """A process that legitimately EXITED with code 259 is caught by
    WaitForSingleObject (WAIT_OBJECT_0) — dead, never masked by the 259."""
    fake_win({200: {"want_sync_ok": True, "ct": 100.0,
                    "wait": proc_probe._WAIT_OBJECT_0, "exit": 259}})
    assert proc_probe.probe_status(200)[0] == proc_probe.PROBE_EXITED
    assert proc_probe.is_alive(200) is False
    # Confirmed dead as our process: WAIT_OBJECT_0 + matching identity tuple.
    assert proc_probe.confirmed_dead(200, 100.0) is True


# ── Denied-open / access-denied → abstain ────────────────────────────────────

def test_denied_open_abstains(fake_win):
    """OpenProcess failing entirely ⇒ PROBE_UNKNOWN and never confirmed dead."""
    fake_win({})  # pid 300 absent ⇒ open() returns None
    assert proc_probe.probe_status(300) == (proc_probe.PROBE_UNKNOWN, None, None)
    assert proc_probe.confirmed_dead(300, 100.0) is False
    assert proc_probe.identity(300) is None
    assert proc_probe.is_alive(300) is False


def test_synchronize_denied_falls_back_but_never_confirms_death(fake_win):
    """When only SYNCHRONIZE is denied, is_alive falls back to the exit-code
    probe (STILL_ACTIVE ⇒ alive) but the kill predicate still ABSTAINS — death
    can only be confirmed via the wait."""
    fake_win({301: {"want_sync_ok": False, "ct": 100.0, "exit": 259}})
    # probe_status can't get a SYNCHRONIZE handle → UNKNOWN.
    assert proc_probe.probe_status(301)[0] == proc_probe.PROBE_UNKNOWN
    # …but the QUERY_LIMITED exit-code fallback still reads alive.
    assert proc_probe.is_alive(301) is True
    # …and death is never confirmed without the wait ⇒ abstain.
    assert proc_probe.confirmed_dead(301, 100.0) is False


# ── PID reuse within a sweep → abstain (identity-tuple mismatch) ──────────────

def test_recycled_pid_running_never_confirmed_dead(fake_win):
    """A PID recycled to a live, DIFFERENT process (creation-time mismatch) is
    RUNNING and never confirmed dead — we must not act against the new owner."""
    fake_win({400: {"want_sync_ok": True, "ct": 9999.0,
                    "wait": proc_probe._WAIT_TIMEOUT}})
    assert proc_probe.confirmed_dead(400, 5.0) is False  # recorded ct was 5.0
    ident = proc_probe.identity(400)
    assert ident == (400, 9999.0, None)
    assert proc_probe._identity_matches(ident[1], 5.0) is False


def test_exited_but_identity_mismatch_abstains(fake_win):
    """Even a WAIT_OBJECT_0 (exited) result does NOT confirm death when the
    creation time mismatches the recorded identity tuple — it is a different
    process object, so we abstain."""
    fake_win({401: {"want_sync_ok": True, "ct": 9999.0,
                    "wait": proc_probe._WAIT_OBJECT_0}})
    assert proc_probe.confirmed_dead(401, 5.0) is False
    # Matching identity is what flips it to confirmed-dead.
    assert proc_probe.confirmed_dead(401, 9999.0) is True


# ── Identity tuple carries the image path ────────────────────────────────────

def test_identity_tuple_carries_image_path(fake_win):
    fake_win({500: {"want_sync_ok": True, "ct": 5.0, "img": r"C:\Windows\py.exe"}})
    assert proc_probe.identity(500) == (500, 5.0, r"C:\Windows\py.exe")


# ── Reaper snapshot records the image path in the identity tuple ─────────────

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


class _ImageProbe:
    def creation_time(self, pid):
        return 5.0 if pid == 900 else None

    def image_path(self, pid):
        return r"C:\app.exe" if pid == 900 else None


class _BareProbe:
    """A creation-time-only probe (the Wave-2 shape) — no image_path attr."""
    def creation_time(self, pid):
        return 5.0


def _running_rec(pid):
    return {"session_id": "s", "status": "running", "pid": pid,
            "proc_create_time": 5.0, "crypt_token": "tok"}


def test_reaper_snapshot_records_image_path(reaper_mod):
    r = reaper_mod
    snap = r.build_snapshot(attached_pty_ids=set(), records=[_running_rec(900)],
                            job_active=lambda _s: False, probe=_ImageProbe())
    assert snap.pid_identity[900] == (900, 5.0, r"C:\app.exe")


def test_reaper_snapshot_image_path_none_for_bare_probe(reaper_mod):
    """A probe with no ``image_path`` (the Wave-2 fake shape) leaves the third
    identity-tuple field None — the enrichment is strictly additive."""
    r = reaper_mod
    snap = r.build_snapshot(attached_pty_ids=set(), records=[_running_rec(900)],
                            job_active=lambda _s: False, probe=_BareProbe())
    assert snap.pid_identity[900] == (900, 5.0, None)


# ── WRITE_LOCK reentrancy: _save_sessions never re-acquires under a held lock ─

@pytest.fixture
def registry_mod(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    import paths
    importlib.reload(paths)
    import session_registry
    importlib.reload(session_registry)
    return paths, session_registry


def test_save_under_held_nonreentrant_lock_no_deadlock(registry_mod, monkeypatch):
    """With ``paths.WRITE_LOCK`` a PLAIN (non-reentrant) Lock, a mutating CRUD
    call — which holds the lock and then saves — must NOT self-deadlock. If
    ``_save_sessions`` re-acquired the lock this would hang forever."""
    paths, session_registry = registry_mod
    monkeypatch.setattr(paths, "WRITE_LOCK", threading.Lock())

    result = {}
    err = {}

    def _work():
        try:
            rec = session_registry.register_session("proj", "build",
                                                    session_id="deadlock-probe")
            result["rec"] = rec
        except Exception as e:  # pragma: no cover - only on a regression
            err["e"] = e

    t = threading.Thread(target=_work)
    t.start()
    t.join(timeout=10.0)
    assert not t.is_alive(), "register_session deadlocked under a non-reentrant lock"
    assert not err, f"register_session raised: {err.get('e')}"
    assert result["rec"]["session_id"] == "deadlock-probe"
    # The record is actually persisted (the split critical section still writes).
    assert session_registry.get_session("deadlock-probe") is not None


def test_direct_save_locked_flag_no_reacquire(registry_mod, monkeypatch):
    """Calling ``_save_sessions(reg, _locked=True)`` while already holding a
    plain Lock completes without deadlock; ``_locked=False`` acquires normally."""
    paths, session_registry = registry_mod
    monkeypatch.setattr(paths, "WRITE_LOCK", threading.Lock())

    done = {}

    def _work():
        reg = {"x": session_registry._normalize(
            {"session_id": "x", "status": "idle"})}
        with paths.WRITE_LOCK:                       # caller holds the lock…
            session_registry._save_sessions(reg, _locked=True)   # …no re-acquire
        session_registry._save_sessions(reg, _locked=False)      # acquires fine
        done["ok"] = True

    t = threading.Thread(target=_work)
    t.start()
    t.join(timeout=10.0)
    assert not t.is_alive()
    assert done.get("ok") is True


# ── Parallel sweep + concurrent user writes: store stays intact ──────────────

def test_parallel_sweep_and_user_write_stress(registry_mod):
    """Many concurrent registrations/updates (user writes) racing repeated
    read-only sweeps (list_sessions + build_snapshot) leave the store parseable
    and complete, with the expected number of records and no exceptions."""
    paths, session_registry = registry_mod
    import reaper
    importlib.reload(reaper)

    errors = []
    n_writers = 4
    per_writer = 10
    stop = threading.Event()

    def _writer(wid):
        try:
            for i in range(per_writer):
                sid = f"w{wid}-s{i}"
                session_registry.register_session(
                    "proj", "build", status=session_registry.STATUS_RUNNING,
                    session_id=sid)
                session_registry.update_session(sid, label=f"lbl-{wid}-{i}")
        except Exception as e:
            errors.append(e)

    def _sweeper():
        try:
            while not stop.is_set():
                recs = session_registry.list_sessions(
                    status=session_registry.STATUS_RUNNING)
                # A real read-only sweep over the immutable snapshot (no probe).
                snap = reaper.build_snapshot(
                    attached_pty_ids=set(), records=recs,
                    job_active=lambda _s: False, probe=reaper.NO_PROBE)
                reaper.live_owner_ids(snap)
        except Exception as e:
            errors.append(e)

    writers = [threading.Thread(target=_writer, args=(w,)) for w in range(n_writers)]
    sweepers = [threading.Thread(target=_sweeper) for _ in range(2)]
    for t in sweepers:
        t.start()
    for t in writers:
        t.start()
    for t in writers:
        t.join(timeout=30.0)
    stop.set()
    for t in sweepers:
        t.join(timeout=30.0)

    assert not any(t.is_alive() for t in writers + sweepers), "a thread hung"
    assert errors == [], f"concurrency raised: {errors[:3]}"

    # The store is intact and holds exactly the writers' records.
    text = session_registry.sessions_path().read_text(encoding="utf-8")
    items = json.loads(text)                       # parses (never a torn write)
    ids = {e["session_id"] for e in items}
    expected = {f"w{w}-s{i}" for w in range(n_writers) for i in range(per_writer)}
    assert expected <= ids
    assert len(items) == n_writers * per_writer
