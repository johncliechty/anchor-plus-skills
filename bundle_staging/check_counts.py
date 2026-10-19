import sys
sys.path.append("C:/dev/Anchor")
import rnd_registry
import os
import json

projects = rnd_registry.list_projects()
total_sessions = 0
for p in projects:
    pid = p['id']
    resp = rnd_registry.reconcile_folder(pid)
    if resp and resp.get("ok"):
        folder = resp.get("path") or resp.get("folder")
        if folder:
            reg_file = os.path.join(folder, ".anchor", "registry.json")
            if os.path.exists(reg_file):
                with open(reg_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    total_sessions += len(data.get("sessions", []))

print(f"Total sessions: {total_sessions}")
