"""Usage / time rollup reader — W12, Phase 3.

Reads only through ``anchor.build.rollup_registry.RollupRegistry`` (W4).
Surface waves never invent numerals:

* **PROVEN** (nonzero / zero_measured) → measured numeral + NamedState
* **PROVEN/empty** → empty (no numeral)
* **NO_AGGREGATOR** → pending naming the aggregation wave; numeral access
  **raises at test time** (``NumeralFromNoAggregator``)
* **READ_FAILED** → **unknown** only — never ``0``, never pending

E2 ``provisional data`` (usage/time only): a numeral may ship under a signed
E2 with a visible ``as_of`` stamp and a post-hoc reconciliation entry in
``EXECUTION-LOG.md``. Dollars remain illegal for E2 (W2/W7).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from anchor.build.rollup_registry import (
    NumeralFromEmpty,
    NumeralFromNoAggregator,
    NumeralFromReadFailed,
    RegistryEntry,
    RollupRegistry,
    RollupRegistryError,
    UnknownRollup,
    entry_from_evidence,
    registry_from_evidence_set,
)
from anchor.ui.named_state import NamedState
from tools.rollup_evidence_gate import (
    DEFAULT_AGGREGATION_WAVE,
    REQUIRED_ROLLUPS,
    RENDER_EMPTY,
    RENDER_OK,
    RENDER_PENDING,
    RENDER_UNKNOWN,
    RENDER_ZERO_MEASURED,
    RollupEvidence,
    RollupEvidenceSet,
    SubVerdict,
    Verdict,
    fixture_no_aggregator,
    fixture_proven_empty,
    fixture_proven_nonzero,
    fixture_proven_zero_measured,
    fixture_read_failed,
    pending_label,
    surface_render_for,
)

# --------------------------------------------------------------------------
# Public constants
# --------------------------------------------------------------------------

WAVE_ID = "W12"
SURFACE_ID = "usage-time"

#: The three UI surfaces criterion 3 usage/time tiles live on.
SURFACE_DASHBOARD = "dashboard"
SURFACE_WORKBENCH = "workbench"
SURFACE_SESSION_CHROME = "session_chrome"

USAGE_SURFACES: Tuple[str, ...] = (
    SURFACE_DASHBOARD,
    SURFACE_WORKBENCH,
    SURFACE_SESSION_CHROME,
)

METRIC_USAGE = "usage"
METRIC_TIME = "time"
USAGE_METRICS: Tuple[str, ...] = (METRIC_USAGE, METRIC_TIME)

#: Induced faults the W12 gate must exercise (one per named failure reason).
INDUCED_FAULT_EMPTY_SCOPE = "empty_scope"
INDUCED_FAULT_ZERO_MEASURED = "zero_measured"
INDUCED_FAULT_QUERY_FAILURE = "query_failure"
INDUCED_FAULT_ABSENT_AGGREGATOR = "absent_aggregator"

INDUCED_FAULT_REASONS: Tuple[str, ...] = (
    INDUCED_FAULT_EMPTY_SCOPE,
    INDUCED_FAULT_ZERO_MEASURED,
    INDUCED_FAULT_QUERY_FAILURE,
    INDUCED_FAULT_ABSENT_AGGREGATOR,
)

#: Marker used in EXECUTION-LOG reconciliation entries (machine-readable).
RECONCILIATION_MARKER = "usage-time-e2-reconciliation"
RECONCILIATION_SECTION_HEADER = "## W12 E2 provisional reconciliation"

EXECUTION_LOG_RELPATH = "EXECUTION-LOG.md"

# Map surface_render label → NamedState.
_RENDER_TO_STATE: Dict[str, NamedState] = {
    RENDER_PENDING: NamedState.pending,
    RENDER_UNKNOWN: NamedState.unknown,
    RENDER_EMPTY: NamedState.empty,
    RENDER_ZERO_MEASURED: NamedState.zero_measured,
    RENDER_OK: NamedState.ok,
}


# --------------------------------------------------------------------------
# Errors (re-export registry errors for call-site clarity)
# --------------------------------------------------------------------------


class UsageReadError(Exception):
    """Base error for usage/time rollup reads."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NumeralFromPending(UsageReadError, NumeralFromNoAggregator):
    """Alias: numeral access on NO_AGGREGATOR raises at test time."""


