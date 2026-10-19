#!/usr/bin/env python3
"""Anchor distribution builder + no-personal-data scanner (Wave 8, stdlib only).

Frozen design: MASTER-PLAN.md "## Architecture (frozen)" -> Distribution; C10
("Shareable, zero personal data"). Implementation plan: Wave 8.

What this does
==============
Builds a *publishable, data-free* export of the Anchor product into a staging
directory, then scans every staged file for personal data / secrets. The build
is **deny-by-default**: a file is staged ONLY if it matches an allow entry in
``dist_manifest.txt``. Everything else — task/project markdown, the R&D
registry JSON, ``.anchor/`` stores, ``logs/``, ``health_reports/``,
``foreman-checkpoint.json``, ``planning/``, ``_archive/`` — is excluded
automatically because it is simply not listed.

If the no-personal-data scan finds a hit in any staged file, ``build_distro``
raises :class:`PersonalDataError` naming the offending file(s) and what matched,
and (by default) tears down the staging dir so nothing leaks downstream.

The scan: real secrets fail, legitimate code passes
===================================================
The shipped product code legitimately contains the *identifier* ``ANCHOR_TOKEN``
(the env-var NAME) and may mention the Windows user-profile dir in a comment or
docstring example. The scan flags concrete personal-data **values and
secrets**, not bare identifiers. CRITICAL: this scanner stores **no** real PII
literal of its own — it detects PII by PATTERN, so it never has to embed (and
therefore never leaks) a real value.

- **Email (by pattern, not by stored value)**: any concrete user-at-host-dot-
  tld email literal in a staged file is flagged, EXCEPT a small hardcoded
  allowlist of known-safe, non-personal addresses that legitimately appear in
  the product (``anchor`` at ``localhost`` — the git identity used by
  ``effort_history``; the Anthropic ``noreply`` co-author address; and the
  RFC-2606 doc domains ``example.com`` / ``example.org`` / ``example.net``). A
  bare mention of the word "email" has no at-host-dot-tld shape and does not
  trip it. The real personal email is NOT stored anywhere in this file; it is
  caught purely by the generic regex.
- **User profile paths**: an *absolute Windows user-profile path* — a drive
  letter, then the Users dir, then a concrete account name, then a further path
  segment. The bare prefix (drive + Users dir, no account name + separator) does
  NOT trip it, so a code comment that merely mentions the Users dir passes,
  while a fully-qualified ``<drive>\\Users\\<account>\\<segment>`` fails. The
  allowlisted account ``example`` (``C:\\Users\\example\\...`` doc placeholder)
  is exempt.
- **Auth-token VALUE**: an actual secret value assigned to a token, in QUOTED
  or UNQUOTED assignment form and in JSON ``"key": "value"`` form, when the key
  is a secret/token-ish name (``ANCHOR_TOKEN``, ``token``, ``secret``,
  ``api_key``, ``password``, ``access_token``, ``auth_token``, ``bearer``):
  ``ANCHOR_TOKEN = "<value>"`` / ``"ANCHOR_TOKEN": "<value>"`` /
  ``ANCHOR_TOKEN=<value>``. The bare identifier ``ANCHOR_TOKEN`` with no value
  (env-var reference, ``"ANCHOR_TOKEN"`` as a dict KEY only, ``delenv(...)``)
  does NOT trip it, and placeholder values are exempt.
- **Concrete secret shapes (key-independent)**: AWS access key
  (``AKIA[0-9A-Z]{16}``), JWT (``eyJ...\\.<b64>\\.<b64>``), ``sk-`` / ``ghp_`` /
  ``gho_`` token prefixes, and ``Bearer <token>``.
- **Generic high-entropy token (first-party files only)**: a long base64/hex
  run assigned to a secret-named key, or a standalone 40+ char high-entropy run.
  To avoid false positives on the **vendored, minified KaTeX** (275KB+ of
  third-party code full of high-entropy-looking runs, with documented
  PROVENANCE), the generic entropy heuristic is applied ONLY to first-party
  files and is SKIPPED for anything under ``vendor/``. The concrete-PII patterns
  (email, user path, registry/.anchor artifact, AWS/JWT/keyword-token) DO run
  over every staged file including ``vendor/``.
- **Registry / .anchor data artifact**: a staged file whose *content* is an
  R&D registry pointer-record / ``.anchor`` store payload (a JSON object with
  registry-shaped keys like ``folder_path`` + ``project`` ids, or a job
  pointer-record). Source code that merely constructs the string
  ``.anchor/projects/...`` does NOT trip it.

- **Third-party / native imports (stdlib-only enforcement)**: every staged
  first-party (non-``vendor/``, non-``tests/``) ``.py`` file is parsed with
  ``ast`` and each top-level import is checked. An import of a module that is
  NEITHER stdlib NOR a first-party Anchor module is an undeclared third-party /
  native dependency and FAILS the scan — UNLESS it is the single DECLARED,
  file-scoped exception: ``import winpty`` (the native ``pywinpty`` ConPTY
  backend) is allowed ONLY in ``pty_manager.py`` (lazy, terminal-subsystem-only).
  ``import winpty`` anywhere else, or ANY other native/third-party import (e.g.
  ``import numpy``) in any product file, is still refused. ``tests/`` are
  dev-only (pytest is a declared dev dependency) and ``vendor/`` is third-party
  by construction (documented PROVENANCE), so both are exempt from this rule.

No inline suppression marker exists. No shipped file embeds a real secret, so no
file needs (or can grant itself) an exemption — a leaking product file CANNOT
suppress its own detection.

Stdlib only (the scanner itself uses only ``ast``/``re``/``json`` etc.). Never
publishes/pushes anywhere — it builds a local export dir.
"""

