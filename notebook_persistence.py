"""Persist explicitly registered instructional notebooks before worktree teardown.

DELIVERABLES.md remains the only product register. This module owns only recovery
receipts, not a second register or transaction claim. Callers must refuse step
completion/worktree teardown when ``ok`` is false. Only the supplied .py/.R rows
with valid notebook companions are considered; no script discovery/conversion.

Files are snapshotted, validated, copied exclusively into MAIN, then registered
using notebook_products. Existing different MAIN bytes are never overwritten.
Partial copies/registrations remain recoverable through a private pending receipt.
"""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import threading
from typing import Callable, Mapping, Sequence
import uuid


MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_BATCH_BYTES = 256 * 1024 * 1024
_LOCK = threading.RLock()


class NotebookPersistenceError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str):
    raise NotebookPersistenceError(code, message)


def _relative(value: object) -> str:
    if not isinstance(value, str) or not value or any(ord(c) < 32 for c in value):
        _fail("invalid_product_path", "A product path must be a relative file path.")
    value = value.replace("\\", "/")
    path = PurePosixPath(value)
    if value.startswith("/") or ":" in value or ".." in value.split("/") or path.is_absolute():
        _fail("invalid_product_path", "Product paths cannot be absolute or traverse outside the project.")
    if "`" in value or "|" in value or not path.parts or path.name in {"", "."}:
        _fail("invalid_product_path", "Pass the parsed relative register path, not Markdown.")
    return path.as_posix()


def _check_components(path: Path, *, existing: bool = True) -> None:
    for component in (path, *path.parents):
        try:
            details = component.lstat()
        except FileNotFoundError:
            if existing:
                _fail("missing_product", "A required product path no longer exists.")
            continue
        if stat.S_ISLNK(details.st_mode) or getattr(details, "st_file_attributes", 0) & 0x400:
            _fail("reparse_path", "Notebook persistence cannot traverse symlinks or reparse points.")


def _root(value: str | Path) -> Path:
    raw = str(value)
    path = Path(value)
    if not path.is_absolute() or raw.startswith(("\\\\", "//")):
        _fail("invalid_project_root", "Notebook persistence requires explicit local absolute project roots.")
    if os.name == "nt":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
        kernel.GetDriveTypeW.restype = wintypes.UINT
        if kernel.GetDriveTypeW(path.anchor) != 3:
            _fail("invalid_project_root", "Notebook persistence roots must be on local fixed disks.")
    _check_components(path)
    if not path.is_dir():
        _fail("invalid_project_root", "Notebook persistence requires existing project directories.")
    return path.resolve(strict=True)


def _path(root: Path, relative: str, *, existing: bool = True) -> Path:
    normalized = _relative(relative)
    path = root.joinpath(*PurePosixPath(normalized).parts)
    _check_components(path, existing=existing)
    try:
        path.resolve(strict=existing).relative_to(root)
    except (ValueError, OSError):
        _fail("invalid_product_path", "A product path escaped its project root.")
    if existing and not path.is_file():
        _fail("invalid_product_path", "A product path must refer to a regular file.")
    return path


def _bytes(path: Path) -> bytes:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            _fail("product_too_large", "A notebook product exceeds the 64 MiB persistence limit.")
        with path.open("rb") as handle:
            data = handle.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            _fail("product_too_large", "A notebook product exceeds the 64 MiB persistence limit.")
        return data
    except OSError:
        _fail("product_read_failed", "A required notebook product could not be read.")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _resolver(root, source):
    from notebook_artifacts import resolve_artifact
    return resolve_artifact(root, source)


def _register(root, source, *, what, step):
    from notebook_products import register_instructional
    return register_instructional(root, source, what=what, step=step, regenerate=False)


