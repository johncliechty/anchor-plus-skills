"""
Anchor Dashboard Launcher (browser-only).

Double-click this file (or the taskbar/desktop shortcut) to open the Anchor
dashboard in your default browser. It runs silently (no terminal window).

IMPORTANT — this launcher does NOT start a server.
The Anchor server runs PERSISTENTLY in the background under the NSSM Windows
service ``anchor`` (it owns http://localhost:8777). If a launcher spawned its
own ``python anchor_gui.py``, that second process would compete for port 8777,
squat it, and serve stale (pre-deploy) file contents — the exact duplicate /
zombie-server bug this file used to cause. So the only thing this launcher does
is open the URL. If the dashboard does not load, the service is down; restart it
from an elevated shell with ``nssm restart anchor``.
"""

import webbrowser

URL = "http://localhost:8777"

if __name__ == "__main__":
    webbrowser.open(URL)
