#!/usr/bin/env python3
"""Safe one-shot Codex transport for Anchor's ChatGPT subscription seat.

The adapter is both importable (pure argv/env/JSONL seams for tests and callers)
and executable (``job_runner`` launches it as a normal stdlib child). It emits
Codex's native JSONL on stderr for the durable job log, then exactly one
Claude-compatible ``type=result`` envelope on stdout so Anchor's existing reader
can capture the answer, usage, thread id, and a whitelisted model receipt.

No API-key transport is allowed. The prompt is read from stdin and forwarded to
``codex exec ... -``; it never appears in argv or a durable prompt file.
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import io
import json
import os
import re
import signal
import stat
import subprocess
import sys
import threading
import time
import tomllib
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path


CODEX_MODEL = "gpt-5.6-sol"
CODEX_EFFORT = "ultra"
DEFAULT_TIMEOUT_SECONDS = 45 * 60
VALID_SANDBOXES = frozenset(("read-only", "workspace-write"))
MAX_ARTIFACT_SCAN_FILES = 10_000
MAX_ARTIFACT_SCAN_BYTES = 512 * 1024 * 1024
MAX_NATIVE_TOKEN_COUNT = 100_000_000
MAX_NATIVE_STDOUT_BYTES = 32 * 1024 * 1024
MAX_NATIVE_STDERR_BYTES = 8 * 1024 * 1024
MAX_NATIVE_OUTPUT_BYTES = 36 * 1024 * 1024
MAX_NATIVE_EVENT_COUNT = 100_000
MAX_NATIVE_EVENT_BYTES = 1024 * 1024
MAX_PREFLIGHT_STDOUT_BYTES = 2 * 1024 * 1024
MAX_PREFLIGHT_STDERR_BYTES = 512 * 1024
MAX_PREFLIGHT_OUTPUT_BYTES = 2 * 1024 * 1024
PIPE_CHUNK_BYTES = 64 * 1024
PIPE_DRAIN_TIMEOUT_SECONDS = 5.0
MAX_EXPECTED_ARTIFACTS = 32
MAX_EXPECTED_PATH_BYTES = 512
MAX_EXPECTED_TOTAL_PATH_BYTES = 4096
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
MAX_ARTIFACT_TOTAL_BYTES = 256 * 1024 * 1024
IGNORED_ARTIFACT_NAMES = frozenset(("launch.pointer.json",))
WINDOWS_RESERVED_NAMES = frozenset(
    ("con", "prn", "aux", "nul", "clock$", "conin$", "conout$") +
    tuple("com%d" % value for value in range(1, 10)) +
    tuple("lpt%d" % value for value in range(1, 10)) +
    tuple("com%s" % value for value in ("¹", "²", "³")) +
    tuple("lpt%s" % value for value in ("¹", "²", "³"))
)

API_AUTH_ENV_KEYS = frozenset((
    "OPENAI_API_KEY",
    "CODEX_API_KEY",
    "CODEX_ACCESS_TOKEN",
    "OPENAI_ORG_ID",
    "OPENAI_ORGANIZATION",
    "OPENAI_PROJECT_ID",
    "OPENAI_BASE_URL",
    "OPENAI_API_BASE",
    "CODEX_BASE_URL",
))

COMMAND_OVERRIDE_ENV_KEYS = frozenset(("ANCHOR_CODEX_CMD", "CODEX_BIN"))
PROTECTED_USER_CONFIG_KEYS = frozenset((
    "apps", "chatgpt_base_url", "hooks", "model_provider",
    "model_providers", "notify", "openai_base_url", "plugins", "profile",
    "profiles",
))
PROTECTED_FEATURE_KEYS = frozenset((
    "apps", "browser_use", "browser_use_external", "computer_use", "hooks",
    "image_generation", "plugins", "remote_plugin",
    "skill_mcp_dependency_install",
))
USAGE_KEYS = (
    "input_tokens", "cached_input_tokens", "cache_write_input_tokens",
    "output_tokens", "reasoning_output_tokens",
)

# No caller environment key is inherited. Values below are reconstructed from
# OS identity APIs and fixed system paths so new workload/API credential names
# cannot silently cross the subscription boundary.


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _canonical_path(value) -> Path:
    return Path(value).expanduser().resolve(strict=False)


def _windows_known_folder(folder_id: str) -> Path:
    """Resolve an identity directory through Win32, never caller environment."""
    import ctypes

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
            ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8),
        ]

    guid = GUID.from_buffer_copy(uuid.UUID(folder_id).bytes_le)
    allocated = ctypes.c_wchar_p()
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    ole32 = ctypes.WinDLL("ole32", use_last_error=True)
    shell32.SHGetKnownFolderPath.argtypes = [
        ctypes.POINTER(GUID), ctypes.c_ulong, ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_wchar_p),
    ]
    shell32.SHGetKnownFolderPath.restype = ctypes.c_long
    result = shell32.SHGetKnownFolderPath(
        ctypes.byref(guid), 0, None, ctypes.byref(allocated))
    if result != 0:
        raise OSError("SHGetKnownFolderPath failed (0x%08x)" % (result & 0xFFFFFFFF))
    try:
        return _canonical_path(allocated.value)
    finally:
        ole32.CoTaskMemFree(allocated)


def _os_profile_dir(platform_name=None) -> Path:
    runtime_platform = os.name if platform_name is None else str(platform_name)
    if runtime_platform == "nt":
        # FOLDERID_Profile
        return _windows_known_folder("5e6c858f-0e22-4760-9afe-ea3317b67173")
    try:
        import pwd
        return _canonical_path(pwd.getpwuid(os.getuid()).pw_dir)
    except (ImportError, KeyError, OSError, AttributeError):
        # Path.home()/expanduser() may consult caller-controlled HOME.  Saved
        # subscription auth is an identity boundary, so an unavailable OS
        # account database is a hard failure rather than an environment
        # fallback.
        raise OSError("OS account profile directory is unavailable")


def _codex_home_path(platform_name=None) -> Path:
    return _os_profile_dir(platform_name) / ".codex"


def _known_codex_roots(env=None, platform_name=None) -> list[Path]:
    runtime_platform = os.name if platform_name is None else str(platform_name)
    profile = _os_profile_dir(runtime_platform)
    roots = []
    if runtime_platform == "nt":
        # FOLDERID_LocalAppData
        local = _windows_known_folder("f1b32785-6fba-4fcf-9d55-7b8e7f157091")
        roots.extend((
            local / "Programs" / "OpenAI" / "Codex" / "bin",
            profile / ".codex" / "packages" / "standalone" / "current" / "bin",
        ))
    else:
        roots.extend((profile / ".codex" / "bin", profile / ".local" / "bin"))
    if runtime_platform != "nt":
        roots.extend((_canonical_path("/usr/local/bin"), _canonical_path("/usr/bin")))
    return list(dict.fromkeys(_canonical_path(root) for root in roots))


def resolve_codex_cmd(env=None) -> str:
    """Resolve only a known local Codex installation, never a caller override."""
    env = dict(os.environ if env is None else env)
    exe = "codex.exe" if os.name == "nt" else "codex"
    candidates = [root / exe for root in _known_codex_roots(env, os.name)]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.resolve())
    raise FileNotFoundError(
        "Codex executable was not found in an approved installation directory")


def subscription_only_env(env=None) -> dict:
    """Return the minimal OS environment needed by a saved-login Codex child."""
    if os.name == "nt":
        windows_path = _windows_directory()
        profile_path = _os_profile_dir("nt")
        local_path = _windows_known_folder(
            "f1b32785-6fba-4fcf-9d55-7b8e7f157091")
        roaming_path = _windows_known_folder(
            "3eb685db-65f9-4cf6-a03a-e3ef65729f3d")
        codex_roots = _known_codex_roots({}, "nt")
        trusted_search = list(codex_roots) + [
            windows_path / "System32", windows_path,
        ]
        clean = {
            "APPDATA": str(roaming_path),
            "COMSPEC": str(windows_path / "System32" / "cmd.exe"),
            "HOMEDRIVE": profile_path.drive,
            "HOMEPATH": str(profile_path)[len(profile_path.drive):],
            "LOCALAPPDATA": str(local_path),
            "NO_COLOR": "1",
            "OS": "Windows_NT",
            "PATH": os.pathsep.join(str(path) for path in trusted_search),
            "PATHEXT": ".COM;.EXE;.BAT;.CMD",
            "SYSTEMDRIVE": windows_path.drive,
            "SYSTEMROOT": str(windows_path),
            "TEMP": str(local_path / "Temp"),
            "TMP": str(local_path / "Temp"),
            "USERNAME": profile_path.name,
            "USERPROFILE": str(profile_path),
            "WINDIR": str(windows_path),
        }
    else:
        profile_path = _os_profile_dir("posix")
        try:
            import pwd
            username = pwd.getpwuid(os.getuid()).pw_name
        except (ImportError, KeyError, OSError, AttributeError):
            username = profile_path.name
        clean = {
            "HOME": str(profile_path), "LANG": "C.UTF-8",
            "LOGNAME": username, "NO_COLOR": "1",
            "PATH": "/usr/local/bin:/usr/bin:/bin", "SHELL": "/bin/sh",
            "TMPDIR": "/tmp", "USER": username,
        }
    # Saved ChatGPT auth is loaded only from the OS identity's fixed profile.
    # A caller-controlled CODEX_HOME would redirect both credentials and config.
    nominal_home = _codex_home_path(os.name).expanduser().absolute()
    codex_home = nominal_home.resolve(strict=False)
    if os.path.normcase(str(nominal_home)) != os.path.normcase(str(codex_home)):
        raise ValueError("fixed CODEX_HOME must not be redirected by a link or junction")
    clean["CODEX_HOME"] = str(codex_home)
    return clean


def _minimal_env_verified(clean: dict, platform_name=None) -> bool:
    runtime_platform = os.name if platform_name is None else str(platform_name)
    windows_keys = {
        "APPDATA", "CODEX_HOME", "COMSPEC", "HOMEDRIVE", "HOMEPATH",
        "LOCALAPPDATA", "NO_COLOR", "OS", "PATH", "PATHEXT", "SYSTEMDRIVE",
        "SYSTEMROOT", "TEMP", "TMP", "USERNAME", "USERPROFILE", "WINDIR",
    }
    posix_keys = {
        "CODEX_HOME", "HOME", "LANG", "LOGNAME", "NO_COLOR", "PATH",
        "SHELL", "TMPDIR", "USER",
    }
    expected = windows_keys if runtime_platform == "nt" else posix_keys
    if set(clean) != expected or any(not isinstance(value, str) for value in clean.values()):
        return False
    forbidden_fragments = (
        "API_KEY", "ACCESS_TOKEN", "REFRESH_TOKEN", "IDENTITY_TOKEN",
        "FEDERATED_TOKEN", "CREDENTIALS", "CLIENT_SECRET", "BASE_URL",
        "ENDPOINT", "PROVIDER",
    )
    return not any(
        fragment in key.upper() for key in clean for fragment in forbidden_fragments)


def _open_guarded_file(path: Path):
    """Open without write/delete sharing on Windows and without symlinks on POSIX."""
    canonical = path.expanduser().absolute()
    if os.name == "nt":
        import ctypes
        import msvcrt

        generic_read = 0x80000000
        share_read = 0x00000001
        open_existing = 3
        normal_no_reparse_follow = 0x00000080 | 0x00200000
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateFileW.argtypes = [
            ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p,
            ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p,
        ]
        kernel32.CreateFileW.restype = ctypes.c_void_p
        handle = kernel32.CreateFileW(
            str(canonical), generic_read, share_read, None, open_existing,
            normal_no_reparse_follow, None)
        invalid = ctypes.c_void_p(-1).value
        if handle in (None, invalid):
            raise OSError(ctypes.get_last_error(), "CreateFileW failed", str(canonical))
        try:
            fd = msvcrt.open_osfhandle(int(handle), os.O_RDONLY)
        except BaseException:
            kernel32.CloseHandle(handle)
            raise
        return os.fdopen(fd, "rb", closefd=True)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    return os.fdopen(os.open(canonical, flags), "rb", closefd=True)


class _GuardedFd:
    """Minimal context-managed owner for an OS descriptor."""

    def __init__(self, fd):
        self._fd = int(fd)
        self.closed = False

    def fileno(self):
        if self.closed:
            raise ValueError("guarded descriptor is closed")
        return self._fd

    def close(self):
        if not self.closed:
            os.close(self._fd)
            self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, _kind, _value, _traceback):
        self.close()


def _open_guarded_directory(path: Path):
    """Hold the workspace root identity; allow writes but deny root rename."""
    canonical = path.expanduser().absolute()
    if os.name == "nt":
        import ctypes
        import msvcrt

        generic_read = 0x80000000
        share_read_write = 0x00000001 | 0x00000002
        open_existing = 3
        backup_semantics_no_reparse = 0x02000000 | 0x00200000
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateFileW.argtypes = [
            ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p,
            ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p,
        ]
        kernel32.CreateFileW.restype = ctypes.c_void_p
        handle = kernel32.CreateFileW(
            str(canonical), generic_read, share_read_write, None,
            open_existing, backup_semantics_no_reparse, None)
        invalid = ctypes.c_void_p(-1).value
        if handle in (None, invalid):
            raise OSError(
                ctypes.get_last_error(), "CreateFileW(directory) failed",
                str(canonical))
        try:
            fd = msvcrt.open_osfhandle(int(handle), os.O_RDONLY)
        except BaseException:
            kernel32.CloseHandle(handle)
            raise
        return _GuardedFd(fd)
    flags = (os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) |
             getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_DIRECTORY", 0))
    return _GuardedFd(os.open(canonical, flags))


def _guarded_directory_identity(handle, canonical: Path):
    observed = os.fstat(handle.fileno())
    if not stat.S_ISDIR(observed.st_mode) or _is_reparse(observed):
        raise OSError("workspace root guard is not a plain directory")
    return (int(observed.st_dev), int(observed.st_ino))


def _workspace_root_matches(root: Path, identity) -> bool:
    try:
        observed = root.lstat()
    except OSError:
        return False
    return bool(
        stat.S_ISDIR(observed.st_mode) and not stat.S_ISLNK(observed.st_mode) and
        not _is_reparse(observed) and
        (int(observed.st_dev), int(observed.st_ino)) == tuple(identity)
    )


def _fingerprint_handle(handle, canonical: Path) -> dict:
    before = os.fstat(handle.fileno())
    if not stat.S_ISREG(before.st_mode):
        raise OSError("guarded path is not a regular file: %s" % canonical)
    handle.seek(0)
    digest = hashlib.sha256()
    for block in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(block)
    after = os.fstat(handle.fileno())
    identity = (
        int(before.st_dev), int(before.st_ino), int(before.st_size),
        int(before.st_mtime_ns),
    )
    if identity != (
            int(after.st_dev), int(after.st_ino), int(after.st_size),
            int(after.st_mtime_ns)):
        raise OSError("guarded file changed while it was being fingerprinted")
    return {
        "path": str(canonical), "exists": True,
        "sha256": digest.hexdigest(), "size": int(after.st_size),
        "mtime_ns": int(after.st_mtime_ns), "device": int(after.st_dev),
        "inode": int(after.st_ino),
    }


def _stable_file_fingerprint(path: Path) -> dict:
    """Hash a regular file while proving it did not change during the read."""
    canonical = path.resolve(strict=False)
    try:
        handle = _open_guarded_file(canonical)
    except FileNotFoundError:
        return {"path": str(canonical), "exists": False, "sha256": None}
    with handle:
        return _fingerprint_handle(handle, canonical)


def _stable_file_bytes(path: Path, max_bytes=4 * 1024 * 1024) -> tuple[bytes, dict]:
    """Read and hash one small guarded file from the same open handle."""
    canonical = path.expanduser().absolute()
    handle = _open_guarded_file(canonical)
    with handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > int(max_bytes):
            raise OSError("guarded configuration file is invalid or too large")
        content = handle.read(int(max_bytes) + 1)
        if len(content) > int(max_bytes):
            raise OSError("guarded configuration file is too large")
        after = os.fstat(handle.fileno())
        identity = (
            int(before.st_dev), int(before.st_ino), int(before.st_size),
            int(before.st_mtime_ns),
        )
        if identity != (
                int(after.st_dev), int(after.st_ino), int(after.st_size),
                int(after.st_mtime_ns)) or len(content) != int(after.st_size):
            raise OSError("guarded configuration changed while it was read")
        fingerprint = {
            "path": str(canonical), "exists": True,
            "sha256": hashlib.sha256(content).hexdigest(),
            "size": int(after.st_size), "mtime_ns": int(after.st_mtime_ns),
            "device": int(after.st_dev), "inode": int(after.st_ino),
        }
        return content, fingerprint


def _fingerprints_match(left, right) -> bool:
    keys = ("path", "exists", "sha256", "size", "mtime_ns", "device", "inode")
    return all((left or {}).get(key) == (right or {}).get(key) for key in keys)


def _path_matches_fingerprint(path: Path, fingerprint: dict) -> bool:
    """Bind a guarded handle fingerprint back to the executable pathname."""
    try:
        observed = path.lstat()
    except OSError:
        return False
    if stat.S_ISLNK(observed.st_mode) or _is_reparse(observed):
        return False
    expected = fingerprint or {}
    return (
        int(observed.st_dev) == int(expected.get("device")) and
        int(observed.st_ino) == int(expected.get("inode")) and
        int(observed.st_size) == int(expected.get("size")) and
        int(observed.st_mtime_ns) == int(expected.get("mtime_ns"))
    )


def inspect_user_config(env=None) -> dict:
    """Fail closed on user config capable of widening Anchor's transport."""
    clean = subscription_only_env(env)
    codex_home = _canonical_path(clean["CODEX_HOME"])
    config_path = codex_home / "config.toml"
    # A symlinked config can redirect the audited trust boundary after HOME was
    # canonicalized. Refuse it rather than trying to reason about its owner.
    if config_path.is_symlink():
        return {
            "ok": False, "status": "config_guard_failed",
            "codex_home": str(codex_home), "config_path": str(config_path),
            "error": "Codex user config must not be a symbolic link",
        }
    if not config_path.exists():
        fingerprint = {
            "path": str(config_path.absolute()), "exists": False, "sha256": None,
        }
        return {
            "ok": True, "codex_home": str(codex_home),
            "config_path": str(config_path), "config_fingerprint": fingerprint,
            "mcp_entries_absent": True,
        }
    fingerprint = {
        "path": str(config_path.absolute()), "exists": True, "sha256": None,
    }
    try:
        content, fingerprint = _stable_file_bytes(config_path)
        raw = tomllib.loads(content.decode("utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        return {
            "ok": False, "status": "config_guard_failed",
            "codex_home": str(codex_home), "config_path": str(config_path),
            "config_fingerprint": fingerprint,
            "error": "Codex user config could not be audited: %s" % str(exc)[:300],
        }
    if not isinstance(raw, dict):
        return {
            "ok": False, "status": "config_guard_failed",
            "codex_home": str(codex_home), "config_path": str(config_path),
            "config_fingerprint": fingerprint,
            "error": "Codex user config is not a TOML table",
        }
    unsafe = sorted(key for key in PROTECTED_USER_CONFIG_KEYS if key in raw)
    if unsafe:
        return {
            "ok": False, "status": "config_guard_failed",
            "codex_home": str(codex_home), "config_path": str(config_path),
            "config_fingerprint": fingerprint,
            "error": "Codex user config contains protected widening keys: %s" %
                     ", ".join(unsafe),
        }
    features = raw.get("features", {})
    if not isinstance(features, dict):
        return {
            "ok": False, "status": "config_guard_failed",
            "codex_home": str(codex_home), "config_path": str(config_path),
            "config_fingerprint": fingerprint,
            "error": "Codex features config is not a table",
        }
    unsafe_features = sorted(key for key in PROTECTED_FEATURE_KEYS if key in features)
    if unsafe_features:
        return {
            "ok": False, "status": "config_guard_failed",
            "codex_home": str(codex_home), "config_path": str(config_path),
            "config_fingerprint": fingerprint,
            "error": "Codex user config contains protected feature keys: %s" %
                     ", ".join(unsafe_features),
        }
    mcp = raw.get("mcp_servers", {})
    if not isinstance(mcp, dict):
        return {
            "ok": False, "status": "config_guard_failed",
            "codex_home": str(codex_home), "config_path": str(config_path),
            "config_fingerprint": fingerprint,
            "error": "Codex mcp_servers config is not a table",
        }
    if mcp:
        labels = [repr(str(key)) for key in mcp]
        return {
            "ok": False, "status": "config_guard_failed",
            "codex_home": str(codex_home), "config_path": str(config_path),
            "config_fingerprint": fingerprint,
            "error": "Codex user MCP entries are forbidden: %s" % ", ".join(labels),
        }
    return {
        "ok": True, "codex_home": str(codex_home),
        "config_path": str(config_path), "config_fingerprint": fingerprint,
        "mcp_entries_absent": True,
    }


def _win_verify_trust(path: Path, guarded_handle=None) -> dict:
    """Verify and extract the accepted leaf signer from one WVT provider state."""
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8),
        ]

    class WINTRUST_FILE_INFO(ctypes.Structure):
        _fields_ = [
            ("cbStruct", wintypes.DWORD), ("pcwszFilePath", wintypes.LPCWSTR),
            ("hFile", wintypes.HANDLE), ("pgKnownSubject", ctypes.POINTER(GUID)),
        ]

    class WINTRUST_DATA(ctypes.Structure):
        _fields_ = [
            ("cbStruct", wintypes.DWORD),
            ("pPolicyCallbackData", wintypes.LPVOID),
            ("pSIPClientData", wintypes.LPVOID),
            ("dwUIChoice", wintypes.DWORD),
            ("fdwRevocationChecks", wintypes.DWORD),
            ("dwUnionChoice", wintypes.DWORD),
            ("pFile", ctypes.POINTER(WINTRUST_FILE_INFO)),
            ("dwStateAction", wintypes.DWORD),
            ("hWVTStateData", wintypes.HANDLE),
            ("pwszURLReference", wintypes.LPCWSTR),
            ("dwProvFlags", wintypes.DWORD),
            ("dwUIContext", wintypes.DWORD),
            ("pSignatureSettings", wintypes.LPVOID),
        ]

    class CERT_CONTEXT(ctypes.Structure):
        _fields_ = [
            ("dwCertEncodingType", wintypes.DWORD),
            ("pbCertEncoded", ctypes.POINTER(ctypes.c_ubyte)),
            ("cbCertEncoded", wintypes.DWORD),
            ("pCertInfo", ctypes.c_void_p),
            ("hCertStore", wintypes.HANDLE),
        ]

    class CRYPT_PROVIDER_CERT(ctypes.Structure):
        _fields_ = [
            ("cbStruct", wintypes.DWORD),
            ("pCert", ctypes.POINTER(CERT_CONTEXT)),
        ]

    class CRYPT_PROVIDER_SGNR(ctypes.Structure):
        _fields_ = [
            ("cbStruct", wintypes.DWORD),
            ("sftVerifyAsOf", wintypes.FILETIME),
            ("csCertChain", wintypes.DWORD),
            ("pasCertChain", ctypes.POINTER(CRYPT_PROVIDER_CERT)),
        ]

    action = GUID.from_buffer_copy(
        uuid.UUID("00aac56b-cd44-11d0-8cc2-00c04fc295ee").bytes_le)
    native_handle = None
    if guarded_handle is not None:
        import msvcrt
        native_handle = wintypes.HANDLE(
            msvcrt.get_osfhandle(guarded_handle.fileno()))
    file_info = WINTRUST_FILE_INFO(
        ctypes.sizeof(WINTRUST_FILE_INFO), str(path), native_handle, None)
    data = WINTRUST_DATA()
    data.cbStruct = ctypes.sizeof(WINTRUST_DATA)
    data.dwUIChoice = 2  # WTD_UI_NONE
    data.fdwRevocationChecks = 0  # WTD_REVOKE_NONE
    data.dwUnionChoice = 1  # WTD_CHOICE_FILE
    data.pFile = ctypes.pointer(file_info)
    data.dwStateAction = 1  # WTD_STATEACTION_VERIFY
    data.dwProvFlags = 0x00001000  # WTD_CACHE_ONLY_URL_RETRIEVAL
    wintrust = ctypes.WinDLL("wintrust", use_last_error=True)
    wintrust.WinVerifyTrust.argtypes = [
        wintypes.HWND, ctypes.POINTER(GUID), ctypes.c_void_p]
    wintrust.WinVerifyTrust.restype = ctypes.c_long
    wintrust.WTHelperProvDataFromStateData.argtypes = [wintypes.HANDLE]
    wintrust.WTHelperProvDataFromStateData.restype = ctypes.c_void_p
    wintrust.WTHelperGetProvSignerFromChain.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    wintrust.WTHelperGetProvSignerFromChain.restype = \
        ctypes.POINTER(CRYPT_PROVIDER_SGNR)
    result = None
    try:
        result = int(wintrust.WinVerifyTrust(
            None, ctypes.byref(action), ctypes.byref(data)))
        status = "0x%08x" % (result & 0xFFFFFFFF)
        if result != 0:
            return {"ok": False, "signature_status": status}
        provider = wintrust.WTHelperProvDataFromStateData(data.hWVTStateData)
        if not provider:
            return {
                "ok": False, "signature_status": status,
                "error": "WinVerifyTrust provider state is unavailable",
            }
        signer = wintrust.WTHelperGetProvSignerFromChain(
            provider, 0, False, 0)
        if (not signer or int(signer.contents.csCertChain) < 1 or
                not signer.contents.pasCertChain):
            return {
                "ok": False, "signature_status": status,
                "error": "WinVerifyTrust accepted no leaf signer chain",
            }
        cert = signer.contents.pasCertChain[0].pCert
        if not cert or not cert.contents.pbCertEncoded:
            return {
                "ok": False, "signature_status": status,
                "error": "WinVerifyTrust leaf certificate is unavailable",
            }
        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        crypt32.CertGetNameStringW.argtypes = [
            ctypes.POINTER(CERT_CONTEXT), wintypes.DWORD, wintypes.DWORD,
            ctypes.c_void_p, wintypes.LPWSTR, wintypes.DWORD,
        ]
        crypt32.CertGetNameStringW.restype = wintypes.DWORD

        def _subject_attribute(oid):
            encoded_oid = ctypes.create_string_buffer(oid.encode("ascii") + b"\0")
            oid_pointer = ctypes.cast(encoded_oid, ctypes.c_void_p)
            count = int(crypt32.CertGetNameStringW(
                cert, 3, 0, oid_pointer, None, 0))  # CERT_NAME_ATTR_TYPE
            if count <= 1 or count > 1024:
                return ""
            value = ctypes.create_unicode_buffer(count)
            written = int(crypt32.CertGetNameStringW(
                cert, 3, 0, oid_pointer, value, count))
            return value.value if written == count else ""

        encoded_cert = ctypes.string_at(
            cert.contents.pbCertEncoded, int(cert.contents.cbCertEncoded))
        return {
            "ok": True, "signature_status": status,
            "signer_common_name": _subject_attribute("2.5.4.3"),
            "signer_organization": _subject_attribute("2.5.4.10"),
            "signer_certificate_sha256": hashlib.sha256(encoded_cert).hexdigest(),
        }
    finally:
        if data.hWVTStateData:
            data.dwStateAction = 2  # WTD_STATEACTION_CLOSE
            wintrust.WinVerifyTrust(
                None, ctypes.byref(action), ctypes.byref(data))