def _collect(worktree: Path, items: Sequence[Mapping[str, object]], resolver: Callable):
    if not isinstance(items, (list, tuple)):
        _fail("invalid_product_rows", "Supply explicit parsed instructional product rows.")
    products, files, total = [], {}, 0
    seen = set()
    for item in items:
        if not isinstance(item, Mapping):
            _fail("invalid_product_rows", "A product row must be an object.")
        source = _relative(item.get("where"))
        if Path(source).suffix.lower() not in {".py", ".r"}:
            _fail("instructional_source_required", "Only explicit Python and R instructional source rows may be persisted here.")
        what, step = item.get("what"), item.get("step", "")
        if (not isinstance(what, str) or not what.strip() or isinstance(step, bool)
                or not isinstance(step, (str, int))):
            _fail("invalid_product_rows", "Product rows require a description and an optional step label.")
        if source in seen:
            _fail("duplicate_product_row", "The same instructional source was supplied more than once.")
        seen.add(source)
        info = resolver(worktree, source)
        if not isinstance(info, Mapping) or info.get("status") not in {"current", "notebook_edited"}:
            status = info.get("status") if isinstance(info, Mapping) else None
            code = "source_changed" if status == "source_changed" else "explicit_registration_required"
            if status == "conflict":
                code = "artifact_conflict"
            _fail(code, "Resolve or explicitly register the instructional notebook before persisting the worktree.")
        notebook = _relative(info.get("notebook"))
        if _relative(info.get("source")) != source or Path(notebook).suffix.lower() != ".ipynb":
            _fail("artifact_conflict", "The registered source and notebook association is inconsistent.")
        companion = source + ".anchor-notebook.json"
        snapshot = {}
        for relative in (source, notebook, companion):
            snapshot[relative] = _bytes(_path(worktree, relative))
        try:
            notebook_document = json.loads(snapshot[notebook])
            if (not isinstance(notebook_document, dict) or notebook_document.get("nbformat") != 4
                    or not isinstance(notebook_document.get("cells"), list)):
                raise ValueError()
        except (ValueError, UnicodeError):
            _fail("artifact_conflict", "The current notebook bytes are not a valid notebook document.")
        try:
            metadata = json.loads(snapshot[companion].decode("utf-8"))
        except (ValueError, UnicodeError):
            _fail("artifact_conflict", "The notebook companion is not valid UTF-8 JSON.")
        required = {"schema", "version", "source", "source_sha256", "notebook", "converter_version", "notebook_sha256"}
        if (not isinstance(metadata, dict) or set(metadata) != required
                or metadata.get("schema") != "anchor.notebook-companion" or metadata.get("version") != 1
                or metadata.get("converter_version") != "1"
                or metadata.get("source") != source or metadata.get("notebook") != notebook):
            _fail("artifact_conflict", "The notebook companion does not match the supported source/notebook contract.")
        if metadata["source_sha256"] != _sha(snapshot[source]):
            _fail("source_changed", "Instructional source changed after its notebook was registered.")
        # notebook_sha256 is the original baseline, NOT permission to overwrite
        # an edited notebook. Persist the current notebook bytes unchanged.
        for hash_name in ("source_sha256", "notebook_sha256"):
            value = metadata[hash_name]
            if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                _fail("artifact_conflict", "The notebook companion contains an invalid content hash.")
        for relative, content in snapshot.items():
            if relative in files and files[relative] != content:
                _fail("artifact_conflict", "Product rows disagree about shared file contents.")
            if relative not in files:
                total += len(content)
                if total > MAX_BATCH_BYTES:
                    _fail("product_batch_too_large", "The notebook persistence batch exceeds 256 MiB.")
                files[relative] = content
        products.append({"source": source, "notebook": notebook, "what": what, "step": str(step),
                         "files": [source, notebook, companion]})
    return products, files


def _mkdir_contained(root: Path, directory: Path) -> None:
    try:
        parts = directory.relative_to(root).parts
    except ValueError:
        _fail("invalid_product_path", "A product directory escaped MAIN.")
    if ".." in parts:
        _fail("invalid_product_path", "A product directory cannot traverse outside MAIN.")
    current = root
    for part in parts:
        current /= part
        _check_components(current, existing=False)
        if not current.exists():
            current.mkdir(mode=0o700)
        if not current.is_dir():
            _fail("main_file_conflict", "An existing file blocks a required notebook product directory.")


def _private_directory(path: Path, *, created: bool) -> None:
    if os.name != "nt":
        details = path.stat()
        if details.st_uid != os.geteuid() or stat.S_IMODE(details.st_mode) & 0o077:
            _fail("private_receipts_required", "Notebook recovery receipts require a private owner-only directory.")
        return
    from notebook_service import current_windows_account, verify_private_path
    account = current_windows_account()
    if created:
        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [wintypes.LPCWSTR,
            wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
        advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
        advapi.GetSecurityDescriptorDacl.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL),
            ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.BOOL)]
        advapi.GetSecurityDescriptorDacl.restype = wintypes.BOOL
        advapi.SetNamedSecurityInfoW.argtypes = [wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD,
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        advapi.SetNamedSecurityInfoW.restype = wintypes.DWORD
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        descriptor = ctypes.c_void_p()
        sddl = "D:P" + "".join(f"(A;OICI;FA;;;{sid})" for sid in
                                dict.fromkeys((str(account["sid"]), "S-1-5-18", "S-1-5-32-544")))
        if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None):
            _fail("private_receipts_required", "Could not establish a private notebook receipt directory.")
        try:
            present, defaulted, dacl = wintypes.BOOL(), wintypes.BOOL(), ctypes.c_void_p()
            if not advapi.GetSecurityDescriptorDacl(descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)):
                _fail("private_receipts_required", "Could not establish a private notebook receipt directory.")
            if advapi.SetNamedSecurityInfoW(str(path), 1, 0x4 | 0x80000000, None, None, dacl, None):
                _fail("private_receipts_required", "Could not establish a private notebook receipt directory.")
        finally:
            kernel.LocalFree(descriptor)
    verify_private_path(path, account)


