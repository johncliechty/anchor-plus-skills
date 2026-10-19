#!/usr/bin/env python3
"""Anchor service bootstrap — the thin NSSM entry wrapper (2026-10-10).

PURPOSE
    Move the Anchor service's environment (the ``ANCHOR_TOKEN`` bearer and the
    other ``AppEnvironmentExtra`` variables) out of the world-readable NSSM
    registry key into ONE service-owned JSON file that only the service
    account, SYSTEM and Administrators can read; load that file at process
    start; then run the fixed sibling ``anchor_gui.py`` exactly as NSSM runs it
    today.

    Blocking evidence (2026-10-10): NSSM keeps the bearer in
    ``HKLM\\SYSTEM\\CurrentControlSet\\Services\\anchor\\Parameters\\AppEnvironmentExtra``.
    Both the rawAppContainer sandbox and the Codex MXC sandbox can open that key
    with ``KEY_QUERY_VALUE``, and a network-off job can launder a readable
    secret to the networked author through its outputs. A parent-owned,
    ACL-protected FILE is denied to those sandboxes (MXC ``:minimal`` plus
    exact-workspace-write refuses reads outside the synthetic files), so the
    service environment has to move there. This module is the STARTUP half of
    that move only; the elevated installer, the registry clean-up and the
    sandbox-denial proof are owned by the reviewer (see PREREQUISITES).

WHAT THIS IS / IS NOT
    * The SAME service environment in protected storage. NOT an auth redesign,
      NOT a token rotation, NOT a permission bypass. Every existing consumer
      keeps reading ``os.environ`` exactly as before (``paths.expected_token``
      reads ``ANCHOR_TOKEN``, ``paths.data_dir`` reads ``ANCHOR_DATA_DIR``, ...)
      because the map is applied BEFORE ``anchor_gui.py`` — and therefore
      ``paths`` — is imported.
    * The default direct launch ``python anchor_gui.py --no-browser`` is
      UNCHANGED and unaffected. This wrapper is used only by the reviewed
      installer.
    * Stdlib only, and it imports NO Anchor module: nothing can read the
      environment before the map is applied, and the wrapper stays importable
      from a hermetic test without touching Anchor state.

INVOCATION (installer-owned)
    python service_bootstrap.py [--check] --environment-file <ABSOLUTE PATH> [forwarded args...]

    * ``--environment-file <path>`` is REQUIRED and must come first (after the
      optional ``--check``). The path must be absolute, on a local drive, free
      of the ``\\\\?\\`` / ``\\\\.\\`` prefixes, canonical (no symlink, junction
      or mapped-drive indirection anywhere in it) and name a real regular file.
    * Everything after the path is forwarded VERBATIM to ``anchor_gui.py`` as
      its ``sys.argv[1:]``. ``anchor_gui.main`` reads exactly two flags today,
      ``--no-browser`` and ``--port <n>``, straight from ``sys.argv``; this
      wrapper invents none and interprets none. It only refuses a NUL byte, a
      second ``--environment-file`` and a misplaced ``--check``.
    * The target is FIXED: the ``anchor_gui.py`` adjacent to THIS file. No
      argument, environment variable or file content can substitute another
      executable, module or script.
    * ``--check`` validates the file and the target, prints SAFE diagnostics
      (normalized path, size, entry count, variable NAMES — never values) as one
      JSON line on stdout, and exits WITHOUT touching ``os.environ`` or running
      anything. Exit 0 when the service would start, ``EXIT_BOOTSTRAP_ERROR``
      otherwise.

FILE FORMAT (UTF-8 JSON, at most ``MAX_FILE_BYTES``)
    {
      "schema": "anchor-service-environment/1",
      "environment": {
        "ANCHOR_TOKEN": "<bearer>",
        "ANCHOR_DATA_DIR": "C:\\\\..."
      }
    }

    Any violation refuses startup BEFORE anything is served. There is NO
    fallback to the registry and NO fallback to running with auth disabled.
    * top level: a JSON object with exactly the keys ``schema`` and
      ``environment``;
    * ``schema``: exactly ``"anchor-service-environment/1"``;
    * ``environment``: a JSON object with 1..``MAX_ENTRIES`` entries, every
      value a JSON string (no numbers, booleans, null or nesting);
    * names: ``[A-Za-z_][A-Za-z0-9_]*``, at most ``MAX_NAME_CHARS``, unique
      CASE-INSENSITIVELY (a Windows environment block is case-insensitive);
      exact duplicates are refused as well (the JSON parser would otherwise
      keep the last one silently);
    * values: at most ``MAX_VALUE_CHARS`` (the Windows per-variable limit), no
      NUL (``\\u0000``) — ``os.environ`` cannot hold one and a NUL would
      truncate the value for a C consumer;
    * ``ANCHOR_TOKEN`` (spelled exactly) MUST be present and non-blank, because
      ``paths.expected_token`` treats a blank token as "auth disabled".

PRECEDENCE
    The file wins for exactly the names it supplies; every other inherited
    variable (``PATH``, ``USERPROFILE``, a non-secret ``AppEnvironmentExtra``
    entry the installer chose to leave in place, ...) is preserved untouched.

SAFE DIAGNOSTICS
    Refusals (one stderr line, exit ``EXIT_BOOTSTRAP_ERROR``) and ``--check``
    output carry only: a short code, a reason built from fixed text, counts,
    positions and WELL-FORMED names (an ill-formed key — which may be a value
    pasted into the key position — is reported by position, never echoed), the
    NORMALIZED environment-file path, the canonical path when it differs, and
    the fixed target path. No environment VALUE is ever printed, logged or
    embedded in an exception — including the JSON parser's own messages and any
    unexpected exception, which is reported by type name only.

LINK / REPARSE HANDLING
    The configured path is inspected with ``os.lstat``: a symlink, any reparse
    point (junction, mount point, ...) or a non-regular file is refused; then
    the canonical path (``os.path.realpath``) must equal the configured path
    (so a link or junction in an ANCESTOR, an 8.3 short name or a mapped drive
    is refused with the canonical path in the diagnostic); then the file is
    opened and ``os.fstat`` must report the same ``(st_dev, st_ino)`` identity
    the inspection saw. That narrows the inspect-then-open race; it does not
    replace the ACL, which is the actual control. NOTHING here claims NTFS
    protection: Python's stat metadata says nothing about a DACL, so no
    diagnostic reports the file as "protected".

PREREQUISITES (owned by the reviewed, ELEVATED installer — not by this module)
    1. Create the service-owned file OUTSIDE every job workspace, repository
       and data dir (recommended: ``%ProgramData%\\Anchor\\service-env.json``),
       written from the PRESERVED current ``AppEnvironmentExtra`` so nothing is
       lost.
    2. Bind an explicit NTFS ACL to the file AND its directory: disable
       inheritance; grant read to the service account (the ``ObjectName`` of
       the ``anchor`` service), full control to ``SYSTEM`` and
       ``Administrators``; no ``Users`` / ``Authenticated Users`` /
       ``Everyone`` / AppContainer / package entries. Verify with ``icacls`` or
       ``Get-Acl``. This module does not and cannot verify the ACL.
    3. Prove ``python service_bootstrap.py --check --environment-file <file>``
       exits 0 as the service account, then point the service at the wrapper
       (``nssm set anchor AppParameters "<ANCHOR_DIR>\\service_bootstrap.py
       --environment-file <file> --no-browser"``) and set
       ``nssm set anchor AppExit 3 Exit`` so a refused configuration stops the
       service instead of restart-looping.
    4. Only AFTER the service runs from the file, remove the secret entries
       from ``AppEnvironmentExtra`` (registry plaintext removal). Non-secret
       entries may stay; the file wins only for the names it supplies.
    5. Prove sandbox denial with SYNTHETIC fixtures (never the real file): a
       network-off job under rawAppContainer and under MXC must fail to open a
       synthetic file carrying the same ACL. Keep that proof with the
       installer. No real credential is read, copied or printed by any of
       these steps or by this module's tests.
"""

