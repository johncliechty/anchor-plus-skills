"""S1 finding classifier — W22, Phase 5.

S1 is a **live** validation session with John. This module does not invent
PASS; it classifies findings John (or a scripted test injection) reports.

Hard rules:

* The four North-Star violation classes are **BUILD_BLOCKING**:
  dead control / silent zero / mislabelled empty / raw-binary preview.
* BUILD_BLOCKING findings **cannot** be routed to exit E6 (follow-on).
  Routing attempt raises :class:`E6RoutingForbidden`.
* S1 is the only gate that may convert a criterion from CANDIDATE-MET to MET;
  a criterion S1 fails reverts to OPEN.
* Default S1 verdict is PENDING — structure alone never declares the North
  Star met.

Paths are relative to the stage2 containment root when a root is used.
No absolute host paths are hard-coded.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Union

from anchor.build.exit_register import (
    E6_CLOSED_MESSAGE,
    ExitId,
    IllegalExit,
    is_ns_violation_class,
    terminal_status,
    validate_justification,
)

# --------------------------------------------------------------------------
# Public constants
# --------------------------------------------------------------------------

BUILD_BLOCKING = "BUILD_BLOCKING"
FOLLOW_ON = "FOLLOW_ON"
INFORMATIONAL = "INFORMATIONAL"

#: Default until John records a live S1 verdict — never auto-PASS.
S1_PENDING = "PENDING"
S1_PASS = "PASS"
S1_FAIL = "FAIL"

S1_VALIDATION_RELPATH = "artifacts/S1-VALIDATION.md"

#: Canonical tokens for the four closed classes (machine form).
DEAD_CONTROL = "dead_control"
SILENT_ZERO = "silent_zero"
MISLABELLED_EMPTY = "mislabelled_empty"
RAW_BINARY_PREVIEW = "raw_binary_preview"

BUILD_BLOCKING_CLASSES: frozenset = frozenset(
    {
        DEAD_CONTROL,
        SILENT_ZERO,
        MISLABELLED_EMPTY,
        RAW_BINARY_PREVIEW,
    }
)

#: Phrases / aliases that map into BUILD_BLOCKING_CLASSES.
_CLASS_ALIASES: Dict[str, str] = {
    "dead_control": DEAD_CONTROL,
    "dead control": DEAD_CONTROL,
    "dead-control": DEAD_CONTROL,
    "silent_zero": SILENT_ZERO,
    "silent zero": SILENT_ZERO,
    "silent-zero": SILENT_ZERO,
    "mislabelled_empty": MISLABELLED_EMPTY,
    "mislabelled empty": MISLABELLED_EMPTY,
    "mislabelled-empty": MISLABELLED_EMPTY,
    "mislabeled_empty": MISLABELLED_EMPTY,
    "mislabeled empty": MISLABELLED_EMPTY,
    "raw_binary": RAW_BINARY_PREVIEW,
    "raw-binary": RAW_BINARY_PREVIEW,
    "raw binary": RAW_BINARY_PREVIEW,
    "raw_binary_preview": RAW_BINARY_PREVIEW,
    "raw-binary preview": RAW_BINARY_PREVIEW,
    "raw binary preview": RAW_BINARY_PREVIEW,
}

_PHRASE_TO_CLASS: tuple = (
    (re.compile(r"\bdead\s+control\b", re.I), DEAD_CONTROL),
    (re.compile(r"\bsilent\s+zero\b", re.I), SILENT_ZERO),
    (re.compile(r"\bmislabel+ed\s+empty\b", re.I), MISLABELLED_EMPTY),
    (re.compile(r"\braw[-\s]?binary(\s+preview)?\b", re.I), RAW_BINARY_PREVIEW),
)

_VERDICT_PASS = frozenset({"PASS", "PASSED", "S1 PASS", "S1_PASS", "S1-PASS"})
_VERDICT_FAIL = frozenset({"FAIL", "FAILED", "S1 FAIL", "S1_FAIL", "S1-FAIL"})

E6_ROUTING_FORBIDDEN_MESSAGE = (
    "BUILD_BLOCKING finding cannot be routed to E6 — "
    "dead control / silent zero / mislabelled empty / raw-binary preview "
    "are North-Star violations, not follow-on"
)

STATUS_CANDIDATE_MET = "CANDIDATE-MET"
STATUS_MET = "MET"
STATUS_OPEN = "OPEN"


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class S1FindingsError(Exception):
    """Base error for S1 finding classification / routing."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class E6RoutingForbidden(S1FindingsError):
    """Raised when a BUILD_BLOCKING finding is offered to E6."""


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------


