#!/usr/bin/env bash
# Anchor v1.5.2 — Turnkey Standalone Native GUI Installer & Updater for Apple macOS (MacBook Air / Pro) & Linux
# Note: Windows Anchor.exe is a PE32+ x86_64 Windows binary and will not run directly on macOS or Linux.
# On macOS (Apple Silicon M1/M2/M3/M4 or Intel) and Linux, Anchor builds and runs as a standalone native
# desktop GUI application (Anchor.app on macOS via Cocoa/WebKit; Anchor desktop app on Linux via WebKitGTK)
# and NEVER runs inside a web browser.

set -euo pipefail

ANCHOR_REPO_URL="${ANCHOR_REPO_URL:-https://github.com/johncliechty/ghostworldlabs-anchor.git}"
ANCHOR_INSTALL_DIR="${ANCHOR_INSTALL_DIR:-$HOME/dev/Anchor}"
OS_NAME="$(uname -s)"

echo "=================================================================="
echo "  Anchor v1.5.2 — macOS (MacBook Air / Pro) & Linux Native GUI"
echo "=================================================================="
echo "Platform: $OS_NAME ($(uname -m))"
echo "Target folder: $ANCHOR_INSTALL_DIR"
echo ""

# 1. Check prerequisites (git, python3, node)
if ! command -v git >/dev/null 2>&1; then
  echo "[!] git is not installed."
  if [ "$OS_NAME" = "Darwin" ]; then
    echo "    Run: xcode-select --install   (or: brew install git)"
  else
    echo "    Run: sudo apt install -y git  (or your distro's package manager)"
  fi
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "[!] python3 is not installed."
  if [ "$OS_NAME" = "Darwin" ]; then
    echo "    Run: brew install python"
  else
    echo "    Run: sudo apt install -y python3 python3-venv python3-pip python3-gi gir1.2-webkit2-4.1"
  fi
  exit 1
fi

if ! command -v node >/dev/null 2>&1; then
  echo "[!] Warning: node (Node.js 18+) was not found on PATH."
  echo "    The Anchor native GUI will still run, but Steward / Trio engines require Node.js 18+."
  if [ "$OS_NAME" = "Darwin" ]; then
    echo "    Recommended: brew install node"
  else
    echo "    Recommended: install Node.js 18+ via nodesource or nvm."
  fi
fi

# 2. Clone or update in-place if the Anchor script is already inside an extracted Anchor folder
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/anchor_gui.py" ] && [ -f "$SCRIPT_DIR/onboard.py" ]; then
  ANCHOR_INSTALL_DIR="$SCRIPT_DIR"
  echo "[*] Detected existing Anchor bundle at: $ANCHOR_INSTALL_DIR"
  if [ -d "$ANCHOR_INSTALL_DIR/.git" ]; then
    echo "[*] Pulling latest Anchor updates..."
    git -C "$ANCHOR_INSTALL_DIR" pull --ff-only || true
  fi
elif [ -f "$SCRIPT_DIR/anchor-core-overlay.zip" ]; then
  mkdir -p "$ANCHOR_INSTALL_DIR"
  echo "[*] Extracting bundled Anchor Mother Ship core into $ANCHOR_INSTALL_DIR..."
  python3 - "$SCRIPT_DIR/anchor-core-overlay.zip" "$ANCHOR_INSTALL_DIR" <<'UNZIP_PY'
import pathlib, sys, zipfile
zpath = pathlib.Path(sys.argv[1])
dest = pathlib.Path(sys.argv[2])
dest.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(zpath, "r") as zf:
    zf.extractall(dest)
UNZIP_PY
  if [ -d "$SCRIPT_DIR/shell" ] && [ ! -d "$ANCHOR_INSTALL_DIR/shell" ]; then
    cp -R "$SCRIPT_DIR/shell" "$ANCHOR_INSTALL_DIR/shell"
  fi
  cp -f "$SCRIPT_DIR/install-mac-linux.sh" "$ANCHOR_INSTALL_DIR/install-mac-linux.sh" 2>/dev/null || true
  cp -f "$SCRIPT_DIR/Anchor.command" "$ANCHOR_INSTALL_DIR/Anchor.command" 2>/dev/null || true
else
  mkdir -p "$(dirname "$ANCHOR_INSTALL_DIR")"
  if [ -d "$ANCHOR_INSTALL_DIR/.git" ]; then
    echo "[*] Updating existing git clone at $ANCHOR_INSTALL_DIR..."
    git -C "$ANCHOR_INSTALL_DIR" pull --ff-only || true
  elif [ -f "$ANCHOR_INSTALL_DIR/anchor_gui.py" ]; then
    echo "[*] Using existing Anchor directory at $ANCHOR_INSTALL_DIR..."
  else
    echo "[*] Cloning Anchor into $ANCHOR_INSTALL_DIR..."
    git clone "$ANCHOR_REPO_URL" "$ANCHOR_INSTALL_DIR"
  fi
fi

cd "$ANCHOR_INSTALL_DIR"

# 3. Install & overwrite all 20 bundled Foundry skills into ~/.claude/skills and ~/.agents/skills
echo "[*] Syncing all 20 bundled Foundry skills and scaffolding Anchor workspace..."
python3 - <<'PY'
import pathlib, onboard
root = pathlib.Path.cwd()
skills_src = root / "vendor" / "bundled-skills"
if skills_src.is_dir():
    res = onboard.install_skills(skills_src=skills_src, overwrite=True)
    print(f"    Synced {len(res.get('installed', []))} skills -> {res.get('dest')}")
onboard.scaffold_anchor(data_dir=root)
tok = onboard.generate_token()
print(f"    Token ready at: {tok.get('token_file')}")
PY