import errno
import json
import os
import re
import runpy
import stat
import sys
from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple

__all__ = [
    "BootstrapError",
    "Invocation",
    "ENVIRONMENT_FILE_FLAG",
    "CHECK_FLAG",
    "TARGET_NAME",
    "SCHEMA_ID",
    "TOKEN_NAME",
    "REQUIRED_NAMES",
    "MAX_FILE_BYTES",
    "MAX_ENTRIES",
    "MAX_NAME_CHARS",
    "MAX_VALUE_CHARS",
    "EXIT_BOOTSTRAP_ERROR",
    "REFUSED_PREFIX",
    "USAGE",
    "parse_args",
    "normalize_environment_path",
    "inspect_environment_file",
    "read_environment_file",
    "parse_environment_document",
    "load_environment_file",
    "apply_environment",
    "target_path",
    "check_target",
    "run_anchor_gui",
    "diagnose",
    "main",
]

ENVIRONMENT_FILE_FLAG = "--environment-file"
CHECK_FLAG = "--check"
# The FIXED target: the anchor_gui.py adjacent to this file. Never configurable.
TARGET_NAME = "anchor_gui.py"
SCHEMA_ID = "anchor-service-environment/1"
SCHEMA_KEY = "schema"
ENVIRONMENT_KEY = "environment"
TOP_LEVEL_KEYS = (SCHEMA_KEY, ENVIRONMENT_KEY)
# Mirrors paths.AUTH_TOKEN_ENV. Deliberately NOT imported from paths: this module
# must import no Anchor module (see the module docstring).
TOKEN_NAME = "ANCHOR_TOKEN"
REQUIRED_NAMES = (TOKEN_NAME,)
MAX_FILE_BYTES = 128 * 1024
MAX_ENTRIES = 256
MAX_NAME_CHARS = 255
MAX_VALUE_CHARS = 32767  # the Windows per-variable limit
EXIT_BOOTSTRAP_ERROR = 3
REFUSED_PREFIX = "anchor service bootstrap refused: "
USAGE = ("usage: service_bootstrap.py [--check] --environment-file <absolute path> "
         "[forwarded anchor_gui.py arguments, e.g. --no-browser --port 8777]")

