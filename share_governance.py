"""Governance pack generator for Shareable Anchor + Skills (W4).

Builds an exportable, version-stamped operating-rules pack from canonical
AGENTS.md-style sources plus a host-personal denylist:

* ``AGENTS.md`` — scrubbed, version-stamped exportable rules
* ``CLAUDE.md`` / ``GEMINI.md`` — thin pointers to AGENTS.md

Pack content (NS 5; Master Plan P2): Status-table 10-minute format, seating
law (prefs → family → subscription CLI), skill immutability vs Foundry edit
path, journal/run-capture expectations; Foundry sleep labeled **future-ready**
(not v1-complete).

Golden fixture CI: generated pack after denylist must match the golden tree
and contain no author absolute paths (stranger-machine assertion).

Extends the share stack — does not invent a second distro. Stdlib only.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

_MODULE_DIR = Path(__file__).resolve().parent

# Schema / pack identity (semver for the exportable pack body).
GOVERNANCE_PACK_VERSION = "1.0.0"
GOVERNANCE_SCHEMA = "share-governance-pack/v1"

# Default host-personal denylist tokens (literal substrings scrubbed first).
# Tests inject author-shaped paths; production generate also strips these.
DEFAULT_HOST_PERSONAL_DENYLIST = (
    # Concat form avoids Python ``\U`` unicode-escape in string literals.
    "C:\\" + "Users\\john",
    "C:\\" + "Users\\John",
    "/Users/john",
    "/home/john",
    "C:\\" + "dev\\Skill Foundry",
    "C:\\" + "dev\\trio",
    "C:\\" + "dev\\Anchor",
    "C:\\" + "dev\\plans",
    "John Liechty",
    "J.C. Liechty",
)

# Residual path/email scrub (mirrors vendor_skills residual rules — reuse style,
# not a second scrub stack).
_WIN_USER_RE = re.compile(
    r"[A-Za-z]:\\Users\\[^\s\"'<>|]*",
    re.IGNORECASE,
)
_WIN_DEV_RE = re.compile(
    r"[A-Za-z]:\\(?:[^\s\"'<>|]*\\)?dev\\[^\s\"'<>|]*",
)
_POSIX_HOME_RE = re.compile(
    r"/(?:Users|home)/[^/\s\"'<>|]+(?:/[^\s\"'<>|]*)?",
)
_EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}",
)

# Author-path detectors for stranger-machine assertions (fail if any remain).
AUTHOR_PATH_RES = (
    re.compile(r"[A-Za-z]:\\Users\\", re.IGNORECASE),
    re.compile(r"/(?:Users|home)/[^/\s\"'<>|]+"),
    re.compile(r"[A-Za-z]:\\dev\\", re.IGNORECASE),
)

PATH_PLACEHOLDER = "<path>"
EMAIL_PLACEHOLDER = "<email>"

# Required section markers the exportable pack MUST include.
REQUIRED_SECTION_MARKERS = (
    "10-minute",
    "Status table",
    "UNIVERSAL SEATING LAW",
    "coding_family",
    "subscription",
    "skill immutability",
    "Foundry",
    "journal",
    "future-ready",
)

# Shipped exportable body + pointer templates (host-path free). Loaded from
# share_governance_pack/ so golden fixtures can share the same bytes.
_PACK_DIR = _MODULE_DIR / "share_governance_pack"
_BODY_PATH = _PACK_DIR / "AGENTS.body.md"
_POINTER_PATH = _PACK_DIR / "CLAUDE.md"


def _load_exportable_body() -> str:
    return _BODY_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")


def _load_pointer_body() -> str:
    return _POINTER_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")



class GovernancePackError(Exception):
    """Raised when pack generation refuses (missing required content, etc.)."""


def apply_host_personal_denylist(text: str, denylist=None) -> str:
    """Strip host-personal tokens then residual path/email shapes.

    Order: longest literal denylist tokens first (so nested paths scrub cleanly),
    then residual regexes shared with the vendoring residual-scrub style.
    """
    if not isinstance(text, str):
        return ""
    deny = list(denylist) if denylist is not None else list(
        DEFAULT_HOST_PERSONAL_DENYLIST
    )
    # Longest first so "C:\\Users\\john\\foo" wins over "john" alone when both present.
    deny_sorted = sorted(
        (str(t) for t in deny if t),
        key=lambda s: len(s),
        reverse=True,
    )
    out = text
    for token in deny_sorted:
        if token in out:
            out = out.replace(token, PATH_PLACEHOLDER)
    out = _WIN_DEV_RE.sub(PATH_PLACEHOLDER, out)
    out = _WIN_USER_RE.sub(PATH_PLACEHOLDER, out)
    out = _POSIX_HOME_RE.sub(PATH_PLACEHOLDER, out)
    out = _EMAIL_RE.sub(EMAIL_PLACEHOLDER, out)
    return out


def assert_no_author_paths(text: str) -> list:
    """Return problem strings for any remaining author-shaped absolute paths."""
    problems = []
    if not isinstance(text, str):
        return ["text-not-a-string"]
    for rx in AUTHOR_PATH_RES:
        if rx.search(text):
            problems.append("author-path-remains:%s" % rx.pattern)
    return problems


def _stamp_header(version: str = GOVERNANCE_PACK_VERSION) -> str:
    return (
        "<!-- governance-pack: schema=%s version=%s -->\n"
        % (GOVERNANCE_SCHEMA, version)
    )


def _merge_sources(source_texts) -> str:
    """Merge optional extra source texts under the exportable spine.

    Extra sources are appended under a clear separator so denylist can scrub
    author host paths from them without rewriting the spine semantics.
    """
    body = _load_exportable_body().rstrip() + "\n"
    extras = []
    for t in source_texts or []:
        if isinstance(t, str) and t.strip():
            extras.append(t.strip())
    if extras:
        body += "\n## Imported source excerpts (scrubbed)\n\n"
        for i, t in enumerate(extras, start=1):
            body += "### Source excerpt %d\n\n%s\n\n" % (i, t)
    return body


def build_pack_files(
    source_texts=None,
    *,
    denylist=None,
    version: str = GOVERNANCE_PACK_VERSION,
) -> dict:
    """Build in-memory pack ``{filename: text}`` after denylist scrub.

    Always includes AGENTS.md + CLAUDE.md + GEMINI.md. Raises
    :class:`GovernancePackError` if required section markers are missing after
    scrub (fail closed — do not ship an incomplete pack).
    """
    raw = _merge_sources(source_texts)
    agents = _stamp_header(version) + apply_host_personal_denylist(
        raw, denylist=denylist
    )
    # Normalize newlines for golden stability.
    if not agents.endswith("\n"):
        agents += "\n"
    agents = agents.replace("\r\n", "\n")

    missing = [m for m in REQUIRED_SECTION_MARKERS if m not in agents]
    if missing:
        raise GovernancePackError(
            "governance pack missing required markers: %s" % ",".join(missing)
        )
    path_problems = assert_no_author_paths(agents)
    if path_problems:
        raise GovernancePackError(
            "governance pack still contains author paths: %s"
            % ";".join(path_problems)
        )

    pointer = apply_host_personal_denylist(
        _load_pointer_body(), denylist=denylist
    ).replace("\r\n", "\n")
    if not pointer.endswith("\n"):
        pointer += "\n"

    return {
        "AGENTS.md": agents,
        "CLAUDE.md": pointer,
        "GEMINI.md": pointer,
    }


def write_governance_pack(
    dest_dir,
    source_texts=None,
    *,
    denylist=None,
    version: str = GOVERNANCE_PACK_VERSION,
    source_paths=None,
) -> dict:
    """Write the pack into ``dest_dir``; return ``{filename: Path}``.

    ``source_paths`` (optional) are read as UTF-8 and treated as extra source
    texts (scrubbed via the denylist). Does not embed absolute author paths in
    the written files.
    """
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    texts = list(source_texts or [])
    for p in source_paths or []:
        texts.append(Path(p).read_text(encoding="utf-8"))
    files = build_pack_files(
        texts, denylist=denylist, version=version
    )
    written = {}
    for name, content in files.items():
        out = dest / name
        out.write_text(content, encoding="utf-8", newline="\n")
        written[name] = out
    return written


def pack_matches_golden(generated: dict, golden_dir) -> list:
    """Compare generated pack dict to files under ``golden_dir``.

    Returns a list of problem strings (empty = match).
    """
    golden = Path(golden_dir)
    problems = []
    if not golden.is_dir():
        return ["golden-dir-missing:%s" % golden]
    expected_names = sorted(generated.keys())
    for name in expected_names:
        gpath = golden / name
        if not gpath.is_file():
            problems.append("golden-missing-file:%s" % name)
            continue
        want = gpath.read_text(encoding="utf-8").replace("\r\n", "\n")
        got = generated[name].replace("\r\n", "\n")
        if want != got:
            problems.append(
                "golden-mismatch:%s:want_sha=%s:got_sha=%s"
                % (
                    name,
                    hashlib.sha256(want.encode("utf-8")).hexdigest()[:12],
                    hashlib.sha256(got.encode("utf-8")).hexdigest()[:12],
                )
            )
    # Extra golden files not in generated are ignored (forward-compat).
    return problems


def is_governance_installed(home_or_pack_dir) -> bool:
    """True when an AGENTS.md pack root exists with the governance stamp."""
    root = Path(home_or_pack_dir)
    agents = root / "AGENTS.md"
    if not agents.is_file():
        return False
    try:
        text = agents.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return (
        "governance-pack:" in text
        or GOVERNANCE_SCHEMA in text
        or "Status table" in text
    )


def governance_pack_version_of(home_or_pack_dir) -> str | None:
    """Parse stamped version from installed AGENTS.md, or None."""
    agents = Path(home_or_pack_dir) / "AGENTS.md"
    if not agents.is_file():
        return None
    try:
        head = agents.read_text(encoding="utf-8", errors="replace")[:500]
    except OSError:
        return None
    m = re.search(r"version=([0-9]+\.[0-9]+\.[0-9]+)", head)
    return m.group(1) if m else None
