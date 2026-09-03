#!/usr/bin/env python3
"""Anchor job runner — the keystone of the R&D control surface (Wave 4).

A *job* is a server-owned subprocess that streams stdout line-by-line. In
production a job is a ``claude -p --input-format stream-json --output-format
stream-json`` invocation running the relevant skill (researchPrime / crucible /
foreman) in the project cwd (Master Plan D1). For tests and to keep the Foreman
gate billing-free, the launched command is resolved from the **``ANCHOR_RUNNER_CMD``**
env var, which the test suite points at ``tests/fake_claude.py``.

Responsibilities (frozen design — MASTER-PLAN.md "Job runner (the keystone)" +
Wave 4 acceptance):
- ``launch(lane, ...)`` — spawn the runner subprocess (cwd = project), stream
  stdout to a DURABLE log file *and* an in-memory ring buffer, and record a job
  with ``{job_id, lane, pid, status, log_path}`` (+ extras).
- ``tail(job_id, since)`` — return the captured lines *after* index ``since``
  (long-poll friendly; the HTTP long-poll wrapper lives in :func:`long_poll`).
- ``long_poll(job_id, since, ceiling)`` — block up to ``ceiling`` seconds (the
  production default is 25s, injectable for fast tests) for new lines.
- liveness / startup reconciliation — mark dead-but-"running" jobs ``interrupted``.
- ``cancel(job_id)`` — tree-kill via ``taskkill /T /F /PID <pid>`` (reaps
  grandchildren, spike-proven) → status ``cancelled``; tolerates an
  already-gone process without crashing.

All job-state / JSON mutations run under ``paths.WRITE_LOCK``. Job records are
persisted under ``ANCHOR_DATA_DIR`` (resolved via ``paths`` — never a hard-coded
location). Per-project namespacing happens in Wave 6; here a single jobs store
keyed by ``job_id`` is sufficient.

Stdlib only. No third-party imports.
"""

import hashlib
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from pathlib import Path

import paths as _paths
import journal as _journal
import codex_adapter as _codex

# ── Constants ──────────────────────────────────────────────────────────────

#: Env var holding the runner command (indirection point). When unset, the
#: production default below is used. Tests set this to the fake runner so live
#: ``claude`` is never invoked.
RUNNER_CMD_ENV = "ANCHOR_RUNNER_CMD"

#: Production default runner (D1) — the *base* claude command shape. NOT used in
#: the gate (tests override via ANCHOR_RUNNER_CMD). This base is what
#: ``resolve_runner_cmd`` returns when no per-launch prompt is supplied (e.g. the
#: engine-selector tests that only inspect the command shape). For a real launch
#: the per-lane argv is built by ``build_backend_argv`` below, which appends the
#: prompt + output-dir + permission flags appropriate to the lane (research is
#: non-gated and takes the prompt on argv; plan/build are gated and take the
#: prompt as a stream-json user message on stdin).
#: prompt as a stream-json user message on stdin).
DEFAULT_RUNNER_CMD = "claude -p --output-format stream-json"

#: Engine backends. Claude is the historical default; saved Anchor preferences
#: select the family at the lane boundary. ``ANCHOR_RUNNER_CMD`` remains the
#: Claude/Gemini test seam. ChatGPT always uses its dedicated receipt-bearing
#: adapter seam so a generic runner cannot impersonate a subscription seat.
BACKEND_CLAUDE = "claude"
BACKEND_GEMINI = "gemini"
BACKEND_GROK = "grok"
BACKEND_CHATGPT = "chatgpt"
VALID_BACKENDS = frozenset((
    BACKEND_CLAUDE, BACKEND_GEMINI, BACKEND_GROK, BACKEND_CHATGPT,
))
CHATGPT_ONESHOT_LANES = frozenset(("research",))
_CHATGPT_MAX_TOKEN_FIELD = int(_codex.MAX_NATIVE_TOKEN_COUNT)
_CHATGPT_MAX_TOKEN_SUM = _CHATGPT_MAX_TOKEN_FIELD * 5
_CHATGPT_MAX_EVENTS = 10_000_000
_CHATGPT_MAX_THREAD_ID_CHARS = 200
#: Jobs keep Claude as the default backend; interactive terminals read
#: ``anchor_settings.get_default_cli()`` (default ``grok``) instead.
DEFAULT_BACKEND = BACKEND_CLAUDE


def _require_backend(backend) -> str:
    """Return one exact backend string or raise a typed boundary refusal."""
    if not isinstance(backend, str) or backend not in VALID_BACKENDS:
        raise ValueError("unknown backend %r" % (backend,))
    return backend

#: Env var overriding the Gemini runner command. When unset,
#: :data:`DEFAULT_GEMINI_CMD` is used. Spike finding (2026-06-09): ``gemini -p``
#: runs headless and authenticates as the service user, BUT it refuses agentic
#: work in a project folder unless ``--skip-trust`` is passed — it treats
#: untrusted dirs as read-only and overrides the approval mode. Since jobs run
#: INSIDE the project folder, ``--skip-trust`` is required. ``--output-format
#: stream-json`` is supported. ``--approval-mode plan`` is read-only (research is
#: non-mutating). The prompt/seed is appended by the lane wiring via
#: ``extra_args`` exactly as for claude; the gemini CLI tolerates/parses the
#: trailing seed. Override the whole command via this env var if needed.
#: Spike finding (2026-06-09, verified live): the previous default passed
#: ``--approval-mode plan``, which is READ-ONLY — a research lane MUST write its
#: report into the output dir, so ``plan`` blocks it. The minimal write-capable
#: mode is ``auto_edit`` (auto-approves file edits; gemini is research-only here
#: and never needs to run shell commands, so ``yolo`` would be over-broad). Also
#: note the real gemini flag is ``-p/--prompt`` whose VALUE is the prompt (NOT a
#: bare ``-p`` consuming the prompt from stdin) and ``--include-directories``
#: (NOT ``--output-dir``) grants access to the output dir — both are appended by
#: ``build_backend_argv`` for a real launch. This base constant is the command
#: SHAPE returned when no per-launch prompt is supplied.
GEMINI_CMD_ENV = "ANCHOR_GEMINI_CMD"
DEFAULT_GEMINI_CMD = (
    "gemini --skip-trust -p --output-format stream-json --approval-mode auto_edit"
)

#: Receipt-bearing ChatGPT adapter shipped with this exact Anchor checkout.
#: Tests monkeypatch this module constant directly; production environment
#: variables cannot replace the adapter and impersonate a subscription seat.
CODEX_ADAPTER_PATH = str(
    (Path(__file__).resolve().parent / "codex_adapter.py").resolve()
)

#: Long-poll ceiling (seconds). Production default per the frozen design; the
#: HTTP layer passes this. Injectable so tests run fast (never actually 25s).
DEFAULT_LONGPOLL_CEILING = 25.0

#: Sub-directory under the data dir that holds job records + durable logs.
JOBS_DIRNAME = "rnd_jobs"

#: In-memory ring buffer cap per job (durable log keeps the full history).
RING_CAPACITY = 5000

# Job statuses.
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_CANCELLED = "cancelled"
STATUS_INTERRUPTED = "interrupted"
STATUS_FAILED = "failed"

#: The set of runner statuses that mean the job's process lifecycle is over.
#: A terminal job cannot accept a continuation turn (its session is gone).
TERMINAL_STATUSES = frozenset(
    (STATUS_DONE, STATUS_CANCELLED, STATUS_INTERRUPTED, STATUS_FAILED)
)

#: Runner-seam env vars captured into a job's ``relaunch_spec`` (durability
#: 2026-07 Wave 1). ONLY these seed keys are persisted from the launch ``env``
#: overlay — never the full environment — so a durable record can re-drive the
#: stub/test seams on relaunch without ever writing secrets into a record.
RELAUNCH_ENV_EXACT = ("ANCHOR_RUNNER_CMD",)
RELAUNCH_ENV_PREFIXES = ("STUB_", "FAKE_", "ANCHOR_GANDALF_")

#: Machine-readable relaunch refusal reasons (strings, never exceptions).
RELAUNCH_REASON_UNKNOWN = "unknown-job"
RELAUNCH_REASON_NOT_INTERRUPTED = "not-interrupted"
RELAUNCH_REASON_NO_SPEC = "no-relaunch-spec"

#: Lane stamped on the ``session_registry`` record we mint for every spawned job
#: (zombie-hunter v2). Each job is a "swarm" sub-agent; registering it under this
#: lane — with the SAME identity (pid / proc_create_time / crypt_token) we already
#: persist on the job record — is what makes the otherwise-invisible swarm child
#: SWEEPABLE by ``zombie_hunter`` (DESIGN.md coverage gap: the identity used to
#: live only in the job store, never in ``session_registry`` where the hunter
#: looks). The hunter ABSTAINS on any record missing this identity, so a launch
#: that failed to stamp it is never mis-killed.
SWARM_LANE = "swarm"

# ── In-memory live job table ────────────────────────────────────────────────
# Maps job_id -> a _LiveJob holding the Popen, reader thread, and ring buffer.
# Only live (this-process) jobs appear here; persisted records on disk are the
# durable source of truth and survive restarts.
_LIVE = {}
_LIVE_LOCK = threading.RLock()

# Maps job_id -> the jobs directory resolved AT LAUNCH TIME. A job's storage
# location is pinned for its lifetime so a background reader/finalizer thread
# writes to the same place even if ANCHOR_DATA_DIR changes underneath it (which
# also matters in tests, where each test's tmp data dir is torn down while a
# daemon reader may still be finalizing). For jobs that predate this process
# (startup reconciliation), the helpers fall back to the live data dir.
_JOB_DIRS = {}
_JOB_DIRS_LOCK = threading.RLock()

# ── Concurrency policy registries (Wave 6) ──────────────────────────────────
# All concurrency/lock state lives under ``paths.WRITE_LOCK`` (acquired by the
# helpers below), per the frozen design. These are *in-process* tables — a
# server owns its subprocess jobs, so a single ThreadingHTTPServer's policy is
# enforced here; durable records on disk remain the cross-restart source of
# truth.
#
# _ACTIVE_LANE maps (project_id, lane) -> job_id for the currently-running job
# in that project lane. It enforces WITHIN-a-project same-lane serialization
# (cross-lane stays concurrent because the key includes the lane).
_ACTIVE_LANE = {}
# _FOLDER_BUILD maps folder_path -> job_id for the build currently holding that
# folder's build lock. It enforces ACROSS-projects-sharing-a-folder build
# serialization: at most one build per folder at a time. research/plan are NOT
# folder-locked, so they never appear here and never block.
_FOLDER_BUILD = {}

#: The lane that mutates the shared working tree and is therefore serialized at
#: the FOLDER level (the trio forbids parallel coders in one tree).
BUILD_LANE = "build"

#: Refusal reasons surfaced when a launch is blocked by the concurrency policy.
REFUSED_SAME_LANE = "same-lane-busy"
REFUSED_FOLDER_BUILD = "folder-build-lock"


class LaneBusyError(RuntimeError):
    """Raised when a launch is refused by the concurrency policy.

    Carries a machine-readable ``reason`` (one of :data:`REFUSED_SAME_LANE` /
    :data:`REFUSED_FOLDER_BUILD`) and ``holder`` (the job_id already holding the
    contended slot) so the caller / UI can render the right indicator (e.g. the
    folder-build-lock badge).
    """

    def __init__(self, reason, holder=None, message=None):
        self.reason = reason
        self.holder = holder
        super().__init__(message or f"{reason} (held by {holder})")


class _LiveJob:
    """Runtime handle for a job owned by *this* server process."""

    __slots__ = ("job_id", "proc", "ring", "reader", "log_path", "lock", "done",
                 "gated", "_h_job", "_cancel_requested")

    def __init__(self, job_id, proc, log_path, gated=False):
        self.job_id = job_id
        self.proc = proc
        self.ring = deque(maxlen=RING_CAPACITY)
        self.reader = None
        self.log_path = log_path
        self.lock = threading.Lock()
        self.done = threading.Event()
        # Truthy ("plan"/"build") for a gated lane: the reader loop feeds each
        # stdout line to the gate adapter so an AskUserQuestion frame surfaces as
        # awaiting-input state in production (NOT just in hand-injected tests).
        self.gated = gated
        # Cancellation is a two-phase transition: request + verified tree
        # termination/drain, then (and only then) durable ``cancelled``.
        self._cancel_requested = False


# ── Persistence ─────────────────────────────────────────────────────────────

def jobs_dir() -> Path:
    """Directory holding job records + durable logs, under ANCHOR_DATA_DIR."""
    return _paths.data_dir() / JOBS_DIRNAME


def _jobs_dir_for(job_id: str) -> Path:
    """Resolve a specific job's jobs dir, honoring the launch-time pin.

    Pinned at launch so background threads stay consistent; falls back to the
    current data dir for jobs not launched by this process (reconciliation).
    """
    with _JOB_DIRS_LOCK:
        pinned = _JOB_DIRS.get(job_id)
    return pinned if pinned is not None else jobs_dir()


def _record_path(job_id: str) -> Path:
    return _jobs_dir_for(job_id) / f"{job_id}.json"


def log_path_for(job_id: str) -> Path:
    return _jobs_dir_for(job_id) / f"{job_id}.log"


def _ensure_jobs_dir() -> None:
    jobs_dir().mkdir(parents=True, exist_ok=True)


def _write_record(rec: dict) -> None:
    """Persist a job record (atomic-ish) under the write lock.

    On Windows, ``os.replace`` fails with a transient PermissionError
    (WinError 5) while any other handle holds the destination open —
    ``load_record`` reads take no lock, so a concurrent read can briefly
    block the swap (observed live 2026-08-07: the reader thread's
    ``_finalize`` died unhandled mid-replace). Retry the replace a few
    times before letting the error propagate; the holds are millisecond
    -scale.
    """
    with _paths.WRITE_LOCK:
        p = _record_path(rec["job_id"])
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(rec, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        for attempt in range(5):
            try:
                tmp.replace(p)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.02 * (attempt + 1))


def load_record(job_id: str):
    """Return the persisted job record dict, or ``None``.

    A read racing an in-flight ``_write_record`` replace can transiently
    fail on Windows (the destination passes through a delete-pending
    state → OSError on open), so one failed read gets a single short
    retry before the honest ``None``.
    """
    p = _record_path(job_id)
    for attempt in range(2):
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            if attempt == 0:
                time.sleep(0.02)
    return None


def list_records() -> list:
    """All persisted job records (best-effort; skips unreadable ones).

    A job's durable GATE file (``<job_id>.gate.json`` — durability 2026-07
    Wave 2) and its durable read-CURSOR file (``<job_id>.cursor.json`` — rearch
    W15) live in the same directory and match the ``*.json`` glob; neither is a
    job record and both are skipped so no phantom job ever surfaces here.
    """
    d = jobs_dir()
    if not d.exists():
        return []
    out = []
    for p in sorted(d.glob("*.json")):
        if p.name.endswith((".gate.json", ".cursor.json")):
            continue
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return out


def _update_record(job_id: str, **fields) -> dict:
    """Read-modify-write a record under the lock. Returns the new record."""
    with _paths.WRITE_LOCK:
        rec = load_record(job_id) or {"job_id": job_id}
        rec.update(fields)
        _write_record(rec)
        return rec


# ── Runner command resolution ────────────────────────────────────────────────

def _shlex_split(raw: str) -> list:
    """Split a command string into argv, surviving Windows backslash paths.

    Carried-bug fix: ``shlex.split(posix=True)`` eats backslashes, corrupting an
    explicitly-set ``ANCHOR_RUNNER_CMD`` like ``python C:\\dev\\...\\fake.py`` on
    Windows. Use ``posix=False`` on Windows so backslashes survive; POSIX rules
    elsewhere. (The prod defaults use forward-slash-free bare binaries, so this
    only matters for an explicit override.)
    """
    return shlex.split(raw, posix=(os.name != "nt"))


def _build_claude_argv(prompt, output_dir, gated, permission_mode=None) -> list:
    """Build a VALID ``claude`` argv for a real (override-unset) launch.

    Verified-real claude flags only (claude --help): ``-p`` (print/headless),
    ``--output-format stream-json``, ``--add-dir <dir>`` (grant tool access to
    the output dir so the skill can WRITE its report there), and
    ``--permission-mode <mode>``.

    - RESEARCH (non-gated): the natural-language seed IS the prompt and is passed
      as a trailing argv value. ``acceptEdits`` is the MINIMAL mode that lets the
      skill write files into the output dir (``plan`` is read-only and would
      block the report; ``bypassPermissions`` is broader than research needs).
    - PLAN/BUILD (gated): ``--input-format stream-json`` is added, which makes
      claude consume the prompt as a stream-json user message from STDIN (NOT
      argv) — so the prompt is delivered by :func:`launch` on the stdin pipe, not
      here. build mutates the tree and may run Bash → ``bypassPermissions``; plan
      is non-mutating but writes docs → ``acceptEdits``.

    There is intentionally NO ``--skill`` / ``--output-dir`` / ``--prompt-seed``
    (none are real flags — that was the bug). Skills are auto-discovered and
    invoked via the natural-language seed.
    """
    # Live-smoke finding (2026-06-10): real ``claude -p --output-format
    # stream-json`` REQUIRES ``--verbose`` ("--output-format=stream-json requires
    # --verbose") — without it claude refuses to start. (Not in the mock path.)
    argv = ["claude", "-p", "--verbose", "--output-format", "stream-json"]
    if output_dir:
        argv += ["--add-dir", str(output_dir)]
    if gated:
        # Gated lanes consume the initial prompt from stdin as a stream-json user
        # message (delivered by launch()); build may mutate the tree + run Bash.
        argv += ["--input-format", "stream-json"]
        argv += ["--permission-mode", "bypassPermissions" if gated == "build"
                 else "acceptEdits"]
        # Prompt is NOT placed on argv for gated lanes — it arrives on stdin.
    else:
        # Research: ``acceptEdits`` lets a trio skill write its report into the
        # output dir. A READ-ONLY caller (the Gandalf advisor — it writes NO file,
        # only emits its analysis as the final message) passes
        # ``permission_mode="plan"`` so claude can NEVER edit the analyzed project.
        # The seed is the prompt on argv.
        argv += ["--permission-mode", permission_mode or "acceptEdits"]
        if prompt:
            argv.append(prompt)
    return argv


