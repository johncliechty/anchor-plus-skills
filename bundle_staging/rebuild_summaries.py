import sys
import os
import json
sys.path.append("C:/dev/Anchor")
import summarizer
import rnd_registry
import session_registry

projects = rnd_registry.list_projects()
for p in projects:
    pid = p['id']
    resp = rnd_registry.reconcile_folder(pid)
    if resp and resp.get('ok'):
        folder = resp.get('folder_path')
        if not folder:
            continue
        print(f"Summarizing project: {pid} in {folder}")
        try:
            summarizer.summarize_project(folder, pid, force=True)
            sessions = session_registry.list_sessions(project_id=pid)
            for s in sessions:
                sid = s.get("session_id")
                lane = s.get("lane")
                if sid and lane:
                    print(f"Summarizing session: {sid}")
                    summarizer.summarize_session(folder, pid, lane, s, force=True)
        except Exception as e:
            print(f"Error on {pid}: {e}")
print("Finished rebuilding all summaries.")
