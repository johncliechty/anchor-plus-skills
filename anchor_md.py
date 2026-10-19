"""anchor_md — the single shared markdown-parsing layer for Anchor.

Pillar C5 of the 2026-07 rearchitecture: collapse the three drifting copies of
the task/project/inbox/archived markdown parsers to ONE source of truth. Both
``anchor_gui.py`` (the live server) and ``anchor.py`` (the CLI mirror) import
their parsers from here; the drifted third copy died with the deleted, dead
legacy Flask app ``anchor_server.py``.

The functions are a verbatim, behavior-parity extraction of the pre-de-fork
``anchor_gui.py`` twins (the richer, more-defensive copy — it tolerates a
``None`` filepath, and includes ``parse_archived_tasks`` and
``serialize_task_line`` that the CLI copy lacked). Every parser takes a
``pathlib.Path``, is resilient to non-UTF-8 bytes (see ``_read_md_text``), and
returns plain ``dict``/``list`` structures. Stdlib only.

A golden-corpus gate (``tests/test_anchor_md_defork_w10.py``) freezes this
module's behavior against the pre-de-fork implementation on the REAL markdown
files, so any future drift here fails a test rather than silently diverging the
GUI and CLI again.
"""

import re
from pathlib import Path


def _read_md_text(filepath):
    """Read a markdown file as text, resilient to non-UTF-8 bytes.

    Anchor always writes markdown as UTF-8, but a file edited by an external
    tool can arrive in another encoding (e.g. a Windows-1252 em-dash, byte
    0x97). A single such byte must never take down the dashboard: try strict
    UTF-8 first, and on a UnicodeDecodeError fall back to a lenient decode so
    the stray byte degrades to a replacement char instead of raising. The next
    write re-saves the file as clean UTF-8. The daily healthcheck still reads
    strictly, so a malformed file is still surfaced there for cleanup.
    """
    try:
        return filepath.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return filepath.read_text(encoding="utf-8", errors="replace")


def parse_tasks_from_md(filepath):
    """Extract checkbox tasks from a markdown file."""
    tasks = []
    if not filepath or not filepath.exists():
        return tasks
    text = _read_md_text(filepath)
    for line in text.splitlines():
        m = re.match(r'\s*-\s*\[([ xX])\]\s*\*?\*?(.*?)(?:\*?\*?\s*—\s*(.*))?$', line)
        if m:
            done = m.group(1).lower() == 'x'
            raw_text = m.group(2).strip().rstrip('*')
            meta = m.group(3) or ""
            pm = re.search(r'Priority:\s*(\d)', meta) or re.search(r'Priority:\s*(\d)', raw_text)
            priority = int(pm.group(1)) if pm else 2
            em = re.search(r'energy:\s*(\w+)', meta, re.I) or re.search(r'energy:\s*(\w+)', raw_text, re.I)
            energy = em.group(1).lower() if em else "med"
            dm = re.search(r'\[(\w+)\]', meta) or re.search(r'\[(\w+)\]', raw_text)
            domain = dm.group(1).lower() if dm else "personal"
            due_m = re.search(r'Due:\s*([\d/\-\w]+)', meta, re.I)
            due = due_m.group(1) if due_m else ""
            # Extract the optional Project: <id> field (Wave 3 task↔project link;
            # a no-op until Wave 9 — it must simply round-trip unchanged).
            proj_m = re.search(r'Project:\s*([^\s—]+)', meta, re.I)
            project = proj_m.group(1).strip() if proj_m else ""
            # Extract notes
            notes_m = re.search(r'Notes:\s*(.+?)(?:\s*—\s*(?:Priority|energy|Due|Project|\[)|$)', meta, re.I)
            if not notes_m:
                notes_m = re.search(r'Notes:\s*(.+?)$', meta, re.I)
            notes = notes_m.group(1).strip().rstrip(' —') if notes_m else ""
            clean = re.sub(r'\s*—\s*Priority:.*', '', raw_text)
            clean = re.sub(r'\s*—\s*\[.*', '', clean)
            clean = re.sub(r'\s*—\s*energy:.*', '', clean, flags=re.I)
            clean = re.sub(r'\s*—\s*Notes:.*', '', clean, flags=re.I)
            clean = re.sub(r'\s*—\s*Project:.*', '', clean, flags=re.I)
            clean = clean.strip(' *')
            tasks.append({"text": clean, "done": done, "priority": priority,
                          "energy": energy, "domain": domain, "due": due,
                          "notes": notes, "project": project})
    return tasks