def _windows_directory() -> Path:
    import ctypes

    buffer = ctypes.create_unicode_buffer(32768)
    length = ctypes.WinDLL("kernel32", use_last_error=True).GetWindowsDirectoryW(
        buffer, len(buffer))
    if length <= 0 or length >= len(buffer):
        raise OSError(ctypes.get_last_error(), "GetWindowsDirectoryW failed")
    return _canonical_path(buffer.value)


def _windows_authenticode(path: Path, env, run_impl=subprocess.run,
                          trust_impl=_win_verify_trust,
                          windows_dir_fn=_windows_directory,
                          guarded_handle=None) -> dict:
    """Verify Authenticode and require the exact OpenAI corporate signer."""
    trust_evidence = (
        trust_impl(path, guarded_handle)
        if guarded_handle is not None else trust_impl(path)
    )
    if not isinstance(trust_evidence, dict):
        return {
            "ok": False,
            "error": "WinVerifyTrust did not return bound signer evidence",
        }
    trust_ok = trust_evidence.get("ok") is True
    trust_status = str(trust_evidence.get("signature_status") or "unknown")
    if not trust_ok:
        return {
            "ok": False, "error": trust_evidence.get("error") or
            "WinVerifyTrust rejected Codex (%s)" % trust_status,
            "signature_status": trust_status,
        }
    common_name = str(trust_evidence.get("signer_common_name") or "")
    organization = str(trust_evidence.get("signer_organization") or "")
    if (common_name != "OpenAI OpCo, LLC" or
            organization != "OpenAI OpCo, LLC"):
        return {
            "ok": False,
            "error": "WinVerifyTrust leaf signer CN/O is not exactly OpenAI OpCo, LLC",
            "signature_status": trust_status,
            "signer_subject": "CN=%s, O=%s" % (common_name, organization),
        }
    return {
        "ok": True, "signature_status": trust_status,
        "signer_subject": "CN=%s, O=%s" % (common_name, organization),
        "signer_certificate_sha256": trust_evidence.get(
            "signer_certificate_sha256"),
        "signature_revocation_freshness": "unproven_cache_only",
    }


def inspect_executable(cmd: str, env=None, platform_name=None,
                       signature_run_impl=subprocess.run, keep_guard=False) -> dict:
    """Attest a canonical Codex binary in a known installation directory."""
    clean = subscription_only_env(env)
    runtime_platform = os.name if platform_name is None else str(platform_name)
    supplied = Path(str(cmd)).expanduser()
    if not supplied.is_absolute():
        return {"ok": False, "error": "Codex executable path is not absolute"}
    try:
        canonical = supplied.resolve(strict=True)
    except OSError as exc:
        return {"ok": False, "error": "Codex executable is unavailable: %s" % str(exc)[:300]}
    expected_name = "codex.exe" if runtime_platform == "nt" else "codex"
    roots = _known_codex_roots(clean, runtime_platform)
    if canonical.name.casefold() != expected_name.casefold() or not any(
            canonical.parent == root for root in roots):
        return {
            "ok": False,
            "error": "Codex executable is outside approved installation roots",
        }
    guard = None
    try:
        guard = _open_guarded_file(canonical)
        fingerprint = _fingerprint_handle(guard, canonical)
        if not _path_matches_fingerprint(canonical, fingerprint):
            return {"ok": False, "error": "Codex path does not name the guarded image"}
        file_stat = os.fstat(guard.fileno())
        mode = file_stat.st_mode
        if runtime_platform == "nt":
            # The no-write/no-delete-share guard remains open across both trust
            # and signer extraction. A second handle hash below binds every
            # reported fact to these exact bytes and file identity.
            signature = _windows_authenticode(
                canonical, clean, signature_run_impl, guarded_handle=guard)
            if not signature.get("ok"):
                return dict(signature, executable_path=str(canonical))
            signature_kind = "authenticode-openai"
            signer_subject = signature.get("signer_subject")
            signer_certificate_sha256 = signature.get(
                "signer_certificate_sha256")
            revocation_freshness = signature.get("signature_revocation_freshness")
        else:
            current_uid = os.getuid() if hasattr(os, "getuid") else file_stat.st_uid
            if int(file_stat.st_uid) not in (0, int(current_uid)):
                return {"ok": False, "error": "Codex executable has an untrusted owner"}
            if stat.S_IMODE(mode) & (stat.S_IWGRP | stat.S_IWOTH):
                return {"ok": False, "error": "Codex executable is group/world writable"}
            if not stat.S_IMODE(mode) & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH):
                return {"ok": False, "error": "Codex executable has no execute bit"}
            root_stat = canonical.parent.stat()
            if (int(root_stat.st_uid) not in (0, int(current_uid)) or
                    stat.S_IMODE(root_stat.st_mode) & (stat.S_IWGRP | stat.S_IWOTH)):
                return {"ok": False, "error": "Codex installation root is not trusted"}
            signature_kind = "posix-owner-mode"
            signer_subject = None
            signer_certificate_sha256 = None
            revocation_freshness = "not_applicable"
        rebound = _fingerprint_handle(guard, canonical)
        if (not _fingerprints_match(fingerprint, rebound) or
                not _path_matches_fingerprint(canonical, rebound)):
            return {"ok": False, "error": "Codex image changed during provenance attestation"}
        result = {
            "ok": True, "executable_path": str(canonical),
            "executable_fingerprint": fingerprint,
            "executable_provenance_verified": True,
            "executable_provenance_kind": signature_kind,
            "executable_signer_subject": signer_subject,
            "executable_signer_certificate_sha256": signer_certificate_sha256,
            "signature_revocation_freshness": revocation_freshness,
            # Windows binds the WVT leaf signer and SHA to one guarded handle.
            # POSIX has owner/mode evidence but no platform signer identity.
            "signer_image_binding_verified": runtime_platform == "nt",
        }
        if keep_guard:
            result["_executable_guard_handle"] = guard
            guard = None
        return result
    except OSError as exc:
        return {
            "ok": False,
            "error": "Codex executable provenance failed: %s" % str(exc)[:300],
        }
    finally:
        if guard is not None:
            try:
                guard.close()
            except BaseException:
                pass


def recheck_runtime_guard(preflight: dict, env=None, platform_name=None) -> dict:
    """Lock and re-attest the exact executable immediately before Popen."""
    clean = subscription_only_env(env)
    if str(clean.get("CODEX_HOME")) != str(preflight.get("codex_home")):
        return {
            "ok": False, "status": "config_guard_changed",
            "error": "fixed Codex authentication home changed after preflight",
        }
    current_executable = inspect_executable(
        str(preflight.get("executable_path") or ""), clean, platform_name,
        keep_guard=True)
    if not current_executable.get("ok"):
        return {
            "ok": False, "status": "executable_guard_changed",
            "error": current_executable.get("error") or "Codex executable guard failed",
        }
    if not _fingerprints_match(
            current_executable.get("executable_fingerprint"),
            preflight.get("executable_fingerprint")):
        handle = current_executable.get("_executable_guard_handle")
        if handle is not None:
            handle.close()
        return {
            "ok": False, "status": "executable_guard_changed",
            "error": "Codex executable changed after preflight",
        }
    return {
        "ok": True, "config_guard_verified": True,
        "runtime_guard_rechecked": True,
        "executable_provenance_verified": True,
        "signer_image_binding_verified": bool(
            current_executable.get("signer_image_binding_verified")),
        "user_config_ignored": True,
        "mcp_entries_absent": True,
        # Kept open by run_codex until Popen returns. This blocks replacement on
        # Windows, but Popen cannot prove the final kernel child image identity.
        "_executable_guard_handle": current_executable.get(
            "_executable_guard_handle"),
        "executable_handle_guarded_through_spawn": False,
        "preexecution_child_image_attested": False,
    }


