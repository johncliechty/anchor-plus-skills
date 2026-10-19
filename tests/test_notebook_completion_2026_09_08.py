"""Synthetic read-only worktree deletion gates; never launch notebook kernels."""
import hashlib
import json
from pathlib import Path

import pytest

import notebook_completion as completion
import notebook_persistence as persistence


SOURCE = "lessons/example.py"
NOTEBOOK = "lessons/example.ipynb"


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _register(root, *, what="Class illustration", where=SOURCE, step="2", date="2026-01-01"):
    (root / "DELIVERABLES.md").write_text(
        "# Deliverables\n\n| What | Where | Date | Step |\n| --- | --- | --- | --- |\n"
        f"| {what} | `{where}` | {date} | {step} |\n", encoding="utf-8")


def _product(root, *, edited=False):
    (root / "lessons").mkdir(exist_ok=True)
    source_bytes = b"print('class illustration')\n"
    (root / SOURCE).write_bytes(source_bytes)
    notebook = {"nbformat": 4, "nbformat_minor": 5, "metadata": {}, "cells": [
        {"cell_type": "code", "source": [source_bytes.decode("utf-8")], "metadata": {},
         "outputs": [], "execution_count": None}]}
    initial_bytes = json.dumps(notebook).encode("utf-8")
    if edited:
        notebook["cells"].append({"cell_type": "markdown", "source": ["Retain this collaborator edit"], "metadata": {}})
    (root / NOTEBOOK).write_bytes(json.dumps(notebook).encode("utf-8"))
    companion = {"schema": "anchor.notebook-companion", "version": 1, "source": SOURCE,
                 "source_sha256": _hash(source_bytes), "notebook": NOTEBOOK,
                 "notebook_sha256": _hash(initial_bytes), "converter_version": "1"}
    (root / (SOURCE + ".anchor-notebook.json")).write_text(json.dumps(companion), encoding="utf-8")
    _register(root)


def _receipt(root, *, stage="registered", source=SOURCE, notebook=NOTEBOOK):
    directory = root / ".anchor" / "notebook-products"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (hashlib.sha256(source.encode("utf-8")).hexdigest() + ".json")
    document = {"schema": "anchor.notebook-product-completion", "version": 1, "stage": stage,
                "source": source, "notebook": notebook,
                "registration": {"what": "Class illustration", "where": source,
                                 "date": "2026-01-01", "step": "2"}}
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


@pytest.fixture
def projects(tmp_path, monkeypatch):
    main, wt = tmp_path / "main", tmp_path / "worktree"
    main.mkdir()
    wt.mkdir()

    def resolver(root, source):
        companion = json.loads((root / (source + ".anchor-notebook.json")).read_text(encoding="utf-8"))
        actual = _hash((root / companion["notebook"]).read_bytes())
        status = "current" if actual == companion["notebook_sha256"] else "notebook_edited"
        return {"status": status, "source": source, "notebook": companion["notebook"]}

    monkeypatch.setattr(persistence, "_resolver", resolver)
    return main, wt


def test_missing_register_and_no_receipts_has_no_notebook_requirement(projects, monkeypatch):
    _, wt = projects
    monkeypatch.setattr(persistence, "persist_registered_products", lambda *_: pytest.fail("unexpected persistence"))
    assert completion.registered_items(wt) == []
    assert completion.persist_to_main(None, wt)["notebooks_required"] is False
    assert completion.verify_main_copy(None, wt) == {
        "ok": True, "reason": "no_registered_notebooks", "notebooks_required": False}
    assert list(wt.iterdir()) == []


def test_ordinary_unconverted_scripts_do_not_require_main(projects, monkeypatch):
    _, wt = projects
    _register(wt)
    (wt / "lessons").mkdir()
    (wt / SOURCE).write_text("print('ordinary script')", encoding="utf-8")
    monkeypatch.setattr(persistence, "persist_registered_products", lambda *_: pytest.fail("unexpected persistence"))
    assert completion.registered_items(wt) == []
    assert completion.persist_to_main(None, wt)["ok"] is True
    assert completion.verify_main_copy(None, wt)["notebooks_required"] is False
    assert not (wt / ".anchor").exists()


def test_registered_source_with_edited_notebook_is_required(projects):
    _, wt = projects
    _product(wt, edited=True)
    _receipt(wt)
    assert completion.registered_items(wt) == [{"where": SOURCE, "what": "Class illustration", "step": "2"}]
    result = completion.verify_main_copy(None, wt)
    assert result == {"ok": False, "reason": "main_required", "notebooks_required": True}


def test_registered_import_without_private_receipts_is_supported(projects):
    _, wt = projects
    _product(wt)
    assert len(completion.registered_items(wt)) == 1
    assert not (wt / ".anchor").exists()


