#!/usr/bin/env python3
"""Anchor zombie-hunter sweeper — orphaned sub-agent reaper (stdlib only).

Per Skill-Foundry PLAN.md (zombie-hunter v2): the background sweeper that
guarantees zero orphaned sub-agents ("zombies"). A managed terminal session
spawns a backend process (claude/gemini) whose PID + that PID's creation time +
a per-session crypt token are recorded on the session record at spawn
(``session_registry`` schema). On a periodic sweep we ask, for every record the
registry still marks RUNNING: *is this process still ours, and is anyone still
attached to it?* If it is OUR process (creation-time identity proof matches) and
NOT attached, it is an orphan → kill it and reap the record.

The decision is a **pure** :func:`classify` so the kill/no-kill verdict is unit
testable without any real process. The daemon (:func:`start_hunter`) is OFF by
default and only auto-kills when ``ANCHOR_ZOMBIE_HUNTER=1`` is set explicitly.

Safety invariants (encoded in the verdict taxonomy):

- A missing identity (no token / no pid / no recorded creation time) → ABSTAIN.
  We NEVER kill and NEVER auto-reap a record we cannot positively identify;
  it is flagged for manual review instead.
- A creation-time mismatch means the PID was RECYCLED by a different process →
  we update our registry but NEVER kill the new owner.
- We only ever kill a process whose recorded creation time still matches the
  live PID's creation time (proof it is ours) AND whose session is not in the
  live/attached set (proof it is orphaned).

Stdlib only. No third-party imports.
"""

from __future__ import annotations

import json
import os
import threading
import time

import proc_probe
import session_registry


# ── Verdict taxonomy ────────────────────────────────────────────────────────

#: The verdict strings :func:`classify` may return.
VERDICT_SKIP = "skip"
VERDICT_ABSTAIN = "abstain"
VERDICT_REAP_DEAD = "reap_dead"
VERDICT_REAP_RECYCLED = "reap_recycled"
VERDICT_ALIVE = "alive"
VERDICT_KILL = "kill"

#: Where the last sweep report is persisted (a dashboard reads real metrics).
LAST_REPORT_NAME = "zombie_hunter_last.json"

#: Env var that arms the daemon. OFF unless set to exactly "1".
HUNTER_ENV = "ANCHOR_ZOMBIE_HUNTER"


# ── Orphan PAUSE bookkeeping ────────────────────────────────────────────────
# An orphaned (detached) session keeps burning CPU until the user decides to
# kill it. We FREEZE such a process while it waits (proc_probe.suspend) so it
# can't do further work, and track which PIDs we've frozen so we never
# double-suspend (NtSuspendProcess is counted — every suspend needs a matching
# resume). PAUSE is reversible: :func:`resume_pid` un-freezes; a kill calls
# :func:`forget_pid`. In-memory only (a server restart leaves an orphan frozen,
# which is acceptable — it was already slated to die).
_PAUSED_PIDS: set = set()
_PAUSE_LOCK = threading.Lock()


def pause_orphan(pid) -> bool:
    """Freeze an orphaned process ONCE. No-op if already frozen. Best-effort.

    HARD GUARD: never freezes anything under pytest (``PYTEST_CURRENT_TEST``) —
    tests render the report with synthetic PIDs against the real probe, and a
    synthetic PID could collide with a real process. Production only.
    """
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    with _PAUSE_LOCK:
        if pid in _PAUSED_PIDS:
            return True
        if proc_probe.suspend(pid):
            _PAUSED_PIDS.add(pid)
            return True
    return False


def resume_pid(pid) -> bool:
    """Un-freeze a paused process and stop tracking it. Best-effort."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    ok = proc_probe.resume(pid)
    with _PAUSE_LOCK:
        _PAUSED_PIDS.discard(pid)
    return ok


def is_paused(pid) -> bool:
    """Whether we have this PID frozen."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    with _PAUSE_LOCK:
        return pid in _PAUSED_PIDS


