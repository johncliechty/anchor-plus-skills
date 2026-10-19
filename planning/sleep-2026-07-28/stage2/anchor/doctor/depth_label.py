"""Depth labels for per-engine Doctor reports — W15.

Every engine report (Claude, Gemini, Grok) must carry a depth label from the
closed vocabulary. An unlabelled report is rejected by name (engine + report),
so a shared/echoed verdict cannot silently ship without stating how deep the
probe actually went.

Vocabulary (closed set):

* ``deep`` — full independent probe completed successfully
* ``shallow`` — probe ran but only partially (timeout, garbage, limited scope)
* ``unavailable`` — probe could not run (missing, unreadable store, absent)

Depth is orthogonal to ``NamedState``: a timeout report still carries
``depth=shallow`` (or ``unavailable``) alongside ``NamedState.timeout``.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

from anchor.ui.named_state import NamedState

# --------------------------------------------------------------------------
# Public constants
# --------------------------------------------------------------------------

WAVE_ID = "W15"
SURFACE_ID = "doctor-engines"

ENGINE_CLAUDE = "claude"
ENGINE_GEMINI = "gemini"
ENGINE_GROK = "grok"

ENGINE_IDS: Tuple[str, ...] = (ENGINE_CLAUDE, ENGINE_GEMINI, ENGINE_GROK)

ENGINE_CONTROL_IDS: Dict[str, str] = {
    ENGINE_CLAUDE: "diagnose_claude",
    ENGINE_GEMINI: "diagnose_gemini",
    ENGINE_GROK: "diagnose_grok",
}

ENGINE_LABELS: Dict[str, str] = {
    ENGINE_CLAUDE: "Claude",
    ENGINE_GEMINI: "Gemini",
    ENGINE_GROK: "Grok",
}


class DepthLabel(str, Enum):
    """Closed depth vocabulary for per-engine Doctor reports."""

    DEEP = "deep"
    SHALLOW = "shallow"
    UNAVAILABLE = "unavailable"

    @property
    def label(self) -> str:
        return self.value


DEPTH_VALUES: frozenset = frozenset(d.value for d in DepthLabel)

#: Default depth for a successful full probe.
DEPTH_OK = DepthLabel.DEEP

#: Default depth when the probe timed out or returned limited data.
DEPTH_PARTIAL = DepthLabel.SHALLOW

#: Default depth when the probe could not run at all.
DEPTH_MISSING = DepthLabel.UNAVAILABLE


class UnlabelledReportError(ValueError):
    """Raised when an engine report is missing a depth label.

    Message always names the engine and the unlabelled report so the wave
    gate can fail closed without guessing which seat was at fault.
    """

    def __init__(self, engine: str, report: Any = None, message: str = ""):
        eng = str(engine).strip() or "<unknown-engine>"
        if message:
            msg = message
        else:
            msg = (
                "engine %r: unlabelled report rejected — depth label required "
                "(report=%r)" % (eng, report)
            )
        super().__init__(msg)
        self.engine = eng
        self.report = report


class UnknownDepthError(ValueError):
    """Raised when a depth token is outside the closed vocabulary."""

    def __init__(self, engine: str, depth: Any):
        eng = str(engine).strip() or "<unknown-engine>"
        super().__init__(
            "engine %r: unknown depth label %r — must be one of %s"
            % (eng, depth, sorted(DEPTH_VALUES))
        )
        self.engine = eng
        self.depth = depth


# --------------------------------------------------------------------------
# Engine report
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class EngineReport:
    """One independent per-engine Doctor report.

    ``depth`` is required for a valid report. ``None`` (or blank) is the
    unlabelled form used only to prove validation rejects it.
    """

    engine: str
    named_state: NamedState
    depth: Optional[DepthLabel] = None
    ok: bool = False
    control_id: str = ""
    reading_name: Optional[str] = None
    reading_value: Any = None
    detail: str = ""
    fault: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "engine": self.engine,
            "named_state": self.named_state.value if self.named_state is not None else None,
            "depth": self.depth.value if self.depth is not None else None,
            "ok": self.ok,
            "control_id": self.control_id,
            "reading_name": self.reading_name,
            "reading_value": self.reading_value,
            "detail": self.detail,
            "fault": self.fault,
        }

    @property
    def is_labelled(self) -> bool:
        return self.depth is not None and str(self.depth.value).strip() != ""

    @property
    def depth_value(self) -> Optional[str]:
        return self.depth.value if self.depth is not None else None


# --------------------------------------------------------------------------
# Depth coercion + validation
# --------------------------------------------------------------------------


def coerce_depth(
    value: Union[DepthLabel, str, None],
    *,
    engine: str = "",
) -> Optional[DepthLabel]:
    """Coerce a depth token to :class:`DepthLabel`, or None if blank.

    Unknown non-blank tokens raise :class:`UnknownDepthError`.
    """
    if value is None:
        return None
    if isinstance(value, DepthLabel):
        return value
    raw = str(value).strip().lower()
    if not raw:
        return None
    for d in DepthLabel:
        if d.value == raw:
            return d
    raise UnknownDepthError(engine or "<unknown-engine>", value)


def validate_engine_report(report: EngineReport) -> DepthLabel:
    """Require a depth label on *report*; reject unlabelled reports by name.

    Returns the validated :class:`DepthLabel`. Raises
    :class:`UnlabelledReportError` naming the engine and the unlabelled report
    when depth is missing/blank. Raises :class:`UnknownDepthError` for an
    out-of-vocabulary token.
    """
    if report is None:
        raise UnlabelledReportError("<none>", report=None)

    engine = str(report.engine).strip() or "<unknown-engine>"
    depth = report.depth

    if depth is None:
        raise UnlabelledReportError(engine, report=report.as_dict())

    if isinstance(depth, DepthLabel):
        return depth

    coerced = coerce_depth(depth, engine=engine)
    if coerced is None:
        raise UnlabelledReportError(engine, report=report.as_dict())
    return coerced


def validate_engine_reports(
    reports: Union[Mapping[str, EngineReport], Sequence[EngineReport]],
) -> Dict[str, DepthLabel]:
    """Validate every report in a mapping or sequence; return engine→depth."""
    out: Dict[str, DepthLabel] = {}
    if isinstance(reports, Mapping):
        items: Iterable[EngineReport] = reports.values()
    else:
        items = reports
    for report in items:
        depth = validate_engine_report(report)
        out[report.engine] = depth
    return out


def require_depth(
    engine: str,
    depth: Union[DepthLabel, str, None],
) -> DepthLabel:
    """Return a DepthLabel or raise UnlabelledReportError / UnknownDepthError."""
    eng = str(engine).strip() or "<unknown-engine>"
    coerced = coerce_depth(depth, engine=eng)
    if coerced is None:
        raise UnlabelledReportError(
            eng,
            report={"engine": eng, "depth": depth},
            message=(
                "engine %r: unlabelled report rejected — depth label required"
                % eng
            ),
        )
    return coerced


def attach_depth(
    report: EngineReport,
    depth: Union[DepthLabel, str],
) -> EngineReport:
    """Return a copy of *report* with *depth* attached (always labelled)."""
    eng = report.engine
    d = require_depth(eng, depth)
    return EngineReport(
        engine=report.engine,
        named_state=report.named_state,
        depth=d,
        ok=report.ok,
        control_id=report.control_id,
        reading_name=report.reading_name,
        reading_value=report.reading_value,
        detail=report.detail,
        fault=report.fault,
    )


def make_engine_report(
    engine: str,
    named_state: NamedState,
    *,
    depth: Union[DepthLabel, str, None],
    ok: bool = False,
    reading_name: Optional[str] = None,
    reading_value: Any = None,
    detail: str = "",
    fault: Optional[str] = None,
    control_id: Optional[str] = None,
    require_label: bool = True,
) -> EngineReport:
    """Build an :class:`EngineReport`, optionally requiring a depth label.

    When ``require_label`` is True (default), missing depth raises
    :class:`UnlabelledReportError`. Set ``require_label=False`` only for
    tests that intentionally construct an unlabelled report.
    """
    eng = str(engine).strip().lower()
    if eng not in ENGINE_IDS and require_label:
        # Still allow non-canonical engines for isolation tests, but require depth.
        pass
    cid = control_id if control_id is not None else ENGINE_CONTROL_IDS.get(eng, "")
    if require_label:
        d = require_depth(eng, depth)
    else:
        d = coerce_depth(depth, engine=eng)
    return EngineReport(
        engine=eng,
        named_state=named_state,
        depth=d,
        ok=ok,
        control_id=cid,
        reading_name=reading_name,
        reading_value=reading_value,
        detail=detail,
        fault=fault,
    )


def depth_for_named_state(state: NamedState) -> DepthLabel:
    """Default depth mapping for a named probe outcome (not a shared verdict).

    Each engine still runs its own probe; this only suggests a depth token
    consistent with the named state the probe itself produced.
    """
    if state is NamedState.ok:
        return DepthLabel.DEEP
    if state is NamedState.timeout:
        return DepthLabel.SHALLOW
    if state is NamedState.empty:
        return DepthLabel.SHALLOW
    if state is NamedState.zero_measured:
        return DepthLabel.DEEP
    if state is NamedState.measurement_failed:
        return DepthLabel.SHALLOW
    if state is NamedState.unknown:
        return DepthLabel.UNAVAILABLE
    if state in (
        NamedState.cannot_run,
        NamedState.cannot_open,
        NamedState.cannot_retry,
        NamedState.cannot_restart,
    ):
        return DepthLabel.UNAVAILABLE
    if state is NamedState.stale:
        return DepthLabel.SHALLOW
    if state is NamedState.unmeasured:
        return DepthLabel.SHALLOW
    if state is NamedState.pending:
        return DepthLabel.UNAVAILABLE
    return DepthLabel.SHALLOW


__all__ = [
    "WAVE_ID",
    "SURFACE_ID",
    "ENGINE_CLAUDE",
    "ENGINE_GEMINI",
    "ENGINE_GROK",
    "ENGINE_IDS",
    "ENGINE_CONTROL_IDS",
    "ENGINE_LABELS",
    "DepthLabel",
    "DEPTH_VALUES",
    "DEPTH_OK",
    "DEPTH_PARTIAL",
    "DEPTH_MISSING",
    "UnlabelledReportError",
    "UnknownDepthError",
    "EngineReport",
    "coerce_depth",
    "validate_engine_report",
    "validate_engine_reports",
    "require_depth",
    "attach_depth",
    "make_engine_report",
    "depth_for_named_state",
]
