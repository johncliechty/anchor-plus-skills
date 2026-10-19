"""Per-context restart entry points — W17, Phase 3.

Enumerate every restart context (run / session / engine / workbench), guarantee
exactly **one** restart control per context, and make each control state its
**scope name** and **preserved/lost** contract.

Cross-context unification is explicitly **out of scope** (frozen plan).

Each entry point returns a viable ``RestartAction`` or a named
``CannotRestart`` (never a dead button). When restart executes, the actual
preserved/lost outcome must match the written contract for that context
(asserted by ``tests/test_restart_contract_2026_07_29.py``).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from anchor.ui.named_state import NamedState
from tools.capability_inventory import InventoryRow, may_authorize_live_control

# --------------------------------------------------------------------------
# Public constants
# --------------------------------------------------------------------------

WAVE_ID = "W17"
SURFACE_ID = "restart"

#: Canonical context ids (enumeration — frozen by RESTART-CONTEXTS.md).
CONTEXT_RUN = "run"
CONTEXT_SESSION = "session"
CONTEXT_ENGINE = "engine"
CONTEXT_WORKBENCH = "workbench"

RESTART_CONTEXT_IDS: Tuple[str, ...] = (
    CONTEXT_RUN,
    CONTEXT_SESSION,
    CONTEXT_ENGINE,
    CONTEXT_WORKBENCH,
)

#: Inventory control id per context (CAPABILITY-INVENTORY.md).
CONTROL_ID_BY_CONTEXT: Dict[str, str] = {
    CONTEXT_RUN: "restart_run",
    CONTEXT_SESSION: "restart_session",
    CONTEXT_ENGINE: "restart_engine",
    CONTEXT_WORKBENCH: "restart_workbench",
}

#: Scope-display name per context (exactly one control carries this label).
SCOPE_NAME_BY_CONTEXT: Dict[str, str] = {
    CONTEXT_RUN: "Restart run",
    CONTEXT_SESSION: "Restart session",
    CONTEXT_ENGINE: "Restart engine",
    CONTEXT_WORKBENCH: "Restart workbench",
}

#: Single control label per context (no competing 'Restart' vs 'Restart session').
CONTROL_LABEL_BY_CONTEXT: Dict[str, str] = dict(SCOPE_NAME_BY_CONTEXT)


# --------------------------------------------------------------------------
# Written preserved/lost contracts (machine + human; tests assert match)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PreservedLostContract:
    """Written restart contract for one context.

    ``contract_line`` is the canonical one-line form asserted by tests
    (e.g. "transcript preserved, running tool calls lost").
    """

    context_id: str
    scope_name: str
    control_id: str
    control_label: str
    preserved: Tuple[str, ...]
    lost: Tuple[str, ...]
    contract_line: str
    requires_scope_confirmation: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {
            "context_id": self.context_id,
            "scope_name": self.scope_name,
            "control_id": self.control_id,
            "control_label": self.control_label,
            "preserved": list(self.preserved),
            "lost": list(self.lost),
            "contract_line": self.contract_line,
            "requires_scope_confirmation": bool(self.requires_scope_confirmation),
        }


#: Frozen enumeration — one contract per context; exactly one control each.
RESTART_CONTRACTS: Dict[str, PreservedLostContract] = {
    CONTEXT_RUN: PreservedLostContract(
        context_id=CONTEXT_RUN,
        scope_name=SCOPE_NAME_BY_CONTEXT[CONTEXT_RUN],
        control_id=CONTROL_ID_BY_CONTEXT[CONTEXT_RUN],
        control_label=CONTROL_LABEL_BY_CONTEXT[CONTEXT_RUN],
        preserved=("session_identity", "transcript", "workspace_files"),
        lost=("running_tool_calls", "in_flight_run_handle", "partial_run_output"),
        contract_line=(
            "session identity and transcript preserved; "
            "running tool calls and in-flight run handle lost"
        ),
        requires_scope_confirmation=False,
    ),
    CONTEXT_SESSION: PreservedLostContract(
        context_id=CONTEXT_SESSION,
        scope_name=SCOPE_NAME_BY_CONTEXT[CONTEXT_SESSION],
        control_id=CONTROL_ID_BY_CONTEXT[CONTEXT_SESSION],
        control_label=CONTROL_LABEL_BY_CONTEXT[CONTEXT_SESSION],
        preserved=("transcript",),
        lost=("running_tool_calls",),
        # Exact GWT contract line from IMPLEMENTATION-PLAN W17.
        contract_line="transcript preserved, running tool calls lost",
        requires_scope_confirmation=False,
    ),
    CONTEXT_ENGINE: PreservedLostContract(
        context_id=CONTEXT_ENGINE,
        scope_name=SCOPE_NAME_BY_CONTEXT[CONTEXT_ENGINE],
        control_id=CONTROL_ID_BY_CONTEXT[CONTEXT_ENGINE],
        control_label=CONTROL_LABEL_BY_CONTEXT[CONTEXT_ENGINE],
        preserved=("session_record", "workspace", "on_disk_transcript"),
        lost=("live_pty", "engine_process", "in_memory_engine_state"),
        contract_line=(
            "session record and on-disk transcript preserved; "
            "live PTY and engine process lost"
        ),
        requires_scope_confirmation=True,
    ),
    CONTEXT_WORKBENCH: PreservedLostContract(
        context_id=CONTEXT_WORKBENCH,
        scope_name=SCOPE_NAME_BY_CONTEXT[CONTEXT_WORKBENCH],
        control_id=CONTROL_ID_BY_CONTEXT[CONTEXT_WORKBENCH],
        control_label=CONTROL_LABEL_BY_CONTEXT[CONTEXT_WORKBENCH],
        preserved=("project_registry", "persisted_documents"),
        lost=("open_panels", "live_terminal_attachments", "ephemeral_ui_state"),
        contract_line=(
            "project registry and persisted documents preserved; "
            "open panels and live terminal attachments lost"
        ),
        requires_scope_confirmation=True,
    ),
}


def get_contract(context_id: str) -> PreservedLostContract:
    """Return the frozen preserved/lost contract for a context id."""
    cid = normalize_context_id(context_id)
    return RESTART_CONTRACTS[cid]


def all_contracts() -> List[PreservedLostContract]:
    """Ordered list of every enumerated restart contract."""
    return [RESTART_CONTRACTS[c] for c in RESTART_CONTEXT_IDS]


# --------------------------------------------------------------------------
# Reasons (cannot-restart)
# --------------------------------------------------------------------------


class RestartReason(str, Enum):
    """Enumerated cannot-restart / restart outcomes (W17)."""

    OK = "ok"
    CAPABILITY_ABSENT = "capability_absent"
    NO_TARGET = "no_target"
    TARGET_GONE = "target_gone"
    STORE_UNREADABLE = "store_unreadable"
    EMPTY_SCOPE = "empty_scope"
    ALREADY_RESTARTING = "already_restarting"
    ENGINE_UNAVAILABLE = "engine_unavailable"


RESTART_REASONS: Tuple[str, ...] = tuple(r.value for r in RestartReason)

#: Induced-fault reasons the W17 gate exercises (one per named failure class).
INDUCED_FAULT_REASONS: Tuple[str, ...] = (
    RestartReason.CAPABILITY_ABSENT.value,
    RestartReason.NO_TARGET.value,
    RestartReason.STORE_UNREADABLE.value,
    RestartReason.EMPTY_SCOPE.value,
    RestartReason.TARGET_GONE.value,
)

REASON_LABELS: Dict[str, str] = {
    RestartReason.OK.value: "restart executed",
    RestartReason.CAPABILITY_ABSENT.value: "restart capability absent",
    RestartReason.NO_TARGET.value: "no restart target",
    RestartReason.TARGET_GONE.value: "restart target gone",
    RestartReason.STORE_UNREADABLE.value: "restart store unreadable",
    RestartReason.EMPTY_SCOPE.value: "restart scope empty",
    RestartReason.ALREADY_RESTARTING.value: "restart already in flight",
    RestartReason.ENGINE_UNAVAILABLE.value: "engine unavailable for restart",
}

REASON_STATE: Dict[str, NamedState] = {
    RestartReason.OK.value: NamedState.ok,
    RestartReason.CAPABILITY_ABSENT.value: NamedState.cannot_restart,
    RestartReason.NO_TARGET.value: NamedState.cannot_restart,
    RestartReason.TARGET_GONE.value: NamedState.cannot_restart,
    RestartReason.STORE_UNREADABLE.value: NamedState.unknown,
    RestartReason.EMPTY_SCOPE.value: NamedState.empty,
    RestartReason.ALREADY_RESTARTING.value: NamedState.cannot_restart,
    RestartReason.ENGINE_UNAVAILABLE.value: NamedState.cannot_restart,
}


# --------------------------------------------------------------------------
# Subject state (injectable; tests assert preserved/lost after restart)
# --------------------------------------------------------------------------


@dataclass
class RestartSubject:
    """Mutable pre-restart subject state for one context.

    Tests construct a subject with named fields present, run the context
    entry point, and assert the after-state matches the written contract.
    """

    context_id: str
    target_id: str = ""
    # Shared / session-ish fields
    transcript: Optional[str] = "session transcript body"
    running_tool_calls: List[str] = field(
        default_factory=lambda: ["tool_call_a", "tool_call_b"]
    )
    session_identity: str = "session-id-1"
    session_id: str = "session-id-1"
    session_record: Optional[Dict[str, Any]] = field(
        default_factory=lambda: {"id": "session-id-1", "lane": "build"}
    )
    workspace_files: List[str] = field(
        default_factory=lambda: ["README.md", "src/main.py"]
    )
    workspace: str = "workspace-root"
    on_disk_transcript: Optional[str] = "on-disk transcript body"
    # Run-scoped
    in_flight_run_handle: Optional[str] = "run-handle-1"
    partial_run_output: Optional[str] = "partial output chunk"
    # Engine-scoped
    live_pty: bool = True
    engine_process: Optional[str] = "engine-pid-1"
    in_memory_engine_state: Optional[Dict[str, Any]] = field(
        default_factory=lambda: {"buffer": "live"}
    )
    # Workbench-scoped
    project_registry: Optional[Dict[str, Any]] = field(
        default_factory=lambda: {"projects": ["p1"]}
    )
    persisted_documents: List[str] = field(
        default_factory=lambda: ["NORTH-STAR.md"]
    )
    open_panels: List[str] = field(
        default_factory=lambda: ["panel-a", "panel-b"]
    )
    live_terminal_attachments: List[str] = field(
        default_factory=lambda: ["term-1"]
    )
    ephemeral_ui_state: Optional[Dict[str, Any]] = field(
        default_factory=lambda: {"scroll": 12}
    )
    # Store simulation
    store_unreadable: bool = False
    target_gone: bool = False
    empty_scope: bool = False
    already_restarting: bool = False
    engine_unavailable: bool = False
    meta: Dict[str, Any] = field(default_factory=dict)

    def snapshot(self) -> Dict[str, Any]:
        """Serializable snapshot of fields relevant to contracts."""
        return {
            "context_id": self.context_id,
            "target_id": self.target_id,
            "transcript": self.transcript,
            "running_tool_calls": list(self.running_tool_calls),
            "session_identity": self.session_identity,
            "session_id": self.session_id,
            "session_record": dict(self.session_record or {}) or None,
            "workspace_files": list(self.workspace_files),
            "workspace": self.workspace,
            "on_disk_transcript": self.on_disk_transcript,
            "in_flight_run_handle": self.in_flight_run_handle,
            "partial_run_output": self.partial_run_output,
            "live_pty": self.live_pty,
            "engine_process": self.engine_process,
            "in_memory_engine_state": (
                dict(self.in_memory_engine_state)
                if self.in_memory_engine_state is not None
                else None
            ),
            "project_registry": (
                dict(self.project_registry)
                if self.project_registry is not None
                else None
            ),
            "persisted_documents": list(self.persisted_documents),
            "open_panels": list(self.open_panels),
            "live_terminal_attachments": list(self.live_terminal_attachments),
            "ephemeral_ui_state": (
                dict(self.ephemeral_ui_state)
                if self.ephemeral_ui_state is not None
                else None
            ),
        }


def make_subject(
    context_id: str,
    *,
    target_id: str = "target-1",
    **kwargs: Any,
) -> RestartSubject:
    """Factory for a default RestartSubject for the given context."""
    cid = normalize_context_id(context_id)
    return RestartSubject(context_id=cid, target_id=target_id, **kwargs)


# --------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class RestartAction:
    """Successful restart — viable action with preserved/lost outcome."""

    context_id: str
    scope_name: str
    control_id: str
    control_label: str
    contract_line: str
    preserved: Tuple[str, ...]
    lost: Tuple[str, ...]
    target_id: str = ""
    before_state: Dict[str, Any] = field(default_factory=dict)
    after_state: Dict[str, Any] = field(default_factory=dict)
    preserved_values: Dict[str, Any] = field(default_factory=dict)
    lost_values: Dict[str, Any] = field(default_factory=dict)
    requires_scope_confirmation: bool = False
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return True

    @property
    def named_state(self) -> NamedState:
        return NamedState.ok

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "context_id": self.context_id,
            "scope_name": self.scope_name,
            "control_id": self.control_id,
            "control_label": self.control_label,
            "contract_line": self.contract_line,
            "preserved": list(self.preserved),
            "lost": list(self.lost),
            "target_id": self.target_id,
            "before_state": dict(self.before_state),
            "after_state": dict(self.after_state),
            "preserved_values": dict(self.preserved_values),
            "lost_values": dict(self.lost_values),
            "requires_scope_confirmation": bool(self.requires_scope_confirmation),
            "named_state": self.named_state.value,
            "meta": dict(self.meta),
        }

    def field_present_after(self, name: str) -> bool:
        """True when *name* is present (non-empty) in after_state."""
        val = self.after_state.get(name)
        return _is_present(val)

    def field_absent_after(self, name: str) -> bool:
        """True when *name* is absent / cleared in after_state."""
        return not self.field_present_after(name)


@dataclass(frozen=True)
class CannotRestart:
    """Restart refused with a named reason and NamedState."""

    context_id: str
    reason: str
    detail: str = ""
    target_id: str = ""
    scope_name: str = ""
    control_id: str = ""

    @property
    def ok(self) -> bool:
        return False

    @property
    def named_state(self) -> NamedState:
        return REASON_STATE.get(self.reason, NamedState.cannot_restart)

    @property
    def label(self) -> str:
        return REASON_LABELS.get(self.reason, self.reason)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": False,
            "context_id": self.context_id,
            "reason": self.reason,
            "detail": self.detail,
            "target_id": self.target_id,
            "scope_name": self.scope_name,
            "control_id": self.control_id,
            "named_state": self.named_state.value,
            "label": self.label,
        }


# --------------------------------------------------------------------------
# Normalization helpers
# --------------------------------------------------------------------------


def normalize_context_id(context_id: Union[str, None]) -> str:
    raw = str(context_id or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "run": CONTEXT_RUN,
        "restart_run": CONTEXT_RUN,
        "session": CONTEXT_SESSION,
        "restart_session": CONTEXT_SESSION,
        "engine": CONTEXT_ENGINE,
        "restart_engine": CONTEXT_ENGINE,
        "workbench": CONTEXT_WORKBENCH,
        "restart_workbench": CONTEXT_WORKBENCH,
    }
    if raw not in aliases:
        raise ValueError(
            "unknown restart context %r — must be one of %s"
            % (context_id, list(RESTART_CONTEXT_IDS))
        )
    return aliases[raw]


def normalize_restart_reason(reason: Union[str, RestartReason]) -> str:
    if isinstance(reason, RestartReason):
        return reason.value
    raw = str(reason).strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "ok": RestartReason.OK.value,
        "capability_absent": RestartReason.CAPABILITY_ABSENT.value,
        "missing_capability": RestartReason.CAPABILITY_ABSENT.value,
        "no_target": RestartReason.NO_TARGET.value,
        "missing_target": RestartReason.NO_TARGET.value,
        "target_gone": RestartReason.TARGET_GONE.value,
        "process_gone": RestartReason.TARGET_GONE.value,
        "store_unreadable": RestartReason.STORE_UNREADABLE.value,
        "backing_store_unreadable": RestartReason.STORE_UNREADABLE.value,
        "empty_scope": RestartReason.EMPTY_SCOPE.value,
        "empty": RestartReason.EMPTY_SCOPE.value,
        "already_restarting": RestartReason.ALREADY_RESTARTING.value,
        "engine_unavailable": RestartReason.ENGINE_UNAVAILABLE.value,
    }
    if raw not in aliases:
        raise ValueError(
            "unknown restart reason %r — must be one of %s"
            % (reason, list(RESTART_REASONS))
        )
    return aliases[raw]


def restart_reason_named_state(
    reason: Union[str, RestartReason],
) -> NamedState:
    token = normalize_restart_reason(reason)
    return REASON_STATE[token]


# --------------------------------------------------------------------------
# Core restart execution
# --------------------------------------------------------------------------


def restart(
    context_id: str,
    *,
    subject: Optional[RestartSubject] = None,
    target_id: Optional[str] = None,
    inventory_row: Optional[InventoryRow] = None,
    capability_present: Optional[bool] = None,
    force_reason: Optional[Union[str, RestartReason]] = None,
    root: Optional[Path] = None,
) -> Union[RestartAction, CannotRestart]:
    """Generic restart entry for any enumerated context.

    Prefer the per-context wrappers (``restart_run`` / ``restart_session`` /
    ``restart_engine`` / ``restart_workbench``) at call sites.
    """
    cid = normalize_context_id(context_id)
    contract = RESTART_CONTRACTS[cid]
    tid = str(
        target_id
        if target_id is not None
        else (subject.target_id if subject is not None else "")
        or ""
    ).strip()

    if force_reason is not None:
        reason = normalize_restart_reason(force_reason)
        if reason == RestartReason.OK.value:
            # Force-ok still needs a subject to apply the contract.
            subj = subject or make_subject(cid, target_id=tid or "forced-target")
            return _execute_restart(cid, contract, subj, tid or subj.target_id)
        return CannotRestart(
            context_id=cid,
            reason=reason,
            detail=REASON_LABELS.get(reason, reason),
            target_id=tid,
            scope_name=contract.scope_name,
            control_id=contract.control_id,
        )

    cap_ok = _capability_ok(inventory_row, capability_present, root=root)
    if not cap_ok:
        return CannotRestart(
            context_id=cid,
            reason=RestartReason.CAPABILITY_ABSENT.value,
            detail=REASON_LABELS[RestartReason.CAPABILITY_ABSENT.value],
            target_id=tid,
            scope_name=contract.scope_name,
            control_id=contract.control_id,
        )

    subj = subject if subject is not None else make_subject(cid, target_id=tid)

    if subj.store_unreadable:
        return CannotRestart(
            context_id=cid,
            reason=RestartReason.STORE_UNREADABLE.value,
            detail=REASON_LABELS[RestartReason.STORE_UNREADABLE.value],
            target_id=tid or subj.target_id,
            scope_name=contract.scope_name,
            control_id=contract.control_id,
        )
    if subj.empty_scope:
        return CannotRestart(
            context_id=cid,
            reason=RestartReason.EMPTY_SCOPE.value,
            detail=REASON_LABELS[RestartReason.EMPTY_SCOPE.value],
            target_id=tid or subj.target_id,
            scope_name=contract.scope_name,
            control_id=contract.control_id,
        )
    if subj.target_gone:
        return CannotRestart(
            context_id=cid,
            reason=RestartReason.TARGET_GONE.value,
            detail=REASON_LABELS[RestartReason.TARGET_GONE.value],
            target_id=tid or subj.target_id,
            scope_name=contract.scope_name,
            control_id=contract.control_id,
        )
    if subj.already_restarting:
        return CannotRestart(
            context_id=cid,
            reason=RestartReason.ALREADY_RESTARTING.value,
            detail=REASON_LABELS[RestartReason.ALREADY_RESTARTING.value],
            target_id=tid or subj.target_id,
            scope_name=contract.scope_name,
            control_id=contract.control_id,
        )
    if subj.engine_unavailable and cid == CONTEXT_ENGINE:
        return CannotRestart(
            context_id=cid,
            reason=RestartReason.ENGINE_UNAVAILABLE.value,
            detail=REASON_LABELS[RestartReason.ENGINE_UNAVAILABLE.value],
            target_id=tid or subj.target_id,
            scope_name=contract.scope_name,
            control_id=contract.control_id,
        )

    effective_tid = tid or str(subj.target_id or "").strip()
    if not effective_tid:
        return CannotRestart(
            context_id=cid,
            reason=RestartReason.NO_TARGET.value,
            detail=REASON_LABELS[RestartReason.NO_TARGET.value],
            target_id="",
            scope_name=contract.scope_name,
            control_id=contract.control_id,
        )

    return _execute_restart(cid, contract, subj, effective_tid)


def restart_run(
    *,
    subject: Optional[RestartSubject] = None,
    target_id: Optional[str] = None,
    inventory_row: Optional[InventoryRow] = None,
    capability_present: Optional[bool] = None,
    force_reason: Optional[Union[str, RestartReason]] = None,
    root: Optional[Path] = None,
) -> Union[RestartAction, CannotRestart]:
    """Restart entry point — **run** context only."""
    return restart(
        CONTEXT_RUN,
        subject=subject,
        target_id=target_id,
        inventory_row=inventory_row,
        capability_present=capability_present,
        force_reason=force_reason,
        root=root,
    )


def restart_session(
    *,
    subject: Optional[RestartSubject] = None,
    target_id: Optional[str] = None,
    inventory_row: Optional[InventoryRow] = None,
    capability_present: Optional[bool] = None,
    force_reason: Optional[Union[str, RestartReason]] = None,
    root: Optional[Path] = None,
) -> Union[RestartAction, CannotRestart]:
    """Restart entry point — **session** context only."""
    return restart(
        CONTEXT_SESSION,
        subject=subject,
        target_id=target_id,
        inventory_row=inventory_row,
        capability_present=capability_present,
        force_reason=force_reason,
        root=root,
    )


def restart_engine(
    *,
    subject: Optional[RestartSubject] = None,
    target_id: Optional[str] = None,
    inventory_row: Optional[InventoryRow] = None,
    capability_present: Optional[bool] = None,
    force_reason: Optional[Union[str, RestartReason]] = None,
    root: Optional[Path] = None,
) -> Union[RestartAction, CannotRestart]:
    """Restart entry point — **engine** context only."""
    return restart(
        CONTEXT_ENGINE,
        subject=subject,
        target_id=target_id,
        inventory_row=inventory_row,
        capability_present=capability_present,
        force_reason=force_reason,
        root=root,
    )


def restart_workbench(
    *,
    subject: Optional[RestartSubject] = None,
    target_id: Optional[str] = None,
    inventory_row: Optional[InventoryRow] = None,
    capability_present: Optional[bool] = None,
    force_reason: Optional[Union[str, RestartReason]] = None,
    root: Optional[Path] = None,
) -> Union[RestartAction, CannotRestart]:
    """Restart entry point — **workbench** context only."""
    return restart(
        CONTEXT_WORKBENCH,
        subject=subject,
        target_id=target_id,
        inventory_row=inventory_row,
        capability_present=capability_present,
        force_reason=force_reason,
        root=root,
    )


#: One entry point per enumerated context (plan deliverable).
ENTRY_POINTS: Dict[str, Any] = {
    CONTEXT_RUN: restart_run,
    CONTEXT_SESSION: restart_session,
    CONTEXT_ENGINE: restart_engine,
    CONTEXT_WORKBENCH: restart_workbench,
}


def entry_point_for(context_id: str):
    """Return the restart callable for *context_id*."""
    return ENTRY_POINTS[normalize_context_id(context_id)]


# --------------------------------------------------------------------------
# Contract application
# --------------------------------------------------------------------------


def _execute_restart(
    context_id: str,
    contract: PreservedLostContract,
    subject: RestartSubject,
    target_id: str,
) -> RestartAction:
    """Apply the written preserved/lost contract to *subject* and return action."""
    before = subject.snapshot()
    after = dict(before)
    lost_values: Dict[str, Any] = {}
    preserved_values: Dict[str, Any] = {}

    # Clear every lost field per the written contract.
    for name in contract.lost:
        lost_values[name] = after.get(name)
        after[name] = _cleared_value(name)
        _apply_clear_to_subject(subject, name)

    # Capture preserved values (must remain present).
    for name in contract.preserved:
        preserved_values[name] = after.get(name)
        # If somehow cleared, restore from before (contract invariant).
        if not _is_present(after.get(name)) and _is_present(before.get(name)):
            after[name] = before.get(name)
            preserved_values[name] = after[name]

    return RestartAction(
        context_id=context_id,
        scope_name=contract.scope_name,
        control_id=contract.control_id,
        control_label=contract.control_label,
        contract_line=contract.contract_line,
        preserved=contract.preserved,
        lost=contract.lost,
        target_id=target_id,
        before_state=before,
        after_state=after,
        preserved_values=preserved_values,
        lost_values=lost_values,
        requires_scope_confirmation=contract.requires_scope_confirmation,
    )


def assert_outcome_matches_contract(
    action: RestartAction,
    *,
    contract: Optional[PreservedLostContract] = None,
) -> None:
    """Raise ``AssertionError`` if actual preserved/lost ≠ written contract.

    Used by the wave gate test (GWT: transcript present, tool calls absent).
    """
    c = contract or RESTART_CONTRACTS[action.context_id]
    if action.contract_line != c.contract_line:
        raise AssertionError(
            "restart contract_line mismatch for %s: got %r expected %r"
            % (action.context_id, action.contract_line, c.contract_line)
        )
    for name in c.preserved:
        if not action.field_present_after(name):
            raise AssertionError(
                "contract requires %r preserved for context %s, but after_state "
                "has it absent (value=%r); contract_line=%r"
                % (name, action.context_id, action.after_state.get(name), c.contract_line)
            )
    for name in c.lost:
        if not action.field_absent_after(name):
            raise AssertionError(
                "contract requires %r lost for context %s, but after_state "
                "still has it present (value=%r); contract_line=%r"
                % (name, action.context_id, action.after_state.get(name), c.contract_line)
            )


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


def _is_present(val: Any) -> bool:
    if val is None:
        return False
    if val is False:
        return False
    if isinstance(val, (str, bytes)):
        return bool(val)
    if isinstance(val, (list, tuple, set, dict)):
        return len(val) > 0
    return True


def _cleared_value(name: str) -> Any:
    """Canonical cleared value for a lost field name."""
    if name in (
        "running_tool_calls",
        "workspace_files",
        "open_panels",
        "live_terminal_attachments",
        "persisted_documents",
    ):
        return []
    if name in (
        "live_pty",
    ):
        return False
    if name in (
        "in_memory_engine_state",
        "ephemeral_ui_state",
        "session_record",
        "project_registry",
    ):
        return None
    return None


def _apply_clear_to_subject(subject: RestartSubject, name: str) -> None:
    """Mutate subject so lost fields are actually cleared (not only snapshot)."""
    cleared = _cleared_value(name)
    if hasattr(subject, name):
        setattr(subject, name, cleared)


__all__ = [
    "WAVE_ID",
    "SURFACE_ID",
    "CONTEXT_RUN",
    "CONTEXT_SESSION",
    "CONTEXT_ENGINE",
    "CONTEXT_WORKBENCH",
    "RESTART_CONTEXT_IDS",
    "CONTROL_ID_BY_CONTEXT",
    "SCOPE_NAME_BY_CONTEXT",
    "CONTROL_LABEL_BY_CONTEXT",
    "PreservedLostContract",
    "RESTART_CONTRACTS",
    "get_contract",
    "all_contracts",
    "RestartReason",
    "RESTART_REASONS",
    "INDUCED_FAULT_REASONS",
    "REASON_LABELS",
    "REASON_STATE",
    "RestartSubject",
    "make_subject",
    "RestartAction",
    "CannotRestart",
    "normalize_context_id",
    "normalize_restart_reason",
    "restart_reason_named_state",
    "restart",
    "restart_run",
    "restart_session",
    "restart_engine",
    "restart_workbench",
    "ENTRY_POINTS",
    "entry_point_for",
    "assert_outcome_matches_contract",
]
