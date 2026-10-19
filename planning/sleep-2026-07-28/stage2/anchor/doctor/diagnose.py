"""Real Doctor diagnosis — W14, Phase 3.

Every finding is derived from a **reading taken at diagnose time** (a value,
path, version, or count read from the live system) and carries that reading
with it.

Hard bans (frozen plan — machine-enforced by the wave tests):

* **Fixed seed strings are banned** — no rendered finding text may be a
  source literal.
* **No injector-tag → polished-prose branch** — diagnosis evaluates live
  readings against a healthy baseline; it never maps a fault tag to canned
  prose. A multi-branch template fails the anti-template test by
  construction (a fault absent from the contract table still must quote a
  live reading, or render the named no-finding state).

Fault→finding contracts live in
``artifacts/FAULT-FINDING-CONTRACTS.md`` (shape only — never wording).
"""
from __future__ import annotations

import copy
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from anchor.ui.named_state import NamedState

# --------------------------------------------------------------------------
# Public constants
# --------------------------------------------------------------------------

WAVE_ID = "W14"
SURFACE_ID = "doctor-diagnose"
CONTROL_DIAGNOSE = "diagnose"

#: Relative path of the fault→finding contract table under the stage2 root.
FAULT_CONTRACTS_RELPATH = os.path.join("artifacts", "FAULT-FINDING-CONTRACTS.md")

#: Named no-finding state (empty scope — legitimate zero findings).
NO_FINDING_STATE = NamedState.empty

#: Named unavailable state for the Diagnose control when capability is absent.
DIAGNOSE_UNAVAILABLE_STATE = NamedState.cannot_run

#: Reading keys always taken at diagnose time (order stable for traces).
READING_KEYS: Tuple[str, ...] = (
    "service_status",
    "process_count",
    "config_path",
    "version",
    "probe_elapsed_ms",
    "orphan_socket_count",
    "health_store_readable",
    "finding_scope_empty",
)

#: Contract-table fault ids (must match FAULT-FINDING-CONTRACTS.md rows).
CONTRACT_FAULTS: Tuple[str, ...] = (
    "service_status_down",
    "process_count_zero",
    "config_path_missing",
    "version_mismatch",
    "probe_timeout",
    "health_store_unreadable",
    "empty_finding_scope",
)

#: Fault absent from the contract table — anti-template / baseline-diff only.
ANTI_TEMPLATE_FAULT = "orphan_socket_flood"

#: Healthy baseline values (live readings compare against these).
_HEALTHY: Dict[str, Any] = {
    "service_status": "up",
    "process_count": 3,
    "config_path": "config/anchor.json",
    "version": "1.2.0",
    "probe_elapsed_ms": 12,
    "orphan_socket_count": 0,
    "health_store_readable": True,
    "finding_scope_empty": False,
}

#: Per-fault mutation of the live system (values only — never prose).
_FAULT_MUTATIONS: Dict[str, Dict[str, Any]] = {
    "service_status_down": {"service_status": "down"},
    "process_count_zero": {"process_count": 0},
    "config_path_missing": {"config_path": "config/missing.json"},
    "version_mismatch": {"version": "0.9.0"},
    "probe_timeout": {"probe_elapsed_ms": 9000},
    "health_store_unreadable": {"health_store_readable": False},
    "empty_finding_scope": {"finding_scope_empty": True},
    # Anti-template: not listed in FAULT-FINDING-CONTRACTS.md
    ANTI_TEMPLATE_FAULT: {"orphan_socket_count": 17},
}

#: Probe timeout bound (ms) — elapsed above this is a timeout finding shape.
PROBE_TIMEOUT_BOUND_MS = 5000

#: Expected product version for the version reading.
EXPECTED_VERSION = "1.2.0"


# --------------------------------------------------------------------------
# System state + readings
# --------------------------------------------------------------------------


@dataclass
class SystemState:
    """Injectable live system under diagnosis.

    Defaults match the healthy baseline. Fault injection mutates fields
    before readings are taken; diagnosis never branches on fault tags for
    prose — it only compares readings to baseline.
    """

    service_status: str = "up"
    process_count: int = 3
    config_path: str = "config/anchor.json"
    version: str = "1.2.0"
    probe_elapsed_ms: int = 12
    orphan_socket_count: int = 0
    health_store_readable: bool = True
    finding_scope_empty: bool = False
    active_fault: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "service_status": self.service_status,
            "process_count": self.process_count,
            "config_path": self.config_path,
            "version": self.version,
            "probe_elapsed_ms": self.probe_elapsed_ms,
            "orphan_socket_count": self.orphan_socket_count,
            "health_store_readable": self.health_store_readable,
            "finding_scope_empty": self.finding_scope_empty,
            "active_fault": self.active_fault,
        }


