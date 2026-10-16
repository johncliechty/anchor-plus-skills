#!/usr/bin/env python3
"""Restart-durable, PROTECT-ONLY freeze state (Anchor zombie-hunter, Wave 7).

The safe-to-arm ladder is pause-first: the reaper's FIRST destructive tier is a
*reversible* freeze (per-PID suspend), never a kill. For that freeze to be
trustworthy across an NSSM ``anchor`` service restart, the set of frozen sessions
must be **persisted crash-safely** and **re-honored** when the process comes back
— but the persisted state must never, by itself, be able to authorize a KILL.
This module is that persisted-frozen-set + the restart reconcile.

────────────────────────────────────────────────────────────────────────────
THE TWO LOAD-BEARING PROPERTIES (criteria 9, 14)
────────────────────────────────────────────────────────────────────────────

1. **Crash-safe, protect-only persistence.** The frozen-set lives in
   ``.anchor/reaper_frozen.json``, written atomically (tmp file + ``os.replace``,
   under ``paths.WRITE_LOCK``) BEFORE any arming, so a crash mid-write can never
   leave a truncated store. A persisted entry may only ever cause the process to
   **keep a session frozen** or **thaw** it — it can NEVER, on its own, cause a
   kill. A ``would-kill`` marker (dry-run telemetry) is honestly recorded but is
   INERT on restart: reconcile never acts on it. Any post-restart destructive
   action is re-derived IN-PROCESS from a fresh live probe
   (:func:`rederive_kill_authorized` → :func:`reaper.kill_authorized`), never
   read out of the file.

2. **Per-PID suspend/resume is the FLOOR.** Freeze does not rely on any OS
   containment (Job Objects, ``KILL_ON_JOB_CLOSE``, etc.). It is a plain
   ``ntdll!NtSuspendProcess`` / ``SIGSTOP`` on the owning PID
   (:func:`proc_probe.suspend`). OS-level process containment is DEMOTED to a
   non-load-bearing enhancement: it is deliberately NOT built into the critical
   path here, so when it is absent the service restart cannot trigger a
   mass-kill-on-handle-close (there is no handle whose close kills anything), and
   freeze still works via the verified per-PID primitive.

────────────────────────────────────────────────────────────────────────────
RESTART RECONCILE — re-probe, then re-establish freeze from scratch
────────────────────────────────────────────────────────────────────────────
:func:`reconcile_after_restart` treats the persisted frozen-set as *advisory,
to be revalidated*. For each entry it re-probes the owning PID's identity
(creation-time match — the anti-recycle guard, identical to the reaper's
``owner_alive`` rule):

  • **alive + identity matches** and state is ``frozen`` → the session is
    re-suspended (freeze re-established FROM SCRATCH — a suspend does not durably
    survive our process boundary in a guaranteed way, so we re-assert it) and the
    entry is KEPT.
  • **alive + identity matches** and state is ``would-kill`` → KEPT as a pending
    marker for in-process re-derivation; NOTHING is suspended or killed.
  • **dead** (PID gone) → there is nothing to freeze; the entry is dropped.
  • **recycled** (PID alive but creation-time mismatches) → a DIFFERENT process
    now holds that PID; the stale entry is dropped and the new owner is NEVER
    touched (never suspended, never killed).

Reconcile calls a ``suspend`` seam and NOTHING else destructive — it holds no
reference to any kill primitive, which is what structurally guarantees the
protect-only invariant.

Stdlib only. No third-party imports.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import paths as _paths

_log = logging.getLogger("anchor.freeze_state")


# ── On-disk location ─────────────────────────────────────────────────────────
FROZEN_NAME = "reaper_frozen.json"
ANCHOR_DIRNAME = ".anchor"

# ── Frozen-entry states ──────────────────────────────────────────────────────
#: The session is actively suspended (a real, reversible freeze). Protect-only:
#: reconcile re-asserts the suspend; it is the only state that touches a process.
STATE_FROZEN = "frozen"
#: A DRY-RUN telemetry marker: the reaper decided the session WOULD be killed had
#: it been armed to kill. It is recorded for precision measurement ONLY and is
#: INERT on restart — reconcile never suspends or kills on a would-kill marker.
STATE_WOULD_KILL = "would-kill"

VALID_STATES = frozenset((STATE_FROZEN, STATE_WOULD_KILL))

#: Default creation-time drift (seconds) for the identity-reuse guard — matches
#: the reaper's ``tol`` so "same process" means the same thing everywhere.
DEFAULT_TOL = 2.0


def anchor_dir() -> Path:
    """Absolute path to the ``.anchor/`` dir under the resolved data dir."""
    return _paths.data_dir() / ANCHOR_DIRNAME


def frozen_path() -> Path:
    """Absolute path to the persisted frozen-set (``.anchor/reaper_frozen.json``)."""
    return anchor_dir() / FROZEN_NAME


# ── Frozen entry (minimal, immutable metadata) ───────────────────────────────

@dataclass(frozen=True)
class FrozenEntry:
    """One persisted freeze record — the MINIMAL metadata reconcile needs.

    ``pid`` + ``proc_create_time`` form the identity tuple: on restart the PID is
    re-probed and its creation time must match ``proc_create_time`` within ``tol``
    or the entry is treated as RECYCLED (a different process now holds the PID) and
    dropped — never touched. Nothing here can encode "kill"; ``state`` is only ever
    :data:`STATE_FROZEN` or :data:`STATE_WOULD_KILL`.
    """

    session_id: str
    pid: Optional[int] = None
    proc_create_time: Optional[float] = None
    state: str = STATE_FROZEN
    frozen_at: Optional[float] = None
    reason: str = ""
    #: Wave 8 auto-thaw watchdog: the epoch after which this freeze must be
    #: automatically resumed (``reaper_arming.auto_thaw_expired``) so a freeze can
    #: never be forgotten forever. ``None`` ⇒ no watchdog (a legacy / manual
    #: freeze) — the conservative reading is "do not auto-thaw", never "thaw now".
    thaw_deadline: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "pid": self.pid,
            "proc_create_time": self.proc_create_time,
            "state": self.state,
            "frozen_at": self.frozen_at,
            "reason": self.reason,
            "thaw_deadline": self.thaw_deadline,
        }


def _coerce_pid(value):
    try:
        p = int(value)
    except (TypeError, ValueError):
        return None
    return p if p > 0 else None


def _coerce_float(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_entry(raw: dict) -> Optional[FrozenEntry]:
    """Coerce a stored dict into a :class:`FrozenEntry`, or ``None`` if unusable.

    An unknown/blank ``state`` folds to :data:`STATE_FROZEN` — the conservative
    over-protect reading (treat an ambiguous record as a real freeze to re-assert,
    never as a would-kill that could be misread as license to act).
    """
    if not isinstance(raw, dict):
        return None
    sid = raw.get("session_id")
    if not sid:
        return None
    state = raw.get("state")
    if state not in VALID_STATES:
        state = STATE_FROZEN
    return FrozenEntry(
        session_id=str(sid),
        pid=_coerce_pid(raw.get("pid")),
        proc_create_time=_coerce_float(raw.get("proc_create_time")),
        state=state,
        frozen_at=_coerce_float(raw.get("frozen_at")),
        reason=str(raw.get("reason") or ""),
        thaw_deadline=_coerce_float(raw.get("thaw_deadline")),
    )


# ── Persistence (best-effort load; atomic, lock-guarded write) ────────────────

def load_frozen() -> dict:
    """Load the persisted frozen-set as ``{session_id: FrozenEntry}``.

    Best-effort: a missing / unreadable / corrupt store returns ``{}`` (a corrupt
    frozen-set must never crash boot — it just means "nothing to re-honor"). The
    JSON on disk is a list of entry dicts.
    """
    p = frozen_path()
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError):
        return {}
    out = {}
    if isinstance(raw, list):
        for e in raw:
            entry = _normalize_entry(e)
            if entry is not None:
                out[entry.session_id] = entry
    elif isinstance(raw, dict):
        for k, e in raw.items():
            if isinstance(e, dict):
                e = dict(e)
                e.setdefault("session_id", k)
            entry = _normalize_entry(e)
            if entry is not None:
                out[entry.session_id] = entry
    return out


#: Bounded retry for the atomic ``os.replace`` on Windows — a concurrent
#: read-only sweep holding the target open triggers a transient sharing
#: violation (``PermissionError``, NOT a real permission fault); a few short
#: backed-off retries turn the race into a correct atomic write. POSIX never hits
#: it (first attempt succeeds). Mirrors ``session_registry``'s discipline.
_REPLACE_RETRIES = 40
_REPLACE_BACKOFF_S = 0.005


def _atomic_replace(tmp: str, target: str) -> None:
    """``os.replace`` with a bounded retry over the transient Windows sharing
    violation raised while a concurrent reader has ``target`` open."""
    for attempt in range(_REPLACE_RETRIES):
        try:
            os.replace(tmp, target)
            return
        except PermissionError:
            if attempt == _REPLACE_RETRIES - 1:
                raise
            time.sleep(_REPLACE_BACKOFF_S)


def _write_frozen_locked(entries: dict) -> None:
    """The atomic write itself — caller MUST already hold ``paths.WRITE_LOCK``.

    Writes to a sibling tmp file then ``os.replace`` over the target (tmp+rename
    durability discipline), so a crash mid-write can never leave a truncated /
    corrupt frozen-set. Ensures the ``.anchor/`` dir exists first.
    """
    d = anchor_dir()
    d.mkdir(parents=True, exist_ok=True)
    items = [
        (e.to_dict() if isinstance(e, FrozenEntry) else dict(e))
        for e in entries.values()
    ]
    target = frozen_path()
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(items, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    _atomic_replace(str(tmp), str(target))


def save_frozen(entries: dict, *, _locked: bool = False) -> None:
    """Persist ``{session_id: FrozenEntry}`` atomically.

    Mirrors :mod:`session_registry`'s split-critical-section discipline: a caller
    already holding ``paths.WRITE_LOCK`` passes ``_locked=True`` so the write does
    NOT re-acquire the lock. ``paths.WRITE_LOCK`` is reentrant today, but the split
    keeps the code correct even if it were not.
    """
    if _locked:
        _write_frozen_locked(entries)
    else:
        with _paths.WRITE_LOCK:
            _write_frozen_locked(entries)


# ── Freeze / thaw / would-kill (the mutating ops) ────────────────────────────

def _identity_of(record) -> tuple:
    """Extract ``(session_id, pid, proc_create_time)`` from a session record."""
    sid = record.get("session_id")
    return (sid,
            _coerce_pid(record.get("pid")),
            _coerce_float(record.get("proc_create_time")))


def freeze_session(record, *, suspend=None, now=None, reason="",
                   thaw_deadline=None) -> dict:
    """FREEZE a session: persist the entry FIRST, THEN suspend its PID.

    Persist-before-suspend is deliberate: if the process crashes between the two
    steps, the frozen-set already knows the session should be frozen, and
    :func:`reconcile_after_restart` re-establishes the suspend from scratch. The
    reverse order could leave a suspended process with no record to resume it.

    ``suspend`` — the freeze primitive ``pid -> bool``; defaults to
    :func:`proc_probe.suspend` (per-PID ``NtSuspendProcess`` / ``SIGSTOP``). Only
    the per-PID floor is used — no OS containment.

    Returns ``{"ok": bool, "suspended": bool}``. ``ok`` reflects the persist; a
    ``False`` ``suspended`` (a process that vanished before we could suspend it)
    is not an error — reconcile / a fresh probe handles the aftermath.
    """
    sid, pid, ctime = _identity_of(record)
    if not sid:
        return {"ok": False, "suspended": False}
    if now is None:
        now = time.time()
    entry = FrozenEntry(session_id=sid, pid=pid, proc_create_time=ctime,
                        state=STATE_FROZEN, frozen_at=now, reason=reason or "",
                        thaw_deadline=_coerce_float(thaw_deadline))
    with _paths.WRITE_LOCK:
        entries = load_frozen()
        entries[sid] = entry
        save_frozen(entries, _locked=True)
    suspended = False
    if pid is not None:
        if suspend is None:
            try:
                import proc_probe
                suspend = proc_probe.suspend
            except Exception:  # pragma: no cover - defensive import guard
                suspend = lambda _p: False
        try:
            suspended = bool(suspend(pid))
        except Exception:
            suspended = False
    return {"ok": True, "suspended": suspended}


def thaw_session(session_id, *, resume=None) -> dict:
    """THAW a frozen session: resume its PID, then drop the persisted entry.

    ``resume`` — the unfreeze primitive ``pid -> bool``; defaults to
    :func:`proc_probe.resume`. A missing entry is a no-op (idempotent).
    """
    if not session_id:
        return {"ok": False, "resumed": False}
    resumed = False
    with _paths.WRITE_LOCK:
        entries = load_frozen()
        entry = entries.pop(session_id, None)
        save_frozen(entries, _locked=True)
    if entry is not None and entry.pid is not None:
        if resume is None:
            try:
                import proc_probe
                resume = proc_probe.resume
            except Exception:  # pragma: no cover - defensive import guard
                resume = lambda _p: False
        try:
            resumed = bool(resume(entry.pid))
        except Exception:
            resumed = False
    return {"ok": True, "resumed": resumed}


def mark_would_kill(record, *, now=None, reason="") -> dict:
    """Record a DRY-RUN ``would-kill`` marker — NEVER suspends, NEVER kills.

    This is the arming-gate telemetry hook (criterion 16): what the daemon WOULD
    have killed had it been armed, captured so precision can be measured on the
    live service before the arm flag is ever set. It touches no process and is
    inert on restart — :func:`reconcile_after_restart` never acts on it.
    """
    sid, pid, ctime = _identity_of(record)
    if not sid:
        return {"ok": False}
    if now is None:
        now = time.time()
    entry = FrozenEntry(session_id=sid, pid=pid, proc_create_time=ctime,
                        state=STATE_WOULD_KILL, frozen_at=now, reason=reason or "")
    with _paths.WRITE_LOCK:
        entries = load_frozen()
        entries[sid] = entry
        save_frozen(entries, _locked=True)
    return {"ok": True}


# ── Read accessors ───────────────────────────────────────────────────────────

def get_entry(session_id) -> Optional[FrozenEntry]:
    """The persisted :class:`FrozenEntry` for ``session_id``, or ``None``."""
    return load_frozen().get(session_id)


def is_frozen(session_id) -> bool:
    """Whether ``session_id`` is persisted in the actively-frozen state."""
    e = load_frozen().get(session_id)
    return e is not None and e.state == STATE_FROZEN


def frozen_session_ids() -> set:
    """The set of session ids persisted in the actively-frozen state."""
    return {sid for sid, e in load_frozen().items() if e.state == STATE_FROZEN}


# ── Restart reconcile (the keystone) ─────────────────────────────────────────

@dataclass(frozen=True)
class ReconcileResult:
    """Outcome of one restart reconcile pass.

    ``re_frozen``          — session ids re-suspended and kept frozen (alive +
                             identity-matched ``frozen`` entries);
    ``thawed``             — session ids dropped because their PID is gone or was
                             RECYCLED by a different process (never touched);
    ``would_kill_pending`` — ``would-kill`` markers still alive+matched, KEPT as
                             pending; reconcile did NOT act on them — any kill must
                             be re-derived in-process from a fresh live probe.
    """

    re_frozen: tuple = ()
    thawed: tuple = ()
    would_kill_pending: tuple = ()


def _probe_ctime(probe, pid):
    """Re-probe ``pid``'s creation time via the ``probe`` seam, or ``None``.

    Uses ``probe.creation_time(pid)`` (the same seam the reaper snapshot uses) so
    a unit test can drive reconcile with a pure creation-time fake. Any probe
    failure is ``None`` (treated as "gone") — never raises.
    """
    if pid is None:
        return None
    try:
        return _coerce_float(probe.creation_time(pid))
    except Exception:
        return None


def reconcile_after_restart(*, probe=None, suspend=None, tol=DEFAULT_TOL) -> ReconcileResult:
    """Re-probe every persisted freeze entry and RE-ESTABLISH freeze from scratch.

    PROTECT-ONLY by construction: this function holds no reference to any kill
    primitive. It can only (a) re-suspend an alive, identity-matched ``frozen``
    session, (b) drop a dead/recycled entry, or (c) keep a ``would-kill`` marker
    pending. A persisted marker can therefore NEVER cause a kill on restart — the
    kill decision is re-derived in-process elsewhere (:func:`rederive_kill_authorized`).

    ``probe``   — supplies ``creation_time(pid)``; defaults to :mod:`proc_probe`.
    ``suspend`` — the re-freeze primitive ``pid -> bool``; defaults to
                  :func:`proc_probe.suspend`. Called ONLY for kept-frozen entries.
    ``tol``     — creation-time drift for the identity-reuse guard.

    The surviving set (kept-frozen + kept-would-kill) is re-persisted atomically;
    dropped entries are removed. Best-effort — a load/probe failure degrades to an
    empty pass, never raises.
    """
    if probe is None:
        try:
            import proc_probe as probe
        except Exception:  # pragma: no cover - defensive import guard
            return ReconcileResult()
    if suspend is None:
        try:
            import proc_probe
            suspend = proc_probe.suspend
        except Exception:  # pragma: no cover - defensive import guard
            suspend = lambda _p: False

    try:
        entries = load_frozen()
    except Exception:  # pragma: no cover - load_frozen already best-effort
        return ReconcileResult()

    re_frozen = []
    thawed = []
    would_kill_pending = []
    survivors = {}

    for sid, entry in entries.items():
        pid = entry.pid
        stored_ct = entry.proc_create_time
        actual_ct = _probe_ctime(probe, pid)

        # Identity-reuse guard (anti-recycle): the PID must resolve to a LIVE
        # process whose creation time matches the recorded identity tuple.
        alive_and_ours = (
            actual_ct is not None and stored_ct is not None
            and abs(actual_ct - stored_ct) <= tol
        )

        if not alive_and_ours:
            # Dead (actual_ct is None) OR recycled (a different process now holds
            # the PID) — drop the stale entry. NEVER suspend/kill the new owner.
            thawed.append(sid)
            continue

        if entry.state == STATE_WOULD_KILL:
            # Protect-only: a would-kill marker is INERT here. Keep it pending;
            # re-derivation happens in-process from a fresh live probe.
            survivors[sid] = entry
            would_kill_pending.append(sid)
            continue

        # A live, identity-matched frozen session: re-establish the freeze from
        # scratch (re-assert the per-PID suspend — the floor mechanism, no OS
        # containment relied upon).
        try:
            suspend(pid)
        except Exception:
            pass
        survivors[sid] = entry
        re_frozen.append(sid)

    try:
        with _paths.WRITE_LOCK:
            save_frozen(survivors, _locked=True)
    except Exception as e:  # pragma: no cover - best-effort persist
        _log.error("freeze_state reconcile persist failed: %s", e)

    if thawed or re_frozen or would_kill_pending:
        _log.info(
            "freeze_state reconcile: re-froze %d, dropped %d (dead/recycled), "
            "%d would-kill marker(s) pending in-process re-derivation",
            len(re_frozen), len(thawed), len(would_kill_pending))

    return ReconcileResult(
        re_frozen=tuple(re_frozen),
        thawed=tuple(thawed),
        would_kill_pending=tuple(would_kill_pending),
    )


def rederive_kill_authorized(record, snapshot, *, revalidate=None, tol=DEFAULT_TOL) -> bool:
    """Re-derive kill authorization IN-PROCESS from a fresh live probe.

    This is the ONLY sanctioned path from a persisted ``would-kill`` marker to an
    actual destructive action after a restart: the marker itself authorizes
    nothing; a caller must feed a freshly-built liveness ``snapshot`` (and,
    immediately before acting, a ``revalidate`` callable) through
    :func:`reaper.kill_authorized`, which rests on POSITIVE proof of death. A
    ``None``/degraded snapshot or any fault → ``False`` (never authorize on
    uncertainty). Thin, deliberate delegation so the protect-only boundary is
    unmistakable in the call graph.
    """
    try:
        import reaper
        return reaper.kill_authorized(record, snapshot, revalidate=revalidate, tol=tol)
    except Exception:
        return False