def _build_gemini_argv(prompt, output_dir, gated, permission_mode=None) -> list:
    """Build the argv for a real Gemini launch — routed through the host ``agy`` CLI.

    This host has NO bare ``gemini`` binary; Gemini IS the ``agy`` CLI, whose old
    ``--skip-trust`` / ``--output-format stream-json`` flags are DEAD (hard-error).
    So a real Gemini launch runs the thin Node adapter ``agy_job_adapter.mjs``, which
    drives the sanctioned ``agy-dispatch.mjs`` transport (no-shell STEER + transcript
    polling + windowsHide) and re-emits the reply as ONE stream-json ``result`` line —
    parsed unchanged by :func:`extract_assistant_text` and by ``gandalf._map_shards`` /
    ``summarizer``. The (possibly large) prompt is written to a temp FILE, never put on
    argv (agy's argv ceiling is ~32KB). Read-only posture (``--readonly``) for plan-mode
    reads (e.g. gandalf shards); edit posture (agy ``--sandbox --add-dir``, applied by
    the dispatcher) when the lane must write its report (research). Overrides:
    ``ANCHOR_AGY_ADAPTER`` (adapter path), ``ANCHOR_AGY_DISPATCH`` (dispatch path),
    ``GEMINI_MODEL``/``TRIO_MODEL`` (model).
    """
    import tempfile
    fd, prompt_file = tempfile.mkstemp(prefix="agyprompt-", suffix=".txt")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(prompt or "")
    adapter = (os.environ.get("ANCHOR_AGY_ADAPTER") or
               os.path.join(os.path.dirname(os.path.abspath(__file__)), "agy_job_adapter.mjs"))
    model = (os.environ.get("GEMINI_MODEL") or os.environ.get("TRIO_MODEL") or "gemini-3.1-pro")
    argv = ["node", adapter, "--prompt-file", prompt_file, "--model", model,
            "--target", str(output_dir or ".")]
    if permission_mode == "plan" or gated == "plan":
        argv.append("--readonly")
    return argv


def _normalize_expected_artifacts(expected_artifacts) -> list:
    """Return a bounded, target-relative artifact contract.

    ChatGPT workspace-write jobs are accepted only when the caller names the
    exact files that constitute completion.  Validation happens again in the
    adapter, but this parent-side copy keeps malformed contracts from creating
    a job record or starting a subscription seat.
    """
    if expected_artifacts is None:
        return []
    if isinstance(expected_artifacts, (str, bytes)):
        raise ValueError("chatgpt-artifact-contract-invalid: expected a path list")
    try:
        values = list(expected_artifacts)
    except TypeError as exc:
        raise ValueError(
            "chatgpt-artifact-contract-invalid: expected a path list"
        ) from exc
    if not values:
        return []
    try:
        return list(_codex._normalize_expected_artifacts(
            Path(__file__).resolve().parent, values))
    except (OSError, TypeError, ValueError) as exc:
        raise ValueError(
            "chatgpt-artifact-contract-invalid: non-portable path contract"
        ) from exc


def _build_chatgpt_argv(prompt, output_dir, gated, permission_mode=None,
                        expected_artifacts=None) -> list:
    """Build Anchor's safe one-shot ChatGPT subscription adapter command.

    Codex reads the prompt from stdin, so neither ``prompt`` nor project content
    enters argv. Artifact-producing research needs ``workspace-write`` inside the
    validated project cwd; advisor/diagnostic calls explicitly request ``plan``
    and remain read-only. Claude's kept-open AskUserQuestion protocol is not
    equivalent to one-shot Codex, so gated lanes fail before any process starts.
    """
    if gated:
        raise ValueError(
            "chatgpt-gated-bridge-pending: ChatGPT plan/build requires the "
            "persistent Codex exec/resume cockpit bridge; no seat was started"
        )
    if not output_dir:
        raise ValueError("chatgpt-target-required: a project-scoped output directory is required")
    target = Path(output_dir).resolve()
    if not target.is_dir():
        raise ValueError("chatgpt-target-required: output directory does not exist: %s" % target)
    adapter = CODEX_ADAPTER_PATH
    sandbox = "read-only" if permission_mode == "plan" else "workspace-write"
    expected = _normalize_expected_artifacts(expected_artifacts)
    if sandbox == "workspace-write" and not expected:
        raise ValueError(
            "chatgpt-artifact-contract-required: workspace-write requires "
            "explicit expected artifact paths"
        )
    if sandbox == "read-only" and expected:
        raise ValueError(
            "chatgpt-artifact-contract-invalid: read-only jobs cannot expect writes"
        )
    argv = [sys.executable, adapter, "--sandbox", sandbox,
            "--target", str(target)]
    for rel in expected:
        argv.extend(("--expected-artifact", rel))
    return argv


def build_backend_argv(backend, prompt, output_dir, gated, permission_mode=None,
                       expected_artifacts=None) -> list:
    """Build the VALID production argv for a backend + lane shape.

    Used only on the override-UNSET (real-CLI) path. Dispatches to the
    per-backend builder. ``gated`` is falsy for one-shot research/general jobs
    and truthy for persistent plan/build sessions. ChatGPT gated jobs refuse
    here until Anchor has a tested Codex exec/resume bridge.
    """
    backend = _require_backend(backend)
    if backend == BACKEND_GROK:
        # Interactive Grok terminals are supported via terminal_session; headless
        # job_runner has no tool-capable Grok argv builder yet. Refuse honestly
        # rather than silently launching Claude under a grok backend label.
        raise ValueError(
            "job_runner does not support backend='grok' for headless jobs yet; "
            "use an interactive Grok terminal (terminal_session) or set "
            "coding_family/review_family for trio seat routing instead"
        )
    if backend == BACKEND_CHATGPT:
        return _build_chatgpt_argv(
            prompt, output_dir, gated, permission_mode=permission_mode,
            expected_artifacts=expected_artifacts,
        )
    if backend == BACKEND_GEMINI:
        return _build_gemini_argv(prompt, output_dir, gated, permission_mode=permission_mode)
    return _build_claude_argv(prompt, output_dir, gated, permission_mode=permission_mode)


def resolve_runner_cmd(extra_args=None, backend=DEFAULT_BACKEND,
                       prompt=None, output_dir=None, gated=False,
                       permission_mode=None, expected_artifacts=None) -> list:
    """Resolve the runner command as an argv list, honoring the engine backend.

    Resolution order (CRITICAL — transport identity must remain truthful):
    1. ChatGPT always resolves through its dedicated receipt-bearing adapter;
       generic runner overrides and arbitrary trailing args cannot impersonate it.
    2. ``ANCHOR_RUNNER_CMD`` set → use it for Claude/Gemini (this is how the
       legacy suite drives ``tests/fake_claude.py``). The command is used as-is; if a
       ``prompt`` is supplied it is appended as a trailing arg the mock tolerates
       via ``parse_known_args`` (so tests still drive the mock and the prompt
       never leaks into a real CLI). ``extra_args`` (test flags like ``--lines``)
       are appended last. Never broken by the per-backend builders.
    3. else (override unset → a REAL launch): build a VALID per-backend, per-lane
       argv via :func:`build_backend_argv` — but only when a ``prompt`` is
       supplied (a real lane launch always supplies one). When no ``prompt`` is
       supplied (e.g. an engine-selector test inspecting only the command SHAPE),
       fall back to the per-backend default command constant so its shape is
       observable. ``extra_args`` are appended in both sub-cases.
    """
    backend = _require_backend(backend)
    if backend == BACKEND_CHATGPT and extra_args:
        raise ValueError(
            "chatgpt-extra-args-refused: safety and target arguments are owned "
            "by Anchor's Codex adapter"
        )
    override = os.environ.get(RUNNER_CMD_ENV)
    if override and override.strip() and backend != BACKEND_CHATGPT:
        # Test indirection: the mock runner drives every test. Use the override
        # base verbatim; append the prompt (mock ignores it) so the gated/stdin
        # path is exercised without a real CLI, then the test's extra_args.
        argv = _shlex_split(override)
        if prompt is not None:
            argv = argv + [prompt]
    elif prompt is not None:
        # Real launch: construct a valid per-backend argv from scratch.
        argv = build_backend_argv(
            backend, prompt, output_dir, gated,
            permission_mode=permission_mode,
            expected_artifacts=expected_artifacts,
        )
    else:
        # Shape-only resolution (no prompt): return the per-backend default base.
        if backend == BACKEND_GEMINI:
            gem = os.environ.get(GEMINI_CMD_ENV)
            raw = gem if (gem and gem.strip()) else DEFAULT_GEMINI_CMD
        elif backend == BACKEND_CHATGPT:
            argv = _build_chatgpt_argv(
                None, output_dir, gated, permission_mode=permission_mode,
                expected_artifacts=expected_artifacts,
            )
            raw = None
        else:
            raw = DEFAULT_RUNNER_CMD
        if raw is not None:
            argv = _shlex_split(raw)
    if extra_args:
        argv = argv + list(extra_args)
    return argv


# ── Launch ───────────────────────────────────────────────────────────────────

def _stream_json_user_turn(text: str) -> str:
    """Render an initial prompt as a stream-json user message (for stdin).

    A gated lane (claude ``--input-format stream-json``) consumes its INITIAL
    prompt as a stream-json user message on stdin (the prompt is NOT on argv).
    This is the same envelope shape ``gate_adapter._format_turn`` writes for a
    continuation answer, so the session reads them uniformly.
    """
    envelope = {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
    }
    return json.dumps(envelope, ensure_ascii=False) + "\n"


def _relaunch_env_seed(env) -> dict:
    """Filter a launch ``env`` overlay down to the runner-seam variables.

    Keeps only :data:`RELAUNCH_ENV_EXACT` keys and keys starting with a
    :data:`RELAUNCH_ENV_PREFIXES` prefix (``ANCHOR_RUNNER_CMD`` / ``STUB_*`` /
    ``FAKE_*`` / ``ANCHOR_GANDALF_*``). Everything else — anything that could
    carry a secret — is dropped, so the durable record never persists the full
    environment.
    """
    seed = {}
    for k, v in (env or {}).items():
        if k in RELAUNCH_ENV_EXACT or str(k).startswith(RELAUNCH_ENV_PREFIXES):
            seed[k] = v
    return seed


def _build_relaunch_spec(lane, cwd, prompt, output_dir, gated,
                         permission_mode, backend, env,
                         project_id=None, folder_path=None,
                         command=None, expected_artifacts=None) -> dict:
    """Everything a guarded launch needs to start an equivalent job (Wave 1).

    Persisted on the job record at launch time so an ``interrupted`` job can be
    re-launched in ONE call (:func:`relaunch`) from disk state alone. ``env_keys``
    holds ONLY the runner-seam seed vars (see :func:`_relaunch_env_seed`).
    ``project_id``/``folder_path`` (approved amendment, 2026-07-02) carry the
    concurrency-policy context so a relaunch goes through :func:`launch_guarded`
    exactly as the first launch did; a direct :func:`launch` records them as
    ``None``. ``command`` (foundry-v2 Wave 7) preserves an explicit
    control-plane argv so an interrupted op job never relaunches as a model
    job; the key is present ONLY on such launches (a model job's spec shape
    is unchanged).
    """
    spec = {
        "lane": lane,
        "cwd": str(cwd) if cwd else None,
        "prompt": prompt,
        "output_dir": str(output_dir) if output_dir else None,
        "gated": gated,
        "permission_mode": permission_mode,
        "backend": backend,
        "expected_artifacts": _normalize_expected_artifacts(expected_artifacts),
        "env_keys": _relaunch_env_seed(env),
        "project_id": project_id,
        "folder_path": str(folder_path) if folder_path else None,
    }
    if command:
        spec["command"] = [str(a) for a in command]
    return spec


