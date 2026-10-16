"""Synthetic, project-independent notebook registration contract tests."""

import hashlib
import json
from pathlib import Path

import pytest

import notebook_products as products


def _source(root: Path, relative: str = "examples/lesson.py") -> str:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("values = [1, 2, 3]\nprint(sum(values))\n", encoding="utf-8")
    return relative


def _pending(root: Path, source: str) -> Path:
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    return root / ".anchor" / "notebook-products" / f"{digest}.json"


def test_new_register_materializes_and_records_one_source_row(tmp_path):
    source = _source(tmp_path)
    result = products.register_instructional(tmp_path, source, "Illustrative Python", "2: Practice")
    register = (tmp_path / "DELIVERABLES.md").read_text(encoding="utf-8")
    assert "| What | Where | Date | Step |" in register
    assert register.count(f"`{source}`") == 1
    assert "2: Practice" in register
    assert (tmp_path / result["notebook"]).is_file()
    assert (tmp_path / source).is_file()
    assert result["created_row"] is True
    receipt = json.loads(_pending(tmp_path, source).read_text(encoding="utf-8"))
    assert receipt["stage"] == "registered"
    assert receipt["registration"]["where"] == source
    assert "completed" not in receipt
    assert not (tmp_path / ".anchor/notebook-products/register.lock").exists()


def test_repeat_is_idempotent_and_preserves_unrelated_content(tmp_path):
    source = _source(tmp_path)
    unrelated = "| Keep this exactly | `notes/readme.txt` | 2026-01-01 | 1 | Casey |\n"
    original = (
        "# Project work products\n\nIntro stays unchanged.\n\n"
        "| What | Where | Date | Step | Owner |\n"
        "| --- | --- | --- | --- | --- |\n"
        + unrelated + "\n## Notes\nDo not rewrite these notes.\n"
    )
    register = tmp_path / "DELIVERABLES.md"
    register.write_text(original, encoding="utf-8")
    products.register_instructional(tmp_path, source, "Demo", "Practice")
    first = register.read_bytes()
    second_result = products.register_instructional(tmp_path, source, "Demo", "Practice")
    assert register.read_bytes() == first
    assert second_result["created_row"] is False
    assert unrelated in register.read_text(encoding="utf-8")
    assert register.read_text(encoding="utf-8").endswith("## Notes\nDo not rewrite these notes.\n")


def test_r_source_is_registered_without_execution_or_rewriting(tmp_path):
    source = "examples/lesson.R"
    path = tmp_path / source
    path.parent.mkdir(parents=True)
    content = "values <- c(1, 2, 3)\nprint(sum(values))\n"
    path.write_text(content, encoding="utf-8")
    result = products.register_instructional(tmp_path, source, "Illustrative R", "Practice")
    notebook = json.loads((tmp_path / result["notebook"]).read_text(encoding="utf-8"))
    assert notebook["metadata"]["kernelspec"]["name"] == "ir"
    assert path.read_text(encoding="utf-8") == content
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            assert cell.get("execution_count") is None
            assert cell.get("outputs", []) == []


def test_existing_selected_notebook_row_becomes_source_row_and_keeps_extra_columns(tmp_path):
    source = _source(tmp_path)
    artifact = products.materialize(tmp_path, source)
    register = tmp_path / "DELIVERABLES.md"
    register.write_text(
        "| What | Where | Date | Step | Owner |\n"
        "| --- | --- | --- | --- | --- |\n"
        f"| Old label | `{artifact['notebook']}` | 2026-01-01 | 1 | Casey |\n",
        encoding="utf-8",
    )
    result = products.register_instructional(tmp_path, source, "New label", "3")
    text = register.read_text(encoding="utf-8")
    assert result["created_row"] is False
    assert "Old label" not in text
    assert f"| New label | `{source}` |" in text
    assert "| 3 | Casey |" in text
    assert text.count(f"`{source}`") == 1