from __future__ import annotations

import ast
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

import paths  # shared helper (CODE_DIR); stdlib-only, no side effects on import


# ── Configuration ───────────────────────────────────────────────────────────

REPO_ROOT = paths.CODE_DIR
MANIFEST_NAME = "dist_manifest.txt"

# Known-safe, NON-personal email addresses that legitimately appear in the
# product and must NOT be flagged. Detection is by PATTERN; this allowlist is
# the only thing the scanner stores, and it deliberately contains no real
# personal address. ``*@example.{com,org,net}`` (RFC-2606 doc domains) are
# allowed via a domain suffix check below.
_EMAIL_ALLOWLIST = frozenset({
    "anchor@localhost",        # git identity used by effort_history auto-commits
    "noreply@anthropic.com",   # Claude Code co-author trailer
})
_EMAIL_ALLOWLIST_DOMAINS = ("example.com", "example.org", "example.net")

# Account name(s) inside an absolute Windows user-profile path that are
# documentation placeholders, not real accounts. The real account name is NEVER
# stored here — any other concrete account name in a user-profile path is
# flagged generically.
_USERPATH_ALLOWED_ACCOUNTS = frozenset({"example"})


# ── Third-party / native-dependency import allowlist ─────────────────────────
#
# The shipped Anchor product is **Python standard library only** — with EXACTLY
# ONE declared, scoped exception: the v3 ConPTY terminal subsystem may use the
# native ``pywinpty`` package (imported in Python as ``winpty``). That import is
# LAZY (inside ``pty_manager.PywinptyBackend.start``) and the rest of Anchor is
# unaffected when the native dep is absent (the terminal subsystem reports "real
# terminal unavailable").
#
# The import scan (``scan_third_party_imports``) parses every staged FIRST-PARTY
# (non-vendor) ``.py`` file and flags any ``import``/``from … import`` of a
# top-level module that is NEITHER stdlib NOR a first-party Anchor module — i.e.
# an undeclared third-party / native dependency leaking into the product. The
# allowlist below is the SINGLE declared exception, and it is SCOPED: ``winpty``
# is permitted ONLY in ``pty_manager.py``. An ``import winpty`` anywhere else, or
# ANY other third-party import (e.g. ``import numpy`` / ``import requests``) in
# any first-party file, is still REFUSED.
#
# Each entry maps the imported top-level module name → the set of first-party
# files (POSIX relpaths) where it is allowed, plus a human reason.
_THIRD_PARTY_IMPORT_ALLOWLIST = {
    "winpty": {
        "files": frozenset({"pty_manager.py"}),
        "reason": ("pty_manager.py — terminal subsystem (ConPTY), the only "
                   "native-dep exception (lazy import; degrades if absent)"),
    },
}


class PersonalDataError(Exception):
    """Raised when the no-personal-data scan finds a hit in a staged file.

    ``hits`` is a list of ``(relpath, category, snippet)`` tuples so callers /
    tests can assert *which* file and *what* matched.
    """

    def __init__(self, hits):
        self.hits = list(hits)
        lines = [f"  {rel}: {cat}: {snip}" for (rel, cat, snip) in self.hits]
        super().__init__(
            "no-personal-data scan FAILED — offending staged file(s):\n"
            + "\n".join(lines)
        )


# ── Manifest (deny-by-default allowlist) ─────────────────────────────────────

def load_manifest(manifest_path: Path | None = None) -> list[str]:
    """Read ``dist_manifest.txt`` -> list of allow patterns (POSIX, relative).

    Comment (``#``) and blank lines are dropped. Order preserved.
    """
    mp = Path(manifest_path) if manifest_path else (REPO_ROOT / MANIFEST_NAME)
    patterns: list[str] = []
    for raw in mp.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        patterns.append(line.replace("\\", "/"))
    return patterns


def _iter_repo_files(root: Path):
    """Yield every file under ``root`` as a POSIX relpath, skipping VCS/cache.

    We never descend into directories that can never be shippable and that are
    expensive/noisy to walk: ``.git``, ``__pycache__``, ``.pytest_cache``.
    Everything else is enumerated; the manifest decides what is actually staged.
    """
    skip_dirs = {".git", "__pycache__", ".pytest_cache"}
    for p in sorted(root.rglob("*")):
        if p.is_dir():
            continue
        rel = p.relative_to(root)
        if any(part in skip_dirs for part in rel.parts):
            continue
        yield rel.as_posix(), p


