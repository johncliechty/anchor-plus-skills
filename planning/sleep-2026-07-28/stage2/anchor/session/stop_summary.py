"""Stop-summary inventory collector — W16, Phase 3.

Collects **in-flight work at stop time** from the inventory source named in
``artifacts/CAPABILITY-INVENTORY.md`` (control id ``stop_summary``). Returns
structured items with counts so the stop tile is inventory-backed, never a
placeholder.

Honesty (North Star — unknown ≠ empty):

* **empty** — inventory read succeeded and nothing was in flight
* **unknown** — in-flight inventory could not be read (never looks empty)
* **ok** — inventory read succeeded with one or more in-flight items + counts
* **zero_measured** — aggregation over an existing scope measured total 0

Induced faults (frozen plan gate): inventory unreadable, zero items, partial
items. Partial items still surface with their recoverable counts; they never
collapse into unknown or empty.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

from anchor.ui.named_state import NamedState

# --------------------------------------------------------------------------
# Public constants — inventory source bound to CAPABILITY-INVENTORY.md
# --------------------------------------------------------------------------

WAVE_ID = "W16"
SURFACE_ID = "stop-summary"

#: Control id + label as recorded in CAPABILITY-INVENTORY.md (W3).
CAPABILITY_CONTROL_ID = "stop_summary"
INVENTORY_SOURCE_LABEL = "stop-summary inventory source"
INVENTORY_SOURCE_NAME = CAPABILITY_CONTROL_ID

#: Query id stamped on every successful inventory query (traceable counts).
DEFAULT_QUERY_ID = "stop_summary.in_flight"


class StopSummaryReason(str, Enum):
    """Enumerated stop-summary outcomes / induced-fault reasons."""

    OK = "ok"
    INVENTORY_UNREADABLE = "inventory_unreadable"
    ZERO_ITEMS = "zero_items"
    PARTIAL_ITEMS = "partial_items"
    ZERO_MEASURED = "zero_measured"
    CAPABILITY_ABSENT = "capability_absent"


STOP_SUMMARY_REASONS: Tuple[str, ...] = tuple(r.value for r in StopSummaryReason)

#: Induced faults the W16 gate must exercise (plan deliverables).
INDUCED_FAULT_INVENTORY_UNREADABLE = StopSummaryReason.INVENTORY_UNREADABLE.value
INDUCED_FAULT_ZERO_ITEMS = StopSummaryReason.ZERO_ITEMS.value
INDUCED_FAULT_PARTIAL_ITEMS = StopSummaryReason.PARTIAL_ITEMS.value

INDUCED_FAULT_REASONS: Tuple[str, ...] = (
    INDUCED_FAULT_INVENTORY_UNREADABLE,
    INDUCED_FAULT_ZERO_ITEMS,
    INDUCED_FAULT_PARTIAL_ITEMS,
)

REASON_LABELS: Dict[str, str] = {
    StopSummaryReason.OK.value: "in-flight work summarized",
    StopSummaryReason.INVENTORY_UNREADABLE.value: "in-flight inventory unreadable",
    StopSummaryReason.ZERO_ITEMS.value: "nothing was in flight",
    StopSummaryReason.PARTIAL_ITEMS.value: "partial in-flight items recovered",
    StopSummaryReason.ZERO_MEASURED.value: "in-flight total measured zero",
    StopSummaryReason.CAPABILITY_ABSENT.value: "stop-summary inventory source absent",
}

REASON_STATE: Dict[str, NamedState] = {
    StopSummaryReason.OK.value: NamedState.ok,
    # Unreadable inventory → unknown (NEVER empty).
    StopSummaryReason.INVENTORY_UNREADABLE.value: NamedState.unknown,
    # Successful read, zero items → empty (NEVER unknown).
    StopSummaryReason.ZERO_ITEMS.value: NamedState.empty,
    # Partial recovery still a successful read of what was available → ok.
    StopSummaryReason.PARTIAL_ITEMS.value: NamedState.ok,
    StopSummaryReason.ZERO_MEASURED.value: NamedState.zero_measured,
    StopSummaryReason.CAPABILITY_ABSENT.value: NamedState.unknown,
}


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class InventoryUnreadableError(Exception):
    """Raised when the in-flight inventory source cannot be read."""

    def __init__(self, message: str = "in-flight inventory unreadable"):
        super().__init__(message)
        self.message = message


class StopSummaryError(Exception):
    """Base error for stop-summary collection."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


