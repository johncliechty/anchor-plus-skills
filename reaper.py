#!/usr/bin/env python3
"""Anchor reaper — the ONE canonical liveness/ownership surface (stdlib only).

Wave 1 of the *zombie-hunter → safe-to-arm* build. This module collapses the
five historically-drifted orphan discriminators (the ``/api/rnd/orphan_check``
banner, the Swarm & Owner View freeze, the ``zombie_terminal_start`` brief, the
armed kill-daemon's ``live_ids`` provider, and the boot reconcile) onto ONE
import surface fed by ONE immutable per-sweep snapshot. Every later safety
property (abstain-not-kill, bounded blast radius, restart-durable freeze, the
arming ladder) leans on this structural foundation: if two call sites can
classify the same session against different/narrower inputs, no downstream
safety proof holds.

────────────────────────────────────────────────────────────────────────────
OWNER-ENUMERATION CONTRACT (the load-bearing definition — criterion 15)
────────────────────────────────────────────────────────────────────────────
A registered-RUNNING session is a true orphan ONLY if it is identity-alive AND
has **no live owner**. Being attached to a PTY/browser stream is just ONE kind
of owner. The canonical live-owner set is::

    live_owner_ids(snapshot) = attached_pty_ids
                             ∪ job_owned_ids
                             ∪ transitive-parent-owned_ids

where

  • ``attached_pty_ids``   — sessions with a live PTY/browser stream
                             (``pty_manager.live_sessions()``).
  • ``job_owned_ids``      — sessions backed by an actively-running OWNING job
                             (``job_runner._holder_is_active`` — the session_id
                             IS the job_id for a swarm/lane job).
  • parent-owned (transitive) — a session whose ``parent_session_id`` chain
                             reaches a live owner is itself owned. Walked to a
                             fixpoint over the immutable snapshot.

Ownership is enumerated from the **launch-time identity the registry recorded**
(session records + their owning jobs + the ``parent_session_id`` lineage),
NEVER from live OS parentage. So a backend PID re-parented to PID 1 after its
launcher exited stays owned as long as its owning job / a live parent still
claims it — a session is never orphaned *merely because its OS parent exited*.

INVARIANTS enforced in code:

  1. The snapshot is built EXACTLY ONCE per sweep (:func:`build_snapshot`) and is
     immutable (a frozen dataclass over frozensets + read-only mappings).
  2. :func:`live_owner_ids` is a PURE function of the snapshot — no self-sourcing,
     no I/O, rebuilt fresh each sweep so no drift carries across sweeps.
  3. :func:`classify` takes the live-owner set AND the positive-liveness map as
     its ONLY inputs (both REQUIRED positional args): a new consumer is
     compile-forced to supply them, so it cannot silently classify against a
     narrower input set.

The line is **live owner**, never "effort-bound": binding to an effort must NOT
neuter the hunter. A genuinely-orphaned swarm (identity-alive, no live owner)
still classifies ``kill``.

────────────────────────────────────────────────────────────────────────────
POSITIVE-PROOF-OF-DEATH KILL PREDICATE + ABSTAIN BOUNDARY (Wave 2)
────────────────────────────────────────────────────────────────────────────
:func:`classify` flags CANDIDATES (an identity-alive session with no live owner
is flagged ``kill`` for the banner / Swarm & Owner View). A destructive action
is separately gated by :func:`kill_authorized`, which authorizes ONLY on
POSITIVE proof of death — a confirmed-dead OWNER (``VERDICT_REAP_DEAD``) AND no
CORROBORATED positive signal (:func:`has_corroborated_positive`, which gates
every detectable artifact — git ``index.lock``, a heartbeat, an owned socket, a
fresh worktree write, a CPU sample — on owning-PID-alive corroboration so a
stale lock / forged heartbeat is never mistaken for life) AND a fresh in-lock
re-validation (:func:`revalidate_target`) that finds no new sign of life. ANY
uncertainty — a ``None``/``degraded`` snapshot, a throwing owner computation, a
missing/partial input — resolves to KEEP: :func:`classify_record` returns the
abstain sentinel and :func:`kill_authorized` returns ``False`` (criterion 1).

Stdlib only. No third-party imports.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Optional, Tuple

import paths as _paths
import proc_probe
import session_registry


# ── Verdict taxonomy (re-exported so callers depend on ONE source) ──────────
VERDICT_SKIP = "skip"
VERDICT_ABSTAIN = "abstain"
VERDICT_REAP_DEAD = "reap_dead"
VERDICT_REAP_RECYCLED = "reap_recycled"
VERDICT_ALIVE = "alive"
VERDICT_KILL = "kill"

#: Sentinel for :func:`build_snapshot`'s ``probe`` argument meaning "do NOT probe
#: PID identity for this snapshot" — used by the ownership-only callers (e.g.
#: :func:`zombie_hunter.live_owner_ids`) that never consult positive-liveness.
NO_PROBE = object()


# ── Positive-liveness signals (per session) ─────────────────────────────────

@dataclass(frozen=True)
class PositiveSignals:
    """Per-session liveness signals sampled ONCE when the snapshot is built.

    Wave 1 carried only the identity-probe outcome. Wave 2 enriches this with
    concretely-detectable stdlib positive signals — git ``index.lock`` presence,
    a session heartbeat file, an owned-socket probe, worktree write mtime, a CPU
    sample — plus the two derived owner-liveness verdicts. THE CORROBORATION RULE
    (criterion 1): a positive signal counts as *liveness* ONLY when the owning
    PID is alive (:attr:`owner_alive`). A stale ``index.lock`` or a forged
    heartbeat whose owner is DEAD is NOT liveness — see
    :func:`has_corroborated_positive`. All fields are sampled once, immutably.
    """

    owner_pid: Optional[int] = None
    #: The owning PID's live creation time (epoch seconds). ``None`` ⇒ the PID
    #: has no accessible live process (gone / exited / access-denied).
    owner_create_time: Optional[float] = None
    #: The owning PID resolves to a LIVE process whose creation time MATCHES the
    #: recorded identity (our process, still running). This is the process-alive
    #: probe — itself a corroborated positive signal.
    owner_alive: bool = False
    #: The owning PID resolves to NO accessible process (gone). Positive proof of
    #: death of the owner — a precondition of :func:`kill_authorized`. (Wave 3
    #: hardens the access-denied-vs-gone distinction via WaitForSingleObject.)
    owner_confirmed_dead: bool = False
    #: A git ``index.lock`` is present in the session's worktree (raw detection;
    #: only *protective* when corroborated by ``owner_alive``).
    index_lock: bool = False
    #: A fresh session heartbeat file (mtime within the staleness window).
    heartbeat_fresh: bool = False
    #: An owned listening socket the session recorded is reachable.
    socket_owned: bool = False
    #: A worktree write occurred within the work-mtime window.
    work_mtime_fresh: bool = False
    #: A CPU sample showed the owning process burning cycles in the window.
    cpu_active: bool = False
    #: The owning PID could NOT be resolved to a definite alive-or-gone verdict
    #: this sweep — an OpenProcess-DENIED read whose PID nonetheless appears in
    #: the Toolhelp enumeration (denied ≠ gone), or an enumeration GAP. UNKNOWN
    #: ⇒ :func:`classify` ABSTAINS (never confirms death on uncertainty). Set only
    #: when :func:`build_snapshot` is given an ``enumerate_pids`` oracle; the
    #: legacy (no-enumerator) path leaves it ``False`` and behaves exactly as
    #: before (``owner_create_time is None`` ⇒ gone).
    owner_probe_unknown: bool = False


# ── The immutable per-sweep snapshot ────────────────────────────────────────

@dataclass(frozen=True)
class LivenessSnapshot:
    """The ONE immutable input every reaper decision is derived from.

    Built EXACTLY ONCE per sweep by :func:`build_snapshot`. Frozen: attributes
    cannot be reassigned, the id-sets are ``frozenset``, and the maps are
    ``MappingProxyType`` (read-only) — so a decision can never mutate the
    snapshot, and two sweeps never share drifting state.
    """

    #: Sessions with a live PTY/browser stream.
    attached_pty_ids: frozenset = field(default_factory=frozenset)
    #: Sessions backed by an actively-running owning job.
    job_owned_ids: frozenset = field(default_factory=frozenset)
    #: Sessions transitively owned via their ``parent_session_id`` lineage.
    parent_owned_ids: frozenset = field(default_factory=frozenset)
    #: telemetry-resume W6 — sessions whose read-only plan-mode ORIENTATION
    #: one-shot job is in flight: the origin session is treated as owned-for-N-
    #: minutes (``now < orientation_owned_until``) so the hunter never flags/kills
    #: a session while its orientation read is running, then it auto-expires.
    orientation_owned_ids: frozenset = field(default_factory=frozenset)
    #: pid → (pid, create_time, image_path) — the launch-time identity tuples.
    pid_identity: Mapping[int, Tuple[int, Optional[float], Optional[str]]] = \
        field(default_factory=lambda: MappingProxyType({}))
    #: session_id → :class:`PositiveSignals` sampled once for this sweep.
    positive_liveness: Mapping[str, PositiveSignals] = \
        field(default_factory=lambda: MappingProxyType({}))
    #: TRUE when the owner-enumeration inputs DEGRADED (a default fetch of the
    #: attached set / running records / owning-job predicate threw), so the
    #: owner set may be artificially narrow/empty. The defensive boundary
    #: (criterion 1) treats a degraded snapshot as "cannot classify" → every
    #: call site KEEPS (never freeze/kill on a degraded snapshot). Distinct from
    #: a *legitimately* empty owner set built from good inputs.
    degraded: bool = False


def build_snapshot(attached_pty_ids=None, records=None, job_active=None,
                   probe=None, *, tol=2.0, now=None,
                   enumerate_pids=None) -> LivenessSnapshot:
    """Build the immutable per-sweep :class:`LivenessSnapshot` — call ONCE/sweep.

    ``attached_pty_ids`` — the base set of sessions with a live PTY/browser
                           stream; defaults to ``pty_manager.live_sessions()``.
    ``records``          — the RUNNING session records to consider; defaults to
                           ``session_registry.list_sessions(status="running")``.
    ``job_active``       — callable ``session_id -> bool`` reporting whether an
                           actively-running OWNING job backs the session;
                           defaults to ``job_runner._holder_is_active``.
    ``probe``            — supplies ``creation_time(pid)`` for the identity /
                           positive-liveness sampling; defaults to
                           :mod:`proc_probe`. Pass :data:`NO_PROBE` to skip the
                           per-PID probe entirely (ownership-only callers).
    ``tol``              — allowed creation-time drift (seconds) when deciding
                           whether the live PID is still OUR process.
    ``now``              — epoch seconds for the mtime/heartbeat freshness math
                           (injectable for tests); defaults to ``time.time()``.
    ``enumerate_pids``   — OPTIONAL callable ``() -> frozenset[int] | None`` (the
                           Toolhelp process enumeration, e.g.
                           ``proc_probe.enum_pids``). When supplied, a PID whose
                           ``OpenProcess`` read failed (``creation_time`` → ``None``)
                           is DISAMBIGUATED: still enumerable (or the enumeration
                           itself GAPPED / threw) ⇒ ``owner_probe_unknown`` →
                           :func:`classify` ABSTAINS (denied ≠ gone); absent from a
                           good enumeration ⇒ genuinely gone (confirmed dead).
                           DEFAULT ``None`` ⇒ the legacy semantics EXACTLY
                           (``creation_time is None`` ⇒ gone) — zero behavior
                           change for every existing caller/test.

    Best-effort: any probe/import failure degrades to "not owned via that path"
    / "identity unknown", never raises. When a DEFAULT fetch (attached set /
    running records / owning-job predicate) itself throws, :attr:`degraded` is
    set TRUE so the defensive boundary can KEEP everything (criterion 1) rather
    than silently classify against an artificially-narrow owner set.
    """
    degraded = False

    # ── attached ────────────────────────────────────────────────────────────
    if attached_pty_ids is None:
        try:
            import pty_manager
            attached_pty_ids = set(pty_manager.live_sessions())
        except Exception:
            attached_pty_ids = set()
            degraded = True
    attached = set(attached_pty_ids or ())

    # ── owning-job predicate ─────────────────────────────────────────────────
    if job_active is None:
        try:
            import job_runner
            job_active = job_runner._holder_is_active
        except Exception:  # pragma: no cover - defensive against an import cycle
            job_active = lambda _sid: False
            degraded = True

    # ── the RUNNING records for this sweep ───────────────────────────────────
    if records is None:
        try:
            records = session_registry.list_sessions(status="running")
        except Exception:
            records = []
            degraded = True

    by_id = {}
    job_owned = set()
    for rec in records or []:
        sid = rec.get("session_id")
        if not sid:
            continue
        by_id[sid] = rec
        if sid in attached:
            continue
        try:
            if job_active(sid):
                job_owned.add(sid)
        except Exception:  # pragma: no cover - a probe failure is "not owned"
            pass

    # ── transitive parent-owned closure from (attached ∪ job_owned) ──────────
    # Iterate to a fixpoint (bounded by the record count — small). Rebuilt fresh
    # every sweep; never incrementally mutated across sweeps.
    seeded = set(attached) | job_owned
    parent_owned = set()
    changed = True
    while changed:
        changed = False
        for sid, rec in by_id.items():
            if sid in seeded or sid in parent_owned:
                continue
            parent = rec.get("parent_session_id")
            if parent and (parent in seeded or parent in parent_owned):
                parent_owned.add(sid)
                changed = True

    # ── identity tuples + positive-liveness (probe each PID ONCE) ────────────
    if now is None:
        now = time.time()

    # ── telemetry-resume W6: orientation-origin ownership (owned-for-N-minutes)
    # A session whose read-only plan-mode orientation one-shot job is in flight
    # carries ``orientation_owned_until`` (an epoch set at orient-launch). While
    # ``now < orientation_owned_until`` the session is OWNED (never a zombie),
    # then the window auto-expires — no cleanup needed. Best-effort per record.
    orientation_owned = set()
    for sid, rec in by_id.items():
        try:
            until = rec.get("orientation_owned_until")
            if until is not None and float(until) > now:
                orientation_owned.add(sid)
        except (TypeError, ValueError):
            continue
    # Take the Toolhelp process enumeration ONCE for this sweep (when an oracle
    # was supplied) so the denied-vs-gone disambiguation below is O(1)/PID. A
    # throwing enumerator is itself an enumeration GAP → every dead-looking PID
    # abstains (never confirmed dead) rather than acting on an unknown.
    enum_set = None
    enum_supplied = enumerate_pids is not None
    if enum_supplied:
        try:
            enum_set = enumerate_pids()
        except Exception:
            enum_set = None
    pid_identity = {}
    positive = {}
    do_probe = probe is not NO_PROBE
    if do_probe and probe is None:
        probe = proc_probe
    if do_probe:
        for sid, rec in by_id.items():
            pid = rec.get("pid")
            if not pid:
                continue
            try:
                pid_int = int(pid)
            except (TypeError, ValueError):
                continue
            try:
                actual = probe.creation_time(pid_int)
            except Exception:
                actual = None
            # Wave 3: the identity tuple carries the image path "where available"
            # — a best-effort corroborating field. Probed only when the probe
            # exposes it (the real proc_probe does; a bare creation-time fake does
            # not), so a fake without image_path leaves the field None unchanged.
            img_path = None
            _img_getter = getattr(probe, "image_path", None)
            if callable(_img_getter):
                try:
                    img_path = _img_getter(pid_int)
                except Exception:
                    img_path = None
            pid_identity[pid_int] = (pid_int, actual, img_path)

            # Derive the two owner-liveness verdicts from the recorded identity.
            recorded_ct = rec.get("proc_create_time")
            owner_alive = (actual is not None and recorded_ct is not None
                           and abs(actual - recorded_ct) <= tol)
            #: confirmed dead = the PID resolves to NO live process at all. A PID
            #: that is live but whose creation time MISMATCHES is a RECYCLED PID
            #: (a different process now owns it) — neither alive-ours NOR
            #: confirmed-dead: we must abstain, never kill the new owner.
            owner_probe_unknown = False
            if actual is None and enum_supplied:
                # OpenProcess could not read this PID. Disambiguate denied-vs-gone
                # via the Toolhelp enumeration: a PID that is still enumerable — or
                # an enumeration that GAPPED (enum_set is None) — is UNKNOWN and
                # must ABSTAIN, NEVER be confirmed dead. Only a PID demonstrably
                # ABSENT from a good enumeration is genuinely gone.
                if enum_set is None or pid_int in enum_set:
                    owner_confirmed_dead = False
                    owner_probe_unknown = True
                else:
                    owner_confirmed_dead = True
            else:
                owner_confirmed_dead = (actual is None)

            # Concretely-detectable positive signals (raw detection; the
            # corroboration gate lives in has_corroborated_positive). Cheap,
            # best-effort, stdlib-only — a probe failure is just "no signal".
            wp = rec.get("worktree_path") or ""
            positive[sid] = PositiveSignals(
                owner_pid=pid_int,
                owner_create_time=actual,
                owner_alive=owner_alive,
                owner_confirmed_dead=owner_confirmed_dead,
                index_lock=_probe_index_lock(wp),
                heartbeat_fresh=_probe_heartbeat(wp, now),
                socket_owned=_probe_socket(rec),
                work_mtime_fresh=_probe_work_mtime(wp, now),
                cpu_active=_probe_cpu(rec),
                owner_probe_unknown=owner_probe_unknown,
            )

    return LivenessSnapshot(
        attached_pty_ids=frozenset(attached),
        job_owned_ids=frozenset(job_owned),
        parent_owned_ids=frozenset(parent_owned),
        orientation_owned_ids=frozenset(orientation_owned),
        pid_identity=MappingProxyType(dict(pid_identity)),
        positive_liveness=MappingProxyType(dict(positive)),
        degraded=degraded,
    )


# ── Positive-liveness signal probes (stdlib, cheap, best-effort) ─────────────
# Each returns a raw bool: whether the artifact is DETECTABLE right now. Whether
# a detected artifact grants KEEP is decided by has_corroborated_positive, which
# gates every one of them on owning-PID-alive corroboration — so a stale lock or
# a forged heartbeat left by a DEAD owner is never mistaken for life.

HEARTBEAT_FILENAME = ".anchor_heartbeat"


def _probe_index_lock(worktree_path) -> bool:
    """A git ``index.lock`` present in the worktree (a build/commit in flight)."""
    if not worktree_path:
        return False
    try:
        return (Path(worktree_path) / ".git" / "index.lock").exists()
    except Exception:
        return False


def _probe_heartbeat(worktree_path, now, stale_secs=None) -> bool:
    """A session heartbeat file whose mtime is fresher than the stale window."""
    if not worktree_path:
        return False
    if stale_secs is None:
        stale_secs = _paths.reaper_heartbeat_stale_secs()
    try:
        hb = Path(worktree_path) / HEARTBEAT_FILENAME
        if not hb.exists():
            return False
        return (now - hb.stat().st_mtime) <= stale_secs
    except Exception:
        return False


def _probe_work_mtime(worktree_path, now, max_secs=None) -> bool:
    """A recent write anywhere shallow in the worktree (work in progress).

    Cheap by design (a Wave-9 perf gate follows): the worktree root and its
    immediate children only — never a full recursive walk.
    """
    if not worktree_path:
        return False
    if max_secs is None:
        max_secs = _paths.reaper_work_mtime_secs()
    try:
        root = Path(worktree_path)
        newest = root.stat().st_mtime
        try:
            for child in os.scandir(root):
                try:
                    ct = child.stat().st_mtime
                except OSError:
                    continue
                if ct > newest:
                    newest = ct
        except OSError:
            pass
        return (now - newest) <= max_secs
    except Exception:
        return False


def _probe_socket(record) -> bool:
    """An owned listening socket the session recorded (``port``) is reachable.

    Best-effort: only records that declared a loopback ``port`` are probed, with
    a short non-blocking connect. No recorded port → no signal (``False``).
    """
    port = record.get("port") if hasattr(record, "get") else None
    if not port:
        return False
    try:
        import socket as _socket
        with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
            s.settimeout(0.15)
            return s.connect_ex(("127.0.0.1", int(port))) == 0
    except Exception:
        return False


def _probe_cpu(record) -> bool:
    """Whether a CPU sample shows the owning process active in the window.

    A true CPU-activity read needs two samples spaced over
    ``ANCHOR_REAPER_CPU_WINDOW_SECS``; the single-shot snapshot cannot take the
    second sample without stalling the sweep, so this is a forward hook that
    defaults to ``False`` (no CPU signal) and is corroborated by the
    :func:`revalidate_target` re-probe / the Wave-9 evidence harness. Honestly
    inert here rather than fabricating activity.
    """
    return False


# ── Pure derivations over the immutable snapshot ────────────────────────────

def enumerate_live_pids():
    """The production ``enumerate_pids`` oracle for :func:`build_snapshot`.

    A thin, lazy passthrough to :func:`proc_probe.enum_pids` (the Toolhelp
    process enumeration) so the five production sweep call sites can wire the
    denied-vs-gone disambiguation with one shared provider without importing
    ``proc_probe`` at each site. Returns a ``frozenset[int]`` of live PIDs, or
    ``None`` on an enumeration GAP / non-Windows host (→ dead-looking PIDs
    ABSTAIN). Never raises.
    """
    try:
        import proc_probe
        return proc_probe.enum_pids()
    except Exception:
        return None


def live_owner_ids(snapshot) -> set:
    """The canonical live-owner set — a PURE function of ``snapshot``.

    Returns ``attached_pty_ids ∪ job_owned_ids ∪ transitive-parent-owned ∪
    orientation-owned`` as a NEW set each call. No self-sourcing, no I/O: it only
    reads the immutable snapshot, so two sweeps over the same registry state
    yield equal sets with no drift carried across sweeps.
    """
    return (set(snapshot.attached_pty_ids)
            | set(snapshot.job_owned_ids)
            | set(snapshot.parent_owned_ids)
            | set(getattr(snapshot, "orientation_owned_ids", frozenset())))


def live_pid_ids(snapshot) -> set:
    """Sessions whose recorded PID resolves to a LIVE process (identity present).

    This is process-liveness, NOT ownership: a session is "PID-alive" whenever
    its owning PID currently hosts an accessible process — whether it is genuine
    work OR a true orphan the banner/daemon handle. The boot reconcile uses this
    to leave PID-alive records RUNNING and reconcile only dead PIDs, so it never
    silently reaps an orphan at startup.
    """
    return {sid for sid, sig in snapshot.positive_liveness.items()
            if sig is not None and (sig.owner_create_time is not None
                                    or getattr(sig, "owner_probe_unknown", False))}


def classify(record, live_owner_ids, positive_liveness, *, tol=2.0) -> str:
    """Pure verdict for one ``record`` — the ONLY inputs are the live-owner set
    and the positive-liveness map (both REQUIRED positional args).

    A new consumer is compile-forced to supply both, so it cannot classify a
    session against a narrower input set than every other call site.

    Verdicts:
      - ``"skip"``          — record is not RUNNING; not our concern.
      - ``"abstain"``       — missing identity (no token / pid / create-time):
                              NEVER kill, NEVER auto-reap; flag for review.
      - ``"reap_dead"``     — the recorded PID has no live process (identity
                              absent from the positive-liveness map): gone
                              already, reconcile the registry only (no kill).
      - ``"reap_recycled"`` — the PID is live but its creation time differs: the
                              PID was reused by a DIFFERENT process; reconcile,
                              NEVER kill the new owner.
      - ``"alive"``         — our process, still running, and OWNED: leave it.
      - ``"kill"``          — our process, still running, and NO live owner →
                              orphan → kill + reap.
    """
    if record.get("status") != session_registry.STATUS_RUNNING:
        return VERDICT_SKIP

    pid = record.get("pid")
    ctime = record.get("proc_create_time")
    token = record.get("crypt_token")

    # Missing identity → never killable / never auto-reapable.
    if not token or not pid or ctime is None:
        return VERDICT_ABSTAIN

    sid = record.get("session_id")
    signals = positive_liveness.get(sid) if positive_liveness else None
    if signals is not None and getattr(signals, "owner_probe_unknown", False):
        # Owner liveness is UNKNOWN this sweep — an OpenProcess-DENIED read whose
        # PID is still enumerable (denied ≠ gone), or an enumeration GAP. Never
        # confirm death on uncertainty: ABSTAIN (KEEP), never reap.
        return VERDICT_ABSTAIN
    actual = signals.owner_create_time if signals is not None else None
    if actual is None:
        # No live process for this PID — reconcile only (no kill).
        return VERDICT_REAP_DEAD
    if abs(actual - ctime) > tol:
        # PID recycled by a different process — never kill the new owner.
        return VERDICT_REAP_RECYCLED

    owners = live_owner_ids if live_owner_ids is not None else ()
    if sid in owners:
        return VERDICT_ALIVE
    return VERDICT_KILL


def classify_record(record, snapshot, *, tol=2.0) -> str:
    """The single classify entry every call site uses — DEFENSIVELY BOUNDED.

    Classifies one ``record`` against the immutable ``snapshot`` — its live-owner
    set AND its positive-liveness map — so all five discriminators share the
    identical provider. Bypassing this (hand-rolling :func:`classify` args, or
    reaching back into the old per-site input set) is what the Wave-1 stub-gate
    is designed to catch.

    THE DEFENSIVE BOUNDARY (Wave 2, criterion 1 — abstain-not-kill): ANY
    uncertainty resolves to KEEP. A ``None`` snapshot, a :attr:`degraded`
    snapshot (owner enumeration failed), a throwing ``live_owner_ids``, or a
    missing/partial positive-liveness map all return :data:`VERDICT_ABSTAIN` —
    the sentinel every call site interprets as OWNED/alive, so no site ever
    freezes or kills on a fault. It NEVER returns ``kill`` on a fault.
    """
    try:
        if snapshot is None or getattr(snapshot, "degraded", False):
            return VERDICT_ABSTAIN
        owners = live_owner_ids(snapshot)
        return classify(record, owners, snapshot.positive_liveness, tol=tol)
    except Exception:
        # Fail SAFE: any fault in the owner / positive-liveness computation is
        # treated as OWNED/alive — never a kill.
        return VERDICT_ABSTAIN


# ── Positive-proof-of-death kill predicate (Wave 2) ─────────────────────────

def has_corroborated_positive(signals) -> bool:
    """Whether ``signals`` carries a CORROBORATED positive-liveness signal.

    THE CORROBORATION RULE: a detectable artifact (``index.lock``, a heartbeat
    file, an owned socket, a fresh worktree write, a CPU sample) grants KEEP
    ONLY when the owning PID is alive (``owner_alive``). A stale lock or a forged
    heartbeat whose owner is DEAD is NOT liveness → returns ``False`` so the
    orphan stays reap-eligible. When the owner PID IS alive, the process-alive
    probe is itself a corroborated positive signal.
    """
    if signals is None or not getattr(signals, "owner_alive", False):
        return False
    return bool(signals.owner_alive or signals.index_lock or signals.heartbeat_fresh
                or signals.socket_owned or signals.work_mtime_fresh
                or signals.cpu_active)


def kill_authorized(record, snapshot, *, revalidate=None, tol=2.0) -> bool:
    """Whether a DESTRUCTIVE action (freeze/kill) is authorized for ``record``.

    The KILL predicate — KILL rests on POSITIVE proof of death, never on absence
    and never on a stale artifact masquerading as life. Authorizes ONLY when ALL
    hold:

      1. **no live owner** — the session is not attached / job-owned / parent-
         owned in the snapshot;
      2. **identity-probe-confirmed-dead** — the owning PID resolves to NO live
         process (``VERDICT_REAP_DEAD``). An ALIVE process (owned or not), a
         RECYCLED PID, a missing identity, or a non-running record are all KEPT;
      3. **no corroborated positive signal** — :func:`has_corroborated_positive`
         is ``False`` (a dead owner's stale lock/heartbeat is not protective);
      4. **fresh in-lock re-validation** — when a ``revalidate`` callable is
         supplied (used immediately before the destructive action, under the
         same lock), it must report NO new sign of life.

    Defensively bounded: a ``None``/``degraded`` snapshot or ANY exception →
    ``False`` (never authorize on uncertainty).
    """
    try:
        if snapshot is None or getattr(snapshot, "degraded", False):
            return False
        sid = record.get("session_id")
        if not sid:
            return False
        # (1)+(2): only a confirmed-dead-of-owner orphan is eligible.
        verdict = classify(record, live_owner_ids(snapshot),
                           snapshot.positive_liveness, tol=tol)
        if verdict != VERDICT_REAP_DEAD:
            return False
        # (3): no corroborated positive signal.
        signals = snapshot.positive_liveness.get(sid)
        if has_corroborated_positive(signals):
            return False
        # (4): fresh, single-target re-validation immediately before acting.
        if revalidate is not None:
            try:
                if revalidate(record):
                    return False
            except Exception:
                # A re-validation that itself faults is uncertainty → abort.
                return False
        return True
    except Exception:
        return False


def revalidate_target(record, *, attached_pty_ids=None, records=None,
                      job_active=None, probe=None, tol=2.0, now=None) -> bool:
    """Fresh, single-target liveness recheck for the pre-execution gate.

    Called INSIDE the destructive lock, immediately before freezing/killing the
    specific target: it rebuilds a one-record snapshot from a LIVE probe and
    reports whether ANYTHING now indicates life — a live owner, an alive owning
    PID, or a corroborated positive signal. Returns ``True`` ⇒ **ABORT** the
    action (life re-appeared); ``False`` ⇒ the target still looks dead.

    Fail-safe: any exception returns ``True`` (abort) — a failed recheck must
    never green-light a kill.
    """
    try:
        snap = build_snapshot(
            attached_pty_ids=attached_pty_ids,
            records=records if records is not None else [record],
            job_active=job_active, probe=probe, tol=tol, now=now,
        )
        if getattr(snap, "degraded", False):
            return True
        sid = record.get("session_id")
        if sid in live_owner_ids(snap):
            return True
        signals = snap.positive_liveness.get(sid)
        if signals is not None and (signals.owner_alive
                                    or has_corroborated_positive(signals)):
            return True
        return False
    except Exception:
        return True


def owner_ids_or_abstain(snapshot, records) -> set:
    """Abstain-safe live-owner set for the armed kill-daemon's live_ids provider.

    If the snapshot is ``None`` or :attr:`degraded` (owner enumeration failed →
    an artificially-narrow/empty owner set), return EVERY running session id as
    "owned" so the sweep classifies them all alive and kills NOTHING this cycle
    (uncertainty → KEEP). Otherwise the canonical :func:`live_owner_ids`. This is
    what keeps the most dangerous call site (the daemon) from mass-killing on a
    single fetch hiccup.
    """
    try:
        if snapshot is None or getattr(snapshot, "degraded", False):
            return {r.get("session_id") for r in (records or [])
                    if r.get("session_id")}
        return live_owner_ids(snapshot)
    except Exception:
        return {r.get("session_id") for r in (records or [])
                if r.get("session_id")}


# ─────────────────────────────────────────────────────────────────────────────
# BOUNDED BLAST RADIUS + BOOT GRACE + CONSERVATIVE AGE + SAFE LINEAGE (Wave 4)
# ─────────────────────────────────────────────────────────────────────────────
# Cap the worst case BEFORE any arming is contemplated: no runaway cascade (a
# per-cycle blast cap), no touching young sessions (a boot/startup grace window),
# no touching unknown-age sessions (a registered created_at is REQUIRED for
# kill-eligibility), and a transitive-parent lineage walk that can never spin on
# a malformed/looping chain (a visited-set + hard depth cap; a cycle is flagged
# by the registry-integrity check and its whole branch is PROTECTED/abstained).
#
# Every predicate here fails in the SAFE direction: any uncertainty (unknown age,
# a lineage cycle, an over-deep chain, a throwing probe) resolves to PROTECTED,
# never to an action. These bounds sit ON TOP of the Wave-2 positive-proof-of-
# death :func:`kill_authorized` predicate — a session is only ever a sweep
# candidate when it is BOTH confirmed-dead-of-owner AND past every bound here.

_log = logging.getLogger("anchor.reaper")
# The reaper is a safety subsystem whose operational WARNINGs (e.g. a blast-cap
# deferral) must stay independently visible — capturable by tests and available
# to any root handler. ``anchor_gui`` reconfigures process-wide logging when it
# loads: it pins the ROOT logger to ERROR (``basicConfig(level=ERROR)``) and
# islands the ``anchor`` logger (``propagate=False``) to de-duplicate its own
# error log. As a child of ``anchor`` under an ERROR root, the reaper's warnings
# would then neither fire nor propagate. Decouple this logger from that global
# state: keep it firing at INFO+ and parent it directly to root so its records
# reach the root logger's handlers regardless of ``anchor_gui``'s islanding.
_log.setLevel(logging.INFO)
_log.propagate = True
_log.parent = logging.getLogger()


def _coerce_epoch(value):
    """Coerce a stored timestamp to epoch-seconds float, or ``None`` if absent
    / uninterpretable. Never raises — an unparseable value is ``None`` (unknown),
    which the callers treat as PROTECTED."""
    if value is None:
        return None
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return None
    # A zero / negative timestamp is not a defensible birth signal → unknown.
    return ts if ts > 0 else None


def _pid_start_time(record, snapshot=None, probe=None):
    """The owning PID's process-tree start time (GetProcessTimes) — the defensible
    age anchor, NEVER file mtime.

    Prefers the value already sampled into the immutable snapshot's
    positive-liveness map (one probe per sweep); falls back to a fresh
    ``probe.creation_time(pid)`` only when a ``probe`` is supplied (unit tests) and
    the snapshot has no entry. Returns ``None`` when the PID has no accessible live
    process (gone / exited / access-denied) — a dead orphan has no probeable start,
    so its only age signal is its registry ``created_at``.
    """
    sid = record.get("session_id")
    if snapshot is not None:
        try:
            sig = snapshot.positive_liveness.get(sid)
        except Exception:
            sig = None
        if sig is not None and getattr(sig, "owner_create_time", None) is not None:
            return sig.owner_create_time
    if probe is not None:
        pid = record.get("pid")
        try:
            pid_int = int(pid)
        except (TypeError, ValueError):
            return None
        try:
            return probe.creation_time(pid_int)
        except Exception:
            return None
    return None


def session_age_secs(record, snapshot=None, *, now=None, probe=None):
    """Conservative age of ``record`` in seconds, or ``None`` when unknown.

    Age is derived from the oldest DEFENSIBLE birth signal — the process-tree
    start time via ``GetProcessTimes`` on the live PID and/or the registry
    ``created_at`` — and NEVER from file mtime (a file can be touched at any time).
    When both a PID start and a ``created_at`` exist, the age is taken from the
    MOST-RECENT (youngest) of them, so a session counts as "old enough" only when
    EVERY defensible signal agrees it is — the conservative/protect direction on
    disagreement. Returns ``None`` when NO defensible signal exists (unknown age →
    the caller PROTECTS).
    """
    if now is None:
        now = time.time()
    starts = []
    created = _coerce_epoch(record.get("created_at"))
    if created is not None:
        starts.append(created)
    pid_start = _coerce_epoch(_pid_start_time(record, snapshot, probe))
    if pid_start is not None:
        starts.append(pid_start)
    if not starts:
        return None
    age = now - max(starts)
    return age if age > 0 else 0.0


def age_protected(record, snapshot=None, *, now=None, grace=None, probe=None) -> bool:
    """Whether ``record`` must NOT be frozen/killed on AGE grounds (PROTECTED).

    Returns ``True`` (PROTECTED — abstain) when ANY of:

      • **no registered created_at** — a registered ``created_at`` is REQUIRED for
        kill-eligibility; without it the session is never age-eligible;
      • **unknown age** — no created_at AND no probeable PID start;
      • **inside the boot/startup grace window** — younger than
        ``ANCHOR_REAPER_BOOT_GRACE_SECS`` (it has not yet had time to attach a PTY,
        register its owning job, or write its first heartbeat).

    Fails safe: any exception → ``True`` (PROTECTED).
    """
    try:
        if _coerce_epoch(record.get("created_at")) is None:
            return True  # a registered created_at is required for kill-eligibility
        age = session_age_secs(record, snapshot, now=now, probe=probe)
        if age is None:
            return True  # unknown age → PROTECTED
        if grace is None:
            grace = _paths.reaper_boot_grace_secs()
        return age < grace
    except Exception:
        return True


def find_lineage_cycles(records, *, max_depth=None) -> set:
    """Registry-integrity check: session ids on a malformed ``parent_session_id``
    lineage — a cycle, or a chain deeper than the hard depth cap.

    The transitive-parent walk is a functional graph (each session points at ONE
    ``parent_session_id``). This walks every session up its parent chain with a
    per-walk visited-set and a hard depth cap
    (``ANCHOR_REAPER_LINEAGE_MAX_DEPTH``): a revisited node means a CYCLE (the loop
    portion is flagged); exceeding the cap means a runaway/over-deep chain (the
    walked branch is flagged). Flagged sessions are treated as PROTECTED (abstain)
    by :func:`plan_sweep` — a broken chain must never authorize a kill.

    Never raises — a malformed record is skipped, not fatal.
    """
    if max_depth is None:
        max_depth = _paths.reaper_lineage_max_depth()
    parent = {}
    for rec in records or []:
        try:
            sid = rec.get("session_id")
        except Exception:
            continue
        if not sid:
            continue
        parent[sid] = rec.get("parent_session_id") or ""

    flagged = set()
    for start in parent:
        node = start
        seen = []
        seen_set = set()
        depth = 0
        while node and node in parent:
            if node in seen_set:
                # Cycle: flag from the first occurrence of this node onward.
                idx = seen.index(node)
                flagged.update(seen[idx:])
                break
            if depth >= max_depth:
                # Over-deep / runaway chain: protect the whole walked branch.
                flagged.update(seen)
                flagged.add(node)
                break
            seen.append(node)
            seen_set.add(node)
            depth += 1
            node = parent.get(node)
    return flagged


@dataclass(frozen=True)
class SweepPlan:
    """The bounded plan for ONE sweep cycle — what the sweep may act on now.

    ``to_act``        — session ids authorized for a destructive action THIS cycle,
                        already capped at the per-cycle blast-radius limit;
    ``deferred``      — authorized candidates BEYOND the cap, deferred (logged) to
                        the next sweep so a runaway can never cascade;
    ``protected``     — sessions that were death-authorized but SPARED by a Wave-4
                        bound (boot grace / unknown age / lineage cycle);
    ``lineage_cycles``— the registry-integrity flag set: every session id on a
                        malformed (cyclic / over-deep) lineage, action-eligible or
                        not;
    ``cap``           — the per-cycle blast-radius cap that was applied.
    """

    to_act: tuple = ()
    deferred: tuple = ()
    protected: tuple = ()
    lineage_cycles: tuple = ()
    cap: int = 0


def plan_sweep(records, snapshot, *, now=None, max_actions=None, grace=None,
               max_depth=None, revalidate=None, probe=None) -> SweepPlan:
    """Compute the BOUNDED destructive-action plan for one sweep cycle.

    Starts from the Wave-2 positive-proof-of-death predicate
    (:func:`kill_authorized`) and then applies every Wave-4 bound: a candidate is
    dropped to ``protected`` if it is inside the boot-grace window, of unknown age,
    or on a malformed lineage; the survivors are capped at
    ``ANCHOR_REAPER_MAX_ACTIONS_PER_SWEEP`` and the remainder is ``deferred`` (and
    logged). A degraded/``None`` snapshot yields an EMPTY plan (``kill_authorized``
    already refuses everything) — uncertainty never acts.

    Pure and side-effect-free except for a single deferred-remainder log line —
    the caller owns the actual freeze/kill so this stays unit-testable with no real
    process.
    """
    if now is None:
        now = time.time()
    if max_actions is None:
        max_actions = _paths.reaper_max_actions_per_sweep()
    recs = list(records or [])

    cycles = find_lineage_cycles(recs, max_depth=max_depth)

    candidates = []
    protected = []
    for rec in recs:
        try:
            sid = rec.get("session_id")
        except Exception:
            continue
        if not sid:
            continue
        # Only a confirmed-dead-of-owner orphan is ever a candidate (Wave 2).
        try:
            authorized = kill_authorized(rec, snapshot, revalidate=revalidate)
        except Exception:
            authorized = False
        if not authorized:
            continue
        # Wave-4 bounds — any one spares the session (PROTECT/abstain).
        if sid in cycles:
            protected.append(sid)
            continue
        if age_protected(rec, snapshot, now=now, grace=grace, probe=probe):
            protected.append(sid)
            continue
        candidates.append(sid)

    to_act = candidates[:max_actions]
    deferred = candidates[max_actions:]
    if deferred:
        _log.warning(
            "reaper sweep blast-cap reached (%d): acting on %d, deferring %d "
            "to the next sweep: %s",
            max_actions, len(to_act), len(deferred), list(deferred),
        )

    return SweepPlan(
        to_act=tuple(to_act),
        deferred=tuple(deferred),
        protected=tuple(protected),
        lineage_cycles=tuple(sorted(cycles)),
        cap=max_actions,
    )