@pytest.mark.parametrize("stage", ["pending", "materialized", "copied", "failed"])
def test_pending_runtime_receipt_blocks_even_an_ordinary_source_row(projects, stage):
    _, wt = projects
    _register(wt)
    _receipt(wt, stage=stage)
    result = completion.verify_main_copy(None, wt)
    assert result["ok"] is False
    assert result["reason"] == "notebook_registration_pending"
    assert result["notebooks_required"] is True


def test_register_lock_blocks_without_receipt_or_register(projects):
    _, wt = projects
    directory = wt / ".anchor" / "notebook-products"
    directory.mkdir(parents=True)
    lock = directory / "register.lock"
    lock.write_bytes(b"owned by another operation")
    result = completion.verify_main_copy(None, wt)
    assert result["reason"] == "notebook_registration_busy"
    assert lock.read_bytes() == b"owned by another operation"


@pytest.mark.parametrize("suffix", [".anchor-notebook.pending.json", ".anchor-notebook.lock"])
def test_known_source_pending_materialization_blocks_before_companion_exists(projects, suffix):
    _, wt = projects
    _register(wt)
    (wt / "lessons").mkdir()
    marker = wt / (SOURCE + suffix)
    marker.write_text("pending", encoding="utf-8")
    assert completion.verify_main_copy(None, wt)["reason"] == "notebook_materialization_pending"
    assert marker.read_text(encoding="utf-8") == "pending"


def test_registered_receipt_without_register_blocks(projects):
    _, wt = projects
    _receipt(wt)
    result = completion.verify_main_copy(None, wt)
    assert result["ok"] is False
    assert result["reason"] == "missing_deliverables"


def test_registered_receipt_not_represented_in_sole_register_blocks(projects):
    _, wt = projects
    _product(wt)
    _receipt(wt)
    _register(wt, where="notes/readme.md")
    assert completion.verify_main_copy(None, wt)["reason"] == "unregistered_notebook_receipt"


def test_current_register_title_and_step_override_historical_receipt_labels(projects):
    main, wt = projects
    _product(wt, edited=True)
    _product(main, edited=True)
    wt_receipt = _receipt(wt)
    main_receipt = _receipt(main)
    before_wt = wt_receipt.read_bytes()
    before_main = main_receipt.read_bytes()
    _register(wt, what="Updated classroom title", step="3 — revised plan")
    _register(main, what="Updated classroom title", step="3 — revised plan")
    assert completion.registered_items(wt) == [{"where": SOURCE, "what": "Updated classroom title", "step": "3 — revised plan"}]
    assert completion.verify_main_copy(main, wt)["ok"] is True
    assert wt_receipt.read_bytes() == before_wt
    assert main_receipt.read_bytes() == before_main


def test_receipt_notebook_association_still_must_match_materialized_product(projects):
    _, wt = projects
    _product(wt)
    path = _receipt(wt)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["notebook"] = "lessons/unrelated.ipynb"
    path.write_text(json.dumps(document), encoding="utf-8")
    assert completion.verify_main_copy(None, wt)["reason"] == "notebook_registration_mismatch"


@pytest.mark.parametrize("contents", ["{broken", "[]", '{"schema":"unexpected","version":1}'])
def test_corrupt_receipt_blocks_without_repair(projects, contents):
    _, wt = projects
    path = _receipt(wt)
    path.write_text(contents, encoding="utf-8")
    result = completion.verify_main_copy(None, wt)
    assert result["ok"] is False
    assert result["reason"] == "invalid_notebook_receipts"
    assert path.read_text(encoding="utf-8") == contents


@pytest.mark.parametrize("contents,reason", [
    ("| What | Where | Date |\n| malformed separator |\n", "malformed_deliverables"),
    ("| What | Where | Notes |\n| --- | --- | --- |\n", "malformed_deliverables"),
    ("| What | Where | Date | Notes | Step |\n| --- | --- | --- | --- | --- |\n", "malformed_deliverables"),
    ("| What | Where | Date |\n| --- | --- | --- |\n\n| What | Where | Date |\n| --- | --- | --- |\n", "ambiguous_deliverables"),
])
def test_malformed_or_ambiguous_register_refuses_completion(projects, contents, reason):
    _, wt = projects
    (wt / "DELIVERABLES.md").write_text(contents, encoding="utf-8")
    assert completion.verify_main_copy(None, wt)["reason"] == reason


def test_duplicate_source_rows_are_ambiguous(projects):
    _, wt = projects
    _product(wt)
    path = wt / "DELIVERABLES.md"
    original = path.read_text(encoding="utf-8")
    path.write_text(original + "| Another label | `lessons/example.py` | 2026-01-01 | 3 |\n", encoding="utf-8")
    assert completion.verify_main_copy(None, wt)["reason"] == "ambiguous_deliverables"


