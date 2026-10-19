#!/usr/bin/env python3
# Wave 14: acceptance tests added
# Wave 15: trust ceremony added
"""
Anchor — Productivity Engine for J.C. Liechty
Reads/writes markdown files, generates dashboard.html, logs changes.

Usage:
    python3 anchor.py dashboard          # Rebuild dashboard.html from markdown files
    python3 anchor.py done "task text"   # Mark a task as done
    python3 anchor.py cancel "task text" # Cancel a task (moves to CANCELLED.md)
    python3 anchor.py save "task text"   # Save a task for later (moves to SAVED_FOR_LATER.md)
    python3 anchor.py restore "task text" --from saved|cancelled  # Restore archived task
    python3 anchor.py add "task" --domain academic --priority 1 --energy high --due 2026-04-10 --notes "some note"
    python3 anchor.py capture "idea"     # Add to inbox
    python3 anchor.py link "task text" --project <id>   # Link a task to an R&D project
    python3 anchor.py status             # Print current status summary

R&D control-surface mirror (v2 — delegates to the shared modules):
    python3 anchor.py rnd sessions <project_id> --lane planning
    python3 anchor.py rnd status <project_id>
    python3 anchor.py rnd reconcile <project_id> [--apply]   # default = dry-run preview
    python3 anchor.py rnd add-idea <project_id> "idea text" [--notes "..."]
    python3 anchor.py rnd promote-inbox <project_id> "inbox item text"
    python3 anchor.py rnd pin-deliverable <project_id> <path> [--name N] [--type doc|script|skill|program] [--desc "..."]
    python3 anchor.py rnd set-blurb <project_id> "what this project is"
    python3 anchor.py rnd regenerate-summary <project_id> --lane planning --session <session_id>

R&D v3 "Mission Control" inspection mirror (read-only; live terminals/previews
are interactive and have NO CLI form):
    python3 anchor.py rnd term-sessions <project_id>          # managed ConPTY terminal sessions
    python3 anchor.py rnd previews <project_id>               # ephemeral deliverable-run previews
    python3 anchor.py rnd handoff <project_id> [--lane build] [--seed-session <session_id>]

R&D v4 "Project Cockpit" inspection mirror (read-only DATA seams; live
terminal start/switch + deliverable launch are interactive and have NO CLI form):
    python3 anchor.py rnd rollup <project_id> [--window lifetime|30d]   # cost/tokens/time rollup
    python3 anchor.py rnd doc-roles <project_id> --lane <lane> --session <id>  # per-lane role->doc map
    python3 anchor.py rnd deliverable-type <project_id> <deliverable_id>  # type detection (skill/tool also verify)
    python3 anchor.py rnd engine <project_id>                 # the project's last-used engine

R&D v5 "Durable Work" inspection mirror (read-only DATA seams; continue-live,
grass develop/promote, save-refinement, deliverable launch are interactive and
have NO CLI form):
    python3 anchor.py rnd session-summary <project_id> --lane <lane> --session <id>  # cached session summary (skill/prompts/actions)
    python3 anchor.py rnd grass <project_id>                  # grass ideas + status + refinement counts
    python3 anchor.py rnd build-deliverable <project_id> --session <id> [--lane build]  # the deliverable a build produced (honest unresolved)

R&D v6 "Linked Pipeline" inspection mirror (read-only DATA seam; advance/continue
are interactive and have NO CLI form):
    python3 anchor.py rnd chain <project_id> --session <id>   # the ordered lineage chain (research -> planning -> build)

R&D v7 "Integrated Board" inspection mirror (read-only DATA seam; the board/general
terminal are interactive and have NO CLI form):
    python3 anchor.py rnd blurb <project_id> --lane <lane> --session <id>  # the short, clean one-line session blurb (cache-only)

R&D v8 "Durable Artifacts" inspection mirror (read-only DATA seams; link/push,
grass develop/export, continue-live are interactive and have NO CLI form):
    python3 anchor.py rnd remote <project_id>                 # GitHub remote link + auto-push opt-in state (no network)
    python3 anchor.py rnd docs <project_id> --session <id> [--lane <lane>]  # documents the session persisted into the project

R&D v9 "Tidy" inspection mirror (read-only DATA seams; session/grass delete + the
guarded on-disk move are interactive mutating ops with NO one-shot CLI form):
    python3 anchor.py rnd folders                             # project folders (groups) + members (Ungrouped last)
    python3 anchor.py rnd ghost-sessions <project_id>         # empty/ghost sessions cleanup_ghost_sessions would remove

R&D v10 "Live Handoff & Boneyard" inspection mirror (read-only DATA seams;
session/grass delete, the guarded move, live paste/advance are interactive and
have NO one-shot CLI form):
    python3 anchor.py rnd boneyard <project_id> [--search <q>]  # discarded material (killed/deleted/grass-deleted), newest-first
    python3 anchor.py rnd next-prompt <project_id> --session <id>  # the generated next-stage handoff prompt (pending paste / NEXT-PROMPT.md)

telemetry-resume W3 "Narration floor" inspection mirror (read-only, cache-only;
never spawns a PTY / runs the model / touches the network):
    python3 anchor.py rnd narration <project_id> --lane <lane> --session <id>  # the Layer-1 warm narration spine (done / produced / next)
    python3 anchor.py rnd narration-coverage [<project_id>]   # the two-number report (template coverage MUST be 100% + enrichment coverage %)

R&D v12 "Efforts" inspection mirror (read-only DATA seams; the in-session
advance/handoff/dock are interactive live ops with NO CLI form):
    python3 anchor.py rnd efforts <project_id>               # the project's efforts (id - current_stage - status - stage count)
    python3 anchor.py rnd effort <project_id> --session <id>  # one effort's ordered stage_history (SAFE: no worktree/branch/baseline)
    python3 anchor.py rnd effort-deliverable <project_id> --session <id>  # the build-stage resolved deliverable (honest unresolved)

Gandalf v1 inspection mirror (read-only; run/re-run is interactive — NO CLI form):
    python3 anchor.py rnd gandalf <project_id>               # the project's Gandalf reads (verdict + chips + report path), newest-first
"""

import json, os, re, sys
from datetime import datetime, date
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────
# Single-folder layout (was previously dual-folder PSU + Axmra; consolidated 2026-05-02).
# Wave 2: all data paths resolve via the shared `paths` helper, which honors the
# ANCHOR_DATA_DIR env var (unset -> the code dir, so behavior is unchanged).
import paths as _paths

# ANCHOR_DIR is the *code* dir (kept for code-relative references / back-compat).
ANCHOR_DIR = _paths.CODE_DIR

# Data paths resolved at module load from the current ANCHOR_DATA_DIR. Resolving
# here (not at every use site) keeps the existing module-level constant API while
# still honoring the env var; tests that need a tmp data dir set the env var
# before import, or call the paths.* helpers directly.
DASHBOARD_MD = _paths.dashboard_md()
PROJECTS_MD = _paths.projects_md()
INBOX_MD = _paths.inbox_md()
DOMAINS_DIR = _paths.domains_dir()
LOGS_DIR = _paths.logs_dir()
HTML_FILE = _paths.dashboard_html()
CANCELLED_MD = _paths.cancelled_md()
SAVED_FOR_LATER_MD = _paths.saved_for_later_md()

# NOTE: directory creation is intentionally NOT done at import time (carried
# minor finding). Callers that mutate state call paths.ensure_data_dirs() /
# create the logs dir lazily inside the write helpers (see log_change()).


# ── Parsing helpers ────────────────────────────────────────────────────

def _read_md_text(filepath):
    """Read a markdown file as text, resilient to non-UTF-8 bytes.

    Mirrors anchor_gui._read_md_text: a stray non-UTF-8 byte (e.g. a
    Windows-1252 em-dash, 0x97) in a markdown file must not crash the CLI.
    Strict UTF-8 first; on a UnicodeDecodeError fall back to a lenient decode.
    """
    try:
        return filepath.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return filepath.read_text(encoding="utf-8", errors="replace")


# ── Markdown parsers — the single shared layer (C5 de-fork, 2026-07) ───
# These parsers used to be a byte-identical twin of anchor_gui.py's copies
# (with a drifted third copy in the now-deleted dead Flask anchor_server.py).
# They now live once, in the shared ``anchor_md`` module, imported by both the
# CLI (here) and the GUI. Re-exported as module globals so ``anchor.parse_*``
# call sites keep working unchanged. The CLI additionally gains
# ``parse_archived_tasks`` and ``serialize_task_line`` for free (previously
# GUI-only).
from anchor_md import (
    parse_tasks_from_md,
    serialize_task_line,
    parse_projects_from_md,
    parse_inbox_from_md,
    parse_archived_tasks,
)


# ── Dashboard HTML generation ──────────────────────────────────────────

def read_html_template():
    """Read the dashboard.html and return (before_state, after_state) for STATE injection."""
    if not HTML_FILE.exists():
        return None, None
    text = HTML_FILE.read_text(encoding="utf-8")
    # Find the STATE block
    state_start = text.find("const STATE = {")
    if state_start < 0:
        return None, None
    # Find the closing of STATE (nextId line + };)
    state_end = text.find("};", text.find("nextId:", state_start))
    if state_end < 0:
        return None, None
    state_end += 2  # include the };
    return text[:state_start], text[state_end:]


def generate_state_js(projects, tasks, inbox):
    """Generate the JavaScript STATE object."""
    def js_str(s):
        return s.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"').replace("\n", " ")

    lines = ["const STATE = {"]
    lines.append("  projects: [")
    for i, p in enumerate(projects):
        lines.append("    {")
        lines.append(f'      id: {i+1}, name: "{js_str(p["name"])}", domain: "{p["domain"]}", priority: {p["priority"]},')
        lines.append(f'      status: "{p["status"]}", effort: "{p.get("effort","high")}", due: "{p.get("due","")}",')
        lines.append(f'      next: "{js_str(p.get("next",""))}", collabs: "{js_str(p.get("collabs",""))}", notes: "{js_str(p.get("notes",""))}"')
        lines.append("    },")
    lines.append("  ],")

    lines.append("  tasks: [")
    for i, t in enumerate(tasks):
        done_str = "true" if t["done"] else "false"
        lines.append(f'    {{ id: {i+1}, text: "{js_str(t["text"])}", domain: "{t["domain"]}", priority: {t["priority"]}, energy: "{t["energy"]}", due: "{t.get("due","")}", done: {done_str} }},')
    lines.append("  ],")

    lines.append("  inbox: [")
    for i, item in enumerate(inbox):
        lines.append(f'    {{ id: {i+1}, text: "{js_str(item["text"])}", date: "{item["date"]}", domain: "{item.get("domain","")}" }},')
    lines.append("  ],")

    next_proj = len(projects) + 50
    next_task = len(tasks) + 1
    next_inbox = len(inbox) + 1
    lines.append(f"  nextId: {{ projects: {next_proj}, tasks: {next_task}, inbox: {next_inbox} }}")
    lines.append("};")
    return "\n".join(lines)


