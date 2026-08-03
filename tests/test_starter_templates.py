"""Share-distro Wave 5 — starter Anchor templates (no data).

Proves the Wave 5 done-when (IMPLEMENTATION-PLAN.md "## Wave 5"):

 1. Given each starter file, When parsed by the EXISTING markdown parser for its
    type (tasks / projects / inbox / archived), Then it PARSES without error AND
    yields ZERO entries (``len == 0``).
 2. Given the ``starter/`` tree, When run through distro.py's no-PII scan
    (``scan_paths``), Then it is CLEAN — these are empty, data-free templates.

The starter files are headers-only skeletons that mirror the REAL Anchor data
files' section structure but carry NONE of John's data. They live under
``starter/`` (manifest-allow-listed ``starter/**``) and the ``starter/domains/``
subdir.

Hermetic: reads only the in-repo ``starter/`` tree; imports the real parsers
(no monkeypatching of paths, no server, no network, never binds :8777).
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import anchor_gui  # noqa: E402
import distro  # noqa: E402

STARTER = REPO_ROOT / "starter"
STARTER_DOMAINS = STARTER / "domains"

# The 6 top-level starter markdown files + the 4 domain files, each tagged with
# the kind of entry its real parser extracts.
TASK_FILES = [
    STARTER / "DASHBOARD.md",
    STARTER_DOMAINS / "academic.md",
    STARTER_DOMAINS / "commercial.md",
    STARTER_DOMAINS / "family.md",
    STARTER_DOMAINS / "writing.md",
]
PROJECT_FILES = [STARTER / "PROJECTS.md"]
INBOX_FILES = [STARTER / "INBOX.md"]
ARCHIVE_FILES = [STARTER / "SAVED_FOR_LATER.md", STARTER / "CANCELLED.md"]
# WEEKLY_REVIEW.md has no dedicated parser in gather_all(); it must merely exist
# and carry no PII (covered by the scan + existence checks).
EXTRA_FILES = [STARTER / "WEEKLY_REVIEW.md"]

ALL_STARTER_FILES = TASK_FILES + PROJECT_FILES + INBOX_FILES + ARCHIVE_FILES + EXTRA_FILES


def test_all_starter_files_exist():
    """Given the Wave-5 spec, all 6 top-level + 4 domain templates are present."""
    for f in ALL_STARTER_FILES:
        assert f.is_file(), f"missing starter template: {f.relative_to(REPO_ROOT)}"


@pytest.mark.parametrize("md", TASK_FILES, ids=lambda p: p.name)
def test_task_files_parse_to_zero_tasks(md):
    """Given a starter task file, When parse_tasks_from_md, Then ZERO tasks."""
    tasks = anchor_gui.parse_tasks_from_md(md)
    assert tasks == [], f"{md.name} should parse to zero tasks, got {tasks!r}"
    assert len(tasks) == 0


@pytest.mark.parametrize("md", PROJECT_FILES, ids=lambda p: p.name)
def test_project_file_parses_to_zero_projects(md):
    """Given the starter PROJECTS.md, When parse_projects_from_md, Then ZERO."""
    projects = anchor_gui.parse_projects_from_md(md)
    assert projects == [], f"{md.name} should parse to zero projects, got {projects!r}"
    assert len(projects) == 0


@pytest.mark.parametrize("md", INBOX_FILES, ids=lambda p: p.name)
def test_inbox_file_parses_to_zero_items(md):
    """Given the starter INBOX.md, When parse_inbox_from_md, Then ZERO items."""
    items = anchor_gui.parse_inbox_from_md(md)
    assert items == [], f"{md.name} should parse to zero inbox items, got {items!r}"
    assert len(items) == 0


@pytest.mark.parametrize("md", ARCHIVE_FILES, ids=lambda p: p.name)
def test_archive_files_parse_to_zero_items(md):
    """Given a starter archive file, When parse_archived_tasks, Then ZERO."""
    items = anchor_gui.parse_archived_tasks(md)
    assert items == [], f"{md.name} should parse to zero archived items, got {items!r}"
    assert len(items) == 0


def test_starter_tree_is_pii_clean():
    """Given the starter/ tree, When the no-PII scan runs, Then it is CLEAN."""
    files = []
    for p in sorted(STARTER.rglob("*")):
        if p.is_file():
            files.append((p.relative_to(STARTER).as_posix(), p))
    assert files, "expected starter files to scan"
    hits = distro.scan_paths(files, root=REPO_ROOT)
    assert hits == [], f"starter templates must be PII-clean, got hits: {hits!r}"