def serialize_task_line(task):
    """Serialize a parsed task dict back to its markdown line.

    Round-trips the Wave 3 ``project`` field (``Project: <id>``) unchanged so a
    task with a project link survives parse→serialize (a no-op until Wave 9).
    Field order mirrors :func:`add_task` so existing tasks serialize identically.
    """
    check = "x" if task.get("done") else " "
    text = task.get("text", "")
    priority = task.get("priority", 2)
    energy = task.get("energy", "med")
    domain = task.get("domain", "personal")
    due = task.get("due", "")
    notes = task.get("notes", "")
    project = task.get("project", "")
    due_str = f" — Due: {due}" if due else ""
    notes_str = f" — Notes: {notes}" if notes else ""
    project_str = f" — Project: {project}" if project else ""
    return (f"- [{check}] {text} — Priority: {priority} — energy: {energy} "
            f"— [{domain}]{due_str}{project_str}{notes_str}")


def parse_projects_from_md(filepath):
    """Extract projects from PROJECTS.md."""
    projects = []
    if not filepath or not filepath.exists():
        return projects
    text = _read_md_text(filepath)
    current = None
    for line in text.splitlines():
        h2 = re.match(r'^##\s+(.+)', line)
        if h2:
            if current:
                projects.append(current)
            current = {"name": h2.group(1).strip(), "domain": "academic", "priority": 2,
                       "status": "active", "effort": "high", "due": "", "next": "",
                       "collabs": "", "notes": ""}
            continue
        if current:
            kv = re.match(r'\s*-\s*\*\*(\w[\w\s]*?):\*\*\s*(.*)', line)
            if kv:
                key = kv.group(1).strip().lower()
                val = kv.group(2).strip()
                if key == "domain":
                    current["domain"] = val.lower().split("+")[0].strip().split("/")[0].strip()
                elif key == "priority":
                    try: current["priority"] = int(val)
                    except: pass
                elif key == "status":
                    current["status"] = val.lower().split("—")[0].strip()
                elif key.startswith("next"):
                    current["next"] = val
                elif key == "collaborators":
                    current["collabs"] = val
                elif key == "notes":
                    current["notes"] = val
                elif key in ("effort", "effort level"):
                    current["effort"] = val.lower()
                elif key in ("deadline", "due"):
                    current["due"] = val
    if current:
        projects.append(current)
    return projects


def parse_inbox_from_md(filepath):
    """Extract inbox items from INBOX.md."""
    items = []
    if not filepath or not filepath.exists():
        return items
    text = _read_md_text(filepath)
    for line in text.splitlines():
        m = re.match(r'\s*-\s*(\d{4}-\d{2}-\d{2}):\s*(.*?)(?:\s*\[(\w+)\])?\s*$', line)
        if m:
            items.append({"date": m.group(1), "text": m.group(2).strip(),
                          "domain": m.group(3) or ""})
    return items


def parse_archived_tasks(filepath):
    """Parse cancelled or saved-for-later tasks from their archive file."""
    items = []
    if not filepath or not filepath.exists():
        return items
    text = _read_md_text(filepath)
    for line in text.splitlines():
        m = re.match(r'\s*-\s*(\d{4}-\d{2}-\d{2}):\s*(.*?)(?:\s*—\s*\[(\w+)\])?(?:\s*—\s*P(\d))?(?:\s*—\s*Notes:\s*(.*))?$', line)
        if m:
            items.append({
                "date": m.group(1),
                "text": m.group(2).strip(),
                "domain": m.group(3) or "",
                "priority": int(m.group(4)) if m.group(4) else 2,
                "notes": m.group(5).strip() if m.group(5) else "",
            })
    return items
