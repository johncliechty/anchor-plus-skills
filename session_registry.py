#!/usr/bin/env python3
"""Anchor managed-terminal session registry — durable, id-keyed (stdlib only).

v3 "Mission Control" (MASTER-PLAN §D / §I, Implementation-Plan Wave 2). A
DURABLE registry of managed terminal sessions that **survives a server restart**:
it is persisted as JSON under the ``.anchor/`` data dir (resolved via
``paths.data_dir()`` — NEVER hard-coded), so on reconnect the dashboard can
reflect true live state.

A session record models::

    {session_id, project_id, lane, backend ("claude"|"gemini"|"grok"),
     worktree_path, branch, status, created_at, label,
     seeded, seed_text}

``seeded`` / ``seed_text`` (v4 Wave 1) record whether the session's one-time
lane skill-seed turn was already written, so the seed is **never re-sent** on a
subsequent attach/input/read.

Persistence MIRRORS ``rnd_registry.py``:

- best-effort :func:`load_sessions` (a corrupt/missing store → empty dict,
  never crash);
- :func:`_save_sessions` runs under ``paths.WRITE_LOCK`` with an **atomic write**
  (write a tmp file, then ``os.replace`` — the durability discipline) so a
  concurrent ``ThreadingHTTPServer`` writer or a crash mid-write cannot leave a
  half-written store;
- entries are normalized via :func:`_normalize` and keyed by ``session_id``.

Stdlib only. No third-party imports.
"""

import json
import logging
import os
import time
import uuid
from pathlib import Path

import paths as _paths

_log = logging.getLogger("anchor.session_registry")


def _log_rejected_transition(session_id, from_status, to_status) -> None:
    """Audit a rejected status transition (Wave 5 terminal-lock guard)."""
    _log.info(
        "session_registry: rejected terminal transition %s: %s -> %s "
        "(kept %s — a terminal-locked state is never resurrected)",
        session_id, from_status, to_status, from_status)

# Sessions JSON filename, stored under ``.anchor/`` at the data-dir root.
SESSIONS_NAME = "sessions.json"
ANCHOR_DIRNAME = ".anchor"


# ── Status constants (locked color mapping; Wave 4 maps these → colors) ──────
#
# The locked status→color mapping (MASTER-PLAN §E / §I), encoded here WITHOUT
# building any UI. Wave 4's window-manager maps these strings to the colors:
#
#   STATUS_RUNNING          → GREEN  (working / a live PTY producing output)
#   STATUS_NEEDS_ATTENTION  → AMBER  (the session is waiting on the user)
#   STATUS_DONE             → AMBER  (finished cleanly; awaiting the user's review)
#   STATUS_FAILED           → RED    (the process failed / errored out)
#   STATUS_IDLE             → GREY   (registered but no live process — e.g. after
#                                     a restart, before reattach, or reaped)
#
# Both amber states (needs-you and done) share the amber bucket per the locked
# mapping "amber = needs-you-or-done".
STATUS_RUNNING = "running"
STATUS_NEEDS_ATTENTION = "needs-attention"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_IDLE = "idle"
#: A run that was actively cancelled (tree-killed) in flight — a finished,
#: non-running terminal state. Mirrors ``job_runner.STATUS_CANCELLED`` so the
#: Gandalf active-cancel path (Wave 1) can stamp the session honestly instead of
#: having ``_normalize`` coerce the unknown status to ``idle``.
STATUS_CANCELLED = "cancelled"

# ── zombie-hunter safe-to-arm, Wave 5: split the overloaded STATUS_IDLE ───────
#
# The historical ``STATUS_IDLE`` meant BOTH "parked warm — a graceful "×" close,
# resumable, keeps its worktree" AND "reaped orphan — reconciled dead, worktree
# gone". Those two meanings drive OPPOSITE worktree-retention decisions, so the
# reaper cannot trust a bare ``idle`` to decide whether a worktree may be
# removed. Wave 5 disambiguates them into two EXPLICIT states:
#
#   STATUS_PARKED_WARM    → non-running, RESUMABLE, KEEPS its worktree (grey).
#   STATUS_REAPED_ORPHAN  → non-running, reconciled dead, worktree NOT retained.
#
# Legacy ``STATUS_IDLE`` records are conservatively read as PARKED_WARM
# (over-protect only — an idle record kept its worktree, so warm-park is the safe
# reading) and are migrated forward by :func:`migrate_idle_to_parked_warm`.
STATUS_PARKED_WARM = "parked-warm"
STATUS_REAPED_ORPHAN = "reaped-orphan"

#: Every recognized status.
VALID_STATUSES = {
    STATUS_RUNNING,
    STATUS_NEEDS_ATTENTION,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_IDLE,
    STATUS_CANCELLED,
    STATUS_PARKED_WARM,
    STATUS_REAPED_ORPHAN,
}

#: Terminal statuses — a session in one of these has no live process and is
#: never "running". (``idle`` is non-running too, but it is the parked/recovered
#: state rather than a finished one.)
TERMINAL_STATUSES = frozenset((STATUS_DONE, STATUS_FAILED))

# ── Wave 5: state-transition table (STATUS_CANCELLED strictly terminal) ───────
#
# A terminal-LOCKED status is one no transition can ever leave: a CANCELLED run
# is never re-adopted / reconciled-to-running / resurrected, and a REAPED_ORPHAN
# is gone. :func:`can_transition` is the single authority the mutating CRUD
# entrypoints consult so a status change OUT of a locked state is REJECTED
# (the locked status is kept, the record is never resurrected).
TERMINAL_LOCKED_STATUSES = frozenset((STATUS_CANCELLED, STATUS_REAPED_ORPHAN))

#: Non-running statuses whose managed worktree is RETAINED (resumable warm).
#: Legacy ``STATUS_IDLE`` folds in here — the conservative over-protect reading.
WORKTREE_RETAINING_STATUSES = frozenset((STATUS_PARKED_WARM, STATUS_IDLE))

#: Non-running statuses whose managed worktree is explicitly NOT retained.
WORKTREE_DROPPING_STATUSES = frozenset((STATUS_REAPED_ORPHAN, STATUS_CANCELLED))

#: Live / finished statuses that are NOT "parked warm" (so :func:`is_parked_warm`
#: reports False — a live session is kept by the active-id check, a finished one
#: is handled by its own teardown). Enumerated so an UNRECOGNIZED status is the
#: only thing left to the fail-SAFE branch.
_NON_PARKED_KNOWN_STATUSES = frozenset(
    (STATUS_RUNNING, STATUS_NEEDS_ATTENTION, STATUS_DONE, STATUS_FAILED))


