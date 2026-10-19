"""Shared-artifact ledger — W1, Phase 0.

``artifacts/shared-artifact-ledger.md`` is the one place that says what this
build reads, what it writes, who owns each path, and — crucially — which
repo-root documents belong to *other* efforts and must not be touched.

This module is its parser and validator:

* every ``write`` / ``append`` / ``read-write`` row must resolve **inside** the
  containment root (checked through :mod:`tools.containment_smoke`, so the
  ledger and the smoke cannot drift apart);
* every ``must-not-touch`` row must name a file that
  :data:`tools.containment_smoke.ROOT_FOREIGN_ARTIFACTS` already knows about —
  a ledger row promising protection the smoke does not enforce is a lie;
* the sign-off is John's or the ledger is UNSIGNED, and an unsigned ledger is a
  HALT with the reason :data:`HALT_REASON_UNSIGNED`.

Paths are written repo-relative, or with the ``${REPO_ROOT}/`` prefix for the
must-not-touch rows, so no host absolute path is ever stored in the ledger.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

GO = "GO"
HALT = "HALT"

HALT_REASON_UNSIGNED = "live-John item — shared-artifact ledger is unsigned"
HALT_REASON_MALFORMED = "shared-artifact ledger is malformed"

ARTIFACT_RELPATH = os.path.join("artifacts", "shared-artifact-ledger.md")

REPO_ROOT_TOKEN = "${REPO_ROOT}/"

MODE_READ = "read"
MODE_WRITE = "write"
MODE_APPEND = "append"
MODE_READ_WRITE = "read-write"
MODE_MUST_NOT_TOUCH = "must-not-touch"
MODES = (MODE_READ, MODE_WRITE, MODE_APPEND, MODE_READ_WRITE, MODE_MUST_NOT_TOUCH)
WRITING_MODES = (MODE_WRITE, MODE_APPEND, MODE_READ_WRITE)

COLUMNS = ("id", "path", "owner", "mode", "consumed_by", "notes")

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_KV = re.compile(r"^-\s*\*\*(?P<key>[a-z_]+):\*\*\s*(?P<value>.*)$")
_SEPARATOR_CELL = re.compile(r"^:?-{2,}:?$")


@dataclass
class Result:
    status: str
    reason: str
    problems: List[str] = field(default_factory=list)

    @property
    def is_go(self) -> bool:
        return self.status == GO


def _root(root: Optional[Path] = None) -> Path:
    if root is not None:
        return Path(root)
    return _containment().containment_root()


def _containment():
    try:
        from tools import containment_smoke  # type: ignore
    except ImportError:  # running as a script: tools/ is sys.path[0]
        import containment_smoke  # type: ignore
    return containment_smoke


def ledger_path(root: Optional[Path] = None) -> Path:
    return _root(root) / ARTIFACT_RELPATH


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------


def _clean(value: str) -> str:
    """``(pending — John)`` and friends mean *empty*, not a value."""
    value = value.strip()
    if value.startswith("(") and value.endswith(")"):
        return ""
    return value


def parse_ledger(text: str) -> Dict[str, object]:
    """Parse the markdown table plus the ``## Sign-off`` key/value block."""
    rows: List[Dict[str, str]] = []
    signoff: Dict[str, str] = {"status": "", "signed_by": "", "date": "", "line": ""}
    in_signoff = False

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.lower().startswith("## "):
            in_signoff = line.lower().startswith("## sign-off")
            continue

        if in_signoff:
            match = _KV.match(line)
            if match:
                signoff[match.group("key")] = _clean(match.group("value"))
            continue

        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != len(COLUMNS):
            continue
        if [c.lower() for c in cells] == list(COLUMNS):
            continue  # header
        if all(_SEPARATOR_CELL.match(c) for c in cells):
            continue  # separator
        rows.append(dict(zip(COLUMNS, cells)))

    return {"rows": rows, "signoff": signoff}


