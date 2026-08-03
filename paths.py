#!/usr/bin/env python3
"""Anchor shared path + write-lock helper (stdlib only).

Single source of truth for every Anchor data path, imported by the GUI server
(`anchor_gui.py`), the CLI engine (`anchor.py`), and the daily health check
(`anchor_healthcheck.py`).

Design (Wave 2, frozen plan):
- The *code* dir is always `Path(__file__).parent` (where this module lives).
- The *data* dir is controlled by the env var ``ANCHOR_DATA_DIR``. When that
  env var is **unset**, the data dir defaults to the **code dir** — so existing
  behavior and existing on-disk data are preserved with ZERO behavior change.
- Paths are resolved **lazily, per call** (the env var is read at resolution
  time), so a test can set ``ANCHOR_DATA_DIR`` to a tmp dir before calling.
- Importing this module performs **no** directory creation. Callers that need
  the data dirs to exist must call :func:`ensure_data_dirs` explicitly. (This
  is the deliberate fix for the carried minor finding that ``anchor.py`` ran
  ``LOGS_DIR.mkdir(...)`` at import time.)

It also exposes a single process-wide :data:`WRITE_LOCK` so concurrent
mutating requests (under ``ThreadingHTTPServer``) cannot lose an update.
"""

import os
import threading
from pathlib import Path

# Where the Anchor *code* lives. This never depends on the env var.
CODE_DIR = Path(__file__).resolve().parent

# Process-wide write lock. A single global lock is the simplest serialization
# that guarantees no lost update across concurrent markdown/JSON mutations.
# Acquire it around EVERY file mutation (markdown and JSON).
WRITE_LOCK = threading.RLock()

# Env var that decouples data location from code location.
DATA_DIR_ENV = "ANCHOR_DATA_DIR"

# Canonical filenames / subdir names (data layout), centralized here.
DASHBOARD_NAME = "DASHBOARD.md"
PROJECTS_NAME = "PROJECTS.md"
INBOX_NAME = "INBOX.md"
CANCELLED_NAME = "CANCELLED.md"
SAVED_FOR_LATER_NAME = "SAVED_FOR_LATER.md"
DASHBOARD_HTML_NAME = "dashboard.html"
DOMAINS_DIRNAME = "domains"
LOGS_DIRNAME = "logs"
HEALTH_REPORTS_DIRNAME = "health_reports"


def data_dir() -> Path:
    """Resolve the Anchor data root.

    Reads ``ANCHOR_DATA_DIR`` at call time. Unset/blank -> the code dir
    (backward compatible). Returns an absolute :class:`~pathlib.Path`. Does
    NOT create the directory.
    """
    raw = os.environ.get(DATA_DIR_ENV)
    if raw and raw.strip():
        return Path(raw).expanduser().resolve()
    return CODE_DIR


# ── Canonical data paths (each resolved lazily via data_dir()) ─────────────

def dashboard_md() -> Path:
    return data_dir() / DASHBOARD_NAME


def projects_md() -> Path:
    return data_dir() / PROJECTS_NAME


def inbox_md() -> Path:
    return data_dir() / INBOX_NAME


def cancelled_md() -> Path:
    return data_dir() / CANCELLED_NAME


def saved_for_later_md() -> Path:
    return data_dir() / SAVED_FOR_LATER_NAME


def dashboard_html() -> Path:
    return data_dir() / DASHBOARD_HTML_NAME


def domains_dir() -> Path:
    return data_dir() / DOMAINS_DIRNAME


def logs_dir() -> Path:
    return data_dir() / LOGS_DIRNAME


def health_reports_dir() -> Path:
    return data_dir() / HEALTH_REPORTS_DIRNAME


# ── Reaper (zombie-hunter → safe-to-arm) tuning knobs (Wave 2) ─────────────
# Positive-liveness corroboration windows, read at call time so a test/deploy
# can tune them via env. Each has a conservative default (over-protect: a wider
# window keeps MORE sessions, which is the safe direction). All are seconds.

