"""Machine list of rollup evidence that surface waves import — W4.

Surface waves (W12 usage/time, W13 cost) read this registry instead of
inventing numerals. Rules (frozen plan):

* A **PROVEN** rollup may render a numeral when sub-verdict is ``nonzero`` or
  ``zero_measured`` (measured zero is a real, trustworthy 0 — never pending).
* Rendering a numeral from a **NO_AGGREGATOR** rollup **raises at test time**.
* A **READ_FAILED** rollup may render **only** ``unknown`` — never a numeral,
  never pending.
* PROVEN/empty renders the empty state (no numeral).

The registry is populated from ``tools.rollup_evidence_gate`` evidence rows
(``ROLLUP-EVIDENCE.md`` / in-memory fixtures). Paths stay relative to the
stage2 containment root.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Union

from tools.rollup_evidence_gate import (
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
    load_evidence,
    pending_label,
    surface_render_for,
    validate_evidence_integrity,
)

# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class RollupRegistryError(Exception):
    """Base registry error."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NumeralFromNoAggregator(RollupRegistryError):
    """Raised at test time when a surface tries to render a numeral from a
    NO_AGGREGATOR rollup (must show pending naming the aggregation wave)."""


class NumeralFromReadFailed(RollupRegistryError):
    """Raised when a surface tries to render a numeral from a READ_FAILED
    rollup (may render only unknown)."""


class NumeralFromEmpty(RollupRegistryError):
    """Raised when a surface tries to render a numeral from PROVEN/empty
    (no series / no scope — not a measured number)."""


class UnknownRollup(RollupRegistryError):
    """Rollup id is not in the registry."""


# --------------------------------------------------------------------------
# Registry entry
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class RegistryEntry:
    """One rollup as surface waves consume it."""

    rollup_id: str
    verdict: Verdict
    sub_verdict: Optional[SubVerdict]
    surface_render: str
    total: Optional[Union[int, float]]
    aggregation_wave: Optional[str]
    row_count: int
    label: str = ""

    @property
    def is_proven(self) -> bool:
        return self.verdict is Verdict.PROVEN

    @property
    def allows_numeral(self) -> bool:
        return self.verdict is Verdict.PROVEN and self.sub_verdict in {
            SubVerdict.NONZERO,
            SubVerdict.ZERO_MEASURED,
        }

    def as_dict(self) -> Dict[str, Any]:
        return {
            "rollup_id": self.rollup_id,
            "verdict": self.verdict.value,
            "sub_verdict": self.sub_verdict.value if self.sub_verdict else None,
            "surface_render": self.surface_render,
            "total": self.total,
            "aggregation_wave": self.aggregation_wave,
            "row_count": self.row_count,
            "label": self.label,
            "allows_numeral": self.allows_numeral,
        }


def entry_from_evidence(evidence: RollupEvidence) -> RegistryEntry:
    validate_evidence_integrity(evidence)
    return RegistryEntry(
        rollup_id=evidence.rollup_id,
        verdict=evidence.verdict,
        sub_verdict=evidence.sub_verdict,
        surface_render=surface_render_for(evidence),
        total=evidence.total,
        aggregation_wave=evidence.aggregation_wave,
        row_count=evidence.row_count,
        label=evidence.label,
    )


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------