def load_ledger(path: Optional[Path] = None, root: Optional[Path] = None) -> Dict[str, object]:
    target = ledger_path(root) if path is None else Path(path)
    return parse_ledger(target.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def signoff_is_valid(signoff: Dict[str, str]) -> bool:
    if str(signoff.get("status", "")).strip().upper() != "SIGNED":
        return False
    if not _ISO_DATE.match(str(signoff.get("date", "")).strip()):
        return False
    if not str(signoff.get("signed_by", "")).strip():
        return False
    if not str(signoff.get("line", "")).strip():
        return False
    return True


def write_targets(doc: Optional[Dict[str, object]] = None,
                  root: Optional[Path] = None) -> List[str]:
    """Every path the ledger says this build writes (containment-checkable)."""
    if doc is None:
        try:
            doc = load_ledger(root=root)
        except OSError:
            return []
    rows = doc.get("rows") if isinstance(doc, dict) else None
    targets: List[str] = []
    for row in rows or []:
        if row.get("mode") in WRITING_MODES:
            path = str(row.get("path", "")).strip()
            if path and not path.startswith(REPO_ROOT_TOKEN):
                targets.append(path)
    return targets


def validate_ledger(doc: Dict[str, object], root: Optional[Path] = None) -> Result:
    base = _root(root)
    containment = _containment()
    rows = doc.get("rows") or []
    problems: List[str] = []

    if not rows:
        problems.append("no artifact rows: the ledger must list every artifact "
                        "this build reads or writes")

    seen = set()
    for row in rows:
        rid = row.get("id") or "<unnamed>"
        if rid in seen:
            problems.append("duplicate ledger id %r" % rid)
        seen.add(rid)
        for column in ("path", "owner", "mode"):
            if not str(row.get(column, "")).strip():
                problems.append("row %s: %s is empty" % (rid, column))
        mode = str(row.get("mode", "")).strip()
        if mode and mode not in MODES:
            problems.append("row %s: unknown mode %r (allowed: %s)"
                            % (rid, mode, ", ".join(MODES)))
        path = str(row.get("path", "")).strip()
        if not path:
            continue

        if mode == MODE_MUST_NOT_TOUCH:
            if not path.startswith(REPO_ROOT_TOKEN):
                problems.append("row %s: a must-not-touch path must be written "
                                "'%s<name>'" % (rid, REPO_ROOT_TOKEN))
                continue
            name = path[len(REPO_ROOT_TOKEN):]
            if name not in containment.ROOT_FOREIGN_ARTIFACTS:
                problems.append(
                    "row %s: %r is not in containment_smoke.ROOT_FOREIGN_ARTIFACTS, so the "
                    "ledger promises protection the smoke does not enforce" % (rid, name))
            continue

        if path.startswith(REPO_ROOT_TOKEN):
            problems.append("row %s: only must-not-touch rows may use %s"
                            % (rid, REPO_ROOT_TOKEN))
            continue

        verdict = containment.check_write_target(path, root=base)
        if mode in WRITING_MODES and not verdict.allowed:
            problems.append("row %s: write path %r escapes the containment root (%s)"
                            % (rid, path, verdict.rule))
        elif not verdict.allowed and mode == MODE_READ:
            problems.append("row %s: read path %r is outside the containment root (%s)"
                            % (rid, path, verdict.rule))

    for name in containment.ROOT_FOREIGN_ARTIFACTS:
        declared = any(str(r.get("path", "")).strip() == REPO_ROOT_TOKEN + name
                       for r in rows)
        if not declared:
            problems.append("root foreign artifact %r is protected by the smoke but "
                            "absent from the ledger" % name)

    if problems:
        return Result(HALT, "%s: %d problem(s)" % (HALT_REASON_MALFORMED, len(problems)),
                      problems=problems)

    if not signoff_is_valid(doc.get("signoff") or {}):
        return Result(HALT, HALT_REASON_UNSIGNED,
                      problems=["the ledger carries no dated sign-off from John"])

    return Result(GO, "ledger complete and signed")


def gate(path: Optional[Path] = None, root: Optional[Path] = None) -> Result:
    target = ledger_path(root) if path is None else Path(path)
    if not target.is_file():
        return Result(HALT, "%s: %s not found" % (HALT_REASON_MALFORMED, ARTIFACT_RELPATH),
                      problems=["artifact missing"])
    return validate_ledger(parse_ledger(target.read_text(encoding="utf-8")), root=root)


def main(argv: Optional[List[str]] = None) -> int:  # pragma: no cover - CLI
    import sys

    result = gate()
    sys.stdout.write("%s — %s\n" % (result.status, result.reason))
    for problem in result.problems:
        sys.stdout.write("  - %s\n" % problem)
    return 0 if result.is_go else 1


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