class FindingSeverity(str, Enum):
    BUILD_BLOCKING = BUILD_BLOCKING
    FOLLOW_ON = FOLLOW_ON
    INFORMATIONAL = INFORMATIONAL


@dataclass(frozen=True)
class ClassifiedFinding:
    """One S1 finding after classification."""

    description: str
    finding_class: str
    severity: str
    may_route_to_e6: bool
    control: Optional[str] = None
    criterion: Optional[str] = None
    source_step: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class S1SessionResult:
    """Aggregate of a live (or test-injected) S1 session.

    Default verdict is PENDING — S1 has not been faked as passed.
    """

    verdict: str = S1_PENDING
    findings: List[ClassifiedFinding] = field(default_factory=list)
    step_outcomes: Dict[str, str] = field(default_factory=dict)
    date: Optional[str] = None
    john_confirmation: Optional[str] = None

    def has_build_blocking(self) -> bool:
        return any(f.severity == BUILD_BLOCKING for f in self.findings)

    def build_blocking_findings(self) -> List[ClassifiedFinding]:
        return [f for f in self.findings if f.severity == BUILD_BLOCKING]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict,
            "date": self.date,
            "john_confirmation": self.john_confirmation,
            "step_outcomes": dict(self.step_outcomes),
            "findings": [f.as_dict() for f in self.findings],
            "has_build_blocking": self.has_build_blocking(),
        }


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------


def normalize_finding_class(finding_class: Optional[str]) -> Optional[str]:
    """Map free-form class labels to canonical tokens when known."""
    if finding_class is None:
        return None
    raw = str(finding_class).strip().lower()
    if not raw:
        return None
    collapsed = " ".join(raw.replace("_", " ").replace("-", " ").split())
    if raw in _CLASS_ALIASES:
        return _CLASS_ALIASES[raw]
    if collapsed in _CLASS_ALIASES:
        return _CLASS_ALIASES[collapsed]
    # Underscored form of collapsed words.
    underscored = collapsed.replace(" ", "_")
    if underscored in _CLASS_ALIASES:
        return _CLASS_ALIASES[underscored]
    if underscored in BUILD_BLOCKING_CLASSES:
        return underscored
    return underscored


def detect_class_from_text(text: str) -> Optional[str]:
    """Scan description text for one of the four violation classes."""
    if not text:
        return None
    for pattern, token in _PHRASE_TO_CLASS:
        if pattern.search(text):
            return token
    return None


def _canonical_blocking_class(token: Optional[str]) -> Optional[str]:
    """Return a BUILD_BLOCKING_CLASSES member, or None if not one of the four."""
    if token is None:
        return None
    norm = normalize_finding_class(token)
    if norm in BUILD_BLOCKING_CLASSES:
        return norm
    if is_ns_violation_class(token):
        low = str(token).strip().lower().replace("-", " ").replace("_", " ")
        if "dead" in low:
            return DEAD_CONTROL
        if "silent" in low:
            return SILENT_ZERO
        if "mislabel" in low:
            return MISLABELLED_EMPTY
        if "binary" in low:
            return RAW_BINARY_PREVIEW
    from_text = detect_class_from_text(str(token))
    if from_text in BUILD_BLOCKING_CLASSES:
        return from_text
    return None


def classify_finding(
    description: str = "",
    *,
    finding_class: Optional[str] = None,
    control: Optional[str] = None,
    criterion: Optional[str] = None,
    source_step: Optional[str] = None,
    severity_hint: Optional[str] = None,
) -> ClassifiedFinding:
    """Classify a single S1 finding.

    The four North-Star violation classes are always BUILD_BLOCKING with
    ``may_route_to_e6=False``. Other classes default to FOLLOW_ON (E6-eligible)
    unless ``severity_hint`` says INFORMATIONAL.
    """
    desc = str(description or "").strip()

    # Prefer explicit class, then description phrases.
    blocking = _canonical_blocking_class(finding_class)
    if blocking is None:
        blocking = detect_class_from_text(desc)

    if blocking in BUILD_BLOCKING_CLASSES:
        return ClassifiedFinding(
            description=desc,
            finding_class=blocking,
            severity=BUILD_BLOCKING,
            may_route_to_e6=False,
            control=control,
            criterion=criterion,
            source_step=source_step,
        )

    detected = normalize_finding_class(finding_class) or "unspecified"
    hint = (severity_hint or FOLLOW_ON).strip().upper()
    if hint == INFORMATIONAL:
        sev = INFORMATIONAL
        may_e6 = False
    elif hint == BUILD_BLOCKING:
        # Non-NS class forced blocking still cannot invent E6 eligibility.
        sev = BUILD_BLOCKING
        may_e6 = False
    else:
        sev = FOLLOW_ON
        may_e6 = True

    return ClassifiedFinding(
        description=desc,
        finding_class=detected,
        severity=sev,
        may_route_to_e6=may_e6,
        control=control,
        criterion=criterion,
        source_step=source_step,
    )


