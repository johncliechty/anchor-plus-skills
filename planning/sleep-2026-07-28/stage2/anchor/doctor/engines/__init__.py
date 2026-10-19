"""Per-engine independent Doctor probes — W15.

Claude, Gemini, and Grok each have their own probe module with its own
failure path and named state. Results are never echoed across engines:
:func:`probe_all_engines` runs each probe independently and returns three
depth-labelled reports.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from anchor.doctor.depth_label import (
    ENGINE_CLAUDE,
    ENGINE_GEMINI,
    ENGINE_GROK,
    ENGINE_IDS,
    EngineReport,
    validate_engine_reports,
)
from anchor.doctor.engines import claude as claude_mod
from anchor.doctor.engines import gemini as gemini_mod
from anchor.doctor.engines import grok as grok_mod

_PROBE_BY_ENGINE = {
    ENGINE_CLAUDE: claude_mod.probe,
    ENGINE_GEMINI: gemini_mod.probe,
    ENGINE_GROK: grok_mod.probe,
}


def probe_engine(
    engine: str,
    *,
    fault: Optional[str] = None,
    state: Any = None,
) -> EngineReport:
    """Run one engine's independent probe. Never consults other engines."""
    eng = str(engine).strip().lower()
    if eng not in _PROBE_BY_ENGINE:
        raise ValueError(
            "unknown engine %r — expected one of %s" % (engine, list(ENGINE_IDS))
        )
    return _PROBE_BY_ENGINE[eng](state=state, fault=fault)


def probe_all_engines(
    *,
    faults: Optional[Mapping[str, Optional[str]]] = None,
    states: Optional[Mapping[str, Any]] = None,
    validate: bool = True,
) -> Dict[str, EngineReport]:
    """Probe Claude, Gemini, and Grok independently.

    *faults* and *states* are per-engine maps. A fault on one engine never
    mutates another engine's probe input or report. When *validate* is True
    (default), every report must carry a depth label.
    """
    fault_map = dict(faults or {})
    state_map = dict(states or {})
    reports: Dict[str, EngineReport] = {}
    for eng in ENGINE_IDS:
        reports[eng] = probe_engine(
            eng,
            fault=fault_map.get(eng),
            state=state_map.get(eng),
        )
    if validate:
        validate_engine_reports(reports)
    return reports


__all__ = [
    "ENGINE_CLAUDE",
    "ENGINE_GEMINI",
    "ENGINE_GROK",
    "ENGINE_IDS",
    "EngineReport",
    "claude_mod",
    "gemini_mod",
    "grok_mod",
    "probe_engine",
    "probe_all_engines",
]
