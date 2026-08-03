#!/usr/bin/env python3
"""Anchor PTY session manager — real ConPTY (pywinpty) with a stub backend seam.

v3 "Mission Control" (MASTER-PLAN §D / Implementation-Plan Wave 1). This is the
ONE place in Anchor that may use a native dependency (``pywinpty`` / ConPTY),
consciously waiving the otherwise stdlib-only rule **for the terminal subsystem
only**. The native dependency is isolated here and imported LAZILY:

- ``import winpty`` happens INSIDE the pywinpty backend's ``start`` path, never at
  module import. So ``import pty_manager`` always works even on a host without
  pywinpty; only actually *starting* a real PTY (default backend) needs it.
- If ``winpty`` is absent, the pywinpty backend raises :class:`PtyUnavailable`;
  the rest of the module — and the whole rest of Anchor — is unaffected.

Backend selection is by the env var ``ANCHOR_PTY_BACKEND``:

- ``ANCHOR_PTY_BACKEND=stub`` selects the deterministic in-memory **stub**
  backend used by every test (no real subprocess, no native dep).
- unset / anything else selects the real **pywinpty** backend (runtime).

Manager core API (cursor-stable like ``job_runner.tail``):

    start(cmd, cwd=None, env=None) -> session_id
    write(session_id, data)
    read_since(session_id, cursor) -> {"text", "next", "status"}
    resize(session_id, cols, rows)
    kill(session_id)

Unknown-session calls raise :class:`UnknownSession` (a ``KeyError`` subclass).
Thread-safe: a module-local re-entrant lock guards the live-session table, since
the live HTTP server is threaded.
"""

import os
import subprocess
import sys
import threading
import uuid

import paths as _paths

# ── Errors ──────────────────────────────────────────────────────────────────


class PtyUnavailable(RuntimeError):
    """The real PTY backend (pywinpty / ConPTY) is unavailable on this host.

    Raised by the pywinpty backend when ``import winpty`` fails. The terminal
    subsystem reports "real terminal unavailable"; the rest of Anchor is fine.
    """


class UnknownSession(KeyError):
    """A manager call referenced a session id that is not in the live table."""


# ── Backend selection ─────────────────────────────────────────────────────────

#: Env var that selects the PTY backend. ``stub`` → in-memory fake child;
#: unset / anything else → the real pywinpty (ConPTY) backend.
BACKEND_ENV = "ANCHOR_PTY_BACKEND"
STUB_BACKEND = "stub"

#: Max characters of cumulative output retained per session. A long-lived
#: terminal can't grow memory without bound; we keep only this tail window.
#: ``read_since`` preserves absolute-cursor semantics across the drop boundary
#: (see :meth:`_StubChild.read_since`).
MAX_BUFFER_CHARS = 200_000


def select_backend():
    """Return a backend instance per ``ANCHOR_PTY_BACKEND`` (read at call time).

    Selection (read at call time so it is unit-testable):

    - ``ANCHOR_PTY_BACKEND=stub`` → :class:`StubBackend` (forced; every test).
    - unset on **Windows** → :class:`PywinptyBackend` (the real ConPTY backend).
    - unset on **non-Windows** (macOS / Linux) → :class:`PosixPtyBackend` (the
      stdlib ``pty`` backend — share-distro v1 Wave 1, decision #4 cross-platform
      terminals).
    - anything else set → the platform default (pywinpty on Windows, posix
      elsewhere) — only the literal ``stub`` forces the stub.

    Kept tiny/pure so the selection is unit-testable on any host.
    """
    raw = os.environ.get(BACKEND_ENV)
    if raw and raw.strip().lower() == STUB_BACKEND:
        return StubBackend()
    if sys.platform == "win32":
        return PywinptyBackend()
    return PosixPtyBackend()


#: Backwards/alias name used by the share-distro plan + its done-whens. The
#: public seam is :func:`select_backend`; ``_select_backend`` is an alias so the
#: two names refer to the SAME selector (no forked logic).
def _select_backend():
    return select_backend()