def classify_findings(
    items: Sequence[Union[Mapping[str, Any], ClassifiedFinding, str]],
) -> List[ClassifiedFinding]:
    """Classify a batch of findings (dicts, strings, or already classified)."""
    out: List[ClassifiedFinding] = []
    for item in items:
        if isinstance(item, ClassifiedFinding):
            out.append(item)
            continue
        if isinstance(item, str):
            out.append(classify_finding(item))
            continue
        if isinstance(item, Mapping):
            out.append(
                classify_finding(
                    str(item.get("description") or item.get("observed") or ""),
                    finding_class=item.get("finding_class") or item.get("class"),
                    control=item.get("control"),
                    criterion=item.get("criterion"),
                    source_step=item.get("source_step") or item.get("step"),
                    severity_hint=item.get("severity_hint") or item.get("severity"),
                )
            )
            continue
        raise S1FindingsError(
            "classify_findings expects str, mapping, or ClassifiedFinding; got %r"
            % type(item).__name__
        )
    return out


# --------------------------------------------------------------------------
# E6 routing
# --------------------------------------------------------------------------


def may_route_to_e6(finding: Union[ClassifiedFinding, str, Mapping[str, Any]]) -> bool:
    """True only when the finding is not a North-Star BUILD_BLOCKING class."""
    if isinstance(finding, ClassifiedFinding):
        return bool(finding.may_route_to_e6) and finding.severity != BUILD_BLOCKING
    classified = (
        classify_finding(finding)
        if isinstance(finding, str)
        else classify_finding(
            str(finding.get("description") or ""),
            finding_class=finding.get("finding_class") or finding.get("class"),
        )
    )
    return may_route_to_e6(classified)


def assert_e6_routing_allowed(
    finding: Union[ClassifiedFinding, str, Mapping[str, Any]],
) -> ClassifiedFinding:
    """Return the classified finding or raise E6RoutingForbidden / IllegalExit."""
    if isinstance(finding, ClassifiedFinding):
        classified = finding
    elif isinstance(finding, str):
        classified = classify_finding(finding)
    else:
        classified = classify_finding(
            str(finding.get("description") or ""),
            finding_class=finding.get("finding_class") or finding.get("class"),
            control=finding.get("control"),
            criterion=finding.get("criterion"),
        )

    if classified.severity == BUILD_BLOCKING or not classified.may_route_to_e6:
        if classified.finding_class in BUILD_BLOCKING_CLASSES or is_ns_violation_class(
            classified.finding_class
        ):
            raise E6RoutingForbidden(E6_ROUTING_FORBIDDEN_MESSAGE)

    # Also enforce exit_register's E6 closed list (same four classes).
    try:
        validate_justification(
            ExitId.E6,
            finding_class=classified.finding_class,
            justification=classified.description,
            criterion=classified.criterion or "S1 findings",
            forcing_evidence=classified.description or classified.finding_class,
        )
    except IllegalExit as exc:
        if E6_CLOSED_MESSAGE in str(exc) or "E6 is closed" in str(exc):
            raise E6RoutingForbidden(E6_ROUTING_FORBIDDEN_MESSAGE) from exc
        raise

    return classified


def route_to_e6(
    finding: Union[ClassifiedFinding, str, Mapping[str, Any]],
) -> ClassifiedFinding:
    """Attempt E6 routing. BUILD_BLOCKING classes always fail closed."""
    return assert_e6_routing_allowed(finding)


# --------------------------------------------------------------------------
# S1 verdict + session
# --------------------------------------------------------------------------


def normalize_s1_verdict(verdict: Optional[str]) -> str:
    """Normalize a verdict token; default PENDING when empty/unknown."""
    if verdict is None:
        return S1_PENDING
    text = str(verdict).strip().upper()
    if not text:
        return S1_PENDING
    if text in _VERDICT_PASS:
        return S1_PASS
    if text in _VERDICT_FAIL:
        return S1_FAIL
    if text in {S1_PENDING, "S1 PENDING", "S1_PENDING", "NOT RUN", "NOT_RUN"}:
        return S1_PENDING
    # Unknown tokens stay pending — never treat as PASS.
    return S1_PENDING