def _match_any(rel_posix: str, patterns: list[str]) -> bool:
    """True if ``rel_posix`` matches any manifest pattern.

    ``**`` matches across path separators; ``*`` matches within a segment.
    A bare path (no glob char) must match exactly.
    """
    for pat in patterns:
        if "*" in pat:
            if _glob_match(rel_posix, pat):
                return True
        elif rel_posix == pat:
            return True
    return False


def _glob_match(rel_posix: str, pattern: str) -> bool:
    """Translate a manifest glob (with ``**``) into a regex and test it."""
    # Build regex piece by piece so ** vs * have distinct semantics.
    out = []
    i = 0
    n = len(pattern)
    while i < n:
        c = pattern[i]
        if c == "*":
            if i + 1 < n and pattern[i + 1] == "*":
                out.append(".*")  # ** -> across separators
                i += 2
                # swallow an immediate trailing slash so vendor/** matches vendor/x
                if i < n and pattern[i] == "/":
                    i += 1
                continue
            out.append("[^/]*")  # * -> within a segment
            i += 1
            continue
        out.append(re.escape(c))
        i += 1
    return re.fullmatch("".join(out), rel_posix) is not None


def select_shippable(root: Path | None = None,
                     manifest_path: Path | None = None) -> list[str]:
    """Return the deny-by-default list of relpaths that ARE shippable.

    Only files matching a manifest allow-pattern are returned. This is the
    answer to AC1: data/registry/.anchor/ etc. never appear because they are
    not listed.
    """
    root = Path(root) if root else REPO_ROOT
    patterns = load_manifest(manifest_path)
    selected = []
    for rel_posix, _abs in _iter_repo_files(root):
        if _match_any(rel_posix, patterns):
            selected.append(rel_posix)
    return selected


# ── No-personal-data scan ────────────────────────────────────────────────────

# Absolute Windows user-profile path with a concrete account name + a following
# path segment. Requires the account name AND a separator after it, so the bare
# token "C:\Users" (mentioned in a comment) does not match. The account name is
# captured so a doc-placeholder account ("example") can be allowlisted.
_USERPATH_RE = re.compile(
    r"[A-Za-z]:[\\/]Users[\\/](?P<acct>[^\\/\s\"']+)[\\/][^\s\"']",
    re.IGNORECASE,
)

# Build-host / dev-tree paths the _USERPATH_RE above does NOT catch. The
# user-profile detector only fires on ``<drive>\Users\<account>\<seg>``; a
# project checked out under a ``dev\`` tree (no Users segment) or a POSIX
# ``/Users/example/<seg>`` / ``/home/example/<seg>`` home path leaks the build host's
# tree without ever touching the Users dir. These are caught here. Detection by
# PATTERN — no real host path literal is stored. NOTE: vendored files are
# already host-path-SCRUBBED by vendor_skills, so this (like the generic
# entropy heuristic) is applied ONLY to first-party / non-vendored files.
#
# Windows dev tree: a drive letter then ``\dev\`` directly, or ``…\dev\``
# nested under any path, then a further concrete segment (the LEAF, captured so
# a documented-placeholder leaf can be allowlisted, like the user-profile
# ``example`` account). The leaf charclass excludes path-adjacent prose
# punctuation (backtick / paren / comma / colon / period / quote) so a captured
# leaf is the bare directory name. Requires a path segment AFTER ``dev`` so the
# bare word "dev" in prose never matches.
_WIN_DEVPATH_RE = re.compile(
    r"[A-Za-z]:\\(?:[^\s\"'<>|]*\\)?dev\\(?P<leaf>[^\s\"'<>|/\\`(),:;.]+)",
)
# POSIX home paths: /Users/example/<seg> and /home/example/<seg>. Requires a concrete
# user segment AND a further path segment so the bare prefix "/home/" or
# "/Users/" (mentioned in prose) does not match. The first segment under the
# home root (the username) is captured as the leaf for allowlisting.
_POSIX_HOMEPATH_RE = re.compile(
    r"/(?:Users|home)/(?P<leaf>[^/\s\"'<>|`(),:;]+)/[^\s\"'<>|]+",
)

# Documented-placeholder / project-own host-path leaf names that are NOT a real
# personal build-tree leak even though they sit under ``dev\`` / a home dir.
# This mirrors ``_USERPATH_ALLOWED_ACCOUNTS`` — detection is by PATTERN; only
# these explicit doc placeholders + the project's OWN root name are exempt. The
# canonical build root (``C:\dev\Anchor``) is the project's own folder, used
# throughout the code as the illustrative example path. Any OTHER leaf (e.g. a
# private ``secret``-named dir under a dev tree) is flagged.
# NOTE on the trio/skill-source leaves: ``C:\dev\trio`` / ``C:\dev\Skill
# Foundry`` are the author's OWN trio/Gandalf source repos, referenced in
# comments + a default-dir constant as documented examples (the live sources are
# always env-injected, never hardcoded for the build). They are genericized over
# the FINAL shipped surface in Wave 11; for now they are documented-own-tree
# references, not third-party PII, and are allowlisted here.
_HOSTPATH_ALLOWED_LEAVES = frozenset({
    "anchor",     # the project's own root (C:\dev\Anchor) — REPO_ROOT.name
    "example",    # doc placeholder (mirrors _USERPATH_ALLOWED_ACCOUNTS)
    "...",        # ellipsis placeholder in docstring examples
    "<path>",     # the vendor-scrub genericized token
    "trio",       # author's own trio source repo (doc/comment; W11 genericizes)
    "skill",      # author's own "Skill Foundry" source (doc/comment; W11)
})

