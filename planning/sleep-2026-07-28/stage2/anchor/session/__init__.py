"""Session open / run / attach / stop-summary entry points (W10+).

Re-exports the ``open_work`` / ``run_work`` / ``attach`` / ``stop_summary``
*submodules* (not the functions of the same name). Callers that need the
callable use ``open_work.open_work`` or
``from anchor.session.open_work import open_work``. Binding the functions on
this package under those names would shadow the modules and break
``from anchor.session import open_work`` → ``.OPEN_REASONS``.
"""
from __future__ import annotations

from . import attach, open_work, run_work, stop_summary
from .attach import (
    ATTACH_REASONS,
    AttachReason,
    AttachedSession,
    CannotAttach,
    CannotRetry,
    RetryAction,
)
from .open_work import (
    OPEN_REASONS,
    CannotOpen,
    OpenReason,
    OpenedWork,
)
from .run_work import (
    RUN_REASONS,
    CannotRun,
    LiveRunHandle,
    RunReason,
)
from .stop_summary import (
    INDUCED_FAULT_REASONS as STOP_SUMMARY_INDUCED_FAULTS,
    STOP_SUMMARY_REASONS,
    InFlightItem,
    StopSummaryResult,
    collect_stop_summary,
)

__all__ = [
    "open_work",
    "run_work",
    "attach",
    "stop_summary",
    "OPEN_REASONS",
    "CannotOpen",
    "OpenReason",
    "OpenedWork",
    "RUN_REASONS",
    "CannotRun",
    "LiveRunHandle",
    "RunReason",
    "ATTACH_REASONS",
    "AttachReason",
    "AttachedSession",
    "CannotAttach",
    "CannotRetry",
    "RetryAction",
    "STOP_SUMMARY_REASONS",
    "STOP_SUMMARY_INDUCED_FAULTS",
    "InFlightItem",
    "StopSummaryResult",
    "collect_stop_summary",
]
