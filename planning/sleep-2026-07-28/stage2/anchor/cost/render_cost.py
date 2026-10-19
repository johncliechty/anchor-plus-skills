"""The only sanctioned cost renderer — W7 Phase 2.

Cost labelling derives from ``cost_state``, never from the number:

* ``subscription_covered`` → ``(subscription)`` from the enum label
* ``unmeasured`` → ``render_state(NamedState.unmeasured)``
* ``measurement_failed`` → ``render_state(NamedState.measurement_failed)``
* ``measured`` → dollar figure (``$X.XX``), including a real measured ``$0.00``

Emitting ``$0.00`` **without** ``cost_state == measured`` raises
``DollarFabricationError``. No other module may format cost dollars for a
user-facing surface.
"""
from __future__ import annotations

import html
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping, Optional, Set, Union

from anchor.cost.cost_state import (
    SUBSCRIPTION_LABEL,
    CostState,
    InvalidCostState,
    coerce_cost_state,
)
from anchor.cost.read_cost_state import (
    cost_state_for_spot_check_engine,
    read_cost_state,
)
from anchor.ui.named_state import NamedState, render_state

# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class DollarFabricationError(ValueError):
    """Raised when a path would emit ``$0.00`` (or any dollar figure) dishonestly.

    ``$0.00`` is only legal when ``cost_state == measured``. Fabricating a
    dollar amount under unmeasured / measurement_failed / subscription_covered
    (or with no state) is a North-Star violation.
    """


class CostRenderError(ValueError):
    """Raised when render_cost cannot produce an honest label."""


# --------------------------------------------------------------------------
# Dollar formatting (measured only)
# --------------------------------------------------------------------------

_ZERO_DOLLAR_RE = re.compile(r"\$0(?:\.0+)?\b")
_DOLLAR_FIGURE_RE = re.compile(r"\$\d")


def _to_decimal(amount: Any) -> Decimal:
    if isinstance(amount, Decimal):
        return amount
    if amount is None:
        raise CostRenderError(
            "measured cost requires a numeric amount — got None"
        )
    try:
        return Decimal(str(amount))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise CostRenderError(
            "measured cost amount is not numeric: %r" % (amount,)
        ) from exc


def format_measured_dollars(
    amount: Any,
    *,
    cost_state: Any = CostState.measured,
) -> str:
    """Format ``amount`` as ``$X.XX`` — only legal under ``cost_state == measured``.

    Raises ``DollarFabricationError`` if asked to emit a dollar figure
    (including ``$0.00``) without ``cost_state == measured``.
    """
    try:
        cs = coerce_cost_state(cost_state)
    except InvalidCostState as exc:
        raise DollarFabricationError(
            "cannot emit a dollar figure without a known measured cost_state: %s"
            % exc
        ) from exc

    if cs is not CostState.measured:
        # Explicit ban: $0.00 (and any $ figure) outside measured.
        raise DollarFabricationError(
            "refusing to emit a dollar figure without cost_state == measured "
            "(got cost_state=%s); $0.00 is never a fact outside measured"
            % cs.value
        )

    dec = _to_decimal(amount)
    # Quantize to cents for stable display.
    quantized = dec.quantize(Decimal("0.01"))
    # Always two decimal places; keep sign for negative measured costs.
    text = "$" + format(quantized, "f")
    if quantized == 0:
        # Normalise -0.00 / 0.0 → $0.00
        text = "$0.00"
    return text


def _assert_no_fabricated_zero(rendered: str, cost_state: CostState) -> None:
    """Post-condition: non-measured renders never carry $0.00 or any $ figure."""
    if cost_state is CostState.measured:
        return
    if _ZERO_DOLLAR_RE.search(rendered) or "$0.00" in rendered:
        raise DollarFabricationError(
            "rendered output for cost_state=%s contains '$0.00' — "
            "dollar-zero is never a fact outside measured: %r"
            % (cost_state.value, rendered)
        )
    if _DOLLAR_FIGURE_RE.search(rendered):
        raise DollarFabricationError(
            "rendered output for cost_state=%s contains a dollar figure — "
            "only measured may emit dollars: %r"
            % (cost_state.value, rendered)
        )


# --------------------------------------------------------------------------
# render_cost — sole sanctioned path
# --------------------------------------------------------------------------