def rebuild_dashboard():
    """Read all markdown files, regenerate dashboard.html STATE."""
    before, after = read_html_template()
    if before is None:
        print("ERROR: dashboard.html not found or STATE block not parseable")
        return False

    # Gather tasks (deduplicated by first 60 chars of lowercased text)
    all_tasks = []
    seen_texts = set()

    def _add_tasks(task_list, default_domain=None):
        for t in task_list:
            key = t["text"].lower().strip()[:60]
            if key not in seen_texts:
                seen_texts.add(key)
                if default_domain and t["domain"] == "personal":
                    t["domain"] = default_domain
                all_tasks.append(t)

    if DASHBOARD_MD.exists():
        _add_tasks(parse_tasks_from_md(DASHBOARD_MD))

    if DOMAINS_DIR.exists():
        for domain_file in sorted(DOMAINS_DIR.glob("*.md")):
            _add_tasks(parse_tasks_from_md(domain_file), default_domain=domain_file.stem)

    # Projects
    projects = []
    seen_proj = set()
    if PROJECTS_MD.exists():
        for p in parse_projects_from_md(PROJECTS_MD):
            key = p["name"].lower().strip()[:60]
            if key not in seen_proj:
                seen_proj.add(key)
                projects.append(p)

    # Inbox
    inbox = []
    if INBOX_MD.exists():
        inbox.extend(parse_inbox_from_md(INBOX_MD))

    # Generate new STATE
    state_js = generate_state_js(projects, all_tasks, inbox)

    # Write updated HTML
    new_html = before + state_js + after
    HTML_FILE.write_text(new_html, encoding="utf-8")

    # Summary
    active = [t for t in all_tasks if not t["done"]]
    p1 = [t for t in active if t["priority"] == 1]
    done_count = len([t for t in all_tasks if t["done"]])

    print(f"Dashboard rebuilt: {len(projects)} projects, {len(active)} active tasks, {done_count} completed, {len(inbox)} inbox items")
    if p1:
        print(f"P1 tasks: {len(p1)}")
        for t in p1:
            due_str = f" (due {t['due']})" if t.get('due') else ""
            print(f"  - {t['text']}{due_str}")
    return True


# ── Change operations ──────────────────────────────────────────────────

def log_change(message):
    """Append a timestamped line to today's log file."""
    today = date.today().isoformat()
    now = datetime.now().strftime("%H:%M")

    LOGS_DIR.mkdir(exist_ok=True)
    log_file = LOGS_DIR / f"{today}.md"
    if not log_file.exists():
        day_name = datetime.now().strftime("%A")
        log_file.write_text(f"# {today} — {day_name}\n\n## Changes\n", encoding="utf-8")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"- {now} — {message}\n")

    print(f"Logged: {now} — {message}")


def mark_done(task_text):
    """Mark a task as done across all markdown files."""
    search = task_text.lower().strip()
    found = False

    for md_file in _all_md_files():
        if not md_file.exists():
            continue
        text = _read_md_text(md_file)
        new_lines = []
        changed = False
        for line in text.splitlines():
            if re.match(r'\s*-\s*\[ \]', line) and search in line.lower():
                new_lines.append(line.replace("[ ]", "[x]", 1))
                found = True
                changed = True
            else:
                new_lines.append(line)
        if changed:
            md_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    if found:
        log_change(f"Completed: {task_text}")
        rebuild_dashboard()
        print(f"✓ Marked done: {task_text}")
    else:
        print(f"Task not found: {task_text}")
        print("Available tasks:")
        for md_file in _all_md_files():
            if md_file and md_file.exists():
                for t in parse_tasks_from_md(md_file):
                    if not t["done"]:
                        print(f"  - {t['text']} ({md_file.parent.name}/{md_file.name})")
    return found


def add_task(text, domain="academic", priority=2, energy="med", due="", notes=""):
    """Add a new task to DASHBOARD.md and the relevant domain file."""
    due_str = f" — Due: {due}" if due else ""
    notes_str = f" — Notes: {notes}" if notes else ""
    line = f"- [ ] {text} — Priority: {priority} — energy: {energy} — [{domain}]{due_str}{notes_str}"

    def _insert_in_section(filepath, section_names):
        """Insert a task line into the first matching section of a markdown file."""
        if not filepath or not filepath.exists():
            return False
        content = _read_md_text(filepath)
        for section in section_names:
            idx = content.find(section)
            if idx >= 0:
                next_section = content.find("\n##", idx + len(section))
                if next_section < 0:
                    next_section = len(content)
                content = content[:next_section].rstrip() + "\n" + line + "\n\n" + content[next_section:]
                filepath.write_text(content, encoding="utf-8")
                return True
        return False

    # Always add to DASHBOARD.md (central hub)
    _insert_in_section(DASHBOARD_MD, ["## Today's Priorities", "## Active Priorities"])

    # Add to the matching domain file (commercial included — was formerly Axmra)
    if DOMAINS_DIR.exists():
        domain_file = DOMAINS_DIR / f"{domain}.md"
        _insert_in_section(domain_file, ["## Active Tasks"])

    log_change(f"Added task: {text} [{domain}] P{priority}")
    rebuild_dashboard()
    print(f"✓ Added: {text} [{domain}] P{priority}")


def capture_inbox(text, domain=""):
    """Add an item to the inbox."""
    today = date.today().isoformat()
    domain_tag = f" [{domain}]" if domain else ""
    line = f"- {today}: {text}{domain_tag}"

    if not INBOX_MD.exists():
        # Fresh/empty data dir: create a minimal inbox so the capture is never
        # silently dropped.
        INBOX_MD.write_text("# Inbox\n\n", encoding="utf-8")
    content = _read_md_text(INBOX_MD)
    content = content.rstrip() + "\n" + line + "\n"
    INBOX_MD.write_text(content, encoding="utf-8")

    log_change(f"Captured to inbox: {text}")
    rebuild_dashboard()
    print(f"✓ Captured: {text}")


def print_status():
    """Print a status summary."""
    tasks = []
    seen = set()
    for md_file in _all_md_files():
        if md_file and md_file.exists():
            for t in parse_tasks_from_md(md_file):
                key = t["text"].lower().strip()[:60]
                if key not in seen:
                    seen.add(key)
                    tasks.append(t)

    projects = []
    if PROJECTS_MD.exists():
        projects.extend(parse_projects_from_md(PROJECTS_MD))

    inbox = []
    if INBOX_MD.exists():
        inbox.extend(parse_inbox_from_md(INBOX_MD))

    active = [t for t in tasks if not t["done"]]
    done = [t for t in tasks if t["done"]]
    p1 = [t for t in active if t["priority"] == 1]

    today = datetime.now().strftime("%A, %B %d, %Y")
    print(f"Anchor — {today}")
    print(f"{len(projects)} projects | {len(active)} active tasks | {len(done)} completed | {len(inbox)} inbox")
    if p1:
        print(f"\nUrgent (P1):")
        for t in p1:
            due = f" — due {t['due']}" if t.get("due") else ""
            print(f"  ⚡ {t['text']}{due}")


def _remove_task_from_files(task_text):
    """Remove a task line from all markdown files. Returns the task dict if found."""
    search = task_text.lower().strip()
    found_task = None
    for md_file in _all_md_files():
        if not md_file or not md_file.exists():
            continue
        text = _read_md_text(md_file)
        new_lines = []
        changed = False
        for line in text.splitlines():
            if re.match(r'\s*-\s*\[([ xX])\]', line) and search in line.lower():
                if not found_task:
                    tm = re.match(r'\s*-\s*\[([ xX])\]\s*\*?\*?(.*?)(?:\*?\*?\s*—\s*(.*))?$', line)
                    if tm:
                        meta = tm.group(3) or ""
                        dm = re.search(r'\[(\w+)\]', meta)
                        pm = re.search(r'Priority:\s*(\d)', meta)
                        notes_m = re.search(r'Notes:\s*(.+?)(?:\s*—\s*(?:Priority|energy|Due|\[)|$)', meta, re.I)
                        if not notes_m:
                            notes_m = re.search(r'Notes:\s*(.+?)$', meta, re.I)
                        found_task = {
                            "text": task_text,
                            "domain": dm.group(1).lower() if dm else "",
                            "priority": int(pm.group(1)) if pm else 2,
                            "notes": notes_m.group(1).strip().rstrip(' —') if notes_m else "",
                        }
                changed = True
                continue
            new_lines.append(line)
        if changed:
            md_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return found_task


def _append_to_archive(filepath, task_dict):
    """Append a task entry to an archive file (CANCELLED.md or SAVED_FOR_LATER.md)."""
    if not filepath:
        return
    today = date.today().isoformat()
    domain_str = f" — [{task_dict.get('domain', '')}]" if task_dict.get('domain') else ""
    priority_str = f" — P{task_dict.get('priority', 2)}"
    notes_str = f" — Notes: {task_dict['notes']}" if task_dict.get('notes') else ""
    line = f"- {today}: {task_dict['text']}{domain_str}{priority_str}{notes_str}"

    if not filepath.exists():
        filepath.write_text(f"# {filepath.stem.replace('_', ' ').title()}\n\n", encoding="utf-8")
    content = _read_md_text(filepath)
    content = content.rstrip() + "\n" + line + "\n"
    filepath.write_text(content, encoding="utf-8")


def cancel_task(task_text):
    """Cancel a task: remove from active lists, add to CANCELLED.md, log it."""
    task = _remove_task_from_files(task_text)
    if task:
        _append_to_archive(CANCELLED_MD, task)
        log_change(f"Cancelled: {task_text}")
        rebuild_dashboard()
        print(f"✗ Cancelled: {task_text}")
        return True
    print(f"Task not found: {task_text}")
    return False


def save_for_later(task_text):
    """Save a task for later: remove from active lists, add to SAVED_FOR_LATER.md, log it."""
    task = _remove_task_from_files(task_text)
    if task:
        _append_to_archive(SAVED_FOR_LATER_MD, task)
        log_change(f"Saved for later: {task_text}")
        rebuild_dashboard()
        print(f"⏳ Saved for later: {task_text}")
        return True
    print(f"Task not found: {task_text}")
    return False