# --------------------------------------------------------------------------
# Result schema
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class UsageReadResult:
    """One usage or time rollup read as surfaces consume it.

    A bare ``0`` is never invented. ``numeral`` is set only when the registry
    authorizes a measured value (PROVEN/nonzero or PROVEN/zero_measured).
    Under E2 provisional data, ``is_provisional`` is True and ``as_of`` is
    required so the surface can stamp the number.
    """

    rollup_id: str
    surface: str
    metric: str
    verdict: Verdict
    sub_verdict: Optional[SubVerdict]
    named_state: NamedState
    numeral: Optional[Union[int, float]]
    aggregation_wave: Optional[str]
    pending_message: Optional[str]
    as_of: Optional[str] = None
    is_provisional: bool = False
    row_count: int = 0
    label: str = ""
    notes: str = ""

    @property
    def allows_numeral(self) -> bool:
        return self.numeral is not None and self.named_state in {
            NamedState.ok,
            NamedState.zero_measured,
        }

    @property
    def surface_render(self) -> str:
        return self.named_state.value

    def require_numeral(self) -> Union[int, float]:
        """Return the measured numeral or raise (test-time fail closed).

        * NO_AGGREGATOR → :class:`NumeralFromNoAggregator`
        * READ_FAILED → :class:`NumeralFromReadFailed`
        * PROVEN/empty → :class:`NumeralFromEmpty`
        * PROVEN zero/nonzero → the measured value (0 is legal for zero_measured)
        """
        if self.verdict is Verdict.NO_AGGREGATOR:
            raise NumeralFromNoAggregator(
                "cannot render a numeral from NO_AGGREGATOR rollup %r — "
                "surface must render pending naming wave %r"
                % (self.rollup_id, self.aggregation_wave)
            )
        if self.verdict is Verdict.READ_FAILED:
            raise NumeralFromReadFailed(
                "cannot render a numeral from READ_FAILED rollup %r — "
                "surface may render only unknown" % self.rollup_id
            )
        if self.verdict is Verdict.PROVEN and self.sub_verdict is SubVerdict.EMPTY:
            raise NumeralFromEmpty(
                "cannot render a numeral from PROVEN/empty rollup %r — "
                "scope is empty" % self.rollup_id
            )
        if self.numeral is None:
            raise UsageReadError(
                "rollup %r has no renderable numeral (state=%s)"
                % (self.rollup_id, self.named_state.value)
            )
        return self.numeral

    def as_dict(self) -> Dict[str, Any]:
        return {
            "rollup_id": self.rollup_id,
            "surface": self.surface,
            "metric": self.metric,
            "verdict": self.verdict.value,
            "sub_verdict": self.sub_verdict.value if self.sub_verdict else None,
            "named_state": self.named_state.value,
            "numeral": self.numeral,
            "aggregation_wave": self.aggregation_wave,
            "pending_message": self.pending_message,
            "as_of": self.as_of,
            "is_provisional": self.is_provisional,
            "row_count": self.row_count,
            "label": self.label,
            "notes": self.notes,
            "allows_numeral": self.allows_numeral,
        }


# --------------------------------------------------------------------------
# Path / id helpers
# --------------------------------------------------------------------------


def containment_root(root: Optional[Path] = None) -> Path:
    if root is not None:
        return Path(root)
    env = os.environ.get("ANCHOR_SLEEP_CONTAINMENT_ROOT")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2]


def rollup_id_for(surface: str, metric: str) -> str:
    """Map surface + metric → registry rollup id (e.g. dashboard_usage)."""
    s = str(surface or "").strip().lower().replace("-", "_").replace(" ", "_")
    m = str(metric or "").strip().lower()
    if s == "sessionchrome":
        s = SURFACE_SESSION_CHROME
    if s not in USAGE_SURFACES:
        raise UsageReadError(
            "unknown usage surface %r — expected one of %s" % (surface, USAGE_SURFACES)
        )
    if m not in USAGE_METRICS:
        raise UsageReadError(
            "unknown usage metric %r — expected one of %s" % (metric, USAGE_METRICS)
        )
    return "%s_%s" % (s, m)


