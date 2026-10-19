"""Cost honesty primitives — W7 Phase 2.

Cost labelling derives from ``cost_state``, never from the numeric value.
``$0.00`` is never emitted as a fact outside ``cost_state == measured``.
``(subscription)`` is emitted only when ``cost_state == subscription_covered``.

The only sanctioned surface renderer is ``render_cost`` (``render_cost.py``).

Package-level names ``cost_state``, ``read_cost_state``, and ``render_cost``
are the **submodules** (so ``from anchor.cost import read_cost_state`` yields
the module). Callables of the same name live on those modules
(``anchor.cost.read_cost_state.read_cost_state``, etc.).
"""
from __future__ import annotations

# Submodules first — must not be shadowed by same-named callables below.
from . import cost_state
from . import read_cost_state
from . import render_cost

from .cost_state import (
    COST_STATE_COUNT,
    COST_STATE_TOKENS,
    SUBSCRIPTION_LABEL,
    CostState,
    coerce_cost_state,
)
from .read_cost_state import (
    COLUMN_ABSENT,
    COST_STATE_COLUMN,
    read_cost_state_from_schema,
)
from .render_cost import (
    DollarFabricationError,
    format_measured_dollars,
    render_cost_for_engine,
    render_cost_row,
)

__all__ = [
    "COLUMN_ABSENT",
    "COST_STATE_COLUMN",
    "COST_STATE_COUNT",
    "COST_STATE_TOKENS",
    "CostState",
    "DollarFabricationError",
    "SUBSCRIPTION_LABEL",
    "coerce_cost_state",
    "cost_state",
    "format_measured_dollars",
    "read_cost_state",
    "read_cost_state_from_schema",
    "render_cost",
    "render_cost_for_engine",
    "render_cost_row",
]
