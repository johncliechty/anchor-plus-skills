"""Portable, non-executing Python/R -> Jupyter work-product conversion.

Callers must explicitly identify an instructional source file. This module does
not scan a project, execute code, register deliverables, install dependencies, or
configure Jupyter. Relative paths and companions are safe to redistribute.

The workspace is trusted and single-user, not an OS sandbox. Cooperating writers
are serialized with an exclusive lock; unexpected files or edits fail closed.
Reparse points below the selected root are rejected, including Windows junctions.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat
from typing import Any
import uuid


MAX_SOURCE_BYTES = 1024 * 1024
MAX_NOTEBOOK_BYTES = 8 * MAX_SOURCE_BYTES
MAX_METADATA_BYTES = 64 * 1024
CONVERTER_VERSION = "1"
COMPANION_SCHEMA = "anchor.notebook-companion"
PENDING_SCHEMA = "anchor.notebook-pending"


class NotebookArtifactError(ValueError):
    """A conversion cannot safely proceed; no existing notebook is replaced."""


class UnsafeArtifactPath(NotebookArtifactError):
    """A path is not a contained, ordinary project-relative path."""


class InvalidNotebookSource(NotebookArtifactError):
    """The explicitly selected source is unavailable or not supported."""


class NotebookConflict(NotebookArtifactError):
    """Existing artifacts require recovery or an explicit new revision."""


class NotebookBusy(NotebookArtifactError):
    """A conversion lock exists. It is never automatically taken over."""


def _relative(value: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise UnsafeArtifactPath("Use a nonempty project-relative path.")
    # Require portable POSIX-style companions even on Windows. Reject ADS paths,
    # drive-relative paths, UNC paths, dot components, and Windows device names.
    if "\\" in value or ":" in value or PureWindowsPath(value).drive:
        raise UnsafeArtifactPath("Use a portable relative path with '/' separators.")
    parts = value.split("/")
    if PurePosixPath(value).is_absolute() or any(p in ("", ".", "..") for p in parts):
        raise UnsafeArtifactPath("Absolute paths and dot path components are forbidden.")
    for part in parts:
        if part.endswith((".", " ")) or re.fullmatch(
            r"(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part
        ):
            raise UnsafeArtifactPath("The path is not portable to Windows.")
        if any(ch in part for ch in '<>"|?*') or any(ord(ch) < 32 for ch in part):
            raise UnsafeArtifactPath("The path contains unsupported filename characters.")
    return value


def _root(value: str | os.PathLike[str]) -> Path:
    try:
        root = Path(value).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise UnsafeArtifactPath("The selected workspace root is unavailable.") from exc
    if not root.is_dir():
        raise UnsafeArtifactPath("The selected workspace root must be a directory.")
    return root


def _path(root: Path, relative: str) -> Path:
    relative = _relative(relative)
    candidate = root.joinpath(*relative.split("/"))
    current = root
    for component in relative.split("/"):
        current = current / component
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise UnsafeArtifactPath("An artifact path cannot be inspected.") from exc
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(
            stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400
        ):
            raise UnsafeArtifactPath("Symlinks and junctions below the workspace root are forbidden.")
    try:
        candidate.resolve(strict=False).relative_to(root)
    except (ValueError, OSError, RuntimeError) as exc:
        raise UnsafeArtifactPath("The artifact path escapes the selected workspace.") from exc
    return candidate


def _digest(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _read(root: Path, relative: str, limit: int, *, allow_oversize: bool = False) -> bytes | None:
    path = _path(root, relative)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise NotebookConflict("An artifact could not be opened safely.") from exc
    with os.fdopen(fd, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise NotebookConflict("Artifacts must be ordinary files.")
        blob = handle.read(limit + 1)
    if len(blob) > limit and not allow_oversize:
        raise NotebookConflict("An artifact exceeds the supported size limit.")
    return blob


def _notebook_hash(root: Path, relative: str) -> str | None:
    blob = _read(root, relative, MAX_NOTEBOOK_BYTES, allow_oversize=True)
    if blob is None:
        return None
    # Executed notebooks may accumulate arbitrarily large user outputs. They
    # remain edited work, not unreadable companions or regeneration blockers.
    return "oversize-edited-notebook" if len(blob) > MAX_NOTEBOOK_BYTES else _digest(blob)


def _source(root: Path, relative: str) -> bytes:
    if PurePosixPath(relative).suffix.lower() not in (".py", ".r"):
        raise InvalidNotebookSource("Select an instructional .py or .R source file explicitly.")
    try:
        blob = _read(root, relative, MAX_SOURCE_BYTES)
    except NotebookConflict as exc:
        raise InvalidNotebookSource("Source must be an ordinary UTF-8 file no larger than 1 MiB.") from exc
    if blob is None:
        raise InvalidNotebookSource("The selected source does not exist.")
    try:
        blob.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise InvalidNotebookSource("Source must be UTF-8; no encoding conversion was performed.") from exc
    return blob


def _notebook(source_relative: str, source: bytes) -> bytes:
    python = PurePosixPath(source_relative).suffix.lower() == ".py"
    language, kernel = ("python", "python3") if python else ("R", "ir")
    return _json_bytes({
        "cells": [{
            "cell_type": "code", "execution_count": None, "id": "instructional-source",
            "metadata": {}, "outputs": [], "source": source.decode("utf-8"),
        }],
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3" if python else "R",
                "language": language, "name": kernel,
            },
            "language_info": {"name": language},
        },
        "nbformat": 4, "nbformat_minor": 5,
    })


def _names(source: str) -> tuple[str, str, str]:
    prefix = source + ".anchor-notebook"
    return prefix + ".json", prefix + ".pending.json", prefix + ".lock"


def _parse(blob: bytes, description: str) -> dict[str, Any]:
    try:
        result = json.loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise NotebookConflict(f"The {description} is invalid; it was not replaced.") from exc
    if not isinstance(result, dict):
        raise NotebookConflict(f"The {description} must be a JSON object.")
    return result


def _validate_companion(root: Path, source: str, value: dict[str, Any]) -> dict[str, Any]:
    expected_keys = {
        "schema", "version", "source", "source_sha256", "notebook",
        "converter_version", "notebook_sha256",
    }
    if set(value) != expected_keys or value.get("schema") != COMPANION_SCHEMA or type(value.get("version")) is not int or value["version"] != 1:
        raise NotebookConflict("The companion schema is unsupported; it was not replaced.")
    if value.get("source") != source or value.get("converter_version") != CONVERTER_VERSION:
        raise NotebookConflict("The companion does not match this source/converter.")
    for key in ("source_sha256", "notebook_sha256"):
        if not isinstance(value.get(key), str) or not re.fullmatch(r"[0-9a-f]{64}", value[key]):
            raise NotebookConflict("The companion has an invalid content hash.")
    notebook = value.get("notebook")
    _path(root, notebook)
    source_path, notebook_path = PurePosixPath(source), PurePosixPath(notebook)
    allowed_name = re.escape(source_path.stem) + r"(?:\.rev-[1-9][0-9]*)?\.ipynb"
    if notebook_path.parent != source_path.parent or not re.fullmatch(allowed_name, notebook_path.name):
        raise NotebookConflict("The companion notebook must be a managed source sibling.")
    return value


def _new_file(root: Path, relative: str, blob: bytes) -> None:
    path = _path(root, relative)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise NotebookConflict("An output already exists; no file was overwritten.") from exc
    # Interrupted writes remain as explicit conflicts. Never delete a notebook
    # merely because publication of its companion did not complete.
    with os.fdopen(fd, "wb") as handle:
        handle.write(blob)
        handle.flush()
        os.fsync(handle.fileno())


def _publish_companion(
    root: Path, relative: str, blob: bytes, previous: bytes | None,
    source_relative: str, source_blob: bytes,
) -> None:
    temporary = relative + "." + uuid.uuid4().hex + ".tmp"
    _new_file(root, temporary, blob)
    try:
        if _read(root, relative, MAX_METADATA_BYTES) != previous:
            raise NotebookConflict("The companion changed during conversion; it was not replaced.")
        _stable_source(root, source_relative, source_blob)
        # The per-source lock serializes all module writers. os.replace keeps
        # readers from observing a partially replaced companion.
        os.replace(_path(root, temporary), _path(root, relative))
    finally:
        temp_path = _path(root, temporary)
        if temp_path.exists():
            temp_path.unlink()


def _remove_matching(root: Path, relative: str, expected: bytes) -> None:
    if _read(root, relative, MAX_METADATA_BYTES) != expected:
        raise NotebookConflict("Recovery metadata changed; manual inspection is required.")
    _path(root, relative).unlink()


class _SourceLock:
    def __init__(self, root: Path, relative: str):
        self.root, self.relative = root, relative
        self.owner = uuid.uuid4().hex.encode("ascii")
        self.fd: int | None = None
        self.identity: tuple[int, int] | None = None

    def __enter__(self) -> "_SourceLock":
        path = _path(self.root, self.relative)
        try:
            self.fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        except FileExistsError as exc:
            raise NotebookBusy("A conversion lock exists. Confirm its owner has stopped before manually removing it; there is no stale-lock takeover.") from exc
        info = os.fstat(self.fd)
        self.identity = (info.st_dev, info.st_ino)
        try:
            os.write(self.fd, self.owner)
            os.fsync(self.fd)
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        # A replacement lock belongs to someone else. Never unlink it.
        try:
            path = _path(self.root, self.relative)
            info = path.lstat()
            if (info.st_dev, info.st_ino) == self.identity and _read(self.root, self.relative, MAX_METADATA_BYTES) == self.owner:
                path.unlink()
        except (OSError, NotebookArtifactError):
            pass


def _stable_source(root: Path, relative: str, expected: bytes) -> None:
    if _source(root, relative) != expected:
        raise NotebookConflict("Source changed during conversion. Existing outputs were preserved; inspect the pending record before retrying.")


def _recover(root: Path, source: str, source_blob: bytes, pending_blob: bytes) -> dict[str, Any]:
    companion_relative, pending_relative, _ = _names(source)
    pending = _parse(pending_blob, "pending conversion record")
    if set(pending) != {"schema", "version", "operation_id", "companion", "previous_companion_sha256"} or pending.get("schema") != PENDING_SCHEMA or type(pending.get("version")) is not int or pending["version"] != 1:
        raise NotebookConflict("The pending conversion record is unsupported; inspect it before retrying.")
    if not isinstance(pending.get("operation_id"), str) or not re.fullmatch(r"[0-9a-f]{32}", pending["operation_id"]):
        raise NotebookConflict("The pending conversion record has no valid operation identity.")
    if not isinstance(pending.get("companion"), dict):
        raise NotebookConflict("The pending conversion record has no valid companion.")
    companion = _validate_companion(root, source, pending["companion"])
    previous_hash = pending.get("previous_companion_sha256")
    if previous_hash is not None and (not isinstance(previous_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", previous_hash)):
        raise NotebookConflict("The pending conversion record has an invalid prior-companion hash.")
    notebook_blob = _notebook(source, source_blob)
    if companion["source_sha256"] != _digest(source_blob) or companion["notebook_sha256"] != _digest(notebook_blob):
        raise NotebookConflict("The source no longer matches its pending conversion. Preserve the outputs and inspect the pending record.")
    existing_companion = _read(root, companion_relative, MAX_METADATA_BYTES)
    companion_blob = _json_bytes(companion)
    if existing_companion != companion_blob and (None if existing_companion is None else _digest(existing_companion)) != previous_hash:
        raise NotebookConflict("The companion no longer matches the pending operation; it was not replaced.")
    existing_notebook_hash = _notebook_hash(root, companion["notebook"])
    if existing_notebook_hash is None:
        if existing_companion == companion_blob:
            raise NotebookConflict("A published notebook is missing; recovery will not silently recreate it.")
        _stable_source(root, source, source_blob)
        _new_file(root, companion["notebook"], notebook_blob)
    elif existing_notebook_hash != companion["notebook_sha256"]:
        raise NotebookConflict("The pending notebook was edited or incompletely written; it was preserved.")
    _stable_source(root, source, source_blob)
    if existing_companion != companion_blob:
        _publish_companion(root, companion_relative, companion_blob, existing_companion, source, source_blob)
    _remove_matching(root, pending_relative, pending_blob)
    return dict(companion)


def materialize(root: str | os.PathLike[str], source_relative: str, regenerate: bool = False) -> dict[str, Any]:
    """Create/recover an instructional notebook without execution or overwrite.

    An unchanged repeat returns its existing companion. Changed source or edited
    notebook requires ``regenerate=True``, which creates a new ``.rev-N.ipynb``.
    Any pending operation is recovered first, never silently discarded.
    """
    workspace, source = _root(root), _relative(source_relative)
    # Validate the input before creating a lock, then reread under the lock.
    _source(workspace, source)
    companion_relative, pending_relative, lock_relative = _names(source)
    with _SourceLock(workspace, lock_relative):
        source_blob = _source(workspace, source)
        pending_blob = _read(workspace, pending_relative, MAX_METADATA_BYTES)
        if pending_blob is not None:
            return _recover(workspace, source, source_blob, pending_blob)
        previous = _read(workspace, companion_relative, MAX_METADATA_BYTES)
        if previous is not None:
            companion = _validate_companion(workspace, source, _parse(previous, "notebook companion"))
            notebook_hash = _notebook_hash(workspace, companion["notebook"])
            if not regenerate and companion["source_sha256"] == _digest(source_blob) and notebook_hash is not None and companion["notebook_sha256"] == notebook_hash:
                _stable_source(workspace, source, source_blob)
                return dict(companion)
            if not regenerate:
                raise NotebookConflict("The source or notebook changed, or the notebook is missing. Explicit regeneration creates a new revision and preserves existing files.")
        source_path = PurePosixPath(source)
        notebook_relative = str(source_path.with_suffix(".ipynb"))
        if regenerate:
            revision = 1
            while _path(workspace, notebook_relative := str(source_path.with_name(f"{source_path.stem}.rev-{revision}.ipynb"))).exists():
                revision += 1
        elif _path(workspace, notebook_relative).exists():
            raise NotebookConflict("An unmatched notebook sibling already exists. Explicit regeneration creates a new revision without replacing it.")
        notebook_blob = _notebook(source, source_blob)
        companion = {
            "schema": COMPANION_SCHEMA, "version": 1,
            "source": source, "source_sha256": _digest(source_blob),
            "notebook": notebook_relative, "converter_version": CONVERTER_VERSION,
            "notebook_sha256": _digest(notebook_blob),
        }
        pending_blob = _json_bytes({
            "schema": PENDING_SCHEMA, "version": 1, "operation_id": uuid.uuid4().hex,
            "companion": companion,
            "previous_companion_sha256": None if previous is None else _digest(previous),
        })
        _stable_source(workspace, source, source_blob)
        _new_file(workspace, pending_relative, pending_blob)
        return _recover(workspace, source, source_blob, pending_blob)


def resolve_artifact(root: str | os.PathLike[str], source_relative: str) -> dict[str, Any]:
    """Inspect a source/companion without writing or executing anything.

    Only ``current`` means the generated pair is unchanged. A notebook marked
    ``notebook_edited`` is still user work: callers may offer opening it but must
    not regenerate in place. ``conflict`` does not establish a valid pairing.
    Unsafe paths and invalid sources raise typed exceptions.
    """
    workspace, source = _root(root), _relative(source_relative)
    source_blob = _source(workspace, source)
    companion_relative, pending_relative, lock_relative = _names(source)
    result: dict[str, Any] = {"source": source, "notebook": None, "status": "unconverted"}
    if _path(workspace, lock_relative).exists():
        return {**result, "status": "conflict", "reason": "conversion_lock_exists"}
    if _path(workspace, pending_relative).exists():
        return {**result, "status": "conflict", "reason": "pending_conversion_requires_recovery"}
    try:
        previous = _read(workspace, companion_relative, MAX_METADATA_BYTES)
    except UnsafeArtifactPath:
        raise
    except NotebookConflict as exc:
        return {**result, "status": "conflict", "reason": "invalid_companion", "detail": str(exc)}
    if previous is None:
        if _path(workspace, str(PurePosixPath(source).with_suffix(".ipynb"))).exists():
            return {**result, "status": "conflict", "reason": "unmatched_notebook_sibling"}
        return result
    try:
        companion = _validate_companion(workspace, source, _parse(previous, "notebook companion"))
        notebook_hash = _notebook_hash(workspace, companion["notebook"])
    except UnsafeArtifactPath:
        raise
    except NotebookConflict as exc:
        return {**result, "status": "conflict", "reason": "invalid_companion_or_notebook", "detail": str(exc)}
    if notebook_hash is None:
        return {**result, "status": "conflict", "reason": "notebook_missing"}
    source_changed = companion["source_sha256"] != _digest(source_blob)
    notebook_edited = companion["notebook_sha256"] != notebook_hash
    return {
        "source": source, "notebook": companion["notebook"],
        "status": "notebook_edited" if notebook_edited else "source_changed" if source_changed else "current",
        "source_changed": source_changed, "notebook_edited": notebook_edited,
        "companion": companion,
    }