def launch(lane: str, cwd=None, extra_args=None, env=None,
           job_id: str = None, backend=DEFAULT_BACKEND,
           prompt=None, output_dir=None, gated=False,
           permission_mode=None, project_id=None, folder_path=None,
           command=None, kill_on_job_close: bool = True,
           expected_artifacts=None) -> dict:
    """Launch a server-owned job. Returns the job record.

    ``command`` (foundry-v2 Wave 7 — the control-plane dispatch seam): when
    set (an argv list), it IS the launched command verbatim. The caller
    (``foundry_ops``) resolved it from a validated op manifest; backend
    resolution and the ``ANCHOR_RUNNER_CMD`` test indirection are MODEL-run
    seams and deliberately do not apply — a control-plane op body is
    deterministic local code that must genuinely run (headlessly), in tests
    and production alike. Everything else (durable log, ring buffer, record,
    reconcile, cancel tree-kill) applies unchanged.

    The record holds at least ``{job_id, lane, pid, status, log_path, backend}``.
    stdout is streamed by a daemon reader thread into a durable log file *and* an
    in-memory ring buffer. ``cwd`` is the project working directory; ``env`` is
    merged onto the current environment. ``backend`` selects Claude, Gemini,
    or the one-shot ChatGPT subscription adapter (Grok headless jobs still
    refuse). It is recorded on the job so the UI/history can show which engine
    ran the effort.
    ``ANCHOR_RUNNER_CMD`` remains a Claude/Gemini test seam. ChatGPT always uses
    the pinned sibling adapter and requires its complete receipt.

    ``prompt`` (the natural-language lane seed), ``output_dir`` (project-scoped),
    and ``gated`` (falsy for research; ``"plan"``/``"build"`` for the gated lanes)
    are threaded into :func:`resolve_runner_cmd` so a real launch builds a VALID
    per-backend argv.

    ``project_id`` / ``folder_path`` (durability 2026-07 Wave 1, amended) are
    NOT used by the spawn itself — they are persisted into the record's
    ``relaunch_spec`` so :func:`relaunch` can re-drive :func:`launch_guarded`
    with the same concurrency-policy context. :func:`launch_guarded` passes
    them; a direct call may leave them ``None``.

    Stdin handling (D / SETUP §5):
    - NON-GATED Claude/Gemini (research) **or** no prompt: ``stdin=DEVNULL``;
      their prompt remains on the established backend argv.
    - NON-GATED ChatGPT: ``stdin=PIPE``; the raw prompt is written once and the
      pipe is closed. The adapter then forwards it to ``codex exec ... -`` so
      project content never appears in process arguments.
    - GATED (plan/build, claude only): ``stdin=PIPE`` kept OPEN for the job's
      lifetime, and the INITIAL prompt is written as a stream-json user message
      (claude's ``--input-format stream-json`` consumes the prompt from stdin,
      not argv). The live process stdin is registered with the gate adapter so an
      answer can be written into the SAME pipe. NOTE: in the test path
      (``ANCHOR_RUNNER_CMD`` set → the mock), the mock reads no stdin, so we still
      open the pipe but the mock simply ignores it; gate tests register their own
      fake sink. This plain-text-after-auto-dismiss gate path is inherently
      FRAGILE (SETUP §4 residual risk): AskUserQuestion can't be answered via a
      tool_result, so the model re-asks in plain text and we answer with a
      stream-json user TEXT turn — best-effort continuation, not guaranteed.
    """
    backend = _require_backend(DEFAULT_BACKEND if backend is None else backend)
    if backend == BACKEND_CHATGPT and lane not in CHATGPT_ONESHOT_LANES:
        # The lane is authoritative only at this public launch boundary. Command
        # resolution deliberately has no lane input and therefore must not infer
        # one. Until F1B lands, only the bounded one-shot research adapter may run.
        raise ValueError(
            "chatgpt-gated-bridge-pending: %s requires the persistent Codex "
            "exec/resume cockpit bridge; no seat was started" % (lane,)
        )
    if backend == BACKEND_CHATGPT and command:
        # This guard MUST precede job-id allocation, directory pinning, log
        # creation, and record/journal writes. A generic control-plane command
        # cannot impersonate the receipt-bearing ChatGPT adapter.
        raise ValueError(
            "chatgpt-command-override-refused: ChatGPT transport is owned by "
            "Anchor's Codex adapter"
        )
    if backend == BACKEND_CHATGPT and env:
        # Caller overlays can redirect HOME/CODEX_HOME/LOCALAPPDATA/PATH and
        # make the adapter execute or load attacker-selected state before a
        # parent receipt could reject it. ChatGPT inherits only Anchor's host
        # environment plus the internally-derived preference markers below.
        raise ValueError(
            "chatgpt-env-overlay-refused: ChatGPT launch environment is owned "
            "by Anchor's Codex adapter"
        )
    if backend == BACKEND_CHATGPT and extra_args:
        raise ValueError(
            "chatgpt-extra-args-refused: safety and target arguments are owned "
            "by Anchor's Codex adapter"
        )
    if backend == BACKEND_CHATGPT:
        if not cwd or not output_dir:
            raise ValueError(
                "chatgpt-target-required: project cwd and project-scoped output "
                "directory are required"
            )
        project_root = Path(cwd).resolve()
        target = Path(output_dir).resolve()
        if not project_root.is_dir() or not target.is_dir():
            raise ValueError(
                "chatgpt-target-required: project cwd and output directory must exist"
            )
        try:
            target.relative_to(project_root)
        except ValueError as exc:
            raise ValueError(
                "chatgpt-target-outside-project: %s is outside %s" %
                (target, project_root)
            ) from exc
    if backend == BACKEND_CHATGPT and gated:
        raise ValueError(
            "chatgpt-gated-bridge-pending: ChatGPT plan/build requires the "
            "persistent Codex exec/resume cockpit bridge; no seat was started"
        )
    normalized_expected_artifacts = _normalize_expected_artifacts(expected_artifacts)
    if backend == BACKEND_CHATGPT:
        read_only = permission_mode == "plan"
        if not read_only and not normalized_expected_artifacts:
            raise ValueError(
                "chatgpt-artifact-contract-required: workspace-write requires "
                "explicit expected artifact paths"
            )
        if read_only and normalized_expected_artifacts:
            raise ValueError(
                "chatgpt-artifact-contract-invalid: read-only jobs cannot expect writes"
            )
    elif normalized_expected_artifacts:
        raise ValueError(
            "chatgpt-artifact-contract-invalid: expected artifacts are owned "
            "by the ChatGPT adapter"
        )
    job_id = job_id or uuid.uuid4().hex
    # Pin this job's storage dir for its lifetime (resolved now, once).
    pinned = jobs_dir()
    pinned.mkdir(parents=True, exist_ok=True)
    with _JOB_DIRS_LOCK:
        _JOB_DIRS[job_id] = pinned
    lp = log_path_for(job_id)
    # Truncate/create the durable log up front so tail() always has a target.
    lp.write_text("", encoding="utf-8")

    if command:
        # Explicit control-plane argv (Wave 7): the op manifest already
        # resolved the exact command — no model-seam resolution applies.
        argv = [str(a) for a in command]
    else:
        argv = resolve_runner_cmd(extra_args, backend=backend, prompt=prompt,
                                  output_dir=output_dir, gated=gated,
                                  permission_mode=permission_mode,
                                  expected_artifacts=normalized_expected_artifacts)

    full_env = dict(os.environ)
    if env and backend != BACKEND_CHATGPT:
        full_env.update(env)
    # Propagate Anchor model-family prefs so foundry/trio seats (and any agent
    # reading CODING_FAMILY / REVIEW_FAMILY) honor the dashboard knobs.
    # Saved settings are authoritative and overwrite stale process/setx values.
    try:
        import anchor_settings as _aset
        for _k, _v in _aset.export_env_overrides().items():
            full_env[_k] = _v
    except Exception:
        pass
    if backend == BACKEND_GEMINI:
        full_env["TRIO_DRIVER"] = "gemini-cli-native"
    elif backend == BACKEND_CHATGPT:
        full_env["TRIO_DRIVER"] = "chatgpt-cli"
        full_env = _codex.subscription_only_env(full_env)
    
    crypt_token = uuid.uuid4().hex
    full_env["ANCHOR_SESSION_ID_CRYPT_TOKEN"] = crypt_token

    # On Windows, create a new process group so the whole tree is reapable and
    # signals/kills target the group. taskkill /T handles tree reap regardless,
    # but the flag keeps the child detached from our console.
    creationflags = 0
    if os.name == "nt":
        # CREATE_NO_WINDOW: a console-subsystem child (claude/gemini/python) must
        # never flash a visible window (John's standing no-visible-shells rule).
        creationflags = (getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                         | _paths.NO_WINDOW)

    # Gated Claude lanes keep stdin open for the initial prompt + gate answer.
    # One-shot ChatGPT gets a PIPE only long enough to deliver its raw prompt.
    use_stdin_pipe = bool(gated) or backend == BACKEND_CHATGPT
    proc = subprocess.Popen(
        argv,
        cwd=str(cwd) if cwd else None,
        stdin=(subprocess.PIPE if use_stdin_pipe else subprocess.DEVNULL),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=full_env,
        bufsize=1,
        text=True,
        # The runner emits UTF-8 (claude -p stream-json, em-dashes / smart quotes /
        # ☢ etc.). Without an explicit encoding, text mode uses the Windows locale
        # (cp1252) and mojibakes every non-ASCII char at capture time. Decode UTF-8
        # (replace any stray byte rather than crash the reader thread).
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
        # Own the adapter group on POSIX so cancellation cannot target Anchor's
        # server group. The adapter relays SIGTERM into Codex's child group.
        start_new_session=(os.name != "nt"),
    )

    live = _LiveJob(job_id, proc, lp, gated=gated)
    with _LIVE_LOCK:
        _LIVE[job_id] = live

    # Wrap the subprocess in a Job Object with KILL_ON_JOB_CLOSE (Windows only).
    # OPT-OUT: long-lived tool panels (e.g. tidy-idy Triage Panel) must survive
    # an Anchor/NSSM restart — KILL_ON_JOB_CLOSE would murder them the moment
    # the service process exits (observed 2026-07-22: every restart interrupted
    # mid-debate tidy jobs; remote Tailscale clients froze on corpse status).
    if os.name == "nt" and kill_on_job_close:
        try:
            import proc_probe
            live._h_job = proc_probe.attach_to_job_object(proc.pid)
        except Exception:
            live._h_job = None
    else:
        live._h_job = None

    # For a gated lane, deliver the initial prompt as a stream-json user turn on
    # stdin and register the (kept-open) pipe with the gate adapter so a later
    # answer writes into the SAME session. Deferred import avoids a cycle.
    if backend == BACKEND_CHATGPT and proc.stdin is not None:
        try:
            proc.stdin.write(prompt or "")
            proc.stdin.close()
        except (OSError, ValueError):
            pass
    elif use_stdin_pipe and proc.stdin is not None:
        try:
            if prompt:
                proc.stdin.write(_stream_json_user_turn(prompt))
                proc.stdin.flush()
            import gate_adapter as _ga
            _ga.register_stdin_sink(job_id, proc.stdin)
        except (OSError, ValueError, ImportError):
            # A dead/closed pipe (e.g. the mock exited instantly) is non-fatal —
            # the reader thread + finalize still record the terminal status.
            pass

    try:
        import proc_probe
        proc_create_time = proc_probe.creation_time(proc.pid)
    except Exception:
        proc_create_time = None

    # zombie-hunter v2: mint a sweepable session_registry record for this swarm
    # child, stamping the SAME identity (pid / proc_create_time / crypt_token) the
    # hunter's classify needs. Done here, at the single spawn site, so EVERY job
    # (direct launch() or launch_guarded()) participates. Cleared on exit by
    # _finalize/cancel via _mirror_session_status (the finally-reset).
    _register_swarm_session(job_id, proc.pid, proc_create_time, crypt_token,
                            cwd=cwd, backend=backend)

    rec = {
        "job_id": job_id,
        "lane": lane,
        "pid": proc.pid,
        "status": STATUS_RUNNING,
        "log_path": str(lp),
        "cwd": str(cwd) if cwd else None,
        "started_at": time.time(),
        "exit_code": None,
        "session_id": None,
        "backend": backend,
        "crypt_token": crypt_token,
        "proc_create_time": proc_create_time,
        # Durability 2026-07 Wave 1: everything a guarded launch needs to start
        # an equivalent job, so an interrupted record is re-launchable in ONE
        # call. project_id/folder_path (approved amendment 2026-07-02) are set
        # when the launch came through launch_guarded().
        "relaunch_spec": _build_relaunch_spec(
            lane, cwd, prompt, output_dir, gated, permission_mode, backend, env,
            project_id=project_id, folder_path=folder_path, command=command,
            expected_artifacts=normalized_expected_artifacts),
    }
    # W13 (C3): journal the launch. Use the project_id/folder_path PARAMETERS
    # (a guarded launch passes them) — the rec dict carries them only inside
    # relaunch_spec, so reading rec.get("project_id") here would always no-op.
    _journal.emit_safe(project_id or "", _journal.EV_JOB_LAUNCHED,
                       correlation_id=job_id or "x", folder_path=folder_path,
                       payload={"job_id": job_id, "lane": lane})
    _write_record(rec)

    live.reader = threading.Thread(
        target=_reader_loop, args=(live,), name=f"job-reader-{job_id}",
        daemon=True,
    )
    live.reader.start()
    return rec


def _reader_loop(live: _LiveJob) -> None:
    """Drain the subprocess stdout into the ring buffer + durable log.

    While draining, sniff each line for a stream-json ``result`` envelope and
    capture its cost/usage/duration onto the job record (Wave 7) so the effort
    history can roll cost up per-lane / per-project. The last ``result`` line
    wins (a session emits one terminal result envelope).

    BLOCKER FIX (gated lanes): for a GATED lane (``live.gated`` truthy) we also
    feed each line to ``gate_adapter.parse_event``; the FIRST ``AskUserQuestion``
    frame is persisted via ``gate_adapter.mark_awaiting_input`` so the job's gate
    ``state`` flips to ``awaiting-input`` and ``pending_prompt`` is stored. This
    is the ONLY production path that surfaces a gate from the live stream — before
    this, the reader merely logged the frame as a plain line and the prompt box
    (which renders solely on a non-null ``load_pending_prompt``) never appeared,
    so gated lanes were end-to-end dead. We gate this on ``live.gated`` so a
    research lane (non-gated) never acquires spurious gate state. The deferred
    import avoids a module import cycle (gate_adapter imports job_runner). We only
    mark the FIRST gate (``gate_marked``) — re-asks land in the log; the existing
    answer/continuation path advances ``state`` off awaiting-input.
    """
    proc = live.proc
    result_envelope = None
    gate_marked = False
    _ga = None
    if live.gated:
        try:
            import gate_adapter as _ga
        except ImportError:
            _ga = None
    # Runaway-log guard: a wedged/spewing job must not fill the disk. Past the
    # cap the durable file stops growing (one honest truncation marker); the
    # in-memory ring keeps serving the live tail.
    try:
        _log_cap = int(os.environ.get("ANCHOR_JOB_LOG_MAX_BYTES", "") or 50 * 1024 * 1024)
    except ValueError:
        _log_cap = 50 * 1024 * 1024
    _log_bytes = 0
    _log_capped = False
    try:
        with open(live.log_path, "a", encoding="utf-8") as logf:
            def _emit_line(text):
                nonlocal _log_bytes, _log_capped
                with live.lock:
                    live.ring.append(text)
                if _log_capped:
                    return
                if _log_bytes > _log_cap:
                    logf.write("!! anchor: durable log cap reached — further "
                               "output kept in the live ring only\n")
                    logf.flush()
                    _log_capped = True
                    return
                logf.write(text + "\n")
                logf.flush()
                _log_bytes += len(text) + 1

            for line in proc.stdout:
                line = line.rstrip("\n")
                _emit_line(line)
                env = _parse_result_envelope(line)
                if env is not None:
                    result_envelope = env
                # Gated lanes: surface the first AskUserQuestion gate from the
                # live stream into awaiting-input state (production wiring).
                # A parse/mark FAILURE is surfaced into the ring+log (2026-07
                # review: silently-eaten gate failures made a gated build look
                # gate-less instead of gate-broken).
                if _ga is not None and not gate_marked:
                    try:
                        prompts = _ga.parse_event(line)
                    except Exception as exc:
                        prompts = []
                        _emit_line("!! anchor: gate-event parse FAILED (%s) — a "
                                   "pending question may not surface; check the "
                                   "session" % (str(exc)[:120],))
                    if prompts:
                        try:
                            _ga.mark_awaiting_input(live.job_id, prompts[0])
                            gate_marked = True
                        except Exception as exc:
                            _emit_line("!! anchor: gate mark-awaiting FAILED (%s) "
                                       "— the dashboard will NOT show this gate; "
                                       "answer via the session terminal" %
                                       (str(exc)[:120],))
    except (ValueError, OSError):
        # Pipe closed underneath us (e.g. process tree-killed mid-read). Not
        # fatal — finalization below records the terminal status.
        pass
    finally:
        try:
            proc.stdout.close()
        except Exception:
            pass
        code = proc.wait()
        # Finalize the persisted record BEFORE signaling done, so a waiter that
        # unblocks on `done` always observes the terminal status.
        _finalize(live.job_id, code, result_envelope)
        live.done.set()


def _parse_result_envelope(line: str):
    """Return the cost fields from a stream-json ``result`` line, or ``None``.

    A real ``claude -p`` stream-json session ends with a ``{"type":"result", ...}``
    envelope carrying ``total_cost_usd``, ``usage``, ``duration_ms``, and
    ``session_id`` (spike-proven). The mock runner emits the same shape. Only
    well-formed JSON objects of ``type == "result"`` are recognized; everything
    else (plain content lines) is ignored cheaply.
    """
    s = line.strip()
    if not s.startswith("{"):
        return None
    if '"result"' not in s and '"stats"' not in s:
        return None
    try:
        obj = json.loads(s)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(obj, dict):
        return None
    if obj.get("type") != "result" and "stats" not in obj:
        return None
    return obj


def _cost_from_envelope(env: dict) -> dict:
    """Normalize a result envelope into the cost fields stored on a record.

    Returns ``{total_cost_usd, duration_ms, input_tokens, output_tokens,
    total_tokens, session_id}`` with safe defaults. Token counts come from the
    envelope's ``usage`` block.
    """
    usage = env.get("usage") or {}
    inp = usage.get("input_tokens") or 0
    out = usage.get("output_tokens") or 0

    # Gemini stats parsing
    stats = env.get("stats") or {}
    models = stats.get("models") or {}
    if models:
        for model_name, model_stats in models.items():
            if not isinstance(model_stats, dict):
                continue
            tokens = model_stats.get("tokens") or {}
            inp_val = tokens.get("input") or tokens.get("prompt")
            if inp_val is not None:
                inp = inp_val
            out_val = tokens.get("candidates")
            if out_val is not None:
                out = out_val

            api = model_stats.get("api") or {}
            latency = api.get("totalLatencyMs")
            if latency is not None:
                env["duration_ms"] = latency
            break

    try:
        inp = int(inp)
    except (TypeError, ValueError):
        inp = 0
    try:
        out = int(out)
    except (TypeError, ValueError):
        out = 0
    billing_mode = env.get("billing_mode") or \
        (env.get("model_receipt") or {}).get("billing_mode")
    cost_state = env.get("cost_state") or \
        (env.get("model_receipt") or {}).get("cost_state")
    raw_cost = env.get("total_cost_usd")
    if raw_cost is not None and not billing_mode and not cost_state:
        # The engine supplied a dollar field (including a genuine zero), so it is
        # measured rather than inferred from Anchor's own pricing table.
        billing_mode = "metered"
        cost_state = "engine_reported"
    if raw_cost is None and cost_state in (
            "subscription_covered", "no_seat_started"):
        cost = None
    else:
        try:
            cost = float(raw_cost or 0.0)
        except (TypeError, ValueError):
            cost = 0.0
    try:
        dur = int(env.get("duration_ms") or 0)
    except (TypeError, ValueError):
        dur = 0
    try:
        cached_inp = int(usage.get("cached_input_tokens") or 0)
    except (TypeError, ValueError):
        cached_inp = 0
    return {
        "total_cost_usd": cost,
        "billing_mode": billing_mode,
        "cost_state": cost_state,
        "duration_ms": dur,
        "input_tokens": inp,
        "cached_input_tokens": cached_inp,
        "output_tokens": out,
        "total_tokens": inp + out,
        "session_id": env.get("session_id"),
    }


# ── Swarm-job session registration (zombie-hunter v2) ────────────────────────
#
# Every job we spawn is a "swarm" sub-agent. Historically its identity
# (pid / proc_create_time / crypt_token) was written ONLY to the job store, so
# ``zombie_hunter.sweep`` — which reads ``session_registry.load_sessions()`` —
# could not see it (DESIGN.md gap). These two helpers close that gap: we mint a
# RUNNING session_registry record at spawn carrying the SAME identity, then clear
# it out of RUNNING when the job exits (the gandalf finally-reset analog) so a
# finished OR crashed swarm child is never left looking orphaned.

def _register_swarm_session(job_id, pid, proc_create_time, crypt_token,
                            cwd=None, backend=DEFAULT_BACKEND) -> None:
    """Register a spawned swarm job in ``session_registry`` (hunter-sweepable).

    Stamps the EXACT identity ``zombie_hunter.classify`` requires — ``pid``,
    ``proc_create_time`` (from the existing ``proc_probe`` reading taken at
    spawn), and the per-job ``crypt_token`` — keyed by the ``job_id`` as the
    session id. Best-effort: a registry failure must NEVER block a launch (so the
    job still runs; the hunter simply ABSTAINS on the un-stamped record).
    """
    try:
        import session_registry as _sr
        _sr.register_session(
            project_id="",
            lane=SWARM_LANE,
            backend=backend,
            status=_sr.STATUS_RUNNING,
            session_id=job_id,
            worktree_path=str(cwd) if cwd else "",
            pid=pid,
            proc_create_time=proc_create_time,
            crypt_token=crypt_token or "",
        )
    except Exception:  # pragma: no cover - registry is best-effort
        pass