# ── Stub backend — deterministic in-memory pty-able fake child ────────────────


class _StubChild:
    """A faithful, in-memory fake pty child.

    No real subprocess. It is "alive" from ``start`` until ``kill``. A ``write``
    ECHOES the written text into the child's readable output buffer, so a
    start→write→read round-trip works. ``read_since`` returns output after a
    cursor (a character offset into the cumulative output buffer). ``resize``
    records the requested cols/rows. This stub is reused by later waves (the
    Wave-3 terminal tests), so it is deliberately faithful and importable.
    """

    def __init__(self, cmd, cwd=None, env=None):
        self.cmd = cmd
        self.cwd = cwd
        self.env = env
        # Bounded tail window of cumulative output. ``_total`` = total chars ever
        # produced; ``_dropped`` = chars discarded from the front. The retained
        # text is always the last ``_total - _dropped`` chars.
        self._buf = ""           # retained tail window (str)
        self._total = 0
        self._dropped = 0
        self._lock = threading.RLock()
        self.cols = 80
        self.rows = 24
        self._alive = True
        self.reaped = False

    def _append(self, text):
        """Append output to the bounded tail window (caller holds ``_lock``)."""
        if not text:
            return
        self._buf += text
        self._total += len(text)
        excess = len(self._buf) - MAX_BUFFER_CHARS
        if excess > 0:
            self._buf = self._buf[excess:]
            self._dropped += excess

    def _read_since(self, cursor):
        """Serve output after ``cursor`` from the tail window (holds ``_lock``).

        A cursor below ``_dropped`` (caller missed scrollback) is clamped to the
        oldest retained char — no crash, no duplication. ``next`` is the absolute
        total, so a re-read from ``next`` returns ``""``.
        """
        start = max(int(cursor), self._dropped)
        if start >= self._total:
            return "", self._total
        text = self._buf[start - self._dropped:]
        return text, self._total

    # --- lifecycle ---
    def is_alive(self):
        with self._lock:
            return self._alive

    def kill(self):
        with self._lock:
            self._alive = False
            self.reaped = True

    # --- io ---
    def write(self, data):
        if data is None:
            return
        text = data if isinstance(data, str) else data.decode("utf-8", "replace")
        with self._lock:
            if not self._alive:
                return
            # Echo the written bytes into the readable output buffer so a
            # round-trip test observes them.
            self._append(text)

    def read_since(self, cursor):
        """Return (text_after_cursor, next_cursor).

        ``cursor`` is an ABSOLUTE character offset into the cumulative output.
        The next cursor is the absolute total, so a second read returns nothing
        new. Output past the bounded tail window is dropped (see ``_append``).
        """
        with self._lock:
            return self._read_since(cursor)

    def resize(self, cols, rows):
        with self._lock:
            self.cols = int(cols)
            self.rows = int(rows)


class StubBackend:
    """Backend that creates :class:`_StubChild` instances (no native dep)."""

    name = STUB_BACKEND

    def start(self, cmd, cwd=None, env=None):
        return _StubChild(cmd, cwd=cwd, env=env)


# ── pywinpty backend — real ConPTY child (lazy native import) ─────────────────


