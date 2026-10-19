"""W10 / C5 golden-corpus gate — markdown-parser de-fork + dead-server deletion.

Proves the Wave 12 (W10) done-when from ``IMPLEMENTATION-PLAN.md``:

    "Given the complete set of real DASHBOARD.md/domains/INBOX/archive files as a
     golden corpus, when parsed via the pre-de-fork copies and via anchor_md,
     then the parsed structures are identical, byte-for-byte on serialization."

Strategy — a self-contained golden gate:

  * ``_ref_*`` below are a FROZEN, verbatim snapshot of the pre-de-fork
    ``anchor_gui.py`` parser twins (the richer, more-defensive copy that was the
    canonical behavior before extraction). They are the golden reference and are
    intentionally kept as an independent copy here: if ``anchor_md`` ever drifts
    from the pre-de-fork behavior, this test fails rather than the GUI and CLI
    silently diverging again.
  * The gate parses every REAL Anchor markdown file (today's live corpus in the
    repo root) with both the frozen reference and ``anchor_md`` and asserts the
    parsed structures serialize BYTE-FOR-BYTE identically.
  * It also asserts the de-fork is real: ``anchor_gui`` and ``anchor`` re-export
    the *same* callables as ``anchor_md`` (one source of truth), and the dead
    ``anchor_server.py`` is gone.

Hermetic: reads only in-repo markdown; imports the real parsers; no server, no
network, never binds :8777.
"""

import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import anchor_md


# ── Frozen pre-de-fork reference parsers (verbatim snapshot) ──────────────

def _ref_read_md_text(filepath):
    try:
        return filepath.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return filepath.read_text(encoding="utf-8", errors="replace")


def _ref_parse_tasks_from_md(filepath):
    tasks = []
    if not filepath or not filepath.exists():
        return tasks
    text = _ref_read_md_text(filepath)
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
            proj_m = re.search(r'Project:\s*([^\s—]+)', meta, re.I)
            project = proj_m.group(1).strip() if proj_m else ""
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


def _ref_serialize_task_line(task):
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


def _ref_parse_projects_from_md(filepath):
    projects = []
    if not filepath or not filepath.exists():
        return projects
    text = _ref_read_md_text(filepath)
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


def _ref_parse_inbox_from_md(filepath):
    items = []
    if not filepath or not filepath.exists():
        return items
    text = _ref_read_md_text(filepath)
    for line in text.splitlines():
        m = re.match(r'\s*-\s*(\d{4}-\d{2}-\d{2}):\s*(.*?)(?:\s*\[(\w+)\])?\s*$', line)
        if m:
            items.append({"date": m.group(1), "text": m.group(2).strip(),
                          "domain": m.group(3) or ""})
    return items


def _ref_parse_archived_tasks(filepath):
    items = []
    if not filepath or not filepath.exists():
        return items
    text = _ref_read_md_text(filepath)
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


# ── The real golden corpus (today's live markdown files) ──────────────────

def _task_corpus():
    files = [REPO_ROOT / "DASHBOARD.md"]
    domains = REPO_ROOT / "domains"
    if domains.exists():
        files.extend(sorted(domains.glob("*.md")))
    return [f for f in files if f.exists()]


def _project_corpus():
    return [f for f in [REPO_ROOT / "PROJECTS.md"] if f.exists()]


def _inbox_corpus():
    return [f for f in [REPO_ROOT / "INBOX.md"] if f.exists()]


def _archive_corpus():
    return [f for f in [REPO_ROOT / "CANCELLED.md",
                        REPO_ROOT / "SAVED_FOR_LATER.md"] if f.exists()]


def _ser(obj):
    """Byte-for-byte-comparable serialization of a parsed structure."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False)


def test_corpus_is_present_not_vacuous():
    """Guard: the core real markdown files exist, so the gate is not vacuous."""
    assert (REPO_ROOT / "DASHBOARD.md").exists()
    assert (REPO_ROOT / "PROJECTS.md").exists()
    assert (REPO_ROOT / "INBOX.md").exists()
    assert _task_corpus(), "expected at least DASHBOARD.md + domains in the corpus"


@pytest.mark.parametrize("filepath", _task_corpus(), ids=lambda p: p.name)
def test_tasks_parse_identically(filepath):
    ref = _ref_parse_tasks_from_md(filepath)
    new = anchor_md.parse_tasks_from_md(filepath)
    assert _ser(new) == _ser(ref), f"task parse drift on {filepath.name}"


@pytest.mark.parametrize("filepath", _project_corpus(), ids=lambda p: p.name)
def test_projects_parse_identically(filepath):
    ref = _ref_parse_projects_from_md(filepath)
    new = anchor_md.parse_projects_from_md(filepath)
    assert _ser(new) == _ser(ref), f"project parse drift on {filepath.name}"


@pytest.mark.parametrize("filepath", _inbox_corpus(), ids=lambda p: p.name)
def test_inbox_parse_identically(filepath):
    ref = _ref_parse_inbox_from_md(filepath)
    new = anchor_md.parse_inbox_from_md(filepath)
    assert _ser(new) == _ser(ref), f"inbox parse drift on {filepath.name}"


@pytest.mark.parametrize("filepath", _archive_corpus(), ids=lambda p: p.name)
def test_archived_parse_identically(filepath):
    ref = _ref_parse_archived_tasks(filepath)
    new = anchor_md.parse_archived_tasks(filepath)
    assert _ser(new) == _ser(ref), f"archive parse drift on {filepath.name}"


def test_serialize_round_trips_identically():
    """Every real task round-trips (parse→serialize) identically ref vs anchor_md."""
    for f in _task_corpus():
        ref_tasks = _ref_parse_tasks_from_md(f)
        for t in ref_tasks:
            assert anchor_md.serialize_task_line(t) == _ref_serialize_task_line(t)
        # And the full serialized corpus for the file matches, line for line.
        new_tasks = anchor_md.parse_tasks_from_md(f)
        assert [anchor_md.serialize_task_line(t) for t in new_tasks] == \
               [_ref_serialize_task_line(t) for t in ref_tasks]


def test_defork_single_source_of_truth():
    """anchor_gui and anchor re-export the SAME callables as anchor_md."""
    import anchor_gui
    import anchor
    for name in ("parse_tasks_from_md", "parse_projects_from_md",
                 "parse_inbox_from_md", "parse_archived_tasks",
                 "serialize_task_line"):
        canonical = getattr(anchor_md, name)
        assert getattr(anchor_gui, name) is canonical, f"anchor_gui.{name} forked"
        assert getattr(anchor, name) is canonical, f"anchor.{name} forked"


def test_dead_flask_server_deleted():
    """The dead legacy Flask app (the drifted third parser copy) is gone."""
    assert not (REPO_ROOT / "anchor_server.py").exists()
