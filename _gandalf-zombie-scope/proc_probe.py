#!/usr/bin/env python3
"""Win32 process probe — stdlib ``ctypes`` only (Anchor zombie-hunter, D2).

Per Skill-Foundry PLAN.md decision **D2**: the zombie-hunter must read each
candidate PID's **process creation time** to defeat PID-recycle false positives,
WITHOUT taking a dependency on ``psutil`` (breaks Anchor's stdlib-only invariant)
or bare ``WMIC`` (deprecated on Win11). ``ctypes`` ships with CPython, so this
holds the invariant.

Two read-only probes + one kill:

- :func:`creation_time` — Win32 ``OpenProcess`` + ``GetProcessTimes`` → the PID's
  creation time as Unix epoch seconds, or ``None`` if no such process / no access.
  The creation time is the **identity proof**: we record it at spawn, so a later
  match guarantees the PID still hosts *our* process (a recycled PID gets a
  different creation time → no match → we abstain).
- :func:`is_alive` — whether the PID currently has a non-exited process.
- :func:`tree_kill` — ``taskkill /T /F`` on a PID (kills the whole tree). Spawned
  with ``CREATE_NO_WINDOW`` so it never pops a console window (global no-popup
  rule). Only ever called by the sweeper on a *positive* dead-session match.

On a non-Windows host every probe degrades to "unknown" (``creation_time`` →
``None``, ``is_alive`` → ``False``, ``tree_kill`` → ``False``) so importing this
module is always safe; the real behavior is Windows-only by design (Anchor is a
Windows service).
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

if _IS_WINDOWS:  # pragma: no cover - exercised only on Windows
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _STILL_ACTIVE = 259  # GetExitCodeProcess code for a not-yet-exited process

    class _FILETIME(ctypes.Structure):
        _fields_ = [
            ("dwLowDateTime", wintypes.DWORD),
            ("dwHighDateTime", wintypes.DWORD),
        ]

    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.GetProcessTimes.restype = wintypes.BOOL
    _kernel32.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_FILETIME),
        ctypes.POINTER(_FILETIME),
        ctypes.POINTER(_FILETIME),
        ctypes.POINTER(_FILETIME),
    ]
    _kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    _kernel32.GetExitCodeProcess.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL
    _kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]

    def _filetime_to_epoch(ft: "_FILETIME") -> float:
        raw = (ft.dwHighDateTime << 32) | ft.dwLowDateTime
        return (raw - _EPOCH_AS_FILETIME) / _HUNDRED_NS_PER_SEC

    def _open(pid: int):
        if not pid or pid <= 0:
            return None
        h = _kernel32.OpenProcess(
            _PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid)
        )
        return h or None


def creation_time(pid: int):
    """Return ``pid``'s process creation time as Unix epoch seconds, or ``None``.

    ``None`` means "no such accessible process" — either the PID does not exist,
    has exited, or we lack rights to query it. A real float means a live process
    with that PID exists *and* this is its true start time (the anti-recycle
    identity proof).
    """
    if not _IS_WINDOWS:
        return None
    h = _open(pid)  # pragma: no cover - Windows-only path
    if not h:
        return None
    try:
        creation, exit_, kernel, user = (_FILETIME() for _ in range(4))
        ok = _kernel32.GetProcessTimes(
            h,
            ctypes.byref(creation),
            ctypes.byref(exit_),
            ctypes.byref(kernel),
            ctypes.byref(user),
        )
        if not ok:
            return None
        return _filetime_to_epoch(creation)
    finally:
        _kernel32.CloseHandle(h)


def is_alive(pid: int) -> bool:
    """Whether ``pid`` currently hosts a non-exited process."""
    if not _IS_WINDOWS:
        return False
    h = _open(pid)  # pragma: no cover - Windows-only path
    if not h:
        return False
    try:
        # ``GetExitCodeProcess`` works with a PROCESS_QUERY_LIMITED_INFORMATION
        # handle (unlike ``WaitForSingleObject``, which needs SYNCHRONIZE):
        # a not-yet-exited process reports ``STILL_ACTIVE`` (259).
        code = wintypes.DWORD()
        ok = _kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        if not ok:
            return False
        return code.value == _STILL_ACTIVE
    finally:
        _kernel32.CloseHandle(h)


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


# 0x0800 = PROCESS_SUSPEND_RESUME — the only right we need to (un)freeze a tree.
_PROCESS_SUSPEND_RESUME = 0x0800


def suspend(pid: int) -> bool:
    """Best-effort FREEZE a process (all its threads) so it stops consuming CPU
    while it waits to be killed. Cross-platform: Windows uses the undocumented
    ``ntdll!NtSuspendProcess`` (stdlib ``ctypes`` only — no psutil); POSIX uses
    ``SIGSTOP``. Returns ``True`` on success, never raises. Idempotent at the OS
    level is NOT guaranteed (NtSuspendProcess is counted), so callers should
    track which PIDs they've already suspended and pair every suspend with a
    later :func:`resume`.
    """
    if not pid or int(pid) <= 0:
        return False
    if _IS_WINDOWS:
        try:
            import ctypes
            h = ctypes.windll.kernel32.OpenProcess(
                _PROCESS_SUSPEND_RESUME, False, int(pid))
            if not h:
                return False
            try:
                return ctypes.windll.ntdll.NtSuspendProcess(h) == 0
            finally:
                ctypes.windll.kernel32.CloseHandle(h)
        except Exception:
            return False
    try:
        import os
        import signal
        os.kill(int(pid), signal.SIGSTOP)
        return True
    except Exception:
        return False


def resume(pid: int) -> bool:
    """Best-effort UNFREEZE a process suspended by :func:`suspend`. Windows uses
    ``ntdll!NtResumeProcess``; POSIX uses ``SIGCONT``. Returns ``True`` on
    success, never raises.
    """
    if not pid or int(pid) <= 0:
        return False
    if _IS_WINDOWS:
        try:
            import ctypes
            h = ctypes.windll.kernel32.OpenProcess(
                _PROCESS_SUSPEND_RESUME, False, int(pid))
            if not h:
                return False
            try:
                return ctypes.windll.ntdll.NtResumeProcess(h) == 0
            finally:
                ctypes.windll.kernel32.CloseHandle(h)
        except Exception:
            return False
    try:
        import os
        import signal
        os.kill(int(pid), signal.SIGCONT)
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
