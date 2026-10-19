"""Independent Claude Doctor probe — W15.

Own failure path, own named state, own depth label. Never reads Gemini or
Grok state; never echoes another engine's verdict.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Dict, Optional

from anchor.doctor.depth_label import (
    ENGINE_CLAUDE,
    ENGINE_CONTROL_IDS,
    DepthLabel,
    EngineReport,
    depth_for_named_state,
    make_engine_report,
)
from anchor.ui.named_state import NamedState

ENGINE_ID = ENGINE_CLAUDE
CONTROL_ID = ENGINE_CONTROL_IDS[ENGINE_CLAUDE]
WAVE_ID = "W15"

#: Claude-only reading identity (never shared with other engines).
READING_NAME = "claude_model_reachable"
HEALTHY_MODEL_ID = "claude-frontier"
PROBE_TIMEOUT_BOUND_MS = 5000

FAULT_TIMEOUT = "timeout"
FAULT_STORE_UNREADABLE = "store_unreadable"
FAULT_EMPTY = "empty"
FAULT_MISSING = "missing"
FAULT_GARBAGE = "garbage"
FAULT_ZERO_MEASURED = "zero_measured"

_FAULT_MUTATIONS: Dict[str, Dict[str, Any]] = {
    FAULT_TIMEOUT: {"probe_elapsed_ms": 9000},
    FAULT_STORE_UNREADABLE: {"store_readable": False},
    FAULT_EMPTY: {"finding_scope_empty": True},
    FAULT_MISSING: {"available": False},
    FAULT_GARBAGE: {"returns_garbage": True},
    FAULT_ZERO_MEASURED: {"finding_count": 0, "scope_exists": True},
}


@dataclass
class ClaudeProbeState:
    """Injectable live state for the Claude-only probe."""

    available: bool = True
    store_readable: bool = True
    probe_elapsed_ms: int = 12
    model_id: str = HEALTHY_MODEL_ID
    model_reachable: bool = True
    finding_scope_empty: bool = False
    returns_garbage: bool = False
    finding_count: int = 2
    scope_exists: bool = True
    active_fault: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "engine": ENGINE_ID,
            "available": self.available,
            "store_readable": self.store_readable,
            "probe_elapsed_ms": self.probe_elapsed_ms,
            "model_id": self.model_id,
            "model_reachable": self.model_reachable,
            "finding_scope_empty": self.finding_scope_empty,
            "returns_garbage": self.returns_garbage,
            "finding_count": self.finding_count,
            "scope_exists": self.scope_exists,
            "active_fault": self.active_fault,
        }


def healthy_state() -> ClaudeProbeState:
    return ClaudeProbeState()


def force_fault(
    fault_id: str,
    state: Optional[ClaudeProbeState] = None,
) -> ClaudeProbeState:
    base = copy.deepcopy(state) if state is not None else healthy_state()
    fid = str(fault_id).strip()
    mutations = _FAULT_MUTATIONS.get(fid)
    if mutations:
        for key, value in mutations.items():
            setattr(base, key, value)
    base.active_fault = fid
    return base


def probe(
    state: Optional[ClaudeProbeState] = None,
    *,
    fault: Optional[str] = None,
) -> EngineReport:
    """Run the Claude-only diagnose probe; always returns a depth-labelled report."""
    sys = state
    if fault is not None:
        sys = force_fault(fault, state)
    if sys is None:
        sys = healthy_state()
    active = fault if fault is not None else sys.active_fault

    if not sys.available:
        return make_engine_report(
            ENGINE_ID,
            NamedState.cannot_run,
            depth=DepthLabel.UNAVAILABLE,
            ok=False,
            reading_name=READING_NAME,
            reading_value=False,
            detail="claude probe capability absent",
            fault=active,
            control_id=CONTROL_ID,
        )

    if not sys.store_readable:
        return make_engine_report(
            ENGINE_ID,
            NamedState.unknown,
            depth=DepthLabel.UNAVAILABLE,
            ok=False,
            reading_name="claude_store_readable",
            reading_value=False,
            detail="claude engine store unreadable",
            fault=active,
            control_id=CONTROL_ID,
        )

    if sys.returns_garbage:
        return make_engine_report(
            ENGINE_ID,
            NamedState.measurement_failed,
            depth=DepthLabel.SHALLOW,
            ok=False,
            reading_name="claude_payload",
            reading_value="garbage",
            detail="claude probe returned unusable payload",
            fault=active,
            control_id=CONTROL_ID,
        )

    if sys.finding_scope_empty:
        return make_engine_report(
            ENGINE_ID,
            NamedState.empty,
            depth=DepthLabel.SHALLOW,
            ok=False,
            reading_name="claude_finding_scope",
            reading_value=0,
            detail="claude finding scope legitimately empty",
            fault=active,
            control_id=CONTROL_ID,
        )

    if int(sys.probe_elapsed_ms) > PROBE_TIMEOUT_BOUND_MS:
        return make_engine_report(
            ENGINE_ID,
            NamedState.timeout,
            depth=DepthLabel.SHALLOW,
            ok=False,
            reading_name="claude_probe_elapsed_ms",
            reading_value=int(sys.probe_elapsed_ms),
            detail="claude probe timed out",
            fault=active,
            control_id=CONTROL_ID,
        )

    if sys.scope_exists and int(sys.finding_count) == 0:
        return make_engine_report(
            ENGINE_ID,
            NamedState.zero_measured,
            depth=DepthLabel.DEEP,
            ok=True,
            reading_name="claude_finding_count",
            reading_value=0,
            detail="claude measured zero findings over existing scope",
            fault=active,
            control_id=CONTROL_ID,
        )

    # Healthy full probe — deep.
    return make_engine_report(
        ENGINE_ID,
        NamedState.ok,
        depth=DepthLabel.DEEP,
        ok=True,
        reading_name=READING_NAME,
        reading_value=sys.model_reachable,
        detail="claude model_id=%s reachable=%s" % (sys.model_id, sys.model_reachable),
        fault=active,
        control_id=CONTROL_ID,
    )


def named_state_for_fault(fault_id: str) -> NamedState:
    """Map a Claude fault id to the named state this probe alone would emit."""
    return probe(fault=fault_id).named_state


def depth_for_fault(fault_id: str) -> DepthLabel:
    return probe(fault=fault_id).depth or depth_for_named_state(NamedState.unknown)


__all__ = [
    "ENGINE_ID",
    "CONTROL_ID",
    "WAVE_ID",
    "READING_NAME",
    "HEALTHY_MODEL_ID",
    "PROBE_TIMEOUT_BOUND_MS",
    "FAULT_TIMEOUT",
    "FAULT_STORE_UNREADABLE",
    "FAULT_EMPTY",
    "FAULT_MISSING",
    "FAULT_GARBAGE",
    "FAULT_ZERO_MEASURED",
    "ClaudeProbeState",
    "healthy_state",
    "force_fault",
    "probe",
    "named_state_for_fault",
    "depth_for_fault",
]