_MODEL_RECEIPT_FIELDS = frozenset((
    "family_requested", "backend_requested", "transport_requested",
    "transport_actual", "executable_path", "executable_sha256",
    "executable_provenance_verified", "executable_provenance_kind",
    "executable_signer_subject", "executable_signer_certificate_sha256",
    "signer_image_binding_verified",
    "signature_revocation_freshness",
    "executable_handle_guarded_through_spawn",
    "preexecution_child_image_attested", "cli_version", "auth_kind",
    "auth_probe_at", "subscription_auth", "requested_model",
    "requested_effort", "requested_orchestration_mode",
    "orchestration_mode_served", "model_capability_verified",
    "ultra_capability_verified", "sandbox_requested",
    "approval_policy_requested", "model_provider_requested", "codex_home",
    "config_sha256",
    "user_config_loaded", "user_config_ignored", "critical_overrides_enforced",
    "config_guard_verified", "runtime_guard_rechecked",
    "child_env_allowlist_verified", "rules_ignored", "agents_disabled",
    "network_disabled", "extra_writable_roots_disabled",
    "hosted_tools_disabled", "mcp_servers_disabled", "projects_table_replaced",
    "thread_id", "duration_ms", "tree_kill_verified",
    "process_group_kill_verified", "output_drain_verified",
    "output_limits_verified", "output_eof_verified",
    "stdin_write_verified", "stdin_close_verified",
    "output_overflow_kind", "native_stdout_bytes", "native_stderr_bytes",
    "preflight_probe_count", "preflight_containment_kind",
    "preflight_complete_tree_containment",
    "preflight_no_inference_verified",
    "preflight_no_network_intent_verified",
    "preflight_output_limits_verified",
    "preflight_output_drain_verified", "preflight_root_exit_verified",
    "preflight_windows_job_policy_verified",
    "preflight_windows_job_assignment_verified",
    "preflight_windows_job_membership_verified",
    "preflight_windows_process_handle_verified",
    "preflight_windows_primary_thread_verified",
    "preflight_windows_process_resumed",
    "preflight_windows_job_empty_verified",
    "preflight_process_group_kill_verified",
    "containment_kind", "complete_tree_containment",
    "windows_job_policy_verified", "windows_job_assignment_verified",
    "windows_job_membership_verified", "windows_process_handle_verified",
    "windows_primary_thread_verified", "windows_process_resumed",
    "windows_execution_possible", "windows_job_empty_verified",
    "root_exit_verified",
    "exit_code", "status",
    "timed_out", "aborted", "seat_started", "fallback_from", "fallback_to", "cross_model",
    "billing_mode", "cost_state", "model_served", "reasoning_served",
    "model_attested", "degraded", "api_key_env_scrubbed", "prompt_sha256",
    "event_count", "malformed_count", "tool_error_count",
    "artifact_write_observed", "artifact_scan_complete",
    "usage", "artifact_paths",
    "expected_artifact_paths", "artifact_contract_verified",
    "artifact_mutation_verified", "artifact_hashes", "artifact_evidence",
    "error",
))

_CHATGPT_USAGE_FIELDS = (
    "input_tokens", "cached_input_tokens", "cache_write_input_tokens",
    "output_tokens", "reasoning_output_tokens",
)


def _chatgpt_telemetry_within_bounds(usage, event_count, malformed_count,
                                     tool_error_count) -> bool:
    """Bound hostile-child integer telemetry before persistence/aggregation."""
    if (not isinstance(usage, dict) or
            set(usage) != set(_CHATGPT_USAGE_FIELDS)):
        return False
    if any(type(usage.get(key)) is not int or usage[key] < 0 or
           usage[key] > _CHATGPT_MAX_TOKEN_FIELD
           for key in _CHATGPT_USAGE_FIELDS):
        return False
    if sum(usage[key] for key in _CHATGPT_USAGE_FIELDS) > _CHATGPT_MAX_TOKEN_SUM:
        return False
    counts = (event_count, malformed_count, tool_error_count)
    if any(type(value) is not int or value < 0 or
           value > _CHATGPT_MAX_EVENTS for value in counts):
        return False
    if malformed_count > event_count or tool_error_count > event_count:
        return False
    return True


def _valid_chatgpt_thread_id(value, allow_none=False) -> bool:
    """Accept only a small printable ASCII opaque id at the trust boundary."""
    if value is None:
        return bool(allow_none)
    return bool(
        isinstance(value, str) and
        len(value) <= _CHATGPT_MAX_THREAD_ID_CHARS and
        re.fullmatch(r"[A-Za-z0-9._:-]+", value)
    )


def _receipt_matches_required(receipt, required) -> bool:
    """Match fixed receipt values without allowing bool/int aliases."""
    for key, expected in required.items():
        if key not in receipt:
            return False
        observed = receipt.get(key)
        if type(expected) in (bool, int) and type(observed) is not type(expected):
            return False
        if observed != expected:
            return False
    return True

_CHATGPT_NO_SEAT_FAILURES = frozenset((
    "adapter_error", "executable_unavailable", "config_guard_failed",
    "preflight_timeout", "preflight_failed", "version_probe_failed",
    "subscription_auth_required", "catalog_probe_failed",
    "capability_unavailable", "spawn_error", "spawn_aborted",
    "signal_guard_unavailable", "executable_provenance_failed",
    "runtime_guard_failed", "config_guard_changed",
    "executable_guard_changed", "security_guard_failed",
    "artifact_contract_required", "artifact_scan_incomplete",
    "containment_assignment_failed",
    "preflight_command_refused", "preflight_containment_failed",
    "preflight_spawn_error", "preflight_cleanup_failed",
    "preflight_output_limit_exceeded", "preflight_aborted",
    "preflight_process_tree_straggler",
    "signal_guard_restore_failed",
))
_CHATGPT_SEAT_FAILURES = frozenset((
    "usage_limit", "auth_error", "cli_error", "protocol_error", "no_reply",
    "timeout", "aborted", "kill_failed", "spawn_error", "spawn_aborted",
    "signal_guard_unavailable",
    "signal_guard_restore_failed", "artifact_scan_incomplete",
    "artifact_required",
    "containment_assignment_failed", "process_tree_straggler",
    "output_limit_exceeded", "protocol_limit_exceeded",
    "output_drain_failed", "stdin_write_failed",
))


def _model_receipt_from_envelope(envelope):
    """Copy only the stable, non-secret receipt contract from a child result."""
    if not isinstance(envelope, dict):
        return None
    raw = envelope.get("model_receipt")
    if not isinstance(raw, dict):
        return None
    out = {}
    for key in _MODEL_RECEIPT_FIELDS:
        if key not in raw:
            continue
        value = raw.get(key)
        if value is None or isinstance(value, (str, int, float, bool)):
            out[key] = value
    usage = raw.get("usage")
    if isinstance(usage, dict):
        clean_usage = {}
        for key in _CHATGPT_USAGE_FIELDS:
            try:
                clean_usage[key] = int(usage.get(key) or 0)
            except (TypeError, ValueError):
                clean_usage[key] = 0
        out["usage"] = clean_usage
    for field in ("artifact_paths", "expected_artifact_paths"):
        values = raw.get(field)
        if isinstance(values, list):
            try:
                clean = _normalize_expected_artifacts(values)
            except ValueError:
                clean = None
            if clean is not None and clean == values:
                out[field] = clean
    hashes = raw.get("artifact_hashes")
    if isinstance(hashes, dict) and len(hashes) <= 32:
        clean_hashes = {}
        for key, value in hashes.items():
            if (not isinstance(key, str) or not isinstance(value, str) or
                    len(value) != 64 or
                    any(ch not in "0123456789abcdef" for ch in value)):
                clean_hashes = None
                break
            clean_hashes[key] = value
        if clean_hashes is not None:
            out["artifact_hashes"] = clean_hashes
    evidence = raw.get("artifact_evidence")
    if isinstance(evidence, dict) and len(evidence) <= 32:
        clean_evidence = {}
        for key, value in evidence.items():
            if (not isinstance(key, str) or not isinstance(value, dict) or
                    set(value) != {"sha256", "size", "device", "inode"}):
                clean_evidence = None
                break
            digest = value.get("sha256")
            size = value.get("size")
            device = value.get("device")
            inode = value.get("inode")
            if (not isinstance(digest, str) or len(digest) != 64 or
                    any(ch not in "0123456789abcdef" for ch in digest) or
                    type(size) is not int or size < 0 or
                    size > int(getattr(_codex, "MAX_ARTIFACT_BYTES", 64 * 1024 * 1024)) or
                    type(device) is not int or device < 0 or
                    type(inode) is not int or inode < 0):
                clean_evidence = None
                break
            clean_evidence[key] = {
                "sha256": digest, "size": size,
                "device": device, "inode": inode,
            }
        if clean_evidence is not None:
            out["artifact_evidence"] = clean_evidence
    return out


def _artifact_contract_from_record(record, expected_sandbox):
    """Return the server-owned canonical completion paths or ``None``."""
    spec = ((record or {}).get("relaunch_spec") or {})
    raw = spec.get("expected_artifacts")
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        return None
    try:
        clean = _normalize_expected_artifacts(raw)
    except ValueError:
        return None
    if clean != raw:
        return None
    if expected_sandbox == "workspace-write" and not clean:
        return None
    if expected_sandbox == "read-only" and clean:
        return None
    return clean


def _hash_current_artifact(output_root, relative):
    """Hash one nonempty regular file beneath the pinned output root."""
    try:
        root = Path(output_root).resolve(strict=True)
        candidate = root / relative
        if candidate.is_symlink():
            return None
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
        if not resolved.is_file():
            return None
        limit = int(getattr(_codex, "MAX_ARTIFACT_SCAN_BYTES", 512 * 1024 * 1024))
        size = resolved.stat().st_size
        if size <= 0 or size > limit:
            return None
        digest = hashlib.sha256()
        seen = 0
        with resolved.open("rb") as fh:
            before = os.fstat(fh.fileno())
            while True:
                chunk = fh.read(1024 * 1024)
                if not chunk:
                    break
                seen += len(chunk)
                if seen > limit:
                    return None
                digest.update(chunk)
            after = os.fstat(fh.fileno())
        if (seen <= 0 or before.st_size != seen or after.st_size != seen or
                getattr(before, "st_mtime_ns", None) !=
                getattr(after, "st_mtime_ns", None)):
            return None
        return digest.hexdigest()
    except (OSError, RuntimeError, TypeError, ValueError):
        return None


def _current_artifact_snapshot(output_root, relatives):
    """Re-attest named artifacts while holding the exact workspace root."""
    guard = None
    result = None
    try:
        root = Path(output_root).resolve(strict=True)
        guard = _codex._open_guarded_directory(root)
        identity = _codex._guarded_directory_identity(guard, root)
        snapshot, complete = _codex._expected_artifact_snapshot(
            root, tuple(relatives), identity)
        if complete and _codex._workspace_root_matches(root, identity):
            result = snapshot
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        result = None
    finally:
        if guard is not None:
            try:
                guard.close()
            except BaseException:
                result = None
    return result


def _valid_current_chatgpt_provenance(receipt) -> bool:
    """Independently bind child provenance claims to the current Codex image."""
    if not isinstance(receipt, dict):
        return False
    if receipt.get("config_sha256") is not None or \
            receipt.get("user_config_loaded") is not False:
        return False
    try:
        expected_executable = Path(_codex.resolve_codex_cmd()).resolve(strict=True)
        actual_executable = Path(receipt.get("executable_path") or "").resolve(
            strict=True)
        current = _codex.inspect_executable(str(expected_executable))
        clean_env = _codex.subscription_only_env()
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        return False
    if (os.path.normcase(str(actual_executable)) !=
            os.path.normcase(str(expected_executable)) or
            not isinstance(current, dict) or current.get("ok") is not True):
        return False
    fingerprint = current.get("executable_fingerprint") or {}
    fields = {
        "executable_sha256": fingerprint.get("sha256"),
        "executable_provenance_kind": current.get(
            "executable_provenance_kind"),
        "executable_signer_subject": current.get("executable_signer_subject"),
        "executable_signer_certificate_sha256": current.get(
            "executable_signer_certificate_sha256"),
        "signer_image_binding_verified": bool(
            current.get("signer_image_binding_verified")),
        "signature_revocation_freshness": current.get(
            "signature_revocation_freshness"),
        "codex_home": clean_env.get("CODEX_HOME"),
    }
    return bool(
        receipt.get("executable_provenance_verified") is True and
        all(receipt.get(key) == value for key, value in fields.items())
    )


_CHATGPT_CONTAINMENT_BOOL_FIELDS = (
    "complete_tree_containment", "windows_job_policy_verified",
    "windows_job_assignment_verified", "windows_job_membership_verified",
    "windows_process_handle_verified", "windows_primary_thread_verified",
    "windows_process_resumed", "windows_execution_possible",
    "windows_job_empty_verified", "root_exit_verified",
)

_CHATGPT_PREFLIGHT_BOOL_FIELDS = (
    "preflight_complete_tree_containment",
    "preflight_no_inference_verified",
    "preflight_no_network_intent_verified",
    "preflight_output_limits_verified",
    "preflight_output_drain_verified", "preflight_root_exit_verified",
    "preflight_windows_job_policy_verified",
    "preflight_windows_job_assignment_verified",
    "preflight_windows_job_membership_verified",
    "preflight_windows_process_handle_verified",
    "preflight_windows_primary_thread_verified",
    "preflight_windows_process_resumed",
    "preflight_windows_job_empty_verified",
)

_CHATGPT_RUNTIME_IO_FIELDS = (
    "output_limits_verified", "output_eof_verified",
    "stdin_write_verified", "stdin_close_verified",
)


def _valid_chatgpt_io_shape(receipt) -> bool:
    if any(receipt.get(key) is not None and type(receipt.get(key)) is not bool
           for key in _CHATGPT_RUNTIME_IO_FIELDS):
        return False
    overflow = receipt.get("output_overflow_kind")
    if overflow not in (None, "stdout", "stderr", "aggregate"):
        return False
    stdout_bytes = receipt.get("native_stdout_bytes")
    stderr_bytes = receipt.get("native_stderr_bytes")
    return bool(
        type(stdout_bytes) is int and 0 <= stdout_bytes <=
        int(getattr(_codex, "MAX_NATIVE_STDOUT_BYTES", 32 * 1024 * 1024)) + 1 and
        type(stderr_bytes) is int and 0 <= stderr_bytes <=
        int(getattr(_codex, "MAX_NATIVE_STDERR_BYTES", 8 * 1024 * 1024)) + 1
    )


def _valid_chatgpt_preflight_shape(receipt) -> bool:
    count = receipt.get("preflight_probe_count")
    kind = receipt.get("preflight_containment_kind")
    group = receipt.get("preflight_process_group_kill_verified")
    return bool(
        type(count) is int and 0 <= count <= 3 and
        kind in (None, "windows_job", "posix_process_group_degraded") and
        all(type(receipt.get(key)) is bool
            for key in _CHATGPT_PREFLIGHT_BOOL_FIELDS) and
        (group is None or type(group) is bool)
    )


def _valid_chatgpt_success_preflight(receipt) -> bool:
    if not _valid_chatgpt_preflight_shape(receipt):
        return False
    common = (
        receipt.get("preflight_probe_count") == 3 and
        receipt.get("preflight_no_inference_verified") is True and
        receipt.get("preflight_no_network_intent_verified") is True and
        receipt.get("preflight_output_limits_verified") is True and
        receipt.get("preflight_output_drain_verified") is True and
        receipt.get("preflight_root_exit_verified") is True
    )
    if not common:
        return False
    windows_fields = (
        "preflight_windows_job_policy_verified",
        "preflight_windows_job_assignment_verified",
        "preflight_windows_job_membership_verified",
        "preflight_windows_process_handle_verified",
        "preflight_windows_primary_thread_verified",
        "preflight_windows_process_resumed",
        "preflight_windows_job_empty_verified",
    )
    if os.name == "nt":
        return bool(
            receipt.get("preflight_containment_kind") == "windows_job" and
            receipt.get("preflight_complete_tree_containment") is True and
            all(receipt.get(key) is True for key in windows_fields) and
            receipt.get("preflight_process_group_kill_verified") is None
        )
    return bool(
        receipt.get("preflight_containment_kind") ==
        "posix_process_group_degraded" and
        receipt.get("preflight_complete_tree_containment") is False and
        all(receipt.get(key) is False for key in windows_fields) and
        receipt.get("preflight_process_group_kill_verified") is None
    )


def _valid_chatgpt_success_io(receipt) -> bool:
    if not _valid_chatgpt_io_shape(receipt):
        return False
    stdout_bytes = receipt["native_stdout_bytes"]
    stderr_bytes = receipt["native_stderr_bytes"]
    return bool(
        all(receipt.get(key) is True for key in _CHATGPT_RUNTIME_IO_FIELDS) and
        receipt.get("output_overflow_kind") is None and
        stdout_bytes <= int(getattr(
            _codex, "MAX_NATIVE_STDOUT_BYTES", 32 * 1024 * 1024)) and
        stderr_bytes <= int(getattr(
            _codex, "MAX_NATIVE_STDERR_BYTES", 8 * 1024 * 1024)) and
        stdout_bytes + stderr_bytes <= int(getattr(
            _codex, "MAX_NATIVE_OUTPUT_BYTES", 36 * 1024 * 1024))
    )


def _valid_chatgpt_no_seat_io(receipt) -> bool:
    return bool(
        _valid_chatgpt_io_shape(receipt) and
        all(receipt.get(key) is None for key in _CHATGPT_RUNTIME_IO_FIELDS) and
        receipt.get("output_overflow_kind") is None and
        receipt.get("native_stdout_bytes") == 0 and
        receipt.get("native_stderr_bytes") == 0
    )