def parse_login_status(stdout: str, stderr: str = "", returncode: int = 0) -> bool:
    """True only when the CLI explicitly reports ChatGPT subscription login."""
    text = "%s\n%s" % (stdout or "", stderr or "")
    return returncode == 0 and re.search(r"logged in using chatgpt", text, re.I) is not None


def parse_model_catalog(text: str) -> list[dict]:
    """Return only model slugs and advertised reasoning efforts from catalog JSON."""
    raw = json.loads((text or "").strip())
    models = raw.get("models") if isinstance(raw, dict) else None
    if not isinstance(models, list):
        raise ValueError("Codex model catalog did not contain a models array")
    out = []
    for model in models:
        if not isinstance(model, dict):
            continue
        levels = model.get("supported_reasoning_levels") or []
        efforts = []
        for level in levels:
            if isinstance(level, dict) and isinstance(level.get("effort"), str):
                effort = level["effort"].strip().lower()
                if effort:
                    efforts.append(effort)
        out.append({"slug": str(model.get("slug") or ""), "efforts": efforts})
    return out


class _PreflightProbeFailure(RuntimeError):
    """Typed no-seat probe refusal carrying bounded containment evidence."""

    def __init__(self, status, detail, evidence=None):
        super().__init__(str(detail))
        self.status = str(status)
        self.detail = str(detail)[:500]
        self.evidence = dict(evidence or {})


def _preflight_args_are_local_only(args) -> bool:
    """Allow only the three exact local, non-inference preflight commands."""
    supplied = tuple(str(value) for value in args)
    return supplied in (
        ("--version",),
        ("login", "status"),
        (
            "-c", "model_providers={}",
            "-c", 'model_provider="openai"',
            "-c", "mcp_servers={}",
            "-c", "apps={}",
            "debug", "models",
        ),
    )


def preflight_codex(cmd: str, model=CODEX_MODEL, effort=CODEX_EFFORT,
                    env=None, run_impl=None, now_fn=_now_iso,
                    provenance_fn=inspect_executable,
                    popen_impl=subprocess.Popen, platform_name=None,
                    windows_job_factory=None) -> dict:
    """Prove executable, ChatGPT auth, and installed model/Ultra capability."""
    child_env = subscription_only_env(env)
    base = {
        "executable_path": str(cmd),
        "transport_actual": None,
        "cli_version": None,
        "auth_kind": None,
        "auth_probe_at": now_fn(),
        "subscription_auth": None,
        "model_capability_verified": False,
        "ultra_capability_verified": False,
        "config_guard_verified": False,
        "user_config_ignored": False,
        "runtime_guard_rechecked": False,
        "executable_provenance_verified": False,
        "child_env_allowlist_verified": _minimal_env_verified(child_env),
        "api_key_env_scrubbed": _minimal_env_verified(child_env),
        "mcp_entries_absent": False,
        "codex_home": child_env.get("CODEX_HOME"),
        "preflight_probe_count": 0,
        "preflight_containment_kind": None,
        "preflight_complete_tree_containment": False,
        "preflight_no_inference_verified": False,
        "preflight_no_network_intent_verified": False,
        "preflight_output_limits_verified": False,
        "preflight_output_drain_verified": False,
        "preflight_root_exit_verified": False,
        "preflight_windows_job_policy_verified": False,
        "preflight_windows_job_assignment_verified": False,
        "preflight_windows_job_membership_verified": False,
        "preflight_windows_process_handle_verified": False,
        "preflight_windows_primary_thread_verified": False,
        "preflight_windows_process_resumed": False,
        "preflight_windows_job_empty_verified": False,
        "preflight_process_group_kill_verified": None,
    }
    try:
        provenance = provenance_fn(cmd, child_env)
    except (OSError, TypeError, ValueError) as exc:
        provenance = {"ok": False, "error": str(exc)[:300]}
    if not provenance.get("ok"):
        return dict(
            base, ok=False, status="executable_provenance_failed",
            error=provenance.get("error") or "Codex executable provenance failed",
        )
    base.update(
        executable_path=provenance.get("executable_path"),
        executable_fingerprint=provenance.get("executable_fingerprint"),
        executable_provenance_verified=bool(
            provenance.get("executable_provenance_verified")),
        executable_provenance_kind=provenance.get("executable_provenance_kind"),
        executable_signer_subject=provenance.get("executable_signer_subject"),
        executable_signer_certificate_sha256=provenance.get(
            "executable_signer_certificate_sha256"),
        signer_image_binding_verified=bool(
            provenance.get("signer_image_binding_verified")),
        signature_revocation_freshness=provenance.get(
            "signature_revocation_freshness"),
    )
    cmd = str(base["executable_path"])

    def _merge_probe_evidence(evidence):
        evidence = dict(evidence or {})
        base["preflight_probe_count"] = int(base["preflight_probe_count"]) + 1
        kind = evidence.get("preflight_containment_kind")
        previous_kind = base.get("preflight_containment_kind")
        if previous_kind not in (None, kind):
            raise _PreflightProbeFailure(
                "preflight_containment_failed",
                "preflight probes did not retain one containment kind", evidence)
        base["preflight_containment_kind"] = kind
        for key in (
                "preflight_complete_tree_containment",
                "preflight_no_inference_verified",
                "preflight_no_network_intent_verified",
                "preflight_output_limits_verified",
                "preflight_output_drain_verified",
                "preflight_root_exit_verified",
                "preflight_windows_job_policy_verified",
                "preflight_windows_job_assignment_verified",
                "preflight_windows_job_membership_verified",
                "preflight_windows_process_handle_verified",
                "preflight_windows_primary_thread_verified",
                "preflight_windows_process_resumed",
                "preflight_windows_job_empty_verified"):
            observed = bool(evidence.get(key))
            base[key] = observed if base["preflight_probe_count"] == 1 else bool(
                base.get(key) and observed)
        group_proof = evidence.get("preflight_process_group_kill_verified")
        if group_proof is not None:
            base["preflight_process_group_kill_verified"] = bool(group_proof)

    def _probe(args, timeout):
        canonical_cmd = Path(cmd).resolve(strict=False)
        if not _preflight_args_are_local_only(args):
            raise _PreflightProbeFailure(
                "preflight_command_refused",
                "preflight command is not an exact local-only probe")
        # ``run_impl`` is retained only for hermetic unit-test injection. The
        # production path never enters subprocess.run/communicate buffering.
        if run_impl is not None:
            return run_impl(
                [str(canonical_cmd)] + list(args),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=child_env,
                cwd=str(canonical_cmd.parent),
                executable=str(canonical_cmd),
                shell=False,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0)
                               if os.name == "nt" else 0),
            )
        probe = _run_preflight_probe(
            str(canonical_cmd), args, child_env, timeout,
            popen_impl=popen_impl, platform_name=platform_name,
            windows_job_factory=windows_job_factory)
        _merge_probe_evidence(probe.get("evidence"))
        if not probe.get("ok"):
            raise _PreflightProbeFailure(
                probe.get("status") or "preflight_probe_failed",
                probe.get("error") or "Codex preflight probe failed",
                probe.get("evidence"))
        return subprocess.CompletedProcess(
            probe.get("argv") or [], int(probe.get("returncode") or 0),
            probe.get("stdout") or "", probe.get("stderr") or "")

    try:
        version = _probe(("--version",), 10)
    except _PreflightProbeFailure as exc:
        base.update(exc.evidence)
        return dict(base, ok=False, status=exc.status, error=exc.detail)
    except subprocess.TimeoutExpired:
        return dict(base, ok=False, status="preflight_timeout",
                    error="Codex version probe timed out")
    except OSError as exc:
        return dict(base, ok=False, status="spawn_error", error=str(exc)[:500])
    if version.returncode != 0:
        detail = (version.stderr or version.stdout or "version command failed").strip()
        return dict(base, ok=False, status="version_probe_failed", error=detail[:500])
    base["cli_version"] = (version.stdout or version.stderr or "").strip()[:200]
    base["transport_actual"] = "codex-cli"

    try:
        login = _probe(("login", "status"), 15)
    except _PreflightProbeFailure as exc:
        base.update(exc.evidence)
        return dict(base, ok=False, status=exc.status, error=exc.detail)
    except subprocess.TimeoutExpired:
        return dict(base, ok=False, status="preflight_timeout",
                    error="Codex subscription login probe timed out")
    except OSError as exc:
        return dict(base, ok=False, status="spawn_error", error=str(exc)[:500])
    if not parse_login_status(login.stdout, login.stderr, login.returncode):
        detail = (login.stderr or login.stdout or
                  "Codex CLI is not logged in using ChatGPT").strip()
        return dict(base, ok=False, status="subscription_auth_required",
                    subscription_auth=False, error=detail[:500])
    base.update(auth_kind="chatgpt_subscription", subscription_auth=True)

    try:
        catalog_run = _probe((
            "-c", "model_providers={}",
            "-c", 'model_provider="openai"',
            "-c", "mcp_servers={}",
            "-c", "apps={}",
            "debug", "models",
        ), 30)
    except _PreflightProbeFailure as exc:
        base.update(exc.evidence)
        return dict(base, ok=False, status=exc.status, error=exc.detail)
    except subprocess.TimeoutExpired:
        return dict(base, ok=False, status="preflight_timeout",
                    error="Codex installed-model capability probe timed out")
    except OSError as exc:
        return dict(base, ok=False, status="spawn_error", error=str(exc)[:500])
    if catalog_run.returncode != 0:
        detail = (catalog_run.stderr or catalog_run.stdout or
                  "catalog command failed").strip()
        return dict(base, ok=False, status="catalog_probe_failed", error=detail[:500])
    try:
        catalog = parse_model_catalog(catalog_run.stdout)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        return dict(base, ok=False, status="catalog_probe_failed", error=str(exc)[:500])
    selected = next((entry for entry in catalog if entry.get("slug") == model), None)
    if selected is None:
        return dict(base, ok=False, status="capability_unavailable",
                    error="installed Codex catalog does not advertise model %s" % model)
    base["model_capability_verified"] = True
    if effort not in selected.get("efforts", []):
        return dict(
            base, ok=False, status="capability_unavailable",
            error=("installed Codex model %s does not advertise effort %s "
                   "(supports %s)" %
                   (model, effort, "|".join(selected.get("efforts") or ["none"]))),
        )
    base["ultra_capability_verified"] = effort == "ultra"
    return dict(base, ok=True, status="ready")


def _toml_basic_string(value) -> str:
    """Encode one TOML basic string without relying on dotted-key parsing."""
    return json.dumps(str(value), ensure_ascii=False)


def build_exec_argv(cmd: str, target, sandbox="read-only",
                    model=CODEX_MODEL, effort=CODEX_EFFORT,
                    mcp_server_ids=()) -> list[str]:
    """Build the pinned, prompt-on-stdin ``codex exec`` argv.

    The real CODEX_HOME remains available only for saved ChatGPT authentication
    and Codex's own ephemeral state. ``--ignore-user-config`` prevents its
    mutable config.toml from entering the seat; Anchor owns every runtime
    setting below. Workspace-write success proves only a stable SHA mutation of
    each explicitly expected safe path, never semantic correctness.
    """
    if sandbox not in VALID_SANDBOXES:
        raise ValueError("unsupported Codex sandbox %r" % (sandbox,))
    if tuple(mcp_server_ids or ()):
        raise ValueError("user MCP entries are forbidden for Anchor Codex seats")
    target_path = Path(target).resolve()
    # Replace the entire projects table. A quoted key inside one inline table
    # handles drive letters, dots, spaces, quotes, backslashes, and Unicode as a
    # literal project path instead of accidentally constructing dotted tables.
    projects_override = 'projects={%s={trust_level="untrusted"}}' % (
        _toml_basic_string(str(target_path)),)
    argv = [
        str(cmd),
        "exec",
        "--skip-git-repo-check",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--strict-config",
        "--color", "never",
        "--json",
        "--sandbox", sandbox,
        "-c", 'approval_policy="never"',
        "-c", 'forced_login_method="chatgpt"',
        "-c", 'model_providers={}',
        "-c", 'model_provider="openai"',
        "-c", 'mcp_servers={}',
        "-c", 'agents.enabled=false',
        "-c", 'features.multi_agent=false',
        "-c", 'apps={}',
        "-c", 'features.apps=false',
        "-c", 'apps._default.enabled=false',
        "-c", 'features.hooks=false',
        "-c", 'features.skill_mcp_dependency_install=false',
        "-c", 'features.remote_plugin=false',
        "-c", 'features.plugins=false',
        "-c", 'features.browser_use=false',
        "-c", 'features.browser_use_external=false',
        "-c", 'features.computer_use=false',
        "-c", 'features.image_generation=false',
        "-c", 'web_search="disabled"',
        "-c", 'tools.web_search=false',
        "-c", 'sandbox_workspace_write.network_access=false',
        "-c", 'sandbox_workspace_write.writable_roots=[]',
        "-c", 'sandbox_workspace_write.exclude_slash_tmp=true',
        "-c", 'sandbox_workspace_write.exclude_tmpdir_env_var=true',
        "-c", 'shell_environment_policy.inherit="core"',
        "-c", 'shell_environment_policy.ignore_default_excludes=false',
        "-c", 'shell_environment_policy.set={}',
        "-c", projects_override,
        "-c", 'model_reasoning_effort="%s"' % effort,
        "--cd", str(target_path),
        "--model", model,
        "-",
    ]
    return argv


def _derive_security_controls(argv: list[str], preflight: dict) -> dict:
    configs = {
        argv[index + 1] for index, value in enumerate(argv[:-1])
        if value == "-c"
    }
    hosted = {
        "features.apps=false", "apps._default.enabled=false",
        "features.hooks=false", "features.skill_mcp_dependency_install=false",
        "features.remote_plugin=false", "features.plugins=false",
        "features.browser_use=false", "features.browser_use_external=false",
        "features.computer_use=false", "features.image_generation=false",
        'web_search="disabled"', "tools.web_search=false",
    }
    rules_ignored = "--ignore-rules" in argv
    agents_disabled = {
        "agents.enabled=false", "features.multi_agent=false",
    }.issubset(configs)
    network_disabled = "sandbox_workspace_write.network_access=false" in configs
    roots_disabled = "sandbox_workspace_write.writable_roots=[]" in configs
    hosted_disabled = hosted.issubset(configs)
    projects_replaced = any(value.startswith("projects={") for value in configs)
    providers_replaced = "model_providers={}" in configs
    mcp_replaced = "mcp_servers={}" in configs
    apps_replaced = "apps={}" in configs
    user_config_ignored = "--ignore-user-config" in argv
    critical = all((
        preflight.get("config_guard_verified") is True,
        preflight.get("runtime_guard_rechecked") is True,
        preflight.get("executable_provenance_verified") is True,
        preflight.get("child_env_allowlist_verified") is True,
        preflight.get("api_key_env_scrubbed") is True,
        rules_ignored, agents_disabled, network_disabled, roots_disabled,
        hosted_disabled, projects_replaced,
        providers_replaced, mcp_replaced, apps_replaced,
        user_config_ignored,
        preflight.get("mcp_entries_absent") is True,
        'approval_policy="never"' in configs,
        'forced_login_method="chatgpt"' in configs,
        'model_provider="openai"' in configs,
    ))
    return {
        "critical_overrides_enforced": critical,
        "user_config_ignored": user_config_ignored,
        "rules_ignored": rules_ignored,
        "agents_disabled": agents_disabled,
        "network_disabled": network_disabled,
        "extra_writable_roots_disabled": roots_disabled,
        "hosted_tools_disabled": hosted_disabled,
        "mcp_servers_disabled": mcp_replaced,
        "projects_table_replaced": projects_replaced,
    }


def _artifact_snapshot(target) -> tuple[dict, bool]:
    """Return bounded SHA-256 evidence below ``target`` and scan completeness."""
    root = Path(target).resolve()
    found = {}
    scanned_bytes = 0
    try:
        paths = root.rglob("*")
        for path in paths:
            if len(found) >= MAX_ARTIFACT_SCAN_FILES:
                return found, False
            try:
                if not path.is_file() or path.name in IGNORED_ARTIFACT_NAMES:
                    continue
                rel = path.resolve().relative_to(root).as_posix()
                file_stat = path.stat()
            except (OSError, RuntimeError, ValueError):
                continue
            size = int(file_stat.st_size)
            if size < 0 or scanned_bytes + size > MAX_ARTIFACT_SCAN_BYTES:
                return found, False
            try:
                fingerprint = _stable_file_fingerprint(path)
            except OSError:
                return found, False
            scanned_bytes += size
            found[rel] = {
                "sha256": fingerprint.get("sha256"), "size": size,
            }
    except (OSError, RuntimeError):
        return found, False
    return found, True


def _changed_artifacts(before: dict, after: dict) -> list[str]:
    """Return target-relative files created or observably changed this turn."""
    return sorted(
        rel for rel, metadata in after.items()
        if rel not in before or before.get(rel) != metadata
    )


