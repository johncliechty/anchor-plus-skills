"""Read-only notebook completion/deletion gate and explicit MAIN persistence.

DELIVERABLES.md is the sole register. Private notebook-products receipts only
detect unfinished or lost registrations; they never create an additional list of
deliverables. There is no recursive artifact discovery and no conversion here.

Call ``persist_to_main`` before finishing a producing step. Immediately before
worktree deletion, call ``verify_main_copy`` and retain the worktree unless ok is
true. Verification never writes, copies, registers, launches, or changes ACLs.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

import notebook_persistence as _persistence
from notebook_products import (
    _SEPARATOR as _PRODUCT_SEPARATOR,
    _split_row as _product_split_row,
    _table_candidates as _product_table_candidates,
)


MAX_REGISTER_BYTES = 2 * 1024 * 1024
MAX_RECEIPT_BYTES = 256 * 1024
MAX_RECEIPT_TOTAL_BYTES = 8 * 1024 * 1024
MAX_RECEIPT_ENTRIES = 512
_RECEIPT_NAME = re.compile(r"^[0-9a-f]{64}\.json$")


class NotebookCompletionError(ValueError):
    """A conservative completion failure, safe for status and recovery records."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str):
    raise NotebookCompletionError(code, message)


def _read_limited(path: Path, limit: int, code: str) -> bytes:
    try:
        if path.stat().st_size > limit:
            _fail(code, "Notebook completion metadata exceeds the supported size.")
        with path.open("rb") as handle:
            data = handle.read(limit + 1)
        if len(data) > limit:
            _fail(code, "Notebook completion metadata exceeds the supported size.")
        return data
    except OSError:
        _fail(code, "Notebook completion metadata could not be read.")


def _register_rows(root: Path) -> list[dict[str, str]] | None:
    """Read the writer's sole canonical table, preserving its Markdown semantics.

    The shared parser owns fence handling, escaped/inline-code pipes, and table
    candidacy. Header validation follows the writer: What/Where/Date first,
    optional Step fourth, and any supported extra columns retained by the writer.
    """
    path = _persistence._path(root, "DELIVERABLES.md", existing=False)
    if not path.exists():
        return None
    if not path.is_file():
        _fail("malformed_deliverables", "DELIVERABLES.md must be a regular file.")
    try:
        lines = _read_limited(path, MAX_REGISTER_BYTES, "malformed_deliverables").decode("utf-8-sig").splitlines()
    except UnicodeError:
        _fail("malformed_deliverables", "DELIVERABLES.md must be UTF-8 Markdown.")
    candidates = _product_table_candidates(lines)
    if len(candidates) > 1:
        _fail("ambiguous_deliverables", "More than one product register table was found.")
    if not candidates:
        # Prose and fenced examples are not another product register. Receipts
        # proving a notebook requirement are checked against this empty set by
        # registered_items, and therefore still prevent unsafe completion.
        return []
    header_index, header = candidates[0]
    labels = [cell.casefold() for cell in header]
    if labels[:3] != ["what", "where", "date"]:
        _fail("malformed_deliverables", "The product table must begin with What, Where, and Date columns.")
    if "step" in labels and (len(labels) < 4 or labels[3] != "step" or labels.count("step") != 1):
        _fail("malformed_deliverables", "The optional Step column must occur exactly once in fourth position.")
    has_step = len(labels) >= 4 and labels[3] == "step"
    if header_index + 1 >= len(lines):
        _fail("malformed_deliverables", "The product table is missing its Markdown separator.")
    separator = _product_split_row(lines[header_index + 1])
    if separator is None or len(separator) != len(header) or not all(_PRODUCT_SEPARATOR.fullmatch(cell) for cell in separator):
        _fail("malformed_deliverables", "The product table has an invalid Markdown separator.")
    rows = []
    for line in lines[header_index + 2:]:
        cells = _product_split_row(line)
        if cells is None or not line.strip():
            break
        if len(cells) != len(header):
            _fail("malformed_deliverables", "A product table row has the wrong number of columns.")
        row = {"what": cells[0], "where": cells[1], "date": cells[2], "step": cells[3] if has_step else ""}
        if not row["what"] or not row["where"]:
            _fail("malformed_deliverables", "Product rows require both What and Where.")
        rows.append(row)
    return rows


