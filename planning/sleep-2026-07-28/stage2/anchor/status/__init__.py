"""Status cadence package — W20, Phase 3.

Timer-owned status cadence reading live telemetry with mandatory ``as_of``
and named staleness states (fresh / stale-with-age / unknown / empty).
"""
from __future__ import annotations

from anchor.status.cadence import (
    CAPABILITY_CONTROL_ID,
    DEFAULT_CADENCE_INTERVAL_SECONDS,
    SURFACE_ID,
    WAVE_ID,
    CadenceLoop,
    CadenceTick,
    StatusSnapshot,
    TelemetryOutage,
    TelemetrySample,
    TelemetrySource,
    force_snapshot_for_fault,
    read_status_snapshot,
)
from anchor.status.staleness import (
    STALENESS_THRESHOLD_SECONDS,
    Freshness,
    MissingAsOfError,
    StalenessResult,
    classify_staleness,
    require_as_of,
)

__all__ = [
    "CAPABILITY_CONTROL_ID",
    "DEFAULT_CADENCE_INTERVAL_SECONDS",
    "SURFACE_ID",
    "WAVE_ID",
    "CadenceLoop",
    "CadenceTick",
    "Freshness",
    "MissingAsOfError",
    "STALENESS_THRESHOLD_SECONDS",
    "StatusSnapshot",
    "StalenessResult",
    "TelemetryOutage",
    "TelemetrySample",
    "TelemetrySource",
    "classify_staleness",
    "force_snapshot_for_fault",
    "read_status_snapshot",
    "require_as_of",
]