class RollupRegistry:
    """Machine list of rollups surface waves import.

    Only PROVEN entries with nonzero / zero_measured sub-verdicts may yield a
    numeral via :meth:`render_numeral`. NO_AGGREGATOR raises; READ_FAILED is
    restricted to the unknown label via :meth:`render_state`.
    """

    def __init__(self, entries: Optional[Iterable[RegistryEntry]] = None):
        self._entries: Dict[str, RegistryEntry] = {}
        if entries:
            for e in entries:
                self.register(e)

    def register(self, entry: RegistryEntry) -> RegistryEntry:
        self._entries[entry.rollup_id] = entry
        return entry

    def register_evidence(self, evidence: RollupEvidence) -> RegistryEntry:
        return self.register(entry_from_evidence(evidence))

    def get(self, rollup_id: str) -> Optional[RegistryEntry]:
        return self._entries.get(rollup_id)

    def require(self, rollup_id: str) -> RegistryEntry:
        entry = self._entries.get(rollup_id)
        if entry is None:
            raise UnknownRollup("rollup %r is not in the registry" % rollup_id)
        return entry

    def list_entries(self) -> List[RegistryEntry]:
        order = {rid: i for i, rid in enumerate(REQUIRED_ROLLUPS)}
        return sorted(
            self._entries.values(),
            key=lambda e: (order.get(e.rollup_id, 999), e.rollup_id),
        )

    def proven_ids(self) -> List[str]:
        return [e.rollup_id for e in self.list_entries() if e.is_proven]

    def render_numeral(self, rollup_id: str) -> Union[int, float]:
        """Return the measured numeral for a PROVEN rollup.

        * NO_AGGREGATOR → raises :class:`NumeralFromNoAggregator` (test-time
          failure for any surface that tries to invent a number).
        * READ_FAILED → raises :class:`NumeralFromReadFailed` (only unknown
          is legal — use :meth:`render_state`).
        * PROVEN/empty → raises :class:`NumeralFromEmpty`.
        * PROVEN/zero_measured → returns ``0`` (measured zero must survive).
        * PROVEN/nonzero → returns the recorded total.
        """
        entry = self.require(rollup_id)

        if entry.verdict is Verdict.NO_AGGREGATOR:
            raise NumeralFromNoAggregator(
                "cannot render a numeral from NO_AGGREGATOR rollup %r — "
                "surface must render pending naming wave %r"
                % (rollup_id, entry.aggregation_wave)
            )

        if entry.verdict is Verdict.READ_FAILED:
            raise NumeralFromReadFailed(
                "cannot render a numeral from READ_FAILED rollup %r — "
                "surface may render only unknown" % rollup_id
            )

        if entry.verdict is Verdict.PROVEN:
            if entry.sub_verdict is SubVerdict.EMPTY:
                raise NumeralFromEmpty(
                    "cannot render a numeral from PROVEN/empty rollup %r — "
                    "scope is empty" % rollup_id
                )
            if entry.sub_verdict is SubVerdict.ZERO_MEASURED:
                # Measured zero is a real, trustworthy 0 — never pending.
                return 0 if entry.total is None else entry.total
            if entry.sub_verdict is SubVerdict.NONZERO:
                if entry.total is None:
                    raise RollupRegistryError(
                        "PROVEN/nonzero rollup %r has no total" % rollup_id
                    )
                return entry.total

        raise RollupRegistryError(
            "rollup %r has no renderable numeral (verdict=%s sub=%s)"
            % (
                rollup_id,
                entry.verdict.value,
                entry.sub_verdict.value if entry.sub_verdict else None,
            )
        )

    def render_state(self, rollup_id: str) -> str:
        """Return the surface-native state label for this rollup.

        READ_FAILED → ``unknown`` only.
        NO_AGGREGATOR → ``pending``.
        PROVEN → ``ok`` | ``zero_measured`` | ``empty``.
        """
        entry = self.require(rollup_id)
        return entry.surface_render

    def render_pending_message(self, rollup_id: str) -> str:
        """Pending text naming the aggregation wave (NO_AGGREGATOR only)."""
        entry = self.require(rollup_id)
        if entry.verdict is not Verdict.NO_AGGREGATOR:
            raise RollupRegistryError(
                "render_pending_message only applies to NO_AGGREGATOR "
                "(got %s for %r)" % (entry.verdict.value, rollup_id)
            )
        # Build a minimal evidence-shaped object for pending_label.
        from tools.rollup_evidence_gate import (
            RollupEvidence as _RE,
            RunReceipt,
        )

        fake = _RE(
            rollup_id=entry.rollup_id,
            verdict=entry.verdict,
            query="(registry)",
            row_count=entry.row_count,
            sample_row=None,
            receipt=RunReceipt(
                run_timestamp="", window="", scope_size=0
            ),
            sub_verdict=None,
            aggregation_wave=entry.aggregation_wave,
            label=entry.label,
        )
        return pending_label(fake)

    def may_render_numeral(self, rollup_id: str) -> bool:
        entry = self.get(rollup_id)
        if entry is None:
            return False
        return entry.allows_numeral


def registry_from_evidence_set(s: RollupEvidenceSet) -> RollupRegistry:
    reg = RollupRegistry()
    for row in s.list_rows():
        reg.register_evidence(row)
    return reg


def load_registry(*, root=None) -> RollupRegistry:
    """Load the registry from on-disk ROLLUP-EVIDENCE.md."""
    s = load_evidence(root=root)
    return registry_from_evidence_set(s)


def bootstrap_registry(*, root=None, write: bool = False) -> RollupRegistry:
    """Build registry from Phase-1 bootstrap evidence (optionally writing docs)."""
    from tools.rollup_evidence_gate import bootstrap_phase1

    s, _, _ = bootstrap_phase1(root=root, write=write)
    return registry_from_evidence_set(s)


# Re-export surface labels for consumers / tests.
__all__ = [
    "NumeralFromEmpty",
    "NumeralFromNoAggregator",
    "NumeralFromReadFailed",
    "RegistryEntry",
    "RENDER_EMPTY",
    "RENDER_OK",
    "RENDER_PENDING",
    "RENDER_UNKNOWN",
    "RENDER_ZERO_MEASURED",
    "REQUIRED_ROLLUPS",
    "RollupRegistry",
    "RollupRegistryError",
    "UnknownRollup",
    "bootstrap_registry",
    "entry_from_evidence",
    "load_registry",
    "registry_from_evidence_set",
]
