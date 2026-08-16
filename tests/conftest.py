"""pytest configuration for the Anchor test suite.

Ensures the repository root is importable so tests can `import anchor`
(the stdlib-only CLI engine) regardless of the working directory pytest
is invoked from.

It ALSO installs the suite-wide determinism harness (added to kill systemic
streaming/thread flakiness in the full-suite gate):

1. A process-wide ``threading.excepthook`` that SWALLOWS *benign* daemon-thread
   teardown exceptions — a leaked SSE/WS pump or ``serve_forever`` request
   thread that loses its client mid-flight, or reads a session that a teardown
   already reaped, raises late and pytest's threadexception plugin would
   otherwise attribute that benign noise to whatever unrelated test happens to
   be running and FAIL it. Non-benign thread exceptions are delegated to the
   previous hook untouched, so real bugs still surface.

2. An autouse, function-scoped reap fixture that, after EACH test, best-effort
   shuts down any HTTP servers / stream threads the test leaked and resets the
   shared live PTY/job tables — so leakage can't bleed into the next test.

Both are strictly teardown/infra hardening: no test assertion and no product
behavior is changed. Everything is best-effort and guarded — the harness never
fails a test in teardown.
"""
import sys
import threading
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# ──────────────────────────────────────────────────────────────────────────────
# Billing safety net: default BOTH model-spawn seams to the stubs, suite-wide
# ──────────────────────────────────────────────────────────────────────────────
# Model spawns fire as BACKGROUND side effects of innocent tests — the
# project-blurb / session-summary threads and PTY session starts resolve their
# command from the environment at spawn time. A test that didn't set the seams
# fell through to ``DEFAULT_RUNNER_CMD`` (real ``claude -p``) / real ConPTY
# ``claude`` and incurred REAL BILLING (8,816 live sessions leaked from this
# suite's tmp dirs between 2026-06-20 and 2026-07-14).
#
# FAIL-CLOSED (2026-07-26 hardening). This used to ``setdefault``, so ANY ambient
# value in the shell/profile/service environment silently WON — and
# ``pty_manager.select_backend`` treats anything that is not exactly ``"stub"`` as
# the REAL ConPTY backend, so a stray/typo'd ``ANCHOR_PTY_BACKEND`` re-armed live
# spawns across 62 test files. The guard is now a hard assignment: under test the
# seams are OURS. ``monkeypatch`` (used by the delenv/restore tests) still wins
# per-test because it mutates os.environ after this import-time block.
# A deliberate live run must opt in with ``ANCHOR_TESTS_ALLOW_LIVE=1``.
import os

if os.environ.get("ANCHOR_TESTS_ALLOW_LIVE", "").strip() != "1":
    _TESTS_DIR = Path(__file__).resolve().parent
    _FAKE_CLAUDE = _TESTS_DIR / "fake_claude.py"
    _STUB_GH = _TESTS_DIR / "stub_gh.py"
    os.environ["ANCHOR_RUNNER_CMD"] = f"python {_FAKE_CLAUDE}"
    os.environ["ANCHOR_PTY_BACKEND"] = "stub"
    # The interactive-terminal path has no ANCHOR_RUNNER_CMD equivalent — it
    # resolves the RAW engine binary. ANCHOR_ENGINE_CMD is the matching seam
    # (terminal_session._resolve_engine_cmd), so ANCHOR_PTY_BACKEND is no longer
    # a single point of failure for every terminal test.
    os.environ["ANCHOR_ENGINE_CMD"] = f"{sys.executable} -c pass"
    # gh reachable a real `gh repo create` from two healthcheck/cli tests.
    if _STUB_GH.exists():
        os.environ["ANCHOR_GH_CMD"] = f"python {_STUB_GH}"

import subprocess
if sys.platform == "win32":
    _orig_run = getattr(subprocess, "run", None)
    _orig_popen = subprocess.Popen
    _orig_check_output = getattr(subprocess, "check_output", None)
    _orig_call = getattr(subprocess, "call", None)
    _orig_check_call = getattr(subprocess, "check_call", None)

    def _inject(kwargs):
        if "creationflags" not in kwargs:
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

    def _patched_run(*args, **kwargs):
        _inject(kwargs)
        return _orig_run(*args, **kwargs)

    class _PatchedPopen(_orig_popen):
        def __init__(self, *args, **kwargs):
            _inject(kwargs)
            super().__init__(*args, **kwargs)

    def _patched_check_output(*args, **kwargs):
        _inject(kwargs)
        return _orig_check_output(*args, **kwargs)

    def _patched_call(*args, **kwargs):
        _inject(kwargs)
        return _orig_call(*args, **kwargs)

    def _patched_check_call(*args, **kwargs):
        _inject(kwargs)
        return _orig_check_call(*args, **kwargs)

    if _orig_run:
        subprocess.run = _patched_run
    subprocess.Popen = _PatchedPopen
    if _orig_check_output:
        subprocess.check_output = _patched_check_output
    if _orig_call:
        subprocess.call = _patched_call
    if _orig_check_call:
        subprocess.check_call = _patched_check_call

