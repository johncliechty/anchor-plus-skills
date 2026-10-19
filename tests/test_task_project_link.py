"""Wave 9 — AC2: a task with ``Project: <id>`` appears under that project in the
project-tasks view; the link round-trips through parse → serialize (byte-stable
for the field) AND survives a healthcheck-style parse with NO loss/reformat of
the user's markdown. A task WITHOUT a Project field is unaffected.
"""
import importlib
from pathlib import Path

import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    # Reload the path-bound modules so their module-level constants point at the
    # tmp data dir (anchor / anchor_gui resolve paths at import).
    import paths
    importlib.reload(paths)
    import rnd_registry
    importlib.reload(rnd_registry)
    import anchor
    importlib.reload(anchor)
    import anchor_gui
    importlib.reload(anchor_gui)
    # Minimal data scaffold the GUI/CLI expect.
    (tmp_path / "domains").mkdir(exist_ok=True)
    return {"tmp": tmp_path, "paths": paths, "rnd": rnd_registry,
            "anchor": anchor, "gui": anchor_gui}


def _write_dashboard(tmp_path, lines):
    body = ("# Dashboard\n\n## Today's Priorities\n\n"
            + "\n".join(lines) + "\n")
    (tmp_path / "DASHBOARD.md").write_text(body, encoding="utf-8")


# ── parse → serialize round-trip (byte-stable for the Project field) ────────

def test_project_field_round_trips_parse_serialize(env):
    gui = env["gui"]
    tmp = env["tmp"]
    line = ("- [ ] Write the spec — Priority: 1 — energy: high — [academic] "
            "— Due: 2026-07-01 — Project: proj-abc123 — Notes: see email")
    _write_dashboard(tmp, [line])

    tasks = gui.parse_tasks_from_md(tmp / "DASHBOARD.md")
    assert len(tasks) == 1
    t = tasks[0]
    assert t["project"] == "proj-abc123"
    # Serialize back: the Project field survives unchanged.
    out = gui.serialize_task_line(t)
    # Round-trip the *field*: parse(serialize(parse(line)))['project'] stable.
    tmp2 = tmp / "rt.md"
    tmp2.write_text("## S\n\n" + out + "\n", encoding="utf-8")
    rt = gui.parse_tasks_from_md(tmp2)[0]
    assert rt["project"] == "proj-abc123"
    assert rt["text"] == t["text"]
    assert rt["priority"] == t["priority"]
    assert rt["notes"] == t["notes"]


def test_anchor_and_gui_parse_agree(env):
    """The CLI engine and the GUI parse the Project field identically (the
    healthcheck uses one of these parse paths)."""
    gui = env["gui"]
    anchor = env["anchor"]
    tmp = env["tmp"]
    line = "- [ ] Task X — Priority: 2 — energy: med — [writing] — Project: pid-9"
    f = tmp / "one.md"
    f.write_text("## S\n\n" + line + "\n", encoding="utf-8")
    assert gui.parse_tasks_from_md(f)[0]["project"] == "pid-9"
    assert anchor.parse_tasks_from_md(f)[0]["project"] == "pid-9"


# ── link op: byte-stability of untouched tasks + clean field set ────────────

def test_link_sets_field_and_keeps_others_byte_stable(env):
    anchor = env["anchor"]
    tmp = env["tmp"]
    linked = "- [ ] Linkable task — Priority: 1 — energy: high — [academic]"
    untouched = "- [ ] Other task — Priority: 2 — energy: med — [family]"
    _write_dashboard(tmp, [linked, untouched])
    before = (tmp / "DASHBOARD.md").read_text(encoding="utf-8")

    ok = anchor.link_task("Linkable task", "proj-xyz")
    assert ok is True
    after = (tmp / "DASHBOARD.md").read_text(encoding="utf-8")

    # The untouched task line is byte-identical (no reformat).
    assert untouched in after, "untouched task line was reformatted/lost"
    # The linked task gained exactly the Project field appended.
    assert (linked + " — Project: proj-xyz") in after
    # Only the one line changed.
    assert before.replace(linked, linked + " — Project: proj-xyz") == after