REAPER_WORK_MTIME_SECS_ENV = "ANCHOR_REAPER_WORK_MTIME_SECS"
REAPER_CPU_WINDOW_SECS_ENV = "ANCHOR_REAPER_CPU_WINDOW_SECS"
REAPER_HEARTBEAT_STALE_SECS_ENV = "ANCHOR_REAPER_HEARTBEAT_STALE_SECS"

#: A worktree write within this window counts as a (corroborated) work signal.
REAPER_WORK_MTIME_SECS_DEFAULT = 120.0
#: The window over which a CPU sample is judged "active".
REAPER_CPU_WINDOW_SECS_DEFAULT = 5.0
#: A session heartbeat file older than this is STALE (grants no liveness).
REAPER_HEARTBEAT_STALE_SECS_DEFAULT = 90.0


def _env_float(name: str, default: float) -> float:
    """Read a float env knob at call time; blank/invalid → ``default``."""
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return default
    # A non-positive window is meaningless; fall back to the safe default.
    return val if val > 0 else default


def reaper_work_mtime_secs() -> float:
    """Worktree-write freshness window (``ANCHOR_REAPER_WORK_MTIME_SECS``)."""
    return _env_float(REAPER_WORK_MTIME_SECS_ENV, REAPER_WORK_MTIME_SECS_DEFAULT)


def reaper_cpu_window_secs() -> float:
    """CPU-sample activity window (``ANCHOR_REAPER_CPU_WINDOW_SECS``)."""
    return _env_float(REAPER_CPU_WINDOW_SECS_ENV, REAPER_CPU_WINDOW_SECS_DEFAULT)


def reaper_heartbeat_stale_secs() -> float:
    """Heartbeat staleness threshold (``ANCHOR_REAPER_HEARTBEAT_STALE_SECS``)."""
    return _env_float(REAPER_HEARTBEAT_STALE_SECS_ENV,
                      REAPER_HEARTBEAT_STALE_SECS_DEFAULT)


# ── Reaper bounds knobs (Wave 4 — bounded blast radius + boot grace) ────────
# The worst-case containment: a per-cycle blast-radius cap so a runaway sweep
# can never cascade, a boot/startup grace window so a freshly-started session is
# never touched before it can establish ownership, and a hard lineage-walk depth
# cap so a malformed/looping chain can never spin the transitive-parent walk.
# All read at call time so a test/deploy can tune them via env. Defaults chosen
# in the SAFE direction (small blast cap, wide grace).

REAPER_MAX_ACTIONS_PER_SWEEP_ENV = "ANCHOR_REAPER_MAX_ACTIONS_PER_SWEEP"
REAPER_BOOT_GRACE_SECS_ENV = "ANCHOR_REAPER_BOOT_GRACE_SECS"
REAPER_LINEAGE_MAX_DEPTH_ENV = "ANCHOR_REAPER_LINEAGE_MAX_DEPTH"

#: At most this many freeze/kill actions may fire per sweep cycle; the remainder
#: is deferred (logged) to the next sweep. Small on purpose — a runaway sweep is
#: halted long before it can cascade across a whole swarm.
REAPER_MAX_ACTIONS_PER_SWEEP_DEFAULT = 3
#: A session younger than this (seconds) is inside the boot/startup grace window
#: and is NEVER frozen or killed — it has not yet had time to attach a PTY,
#: register its owning job, or write its first heartbeat.
REAPER_BOOT_GRACE_SECS_DEFAULT = 300.0
#: Hard cap on how many parent hops the transitive-lineage walk may take before
#: it declares the chain malformed and abstains (PROTECT) on the whole branch.
REAPER_LINEAGE_MAX_DEPTH_DEFAULT = 64


def _env_int(name: str, default: int) -> int:
    """Read an int env knob at call time; blank/invalid/non-positive → default."""
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        val = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    # A non-positive cap/depth is meaningless; fall back to the safe default.
    return val if val > 0 else default


