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

import json
import os
import shlex
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from pathlib import Path

import paths as _paths
import journal as _journal

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

#: Engine backends. Claude is the default for all core tasks. Gemini is supported
#: via the Gandalf architecture integration (or specifically configured lanes). The runner command for each is resolved by
#: :func:`resolve_runner_cmd`. ``ANCHOR_RUNNER_CMD`` (the test indirection point)
#: ALWAYS wins, regardless of backend, so the mock runner drives every test.
BACKEND_CLAUDE = "claude"
BACKEND_GEMINI = "gemini"
BACKEND_GROK = "grok"
#: Jobs keep Claude as the default backend; interactive terminals read
#: ``anchor_settings.get_default_cli()`` (default ``grok``) instead.
DEFAULT_BACKEND = BACKEND_CLAUDE

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
                 "gated", "_h_job")

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
    """Persist a job record (atomic-ish) under the write lock."""
    with _paths.WRITE_LOCK:
        p = _record_path(rec["job_id"])
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(rec, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(p)


def load_record(job_id: str):
    """Return the persisted job record dict, or ``None``."""
    p = _record_path(job_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
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


def build_backend_argv(backend, prompt, output_dir, gated, permission_mode=None) -> list:
    """Build the VALID production argv for a backend + lane shape.

    Used only on the override-UNSET (real-CLI) path. Dispatches to the
    per-backend builder. ``gated`` is falsy for research, ``"plan"``/``"build"``
    (truthy) for the gated lanes (claude only — gemini is research-only).
    """
    if backend == BACKEND_GROK:
        # Interactive Grok terminals are supported via terminal_session; headless
        # job_runner has no tool-capable Grok argv builder yet. Refuse honestly
        # rather than silently launching Claude under a grok backend label.
        raise ValueError(
            "job_runner does not support backend='grok' for headless jobs yet; "
            "use an interactive Grok terminal (terminal_session) or set "
            "coding_family/review_family for trio seat routing instead"
        )
    if backend == BACKEND_GEMINI:
        return _build_gemini_argv(prompt, output_dir, gated, permission_mode=permission_mode)
    return _build_claude_argv(prompt, output_dir, gated, permission_mode=permission_mode)


def resolve_runner_cmd(extra_args=None, backend=DEFAULT_BACKEND,
                       prompt=None, output_dir=None, gated=False,
                       permission_mode=None) -> list:
    """Resolve the runner command as an argv list, honoring the engine backend.

    Resolution order (CRITICAL — the test indirection must always win):
    1. ``ANCHOR_RUNNER_CMD`` set → use it **for any backend** (this is how the
       whole test suite drives the mock ``tests/fake_claude.py`` regardless of
       which engine a launch selected). The base mock command is used as-is; if a
       ``prompt`` is supplied it is appended as a trailing arg the mock tolerates
       via ``parse_known_args`` (so tests still drive the mock and the prompt
       never leaks into a real CLI). ``extra_args`` (test flags like ``--lines``)
       are appended last. Never broken by the per-backend builders.
    2. else (override unset → a REAL launch): build a VALID per-backend, per-lane
       argv via :func:`build_backend_argv` — but only when a ``prompt`` is
       supplied (a real lane launch always supplies one). When no ``prompt`` is
       supplied (e.g. an engine-selector test inspecting only the command SHAPE),
       fall back to the per-backend default command constant so its shape is
       observable. ``extra_args`` are appended in both sub-cases.
    """
    override = os.environ.get(RUNNER_CMD_ENV)
    if override and override.strip():
        # Test indirection: the mock runner drives every test. Use the override
        # base verbatim; append the prompt (mock ignores it) so the gated/stdin
        # path is exercised without a real CLI, then the test's extra_args.
        argv = _shlex_split(override)
        if prompt is not None:
            argv = argv + [prompt]
    elif prompt is not None:
        # Real launch: construct a valid per-backend argv from scratch.
        argv = build_backend_argv(backend, prompt, output_dir, gated,
                                  permission_mode=permission_mode)
    else:
        # Shape-only resolution (no prompt): return the per-backend default base.
        if backend == BACKEND_GEMINI:
            gem = os.environ.get(GEMINI_CMD_ENV)
            raw = gem if (gem and gem.strip()) else DEFAULT_GEMINI_CMD
        else:
            raw = DEFAULT_RUNNER_CMD
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
                         command=None) -> dict:
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
           command=None, kill_on_job_close: bool = True) -> dict:
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
    merged onto the current environment. ``backend`` ∈ {"claude","gemini"}
    selects the engine command (resolved by :func:`resolve_runner_cmd`); it is
    recorded on the job so the UI/history can show which engine ran the effort.
    ``ANCHOR_RUNNER_CMD``, when set, still overrides the command for any backend.

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
    - NON-GATED (research) **or** no prompt: ``stdin=DEVNULL`` (unchanged Wave-4
      contract — the prompt, if any, is on argv).
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
    backend = backend or DEFAULT_BACKEND
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
                                  permission_mode=permission_mode)

    full_env = dict(os.environ)
    if backend == BACKEND_GEMINI:
        full_env["TRIO_DRIVER"] = "gemini-cli-native"
    # Propagate Anchor model-family prefs so foundry/trio seats (and any agent
    # reading CODING_FAMILY / REVIEW_FAMILY) honor the dashboard knobs.
    # Pre-set env always wins over settings (caller / setx override).
    try:
        import anchor_settings as _aset
        for _k, _v in _aset.export_env_overrides().items():
            full_env.setdefault(_k, _v)
    except Exception:
        pass
    if env:
        full_env.update(env)
    
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

    # Gated lanes need a kept-open stdin PIPE so the initial prompt + the gate
    # answer can be written into the live session. Non-gated lanes keep the
    # original DEVNULL contract.
    use_stdin_pipe = bool(gated)
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
    if use_stdin_pipe and proc.stdin is not None:
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
                            cwd=cwd)

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
            project_id=project_id, folder_path=folder_path, command=command),
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
    try:
        cost = float(env.get("total_cost_usd") or 0.0)
    except (TypeError, ValueError):
        cost = 0.0
    try:
        dur = int(env.get("duration_ms") or 0)
    except (TypeError, ValueError):
        dur = 0
    return {
        "total_cost_usd": cost,
        "duration_ms": dur,
        "input_tokens": inp,
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
                            cwd=None) -> None:
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
            status=_sr.STATUS_RUNNING,
            session_id=job_id,
            worktree_path=str(cwd) if cwd else "",
            pid=pid,
            proc_create_time=proc_create_time,
            crypt_token=crypt_token or "",
        )
    except Exception:  # pragma: no cover - registry is best-effort
        pass


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

    Cancellation may have already set the status to ``cancelled``; do not
    clobber a terminal status that was set deliberately. If a ``result``
    envelope was captured from the stream (Wave 7), stamp its cost/usage/
    duration onto the record regardless of the terminal status (a cancelled
    job may still have emitted a partial result envelope before the kill).
    """
    with _LIVE_LOCK:
        live = _LIVE.get(job_id)
    if live and getattr(live, "_h_job", None) is not None:
        try:
            import proc_probe
            proc_probe.close_handle(live._h_job)
            live._h_job = None
        except Exception:
            pass

    with _paths.WRITE_LOCK:
        rec = load_record(job_id)
        if rec is None:
            return
        if result_envelope is not None:
            cost = _cost_from_envelope(result_envelope)
            rec["cost"] = cost
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
        rec["status"] = STATUS_DONE if exit_code == 0 else STATUS_FAILED
        _journal.emit_safe(rec.get("project_id") or "", _journal.EV_JOB_FINISHED, correlation_id=job_id, folder_path=rec.get("folder_path"), payload={"job_id": job_id, "status": rec.get("status")})
        _write_record(rec)
    # Mirror the terminal status onto the swarm session (gandalf finally analog),
    # OUTSIDE the write lock the registry takes its own lock internally.
    _mirror_session_status(job_id, STATUS_DONE if exit_code == 0 else STATUS_FAILED)

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

    try:
        new_rec = launch_guarded(
            spec.get("lane"),
            project_id=project_id,
            folder_path=folder_path,
            cwd=spec.get("cwd"),
            env=spec.get("env_keys") or None,
            backend=spec.get("backend") or DEFAULT_BACKEND,
            prompt=prompt,
            output_dir=spec.get("output_dir"),
            gated=spec.get("gated") or False,
            permission_mode=spec.get("permission_mode"),
            command=spec.get("command") or None,
        )
    except LaneBusyError as e:
        return {"ok": False, "reason": str(e.reason), "holder": e.holder}
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
    """Tree-kill a job and mark it ``cancelled``.

    Uses ``taskkill /T /F /PID <pid>`` on Windows to reap the full process tree
    (children + grandchildren — spike-proven). On POSIX, falls back to killing
    the process group. An already-gone process is tolerated (no crash). The
    status is set to ``cancelled`` regardless, so an external cancel is honestly
    recorded even if the process raced to exit first.

    Returns the updated record (or ``None`` if the job is unknown).
    """
    rec = load_record(job_id)
    if rec is None:
        return None

    pid = rec.get("pid")
    # Set the terminal status FIRST so the reader's _finalize() does not clobber
    # it with done/failed when the pipe closes after the kill.
    _journal.emit_safe((load_record(job_id) or {}).get("project_id") or "", _journal.EV_JOB_CANCELLED, correlation_id=job_id, folder_path=(load_record(job_id) or {}).get("folder_path"), payload={"job_id": job_id})
    _update_record(job_id, status=STATUS_CANCELLED)
    # Clear the swarm session out of RUNNING immediately (covers the no-live-reader
    # case where _finalize never runs — e.g. cancelling a job from a prior process).
    _mirror_session_status(job_id, STATUS_CANCELLED)

    if pid:
        _tree_kill(pid)

    # Give the reader thread a moment to drain + finalize the exit code.
    with _LIVE_LOCK:
        live = _LIVE.get(job_id)
    if live is not None:
        live.done.wait(timeout=10)

    return load_record(job_id)


def _tree_kill(pid) -> None:
    """Kill a process tree by PID, tolerating an already-dead process."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(pid)],
                capture_output=True, text=True, timeout=15,
                creationflags=_paths.NO_WINDOW,
            )
        except (OSError, subprocess.SubprocessError):
            # Process already gone / taskkill unavailable — not fatal.
            pass
        return
    # POSIX best-effort: kill the process group, then the pid.
    try:
        os.killpg(os.getpgid(pid), 9)
    except (OSError, ProcessLookupError):
        try:
            os.kill(pid, 9)
        except (OSError, ProcessLookupError):
            pass


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
                   kill_on_job_close: bool = True) -> dict:
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
                     command=command, kill_on_job_close=kill_on_job_close)
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