_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_VERBATIM_PREFIXES = ("\\\\?\\", "\\\\.\\", "//?/", "//./")


class BootstrapError(Exception):
    """A refusal raised BEFORE anything is served.

    Carries only safe fields: ``code`` (a short machine token), ``reason`` (a
    sentence built from fixed text, counts, positions and well-formed names)
    and ``path`` (the normalized environment-file path, or ``None`` when the
    refusal happened before a path was known). Never an environment value.
    """

    def __init__(self, code: str, reason: str, path: Optional[str] = None):
        self.code = code
        self.reason = reason
        self.path = path
        super().__init__(self.describe())

    def describe(self) -> str:
        text = "{}: {}".format(self.code, self.reason)
        if self.path is not None:
            text += " [environment file: {}]".format(self.path)
        return text


class Invocation(object):
    """The parsed command line.

    ``environment_file`` is the raw path argument (normalized later),
    ``forwarded`` the verbatim service arguments handed to ``anchor_gui.py``,
    ``check`` whether ``--check`` was requested.
    """

    __slots__ = ("environment_file", "forwarded", "check")

    def __init__(self, environment_file: str, forwarded: Sequence[str], check: bool = False):
        self.environment_file = environment_file
        self.forwarded = list(forwarded)
        self.check = bool(check)


# ── Safe diagnostics helpers ───────────────────────────────────────────────

def _well_formed_name(name: Any) -> bool:
    return (isinstance(name, str) and len(name) <= MAX_NAME_CHARS
            and _NAME_RE.fullmatch(name) is not None)


def _safe_label(name: Any, position: Optional[int] = None) -> str:
    """A label that never echoes an ill-formed key (it may be a value pasted
    into the key position): the quoted name when well-formed, else the
    1-based position."""
    if _well_formed_name(name):
        return "'{}'".format(name)
    if position is not None:
        return "entry {}".format(position)
    return "an entry"


def _emit(stream, text: str) -> None:
    """Write one line; silent when the stream is absent (pythonw) or broken."""
    if stream is None:
        return
    try:
        stream.write(text + "\n")
        stream.flush()
    except Exception:
        pass


# ── Command line ───────────────────────────────────────────────────────────

def parse_args(argv: Sequence[str]) -> Invocation:
    """``[--check] --environment-file <path> [forwarded...]`` → :class:`Invocation`.

    Refuses (code ``usage``) a non-string or NUL-bearing argument, a missing or
    misplaced ``--environment-file``, an empty path, a second
    ``--environment-file`` (in any spelling) and a misplaced ``--check``.
    Everything after the path is forwarded verbatim — never interpreted.
    """
    args = list(argv)
    for position, token in enumerate(args, 1):
        if not isinstance(token, str):
            raise BootstrapError("usage", "argument {} is not a string".format(position))
        if "\x00" in token:
            raise BootstrapError("usage", "argument {} contains a NUL byte".format(position))
    check = bool(args) and args[0] == CHECK_FLAG
    if check:
        args = args[1:]
    if len(args) < 2 or args[0] != ENVIRONMENT_FILE_FLAG:
        raise BootstrapError("usage", USAGE)
    raw_path, forwarded = args[1], args[2:]
    if not raw_path.strip():
        raise BootstrapError("usage", "the environment-file path is empty")
    for token in forwarded:
        if token == ENVIRONMENT_FILE_FLAG or token.startswith(ENVIRONMENT_FILE_FLAG + "="):
            raise BootstrapError(
                "usage", "--environment-file may appear exactly once, as the first argument")
        if token == CHECK_FLAG:
            raise BootstrapError("usage", "--check must be the first argument")
    return Invocation(raw_path, forwarded, check)


