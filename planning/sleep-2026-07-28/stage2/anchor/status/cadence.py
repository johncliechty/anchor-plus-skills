"""Timer-owned status cadence from live telemetry — W20, Phase 3.

Anchor owns the cadence timer. Every tick reads live telemetry and emits a
``StatusSnapshot`` with a mandatory ISO ``as_of``. Tests inject the clock and
telemetry source so two intervals advance ``as_of`` without real wall time.

Honesty:

* **fresh** — sample age < staleness threshold → ``NamedState.ok``
* **stale** — aged sample → ``NamedState.stale`` with age shown
* **unknown** — telemetry outage / unreachable
* **empty** — telemetry readable, legitimately no series

No status is produced without ``as_of`` (``MissingAsOfError``).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from anchor.status.staleness import (
    STALENESS_THRESHOLD_SECONDS,
    Freshness,
    MissingAsOfError,
    StalenessResult,
    classify_staleness,
    format_as_of,
    require_as_of,
)
from anchor.ui.named_state import NamedState

# --------------------------------------------------------------------------
# Public constants
# --------------------------------------------------------------------------

WAVE_ID = "W20"
SURFACE_ID = "cadence"

#: Capability inventory control id (CAPABILITY-INVENTORY.md).
CAPABILITY_CONTROL_ID = "cadence_telemetry"
TELEMETRY_SOURCE_LABEL = "cadence telemetry source"
TELEMETRY_SOURCE_NAME = CAPABILITY_CONTROL_ID

#: Default cadence interval (seconds). Tests inject shorter intervals.
DEFAULT_CADENCE_INTERVAL_SECONDS: float = 600.0

#: Staleness bound re-exported for callers that only import cadence.
STALENESS_THRESHOLD = STALENESS_THRESHOLD_SECONDS


class CadenceReason(str, Enum):
    """Enumerated cadence outcomes / induced-fault reasons."""

    OK = "ok"
    FRESH = "fresh"
    STALE = "stale"
    TELEMETRY_OUTAGE = "telemetry_outage"
    EMPTY_SERIES = "empty_series"
    AGED_SAMPLE = "aged_sample"
    CAPABILITY_ABSENT = "capability_absent"
    MISSING_AS_OF = "missing_as_of"


CADENCE_REASONS: Tuple[str, ...] = tuple(r.value for r in CadenceReason)

INDUCED_FAULT_TELEMETRY_OUTAGE = CadenceReason.TELEMETRY_OUTAGE.value
INDUCED_FAULT_EMPTY_SERIES = CadenceReason.EMPTY_SERIES.value
INDUCED_FAULT_AGED_SAMPLE = CadenceReason.AGED_SAMPLE.value

INDUCED_FAULT_REASONS: Tuple[str, ...] = (
    INDUCED_FAULT_TELEMETRY_OUTAGE,
    INDUCED_FAULT_EMPTY_SERIES,
    INDUCED_FAULT_AGED_SAMPLE,
)

REASON_LABELS: Dict[str, str] = {
    CadenceReason.OK.value: "live telemetry status",
    CadenceReason.FRESH.value: "telemetry sample within freshness bound",
    CadenceReason.STALE.value: "telemetry sample aged past threshold",
    CadenceReason.TELEMETRY_OUTAGE.value: "telemetry unreachable",
    CadenceReason.EMPTY_SERIES.value: "telemetry readable; no series",
    CadenceReason.AGED_SAMPLE.value: "aged telemetry sample (stale-with-age)",
    CadenceReason.CAPABILITY_ABSENT.value: "cadence telemetry source absent",
    CadenceReason.MISSING_AS_OF.value: "status missing mandatory as_of",
}

REASON_STATE: Dict[str, NamedState] = {
    CadenceReason.OK.value: NamedState.ok,
    CadenceReason.FRESH.value: NamedState.ok,
    CadenceReason.STALE.value: NamedState.stale,
    CadenceReason.TELEMETRY_OUTAGE.value: NamedState.unknown,
    CadenceReason.EMPTY_SERIES.value: NamedState.empty,
    CadenceReason.AGED_SAMPLE.value: NamedState.stale,
    CadenceReason.CAPABILITY_ABSENT.value: NamedState.unknown,
    CadenceReason.MISSING_AS_OF.value: NamedState.unknown,
}


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class TelemetryOutage(Exception):
    """Raised when the live telemetry source cannot be reached."""

    def __init__(self, message: str = "telemetry unreachable"):
        super().__init__(message)
        self.message = message


class CadenceError(Exception):
    """Base error for cadence operations."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


