#!/usr/bin/env bash
# 1-Command Updater for Anchor.app on Apple Mac (MacBook Air / Pro) & Linux
# Closes any frozen/open Anchor.app instance, pulls the latest code, rebuilds Anchor.app
# while preserving your saved Tailscale Mother Ship connection, atomically installs & signs
# /Applications/Anchor.app on Apple Silicon, and verifies Anchor stays open cleanly.

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
if [ "$(uname -s)" = "Darwin" ]; then
  hdiutil detach "/Volumes/Anchor" -force >/dev/null 2>&1 || true
  rm -rf "$HOME/Library/Saved Application State/"*Anchor*.savedState 2>/dev/null || true
  rm -f "$HOME/Library/Application Support/anchor-shell/instance.lock" 2>/dev/null || true
fi
sleep 0.5

echo "[2/4] Pulling latest Anchor updates in $ANCHOR_DIR..."
cd "$ANCHOR_DIR"
if [ -d .git ]; then
  git pull --ff-only
fi

echo "[3/4] Rebuilding native Anchor.app..."
ANCHOR_SKIP_ARCHIVES=1 bash "$ANCHOR_DIR/shell/build_unix.sh"

if [ "$(uname -s)" = "Darwin" ] && [ -d "$ANCHOR_DIR/shell/dist/Anchor.app" ]; then
  SHELL_DATA_DIR="$HOME/Library/Application Support/anchor-shell"
  mkdir -p "$SHELL_DATA_DIR"
  SHELL_LOG="$SHELL_DATA_DIR/shell.log"
  : > "$SHELL_LOG"

  TARGET_APP="$ANCHOR_DIR/shell/dist/Anchor.app"
  if [ -w "/Applications" ]; then
    STAGE_APP="/Applications/.Anchor.app.tmp.$$"
    rm -rf "$STAGE_APP"
    ditto "$ANCHOR_DIR/shell/dist/Anchor.app" "$STAGE_APP"
    xattr -cr "$STAGE_APP" 2>/dev/null || true
    if command -v codesign >/dev/null 2>&1; then
      codesign --force --deep --sign - "$STAGE_APP"
      codesign --verify --deep --strict "$STAGE_APP"
    fi
    rm -rf "/Applications/Anchor.app"
    mv "$STAGE_APP" "/Applications/Anchor.app"
    TARGET_APP="/Applications/Anchor.app"

    # Ensure Desktop shortcut (if present) points to /Applications/Anchor.app rather than a duplicate bundle
    if [ -e "$HOME/Desktop/Anchor.app" ] || [ -L "$HOME/Desktop/Anchor.app" ]; then
      rm -rf "$HOME/Desktop/Anchor.app" 2>/dev/null || true
      ln -sf "/Applications/Anchor.app" "$HOME/Desktop/Anchor.app" || true
    fi

    LSREG="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
    if [ -x "$LSREG" ]; then
      "$LSREG" -f "/Applications/Anchor.app" >/dev/null 2>&1 || true
    fi
  fi

  echo "[4/4] Installed & signed $TARGET_APP — launching and verifying..."
  open -a "$TARGET_APP"
  sleep 3
  LIVE_PIDS="$(pgrep -f "Anchor.app/Contents/MacOS/Anchor" || true)"
  if [ -n "$LIVE_PIDS" ]; then
    echo "[✓] Anchor.app is running cleanly (PID: $(echo "$LIVE_PIDS" | tr '\n' ' '))."
  else
    echo "[!] Anchor.app exited within 3s — diagnostic details:"
    if [ -s "$SHELL_LOG" ]; then
      echo "--- shell.log ---"
      cat "$SHELL_LOG"
    else
      echo "  (shell.log is empty — process terminated before Python main)"
    fi
    LATEST_CRASH="$(ls -t "$HOME/Library/Logs/DiagnosticReports/"Anchor* 2>/dev/null | head -n 1 || true)"
    if [ -n "$LATEST_CRASH" ] && [ -f "$LATEST_CRASH" ]; then
      echo "--- Latest macOS DiagnosticReport ($LATEST_CRASH) ---"
      head -n 45 "$LATEST_CRASH" || true
    fi
    exit 1
  fi
else
  echo "[4/4] Done."
fi