# Any concrete email literal (generic RFC-ish shape). Detection is by PATTERN;
# the personal address is NOT stored — it is caught here like any other email,
# then NON-personal addresses are filtered out via the allowlist.
_EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"
)

# Auth-token VALUE assigned to a token/secret-named key. Handles:
#   - QUOTED value:    KEY = "value"        KEY: "value"
#   - UNQUOTED value:  KEY=value            KEY = value
#   - JSON form:       "KEY": "value"
# An optional quote may wrap the KEY (JSON). A bare identifier with no value,
# or a placeholder value, does not match (value must be >= 8 chars, non-trivial).
_TOKEN_KEY = (
    r"ANCHOR_TOKEN|api[_-]?key|secret|password|bearer"
    r"|access[_-]?token|auth[_-]?token|token"
)
# Quoted / JSON value form.
_TOKEN_ASSIGN_QUOTED_RE = re.compile(
    rf"""(?ix)
    ['"]?\b(?:{_TOKEN_KEY})\b['"]?
    \s* [:=] \s*
    (?P<q>['"])
    (?P<val>[^'"\s]{{8,}})
    (?P=q)
    """,
)
# Unquoted value form: KEY=token-run (env-file / shell / JSON-less assignment).
# The value run is letters/digits and a few token chars, >= 8 chars. Requires a
# clear boundary so we don't grab ordinary prose.
_TOKEN_ASSIGN_UNQUOTED_RE = re.compile(
    rf"""(?ix)
    \b(?:{_TOKEN_KEY})\b
    \s* = \s*
    (?P<val>[A-Za-z0-9][A-Za-z0-9._\-+/]{{7,}})
    (?=[\s,;)\]}}'"]|$)
    """,
)

# Concrete secret SHAPES, independent of the key name.
_TOKEN_VALUE_RE = re.compile(
    r"""(?x)
    (?:
        \bAKIA[0-9A-Z]{16}\b                                   # AWS access key
      | \beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+ # JWT
      | \bsk-[A-Za-z0-9]{16,}\b                                # OpenAI-style
      | \bghp_[A-Za-z0-9]{20,}\b                               # GitHub PAT
      | \bgho_[A-Za-z0-9]{20,}\b                               # GitHub OAuth
      | Bearer\s+[A-Za-z0-9._\-]{24,}                          # Bearer token
    )
    """
)

# GENERIC high-entropy run (first-party files ONLY; vendor/ is skipped). A
# standalone 40+ char base64/hex token: contiguous [A-Za-z0-9+/] with NO
# word separators (so snake_case identifiers and hyphenated names do NOT match).
# An entropy gate (mixed char classes + variety) further guards against long
# dictionary-ish words. base64url ("-"/"_") and JWT are handled by the concrete
# shape detectors above, so the generic run deliberately excludes "_" and "-".
_GENERIC_ENTROPY_RE = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{40,}(?![A-Za-z0-9+/])")

# Placeholder values that are NOT real secrets even if assigned to a token key.
_PLACEHOLDER_VALUES = {
    "changeme", "your-token-here", "yourtokenhere", "placeholder",
    "xxxxxxxx", "example", "redacted", "s3cret", "tok-123", "hc-tok",
    "your_token_here", "none", "null", "true", "false",
}


def _email_allowed(addr: str) -> bool:
    """True if ``addr`` is a known-safe, non-personal address (allowlist)."""
    low = addr.lower()
    if low in _EMAIL_ALLOWLIST:
        return True
    domain = low.rsplit("@", 1)[-1]
    return domain in _EMAIL_ALLOWLIST_DOMAINS


def _looks_high_entropy(s: str) -> bool:
    """Heuristic entropy gate: requires a mix of character classes so plain
    long identifiers / repeated runs do not trip the generic detector."""
    has_lower = any(c.islower() for c in s)
    has_upper = any(c.isupper() for c in s)
    has_digit = any(c.isdigit() for c in s)
    classes = sum((has_lower, has_upper, has_digit))
    if classes < 2:
        return False
    # Reject low-variety runs (e.g. "aaaa...") — need enough distinct chars.
    return len(set(s)) >= 12

# Registry / job pointer-record key signatures. A staged file whose parsed JSON
# (or content) carries these registry-shaped keys is .anchor / registry data.
_REGISTRY_KEY_SETS = (
    {"id", "name", "folder_path"},          # rnd registry entry
    {"job_id", "lane", "log_path"},          # job pointer-record
    {"projects"},                            # registry top-level container
)


