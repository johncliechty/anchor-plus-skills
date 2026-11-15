#!/usr/bin/env bash
# Anchor.command — Double-clickable Standalone Native GUI Launcher for macOS & Linux (Anchor v1.5.2)
# Starts the local background Mother Ship service with --no-browser and opens the standalone
# native Anchor desktop GUI window (Anchor.app / shell/anchor_shell.py) — never a web browser.

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

echo "=================================================================="
echo "  Anchor v$(cat VERSION 2>/dev/null || echo '1.5.2') — Standalone Native GUI Launcher"
echo "  Folder: $ANCHOR_DIR"
echo "=================================================================="

if [ "${1:-}" = "--update" ]; then
  echo "[*] Pulling latest Anchor update and syncing 20 Foundry skills..."
  python3 -c "import mothership_updater, pathlib; print(mothership_updater.pull_latest_update(pathlib.Path.cwd(), restart_service=False))"
fi

# 1. Ensure background Mother Ship service is running WITHOUT opening any browser
python3 launch_anchor_dashboard.py --no-browser

# 2. Launch the standalone native GUI window (Anchor.app on macOS / anchor_shell.py via pywebview)
if [ "$OS_NAME" = "Darwin" ]; then
  if [ -d "/Applications/Anchor.app" ]; then
    open -a "/Applications/Anchor.app"
    exit 0
  elif [ -d "$ANCHOR_DIR/shell/dist/Anchor.app" ]; then
    open -a "$ANCHOR_DIR/shell/dist/Anchor.app"
    exit 0
  fi
  SHELL_DATA_DIR="${HOME}/Library/Application Support/anchor-shell"
else
  if [ -x "$ANCHOR_DIR/shell/dist/Anchor/Anchor" ]; then
    nohup "$ANCHOR_DIR/shell/dist/Anchor/Anchor" >/dev/null 2>&1 &
    exit 0
  fi
  XDG_BASE="${XDG_DATA_HOME:-${HOME}/.local/share}"
  SHELL_DATA_DIR="${XDG_BASE}/anchor-shell"
fi

SHELL_VENV="${ANCHOR_SHELL_BUILD_VENV:-${SHELL_DATA_DIR}/.venv}"
if [ -x "$SHELL_VENV/bin/python" ] && [ -f "$ANCHOR_DIR/shell/anchor_shell.py" ]; then
  nohup "$SHELL_VENV/bin/python" "$ANCHOR_DIR/shell/anchor_shell.py" >/dev/null 2>&1 &
else
  echo "[*] First-time native GUI setup — running install-mac-linux.sh..."
  bash "$ANCHOR_DIR/install-mac-linux.sh"
fi