def parse_surface_metric(rollup_id: str) -> Tuple[str, str]:
    rid = str(rollup_id or "").strip()
    for surface in USAGE_SURFACES:
        for metric in USAGE_METRICS:
            if rid == "%s_%s" % (surface, metric):
                return surface, metric
    # Cost rollups are out of W12 scope — still parse shape for registry tests.
    if rid.endswith("_usage"):
        return rid[: -len("_usage")], METRIC_USAGE
    if rid.endswith("_time"):
        return rid[: -len("_time")], METRIC_TIME
    raise UsageReadError("cannot parse surface/metric from rollup_id %r" % rollup_id)


def _named_state_for_entry(entry: RegistryEntry) -> NamedState:
    token = entry.surface_render
    ns = _RENDER_TO_STATE.get(token)
    if ns is None:
        # Fail closed to unknown rather than invent a numeral/label.
        return NamedState.unknown
    return ns


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


# --------------------------------------------------------------------------
# Core read
# --------------------------------------------------------------------------


def read_usage_rollup(
    surface: str,
    metric: str = METRIC_USAGE,
    *,
    registry: Optional[RollupRegistry] = None,
    entry: Optional[RegistryEntry] = None,
    evidence: Optional[RollupEvidence] = None,
    provisional: bool = False,
    as_of: Optional[str] = None,
    raise_on_no_aggregator_numeral: bool = False,
) -> UsageReadResult:
    """Read one usage/time rollup and map it to a NamedState + optional numeral.

    Parameters
    ----------
    raise_on_no_aggregator_numeral:
        When True **and** the rollup is NO_AGGREGATOR, raise immediately
        (test-time path that asserts numeral access is illegal). The normal
        surface path leaves ``numeral=None`` and returns pending.
    provisional / as_of:
        E2 provisional data path. A measured numeral under provisional requires
        a non-empty ``as_of`` stamp; the surface stamps it beside the number.
    """
    rid = rollup_id_for(surface, metric)
    surf, met = parse_surface_metric(rid)

    if evidence is not None:
        reg_entry = entry_from_evidence(evidence)
    elif entry is not None:
        reg_entry = entry
    elif registry is not None:
        reg_entry = registry.require(rid)
    else:
        raise UsageReadError(
            "read_usage_rollup requires registry, entry, or evidence for %r" % rid
        )

    if reg_entry.rollup_id != rid and evidence is None and entry is None:
        # Registry looked up by id — ok. When injecting entry/evidence, allow
        # the injected rollup_id to drive surface/metric if it matches shape.
        pass

    # Prefer the entry's own id when tests inject fixtures under that id.
    effective_id = reg_entry.rollup_id
    try:
        surf, met = parse_surface_metric(effective_id)
    except UsageReadError:
        surf, met = surface, metric

    named = _named_state_for_entry(reg_entry)
    numeral: Optional[Union[int, float]] = None
    pending_msg: Optional[str] = None
    wave = reg_entry.aggregation_wave

    if reg_entry.verdict is Verdict.NO_AGGREGATOR:
        named = NamedState.pending
        pending_msg = (
            "pending (awaits %s)"
            % (wave or DEFAULT_AGGREGATION_WAVE)
        )
        if raise_on_no_aggregator_numeral:
            raise NumeralFromNoAggregator(
                "cannot render a numeral from NO_AGGREGATOR rollup %r — "
                "surface must render pending naming wave %r"
                % (effective_id, wave)
            )
        # Never invent 0 or pending-as-numeral.
        numeral = None
    elif reg_entry.verdict is Verdict.READ_FAILED:
        named = NamedState.unknown
        # Never 0, never pending.
        numeral = None
        pending_msg = None
    elif reg_entry.verdict is Verdict.PROVEN:
        if reg_entry.sub_verdict is SubVerdict.EMPTY:
            named = NamedState.empty
            numeral = None
        elif reg_entry.sub_verdict is SubVerdict.ZERO_MEASURED:
            named = NamedState.zero_measured
            numeral = 0 if reg_entry.total is None else reg_entry.total
        elif reg_entry.sub_verdict is SubVerdict.NONZERO:
            named = NamedState.ok
            if reg_entry.total is None:
                raise UsageReadError(
                    "PROVEN/nonzero rollup %r has no total" % effective_id
                )
            numeral = reg_entry.total
        else:
            named = NamedState.unknown
            numeral = None

    # E2 provisional: measured numerals require as_of; non-measured ignore.
    is_prov = bool(provisional) and numeral is not None
    as_of_stamp: Optional[str] = None
    if is_prov:
        as_of_stamp = (as_of or "").strip() or _utc_now_iso()
    elif provisional and numeral is None:
        # Provisional flag on a non-numeric state is a no-op (still honest).
        is_prov = False
        as_of_stamp = None

    return UsageReadResult(
        rollup_id=effective_id,
        surface=surf,
        metric=met,
        verdict=reg_entry.verdict,
        sub_verdict=reg_entry.sub_verdict,
        named_state=named,
        numeral=numeral,
        aggregation_wave=wave,
        pending_message=pending_msg,
        as_of=as_of_stamp,
        is_provisional=is_prov,
        row_count=reg_entry.row_count,
        label=reg_entry.label,
        notes="",
    )