# 4. Provision the standalone Native Desktop GUI Shell (pywebview — never runs in a browser)
if [ "$OS_NAME" = "Darwin" ]; then
  SHELL_DATA_DIR="${HOME}/Library/Application Support/anchor-shell"
else
  XDG_BASE="${XDG_DATA_HOME:-${HOME}/.local/share}"
  SHELL_DATA_DIR="${XDG_BASE}/anchor-shell"
fi
SHELL_VENV="${ANCHOR_SHELL_BUILD_VENV:-${SHELL_DATA_DIR}/.venv}"
mkdir -p "$(dirname "$SHELL_VENV")"

if [ ! -x "$SHELL_VENV/bin/python" ]; then
  echo "[*] Creating standalone native GUI environment at $SHELL_VENV..."
  if [ "$OS_NAME" = "Linux" ]; then
    python3 -m venv --system-site-packages "$SHELL_VENV"
  else
    python3 -m venv "$SHELL_VENV"
  fi
fi

echo "[*] Installing standalone native GUI window runtime (pywebview)..."
"$SHELL_VENV/bin/python" -m pip install --upgrade pip -q
"$SHELL_VENV/bin/python" -m pip install --upgrade pywebview pillow -q

# Optional: build standalone Anchor.app (macOS) or Anchor binary + .desktop launcher (Linux)
if [ "${ANCHOR_BUILD_NATIVE_APP:-1}" = "1" ] && [ -f "$ANCHOR_INSTALL_DIR/shell/build_unix.sh" ]; then
  echo "[*] Building standalone native Anchor desktop app..."
  bash "$ANCHOR_INSTALL_DIR/shell/build_unix.sh" || echo "[!] Standalone PyInstaller bundle step skipped; using direct native pywebview window."
  if [ "$OS_NAME" = "Darwin" ] && [ -d "$ANCHOR_INSTALL_DIR/shell/dist/Anchor.app" ]; then
    if [ -w "/Applications" ]; then
      rm -rf "/Applications/Anchor.app" 2>/dev/null || true
      cp -R "$ANCHOR_INSTALL_DIR/shell/dist/Anchor.app" "/Applications/Anchor.app" || true
      echo "[*] Installed standalone macOS app -> /Applications/Anchor.app"
    fi
    if [ -d "$HOME/Desktop" ]; then
      rm -rf "$HOME/Desktop/Anchor.app" 2>/dev/null || true
      ln -sf "$ANCHOR_INSTALL_DIR/shell/dist/Anchor.app" "$HOME/Desktop/Anchor.app" || true
    fi
  elif [ "$OS_NAME" = "Linux" ] && [ -x "$ANCHOR_INSTALL_DIR/shell/dist/Anchor/install-desktop-entry.sh" ]; then
    bash "$ANCHOR_INSTALL_DIR/shell/dist/Anchor/install-desktop-entry.sh" || true
  fi
fi

# 5. Ensure Anchor.command is executable and create a macOS Desktop shortcut if on Darwin
if [ -f "$ANCHOR_INSTALL_DIR/Anchor.command" ]; then
  chmod +x "$ANCHOR_INSTALL_DIR/Anchor.command"
  if [ "$OS_NAME" = "Darwin" ] && [ -d "$HOME/Desktop" ]; then
    ln -sf "$ANCHOR_INSTALL_DIR/Anchor.command" "$HOME/Desktop/Anchor.command" || true
    echo "[*] Placed double-clickable 'Anchor.command' native GUI launcher on your macOS Desktop."
  fi
fi

echo ""
echo "=================================================================="
echo "  Anchor v$(cat VERSION 2>/dev/null || echo '1.5.2') Standalone Native GUI is installed!"
echo "=================================================================="
echo "To launch the standalone Anchor GUI window at any time (never a browser):"
if [ "$OS_NAME" = "Darwin" ]; then
  echo "  - macOS Applications / Desktop: Double-click 'Anchor.app' or 'Anchor.command'"
else
  echo "  - Linux App Menu / Terminal:    Launch 'Anchor' from your desktop menu or run './Anchor.command'"
fi
echo ""

if [ "${ANCHOR_NO_LAUNCH:-0}" != "1" ]; then
  REMOTE_CONFIGURED="$("$SHELL_VENV/bin/python" - <<'CHK_REMOTE' 2>/dev/null || echo "0"
import json, os, pathlib, sys
base = pathlib.Path.home() / ("Library/Application Support/anchor-shell" if sys.platform == "darwin" else ".local/share/anchor-shell")
sp = base / "settings.json"
if sp.is_file():
    addr = str(json.loads(sp.read_text(encoding="utf-8")).get("address") or "").strip()
    if addr and not addr.startswith(("http://127.0.0.1", "http://localhost", "http://[::1]")):
        print("1")
        raise SystemExit(0)
print("0")
CHK_REMOTE
)"
  if [ "$REMOTE_CONFIGURED" != "1" ]; then
    echo "[*] Starting Anchor Mother Ship background service (--no-browser)..."
    python3 launch_anchor_dashboard.py --no-browser
  else
    echo "[*] Preserving existing remote Mother Ship connection (skipping local server start)..."
  fi
  if [ "$OS_NAME" = "Darwin" ] && [ -d "/Applications/Anchor.app" ]; then
    open -a "/Applications/Anchor.app"
  elif [ "$OS_NAME" = "Darwin" ] && [ -d "$ANCHOR_INSTALL_DIR/shell/dist/Anchor.app" ]; then
    open -a "$ANCHOR_INSTALL_DIR/shell/dist/Anchor.app"
  else
    "$SHELL_VENV/bin/python" "$ANCHOR_INSTALL_DIR/shell/anchor_shell.py" &
  fi
fi