# NOTE: there is NO inline suppression marker. No shipped file embeds a real
# secret, so no file needs an exemption — and no leaking product file can grant
# itself one. The scanner detects PII purely by pattern + allowlist.

# First-party prefixes that the GENERIC high-entropy heuristic applies to.
# Anything under vendor/ is third-party (documented PROVENANCE) and is SKIPPED
# by the generic heuristic to avoid false positives on minified KaTeX.
def _is_vendored(rel: str) -> bool:
    norm = rel.replace("\\", "/")
    return norm.startswith("vendor/") or "/vendor/" in norm


def _is_test_file(rel: str) -> bool:
    """True for shipped dev-only test files (``tests/...``)."""
    norm = rel.replace("\\", "/")
    return norm.startswith("tests/") or "/tests/" in norm


def _scan_text(rel: str, text: str):
    """Yield ``(rel, category, snippet)`` for each personal-data hit in text.

    Concrete-PII patterns run over ALL files (incl. vendor/). The GENERIC
    high-entropy heuristic runs ONLY over first-party files.
    """
    for m in _EMAIL_RE.finditer(text):
        addr = m.group(0)
        if _email_allowed(addr):
            continue
        yield (rel, "personal-email", addr)

    for m in _USERPATH_RE.finditer(text):
        acct = (m.group("acct") or "").lower()
        if acct in _USERPATH_ALLOWED_ACCOUNTS:
            continue
        yield (rel, "user-profile-path", _snip(m.group(0)))

    for m in _TOKEN_ASSIGN_QUOTED_RE.finditer(text):
        val = m.group("val")
        if val.lower() in _PLACEHOLDER_VALUES:
            continue
        yield (rel, "auth-token-value", _redact(m.group(0)))

    for m in _TOKEN_ASSIGN_UNQUOTED_RE.finditer(text):
        val = m.group("val")
        if val.lower() in _PLACEHOLDER_VALUES:
            continue
        yield (rel, "auth-token-value", _redact(m.group(0)))

    for m in _TOKEN_VALUE_RE.finditer(text):
        yield (rel, "secret-token-literal", _redact(m.group(0)))

    # GENERIC high-entropy detector + BUILD-HOST-PATH detector — first-party
    # (non-vendored) files only. Vendored skill files are host-path-scrubbed by
    # vendor_skills, so applying these to vendor/ would (a) false-fail on the
    # scrubbed-but-incidental and (b) be redundant; the concrete-PII detectors
    # above (email / Windows user-profile / token shapes) still run everywhere.
    if not _is_vendored(rel):
        for m in _WIN_DEVPATH_RE.finditer(text):
            if m.group("leaf").lower() in _HOSTPATH_ALLOWED_LEAVES:
                continue
            yield (rel, "build-host-path", _snip(m.group(0)))
        for m in _POSIX_HOMEPATH_RE.finditer(text):
            if m.group("leaf").lower() in _HOSTPATH_ALLOWED_LEAVES:
                continue
            yield (rel, "build-host-path", _snip(m.group(0)))
        for m in _GENERIC_ENTROPY_RE.finditer(text):
            run = m.group(0)
            if run.lower() in _PLACEHOLDER_VALUES:
                continue
            if _looks_high_entropy(run):
                yield (rel, "high-entropy-token", _redact(run))


def _scan_registry_artifact(rel: str, text: str):
    """Yield a hit if the file content is a registry / .anchor data artifact."""
    stripped = text.lstrip()
    if not stripped.startswith(("{", "[")):
        return
    try:
        data = json.loads(text)
    except (ValueError, json.JSONDecodeError):
        return
    objs = data if isinstance(data, list) else [data]
    for obj in objs:
        if not isinstance(obj, dict):
            continue
        keys = set(obj.keys())
        for sig in _REGISTRY_KEY_SETS:
            if sig <= keys:
                yield (rel, "registry-data-artifact",
                       "registry/.anchor JSON keys: " + ", ".join(sorted(sig)))
                return


# ── Third-party import scan (stdlib-only enforcement + pywinpty exception) ────

def _stdlib_module_names() -> frozenset:
    """The set of standard-library top-level module names.

    Uses ``sys.stdlib_module_names`` (Python 3.10+). On older interpreters
    (the product supports 3.8+) falls back to a curated superset of the stdlib
    modules Anchor actually imports plus the common ones, so the scan never
    false-positives a stdlib import as "third-party".
    """
    names = getattr(sys, "stdlib_module_names", None)
    if names:
        return frozenset(names)
    # Fallback for 3.8/3.9 — a generous stdlib allowlist.
    return frozenset({
        "__future__", "abc", "argparse", "ast", "asyncio", "base64", "bisect",
        "builtins", "bz2", "calendar", "collections", "concurrent",
        "configparser", "contextlib", "copy", "csv", "ctypes", "dataclasses",
        "datetime", "decimal", "difflib", "dis", "email", "enum", "errno",
        "fnmatch", "functools", "gc", "getpass", "glob", "gzip", "hashlib",
        "heapq", "hmac", "html", "http", "importlib", "inspect", "io",
        "ipaddress", "itertools", "json", "keyword", "linecache", "locale",
        "logging", "lzma", "math", "mimetypes", "multiprocessing", "operator",
        "os", "pathlib", "pickle", "pkgutil", "platform", "posixpath", "pprint",
        "queue", "random", "re", "secrets", "select", "selectors", "shlex",
        "shutil", "signal", "site", "socket", "socketserver", "sqlite3", "ssl",
        "stat", "string", "struct", "subprocess", "sys", "tempfile", "textwrap",
        "threading", "time", "timeit", "token", "tokenize", "traceback",
        "types", "typing", "unicodedata", "unittest", "urllib", "uuid",
        "warnings", "weakref", "webbrowser", "xml", "zipfile", "zlib",
    })