def restore_task(task_text, from_archive="saved"):
    """Restore a task from an archive back to the active dashboard."""
    archive_file = SAVED_FOR_LATER_MD if from_archive == "saved" else CANCELLED_MD
    if not archive_file or not archive_file.exists():
        print(f"Archive file not found")
        return False
    text = _read_md_text(archive_file)
    search = task_text.lower().strip()
    found = None
    new_lines = []
    for line in text.splitlines():
        if search in line.lower() and not found:
            m = re.match(r'\s*-\s*\d{4}-\d{2}-\d{2}:\s*(.*?)(?:\s*—\s*\[(\w+)\])?(?:\s*—\s*P(\d))?(?:\s*—\s*Notes:\s*(.*))?$', line)
            if m:
                found = {
                    "text": m.group(1).strip(),
                    "domain": m.group(2) or "personal",
                    "priority": int(m.group(3)) if m.group(3) else 2,
                    "notes": m.group(4).strip() if m.group(4) else "",
                }
            continue
        new_lines.append(line)
    if found:
        archive_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        add_task(found["text"], found["domain"], found["priority"], "med", "", found["notes"])
        log_change(f"Restored from {from_archive}: {task_text}")
        print(f"✓ Restored: {task_text}")
        return True
    print(f"Task not found in archive: {task_text}")
    return False


def link_task(task_text, project_id):
    """Link a task to an R&D project — set/maintain its ``Project: <id>`` field.

    Wave 9 ACTIVATES the ``Project:`` field that Wave 3 parsed as a no-op. This
    edits ONLY that field, surgically, on the first matching active task line:

    - If the line has no ``Project:`` field, append ``" — Project: <id>"`` to it.
    - If it already has one, replace just the ``<id>`` in place.
    - Passing an empty ``project_id`` REMOVES the field (unlink).

    Every other character of the user's markdown line is preserved verbatim, so
    a task without the field that is not being touched stays byte-stable, and a
    task with the field round-trips cleanly through parse/serialize + the
    healthcheck parse path. Returns True if a task was updated.
    """
    search = task_text.lower().strip()
    new_id = (project_id or "").strip()
    found = False

    for md_file in _all_md_files():
        if not md_file.exists():
            continue
        text = _read_md_text(md_file)
        new_lines = []
        changed = False
        for line in text.splitlines():
            if (not found and re.match(r'\s*-\s*\[([ xX])\]', line)
                    and search in line.lower()):
                existing = re.search(r'(\s*—\s*Project:\s*)([^\s—]+)', line, re.I)
                if existing:
                    if new_id:
                        # Replace just the id; keep surrounding text untouched.
                        new_line = (line[:existing.start(2)] + new_id
                                    + line[existing.end(2):])
                    else:
                        # Unlink: drop the whole " — Project: <id>" segment.
                        new_line = line[:existing.start(1)] + line[existing.end(2):]
                else:
                    if new_id:
                        new_line = line.rstrip() + f" — Project: {new_id}"
                    else:
                        new_line = line  # nothing to remove
                if new_line != line:
                    changed = True
                new_lines.append(new_line)
                found = True
            else:
                new_lines.append(line)
        if changed:
            md_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    if found:
        if new_id:
            log_change(f"Linked task '{task_text}' to project {new_id}")
            print(f"✓ Linked: {task_text} → project {new_id}")
        else:
            log_change(f"Unlinked task '{task_text}' from its project")
            print(f"✓ Unlinked: {task_text}")
        rebuild_dashboard()
    else:
        print(f"Task not found: {task_text}")
    return found


def _all_md_files():
    """Return all markdown files that might contain tasks."""
    files = []
    if DASHBOARD_MD.exists():
        files.append(DASHBOARD_MD)
    if DOMAINS_DIR.exists():
        files.extend(sorted(DOMAINS_DIR.glob("*.md")))
    return files


# ── R&D Grass Catchers content feeds (Wave 5 mirror) ───────────────────────

def add_idea(folder_path, project_id, text, notes=""):
    """CLI mirror of ``effort_history.add_idea`` — manual Grass Catchers idea.

    Records a real Anchor-created idea card on the project's grass lane.
    Delegates to the single source of truth in ``effort_history`` so the GUI and
    CLI never diverge. Returns the stored pointer-record.
    """
    import effort_history as _eh
    return _eh.add_idea(folder_path, project_id, text, notes=notes)


def promote_inbox(folder_path, project_id, inbox_item_text):
    """CLI mirror of ``effort_history.promote_inbox`` — promote an INBOX item.

    Reads the existing ``INBOX.md`` with this module's ``parse_inbox_from_md``
    (no new format) and copies the matching item into the project's Grass
    Catchers lane (copy-by-default — the inbox item is NOT removed). Returns the
    stored grass pointer-record. Raises ``ValueError`` if no item matches.
    """
    import effort_history as _eh
    inbox_items = parse_inbox_from_md(INBOX_MD)
    return _eh.promote_inbox(folder_path, project_id, inbox_item_text,
                             inbox_items=inbox_items)


# ── R&D v2 surface mirror (Wave 8) ─────────────────────────────────────────
# These delegate (never duplicate logic) to the shared v2 modules so the CLI
# and the GUI/API stay byte-for-byte consistent. Each resolves a project by id
# via ``rnd_registry`` and forwards to ``sessions`` / ``rnd_registry`` /
# ``effort_history`` / ``deliverables`` / ``summarizer``.

def _rnd_resolve(project_id):
    """Return ``(project_entry, folder_path)`` for an R&D project id.

    Raises ``KeyError`` (with a clean message) for an unknown id so callers can
    print a friendly error rather than a traceback.
    """
    import rnd_registry as _rnd
    proj = _rnd.get_project(project_id)
    if proj is None:
        raise KeyError(project_id)
    return proj, proj.get("folder_path", "")


def rnd_list_sessions(project_id, lane):
    """CLI mirror of ``sessions.list_sessions`` — one trio run = one session.

    Returns the lane's sessions newest-first (delegates to ``sessions``).
    """
    import sessions as _sessions
    _proj, folder = _rnd_resolve(project_id)
    return _sessions.list_sessions(folder, project_id, lane)


def rnd_status_line(project_id):
    """CLI mirror of ``rnd_registry.status_line`` — per-lane counts + provenance."""
    import rnd_registry as _rnd
    # Validate the id (status_line is best-effort and returns zeros for unknown).
    _rnd_resolve(project_id)
    return _rnd.status_line(project_id)


def rnd_reconcile(project_id, apply=False):
    """CLI mirror of ``rnd_registry.reconcile_folder`` — preview (dry-run) / apply.

    With ``apply=False`` (default) returns the PLAN of what folding+deleting would
    do WITHOUT mutating anything; with ``apply=True`` folds same-folder siblings'
    real sessions into the active id, then hard-deletes them.
    """
    import rnd_registry as _rnd
    return _rnd.reconcile_folder(project_id, apply=apply)


def rnd_set_blurb(project_id, blurb):
    """CLI mirror of ``rnd_registry.set_blurb`` — the project's 'what this is' line."""
    import rnd_registry as _rnd
    _rnd_resolve(project_id)
    return _rnd.set_blurb(project_id, blurb)


def rnd_pin_deliverable(project_id, path, name=None, dtype=None, description=""):
    """CLI mirror of ``deliverables.pin_deliverable`` — pin any path as a deliverable.

    Surfaces a file (e.g. ``anchor_gui.py`` at repo root) as a deliverables-lane
    effort even though it is not under a ``deliverables/`` directory.
    """
    import deliverables as _deliv
    _proj, folder = _rnd_resolve(project_id)
    return _deliv.pin_deliverable(folder, project_id, path, name=name,
                                  dtype=dtype, description=description)


def rnd_regenerate_summary(project_id, lane, session_id):
    """CLI mirror of ``summarizer.summarize_session(force=True)`` — re-cache a summary.

    Re-runs the validated summarizer (through the runner seam — ``ANCHOR_RUNNER_CMD``)
    for one session and overwrites its cached ``summary.json`` / ``summary.md``.
    Raises ``KeyError`` for an unknown project and ``ValueError`` for an unknown
    session so the CLI can report a clean error.
    """
    import sessions as _sessions
    import summarizer as _summarizer
    _proj, folder = _rnd_resolve(project_id)
    session = None
    for s in _sessions.list_sessions(folder, project_id, lane):
        if s.get("session_id") == session_id:
            session = s
            break
    if session is None:
        raise ValueError(f"unknown session: {session_id}")
    return _summarizer.summarize_session(folder, project_id, lane, session,
                                         force=True)


# ── R&D v3 surface mirror (Wave 10) ────────────────────────────────────────
# Read-only INSPECTION of the new v3 "Mission Control" data: managed ConPTY
# terminal sessions (``session_registry``), ephemeral deliverable-run previews
# (``preview_server``), and stage handoffs (``handoff``). These DELEGATE to the
# shared modules — no forked logic. There is intentionally NO CLI for the live
# interactive terminal (start/input/SSE/WS) or for preview START/STOP — those are
# interactive / mutating live operations driven by the dashboard, never one-shot
# CLI calls. The CLI mirrors only the data/inspection seams.

def rnd_term_sessions(project_id):
    """CLI mirror of ``session_registry.list_sessions`` — managed terminal sessions.

    Returns the project's managed ConPTY/REPL terminal session records
    (newest-first), validating the project id first.
    """
    import session_registry as _sreg
    _rnd_resolve(project_id)
    return _sreg.list_sessions(project_id=project_id)


def rnd_previews(project_id):
    """CLI mirror of ``preview_server.list_previews`` — deliverable-run previews.

    Returns the project's ephemeral deliverable preview records (newest-first).
    ``list_previews`` first reconciles any dead preview to ``stopped`` so the CLI
    reflects the truth (it never spawns or kills anything).
    """
    import preview_server as _preview
    _rnd_resolve(project_id)
    return _preview.list_previews(project_id=project_id)


def rnd_handoff(project_id, lane="build", seed_session=None):
    """CLI mirror of ``handoff.propose_handoff`` — the most-recent plan set + records.

    Returns ``{proposal, handoffs}``: ``proposal`` is the read-only
    ``propose_handoff`` result (``has_plan_set`` / ``plan_set`` / ``message`` —
    the most-recent plan set a build session would execute on, honoring an
    optional ``seed_session`` override) and ``handoffs`` is the list of recorded
    handoffs from ``discovery.json``. Inspection only — primes/records nothing.
    """
    import handoff as _handoff
    _proj, folder = _rnd_resolve(project_id)
    proposal = _handoff.propose_handoff(folder, project_id, lane,
                                        source_session_id=seed_session)
    recorded = _handoff.list_handoffs(folder, project_id)
    return {"proposal": proposal, "handoffs": recorded}


# ── R&D v4 "Project Cockpit" data mirror (Wave 9) ──────────────────────────
# Read-only DATA seams the cockpit renders. These DELEGATE to the shared v4
# modules (no forked logic). There is intentionally NO CLI for the live
# interactive terminal (start/input/engine-switch) or for deliverable LAUNCH —
# those are interactive / mutating live operations driven by the dashboard.