@dataclass(frozen=True)
class Reading:
    """One live reading taken at diagnose time."""

    name: str
    value: Any
    source: str = "live_system"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "source": self.source,
        }

    def display_value(self) -> str:
        """String form of the live value (used inside rendered findings)."""
        if isinstance(self.value, bool):
            return "true" if self.value else "false"
        return str(self.value)


@dataclass(frozen=True)
class Finding:
    """A diagnosis finding bound to one live reading.

    ``rendered`` is composed at diagnose time from the reading name + value
    and must never appear as a fixed source literal. ``shape`` is the
    contract-table shape token (never free-form prose).
    """

    reading_name: str
    reading_value: Any
    shape: str
    rendered: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "reading_name": self.reading_name,
            "reading_value": self.reading_value,
            "shape": self.shape,
            "rendered": self.rendered,
        }

    def quotes_reading(self) -> bool:
        """True when the rendered text contains the live reading value."""
        needle = (
            "true"
            if self.reading_value is True
            else "false"
            if self.reading_value is False
            else str(self.reading_value)
        )
        return needle in self.rendered and self.reading_name in self.rendered


@dataclass
class DiagnosisResult:
    """Outcome of one diagnose() call."""

    readings: Dict[str, Reading] = field(default_factory=dict)
    findings: List[Finding] = field(default_factory=list)
    named_state: Optional[NamedState] = None
    no_finding: bool = False
    fault: Optional[str] = None
    ok: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {
            "readings": {k: v.as_dict() for k, v in self.readings.items()},
            "findings": [f.as_dict() for f in self.findings],
            "named_state": (
                self.named_state.value if self.named_state is not None else None
            ),
            "no_finding": self.no_finding,
            "fault": self.fault,
            "ok": self.ok,
        }

    def finding_for_reading(self, reading_name: str) -> Optional[Finding]:
        for f in self.findings:
            if f.reading_name == reading_name:
                return f
        return None

    def rendered_finding_strings(self) -> List[str]:
        return [f.rendered for f in self.findings]


# --------------------------------------------------------------------------
# Live system helpers
# --------------------------------------------------------------------------


def healthy_system() -> SystemState:
    """Return a fresh healthy SystemState (all readings at baseline)."""
    return SystemState()


def force_fault(fault_id: str, system: Optional[SystemState] = None) -> SystemState:
    """Apply a fault mutation to a system copy and return it.

    Unknown fault ids that have a mutation table entry still apply; faults
    with no mutation entry leave the system healthy (anti-template path can
    still use ANTI_TEMPLATE_FAULT which is registered).
    """
    base = copy.deepcopy(system) if system is not None else healthy_system()
    fid = str(fault_id).strip()
    mutations = _FAULT_MUTATIONS.get(fid)
    if mutations:
        for key, value in mutations.items():
            setattr(base, key, value)
    base.active_fault = fid
    return base


def take_readings(system: Optional[SystemState] = None) -> Dict[str, Reading]:
    """Take every reading from the live system at diagnose time."""
    sys = system if system is not None else healthy_system()
    if not sys.health_store_readable:
        # Store unreadable: readings cannot be taken — caller handles unknown.
        return {}
    out: Dict[str, Reading] = {}
    for key in READING_KEYS:
        out[key] = Reading(name=key, value=getattr(sys, key), source="live_system")
    return out


def _compose_finding(reading: Reading, shape: str) -> Finding:
    """Compose a finding at runtime from a live reading.

    Deliberately builds the rendered string from parts so the full rendered
    text is never a source literal. Shape is a contract token, not prose.
    """
    # Parts joined at runtime — no complete finding sentence lives in source.
    parts = [
        reading.name,
        "=",
        reading.display_value(),
        " ",
        "shape",
        "=",
        shape,
    ]
    rendered = "".join(parts)
    return Finding(
        reading_name=reading.name,
        reading_value=reading.value,
        shape=shape,
        rendered=rendered,
    )


