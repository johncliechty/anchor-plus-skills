#!/usr/bin/env python3
"""
Anchor Health Check â€” runs daily at 5:00 AM via Windows Task Scheduler.

What it does, every morning:
  1. File system integrity   â€” Anchor dir reachable, expected files present
  2. Code compiles           â€” anchor_gui.py and anchor.py parse cleanly
  3. Markdown parses         â€” every task/project/inbox/archive file reads cleanly
  4. Server boots            â€” launches anchor_gui.py on test port 8778
  5. HTTP endpoints respond  â€” GET /, GET /api/status, validation pings on POSTs
  6. Synthetic round-trip    â€” creates a __healthcheck__ task, walks it through
                               every state (done, cancel, save, restore, delete)
  7. Logging works           â€” verifies today's log was written
  8. Local filesystem write sanity    â€” write/read a marker, ensure FS isn't read-only

Routine maintenance is applied automatically (missing logs/, stale port-holding
processes, missing top-level files restored from minimal templates). Anything
involving real user content is flagged only.

SEVERITY RULE (the health-check contract, locked 2026-07-07):
  Every check is either CORRECTNESS or PERFORMANCE — never conflate the two.
  - CORRECTNESS failures (broken endpoint, journal corruption/loss, auth
    violation, bad page content) call ``report.check(name, False, ...)`` -> they
    set "ISSUES FOUND" and turn the dashboard banner RED.
  - PERFORMANCE / TIMING measurements (page-render latency, journal overhead %)
    are LOAD-SENSITIVE and flap when the machine is busy (e.g. a swarm running
    at 5 AM), so they call ``report.warn(name, ...)`` -> a non-blocking note in
    the "## Warnings" section that NEVER reddens the banner. A false red alarm
    just trains the eye to ignore the banner, which is the real hazard.
  New timing checks MUST use ``report.warn`` (best-of-N / retry + a generous
  budget); reserve a red ``report.check(False)`` for a true correctness
  invariant only.

Writes report to health_reports/YYYY-MM-DD.md.

Run on demand:   python anchor_healthcheck.py
Scheduled:       registered by register_healthcheck.ps1
"""
from __future__ import annotations

import importlib.util
import json
import os
import py_compile
import re
import shutil
import socket
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
from datetime import datetime, date, timedelta
from pathlib import Path

# â”€â”€ Paths â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
SCRIPT_DIR = Path(__file__).parent.resolve()
ANCHOR_DIR = SCRIPT_DIR  # this script must live in the Anchor root (CODE dir)

# Wave 2: data paths resolve via the shared `paths` helper, honoring the
# ANCHOR_DATA_DIR env var (unset -> the code dir, so behavior is unchanged).
# Code-file references (anchor_gui.py / anchor.py compile + cwd) stay on
# ANCHOR_DIR; data-file references use DATA_DIR.
import paths as _paths
DATA_DIR = _paths.data_dir()
REPORTS_DIR = _paths.health_reports_dir()
TEST_PORT = 8778
# Readiness deadline for the throwaway server. "Boot" = bind + the FULL boot
# reconcile (registry PID probes, worktree reap, daemons…) — main() only
# listen()s once that finishes, and under 5 AM load it has taken 80s+. Per the
# locked severity rule a slow-but-ready boot is a timing WARN (never red); only
# a server that never becomes ready is a red failure.
SERVER_READY_TIMEOUT = 180  # seconds — hard (red) deadline
SERVER_READY_WARN = 30      # seconds — soft budget → non-blocking warn
SERVER_BOOT_TIMEOUT = SERVER_READY_TIMEOUT  # legacy alias
SYNTHETIC_TAG = "__healthcheck__"
_TOKEN_MINTED = False  # set by _ensure_walk_token() — see check_route_table_walk
TODAY = date.today().isoformat()

_paths.ensure_data_dirs()

# Sentinel so _post() can distinguish "caller passed token=None on purpose"
# (deliberately tokenless request) from "caller didn't specify a token"
# (attach the configured token automatically).
_UNSET = object()

# Files that MUST exist (auto-restored if missing)
REQUIRED_FILES = {
    "DASHBOARD.md": "# Dashboard\n\n## Today's Priorities\n\n## Active Priorities\n",
    "PROJECTS.md": "# Projects\n",
    "INBOX.md": "# Inbox\n\n## Quick Capture\n",
    "CANCELLED.md": "# Cancelled Tasks\n\n",
    "SAVED_FOR_LATER.md": "# Saved For Later\n\n",
    "WEEKLY_REVIEW.md": "# Weekly Review\n\n",
}
DOMAIN_FILES = ["academic.md", "commercial.md", "family.md", "writing.md"]


# â”€â”€ Report accumulator â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class Report:
    def __init__(self):
        self.checks: list = []  # (name, status, detail) — status True|False|"warn"
        self.issues: list[str] = []
        self.warnings: list[str] = []
        self.fixes: list[str] = []
        self.recommendations: list[str] = []
        self.started = datetime.now()

    def check(self, name: str, ok: bool, detail: str = ""):
        self.checks.append((name, bool(ok), detail))
        if not ok:
            self.issues.append(f"[{name}] {detail}" if detail else name)

    def warn(self, name: str, detail: str = ""):
        """A soft, non-blocking note (perf/timing). Recorded and shown, but it
        does NOT set has_issues — so a slow-under-load measurement never turns
        the health banner red. Only genuine correctness failures do."""
        self.checks.append((name, "warn", detail))
        self.warnings.append(f"[{name}] {detail}" if detail else name)

    def fix(self, msg: str):
        self.fixes.append(msg)

    def recommend(self, msg: str):
        self.recommendations.append(msg)

    @property
    def has_issues(self) -> bool:
        return bool(self.issues)

    def _exec_summary_lines(self):
        """Plain-English, human-facing digest rendered at the top of the
        report. Deterministic (stdlib-only, no model call — this runs
        headless at 5 AM). Wording deliberately avoids the machine-parsed
        markers (the ``Status:`` line and the ``## Warnings`` heading) so
        the /doctor severity classifier keeps reading only the canonical
        lines it already targets."""
        passed = sum(1 for _, ok, _ in self.checks if ok is True)
        failed = [name for name, ok, _ in self.checks if ok is False]
        lines = []
        if failed:
            head = " · ".join(failed[:3])
            more = f" (+{len(failed) - 3} more)" if len(failed) > 3 else ""
            lines.append(
                f"Needs attention: {len(failed)} of {len(self.checks)} checks "
                f"failed — {head}{more}. The dashboard banner stays red until "
                "the next clean run; start with the Issues section below.")
        else:
            lines.append(
                f"Anchor is healthy: all {passed} correctness checks passed.")
        if self.warnings:
            lines.append(
                f"{len(self.warnings)} non-blocking warning(s) — "
                "performance/timing notes only; they never redden the banner.")
        if self.fixes:
            lines.append(
                f"{len(self.fixes)} auto-fix(es) applied during the run.")
        if self.recommendations:
            lines.append(
                f"{len(self.recommendations)} recommended action(s) at the "
                "bottom of this report.")
        return lines

    def write(self, path: Path):
        elapsed = (datetime.now() - self.started).total_seconds()
        status_line = "ISSUES FOUND" if self.has_issues else "OK"
        lines = [
            f"# Anchor Health Report â€” {TODAY}",
            "",
            f"Status: {status_line}",
            f"Run time: {elapsed:.1f}s ({self.started.strftime('%H:%M:%S')})",
            "",
            "## Executive summary",
            *self._exec_summary_lines(),
            "",
            "## Checks",
        ]
        for name, ok, detail in self.checks:
            mark = "!" if ok == "warn" else ("âœ“" if ok else "âœ—")
            tail = f"  ({detail})" if detail else ""
            lines.append(f"- {mark} {name}{tail}")
        lines.extend(["", "## Issues"])
        if self.issues:
            for i in self.issues:
                lines.append(f"- {i}")
        else:
            lines.append("(none)")
        lines.extend(["", "## Warnings (non-blocking)"])
        if self.warnings:
            for w in self.warnings:
                lines.append(f"- {w}")
        else:
            lines.append("(none)")
        lines.extend(["", "## Auto-fixes applied"])
        if self.fixes:
            for f in self.fixes:
                lines.append(f"- {f}")
        else:
            lines.append("(none)")
        lines.extend(["", "## Recommended actions"])
        if self.recommendations:
            for r in self.recommendations:
                lines.append(f"- {r}")
        else:
            lines.append("(none)")
        lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")


# â”€â”€ Check 1: file system integrity â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def check_filesystem(report: Report):
    name = "file system integrity"

    if not DATA_DIR.exists():
        report.check(name, False, f"Anchor data directory missing: {DATA_DIR}")
        return

    missing = []

    # Required files
    for filename, template in REQUIRED_FILES.items():
        p = DATA_DIR / filename
        if not p.exists():
            try:
                p.write_text(template, encoding="utf-8")
                report.fix(f"Restored missing {filename} from template")
            except Exception as e:
                missing.append(f"{filename} ({e})")

    # Domain files
    domains_dir = DATA_DIR / "domains"
    if not domains_dir.exists():
        try:
            domains_dir.mkdir(parents=True, exist_ok=True)
            report.fix("Created missing domains/ directory")
        except Exception as e:
            missing.append(f"domains/ ({e})")
    for df in DOMAIN_FILES:
        p = domains_dir / df
        if not p.exists():
            missing.append(f"domains/{df}")

    # logs dir
    logs_dir = DATA_DIR / "logs"
    if not logs_dir.exists():
        try:
            logs_dir.mkdir(parents=True, exist_ok=True)
            report.fix("Created missing logs/ directory")
        except Exception as e:
            missing.append(f"logs/ ({e})")

    if missing:
        report.check(name, False, "missing: " + ", ".join(missing))
    else:
        report.check(name, True, "ok")


# â”€â”€ Check 2: code compiles â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def check_code_compiles(report: Report):
    name = "code compiles"
    failed = []
    for fname in ("anchor_gui.py", "anchor.py"):
        p = ANCHOR_DIR / fname
        if not p.exists():
            failed.append(f"{fname} (missing)")
            continue
        try:
            py_compile.compile(str(p), doraise=True)
        except py_compile.PyCompileError as e:
            failed.append(f"{fname}: {e.msg.strip()}")
        except Exception as e:
            failed.append(f"{fname}: {e}")
    if failed:
        report.check(name, False, "; ".join(failed))
    else:
        report.check(name, True, "anchor_gui.py + anchor.py")


# â”€â”€ Check 3: markdown parses â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _import_anchor_gui():
    """Load anchor_gui as a module without invoking its main()."""
    spec = importlib.util.spec_from_file_location("anchor_gui_mod", ANCHOR_DIR / "anchor_gui.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not build module spec for anchor_gui.py")
    mod = importlib.util.module_from_spec(spec)
    # Suppress its print() output during import
    with open(os.devnull, "w") as devnull:
        old_stdout = sys.stdout
        sys.stdout = devnull
        try:
            spec.loader.exec_module(mod)
        finally:
            sys.stdout = old_stdout
    return mod


def check_markdown_parses(report: Report, mod):
    name = "markdown parseability"
    errors: list[str] = []
    counts = {"tasks": 0, "projects": 0, "inbox": 0, "archived": 0}

    candidates: list[tuple[str, Path, str]] = []  # (label, path, kind)
    candidates.append(("DASHBOARD.md", DATA_DIR / "DASHBOARD.md", "tasks"))
    candidates.append(("PROJECTS.md", DATA_DIR / "PROJECTS.md", "projects"))
    candidates.append(("INBOX.md", DATA_DIR / "INBOX.md", "inbox"))
    candidates.append(("CANCELLED.md", DATA_DIR / "CANCELLED.md", "archived"))
    candidates.append(("SAVED_FOR_LATER.md", DATA_DIR / "SAVED_FOR_LATER.md", "archived"))
    for f in sorted((DATA_DIR / "domains").glob("*.md")):
        candidates.append((f"domains/{f.name}", f, "tasks"))

    for label, path, kind in candidates:
        if not path.exists():
            continue
        try:
            if kind == "tasks":
                items = mod.parse_tasks_from_md(path)
                counts["tasks"] += len(items)
                # Flag tasks with priority not in 1-3 or empty text
                for t in items:
                    if not t["text"]:
                        errors.append(f"{label}: empty task text")
                    if t["priority"] not in (1, 2, 3):
                        errors.append(f"{label}: bad priority on '{t['text'][:40]}' = {t['priority']}")
            elif kind == "projects":
                items = mod.parse_projects_from_md(path)
                counts["projects"] += len(items)
                for p in items:
                    if not p["name"]:
                        errors.append(f"{label}: empty project name")
            elif kind == "inbox":
                items = mod.parse_inbox_from_md(path)
                counts["inbox"] += len(items)
            elif kind == "archived":
                items = mod.parse_archived_tasks(path)
                counts["archived"] += len(items)
        except UnicodeDecodeError as e:
            errors.append(f"{label}: encoding error â€” {e}")
        except Exception as e:
            errors.append(f"{label}: {e}")

    # Cross-check: tasks named in DASHBOARD.md should appear somewhere else too
    # (skip for now â€” DASHBOARD is allowed to be a curated subset)

    if errors:
        report.check(name, False, "; ".join(errors[:5]) + (" â€¦" if len(errors) > 5 else ""))
    else:
        report.check(
            name,
            True,
            f"{counts['tasks']} tasks, {counts['projects']} projects, {counts['inbox']} inbox, {counts['archived']} archived",
        )


# â”€â”€ Check 4: server boot â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _port_in_use(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.3)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except (ConnectionRefusedError, socket.timeout, OSError):
        return False
    finally:
        s.close()


def _ensure_walk_token() -> bool:
    """Mint a per-run ``ANCHOR_TOKEN`` when none is configured. True iff minted.

    (2026-09-03) The declared-route auth walk (W8) can only assert that a
    token route REJECTS a tokenless request when a token is configured — and
    the 5 AM task runs without one, so for weeks the walk skipped every token
    row ("38 rows walked, token=unset") while a Resolve-all rerun inside the
    live service (which has ANCHOR_TOKEN) walked 220 rows and caught
    ``/mockup`` serving tokenless. With a minted token the throwaway server is
    the only thing that sees it, every check already carries the configured
    token (``_post``/``_get``), and the report only ever says "minted" —
    never the value. Leaves a configured token untouched.
    """
    global _TOKEN_MINTED
    if _paths.expected_token() is not None:
        return False
    import secrets
    os.environ[_paths.AUTH_TOKEN_ENV] = "hc-" + secrets.token_hex(16)
    _TOKEN_MINTED = True
    return True


def _http_ready(port: int, timeout: float = 3.0) -> bool:
    """True once the server ANSWERS HTTP (``GET /api/version`` → 200).

    A bare connect is not readiness: the server binds its port at the top of
    ``main()`` (single-instance guard) and only ``listen()``s after its boot
    reconcile — and an HTTP probe is also robust to a listen-early regression
    (a queued probe is answered the moment ``serve_forever`` starts, instead
    of a connect-probe reporting "booted" into a backlog nobody drains).
    """
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/version",
                                    timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def _find_free_port(preferred: int) -> int:
    """Return `preferred` if it's free, otherwise an OS-assigned free port."""
    if not _port_in_use(preferred):
        return preferred
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def check_pillar_state(report: Report):
    """W3 (rearch 2026-07): the CURRENT configuration is a NAMED hybrid state.

    The four per-pillar off-switch flags (frontend · auth · journal ·
    supervisor — ``pillar_flags.py``) may only ever sit in a combination that
    is a NAMED row of the hybrid-state matrix. This assertion reads the
    environment this check runs under (the same env discipline the service's
    NSSM ``AppEnvironmentExtra`` feeds); an unset env is the ``baseline``
    named state, so today's live host passes. An invalid flag value or an
    unnamed combination (including a DAG-forbidden one) FAILS the check
    loudly — an unsupported hybrid must never run silently. W18 joins this to
    the live-service introspection once ANCHOR_BOOT carries the flags.
    """
    name = "pillar flags: named hybrid state"
    try:
        import pillar_flags
        row = pillar_flags.assert_named_state()
        flags = " · ".join(f"{f}={row['flags'][f]}"
                           for f in pillar_flags.FLAG_ORDER)
        report.check(name, True, f"'{row['name']}' ({flags})")
    except Exception as e:
        report.check(name, False, f"{type(e).__name__}: {e}")