def _normalize_expected_artifacts(target, expected_artifact_paths) -> tuple[str, ...]:
    root = Path(target).resolve()
    if expected_artifact_paths is None:
        return ()
    if isinstance(expected_artifact_paths, (str, bytes, os.PathLike)):
        expected_artifact_paths = (expected_artifact_paths,)
    raw_values = list(expected_artifact_paths)
    if not raw_values or len(raw_values) > MAX_EXPECTED_ARTIFACTS:
        raise ValueError("expected artifact count is outside the portable limit")
    normalized = []
    portable_keys = set()
    total_bytes = 0
    for raw in raw_values:
        try:
            text_value = os.fspath(raw)
        except TypeError as exc:
            raise ValueError("expected artifact path must be text") from exc
        if not isinstance(text_value, str):
            raise ValueError("expected artifact path must be text")
        if not text_value:
            raise ValueError("expected artifact path is empty")
        if text_value != unicodedata.normalize("NFC", text_value):
            raise ValueError("expected artifact path must use NFC Unicode")
        encoded = text_value.encode("utf-8")
        total_bytes += len(encoded)
        if (len(encoded) > MAX_EXPECTED_PATH_BYTES or
                total_bytes > MAX_EXPECTED_TOTAL_PATH_BYTES):
            raise ValueError("expected artifact path bytes exceed the portable limit")
        if (any(character in '<>:"|\\' for character in text_value) or
                any(character in "*?[]{}" for character in text_value) or
                any(ord(character) < 32 or ord(character) == 127
                    for character in text_value)):
            raise ValueError("expected artifact path contains non-portable characters")
        pieces = text_value.split("/")
        if any(not piece or piece in (".", "..") for piece in pieces):
            raise ValueError("expected artifact path has an unsafe segment")
        for piece in pieces:
            if piece.endswith((".", " ")):
                raise ValueError("expected artifact segment has a trailing dot or space")
            if len(piece.encode("utf-8")) > 255:
                raise ValueError("expected artifact segment exceeds 255 bytes")
            reserved_stem = piece.split(".", 1)[0].casefold()
            if reserved_stem in WINDOWS_RESERVED_NAMES:
                raise ValueError("expected artifact uses a reserved Windows name")
        supplied = Path(text_value)
        if supplied.is_absolute():
            raise ValueError("expected artifact path must be target-relative")
        # Keep the caller's already-validated lexical path.  Resolving here
        # would silently turn an existing link/junction into its target and
        # evade the component-level reparse rejection in the snapshotter.
        relative = "/".join(pieces)
        ignored_names = {name.casefold() for name in IGNORED_ARTIFACT_NAMES}
        if (relative in ("", ".") or
                Path(relative).name.casefold() in ignored_names):
            raise ValueError("expected artifact path is not an eligible file")
        portable_key = unicodedata.normalize("NFC", relative).casefold()
        if portable_key in portable_keys:
            raise ValueError("expected artifacts contain a case-equivalent duplicate")
        portable_keys.add(portable_key)
        normalized.append(relative)
    return tuple(sorted(normalized, key=lambda value: value.casefold()))


def _is_reparse(stat_result) -> bool:
    return bool(getattr(stat_result, "st_file_attributes", 0) & 0x00000400)


def _artifact_components_safe(root: Path, relative: str) -> bool:
    current = root
    parts = Path(relative).parts
    for index, part in enumerate(parts):
        current = current / part
        try:
            entry = current.lstat()
        except FileNotFoundError:
            return True
        except OSError:
            return False
        if stat.S_ISLNK(entry.st_mode) or _is_reparse(entry):
            return False
        if index < len(parts) - 1 and not stat.S_ISDIR(entry.st_mode):
            return False
    return True


def _artifact_file_evidence(root: Path, relative: str):
    path = root / relative
    if not _artifact_components_safe(root, relative):
        raise OSError("expected artifact traverses a symlink or reparse point")
    try:
        path_stat = path.lstat()
    except FileNotFoundError:
        return None
    if (stat.S_ISLNK(path_stat.st_mode) or _is_reparse(path_stat) or
            not stat.S_ISREG(path_stat.st_mode)):
        raise OSError("expected artifact is not a plain regular file")
    handle = _open_guarded_file(path)
    with handle:
        before = os.fstat(handle.fileno())
        identity = (int(before.st_dev), int(before.st_ino))
        if identity != (int(path_stat.st_dev), int(path_stat.st_ino)):
            raise OSError("expected artifact identity changed before hashing")
        if int(before.st_nlink) != 1:
            raise OSError("expected artifact is a hard-link alias")
        size = int(before.st_size)
        if size < 0 or size > MAX_ARTIFACT_BYTES:
            raise OSError("expected artifact exceeds the byte limit")
        handle.seek(0)
        digest = hashlib.sha256()
        remaining = size
        while remaining:
            block = handle.read(min(1024 * 1024, remaining))
            if not block:
                raise OSError("expected artifact ended during hashing")
            digest.update(block)
            remaining -= len(block)
        if handle.read(1):
            raise OSError("expected artifact grew during hashing")
        after = os.fstat(handle.fileno())
        stable = (
            int(before.st_dev), int(before.st_ino), int(before.st_size),
            int(before.st_mtime_ns), int(before.st_nlink),
        ) == (
            int(after.st_dev), int(after.st_ino), int(after.st_size),
            int(after.st_mtime_ns), int(after.st_nlink),
        )
        if not stable:
            raise OSError("expected artifact changed while hashing")
    final_stat = path.lstat()
    if ((int(final_stat.st_dev), int(final_stat.st_ino)) != identity or
            int(final_stat.st_size) != size or
            int(final_stat.st_mtime_ns) != int(after.st_mtime_ns) or
            int(final_stat.st_nlink) != 1 or
            stat.S_ISLNK(final_stat.st_mode) or _is_reparse(final_stat) or
            not _artifact_components_safe(root, relative)):
        raise OSError("expected artifact identity changed after hashing")
    return {
        "sha256": digest.hexdigest(), "size": size,
        "device": identity[0], "inode": identity[1],
    }


def _expected_artifact_snapshot(
        target, expected_paths, expected_root_identity=None) -> tuple[dict, bool]:
    root = Path(target).resolve()
    if (expected_root_identity is not None and
            not _workspace_root_matches(root, expected_root_identity)):
        return {}, False
    snapshot = {}
    identities = set()
    total_bytes = 0
    for relative in expected_paths:
        try:
            evidence = _artifact_file_evidence(root, relative)
        except (OSError, RuntimeError, ValueError):
            return snapshot, False
        if evidence is not None:
            identity = (evidence["device"], evidence["inode"])
            if identity in identities:
                return snapshot, False
            identities.add(identity)
            total_bytes += int(evidence["size"])
            if total_bytes > MAX_ARTIFACT_TOTAL_BYTES:
                return snapshot, False
        snapshot[relative] = evidence
    if (expected_root_identity is not None and
            not _workspace_root_matches(root, expected_root_identity)):
        return snapshot, False
    return snapshot, True


def _tool_error_count(stderr: str) -> int:
    """Count native Codex tool-router errors without inspecting answer prose."""
    return sum(
        1 for line in (stderr or "").splitlines()
        if re.search(r"\bERROR\s+codex_core::tools::router:\s+error=", line)
    )


def _bounded_usage(value) -> tuple[int, bool]:
    if value is None:
        return 0, True
    if isinstance(value, bool) or not isinstance(value, int):
        return 0, False
    if value < 0 or value > MAX_NATIVE_TOKEN_COUNT:
        return 0, False
    return int(value), True


def parse_jsonl(stdout: str) -> dict:
    """Parse stable Codex events without treating answer text as error metadata."""
    malformed = 0
    event_count = 0
    input_bytes = 0
    limits_exceeded = False
    thread_id = None
    last_message = ""
    usage = {}
    failures = []
    completed = False
    # StringIO avoids splitlines() duplicating the entire already-capped native
    # stream. Per-event and event-count limits apply before retaining any JSON.
    for raw_line in io.StringIO(stdout or ""):
        line_bytes = len(raw_line.encode("utf-8", errors="replace"))
        input_bytes += line_bytes
        if (input_bytes > MAX_NATIVE_STDOUT_BYTES or
                line_bytes > MAX_NATIVE_EVENT_BYTES or
                event_count >= MAX_NATIVE_EVENT_COUNT):
            limits_exceeded = True
            break
        line = raw_line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            malformed += 1
            continue
        if not isinstance(obj, dict):
            continue
        event_count += 1
        kind = obj.get("type")
        if kind == "thread.started" and isinstance(obj.get("thread_id"), str):
            thread_id = obj["thread_id"]
        elif kind == "item.completed":
            item = obj.get("item") or {}
            if (isinstance(item, dict) and item.get("type") == "agent_message"
                    and isinstance(item.get("text"), str) and item["text"].strip()):
                last_message = item["text"].strip()
        elif kind == "turn.completed":
            completed = True
            if isinstance(obj.get("usage"), dict):
                usage = obj["usage"]
        elif kind in ("turn.failed", "error"):
            err = obj.get("error")
            for value in (
                obj.get("message"), obj.get("detail"),
                err.get("message") if isinstance(err, dict) else err,
                err.get("code") if isinstance(err, dict) else None,
            ):
                if isinstance(value, str) and value.strip():
                    failures.append(value.strip())

    if limits_exceeded:
        failures.append("Codex native protocol exceeded its event-memory contract")

    normalized_usage = {}
    usage_valid = True
    for key in USAGE_KEYS:
        normalized_usage[key], valid = _bounded_usage(usage.get(key))
        usage_valid = usage_valid and valid
    if not usage_valid:
        failures.append("Codex native usage contained an invalid token count")
    return {
        # A completed structured turn remains authoritative even if a CLI build
        # writes an informational non-JSON line to stdout. Preserve the count in
        # the receipt for diagnostics; do not discard a paid answer because of it.
        "ok": bool(last_message) and completed and not failures and usage_valid,
        "text": last_message,
        "thread_id": thread_id,
        "usage": normalized_usage,
        "usage_valid": usage_valid,
        "event_count": event_count,
        "malformed_count": malformed,
        "limits_exceeded": limits_exceeded,
        "failure_detail": "\n".join(failures)[:2000],
    }


def classify_failure(stderr: str, parsed: dict, exit_code,
                     timed_out=False, aborted=False) -> str:
    """Classify from stderr + structured failure events, never answer/usage JSON."""
    if aborted:
        return "aborted"
    if timed_out:
        return "timeout"
    if parsed.get("limits_exceeded"):
        return "protocol_limit_exceeded"
    if parsed.get("ok") and exit_code == 0:
        return "success"
    detail = "%s\n%s" % (stderr or "", parsed.get("failure_detail") or "")
    if re.search(r"usage limit|rate limit|quota|resource exhausted|too many requests|\b429\b",
                 detail, re.I):
        return "usage_limit"
    if re.search(r"not logged in|authentication|unauthorized|forbidden|\b401\b|\b403\b",
                 detail, re.I):
        return "auth_error"
    if exit_code not in (0, None):
        return "cli_error"
    if parsed.get("text"):
        return "protocol_error"
    return "no_reply"


def build_receipt(*, status: str, prompt: str, sandbox: str, preflight: dict,
                   parsed=None, exit_code=None, error=None, timed_out=False,
                   aborted=False, seat_started=False, model=CODEX_MODEL,
                   effort=CODEX_EFFORT, artifact_paths=None,
                   artifact_hashes=None, expected_artifact_paths=None,
                   artifact_contract_verified=False,
                   artifact_mutation_verified=False, artifact_evidence=None,
                   artifact_scan_complete=True, tool_error_count=0,
                   tree_kill_verified=None, output_drain_verified=None,
                   process_group_kill_verified=None,
                   output_limits_verified=None, output_eof_verified=None,
                   stdin_write_verified=None, stdin_close_verified=None,
                   output_overflow_kind=None, native_stdout_bytes=0,
                   native_stderr_bytes=0) -> dict:
    """Build the durable whitelisted receipt; requested and observed stay distinct."""
    parsed = parsed or {}
    raw_usage = parsed.get("usage") or {}
    normalized_usage = {}
    for key in USAGE_KEYS:
        normalized_usage[key], _valid = _bounded_usage(raw_usage.get(key))
    executable_fingerprint = preflight.get("executable_fingerprint") or {}
    # ``artifact_contract_verified`` is retained as a compatibility spelling,
    # but both receipt fields deliberately carry the same narrow mutation fact.
    artifact_mutated = bool(artifact_mutation_verified)
    receipt = {
        "family_requested": "chatgpt",
        "backend_requested": "chatgpt",
        "transport_requested": "codex-cli",
        "transport_actual": preflight.get("transport_actual"),
        "executable_path": preflight.get("executable_path"),
        "executable_sha256": executable_fingerprint.get("sha256"),
        "executable_provenance_verified": bool(
            preflight.get("executable_provenance_verified")),
        "executable_provenance_kind": preflight.get("executable_provenance_kind"),
        "executable_signer_subject": preflight.get(
            "executable_signer_subject"),
        "executable_signer_certificate_sha256": preflight.get(
            "executable_signer_certificate_sha256"),
        "signer_image_binding_verified": bool(
            preflight.get("signer_image_binding_verified")),
        "signature_revocation_freshness": preflight.get(
            "signature_revocation_freshness"),
        "executable_handle_guarded_through_spawn": bool(
            preflight.get("executable_handle_guarded_through_spawn")),
        "preexecution_child_image_attested": bool(
            preflight.get("preexecution_child_image_attested")),
        "cli_version": preflight.get("cli_version"),
        "auth_kind": preflight.get("auth_kind"),
        "auth_probe_at": preflight.get("auth_probe_at"),
        "subscription_auth": preflight.get("subscription_auth"),
        "requested_model": model,
        "requested_effort": effort,
        "requested_orchestration_mode": "ultra" if effort == "ultra" else "single",
        "orchestration_mode_served": None,
        "model_capability_verified": bool(preflight.get("model_capability_verified")),
        "ultra_capability_verified": bool(preflight.get("ultra_capability_verified")),
        "sandbox_requested": sandbox,
        "approval_policy_requested": "never",
        "model_provider_requested": "openai",
        "codex_home": preflight.get("codex_home"),
        # --ignore-user-config means config.toml is neither loaded nor hashed as
        # an execution input, even when the saved-auth directory contains one.
        "config_sha256": None,
        "user_config_loaded": False,
        "user_config_ignored": bool(preflight.get("user_config_ignored")),
        "critical_overrides_enforced": bool(
            preflight.get("critical_overrides_enforced")),
        "config_guard_verified": bool(preflight.get("config_guard_verified")),
        "runtime_guard_rechecked": bool(preflight.get("runtime_guard_rechecked")),
        "child_env_allowlist_verified": bool(
            preflight.get("child_env_allowlist_verified")),
        "rules_ignored": bool(preflight.get("rules_ignored")),
        "agents_disabled": bool(preflight.get("agents_disabled")),
        "network_disabled": bool(preflight.get("network_disabled")),
        "extra_writable_roots_disabled": bool(
            preflight.get("extra_writable_roots_disabled")),
        "hosted_tools_disabled": bool(preflight.get("hosted_tools_disabled")),
        "mcp_servers_disabled": bool(preflight.get("mcp_servers_disabled")),
        "projects_table_replaced": bool(preflight.get("projects_table_replaced")),
        "thread_id": parsed.get("thread_id"),
        "usage": normalized_usage,
        "exit_code": exit_code,
        "status": status,
        "timed_out": bool(timed_out),
        "aborted": bool(aborted),
        "tree_kill_verified": (None if tree_kill_verified is None
                               else bool(tree_kill_verified)),
        "process_group_kill_verified": (
            None if process_group_kill_verified is None
            else bool(process_group_kill_verified)),
        "output_drain_verified": (None if output_drain_verified is None
                                   else bool(output_drain_verified)),
        "output_limits_verified": (None if output_limits_verified is None
                                    else bool(output_limits_verified)),
        "output_eof_verified": (None if output_eof_verified is None
                                 else bool(output_eof_verified)),
        "stdin_write_verified": (None if stdin_write_verified is None
                                  else bool(stdin_write_verified)),
        "stdin_close_verified": (None if stdin_close_verified is None
                                  else bool(stdin_close_verified)),
        "output_overflow_kind": (
            str(output_overflow_kind) if output_overflow_kind in (
                "stdout", "stderr", "aggregate") else None),
        "native_stdout_bytes": min(
            MAX_NATIVE_STDOUT_BYTES + 1,
            max(0, int(native_stdout_bytes or 0))),
        "native_stderr_bytes": min(
            MAX_NATIVE_STDERR_BYTES + 1,
            max(0, int(native_stderr_bytes or 0))),
        "preflight_probe_count": max(
            0, int(preflight.get("preflight_probe_count") or 0)),
        "preflight_containment_kind": preflight.get(
            "preflight_containment_kind"),
        "preflight_complete_tree_containment": bool(
            preflight.get("preflight_complete_tree_containment")),
        "preflight_no_inference_verified": bool(
            preflight.get("preflight_no_inference_verified")),
        "preflight_no_network_intent_verified": bool(
            preflight.get("preflight_no_network_intent_verified")),
        "preflight_output_limits_verified": bool(
            preflight.get("preflight_output_limits_verified")),
        "preflight_output_drain_verified": bool(
            preflight.get("preflight_output_drain_verified")),
        "preflight_root_exit_verified": bool(
            preflight.get("preflight_root_exit_verified")),
        "preflight_windows_job_policy_verified": bool(
            preflight.get("preflight_windows_job_policy_verified")),
        "preflight_windows_job_assignment_verified": bool(
            preflight.get("preflight_windows_job_assignment_verified")),
        "preflight_windows_job_membership_verified": bool(
            preflight.get("preflight_windows_job_membership_verified")),
        "preflight_windows_process_handle_verified": bool(
            preflight.get("preflight_windows_process_handle_verified")),
        "preflight_windows_primary_thread_verified": bool(
            preflight.get("preflight_windows_primary_thread_verified")),
        "preflight_windows_process_resumed": bool(
            preflight.get("preflight_windows_process_resumed")),
        "preflight_windows_job_empty_verified": bool(
            preflight.get("preflight_windows_job_empty_verified")),
        "preflight_process_group_kill_verified": (
            None if preflight.get("preflight_process_group_kill_verified") is None
            else bool(preflight.get("preflight_process_group_kill_verified"))),
        "containment_kind": preflight.get("containment_kind"),
        "complete_tree_containment": bool(
            preflight.get("complete_tree_containment")),
        "windows_job_policy_verified": bool(
            preflight.get("windows_job_policy_verified")),
        "windows_job_assignment_verified": bool(
            preflight.get("windows_job_assignment_verified")),
        "windows_job_membership_verified": bool(
            preflight.get("windows_job_membership_verified")),
        "windows_process_handle_verified": bool(
            preflight.get("windows_process_handle_verified")),
        "windows_primary_thread_verified": bool(
            preflight.get("windows_primary_thread_verified")),
        "windows_process_resumed": bool(
            preflight.get("windows_process_resumed")),
        "windows_execution_possible": bool(
            preflight.get("windows_execution_possible")),
        "windows_job_empty_verified": bool(
            preflight.get("windows_job_empty_verified")),
        "root_exit_verified": bool(preflight.get("root_exit_verified")),
        "seat_started": bool(seat_started),
        "fallback_from": None,
        "fallback_to": None,
        "cross_model": None,
        "billing_mode": ("subscription"
                         if seat_started and preflight.get("subscription_auth") is True
                         else None),
        "cost_state": ("subscription_covered"
                       if seat_started and preflight.get("subscription_auth") is True
                       else "no_seat_started"),
        "model_served": None,
        "reasoning_served": None,
        "model_attested": False,
        "degraded": True,
        "api_key_env_scrubbed": bool(preflight.get("api_key_env_scrubbed")),
        "prompt_sha256": hashlib.sha256((prompt or "").encode("utf-8")).hexdigest(),
        "event_count": int(parsed.get("event_count") or 0),
        "malformed_count": int(parsed.get("malformed_count") or 0),
        "tool_error_count": max(0, int(tool_error_count or 0)),
        "artifact_write_observed": bool(artifact_paths),
        "artifact_scan_complete": bool(artifact_scan_complete),
        "artifact_paths": list(artifact_paths or [])[:100],
        "expected_artifact_paths": list(expected_artifact_paths or [])[:100],
        "artifact_contract_verified": artifact_mutated,
        # Both names mean only "the named safe files were stably hash-mutated";
        # neither claims that their content is correct or useful.
        "artifact_mutation_verified": artifact_mutated,
        "artifact_hashes": {
            str(key): str(value) for key, value in sorted(
                dict(artifact_hashes or {}).items())
        },
        "artifact_evidence": {
            str(key): {
                "sha256": str(value.get("sha256")),
                "size": int(value.get("size") or 0),
                "device": int(value.get("device") or 0),
                "inode": int(value.get("inode") or 0),
            }
            for key, value in sorted(dict(artifact_evidence or {}).items())
        },
    }
    if error:
        receipt["error"] = str(error)[:500]
    return receipt