def is_s1_pass(verdict: Optional[str]) -> bool:
    return normalize_s1_verdict(verdict) == S1_PASS


def is_s1_fail(verdict: Optional[str]) -> bool:
    return normalize_s1_verdict(verdict) == S1_FAIL


def build_session_result(
    *,
    verdict: Optional[str] = None,
    findings: Optional[Sequence[Union[Mapping[str, Any], ClassifiedFinding, str]]] = None,
    step_outcomes: Optional[Mapping[str, str]] = None,
    date: Optional[str] = None,
    john_confirmation: Optional[str] = None,
) -> S1SessionResult:
    """Build an S1 session result. Default verdict is PENDING (S1 not faked)."""
    classified = classify_findings(list(findings or []))
    v = normalize_s1_verdict(verdict)
    # BUILD_BLOCKING findings force FAIL if someone tried to stamp PASS.
    if any(f.severity == BUILD_BLOCKING for f in classified):
        if v == S1_PASS:
            v = S1_FAIL
        elif v == S1_PENDING:
            pass  # stay pending until John records; findings still classified
    return S1SessionResult(
        verdict=v,
        findings=classified,
        step_outcomes=dict(step_outcomes or {}),
        date=date,
        john_confirmation=john_confirmation,
    )


def north_star_met(
    *,
    s1_verdict: Optional[str] = None,
    signed_exit_count: int = 0,
    session: Optional[S1SessionResult] = None,
) -> bool:
    """True only when S1 PASS, zero signed exits, and no BUILD_BLOCKING findings.

    Structure tests alone never return True.
    """
    if session is not None:
        if session.has_build_blocking():
            return False
        verdict = session.verdict
    else:
        verdict = s1_verdict
    if signed_exit_count != 0:
        return False
    return is_s1_pass(verdict)


def emit_terminal_status_for_s1(
    rows: Sequence[Any] = (),
    *,
    s1_verdict: Optional[str] = None,
    session: Optional[S1SessionResult] = None,
) -> str:
    """Machine-emit terminal status via exit_register.terminal_status.

    Injected/session verdicts only — default PENDING keeps CANDIDATE-MET and
    North Star pending S1. Never invents PASS from structure.
    """
    if session is not None:
        # BUILD_BLOCKING means North Star cannot be met even if a PASS was injected.
        if session.has_build_blocking():
            return terminal_status(rows, s1_verdict=None)
        verdict = session.verdict
    else:
        verdict = s1_verdict
    # Only PASS is forwarded; PENDING/FAIL leave s1_verdict unset/non-pass.
    if is_s1_pass(verdict):
        return terminal_status(rows, s1_verdict="PASS")
    return terminal_status(rows, s1_verdict=None)


# --------------------------------------------------------------------------
# Traceability matrix status transitions (S1 only)
# --------------------------------------------------------------------------


def s1_status_transition(
    current_status: str,
    *,
    s1_verdict: Optional[str],
    criterion_passed: Optional[bool] = None,
) -> str:
    """Apply S1's sole authority over CANDIDATE-MET → MET / OPEN.

    * Without S1 PASS → status stays CANDIDATE-MET or OPEN (never promotes to MET).
    * S1 PASS + criterion_passed True (or None meaning all-pass) → MET.
    * S1 FAIL or criterion_passed False → OPEN.
    """
    cur = (current_status or "").strip().upper().replace("_", "-")
    if cur in {"CANDIDATE MET", "CANDIDATE_MET"}:
        cur = STATUS_CANDIDATE_MET
    if cur == "MET":
        # Pre-S1 MET is illegal elsewhere; if we see it under S1 fail, open it.
        cur = STATUS_MET

    verdict = normalize_s1_verdict(s1_verdict)

    if verdict == S1_FAIL or criterion_passed is False:
        return STATUS_OPEN

    if verdict != S1_PASS:
        # PENDING / unknown: never promote; demote illegal bare MET back to candidate.
        if cur == STATUS_MET:
            return STATUS_CANDIDATE_MET
        return cur if cur in {STATUS_CANDIDATE_MET, STATUS_OPEN} else STATUS_CANDIDATE_MET

    # S1 PASS
    if criterion_passed is False:
        return STATUS_OPEN
    if cur == STATUS_OPEN and criterion_passed is not True:
        # Open stays open unless this criterion explicitly passed.
        return STATUS_OPEN
    return STATUS_MET