def can_transition(from_status, to_status) -> bool:
    """Is a status change ``from_status`` → ``to_status`` permitted? (Wave 5.)

    The state-transition table is intentionally minimal: it locks ONLY the
    terminal states. A record already in a :data:`TERMINAL_LOCKED_STATUSES`
    status (``cancelled`` / ``reaped-orphan``) may NEVER transition to a
    different status — the sole permitted "transition" is the identity (staying
    put). Every other transition stays permissive so the non-terminal lifecycle
    is unchanged. This is the single guard that makes ``STATUS_CANCELLED``
    strictly terminal (never re-adopted, never reconciled to running).
    """
    if from_status == to_status:
        return True
    if from_status in TERMINAL_LOCKED_STATUSES:
        return False
    return True


def is_parked_warm(record_or_status) -> bool:
    """Does this record/status mean "parked WARM — keep the worktree"? (Wave 5.)

    Retention is keyed on the EXPLICIT state field, not the overloaded ``idle``:

    - ``STATUS_PARKED_WARM`` / legacy ``STATUS_IDLE`` → **True** (keep; resumable).
    - ``STATUS_REAPED_ORPHAN`` / ``STATUS_CANCELLED`` → **False** (no worktree).
    - a live / finished status (running/needs-attention/done/failed) → **False**
      (a live session is retained by the active-id check; a finished one by its
      own teardown — neither is "parked warm").
    - anything else (an ambiguous / UNRECOGNIZED status) → fail **SAFE** to
      **True** (parked/keep) so an unknown state is NEVER reaped.

    Accepts either a record dict or a bare status string.
    """
    status = (record_or_status.get("status")
              if isinstance(record_or_status, dict) else record_or_status)
    if status in WORKTREE_DROPPING_STATUSES:
        return False
    if status in WORKTREE_RETAINING_STATUSES:
        return True
    if status in _NON_PARKED_KNOWN_STATUSES:
        return False
    # Unknown / ambiguous → fail SAFE (keep, never reap).
    return True

#: Recognized backends (interactive terminal peers).
BACKEND_CLAUDE = "claude"
BACKEND_GEMINI = "gemini"
BACKEND_GROK = "grok"
BACKEND_CHATGPT = "chatgpt"
VALID_BACKENDS = {BACKEND_CLAUDE, BACKEND_GEMINI, BACKEND_GROK, BACKEND_CHATGPT}


# ── Persistence ─────────────────────────────────────────────────────────────

def anchor_dir() -> Path:
    """Absolute path to the ``.anchor/`` dir under the resolved data dir."""
    return _paths.data_dir() / ANCHOR_DIRNAME


def sessions_path() -> Path:
    """Absolute path to the sessions JSON file (``.anchor/sessions.json``)."""
    return anchor_dir() / SESSIONS_NAME


def _new_id() -> str:
    """Generate a fresh, collision-resistant session id (stdlib uuid4 hex)."""
    return uuid.uuid4().hex


#: Bounded retry for the READ side — the symmetric counterpart of the write-side
#: ``_atomic_replace`` retry. While a concurrent writer is mid ``os.replace`` over
#: the store, this reader's ``read_text`` open can be transiently DENIED by
#: Windows with ``PermissionError`` (a sharing violation, NOT a real fault). The
#: writer's rename completes within microseconds, so a few short backed-off
#: retries let the reader see the complete NEW file. Without this, a single
#: transient would make ``load_sessions`` return ``{}`` — dropping the ENTIRE
#: registry for that read (a spurious "no sessions"), which under load surfaces
#: as a session momentarily vanishing from ``list_sessions``. POSIX never hits
#: the window — the first read succeeds and the loop is a no-op.
_READ_RETRIES = 40
_READ_BACKOFF_S = 0.005


def load_sessions() -> dict:
    """Load the session registry as a dict ``{session_id: record}``.

    Best-effort: returns an empty dict if the store does not exist or is
    unreadable/corrupt (a corrupt registry must never crash the dashboard). The
    JSON on disk is a list of records; this returns them keyed by ``session_id``
    for O(1) lookup. A keyed-dict form on disk is also tolerated.

    A transient ``OSError`` (the Windows sharing-violation race with a concurrent
    atomic write) is RETRIED briefly (see ``_READ_RETRIES``) rather than swallowed
    — swallowing it would drop the whole registry for that read. A genuine JSON
    corruption is NOT retried: atomic writes never yield a half-written file, so a
    decode error is a real fault, and ``{}`` is the honest best-effort fallback.
    """
    p = sessions_path()
    if not p.exists():
        return {}
    raw = None
    for attempt in range(_READ_RETRIES):
        try:
            text = p.read_text(encoding="utf-8")
        except FileNotFoundError:
            # Raced with a rename where the target briefly did not resolve — the
            # NEW file is landing; a retry sees it. Exhausted budget → {}.
            if attempt == _READ_RETRIES - 1:
                return {}
            time.sleep(_READ_BACKOFF_S)
            continue
        except OSError:
            # Transient Windows sharing violation while the writer replaces the
            # store — back off and retry so we read the complete file, not {}.
            if attempt == _READ_RETRIES - 1:
                return {}
            time.sleep(_READ_BACKOFF_S)
            continue
        try:
            raw = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return {}
        break
    if raw is None:
        return {}
    out = {}
    if isinstance(raw, list):
        for e in raw:
            if isinstance(e, dict) and e.get("session_id"):
                out[e["session_id"]] = _normalize(e)
    elif isinstance(raw, dict):
        for k, e in raw.items():
            if isinstance(e, dict):
                e = dict(e)
                e.setdefault("session_id", k)
                if e.get("session_id"):
                    out[e["session_id"]] = _normalize(e)
    return out


