
import sys
with open("C:/dev/Anchor/anchor_gui.py", "r", encoding="utf-8") as f:
    text = f.read()

import re
target = r"    # RUNNING .\+ focus the existing live session \(no new spawn\)\.\n    if src_rec\.get\(\"status\"\) == _sessreg\.STATUS_RUNNING:"

replacement = """    import pty_manager as _pty
    is_truly_live = False
    if src_rec.get("status") == _sessreg.STATUS_RUNNING:
        with _pty._TABLE_LOCK:
            is_truly_live = source in _pty._LIVE

    # RUNNING -> focus the existing live session (no new spawn).
    if src_rec.get("status") == _sessreg.STATUS_RUNNING and is_truly_live:"""

if re.search(target, text):
    text = re.sub(target, replacement, text, count=1)
    with open("C:/dev/Anchor/anchor_gui.py", "w", encoding="utf-8") as f:
        f.write(text)
    print("Replaced successfully!")
else:
    print("Target not found!")

