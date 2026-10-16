"""Wave 2: idempotent migration of legacy markdown into ANCHOR_DATA_DIR.

Seeds a fake "legacy" source layout, migrates it into a tmp data dir, and
asserts:
- zero project/task loss (every source line is present in the destination),
- a no-op when source == dest (ANCHOR_DATA_DIR unset == code dir),
- running twice is stable (nothing duplicated/deleted; existing files kept).
"""
import importlib

import paths


def _seed_legacy(src):
    (src / "domains").mkdir(parents=True, exist_ok=True)
    (src / "logs").mkdir(parents=True, exist_ok=True)
    (src / "DASHBOARD.md").write_text(
        "# Dashboard\n- [ ] task-A — Priority: 1 — [academic]\n"
        "- [ ] task-B — Priority: 2 — [writing]\n",
        encoding="utf-8",
    )
    (src / "PROJECTS.md").write_text(
        "# Projects\n- Project Alpha — P1\n- Project Beta — P2\n", encoding="utf-8"
    )
    (src / "INBOX.md").write_text("# Inbox\n- idea one\n", encoding="utf-8")
    (src / "CANCELLED.md").write_text("# Cancelled\n", encoding="utf-8")
    (src / "SAVED_FOR_LATER.md").write_text("# Saved\n", encoding="utf-8")
    (src / "domains" / "academic.md").write_text(
        "# Academic\n- [ ] read paper — Priority: 1 — [academic]\n", encoding="utf-8"
    )
    (src / "logs" / "2026-06-01.md").write_text("# log\n- 09:00 — did a thing\n", encoding="utf-8")


def _all_files(root):
    return {
        p.relative_to(root).as_posix(): p.read_text(encoding="utf-8")
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_migration_zero_loss(tmp_path):
    importlib.reload(paths)
    src = tmp_path / "legacy"
    dst = tmp_path / "data"
    src.mkdir()
    _seed_legacy(src)

    report = paths.migrate_data(source=src, dest=dst)
    assert report["noop"] is False

    src_files = _all_files(src)
    dst_files = _all_files(dst)

    # Every source file made it across with identical content (zero loss).
    for rel, content in src_files.items():
        assert rel in dst_files, f"missing after migration: {rel}"
        assert dst_files[rel] == content, f"content drift: {rel}"

    # Spot-check the actual task/project payload survived.
    dash = (dst / "DASHBOARD.md").read_text(encoding="utf-8")
    assert "task-A" in dash and "task-B" in dash
    proj = (dst / "PROJECTS.md").read_text(encoding="utf-8")
    assert "Project Alpha" in proj and "Project Beta" in proj


def test_migration_is_idempotent(tmp_path):
    importlib.reload(paths)
    src = tmp_path / "legacy"
    dst = tmp_path / "data"
    src.mkdir()
    _seed_legacy(src)

    r1 = paths.migrate_data(source=src, dest=dst)
    snapshot1 = _all_files(dst)

    r2 = paths.migrate_data(source=src, dest=dst)
    snapshot2 = _all_files(dst)

    # Second run copies nothing new and changes nothing.
    assert snapshot1 == snapshot2
    assert r2["copied"] == []
    assert set(r2["skipped_existing"]) >= set(r1["copied"])


def test_migration_noop_when_source_equals_dest(tmp_path):
    importlib.reload(paths)
    same = tmp_path / "same"
    same.mkdir()
    _seed_legacy(same)
    report = paths.migrate_data(source=same, dest=same)
    assert report["noop"] is True
    assert report["copied"] == []


def test_migration_preserves_existing_dest_files(tmp_path):
    """Migration never overwrites a file already present in dest."""
    importlib.reload(paths)
    src = tmp_path / "legacy"
    dst = tmp_path / "data"
    src.mkdir()
    dst.mkdir()
    _seed_legacy(src)
    # Pre-existing, user-edited destination file.
    (dst / "DASHBOARD.md").write_text("# Dashboard\n- [ ] LOCAL EDIT keep me\n", encoding="utf-8")

    paths.migrate_data(source=src, dest=dst)

    # The local edit is preserved, not clobbered by the legacy copy.
    assert "LOCAL EDIT keep me" in (dst / "DASHBOARD.md").read_text(encoding="utf-8")
    # Other files still migrated.
    assert (dst / "PROJECTS.md").exists()
