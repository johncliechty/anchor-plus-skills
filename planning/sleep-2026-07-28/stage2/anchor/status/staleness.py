"""Staleness classification for cadence status — W20, Phase 3.

Named states (surface-native via ``NamedState``):

* **fresh** — sample age < ``STALENESS_THRESHOLD_SECONDS`` → ``NamedState.ok``
* **stale** — sample age >= threshold → ``NamedState.stale`` **with age shown**
* **unknown** — telemetry unreachable → ``NamedState.unknown``
* **empty** — telemetry readable but no series (legitimately empty)

No status may be classified without an ``as_of`` ISO timestamp. A missing
``as_of`` raises ``MissingAsOfError`` so a confidently current-looking blank
cannot ship.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, Union

from anchor.ui.named_state import NamedState

# --------------------------------------------------------------------------
# Named numeric bound (plan: untestable adjectives forbidden)
# --------------------------------------------------------------------------

#: Age at or above this many seconds is **stale** (not current-looking).
STALENESS_THRESHOLD_SECONDS: int = 120

WAVE_ID = "W20"
SURFACE_ID = "cadence"


class Freshness(str, Enum):
    """Cadence-native freshness vocabulary (maps onto NamedState)."""

    fresh = "fresh"
    stale = "stale"
    unknown = "unknown"
    empty = "empty"


#: Freshness token → NamedState (render_state vocabulary).
FRESHNESS_NAMED_STATE = {
    Freshness.fresh: NamedState.ok,
    Freshness.stale: NamedState.stale,
    Freshness.unknown: NamedState.unknown,
    Freshness.empty: NamedState.empty,
}

FRESHNESS_DEFINITIONS = {
    Freshness.fresh: (
        "telemetry sample age is strictly less than the staleness threshold; "
        "status may be presented as current (NamedState.ok)."
    ),
    Freshness.stale: (
        "telemetry sample age is at or above the staleness threshold; "
        "status is labelled stale with its age shown — never current-looking."
    ),
    Freshness.unknown: (
        "telemetry is unreachable (read failed / outage); status is unknown "
        "— never empty, never a confidently current-looking status."
    ),
    Freshness.empty: (
        "telemetry is readable but there is legitimately no series "
        "(empty scope); distinct from unknown and from stale."
    ),
}


class MissingAsOfError(ValueError):
    """Raised when a status is classified or rendered without as_of."""

    def __init__(self, message: str = "status requires as_of — no status without as_of"):
        super().__init__(message)
        self.message = message


class StalenessError(ValueError):
    """Raised when staleness inputs are invalid."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


# --------------------------------------------------------------------------
# Result type
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class StalenessResult:
    """Classified freshness for one status sample.

    ``as_of`` is mandatory. ``age_seconds`` is None only for unknown (no
    trustworthy sample age). ``stale`` always carries a non-negative age.
    """

    freshness: Freshness
    named_state: NamedState
    as_of: str
    age_seconds: Optional[float] = None
    threshold_seconds: int = STALENESS_THRESHOLD_SECONDS
    detail: str = ""

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
        """User-visible age fragment for stale (and optional fresh) display."""
        if self.age_seconds is None:
            return ""
        age = float(self.age_seconds)
        if age == int(age):
            return "%ds" % int(age)
        return "%.1fs" % age

    def as_dict(self) -> dict:
        return {
            "freshness": self.freshness.value,
            "named_state": self.named_state.value,
            "as_of": self.as_of,
            "age_seconds": self.age_seconds,
            "threshold_seconds": int(self.threshold_seconds),
            "detail": self.detail or "",
        }


# --------------------------------------------------------------------------
# as_of parsing / requirement
# --------------------------------------------------------------------------


def require_as_of(as_of: Any) -> str:
    """Return a non-blank as_of string or raise ``MissingAsOfError``.

    Every rendered status MUST carry as_of; this is the single choke-point.
    """
    if as_of is None:
        raise MissingAsOfError(
            "status requires as_of — got None (no status without as_of)"
        )
    text = str(as_of).strip()
    if not text:
        raise MissingAsOfError(
            "status requires as_of — got blank (no status without as_of)"
        )
    return text