# ── Path + file inspection ─────────────────────────────────────────────────

def normalize_environment_path(raw: str) -> str:
    """Return the lexically normalized absolute path, or refuse (code ``path``).

    Refuses an empty or whitespace-padded path, a NUL byte, a ``\\\\?\\`` /
    ``\\\\.\\`` prefix (hidden normalization bypass), a relative or
    drive-relative path (NSSM's working directory is not a trust anchor) and a
    UNC path (the file must live on a local, ACL-bound volume). Normalization
    is ``os.path.normpath`` only: it NEVER follows links — link handling is the
    separate, explicit refusal in :func:`inspect_environment_file`.
    """
    if not isinstance(raw, str) or not raw or raw != raw.strip():
        raise BootstrapError("path", "the environment-file path is empty or padded with whitespace")
    if "\x00" in raw:
        raise BootstrapError("path", "the environment-file path contains a NUL byte")
    if raw.startswith(_VERBATIM_PREFIXES):
        raise BootstrapError("path", "the environment-file path must not use a \\\\?\\ or \\\\.\\ prefix")
    if not os.path.isabs(raw) or (os.name == "nt" and not os.path.splitdrive(raw)[0]):
        raise BootstrapError(
            "path", "the environment-file path must be absolute (with a drive letter on Windows)")
    normalized = os.path.normpath(raw)
    if normalized.startswith("\\\\") or normalized.startswith("//"):
        raise BootstrapError("path", "the environment-file path must be on a local drive, not a UNC share")
    return normalized


def _is_link(st) -> bool:
    """True for a symlink or ANY Windows reparse point (junction, mount point)."""
    if stat.S_ISLNK(st.st_mode):
        return True
    if getattr(st, "st_file_attributes", 0) & _REPARSE_POINT:
        return True
    if getattr(st, "st_reparse_tag", 0):
        return True
    return False


def _identity(st) -> Optional[Tuple[int, int]]:
    """``(st_dev, st_ino)`` when the platform populates both, else ``None``
    (the identity re-check is then skipped — recorded, never claimed)."""
    dev, ino = getattr(st, "st_dev", 0), getattr(st, "st_ino", 0)
    if dev and ino:
        return (int(dev), int(ino))
    return None


def inspect_environment_file(path: str) -> Dict[str, Any]:
    """``os.lstat``-based facts about the NORMALIZED path (no open, no read).

    Refuses: missing (``missing``), not inspectable (``unreadable``), a
    symlink / reparse point (``link``), not a regular file (``not-a-file``), a
    canonical path that differs from the configured one — a link, junction,
    short name or mapped drive somewhere in the ancestry (``link``, with the
    canonical path in the reason so the installer can configure it) — and a
    file larger than ``MAX_FILE_BYTES`` (``oversize``).

    Returns ``{"path", "canonical", "size", "identity"}``. Nothing about the
    DACL: Python's stat metadata cannot show NTFS protection.
    """
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        raise BootstrapError("missing", "the environment file does not exist", path)
    except PermissionError:
        raise BootstrapError("unreadable", "the environment file cannot be inspected (permission denied)", path)
    except OSError as exc:
        raise BootstrapError(
            "unreadable", "the environment file cannot be inspected (errno {})".format(exc.errno), path)
    if _is_link(st):
        raise BootstrapError(
            "link", "the environment file is a symlink or reparse point (junction); "
                    "a real regular file is required", path)
    if not stat.S_ISREG(st.st_mode):
        raise BootstrapError("not-a-file", "the environment-file path is not a regular file", path)
    try:
        canonical = os.path.realpath(path)
    except OSError:
        raise BootstrapError("unreadable", "the environment-file path cannot be canonicalized", path)
    if os.path.normcase(canonical) != os.path.normcase(path):
        raise BootstrapError(
            "link", "the environment-file path traverses a link, junction, short name or mapped "
                    "drive; configure the canonical path {}".format(canonical), path)
    size = int(getattr(st, "st_size", 0))
    if size > MAX_FILE_BYTES:
        raise BootstrapError(
            "oversize", "the environment file is {} bytes; the limit is {}".format(size, MAX_FILE_BYTES), path)
    return {"path": path, "canonical": canonical, "size": size, "identity": _identity(st)}


