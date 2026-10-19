#!/usr/bin/env python3
"""Win32 process probe — stdlib ``ctypes`` only (Anchor zombie-hunter, D2 / W3).

Per Skill-Foundry PLAN.md decision **D2**: the zombie-hunter must read each
candidate PID's **process creation time** to defeat PID-recycle false positives,
WITHOUT taking a dependency on ``psutil`` (breaks Anchor's stdlib-only invariant)
or bare ``WMIC`` (deprecated on Win11). ``ctypes`` ships with CPython, so this
holds the invariant.

────────────────────────────────────────────────────────────────────────────
WIN32 CORRECTNESS (zombie-hunter → safe-to-arm, Wave 3)
────────────────────────────────────────────────────────────────────────────
The whole positive-proof-of-death kill predicate leans on this probe, so it is
hardened against the three Win32 foot-guns before any age/containment logic
relies on it:

  1. **Full-width handles.** Every ``kernel32`` / ``ntdll`` entry point used
     here has its ``argtypes`` / ``restype`` pinned with ``HANDLE`` declared as
     :data:`ctypes.c_void_p` — NEVER the implicit ``c_int`` you get from a bare
     ``ctypes.windll.kernel32.OpenProcess(...)`` call, which truncates / sign-
     extends a 64-bit handle on 64-bit Python.
  2. **STILL_ACTIVE / 259 disambiguation.** ``GetExitCodeProcess`` returning
     259 is AMBIGUOUS — a not-yet-exited process reports ``STILL_ACTIVE`` (259)
     but a real process may also legitimately *exit* with code 259. Death is
     therefore decided by ``WaitForSingleObject(handle, 0)``
     (``WAIT_OBJECT_0`` = the process object is signaled = exited vs
     ``WAIT_TIMEOUT`` = still running), NEVER inferred from a bare 259. An open
     failure / ACCESS_DENIED / ``WAIT_FAILED`` yields ``UNKNOWN`` → the caller
     ABSTAINS.
  3. **Stable identity tuple.** :func:`identity` reads ``(pid, creation_time,
     image_path)`` off ONE handle. ``confirmed dead`` = ``WAIT_OBJECT_0`` AND a
     creation-time that matches the recorded identity tuple; a mismatch means
     the PID was recycled by a DIFFERENT process → abstain, never act.

Read-only probes + the (un)freeze / kill primitives:

- :func:`creation_time` — the PID's creation time as Unix epoch seconds, or
  ``None`` if no such process / no access. The anti-recycle identity proof.
- :func:`image_path` — the PID's full image path where obtainable, else ``None``.
- :func:`identity` — the ``(pid, creation_time, image_path)`` identity tuple.
- :func:`probe_status` — the disambiguated ``(status, creation_time, image_path)``
  liveness verdict (RUNNING / EXITED / UNKNOWN) via ``WaitForSingleObject``.
- :func:`confirmed_dead` — the positive-proof-of-death primitive (WAIT_OBJECT_0
  AND matching identity tuple).
- :func:`is_alive` — whether the PID currently has a non-exited process.
- :func:`suspend` / :func:`resume` — best-effort FREEZE / UNFREEZE a process.
- :func:`tree_kill` — ``taskkill /T /F`` on a PID (kills the whole tree),
  spawned with ``CREATE_NO_WINDOW`` so it never pops a console window.

On a non-Windows host every probe degrades to "unknown" (``creation_time`` →
``None``, ``probe_status`` → ``(UNKNOWN, None, None)``, ``is_alive`` → ``False``,
``tree_kill`` → ``False``) so importing this module is always safe; the real
behavior is Windows-only by design (Anchor is a Windows service).

The ctypes I/O is isolated behind the module-level :data:`_win` seam so the pure
decision logic (:func:`_status_from_wait`, :func:`_identity_matches`) is unit-
testable without spawning real processes.
"""

from __future__ import annotations

import subprocess
import sys

import paths as _paths

_IS_WINDOWS = sys.platform.startswith("win")

# 100-ns intervals between 1601-01-01 (Win32 FILETIME epoch) and 1970-01-01.
_EPOCH_AS_FILETIME = 116444736000000000
_HUNDRED_NS_PER_SEC = 10_000_000