def test_three_column_header_upgrades_without_losing_rows(tmp_path):
    source = _source(tmp_path)
    register = tmp_path / "DELIVERABLES.md"
    register.write_text(
        "# Deliverables\n\n| What | Where | Date |\n"
        "| :--- | ---: | :---: |\n"
        "| Existing | `old.txt` | 2026-01-01 |\n",
        encoding="utf-8",
    )
    products.register_instructional(tmp_path, source, "Lesson", "2")
    text = register.read_text(encoding="utf-8")
    assert "| What | Where | Date | Step |" in text
    assert "| :--- | ---: | :---: | --- |" in text
    assert "| Existing | `old.txt` | 2026-01-01 |  |" in text


def test_extra_columns_without_step_are_shifted_without_loss(tmp_path):
    source = _source(tmp_path)
    register = tmp_path / "DELIVERABLES.md"
    register.write_text(
        "| What | Where | Date | Owner |\n| --- | --- | --- | --- |\n"
        f"| Demo | `{source}` | 2026-01-01 | Casey |\n", encoding="utf-8"
    )
    products.register_instructional(tmp_path, source, "Lesson", "2")
    text = register.read_text(encoding="utf-8")
    assert "| What | Where | Date | Step | Owner |" in text
    assert "| 2 | Casey |" in text


@pytest.mark.parametrize("field,value", [
    ("source", "examples/bad`name.py"),
    ("source", "examples/bad|name.py"),
    ("what", "Label\n| Injected |"),
    ("what", "`other.py`"),
    ("step", "2 | complete"),
    ("step", "2\r3"),
    ("step", "2\u20283"),
])
def test_markdown_injection_is_rejected_before_materialization(tmp_path, monkeypatch, field, value):
    def unexpected(*args, **kwargs):
        pytest.fail("Injection must be rejected before materialization")
    monkeypatch.setattr(products, "materialize", unexpected)
    arguments = {"source": "examples/lesson.py", "what": "Lesson", "step": "2"}
    arguments[field] = value
    with pytest.raises(products.NotebookProductError, match="delimiter"):
        products.register_instructional(tmp_path, **arguments)
    assert not (tmp_path / "DELIVERABLES.md").exists()


@pytest.mark.parametrize("table", [
    "| What | Where | Date |\nmissing separator\n",
    "| What | Wher | Dat |\n| --- | --- | --- |\n",
    "| Where | What | Date |\n| --- | --- | --- |\n",
    "| What | Where | Date |\n| --- | --- | --- |\n| Too | Few |\n",
    "| What | Where | Date |\n| --- | --- | --- |\n\n"
    "| What | Where | Date |\n| --- | --- | --- |\n",
    "| What | Where | Date | Owner | Step |\n| --- | --- | --- | --- | --- |\n",
])
def test_malformed_register_is_unchanged_and_leaves_recoverable_pending(tmp_path, table):
    source = _source(tmp_path)
    register = tmp_path / "DELIVERABLES.md"
    register.write_text(table, encoding="utf-8")
    original = register.read_bytes()
    with pytest.raises(products.NotebookProductError):
        products.register_instructional(tmp_path, source, "Lesson")
    assert register.read_bytes() == original
    receipt = json.loads(_pending(tmp_path, source).read_text(encoding="utf-8"))
    assert receipt["stage"] == "materialized"
    assert "last_error" in receipt
    assert (tmp_path / receipt["notebook"]).is_file()
    assert (tmp_path / source).is_file()


def test_duplicate_matching_rows_are_not_silently_collapsed(tmp_path):
    source = _source(tmp_path)
    artifact = products.materialize(tmp_path, source)
    register = tmp_path / "DELIVERABLES.md"
    original = (
        "| What | Where | Date | Step |\n| --- | --- | --- | --- |\n"
        f"| Source | `{source}` | 2026-01-01 | 1 |\n"
        f"| Notebook | `{artifact['notebook']}` | 2026-01-01 | 1 |\n"
    )
    register.write_text(original, encoding="utf-8")
    with pytest.raises(products.NotebookProductError, match="Multiple"):
        products.register_instructional(tmp_path, source, "Lesson")
    assert register.read_text(encoding="utf-8") == original


