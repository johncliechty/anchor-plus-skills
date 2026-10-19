
import sys
with open("C:/dev/Anchor/anchor_gui.py", "r", encoding="utf-8") as f:
    text = f.read()

target = "if src_rec.get(\"status\") == _sessreg.STATUS_RUNNING:\n        handler._send_json({\"ok\": True, \"mode\": \"already-live\""

replacement = """import pty_manager as _pty
    is_truly_live = False
    if src_rec.get("status") == _sessreg.STATUS_RUNNING:
        with _pty._TABLE_LOCK:
            is_truly_live = source in _pty._LIVE

    if src_rec.get("status") == _sessreg.STATUS_RUNNING and is_truly_live:
        handler._send_json({"ok": True, "mode": "already-live\""""

if target in text:
    text = text.replace(target, replacement)
    with open("C:/dev/Anchor/anchor_gui.py", "w", encoding="utf-8") as f:
        f.write(text)
    print("Replaced successfully!")
else:
    print("Target not found!")