# --------------------------------------------------------------------------
# Structured items
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class InFlightItem:
    """One in-flight work unit collected from the inventory source.

    ``count`` is the inventory-query count for this item; ``query_ref`` ties
    the visible count back to the inventory query (traceability GWT).
    """

    item_id: str
    label: str
    count: int
    partial: bool = False
    query_ref: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "item_id": self.item_id,
            "label": self.label,
            "count": int(self.count),
            "partial": bool(self.partial),
            "query_ref": self.query_ref or "",
            "meta": dict(self.meta),
        }

    @property
    def visible_label(self) -> str:
        """User-visible item line: label + count (asserted as text nodes)."""
        return "%s ×%d" % (self.label, int(self.count))


@dataclass(frozen=True)
class StopSummaryResult:
    """Structured stop-summary result for the tile renderer.

    ``items`` carries counts traceable to the inventory query via
    ``query_id`` / per-item ``query_ref``. ``named_state`` is the honesty
    state the tile must render through ``render_state``.
    """

    session_id: str
    named_state: NamedState
    items: Tuple[InFlightItem, ...]
    total_count: int
    inventory_source: str = INVENTORY_SOURCE_NAME
    inventory_source_label: str = INVENTORY_SOURCE_LABEL
    query_id: str = DEFAULT_QUERY_ID
    reason: str = ""
    detail: str = ""
    partial: bool = False

    @property
    def ok(self) -> bool:
        return self.named_state is NamedState.ok

    @property
    def item_count(self) -> int:
        return len(self.items)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "session_id": self.session_id,
            "named_state": self.named_state.value,
            "items": [i.as_dict() for i in self.items],
            "total_count": int(self.total_count),
            "item_count": self.item_count,
            "inventory_source": self.inventory_source,
            "inventory_source_label": self.inventory_source_label,
            "query_id": self.query_id,
            "reason": self.reason,
            "detail": self.detail,
            "partial": bool(self.partial),
        }


# --------------------------------------------------------------------------
# Injectable inventory source (named by CAPABILITY-INVENTORY stop_summary)
# --------------------------------------------------------------------------


class InFlightInventory:
    """Injectable in-flight inventory source for stop-time collection.

    Bound to the CAPABILITY-INVENTORY control ``stop_summary``. Production
    callers inject a live source; tests inject fixtures for the three
    induced faults and the three-item GWT.
    """

    source_name: str = INVENTORY_SOURCE_NAME
    source_label: str = INVENTORY_SOURCE_LABEL
    query_id: str = DEFAULT_QUERY_ID

    def __init__(
        self,
        items: Optional[Sequence[Union[InFlightItem, Mapping[str, Any]]]] = None,
        *,
        unreadable: bool = False,
        session_id: str = "",
        query_id: Optional[str] = None,
    ) -> None:
        self._unreadable = bool(unreadable)
        self._session_id = str(session_id or "")
        self.query_id = str(query_id or DEFAULT_QUERY_ID)
        self._items: List[InFlightItem] = [
            _as_item(i, query_id=self.query_id) for i in (items or ())
        ]

    def list_in_flight(self, session_id: str = "") -> List[InFlightItem]:
        """Return in-flight items for ``session_id`` or raise if unreadable."""
        if self._unreadable:
            raise InventoryUnreadableError(
                "in-flight inventory unreadable for session %r"
                % (session_id or self._session_id or "")
            )
        return list(self._items)

    def query_receipt(self) -> Dict[str, Any]:
        """Receipt that ties rendered counts to this inventory query."""
        return {
            "inventory_source": self.source_name,
            "inventory_source_label": self.source_label,
            "query_id": self.query_id,
            "capability_control": CAPABILITY_CONTROL_ID,
            "unreadable": self._unreadable,
            "item_count": 0 if self._unreadable else len(self._items),
        }