# --------------------------------------------------------------------------
# Telemetry sample / source
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class TelemetrySample:
    """One live telemetry reading.

    ``as_of`` is the sample's own timestamp (ISO). ``series`` is the payload
    series; ``None`` or empty list with ``empty=True`` means legitimately empty.
    """

    as_of: str
    series: Optional[Sequence[Any]] = None
    empty: bool = False
    meta: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "as_of": self.as_of,
            "series": list(self.series) if self.series is not None else None,
            "empty": bool(self.empty),
            "meta": dict(self.meta),
        }

    @property
    def has_series(self) -> bool:
        if self.empty:
            return False
        if self.series is None:
            return False
        return len(list(self.series)) > 0


#: Callable / protocol: returns TelemetrySample or raises TelemetryOutage.
TelemetrySource = Callable[[], TelemetrySample]
ClockFn = Callable[[], datetime]


def _default_clock() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# CadenceTick / StatusSnapshot
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CadenceTick:
    """One fire of the Anchor-owned cadence timer.

    ``as_of`` is mandatory (ISO). ``tick_index`` is monotonic from the loop.
    ``interval_seconds`` records the cadence interval that produced this tick.
    """

    as_of: str
    tick_index: int
    interval_seconds: float
    source: str = TELEMETRY_SOURCE_NAME

    def __post_init__(self) -> None:
        require_as_of(self.as_of)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "as_of": self.as_of,
            "tick_index": int(self.tick_index),
            "interval_seconds": float(self.interval_seconds),
            "source": self.source,
        }


@dataclass(frozen=True)
class StatusSnapshot:
    """Rendered-status inputs after a cadence tick + staleness classification.

    ``as_of`` is mandatory. ``named_state`` is the surface vocabulary token.
    ``freshness`` is the cadence-native token (fresh/stale/unknown/empty).
    ``age_seconds`` is set for fresh/stale/empty; None for unknown outage.
    """

    as_of: str
    named_state: NamedState
    freshness: Freshness
    reason: str
    age_seconds: Optional[float] = None
    threshold_seconds: int = STALENESS_THRESHOLD_SECONDS
    tick_index: int = 0
    interval_seconds: float = DEFAULT_CADENCE_INTERVAL_SECONDS
    series: Optional[Sequence[Any]] = None
    telemetry_source: str = TELEMETRY_SOURCE_NAME
    detail: str = ""
    from_telemetry: bool = True
    tick: Optional[CadenceTick] = None
    staleness: Optional[StalenessResult] = None

    def __post_init__(self) -> None:
        require_as_of(self.as_of)

    @property
    def is_fresh(self) -> bool:
        return self.freshness is Freshness.fresh

    @property
    def is_stale(self) -> bool:
        return self.freshness is Freshness.stale

    @property
    def is_unknown(self) -> bool:
        return self.freshness is Freshness.unknown

    @property
    def is_empty(self) -> bool:
        return self.freshness is Freshness.empty

    def age_label(self) -> str:
        if self.age_seconds is None:
            return ""
        age = float(self.age_seconds)
        if age == int(age):
            return "%ds" % int(age)
        return "%.1fs" % age

    def as_dict(self) -> Dict[str, Any]:
        return {
            "as_of": self.as_of,
            "named_state": self.named_state.value,
            "freshness": self.freshness.value,
            "reason": self.reason,
            "age_seconds": self.age_seconds,
            "threshold_seconds": int(self.threshold_seconds),
            "tick_index": int(self.tick_index),
            "interval_seconds": float(self.interval_seconds),
            "series": list(self.series) if self.series is not None else None,
            "telemetry_source": self.telemetry_source,
            "detail": self.detail or "",
            "from_telemetry": bool(self.from_telemetry),
            "wave_id": WAVE_ID,
            "surface": SURFACE_ID,
        }


# --------------------------------------------------------------------------
# Snapshot construction
# --------------------------------------------------------------------------