class _PywinptyChild:
    """A real ConPTY child driven by ``pywinpty``'s high-level ``PtyProcess``.

    pywinpty's ``read()`` can block, so a daemon reader thread continuously
    drains output into an in-memory cumulative buffer; ``read_since`` then serves
    that buffer cursor-stably (same contract as the stub). ``write`` feeds the
    PTY; ``resize`` calls ``setwinsize(rows, cols)``; ``kill`` terminates the
    child (force) and stops the reader.
    """

    def __init__(self, proc):
        self._proc = proc                 # winpty.PtyProcess
        self.pid = getattr(proc, "pid", None)
        # Bounded tail window of cumulative output (see _StubChild for the
        # absolute-cursor contract). ``_total``/``_dropped`` track the absolute
        # offset of the retained window.
        self._buf = ""
        self._total = 0
        self._dropped = 0
        self._lock = threading.RLock()
        self._closed = False
        self.cols = None
        self.rows = None
        # Drain output in the background because PtyProcess.read() blocks.
        self._reader = threading.Thread(target=self._drain, daemon=True)
        self._reader.start()

    def _drain(self):
        while True:
            if self._closed:
                break
            try:
                data = self._proc.read(1024)
            except EOFError:
                break
            except Exception:
                break
            if data:
                with self._lock:
                    self._append(data)

    def _append(self, text):
        """Append output to the bounded tail window (caller holds ``_lock``)."""
        if not text:
            return
        self._buf += text
        self._total += len(text)
        excess = len(self._buf) - MAX_BUFFER_CHARS
        if excess > 0:
            self._buf = self._buf[excess:]
            self._dropped += excess

    def is_alive(self):
        try:
            return bool(self._proc.isalive())
        except Exception:
            return False

    def kill(self):
        # Signal the daemon reader thread to stop; _drain breaks on the
        # terminated proc's EOFError/exception, so no busy-spin and no need to
        # block on a join (it's a daemon).
        with self._lock:
            self._closed = True

        if getattr(self, "_h_job", None) is not None:
            try:
                import proc_probe
                proc_probe.close_handle(self._h_job)
                self._h_job = None
            except Exception:
                pass

        pid = self.pid
        try:
            self._proc.terminate(force=True)
        except Exception:
            pass
        # terminate(force=True) reaps only the DIRECT child; real `claude`
        # spawns `node` grandchildren. Mirror job_runner's tree-kill precedent
        # (`taskkill /T /F /PID`) so the whole tree is reaped — failure tolerated.
        if sys.platform == "win32" and pid:
            try:
                subprocess.run(
                    ["taskkill", "/T", "/F", "/PID", str(pid)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=15,
                    creationflags=_paths.NO_WINDOW,
                )
            except (OSError, subprocess.SubprocessError):
                pass

    def write(self, data):
        if data is None:
            return
        text = data if isinstance(data, str) else data.decode("utf-8", "replace")
        try:
            self._proc.write(text)
            try:
                self._proc.flush()
            except Exception:
                pass
        except Exception:
            pass

    def read_since(self, cursor):
        # Absolute-cursor contract; a cursor below the retained window is clamped
        # to the oldest retained char (missed scrollback) — no crash/duplication.
        with self._lock:
            start = max(int(cursor), self._dropped)
            if start >= self._total:
                return "", self._total
            return self._buf[start - self._dropped:], self._total

    def resize(self, cols, rows):
        self.cols = int(cols)
        self.rows = int(rows)
        try:
            # pywinpty signature is setwinsize(rows, cols).
            self._proc.setwinsize(int(rows), int(cols))
        except Exception:
            pass


class PywinptyBackend:
    """Real ConPTY backend. Imports ``winpty`` LAZILY inside :meth:`start`."""

    name = "pywinpty"

    def start(self, cmd, cwd=None, env=None):
        # Lazy native import — this is the ONLY ``import winpty`` in Anchor and
        # it must NOT run at module import time. A missing native dep surfaces a
        # clear, isolated error.
        try:
            import winpty  # noqa: F401  (imported lazily on purpose)
        except Exception as exc:  # ImportError or a native-load failure
            raise PtyUnavailable(
                "pywinpty (ConPTY) is unavailable: real terminal cannot start "
                "(%s). Set ANCHOR_PTY_BACKEND=stub for the test backend." % exc
            ) from exc

        argv = cmd if isinstance(cmd, (list, tuple)) else [cmd]
        argv = [str(a) for a in argv]
        # pywinpty wants dimensions as (rows, cols); default to 24x80.
        proc = winpty.PtyProcess.spawn(
            argv, cwd=cwd, env=env, dimensions=(24, 80))
        child = _PywinptyChild(proc)
        if sys.platform == "win32" and child.pid:
            try:
                import proc_probe
                child._h_job = proc_probe.attach_to_job_object(child.pid)
            except Exception:
                child._h_job = None
        else:
            child._h_job = None
        return child


# ── POSIX backend — real PTY via the stdlib `pty` (macOS / Linux) ─────────────
#
# share-distro v1 Wave 1 (MASTER-PLAN decision #4 — cross-platform terminals).
# On macOS/Linux a real interactive terminal runs over the stdlib ``pty`` module
# (no native dependency — pywinpty is Windows-only and this backend never needs
# it). The child is a real subprocess attached to a pty master fd; a daemon
# reader thread drains the master fd into the same bounded, cursor-stable buffer
# the other backends use, so the start/write/read_since/resize/kill/live_sessions
# contract is byte-for-byte identical from the manager's point of view.
#
# Every POSIX-only module call goes through an INJECTED seam (``_posix`` /
# ``_io_seam``) so the logic is unit-testable on the Windows gate by injecting
# fakes (a faked ``pty.openpty`` / ``os.read`` / ``os.write`` / ``select``) —
# without calling a real POSIX syscall. The seam defaults to the real stdlib
# modules at runtime on a POSIX host.


def _default_posix_seam():
    """Return the real stdlib POSIX seam used at runtime on macOS/Linux.

    Imported lazily so this never executes (and never fails) on Windows at
    import time. Tests inject a FAKE seam instead of calling this.
    """
    import fcntl
    import os as _os
    import pty
    import select as _select
    import signal
    import struct
    import subprocess as _subprocess
    import termios

    return {
        "openpty": pty.openpty,
        "read": _os.read,
        "write": _os.write,
        "close": _os.close,
        "select": _select.select,
        "set_nonblocking": (lambda fd: fcntl.fcntl(
            fd, fcntl.F_SETFL,
            fcntl.fcntl(fd, fcntl.F_GETFL) | _os.O_NONBLOCK)),
        "ws_ioctl": (lambda fd, cols, rows: fcntl.ioctl(
            fd, termios.TIOCSWINSZ,
            struct.pack("HHHH", int(rows), int(cols), 0, 0))),
        "Popen": _subprocess.Popen,
        "killpg": _os.killpg,
        "getpgid": _os.getpgid,
        "setsid": _os.setsid,
        "SIGKILL": signal.SIGKILL,
    }


class _PosixChild:
    """A real POSIX pty child driven through an injectable stdlib ``pty`` seam.

    The subprocess is started in its own session/process-group and attached to a
    pty slave fd; a daemon reader thread drains the pty MASTER fd into a bounded
    cumulative buffer (same absolute-cursor contract as the stub/pywinpty
    children). ``write`` writes onto the master fd; ``resize`` issues a
    ``TIOCSWINSZ`` ioctl; ``kill`` signals the whole process group (tree-reap)
    and stops the reader.

    All POSIX module calls are taken from ``seam`` (dependency injection), so the
    class is exercisable on Windows with fakes — no real syscall is required.
    """

    def __init__(self, cmd, cwd=None, env=None, seam=None):
        self._seam = seam or _default_posix_seam()
        self.cmd = cmd
        self.cwd = cwd
        self.env = env
        self._buf = ""
        self._total = 0
        self._dropped = 0
        self._lock = threading.RLock()
        self.cols = 80
        self.rows = 24
        self._closed = False
        self.reaped = False
        self._proc = None
        self.pid = None
        self._master_fd = None
        self._slave_fd = None
        self._start()

    # --- lifecycle ---
    def _start(self):
        seam = self._seam
        master_fd, slave_fd = seam["openpty"]()
        self._master_fd = master_fd
        self._slave_fd = slave_fd
        argv = self.cmd if isinstance(self.cmd, (list, tuple)) else [self.cmd]
        argv = [str(a) for a in argv]
        # Start the child in its own session so ``kill`` can signal the whole
        # process group (real `claude` spawns `node` grandchildren).
        preexec = seam.get("setsid")
        proc = seam["Popen"](
            argv,
            cwd=self.cwd,
            env=self.env,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            preexec_fn=preexec,
            close_fds=True,
        )
        self._proc = proc
        self.pid = getattr(proc, "pid", None)
        # The slave fd is owned by the child now; close our copy so EOF surfaces
        # on the master when the child exits.
        try:
            seam["close"](slave_fd)
            self._slave_fd = None
        except Exception:
            pass
        # Non-blocking master so the reader loop never wedges.
        try:
            setnb = seam.get("set_nonblocking")
            if setnb is not None:
                setnb(master_fd)
        except Exception:
            pass
        self._reader = threading.Thread(target=self._drain, daemon=True)
        self._reader.start()

    def _drain(self):
        seam = self._seam
        while True:
            if self._closed:
                break
            try:
                rlist, _, _ = seam["select"]([self._master_fd], [], [], 0.05)
            except Exception:
                break
            if not rlist:
                if self._closed:
                    break
                continue
            try:
                data = seam["read"](self._master_fd, 4096)
            except (OSError, BlockingIOError):
                # EAGAIN on a non-blocking fd with nothing ready; loop.
                continue
            except Exception:
                break
            if not data:  # EOF — the child exited and closed its slave end.
                break
            text = data if isinstance(data, str) else data.decode(
                "utf-8", "replace")
            with self._lock:
                self._append(text)

    def _append(self, text):
        if not text:
            return
        self._buf += text
        self._total += len(text)
        excess = len(self._buf) - MAX_BUFFER_CHARS
        if excess > 0:
            self._buf = self._buf[excess:]
            self._dropped += excess

    def is_alive(self):
        if self._closed:
            return False
        proc = self._proc
        if proc is None:
            return False
        try:
            return proc.poll() is None
        except Exception:
            return False

    def kill(self):
        with self._lock:
            self._closed = True
            self.reaped = True
        seam = self._seam
        pid = self.pid
        # Signal the whole process group (tree-reap) — best-effort.
        if pid is not None and seam.get("killpg") and seam.get("getpgid"):
            try:
                seam["killpg"](seam["getpgid"](pid), seam["SIGKILL"])
            except Exception:
                pass
        proc = self._proc
        if proc is not None:
            try:
                proc.kill()
            except Exception:
                pass
        # Close the master fd so the reader's select/read unblocks and exits.
        if self._master_fd is not None:
            try:
                seam["close"](self._master_fd)
            except Exception:
                pass

    # --- io ---
    def write(self, data):
        if data is None:
            return
        if self._closed:
            return
        raw = data if isinstance(data, (bytes, bytearray)) else \
            str(data).encode("utf-8")
        try:
            self._seam["write"](self._master_fd, raw)
        except Exception:
            pass

    def read_since(self, cursor):
        with self._lock:
            start = max(int(cursor), self._dropped)
            if start >= self._total:
                return "", self._total
            return self._buf[start - self._dropped:], self._total

    def resize(self, cols, rows):
        self.cols = int(cols)
        self.rows = int(rows)
        ws = self._seam.get("ws_ioctl")
        if ws is not None and self._master_fd is not None:
            try:
                ws(self._master_fd, int(cols), int(rows))
            except Exception:
                pass


class PosixPtyBackend:
    """Real POSIX (macOS/Linux) terminal backend over the stdlib ``pty``.

    Stdlib only — no native dependency. ``seam`` is an optional dependency
    injection of the POSIX module calls (defaults to the real stdlib seam at
    runtime); tests pass a FAKE seam so the backend's logic runs on the Windows
    gate without a real syscall.
    """

    name = "posix"

    def __init__(self, seam=None):
        self._seam = seam

    def start(self, cmd, cwd=None, env=None):
        return _PosixChild(cmd, cwd=cwd, env=env, seam=self._seam)


# ── Manager core ──────────────────────────────────────────────────────────────

#: Module-local lock guarding the live-session table. The HTTP server is
#: threaded, so every table mutation/read goes through this.
_TABLE_LOCK = threading.RLock()

#: session_id -> child object (a _StubChild or _PywinptyChild).
_LIVE = {}


def _get(session_id):
    with _TABLE_LOCK:
        child = _LIVE.get(session_id)
    if child is None:
        raise UnknownSession(session_id)
    return child

class SpawnCapReached(Exception):
    pass


def prune_dead_live() -> int:
    """Drop PTY table entries whose children are no longer alive. Returns count removed."""
    dead = []
    with _TABLE_LOCK:
        for sid, child in list(_LIVE.items()):
            try:
                alive = bool(child.is_alive())
            except Exception:
                alive = False
            if not alive:
                dead.append(sid)
        for sid in dead:
            _LIVE.pop(sid, None)
    return len(dead)


def count_live_for_spawn_cap() -> tuple:
    """Return ``(total, live_ptys, live_jobs, cap)`` after pruning dead entries.

    Uses unique OS PIDs for PTY children so a multi-pane session does not burn
    the whole budget. Jobs are counted only when :func:`job_runner._holder_is_active`.
    """
    import job_runner
    prune_dead_live()
    try:
        job_runner.prune_dead_live()
    except Exception:
        pass
    pids = set()
    live_ptys = 0
    with _TABLE_LOCK:
        for child in _LIVE.values():
            try:
                if not child.is_alive():
                    continue
            except Exception:
                continue
            live_ptys += 1
            pid = getattr(child, "pid", None)
            if pid:
                try:
                    pids.add(int(pid))
                except (TypeError, ValueError):
                    pass
    live_jobs = 0
    job_pids = set()
    for jid in list(job_runner._LIVE.keys()):
        if not job_runner._holder_is_active(jid):
            continue
        live_jobs += 1
        try:
            rec = job_runner.load_record(jid) or {}
            pid = rec.get("pid")
            if pid:
                job_pids.add(int(pid))
        except Exception:
            pass
    # Unique process identities (PTYs ∪ jobs). Avoid double-count when a job
    # and a PTY share a process identity.
    unique = len(pids | job_pids)
    # Fallback when PIDs unavailable: sessions + jobs (legacy).
    if unique == 0:
        total = live_ptys + live_jobs
    else:
        # Count unique PIDs, but never under-count sessions that lack PIDs.
        no_pid_ptys = max(0, live_ptys - len(pids))
        no_pid_jobs = max(0, live_jobs - len(job_pids))
        total = unique + no_pid_ptys + no_pid_jobs
    try:
        cap = int(os.environ.get("ANCHOR_SPAWN_CAP", 32))
    except ValueError:
        cap = 32
    if cap < 1:
        cap = 32
    return total, live_ptys, live_jobs, cap


def start(cmd, cwd=None, env=None):
    """Start a PTY child for ``cmd`` and return its ``session_id``.

    The backend is selected per ``ANCHOR_PTY_BACKEND`` at call time. ``cmd`` may
    be a string or an argv list. Returns a fresh opaque session id.
    """
    import job_runner
    import os
    total_live, live_ptys, live_jobs, cap = count_live_for_spawn_cap()
    if total_live >= cap:
        raise SpawnCapReached(
            f"Global sub-agent spawn cap reached ({total_live}/{cap} "
            f"— {live_ptys} terminals + {live_jobs} jobs). "
            f"Close idle Anchor terminals, let jobs finish, or restart Anchor. "
            f"Override with ANCHOR_SPAWN_CAP."
        )

    # ── zombie-hunter Phase 1: capture process identity at spawn ───────────
    # Mint a per-session crypt token and inject it into the child's environment
    # as ANCHOR_SESSION_ID_CRYPT_TOKEN. After the child has a real pid, record
    # that pid's OS creation time. The (token, pid, proc_create_time) triple is
    # stored on the child so terminal_session can persist it into the registry,
    # letting the sweeper later prove a still-live pid is OUR process (creation-
    # time match) and not a recycled pid. A stub/backend with no pid leaves
    # proc_create_time None — the sweeper then abstains (safe), never kills.
    crypt_token = uuid.uuid4().hex
    if env is None:
        env = dict(os.environ)
    else:
        env = dict(env)
    # Inject Anchor model-family prefs so interactive CLI sessions (Claude Code /
    # AGY / Grok Build) inherit coding/review family for skill seat resolution.
    # Pre-set env wins (setdefault). Best-effort — never block a PTY start.
    try:
        import anchor_settings as _aset
        for _k, _v in _aset.export_env_overrides().items():
            env.setdefault(_k, _v)
    except Exception:
        pass
    env["ANCHOR_SESSION_ID_CRYPT_TOKEN"] = crypt_token

    backend = select_backend()
    child = backend.start(cmd, cwd=cwd, env=env)

    child.crypt_token = crypt_token
    pid = getattr(child, "pid", None)
    if pid:
        try:
            import proc_probe
            child.proc_create_time = proc_probe.creation_time(pid)
        except Exception:
            child.proc_create_time = None
    else:
        child.proc_create_time = None

    sid = uuid.uuid4().hex
    with _TABLE_LOCK:
        _LIVE[sid] = child
    return sid


def write(session_id, data):
    """Write ``data`` (str or bytes) onto the session's PTY input.

    Raises :class:`UnknownSession` for an unknown id.
    """
    child = _get(session_id)
    child.write(data)


def read_since(session_id, cursor=0):
    """Return output produced AFTER ``cursor`` for a session.

    Returns ``{"text", "next", "status"}`` where ``next`` is the cursor to pass
    on the next read (cursor-stable: a second read from ``next`` returns ``""``)
    and ``status`` is ``"running"`` or ``"dead"``. Raises :class:`UnknownSession`
    for an unknown id.
    """
    child = _get(session_id)
    text, nxt = child.read_since(cursor)
    # Absolute count of chars dropped from the FRONT of the bounded tail window.
    # A reattaching client compares this against its cursor to know whether older
    # scrollback was discarded (see terminal_session.attach's ``truncated``).
    try:
        with child._lock:
            dropped = int(child._dropped)
    except Exception:
        dropped = 0
    return {
        "text": text,
        "next": nxt,
        "dropped": dropped,
        "status": "running" if child.is_alive() else "dead",
    }


def resize(session_id, cols, rows):
    """Resize the session's PTY to ``cols`` x ``rows``.

    Raises :class:`UnknownSession` for an unknown id.
    """
    child = _get(session_id)
    child.resize(cols, rows)


def kill(session_id):
    """Kill the session's child, reap it, and remove it from the live table.

    Raises :class:`UnknownSession` for an unknown id. After ``kill`` the id is no
    longer in the live table (a subsequent manager call raises UnknownSession).
    """
    with _TABLE_LOCK:
        child = _LIVE.get(session_id)
        if child is None:
            raise UnknownSession(session_id)
        del _LIVE[session_id]
    child.kill()


def live_sessions():
    """Return the list of currently-live session ids (snapshot)."""
    with _TABLE_LOCK:
        return list(_LIVE.keys())


def _reset_live_table_for_tests():
    """Test hook: kill + drop every live session (mirrors job_runner's helper)."""
    with _TABLE_LOCK:
        children = list(_LIVE.values())
        _LIVE.clear()
    for c in children:
        try:
            c.kill()
        except Exception:
            pass
