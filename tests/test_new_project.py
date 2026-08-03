"""Wave 3 — New Project flow + per-project store + Project field round-trip.

Covers: create-new-folder (folder + scaffold + fresh id); select-existing
(registers; missing path → path-missing, no crash); folder-with-existing
offers add-another (not blocked) with isolated store; two projects in one
folder render grouped + stores don't collide; task ``Project:`` field
round-trips unchanged.
"""
import importlib

import pytest


@pytest.fixture
def gui(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    import paths
    importlib.reload(paths)
    import rnd_registry
    importlib.reload(rnd_registry)
    import dir_browser
    importlib.reload(dir_browser)
    import anchor_gui
    importlib.reload(anchor_gui)
    return anchor_gui


def test_create_new_folder(gui, tmp_path):
    parent = tmp_path / "dev"
    parent.mkdir()
    res = gui.create_new_folder_project("MyProj", str(parent))
    assert res["folder_created"]
    folder = parent / "MyProj"
    assert folder.is_dir()
    entry = res["entry"]
    assert entry["id"]
    # Fresh id is in the registry.
    import rnd_registry
    assert rnd_registry.get_project(entry["id"]) is not None
    # Scaffold dirs exist.
    store = folder / ".anchor" / "projects" / entry["id"]
    for lane in ("research", "planning", "build", "deliverables", "jobs"):
        assert (store / lane).is_dir()


def test_create_new_folder_always_git_repo(gui, tmp_path):
    # v8 Wave 1: every project is bootstrapped — a starter CLAUDE.md always, and a
    # git repo when git is available — so Research/Plan never errors not-a-git-repo
    # (the legacy git_init flag no longer gates whether a repo exists).
    import shutil
    parent = tmp_path / "dev2"
    parent.mkdir()
    res = gui.create_new_folder_project("NoGit", str(parent), git_init=False)
    folder = parent / "NoGit"
    assert folder.is_dir()
    assert (folder / "CLAUDE.md").exists()
    if shutil.which("git"):
        assert (folder / ".git").exists()


def test_select_existing_registers(gui, tmp_path):
    folder = tmp_path / "existing"
    folder.mkdir()
    res = gui.select_existing_project("Existing", str(folder))
    assert res["path_exists"]
    assert res["entry"]["id"]
    store = folder / ".anchor" / "projects" / res["entry"]["id"]
    assert store.is_dir()


def test_select_existing_missing_path_no_crash(gui, tmp_path):
    missing = tmp_path / "does-not-exist"
    res = gui.select_existing_project("Ghost", str(missing))
    assert res["path_exists"] is False
    assert res["entry"]["state"] == "path-missing"
    # Listing surfaces path-missing, does not crash.
    import rnd_registry
    listed = {e["id"]: e for e in rnd_registry.list_projects()}
    assert listed[res["entry"]["id"]]["state"] == "path-missing"


def test_folder_with_existing_offers_add_another(gui, tmp_path):
    folder = tmp_path / "shared"
    folder.mkdir()
    first = gui.select_existing_project("First", str(folder))
    # Adding another in the same folder is NOT blocked.
    second = gui.select_existing_project("Second", str(folder))
    assert second["entry"]["id"] != first["entry"]["id"]
    # The flow reports the existing siblings.
    sibling_ids = {s["id"] for s in second["siblings_in_folder"]}
    assert first["entry"]["id"] in sibling_ids
    # Isolated stores.
    s1 = folder / ".anchor" / "projects" / first["entry"]["id"]
    s2 = folder / ".anchor" / "projects" / second["entry"]["id"]
    assert s1.is_dir() and s2.is_dir() and s1 != s2


def test_two_projects_one_folder_render_grouped(gui, tmp_path):
    folder = tmp_path / "grp"
    folder.mkdir()
    a = gui.select_existing_project("Alpha", str(folder))
    b = gui.select_existing_project("Beta", str(folder))
    html = gui.render_projects_view_html()
    assert "Alpha" in html
    assert "Beta" in html
    # v9 Wave 3: projects render as thin rows nested under collapsible group
    # FOLDERS (the v8 flat list is replaced). Both co-located ungrouped projects
    # render under the single "Ungrouped" folder; the on-disk folder PATH is NOT
    # printed (the Ungrouped catch-all suppresses its path block, and the path
    # otherwise lives on the project-window header).
    assert html.count(str(folder)) == 0
    assert html.count('data-project-id="') == 2
    # The Ungrouped collapsible folder header is present (one group, two rows).
    assert "rnd-folder-head" in html
    assert "Ungrouped" in html
    # Stores don't collide.
    import rnd_registry
    sa = rnd_registry.project_store_dir(str(folder), a["entry"]["id"])
    sb = rnd_registry.project_store_dir(str(folder), b["entry"]["id"])
    assert sa != sb


def test_status_line_none_yet(gui, tmp_path):
    folder = tmp_path / "s"
    folder.mkdir()
    e = gui.select_existing_project("S", str(folder))
    html = gui.render_status_line_html(e["entry"]["id"])
    for lane in ("Research", "Planning", "Build", "Deliverables"):
        assert lane in html
    # Wave 3 contract: empty lanes read "Lane: 0", NOT the old "none-yet" state.
    assert "none-yet" not in html
    assert "Research: 0" in html
    assert "Planning: 0" in html


def test_project_field_round_trips_unchanged(gui):
    # Parse a task line carrying a Project: <id> field, then serialize it back.
    line = ("- [ ] Wire up runner — Priority: 1 — energy: high — [academic] "
            "— Project: abc123def — Notes: see plan")
    md = "## Active Tasks\n" + line + "\n"
    from pathlib import Path
    import tempfile
    p = Path(tempfile.mkdtemp()) / "t.md"
    p.write_text(md, encoding="utf-8")
    tasks = gui.parse_tasks_from_md(p)
    assert len(tasks) == 1
    t = tasks[0]
    assert t["project"] == "abc123def"
    assert t["notes"] == "see plan"
    assert t["priority"] == 1
    assert t["text"] == "Wire up runner"
    # Serialize and re-parse — the project link survives unchanged.
    out = gui.serialize_task_line(t)
    assert "Project: abc123def" in out
    # Re-parse via a temp file to confirm full round-trip.
    p.write_text("## Active Tasks\n" + out + "\n", encoding="utf-8")
    t2 = gui.parse_tasks_from_md(p)[0]
    assert t2["project"] == "abc123def"
    assert t2["text"] == "Wire up runner"
    assert t2["notes"] == "see plan"


def test_anchor_cli_parser_preserves_project(monkeypatch, tmp_path):
    # The CLI parser (anchor.py) must also preserve the Project field.
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    import importlib
    import paths
    importlib.reload(paths)
    import anchor
    importlib.reload(anchor)
    from pathlib import Path
    p = Path(tmp_path) / "t.md"
    p.write_text(
        "## Active Tasks\n- [ ] Task X — Priority: 2 — [writing] "
        "— Project: pid-9\n", encoding="utf-8")
    tasks = anchor.parse_tasks_from_md(p)
    assert tasks[0]["project"] == "pid-9"
    assert tasks[0]["text"] == "Task X"