def rnd_rollup(project_id, window="lifetime"):
    """CLI mirror of ``effort_history.project_effort_rollup`` — cost/tokens/time.

    Sums ``job_runner`` cost records for the project's RUN-provenance sessions
    only (imported/discovered contribute 0). ``window`` is ``lifetime`` (all
    records) or ``30d`` (records within the last 30 days). Returns
    ``{tokens, cost_usd, wall_clock_ms, sessions}``.
    """
    import effort_history as _eh
    _proj, folder = _rnd_resolve(project_id)
    return _eh.project_effort_rollup(project_id, window=window,
                                     folder_path=folder)


def rnd_doc_roles(project_id, lane, session_id):
    """CLI mirror of ``summarizer.session_doc_roles`` — per-lane role->doc map.

    Resolves the session's member docs to the LANE'S locked role set and returns
    ``{role: {label, href}}`` (each href via the existing ``/report`` /
    ``/artifact`` routes). Roles whose document is absent are omitted.
    """
    import summarizer as _summarizer
    _proj, folder = _rnd_resolve(project_id)
    return _summarizer.session_doc_roles(project_id, lane, session_id,
                                         folder_path=folder)


def rnd_deliverable_type(project_id, deliverable_id):
    """Type detection (+ skill/tool verify) for a pinned deliverable (Wave 9).

    Delegates to ``deliverables``: resolves the pinned deliverable by its
    content-addressed id, reports its declared type (else ``infer_type`` from the
    path), and — for a ``skill``/``tool`` — adds the no-spawn verify status
    (``available`` | ``loaded`` | ``missing``) via ``verify_skill_or_tool``. No
    process is ever spawned (inspection only). Raises ``ValueError`` for an
    unknown deliverable so the CLI prints a clean error.
    """
    import deliverables as _deliv
    _proj, folder = _rnd_resolve(project_id)
    rec = _deliv.get_pinned_deliverable(folder, project_id, deliverable_id)
    if rec is None:
        raise ValueError(f"unknown deliverable: {deliverable_id}")
    dtype = (rec.get("deliverable_type") or "").strip().lower()
    if dtype not in _deliv.VALID_TYPES:
        dtype = _deliv.infer_type(rec.get("artifact_path") or "")
    out = {
        "deliverable_id": deliverable_id,
        "type": dtype,
        "artifact_path": rec.get("artifact_path", ""),
        "title": rec.get("title", ""),
    }
    if dtype in _deliv.VERIFY_TYPES:
        out["verify"] = _deliv.verify_skill_or_tool(dtype, rec)
    return out


def rnd_engine(project_id):
    """CLI mirror of ``terminal_session.last_engine_for_project`` — last engine.

    Returns the project's last-used engine (``claude`` | ``gemini``; defaults to
    ``claude`` when unset). Read-only — switching engines is a live terminal
    operation with no CLI form.
    """
    import terminal_session as _ts
    _rnd_resolve(project_id)
    return _ts.last_engine_for_project(project_id)


# ── R&D v5 "Durable Work" data mirror (Wave 6) ─────────────────────────────
# Read-only DATA/INSPECTION seams the durable-work surface exposes. These
# DELEGATE to the shared v5 modules (no forked logic). There is intentionally NO
# CLI for the live interactive operations (continue-live, develop/promote a grass
# idea, save-refinement, set-status, deliverable LAUNCH) — those are interactive /
# mutating live operations driven by the dashboard. The CLI mirrors only the
# data/inspection seams.

def rnd_session_summary(project_id, lane, session_id):
    """CLI mirror of the cached validated SESSION summary (read-only, v5 Wave 2).

    Mirrors the read-only ``GET /api/rnd/session_summary`` contract: returns the
    CACHED structured summary (skill · prompts · actions · member links) when one
    exists, else ``None`` — it NEVER runs the model synchronously (cache only;
    use ``rnd regenerate-summary`` to force a re-run). Raises ``KeyError`` for an
    unknown project.
    """
    import effort_history as _eh
    import summarizer as _summarizer
    _proj, folder = _rnd_resolve(project_id)
    store_lane = _eh._resolve_subdir(lane)
    cached = _summarizer.load_cached(folder, project_id, store_lane, session_id)
    if isinstance(cached, dict) and cached.get("error"):
        return None
    return cached


def rnd_blurb(project_id, lane, session_id):
    """CLI mirror of ``summarizer.session_blurb`` — the short, clean one-liner (v7).

    READ-ONLY cache lookup: returns the short, glyph/markdown-stripped one-line
    blurb derived from the session's CACHED summary (the same data source the
    board tile uses), or an empty string when no usable cache exists — it NEVER
    runs the model synchronously. Raises ``KeyError`` for an unknown project.
    """
    import summarizer as _summarizer
    _proj, folder = _rnd_resolve(project_id)
    return _summarizer.session_blurb(folder, project_id, lane, session_id)


def rnd_grass(project_id):
    """CLI mirror of ``effort_history.grass_workbench_data`` — the idea board.

    Returns the project's grass ideas (newest-first), each carrying its id +
    status (raw/refined/promoted) + versioned refinements + source. Read-only —
    developing / promoting an idea is a live operation with no CLI form.
    """
    import effort_history as _eh
    _proj, folder = _rnd_resolve(project_id)
    return _eh.grass_workbench_data(folder, project_id)


def rnd_build_deliverable(project_id, session_id, lane="build"):
    """CLI mirror of ``deliverables.resolve_build_deliverable`` — per-build product.

    Resolves the deliverable a BUILD session produced from EXPLICIT signals only
    (pinned path / declared marker / config / session product); returns the
    ``{resolved, deliverable, signal, reason}`` dict — an HONEST ``resolved=False``
    when nothing resolves (never a fabricated path). Read-only; no spawn, no model
    call. Raises ``KeyError`` for an unknown project and ``ValueError`` for an
    unknown session so the CLI prints a clean error.
    """
    import sessions as _sessions
    import deliverables as _deliv
    _proj, folder = _rnd_resolve(project_id)
    session = None
    for s in _sessions.list_sessions(folder, project_id, lane):
        if s.get("session_id") == session_id:
            session = s
            break
    if session is None:
        raise ValueError(f"unknown session: {session_id}")
    return _deliv.resolve_build_deliverable(folder, project_id, session)


def rnd_chain(project_id, session_id):
    """CLI mirror of ``session_registry.chain_for`` + ``chain_members`` (v6 Wave 2).

    Resolves the ordered lineage chain (research → planning → build, then by
    ``created_at``) that ``session_id`` belongs to. Returns
    ``{chain_id, members}`` where ``members`` is a SAFE projection of each
    record (``session_id`` · ``lane`` · ``label`` · ``status`` ·
    ``parent_session_id`` · ``chain_id`` — never ``worktree_path`` / ``branch``),
    mirroring the read-only ``GET /api/rnd/chain`` contract. When the session is
    unknown (no chain), returns ``{chain_id: None, members: []}`` — honest-absent,
    never fabricated. Read-only; no spawn, no model call. Raises ``KeyError`` for
    an unknown project.
    """
    import session_registry as _sreg
    # Validate the project id (the chain lives in the global session registry,
    # but we keep the resolve for a clean unknown-project error like the others).
    _rnd_resolve(project_id)
    chain_id = _sreg.chain_for(session_id)
    members_raw = _sreg.chain_members(chain_id) if chain_id else []
    members = []
    for r in members_raw:
        if not isinstance(r, dict):
            continue
        members.append({
            "session_id": r.get("session_id", ""),
            "lane": r.get("lane", ""),
            "label": r.get("label", ""),
            "status": r.get("status", ""),
            "parent_session_id": r.get("parent_session_id", ""),
            "chain_id": r.get("chain_id", ""),
        })
    return {"chain_id": chain_id, "members": members}


def rnd_remote(project_id):
    """CLI mirror of ``project_remote.remote_status`` — the offsite link state (v8).

    READ-ONLY: returns the project's GitHub remote link + auto-push opt-in state
    (``{linked, remote_url, auto_push}``) from the persisted registry record —
    NEVER touches the network / real ``gh`` / real github.com, and never pushes
    (linking / pushing / toggling are interactive mutating ops with no CLI form).
    Honest-absent: an unlinked project returns ``linked=False`` + an empty url.
    Raises ``KeyError`` for an unknown project.
    """
    import project_remote as _remote
    # Validate the id (remote_status is best-effort and returns the unlinked
    # default for an unknown id; keep the clean unknown-project error like the
    # other mirrors).
    _rnd_resolve(project_id)
    return _remote.remote_status(project_id)


def rnd_docs(project_id, lane, session_id):
    """CLI mirror of ``effort_history.efforts_for_session_id`` — persisted docs (v8).

    READ-ONLY: returns the list of documents a session PERSISTED into the main
    project (the v8 Wave-2 keystone stamps each persisted doc effort with the
    originating managed ``session_id``). Each item is a SAFE projection
    ``{title, kind, path, status}`` resolved from the lane's pointer-records —
    honest-absent (``[]``) when the session produced/persisted nothing. No spawn,
    no model call. Raises ``KeyError`` for an unknown project.
    """
    import effort_history as _eh
    _proj, folder = _rnd_resolve(project_id)
    store_lane = _eh._resolve_subdir(lane)
    efforts = _eh.efforts_for_session_id(folder, project_id, store_lane,
                                         session_id)
    docs = []
    for e in efforts:
        rel = e.get("artifact_path", "") or ""
        if not rel:
            continue
        docs.append({
            "title": e.get("title", "") or "",
            "kind": e.get("kind", "") or "",
            "path": rel,
            "status": e.get("status", "") or "",
        })
    return docs


def rnd_folders():
    """CLI mirror of ``rnd_registry.group_by_group`` — the project folders (v9).

    READ-ONLY: returns the project organization as an ordered dict
    ``{group_name: [project_entry, ...]}`` — named groups (alphabetical) first,
    with ``Ungrouped`` always last. The ``group`` field is dashboard-only
    organization; this NEVER moves anything on disk (the guarded on-disk move is
    an interactive mutating op with no CLI form). Honest-absent: a project with
    no ``group`` buckets under ``Ungrouped``. No project arg — lists every
    project grouped.
    """
    import rnd_registry as _rnd
    return _rnd.group_by_group()