def reaper_max_actions_per_sweep() -> int:
    """Per-sweep blast-radius cap (``ANCHOR_REAPER_MAX_ACTIONS_PER_SWEEP``)."""
    return _env_int(REAPER_MAX_ACTIONS_PER_SWEEP_ENV,
                    REAPER_MAX_ACTIONS_PER_SWEEP_DEFAULT)


def reaper_boot_grace_secs() -> float:
    """Boot/startup grace window (``ANCHOR_REAPER_BOOT_GRACE_SECS``)."""
    return _env_float(REAPER_BOOT_GRACE_SECS_ENV,
                      REAPER_BOOT_GRACE_SECS_DEFAULT)


def reaper_lineage_max_depth() -> int:
    """Transitive-lineage walk hard depth cap (``ANCHOR_REAPER_LINEAGE_MAX_DEPTH``)."""
    return _env_int(REAPER_LINEAGE_MAX_DEPTH_ENV,
                    REAPER_LINEAGE_MAX_DEPTH_DEFAULT)


# ── Arming ladder knobs (Wave 8 — safe-to-arm control plane) ────────────────
# The daemon ships UNARMED (dry-run) and advances a rung (log → freeze → kill)
# only when a numeric bar is met, recomputed IN-PROCESS from the tamper-evident
# receipt chain. All read at call time (env-tunable) with conservative defaults
# in the SAFE direction (a HIGH sweep bar, a LOW abstain-banner threshold, a
# BOUNDED auto-thaw so a freeze can never be forgotten forever).

REAPER_ARM_MIN_SWEEPS_ENV = "ANCHOR_REAPER_ARM_MIN_SWEEPS"
REAPER_ABSTAIN_BANNER_K_ENV = "ANCHOR_REAPER_ABSTAIN_BANNER_K"
REAPER_FREEZE_MAX_SECS_ENV = "ANCHOR_REAPER_FREEZE_MAX_SECS"

#: How many CONSECUTIVE clean dry-run/observation sweeps the receipt chain must
#: show before a rung may be armed/advanced. Deliberately high — the arm bar is
#: earned by observed evidence, never asserted.
REAPER_ARM_MIN_SWEEPS_DEFAULT = 10
#: The dashboard health-banner trips when the reaper has ABSTAINED (degraded /
#: could-not-observe liveness) for MORE than this many consecutive sweeps — a
#: signal the liveness inputs are broken and the reaper is flying blind.
REAPER_ABSTAIN_BANNER_K_DEFAULT = 5
#: An auto-thaw watchdog bounds every freeze: a session frozen by the freeze-only
#: tier is automatically resumed after this many seconds so a freeze can never be
#: forgotten indefinitely (fully-reversible, self-healing first rung).
REAPER_FREEZE_MAX_SECS_DEFAULT = 3600.0


def reaper_arm_min_sweeps() -> int:
    """Consecutive-clean-sweep arm bar (``ANCHOR_REAPER_ARM_MIN_SWEEPS``)."""
    return _env_int(REAPER_ARM_MIN_SWEEPS_ENV, REAPER_ARM_MIN_SWEEPS_DEFAULT)


def reaper_abstain_banner_k() -> int:
    """Consecutive-abstain health-banner threshold (``ANCHOR_REAPER_ABSTAIN_BANNER_K``)."""
    return _env_int(REAPER_ABSTAIN_BANNER_K_ENV, REAPER_ABSTAIN_BANNER_K_DEFAULT)


def reaper_freeze_max_secs() -> float:
    """Auto-thaw watchdog bound for a freeze (``ANCHOR_REAPER_FREEZE_MAX_SECS``)."""
    return _env_float(REAPER_FREEZE_MAX_SECS_ENV, REAPER_FREEZE_MAX_SECS_DEFAULT)


def ensure_data_dirs() -> None:
    """Create the data subdirectories that Anchor writes into.

    Idempotent. Callers (server startup, CLI commands that write, health
    check) invoke this explicitly — it is intentionally NOT run on import.
    """
    base = data_dir()
    base.mkdir(parents=True, exist_ok=True)
    logs_dir().mkdir(parents=True, exist_ok=True)
    domains_dir().mkdir(parents=True, exist_ok=True)
    health_reports_dir().mkdir(parents=True, exist_ok=True)