def forget_pid(pid) -> None:
    """Drop a PID from the paused set (called after a kill — no resume needed)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return
    with _PAUSE_LOCK:
        _PAUSED_PIDS.discard(pid)


def classify(record, live_session_ids, probe=proc_probe, tol=2.0) -> str:
    """Pure verdict for one session ``record``. Returns a verdict string.

    ``record`` is a normalized session record (a dict). ``live_session_ids`` is
    the set of currently-attached session ids. ``probe`` supplies
    ``creation_time(pid)`` (injectable for tests). ``tol`` is the allowed
    creation-time drift in seconds (FILETIME vs. recorded epoch jitter).

    Backward-compatible shim (Wave 1, single-source): the verdict LOGIC now lives
    in :func:`reaper.classify`. This shim samples the ONE identity signal
    ``reaper.classify`` needs for THIS record from the injected probe (a one-entry
    positive-liveness map) and delegates, so there is a single source of the
    verdict taxonomy.

    Verdicts:
      - ``"skip"``          — record is not RUNNING; not our concern.
      - ``"abstain"``       — missing identity (no token / pid / create-time):
                              NEVER kill, NEVER auto-reap; flag for review.
      - ``"reap_dead"``     — the recorded PID has no live process: gone already,
                              update registry only (no kill).
      - ``"reap_recycled"`` — the PID is live but its creation time differs: the
                              PID was reused by a DIFFERENT process; update our
                              registry, NEVER kill the new owner.
      - ``"alive"``         — our process, still running, and OWNED: leave it.
      - ``"kill"``          — our process, still running, NO live owner → orphan →
                              kill + reap.
    """
    import reaper

    sid = record.get("session_id")
    pid = record.get("pid")
    positive = {}
    if sid and pid:
        try:
            actual = probe.creation_time(pid)
        except Exception:
            actual = None
        positive[sid] = reaper.PositiveSignals(owner_pid=pid,
                                               owner_create_time=actual)

    owners = set(live_session_ids or ())
    return reaper.classify(record, owners, positive, tol=tol)


# ── Orphan discriminator — the "live owner" set ─────────────────────────────
# (#1, safety-critical) A registered-RUNNING session is a true orphan only if it
# is identity-alive AND has NO LIVE OWNER. Being attached to a PTY/browser stream
# is just ONE kind of owner: a session is equally NOT-orphaned when an
# actively-running owning job backs it, or when a live parent session owns it. So
# the set we hand to :func:`classify` as "attached/live" must be broadened from
# the bare ``pty_manager.live_sessions()`` to the full live-owner set. Without
# this, a legit, work-doing swarm/lane session with no OPEN browser stream falls
# out of the attached set and is classed ``kill`` → false banner / false freeze /
# (with the daemon armed) a false kill. The line is **live owner**, never
# "effort-bound" — binding to an effort must NOT neuter the hunter.

def live_owner_ids(attached_ids, records=None, job_active=None):
    """Expand an attached/streaming session-id set to every session with a LIVE OWNER.

    ``attached_ids`` — the base set of sessions with a live PTY/browser stream
                       (e.g. ``set(pty_manager.live_sessions())``).
    ``records``      — the RUNNING session records to consider; defaults to
                       ``session_registry.list_sessions(status="running")``.
    ``job_active``   — callable ``session_id -> bool`` reporting whether an
                       actively-running OWNING JOB backs the session; defaults to
                       ``job_runner._holder_is_active`` (the session_id IS the
                       job_id for a swarm/lane job). Injectable for tests.

    A session counts as OWNED when it is attached, OR an owning job is active,
    OR (transitively) its ``parent_session_id`` has a live owner. Returns a NEW
    set that is always a superset of ``attached_ids``. Best-effort: any probe
    failure degrades to "not owned via that path", never raises.

    Backward-compatible shim (Wave 1, single-source): the owner-enumeration LOGIC
    now lives in :mod:`reaper`. This builds an ownership-only snapshot (no PID
    probe — ``reaper.NO_PROBE``) and returns ``reaper.live_owner_ids`` over it, so
    every caller shares the ONE canonical live-owner computation.
    """
    import reaper

    snap = reaper.build_snapshot(
        attached_pty_ids=attached_ids,
        records=records,
        job_active=job_active,
        probe=reaper.NO_PROBE,
    )
    return reaper.live_owner_ids(snap)


# ── Report persistence ──────────────────────────────────────────────────────

def _last_report_path():
    """Absolute path to the persisted last-sweep report."""
    return session_registry.anchor_dir() / LAST_REPORT_NAME


def _persist_report(report) -> None:
    """Atomically persist ``report`` to ``.anchor/zombie_hunter_last.json``.

    Mirrors the registry's atomic-write discipline (tmp file + ``os.replace``)
    under ``paths.WRITE_LOCK``. Best-effort: a persistence failure must never
    break the sweep loop.
    """
    try:
        import paths as _paths
        with _paths.WRITE_LOCK:
            d = session_registry.anchor_dir()
            d.mkdir(parents=True, exist_ok=True)
            target = _last_report_path()
            tmp = target.with_name(target.name + ".tmp")
            tmp.write_text(
                json.dumps(report, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            os.replace(str(tmp), str(target))
    except Exception:  # pragma: no cover - persistence is best-effort
        pass


# ── Sweep ───────────────────────────────────────────────────────────────────

def sweep(live_session_ids, probe=proc_probe, killer=None, apply=True) -> dict:
    """Classify every RUNNING session and act on the verdict. Returns a report.

    ``killer`` defaults to :func:`proc_probe.tree_kill`. The report is::

        {"killed": [...], "reaped_dead": [...], "reaped_recycled": [...],
         "abstained": [...], "alive": [...], "swept_at": float, "total": int}

    Actions (only when ``apply=True``):
      - kill: call ``killer(pid)``; ALWAYS set the session to ``STATUS_IDLE``
        (even on a kill failure — avoid a wedged record) → ``killed``.
      - reap_dead / reap_recycled: set ``STATUS_IDLE`` (no kill).
      - abstain: no mutation, no kill (flagged for manual review).
      - alive: no mutation.

    With ``apply=False`` it is a dry-run: classify + report only, NO kills and
    NO registry mutations, and the report is NOT persisted.
    """
    if killer is None:
        killer = proc_probe.tree_kill
    live = set(live_session_ids) if live_session_ids is not None else set()

    report = {
        "killed": [],
        "reaped_dead": [],
        "reaped_recycled": [],
        "abstained": [],
        "alive": [],
        "swept_at": time.time(),
        "total": 0,
    }

    reg = session_registry.load_sessions()
    for sid, rec in reg.items():
        if rec.get("status") != session_registry.STATUS_RUNNING:
            continue
        report["total"] += 1
        verdict = classify(rec, live, probe=probe)

        if verdict == VERDICT_KILL:
            if apply:
                try:
                    killer(rec.get("pid"))
                except Exception:  # pragma: no cover - killer is injected/defensive
                    pass
                # Always reap to avoid a wedged record, even on a kill failure.
                _mark_idle(sid)
            report["killed"].append(sid)
        elif verdict == VERDICT_REAP_DEAD:
            if apply:
                _mark_idle(sid)
            report["reaped_dead"].append(sid)
        elif verdict == VERDICT_REAP_RECYCLED:
            if apply:
                _mark_idle(sid)
            report["reaped_recycled"].append(sid)
        elif verdict == VERDICT_ABSTAIN:
            report["abstained"].append(sid)
        elif verdict == VERDICT_ALIVE:
            report["alive"].append(sid)
        # VERDICT_SKIP cannot occur here (we pre-filter to RUNNING).

    if apply:
        _persist_report(report)
    return report


def _mark_idle(session_id) -> None:
    """Set a session to ``STATUS_IDLE`` (best-effort; never raises out)."""
    try:
        session_registry.update_session(
            session_id, status=session_registry.STATUS_IDLE
        )
    except Exception:  # pragma: no cover - defensive against a vanished record
        pass


# ── Daemon ──────────────────────────────────────────────────────────────────

_hunter_thread = None
_stop_event = None
_hunter_lock = threading.Lock()


def start_hunter(live_ids_provider, interval_sec=600, enabled=None, sweep_fn=None):
    """Start the background sweep daemon. Returns the thread, or ``None``.

    By default, starting is enabled (runs in dry-run mode, apply=False, unless
    ANCHOR_ZOMBIE_HUNTER == "1").

    When enabled, start exactly ONE daemon thread (a module global guards
    against a second concurrent daemon; a second call is a no-op returning the
    existing thread). The loop calls ``sweep(live_ids_provider(), apply=...)`` every
    ``interval_sec`` seconds, swallowing+logging any exception so the loop never
    dies. ``live_ids_provider`` is a zero-arg callable returning the set of
    currently-attached session ids.

    ``sweep_fn`` (Wave 8) — an optional zero-arg callable run INSTEAD of the
    legacy ``sweep`` each cycle. The boot daemon passes the arming-ladder sweep
    (:func:`reaper_arming.armed_sweep`, governed by the effective arm tier +
    kill-switch brake) so the daemon is UNARMED by default and only ever kills
    through the in-process, gate-authorized ladder. When ``None`` the legacy
    dry-run/env-armed behavior is unchanged.
    """
    global _hunter_thread, _stop_event

    if enabled is None:
        enabled = True
    if not enabled:
        return None

    with _hunter_lock:
        if _hunter_thread is not None and _hunter_thread.is_alive():
            return _hunter_thread  # already running — no-op

        _stop_event = threading.Event()
        stop = _stop_event

        def _loop():
            # Sweep immediately on start, then every interval until stopped.
            while not stop.is_set():
                try:
                    if sweep_fn is not None:
                        sweep_fn()
                    else:
                        apply_kills = os.environ.get(HUNTER_ENV) == "1"
                        sweep(live_ids_provider(), apply=apply_kills)
                except Exception as exc:  # never let the loop die
                    try:
                        print(f"[zombie_hunter] sweep error: {exc!r}")
                    except Exception:
                        pass
                stop.wait(interval_sec)

        t = threading.Thread(
            target=_loop, name="anchor-zombie-hunter", daemon=True
        )
        _hunter_thread = t
        t.start()
        return t


def stop_hunter() -> None:
    """Signal the daemon loop to end (idempotent). Does not join."""
    global _hunter_thread, _stop_event
    with _hunter_lock:
        if _stop_event is not None:
            _stop_event.set()
        _hunter_thread = None