# ──────────────────────────────────────────────────────────────────────────────
# Benign daemon-thread teardown classifier
# ──────────────────────────────────────────────────────────────────────────────
def _is_benign_thread_teardown(exc):
    """True for a benign exception raised by a leaked daemon thread on teardown.

    This is the SUPERSET the threadexception hook is allowed to swallow:

    * the production socket-teardown set already defined as
      ``anchor_gui._is_benign_disconnect`` (BrokenPipeError / ConnectionResetError
      / ConnectionAbortedError / OSError winerror 10053/10054) — a client that
      went away mid SSE/WS/HTTP write; PLUS
    * ``ValueError("I/O operation on closed file")`` — an SSE pump flushing onto
      a ``wfile`` that the request thread's teardown already closed; PLUS
    * a ``KeyError`` / "unknown session" style ``RuntimeError`` from a stream
      loop reading a session that a fixture teardown already reaped.

    Everything else returns False → delegated to the previous hook (real bugs
    still surface). Deliberately TIGHT (matched on type + message), never a
    blanket swallow.
    """
    if exc is None:
        return False
    # Reuse the exact production benign-disconnect set when importable.
    try:
        import anchor_gui
        if anchor_gui._is_benign_disconnect(exc):
            return True
    except Exception:
        # Fall back to a local copy of the production predicate if anchor_gui
        # can't be imported in this teardown context.
        if isinstance(exc, (BrokenPipeError, ConnectionResetError,
                            ConnectionAbortedError)):
            return True
        if isinstance(exc, OSError) and getattr(exc, "winerror", None) in (10053, 10054):
            return True

    msg = str(exc)
    # An SSE/stream pump writing/flushing onto a wfile the request teardown
    # already closed.
    if isinstance(exc, ValueError) and "closed file" in msg:
        return True
    # A stream loop reading a session the test teardown already reaped.
    if isinstance(exc, KeyError):
        return True
    if isinstance(exc, RuntimeError) and (
            "unknown session" in msg.lower() or "reaped" in msg.lower()):
        return True
    return False


# ──────────────────────────────────────────────────────────────────────────────
# Process-wide threading.excepthook: swallow ONLY benign teardown noise
# ──────────────────────────────────────────────────────────────────────────────
_PREV_THREAD_EXCEPTHOOK = None


def _thread_excepthook(args):
    """Swallow benign daemon-thread teardown exceptions; delegate the rest.

    ``args`` is a ``threading.ExceptHookArgs`` (exc_type, exc_value,
    exc_traceback, thread). For a benign teardown exception we return silently
    (so pytest's threadexception plugin never sees it and can't fail an
    unrelated test). For anything else we delegate to the previous hook so a
    genuine defect still raises the normal warning/error.
    """
    if _is_benign_thread_teardown(getattr(args, "exc_value", None)):
        return
    if _PREV_THREAD_EXCEPTHOOK is not None:
        _PREV_THREAD_EXCEPTHOOK(args)
    else:  # pragma: no cover - threading always installs a default hook
        threading.__excepthook__(args)


def pytest_configure(config):
    """Install the benign-teardown threading excepthook once for the session."""
    global _PREV_THREAD_EXCEPTHOOK
    if _PREV_THREAD_EXCEPTHOOK is None:
        _PREV_THREAD_EXCEPTHOOK = threading.excepthook
        threading.excepthook = _thread_excepthook

    # W1 (rearch 2026-07): opt-in write-site tripwire. When the orchestrator
    # runs the suite with ANCHOR_WRITE_TRIPWIRE=inventory (or =enforce, once
    # the journal lands), every .anchor/ write across the WHOLE suite is
    # recorded into the mutation-of-record inventory. Off by default; a plain
    # test run is untouched. Best-effort — a tripwire import/install failure
    # never breaks the suite.
    global _TRIPWIRE_MOD
    try:
        import os as _os
        from tools import write_tripwire as _wt
        mode = _wt.env_requested_mode(_os.environ)
        if mode is not None:
            _wt.install(mode=mode, clear=False)
            _TRIPWIRE_MOD = _wt
    except Exception:
        _TRIPWIRE_MOD = None


_TRIPWIRE_MOD = None


def pytest_unconfigure(config):
    """Restore the previous threading excepthook at session end."""
    global _PREV_THREAD_EXCEPTHOOK
    if _PREV_THREAD_EXCEPTHOOK is not None:
        threading.excepthook = _PREV_THREAD_EXCEPTHOOK
        _PREV_THREAD_EXCEPTHOOK = None

    # W1 (rearch 2026-07): flush + uninstall the opt-in write-site tripwire.
    # The inventory artifact accumulates (merge=True) so suite + healthcheck
    # runs fold into one checked-in mutation-of-record inventory.
    global _TRIPWIRE_MOD
    if _TRIPWIRE_MOD is not None:
        try:
            import os as _os
            _TRIPWIRE_MOD.write_inventory(
                _os.environ.get("ANCHOR_TRIPWIRE_INVENTORY") or None,
                merge=True)
        except Exception:
            pass
        try:
            _TRIPWIRE_MOD.uninstall()
        except Exception:
            pass
        _TRIPWIRE_MOD = None