# ── Crash-safe atomic text write (data-loss guard) ─────────────────────────

#: Bounded retry for the atomic ``os.replace`` on Windows. A concurrent
#: read-only reader momentarily holds the target file open; Windows then denies
#: the rename with ``PermissionError`` (a transient sharing violation, NOT a real
#: permission fault). The reader's handle is released within microseconds, so a
#: few short backed-off retries turn the race into a correct atomic write rather
#: than a spurious crash. POSIX ``os.replace`` never hits this — the loop is a
#: no-op there (the first attempt succeeds).
_ATOMIC_REPLACE_RETRIES = 40
_ATOMIC_REPLACE_BACKOFF_S = 0.005


def _replace_with_retry(tmp, target) -> None:
    """``os.replace(tmp, target)`` with a bounded retry over the transient
    Windows sharing-violation ``PermissionError`` raised while a concurrent
    reader has ``target`` open. Re-raises the last error if the window never
    clears within the retry budget."""
    import time as _time

    for attempt in range(_ATOMIC_REPLACE_RETRIES):
        try:
            os.replace(tmp, target)
            return
        except PermissionError:
            if attempt == _ATOMIC_REPLACE_RETRIES - 1:
                raise
            _time.sleep(_ATOMIC_REPLACE_BACKOFF_S)


def atomic_write_text(path, text, encoding="utf-8"):
    """Crash-safe text write: write to a temp file in the SAME directory, fsync, then
    os.replace() onto the target — so a crash never leaves the target truncated/partial.
    os.replace is atomic on Windows and POSIX for same-directory (same-volume) renames.

    Behaves like ``Path.write_text`` except for atomicity: pass the SAME string the
    caller already builds. Callers already hold :data:`WRITE_LOCK`, so the fixed
    ``.tmp`` sidecar name is safe from concurrent collision. The final rename goes
    through :func:`_replace_with_retry` so a concurrent read-only reader holding the
    target open (the Windows sharing-violation race) is tolerated with a bounded
    retry rather than surfacing a spurious ``PermissionError``.
    """
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding=encoding, newline="") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    _replace_with_retry(str(tmp), str(path))


# ── Fail-closed engine-sidecar root resolver (Honest Telemetry, W2) ─────────
#
# The Honest-Telemetry capture pipeline (W4) reads Claude Code's per-session
# usage sidecars from ``~/.claude/projects/<slug>/<session-uuid>.jsonl``. In ANY
# hermetic context — a pytest run, the daily healthcheck, or a redirected
# ``ANCHOR_DATA_DIR`` deploy — resolving that live ``~/.claude`` home store would
# let a test/healthcheck read (or diverge fixtures from) a real user's private
# transcripts. The resolver therefore FAILS CLOSED: it RAISES unless
# ``ANCHOR_SIDECAR_DIR`` is explicitly pointed at a fixture/temp dir. This lands
# BEFORE any finalize/capture code exists (the W2 durability substrate) so the
# capture pipeline is physically unable to open the live store in tests.

#: Env var that pins the sidecar store root to a fixture/temp dir (the ONLY way a
#: hermetic context obtains a sidecar root).
SIDECAR_DIR_ENV = "ANCHOR_SIDECAR_DIR"
#: Env marker the daily healthcheck sets on its own process (defense-in-depth so
#: a healthcheck walk that forgot to set ``ANCHOR_SIDECAR_DIR`` still fails closed
#: rather than resolving the real home store).
HEALTHCHECK_ENV = "ANCHOR_HEALTHCHECK"


class SidecarRootUnavailable(RuntimeError):
    """Raised by :func:`sidecar_root` when the engine session-JSONL sidecar
    store root cannot be resolved SAFELY (a hermetic context with
    ``ANCHOR_SIDECAR_DIR`` unset). The live ``~/.claude`` home store is never
    resolved in that case — the resolver fails closed."""


