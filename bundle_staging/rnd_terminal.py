#!/usr/bin/env python3
"""Anchor R&D interactive terminal — persistent stream-json REPL (Wave 7).

The v2 terminal substrate (MASTER-PLAN §E) is NOT a native ConPTY terminal
(that would need a compiled dependency, violating Anchor's stdlib-only / no
native-asset rule). Instead it keeps the terminal *feel* over a **persistent
``stream-json`` REPL**: ONE long-lived ``claude``/``gemini`` process per terminal
session, auto-seeded with the lane's trio skill (research→researchPrime,
plan→crucible, build→foreman), with user turns POSTed onto the live process's
stdin and assistant output streamed back over SSE. It generalizes — never forks —
the existing job-runner stdin mechanism used by the gate adapter.

This module is a thin orchestration layer ON TOP of ``job_runner`` + ``lanes`` +
``gate_adapter``; it does not reimplement process management, stdin wiring, or
output capture. A *terminal session* is just a long-lived ``job_runner`` job:

- :func:`start_terminal` resolves the project + lane, computes the project-scoped
  output dir (reusing ``lanes.lane_output_dir``), seeds the lane skill prompt
  (``lanes.build_prompt_seed``), and launches a persistent job via
  ``job_runner.launch_guarded`` with the stdin pipe kept OPEN (``gated`` = the
  lane name) so subsequent turns can be written. The initial seed is delivered as
  the job's first stream-json user turn (job_runner does this) so the skill is
  invoked the moment the session starts.
- :func:`send_turn` writes ONE stream-json user turn onto the live process stdin
  by REUSING ``gate_adapter.answer`` semantics' lower-level sink — specifically
  the SAME stdin-sink registry the gate adapter registers at launch. It does NOT
  fork the gate/stdin code: it resolves the registered sink via
  ``gate_adapter._get_stdin_sink`` and writes the identical user-text envelope
  ``gate_adapter._format_turn`` produces.
- :func:`read_since` returns incremental output via ``job_runner.tail`` (the
  durable-log-backed cursor read; long-poll-safe).
- :func:`discover_produced` scans the session's output dir for files produced
  during the run and returns an *adoption proposal* (a session-grouping preview)
  the UI confirms. On confirm, :func:`adopt_produced` records those files as a
  RUN session under the lane (reusing the Wave-1 session model + Wave-2 adopt
  paths via ``effort_history.record_effort`` keyed by the terminal job_id) so the
  produced docs appear as ONE session in the lane.

Stdlib only. No third-party imports. No native/ConPTY dependency.
"""

import html as _html
import json
import os
import time
import uuid
from pathlib import Path

import paths as _paths
import rnd_registry as _rnd
import lanes as _lanes
import job_runner as _jr
import gate_adapter as _gate
import sessions as _sessions
import effort_history as _eh

# ── Constants ────────────────────────────────────────────────────────────────

#: SSE event names emitted by the stream endpoint (see anchor_gui term_stream).
SSE_EVENT_OUTPUT = "output"
SSE_EVENT_STATUS = "status"
SSE_EVENT_GATE = "gate"
SSE_EVENT_DONE = "done"
SSE_EVENT_HEARTBEAT = "heartbeat"

#: Maximum size (in characters) of a single user turn. A turn larger than this is
#: rejected with a clean error rather than written — guards against a runaway
#: paste pinning the live process's stdin. ~100 KB is well above any sane prompt.
MAX_TURN_CHARS = 100_000

#: A terminal session IS a job_runner job; we reuse its terminal-status set so a
#: caller never has to import two modules to know a session ended.
TERMINAL_STATUSES = _jr.TERMINAL_STATUSES


# ── Start a terminal session ─────────────────────────────────────────────────

