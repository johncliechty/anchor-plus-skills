
import sys
with open("C:/dev/Anchor/terminal_session.py", "r", encoding="utf-8") as f:
    text = f.read()

import re
target = r"def _generate_switch_summary\(session_id, record\):(.+?)try:\n        try:"
replacement = """def _generate_switch_summary(session_id, record):\\1try:
        worktree_path = (record or {}).get("worktree_path") or ""
        lane = (record or {}).get("lane") or ""
        if worktree_path and lane:
            import os
            restart_doc = os.path.join(worktree_path, lane, "RESTART.md")
            if os.path.exists(restart_doc):
                return f"Switching engines. Please read the {restart_doc} file to get oriented with the current state. Do NOT read the full raw transcripts unless specifically needed."
        try:"""

if re.search(target, text, re.DOTALL):
    text = re.sub(target, replacement, text, count=1, flags=re.DOTALL)
    with open("C:/dev/Anchor/terminal_session.py", "w", encoding="utf-8") as f:
        f.write(text)
    print("Replaced successfully!")
else:
    print("Target not found!")