def _sidecar_hermetic_mode(env=None) -> bool:
    """True when the sidecar root MUST NOT resolve the live ``~/.claude`` store.

    Hermetic ⇔ any of: pytest is running (``PYTEST_CURRENT_TEST``), the data dir
    is redirected (``ANCHOR_DATA_DIR`` set — production leaves it unset), or the
    healthcheck marked its process (``ANCHOR_HEALTHCHECK``). Read at call time so
    a test/deploy can toggle it. Pure.
    """
    e = os.environ if env is None else env
    if e.get("PYTEST_CURRENT_TEST"):
        return True
    if (e.get(DATA_DIR_ENV) or "").strip():
        return True
    if (e.get(HEALTHCHECK_ENV) or "").strip():
        return True
    return False


def sidecar_root(env=None) -> Path:
    """Resolve the engine session-JSONL sidecar store root — FAIL CLOSED.

    - ``ANCHOR_SIDECAR_DIR`` set (non-blank) → that dir (expanded + resolved).
      This is the ONLY way a hermetic context (test / healthcheck / redirected
      data) obtains a sidecar root, and it points at a fixture/temp dir — never
      the real home store.
    - Otherwise, in a hermetic context → raise :class:`SidecarRootUnavailable`
      (the live ``~/.claude`` store is never touched).
    - Otherwise (genuine production: no redirect, not a test, not the
      healthcheck) → ``~/.claude/projects``.

    Never OPENS anything — it only resolves and returns the path (the caller
    reads). Pure aside from reading the environment + the home dir.
    """
    e = os.environ if env is None else env
    raw = e.get(SIDECAR_DIR_ENV)
    if raw and raw.strip():
        return Path(raw).expanduser().resolve()
    if _sidecar_hermetic_mode(e):
        raise SidecarRootUnavailable(
            "sidecar root refused: ANCHOR_SIDECAR_DIR is unset in a hermetic "
            "(test / healthcheck / redirected-data) context — the live "
            "~/.claude store is never resolved here. Set ANCHOR_SIDECAR_DIR to "
            "a fixture or temp dir.")
    return Path.home() / ".claude" / "projects"


# ── Auth helper (Wave 2) ───────────────────────────────────────────────────

AUTH_TOKEN_ENV = "ANCHOR_TOKEN"


def expected_token():
    """Return the configured shared-secret token, or ``None`` if unset.

    ``None`` means auth is disabled (local-only backward compatibility).
    """
    tok = os.environ.get(AUTH_TOKEN_ENV)
    if tok and tok.strip():
        return tok
    return None


def auth_ok(provided) -> bool:
    """Token-check predicate for mutating ``/api/*`` requests.

    - If no token is configured (env unset) -> auth disabled -> always True.
    - Otherwise the provided token must match in CONSTANT TIME
      (``hmac.compare_digest`` — a plain ``==`` leaks match-length timing).

    Kept tiny and pure so it is unit-testable on its own.
    """
    want = expected_token()
    if want is None:
        import pillar_flags
        try:
            mode = pillar_flags.current_flags()[pillar_flags.FLAG_AUTH]
        except Exception:
            mode = pillar_flags.FLAG_DEFAULTS[pillar_flags.FLAG_AUTH]
        if mode == "enforce":
            return False
        return True
    import hmac
    return hmac.compare_digest(str(provided or ""), str(want))


def token_from_authorization(header_value):
    """Extract the shared-secret token from an ``Authorization`` header value.

    W2 (re-architecture 2026-07): every consumer of a token-gated route has a
    header-based token path — ``Authorization: Bearer <token>`` is the standard
    spelling (scheme case-insensitive). A bare token value (no scheme) is also
    accepted so simple scripts (curl one-liners, PowerShell probes) don't need
    to know the Bearer convention. ``?token=`` remains only for the WS/SSE
    transports, where browsers cannot set request headers.

    Returns the token string, or ``None`` when the header is absent/blank
    (callers then fall back to the legacy senders: ``X-Anchor-Token``,
    ``?token=``, JSON-body ``token``). Pure — never reads the environment.
    """
    if header_value is None:
        return None
    value = str(header_value).strip()
    if not value:
        return None
    lowered = value.lower()
    if lowered == "bearer":
        # A scheme word with no token (e.g. "Bearer ") is NOT a bare token.
        return None
    if lowered.startswith("bearer "):
        value = value[len("bearer "):].strip()
    return value or None


