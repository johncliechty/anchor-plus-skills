"""Recovery/ordering tests; no notebook code execution or repository teardown."""
import hashlib
import json

import pytest

import notebook_persistence as persistence


def digest(data):
    return hashlib.sha256(data).hexdigest()


def add_product(root, source="lessons/example.py", *, edited=False):
    path = root / source
    path.parent.mkdir(parents=True, exist_ok=True)
    content = b"print('synthetic lesson')\n" if source.endswith(".py") else b"print('synthetic R lesson')\n"
    path.write_bytes(content)
    notebook = source.rsplit(".", 1)[0] + ".ipynb"
    document = {"nbformat": 4, "nbformat_minor": 5, "metadata": {}, "cells": [
        {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
         "source": content.decode("utf-8").splitlines(keepends=True)}]}
    initial = (json.dumps(document, ensure_ascii=False) + "\n").encode("utf-8")
    if edited:
        document["cells"].append({"cell_type": "markdown", "metadata": {}, "source": ["Collaborator's retained note"]})
    actual = (json.dumps(document, ensure_ascii=False) + "\n").encode("utf-8")
    (root / notebook).write_bytes(actual)
    companion = {"schema": "anchor.notebook-companion", "version": 1, "source": source,
                 "source_sha256": digest(content), "notebook": notebook, "notebook_sha256": digest(initial),
                 "converter_version": "1"}
    (root / (source + ".anchor-notebook.json")).write_text(json.dumps(companion), encoding="utf-8")
    return {"what": "Synthetic classroom notebook", "where": source, "step": "2"}


@pytest.fixture
def setup(tmp_path):
    main, worktree = tmp_path / "main", tmp_path / "worktree"
    main.mkdir()
    worktree.mkdir()
    row = add_product(worktree)
    calls = []

    def resolver(root, source):
        return {"status": "current", "source": source, "notebook": source.rsplit(".", 1)[0] + ".ipynb"}

    def register(root, source, *, what, step):
        notebook = source.rsplit(".", 1)[0] + ".ipynb"
        for relative in (source, notebook, source + ".anchor-notebook.json"):
            assert (root / relative).is_file(), "register must follow persistence of all product bytes"
        calls.append((source, what, step))
        return {"ok": True, "stage": "registered", "source": source, "notebook": notebook}

    def receipts(root):
        directory = root / ".anchor" / "notebook-completions"
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        return directory

    return {"main": main, "worktree": worktree, "rows": [row], "calls": calls,
            "resolver": resolver, "register": register, "receipt_directory": receipts}


def run(setup, **overrides):
    kwargs = {key: setup[key] for key in ("resolver", "register", "receipt_directory")}
    kwargs.update(overrides)
    return persistence.persist_registered_products(setup["main"], setup["worktree"], setup["rows"], **kwargs)


def receipt(setup, outcome):
    return json.loads((setup["main"] / outcome["completion_receipt"]).read_text(encoding="utf-8"))


def test_exact_triplet_durable_before_register_and_completion_receipt(setup):
    outcome = run(setup)
    assert outcome["ok"] is True
    assert outcome["products"] == 1
    assert len(outcome["persisted"]) == 3
    assert len(setup["calls"]) == 1
    for relative in outcome["persisted"]:
        assert (setup["main"] / relative).read_bytes() == (setup["worktree"] / relative).read_bytes()
    record = receipt(setup, outcome)
    assert record["stage"] == "registered"
    assert record["registered"] == ["lessons/example.py"]
    assert str(setup["main"]) not in json.dumps(record)
    assert str(setup["worktree"]) not in json.dumps(record)
    assert not list((setup["main"] / "lessons").glob("*.stage"))


@pytest.mark.parametrize("label,step", [("Edited MAIN title", "2"), ("Synthetic classroom notebook", "9")])
def test_differing_main_register_metadata_is_not_overwritten(setup, label, step):
    target = setup["main"] / "DELIVERABLES.md"
    content = f"| What | Where | Date | Step |\n| --- | --- | --- | --- |\n| {label} | `lessons/example.py` | 2026-01-01 | {step} |\n"
    target.write_text(content, encoding="utf-8")
    outcome = run(setup)
    assert outcome["ok"] is False
    assert outcome["reason"] == "main_registration_conflict"
    assert outcome["persisted"] == []
    assert target.read_text(encoding="utf-8") == content
    assert setup["calls"] == []


