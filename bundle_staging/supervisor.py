#!/usr/bin/env python3
"""Anchor supervisor seam — job ownership behind ANCHOR_SUPERVISOR (rearch W15).

The fourth pillar (Master Plan Phase 5; D2): spawned lane jobs are owned behind
an ``ANCHOR_SUPERVISOR=inline|external`` seam so the dashboard can restart
WITHOUT killing in-flight jobs or terminals. W15 lands the SEAM + the fully
wired **inline** (in-process) implementation — the owner used by the test suite,
the daily healthcheck, and as the honest *degraded fallback* when the external
supervisor is unavailable. W16 stands up the real external second process
(its own NSSM service, loopback token-authed IPC) behind the SAME seam.

This module is ALSO the single source of truth for two checked-in gate
artifacts, authored BEFORE the code they govern (the W1/W3 pattern — a module
owns the data, a renderer writes the reviewable ``.md``):

  * the **IPC contract table** (:data:`IPC_CONTRACT`): every dashboard↔job
    interaction (launch · tail-since · tail-cursor-durability · cancel ·
    gate-answer · cost/rollup · swarm-register) with its *state owner*,
    *idempotency key*, and *defined behavior when EITHER side restarts
    mid-interaction*. Rendered to ``planning/rearch-2026-07/IPC-CONTRACT.md``.
  * the **in-memory-structure rebuild table** (:data:`REBUILD_TABLE`): every
    dashboard-side structure (``_LIVE``, ``_JOB_DIRS``, ``_ACTIVE_LANE``,
    ``_FOLDER_BUILD``, lane locks, SSE attach points) with a *rebuild-source*
    column (``durable record`` | ``supervisor query`` | ``re-derived``). ZERO
    rows may be unresolved. Rendered to
    ``planning/rearch-2026-07/REBUILD-TABLE.md``.

The seam's ownership operations delegate to :mod:`job_runner` (launch / tail /
cancel / liveness) and :mod:`gate_adapter` (the durable gate-answer path). The
inline implementation IS the dashboard process, so a "supervisor query" is a
local re-derivation from the durable records; the cross-process live survival
(a real ``nssm restart anchor`` mid-job) is W16's two live probes.

Stdlib only. No third-party imports.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
from pathlib import Path

import pillar_flags as _pf
import job_runner as _jr
import gate_adapter as _ga

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_ARTIFACT_DIR = REPO_ROOT / "planning" / "rearch-2026-07"

#: Supervisor modes (mirror the ``supervisor`` pillar flag values).
MODE_INLINE = "inline"
MODE_EXTERNAL = "external"

# ── External-process IPC configuration (W16) ─────────────────────────────────
#: Loopback host the supervisor binds / the client dials. NEVER the tailnet — a
#: job-owning IPC surface stays on 127.0.0.1 (the same discipline as
#: ``preview_server``). Overridable only for tests.
SUPERVISOR_HOST_ENV = "ANCHOR_SUPERVISOR_HOST"
SUPERVISOR_PORT_ENV = "ANCHOR_SUPERVISOR_PORT"
SUPERVISOR_TOKEN_ENV = "ANCHOR_SUPERVISOR_TOKEN"
SUPERVISOR_URL_ENV = "ANCHOR_SUPERVISOR_URL"

DEFAULT_SUPERVISOR_HOST = "127.0.0.1"
#: The supervisor's fixed IPC port (distinct from the dashboard's 8777 and the
#: ledger's 8778). A test binds port 0 (OS-assigned) instead.
DEFAULT_SUPERVISOR_PORT = 8781

#: CreateProcess flag: a child spawned with this BREAKS AWAY from the parent's
#: Win32 Job Object, so a supervisor restart (which closes the supervisor's
#: KILL_ON_JOB_CLOSE job handle) does NOT kill the in-flight job — the W16
#: "job-object breakaway" live probe. 0 / ignored off Windows.
CREATE_BREAKAWAY_FROM_JOB = 0x01000000 if os.name == "nt" else 0

#: Short connect/read timeout for the client → supervisor loopback hops. A hop
#: that can't answer inside this bound is treated as "supervisor down" and the
#: seam degrades to inline (never hangs the dashboard on a wedged supervisor).
DEFAULT_IPC_TIMEOUT = 5.0


class SupervisorUnavailable(RuntimeError):
    """The requested supervisor backend is not available.

    Raised only when an ``external`` supervisor is requested but no external
    process can be reached AND a degraded inline fallback is explicitly refused.
    The default factory NEVER raises this — it degrades to inline (the honest
    "supervisor is down" behavior; W16 provides the real external process).
    """


# ── The IPC contract table (source of truth; rendered to IPC-CONTRACT.md) ─────
#
# Each row is one dashboard↔job interaction. Columns:
#   interaction     — the operation name.
#   state_owner     — who owns the authoritative state for this interaction.
#   idempotency_key — the key that makes a retry safe (never doubled).
#   dashboard_down  — defined behavior when the DASHBOARD side restarts
#                     mid-interaction.
#   job_down        — defined behavior when the JOB/SUPERVISOR side dies
#                     mid-interaction.
#   seam_method     — the Supervisor method that implements it.

def _c(interaction, state_owner, idempotency_key, dashboard_down, job_down,
       seam_method):
    return {
        "interaction": interaction,
        "state_owner": state_owner,
        "idempotency_key": idempotency_key,
        "dashboard_down": dashboard_down,
        "job_down": job_down,
        "seam_method": seam_method,
    }


IPC_CONTRACT = (
    _c("launch",
       "supervisor (owns the OS subprocess); durable job record on disk",
       "job_id (caller-supplied or minted once; a relaunch links relaunch_of)",
       "The durable record already carries status=running + pid; on restart "
       "the seam re-adopts it via rebuild() — the SAME job_id is listed "
       "running, never a duplicate spawn.",
       "reconcile_on_startup marks a dead-but-running record `interrupted`; "
       "relaunch() re-drives it from the durable relaunch_spec in one call.",
       "launch_guarded / launch"),
    _c("tail-since",
       "durable per-job log file (append-only) + in-memory ring",
       "since (line index; the log is the stable cursor space)",
       "Tailing is stateless — after restart tail(job_id, since) reads the "
       "durable log from the same index; the cursor keeps advancing.",
       "The durable log survives; a partially-written final line is tolerated "
       "(the reader appends whole lines only).",
       "tail"),
    _c("tail-cursor-durability",
       "durable per-job read-offset file in the job dir (<job_id>.cursor.json)",
       "job_id (the offset is a single last-read index, overwrite-idempotent)",
       "The persisted read offset is re-loaded after restart so a client "
       "resumes exactly where it left off (survives a SUPERVISOR restart — "
       "W16 lives here too).",
       "The offset file is written atomically (tmp+replace); a torn write "
       "falls back to offset 0 (re-reads, never skips).",
       "read_cursor / persist_cursor / tail(persist=True)"),
    _c("cancel",
       "supervisor (owns the process tree); durable record is authoritative",
       "job_id (status→cancelled set FIRST, then tree-kill; re-cancel no-ops)",
       "The record already reads `cancelled`; a repeated cancel is a clean "
       "no-op (tolerates an already-gone process).",
       "cancel sets the terminal status even if the process raced to exit, so "
       "an external cancel is honestly recorded.",
       "cancel"),
    _c("gate-answer",
       "durable gate file in the job dir (<job_id>.gate.json)",
       "tool_use_id / job_id + the delivered_at + gate_consumed markers",
       "The answer is durably QUEUED + ACKed to the job dir BEFORE the POST "
       "returns; on restart deliver_queued_answer replays it exactly once.",
       "A hop killed after the ACK but before the stdin write leaves the "
       "answer QUEUED (answered, not delivered); a retry delivers it exactly "
       "once — never lost, never doubled (delivered_at guard).",
       "answer_gate / deliver_gate"),
    _c("cost/rollup",
       "durable job record (`cost` block, stamped by the reader at finalize)",
       "job_id (the terminal result envelope is captured once; last wins)",
       "Cost is read from the durable record; a restart re-reads it, and the "
       "effort rollup de-dupes by (store_lane, job_id).",
       "A job that finalized before the restart already stamped its cost; an "
       "interrupted job carries whatever partial result envelope it emitted.",
       "load_job / list_jobs"),
    _c("swarm-register",
       "session_registry record minted at spawn with the job identity "
       "(pid / proc_create_time / crypt_token)",
       "session_id == job_id (register is keyed by it; re-register overwrites "
       "the same row)",
       "The registry row is durable; rebuild() reconciles a dead `running` "
       "row by process liveness so the zombie-hunter never sees a false "
       "orphan after a restart.",
       "The finalize/cancel path mirrors the terminal status onto the row "
       "(the finally-reset); a missed mirror is reconciled on next boot.",
       "rebuild / reconcile"),
)


# ── The in-memory-structure rebuild table (source of truth) ───────────────────
#
# Each dashboard-side in-memory structure with WHERE its content is rebuilt from
# after a dashboard restart. A row is UNRESOLVED iff its `source` is empty or
# names no real rebuild path — the W15 gate forbids that.

SOURCE_DURABLE = "durable record"
SOURCE_QUERY = "supervisor query"
SOURCE_DERIVED = "re-derived"

#: The recognized (= resolved) rebuild sources. Any row whose source is not one
#: of these is UNRESOLVED and fails :func:`unresolved_rebuild_rows`.
RESOLVED_SOURCES = (SOURCE_DURABLE, SOURCE_QUERY, SOURCE_DERIVED)


def _r(structure, owner, source, rebuild_note):
    return {
        "structure": structure,
        "owner": owner,
        "source": source,
        "rebuild_note": rebuild_note,
    }


REBUILD_TABLE = (
    _r("job_runner._LIVE",
       "dashboard (this process)",
       SOURCE_DURABLE,
       "Not repopulated with Popen handles across a restart (the subprocess is "
       "owned by the supervisor); the durable record + pid liveness are the "
       "cross-restart truth. Tail/liveness fall back to the durable log."),
    _r("job_runner._JOB_DIRS",
       "dashboard (this process)",
       SOURCE_DERIVED,
       "Launch-time storage pin; re-derived per job_id from the live data dir "
       "on demand (_jobs_dir_for falls back to jobs_dir() for non-owned jobs)."),
    _r("job_runner._ACTIVE_LANE",
       "dashboard concurrency policy",
       SOURCE_DURABLE,
       "Rebuilt by scanning durable records for still-running (project_id, "
       "lane) holders whose pid is alive — rebuild() repopulates the slot so "
       "same-lane serialization survives a restart."),
    _r("job_runner._FOLDER_BUILD",
       "dashboard concurrency policy",
       SOURCE_DURABLE,
       "Rebuilt from durable running BUILD records (folder_path→job_id) whose "
       "pid is alive, so the folder-build lock survives a restart."),
    _r("lane locks (WRITE_LOCK critical sections)",
       "dashboard (paths.WRITE_LOCK)",
       SOURCE_DERIVED,
       "Process-local threading lock — re-created fresh on start; it guards "
       "the durable stores, which are the cross-restart truth. Nothing to "
       "carry across a restart."),
    _r("gate_adapter._SINKS (SSE / stdin attach points)",
       "dashboard (this process)",
       SOURCE_QUERY,
       "Live stdin pipes/attach points are process-local and are NOT carried; "
       "a reattaching client re-establishes the sink, and a queued gate answer "
       "is delivered via deliver_queued_answer once a sink exists again."),
)


# ── Doc renderers (checked-in gate artifacts) ─────────────────────────────────

def render_ipc_contract_md() -> str:
    """Render the IPC contract table as the checked-in ``IPC-CONTRACT.md``."""
    lines = [
        "# IPC contract — dashboard ↔ job interactions (rearch W15)",
        "",
        "Generated by `supervisor.write_ipc_contract_doc()` — the module "
        "`supervisor.py` (`IPC_CONTRACT`) is the single source of truth; this "
        "doc is its reviewable rendering, refreshed mechanically by the W15 "
        "gate, never hand-edited.",
        "",
        "The supervisor pillar (`ANCHOR_SUPERVISOR=inline|external`) owns "
        "spawned lane jobs behind a seam so the dashboard can restart without "
        "killing in-flight work. Every interaction below declares its state "
        "owner, the idempotency key that makes a retry safe, and the defined "
        "behavior when EITHER side restarts mid-interaction.",
        "",
        "| interaction | state owner | idempotency key | dashboard restarts "
        "mid-interaction | job/supervisor dies mid-interaction | seam method |",
        "|---|---|---|---|---|---|",
    ]
    for row in IPC_CONTRACT:
        lines.append(
            f"| **{row['interaction']}** | {row['state_owner']} | "
            f"`{row['idempotency_key']}` | {row['dashboard_down']} | "
            f"{row['job_down']} | `{row['seam_method']}` |")
    lines += [
        "",
        "## The seam",
        "",
        "`supervisor.get_supervisor(env=)` resolves the `ANCHOR_SUPERVISOR` "
        "flag to a `Supervisor`:",
        "",
        "- **inline** — the in-process owner (`InlineSupervisor`) used by the "
        "test suite, the healthcheck, and as the degraded fallback. It "
        "delegates ownership to `job_runner` / `gate_adapter`.",
        "- **external** — the real second process (W16). Until it exists, the "
        "factory DEGRADES to inline with `degraded=True` + a reason, so the "
        "seam always works and the 'supervisor is down' behavior is honest.",
        "",
        "The gate-answer row is the keystone: an answer is **durably queued + "
        "ACKed to the job dir before the POST returns**, and the stdin write "
        "happens supervisor-side against the handle it owns. A hop killed "
        "between the ACK and the write leaves the answer queued; a retry "
        "delivers it exactly once (the `delivered_at` guard).",
        "",
    ]
    return "\n".join(lines)


def render_rebuild_table_md() -> str:
    """Render the in-memory-structure rebuild table (``REBUILD-TABLE.md``)."""
    unresolved = unresolved_rebuild_rows()
    lines = [
        "# In-memory-structure rebuild table (rearch W15)",
        "",
        "Generated by `supervisor.write_rebuild_table_doc()` — the module "
        "`supervisor.py` (`REBUILD_TABLE`) is the single source of truth. Every "
        "dashboard-side in-memory structure names WHERE its content is rebuilt "
        "from after a dashboard restart. A row is UNRESOLVED iff its source is "
        "empty or unrecognized; the W15 gate forbids any unresolved row before "
        "EXECUTE.",
        "",
        f"**Unresolved rows: {len(unresolved)}** "
        f"(gate requires 0).",
        "",
        "| structure | owner | rebuild source | rebuild note |",
        "|---|---|---|---|",
    ]
    for row in REBUILD_TABLE:
        lines.append(
            f"| `{row['structure']}` | {row['owner']} | "
            f"**{row['source']}** | {row['rebuild_note']} |")
    lines += [
        "",
        "Rebuild sources: **durable record** (re-derived from the on-disk job "
        "record / registry), **supervisor query** (asked of the owning "
        "supervisor — inline = a local re-derivation), **re-derived** "
        "(reconstructed on demand; nothing to carry across a restart).",
        "",
        "`supervisor.get_supervisor().rebuild()` repopulates the concurrency "
        "slots (`_ACTIVE_LANE`, `_FOLDER_BUILD`) from durable running records "
        "whose pid is alive, after `job_runner.reconcile_on_startup()` retires "
        "dead-but-running records to `interrupted`.",
        "",
    ]
    return "\n".join(lines)


def unresolved_rebuild_rows() -> list:
    """The rebuild-table rows with no resolved rebuild source (must be empty)."""
    return [r for r in REBUILD_TABLE
            if (r.get("source") or "") not in RESOLVED_SOURCES]


def _write_doc(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if path.exists() and path.read_text(encoding="utf-8") == text:
            return path
    except OSError:
        pass
    path.write_text(text, encoding="utf-8")
    return path


def write_ipc_contract_doc(out_dir=None) -> Path:
    """Write ``IPC-CONTRACT.md`` (skipping an unchanged rewrite); return path."""
    out = Path(out_dir) if out_dir is not None else DEFAULT_ARTIFACT_DIR
    return _write_doc(out / "IPC-CONTRACT.md", render_ipc_contract_md())


def write_rebuild_table_doc(out_dir=None) -> Path:
    """Write ``REBUILD-TABLE.md`` (skipping an unchanged rewrite); return path."""
    out = Path(out_dir) if out_dir is not None else DEFAULT_ARTIFACT_DIR
    return _write_doc(out / "REBUILD-TABLE.md", render_rebuild_table_md())


# ── The Supervisor seam ───────────────────────────────────────────────────────

class Supervisor:
    """Abstract owner of spawned lane jobs (the ANCHOR_SUPERVISOR seam).

    Subclasses implement the interaction methods of :data:`IPC_CONTRACT`. The
    dashboard talks to the seam for every job-ownership operation, so the
    inline↔external split is a single swap point.
    """

    mode = None
    degraded = False
    reason = None

    # -- launch --------------------------------------------------------------
    def launch_guarded(self, lane, project_id, folder_path, **kw):
        raise NotImplementedError

    def launch(self, lane, **kw):
        raise NotImplementedError

    # -- tail + cursor -------------------------------------------------------
    def tail(self, job_id, since=None, persist=False):
        raise NotImplementedError

    def read_cursor(self, job_id):
        raise NotImplementedError

    def persist_cursor(self, job_id, offset):
        raise NotImplementedError

    # -- cancel --------------------------------------------------------------
    def cancel(self, job_id):
        raise NotImplementedError

    # -- gate answer ---------------------------------------------------------
    def answer_gate(self, job_id, choice):
        raise NotImplementedError

    def deliver_gate(self, job_id):
        raise NotImplementedError

    # -- introspection / rebuild --------------------------------------------
    def load_job(self, job_id):
        raise NotImplementedError

    def list_jobs(self, project_id=None, running_only=False):
        raise NotImplementedError

    def is_live(self, job_id):
        raise NotImplementedError

    def reconcile(self):
        raise NotImplementedError

    def rebuild(self):
        raise NotImplementedError


class InlineSupervisor(Supervisor):
    """In-process supervisor — owns jobs directly via job_runner/gate_adapter.

    The default owner for tests, the healthcheck, and the degraded fallback.
    Every method delegates to the durable-store-backed job_runner primitives,
    so a "restart" of the dashboard side (clearing the in-memory tables) is
    recoverable via :meth:`rebuild`.
    """

    mode = MODE_INLINE

    def __init__(self, degraded=False, reason=None):
        self.degraded = bool(degraded)
        self.reason = reason

    # -- launch --------------------------------------------------------------
    def launch_guarded(self, lane, project_id, folder_path, **kw):
        return _jr.launch_guarded(lane, project_id, folder_path, **kw)

    def launch(self, lane, **kw):
        return _jr.launch(lane, **kw)

    # -- tail + cursor -------------------------------------------------------
    def read_cursor(self, job_id):
        return _jr.load_read_cursor(job_id)

    def persist_cursor(self, job_id, offset):
        _jr.persist_read_cursor(job_id, offset)

    def tail(self, job_id, since=None, persist=False):
        """Tail from ``since`` (or the durable cursor when ``since is None``).

        When ``persist`` is set, the returned ``next`` offset is written to the
        durable per-job cursor file so a client resumes across a restart (the
        tail-cursor-durability contract row).
        """
        if since is None:
            since = _jr.load_read_cursor(job_id)
        out = _jr.tail(job_id, since)
        if persist:
            try:
                _jr.persist_read_cursor(job_id, out.get("next", since))
            except OSError:
                pass
        return out

    # -- cancel --------------------------------------------------------------
    def cancel(self, job_id):
        return _jr.cancel(job_id)

    # -- gate answer ---------------------------------------------------------
    def answer_gate(self, job_id, choice):
        """Durably QUEUE + ACK the answer, then deliver it supervisor-side.

        The queue write is the ACK — it lands in the job dir BEFORE the POST
        returns. Delivery (the stdin write against the handle the supervisor
        owns) is exactly-once and retryable: a hop killed after the ACK leaves
        the answer queued, and a retry delivers it once (never doubled).

        Returns ``{ok, written, delivered, deferred, queued, reason, job_id}``.
        ``written`` mirrors ``delivered`` for the legacy endpoint contract.
        """
        queued = _ga.queue_gate_answer(job_id, choice)
        if queued is None or not queued.get("ok", True):
            reason = (queued or {}).get("reason", "unknown") if queued else \
                "unknown"
            return {"ok": False, "written": False, "delivered": False,
                    "deferred": False, "queued": False, "reason": reason,
                    "job_id": job_id}
        delivery = _ga.deliver_queued_answer(job_id)
        delivered = bool(delivery.get("delivered"))
        return {
            "ok": True,
            "queued": True,
            "written": delivered,
            "delivered": delivered,
            "deferred": not delivered,
            "reason": delivery.get("reason"),
            "job_id": job_id,
        }

    def deliver_gate(self, job_id):
        """Retry delivery of a queued gate answer (exactly-once)."""
        return _ga.deliver_queued_answer(job_id)

    # -- introspection / rebuild --------------------------------------------
    def load_job(self, job_id):
        return _jr.load_record(job_id)

    def list_jobs(self, project_id=None, running_only=False):
        out = []
        for rec in _jr.list_records():
            if project_id and rec.get("project_id") != project_id:
                continue
            if running_only and rec.get("status") != _jr.STATUS_RUNNING:
                continue
            out.append(rec)
        out.sort(key=lambda r: r.get("started_at") or 0, reverse=True)
        return out

    def is_live(self, job_id):
        rec = _jr.load_record(job_id)
        if rec is None or rec.get("status") != _jr.STATUS_RUNNING:
            return False
        return _jr._holder_is_active(job_id)

    def reconcile(self):
        return _jr.reconcile_on_startup()

    def rebuild(self):
        """Re-adopt in-flight jobs after a dashboard restart.

        1. Reconcile dead-but-running records to ``interrupted``.
        2. Repopulate the concurrency slots (``_ACTIVE_LANE`` /
           ``_FOLDER_BUILD``) from the durable records that are STILL running
           and whose pid is alive, so same-lane serialization + the
           folder-build lock survive the restart.

        Returns a summary dict for the caller/log.
        """
        interrupted = self.reconcile()
        lane_slots = 0
        folder_locks = 0
        running = []
        with _jr._paths.WRITE_LOCK:
            for rec in _jr.list_records():
                if rec.get("status") != _jr.STATUS_RUNNING:
                    continue
                jid = rec.get("job_id")
                if not jid or not _jr._pid_alive(rec.get("pid")):
                    continue
                running.append(jid)
                pid = rec.get("project_id")
                lane = rec.get("lane")
                if pid and lane:
                    key = (pid, lane)
                    if key not in _jr._ACTIVE_LANE:
                        _jr._ACTIVE_LANE[key] = jid
                        lane_slots += 1
                folder = rec.get("folder_path")
                if lane == _jr.BUILD_LANE and folder:
                    if folder not in _jr._FOLDER_BUILD:
                        _jr._FOLDER_BUILD[folder] = jid
                        folder_locks += 1
        return {
            "mode": self.mode,
            "degraded": self.degraded,
            "interrupted": list(interrupted or []),
            "running_jobs": running,
            "rebuilt_lane_slots": lane_slots,
            "rebuilt_folder_locks": folder_locks,
        }


# ── W16 supervisor-side spawn helpers (breakaway + claude probe) ─────────────

def _spawn_creationflags(breakaway=True):
    """Windows creationflags for a supervisor-owned child.

    Always ``CREATE_NO_WINDOW`` (no console flash — John's standing rule) plus a
    new process group so the tree is reapable. When ``breakaway`` is set the
    child also carries ``CREATE_BREAKAWAY_FROM_JOB`` so it survives the
    supervisor's own Job Object being torn down on a restart (the W16 live
    probe). Off Windows this is always 0.
    """
    if os.name != "nt":
        return 0
    flags = (getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
             | _paths_no_window())
    if breakaway:
        flags |= CREATE_BREAKAWAY_FROM_JOB
    return flags


def _paths_no_window():
    import paths as _paths
    return getattr(_paths, "NO_WINDOW", 0)


def spawn_breakaway_child(argv, cwd=None, env=None):
    """Spawn a detached, job-breakaway child; return ``{ok, pid, reason}``.

    The child is spawned with ``CREATE_NO_WINDOW`` (never a visible console) and
    ``CREATE_BREAKAWAY_FROM_JOB`` so it OUTLIVES a supervisor restart. If the
    containing job forbids breakaway (``ERROR_ACCESS_DENIED`` at CreateProcess),
    we retry WITHOUT the breakaway flag and record ``breakaway=False`` — the job
    still spawns; only the restart-survival guarantee is narrowed, honestly
    reported rather than crashing.
    """
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    for breakaway in (True, False):
        try:
            proc = subprocess.Popen(
                list(argv),
                cwd=str(cwd) if cwd else None,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=full_env,
                creationflags=_spawn_creationflags(breakaway=breakaway),
            )
            return {"ok": True, "pid": proc.pid, "breakaway": bool(breakaway),
                    "reason": None}
        except OSError as e:
            # ACCESS_DENIED (breakaway forbidden by the job) → retry plain.
            if breakaway and os.name == "nt":
                continue
            return {"ok": False, "pid": None, "breakaway": False,
                    "reason": f"{type(e).__name__}: {e}"}
    return {"ok": False, "pid": None, "breakaway": False,
            "reason": "spawn failed"}


def _resolve_claude_cmd():
    """Resolve the claude executable for the version probe.

    Honors ``ANCHOR_CLAUDE_CMD`` (an explicit override / test seam), else the
    bare ``claude.exe`` (Windows) / ``claude`` on PATH. Returns the command
    string; the caller runs it with ``--version``.
    """
    override = os.environ.get("ANCHOR_CLAUDE_CMD")
    if override and override.strip():
        return override.strip()
    return "claude.exe" if os.name == "nt" else "claude"


def probe_claude_version(timeout=20.0):
    """Live probe (a): spawn ``claude --version`` under THIS process account.

    Runs the real claude binary with ``--version`` (no window), capturing
    stdout — proving the supervisor's credentials + PATH resolve claude under
    the service account. Returns ``{ok, output, cmd, returncode, reason}``;
    ``ok`` is False (with a ``reason``) when claude is absent/unrunnable, never
    an exception.
    """
    cmd = _resolve_claude_cmd()
    argv = cmd.split() if (" " in cmd) else [cmd]
    argv = argv + ["--version"]
    try:
        res = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout,
            creationflags=(_paths_no_window() if os.name == "nt" else 0),
        )
    except FileNotFoundError:
        return {"ok": False, "output": "", "cmd": cmd, "returncode": None,
                "reason": "claude executable not found on PATH"}
    except (OSError, subprocess.SubprocessError) as e:
        return {"ok": False, "output": "", "cmd": cmd, "returncode": None,
                "reason": f"{type(e).__name__}: {e}"}
    out = (res.stdout or "").strip() or (res.stderr or "").strip()
    return {"ok": res.returncode == 0 and bool(out), "output": out,
            "cmd": cmd, "returncode": res.returncode,
            "reason": None if res.returncode == 0 else "non-zero exit"}


# ── The external supervisor: loopback token-authed HTTP IPC ───────────────────
#
# The server side runs IN the supervisor process (its own NSSM service). It owns
# an :class:`InlineSupervisor` and exposes every IPC-contract interaction as a
# JSON POST on 127.0.0.1. The client side (:class:`ExternalSupervisor`) is the
# dashboard's implementation of the seam — a thin RPC that degrades to inline
# when the hop can't be reached.

def _supervisor_token(env=None):
    src = env if env is not None else os.environ
    tok = src.get(SUPERVISOR_TOKEN_ENV)
    return tok.strip() if tok and tok.strip() else None


def _supervisor_base_url(env=None):
    src = env if env is not None else os.environ
    url = src.get(SUPERVISOR_URL_ENV)
    if url and url.strip():
        return url.strip().rstrip("/")
    host = (src.get(SUPERVISOR_HOST_ENV) or DEFAULT_SUPERVISOR_HOST).strip()
    port = src.get(SUPERVISOR_PORT_ENV) or DEFAULT_SUPERVISOR_PORT
    try:
        port = int(port)
    except (TypeError, ValueError):
        port = DEFAULT_SUPERVISOR_PORT
    return f"http://{host}:{port}"


def _make_ipc_handler():
    """Build the ``BaseHTTPRequestHandler`` subclass for the supervisor server.

    Deferred so importing :mod:`supervisor` never pays for :mod:`http.server`
    unless the process actually serves IPC.
    """
    from http.server import BaseHTTPRequestHandler

    class _SupervisorHandler(BaseHTTPRequestHandler):
        server_version = "AnchorSupervisor/1"

        # Silence the default stderr access log (no console spam under NSSM).
        def log_message(self, *a):  # noqa: D401 - stdlib override
            pass

        def _authed(self):
            want = getattr(self.server, "auth_token", None)
            if want is None:
                return True
            got = None
            hdr = self.headers.get("Authorization")
            if hdr:
                import paths as _p
                got = _p.token_from_authorization(hdr)
            if got is None:
                got = self.headers.get("X-Anchor-Supervisor-Token")
            import hmac
            return bool(got) and hmac.compare_digest(str(got), str(want))

        def _send(self, code, obj):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except OSError:
                pass

        def _read_json(self):
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except (TypeError, ValueError):
                n = 0
            if n <= 0:
                return {}
            try:
                return json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            except (ValueError, OSError):
                return {}

        def do_GET(self):
            # 401 BEFORE any work (mirrors the dashboard's default-deny).
            if not self._authed():
                self._send(401, {"ok": False, "error": "unauthorized"})
                return
            if self.path.split("?", 1)[0] == "/ping":
                self._send(200, self.server.supervisor_ping())
                return
            self._send(404, {"ok": False, "error": "not found"})

        def do_POST(self):
            if not self._authed():
                self._send(401, {"ok": False, "error": "unauthorized"})
                return
            path = self.path.split("?", 1)[0]
            payload = self._read_json()
            try:
                result = self.server.dispatch(path, payload)
            except _IPCNotFound:
                self._send(404, {"ok": False, "error": f"no route {path}"})
                return
            except Exception as e:  # a method error is 200-with-error, not 500
                self._send(200, {"ok": False,
                                 "error": f"{type(e).__name__}: {e}"})
                return
            self._send(200, result)

    return _SupervisorHandler


class _IPCNotFound(Exception):
    """Unknown IPC route (→ 404)."""


class SupervisorServer:
    """The supervisor-side loopback IPC server (runs in the supervisor process).

    Owns an :class:`InlineSupervisor` and serves every IPC-contract interaction
    as a token-authed JSON POST on 127.0.0.1. ``start()`` binds (port 0 → an
    OS-assigned free port for tests) and serves on a daemon thread; ``stop()``
    shuts it down. A supervisor RESTART is modelled by ``stop()`` on the old
    server + ``start()`` of a new one over the SAME data dir — durable job
    records + persisted tail cursors carry across (nothing in-memory is
    required to survive).
    """

    def __init__(self, host=None, port=None, token=None):
        self.host = host or os.environ.get(SUPERVISOR_HOST_ENV) \
            or DEFAULT_SUPERVISOR_HOST
        self._req_port = DEFAULT_SUPERVISOR_PORT if port is None else int(port)
        self.token = token if token is not None else _supervisor_token()
        self._sup = InlineSupervisor()
        self._httpd = None
        self._thread = None
        self.port = None
        # Track sacrificial probe children so we can reap them on stop().
        self._probe_children = []

    # -- IPC method table ----------------------------------------------------
    def dispatch(self, path, payload):
        name = path.strip("/").replace("-", "_")
        fn = getattr(self, f"_op_{name}", None)
        if fn is None:
            raise _IPCNotFound(path)
        return fn(payload or {})

    def supervisor_ping(self):
        return {"ok": True, "mode": MODE_EXTERNAL, "pid": os.getpid(),
                "ipc_contract_rows": len(IPC_CONTRACT)}

    def _op_ping(self, _):
        return self.supervisor_ping()

    def _op_launch(self, p):
        return self._sup.launch(p.pop("lane"), **p)

    def _op_launch_guarded(self, p):
        return self._sup.launch_guarded(
            p.pop("lane"), p.pop("project_id"), p.pop("folder_path"), **p)

    def _op_tail(self, p):
        return self._sup.tail(p["job_id"], since=p.get("since"),
                              persist=bool(p.get("persist")))

    def _op_read_cursor(self, p):
        return {"job_id": p["job_id"],
                "offset": self._sup.read_cursor(p["job_id"])}

    def _op_persist_cursor(self, p):
        self._sup.persist_cursor(p["job_id"], p["offset"])
        return {"ok": True, "job_id": p["job_id"], "offset": p["offset"]}

    def _op_cancel(self, p):
        return self._sup.cancel(p["job_id"])

    def _op_answer_gate(self, p):
        return self._sup.answer_gate(p["job_id"], p.get("choice"))

    def _op_deliver_gate(self, p):
        return self._sup.deliver_gate(p["job_id"])

    def _op_load_job(self, p):
        return {"record": self._sup.load_job(p["job_id"])}

    def _op_list_jobs(self, p):
        return {"jobs": self._sup.list_jobs(
            project_id=p.get("project_id"),
            running_only=bool(p.get("running_only")))}

    def _op_is_live(self, p):
        return {"job_id": p["job_id"], "live": self._sup.is_live(p["job_id"])}

    def _op_reconcile(self, _):
        return {"interrupted": list(self._sup.reconcile() or [])}

    def _op_rebuild(self, _):
        return self._sup.rebuild()

    # -- the two live-probe operations (W16) ---------------------------------
    def _op_probe_claude_version(self, p):
        return probe_claude_version(timeout=float(p.get("timeout", 20.0)))

    def _op_spawn_sacrificial(self, p):
        """Spawn a long-lived breakaway child for the restart-survival probe.

        Returns its pid; the child breaks away from THIS supervisor's job
        object so it survives the supervisor being restarted.
        """
        seconds = int(p.get("seconds", 120))
        import sys as _sys
        argv = [_sys.executable, "-c",
                f"import time; time.sleep({seconds})"]
        out = spawn_breakaway_child(argv)
        if out.get("ok"):
            self._probe_children.append(out["pid"])
        return out

    def _op_reap_pid(self, p):
        import proc_probe
        pid = p.get("pid")
        killed = proc_probe.tree_kill(pid) if pid else False
        return {"ok": bool(killed), "pid": pid}

    # -- lifecycle -----------------------------------------------------------
    def start(self):
        from http.server import ThreadingHTTPServer
        handler = _make_ipc_handler()
        self._httpd = ThreadingHTTPServer((self.host, self._req_port), handler)
        self.port = self._httpd.server_address[1]
        # Attach the owner + token onto the server so the handler can reach them.
        self._httpd.supervisor_ping = self.supervisor_ping
        self._httpd.dispatch = self.dispatch
        self._httpd.auth_token = self.token
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name="anchor-supervisor",
            daemon=True)
        self._thread.start()
        return self.port

    @property
    def url(self):
        return f"http://{self.host}:{self.port}"

    def stop(self, reap_children=True):
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
            except Exception:
                pass
            try:
                self._httpd.server_close()
            except Exception:
                pass
        self._httpd = None
        self._thread = None
        if reap_children:
            import proc_probe
            for pid in self._probe_children:
                try:
                    proc_probe.tree_kill(pid)
                except Exception:
                    pass
            self._probe_children = []


class ExternalSupervisor(Supervisor):
    """The real second-process supervisor CLIENT (W16).

    A thin loopback RPC to the NSSM-hosted supervisor process implementing
    :data:`IPC_CONTRACT`. Ownership operations (launch / cancel / gate-answer /
    rebuild) and reads route over 127.0.0.1 HTTP; the durable stores + persisted
    tail cursors live in the shared data dir, so a SUPERVISOR restart is
    survivable by construction. :meth:`available` probes ``/ping``; a hop that
    can't be reached makes the factory degrade to inline honestly.
    """

    mode = MODE_EXTERNAL

    def __init__(self, base_url=None, token=None, timeout=DEFAULT_IPC_TIMEOUT,
                 env=None):
        self.base_url = (base_url or _supervisor_base_url(env)).rstrip("/")
        self.token = token if token is not None else _supervisor_token(env)
        self.timeout = float(timeout)

    # -- transport -----------------------------------------------------------
    def _call(self, path, payload=None, method="POST"):
        import urllib.request
        import urllib.error
        url = f"{self.base_url}{path}"
        data = None
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if method == "POST":
            data = json.dumps(payload or {}).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers,
                                     method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8") or "{}"
                return json.loads(body)
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise SupervisorUnavailable("supervisor rejected the token")
            try:
                return json.loads(e.read().decode("utf-8") or "{}")
            except Exception:
                raise SupervisorUnavailable(f"supervisor HTTP {e.code}")
        except (urllib.error.URLError, socket.timeout, OSError, ValueError) as e:
            raise SupervisorUnavailable(
                f"supervisor unreachable: {type(e).__name__}: {e}")

    def available(self):
        try:
            out = self._call("/ping", method="GET")
        except SupervisorUnavailable:
            return False
        return bool(out.get("ok"))

    # -- launch --------------------------------------------------------------
    def launch_guarded(self, lane, project_id, folder_path, **kw):
        return self._call("/launch_guarded", dict(
            lane=lane, project_id=project_id, folder_path=folder_path, **kw))

    def launch(self, lane, **kw):
        return self._call("/launch", dict(lane=lane, **kw))

    # -- tail + cursor -------------------------------------------------------
    def tail(self, job_id, since=None, persist=False):
        return self._call("/tail", dict(job_id=job_id, since=since,
                                        persist=bool(persist)))

    def read_cursor(self, job_id):
        return int(self._call("/read_cursor", dict(job_id=job_id))
                   .get("offset", 0))

    def persist_cursor(self, job_id, offset):
        self._call("/persist_cursor", dict(job_id=job_id, offset=offset))

    # -- cancel --------------------------------------------------------------
    def cancel(self, job_id):
        return self._call("/cancel", dict(job_id=job_id))

    # -- gate answer ---------------------------------------------------------
    def answer_gate(self, job_id, choice):
        return self._call("/answer_gate", dict(job_id=job_id, choice=choice))

    def deliver_gate(self, job_id):
        return self._call("/deliver_gate", dict(job_id=job_id))

    # -- introspection / rebuild --------------------------------------------
    def load_job(self, job_id):
        return self._call("/load_job", dict(job_id=job_id)).get("record")

    def list_jobs(self, project_id=None, running_only=False):
        return self._call("/list_jobs", dict(
            project_id=project_id, running_only=bool(running_only))
        ).get("jobs", [])

    def is_live(self, job_id):
        return bool(self._call("/is_live", dict(job_id=job_id)).get("live"))

    def reconcile(self):
        return self._call("/reconcile").get("interrupted", [])

    def rebuild(self):
        return self._call("/rebuild")

    # -- W16 live probes -----------------------------------------------------
    def probe_claude_version(self, timeout=20.0):
        return self._call("/probe_claude_version", dict(timeout=timeout))

    def spawn_sacrificial(self, seconds=120):
        return self._call("/spawn_sacrificial", dict(seconds=seconds))

    def reap_pid(self, pid):
        return self._call("/reap_pid", dict(pid=pid))


def get_supervisor(env=None):
    """Resolve the ANCHOR_SUPERVISOR flag to a live :class:`Supervisor`.

    - ``inline`` → :class:`InlineSupervisor` (the in-process owner).
    - ``external`` → the real :class:`ExternalSupervisor` client WHEN the
      loopback supervisor answers ``/ping``; otherwise a DEGRADED inline
      fallback (``degraded=True`` + a reason) — the honest "the supervisor is
      down, keep working in-process" behavior. The dashboard therefore always
      resolves to a working owner and never crashes over a missing process.

    Never raises for the default flag values; an invalid flag value still
    raises :class:`pillar_flags.PillarStateError` (a typo must fail loudly).
    """
    flags = _pf.current_flags(env=env)          # raises on an invalid value
    mode = flags[_pf.FLAG_SUPERVISOR]
    if mode == MODE_EXTERNAL:
        ext = ExternalSupervisor(env=env)
        if ext.available():
            return ext
        return InlineSupervisor(
            degraded=True,
            reason="external supervisor unavailable at "
                   f"{ext.base_url} — degraded to inline")
    return InlineSupervisor()


def serve(host=None, port=None, token=None):  # pragma: no cover - live service
    """Run the supervisor IPC server forever (the NSSM service entry point).

    Binds the loopback IPC port and serves the contract table until killed.
    ``install_supervisor.ps1`` runs ``python supervisor.py --serve`` under the
    ``.\\john`` account with ``ANCHOR_SUPERVISOR_TOKEN`` / ``_PORT`` in the
    cloned environment.
    """
    srv = SupervisorServer(host=host, port=port, token=token)
    srv.start()
    print(f"anchor supervisor serving on {srv.url} "
          f"(auth={'on' if srv.token else 'off'})", flush=True)
    try:
        while True:
            import time as _t
            _t.sleep(3600)
    except KeyboardInterrupt:
        srv.stop()
    return 0


def main(argv=None):  # pragma: no cover - thin CLI shim
    """CLI: ``--serve`` runs the IPC server; ``--write-docs`` refreshes the gate
    artifacts; else print the resolved seam state."""
    import json as _json
    import sys as _sys

    argv = list(_sys.argv[1:] if argv is None else argv)
    if "--serve" in argv:
        return serve()
    if "--write-docs" in argv:
        p1 = write_ipc_contract_doc()
        p2 = write_rebuild_table_doc()
        print(f"wrote {p1}\nwrote {p2}")
        return 0
    sup = get_supervisor()
    print(_json.dumps({
        "mode": sup.mode,
        "degraded": sup.degraded,
        "reason": sup.reason,
        "unresolved_rebuild_rows": len(unresolved_rebuild_rows()),
        "ipc_contract_rows": len(IPC_CONTRACT),
    }, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(main())