# ── Cookie-based browser auth (rearch 2026-07 · W9) ─────────────────────────

#: The auth cookie name. Browser PAGE NAVIGATION authenticates off this cookie
#: (set at login), so no shared-secret token ever rides in a page URL — the W9
#: cutover keeps ``?token=`` ONLY on the WS/SSE transports the cookie spike did
#: not clear for every client (SPIKE-COOKIE-WS-VERDICT: desktop WS proven, the
#: iPhone PWA unproven → its ``?token=`` fallback stays).
AUTH_COOKIE_NAME = "anchor_auth"


def token_from_cookie(cookie_header, cookie_name=AUTH_COOKIE_NAME):
    """Extract the auth token from a request ``Cookie`` header value (W9).

    The desktop cookie-through-WS spike proved the browser sends this cookie on
    the ``term_ws`` upgrade too, so the same value authenticates both page
    navigation and the terminal transport. Parses the standard
    ``name=value; name2=value2`` cookie syntax and returns the value of
    ``cookie_name`` verbatim (the token is an opaque shared secret — no URL
    unescaping is applied). Returns ``None`` when the header is absent/blank or
    the cookie is not present. Pure — never reads the environment.
    """
    if not cookie_header:
        return None
    for part in str(cookie_header).split(";"):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        if k.strip() == cookie_name:
            v = v.strip()
            return v or None
    return None


def build_auth_cookie(token, *, secure=False, clear=False,
                      cookie_name=AUTH_COOKIE_NAME):
    """Build the ``Set-Cookie`` header VALUE for the auth cookie (W9).

    The cookie carries the shared-secret token so the browser presents it
    automatically on same-origin page navigation and the ``term_ws`` upgrade.
    Attributes:

      * ``HttpOnly`` — JS can never read the cookie value (an XSS cannot exfil
        the token from the cookie jar);
      * ``SameSite=Strict`` — never sent cross-site (this is a single-origin
        app; also a CSRF hardening — mutating POSTs still require the explicit
        ``X-Anchor-Token`` header, never the cookie alone);
      * ``Path=/`` — the whole app;
      * ``Secure`` — added ONLY when the request arrived over HTTPS (the
        Tailscale Serve origin) and omitted on the plain-HTTP loopback so local
        ``http://localhost:8777`` use still works.

    ``clear=True`` emits an immediate-expiry deletion cookie (logout). Pure
    string builder — stdlib only.
    """
    if clear:
        attrs = [f"{cookie_name}=", "Path=/", "Max-Age=0",
                 "HttpOnly", "SameSite=Strict"]
    else:
        attrs = [f"{cookie_name}={token}", "Path=/",
                 "HttpOnly", "SameSite=Strict"]
    if secure:
        attrs.append("Secure")
    return "; ".join(attrs)


# ── Silent subprocess spawning (John's no-visible-shells rule) ──────────────