def test_successful_retry_is_idempotent_but_revalidates_main(setup):
    first = run(setup)
    original = {p: (setup["main"] / p).read_bytes() for p in first["persisted"]}
    second = run(setup)
    assert first["completion_receipt"] == second["completion_receipt"]
    assert second["ok"] is True
    assert original == {p: (setup["main"] / p).read_bytes() for p in second["persisted"]}
    (setup["main"] / "lessons/example.ipynb").write_text("later local change", encoding="utf-8")
    third = run(setup)
    assert third["ok"] is False
    assert third["reason"] == "main_file_conflict"


def test_edited_notebook_is_preserved_exactly(setup):
    setup["rows"] = [add_product(setup["worktree"], edited=True)]
    initial = (setup["worktree"] / "lessons/example.ipynb").read_bytes()
    outcome = run(setup, resolver=lambda root, source: {"status": "notebook_edited", "source": source,
                                                      "notebook": "lessons/example.ipynb"})
    assert outcome["ok"] is True
    assert (setup["main"] / "lessons/example.ipynb").read_bytes() == initial
    companion = json.loads((setup["main"] / "lessons/example.py.anchor-notebook.json").read_text(encoding="utf-8"))
    assert companion["notebook_sha256"] != digest(initial)


def test_main_conflict_preserved_and_preflight_prevents_other_copies(setup):
    directory = setup["main"] / "lessons"
    directory.mkdir()
    notebook = directory / "example.ipynb"
    notebook.write_bytes(b"unrelated MAIN notebook")
    outcome = run(setup)
    assert outcome["ok"] is False
    assert outcome["reason"] == "main_file_conflict"
    assert notebook.read_bytes() == b"unrelated MAIN notebook"
    assert not (directory / "example.py").exists()
    assert not setup["calls"]
    assert receipt(setup, outcome)["stage"] == "pending"


def test_copy_failure_retains_pending_receipt_and_retry_recovers(setup):
    count = 0

    def interrupted(destination, content, *, staging):
        nonlocal count
        count += 1
        if count == 2:
            staging.write_bytes(content[:7])
            raise RuntimeError("synthetic interruption")
        persistence._copy_exclusive(destination, content, staging=staging)

    first = run(setup, copy_file=interrupted)
    assert first["ok"] is False
    assert len(first["persisted"]) == 1
    assert receipt(setup, first)["stage"] == "pending"
    assert not setup["calls"]
    second = run(setup)
    assert second["ok"] is True
    assert second["completion_receipt"] == first["completion_receipt"]
    assert receipt(setup, second)["stage"] == "registered"


def test_registration_failure_reports_durable_copies_then_retry(setup):
    first = run(setup, register=lambda *args, **kwargs: {"ok": False})
    assert first["ok"] is False
    assert first["reason"] == "registration_failed"
    assert len(first["persisted"]) == 3
    assert receipt(setup, first)["stage"] == "copied"
    second = run(setup)
    assert second["ok"] is True
    assert first["completion_receipt"] == second["completion_receipt"]


def test_partial_multi_product_registration_never_reports_complete(setup):
    setup["rows"].append(add_product(setup["worktree"], "lessons/another.R"))
    count = 0
    original = setup["register"]

    def interrupted(*args, **kwargs):
        nonlocal count
        count += 1
        if count == 2:
            raise RuntimeError("synthetic register failure")
        return original(*args, **kwargs)

    first = run(setup, register=interrupted)
    assert first["ok"] is False
    assert receipt(setup, first)["stage"] == "copied"
    assert len(receipt(setup, first)["registered"]) == 1
    assert run(setup)["ok"] is True


@pytest.mark.parametrize("status,code", [("source_changed", "source_changed"),
    ("conflict", "artifact_conflict"), ("missing", "explicit_registration_required")])