def empty_inventory(session_id: str = "") -> InFlightInventory:
    """Legitimately empty in-flight inventory (empty, not unknown)."""
    return InFlightInventory(items=[], session_id=session_id)


def unreadable_inventory(session_id: str = "") -> InFlightInventory:
    """Inventory that fails every read (unknown, not empty)."""
    return InFlightInventory(items=[], unreadable=True, session_id=session_id)


def three_item_inventory(session_id: str = "sess-stop") -> InFlightInventory:
    """Fixture: three in-flight items with counts (primary GWT)."""
    q = DEFAULT_QUERY_ID
    return InFlightInventory(
        items=[
            InFlightItem(
                item_id="job-1",
                label="research job",
                count=2,
                query_ref="%s#job-1" % q,
            ),
            InFlightItem(
                item_id="job-2",
                label="plan draft",
                count=1,
                query_ref="%s#job-2" % q,
            ),
            InFlightItem(
                item_id="job-3",
                label="build wave",
                count=3,
                query_ref="%s#job-3" % q,
            ),
        ],
        session_id=session_id,
        query_id=q,
    )


def partial_item_inventory(session_id: str = "sess-stop") -> InFlightInventory:
    """Fixture: some items only partially recovered (still listed + counted)."""
    q = DEFAULT_QUERY_ID
    return InFlightInventory(
        items=[
            InFlightItem(
                item_id="job-1",
                label="research job",
                count=2,
                partial=False,
                query_ref="%s#job-1" % q,
            ),
            InFlightItem(
                item_id="job-partial",
                label="partial work unit",
                count=1,
                partial=True,
                query_ref="%s#job-partial" % q,
                meta={"recovery": "partial"},
            ),
        ],
        session_id=session_id,
        query_id=q,
    )


def zero_measured_inventory(session_id: str = "sess-stop") -> InFlightInventory:
    """Scope exists; measured total in-flight count is 0 (zero_measured)."""
    q = DEFAULT_QUERY_ID
    return InFlightInventory(
        items=[
            InFlightItem(
                item_id="slot-a",
                label="engine slot A",
                count=0,
                query_ref="%s#slot-a" % q,
            ),
            InFlightItem(
                item_id="slot-b",
                label="engine slot B",
                count=0,
                query_ref="%s#slot-b" % q,
            ),
        ],
        session_id=session_id,
        query_id=q,
    )


# --------------------------------------------------------------------------
# collect_stop_summary
# --------------------------------------------------------------------------


def normalize_stop_reason(reason: Union[str, StopSummaryReason]) -> str:
    if isinstance(reason, StopSummaryReason):
        return reason.value
    raw = str(reason).strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "ok": StopSummaryReason.OK.value,
        "success": StopSummaryReason.OK.value,
        "inventory_unreadable": StopSummaryReason.INVENTORY_UNREADABLE.value,
        "unreadable": StopSummaryReason.INVENTORY_UNREADABLE.value,
        "backing_store_unreadable": StopSummaryReason.INVENTORY_UNREADABLE.value,
        "read_failed": StopSummaryReason.INVENTORY_UNREADABLE.value,
        "zero_items": StopSummaryReason.ZERO_ITEMS.value,
        "empty": StopSummaryReason.ZERO_ITEMS.value,
        "nothing_in_flight": StopSummaryReason.ZERO_ITEMS.value,
        "partial_items": StopSummaryReason.PARTIAL_ITEMS.value,
        "partial": StopSummaryReason.PARTIAL_ITEMS.value,
        "zero_measured": StopSummaryReason.ZERO_MEASURED.value,
        "measured_zero": StopSummaryReason.ZERO_MEASURED.value,
        "capability_absent": StopSummaryReason.CAPABILITY_ABSENT.value,
        "missing_capability": StopSummaryReason.CAPABILITY_ABSENT.value,
    }
    if raw not in aliases:
        raise ValueError(
            "unknown stop-summary reason %r — must be one of %s"
            % (reason, list(STOP_SUMMARY_REASONS))
        )
    return aliases[raw]


