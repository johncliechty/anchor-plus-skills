"""Named-state vocabulary + single render primitive — W6, Phase 2.

Ship the load-bearing primitive every surface wave renders through so no wave
hand-invents a label and no ambiguous zero can reach the screen.

**Binding definitions (canonical trichotomy — four words only):**

* **empty** — the read succeeded and there is legitimately no series and no
  scope: nothing was ever in scope (no sessions, no projects, no files).
* **zero_measured** — the aggregation ran successfully over a scope that
  exists, and the total is 0. A real, trustworthy zero.
* **unknown** — we did not successfully read. Query failed, store
  unreadable, probe errored, or the value was never fetched.
* **pending** — no aggregator exists yet. The code that would produce this
  value has not been built.

Extended NamedState members (ok, unmeasured, measurement_failed, timeout,
stale, cannot_*) are surface-native states that must map through
``STATE-VOCABULARY-MAP.md`` (W8). They never collapse into a fifth trichotomy
word.

``render_state`` is the single render primitive: every surface-bearing tile
emits a labelled visible text node for a NamedState, and raises on None/blank
input so an ambiguous empty cell cannot ship.

``FAILURE_STATE_TABLE`` / ``validate_failure_state_table`` enforce hardening
gates 0080/0081: **unknown** and **empty** are SEPARATE rows; merges such as
``unknown/empty`` or ``pending/zero_measured`` fail by name.
"""
from __future__ import annotations

import html
import re
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Union

# --------------------------------------------------------------------------
# Binding definitions — trichotomy wording (verbatim from IMPLEMENTATION-PLAN)
# --------------------------------------------------------------------------

#: Verbatim binding definition for **empty** (tests assert member docstring).
BINDING_EMPTY = (
    "the read succeeded and there is legitimately no series and no scope: "
    "nothing was ever in scope (no sessions, no projects, no files)."
)

#: Verbatim binding definition for **zero_measured**.
BINDING_ZERO_MEASURED = (
    "the aggregation ran successfully over a scope that exists, and the "
    "total is 0. A real, trustworthy zero."
)

#: Verbatim binding definition for **unknown**.
BINDING_UNKNOWN = (
    "we did not successfully read. Query failed, store unreadable, probe "
    "errored, or the value was never fetched."
)

#: Verbatim binding definition for **pending**.
BINDING_PENDING = (
    "no aggregator exists yet. The code that would produce this value has "
    "not been built."
)

# Extended-state definitions (plan-listed; not part of the four-word trichotomy).
_DEF_OK = (
    "read or aggregation succeeded with a usable non-empty result "
    "(PROVEN/nonzero or a healthy live control path)."
)
_DEF_UNMEASURED = (
    "measurement instrumentation is not present for this scope; no value "
    "was measured (never invent a zero or a dollar figure)."
)
_DEF_MEASUREMENT_FAILED = (
    "measurement ran but failed — disagreement with source rows, read "
    "error after instrumenting, or fail-closed partial migration."
)
_DEF_TIMEOUT = (
    "the operation exceeded its time bound; classified as timeout, never "
    "as unknown session or empty."
)
_DEF_STALE = (
    "a value exists but is outside the freshness bound (e.g. inventory "
    "row older than 14 days or hash-mismatched); fail closed."
)
_DEF_CANNOT_RETRY = (
    "retry is not viable; no re-issue action exists — render the named "
    "cannot-retry state and emit no dead Retry control."
)
_DEF_CANNOT_OPEN = (
    "the open control cannot run for a named reason (no such project, "
    "workspace locked, capability absent). Store unreadable is unknown "
    "(not cannot_open) — the open reason map must not collapse that pair."
)
_DEF_CANNOT_RUN = (
    "the run control cannot run for a named reason (no runnable target, "
    "engine unavailable, prior run in flight, capability absent)."
)
_DEF_CANNOT_RESTART = (
    "the restart control cannot run for a named reason in its restart "
    "context; emit no dead restart control."
)

# Forbidden ambiguous placeholders that must never appear as a "state".
_FORBIDDEN_PLACEHOLDERS = frozenset({"", "—", "-", "–", "0", "0.0", "n/a", "N/A"})

# Merge tokens that collapse distinct honesty states (hardening 0080/0081).
_MERGE_SEPARATORS = re.compile(r"[/|+,;&]+|\s+or\s+|\s+and\s+", re.IGNORECASE)

