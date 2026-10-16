"""codex-discipline-2026-09-15 Wave 1.6 — the service-wide maintenance barrier.

One in-memory state on the existing restart path (``POST /api/restart``
with ``drain: true``): John's messages keep being accepted into each
steward's persisted queue; no new steward wake, page-open wake or job
launch starts; running turns and jobs reach their own boundary; the watcher
polls until nothing is in flight, then the supervised process restarts onto
the code on disk (the same drain-and-exit a plain restart performs). A fresh
process starts with the flag off by construction.

Every activation this week waited hours because the only tools were "refuse
while busy" and "kill after ten seconds". This is the third option. Stdlib
only; the probes and the restart are injected, so it is testable without a
server.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable

POLL_SECONDS = 5.0
MAX_WAIT_SECONDS = 4 * 3600  # needed because: a drain that never ends must become visible, not silent

_LOCK = threading.Lock()
_STATE: dict[str, Any] = {"active": False}
_THREAD: threading.Thread | None = None
_GENERATION = 0  # needed because: a cancel-then-begin inside one poll must not let the old watcher write


def is_active() -> bool:
    with _LOCK:
        return bool(_STATE.get("active"))


def status() -> dict[str, Any]:
    with _LOCK:
        return dict(_STATE)


def cancel(reason: str = "cancelled") -> dict[str, Any]:
    with _LOCK:
        _STATE.update({"active": False, "cleared_at": time.time(), "cleared_reason": reason})
        return dict(_STATE)


def begin(reason: str, *, busy_engines: Callable[[], list[str]],
          running_jobs: Callable[[], list[str]], restart: Callable[[str], Any],
          poll_seconds: float = POLL_SECONDS, max_wait: float = MAX_WAIT_SECONDS,
          clock: Callable[[], float] = time.time) -> dict[str, Any]:
    """Arm the barrier and start the drain watcher. Idempotent while a watcher
    is alive; re-arms when the flag outlived a dead watcher."""
    global _THREAD, _GENERATION
    with _LOCK:
        if _STATE.get("active") and _THREAD is not None and _THREAD.is_alive():
            return dict(_STATE)
        _GENERATION += 1
        generation = _GENERATION
        _STATE.clear()
        _STATE.update({"active": True, "generation": generation, "reason": str(reason)[:200],
                       "requested_at": clock(), "waiting_on": [], "checks": 0,
                       "restart_called": False})

    def _mine() -> bool:
        return bool(_STATE.get("active")) and _STATE.get("generation") == generation

    def _watch() -> None:
        while True:
            with _LOCK:
                if not _mine():
                    return
                started = _STATE.get("requested_at") or clock()
            try:
                waiting = [f"steward:{k}" for k in busy_engines()] + [f"job:{j}" for j in running_jobs()]
            except Exception as exc:  # a broken probe must not fake a drained system
                waiting = [f"probe-error:{type(exc).__name__}"]
            with _LOCK:
                if not _mine():
                    return
                _STATE["waiting_on"] = waiting[:50]
                _STATE["checks"] = int(_STATE.get("checks", 0)) + 1
                _STATE["last_check_at"] = clock()
                drained = not waiting
                timed_out = clock() - started > max_wait
                if drained:
                    _STATE["restart_called"] = True
                    _STATE["drained_at"] = clock()
                elif timed_out:
                    _STATE.update({"active": False, "cleared_at": clock(),
                                   "cleared_reason": "max wait exceeded; still busy"})
            if drained:
                try:
                    restart(str(reason))
                except Exception as exc:
                    with _LOCK:
                        _STATE.update({"active": False, "cleared_at": clock(),
                                       "cleared_reason": f"restart failed: {type(exc).__name__}"})
                return
            if timed_out:
                return
            time.sleep(poll_seconds)

    _THREAD = threading.Thread(target=_watch, name="anchor-maintenance-barrier", daemon=True)
    _THREAD.start()
    return status()


def handle_op(body: dict[str, Any], *, busy_engines: Callable[[], list[str]],
              running_jobs: Callable[[], list[str]], restart: Callable[[str], Any],
              supervised: bool) -> tuple[dict[str, Any], int]:
    """The ``POST /api/restart`` drain/status/cancel ops (pure; the HTTP
    handler only forwards). ``{"drain": true}`` or ``{"op": "begin"}`` arms
    the barrier; ``{"op": "status"}`` and ``{"op": "cancel"}`` do what they say."""
    op = str(body.get("op") or ("begin" if body.get("drain") else "status"))
    if op == "status":
        return {"ok": True, **status(), "busy_engines": busy_engines(),
                "running_jobs": running_jobs()}, 200
    if op == "cancel":
        return {"ok": True, **cancel("cancelled by request")}, 200
    if op == "begin":
        if not supervised and not body.get("force"):
            return {"ok": False, "error": "not_supervised",
                    "message": "Not running under nssm - a drained exit would leave the server down."}, 409
        state = begin(str(body.get("reason") or "activation"), busy_engines=busy_engines,
                      running_jobs=running_jobs, restart=restart)
        return {"ok": True, **state, "busy_engines": busy_engines(),
                "running_jobs": running_jobs()}, 200
    return {"ok": False, "error": "unknown op"}, 400