def start_terminal(project_id, lane, backend=_jr.DEFAULT_BACKEND,
                   env=None, job_id=None, extra_args=None):
    """Start a PERSISTENT interactive terminal session for a project lane.

    Resolves the project + lane (reusing the Wave-6 lane wiring), seeds the
    lane's trio skill, and launches ONE long-lived ``stream-json`` job with its
    stdin pipe kept open so turns can be sent. The lane skill is auto-invoked via
    the seed delivered as the job's first stream-json user turn (job_runner).

    Returns the augmented job record (``{job_id, lane, skill, output_dir,
    backend, status, ...}``) — the ``job_id`` is the terminal *session id*.

    Mirrors ``lanes.launch_lane`` deliberately (skill seed + project-scoped
    output dir + engine policy + concurrency policy) but ALWAYS keeps stdin open
    (``gated`` = lane) because a terminal is interactive even for research.

    Raises ``KeyError`` (unknown project), ``lanes.EngineNotAllowedError``
    (engine policy), or ``job_runner.LaneBusyError`` (concurrency policy).
    """
    backend = backend or _jr.DEFAULT_BACKEND
    ld = _lanes.get_lane(lane)                     # KeyError for an invalid lane
    _lanes.check_engine_allowed(lane, backend)     # engine policy
    project = _rnd.get_project(project_id)
    if project is None:
        raise KeyError(project_id)
    folder_path = project.get("folder_path", "")

    output_dir = _lanes.lane_output_dir(folder_path, project_id, lane)
    _rnd.scaffold_project_store(folder_path, project_id)
    output_dir.mkdir(parents=True, exist_ok=True)

    prompt_seed = _lanes.build_prompt_seed(lane, project, output_dir)
    # A terminal is interactive on EVERY lane, so we always keep stdin open by
    # passing a truthy ``gated`` (the lane name). For plan/build this also enables
    # the runner's live-stream gate parsing (gate_adapter) exactly as launch_lane;
    # for research it just keeps the pipe open for turns (the runner picks the
    # acceptEdits permission mode, correct for non-mutating research).
    gated = ld.lane

    # Snapshot the output-dir contents BEFORE launching the process so the
    # pre-run snapshot reflects the dir state prior to ANY process writes
    # (launch-then-snapshot is a race: the engine could write a file in the
    # window between launch and snapshot, hiding it from discover_produced). The
    # job_id is allocated here so the snapshot can be keyed by it up front
    # (job_runner uses uuid4().hex; pre-allocating one and passing it through
    # launch_guarded keeps the snapshot key and the launched job_id identical).
    jid = job_id or uuid.uuid4().hex
    _snapshot_output_dir(output_dir, jid)

    rec = _jr.launch_guarded(
        lane, project_id=project_id, folder_path=folder_path,
        cwd=folder_path or None, extra_args=extra_args, env=env,
        job_id=jid, backend=backend, prompt=prompt_seed,
        output_dir=output_dir, gated=gated,
    )
    jid = rec["job_id"]

    # Augment + persist the record with terminal metadata for the UI/history.
    rec = _jr._update_record(
        jid,
        skill=ld.skill,
        output_dir=str(output_dir),
        gates=ld.gates,
        mutates_tree=ld.mutates_tree,
        backend=backend,
        terminal=True,
        prompt_seed=prompt_seed,
    )
    return rec


# ── Send a turn (writes onto the live stdin — reuses gate_adapter's sink) ─────

def send_turn(session_id, text):
    """Write ONE stream-json user turn onto the live session's stdin.

    REUSES (does not fork) the job-runner/gate-adapter stdin mechanism: it
    resolves the SAME stdin sink ``gate_adapter`` registered at launch
    (``gate_adapter._get_stdin_sink``) and writes the identical user-text
    envelope ``gate_adapter._format_turn`` produces. The write happens under
    ``paths.WRITE_LOCK`` so it cannot interleave with a concurrent gate answer
    writing into the same pipe.

    Returns ``True`` if the turn was written; ``False`` for an unknown/terminal
    session, an empty/whitespace-only turn, an oversized turn (> ``MAX_TURN_CHARS``),
    a dead/closed stdin, or when no writable stdin sink is available. All rejection
    paths are clean (nothing is written and nothing is raised) — special chars
    (newlines/quotes/unicode) keep working because the text is enveloped by
    ``gate_adapter._format_turn``, not interpolated.
    """
    rec = _jr.load_record(session_id)
    if rec is None:
        return False
    if rec.get("status") in _jr.TERMINAL_STATUSES:
        return False
    # Reject an empty/whitespace-only turn cleanly (a no-op write would otherwise
    # push an empty user envelope that the engine can choke on).
    if text is None or not str(text).strip():
        return False
    # Cap the turn size so a runaway paste can't pin the live process's stdin.
    if len(str(text)) > MAX_TURN_CHARS:
        return False
    payload = _gate._format_turn(text)
    with _paths.WRITE_LOCK:
        sink = _gate._get_stdin_sink(session_id)
        if sink is None:
            return False
        # If the underlying stdin is already gone (process exited, pipe closed),
        # bail cleanly rather than throwing on the write.
        if getattr(sink, "closed", False):
            return False
        try:
            sink.write(payload)
            try:
                sink.flush()
            except Exception:
                pass
        except (OSError, ValueError):
            return False
    return True