def rnd_ghost_sessions(project_id):
    """CLI mirror — list a project's empty/ghost managed sessions (v9).

    READ-ONLY: returns the managed session records that
    ``terminal_session.cleanup_ghost_sessions`` WOULD remove — a *ghost* is a
    non-running (DONE/FAILED/IDLE) registry session with NO effort pointer-records
    tied to it in its lane (a phantom tile that produced nothing Anchor recorded).
    This is a pure listing: it NEVER deletes/kills anything (delete is an
    interactive mutating op with no one-shot CLI form). A live RUNNING session is
    never a ghost and is excluded. Each item is a SAFE projection
    ``{session_id, lane, status, label}``. Honest-absent: ``[]`` when there are no
    ghosts. Raises ``KeyError`` for an unknown project.
    """
    import session_registry as _sreg
    import effort_history as _eh
    _proj, folder = _rnd_resolve(project_id)
    ghosts = []
    for rec in _sreg.list_sessions(project_id=project_id):
        if rec.get("status") == _sreg.STATUS_RUNNING:
            continue  # a live session is never a ghost
        sid = rec.get("session_id", "")
        lane = rec.get("lane", "") or ""
        has_efforts = False
        if folder and lane:
            try:
                has_efforts = bool(_eh.efforts_for_session_id(
                    folder, project_id, lane, sid))
            except Exception:
                has_efforts = False
        if has_efforts:
            continue  # produced recorded work — not a ghost
        ghosts.append({
            "session_id": sid,
            "lane": lane,
            "status": rec.get("status", "") or "",
            "label": rec.get("label", "") or "",
        })
    return ghosts


def rnd_boneyard(project_id, search=None):
    """CLI mirror of ``boneyard.list_entries`` / ``boneyard.search`` (v10).

    READ-ONLY: returns the project's Boneyard — the per-project, searchable INDEX
    over DISCARDED material (a hard-KILLED session that produced docs, a v9-DELETED
    session, or a DELETED grass idea), NEWEST-FIRST, as SAFE projections (never an
    absolute path / worktree / branch — only the ``boneyard._SAFE_KEYS``). With
    ``search`` given it delegates to the stdlib token/substring search over the
    title + summary excerpt + idea text + doc paths; otherwise it lists every
    entry. This NEVER deletes/removes anything (the Boneyard is purely additive;
    pruning is an interactive op with no CLI form). Honest-absent: ``[]`` when the
    project has discarded nothing. Raises ``KeyError`` for an unknown project.
    """
    import boneyard as _bone
    _proj, folder = _rnd_resolve(project_id)
    q = (search or "").strip()
    if q:
        return _bone.search(folder, project_id, q)
    return _bone.list_entries(folder, project_id)


def rnd_events(project_id, since=None):
    """CLI mirror of ``journal.read_events`` (rearch W13, C3 — the journal tail).

    READ-ONLY: returns the project's schema-versioned journal events, in journal
    (append) order — OLDEST-first, NEWEST-LAST — from the per-project append-only
    ``journal.jsonl``. With ``since`` given, only events whose ``seq`` is strictly
    greater are returned (the "what happened while I was away" tail). This never
    calls a model and never touches the live ``:8777`` server — it reads the
    on-disk journal only, tolerating unknown fields / a higher ``schema_ver`` per
    the journal's schema-evolution rule. Honest-absent: ``[]`` when the project
    has no journal yet (the ``journal`` pillar flag has never been on for it).
    Raises ``KeyError`` for an unknown project.
    """
    import journal as _journal
    _proj, folder = _rnd_resolve(project_id)
    since_seq = None
    if since is not None and str(since).strip() != "":
        try:
            since_seq = int(since)
        except (TypeError, ValueError):
            raise ValueError(f"--since must be an integer seq (got {since!r})")
    return _journal.read_events(project_id, folder_path=folder,
                                since_seq=since_seq)


def rnd_gandalf(project_id):
    """CLI mirror of ``gandalf.list_runs`` (Gandalf v1).

    READ-ONLY: returns the project's Gandalf run history — the honest "what's
    really going on here" reads — NEWEST-FIRST, as SAFE projections (never an
    absolute path; only ``ts · run_id · verdict · cross_model · degraded · ok ·
    report_rel · exec_rel · advisor_rel · reason?``). This NEVER runs the model /
    the host (run/re-run is interactive, no CLI form) — it reads the internal
    index only. Honest-absent: ``[]`` when no Gandalf read has happened yet.
    Raises ``KeyError`` for an unknown project.
    """
    import gandalf as _gandalf
    _proj, folder = _rnd_resolve(project_id)
    return _gandalf.list_runs(folder, project_id)


def rnd_reaper_explain():
    """CLI mirror of ``reaper_arming.explain`` (Wave 8, reaper-explain).

    READ-ONLY inspection: dumps the reaper's current liveness snapshot summary,
    the live-owner set, each running session's classification + latest
    owner-evidence receipt, the current arm tier + distance-to-bar, the
    disarm/kill-switch-brake state, and the consecutive-abstain health banner.
    GLOBAL (not project-scoped) — the reaper governs the whole service. NEVER
    runs the model / kills / freezes; it reads the registry + the tamper-evident
    receipt chain only. Returns the explain dict.
    """
    import reaper_arming as _arm
    return _arm.explain()


def rnd_next_prompt(project_id, session_id):
    """CLI mirror — the generated next-stage handoff prompt for a session (v10).

    READ-ONLY: returns the reviewable next-stage prompt (the ``NEXT-PROMPT.md``
    body) that a v10 advance delivered as a PENDING PASTE — the prompt sitting in
    the next stage's terminal input UNSENT. Resolution prefers the CLEANEST DURABLE
    read source, in order, and NEVER starts a session / runs a model:

      1. the session record's ``pending_paste`` (the exact unsent prompt, when it
         has not yet been flushed);
      2. the durable ``NEXT-PROMPT.md`` written into the session's worktree;
      3. a best-effort rebuild via ``handoff.build_next_stage_prompt`` for a
         linked CHILD session (using its parent + lane), so a flushed/started
         session can still surface the prompt it was handed.

    Returns a ``str`` (possibly multi-line). Honest-absent: ``""`` when no handoff
    prompt resolves. Raises ``KeyError`` for an unknown project.
    """
    import session_registry as _sreg
    import handoff as _handoff
    _proj, folder = _rnd_resolve(project_id)
    rec = _sreg.get_session(session_id)
    if rec is None:
        return ""

    # 1) The exact unsent prompt held on the record (cleanest source).
    pending = (rec.get("pending_paste") or "").strip()
    if pending:
        return pending

    # 2) The durable NEXT-PROMPT.md in the session's worktree (survives the flush).
    wt = rec.get("worktree_path") or ""
    if wt:
        try:
            from pathlib import Path as _Path
            np = _Path(wt) / _handoff.NEXT_PROMPT_FILENAME
            if np.is_file():
                body = np.read_text(encoding="utf-8")
                if body.strip():
                    return body.rstrip("\r\n")
        except OSError:
            pass

    # 3) Rebuild for a linked child session from its parent + lane (read-only).
    parent = (rec.get("parent_session_id") or "").strip()
    if parent:
        try:
            text = _handoff.build_next_stage_prompt(
                folder, project_id, parent, rec.get("lane") or "")
            if text and text.strip():
                return text.rstrip("\r\n")
        except Exception:
            pass
    return ""


# ── telemetry-resume W3 "Narration floor" inspection mirror (read-only) ──────

def rnd_narration(project_id, lane, session_id):
    """CLI mirror of ``narration.narrate_session`` — the Layer-1 warm narration.

    READ-ONLY, cache-only: returns the deterministic narration SPINE (done /
    produced / next) a session tile renders as the first-click 'warm terminal
    that narrates'. NEVER spawns a PTY, runs the model, or touches the network —
    a summary-less session renders the honest floor (no ``enrichment='generating'``
    trigger from the CLI, which does not schedule background work). Raises
    ``KeyError`` for an unknown project.
    """
    import narration as _narr
    _proj, folder = _rnd_resolve(project_id)
    return _narr.narrate_session(project_id, lane, session_id,
                                 folder_path=folder)


def rnd_narration_coverage(project_id=None):
    """CLI mirror of ``narration.coverage_report`` — the honest two-number report.

    Template coverage (MUST be 1.0 — the deterministic floor is TOTAL over every
    record class) + enrichment coverage (the fraction served from a cached model
    summary). Runs over the LIVE ``session_registry`` (optionally one project) +
    each lane's finished one-shot-job efforts. Read-only; never runs the model.
    """
    import narration as _narr
    import session_registry as _sreg
    import effort_history as _eh
    import summarizer as _s
    sessions = []
    try:
        sessions = _sreg.list_sessions(project_id=project_id) or []
    except Exception:
        sessions = []
    # Finished one-shot-job efforts: RUN-provenance efforts with a cost block and
    # no owning managed session, across each project's trio lanes.
    efforts = []
    folders = {}
    try:
        import rnd_registry as _rnd2
        pids = {r.get("project_id") for r in sessions if r.get("project_id")}
        if project_id:
            pids.add(project_id)
        for pid in pids:
            proj = _rnd2.get_project(pid)
            folder = (proj or {}).get("folder_path", "")
            folders[pid] = folder
            for lane in ("research", "planning", "build"):
                try:
                    for e in _eh.list_efforts(folder, pid, lane):
                        if (e.get("provenance") == "run"
                                and not (e.get("session_id") or "")
                                and isinstance(e.get("cost"), dict)):
                            efforts.append(e)
                except Exception:
                    pass
    except Exception:
        pass

    def _enrich(rec):
        pid = rec.get("project_id") or ""
        folder = folders.get(pid, "")
        lane = rec.get("lane") or ""
        try:
            store_lane = _eh._resolve_subdir(lane) if lane else lane
            return _s.load_cached(folder, pid, store_lane or lane,
                                  rec.get("session_id") or "")
        except Exception:
            return None

    return _narr.coverage_report(sessions, efforts, enrichment_lookup=_enrich)


# ── R&D v12 "Efforts" inspection mirror (read-only) ──────────────────────

def rnd_efforts(project_id):
    """CLI mirror of ``effort_view.build_effort_view`` — the project's efforts (v12).

    READ-ONLY: returns the project's efforts (legacy research→plan→build *chains*
    and new v12 single-session efforts rendered UNIFORMLY as one effort each),
    rebuilt from the ``session_registry`` on every call (a derived cache, never a
    stored source). Each entry is a SAFE projection
    ``{effort_id, current_stage, status, stage_count}`` — NEVER a ``worktree_path``
    / ``branch`` (those are stripped by ``effort_view``'s member projections, which
    this further reduces). Honest-absent: ``[]`` when the project has no efforts.
    Raises ``KeyError`` for an unknown project.
    """
    import effort_view as _ev
    _proj, folder = _rnd_resolve(project_id)
    efforts = _ev.build_effort_view(folder, project_id) or []
    out = []
    for eff in efforts:
        if not isinstance(eff, dict):
            continue
        out.append({
            "effort_id": eff.get("effort_id", "") or "",
            "current_stage": eff.get("current_stage", "") or "",
            "status": eff.get("status", "") or "",
            "stage_count": len(eff.get("stage_history", []) or []),
        })
    return out