def read_environment_file(path: str, expected_identity: Optional[Tuple[int, int]] = None) -> bytes:
    """Open, ``fstat``-recheck and read at most ``MAX_FILE_BYTES`` bytes.

    The opened object must be a regular non-link file with the identity the
    inspection saw (when the platform reports identities), else ``link``.
    """
    flags = (os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
             | getattr(os, "O_CLOEXEC", 0))
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        raise BootstrapError("missing", "the environment file does not exist", path)
    except PermissionError:
        raise BootstrapError("unreadable", "the environment file cannot be opened (permission denied)", path)
    except OSError as exc:
        if exc.errno == getattr(errno, "ELOOP", None):
            raise BootstrapError("link", "the environment file is a symlink; a real regular file is required", path)
        raise BootstrapError(
            "unreadable", "the environment file cannot be opened (errno {})".format(exc.errno), path)
    try:
        st = os.fstat(fd)
        if _is_link(st) or not stat.S_ISREG(st.st_mode):
            raise BootstrapError("link", "the opened environment file is not a regular file", path)
        if expected_identity is not None:
            actual = _identity(st)
            if actual is not None and actual != expected_identity:
                raise BootstrapError(
                    "link", "the environment file changed identity between inspection and open "
                            "(a link or a swap)", path)
        size = int(getattr(st, "st_size", 0))
        if size > MAX_FILE_BYTES:
            raise BootstrapError(
                "oversize", "the environment file is {} bytes; the limit is {}".format(size, MAX_FILE_BYTES), path)
        handle = os.fdopen(fd, "rb")
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        raise
    with handle:
        data = handle.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise BootstrapError(
            "oversize", "the environment file exceeds {} bytes".format(MAX_FILE_BYTES), path)
    return data


# ── Document validation ────────────────────────────────────────────────────

class _Pairs(list):
    """A JSON object kept as its ordered ``(key, value)`` pairs so duplicate
    keys stay visible (``json`` would silently keep the last one)."""


def _top_level(document: Any, path: Optional[str]) -> Dict[str, Any]:
    if not isinstance(document, _Pairs):
        raise BootstrapError(
            "shape", "the top level must be a JSON object with the keys 'schema' and 'environment'", path)
    top = {}  # type: Dict[str, Any]
    for position, (key, value) in enumerate(document, 1):
        if key in top:
            raise BootstrapError("shape", "top-level key at position {} is a duplicate".format(position), path)
        if key not in TOP_LEVEL_KEYS:
            raise BootstrapError(
                "shape", "unexpected top-level key at position {} (only 'schema' and 'environment' "
                         "are allowed)".format(position), path)
        top[key] = value
    for key in TOP_LEVEL_KEYS:
        if key not in top:
            raise BootstrapError("shape", "missing top-level key '{}'".format(key), path)
    if not isinstance(top[SCHEMA_KEY], str) or top[SCHEMA_KEY] != SCHEMA_ID:
        raise BootstrapError("schema", "unsupported schema (expected '{}')".format(SCHEMA_ID), path)
    return top