def read_from_registry(
    registry: RollupRegistry,
    surface: str,
    metric: str = METRIC_USAGE,
    **kwargs: Any,
) -> UsageReadResult:
    return read_usage_rollup(surface, metric, registry=registry, **kwargs)


# --------------------------------------------------------------------------
# Induced-fault fixtures (one per W12 named failure reason)
# --------------------------------------------------------------------------


def force_read_for_fault(
    fault: str,
    *,
    surface: str = SURFACE_DASHBOARD,
    metric: str = METRIC_USAGE,
    aggregation_wave: str = "W12-usage-aggregation",
) -> UsageReadResult:
    """Build a UsageReadResult under one induced fault (gate GWT suite)."""
    key = str(fault or "").strip().lower().replace("-", "_")
    rid = rollup_id_for(surface, metric)

    if key in (
        INDUCED_FAULT_EMPTY_SCOPE,
        "empty",
        "empty_result_set",
        "scope_empty",
    ):
        ev = fixture_proven_empty(rid)
        return read_usage_rollup(surface, metric, evidence=ev)

    if key in (
        INDUCED_FAULT_ZERO_MEASURED,
        "measured_zero",
        "zero",
    ):
        ev = fixture_proven_zero_measured(rid, scope_size=12)
        return read_usage_rollup(surface, metric, evidence=ev)

    if key in (
        INDUCED_FAULT_QUERY_FAILURE,
        "query_failed",
        "read_failed",
        "read_failure",
    ):
        ev = fixture_read_failed(rid)
        return read_usage_rollup(surface, metric, evidence=ev)

    if key in (
        INDUCED_FAULT_ABSENT_AGGREGATOR,
        "no_aggregator",
        "pending",
        "absent",
    ):
        ev = fixture_no_aggregator(rid, aggregation_wave=aggregation_wave)
        return read_usage_rollup(surface, metric, evidence=ev)

    raise UsageReadError(
        "unknown induced fault %r — expected one of %s"
        % (fault, INDUCED_FAULT_REASONS)
    )


def registry_with_entries(entries: Sequence[RegistryEntry]) -> RollupRegistry:
    return RollupRegistry(entries)


def registry_from_fixtures(
    mapping: Mapping[str, RollupEvidence],
) -> RollupRegistry:
    s = RollupEvidenceSet()
    for _rid, ev in mapping.items():
        s.upsert(ev)
    return registry_from_evidence_set(s)


# --------------------------------------------------------------------------
# E2 provisional reconciliation hook
# --------------------------------------------------------------------------


def reconciliation_entry_text(
    *,
    rollup_id: str,
    numeral: Union[int, float],
    as_of: str,
    wave_id: str = WAVE_ID,
    note: str = "",
) -> str:
    """Format one machine-readable reconciliation line for EXECUTION-LOG."""
    stamp = (as_of or "").strip() or _utc_now_iso()
    body = (
        "- **%s** — wave=%s rollup=%s numeral=%s as_of=%s"
        % (RECONCILIATION_MARKER, wave_id, rollup_id, numeral, stamp)
    )
    if note:
        body += " — %s" % note.strip()
    return body


