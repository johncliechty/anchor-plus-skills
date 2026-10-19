# Dashboard Skill — Anchor

## Trigger
Activates on: "Dashboard", "dashboard", "anchor", "start", "update", "refresh"

## Instructions

### Primary: Launch the GUI
1. Run `python3 anchor_gui.py` in the background using Bash. This starts a local web server on http://localhost:8777 and opens the user's default browser.
2. The GUI is fully interactive — the user can check tasks done, add tasks, capture ideas, and browse by domain directly in the browser. All changes write to the markdown files automatically and are logged.
3. Give a brief 2-3 line status summary (date, active tasks, projects, inbox count). You can get this from the server: `curl -s http://localhost:8777/api/status`
4. Tell the user the dashboard is running at http://localhost:8777 and they can interact with it directly in the browser.

### Launch command
```bash
cd "<this directory>" && python3 anchor_gui.py &
```
Wait a couple seconds, then verify it's running:
```bash
curl -s http://localhost:8777/api/status
```

### If GUI fails to launch
Fall back to the CLI approach:
1. Run `python3 anchor.py dashboard` to rebuild dashboard.html
2. Present `dashboard.html` via present_files tool
3. User gives text commands: "done: [task]", "add: [task]", "capture: [idea]"

### Processing text commands (fallback or supplement)
If the user gives commands in chat instead of using the browser GUI:
- **"done: X"** → `python3 anchor.py done "X"` then confirm
- **"add: X"** → `python3 anchor.py add "X" --domain D --priority N --energy E` then confirm
- **"capture: X"** → `python3 anchor.py capture "X"` then confirm
- **"update"/"refresh"** → tell user to click Update in browser, or `curl -s http://localhost:8777/` to refresh

### How it works
- `anchor_gui.py` is a standalone Python web server (no dependencies beyond stdlib)
- It reads/writes markdown files directly in both Anchor PSU and Anchor Axmra
- Both directories stay in sync automatically — it discovers the sibling directory on startup
- Every change is logged to `logs/YYYY-MM-DD.md` in both directories
- The server runs at http://localhost:8777 until stopped with Ctrl+C
- **PROJECTS.md in .anchor/ contains proprietary info — never share outside the session.**

---
*NOTE: The original location of this file was `.claude/skills/dashboard/SKILL.md` — renamed to `dot_claude/...` here because the snapshot writer cannot write into a `.claude/` path.*