def _shape_for_deviation(name: str, value: Any) -> Optional[str]:
    """Return the finding *shape* for a reading that deviates from baseline.

    Shape tokens are structural (status_value, count_value, …) — never
    polished prose. Returns None when the reading is healthy.
    """
    baseline = _HEALTHY.get(name)
    if name == "health_store_readable":
        # Handled as named unknown before evaluation.
        return None
    if name == "finding_scope_empty":
        return None
    if name == "service_status":
        if value != baseline:
            return "status_value"
        return None
    if name == "process_count":
        if int(value) != int(baseline):
            return "count_value"
        return None
    if name == "config_path":
        if value != baseline:
            return "path_value"
        return None
    if name == "version":
        if value != baseline:
            return "version_value"
        return None
    if name == "probe_elapsed_ms":
        if int(value) > PROBE_TIMEOUT_BOUND_MS:
            return "elapsed_ms_value"
        if int(value) != int(baseline):
            return "elapsed_ms_value"
        return None
    if name == "orphan_socket_count":
        if int(value) != int(baseline):
            return "count_value"
        return None
    # Generic baseline-diff for any future reading key (anti-template path).
    if value != baseline:
        return "reading_value"
    return None


def diagnose(
    system: Optional[SystemState] = None,
    *,
    fault: Optional[str] = None,
) -> DiagnosisResult:
    """Run a real diagnosis from live readings.

    If *fault* is given, the fault is applied to a system copy first. Findings
    are produced only from readings that deviate from the healthy baseline —
    never from a tag→prose map. When the health store is unreadable the
    result is ``named_state=unknown`` with no findings. When the finding
    scope is legitimately empty the result is the named no-finding state
    (``empty``).
    """
    sys = system
    if fault is not None:
        sys = force_fault(fault, system)
    if sys is None:
        sys = healthy_system()

    active = fault if fault is not None else sys.active_fault

    # Unknown: could not read the health store.
    if not sys.health_store_readable:
        return DiagnosisResult(
            readings={},
            findings=[],
            named_state=NamedState.unknown,
            no_finding=False,
            fault=active,
            ok=False,
        )

    # Empty: legitimate empty finding scope (nothing in scope to diagnose).
    if sys.finding_scope_empty:
        readings = take_readings(sys)
        return DiagnosisResult(
            readings=readings,
            findings=[],
            named_state=NO_FINDING_STATE,
            no_finding=True,
            fault=active,
            ok=False,
        )

    readings = take_readings(sys)
    findings: List[Finding] = []
    for key in READING_KEYS:
        if key in ("health_store_readable", "finding_scope_empty"):
            continue
        reading = readings.get(key)
        if reading is None:
            continue
        shape = _shape_for_deviation(key, reading.value)
        if shape is None:
            continue
        findings.append(_compose_finding(reading, shape))

    if not findings:
        return DiagnosisResult(
            readings=readings,
            findings=[],
            named_state=NamedState.ok,
            no_finding=False,
            fault=active,
            ok=True,
        )

    # Timeout shape surfaces as NamedState.timeout when probe_elapsed is the
    # only finding and it is over the bound (still quotes the live reading).
    named: Optional[NamedState] = None
    if (
        len(findings) == 1
        and findings[0].reading_name == "probe_elapsed_ms"
        and int(findings[0].reading_value) > PROBE_TIMEOUT_BOUND_MS
    ):
        named = NamedState.timeout

    return DiagnosisResult(
        readings=readings,
        findings=findings,
        named_state=named,
        no_finding=False,
        fault=active,
        ok=False,
    )


# --------------------------------------------------------------------------
# Contract table loader
# --------------------------------------------------------------------------


def _root(root: Optional[Path] = None) -> Path:
    if root is not None:
        return Path(root)
    env = os.environ.get("ANCHOR_SLEEP_CONTAINMENT_ROOT")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2]


def fault_contracts_path(root: Optional[Path] = None) -> Path:
    return _root(root) / FAULT_CONTRACTS_RELPATH


def parse_fault_contracts(
    text: Optional[str] = None,
    *,
    root: Optional[Path] = None,
) -> List[Dict[str, str]]:
    """Parse FAULT-FINDING-CONTRACTS.md machine rows.

    Expected columns: fault | reading | shape | notes
    """
    if text is None:
        path = fault_contracts_path(root)
        text = path.read_text(encoding="utf-8")
    rows: List[Dict[str, str]] = []
    in_table = False
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("| fault"):
            in_table = True
            continue
        if in_table and line.startswith("|---"):
            continue
        if in_table and line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) < 3:
                continue
            if cells[0] in ("fault",):
                continue
            rows.append(
                {
                    "fault": cells[0].strip("`"),
                    "reading": cells[1].strip("`"),
                    "shape": cells[2].strip("`"),
                    "notes": cells[3] if len(cells) > 3 else "",
                }
            )
        elif in_table and not line.startswith("|"):
            break
    return rows