def _receipt_directory(main: Path) -> Path:
    parent = main / ".anchor"
    _mkdir_contained(main, parent)
    directory = parent / "notebook-completions"
    _check_components(directory, existing=False)
    created = False
    try:
        directory.mkdir(mode=0o700)
        created = True
    except FileExistsError:
        if not directory.is_dir():
            _fail("private_receipts_required", "A file blocks the notebook receipt directory.")
    _private_directory(directory, created=created)
    return directory


@contextmanager
def _completion_lock(directory: Path):
    path = directory / ".persistence.lock"
    _check_components(path, existing=False)
    with _LOCK, path.open("a+b") as handle:
        handle.seek(0)
        if not handle.read(1):
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            _fail("persistence_busy", "Another notebook completion is persisting into MAIN.")
        try:
            yield
        finally:
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def _write_receipt(path: Path, receipt: Mapping[str, object]) -> None:
    _check_components(path, existing=False)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(receipt, handle, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)  # Only this private receipt, never a product.
    finally:
        if temporary.exists():
            temporary.unlink()


def _copy_exclusive(destination: Path, content: bytes, *, staging: Path) -> None:
    """Atomic create-without-replace using a receipt-owned staging hard link.

    The caller records this exact staging path in the pending receipt first.
    Partial single-link staging bytes may be discarded on retry, never MAIN.
    """
    _check_components(destination, existing=False)
    _check_components(staging, existing=False)
    if destination.exists():
        if not destination.is_file() or _bytes(destination) != content:
            _fail("main_file_conflict", "MAIN already has different product bytes; nothing was overwritten.")
        # Recover a crash after atomic linking but before staging cleanup.
        if staging.exists():
            if not staging.is_file() or (_bytes(staging) != content and staging.stat().st_nlink != 1):
                _fail("staging_conflict", "A staged recovery file has unexpected bytes.")
            staging.unlink()
        return
    if staging.exists():
        if not staging.is_file():
            _fail("staging_conflict", "A staged recovery file has unexpected bytes.")
        if _bytes(staging) != content:
            if staging.stat().st_nlink != 1:
                _fail("staging_conflict", "A staged recovery file has unexpected links.")
            staging.unlink()  # Exact receipt-owned partial file; worktree source remains.
    if not staging.exists():
        created = False
        try:
            with staging.open("xb") as handle:
                created = True
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            # We own this newly-created staging file, never the destination.
            if created and staging.exists():
                staging.unlink()
            raise
    try:
        os.link(staging, destination)  # Atomic exclusive creation on Windows/POSIX.
    except FileExistsError:
        if not destination.is_file() or _bytes(destination) != content:
            _fail("main_file_conflict", "MAIN changed while persisting; nothing was overwritten.")
    finally:
        if staging.exists():
            staging.unlink()


def _verify_snapshot(root: Path, files: Mapping[str, bytes], code: str) -> None:
    for relative, content in files.items():
        if _bytes(_path(root, relative)) != content:
            _fail(code, "Notebook product bytes changed during completion; retain the worktree for recovery.")


def _preserve_main_registration(main: Path, products: Sequence[Mapping[str, object]]) -> None:
    """Without an edit baseline, never overwrite a differing MAIN product label."""
    from notebook_completion import _register_rows
    rows = _register_rows(main) or []
    for product in products:
        locations = {f'`{product["source"]}`', f'`{product["notebook"]}`'}
        matching = [row for row in rows if row["where"].strip() in locations]
        if len(matching) > 1 or any(row["what"] != product["what"]
                or str(row["step"]) != str(product["step"]) for row in matching):
            _fail("main_registration_conflict", "MAIN has a different notebook label or producing step; merge the register explicitly before completion.")


