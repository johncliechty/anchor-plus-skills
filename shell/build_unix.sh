#!/usr/bin/env bash
# Build the native Anchor desktop shell on macOS (Anchor.app, Anchor-macOS.zip, Anchor-macOS.dmg)
# and Linux (Anchor-Linux.tar.gz + install-desktop-entry.sh).
#
# Not product code: lives under shell/ and stays off dist_manifest.txt.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
OS_NAME="$(uname -s)"

PY_BIN="${PYTHON:-python3}"
if ! command -v "$PY_BIN" >/dev/null 2>&1; then
    PY_BIN="python"
fi

# Verify VERSION matches pyproject.toml before packaging
"$PY_BIN" - "$ROOT" <<'PY'
import pathlib, re, sys
root = pathlib.Path(sys.argv[1])
v_file = (root / "VERSION").read_text(encoding="utf-8").strip()
pyproj = (root / "pyproject.toml").read_text(encoding="utf-8")
m = re.search(r'(?m)^version\s*=\s*"([^"]+)"', pyproj)
v_proj = m.group(1).strip() if m else ""
if not v_file or v_file != v_proj:
    raise SystemExit(f"VERSION mismatch: VERSION='{v_file}' vs pyproject.toml='{v_proj}'")
print(f"Building Anchor desktop shell v{v_file} ({sys.platform})")
PY

if [ "$OS_NAME" = "Darwin" ]; then
    SHELL_DATA_DIR="${HOME}/Library/Application Support/anchor-shell"
else
    XDG_BASE="${XDG_DATA_HOME:-${HOME}/.local/share}"
    SHELL_DATA_DIR="${XDG_BASE}/anchor-shell"
fi

VENV_DIR="${ANCHOR_SHELL_BUILD_VENV:-${SHELL_DATA_DIR}/.venv}"
mkdir -p "$(dirname "$VENV_DIR")"

if [ ! -x "$VENV_DIR/bin/python" ]; then
    if [ "$OS_NAME" = "Linux" ]; then
        "$PY_BIN" -m venv --system-site-packages "$VENV_DIR"
    else
        "$PY_BIN" -m venv "$VENV_DIR"
    fi
fi

"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install --upgrade pywebview pyinstaller pillow

WORK_DIR="${SHELL_DATA_DIR}/build"
DIST_DIR="$HERE/dist"
rm -rf "$WORK_DIR" "$DIST_DIR"
mkdir -p "$WORK_DIR" "$DIST_DIR"

ICON_ICO="$ROOT/vendor/brand/anchor-icon.ico"
VERSION_FILE="$ROOT/VERSION"

# Build core overlay zip so freshly installed/upgraded Mother Ships have latest wizard & routes
OVERLAY_ZIP="$HERE/anchor-core-overlay.zip"
"$PY_BIN" - "$ROOT" "$OVERLAY_ZIP" <<'PY'
import pathlib, sys, zipfile
root = pathlib.Path(sys.argv[1])
out_zip = pathlib.Path(sys.argv[2])
files = [
    "VERSION", "anchor_gui.py", "anchor.py", "paths.py", "route_table.py",
    "onboard.py", "onboard.cmd", "onboard.ps1", "onboard.sh", "onboard_cli.py",
    "onboard_bootstrap.py", "onboard_wizard.py", "website_portal.py",
    "share_onboard.py", "launch_anchor_dashboard.py", "USER-ONBOARD.md",
]
with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
    for rel in files:
        p = root / rel
        if p.is_file():
            zf.write(p, arcname=rel)
PY

ADD_DATA_ARGS=(
    --add-data "${ICON_ICO}:."
    --add-data "${VERSION_FILE}:."
    --add-data "${OVERLAY_ZIP}:."
)

"$VENV_DIR/bin/python" -m PyInstaller \
    --noconfirm \
    --clean \
    --onedir \
    --windowed \
    --name Anchor \
    --icon "$ICON_ICO" \
    --paths "$HERE" \
    --paths "$ROOT" \
    "${ADD_DATA_ARGS[@]}" \
    --distpath "$DIST_DIR" \
    --workpath "$WORK_DIR" \
    --specpath "$WORK_DIR" \
    "$HERE/anchor_shell.py"

DOWNLOADS_DIR="$ROOT/static/downloads"
mkdir -p "$DOWNLOADS_DIR"

if [ "$OS_NAME" = "Darwin" ]; then
    APP_BUNDLE="$DIST_DIR/Anchor.app"
    if [ -d "$APP_BUNDLE" ]; then
        cp -f "$OVERLAY_ZIP" "$APP_BUNDLE/Contents/MacOS/anchor-core-overlay.zip" || true
        if command -v codesign >/dev/null 2>&1; then
            codesign --force --deep --sign - "$APP_BUNDLE" || true
        fi
        MAC_ZIP="$HERE/Anchor-macOS.zip"
        rm -f "$MAC_ZIP"
        ditto -c -k --sequesterRsrc --keepParent "$APP_BUNDLE" "$MAC_ZIP"
        cp -f "$MAC_ZIP" "$DOWNLOADS_DIR/Anchor-macOS.zip"
        echo "Built macOS app archive: $MAC_ZIP"

        if command -v hdiutil >/dev/null 2>&1; then
            MAC_DMG="$HERE/Anchor-macOS.dmg"
            rm -f "$MAC_DMG"
            hdiutil create -volname "Anchor" -srcfolder "$APP_BUNDLE" -ov -format UDZO "$MAC_DMG" || true
            if [ -f "$MAC_DMG" ]; then
                cp -f "$MAC_DMG" "$DOWNLOADS_DIR/Anchor-macOS.dmg"
                echo "Built macOS disk image: $MAC_DMG"
            fi
        fi
    fi
else
    LINUX_BUNDLE="$DIST_DIR/Anchor"
    cp -f "$OVERLAY_ZIP" "$LINUX_BUNDLE/anchor-core-overlay.zip" || true
    cp -f "$ICON_ICO" "$LINUX_BUNDLE/anchor-icon.ico" || true
    cat > "$LINUX_BUNDLE/install-desktop-entry.sh" <<'DESKTOP_EOF'
#!/usr/bin/env bash
set -euo pipefail
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESKTOP_DIR="${XDG_DATA_HOME:-${HOME}/.local/share}/applications"
mkdir -p "$DESKTOP_DIR"
cat > "$DESKTOP_DIR/anchor.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Anchor
Comment=Anchor Productivity & AI Cockpit Shell
Exec="${APP_DIR}/Anchor"
Path=${APP_DIR}
Icon=${APP_DIR}/anchor-icon.ico
Terminal=false
Categories=Development;Utility;
StartupWMClass=Anchor
EOF
chmod +x "$DESKTOP_DIR/anchor.desktop"
echo "Installed desktop launcher: $DESKTOP_DIR/anchor.desktop"
DESKTOP_EOF
    chmod +x "$LINUX_BUNDLE/install-desktop-entry.sh"

    LINUX_TAR="$HERE/Anchor-Linux.tar.gz"
    rm -f "$LINUX_TAR"
    tar -C "$DIST_DIR" -czf "$LINUX_TAR" Anchor
    cp -f "$LINUX_TAR" "$DOWNLOADS_DIR/Anchor-Linux.tar.gz"
    echo "Built Linux archive: $LINUX_TAR"
fi