def _valid_chatgpt_no_seat_preflight(receipt, status) -> bool:
    if not _valid_chatgpt_preflight_shape(receipt):
        return False
    count = receipt["preflight_probe_count"]
    kind = receipt.get("preflight_containment_kind")
    windows_fields = (
        "preflight_windows_job_policy_verified",
        "preflight_windows_job_assignment_verified",
        "preflight_windows_job_membership_verified",
        "preflight_windows_process_handle_verified",
        "preflight_windows_primary_thread_verified",
        "preflight_windows_process_resumed",
        "preflight_windows_job_empty_verified",
    )
    if count == 0:
        return bool(
            kind is None and
            all(receipt.get(key) is False
                for key in _CHATGPT_PREFLIGHT_BOOL_FIELDS) and
            receipt.get("preflight_process_group_kill_verified") is None
        )
    expected_kind = ("windows_job" if os.name == "nt"
                     else "posix_process_group_degraded")
    if (kind != expected_kind or
            receipt.get("preflight_no_inference_verified") is not True or
            receipt.get("preflight_no_network_intent_verified") is not True):
        return False
    if os.name == "nt":
        if receipt.get("preflight_process_group_kill_verified") is not None:
            return False
    elif (receipt.get("preflight_complete_tree_containment") is not False or
            any(receipt.get(key) is not False for key in windows_fields)):
        return False
    if status == "preflight_output_limit_exceeded":
        return bool(
            receipt.get("preflight_output_limits_verified") is False and
            receipt.get("preflight_output_drain_verified") is True and
            receipt.get("preflight_root_exit_verified") is True
        )
    if status == "preflight_cleanup_failed":
        # This is a negative result, never an upgrade to a usable seat. The
        # producer also uses it when the final Job handle close fails, or when
        # degraded POSIX group cleanup cannot be proven, neither of which has a
        # separate positive receipt field. Preserve that honest refusal even if
        # root exit and pipe drain were otherwise observed.
        return True
    if status == "preflight_containment_failed":
        return receipt.get("preflight_complete_tree_containment") is False
    if status == "preflight_spawn_error":
        return bool(
            receipt.get("preflight_output_drain_verified") is False and
            receipt.get("preflight_root_exit_verified") is False)
    if status in ("preflight_timeout", "preflight_aborted",
                  "preflight_process_tree_straggler"):
        return bool(
            receipt.get("preflight_output_limits_verified") is True and
            receipt.get("preflight_output_drain_verified") is True and
            receipt.get("preflight_root_exit_verified") is True)
    if (receipt.get("preflight_output_limits_verified") is not True or
            receipt.get("preflight_output_drain_verified") is not True or
            receipt.get("preflight_root_exit_verified") is not True):
        return False
    if os.name == "nt":
        return bool(
            receipt.get("preflight_complete_tree_containment") is True and
            all(receipt.get(key) is True for key in windows_fields))
    return True


def _valid_chatgpt_failure_io(receipt, status) -> bool:
    if not _valid_chatgpt_io_shape(receipt):
        return False
    limits = receipt.get("output_limits_verified")
    eof = receipt.get("output_eof_verified")
    drain = receipt.get("output_drain_verified")
    write = receipt.get("stdin_write_verified")
    close = receipt.get("stdin_close_verified")
    overflow = receipt.get("output_overflow_kind")
    stdout_bytes = receipt["native_stdout_bytes"]
    stderr_bytes = receipt["native_stderr_bytes"]
    stdout_limit = int(getattr(
        _codex, "MAX_NATIVE_STDOUT_BYTES", 32 * 1024 * 1024))
    stderr_limit = int(getattr(
        _codex, "MAX_NATIVE_STDERR_BYTES", 8 * 1024 * 1024))
    aggregate_limit = int(getattr(
        _codex, "MAX_NATIVE_OUTPUT_BYTES", 36 * 1024 * 1024))
    if status == "output_limit_exceeded":
        overflow_matches = (
            (overflow == "stdout" and stdout_bytes > stdout_limit) or
            (overflow == "stderr" and stderr_bytes > stderr_limit) or
            (overflow == "aggregate" and
             stdout_bytes + stderr_bytes > aggregate_limit)
        )
        return bool(
            limits is False and overflow_matches and eof is True and
            drain is True)
    if status == "output_drain_failed":
        return bool(
            overflow is None and (drain is False or eof is False))
    if status == "stdin_write_failed":
        return bool(
            limits is True and eof is True and drain is True and
            overflow is None and (write is False or close is False))
    if status == "protocol_limit_exceeded":
        return bool(
            limits is True and eof is True and drain is True and
            write is True and close is True and overflow is None and
            stdout_bytes <= stdout_limit and stderr_bytes <= stderr_limit and
            stdout_bytes + stderr_bytes <= aggregate_limit)
    if status in ("timeout", "aborted"):
        return bool(
            limits is True and eof is True and drain is True and
            close is True and overflow is None)
    if status == "kill_failed":
        return True
    return bool(
        limits is True and eof is True and drain is True and
        write is True and close is True and overflow is None and
        stdout_bytes <= stdout_limit and stderr_bytes <= stderr_limit and
        stdout_bytes + stderr_bytes <= aggregate_limit
    )


def _valid_chatgpt_success_containment(receipt) -> bool:
    """Require platform-accurate process-tree evidence for a successful seat."""
    if any(type(receipt.get(key)) is not bool
           for key in _CHATGPT_CONTAINMENT_BOOL_FIELDS):
        return False
    if (receipt.get("tree_kill_verified") is not None or
            receipt.get("process_group_kill_verified") is not None or
            receipt.get("output_drain_verified") is not True):
        return False
    if os.name == "nt":
        return bool(
            receipt.get("containment_kind") == "windows_job" and
            all(receipt.get(key) is True for key in (
                "complete_tree_containment", "windows_job_policy_verified",
                "windows_job_assignment_verified",
                "windows_job_membership_verified",
                "windows_process_handle_verified",
                "windows_primary_thread_verified", "windows_process_resumed",
                "windows_execution_possible", "windows_job_empty_verified",
                "root_exit_verified",
            ))
        )
    return bool(
        receipt.get("containment_kind") == "posix_process_group_degraded" and
        receipt.get("complete_tree_containment") is False and
        all(receipt.get(key) is False for key in (
            "windows_job_policy_verified", "windows_job_assignment_verified",
            "windows_job_membership_verified", "windows_process_handle_verified",
            "windows_primary_thread_verified", "windows_process_resumed",
            "windows_execution_possible", "windows_job_empty_verified",
            "root_exit_verified",
        ))
    )


def _valid_chatgpt_failure_containment(receipt, status, seat_started) -> bool:
    """Validate partial/terminal containment facts without upgrading failures."""
    if any(type(receipt.get(key)) is not bool
           for key in _CHATGPT_CONTAINMENT_BOOL_FIELDS):
        return False
    group_verified = receipt.get("process_group_kill_verified")
    if group_verified is not None and type(group_verified) is not bool:
        return False
    kind = receipt.get("containment_kind")
    if kind not in (None, "windows_job", "posix_process_group_degraded"):
        return False
    if os.name == "nt":
        if group_verified is not None or kind == "posix_process_group_degraded":
            return False
        if seat_started:
            if (kind != "windows_job" or
                    receipt.get("windows_job_policy_verified") is not True or
                    receipt.get("windows_job_assignment_verified") is not True or
                    receipt.get("windows_job_membership_verified") is not True or
                    receipt.get("windows_process_handle_verified") is not True or
                    receipt.get("windows_primary_thread_verified") is not True or
                    receipt.get("windows_execution_possible") is not True or
                    receipt.get("complete_tree_containment") is not True):
                return False
            if status != "kill_failed" and (
                    receipt.get("windows_job_empty_verified") is not True or
                    receipt.get("root_exit_verified") is not True):
                return False
        else:
            if (receipt.get("windows_process_resumed") is not False or
                    receipt.get("windows_execution_possible") is not False):
                return False
            if kind is None and any(receipt.get(key) is not False for key in (
                    "complete_tree_containment", "windows_job_policy_verified",
                    "windows_job_assignment_verified",
                    "windows_job_membership_verified",
                    "windows_process_handle_verified",
                    "windows_primary_thread_verified",
                    "windows_job_empty_verified", "root_exit_verified")):
                return False
        return True
    if (kind == "windows_job" or
            any(receipt.get(key) is not False for key in (
                "complete_tree_containment", "windows_job_policy_verified",
                "windows_job_assignment_verified",
                "windows_job_membership_verified",
                "windows_process_handle_verified",
                "windows_primary_thread_verified", "windows_process_resumed",
                "windows_execution_possible", "windows_job_empty_verified",
                "root_exit_verified"))):
        return False
    if seat_started:
        return kind == "posix_process_group_degraded"
    # POSIX stamps the intended process-group boundary before Popen. A spawn
    # failure therefore has no seat but can honestly retain that degraded kind.
    return kind in (None, "posix_process_group_degraded")


def _valid_chatgpt_success_envelope(envelope, record,
                                    adapter_exit_code) -> bool:
    """Fail closed unless a ChatGPT job proves the dedicated adapter contract."""
    if type(adapter_exit_code) is not int or adapter_exit_code != 0:
        return False
    if not isinstance(envelope, dict) or envelope.get("type") != "result":
        return False
    if envelope.get("subtype") != "success":
        return False
    if envelope.get("is_error") is not False:
        return False
    if not isinstance(envelope.get("result"), str) or not envelope["result"].strip():
        return False
    receipt = envelope.get("model_receipt")
    if not isinstance(receipt, dict):
        return False
    if any(key not in receipt for key in
           (_MODEL_RECEIPT_FIELDS - {"error"})):
        return False
    spec = ((record or {}).get("relaunch_spec") or {})
    expected_sandbox = (
        "read-only" if spec.get("permission_mode") == "plan"
        else "workspace-write"
    )
    required = {
        "family_requested": BACKEND_CHATGPT,
        "backend_requested": BACKEND_CHATGPT,
        "transport_requested": "codex-cli",
        "transport_actual": "codex-cli",
        "auth_kind": "chatgpt_subscription",
        "subscription_auth": True,
        "requested_model": _codex.CODEX_MODEL,
        "requested_effort": _codex.CODEX_EFFORT,
        "requested_orchestration_mode": "ultra",
        "orchestration_mode_served": None,
        "model_capability_verified": True,
        "ultra_capability_verified": True,
        "sandbox_requested": expected_sandbox,
        "approval_policy_requested": "never",
        "model_provider_requested": "openai",
        "config_sha256": None,
        "user_config_loaded": False,
        "user_config_ignored": True,
        "critical_overrides_enforced": True,
        "config_guard_verified": True,
        "runtime_guard_rechecked": True,
        "child_env_allowlist_verified": True,
        "rules_ignored": True,
        "agents_disabled": True,
        "network_disabled": True,
        "extra_writable_roots_disabled": True,
        "hosted_tools_disabled": True,
        "mcp_servers_disabled": True,
        "projects_table_replaced": True,
        "executable_provenance_verified": True,
        "executable_handle_guarded_through_spawn": True,
        "preexecution_child_image_attested": False,
        "status": "success",
        "seat_started": True,
        "exit_code": 0,
        "timed_out": False,
        "aborted": False,
        "fallback_from": None,
        "fallback_to": None,
        "cross_model": None,
        "billing_mode": "subscription",
        "cost_state": "subscription_covered",
        "model_served": None,
        "reasoning_served": None,
        "model_attested": False,
        "degraded": True,
        "api_key_env_scrubbed": True,
        "artifact_scan_complete": True,
    }
    if not _receipt_matches_required(receipt, required):
        return False
    security_flags = (
        "user_config_loaded", "user_config_ignored",
        "critical_overrides_enforced",
        "config_guard_verified", "runtime_guard_rechecked",
        "child_env_allowlist_verified", "rules_ignored", "agents_disabled",
        "network_disabled", "extra_writable_roots_disabled",
        "hosted_tools_disabled", "mcp_servers_disabled",
        "projects_table_replaced", "executable_provenance_verified",
        "signer_image_binding_verified",
        "executable_handle_guarded_through_spawn",
        "preexecution_child_image_attested", "api_key_env_scrubbed",
        "artifact_contract_verified", "artifact_mutation_verified",
        *_CHATGPT_CONTAINMENT_BOOL_FIELDS,
    )
    if any(type(receipt.get(key)) is not bool for key in security_flags):
        return False
    if (envelope.get("billing_mode") != receipt.get("billing_mode") or
            envelope.get("cost_state") != receipt.get("cost_state") or
            envelope.get("total_cost_usd") is not None):
        return False
    if (not _valid_current_chatgpt_provenance(receipt) or
            not _valid_chatgpt_success_containment(receipt) or
            not _valid_chatgpt_success_preflight(receipt) or
            not _valid_chatgpt_success_io(receipt)):
        return False
    prompt = spec.get("prompt")
    if not isinstance(prompt, str):
        return False
    expected_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    if receipt.get("prompt_sha256") != expected_hash:
        return False
    thread_id = receipt.get("thread_id")
    if (not _valid_chatgpt_thread_id(thread_id) or
            envelope.get("session_id") != thread_id):
        return False
    usage = receipt.get("usage")
    envelope_usage = envelope.get("usage")
    if (not isinstance(usage, dict) or not isinstance(envelope_usage, dict) or
            set(usage) != set(_CHATGPT_USAGE_FIELDS) or
            set(envelope_usage) != set(_CHATGPT_USAGE_FIELDS)):
        return False
    if envelope_usage != usage:
        return False
    duration = envelope.get("duration_ms")
    receipt_duration = receipt.get("duration_ms")
    max_duration = (int(getattr(_codex, "DEFAULT_TIMEOUT_SECONDS", 2700)) + 60) * 1000
    if (type(duration) is not int or type(receipt_duration) is not int or
            duration != receipt_duration or duration < 0 or
            duration > max_duration):
        return False
    if (not _chatgpt_telemetry_within_bounds(
            usage, receipt.get("event_count"),
            receipt.get("malformed_count"),
            receipt.get("tool_error_count")) or
            receipt["event_count"] < 3):
        return False

    expected_artifacts = _artifact_contract_from_record(record, expected_sandbox)
    artifacts = receipt.get("artifact_paths")
    receipt_expected = receipt.get("expected_artifact_paths")
    artifact_hashes = receipt.get("artifact_hashes")
    artifact_evidence = receipt.get("artifact_evidence")
    mutation_verified = receipt.get("artifact_mutation_verified")
    contract_verified = receipt.get("artifact_contract_verified")
    if (expected_artifacts is None or not isinstance(artifacts, list) or
            not isinstance(receipt_expected, list) or
            not isinstance(artifact_hashes, dict) or
            not isinstance(artifact_evidence, dict) or
            type(mutation_verified) is not bool or
            type(contract_verified) is not bool or
            mutation_verified is not contract_verified or
            receipt_expected != expected_artifacts):
        return False
    if expected_sandbox == "read-only":
        return bool(
            receipt.get("artifact_write_observed") is False and
            mutation_verified is False and
            not artifacts and not artifact_hashes and not artifact_evidence and
            not expected_artifacts
        )
    if (receipt.get("artifact_write_observed") is not True or
            mutation_verified is not True or
            artifacts != expected_artifacts or
            set(artifact_hashes) != set(expected_artifacts) or
            set(artifact_evidence) != set(expected_artifacts)):
        return False
    output_raw = spec.get("output_dir")
    if not isinstance(output_raw, str):
        return False
    output_root = Path(output_raw).resolve()
    current_evidence = _current_artifact_snapshot(output_root, expected_artifacts)
    if current_evidence is None or current_evidence != artifact_evidence:
        return False
    return all(
        artifact_hashes.get(rel) == artifact_evidence[rel].get("sha256")
        for rel in expected_artifacts
    )