def _entries(pairs: Any, path: Optional[str]) -> Dict[str, str]:
    if not isinstance(pairs, _Pairs):
        raise BootstrapError("shape", "'environment' must be a JSON object of name -> string", path)
    if len(pairs) == 0:
        raise BootstrapError("shape", "'environment' is empty", path)
    if len(pairs) > MAX_ENTRIES:
        raise BootstrapError(
            "oversize", "'environment' has {} entries; the limit is {}".format(len(pairs), MAX_ENTRIES), path)
    result = {}  # type: Dict[str, str]
    folded = {}  # type: Dict[str, str]
    for position, (name, value) in enumerate(pairs, 1):
        label = _safe_label(name, position)
        if "\x00" in name:
            raise BootstrapError("nul", "{}: the name contains a NUL character".format(label), path)
        if not _well_formed_name(name):
            raise BootstrapError(
                "invalid-name", "{}: the name must match [A-Za-z_][A-Za-z0-9_]* and be at most {} "
                                "characters".format(label, MAX_NAME_CHARS), path)
        if not isinstance(value, str):
            raise BootstrapError("shape", "{}: the value must be a JSON string".format(label), path)
        if "\x00" in value:
            raise BootstrapError("nul", "{}: the value contains a NUL character".format(label), path)
        if len(value) > MAX_VALUE_CHARS:
            raise BootstrapError(
                "oversize", "{}: the value is {} characters; the limit is {}".format(
                    label, len(value), MAX_VALUE_CHARS), path)
        key = name.upper()
        if key in folded:
            raise BootstrapError(
                "duplicate-name", "{} duplicates '{}' (names are compared case-insensitively)".format(
                    label, folded[key]), path)
        folded[key] = name
        result[name] = value
    for required in REQUIRED_NAMES:
        if required not in result:
            raise BootstrapError(
                "missing-required", "'{}' is required (spelled exactly) and absent; the service never "
                                    "starts with authentication disabled".format(required), path)
        if not result[required].strip():
            raise BootstrapError(
                "missing-required", "'{}' is blank; the service never starts with authentication "
                                    "disabled".format(required), path)
    return result


def parse_environment_document(data: bytes, path: Optional[str] = None) -> Dict[str, str]:
    """Raw bytes → the validated ``{name: value}`` map, or a refusal.

    Codes: ``encoding`` (not UTF-8), ``nul``, ``invalid-json`` (line/column
    only — never the parser's text), ``shape``, ``schema``, ``invalid-name``,
    ``oversize``, ``duplicate-name``, ``missing-required``.
    """
    try:
        text = bytes(data).decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise BootstrapError(
            "encoding", "the environment file is not valid UTF-8 (byte offset {})".format(exc.start), path)
    if "\x00" in text:
        raise BootstrapError("nul", "the environment file contains a NUL character", path)
    try:
        document = json.loads(text, object_pairs_hook=_Pairs)
    except RecursionError:
        raise BootstrapError("shape", "the environment file nests too deeply", path)
    except ValueError as exc:
        raise BootstrapError(
            "invalid-json", "the environment file is not valid JSON (line {}, column {})".format(
                getattr(exc, "lineno", "?"), getattr(exc, "colno", "?")), path)
    top = _top_level(document, path)
    return _entries(top[ENVIRONMENT_KEY], path)


def load_environment_file(raw_path: str) -> Tuple[str, Dict[str, str], Dict[str, Any]]:
    """normalize → inspect → read → parse. Returns ``(path, env_map, facts)``."""
    path = normalize_environment_path(raw_path)
    facts = inspect_environment_file(path)
    data = read_environment_file(path, expected_identity=facts["identity"])
    env_map = parse_environment_document(data, path)
    return path, env_map, facts


# ── Apply + target + run ───────────────────────────────────────────────────

def apply_environment(env_map: Mapping[str, str], environ: MutableMapping[str, str]) -> List[str]:
    """Set exactly the supplied names into ``environ`` (the file wins for those
    names; every other entry is untouched). Returns the sorted names applied.
    Defensive re-checks keep a NUL or non-string out of ``os.environ`` even
    when called with an unvalidated map."""
    names = []  # type: List[str]
    for name, value in env_map.items():
        if not isinstance(name, str) or not isinstance(value, str):
            raise BootstrapError("shape", "{}: environment entries must be string -> string".format(
                _safe_label(name)))
        if "\x00" in name or "\x00" in value:
            raise BootstrapError("nul", "{}: contains a NUL character".format(_safe_label(name)))
        names.append(name)
    for name in names:
        try:
            environ[name] = env_map[name]
        except Exception as exc:
            raise BootstrapError("apply", "{}: could not be set ({})".format(
                _safe_label(name), type(exc).__name__))
    return sorted(names)


