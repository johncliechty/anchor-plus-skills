"""Write the Start-menu shortcut for the Anchor program (PLAN v2.2 section 3.3).

Run once with the shell venv's python. The shortcut carries the same AppUserModelID the program sets on
itself, so the pinned icon and the running window are ONE taskbar button wearing the anchor.

  %LOCALAPPDATA%/anchor-shell/.venv/Scripts/python.exe shell/make_shortcut.py
"""
import os
import sys
from pathlib import Path

import pythoncom
from win32com.propsys import propsys, pscon
from win32com.shell import shell

sys.path.insert(0, str(Path(__file__).resolve().parent))
from anchor_shell import APP_ID, ICON  # noqa: E402

SCRIPT = Path(__file__).resolve().parent / "anchor_shell.py"
PYTHONW = Path(sys.executable).with_name("pythonw.exe")
LINK = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Anchor.lnk"


def main():
    link = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink)
    link.SetPath(str(PYTHONW))
    link.SetArguments('"%s"' % SCRIPT)
    link.SetWorkingDirectory(str(SCRIPT.parent.parent))
    link.SetIconLocation(str(ICON), 0)
    link.SetDescription("Anchor")
    store = link.QueryInterface(propsys.IID_IPropertyStore)
    store.SetValue(pscon.PKEY_AppUserModel_ID, propsys.PROPVARIANTType(APP_ID))
    store.Commit()
    link.QueryInterface(pythoncom.IID_IPersistFile).Save(str(LINK), 0)
    print(LINK)


if __name__ == "__main__":
    main()