def _valid_chatgpt_failure_envelope(envelope, record,
                                    adapter_exit_code=None) -> bool:
    """Validate an adapter error receipt without weakening success acceptance.

    Failure envelopes may carry useful no-seat/quota/termination evidence, but
    they cross the same hostile child boundary as success. Only the adapter's
    closed status vocabulary and internally-consistent, prompt-bound telemetry
    are accepted. Dollar cost is always unpriced/null.
    """
    if (not isinstance(envelope, dict) or envelope.get("type") != "result" or
            envelope.get("subtype") != "error" or
            envelope.get("is_error") is not True or
            not isinstance(envelope.get("result"), str)):
        return False
    if (adapter_exit_code is not None and
            (type(adapter_exit_code) is not int or adapter_exit_code == 0)):
        return False
    receipt = envelope.get("model_receipt")
    if not isinstance(receipt, dict):
        return False
    if any(key not in receipt for key in _MODEL_RECEIPT_FIELDS):
        return False
    status = receipt.get("status")
    seat_started = receipt.get("seat_started")
    if type(seat_started) is not bool:
        return False
    allowed = (_CHATGPT_SEAT_FAILURES if seat_started
               else _CHATGPT_NO_SEAT_FAILURES)
    if status not in allowed:
        return False
    if (not _valid_chatgpt_io_shape(receipt) or
            not _valid_chatgpt_preflight_shape(receipt)):
        return False

    spec = ((record or {}).get("relaunch_spec") or {})
    expected_sandbox = (
        "read-only" if spec.get("permission_mode") == "plan"
        else "workspace-write"
    )
    required = {
        "family_requested": BACKEND_CHATGPT,
        "backend_requested": BACKEND_CHATGPT,
        "transport_requested": "codex-cli",
        "requested_model": _codex.CODEX_MODEL,
        "requested_effort": _codex.CODEX_EFFORT,
        "requested_orchestration_mode": "ultra",
        "orchestration_mode_served": None,
        "sandbox_requested": expected_sandbox,
        "approval_policy_requested": "never",
        "model_provider_requested": "openai",
        "config_sha256": None,
        "user_config_loaded": False,
        "fallback_from": None,
        "fallback_to": None,
        "cross_model": None,
        "model_served": None,
        "reasoning_served": None,
        "model_attested": False,
        "degraded": True,
    }
    if not _receipt_matches_required(receipt, required):
        return False
    security_flags = (
        "user_config_loaded", "user_config_ignored",
        "critical_overrides_enforced",
        "config_guard_verified", "runtime_guard_rechecked",
        "child_env_allowlist_verified", "rules_ignored", "agents_disabled",
        "network_disabled", "extra_writable_roots_disabled",
        "hosted_tools_disabled", "mcp_servers_disabled",
        "projects_table_replaced", "executable_provenance_verified",
        "signer_image_binding_verified",
        "executable_handle_guarded_through_spawn",
        "preexecution_child_image_attested", "api_key_env_scrubbed",
        "artifact_contract_verified", "artifact_mutation_verified",
        *_CHATGPT_CONTAINMENT_BOOL_FIELDS,
    )
    if any(type(receipt.get(key)) is not bool for key in security_flags):
        return False
    auth_probe_at = receipt.get("auth_probe_at")
    if (not isinstance(auth_probe_at, str) or not auth_probe_at.strip() or
            len(auth_probe_at) > 80 or "\n" in auth_probe_at or
            "\r" in auth_probe_at):
        return False
    subscription_auth = receipt.get("subscription_auth")
    if (receipt.get("transport_actual") not in (None, "codex-cli") or
            receipt.get("auth_kind") not in (None, "chatgpt_subscription") or
            (subscription_auth is not None and
             type(subscription_auth) is not bool) or
            type(receipt.get("model_capability_verified")) is not bool or
            type(receipt.get("ultra_capability_verified")) is not bool or
            type(receipt.get("config_guard_verified")) is not bool or
            type(receipt.get("critical_overrides_enforced")) is not bool):
        return False
    if (receipt["critical_overrides_enforced"] and
            not receipt["config_guard_verified"]):
        return False
    if (receipt["ultra_capability_verified"] and
            not receipt["model_capability_verified"]):
        return False
    if ((receipt.get("subscription_auth") is True) !=
            (receipt.get("auth_kind") == "chatgpt_subscription")):
        return False
    cli_version = receipt.get("cli_version")
    if (cli_version is not None and
            (not isinstance(cli_version, str) or len(cli_version) > 200 or
             "\n" in cli_version or "\r" in cli_version)):
        return False
    error = receipt.get("error")
    if not isinstance(error, str) or not error.strip() or len(error) > 500:
        return False

    prompt = spec.get("prompt")
    if not isinstance(prompt, str):
        return False
    expected_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    if receipt.get("prompt_sha256") != expected_hash:
        return False

    executable = receipt.get("executable_path")
    if status in ("adapter_error", "executable_unavailable"):
        if executable is not None:
            return False
    else:
        try:
            expected_executable = Path(_codex.resolve_codex_cmd()).resolve()
            actual_executable = Path(executable or "").resolve()
        except (OSError, RuntimeError, TypeError, ValueError):
            return False
        if (os.path.normcase(str(actual_executable)) !=
                os.path.normcase(str(expected_executable))):
            return False
    if receipt.get("executable_provenance_verified") is True:
        if not _valid_current_chatgpt_provenance(receipt):
            return False
    elif (any(receipt.get(key) is not None for key in (
            "executable_sha256", "executable_provenance_kind",
            "executable_signer_subject",
            "executable_signer_certificate_sha256",
            "signature_revocation_freshness")) or
            receipt.get("signer_image_binding_verified") is not False):
        return False
    if (receipt.get("runtime_guard_rechecked") is True and
            (receipt.get("user_config_ignored") is not True or
             receipt.get("executable_provenance_verified") is not True)):
        return False

    usage = receipt.get("usage")
    envelope_usage = envelope.get("usage")
    if (not isinstance(usage, dict) or not isinstance(envelope_usage, dict) or
            set(usage) != set(_CHATGPT_USAGE_FIELDS) or
            set(envelope_usage) != set(_CHATGPT_USAGE_FIELDS) or
            envelope_usage != usage):
        return False
    duration = envelope.get("duration_ms")
    receipt_duration = receipt.get("duration_ms")
    max_duration = (int(getattr(_codex, "DEFAULT_TIMEOUT_SECONDS", 2700)) + 60) * 1000
    if (type(duration) is not int or type(receipt_duration) is not int or
            duration != receipt_duration or duration < 0 or
            duration > max_duration):
        return False
    if envelope.get("total_cost_usd") is not None:
        return False

    thread_id = receipt.get("thread_id")
    if not _valid_chatgpt_thread_id(thread_id, allow_none=True):
        return False
    if envelope.get("session_id") != thread_id:
        return False
    if not _chatgpt_telemetry_within_bounds(
            usage, receipt.get("event_count"),
            receipt.get("malformed_count"), receipt.get("tool_error_count")):
        return False
    native_exit = receipt.get("exit_code")
    if native_exit is not None and type(native_exit) is not int:
        return False
    tree_kill_verified = receipt.get("tree_kill_verified")
    if (type(receipt.get("timed_out")) is not bool or
            type(receipt.get("aborted")) is not bool or
            (tree_kill_verified is not None and
             type(tree_kill_verified) is not bool)):
        return False
    if not _valid_chatgpt_failure_containment(receipt, status, seat_started):
        return False

    if seat_started:
        if (not _valid_chatgpt_success_preflight(receipt) or
                not _valid_chatgpt_failure_io(receipt, status)):
            return False
        if (receipt.get("transport_actual") != "codex-cli" or
                receipt.get("auth_kind") != "chatgpt_subscription" or
                receipt.get("subscription_auth") is not True or
                receipt.get("model_capability_verified") is not True or
                receipt.get("ultra_capability_verified") is not True or
                receipt.get("config_guard_verified") is not True or
                receipt.get("user_config_ignored") is not True or
                receipt.get("runtime_guard_rechecked") is not True or
                receipt.get("child_env_allowlist_verified") is not True or
                receipt.get("critical_overrides_enforced") is not True or
                receipt.get("rules_ignored") is not True or
                receipt.get("agents_disabled") is not True or
                receipt.get("network_disabled") is not True or
                receipt.get("extra_writable_roots_disabled") is not True or
                receipt.get("hosted_tools_disabled") is not True or
                receipt.get("mcp_servers_disabled") is not True or
                receipt.get("projects_table_replaced") is not True or
                receipt.get("executable_provenance_verified") is not True or
                receipt.get("signer_image_binding_verified") is not
                (os.name == "nt") or
                receipt.get("executable_handle_guarded_through_spawn") is not True or
                receipt.get("preexecution_child_image_attested") is not False or
                receipt.get("api_key_env_scrubbed") is not True or
                receipt.get("billing_mode") != "subscription" or
                receipt.get("cost_state") != "subscription_covered" or
                envelope.get("billing_mode") != "subscription" or
                envelope.get("cost_state") != "subscription_covered"):
            return False
    else:
        if (not _valid_chatgpt_no_seat_io(receipt) or
                not _valid_chatgpt_no_seat_preflight(receipt, status) or
                native_exit is not None or thread_id is not None or
                any(usage.values()) or receipt.get("event_count") != 0 or
                receipt.get("malformed_count") != 0 or
                receipt.get("tool_error_count") != 0 or
                receipt.get("billing_mode") is not None or
                receipt.get("cost_state") != "no_seat_started" or
                envelope.get("billing_mode") is not None or
                envelope.get("cost_state") != "no_seat_started"):
            return False

    timed_out = receipt["timed_out"]
    aborted = receipt["aborted"]
    tree_verified = receipt.get("tree_kill_verified")
    group_verified = receipt.get("process_group_kill_verified")
    drain_verified = receipt.get("output_drain_verified")
    if drain_verified is not None and type(drain_verified) is not bool:
        return False
    if status == "timeout":
        if (not timed_out or aborted or tree_verified is not True or
                drain_verified is not True):
            return False
    elif status == "aborted":
        if (timed_out or not aborted or tree_verified is not True or
                drain_verified is not True):
            return False
    elif status == "spawn_aborted":
        if (timed_out or not aborted or
                (seat_started and (tree_verified is not True or
                                   drain_verified is not True)) or
                (not seat_started and
                 (tree_verified is not None or drain_verified is not None))):
            return False
    elif status == "spawn_error" and seat_started:
        if (timed_out or aborted or tree_verified is not True or
                drain_verified is not True):
            return False
    elif status == "kill_failed":
        if tree_verified is not False:
            return False
    elif status == "containment_assignment_failed":
        if (timed_out or aborted or tree_verified not in (None, True) or
                ((tree_verified is True) != (drain_verified is True))):
            return False
    elif status == "process_tree_straggler":
        if (not seat_started or timed_out or aborted or
                tree_verified is not True or drain_verified is not True):
            return False
    elif status == "output_limit_exceeded":
        termination_verified = bool(
            tree_verified is True or
            (os.name == "nt" and
             receipt.get("windows_job_empty_verified") is True and
             receipt.get("root_exit_verified") is True))
        if os.name != "nt":
            termination_verified = group_verified is True
        if (not seat_started or timed_out or aborted or
                not termination_verified or drain_verified is not True):
            return False
    elif status == "output_drain_failed":
        if (not seat_started or timed_out or aborted or
                drain_verified is not False):
            return False
    elif status == "protocol_limit_exceeded":
        if not seat_started or timed_out or aborted or tree_verified is not None:
            return False
    elif status == "stdin_write_failed":
        cleanup_verified = tree_verified in (None, True)
        if os.name != "nt" and tree_verified is False:
            cleanup_verified = group_verified is True
        if not seat_started or timed_out or aborted or not cleanup_verified:
            return False
    elif status == "signal_guard_unavailable":
        if (seat_started and (tree_verified is not True or
                              drain_verified is not True)) or \
                (not seat_started and tree_verified is not None):
            return False
    elif status == "signal_guard_restore_failed":
        if tree_verified not in (None, True):
            return False
    elif status == "artifact_scan_incomplete":
        # A pre-seat fingerprint operation may be interrupted. It still starts
        # no model and preserves the negative scan result; post-seat artifact
        # scans never replace an authoritative cancellation status.
        if timed_out or tree_verified is not None or (seat_started and aborted):
            return False
    elif timed_out or aborted or tree_verified is not None:
        return False
    if (seat_started and status not in ("kill_failed", "output_drain_failed") and
            drain_verified is not True):
        return False
    if (not seat_started and drain_verified is not None and
            status != "containment_assignment_failed"):
        return False

    expected_artifacts = _artifact_contract_from_record(record, expected_sandbox)
    artifacts = receipt.get("artifact_paths")
    receipt_expected = receipt.get("expected_artifact_paths")
    artifact_hashes = receipt.get("artifact_hashes")
    artifact_evidence = receipt.get("artifact_evidence")
    contract_verified = receipt.get("artifact_contract_verified")
    mutation_verified = receipt.get("artifact_mutation_verified")
    if (expected_artifacts is None or not isinstance(artifacts, list) or
            not isinstance(receipt_expected, list) or
            not isinstance(artifact_hashes, dict) or
            not isinstance(artifact_evidence, dict) or
            receipt_expected != expected_artifacts or
            type(contract_verified) is not bool or
            type(mutation_verified) is not bool or
            contract_verified is not mutation_verified):
        return False
    if (type(receipt.get("artifact_write_observed")) is not bool or
            type(receipt.get("artifact_scan_complete")) is not bool or
            receipt["artifact_write_observed"] != bool(artifacts)):
        return False
    expected_scan_complete = status != "artifact_scan_incomplete"
    if not seat_started and (artifacts or receipt["artifact_write_observed"] or
                             receipt["artifact_scan_complete"] is not
                             expected_scan_complete or
                             artifact_hashes or artifact_evidence or
                             mutation_verified):
        return False
    if expected_sandbox == "read-only":
        if (artifacts or receipt["artifact_write_observed"] or artifact_hashes or
                artifact_evidence or mutation_verified):
            return False
    else:
        output_raw = spec.get("output_dir")
        if not isinstance(output_raw, str):
            return False
        output_root = Path(output_raw).resolve()
        if (any(rel not in expected_artifacts for rel in artifacts) or
                any(rel not in expected_artifacts for rel in artifact_hashes) or
                any(rel not in expected_artifacts for rel in artifact_evidence) or
                set(artifact_hashes) != set(artifact_evidence)):
            return False
        if artifact_evidence:
            current_evidence = _current_artifact_snapshot(
                output_root, tuple(artifact_evidence))
            if current_evidence is None or current_evidence != artifact_evidence:
                return False
        if any(artifact_hashes.get(rel) != value.get("sha256")
               for rel, value in artifact_evidence.items()):
            return False
        should_verify = bool(
            receipt["artifact_scan_complete"] and
            artifacts == expected_artifacts and
            set(artifact_evidence) == set(expected_artifacts)
        )
        if mutation_verified is not should_verify:
            return False
    if (status == "artifact_required" and
            (expected_sandbox != "workspace-write" or contract_verified or
             receipt["artifact_scan_complete"] is not True)):
        return False
    if (status == "artifact_scan_incomplete" and
            (expected_sandbox != "workspace-write" or
             receipt["artifact_scan_complete"] is not False)):
        return False
    return True


def _mirror_session_status(job_id, job_status) -> None:
    """Mirror a swarm job's terminal status onto its session record.

    Maps the job's terminal status to a session status and clears the session
    OUT of RUNNING so the hunter no longer treats it as a sweep candidate
    (DONE→done, FAILED→failed, CANCELLED→cancelled, INTERRUPTED→idle). This is
    the job-runner analog of the gandalf ``finally`` reset. Best-effort and
    idempotent: a ``KeyError`` (no session was registered for this job — e.g. a
    legacy/pre-existing record) or any other registry error is swallowed.
    """
    try:
        import session_registry as _sr
    except Exception:  # pragma: no cover
        return
    target = {
        STATUS_DONE: _sr.STATUS_DONE,
        STATUS_FAILED: _sr.STATUS_FAILED,
        STATUS_CANCELLED: _sr.STATUS_CANCELLED,
        STATUS_INTERRUPTED: _sr.STATUS_IDLE,
    }.get(job_status, _sr.STATUS_IDLE)
    try:
        _sr.update_session(job_id, status=target)
    except KeyError:
        pass  # no swarm session registered for this job — nothing to mirror.
    except Exception:  # pragma: no cover - registry is best-effort
        pass


def _finalize(job_id: str, exit_code, result_envelope=None) -> None:
    """Record the terminal status once the process exits.

    ChatGPT child telemetry crosses a hostile process boundary: validate the
    complete adapter envelope before deriving or persisting cost, receipt,
    session, or usage-ledger data. Cancellation is two-phase; while a verified
    cancel is pending, record only the observed process exit and let
    :func:`cancel` choose the durable terminal state after tree/drain checks.
    """
    # Transfer Job Object ownership under the same lock cancellation uses. If a
    # cancel is pending, cancel/_tree_kill owns the handle; otherwise finalizer
    # detaches and closes it exactly once. This prevents a double-close/reused-
    # handle race when process exit and cancellation cross.
    h_job = None
    with _LIVE_LOCK:
        live = _LIVE.get(job_id)
        if (live is not None and
                not getattr(live, "_cancel_requested", False)):
            h_job = getattr(live, "_h_job", None)
            live._h_job = None
    if h_job is not None:
        try:
            import proc_probe
            proc_probe.close_handle(h_job)
        except Exception:
            pass

    with _paths.WRITE_LOCK:
        rec = load_record(job_id)
        if rec is None:
            return
        is_chatgpt = rec.get("backend") == BACKEND_CHATGPT
        success_ok = (not is_chatgpt or
                      _valid_chatgpt_success_envelope(
                          result_envelope, rec, adapter_exit_code=exit_code,
                      ))
        failure_ok = bool(
            is_chatgpt and _valid_chatgpt_failure_envelope(
                result_envelope, rec, adapter_exit_code=exit_code,
            )
        )
        trusted_envelope = bool(
            result_envelope is not None and
            (not is_chatgpt or success_ok or failure_ok)
        )
        if trusted_envelope:
            cost = _cost_from_envelope(result_envelope)
            rec["cost"] = cost
            model_receipt = _model_receipt_from_envelope(result_envelope)
            if model_receipt is not None:
                rec["model_receipt"] = model_receipt
            if cost.get("session_id") and not rec.get("session_id"):
                rec["session_id"] = cost["session_id"]
            # Honest Telemetry W4 — job_runner unification: route this durable
            # job's captured stream-json usage through the SAME usage ledger as
            # interactive PTY sessions, keyed by the engine session UUID the
            # result envelope reported. Lane launches, Gandalf shards, and
            # summarizer runs all land in one ledger. Best-effort + idempotent
            # (keyed by job_id) — never breaks job finalization.
            try:
                euuid = cost.get("session_id")
                if euuid:
                    import usage_capture as _usage_cap
                    _usage_cap.ingest_job_cost(euuid, cost, job_id)
            except Exception:
                pass
        if failure_ok:
            raw_receipt = result_envelope["model_receipt"]
            rec["adapter_failure_status"] = raw_receipt["status"]
            rec["failure_reason"] = raw_receipt["status"]
            rec["failure_detail"] = raw_receipt["error"]
        if live is not None and getattr(live, "_cancel_requested", False):
            # Do not claim cancellation yet. The cancel caller still has to
            # prove tree termination and wait for this reader to drain.
            rec["exit_code"] = exit_code
            rec.setdefault("finished_at", time.time())
            _write_record(rec)
            return
        if rec.get("status") in (STATUS_CANCELLED, STATUS_INTERRUPTED):
            # Terminal status already chosen (cancel / reconciliation). Keep it,
            # just stamp the exit code + finish time.
            rec["exit_code"] = exit_code
            rec.setdefault("finished_at", time.time())
            _write_record(rec)
            # Clear the swarm session out of RUNNING to match (finally-reset).
            _mirror_session_status(job_id, rec.get("status"))
            return
        rec["exit_code"] = exit_code
        rec["finished_at"] = time.time()
        if is_chatgpt:
            if not success_ok and not failure_ok:
                # Never derive even a reason string from the untrusted child.
                rec["failure_reason"] = "chatgpt-valid-receipt-required"
        final_status = (STATUS_DONE
                        if exit_code == 0 and success_ok else STATUS_FAILED)
        rec["status"] = final_status
        _journal.emit_safe(
            rec.get("project_id") or "", _journal.EV_JOB_FINISHED,
            correlation_id=job_id, folder_path=rec.get("folder_path"),
            payload={
                "job_id": job_id,
                "status": rec.get("status"),
                "failure_reason": rec.get("failure_reason"),
            },
        )
        _write_record(rec)
    # Mirror the terminal status onto the swarm session (gandalf finally analog),
    # OUTSIDE the write lock the registry takes its own lock internally.
    _mirror_session_status(job_id, final_status)

    # Followup Wave 3: BRIDGE the captured cost/tokens/duration onto the project
    # EFFORT pointer-record, so the per-project / per-effort rollups (which read
    # the effort `cost` block) stop reporting zeros. `finalize_effort` ->
    # `attach_cost` is the only writer of that block and had no production caller;
    # the runner captured cost onto the JOB record but never bridged it. Only for
    # launch_lane jobs (they carry project_id + folder_path via launch_guarded)
    # that actually captured a result envelope. Best-effort, idempotent, and
    # auto_commit=False (no git commit from job finalization). Lazy import +
    # broad guard so a bridge failure can never break job finalization. Runs
    # OUTSIDE the WRITE_LOCK (record_effort takes the lock itself).
    if rec.get("project_id") and rec.get("folder_path") and rec.get("cost"):
        try:
            import effort_history as _eh
            _eh.finalize_effort(
                rec["folder_path"], rec["project_id"], rec.get("lane"),
                job_id, rec, auto_commit=False)
        except Exception:  # pragma: no cover - bridge is strictly best-effort
            pass