def _snapshot_from_sample(
    sample: TelemetrySample,
    *,
    now: datetime,
    tick_index: int = 0,
    interval_seconds: float = DEFAULT_CADENCE_INTERVAL_SECONDS,
    threshold_seconds: int = STALENESS_THRESHOLD_SECONDS,
    tick: Optional[CadenceTick] = None,
) -> StatusSnapshot:
    stamp = require_as_of(sample.as_of)
    # Readable + empty series: explicit empty flag OR empty list.
    series_list = list(sample.series) if sample.series is not None else None
    empty = bool(sample.empty) or (series_list is not None and len(series_list) == 0)

    staleness = classify_staleness(
        as_of=stamp,
        now=now,
        threshold_seconds=threshold_seconds,
        unreachable=False,
        empty_series=empty,
    )
    reason = (
        CadenceReason.EMPTY_SERIES.value
        if staleness.freshness is Freshness.empty
        else (
            CadenceReason.STALE.value
            if staleness.freshness is Freshness.stale
            else CadenceReason.FRESH.value
        )
    )
    if staleness.freshness is Freshness.fresh:
        reason = CadenceReason.OK.value

    return StatusSnapshot(
        as_of=stamp,
        named_state=staleness.named_state,
        freshness=staleness.freshness,
        reason=reason,
        age_seconds=staleness.age_seconds,
        threshold_seconds=int(threshold_seconds),
        tick_index=tick_index,
        interval_seconds=float(interval_seconds),
        series=list(sample.series) if sample.series is not None else None,
        telemetry_source=TELEMETRY_SOURCE_NAME,
        detail=staleness.detail,
        from_telemetry=True,
        tick=tick,
        staleness=staleness,
    )


def _snapshot_unknown(
    *,
    as_of: str,
    tick_index: int = 0,
    interval_seconds: float = DEFAULT_CADENCE_INTERVAL_SECONDS,
    threshold_seconds: int = STALENESS_THRESHOLD_SECONDS,
    reason: str = CadenceReason.TELEMETRY_OUTAGE.value,
    detail: str = "telemetry unreachable",
    tick: Optional[CadenceTick] = None,
) -> StatusSnapshot:
    stamp = require_as_of(as_of)
    staleness = classify_staleness(
        as_of=stamp,
        now=stamp,  # age irrelevant for unknown
        threshold_seconds=threshold_seconds,
        unreachable=True,
    )
    return StatusSnapshot(
        as_of=stamp,
        named_state=NamedState.unknown,
        freshness=Freshness.unknown,
        reason=reason,
        age_seconds=None,
        threshold_seconds=int(threshold_seconds),
        tick_index=tick_index,
        interval_seconds=float(interval_seconds),
        series=None,
        telemetry_source=TELEMETRY_SOURCE_NAME,
        detail=detail,
        from_telemetry=False,
        tick=tick,
        staleness=staleness,
    )


