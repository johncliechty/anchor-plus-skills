"""
Create a Windows desktop shortcut for the Anchor Dashboard.
Run this once: python setup_shortcut.py
It will place an "Anchor Dashboard" shortcut on your Desktop.
"""

import os
import sys

def create_shortcut():
    try:
        from win32com.client import Dispatch
        has_win32 = True
    except ImportError:
        has_win32 = False

    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    if not os.path.exists(desktop):
        desktop = os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop")
    if not os.path.exists(desktop):
        print(f"Could not find Desktop folder. Creating launcher in current directory.")
        desktop = os.path.dirname(os.path.abspath(__file__))

    script_dir = os.path.dirname(os.path.abspath(__file__))
    launcher = os.path.join(script_dir, "launch_anchor.pyw")

    if has_win32:
        # Create a proper .lnk shortcut
        shortcut_path = os.path.join(desktop, "Anchor Dashboard.lnk")
        pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if not os.path.exists(pythonw):
            pythonw = sys.executable

        shell = Dispatch('WScript.Shell')
        shortcut = shell.CreateShortCut(shortcut_path)
        shortcut.Targetpath = pythonw
        shortcut.Arguments = f'"{launcher}"'
        shortcut.WorkingDirectory = script_dir
        shortcut.Description = "Launch Anchor Dashboard"
        shortcut.save()
        print(f"Shortcut created: {shortcut_path}")
    else:
        # Fallback: create a .bat file
        bat_path = os.path.join(desktop, "Anchor Dashboard.bat")
        bat_content = f'''@echo off
cd /d "{script_dir}"
start "" pythonw "{launcher}"
'''
        with open(bat_path, "w") as f:
            f.write(bat_content)
        print(f"Launcher created: {bat_path}")

    print("Double-click 'Anchor Dashboard' on your Desktop to launch!")


if __name__ == "__main__":
    create_shortcut()