def test_unresolved_artifact_never_converts_or_registers(setup, status, code):
    outcome = run(setup, resolver=lambda *_: {"status": status})
    assert outcome["ok"] is False
    assert outcome["reason"] == code
    assert not list(setup["main"].iterdir())
    assert not setup["calls"]


def test_source_changed_after_resolution_is_detected_by_hash(setup):
    (setup["worktree"] / "lessons/example.py").write_bytes(b"changed source")
    outcome = run(setup)
    assert outcome["ok"] is False
    assert outcome["reason"] == "source_changed"
    assert not setup["calls"]


def test_worktree_edits_during_copy_block_completion_and_reap(setup):
    def changes_source(destination, content, *, staging):
        persistence._copy_exclusive(destination, content, staging=staging)
        (setup["worktree"] / "lessons/example.py").write_bytes(b"concurrent lesson edit")

    outcome = run(setup, copy_file=changes_source)
    assert outcome["ok"] is False
    assert outcome["reason"] == "worktree_changed_during_completion"
    assert not setup["calls"]


def test_main_equals_worktree_validates_and_registers_without_overwrite(setup):
    setup["main"] = setup["worktree"]
    original = (setup["main"] / "lessons/example.ipynb").read_bytes()
    outcome = run(setup)
    assert outcome["ok"] is True
    assert (setup["main"] / "lessons/example.ipynb").read_bytes() == original


@pytest.mark.parametrize("value", ["../escape.py", "C:\\private\\secret.py", "/private/secret.py",
                                   "lessons/../../secret.py", "`lessons/example.py`", "lessons/example.py|bad"])
def test_traversal_absolute_or_raw_markdown_paths_rejected(setup, value):
    setup["rows"][0]["where"] = value
    outcome = run(setup)
    assert outcome["ok"] is False
    assert outcome["reason"] == "invalid_product_path"
    assert not setup["calls"]


def test_only_explicit_rows_are_copied_not_private_project_files(setup):
    (setup["worktree"] / "private-settings.json").write_text('{"token":"private"}', encoding="utf-8")
    (setup["worktree"] / "unregistered.py").write_text("print('not a deliverable')", encoding="utf-8")
    assert run(setup)["ok"] is True
    assert not (setup["main"] / "private-settings.json").exists()
    assert not (setup["main"] / "unregistered.py").exists()


def test_companion_cannot_smuggle_host_specific_fields(setup):
    path = setup["worktree"] / "lessons/example.py.anchor-notebook.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["private_token"] = "not copied"
    path.write_text(json.dumps(document), encoding="utf-8")
    outcome = run(setup)
    assert outcome["ok"] is False
    assert outcome["reason"] == "artifact_conflict"
    assert not list(setup["main"].iterdir())


def test_invalid_notebook_snapshot_is_not_persisted(setup):
    (setup["worktree"] / "lessons/example.ipynb").write_bytes(b"partial JSON")
    outcome = run(setup)
    assert outcome["ok"] is False
    assert outcome["reason"] == "artifact_conflict"


def test_corrupted_existing_receipt_is_preserved(setup):
    first = run(setup)
    path = setup["main"] / first["completion_receipt"]
    path.write_bytes(b"corrupt receipt, retain for diagnosis")
    second = run(setup)
    assert second["ok"] is False
    assert second["reason"] == "receipt_conflict"
    assert path.read_bytes() == b"corrupt receipt, retain for diagnosis"


def test_symlink_destination_not_followed_or_deleted(setup, tmp_path):
    target = tmp_path / "outside"
    target.mkdir()
    try:
        (setup["main"] / "lessons").symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks unavailable for this test account")
    outcome = run(setup)
    assert outcome["ok"] is False
    assert outcome["reason"] == "reparse_path"
    assert not list(target.iterdir())


def test_no_registered_notebooks_is_noop_no_runtime_directory(setup):
    setup["rows"] = []
    result = run(setup)
    assert result == {"ok": True, "persisted": [], "products": 0, "reason": "no_registered_notebooks", "completion_receipt": None}
    assert not list(setup["main"].iterdir())
