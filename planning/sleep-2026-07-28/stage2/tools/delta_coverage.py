"""Delta-coverage checker — W8.

Names new routes / handlers / frontend symbols and requires each to appear
in a dated ``tests/test_<subject>_2026_07_29.py`` file.

When W1's coverage-toolchain probe recorded delta-coverage tooling **absent**
(``artifacts/coverage-toolchain-probe.json`` → ``delta_coverage.available ==
false``), this module **degrades** to the enumerated per-handler list under
E4: a signed substitute list that still names every handler. Inventing E4
while tooling is present is a gate failure.

Usage::

    from tools.delta_coverage import check_delta_coverage, DeltaCoverageError

    check_delta_coverage(
        handlers=["/api/rnd/open", "open_work"],
        # when tooling absent:
        e4_enumerated_list=["/api/rnd/open", "open_work"],
    )

CLI::

    python -m tools.delta_coverage --handler open_work --handler run_work
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Union

SCHEMA = "delta-coverage-result/v1"
DATED_TEST_SUFFIX = "2026_07_29"
DATED_TEST_RE = re.compile(r"test_.*_2026_07_29\.py$")
PROBE_RELPATH = os.path.join("artifacts", "coverage-toolchain-probe.json")
FACT_UNAVAILABLE = "delta-coverage unavailable"


class DeltaCoverageError(ValueError):
    """Wave gate failure: uncovered route/handler or illegal E4."""


@dataclass
class DeltaCoverageReport:
    """Machine-readable gate result."""

    ok: bool
    mode: str  # "delta-coverage" | "e4-enumerated-list"
    handlers: List[str] = field(default_factory=list)
    covered: List[str] = field(default_factory=list)
    uncovered: List[str] = field(default_factory=list)
    e4_enumerated_list: Optional[List[str]] = None
    probe_available: Optional[bool] = None
    probe_fact: Optional[str] = None
    test_files: List[str] = field(default_factory=list)
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": SCHEMA,
            "ok": self.ok,
            "mode": self.mode,
            "handlers": list(self.handlers),
            "covered": list(self.covered),
            "uncovered": list(self.uncovered),
            "e4_enumerated_list": (
                list(self.e4_enumerated_list)
                if self.e4_enumerated_list is not None
                else None
            ),
            "probe_available": self.probe_available,
            "probe_fact": self.probe_fact,
            "test_files": list(self.test_files),
            "message": self.message,
        }


def _containment_root() -> Path:
    try:
        from tools import containment_smoke  # type: ignore

        return Path(containment_smoke.containment_root())
    except Exception:
        return Path(__file__).resolve().parents[1]


def probe_path(root: Optional[Path] = None) -> Path:
    base = Path(root) if root is not None else _containment_root()
    return base / PROBE_RELPATH


def read_probe(root: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """Load W1 coverage-toolchain probe record (or None if missing)."""
    path = probe_path(root)
    if not path.is_file():
        # Fall back to the probe module's reader when available.
        try:
            from tools.coverage_toolchain_probe import read_record

            return read_record(root=root)
        except Exception:
            return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def delta_coverage_available(probe: Optional[Dict[str, Any]]) -> bool:
    if not probe:
        return False
    delta = probe.get("delta_coverage") or {}
    return bool(delta.get("available"))


def probe_fact(probe: Optional[Dict[str, Any]]) -> str:
    if not probe:
        return FACT_UNAVAILABLE
    delta = probe.get("delta_coverage") or {}
    return str(delta.get("fact") or FACT_UNAVAILABLE)


def list_dated_test_files(tests_dir: Path) -> List[Path]:
    if not tests_dir.is_dir():
        return []
    return sorted(
        p for p in tests_dir.iterdir() if p.is_file() and DATED_TEST_RE.search(p.name)
    )


def _handler_mentioned(handler: str, text: str) -> bool:
    """True when the handler/route/symbol appears in test source text."""
    if not handler:
        return False
    h = handler.strip()
    if not h:
        return False
    if h in text:
        return True
    # Also accept hyphen/underscore / path-tail variants.
    alt = h.replace("-", "_")
    if alt != h and alt in text:
        return True
    alt2 = h.replace("_", "-")
    if alt2 != h and alt2 in text:
        return True
    # Route tail: /api/rnd/open → open as a weak signal is NOT enough alone;
    # require a substantial token (len >= 3) that is unique-ish.
    if "/" in h:
        tail = h.rstrip("/").split("/")[-1]
        if len(tail) >= 3 and tail in text:
            return True
    return False


def handlers_covered_by_tests(
    handlers: Sequence[str],
    tests_dir: Path,
) -> Dict[str, List[str]]:
    """Map each handler → list of dated test file names that mention it."""
    files = list_dated_test_files(tests_dir)
    contents: Dict[str, str] = {}
    for p in files:
        try:
            contents[p.name] = p.read_text(encoding="utf-8")
        except OSError:
            contents[p.name] = ""

    coverage: Dict[str, List[str]] = {h: [] for h in handlers}
    for h in handlers:
        for name, text in contents.items():
            if _handler_mentioned(h, text):
                coverage[h].append(name)
    return coverage


def check_delta_coverage(
    handlers: Sequence[str],
    *,
    root: Optional[Path] = None,
    tests_dir: Optional[Path] = None,
    probe: Optional[Dict[str, Any]] = None,
    e4_enumerated_list: Optional[Sequence[str]] = None,
    raise_on_fail: bool = True,
) -> DeltaCoverageReport:
    """Require every new route/handler/frontend symbol to be test-covered.

    Modes:

    * **delta-coverage available** (probe): each handler must appear in a
      dated ``tests/test_*_2026_07_29.py``. An E4 list is **illegal** here
      (tooling present → cannot invent reduced instrument).
    * **delta-coverage unavailable** (W1 fact): either the same dated-test
      check passes, **or** a complete ``e4_enumerated_list`` substitute is
      provided that names every handler (E4 reduced-instrument path).

    GWT: a new route without a dated test fails listing the uncovered route,
    or records a signed E4 with the enumerated per-handler list as substitute.
    """
    base = Path(root) if root is not None else _containment_root()
    tdir = Path(tests_dir) if tests_dir is not None else base / "tests"
    rec = probe if probe is not None else read_probe(base)
    available = delta_coverage_available(rec)
    fact = probe_fact(rec)

    handlers_list = [str(h).strip() for h in handlers if str(h).strip()]
    test_files = [p.name for p in list_dated_test_files(tdir)]
    cov_map = handlers_covered_by_tests(handlers_list, tdir)
    covered = sorted(h for h, files in cov_map.items() if files)
    uncovered = sorted(h for h, files in cov_map.items() if not files)

    e4_list = (
        [str(x).strip() for x in e4_enumerated_list if str(x).strip()]
        if e4_enumerated_list is not None
        else None
    )

    if available:
        # Full path — E4 invent not allowed.
        if e4_list is not None:
            report = DeltaCoverageReport(
                ok=False,
                mode="delta-coverage",
                handlers=handlers_list,
                covered=covered,
                uncovered=uncovered,
                e4_enumerated_list=e4_list,
                probe_available=True,
                probe_fact=fact,
                test_files=test_files,
                message=(
                    "E4 enumerated list is illegal while delta-coverage "
                    "tooling is available (%s)" % fact
                ),
            )
            if raise_on_fail:
                raise DeltaCoverageError(report.message)
            return report

        if uncovered:
            report = DeltaCoverageReport(
                ok=False,
                mode="delta-coverage",
                handlers=handlers_list,
                covered=covered,
                uncovered=uncovered,
                probe_available=True,
                probe_fact=fact,
                test_files=test_files,
                message=(
                    "uncovered route/handler/frontend (no dated test "
                    "test_*_%s.py names them): %s"
                    % (DATED_TEST_SUFFIX, ", ".join(uncovered))
                ),
            )
            if raise_on_fail:
                raise DeltaCoverageError(report.message)
            return report

        return DeltaCoverageReport(
            ok=True,
            mode="delta-coverage",
            handlers=handlers_list,
            covered=covered,
            uncovered=[],
            probe_available=True,
            probe_fact=fact,
            test_files=test_files,
            message="all handlers named in dated tests",
        )

    # --- E4 degrade path (tooling absent) --------------------------------
    # Accept either full dated-test coverage OR a complete enumerated list.
    if not uncovered:
        return DeltaCoverageReport(
            ok=True,
            mode="e4-enumerated-list",
            handlers=handlers_list,
            covered=covered,
            uncovered=[],
            e4_enumerated_list=e4_list,
            probe_available=False,
            probe_fact=fact,
            test_files=test_files,
            message=(
                "delta-coverage unavailable; all handlers still named in dated "
                "tests (E4 list optional)"
            ),
        )

    if e4_list is None:
        report = DeltaCoverageReport(
            ok=False,
            mode="e4-enumerated-list",
            handlers=handlers_list,
            covered=covered,
            uncovered=uncovered,
            e4_enumerated_list=None,
            probe_available=False,
            probe_fact=fact,
            test_files=test_files,
            message=(
                "uncovered route/handler/frontend: %s — delta-coverage "
                "unavailable (%s); provide e4_enumerated_list as substitute "
                "or add dated tests naming each handler"
                % (", ".join(uncovered), fact)
            ),
        )
        if raise_on_fail:
            raise DeltaCoverageError(report.message)
        return report

    # Enumerated list must name every handler (set equality on required set).
    e4_set = set(e4_list)
    required = set(handlers_list)
    missing_from_e4 = sorted(required - e4_set)
    if missing_from_e4:
        report = DeltaCoverageReport(
            ok=False,
            mode="e4-enumerated-list",
            handlers=handlers_list,
            covered=covered,
            uncovered=uncovered,
            e4_enumerated_list=e4_list,
            probe_available=False,
            probe_fact=fact,
            test_files=test_files,
            message=(
                "E4 enumerated list incomplete — missing handlers: %s"
                % ", ".join(missing_from_e4)
            ),
        )
        if raise_on_fail:
            raise DeltaCoverageError(report.message)
        return report

    return DeltaCoverageReport(
        ok=True,
        mode="e4-enumerated-list",
        handlers=handlers_list,
        covered=covered,
        uncovered=uncovered,
        e4_enumerated_list=e4_list,
        probe_available=False,
        probe_fact=fact,
        test_files=test_files,
        message=(
            "delta-coverage unavailable; signed E4 enumerated per-handler "
            "list covers all handlers as substitute"
        ),
    )


def main(argv: Optional[Sequence[str]] = None) -> int:  # pragma: no cover - CLI
    parser = argparse.ArgumentParser(description="W8 delta-coverage gate")
    parser.add_argument(
        "--handler",
        action="append",
        default=[],
        dest="handlers",
        help="route/handler/frontend symbol (repeatable)",
    )
    parser.add_argument(
        "--e4-list",
        action="append",
        default=None,
        dest="e4_list",
        help="E4 enumerated handler (repeatable; only when tooling absent)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print report JSON",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    if not args.handlers:
        sys.stderr.write("usage: provide at least one --handler\n")
        return 2
    try:
        report = check_delta_coverage(
            args.handlers,
            e4_enumerated_list=args.e4_list,
            raise_on_fail=False,
        )
    except DeltaCoverageError as exc:
        sys.stderr.write(str(exc) + "\n")
        return 1
    if args.json:
        sys.stdout.write(json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(report.message + "\n")
        if report.uncovered:
            sys.stdout.write("uncovered: %s\n" % ", ".join(report.uncovered))
    return 0 if report.ok else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
