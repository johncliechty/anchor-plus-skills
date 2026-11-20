#!/usr/bin/env bash
# 1-Command Updater for Anchor.app on Apple Mac (MacBook Air / Pro) & Linux
# Closes any frozen/open Anchor.app instance, pulls the latest code, rebuilds Anchor.app
# while preserving your saved Tailscale Mother Ship connection, and reopens Anchor.app.

set -euo pipefail

ANCHOR_DIR="${ANCHOR_INSTALL_DIR:-$HOME/dev/Anchor}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/shell/anchor_shell.py" ]; then
  ANCHOR_DIR="$SCRIPT_DIR"
fi

if [ ! -d "$ANCHOR_DIR" ]; then
  echo "[!] Could not find Anchor directory at $ANCHOR_DIR"
  exit 1
fi

echo "[1/4] Closing any open or frozen Anchor app instance..."
pkill -9 -f "Anchor.app/Contents/MacOS/Anchor" 2>/dev/null || true
pkill -9 -f "anchor_shell.py" 2>/dev/null || true
sleep 0.5

echo "[2/4] Pulling latest Anchor updates in $ANCHOR_DIR..."
cd "$ANCHOR_DIR"
if [ -d .git ]; then
  git pull --ff-only
fi

echo "[3/4] Rebuilding native Anchor.app..."
bash "$ANCHOR_DIR/shell/build_unix.sh"

if [ "$(uname -s)" = "Darwin" ] && [ -d "$ANCHOR_DIR/shell/dist/Anchor.app" ]; then
  if [ -w "/Applications" ]; then
    rm -rf "/Applications/Anchor.app"
    cp -R "$ANCHOR_DIR/shell/dist/Anchor.app" "/Applications/Anchor.app"
    echo "[4/4] Installed updated /Applications/Anchor.app and launching..."
    open -a "/Applications/Anchor.app"
  else
    echo "[4/4] Launching updated $ANCHOR_DIR/shell/dist/Anchor.app..."
    open -a "$ANCHOR_DIR/shell/dist/Anchor.app"
  fi
else
  echo "[4/4] Done."
fi