def target_path() -> str:
    """The FIXED target: ``anchor_gui.py`` adjacent to this file. Not
    configurable by argument, environment or file content."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), TARGET_NAME)


def check_target(target: str) -> None:
    """The fixed target must exist as a real regular file (a symlinked or
    missing ``anchor_gui.py`` is refused with code ``target``)."""
    try:
        st = os.lstat(target)
    except OSError:
        raise BootstrapError("target", "the fixed target {} is missing".format(target))
    if _is_link(st) or not stat.S_ISREG(st.st_mode):
        raise BootstrapError("target", "the fixed target {} is not a regular file".format(target))


def run_anchor_gui(target: str, forwarded: Sequence[str]) -> None:
    """The default runner: execute the fixed target as ``__main__`` in THIS
    process via ``runpy`` with ``sys.argv = [target, *forwarded]``, so
    ``anchor_gui.main`` sees exactly what ``python anchor_gui.py <args>`` would.
    The target's directory is ensured on ``sys.path`` (a script launch already
    puts it first) so ``import paths`` and the other siblings resolve."""
    here = os.path.dirname(target)
    wanted = os.path.normcase(os.path.abspath(here))
    if not any(os.path.normcase(os.path.abspath(entry or os.curdir)) == wanted for entry in sys.path):
        sys.path.insert(0, here)
    sys.argv = [target] + list(forwarded)
    runpy.run_path(target, run_name="__main__")


# ── Orchestration ──────────────────────────────────────────────────────────

def _prepare(args: Sequence[str]) -> Tuple[Invocation, str, Dict[str, str], Dict[str, Any], str]:
    """parse → load → target check. Any unexpected exception becomes a
    ``BootstrapError`` carrying its TYPE NAME only (never its message, which
    could contain file content)."""
    try:
        invocation = parse_args(args)
        path, env_map, facts = load_environment_file(invocation.environment_file)
        target = target_path()
        check_target(target)
    except BootstrapError:
        raise
    except Exception as exc:
        raise BootstrapError(
            "internal", "unexpected {} while validating the service environment".format(type(exc).__name__))
    return invocation, path, env_map, facts, target


def _failure_report(exc: BootstrapError) -> Dict[str, Any]:
    return {"ok": False, "code": exc.code, "reason": exc.reason, "path": exc.path}


def _success_report(invocation: Invocation, path: str, env_map: Mapping[str, str],
                    facts: Mapping[str, Any], target: str) -> Dict[str, Any]:
    return {
        "ok": True,
        "code": None,
        "reason": None,
        "path": path,
        "size": facts.get("size"),
        "entry_count": len(env_map),
        "names": sorted(env_map),
        "target": target,
        "forwarded": list(invocation.forwarded),
    }


def diagnose(argv: Sequence[str]) -> Dict[str, Any]:
    """Validate the invocation, the file and the target WITHOUT applying or
    running anything. Returns the SAFE report ``--check`` prints (names, never
    values)."""
    try:
        invocation, path, env_map, facts, target = _prepare(list(argv))
    except BootstrapError as exc:
        return _failure_report(exc)
    return _success_report(invocation, path, env_map, facts, target)


def main(argv: Optional[Sequence[str]] = None, *,
         environ: Optional[MutableMapping[str, str]] = None,
         runner: Optional[Callable[[str, Sequence[str]], Any]] = None,
         stdout=None, stderr=None) -> int:
    """The NSSM entry point.

    Validates everything BEFORE serving; on a refusal writes one safe line to
    stderr (plus the JSON report on stdout under ``--check``) and returns
    ``EXIT_BOOTSTRAP_ERROR`` — never the registry, never auth-disabled. On
    success applies the map into ``environ`` (``os.environ`` by default) and
    hands the fixed target plus the verbatim forwarded arguments to ``runner``
    (``run_anchor_gui`` by default; injectable for tests). Prints nothing on the
    success path — the target owns its own banner.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    out = sys.stdout if stdout is None else stdout
    err = sys.stderr if stderr is None else stderr
    check_requested = bool(args) and args[0] == CHECK_FLAG
    try:
        invocation, path, env_map, facts, target = _prepare(args)
    except BootstrapError as exc:
        _emit(err, REFUSED_PREFIX + exc.describe())
        if check_requested:
            _emit(out, json.dumps(_failure_report(exc), sort_keys=True))
        return EXIT_BOOTSTRAP_ERROR
    if invocation.check:
        _emit(out, json.dumps(_success_report(invocation, path, env_map, facts, target), sort_keys=True))
        return 0
    try:
        apply_environment(env_map, os.environ if environ is None else environ)
    except BootstrapError as exc:
        _emit(err, REFUSED_PREFIX + exc.describe())
        return EXIT_BOOTSTRAP_ERROR
    (run_anchor_gui if runner is None else runner)(target, list(invocation.forwarded))
    return 0


if __name__ == "__main__":
    sys.exit(main())
