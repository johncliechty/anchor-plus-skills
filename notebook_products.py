"""Register explicit instructional scripts as notebook work products.

DELIVERABLES.md remains the only deliverable registry.  The runtime receipt under
.anchor/notebook-products records recoverable completion stages; it is not a
second registry and must not be included in distributable skills or examples.

This module does not execute notebooks, install dependencies, complete plan
steps, or delete source/notebook artifacts.  Its lock coordinates callers of
this module, while an optimistic byte check protects observed external edits.
Uncooperative writers can still race the final filesystem replace; they should
participate in the same register lock when stronger coordination is needed.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Iterator

from notebook_artifacts import NotebookArtifactError, materialize


class NotebookProductError(NotebookArtifactError):
    """Registration could not safely complete; existing artifacts are retained."""


_REGISTER = "DELIVERABLES.md"
_RUNTIME = Path(".anchor") / "notebook-products"
_SEPARATOR = re.compile(r":?-{3,}:?\Z")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


def _cell(value: str, field: str, *, required: bool = False) -> str:
    if not isinstance(value, str):
        raise NotebookProductError(f"{field} must be text")
    if any(character in value for character in (
        "|", "`", "\x00", "\r", "\n", "\v", "\f", "\x1c", "\x1d", "\x1e",
        "\x85", "\u2028", "\u2029",
    )):
        raise NotebookProductError(f"{field} contains a Markdown cell delimiter")
    if required and not value.strip():
        raise NotebookProductError(f"{field} must not be empty")
    return value


def _root_directory(root: str | Path) -> Path:
    try:
        from notebook_persistence import _root
        directory = _root(root)
    except (OSError, RuntimeError) as exc:
        raise NotebookProductError("The workspace root is unavailable") from exc
    if not directory.is_dir():
        raise NotebookProductError("The workspace root must be a directory")
    return directory


def _runtime_directory(root: Path) -> Path:
    from notebook_persistence import _check_components, _private_directory
    current = root
    for component in _RUNTIME.parts:
        current = current / component
        _check_components(current, existing=False)
        created = False
        try:
            current.mkdir(mode=0o700)
            created = True
        except FileExistsError:
            pass
        except OSError as exc:
            raise NotebookProductError("Cannot create the notebook runtime directory") from exc
        if not current.is_dir() or not current.resolve().is_relative_to(root):
            raise NotebookProductError("Notebook runtime directory escapes the workspace")
        if component == _RUNTIME.parts[-1]:
            _private_directory(current, created=created)
    return current


@contextmanager
def _register_lock(runtime: Path) -> Iterator[None]:
    lock = runtime / "register.lock"
    try:
        descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise NotebookProductError(
            "Notebook registration is busy (or has an abandoned register.lock); "
            "no lock was taken over. Inspect its owner before manual recovery."
        ) from exc
    except OSError as exc:
        raise NotebookProductError("Cannot acquire the notebook register lock") from exc
    identity = os.fstat(descriptor)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump({"pid": os.getpid(), "started_at": _now()}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        yield
    finally:
        # Never remove a replacement lock belonging to another caller.
        try:
            present = lock.stat(follow_symlinks=False)
            if (present.st_dev, present.st_ino) == (identity.st_dev, identity.st_ino):
                lock.unlink()
        except FileNotFoundError:
            pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_optional(path: Path) -> bytes | None:
    if path.is_symlink():
        raise NotebookProductError(f"{path.name} must not be a symlink")
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise NotebookProductError(f"Cannot read {path.name}") from exc


def _atomic_write(path: Path, content: bytes, expected: bytes | None) -> None:
    """Replace only if the bytes observed by this operation are still current."""
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.anchor-", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if _read_optional(path) != expected:
            raise NotebookProductError(
                f"{path.name} changed during registration; the external edit was preserved"
            )
        if content != expected:
            os.replace(temporary, path)
    finally:
        # This path was created by this invocation; no glob or stale-temp sweep.
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _write_pending(path: Path, record: dict) -> None:
    expected = _read_optional(path)
    content = (json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    _atomic_write(path, content, expected)


def _split_row(line: str) -> list[str] | None:
    """Split real cell boundaries, retaining escaped and inline-code pipes."""
    text = line.rstrip("\r\n").strip()
    pieces: list[str] = []
    start = 0
    cursor = 0
    code_width = 0
    had_boundary = False
    while cursor < len(text):
        character = text[cursor]
        if character == "\\":
            cursor += 2
            continue
        if character == "`":
            end = cursor + 1
            while end < len(text) and text[end] == "`":
                end += 1
            width = end - cursor
            if code_width == 0:
                code_width = width
            elif code_width == width:
                code_width = 0
            cursor = end
            continue
        if character == "|" and code_width == 0:
            pieces.append(text[start:cursor].strip())
            start = cursor + 1
            had_boundary = True
        cursor += 1
    if not had_boundary:
        return None
    pieces.append(text[start:].strip())
    if text.startswith("|"):
        pieces.pop(0)
    if text.endswith("|") and pieces and pieces[-1] == "":
        pieces.pop()
    return pieces


def _row(cells: list[str], newline: str) -> str:
    return "| " + " | ".join(cells) + " |" + newline


def _table_candidates(lines: list[str]) -> list[tuple[int, list[str]]]:
    candidates: list[tuple[int, list[str]]] = []
    fence_character = ""
    fence_width = 0
    for index, line in enumerate(lines):
        fence = _FENCE.match(line.rstrip("\r\n"))
        if fence_character:
            if (fence and fence.group(1)[0] == fence_character
                    and len(fence.group(1)) >= fence_width
                    and not fence.group(2).strip()):
                fence_character = ""
            continue
        if fence:
            fence_character = fence.group(1)[0]
            fence_width = len(fence.group(1))
            continue
        cells = _split_row(line)
        if cells is None:
            continue
        labels = [cell.casefold() for cell in cells]
        if ((labels and labels[0] == "what")
                or len(set(labels).intersection({"what", "where", "date"})) >= 2):
            candidates.append((index, cells))
    return candidates


def _render_register(
    original: bytes | None, source: str, notebook: str, what: str, step: str, today: str
) -> tuple[bytes, bool]:
    try:
        text = (original or b"").decode("utf-8")
    except UnicodeDecodeError as exc:
        raise NotebookProductError("DELIVERABLES.md must be UTF-8") from exc
    # Preserve a BOM and the existing newline convention without introducing a
    # second heading/table when a file already has prose or other content.
    bom = "\ufeff" if text.startswith("\ufeff") else ""
    if bom:
        text = text[1:]
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    candidates = _table_candidates(lines)
    if len(candidates) > 1:
        raise NotebookProductError("DELIVERABLES.md has competing deliverable tables")
    new_cells = [what, f"`{source}`", today, step]
    if not candidates:
        if not text.strip():
            text = "# Deliverables" + newline + newline
        else:
            if not text.endswith(("\n", "\r")):
                text += newline
            if not text.endswith(newline + newline):
                text += newline
        text += _row(["What", "Where", "Date", "Step"], newline)
        text += _row(["---"] * 4, newline)
        text += _row(new_cells, newline)
        return (bom + text).encode("utf-8"), True

    header_index, header = candidates[0]
    labels = [cell.casefold() for cell in header]
    if labels[:3] != ["what", "where", "date"]:
        raise NotebookProductError("The deliverable header must start with What, Where, Date")
    if "step" in labels and (len(labels) < 4 or labels[3] != "step" or labels.count("step") != 1):
        raise NotebookProductError("The deliverable Step column must be fourth")
    needs_step = len(header) == 3 or labels[3] != "step"
    separator_index = header_index + 1
    separator = _split_row(lines[separator_index]) if separator_index < len(lines) else None
    if (separator is None or len(separator) != len(header)
            or not all(_SEPARATOR.fullmatch(cell) for cell in separator)):
        raise NotebookProductError("The deliverable table separator is missing or malformed")

    body: list[tuple[int, list[str]]] = []
    cursor = separator_index + 1
    while cursor < len(lines):
        cells = _split_row(lines[cursor])
        if cells is None or not lines[cursor].strip():
            break
        if len(cells) != len(header):
            raise NotebookProductError("A deliverable row has the wrong number of columns")
        body.append((cursor, cells))
        cursor += 1
    matching: list[tuple[int, list[str]]] = []
    for index, cells in body:
        location = re.search(r"`([^`]*)`", cells[1])
        if location and location.group(1) in {source, notebook}:
            matching.append((index, cells))
    if len(matching) > 1:
        raise NotebookProductError("Multiple existing deliverable rows match this notebook product")

    if needs_step:
        header.insert(3, "Step")
        separator.insert(3, "---")
        lines[header_index] = _row(header, newline)
        lines[separator_index] = _row(separator, newline)
        for index, cells in body:
            cells.insert(3, "")
            lines[index] = _row(cells, newline)
    if matching:
        index, cells = matching[0]
        cells[:4] = new_cells
        lines[index] = _row(cells, newline)
        created = False
    else:
        new_cells.extend([""] * (len(header) - 4))
        if cursor and not lines[cursor - 1].endswith(("\n", "\r")):
            lines[cursor - 1] += newline
        lines.insert(cursor, _row(new_cells, newline))
        created = True
    return (bom + "".join(lines)).encode("utf-8"), created


def register_instructional(
    root: str | Path,
    source: str,
    what: str,
    step: str = "",
    regenerate: bool = False,
) -> dict:
    """Materialize a Python/R notebook, then register one logical work product.

    A failure after conversion intentionally leaves the source, notebook and
    materialized-stage receipt for a later retry.  Existing matching rows are
    updated, not duplicated.  ``step`` is the plan's display number/name; this
    operation never changes the plan's completion state.
    """
    _cell(source, "source", required=True)
    _cell(what, "what", required=True)
    _cell(step, "step")
    directory = _root_directory(root)
    runtime = _runtime_directory(directory)
    with _register_lock(runtime):
        artifact = materialize(directory, source, regenerate=regenerate)
        canonical_source = _cell(artifact["source"], "source", required=True)
        notebook = _cell(artifact["notebook"], "notebook", required=True)
        digest = hashlib.sha256(canonical_source.encode("utf-8")).hexdigest()
        pending_path = runtime / f"{digest}.json"
        today = date.today().isoformat()
        record = {
            "schema": "anchor.notebook-product-completion",
            "version": 1,
            "stage": "materialized",
            "updated_at": _now(),
            "source": canonical_source,
            "notebook": notebook,
            "artifact": artifact,
            "registration": {"what": what, "where": canonical_source, "date": today, "step": step},
        }
        _write_pending(pending_path, record)
        try:
            register_path = directory / _REGISTER
            original = _read_optional(register_path)
            rendered, created = _render_register(
                original, canonical_source, notebook, what, step, today
            )
            _atomic_write(register_path, rendered, original)
        except (NotebookArtifactError, OSError) as exc:
            record["last_error"] = str(exc)
            record["updated_at"] = _now()
            try:
                _write_pending(pending_path, record)
            except (NotebookArtifactError, OSError):
                # The materialized receipt already exists.  Do not hide the
                # registration failure behind a secondary annotation failure.
                pass
            raise
        record["stage"] = "registered"
        record["updated_at"] = _now()
        record["register_sha256"] = hashlib.sha256(rendered).hexdigest()
        _write_pending(pending_path, record)
        return {
            "ok": True,
            "stage": "registered",
            "source": canonical_source,
            "notebook": notebook,
            "register": _REGISTER,
            "created_row": created,
            "pending_record": pending_path.relative_to(directory).as_posix(),
            "artifact": artifact,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="Workspace containing DELIVERABLES.md")
    parser.add_argument("--source", required=True, help="Portable workspace-relative .py or .R path")
    parser.add_argument("--what", required=True, help="Deliverable label")
    parser.add_argument("--step", default="", help="Producing plan step number/name")
    parser.add_argument("--regenerate", action="store_true", help="Request a new notebook revision")
    arguments = parser.parse_args(argv)
    try:
        result = register_instructional(
            arguments.root, arguments.source, arguments.what,
            arguments.step, arguments.regenerate,
        )
    except (NotebookArtifactError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
