"""share-distro v1 Wave 1 — POSIX PTY backend (``pty_manager.PosixPtyBackend``).

Decision #4 (cross-platform terminals): terminals must run on macOS/Linux via
the stdlib ``pty`` module, behind the SAME backend seam the stub/pywinpty
backends use.

THE GATE HOST IS WINDOWS. Per the plan's Conventions block, a cross-platform
done-when MUST run on Windows via a faked-platform / dependency-injected seam —
``pytest.skip`` is NOT acceptable as the sole coverage of a POSIX path (the
rnd-v12 vacuous-GREEN lesson). So these tests:

  - INJECT a fake POSIX seam (fake ``pty.openpty`` / ``os.read`` / ``os.write`` /
    ``select`` / ``Popen`` / ``killpg`` …) into ``PosixPtyBackend`` — no real
    POSIX syscall is ever called — and assert an echo round-trips through
    start → write → read_since, and that ``kill`` reaps the child; AND
  - monkeypatch ``sys.platform`` to ``"linux"`` with ``ANCHOR_PTY_BACKEND``
    UNSET and assert the selector returns ``PosixPtyBackend``.

These run identically on Windows (the gate) and on a real POSIX host.
"""
import importlib
import threading

import pytest


# ── A fully in-memory FAKE POSIX seam (no real syscalls) ─────────────────────
#
# Models a single pty pair: a write to the master fd ECHOES into a readable
# buffer that ``select`` flags as ready and ``read`` drains — so a real child's
# "the terminal echoes my input" behavior is reproduced deterministically.

class _FakePtyWorld:
    def __init__(self):
        self.master_fd = 7
        self.slave_fd = 8
        self._buf = bytearray()           # bytes readable from the master
        self._lock = threading.RLock()
        self._eof = False                 # set once the child is killed
        self.closed_fds = []
        self.popen_started = []           # argv lists Popen was asked to run
        self.killpg_calls = []            # (pgid, sig) tuples
        self.resize_calls = []            # (fd, cols, rows)
        self.setnb_calls = []             # fds set non-blocking
        self.proc = _FakeProc(pid=4321)

    # --- the injected seam callables ---
    def openpty(self):
        return (self.master_fd, self.slave_fd)

    def write(self, fd, data):
        # The terminal echoes written bytes back onto the master fd.
        if fd != self.master_fd:
            raise OSError("write to non-master fd")
        with self._lock:
            self._buf.extend(data)
        return len(data)

    def select(self, rlist, wlist, xlist, timeout=0.0):
        with self._lock:
            ready = bool(self._buf) or self._eof
        if not ready and timeout:
            # Honor the timeout like real select() so a reader polling an IDLE fd
            # sleeps instead of busy-spinning at 100% CPU. Without this, a leaked
            # (un-killed) daemon reader starves a full pytest run — the W1 stall.
            import time as _t
            _t.sleep(timeout)
        return (list(rlist) if ready else [], [], [])

    def read(self, fd, n):
        if fd != self.master_fd:
            raise OSError("read from non-master fd")
        with self._lock:
            if not self._buf:
                if self._eof:
                    return b""            # EOF after kill → reader exits
                raise BlockingIOError("EAGAIN")
            chunk = bytes(self._buf[:n])
            del self._buf[:n]
            return chunk

    def close(self, fd):
        self.closed_fds.append(fd)
        if fd == self.master_fd:
            with self._lock:
                self._eof = True

    def set_nonblocking(self, fd):
        self.setnb_calls.append(fd)

    def ws_ioctl(self, fd, cols, rows):
        self.resize_calls.append((fd, cols, rows))

    def Popen(self, argv, **kw):
        self.popen_started.append(argv)
        return self.proc

    def killpg(self, pgid, sig):
        self.killpg_calls.append((pgid, sig))
        self.proc.alive = False

    def getpgid(self, pid):
        return pid

    def setsid(self):  # never actually called in tests (preexec_fn)
        return None

    def seam(self):
        return {
            "openpty": self.openpty,
            "read": self.read,
            "write": self.write,
            "close": self.close,
            "select": self.select,
            "set_nonblocking": self.set_nonblocking,
            "ws_ioctl": self.ws_ioctl,
            "Popen": self.Popen,
            "killpg": self.killpg,
            "getpgid": self.getpgid,
            "setsid": self.setsid,
            "SIGKILL": 9,
        }


class _FakeProc:
    def __init__(self, pid):
        self.pid = pid
        self.alive = True

    def poll(self):
        return None if self.alive else 0

    def kill(self):
        self.alive = False


@pytest.fixture
def pm():
    """pty_manager with the env clean (no stub forcing); reloaded per test."""
    import pty_manager
    importlib.reload(pty_manager)
    yield pty_manager
    try:
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