def _first_party_module_names(root: Path) -> frozenset:
    """Top-level first-party module names = the basenames of repo-root ``.py``
    files plus first-party packages (a dir with ``__init__.py``).

    These are NOT third-party imports — an Anchor module importing another
    Anchor module is fine. Derived from the on-disk tree, not hard-coded, so a
    new first-party module is recognized automatically.
    """
    names = set()
    try:
        for p in root.iterdir():
            if p.is_file() and p.suffix == ".py":
                names.add(p.stem)
            elif p.is_dir() and (p / "__init__.py").exists():
                names.add(p.name)
    except OSError:
        pass
    # The vendored brand/katex/xterm dirs are static assets, not import targets,
    # but ``tests`` is a first-party package (imported as ``tests.fake_claude``).
    names.add("tests")
    return frozenset(names)


def _import_top_levels(text: str):
    """Yield ``(top_level_module, lineno)`` for each import in Python source.

    Relative imports (``from . import x``) have no top-level module name and are
    skipped. Uses ``ast`` so commented-out / string-literal imports never trip.
    Unparseable source yields nothing (the text scan still runs over it).
    """
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".", 1)[0]
                if top:
                    yield top, node.lineno
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                continue  # relative import — first-party by construction
            if node.module:
                top = node.module.split(".", 1)[0]
                if top:
                    yield top, node.lineno


def _import_allowed(module: str, rel: str) -> bool:
    """True if ``module`` imported in first-party file ``rel`` is permitted.

    Permitted iff it is in the declared allowlist AND ``rel`` is one of the
    files that entry is scoped to (e.g. ``winpty`` only in ``pty_manager.py``).
    """
    entry = _THIRD_PARTY_IMPORT_ALLOWLIST.get(module)
    if entry is None:
        return False
    rel_norm = rel.replace("\\", "/")
    return rel_norm in entry["files"]


def scan_third_party_imports(files, root: Path | None = None):
    """Scan staged FIRST-PARTY ``.py`` files for undeclared third-party imports.

    ``files`` is a list of ``(relpath, abspath)`` pairs (the staged set). For
    each first-party (non-``vendor/``) ``.py`` file, every top-level import is
    checked: if it is neither stdlib nor a first-party Anchor module, it is a
    third-party / native dependency. Such an import FAILS the scan UNLESS it is
    the declared, file-scoped exception (``winpty`` in ``pty_manager.py``).

    Returns a list of ``(rel, "third-party-import", snippet)`` hits — empty when
    the staged product is stdlib-only modulo the declared pywinpty exception.

    vendor/ files are third-party by definition (documented PROVENANCE) and are
    NOT subject to this stdlib-only rule, mirroring the generic-entropy skip.
    """
    root = Path(root) if root else REPO_ROOT
    stdlib = _stdlib_module_names()
    first_party = _first_party_module_names(root)
    hits = []
    for rel, abspath in files:
        rel_norm = rel.replace("\\", "/")
        if not rel_norm.endswith(".py"):
            continue
        if _is_vendored(rel_norm):
            continue
        if _is_test_file(rel_norm):
            # tests/ are dev-only (shipped solely so a collaborator can run the
            # gate); pytest is a DECLARED dev dependency, not a product runtime
            # import. The stdlib-only rule governs the PRODUCT import path.
            continue
        try:
            text = abspath.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for module, lineno in _import_top_levels(text):
            if module in stdlib or module in first_party:
                continue
            if _import_allowed(module, rel_norm):
                continue
            hits.append((
                rel_norm,
                "third-party-import",
                f"undeclared non-stdlib import '{module}' (line {lineno})",
            ))
    return hits


def _snip(s: str, n: int = 60) -> str:
    s = s.replace("\n", " ")
    return s if len(s) <= n else s[:n] + "…"


def _redact(s: str) -> str:
    """Show the matched shape but not the full secret value in error output."""
    s = s.replace("\n", " ")
    return (s[:24] + "…") if len(s) > 24 else s


# Binary-ish extensions we read as bytes and skip text scanning for (fonts,
# images). They cannot carry the textual personal-data patterns we look for.
_BINARY_EXTS = {".woff", ".woff2", ".ttf", ".eot", ".png", ".ico",
                ".jpg", ".jpeg", ".gif", ".pdf"}