# CreateProcess flag: run the helper with no console window (no-popup rule).
_CREATE_NO_WINDOW = 0x08000000

# ── Win32 access rights + wait codes (module scope so the cross-platform pure
#    helpers below can reference them without touching ctypes) ────────────────
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
# 0x0800 = PROCESS_SUSPEND_RESUME — the only right we need to (un)freeze a tree.
_PROCESS_SUSPEND_RESUME = 0x0800
# 0x00100000 = SYNCHRONIZE — required by WaitForSingleObject (GetExitCodeProcess
# works with PROCESS_QUERY_LIMITED_INFORMATION alone, but the 259 disambiguation
# needs a SYNCHRONIZE-bearing handle).
_SYNCHRONIZE = 0x00100000
_STILL_ACTIVE = 259  # GetExitCodeProcess code for a not-yet-exited process
_WAIT_OBJECT_0 = 0x00000000   # the process object is signaled ⇒ exited
_WAIT_TIMEOUT = 0x00000102    # still running
_WAIT_FAILED = 0xFFFFFFFF     # the wait itself failed ⇒ unknown

# ── Liveness-probe verdicts (proc_probe-local; distinct from the session
#    registry's status strings) ────────────────────────────────────────────
PROBE_RUNNING = "running"
PROBE_EXITED = "exited"
PROBE_UNKNOWN = "unknown"

# ── Toolhelp process-enumeration constants (module scope; the Windows block
#    below pins the ctypes surface). TH32CS_SNAPPROCESS = walk the process list.
_TH32CS_SNAPPROCESS = 0x00000002
_MAX_PATH = 260


def _coerce_pid(pid):
    """Coerce ``pid`` to a positive ``int`` PID, or ``None`` when it is not one."""
    try:
        p = int(pid)
    except (TypeError, ValueError):
        return None
    return p if p > 0 else None


def _status_from_wait(wait_code):
    """Pure map ``WaitForSingleObject(handle, 0)`` → a liveness verdict.

    ``WAIT_OBJECT_0`` ⇒ the process object is signaled ⇒ :data:`PROBE_EXITED`.
    ``WAIT_TIMEOUT``  ⇒ the object is not signaled ⇒ :data:`PROBE_RUNNING`.
    Anything else (``WAIT_FAILED`` / an unexpected code) ⇒ :data:`PROBE_UNKNOWN`
    → the caller ABSTAINS. Death is NEVER inferred from a bare
    ``GetExitCodeProcess`` == 259 — only from ``WAIT_OBJECT_0``.
    """
    if wait_code == _WAIT_OBJECT_0:
        return PROBE_EXITED
    if wait_code == _WAIT_TIMEOUT:
        return PROBE_RUNNING
    return PROBE_UNKNOWN


def _identity_matches(probe_ct, expected_ct, tol=2.0):
    """Whether a freshly-probed creation time matches the recorded identity
    tuple's creation time within ``tol`` seconds (i.e. the PID still hosts OUR
    process). A mismatch means the PID was recycled by a DIFFERENT process, so
    the caller must abstain — never read liveness or kill against it.
    """
    return (probe_ct is not None and expected_ct is not None
            and abs(probe_ct - expected_ct) <= tol)


