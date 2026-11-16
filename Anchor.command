#!/usr/bin/env bash
# Anchor.command — Double-clickable Standalone Native GUI Launcher for macOS & Linux (Anchor v1.5.2)
# Connects to a remote Mother Ship (e.g. https://gwl-server.tailb49f65.ts.net) when configured in
# settings.json (or via --mothership <url>), or starts the local background Mother Ship service with
# --no-browser, then opens the standalone native Anchor desktop GUI window (never a web browser).

set -euo pipefail

# Resolve symlink target so Desktop symlink points back to the Anchor repo
SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"
done
ANCHOR_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
OS_NAME="$(uname -s)"

cd "$ANCHOR_DIR"

if [ "$OS_NAME" = "Darwin" ]; then
  SHELL_DATA_DIR="${HOME}/Library/Application Support/anchor-shell"
else
  XDG_BASE="${XDG_DATA_HOME:-${HOME}/.local/share}"
  SHELL_DATA_DIR="${XDG_BASE}/anchor-shell"
fi
SETTINGS_JSON="$SHELL_DATA_DIR/settings.json"

echo "=================================================================="
echo "  Anchor v$(cat VERSION 2>/dev/null || echo '1.5.2') — Standalone Native GUI Launcher"
echo "  Folder: $ANCHOR_DIR"
echo "=================================================================="

if [ "${1:-}" = "--update" ]; then
  echo "[*] Pulling latest Anchor update and syncing 20 Foundry skills..."
  python3 -c "import mothership_updater, pathlib; print(mothership_updater.pull_latest_update(pathlib.Path.cwd(), restart_service=False))"
  shift
fi

if [ "${1:-}" = "--mothership" ] && [ -n "${2:-}" ]; then
  TARGET_MS="$2"
  shift 2
  python3 - "$SETTINGS_JSON" "$TARGET_MS" <<'PY'
import json, pathlib, sys
sf = pathlib.Path(sys.argv[1])
url = sys.argv[2].strip().rstrip("/")
if "://" not in url:
    url = "https://" + url
sf.parent.mkdir(parents=True, exist_ok=True)
data = {}
if sf.is_file():
    try:
        data = json.loads(sf.read_text(encoding="utf-8"))
    except Exception:
        data = {}
data["address"] = url
sf.write_text(json.dumps(data, indent=2) + "
", encoding="utf-8")
print(f"[*] Saved Mother Ship address -> {url} in {sf}")
PY
  # Stop any local port-8777 service and close any existing Anchor window so it reconnects cleanly
  lsof -ti tcp:8777 -sTCP:LISTEN 2>/dev/null | xargs kill -15 2>/dev/null || true
  pkill -f "Anchor.app/Contents/MacOS/Anchor" 2>/dev/null || true
  pkill -f "anchor_shell.py" 2>/dev/null || true
  sleep 1
fi

# Check whether settings.json points to a remote https:// Mother Ship
SAVED_ADDR="$(python3 - "$SETTINGS_JSON" <<'PY'
import json, pathlib, sys
sf = pathlib.Path(sys.argv[1])
if sf.is_file():
    try:
        print(str(json.loads(sf.read_text(encoding="utf-8")).get("address") or "").strip())
    except Exception:
        pass
PY
)"

if [[ "$SAVED_ADDR" == https://* ]]; then
  echo "[*] Connecting standalone native GUI to remote Mother Ship: $SAVED_ADDR"
  # Ensure no unneeded local server is running on port 8777
  lsof -ti tcp:8777 -sTCP:LISTEN 2>/dev/null | xargs kill -15 2>/dev/null || true
else
  # Local Mother Ship mode: ensure background service is running WITHOUT opening any browser
  python3 launch_anchor_dashboard.py --no-browser
fi

# Launch the standalone native GUI window (Anchor.app on macOS / anchor_shell.py via pywebview)
if [ "$OS_NAME" = "Darwin" ]; then
  if [ -d "/Applications/Anchor.app" ]; then
    open -a "/Applications/Anchor.app"
    exit 0
  elif [ -d "$ANCHOR_DIR/shell/dist/Anchor.app" ]; then
    open -a "$ANCHOR_DIR/shell/dist/Anchor.app"
    exit 0
  fi
else
  if [ -x "$ANCHOR_DIR/shell/dist/Anchor/Anchor" ]; then
    nohup "$ANCHOR_DIR/shell/dist/Anchor/Anchor" >/dev/null 2>&1 &
    exit 0
  fi
fi

SHELL_VENV="${ANCHOR_SHELL_BUILD_VENV:-${SHELL_DATA_DIR}/.venv}"
if [ -x "$SHELL_VENV/bin/python" ] && [ -f "$ANCHOR_DIR/shell/anchor_shell.py" ]; then
  nohup "$SHELL_VENV/bin/python" "$ANCHOR_DIR/shell/anchor_shell.py" >/dev/null 2>&1 &
else
  echo "[*] First-time native GUI setup — running install-mac-linux.sh..."
  bash "$ANCHOR_DIR/install-mac-linux.sh"
fi