def _wait_until(predicate, timeout=2.0):
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


# ── start → write → read_since round-trips echoed bytes (injected fakes) ─────

def test_posix_backend_round_trips_echoed_bytes_via_injected_seam(pm):
    world = _FakePtyWorld()
    backend = pm.PosixPtyBackend(seam=world.seam())
    child = backend.start(["claude", "-p"], cwd="/tmp", env={"X": "1"})

    # Popen was invoked with the argv via the injected seam (no real subprocess).
    assert world.popen_started == [["claude", "-p"]]
    assert child.is_alive() is True

    # Write → the fake terminal echoes onto the master fd → the daemon reader
    # drains it → read_since serves it cursor-stably.
    child.write("hello posix")
    assert _wait_until(lambda: child.read_since(0)[0] == "hello posix"), \
        "echoed bytes did not round-trip through the POSIX backend reader"

    text, nxt = child.read_since(0)
    assert text == "hello posix"
    # A re-read from the advanced absolute cursor yields nothing new.
    assert child.read_since(nxt) == ("", nxt)

    # A further write is picked up from the advanced cursor only.
    child.write(b"-more")
    assert _wait_until(lambda: child.read_since(nxt)[0] == "-more")
    child.kill()  # reap the daemon reader thread (no leaked spinner)


def test_posix_backend_resize_issues_winsize_ioctl_via_seam(pm):
    world = _FakePtyWorld()
    child = pm.PosixPtyBackend(seam=world.seam()).start("bash")
    child.resize(120, 40)
    assert child.cols == 120 and child.rows == 40
    assert world.resize_calls == [(world.master_fd, 120, 40)]
    child.kill()  # reap the daemon reader thread (no leaked spinner)


# ── kill reaps the child (process group signalled, master fd closed) ─────────

def test_posix_backend_kill_reaps_child_via_seam(pm):
    world = _FakePtyWorld()
    child = pm.PosixPtyBackend(seam=world.seam()).start("bash")
    assert child.is_alive() is True

    child.kill()

    assert child.reaped is True
    assert child.is_alive() is False
    # The whole process group was signalled with SIGKILL (tree-reap).
    assert world.killpg_calls == [(world.proc.pid, 9)]
    # The master fd was closed so the reader thread unblocks and exits.
    assert world.master_fd in world.closed_fds


def test_posix_backend_through_manager_core_with_injected_backend(pm):
    """The manager's start/write/read_since/kill route a PosixPtyBackend the
    same as any other backend (contract parity), driven by injected fakes."""
    world = _FakePtyWorld()
    pm.select_backend = lambda: pm.PosixPtyBackend(seam=world.seam())  # type: ignore
    sid = pm.start(["claude"])
    assert sid in pm.live_sessions()
    pm.write(sid, "round")
    assert _wait_until(lambda: pm.read_since(sid, 0)["text"] == "round")
    pm.kill(sid)
    assert sid not in pm.live_sessions()
    with pytest.raises(pm.UnknownSession):
        pm.read_since(sid, 0)


# ── _select_backend picks PosixPtyBackend on non-Windows w/ env unset ────────

def test_select_backend_picks_posix_on_linux_env_unset(pm, monkeypatch):
    monkeypatch.delenv(pm.BACKEND_ENV, raising=False)
    monkeypatch.setattr(pm.sys, "platform", "linux")
    backend = pm._select_backend()
    assert isinstance(backend, pm.PosixPtyBackend)
    assert backend.name == "posix"
    # The public seam name resolves to the SAME selection (alias, no fork).
    assert isinstance(pm.select_backend(), pm.PosixPtyBackend)


def test_select_backend_picks_posix_on_darwin_env_unset(pm, monkeypatch):
    monkeypatch.delenv(pm.BACKEND_ENV, raising=False)
    monkeypatch.setattr(pm.sys, "platform", "darwin")
    assert isinstance(pm._select_backend(), pm.PosixPtyBackend)


def test_stub_still_forced_when_env_set_even_on_linux(pm, monkeypatch):
    """The literal ``stub`` override still wins over platform auto-selection."""
    monkeypatch.setenv(pm.BACKEND_ENV, "stub")
    monkeypatch.setattr(pm.sys, "platform", "linux")
    assert isinstance(pm._select_backend(), pm.StubBackend)


def test_select_backend_picks_pywinpty_on_windows_env_unset(pm, monkeypatch):
    monkeypatch.delenv(pm.BACKEND_ENV, raising=False)
    monkeypatch.setattr(pm.sys, "platform", "win32")
    assert isinstance(pm._select_backend(), pm.PywinptyBackend)