def apply_s1_to_matrix_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    s1_verdict: Optional[str],
    failed_criteria: Optional[Iterable[Union[int, str]]] = None,
) -> List[Dict[str, Any]]:
    """Return matrix row dicts with status updated under S1 rules.

    ``failed_criteria`` is a set of criterion ids (int or str) that S1 failed;
    those revert to OPEN. On overall FAIL without a list, all CANDIDATE-MET
    rows become OPEN.
    """
    failed: set = set()
    for c in failed_criteria or ():
        failed.add(str(c).strip())
        try:
            failed.add(str(int(c)))
        except (TypeError, ValueError):
            pass

    verdict = normalize_s1_verdict(s1_verdict)
    out: List[Dict[str, Any]] = []
    for row in rows:
        r = dict(row)
        cid = str(r.get("criterion") or r.get("id") or "").strip()
        cur = str(r.get("status") or STATUS_CANDIDATE_MET)
        if verdict == S1_FAIL and not failed:
            r["status"] = s1_status_transition(
                cur, s1_verdict=verdict, criterion_passed=False
            )
        elif cid and cid in failed:
            r["status"] = s1_status_transition(
                cur, s1_verdict=verdict, criterion_passed=False
            )
        else:
            r["status"] = s1_status_transition(
                cur,
                s1_verdict=verdict,
                criterion_passed=True if verdict == S1_PASS else None,
            )
        out.append(r)
    return out


# --------------------------------------------------------------------------
# S1-VALIDATION.md verdict read
# --------------------------------------------------------------------------


_S1_VERDICT_LINE = re.compile(
    r"^\s*S1_VERDICT\s*:\s*(\S+)",
    re.IGNORECASE | re.MULTILINE,
)
_S1_OVERALL_ROW = re.compile(
    r"\|\s*\*?\*?S1 verdict\*?\*?\s*\|\s*\*?\*?([A-Za-z0-9_ \-]+)\*?\*?\s*\|",
    re.IGNORECASE,
)


def parse_s1_verdict_from_validation_md(text: str) -> str:
    """Parse overall S1 verdict from S1-VALIDATION.md body. Default PENDING."""
    if not text:
        return S1_PENDING
    m = _S1_VERDICT_LINE.search(text)
    if m:
        return normalize_s1_verdict(m.group(1))
    m2 = _S1_OVERALL_ROW.search(text)
    if m2:
        return normalize_s1_verdict(m2.group(1))
    # Explicit PENDING word near overall is the shipping default.
    if re.search(r"S1 overall verdict\s*\|\s*\*?\*?PENDING", text, re.I):
        return S1_PENDING
    return S1_PENDING


def read_s1_verdict(root: Optional[Path] = None) -> str:
    """Read S1 verdict from artifacts/S1-VALIDATION.md under containment root."""
    if root is None:
        # anchor/build/s1_findings.py → stage2 is parents[2]
        root = Path(__file__).resolve().parents[2]
    path = Path(root) / S1_VALIDATION_RELPATH
    if not path.is_file():
        return S1_PENDING
    return parse_s1_verdict_from_validation_md(
        path.read_text(encoding="utf-8")
    )


# --------------------------------------------------------------------------
# Exports
# --------------------------------------------------------------------------

__all__ = [
    "BUILD_BLOCKING",
    "BUILD_BLOCKING_CLASSES",
    "ClassifiedFinding",
    "DEAD_CONTROL",
    "E6RoutingForbidden",
    "E6_ROUTING_FORBIDDEN_MESSAGE",
    "FOLLOW_ON",
    "FindingSeverity",
    "INFORMATIONAL",
    "MISLABELLED_EMPTY",
    "RAW_BINARY_PREVIEW",
    "S1FindingsError",
    "S1SessionResult",
    "S1_FAIL",
    "S1_PASS",
    "S1_PENDING",
    "S1_VALIDATION_RELPATH",
    "SILENT_ZERO",
    "STATUS_CANDIDATE_MET",
    "STATUS_MET",
    "STATUS_OPEN",
    "apply_s1_to_matrix_rows",
    "assert_e6_routing_allowed",
    "build_session_result",
    "classify_finding",
    "classify_findings",
    "detect_class_from_text",
    "emit_terminal_status_for_s1",
    "is_s1_fail",
    "is_s1_pass",
    "may_route_to_e6",
    "normalize_finding_class",
    "normalize_s1_verdict",
    "north_star_met",
    "parse_s1_verdict_from_validation_md",
    "read_s1_verdict",
    "route_to_e6",
    "s1_status_transition",
]