def test_source_changed_refuses_persistence_and_verification(projects, monkeypatch):
    main, wt = projects
    _product(wt)
    (wt / SOURCE).write_bytes(b"changed source after conversion")
    monkeypatch.setattr(persistence, "persist_registered_products", lambda *_: pytest.fail("source change must block copy"))
    assert completion.persist_to_main(main, wt)["reason"] == "source_changed"
    assert completion.verify_main_copy(main, wt)["reason"] == "source_changed"


def test_main_missing_triplet_or_register_row_blocks(projects):
    main, wt = projects
    _product(wt)
    result = completion.verify_main_copy(main, wt)
    assert result["ok"] is False
    assert result["reason"] == "main_registration_missing_or_different"


def test_main_different_notebook_preserves_both_sides(projects):
    main, wt = projects
    _product(wt)
    _product(main, edited=True)
    before = (main / NOTEBOOK).read_bytes()
    result = completion.verify_main_copy(main, wt)
    assert result["ok"] is False
    assert result["reason"] == "main_notebook_copy_different"
    assert (main / NOTEBOOK).read_bytes() == before


def test_main_removed_or_changed_register_row_blocks(projects):
    main, wt = projects
    _product(wt)
    _product(main)
    _register(main, what="Changed purpose", step="2")
    assert completion.verify_main_copy(main, wt)["reason"] == "main_registration_missing_or_different"
    _register(main, where="notes.md")
    assert completion.verify_main_copy(main, wt)["reason"] == "main_registration_missing_or_different"


def test_correct_main_copy_passes_even_registration_date_differs(projects):
    main, wt = projects
    _product(wt, edited=True)
    _product(main, edited=True)
    _register(main, date="2026-01-02")
    assert completion.verify_main_copy(main, wt) == {
        "ok": True, "reason": "main_notebooks_verified", "notebooks_required": True}


def test_verify_is_strictly_read_only(projects, monkeypatch):
    main, wt = projects
    _product(wt, edited=True)
    _product(main, edited=True)
    _receipt(wt)
    _receipt(main)
    original_open = Path.open

    def readonly_open(path, mode="r", *args, **kwargs):
        assert not any(flag in mode for flag in "wax+"), "verification attempted a filesystem write"
        return original_open(path, mode, *args, **kwargs)

    def forbidden(*args, **kwargs):
        pytest.fail("verification attempted mutation or persistence")

    monkeypatch.setattr(Path, "open", readonly_open)
    monkeypatch.setattr(Path, "mkdir", forbidden)
    monkeypatch.setattr(persistence, "persist_registered_products", forbidden)
    monkeypatch.setattr(persistence, "_copy_exclusive", forbidden)
    monkeypatch.setattr(persistence, "_write_receipt", forbidden)
    monkeypatch.setattr(persistence, "_register", forbidden)
    assert completion.verify_main_copy(main, wt)["ok"] is True


def test_persist_forwards_only_validated_rows_and_preserves_helper_result(projects, monkeypatch):
    main, wt = projects
    _product(wt)
    seen = []

    def persist(main_arg, wt_arg, items):
        seen.append((main_arg, wt_arg, items))
        return {"ok": False, "persisted": [SOURCE], "products": 1, "reason": "registration_failed",
                "completion_receipt": ".anchor/notebook-completions/synthetic.json"}

    monkeypatch.setattr(persistence, "persist_registered_products", persist)
    outcome = completion.persist_to_main(main, wt)
    assert seen == [(main, wt, [{"where": SOURCE, "what": "Class illustration", "step": "2"}])]
    assert outcome["notebooks_required"] is True
    assert outcome["ok"] is False
    assert outcome["persisted"] == [SOURCE]
    assert outcome["reason"] == "registration_failed"


def test_optional_step_column_and_escaped_description_pipe(projects):
    _, wt = projects
    _product(wt)
    (wt / "DELIVERABLES.md").write_text(
        "| What | Where | Date |\n| --- | --- | --- |\n"
        "| Python \\| illustration | `lessons/example.py` | 2026-01-01 |\n", encoding="utf-8")
    canonical_title = completion._product_split_row(
        "| Python \\| illustration | `lessons/example.py` | 2026-01-01 |")[0]
    assert completion.registered_items(wt) == [{"where": SOURCE, "what": canonical_title, "step": ""}]


