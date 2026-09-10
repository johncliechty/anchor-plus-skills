"""Synthetic, portable canaries for instructional notebook work products."""

import hashlib
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

import notebook_artifacts as artifacts


def source(tmp_path, name="lesson.py", text="print('hello')\n"):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name,kernel,language", [("lesson.py", "python3", "python"), ("lesson.R", "ir", "R")])
def test_verbatim_single_cell_without_execution(tmp_path, name, kernel, language):
    text = "# illustrative only\r\nmessage = 'café'\r\n\r\n"
    source(tmp_path, name, text)
    companion = artifacts.materialize(tmp_path, name)
    notebook = read_json(tmp_path / companion["notebook"])
    assert len(notebook["cells"]) == 1
    cell = notebook["cells"][0]
    assert cell["cell_type"] == "code"
    assert cell["source"] == text
    assert cell["execution_count"] is None and cell["outputs"] == []
    assert notebook["metadata"]["kernelspec"]["name"] == kernel
    assert notebook["metadata"]["language_info"]["name"] == language
    assert companion["source_sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert companion["notebook_sha256"] == hashlib.sha256((tmp_path / companion["notebook"]).read_bytes()).hexdigest()
    assert artifacts.resolve_artifact(tmp_path, name)["status"] == "current"


def test_companion_is_relative_and_contains_no_runtime_identity(tmp_path):
    source(tmp_path, "examples/lesson.py")
    companion = artifacts.materialize(tmp_path, "examples/lesson.py")
    assert companion["source"] == "examples/lesson.py"
    assert companion["notebook"] == "examples/lesson.ipynb"
    assert set(companion) == {"schema", "version", "source", "source_sha256", "notebook", "converter_version", "notebook_sha256"}
    assert str(tmp_path) not in json.dumps(companion)
    assert read_json(tmp_path / "examples/lesson.py.anchor-notebook.json") == companion


def test_unchanged_repeat_does_not_touch_files(tmp_path):
    source(tmp_path)
    first = artifacts.materialize(tmp_path, "lesson.py")
    notebook, companion = tmp_path / "lesson.ipynb", tmp_path / "lesson.py.anchor-notebook.json"
    before = (notebook.stat().st_mtime_ns, companion.stat().st_mtime_ns)
    assert artifacts.materialize(tmp_path, "lesson.py") == first
    assert (notebook.stat().st_mtime_ns, companion.stat().st_mtime_ns) == before
    assert not (tmp_path / "lesson.py.anchor-notebook.lock").exists()
    assert not (tmp_path / "lesson.py.anchor-notebook.pending.json").exists()


def test_unconverted_and_unmatched_sibling_are_distinct(tmp_path):
    source(tmp_path)
    assert artifacts.resolve_artifact(tmp_path, "lesson.py")["status"] == "unconverted"
    sibling = tmp_path / "lesson.ipynb"
    sibling.write_text("user notebook", encoding="utf-8")
    assert artifacts.resolve_artifact(tmp_path, "lesson.py")["reason"] == "unmatched_notebook_sibling"
    with pytest.raises(artifacts.NotebookConflict, match="unmatched"):
        artifacts.materialize(tmp_path, "lesson.py")
    created = artifacts.materialize(tmp_path, "lesson.py", regenerate=True)
    assert created["notebook"] == "lesson.rev-1.ipynb"
    assert sibling.read_text(encoding="utf-8") == "user notebook"


def test_source_change_requires_new_revision_preserving_history(tmp_path):
    path = source(tmp_path)
    artifacts.materialize(tmp_path, "lesson.py")
    old_bytes = (tmp_path / "lesson.ipynb").read_bytes()
    path.write_text("print('second version')\n", encoding="utf-8")
    assert artifacts.resolve_artifact(tmp_path, "lesson.py")["status"] == "source_changed"
    with pytest.raises(artifacts.NotebookConflict, match="regeneration"):
        artifacts.materialize(tmp_path, "lesson.py")
    (tmp_path / "lesson.rev-1.ipynb").write_text("unrelated revision", encoding="utf-8")
    companion = artifacts.materialize(tmp_path, "lesson.py", regenerate=True)
    assert companion["notebook"] == "lesson.rev-2.ipynb"
    assert (tmp_path / "lesson.ipynb").read_bytes() == old_bytes
    assert (tmp_path / "lesson.rev-1.ipynb").read_text(encoding="utf-8") == "unrelated revision"
    assert artifacts.resolve_artifact(tmp_path, "lesson.py")["status"] == "current"


def test_notebook_edits_are_preserved_and_reported(tmp_path):
    source(tmp_path)
    artifacts.materialize(tmp_path, "lesson.py")
    path = tmp_path / "lesson.ipynb"
    edited = read_json(path)
    edited["cells"][0]["source"] += "# my explanation\n"
    path.write_text(json.dumps(edited), encoding="utf-8")
    edited_bytes = path.read_bytes()
    status = artifacts.resolve_artifact(tmp_path, "lesson.py")
    assert status["status"] == "notebook_edited" and status["notebook"] == "lesson.ipynb"
    with pytest.raises(artifacts.NotebookConflict):
        artifacts.materialize(tmp_path, "lesson.py")
    assert artifacts.materialize(tmp_path, "lesson.py", regenerate=True)["notebook"] == "lesson.rev-1.ipynb"
    assert path.read_bytes() == edited_bytes


def test_explicit_regeneration_creates_revision_even_when_unchanged(tmp_path):
    source(tmp_path)
    artifacts.materialize(tmp_path, "lesson.py")
    assert artifacts.materialize(tmp_path, "lesson.py", regenerate=True)["notebook"] == "lesson.rev-1.ipynb"
    assert artifacts.materialize(tmp_path, "lesson.py", regenerate=True)["notebook"] == "lesson.rev-2.ipynb"


def test_large_edited_notebook_does_not_block_preserving_regeneration(tmp_path):
    source(tmp_path)
    artifacts.materialize(tmp_path, "lesson.py")
    notebook = tmp_path / "lesson.ipynb"
    notebook.write_bytes(b"x" * (artifacts.MAX_NOTEBOOK_BYTES + 1))
    assert artifacts.resolve_artifact(tmp_path, "lesson.py")["status"] == "notebook_edited"
    assert artifacts.materialize(tmp_path, "lesson.py", regenerate=True)["notebook"] == "lesson.rev-1.ipynb"
    assert notebook.stat().st_size == artifacts.MAX_NOTEBOOK_BYTES + 1


@pytest.mark.parametrize("relative", ["../outside.py", "/outside.py", "C:/outside.py", "C:outside.py", "a/../lesson.py", "a\\lesson.py", "//server/share.py", "a//lesson.py", "./lesson.py", "lesson.py:secret", "CON.py", "folder./lesson.py"])
def test_unsafe_paths_are_rejected(tmp_path, relative):
    with pytest.raises(artifacts.UnsafeArtifactPath):
        artifacts.materialize(tmp_path, relative)


def test_source_limits_and_utf8_are_explicit(tmp_path):
    source(tmp_path, text="x" * artifacts.MAX_SOURCE_BYTES)
    artifacts.materialize(tmp_path, "lesson.py")
    source(tmp_path, "large.py", "x" * (artifacts.MAX_SOURCE_BYTES + 1))
    with pytest.raises(artifacts.InvalidNotebookSource, match="1 MiB"):
        artifacts.materialize(tmp_path, "large.py")
    (tmp_path / "nonutf.py").write_bytes(b"\xff\xfe")
    with pytest.raises(artifacts.InvalidNotebookSource, match="UTF-8"):
        artifacts.materialize(tmp_path, "nonutf.py")
    source(tmp_path, "lesson.txt")
    with pytest.raises(artifacts.InvalidNotebookSource, match=".py or .R"):
        artifacts.materialize(tmp_path, "lesson.txt")


def test_symlink_escape_is_rejected(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    source(outside)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    try:
        (workspace / "link").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Host does not permit creating symlinks for this synthetic canary")
    with pytest.raises(artifacts.UnsafeArtifactPath, match="Symlinks and junctions"):
        artifacts.materialize(workspace, "link/lesson.py")
    assert not (outside / "lesson.ipynb").exists()


def test_windows_reparse_attribute_is_rejected_without_platform_dependency(tmp_path, monkeypatch):
    source(tmp_path)
    original = Path.lstat

    class ReparseStat:
        st_mode = 0o100644
        st_file_attributes = 0x400

    def fake_lstat(path, *args, **kwargs):
        if path == tmp_path / "lesson.py":
            return ReparseStat()
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", fake_lstat)
    with pytest.raises(artifacts.UnsafeArtifactPath, match="junctions"):
        artifacts.materialize(tmp_path, "lesson.py")


def test_existing_lock_is_not_removed_or_taken_over(tmp_path):
    source(tmp_path)
    lock = tmp_path / "lesson.py.anchor-notebook.lock"
    lock.write_text("another owner", encoding="utf-8")
    with pytest.raises(artifacts.NotebookBusy, match="no stale-lock takeover"):
        artifacts.materialize(tmp_path, "lesson.py")
    assert lock.read_text(encoding="utf-8") == "another owner"
    assert artifacts.resolve_artifact(tmp_path, "lesson.py")["reason"] == "conversion_lock_exists"


def test_release_does_not_remove_replaced_lock(tmp_path):
    lock_name = "lesson.py.anchor-notebook.lock"
    with artifacts._SourceLock(tmp_path, lock_name):
        lock = tmp_path / lock_name
        # Changing the owner content is sufficient even when the inode is same.
        lock.write_text("replacement owner", encoding="utf-8")
    assert (tmp_path / lock_name).read_text(encoding="utf-8") == "replacement owner"


def test_concurrent_materialization_fails_busy_without_overwriting(tmp_path, monkeypatch):
    source(tmp_path)
    entered, finish = threading.Event(), threading.Event()
    original = artifacts._read

    def slow_pending_read(root, relative, limit, **kwargs):
        if relative.endswith(".pending.json"):
            entered.set()
            assert finish.wait(timeout=5)
        return original(root, relative, limit, **kwargs)

    monkeypatch.setattr(artifacts, "_read", slow_pending_read)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(artifacts.materialize, tmp_path, "lesson.py")
        assert entered.wait(timeout=5)
        try:
            with pytest.raises(artifacts.NotebookBusy):
                artifacts.materialize(tmp_path, "lesson.py")
        finally:
            finish.set()
        assert first.result(timeout=5)["notebook"] == "lesson.ipynb"


def test_sidecar_failure_preserves_notebook_and_retry_recovers(tmp_path, monkeypatch):
    source(tmp_path)
    original = artifacts._publish_companion

    def fail_publish(*args, **kwargs):
        raise OSError("synthetic sidecar publication failure")

    monkeypatch.setattr(artifacts, "_publish_companion", fail_publish)
    with pytest.raises(OSError, match="synthetic"):
        artifacts.materialize(tmp_path, "lesson.py")
    notebook = tmp_path / "lesson.ipynb"
    original_bytes = notebook.read_bytes()
    assert not (tmp_path / "lesson.py.anchor-notebook.json").exists()
    assert not (tmp_path / "lesson.py.anchor-notebook.lock").exists()
    assert artifacts.resolve_artifact(tmp_path, "lesson.py")["reason"] == "pending_conversion_requires_recovery"
    monkeypatch.setattr(artifacts, "_publish_companion", original)
    assert artifacts.materialize(tmp_path, "lesson.py")["notebook"] == "lesson.ipynb"
    assert notebook.read_bytes() == original_bytes
    assert artifacts.resolve_artifact(tmp_path, "lesson.py")["status"] == "current"


def test_pending_recovery_preserves_notebook_edited_after_failure(tmp_path, monkeypatch):
    source(tmp_path)
    original = artifacts._publish_companion
    monkeypatch.setattr(artifacts, "_publish_companion", lambda *a, **kw: (_ for _ in ()).throw(OSError("synthetic")))
    with pytest.raises(OSError):
        artifacts.materialize(tmp_path, "lesson.py")
    notebook = tmp_path / "lesson.ipynb"
    notebook.write_text("edited after failure", encoding="utf-8")
    monkeypatch.setattr(artifacts, "_publish_companion", original)
    with pytest.raises(artifacts.NotebookConflict, match="edited or incompletely written"):
        artifacts.materialize(tmp_path, "lesson.py", regenerate=True)
    assert notebook.read_text(encoding="utf-8") == "edited after failure"


def test_source_change_during_conversion_is_not_published(tmp_path, monkeypatch):
    path = source(tmp_path)
    original = artifacts._new_file

    def change_after_notebook(root, relative, blob):
        original(root, relative, blob)
        if relative.endswith(".ipynb"):
            path.write_text("print('changed mid-conversion')\n", encoding="utf-8")

    monkeypatch.setattr(artifacts, "_new_file", change_after_notebook)
    with pytest.raises(artifacts.NotebookConflict, match="Source changed"):
        artifacts.materialize(tmp_path, "lesson.py")
    assert (tmp_path / "lesson.ipynb").exists()
    assert not (tmp_path / "lesson.py.anchor-notebook.json").exists()
    with pytest.raises(artifacts.NotebookConflict, match="pending conversion"):
        artifacts.materialize(tmp_path, "lesson.py")


def test_invalid_companion_never_overwritten_even_on_regeneration(tmp_path):
    source(tmp_path)
    sidecar = tmp_path / "lesson.py.anchor-notebook.json"
    sidecar.write_text("{broken", encoding="utf-8")
    with pytest.raises(artifacts.NotebookConflict, match="invalid"):
        artifacts.materialize(tmp_path, "lesson.py", regenerate=True)
    assert sidecar.read_text(encoding="utf-8") == "{broken"
    assert artifacts.resolve_artifact(tmp_path, "lesson.py")["status"] == "conflict"


def test_companion_escape_does_not_establish_pairing(tmp_path):
    source(tmp_path)
    companion = artifacts.materialize(tmp_path, "lesson.py")
    companion["notebook"] = "../outside.ipynb"
    (tmp_path / "lesson.py.anchor-notebook.json").write_text(json.dumps(companion), encoding="utf-8")
    with pytest.raises(artifacts.UnsafeArtifactPath):
        artifacts.resolve_artifact(tmp_path, "lesson.py")


def test_companion_race_during_publication_does_not_replace_external_edit(tmp_path, monkeypatch):
    source(tmp_path)
    original = artifacts._new_file
    sidecar = tmp_path / "lesson.py.anchor-notebook.json"

    def external_edit(root, relative, blob):
        original(root, relative, blob)
        if relative.endswith(".tmp"):
            sidecar.write_text("external companion edit", encoding="utf-8")

    monkeypatch.setattr(artifacts, "_new_file", external_edit)
    with pytest.raises(artifacts.NotebookConflict, match="companion changed"):
        artifacts.materialize(tmp_path, "lesson.py")
    assert sidecar.read_text(encoding="utf-8") == "external companion edit"
    assert (tmp_path / "lesson.ipynb").exists()
    assert not list(tmp_path.glob("*.tmp"))


def test_source_change_while_preparing_companion_does_not_publish(tmp_path, monkeypatch):
    path = source(tmp_path)
    original = artifacts._new_file

    def source_edit(root, relative, blob):
        original(root, relative, blob)
        if relative.endswith(".tmp"):
            path.write_text("# changed while preparing companion\n", encoding="utf-8")

    monkeypatch.setattr(artifacts, "_new_file", source_edit)
    with pytest.raises(artifacts.NotebookConflict, match="Source changed"):
        artifacts.materialize(tmp_path, "lesson.py")
    assert not (tmp_path / "lesson.py.anchor-notebook.json").exists()
    assert (tmp_path / "lesson.ipynb").exists()


def test_deleted_published_notebook_is_not_silently_recreated(tmp_path):
    source(tmp_path)
    artifacts.materialize(tmp_path, "lesson.py")
    (tmp_path / "lesson.ipynb").unlink()
    assert artifacts.resolve_artifact(tmp_path, "lesson.py")["reason"] == "notebook_missing"
    with pytest.raises(artifacts.NotebookConflict, match="missing"):
        artifacts.materialize(tmp_path, "lesson.py")
    assert artifacts.materialize(tmp_path, "lesson.py", regenerate=True)["notebook"] == "lesson.rev-1.ipynb"
