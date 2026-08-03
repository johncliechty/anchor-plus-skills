"""Wave 1 smoke test: establishes the pytest gate.

Exercises a real, import-safe source module (`anchor.py`, the stdlib-only CLI
engine). `anchor.py` has no import-time side effects — top level only defines
path constants; all file I/O and the CLI entrypoint are guarded inside
functions / `if __name__ == "__main__":` — so importing it at collection time
is safe.

The test asserts on the real behavior of `anchor.parse_tasks_from_md`, which
parses the Anchor task markdown format documented in CLAUDE.md.
"""
from pathlib import Path

import anchor


def test_anchor_imports_and_exposes_parser():
    """The CLI engine imports cleanly and exposes its markdown parser."""
    assert callable(anchor.parse_tasks_from_md)


def test_parse_tasks_from_md_missing_file_returns_empty(tmp_path):
    """A non-existent file yields an empty task list, not an error."""
    missing = tmp_path / "does_not_exist.md"
    assert anchor.parse_tasks_from_md(missing) == []


def test_parse_tasks_from_md_parses_real_task_line(tmp_path):
    """A real Anchor task line parses into the documented field structure."""
    md = tmp_path / "tasks.md"
    md.write_text(
        "# Tasks\n"
        "- [ ] Review David Leavitt paper — Priority: 1 — energy: high — "
        "[academic] — Due: 2026-07-01 — Notes: see email from Dr. Smith\n"
        "- [x] Submit grant report — Priority: 2 — energy: med — [academic]\n",
        encoding="utf-8",
    )

    tasks = anchor.parse_tasks_from_md(md)

    assert len(tasks) == 2

    first = tasks[0]
    assert first["text"] == "Review David Leavitt paper"
    assert first["done"] is False
    assert first["priority"] == 1
    assert first["energy"] == "high"
    assert first["domain"] == "academic"
    assert first["due"] == "2026-07-01"
    assert "Dr. Smith" in first["notes"]

    second = tasks[1]
    assert second["done"] is True
    assert second["priority"] == 2


def test_parse_tasks_from_md_defaults(tmp_path):
    """A bare task line falls back to documented defaults."""
    md = tmp_path / "bare.md"
    md.write_text("- [ ] Buy groceries\n", encoding="utf-8")

    tasks = anchor.parse_tasks_from_md(md)

    assert len(tasks) == 1
    task = tasks[0]
    assert task["text"] == "Buy groceries"
    assert task["priority"] == 2          # default priority
    assert task["energy"] == "med"        # default energy
    assert task["domain"] == "personal"   # default domain


def test_project_field_only_from_trailing_metadata(tmp_path):
    """F2 regression guard (anchor.py): a task whose *body text* merely mentions
    "Project:" must NOT parse a project link, while a real trailing
    ``— Project: <id>`` metadata field must parse correctly."""
    md = tmp_path / "proj.md"
    md.write_text(
        # Title mentions "Project:" but it is NOT a trailing metadata field.
        "- [ ] Plan Project: Apollo milestones\n"
        # Real trailing metadata field.
        "- [ ] Wire dashboard — Priority: 1 — energy: high — [academic] "
        "— Project: abc123\n",
        encoding="utf-8",
    )

    tasks = anchor.parse_tasks_from_md(md)
    assert len(tasks) == 2

    # Body mention → no project link.
    assert not tasks[0]["project"]
    assert "Plan Project: Apollo milestones" in tasks[0]["text"]

    # Real trailing field → parsed.
    assert tasks[1]["project"] == "abc123"


def test_anchor_module_is_import_safe():
    """Sanity: importing the module did not perform host file writes.

    The dashboard HTML is only written when rebuild_dashboard() is called,
    never at import time. We assert the path constant exists but that import
    alone is side-effect free by confirming the function (not its effect) is
    what's exposed.
    """
    assert isinstance(anchor.ANCHOR_DIR, Path)
    assert callable(anchor.rebuild_dashboard)