def parse_as_of(as_of: str) -> datetime:
    """Parse an ISO-8601 as_of into an aware UTC datetime."""
    text = require_as_of(as_of)
    # Accept trailing Z and common ISO forms.
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise StalenessError("as_of is not valid ISO-8601: %r" % as_of) from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_as_of(dt: datetime) -> str:
    """Format a datetime as ISO-8601 with Z suffix (UTC)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    # Second precision; drop microseconds for stable test stamps.
    s = dt.replace(microsecond=0).isoformat()
    if s.endswith("+00:00"):
        s = s[:-6] + "Z"
    return s


def age_seconds_between(as_of: str, now: Union[datetime, float, int, str]) -> float:
    """Return non-negative age of ``as_of`` relative to ``now``."""
    sample_dt = parse_as_of(as_of)
    if isinstance(now, datetime):
        now_dt = now
        if now_dt.tzinfo is None:
            now_dt = now_dt.replace(tzinfo=timezone.utc)
        else:
            now_dt = now_dt.astimezone(timezone.utc)
    elif isinstance(now, (int, float)):
        now_dt = datetime.fromtimestamp(float(now), tz=timezone.utc)
    else:
        now_dt = parse_as_of(str(now))
    delta = (now_dt - sample_dt).total_seconds()
    if delta < 0:
        # Clock skew: treat as age 0 (fresh), never negative age display.
        return 0.0
    return float(delta)


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------


def classify_staleness(
    *,
    as_of: Any,
    now: Union[datetime, float, int, str],
    threshold_seconds: int = STALENESS_THRESHOLD_SECONDS,
    unreachable: bool = False,
    empty_series: bool = False,
) -> StalenessResult:
    """Classify freshness for a telemetry sample.

    Precedence:

    1. ``unreachable`` → **unknown** (as_of still required — the cadence
       tick's as_of, not the sample's).
    2. ``empty_series`` → **empty** (readable, legitimately no series).
    3. age < threshold → **fresh** (``NamedState.ok``).
    4. age >= threshold → **stale** with age shown (``NamedState.stale``).
    """
    stamp = require_as_of(as_of)
    thr = int(threshold_seconds)
    if thr < 0:
        raise StalenessError("threshold_seconds must be non-negative, got %r" % thr)

    if unreachable:
        return StalenessResult(
            freshness=Freshness.unknown,
            named_state=NamedState.unknown,
            as_of=stamp,
            age_seconds=None,
            threshold_seconds=thr,
            detail="telemetry unreachable",
        )

    if empty_series:
        age = age_seconds_between(stamp, now)
        return StalenessResult(
            freshness=Freshness.empty,
            named_state=NamedState.empty,
            as_of=stamp,
            age_seconds=age,
            threshold_seconds=thr,
            detail="telemetry readable; no series (empty scope)",
        )

    age = age_seconds_between(stamp, now)
    if age >= thr:
        return StalenessResult(
            freshness=Freshness.stale,
            named_state=NamedState.stale,
            as_of=stamp,
            age_seconds=age,
            threshold_seconds=thr,
            detail="sample age %s >= threshold %ds" % (
                ("%ds" % int(age)) if age == int(age) else ("%.1fs" % age),
                thr,
            ),
        )

    return StalenessResult(
        freshness=Freshness.fresh,
        named_state=NamedState.ok,
        as_of=stamp,
        age_seconds=age,
        threshold_seconds=thr,
        detail="sample age within threshold",
    )


def freshness_to_named_state(freshness: Union[Freshness, str]) -> NamedState:
    """Map a freshness token onto the surface NamedState vocabulary."""
    if isinstance(freshness, Freshness):
        return FRESHNESS_NAMED_STATE[freshness]
    key = str(freshness).strip().lower().replace("-", "_")
    # Accept "ok" as alias for fresh (render path).
    if key in ("ok", "current"):
        key = Freshness.fresh.value
    try:
        fr = Freshness(key)
    except ValueError as exc:
        raise StalenessError("unknown freshness token %r" % freshness) from exc
    return FRESHNESS_NAMED_STATE[fr]


__all__ = [
    "FRESHNESS_DEFINITIONS",
    "FRESHNESS_NAMED_STATE",
    "Freshness",
    "MissingAsOfError",
    "STALENESS_THRESHOLD_SECONDS",
    "SURFACE_ID",
    "StalenessError",
    "StalenessResult",
    "WAVE_ID",
    "age_seconds_between",
    "classify_staleness",
    "format_as_of",
    "freshness_to_named_state",
    "parse_as_of",
    "require_as_of",
]