def rnd_effort(project_id, session_id):
    """CLI mirror of ``effort_view.effort_for_session`` — one effort's stages (v12).

    READ-ONLY: returns the ordered ``stage_history`` of the effort the given
    ``session_id`` belongs to, as a SAFE projection of each stage entry
    ``{stage, state, doc_count, summary_ref}`` — NEVER ``baseline_ref`` (a git
    SHA), ``store_lane``, ``worktree_path`` or ``branch`` (matching the
    ``/api/rnd/advance_stage`` SAFE-projection contract). Returns
    ``{effort_id, current_stage, status, stage_history}``; honest-absent
    (``stage_history==[]`` / ``effort_id==None``) for an unknown session or one
    with no effort. No spawn, no model call. Raises ``KeyError`` for an unknown
    project.
    """
    import effort_view as _ev
    _proj, folder = _rnd_resolve(project_id)
    eff = _ev.effort_for_session(folder, project_id, session_id)
    if not isinstance(eff, dict):
        return {"effort_id": None, "current_stage": "", "status": "",
                "stage_history": []}
    stages = []
    for ent in eff.get("stage_history", []) or []:
        if not isinstance(ent, dict):
            continue
        stages.append({
            "stage": ent.get("stage", "") or "",
            "state": ent.get("state", "") or "",
            "doc_count": int(ent.get("doc_count", 0) or 0),
            "summary_ref": ent.get("summary_ref"),
        })
    return {
        "effort_id": eff.get("effort_id", "") or "",
        "current_stage": eff.get("current_stage", "") or "",
        "status": eff.get("status", "") or "",
        "stage_history": stages,
    }


def rnd_effort_deliverable(project_id, session_id):
    """CLI mirror of ``deliverables.resolve_build_deliverable`` (effort-scoped) (v12).

    READ-ONLY: resolves the deliverable an EFFORT's BUILD stage produced — feeding
    the resolver the live session RECORD as a v12 effort subject (it carries
    ``current_stage`` / ``stage_history`` / ``session_id``), so the resolver scopes
    to the BUILD-stage doc set ONLY (a plan-stage ``MASTER-PLAN.md`` can never be
    mis-resolved as the build product — Shark C6). Returns the
    ``{resolved, deliverable, signal, reason}`` dict — an HONEST ``resolved=False``
    when the effort is not at the build stage or has no build signal (never a
    fabricated path). No spawn, no model call. Raises ``KeyError`` for an unknown
    project and ``ValueError`` for an unknown session.
    """
    import session_registry as _sreg
    import deliverables as _deliv
    _proj, folder = _rnd_resolve(project_id)
    rec = _sreg.get_session(session_id)
    if rec is None:
        raise ValueError(f"unknown session: {session_id}")
    return _deliv.resolve_build_deliverable(folder, project_id, rec)


# ── CLI ────────────────────────────────────────────────────────────────

def main():
    # Print UTF-8 regardless of the console code page. On a Windows cp1252 console
    # `print()` of non-ASCII output (e.g. a grass idea title containing "→" or an
    # em-dash) otherwise raises UnicodeEncodeError and aborts the command. Best-
    # effort: reconfigure stdout/stderr to UTF-8 with replacement (Python 3.7+).
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass

    if len(sys.argv) < 2:
        print(__doc__)
        return

    cmd = sys.argv[1].lower()

    if cmd == "dashboard":
        rebuild_dashboard()

    elif cmd == "update":
        import update_transaction
        update_transaction.run_update(sys.argv[2:])

    elif cmd == "edits":
        import update_transaction
        update_transaction.run_edits(sys.argv[2:])

    elif cmd == "status":
        print_status()

    elif cmd == "doctor":
        import doctor
        sys.exit(doctor.run_doctor(sys.argv[2:]))

    elif cmd == "done":
        if len(sys.argv) < 3:
            print("Usage: anchor.py done \"task text\"")
            return
        mark_done(" ".join(sys.argv[2:]))

    elif cmd == "cancel":
        if len(sys.argv) < 3:
            print("Usage: anchor.py cancel \"task text\"")
            return
        cancel_task(" ".join(sys.argv[2:]))

    elif cmd == "save":
        if len(sys.argv) < 3:
            print("Usage: anchor.py save \"task text\"")
            return
        save_for_later(" ".join(sys.argv[2:]))

    elif cmd == "restore":
        if len(sys.argv) < 3:
            print("Usage: anchor.py restore \"task text\" --from saved|cancelled")
            return
        text_parts = []
        from_archive = "saved"
        i = 2
        while i < len(sys.argv):
            if sys.argv[i] == "--from" and i+1 < len(sys.argv):
                from_archive = sys.argv[i+1]; i += 2
            else:
                text_parts.append(sys.argv[i]); i += 1
        restore_task(" ".join(text_parts), from_archive)

    elif cmd == "add":
        if len(sys.argv) < 3:
            print("Usage: anchor.py add \"task\" --domain academic --priority 1 --energy high --due 2026-04-10 --notes \"some note\"")
            return
        # Parse arguments
        text_parts = []
        domain = "academic"
        priority = 2
        energy = "med"
        due = ""
        notes = ""
        i = 2
        while i < len(sys.argv):
            arg = sys.argv[i]
            if arg == "--domain" and i+1 < len(sys.argv):
                domain = sys.argv[i+1]; i += 2
            elif arg == "--priority" and i+1 < len(sys.argv):
                priority = int(sys.argv[i+1]); i += 2
            elif arg == "--energy" and i+1 < len(sys.argv):
                energy = sys.argv[i+1]; i += 2
            elif arg == "--due" and i+1 < len(sys.argv):
                due = sys.argv[i+1]; i += 2
            elif arg == "--notes" and i+1 < len(sys.argv):
                notes = sys.argv[i+1]; i += 2
            else:
                text_parts.append(arg); i += 1
        add_task(" ".join(text_parts), domain, priority, energy, due, notes)

    elif cmd == "link":
        # anchor.py link "task text" --project <id>   (or --unlink to remove)
        if len(sys.argv) < 3:
            print("Usage: anchor.py link \"task text\" --project <id> | --unlink")
            return
        text_parts = []
        project_id = ""
        i = 2
        while i < len(sys.argv):
            if sys.argv[i] == "--project" and i + 1 < len(sys.argv):
                project_id = sys.argv[i + 1]; i += 2
            elif sys.argv[i] == "--unlink":
                project_id = ""; i += 1
            else:
                text_parts.append(sys.argv[i]); i += 1
        link_task(" ".join(text_parts), project_id)

    elif cmd == "capture":
        if len(sys.argv) < 3:
            print("Usage: anchor.py capture \"idea\" [--domain academic]")
            return
        text_parts = []
        domain = ""
        i = 2
        while i < len(sys.argv):
            if sys.argv[i] == "--domain" and i+1 < len(sys.argv):
                domain = sys.argv[i+1]; i += 2
            else:
                text_parts.append(sys.argv[i]); i += 1
        capture_inbox(" ".join(text_parts), domain)

    elif cmd == "rnd":
        _rnd_cli(sys.argv[2:])

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)


# ── R&D CLI dispatcher (Wave 8) ────────────────────────────────────────────