# ── Tail / long-poll ─────────────────────────────────────────────────────────

def _lines_from_log(job_id: str) -> list:
    """Read the full durable log as a list of lines (no trailing newline)."""
    lp = log_path_for(job_id)
    if not lp.exists():
        return []
    try:
        text = lp.read_text(encoding="utf-8")
    except OSError:
        return []
    if text == "":
        return []
    lines = text.split("\n")
    # A trailing newline yields a final empty element — drop it.
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def all_lines(job_id: str) -> list:
    """Return every captured line for a job (live ring if present, else log)."""
    with _LIVE_LOCK:
        live = _LIVE.get(job_id)
    if live is not None:
        with live.lock:
            # The ring is capped; if it has been truncated, fall back to the
            # durable log which holds full history.
            if len(live.ring) >= live.ring.maxlen:
                return _lines_from_log(job_id)
            return list(live.ring)
    return _lines_from_log(job_id)


def extract_assistant_text(lines) -> list:
    """Extract the model's ACTUAL text from a job's captured stdout lines.

    Production runs ``claude -p --output-format stream-json``, whose stdout is
    NDJSON envelopes — the model's text is NOT emitted as bare lines. It lives in
    ``{"type":"assistant","message":{"content":[{"type":"text","text":...}]}}``
    frames, and the complete final answer is in the terminal
    ``{"type":"result","result":"<final text>"}`` envelope (the ``-p`` print
    result). A naive "skip every ``{...}`` line with a ``type``" parser therefore
    discards 100% of the model output in production (the summarizer bug).

    This returns the model's text as a list of non-empty, newline-split lines,
    preferring the canonical ``result`` envelope text, then concatenated
    ``assistant`` text blocks. **Back-compat:** a line that is NOT a stream-json
    envelope (e.g. a bare claim line from a test stub / non-stream output) is
    taken verbatim as text, so existing stub-driven callers keep working.

    Stdlib only; never raises (an unparseable line is treated as bare text).
    """
    result_text = None
    assistant_parts = []
    bare_parts = []
    for raw in (lines or []):
        s = (raw or "").strip()
        if not s:
            continue
        obj = None
        if s.startswith("{") and s.endswith("}"):
            try:
                obj = json.loads(s)
            except (json.JSONDecodeError, ValueError):
                obj = None
        if isinstance(obj, dict) and obj.get("type"):
            t = obj.get("type")
            if t == "result":
                r = obj.get("result")
                if isinstance(r, str) and r.strip():
                    result_text = r  # last terminal result wins
            elif t == "assistant":
                msg = obj.get("message") or {}
                for block in (msg.get("content") or []):
                    if (isinstance(block, dict)
                            and block.get("type") == "text"
                            and isinstance(block.get("text"), str)
                            and block["text"].strip()):
                        assistant_parts.append(block["text"])
            # Other envelope types (system/user/tool_use/...) carry no answer text.
            continue
        # Not a recognized envelope → a bare text line (test stub / plain output).
        bare_parts.append(s)

    if result_text is not None:
        text = result_text
    elif assistant_parts:
        text = "\n".join(assistant_parts)
    else:
        text = "\n".join(bare_parts)

    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def tail(job_id: str, since: int = 0) -> dict:
    """Return captured lines *after* index ``since``.

    Returns ``{lines, next, total, status}`` where ``next`` is the index a
    client should pass as ``since`` on its next poll, ``total`` is the current
    line count, and ``status`` is the job's current status.
    """
    lines = all_lines(job_id)
    total = len(lines)
    start = max(0, int(since))
    new = lines[start:] if start < total else []
    rec = load_record(job_id) or {}
    return {
        "lines": new,
        "next": total,
        "total": total,
        "status": rec.get("status"),
    }


# ── Durable tail cursor (rearch W15 — IPC contract "tail-cursor-durability") ──
# A client's last-read line offset is persisted in the job dir so a tail cursor
# survives a dashboard/supervisor restart (the W16 external supervisor lives on
# this same file). The offset is a single last-read index — overwriting it is
# idempotent; a torn write falls back to 0 (re-reads, never skips).

def cursor_path_for(job_id: str) -> Path:
    """Durable read-cursor path for a job (``<jobs_dir>/<job_id>.cursor.json``).

    Distinct from the ``.gate.json`` sibling and the ``.json`` record; the
    ``list_records`` glob skips ``.gate.json`` and this ``.cursor.json`` matches
    the same ``*.json`` glob, so it is filtered there too (see below).
    """
    return _jobs_dir_for(job_id) / f"{job_id}.cursor.json"


def persist_read_cursor(job_id: str, offset) -> None:
    """Persist a client's last-read line offset for a job (atomic, locked)."""
    try:
        off = max(0, int(offset))
    except (TypeError, ValueError):
        off = 0
    with _paths.WRITE_LOCK:
        p = cursor_path_for(job_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"job_id": job_id, "offset": off}),
                       encoding="utf-8")
        tmp.replace(p)


def load_read_cursor(job_id: str) -> int:
    """Return a job's persisted read offset (0 when absent or torn)."""
    p = cursor_path_for(job_id)
    if not p.exists():
        return 0
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
        return max(0, int(obj.get("offset", 0)))
    except (json.JSONDecodeError, OSError, ValueError, TypeError, AttributeError):
        return 0


def long_poll(job_id: str, since: int = 0,
              ceiling: float = DEFAULT_LONGPOLL_CEILING,
              poll_interval: float = 0.05) -> dict:
    """Block up to ``ceiling`` seconds for lines after ``since``.

    Returns immediately if new lines already exist; otherwise polls every
    ``poll_interval`` seconds until new lines appear, the job ends, or the
    ceiling elapses. ``ceiling`` is injectable so tests need not wait 25s; the
    production default (:data:`DEFAULT_LONGPOLL_CEILING`) is unchanged.
    """
    deadline = time.monotonic() + max(0.0, float(ceiling))
    while True:
        out = tail(job_id, since)
        if out["lines"]:
            return out
        # If the job is finished and there is nothing new, return (empty) so the
        # client learns the terminal status rather than spinning.
        if out["status"] in TERMINAL_STATUSES:
            return out
        if time.monotonic() >= deadline:
            return out
        time.sleep(poll_interval)


# ── Liveness / reconciliation ────────────────────────────────────────────────

def _pid_alive(pid) -> bool:
    """Best-effort: is a PID currently a live process? Stdlib only."""
    if not pid:
        return False
    if os.name == "nt":
        # tasklist filtered by PID; if the PID appears, it's alive.
        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {int(pid)}", "/NH"],
                capture_output=True, text=True, timeout=10,
                creationflags=_paths.NO_WINDOW,
            )
        except (OSError, subprocess.SubprocessError, ValueError):
            return False
        return str(int(pid)) in (out.stdout or "")
    # POSIX
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError):
        return False
    return True


def liveness_check(job_id: str) -> dict:
    """Reconcile one job's status against reality.

    If a record says ``running`` but its process is gone (and it isn't a live
    job still being drained in *this* process), mark it ``interrupted``.
    Returns the (possibly updated) record.
    """
    rec = load_record(job_id)
    if rec is None:
        return None
    if rec.get("status") != STATUS_RUNNING:
        return rec
    # A job still draining in this very process is genuinely live even if the
    # PID check races; trust the live table + its done flag.
    with _LIVE_LOCK:
        live = _LIVE.get(job_id)
    if live is not None and not live.done.is_set():
        if _pid_alive(rec.get("pid")):
            return rec
        # Process died but reader hasn't finalized yet — let _finalize handle it
        # unless the pid is truly gone; mark interrupted to be safe.
    if _pid_alive(rec.get("pid")):
        return rec
    out = _update_record(job_id, status=STATUS_INTERRUPTED,
                         finished_at=time.time())
    _mirror_session_status(job_id, STATUS_INTERRUPTED)
    return out


def reconcile_on_startup() -> list:
    """Mark every dead-but-"running" persisted job ``interrupted``.

    Called at server startup: any job recorded ``running`` whose process is no
    longer alive (e.g. the server was restarted out from under it) is honestly
    reported as ``interrupted`` (C9 — restart-from-checkpoint, not transparent
    resume). Returns the list of reconciled job_ids — callers may relaunch
    selectively via :func:`relaunch`; there is deliberately NO auto-relaunch (a
    restart storm must not launch N stale jobs unattended).
    """
    changed = []
    for rec in list_records():
        if rec.get("status") != STATUS_RUNNING:
            continue
        jid = rec.get("job_id")
        with _LIVE_LOCK:
            live = _LIVE.get(jid)
        if live is not None and not live.done.is_set():
            # Owned by this live process and still draining — leave it.
            continue
        if not _pid_alive(rec.get("pid")):
            _update_record(jid, status=STATUS_INTERRUPTED,
                           finished_at=time.time())
            _mirror_session_status(jid, STATUS_INTERRUPTED)
            changed.append(jid)
    # Disk hygiene (2026-07 review): reap the durable .log files of long-terminal
    # jobs. The small JSON records are KEPT forever (effort rollups/report views
    # reference them per job_id); only the bulky logs age out. Best-effort.
    try:
        gc_old_job_logs()
    except Exception:
        pass
    return changed


def gc_old_job_logs(retention_days=None) -> int:
    """Delete the ``.log`` of every TERMINAL job that finished more than
    ``retention_days`` (default 45; env ``ANCHOR_JOB_LOG_RETENTION_DAYS``) ago.

    Records (``.json``) are never touched — history, cost rollups and report
    views stay intact; only the raw transcript ages out. A running/gated job's
    log is never reaped (terminal statuses only). Returns the reap count.
    """
    if retention_days is None:
        try:
            retention_days = float(
                os.environ.get("ANCHOR_JOB_LOG_RETENTION_DAYS", "") or 45)
        except ValueError:
            retention_days = 45.0
    if retention_days <= 0:
        return 0
    cutoff = time.time() - retention_days * 86400.0
    reaped = 0
    for rec in list_records():
        if rec.get("status") == STATUS_RUNNING:
            continue
        fin = rec.get("finished_at") or rec.get("started_at") or 0
        try:
            fin = float(fin)
        except (TypeError, ValueError):
            continue
        if not fin or fin > cutoff:
            continue
        jid = str(rec.get("job_id") or "")
        if not jid:
            continue
        try:
            lp = _jobs_dir_for(jid) / f"{jid}.log"
            if lp.exists():
                lp.unlink()
                reaped += 1
        except OSError:
            pass
    return reaped


# ── Relaunch (durability 2026-07 Wave 1) ─────────────────────────────────────

def relaunch(job_id: str) -> dict:
    """Re-launch an ``interrupted`` job in ONE call from its durable record.

    Loads the record and refuses honestly (``{ok: False, reason}`` — reasons are
    strings, never exceptions) unless the record exists, its ``status`` is
    ``interrupted``, and it carries a ``relaunch_spec`` (a legacy record without
    one refuses with ``reason == 'no-relaunch-spec'``). Otherwise calls
    :func:`launch_guarded` with the persisted spec (approved amendment,
    2026-07-02) — the concurrency policy (same-lane serialize, folder-build
    lock, spawn cap) and the project-metadata propagation apply to a relaunch
    EXACTLY as to a first launch; a policy refusal (:class:`LaneBusyError`)
    comes back as an honest ``{ok: False, reason, holder}``, never an
    exception — links the records both ways (``relaunched_as`` on the old
    record / ``relaunch_of`` on the new one), and returns the new record (with
    ``ok: True`` added for uniform callers).
    """
    rec = load_record(job_id)
    if rec is None:
        return {"ok": False, "reason": RELAUNCH_REASON_UNKNOWN}
    status = rec.get("status")
    if status != STATUS_INTERRUPTED:
        return {"ok": False,
                "reason": f"{RELAUNCH_REASON_NOT_INTERRUPTED}:{status}"}
    spec = rec.get("relaunch_spec")
    if not isinstance(spec, dict) or not spec:
        return {"ok": False, "reason": RELAUNCH_REASON_NO_SPEC}

    # Policy context for the guarded launch. A guarded first launch persisted
    # real project_id/folder_path in the spec; a direct launch() recorded None
    # (record-level fields are a fallback for early-Wave-1 records). The
    # folder_path degrades to the job's cwd so the folder-build lock still has
    # an honest key for a metadata-less build record.
    project_id = spec.get("project_id") or rec.get("project_id")
    folder_path = (spec.get("folder_path") or rec.get("folder_path")
                   or spec.get("cwd") or "")

    # Durable gate answers (2026-07 Wave 2): a pending gate rides the relaunch.
    # An ANSWERED-but-undelivered gate answer is appended to the seed prompt as
    # context — delivered exactly ONCE (``delivered_at`` is stamped below, only
    # after the launch actually happened). An UNANSWERED gate file is carried to
    # the new job id after launch so the question keeps rendering. Deferred
    # import (gate_adapter imports job_runner).
    prompt = spec.get("prompt")
    gate = None
    try:
        import gate_adapter as _ga
    except ImportError:  # pragma: no cover - stdlib sibling module
        _ga = None
    if _ga is not None:
        gate = _ga.load_gate_file(job_id)
        if (gate is not None and gate.get("answered")
                and not gate.get("delivered_at")):
            prompt = _ga.append_gate_answer_context(prompt, gate)

    record_backend = rec.get("backend")
    spec_backend = spec.get("backend")
    receipt = rec.get("model_receipt")
    if not isinstance(receipt, dict):
        receipt = {}
    provider_evidence = (
        ("record", record_backend),
        ("spec", spec_backend),
        ("receipt-backend", receipt.get("backend_requested")),
        ("receipt-family", receipt.get("family_requested")),
    )
    present_backends = []
    for source, value in provider_evidence:
        if value is None:
            continue
        if not isinstance(value, str) or value not in VALID_BACKENDS:
            return {"ok": False,
                    "reason": "relaunch-unknown-%s:%r" % (source, value)}
        present_backends.append(value)
    if len(set(present_backends)) > 1:
        return {"ok": False, "reason": "relaunch-backend-conflict"}
    preserved_backend = present_backends[0] if present_backends else DEFAULT_BACKEND
    if preserved_backend == BACKEND_CHATGPT and (
            spec_backend != BACKEND_CHATGPT or
            "expected_artifacts" not in spec):
        return {"ok": False,
                "reason": "chatgpt-relaunch-spec-incomplete"}

    try:
        new_rec = launch_guarded(
            spec.get("lane"),
            project_id=project_id,
            folder_path=folder_path,
            cwd=spec.get("cwd"),
            env=spec.get("env_keys") or None,
            backend=preserved_backend,
            prompt=prompt,
            output_dir=spec.get("output_dir"),
            gated=spec.get("gated") or False,
            permission_mode=spec.get("permission_mode"),
            command=spec.get("command") or None,
            expected_artifacts=spec.get("expected_artifacts"),
        )
    except LaneBusyError as e:
        return {"ok": False, "reason": str(e.reason), "holder": e.holder}
    except ValueError as exc:
        # Persisted legacy/tampered ChatGPT specs can lack the now-required
        # artifact contract (or carry an unsafe path). Relaunch is an API seam:
        # return a typed refusal rather than escalating the validation error to
        # an HTTP 500 or guessing a completion file from stale state.
        return {"ok": False, "reason": str(exc)[:500]}
    # Link both ways on disk (each side under the write lock).
    _update_record(job_id, relaunched_as=new_rec["job_id"])
    new_rec = _update_record(new_rec["job_id"], relaunch_of=job_id)
    # Gate bookkeeping (Wave 2) — only after the launch actually happened, so a
    # refused relaunch never consumes ("delivers") the recorded answer.
    if _ga is not None and gate is not None:
        if gate.get("answered") and not gate.get("delivered_at"):
            _ga.mark_gate_delivered(job_id, delivered_to=new_rec["job_id"])
        elif not gate.get("answered"):
            _ga.carry_gate_file(job_id, new_rec["job_id"])
    out = dict(new_rec)
    out["ok"] = True
    return out


# ── Cancel (tree-kill) ───────────────────────────────────────────────────────