def _source_reference(where: str) -> str | None:
    """Only the canonical backticked source form declares an instructional row."""
    match = re.fullmatch(r"`([^`]+)`", where.strip())
    if not match:
        return None
    candidate = match.group(1)
    if Path(candidate).suffix.lower() not in {".py", ".r"}:
        return None
    return _persistence._relative(candidate)


def _receipt_rows(root: Path) -> list[dict[str, object]]:
    directory = root / ".anchor" / "notebook-products"
    _persistence._check_components(directory, existing=False)
    if not directory.exists():
        return []
    if not directory.is_dir():
        _fail("invalid_notebook_receipts", "Notebook registration state must be a directory.")
    records, total, count = [], 0, 0
    try:
        for entry in directory.iterdir():
            count += 1
            if count > MAX_RECEIPT_ENTRIES:
                _fail("notebook_receipts_limit", "Too many notebook receipt entries to verify safely in one completion.")
            _persistence._check_components(entry)
            if entry.name == "register.lock":
                _fail("notebook_registration_busy", "Notebook registration is active or interrupted; retain the worktree.")
            if entry.suffix.lower() != ".json":
                continue
            if not _RECEIPT_NAME.fullmatch(entry.name) or not entry.is_file():
                _fail("invalid_notebook_receipts", "An unexpected notebook registration receipt needs investigation.")
            data = _read_limited(entry, MAX_RECEIPT_BYTES, "invalid_notebook_receipts")
            total += len(data)
            if total > MAX_RECEIPT_TOTAL_BYTES:
                _fail("notebook_receipts_limit", "Notebook receipt metadata exceeds the completion verification limit.")
            try:
                record = json.loads(data)
            except (ValueError, UnicodeError):
                _fail("invalid_notebook_receipts", "A notebook registration receipt is corrupt.")
            if (not isinstance(record, dict) or record.get("schema") != "anchor.notebook-product-completion"
                    or type(record.get("version")) is not int or record["version"] != 1):
                _fail("invalid_notebook_receipts", "A notebook registration receipt has an unsupported schema.")
            if record.get("stage") != "registered":
                _fail("notebook_registration_pending", "An instructional notebook has not finished product registration.")
            source = _persistence._relative(record.get("source"))
            notebook = _persistence._relative(record.get("notebook"))
            if Path(source).suffix.lower() not in {".py", ".r"} or Path(notebook).suffix.lower() != ".ipynb":
                _fail("invalid_notebook_receipts", "A notebook receipt contains an invalid source/notebook association.")
            if entry.name != hashlib.sha256(source.encode("utf-8")).hexdigest() + ".json":
                _fail("invalid_notebook_receipts", "A notebook receipt filename does not match its source.")
            registration = record.get("registration")
            if (not isinstance(registration, dict) or not isinstance(registration.get("what"), str)
                    or not isinstance(registration.get("where"), str)
                    or not isinstance(registration.get("date"), str)
                    or not isinstance(registration.get("step", ""), (str, int))
                    or isinstance(registration.get("step", ""), bool)):
                _fail("invalid_notebook_receipts", "A notebook receipt has invalid product registration metadata.")
            declared = registration["where"].strip()
            if declared.startswith("`") and declared.endswith("`"):
                declared = declared[1:-1]
            if _persistence._relative(declared) != source:
                _fail("invalid_notebook_receipts", "A notebook receipt's registration path disagrees with its source.")
            records.append({"source": source, "notebook": notebook, "registration": registration})
    except OSError:
        _fail("invalid_notebook_receipts", "Notebook registration state could not be inspected safely.")
    return records