def record_e2_reconciliation(
    result: UsageReadResult,
    *,
    root: Optional[Path] = None,
    log_path: Optional[Path] = None,
    note: str = "post-hoc reconciliation pending for provisional usage/time",
) -> str:
    """Append a reconciliation entry for an E2 provisional usage/time count.

    Returns the line written. Raises if the result is not provisional with a
    numeral + as_of (E2 path only — never for READ_FAILED / NO_AGGREGATOR).
    """
    if not result.is_provisional or result.numeral is None:
        raise UsageReadError(
            "record_e2_reconciliation requires a provisional measured "
            "usage/time result (got provisional=%s numeral=%r)"
            % (result.is_provisional, result.numeral)
        )
    if not result.as_of:
        raise UsageReadError(
            "provisional usage/time requires a non-empty as_of stamp"
        )

    line = reconciliation_entry_text(
        rollup_id=result.rollup_id,
        numeral=result.numeral,
        as_of=result.as_of,
        note=note,
    )

    path = log_path
    if path is None:
        path = containment_root(root) / EXECUTION_LOG_RELPATH

    path.parent.mkdir(parents=True, exist_ok=True)
    existing = ""
    if path.is_file():
        existing = path.read_text(encoding="utf-8")

    if RECONCILIATION_SECTION_HEADER not in existing:
        block = (
            "\n\n%s\n\n"
            "Provisional usage/time counts shipped under signed E2 "
            "(`provisional data`) with visible `as_of` stamps. Each entry "
            "below is a post-hoc reconciliation hook (orchestrator-owned "
            "resolution). Paths stay relative; no absolute host paths.\n\n"
            "%s\n"
            % (RECONCILIATION_SECTION_HEADER, line)
        )
        path.write_text(existing.rstrip() + block + "\n", encoding="utf-8")
    else:
        # Append under the existing section if the exact line is absent.
        if line not in existing:
            path.write_text(existing.rstrip() + "\n" + line + "\n", encoding="utf-8")

    return line


def has_reconciliation_entry(
    *,
    root: Optional[Path] = None,
    log_path: Optional[Path] = None,
    rollup_id: Optional[str] = None,
) -> bool:
    """True when EXECUTION-LOG carries a W12 E2 reconciliation entry."""
    path = log_path
    if path is None:
        path = containment_root(root) / EXECUTION_LOG_RELPATH
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    if RECONCILIATION_MARKER not in text:
        return False
    if rollup_id and ("rollup=%s" % rollup_id) not in text:
        return False
    return True


# Re-export registry numeral errors for tests.
__all__ = [
    "DEFAULT_AGGREGATION_WAVE",
    "EXECUTION_LOG_RELPATH",
    "INDUCED_FAULT_ABSENT_AGGREGATOR",
    "INDUCED_FAULT_EMPTY_SCOPE",
    "INDUCED_FAULT_QUERY_FAILURE",
    "INDUCED_FAULT_REASONS",
    "INDUCED_FAULT_ZERO_MEASURED",
    "METRIC_TIME",
    "METRIC_USAGE",
    "NumeralFromEmpty",
    "NumeralFromNoAggregator",
    "NumeralFromPending",
    "NumeralFromReadFailed",
    "RECONCILIATION_MARKER",
    "RECONCILIATION_SECTION_HEADER",
    "SURFACE_DASHBOARD",
    "SURFACE_SESSION_CHROME",
    "SURFACE_WORKBENCH",
    "SURFACE_ID",
    "USAGE_METRICS",
    "USAGE_SURFACES",
    "UsageReadError",
    "UsageReadResult",
    "WAVE_ID",
    "containment_root",
    "force_read_for_fault",
    "has_reconciliation_entry",
    "parse_surface_metric",
    "read_from_registry",
    "read_usage_rollup",
    "reconciliation_entry_text",
    "record_e2_reconciliation",
    "registry_from_fixtures",
    "registry_with_entries",
    "rollup_id_for",
]
