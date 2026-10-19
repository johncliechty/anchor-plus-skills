#!/usr/bin/env python3
"""
Creates a desktop shortcut and a pinnable launcher for Anchor Dashboard.
Run this once:  python create_shortcut.py

What it does:
  1. Generates an anchor.ico icon file (blue anchor on dark background)
  2. Creates a Windows shortcut (.lnk) on your Desktop
  3. Creates a .bat launcher you can pin to the taskbar

After running, right-click AnchorDashboard.bat → "Pin to taskbar" for one-click access.
"""

import os
import sys
import struct
from pathlib import Path

ANCHOR_DIR = Path(__file__).parent.resolve()
ICON_PATH = ANCHOR_DIR / "anchor.ico"
BAT_PATH = ANCHOR_DIR / "AnchorDashboard.bat"

# ── Generate a simple .ico file (48x48 + 32x32 + 16x16) ───────────────

def make_ico():
    """Generate a minimal anchor icon."""
    try:
        from PIL import Image, ImageDraw
        for size in [48, 32, 16]:
            img = Image.new("RGBA", (size, size), (15, 17, 23, 255))
            draw = ImageDraw.Draw(img)
            cx, cy = size // 2, size // 2
            r = size // 3
            # Vertical line
            draw.line([(cx, cy - r), (cx, cy + r)], fill=(108, 156, 252, 255), width=max(2, size // 12))
            # Horizontal bar at top
            bw = r // 2
            draw.line([(cx - bw, cy - r + 2), (cx + bw, cy - r + 2)], fill=(108, 156, 252, 255), width=max(2, size // 16))
            # Curved bottom (arc)
            arc_r = r - 2
            draw.arc([(cx - arc_r, cy), (cx + arc_r, cy + arc_r * 2)], 180, 0, fill=(108, 156, 252, 255), width=max(2, size // 12))
            # Small circle at top
            cr = max(2, size // 10)
            draw.ellipse([(cx - cr, cy - r - cr - 1), (cx + cr, cy - r + cr - 1)], fill=(108, 156, 252, 255))
            if size == 48: img48 = img
            elif size == 32: img32 = img
            else: img16 = img
        img48.save(str(ICON_PATH), format="ICO", sizes=[(48, 48), (32, 32), (16, 16)], append_images=[img32, img16])
        print(f"  Created icon: {ICON_PATH}")
        return True
    except ImportError:
        print("  PIL not available. Install with: pip install Pillow")
        print("  Skipping icon generation.")
        return False

# ── Create .bat launcher ───────────────────────────────────────────────

def make_bat():
    """Create a .bat file that ONLY opens the dashboard in the browser.

    The Anchor server runs persistently under the NSSM service ``anchor``; the
    launcher must never start its own server (a duplicate would squat port 8777
    and serve stale content).
    """
    bat_content = '''@echo off
rem Open the Anchor dashboard. The server runs under the NSSM service "anchor";
rem this launcher must NOT start a server. If it does not load, run (elevated):
rem   nssm restart anchor
start "" "http://localhost:8777"
'''
    BAT_PATH.write_text(bat_content, encoding="utf-8")
    print(f"  Created launcher: {BAT_PATH}")

# ── Create .vbs wrapper (launches .bat minimized, no console flash) ────

def make_vbs():
    """Create a .vbs wrapper for cleaner launching."""
    vbs_path = ANCHOR_DIR / "AnchorDashboard.vbs"
    vbs_content = f'''Set WshShell = CreateObject("WScript.Shell")
WshShell.Run """{BAT_PATH}""", 7, False
'''
    vbs_path.write_text(vbs_content, encoding="utf-8")
    print(f"  Created silent launcher: {vbs_path}")

# ── Create Desktop shortcut ────────────────────────────────────────────

def make_desktop_shortcut():
    """Create a Windows desktop shortcut (.lnk) using PowerShell."""
    desktop = Path.home() / "Desktop"
    if not desktop.exists():
        desktop = Path.home() / "OneDrive" / "Desktop"
    if not desktop.exists():
        print("  Could not find Desktop folder. Skipping shortcut.")
        return

    lnk_path = desktop / "Anchor Dashboard.lnk"
    ps_script = f'''
$ws = New-Object -ComObject WScript.Shell
$s = $ws.CreateShortcut("{lnk_path}")
$s.TargetPath = "{BAT_PATH}"
$s.WorkingDirectory = "{ANCHOR_DIR}"
$s.IconLocation = "{ICON_PATH},0"
$s.Description = "Anchor Life Dashboard"
$s.WindowStyle = 7
$s.Save()
'''
    import subprocess
    try:
        subprocess.run(["powershell", "-Command", ps_script], capture_output=True, timeout=10)
        print(f"  Created desktop shortcut: {lnk_path}")
    except Exception as e:
        print(f"  Could not create desktop shortcut: {e}")
        print(f"  You can manually create a shortcut to: {BAT_PATH}")

# ── Main ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n  Anchor Dashboard — Setup")
    print("  ──────────────────────────\n")

    make_ico()
    make_bat()
    make_vbs()

    if sys.platform == "win32":
        make_desktop_shortcut()

    print(f"""
  Done! Here's how to use it:

  OPTION 1 — Double-click:
    {BAT_PATH}

  OPTION 2 — Pin to taskbar:
    1. Right-click AnchorDashboard.bat
    2. Select "Pin to taskbar"
    3. If icon doesn't show: right-click shortcut → Properties
       → Change Icon → browse to {ICON_PATH}

  OPTION 3 — Desktop shortcut:
    Already created on your Desktop (if on Windows).

  The launcher only OPENS http://localhost:8777 in your browser.
  The server itself runs persistently under the NSSM service "anchor".
""")