def test_ordinary_extra_columns_are_not_a_notebook_requirement(projects):
    _, wt = projects
    (wt / "DELIVERABLES.md").write_text(
        "| What | Where | Date | Step | Notes |\n| --- | --- | --- | --- | --- |\n"
        "| Ordinary script | `scripts/plain.py` | 2026-01-01 | 2 | Not converted |\n"
        "| Readme | `README.md` | 2026-01-01 | 2 | Ordinary document |\n", encoding="utf-8")
    assert completion.registered_items(wt) == []
    assert completion.verify_main_copy(None, wt)["notebooks_required"] is False
    assert not (wt / ".anchor").exists()


@pytest.mark.parametrize("step_column", [False, True])
def test_notebook_register_supports_extra_columns_with_or_without_step(projects, step_column):
    main, wt = projects
    for root in (main, wt):
        _product(root, edited=True)
        _receipt(root)
        header = "| What | Where | Date | Step | Notes |" if step_column else "| What | Where | Date | Notes |"
        separator = "| --- | --- | --- | --- | --- |" if step_column else "| --- | --- | --- | --- |"
        row = (f"| Updated title | `{SOURCE}` | 2026-01-01 | Updated plan step | Annotation |"
               if step_column else f"| Updated title | `{SOURCE}` | 2026-01-01 | Annotation |")
        (root / "DELIVERABLES.md").write_text("\n".join([header, separator, row, ""]), encoding="utf-8")
    expected_step = "Updated plan step" if step_column else ""
    assert completion.registered_items(wt) == [{"where": SOURCE, "what": "Updated title", "step": expected_step}]
    assert completion.verify_main_copy(main, wt)["ok"] is True


@pytest.mark.parametrize("fence", ["```", "~~~"])
def test_fenced_example_tables_are_not_competing_registers(projects, fence):
    main, wt = projects
    for root in (main, wt):
        _product(root, edited=True)
        actual = (root / "DELIVERABLES.md").read_text(encoding="utf-8")
        example = (f"{fence}markdown\n| What | Where | Date |\n| --- | --- | --- |\n"
                   f"| Example only | `not-a-product.py` | Example |\n{fence}\n\n")
        (root / "DELIVERABLES.md").write_text("# Documentation\n\n" + example + actual + "\n" + example, encoding="utf-8")
    assert len(completion.registered_items(wt)) == 1
    assert completion.verify_main_copy(main, wt)["ok"] is True


def test_prose_and_fenced_examples_alone_do_not_declare_products(projects):
    _, wt = projects
    (wt / "DELIVERABLES.md").write_text(
        "# Deliverable examples\n\nNo actual products are declared in this document.\n\n"
        "```markdown\n| What | Where | Date |\n| --- | --- | --- |\n"
        "| Example | `example.py` | Example date |\n```\n", encoding="utf-8")
    assert completion.registered_items(wt) == []
    assert completion.verify_main_copy(None, wt)["notebooks_required"] is False
    _receipt(wt)
    assert completion.verify_main_copy(None, wt)["reason"] == "unregistered_notebook_receipt"


def test_inline_code_pipes_use_canonical_writer_parsing(projects):
    main, wt = projects
    title = "Illustration of `x|y` and `a || b`"
    for root in (main, wt):
        _product(root)
        _register(root, what=title)
        _receipt(root)
    assert completion.registered_items(wt) == [{"where": SOURCE, "what": title, "step": "2"}]
    assert completion.verify_main_copy(main, wt)["ok"] is True


def test_title_edits_do_not_relax_exact_notebook_copy_requirement(projects):
    main, wt = projects
    _product(wt)
    _product(main, edited=True)
    for root in (main, wt):
        _receipt(root)
        _register(root, what="Legitimately edited title", step="3")
    assert completion.verify_main_copy(main, wt)["reason"] == "main_notebook_copy_different"


def test_receipt_scan_is_bounded_and_does_not_recurse(projects, monkeypatch):
    _, wt = projects
    directory = wt / ".anchor" / "notebook-products"
    directory.mkdir(parents=True)
    (directory / "irrelevant-a").write_text("a", encoding="utf-8")
    (directory / "irrelevant-b").write_text("b", encoding="utf-8")
    monkeypatch.setattr(completion, "MAX_RECEIPT_ENTRIES", 1)
    assert completion.verify_main_copy(None, wt)["reason"] == "notebook_receipts_limit"


def test_receipt_reparse_path_is_not_followed(projects, tmp_path):
    _, wt = projects
    outside = tmp_path / "outside"
    outside.mkdir()
    (wt / ".anchor").mkdir()
    try:
        (wt / ".anchor" / "notebook-products").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks unavailable for this test account")
    result = completion.verify_main_copy(None, wt)
    assert result["ok"] is False
    assert result["reason"] == "reparse_path"
    assert not list(outside.iterdir())