def read_status_snapshot(
    *,
    telemetry: Optional[TelemetrySource] = None,
    clock: Optional[ClockFn] = None,
    tick_index: int = 0,
    interval_seconds: float = DEFAULT_CADENCE_INTERVAL_SECONDS,
    threshold_seconds: int = STALENESS_THRESHOLD_SECONDS,
    force_fault: Optional[str] = None,
    sample: Optional[TelemetrySample] = None,
    capability_present: bool = True,
) -> StatusSnapshot:
    """Read one status snapshot from live (or injected) telemetry.

    On outage, still emits a snapshot with ``as_of`` from the clock (the
    cadence tick time) and ``NamedState.unknown`` — never a blank status.
    """
    if force_fault:
        return force_snapshot_for_fault(
            force_fault,
            clock=clock,
            tick_index=tick_index,
            interval_seconds=interval_seconds,
            threshold_seconds=threshold_seconds,
        )

    now_fn = clock or _default_clock
    now = now_fn()
    if not isinstance(now, datetime):
        raise CadenceError("clock must return datetime, got %r" % type(now).__name__)
    tick_as_of = format_as_of(now)

    if not capability_present:
        return _snapshot_unknown(
            as_of=tick_as_of,
            tick_index=tick_index,
            interval_seconds=interval_seconds,
            threshold_seconds=threshold_seconds,
            reason=CadenceReason.CAPABILITY_ABSENT.value,
            detail="cadence telemetry source absent",
        )

    if sample is not None:
        return _snapshot_from_sample(
            sample,
            now=now,
            tick_index=tick_index,
            interval_seconds=interval_seconds,
            threshold_seconds=threshold_seconds,
        )

    if telemetry is None:
        # No source injected and no sample → honest unknown (not empty).
        return _snapshot_unknown(
            as_of=tick_as_of,
            tick_index=tick_index,
            interval_seconds=interval_seconds,
            threshold_seconds=threshold_seconds,
            reason=CadenceReason.TELEMETRY_OUTAGE.value,
            detail="no telemetry source bound",
        )

    try:
        live = telemetry()
    except TelemetryOutage as exc:
        return _snapshot_unknown(
            as_of=tick_as_of,
            tick_index=tick_index,
            interval_seconds=interval_seconds,
            threshold_seconds=threshold_seconds,
            reason=CadenceReason.TELEMETRY_OUTAGE.value,
            detail=str(exc) or "telemetry unreachable",
        )
    except Exception as exc:  # any other read failure → unknown
        return _snapshot_unknown(
            as_of=tick_as_of,
            tick_index=tick_index,
            interval_seconds=interval_seconds,
            threshold_seconds=threshold_seconds,
            reason=CadenceReason.TELEMETRY_OUTAGE.value,
            detail="telemetry read failed: %s" % (str(exc) or type(exc).__name__),
        )

    if not isinstance(live, TelemetrySample):
        # Garbage payload → unknown (never invent current status).
        return _snapshot_unknown(
            as_of=tick_as_of,
            tick_index=tick_index,
            interval_seconds=interval_seconds,
            threshold_seconds=threshold_seconds,
            reason=CadenceReason.TELEMETRY_OUTAGE.value,
            detail="telemetry returned non-sample payload",
        )

    return _snapshot_from_sample(
        live,
        now=now,
        tick_index=tick_index,
        interval_seconds=interval_seconds,
        threshold_seconds=threshold_seconds,
    )


def force_snapshot_for_fault(
    fault: str,
    *,
    clock: Optional[ClockFn] = None,
    tick_index: int = 0,
    interval_seconds: float = DEFAULT_CADENCE_INTERVAL_SECONDS,
    threshold_seconds: int = STALENESS_THRESHOLD_SECONDS,
    as_of: Optional[str] = None,
) -> StatusSnapshot:
    """Induce one named cadence fault for GWT / trace coverage."""
    key = str(fault or "").strip().lower().replace("-", "_")
    now_fn = clock or _default_clock
    now = now_fn()
    tick_as_of = require_as_of(as_of) if as_of else format_as_of(now)

    if key in (
        "telemetry_outage",
        "outage",
        "unreachable",
        "unknown",
        "read_failed",
    ):
        return _snapshot_unknown(
            as_of=tick_as_of,
            tick_index=tick_index,
            interval_seconds=interval_seconds,
            threshold_seconds=threshold_seconds,
            reason=CadenceReason.TELEMETRY_OUTAGE.value,
        )

    if key in ("empty_series", "empty", "empty_scope"):
        sample = TelemetrySample(as_of=tick_as_of, series=[], empty=True)
        return _snapshot_from_sample(
            sample,
            now=now,
            tick_index=tick_index,
            interval_seconds=interval_seconds,
            threshold_seconds=threshold_seconds,
        )

    if key in ("aged_sample", "stale", "stale_with_age"):
        # Place sample well past the threshold.
        thr = int(threshold_seconds)
        aged_seconds = thr + 30
        # as_of = now - aged_seconds
        from datetime import timedelta

        sample_dt = now - timedelta(seconds=aged_seconds)
        sample_as_of = format_as_of(sample_dt)
        sample = TelemetrySample(
            as_of=sample_as_of,
            series=[{"wave": 1, "status": "running"}],
            empty=False,
        )
        snap = _snapshot_from_sample(
            sample,
            now=now,
            tick_index=tick_index,
            interval_seconds=interval_seconds,
            threshold_seconds=threshold_seconds,
        )
        # Pin reason to aged_sample for fault enumeration.
        return replace(
            snap,
            reason=CadenceReason.AGED_SAMPLE.value,
        )

    if key in ("ok", "fresh", "live"):
        sample = TelemetrySample(
            as_of=tick_as_of,
            series=[{"wave": 1, "status": "running"}],
            empty=False,
        )
        return _snapshot_from_sample(
            sample,
            now=now,
            tick_index=tick_index,
            interval_seconds=interval_seconds,
            threshold_seconds=threshold_seconds,
        )

    if key in ("capability_absent", "absent"):
        return _snapshot_unknown(
            as_of=tick_as_of,
            tick_index=tick_index,
            interval_seconds=interval_seconds,
            threshold_seconds=threshold_seconds,
            reason=CadenceReason.CAPABILITY_ABSENT.value,
            detail="cadence telemetry source absent",
        )

    if key in ("missing_as_of",):
        # Exercise the choke-point: constructing without as_of must raise.
        raise MissingAsOfError(
            "status requires as_of — induced missing_as_of fault"
        )

    raise CadenceError("unknown cadence fault %r" % fault)