def cancel(job_id: str) -> dict:
    """Cancel after ownership, tree termination, and drain are verified.

    A persisted PID is not authority to kill: after a restart it may have been
    recycled. A live ``Popen`` establishes identity; otherwise Windows must
    match the recorded creation time before a kill. POSIX unowned live PIDs fail
    closed. Already-terminal records and PIDs proven absent remain idempotent.
    """
    rec = load_record(job_id)
    if rec is None:
        return None
    if rec.get("status") in TERMINAL_STATUSES:
        # Terminal truth is immutable. A retained Popen whose poll() is no
        # longer None proves only that the child exited; it does not turn an
        # already-completed/failed/interrupted job into a user cancellation.
        return rec

    pid = rec.get("pid")
    with _LIVE_LOCK:
        live = _LIVE.get(job_id)
        identity = _cancel_identity_state(rec, live)
        if identity == "owned-running" and live is not None:
            # Claim cancellation + Job Object ownership atomically against the
            # finalizer's handle-detach decision.
            live._cancel_requested = True
    if identity == "gone":
        return _commit_cancelled(
            job_id, rec,
            "no-process-recorded" if pid is None else "already-gone")
    if identity != "owned-running":
        return _update_record(
            job_id,
            cancel_succeeded=False,
            tree_kill_verified=False,
            failure_reason="cancel-pid-identity-unverified",
            cancel_failed_at=time.time(),
        )

    kill_ok = _tree_kill(
        pid, live=live, expected_create_time=rec.get("proc_create_time"),
    )
    drained = (live.done.wait(timeout=10) if live is not None
               else _pid_proven_absent(pid))
    if kill_ok and drained:
        return _commit_cancelled(job_id, rec, "tree-kill-and-drain")

    if live is not None:
        # A failed cancel must not strand later natural finalization in the
        # pending state. If the reader drained, the root ended but the full
        # process tree was not proven reaped: record ``interrupted``.
        live._cancel_requested = False
    direct_dead = _direct_process_dead(pid, live=live, timeout=0)
    failed_status = STATUS_INTERRUPTED if drained or direct_dead else rec.get("status")
    failed = _update_record(
        job_id,
        status=failed_status,
        cancel_succeeded=False,
        tree_kill_verified=False,
        failure_reason=("cancel-reader-drain-unverified"
                        if kill_ok and not drained
                        else "cancel-tree-termination-unverified"),
        cancel_failed_at=time.time(),
    )
    if failed_status == STATUS_INTERRUPTED:
        _mirror_session_status(job_id, STATUS_INTERRUPTED)
    return failed


def _commit_cancelled(job_id, record, verification) -> dict:
    """Persist the terminal cancellation transition after positive proof."""
    _journal.emit_safe(
        (record or {}).get("project_id") or "", _journal.EV_JOB_CANCELLED,
        correlation_id=job_id, folder_path=(record or {}).get("folder_path"),
        payload={"job_id": job_id, "verification": verification},
    )
    out = _update_record(
        job_id,
        status=STATUS_CANCELLED,
        cancel_succeeded=True,
        termination_verified=True,
        tree_kill_verified=(True if verification == "tree-kill-and-drain"
                            else None),
        cancel_verification=verification,
        cancelled_at=time.time(),
        failure_reason=None,
    )
    _mirror_session_status(job_id, STATUS_CANCELLED)
    return out


def _same_creation_time(observed, expected, tolerance=2.0) -> bool:
    """Match observed and recorded PID creation times without coercion gaps."""
    if (isinstance(observed, bool) or isinstance(expected, bool) or
            not isinstance(observed, (int, float)) or
            not isinstance(expected, (int, float))):
        return False
    return abs(float(observed) - float(expected)) <= float(tolerance)


def _pid_proven_absent(pid) -> bool:
    """Return true only when the OS positively proves no process has ``pid``."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import proc_probe
            return proc_probe.pid_alive_via_enum(pid) is False
        except Exception:
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except (OSError, PermissionError):
        return False
    return False


def _direct_process_dead(pid, live=None, timeout=3.0) -> bool:
    """Verify the direct process exited; never infer death from a kill call."""
    proc = getattr(live, "proc", None) if live is not None else None
    if proc is not None:
        try:
            if proc.poll() is not None:
                return True
            proc.wait(timeout=max(0.0, float(timeout)))
            return True
        except (AttributeError, OSError, subprocess.SubprocessError):
            return False
    deadline = time.monotonic() + max(0.0, float(timeout))
    while True:
        if _pid_proven_absent(pid):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)


def _cancel_identity_state(record, live=None) -> str:
    """Classify cancellation authority as owned-running, gone, or unsafe."""
    raw_pid = (record or {}).get("pid")
    if raw_pid is None:
        # No process identity was ever recorded. Launch stamps the real pid in
        # the SAME write as the running record (see the launch path), so a
        # pid-less non-terminal record can only be a job that never got a
        # child: nothing to kill, no recycled-PID risk, cancel is honest.
        return "gone"
    try:
        pid = int(raw_pid)
    except (TypeError, ValueError):
        return "unsafe"
    if pid <= 0:
        return "unsafe"

    proc = getattr(live, "proc", None) if live is not None else None
    if proc is not None:
        if getattr(proc, "pid", None) != pid:
            return "unsafe"
        try:
            return "gone" if proc.poll() is not None else "owned-running"
        except (AttributeError, OSError):
            return "unsafe"

    # A durable terminal record was written only after this runner observed the
    # direct process exit. Do not touch a potentially recycled PID.
    if (record or {}).get("status") in TERMINAL_STATUSES:
        return "gone"

    if os.name != "nt":
        return "gone" if _pid_proven_absent(pid) else "unsafe"

    try:
        import proc_probe
        status, observed_ct, _image = proc_probe.probe_status(pid)
        expected_ct = (record or {}).get("proc_create_time")
        if status in (proc_probe.PROBE_RUNNING, proc_probe.PROBE_EXITED):
            if not _same_creation_time(observed_ct, expected_ct):
                return "unsafe"
            return ("owned-running" if status == proc_probe.PROBE_RUNNING
                    else "gone")
        return "gone" if proc_probe.pid_alive_via_enum(pid) is False else "unsafe"
    except Exception:
        return "unsafe"


def _posix_group_dead(pgid, timeout=3.0) -> bool:
    deadline = time.monotonic() + max(0.0, float(timeout))
    while True:
        try:
            os.killpg(int(pgid), 0)
        except ProcessLookupError:
            return True
        except (OSError, PermissionError):
            return False
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)


def _tree_kill(pid, live=None, expected_create_time=None) -> bool:
    """Kill and verify a process tree; false means the outcome is uncertain."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False

    if os.name == "nt":
        # Atomically detach the handle so _finalize can never close the same
        # numeric HANDLE concurrently (a double-close can hit a reused handle).
        h_job = None
        if live is not None:
            with _LIVE_LOCK:
                h_job = getattr(live, "_h_job", None)
                live._h_job = None
        result = None
        try:
            result = subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(pid)],
                capture_output=True, text=True, timeout=15,
                creationflags=_paths.NO_WINDOW,
            )
        except (OSError, subprocess.SubprocessError):
            result = None
        root_dead = _direct_process_dead(pid, live=live, timeout=5)
        if not root_dead and expected_create_time is not None:
            try:
                import proc_probe
                root_dead = proc_probe.confirmed_dead(pid, expected_create_time)
            except Exception:
                root_dead = False
        # Close the detached Job Object as leak reduction. close_handle() does
        # not expose CloseHandle's success bit, so root death after this call is
        # NOT accepted as proof that descendants were reaped.
        if h_job is not None:
            try:
                import proc_probe
                proc_probe.close_handle(h_job)
            except Exception:
                pass
        return bool(result is not None and result.returncode == 0 and root_dead)

    proc = getattr(live, "proc", None) if live is not None else None
    identity_safe = proc is not None and getattr(proc, "pid", None) == pid
    if identity_safe:
        try:
            pgid = os.getpgid(pid)
        except (OSError, ProcessLookupError):
            return _direct_process_dead(pid, live=live, timeout=0)
        # launch() uses start_new_session=True. Never signal Anchor's own or an
        # unrelated process group if that invariant is not observable.
        if pgid != pid:
            return False
        try:
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            return _direct_process_dead(pid, live=live, timeout=0)
        except (OSError, PermissionError):
            return False
        if (_direct_process_dead(pid, live=live, timeout=3) and
                _posix_group_dead(pgid, timeout=1)):
            return True
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except (OSError, PermissionError):
            return False
        return (_direct_process_dead(pid, live=live, timeout=5) and
                _posix_group_dead(pgid, timeout=5))

    # Compatibility for direct, freshly-owned helper processes outside _LIVE:
    # kill only the PID. Group killing is reserved for a positively-owned
    # session leader, so this path can never hit Anchor's process group.
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    except (OSError, PermissionError):
        return False
    if _direct_process_dead(pid, timeout=1):
        return True
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return True
    except (OSError, PermissionError):
        return False
    return _direct_process_dead(pid, timeout=3)


# ── Concurrency policy: same-lane serialize + folder-build lock (Wave 6) ─────

def _holder_is_active(job_id: str) -> bool:
    """True if ``job_id`` is still a live (non-terminal) job.

    Used to garbage-collect stale slots: a holder whose record is terminal (or
    gone) no longer occupies its lane/folder slot, so a fresh launch may proceed.
    Consults the durable record (the cross-restart source of truth); reconciles
    a dead 'running' record to interrupted via :func:`liveness_check`.
    """
    if not job_id:
        return False
    rec = load_record(job_id)
    if rec is None:
        return False
    if rec.get("status") in TERMINAL_STATUSES:
        return False
    # Record still says running — verify the process is genuinely alive,
    # reconciling a dead-but-"running" record to interrupted as a side effect.
    rec = liveness_check(job_id) or rec
    return rec.get("status") not in TERMINAL_STATUSES


def prune_dead_live() -> int:
    """Drop ``_LIVE`` entries whose durable status is terminal / inactive.

    Finished jobs used to linger in ``_LIVE`` forever (only cleared on test
    reset), which inflated the global spawn-cap census and blocked Tidy-Idy
    and new terminals after a long Anchor uptime. Returns count removed.
    """
    dead = []
    with _LIVE_LOCK:
        keys = list(_LIVE.keys())
    for jid in keys:
        if not _holder_is_active(jid):
            dead.append(jid)
    if not dead:
        return 0
    with _LIVE_LOCK:
        for jid in dead:
            _LIVE.pop(jid, None)
    return len(dead)


def is_gate_blocked(job_id: str) -> bool:
    """True when ``job_id`` is parked on an AskUserQuestion gate.

    A gate-blocked job's ``state`` is ``awaiting-input`` (set by
    :func:`gate_adapter.mark_awaiting_input`) — it is blocked on a stdin read,
    doing no file writes and burning no CPU, yet it is legitimately in-flight.
    """
    if not job_id:
        return False
    rec = load_record(job_id)
    if rec is None:
        return False
    try:
        import gate_adapter as _ga
        return rec.get("state") == _ga.STATE_AWAITING_INPUT
    except Exception:  # pragma: no cover - defensive against an import failure
        return rec.get("state") == "awaiting-input"


def blocked_but_owned(job_id: str) -> bool:
    """A gate-blocked / API-waiting job that is STILL owned (in-flight).

    The zombie-hunter reaper (Wave 2) leans on this INVARIANT: a legitimately-
    working sub-agent blocked on a gate must stay in ``reaper.build_snapshot``'s
    ``job_owned_ids`` so it is never classified as an orphan. It already does —
    a gate-blocked job keeps its process alive (blocked on the stdin read) and
    its ``status`` stays RUNNING, so :func:`_holder_is_active` returns True — and
    the owner-enumeration contract uses ``_holder_is_active`` as its owning-job
    predicate. NO ``blocked_but_owned`` job state was needed in ``job_runner``;
    this accessor surfaces the invariant (gate-blocked AND still an active
    holder) for the reaper's instrumentation / the Wave-2 proof test.
    """
    return bool(is_gate_blocked(job_id) and _holder_is_active(job_id))


def _gc_lane_slot(project_id: str, lane: str) -> None:
    """Drop the (project_id, lane) active slot if its holder is no longer live."""
    key = (project_id, lane)
    holder = _ACTIVE_LANE.get(key)
    if holder is not None and not _holder_is_active(holder):
        _ACTIVE_LANE.pop(key, None)


def _gc_folder_build(folder_path: str) -> None:
    """Drop the folder build lock if its holder is no longer live."""
    holder = _FOLDER_BUILD.get(folder_path)
    if holder is not None and not _holder_is_active(holder):
        _FOLDER_BUILD.pop(folder_path, None)


def lane_holder(project_id: str, lane: str):
    """Return the job_id currently holding (project_id, lane), or ``None``.

    Self-healing: a stale slot whose holder has gone terminal is cleared first.
    """
    with _paths.WRITE_LOCK:
        _gc_lane_slot(project_id, lane)
        return _ACTIVE_LANE.get((project_id, lane))


def folder_build_holder(folder_path: str):
    """Return the job_id holding ``folder_path``'s build lock, or ``None``.

    This is what the UI's folder-build-lock badge keys off of. Self-healing:
    a finished build's lock is released here.
    """
    folder_path = str(folder_path)
    with _paths.WRITE_LOCK:
        _gc_folder_build(folder_path)
        return _FOLDER_BUILD.get(folder_path)


def launch_guarded(lane: str, project_id: str, folder_path, cwd=None,
                   extra_args=None, env=None, job_id: str = None,
                   backend=DEFAULT_BACKEND, prompt=None, output_dir=None,
                   gated=False, permission_mode=None, command=None,
                   kill_on_job_close: bool = True,
                   expected_artifacts=None) -> dict:
    """Launch a job under the Wave-6 concurrency policy.

    Policy (frozen design — MASTER-PLAN "Lanes & concurrency"):
    - WITHIN a project: same-lane jobs are **serialized** (a second same-lane
      launch while one is live is refused); cross-lane jobs run **concurrently**
      (the key includes the lane, so different lanes never contend).
    - ACROSS projects sharing a folder: **build** jobs are serialized at the
      FOLDER level (at most one build per ``folder_path``); a second build in
      that folder — even for a different project — is refused with the
      ``folder-build-lock`` indicator. research/plan are NOT folder-locked.

    The reservation (check-and-set of both the lane slot and, for builds, the
    folder lock) plus the actual :func:`launch` all happen INSIDE
    ``paths.WRITE_LOCK``, so the policy is correct under concurrency — two
    builds for one folder can never both win the lock.

    ``prompt`` / ``output_dir`` / ``gated`` / ``permission_mode`` are threaded
    straight through to :func:`launch` so the real per-backend argv (and the
    gated stdin pipe) are built there. They are inert under the concurrency
    policy itself.

    Raises :class:`LaneBusyError` (with ``reason`` + ``holder``) when refused.
    On success returns the job record (as :func:`launch`).
    """
    folder_path = str(folder_path)
    with _paths.WRITE_LOCK:
        # 0) Global spawn cap (shared with pty_manager.start).
        import pty_manager
        total_live, live_ptys, live_jobs, cap = pty_manager.count_live_for_spawn_cap()
        if total_live >= cap:
            raise LaneBusyError(
                "spawn-cap-reached",
                message=(
                    f"Global sub-agent spawn cap reached ({total_live}/{cap} "
                    f"— {live_ptys} terminals + {live_jobs} jobs). "
                    f"Close idle Anchor terminals, let jobs finish, or restart Anchor. "
                    f"Override with ANCHOR_SPAWN_CAP."
                ),
            )

        # 1) Same-lane within-project serialization.
        _gc_lane_slot(project_id, lane)
        same = _ACTIVE_LANE.get((project_id, lane))
        if same is not None:
            raise LaneBusyError(REFUSED_SAME_LANE, holder=same)

        # 2) Folder-level build lock (build lane only).
        if lane == BUILD_LANE:
            _gc_folder_build(folder_path)
            held = _FOLDER_BUILD.get(folder_path)
            if held is not None:
                raise LaneBusyError(REFUSED_FOLDER_BUILD, holder=held)

        # Both gates clear → launch under the lock, then record the reservation
        # against the real job_id so subsequent contenders see it. project_id /
        # folder_path ride into launch() so the durable relaunch_spec carries
        # the policy context (approved amendment, 2026-07-02).
        rec = launch(lane, cwd=cwd, extra_args=extra_args, env=env,
                     job_id=job_id, backend=backend, prompt=prompt,
                     output_dir=output_dir, gated=gated,
                     permission_mode=permission_mode,
                     project_id=project_id, folder_path=folder_path,
                     command=command, kill_on_job_close=kill_on_job_close,
                     expected_artifacts=expected_artifacts)
        jid = rec["job_id"]
        _ACTIVE_LANE[(project_id, lane)] = jid
        if lane == BUILD_LANE:
            _FOLDER_BUILD[folder_path] = jid
        # Stamp the policy context onto the durable record for introspection
        # (and so the folder-build-lock badge can be reconstructed from disk).
        _update_record(jid, project_id=project_id, folder_path=folder_path)
        return rec


def release_slots(job_id: str) -> None:
    """Release any lane/folder slots a (now-finished) job was holding.

    Called when a job reaches a terminal status to promptly free its lane and,
    if it was a build, its folder lock. Safe to call repeatedly; the lazy GC in
    the holder accessors also reclaims slots, so this is an optimization for
    responsiveness, not a correctness requirement.
    """
    with _paths.WRITE_LOCK:
        for key, holder in list(_ACTIVE_LANE.items()):
            if holder == job_id:
                _ACTIVE_LANE.pop(key, None)
        for folder, holder in list(_FOLDER_BUILD.items()):
            if holder == job_id:
                _FOLDER_BUILD.pop(folder, None)


# ── Test/maintenance helpers ─────────────────────────────────────────────────

def wait(job_id: str, timeout: float = 30.0) -> dict:
    """Block until the job's reader thread finishes (or timeout). Test helper."""
    with _LIVE_LOCK:
        live = _LIVE.get(job_id)
    if live is not None:
        live.done.wait(timeout=timeout)
    return load_record(job_id)


def _reset_live_table_for_tests() -> None:
    """Drop the in-memory live + policy tables (used between tests).

    Does not kill procs. Clears the live job table and the Wave-6 concurrency
    registries (lane slots + folder build locks) so each test starts clean.
    """
    with _LIVE_LOCK:
        _LIVE.clear()
    with _paths.WRITE_LOCK:
        _ACTIVE_LANE.clear()
        _FOLDER_BUILD.clear()
