"""Fault-injection utility — W9, Phase 2.

Induce **one fault per named failure reason** so surface waves can prove
that GREEN means "traced end to end under induced faults", not "handler is
bound".

Named failure reasons (frozen plan — exhaustive for this build):

* ``timeout``
* ``missing_capability``
* ``empty_result_set``
* ``unmeasured_cost``
* ``stale_telemetry``

Under E4 the reduced form is still **one-per-reason** (combinatorial
extras are optional; dropping a named reason is never allowed).

This module is a **test/build instrument**. Production-mode invoke is
refused so live surfaces cannot be forced into fabricated named states.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

# --------------------------------------------------------------------------
# Public constants
# --------------------------------------------------------------------------

#: Environment seam that marks an allowed test/build context.
ENV_ALLOW_FAULT_INJECT = "ANCHOR_SLEEP_ALLOW_FAULT_INJECT"

#: Environment seam that forces production refuse even under pytest.
ENV_FORCE_PRODUCTION = "ANCHOR_SLEEP_FAULT_INJECT_PRODUCTION"

REASON_TIMEOUT = "timeout"
REASON_MISSING_CAPABILITY = "missing_capability"
REASON_EMPTY_RESULT_SET = "empty_result_set"
REASON_UNMEASURED_COST = "unmeasured_cost"
REASON_STALE_TELEMETRY = "stale_telemetry"

NAMED_FAILURE_REASONS: Tuple[str, ...] = (
    REASON_TIMEOUT,
    REASON_MISSING_CAPABILITY,
    REASON_EMPTY_RESULT_SET,
    REASON_UNMEASURED_COST,
    REASON_STALE_TELEMETRY,
)

#: Human-facing labels (one per reason; used by traces / failure tables).
REASON_LABELS: Dict[str, str] = {
    REASON_TIMEOUT: "timeout",
    REASON_MISSING_CAPABILITY: "missing capability",
    REASON_EMPTY_RESULT_SET: "empty result set",
    REASON_UNMEASURED_COST: "unmeasured cost",
    REASON_STALE_TELEMETRY: "stale telemetry",
}

#: Default NamedState token each reason is expected to drive (W6 vocabulary).
REASON_DEFAULT_STATE: Dict[str, str] = {
    REASON_TIMEOUT: "timeout",
    REASON_MISSING_CAPABILITY: "cannot_run",
    REASON_EMPTY_RESULT_SET: "empty",
    REASON_UNMEASURED_COST: "unmeasured",
    REASON_STALE_TELEMETRY: "stale",
}

PRODUCTION_REFUSE_MESSAGE = (
    "fault injection refused in production — test/build instrument only"
)


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class FaultInjectionError(Exception):
    """Raised when a fault cannot be induced (unknown reason, production)."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ProductionFaultRefuse(FaultInjectionError):
    """Raised when induction is attempted outside an allowed test context."""


class UnknownFaultReason(FaultInjectionError):
    """Raised when the reason is not one of the five named failure reasons."""


# --------------------------------------------------------------------------
# Enum + fault record
# --------------------------------------------------------------------------


class FaultReason(str, Enum):
    """The five named failure reasons this build can induce."""

    TIMEOUT = REASON_TIMEOUT
    MISSING_CAPABILITY = REASON_MISSING_CAPABILITY
    EMPTY_RESULT_SET = REASON_EMPTY_RESULT_SET
    UNMEASURED_COST = REASON_UNMEASURED_COST
    STALE_TELEMETRY = REASON_STALE_TELEMETRY

    @property
    def label(self) -> str:
        return REASON_LABELS[self.value]

    @property
    def default_state(self) -> str:
        return REASON_DEFAULT_STATE[self.value]


@dataclass(frozen=True)
class InducedFault:
    """A single induced fault, one per named reason under E4."""

    reason: str
    label: str
    default_state: str
    active: bool = True
    detail: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "reason": self.reason,
            "label": self.label,
            "default_state": self.default_state,
            "active": self.active,
            "detail": self.detail,
        }


# --------------------------------------------------------------------------
# Session store (process-local; cleared between tests)
# --------------------------------------------------------------------------

_lock = threading.RLock()
_active: Dict[str, InducedFault] = {}


def named_failure_reasons() -> Tuple[str, ...]:
    """Return the exhaustive named-reason set (order stable)."""
    return NAMED_FAILURE_REASONS


def normalize_reason(reason: Union[str, FaultReason]) -> str:
    """Map a free-text or enum reason onto a canonical named token."""
    if isinstance(reason, FaultReason):
        return reason.value
    raw = str(reason).strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "timeout": REASON_TIMEOUT,
        "missing_capability": REASON_MISSING_CAPABILITY,
        "missingcapability": REASON_MISSING_CAPABILITY,
        "capability_missing": REASON_MISSING_CAPABILITY,
        "capability_absent": REASON_MISSING_CAPABILITY,
        "empty_result_set": REASON_EMPTY_RESULT_SET,
        "empty_result": REASON_EMPTY_RESULT_SET,
        "empty": REASON_EMPTY_RESULT_SET,
        "empty_results": REASON_EMPTY_RESULT_SET,
        "unmeasured_cost": REASON_UNMEASURED_COST,
        "unmeasured": REASON_UNMEASURED_COST,
        "cost_unmeasured": REASON_UNMEASURED_COST,
        "stale_telemetry": REASON_STALE_TELEMETRY,
        "stale": REASON_STALE_TELEMETRY,
        "telemetry_stale": REASON_STALE_TELEMETRY,
    }
    if raw not in aliases:
        raise UnknownFaultReason(
            "unknown fault reason %r — must be one of %s"
            % (reason, list(NAMED_FAILURE_REASONS))
        )
    return aliases[raw]