def test_external_edit_before_replace_is_preserved(tmp_path, monkeypatch):
    source = _source(tmp_path)
    register = tmp_path / "DELIVERABLES.md"
    external = b"# External edit must survive\n"
    write = products._atomic_write
    def concurrent_write(path, content, expected):
        if path.name == "DELIVERABLES.md":
            path.write_bytes(external)
        return write(path, content, expected)
    monkeypatch.setattr(products, "_atomic_write", concurrent_write)
    with pytest.raises(products.NotebookProductError, match="changed during"):
        products.register_instructional(tmp_path, source, "Lesson")
    assert register.read_bytes() == external
    receipt = json.loads(_pending(tmp_path, source).read_text(encoding="utf-8"))
    assert receipt["stage"] == "materialized"
    assert (tmp_path / receipt["notebook"]).is_file()
    assert not list(tmp_path.glob(".DELIVERABLES.md.anchor-*.tmp"))


def test_busy_lock_has_no_stale_takeover_or_materialization(tmp_path, monkeypatch):
    source = _source(tmp_path)
    runtime = products._runtime_directory(tmp_path)
    lock = runtime / "register.lock"
    lock.write_text('{"pid": 999999999, "started_at": "old"}', encoding="utf-8")
    original = lock.read_bytes()
    def unexpected(*args, **kwargs):
        pytest.fail("A busy register must not materialize artifacts")
    monkeypatch.setattr(products, "materialize", unexpected)
    with pytest.raises(products.NotebookProductError, match="no lock was taken over"):
        products.register_instructional(tmp_path, source, "Lesson")
    assert lock.read_bytes() == original
    assert not (tmp_path / "DELIVERABLES.md").exists()


def test_registration_can_recover_when_final_receipt_write_failed(tmp_path, monkeypatch):
    source = _source(tmp_path)
    write = products._write_pending
    def incomplete_receipt(path, record):
        if record["stage"] == "registered":
            raise OSError("Synthetic final receipt failure")
        return write(path, record)
    monkeypatch.setattr(products, "_write_pending", incomplete_receipt)
    with pytest.raises(OSError, match="Synthetic"):
        products.register_instructional(tmp_path, source, "Lesson", "2")
    assert json.loads(_pending(tmp_path, source).read_text(encoding="utf-8"))["stage"] == "materialized"
    monkeypatch.setattr(products, "_write_pending", write)
    result = products.register_instructional(tmp_path, source, "Lesson", "2")
    assert result["created_row"] is False
    assert (tmp_path / "DELIVERABLES.md").read_text(encoding="utf-8").count(f"`{source}`") == 1
    assert json.loads(_pending(tmp_path, source).read_text(encoding="utf-8"))["stage"] == "registered"


def test_code_fence_example_is_not_a_competing_register(tmp_path):
    source = _source(tmp_path)
    example = "```markdown\n| What | Where | Date |\n| --- | --- | --- |\n```\n\n"
    register = tmp_path / "DELIVERABLES.md"
    register.write_text(example, encoding="utf-8")
    products.register_instructional(tmp_path, source, "Lesson")
    assert register.read_text(encoding="utf-8").startswith(example)


def test_bom_and_crlf_survive(tmp_path):
    source = _source(tmp_path)
    register = tmp_path / "DELIVERABLES.md"
    register.write_bytes(
        b"\xef\xbb\xbf# Deliverables\r\n\r\n| What | Where | Date | Step |\r\n"
        b"| --- | --- | --- | --- |\r\n"
    )
    products.register_instructional(tmp_path, source, "Lesson")
    result = register.read_bytes()
    assert result.startswith(b"\xef\xbb\xbf")
    assert b"\n" not in result.replace(b"\r\n", b"")


def test_cli_emits_generic_result_and_no_project_specific_paths(tmp_path, capsys):
    source = _source(tmp_path)
    assert products.main(["--root", str(tmp_path), "--source", source, "--what", "Lesson", "--step", "2"]) == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["source"] == source
    assert payload["stage"] == "registered"
    assert str(tmp_path) not in captured.out
    assert captured.err == ""


def test_cli_reports_failure_without_traceback(tmp_path, capsys):
    assert products.main(["--root", str(tmp_path), "--source", "absent.py", "--what", "Lesson"]) == 2
    captured = capsys.readouterr()
    assert json.loads(captured.err)["ok"] is False
    assert "Traceback" not in captured.err