#: Pairs that must never share a single failure-table row.
FORBIDDEN_ROW_MERGES: frozenset = frozenset(
    {
        frozenset({"unknown", "empty"}),
        frozenset({"pending", "zero_measured"}),
        frozenset({"unknown", "zero_measured"}),
        frozenset({"empty", "zero_measured"}),
        frozenset({"pending", "unknown"}),
        frozenset({"pending", "empty"}),
    }
)

REQUIRED_SEPARATE_STATES: frozenset = frozenset({"unknown", "empty"})

NAMED_STATE_COUNT = 13


class NamedState(str, Enum):
    """Surface-native named states. Trichotomy members carry binding defs.

    Each member's ``.value`` is the canonical token; ``.label`` is the
    user-visible string; ``.__doc__`` holds the binding (or extended)
    definition so vocabulary cannot drift without a failing test.
    """

    ok = "ok"
    unknown = "unknown"
    empty = "empty"
    zero_measured = "zero_measured"
    pending = "pending"
    unmeasured = "unmeasured"
    measurement_failed = "measurement_failed"
    timeout = "timeout"
    stale = "stale"
    cannot_retry = "cannot_retry"
    cannot_open = "cannot_open"
    cannot_run = "cannot_run"
    cannot_restart = "cannot_restart"

    @property
    def label(self) -> str:
        """Distinct user-visible label (never blank, never a bare zero)."""
        return _USER_VISIBLE[self]

    @property
    def definition(self) -> str:
        """Binding / extended definition text for this state."""
        return _DEFINITIONS[self]


# Member docstrings — trichotomy members match BINDING_* verbatim.
NamedState.ok.__doc__ = _DEF_OK
NamedState.unknown.__doc__ = BINDING_UNKNOWN
NamedState.empty.__doc__ = BINDING_EMPTY
NamedState.zero_measured.__doc__ = BINDING_ZERO_MEASURED
NamedState.pending.__doc__ = BINDING_PENDING
NamedState.unmeasured.__doc__ = _DEF_UNMEASURED
NamedState.measurement_failed.__doc__ = _DEF_MEASUREMENT_FAILED
NamedState.timeout.__doc__ = _DEF_TIMEOUT
NamedState.stale.__doc__ = _DEF_STALE
NamedState.cannot_retry.__doc__ = _DEF_CANNOT_RETRY
NamedState.cannot_open.__doc__ = _DEF_CANNOT_OPEN
NamedState.cannot_run.__doc__ = _DEF_CANNOT_RUN
NamedState.cannot_restart.__doc__ = _DEF_CANNOT_RESTART

_DEFINITIONS: Dict[NamedState, str] = {
    NamedState.ok: _DEF_OK,
    NamedState.unknown: BINDING_UNKNOWN,
    NamedState.empty: BINDING_EMPTY,
    NamedState.zero_measured: BINDING_ZERO_MEASURED,
    NamedState.pending: BINDING_PENDING,
    NamedState.unmeasured: _DEF_UNMEASURED,
    NamedState.measurement_failed: _DEF_MEASUREMENT_FAILED,
    NamedState.timeout: _DEF_TIMEOUT,
    NamedState.stale: _DEF_STALE,
    NamedState.cannot_retry: _DEF_CANNOT_RETRY,
    NamedState.cannot_open: _DEF_CANNOT_OPEN,
    NamedState.cannot_run: _DEF_CANNOT_RUN,
    NamedState.cannot_restart: _DEF_CANNOT_RESTART,
}

# Distinct user-visible strings — each state is uniquely named on screen.
# Trichotomy labels are the canonical tokens so rendered HTML always carries
# the binding vocabulary word as a visible text node (never "0" / "—").
_USER_VISIBLE: Dict[NamedState, str] = {
    NamedState.ok: "ok",
    NamedState.unknown: "unknown",
    NamedState.empty: "empty",
    NamedState.zero_measured: "zero_measured",
    NamedState.pending: "pending",
    NamedState.unmeasured: "unmeasured",
    NamedState.measurement_failed: "measurement_failed",
    NamedState.timeout: "timeout",
    NamedState.stale: "stale",
    NamedState.cannot_retry: "cannot_retry",
    NamedState.cannot_open: "cannot_open",
    NamedState.cannot_run: "cannot_run",
    NamedState.cannot_restart: "cannot_restart",
}


class BlankStateError(ValueError):
    """Raised when render_state is given None or a blank input."""


class FailureStateTableError(ValueError):
    """Raised when a failure-state table violates the SEPARATE-rows schema."""


# --------------------------------------------------------------------------
# FAILURE_STATE_TABLE schema (hardening gates 0080 / 0081)
# --------------------------------------------------------------------------