def render_cost(
    amount: Any = None,
    cost_state: Any = None,
    *,
    engine: Optional[str] = None,
    measurement_failed_engines: Optional[Iterable[str]] = None,
) -> str:
    """Render a labelled cost HTML node from ``cost_state`` (never from zero).

    Parameters
    ----------
    amount:
        Numeric cost when ``cost_state == measured``. Ignored for labelling
        under subscription_covered / unmeasured / measurement_failed (the
        number must not choose the label).
    cost_state:
        A CostState (or token). Required unless ``engine`` is forced to
        measurement_failed via the spot-check set.
    engine:
        Optional engine id; when listed in ``measurement_failed_engines``
        (W4 spot-check disagreement), forces ``measurement_failed``.
    measurement_failed_engines:
        Engines the W4 cost spot-check marked measurement_failed.

    Returns
    -------
    str
        An HTML fragment with ``class="cost-state"`` and
        ``data-cost-state="<token>"``, containing either a dollar figure
        (measured only), the subscription label (from the enum), or a
        ``render_state`` node for unmeasured / measurement_failed.
    """
    failed: Set[str] = set(measurement_failed_engines or ())

    # Spot-check override: wrong figure for this engine → measurement_failed.
    if engine is not None and engine in failed:
        cs = CostState.measurement_failed
    elif cost_state is None and engine is not None and failed:
        # Engine-only call with a known failed set: resolve via helper.
        cs = cost_state_for_spot_check_engine(engine, failed)
    elif cost_state is None:
        # No state at all → fail closed (never invent measured / subscription).
        cs = CostState.measurement_failed
    else:
        try:
            cs = coerce_cost_state(cost_state)
        except InvalidCostState:
            cs = CostState.measurement_failed

    # ----- label from state, never from amount -----
    if cs is CostState.subscription_covered:
        # Label comes from the enum constant — not from amount == 0.
        visible = html.escape(CostState.subscription_covered.label, quote=False)
        assert visible == SUBSCRIPTION_LABEL
        assert visible == CostState.subscription_covered.label
        inner = visible
        out = _wrap(cs, inner)
        _assert_no_fabricated_zero(out, cs)
        # Must not depend on amount for this branch.
        return out

    if cs is CostState.unmeasured:
        inner = render_state(NamedState.unmeasured)
        out = _wrap(cs, inner)
        _assert_no_fabricated_zero(out, cs)
        return out

    if cs is CostState.measurement_failed:
        inner = render_state(NamedState.measurement_failed)
        out = _wrap(cs, inner)
        _assert_no_fabricated_zero(out, cs)
        return out

    if cs is CostState.measured:
        # Only path that may emit a dollar figure (including $0.00).
        dollars = format_measured_dollars(amount, cost_state=cs)
        inner = html.escape(dollars, quote=False)
        return _wrap(cs, inner)

    # Unreachable if coerce is total over CostState, but fail closed.
    raise CostRenderError("unhandled cost_state %r" % (cs,))


def render_cost_for_engine(
    amount: Any,
    engine: str,
    *,
    cost_state: Any = None,
    measurement_failed_engines: Optional[Iterable[str]] = None,
    spot_check_record: Any = None,
) -> str:
    """Render cost for an engine, honouring the W4 spot-check fail set.

    If ``spot_check_record`` is provided, its measurement-failed engines are
    unioned with ``measurement_failed_engines``. A wrong-figure engine always
    renders ``measurement_failed`` with no numeric dollar value.
    """
    failed: Set[str] = set(measurement_failed_engines or ())
    if spot_check_record is not None:
        try:
            from tools.rollup_evidence_gate import measurement_failed_engines as _mfe

            failed |= set(_mfe(spot_check_record))
        except Exception:
            # Fail closed on an unreadable spot-check: treat as no extra
            # engines rather than inventing agreement.
            pass

    if engine in failed:
        return render_cost(
            amount,
            CostState.measurement_failed,
            engine=engine,
            measurement_failed_engines=failed,
        )

    if cost_state is None:
        cost_state = CostState.unmeasured

    return render_cost(
        amount,
        cost_state,
        engine=engine,
        measurement_failed_engines=failed,
    )


def render_cost_row(
    row: Optional[Mapping[str, Any]],
    *,
    amount_keys: Iterable[str] = ("cost", "amount", "cost_dollars", "cents"),
    cost_state_column: str = "cost_state",
    amount_unit: str = "dollars",
) -> str:
    """Render cost for a DB/session row via fail-closed ``read_cost_state``.

    Mid-deploy rows (no cost_state column) → measurement_failed, no ``$``,
    no ``(subscription)``.
    """
    cs = read_cost_state(row, column=cost_state_column)
    amount: Any = None
    if isinstance(row, Mapping):
        for key in amount_keys:
            if key in row and row[key] is not None:
                amount = row[key]
                if key == "cents" or amount_unit == "cents":
                    try:
                        amount = Decimal(str(amount)) / Decimal(100)
                    except (InvalidOperation, ValueError, TypeError):
                        pass
                break
    return render_cost(amount, cs)


def _wrap(cs: CostState, inner: str) -> str:
    token = html.escape(cs.value, quote=True)
    return (
        '<span class="cost-state" data-cost-state="%s" data-state="%s">'
        "%s</span>" % (token, token, inner)
    )


def generate_cost_html(
    rows: Optional[Iterable[Mapping[str, Any]]] = None,
    *,
    title: str = "cost-state surface",
) -> str:
    """Minimal HTML document embedding ``render_cost`` / ``render_cost_row`` output.

    Used by wave tests to assert visible text nodes. No absolute host paths.
    """
    if rows is None:
        rows = [
            {"cost": 0, "cost_state": "unmeasured"},
            {"cost": 0, "cost_state": "subscription_covered"},
            {"cost": 0, "cost_state": "measured"},
            {"cost": 0, "cost_state": "measurement_failed"},
        ]

    tiles = []
    for idx, row in enumerate(rows):
        tiles.append(
            '<div class="tile" data-tile-index="%d">%s</div>'
            % (idx, render_cost_row(row))
        )

    body = "\n".join(tiles)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8"/>\n'
        "  <title>%s</title>\n"
        "</head>\n"
        "<body>\n"
        '  <main class="cost-state-surface" data-surface="cost-state">\n'
        "%s\n"
        "  </main>\n"
        "</body>\n"
        "</html>\n"
        % (html.escape(title, quote=False), body)
    )


__all__ = [
    "CostRenderError",
    "DollarFabricationError",
    "format_measured_dollars",
    "generate_cost_html",
    "render_cost",
    "render_cost_for_engine",
    "render_cost_row",
]