# ── Cancel a terminal session (tab-close reaping / explicit stop) ────────────

def cancel_terminal(session_id):
    """Cancel a terminal session, tree-killing its persistent process.

    Thin delegation to ``job_runner.cancel`` (a terminal session IS a job): it
    reaps the full process tree (``taskkill /T /F`` on Windows / process-group
    kill on POSIX) and marks the job ``cancelled``. This is the clean reap path
    used when the user closes the tab WITHOUT adopting — a persistent interactive
    process otherwise waits for input forever (a leak). An already-terminal or
    unknown session is tolerated.

    Returns the updated job record, or ``None`` for an unknown session.
    """
    rec = _jr.load_record(session_id)
    if rec is None:
        return None
    # Already finished — nothing to kill; return the record as-is (idempotent).
    if rec.get("status") in _jr.TERMINAL_STATUSES:
        return rec
    return _jr.cancel(session_id)


# ── Incremental read ─────────────────────────────────────────────────────────

def read_since(session_id, cursor=0):
    """Return output produced AFTER ``cursor`` for a terminal session.

    Thin wrapper over ``job_runner.tail`` (durable-log-backed, cursor-stable).
    Returns ``{lines, next, total, status, pending_prompt}`` — ``pending_prompt``
    surfaces an in-session gate (plan/build) so the terminal can render it inline.
    """
    out = _jr.tail(session_id, cursor)
    try:
        pending = _gate.load_pending_prompt(session_id)
    except Exception:
        pending = None
    out = dict(out)
    out["pending_prompt"] = pending
    return out


# ── Output-dir snapshotting (so discover_produced reports only new files) ─────

def _snapshot_name(job_id):
    return f".terminal-snapshot-{job_id}.json"


def _scan_output_files(output_dir):
    """Return ``{rel_posix: mtime}`` for every regular file under ``output_dir``.

    Excludes Anchor's own bookkeeping (pointer-records, indexes, snapshots,
    launch records) so only genuine engine-produced docs are proposed.
    """
    out = {}
    base = Path(output_dir)
    if not base.exists():
        return out
    for p in base.rglob("*"):
        if not p.is_file():
            continue
        name = p.name
        if name.startswith(".terminal-snapshot-"):
            continue
        if name in (_lanes.LAUNCH_RECORD_NAME, _sessions.OVERRIDES_NAME):
            continue
        if name.endswith(".pointer.json") or name == "index.json":
            continue
        # Skip Anchor's per-effort pointer dir contents (efforts live under the
        # lane store dir; produced docs are the engine's own files).
        try:
            rel = p.relative_to(base).as_posix()
        except ValueError:
            continue
        try:
            out[rel] = p.stat().st_mtime
        except OSError:
            continue
    return out


def _snapshot_output_dir(output_dir, job_id):
    """Persist a pre-run snapshot of ``output_dir`` keyed by ``job_id``."""
    snap = _scan_output_files(output_dir)
    p = Path(output_dir) / _snapshot_name(job_id)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _load_snapshot(output_dir, job_id):
    p = Path(output_dir) / _snapshot_name(job_id)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


# ── Discover produced files → adoption proposal ──────────────────────────────

def _title_for(rel):
    """A human title for a produced file (first markdown H1, else the stem)."""
    return Path(rel).stem.replace("_", " ").replace("-", " ").strip() or rel


def _kind_for(rel):
    low = rel.lower()
    if "master" in low:
        return "master-plan"
    if "implementation" in low or "impl" in low:
        return "implementation-plan"
    if "report" in low:
        return "report"
    return "doc"


