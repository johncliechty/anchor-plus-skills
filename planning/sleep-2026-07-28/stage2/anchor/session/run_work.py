"""Run path — W10, Phase 3.

Returns a live run handle or ``CannotRun(reason)`` with reasons enumerated:

* ``no_runnable_target``
* ``engine_unavailable``
* ``prior_run_in_flight``
* ``capability_absent``

The run control is live only when the dead-control contract authorizes it
(PRESENT on a non-STALE inventory row). Capability absence still gets a
named cannot-run reason so the surface never emits a dead Run button.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Union

from anchor.ui.named_state import NamedState
from tools.capability_inventory import InventoryRow, may_authorize_live_control

# --------------------------------------------------------------------------
# Reasons (exhaustive for run)
# --------------------------------------------------------------------------


class RunReason(str, Enum):
    """Enumerated cannot-run reasons (frozen plan — W10)."""

    NO_RUNNABLE_TARGET = "no_runnable_target"
    ENGINE_UNAVAILABLE = "engine_unavailable"
    PRIOR_RUN_IN_FLIGHT = "prior_run_in_flight"
    CAPABILITY_ABSENT = "capability_absent"


RUN_REASONS: tuple = tuple(r.value for r in RunReason)

RUN_REASON_LABELS: Dict[str, str] = {
    RunReason.NO_RUNNABLE_TARGET.value: "no runnable target",
    RunReason.ENGINE_UNAVAILABLE.value: "engine unavailable",
    RunReason.PRIOR_RUN_IN_FLIGHT.value: "prior run still in flight",
    RunReason.CAPABILITY_ABSENT.value: "run capability absent",
}

#: Every cannot-run reason renders as cannot_run (surface-native).
#: Empty vs unknown for *targets* is handled by the list/state helpers.
RUN_REASON_STATE: Dict[str, NamedState] = {
    RunReason.NO_RUNNABLE_TARGET.value: NamedState.cannot_run,
    RunReason.ENGINE_UNAVAILABLE.value: NamedState.cannot_run,
    RunReason.PRIOR_RUN_IN_FLIGHT.value: NamedState.cannot_run,
    RunReason.CAPABILITY_ABSENT.value: NamedState.cannot_run,
}


# --------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class LiveRunHandle:
    """A live run that was successfully started."""

    run_id: str
    target_id: str
    engine: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return True

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "run_id": self.run_id,
            "target_id": self.target_id,
            "engine": self.engine,
            "meta": dict(self.meta),
        }


@dataclass(frozen=True)
class CannotRun:
    """Run refused with a named reason and NamedState."""

    reason: str
    detail: str = ""
    target_id: str = ""

    @property
    def ok(self) -> bool:
        return False

    @property
    def named_state(self) -> NamedState:
        return RUN_REASON_STATE.get(self.reason, NamedState.cannot_run)

    @property
    def label(self) -> str:
        return RUN_REASON_LABELS.get(self.reason, self.reason)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": False,
            "reason": self.reason,
            "detail": self.detail,
            "target_id": self.target_id,
            "named_state": self.named_state.value,
            "label": self.label,
        }


# --------------------------------------------------------------------------
# Injectable run environment
# --------------------------------------------------------------------------


@dataclass
class RunnableTarget:
    """One runnable target (session / job / lane entry)."""

    target_id: str
    engine: str = ""
    label: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RunEnvironment:
    """Injectable environment for the run path (tests + traces)."""

    targets: Dict[str, RunnableTarget] = field(default_factory=dict)
    available_engines: Set[str] = field(default_factory=set)
    in_flight: Set[str] = field(default_factory=set)
    targets_unreadable: bool = False

    def list_targets(self) -> List[RunnableTarget]:
        if self.targets_unreadable:
            raise RunStoreError("runnable target store unreadable")
        return list(self.targets.values())

    def get_target(self, target_id: str) -> Optional[RunnableTarget]:
        if self.targets_unreadable:
            raise RunStoreError("runnable target store unreadable")
        return self.targets.get(str(target_id).strip())

    def engine_available(self, engine: str) -> bool:
        if not engine:
            # No engine named → treat as available only when any engine exists.
            return bool(self.available_engines)
        return engine in self.available_engines

    def is_in_flight(self, target_id: str) -> bool:
        return str(target_id).strip() in self.in_flight


class RunStoreError(Exception):
    """Raised when the runnable-target store cannot be read."""


def empty_run_env() -> RunEnvironment:
    return RunEnvironment()


def make_run_env(
    *,
    targets: Optional[Sequence[Union[RunnableTarget, Mapping[str, Any]]]] = None,
    engines: Optional[Iterable[str]] = None,
    in_flight: Optional[Iterable[str]] = None,
    unreadable: bool = False,
) -> RunEnvironment:
    env = RunEnvironment(targets_unreadable=unreadable)
    for t in targets or ():
        rec = _as_target(t)
        env.targets[rec.target_id] = rec
        if rec.engine:
            env.available_engines.add(rec.engine)
    for e in engines or ():
        env.available_engines.add(str(e).strip())
    for tid in in_flight or ():
        env.in_flight.add(str(tid).strip())
    return env


# --------------------------------------------------------------------------
# run_work
# --------------------------------------------------------------------------


def normalize_run_reason(reason: Union[str, RunReason]) -> str:
    if isinstance(reason, RunReason):
        return reason.value
    raw = str(reason).strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "no_runnable_target": RunReason.NO_RUNNABLE_TARGET.value,
        "no_target": RunReason.NO_RUNNABLE_TARGET.value,
        "missing_target": RunReason.NO_RUNNABLE_TARGET.value,
        "engine_unavailable": RunReason.ENGINE_UNAVAILABLE.value,
        "engine_missing": RunReason.ENGINE_UNAVAILABLE.value,
        "no_engine": RunReason.ENGINE_UNAVAILABLE.value,
        "prior_run_in_flight": RunReason.PRIOR_RUN_IN_FLIGHT.value,
        "in_flight": RunReason.PRIOR_RUN_IN_FLIGHT.value,
        "run_in_flight": RunReason.PRIOR_RUN_IN_FLIGHT.value,
        "capability_absent": RunReason.CAPABILITY_ABSENT.value,
        "missing_capability": RunReason.CAPABILITY_ABSENT.value,
        "capability_missing": RunReason.CAPABILITY_ABSENT.value,
    }
    if raw not in aliases:
        raise ValueError(
            "unknown run reason %r — must be one of %s" % (reason, list(RUN_REASONS))
        )
    return aliases[raw]


def run_work(
    target_id: Optional[str] = None,
    *,
    engine: str = "",
    env: Optional[RunEnvironment] = None,
    inventory_row: Optional[InventoryRow] = None,
    capability_present: Optional[bool] = None,
    force_reason: Optional[Union[str, RunReason]] = None,
    root: Optional[Path] = None,
    run_id: Optional[str] = None,
) -> Union[LiveRunHandle, CannotRun]:
    """Start a run or return ``CannotRun`` with an enumerated reason."""
    if force_reason is not None:
        reason = normalize_run_reason(force_reason)
        return CannotRun(
            reason=reason,
            detail=RUN_REASON_LABELS.get(reason, reason),
            target_id=str(target_id or ""),
        )

    cap_ok = _capability_ok(inventory_row, capability_present, root=root)
    if not cap_ok:
        return CannotRun(
            reason=RunReason.CAPABILITY_ABSENT.value,
            detail=RUN_REASON_LABELS[RunReason.CAPABILITY_ABSENT.value],
            target_id=str(target_id or ""),
        )

    run_env = env if env is not None else empty_run_env()

    # Resolve target.
    try:
        if target_id is None or str(target_id).strip() == "":
            targets = run_env.list_targets()
            if not targets:
                return CannotRun(
                    reason=RunReason.NO_RUNNABLE_TARGET.value,
                    detail=RUN_REASON_LABELS[RunReason.NO_RUNNABLE_TARGET.value],
                )
            # Ambiguous without id.
            return CannotRun(
                reason=RunReason.NO_RUNNABLE_TARGET.value,
                detail="target id required",
            )
        tid = str(target_id).strip()
        target = run_env.get_target(tid)
    except RunStoreError:
        # Unreadable target store is still a cannot-run (no runnable target
        # proven); the list surface uses unknown via list_targets_state.
        return CannotRun(
            reason=RunReason.NO_RUNNABLE_TARGET.value,
            detail="runnable target store unreadable",
            target_id=str(target_id or ""),
        )

    if target is None:
        return CannotRun(
            reason=RunReason.NO_RUNNABLE_TARGET.value,
            detail=RUN_REASON_LABELS[RunReason.NO_RUNNABLE_TARGET.value],
            target_id=tid,
        )

    eng = (engine or target.engine or "").strip()
    if eng:
        if not run_env.engine_available(eng):
            return CannotRun(
                reason=RunReason.ENGINE_UNAVAILABLE.value,
                detail=RUN_REASON_LABELS[RunReason.ENGINE_UNAVAILABLE.value],
                target_id=tid,
            )
    elif not run_env.available_engines:
        return CannotRun(
            reason=RunReason.ENGINE_UNAVAILABLE.value,
            detail=RUN_REASON_LABELS[RunReason.ENGINE_UNAVAILABLE.value],
            target_id=tid,
        )

    if run_env.is_in_flight(tid):
        return CannotRun(
            reason=RunReason.PRIOR_RUN_IN_FLIGHT.value,
            detail=RUN_REASON_LABELS[RunReason.PRIOR_RUN_IN_FLIGHT.value],
            target_id=tid,
        )

    rid = (run_id or ("run-%s" % tid)).strip()
    return LiveRunHandle(
        run_id=rid,
        target_id=tid,
        engine=eng or next(iter(run_env.available_engines), ""),
        meta=dict(target.meta),
    )


def list_targets_state(env: Optional[RunEnvironment] = None) -> NamedState:
    """Trichotomy for the runnable-target list: empty vs unknown.

    * store unreadable → ``NamedState.unknown``
    * store readable and zero targets → ``NamedState.empty``
    * store readable with targets → ``NamedState.ok``
    """
    run_env = env if env is not None else empty_run_env()
    try:
        targets = run_env.list_targets()
    except RunStoreError:
        return NamedState.unknown
    if not targets:
        return NamedState.empty
    return NamedState.ok


def run_reason_named_state(reason: Union[str, RunReason]) -> NamedState:
    token = normalize_run_reason(reason)
    return RUN_REASON_STATE[token]


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _capability_ok(
    inventory_row: Optional[InventoryRow],
    capability_present: Optional[bool],
    *,
    root: Optional[Path] = None,
) -> bool:
    if capability_present is False:
        return False
    if capability_present is True:
        return True
    if inventory_row is None:
        return False
    return may_authorize_live_control(inventory_row, root=root)


def _as_target(t: Union[RunnableTarget, Mapping[str, Any]]) -> RunnableTarget:
    if isinstance(t, RunnableTarget):
        return t
    return RunnableTarget(
        target_id=str(t.get("target_id") or t.get("id") or "").strip(),
        engine=str(t.get("engine") or ""),
        label=str(t.get("label") or t.get("name") or ""),
        meta=dict(t.get("meta") or {}),
    )


__all__ = [
    "RUN_REASONS",
    "RUN_REASON_LABELS",
    "RUN_REASON_STATE",
    "RunReason",
    "LiveRunHandle",
    "CannotRun",
    "RunnableTarget",
    "RunEnvironment",
    "RunStoreError",
    "empty_run_env",
    "make_run_env",
    "normalize_run_reason",
    "run_work",
    "list_targets_state",
    "run_reason_named_state",
]