def scan_paths(files: list[tuple[str, Path]], root: Path | None = None):
    """Scan ``(relpath, abspath)`` pairs -> list of hits. Empty list == clean.

    Runs the personal-data / secret scan over every text file AND the
    third-party-import scan over first-party ``.py`` files (stdlib-only modulo
    the declared pywinpty exception). ``root`` (optional) is used to derive the
    first-party module set for the import scan; defaults to the repo root.
    """
    hits = []
    for rel, abspath in files:
        if Path(rel).suffix.lower() in _BINARY_EXTS:
            continue
        try:
            text = abspath.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue  # treat undecodable as binary; no textual scan
        hits.extend(_scan_text(rel, text))
        hits.extend(_scan_registry_artifact(rel, text))
    hits.extend(scan_third_party_imports(files, root=root))
    return hits


def scan_staged_dir(staging: Path):
    """Scan an already-staged export dir. Returns the hit list."""
    staging = Path(staging)
    files = []
    for p in sorted(staging.rglob("*")):
        if p.is_file():
            files.append((p.relative_to(staging).as_posix(), p))
    return scan_paths(files)


# ── README emission (AC3) ────────────────────────────────────────────────────

_README = """# Anchor — per-project R&D control surface

Anchor turns a task/project tracker into a per-project **R&D control surface**:
each code project is a folder, and a single dashboard drives the
**researchPrime → Crucible → Foreman** trio as durable, server-owned jobs with
versioned effort history, task↔project integration, and deliverable execution.

This is a **clean, data-free distribution** — it ships only the product code and
dependency-free assets. There is no personal task/project data, no R&D registry,
and no `.anchor/` store in this export; you start from an empty state.

## Requirements
- Python 3.8+ (the shipped product is **Python standard library only** — with
  ONE optional, isolated exception: the v3 ConPTY terminal subsystem can use the
  native `pywinpty` package).
- **Optional terminal extra (`pywinpty`):** real in-browser ConPTY terminals
  (`pty_manager.py`) need `pywinpty` (`pip install .[terminal]`, Windows only).
  It is imported LAZILY and ONLY by the terminal subsystem — if absent, the
  terminal feature reports "real terminal unavailable" and the rest of Anchor is
  unaffected. The core import path stays stdlib-only.
- Optional system tools, invoked as subprocesses when present: `claude`
  (Claude Code), `git`, `latexmk` (for PDF reports).

## Run
```
python anchor_gui.py --no-browser      # local web server (default :8777)
```
Then open the dashboard in your browser.

## Develop / test
`pytest` is a dev-only dependency (not shipped at runtime):
```
pip install -e ".[dev]"
python -m pytest -v
```

## Layout
- `anchor_gui.py` — the dashboard server (main interface).
- `anchor.py` — CLI engine.
- `paths.py`, `rnd_registry.py`, `job_runner.py`, `gate_adapter.py`,
  `lanes.py`, `effort_history.py`, `report_viewer.py`, `dir_browser.py`,
  `anchor_healthcheck.py` — supporting modules.
- `vendor/katex/` — vendored KaTeX (math rendering for the report viewer).
- `dist_manifest.txt` — the deny-by-default shippable-file manifest.

## License
See `LICENSE` if present, otherwise all rights reserved by the author.
"""


def emit_readme(staging: Path) -> Path:
    """Write README.md into the staging dir (AC3). Returns its path."""
    readme = Path(staging) / "README.md"
    readme.write_text(_README, encoding="utf-8")
    return readme


# ── Build ────────────────────────────────────────────────────────────────────