#: Schema object every surface-bearing failure table is validated against.
#: Requires **unknown** and **empty** as SEPARATE rows; forbids merges that
#: collapse the honesty trichotomy.
FAILURE_STATE_TABLE: Dict[str, Any] = {
    "schema": "failure-state-table/v1",
    "hardening_gates": ("0080", "0081"),
    "required_separate_states": sorted(REQUIRED_SEPARATE_STATES),
    "forbidden_merges": [
        sorted(pair) for pair in sorted(FORBIDDEN_ROW_MERGES, key=lambda s: sorted(s)[0])
    ],
    "required_row_fields": ("state", "user_visible", "trigger"),
    "notes": (
        "unknown and empty are SEPARATE rows for any surface-bearing table; "
        "a combined 'unknown/empty' row fails naming the merged row."
    ),
}


def _normalize_state_token(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, NamedState):
        return raw.value
    text = str(raw).strip().lower().replace("-", "_").replace(" ", "_")
    return text


def _tokens_in_row_name(name: str) -> List[str]:
    """Split a row name on merge separators into candidate state tokens."""
    if not name:
        return []
    parts = _MERGE_SEPARATORS.split(name.strip().lower())
    out: List[str] = []
    for p in parts:
        tok = p.strip().replace("-", "_").replace(" ", "_")
        if tok:
            out.append(tok)
    return out


def validate_failure_state_table(
    table: Union[Sequence[Any], Mapping[str, Any]],
) -> None:
    """Validate a surface failure-state table against FAILURE_STATE_TABLE.

    Accepts either:

    * a sequence of row mappings (``state`` / ``name`` / ``id`` keys), or
    * a mapping with a ``rows`` sequence.

    Raises ``FailureStateTableError`` naming any merged row that collapses
    unknown+empty (or pending+zero_measured, etc.), satisfying hardening
    gates 0080/0081.
    """
    if isinstance(table, Mapping):
        rows = table.get("rows", table.get("states", table.get("table")))
        if rows is None and any(
            k in table for k in ("state", "name", "id", "row")
        ):
            rows = [table]
        if rows is None:
            raise FailureStateTableError(
                "failure-state table has no rows — required separate states "
                "unknown and empty are missing"
            )
    else:
        rows = table

    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise FailureStateTableError(
            "failure-state table rows must be a sequence of row objects"
        )

    seen: set = set()
    for idx, row in enumerate(rows):
        if isinstance(row, Mapping):
            raw_name = (
                row.get("state")
                or row.get("name")
                or row.get("id")
                or row.get("row")
                or row.get("code")
                or ""
            )
        else:
            raw_name = str(row)

        name = str(raw_name).strip()
        if not name:
            raise FailureStateTableError(
                "failure-state table row %d has a blank state name" % idx
            )

        # Detect slash-style merges in the raw name first (explicit GWT case).
        tokens = _tokens_in_row_name(name)
        # Also accept a single token when the row is well-formed.
        if len(tokens) == 0:
            tokens = [_normalize_state_token(name)]

        token_set = set(tokens)
        for forbidden in FORBIDDEN_ROW_MERGES:
            if forbidden.issubset(token_set) or (
                len(tokens) > 1 and forbidden == token_set
            ):
                raise FailureStateTableError(
                    "merged row %r collapses %s — unknown and empty must be "
                    "SEPARATE rows (hardening gates 0080/0081)"
                    % (name, " + ".join(sorted(forbidden)))
                )
            # Also catch "unknown/empty" as a single raw string without split
            # if separators failed for some unicode slash.
            joined = name.lower().replace(" ", "")
            a, b = sorted(forbidden)
            for sep in ("/", "|", "+", ",", "&", "-"):
                if a + sep + b in joined or b + sep + a in joined:
                    raise FailureStateTableError(
                        "merged row %r collapses %s — unknown and empty must "
                        "be SEPARATE rows (hardening gates 0080/0081)"
                        % (name, " + ".join(sorted(forbidden)))
                    )

        # Single-token rows contribute to coverage.
        if len(tokens) == 1:
            seen.add(tokens[0])
        else:
            # Multi-token row that wasn't a forbidden merge still fails:
            # each row must name exactly one state.
            raise FailureStateTableError(
                "merged row %r names multiple states %s — each row must name "
                "exactly one surface-native state"
                % (name, tokens)
            )

    missing = REQUIRED_SEPARATE_STATES - seen
    if missing:
        raise FailureStateTableError(
            "failure-state table missing required separate row(s): %s"
            % ", ".join(sorted(missing))
        )


# --------------------------------------------------------------------------
# render_state — the single render primitive
# --------------------------------------------------------------------------