def stop_reason_named_state(reason: Union[str, StopSummaryReason]) -> NamedState:
    token = normalize_stop_reason(reason)
    return REASON_STATE[token]


def collect_stop_summary(
    session_id: str = "",
    *,
    inventory: Optional[InFlightInventory] = None,
    force_fault: Optional[Union[str, StopSummaryReason]] = None,
    capability_present: Optional[bool] = None,
) -> StopSummaryResult:
    """Collect in-flight work at stop time from the proven inventory source.

    * ``force_fault`` (fault injection) returns the named outcome without
      further inventory I/O.
    * Unreadable inventory → ``NamedState.unknown`` (never empty).
    * Readable empty list → ``NamedState.empty`` (nothing was in flight).
    * Readable items with any ``partial=True`` → ok + partial flag.
    * Readable items with total count 0 over non-empty slots → zero_measured.
    * Readable items with positive total → ok.
    """
    sid = str(session_id or "").strip() or "session"

    if force_fault is not None:
        return _forced_result(sid, normalize_stop_reason(force_fault))

    if capability_present is False:
        return StopSummaryResult(
            session_id=sid,
            named_state=NamedState.unknown,
            items=(),
            total_count=0,
            inventory_source=INVENTORY_SOURCE_NAME,
            inventory_source_label=INVENTORY_SOURCE_LABEL,
            query_id=DEFAULT_QUERY_ID,
            reason=StopSummaryReason.CAPABILITY_ABSENT.value,
            detail=REASON_LABELS[StopSummaryReason.CAPABILITY_ABSENT.value],
        )

    inv = inventory if inventory is not None else empty_inventory(sid)

    try:
        raw_items = inv.list_in_flight(sid)
    except InventoryUnreadableError as exc:
        return StopSummaryResult(
            session_id=sid,
            named_state=NamedState.unknown,
            items=(),
            total_count=0,
            inventory_source=getattr(inv, "source_name", INVENTORY_SOURCE_NAME),
            inventory_source_label=getattr(
                inv, "source_label", INVENTORY_SOURCE_LABEL
            ),
            query_id=getattr(inv, "query_id", DEFAULT_QUERY_ID),
            reason=StopSummaryReason.INVENTORY_UNREADABLE.value,
            detail=str(exc) or REASON_LABELS[
                StopSummaryReason.INVENTORY_UNREADABLE.value
            ],
        )

    items = tuple(raw_items)
    total = sum(int(i.count) for i in items)
    any_partial = any(bool(i.partial) for i in items)
    qid = getattr(inv, "query_id", DEFAULT_QUERY_ID)
    src = getattr(inv, "source_name", INVENTORY_SOURCE_NAME)
    label = getattr(inv, "source_label", INVENTORY_SOURCE_LABEL)

    if not items:
        return StopSummaryResult(
            session_id=sid,
            named_state=NamedState.empty,
            items=(),
            total_count=0,
            inventory_source=src,
            inventory_source_label=label,
            query_id=qid,
            reason=StopSummaryReason.ZERO_ITEMS.value,
            detail=REASON_LABELS[StopSummaryReason.ZERO_ITEMS.value],
        )

    if total == 0:
        return StopSummaryResult(
            session_id=sid,
            named_state=NamedState.zero_measured,
            items=items,
            total_count=0,
            inventory_source=src,
            inventory_source_label=label,
            query_id=qid,
            reason=StopSummaryReason.ZERO_MEASURED.value,
            detail=REASON_LABELS[StopSummaryReason.ZERO_MEASURED.value],
            partial=any_partial,
        )

    reason = (
        StopSummaryReason.PARTIAL_ITEMS.value
        if any_partial
        else StopSummaryReason.OK.value
    )
    return StopSummaryResult(
        session_id=sid,
        named_state=NamedState.ok,
        items=items,
        total_count=total,
        inventory_source=src,
        inventory_source_label=label,
        query_id=qid,
        reason=reason,
        detail=REASON_LABELS[reason],
        partial=any_partial,
    )


