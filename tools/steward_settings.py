"""Steward runtime settings & session reboot tool (v1.4.7).

Allows the AI Cockpit steward (or CLI caller) to inspect or update Claude /
provider permissions, fence status, model, effort, and automatically reboot the
underlying Claude Code / provider session while preserving the conversation.

Examples:
  python C:/dev/Anchor/tools/steward_settings.py show
  python C:/dev/Anchor/tools/steward_settings.py apply --permission-mode bypassPermissions --fence off --reboot
  python C:/dev/Anchor/tools/steward_settings.py apply --fence on --reboot
  python C:/dev/Anchor/tools/steward_settings.py apply --model opus --effort high --reboot
  python C:/dev/Anchor/tools/steward_settings.py reboot
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ANCHOR = Path(__file__).resolve().parent.parent
if str(ANCHOR) not in sys.path:
    sys.path.insert(0, str(ANCHOR))
from tools.steward_code_job import project_for  # noqa: E402


def _auth_token() -> str:
    tok = os.environ.get("ANCHOR_TOKEN", "").strip()
    if tok:
        return tok
    try:
        import paths
        return paths.read_or_create_token()
    except Exception:
        return ""


def main():
    ap = argparse.ArgumentParser(description="Configure AI Cockpit session permissions/settings and reboot.")
    ap.add_argument("action", choices=("show", "apply", "reboot"))
    ap.add_argument("--permission-mode", dest="permission_mode", default="",
                    help="Claude permission mode: bypassPermissions (yolo), default, acceptEdits, plan")
    ap.add_argument("--fence", choices=("on", "off", ""), default="",
                    help="Enable ('on') or disable ('off') the effort-folder write fence")
    ap.add_argument("--model", default="",
                    help="Provider model override (e.g., opus, sonnet, haiku, best)")
    ap.add_argument("--effort", default="",
                    help="Reasoning effort override (e.g., max, high, medium, low)")
    ap.add_argument("--reboot", action="store_true",
                    help="Stop and reboot the underlying Claude Code / provider subprocess with the updated settings")
    ap.add_argument("--port", default=os.environ.get("ANCHOR_PORT", "8777"))
    a = ap.parse_args()

    cwd = os.environ.get("ANCHOR_STEWARD_DIR") or os.getcwd()
    pid, rel = project_for(cwd)
    body = {
        "dir": rel,
        "action": a.action,
        "permission_mode": a.permission_mode,
        "fence": a.fence,
        "model": a.model,
        "effort": a.effort,
        "reboot": True if a.action == "reboot" else bool(a.reboot),
        "from_steward_tool": True,
    }
    req = urllib.request.Request(
        f"http://127.0.0.1:{a.port}/api/steward/configure_session?pid={pid}",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + _auth_token(),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            print(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(e.read().decode("utf-8", "replace"))
        sys.exit(1)


if __name__ == "__main__":
    main()