def build_distro(root: Path | None = None,
                 output_dir: Path | None = None,
                 manifest_path: Path | None = None,
                 emit_readme_file: bool = True,
                 cleanup_on_fail: bool = True,
                 vendor_skills_: bool = True,
                 vendor_sources=None):
    """Build a data-free export into ``output_dir`` and scan it.

    Steps:
      1. Select shippable files (deny-by-default, manifest is the truth).
      2. Stage them into ``output_dir`` (created; existing contents replaced).
      3. GENERATE the vendored bundled skills into the export (via
         ``vendor_skills.vendor_all`` — ``git archive`` of each env-injected
         source + denylist + host-path/PII scrub) when ``vendor_skills_`` is
         True. The generated files are NOT copied from ``root`` (they don't
         exist there); they are produced directly into the export and scanned
         like everything else. The manifest entry ``vendor/bundled-skills/**``
         is what KEEPS them (deny-by-default).
      4. Emit README.md (AC3).
      5. Run the no-personal-data scan over the staged set.
         - Any hit -> raise :class:`PersonalDataError` naming the file(s);
           the staging dir is torn down (``cleanup_on_fail``) so nothing leaks.

    Returns a report dict on success:
      ``{"staging": Path, "files": [relpaths...], "readme": Path,
         "vendored_skills": <vendor_all report or None>}``.

    Never publishes/pushes — produces a local export dir only.
    """
    root = Path(root) if root else REPO_ROOT
    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp(prefix="anchor-distro-"))
    else:
        output_dir = Path(output_dir)
        if output_dir.exists():
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

    selected = select_shippable(root=root, manifest_path=manifest_path)

    staged_pairs = []
    for rel in selected:
        src = root / rel
        dst = output_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        staged_pairs.append((rel, dst))

    # Generate the vendored bundled skills INTO the export (not copied from
    # root). Honest SKIP when a source env is unset (vendor_all returns those in
    # its "skipped" list — never a hardcoded real-path fallback). The produced
    # files are added to the staged set + report so they are both kept AND
    # scanned (they must pass the same clean-scan gate as everything else).
    vendor_report = None
    if vendor_skills_:
        import vendor_skills  # local import: keeps distro importable if absent
        vendor_report = vendor_skills.vendor_all(output_dir, sources=vendor_sources)
        bundle_root = output_dir / "vendor" / "bundled-skills"
        if bundle_root.exists():
            for p in sorted(bundle_root.rglob("*")):
                if not p.is_file():
                    continue
                rel = p.relative_to(output_dir).as_posix()
                staged_pairs.append((rel, p))
                if rel not in selected:
                    selected.append(rel)
                    
    # Generate the skill-integrity hash manifest for the bundled skills
    try:
        import foundry_integrity
        skills_root = output_dir / "vendor" / "bundled-skills"
        if skills_root.exists():
            manifest = foundry_integrity.build_manifest(skills_root)
            manifest_path = output_dir / foundry_integrity.MANIFEST_FILENAME
            manifest_text = json.dumps(manifest, indent=2) + "\n"
            manifest_path.write_text(manifest_text, encoding="utf-8")
            
            manifest_rel = manifest_path.relative_to(output_dir).as_posix()
            staged_pairs.append((manifest_rel, manifest_path))
            if manifest_rel not in selected:
                selected.append(manifest_rel)
    except Exception as e:
        import logging
        logging.getLogger("distro").error("Failed to build skill-integrity manifest: %s", e)

    readme_path = emit_readme(output_dir) if emit_readme_file else None

    # Scan the staged set (NOT the source tree) — what we'd actually ship. The
    # import scan derives first-party module names from the SOURCE ``root`` being
    # built (so a custom test tree's modules are recognized as first-party).
    scan_pairs = list(staged_pairs)
    if readme_path is not None:
        scan_pairs.append(("README.md", readme_path))
    hits = scan_paths(scan_pairs, root=root)
    if hits:
        if cleanup_on_fail:
            shutil.rmtree(output_dir, ignore_errors=True)
        raise PersonalDataError(hits)

    return {
        "staging": output_dir,
        "files": selected,
        "readme": readme_path,
        "vendored_skills": vendor_report,
    }


def publish_distro(dest: Path | None = None, remote_cmd: str | None = None) -> dict:
    """Build, scan-gate, and push to a private GitHub repository.

    Aborts BEFORE any git or push operations if the scan fails.
    """
    import subprocess
    import os

    gh_cmd = remote_cmd or os.environ.get("ANCHOR_GH_CMD")
    if not gh_cmd and not shutil.which("gh"):
        print("Manual path: 'gh' CLI not found. Please push manually.")
        gh_available = False
    else:
        gh_available = True

    # The clean-scan GATE. Raises PersonalDataError on failure.
    report = build_distro(output_dir=dest, emit_readme_file=True, cleanup_on_fail=False)
    staging = report["staging"]

    if not gh_available:
        return {"status": "manual", "staging": staging}

    # git init + commit
    subprocess.run(["git", "init"], cwd=staging, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=staging, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=staging, check=True, capture_output=True)

    # gh repo create --private + push
    if gh_cmd:
        cmd_parts = gh_cmd.split()
        subprocess.run(cmd_parts + ["repo", "create", "--private"], cwd=staging, check=True, capture_output=True)
        subprocess.run(cmd_parts + ["push"], cwd=staging, check=True, capture_output=True)
    else:
        subprocess.run(["gh", "repo", "create", "--private", "--source=.", "--remote=origin", "--push"], cwd=staging, check=True, capture_output=True)

    return {"status": "published", "staging": staging}


# ── CLI ──────────────────────────────────────────────────────────────────────

def _main(argv=None):
    import argparse

    ap = argparse.ArgumentParser(
        description="Build a data-free Anchor distribution and scan it."
    )
    ap.add_argument("-o", "--output", default=None,
                    help="output/staging dir (default: a fresh tmp dir)")
    ap.add_argument("--no-readme", action="store_true",
                    help="do not emit README.md")
    args = ap.parse_args(argv)

    try:
        report = build_distro(
            output_dir=Path(args.output) if args.output else None,
            emit_readme_file=not args.no_readme,
        )
    except PersonalDataError as exc:
        print("BUILD FAILED:\n" + str(exc))
        return 2

    print(f"Built data-free export -> {report['staging']}")
    print(f"  {len(report['files'])} files staged; scan clean.")
    if report["readme"]:
        print(f"  README: {report['readme']}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_main())