def registered_items(worktree_root: str | Path) -> list[dict[str, str]]:
    """Return validated explicit notebook-backed source rows; raise on ambiguity.

    Ordinary script rows without a companion are ignored. A missing register is
    safe only when no notebook registration receipt/lock establishes a pending
    requirement. Known receipts must be represented in the sole register.
    """
    root = _persistence._root(worktree_root)
    receipts = _receipt_rows(root)
    rows = _register_rows(root)
    if rows is None:
        if receipts:
            _fail("missing_deliverables", "Notebook receipts exist but DELIVERABLES.md is missing.")
        return []
    selected, by_source, seen = [], {}, set()
    for row in rows:
        source = _source_reference(row["where"])
        if source is None:
            continue
        key = source.casefold()  # Conservative across Windows/collaborator filesystems.
        if key in seen:
            _fail("ambiguous_deliverables", "An instructional source occurs more than once in the product register.")
        seen.add(key)
        for suffix in (".anchor-notebook.pending.json", ".anchor-notebook.lock"):
            pending = _persistence._path(root, source + suffix, existing=False)
            if pending.exists():
                _fail("notebook_materialization_pending", "A declared source has pending notebook materialization; retain the worktree.")
        companion = _persistence._path(root, source + ".anchor-notebook.json", existing=False)
        if not companion.exists():
            continue
        if not companion.is_file():
            _fail("invalid_notebook_companion", "The registered notebook companion must be a regular file.")
        item = {"where": source, "what": row["what"], "step": row["step"]}
        selected.append(item)
        by_source[source] = item
    # Shared validation includes source hash, valid notebook bytes, association,
    # direct companion schema, and pending/lock conflicts via resolve_artifact.
    products, _ = _persistence._collect(root, selected, _persistence._resolver)
    product_map = {product["source"]: product for product in products}
    for receipt in receipts:
        source = receipt["source"]
        row = by_source.get(source)
        if row is None:
            _fail("unregistered_notebook_receipt", "A registered notebook receipt is no longer represented in DELIVERABLES.md.")
        # Receipt labels are historical recovery metadata, not a second product
        # register. User edits to What/Step belong to DELIVERABLES.md. Only the
        # materialized source/notebook association remains a safety constraint.
        if product_map[source]["notebook"] != receipt["notebook"]:
            _fail("notebook_registration_mismatch", "The notebook receipt disagrees with the materialized notebook association.")
    return selected


def _failure(exc: Exception, *, persisted: bool = False) -> dict[str, object]:
    result = {"ok": False, "reason": getattr(exc, "code", "notebook_completion_unverified"),
              "notebooks_required": True}
    if persisted:
        result.update({"persisted": [], "products": 0, "completion_receipt": None})
    return result


def persist_to_main(main: str | Path | None, wt: str | Path) -> dict[str, object]:
    """Persist only proven notebook-backed rows; false must prevent completion/reap."""
    try:
        items = registered_items(wt)
        if not items:
            return {"ok": True, "reason": "no_registered_notebooks", "notebooks_required": False,
                    "persisted": [], "products": 0, "completion_receipt": None}
        if main is None or not str(main).strip():
            _fail("main_required", "The MAIN project must be known before notebook worktree completion.")
        result = _persistence.persist_registered_products(main, wt, items)
        return {**result, "notebooks_required": True}
    except Exception as exc:
        return _failure(exc, persisted=True)


def verify_main_copy(main: str | Path | None, wt: str | Path) -> dict[str, object]:
    """Read-only exact-copy/register gate; does not repair or create anything."""
    try:
        items = registered_items(wt)
        if not items:
            return {"ok": True, "reason": "no_registered_notebooks", "notebooks_required": False}
        if main is None or not str(main).strip():
            _fail("main_required", "The MAIN project must be known before notebook worktree deletion.")
        main_root, worktree_root = _persistence._root(main), _persistence._root(wt)
        main_items = registered_items(main_root)
        main_rows = {item["where"]: item for item in main_items}
        for item in items:
            if main_rows.get(item["where"]) != item:
                _fail("main_registration_missing_or_different", "MAIN does not contain the matching instructional product register row.")
        _, files = _persistence._collect(worktree_root, items, _persistence._resolver)
        _persistence._verify_snapshot(main_root, files, "main_notebook_copy_different")
        # Detect a change in WT while comparing MAIN; a caller must keep WT on
        # any concurrent edit instead of relying on the earlier snapshot.
        _persistence._verify_snapshot(worktree_root, files, "worktree_changed_during_verification")
        return {"ok": True, "reason": "main_notebooks_verified", "notebooks_required": True}
    except Exception as exc:
        return _failure(exc)
