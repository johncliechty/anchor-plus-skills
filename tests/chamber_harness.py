"""Shared chamber-build test harness (steward-chamber W3).

Boots a hermetic Anchor server (temp data dir, stub PTY, OS-assigned port —
never :8777) in an explicit auth posture, with an optional POST **dispatch
shim** for the F6 red-to-green proofs.

The dispatch shim replaces ``AnchorHandler._strangler_dispatch`` with a
function that answers a marker JSON for every POST and delegates GETs to the
real dispatcher. It is installed AFTER the real ``do_POST`` token middleware
in the request path — the middleware runs first, on a real socket, exactly as
in production — so:

* a request that gets the marker back has PASSED the production auth gate;
* a request that gets a 401 was refused BY the production auth gate;
* no real mutating handler body ever executes (no side effects, no spawns,
  no slow paths), which is what makes probing the ENTIRE state-changing
  route inventory tractable inside the wave gate.

Auth-on legs that expect a 401 never reach the shim at all — those proofs are
full-stack with or without it.

This module is deliberately import-light: test files build their own thin
pytest fixtures over :func:`boot_server` / :func:`stop_server`.
"""
from __future__ import annotations

import importlib
import os
import threading
import time

#: The distro secret-scanner allowlists this exact placeholder
#: (distro._PLACEHOLDER_VALUES) — same token the sibling auth suites use.
TEST_TOKEN = "s3cret"

#: Modules whose state binds to ANCHOR_DATA_DIR / auth env at import-reload
#: time. Mirrors the reload list the existing auth-ON steward suite uses.
_RELOAD_MODULES = (
    "paths", "job_runner", "pty_manager", "rnd_registry", "effort_history",
    "sessions", "anchor_marker", "session_registry", "worktrees", "lanes",
    "summarizer", "report_viewer", "handoff", "boneyard", "terminal_session",
)

_ENV_KEYS = ("ANCHOR_DATA_DIR", "ANCHOR_PTY_BACKEND", "ANCHOR_TOKEN",
             "ANCHOR_AUTH_MODE")


def boot_server(tmp_path, *, token=None, auth_mode=None, shim_dispatch=False):
    """Boot a hermetic Anchor server in an explicit auth posture.

    ``token=None`` boots the AUTH-OFF condition (``ANCHOR_TOKEN`` unset and
    ``ANCHOR_AUTH_MODE`` cleared — the exact condition under which the chamber
    shipped broken twice). ``token=<str>`` boots auth-ON; add
    ``auth_mode='enforce'`` to also gate the data-plane GET surface.

    Returns a handle dict: ``base``, ``port``, ``gui``, ``stop()`` (idempotent
    teardown restoring env + un-shimming).
    """
    data = tmp_path / ("data-authon" if token else "data-authoff")
    data.mkdir(parents=True, exist_ok=True)

    saved = {k: os.environ.get(k) for k in _ENV_KEYS}
    os.environ["ANCHOR_DATA_DIR"] = str(data)
    os.environ["ANCHOR_PTY_BACKEND"] = "stub"
    if token:
        os.environ["ANCHOR_TOKEN"] = token
    else:
        os.environ.pop("ANCHOR_TOKEN", None)
    if auth_mode:
        os.environ["ANCHOR_AUTH_MODE"] = auth_mode
    else:
        # An inherited enforce-mode would make even the auth-off posture 401
        # everything (paths.auth_ok fails closed under enforce) — the harness
        # sets the posture EXPLICITLY, never by inheritance.
        os.environ.pop("ANCHOR_AUTH_MODE", None)

    for name in _RELOAD_MODULES:
        importlib.reload(importlib.import_module(name))
    import paths
    paths.ensure_data_dirs()
    import anchor_gui
    gui = importlib.reload(anchor_gui)

    unshim = None
    if shim_dispatch:
        unshim = install_dispatch_shim(gui)

    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777, "a test server must never bind the live Anchor port"
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()

    state = {"stopped": False}

    def stop():
        if state["stopped"]:
            return
        state["stopped"] = True
        try:
            srv.shutdown()
        except Exception:
            pass
        time.sleep(0.15)
        try:
            srv.server_close()
        except Exception:
            pass
        thread.join(timeout=5)
        if unshim is not None:
            try:
                unshim()
            except Exception:
                pass
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        try:
            import pty_manager
            pty_manager._reset_live_table_for_tests()
        except Exception:
            pass

    return {"base": "http://127.0.0.1:%d" % port, "port": port,
            "gui": gui, "server": srv, "stop": stop}


def install_dispatch_shim(gui):
    """Swap the post-auth dispatch boundary for a marker responder.

    Every POST that reaches dispatch (i.e. PASSED the do_POST token
    middleware) answers ``{ok: true, <DISPATCH_MARKER_KEY>: true, path}`` and
    is fully handled — neither the strangler's migrated handlers nor the
    legacy if/elif chain ever run. GETs delegate to the real dispatcher
    untouched. Returns an ``uninstall()`` callable.
    """
    import chamber_enforcement as ce

    orig = gui.AnchorHandler._strangler_dispatch

    def shim(self, method, path, body=None):
        if method == "POST":
            self._send_json(
                {"ok": True, ce.DISPATCH_MARKER_KEY: True, "path": path}, 200)
            return True
        return orig(self, method, path, body)

    gui.AnchorHandler._strangler_dispatch = shim

    def uninstall():
        gui.AnchorHandler._strangler_dispatch = orig

    return uninstall
