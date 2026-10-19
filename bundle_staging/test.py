import sys
sys.path.append("C:/dev/Anchor")
import rnd_registry
import json

projects = rnd_registry.list_projects()
for p in projects:
    resp = rnd_registry.reconcile_folder(p['id'])
    print(f"ID: {p['id']}, Resp: {resp}")