def persist_registered_products(main_root: str | Path, worktree_root: str | Path,
                                items: Sequence[Mapping[str, object]], *,
                                resolver: Callable = _resolver, register: Callable = _register,
                                copy_file: Callable = _copy_exclusive,
                                receipt_directory: Callable = _receipt_directory) -> dict[str, object]:
    """Persist the explicit source/notebook/companion triplets, then register them.

    Injection seams are for focused tests; normal callers supply only three
    positional arguments. Every failure returns ok:false and must block reap.
    Recovery retries re-verify all bytes, even for a previously registered receipt.
    """
    persisted, products, receipt, receipt_path = [], [], None, None
    try:
        main, worktree = _root(main_root), _root(worktree_root)
        products, files = _collect(worktree, items, resolver)
        if not products:
            return {"ok": True, "persisted": [], "products": 0, "reason": "no_registered_notebooks", "completion_receipt": None}
        manifest = {relative: _sha(content) for relative, content in sorted(files.items())}
        identity = {"main": os.path.normcase(str(main)), "worktree": os.path.normcase(str(worktree)),
                    "rows": products, "manifest": manifest}
        key = _sha(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode("utf-8"))[:32]
        directory = receipt_directory(main)
        receipt_path = directory / f"{key}.json"
        relative_receipt = receipt_path.relative_to(main).as_posix()
        with _completion_lock(directory):
            _preserve_main_registration(main, products)
            if receipt_path.exists():
                _check_components(receipt_path)
                try:
                    receipt = json.loads(_bytes(receipt_path).decode("utf-8"))
                except (ValueError, UnicodeError):
                    _fail("receipt_conflict", "The existing completion receipt is unreadable; retain it for recovery.")
                if (not isinstance(receipt, dict) or receipt.get("schema") != "anchor.notebook-completion"
                        or receipt.get("version") != 1 or receipt.get("manifest") != manifest
                        or receipt.get("completion_id") != key):
                    _fail("receipt_conflict", "The existing completion receipt does not match these products.")
            else:
                receipt = {"schema": "anchor.notebook-completion", "version": 1, "completion_id": key,
                           "stage": "pending", "manifest": manifest, "copied": [], "registered": [],
                           "products": [{"source": p["source"], "notebook": p["notebook"]} for p in products]}
            receipt.pop("last_error", None)
            receipt["stage"] = "pending"
            receipt["copied"] = []
            receipt["registered"] = []
            receipt["staging"] = {relative: (PurePosixPath(relative).parent /
                f".anchor-notebook-{key}-{_sha(relative.encode('utf-8'))[:24]}.stage").as_posix()
                for relative in files}
            _write_receipt(receipt_path, receipt)  # Pending intent exists BEFORE any MAIN copy.
            for relative, content in files.items():
                destination = _path(main, relative, existing=False)
                if destination.exists() and (not destination.is_file() or _bytes(destination) != content):
                    _fail("main_file_conflict", "MAIN already has different product bytes; nothing was overwritten.")
            for relative, content in files.items():
                destination = _path(main, relative, existing=False)
                _mkdir_contained(main, destination.parent)
                # Stage alongside the product so it inherits MAIN's intended
                # notebook-account ACL and is guaranteed on the same filesystem.
                # Receipts stay private; product bytes are already authorized
                # to live here. Hidden staging names are never register entries.
                staging = _path(main, receipt["staging"][relative], existing=False)
                copy_file(destination, content, staging=staging)
                persisted.append(relative)
                receipt["copied"] = list(persisted)
                _write_receipt(receipt_path, receipt)
            _verify_snapshot(main, files, "main_changed_during_completion")
            _verify_snapshot(worktree, files, "worktree_changed_during_completion")
            receipt["stage"] = "copied"
            _write_receipt(receipt_path, receipt)
            registered = []
            for product in products:
                _preserve_main_registration(main, [product])
                outcome = register(main, product["source"], what=product["what"], step=product["step"])
                if not isinstance(outcome, Mapping) or outcome.get("ok") is not True:
                    _fail("registration_failed", "Notebook bytes are durable, but product registration has not completed.")
                registered.append(product["source"])
                receipt["registered"] = list(registered)
                _write_receipt(receipt_path, receipt)
            _verify_snapshot(main, files, "main_changed_during_completion")
            _verify_snapshot(worktree, files, "worktree_changed_during_completion")
            receipt["stage"] = "registered"
            _write_receipt(receipt_path, receipt)
            return {"ok": True, "persisted": persisted, "products": len(products),
                    "reason": "registered", "completion_receipt": relative_receipt}
    except Exception as exc:
        code = getattr(exc, "code", "persistence_failed")
        # Never replace a corrupt/conflicting existing receipt with guessed state.
        if receipt_path is not None and isinstance(receipt, dict) and code != "receipt_conflict":
            try:
                # The failed operation released its lock. Reacquire before
                # annotating, and do not clobber a newer successful retry.
                with _completion_lock(receipt_path.parent):
                    current = json.loads(_bytes(receipt_path).decode("utf-8"))
                    if current.get("completion_id") == receipt.get("completion_id") and current.get("stage") != "registered":
                        current["last_error"] = code
                        _write_receipt(receipt_path, current)
            except Exception:
                code = "receipt_update_failed"
        relative_receipt = None
        if receipt_path is not None:
            try:
                relative_receipt = receipt_path.relative_to(main).as_posix()
            except ValueError:
                pass
        return {"ok": False, "persisted": persisted, "products": len(products),
                "reason": code, "completion_receipt": relative_receipt}