def normalized_result(text: str, receipt: dict, duration_ms: int,
                      is_error: bool) -> dict:
    """Render the one envelope consumed by Anchor's existing stream reader."""
    receipt = dict(receipt or {})
    receipt["duration_ms"] = max(0, int(duration_ms or 0))
    return {
        "type": "result",
        "subtype": "error" if is_error else "success",
        "is_error": bool(is_error),
        "result": text or "",
        "usage": dict(receipt.get("usage") or {}),
        "session_id": receipt.get("thread_id"),
        "duration_ms": receipt["duration_ms"],
        "total_cost_usd": None,
        "billing_mode": receipt.get("billing_mode"),
        "cost_state": receipt.get("cost_state"),
        "model_receipt": receipt,
    }


class _WindowsJob:
    """Verified kill-on-close Job Object for one suspended Codex process."""

    CREATE_SUSPENDED = 0x00000004
    KILL_ON_CLOSE = 0x00002000
    BREAKAWAY_FLAGS = 0x00000800 | 0x00001000

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        self.ctypes = ctypes
        self.wintypes = wintypes
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.handle = None
        self.assigned = False
        self.membership_verified = False
        self.process_handle_verified = False
        self.primary_thread_verified = False
        self.resumed = False
        self.execution_possible = False
        self.policy_verified = False
        self.empty_verified = False
        self.closed = False

        class BASIC_LIMIT(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class EXTENDED_LIMIT(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BASIC_LIMIT), ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        class ACCOUNTING(ctypes.Structure):
            _fields_ = [
                ("TotalUserTime", ctypes.c_longlong),
                ("TotalKernelTime", ctypes.c_longlong),
                ("ThisPeriodTotalUserTime", ctypes.c_longlong),
                ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
                ("TotalPageFaultCount", wintypes.DWORD),
                ("TotalProcesses", wintypes.DWORD),
                ("ActiveProcesses", wintypes.DWORD),
                ("TotalTerminatedProcesses", wintypes.DWORD),
            ]

        class PID_LIST_ONE(ctypes.Structure):
            _fields_ = [
                ("NumberOfAssignedProcesses", wintypes.DWORD),
                ("NumberOfProcessIdsInList", wintypes.DWORD),
                ("ProcessIdList", ctypes.c_size_t * 1),
            ]

        class THREADENTRY32(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ThreadID", wintypes.DWORD),
                ("th32OwnerProcessID", wintypes.DWORD),
                ("tpBasePri", wintypes.LONG), ("tpDeltaPri", wintypes.LONG),
                ("dwFlags", wintypes.DWORD),
            ]

        self.EXTENDED_LIMIT = EXTENDED_LIMIT
        self.ACCOUNTING = ACCOUNTING
        self.PID_LIST_ONE = PID_LIST_ONE
        self.THREADENTRY32 = THREADENTRY32
        self._declare()
        handle = self.kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
        self.handle = handle
        try:
            limits = EXTENDED_LIMIT()
            limits.BasicLimitInformation.LimitFlags = self.KILL_ON_CLOSE
            if not self.kernel32.SetInformationJobObject(
                    handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                raise OSError(ctypes.get_last_error(), "SetInformationJobObject failed")
            observed = EXTENDED_LIMIT()
            if not self.kernel32.QueryInformationJobObject(
                    handle, 9, ctypes.byref(observed), ctypes.sizeof(observed), None):
                raise OSError(ctypes.get_last_error(), "QueryInformationJobObject failed")
            flags = int(observed.BasicLimitInformation.LimitFlags)
            if not flags & self.KILL_ON_CLOSE or flags & self.BREAKAWAY_FLAGS:
                raise OSError("unsafe Windows Job Object policy")
            self.policy_verified = True
        except BaseException:
            self.close()
            raise

    def _declare(self):
        c = self.ctypes
        w = self.wintypes
        k = self.kernel32
        # Explicit HANDLE-width prototypes are security-critical on 64-bit
        # Windows.  ctypes otherwise assumes C ``int`` arguments and can
        # truncate a verified process or Job Object handle.
        k.CreateJobObjectW.argtypes = [c.c_void_p, w.LPCWSTR]
        k.CreateJobObjectW.restype = w.HANDLE
        k.SetInformationJobObject.argtypes = [
            w.HANDLE, c.c_int, c.c_void_p, w.DWORD]
        k.SetInformationJobObject.restype = w.BOOL
        k.QueryInformationJobObject.argtypes = [
            w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.POINTER(w.DWORD)]
        k.QueryInformationJobObject.restype = w.BOOL
        k.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        k.AssignProcessToJobObject.restype = w.BOOL
        k.IsProcessInJob.argtypes = [w.HANDLE, w.HANDLE, c.POINTER(w.BOOL)]
        k.IsProcessInJob.restype = w.BOOL
        k.TerminateJobObject.argtypes = [w.HANDLE, w.UINT]
        k.TerminateJobObject.restype = w.BOOL
        k.TerminateProcess.argtypes = [w.HANDLE, w.UINT]
        k.TerminateProcess.restype = w.BOOL
        k.GetProcessId.argtypes = [w.HANDLE]
        k.GetProcessId.restype = w.DWORD
        k.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
        k.CreateToolhelp32Snapshot.restype = w.HANDLE
        k.Thread32First.argtypes = [w.HANDLE, c.c_void_p]
        k.Thread32First.restype = w.BOOL
        k.Thread32Next.argtypes = [w.HANDLE, c.c_void_p]
        k.Thread32Next.restype = w.BOOL
        k.OpenThread.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        k.OpenThread.restype = w.HANDLE
        k.GetProcessIdOfThread.argtypes = [w.HANDLE]
        k.GetProcessIdOfThread.restype = w.DWORD
        k.ResumeThread.argtypes = [w.HANDLE]
        k.ResumeThread.restype = w.DWORD
        k.CloseHandle.argtypes = [w.HANDLE]
        k.CloseHandle.restype = w.BOOL

    def _process_handle(self, proc):
        raw = getattr(proc, "_handle", None)
        try:
            handle = int(raw)
        except (TypeError, ValueError):
            raise OSError("Popen did not expose a verifiable process handle")
        if not handle or int(self.kernel32.GetProcessId(handle)) != int(proc.pid):
            raise OSError("Popen process handle identity mismatch")
        self.process_handle_verified = True
        return handle

    def _job_pid(self):
        payload = self.PID_LIST_ONE()
        if not self.kernel32.QueryInformationJobObject(
                self.handle, 3, self.ctypes.byref(payload),
                self.ctypes.sizeof(payload), None):
            raise OSError(self.ctypes.get_last_error(), "job PID query failed")
        if (int(payload.NumberOfAssignedProcesses) != 1 or
                int(payload.NumberOfProcessIdsInList) != 1):
            raise OSError("suspended Job Object membership is not singular")
        return int(payload.ProcessIdList[0])

    def _primary_thread(self, pid):
        invalid = self.ctypes.c_void_p(-1).value
        snapshot = self.kernel32.CreateToolhelp32Snapshot(0x00000004, 0)
        if snapshot in (None, invalid):
            raise OSError(self.ctypes.get_last_error(), "thread snapshot failed")
        tids = []
        entry = self.THREADENTRY32()
        entry.dwSize = self.ctypes.sizeof(entry)
        try:
            ok = self.kernel32.Thread32First(snapshot, self.ctypes.byref(entry))
            while ok:
                if int(entry.th32OwnerProcessID) == int(pid):
                    tids.append(int(entry.th32ThreadID))
                ok = self.kernel32.Thread32Next(snapshot, self.ctypes.byref(entry))
        finally:
            self.kernel32.CloseHandle(snapshot)
        if len(tids) != 1:
            raise OSError("suspended Codex process did not have exactly one thread")
        thread = self.kernel32.OpenThread(0x0002 | 0x0800, False, tids[0])
        if not thread:
            raise OSError(self.ctypes.get_last_error(), "OpenThread failed")
        if int(self.kernel32.GetProcessIdOfThread(thread)) != int(pid):
            self.kernel32.CloseHandle(thread)
            raise OSError("primary thread owner mismatch")
        self.primary_thread_verified = True
        return thread

    def assign_and_resume(self, proc, cancel_before_resume=False):
        process = self._process_handle(proc)
        if not self.kernel32.AssignProcessToJobObject(self.handle, process):
            raise OSError(self.ctypes.get_last_error(), "AssignProcessToJobObject failed")
        self.assigned = True
        membership = self.wintypes.BOOL(False)
        if (not self.kernel32.IsProcessInJob(
                process, self.handle, self.ctypes.byref(membership)) or
                not membership.value or self._job_pid() != int(proc.pid)):
            raise OSError("Windows Job Object membership could not be verified")
        self.membership_verified = True
        thread = self._primary_thread(proc.pid)
        try:
            cancelled = (bool(cancel_before_resume())
                         if callable(cancel_before_resume)
                         else bool(cancel_before_resume))
            if cancelled:
                return False
            previous = int(self.kernel32.ResumeThread(thread))
            if previous == 0:
                # The primary thread was already runnable. The containment
                # transition failed, but code may have run and must be billed
                # and terminated as a started seat.
                self.execution_possible = True
                raise OSError("ResumeThread found an already-runnable process")
            if previous != 1:
                raise OSError("ResumeThread did not observe exactly one suspension")
            self.execution_possible = True
            self.resumed = True
            return True
        finally:
            self.kernel32.CloseHandle(thread)

    def active_count(self):
        accounting = self.ACCOUNTING()
        if not self.kernel32.QueryInformationJobObject(
                self.handle, 1, self.ctypes.byref(accounting),
                self.ctypes.sizeof(accounting), None):
            raise OSError(self.ctypes.get_last_error(), "job accounting query failed")
        return int(accounting.ActiveProcesses)

    def terminate_verified(self, proc, timeout_seconds=5.0):
        if not self.assigned:
            return False
        if not self.kernel32.TerminateJobObject(self.handle, 0xC000013A):
            return False
        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        while time.monotonic() <= deadline:
            try:
                empty = self.active_count() == 0
            except OSError:
                return False
            if empty and _proc_dead(proc, timeout_seconds=0):
                self.empty_verified = True
                return True
            time.sleep(0.05)
        return False

    def abort_suspended(self, proc):
        if self.assigned:
            return self.terminate_verified(proc)
        try:
            process = self._process_handle(proc)
            terminated = bool(self.kernel32.TerminateProcess(process, 0xC000013A))
        except OSError:
            return False
        return bool(terminated and _proc_dead(proc))

    def verify_empty(self, timeout_seconds=2.0):
        # Job accounting can settle just after WaitForSingleObject/Popen reap.
        # Bound that legitimate kernel lag rather than stamping an ordinary
        # exit as a descendant straggler from one instantaneous query.
        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        while True:
            try:
                self.empty_verified = self.active_count() == 0
            except OSError:
                self.empty_verified = False
                return False
            if self.empty_verified or time.monotonic() >= deadline:
                return self.empty_verified
            time.sleep(0.02)

    def close(self):
        if self.closed:
            return True
        if self.handle and not self.kernel32.CloseHandle(self.handle):
            raise OSError(self.ctypes.get_last_error(), "CloseHandle(Job) failed")
        self.closed = True
        self.handle = None
        return True


def _bounded_pipe_exchange(
        proc, input_text, timeout_seconds, *, terminate_fn,
        stdout_limit, stderr_limit, aggregate_limit,
        abort_requested=None, drain_timeout=PIPE_DRAIN_TIMEOUT_SECONDS) -> dict:
    """Write stdin and drain both binary pipes concurrently under hard caps.

    Readers continue discarding after a cap is crossed so termination cannot
    deadlock on a full inherited pipe. A cap crossing is always returned as a
    failure fact; captured/truncated bytes can never be parsed as success.
    """
    limits = {
        "stdout": int(stdout_limit), "stderr": int(stderr_limit),
    }
    aggregate_limit = int(aggregate_limit)
    if (any(value <= 0 for value in limits.values()) or aggregate_limit <= 0 or
            aggregate_limit > sum(limits.values())):
        raise ValueError("invalid bounded-pipe limits")
    stdout_pipe = getattr(proc, "stdout", None)
    stderr_pipe = getattr(proc, "stderr", None)
    stdin_pipe = getattr(proc, "stdin", None)
    if (stdout_pipe is None or stderr_pipe is None or
            not callable(getattr(stdout_pipe, "read", None)) or
            not callable(getattr(stderr_pipe, "read", None))):
        raise ValueError("bounded exchange requires readable stdout/stderr pipes")

    lock = threading.Lock()
    captured = {"stdout": bytearray(), "stderr": bytearray()}
    observed = {"stdout": 0, "stderr": 0}
    eof = {"stdout": False, "stderr": False}
    read_errors = {"stdout": None, "stderr": None}
    aggregate_captured = 0
    overflow_kind = None
    overflow_event = threading.Event()

    def _reader(name, stream):
        nonlocal aggregate_captured, overflow_kind
        try:
            while True:
                block = stream.read(PIPE_CHUNK_BYTES)
                if block in (b"", ""):
                    eof[name] = True
                    return
                if isinstance(block, str):
                    block = block.encode("utf-8", errors="replace")
                elif not isinstance(block, (bytes, bytearray)):
                    raise TypeError("pipe read returned a non-byte payload")
                block = bytes(block)
                with lock:
                    # Saturating counters prove a crossing without allowing an
                    # overproducing child to create unbounded receipt integers.
                    observed[name] = min(
                        limits[name] + 1, observed[name] + len(block))
                    stream_room = max(0, limits[name] - len(captured[name]))
                    aggregate_room = max(0, aggregate_limit - aggregate_captured)
                    keep = min(len(block), stream_room, aggregate_room)
                    if keep:
                        captured[name].extend(block[:keep])
                        aggregate_captured += keep
                    if keep != len(block) and overflow_kind is None:
                        overflow_kind = (
                            name if stream_room < len(block) else "aggregate")
                        overflow_event.set()
        except BaseException as exc:
            read_errors[name] = "%s: %s" % (
                type(exc).__name__, str(exc)[:200])

    stdin_write_verified = input_text is None
    stdin_close_verified = input_text is None
    writer_error = None
    if input_text is None and stdin_pipe is not None:
        try:
            stdin_pipe.close()
            stdin_close_verified = True
        except (BrokenPipeError, OSError, ValueError):
            stdin_close_verified = False

    def _writer():
        nonlocal stdin_write_verified, stdin_close_verified, writer_error
        try:
            if stdin_pipe is None:
                raise OSError("prompt stdin pipe is unavailable")
            payload = str(input_text).encode("utf-8")
            offset = 0
            while offset < len(payload):
                written = stdin_pipe.write(payload[offset:offset + PIPE_CHUNK_BYTES])
                if written is None:
                    written = min(PIPE_CHUNK_BYTES, len(payload) - offset)
                written = int(written)
                if written <= 0:
                    raise OSError("prompt stdin pipe stopped accepting bytes")
                offset += written
                stdin_pipe.flush()
            stdin_write_verified = offset == len(payload)
        except (BrokenPipeError, OSError, TypeError, ValueError) as exc:
            writer_error = "%s: %s" % (type(exc).__name__, str(exc)[:200])
        finally:
            if stdin_pipe is not None:
                try:
                    stdin_pipe.close()
                    stdin_close_verified = True
                except (BrokenPipeError, OSError, ValueError):
                    stdin_close_verified = False

    readers = [
        threading.Thread(target=_reader, args=("stdout", stdout_pipe),
                         name="anchor-codex-stdout", daemon=True),
        threading.Thread(target=_reader, args=("stderr", stderr_pipe),
                         name="anchor-codex-stderr", daemon=True),
    ]
    for thread in readers:
        thread.start()
    writer = None
    if input_text is not None:
        writer = threading.Thread(
            target=_writer, name="anchor-codex-stdin", daemon=True)
        writer.start()

    timed_out = False
    aborted = False
    wait_error = None
    termination_attempted = False
    termination_verified = None

    def _terminate_once():
        nonlocal termination_attempted, termination_verified
        if termination_attempted:
            return bool(termination_verified)
        termination_attempted = True
        try:
            termination_verified = bool(terminate_fn())
        except BaseException:
            termination_verified = False
        return bool(termination_verified)

    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    try:
        while True:
            if overflow_event.is_set():
                _terminate_once()
                break
            if callable(abort_requested) and bool(abort_requested()):
                aborted = True
                _terminate_once()
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                _terminate_once()
                break
            try:
                proc.wait(timeout=min(0.05, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
    except (KeyboardInterrupt, SystemExit):
        aborted = True
        _terminate_once()
    except BaseException as exc:
        wait_error = "%s: %s" % (type(exc).__name__, str(exc)[:200])
        _terminate_once()

    root_exit_verified = _proc_dead(proc, timeout_seconds=drain_timeout)

    drain_deadline = time.monotonic() + max(0.0, float(drain_timeout))
    for thread in ([writer] if writer is not None else []) + readers:
        remaining = max(0.0, drain_deadline - time.monotonic())
        thread.join(remaining)
    if any(thread.is_alive() for thread in readers):
        # A descendant can keep a copied pipe handle open after the root exits.
        # Terminate the owned tree, then give EOF one final bounded chance.
        _terminate_once()
        second_deadline = time.monotonic() + max(0.2, float(drain_timeout))
        for thread in readers:
            thread.join(max(0.0, second_deadline - time.monotonic()))
        if any(thread.is_alive() for thread in readers):
            for stream in (stdout_pipe, stderr_pipe):
                try:
                    stream.close()
                except (OSError, ValueError):
                    pass
            for thread in readers:
                thread.join(0.2)
    if writer is not None and writer.is_alive():
        _terminate_once()
        # Avoid BufferedWriter.close() lock contention with a thread blocked in
        # write/flush. Releasing the underlying descriptor after child death
        # makes that writer fail closed and lets its finally block complete.
        if stdin_pipe is not None:
            try:
                os.close(stdin_pipe.fileno())
            except (OSError, ValueError):
                pass
        writer.join(max(0.2, float(drain_timeout)))

    writer_stopped = writer is None or not writer.is_alive()
    stdin_write_verified = bool(stdin_write_verified and writer_stopped)
    stdin_close_verified = bool(stdin_close_verified and writer_stopped)
    output_eof_verified = bool(
        eof["stdout"] and eof["stderr"] and
        not any(thread.is_alive() for thread in readers))
    output_drain_verified = bool(
        output_eof_verified and not any(read_errors.values()))
    return {
        "stdout": bytes(captured["stdout"]).decode("utf-8", errors="replace"),
        "stderr": bytes(captured["stderr"]).decode("utf-8", errors="replace"),
        "stdout_bytes": int(observed["stdout"]),
        "stderr_bytes": int(observed["stderr"]),
        "overflow_kind": overflow_kind,
        "output_limits_verified": overflow_kind is None,
        "output_eof_verified": output_eof_verified,
        "output_drain_verified": output_drain_verified,
        "stdin_write_verified": stdin_write_verified,
        "stdin_close_verified": stdin_close_verified,
        "timed_out": timed_out,
        "aborted": aborted,
        "wait_error": wait_error,
        "writer_error": writer_error,
        "read_errors": dict(read_errors),
        "termination_attempted": termination_attempted,
        "termination_verified": termination_verified,
        "root_exit_verified": bool(root_exit_verified),
    }


def _run_preflight_probe(
        cmd, args, child_env, timeout_seconds, *,
        popen_impl=subprocess.Popen, platform_name=None,
        windows_job_factory=None) -> dict:
    """Run one exact no-model probe with bounded I/O and honest containment."""
    runtime_platform = os.name if platform_name is None else str(platform_name)
    canonical = Path(str(cmd)).resolve(strict=False)
    argv = [str(canonical)] + [str(value) for value in args]
    evidence = {
        "preflight_containment_kind": (
            "windows_job" if runtime_platform == "nt"
            else "posix_process_group_degraded"),
        "preflight_complete_tree_containment": False,
        "preflight_no_inference_verified": _preflight_args_are_local_only(args),
        "preflight_no_network_intent_verified": _preflight_args_are_local_only(args),
        "preflight_output_limits_verified": False,
        "preflight_output_drain_verified": False,
        "preflight_root_exit_verified": False,
        "preflight_windows_job_policy_verified": False,
        "preflight_windows_job_assignment_verified": False,
        "preflight_windows_job_membership_verified": False,
        "preflight_windows_process_handle_verified": False,
        "preflight_windows_primary_thread_verified": False,
        "preflight_windows_process_resumed": False,
        "preflight_windows_job_empty_verified": False,
        "preflight_process_group_kill_verified": None,
    }
    if (not evidence["preflight_no_inference_verified"] or
            not _minimal_env_verified(child_env, runtime_platform) or
            not canonical.is_absolute()):
        return {
            "ok": False, "status": "preflight_command_refused",
            "error": "preflight command/environment is outside the local-only contract",
            "argv": argv, "evidence": evidence,
        }
    job = None
    proc = None
    creationflags = 0
    if runtime_platform == "nt":
        factory = _WindowsJob if windows_job_factory is None else windows_job_factory
        try:
            job = factory()
        except BaseException as exc:
            return {
                "ok": False, "status": "preflight_containment_failed",
                "error": "preflight Job policy failed: %s" % str(exc)[:300],
                "argv": argv, "evidence": evidence,
            }
        evidence["preflight_windows_job_policy_verified"] = bool(
            getattr(job, "policy_verified", False))
        if not evidence["preflight_windows_job_policy_verified"]:
            try:
                job.close()
            except BaseException:
                pass
            return {
                "ok": False, "status": "preflight_containment_failed",
                "error": "preflight Job policy was not verified",
                "argv": argv, "evidence": evidence,
            }
        creationflags = (
            getattr(subprocess, "CREATE_SUSPENDED", _WindowsJob.CREATE_SUSPENDED) |
            getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        proc = popen_impl(
            argv, executable=str(canonical), cwd=str(canonical.parent),
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env=child_env, shell=False,
            close_fds=True, text=False, creationflags=creationflags,
            start_new_session=(runtime_platform != "nt"))
    except BaseException as exc:
        closed = True
        if job is not None:
            try:
                closed = job.close() is not False
            except BaseException:
                closed = False
        return {
            "ok": False,
            "status": ("preflight_spawn_error" if closed
                       else "preflight_cleanup_failed"),
            "error": "preflight spawn failed: %s" % str(exc)[:300],
            "argv": argv, "evidence": evidence,
        }

    if runtime_platform == "nt":
        setattr(proc, "_anchor_windows_job", job)
        try:
            resumed = bool(job.assign_and_resume(proc))
        except BaseException as exc:
            resumed = False
            assignment_error = str(exc)[:300]
        else:
            assignment_error = None
        evidence.update(
            preflight_windows_job_assignment_verified=bool(job.assigned),
            preflight_windows_job_membership_verified=bool(job.membership_verified),
            preflight_windows_process_handle_verified=bool(
                job.process_handle_verified),
            preflight_windows_primary_thread_verified=bool(
                job.primary_thread_verified),
            preflight_windows_process_resumed=bool(job.resumed),
        )
        if (not resumed or not all((
                evidence["preflight_windows_job_assignment_verified"],
                evidence["preflight_windows_job_membership_verified"],
                evidence["preflight_windows_process_handle_verified"],
                evidence["preflight_windows_primary_thread_verified"],
                evidence["preflight_windows_process_resumed"]))):
            try:
                killed = bool(job.abort_suspended(proc))
            except BaseException:
                killed = False
            exchange = _bounded_pipe_exchange(
                proc, None, PIPE_DRAIN_TIMEOUT_SECONDS,
                terminate_fn=lambda: job.abort_suspended(proc),
                stdout_limit=MAX_PREFLIGHT_STDOUT_BYTES,
                stderr_limit=MAX_PREFLIGHT_STDERR_BYTES,
                aggregate_limit=MAX_PREFLIGHT_OUTPUT_BYTES)
            try:
                empty = bool(job.verify_empty())
            except BaseException:
                empty = False
            evidence.update(
                preflight_output_limits_verified=bool(
                    exchange["output_limits_verified"]),
                preflight_output_drain_verified=bool(
                    exchange["output_drain_verified"]),
                preflight_root_exit_verified=bool(
                    exchange["root_exit_verified"]),
                preflight_windows_job_empty_verified=empty,
            )
            try:
                closed = job.close() is not False
            except BaseException:
                closed = False
            cleanup = bool(killed and empty and closed and
                           exchange["output_drain_verified"] and
                           exchange["root_exit_verified"])
            return {
                "ok": False,
                "status": ("preflight_containment_failed" if cleanup
                           else "preflight_cleanup_failed"),
                "error": assignment_error or "preflight assignment was not verified",
                "argv": argv, "evidence": evidence,
            }
        terminate_fn = lambda: job.terminate_verified(proc)
    else:
        try:
            pgid = int(proc.pid)
        except (AttributeError, TypeError, ValueError):
            pgid = None
        terminate_fn = lambda: _kill_tree(proc, pgid, runtime_platform)

    exchange = _bounded_pipe_exchange(
        proc, None, timeout_seconds, terminate_fn=terminate_fn,
        stdout_limit=MAX_PREFLIGHT_STDOUT_BYTES,
        stderr_limit=MAX_PREFLIGHT_STDERR_BYTES,
        aggregate_limit=MAX_PREFLIGHT_OUTPUT_BYTES)
    evidence.update(
        preflight_output_limits_verified=bool(exchange["output_limits_verified"]),
        preflight_output_drain_verified=bool(exchange["output_drain_verified"]),
        preflight_root_exit_verified=bool(exchange["root_exit_verified"]),
    )
    straggler = False
    closed = True
    if runtime_platform == "nt":
        try:
            empty = bool(job.verify_empty())
        except BaseException:
            empty = False
        if not empty:
            straggler = True
            try:
                job.terminate_verified(proc)
                empty = bool(job.verify_empty())
            except BaseException:
                empty = False
        evidence["preflight_windows_job_empty_verified"] = empty
        evidence["preflight_complete_tree_containment"] = bool(
            evidence["preflight_windows_job_policy_verified"] and
            evidence["preflight_windows_job_assignment_verified"] and
            evidence["preflight_windows_job_membership_verified"] and
            evidence["preflight_windows_process_handle_verified"] and
            evidence["preflight_windows_primary_thread_verified"] and
            evidence["preflight_windows_process_resumed"] and empty and
            evidence["preflight_root_exit_verified"])
        try:
            closed = job.close() is not False
        except BaseException:
            closed = False
    else:
        group_proof = getattr(
            proc, "_anchor_process_group_kill_verified", None)
        evidence["preflight_process_group_kill_verified"] = (
            None if group_proof is None else bool(group_proof))

    degraded_kill_proven = bool(
        runtime_platform == "nt" or not exchange["termination_attempted"] or
        evidence["preflight_process_group_kill_verified"] is True)
    cleanup_ok = bool(
        exchange["output_drain_verified"] and exchange["root_exit_verified"] and
        closed and degraded_kill_proven and (runtime_platform != "nt" or
                    evidence["preflight_windows_job_empty_verified"]))
    if not cleanup_ok:
        status = "preflight_cleanup_failed"
        error = "preflight root/pipe/tree cleanup was not fully verified"
    elif exchange["overflow_kind"] is not None:
        status = "preflight_output_limit_exceeded"
        error = "preflight %s output exceeded its byte contract" % (
            exchange["overflow_kind"])
    elif exchange["timed_out"]:
        status = "preflight_timeout"
        error = "preflight probe timed out"
    elif exchange["aborted"]:
        status = "preflight_aborted"
        error = "preflight probe was cancelled"
    elif straggler:
        status = "preflight_process_tree_straggler"
        error = "preflight Job contained a descendant after root exit"
    elif exchange["wait_error"] or any(exchange["read_errors"].values()):
        status = "preflight_cleanup_failed"
        error = "preflight pipe/wait state failed closed"
    else:
        status = "ready"
        error = None
    return {
        "ok": status == "ready", "status": status, "error": error,
        "argv": argv, "returncode": getattr(proc, "returncode", None),
        "stdout": exchange["stdout"], "stderr": exchange["stderr"],
        "evidence": evidence,
    }


def _proc_dead(proc, timeout_seconds=3.0) -> bool:
    """Return true only after the direct child is observably reaped/exited."""
    try:
        if proc.poll() is not None:
            return True
    except (AttributeError, OSError):
        pass
    try:
        proc.wait(timeout=max(0.0, float(timeout_seconds)))
        return True
    except (AttributeError, OSError, subprocess.SubprocessError):
        return False


def _overflow_cleanup_verified(proc, runtime_platform, output_drain_verified,
                               tree_kill_verified,
                               process_group_kill_verified, *,
                               complete_tree_containment=False,
                               windows_job_empty_verified=False) -> bool:
    """Bind an overflow refusal to the strongest platform cleanup proof."""
    if (output_drain_verified is not True or
            not _proc_dead(proc, timeout_seconds=0)):
        return False
    if runtime_platform == "nt":
        return bool(
            tree_kill_verified is True or
            (complete_tree_containment is True and
             windows_job_empty_verified is True))
    return process_group_kill_verified is True


def _posix_group_dead(pgid, timeout_seconds=3.0) -> bool:
    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    while True:
        try:
            os.killpg(int(pgid), 0)
        except ProcessLookupError:
            return True
        except OSError as exc:
            if exc.errno == errno.ESRCH:
                return True
            return False
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)


def _kill_tree(proc, posix_pgid=None, platform_name=None) -> bool:
    """Kill and verify the owned child tree; false means containment is unknown."""
    runtime_platform = os.name if platform_name is None else str(platform_name)
    pid = getattr(proc, "pid", None)
    if not pid:
        return False
    if runtime_platform == "nt":
        job = getattr(proc, "_anchor_windows_job", None)
        if job is not None and getattr(job, "membership_verified", False):
            try:
                if job.terminate_verified(proc):
                    return True
            except BaseException:
                pass
        # Without a verified Job Object, kill only the direct root as leak
        # reduction and never report tree proof.
        try:
            proc.kill()
            _proc_dead(proc)
        except (OSError, AttributeError, subprocess.SubprocessError):
            pass
        return False

    # The child was started with start_new_session=True, so its PID must be the
    # group id. Never rediscover and kill an unrelated/recycled group.
    if not posix_pgid or int(posix_pgid) != int(pid):
        return False
    root_dead = _proc_dead(proc, timeout_seconds=0)
    if not root_dead:
        try:
            current = os.getpgid(int(pid))
        except ProcessLookupError:
            root_dead = _proc_dead(proc, timeout_seconds=0)
        except OSError:
            return False
        else:
            if int(current) != int(posix_pgid):
                return False
    try:
        os.killpg(int(posix_pgid), signal.SIGKILL)
    except ProcessLookupError:
        group_verified = bool(_proc_dead(proc, timeout_seconds=0)
                              and _posix_group_dead(posix_pgid, timeout_seconds=0))
        setattr(proc, "_anchor_process_group_kill_verified", group_verified)
        return False
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            group_verified = bool(_proc_dead(proc, timeout_seconds=0)
                                  and _posix_group_dead(posix_pgid, timeout_seconds=0))
            setattr(proc, "_anchor_process_group_kill_verified", group_verified)
            return False
        return False
    root_dead = _proc_dead(proc)
    group_dead = _posix_group_dead(posix_pgid)
    setattr(proc, "_anchor_process_group_kill_verified", bool(root_dead and group_dead))
    # Process groups cannot contain setsid/double-fork escapees. Never elevate
    # group death to complete descendant-tree proof.
    return False


def run_codex(prompt: str, target, sandbox="read-only",
              timeout_seconds=DEFAULT_TIMEOUT_SECONDS, env=None,
              preflight_fn=preflight_codex, popen_impl=subprocess.Popen,
              platform_name=None, signal_api=signal,
              resolve_fn=resolve_codex_cmd,
              guard_recheck_fn=recheck_runtime_guard,
              expected_artifact_paths=None,
              windows_job_factory=_WindowsJob) -> tuple[dict, int, str, str]:
    """Run one subscription seat and return envelope, adapter exit, native out/err."""
    started = time.monotonic()
    if sandbox not in VALID_SANDBOXES:
        raise ValueError("unsupported Codex sandbox %r" % (sandbox,))
    target_path = Path(target or Path.cwd()).resolve()
    if not target_path.is_dir():
        raise ValueError("Codex target is not a directory: %s" % target_path)
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("Codex prompt on stdin is empty")
    expected_paths = _normalize_expected_artifacts(
        target_path, expected_artifact_paths)
    if sandbox != "workspace-write" and expected_paths:
        raise ValueError("expected artifacts require workspace-write sandbox")
    if sandbox == "workspace-write" and not expected_paths:
        preflight = {
            "auth_probe_at": _now_iso(), "subscription_auth": None,
            "executable_path": None,
        }
        receipt = build_receipt(
            status="artifact_contract_required", prompt=prompt, sandbox=sandbox,
            preflight=preflight,
            error="Workspace-write requires explicit expected artifact paths",
            expected_artifact_paths=expected_paths,
        )
        elapsed = int((time.monotonic() - started) * 1000)
        return normalized_result("", receipt, elapsed, True), 2, "", ""

    runtime_platform = os.name if platform_name is None else str(platform_name)
    child_env = subscription_only_env(env)
    try:
        cmd = resolve_fn(child_env)
    except OSError as exc:
        preflight = {
            "executable_path": None, "auth_probe_at": _now_iso(),
            "subscription_auth": None,
        }
        receipt = build_receipt(
            status="executable_unavailable", prompt=prompt, sandbox=sandbox,
            preflight=preflight, error=exc,
            expected_artifact_paths=expected_paths,
        )
        elapsed = int((time.monotonic() - started) * 1000)
        return normalized_result("", receipt, elapsed, True), 2, "", ""
    preflight = dict(preflight_fn(cmd, CODEX_MODEL, CODEX_EFFORT, child_env))
    if not preflight.get("ok"):
        status = str(preflight.get("status") or "preflight_failed")
        receipt = build_receipt(
            status=status, prompt=prompt, sandbox=sandbox, preflight=preflight,
            error=preflight.get("error"), expected_artifact_paths=expected_paths,
        )
        elapsed = int((time.monotonic() - started) * 1000)
        return normalized_result("", receipt, elapsed, True), 2, "", ""

    artifact_root_guard = None
    artifact_root_identity = None

    def _release_artifact_root_guard():
        nonlocal artifact_root_guard
        if artifact_root_guard is None:
            return True
        try:
            artifact_root_guard.close()
            artifact_root_guard = None
            return True
        except BaseException:
            return False

    if expected_paths:
        try:
            artifact_root_guard = _open_guarded_directory(target_path)
            artifact_root_identity = _guarded_directory_identity(
                artifact_root_guard, target_path)
            if not _workspace_root_matches(target_path, artifact_root_identity):
                raise OSError("workspace root path changed during guard acquisition")
        except BaseException as exc:
            _release_artifact_root_guard()
            receipt = build_receipt(
                status="artifact_scan_incomplete", prompt=prompt,
                sandbox=sandbox, preflight=preflight,
                error="Workspace root could not be identity-guarded: %s" % str(exc)[:300],
                expected_artifact_paths=expected_paths,
                artifact_scan_complete=False,
            )
            elapsed = int((time.monotonic() - started) * 1000)
            return normalized_result("", receipt, elapsed, True), 2, "", ""

    try:
        before_artifacts, before_scan_complete = (
            _expected_artifact_snapshot(
                target_path, expected_paths, artifact_root_identity)
            if expected_paths else ({}, True)
        )
    except BaseException as exc:
        _release_artifact_root_guard()
        interrupted = isinstance(exc, (KeyboardInterrupt, SystemExit))
        receipt = build_receipt(
            status="artifact_scan_incomplete", prompt=prompt,
            sandbox=sandbox, preflight=preflight,
            error="Expected-artifact pre-scan was interrupted",
            expected_artifact_paths=expected_paths,
            artifact_scan_complete=False, aborted=interrupted,
        )
        elapsed = int((time.monotonic() - started) * 1000)
        return normalized_result("", receipt, elapsed, True), \
            (130 if interrupted else 2), "", ""
    if not before_scan_complete:
        _release_artifact_root_guard()
        receipt = build_receipt(
            status="artifact_scan_incomplete", prompt=prompt, sandbox=sandbox,
            preflight=preflight,
            error="Expected artifacts could not be fingerprinted before launch",
            expected_artifact_paths=expected_paths, artifact_scan_complete=False,
        )
        elapsed = int((time.monotonic() - started) * 1000)
        return normalized_result("", receipt, elapsed, True), 2, "", ""

    canonical_cmd = Path(str(preflight.get("executable_path") or cmd)).expanduser()
    if not canonical_cmd.is_absolute():
        _release_artifact_root_guard()
        receipt = build_receipt(
            status="executable_provenance_failed", prompt=prompt, sandbox=sandbox,
            preflight=preflight,
            error="Attested Codex executable path is not absolute",
            expected_artifact_paths=expected_paths,
        )
        elapsed = int((time.monotonic() - started) * 1000)
        return normalized_result("", receipt, elapsed, True), 2, "", ""
    try:
        canonical_cmd = canonical_cmd.resolve(strict=False)
        cmd = str(canonical_cmd)
        trusted_launch_cwd = str(canonical_cmd.parent)
        argv = build_exec_argv(cmd, target_path, sandbox=sandbox)
    except BaseException:
        _release_artifact_root_guard()
        raise
    creationflags = 0
    if runtime_platform == "nt":
        creationflags = (getattr(subprocess, "CREATE_SUSPENDED", 0x00000004)
                         | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                         | getattr(subprocess, "CREATE_NO_WINDOW", 0))

    proc = None
    posix_pgid = None
    previous_handlers = {}
    previous_mask = None
    signal_guard_armed = False
    signal_mask_used = False
    guarded_signals = ()
    termination_pending = False
    tree_kill_verified = None
    process_group_kill_verified = None
    output_drain_verified = None
    output_limits_verified = None
    output_eof_verified = None
    stdin_write_verified = None
    stdin_close_verified = None
    output_overflow_kind = None
    native_stdout_bytes = 0
    native_stderr_bytes = 0
    executable_guard = None
    windows_job = None
    seat_started = False

    def _safe_close_handle(handle):
        if handle is None:
            return True
        try:
            handle.close()
            return True
        except BaseException:
            return False

    def _safe_close_windows_job(job):
        if job is None:
            return True
        try:
            return job.close() is not False
        except BaseException:
            return False

    def _guard_failure(status, detail):
        _release_artifact_root_guard()
        receipt = build_receipt(
            status=status, prompt=prompt, sandbox=sandbox,
            preflight=preflight, error=detail,
            expected_artifact_paths=expected_paths,
        )
        elapsed = int((time.monotonic() - started) * 1000)
        return normalized_result("", receipt, elapsed, True), 2, "", ""

    def _restore_signal_guard():
        """Restore handlers without opening an unguarded delivery window."""
        nonlocal signal_guard_armed
        if not signal_guard_armed:
            return True
        ok = True
        if signal_mask_used:
            try:
                signal_api.pthread_sigmask(signal_api.SIG_BLOCK, set(guarded_signals))
            except BaseException:
                ok = False
        for sig, handler in previous_handlers.items():
            try:
                signal_api.signal(sig, handler)
            except BaseException:
                ok = False
        if signal_mask_used:
            try:
                signal_api.pthread_sigmask(signal_api.SIG_SETMASK, previous_mask)
            except BaseException:
                ok = False
        signal_guard_armed = False
        return ok

    def _attempt_tree_kill():
        nonlocal tree_kill_verified, process_group_kill_verified
        if proc is None:
            tree_kill_verified = False
            return False
        if (runtime_platform == "nt" and windows_job is not None and
                getattr(windows_job, "empty_verified", False) and
                _proc_dead(proc, timeout_seconds=0)):
            # A signal delivered after verified Job emptiness needs no second
            # termination call (the handle may already be closed).
            tree_kill_verified = True
            return True
        try:
            verified = bool(_kill_tree(proc, posix_pgid, runtime_platform))
        except BaseException:
            verified = False
        if runtime_platform != "nt":
            process_group_kill_verified = bool(getattr(
                proc, "_anchor_process_group_kill_verified", False))
        tree_kill_verified = bool(tree_kill_verified is True or verified)
        return verified

    def _has_readable_native_pipes():
        return bool(
            proc is not None and
            callable(getattr(getattr(proc, "stdout", None), "read", None)) and
            callable(getattr(getattr(proc, "stderr", None), "read", None)))

    def _bounded_native_exchange(input_text, exchange_timeout):
        return _bounded_pipe_exchange(
            proc, input_text, exchange_timeout,
            terminate_fn=_attempt_tree_kill,
            stdout_limit=MAX_NATIVE_STDOUT_BYTES,
            stderr_limit=MAX_NATIVE_STDERR_BYTES,
            aggregate_limit=MAX_NATIVE_OUTPUT_BYTES,
            abort_requested=(lambda: termination_pending)
            if runtime_platform == "nt" else None)

    def _drain_after_termination(drain_timeout=PIPE_DRAIN_TIMEOUT_SECONDS):
        """Bound real pipes; retain communicate only for pipe-less test doubles."""
        if _has_readable_native_pipes():
            exchange = _bounded_native_exchange(None, drain_timeout)
            return exchange["stdout"], exchange["stderr"], exchange
        out, err = proc.communicate(timeout=drain_timeout)
        return out, err, {
            "output_drain_verified": True, "output_eof_verified": True,
            "output_limits_verified": True, "stdin_write_verified": False,
            "stdin_close_verified": True, "overflow_kind": None,
            "stdout_bytes": len((out or "").encode("utf-8", errors="replace")),
            "stderr_bytes": len((err or "").encode("utf-8", errors="replace")),
            "root_exit_verified": True,
        }

    def _record_exchange(exchange):
        nonlocal output_drain_verified, output_limits_verified
        nonlocal output_eof_verified, stdin_write_verified
        nonlocal stdin_close_verified, output_overflow_kind
        nonlocal native_stdout_bytes, native_stderr_bytes
        output_drain_verified = bool(exchange.get("output_drain_verified"))
        output_limits_verified = bool(exchange.get("output_limits_verified"))
        output_eof_verified = bool(exchange.get("output_eof_verified"))
        stdin_write_verified = exchange.get("stdin_write_verified")
        stdin_close_verified = exchange.get("stdin_close_verified")
        output_overflow_kind = exchange.get("overflow_kind")
        native_stdout_bytes = int(exchange.get("stdout_bytes") or 0)
        native_stderr_bytes = int(exchange.get("stderr_bytes") or 0)

    def _record_pipe_less_test_exchange(out, err, input_sent=True):
        stdout_size = len((out or "").encode("utf-8", errors="replace"))
        stderr_size = len((err or "").encode("utf-8", errors="replace"))
        overflow = None
        if stdout_size > MAX_NATIVE_STDOUT_BYTES:
            overflow = "stdout"
        elif stderr_size > MAX_NATIVE_STDERR_BYTES:
            overflow = "stderr"
        elif stdout_size + stderr_size > MAX_NATIVE_OUTPUT_BYTES:
            overflow = "aggregate"
        _record_exchange({
            "output_drain_verified": True, "output_eof_verified": True,
            "output_limits_verified": overflow is None,
            "stdin_write_verified": bool(input_sent),
            "stdin_close_verified": bool(input_sent),
            "overflow_kind": overflow, "stdout_bytes": stdout_size,
            "stderr_bytes": stderr_size,
        })

    def _relay_termination(_signum, _frame):
        nonlocal termination_pending
        if runtime_platform == "nt":
            termination_pending = True
            if (proc is not None and windows_job is not None and
                    (windows_job.resumed or
                     getattr(windows_job, "execution_possible", False))):
                # Python delivers Windows console handlers between arbitrary
                # bytecodes, including the membership-to-communicate gap.  Do
                # not throw through that state machine: terminate the already
                # owned Job and let the bounded drain path stamp the abort.
                _attempt_tree_kill()
            # Before verified assignment/resume, the suspended-spawn state
            # machine observes this flag and terminates without running code.
            return
        if proc is None:
            termination_pending = True
            return
        _attempt_tree_kill()
        raise KeyboardInterrupt

    if threading.current_thread() is not threading.main_thread():
        return _guard_failure(
            "signal_guard_unavailable",
            "Cancellation guard requires the Python main thread")
    required = ("SIGTERM", "SIGINT", "getsignal", "signal")
    if runtime_platform != "nt":
        required += ("pthread_sigmask", "SIG_BLOCK", "SIG_SETMASK")
    if any(not hasattr(signal_api, name) for name in required):
        return _guard_failure(
            "signal_guard_unavailable",
            "Cancellation signal guard is unavailable")
    guarded_signals = (signal_api.SIGTERM, signal_api.SIGINT)
    try:
        if runtime_platform != "nt":
            # Close the spawn-to-handler race on POSIX by holding both signals.
            previous_mask = signal_api.pthread_sigmask(
                signal_api.SIG_BLOCK, set(guarded_signals))
            signal_mask_used = True
        signal_guard_armed = True
        for sig in guarded_signals:
            previous_handlers[sig] = signal_api.getsignal(sig)
            signal_api.signal(sig, _relay_termination)
    except BaseException as exc:
        _restore_signal_guard()
        return _guard_failure(
            "signal_guard_unavailable",
            "Cancellation signal guard could not be armed: %s" % exc)

    # Re-attest the canonical signed executable at the last possible point. The
    # returned handle stays open through Popen; mutable user config is excluded
    # by --ignore-user-config rather than re-read here.
    try:
        recheck = dict(guard_recheck_fn(preflight, child_env, runtime_platform))
    except BaseException as exc:
        recheck = {"ok": False, "status": "runtime_guard_failed", "error": str(exc)}
    if not recheck.get("ok"):
        _safe_close_handle(recheck.pop("_executable_guard_handle", None))
        _restore_signal_guard()
        return _guard_failure(
            str(recheck.get("status") or "runtime_guard_failed"),
            recheck.get("error") or "Codex runtime guard failed")
    executable_guard = recheck.pop("_executable_guard_handle", None)
    preflight.update(recheck)
    try:
        preflight.update(_derive_security_controls(argv, preflight))
    except BaseException as exc:
        _safe_close_handle(executable_guard)
        _restore_signal_guard()
        return _guard_failure(
            "security_guard_failed",
            "Codex security-control derivation failed: %s" % str(exc)[:300])
    if preflight.get("critical_overrides_enforced") is not True:
        _safe_close_handle(executable_guard)
        _restore_signal_guard()
        return _guard_failure(
            "security_guard_failed",
            "Codex command or environment controls were not fully attested")

    if runtime_platform == "nt":
        try:
            windows_job = windows_job_factory()
        except BaseException as exc:
            _safe_close_handle(executable_guard)
            _restore_signal_guard()
            return _guard_failure(
                "containment_assignment_failed",
                "Windows Job Object policy could not be established: %s" % str(exc)[:300])
        preflight.update(
            containment_kind="windows_job",
            complete_tree_containment=False,
            windows_job_policy_verified=bool(
                getattr(windows_job, "policy_verified", False)),
        )
        if preflight["windows_job_policy_verified"] is not True:
            _safe_close_windows_job(windows_job)
            _safe_close_handle(executable_guard)
            _restore_signal_guard()
            return _guard_failure(
                "containment_assignment_failed",
                "Windows Job Object policy was not verified")
    else:
        preflight.update(
            containment_kind="posix_process_group_degraded",
            complete_tree_containment=False,
        )

    spawn_exception = None
    try:
        proc = popen_impl(
            argv, cwd=trusted_launch_cwd, executable=cmd, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=child_env,
            shell=False, close_fds=True, text=False,
            creationflags=creationflags,
            start_new_session=(runtime_platform != "nt"),
        )
    except BaseException as exc:  # includes KeyboardInterrupt/SystemExit
        spawn_exception = exc
    finally:
        if executable_guard is not None:
            try:
                executable_guard.close()
            except BaseException:
                spawn_exception = spawn_exception or RuntimeError(
                    "executable guard could not be closed")
        preflight["executable_handle_guarded_through_spawn"] = bool(
            executable_guard is not None and spawn_exception is None)

    if spawn_exception is not None:
        cleanup_verified = proc is None
        if proc is not None and runtime_platform == "nt":
            setattr(proc, "_anchor_windows_job", windows_job)
            seat_started = bool(
                getattr(windows_job, "resumed", False) or
                getattr(windows_job, "execution_possible", False))
            try:
                killed = bool(windows_job.abort_suspended(proc))
            except BaseException:
                killed = False
            try:
                _discard_out, _discard_err, exchange = _drain_after_termination()
                _record_exchange(exchange)
            except BaseException:
                output_drain_verified = False
            root_exit_verified = bool(_proc_dead(proc, timeout_seconds=0))
            # Before ResumeThread a suspended root cannot have descendants.
            tree_kill_verified = bool(
                killed and not seat_started and root_exit_verified and
                output_drain_verified)
            preflight.update(
                containment_kind="windows_job",
                windows_job_assignment_verified=bool(windows_job.assigned),
                windows_job_membership_verified=bool(
                    windows_job.membership_verified),
                windows_process_handle_verified=bool(
                    windows_job.process_handle_verified),
                windows_primary_thread_verified=bool(
                    windows_job.primary_thread_verified),
                windows_process_resumed=bool(windows_job.resumed),
                windows_execution_possible=bool(
                    getattr(windows_job, "execution_possible", False)),
                windows_job_empty_verified=bool(windows_job.empty_verified),
                root_exit_verified=root_exit_verified,
            )
            cleanup_verified = bool(tree_kill_verified)
        elif proc is not None:
            seat_started = True
            try:
                posix_pgid = int(proc.pid)
            except (AttributeError, TypeError, ValueError):
                posix_pgid = None
            _attempt_tree_kill()
            try:
                _discard_out, _discard_err, exchange = _drain_after_termination()
                _record_exchange(exchange)
            except BaseException:
                output_drain_verified = False
            cleanup_verified = bool(
                tree_kill_verified is True and output_drain_verified)
        job_closed = _safe_close_windows_job(windows_job)
        cleanup_verified = bool(cleanup_verified and job_closed)
        if tree_kill_verified is not None and output_drain_verified is not True:
            tree_kill_verified = False
        signal_guard_restored = _restore_signal_guard()
        _release_artifact_root_guard()
        interrupted = isinstance(spawn_exception, (KeyboardInterrupt, SystemExit))
        status = "spawn_aborted" if interrupted else "spawn_error"
        if proc is not None and not cleanup_verified:
            status = "kill_failed"
        if not signal_guard_restored:
            status = "signal_guard_restore_failed"
        receipt = build_receipt(
            status=status, prompt=prompt, sandbox=sandbox, preflight=preflight,
            error=("Codex spawn was interrupted" if interrupted else spawn_exception),
            aborted=interrupted, seat_started=seat_started,
            expected_artifact_paths=expected_paths,
            tree_kill_verified=tree_kill_verified,
            output_drain_verified=output_drain_verified,
            process_group_kill_verified=process_group_kill_verified,
            output_limits_verified=output_limits_verified,
            output_eof_verified=output_eof_verified,
            stdin_write_verified=stdin_write_verified,
            stdin_close_verified=stdin_close_verified,
            output_overflow_kind=output_overflow_kind,
            native_stdout_bytes=native_stdout_bytes,
            native_stderr_bytes=native_stderr_bytes,
        )
        elapsed = int((time.monotonic() - started) * 1000)
        return normalized_result("", receipt, elapsed, True), \
            (130 if interrupted else 2), "", str(spawn_exception)

    if runtime_platform == "nt":
        setattr(proc, "_anchor_windows_job", windows_job)
        containment_error = None
        try:
            # Re-read the flag at the final instruction boundary.  A Windows
            # console signal may arrive after Job membership is verified but
            # before ResumeThread; the child must remain suspended in that
            # window.
            resumed = windows_job.assign_and_resume(
                proc, cancel_before_resume=lambda: termination_pending)
            seat_started = bool(
                resumed or getattr(windows_job, "execution_possible", False))
        except BaseException as exc:
            containment_error = exc
            # ResumeThread may have succeeded immediately before a later guard
            # failure. Preserve that fact and terminate as a started seat.
            seat_started = bool(
                getattr(windows_job, "resumed", False) or
                getattr(windows_job, "execution_possible", False))
            try:
                killed = bool(windows_job.abort_suspended(proc))
            except BaseException:
                killed = False
            try:
                _discard_out, _discard_err, exchange = _drain_after_termination()
                _record_exchange(exchange)
            except BaseException:
                output_drain_verified = False
            tree_kill_verified = bool(
                killed and output_drain_verified and
                (not seat_started or windows_job.membership_verified))
        preflight.update(
            windows_job_assignment_verified=bool(windows_job.assigned),
            windows_job_membership_verified=bool(windows_job.membership_verified),
            windows_process_handle_verified=bool(windows_job.process_handle_verified),
            windows_primary_thread_verified=bool(windows_job.primary_thread_verified),
            windows_process_resumed=bool(windows_job.resumed),
            windows_execution_possible=bool(
                getattr(windows_job, "execution_possible", False)),
            complete_tree_containment=bool(
                windows_job.assigned and windows_job.membership_verified),
        )
        if containment_error is not None:
            preflight["windows_job_empty_verified"] = bool(
                windows_job.empty_verified)
            preflight["root_exit_verified"] = bool(
                _proc_dead(proc, timeout_seconds=0))
            job_closed = _safe_close_windows_job(windows_job)
            signal_guard_restored = _restore_signal_guard()
            _release_artifact_root_guard()
            status = ("containment_assignment_failed"
                      if tree_kill_verified and job_closed
                      else "kill_failed")
            if not signal_guard_restored:
                status = "signal_guard_restore_failed"
            receipt = build_receipt(
                status=status, prompt=prompt, sandbox=sandbox,
                preflight=preflight, error=str(containment_error)[:500],
                seat_started=seat_started, tree_kill_verified=tree_kill_verified,
                output_drain_verified=output_drain_verified,
                output_limits_verified=output_limits_verified,
                output_eof_verified=output_eof_verified,
                stdin_write_verified=stdin_write_verified,
                stdin_close_verified=stdin_close_verified,
                output_overflow_kind=output_overflow_kind,
                native_stdout_bytes=native_stdout_bytes,
                native_stderr_bytes=native_stderr_bytes,
                expected_artifact_paths=expected_paths,
            )
            elapsed = int((time.monotonic() - started) * 1000)
            return normalized_result("", receipt, elapsed, True), 1, "", ""
    else:
        seat_started = True
        try:
            posix_pgid = int(proc.pid)
            if posix_pgid <= 0:
                raise ValueError("process-group id must be positive")
        except (AttributeError, TypeError, ValueError):
            _attempt_tree_kill()
            try:
                _discard_out, _discard_err, exchange = _drain_after_termination()
                _record_exchange(exchange)
            except BaseException:
                output_drain_verified = False
                tree_kill_verified = False
            _restore_signal_guard()
            _release_artifact_root_guard()
            receipt = build_receipt(
                status="kill_failed", prompt=prompt, sandbox=sandbox,
                preflight=preflight,
                error="Codex child did not expose a stable POSIX process-group id",
                seat_started=True, tree_kill_verified=tree_kill_verified,
                output_drain_verified=output_drain_verified,
                output_limits_verified=output_limits_verified,
                output_eof_verified=output_eof_verified,
                stdin_write_verified=stdin_write_verified,
                stdin_close_verified=stdin_close_verified,
                output_overflow_kind=output_overflow_kind,
                native_stdout_bytes=native_stdout_bytes,
                native_stderr_bytes=native_stderr_bytes,
                expected_artifact_paths=expected_paths,
            )
            elapsed = int((time.monotonic() - started) * 1000)
            return normalized_result("", receipt, elapsed, True), 1, "", ""

    timed_out = False
    aborted = False
    signal_guard_error = None
    native_out = ""
    native_err = ""
    stdin_exchange_error = None
    signal_guard_restored = True
    try:
        if runtime_platform == "nt" and termination_pending:
            raise KeyboardInterrupt
        if runtime_platform != "nt":
            try:
                signal_api.pthread_sigmask(signal_api.SIG_SETMASK, previous_mask)
            except (AttributeError, OSError, RuntimeError, ValueError) as exc:
                signal_guard_error = str(exc)[:300]
                _attempt_tree_kill()
                try:
                    native_out, native_err, exchange = _drain_after_termination()
                    _record_exchange(exchange)
                except BaseException:
                    output_drain_verified = False
        if signal_guard_error is None:
            if _has_readable_native_pipes():
                exchange = _bounded_native_exchange(prompt, timeout_seconds)
                _record_exchange(exchange)
                native_out, native_err = exchange["stdout"], exchange["stderr"]
                timed_out = bool(exchange["timed_out"])
                aborted = bool(exchange["aborted"])
                stdin_exchange_error = exchange.get("writer_error")
                if exchange.get("wait_error"):
                    aborted = True
                    native_err = (native_err + "\nAdapter wait failure: " +
                                  str(exchange["wait_error"])[:300]).strip()
            else:
                native_out, native_err = proc.communicate(
                    input=prompt, timeout=float(timeout_seconds))
                _record_pipe_less_test_exchange(native_out, native_err)
    except subprocess.TimeoutExpired:
        timed_out = True
        _attempt_tree_kill()
        try:
            native_out, native_err, exchange = _drain_after_termination()
            _record_exchange(exchange)
        except BaseException:
            _attempt_tree_kill()
            output_drain_verified = False
            native_out, native_err = "", "Codex process tree did not drain after timeout"
    except (KeyboardInterrupt, SystemExit):
        aborted = True
        _attempt_tree_kill()
        try:
            native_out, native_err, exchange = _drain_after_termination()
            _record_exchange(exchange)
        except BaseException:
            _attempt_tree_kill()
            output_drain_verified = False
            native_out, native_err = "", "Codex process tree did not drain after cancellation"
    except BaseException as exc:
        aborted = True
        _attempt_tree_kill()
        try:
            native_out, native_err, exchange = _drain_after_termination()
            _record_exchange(exchange)
        except BaseException:
            output_drain_verified = False
        native_err = (native_err + "\nAdapter interruption: " + str(exc)[:300]).strip()
    finally:
        # On Windows retain the non-throwing relay through Job verification and
        # close; otherwise Ctrl-C can unwind the narrow post-communicate cleanup
        # gap. POSIX delivery was unmasked only inside this try and is restored
        # here in the original masked order.
        if runtime_platform != "nt":
            signal_guard_restored = _restore_signal_guard()

    if tree_kill_verified is not None and output_drain_verified is not True:
        # An open inherited pipe is evidence that a descendant may still live.
        tree_kill_verified = False
    containment_straggler = False
    containment_cleanup_failed = False
    if runtime_platform == "nt" and windows_job is not None:
        try:
            job_empty = bool(windows_job.verify_empty())
        except BaseException:
            job_empty = False
        if not job_empty:
            containment_straggler = True
            try:
                terminated = bool(windows_job.terminate_verified(proc))
            except BaseException:
                terminated = False
            tree_kill_verified = bool(
                terminated and output_drain_verified is True)
        preflight["windows_job_empty_verified"] = bool(windows_job.empty_verified)
        preflight["root_exit_verified"] = bool(_proc_dead(proc, timeout_seconds=0))
        containment_cleanup_failed = not _safe_close_windows_job(windows_job)
        signal_guard_restored = _restore_signal_guard()
    if runtime_platform == "nt" and termination_pending:
        aborted = True
    parsed = parse_jsonl(native_out)
    exit_code = getattr(proc, "returncode", None)
    status = classify_failure(native_err, parsed, exit_code,
                              timed_out=timed_out, aborted=aborted)
    if (timed_out or aborted or signal_guard_error is not None) and (
            tree_kill_verified is not True or output_drain_verified is not True or
            stdin_close_verified is not True):
        status = "kill_failed"
    elif containment_cleanup_failed:
        status = "kill_failed"
    elif containment_straggler:
        status = "process_tree_straggler"
    elif (not timed_out and not aborted and signal_guard_error is None and
          output_overflow_kind is not None):
        overflow_cleanup_verified = _overflow_cleanup_verified(
            proc, runtime_platform, output_drain_verified,
            tree_kill_verified, process_group_kill_verified,
            complete_tree_containment=preflight.get(
                "complete_tree_containment"),
            windows_job_empty_verified=preflight.get(
                "windows_job_empty_verified"))
        status = ("output_limit_exceeded" if overflow_cleanup_verified
                  else "kill_failed")
    elif (not timed_out and not aborted and signal_guard_error is None and
          (output_drain_verified is not True or output_eof_verified is not True)):
        status = "output_drain_failed"
    elif (not timed_out and not aborted and signal_guard_error is None and
          output_limits_verified is not True):
        status = "output_limit_exceeded"
    elif (not timed_out and not aborted and signal_guard_error is None and
          (stdin_write_verified is not True or stdin_close_verified is not True)):
        status = "stdin_write_failed"
    elif signal_guard_error is not None:
        status = "signal_guard_unavailable"
    elif not signal_guard_restored:
        status = "signal_guard_restore_failed"

    artifact_paths = []
    artifact_hashes = {}
    artifact_evidence = {}
    artifact_scan_complete = before_scan_complete
    artifact_contract_verified = False
    if sandbox == "workspace-write":
        try:
            after_artifacts, after_scan_complete = _expected_artifact_snapshot(
                target_path, expected_paths, artifact_root_identity)
        except BaseException:
            after_artifacts, after_scan_complete = {}, False
        artifact_scan_complete = before_scan_complete and after_scan_complete
        for relative in expected_paths:
            after_value = after_artifacts.get(relative)
            if isinstance(after_value, dict) and after_value.get("sha256"):
                artifact_hashes[relative] = after_value["sha256"]
                artifact_evidence[relative] = dict(after_value)
            before_value = before_artifacts.get(relative)
            if (after_value is not None and
                    (before_value is None or
                     before_value.get("sha256") != after_value.get("sha256"))):
                artifact_paths.append(relative)
        artifact_contract_verified = bool(
            artifact_scan_complete and len(artifact_paths) == len(expected_paths))
        if status == "success" and not artifact_scan_complete:
            status = "artifact_scan_incomplete"
        elif status == "success" and not artifact_contract_verified:
            status = "artifact_required"

    if not _release_artifact_root_guard():
        artifact_scan_complete = False
        artifact_contract_verified = False
        if status == "success":
            status = "artifact_scan_incomplete"

    tool_errors = _tool_error_count(native_err)
    safe_error = parsed.get("failure_detail") or (
        (native_err or "").strip() if status != "success" else "")
    if status == "kill_failed":
        safe_error = "Codex process-tree termination and pipe drain were not both verified"
    elif status == "output_limit_exceeded":
        safe_error = "Codex %s output exceeded the bounded native-output contract" % (
            output_overflow_kind or "native")
    elif status == "output_drain_failed":
        safe_error = "Codex stdout/stderr did not both reach verified EOF"
    elif status == "stdin_write_failed":
        safe_error = "Codex prompt stdin was not fully written and closed: %s" % (
            stdin_exchange_error or "unverified prompt delivery")
    elif status == "signal_guard_unavailable":
        safe_error = "POSIX cancellation signal guard failed: %s" % signal_guard_error
    elif status == "signal_guard_restore_failed":
        safe_error = "POSIX cancellation signal guard could not be restored"
    elif not safe_error and status != "success":
        safe_error = "Codex seat ended with status %s" % status
    receipt = build_receipt(
        status=status, prompt=prompt, sandbox=sandbox, preflight=preflight,
        parsed=parsed, exit_code=exit_code, error=safe_error,
        timed_out=timed_out, aborted=aborted, seat_started=seat_started,
        artifact_paths=artifact_paths, artifact_hashes=artifact_hashes,
        artifact_evidence=artifact_evidence,
        expected_artifact_paths=expected_paths,
        artifact_contract_verified=artifact_contract_verified,
        artifact_mutation_verified=artifact_contract_verified,
        artifact_scan_complete=artifact_scan_complete,
        tool_error_count=tool_errors, tree_kill_verified=tree_kill_verified,
        output_drain_verified=output_drain_verified,
        process_group_kill_verified=process_group_kill_verified,
        output_limits_verified=output_limits_verified,
        output_eof_verified=output_eof_verified,
        stdin_write_verified=stdin_write_verified,
        stdin_close_verified=stdin_close_verified,
        output_overflow_kind=output_overflow_kind,
        native_stdout_bytes=native_stdout_bytes,
        native_stderr_bytes=native_stderr_bytes,
    )
    elapsed = int((time.monotonic() - started) * 1000)
    is_error = status != "success"
    adapter_exit = 0 if not is_error else (130 if status == "aborted" else 1)
    return normalized_result(parsed.get("text") or "", receipt, elapsed, is_error), \
        adapter_exit, native_out, native_err


def _failure_envelope(exc: Exception, prompt: str, sandbox: str) -> dict:
    preflight = {
        "executable_path": None,
        "auth_probe_at": _now_iso(),
        "subscription_auth": None,
    }
    receipt = build_receipt(
        status="adapter_error", prompt=prompt, sandbox=sandbox,
        preflight=preflight, error=exc,
    )
    return normalized_result("", receipt, 0, True)


def main(argv=None) -> int:
    # Anchor opens these pipes as UTF-8 on every platform. Python otherwise uses
    # the Windows locale codec for redirected standard streams, which can corrupt
    # prompts/results or lose the terminal receipt on ordinary model punctuation.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="strict")
        except (AttributeError, OSError, ValueError):
            pass
    parser = argparse.ArgumentParser(description="Anchor ChatGPT subscription adapter")
    parser.add_argument("--target", default=os.getcwd())
    parser.add_argument("--sandbox", choices=sorted(VALID_SANDBOXES), default="read-only")
    parser.add_argument(
        "--expected-artifact", action="append", default=[],
        help="Target-relative file that workspace-write must create or hash-change",
    )
    parser.add_argument("--timeout-seconds", type=float,
                        default=float(os.environ.get("ANCHOR_CODEX_TIMEOUT_SECONDS")
                                      or DEFAULT_TIMEOUT_SECONDS))
    args = parser.parse_args(argv)
    prompt = sys.stdin.read()
    try:
        envelope, exit_code, native_out, native_err = run_codex(
            prompt, args.target, sandbox=args.sandbox,
            timeout_seconds=args.timeout_seconds,
            expected_artifact_paths=args.expected_artifact,
        )
    except (OSError, ValueError, TypeError) as exc:
        envelope = _failure_envelope(exc, prompt, args.sandbox)
        exit_code, native_out, native_err = 2, "", str(exc)

    if native_out:
        sys.stderr.write(native_out.rstrip("\n") + "\n")
    if native_err:
        sys.stderr.write(native_err.rstrip("\n") + "\n")
    sys.stderr.flush()
    sys.stdout.write(json.dumps(envelope, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
