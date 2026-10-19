"""Fail-closed cost_state reader — W7 Phase 2.

A row whose ``cost_state`` column is **absent**, **NULL**, or **unreadable**
— mid-deploy, failed migration, rolled-back migration, or a replica that has
not caught up — resolves to ``measurement_failed``.

It never resolves to ``measured`` and never to ``subscription_covered`` under
those partial-migration conditions. The surface then renders the labelled
``measurement_failed`` state with no dollar figure and no ``(subscription)``.

After a successful migration, existing rows are backfilled to ``unmeasured``
(see ``migrations/*_add_cost_state.sql``). That is distinct from the fail-closed
path: successful backfill → unmeasured; incomplete/NULL → measurement_failed.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Union

from anchor.cost.cost_state import (
    CostState,
    InvalidCostState,
    coerce_cost_state,
)

#: Canonical column name on session / cost event rows.
COST_STATE_COLUMN = "cost_state"

#: Sentinel: schema does not yet carry the cost_state column (mid-deploy).
COLUMN_ABSENT = object()


def read_cost_state(
    row: Optional[Mapping[str, Any]],
    *,
    column: str = COST_STATE_COLUMN,
) -> CostState:
    """Resolve cost_state from a row mapping, fail-closed.

    * ``row is None`` → ``measurement_failed``
    * column key absent → ``measurement_failed`` (mid-deploy / no column)
    * value is ``None`` → ``measurement_failed`` (NULL / partial backfill)
    * value unreadable / unknown token → ``measurement_failed``
    * known token → that CostState

    Never invents ``measured`` or ``subscription_covered`` from a missing or
    NULL column. Callers must not treat a bare numeric zero as subscription.
    """
    if row is None:
        return CostState.measurement_failed

    if not isinstance(row, Mapping):
        return CostState.measurement_failed

    if column not in row:
        return CostState.measurement_failed

    raw = row[column]
    if raw is None:
        return CostState.measurement_failed

    # Empty / whitespace-only string is unreadable.
    if isinstance(raw, str) and not raw.strip():
        return CostState.measurement_failed

    try:
        return coerce_cost_state(raw)
    except InvalidCostState:
        return CostState.measurement_failed
    except Exception:
        # Any unexpected decode failure fails closed.
        return CostState.measurement_failed


def read_cost_state_from_schema(
    raw: Any = COLUMN_ABSENT,
    *,
    column_present: Optional[bool] = None,
) -> CostState:
    """Resolve cost_state when the caller knows schema presence explicitly.

    Parameters
    ----------
    raw:
        The column value, or ``COLUMN_ABSENT`` when the column does not exist
        on the row/schema (mid-deploy database).
    column_present:
        If False, always ``measurement_failed`` regardless of ``raw``.
        If True, treat ``raw`` as the column value (NULL → measurement_failed).
        If None, infer: ``COLUMN_ABSENT`` means absent; otherwise present.
    """
    if column_present is False:
        return CostState.measurement_failed

    if column_present is None:
        if raw is COLUMN_ABSENT:
            return CostState.measurement_failed
    else:
        # column_present is True
        if raw is COLUMN_ABSENT:
            # Explicit present + ABSENT sentinel is inconsistent → fail closed.
            return CostState.measurement_failed

    if raw is COLUMN_ABSENT:
        return CostState.measurement_failed

    if raw is None:
        return CostState.measurement_failed

    if isinstance(raw, str) and not raw.strip():
        return CostState.measurement_failed

    try:
        return coerce_cost_state(raw)
    except InvalidCostState:
        return CostState.measurement_failed
    except Exception:
        return CostState.measurement_failed


def cost_state_for_spot_check_engine(
    engine: str,
    failed_engines: Optional[Union[set, frozenset, list, tuple]] = None,
) -> CostState:
    """If the W4 spot-check recorded a wrong figure for ``engine``, fail closed.

    Returns ``measurement_failed`` when ``engine`` is in the measurement-failed
    set; otherwise does **not** invent a state (returns ``unmeasured`` as the
    honest default when no positive classification is supplied). Callers that
    already hold a stored cost_state should prefer that over this default.
    """
    failed = set(failed_engines or ())
    if engine in failed:
        return CostState.measurement_failed
    return CostState.unmeasured


__all__ = [
    "COLUMN_ABSENT",
    "COST_STATE_COLUMN",
    "cost_state_for_spot_check_engine",
    "read_cost_state",
    "read_cost_state_from_schema",
]
