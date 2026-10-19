"""Coverage-toolchain probe — W1, Phase 0 (truth, not assumption).

W8 plans a ``tools/delta_coverage.py`` gate, and E4 lets a wave substitute an
enumerated per-handler test list *when the tooling is genuinely absent*. That
substitution is only honest if somebody actually looked. This module looks.

The governing rule is one-directional: :data:`FACT_UNAVAILABLE` is the
**default**, and ``delta_coverage.available`` flips to ``True`` only when a
delta-coverage distribution is positively found *and* a coverage engine is
positively found. A probe that errors, a distribution whose version cannot be
read, an import that is missing — all of those record *unavailable*. Nothing
here infers availability from the absence of evidence.

The record is written to ``artifacts/coverage-toolchain-probe.json`` with an
atomic temp + fsync + rename write, and the write is **idempotent**: the
fingerprint covers the toolchain facts only (never the clock), so re-probing an
unchanged box leaves the file byte-identical.
"""
from __future__ import annotations

import importlib.util
import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

SCHEMA = "coverage-toolchain-probe/1"

#: The exact fact string a box without delta-coverage tooling records.
FACT_UNAVAILABLE = "delta-coverage unavailable"
FACT_AVAILABLE_TEMPLATE = "delta-coverage available via {tool} {version}"

#: import name -> distribution name
COVERAGE_ENGINES: Tuple[Tuple[str, str], ...] = (("coverage", "coverage"),)
PLUGINS: Tuple[Tuple[str, str], ...] = (("pytest_cov", "pytest-cov"),)
#: The tools that can actually compute coverage *of a diff*.
DELTA_COVERAGE_TOOLS: Tuple[Tuple[str, str], ...] = (
    ("diff_cover", "diff-cover"),
    ("pytest_diff_cover", "pytest-diff-cover"),
)

ARTIFACT_RELPATH = os.path.join("artifacts", "coverage-toolchain-probe.json")


# --------------------------------------------------------------------------
# The probe seam
# --------------------------------------------------------------------------

Finding = Dict[str, Optional[object]]
Finder = Callable[[str, str], Finding]


def default_finder(import_name: str, dist_name: str) -> Finding:
    """Look for one tool. Never raises; an error is recorded as not-found."""
    found = False
    version = None
    error = None
    try:
        found = importlib.util.find_spec(import_name) is not None
    except Exception as exc:  # a broken/partial install is NOT availability
        found = False
        error = "%s: %s" % (type(exc).__name__, exc)
    if found:
        try:
            from importlib import metadata  # Python 3.8+

            version = metadata.version(dist_name)
        except Exception as exc:
            version = None
            error = error or "%s: %s" % (type(exc).__name__, exc)
    return {
        "import_name": import_name,
        "distribution": dist_name,
        "found": bool(found),
        "version": version,
        "error": error,
    }


def _probe_group(
    specs: Tuple[Tuple[str, str], ...],
    finder: Finder,
) -> List[Finding]:
    return [finder(import_name, dist) for import_name, dist in specs]


def _first_found(findings: List[Finding]) -> Optional[Finding]:
    for finding in findings:
        if finding.get("found"):
            return finding
    return None


def probe(finder: Optional[Finder] = None) -> Dict[str, object]:
    """The clock-free toolchain record. Deterministic for a given box."""
    finder = default_finder if finder is None else finder
    engines = _probe_group(COVERAGE_ENGINES, finder)
    plugins = _probe_group(PLUGINS, finder)
    delta = _probe_group(DELTA_COVERAGE_TOOLS, finder)

    engine = _first_found(engines)
    delta_tool = _first_found(delta)

    # Availability is EARNED, never defaulted: a delta tool alone proves
    # nothing without an engine to measure with.
    available = bool(delta_tool) and bool(engine)
    if available and delta_tool is not None:
        fact = FACT_AVAILABLE_TEMPLATE.format(
            tool=delta_tool["distribution"],
            version=delta_tool.get("version") or "version-unreadable",
        )
    else:
        fact = FACT_UNAVAILABLE

    return {
        "schema": SCHEMA,
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
        },
        "coverage_engines": engines,
        "plugins": plugins,
        "delta_coverage_candidates": delta,
        "coverage_tool": {
            "name": engine["distribution"] if engine else None,
            "version": engine.get("version") if engine else None,
            "found": bool(engine),
        },
        "delta_coverage": {
            "available": available,
            "tool": delta_tool["distribution"] if delta_tool else None,
            "version": (delta_tool.get("version") if delta_tool else None),
            "fact": fact,
        },
        # W8/E4: with no delta-coverage tooling, later waves owe the
        # enumerated per-handler test list instead.
        "e4_enumerated_list_required": not available,
    }


def fingerprint(record: Dict[str, object]) -> str:
    """Stable digest of the toolchain facts — deliberately clock-free."""
    import hashlib

    payload = {k: v for k, v in record.items() if k not in ("probed_at", "fingerprint")}
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Recording
# --------------------------------------------------------------------------


def artifact_path(root: Optional[Path] = None) -> Path:
    if root is None:
        try:
            from tools import containment_smoke  # type: ignore
        except ImportError:  # running as a script: tools/ is sys.path[0]
            import containment_smoke  # type: ignore
        root = containment_smoke.containment_root()
    return Path(root) / ARTIFACT_RELPATH


def _atomic_write_text(path: Path, text: str) -> None:
    """temp + fsync + rename (the storage-mechanism vocabulary the plan names)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / (path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(str(tmp), str(path))


def write_record(
    root: Optional[Path] = None,
    finder: Optional[Finder] = None,
    now: Optional[str] = None,
) -> Dict[str, object]:
    """Probe and persist. Idempotent: an unchanged box rewrites nothing.

    Returns the record actually on disk plus a ``changed`` flag.
    """
    path = artifact_path(root)
    record = probe(finder=finder)
    digest = fingerprint(record)

    previous = read_record(root=root, path=path)
    if previous is not None and previous.get("fingerprint") == digest:
        return {"record": previous, "changed": False, "path": str(path),
                "fingerprint": digest}

    stamped = dict(record)
    stamped["fingerprint"] = digest
    stamped["probed_at"] = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    _atomic_write_text(path, json.dumps(stamped, indent=2, sort_keys=True) + "\n")
    return {"record": stamped, "changed": True, "path": str(path), "fingerprint": digest}


def read_record(
    root: Optional[Path] = None,
    path: Optional[Path] = None,
) -> Optional[Dict[str, object]]:
    path = artifact_path(root) if path is None else Path(path)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def summary_line(record: Dict[str, object]) -> str:
    delta = record.get("delta_coverage") or {}
    tool = record.get("coverage_tool") or {}
    name = tool.get("name") or "no coverage engine"
    version = tool.get("version") or "unknown version"
    return "coverage: %s %s · %s" % (name, version, delta.get("fact", FACT_UNAVAILABLE))


def main(argv: Optional[List[str]] = None) -> int:  # pragma: no cover - CLI
    argv = list(sys.argv[1:] if argv is None else argv)
    outcome = write_record()
    record = outcome["record"]
    sys.stdout.write(summary_line(record) + "\n")
    sys.stdout.write("recorded at %s (%s)\n" % (
        outcome["path"], "updated" if outcome["changed"] else "unchanged"))
    if "--json" in argv:
        sys.stdout.write(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