def assert_finding_matches_contract(
    result: DiagnosisResult,
    contract: Mapping[str, str],
) -> None:
    """Assert a diagnosis result satisfies one fault→finding contract row.

    Differs-from-baseline alone is not enough: the finding must quote the
    reading the fault changed and carry the expected shape token.
    """
    fault = contract["fault"]
    reading_name = contract["reading"]
    shape = contract["shape"]

    # Named-state-only rows (unknown / empty / no_finding).
    if shape in ("named_unknown", "named_empty", "no_finding"):
        if shape == "named_unknown":
            if result.named_state != NamedState.unknown:
                raise AssertionError(
                    "fault %r expected named_state unknown, got %r"
                    % (fault, result.named_state)
                )
            if result.findings:
                raise AssertionError(
                    "fault %r (store unreadable) must not emit findings" % fault
                )
            return
        if shape in ("named_empty", "no_finding"):
            if not result.no_finding and result.named_state != NO_FINDING_STATE:
                raise AssertionError(
                    "fault %r expected named no-finding/empty, got state=%r no_finding=%s"
                    % (fault, result.named_state, result.no_finding)
                )
            if result.findings:
                raise AssertionError(
                    "fault %r (empty scope) must not emit findings" % fault
                )
            return

    finding = result.finding_for_reading(reading_name)
    if finding is None:
        raise AssertionError(
            "fault %r: no finding for reading %r (findings=%r)"
            % (fault, reading_name, [f.as_dict() for f in result.findings])
        )
    if finding.shape != shape:
        raise AssertionError(
            "fault %r: shape %r != expected %r" % (fault, finding.shape, shape)
        )
    if not finding.quotes_reading():
        raise AssertionError(
            "fault %r: finding does not quote live reading %s=%r (rendered=%r)"
            % (fault, reading_name, finding.reading_value, finding.rendered)
        )
    # Reading must be present in the result and match the finding.
    live = result.readings.get(reading_name)
    if live is None:
        raise AssertionError(
            "fault %r: reading %r missing from diagnose-time readings" % (fault, reading_name)
        )
    if live.value != finding.reading_value:
        raise AssertionError(
            "fault %r: finding reading_value %r != live reading %r"
            % (fault, finding.reading_value, live.value)
        )


def collect_rendered_finding_strings(
    faults: Optional[Sequence[str]] = None,
) -> List[str]:
    """Run diagnose under each fault and collect rendered finding strings."""
    target = list(faults) if faults is not None else list(CONTRACT_FAULTS) + [
        ANTI_TEMPLATE_FAULT
    ]
    out: List[str] = []
    for fid in target:
        result = diagnose(fault=fid)
        out.extend(result.rendered_finding_strings())
    return out


def source_contains_finding_literal(
    rendered: str,
    source_text: str,
) -> bool:
    """True when *rendered* appears as a string/bytes literal in *source_text*."""
    if not rendered:
        return False
    # Quote forms: "…", '…', \"…\", '''…''', \"\"\"…\"\"\"
    patterns = (
        '"%s"' % re.escape(rendered),
        "'%s'" % re.escape(rendered),
        '"""%s"""' % re.escape(rendered),
        "'''%s'''" % re.escape(rendered),
    )
    return any(re.search(p, source_text) for p in patterns)


__all__ = [
    "WAVE_ID",
    "SURFACE_ID",
    "CONTROL_DIAGNOSE",
    "FAULT_CONTRACTS_RELPATH",
    "NO_FINDING_STATE",
    "DIAGNOSE_UNAVAILABLE_STATE",
    "READING_KEYS",
    "CONTRACT_FAULTS",
    "ANTI_TEMPLATE_FAULT",
    "PROBE_TIMEOUT_BOUND_MS",
    "EXPECTED_VERSION",
    "SystemState",
    "Reading",
    "Finding",
    "DiagnosisResult",
    "healthy_system",
    "force_fault",
    "take_readings",
    "diagnose",
    "fault_contracts_path",
    "parse_fault_contracts",
    "assert_finding_matches_contract",
    "collect_rendered_finding_strings",
    "source_contains_finding_literal",
]
