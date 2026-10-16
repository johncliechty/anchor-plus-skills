#!/usr/bin/env python3
"""Anchor per-project append-only event journal — the C3 spine (rearch W12).

This module is the ONE schema-validated, append-only write path for the Butler
substrate's event log (frozen plan ``IMPLEMENTATION-PLAN.md`` W12; locked
decision **D1**: a per-project append-only JSONL journal, DUAL-WRITE — the
legacy stores stay authoritative for reads; the parity gate + recovery tools
(W14) are the journal's mandatory consumers).

Design (the deliverables of W12):

* **ONE emit() choke point.** :func:`emit` is the *only* function that appends
  to a journal. It schema-validates the event, allocates a monotonic per-project
  ``seq`` under :data:`paths.WRITE_LOCK`, and does an O(1) open-append-close of a
  single JSON line, with a configurable fsync policy
  (``ANCHOR_JOURNAL_FSYNC``). No other module may open a journal file for
  writing — :func:`scan_direct_journal_writes` is the distro.py-style scan that
  enforces this mechanically.
* **Butler envelope.** Every event carries the mandatory envelope fields the
  three W3 Butler user stories are answered from
  (``planning/rearch-2026-07/BUTLER-USER-STORIES.md``): a per-project monotonic
  ``seq`` and wall ``ts``; ``correlation_id`` (groups a whole effort/chain);
  ``causation_id`` (the id of the thing that caused this event — the parent
  session for a lifecycle event; ``None`` for a root user action); an
  ``actor`` ``{kind, id}`` whose kind is one of :data:`ACTOR_KINDS`
  (``user-click`` · ``auto-advance`` · ``healthcheck-synthetic`` · ``cli``); the
  event ``type``; and ``schema_ver``.
* **Dual-write, journal-first.** :func:`dual_write` is the blessed wrapper — the
  ONLY sanctioned :func:`emit` call site for an instrumented mutation. It emits
  the journal event FIRST, then performs the legacy-store write, both paired
  under the write-tripwire (:mod:`tools.write_tripwire`). Journal emission is
  best-effort: a journal failure is swallowed so it can NEVER prevent the legacy
  write ("alongside, never instead of"). A crash *between* the journal append
  and the legacy write leaves an orphaned journal event that classifies as
  **benign journal-ahead intent** — replayable idempotently by the W14 recovery
  tool, never a lost legacy write.
* **Off-switch.** Journal emission is behind the ``journal`` pillar flag
  (``ANCHOR_JOURNAL=off|on``, default **off** = today's live behavior — see
  :mod:`pillar_flags`). With the flag off, :func:`dual_write` runs ONLY the
  legacy write, byte-identical to pre-journal behavior; :func:`emit` still works
  when called directly (it is the mechanism; the flag is policy at the call
  sites).

── Schema-evolution rule (BINDING module convention) ────────────────────────

The journal is an append-only log read back by tools written at many different
points in time, so the on-disk schema evolves under a strict, binding rule:

  1. **Additive-only within a major version.** Within a given
     ``schema_ver`` major, new fields may be ADDED but an existing field's
     name/meaning is NEVER changed or removed. A field, once shipped in a
     major, means the same thing forever in that major.
  2. **Unknown-field-tolerant readers.** Every reader
     (:func:`read_events` and any Butler/tool consumer) MUST tolerate events
     that carry fields it does not recognise, and events whose ``schema_ver``
     is HIGHER than the reader knows — it reads the envelope fields it
     understands and ignores the rest, never raising. A field is only ever
     REMOVED / repurposed across a major-version bump, and a reader that must
     span a bump migrates old events forward via :func:`migrate_event`.

:data:`CURRENT_SCHEMA_VER` is the version :func:`emit` stamps. The
v1-through-v-current round-trip is proven green in the W12 test
(``tests/test_journal_core_w12.py``): a v1 event written and read back is
unchanged, and a forward event (higher ``schema_ver`` + an unknown field) is
still read without error.

Stdlib only (``json``, ``os``, ``threading``, ``time``, ``pathlib``); imports
:mod:`paths` and :mod:`pillar_flags` (both stdlib-only) at module load, and
:mod:`rnd_registry` / :mod:`tools.write_tripwire` lazily to avoid any import
cycle.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path

import paths as _paths
import pillar_flags as _flags

REPO_ROOT = Path(__file__).resolve().parent

# ── Schema + envelope constants ──────────────────────────────────────────────

#: The schema-major :func:`emit` stamps on every event. Bumped only on a
#: breaking change, per the schema-evolution rule in the module docstring.
CURRENT_SCHEMA_VER = 1

ANCHOR_DIRNAME = ".anchor"
PROJECTS_DIRNAME = "projects"
#: The single journal filename per project (allowlisted by the write-tripwire —
#: see :data:`tools.write_tripwire.JOURNAL_FILENAMES`; the names were fixed in W1
#: before the journal existed).
JOURNAL_FILENAME = "journal.jsonl"

#: The four sanctioned actor kinds (Butler story 3 partitions on these).
ACTOR_KIND_USER_CLICK = "user-click"
ACTOR_KIND_AUTO_ADVANCE = "auto-advance"
ACTOR_KIND_HEALTHCHECK = "healthcheck-synthetic"
ACTOR_KIND_CLI = "cli"
ACTOR_KINDS = (
    ACTOR_KIND_USER_CLICK,
    ACTOR_KIND_AUTO_ADVANCE,
    ACTOR_KIND_HEALTHCHECK,
    ACTOR_KIND_CLI,
)

#: The neutral fallback actor when no ambient/explicit actor is supplied — a
#: programmatic call (never mislabels a user click or a synthetic walk).
DEFAULT_ACTOR_KIND = ACTOR_KIND_CLI

# ── Session-lifecycle event types (the W12 "first instrumented class") ────────

EV_SESSION_STARTED = "session-started"
EV_SESSION_ADVANCED = "session-advanced"
EV_SESSION_KILLED = "session-killed"
EV_SESSION_CLOSED = "session-closed"

# ── W13 (C3): the full mutation-of-record set the W1 tripwire enumerated ───────
# Every remaining mutation-of-record class instrumented via the blessed
# :func:`journaled` / :func:`dual_write` wrappers (frozen plan Wave 15). Per-tick
# / telemetry writes (a job record's periodic cost/progress re-stamp, a
# summary-cache refresh) are EXCLUDED BY RULE — they are not mutations of record.

#: doc-persisted — a trio session's produced docs copied+committed into the main
#: project (``effort_history.persist_session_docs``; the v8 keystone).
EV_DOC_PERSISTED = "doc-persisted"

#: job lifecycle — a durable lane job launched / reached a terminal state /
#: cancelled (``job_runner``).
EV_JOB_LAUNCHED = "job-launched"
EV_JOB_FINISHED = "job-finished"
EV_JOB_CANCELLED = "job-cancelled"

#: effort promoted — an inbox item or a grass idea promoted into a real lane.
EV_EFFORT_PROMOTED = "effort-promoted"

#: grass idea lifecycle (raw → refined → promoted, plus archive/export/delete).
EV_GRASS_IDEA_ADDED = "grass-idea-added"
EV_GRASS_IDEA_REFINED = "grass-idea-refined"
EV_GRASS_IDEA_STATUS = "grass-idea-status-changed"
EV_GRASS_IDEA_ARCHIVED = "grass-idea-archived"
EV_GRASS_IDEA_EXPORTED = "grass-idea-exported"
EV_GRASS_IDEA_DELETED = "grass-idea-deleted"

#: deliverable pinned / launched (``deliverables``).
EV_DELIVERABLE_PINNED = "deliverable-pinned"
EV_DELIVERABLE_LAUNCHED = "deliverable-launched"

#: project lifecycle — created / priority-archive-retire-reactivate / relabel
#: (``rnd_registry``).
EV_PROJECT_CREATED = "project-created"
EV_PROJECT_LIFECYCLE = "project-lifecycle-changed"

#: handoff recorded — a stage handoff persisted (``handoff.record_handoff``).
EV_HANDOFF_RECORDED = "handoff-recorded"

#: boneyard capture — discarded material indexed (``boneyard.record_entry``).
EV_BONEYARD_CAPTURED = "boneyard-captured"

#: The mandatory envelope keys every event carries (schema validation target).
ENVELOPE_KEYS = (
    "schema_ver",
    "seq",
    "ts",
    "type",
    "actor",
    "correlation_id",
    "causation_id",
    "project_id",
    "event_id",
    "payload",
)

# The fsync policy env seam (configurable fsync policy, W12 deliverable).
FSYNC_ENV = "ANCHOR_JOURNAL_FSYNC"


class JournalError(RuntimeError):
    """Base class for journal failures."""


class JournalSchemaError(JournalError, ValueError):
    """An event failed schema validation at the :func:`emit` choke point."""


# ── Off-switch + fsync policy ────────────────────────────────────────────────

def enabled(env=None) -> bool:
    """True when journal emission is ON (the ``journal`` pillar flag).

    Default is OFF (today's live behavior). Reads the flag via
    :func:`pillar_flags.current_flags` so an invalid value fails loudly there.
    """
    try:
        return _flags.current_flags(env=env)[_flags.FLAG_JOURNAL] == "on"
    except Exception:
        # A malformed flag env is surfaced by pillar_flags' own healthcheck
        # assertion; the journal must never crash a mutation over it — default
        # to OFF (the safe, no-op behavior).
        return False


def fsync_enabled(env=None) -> bool:
    """True when each append should be fsync'd to durable storage.

    Configurable via ``ANCHOR_JOURNAL_FSYNC`` (``1``/``on``/``true``/``yes``).
    Default OFF — the atomic single-line append is already crash-consistent for
    the journal-ahead model; fsync is opt-in for hosts that want durability over
    throughput.
    """
    e = os.environ if env is None else env
    raw = (e.get(FSYNC_ENV) or "").strip().lower()
    return raw in ("1", "on", "true", "yes")


# ── Journal path resolution (journals born in the relocated data dir) ─────────

def journal_path_for(folder_path, project_id: str) -> Path:
    """``<folder>/.anchor/projects/<id>/journal.jsonl`` — pure, not created.

    Matches :func:`rnd_registry.project_store_dir` exactly, so the journal is
    born alongside the per-project stores under the relocated data dir.
    """
    return (Path(folder_path) / ANCHOR_DIRNAME / PROJECTS_DIRNAME
            / str(project_id) / JOURNAL_FILENAME)


def journal_path(project_id: str, folder_path=None) -> Path:
    """Resolve a project's journal path, looking up its folder when not given.

    ``folder_path`` (when supplied) wins — pure and decoupled. Otherwise the
    project's ``folder_path`` is read from :mod:`rnd_registry`; a project with no
    resolvable folder falls back to the data-dir root
    (``paths.data_dir()/.anchor/projects/<id>/journal.jsonl``).
    """
    folder = folder_path
    if not folder:
        try:
            import rnd_registry as _rnd
            proj = _rnd.get_project(project_id)
            folder = (proj or {}).get("folder_path", "") or ""
        except Exception:
            folder = ""
    if not folder:
        folder = str(_paths.data_dir())
    return journal_path_for(folder, project_id)


# ── Actor helpers (explicit arg → thread-local ambient → default) ────────────

_ACTOR_TLS = threading.local()


def actor(kind, id="") -> dict:
    """Build + validate an ``{kind, id}`` actor. Raises on an unknown kind."""
    if kind not in ACTOR_KINDS:
        raise JournalSchemaError(
            "unknown actor kind %r — expected one of: %s"
            % (kind, ", ".join(ACTOR_KINDS)))
    return {"kind": kind, "id": "" if id is None else str(id)}


def auto_advance_actor(id="") -> dict:
    """The ``auto-advance`` actor (the machine acting on John's behalf)."""
    return actor(ACTOR_KIND_AUTO_ADVANCE, id)


def default_actor() -> dict:
    """The ambient thread-local actor if one is in scope, else the CLI default."""
    amb = getattr(_ACTOR_TLS, "actor", None)
    if amb is not None:
        return dict(amb)
    return {"kind": DEFAULT_ACTOR_KIND, "id": ""}


class actor_scope:
    """Context manager establishing the ambient actor for the current thread.

    An HTTP handler wraps a request in ``with journal.actor_scope('user-click',
    <user>):`` so every lifecycle mutation it drives is attributed correctly
    without threading an ``actor`` argument through every call. Nestable — the
    prior ambient actor is restored on exit.
    """

    def __init__(self, kind, id=""):
        self._actor = actor(kind, id)
        self._prev = None

    def __enter__(self):
        self._prev = getattr(_ACTOR_TLS, "actor", None)
        _ACTOR_TLS.actor = self._actor
        return self._actor

    def __exit__(self, *exc):
        _ACTOR_TLS.actor = self._prev
        return False


def _coerce_actor(a) -> dict:
    """Normalise an actor arg (dict | kind-string | None) to a valid actor."""
    if a is None:
        return default_actor()
    if isinstance(a, str):
        return actor(a)
    if isinstance(a, dict):
        return actor(a.get("kind"), a.get("id", ""))
    raise JournalSchemaError("actor must be a dict, a kind string, or None")


# ── Write-tripwire pairing (best-effort; no-op when the tripwire is absent) ───

class _NullPairing:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def pairing():
    """Arm the write-tripwire journal pairing for the enclosed writes.

    Returns :func:`tools.write_tripwire.journal_event` when the tripwire module
    is importable (so the blessed legacy-store writes an emit triggers are PAIRED
    once the completeness gate is armed in W13), else a harmless no-op context
    manager. Never raises.
    """
    try:
        from tools import write_tripwire as _wt
        return _wt.journal_event()
    except Exception:
        return _NullPairing()


# ── The permanent C3 completeness gate (W13: enforce mode + journal on) ───────

class completeness_gate:
    """Arm the permanent C3 write-completeness gate for the enclosed block.

    W13 flips the W1 write-site tripwire to its permanent ENFORCE mode: with this
    gate active, EVERY mutation of a ``.anchor/`` store that is not paired with a
    journal event (via :class:`journaled` / :func:`dual_write`) raises
    :class:`tools.write_tripwire.TripwireViolation` naming the write site —
    completeness is mechanical, not narrated.

    On enter it (1) forces the ``journal`` flag ON in the process env (so the
    blessed wrappers actually emit + arm pairing) and (2) installs the tripwire
    in enforce mode. On exit it uninstalls the tripwire and restores the prior
    ``ANCHOR_JOURNAL`` value. Best-effort import of the tripwire — a host without
    the tools package degrades to journal-on-only (never crashes the caller).
    """

    def __init__(self, clear=True):
        self._clear = clear
        self._prev_journal = None
        self._wt = None

    def __enter__(self):
        self._prev_journal = os.environ.get(_flags.FLAG_ENV[_flags.FLAG_JOURNAL])
        os.environ[_flags.FLAG_ENV[_flags.FLAG_JOURNAL]] = "on"
        try:
            from tools import write_tripwire as _wt
            _wt.install(mode=_wt.MODE_ENFORCE, clear=self._clear)
            self._wt = _wt
        except Exception:
            self._wt = None
        return self

    def __exit__(self, *exc):
        if self._wt is not None:
            try:
                self._wt.uninstall()
            except Exception:
                pass
            self._wt = None
        if self._prev_journal is None:
            os.environ.pop(_flags.FLAG_ENV[_flags.FLAG_JOURNAL], None)
        else:
            os.environ[_flags.FLAG_ENV[_flags.FLAG_JOURNAL]] = self._prev_journal
        return False


# ── The choke point ──────────────────────────────────────────────────────────

_SEQ_LOCK = threading.Lock()
_SEQ_CACHE = {}  # str(path) -> last allocated seq


def reset_seq_cache():
    """Drop the per-path seq cache (tests that reuse a data dir call this)."""
    with _SEQ_LOCK:
        _SEQ_CACHE.clear()


def _read_last_seq(path: Path) -> int:
    """The highest ``seq`` already on disk for ``path`` (0 when absent/empty)."""
    try:
        if not path.exists():
            return 0
    except OSError:
        return 0
    last = 0
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except (ValueError, TypeError):
                    continue
                try:
                    s = int(ev.get("seq", 0))
                except (ValueError, TypeError):
                    continue
                if s > last:
                    last = s
    except OSError:
        return last
    return last


def _next_seq(path: Path) -> int:
    """Allocate the next monotonic per-project ``seq`` for ``path``.

    Steady-state O(1): a cached counter incremented under the seq lock. The disk
    is re-read only on a cache miss or when the file is missing (so a deleted
    journal restarts cleanly), keeping the append itself open-append-close.
    """
    key = str(path)
    with _SEQ_LOCK:
        cached = _SEQ_CACHE.get(key)
        exists = False
        try:
            exists = path.exists()
        except OSError:
            exists = False
        if cached is None or not exists:
            nxt = _read_last_seq(path) + 1
        else:
            nxt = cached + 1
        _SEQ_CACHE[key] = nxt
        return nxt


def _validate(event: dict) -> None:
    """Schema-validate an event envelope. Raises :class:`JournalSchemaError`."""
    if not isinstance(event, dict):
        raise JournalSchemaError("event must be a dict")
    missing = [k for k in ENVELOPE_KEYS if k not in event]
    if missing:
        raise JournalSchemaError("event missing envelope fields: %s"
                                 % ", ".join(missing))
    if not isinstance(event["schema_ver"], int) or event["schema_ver"] < 1:
        raise JournalSchemaError("schema_ver must be a positive int")
    if not isinstance(event["seq"], int) or event["seq"] < 1:
        raise JournalSchemaError("seq must be a positive int")
    if not isinstance(event["type"], str) or not event["type"]:
        raise JournalSchemaError("type must be a non-empty str")
    if not isinstance(event["project_id"], str) or not event["project_id"]:
        raise JournalSchemaError("project_id must be a non-empty str")
    if not isinstance(event["correlation_id"], str) or not event["correlation_id"]:
        raise JournalSchemaError("correlation_id must be a non-empty str")
    cause = event["causation_id"]
    if cause is not None and not isinstance(cause, str):
        raise JournalSchemaError("causation_id must be a str or None")
    a = event["actor"]
    if not isinstance(a, dict) or a.get("kind") not in ACTOR_KINDS:
        raise JournalSchemaError(
            "actor must be {kind,id} with kind in %s" % (ACTOR_KINDS,))
    if not isinstance(event["payload"], dict):
        raise JournalSchemaError("payload must be a dict")


def emit(project_id, event_type, *, correlation_id, folder_path=None,
         actor=None, causation_id=None, payload=None, ts=None,
         schema_ver=None) -> dict:
    """Append ONE schema-validated event to a project's journal — the choke point.

    This is the single append path (enforced by :func:`scan_direct_journal_writes`).
    Allocates a monotonic per-project ``seq`` under :data:`paths.WRITE_LOCK`,
    stamps the wall ``ts`` and ``schema_ver``, validates the full Butler
    envelope, and does an O(1) open-append-close of the JSON line (fsync'd when
    :func:`fsync_enabled`). Returns the written event dict.

    Raises :class:`JournalSchemaError` on an invalid envelope — the choke point
    is strict. Call sites that must never let journaling break a real mutation
    use :func:`dual_write`, which wraps this best-effort.

    NB: this always writes when called — the ``journal`` off-switch is policy at
    the call sites (see :func:`dual_write`), not inside the mechanism.
    """
    a = _coerce_actor(actor)
    # Pre-validate the seq-independent inputs BEFORE allocating a seq, so an
    # invalid call never burns a sequence number (keeps seq gap-free).
    if not isinstance(event_type, str) or not event_type:
        raise JournalSchemaError("type must be a non-empty str")
    if not isinstance(project_id, str) or not project_id:
        raise JournalSchemaError("project_id must be a non-empty str")
    if correlation_id is None or str(correlation_id) == "":
        raise JournalSchemaError("correlation_id must be a non-empty str")
    if causation_id is not None and not isinstance(causation_id, str):
        raise JournalSchemaError("causation_id must be a str or None")
    if payload is not None and not isinstance(payload, dict):
        raise JournalSchemaError("payload must be a dict")
    with _paths.WRITE_LOCK:
        path = journal_path(project_id, folder_path=folder_path)
        seq = _next_seq(path)
        event = {
            "schema_ver": int(schema_ver) if schema_ver is not None
            else CURRENT_SCHEMA_VER,
            "seq": seq,
            "ts": float(ts) if ts is not None else time.time(),
            "type": event_type,
            "actor": a,
            "correlation_id": "" if correlation_id is None else str(correlation_id),
            "causation_id": None if causation_id is None else str(causation_id),
            "project_id": "" if project_id is None else str(project_id),
            "event_id": "%s#%d" % ("" if project_id is None else project_id, seq),
            "payload": dict(payload) if payload else {},
        }
        _validate(event)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
            if fsync_enabled():
                f.flush()
                os.fsync(f.fileno())
        return event


# ── The blessed dual-write wrapper (D1) ──────────────────────────────────────

def dual_write(project_id, event_type, legacy_write, *, correlation_id,
               folder_path=None, actor=None, causation_id=None, payload=None):
    """Journal-first-then-legacy dual write — the ONLY sanctioned emit() site.

    1. If the ``journal`` off-switch is OFF → run ONLY ``legacy_write`` (byte-
       identical to pre-journal behavior) and return its result.
    2. Otherwise, under the write-tripwire :func:`pairing`: emit the journal
       event FIRST (best-effort — a journal failure is swallowed so it can never
       prevent the legacy mutation, honoring "alongside, never instead of"),
       then run ``legacy_write`` and return its result.

    A crash between the emit and ``legacy_write`` leaves an orphaned journal
    event that the W14 parity gate classifies as benign journal-ahead intent,
    replayable idempotently — never a lost legacy write. ``legacy_write``'s own
    exceptions propagate to the caller unchanged (the caller keeps its rollback).
    """
    if not enabled():
        return legacy_write()
    with pairing():
        try:
            emit(project_id, event_type, correlation_id=correlation_id,
                 folder_path=folder_path, actor=actor,
                 causation_id=causation_id, payload=payload)
        except Exception:
            # journal-first, but journaling NEVER blocks the legacy mutation.
            pass
        return legacy_write()


# ── emit_safe + the journaled() blessed wrapper (W13) ────────────────────────

def emit_safe(project_id, event_type, *, correlation_id, folder_path=None,
              actor=None, causation_id=None, payload=None):
    """Best-effort, off-switch-gated :func:`emit` — the W13 semantic-event helper.

    Emits ONLY when the ``journal`` flag is on, and NEVER raises: a schema/IO
    failure is swallowed so journaling a mutation-of-record can never break the
    real mutation ("alongside, never instead of"). Returns the written event, or
    ``None`` when the flag is off or the emit failed. Callers that also need the
    write-tripwire pairing for the legacy store write use :class:`journaled`.
    """
    if not enabled():
        return None
    try:
        return emit(project_id, event_type, correlation_id=correlation_id,
                    folder_path=folder_path, actor=actor,
                    causation_id=causation_id, payload=payload)
    except Exception:
        return None


class journaled:
    """The blessed wrapper for a W13 mutation-of-record class — pairing + emit.

    ``with journal.journaled(pid, EV_X, correlation_id=..., folder_path=...,
    payload={...}): <legacy store writes>`` does, on enter, exactly the D1
    journal-first-then-legacy dance for a whole block of legacy writes:

      1. arm the write-tripwire :func:`pairing` for the enclosed writes (so the
         C3 completeness gate treats every ``.anchor/`` mutation inside the block
         as PAIRED — never an unjournaled-mutation violation);
      2. emit the semantic journal event FIRST (best-effort, off-switch-gated via
         :func:`emit_safe`), before the block's legacy writes run.

    With the ``journal`` flag OFF (today's default) the emit is skipped and the
    pairing is an inert no-op (it only matters when the tripwire is installed in
    enforce mode), so the enclosed legacy writes are byte-identical to pre-journal
    behavior. A journal failure never propagates. Nestable (pairing is a counter).
    """

    def __init__(self, project_id, event_type, *, correlation_id,
                 folder_path=None, actor=None, causation_id=None, payload=None):
        self.project_id = project_id
        self.event_type = event_type
        self.correlation_id = correlation_id
        self.folder_path = folder_path
        self.actor = actor
        self.causation_id = causation_id
        self.payload = payload
        self._pair = None
        self.event = None

    def __enter__(self):
        # Gate on the off-switch exactly like :func:`dual_write`: when the
        # journal flag is OFF (today's default) this is fully inert — no pairing
        # is armed and no event is emitted, so the enclosed legacy writes are
        # byte-identical to pre-journal behavior. When ON, arm the pairing (so
        # the enforce gate treats the enclosed .anchor/ writes as paired) and
        # emit the semantic event journal-first, before the legacy writes run.
        if enabled():
            self._pair = pairing()
            self._pair.__enter__()
            self.event = emit_safe(
                self.project_id, self.event_type,
                correlation_id=self.correlation_id, folder_path=self.folder_path,
                actor=self.actor, causation_id=self.causation_id,
                payload=self.payload)
        return self

    def __exit__(self, *exc):
        if self._pair is not None:
            return self._pair.__exit__(*exc)
        return False


# ── Readers (unknown-field-tolerant; schema-evolution rule) ──────────────────

def migrate_event(event: dict) -> dict:
    """Forward-migrate an older-schema event to the current envelope shape.

    Within schema major v1 this is the identity (additive-only — nothing to
    migrate). A future major bump adds its migration steps here; a reader that
    must span a bump calls this to normalise. Unknown fields are preserved.
    """
    return dict(event)


def read_events(project_id, folder_path=None, since_seq=None, path=None) -> list:
    """Read a project's journal events, newest-last, tolerating unknown fields.

    Unknown-field-tolerant per the schema-evolution rule: each line is parsed as
    JSON and returned as-is (extra fields kept; a HIGHER ``schema_ver`` never
    raises); a torn/blank line is skipped. ``since_seq`` (when given) returns
    only events with ``seq`` strictly greater. ``path`` overrides the resolved
    per-project path (tests). Missing journal → ``[]``.
    """
    p = Path(path) if path is not None else journal_path(
        project_id, folder_path=folder_path)
    out = []
    try:
        if not p.exists():
            return out
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except (ValueError, TypeError):
                    continue  # torn tail line — tolerate
                if not isinstance(ev, dict):
                    continue
                if since_seq is not None:
                    try:
                        if int(ev.get("seq", 0)) <= int(since_seq):
                            continue
                    except (ValueError, TypeError):
                        continue
                out.append(ev)
    except OSError:
        return out
    return out


# ── distro.py-style scan: emit() is the ONLY journal write path ──────────────

# A write call whose target expression references a journal path token. The
# scan flags such a line in any PRODUCT module other than journal.py, so nothing
# but emit() can append to a journal.
_JOURNAL_TOKEN_RE = re.compile(
    r"journal\.jsonl|['\"]journal['\"]|journal_path|journal_path_for")
_WRITE_CALL_RE = re.compile(
    # open(<path>, "w"/"a"/"x") — the path arg may be a STRING LITERAL *or* a
    # variable/expression: match up to the write-mode SECOND arg. A first-arg-
    # must-be-a-string-literal form (the earlier pattern) silently missed the
    # most natural direct write, ``open(journal_path, "w")``.
    r"open\s*\([^)]*,\s*['\"][wax]"
    r"|\.write_text\s*\("
    r"|\.write_bytes\s*\("
    r"|json\.dump\s*\(")

#: Directories/files the scan does not police (dev-only or the module itself).
_SCAN_SKIP_DIRS = ("__pycache__", ".git", ".pytest_cache", "tests", "vendor",
                   "_archive", "planning", "docs", "starter", "static",
                   "health_reports", "logs", "_mockups", "_prototypes",
                   "_devtest", "anchor_test", "rnd_jobs")
#: journal.py is the module; the tripwire legitimately NAMES the journal file in
#: its allowlist constants (it never writes one).
_SCAN_SKIP_FILES = ("journal.py",)


def _line_is_forbidden_journal_write(line: str) -> bool:
    """True when a source line both writes AND targets a journal path.

    The predicate is the unit of the scan: a line that opens-for-write /
    ``write_text`` / ``write_bytes`` / ``json.dump``s to something spelled like a
    journal path is a forbidden direct journal write (only :func:`emit` may).
    """
    if not _JOURNAL_TOKEN_RE.search(line):
        return False
    return bool(_WRITE_CALL_RE.search(line))


def scan_direct_journal_writes(repo_root=None) -> list:
    """Scan product ``.py`` files for a direct journal write outside emit().

    distro.py-style: returns a list of ``(rel, "direct-journal-write", snippet)``
    hits — EMPTY when clean (the invariant W12 locks: :func:`emit` is the only
    journal write path). Skips dev-only trees (:data:`_SCAN_SKIP_DIRS`), the
    vendored code, and ``journal.py`` itself.
    """
    root = Path(repo_root) if repo_root else REPO_ROOT
    hits = []
    for p in sorted(root.rglob("*.py")):
        rel = p.relative_to(root).as_posix()
        parts = set(rel.split("/"))
        if parts & set(_SCAN_SKIP_DIRS):
            continue
        if p.name in _SCAN_SKIP_FILES:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if _line_is_forbidden_journal_write(line):
                snip = line.strip()
                hits.append((rel, "direct-journal-write",
                             f"line {i}: {snip[:80]}"))
    return hits