#: OR this into every ``subprocess.Popen/run`` ``creationflags`` on Windows so a
#: console child can never flash a window (the service is windowless, but a
#: console-subsystem child may still allocate its own console without this).
#: Zero on POSIX, so call sites can apply it unconditionally.
NO_WINDOW = getattr(__import__("subprocess"), "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


# ── Idempotent migration (Wave 2) ──────────────────────────────────────────

# The canonical set of top-level data files + data subdirectories that make up
# an Anchor data layout. Used by migrate_data() to copy legacy data into a
# fresh ANCHOR_DATA_DIR with zero loss.
_DATA_FILES = (
    DASHBOARD_NAME,
    PROJECTS_NAME,
    INBOX_NAME,
    CANCELLED_NAME,
    SAVED_FOR_LATER_NAME,
)
_DATA_SUBDIRS = (DOMAINS_DIRNAME, LOGS_DIRNAME, HEALTH_REPORTS_DIRNAME)


def migrate_data(source=None, dest=None):
    """Migrate the legacy Anchor markdown/data layout into the data dir.

    - ``source`` defaults to the code dir (where the legacy committed markdown
      lives); ``dest`` defaults to the resolved data dir (ANCHOR_DATA_DIR).
    - Copies the canonical data files + data subdirectories from source to
      dest. **Never deletes or overwrites** an existing destination file, so it
      is idempotent: running twice produces the same result with nothing
      duplicated or lost.
    - When ``source`` and ``dest`` resolve to the same path (the default when
      ANCHOR_DATA_DIR is unset), it is a no-op.

    Returns a dict report: ``{"copied": [...], "skipped_existing": [...],
    "noop": bool}``.
    """
    import shutil

    src = Path(source).resolve() if source is not None else CODE_DIR
    dst = Path(dest).resolve() if dest is not None else data_dir()

    report = {"copied": [], "skipped_existing": [], "noop": False}
    if src == dst:
        report["noop"] = True
        return report

    dst.mkdir(parents=True, exist_ok=True)

    # Top-level files.
    for name in _DATA_FILES:
        s = src / name
        d = dst / name
        if not s.exists():
            continue
        if d.exists():
            report["skipped_existing"].append(name)
            continue
        shutil.copy2(s, d)
        report["copied"].append(name)

    # Data subdirectories (copy file-by-file so existing files are preserved).
    for sub in _DATA_SUBDIRS:
        s_dir = src / sub
        if not s_dir.is_dir():
            continue
        d_dir = dst / sub
        d_dir.mkdir(parents=True, exist_ok=True)
        for s_file in sorted(s_dir.rglob("*")):
            if s_file.is_dir():
                continue
            rel = s_file.relative_to(s_dir)
            d_file = d_dir / rel
            key = f"{sub}/{rel.as_posix()}"
            if d_file.exists():
                report["skipped_existing"].append(key)
                continue
            d_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s_file, d_file)
            report["copied"].append(key)

    return report


# ── Bind-retry helper (Wave 2) ─────────────────────────────────────────────

def bind_with_retry(make_server, attempts: int = 5, delay: float = 0.25):
    """Construct/bind a server with a bounded retry loop.

    ``make_server`` is a zero-arg callable that constructs (and binds) the
    server, returning it. If it raises :class:`OSError` (e.g. a slow Tailscale
    interface not yet up), retry up to ``attempts`` times with ``delay``
    seconds between tries. Re-raises the last error if all attempts fail.

    A bind that fails because the address is already **owned by another
    instance** (EADDRINUSE / WSAEADDRINUSE) is NOT a transient hiccup — retrying
    can never succeed while the other process holds the port — so it is
    re-raised immediately instead of consuming the retry budget. Every other
    OSError (notably EADDRNOTAVAIL / WSAEADDRNOTAVAIL — the address not yet
    assignable on a slow-to-come-up Tailscale interface — and generic, errno-less
    OSErrors) is treated as transient and retried. This keeps the original
    Wave-2 retry contract (a plain ``OSError("...")`` with no errno still
    retries) intact.

    Structured so a test can monkeypatch ``socket.bind`` to fail once then
    succeed and observe recovery.
    """
    import time

    last_exc = None
    for i in range(max(1, attempts)):
        try:
            return make_server()
        except OSError as exc:  # bind failures surface as OSError
            last_exc = exc
            # "Address already owned by another Anchor" → no point retrying.
            if classify_bind_error(exc) == "exit":
                raise
            if i < attempts - 1:
                time.sleep(delay)
    raise last_exc


# ── Single-instance guard (Wave 3) ─────────────────────────────────────────
#
# The Anchor server runs on a FIXED port (8777) under the NSSM service. If a
# duplicate/orphan process is already squatting that port, a second process
# binding with SO_REUSEADDR could quietly steal/share it and serve stale code.
# The guard makes that impossible: the real fixed-port bind requests EXCLUSIVE
# ownership (Windows SO_EXCLUSIVEADDRUSE), and a bind that loses to an existing
# owner is classified as "another instance already running → exit cleanly"
# rather than retried forever.
#
# Both helpers below are pure / side-effect-free so they unit-test in isolation
# without ever touching the real port or the live service.