def cadence_reason_named_state(reason: str) -> NamedState:
    key = str(reason or "").strip().lower().replace("-", "_")
    if key in REASON_STATE:
        return REASON_STATE[key]
    return NamedState.unknown


# --------------------------------------------------------------------------
# CadenceLoop — Anchor-owned timer
# --------------------------------------------------------------------------


class CadenceLoop:
    """Timer-owned cadence loop reading live telemetry.

    Injectable ``clock`` and ``telemetry`` make the loop fully deterministic
    under test: advance the clock by ``interval_seconds`` and call ``tick()``
    (or ``run_until``) — ``as_of`` advances from telemetry, not a static string.
    """

    def __init__(
        self,
        *,
        telemetry: Optional[TelemetrySource] = None,
        clock: Optional[ClockFn] = None,
        interval_seconds: float = DEFAULT_CADENCE_INTERVAL_SECONDS,
        threshold_seconds: int = STALENESS_THRESHOLD_SECONDS,
        capability_present: bool = True,
    ) -> None:
        self._telemetry = telemetry
        self._clock = clock or _default_clock
        self.interval_seconds = float(interval_seconds)
        self.threshold_seconds = int(threshold_seconds)
        self.capability_present = bool(capability_present)
        self._tick_index = 0
        self._history: List[StatusSnapshot] = []
        self._last: Optional[StatusSnapshot] = None
        self._running = False

    @property
    def tick_index(self) -> int:
        return self._tick_index

    @property
    def history(self) -> List[StatusSnapshot]:
        return list(self._history)

    @property
    def last(self) -> Optional[StatusSnapshot]:
        return self._last

    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> StatusSnapshot:
        """Start the loop and emit the first tick immediately."""
        self._running = True
        return self.tick()

    def stop(self) -> None:
        self._running = False

    def tick(self) -> StatusSnapshot:
        """Fire one cadence interval: read telemetry, emit snapshot with as_of."""
        now = self._clock()
        if not isinstance(now, datetime):
            raise CadenceError(
                "clock must return datetime, got %r" % type(now).__name__
            )
        as_of = format_as_of(now)
        tick = CadenceTick(
            as_of=as_of,
            tick_index=self._tick_index,
            interval_seconds=self.interval_seconds,
            source=TELEMETRY_SOURCE_NAME,
        )
        snap = read_status_snapshot(
            telemetry=self._telemetry,
            clock=lambda: now,
            tick_index=self._tick_index,
            interval_seconds=self.interval_seconds,
            threshold_seconds=self.threshold_seconds,
            capability_present=self.capability_present,
        )
        # Attach the tick object (as_of already set from telemetry/clock).
        snap = replace(snap, tick=tick, tick_index=self._tick_index)
        # Guarantee as_of present (choke-point).
        require_as_of(snap.as_of)
        self._history.append(snap)
        self._last = snap
        self._tick_index += 1
        self._running = True
        return snap

    def run_ticks(self, n: int) -> List[StatusSnapshot]:
        """Fire ``n`` ticks in sequence (tests advance the clock between)."""
        if n < 0:
            raise CadenceError("run_ticks n must be non-negative, got %r" % n)
        out: List[StatusSnapshot] = []
        for _ in range(n):
            out.append(self.tick())
        return out

    def as_of_sequence(self) -> List[str]:
        """Return as_of stamps from every recorded tick (for advance asserts)."""
        return [s.as_of for s in self._history]


