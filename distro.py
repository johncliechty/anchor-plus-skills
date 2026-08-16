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
    "ecgberht@anchor.local",   # git identity used by commission_session campaign auto-commits
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


class ImportClosureError(Exception):
    """The staged set is import-incomplete — a staged product file imports a
    first-party module that is NOT staged (and not declared optional).

    THE v1.1.x SHARE INCIDENT CLASS (friction-intake-2026-07-30): eleven
    runtime modules (reaper / freeze_state / zombie_hunter / proc_probe / …)
    existed on the author machine but were absent from ``dist_manifest.txt``.
    Because every consumer imports them LAZILY inside try/except, the
    startup-import gate stayed green while collaborator installs booted
    degraded and spammed ModuleNotFoundError. A content scan cannot catch an
    ABSENT file, and a top-level import probe cannot catch a lazy import —
    only a static walk of every import in every staged file can. This gate is
    that walk. ``hits`` mirrors :class:`PersonalDataError`.
    """

    def __init__(self, hits):
        self.hits = list(hits)
        lines = [f"  {rel}: {cat}: {snip}" for (rel, cat, snip) in self.hits]
        super().__init__(
            "import-closure gate FAILED — staged files import UNSTAGED "
            "first-party module(s):\n" + "\n".join(lines)
        )


class ScrubResidueError(Exception):
    """A staged file carries a SCRUBBED path token still followed by a file
    target — i.e. a reference the PII scrub relocated to nowhere.

    THE v1.2 CLASS: every vendored ``SKILL.md`` deferred its run contract to
    ``C:\\dev\\Skill Foundry\\AGENTS.md``. The no-personal-data scan correctly
    rewrote the author path to the ``<path>`` token and, in doing so, converted
    a diagnosable absolute path into an unresolvable string — ten staged files
    shipped pointing at ``<path> Foundry\\AGENTS.md``, so the LOCKED 10-minute
    status-table format was undefined on every collaborator machine while all
    gates stayed green. The artifact linked; the symbol was missing.

    Deliberately NARROW. A general "does every referenced doc exist" gate was
    refuted cross-family: staged prose legitimately names unstaged files
    (DASHBOARD.md, MASTER-PLAN.md, friction-intake-*.md), so its false-positive
    rate would force an unmanageable optional-list and the gate would be turned
    off. This one fires ONLY on the scrub-residue shape — measured against the
    real v1.2.2 tree: 10 hits, 1 distinct pattern, 0 false positives.
    """

    def __init__(self, hits):
        self.hits = list(hits)
        lines = [f"  {rel}: {cat}: {snip}" for (rel, cat, snip) in self.hits]
        super().__init__(
            "scrub-residue gate FAILED — staged file(s) point at a SCRUBBED "
            "path that resolves to nothing:\n" + "\n".join(lines)
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
    # ``!pattern`` lines are explicit DENIALS: a file matching one never ships
    # even when an allow-pattern (e.g. the tests/test_*.py wildcard) covers it.
    # This is how PII-planting test files (scrub/redaction suites that embed
    # synthetic secrets BY DESIGN) stay out of the stranger-facing bundle
    # without weakening either the tests or the scanner.
    denies = [p[1:] for p in patterns if p.startswith("!")]
    allows = [p for p in patterns if not p.startswith("!")]
    selected = []
    for rel_posix, _abs in _iter_repo_files(root):
        if _match_any(rel_posix, allows) and not _match_any(rel_posix, denies):
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
    "ecgberht",   # author's Ecgberht steward-engine source (doc/comment in
                  # route_table's TW5/TW6 section headers; same class as trio)
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

# A dotted identifier chain (``panel.token``, ``process.env.X``,
# ``body.confirmToken``) — a code READ of a runtime value, never a pasted
# secret literal. Generalizes the old self./cls. special case (v1.1.3). A
# real dotted secret (a JWT) is caught by its concrete shape detector.
_DOTTED_CHAIN_RE = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_$]*)+")