if _IS_WINDOWS:  # pragma: no cover - exercised only on Windows
    import ctypes
    from ctypes import wintypes

    #: The full-width handle type — NEVER an implicit ``c_int`` (which truncates
    #: a 64-bit handle on 64-bit Python). ``wintypes.HANDLE`` is already
    #: ``c_void_p``; we bind the name explicitly so the intent is unmissable.
    _HANDLE = ctypes.c_void_p

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _ntdll = ctypes.WinDLL("ntdll", use_last_error=True)

    class _FILETIME(ctypes.Structure):
        _fields_ = [
            ("dwLowDateTime", wintypes.DWORD),
            ("dwHighDateTime", wintypes.DWORD),
        ]

    _PFILETIME = ctypes.POINTER(_FILETIME)

    # ── Explicit, full-width kernel32 surface (argtypes/restype pinned) ──────
    _kernel32.OpenProcess.restype = _HANDLE
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [_HANDLE]
    _kernel32.GetProcessTimes.restype = wintypes.BOOL
    _kernel32.GetProcessTimes.argtypes = [
        _HANDLE, _PFILETIME, _PFILETIME, _PFILETIME, _PFILETIME,
    ]
    _kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    _kernel32.GetExitCodeProcess.argtypes = [_HANDLE, ctypes.POINTER(wintypes.DWORD)]
    _kernel32.WaitForSingleObject.restype = wintypes.DWORD
    _kernel32.WaitForSingleObject.argtypes = [_HANDLE, wintypes.DWORD]
    _kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    _kernel32.QueryFullProcessImageNameW.argtypes = [
        _HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
    ]
    # Job-object surface (Wave 1; HANDLE widened to the explicit c_void_p).
    _kernel32.CreateJobObjectW.restype = _HANDLE
    _kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL
    _kernel32.SetInformationJobObject.argtypes = [
        _HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
    ]
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.AssignProcessToJobObject.argtypes = [_HANDLE, _HANDLE]
    # ── ntdll suspend/resume — declared full-width (replaces the old
    #    ``ctypes.windll.ntdll`` implicit-int probing) ────────────────────────
    _ntdll.NtSuspendProcess.restype = ctypes.c_long  # NTSTATUS
    _ntdll.NtSuspendProcess.argtypes = [_HANDLE]
    _ntdll.NtResumeProcess.restype = ctypes.c_long
    _ntdll.NtResumeProcess.argtypes = [_HANDLE]

    #: (HANDLE)-1 — what CreateToolhelp32Snapshot returns on failure. Compared
    #: as the full-width c_void_p value so a 64-bit sentinel is never truncated.
    _INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    class _PROCESSENTRY32W(ctypes.Structure):
        """The Win32 ``PROCESSENTRY32W`` — only ``th32ProcessID`` is read, but the
        WHOLE struct is declared so ``dwSize`` (which Toolhelp validates) and the
        field offsets are correct."""
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * _MAX_PATH),
        ]

    # ── Full-width Toolhelp process-enumeration surface (Wave 9) ─────────────
    _kernel32.CreateToolhelp32Snapshot.restype = _HANDLE
    _kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    _kernel32.Process32FirstW.restype = wintypes.BOOL
    _kernel32.Process32FirstW.argtypes = [_HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
    _kernel32.Process32NextW.restype = wintypes.BOOL
    _kernel32.Process32NextW.argtypes = [_HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]

    def _filetime_to_epoch(ft: "_FILETIME") -> float:
        raw = (ft.dwHighDateTime << 32) | ft.dwLowDateTime
        return (raw - _EPOCH_AS_FILETIME) / _HUNDRED_NS_PER_SEC

    class _Win32Probe:
        """Thin ctypes I/O seam over the pinned ``kernel32`` surface.

        Every method takes/returns plain Python values so a test can replace
        ``proc_probe._win`` with a pure-Python fake and drive the decision logic
        (:func:`probe_status`, :func:`confirmed_dead`, :func:`is_alive`) without
        spawning real processes. Handles flow through unchanged — nothing here
        truncates a handle value.
        """

        def open(self, pid, want_sync=False):
            """OpenProcess for ``pid``; ``want_sync`` adds ``SYNCHRONIZE`` (needed
            by ``WaitForSingleObject``). Returns the handle value or ``None``."""
            access = _PROCESS_QUERY_LIMITED_INFORMATION
            if want_sync:
                access |= _SYNCHRONIZE
            h = _kernel32.OpenProcess(access, False, int(pid))
            return h or None

        def creation_time(self, handle):
            creation, exit_, kern, user = (_FILETIME() for _ in range(4))
            ok = _kernel32.GetProcessTimes(
                handle,
                ctypes.byref(creation),
                ctypes.byref(exit_),
                ctypes.byref(kern),
                ctypes.byref(user),
            )
            if not ok:
                return None
            return _filetime_to_epoch(creation)

        def image_path(self, handle):
            try:
                size = wintypes.DWORD(32768)
                buf = ctypes.create_unicode_buffer(size.value)
                ok = _kernel32.QueryFullProcessImageNameW(
                    handle, 0, buf, ctypes.byref(size))
                if not ok:
                    return None
                return buf.value or None
            except Exception:
                return None

        def wait(self, handle, ms=0):
            return int(_kernel32.WaitForSingleObject(handle, int(ms)))

        def exit_code(self, handle):
            code = wintypes.DWORD()
            ok = _kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            if not ok:
                return None
            return int(code.value)

        def close(self, handle):
            try:
                _kernel32.CloseHandle(handle)
            except Exception:
                pass

    _win = _Win32Probe()
else:
    _win = None


# ── Read-only probes ─────────────────────────────────────────────────────────

def creation_time(pid: int):
    """Return ``pid``'s process creation time as Unix epoch seconds, or ``None``.

    ``None`` means "no such accessible process" — either the PID does not exist,
    has exited, or we lack rights to query it. A real float means a live process
    with that PID exists *and* this is its true start time (the anti-recycle
    identity proof).
    """
    if _win is None:
        return None
    p = _coerce_pid(pid)
    if p is None:
        return None
    h = _win.open(p)
    if not h:
        return None
    try:
        return _win.creation_time(h)
    finally:
        _win.close(h)


def image_path(pid: int):
    """Return ``pid``'s full image path where obtainable, else ``None``.

    Part of the stable identity tuple ("where available"): the image path is a
    best-effort corroborating field — ``None`` when the process is gone or the
    query is denied — never a hard requirement of a liveness/kill decision.
    """
    if _win is None:
        return None
    p = _coerce_pid(pid)
    if p is None:
        return None
    h = _win.open(p)
    if not h:
        return None
    try:
        return _win.image_path(h)
    finally:
        _win.close(h)


def identity(pid: int):
    """Return the stable identity tuple ``(pid, creation_time, image_path)`` for
    ``pid``, or ``None`` when no accessible process hosts that PID.

    Read from ONE handle so the creation time and image path describe the SAME
    process object. The creation time is the anti-recycle proof: a later probe
    whose creation time differs (:func:`_identity_matches` → ``False``) means the
    PID was recycled by a DIFFERENT process, so the caller must abstain.
    """
    if _win is None:
        return None
    p = _coerce_pid(pid)
    if p is None:
        return None
    h = _win.open(p)
    if not h:
        return None
    try:
        ct = _win.creation_time(h)
        if ct is None:
            return None
        return (p, ct, _win.image_path(h))
    finally:
        _win.close(h)


def probe_status(pid: int):
    """Disambiguated liveness for ``pid`` → ``(status, creation_time, image_path)``.

    ``status`` is one of :data:`PROBE_RUNNING` / :data:`PROBE_EXITED` /
    :data:`PROBE_UNKNOWN`. The verdict is decided by ``WaitForSingleObject`` —
    ``WAIT_OBJECT_0`` = the process object is signaled = EXITED, ``WAIT_TIMEOUT``
    = still running — NEVER by ``GetExitCodeProcess`` returning 259/STILL_ACTIVE
    (a real process may legitimately exit with code 259). An open failure /
    ACCESS_DENIED / ``WAIT_FAILED`` yields :data:`PROBE_UNKNOWN` so the caller
    ABSTAINS rather than inferring death.
    """
    if _win is None:
        return (PROBE_UNKNOWN, None, None)
    p = _coerce_pid(pid)
    if p is None:
        return (PROBE_UNKNOWN, None, None)
    h = _win.open(p, want_sync=True)
    if not h:
        # Open failure / ACCESS_DENIED — cannot prove anything → abstain.
        return (PROBE_UNKNOWN, None, None)
    try:
        ct = _win.creation_time(h)
        img = _win.image_path(h)
        status = _status_from_wait(_win.wait(h, 0))
        return (status, ct, img)
    finally:
        _win.close(h)


def confirmed_dead(pid: int, expected_create_time, tol: float = 2.0) -> bool:
    """The positive-proof-of-death primitive: whether ``pid`` is CONFIRMED DEAD
    *as our process*.

    Returns ``True`` ONLY when ``WaitForSingleObject`` reports the process object
    signaled (:data:`PROBE_EXITED`) AND the exited process's creation time
    matches the recorded identity tuple within ``tol``. A running process
    (``WAIT_TIMEOUT``), a recycled PID (creation-time mismatch), or any UNKNOWN
    (open failure / ACCESS_DENIED / ``WAIT_FAILED``) returns ``False`` → abstain.
    """
    status, ct, _img = probe_status(pid)
    if status != PROBE_EXITED:
        return False
    return _identity_matches(ct, expected_create_time, tol)


def is_alive(pid: int) -> bool:
    """Whether ``pid`` currently hosts a non-exited process.

    Prefers the ``WaitForSingleObject`` disambiguation (so a process that exited
    with code 259 is correctly reported dead). If the SYNCHRONIZE-bearing open is
    denied/unavailable (``PROBE_UNKNOWN``), it falls back to the
    ``PROCESS_QUERY_LIMITED_INFORMATION`` exit-code probe — still never inferring
    death from a bare 259 (a not-yet-exited process reports ``STILL_ACTIVE`` and
    is reported alive; only a clean non-259 exit code / a failed probe is dead).
    """
    if _win is None:
        return False
    status, _ct, _img = probe_status(pid)
    if status == PROBE_RUNNING:
        return True
    if status == PROBE_EXITED:
        return False
    # UNKNOWN → fall back to the exit-code probe (no SYNCHRONIZE needed).
    p = _coerce_pid(pid)
    if p is None:
        return False
    h = _win.open(p)
    if not h:
        return False
    try:
        code = _win.exit_code(h)
        return code == _STILL_ACTIVE
    finally:
        _win.close(h)


def enum_pids():
    """Enumerate every live PID via the Toolhelp process snapshot (ctypes only).

    Returns a ``frozenset[int]`` of the currently-live process ids, or ``None``
    on an enumeration GAP — a failed snapshot, a non-Windows host, or any ctypes
    error. **A ``None`` return is the UNKNOWN sentinel: the caller must ABSTAIN**
    (never infer death from an enumeration it could not take).

    This is the ownership-safe liveness oracle the ``OpenProcess``-based probes
    cannot be. Toolhelp lists a PID regardless of whether we may OPEN it, so a
    process we are DENIED access to (``creation_time`` → ``None``) still shows as
    alive here — closing the "denied-open looks dead" hole a bare OpenProcess
    probe leaves. Validated against ``psutil`` ground truth in the Wave-9 test
    harness (``psutil`` is a dev/test-only dependency — never a product import).
    """
    if not _IS_WINDOWS or _win is None:
        return None
    try:  # pragma: no cover - exercised on Windows via the Wave-9 harness
        snap = _kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
        if snap is None or snap == _INVALID_HANDLE_VALUE:
            return None
        try:
            entry = _PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
            pids = set()
            ok = _kernel32.Process32FirstW(snap, ctypes.byref(entry))
            # Guard the walk with a hard cap so a pathological snapshot can never
            # spin forever (a Windows host has far fewer than this many PIDs).
            guard = 0
            while ok and guard < 1_000_000:
                pids.add(int(entry.th32ProcessID))
                ok = _kernel32.Process32NextW(snap, ctypes.byref(entry))
                guard += 1
            return frozenset(pids)
        finally:
            _kernel32.CloseHandle(snap)
    except Exception:
        return None


def pid_alive_via_enum(pid, enum=None):
    """Tri-state liveness for ``pid`` from the Toolhelp enumeration.

    - ``True``  — the PID is present in the process snapshot (ALIVE, even when we
      cannot OPEN it: a denied-open process is still alive);
    - ``False`` — the PID is absent from a SUCCESSFUL snapshot (gone);
    - ``None``  — the snapshot could not be taken (gap / non-Windows) → UNKNOWN,
      the caller ABSTAINS.

    ``enum`` may pre-supply the snapshot set (one enumeration per sweep); when
    omitted a fresh :func:`enum_pids` is taken.
    """
    p = _coerce_pid(pid)
    if p is None:
        return None
    pids = enum_pids() if enum is None else enum
    if pids is None:
        return None
    return p in pids


def tree_kill(pid: int) -> bool:
    """Force-kill ``pid`` and its whole child tree via ``taskkill /T /F``.

    Returns ``True`` on a 0 exit code. Spawned with ``CREATE_NO_WINDOW`` so no
    console window flashes. The sweeper calls this ONLY after a positive
    dead-session match (creation-time verified ours, not attached) — never on an
    abstain.
    """
    if not _IS_WINDOWS or not pid or int(pid) <= 0:
        return False
    try:  # pragma: no cover - exercised via integration, not unit
        res = subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(int(pid))],
            capture_output=True,
            creationflags=_CREATE_NO_WINDOW | _paths.NO_WINDOW,
            timeout=15,
        )
        return res.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def suspend(pid: int) -> bool:
    """Best-effort FREEZE a process (all its threads) so it stops consuming CPU
    while it waits to be killed. Cross-platform: Windows uses the undocumented
    ``ntdll!NtSuspendProcess`` through the full-width, pinned ``_ntdll`` surface
    (stdlib ``ctypes`` only — no psutil, no implicit-int ``windll``); POSIX uses
    ``SIGSTOP``. Returns ``True`` on success, never raises. Idempotent at the OS
    level is NOT guaranteed (NtSuspendProcess is counted), so callers should
    track which PIDs they've already suspended and pair every suspend with a
    later :func:`resume`.
    """
    p = _coerce_pid(pid)
    if p is None:
        return False
    if _IS_WINDOWS:
        try:
            h = _kernel32.OpenProcess(_PROCESS_SUSPEND_RESUME, False, p)
            if not h:
                return False
            try:
                return _ntdll.NtSuspendProcess(h) == 0
            finally:
                _kernel32.CloseHandle(h)
        except Exception:
            return False
    try:
        import os
        import signal
        os.kill(p, signal.SIGSTOP)
        return True
    except Exception:
        return False


