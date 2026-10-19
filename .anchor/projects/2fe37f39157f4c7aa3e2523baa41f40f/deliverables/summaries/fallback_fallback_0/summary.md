# anchor_gui.py

*Lane: deliverables · validated, cached summary*

**When run:** 2026-06-12

**What was asked:** anchor_gui.py

## Actions & files produced

- anchor_gui.py

**Effort:** imported — no run metrics

## Summary

- The deliverable in this session is `anchor_gui.py`.
- `anchor_gui.py` is the Anchor application: a self-contained, stdlib-only Python HTTP server that serves an interactive web dashboard and exposes API endpoints so every UI action writes directly to the markdown source files, logs the change, and refreshes state (`anchor_gui.py:1-14`).
- **Single-file, no external deps.** Imports are stdlib only â€” `json, logging, os, re, socket, sys, threading, time, traceback, webbrowser`, plus `http.server.ThreadingHTTPServer`/`BaseHTTPRequestHandler` and `urllib.parse` (`anchor_gui.py:16-21`).
- **Path/data layer is centralized.** All file paths resolve through the shared `paths` helper, honoring `ANCHOR_DATA_DIR`; `DASHBOARD_MD`, `PROJECTS_MD`, `INBOX_MD`, `DOMAINS_DIR`, `LOGS_DIR`, `CANCELLED_MD`, `SAVED_FOR_LATER_MD` are derived from it (`anchor_gui.py:23-47`).
- **Error/lifecycle logging.** Logs ERROR + INFO to `logs/errors.log`, with explicit guards against double FileHandler attach and propagation when the module is imported twice (e.g. by `anchor_healthcheck`) (`anchor_gui.py:49-71`).
- **Cache-bust build identity.** A build id is computed once at startup from `git rev-parse --short HEAD`; the self-healing client JS uses it to force a cache-busting reload and clear stale service workers/Cache Storage on redeploy (`anchor_gui.py:74-90`, `144`).
- **Task/markdown parsing + gathering.** Parsers read markdown into dicts â€” `parse_tasks_from_md`, `parse_projects_from_md`, `parse_inbox_from_md`, `parse_archived_tasks` â€” and `gather_all()` aggregates DASHBOARD + domain files (`anchor_gui.py:181-388`).
- **Full task lifecycle ops.** `mark_done`/`mark_undone`, `add_task`, `capture_inbox`, `edit_task`, `edit_project`, `cancel_task`, `save_for_later`, `restore_task`, `link_task`, plus archive append helpers (`anchor_gui.py:5325-5751`).

## Files

- [anchor_gui.py](/artifact/2fe37f39157f4c7aa3e2523baa41f40f?path=anchor_gui.py)