def force_collect_for_fault(
    fault: Union[str, StopSummaryReason],
    *,
    session_id: str = "sess-stop",
) -> StopSummaryResult:
    """Induce one named stop-summary fault (W16 gate / fault_inject seam)."""
    return collect_stop_summary(session_id, force_fault=fault)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _forced_result(session_id: str, reason: str) -> StopSummaryResult:
    ns = REASON_STATE[reason]
    if reason == StopSummaryReason.OK.value:
        inv = three_item_inventory(session_id)
        items = tuple(inv.list_in_flight(session_id))
        total = sum(int(i.count) for i in items)
        return StopSummaryResult(
            session_id=session_id,
            named_state=NamedState.ok,
            items=items,
            total_count=total,
            query_id=inv.query_id,
            reason=reason,
            detail=REASON_LABELS[reason],
        )
    if reason == StopSummaryReason.PARTIAL_ITEMS.value:
        inv = partial_item_inventory(session_id)
        items = tuple(inv.list_in_flight(session_id))
        total = sum(int(i.count) for i in items)
        return StopSummaryResult(
            session_id=session_id,
            named_state=NamedState.ok,
            items=items,
            total_count=total,
            query_id=inv.query_id,
            reason=reason,
            detail=REASON_LABELS[reason],
            partial=True,
        )
    if reason == StopSummaryReason.ZERO_MEASURED.value:
        inv = zero_measured_inventory(session_id)
        items = tuple(inv.list_in_flight(session_id))
        return StopSummaryResult(
            session_id=session_id,
            named_state=NamedState.zero_measured,
            items=items,
            total_count=0,
            query_id=inv.query_id,
            reason=reason,
            detail=REASON_LABELS[reason],
        )
    # unknown / empty / capability_absent — no items
    return StopSummaryResult(
        session_id=session_id,
        named_state=ns,
        items=(),
        total_count=0,
        reason=reason,
        detail=REASON_LABELS.get(reason, reason),
    )


def _as_item(
    raw: Union[InFlightItem, Mapping[str, Any]],
    *,
    query_id: str = DEFAULT_QUERY_ID,
) -> InFlightItem:
    if isinstance(raw, InFlightItem):
        if raw.query_ref:
            return raw
        return InFlightItem(
            item_id=raw.item_id,
            label=raw.label,
            count=int(raw.count),
            partial=bool(raw.partial),
            query_ref="%s#%s" % (query_id, raw.item_id),
            meta=dict(raw.meta),
        )
    item_id = str(raw.get("item_id") or raw.get("id") or "").strip()
    label = str(raw.get("label") or raw.get("name") or item_id or "item")
    count = int(raw.get("count", raw.get("n", 0)) or 0)
    partial = bool(raw.get("partial", False))
    qref = str(raw.get("query_ref") or "").strip() or (
        "%s#%s" % (query_id, item_id or "item")
    )
    meta = dict(raw.get("meta") or {})
    return InFlightItem(
        item_id=item_id or "item",
        label=label,
        count=count,
        partial=partial,
        query_ref=qref,
        meta=meta,
    )


__all__ = [
    "WAVE_ID",
    "SURFACE_ID",
    "CAPABILITY_CONTROL_ID",
    "INVENTORY_SOURCE_LABEL",
    "INVENTORY_SOURCE_NAME",
    "DEFAULT_QUERY_ID",
    "STOP_SUMMARY_REASONS",
    "INDUCED_FAULT_REASONS",
    "INDUCED_FAULT_INVENTORY_UNREADABLE",
    "INDUCED_FAULT_ZERO_ITEMS",
    "INDUCED_FAULT_PARTIAL_ITEMS",
    "REASON_LABELS",
    "REASON_STATE",
    "StopSummaryReason",
    "InventoryUnreadableError",
    "StopSummaryError",
    "InFlightItem",
    "StopSummaryResult",
    "InFlightInventory",
    "empty_inventory",
    "unreadable_inventory",
    "three_item_inventory",
    "partial_item_inventory",
    "zero_measured_inventory",
    "normalize_stop_reason",
    "stop_reason_named_state",
    "collect_stop_summary",
    "force_collect_for_fault",
]