def discover_produced(session_id):
    """Scan the session's output dir on exit → an ADOPTION PROPOSAL.

    Compares the current output-dir contents against the pre-run snapshot taken
    at :func:`start_terminal` and returns the set of files this session produced
    or modified, packaged as a proposal the UI confirms:

        {
          "session_id": <job_id>,
          "project_id", "lane", "skill", "output_dir",
          "produced": [{"rel", "title", "kind", "mtime"}, ...],
          "adoptable": <bool>,   # at least one produced file
        }

    Returns ``None`` for an unknown session. Reuses the project/lane resolution
    already stamped on the job record at launch.
    """
    rec = _jr.load_record(session_id)
    if rec is None:
        return None
    output_dir = rec.get("output_dir") or ""
    project_id = rec.get("project_id") or ""
    lane = rec.get("lane") or ""
    skill = rec.get("skill") or ""
    before = _load_snapshot(output_dir, session_id)
    after = _scan_output_files(output_dir)
    produced = []
    for rel, mtime in sorted(after.items()):
        prev = before.get(rel)
        # New file, or modified since the snapshot (mtime advanced).
        if prev is None or float(mtime) > float(prev) + 1e-6:
            # HTML-escape the display-facing rel/title/kind so a filename with
            # HTML metacharacters (e.g. ``<x>&'".md``) round-trips safely into
            # the session record / confirm panel even though the frontend also
            # uses textContent. ``rel_raw`` keeps the real on-disk path so
            # adopt_produced can still resolve the actual file.
            produced.append({
                "rel": _html.escape(rel, quote=True),
                "rel_raw": rel,
                "title": _html.escape(_title_for(rel), quote=True),
                "kind": _html.escape(_kind_for(rel), quote=True),
                "mtime": mtime,
            })
    return {
        "session_id": session_id,
        "project_id": project_id,
        "lane": lane,
        "skill": skill,
        "output_dir": output_dir,
        "produced": produced,
        "adoptable": bool(produced),
    }


def adopt_produced(session_id, proposal=None):
    """Adopt a session's produced files as ONE RUN session in the lane.

    On user-confirm, records the produced files as a single RUN effort keyed by
    the terminal ``session_id`` (the job_id) — so the Wave-1 session model groups
    them into ONE session (run efforts group by job_id) and the Wave-4 lane
    rendering shows them as a single most-recent card. The pointer-record carries
    the produced files' relative paths under ``produced_files`` and a representative
    ``artifact_path`` (the first produced file) so the report viewer + summarizer
    can resolve them.

    ``proposal`` may be supplied (e.g. the one the UI already showed); otherwise
    it is recomputed via :func:`discover_produced`. Returns the recomputed session
    record for the lane (the one matching this job_id), or ``None`` if there was
    nothing to adopt / the session is unknown.
    """
    rec = _jr.load_record(session_id)
    if rec is None:
        return None
    if proposal is None:
        proposal = discover_produced(session_id)
    if not proposal or not proposal.get("adoptable"):
        return None
    project_id = proposal["project_id"]
    lane = proposal["lane"]
    skill = proposal.get("skill") or ""
    folder_path = rec.get("folder_path")
    if not folder_path:
        proj = _rnd.get_project(project_id)
        folder_path = (proj or {}).get("folder_path", "")
    produced = proposal.get("produced") or []
    # The lane subdir the engine wrote into (research/planning/build/...).
    store_lane = lane or _eh._resolve_subdir(rec.get("lane") or "")
    rep = produced[0]
    # Prefer the RAW (unescaped) rel path for on-disk resolution; the escaped
    # ``rel``/``title``/``kind`` are display-only (see discover_produced). Falling
    # back to ``rel`` keeps a caller-supplied legacy proposal (no rel_raw) working.
    extra = {
        "source": _eh.SOURCE_RUN,
        "kind": rep.get("kind", "doc"),
        "title": rep.get("title", ""),
        # artifact_path is relative to the lane store dir (where the engine wrote);
        # discover_produced rel paths are already relative to that output dir.
        "artifact_path": rep.get("rel_raw") or rep.get("rel", ""),
        "produced_files": [(p.get("rel_raw") or p.get("rel", "")) for p in produced],
        "status": "done",
        "terminal_adopted": True,
        "output_dir": proposal.get("output_dir", ""),
    }
    _eh.record_effort(folder_path, project_id, store_lane, session_id,
                      skill=skill, prompt_seed=rec.get("prompt_seed"),
                      extra=extra)
    # Return the recomputed session (Wave-1 grouping) matching this job_id.
    for s in _sessions.list_sessions(folder_path, project_id, store_lane):
        if s.get("session_id") == f"run::{session_id}":
            return s
        for m in s.get("member_files", []):
            if m.get("job_id") == session_id:
                return s
    return None
