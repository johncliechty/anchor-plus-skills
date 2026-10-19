"""Doctor package — real diagnose + banner handoff (W14) + per-engine probes (W15).

Re-exports the ``diagnose`` and ``banner_handoff`` *submodules* (not the
``diagnose`` function of the same name). Callers that need the callable use
``diagnose.diagnose`` or ``from anchor.doctor.diagnose import diagnose``.
Binding the function on this package under that name would shadow the module
and break ``from anchor.doctor import diagnose`` → ``.WAVE_ID``.

W15 adds ``depth_label`` and ``engines`` (Claude / Gemini / Grok independent
probes with depth labels).
"""
from __future__ import annotations

from . import banner_handoff, depth_label, diagnose, engines
from .banner_handoff import (
    IssuePayload,
    RedetectionForbidden,
    banner_issue_payload,
    doctor_entry,
    issue_payload_hash,
)
from .depth_label import (
    DepthLabel,
    EngineReport,
    UnlabelledReportError,
    validate_engine_report,
    validate_engine_reports,
)
from .diagnose import (
    CONTRACT_FAULTS,
    DiagnosisResult,
    Finding,
    Reading,
    SystemState,
    force_fault,
    healthy_system,
    parse_fault_contracts,
    take_readings,
)
from .engines import probe_all_engines, probe_engine

__all__ = [
    "banner_handoff",
    "depth_label",
    "diagnose",
    "engines",
    "CONTRACT_FAULTS",
    "DepthLabel",
    "DiagnosisResult",
    "EngineReport",
    "Finding",
    "IssuePayload",
    "Reading",
    "RedetectionForbidden",
    "SystemState",
    "UnlabelledReportError",
    "banner_issue_payload",
    "doctor_entry",
    "force_fault",
    "healthy_system",
    "issue_payload_hash",
    "parse_fault_contracts",
    "probe_all_engines",
    "probe_engine",
    "take_readings",
    "validate_engine_report",
    "validate_engine_reports",
]