def resume(pid: int) -> bool:
    """Best-effort UNFREEZE a process suspended by :func:`suspend`. Windows uses
    ``ntdll!NtResumeProcess`` (full-width, pinned surface); POSIX uses
    ``SIGCONT``. Returns ``True`` on success, never raises.
    """
    p = _coerce_pid(pid)
    if p is None:
        return False
    if _IS_WINDOWS:
        try:
            h = _kernel32.OpenProcess(_PROCESS_SUSPEND_RESUME, False, p)
            if not h:
                return False
            try:
                return _ntdll.NtResumeProcess(h) == 0
            finally:
                _kernel32.CloseHandle(h)
        except Exception:
            return False
    try:
        import os
        import signal
        os.kill(p, signal.SIGCONT)
        return True
    except Exception:
        return False


def attach_to_job_object(pid_or_handle):
    """Wrap the given PID or process handle in a Job Object with KILL_ON_JOB_CLOSE.

    Returns the Job Object handle (or None on failure). The caller should keep
    the handle alive as long as the process should live. When the handle is
    closed or the python process exits, the OS will terminate the whole tree.
    """
    if not _IS_WINDOWS or pid_or_handle is None:
        return None
    try:
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
        JobObjectExtendedLimitInformation = 9

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_uint64),
                ("WriteOperationCount", ctypes.c_uint64),
                ("OtherOperationCount", ctypes.c_uint64),
                ("ReadTransferCount", ctypes.c_uint64),
                ("WriteTransferCount", ctypes.c_uint64),
                ("OtherTransferCount", ctypes.c_uint64),
            ]

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        h_job = _kernel32.CreateJobObjectW(None, None)
        if not h_job:
            return None

        limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE

        res = _kernel32.SetInformationJobObject(
            h_job,
            JobObjectExtendedLimitInformation,
            ctypes.byref(limits),
            ctypes.sizeof(limits)
        )
        if not res:
            _kernel32.CloseHandle(h_job)
            return None

        if isinstance(pid_or_handle, int):
            PROCESS_SET_QUOTA = 0x0100
            PROCESS_TERMINATE = 0x0001
            h_proc = _kernel32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, int(pid_or_handle))
            if not h_proc:
                _kernel32.CloseHandle(h_job)
                return None
            close_proc_handle = True
        else:
            h_proc = pid_or_handle
            close_proc_handle = False

        res = _kernel32.AssignProcessToJobObject(h_job, h_proc)
        if close_proc_handle:
            _kernel32.CloseHandle(h_proc)

        if not res:
            _kernel32.CloseHandle(h_job)
            return None

        return h_job
    except Exception:
        return None


def close_handle(handle):
    """Close a Win32 handle."""
    if _IS_WINDOWS and handle is not None:
        try:
            _kernel32.CloseHandle(handle)
        except Exception:
            pass