# errno values for "address already in use" across platforms. WSAEADDRINUSE is
# the Windows Sockets code (10048); EADDRINUSE is the POSIX code (98 on Linux,
# 48 on macOS — provided by the stdlib ``errno`` module per-platform).
_ADDR_IN_USE_ERRNOS = set()


def _addr_in_use_errnos():
    """The set of errno values that mean 'address already in use'."""
    global _ADDR_IN_USE_ERRNOS
    if _ADDR_IN_USE_ERRNOS:
        return _ADDR_IN_USE_ERRNOS
    import errno as _errno
    vals = set()
    for name in ("EADDRINUSE", "WSAEADDRINUSE"):
        v = getattr(_errno, name, None)
        if v is not None:
            vals.add(v)
    # WSAEADDRINUSE numeric fallback (older Pythons may omit the alias on
    # non-Windows; the number is stable on Windows).
    vals.add(10048)
    _ADDR_IN_USE_ERRNOS = vals
    return vals


def classify_bind_error(exc) -> str:
    """Classify a bind-time :class:`OSError`.

    Returns:
      - ``"exit"``  — the address is already in use by **another instance**
        (EADDRINUSE / WSAEADDRINUSE). Retrying cannot help; the caller should
        log and exit cleanly so it does not become a duplicate.
      - ``"retry"`` — any other failure (e.g. EADDRNOTAVAIL: the address is not
        yet assignable on a slow-to-come-up interface), including generic
        errno-less OSErrors. These are treated as transient.

    Pure: inspects only the exception's ``errno`` / ``winerror``. Never raises.
    """
    in_use = _addr_in_use_errnos()
    for attr in ("errno", "winerror"):
        code = getattr(exc, attr, None)
        if code is not None and code in in_use:
            return "exit"
    return "retry"


def use_exclusive_bind(host, port) -> bool:
    """Predicate: should this bind request EXCLUSIVE port ownership?

    True only for the **real fixed-port** server path on Windows:
      - we are on Windows (SO_EXCLUSIVEADDRUSE only exists there), AND
      - ``port`` is a concrete non-zero port (the tests and the health check
        bind ``port=0`` for an OS-assigned ephemeral port; exclusive mode must
        NOT be applied there, or it would change ephemeral-bind semantics).

    Kept pure so it is unit-testable without opening a socket.
    """
    import sys as _sys
    import socket as _socket

    if _sys.platform != "win32":
        return False
    if not hasattr(_socket, "SO_EXCLUSIVEADDRUSE"):
        return False
    try:
        return int(port) != 0
    except (TypeError, ValueError):
        return False


def use_posix_exclusive_bind(host, port) -> bool:
    """Predicate: should this bind claim EXCLUSIVE ownership on **non-Windows**?

    share-distro v1 Wave 2 (MASTER-PLAN decision #6 — POSIX single-instance
    guard). POSIX has no ``SO_EXCLUSIVEADDRUSE``; instead the guard simply
    leaves ``SO_REUSEADDR`` **off** for the real fixed port so a second bind
    fails with ``EADDRINUSE`` (which :func:`classify_bind_error` then maps to a
    clean ``exit(0)`` — parity with the Windows guard). This is True only for the
    real fixed-port path off Windows:

      - we are NOT on Windows, AND
      - ``port`` is a concrete non-zero port (the tests / health check bind
        ``port=0`` for an OS-assigned ephemeral port and must NOT go exclusive,
        or every ephemeral bind across the suite would lose ``SO_REUSEADDR``).

    Pure / side-effect-free so it unit-tests without opening a socket. ONE locked
    mechanism (no pidfile), reusing the existing ``classify_bind_error`` seam.
    """
    import sys as _sys

    if _sys.platform == "win32":
        return False
    try:
        return int(port) != 0
    except (TypeError, ValueError):
        return False