def test_link_replaces_existing_field_in_place(env):
    anchor = env["anchor"]
    tmp = env["tmp"]
    line = ("- [ ] Has a link — Priority: 2 — energy: med — [academic] "
            "— Project: old-id — Notes: keep me")
    _write_dashboard(tmp, [line])
    anchor.link_task("Has a link", "new-id")
    after = (tmp / "DASHBOARD.md").read_text(encoding="utf-8")
    assert "Project: new-id" in after
    assert "old-id" not in after
    # Notes (after the project field) preserved verbatim.
    assert "Notes: keep me" in after


def test_unlink_removes_field_cleanly(env):
    anchor = env["anchor"]
    tmp = env["tmp"]
    line = ("- [ ] Unlink me — Priority: 2 — energy: med — [academic] "
            "— Project: gone")
    _write_dashboard(tmp, [line])
    anchor.link_task("Unlink me", "")
    after = (tmp / "DASHBOARD.md").read_text(encoding="utf-8")
    assert "Project:" not in after
    assert "Unlink me — Priority: 2 — energy: med — [academic]" in after


# ── project-tasks view: linked task appears under its project (AC2) ─────────

def test_linked_task_appears_in_project_view(env):
    gui = env["gui"]
    rnd = env["rnd"]
    anchor = env["anchor"]
    tmp = env["tmp"]

    folder = tmp / "code"
    folder.mkdir()
    entry = rnd.add_project("My Project", str(folder))
    pid = entry["id"]

    _write_dashboard(tmp, [
        "- [ ] Build the widget — Priority: 1 — energy: high — [academic]",
        "- [ ] Unrelated chore — Priority: 2 — energy: low — [family]",
    ])
    anchor.link_task("Build the widget", pid)

    # The filter behind the view returns exactly the linked task.
    matched = gui.project_tasks(pid)
    assert len(matched) == 1
    assert matched[0]["text"] == "Build the widget"
    assert matched[0]["project"] == pid

    # The rendered project window lists it under the project.
    page = gui.render_project_window_html(pid)
    assert "Build the widget" in page
    assert "Unrelated chore" not in page


def test_task_without_project_unaffected(env):
    gui = env["gui"]
    rnd = env["rnd"]
    tmp = env["tmp"]
    folder = tmp / "c2"
    folder.mkdir()
    pid = rnd.add_project("P2", str(folder))["id"]
    _write_dashboard(tmp, [
        "- [ ] Plain task — Priority: 2 — energy: med — [academic]",
    ])
    # No task is linked → the project view shows none, and the plain task still
    # parses with an empty project field (unaffected).
    assert gui.project_tasks(pid) == []
    t = gui.parse_tasks_from_md(tmp / "DASHBOARD.md")[0]
    assert t["project"] == ""


# ── healthcheck-style parse survives the linked field (no loss/reformat) ────

def test_healthcheck_parse_preserves_project_field(env):
    """The healthcheck exercises ``parse_tasks_from_md`` over the markdown. A
    linked task must parse cleanly (valid priority, nonempty text) and keep its
    Project field — i.e. the field does not corrupt the healthcheck parse path.
    """
    anchor = env["anchor"]
    tmp = env["tmp"]
    domains = tmp / "domains"
    f = domains / "academic.md"
    f.write_text(
        "# Academic\n\n## Active Tasks\n\n"
        "- [ ] Linked research task — Priority: 1 — energy: high — [academic]\n",
        encoding="utf-8",
    )
    anchor.link_task("Linked research task", "proj-hc")

    # Re-parse exactly as the healthcheck does (mod.parse_tasks_from_md).
    items = anchor.parse_tasks_from_md(f)
    assert len(items) == 1
    t = items[0]
    assert t["project"] == "proj-hc"
    assert t["text"] == "Linked research task"      # text not corrupted
    assert t["priority"] in (1, 2, 3)               # healthcheck validity check
    assert t["text"], "empty task text would fail the healthcheck"