# --------------------------------------------------------------------------
# Test helpers / fixtures
# --------------------------------------------------------------------------


class FakeClock:
    """Deterministic clock for tests — advance by interval to fire cadence."""

    def __init__(self, start: Optional[datetime] = None) -> None:
        if start is None:
            start = datetime(2026, 7, 29, 12, 0, 0, tzinfo=timezone.utc)
        self._now = start

    def __call__(self) -> datetime:
        return self._now

    @property
    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> datetime:
        from datetime import timedelta

        self._now = self._now + timedelta(seconds=float(seconds))
        return self._now

    def set(self, dt: datetime) -> None:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        self._now = dt


class LiveTelemetry:
    """Injectable telemetry source that stamps as_of from a clock.

    Proves the GWT: as_of advances from telemetry (clock-driven sample),
    not from a static string in the status view.
    """

    def __init__(
        self,
        clock: ClockFn,
        *,
        series: Optional[Sequence[Any]] = None,
        empty: bool = False,
        fail_after: Optional[int] = None,
        unreachable: bool = False,
    ) -> None:
        self._clock = clock
        self._series = list(series) if series is not None else [{"wave": 1}]
        self._empty = bool(empty)
        self._fail_after = fail_after
        self._unreachable = bool(unreachable)
        self._calls = 0
        self.as_of_emitted: List[str] = []

    @property
    def calls(self) -> int:
        return self._calls

    def __call__(self) -> TelemetrySample:
        self._calls += 1
        if self._unreachable:
            raise TelemetryOutage("telemetry unreachable (injected)")
        if self._fail_after is not None and self._calls > self._fail_after:
            raise TelemetryOutage(
                "telemetry unreachable after %d reads" % self._fail_after
            )
        now = self._clock()
        stamp = format_as_of(now)
        self.as_of_emitted.append(stamp)
        if self._empty:
            return TelemetrySample(as_of=stamp, series=[], empty=True)
        return TelemetrySample(
            as_of=stamp,
            series=list(self._series),
            empty=False,
            meta={"call": self._calls},
        )


def make_fresh_sample(
    *,
    clock: Optional[ClockFn] = None,
    series: Optional[Sequence[Any]] = None,
) -> TelemetrySample:
    now = (clock or _default_clock)()
    return TelemetrySample(
        as_of=format_as_of(now),
        series=list(series) if series is not None else [{"wave": 1}],
        empty=False,
    )


def make_aged_sample(
    *,
    clock: Optional[ClockFn] = None,
    age_seconds: float = STALENESS_THRESHOLD_SECONDS + 30,
    series: Optional[Sequence[Any]] = None,
) -> TelemetrySample:
    from datetime import timedelta

    now = (clock or _default_clock)()
    sample_dt = now - timedelta(seconds=float(age_seconds))
    return TelemetrySample(
        as_of=format_as_of(sample_dt),
        series=list(series) if series is not None else [{"wave": 1}],
        empty=False,
    )


def make_empty_sample(*, clock: Optional[ClockFn] = None) -> TelemetrySample:
    now = (clock or _default_clock)()
    return TelemetrySample(as_of=format_as_of(now), series=[], empty=True)


__all__ = [
    "CADENCE_REASONS",
    "CAPABILITY_CONTROL_ID",
    "CadenceError",
    "CadenceLoop",
    "CadenceReason",
    "CadenceTick",
    "ClockFn",
    "DEFAULT_CADENCE_INTERVAL_SECONDS",
    "FakeClock",
    "INDUCED_FAULT_AGED_SAMPLE",
    "INDUCED_FAULT_EMPTY_SERIES",
    "INDUCED_FAULT_REASONS",
    "INDUCED_FAULT_TELEMETRY_OUTAGE",
    "LiveTelemetry",
    "REASON_LABELS",
    "REASON_STATE",
    "STALENESS_THRESHOLD",
    "SURFACE_ID",
    "StatusSnapshot",
    "TELEMETRY_SOURCE_LABEL",
    "TELEMETRY_SOURCE_NAME",
    "TelemetryOutage",
    "TelemetrySample",
    "TelemetrySource",
    "WAVE_ID",
    "cadence_reason_named_state",
    "force_snapshot_for_fault",
    "make_aged_sample",
    "make_empty_sample",
    "make_fresh_sample",
    "read_status_snapshot",
]