def _coerce_float_or_none(v):
    """Coerce a possibly-string/None epoch value to ``float`` or ``None``."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _normalize(record: dict) -> dict:
    """Coerce a record to the canonical session shape.

    Canonical fields: ``session_id, project_id, lane, backend, worktree_path,
    branch, status, created_at, label``. Unknown statuses fall back to
    ``STATUS_IDLE``; unknown backends are kept verbatim (the registry should not
    silently rewrite a backend it doesn't recognize, but the default is claude).
    """
    status = record.get("status", STATUS_IDLE)
    if status not in VALID_STATUSES:
        status = STATUS_IDLE
    backend = record.get("backend") or BACKEND_CLAUDE
    wp = record.get("worktree_path", "")
    try:
        worktree_path = str(Path(wp)) if wp else ""
    except (TypeError, ValueError):
        worktree_path = str(wp)
    created = record.get("created_at")
    try:
        created_at = float(created) if created is not None else None
    except (TypeError, ValueError):
        created_at = None
    sid = record.get("session_id")
    # v6 Wave 2: durable session lineage. ``parent_session_id`` is the upstream
    # session this one was advanced from ("" for a chain root); ``chain_id``
    # groups research→plan→build into one chain. A record with neither field
    # (every pre-v6 record) normalizes to parent="" and a SINGLETON chain whose
    # id is its own session_id — so back-compat holds and existing sessions are
    # already valid one-member chains.
    parent_session_id = record.get("parent_session_id", "") or ""
    chain_id = record.get("chain_id") or sid or ""
    # ── v12 Wave 1: effort stage fields (all back-compat) ──────────────────
    # An effort is ONE session carrying a stage. These fields let a record
    # carry the effort's stage + the v12 discriminator without breaking ANY
    # pre-v12 record (an old record with none of these normalizes with no
    # crash and ``effort_managed==False``).
    lane = record.get("lane", "") or ""
    # ``kind``: trio (the R→P→B lanes) / grass-dev (the grass lane) / general
    # (everything else). Derived from ``lane`` when absent on the record.
    kind = record.get("kind") or ""
    if not kind:
        if lane in ("research", "plan", "planning", "build"):
            kind = "trio"
        elif lane == "grass":
            kind = "grass-dev"
        else:
            kind = "general"
    # ``current_stage``: ""|research|plan|build — the effort's active stage.
    # Derived from ``lane`` when absent (planning → plan; "" for non-trio).
    current_stage = record.get("current_stage")
    if not current_stage:  # re-derive on None OR "" (a persisted trio record may carry "")
        if kind == "trio":
            if lane == "research":
                current_stage = "research"
            elif lane in ("plan", "planning"):
                current_stage = "plan"
            elif lane == "build":
                current_stage = "build"
            else:
                current_stage = ""
        else:
            current_stage = ""
    current_stage = current_stage or ""
    # ``stage_history``: append-only list of per-stage entries. Default [].
    sh = record.get("stage_history")
    # deep-copy each entry dict so a normalized record never aliases the caller's
    # stage entries (W4/W5 mutate entries in place — aliasing would corrupt the source).
    stage_history = [dict(e) if isinstance(e, dict) else e for e in sh] if isinstance(sh, list) else []
    # ``seeded_stages``: audit list of stages whose skill seed was written.
    ss = record.get("seeded_stages")
    seeded_stages = list(ss) if isinstance(ss, list) else []
    # ``effort_id``: the effort's stable id (the root session_id). Defaults to
    # the record's OWN session_id when absent.
    effort_id = record.get("effort_id") or sid or ""
    # ``effort_managed``: the v12 discriminator. Set True ONLY by the v12
    # entrypoints; legacy records (incl. the v6/v8/v10/v11 healthcheck walks)
    # normalize to False.
    effort_managed = bool(record.get("effort_managed", False))
    # ── zombie-hunter v2: process-identity fields (all back-compat) ─────────
    # The sweeper records the spawned PID + that PID's creation time + a
    # per-session crypt token at spawn, so a later sweep can prove a still-live
    # PID is OUR process (creation-time match) and not a recycled PID. Every
    # pre-existing record (none of these keys) normalizes to None/None/"" with
    # no crash — NEVER killable (the sweeper abstains on a missing identity).
    pid_raw = record.get("pid")
    try:
        pid = int(pid_raw) if pid_raw is not None and pid_raw != "" else None
    except (TypeError, ValueError):
        pid = None
    pct = record.get("proc_create_time")
    try:
        proc_create_time = float(pct) if pct is not None else None
    except (TypeError, ValueError):
        proc_create_time = None
    crypt_token = record.get("crypt_token", "") or ""
    # ── Honest Telemetry W2: terminal cost-finalization latch ───────────────
    # ``cost_final`` is the compare-and-set flag that makes finalize-on-every-
    # end-path idempotent: exactly one of the racing end paths (kill / close /
    # reconcile-dead) sets it (via :func:`finalize_cost_once`) and writes the
    # session's single RUN cost record. Back-compat: every pre-feature record
    # (no key) normalizes to ``False`` / ``None``.
    cost_final = bool(record.get("cost_final", False))
    cfa = record.get("cost_final_at")
    try:
        cost_final_at = float(cfa) if cfa is not None else None
    except (TypeError, ValueError):
        cost_final_at = None
    # ── Honest Telemetry W4: engine-session UUID capture + usage state ───────
    # ``engine_session_uuid`` is the Claude/engine session UUID captured AT LAUNCH
    # (``claude --session-id <uuid>`` pins the sidecar filename — never mtime-
    # guessed), the deterministic correlation the W4 usage-capture pipeline reads
    # the per-message sidecar by. ``engine_session_uuids`` is the append-only
    # history of EVERY engine UUID this managed session touched (launch + each
    # engine switch produces a distinct sidecar segment); finalize sums over all
    # of them, counted once. ``usage_state``/``usage_reason`` are the terminal
    # capture verdict stamped at finalize (measured / capture-failed / unmeasured
    # with a reason enum). Every pre-feature record (no keys) normalizes to
    # ""/[]/"" — honestly uncorrelated, never a guessed cost.
    engine_session_uuid = record.get("engine_session_uuid", "") or ""
    raw_euuids = record.get("engine_session_uuids")
    engine_session_uuids = []
    if isinstance(raw_euuids, (list, tuple)):
        _seen_eu = set()
        for u in raw_euuids:
            if u is None:
                continue
            us = str(u)
            if not us or us in _seen_eu:
                continue
            _seen_eu.add(us)
            engine_session_uuids.append(us)
    # Keep the two consistent: a bare ``engine_session_uuid`` seeds the list.
    if engine_session_uuid and engine_session_uuid not in engine_session_uuids:
        engine_session_uuids.insert(0, engine_session_uuid)
    usage_state = record.get("usage_state", "") or ""
    usage_reason = record.get("usage_reason", "") or ""
    # Honest Telemetry W5 (RULED Option C): a durable marker that this session
    # touched a Gemini/agy segment whose usage Anchor cannot capture. Set by
    # ``terminal_session.switch_engine`` whenever it switches TO an engine whose
    # segment is not UUID-captured, so a claude→gemini→claude round-trip (which
    # ends back on the claude backend) is STILL honestly flagged as mixed and the
    # rollup renders 'partial (gemini segment unmeasured)' instead of a
    # complete-looking Claude-only number. Back-compat: absent → False.
    usage_gemini_segment = bool(record.get("usage_gemini_segment", False))
    # Anchor Doctor P0: durable reuse identity. Old/unrelated sessions
    # normalize to empty strings and therefore cannot accidentally match a
    # requested Doctor mode/posture.
    doctor_mode = str(record.get("doctor_mode", "") or "")
    doctor_posture = str(record.get("doctor_posture", "") or "")
    # ── zombie-hunter safe-to-arm, Wave 6: owned-job claim set ──────────────
    # ``owned_job_ids`` is this session's explicit claim over ``job_runner`` job
    # ids — the reference-counted ownership the teardown path (``kill`` /
    # ``delete_session``) walks to reap every job the session owns via a targeted
    # per-``job_id`` cancel (never a full ``list_records`` scan). A job handed off
    # to a live successor stays claimed by that successor, so the reference count
    # keeps it alive across the predecessor's kill. Back-compat: every pre-Wave-6
    # record (no key) normalizes to ``[]``. Sanitized to a de-duped list of
    # non-empty id strings, order preserved.
    raw_jobs = record.get("owned_job_ids")
    owned_job_ids = []
    if isinstance(raw_jobs, (list, tuple)):
        _seen_jobs = set()
        for j in raw_jobs:
            if j is None:
                continue
            js = str(j)
            if not js or js in _seen_jobs:
                continue
            _seen_jobs.add(js)
            owned_job_ids.append(js)
    return {
        "session_id": sid,
        "project_id": record.get("project_id", ""),
        "lane": record.get("lane", ""),
        "backend": backend,
        "worktree_path": worktree_path,
        "branch": record.get("branch", ""),
        "status": status,
        "created_at": created_at,
        "label": record.get("label", ""),
        # v4 Wave 1: one-time lane skill-seed bookkeeping. ``seeded`` is the guard
        # that keeps the seed turn from ever being re-sent; ``seed_text`` is the
        # exact text written (for inspection / tests). Default False / "".
        "seeded": bool(record.get("seeded", False)),
        "seed_text": record.get("seed_text", "") or "",
        # v6 Wave 2: durable lineage (see above).
        "parent_session_id": parent_session_id,
        "chain_id": chain_id,
        # v10 Wave 1: paste-NOT-submit handoff. ``pending_paste`` is the task
        # prompt that is held UNSENT in the PTY input (no trailing newline)
        # until the user presses Enter; it is delivered exactly ONCE, after the
        # greet, by :func:`terminal_session._flush_pending_paste`, which then
        # sets ``paste_flushed=True`` and clears ``pending_paste``. Both fields
        # back-compat to ""/False on every pre-v10 record. SAFE to include in
        # board projections (no worktree_path/branch leak).
        "pending_paste": record.get("pending_paste", "") or "",
        "paste_flushed": bool(record.get("paste_flushed", False)),
        # v12 Wave 1: effort stage fields (see derivation above). All
        # back-compat; an old record normalizes with no crash and
        # ``effort_managed==False``. The board routes by ``current_stage``/
        # ``kind`` only (``lane`` flips with the stage).
        "kind": kind,
        "current_stage": current_stage,
        "stage_history": stage_history,
        "seeded_stages": seeded_stages,
        "effort_id": effort_id,
        "effort_managed": effort_managed,
        # v10 Wave 4: grass→project lineage (D8). ``grass_origin`` is the
        # originating grass idea id (``idea-…``) stamped on the chain when an idea
        # is exported/promoted to the project level, so every downstream project
        # plan/build session can trace back to that idea. Empty for any non-grass
        # session (back-compat default ""). It is just an idea id — SAFE to carry
        # in the board / chain projections (NEVER worktree_path/branch).
        "grass_origin": record.get("grass_origin", "") or "",
        # zombie-hunter v2: process-identity fields (see derivation above).
        "pid": pid,
        "proc_create_time": proc_create_time,
        "crypt_token": crypt_token,
        # zombie-hunter safe-to-arm, Wave 6: reference-counted owned-job claims.
        "owned_job_ids": owned_job_ids,
        # Honest Telemetry W2: terminal cost-finalization latch (see above).
        "cost_final": cost_final,
        "cost_final_at": cost_final_at,
        # Honest Telemetry W4: engine-session UUID capture + usage state (above).
        "engine_session_uuid": engine_session_uuid,
        "engine_session_uuids": engine_session_uuids,
        "usage_state": usage_state,
        "usage_reason": usage_reason,
        "usage_gemini_segment": usage_gemini_segment,
        "doctor_mode": doctor_mode,
        "doctor_posture": doctor_posture,
        # ── telemetry-resume W6: eviction + paste-fallback + orientation ─────
        # ``evicted``/``evicted_at``: the bounded oldest-first parked-worktree
        # eviction reclaims ONLY the worktree; the record stays parked-warm with
        # ``worktree_path=""`` and this durable marker, so the tile renders
        # evicted-parked and its Layer-2 escalation opens a NEW seeded session
        # (never a reattach claim). Everything else — record, chain, summary,
        # finalized cost — survives (the session stays MEASURED). Back-compat:
        # absent → False/None.
        "evicted": bool(record.get("evicted", False)),
        "evicted_at": _coerce_float_or_none(record.get("evicted_at")),
        # ``pending_paste_since``: when a paste was recorded UNSENT, so the
        # greet-gate has a bounded fallback flush (a paraphrased/omitted greet no
        # longer leaves the paste pending forever). Still paste-NOT-submit.
        "pending_paste_since": _coerce_float_or_none(
            record.get("pending_paste_since")),
        # ``orientation_owned_until``/``orientation_job_id``: a read-only
        # plan-mode orientation one-shot job (the Phase-0 fork) marks its origin
        # session owned-for-N-minutes so the zombie-hunter live-owner computation
        # never flags/kills a session while its orientation read is in flight.
        # Absent → None/"" (never owned by orientation).
        "orientation_owned_until": _coerce_float_or_none(
            record.get("orientation_owned_until")),
        "orientation_job_id": record.get("orientation_job_id", "") or "",
    }


#: Bounded retry for the atomic ``os.replace`` on Windows. A concurrent
#: read-only sweep (``load_sessions`` → ``read_text``) momentarily holds the
#: target file open; Windows then denies the rename with ``PermissionError(13,
#: 'Access is denied')`` (a transient sharing violation, NOT a real permission
#: fault). The reader's handle is released within microseconds, so a few short
#: backed-off retries turn the race into a correct, atomic write instead of a
#: spurious crash. POSIX ``os.replace`` never hits this — the loop is a no-op
#: there (first attempt succeeds).
_REPLACE_RETRIES = 40
_REPLACE_BACKOFF_S = 0.005


def _atomic_replace(tmp: str, target: str) -> None:
    """``os.replace`` with a bounded retry over the transient Windows sharing
    violation raised while a concurrent reader has ``target`` open. Re-raises
    the last error if the window never clears within the retry budget."""
    for attempt in range(_REPLACE_RETRIES):
        try:
            os.replace(tmp, target)
            return
        except PermissionError:
            if attempt == _REPLACE_RETRIES - 1:
                raise
            time.sleep(_REPLACE_BACKOFF_S)


def _write_sessions_locked(reg: dict) -> None:
    """The atomic write itself — the caller MUST already hold ``paths.WRITE_LOCK``.

    Writes to a temp file in the same directory then ``os.replace`` over the
    target so a crash mid-write can never leave a truncated/corrupt store
    (durability discipline). Ensures the ``.anchor/`` dir exists first.

    The replace goes through :func:`_atomic_replace` so a concurrent read-only
    sweep holding the target open (the Windows sharing-violation race) is
    tolerated with a bounded retry rather than surfacing a spurious
    ``PermissionError``.
    """
    d = anchor_dir()
    d.mkdir(parents=True, exist_ok=True)
    items = [reg[k] for k in reg]
    target = sessions_path()
    tmp = target.with_name(target.name + ".tmp")
    # Explicit open + flush + fsync (not Path.write_text) so the temp file's
    # bytes are on stable storage BEFORE the atomic rename — a crash between the
    # write and the replace can never leave a torn store (W2 durability
    # substrate). The write site stays attributed to session_registry (the
    # write-tripwire mutation-of-record inventory), and the tmp→target replace
    # keeps the atomic idiom.
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(json.dumps(items, indent=2, ensure_ascii=False))
        f.flush()
        os.fsync(f.fileno())
    _atomic_replace(str(tmp), str(target))


def _save_sessions(reg: dict, *, _locked: bool = False) -> None:
    """Persist the registry (dict keyed by id) as a JSON list, atomically.

    WRITE_LOCK reentrancy (zombie-hunter → safe-to-arm, Wave 3): the mutating
    CRUD entrypoints (:func:`register_session`, :func:`update_session`,
    :func:`set_current_stage`, :func:`remove_session`, :func:`reconcile`) already
    run inside ``with paths.WRITE_LOCK``. They call this with ``_locked=True`` so
    the write does NOT re-acquire the lock — the critical section is SPLIT (the
    held lock is passed down as the ``_locked`` flag), rather than relying on the
    lock being reentrant. The code is therefore correct even if ``WRITE_LOCK`` is
    a plain, non-reentrant ``threading.Lock`` — no self-deadlock on a held lock.
    A standalone caller (the default ``_locked=False``) acquires the lock here.
    """
    if _locked:
        _write_sessions_locked(reg)
    else:
        with _paths.WRITE_LOCK:
            _write_sessions_locked(reg)


# ── CRUD ──────────────────────────────────────────────────────────────────

def register_session(project_id, lane, backend=BACKEND_CLAUDE,
                     worktree_path="", branch="", status=STATUS_IDLE,
                     label="", session_id=None, parent_session_id="",
                     chain_id=None, grass_origin="",
                     effort_id=None, effort_managed=False,
                     pid=None, proc_create_time=None, crypt_token="",
                      engine_session_uuid="", doctor_mode="",
                      doctor_posture="") -> dict:
    """Register a managed terminal session. Returns the stored record.

    ``session_id`` is allocated fresh when not supplied; an explicitly provided
    id is accepted (e.g. so a caller can mint the id, create the worktree under
    it, then register). ``created_at`` is stamped now (``time.time``).

    v6 Wave 2: ``parent_session_id`` is the upstream session this one was
    advanced from ("" for a chain root); ``chain_id`` groups the lineage. When
    ``chain_id`` is None it DEFAULTS to the session's OWN id — i.e. a parentless
    session starts its own singleton chain. A child should pass its parent's
    ``chain_id`` to join that chain.
    """
    with _paths.WRITE_LOCK:
        reg = load_sessions()
        sid = session_id or _new_id()
        while sid in reg and session_id is None:  # cheap collision safety
            sid = _new_id()
        record = _normalize({
            "session_id": sid,
            "project_id": project_id,
            "lane": lane,
            "backend": backend,
            "worktree_path": worktree_path,
            "branch": branch,
            "status": status,
            "created_at": time.time(),
            "label": label,
            "parent_session_id": parent_session_id or "",
            "chain_id": chain_id or sid,
            "grass_origin": grass_origin or "",
            # v12 Wave 1: the effort's stable id (defaults to the OWN sid when
            # not inherited) + the v12 discriminator (set True ONLY by the v12
            # entrypoints; legacy callers leave it False).
            "effort_id": effort_id or sid,
            "effort_managed": bool(effort_managed),
            # zombie-hunter v2: process-identity fields (back-compat None/"").
            "pid": pid,
            "proc_create_time": proc_create_time,
            "crypt_token": crypt_token or "",
            # Honest Telemetry W4: engine-session UUID captured at launch (the
            # deterministic sidecar correlation). Empty when not captured yet.
            "engine_session_uuid": engine_session_uuid or "",
            # Anchor Doctor P0: empty on every ordinary/pre-feature session.
            # Doctor session reuse requires an exact mode/backend/posture tuple.
            "doctor_mode": doctor_mode or "",
            "doctor_posture": doctor_posture or "",
        })
        reg[sid] = record
        _save_sessions(reg, _locked=True)
        return record


def get_session(session_id: str):
    """Return the record for ``session_id`` or ``None``."""
    return load_sessions().get(session_id)


def list_sessions(project_id=None, status=None) -> list:
    """Return session records as a list, optionally filtered.

    - ``project_id`` — only sessions for that project.
    - ``status`` — only sessions in that status.

    Sorted newest-first by ``created_at`` (records with no timestamp sort last).
    """
    reg = load_sessions()
    out = []
    for rec in reg.values():
        if project_id is not None and rec.get("project_id") != project_id:
            continue
        if status is not None and rec.get("status") != status:
            continue
        out.append(rec)
    out.sort(key=lambda r: (r.get("created_at") is None,
                            -(r.get("created_at") or 0.0)))
    return out


# ── Session lineage / chains (v6 Wave 2) ────────────────────────────────────
#
# Stable lane ordering for a chain's members: research → plan/planning → build
# → (anything else) then by created_at ascending. Both the trio-lane keys
# (research/plan/build) and the on-disk dir names (planning/deliverables) are
# scored so either naming sorts correctly.
_CHAIN_LANE_ORDER = {
    "research": 0,
    "plan": 1,
    "planning": 1,
    "build": 2,
    "deliverables": 3,
    "grass": 4,
}
_CHAIN_LANE_DEFAULT = 9  # unknown lanes sort after the known trio order


def chain_for(session_id: str):
    """Return the ``chain_id`` of ``session_id``, or ``None`` if unknown."""
    rec = load_sessions().get(session_id)
    if rec is None:
        return None
    return rec.get("chain_id") or rec.get("session_id")


def chain_members(chain_id: str) -> list:
    """Return the ordered records belonging to ``chain_id``.

    Ordered research → plan/planning → build → (others) by lane, then by
    ``created_at`` ascending (records with no timestamp sort last within a
    lane). Returns ``[]`` when no record carries the given ``chain_id``.
    """
    if not chain_id:
        return []
    reg = load_sessions()
    members = [rec for rec in reg.values()
               if (rec.get("chain_id") or rec.get("session_id")) == chain_id]
    members.sort(key=lambda r: (
        _CHAIN_LANE_ORDER.get(r.get("lane", ""), _CHAIN_LANE_DEFAULT),
        r.get("created_at") is None,
        r.get("created_at") or 0.0,
    ))
    return members


# ── Effort stages (v12 Wave 1) ──────────────────────────────────────────────
#
# An effort is ONE session that carries a stage. ``stage_history`` is an
# append-only list of per-stage entries; ``current_stage``/``lane`` flip as the
# effort advances research → plan → build. ``store_lane`` is recorded per stage
# so a CLOSED stage's docs/summary resolve under the lane they were written in,
# even after ``lane`` later flips (Analyst A1).

#: ``store_lane`` mapping for the trio stages (the on-disk dir a stage's docs +
#: summaries live under). research → research; plan → planning; build → build.
_STAGE_STORE_LANE = {
    "research": "research",
    "plan": "planning",
    "build": "build",
}


def effort_root(session_id: str):
    """Return the ``effort_id`` (the effort's stable root id) for ``session_id``.

    For a v12 effort this is the root session_id (inherited by a context-relief
    continuation). For a pre-v12 record it normalizes to the record's own
    session_id. Returns ``None`` for an unknown session.
    """
    rec = load_sessions().get(session_id)
    if rec is None:
        return None
    return rec.get("effort_id") or rec.get("session_id")


def stage_entry(record: dict, stage: str):
    """Return the most-recent ``stage_history`` entry for ``stage`` in ``record``.

    ``record`` is a normalized session record (a dict). Searches its
    ``stage_history`` newest-last and returns the LAST entry whose ``stage``
    matches (the active or most-recently-closed entry for that stage), or
    ``None`` when the stage has no entry. Pure / read-only — never touches the
    store.
    """
    if not isinstance(record, dict):
        return None
    found = None
    for ent in record.get("stage_history") or []:
        if isinstance(ent, dict) and ent.get("stage") == stage:
            found = ent
    return found


def set_current_stage(session_id: str, stage: str, store_lane: str,
                      baseline_ref: str) -> dict:
    """Flip an effort to a new ``stage``: close the prior active entry, append a
    new active one, and update ``current_stage`` + ``lane`` (v12 Wave 1).

    Mechanics (under ``paths.WRITE_LOCK``):

    - The prior ACTIVE ``stage_history`` entry (``ended_at`` is None) is closed:
      ``ended_at`` is stamped now and its ``state`` becomes ``"done"``.
    - A NEW entry for ``stage`` is appended with ``state="active"``,
      ``started_at`` now, ``ended_at=None``, the given ``store_lane`` +
      ``baseline_ref``, and ``seeded=False`` / ``summary_ref=None`` /
      ``doc_count=0``.
    - ``current_stage`` is set to ``stage`` and ``lane`` is set to
      ``store_lane`` (the board routes by ``current_stage``/``kind``; ``lane``
      tracks the current store-lane).

    Returns the updated record. Raises ``KeyError`` for an unknown id.
    """
    with _paths.WRITE_LOCK:
        reg = load_sessions()
        if session_id not in reg:
            raise KeyError(session_id)
        rec = dict(reg[session_id])
        now = time.time()
        history = [dict(e) for e in (rec.get("stage_history") or [])
                   if isinstance(e, dict)]
        # Close the prior active entry (the one still open).
        for ent in history:
            if ent.get("ended_at") is None:
                ent["ended_at"] = now
                ent["state"] = "done"
        # Append the new active stage entry.
        history.append({
            "stage": stage,
            "store_lane": store_lane,
            "started_at": now,
            "ended_at": None,
            "baseline_ref": baseline_ref,
            "seeded": False,
            "summary_ref": None,
            "doc_count": 0,
            "state": "active",
        })
        rec["stage_history"] = history
        rec["current_stage"] = stage
        rec["lane"] = store_lane
        rec = _normalize(rec)
        rec["session_id"] = session_id
        reg[session_id] = rec
        _save_sessions(reg, _locked=True)
        return rec


def update_session(session_id: str, **fields) -> dict:
    """Update allowed fields of a session record. Returns the updated record.

    Allowed: ``project_id, lane, backend, worktree_path, branch, status,
    label, seeded, seed_text, parent_session_id, chain_id``. ``session_id`` and
    ``created_at`` are immutable. Raises ``KeyError`` if the id is unknown.
    """
    allowed = {"project_id", "lane", "backend", "worktree_path", "branch",
               "status", "label", "seeded", "seed_text",
               "parent_session_id", "chain_id",
               # v10 Wave 1: paste-NOT-submit handoff bookkeeping.
               "pending_paste", "paste_flushed",
               # v10 Wave 4: grass→project lineage stamp.
               "grass_origin",
               # v12 Wave 1: effort stage fields.
               "kind", "current_stage", "stage_history", "seeded_stages",
               "effort_id", "effort_managed",
               # zombie-hunter v2: process-identity fields.
               "pid", "proc_create_time", "crypt_token",
               # zombie-hunter safe-to-arm, Wave 6: owned-job claim set.
               "owned_job_ids",
               # Honest Telemetry W4: engine-session UUID capture + usage state.
               "engine_session_uuid", "engine_session_uuids",
               "usage_state", "usage_reason",
               # Honest Telemetry W5: durable mixed-session (gemini-segment) marker.
               "usage_gemini_segment",
               # Anchor Doctor P0: exact durable session-reuse identity.
               "doctor_mode", "doctor_posture",
               # telemetry-resume W6: bounded oldest-first parked-worktree
               # eviction (worktree reclaimed, everything else survives) +
               # the greet-gate bounded-fallback stamp + the read-only
               # orientation one-shot job's origin-ownership window.
               "evicted", "evicted_at", "pending_paste_since",
               "orientation_owned_until", "orientation_job_id"}
    with _paths.WRITE_LOCK:
        reg = load_sessions()
        if session_id not in reg:
            raise KeyError(session_id)
        rec = dict(reg[session_id])
        # Wave 5: the state-transition table is the single authority that makes
        # STATUS_CANCELLED (and STATUS_REAPED_ORPHAN) strictly terminal. A status
        # change OUT of a terminal-locked state is REJECTED here — the locked
        # status is kept so the record is never resurrected — while every other
        # field in the same call still applies.
        orig_status = reg[session_id].get("status")
        for k, v in fields.items():
            if k in allowed and v is not None:
                if k == "status" and not can_transition(orig_status, v):
                    _log_rejected_transition(session_id, orig_status, v)
                    continue
                rec[k] = v
        rec = _normalize(rec)
        rec["session_id"] = session_id
        reg[session_id] = rec
        _save_sessions(reg, _locked=True)
        return rec


def remove_session(session_id: str) -> bool:
    """Hard-delete a session record from the registry. Returns success."""
    with _paths.WRITE_LOCK:
        reg = load_sessions()
        if session_id in reg:
            del reg[session_id]
            _save_sessions(reg, _locked=True)
            return True
        return False


# ── Terminal cost-finalization latch (Honest Telemetry, W2) ─────────────────

def finalize_cost_once(session_id: str) -> bool:
    """Compare-and-set the terminal cost-finalization flag for a session (W2).

    Finalize-on-every-end-path (kill / close-park / drain / finish /
    reconcile-dead) can fire CONCURRENTLY against the same session; without a
    latch each racer would write the session's RUN cost record and the rollup
    would double-count. This is the atomic gate: it returns ``True`` for EXACTLY
    ONE caller — the one that wins the race to flip ``cost_final`` from unset to
    set — and ``False`` for every subsequent caller (and for an unknown id). The
    caller that gets ``True`` is the sole writer of the finalized cost record.

    Atomicity: the whole read-check-write runs under ``paths.WRITE_LOCK`` and the
    flag is persisted WITH the record (``cost_final`` + ``cost_final_at``) via the
    registry's atomic tmp→rename write, so the latch survives a crash and a
    restart never re-finalizes an already-finalized session. Idempotent by
    construction: calling again after the win is a no-op that returns ``False``.
    """
    if not session_id:
        return False
    with _paths.WRITE_LOCK:
        reg = load_sessions()
        rec = reg.get(session_id)
        if rec is None:
            return False
        if rec.get("cost_final"):
            return False  # another end path already finalized this session
        rec = dict(rec)
        rec["cost_final"] = True
        rec["cost_final_at"] = time.time()
        rec = _normalize(rec)
        rec["session_id"] = session_id
        reg[session_id] = rec
        _save_sessions(reg, _locked=True)
        return True


def add_engine_session_uuid(session_id: str, engine_session_uuid: str) -> dict:
    """Record an engine-session UUID on a managed session (Honest Telemetry W4).

    Sets ``engine_session_uuid`` (the CURRENT/last segment) and APPENDS it to the
    append-only ``engine_session_uuids`` history — so a session that switches
    engine mid-run accumulates BOTH sidecar segments and finalize sums over all of
    them (counted once). Atomic (under ``paths.WRITE_LOCK``), idempotent (a
    duplicate uuid is not re-appended). A no-op returning the current record for an
    unknown id or a blank uuid.
    """
    if not session_id or not engine_session_uuid:
        return get_session(session_id) or {}
    u = str(engine_session_uuid)
    with _paths.WRITE_LOCK:
        reg = load_sessions()
        rec = reg.get(session_id)
        if rec is None:
            return {}
        rec = dict(rec)
        hist = list(rec.get("engine_session_uuids") or [])
        if u not in hist:
            hist.append(u)
        rec["engine_session_uuids"] = hist
        rec["engine_session_uuid"] = u
        rec = _normalize(rec)
        rec["session_id"] = session_id
        reg[session_id] = rec
        _save_sessions(reg, _locked=True)
        return rec


# ── Reference-counted owned-job claims (zombie-hunter safe-to-arm, Wave 6) ───
#
# A managed trio session OWNS the ``job_runner`` jobs it spawned (Gemini-swarm
# sub-agents, previews). When the session dies its jobs must die WITH it — the
# exact orphan-swarm the reaper exists to prevent — via a targeted per-``job_id``
# cancel walked off this explicit claim set (never a full ``list_records``
# scan). Ownership is REFERENCE-COUNTED: a job handed off to / shared with a live
# successor in the chain (e.g. plan→build, a shared preview) is claimed by that
# successor too, so it survives the predecessor's teardown. These helpers are the
# storage seam; the teardown orchestration lives in ``terminal_session``.

def owned_jobs(session_id_or_record) -> list:
    """Return the list of ``job_id``s a session explicitly claims (owns).

    Accepts a ``session_id`` string OR a record dict. An unknown id / a record
    with no claim set yields ``[]``. The returned list is a fresh copy — mutating
    it never touches the stored record.
    """
    rec = session_id_or_record
    if isinstance(rec, str):
        rec = load_sessions().get(rec)
    if not isinstance(rec, dict):
        return []
    jobs = rec.get("owned_job_ids")
    return list(jobs) if isinstance(jobs, (list, tuple)) else []


def claim_job(session_id: str, job_id: str) -> bool:
    """Record that ``session_id`` owns ``job_id`` (append to its claim set).

    Idempotent + de-duped: claiming the same ``job_id`` twice is a no-op. Returns
    True when a NEW claim was recorded, False when the session is unknown or the
    claim already existed. A CANCELLED/terminal-locked record can still take a
    claim — the terminal lock only guards ``status`` (Wave 5), not bookkeeping —
    but the teardown only honors claims held by LIVE sessions, so a claim on a
    dead session never keeps a job alive.
    """
    if not session_id or not job_id:
        return False
    job_id = str(job_id)
    with _paths.WRITE_LOCK:
        reg = load_sessions()
        if session_id not in reg:
            return False
        rec = dict(reg[session_id])
        jobs = list(rec.get("owned_job_ids") or [])
        if job_id in jobs:
            return False
        jobs.append(job_id)
        rec["owned_job_ids"] = jobs
        rec = _normalize(rec)
        rec["session_id"] = session_id
        reg[session_id] = rec
        _save_sessions(reg, _locked=True)
        return True


def release_job(session_id: str, job_id: str) -> bool:
    """Drop ``session_id``'s claim over ``job_id`` (ownership hand-off / reap).

    Returns True when a claim was removed, False when the session is unknown or
    did not hold the claim. Used to record an explicit ownership transfer: when a
    dying session's job survives because a live successor still claims it, the
    dying session releases its claim so the successor is the sole owner.
    """
    if not session_id or not job_id:
        return False
    job_id = str(job_id)
    with _paths.WRITE_LOCK:
        reg = load_sessions()
        if session_id not in reg:
            return False
        rec = dict(reg[session_id])
        jobs = list(rec.get("owned_job_ids") or [])
        if job_id not in jobs:
            return False
        jobs = [j for j in jobs if j != job_id]
        rec["owned_job_ids"] = jobs
        rec = _normalize(rec)
        rec["session_id"] = session_id
        reg[session_id] = rec
        _save_sessions(reg, _locked=True)
        return True


def job_claimants(job_id, records=None, *, exclude=None) -> list:
    """Return the session RECORDS that explicitly claim ``job_id``.

    Reference-count primitive: walks the SESSION registry (never
    ``job_runner.list_records``) for every record whose ``owned_job_ids`` holds
    ``job_id``. ``exclude`` (a session_id or an iterable of them) drops the caller
    from its own count. ``records`` may pre-supply the record list (one snapshot
    per teardown) so the walk is not re-read per job.
    """
    if not job_id:
        return []
    job_id = str(job_id)
    if records is None:
        records = list(load_sessions().values())
    if exclude is None:
        excl = frozenset()
    elif isinstance(exclude, str):
        excl = frozenset((exclude,))
    else:
        excl = frozenset(exclude)
    out = []
    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        sid = rec.get("session_id")
        if sid in excl:
            continue
        jobs = rec.get("owned_job_ids")
        if isinstance(jobs, (list, tuple)) and job_id in [str(j) for j in jobs]:
            out.append(rec)
    return out


# ── Recovery / reconcile (MASTER-PLAN §I) ─────────────────────────────────

def reconcile(live_session_ids=None, worktree_exists=None,
              mark_stale_status=STATUS_IDLE, apply=True) -> dict:
    """Reconcile the persisted registry against live processes + worktrees.

    Called on load (e.g. after a service restart) to make the registry reflect
    true live state. Pure/injectable so it is unit-testable WITHOUT touching real
    processes or git:

    - ``live_session_ids`` — the set of session ids that currently have a LIVE
      process (e.g. ``set(pty_manager.live_sessions())`` and/or running
      ``job_runner`` ids). A persisted session marked ``running`` whose id is NOT
      in this set is **stale** (its process is gone): it is marked not-running
      (``mark_stale_status``, default ``STATUS_IDLE``). ``None`` means "treat no
      session as live" (every running one is stale — the cold-start case).
    - ``worktree_exists`` — an optional callable ``session_id -> bool`` reporting
      whether the session's worktree still exists on disk. A session whose
      worktree is gone is reported under ``orphaned_worktrees`` (the registry
      record is left intact — the caller decides whether to drop it).

    With ``apply=True`` (default) the stale sessions are persisted with their new
    status; with ``apply=False`` it is a dry-run that reports without mutating.

    Returns::

        {"stale": [session_id, ...],          # were running, process gone
         "orphaned_worktrees": [session_id],  # worktree missing on disk
         "marked": [session_id, ...],         # actually re-statused (apply only)
         "applied": bool}

    ``applied`` reports whether a mutation was actually WRITTEN to the store. It
    is therefore ALWAYS ``False`` when ``apply=False`` (a dry-run never mutates),
    regardless of whether any stale sessions were found. When ``apply=True`` it
    is ``True`` only if there was at least one stale session to re-status (no
    stale sessions → nothing written → ``applied`` is ``False``).
    """
    live = set(live_session_ids) if live_session_ids is not None else set()
    reg = load_sessions()

    stale = []
    orphaned = []
    for sid, rec in reg.items():
        if rec.get("status") == STATUS_RUNNING and sid not in live:
            stale.append(sid)
        wp = rec.get("worktree_path") or ""
        if wp:
            if worktree_exists is not None:
                gone = not bool(worktree_exists(sid))
            else:
                try:
                    gone = not Path(wp).exists()
                except (OSError, ValueError):
                    gone = False
            if gone:
                orphaned.append(sid)

    report = {
        "stale": stale,
        "orphaned_worktrees": orphaned,
        "marked": [],
        "applied": bool(apply),
    }
    if not apply or not stale:
        report["applied"] = bool(apply) and bool(stale)
        return report

    with _paths.WRITE_LOCK:
        reg = load_sessions()
        marked = []
        for sid in stale:
            if sid in reg and reg[sid].get("status") == STATUS_RUNNING:
                rec = dict(reg[sid])
                rec["status"] = (mark_stale_status
                                 if mark_stale_status in VALID_STATUSES
                                 else STATUS_IDLE)
                reg[sid] = _normalize(rec)
                marked.append(sid)
        if marked:
            _save_sessions(reg, _locked=True)
        report["marked"] = marked
        report["applied"] = True
    return report


# ── Wave 5: conservative legacy STATUS_IDLE → STATUS_PARKED_WARM migration ────

def migrate_idle_to_parked_warm(apply=True) -> dict:
    """Migrate every legacy ``STATUS_IDLE`` record forward to ``PARKED_WARM``.

    The Wave-5 split disambiguated the overloaded ``idle`` into ``parked-warm``
    (keeps its worktree) and ``reaped-orphan`` (no worktree). A legacy ``idle``
    record kept its worktree, so ``parked-warm`` is the CONSERVATIVE (over-protect
    only) reading — the migration NEVER downgrades a record to reaped-orphan.

    On the FIRST boot that actually migrates a record, the reaper's persistent
    dry-run marker is armed (via :func:`worktrees.arm_reaper_dryrun`) so that the
    first post-migration sweep is REPORT-ONLY (log, delete nothing) — reap is
    re-armed only after one clean dry report, so a migration can never race a live
    delete. Best-effort and never raises.

    Returns ``{"migrated": [session_id, ...], "applied": bool}``.
    """
    reg = load_sessions()
    targets = [sid for sid, rec in reg.items()
               if rec.get("status") == STATUS_IDLE]
    report = {"migrated": [], "applied": bool(apply)}
    if not targets:
        report["applied"] = False
        return report
    if not apply:
        report["migrated"] = list(targets)
        report["applied"] = False
        return report

    with _paths.WRITE_LOCK:
        reg = load_sessions()
        migrated = []
        for sid in targets:
            if sid in reg and reg[sid].get("status") == STATUS_IDLE:
                rec = dict(reg[sid])
                rec["status"] = STATUS_PARKED_WARM
                reg[sid] = _normalize(rec)
                migrated.append(sid)
        if migrated:
            _save_sessions(reg, _locked=True)
        report["migrated"] = migrated

    if report["migrated"]:
        # First post-migration boot sweeps report-only (never a live delete on the
        # boot that just rewrote the state). Best-effort — arming is a safety belt.
        try:
            import worktrees as _wt
            _wt.arm_reaper_dryrun()
        except Exception:
            _log.info("session_registry: reaper dry-run arm skipped after "
                      "idle→parked-warm migration (best-effort)")
    return report