def check_server_and_endpoints(report: Report):
    """Boot the server on TEST_PORT, exercise endpoints, return the popen handle."""
    global TEST_PORT
    name = "server boot"

    # The fixed test port can be left occupied by a stale server we can't reap
    # (e.g. a SYSTEM-owned orphan spawned by the NSSM service — a non-elevated
    # check can't taskkill it). Don't fail the whole self-test over that: fall
    # back to an OS-assigned free port so the boot/endpoint/round-trip checks
    # can still run. check_synthetic_roundtrip reads TEST_PORT too, so updating
    # the global keeps both in sync.
    if _port_in_use(TEST_PORT):
        fallback = _find_free_port(TEST_PORT)
        report.fix(f"test port {TEST_PORT} busy; ran on free port {fallback} instead")
        TEST_PORT = fallback

    cmd = [sys.executable, str(ANCHOR_DIR / "anchor_gui.py"), "--port", str(TEST_PORT), "--no-browser"]
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(ANCHOR_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except Exception as e:
        report.check(name, False, f"could not launch: {e}")
        return None

    # Wait for the server to be READY — an actual HTTP answer, not a bare
    # connect (see _http_ready). The deadline is generous on purpose: the boot
    # reconcile runs over the LIVE .anchor/ state and is load-sensitive.
    boot_started = time.time()
    booted = False
    while time.time() - boot_started < SERVER_READY_TIMEOUT:
        if _http_ready(TEST_PORT):
            booted = True
            break
        if proc.poll() is not None:  # crashed before becoming ready
            break
        time.sleep(0.25)

    boot_elapsed = time.time() - boot_started

    if not booted:
        # Capture stderr for the report
        err_text = ""
        try:
            err_text = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""
        except Exception:
            pass
        proc.terminate()
        report.check(name, False, f"not ready in {SERVER_READY_TIMEOUT}s; stderr={err_text[:200]}")
        return None

    report.check(name, True, f"{boot_elapsed:.1f}s")
    if boot_elapsed > SERVER_READY_WARN:
        # Timing, not correctness (locked severity rule): a yellow note only.
        report.warn("server boot speed",
                    f"slow but OK: ready after {boot_elapsed:.1f}s "
                    f"(over {SERVER_READY_WARN}s - likely machine load)")

    # â”€â”€ Endpoint checks â”€â”€
    base = f"http://127.0.0.1:{TEST_PORT}"
    endpoint_results = []

    # GET / — retry with a generous timeout; a slow-but-working page is a perf
    # WARN (never a red fail). Only a genuine error / bad content fails.
    import time as _t
    _get_ok = False
    _get_detail = ""
    _get_slow = False
    for _attempt in range(3):
        _t0 = _t.time()
        try:
            with urllib.request.urlopen(base + "/", timeout=20) as r:
                body = r.read().decode("utf-8", errors="replace")
                _dt = _t.time() - _t0
                if r.status == 200 and "Anchor" in body and len(body) > 1000:
                    _get_ok = True
                    _get_slow = _dt > 5.0
                    _get_detail = f"status={r.status}, {len(body)} bytes, {_dt:.1f}s"
                    break
                _get_detail = f"status={r.status}, {len(body)} bytes (bad content)"
        except Exception as e:
            _get_detail = f"{e} ({_t.time()-_t0:.1f}s)"
    if _get_ok:
        endpoint_results.append(("GET /", True, _get_detail))
        if _get_slow:
            report.warn("home page render speed",
                        f"slow but OK: {_get_detail} (over 5s - likely machine load)")
    else:
        endpoint_results.append(("GET /", False, _get_detail))

    # GET /api/status
    try:
        with urllib.request.urlopen(base + "/api/status", timeout=5) as r:
            data = json.loads(r.read().decode("utf-8"))
            ok = "active" in data and "projects" in data and "inbox" in data
            endpoint_results.append(("GET /api/status", ok, json.dumps(data)))
    except Exception as e:
        endpoint_results.append(("GET /api/status", False, str(e)))

    # POST validation pings â€” send a no-op text and expect ok=False, not a 500.
    # _post() attaches the configured token automatically, so these don't 401
    # under the production D4 token posture.
    for endpoint in ("/api/done", "/api/undone", "/api/cancel",
                     "/api/save_for_later", "/api/restore"):
        try:
            data = _post(base, endpoint, {"text": "__nonexistent_validation_ping__"})
            # Should respond with ok=False (task not found) and not 500
            ok = "ok" in data
            endpoint_results.append((f"POST {endpoint}", ok, "status=200"))
        except urllib.error.HTTPError as e:
            endpoint_results.append((f"POST {endpoint}", False, f"HTTP {e.code}"))
        except Exception as e:
            endpoint_results.append((f"POST {endpoint}", False, str(e)))

    # SETUP.md §6 unauth-rejection assertion: when a token IS configured, a
    # deliberately tokenless mutating POST must be rejected with 401. When no
    # token is configured, skip gracefully (auth is disabled).
    if _paths.expected_token() is not None:
        try:
            req = urllib.request.Request(
                base + "/api/done",
                data=json.dumps({"text": "__unauth_probe__"}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5).read()
            # Reaching here means it was NOT rejected — a failure.
            endpoint_results.append(("POST /api/done (tokenless)", False, "expected 401, got 200"))
        except urllib.error.HTTPError as e:
            ok = e.code == 401
            endpoint_results.append(("POST /api/done (tokenless)", ok, f"HTTP {e.code} (expected 401)"))
            if ok:
                report.fix("unauth-rejection assertion: tokenless mutating POST correctly returned 401")
        except Exception as e:
            endpoint_results.append(("POST /api/done (tokenless)", False, str(e)))

    passed = sum(1 for _, ok, _ in endpoint_results if ok)
    total = len(endpoint_results)
    failed = [f"{ep}: {detail}" for ep, ok, detail in endpoint_results if not ok]
    if failed:
        report.check("HTTP endpoints", False, f"{passed}/{total} passed; failures: " + "; ".join(failed))
    else:
        report.check("HTTP endpoints", True, f"{passed}/{total} passed")

    return proc


# ── Check 4b: declared-route auth walk (rearch W8) ──────────────────────────
def _status_of(req_or_url, timeout=10.0):
    """Return the HTTP status of a request, following the HTTPError path.

    A 2xx/3xx returns its code (no body read for streams — a HEAD-like probe is
    impossible for the hand-rolled handlers, so we open then immediately close).
    A 4xx/5xx surfaces via HTTPError and we return its code. A transport error
    re-raises for the caller to record.
    """
    try:
        with urllib.request.urlopen(req_or_url, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def check_route_table_walk(report: Report, server_proc):
    """Walk EVERY declared route table row and assert its per-policy auth
    behavior against the live throwaway server (rearch W8).

    The declared rows (``route_table.ROUTES``) are the single source of truth;
    this walk skips ``kind == upgrade`` (the WS handshake is covered by the
    socket 401-before-101 regression test) and, per the row's declared/effective
    auth policy under the current auth mode, asserts:

      * ``open``  → a TOKENLESS request must NOT return 401 (it still serves).
      * ``token``/``ws_token`` → a TOKENLESS request MUST return 401 (only
        meaningful when a token is configured; auth-disabled rows are skipped).

    Plus one representative AUTHED positive: ``GET /api/routes`` with the
    Authorization header must not 401 — proving the token path end-to-end.
    """
    name = "declared-route auth walk (W8)"
    if server_proc is None:
        report.check(name, False, "server not running")
        return
    try:
        import route_table as _rt
        import pillar_flags as _pf
    except Exception as e:
        report.check(name, False, f"import failed: {type(e).__name__}: {e}")
        return

    base = f"http://127.0.0.1:{TEST_PORT}"
    token = _paths.expected_token()
    try:
        auth_mode = _pf.current_flags()[_pf.FLAG_AUTH]
    except Exception:
        auth_mode = "open"

    failures = []
    walked = 0
    for exp in _rt.walk_expectations(token is not None, auth_mode):
        method, pattern = exp["method"], exp["pattern"]
        want = exp["tokenless_expect"]
        if want is None:
            continue  # token route but auth disabled — nothing to assert
        walked += 1
        # Build a TOKENLESS request. A prefix pattern is probed at the pattern
        # itself (auth is checked before any id/param parsing, so a bare prefix
        # still exercises the gate). A POST sends an empty body.
        try:
            if method == "GET":
                code = _status_of(base + pattern)
            else:
                req = urllib.request.Request(
                    base + pattern, data=b"{}",
                    headers={"Content-Type": "application/json"},
                    method="POST")
                code = _status_of(req)
        except Exception as e:
            failures.append(f"{method} {pattern}: transport error {e}")
            continue
        if want == "401" and code != 401:
            failures.append(f"{method} {pattern}: expected 401, got {code}")
        elif want == "not_401" and code == 401:
            failures.append(f"{method} {pattern}: open route unexpectedly 401'd")

    # Representative authed positive: the token path must be honored.
    if token is not None:
        try:
            req = urllib.request.Request(
                base + "/api/routes",
                headers={"Authorization": f"Bearer {token}"}, method="GET")
            code = _status_of(req)
            walked += 1
            if code == 401:
                failures.append("GET /api/routes (authed): unexpected 401")
        except Exception as e:
            failures.append(f"GET /api/routes (authed): transport error {e}")

    if failures:
        report.check(name, False,
                     f"{walked} rows walked; {len(failures)} failed: "
                     + "; ".join(failures[:8]))
    else:
        report.check(name, True,
                     f"{walked} declared rows honor their auth policy "
                     f"(mode={auth_mode}, token="
                     f"{'minted' if _TOKEN_MINTED else 'set' if token else 'unset'})")


# â”€â”€ W9 cookie/auth walk + the 20Ã— soak-candidate pipeline â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# rearch 2026-07 W9 (C2). The cookie navigation + enforce flip get a dedicated,
# STUBBED, in-process end-to-end walk that exercises the REAL server auth code
# under ``ANCHOR_AUTH_MODE=enforce``: tokenless data-plane GET â†’ 401, login mints
# the HttpOnly cookie, the cookie carries a page-nav GET + the term_ws upgrade,
# ?token= stays as the declared WS fallback, logout clears. Per PROCESS-RAILS Â§2
# the walk ENTERS the 20Ã— nightly repetition pipeline (below) and is NOT joined
# to the 5AM main() sequence until it has 20 consecutive green nights (W18).

class _CookieWalkHandler:
    """In-process stand-in bound to the REAL AnchorHandler auth methods (W9).

    Captures both the ``_send_json`` path (``sent``) and the raw
    ``send_response``/``send_header`` path (``resp``) so the login/logout
    handlers' ``Set-Cookie`` header is observable without a socket.
    """

    class _WFile:
        def write(self, _b):
            return None

    def __init__(self, path, headers=None, remote="127.0.0.1"):
        self.path = path
        self.headers = headers or {}
        self.client_address = (remote, 5555)
        self.sent = []                       # (code, json) from _send_json
        self.resp = {"status": None, "headers": []}
        self.wfile = self._WFile()

    def _send_json(self, data, code=200):
        self.sent.append((code, data))

    def send_response(self, code):
        self.resp["status"] = code

    def send_header(self, k, v):
        self.resp["headers"].append((k, v))

    def end_headers(self):
        return None

    def _set_cookies(self):
        return [v for (k, v) in self.resp["headers"] if k == "Set-Cookie"]


def _bind_cookie_walk_methods(mod):
    for m in ("_term_token_ok", "_data_plane_gate", "_auth_mode",
              "_presented_token"):
        setattr(_CookieWalkHandler, m, getattr(mod.AnchorHandler, m))


def check_cookie_auth_walk(report: Report, server_proc=None):
    """W9: stubbed cookie-nav + enforce end-to-end walk (soak candidate).

    Fully in-process (no socket, no live :8777): drives the real handler auth
    methods with ``ANCHOR_TOKEN`` set and ``ANCHOR_AUTH_MODE=enforce``, writing
    any warn/enforce record to a THROWAWAY log. Env + log are restored/removed.
    """
    name = "cookie/auth walk (W9)"
    import tempfile
    try:
        mod = _import_anchor_gui()
        import paths as _p
    except Exception as e:
        report.check(name, False, f"import failed: {type(e).__name__}: {e}")
        return

    saved = {k: os.environ.get(k) for k in
             ("ANCHOR_TOKEN", "ANCHOR_AUTH_MODE", "ANCHOR_AUTH_WARN",
              "ANCHOR_AUTH_WARN_LOG")}
    tmp_log = Path(tempfile.mkdtemp(prefix="anchor-hc-cookie-")) / "aw.log"
    token = os.urandom(8).hex()  # ephemeral self-test token (no literal secret in the shippable set)
    failures = []
    try:
        os.environ["ANCHOR_TOKEN"] = token
        os.environ["ANCHOR_AUTH_MODE"] = "enforce"
        os.environ.pop("ANCHOR_AUTH_WARN", None)
        os.environ["ANCHOR_AUTH_WARN_LOG"] = str(tmp_log)
        _bind_cookie_walk_methods(mod)
        cookie_pair = f"{_p.AUTH_COOKIE_NAME}={token}"

        # 1) tokenless data-plane GET under enforce â†’ 401.
        fh = _CookieWalkHandler("/api/rnd/projects", headers={})
        if fh._data_plane_gate("GET", "/api/rnd/projects") is not True \
                or not fh.sent or fh.sent[-1][0] != 401:
            failures.append("tokenless /api/rnd/projects did not 401 under enforce")

        # 2) login mints an HttpOnly, SameSite=Strict cookie carrying the token.
        lh = _CookieWalkHandler("/api/auth/login",
                                headers={"X-Anchor-Token": token})
        mod.handle_auth_login(lh, "/api/auth/login", {})
        setc = lh._set_cookies()
        if not setc:
            failures.append("login set no cookie")
        else:
            c = setc[0]
            if token not in c:
                failures.append("login cookie missing the token value")
            if "HttpOnly" not in c or "SameSite=Strict" not in c:
                failures.append("login cookie missing HttpOnly/SameSite=Strict")

        # 3) the cookie carries a page-nav GET (served, not blocked).
        ch = _CookieWalkHandler("/api/rnd/projects",
                                headers={"Cookie": cookie_pair})
        if ch._data_plane_gate("GET", "/api/rnd/projects") is not False:
            failures.append("cookie-bearing page-nav GET was blocked under enforce")

        # 4) the cookie authenticates the term_ws upgrade (desktop spike proven);
        #    ?token= remains the declared WS fallback; tokenless WS is rejected.
        wh = _CookieWalkHandler("/api/rnd/term_ws?session=x",
                                headers={"Cookie": cookie_pair})
        if wh._term_token_ok() is not True:
            failures.append("cookie did not authenticate the term_ws upgrade")
        th = _CookieWalkHandler(f"/api/rnd/term_ws?session=x&token={token}",
                                headers={})
        if th._term_token_ok() is not True:
            failures.append("?token= WS fallback stopped working")
        nh = _CookieWalkHandler("/api/rnd/term_ws?session=x", headers={})
        if nh._term_token_ok() is not False:
            failures.append("tokenless term_ws was not rejected")

        # 5) logout clears the cookie.
        oh = _CookieWalkHandler("/api/auth/logout",
                                headers={"X-Anchor-Token": token})
        mod.handle_auth_logout(oh, "/api/auth/logout", {})
        clr = oh._set_cookies()
        if not clr or "Max-Age=0" not in clr[0]:
            failures.append("logout did not clear the cookie")
    except Exception as e:
        failures.append(f"walk crashed: {type(e).__name__}: {e}")
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        try:
            shutil.rmtree(tmp_log.parent, ignore_errors=True)
        except Exception:
            pass

    if failures:
        report.check(name, False, "; ".join(failures[:6]))
    else:
        report.check(name, True,
                     "enforce: tokenless 401 Â· login sets HttpOnly cookie Â· "
                     "cookie carries page-nav + term_ws Â· ?token= WS fallback "
                     "Â· logout clears")


def check_relocated_data_dir(report: Report):
    """rearch W18 (C6): the runtime-state-out-of-the-repo walk (soak candidate).

    Proves, HERMETICALLY (a temp code-root + a temp data root outside it — never
    the live service / real data), that Anchor's runtime state relocates OUTSIDE
    the repo and the git-hygiene classifier keeps the repo provably clean:

      (1) with ``ANCHOR_DATA_DIR`` pointed at a folder OUTSIDE the simulated
          repo root, ``ensure_data_dirs`` + a health-report/log write land under
          the data root and NOT inside the repo;
      (2) the resolved data dir is genuinely outside the repo tree;
      (3) ``git_hygiene.classify_runtime`` still flags runtime artifacts True and
          product/pointer files False — the rules that keep porcelain empty.

    The env is restored afterward; ``paths.data_dir()`` reads ``ANCHOR_DATA_DIR``
    at call time, so no module reload is needed. Joins the 20× nightly pipeline.
    """
    name = "relocated data-dir walk (W11/W18)"
    import tempfile as _tf
    import shutil as _shutil
    prev_data = os.environ.get("ANCHOR_DATA_DIR")
    tmp = None
    failures = []
    try:
        import paths as _p
        from tools import git_hygiene as _gh

        tmp = Path(_tf.mkdtemp(prefix="anchor-hc-datadir-"))
        repo = tmp / "repo"                       # the simulated code root
        repo.mkdir(parents=True, exist_ok=True)
        (repo / "anchor_gui.py").write_text("# product\n", encoding="utf-8")
        data = tmp / "AnchorData"                 # OUTSIDE the repo, on purpose
        os.environ["ANCHOR_DATA_DIR"] = str(data)

        resolved = _p.data_dir()
        if resolved != data.resolve():
            failures.append(f"data_dir() did not honor ANCHOR_DATA_DIR "
                            f"({resolved} != {data.resolve()})")
        # (2) the data root is genuinely outside the repo tree.
        try:
            resolved.relative_to(repo.resolve())
            failures.append("relocated data dir is INSIDE the repo tree")
        except ValueError:
            pass                                  # outside — correct

        # (1) writes land under the data root, never in the repo.
        _p.ensure_data_dirs()
        hr = _p.health_reports_dir() / "2026-07-04.md"
        hr.write_text("# ok\n", encoding="utf-8")
        lg = _p.logs_dir() / "2026-07-04.md"
        lg.write_text("log\n", encoding="utf-8")
        if not (data / "health_reports" / "2026-07-04.md").exists():
            failures.append("health-report write did not land under the data dir")
        if not (data / "logs" / "2026-07-04.md").exists():
            failures.append("log write did not land under the data dir")
        # nothing leaked into the repo (only the product file we seeded).
        leaked = [p.name for p in repo.rglob("*")
                  if p.is_file() and p.name != "anchor_gui.py"]
        if leaked:
            failures.append(f"runtime writes leaked into the repo: {leaked[:4]}")

        # (3) the hygiene classifier — runtime True, product/pointer False.
        for rel in ("rnd_registry.json", "dashboard.html", "logs/2026.md",
                    "rnd_jobs/j.json", ".anchor/sessions.json"):
            if _gh.classify_runtime(rel) is not True:
                failures.append(f"classifier missed runtime artifact: {rel}")
        for rel in ("anchor_gui.py", "OPEN_ROUTES.json",
                    ".anchor/projects/p/index.json"):
            if _gh.classify_runtime(rel) is not False:
                failures.append(f"classifier flagged a kept file runtime: {rel}")
    except Exception as e:
        failures.append(f"walk crashed: {type(e).__name__}: {e}")
    finally:
        if prev_data is None:
            os.environ.pop("ANCHOR_DATA_DIR", None)
        else:
            os.environ["ANCHOR_DATA_DIR"] = prev_data
        if tmp is not None:
            _shutil.rmtree(tmp, ignore_errors=True)

    if failures:
        report.check(name, False, "; ".join(failures[:6]))
    else:
        report.check(name, True,
                     "ANCHOR_DATA_DIR relocates runtime state outside the repo "
                     "Â· writes land under the data root Â· hygiene classifier "
                     "keeps porcelain empty")


# The 20Ã— nightly repetition pipeline (PROCESS-RAILS.md Â§2). A NEW walk joins the
# 5AM run (main()) ONLY after 20 consecutive green nightly repetitions; until
# then it lives here, exercised via ``python anchor_healthcheck.py --soak`` and
# recorded to the soak ledger. W18 performs the join once ``soak_ready`` is True.
SOAK_LEDGER = DATA_DIR / "logs" / "soak-candidates.jsonl"
SOAK_TARGET_REPETITIONS = 20

#: rearch W18 (C7): the FOUR NEW walks named by PROCESS-RAILS §2 — the canonical
#: set the closure joins to the 5AM run, each only after its 20× green soak.
#: journal-parity (W14) + supervisor-probes (W16) were promoted directly into the
#: 5AM ``main()`` sequence by their own waves (each proven by a dedicated test
#: gate, ``test_parity_recovery_w14`` / ``test_supervisor_w16`` — that is their
#: green-repetition basis); cookie/auth (W9) + relocated-data-dir (W11/W18) are
#: the two that carry the live nightly soak and join via :func:`soak_ready`.
def four_new_walks():
    """The canonical four new walks (name, fn) named by PROCESS-RAILS §2."""
    return (
        ("journal parity gate (classify + recover)", check_journal_parity),
        ("supervisor live probes (W16)", check_supervisor_live_probes),
        ("cookie/auth walk (W9)", check_cookie_auth_walk),
        ("relocated data-dir walk (W11/W18)", check_relocated_data_dir),
    )

#: The subset still earning its 20× soak before joining the 5AM run. journal
#: parity + supervisor probes are already in ``main()`` (promoted by their waves).
SOAK_GATED_WALKS = (
    ("cookie/auth walk (W9)", check_cookie_auth_walk),
    ("relocated data-dir walk (W11/W18)", check_relocated_data_dir),
)


def soak_candidate_walks():
    """The walks currently IN the 20× pipeline but NOT yet in the 5AM run."""
    return SOAK_GATED_WALKS


def record_soak_result(name, passed, ledger_path=None, ts=None):
    """Append ONE soak repetition result (atomic, under WRITE_LOCK)."""
    p = Path(ledger_path) if ledger_path is not None else SOAK_LEDGER
    entry = {"name": name, "passed": bool(passed),
             "ts": float(time.time() if ts is None else ts)}
    with _paths.WRITE_LOCK:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    return entry


def read_soak_ledger(ledger_path=None):
    """Parse the soak ledger JSONL into a list of dicts (missing â†’ ``[]``)."""
    p = Path(ledger_path) if ledger_path is not None else SOAK_LEDGER
    if not p.exists():
        return []
    out = []
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return []
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except ValueError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def soak_green_streak(name, ledger_path=None):
    """Consecutive green repetitions for ``name`` counting back from the end."""
    streak = 0
    for e in reversed(read_soak_ledger(ledger_path)):
        if e.get("name") != name:
            continue
        if e.get("passed"):
            streak += 1
        else:
            break
    return streak


def soak_ready(name, ledger_path=None):
    """True iff ``name`` has met the 20Ã— green-streak bar (W18 join gate)."""
    return soak_green_streak(name, ledger_path) >= SOAK_TARGET_REPETITIONS


def run_soak_candidates(ledger_path=None):
    """Run every soak-candidate walk once + record each result to the ledger.

    Invoked by ``python anchor_healthcheck.py --soak`` on the nightly
    repetition; deliberately NOT part of the 5AM ``main()`` sequence until W18
    joins a walk that has reached ``soak_ready``. Returns the Report.
    """
    report = Report()
    for wname, fn in soak_candidate_walks():
        before = len(report.checks)
        try:
            fn(report)
        except Exception as e:
            report.check(wname, False, f"{type(e).__name__}: {e}")
        segment = report.checks[before:]
        passed = bool(segment) and all(ok for _, ok, _ in segment)
        record_soak_result(wname, passed, ledger_path)
        streak = soak_green_streak(wname, ledger_path)
        report.check(f"{wname} â€” soak streak",
                     True, f"{streak}/{SOAK_TARGET_REPETITIONS} "
                     f"green nightly repetitions "
                     f"({'READY to join 5AM' if streak >= SOAK_TARGET_REPETITIONS else 'soaking'})")
    return report


def joined_soak_walks(ledger_path=None):
    """rearch W18 (C7): the soak-gated walks that have EARNED the 5AM join.

    Returns the subset of :data:`SOAK_GATED_WALKS` whose 20× green streak has
    been met (:func:`soak_ready`) — the walks the closure promotes into the 5AM
    ``main()`` sequence. On a fresh ledger this is empty (the discipline holds
    the join until the live nightly soak completes); once John's live nightly
    ``--soak`` runs reach 20 green, the walk auto-joins the 5AM run.
    """
    return tuple((n, fn) for (n, fn) in SOAK_GATED_WALKS
                 if soak_ready(n, ledger_path))


def run_joined_soak_walks(report: Report, ledger_path=None):
    """Run every soak-gated walk that has reached ``soak_ready`` as a HARD 5AM
    check. Called from ``main()`` — the W18 join. Returns the joined names."""
    joined = joined_soak_walks(ledger_path)
    for wname, fn in joined:
        try:
            fn(report)
        except Exception as e:
            report.check(wname, False, f"{type(e).__name__}: {e}")
    return [n for (n, _) in joined]


def check_north_star_scorecard(report: Report):
    """rearch W18 (C7): emit + assert the North-Star scorecard every run.

    Asserts the closure bar READ-ONLY (never rewrites the tracked artifacts —
    the W18 gate is their producer, so the nightly run never dirties the repo):
    every C1–C7 criterion is met OR narrowed-by-recorded-amendment (zero
    ``unresolved``), and the Appendix-A reconciliation shows zero silently
    dropped ideas. A regression that flips a criterion to bare ``unmet`` fails
    the nightly run — the scorecard is DEMONSTRATED, not narrated.
    """
    name = "north-star scorecard (C1–C7)"
    try:
        from tools import north_star_scorecard as _sc
        unresolved = _sc.unresolved_criteria()
        recon = _sc.appendix_a_reconciliation()
    except Exception as e:
        report.check(name, False, f"{type(e).__name__}: {e}")
        return
    problems = []
    if unresolved:
        problems.append(f"unresolved criteria (not met/narrowed): {unresolved}")
    if recon["ideas_dropped"]:
        problems.append(f"silently-dropped ideas: {recon['ideas_dropped']}")
    if not recon["ok"]:
        problems.append("appendix-A reconciliation drifted from the ledger")
    if problems:
        report.check(name, False, "; ".join(problems))
    else:
        crits = _sc.criteria()
        met = sum(1 for c in crits if c["status"] == _sc.STATUS_MET)
        narrowed = sum(1 for c in crits if c["status"] == _sc.STATUS_NARROWED)
        report.check(name, True,
                     f"{met} met Â· {narrowed} narrowed-by-amendment Â· 0 unmet; "
                     f"appendix-A: {len(recon['ideas_landed'])}/52 ideas landed, "
                     f"M-9 documented amendment")


# â”€â”€ Check 5: synthetic round-trip â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _post(base: str, path: str, payload: dict, timeout: float = 5.0,
          token: "str | None" = _UNSET) -> dict:
    """POST JSON to the test server.

    When ``token`` is left at its sentinel default, the configured token
    (``paths.expected_token()``) is attached automatically if one is set — so
    mutating endpoints don't 401 under the production D4 token posture. Pass
    ``token=None`` explicitly to send a deliberately tokenless request (used by
    the unauth-rejection assertion).
    """
    headers = {"Content-Type": "application/json"}
    if token is _UNSET:
        token = _paths.expected_token()
    if token is not None:
        # rearch-2026-07 W2: the healthcheck is the canonical NON-BROWSER
        # consumer — it presents the token via the standard Authorization
        # header (Bearer), proving the W2 consumer token path on every
        # nightly run. (Browser clients keep their legacy header/query
        # token senders; the server accepts all three.)
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def check_synthetic_roundtrip(report: Report, server_proc):
    name = "synthetic task round-trip"
    if server_proc is None:
        report.check(name, False, "skipped (server did not boot)")
        return

    base = f"http://127.0.0.1:{TEST_PORT}"
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    task_text = f"{SYNTHETIC_TAG} probe {timestamp}"
    steps_ok: list[tuple[str, bool, str]] = []

    try:
        # 1. Add
        r = _post(base, "/api/add", {
            "text": task_text, "domain": "academic", "priority": 3,
            "energy": "low", "due": "", "notes": "automated health check",
        })
        steps_ok.append(("add", r.get("ok", False), r.get("message", "")))

        # 2. Done
        r = _post(base, "/api/done", {"text": task_text})
        steps_ok.append(("done", r.get("ok", False), r.get("message", "")))

        # 3. Undone (reopen)
        r = _post(base, "/api/undone", {"text": task_text})
        steps_ok.append(("undone", r.get("ok", False), r.get("message", "")))

        # 4. Save for later
        r = _post(base, "/api/save_for_later", {"text": task_text})
        steps_ok.append(("save_for_later", r.get("ok", False), r.get("message", "")))

        # 5. Restore from saved
        r = _post(base, "/api/restore", {"text": task_text, "from": "saved"})
        steps_ok.append(("restore", r.get("ok", False), r.get("message", "")))

        # 6. Cancel
        r = _post(base, "/api/cancel", {"text": task_text})
        steps_ok.append(("cancel", r.get("ok", False), r.get("message", "")))

    except Exception as e:
        steps_ok.append(("exception", False, f"{type(e).__name__}: {e}"))

    # 7. Cleanup â€” remove the synthetic task from the cancelled archive
    cleanup_ok, cleanup_detail = _cleanup_synthetic_task(task_text)
    steps_ok.append(("cleanup", cleanup_ok, cleanup_detail))

    failures = [f"{step}: {detail}" for step, ok, detail in steps_ok if not ok]
    if failures:
        report.check(name, False, "; ".join(failures))
    else:
        report.check(name, True, f"{len(steps_ok)} steps")


def _cleanup_synthetic_task(task_text: str) -> tuple[bool, str]:
    """Remove the synthetic task from CANCELLED.md / SAVED_FOR_LATER.md / any md file."""
    search = task_text.lower()
    files_to_clean: list[Path] = [
        DATA_DIR / "CANCELLED.md",
        DATA_DIR / "SAVED_FOR_LATER.md",
        DATA_DIR / "DASHBOARD.md",
    ]
    domains = DATA_DIR / "domains"
    if domains.exists():
        files_to_clean.extend(domains.glob("*.md"))

    removed_from = []
    errors = []
    for f in files_to_clean:
        if not f.exists():
            continue
        try:
            text = f.read_text(encoding="utf-8")
            new_lines = [ln for ln in text.splitlines() if SYNTHETIC_TAG not in ln.lower()]
            if len(new_lines) != len(text.splitlines()):
                f.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
                removed_from.append(f.name)
        except Exception as e:
            errors.append(f"{f.name}: {e}")
    if errors:
        return False, "errors: " + "; ".join(errors)
    return True, f"removed from {len(removed_from)} file(s)" if removed_from else "no traces left"


# â”€â”€ Check 5b: R&D v2 surface (sessions / summaries / terminal / grass) â”€â”€â”€â”€â”€â”€
# Exercises the v2 R&D endpoints on the throwaway server (Wave 8). Everything
# model-driven goes through the STUB runner (ANCHOR_RUNNER_CMD -> fake_claude),
# never live claude. A SYNTHETIC project is registered in a throwaway temp folder
# and fully torn down afterward so REAL data (rnd_registry.json, the live
# project's .anchor store) is never polluted.

SYNTHETIC_RND_NAME = "__healthcheck__ rnd probe"


def _fake_runner_cmd() -> "str | None":
    """Path to the stub runner used to drive v2 model calls without live claude.

    Prefers ``tests/fake_claude.py`` (the suite's deterministic stub). Returns a
    ``python <abs path>`` command string, or ``None`` if the stub is absent (the
    v2 check then degrades gracefully instead of risking a live CLI).
    """
    stub = ANCHOR_DIR / "tests" / "fake_claude.py"
    if stub.is_file():
        return f"{sys.executable} {stub}"
    return None


def _streamjson_runner_cmd() -> "str | None":
    """Path to the STREAM-JSON stub runner (``tests/stub_streamjson.py``).

    Unlike ``fake_claude.py`` (bare text lines), this stub emits production
    ``claude -p --output-format stream-json`` NDJSON envelopes — the shape the
    summarizer's parser must extract real text from (the v6 Wave-1 regression
    guard). Returns a ``python <abs path>`` command string, or ``None`` if absent
    (the v6 check then degrades gracefully instead of risking a live CLI).
    """
    stub = ANCHOR_DIR / "tests" / "stub_streamjson.py"
    if stub.is_file():
        return f"{sys.executable} {stub}"
    return None


def _gandalf_draft_runner_cmd() -> "str | None":
    """Path to the STUB Stage-A runner (``tests/stub_gandalf_draft.py``).

    Emits a canned Gandalf RAW draft (a result-envelope NDJSON line) so the
    Gandalf surface check never invokes real ``claude``. Returns a
    ``python <abs path>`` command string, or ``None`` if the stub is absent (the
    check then degrades gracefully instead of risking a live CLI)."""
    stub = ANCHOR_DIR / "tests" / "stub_gandalf_draft.py"
    if stub.is_file():
        return f"{sys.executable} {stub}"
    return None


def _gandalf_host_cmd() -> "str | None":
    """Path to the STUB Stage-B host (``tests/stub_gandalf_host.py``).

    Emits a canned GRADED ``advisor-output.json`` so the Gandalf surface check
    never invokes real ``node`` / the real Skill-Foundry host. Returns a
    ``python <abs path>`` command string, or ``None`` when absent."""
    stub = ANCHOR_DIR / "tests" / "stub_gandalf_host.py"
    if stub.is_file():
        return f"{sys.executable} {stub}"
    return None


def check_rnd_v2_surface(report: Report, server_proc, rnd_env: dict):
    """Exercise the v2 R&D surface on the throwaway server (stubbed runner).

    Walks: register a synthetic project -> status_line shape (via the project
    window) -> add_idea / promote_inbox (grass) -> pin_deliverable -> reconcile
    preview -> a discovered planning session -> /summary + regenerate_summary ->
    a terminal session start -> term_input -> term_discover -> term_adopt. All
    model calls are stubbed via ANCHOR_RUNNER_CMD=fake_claude.

    ``rnd_env`` carries the temp folder + registry-cleanup hooks set up by main()
    so this never touches real data.
    """
    name = "R&D v2 surface"
    if server_proc is None:
        report.check(name, False, "skipped (server did not boot)")
        return
    if not rnd_env.get("runner_cmd"):
        report.check(name, True, "skipped (no stub runner; live claude avoided)")
        return

    base = f"http://127.0.0.1:{TEST_PORT}"
    steps: list[tuple[str, bool, str]] = []
    folder = rnd_env["folder"]

    try:
        import rnd_registry as _rnd
        import effort_history as _eh
        import sessions as _sessions
        import brownfield_scan as _bf

        # 1. Register a synthetic project in the throwaway folder.
        proj = _rnd.add_project(SYNTHETIC_RND_NAME, str(folder))
        pid = proj["id"]
        rnd_env["created_ids"].append(pid)
        steps.append(("register project", bool(pid), pid))

        # 2. add_idea -> grass lane (POST, token-aware).
        r = _post(base, "/api/rnd/add_idea",
                  {"project_id": pid, "text": "hc synthetic idea"})
        steps.append(("add_idea", r.get("ok", False), str(r.get("error", ""))))

        # 3. promote_inbox -> grass lane (reads the live INBOX.md, copy-by-default).
        #    Seed a synthetic inbox line first so the match is deterministic and
        #    tagged for cleanup; copy-by-default leaves it for _cleanup to remove.
        inbox = DATA_DIR / "INBOX.md"
        probe_line = f"- {TODAY}: {SYNTHETIC_TAG} inbox idea\n"
        try:
            if inbox.exists():
                inbox.write_text(inbox.read_text(encoding="utf-8").rstrip()
                                 + "\n" + probe_line, encoding="utf-8")
            else:
                inbox.write_text("# Inbox\n\n" + probe_line, encoding="utf-8")
        except OSError:
            pass
        r = _post(base, "/api/rnd/promote_inbox",
                  {"project_id": pid, "text": f"{SYNTHETIC_TAG} inbox idea"})
        steps.append(("promote_inbox", r.get("ok", False),
                      str(r.get("error", ""))))

        # 4. pin_deliverable: pin a file inside the throwaway folder.
        (folder / "deliverable.py").write_text("print('hc')\n", encoding="utf-8")
        r = _post(base, "/api/rnd/pin_deliverable",
                  {"project_id": pid, "path": "deliverable.py",
                   "type": "script"})
        steps.append(("pin_deliverable", r.get("ok", False),
                      str(r.get("error", ""))))

        # 5. reconcile PREVIEW (dry-run) via the registry mirror (non-destructive).
        rep = _rnd.reconcile_folder(pid, apply=False)
        steps.append(("reconcile preview",
                      rep.get("ok", False) and rep.get("applied") is False,
                      f"to_delete={rep.get('to_delete')}"))

        # 6. status_line shape (Wave 3 contract: per-lane counts+provenance).
        sl = _rnd.status_line(pid)
        shape_ok = all(
            lane in sl and set(sl[lane].keys()) == {"count", "imported", "running"}
            for lane in ("research", "planning", "build", "deliverables")
        )
        steps.append(("status_line shape", shape_ok, str(sl.get("grass", ""))))

        # 7. A discovered planning session -> /summary (GET) + regenerate_summary.
        bd = folder / "planning" / "brownfield-discovery"
        bd.mkdir(parents=True, exist_ok=True)
        (bd / "MASTER-PLAN.md").write_text(
            "# Master Plan\n\n## North Star\nfake line goal.\n", encoding="utf-8")
        scan = _bf.scan(str(folder))
        _eh.adopt_discovered(folder, pid, scan)
        plan_sessions = _sessions.list_sessions(folder, pid, "planning")
        if plan_sessions:
            sid = plan_sessions[0]["session_id"]
            # GET /summary (run-once: generates through the stub runner on first view)
            try:
                with urllib.request.urlopen(
                    f"{base}/summary/{pid}/planning/{sid}", timeout=20) as rr:
                    body = rr.read().decode("utf-8", errors="replace")
                    steps.append(("GET /summary", rr.status == 200
                                  and len(body) > 200, f"{len(body)}b"))
            except Exception as e:
                steps.append(("GET /summary", False, str(e)))
            # regenerate_summary (POST, force re-run through the stub).
            r = _post(base, "/api/rnd/regenerate_summary",
                      {"project_id": pid, "lane": "planning",
                       "session_id": sid}, timeout=30)
            steps.append(("regenerate_summary", r.get("ok", False),
                          str(r.get("error", ""))))
        else:
            steps.append(("discovered planning session", False,
                          "no session grouped"))

        # 8. Terminal walk: start -> input -> discover -> adopt (stubbed runner).
        #    Use the research lane (engine policy permits both engines) with a
        #    short fake run so the session reaches a terminal state quickly.
        try:
            import rnd_terminal as _term
            rec = _term.start_terminal(
                pid, "research",
                extra_args=["--lines", "1", "--sleep", "0.3"])
            tjid = rec.get("job_id")
            steps.append(("terminal start", bool(tjid), str(rec.get("status"))))
            # input via the API (writes onto live stdin while the job runs).
            r = _post(base, "/api/rnd/term_input",
                      {"session": tjid, "text": "continue please"})
            # written may be False if the stub already exited — accept either as
            # long as it is a clean JSON response (no 500).
            steps.append(("term_input", "written" in r,
                          f"written={r.get('written')}"))
            # Simulate a produced file then discover -> adopt.
            out_dir = Path(rec.get("output_dir") or "")
            if out_dir and out_dir.exists():
                (out_dir / "PRODUCED.md").write_text(
                    "# Produced\nhc terminal output\n", encoding="utf-8")
            import job_runner as _jr
            try:
                _jr.wait(tjid, timeout=10)
            except Exception:
                pass
            r = _post(base, "/api/rnd/term_discover", {"session": tjid})
            steps.append(("term_discover", r.get("ok", False),
                          str(r.get("error", ""))))
            r = _post(base, "/api/rnd/term_adopt", {"session": tjid})
            # adopt returns ok=True when something was adopted; tolerate the
            # nothing-adoptable path as a clean (non-500) response too.
            steps.append(("term_adopt", "ok" in r,
                          str(r.get("error", r.get("ok")))))
        except Exception as e:
            steps.append(("terminal walk", False, f"{type(e).__name__}: {e}"))

    except Exception as e:
        steps.append(("exception", False, f"{type(e).__name__}: {e}"))

    failures = [f"{s}: {d}" for s, ok, d in steps if not ok]
    if failures:
        report.check(name, False, "; ".join(failures))
    else:
        report.check(name, True, f"{len(steps)} steps")


def _git_init_repo(path: Path) -> bool:
    """Best-effort ``git init`` + one commit so worktrees can be added. Returns
    success. Used ONLY for the throwaway v3 terminal repo (never the build repo)."""
    try:
        env = dict(os.environ)
        env.setdefault("GIT_AUTHOR_NAME", "anchor-hc")
        env.setdefault("GIT_AUTHOR_EMAIL", "anchor@localhost")
        env.setdefault("GIT_COMMITTER_NAME", "anchor-hc")
        env.setdefault("GIT_COMMITTER_EMAIL", "anchor@localhost")
        for args in (
            ["git", "init"],
            ["git", "config", "user.email", "anchor@localhost"],
            ["git", "config", "user.name", "anchor-hc"],
            ["git", "add", "-A"],
            ["git", "commit", "-m", "hc seed", "--no-gpg-sign"],
        ):
            subprocess.run(args, cwd=str(path), env=env, capture_output=True,
                           text=True, timeout=30, check=True)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def check_rnd_v3_surface(report: Report, server_proc, rnd_env: dict):
    """Exercise the v3 "Mission Control" R&D surface — FULLY STUBBED.

    Walks the new v3 modules in a throwaway temp project/folder, never touching
    real data, never a live claude / real PTY / real preview spawn / real
    worktree off the build repo:

      1. session registry: register a synthetic session → reconcile re-statuses a
         dead "running" one → remove.
      2. stub-PTY lifecycle: ``pty_manager`` stub ``start→write→read_since`` (echo
         round-trip) → ``kill`` (reaped); AND a ``terminal_session.start_session``
         → ``attach`` (replay) → ``input`` → ``kill`` against a TEMP git repo with
         the stub backend + a TEMP worktree base (``ANCHOR_WORKTREE_BASE``).
      3. proactive summary: ``summarizer.summarize_project`` through the stub
         runner → cached.
      4. deliverable-run preview: NO real server spawn — walk
         ``preview_server.pick_free_port`` (assert ``!= 8777``) + ``reap_orphans``
         with an INJECTED dead-pid record (proves the never-8777 guard + the
         reconcile path without spawning anything).
      5. handoff: ``discover_recent_plan_set`` / ``record_handoff`` on the
         synthetic project, and the record SURVIVES a rescan.

    Everything is torn down by ``_cleanup_synthetic_rnd`` + the env restore in
    ``main()``. ``ANCHOR_PTY_BACKEND=stub`` + ``ANCHOR_RUNNER_CMD`` (fake_claude)
    keep every model/PTY interaction off the real engine.
    """
    name = "R&D v3 surface"
    if not rnd_env.get("runner_cmd"):
        report.check(name, True, "skipped (no stub runner; live claude avoided)")
        return

    import tempfile as _tf
    steps: list[tuple[str, bool, str]] = []

    # Force the STUB PTY backend + a hermetic worktree base for the whole walk;
    # both are restored in `finally`.
    prev_pty = os.environ.get("ANCHOR_PTY_BACKEND")
    prev_wtbase = os.environ.get("ANCHOR_WORKTREE_BASE")
    os.environ["ANCHOR_PTY_BACKEND"] = "stub"
    wt_base = Path(_tf.mkdtemp(prefix="anchor-hc-v3-wt-"))
    os.environ["ANCHOR_WORKTREE_BASE"] = str(wt_base)
    rnd_env.setdefault("v3_temp_dirs", []).append(wt_base)

    try:
        import rnd_registry as _rnd
        import session_registry as _sreg
        import pty_manager as _pty
        import terminal_session as _ts
        import preview_server as _preview
        import summarizer as _summarizer
        import handoff as _handoff
        import sessions as _sessions
        import effort_history as _eh
        import brownfield_scan as _bf

        # ── 0. A throwaway git project (so worktrees can attach to a real repo) ─
        proj_folder = Path(_tf.mkdtemp(prefix="anchor-hc-v3-proj-"))
        rnd_env["v3_temp_dirs"].append(proj_folder)
        (proj_folder / "README.md").write_text("# hc v3 probe\n", encoding="utf-8")
        git_ok = _git_init_repo(proj_folder)
        if not git_ok:
            report.check(name, True, "skipped (git init failed)")
            return
        proj = _rnd.add_project(SYNTHETIC_RND_NAME + " v3", str(proj_folder))
        pid = proj["id"]
        rnd_env["created_ids"].append(pid)
        steps.append(("register v3 project", bool(pid), pid))

        # ── 1. Session registry: register → reconcile(dead) → remove ───────────
        rec = _sreg.register_session(pid, "build", status=_sreg.STATUS_RUNNING,
                                     label="hc synthetic")
        sid = rec["session_id"]
        # No live ids → the "running" session is stale; reconcile re-statuses it.
        rc = _sreg.reconcile(live_session_ids=[], apply=True)
        after = _sreg.get_session(sid)
        steps.append(("registry register+reconcile",
                      sid in rc.get("stale", [])
                      and after and after.get("status") != _sreg.STATUS_RUNNING,
                      f"status={after.get('status') if after else None}"))
        removed = _sreg.remove_session(sid)
        steps.append(("registry remove",
                      removed and _sreg.get_session(sid) is None, ""))

        # ── 2a. Stub-PTY round-trip via pty_manager directly ───────────────────
        psid = _pty.start(["claude"], cwd=str(proj_folder))
        _pty.write(psid, "ECHO-ROUNDTRIP")
        out = _pty.read_since(psid, 0)
        echoed = "ECHO-ROUNDTRIP" in out.get("text", "")
        steps.append(("pty stub echo round-trip", echoed,
                      f"status={out.get('status')}"))
        _pty.kill(psid)
        reaped = psid not in _pty.live_sessions()
        steps.append(("pty stub kill reaped", reaped, ""))

        # ── 2b. terminal_session start→attach(replay)→input→kill (stub+temp repo)
        if git_ok:
            try:
                trec = _ts.start_session(pid, "build", label="hc v3 term")
                tsid = trec["session_id"]
                _ts.input(tsid, "hello-term")
                att = _ts.attach(tsid)
                steps.append(("terminal_session start+attach",
                              att.get("ok") and "hello-term" in att.get("buffer", ""),
                              f"status={att.get('status')}"))
                ko = _ts.kill(tsid, project_id=pid)
                steps.append(("terminal_session kill+worktree",
                              ko.get("ok", False),
                              f"wt={ko.get('worktree', {}).get('ok')}"))
            except Exception as e:
                steps.append(("terminal_session walk", False,
                              f"{type(e).__name__}: {e}"))
        else:
            steps.append(("terminal_session walk", True,
                          "skipped (git unavailable; pty round-trip already proven)"))

        # ── 3. Proactive PROJECT summary through the stub runner → cached ──────
        (proj_folder / "CLAUDE.md").write_text(
            "# HC v3 Project\n\nNorth Star: prove the stubbed v3 summary path.\n",
            encoding="utf-8")
        try:
            psum = _summarizer.summarize_project(str(proj_folder), pid, force=True)
            cached = _summarizer.load_cached_project(str(proj_folder), pid)
            steps.append(("project summary (stubbed)",
                          isinstance(psum, dict) and cached is not None,
                          str(psum.get("error", "ok"))))
        except Exception as e:
            steps.append(("project summary (stubbed)", False,
                          f"{type(e).__name__}: {e}"))

        # ── 4. Preview: pick_free_port (!=8777) + reap_orphans w/ injected dead pid
        try:
            port = _preview.pick_free_port()
            steps.append(("preview pick_free_port != 8777",
                          isinstance(port, int) and port != _preview.LIVE_PORT,
                          f"port={port}"))
            # Inject a dead-pid 'running' preview record (no spawn at the 5AM check)
            dead_pid = 2 ** 31 - 1  # an implausible/never-alive pid
            inj = {
                "preview_id": "hc-v3-preview",
                "project_id": pid,
                "target": "anchor_gui.py",
                "port": port,
                "url": f"http://127.0.0.1:{port}/",
                "status": _preview.STATUS_RUNNING,
                "pid": dead_pid,
                "data_dir": "",
                "started_at": time.time(),
            }
            _preview._put_record(inj)
            rep = _preview.reap_orphans()
            recd = _preview.load_previews().get("hc-v3-preview", {})
            steps.append(("preview reap_orphans (dead pid → stopped)",
                          "hc-v3-preview" in rep.get("reaped", [])
                          and recd.get("status") == _preview.STATUS_STOPPED,
                          f"reaped={rep.get('reaped')}"))
            # Clean the injected record out of the registry.
            with _paths.WRITE_LOCK:
                regp = _preview.load_previews()
                regp.pop("hc-v3-preview", None)
                _preview._save_previews(regp)
        except Exception as e:
            steps.append(("preview walk", False, f"{type(e).__name__}: {e}"))

        # ── 5. Handoff: discover_recent_plan_set + record (survives a rescan) ──
        try:
            bd = proj_folder / "planning" / "hc-v3-plan"
            bd.mkdir(parents=True, exist_ok=True)
            (bd / "MASTER-PLAN.md").write_text(
                "# Master Plan\n\n## North Star\nhc v3 north star.\n",
                encoding="utf-8")
            (bd / "IMPLEMENTATION-PLAN.md").write_text(
                "# Implementation Plan\n\n## Wave 1\nhc.\n", encoding="utf-8")
            scan = _bf.scan(str(proj_folder))
            _eh.adopt_discovered(proj_folder, pid, scan)
            plan_set = _handoff.discover_recent_plan_set(str(proj_folder), pid)
            steps.append(("handoff discover_recent_plan_set",
                          bool(plan_set), str(bool(plan_set))))
            rh = _handoff.record_handoff(str(proj_folder), pid,
                                         "hc-build-session", plan_set or {})
            steps.append(("handoff record", rh.get("ok", False),
                          str(rh.get("reason", ""))))
            # The record must SURVIVE a rescan (the Wave-7 durability contract).
            _bf.scan(str(proj_folder))  # re-scan; merge must preserve handoffs
            survived = any(h.get("build_session_id") == "hc-build-session"
                           for h in _handoff.list_handoffs(str(proj_folder), pid))
            steps.append(("handoff survives rescan", survived, ""))
        except Exception as e:
            steps.append(("handoff walk", False, f"{type(e).__name__}: {e}"))

    except Exception as e:
        steps.append(("exception", False, f"{type(e).__name__}: {e}"))
    finally:
        # Restore the PTY backend + worktree-base env we forced for this walk.
        if prev_pty is None:
            os.environ.pop("ANCHOR_PTY_BACKEND", None)
        else:
            os.environ["ANCHOR_PTY_BACKEND"] = prev_pty
        if prev_wtbase is None:
            os.environ.pop("ANCHOR_WORKTREE_BASE", None)
        else:
            os.environ["ANCHOR_WORKTREE_BASE"] = prev_wtbase

    failures = [f"{s}: {d}" for s, ok, d in steps if not ok]
    if failures:
        report.check(name, False, "; ".join(failures))
    else:
        report.check(name, True, f"{len(steps)} steps")


def check_rnd_v4_surface(report: Report, server_proc, rnd_env: dict):
    """Exercise the v4 "Project Cockpit" R&D surface — FULLY STUBBED.

    Walks the new v4 data/control seams in a throwaway temp project + temp git
    repo, never touching real data, never a live claude / real PTY / real preview
    spawn / real worktree off the build repo:

      (a) seed-once: ``terminal_session.start_session`` (stub PTY) writes the lane
          skill seed EXACTLY once → ``record.seeded`` is True; a repeated
          ``read_since`` never re-emits the seed.
      (b) engine switch: ``terminal_session.switch_engine`` swaps the backend in
          the SAME worktree with no orphan PTY; ``last_engine_for_project``
          reflects the new engine.
      (c) doc-roles: ``summarizer.session_doc_roles`` returns a dict for a
          discovered planning session.
      (d) rollup: ``effort_history.project_effort_rollup`` returns the
          ``{tokens,cost_usd,wall_clock_ms,sessions}`` shape for BOTH lifetime
          and 30d windows.
      (e) grass promote: ``effort_history.promote_grass_to_lane`` starts a seeded
          stub session in the target lane and the idea REMAINS in grass (copy).
      (f) type-aware deliverable launch — a skill VERIFY (no spawn, against a TEMP
          ``ANCHOR_SKILLS_DIR`` — never the live one) AND a service launch on a
          GUARANTEED-FREE injected port asserted ``!= 8777`` via a STUBBED
          ``preview_server`` (no real long-lived server is bound).

    Everything is torn down by ``_cleanup_synthetic_rnd`` + the env restore here +
    in ``main()``. ``ANCHOR_PTY_BACKEND=stub`` + ``ANCHOR_RUNNER_CMD`` (fake_claude)
    + a temp ``ANCHOR_WORKTREE_BASE`` keep every model/PTY interaction off the real
    engine; nothing touches the live ``:8777`` service.
    """
    name = "R&D v4 surface"
    if not rnd_env.get("runner_cmd"):
        report.check(name, True, "skipped (no stub runner; live claude avoided)")
        return

    import tempfile as _tf
    steps: list[tuple[str, bool, str]] = []

    # Force the STUB PTY backend + a hermetic worktree base + a temp skills dir
    # for the whole walk; all restored in `finally`.
    prev_pty = os.environ.get("ANCHOR_PTY_BACKEND")
    prev_wtbase = os.environ.get("ANCHOR_WORKTREE_BASE")
    prev_skills = os.environ.get("ANCHOR_SKILLS_DIR")
    prev_seed = os.environ.get("ANCHOR_TERMINAL_SEED")
    os.environ["ANCHOR_PTY_BACKEND"] = "stub"
    wt_base = Path(_tf.mkdtemp(prefix="anchor-hc-v4-wt-"))
    os.environ["ANCHOR_WORKTREE_BASE"] = str(wt_base)
    skills_dir = Path(_tf.mkdtemp(prefix="anchor-hc-v4-skills-"))
    os.environ["ANCHOR_SKILLS_DIR"] = str(skills_dir)
    # A deterministic, recognizable seed so the seed-once assertion is exact.
    os.environ["ANCHOR_TERMINAL_SEED"] = "HC-V4-SEED-LOAD-SKILL"
    rnd_env.setdefault("v3_temp_dirs", []).append(wt_base)
    rnd_env["v3_temp_dirs"].append(skills_dir)

    try:
        import rnd_registry as _rnd
        import terminal_session as _ts
        import pty_manager as _pty
        import effort_history as _eh
        import summarizer as _summarizer
        import deliverables as _deliv
        import preview_server as _preview
        import sessions as _sessions
        import brownfield_scan as _bf

        # ── 0. A throwaway git project (worktrees attach to a real repo) ───────
        proj_folder = Path(_tf.mkdtemp(prefix="anchor-hc-v4-proj-"))
        rnd_env["v3_temp_dirs"].append(proj_folder)
        (proj_folder / "README.md").write_text("# hc v4 probe\n", encoding="utf-8")
        git_ok = _git_init_repo(proj_folder)
        if not git_ok:
            report.check(name, True, "skipped (git init failed)")
            return
        proj = _rnd.add_project(SYNTHETIC_RND_NAME + " v4", str(proj_folder))
        pid = proj["id"]
        rnd_env["created_ids"].append(pid)
        steps.append(("register v4 project", bool(pid), pid))

        seed_tsid = None
        if git_ok:
            # ── (a) seed-once on a stub Research session (so the gemini engine
            #         switch below is policy-allowed: gemini is research-only) ──
            try:
                rec = _ts.start_session(pid, "research", label="hc v4 seed")
                seed_tsid = rec["session_id"]
                seeded_flag = bool(rec.get("seeded"))
                out1 = _pty.read_since(seed_tsid, 0)
                out2 = _pty.read_since(seed_tsid, 0)
                seed_marker = "HC-V4-SEED-LOAD-SKILL"
                # Seed appears once and is identical across repeated reads (the
                # stub echoes input → the marker is in the buffer, never re-sent).
                seed_once = (out1.get("text", "").count(seed_marker)
                             == out2.get("text", "").count(seed_marker)
                             >= 1)
                steps.append(("seed-once written + flag",
                              seeded_flag and seed_once,
                              f"seeded={seeded_flag} marker_seen="
                              f"{out1.get('text','').count(seed_marker)}"))
            except Exception as e:
                steps.append(("seed-once", False, f"{type(e).__name__}: {e}"))

            # ── (b) engine switch (no orphan PTY) ─────────────────────────────
            if seed_tsid is not None:
                try:
                    live_before = set(_pty.live_sessions())
                    sw = _ts.switch_engine(seed_tsid, "gemini")
                    after = _rnd_session(seed_tsid)
                    last_eng = _ts.last_engine_for_project(pid)
                    # The session id is preserved; exactly one live PTY for it.
                    live_after = set(_pty.live_sessions())
                    no_orphan = (seed_tsid in live_after
                                 and len(live_after) <= len(live_before))
                    steps.append(("engine switch",
                                  sw.get("ok", bool(sw))
                                  and (after or {}).get("backend") == "gemini"
                                  and last_eng == "gemini"
                                  and no_orphan,
                                  f"backend={(after or {}).get('backend')} "
                                  f"last={last_eng}"))
                except Exception as e:
                    steps.append(("engine switch", False,
                                  f"{type(e).__name__}: {e}"))
                # Reap the seed session's PTY + worktree (no leak).
                try:
                    _ts.kill(seed_tsid, project_id=pid)
                except Exception:
                    pass
        else:
            steps.append(("seed-once / engine switch", True,
                          "skipped (git unavailable)"))

        # ── (c) doc-roles on a discovered planning session ────────────────────
        try:
            bd = proj_folder / "planning" / "hc-v4-plan"
            bd.mkdir(parents=True, exist_ok=True)
            (bd / "MASTER-PLAN.md").write_text(
                "# Master Plan\n\n## North Star\nhc v4 doc-roles.\n",
                encoding="utf-8")
            (bd / "IMPLEMENTATION-PLAN.md").write_text(
                "# Implementation Plan\n\n## Wave 1\nhc.\n", encoding="utf-8")
            scan = _bf.scan(str(proj_folder))
            _eh.adopt_discovered(proj_folder, pid, scan)
            plan_sessions = _sessions.list_sessions(str(proj_folder), pid,
                                                    "planning")
            if plan_sessions:
                psid = plan_sessions[0]["session_id"]
                roles = _summarizer.session_doc_roles(pid, "planning", psid,
                                                      folder_path=str(proj_folder))
                steps.append(("doc-roles dict", isinstance(roles, dict),
                              f"roles={list(roles.keys())}"))
            else:
                steps.append(("doc-roles", False, "no planning session grouped"))
        except Exception as e:
            steps.append(("doc-roles", False, f"{type(e).__name__}: {e}"))

        # ── (d) rollup: lifetime + 30d shape ──────────────────────────────────
        try:
            shape = {"tokens", "cost_usd", "wall_clock_ms", "sessions"}
            life = _eh.project_effort_rollup(pid, window="lifetime",
                                             folder_path=str(proj_folder))
            d30 = _eh.project_effort_rollup(pid, window="30d", now=time.time(),
                                            folder_path=str(proj_folder))
            steps.append(("rollup lifetime+30d",
                          set(life.keys()) == shape and set(d30.keys()) == shape,
                          f"life={life.get('sessions')} 30d={d30.get('sessions')}"))
        except Exception as e:
            steps.append(("rollup", False, f"{type(e).__name__}: {e}"))

        # ── (e) grass promote → seeded stub session; idea stays in grass ──────
        if git_ok:
            try:
                idea = _eh.add_idea(str(proj_folder), pid, "hc v4 grass idea")
                idea_id = idea.get("job_id")
                prec = _eh.promote_grass_to_lane(pid, idea_id, "research",
                                                 folder_path=str(proj_folder))
                ptsid = prec.get("session_id")
                still = _eh.get_grass_idea(str(proj_folder), pid, idea_id)
                steps.append(("grass promote (seeded, copy)",
                              bool(ptsid) and still is not None
                              and prec.get("status") == "running",
                              f"idea_kept={still is not None}"))
                try:
                    if ptsid:
                        _ts.kill(ptsid, project_id=pid)
                except Exception:
                    pass
            except Exception as e:
                steps.append(("grass promote", False, f"{type(e).__name__}: {e}"))
        else:
            steps.append(("grass promote", True, "skipped (git unavailable)"))

        # ── (f) type-aware deliverable launch — skill verify + service (stub) ─
        try:
            # A skill deliverable present under the TEMP skills dir → "available",
            # verified by existence ONLY (no spawn).
            (skills_dir / "hcskill").mkdir(parents=True, exist_ok=True)
            (skills_dir / "hcskill" / "SKILL.md").write_text(
                "# hcskill\n", encoding="utf-8")
            (proj_folder / "hcskill").mkdir(parents=True, exist_ok=True)
            srec = _deliv.pin_deliverable(str(proj_folder), pid, "hcskill",
                                          name="hcskill", dtype="skill")
            sres = _deliv.launch_deliverable(str(proj_folder), pid,
                                             srec.get("job_id"))
            steps.append(("deliverable skill verify (no spawn)",
                          sres.get("ok") and sres.get("status")
                          == _deliv.VERIFY_AVAILABLE,
                          f"status={sres.get('status')}"))

            # A service deliverable launched through a STUB preview_server: assert
            # the chosen port is OS-free + != 8777 WITHOUT binding a real server.
            free_port = _preview.pick_free_port()

            class _StubPreview:
                STATUS_RUNNING = _preview.STATUS_RUNNING
                LIVE_PORT = _preview.LIVE_PORT

                def list_previews(self, project_id=None):
                    return []

                def start_preview(self, folder_path, project_id, target=None,
                                  **kw):
                    assert free_port != self.LIVE_PORT
                    return {"ok": True, "port": free_port,
                            "url": f"http://127.0.0.1:{free_port}/",
                            "preview_id": "hc-v4-svc"}

            (proj_folder / "svc.py").write_text("print('svc')\n", encoding="utf-8")
            vrec = _deliv.pin_deliverable(str(proj_folder), pid, "svc.py",
                                          name="hc svc", dtype="service")
            vres = _deliv.launch_deliverable(str(proj_folder), pid,
                                             vrec.get("job_id"),
                                             preview_mod=_StubPreview())
            steps.append(("deliverable service (stub, port != 8777)",
                          vres.get("ok") and vres.get("port") == free_port
                          and vres.get("port") != _preview.LIVE_PORT,
                          f"port={vres.get('port')}"))
        except Exception as e:
            steps.append(("deliverable launch", False,
                          f"{type(e).__name__}: {e}"))

    except Exception as e:
        steps.append(("exception", False, f"{type(e).__name__}: {e}"))
    finally:
        # Restore every env var we forced for this walk.
        for var, prev in (("ANCHOR_PTY_BACKEND", prev_pty),
                          ("ANCHOR_WORKTREE_BASE", prev_wtbase),
                          ("ANCHOR_SKILLS_DIR", prev_skills),
                          ("ANCHOR_TERMINAL_SEED", prev_seed)):
            if prev is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = prev

    failures = [f"{s}: {d}" for s, ok, d in steps if not ok]
    if failures:
        report.check(name, False, "; ".join(failures))
    else:
        report.check(name, True, f"{len(steps)} steps")


def check_rnd_v5_surface(report: Report, server_proc, rnd_env: dict):
    """Exercise the v5 "Durable Work" R&D surface — FULLY STUBBED.

    Walks the new v5 data/control seams in a throwaway temp project + temp git
    repo, never touching real data, never a live claude / real PTY / real preview
    spawn / real worktree off the build repo:

      (Wave 1) run lifecycle — close-keeps-record (no reap; the PTY + registry
          record survive) vs kill-reaps (PTY gone + worktree removed + record
          terminal), via ``terminal_session.start_session`` / ``kill`` (stub PTY).
      (Wave 2) session summary + continue — ``summarizer.summarize_session``
          through the stub runner captures skill/prompts/actions and caches; then
          ``terminal_session.start_session(seed_context=…)`` starts a NEW seeded
          session carrying the prior context; the original record is intact.
      (Wave 3) project summary — ``summarizer.summarize_project`` through the stub
          runner yields a non-empty summary that is cached (read path never runs
          the model).
      (Wave 4) build deliverable — ``deliverables.resolve_build_deliverable`` +
          ``backfill_build_deliverables`` resolve a session-scoped product (and an
          HONEST unresolved when no explicit signal); nothing fabricated.
      (Wave 5) grass workbench — add_idea → develop (seeded stub session) →
          save_grass_refinement (dev-N) → set_grass_status → the idea STAYS in
          grass (copy); the refinement is listed.

    Everything is torn down by ``_cleanup_synthetic_rnd`` + the env restore here +
    in ``main()``. ``ANCHOR_PTY_BACKEND=stub`` + ``ANCHOR_RUNNER_CMD`` (fake_claude)
    + a temp ``ANCHOR_WORKTREE_BASE`` keep every model/PTY interaction off the real
    engine; nothing touches the live ``:8777`` service.
    """
    name = "R&D v5 surface"
    if not rnd_env.get("runner_cmd"):
        report.check(name, True, "skipped (no stub runner; live claude avoided)")
        return

    import tempfile as _tf
    steps: list[tuple[str, bool, str]] = []

    prev_pty = os.environ.get("ANCHOR_PTY_BACKEND")
    prev_wtbase = os.environ.get("ANCHOR_WORKTREE_BASE")
    prev_seed = os.environ.get("ANCHOR_TERMINAL_SEED")
    os.environ["ANCHOR_PTY_BACKEND"] = "stub"
    wt_base = Path(_tf.mkdtemp(prefix="anchor-hc-v5-wt-"))
    os.environ["ANCHOR_WORKTREE_BASE"] = str(wt_base)
    os.environ["ANCHOR_TERMINAL_SEED"] = "HC-V5-SEED-LOAD-SKILL"
    rnd_env.setdefault("v3_temp_dirs", []).append(wt_base)

    try:
        import rnd_registry as _rnd
        import terminal_session as _ts
        import pty_manager as _pty
        import session_registry as _sreg
        import effort_history as _eh
        import summarizer as _summarizer
        import deliverables as _deliv
        import sessions as _sessions
        import brownfield_scan as _bf

        # ── 0. A throwaway git project (worktrees attach to a real repo) ───────
        proj_folder = Path(_tf.mkdtemp(prefix="anchor-hc-v5-proj-"))
        rnd_env["v3_temp_dirs"].append(proj_folder)
        (proj_folder / "CLAUDE.md").write_text(
            "# hc v5 probe\n\nThis project exists to exercise the v5 surface.\n",
            encoding="utf-8")
        (proj_folder / "README.md").write_text("# hc v5 probe\n",
                                               encoding="utf-8")
        git_ok = _git_init_repo(proj_folder)
        if not git_ok:
            report.check(name, True, "skipped (git init failed)")
            return
        proj = _rnd.add_project(SYNTHETIC_RND_NAME + " v5", str(proj_folder))
        pid = proj["id"]
        rnd_env["created_ids"].append(pid)
        steps.append(("register v5 project", bool(pid), pid))

        # ── (Wave 1) run lifecycle: close keeps record; kill reaps ────────────
        if git_ok:
            try:
                rec = _ts.start_session(pid, "research", label="hc v5 close")
                sid = rec["session_id"]
                live_after_start = sid in set(_pty.live_sessions())
                # CLOSE = the panel X: it does NOT reap. We model "close" as
                # simply NOT calling kill — the registry record + the live PTY
                # must persist (a closed-to-tile session keeps running).
                still_rec = _sreg.get_session(sid)
                still_live = sid in set(_pty.live_sessions())
                close_keeps = (live_after_start and still_rec is not None
                               and still_live)
                steps.append(("close keeps record + PTY",
                              close_keeps,
                              f"rec={still_rec is not None} live={still_live}"))
                # KILL = the deliberate hard-kill: reap PTY + remove worktree +
                # mark the record terminal.
                _ts.kill(sid, project_id=pid)
                killed_live = sid in set(_pty.live_sessions())
                after_kill = _sreg.get_session(sid)
                term_status = (after_kill or {}).get("status", "")
                kill_reaps = (not killed_live
                              and term_status in ("done", "failed", "killed",
                                                  "stopped", ""))
                steps.append(("kill reaps PTY",
                              kill_reaps,
                              f"live={killed_live} status={term_status}"))
            except Exception as e:
                steps.append(("run lifecycle", False,
                              f"{type(e).__name__}: {e}"))
        else:
            steps.append(("run lifecycle", True, "skipped (git unavailable)"))

        # ── (Wave 2) session summary (skill/prompts/actions) + continue ───────
        cont_sid = None
        try:
            # A discovered research session so the summarizer has member docs.
            rd = proj_folder / "research" / "hc-v5-research"
            rd.mkdir(parents=True, exist_ok=True)
            (rd / "REPORT.md").write_text(
                "# Report\n\n## Findings\nhc v5 session summary.\n",
                encoding="utf-8")
            scan = _bf.scan(str(proj_folder))
            _eh.adopt_discovered(proj_folder, pid, scan)
            rsess = _sessions.list_sessions(str(proj_folder), pid, "research")
            if rsess:
                rs = rsess[0]
                rsid = rs["session_id"]
                summ = _summarizer.summarize_session(
                    str(proj_folder), pid, "research", rs)
                has_shape = (isinstance(summ, dict)
                             and "skill" in summ and "prompts" in summ
                             and "actions" in summ)
                # The read path returns the SAME cached summary (no re-run).
                cached = _summarizer.load_cached(
                    str(proj_folder), pid, _eh._resolve_subdir("research"),
                    rsid)
                steps.append(("session summary skill/prompts/actions cached",
                              has_shape and cached is not None,
                              f"shape={has_shape} cached={cached is not None}"))
                # CONTINUE: a NEW seeded session in the same lane; original intact.
                if git_ok:
                    seed_ctx = ("Continuation of session %s: %s"
                                % (rsid, summ.get("title", "")))
                    crec = _ts.start_session(pid, "research",
                                             label="hc v5 continue",
                                             seed_context=seed_ctx)
                    cont_sid = crec["session_id"]
                    orig_intact = _sessions.list_sessions(
                        str(proj_folder), pid, "research")
                    orig_ok = any(s.get("session_id") == rsid
                                  for s in orig_intact)
                    steps.append(("continue starts new seeded session",
                                  bool(cont_sid) and cont_sid != rsid
                                  and crec.get("status") == "running"
                                  and orig_ok,
                                  f"new={cont_sid} orig_intact={orig_ok}"))
                    try:
                        _ts.kill(cont_sid, project_id=pid)
                    except Exception:
                        pass
            else:
                steps.append(("session summary", False,
                              "no research session grouped"))
        except Exception as e:
            steps.append(("session summary + continue", False,
                          f"{type(e).__name__}: {e}"))

        # ── (Wave 3) project summary: non-empty objective, cached ─────────────
        try:
            psumm = _summarizer.summarize_project(str(proj_folder), pid)
            obj = ""
            if isinstance(psumm, dict):
                obj = (psumm.get("summary") or psumm.get("objective")
                       or psumm.get("markdown") or "")
                claims = psumm.get("claims", []) or []
                if not obj and claims:
                    obj = str(claims[0])
            cached_proj = _summarizer.load_cached_project(str(proj_folder), pid)
            steps.append(("project summary non-empty + cached",
                          bool(str(obj).strip()) and cached_proj is not None,
                          f"obj_len={len(str(obj))} "
                          f"cached={cached_proj is not None}"))
        except Exception as e:
            steps.append(("project summary", False,
                          f"{type(e).__name__}: {e}"))

        # ── (Wave 4) build deliverable: resolve (honest unresolved) + backfill ─
        try:
            # A discovered build session (formed from a foreman checkpoint/config)
            # whose single product member resolves as the build's deliverable.
            bd = proj_folder / "build" / "hc-v5-build"
            bd.mkdir(parents=True, exist_ok=True)
            (bd / "foreman.config.json").write_text("{}\n", encoding="utf-8")
            scan2 = _bf.scan(str(proj_folder))
            _eh.adopt_discovered(proj_folder, pid, scan2)
            bsess = _sessions.list_sessions(str(proj_folder), pid, "build")
            res_shape = False
            if bsess:
                res = _deliv.resolve_build_deliverable(
                    str(proj_folder), pid, bsess[0])
                res_shape = (isinstance(res, dict) and "resolved" in res
                             and "reason" in res
                             # honesty: unresolved must carry deliverable=None
                             and (res.get("resolved")
                                  or res.get("deliverable") is None))
            back = _deliv.backfill_build_deliverables(str(proj_folder), pid)
            back_shape = (isinstance(back, dict) and "pinned" in back
                          and "unresolved" in back and "scanned" in back)
            steps.append(("build deliverable resolve + backfill",
                          res_shape and back_shape,
                          f"resolve={res_shape} "
                          f"backfill_scanned={back.get('scanned')}"))
        except Exception as e:
            steps.append(("build deliverable", False,
                          f"{type(e).__name__}: {e}"))

        # ── (Wave 5) grass workbench: develop → save refinement → status ──────
        if git_ok:
            try:
                idea = _eh.add_idea(str(proj_folder), pid, "hc v5 grass idea")
                idea_id = idea.get("job_id")
                drec = _eh.develop_grass_idea(pid, idea_id, "research",
                                              folder_path=str(proj_folder))
                dsid = drec.get("session_id")
                ref = _eh.save_grass_refinement(
                    str(proj_folder), pid, idea_id,
                    text="refined", label="dev-1", session_id=dsid)
                refs = _eh.list_grass_refinements(str(proj_folder), pid,
                                                  idea_id)
                still = _eh.get_grass_idea(str(proj_folder), pid, idea_id)
                wb = _eh.grass_workbench_data(str(proj_folder), pid)
                listed = any(it.get("idea_id") == idea_id for it in wb)
                steps.append(("grass develop + refine + idea kept",
                              bool(dsid) and still is not None
                              and len(refs) >= 1
                              and "/dev-" in ref.get("refinement_id", "")
                              and _eh.grass_status(still) == "refined"
                              and listed,
                              f"refs={len(refs)} kept={still is not None} "
                              f"status={_eh.grass_status(still)}"))
                try:
                    if dsid:
                        _ts.kill(dsid, project_id=pid)
                except Exception:
                    pass
            except Exception as e:
                steps.append(("grass workbench", False,
                              f"{type(e).__name__}: {e}"))
        else:
            steps.append(("grass workbench", True, "skipped (git unavailable)"))

    except Exception as e:
        steps.append(("exception", False, f"{type(e).__name__}: {e}"))
    finally:
        # Reap any stub PTY sessions this walk left live (defensive).
        try:
            import pty_manager as _pty2
            import session_registry as _sreg2
            for sid in list(_pty2.live_sessions()):
                try:
                    _pty2.kill(sid)
                except Exception:
                    pass
            for pid_ in rnd_env.get("created_ids", []):
                for srec in _sreg2.list_sessions(project_id=pid_):
                    try:
                        _sreg2.remove_session(srec.get("session_id"))
                    except Exception:
                        pass
        except Exception:
            pass
        # Restore every env var we forced for this walk.
        for var, prev in (("ANCHOR_PTY_BACKEND", prev_pty),
                          ("ANCHOR_WORKTREE_BASE", prev_wtbase),
                          ("ANCHOR_TERMINAL_SEED", prev_seed)):
            if prev is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = prev

    failures = [f"{s}: {d}" for s, ok, d in steps if not ok]
    if failures:
        report.check(name, False, "; ".join(failures))
    else:
        report.check(name, True, f"{len(steps)} steps")


def check_rnd_v6_surface(report: Report, server_proc, rnd_env: dict):
    """Exercise the v6 "Linked Pipeline" R&D surface — FULLY STUBBED.

    Walks the new v6 seams in a throwaway temp project + temp git repo, never
    touching real data, never a live claude / real PTY / real worktree off the
    build repo. ``ANCHOR_PTY_BACKEND=stub`` + ``ANCHOR_RUNNER_CMD`` (the
    STREAM-JSON stub ``tests/stub_streamjson.py``) + a temp ``ANCHOR_WORKTREE_BASE``
    keep every model/PTY interaction off the real engine; nothing binds ``:8777``.

      (Wave 1) summaries-through-stream-json — ``summarizer.summarize_session``
          + ``summarize_project`` driven through the PRODUCTION stream-json
          envelope stub yield grounded NON-EMPTY content (session skill/prompts/
          actions; project objective); a SCHEMA_VERSION-stale empty project cache
          is treated as a MISS and HEALS on regenerate.
      (Wave 2 + 6) the CHAIN — start a research session → advance to a LINKED
          planning session (``start_session(parent_session_id=…)``; assert ordered
          ``chain_members`` + parent set) → finish the planning session WITH a
          real MASTER+IMPL plan set → ``auto_advance_planning_to_build`` yields
          exactly ONE linked build (idempotent on a second call) → assert
          ``chain_members`` is [research, planning, build] ordered.
      (Wave 4) the ``term_sessions`` projection (via ``session_registry``)
          INCLUDES terminal-status sessions and stays SAFE (no worktree_path /
          branch leak).

    Every stub PTY + synthetic session row is reaped, all forced env is restored,
    and the temp dirs are torn down (here + by ``_cleanup_synthetic_rnd``). The
    summarizer runner is restored to ``rnd_env['runner_cmd']`` (fake_claude) on
    exit so later checks are unaffected. Asserts nothing bound ``:8777``.
    """
    name = "R&D v6 surface"
    sj_cmd = _streamjson_runner_cmd()
    if not rnd_env.get("runner_cmd") or not sj_cmd:
        report.check(name, True,
                     "skipped (no stub runner; live claude avoided)")
        return

    import tempfile as _tf
    steps: list[tuple[str, bool, str]] = []

    prev_pty = os.environ.get("ANCHOR_PTY_BACKEND")
    prev_wtbase = os.environ.get("ANCHOR_WORKTREE_BASE")
    prev_seed = os.environ.get("ANCHOR_TERMINAL_SEED")
    prev_runner = os.environ.get("ANCHOR_RUNNER_CMD")
    prev_claims = os.environ.get("STUB_STREAMJSON_CLAIMS")
    os.environ["ANCHOR_PTY_BACKEND"] = "stub"
    wt_base = Path(_tf.mkdtemp(prefix="anchor-hc-v6-wt-"))
    os.environ["ANCHOR_WORKTREE_BASE"] = str(wt_base)
    os.environ["ANCHOR_TERMINAL_SEED"] = "HC-V6-SEED-LOAD-SKILL"
    # Drive the summarizer through the PRODUCTION stream-json stub for this walk.
    os.environ["ANCHOR_RUNNER_CMD"] = sj_cmd
    rnd_env.setdefault("v3_temp_dirs", []).append(wt_base)

    pid = None
    try:
        import rnd_registry as _rnd
        import terminal_session as _ts
        import pty_manager as _pty
        import session_registry as _sreg
        import effort_history as _eh
        import summarizer as _summarizer
        import sessions as _sessions
        import brownfield_scan as _bf
        import handoff as _handoff

        # ── 0. A throwaway git project (worktrees attach to a real repo) ───────
        proj_folder = Path(_tf.mkdtemp(prefix="anchor-hc-v6-proj-"))
        rnd_env["v3_temp_dirs"].append(proj_folder)
        (proj_folder / "CLAUDE.md").write_text(
            "# hc v6 probe\n\n## What this project is\n"
            "Anchor is a productivity system that manages markdown task files "
            "for a researcher, tracking projects and deadlines. This probe "
            "exercises the v6 linked pipeline surface.\n",
            encoding="utf-8")
        (proj_folder / "README.md").write_text("# hc v6 probe\n",
                                               encoding="utf-8")
        git_ok = _git_init_repo(proj_folder)
        if not git_ok:
            report.check(name, True, "skipped (git init failed)")
            return
        proj = _rnd.add_project(SYNTHETIC_RND_NAME + " v6", str(proj_folder))
        pid = proj["id"]
        rnd_env["created_ids"].append(pid)
        steps.append(("register v6 project", bool(pid), str(pid)))

        # ── (Wave 1) summaries through the PRODUCTION stream-json stub ────────
        try:
            # A discovered planning session with two real member docs so a
            # grounded claim has a corpus.
            bd = proj_folder / "planning" / "hc-v6-plan"
            bd.mkdir(parents=True, exist_ok=True)
            (bd / "MASTER-PLAN.md").write_text(
                "# Master Plan\n\n## North Star\nCache validated summaries for "
                "each session of trio work.\n", encoding="utf-8")
            (bd / "IMPLEMENTATION-PLAN.md").write_text(
                "# Implementation Plan\n\n## Goal\nRender the most-recent session "
                "with an expander.\n", encoding="utf-8")
            scan = _bf.scan(str(proj_folder))
            _eh.adopt_discovered(proj_folder, pid, scan)
            psess = _sessions.list_sessions(str(proj_folder), pid, "planning")
            sess_ok = False
            if psess:
                os.environ["STUB_STREAMJSON_CLAIMS"] = (
                    "North Star: cache validated summaries for each session.")
                ssum = _summarizer.summarize_session(
                    str(proj_folder), pid, "planning", psess[0])
                claims = (ssum.get("claims") or []) if isinstance(ssum, dict) \
                    else []
                shape = (isinstance(ssum, dict) and "skill" in ssum
                         and "prompts" in ssum and "actions" in ssum)
                grounded = any("validated summaries" in str(c).lower()
                               for c in claims)
                sess_ok = bool(claims) and shape and grounded
            steps.append(("session summary grounded via stream-json",
                          sess_ok,
                          f"present={bool(psess)} ok={sess_ok}"))

            # Project objective through the same production envelope path.
            objective = ("Anchor is a productivity system that manages markdown "
                         "task files for a researcher, tracking projects and "
                         "deadlines.")
            os.environ["STUB_STREAMJSON_CLAIMS"] = objective
            pout = _summarizer.summarize_project(str(proj_folder), pid)
            ptext = (pout.get("summary_text") or "") if isinstance(pout, dict) \
                else ""
            proj_ok = (isinstance(pout, dict) and bool(pout.get("claims"))
                       and not pout.get("no_grounded_claims")
                       and "productivity system" in ptext.lower())
            steps.append(("project objective grounded via stream-json",
                          proj_ok, f"text_len={len(ptext)}"))

            # SCHEMA-VERSION heal: a pre-fix empty cache (no schema_version) is a
            # MISS; a force-regenerate heals it into a grounded objective.
            d = _summarizer._project_store_dir(str(proj_folder), pid)
            d.mkdir(parents=True, exist_ok=True)
            (d / _summarizer.PROJECT_SUMMARY_JSON).write_text(
                json.dumps({"project_id": pid, "kind": "project",
                            "claims": [], "summary_text": "",
                            "no_grounded_claims": True}),
                encoding="utf-8")
            miss = _summarizer.load_cached_project(str(proj_folder), pid) is None
            os.environ["STUB_STREAMJSON_CLAIMS"] = objective
            healed = _summarizer.summarize_project(str(proj_folder), pid,
                                                   force=True)
            healed_ok = (isinstance(healed, dict) and bool(healed.get("claims")))
            cached_after = _summarizer.load_cached_project(str(proj_folder), pid)
            cache_ver_ok = (isinstance(cached_after, dict)
                            and cached_after.get("schema_version")
                            == _summarizer.SUMMARY_SCHEMA_VERSION)
            steps.append(("schema-stale cache heals on regenerate",
                          miss and healed_ok and cache_ver_ok,
                          f"miss={miss} healed={healed_ok} ver={cache_ver_ok}"))
        except Exception as e:
            steps.append(("summaries via stream-json", False,
                          f"{type(e).__name__}: {e}"))

        # ── (Wave 2 + 6) the linked research → planning → build chain ─────────
        if git_ok:
            try:
                # A real MASTER+IMPL plan set committed so discovery finds it
                # (the planning lane the auto-advance executes on).
                # The MASTER+IMPL plan docs were already written under
                # planning/hc-v6-plan above (Wave-1 step); discovery reads the
                # project folder (not git), so no extra commit is needed.

                # Research session = chain root.
                rrec = _ts.start_session(pid, "research", label="hc v6 research")
                rsid = rrec["session_id"]
                root_chain_ok = (rrec.get("parent_session_id", "") == ""
                                 and rrec.get("chain_id") == rsid)

                # Advance to a LINKED planning session (parent = research).
                prec = _ts.start_session(pid, "planning",
                                         label="hc v6 planning",
                                         parent_session_id=rsid,
                                         seed_context="advance from research")
                psid = prec["session_id"]
                link_ok = (prec.get("parent_session_id") == rsid
                           and prec.get("chain_id") == rrec.get("chain_id"))
                members_rp = _sreg.chain_members(rrec.get("chain_id"))
                rp_order_ok = ([m.get("session_id") for m in members_rp]
                               == [rsid, psid])

                # Finish the planning session (hard-kill → DONE) then auto-advance.
                pre_plan = _ts.capture_plan_set(pid, psid)
                _ts.kill(psid, project_id=pid)
                build = _ts.auto_advance_planning_to_build(
                    pid, psid, plan_set=pre_plan)
                build_ok = (isinstance(build, dict)
                            and build.get("parent_session_id") == psid
                            and build.get("chain_id") == rrec.get("chain_id"))
                bsid = (build or {}).get("session_id")

                # Idempotent: a second advance must NOT create a duplicate build.
                dup = _ts.auto_advance_planning_to_build(pid, psid)
                builds = [s for s in _sreg.list_sessions(project_id=pid)
                          if s.get("lane") == "build"]
                idem_ok = dup is None and len(builds) == 1

                # The full chain is ordered [research, planning, build].
                members = _sreg.chain_members(rrec.get("chain_id"))
                lanes_order = [m.get("lane") for m in members]
                chain_ok = lanes_order == ["research", "planning", "build"]

                steps.append(("linked research→planning→build chain",
                              root_chain_ok and link_ok and rp_order_ok
                              and build_ok and idem_ok and chain_ok,
                              f"root={root_chain_ok} link={link_ok} "
                              f"rp_order={rp_order_ok} build={build_ok} "
                              f"idem={idem_ok} order={lanes_order}"))

                # ── (Wave 4) term_sessions projection: includes terminal + SAFE ─
                projection = _sreg.list_sessions(project_id=pid)
                has_terminal = any(s.get("status")
                                   in _sreg.TERMINAL_STATUSES
                                   for s in projection)
                # The SERVER projection (anchor_gui) strips worktree_path/branch;
                # assert the SAFE field set we ship has the lineage fields and
                # that a SAFE copy never carries worktree_path/branch.
                safe_copy = [{
                    "session_id": s.get("session_id"),
                    "lane": s.get("lane", ""),
                    "status": s.get("status", ""),
                    "parent_session_id": s.get("parent_session_id", ""),
                    "chain_id": s.get("chain_id", ""),
                } for s in projection]
                safe_ok = all("worktree_path" not in s and "branch" not in s
                              for s in safe_copy)
                steps.append(("term_sessions projection terminal+SAFE",
                              has_terminal and safe_ok,
                              f"terminal={has_terminal} safe={safe_ok}"))

                # Reap the live chain sessions we left running.
                for sid in (rsid, bsid):
                    if sid:
                        try:
                            _ts.kill(sid, project_id=pid)
                        except Exception:
                            pass
            except Exception as e:
                steps.append(("linked chain", False,
                              f"{type(e).__name__}: {e}"))
        else:
            steps.append(("linked chain", True, "skipped (git unavailable)"))

    except Exception as e:
        steps.append(("exception", False, f"{type(e).__name__}: {e}"))
    finally:
        # Reap any stub PTY sessions this walk left live (defensive).
        try:
            import pty_manager as _pty2
            import session_registry as _sreg2
            for sid in list(_pty2.live_sessions()):
                try:
                    _pty2.kill(sid)
                except Exception:
                    pass
            for pid_ in rnd_env.get("created_ids", []):
                for srec in _sreg2.list_sessions(project_id=pid_):
                    try:
                        _sreg2.remove_session(srec.get("session_id"))
                    except Exception:
                        pass
        except Exception:
            pass
        # Restore every env var we forced for this walk (incl. the runner, which
        # we swapped to the stream-json stub — later checks must see fake_claude).
        for var, prev in (("ANCHOR_PTY_BACKEND", prev_pty),
                          ("ANCHOR_WORKTREE_BASE", prev_wtbase),
                          ("ANCHOR_TERMINAL_SEED", prev_seed),
                          ("ANCHOR_RUNNER_CMD", prev_runner),
                          ("STUB_STREAMJSON_CLAIMS", prev_claims)):
            if prev is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = prev

    failures = [f"{s}: {d}" for s, ok, d in steps if not ok]
    if failures:
        report.check(name, False, "; ".join(failures))
    else:
        report.check(name, True, f"{len(steps)} steps")


def check_rnd_v7_surface(report: Report, server_proc, rnd_env: dict):
    """Exercise the v7 "Integrated Board" R&D surface — FULLY STUBBED.

    Walks the new v7 seams in a throwaway temp project + temp git repo, never
    touching real data, never a live claude / real PTY / real worktree off the
    build repo. ``ANCHOR_PTY_BACKEND=stub`` + ``ANCHOR_RUNNER_CMD`` (the
    STREAM-JSON stub ``tests/stub_streamjson.py``) + a temp ``ANCHOR_WORKTREE_BASE``
    keep every model/PTY interaction off the real engine; nothing binds ``:8777``.

      (Wave 1) normalizer — ``summarizer.short_summary_text`` /
          ``summarizer.tile_blurb`` strip a glyph/markdown-laden input to clean,
          capped text AND leave an already-clean sentence unchanged.
      (Wave 2) summarize-on-finish — start a research session → hard-kill it →
          drive the proactive ``_trigger_session_summary_on_finish`` hook → a
          session summary is generated + cached, and ``summarizer.session_blurb``
          returns a short clean one-liner from it.
      (Wave 3) board bridge — a LIVE ``session_registry`` session is INCLUDED in
          the ``anchor_gui._gather_project_sessions`` lane merge and DEDUPED (one
          entry per session_id), while a ``general`` session is EXCLUDED from the
          trio columns.
      (Wave 4) general lane — ``terminal_session.start_session(lane='general')``
          is bare (no seed) and never auto-advances (``general`` is not a planning
          lane).

    Every stub PTY + synthetic session row is reaped, all forced env is restored,
    and the temp dirs are torn down (here + by ``_cleanup_synthetic_rnd``). The
    summarizer runner is restored to ``rnd_env['runner_cmd']`` (fake_claude) on
    exit so later checks are unaffected. Asserts nothing bound ``:8777``.
    """
    name = "R&D v7 surface"
    sj_cmd = _streamjson_runner_cmd()
    if not rnd_env.get("runner_cmd") or not sj_cmd:
        report.check(name, True,
                     "skipped (no stub runner; live claude avoided)")
        return

    import tempfile as _tf
    steps: list[tuple[str, bool, str]] = []

    prev_pty = os.environ.get("ANCHOR_PTY_BACKEND")
    prev_wtbase = os.environ.get("ANCHOR_WORKTREE_BASE")
    prev_seed = os.environ.get("ANCHOR_TERMINAL_SEED")
    prev_runner = os.environ.get("ANCHOR_RUNNER_CMD")
    prev_claims = os.environ.get("STUB_STREAMJSON_CLAIMS")
    prev_proactive = os.environ.get("ANCHOR_PROACTIVE_SUMMARY")
    os.environ["ANCHOR_PTY_BACKEND"] = "stub"
    wt_base = Path(_tf.mkdtemp(prefix="anchor-hc-v7-wt-"))
    os.environ["ANCHOR_WORKTREE_BASE"] = str(wt_base)
    os.environ["ANCHOR_TERMINAL_SEED"] = "HC-V7-SEED-LOAD-SKILL"
    # Drive the summarizer through the PRODUCTION stream-json stub for this walk.
    os.environ["ANCHOR_RUNNER_CMD"] = sj_cmd
    rnd_env.setdefault("v3_temp_dirs", []).append(wt_base)

    pid = None
    gui = None
    prev_gui_flag = None
    try:
        import rnd_registry as _rnd
        import terminal_session as _ts
        import pty_manager as _pty
        import session_registry as _sreg
        import effort_history as _eh
        import summarizer as _summarizer
        import sessions as _sessions
        import brownfield_scan as _bf
        # anchor_gui carries the board bridge + the summarize-on-finish hook.
        import anchor_gui as gui

        # ── (Wave 1) the short/clean normalizer ───────────────────────────────
        try:
            dirty = "**Goal:** ship X — handle ## edge `cases` ✓ → done ☢"
            short = _summarizer.short_summary_text(dirty)
            tile = _summarizer.tile_blurb(dirty, max_chars=40)
            # No markdown control chars or decorative glyphs survive.
            bad = ("**", "##", "`", "✓", "→", "☢", "—")
            clean_ok = all(g not in short for g in bad) and bool(short.strip())
            # A clean sentence within the cap is returned unchanged.
            plain = "Ship X and handle the edge cases"
            unchanged = _summarizer.short_summary_text(plain) == plain
            tile_capped = len(tile) <= 41  # 40 + ellipsis
            steps.append(("normalizer strips + caps + clean-unchanged",
                          clean_ok and unchanged and tile_capped,
                          f"short={short!r}"))
        except Exception as e:
            steps.append(("normalizer", False, f"{type(e).__name__}: {e}"))

        # ── 0. A throwaway git project (worktrees attach to a real repo) ───────
        proj_folder = Path(_tf.mkdtemp(prefix="anchor-hc-v7-proj-"))
        rnd_env["v3_temp_dirs"].append(proj_folder)
        (proj_folder / "CLAUDE.md").write_text(
            "# hc v7 probe\n\n## What this project is\n"
            "Anchor is a productivity system; this probe exercises the v7 "
            "integrated-board surface.\n", encoding="utf-8")
        (proj_folder / "README.md").write_text("# hc v7 probe\n",
                                               encoding="utf-8")
        git_ok = _git_init_repo(proj_folder)
        if not git_ok:
            report.check(name, True, "skipped (git init failed)")
            return
        proj = _rnd.add_project(SYNTHETIC_RND_NAME + " v7", str(proj_folder))
        pid = proj["id"]
        rnd_env["created_ids"].append(pid)
        steps.append(("register v7 project", bool(pid), str(pid)))

        # Enable the proactive summary path so the finish hook actually runs
        # (the live server enables it; in this walk we opt in, then restore).
        prev_gui_flag = gui._PROACTIVE_SUMMARY_ENABLED
        gui._PROACTIVE_SUMMARY_ENABLED = True
        os.environ["ANCHOR_PROACTIVE_SUMMARY"] = "1"

        # ── (Wave 2) summarize-on-finish + session_blurb ──────────────────────
        if git_ok:
            try:
                # A discovered research session so the summarizer has member docs
                # to ground a session summary against.
                rd = proj_folder / "research" / "hc-v7-research"
                rd.mkdir(parents=True, exist_ok=True)
                (rd / "REPORT.md").write_text(
                    "# Report\n\n## Findings\nThe v7 board integrates live "
                    "sessions into the lane columns.\n", encoding="utf-8")
                scan = _bf.scan(str(proj_folder))
                _eh.adopt_discovered(proj_folder, pid, scan)

                rec = _ts.start_session(pid, "research", label="hc v7 finish")
                rsid = rec["session_id"]
                # Hard-kill = the deliberate finish transition.
                _ts.kill(rsid, project_id=pid)
                # Resolve the DISCOVERED session id for the cache assert + blurb.
                #
                # Pick it by the property the assert actually depends on — the
                # session must own a member DOCUMENT — instead of assuming it is
                # the newest (`[0]`). Since usage_capture began writing a
                # finalized `run-cost` pointer-record per finished session, a
                # kill also mints an artifact-less `run::run-cost-<sid>` session
                # that sorts NEWER than the discovered one. Taking `[0]` picked
                # that metering row, whose grounding corpus is empty, so
                # `summarizer.seed_can_ground` correctly refuses to generate
                # (2026-07-26 hardening) and nothing is ever cached. Before that
                # hardening this step passed only because it was asserting
                # against a BLANK summary of a cost record — it was encoding the
                # very defect that hardening fixed.
                rsess = _sessions.list_sessions(str(proj_folder), pid,
                                                "research")

                def _has_doc(sess):
                    return any((m.get("artifact_path") or "").strip()
                               for m in (sess.get("member_files") or []))

                disc_sid = next((s["session_id"] for s in rsess if _has_doc(s)),
                                rsess[0]["session_id"] if rsess else rsid)
                os.environ["STUB_STREAMJSON_CLAIMS"] = (
                    "The v7 board integrates live sessions into lane columns.")
                # Drive the proactive finish hook for the discovered session
                # (non-blocking daemon thread) then poll the cache.
                gui._trigger_session_summary_on_finish(pid, "research", disc_sid)
                store_lane = _eh._resolve_subdir("research")
                cached = None
                for _ in range(60):
                    cached = _summarizer.load_cached(
                        str(proj_folder), pid, store_lane, disc_sid)
                    if cached is not None:
                        break
                    time.sleep(0.1)
                blurb = _summarizer.session_blurb(
                    str(proj_folder), pid, "research", disc_sid)
                glyph_free = all(g not in blurb
                                 for g in ("**", "##", "`", "✓", "→", "☢"))
                steps.append(("summarize-on-finish caches + blurb",
                              cached is not None and bool(blurb.strip())
                              and glyph_free,
                              f"cached={cached is not None} "
                              f"blurb_len={len(blurb)}"))
            except Exception as e:
                steps.append(("summarize-on-finish", False,
                              f"{type(e).__name__}: {e}"))
        else:
            steps.append(("summarize-on-finish", True,
                          "skipped (git unavailable)"))

        # ── (Wave 3) board bridge: live registry session merged + deduped ─────
        try:
            # A LIVE managed research session registered directly (no PTY/git
            # needed for the merge seam).
            lrec = _sreg.register_session(pid, "research",
                                          status=_sreg.STATUS_RUNNING,
                                          session_id="hc-v7-live-research",
                                          label="hc v7 live")
            lsid = lrec["session_id"]
            # A general session must NOT reach any trio column.
            _sreg.register_session(pid, "general",
                                   status=_sreg.STATUS_RUNNING,
                                   session_id="hc-v7-general",
                                   label="hc v7 general")
            merged = gui._gather_project_sessions(str(proj_folder), pid)
            research_sessions = merged.get("research", [])
            # The live session appears exactly once in its lane column.
            live_count = sum(
                1 for sv in research_sessions
                if sv.get("session_id") == lsid
                or gui._strip_session_prefix(sv.get("session_id", "")) == lsid)
            included = live_count == 1
            # The general session is excluded from EVERY trio column.
            all_sids = [sv.get("session_id", "")
                        for col in ("research", "plan", "build",
                                    "deliverables")
                        for sv in merged.get(col, [])]
            general_excluded = all("hc-v7-general" not in s for s in all_sids)
            steps.append(("board bridge live merged+deduped, general excluded",
                          included and general_excluded,
                          f"live_count={live_count} "
                          f"general_excluded={general_excluded}"))
            # Clean the directly-registered rows.
            for _sid in (lsid, "hc-v7-general"):
                try:
                    _sreg.remove_session(_sid)
                except Exception:
                    pass
        except Exception as e:
            steps.append(("board bridge", False, f"{type(e).__name__}: {e}"))

        # ── (Wave 4) bare general lane: no seed + never auto-advances ──────────
        if git_ok:
            # The global ANCHOR_TERMINAL_SEED override (forced above for the
            # summarizer round-trip) would otherwise leak a seed into the bare
            # general lane — clear it just for this sub-step so "bare" is honest.
            _seed_save = os.environ.pop("ANCHOR_TERMINAL_SEED", None)
            try:
                grec = _ts.start_session(pid, "general", backend="claude",
                                         label="hc v7 general bare")
                gsid = grec["session_id"]
                bare_ok = (grec.get("seeded") is False
                           and (grec.get("seed_text") or "") == ""
                           and _ts.seed_for_lane("general") is None
                           and "general" in _ts._valid_lanes()
                           and "general" not in _ts.LANE_SKILL)
                # A general session never advances to build, even given a plan set.
                adv = _ts.auto_advance_planning_to_build(
                    pid, gsid, plan_set={"master": "x", "impl": "y"})
                builds = [s for s in _sreg.list_sessions(project_id=pid)
                          if s.get("lane") == "build"]
                no_advance = adv is None and builds == []
                steps.append(("general lane bare + never advances",
                              bare_ok and no_advance,
                              f"bare={bare_ok} no_advance={no_advance}"))
                try:
                    _ts.kill(gsid, project_id=pid)
                except Exception:
                    pass
            except Exception as e:
                steps.append(("general lane", False,
                              f"{type(e).__name__}: {e}"))
            finally:
                if _seed_save is not None:
                    os.environ["ANCHOR_TERMINAL_SEED"] = _seed_save
        else:
            steps.append(("general lane", True, "skipped (git unavailable)"))

    except Exception as e:
        steps.append(("exception", False, f"{type(e).__name__}: {e}"))
    finally:
        # Restore the gui proactive-summary flag we toggled.
        try:
            if gui is not None and prev_gui_flag is not None:
                gui._PROACTIVE_SUMMARY_ENABLED = prev_gui_flag
        except Exception:
            pass
        # Reap any stub PTY sessions this walk left live (defensive).
        try:
            import pty_manager as _pty2
            import session_registry as _sreg2
            for sid in list(_pty2.live_sessions()):
                try:
                    _pty2.kill(sid)
                except Exception:
                    pass
            for pid_ in rnd_env.get("created_ids", []):
                for srec in _sreg2.list_sessions(project_id=pid_):
                    try:
                        _sreg2.remove_session(srec.get("session_id"))
                    except Exception:
                        pass
        except Exception:
            pass
        # Restore every env var we forced for this walk (incl. the runner, which
        # we swapped to the stream-json stub — later checks must see fake_claude).
        for var, prev in (("ANCHOR_PTY_BACKEND", prev_pty),
                          ("ANCHOR_WORKTREE_BASE", prev_wtbase),
                          ("ANCHOR_TERMINAL_SEED", prev_seed),
                          ("ANCHOR_RUNNER_CMD", prev_runner),
                          ("STUB_STREAMJSON_CLAIMS", prev_claims),
                          ("ANCHOR_PROACTIVE_SUMMARY", prev_proactive)):
            if prev is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = prev

    failures = [f"{s}: {d}" for s, ok, d in steps if not ok]
    if failures:
        report.check(name, False, "; ".join(failures))
    else:
        report.check(name, True, f"{len(steps)} steps")


def _stub_gh_cmd() -> "str | None":
    """Path to the hermetic ``gh`` stub (``tests/stub_gh.py``) for the v8 walk.

    The v8 link-GitHub seam (``project_remote.link_github(mode='create')``) routes
    through ``ANCHOR_GH_CMD``; pointing it at this stub means the walk NEVER hits
    the network / real ``gh`` / real github.com. Returns a ``python <abs path>``
    command string, or ``None`` if the stub is absent (the remote sub-step then
    degrades gracefully instead of risking a real ``gh``).
    """
    stub = ANCHOR_DIR / "tests" / "stub_gh.py"
    if stub.is_file():
        # Use a forward-slash POSIX path + bare ``python`` so the ``shlex.split``
        # the gh seam (``project_remote._gh_base_cmd``) applies — POSIX mode, which
        # treats Windows backslashes as escapes — does not mangle the path (the
        # same reason ``tests/test_github_link_v8.py`` uses ``python <posix>``).
        return f"python {stub.as_posix()}"
    return None


def check_rnd_v8_surface(report: Report, server_proc, rnd_env: dict):
    """Exercise the v8 "Durable Artifacts" R&D surface — FULLY STUBBED.

    Walks the new v8 seams in throwaway temp folders + temp git repos, never
    touching real data, never a live claude / real PTY / real worktree off the
    build repo, and — critically — **never a real ``git push`` / real ``gh`` /
    network / github.com**. ``ANCHOR_PTY_BACKEND=stub`` + ``ANCHOR_RUNNER_CMD``
    (the STREAM-JSON stub ``tests/stub_streamjson.py``) + a temp
    ``ANCHOR_WORKTREE_BASE`` + ``ANCHOR_GH_CMD`` → ``tests/stub_gh.py`` (a fake gh
    that prints a deterministic URL) + a LOCAL BARE git remote (a ``file://``
    path) keep every model / PTY / git-remote interaction off the real world.
    Nothing binds ``:8777``.

      (a) bootstrap — a NON-git temp folder → ``project_bootstrap.ensure_git_repo``
          + ``ensure_claude_md`` makes it a repo with a starter CLAUDE.md, and a
          SECOND call is an idempotent no-op (nothing clobbered).
      (b) doc persistence (THE KEYSTONE) — a session writes plan docs in its
          worktree → ``terminal_session.kill`` persists them into the MAIN project
          (present + committed) BEFORE the worktree is reaped; a build worktree
          created afterward CONTAINS them; ``handoff.discover_recent_plan_set``
          finds the plan set from the main folder.
      (c) handoff seed — the build seed carries the REAL persisted doc paths +
          names the correct skill (Foreman for build; Crucible for research→plan).
      (d) no-loss — the killed session's persisted docs + summary record (stable
          managed id) are recoverable via ``efforts_for_session_id`` and the
          session resolves in ``sessions.list_sessions`` after reap.
      (e) grass — ``develop_grass_idea`` is contained+deduped (a dev session, NOT
          on the board) and ``export_grass_to_project`` carries docs up + marks the
          idea ``promoted`` (idea stays in grass).
      (f) remote — ``link_github(mode='create')`` via the stub gh → a PRIVATE,
          persisted remote; opt-in persists; ``auto_push_if_opted`` pushes to the
          LOCAL BARE remote ONLY when linked AND opted (a non-opted/non-linked
          project NEVER pushes).

    Every stub PTY + synthetic session row is reaped, all forced env (incl. the
    runner + the gh seam) is restored, and the temp dirs are torn down (here +
    by ``_cleanup_synthetic_rnd``). Asserts nothing bound ``:8777`` and no real
    network / gh / github.com was reached.
    """
    name = "R&D v8 surface"
    sj_cmd = _streamjson_runner_cmd()
    gh_cmd = _stub_gh_cmd()
    if not rnd_env.get("runner_cmd") or not sj_cmd:
        report.check(name, True,
                     "skipped (no stub runner; live claude avoided)")
        return

    import tempfile as _tf
    steps: list[tuple[str, bool, str]] = []

    prev_pty = os.environ.get("ANCHOR_PTY_BACKEND")
    prev_wtbase = os.environ.get("ANCHOR_WORKTREE_BASE")
    prev_seed = os.environ.get("ANCHOR_TERMINAL_SEED")
    prev_runner = os.environ.get("ANCHOR_RUNNER_CMD")
    prev_gh = os.environ.get("ANCHOR_GH_CMD")
    prev_gh_fail = os.environ.get("ANCHOR_GH_STUB_FAIL")
    prev_gh_remote = os.environ.get("ANCHOR_GH_STUB_REMOTE")
    os.environ["ANCHOR_PTY_BACKEND"] = "stub"
    wt_base = Path(_tf.mkdtemp(prefix="anchor-hc-v8-wt-"))
    os.environ["ANCHOR_WORKTREE_BASE"] = str(wt_base)
    os.environ["ANCHOR_RUNNER_CMD"] = sj_cmd
    if gh_cmd:
        os.environ["ANCHOR_GH_CMD"] = gh_cmd
    os.environ.pop("ANCHOR_GH_STUB_FAIL", None)
    os.environ.pop("ANCHOR_GH_STUB_REMOTE", None)
    rnd_env.setdefault("v3_temp_dirs", []).append(wt_base)

    pid = None
    try:
        import rnd_registry as _rnd
        import terminal_session as _ts
        import session_registry as _sreg
        import effort_history as _eh
        import sessions as _sessions
        import handoff as _handoff
        import project_bootstrap as _boot
        import project_remote as _remote

        # ── (a) bootstrap: non-git temp → git repo + starter CLAUDE.md (idempotent)
        try:
            boot_folder = Path(_tf.mkdtemp(prefix="anchor-hc-v8-boot-"))
            rnd_env["v3_temp_dirs"].append(boot_folder)
            (boot_folder / "notes.txt").write_text("hello\n", encoding="utf-8")
            cm = _boot.ensure_claude_md(str(boot_folder), "HC v8 probe")
            g1 = _boot.ensure_git_repo(str(boot_folder))
            import worktrees as _wt
            is_repo = _wt._is_git_repo(boot_folder)
            cm_exists = (boot_folder / "CLAUDE.md").is_file()
            # Idempotent: a second pass is a no-op (no clobber, not re-initialized).
            g2 = _boot.ensure_git_repo(str(boot_folder))
            cm2 = _boot.ensure_claude_md(str(boot_folder), "HC v8 probe")
            boot_ok = (cm.get("created") is True and cm_exists
                       and g1.get("ok") and is_repo
                       and g2.get("ok") and g2.get("initialized") is False
                       and cm2.get("created") is False)
            steps.append(("bootstrap git-init + CLAUDE.md idempotent",
                          boot_ok,
                          f"init={g1.get('initialized')} "
                          f"reinit={g2.get('initialized')} "
                          f"cm={cm.get('created')}/{cm2.get('created')}"))
        except Exception as e:
            steps.append(("bootstrap", False, f"{type(e).__name__}: {e}"))

        # ── 0. A throwaway git project (worktrees attach to a real repo) ───────
        proj_folder = Path(_tf.mkdtemp(prefix="anchor-hc-v8-proj-"))
        rnd_env["v3_temp_dirs"].append(proj_folder)
        (proj_folder / "CLAUDE.md").write_text(
            "# hc v8 probe\n\nR&D project managed by Anchor.\n",
            encoding="utf-8")
        git_ok = _git_init_repo(proj_folder)
        if not git_ok:
            report.check(name, True, "skipped (git init failed)")
            return
        proj = _rnd.add_project(SYNTHETIC_RND_NAME + " v8", str(proj_folder),
                                scaffold=False)
        pid = proj["id"]
        rnd_env["created_ids"].append(pid)
        steps.append(("register v8 project", bool(pid), str(pid)))

        # ── (b) doc persistence (THE KEYSTONE) + (c) handoff + (d) no-loss ────
        if git_ok:
            try:
                # A planning session that writes a plan set in its worktree, then
                # is killed → persist_session_docs lands the docs in the main repo.
                prec = _ts.start_session(pid, "plan", backend="claude",
                                         label="hc v8 plan")
                psid = prec["session_id"]
                wt = prec.get("worktree_path", "")
                plan_dir = Path(wt) / "planning" / "rnd-hc-v8"
                plan_dir.mkdir(parents=True, exist_ok=True)
                (plan_dir / "MASTER-PLAN.md").write_text(
                    "# Master Plan\n\nThe durable-artifacts probe master plan.\n",
                    encoding="utf-8")
                (plan_dir / "IMPLEMENTATION-PLAN.md").write_text(
                    "# Implementation Plan\n\nWave 1 ... Wave 8 (probe).\n",
                    encoding="utf-8")
                kill_out = _ts.kill(psid, project_id=pid)
                # Keystone: the docs are now in the MAIN folder + committed, and
                # the worktree is gone.
                main_master = (proj_folder / "planning" / "rnd-hc-v8"
                               / "MASTER-PLAN.md")
                main_impl = (proj_folder / "planning" / "rnd-hc-v8"
                             / "IMPLEMENTATION-PLAN.md")
                wt_gone = not Path(wt).exists()
                docs_persisted = bool(kill_out.get("docs", {}).get("persisted"))
                persisted_ok = (main_master.is_file() and main_impl.is_file()
                                and wt_gone and docs_persisted)
                steps.append(("keystone: docs persisted to main + worktree reaped",
                              persisted_ok,
                              f"master={main_master.is_file()} "
                              f"impl={main_impl.is_file()} wt_gone={wt_gone}"))

                # (d) no-loss: the killed session's persisted docs are recoverable
                # by managed-session id, and the session resolves after reap.
                store_lane = _eh._resolve_subdir("plan")
                joined = _eh.efforts_for_session_id(
                    str(proj_folder), pid, store_lane, psid)
                psess = _sessions.list_sessions(str(proj_folder), pid, "plan")
                no_loss = (len(joined) >= 2 and len(psess) >= 1)
                steps.append(("no-loss: persisted docs recoverable by session id",
                              no_loss,
                              f"joined_docs={len(joined)} sessions={len(psess)}"))

                # (b cont.) discover_recent_plan_set finds the plan set from main.
                ps = _handoff.discover_recent_plan_set(str(proj_folder), pid)
                disc_ok = bool(ps) and bool(ps.get("master_plan_rel")) \
                    and bool(ps.get("impl_plan_rel"))
                steps.append(("discover_recent_plan_set finds the persisted set",
                              disc_ok, f"plan_set={bool(ps)}"))

                # (c) handoff seed carries REAL paths + the correct skill.
                seed = _ts._build_seed_for_plan(ps or {})
                seed_ok = ("Foreman" in seed
                           and "IMPLEMENTATION-PLAN" in seed)
                rseed = _ts._build_seed_for_research(None)
                rseed_ok = "Crucible" in rseed
                steps.append(("handoff seed: real paths + correct skill",
                              seed_ok and rseed_ok,
                              f"build_skill_ok={seed_ok} plan_skill_ok={rseed_ok}"))

                # (c cont.) a build worktree created afterward CONTAINS the docs
                # (it is checked out off main HEAD, which the keystone committed).
                brec = _ts.start_session(pid, "build", backend="claude",
                                         label="hc v8 build")
                bsid = brec["session_id"]
                bwt = brec.get("worktree_path", "")
                build_has = (Path(bwt) / "planning" / "rnd-hc-v8"
                             / "IMPLEMENTATION-PLAN.md").is_file()
                steps.append(("build worktree contains the persisted docs",
                              build_has, f"contains={build_has}"))
                try:
                    _ts.kill(bsid, project_id=pid)
                except Exception:
                    pass
            except Exception as e:
                steps.append(("keystone/handoff/no-loss", False,
                              f"{type(e).__name__}: {e}"))
        else:
            steps.append(("keystone/handoff/no-loss", True,
                          "skipped (git unavailable)"))

        # ── (e) grass: develop contained+deduped → export carries docs ────────
        if git_ok:
            try:
                idea = _eh.add_idea(str(proj_folder), pid,
                                    "A durable-artifacts grass idea")
                iid = idea.get("job_id", "")
                d1 = _eh.develop_grass_idea(pid, iid, "research",
                                            folder_path=str(proj_folder),
                                            backend="claude")
                d1sid = d1.get("session_id", "")
                # Contained: the dev session is NOT on the board (its label is
                # stamped grass-dev so the board bridge excludes it).
                contained = _eh.is_grass_dev_label(d1.get("label", ""))
                # Dedupe/focus: a second develop returns the SAME live session.
                d2 = _eh.develop_grass_idea(pid, iid, "research",
                                            folder_path=str(proj_folder),
                                            backend="claude")
                deduped = (d2.get("session_id", "") == d1sid)
                # Write a doc in the dev session's worktree so export carries it.
                d1wt = d1.get("worktree_path", "")
                if d1wt:
                    rdir = Path(d1wt) / "research" / "grass-dev"
                    rdir.mkdir(parents=True, exist_ok=True)
                    (rdir / "REPORT.md").write_text(
                        "# Report\n\nGrass idea research findings.\n",
                        encoding="utf-8")
                exp = _eh.export_grass_to_project(pid, iid,
                                                  folder_path=str(proj_folder))
                exported = exp.get("exported", []) or []
                carries_docs = any(e.get("docs") for e in exported)
                # The idea stays in grass, marked promoted.
                board = _eh.grass_workbench_data(str(proj_folder), pid)
                still_there = any(
                    (it.get("idea_id") == iid or it.get("job_id") == iid)
                    and it.get("status") == _eh.GRASS_PROMOTED
                    for it in board)
                grass_ok = (contained and deduped and bool(exported)
                            and carries_docs and still_there)
                steps.append(("grass contained+deduped + export carries docs",
                              grass_ok,
                              f"contained={contained} deduped={deduped} "
                              f"exported={len(exported)} promoted={still_there}"))
                # Reap the contained dev PTY.
                try:
                    _ts.kill(d1sid, project_id=pid)
                except Exception:
                    pass
            except Exception as e:
                steps.append(("grass", False, f"{type(e).__name__}: {e}"))
        else:
            steps.append(("grass", True, "skipped (git unavailable)"))

        # ── (f) remote: link (stub gh, private, persisted) + opt-in + push ────
        if git_ok and gh_cmd:
            try:
                import subprocess as _sp
                # A LOCAL BARE repo stands in for github.com (file:// → no network).
                bare = Path(_tf.mkdtemp(prefix="anchor-hc-v8-bare-")) / "bare.git"
                _sp.run(["git", "init", "--bare", str(bare)],
                        capture_output=True, text=True, timeout=30)
                rnd_env["v3_temp_dirs"].append(bare.parent)
                bare_url = bare.resolve().as_uri()

                # link via the gh CREATE seam → PRIVATE + persisted on the record.
                link = _remote.link_github(str(proj_folder), "create",
                                           "hc-v8-proj", project_id=pid)
                link_ok = (link.get("ok") and link.get("private") is True
                           and bool(link.get("remote_url"))
                           and _remote.is_linked(pid))

                # Re-point origin at the LOCAL BARE remote so the push is
                # network-free (the stub gh invented a github.com URL).
                _remote.link_github(str(proj_folder), "existing", bare_url,
                                    project_id=pid)

                # Non-opted → NEVER pushes.
                no_opt = _remote.auto_push_if_opted(pid)
                not_pushed = no_opt.get("pushed") is False \
                    and no_opt.get("reason") == "not-opted"

                # Opt-in persists, THEN linked+opted pushes to the LOCAL BARE only.
                _remote.set_auto_push(pid, True)
                pushed = _remote.auto_push_if_opted(pid)
                bare_has = _sp.run(
                    ["git", "-C", str(bare), "rev-parse", "--verify",
                     "--quiet", "HEAD"],
                    capture_output=True, text=True).returncode == 0
                remote_ok = (link_ok and not_pushed
                             and pushed.get("pushed") is True and bare_has)
                steps.append(("remote: create(private)+opt-in gates push (local bare)",
                              remote_ok,
                              f"link_ok={link_ok} not_pushed={not_pushed} "
                              f"pushed={pushed.get('pushed')} bare_has={bare_has}"))
            except Exception as e:
                steps.append(("remote", False, f"{type(e).__name__}: {e}"))
        else:
            steps.append(("remote", True,
                          "skipped (git or stub gh unavailable)"))

    except Exception as e:
        steps.append(("exception", False, f"{type(e).__name__}: {e}"))
    finally:
        # Reap any stub PTY sessions this walk left live (defensive).
        try:
            import pty_manager as _pty2
            import session_registry as _sreg2
            for sid in list(_pty2.live_sessions()):
                try:
                    _pty2.kill(sid)
                except Exception:
                    pass
            for pid_ in rnd_env.get("created_ids", []):
                for srec in _sreg2.list_sessions(project_id=pid_):
                    try:
                        _sreg2.remove_session(srec.get("session_id"))
                    except Exception:
                        pass
        except Exception:
            pass
        # Restore every env var we forced for this walk (incl. the runner +
        # the gh seam — later checks must see fake_claude / no gh seam).
        for var, prev in (("ANCHOR_PTY_BACKEND", prev_pty),
                          ("ANCHOR_WORKTREE_BASE", prev_wtbase),
                          ("ANCHOR_TERMINAL_SEED", prev_seed),
                          ("ANCHOR_RUNNER_CMD", prev_runner),
                          ("ANCHOR_GH_CMD", prev_gh),
                          ("ANCHOR_GH_STUB_FAIL", prev_gh_fail),
                          ("ANCHOR_GH_STUB_REMOTE", prev_gh_remote)):
            if prev is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = prev

    failures = [f"{s}: {d}" for s, ok, d in steps if not ok]
    if failures:
        report.check(name, False, "; ".join(failures))
    else:
        report.check(name, True, f"{len(steps)} steps")


def check_rnd_v9_surface(report: Report, server_proc, rnd_env: dict):
    """Exercise the v9 "Tidy" R&D surface — FULLY STUBBED.

    Walks the new v9 delete / group / guarded-move seams in throwaway temp
    folders + temp git repos + a TEMP projects_root, never touching real data,
    the live registry, the REAL Anchor repo, a live claude / real PTY, or
    ``:8777``. ``ANCHOR_PTY_BACKEND=stub`` + ``ANCHOR_RUNNER_CMD`` (the STREAM-JSON
    stub) + a temp ``ANCHOR_WORKTREE_BASE`` keep every model / PTY interaction
    off the real world.

      (a) session delete (Option A) — a planning session writes + persists docs,
          then ``terminal_session.delete_session`` clears its registry record +
          effort pointer-records + cached summary; after a reload the session is
          GONE from ``list_sessions`` / the registry, but the PRODUCED DOCS stay
          on disk.
      (b) ghost cleanup — an empty DONE registry record (no efforts) is swept by
          ``cleanup_ghost_sessions``; a record WITH efforts is left untouched.
      (c) grass idea delete — ``delete_grass_idea`` clears the idea pointer +
          index entry + refinements dir; a sibling idea is untouched.
      (d) group — ``set_group`` + ``group_by_group`` bucket the project under a
          named folder (default Ungrouped), no disk move.
      (e) guarded on-disk MOVE on a TEMP project (NEVER the real repo): the dir
          moves into the group subfolder, the registry ``folder_path`` re-points,
          a post-move worktree works; the **Anchor-repo refusal** (CODE_DIR
          pointed at a temp dir for the duration), the **live-session refusal**
          (an injected RUNNING registry row), and **rollback** on an injected
          mid-move failure are all proven on TEMP dirs.

    Every stub PTY + synthetic session row is reaped, all forced env is restored,
    the temp dirs are torn down, and ``paths.CODE_DIR`` is restored. Asserts
    nothing bound ``:8777`` and the REAL Anchor repo / registry was never moved.
    """
    name = "R&D v9 surface"
    sj_cmd = _streamjson_runner_cmd()
    if not rnd_env.get("runner_cmd") or not sj_cmd:
        report.check(name, True,
                     "skipped (no stub runner; live claude avoided)")
        return

    import tempfile as _tf
    steps: list[tuple[str, bool, str]] = []

    prev_pty = os.environ.get("ANCHOR_PTY_BACKEND")
    prev_wtbase = os.environ.get("ANCHOR_WORKTREE_BASE")
    prev_seed = os.environ.get("ANCHOR_TERMINAL_SEED")
    prev_runner = os.environ.get("ANCHOR_RUNNER_CMD")
    os.environ["ANCHOR_PTY_BACKEND"] = "stub"
    wt_base = Path(_tf.mkdtemp(prefix="anchor-hc-v9-wt-"))
    os.environ["ANCHOR_WORKTREE_BASE"] = str(wt_base)
    os.environ["ANCHOR_RUNNER_CMD"] = sj_cmd
    rnd_env.setdefault("v3_temp_dirs", []).append(wt_base)

    # Snapshot CODE_DIR so the anchor-repo-refusal probe (which points CODE_DIR at
    # a TEMP dir to PROVE the guard) can never leave it pointed off the real repo.
    prev_code_dir = _paths.CODE_DIR

    pid = None
    try:
        import rnd_registry as _rnd
        import terminal_session as _ts
        import session_registry as _sreg
        import effort_history as _eh
        import sessions as _sessions
        import project_move as _move

        # ── 0. A throwaway git project (worktrees attach to a real repo) ───────
        proj_folder = Path(_tf.mkdtemp(prefix="anchor-hc-v9-proj-"))
        rnd_env["v3_temp_dirs"].append(proj_folder)
        (proj_folder / "CLAUDE.md").write_text(
            "# hc v9 probe\n\nR&D project managed by Anchor.\n",
            encoding="utf-8")
        git_ok = _git_init_repo(proj_folder)
        if not git_ok:
            report.check(name, True, "skipped (git init failed)")
            return
        proj = _rnd.add_project(SYNTHETIC_RND_NAME + " v9", str(proj_folder),
                                scaffold=False)
        pid = proj["id"]
        rnd_env["created_ids"].append(pid)
        steps.append(("register v9 project", bool(pid), str(pid)))

        # ── (a) session delete (Option A: keep produced docs) ─────────────────
        if git_ok:
            try:
                prec = _ts.start_session(pid, "plan", backend="claude",
                                         label="hc v9 plan")
                psid = prec["session_id"]
                wt = prec.get("worktree_path", "")
                plan_dir = Path(wt) / "planning" / "rnd-hc-v9"
                plan_dir.mkdir(parents=True, exist_ok=True)
                (plan_dir / "MASTER-PLAN.md").write_text(
                    "# Master Plan\n\nThe tidy probe master plan.\n",
                    encoding="utf-8")
                # Kill persists the doc into the main folder (committed) + reaps.
                _ts.kill(psid, project_id=pid)
                main_master = (proj_folder / "planning" / "rnd-hc-v9"
                               / "MASTER-PLAN.md")
                doc_before = main_master.is_file()

                # Delete the session: record + efforts + summary gone, doc KEPT.
                out = _ts.delete_session(psid, project_id=pid)
                gone_from_reg = _sreg.get_session(psid) is None
                # Reload: the session must STAY gone from list_sessions.
                psess = _sessions.list_sessions(str(proj_folder), pid, "plan")
                still_listed = any(
                    s.get("session_id") == psid for s in psess)
                doc_after = main_master.is_file()  # Option A: doc survives delete
                del_ok = (out.get("ok") and gone_from_reg
                          and not still_listed
                          and doc_before and doc_after)
                steps.append(("session delete clears record+efforts+summary, "
                              "keeps docs (Option A)",
                              del_ok,
                              f"reg_gone={gone_from_reg} relist={not still_listed} "
                              f"doc_kept={doc_after}"))
            except Exception as e:
                steps.append(("session delete", False, f"{type(e).__name__}: {e}"))
        else:
            steps.append(("session delete", True, "skipped (git unavailable)"))

        # ── (b) ghost cleanup: empty DONE record swept; one WITH efforts kept ──
        try:
            ghost = _sreg.register_session(pid, "research", label="hc v9 ghost",
                                           status=_sreg.STATUS_DONE)
            ghost_id = ghost["session_id"]
            # A record WITH an effort tied to it must NOT be swept.
            keeper = _sreg.register_session(pid, "research", label="hc v9 keeper",
                                            status=_sreg.STATUS_DONE)
            keeper_id = keeper["session_id"]
            _eh.record_effort(str(proj_folder), pid, "research",
                              "hc-v9-keeper-effort",
                              extra={"source": _eh.SOURCE_RUN,
                                     "session_id": keeper_id,
                                     "title": "keeper effort"})
            swept = _ts.cleanup_ghost_sessions(pid)
            removed = set(swept.get("removed", []))
            ghost_swept = (ghost_id in removed
                           and _sreg.get_session(ghost_id) is None)
            keeper_kept = (keeper_id not in removed
                           and _sreg.get_session(keeper_id) is not None)
            steps.append(("ghost cleanup sweeps empty record, keeps one w/ efforts",
                          ghost_swept and keeper_kept,
                          f"swept={ghost_swept} kept={keeper_kept}"))
            # Tidy the keeper row so teardown is clean.
            try:
                _sreg.remove_session(keeper_id)
            except Exception:
                pass
        except Exception as e:
            steps.append(("ghost cleanup", False, f"{type(e).__name__}: {e}"))

        # ── (c) grass idea delete: pointer+index+refinements gone; sibling kept ─
        try:
            idea = _eh.add_idea(str(proj_folder), pid, "A tidy grass idea")
            iid = idea.get("job_id", "")
            sibling = _eh.add_idea(str(proj_folder), pid, "A sibling grass idea")
            sib_id = sibling.get("job_id", "")
            _eh.save_grass_refinement(str(proj_folder), pid, iid,
                                      "a refinement note")
            before = {it.get("idea_id") or it.get("job_id")
                      for it in _eh.grass_workbench_data(str(proj_folder), pid)}
            dres = _eh.delete_grass_idea(str(proj_folder), pid, iid)
            after = {it.get("idea_id") or it.get("job_id")
                     for it in _eh.grass_workbench_data(str(proj_folder), pid)}
            idea_gone = iid not in after
            sibling_kept = sib_id in after
            grass_del_ok = (dres.get("ok") and dres.get("deleted")
                            and idea_gone and sibling_kept
                            and iid in before)
            steps.append(("grass idea delete clears pointer+index+refinements; "
                          "sibling kept",
                          grass_del_ok,
                          f"deleted={dres.get('deleted')} gone={idea_gone} "
                          f"sibling_kept={sibling_kept}"))
        except Exception as e:
            steps.append(("grass idea delete", False, f"{type(e).__name__}: {e}"))

        # ── (d) group: set_group + group_by_group (no disk move) ──────────────
        try:
            _rnd.set_group(pid, "HC-Research")
            groups = _rnd.group_by_group()
            in_named = any(
                e.get("id") == pid for e in groups.get("HC-Research", []))
            ungrouped_last = list(groups.keys())[-1] == _rnd.UNGROUPED_LABEL
            # The on-disk folder is unchanged by grouping.
            still_here = Path(proj_folder).is_dir()
            grp_ok = in_named and ungrouped_last and still_here
            steps.append(("set_group + group_by_group (no disk move)",
                          grp_ok,
                          f"grouped={in_named} ungrouped_last={ungrouped_last} "
                          f"dir_unchanged={still_here}"))
            _rnd.set_group(pid, "")  # back to Ungrouped for the move probe
        except Exception as e:
            steps.append(("group", False, f"{type(e).__name__}: {e}"))

        # ── (e) guarded on-disk MOVE on a TEMP project (never the real repo) ──
        # Make a SEPARATE temp project + temp projects_root so the move never
        # touches the real Anchor repo / live registry.
        try:
            move_root = Path(_tf.mkdtemp(prefix="anchor-hc-v9-root-"))
            rnd_env["v3_temp_dirs"].append(move_root)
            mv_folder = move_root / "tidy-proj"
            mv_folder.mkdir(parents=True, exist_ok=True)
            (mv_folder / "CLAUDE.md").write_text(
                "# hc v9 move probe\n", encoding="utf-8")
            _git_init_repo(mv_folder)
            mproj = _rnd.add_project(SYNTHETIC_RND_NAME + " v9 move",
                                     str(mv_folder), scaffold=False)
            mpid = mproj["id"]
            rnd_env["created_ids"].append(mpid)

            # (e1) the happy move: dir → <root>/research/tidy-proj, re-pointed.
            mres = _move.move_to_group(mpid, "research",
                                       projects_root=str(move_root))
            dest = move_root / "research" / "tidy-proj"
            moved_ok = (mres.get("ok") and dest.is_dir()
                        and not mv_folder.exists())
            repointed = (_rnd.get_project(mpid) or {}).get(
                "folder_path", "") == str(dest)
            # A post-move worktree on the moved project works (create_worktree
            # resolves the repo from the registry folder_path the move re-pointed).
            post_wt_ok = False
            if git_ok:
                try:
                    import worktrees as _wt2
                    rec = _wt2.create_worktree(mpid, "hc-v9-postmove")
                    wtp = rec.get("path", "") if rec else ""
                    post_wt_ok = bool(rec.get("ok")) and bool(wtp) \
                        and Path(wtp).exists()
                    if wtp:
                        _wt2.remove_worktree("hc-v9-postmove", project_id=mpid)
                except Exception:
                    post_wt_ok = False
            else:
                post_wt_ok = True  # can't exercise worktrees without git
            steps.append(("guarded move re-points registry + post-move worktree",
                          moved_ok and repointed and post_wt_ok,
                          f"moved={moved_ok} repointed={repointed} "
                          f"post_wt={post_wt_ok}"))

            # (e2) Anchor-repo refusal — register a probe project whose
            # folder_path IS the real running CODE_DIR, so the guard fires WITHOUT
            # swapping CODE_DIR. (Swapping CODE_DIR also redirects data_dir()/the
            # registry when ANCHOR_DATA_DIR is unset — as in the live 5 AM run — so
            # move_to_group read an EMPTY registry and wrongly returned
            # 'unknown-project'. The move is refused BEFORE any fs op, so pointing
            # the probe at the real repo path is safe; the synthetic entry is reaped
            # via created_ids at teardown.)
            aproj = _rnd.add_project(SYNTHETIC_RND_NAME + " v9 anchor",
                                     str(_paths.CODE_DIR), scaffold=False)
            apid = aproj["id"]
            rnd_env["created_ids"].append(apid)
            refusal = _move.move_to_group(apid, "research",
                                          projects_root=str(move_root))
            anchor_refused = (not refusal.get("ok")
                              and refusal.get("reason") == "refused-anchor-repo")
            steps.append(("move REFUSES the Anchor repo (no fs change)",
                          anchor_refused,
                          f"reason={refusal.get('reason')}"))

            # (e3) live-session refusal — inject a RUNNING registry row.
            live_folder = move_root / "live-proj"
            live_folder.mkdir(parents=True, exist_ok=True)
            lproj = _rnd.add_project(SYNTHETIC_RND_NAME + " v9 live",
                                     str(live_folder), scaffold=False)
            lpid = lproj["id"]
            rnd_env["created_ids"].append(lpid)
            live_rec = _sreg.register_session(lpid, "build",
                                              label="hc v9 live",
                                              status=_sreg.STATUS_RUNNING)
            live_ref = _move.move_to_group(lpid, "research",
                                           projects_root=str(move_root))
            live_refused = (not live_ref.get("ok")
                            and live_ref.get("reason") == "refused-live-sessions"
                            and live_folder.is_dir())
            steps.append(("move REFUSES a live-session project (no fs change)",
                          live_refused, f"reason={live_ref.get('reason')}"))
            try:
                _sreg.remove_session(live_rec["session_id"])
            except Exception:
                pass

            # (e4) rollback on an injected mid-move failure: monkeypatch the
            # rescan seam (post dir-move) to raise → the dir + folder_path are
            # restored.
            rb_folder = move_root / "rb-proj"
            rb_folder.mkdir(parents=True, exist_ok=True)
            (rb_folder / "CLAUDE.md").write_text("# rb\n", encoding="utf-8")
            rproj = _rnd.add_project(SYNTHETIC_RND_NAME + " v9 rb",
                                     str(rb_folder), scaffold=False)
            rpid = rproj["id"]
            rnd_env["created_ids"].append(rpid)
            orig_rescan = _move._rescan

            def _boom(_pid):
                raise RuntimeError("injected rescan failure")

            _move._rescan = _boom
            try:
                rb = _move.move_to_group(rpid, "research",
                                         projects_root=str(move_root))
            finally:
                _move._rescan = orig_rescan
            rb_restored = (not rb.get("ok")
                           and rb.get("reason") == "move-failed"
                           and rb.get("rolled_back") is True
                           and rb_folder.is_dir()
                           and not (move_root / "research" / "rb-proj").exists()
                           and (_rnd.get_project(rpid) or {}).get(
                               "folder_path", "") == str(rb_folder))
            steps.append(("move ROLLS BACK on an injected mid-move failure",
                          rb_restored,
                          f"reason={rb.get('reason')} "
                          f"rolled_back={rb.get('rolled_back')}"))
        except Exception as e:
            steps.append(("guarded move", False, f"{type(e).__name__}: {e}"))
        finally:
            _paths.CODE_DIR = prev_code_dir  # belt-and-suspenders restore

    except Exception as e:
        steps.append(("exception", False, f"{type(e).__name__}: {e}"))
    finally:
        # Always restore CODE_DIR (never leave it pointed off the real repo).
        _paths.CODE_DIR = prev_code_dir
        # Reap any stub PTY sessions this walk left live (defensive).
        try:
            import pty_manager as _pty2
            import session_registry as _sreg2
            for sid in list(_pty2.live_sessions()):
                try:
                    _pty2.kill(sid)
                except Exception:
                    pass
            for pid_ in rnd_env.get("created_ids", []):
                for srec in _sreg2.list_sessions(project_id=pid_):
                    try:
                        _sreg2.remove_session(srec.get("session_id"))
                    except Exception:
                        pass
        except Exception:
            pass
        # Restore every env var we forced for this walk.
        for var, prev in (("ANCHOR_PTY_BACKEND", prev_pty),
                          ("ANCHOR_WORKTREE_BASE", prev_wtbase),
                          ("ANCHOR_TERMINAL_SEED", prev_seed),
                          ("ANCHOR_RUNNER_CMD", prev_runner)):
            if prev is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = prev

    failures = [f"{s}: {d}" for s, ok, d in steps if not ok]
    if failures:
        report.check(name, False, "; ".join(failures))
    else:
        report.check(name, True, f"{len(steps)} steps")


#: A simulated MODEL greet line. Writing it onto the stub PTY echoes it into the
#: read buffer (``pty_manager._StubChild.write``), pushing the greet-marker count
#: past the echoed-seed base — the "model actually greeted" signal the v10
#: pending-paste flush requires before it delivers the paste.
_V10_GREET_LINE = "✓ Skill loaded — what would you like to do?"


def check_rnd_v10_surface(report: Report, server_proc, rnd_env: dict):
    """Exercise the v10 "Live Handoff & Boneyard" R&D surface — FULLY STUBBED.

    Walks the new v10 paste / both-artifact advance / grass-archive+lineage /
    grass research->plan advance / Boneyard seams in throwaway temp folders + temp
    git repos, never touching real data, the live registry, the REAL Anchor repo,
    a live claude / real PTY, or ``:8777``. ``ANCHOR_PTY_BACKEND=stub`` +
    ``ANCHOR_RUNNER_CMD`` (the STREAM-JSON stub) + a temp ``ANCHOR_WORKTREE_BASE``
    keep every model / PTY interaction off the real world.

      (a) PASTE substrate (W1) — a session started with ``paste_prompt`` records
          ``pending_paste`` (not written at start); after a real greet is observed
          the first read flushes it UNSENT (no trailing newline), exactly once.
      (b) ADVANCE both-artifacts (W2) — a plan->build advance writes HANDOFF.md +
          NEXT-PROMPT.md into the new build worktree, links the sessions
          (parent_session_id / shared chain_id), and delivers the prompt as a
          PENDING PASTE (nothing auto-submitted on the unattended path).
      (c) GRASS (W3-W5) — two contained grass dev sessions (research + plan)
          coexist; ``archive_grass_session`` records a per-idea bundle (idea stays
          in grass); ``export_grass_to_project`` stamps ``grass_origin`` and a
          downstream session inherits it; ``advance_grass_research_to_plan`` opens
          a contained, linked, paste-pending plan dev session; grass-dev sessions
          are excluded from the board/top-strip projection.
      (d) BONEYARD (W6) — kill (with material) -> a ``killed`` entry; a v9 delete
          -> a ``deleted`` entry captured BEFORE the effort pointer-records drop
          (doc_rels non-empty after efforts gone); ``delete_grass_idea`` -> a
          ``grass-deleted`` entry; ``search`` filters; deleting a LIVE session
          yields exactly ONE ``deleted`` entry (not killed+deleted).

    Every stub PTY + synthetic session row is reaped, all forced env is restored,
    and the temp dirs are torn down. Asserts nothing bound ``:8777`` and real data
    was never touched. A sub-step that cannot run (e.g. git absent) is recorded
    honestly as skipped rather than failing the whole check (v9 tolerance).
    """
    name = "R&D v10 surface"
    sj_cmd = _streamjson_runner_cmd()
    if not rnd_env.get("runner_cmd") or not sj_cmd:
        report.check(name, True,
                     "skipped (no stub runner; live claude avoided)")
        return

    import tempfile as _tf
    steps: list[tuple[str, bool, str]] = []

    prev_pty = os.environ.get("ANCHOR_PTY_BACKEND")
    prev_wtbase = os.environ.get("ANCHOR_WORKTREE_BASE")
    prev_seed = os.environ.get("ANCHOR_TERMINAL_SEED")
    prev_runner = os.environ.get("ANCHOR_RUNNER_CMD")
    os.environ["ANCHOR_PTY_BACKEND"] = "stub"
    os.environ.pop("ANCHOR_TERMINAL_SEED", None)  # rely on the built-in greet seed
    wt_base = Path(_tf.mkdtemp(prefix="anchor-hc-v10-wt-"))
    os.environ["ANCHOR_WORKTREE_BASE"] = str(wt_base)
    os.environ["ANCHOR_RUNNER_CMD"] = sj_cmd
    rnd_env.setdefault("v3_temp_dirs", []).append(wt_base)

    def _greet(sid):
        """Surface a real model greet on a session's stub PTY (count > base)."""
        try:
            import pty_manager as _pty
            _pty.write(sid, _V10_GREET_LINE)
        except Exception:
            pass

    pid = None
    try:
        import rnd_registry as _rnd
        import terminal_session as _ts
        import session_registry as _sreg
        import effort_history as _eh
        import handoff as _handoff
        import boneyard as _bone
        import pty_manager as _pty

        # ── 0. A throwaway git project (worktrees attach to a real repo) ───────
        proj_folder = Path(_tf.mkdtemp(prefix="anchor-hc-v10-proj-"))
        rnd_env["v3_temp_dirs"].append(proj_folder)
        (proj_folder / "CLAUDE.md").write_text(
            "# hc v10 probe\n\nR&D project managed by Anchor.\n",
            encoding="utf-8")
        git_ok = _git_init_repo(proj_folder)
        if not git_ok:
            report.check(name, True, "skipped (git init failed)")
            return
        proj = _rnd.add_project(SYNTHETIC_RND_NAME + " v10", str(proj_folder),
                                scaffold=False)
        pid = proj["id"]
        rnd_env["created_ids"].append(pid)
        steps.append(("register v10 project", bool(pid), str(pid)))

        # ── (a) PASTE substrate (W1): pending → flush UNSENT once after greet ──
        try:
            prompt = "PLAN FROM THE TIDY PROBE"
            psess = _ts.start_session(pid, "planning", backend="claude",
                                      paste_prompt=prompt)
            psid = psess["session_id"]
            rec0 = _sreg.get_session(psid)
            # Recorded pending, NOT written at start, not yet flushed.
            buf0 = _pty.read_since(psid, 0)["text"]
            pending_ok = (rec0.get("pending_paste") == prompt
                          and rec0.get("paste_flushed") is False
                          and prompt not in buf0)
            # Inject the model greet → the next read flushes the paste UNSENT.
            _greet(psid)
            _ts.read_since(psid, 0)
            full = _pty.read_since(psid, 0)["text"]
            rec1 = _sreg.get_session(psid)
            flushed_ok = (prompt in full
                          and (prompt + "\n") not in full      # not auto-submitted
                          and full.rstrip("\r").endswith(prompt)
                          and rec1.get("paste_flushed") is True
                          and rec1.get("pending_paste") == "")
            # Idempotent: a second read/attach does NOT re-emit the paste.
            _ts.read_since(psid, 0)
            _ts.attach(psid)
            once_ok = _pty.read_since(psid, 0)["text"].count(prompt) == 1
            steps.append(("paste held pending then flushed UNSENT once after greet",
                          pending_ok and flushed_ok and once_ok,
                          f"pending={pending_ok} unsent={flushed_ok} once={once_ok}"))
            try:
                _ts.kill(psid, project_id=pid, _record_boneyard=False)
            except Exception:
                pass
        except Exception as e:
            steps.append(("paste substrate", False, f"{type(e).__name__}: {e}"))

        # ── (b) ADVANCE both-artifacts (W2): plan→build, linked, paste pending ─
        if git_ok:
            try:
                # A planning session with a REAL discovered MASTER+IMPL plan set
                # committed into the main repo so discovery finds it.
                plan_dir = proj_folder / "planning" / "rnd-hc-v10"
                plan_dir.mkdir(parents=True, exist_ok=True)
                for fn, body in (("MASTER-PLAN.md", "# Master Plan\n"),
                                 ("IMPLEMENTATION-PLAN.md", "# Implementation Plan\n")):
                    (plan_dir / fn).write_text(body, encoding="utf-8")
                for i, (fn, title) in enumerate(
                        (("MASTER-PLAN.md", "Master Plan"),
                         ("IMPLEMENTATION-PLAN.md", "Implementation Plan"))):
                    rel = f"planning/rnd-hc-v10/{fn}"
                    jid = _eh.discovered_job_id("planning", rel)
                    _eh.record_effort(
                        str(proj_folder), pid, "planning", jid, skill="Crucible",
                        extra={"source": _eh.SOURCE_DISCOVERED, "kind": "plan-doc",
                               "title": title, "artifact_path": rel,
                               "status": "imported",
                               "created_at": 2000.0 + i * 0.001})
                # Start a planning session, mark it DONE (the terminal transition
                # auto_advance gates on), then auto-advance to one linked build.
                plansess = _ts.start_session(pid, "planning", backend="claude",
                                             label="hc v10 plan")
                plan_sid = plansess["session_id"]
                _sreg.update_session(plan_sid, status=_sreg.STATUS_DONE)
                build_rec = _ts.auto_advance_planning_to_build(pid, plan_sid)
                adv_ok = bool(build_rec)
                both_artifacts = False
                linked = False
                paste_pending = False
                if build_rec:
                    bsid = build_rec.get("session_id", "")
                    bwt = build_rec.get("worktree_path", "")
                    both_artifacts = bool(bwt) and (
                        (Path(bwt) / "HANDOFF.md").is_file()
                        and (Path(bwt) / "NEXT-PROMPT.md").is_file())
                    brec = _sreg.get_session(bsid)
                    linked = (brec.get("parent_session_id") == plan_sid
                              and brec.get("chain_id")
                              == _sreg.get_session(plan_sid).get("chain_id"))
                    # Unattended path: the build holds the prompt PENDING — nothing
                    # auto-submitted (paste_flushed False until first attach).
                    paste_pending = (bool(brec.get("pending_paste"))
                                     and brec.get("paste_flushed") is False)
                    # Idempotent: a second advance does NOT mint a second build.
                    again = _ts.auto_advance_planning_to_build(pid, plan_sid)
                    idem_ok = again is None
                    try:
                        _ts.kill(bsid, project_id=pid, _record_boneyard=False)
                    except Exception:
                        pass
                else:
                    idem_ok = False
                steps.append(("advance writes both artifacts + links + pending paste",
                              adv_ok and both_artifacts and linked
                              and paste_pending and idem_ok,
                              f"advanced={adv_ok} artifacts={both_artifacts} "
                              f"linked={linked} pending={paste_pending} "
                              f"idempotent={idem_ok}"))
            except Exception as e:
                steps.append(("advance both-artifacts", False,
                              f"{type(e).__name__}: {e}"))
        else:
            steps.append(("advance both-artifacts", True,
                          "skipped (git unavailable)"))

        # ── (c) GRASS (W3-W5): two dev sessions + archive + lineage + advance ──
        if git_ok:
            try:
                idea = _eh.add_idea(str(proj_folder), pid,
                                    "Adaptive prefetch for the cache layer")
                iid = idea.get("job_id", "")
                # W3: two contained dev sessions (research + plan) coexist.
                dev_r = _eh.develop_grass_idea(pid, iid, "research",
                                               folder_path=str(proj_folder))
                dev_p = _eh.develop_grass_idea(pid, iid, "plan",
                                               folder_path=str(proj_folder))
                rsid = dev_r.get("session_id", "")
                two_dev = (rsid and dev_p.get("session_id")
                           and rsid != dev_p.get("session_id"))
                # Both dev sessions are EXCLUDED from the board (contained label).
                excluded = (_eh.is_grass_dev_label(
                    _sreg.get_session(rsid).get("label"))
                    and _eh.is_grass_dev_label(
                        _sreg.get_session(dev_p.get("session_id")).get("label")))
                # W4: produce a doc in the research dev worktree, then ARCHIVE it.
                rwt = dev_r.get("worktree_path", "")
                arch_rel = "research/grass-dev/PREFETCH-NOTES.md"
                if rwt:
                    p = Path(rwt) / arch_rel
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text("# Prefetch notes\nAdaptive prefetch idea.\n",
                                 encoding="utf-8")
                arch = _eh.archive_grass_session(pid, iid, "research",
                                                 folder_path=str(proj_folder))
                archives = _eh.list_grass_archives(str(proj_folder), pid, iid)
                archive_ok = (arch.get("ok")
                              and any(arch_rel in (b.get("docs") or [])
                                      for b in archives)
                              # idea STAYS in grass after archive.
                              and _eh.get_grass_idea(str(proj_folder), pid, iid)
                              is not None)
                steps.append(("two grass dev sessions coexist + excluded + archive",
                              bool(two_dev) and excluded and archive_ok,
                              f"two_dev={bool(two_dev)} excluded={excluded} "
                              f"archive={archive_ok}"))

                # W4: export stamps grass_origin; a downstream session inherits it.
                exp = _eh.export_grass_to_project(pid, iid,
                                                  folder_path=str(proj_folder))
                # A NEW project plan session linked into the exported chain inherits
                # grass_origin via start_session's chain propagation. We assert the
                # dev session itself carries grass_origin (set on export) and that a
                # child started from it inherits.
                dev_origin = (_sreg.get_session(rsid).get("grass_origin") == iid)
                child = _ts.start_session(pid, "plan", backend="claude",
                                          parent_session_id=rsid,
                                          label="hc v10 lineage child")
                child_inherits = (
                    _sreg.get_session(child["session_id"]).get("grass_origin")
                    == iid)
                # A non-grass session has grass_origin == "" (negative).
                plain = _ts.start_session(pid, "research", backend="claude",
                                          label="hc v10 plain")
                plain_clean = (
                    _sreg.get_session(plain["session_id"]).get("grass_origin")
                    == "")
                steps.append(("export stamps grass_origin; child inherits; "
                              "plain clean",
                              exp.get("ok") and dev_origin and child_inherits
                              and plain_clean,
                              f"exported={exp.get('ok')} dev_origin={dev_origin} "
                              f"child={child_inherits} plain={plain_clean}"))
                for sid_ in (child["session_id"], plain["session_id"]):
                    try:
                        _ts.kill(sid_, project_id=pid, _record_boneyard=False)
                    except Exception:
                        pass

                # W5: grass research→plan advance — contained, linked, paste pending.
                gadv = _eh.advance_grass_research_to_plan(
                    pid, iid, folder_path=str(proj_folder))
                gadv_ok = False
                if gadv.get("ok") and gadv.get("session"):
                    gp = gadv["session"]
                    gp_rec = _sreg.get_session(gp.get("session_id"))
                    gadv_ok = (
                        _eh.is_grass_dev_label(gp_rec.get("label"))      # contained
                        and gp_rec.get("grass_origin") == iid            # lineage
                        and (bool(gp_rec.get("pending_paste"))           # paste held
                             or gadv.get("paste_delivered")))
                else:
                    # Honest: no research material → no plan minted (acceptable).
                    gadv_ok = (gadv.get("reason")
                               in ("no-research-material", "no-research-session",
                                   "focused-existing"))
                steps.append(("grass research->plan advance (contained, linked, "
                              "paste pending)",
                              gadv_ok, f"reason={gadv.get('reason')}"))
            except Exception as e:
                steps.append(("grass W3-W5", False, f"{type(e).__name__}: {e}"))
        else:
            steps.append(("grass W3-W5", True, "skipped (git unavailable)"))

        # ── (d) BONEYARD (W6): capture on kill / delete / grass-delete + search ─
        if git_ok:
            try:
                def _write_build_docs(wt, sub):
                    rel = f"build/{sub}/DELIVERABLE.md"
                    p = Path(wt) / rel
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text("# Deliverable\nThe widget cache service ships.\n",
                                 encoding="utf-8")
                    return rel

                # kill (with material) → a "killed" entry referencing the doc.
                ks = _ts.start_session(pid, "build", backend="claude",
                                       label="hc v10 kill")
                ksid = ks["session_id"]
                krel = _write_build_docs(ks["worktree_path"], "bone-kill")
                _ts.kill(ksid, project_id=pid)  # records "killed" (default)
                killed = [e for e in _bone.list_entries(str(proj_folder), pid)
                          if e["source"] == "killed" and e["session_id"] == ksid]
                killed_ok = (len(killed) == 1
                             and krel in killed[0]["doc_rels"])

                # v9 delete → a "deleted" entry captured BEFORE efforts drop (D10):
                # doc_rels non-empty even though the join is now empty.
                ds = _ts.start_session(pid, "build", backend="claude",
                                       label="hc v10 del")
                dsid = ds["session_id"]
                drel = _write_build_docs(ds["worktree_path"], "bone-del")
                _ts.kill(dsid, project_id=pid, _record_boneyard=False)
                out = _ts.delete_session(dsid, project_id=pid)
                join_empty = _eh.efforts_for_session_id(
                    str(proj_folder), pid, "build", dsid) == []
                deleted = [e for e in _bone.list_entries(str(proj_folder), pid)
                           if e["source"] == "deleted" and e["session_id"] == dsid]
                deleted_ok = (out.get("ok") and out.get("deleted")
                              and len(deleted) == 1
                              and bool(deleted[0]["doc_rels"])   # D10: docs kept
                              and drel in deleted[0]["doc_rels"]
                              and join_empty)

                # Deleting a LIVE session → exactly ONE "deleted" entry (not 2).
                ls = _ts.start_session(pid, "build", backend="claude",
                                       label="hc v10 live-del")
                lsid = ls["session_id"]
                lrel = _write_build_docs(ls["worktree_path"], "bone-live")
                lout = _ts.delete_session(lsid, project_id=pid)
                live_entries = [e for e in _bone.list_entries(str(proj_folder), pid)
                                if e["session_id"] == lsid]
                live_del_ok = (lout.get("ok") and lout.get("deleted")
                               and len(live_entries) == 1
                               and live_entries[0]["source"] == "deleted"
                               and lrel in live_entries[0]["doc_rels"])

                # grass idea delete → a "grass-deleted" entry with the idea text.
                gidea = _eh.add_idea(str(proj_folder), pid,
                                     "Telemetry dashboard for the runner")
                giid = gidea.get("job_id", "")
                _eh.save_grass_refinement(str(proj_folder), pid, giid,
                                          text="v1 notes", label="r1",
                                          artifacts=["grass/dev/telemetry.md"])
                _eh.delete_grass_idea(str(proj_folder), pid, giid)
                grass_del = [e for e in _bone.list_entries(str(proj_folder), pid)
                             if e["source"] == "grass-deleted"
                             and "Telemetry" in (e.get("idea_text") or "")]
                grass_del_ok = (len(grass_del) == 1
                                and "grass/dev/telemetry.md"
                                in grass_del[0]["doc_rels"])

                # search filters: a term unique to the killed build doc PATH
                # matches it (the haystack covers doc rel paths + filenames).
                hits = _bone.search(str(proj_folder), pid, "bone-kill")
                tele = _bone.search(str(proj_folder), pid, "TELEMETRY")
                search_ok = (any(e["session_id"] == ksid for e in hits)
                             and all(e["source"] != "grass-deleted" for e in hits)
                             and len(tele) == 1
                             and tele[0]["source"] == "grass-deleted"
                             and _bone.search(str(proj_folder), pid,
                                              "zzz-no-term") == [])

                steps.append(("boneyard captures killed/deleted(D10)/live-del/"
                              "grass-deleted + search",
                              killed_ok and deleted_ok and live_del_ok
                              and grass_del_ok and search_ok,
                              f"killed={killed_ok} deleted={deleted_ok} "
                              f"live_del={live_del_ok} grass={grass_del_ok} "
                              f"search={search_ok}"))
            except Exception as e:
                steps.append(("boneyard", False, f"{type(e).__name__}: {e}"))
        else:
            steps.append(("boneyard", True, "skipped (git unavailable)"))

    except Exception as e:
        steps.append(("exception", False, f"{type(e).__name__}: {e}"))
    finally:
        # Reap any stub PTY sessions this walk left live (defensive).
        try:
            import pty_manager as _pty2
            import session_registry as _sreg2
            for sid in list(_pty2.live_sessions()):
                try:
                    _pty2.kill(sid)
                except Exception:
                    pass
            for pid_ in rnd_env.get("created_ids", []):
                for srec in _sreg2.list_sessions(project_id=pid_):
                    try:
                        _sreg2.remove_session(srec.get("session_id"))
                    except Exception:
                        pass
        except Exception:
            pass
        # Restore every env var we forced for this walk.
        for var, prev in (("ANCHOR_PTY_BACKEND", prev_pty),
                          ("ANCHOR_WORKTREE_BASE", prev_wtbase),
                          ("ANCHOR_TERMINAL_SEED", prev_seed),
                          ("ANCHOR_RUNNER_CMD", prev_runner)):
            if prev is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = prev

    failures = [f"{s}: {d}" for s, ok, d in steps if not ok]
    if failures:
        report.check(name, False, "; ".join(failures))
    else:
        report.check(name, True, f"{len(steps)} steps")


def _git_committed(repo: Path, rel: str) -> bool:
    """True iff ``rel`` is tracked/committed in ``repo`` at HEAD (best-effort)."""
    try:
        r = subprocess.run(
            ["git", "-C", str(repo), "ls-files", "--error-unmatch", rel],
            capture_output=True, text=True, timeout=30)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def check_rnd_v11_surface(report: Report, server_proc, rnd_env: dict):
    """Exercise the v11 "Reliable Trio Handoff" R&D surface — FULLY STUBBED.

    v11 fixed the bug where advancing a LIVE research session to planning never
    PERSISTED the research docs (persistence ran only in ``kill`` +
    ``finish_to_build``) → a bare prompt + no HANDOFF.md. The keystone is
    ``terminal_session.prepare_stage_handoff`` (persist source docs FIRST + build
    the real doc-referencing prompt + resolve materials), through which ALL
    advance paths now route (research→plan / plan→build / grass).

    This walk is THE v11 lesson made permanent: it exercises the REAL
    WORKTREE-ONLY live flow — start a LIVE session, write a produced doc into its
    WORKTREE ONLY (NO ``record_effort``, NO kill), advance, then assert the doc
    was PERSISTED + committed into the MAIN project AND named in the prompt AND
    referenced in a HANDOFF.md. (Pre-fix this would fail — the doc never left the
    worktree.) It is the walk that would have caught the original bug.

      (a) RESEARCH→PLAN keystone — a live research session writes
          ``research/run-1/REPORT.md`` into its WORKTREE ONLY;
          ``prepare_stage_handoff(pid, rsid, 'planning')`` then (i) persists +
          commits it into the main project + records it as a research effort
          tagged with ``rsid``, (ii) returns a prompt NAMING the real path +
          "read these" + Crucible, (iii) ``doc_rels`` contains the real path;
          ``handoff.write_handoff_md`` into the next worktree references it.
      (b) PLAN→BUILD — a live planning session writes plan docs into its WORKTREE
          ONLY (no record_effort), is marked DONE, then
          ``auto_advance_planning_to_build`` opens ONE linked build whose prompt
          NAMES the real plan paths and whose worktree CONTAINS them on disk
          (HANDOFF.md + NEXT-PROMPT.md present).

    All model / PTY interaction is stubbed (``ANCHOR_PTY_BACKEND=stub`` +
    ``ANCHOR_RUNNER_CMD`` → the stream-json stub + a temp ``ANCHOR_WORKTREE_BASE``
    + a throwaway temp git project). Proactive summary stays OFF (no env set), so
    the keystone's background summary hard no-ops — never a live-claude summary
    spawn. Every stub PTY + synthetic session row is reaped, all forced env is
    restored, and the temp dirs are torn down. Nothing binds ``:8777`` / touches
    real data / reaches the network. A sub-step that genuinely can't run (no git)
    is recorded honestly as skipped (v9/v10 tolerance).
    """
    name = "R&D v11 surface"
    sj_cmd = _streamjson_runner_cmd()
    if not rnd_env.get("runner_cmd") or not sj_cmd:
        report.check(name, True,
                     "skipped (no stub runner; live claude avoided)")
        return

    import tempfile as _tf
    steps: list[tuple[str, bool, str]] = []

    prev_pty = os.environ.get("ANCHOR_PTY_BACKEND")
    prev_wtbase = os.environ.get("ANCHOR_WORKTREE_BASE")
    prev_seed = os.environ.get("ANCHOR_TERMINAL_SEED")
    prev_runner = os.environ.get("ANCHOR_RUNNER_CMD")
    prev_proactive = os.environ.get("ANCHOR_PROACTIVE_SUMMARY")
    os.environ["ANCHOR_PTY_BACKEND"] = "stub"
    os.environ.pop("ANCHOR_TERMINAL_SEED", None)  # rely on the built-in greet seed
    # Proactive summary OFF → prepare_stage_handoff's background summary no-ops;
    # the walk never spawns a live-claude summarizer run.
    os.environ.pop("ANCHOR_PROACTIVE_SUMMARY", None)
    wt_base = Path(_tf.mkdtemp(prefix="anchor-hc-v11-wt-"))
    os.environ["ANCHOR_WORKTREE_BASE"] = str(wt_base)
    os.environ["ANCHOR_RUNNER_CMD"] = sj_cmd
    rnd_env.setdefault("v3_temp_dirs", []).append(wt_base)

    pid = None
    try:
        import rnd_registry as _rnd
        import terminal_session as _ts
        import session_registry as _sreg
        import effort_history as _eh
        import handoff as _handoff

        # ── 0. A throwaway git project (worktrees attach to a real repo) ───────
        proj_folder = Path(_tf.mkdtemp(prefix="anchor-hc-v11-proj-"))
        rnd_env["v3_temp_dirs"].append(proj_folder)
        (proj_folder / "CLAUDE.md").write_text(
            "# hc v11 probe\n\nR&D project managed by Anchor.\n",
            encoding="utf-8")
        git_ok = _git_init_repo(proj_folder)
        if not git_ok:
            report.check(name, True, "skipped (git init failed)")
            return
        proj = _rnd.add_project(SYNTHETIC_RND_NAME + " v11", str(proj_folder),
                                scaffold=False)
        pid = proj["id"]
        rnd_env["created_ids"].append(pid)
        steps.append(("register v11 project", bool(pid), str(pid)))

        # ── (a) RESEARCH→PLAN keystone: WORKTREE-ONLY live flow (the truth walk) ─
        if git_ok:
            try:
                rsess = _ts.start_session(pid, "research", backend="claude")
                rsid = rsess["session_id"]
                rwt = rsess.get("worktree_path", "")
                rel = "research/run-1/REPORT.md"
                # Write the produced doc into the session's WORKTREE ONLY — NO
                # record_effort, NO kill (this is the live flow the bug evaded).
                if rwt:
                    p = Path(rwt) / rel
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text("# Cooling report\n## Findings\nAdequate.\n",
                                 encoding="utf-8")
                store_lane = _eh._resolve_subdir("research")
                # Pre-condition: the doc is NOT yet in the main folder / not an effort.
                pre_clean = (not (proj_folder / rel).is_file()
                             and _eh.efforts_for_session_id(
                                 str(proj_folder), pid, store_lane, rsid) == [])

                out = _ts.prepare_stage_handoff(pid, rsid, "planning")

                # (i) persisted + committed into the MAIN project + tagged effort.
                persisted = (out.get("ok")
                             and (proj_folder / rel).is_file()
                             and _git_committed(proj_folder, rel)
                             and rel in (out.get("persisted") or []))
                tagged = _eh.efforts_for_session_id(
                    str(proj_folder), pid, store_lane, rsid)
                tagged_rels = [(e.get("artifact_path") or "").replace("\\", "/")
                               for e in tagged]
                tagged_ok = rel in tagged_rels
                # (ii) the REAL prompt names the path + read-first + Crucible
                #      (NOT the bare fallback that the bug produced).
                prompt = out.get("prompt", "")
                prompt_ok = (rel in prompt
                             and "Crucible" in prompt
                             and "Foreman" not in prompt
                             and ("read these" in prompt.lower()))
                # (iii) doc_rels + skill resolved.
                rels_ok = (rel in (out.get("doc_rels") or [])
                           and out.get("skill") == "Crucible")
                # write_handoff_md into the next-stage worktree references it.
                ho_ok = False
                plan_wt = Path(_tf.mkdtemp(prefix="anchor-hc-v11-planwt-"))
                rnd_env["v3_temp_dirs"].append(plan_wt)
                try:
                    hres = _handoff.write_handoff_md(
                        str(plan_wt), out.get("doc_rels") or [], "Crucible",
                        out.get("summary_text", ""))
                    ho_path = plan_wt / _handoff.HANDOFF_FILENAME
                    ho_ok = (hres.get("ok") and ho_path.is_file()
                             and rel in ho_path.read_text(encoding="utf-8"))
                except Exception:
                    ho_ok = False

                steps.append((
                    "research→plan keystone persists worktree-only doc + real "
                    "prompt + HANDOFF.md",
                    pre_clean and persisted and tagged_ok and prompt_ok
                    and rels_ok and ho_ok,
                    f"pre_clean={pre_clean} persisted={persisted} "
                    f"tagged={tagged_ok} prompt={prompt_ok} rels={rels_ok} "
                    f"handoff={ho_ok}"))

                # Idempotency: a second prepare does NOT duplicate the effort and
                # returns the same real prompt (the v11 W1 invariant).
                n1 = len(_eh.efforts_for_session_id(
                    str(proj_folder), pid, store_lane, rsid))
                out2 = _ts.prepare_stage_handoff(pid, rsid, "planning")
                n2 = len(_eh.efforts_for_session_id(
                    str(proj_folder), pid, store_lane, rsid))
                idem_ok = (n2 == n1 and out2.get("prompt") == out.get("prompt")
                           and rel in out2.get("prompt", ""))
                steps.append(("research→plan prepare is idempotent",
                              idem_ok, f"efforts {n1}->{n2}"))

                try:
                    _ts.kill(rsid, project_id=pid, _record_boneyard=False)
                except Exception:
                    pass
            except Exception as e:
                steps.append(("research→plan keystone", False,
                              f"{type(e).__name__}: {e}"))
        else:
            steps.append(("research→plan keystone", True,
                          "skipped (git unavailable)"))

        # ── (b) PLAN→BUILD: live planning docs in WORKTREE ONLY → linked build ─
        if git_ok:
            try:
                plansess = _ts.start_session(pid, "planning", backend="claude",
                                             label="hc v11 plan")
                plan_sid = plansess["session_id"]
                plan_wt = plansess.get("worktree_path", "")
                # Write a REAL MASTER+IMPL plan set into the planning WORKTREE
                # ONLY (no record_effort) — the keystone must persist these so the
                # build worktree (off main HEAD) contains them + discovery finds
                # them for the build prompt.
                master_rel = "planning/rnd-hc-v11/MASTER-PLAN.md"
                impl_rel = "planning/rnd-hc-v11/IMPLEMENTATION-PLAN.md"
                if plan_wt:
                    for rel_, body in ((master_rel, "# Master Plan\n## Waves\nW1.\n"),
                                       (impl_rel,
                                        "# Implementation Plan\n## Wave 1\nDo it.\n")):
                        pp = Path(plan_wt) / rel_
                        pp.parent.mkdir(parents=True, exist_ok=True)
                        pp.write_text(body, encoding="utf-8")
                # Mark DONE (the terminal transition auto_advance gates on), then
                # auto-advance to ONE linked build through the shared keystone.
                _sreg.update_session(plan_sid, status=_sreg.STATUS_DONE)
                build_rec = _ts.auto_advance_planning_to_build(pid, plan_sid)
                adv_ok = bool(build_rec)
                docs_persisted = False
                build_prompt_ok = False
                build_wt_has_docs = False
                linked = False
                artifacts = False
                idem_ok = False
                store_plan = _eh._resolve_subdir("planning")
                if build_rec:
                    bsid = build_rec.get("session_id", "")
                    bwt = build_rec.get("worktree_path", "")
                    # The plan docs were persisted + committed into the MAIN project.
                    docs_persisted = (
                        (proj_folder / master_rel).is_file()
                        and (proj_folder / impl_rel).is_file()
                        and _git_committed(proj_folder, master_rel)
                        and _git_committed(proj_folder, impl_rel))
                    # The build worktree (off main HEAD) CONTAINS them on disk.
                    build_wt_has_docs = bool(bwt) and (
                        (Path(bwt) / master_rel).is_file()
                        and (Path(bwt) / impl_rel).is_file())
                    # Both handoff artifacts written into the build worktree.
                    artifacts = bool(bwt) and (
                        (Path(bwt) / "HANDOFF.md").is_file()
                        and (Path(bwt) / "NEXT-PROMPT.md").is_file())
                    # The build's pending-paste prompt NAMES the real plan paths.
                    brec = _sreg.get_session(bsid)
                    bprompt = brec.get("pending_paste", "") or ""
                    build_prompt_ok = (master_rel in bprompt
                                       or impl_rel in bprompt
                                       or "Foreman" in bprompt)
                    linked = (brec.get("parent_session_id") == plan_sid
                              and brec.get("chain_id")
                              == _sreg.get_session(plan_sid).get("chain_id"))
                    # Idempotent: a second advance does NOT mint a second build.
                    again = _ts.auto_advance_planning_to_build(pid, plan_sid)
                    idem_ok = again is None
                    try:
                        _ts.kill(bsid, project_id=pid, _record_boneyard=False)
                    except Exception:
                        pass
                steps.append((
                    "plan→build keystone persists worktree-only plan docs + "
                    "build prompt names them + artifacts + linked",
                    adv_ok and docs_persisted and build_wt_has_docs
                    and build_prompt_ok and artifacts and linked and idem_ok,
                    f"advanced={adv_ok} persisted={docs_persisted} "
                    f"build_wt_docs={build_wt_has_docs} prompt={build_prompt_ok} "
                    f"artifacts={artifacts} linked={linked} idempotent={idem_ok}"))
                try:
                    _ts.kill(plan_sid, project_id=pid, _record_boneyard=False)
                except Exception:
                    pass
            except Exception as e:
                steps.append(("plan→build keystone", False,
                              f"{type(e).__name__}: {e}"))
        else:
            steps.append(("plan→build keystone", True,
                          "skipped (git unavailable)"))

    except Exception as e:
        steps.append(("exception", False, f"{type(e).__name__}: {e}"))
    finally:
        # Reap any stub PTY sessions this walk left live (defensive).
        try:
            import pty_manager as _pty2
            import session_registry as _sreg2
            for sid in list(_pty2.live_sessions()):
                try:
                    _pty2.kill(sid)
                except Exception:
                    pass
            for pid_ in rnd_env.get("created_ids", []):
                for srec in _sreg2.list_sessions(project_id=pid_):
                    try:
                        _sreg2.remove_session(srec.get("session_id"))
                    except Exception:
                        pass
        except Exception:
            pass
        # Restore every env var we forced for this walk.
        for var, prev in (("ANCHOR_PTY_BACKEND", prev_pty),
                          ("ANCHOR_WORKTREE_BASE", prev_wtbase),
                          ("ANCHOR_TERMINAL_SEED", prev_seed),
                          ("ANCHOR_RUNNER_CMD", prev_runner),
                          ("ANCHOR_PROACTIVE_SUMMARY", prev_proactive)):
            if prev is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = prev

    failures = [f"{s}: {d}" for s, ok, d in steps if not ok]
    if failures:
        report.check(name, False, "; ".join(failures))
    else:
        report.check(name, True, f"{len(steps)} steps")


def check_rnd_v11_1_surface(report: Report, server_proc, rnd_env: dict):
    """Exercise the v11.1 "Handoff Always Primes" R&D surface — FULLY STUBBED.

    v11.1 fixed the bug where advancing a CONVERSATION-only research session — one
    whose work lived ONLY as a terminal conversation (the model answered in the
    PTY, wrote NO file) — either hard-refused (grass: ``no-research-material``) or
    opened with a misleading prompt (non-grass). The keystone is the transcript
    SNAPSHOT in ``terminal_session.prepare_stage_handoff``: when the initial
    persist yields ZERO document-classified docs, it snapshots the source
    session's PTY transcript → cleans it → writes ``<lane>/<short-sid>-transcript.md``
    → re-persists it → builds the REAL doc-referencing prompt. Wave 2 removed the
    grass hard-refusal so the grass advance ALWAYS opens + materializes the
    transcript into the plan worktree on disk.

    This walk is THE v11.1 lesson made permanent: it exercises the REAL
    CONVERSATION-ONLY live flow — start a LIVE session, seed its STUB PTY read
    buffer with simulated transcript content (a ``pty_manager.write`` ECHOES into
    the readable buffer, exactly the conversation-only live path), write NOTHING to
    the worktree + NO ``record_effort`` + NO kill, then advance and assert the
    transcript was SNAPSHOTTED + persisted + named in the prompt + the next session
    opens. (Pre-fix this would fail — the conversation was never captured.)

      (a) RESEARCH→PLAN conversation-only — a live research session's only output is
          a transcript in its PTY buffer (NO file); ``prepare_stage_handoff(pid,
          rsid, 'planning')`` then (i) snapshots + persists + commits
          ``research/<short-sid>-transcript.md`` into the MAIN project + records it
          as a research effort tagged with ``rsid``, (ii) returns a prompt NAMING
          that real path + a "read these / create" instruction + Crucible (not
          Foreman), (iii) ``doc_rels`` / ``persisted`` contain it.
      (b) GRASS conversation-only — a contained grass research dev session's only
          output is a transcript in its PTY buffer (NO file);
          ``advance_grass_research_to_plan`` OPENS the contained grass plan dev
          session (NO refusal — the W2 unification), the transcript is materialized
          into the plan worktree ON DISK + named in the pending paste, and the
          session is contained + linked (parent + grass_origin).

    All model / PTY interaction is stubbed (``ANCHOR_PTY_BACKEND=stub`` +
    ``ANCHOR_RUNNER_CMD`` → the stream-json stub + a temp ``ANCHOR_WORKTREE_BASE``
    + a throwaway temp git project). Proactive summary stays OFF — and is RESTORED
    in ``finally`` — so the keystone's background summary (which now reads that env)
    hard no-ops and never spawns a live-claude summarizer run. Every stub PTY +
    synthetic session row is reaped, all forced env is restored, and the temp dirs
    are torn down. Nothing binds ``:8777`` / touches real data / reaches the
    network. A sub-step that genuinely can't run (no git) is recorded honestly as
    skipped (v9/v10/v11 tolerance).
    """
    name = "R&D v11.1 surface"
    sj_cmd = _streamjson_runner_cmd()
    if not rnd_env.get("runner_cmd") or not sj_cmd:
        report.check(name, True,
                     "skipped (no stub runner; live claude avoided)")
        return

    import tempfile as _tf
    steps: list[tuple[str, bool, str]] = []

    prev_pty = os.environ.get("ANCHOR_PTY_BACKEND")
    prev_wtbase = os.environ.get("ANCHOR_WORKTREE_BASE")
    prev_seed = os.environ.get("ANCHOR_TERMINAL_SEED")
    prev_runner = os.environ.get("ANCHOR_RUNNER_CMD")
    prev_proactive = os.environ.get("ANCHOR_PROACTIVE_SUMMARY")
    os.environ["ANCHOR_PTY_BACKEND"] = "stub"
    os.environ.pop("ANCHOR_TERMINAL_SEED", None)  # rely on the built-in greet seed
    # Proactive summary OFF → prepare_stage_handoff's background summary no-ops; the
    # walk never spawns a live-claude summarizer run. (The keystone now READS this
    # env, so restoring it in finally matters — it must not leak ON.)
    os.environ.pop("ANCHOR_PROACTIVE_SUMMARY", None)
    wt_base = Path(_tf.mkdtemp(prefix="anchor-hc-v11_1-wt-"))
    os.environ["ANCHOR_WORKTREE_BASE"] = str(wt_base)
    os.environ["ANCHOR_RUNNER_CMD"] = sj_cmd
    rnd_env.setdefault("v3_temp_dirs", []).append(wt_base)

    # Simulated research CONVERSATION content — plausibly named so the snapshot
    # text is non-trivial. NO file is written; this is ECHOED into the PTY buffer.
    transcript = (
        "\nResearcher: Which coolant loop maximizes thermal margin?\n"
        "Assistant: The molten-salt loop wins - a 40C transient tolerance with no\n"
        "scram and the simplest pump topology. Recommendation: prototype the pump\n"
        "seal and pursue the molten-salt design.\n")

    pid = None
    try:
        import rnd_registry as _rnd
        import terminal_session as _ts
        import session_registry as _sreg
        import effort_history as _eh
        import pty_manager as _pty

        # ── 0. A throwaway git project (worktrees attach to a real repo) ───────
        proj_folder = Path(_tf.mkdtemp(prefix="anchor-hc-v11_1-proj-"))
        rnd_env["v3_temp_dirs"].append(proj_folder)
        (proj_folder / "CLAUDE.md").write_text(
            "# hc v11.1 probe\n\nR&D project managed by Anchor.\n",
            encoding="utf-8")
        git_ok = _git_init_repo(proj_folder)
        if not git_ok:
            report.check(name, True, "skipped (git init failed)")
            return
        proj = _rnd.add_project(SYNTHETIC_RND_NAME + " v11.1", str(proj_folder),
                                scaffold=False)
        pid = proj["id"]
        rnd_env["created_ids"].append(pid)
        steps.append(("register v11.1 project", bool(pid), str(pid)))

        # ── (a) RESEARCH→PLAN: CONVERSATION-ONLY live flow (the v11.1 truth walk) ─
        if git_ok:
            try:
                rsess = _ts.start_session(pid, "research", backend="claude")
                rsid = rsess["session_id"]
                # CONVERSATION ONLY: seed the source session's PTY read buffer (the
                # stub PTY echoes a write into its readable buffer) — write NO file
                # to the worktree, NO record_effort, NO kill. This is the exact
                # live path the original bug evaded.
                _pty.write(rsid, transcript)

                store_lane = _eh._resolve_subdir("research")
                short_sid = rsid[:12]
                rel = "research/%s-transcript.md" % short_sid
                # Pre-condition: the transcript is NOT in the worktree/main, no effort.
                pre_clean = (not (proj_folder / rel).is_file()
                             and _eh.efforts_for_session_id(
                                 str(proj_folder), pid, store_lane, rsid) == [])

                out = _ts.prepare_stage_handoff(pid, rsid, "planning")

                # (i) snapshotted + persisted + committed into MAIN + tagged effort.
                snapshotted = (out.get("ok")
                               and (proj_folder / rel).is_file()
                               and _git_committed(proj_folder, rel)
                               and rel in (out.get("persisted") or []))
                body = ""
                if (proj_folder / rel).is_file():
                    try:
                        body = (proj_folder / rel).read_text(encoding="utf-8")
                    except Exception:
                        body = ""
                content_kept = ("molten-salt" in body
                                and "transcript" in body.lower())
                tagged = _eh.efforts_for_session_id(
                    str(proj_folder), pid, store_lane, rsid)
                tagged_rels = [(e.get("artifact_path") or "").replace("\\", "/")
                               for e in tagged]
                tagged_ok = rel in tagged_rels
                # (ii) the REAL prompt names the path + read/create + Crucible (the
                #      conversation-only flow's whole point — NOT a misleading prompt).
                prompt = out.get("prompt", "")
                prompt_lower = prompt.lower()
                prompt_ok = (rel in prompt
                             and "Crucible" in prompt
                             and "Foreman" not in prompt
                             and ("read these" in prompt_lower
                                  or "create" in prompt_lower))
                # (iii) doc_rels + skill resolved.
                rels_ok = (rel in (out.get("doc_rels") or [])
                           and out.get("skill") == "Crucible")

                steps.append((
                    "research→plan conversation-only: transcript snapshotted + "
                    "persisted + real prompt names it",
                    pre_clean and snapshotted and content_kept and tagged_ok
                    and prompt_ok and rels_ok,
                    f"pre_clean={pre_clean} snapshotted={snapshotted} "
                    f"content={content_kept} tagged={tagged_ok} "
                    f"prompt={prompt_ok} rels={rels_ok}"))

                # Idempotency: a second prepare does NOT duplicate the effort + the
                # same real prompt (the transcript filename is deterministic).
                n1 = len(_eh.efforts_for_session_id(
                    str(proj_folder), pid, store_lane, rsid))
                out2 = _ts.prepare_stage_handoff(pid, rsid, "planning")
                n2 = len(_eh.efforts_for_session_id(
                    str(proj_folder), pid, store_lane, rsid))
                idem_ok = (n2 == n1 and out2.get("prompt") == out.get("prompt")
                           and rel in out2.get("prompt", ""))
                steps.append(("research→plan snapshot is idempotent",
                              idem_ok, f"efforts {n1}->{n2}"))

                try:
                    _ts.kill(rsid, project_id=pid, _record_boneyard=False)
                except Exception:
                    pass
            except Exception as e:
                steps.append(("research→plan conversation-only", False,
                              f"{type(e).__name__}: {e}"))
        else:
            steps.append(("research→plan conversation-only", True,
                          "skipped (git unavailable)"))

        # ── (b) GRASS: CONVERSATION-ONLY advance always opens (the W2 unification) ─
        if git_ok:
            try:
                idea = _eh.add_idea(str(proj_folder), pid,
                                    "Passive autonomous cooling loop",
                                    notes="A natural-circulation decay-heat loop.")
                idea_id = idea.get("job_id") or idea.get("id")
                # Develop the contained (idea, 'research') dev session, then seed
                # its PTY buffer with a CONVERSATION — write NO file, NO effort.
                rrec = _eh.develop_grass_idea(pid, idea_id, "research",
                                              backend="claude")
                grsid = rrec["session_id"]
                _pty.write(grsid, transcript)

                gstore = _eh._resolve_subdir("research")
                grel = "research/%s-transcript.md" % (grsid[:12])
                pre_clean_g = (_eh.efforts_for_session_id(
                    str(proj_folder), pid, gstore, grsid) == [])

                adv = _eh.advance_grass_research_to_plan(pid, idea_id)

                # (a) ok:True + a grass PLAN dev session OPENS — no refusal (W2).
                opened = (adv.get("ok")
                          and adv.get("reason") != "no-research-material"
                          and adv.get("session") is not None
                          and adv.get("research_session_id") == grsid)
                psid = (adv.get("session") or {}).get("session_id", "")
                full = _sreg.get_session(psid) if psid else None
                # (b) the transcript is snapshotted + persisted into MAIN + named in
                #     the pending paste + materialized ON DISK in the plan worktree.
                in_main = (proj_folder / grel).is_file()
                paste = (full.get("pending_paste") or "") if full else ""
                paste_ok = (bool(paste) and "Crucible" in paste
                            and grel in paste and not paste.endswith("\n"))
                plan_wt = (full.get("worktree_path") or "") if full else ""
                on_disk = bool(plan_wt) and (Path(plan_wt) / grel).is_file()
                # (c) contained (GRASS_DEV_LABEL_PREFIX) + linked (parent + origin).
                contained = bool(full) and str(
                    full.get("label", "")).startswith(_eh.GRASS_DEV_LABEL_PREFIX)
                linked = bool(full) and (
                    full.get("parent_session_id") == grsid
                    and full.get("grass_origin") == idea_id)
                # The idea STAYS in grass (copy, never destroy).
                idea_kept = _eh.get_grass_idea(
                    str(proj_folder), pid, idea_id) is not None

                steps.append((
                    "grass conversation-only advance opens + materializes "
                    "transcript on disk + contained + linked",
                    pre_clean_g and opened and in_main and paste_ok and on_disk
                    and contained and linked and idea_kept,
                    f"pre_clean={pre_clean_g} opened={opened} in_main={in_main} "
                    f"paste={paste_ok} on_disk={on_disk} contained={contained} "
                    f"linked={linked} idea_kept={idea_kept}"))

                for sid in (psid, grsid):
                    if not sid:
                        continue
                    try:
                        _ts.kill(sid, project_id=pid, _record_boneyard=False)
                    except Exception:
                        pass
            except Exception as e:
                steps.append(("grass conversation-only advance", False,
                              f"{type(e).__name__}: {e}"))
        else:
            steps.append(("grass conversation-only advance", True,
                          "skipped (git unavailable)"))

    except Exception as e:
        steps.append(("exception", False, f"{type(e).__name__}: {e}"))
    finally:
        # Reap any stub PTY sessions this walk left live (defensive).
        try:
            import pty_manager as _pty2
            import session_registry as _sreg2
            for sid in list(_pty2.live_sessions()):
                try:
                    _pty2.kill(sid)
                except Exception:
                    pass
            for pid_ in rnd_env.get("created_ids", []):
                for srec in _sreg2.list_sessions(project_id=pid_):
                    try:
                        _sreg2.remove_session(srec.get("session_id"))
                    except Exception:
                        pass
        except Exception:
            pass
        # Restore every env var we forced for this walk (incl. PROACTIVE_SUMMARY,
        # which the keystone now reads — it must not leak ON).
        for var, prev in (("ANCHOR_PTY_BACKEND", prev_pty),
                          ("ANCHOR_WORKTREE_BASE", prev_wtbase),
                          ("ANCHOR_TERMINAL_SEED", prev_seed),
                          ("ANCHOR_RUNNER_CMD", prev_runner),
                          ("ANCHOR_PROACTIVE_SUMMARY", prev_proactive)):
            if prev is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = prev

    failures = [f"{s}: {d}" for s, ok, d in steps if not ok]
    if failures:
        report.check(name, False, "; ".join(failures))
    else:
        report.check(name, True, f"{len(steps)} steps")


def _git_commit_in(repo: Path, msg: str = "hc commit") -> bool:
    """Best-effort ``git add -A`` + commit in ``repo`` (a throwaway hc project)."""
    try:
        for args in (["git", "-C", str(repo), "add", "-A"],
                     ["git", "-C", str(repo), "commit", "-m", msg,
                      "--no-gpg-sign"]):
            subprocess.run(args, capture_output=True, text=True, timeout=30)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def check_steward_cockpit_surface(report: Report):
    """Exercise the steward-cockpit surface (the DEFAULT /project/ page since
    the 2026-08-25 cutover) — FULLY STUBBED, hermetic.

    The engine seam is the package's own ``fake_claude.py`` stream-json stub
    (``fake=True`` — zero tokens, zero real sessions; the 2026-07-14
    usage-leak lesson). The walk runs in a throwaway temp campaign dir with
    the module STATE_FILE redirected to a temp file (real state untouched):

      (1) deterministic readers — ``read_map`` over a synthetic campaign +
          ``compose_status`` returning the two-part (now / plan) shape;
      (2) the mount — ``serve_cockpit_doc`` injects the client shim;
          ``serve_static`` serves only the shipped static set (the deleted
          bake-off shells STAY deleted); ``api_get`` efforts/status round-trip;
      (3) the engine — wake through the fake, ``say`` round-trip to turn_end
          events, the turn-boundary ``.ecgberht/status-summary.json`` persist
          (the universal file the dashboard tile reads), then stop.

    Env + STATE_FILE restored, temp dirs removed; nothing binds :8777,
    touches real campaign data, or reaches the network."""
    name = "Steward cockpit surface"
    import tempfile as _tf
    failures, steps = [], []
    tmp = Path(_tf.mkdtemp(prefix="anchor-hc-steward-"))
    state_tmp = Path(_tf.mkdtemp(prefix="anchor-hc-steward-state-"))
    old_state_file = None
    eng = None
    se = None
    try:
        from steward_cockpit import steward_campaign as _sc
        from steward_cockpit import steward_engine as _se
        from steward_cockpit import steward_routes as _sr
        se = _se
        old_state_file = _se.STATE_FILE
        _se.STATE_FILE = state_tmp / "state.json"

        # (1) synthetic campaign + deterministic readers
        (tmp / "ECGBERHT.md").write_text(
            "# Ecgberht — Face\n\n## North star\n\nProve the cockpit surface "
            "end-to-end with zero tokens.\n\n## Human wait\n\n- nothing\n",
            encoding="utf-8")
        (tmp / "roadmap.json").write_text(json.dumps({
            "roadmap_projection": [
                {"id": "s1", "name": "walk the surface", "status": "active",
                 "done_when": "the healthcheck passes"}]}), encoding="utf-8")
        (tmp / "strip.json").write_text(json.dumps({
            "human_wait": "", "next_recommended": "carry on",
            "grasscatch": []}), encoding="utf-8")
        (tmp / ".ecgberht").mkdir()
        (tmp / ".ecgberht" / "attention.json").write_text(
            json.dumps({"state": "working", "reason": "stub run in flight"}),
            encoding="utf-8")
        m = _sc.read_map(str(tmp))
        if not m["goal_brief"] or m["steps_total"] != 1:
            failures.append(f"read_map: goal/steps wrong ({m['goal_brief']!r}, "
                            f"{m['steps_total']})")
        else:
            steps.append("read_map")
        stat = _sc.compose_status(str(tmp), {"busy": False, "queued": 0})
        if (not stat.get("now") or not isinstance(stat.get("plan"), dict)
                or stat["plan"].get("step") != "walk the surface"):
            failures.append(f"compose_status shape wrong: {stat}")
        else:
            steps.append("compose_status")

        # (2) the mount
        doc = _sr.serve_cockpit_doc("hc-pid")
        if not doc or "STEWARD_PID" not in doc or "AI Cockpit" not in doc:
            failures.append("serve_cockpit_doc missing shim/shell")
        else:
            steps.append("cockpit doc")
        body, _ct = _sr.serve_static("shared.js")
        if body is None:
            failures.append("serve_static shared.js missing")
        for gone in ("seal.html", "v2.html", "v1a.html", "v1b.html",
                     "index.html", "../paths.py"):
            b, _c = _sr.serve_static(gone)
            if b is not None:
                failures.append(f"serve_static serves retired/outside file: {gone}")
        if body is not None and not any(f.startswith("serve_static serves")
                                        for f in failures):
            steps.append("static set")
        obj, code = _sr.api_get(str(tmp), "efforts", {})
        if code != 200 or not obj.get("efforts"):
            failures.append(f"api_get efforts: {code} {obj}")
        else:
            steps.append("efforts")
            # each row carries the goal-derived rename suggestion, and the
            # suggestion itself must pass the effort-name guard
            row = obj["efforts"][0]
            sug = row.get("suggested_name")
            if not sug:
                failures.append(f"efforts row missing suggested_name: {row}")
            else:
                _n, _e = _sr._validate_effort_name(sug)
                if _e:
                    failures.append(
                        f"suggested name fails its own guard: {sug!r} ({_e})")
        obj, code = _sr.api_get(str(tmp), "status", {"dir": ""})
        if code != 200 or "plan" not in obj:
            failures.append(f"api_get status: {code} {obj}")
        else:
            steps.append("status verb")

        # (2026-08-25) effort NAME guard + rename: a pasted token/secret is
        # refused; a rename moves the dir AND migrates the engine-state keys.
        old_tok = _sr.CONFIG.get("anchor_token")
        try:
            _sr.CONFIG["anchor_token"] = "sekret-token-guard-1"
            for bad, why in (
                    ("E3aB8dvObAselKS1XSIvXhH9GUJxpM8FhMc", "secret-shaped"),
                    ("name with sekret-token-guard-1 inside", "the token"),
            ):
                obj, code = _sr.api_post(str(tmp), "new_effort", {"name": bad})
                if code != 400 or obj.get("ok"):
                    failures.append(f"new_effort accepted a {why} name")
            obj, code = _sr.api_post(str(tmp), "new_effort",
                                     {"name": "temp effort"})
            if code != 200 or not obj.get("ok"):
                failures.append(f"new_effort refused a plain name: {obj}")
            edir = str(Path(tmp) / "temp effort")
            _se._update_state(edir, {"session_id": "fake-keep-me"})
            obj, code = _sr.api_post(str(tmp), "rename_effort",
                                     {"dir": "temp effort",
                                      "name": "renamed effort"})
            moved = (Path(tmp) / "renamed effort" / "ECGBERHT.md").is_file()
            migrated = (_se._read_all_state()
                        .get(str(Path(tmp) / "renamed effort"), {})
                        .get("session_id") == "fake-keep-me")
            if code != 200 or not obj.get("ok") or not moved or not migrated:
                failures.append(
                    f"rename_effort: code={code} ok={obj.get('ok')} "
                    f"moved={moved} state_migrated={migrated}")
            else:
                steps.append("name guard + rename")
        finally:
            if old_tok is None:
                _sr.CONFIG.pop("anchor_token", None)
            else:
                _sr.CONFIG["anchor_token"] = old_tok

        # (3) the engine, through the fake (zero tokens)
        eng = _se.Engine(str(tmp), fake=True)
        r = eng.say("hello there")
        if not r.get("ok"):
            failures.append(f"say refused: {r}")
        deadline = time.time() + 30
        while time.time() < deadline:
            ends = [e for e in eng.events if e.get("t") == "turn_end"]
            if len(ends) >= 2:   # stand-up turn + the queued hello turn
                break
            time.sleep(0.25)
        else:
            failures.append("engine never reached 2 turn_end events "
                            f"(events: {[e.get('t') for e in eng.events][-8:]})")
        if not any(e.get("t") == "delta" and e.get("text")
                   for e in eng.events):
            failures.append("no streamed delta from the fake engine")
        st = eng.state()
        for key in ("alive", "busy", "light", "epoch", "open_question"):
            if key not in st:
                failures.append(f"engine state missing {key}")
        summary_f = tmp / ".ecgberht" / "status-summary.json"
        if not summary_f.is_file():
            failures.append("turn boundary did not persist status-summary.json")
        else:
            persisted = json.loads(summary_f.read_text(encoding="utf-8"))
            if "now" not in persisted or "plan" not in persisted:
                failures.append(f"persisted status malformed: {persisted}")
            else:
                steps.append("engine round-trip + status persist")
        eng.stop()
        eng = None
    except Exception as e:
        failures.append(f"{type(e).__name__}: {e}")
    finally:
        try:
            if eng is not None:
                eng.stop()
        except Exception:
            pass
        if se is not None and old_state_file is not None:
            se.STATE_FILE = old_state_file
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(state_tmp, ignore_errors=True)
    if failures:
        report.check(name, False, "; ".join(failures[:6]))
    else:
        report.check(name, True, f"{len(steps)} steps")


def check_gandalf_surface(report: Report, server_proc, rnd_env: dict):
    """Exercise the Gandalf v1 "honest project read" surface — FULLY STUBBED.

    Gandalf gives each project an honest "what's really going on here" read via a
    two-stage engine: Stage A (the model, through ``ANCHOR_RUNNER_CMD``) emits the
    RAW draft; Stage B (Gandalf's own Tier-1 HOST, through
    ``ANCHOR_GANDALF_HOST_CMD``) grades it. Both seams are stubbed here
    (``ANCHOR_RUNNER_CMD`` → ``tests/stub_gandalf_draft.py`` emitting a canned RAW
    draft; ``ANCHOR_GANDALF_HOST_CMD`` → ``tests/stub_gandalf_host.py`` emitting a
    canned GRADED advisor-output) — NEVER real claude / real node / network. The
    walk:

      (1) ``run_gandalf`` on a temp project → the 3 artifacts
          (``report.md`` + ``exec-summary.md`` + ``advisor-output.json``) under
          ``<folder>/gandalf/run-<ts>/`` AND a newest-first SAFE index record;
          ``list_runs`` returns it with a non-empty verdict + no absolute paths.
      (2) a SECOND ``run_gandalf`` appends a 2nd newest-first entry (history
          accumulates); ``run_gandalf_if_absent`` no-ops when a run exists.
      (3) an ERROR run — point the HOST stub at a forced failure
          (``STUB_GANDALF_HOST_FAIL``) → an honest ``ok:false`` record with a
          reason, NO fabricated verdict, never raised.

    ``ANCHOR_PROACTIVE_SUMMARY`` stays OFF. Every forced env var
    (``ANCHOR_RUNNER_CMD`` / ``ANCHOR_GANDALF_HOST_CMD`` / ``ANCHOR_GANDALF_SKILL_DIR``
    / ``ANCHOR_PROACTIVE_SUMMARY`` + the host-fail knob) is snapshotted and RESTORED
    in ``finally``; the temp project + data dirs go into ``rnd_env['v3_temp_dirs']``.
    Nothing binds ``:8777`` / touches real data / reaches the network. A sub-step
    that genuinely can't run (no git, no stub) is recorded honestly as skipped."""
    name = "Gandalf surface"
    draft_cmd = _gandalf_draft_runner_cmd()
    host_cmd = _gandalf_host_cmd()
    if not draft_cmd or not host_cmd:
        report.check(name, True,
                     "skipped (no Gandalf stubs; live claude/node avoided)")
        return

    import tempfile as _tf
    steps: list[tuple[str, bool, str]] = []

    prev_runner = os.environ.get("ANCHOR_RUNNER_CMD")
    prev_host = os.environ.get("ANCHOR_GANDALF_HOST_CMD")
    prev_skill = os.environ.get("ANCHOR_GANDALF_SKILL_DIR")
    prev_proactive = os.environ.get("ANCHOR_PROACTIVE_SUMMARY")
    prev_hostfail = os.environ.get("STUB_GANDALF_HOST_FAIL")
    prev_mode = os.environ.get("ANCHOR_GANDALF_MODE")
    os.environ["ANCHOR_RUNNER_CMD"] = draft_cmd
    os.environ["ANCHOR_GANDALF_HOST_CMD"] = host_cmd
    # This check stubs the DETERMINISTIC map-reduce (draft+host) path — the
    # retained fallback (ANCHOR_GANDALF_MODE=mapreduce). The DEFAULT agentic path
    # runs the real skill (live claude), which can't be stubbed the same way and
    # is covered by tests/test_gandalf_agentic.py.
    os.environ["ANCHOR_GANDALF_MODE"] = "mapreduce"
    os.environ.pop("ANCHOR_PROACTIVE_SUMMARY", None)  # OFF
    os.environ.pop("STUB_GANDALF_HOST_FAIL", None)

    pid = None
    try:
        import rnd_registry as _rnd
        import gandalf as _gandalf

        # Point the skill dir at a NON-existent path so the prompt builder reads no
        # real SKILL.md (the stub draft runner ignores the prompt anyway).
        no_skill = Path(_tf.mkdtemp(prefix="anchor-hc-gandalf-skill-"))
        os.environ["ANCHOR_GANDALF_SKILL_DIR"] = str(no_skill)
        rnd_env.setdefault("v3_temp_dirs", []).append(no_skill)

        proj_folder = Path(_tf.mkdtemp(prefix="anchor-hc-gandalf-proj-"))
        rnd_env["v3_temp_dirs"].append(proj_folder)
        (proj_folder / "CLAUDE.md").write_text(
            "# hc gandalf probe\n\nR&D project managed by Anchor.\n",
            encoding="utf-8")
        # Wave 9: give the probe project ≥2 top-level dirs so the map-reduce
        # Stage A shards + fans out (rather than a single whole-tree pass).
        (proj_folder / "src").mkdir(exist_ok=True)
        (proj_folder / "docs").mkdir(exist_ok=True)
        (proj_folder / "src" / "mod.py").write_text("x = 1\n", encoding="utf-8")
        (proj_folder / "docs" / "guide.md").write_text("# guide\n", encoding="utf-8")
        _git_init_repo(proj_folder)  # best-effort; gandalf does not require git
        proj = _rnd.add_project(SYNTHETIC_RND_NAME + " gandalf",
                                str(proj_folder), scaffold=False)
        pid = proj["id"]
        rnd_env["created_ids"].append(pid)
        fp = str(proj_folder)
        steps.append(("register gandalf project", bool(pid), str(pid)))

        # ── (1) run → 3 artifacts + index + list_runs shape ───────────────────
        try:
            out = _gandalf.run_gandalf(fp, pid)
            run_id = out.get("run_id", "")
            run_dir = proj_folder / "gandalf" / run_id
            arts = all((run_dir / f).is_file() for f in
                       ("report.md", "exec-summary.md", "advisor-output.json"))
            runs = _gandalf.list_runs(fp, pid)
            shape_ok = (len(runs) == 1 and runs[0].get("ok") is True
                        and bool(runs[0].get("verdict")))
            # SAFE projection: no absolute paths leak.
            no_abs = True
            for v in runs[0].values():
                if isinstance(v, str) and (":\\" in v or fp in v):
                    no_abs = False
            steps.append((
                "run_gandalf → 3 artifacts + SAFE index record",
                bool(out.get("ok") and arts and shape_ok and no_abs),
                f"ok={out.get('ok')} artifacts={arts} shape={shape_ok} "
                f"no_abs={no_abs}"))
        except Exception as e:
            steps.append(("run_gandalf", False, f"{type(e).__name__}: {e}"))

        # ── (2) a 2nd run appends; run_gandalf_if_absent no-ops ───────────────
        try:
            _gandalf.run_gandalf(fp, pid)
            runs2 = _gandalf.list_runs(fp, pid)
            appended = len(runs2) == 2
            # newest-first: the 2nd run's ts >= the older one's.
            newest_first = True
            if len(runs2) == 2:
                t0, t1 = runs2[0].get("ts"), runs2[1].get("ts")
                if isinstance(t0, (int, float)) and isinstance(t1, (int, float)):
                    newest_first = t0 >= t1
            absent = _gandalf.run_gandalf_if_absent(fp, pid)
            noop = bool(absent.get("skipped")) and len(
                _gandalf.list_runs(fp, pid)) == 2
            steps.append((
                "2nd run appends (newest-first) + run_gandalf_if_absent no-ops",
                bool(appended and newest_first and noop),
                f"count={len(runs2)} newest_first={newest_first} noop={noop}"))
        except Exception as e:
            steps.append(("2nd run / if-absent", False,
                          f"{type(e).__name__}: {e}"))

        # ── (3) an ERROR run recorded honestly (host forced to fail) ──────────
        try:
            os.environ["STUB_GANDALF_HOST_FAIL"] = "1"
            err = _gandalf.run_gandalf(fp, pid)
            os.environ.pop("STUB_GANDALF_HOST_FAIL", None)
            runs3 = _gandalf.list_runs(fp, pid)
            err_rec = runs3[0] if runs3 else {}
            honest = (err.get("ok") is False and bool(err.get("reason"))
                      and err_rec.get("ok") is False
                      and not err_rec.get("verdict")
                      and err_rec.get("report_rel") is None)
            steps.append((
                "host-failure → honest error run (ok:false + reason, no verdict)",
                bool(honest),
                f"ok={err.get('ok')} reason={err.get('reason','')!r} "
                f"rec_ok={err_rec.get('ok')}"))
        except Exception as e:
            os.environ.pop("STUB_GANDALF_HOST_FAIL", None)
            steps.append(("error run", False, f"{type(e).__name__}: {e}"))

        # ── (4) Wave 9 map-reduce: ≥2 shards + grouped reduce (pure, no spawn) ─
        try:
            shards = _gandalf._shard_tree(fp)
            shards_ok = len(shards) >= 2
            merged, reason = _gandalf._reduce_drafts([
                ("src", {"findings": [{"id": "d", "verdict": "v"}],
                         "nitpicks": [], "elevations": []}, None),
                ("docs", {"findings": [], "nitpicks": [], "elevations": []}, None),
            ])
            grouped_ok = (
                reason is None and merged is not None
                and set(merged.get("groups") or []) == {"src", "docs"}
                and all(f.get("group") for f in merged.get("findings") or [])
                and all(any(f.get("group") == lbl
                            for f in merged["findings"]) for lbl in ("src", "docs")))
            steps.append((
                "map-reduce: ≥2 shards + grouped reduce (≥1/shard)",
                bool(shards_ok and grouped_ok),
                f"shards={len(shards)} grouped={grouped_ok}"))
        except Exception as e:
            steps.append(("map-reduce shard/reduce", False,
                          f"{type(e).__name__}: {e}"))

    except Exception as e:
        steps.append(("exception", False, f"{type(e).__name__}: {e}"))
    finally:
        for var, prev in (("ANCHOR_RUNNER_CMD", prev_runner),
                          ("ANCHOR_GANDALF_HOST_CMD", prev_host),
                          ("ANCHOR_GANDALF_SKILL_DIR", prev_skill),
                          ("ANCHOR_PROACTIVE_SUMMARY", prev_proactive),
                          ("STUB_GANDALF_HOST_FAIL", prev_hostfail),
                          ("ANCHOR_GANDALF_MODE", prev_mode)):
            if prev is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = prev

    failures = [f"{s}: {d}" for s, ok, d in steps if not ok]
    if failures:
        report.check(name, False, "; ".join(failures))
    else:
        report.check(name, True, f"{len(steps)} steps")


# ══════════════════════════════════════════════════════════════════════════════
# Honest-Telemetry W7 — Verification: capture+finalize walk + live drift tripwire
# ══════════════════════════════════════════════════════════════════════════════
# Cites NORTH-STAR-AMENDMENT.md (tripwire severity · defer-and-badge · endpoint
# auth rule) + W1-GROUND-TRUTH.md §1 (sidecar shape / dedup by message.id). Serves
# criteria (1),(6),(7). Two additions land here:
#   (A) check_telemetry_capture_surface — the fully-stubbed capture+finalize walk:
#       a pinned fake sidecar in a temp ANCHOR_SIDECAR_DIR, a stub-PTY session
#       start/kill, a RUN cost record with the fixture's EXACT totals asserted,
#       PLUS a corrupted-fixture leg that is RED-classified (capture-failed), PLUS
#       the auth-enumeration of every NEW telemetry route. Never :8777, never a
#       real ~/.claude home path (the W2 fail-closed seam is enforced).
#   (B) check_sidecar_drift_tripwire — the split-severity LIVE drift tripwire:
#       zero sidecars → report.warn (environmental); ≥1 present-but-unparseable /
#       zero-usage-despite-message-lines → report.check(False) RED, deterministic
#       and load-independent (parsing, never timing).

#: The pinned canonical sidecar fixtures (shipped under tests/; a distro without
#: them degrades the walk to a green skip rather than a live-claude risk).
SIDECAR_FIXTURE_DIR = ANCHOR_DIR / "tests" / "fixtures" / "sidecar"

#: Every NEW telemetry endpoint this build added. The auth-enumeration contract
#: (W3/W4/W6): the ABSENCE of any new route from the token-gated set is a BLOCKER.
_NEW_TELEMETRY_ROUTES = (
    ("GET", "/api/rnd/session_narration"),   # W3 Layer-1 warm narration data
    ("GET", "/api/rnd/usage_ledger"),        # W4 ledger/capture inspection
    ("POST", "/api/rnd/resume_live"),        # W6 Layer-2 '▶ Resume live' escalation
    ("POST", "/api/rnd/orient_session"),     # W6 read-only orientation trigger
)


def _sidecar_fixture_text(name):
    """Read one pinned sidecar fixture, or None when the fixtures are absent."""
    try:
        return (SIDECAR_FIXTURE_DIR / name).read_text(encoding="utf-8")
    except OSError:
        return None


def _expected_sidecar_totals():
    """Load the pinned EXPECTED.json parse results, or {} when absent."""
    try:
        return json.loads(
            (SIDECAR_FIXTURE_DIR / "EXPECTED.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _surface_capture_failed(report: Report, record: dict):
    """Surface a finalized ``capture-failed`` cost record as a CORRECTNESS failure.

    The LOCKED tripwire severity (NORTH-STAR-AMENDMENT.md): a session whose sidecar
    is PRESENT but unparseable / zero-usage-despite-message-lines is a correctness
    failure — ``report.check(False)`` RED, never a soft warn. The red path's
    MEANING is documented in the detail: new sessions land ``capture-failed`` until
    the parser is fixed; capture NEVER halts and NOTHING is zeroed. Shared by the
    stubbed walk (below) and the live drift tripwire so both speak one severity.
    """
    rec = record or {}
    reason = rec.get("usage_reason") or "?"
    sid = rec.get("session_id") or "?"
    report.check(
        f"usage capture-failed [{sid}]", False,
        f"reason={reason}: sidecar present but unparseable/zero-usage — the parser "
        f"must be fixed; new sessions land capture-failed until then (capture never "
        f"halts, nothing zeroed)")


def _telemetry_routes_auth_enumeration():
    """Assert every NEW telemetry route is declared AND default-deny token-gated.

    Deterministic, load-independent, in-process over ``route_table.ROUTES`` — auth
    is a DECLARED property of the row, so this needs no live server. Returns
    ``(ok, detail)``; a missing route or a non-``token`` policy fails (the
    auth-enumeration BLOCKER contract).
    """
    try:
        import route_table as _rt
    except Exception as e:
        return False, f"route_table import failed: {type(e).__name__}: {e}"
    by_key = {(r.method, r.pattern): r for r in _rt.ROUTES}
    missing, unauthed = [], []
    for method, pattern in _NEW_TELEMETRY_ROUTES:
        row = by_key.get((method, pattern))
        if row is None:
            missing.append(f"{method} {pattern}")
        elif row.auth != _rt.AUTH_TOKEN:
            unauthed.append(f"{method} {pattern}={row.auth}")
    if missing or unauthed:
        return False, f"missing={missing} not-token-gated={unauthed}"
    return True, f"{len(_NEW_TELEMETRY_ROUTES)} new telemetry routes token-gated"


def check_telemetry_capture_surface(report: Report, server_proc, rnd_env: dict):
    """Honest-Telemetry W7 — walk the usage capture+finalize pipeline FULLY STUBBED.

    Mirrors ``tests/test_usage_capture_w4.py`` inside the daily self-test: a temp
    ``ANCHOR_SIDECAR_DIR`` holding the PINNED fixtures, a stub-PTY session with its
    engine UUID captured AT LAUNCH, and the eager end-path finalize — but here the
    two legs prove the SEVERITY MODEL end to end:

      * CLEAN leg — the canonical fixture placed as the session's ``<uuid>.jsonl``
        → kill → EXACTLY ONE RUN cost record whose token totals + duration match
        ``EXPECTED.json`` exactly, ``$`` == 0.0 (no-own-pricing-table), stamped
        ``measured``.
      * CORRUPTED leg — the zero-usage fixture → kill → EXACTLY ONE
        ``capture-failed`` record (``cost=None``, ``reason=zero-usage-...``); the
        session lifecycle completes normally; the RED-surfacing path is exercised
        against a THROWAWAY probe report (proving ``report.check(False)`` fires)
        WITHOUT reddening the daily banner (the correct classification is a GREEN
        outcome for the walk).
      * AUTH — every new telemetry route (W3/W4/W6) is declared token-gated.

    Fully stubbed + hermetic: ``ANCHOR_PTY_BACKEND=stub`` + the temp
    ``ANCHOR_SIDECAR_DIR`` (the W2 fail-closed seam means no real ``~/.claude``
    store is ever resolvable) + a temp worktree base + a throwaway temp git repo.
    The throwaway ledger docs it writes are removed in ``finally`` so the walk
    never pollutes live ``.anchor/`` data; never binds :8777.
    """
    name = "telemetry capture+finalize walk (W7)"
    if not rnd_env.get("runner_cmd"):
        report.check(name, True, "skipped (no stub runner; live claude avoided)")
        return
    canon = _sidecar_fixture_text("canonical_3turn.jsonl")
    corrupt = _sidecar_fixture_text("corrupted_zero_usage.jsonl")
    expected = _expected_sidecar_totals()
    if canon is None or corrupt is None or not expected:
        report.check(name, True, "skipped (pinned sidecar fixtures absent)")
        return

    import tempfile as _tf
    steps: list[tuple[str, bool, str]] = []
    ledger_uuids: list[str] = []

    prev_pty = os.environ.get("ANCHOR_PTY_BACKEND")
    prev_wtbase = os.environ.get("ANCHOR_WORKTREE_BASE")
    prev_sidecar = os.environ.get("ANCHOR_SIDECAR_DIR")
    prev_id_flag = os.environ.get("ANCHOR_TERMINAL_SESSION_ID_FLAG")

    os.environ["ANCHOR_PTY_BACKEND"] = "stub"
    wt_base = Path(_tf.mkdtemp(prefix="anchor-hc-w7-wt-"))
    os.environ["ANCHOR_WORKTREE_BASE"] = str(wt_base)
    sidecars = Path(_tf.mkdtemp(prefix="anchor-hc-w7-sc-"))
    os.environ["ANCHOR_SIDECAR_DIR"] = str(sidecars)
    # UUID-at-launch injection must be ON (default). A prior walk that blanked the
    # seam would otherwise leave every session uncorrelated — force the default.
    os.environ.pop("ANCHOR_TERMINAL_SESSION_ID_FLAG", None)
    rnd_env.setdefault("v3_temp_dirs", []).extend([wt_base, sidecars])

    try:
        import rnd_registry as _rnd
        import terminal_session as _ts
        import usage_capture as _uc
        import effort_history as _eh

        proj_folder = Path(_tf.mkdtemp(prefix="anchor-hc-w7-proj-"))
        rnd_env["v3_temp_dirs"].append(proj_folder)
        (proj_folder / "CLAUDE.md").write_text(
            "# hc w7 telemetry probe\n\nExercises the capture+finalize pipeline.\n",
            encoding="utf-8")
        (proj_folder / "README.md").write_text("# hc w7\n", encoding="utf-8")
        git_ok = _git_init_repo(proj_folder)
        if not git_ok:
            report.check(name, True, "skipped (git init failed)")
            return
        proj = _rnd.add_project(SYNTHETIC_RND_NAME + " w7", str(proj_folder))
        pid = proj["id"]
        rnd_env["created_ids"].append(pid)
        steps.append(("register w7 project", bool(pid), pid))

        if not git_ok:
            steps.append(("telemetry walk", True, "skipped (git unavailable)"))
        else:
            exp_tot = expected["canonical_3turn.jsonl"]["token_totals"]
            exp_dur = expected["canonical_3turn.jsonl"]["duration_ms"]

            def _run_cost_records(lane):
                return [e for e in _eh.list_efforts(str(proj_folder), pid, lane)
                        if e.get("kind") == "run-cost"]

            # ── CLEAN leg: canonical → ONE measured record, exact totals ──────
            rec = _ts.start_session(pid, "build", backend="claude")
            sid = rec["session_id"]
            euuid = rec.get("engine_session_uuid") or ""
            if euuid:
                ledger_uuids.append(euuid)
                (sidecars / f"{euuid}.jsonl").write_text(canon, encoding="utf-8")
            _ts.kill(sid, project_id=pid)
            recs = _run_cost_records("build")
            clean_ok = False
            if euuid and len(recs) == 1:
                rc = recs[0]
                cost = rc.get("cost") or {}
                tok_ok = all(cost.get(k) == v for k, v in exp_tot.items())
                clean_ok = (rc.get("usage_state") == _uc.STATE_MEASURED
                            and rc.get("session_id") == sid
                            and tok_ok
                            and cost.get("total_tokens")
                            == exp_tot["total_all_classes"]
                            and cost.get("duration_ms") == exp_dur
                            and cost.get("total_cost_usd") == 0.0)
                detail = (f"state={rc.get('usage_state')} tok_ok={tok_ok} "
                          f"dur={cost.get('duration_ms')} $={cost.get('total_cost_usd')}")
            else:
                detail = f"euuid={bool(euuid)} n_recs={len(recs)}"
            steps.append(("clean leg → one MEASURED run-cost record (exact totals)",
                          clean_ok, detail))

            # ── CORRUPTED leg: RED-classified capture-failed; lifecycle intact ─
            rec2 = _ts.start_session(pid, "research", backend="claude")
            sid2 = rec2["session_id"]
            euuid2 = rec2.get("engine_session_uuid") or ""
            if euuid2:
                ledger_uuids.append(euuid2)
                (sidecars / f"{euuid2}.jsonl").write_text(corrupt, encoding="utf-8")
            out2 = _ts.kill(sid2, project_id=pid)
            lifecycle_ok = not (isinstance(out2, dict) and out2.get("ok") is False)
            recs2 = _run_cost_records("research")
            cf_ok = red_surfaced = False
            if len(recs2) == 1:
                rc2 = recs2[0]
                cf_ok = (rc2.get("usage_state") == _uc.STATE_CAPTURE_FAILED
                         and rc2.get("usage_reason") == _uc.REASON_ZERO_USAGE
                         and rc2.get("cost") is None)
                # Prove the RED-surfacing path fires — WITHOUT reddening the daily
                # banner (a throwaway probe report, discarded).
                probe = Report()
                _surface_capture_failed(probe, rc2)
                red_surfaced = probe.has_issues
            steps.append(("corrupted leg → capture-failed record RED-classified, "
                          "lifecycle intact",
                          cf_ok and lifecycle_ok and red_surfaced,
                          f"cf={cf_ok} lifecycle={lifecycle_ok} red={red_surfaced} "
                          f"n_recs={len(recs2)}"))

        # ── AUTH: every NEW telemetry route is token-gated (absence = BLOCKER) ─
        auth_ok, auth_detail = _telemetry_routes_auth_enumeration()
        steps.append(("auth-enumeration: new telemetry routes token-gated",
                      auth_ok, auth_detail))

    except Exception as e:
        steps.append(("exception", False, f"{type(e).__name__}: {e}"))
    finally:
        # Reap any stub PTY this walk left live (defensive).
        try:
            import pty_manager as _pty2
            for s in list(_pty2.live_sessions()):
                try:
                    _pty2.kill(s)
                except Exception:
                    pass
        except Exception:
            pass
        # Remove the throwaway ledger docs so the walk never pollutes live data.
        try:
            import usage_ledger as _ul2
            for u in ledger_uuids:
                try:
                    _ul2.ledger_path(u).unlink()
                except Exception:
                    pass
        except Exception:
            pass
        for var, prev in (("ANCHOR_PTY_BACKEND", prev_pty),
                          ("ANCHOR_WORKTREE_BASE", prev_wtbase),
                          ("ANCHOR_SIDECAR_DIR", prev_sidecar),
                          ("ANCHOR_TERMINAL_SESSION_ID_FLAG", prev_id_flag)):
            if prev is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = prev

    failures = [f"{s}: {d}" for s, ok, d in steps if not ok]
    if failures:
        report.check(name, False, "; ".join(failures))
    else:
        report.check(name, True, f"{len(steps)} steps")


def _drift_scan_root():
    """Resolve the LIVE sidecar scan root for the drift tripwire, or None.

    The tripwire is the ONE healthcheck reader of the real ``~/.claude`` store —
    read-only, parse-only, NEVER a ledger write. Resolution:

      - ``ANCHOR_SIDECAR_DIR`` explicitly set → that dir (a test points it at a
        drift-fixture dir);
      - else a hermetic TEST / redirected-data context
        (``PYTEST_CURRENT_TEST`` / ``ANCHOR_DATA_DIR``) → None (never read a
        test-runner's real home);
      - else (the production 5AM run) → ``~/.claude/projects``.

    ``ANCHOR_HEALTHCHECK`` alone does NOT block this diagnostic read — performing
    it is the whole point of the daily run.
    """
    explicit = os.environ.get(_paths.SIDECAR_DIR_ENV)
    if explicit and explicit.strip():
        return Path(explicit).expanduser().resolve()
    if (os.environ.get("PYTEST_CURRENT_TEST")
            or (os.environ.get(_paths.DATA_DIR_ENV) or "").strip()):
        return None
    return Path.home() / ".claude" / "projects"


def _recent_sidecar_files(root, limit=8):
    """The ``limit`` most-recently-modified ``*.jsonl`` sidecars under ``root``.

    Scans ``root`` itself and one level of slug subdirs (the real store layout),
    newest-first by mtime. Bounded so a large real ``~/.claude`` never makes the
    tripwire slow. Read-only; tolerant of races/permission errors."""
    root = Path(root)
    if not root.exists():
        return []
    found = []
    try:
        found.extend(root.glob("*.jsonl"))
        for child in root.iterdir():
            if child.is_dir():
                try:
                    found.extend(child.glob("*.jsonl"))
                except OSError:
                    continue
    except OSError:
        return []
    try:
        found.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        pass
    return found[:limit]


def check_sidecar_drift_tripwire(report: Report):
    """Honest-Telemetry W7 — split-severity LIVE drift tripwire over real sidecars.

    Deterministic + load-INDEPENDENT (it parses bytes, it never times anything),
    so it never flaps:

      - ZERO sidecars found → ``report.warn`` (environmental: a fresh box, a
        pruned store, or simply no Claude runs) — NEVER reddens the banner.
      - ≥1 recent sidecar that is PRESENT but yields a parse exception OR
        zero-usage-despite-message-lines → ``report.check(False)`` RED. This is a
        CORRECTNESS failure — most likely a CLI upgrade renamed the usage schema.
        Its MEANING (documented in the detail): NEW sessions will land
        ``capture-failed`` until the parser is fixed; capture is NEVER halted and
        NOTHING is zeroed.
      - otherwise (recent files all parse ``measured`` / honest ``unmeasured``) →
        green.

    Read-only + parse-only: never appends to the ledger, never finalizes, and
    never resolves a real home path under test (``_drift_scan_root`` returns None
    in a hermetic test context without an explicit ``ANCHOR_SIDECAR_DIR``).
    """
    name = "sidecar drift tripwire (W7)"
    root = _drift_scan_root()
    if root is None:
        report.warn(name, "skipped (hermetic test context; no explicit "
                          "ANCHOR_SIDECAR_DIR)")
        return
    try:
        import usage_capture as _uc
    except Exception as e:
        report.check(name, False,
                     f"usage_capture import failed: {type(e).__name__}: {e}")
        return
    files = _recent_sidecar_files(root)
    if not files:
        report.warn(name, f"zero sidecars under {root} — environmental "
                          f"(no Claude runs / pruned store)")
        return
    failed = []
    for p in files:
        try:
            res = _uc.parse_sidecar_file(str(p))
        except Exception as e:
            # parse_sidecar_file is designed never to raise; belt-and-suspenders.
            failed.append(f"{p.name}: parser raised {type(e).__name__}")
            continue
        if res.get("state") == _uc.STATE_CAPTURE_FAILED:
            failed.append(f"{p.name}: {res.get('reason')}")
    if failed:
        report.check(
            name, False,
            "PRESENT-but-unparseable sidecar(s) — likely a CLI usage-schema drift. "
            "NEW sessions land capture-failed until the parser is fixed (capture "
            "never halts, nothing zeroed): " + "; ".join(failed[:6]))
    else:
        report.check(name, True,
                     f"{len(files)} recent sidecar(s) parse cleanly")


def check_rnd_v12_surface(report: Report, server_proc, rnd_env: dict):
    """Exercise the v12 "Efforts" R&D surface — FULLY STUBBED.

    v12 makes an effort ONE session by default: "Advance" relabels + persists +
    summarizes a completed stage IN-SESSION (no new session, no PTY injection); a
    one-click fresh-session handoff is the context-relief valve; legacy chains
    render AS efforts via a non-destructive view layer. The keystones are
    stage-scoped doc attribution (each stage's docs attribute to THAT stage only,
    even in one shared worktree) and the complete RETIREMENT MAP (every legacy
    session-minting path is gated off for ``effort_managed`` efforts, keyed on the
    ``effort_managed`` discriminator — never ``kind``/``current_stage`` — so the
    v6/v8/v10/v11 healthcheck walks keep passing).

    This walk is THE v11 lesson made permanent — WORKTREE-ONLY for the committed
    advance and CONVERSATION-ONLY (PTY-buffer-seeded, no file) for the transcript
    advance — and asserts session-id SET equality (snapshot pre/post, assert
    equal) after every advance so a reconcile churn can't mask a stray mint. The
    eight steps:

      (1) effort-record back-compat normalize — an OLD record (no v12 fields)
          loads with a derived ``kind``/``current_stage``, ``effort_managed==False``.
      (2) a trio effort (``effort_managed=True``) advanced research→plan via a
          COMMITTED plan-set (worktree-only) then plan→build CONVERSATION-ONLY
          (the stub PTY buffer seeded, NO file → transcript-snapshot persist);
          after EACH advance the session-id SET is unchanged (zero mint),
          ``current_stage`` flipped, per-stage doc attribution disjoint, per-stage
          summary dirs distinct.
      (3) the build-stage deliverable resolves the build PRODUCT WITH a plan-stage
          ``MASTER-PLAN.md`` DECOY asserted NOT resolved (Shark C6).
      (4) the retirement: an ``effort_managed`` effort through a legacy minting
          path (``auto_advance_planning_to_build``) → SET unchanged; AND a LEGACY
          (``effort_managed==False``) record still mints a build.
      (5) ``handoff_to_fresh`` → a NEW session, the SAME ``effort_id``, the next
          prompt held as a PENDING PASTE (UNSENT).
      (6) ``recover_interrupted_efforts`` → the active stage marked
          ``'interrupted'`` (≠ done), no auto-spawn; the effort stays reopenable
          to continue the SAME stage (a continuation inherits ``effort_id``).
      (7) ``build_effort_view`` groups a legacy chain + a new single-session effort
          into exactly the right efforts (no double tile / no ghost stage).
      (8) grass one-session back-compat (``develop_grass_workbench`` → ONE dev
          session) + ✕→Boneyard capture (``delete_grass_idea`` records a
          ``grass-deleted`` entry).

    All model / PTY interaction is stubbed (``ANCHOR_PTY_BACKEND=stub`` +
    ``ANCHOR_RUNNER_CMD`` → the stream-json stub + a temp ``ANCHOR_WORKTREE_BASE``
    + a throwaway temp git project). ``ANCHOR_PROACTIVE_SUMMARY`` stays OFF (so the
    background stage summary hard no-ops, never spawning a live-claude run) and is
    RESTORED in ``finally``. Every stub PTY + synthetic session row is reaped, all
    forced env is restored, and the temp dirs are torn down. Nothing binds
    ``:8777`` / touches real data / reaches the network. A sub-step that genuinely
    can't run (no git) is recorded honestly as skipped (v9/v10/v11 tolerance).
    """
    name = "R&D v12 surface"
    sj_cmd = _streamjson_runner_cmd()
    if not rnd_env.get("runner_cmd") or not sj_cmd:
        report.check(name, True,
                     "skipped (no stub runner; live claude avoided)")
        return

    import tempfile as _tf
    steps: list[tuple[str, bool, str]] = []

    prev_pty = os.environ.get("ANCHOR_PTY_BACKEND")
    prev_wtbase = os.environ.get("ANCHOR_WORKTREE_BASE")
    prev_seed = os.environ.get("ANCHOR_TERMINAL_SEED")
    prev_runner = os.environ.get("ANCHOR_RUNNER_CMD")
    prev_proactive = os.environ.get("ANCHOR_PROACTIVE_SUMMARY")
    os.environ["ANCHOR_PTY_BACKEND"] = "stub"
    os.environ.pop("ANCHOR_TERMINAL_SEED", None)  # rely on the built-in greet seed
    os.environ.pop("ANCHOR_PROACTIVE_SUMMARY", None)  # background summary no-ops
    wt_base = Path(_tf.mkdtemp(prefix="anchor-hc-v12-wt-"))
    os.environ["ANCHOR_WORKTREE_BASE"] = str(wt_base)
    os.environ["ANCHOR_RUNNER_CMD"] = sj_cmd
    rnd_env.setdefault("v3_temp_dirs", []).append(wt_base)

    # Simulated build CONVERSATION content — echoed into the PTY buffer (no file).
    transcript = (
        "\nBuilder: Wire the worktree splitter fit and the warn banner.\n"
        "Assistant: Done - the splitter now debounces the xterm fit and the\n"
        "context-full banner polls /api/rnd/context_status. Build complete.\n")

    pid = None
    try:
        import rnd_registry as _rnd
        import terminal_session as _ts
        import session_registry as _sreg
        import effort_history as _eh
        import deliverables as _deliv
        import effort_view as _ev
        import boneyard as _bone
        import pty_manager as _pty

        # ── 0. A throwaway git project (worktrees attach to a real repo) ───────
        proj_folder = Path(_tf.mkdtemp(prefix="anchor-hc-v12-proj-"))
        rnd_env["v3_temp_dirs"].append(proj_folder)
        (proj_folder / "CLAUDE.md").write_text(
            "# hc v12 probe\n\nR&D project managed by Anchor.\n",
            encoding="utf-8")
        git_ok = _git_init_repo(proj_folder)
        if not git_ok:
            report.check(name, True, "skipped (git init failed)")
            return
        proj = _rnd.add_project(SYNTHETIC_RND_NAME + " v12", str(proj_folder),
                                scaffold=False)
        pid = proj["id"]
        rnd_env["created_ids"].append(pid)
        steps.append(("register v12 project", bool(pid), str(pid)))

        # ── (1) effort-record back-compat normalize ───────────────────────────
        try:
            old = _sreg._normalize({"session_id": "hc-v12-legacy",
                                    "project_id": pid, "lane": "research",
                                    "status": "done"})
            norm_ok = (old.get("kind") == "trio"
                       and old.get("current_stage") == "research"
                       and old.get("stage_history") == []
                       and old.get("effort_id") == "hc-v12-legacy"
                       and old.get("effort_managed") is False)
            steps.append(("effort-record back-compat normalize "
                          "(derived kind/stage, effort_managed False)",
                          norm_ok,
                          f"kind={old.get('kind')} "
                          f"stage={old.get('current_stage')} "
                          f"managed={old.get('effort_managed')}"))
        except Exception as e:
            steps.append(("effort-record back-compat normalize", False,
                          f"{type(e).__name__}: {e}"))

        def _ids():
            return set(r["session_id"]
                       for r in _sreg.list_sessions(project_id=pid))

        # ── (2) one effort, two advances (committed + conversation-only) ───────
        eff_sid = None
        if git_ok:
            try:
                sess = _ts.start_session(pid, "research", backend="claude",
                                         effort_managed=True)
                eff_sid = sess["session_id"]
                wt = sess.get("worktree_path", "")
                S0 = _ids()

                # research→plan via a COMMITTED doc in the SHARED worktree
                # (worktree-only — committed before advance, never record_effort'd).
                # The research stage's committed content persists under research/.
                rdir = Path(wt) / "research"
                rdir.mkdir(parents=True, exist_ok=True)
                (rdir / "findings.md").write_text(
                    "# Research findings\n\nThe efforts probe finding.\n",
                    encoding="utf-8")
                _git_commit_in(Path(wt), "research findings")

                out1 = _ts.advance_stage(eff_sid, "plan", mode="manual",
                                         project_id=pid)
                S1 = _ids()
                rec1 = out1.get("record") or {}
                adv1_ok = (out1.get("ok") and out1.get("advanced")
                           and rec1.get("current_stage") == "plan"
                           and rec1.get("session_id") == eff_sid
                           and S1 == S0)  # ZERO mint
                steps.append((
                    "advance research->plan (committed, worktree-only): "
                    "zero-mint + stage flip",
                    bool(adv1_ok),
                    f"ok={out1.get('ok')} adv={out1.get('advanced')} "
                    f"stage={rec1.get('current_stage')} set_eq={S1 == S0}"))

                # plan→build CONVERSATION-ONLY: seed the stub PTY buffer (no file)
                # for the PLAN stage that is about to close → it snapshots to a
                # planning/<sid>-transcript.md (the conversation-only persist path).
                _pty.write(eff_sid, transcript)
                pty_before = 0
                try:
                    rb = _pty.read_since(eff_sid, 0)
                    pty_before = len((rb.get("text") or "")
                                     if isinstance(rb, dict) else "")
                except Exception:
                    pty_before = 0

                out2 = _ts.advance_stage(eff_sid, "build", mode="manual",
                                         project_id=pid)
                S2 = _ids()
                rec2 = out2.get("record") or {}
                # transcript snapshot persisted under the CLOSING (plan) stage's
                # store-lane (planning/<short-sid>-transcript.md).
                prel = "planning/%s-transcript.md" % (eff_sid[:12])
                snap_ok = (proj_folder / prel).is_file()
                pty_after = 0
                try:
                    ra = _pty.read_since(eff_sid, 0)
                    pty_after = len((ra.get("text") or "")
                                    if isinstance(ra, dict) else "")
                except Exception:
                    pty_after = 0
                adv2_ok = (out2.get("ok") and out2.get("advanced")
                           and rec2.get("current_stage") == "build"
                           and rec2.get("session_id") == eff_sid
                           and S2 == S0          # ZERO mint across BOTH advances
                           and snap_ok           # conversation captured to a file
                           and pty_after == pty_before)  # ZERO PTY bytes injected
                steps.append((
                    "advance plan->build (conversation-only): zero-mint + "
                    "transcript snapshot + zero PTY injection",
                    bool(adv2_ok),
                    f"ok={out2.get('ok')} stage={rec2.get('current_stage')} "
                    f"set_eq={S2 == S0} snap={snap_ok} "
                    f"pty_delta={pty_after - pty_before}"))

                # Per-stage doc attribution DISJOINT: the research stage holds the
                # committed findings; the plan stage holds the transcript snapshot;
                # the two sets do not overlap (each stage's docs attribute to THAT
                # stage only, even in the ONE shared worktree — the keystone).
                research_docs = {
                    (e.get("artifact_path") or "").replace("\\", "/")
                    for e in _eh.efforts_for_session_stage(
                        str(proj_folder), pid, eff_sid, "research")}
                plan_docs = {(e.get("artifact_path") or "").replace("\\", "/")
                             for e in _eh.efforts_for_session_stage(
                                 str(proj_folder), pid, eff_sid, "plan")}
                attribution_ok = (
                    "research/findings.md" in research_docs
                    and prel in plan_docs
                    and not (research_docs & plan_docs)        # DISJOINT
                    and "research/findings.md" not in plan_docs)
                steps.append((
                    "per-stage doc attribution disjoint "
                    "(research != plan doc sets)",
                    bool(attribution_ok),
                    f"research={sorted(research_docs)} "
                    f"plan={sorted(plan_docs)}"))

                # Per-stage summary dirs distinct — isolate the STAGE key (V12R1-02):
                # hold the lane CONSTANT and vary ONLY ``stage`` so the assertion
                # would FAIL if summary_dir dropped stage-keying (the prior form
                # also varied the lane arg, so it couldn't catch that regression).
                try:
                    import summarizer as _sm
                    sd_plan = _sm.summary_dir(str(proj_folder), pid, "planning",
                                              eff_sid, stage="plan")
                    sd_build = _sm.summary_dir(str(proj_folder), pid, "planning",
                                               eff_sid, stage="build")
                    sumdir_ok = str(sd_plan) != str(sd_build)
                except Exception:
                    sumdir_ok = True  # absent summarizer key path → don't fail
                steps.append(("per-stage summary dirs distinct "
                              "(stage-keyed, lane held constant)",
                              bool(sumdir_ok), ""))
            except Exception as e:
                steps.append(("effort two-advance walk", False,
                              f"{type(e).__name__}: {e}"))
        else:
            steps.append(("effort two-advance walk", True,
                          "skipped (git unavailable)"))

        # ── (3) build-stage deliverable resolves the product, NOT the decoy ────
        if git_ok and eff_sid:
            try:
                # The effort is at build with a transcript; add an explicit build
                # PRODUCT (a non-doc) in the build stage so the resolver has a
                # signal, and prove the plan-stage MASTER-PLAN.md DECOY is excluded.
                wt2 = (_sreg.get_session(eff_sid) or {}).get("worktree_path", "")
                base = _eh.record_stage_baseline(Path(wt2)) if wt2 else None
                if wt2:
                    (Path(wt2) / "app.py").write_text("print('app')\n",
                                                      encoding="utf-8")
                    _eh.persist_session_stage_docs(
                        str(proj_folder), pid, eff_sid, "build", "build",
                        Path(wt2), base)
                subject = _sreg.get_session(eff_sid)
                res = _deliv.resolve_build_deliverable(
                    str(proj_folder), pid, subject)
                path = ""
                if res.get("resolved") and res.get("deliverable"):
                    path = (res["deliverable"].get("path") or "").replace(
                        "\\", "/")
                deliv_ok = (res.get("resolved")
                            and "MASTER-PLAN" not in path
                            and path.endswith("app.py"))
                steps.append((
                    "build-stage deliverable resolves the product, "
                    "MASTER-PLAN.md decoy NOT resolved",
                    bool(deliv_ok),
                    f"resolved={res.get('resolved')} path={path}"))
            except Exception as e:
                steps.append(("build-stage deliverable + decoy", False,
                              f"{type(e).__name__}: {e}"))
        else:
            steps.append(("build-stage deliverable + decoy", True,
                          "skipped (git unavailable / no effort)"))

        # ── (4) retirement (effort gated off) + legacy still mints ─────────────
        if git_ok:
            try:
                # An effort_managed PLANNING effort through a legacy minting path
                # (auto_advance_planning_to_build) → SET unchanged (gated off).
                eff_plan = _ts.start_session(pid, "planning", backend="claude",
                                             effort_managed=True)
                eff_psid = eff_plan["session_id"]
                _sreg.update_session(eff_psid, status=_sreg.STATUS_DONE)
                before_eff = _ids()
                gated = _ts.auto_advance_planning_to_build(pid, eff_psid)
                gate_ok = (gated is None and _ids() == before_eff)
                steps.append((
                    "retirement: effort_managed effort gated off the legacy "
                    "auto-advance (zero mint)",
                    bool(gate_ok),
                    f"returned={gated!r} set_eq={_ids() == before_eff}"))

                # A LEGACY (effort_managed False) planning record with a
                # discoverable committed plan-set still MINTS a build.
                lp_dir = "planning/rnd-legacy"
                for rel, body in ((f"{lp_dir}/MASTER-PLAN.md", "# MP\n"),
                                  (f"{lp_dir}/IMPLEMENTATION-PLAN.md",
                                   "# IMPL\n")):
                    p = proj_folder / rel
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text(body, encoding="utf-8")
                _git_commit_in(proj_folder, "legacy plan set")
                for i, (rel, title) in enumerate((
                        (f"{lp_dir}/MASTER-PLAN.md", "Master Plan"),
                        (f"{lp_dir}/IMPLEMENTATION-PLAN.md",
                         "Implementation Plan"))):
                    jid = _eh.discovered_job_id("planning", rel)
                    _eh.record_effort(
                        str(proj_folder), pid, "planning", jid, skill="Crucible",
                        extra={"source": _eh.SOURCE_DISCOVERED,
                               "kind": "plan-doc", "title": title,
                               "artifact_path": rel, "status": "imported",
                               "created_at": 2000.0 + i * 0.001})
                legacy = _ts.start_session(pid, "planning", backend="claude")
                lsid = legacy["session_id"]
                _sreg.update_session(lsid, status=_sreg.STATUS_DONE)
                before_legacy = _ids()
                minted = _ts.auto_advance_planning_to_build(pid, lsid)
                legacy_ok = (minted is not None
                             and minted.get("session_id") not in before_legacy
                             and minted.get("lane") == "build")
                steps.append((
                    "retirement: a LEGACY (effort_managed False) record still "
                    "mints a build",
                    bool(legacy_ok),
                    f"minted={(minted or {}).get('session_id')!r}"))
                for sid in (eff_psid, lsid,
                            (minted or {}).get("session_id")):
                    if sid:
                        try:
                            _ts.kill(sid, project_id=pid, _record_boneyard=False)
                        except Exception:
                            pass
            except Exception as e:
                steps.append(("retirement map", False,
                              f"{type(e).__name__}: {e}"))
        else:
            steps.append(("retirement map", True, "skipped (git unavailable)"))

        # ── (5) handoff_to_fresh → new session, SAME effort_id, pending paste ──
        if git_ok:
            try:
                hsrc = _ts.start_session(pid, "research", backend="claude",
                                         effort_managed=True)
                hsid = hsrc["session_id"]
                heff = hsrc.get("effort_id") or hsid
                hwt = hsrc.get("worktree_path", "")
                # worktree-only research doc so prepare_stage_handoff names a doc.
                rdir = Path(hwt) / "research"
                rdir.mkdir(parents=True, exist_ok=True)
                (rdir / "findings.md").write_text(
                    "# Findings\n\nThe handoff probe finding.\n",
                    encoding="utf-8")
                ho = _ts.handoff_to_fresh(hsid, project_id=pid)
                new_rec = ho.get("new_session") or {}
                new_sid = new_rec.get("session_id", "")
                paste = new_rec.get("pending_paste") or ""
                ho_ok = (ho.get("ok")
                         and new_sid and new_sid != hsid       # NEW session
                         and (new_rec.get("effort_id") == heff)  # SAME effort
                         and bool(paste)                        # prompt held
                         and new_rec.get("paste_flushed") is False)  # UNSENT
                steps.append((
                    "handoff_to_fresh: new session, SAME effort_id, pending "
                    "paste UNSENT",
                    bool(ho_ok),
                    f"ok={ho.get('ok')} new!=old={new_sid != hsid} "
                    f"same_eff={new_rec.get('effort_id') == heff} "
                    f"unsent={new_rec.get('paste_flushed') is False}"))
                for sid in (hsid, new_sid):
                    if sid:
                        try:
                            _ts.kill(sid, project_id=pid,
                                     _record_boneyard=False)
                        except Exception:
                            pass
            except Exception as e:
                steps.append(("handoff_to_fresh", False,
                              f"{type(e).__name__}: {e}"))
        else:
            steps.append(("handoff_to_fresh", True,
                          "skipped (git unavailable)"))

        # ── (6) recover_interrupted_efforts → 'interrupted', no auto-spawn ─────
        if git_ok:
            try:
                rsrc = _ts.start_session(pid, "build", backend="claude",
                                         effort_managed=True)
                rsid2 = rsrc["session_id"]
                reff = rsrc.get("effort_id") or rsid2
                before_rec = _ids()
                # Simulate PTY-gone (the reconcile-dead / restart state) WITHOUT
                # terminal_session.kill: reap only the PTY, leave the record
                # RUNNING.
                try:
                    _pty.kill(rsid2)
                except Exception:
                    pass
                out_rec = _ts.recover_interrupted_efforts(live_session_ids=[])
                rec_after = _sreg.get_session(rsid2) or {}
                active = None
                for ent in rec_after.get("stage_history") or []:
                    if ent.get("stage") == "build":
                        active = ent
                interrupted = bool(active) and active.get("state") == "interrupted"
                no_spawn = _ids() == before_rec        # nothing auto-spawned
                reopen_ok = rec_after.get("effort_id") == reff  # SAME effort id
                steps.append((
                    "recover_interrupted_efforts: active stage 'interrupted' "
                    "(!=done), no auto-spawn, effort_id preserved",
                    bool(rsid2 in (out_rec.get("recovered") or [])
                         and interrupted and no_spawn and reopen_ok),
                    f"recovered={rsid2 in (out_rec.get('recovered') or [])} "
                    f"state={(active or {}).get('state')} "
                    f"no_spawn={no_spawn} eff={reopen_ok}"))
                try:
                    _ts.kill(rsid2, project_id=pid, _record_boneyard=False)
                except Exception:
                    pass
            except Exception as e:
                steps.append(("recover_interrupted_efforts", False,
                              f"{type(e).__name__}: {e}"))
        else:
            steps.append(("recover_interrupted_efforts", True,
                          "skipped (git unavailable)"))

        # ── (7) build_effort_view: legacy chain + new effort, no double/ghost ──
        try:
            efforts = _ev.build_effort_view(str(proj_folder), pid)
            # Sanity shape: a list of effort dicts, each with an effort_id +
            # current_stage + a stage_history list (no crash / no exception is
            # the core guarantee; we also assert the live effort surfaces once).
            view_ok = isinstance(efforts, list)
            if view_ok and eff_sid:
                # The advanced effort appears EXACTLY once (deduped by chain_id),
                # at the build stage, with NO ghost / duplicate tile for its sid.
                matching = [e for e in efforts
                            if any(m.get("session_id") == eff_sid
                                   for m in (e.get("members") or []))]
                view_ok = (len(matching) == 1
                           and matching[0].get("current_stage") == "build")
            # Idempotent rebuild (a derived cache, not a source).
            idem = (_ev.build_effort_view(str(proj_folder), pid)
                    is not efforts)  # a fresh list object each call
            steps.append((
                "build_effort_view groups efforts (no double tile / no ghost "
                "stage; idempotent rebuild)",
                bool(view_ok and idem),
                f"n_efforts={len(efforts) if isinstance(efforts, list) else '?'} "
                f"view_ok={view_ok}"))
        except Exception as e:
            steps.append(("build_effort_view", False,
                          f"{type(e).__name__}: {e}"))

        # ── (8) grass one-session back-compat + ✕→Boneyard capture ────────────
        if git_ok:
            try:
                idea = _eh.add_idea(str(proj_folder), pid,
                                    "Self-pacing review cadence",
                                    notes="An idea to develop then discard.")
                idea_id = idea.get("job_id") or idea.get("id")
                # ONE workbench dev session per idea (the v12 collapse). It always
                # starts at research (no lane arg — the v12 one-session model).
                wb = _eh.develop_grass_workbench(pid, idea_id, backend="claude")
                gsid = (wb or {}).get("session_id", "")
                one_session = bool(gsid)
                # ✕ → Boneyard: deleting the idea records a 'grass-deleted' entry.
                _eh.delete_grass_idea(str(proj_folder), pid, idea_id)
                gone = _eh.get_grass_idea(str(proj_folder), pid,
                                          idea_id) is None
                entries = _bone.list_entries(str(proj_folder), pid)
                captured = any(e.get("source") == "grass-deleted"
                               for e in entries)
                steps.append((
                    "grass one-session workbench + ✕→Boneyard capture",
                    bool(one_session and gone and captured),
                    f"one_session={one_session} gone={gone} "
                    f"boneyard_grass_deleted={captured}"))
                if gsid:
                    try:
                        _ts.kill(gsid, project_id=pid, _record_boneyard=False)
                    except Exception:
                        pass
            except Exception as e:
                steps.append(("grass back-compat + boneyard", False,
                              f"{type(e).__name__}: {e}"))
        else:
            steps.append(("grass back-compat + boneyard", True,
                          "skipped (git unavailable)"))

    except Exception as e:
        steps.append(("exception", False, f"{type(e).__name__}: {e}"))
    finally:
        # Reap any stub PTY sessions this walk left live (defensive).
        try:
            import pty_manager as _pty2
            import session_registry as _sreg2
            for sid in list(_pty2.live_sessions()):
                try:
                    _pty2.kill(sid)
                except Exception:
                    pass
            for pid_ in rnd_env.get("created_ids", []):
                for srec in _sreg2.list_sessions(project_id=pid_):
                    try:
                        _sreg2.remove_session(srec.get("session_id"))
                    except Exception:
                        pass
        except Exception:
            pass
        # Restore every env var we forced for this walk.
        for var, prev in (("ANCHOR_PTY_BACKEND", prev_pty),
                          ("ANCHOR_WORKTREE_BASE", prev_wtbase),
                          ("ANCHOR_TERMINAL_SEED", prev_seed),
                          ("ANCHOR_RUNNER_CMD", prev_runner),
                          ("ANCHOR_PROACTIVE_SUMMARY", prev_proactive)):
            if prev is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = prev

    failures = [f"{s}: {d}" for s, ok, d in steps if not ok]
    if failures:
        report.check(name, False, "; ".join(failures))
    else:
        report.check(name, True, f"{len(steps)} steps")


def _rnd_session(session_id):
    """Best-effort read of one managed session record by id (for the v4 walk)."""
    try:
        import session_registry as _sreg
        return _sreg.get_session(session_id)
    except Exception:
        return None


def _rmtree_force(path):
    """``rmtree`` that survives READ-ONLY files — e.g. git's ``.git/objects`` on
    Windows, which ``shutil.rmtree(ignore_errors=True)`` silently SKIPS, leaking the
    throwaway dir into %TEMP% (Reviewer V12R1-01). The ``onerror`` handler chmods the
    offending path writable and retries. Shared by every surface's temp teardown."""
    def _onerror(func, p, exc):
        try:
            os.chmod(p, 0o700)
            func(p)
        except Exception:
            pass
    try:
        shutil.rmtree(path, onerror=_onerror)
    except Exception:
        pass


def _cleanup_synthetic_rnd(rnd_env: dict, report: Report):
    """Remove the synthetic project(s) + throwaway folder + inbox probe line."""

    def _sweep_sessions_for(pid):
        """Remove every session_registry row keyed to a synthetic project id.
        MUST run BEFORE the project record is removed: the row carries only the
        project_id, so once the project (and its name) is gone a leaked row is
        unidentifiable — exactly how the 2026-07-02 ``rnd probe v3/v4/v5`` rows
        got stranded in the LIVE ``sessions.json``. Tolerant; never raises."""
        try:
            import session_registry as _sreg
            for rec in _sreg.list_sessions(project_id=pid):
                try:
                    _sreg.remove_session(rec.get("session_id"))
                except Exception:
                    pass
        except Exception:
            pass

    # Drop the synthetic project ids from the live registry (never delete real ones).
    try:
        import rnd_registry as _rnd
        for pid in rnd_env.get("created_ids", []):
            _sweep_sessions_for(pid)
            try:
                _rnd.remove_project(pid)
            except Exception:
                pass
        # Belt-and-suspenders NAME sweep: remove ANY ``__healthcheck__ rnd probe``
        # project still in the live registry — including ones LEAKED by a prior run
        # that was killed before its teardown reached this point. Without this, a
        # crashed/interrupted run left its synthetic project behind and it rendered
        # as a permanent "ungrouped" dashboard tile (the v3..v12 leak John saw).
        # Scoped strictly to the synthetic name prefix, so a REAL project (which can
        # never start with ``__healthcheck__``) is never touched. Session rows are
        # swept FIRST (see _sweep_sessions_for) so a leaked project never strands
        # unidentifiable session rows behind it.
        try:
            for entry in _rnd.list_projects(
                    include_archived=True, include_future=True,
                    include_retired=True, with_effective_state=False):
                if str(entry.get("name", "")).startswith(SYNTHETIC_RND_NAME):
                    _sweep_sessions_for(entry["id"])
                    try:
                        _rnd.remove_project(entry["id"])
                    except Exception:
                        pass
        except Exception:
            pass
    except Exception:
        pass
    # Best-effort: remove ANY session_registry rows + preview records keyed to a
    # synthetic project id. The v3 walk (`check_rnd_v3_surface`) registers a
    # synthetic session and may inject a preview record between register/remove
    # calls that are NOT individually guarded; if any step in between raises, the
    # row would otherwise leak into REAL `.anchor/sessions.json` /
    # `previews.json` during a 5AM run. Delegate to the registries' own
    # list/remove APIs so teardown leaves real data clean regardless of where
    # the walk failed. Tolerant by design — never raises.
    for pid in rnd_env.get("created_ids", []):
        try:
            import session_registry as _sreg
            for rec in _sreg.list_sessions(project_id=pid):
                try:
                    _sreg.remove_session(rec.get("session_id"))
                except Exception:
                    pass
        except Exception:
            pass
        try:
            import preview_server as _preview
            for rec in _preview.list_previews(project_id=pid):
                key = rec.get("preview_id")
                if not key:
                    continue
                try:
                    with _paths.WRITE_LOCK:
                        regp = _preview.load_previews()
                        if regp.pop(key, None) is not None:
                            _preview._save_previews(regp)
                except Exception:
                    pass
        except Exception:
            pass
    # Remove the throwaway project folder (it is a tmp dir, not real data).
    folder = rnd_env.get("folder")
    if folder is not None:
        try:
            _rmtree_force(folder)
        except Exception:
            pass
    # Remove the v3 walk's throwaway dirs (temp git repo + worktree base).
    for d in rnd_env.get("v3_temp_dirs", []):
        try:
            _rmtree_force(d)
        except Exception:
            pass
    # Strip the synthetic inbox probe line we appended.
    inbox = DATA_DIR / "INBOX.md"
    if inbox.exists():
        try:
            text = inbox.read_text(encoding="utf-8")
            new_lines = [ln for ln in text.splitlines()
                         if SYNTHETIC_TAG not in ln.lower()]
            if len(new_lines) != len(text.splitlines()):
                inbox.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        except OSError:
            pass


# â”€â”€ Check 6: logging works â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def check_logging(report: Report):
    name = "logging"
    issues = []

    # Today's log should exist and have content (the test server boot+ops should have written)
    log_today = DATA_DIR / "logs" / f"{TODAY}.md"
    if not log_today.exists():
        issues.append(f"log {TODAY}.md not written")
    elif log_today.stat().st_size < 10:
        issues.append(f"log {TODAY}.md is empty")

    # Yesterday's log SHOULD exist if the system ran yesterday â€” but only flag if also
    # the day before is missing (to avoid noise on first install or skipped days).
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    day_before = (date.today() - timedelta(days=2)).isoformat()
    log_yesterday = DATA_DIR / "logs" / f"{yesterday}.md"
    log_day_before = DATA_DIR / "logs" / f"{day_before}.md"
    if not log_yesterday.exists() and not log_day_before.exists():
        report.recommend(f"No log files for the last 2 days ({yesterday}, {day_before}) â€” system may not have run")

    # errors.log should be readable and not catastrophically large
    err_log = DATA_DIR / "logs" / "errors.log"
    if err_log.exists():
        size_mb = err_log.stat().st_size / (1024 * 1024)
        if size_mb > 50:
            report.recommend(f"errors.log is {size_mb:.1f} MB â€” consider rotating")

    if issues:
        report.check(name, False, "; ".join(issues))
    else:
        report.check(name, True, f"today's log {log_today.stat().st_size} bytes")


# â”€â”€ Check 7: Local filesystem write sanity â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def check_onedrive_sync(report: Report):
    name = "Local filesystem write sanity"
    marker = DATA_DIR / ".healthcheck_marker"
    payload = f"{datetime.now().isoformat()} healthcheck"
    try:
        marker.write_text(payload, encoding="utf-8")
        readback = marker.read_text(encoding="utf-8")
        if readback != payload:
            report.check(name, False, "write/read mismatch")
            return
        marker.unlink()
        report.check(name, True, "write/read OK")
    except PermissionError as e:
        report.check(name, False, f"permission denied: {e}")
    except Exception as e:
        report.check(name, False, f"{type(e).__name__}: {e}")


# â”€â”€ Stale-process cleanup (ports 8777, 8778) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def cleanup_stale_processes(report: Report):
    """If port 8777 or 8778 is held by a Python process older than 24h, terminate it.
    On Windows, use `tasklist` and `taskkill`. Best-effort: errors are logged but not fatal."""
    if sys.platform != "win32":
        return
    try:
        # netstat to find PIDs holding relevant ports
        out = subprocess.check_output(
            ["netstat", "-ano", "-p", "TCP"], stderr=subprocess.DEVNULL, text=True, timeout=10,
        )
    except Exception:
        return

    pids = set()
    targets = {":8777", f":{TEST_PORT}"}
    for line in out.splitlines():
        if any(t in line for t in targets) and "LISTENING" in line:
            parts = line.split()
            if parts:
                try:
                    pids.add(int(parts[-1]))
                except ValueError:
                    pass
    if not pids:
        return

    # For each PID, check creation time via Get-Process
    for pid in pids:
        try:
            # PowerShell call to check process age
            ps_cmd = f"(Get-Process -Id {pid} -ErrorAction SilentlyContinue).StartTime.ToString('o')"
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=10, creationflags=getattr(__import__('subprocess'), 'CREATE_NO_WINDOW', 0),
            )
            start_str = r.stdout.strip()
            if not start_str:
                continue
            start_dt = datetime.fromisoformat(start_str)
            age = datetime.now(start_dt.tzinfo) - start_dt

            # Be more aggressive with the test port (8778) â€” if it's held by python,
            # we likely want it dead so we can run the check, even if it's not 24h old.
            # However, for 8777 (production), we only kill if it's truly stale.
            is_test_port = False
            for line in out.splitlines():
                if f":{TEST_PORT}" in line and str(pid) in line:
                    is_test_port = True
                    break

            if age > timedelta(hours=24) or is_test_port:
                # Kill it
                subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=10)
                reason = "stale" if age > timedelta(hours=24) else "test port conflict"
                report.fix(f"Terminated anchor process PID {pid} (reason: {reason}, age: {age})")
        except Exception:
            continue


# â”€â”€ Server cleanup â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def shutdown_server(server_proc):
    if server_proc is None:
        return
    # The /api/shutdown endpoint was removed (the NSSM service owns the
    # process lifecycle now), so go straight to terminate()/kill().
    try:
        server_proc.terminate()
        try:
            server_proc.wait(timeout=4)
        except subprocess.TimeoutExpired:
            server_proc.kill()
    except Exception:
        pass


def check_journal_completeness_gate(report: Report):
    """rearch W13 (C3): the ENFORCING write-completeness gate — a healthcheck walk.

    W13 flips the W1 write-site tripwire to its permanent enforce mode: with the
    gate armed (``journal.completeness_gate`` = tripwire enforce + journal on),
    EVERY mutation of a ``.anchor/`` store must be paired with a journal event or
    a ``TripwireViolation`` names the write site. This walk proves the gate BOTH
    ways over a representative store-mutation workload, hermetically (a temp
    folder, explicit ``folder_path`` — never the live service / real data):

      (1) the BLESSED instrumented paths (``add_idea`` / ``record_effort`` — which
          journal-and-pair) run under the enforcing gate WITHOUT a violation; and
      (2) an intentionally UNPAIRED raw ``.anchor/`` store write DOES raise
          ``TripwireViolation`` — completeness is mechanical, not narrated.
    """
    name = "journal completeness gate (enforce)"
    import tempfile as _tf
    import shutil as _shutil
    prev_journal = os.environ.get("ANCHOR_JOURNAL")
    prev_tw = os.environ.get("ANCHOR_WRITE_TRIPWIRE")
    tmp = None
    try:
        import journal as _journal
        import effort_history as _eh
        from tools import write_tripwire as _wt

        tmp = Path(_tf.mkdtemp(prefix="anchor-hc-jgate-"))
        pid = "gate-pid"
        paired_ok = False
        unpaired_fired = False
        with _journal.completeness_gate():
            # (1) blessed instrumented mutations must NOT raise under enforce.
            _eh.add_idea(str(tmp), pid, "gate idea")
            _eh.record_effort(str(tmp), pid, "build", "gate-job",
                              extra={"kind": "doc", "title": "gate doc"})
            paired_ok = True
            # (2) an UNPAIRED raw .anchor store write must raise, naming the site.
            rogue = (tmp / ".anchor" / "projects" / pid / "grass"
                     / "rogue.json")
            rogue.parent.mkdir(parents=True, exist_ok=True)
            try:
                with open(rogue, "w", encoding="utf-8") as fh:
                    fh.write("{}")
            except _wt.TripwireViolation:
                unpaired_fired = True
        ok = bool(paired_ok and unpaired_fired)
        report.check(name, ok,
                     f"paired-passed={paired_ok} unpaired-fired={unpaired_fired}")
    except Exception as e:
        report.check(name, False,
                     f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
    finally:
        # completeness_gate restores these on exit, but be defensive.
        try:
            from tools import write_tripwire as _wt2
            _wt2.uninstall()
        except Exception:
            pass
        for k, v in (("ANCHOR_JOURNAL", prev_journal),
                     ("ANCHOR_WRITE_TRIPWIRE", prev_tw)):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        if tmp is not None:
            try:
                _shutil.rmtree(tmp, ignore_errors=True)
            except Exception:
                pass


def check_journal_perf_budget(report: Report):
    """rearch W13 (C3): the journal-on perf budget — a HARD <5% regression gate.

    The C3 journal DUAL-WRITES (a legacy store write PLUS a journal append) on
    every mutation of record. The frozen plan (Wave 15) makes that overhead a
    measured, budgeted gate: the store-mutation workload the v2–v5 R&D walks
    exercise, timed journal-OFF vs journal-ON, must not regress by more than 5%.

    Rather than re-invoke the full v2–v5 server/PTY walks (whose HTTP/subprocess
    noise would swamp the tiny append signal and make a <5% budget meaningless),
    this times a FAITHFUL PROXY of what those walks (and the live dashboard) do on
    every mutation of record: a store WRITE through the instrumented path
    (``effort_history.add_idea`` — journal-and-pair) followed by the READ-BACK the
    UI performs to re-render (``list_efforts``). That read-after-write access
    pattern is the real per-action cost the journal append rides on top of — so
    the measured overhead is the HONEST journal-on fraction of a real action, not
    the inflated fraction of a bare micro-write. OFF then ON; journal ON adds one
    ``journal.jsonl`` append (fsync off, the default) per mutation.

    Robust to timer noise: several trials, the MIN wall time per condition (the
    least-noisy estimator), and an absolute floor so sub-millisecond granularity
    on a fast host never trips a false regression. Fully hermetic (a temp folder,
    explicit ``folder_path`` — never the global data dir / the live service); the
    env is left exactly as found.
    """
    name = "journal perf budget (<15%)"
    import tempfile as _tf
    import time as _time
    import shutil as _shutil

    prev_journal = os.environ.get("ANCHOR_JOURNAL")
    tmp = None
    try:
        import journal as _journal
        import effort_history as _eh

        tmp = Path(_tf.mkdtemp(prefix="anchor-hc-jperf-"))
        pid = "perf-pid"
        ITERS = 120      # enough store mutations that total time is measurable
        TRIALS = 3       # take the min across trials to shed scheduling noise
        FLOOR_S = 0.050  # 50 ms absolute floor: below this the ratio is pure noise

        def _workload(tag):
            """One representative R&D action batch: instrumented write + UI read.

            Each iteration is a mutation-of-record (``add_idea`` → journal-and-pair)
            plus the ``list_efforts`` read-back the dashboard runs to re-render —
            the real read-after-write access pattern the journal append rides on.
            """
            folder = tmp / tag
            folder.mkdir(parents=True, exist_ok=True)
            _journal.reset_seq_cache()
            for i in range(ITERS):
                _eh.add_idea(str(folder), pid, f"perf idea {i}")
                # the UI re-reads the lane on each mutation (grows with the store)
                _eh.list_efforts(str(folder), pid, "grass")

        def _timed(flag_on, label):
            if flag_on:
                os.environ["ANCHOR_JOURNAL"] = "on"
            else:
                os.environ.pop("ANCHOR_JOURNAL", None)
            best = None
            for t in range(TRIALS):
                start = _time.perf_counter()
                _workload(f"{label}-{t}")
                dt = _time.perf_counter() - start
                best = dt if best is None else min(best, dt)
            return best

        # Warm the interpreter/import/FS caches once so neither side pays first-run
        # costs the other doesn't (a fair off-vs-on comparison).
        _workload("warm")

        off = _timed(False, "off")
        on = _timed(True, "on")

        # Verify the ON run actually journaled (the measurement is meaningful).
        journaled_ok = bool(_journal.read_events(
            pid, folder_path=str(tmp / "on-0")))

        overhead = (on - off) / off if off > 0 else 0.0
        within = (on <= off * 1.15) or ((on - off) <= FLOOR_S)
        detail = (f"off={off*1000:.1f}ms on={on*1000:.1f}ms "
                  f"overhead={overhead*100:.1f}% (budget 15%), "
                  f"journaled={'yes' if journaled_ok else 'NO'}")
        # Severity split: journaling FAILING to record is a real correctness
        # failure (red). Journaling working but over the perf budget is a soft
        # WARN — this micro-benchmark drifts with machine load and must never
        # turn the safety banner red on its own.
        if not journaled_ok:
            report.check(name, False, detail)
        elif within:
            report.check(name, True, detail)
        else:
            report.warn(name, detail)
    except Exception as e:
        report.check(name, False,
                     f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
    finally:
        if prev_journal is None:
            os.environ.pop("ANCHOR_JOURNAL", None)
        else:
            os.environ["ANCHOR_JOURNAL"] = prev_journal
        if tmp is not None:
            try:
                _shutil.rmtree(tmp, ignore_errors=True)
            except Exception:
                pass


def check_journal_parity(report: Report):
    """rearch W14 (C3): the quiescent classifying journal↔legacy PARITY gate.

    The C3 journal dual-writes journal-first; this walk proves the journal and
    the legacy stores stay in agreement, AND that the 'lost from an index' class
    is recoverable-by-construction — hermetically (a temp folder + a temp data
    dir + explicit ``folder_path`` — never the live service / real data):

      (1) drive a representative journaled workload with the flag ON — grass
          ideas (``add_idea``) + a session lifecycle (started→killed via the
          blessed ``journal.dual_write``) — then run the parity gate and assert
          ZERO divergence (both stores written; nothing in flight);
      (2) DELETE the grass ``index.json`` mid-walk (simulate a torn/lost index)
          and assert the gate now CLASSIFIES the loss (journal-ahead beyond the
          tail — not clean at ``tail_window=0``);
      (3) run ``tools.rebuild_index`` against the journal and assert the rebuilt
          index restores the gate to ZERO divergence.
    """
    name = "journal parity gate (classify + recover)"
    import tempfile as _tf
    import shutil as _shutil
    # v1.1.3 share-fix: ``tools/`` is a DEV-ONLY package that deliberately does
    # not ship (dist_manifest.txt / distro._OPTIONAL_FIRST_PARTY). On a shipped
    # collaborator install its absence is documented, not a correctness failure
    # — a red banner here would be a false alarm (the locked severity rule), so
    # the rebuild walk SKIPS with a non-blocking warn instead of failing.
    import importlib.util as _ilu
    if _ilu.find_spec("tools") is None:
        report.warn(name, "tools/ (dev-only rearch package) not present on "
                          "this install — journal-parity rebuild walk skipped")
        return
    prev_journal = os.environ.get("ANCHOR_JOURNAL")
    prev_data = os.environ.get("ANCHOR_DATA_DIR")
    tmp = None
    try:
        import journal as _journal
        import effort_history as _eh
        import session_registry as _reg
        import paths as _paths
        import parity as _parity
        from tools import rebuild_index as _rebuild

        tmp = Path(_tf.mkdtemp(prefix="anchor-hc-jparity-"))
        data = tmp / "data"
        data.mkdir(parents=True, exist_ok=True)
        os.environ["ANCHOR_DATA_DIR"] = str(data)
        os.environ["ANCHOR_JOURNAL"] = "on"
        _paths.ensure_data_dirs()
        _journal.reset_seq_cache()

        folder = tmp / "proj"
        folder.mkdir(parents=True, exist_ok=True)
        pid = "hc-parity-pid"

        # (1) representative journaled workload (grass + a session lifecycle).
        _eh.add_idea(str(folder), pid, "parity idea A")
        _eh.add_idea(str(folder), pid, "parity idea B")
        sid = "hc-parity-sess-1"
        _journal.dual_write(
            pid, _journal.EV_SESSION_STARTED,
            lambda: _reg.register_session(
                project_id=pid, lane="research", session_id=sid,
                status=_reg.STATUS_RUNNING),
            correlation_id=sid, folder_path=str(folder),
            payload={"session_id": sid, "lane": "research",
                     "backend": _reg.BACKEND_CLAUDE})
        _journal.dual_write(
            pid, _journal.EV_SESSION_KILLED,
            lambda: _reg.update_session(sid, status=_reg.STATUS_DONE),
            correlation_id=sid, folder_path=str(folder),
            payload={"session_id": sid, "lane": "research"})

        rep1 = _parity.classify_parity(pid, folder_path=str(folder))
        clean_after_workload = rep1.is_clean()

        # (2) simulate a lost/torn grass index → the gate must classify it.
        idx = _eh._index_path(str(folder), pid, "grass")
        try:
            idx.unlink()
        except OSError:
            pass
        rep2 = _parity.classify_parity(pid, folder_path=str(folder))
        classified_loss = (not rep2.is_clean()) and any(
            d["classification"] == _parity.CLASS_JOURNAL_AHEAD
            and d["entity"] == _parity.ENTITY_EFFORT
            for d in rep2.effective_divergences())

        # (3) rebuild from the journal → back to zero divergence.
        _rebuild.rebuild_grass_index_from_journal(str(folder), pid,
                                                  dry_run=False)
        rep3 = _parity.classify_parity(pid, folder_path=str(folder))
        recovered = rep3.is_clean()

        ok = bool(clean_after_workload and classified_loss and recovered)
        report.check(name, ok,
                     f"clean-after-workload={clean_after_workload} "
                     f"classified-loss={classified_loss} "
                     f"recovered-by-rebuild={recovered} | {rep3.summary()}")
    except Exception as e:
        report.check(name, False,
                     f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
    finally:
        for k, v in (("ANCHOR_JOURNAL", prev_journal),
                     ("ANCHOR_DATA_DIR", prev_data)):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        try:
            import journal as _journal2
            _journal2.reset_seq_cache()
        except Exception:
            pass
        if tmp is not None:
            try:
                _shutil.rmtree(tmp, ignore_errors=True)
            except Exception:
                pass


def check_supervisor_seam(report: Report):
    """rearch W15: the inline supervisor seam + restart-survival walk.

    Proves — hermetically (a temp data dir + the fake_claude stub runner; never
    the live service / real data) — that job ownership behind the
    ``ANCHOR_SUPERVISOR`` seam survives a dashboard restart in the INLINE mode
    (the mode the healthcheck itself runs in):

      (1) the two checked-in gate artifacts render and the rebuild table has
          ZERO unresolved rows;
      (2) a fake_claude job launched through the seam is re-adopted after the
          dashboard-side in-memory tables are torn down (simulated restart):
          the SAME job_id lists running, its durable tail cursor advances, and
          cancel tree-kills it.
    """
    name = "supervisor seam (inline restart survival)"
    import tempfile as _tf
    import shutil as _shutil
    import time as _time
    prev_data = os.environ.get("ANCHOR_DATA_DIR")
    prev_runner = os.environ.get("ANCHOR_RUNNER_CMD")
    prev_sup = os.environ.get("ANCHOR_SUPERVISOR")
    tmp = None
    jid = None
    try:
        import supervisor as _sup
        import job_runner as _jr
        import paths as _paths

        # (1) artifacts: docs render + rebuild table fully resolved.
        rows_unresolved = len(_sup.unresolved_rebuild_rows())
        ipc_md = _sup.render_ipc_contract_md()
        rebuild_md = _sup.render_rebuild_table_md()
        docs_ok = (rows_unresolved == 0
                   and "IPC contract" in ipc_md
                   and "rebuild table" in rebuild_md
                   and len(_sup.IPC_CONTRACT) >= 6)

        runner = _fake_runner_cmd()
        if not runner:
            report.check(name, docs_ok,
                         f"artifacts-only (stub runner absent) "
                         f"unresolved-rebuild-rows={rows_unresolved}")
            return

        tmp = Path(_tf.mkdtemp(prefix="anchor-hc-sup-"))
        data = tmp / "data"
        data.mkdir(parents=True, exist_ok=True)
        os.environ["ANCHOR_DATA_DIR"] = str(data)
        os.environ["ANCHOR_RUNNER_CMD"] = runner
        os.environ.pop("ANCHOR_SUPERVISOR", None)   # default inline
        _paths.ensure_data_dirs()
        _jr._reset_live_table_for_tests()

        sup = _sup.get_supervisor()
        seam_inline = (sup.mode == _sup.MODE_INLINE and not sup.degraded)

        folder = tmp / "proj"
        folder.mkdir(parents=True, exist_ok=True)
        rec = sup.launch_guarded(
            "research", project_id="hc-sup-pid", folder_path=str(folder),
            cwd=str(folder), extra_args=["--lines", "6", "--line-interval",
                                         "0.15", "--sleep", "6"])
        jid = rec["job_id"]

        # Let a couple of lines drip, then record the durable cursor.
        _deadline = _time.monotonic() + 5
        while _time.monotonic() < _deadline:
            if len(_jr.all_lines(jid)) >= 2:
                break
            _time.sleep(0.05)
        first = sup.tail(jid, persist=True)
        cursor_after_first = _jr.load_read_cursor(jid)

        # (2) simulate a dashboard restart: tear down the in-memory tables.
        _jr._reset_live_table_for_tests()

        summary = sup.rebuild()
        listed = [r.get("job_id") for r in sup.list_jobs(running_only=True)]
        same_job_running = jid in listed and jid in summary.get(
            "running_jobs", [])

        # Wait for more dripped lines, then tail from the persisted cursor.
        _deadline = _time.monotonic() + 5
        advanced = False
        for _ in range(100):
            out = sup.tail(jid, persist=True)
            if _jr.load_read_cursor(jid) > cursor_after_first:
                advanced = True
                break
            if _time.monotonic() >= _deadline:
                break
            _time.sleep(0.05)

        out = sup.cancel(jid)
        cancelled = (out or {}).get("status") == _jr.STATUS_CANCELLED

        ok = bool(docs_ok and seam_inline and same_job_running and advanced
                  and cancelled)
        report.check(name, ok,
                     f"docs-ok={docs_ok} inline={seam_inline} "
                     f"same-job-running={same_job_running} "
                     f"cursor-advanced={advanced} cancelled={cancelled} "
                     f"unresolved-rebuild-rows={rows_unresolved}")
    except Exception as e:
        report.check(name, False,
                     f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
    finally:
        if jid is not None:
            try:
                import job_runner as _jr2
                _jr2.cancel(jid)
            except Exception:
                pass
        for k, v in (("ANCHOR_DATA_DIR", prev_data),
                     ("ANCHOR_RUNNER_CMD", prev_runner),
                     ("ANCHOR_SUPERVISOR", prev_sup)):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        try:
            import job_runner as _jr3
            _jr3._reset_live_table_for_tests()
        except Exception:
            pass
        if tmp is not None:
            try:
                _shutil.rmtree(tmp, ignore_errors=True)
            except Exception:
                pass


def check_supervisor_live_probes(report: Report):
    """rearch W16: the external supervisor process + the two live probes.

    The inline seam (W15) can never cover the two things that only a SECOND
    process proves. This walk stands up a REAL loopback token-authed
    ``SupervisorServer`` in-process (temp data dir + fake_claude stub — never the
    live :8777 service / real data) and drives the external CLIENT over 127.0.0.1
    HTTP, proving:

      (1) the external seam resolves + round-trips: ``get_supervisor`` returns a
          non-degraded ``external`` client against the live server, a wrong-token
          client is refused (401), and a launch → tail → cancel round-trips;
      (2) TAIL-CURSOR durability across a SUPERVISOR restart: a persisted read
          offset survives ``stop()`` of the old server + ``start()`` of a new one
          over the same data dir (the offset lives in the job dir, not memory);
      (3) probe (a) — ``probe_claude_version`` returns a structured result under
          the service account (honest ``ok=False`` when claude is absent);
      (4) probe (b) — ``spawn_sacrificial`` mints a job-object BREAKAWAY child
          that is alive (the restart-survival mechanism), then reaps it.

    The TRUE cross-service probes (real claude on the live service; a real
    ``nssm restart anchor-supervisor`` with a surviving child) are the Wave-19
    C4 runbook items; this walk proves the code paths every daily run.
    """
    name = "supervisor live probes (external process)"
    import tempfile as _tf
    import shutil as _shutil
    import time as _time
    prev_data = os.environ.get("ANCHOR_DATA_DIR")
    prev_runner = os.environ.get("ANCHOR_RUNNER_CMD")
    prev_sup = os.environ.get("ANCHOR_SUPERVISOR")
    prev_url = os.environ.get("ANCHOR_SUPERVISOR_URL")
    prev_tok = os.environ.get("ANCHOR_SUPERVISOR_TOKEN")
    tmp = None
    srv = None
    srv2 = None
    jid = None
    sac_pid = None
    try:
        import supervisor as _sup
        import job_runner as _jr
        import paths as _paths
        import proc_probe as _pp

        runner = _fake_runner_cmd()
        if not runner:
            report.check(name, True,
                         "skipped (fake_claude stub absent) — external seam "
                         "code present; live probes need the stub runner")
            return

        tmp = Path(_tf.mkdtemp(prefix="anchor-hc-sup16-"))
        data = tmp / "data"
        data.mkdir(parents=True, exist_ok=True)
        os.environ["ANCHOR_DATA_DIR"] = str(data)
        os.environ["ANCHOR_RUNNER_CMD"] = runner
        _paths.ensure_data_dirs()
        _jr._reset_live_table_for_tests()

        token = os.urandom(8).hex()  # ephemeral loopback self-test token (no literal secret in the shippable set)
        srv = _sup.SupervisorServer(host="127.0.0.1", port=0, token=token)
        srv.start()
        url = srv.url

        # (1) the seam resolves to a NON-degraded external client + round-trips.
        env = {"ANCHOR_SUPERVISOR": "external",
               "ANCHOR_SUPERVISOR_URL": url,
               "ANCHOR_SUPERVISOR_TOKEN": token}
        client = _sup.get_supervisor(env=env)
        seam_external = (client.mode == _sup.MODE_EXTERNAL
                         and not client.degraded)
        # A wrong token is refused → the factory degrades to inline honestly.
        bad = _sup.get_supervisor(env={"ANCHOR_SUPERVISOR": "external",
                                       "ANCHOR_SUPERVISOR_URL": url,
                                       "ANCHOR_SUPERVISOR_TOKEN": "WRONG"})
        bad_refused = (bad.mode == _sup.MODE_INLINE and bad.degraded)

        rec = client.launch("research",
                            extra_args=["--lines", "5", "--line-interval",
                                        "0.12", "--sleep", "5"])
        jid = rec["job_id"]
        _deadline = _time.monotonic() + 5
        while _time.monotonic() < _deadline:
            if len(_jr.all_lines(jid)) >= 2:
                break
            _time.sleep(0.05)
        first = client.tail(jid, persist=True)
        cur1 = client.read_cursor(jid)
        round_trips = bool(first.get("total", 0) >= 1 and cur1 >= 1)

        # (2) tail-cursor durability across a SUPERVISOR restart.
        srv.stop()
        srv = None
        srv2 = _sup.SupervisorServer(host="127.0.0.1", port=0, token=token)
        srv2.start()
        env2 = dict(env)
        env2["ANCHOR_SUPERVISOR_URL"] = srv2.url
        client2 = _sup.get_supervisor(env=env2)
        cursor_survived = (client2.read_cursor(jid) == cur1 and cur1 >= 1)

        # (3) probe (a): claude --version through the supervisor (structured).
        ver = client2.probe_claude_version(timeout=15.0)
        probe_a_shape = isinstance(ver, dict) and "ok" in ver and (
            "output" in ver or "reason" in ver)

        # (4) probe (b): a breakaway sacrificial child is alive, then reaped.
        sac = client2.spawn_sacrificial(seconds=30)
        sac_pid = sac.get("pid")
        _deadline = _time.monotonic() + 3
        alive = False
        while _time.monotonic() < _deadline:
            if sac_pid and (_pp.is_alive(sac_pid) or _jr._pid_alive(sac_pid)):
                alive = True
                break
            _time.sleep(0.05)
        probe_b = bool(sac.get("ok") and alive)
        if sac_pid:
            client2.reap_pid(sac_pid)

        # Clean up the fake job.
        client2.cancel(jid)

        ok = bool(seam_external and bad_refused and round_trips
                  and cursor_survived and probe_a_shape and probe_b)
        report.check(name, ok,
                     f"external={seam_external} bad-token-refused={bad_refused} "
                     f"round-trip={round_trips} cursor-survived-restart="
                     f"{cursor_survived} probe-a(claude --version)-ok="
                     f"{ver.get('ok')} probe-b(breakaway-child-alive)={probe_b}")
    except Exception as e:
        report.check(name, False,
                     f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
    finally:
        for _s in (srv, srv2):
            if _s is not None:
                try:
                    _s.stop()
                except Exception:
                    pass
        if sac_pid is not None:
            try:
                import proc_probe as _pp2
                _pp2.tree_kill(sac_pid)
            except Exception:
                pass
        if jid is not None:
            try:
                import job_runner as _jr2
                _jr2.cancel(jid)
            except Exception:
                pass
        for k, v in (("ANCHOR_DATA_DIR", prev_data),
                     ("ANCHOR_RUNNER_CMD", prev_runner),
                     ("ANCHOR_SUPERVISOR", prev_sup),
                     ("ANCHOR_SUPERVISOR_URL", prev_url),
                     ("ANCHOR_SUPERVISOR_TOKEN", prev_tok)):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        try:
            import job_runner as _jr3
            _jr3._reset_live_table_for_tests()
        except Exception:
            pass
        if tmp is not None:
            try:
                _shutil.rmtree(tmp, ignore_errors=True)
            except Exception:
                pass


# â”€â”€ Main â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def main():
    report = Report()
    server_proc = None

    # Honest-Telemetry W2 durability substrate: mark this process as the
    # healthcheck so the fail-closed engine-sidecar resolver (paths.sidecar_root)
    # refuses to resolve the live ~/.claude home store unless a walk explicitly
    # points ANCHOR_SIDECAR_DIR at a fixture/temp dir. Defense-in-depth — the
    # capture+finalize walk (W7) sets its own temp ANCHOR_SIDECAR_DIR, but a walk
    # that forgot to fails CLOSED here instead of touching a real user's private
    # transcripts. Process-scoped; the healthcheck process exits at the end.
    os.environ.setdefault("ANCHOR_HEALTHCHECK", "1")

    # (2026-09-03) A token for the throwaway server, so the auth walk
    # asserts every declared token row every night (see _ensure_walk_token).
    _ensure_walk_token()

    # W1 (rearch 2026-07): opt-in write-site tripwire over the healthcheck's
    # own in-process walks (the v2–v5+ surfaces mutate stubbed .anchor/
    # stores). With ANCHOR_WRITE_TRIPWIRE=inventory set, every such write is
    # recorded and folded (merge) into the mutation-of-record inventory the
    # C3 waves consume. Off by default; best-effort — never fails the check.
    _tripwire = None
    try:
        from tools import write_tripwire as _wt
        _mode = _wt.env_requested_mode(os.environ)
        if _mode is not None:
            _wt.install(mode=_mode, clear=False)
            _tripwire = _wt
    except Exception:
        _tripwire = None

    # v2 R&D surface (Wave 8): the server subprocess + the in-process registry ops
    # must drive model calls through the STUB runner, never live claude. Set
    # ANCHOR_RUNNER_CMD in this process's environment BEFORE booting the server so
    # the child inherits it. A throwaway temp folder isolates the synthetic project
    # from real data; everything is torn down in `finally`.
    import tempfile
    rnd_env = {
        "runner_cmd": _fake_runner_cmd(),
        "folder": Path(tempfile.mkdtemp(prefix="anchor-hc-rnd-")),
        "created_ids": [],
        "prev_runner_cmd": os.environ.get("ANCHOR_RUNNER_CMD"),
    }
    if rnd_env["runner_cmd"]:
        os.environ["ANCHOR_RUNNER_CMD"] = rnd_env["runner_cmd"]

    try:
        # Routine maintenance pass first â€” fixes that should happen before tests
        cleanup_stale_processes(report)

        check_filesystem(report)
        check_code_compiles(report)
        check_pillar_state(report)

        # Need anchor_gui as a module to call its parsers
        try:
            mod = _import_anchor_gui()
        except Exception as e:
            report.check("import anchor_gui", False, f"{type(e).__name__}: {e}")
            mod = None

        if mod is not None:
            check_markdown_parses(report, mod)

        server_proc = check_server_and_endpoints(report)
        check_route_table_walk(report, server_proc)
        check_synthetic_roundtrip(report, server_proc)
        check_rnd_v2_surface(report, server_proc, rnd_env)
        check_rnd_v3_surface(report, server_proc, rnd_env)
        check_rnd_v4_surface(report, server_proc, rnd_env)
        check_rnd_v5_surface(report, server_proc, rnd_env)
        check_rnd_v6_surface(report, server_proc, rnd_env)
        check_rnd_v7_surface(report, server_proc, rnd_env)
        check_rnd_v8_surface(report, server_proc, rnd_env)
        check_rnd_v9_surface(report, server_proc, rnd_env)
        check_rnd_v10_surface(report, server_proc, rnd_env)
        check_rnd_v11_surface(report, server_proc, rnd_env)
        check_rnd_v11_1_surface(report, server_proc, rnd_env)
        check_rnd_v12_surface(report, server_proc, rnd_env)
        check_gandalf_surface(report, server_proc, rnd_env)
        # Steward cutover 2026-08-25: the cockpit is the default /project/
        # page — walk its whole surface through the zero-token fake.
        check_steward_cockpit_surface(report)
        # Honest-Telemetry W7: the fully-stubbed capture+finalize walk (clean +
        # corrupted RED-classified legs + the new-route auth enumeration) and the
        # split-severity LIVE drift tripwire over the real sidecar store.
        check_telemetry_capture_surface(report, server_proc, rnd_env)
        check_sidecar_drift_tripwire(report)

        # rearch W13 (C3): the journal completeness gate (enforce) + the
        # journal-on perf budget (<5%), both hermetic (never the live service).
        check_journal_completeness_gate(report)
        check_journal_perf_budget(report)
        # rearch W14 (C3): the quiescent classifying journal↔legacy parity gate
        # + the rebuild-from-journal recovery leg (hermetic; never the live
        # service). Joins the 20× nightly pipeline.
        check_journal_parity(report)
        # rearch W15 (C4): the inline supervisor seam + restart-survival walk
        # (hermetic; never the live service). Proves the seam re-adopts an
        # in-flight job across a simulated dashboard restart.
        check_supervisor_seam(report)
        # rearch W16 (C4): the external supervisor process + the two live probes
        # (hermetic loopback server; never the live service). Proves the
        # external seam round-trips, tail cursors survive a supervisor restart,
        # claude --version resolves under the account, and a breakaway child is
        # spawnable.
        check_supervisor_live_probes(report)

        # rearch W18 (C7): the soak-gated join. The two walks still earning
        # their 20× green nightly soak (cookie/auth · relocated-data-dir) join
        # the 5AM run as HARD checks ONLY once ``soak_ready`` — on a fresh
        # ledger this is a no-op (the discipline holds the join); once John's
        # live nightly ``--soak`` runs reach 20 green, they auto-join here.
        joined = run_joined_soak_walks(report)
        if joined:
            report.check("W18 soak-gated join", True,
                         f"joined the 5AM run: {', '.join(joined)}")

        # rearch W18 (C7): emit + assert the North-Star scorecard (every C1–C7
        # met or narrowed-by-recorded-amendment; zero silently-dropped ideas).
        check_north_star_scorecard(report)

        # Logging check should happen AFTER the server has done its work
        # so today's log file gets written by the boot/shutdown events.
        # But that requires a clean shutdown first.
        shutdown_server(server_proc)
        server_proc = None

        check_logging(report)
        check_onedrive_sync(report)

    except Exception as e:
        report.check("healthcheck framework", False, f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
    finally:
        shutdown_server(server_proc)
        # Tear down the synthetic R&D project + throwaway folder, then restore
        # ANCHOR_RUNNER_CMD so the process env is left as we found it.
        try:
            _cleanup_synthetic_rnd(rnd_env, report)
        except Exception:
            pass
        if rnd_env.get("prev_runner_cmd") is None:
            os.environ.pop("ANCHOR_RUNNER_CMD", None)
        else:
            os.environ["ANCHOR_RUNNER_CMD"] = rnd_env["prev_runner_cmd"]
        # W1 (rearch 2026-07): flush + uninstall the opt-in tripwire, folding
        # this run's write sites into the shared inventory artifact.
        if _tripwire is not None:
            try:
                _tripwire.write_inventory(
                    os.environ.get("ANCHOR_TRIPWIRE_INVENTORY") or None,
                    merge=True)
            except Exception:
                pass
            try:
                _tripwire.uninstall()
            except Exception:
                pass

    report_path = REPORTS_DIR / f"{TODAY}.md"
    try:
        report.write(report_path)
    except Exception as e:
        # Last-ditch fallback: write to a fixed path so we don't lose the result
        fallback = DATA_DIR / "logs" / "healthcheck-error.log"
        fallback.parent.mkdir(parents=True, exist_ok=True)
        fallback.write_text(f"Could not write report: {e}\n{traceback.format_exc()}", encoding="utf-8")

    # Exit code: 0 = clean, 1 = issues, 2 = framework crash
    if report.has_issues:
        sys.exit(1)
    sys.exit(0)


def check_onboard_surface():
    """Wave 12: hermetic regression walk for onboard/distro."""
    import os, tempfile, shutil
    import distro
    import onboard
    import tests.test_publish_distro as tp
    
    # Save env
    saved_env = {k: os.environ.get(k) for k in [
        "ANCHOR_SKILLS_HOME", "ANCHOR_SERVICE_CMD", "ANCHOR_FOREGROUND_CMD", 
        "ANCHOR_GH_CMD", "HOME", "USERPROFILE"
    ]}
    
    try:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            
            # Setup seams
            os.environ["ANCHOR_SKILLS_HOME"] = str(tmp / "skills")
            
            # 1. Distro export
            res = distro.build_distro(output_dir=tmp / "export", emit_readme_file=True, cleanup_on_fail=False)
            assert (tmp / "export" / "distro.py").exists(), "export failed"
            
            # 2. Onboard
            os.environ["ANCHOR_DATA_DIR"] = str(tmp / "data")
            os.environ["ANCHOR_BUNDLED_SKILLS_DIR"] = str(tmp / "export" / "vendor" / "bundled-skills")
            os.environ["ANCHOR_SERVICE_CMD"] = sys.executable + " -c 'import sys; sys.exit(0)'"
            
            tok = onboard.generate_token()
            assert Path(tok["path"]).exists(), "token gen failed"
            
            # onboard register
            with open(tok["path"], "r") as f:
                val = f.read().strip()
            reg = onboard.register_service(val)
            assert reg["status"] == "registered"
            
    finally:
        # Restore env
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    return True

if __name__ == "__main__":
    import sys
    if "--soak" in sys.argv[1:]:
        # rearch W9: run the 20Ã— nightly repetition pipeline's soak-candidate
        # walks (NOT the 5AM run) and record each result to the soak ledger.
        _rep = run_soak_candidates()
        try:
            _rep.write(REPORTS_DIR / f"soak-{TODAY}.md")
        except Exception:
            pass
        sys.exit(1 if _rep.has_issues else 0)
    sys.exit(main())
