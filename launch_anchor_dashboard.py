#!/usr/bin/env python3
"""Ensure local Anchor dashboard is up, then open the default browser.

Desktop / taskbar entrypoint for Package B (North Star: simple collaborator shell).

Behavior:
  1. Probe local dashboard URL (loopback only).
  2. If down → start service (injectable; production uses share_onboard.start_package_b_service).
  3. Re-probe briefly; open browser when OK (or open anyway with honesty if still down).

Never raises to the shell for probe failures — returns a report dict when used as a module.
CLI: exit 0 if browser open attempted after OK probe, 2 if still unreachable after start.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import webbrowser
from pathlib import Path

# Package root on sys.path when launched as a script from the package tree.
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import share_onboard as sob  # noqa: E402

DEFAULT_URL = sob.DEFAULT_LOCAL_DASHBOARD_URL
# v1.1.3: a COLD anchor_gui boot (large module import + boot reconcile) can
# take several seconds — 8×0.5s raced it and gave up. 40×0.5s (~20s) covers a
# slow first boot on a modest collaborator box; an already-running server
# still short-circuits instantly.
DEFAULT_RETRIES = 40
DEFAULT_SLEEP_S = 0.5


def ensure_dashboard_running(
    *,
    url: str = DEFAULT_URL,
    probe_fn=None,
    start_fn=None,
    open_fn=None,
    retries: int = DEFAULT_RETRIES,
    sleep_s: float = DEFAULT_SLEEP_S,
    home=None,
    token: str | None = None,
    open_browser: bool = True,
) -> dict:
    """Probe → start if needed → re-probe → optional browser open.

    Injectable seams for hermetic tests (no live :8777, no real service).
    """
    url = (url or DEFAULT_URL).strip()
    report = {
        "url": url,
        "already_running": False,
        "start_attempted": False,
        "start_result": None,
        "probe_before": None,
        "probe_after": None,
        "browser_opened": False,
        "ok": False,
        "reason_codes": [],
    }

    if not sob.is_local_dashboard_url(url):
        report["reason_codes"].append("non_local_dashboard_url")
        return report

    before = sob.probe_local_dashboard(url, probe_fn=probe_fn)
    report["probe_before"] = before

    if before.get("ok"):
        report["already_running"] = True
        report["probe_after"] = before
        report["ok"] = True
    else:
        report["start_attempted"] = True
        if start_fn is not None:
            start_result = start_fn()
        else:
            # v1.1.3: start the server on the PORT this launcher is probing,
            # so a non-default ANCHOR_DASHBOARD_URL is honored end-to-end.
            from urllib.parse import urlparse as _up
            try:
                _port = _up(url).port
            except ValueError:
                _port = None
            start_result = sob.start_package_b_service(
                home=home, token=token, port=_port)
        report["start_result"] = start_result

        after = before
        for _ in range(max(1, int(retries))):
            after = sob.probe_local_dashboard(url, probe_fn=probe_fn)
            if after.get("ok"):
                break
            if sleep_s and sleep_s > 0:
                time.sleep(sleep_s)
        report["probe_after"] = after
        report["ok"] = bool(after.get("ok"))
        if not report["ok"]:
            report["reason_codes"].append("anchor_service_unavailable")

    if open_browser:
        opener = open_fn if open_fn is not None else webbrowser.open
        # v1.1.3 token hand-off: give the dashboard the token ONCE via the
        # loopback URL. The page stores it (localStorage), mints the HttpOnly
        # auth cookie (POST /api/auth/login), and strips it from the URL —
        # after that, navigation + API calls authenticate without a token in
        # any page URL. Loopback-only by construction (checked above).
        open_url = url
        if token:
            from urllib.parse import quote
            sep = "&" if "?" in url else "?"
            open_url = url + sep + "token=" + quote(token, safe="")
        try:
            opener(open_url)
            report["browser_opened"] = True
        except Exception as exc:
            report["reason_codes"].append("browser_open_failed")
            report["browser_error"] = str(exc)

    return report


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Start Anchor service if needed, then open the local dashboard."
    )
    p.add_argument(
        "--url",
        default=os.environ.get("ANCHOR_DASHBOARD_URL", DEFAULT_URL),
        help="Local dashboard URL (default http://localhost:8777)",
    )
    p.add_argument(
        "--home",
        default=None,
        help="Optional Anchor home for service start context",
    )
    p.add_argument(
        "--no-browser",
        action="store_true",
        help="Ensure service only; do not open a browser",
    )
    p.add_argument(
        "--retries",
        type=int,
        default=DEFAULT_RETRIES,
        help="Re-probe attempts after start",
    )
    args = p.parse_args(argv)

    # v1.1.3: resolve the onboard-minted token so (a) a spawned server gets it
    # in its env (mutating APIs + terminals gated by default) and (b) the
    # browser receives it once via the loopback URL. Never printed/logged.
    token = (os.environ.get("ANCHOR_TOKEN") or "").strip() or \
        sob.read_onboard_token()

    report = ensure_dashboard_running(
        url=args.url,
        home=args.home,
        token=token,
        open_browser=not args.no_browser,
        retries=args.retries,
    )
    if report.get("already_running"):
        print("Anchor dashboard already running at %s" % report["url"])
    elif report.get("start_attempted"):
        print("Anchor service start attempted for %s" % report["url"])
    if report.get("browser_opened"):
        print("Opened browser to %s" % report["url"])
    if report.get("ok"):
        return 0
    print(
        "Anchor dashboard not reachable at %s (%s)"
        % (report["url"], ",".join(report.get("reason_codes") or ["unknown"])),
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