# ──────────────────────────────────────────────────────────────────────────────
# Autouse reap: stop leaked servers/stream threads + reset shared live tables
# ──────────────────────────────────────────────────────────────────────────────
def _looks_like_server_or_stream(thread):
    """Heuristic: a daemon thread running a server-loop / SSE pump / job reader."""
    name = (thread.name or "").lower()
    if any(tok in name for tok in (
            "serve_forever", "_serve", "job-reader", "stream", "sse", "pump")):
        return True
    # socketserver request threads + our server loops show up via the target's
    # qualified name; sniff the run target where reachable.
    target = getattr(thread, "_target", None)
    qual = (getattr(target, "__qualname__", "") or "").lower()
    return any(tok in qual for tok in (
        "serve_forever", "_serve", "process_request", "stream", "reader"))


def _best_effort_stop_servers(leaked):
    """Best-effort: shut down the server(s) the LEAKED threads belong to.

    A test that started a server via ``serve_forever`` in a daemon thread but
    didn't ``shutdown()``/``server_close()`` leaves the thread blocked in the
    selector. Every suite server thread uses the bound-method pattern
    (``Thread(target=srv.serve_forever)``), so the leaked loop's own server is
    reachable via ``target.__self__`` and is stopped PRECISELY.

    What is deliberately NOT done anymore: sweeping ``gc`` for EVERY live
    ``socketserver.BaseServer`` on any leak. A per-request worker of a healthy
    server (``process_request_thread``) routinely outlives its test by a few
    milliseconds under load; the old global sweep classified that straggler as
    leakage and shut down ALL servers — including a still-owned module-scoped
    fixture server, refusing every later test in the module. A straggling
    request worker now gets a short join (it exits on its own once the
    response is flushed); its OWNING server is never torn down over it. The
    global gc sweep survives only as the fallback for a leaked serve loop
    whose server object cannot be resolved (a closure-wrapped target).
    Guarded — never raises out of teardown.
    """
    try:
        import gc
        import socketserver
    except Exception:
        return

    def _stop(server):
        try:
            # Only servers still in a serve_forever loop expose this flag
            # as a usable Event; shutdown() is a no-op/safe otherwise.
            server.shutdown()
        except Exception:
            pass
        try:
            server.server_close()
        except Exception:
            pass

    try:
        to_stop, sweep = [], False
        for t in leaked:
            target = getattr(t, "_target", None)
            qual = (getattr(target, "__qualname__", "") or "").lower()
            name = (t.name or "").lower()
            owner = getattr(target, "__self__", None)
            if "process_request" in qual:
                # A straggling per-request worker of a live server, not a
                # leaked server: give it a beat to finish flushing.
                t.join(timeout=2.0)
                continue
            if isinstance(owner, socketserver.BaseServer):
                to_stop.append(owner)
            elif any(tok in qual for tok in ("serve_forever", "_serve")) or \
                    any(tok in name for tok in ("serve_forever", "_serve")):
                sweep = True  # a leaked serve loop with no resolvable server
        for srv in to_stop:
            _stop(srv)
        if sweep:
            for obj in gc.get_objects():
                if isinstance(obj, socketserver.BaseServer):
                    _stop(obj)
    except Exception:
        pass


def _best_effort_reset_live_tables():
    """Reset the shared module-level live PTY/job tables so a leaked live
    session can't bleed into the next test (shared registry/port contention)."""
    for mod_name, fn_name in (
            ("pty_manager", "_reset_live_table_for_tests"),
            ("job_runner", "_reset_live_table_for_tests")):
        mod = sys.modules.get(mod_name)
        if mod is None:
            continue
        fn = getattr(mod, fn_name, None)
        if callable(fn):
            try:
                fn()
            except Exception:
                pass


@pytest.fixture(autouse=True)
def _reap_leaked_streams_and_servers():
    """After EACH test, reap server/stream-thread leakage (best-effort).

    Snapshots the live thread set before the test; after it, finds daemon
    threads started DURING the test that are still alive and look like a server
    loop / SSE pump / job reader, shuts down any reachable HTTP server instance,
    and resets the shared live PTY/job tables. Strictly teardown infra — it
    never fails the test (every step is guarded) and changes no assertion.
    """
    before = set(threading.enumerate())
    try:
        yield
    finally:
        try:
            after = list(threading.enumerate())
            leaked = [t for t in after
                      if t not in before and t.is_alive() and t.daemon
                      and _looks_like_server_or_stream(t)]
            if leaked:
                _best_effort_stop_servers(leaked)

            # Wait for any leaked background summarize_session threads to finish
            # before the next test starts, to prevent their subprocesses from
            # inheriting the next test's monkeypatched STUB_SUMMARIZER_COUNTER.
            for t in after:
                if t not in before and t.is_alive():
                    qual = getattr(getattr(t, "_target", None), "__qualname__", "")
                    if "summarize_session" in qual:
                        t.join(timeout=5.0)

            # Reset the shared live tables regardless of detected leaks — a
            # cheap idempotent guard against cross-test session/port bleed.
            _best_effort_reset_live_tables()
        except Exception:
            # Teardown must never fail a test.
            pass
