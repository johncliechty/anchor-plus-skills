"""CostState enum — W7 Phase 2.

Cost labelling derives from **state**, never from the numeric value:

* ``subscription_covered`` → user-visible ``(subscription)`` (from this enum,
  never from ``cost == 0``)
* ``measured`` → a dollar figure is allowed, including a measured ``$0.00``
* ``unmeasured`` → labelled unmeasured (never blank, never ``$0.00``, never
  ``(subscription)``)
* ``measurement_failed`` → labelled measurement_failed (no dollar figure)

Existing rows after migration backfill to ``unmeasured`` — never to a
fabricated measured-zero. Partial-migration / NULL / absent column fail closed
to ``measurement_failed`` (see ``read_cost_state``).
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, FrozenSet

#: Canonical user-visible label for subscription-covered cost.
#: Always taken from CostState.subscription_covered — never inferred from 0.
SUBSCRIPTION_LABEL = "(subscription)"

COST_STATE_COUNT = 4

COST_STATE_TOKENS: FrozenSet[str] = frozenset(
    {
        "subscription_covered",
        "measured",
        "unmeasured",
        "measurement_failed",
    }
)

_DEF_SUBSCRIPTION_COVERED = (
    "usage is covered by a subscription plan; the surface shows "
    "'(subscription)' because cost_state is subscription_covered — never "
    "because the numeric cost is zero."
)
_DEF_MEASURED = (
    "cost was measured successfully; a dollar figure (including a real "
    "measured $0.00) may be rendered only in this state."
)
_DEF_UNMEASURED = (
    "measurement instrumentation is not present for this scope; no value "
    "was measured — never invent a zero or a dollar figure."
)
_DEF_MEASUREMENT_FAILED = (
    "measurement ran but failed — disagreement with source rows, read "
    "error, or fail-closed partial migration; never render a dollar figure."
)


class CostState(str, Enum):
    """Stored and in-memory cost classification (four tokens only)."""

    subscription_covered = "subscription_covered"
    measured = "measured"
    unmeasured = "unmeasured"
    measurement_failed = "measurement_failed"

    @property
    def label(self) -> str:
        """User-visible token/label for this cost state (not a dollar figure)."""
        return _USER_VISIBLE[self]

    @property
    def definition(self) -> str:
        return _DEFINITIONS[self]

    @property
    def allows_dollar_figure(self) -> bool:
        """Only ``measured`` may render a numeric dollar amount."""
        return self is CostState.measured

    @property
    def is_subscription(self) -> bool:
        return self is CostState.subscription_covered


CostState.subscription_covered.__doc__ = _DEF_SUBSCRIPTION_COVERED
CostState.measured.__doc__ = _DEF_MEASURED
CostState.unmeasured.__doc__ = _DEF_UNMEASURED
CostState.measurement_failed.__doc__ = _DEF_MEASUREMENT_FAILED

_DEFINITIONS: Dict[CostState, str] = {
    CostState.subscription_covered: _DEF_SUBSCRIPTION_COVERED,
    CostState.measured: _DEF_MEASURED,
    CostState.unmeasured: _DEF_UNMEASURED,
    CostState.measurement_failed: _DEF_MEASUREMENT_FAILED,
}

# subscription_covered's user-visible string is the subscription label;
# other states use their token (render_cost maps unmeasured/failed through
# NamedState.render_state for the surface vocabulary).
_USER_VISIBLE: Dict[CostState, str] = {
    CostState.subscription_covered: SUBSCRIPTION_LABEL,
    CostState.measured: "measured",
    CostState.unmeasured: "unmeasured",
    CostState.measurement_failed: "measurement_failed",
}


class InvalidCostState(ValueError):
    """Raised when a value cannot be coerced to a known CostState token."""


def coerce_cost_state(value: Any) -> CostState:
    """Coerce ``value`` to a CostState; raise InvalidCostState if unreadable.

    Accepts CostState members and case-insensitive token strings. Does **not**
    fail closed — callers that need fail-closed partial-migration behaviour
    must use ``read_cost_state`` instead.
    """
    if isinstance(value, CostState):
        return value
    if value is None:
        raise InvalidCostState(
            "cost_state is None — use read_cost_state for fail-closed"
        )
    if isinstance(value, str):
        text = value.strip().lower().replace("-", "_").replace(" ", "_")
        if not text:
            raise InvalidCostState("cost_state is blank")
        try:
            return CostState(text)
        except ValueError as exc:
            raise InvalidCostState(
                "unknown cost_state token %r — expected one of %s"
                % (value, sorted(COST_STATE_TOKENS))
            ) from exc
    raise InvalidCostState(
        "cost_state must be CostState or str, got %r" % type(value).__name__
    )


def all_tokens() -> Dict[str, str]:
    """Map every CostState token → its user-visible label."""
    return {s.value: s.label for s in CostState}


__all__ = [
    "COST_STATE_COUNT",
    "COST_STATE_TOKENS",
    "CostState",
    "InvalidCostState",
    "SUBSCRIPTION_LABEL",
    "all_tokens",
    "coerce_cost_state",
]
