#!/usr/bin/env python3
"""Wave 1 empirical spike — real ConPTY child under a simulated `anchor` service.

This is NOT a pytest test. It is the runnable hard gate for v3 Wave 1
(Implementation-Plan §"Wave 1 — ConPTY-under-service spike"): prove that a REAL
``pywinpty`` (ConPTY) child can spawn and round-trip bytes bidirectionally under
a faithful simulation of the non-interactive ``anchor`` NSSM service context
(Windows session 0, no loaded user profile) BEFORE the rest of v3 is built on it.

Run it manually / via the orchestrator:

    python spike_conpty_service.py            # uses cmd.exe (safe default)
    python spike_conpty_service.py --child claude   # uses interactive claude

It launches the child via the pywinpty backend in ``pty_manager``, writes a
command echoing a nonce, reads the PTY output back, and asserts the nonce
round-trips. It prints a single ``SPIKE PASS`` / ``SPIKE FAIL`` line and exits 0
on pass, non-zero on fail. A bounded timeout guarantees it never hangs.

Service-context simulation (per anchor-runtime-facts memory, the documented
pitfall): the ``anchor`` service runs as ``.\\john`` with ``USERPROFILE`` and
``HOME`` pinned to ``C:\\Users\\example`` and NO loaded user profile (so no
``APPDATA``/``LOCALAPPDATA``). The CORRECT way to simulate it is the FULL current
process environment (which includes ``SystemRoot``/``windir`` — omitting those
fast-fail-crashes ``claude`` with ``0xC0000409``) with the profile vars stripped
and ``USERPROFILE``/``HOME`` forced. We deliberately do NOT use
``GetEnvironmentVariables('Machine')`` for exactly this reason.
"""

import argparse
import os
import sys
import time
import uuid

import pty_manager


JOHN_HOME = r"C:\Users\example"

# Read window + overall timeout bounds so the spike can NEVER hang.
READ_TIMEOUT_S = 20.0
READ_POLL_S = 0.1


def simulated_service_env():
    """Build a faithful simulation of the `anchor` service's environment.

    Start from the FULL current process environment (keeps SystemRoot/windir,
    PATH, PATHEXT — required so a native child like ``claude`` does not
    fast-fail-crash with 0xC0000409), then:
      - force ``USERPROFILE`` and ``HOME`` to ``C:\\Users\\example`` (the service
        runs as ``.\\john`` and Anchor pins these so ``claude`` finds
        ``~\\.claude\\.credentials.json``), and
      - drop the loaded-profile-only vars ``APPDATA`` / ``LOCALAPPDATA`` (the
        non-interactive service has no loaded user profile; the auth path does
        not need them — verified 2026-06-10).
    """
    env = dict(os.environ)
    env["USERPROFILE"] = JOHN_HOME
    env["HOME"] = JOHN_HOME
    for k in ("APPDATA", "LOCALAPPDATA"):
        env.pop(k, None)
    return env


def _child_argv(child):
    """Resolve the child command argv. ``cmd`` (default) is the safe spike
    target; ``claude`` exercises the real interactive engine."""
    if child == "cmd":
        # /V:ON delayed expansion (so !R! expands at run time), /Q echo off,
        # /K keep open so we can drive a command then read its computed output.
        return ["cmd.exe", "/V:ON", "/Q", "/K"]
    if child == "claude":
        return ["claude"]
    # Allow an explicit full command string too.
    return child.split()


def run_spike(child="cmd", verbose=True):
    """Launch a real ConPTY child, round-trip a nonce, return (ok, detail)."""
    nonce = uuid.uuid4().hex[:12]
    env = simulated_service_env()
    argv = _child_argv(child)

    # For the cmd path, require the child to have EXECUTED something: pick two
    # random ints and have cmd COMPUTE their product. The expected marker embeds
    # the product, which never appears in anything we type — input-echo alone
    # cannot satisfy it; only real command execution can.
    import random
    _a = random.randint(1000, 9999)
    _b = random.randint(1000, 9999)
    _product = _a * _b
    if child == "cmd":
        marker = f"SPIKEOUT={_product}"
    else:
        marker = f"CONPTY_OK_{nonce}"

    # Force the REAL pywinpty backend for the spike (never the stub).
    os.environ.pop(pty_manager.BACKEND_ENV, None)

    if verbose:
        print(f"[spike] backend     = {pty_manager.select_backend().name}")
        print(f"[spike] child argv  = {argv}")
        print(f"[spike] USERPROFILE = {env.get('USERPROFILE')}")
        print(f"[spike] HOME        = {env.get('HOME')}")
        print(f"[spike] APPDATA in env: {'APPDATA' in env} "
              f"(expected False)")
        print(f"[spike] nonce marker= {marker}")

    sid = None
    try:
        sid = pty_manager.start(argv, cwd=JOHN_HOME, env=env)
    except pty_manager.PtyUnavailable as exc:
        return False, f"pywinpty unavailable: {exc}"
    except Exception as exc:
        return False, f"failed to spawn child: {exc!r}"

    try:
        # Give the child a beat to come up, then write a command that echoes the
        # nonce. ``echo`` works in cmd; for ``claude`` the user-typed line is
        # echoed by the TUI itself, which is enough to prove bidirectional bytes.
        time.sleep(0.6)
        cursor = pty_manager.read_since(sid, 0)["next"]  # skip the banner
        if child == "cmd":
            # Compute the product in-shell, then echo the DISTINCT result token.
            # The product is never typed, so PASS proves cmd actually executed.
            pty_manager.write(sid, f"set /a R={_a}*{_b}\r\n")
            pty_manager.write(sid, "echo SPIKEOUT=!R!\r\n")
        else:
            pty_manager.write(sid, f"{marker}\r\n")

        deadline = time.time() + READ_TIMEOUT_S
        seen = ""
        while time.time() < deadline:
            out = pty_manager.read_since(sid, cursor)
            if out["text"]:
                seen += out["text"]
                cursor = out["next"]
                if marker in seen:
                    break
            if out["status"] == "dead" and marker not in seen:
                # Child exited; one last drain already captured above.
                break
            time.sleep(READ_POLL_S)

        if marker in seen:
            return True, f"nonce {marker} round-tripped bidirectionally"
        return False, (f"nonce {marker} NOT seen in PTY output within "
                       f"{READ_TIMEOUT_S}s; captured {len(seen)} chars")
    finally:
        if sid is not None:
            try:
                pty_manager.kill(sid)
            except Exception:
                pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--child", default="cmd",
        help="child to launch: 'cmd' (default, safe) | 'claude' | a command string")
    parser.add_argument("--quiet", action="store_true",
                        help="suppress the diagnostic preamble")
    args = parser.parse_args(argv)

    ok, detail = run_spike(child=args.child, verbose=not args.quiet)
    if ok:
        print(f"SPIKE PASS — {detail}")
        return 0
    print(f"SPIKE FAIL — {detail}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