def _rnd_cli(args):
    """Dispatch ``anchor.py rnd <subcommand> ...`` to the v2 mirror functions.

    Follows anchor.py's existing manual-arg-parsing convention (no argparse).
    Each subcommand resolves a project by id and delegates to the shared module;
    no R&D logic is reimplemented here.
    """
    if not args:
        print("Usage: anchor.py rnd <sessions|status|reconcile|add-idea|"
              "promote-inbox|pin-deliverable|set-blurb|regenerate-summary|"
              "term-sessions|previews|handoff|rollup|doc-roles|"
              "deliverable-type|engine|session-summary|grass|"
              "build-deliverable|chain|blurb|remote|docs|"
              "folders|ghost-sessions|boneyard|next-prompt|"
              "narration|narration-coverage|"
              "events|efforts|effort|effort-deliverable> ...")
        return
    sub = args[0].lower()
    rest = args[1:]

    def _opt(name, default=None):
        if name in rest:
            i = rest.index(name)
            if i + 1 < len(rest):
                return rest[i + 1]
        return default

    def _flag(name):
        return name in rest

    def _positionals():
        """Positional args = everything not consumed by a --flag or its value."""
        out = []
        skip = False
        for i, a in enumerate(rest):
            if skip:
                skip = False
                continue
            if a.startswith("--"):
                # flags that take a value consume the next token
                if a in ("--lane", "--session", "--notes", "--name",
                         "--type", "--desc", "--seed-session", "--window",
                         "--search", "--since"):
                    skip = True
                continue
            out.append(a)
        return out

    try:
        if sub == "sessions":
            pos = _positionals()
            if not pos:
                print("Usage: anchor.py rnd sessions <project_id> --lane <lane>")
                return
            lane = _opt("--lane", "planning")
            sessions = rnd_list_sessions(pos[0], lane)
            print(f"{len(sessions)} session(s) in lane '{lane}':")
            for s in sessions:
                prov = s.get("provenance", "")
                n = len(s.get("member_files", []))
                print(f"  - [{prov}] {s.get('title','(untitled)')} "
                      f"— {n} file(s) - id={s.get('session_id','')}")

        elif sub == "status":
            pos = _positionals()
            if not pos:
                print("Usage: anchor.py rnd status <project_id>")
                return
            sl = rnd_status_line(pos[0])
            print(f"Status line for {pos[0]}:")
            for lane, counts in sl.items():
                print(f"  {lane:<13} count={counts.get('count',0)} "
                      f"imported={counts.get('imported',0)} "
                      f"running={counts.get('running',0)}")

        elif sub == "reconcile":
            pos = _positionals()
            if not pos:
                print("Usage: anchor.py rnd reconcile <project_id> [--apply]")
                return
            apply = _flag("--apply")
            report = rnd_reconcile(pos[0], apply=apply)
            if not report.get("ok"):
                print(f"Reconcile failed: {report.get('reason')}")
                return
            mode = "APPLIED" if report.get("applied") else "PREVIEW (dry-run)"
            print(f"Reconcile {mode} for {report.get('active_id')} "
                  f"(folder: {report.get('folder_path')})")
            for f in report.get("fold", []):
                print(f"  fold {f['id']} ({f.get('name','')}): "
                      f"{f.get('total_efforts',0)} effort(s) {f.get('efforts',{})}")
            print(f"  to_delete: {report.get('to_delete', [])}")
            if report.get("applied"):
                print(f"  imported: {report.get('imported',0)}  "
                      f"deleted: {report.get('deleted', [])}")

        elif sub == "add-idea":
            pos = _positionals()
            if len(pos) < 2:
                print('Usage: anchor.py rnd add-idea <project_id> "idea text" '
                      '[--notes "..."]')
                return
            _proj, folder = _rnd_resolve(pos[0])
            rec = add_idea(folder, pos[0], " ".join(pos[1:]),
                           notes=_opt("--notes", ""))
            print(f"OK: Idea added to grass lane: {rec.get('title','')} "
                  f"(job_id={rec.get('job_id','')})")

        elif sub == "promote-inbox":
            pos = _positionals()
            if len(pos) < 2:
                print('Usage: anchor.py rnd promote-inbox <project_id> '
                      '"inbox item text"')
                return
            _proj, folder = _rnd_resolve(pos[0])
            rec = promote_inbox(folder, pos[0], " ".join(pos[1:]))
            print(f"OK: Promoted INBOX item to grass lane: {rec.get('title','')}")

        elif sub == "pin-deliverable":
            pos = _positionals()
            if len(pos) < 2:
                print("Usage: anchor.py rnd pin-deliverable <project_id> <path> "
                      "[--name N] [--type doc|script|skill|program] [--desc ...]")
                return
            rec = rnd_pin_deliverable(pos[0], pos[1], name=_opt("--name"),
                                      dtype=_opt("--type"),
                                      description=_opt("--desc", ""))
            print(f"OK: Pinned deliverable: {rec.get('title','')} "
                  f"[{rec.get('deliverable_type','')}] -> {rec.get('artifact_path','')}")

        elif sub == "set-blurb":
            pos = _positionals()
            if len(pos) < 2:
                print('Usage: anchor.py rnd set-blurb <project_id> "blurb text"')
                return
            entry = rnd_set_blurb(pos[0], " ".join(pos[1:]))
            print(f"OK: Blurb set: {entry.get('blurb','')}")

        elif sub == "regenerate-summary":
            pos = _positionals()
            lane = _opt("--lane")
            session_id = _opt("--session")
            if not pos or not lane or not session_id:
                print("Usage: anchor.py rnd regenerate-summary <project_id> "
                      "--lane <lane> --session <session_id>")
                return
            summary = rnd_regenerate_summary(pos[0], lane, session_id)
            claims = summary.get("claims", [])
            print(f"OK: Summary regenerated for session {session_id}: "
                  f"{len(claims)} grounded claim(s)")

        elif sub == "term-sessions":
            pos = _positionals()
            if not pos:
                print("Usage: anchor.py rnd term-sessions <project_id>")
                return
            recs = rnd_term_sessions(pos[0])
            print(f"{len(recs)} managed terminal session(s):")
            for r in recs:
                print(f"  - [{r.get('status','')}] {r.get('lane','')}"
                      f"/{r.get('backend','')} "
                      f"{r.get('label','') or '(no label)'} "
                      f"- id={r.get('session_id','')}")

        elif sub == "previews":
            pos = _positionals()
            if not pos:
                print("Usage: anchor.py rnd previews <project_id>")
                return
            recs = rnd_previews(pos[0])
            print(f"{len(recs)} deliverable preview(s):")
            for r in recs:
                print(f"  - [{r.get('status','')}] {r.get('target','')} "
                      f"port={r.get('port','')} {r.get('url','')} "
                      f"- id={r.get('preview_id','')}")

        elif sub == "handoff":
            pos = _positionals()
            if not pos:
                print("Usage: anchor.py rnd handoff <project_id> "
                      "[--lane build] [--seed-session <session_id>]")
                return
            lane = _opt("--lane", "build")
            seed = _opt("--seed-session")
            out = rnd_handoff(pos[0], lane=lane, seed_session=seed)
            prop = out.get("proposal", {})
            if prop.get("has_plan_set"):
                ps = prop.get("plan_set", {})
                print(f"Most-recent plan set (lane '{lane}'): "
                      f"{ps.get('title','(untitled)')}")
                print(f"  master: {ps.get('master_plan_rel','')}")
                print(f"  impl:   {ps.get('impl_plan_rel','')}")
                print(f"  plan dir: {ps.get('plan_dir','')}")
            else:
                print(f"No plan set available for lane '{lane}'.")
            recorded = out.get("handoffs", [])
            print(f"{len(recorded)} recorded handoff(s):")
            for h in recorded:
                print(f"  - build={h.get('build_session_id','')} "
                      f"plan={h.get('plan_session_id','')} "
                      f"dir={h.get('plan_dir','')}")

        elif sub == "rollup":
            pos = _positionals()
            if not pos:
                print("Usage: anchor.py rnd rollup <project_id> "
                      "[--window lifetime|30d]")
                return
            window = _opt("--window", "lifetime")
            roll = rnd_rollup(pos[0], window=window)
            secs = (roll.get("wall_clock_ms", 0) or 0) / 1000.0
            print(f"Effort rollup for {pos[0]} (window: {window}):")
            print(f"  tokens:     {roll.get('tokens', 0)}")
            print(f"  cost_usd:   ${roll.get('cost_usd', 0.0)}")
            print(f"  wall-clock: {secs:.1f}s")
            print(f"  sessions:   {roll.get('sessions', 0)} (run-only)")

        elif sub == "doc-roles":
            pos = _positionals()
            lane = _opt("--lane")
            session_id = _opt("--session")
            if not pos or not lane or not session_id:
                print("Usage: anchor.py rnd doc-roles <project_id> "
                      "--lane <lane> --session <session_id>")
                return
            roles = rnd_doc_roles(pos[0], lane, session_id)
            print(f"{len(roles)} doc role(s) for session {session_id} "
                  f"(lane '{lane}'):")
            for role, meta in roles.items():
                print(f"  {role:<12} {meta.get('label','')} "
                      f"-> {meta.get('href','')}")

        elif sub == "deliverable-type":
            pos = _positionals()
            if len(pos) < 2:
                print("Usage: anchor.py rnd deliverable-type <project_id> "
                      "<deliverable_id>")
                return
            info = rnd_deliverable_type(pos[0], pos[1])
            print(f"Deliverable {info['deliverable_id']}:")
            print(f"  type:     {info.get('type','')}")
            print(f"  path:     {info.get('artifact_path','')}")
            print(f"  title:    {info.get('title','')}")
            ver = info.get("verify")
            if ver:
                print(f"  verify:   {ver.get('status','')} "
                      f"({ver.get('detail','')})")

        elif sub == "engine":
            pos = _positionals()
            if not pos:
                print("Usage: anchor.py rnd engine <project_id>")
                return
            eng = rnd_engine(pos[0])
            print(f"Last-used engine for {pos[0]}: {eng}")

        elif sub == "session-summary":
            pos = _positionals()
            lane = _opt("--lane")
            session_id = _opt("--session")
            if not pos or not lane or not session_id:
                print("Usage: anchor.py rnd session-summary <project_id> "
                      "--lane <lane> --session <session_id>")
                return
            summary = rnd_session_summary(pos[0], lane, session_id)
            if summary is None:
                print(f"No cached summary for session {session_id} "
                      f"(lane '{lane}'). Run `rnd regenerate-summary` to "
                      f"generate one.")
                return
            print(f"Session summary for {session_id} (lane '{lane}'):")
            print(f"  skill:    {summary.get('skill','') or '(none)'}")
            prompts = summary.get("prompts", []) or []
            print(f"  prompts:  {len(prompts)}")
            for p in prompts:
                print(f"    - {str(p).strip()[:100]}")
            actions = summary.get("actions", []) or []
            print(f"  actions:  {len(actions)}")
            for a in actions:
                print(f"    - {str(a).strip()[:100]}")
            claims = summary.get("claims", []) or []
            print(f"  claims:   {len(claims)} grounded")

        elif sub == "blurb":
            pos = _positionals()
            lane = _opt("--lane")
            session_id = _opt("--session")
            if not pos or not lane or not session_id:
                print("Usage: anchor.py rnd blurb <project_id> "
                      "--lane <lane> --session <session_id>")
                return
            blurb = rnd_blurb(pos[0], lane, session_id)
            if not (blurb or "").strip():
                print(f"Session {session_id} (lane '{lane}'): (no summary yet)")
                return
            print(f"Session {session_id} (lane '{lane}'): {blurb}")

        elif sub == "grass":
            pos = _positionals()
            if not pos:
                print("Usage: anchor.py rnd grass <project_id>")
                return
            ideas = rnd_grass(pos[0])
            print(f"{len(ideas)} grass idea(s):")
            for it in ideas:
                refs = it.get("refinements", []) or []
                promoted = it.get("promoted_to_session", "")
                link = f" -> {promoted}" if promoted else ""
                print(f"  - [{it.get('status','')}] {it.get('title','')} "
                      f"({it.get('short_id','')}) "
                      f"src={it.get('source','')} "
                      f"refinements={len(refs)}{link} "
                      f"- id={it.get('idea_id','')}")

        elif sub == "build-deliverable":
            pos = _positionals()
            session_id = _opt("--session")
            lane = _opt("--lane", "build")
            if not pos or not session_id:
                print("Usage: anchor.py rnd build-deliverable <project_id> "
                      "--session <session_id> [--lane build]")
                return
            res = rnd_build_deliverable(pos[0], session_id, lane=lane)
            if res.get("resolved"):
                d = res.get("deliverable", {}) or {}
                print(f"Build deliverable for session {session_id}: RESOLVED")
                print(f"  name:   {d.get('name','')}")
                print(f"  type:   {d.get('type','')}")
                print(f"  path:   {d.get('rel') or d.get('path','')}")
                print(f"  signal: {res.get('signal','')}")
            else:
                print(f"Build deliverable for session {session_id}: "
                      f"UNRESOLVED")
                print(f"  reason: {res.get('reason','no deliverable pinned yet')}")

        elif sub == "chain":
            pos = _positionals()
            session_id = _opt("--session")
            if not pos or not session_id:
                print("Usage: anchor.py rnd chain <project_id> "
                      "--session <session_id>")
                return
            out = rnd_chain(pos[0], session_id)
            members = out.get("members", []) or []
            if not members:
                print(f"No chain for session {session_id} "
                      f"(unknown session or no lineage).")
                return
            print(f"Chain {out.get('chain_id','')} "
                  f"({len(members)} session(s), research -> planning -> build):")
            for m in members:
                marker = " *" if m.get("session_id") == session_id else ""
                parent = m.get("parent_session_id", "") or "(root)"
                print(f"  - [{m.get('lane','')}] {m.get('label','') or '(no label)'} "
                      f"status={m.get('status','')} "
                      f"parent={parent} "
                      f"id={m.get('session_id','')}{marker}")

        elif sub == "remote":
            pos = _positionals()
            if not pos:
                print("Usage: anchor.py rnd remote <project_id>")
                return
            st = rnd_remote(pos[0])
            if st.get("linked"):
                print(f"Remote for {pos[0]}: LINKED")
                print(f"  remote_url: {st.get('remote_url','')}")
                print(f"  auto_push:  {'on' if st.get('auto_push') else 'off'}")
            else:
                print(f"Remote for {pos[0]}: NOT LINKED")
                print(f"  auto_push:  {'on' if st.get('auto_push') else 'off'}")

        elif sub == "docs":
            pos = _positionals()
            lane = _opt("--lane", "build")
            session_id = _opt("--session")
            if not pos or not session_id:
                print("Usage: anchor.py rnd docs <project_id> "
                      "--session <session_id> [--lane <lane>]")
                return
            docs = rnd_docs(pos[0], lane, session_id)
            if not docs:
                print(f"No persisted documents for session {session_id} "
                      f"(lane '{lane}').")
                return
            print(f"{len(docs)} persisted document(s) for session {session_id} "
                  f"(lane '{lane}'):")
            for d in docs:
                kind = d.get("kind", "") or "doc"
                print(f"  - [{kind}] {d.get('title','') or d.get('path','')} "
                      f"-> {d.get('path','')}")

        elif sub == "folders":
            groups = rnd_folders()
            # Count only the named (non-empty) groups for the header line.
            named = [g for g in groups if g != "Ungrouped"]
            print(f"{len(named)} folder(s) + Ungrouped:")
            for group, members in groups.items():
                members = members or []
                if group == "Ungrouped" and not members and len(groups) > 1:
                    continue  # don't print an empty Ungrouped when there ARE groups
                print(f"  [{group}] ({len(members)} project(s)):")
                for e in members:
                    print(f"    - {e.get('name','')} "
                          f"(prio={e.get('priority','')}) "
                          f"path={e.get('folder_path','')} "
                          f"id={e.get('id','')}")

        elif sub == "ghost-sessions":
            pos = _positionals()
            if not pos:
                print("Usage: anchor.py rnd ghost-sessions <project_id>")
                return
            ghosts = rnd_ghost_sessions(pos[0])
            if not ghosts:
                print(f"No ghost (empty) sessions for {pos[0]}.")
                return
            print(f"{len(ghosts)} ghost (empty) session(s) for {pos[0]} "
                  f"(cleanup_ghost_sessions would remove these):")
            for g in ghosts:
                print(f"  - [{g.get('lane','')}] "
                      f"{g.get('label','') or '(no label)'} "
                      f"status={g.get('status','')} "
                      f"id={g.get('session_id','')}")

        elif sub == "boneyard":
            pos = _positionals()
            if not pos:
                print("Usage: anchor.py rnd boneyard <project_id> "
                      "[--search <query>]")
                return
            query = _opt("--search")
            entries = rnd_boneyard(pos[0], search=query)
            if not entries:
                if query:
                    print(f"No discarded material matching '{query}' "
                          f"for {pos[0]}.")
                else:
                    print(f"No discarded material for {pos[0]}.")
                return
            head = (f"{len(entries)} discarded item(s) for {pos[0]}"
                    + (f" matching '{query}'" if query else "")
                    + " (newest-first):")
            print(head)
            for e in entries:
                title = e.get("title", "") or e.get("idea_text", "") or "(untitled)"
                lane = e.get("lane", "") or "?"
                docs = e.get("doc_rels", []) or []
                print(f"  - [{e.get('source','')}] {title} "
                      f"(lane={lane}, {len(docs)} doc(s)) "
                      f"id={e.get('entry_id','')}")
                for r in docs:
                    print(f"      · {r}")

        elif sub == "gandalf":
            pos = _positionals()
            if not pos:
                print("Usage: anchor.py rnd gandalf <project_id>")
                return
            runs = rnd_gandalf(pos[0])
            if not runs:
                print(f"No Gandalf read yet for {pos[0]}.")
                return
            print(f"{len(runs)} Gandalf read(s) for {pos[0]} (newest-first):")
            for r in runs:
                ts = r.get("ts")
                try:
                    when = (datetime.fromtimestamp(float(ts))
                            .strftime("%Y-%m-%d %H:%M")) if ts else "?"
                except (TypeError, ValueError, OSError):
                    when = "?"
                if r.get("ok"):
                    chips = ("single-family" if not r.get("cross_model")
                             else "cross-model")
                    if r.get("degraded"):
                        chips += ", degraded"
                    verdict = r.get("verdict", "") or "(no verdict)"
                    print(f"  - {when}  [{chips}]  {verdict}")
                    rep = r.get("report_rel")
                    if rep:
                        print(f"      report: {rep}")
                else:
                    print(f"  - {when}  [ERROR]  "
                          f"did not complete: {r.get('reason','unknown')}")

        elif sub == "next-prompt":
            pos = _positionals()
            session_id = _opt("--session")
            if not pos or not session_id:
                print("Usage: anchor.py rnd next-prompt <project_id> "
                      "--session <session_id>")
                return
            prompt = rnd_next_prompt(pos[0], session_id)
            if not prompt:
                print(f"(no handoff prompt) for session {session_id}.")
                return
            print(f"Next-stage handoff prompt for session {session_id}:")
            print(prompt)

        elif sub == "narration":
            pos = _positionals()
            lane = _opt("--lane")
            session_id = _opt("--session")
            if not pos or not lane or not session_id:
                print("Usage: anchor.py rnd narration <project_id> "
                      "--lane <lane> --session <session_id>")
                return
            view = rnd_narration(pos[0], lane, session_id)
            print(f"Layer-1 narration for session {session_id} "
                  f"[{view.get('tile_class','?')}]:")
            print(f"  done:     {view.get('done','')}")
            produced = view.get("produced", []) or []
            if produced:
                print("  produced:")
                for p in produced:
                    role = p.get("role", "") or ""
                    tag = f"{role}: " if role else ""
                    print(f"    - {tag}{p.get('label','')}  ({p.get('href','')})")
            else:
                print(f"  produced: {view.get('produced_note','') or 'none'}")
            nxt = view.get("next") or {}
            print(f"  next:     {nxt.get('text','')} "
                  f"[{nxt.get('source','')}, submit={nxt.get('submit')}]")
            badges = view.get("badges", []) or []
            if badges:
                print(f"  badges:   {', '.join(badges)}")
            print(f"  enrichment: {view.get('enrichment','')}  "
                  f"links_valid={view.get('links_valid')}")

        elif sub == "narration-coverage":
            pos = _positionals()
            rep = rnd_narration_coverage(pos[0] if pos else None)
            scope = pos[0] if pos else "all projects"
            print(f"Narration coverage ({scope}):")
            print(f"  template coverage:   "
                  f"{rep.get('template_covered',0)}/{rep.get('template_total',0)} "
                  f"= {rep.get('template_coverage',0.0)*100:.1f}%  "
                  f"(MUST be 100%)")
            print(f"  enrichment coverage: "
                  f"{rep.get('enrichment_covered',0)}/{rep.get('template_total',0)} "
                  f"= {rep.get('enrichment_coverage',0.0)*100:.1f}%")

        elif sub == "events":
            pos = _positionals()
            if not pos:
                print("Usage: anchor.py rnd events <project_id> [--since <seq>]")
                return
            since = _opt("--since")
            events = rnd_events(pos[0], since=since)
            if not events:
                if since:
                    print(f"No journal events after seq {since} for {pos[0]}.")
                else:
                    print(f"No journal events for {pos[0]} "
                          f"(the journal flag has never been on for it).")
                return
            head = (f"{len(events)} journal event(s) for {pos[0]}"
                    + (f" after seq {since}" if since else "")
                    + " (oldest-first):")
            print(head)
            for e in events:
                actor = e.get("actor", {}) or {}
                akind = actor.get("kind", "") or "?"
                aid = actor.get("id", "") or ""
                who = f"{akind}:{aid}" if aid else akind
                cause = e.get("causation_id")
                causes = f" cause={cause}" if cause else ""
                print(f"  #{e.get('seq','?'):<4} [v{e.get('schema_ver','?')}] "
                      f"{e.get('type','') or '?':<24} "
                      f"corr={e.get('correlation_id','')}{causes} "
                      f"by={who}")

        elif sub == "efforts":
            pos = _positionals()
            if not pos:
                print("Usage: anchor.py rnd efforts <project_id>")
                return
            efforts = rnd_efforts(pos[0])
            if not efforts:
                print(f"No efforts for {pos[0]}.")
                return
            print(f"{len(efforts)} effort(s) for {pos[0]} (newest-first):")
            for e in efforts:
                stage = e.get("current_stage", "") or "(no stage)"
                print(f"  - stage={stage:<9} "
                      f"status={e.get('status','') or '?':<9} "
                      f"stages={e.get('stage_count',0)} "
                      f"id={e.get('effort_id','')}")

        elif sub == "effort":
            pos = _positionals()
            session_id = _opt("--session")
            if not pos or not session_id:
                print("Usage: anchor.py rnd effort <project_id> "
                      "--session <session_id>")
                return
            out = rnd_effort(pos[0], session_id)
            stages = out.get("stage_history", []) or []
            if not out.get("effort_id"):
                print(f"No effort for session {session_id} "
                      f"(unknown session or no effort).")
                return
            print(f"Effort {out.get('effort_id','')} "
                  f"(current_stage={out.get('current_stage','') or '(none)'}, "
                  f"status={out.get('status','') or '?'}, "
                  f"{len(stages)} stage(s), research -> plan -> build):")
            for s in stages:
                sref = "yes" if s.get("summary_ref") else "no"
                print(f"  - [{s.get('stage','')}] state={s.get('state','')} "
                      f"docs={s.get('doc_count',0)} summary={sref}")

        elif sub == "effort-deliverable":
            pos = _positionals()
            session_id = _opt("--session")
            if not pos or not session_id:
                print("Usage: anchor.py rnd effort-deliverable <project_id> "
                      "--session <session_id>")
                return
            res = rnd_effort_deliverable(pos[0], session_id)
            if res.get("resolved"):
                d = res.get("deliverable", {}) or {}
                print(f"Effort build deliverable for session {session_id}: "
                      f"RESOLVED")
                print(f"  name:   {d.get('name','')}")
                print(f"  type:   {d.get('type','')}")
                print(f"  path:   {d.get('rel') or d.get('path','')}")
                print(f"  signal: {res.get('signal','')}")
            else:
                print(f"Effort build deliverable for session {session_id}: "
                      f"UNRESOLVED")
                print(f"  reason: {res.get('reason','no deliverable yet')}")

        elif sub == "reaper":
            # Wave 8 — reaper-explain (GLOBAL, read-only). Dumps the arm tier +
            # distance-to-bar, the disarm/brake state, the abstain health banner,
            # and every running session's classification. NEVER kills/freezes —
            # arm/advance/disarm are interactive mutating ops (no CLI form).
            import reaper_arming as _arm
            dump = rnd_reaper_explain()
            print(_arm.format_explain(dump))

        else:
            print(f"Unknown rnd subcommand: {sub}")
            print(__doc__)
    except KeyError as ke:
        print(f"Unknown project: {ke.args[0] if ke.args else ke}")
    except ValueError as ve:
        print(f"Error: {ve}")


if __name__ == "__main__":
    main()