# A bare SCREAMING_SNAKE identifier (``TEST_TOKEN``) as an UNQUOTED assign
# value (``token=TEST_TOKEN`` in a call/kwarg) is a code READ of a named
# constant — the identifier form of the dotted-chain rule. The shape requires
# an underscore (constant-name form), and the caller additionally gates on a
# NON-high-entropy value, so an all-caps pasted secret still trips.
_CONST_IDENT_RE = re.compile(r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+")


def _is_code_expression_value(val: str) -> bool:
    """True when an assign-pattern "value" is code, not a secret literal:
    a call expression (contains parens — ``encodeURIComponent(tok)``) or a
    dotted identifier chain. Secret literals contain neither."""
    if "(" in val or ")" in val:
        return True
    return _DOTTED_CHAIN_RE.fullmatch(val) is not None


# Placeholder values that are NOT real secrets even if assigned to a token key.
_PLACEHOLDER_VALUES = {
    "changeme", "your-token-here", "yourtokenhere", "placeholder",
    "xxxxxxxx", "example", "redacted", "s3cret", "tok-123", "hc-tok",
    "your_token_here", "none", "null", "true", "false",
    "__anchor_token__",  # anchor_gui's serve-time template placeholder (the
                         # literal is replaced with the real token per request)
    "confirm-",          # skill_runner's mint prefix: token = "confirm-" +
                         # os.urandom(16).hex() — the literal is a label only
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

    # v1.1.3: the KEY-assignment detectors are tuned for first-party Python;
    # over VENDORED skill payloads (already host-path/PII-scrubbed at vendor
    # time, with PROVENANCE) they false-fired on JS config reads and named
    # fixture strings — which the retired side builder handled by silently
    # filtering ALL hits. Now, honestly and narrowly: code-expression values
    # are skipped everywhere, and for vendored files an assign hit must carry
    # a plausibly-REAL (high-entropy) value. The concrete secret SHAPES
    # (AKIA / JWT / sk- / ghp_ / Bearer) still run over every file unchanged.
    _vendored = _is_vendored(rel)
    for m in _TOKEN_ASSIGN_QUOTED_RE.finditer(text):
        val = m.group("val")
        if val.lower() in _PLACEHOLDER_VALUES:
            continue
        if _is_code_expression_value(val):
            continue
        if _vendored and not _looks_high_entropy(val):
            continue
        yield (rel, "auth-token-value", _redact(m.group(0)))

    for m in _TOKEN_ASSIGN_UNQUOTED_RE.finditer(text):
        val = m.group("val")
        if val.lower() in _PLACEHOLDER_VALUES:
            continue
        # An unquoted "value" that is an attribute path (``self.token``,
        # ``cls.auth_token``, ``panel.token``, ``process.env.X``), a call
        # expression, or a bare SCREAMING_SNAKE constant name is a code READ
        # of a runtime value, never a secret literal — the rule exists to
        # catch pasted literals.
        if val.startswith(("self.", "cls.")) or _is_code_expression_value(val):
            continue
        if _CONST_IDENT_RE.fullmatch(val) and not _looks_high_entropy(val):
            continue
        if _vendored and not _looks_high_entropy(val):
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


# ── Import-closure gate (v1.1.3 share-fix) ───────────────────────────────────
#
# First-party modules a staged file may import WITHOUT them being staged. Each
# entry is a DELIBERATE, documented exclusion whose every consumer degrades
# safely when it is absent (lazy import inside try/except). Anything else that
# is first-party-in-source but missing from the staged set fails the build.
_OPTIONAL_FIRST_PARTY = {
    "update_transaction": (
        "deliberately NOT shipped (see the doctor.py manifest block): its "
        "closure drags the foundry update subsystem; anchor.py and doctor.py "
        "import it lazily inside try/except and skip silently when absent"
    ),
    "tools": (
        "dev-only rearch package (extract/census/spike/drain scripts) — never "
        "ships. journal.py's write-tripwire pairing degrades to a no-op "
        "without it (documented best-effort import), and the healthcheck's "
        "journal-parity rebuild walk skip-warns when it is absent"
    ),
    "chamber_mockup_diff": (
        "test-only signed-mockup hash pin/diff (steward-chamber W6/W7) — "
        "never ships: its data document (the signed mockups.html) lives under "
        "planning/, which the manifest excludes. Its one product consumer, "
        "chamber_rail.mockup_css, imports it lazily inside try/except and "
        "degrades to the scoped W6 stylesheet when it is absent (honest "
        "degraded styling; the C9 CI diff gate owns the pin)"
    ),
}


#: The scrub-residue shape: a ``<path>`` token the no-personal-data scan left
#: behind, still followed (within a short window) by a path-shaped file target.
#: A bare ``<path>`` is fine — SOURCES.md uses it as a deliberate provenance
#: placeholder with no target. It is the token PLUS a target that proves a real
#: reference was relocated to nowhere.
_SCRUB_RESIDUE_RE = re.compile(
    r"<path>[^\s]{0,40}[ \t]?[A-Za-z0-9_.-]{0,40}[\\/][A-Za-z0-9_.-]+"
    r"\.(?:md|json|mjs|py|txt|ps1|cmd)"
)

#: Text extensions worth scanning. Binary/vendored assets are out of scope.
_SCRUB_SCAN_SUFFIXES = (".md", ".txt", ".json", ".py", ".mjs", ".js", ".ps1", ".cmd")


def scan_scrub_residue(files):
    """Find staged files pointing at a SCRUBBED path. Empty list == clean.

    Returns ``(rel, "scrub-residue", detail)`` hits, mirroring the other
    scanners. See :class:`ScrubResidueError` for why this is narrow by design.
    """
    hits = []
    for rel, abspath in files:
        rel_norm = str(rel).replace("\\", "/")
        if not rel_norm.lower().endswith(_SCRUB_SCAN_SUFFIXES):
            continue
        try:
            text = Path(abspath).read_text(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            continue
        seen = set()
        for m in _SCRUB_RESIDUE_RE.finditer(text):
            frag = m.group(0)
            if frag in seen:
                continue
            seen.add(frag)
            hits.append((
                rel_norm, "scrub-residue",
                "reference relocated to nowhere by the PII scrub: %r" % frag,
            ))
    return hits


def scan_import_closure(files, root: Path | None = None, extra_optional=()):
    """Static import-closure over the staged set. Empty list == closed.

    For every staged, first-party (non-``vendor/``, non-``tests/``) ``.py``
    file, EVERY import — module-scope or lazy-inside-a-function (``ast.walk``
    sees both) — of a module that is first-party in the SOURCE tree must
    resolve to a module in the STAGED set, or sit in the declared
    :data:`_OPTIONAL_FIRST_PARTY` list. Anything else is a
    ships-broken-by-omission gap: the file will ImportError (module-level) or
    log-and-degrade (lazy) on a stranger install.

    ``extra_optional`` extends the optional list for a SPARSER package that
    deliberately omits modules whose consumers degrade (e.g. Package A —
    skills-only — omits anchor.py/lanes.py, which onboard.py probes lazily
    inside try/except). The full Package B build passes nothing extra.

    Returns ``(rel, "import-closure", detail)`` hits, mirroring the other
    scanners. Stdlib/third-party imports are out of scope here (the
    third-party scan owns those).
    """
    root = Path(root) if root else REPO_ROOT
    optional = set(_OPTIONAL_FIRST_PARTY) | set(extra_optional)
    first_party = _first_party_module_names(root)
    staged_names = set()
    staged_pys = []
    for rel, abspath in files:
        rel_norm = rel.replace("\\", "/")
        if not rel_norm.endswith(".py"):
            continue
        if "/" not in rel_norm:
            staged_names.add(rel_norm[:-3])
        elif rel_norm.endswith("/__init__.py"):
            # A staged package: its top-level dir name is importable.
            staged_names.add(rel_norm.split("/", 1)[0])
        staged_pys.append((rel_norm, abspath))
    # ``tests`` ships (dev-only) and is a first-party package name.
    staged_names.add("tests")

    hits = []
    for rel_norm, abspath in staged_pys:
        if _is_vendored(rel_norm) or _is_test_file(rel_norm):
            continue
        try:
            text = abspath.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for module, lineno in _import_top_levels(text):
            if module not in first_party:
                continue  # stdlib / third-party — not this gate's job
            if module in staged_names or module in optional:
                continue
            hits.append((
                rel_norm,
                "import-closure",
                f"imports first-party '{module}' (line {lineno}) which is "
                f"NOT staged and not declared optional",
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


#: Modules the shipped bundle MUST import for the server to start. ``anchor_gui``
#: is effectively the whole product: it pulls the route table, the foundry GUI
#: chain, the terminal stack and the summarizer in at module scope.
STARTUP_IMPORTS = ("anchor_gui", "anchor")


class StartupImportError(Exception):
    """The staged export cannot be imported — the bundle would not start."""


def scan_startup_imports(staging: Path, timeout: int = 180) -> list:
    """Import the staged bundle in a subprocess; return failures as scan hits.

    WHY THIS EXISTS (2026-07-26). ``dist_manifest.txt`` is deny-by-default and
    every other check here reads file CONTENT — none of them ever loaded the
    result. So when ``foundry_map_v2.schema.json`` was never added to the
    manifest, the build stayed green while shipping a bundle whose very first
    import raised FileNotFoundError: ``anchor_gui`` → ``foundry_gui`` →
    ``foundry_autoload`` → ``foundry_map``, which resolves its schema at MODULE
    SCOPE. The public v1.1.0 tag went out that way and could not start at all.

    A content scan structurally cannot catch a file that is simply ABSENT. Only
    loading the thing can. This runs the staged tree in a CHILD process with a
    throwaway data dir and the stub PTY backend, so it never touches real data
    and never binds a port.
    """
    import os
    import subprocess
    import tempfile as _tf

    staging = Path(staging)
    # Gate only the startup modules this bundle actually STAGES. A sparse
    # bundle (docs-only export, fixture tree in tests) does not ship the app,
    # so "would it start" is not a question it has to answer; a real bundle
    # stages anchor.py / anchor_gui.py and keeps the full gate.
    gated = [mod for mod in STARTUP_IMPORTS
             if (staging / (mod + ".py")).is_file()
             or (staging / mod / "__init__.py").is_file()]
    hits = []
    if not gated:
        return hits
    with _tf.TemporaryDirectory(prefix="anchor-import-gate-") as tmp:
        env = dict(os.environ)
        env["ANCHOR_DATA_DIR"] = tmp
        env["ANCHOR_PTY_BACKEND"] = "stub"
        env["PYTHONIOENCODING"] = "utf-8"
        # The gate must not MUTATE the staging tree it validates: without this
        # the child interpreter writes __pycache__/*.pyc into the export, which
        # then ships (and fails staged-set == manifest-selection equality).
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        for mod in gated:
            try:
                proc = subprocess.run(
                    [sys.executable, "-c", "import " + mod],
                    cwd=str(staging), env=env, timeout=timeout,
                    capture_output=True, text=True, errors="replace")
            except (OSError, subprocess.SubprocessError) as exc:
                hits.append((mod, "startup-import", "could not run: %s" % exc))
                continue
            if proc.returncode != 0:
                tail = (proc.stderr or "").strip().splitlines()
                hits.append((mod, "startup-import",
                             tail[-1] if tail else "exit %s" % proc.returncode))
    return hits


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


# ── Consumer agent-context file (v1.1.3 token-burn discipline) ───────────────
#
# The package used to ship with NO agent-context file, so a collaborator asking
# Claude "why is Anchor broken?" explored blind: reading the 18k-line
# anchor_gui.py whole, crawling the 13 vendored skills, or invoking the paid
# multi-agent trio as a debug tool — burning their usage limits on what a
# deterministic probe answers for free. This THIN consumer CLAUDE.md (emitted
# at build time; NEVER the author's own CLAUDE.md, which stays unstaged) gives
# any agent the cheap path first. Keep it short — it is loaded into every
# agent session a collaborator runs in the package tree.
_CONSUMER_CLAUDE_MD = """# Anchor — collaborator install (agent notes)

This is a data-free Anchor distribution. Read this before exploring.

## Debugging an install: cheap checks FIRST
1. `python doctor.py` — deterministic install health (missing modules,
   pywinpty, engine CLIs, token, server). No model calls, free.
2. Tail `logs/errors.log` INSIDE THIS PACKAGE FOLDER (the package dir is the
   default data dir) — boot problems land there.
3. Only then read code, and read it NARROWLY.

## Reading rules (token discipline)
- Do NOT read `anchor_gui.py` end-to-end (18,000+ lines) — grep for the
  symbol you need and read that region only.
- Do NOT crawl `vendor/bundled-skills/` — those are 13 packaged skills, not
  app code.
- Do NOT bulk-scan `starter/`, `static/`, or `vendor/` trees.

## Paid tools are not debug tools
researchPrime / Crucible / Foreman / Gandalf are intentional MULTI-AGENT
skills: one invocation fans out many model calls against the user's paid
subscription. Never invoke them to diagnose an install problem.

## Running Anchor
- Start: `python launch_anchor_dashboard.py` (starts the server if needed,
  then opens the dashboard). After a reboot, run it again.
- The server is `anchor_gui.py` (Python stdlib only; optional `pywinpty` for
  real terminals). Default port 8777, loopback only.
- The API token lives OUTSIDE this tree (default
  `~/.anchor/.anchor/onboard-token`); the launcher wires it automatically.
"""


def emit_claude_md(staging: Path) -> Path:
    """Write the thin consumer CLAUDE.md into the staging dir. Returns path."""
    p = Path(staging) / "CLAUDE.md"
    p.write_text(_CONSUMER_CLAUDE_MD, encoding="utf-8")
    return p


# The collaborator-facing run contract + autonomy guide. SOURCE lives under
# ``planning/share-v1.2/`` (which the manifest excludes) and is EMITTED to the
# staged root at build time — deliberately NOT kept at the author repo root,
# where an ``AGENTS.md`` would hijack the AGENTS.md-is-canonical convention and
# be read as this project's own instructions rather than as shipped product.
#
# WHY THESE SHIP (2026-08): every vendored SKILL.md defers its run contract to
# "user-global AGENTS.md" and to the Skill Foundry AGENTS.md — neither of which
# is in the bundle. Ten staged files carried a scrubbed ``<path> Foundry\\AGENTS.md``
# pointing at nothing, so the LOCKED 10-minute status-table format (the single
# most visible skill behavior) was undefined on every collaborator machine.
_EMITTED_DOCS = (
    ("AGENTS.md", "planning/share-v1.2/AGENTS.md"),
    ("AUTONOMOUS-MODE.md", "planning/share-v1.2/AUTONOMOUS-MODE.md"),
    # v1.2.4: the Elegance Law + the researchPrime-vetted Rabbit-Catcher
    # battery (Part II). Every vendored SKILL.md carries the binding block
    # inline AND points at ELEGANCE.md Part II for the full battery — the
    # pointer must resolve in the bundle (the dangling-AGENTS.md lesson).
    ("ELEGANCE.md", "planning/share-v1.2/ELEGANCE.md"),
)


def emit_share_docs(staging: Path, root: Path | None = None) -> list:
    """Emit the collaborator run-contract docs into staging.

    Returns ``[(rel, path), ...]`` for the content scanners, mirroring the
    README/CLAUDE.md emitters. Fail-closed: a missing source raises rather than
    silently shipping a bundle whose SKILL.md pointers dangle.
    """
    root = Path(root) if root else REPO_ROOT
    out = []
    for rel, src_rel in _EMITTED_DOCS:
        src = root / src_rel
        if not src.is_file():
            raise FileNotFoundError(
                "share doc source missing: %s (every vendored SKILL.md points at "
                "AGENTS.md; shipping without it re-creates the dangling-pointer "
                "defect)" % src_rel
            )
        p = Path(staging) / rel
        p.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        out.append((rel, p))
    return out


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
                    
    # Generate the skill-integrity hash manifest for the bundled skills.
    # Only when vendoring ran (vendor_skills_): otherwise a custom test tree
    # must not grow a vendor/ tree or a root-level hash map. The file MUST live
    # under vendor/bundled-skills/ (not the export root): it is a map of sha256
    # digests and would trip the first-party high-entropy clean-scan if staged
    # as a root-level product file. Vendored paths skip that heuristic
    # (concrete PII detectors still run).
    if vendor_skills_:
        try:
            import foundry_integrity
            skills_root = output_dir / "vendor" / "bundled-skills"
            if skills_root.exists():
                skill_manifest = foundry_integrity.build_manifest(skills_root)
                # Skip empty manifests (no skills vendored / no hashed files).
                if skill_manifest:
                    skill_manifest_path = (
                        skills_root / foundry_integrity.MANIFEST_FILENAME
                    )
                    skill_manifest_path.write_text(
                        json.dumps(skill_manifest, indent=2) + "\n",
                        encoding="utf-8",
                    )
                    skill_manifest_rel = skill_manifest_path.relative_to(
                        output_dir
                    ).as_posix()
                    staged_pairs.append((skill_manifest_rel, skill_manifest_path))
                    if skill_manifest_rel not in selected:
                        selected.append(skill_manifest_rel)
        except Exception as e:
            import logging
            logging.getLogger("distro").error(
                "Failed to build skill-integrity manifest: %s", e
            )

    readme_path = emit_readme(output_dir) if emit_readme_file else None
    # The thin consumer agent-context file (v1.1.3): emitted like the README —
    # generated at build time, never copied from the author tree (the author's
    # own CLAUDE.md is deliberately NOT on the manifest and never ships).
    claude_md_path = emit_claude_md(output_dir) if emit_readme_file else None
    # Gated on ``vendor_skills_`` for the same reason the vendor tree is: a
    # custom test tree must not be forced to carry the product's doc sources.
    # The coupling is semantic, not incidental — these docs exist to satisfy the
    # VENDORED skills' governance pointers, so a build with no vendored skills
    # has nothing to point at. Every real product build vendors, so the
    # fail-closed guarantee is intact where it matters.
    share_docs = (emit_share_docs(output_dir, root=root)
                  if (emit_readme_file and vendor_skills_) else [])

    # Scan the staged set (NOT the source tree) — what we'd actually ship. The
    # import scan derives first-party module names from the SOURCE ``root`` being
    # built (so a custom test tree's modules are recognized as first-party).
    scan_pairs = list(staged_pairs)
    if readme_path is not None:
        scan_pairs.append(("README.md", readme_path))
    if claude_md_path is not None:
        scan_pairs.append(("CLAUDE.md", claude_md_path))
    scan_pairs.extend(share_docs)
    hits = scan_paths(scan_pairs, root=root)
    if hits:
        if cleanup_on_fail:
            shutil.rmtree(output_dir, ignore_errors=True)
        raise PersonalDataError(hits)

    # IMPORT-CLOSURE GATE (v1.1.3): a staged product file must never import a
    # first-party module that is absent from the staged set (unless declared
    # optional). Static, sees LAZY imports too — the exact class of gap the
    # 2026-07-30 collaborator incident shipped (reaper/freeze_state/… existed
    # in source, were unlisted in the manifest, and every import was lazy, so
    # both the content scans and the startup-import probe stayed green).
    closure_hits = scan_import_closure(scan_pairs, root=root)
    if closure_hits:
        if cleanup_on_fail:
            shutil.rmtree(output_dir, ignore_errors=True)
        raise ImportClosureError(closure_hits)

    # SCRUB-RESIDUE GATE (v1.2): the no-personal-data scan rewrites author paths
    # to a ``<path>`` token. Where the reference had a FILE TARGET, that rewrite
    # leaves a pointer to nothing — the v1.2 dangling-AGENTS.md class. Runs
    # AFTER the PII scan by construction: it audits that scan's own output.
    residue_hits = scan_scrub_residue(scan_pairs)
    if residue_hits:
        if cleanup_on_fail:
            shutil.rmtree(output_dir, ignore_errors=True)
        raise ScrubResidueError(residue_hits)

    # STARTUP GATE: everything above reads file CONTENT, which structurally
    # cannot detect a file that is simply ABSENT from the manifest. Load the
    # staged bundle and confirm it imports before calling the build good.
    import_hits = scan_startup_imports(output_dir)
    if import_hits:
        if cleanup_on_fail:
            shutil.rmtree(output_dir, ignore_errors=True)
        raise StartupImportError(
            "the staged bundle does not import (it would not start):\n"
            + "\n".join("  %s: %s: %s" % h for h in import_hits))

    return {
        "staging": output_dir,
        "files": selected,
        "readme": readme_path,
        "claude_md": claude_md_path,
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
    except StartupImportError as exc:
        print("BUILD FAILED:\n" + str(exc))
        return 3
    except ImportClosureError as exc:
        print("BUILD FAILED:\n" + str(exc))
        return 4

    print(f"Built data-free export -> {report['staging']}")
    print(f"  {len(report['files'])} files staged; scan clean.")
    if report["readme"]:
        print(f"  README: {report['readme']}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_main())
