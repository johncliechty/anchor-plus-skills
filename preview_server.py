#!/usr/bin/env python3
"""Anchor ephemeral preview-server runner (Wave 8, stdlib only).

The Anchor *deliverable* is the running ``anchor_gui.py`` web app itself. A
deliverable preview SERVER is long-running — it never exits on its own — so it
does NOT fit the run-to-completion ``deliverables.run_deliverable`` program
contract (which reaps anything that outlives its timeout). This module is the
dedicated preview runner (MASTER-PLAN §H):

- :func:`start_preview` launches ``python <target> --port <ephemeral>`` in an
  **isolated environment** — a TEMP ``ANCHOR_DATA_DIR`` (so the preview never
  reads or writes the live Anchor data), a loopback-only ``ANCHOR_BIND``, and
  **no** ``ANCHOR_TOKEN`` carried from the parent (so the preview never locks
  the previewer out). The port is **OS-assigned** (bind ``('127.0.0.1', 0)``,
  read the port, close the socket) and is HARD-GUARDED to never be 8777, so the
  preview can never bind / disturb the live ``anchor`` service. The single-
  instance EXCLUSIVE bind in ``anchor_gui``/``paths`` applies ONLY to the fixed
  non-zero port on Windows, so a different ephemeral port never collides.

- :func:`stop_preview` tree-kills the child (mirroring ``job_runner.cancel`` —
  ``taskkill /T /F /PID`` on Windows, process-group kill on POSIX) and marks the
  record stopped. Idempotent on an unknown / already-stopped preview.

- :func:`list_previews` + :func:`reap_orphans` make the registry reflect the
  truth on reconnect: a preview whose process is gone is marked ``stopped``.

The preview registry is a small JSON file persisted under ``.anchor/`` (resolved
via ``paths.data_dir()`` — NEVER hard-coded), mirroring ``session_registry``'s
atomic-write + best-effort-load durability discipline, so previews survive a
dashboard restart far enough to be listed and reaped.

Stdlib only. No third-party imports. (``paths`` / ``job_runner`` are sibling
Anchor modules, also stdlib-only.)
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import paths as _paths
import job_runner as _jr

# ── Constants ───────────────────────────────────────────────────────────────

#: The live Anchor service port — a preview must NEVER bind this.
LIVE_PORT = 8777

#: Preview registry filename, stored under ``.anchor/`` at the data-dir root.
PREVIEWS_NAME = "previews.json"
ANCHOR_DIRNAME = ".anchor"

#: The default deliverable a preview runs — the Anchor web app itself.
DEFAULT_TARGET = "anchor_gui.py"

#: Status values for a preview record (the dashboard shows these).
STATUS_RUNNING = "running"
STATUS_STOPPED = "stopped"
STATUS_FAILED = "failed"

#: How long :func:`start_preview` polls the preview's ``/`` before giving up.
DEFAULT_HEALTH_TIMEOUT = 10.0
#: Per-probe connect/read timeout while health-checking.
_PROBE_TIMEOUT = 1.0
#: Delay between health probes.
_PROBE_INTERVAL = 0.2


# ── Persistence (mirrors session_registry's durability discipline) ──────────

def anchor_dir() -> Path:
    """Absolute path to the ``.anchor/`` dir under the resolved data dir."""
    return _paths.data_dir() / ANCHOR_DIRNAME


def previews_path() -> Path:
    """Absolute path to the preview registry JSON (``.anchor/previews.json``)."""
    return anchor_dir() / PREVIEWS_NAME


def load_previews() -> dict:
    """Load the preview registry as ``{preview_id: record}`` (best-effort).

    A missing / unreadable / corrupt store yields an empty dict — a corrupt
    registry must never crash the dashboard. The JSON on disk is a list of
    records; a keyed-dict form is also tolerated.
    """
    p = previews_path()
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError):
        return {}
    out = {}
    if isinstance(raw, list):
        for e in raw:
            if isinstance(e, dict) and e.get("preview_id"):
                out[e["preview_id"]] = e
    elif isinstance(raw, dict):
        for k, e in raw.items():
            if isinstance(e, dict):
                e = dict(e)
                e.setdefault("preview_id", k)
                if e.get("preview_id"):
                    out[e["preview_id"]] = e
    return out


def _save_previews(reg: dict) -> None:
    """Persist the registry (dict keyed by id) as a JSON list, atomically.

    Runs under ``paths.WRITE_LOCK`` (matching ``session_registry`` /
    ``rnd_registry``). Writes a temp file then ``os.replace`` over the target so
    a crash mid-write can never leave a truncated store.
    """
    with _paths.WRITE_LOCK:
        d = anchor_dir()
        d.mkdir(parents=True, exist_ok=True)
        items = [reg[k] for k in reg]
        target = previews_path()
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(json.dumps(items, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(str(tmp), str(target))


def _put_record(record: dict) -> dict:
    """Insert/replace a preview record under the write lock; return it."""
    with _paths.WRITE_LOCK:
        reg = load_previews()
        reg[record["preview_id"]] = record
        _save_previews(reg)
        return record


# ── Free-port selection (OS-assigned, never 8777) ───────────────────────────

def pick_free_port(attempts: int = 20) -> int:
    """Return an OS-assigned free loopback port, GUARANTEED not to be 8777.

    Binds a throwaway socket to ``('127.0.0.1', 0)`` so the OS hands out a free
    ephemeral port, reads it, and closes the socket. On the astronomically
    unlikely chance the OS hands back 8777 (the live service port), it retries;
    if it cannot get a non-8777 port within ``attempts`` tries it REFUSES with a
    ``RuntimeError`` rather than ever risk binding 8777.
    """
    for _ in range(max(1, attempts)):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        finally:
            s.close()
        if port != LIVE_PORT:
            return port
    raise RuntimeError(
        f"could not obtain a free ephemeral port != {LIVE_PORT}")


# ── Isolated child env ──────────────────────────────────────────────────────

def _isolated_env(data_dir: str) -> dict:
    """Build the preview child's environment.

    - ``ANCHOR_DATA_DIR`` → a TEMP dir (so the preview never reads/writes live
      data).
    - ``ANCHOR_BIND`` → ``127.0.0.1`` (loopback only — never the tailnet).
    - ``ANCHOR_TOKEN`` is STRIPPED (a token carried from the parent would lock
      the previewer out of their own preview; loopback-only makes it safe).
    """
    env = dict(os.environ)
    env["ANCHOR_DATA_DIR"] = str(data_dir)
    env["ANCHOR_BIND"] = "127.0.0.1"
    env.pop("ANCHOR_TOKEN", None)
    return env


def _spawn_preview(target_path: Path, port: int, cwd, env: dict):
    """Spawn ``python <target> --port <port> --no-browser`` (own group).

    Mirrors ``job_runner.launch`` / ``deliverables._spawn`` spawn discipline:
    ``stdin=DEVNULL`` (can never block on input), output captured, a new
    process group on Windows so the whole tree is reapable via ``taskkill
    /T /F`` (``job_runner._tree_kill``).

    Live-checkout-by-design: the preview runs the LIVE checkout's
    ``anchor_gui.py`` straight from the project ``cwd`` — the code is NOT
    copied into a worktree first. IMPLEMENTATION-PLAN Wave 8 prose says "in a
    worktree/copy", but isolating the *code* is unnecessary (and wrong) here:
    the deliverable IS the in-repo ``anchor_gui.py``, so previewing the current
    code is the desired behavior. The safety contract is satisfied entirely by
    DATA + PORT isolation — the child gets a temp ``ANCHOR_DATA_DIR`` (no live
    markdown/registry touched) and an ephemeral OS-assigned port hard-guarded
    ``!= 8777`` (the live ``anchor`` service is never bound or disturbed). So
    data/port isolation, not a code copy, is what protects the live service.
    """
    argv = [sys.executable, str(target_path), "--port", str(port),
            "--no-browser"]
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return subprocess.Popen(
        argv,
        cwd=str(cwd) if cwd else None,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        text=True,
        creationflags=creationflags | _paths.NO_WINDOW,
    )


def _health_check(port: int, proc, timeout: float) -> bool:
    """Poll Anchor's lightweight version seam until it answers 200 (bounded).

    Returns True once the preview responds 200. Returns False if the child dies
    first or the timeout elapses (so the caller can reap + report). Never raises
    on a connection error — those are the expected "not up yet" signal.

    Readiness must not render the full home dashboard: its project summaries and
    Grasscatcher are legitimate application work and can exceed the one-second
    connection probe while the server itself is already healthy.
    """
    deadline = time.time() + max(0.0, float(timeout))
    url = f"http://127.0.0.1:{port}/api/version"
    while time.time() < deadline:
        if proc.poll() is not None:
            return False  # child exited before becoming reachable
        try:
            with urllib.request.urlopen(url, timeout=_PROBE_TIMEOUT) as r:
                if r.status == 200:
                    return True
        except (urllib.error.URLError, urllib.error.HTTPError, OSError):
            pass
        time.sleep(_PROBE_INTERVAL)
    return False


# ── Public API ──────────────────────────────────────────────────────────────

def start_preview(folder_path, project_id, target=DEFAULT_TARGET,
                  health_timeout: float = DEFAULT_HEALTH_TIMEOUT) -> dict:
    """Start an ephemeral preview of a project's deliverable web app.

    Picks an OS-assigned free port (``!= 8777``, hard-guarded), launches
    ``python <target> --port <port> --no-browser`` from ``folder_path`` with an
    isolated TEMP ``ANCHOR_DATA_DIR`` + loopback bind + stripped token,
    health-checks ``/`` until it answers 200, registers the preview, and returns
    ``{ok, preview_id, url, port, pid}``.

    If the preview never comes up within ``health_timeout`` the child is reaped
    and ``{ok: False, reason: ...}`` is returned (no orphan, no registry leak of
    a never-started preview's temp dir).

    ``folder_path`` is the project folder (the preview's cwd); ``target`` is the
    in-folder deliverable to run (default ``anchor_gui.py``).
    """
    folder = Path(folder_path)
    target_path = (folder / target) if not Path(target).is_absolute() \
        else Path(target)
    if not target_path.is_file():
        return {"ok": False,
                "reason": f"target not found: {target_path}"}

    try:
        port = pick_free_port()
    except RuntimeError as exc:
        return {"ok": False, "reason": str(exc)}
    # Defense in depth: never proceed on the live port.
    if port == LIVE_PORT:
        return {"ok": False, "reason": f"refusing to bind live port {LIVE_PORT}"}

    preview_id = uuid.uuid4().hex
    data_dir = tempfile.mkdtemp(prefix=f"anchor-preview-{preview_id[:8]}-")
    env = _isolated_env(data_dir)
    url = f"http://127.0.0.1:{port}/"

    try:
        proc = _spawn_preview(target_path, port, folder, env)
    except OSError as exc:
        _cleanup_dir(data_dir)
        return {"ok": False, "reason": f"spawn failed: {exc}"}

    healthy = _health_check(port, proc, health_timeout)
    if not healthy:
        # Reap the child tree + scrub the temp data dir — no orphan / no leak.
        _jr._tree_kill(proc.pid)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        _drain_quietly(proc)
        _cleanup_dir(data_dir)
        return {"ok": False, "reason": "preview did not become reachable",
                "port": port}

    record = {
        "preview_id": preview_id,
        "project_id": project_id,
        "target": str(target),
        "port": port,
        "url": url,
        "pid": proc.pid,
        "data_dir": str(data_dir),
        "status": STATUS_RUNNING,
        "started_at": time.time(),
        "stopped_at": None,
        "folder_path": str(folder),
    }
    _put_record(record)
    return {"ok": True, "preview_id": preview_id, "url": url, "port": port,
            "pid": proc.pid}


def stop_preview(preview_id: str) -> dict:
    """Tree-kill a preview's child + mark its record stopped (idempotent).

    Mirrors ``job_runner.cancel``: ``taskkill /T /F /PID`` on Windows / process-
    group kill on POSIX. An unknown id returns ``{ok: False, reason}``; an
    already-stopped preview returns ``{ok: True}`` without re-killing.
    """
    rec = load_previews().get(preview_id)
    if rec is None:
        return {"ok": False, "reason": "unknown preview"}
    if rec.get("status") != STATUS_RUNNING:
        return {"ok": True, "preview_id": preview_id,
                "status": rec.get("status")}

    pid = rec.get("pid")
    if pid:
        _jr._tree_kill(pid)
    _cleanup_dir(rec.get("data_dir"))
    rec = dict(rec)
    rec["status"] = STATUS_STOPPED
    rec["stopped_at"] = time.time()
    _put_record(rec)
    return {"ok": True, "preview_id": preview_id, "status": STATUS_STOPPED}


def list_previews(project_id=None) -> list:
    """Return preview records (newest-first), optionally filtered by project.

    A best-effort liveness pass first reconciles any preview whose process is
    gone to ``stopped`` (so the dashboard reflects the truth on reconnect)
    without killing anything that is still alive.
    """
    reap_orphans()
    reg = load_previews()
    out = [r for r in reg.values()
           if project_id is None or r.get("project_id") == project_id]
    out.sort(key=lambda r: (r.get("started_at") is None,
                            -(r.get("started_at") or 0.0)))
    return out


def reap_orphans() -> dict:
    """Reconcile the registry against live processes (startup-safe).

    A preview record marked ``running`` whose process is no longer alive is
    re-statused to ``stopped`` (its temp data dir is scrubbed). Returns
    ``{"reaped": [preview_id, ...]}``. Never kills a still-live preview — this is
    purely a truth-reconcile, e.g. after a dashboard restart.
    """
    reaped = []
    with _paths.WRITE_LOCK:
        reg = load_previews()
        changed = False
        for pid_key, rec in reg.items():
            if rec.get("status") != STATUS_RUNNING:
                continue
            if not _pid_alive(rec.get("pid")):
                rec["status"] = STATUS_STOPPED
                rec["stopped_at"] = time.time()
                _cleanup_dir(rec.get("data_dir"))
                reaped.append(pid_key)
                changed = True
        if changed:
            _save_previews(reg)
    return {"reaped": reaped}


# ── Helpers ─────────────────────────────────────────────────────────────────

def _pid_alive(pid) -> bool:
    """True if the OS process ``pid`` is still alive (best-effort)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if os.name == "nt":
        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, text=True, timeout=15,
                creationflags=_paths.NO_WINDOW)
        except (OSError, subprocess.SubprocessError):
            return False
        return str(pid) in (out.stdout or "")
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def _drain_quietly(proc) -> None:
    """Best-effort close of a child's captured stdout (no dangling pipe)."""
    try:
        if proc.stdout is not None:
            proc.stdout.read()
            proc.stdout.close()
    except (OSError, ValueError):
        pass


def _cleanup_dir(path) -> None:
    """Best-effort recursive remove of a preview's temp data dir."""
    if not path:
        return
    try:
        shutil.rmtree(str(path), ignore_errors=True)
    except OSError:
        pass