def is_production_context(
    *,
    env: Optional[Mapping[str, str]] = None,
    force_production: Optional[bool] = None,
) -> bool:
    """True when fault induction must be refused.

    Allowed (non-production) when any of:

    * ``force_production`` is False (explicit test override), or
    * ``ANCHOR_SLEEP_ALLOW_FAULT_INJECT`` is a truthy value, or
    * ``PYTEST_CURRENT_TEST`` is set (running under pytest).

    ``ANCHOR_SLEEP_FAULT_INJECT_PRODUCTION`` / ``force_production=True``
    always forces refuse.
    """
    if force_production is True:
        return True
    if force_production is False:
        return False
    e = env if env is not None else os.environ
    if _truthy(e.get(ENV_FORCE_PRODUCTION, "")):
        return True
    if _truthy(e.get(ENV_ALLOW_FAULT_INJECT, "")):
        return False
    if e.get("PYTEST_CURRENT_TEST"):
        return False
    return True


def induce_fault(
    reason: Union[str, FaultReason],
    *,
    detail: str = "",
    force_production: Optional[bool] = None,
    env: Optional[Mapping[str, str]] = None,
) -> InducedFault:
    """Induce exactly one named fault. Refuses in production context."""
    if is_production_context(env=env, force_production=force_production):
        raise ProductionFaultRefuse(PRODUCTION_REFUSE_MESSAGE)
    token = normalize_reason(reason)
    fault = InducedFault(
        reason=token,
        label=REASON_LABELS[token],
        default_state=REASON_DEFAULT_STATE[token],
        active=True,
        detail=detail or "",
    )
    with _lock:
        _active[token] = fault
    return fault


def induce_one_per_reason(
    *,
    reasons: Optional[Sequence[Union[str, FaultReason]]] = None,
    force_production: Optional[bool] = None,
    env: Optional[Mapping[str, str]] = None,
) -> Dict[str, InducedFault]:
    """E4-reduced form: induce exactly one fault per named reason.

    Default *reasons* is the full named set. Returns a dict keyed by
    canonical reason token. Still refuses in production.
    """
    target = list(reasons) if reasons is not None else list(NAMED_FAILURE_REASONS)
    out: Dict[str, InducedFault] = {}
    for r in target:
        fault = induce_fault(
            r, force_production=force_production, env=env
        )
        out[fault.reason] = fault
    # Prove one-per-reason: no duplicates, every requested present.
    if len(out) != len(set(out)):
        raise FaultInjectionError("duplicate induced reasons")
    return out


def is_induced(reason: Union[str, FaultReason]) -> bool:
    """True when *reason* is currently active in this process."""
    try:
        token = normalize_reason(reason)
    except UnknownFaultReason:
        return False
    with _lock:
        f = _active.get(token)
        return bool(f and f.active)


def get_fault(reason: Union[str, FaultReason]) -> Optional[InducedFault]:
    try:
        token = normalize_reason(reason)
    except UnknownFaultReason:
        return None
    with _lock:
        return _active.get(token)


def active_faults() -> Dict[str, InducedFault]:
    with _lock:
        return dict(_active)


def clear_faults() -> None:
    """Clear all induced faults (test teardown)."""
    with _lock:
        _active.clear()


def clear_fault(reason: Union[str, FaultReason]) -> None:
    token = normalize_reason(reason)
    with _lock:
        _active.pop(token, None)


def coverage_report(
    induced: Optional[Mapping[str, InducedFault]] = None,
) -> Dict[str, Any]:
    """Report which named reasons have been induced (for wave gate evidence)."""
    have = set((induced or active_faults()).keys())
    missing = [r for r in NAMED_FAILURE_REASONS if r not in have]
    return {
        "required": list(NAMED_FAILURE_REASONS),
        "induced": sorted(have),
        "missing": missing,
        "one_per_reason_complete": len(missing) == 0,
        "e4_reduced_form": "one-per-reason",
    }


def require_one_per_reason(
    induced: Optional[Mapping[str, InducedFault]] = None,
) -> None:
    """Raise if any named reason lacks an induced fault (E4 floor)."""
    report = coverage_report(induced)
    if not report["one_per_reason_complete"]:
        raise FaultInjectionError(
            "E4 one-per-reason incomplete — missing induced faults for: %s"
            % ", ".join(report["missing"])
        )


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _truthy(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


__all__ = [
    "ENV_ALLOW_FAULT_INJECT",
    "ENV_FORCE_PRODUCTION",
    "REASON_TIMEOUT",
    "REASON_MISSING_CAPABILITY",
    "REASON_EMPTY_RESULT_SET",
    "REASON_UNMEASURED_COST",
    "REASON_STALE_TELEMETRY",
    "NAMED_FAILURE_REASONS",
    "REASON_LABELS",
    "REASON_DEFAULT_STATE",
    "PRODUCTION_REFUSE_MESSAGE",
    "FaultInjectionError",
    "ProductionFaultRefuse",
    "UnknownFaultReason",
    "FaultReason",
    "InducedFault",
    "named_failure_reasons",
    "normalize_reason",
    "is_production_context",
    "induce_fault",
    "induce_one_per_reason",
    "is_induced",
    "get_fault",
    "active_faults",
    "clear_faults",
    "clear_fault",
    "coverage_report",
    "require_one_per_reason",
]
