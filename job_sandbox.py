"""Prepare offline checks; the existing controller owns launch and process lifetime.

This is not a confinement attestation. Native MXC support must be demonstrated
separately. Its registry-read capability also makes removal of broker credentials
from readable registry/environment storage a prerequisite for own-Anchor jobs.
Callers must stop the author before preparation and reap the check before cleanup.
No generated file is ever copied back to the author tree.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
from types import MappingProxyType
from typing import Mapping


class SandboxError(ValueError):
    """Preparation or source verification failed; never retry unconfined."""


_EXCLUDED = frozenset({".git", ".ecgberht"})
_ENV_NAMES = frozenset({
    "SYSTEMROOT", "WINDIR", "COMSPEC", "SYSTEMDRIVE", "PATHEXT",
    "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432", "PROGRAMDATA",
    "COMMONPROGRAMFILES", "COMMONPROGRAMFILES(X86)", "COMMONPROGRAMW6432",
    "ALLUSERSPROFILE", "PUBLIC", "USERNAME", "USERDOMAIN", "USERPROFILE",
    "LOCALAPPDATA", "APPDATA", "HOMEDRIVE", "HOMEPATH",
})
_EXTRA_FILE_LIMIT = 8 * 1024 * 1024
_EXTRA_TOTAL_LIMIT = 32 * 1024 * 1024
_CLAUDE_FLAGS = (
    "--restricted", "--safe-mode", "--strict-mcp-config",
    "--tools", "Read,Glob,Grep,Edit,Write",
    "--permission-mode", "acceptEdits", "--permission-prompts", "none",
)


def restricted_claude_flags():
    """Exact verified policy flags; caller retains model/effort and subscription auth.

    Do not append tool, settings, MCP, add-dir, resume or bypass overrides. Observe
    the actual CLI init tools at integration; these arguments alone are no receipt.
    """
    return _CLAUDE_FLAGS


def _absolute(value):
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise SandboxError("an absolute path without parent traversal is required")
    return path


def _is_link(info):
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & 0x400  # FILE_ATTRIBUTE_REPARSE_POINT
    )


def _plain_path(value, *, directory=False):
    """Reject every reparse component, including junctions in the parent chain."""
    path = _absolute(value)
    for part in reversed((path, *path.parents)):
        info = part.lstat()
        if _is_link(info):
            raise SandboxError("symbolic links and reparse paths are not check inputs")
    info = path.lstat()
    if directory:
        valid = stat.S_ISDIR(info.st_mode)
    else:
        valid = stat.S_ISREG(info.st_mode) and info.st_nlink == 1
    if not valid:
        raise SandboxError("expected a plain directory" if directory else
                           "expected a plain file with one hard link")
    if path.resolve(strict=True) != path:
        raise SandboxError("path does not name its canonical filesystem object")
    return path


def _within(path, root):
    return path == root or root in path.parents


def _identity(info):
    return info.st_dev, info.st_ino


def _file_digest(path, destination=None, *, size_limit=None):
    path = _plain_path(path)
    before = path.lstat()
    if size_limit is not None and before.st_size > size_limit:
        raise SandboxError("extra input exceeds its byte limit")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as reader:
        opened = os.fstat(reader.fileno())
        if (_identity(opened) != _identity(before) or opened.st_nlink != 1
                or not stat.S_ISREG(opened.st_mode) or _is_link(opened)):
            raise SandboxError("input identity changed during preparation")
        _plain_path(path)  # Recheck parent junctions before consuming bytes.
        digest = hashlib.sha256()
        copied = 0
        writer = open(destination, "xb") if destination is not None else None
        try:
            for block in iter(lambda: reader.read(1024 * 1024), b""):
                copied += len(block)
                if size_limit is not None and copied > size_limit:
                    raise SandboxError("extra input exceeds its byte limit")
                digest.update(block)
                if writer is not None:
                    writer.write(block)
        finally:
            if writer is not None:
                writer.close()
        after = os.fstat(reader.fileno())
        _plain_path(path)
        current = path.lstat()
        if (any(_identity(info) != _identity(before) for info in (after, current))
                or any((info.st_size, info.st_mtime_ns, info.st_nlink)
                       != (before.st_size, before.st_mtime_ns, 1)
                       for info in (after, current))):
            raise SandboxError("input changed during preparation")
    return digest.hexdigest(), copied


def _snapshot(source, destination=None):
    """Hash names, empty directories, file modes and bytes; optionally copy them."""
    source = _plain_path(source, directory=True)
    digest = hashlib.sha256()

    def record(row):
        digest.update(json.dumps(row, ensure_ascii=True, separators=(",", ":")).encode())
        digest.update(b"\n")

    def visit(folder, relative):
        _plain_path(folder, directory=True)
        with os.scandir(folder) as listing:
            entries = sorted(list(listing), key=lambda item: item.name)
        for entry in entries:
            if entry.name.casefold() in _EXCLUDED:
                continue
            rel = relative / entry.name
            item = folder / entry.name
            info = item.lstat()
            if _is_link(info):
                raise SandboxError("snapshot contains a symbolic link or reparse point")
            if (rel.as_posix().casefold() == ".codex/config.toml"):
                raise SandboxError("job-local Codex configuration cannot configure the check launcher")
            target = destination / rel if destination is not None else None
            if stat.S_ISDIR(info.st_mode):
                record([rel.as_posix(), "directory"])
                if target is not None:
                    target.mkdir()
                visit(item, rel)
            else:
                content_hash, size = _file_digest(item, target)
                record([rel.as_posix(), "file", stat.S_IMODE(info.st_mode), size, content_hash])

    visit(source, Path())
    return digest.hexdigest()


def clean_environment(environ=None, *, runtime_paths=(), temp_dir=None, codex_home=None):
    """Allowlist platform startup data; never inherit tokens or interpreter hooks.

    runtime_paths are resolved by the trusted caller. PATH is rebuilt, rather than
    inherited from a job, shell profile or provider configuration. The author may
    use this helper without codex_home to retain its normal subscription identity.
    """
    parent = os.environ if environ is None else environ
    result = {key.upper(): str(value) for key, value in parent.items()
              if key.upper() in _ENV_NAMES}
    paths = [str(_plain_path(path, directory=True)) for path in runtime_paths]
    windows = result.get("SYSTEMROOT") or result.get("WINDIR")
    if windows:
        windows_path = _plain_path(windows, directory=True)
        paths.extend(str(path) for path in (
            windows_path / "System32", windows_path,
            windows_path / "System32" / "WindowsPowerShell" / "v1.0",
        ) if path.is_dir())
    result["PATH"] = os.pathsep.join(dict.fromkeys(paths))
    if temp_dir is not None:
        result["TEMP"] = result["TMP"] = str(_plain_path(temp_dir, directory=True))
    if codex_home is not None:
        result["CODEX_HOME"] = str(_plain_path(codex_home, directory=True))
    return result


def _config(runtime_roots):
    lines = [
        'default_permissions = "anchor-job"', '[windows]', 'sandbox = "mxc"',
        '[permissions.anchor-job.filesystem]', '":minimal" = "read"',
        '[permissions.anchor-job.filesystem.":workspace_roots"]', '"." = "write"',
        '[permissions.anchor-job.network]', 'enabled = false',
    ]
    for root in runtime_roots:
        lines.extend([
            "[permissions.anchor-job.filesystem." + json.dumps(root.as_posix()) + "]",
            '"." = "read"',
        ])
    return "\n".join(lines) + "\n"


def _cleanup(root, owned_base, identity):
    """Remove only our verified direct child; never descend into a junction.

    The controller must have ended the entire child tree first. Refuse changed
    parent/root identities rather than guessing at ownership after replacement.
    """
    _plain_path(owned_base, directory=True)
    if not root.exists() and not root.is_symlink():
        return
    _plain_path(root, directory=True)
    if root.parent != owned_base or not root.name.startswith("anchor-check-"):
        raise SandboxError("cleanup is outside the owned private directory")
    if _identity(root.lstat()) != identity:
        raise SandboxError("cleanup root identity changed")

    def remove(folder):
        _plain_path(folder, directory=True)
        with os.scandir(folder) as listing:
            entries = list(listing)
        for entry in entries:
            path = folder / entry.name
            info = path.lstat()
            if _is_link(info):
                # Windows junctions are directories; rmdir removes the link only.
                if stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode):
                    os.rmdir(path)
                else:
                    path.unlink()
            elif stat.S_ISDIR(info.st_mode):
                remove(path)
            else:
                path.unlink()
        folder.rmdir()

    remove(root)


@dataclass(frozen=True)
class PreparedCheck:
    source: Path
    root: Path
    owned_base: Path
    workspace: Path
    control: Path
    argv: tuple
    env: Mapping[str, str]
    source_fingerprint: str
    _root_identity: tuple

    @property
    def cwd(self):
        return self.workspace

    @property
    def receipt(self):
        """Parent intent metadata, explicitly not an observed execution verdict."""
        return {
            "adapter": "codex-mxc-offline-snapshot-v1", "source": str(self.source),
            "source_fingerprint": self.source_fingerprint,
            "workspace": str(self.workspace), "control": str(self.control),
            "argv": list(self.argv), "network_enabled": False,
            "confinement_verified": False,
        }

    def verify_source_unchanged(self):
        if _snapshot(self.source) != self.source_fingerprint:
            raise SandboxError("author source changed after check snapshot")
        return True

    def cleanup(self):
        _cleanup(self.root, self.owned_base, self._root_identity)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.cleanup()


def prepare_check(source, argv, *, owned_base, trusted_codex,
                  trusted_runtime_roots=(), extra_inputs=()):
    """Snapshot current files and return an exact, offline native MXC invocation.

    source and owned_base must be existing, disjoint plain directories. argv[0]
    must be a trusted absolute executable outside the author tree. Extra inputs
    are at most 32 explicitly supplied plain files, 8 MiB each / 32 MiB total.
    Only exact standalone path arguments are remapped; embedded shell strings or
    source paths inside flags are never rewritten or given extra read access.
    """
    source = _plain_path(source, directory=True)
    owned_base = _plain_path(owned_base, directory=True)
    if _within(source, owned_base) or _within(owned_base, source):
        raise SandboxError("source and owned base must not overlap")
    codex = _plain_path(trusted_codex)
    if not argv or isinstance(argv, (str, bytes)):
        raise SandboxError("check argv must be a nonempty argument sequence")
    arguments = tuple(os.fspath(arg) for arg in argv)
    if any(not isinstance(arg, str) or "\0" in arg for arg in arguments):
        raise SandboxError("check argv must contain text without NUL")
    executable = _plain_path(arguments[0])
    roots = tuple(dict.fromkeys(_plain_path(path, directory=True)
                               for path in trusted_runtime_roots))
    if any(_within(path, source) or _within(path, owned_base)
           for path in (codex, executable)):
        raise SandboxError("executables must be trusted outside source and owned base")
    if any(root == Path(root.anchor) or _within(source, root)
           or _within(owned_base, root) or _within(root, source)
           or _within(root, owned_base) for root in roots):
        raise SandboxError("runtime read grant overlaps source/control or is a filesystem root")
    extras = tuple(extra_inputs)
    if len(extras) > 32:
        raise SandboxError("too many extra input files")
    # No project configuration may influence launch from our private ancestry.
    for ancestor in (owned_base, *owned_base.parents):
        if (ancestor / ".codex" / "config.toml").exists():
            raise SandboxError("owned base has inherited Codex project configuration")
    root = Path(tempfile.mkdtemp(prefix="anchor-check-", dir=owned_base))
    root_identity = _identity(root.lstat())
    try:
        workspace, control = root / "workspace", root / "control"
        workspace.mkdir()
        control.mkdir()
        fingerprint = _snapshot(source, workspace)
        # A second observation detects ordinary concurrent edits and new files.
        if _snapshot(source) != fingerprint:
            raise SandboxError("author source changed while preparing the snapshot")
        remap = {}
        extra_total = 0
        for index, value in enumerate(extras):
            original = _plain_path(value)
            if str(original) not in arguments:
                raise SandboxError("extra input must match an exact check argument")
            if _within(original, source):
                continue  # Already included and remapped with the author snapshot.
            extra_dir = workspace / (".anchor-check-inputs-" + root.name[len("anchor-check-"):])
            extra_dir.mkdir(exist_ok=True)
            target = extra_dir / (str(index) + "-" + original.name)
            _hash, size = _file_digest(original, target, size_limit=_EXTRA_FILE_LIMIT)
            extra_total += size
            if extra_total > _EXTRA_TOTAL_LIMIT:
                raise SandboxError("extra inputs exceed their total byte limit")
            remap[str(original)] = str(target)
        inner = []
        for arg in arguments:
            if arg in remap:
                inner.append(remap[arg])
            elif Path(arg).is_absolute() and _within(Path(arg), source):
                inner.append(str(workspace / Path(arg).relative_to(source)))
            else:
                inner.append(arg)
        temp_dir = workspace / (".anchor-check-tmp-" + root.name[len("anchor-check-"):])
        temp_dir.mkdir()
        (control / "config.toml").write_text(_config(roots), encoding="utf-8")
        env = clean_environment(runtime_paths=(codex.parent, executable.parent, *roots),
                                temp_dir=temp_dir, codex_home=control)
        outer = (
            str(codex), "-c", "windows.sandbox=mxc", "-c",
            "permissions.anchor-job.network.enabled=false", "sandbox",
            "--include-managed-config", "--permission-profile", "anchor-job",
            "--cd", str(workspace), "--", *inner,
        )
        prepared = PreparedCheck(source, root, owned_base, workspace, control, outer,
                                 MappingProxyType(env), fingerprint, root_identity)
        (control / "preparation.json").write_text(
            json.dumps(prepared.receipt, indent=2), encoding="utf-8")
        return prepared
    except BaseException:
        _cleanup(root, owned_base, root_identity)
        raise