def _coerce_state(state: Any) -> NamedState:
    if state is None:
        raise BlankStateError(
            "render_state refuses None — map an unread value to "
            "NamedState.unknown explicitly; never render a blank cell"
        )
    if isinstance(state, NamedState):
        return state
    if isinstance(state, str):
        text = state.strip()
        if not text:
            raise BlankStateError(
                "render_state refuses blank input — never render an empty cell"
            )
        if text in _FORBIDDEN_PLACEHOLDERS:
            raise BlankStateError(
                "render_state refuses placeholder %r — use a NamedState"
                % text
            )
        key = text.lower().replace("-", "_").replace(" ", "_")
        try:
            return NamedState(key)
        except ValueError as exc:
            raise BlankStateError(
                "render_state: unknown state token %r" % text
            ) from exc
    raise BlankStateError(
        "render_state expects NamedState or non-blank str, got %r"
        % type(state).__name__
    )


def render_state(state: Union[NamedState, str, None]) -> str:
    """Return a labelled visible HTML text node for ``state``.

    Raises ``BlankStateError`` on None or blank input so no surface can ship
    an ambiguous empty cell, bare ``0``, or ``—`` placeholder for a missing
    state.

    The returned node always carries:

    * ``class="named-state"``
    * ``data-named-state="<token>"``
    * visible text equal to the state's distinct user-visible label
    """
    ns = _coerce_state(state)
    label = ns.label
    if not label or not str(label).strip():
        raise BlankStateError(
            "NamedState %s has a blank user-visible label" % ns.value
        )
    if str(label).strip() in _FORBIDDEN_PLACEHOLDERS:
        raise BlankStateError(
            "NamedState %s label must not be a forbidden placeholder"
            % ns.value
        )
    token = html.escape(ns.value, quote=True)
    visible = html.escape(label, quote=False)
    return (
        '<span class="named-state" data-named-state="%s" data-state="%s">'
        "%s</span>" % (token, token, visible)
    )


def generate_html(
    states: Optional[Sequence[Union[NamedState, str]]] = None,
    *,
    title: str = "named-state surface",
) -> str:
    """Minimal HTML document embedding ``render_state`` output for each state.

    Used by wave tests to assert on real rendered output (visible text nodes)
    and to extract ``<script>`` blocks for ``node --check``. Paths inside the
    document are relative; no absolute host paths are emitted.
    """
    if states is None:
        states = list(NamedState)

    tiles: List[str] = []
    for s in states:
        ns = _coerce_state(s)
        tiles.append(
            '<div class="tile" data-tile-state="%s">%s</div>'
            % (html.escape(ns.value, quote=True), render_state(ns))
        )

    # Syntax-valid JS block (node --check); no shell, no absolute paths.
    script = (
        "(function () {\n"
        "  var nodes = document.querySelectorAll('[data-named-state]');\n"
        "  if (!nodes) { return; }\n"
        "  for (var i = 0; i < nodes.length; i++) {\n"
        "    var el = nodes[i];\n"
        "    if (!el || !el.getAttribute('data-named-state')) { continue; }\n"
        "  }\n"
        "})();\n"
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
        '  <main class="named-state-surface" data-surface="named-state">\n'
        "%s\n"
        "  </main>\n"
        "  <script>\n"
        "%s"
        "  </script>\n"
        "</body>\n"
        "</html>\n"
        % (html.escape(title, quote=False), body, script)
    )


def all_labels() -> Dict[str, str]:
    """Map every NamedState token → its user-visible label."""
    return {s.value: s.label for s in NamedState}


def trichotomy_docstrings() -> Dict[str, str]:
    """Return the four trichotomy members' docstrings (binding definitions)."""
    return {
        "empty": NamedState.empty.__doc__ or "",
        "zero_measured": NamedState.zero_measured.__doc__ or "",
        "unknown": NamedState.unknown.__doc__ or "",
        "pending": NamedState.pending.__doc__ or "",
    }


__all__ = [
    "BINDING_EMPTY",
    "BINDING_PENDING",
    "BINDING_UNKNOWN",
    "BINDING_ZERO_MEASURED",
    "BlankStateError",
    "FAILURE_STATE_TABLE",
    "FORBIDDEN_ROW_MERGES",
    "FailureStateTableError",
    "NAMED_STATE_COUNT",
    "NamedState",
    "REQUIRED_SEPARATE_STATES",
    "all_labels",
    "generate_html",
    "render_state",
    "trichotomy_docstrings",
    "validate_failure_state_table",
]
