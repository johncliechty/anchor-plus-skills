#!/usr/bin/env python3
"""Anchor managed-terminal session registry — durable, id-keyed (stdlib only).

v3 "Mission Control" (MASTER-PLAN §D / §I, Implementation-Plan Wave 2). A
DURABLE registry of managed terminal sessions that **survives a server restart**:
it is persisted as JSON under the ``.anchor/`` data dir (resolved via
``paths.data_dir()`` — NEVER hard-coded), so on reconnect the dashboard can
reflect true live state.

A session record models::

    {session_id, project_id, lane, backend ("claude"|"gemini"),
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
import os
import time
import uuid
from pathlib import Path

import paths as _paths

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

#: Every recognized status.
VALID_STATUSES = {
    STATUS_RUNNING,
    STATUS_NEEDS_ATTENTION,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_IDLE,
    STATUS_CANCELLED,
}

#: Terminal statuses — a session in one of these has no live process and is
#: never "running". (``idle`` is non-running too, but it is the parked/recovered
#: state rather than a finished one.)
TERMINAL_STATUSES = frozenset((STATUS_DONE, STATUS_FAILED))

#: Recognized backends.
BACKEND_CLAUDE = "claude"
BACKEND_GEMINI = "gemini"
VALID_BACKENDS = {BACKEND_CLAUDE, BACKEND_GEMINI}


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


def load_sessions() -> dict:
    """Load the session registry as a dict ``{session_id: record}``.

    Best-effort: returns an empty dict if the store does not exist or is
    unreadable/corrupt (a corrupt registry must never crash the dashboard). The
    JSON on disk is a list of records; this returns them keyed by ``session_id``
    for O(1) lookup. A keyed-dict form on disk is also tolerated.
    """
    p = sessions_path()
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError):
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
    }


def _save_sessions(reg: dict) -> None:
    """Persist the registry (dict keyed by id) as a JSON list, atomically.

    Runs under ``paths.WRITE_LOCK`` (matching ``rnd_registry``). Writes to a
    temp file in the same directory then ``os.replace`` over the target so a
    crash mid-write can never leave a truncated/corrupt store (durability
    discipline). Ensures the ``.anchor/`` dir exists first.
    """
    with _paths.WRITE_LOCK:
        d = anchor_dir()
        d.mkdir(parents=True, exist_ok=True)
        items = [reg[k] for k in reg]
        target = sessions_path()
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(
            json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        os.replace(str(tmp), str(target))


# ── CRUD ──────────────────────────────────────────────────────────────────

def register_session(project_id, lane, backend=BACKEND_CLAUDE,
                     worktree_path="", branch="", status=STATUS_IDLE,
                     label="", session_id=None, parent_session_id="",
                     chain_id=None, grass_origin="",
                     effort_id=None, effort_managed=False,
                     pid=None, proc_create_time=None, crypt_token="") -> dict:
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
        })
        reg[sid] = record
        _save_sessions(reg)
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
        _save_sessions(reg)
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
               "pid", "proc_create_time", "crypt_token"}
    with _paths.WRITE_LOCK:
        reg = load_sessions()
        if session_id not in reg:
            raise KeyError(session_id)
        rec = dict(reg[session_id])
        for k, v in fields.items():
            if k in allowed and v is not None:
                rec[k] = v
        rec = _normalize(rec)
        rec["session_id"] = session_id
        reg[session_id] = rec
        _save_sessions(reg)
        return rec


def remove_session(session_id: str) -> bool:
    """Hard-delete a session record from the registry. Returns success."""
    with _paths.WRITE_LOCK:
        reg = load_sessions()
        if session_id in reg:
            del reg[session_id]
            _save_sessions(reg)
            return True
        return False


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
            _save_sessions(reg)
        report["marked"] = marked
        report["applied"] = True
    return report
