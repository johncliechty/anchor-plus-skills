"""Open path — W10, Phase 3.

Returns opened work or ``CannotOpen(reason)`` with reasons enumerated:

* ``no_such_project``
* ``project_store_unreadable``
* ``workspace_locked``
* ``capability_absent``

Store-unreadable is **unknown** (not empty). A legitimately empty project
list is **empty**. Those two must never collapse (North Star: unknown ≠ empty).

Capability absence is decided by the dead-control inventory contract (W3/W5);
this module still enumerates ``capability_absent`` so handlers and traces can
name the reason when the control path is invoked without authorization.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Union

from anchor.ui.named_state import NamedState
from tools.capability_inventory import InventoryRow, may_authorize_live_control

# --------------------------------------------------------------------------
# Reasons (exhaustive for open)
# --------------------------------------------------------------------------


class OpenReason(str, Enum):
    """Enumerated cannot-open reasons (frozen plan — W10)."""

    NO_SUCH_PROJECT = "no_such_project"
    PROJECT_STORE_UNREADABLE = "project_store_unreadable"
    WORKSPACE_LOCKED = "workspace_locked"
    CAPABILITY_ABSENT = "capability_absent"


OPEN_REASONS: tuple = tuple(r.value for r in OpenReason)

#: User-facing reason labels (surface-native open language).
OPEN_REASON_LABELS: Dict[str, str] = {
    OpenReason.NO_SUCH_PROJECT.value: "no such project",
    OpenReason.PROJECT_STORE_UNREADABLE.value: "project store unreadable",
    OpenReason.WORKSPACE_LOCKED.value: "workspace locked",
    OpenReason.CAPABILITY_ABSENT.value: "open capability absent",
}

#: NamedState each reason renders as (unknown ≠ empty ≠ cannot_open).
OPEN_REASON_STATE: Dict[str, NamedState] = {
    # No such project is a named cannot-open (target missing), not empty list.
    OpenReason.NO_SUCH_PROJECT.value: NamedState.cannot_open,
    # Store unreadable → unknown (did not successfully read). NEVER empty.
    OpenReason.PROJECT_STORE_UNREADABLE.value: NamedState.unknown,
    OpenReason.WORKSPACE_LOCKED.value: NamedState.cannot_open,
    OpenReason.CAPABILITY_ABSENT.value: NamedState.cannot_open,
}


# --------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class OpenedWork:
    """Successfully opened work for one project."""

    project_id: str
    label: str = ""
    path: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return True

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "project_id": self.project_id,
            "label": self.label,
            "path": self.path,
            "meta": dict(self.meta),
        }


@dataclass(frozen=True)
class CannotOpen:
    """Open refused with a named reason and NamedState."""

    reason: str
    detail: str = ""
    project_id: str = ""

    @property
    def ok(self) -> bool:
        return False

    @property
    def named_state(self) -> NamedState:
        return OPEN_REASON_STATE.get(self.reason, NamedState.cannot_open)

    @property
    def label(self) -> str:
        return OPEN_REASON_LABELS.get(self.reason, self.reason)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": False,
            "reason": self.reason,
            "detail": self.detail,
            "project_id": self.project_id,
            "named_state": self.named_state.value,
            "label": self.label,
        }


# --------------------------------------------------------------------------
# Project store protocol (injectable; tests supply fixtures)
# --------------------------------------------------------------------------


class ProjectStoreError(Exception):
    """Raised by a store when the backing store cannot be read."""


class WorkspaceLockedError(Exception):
    """Raised when the workspace is locked against open."""


@dataclass
class ProjectRecord:
    """One project row from an open store."""

    project_id: str
    label: str = ""
    path: str = ""
    locked: bool = False
    meta: Dict[str, Any] = field(default_factory=dict)


class ProjectStore:
    """Minimal injectable project store for the open path.

    Production wiring may replace this; the contract is:

    * ``list_projects()`` raises ``ProjectStoreError`` when unreadable
    * ``get(project_id)`` returns None when the id is absent
    * ``get`` may also raise ``ProjectStoreError`` / ``WorkspaceLockedError``
    """

    def __init__(
        self,
        projects: Optional[Sequence[Union[ProjectRecord, Mapping[str, Any]]]] = None,
        *,
        unreadable: bool = False,
        locked_ids: Optional[Iterable[str]] = None,
    ) -> None:
        self._unreadable = bool(unreadable)
        self._locked = set(locked_ids or ())
        self._projects: Dict[str, ProjectRecord] = {}
        for p in projects or ():
            rec = _as_record(p)
            self._projects[rec.project_id] = rec
            if rec.locked:
                self._locked.add(rec.project_id)

    def list_projects(self) -> List[ProjectRecord]:
        if self._unreadable:
            raise ProjectStoreError("project store unreadable")
        return list(self._projects.values())

    def get(self, project_id: str) -> Optional[ProjectRecord]:
        if self._unreadable:
            raise ProjectStoreError("project store unreadable")
        pid = str(project_id).strip()
        if pid in self._locked:
            raise WorkspaceLockedError("workspace locked for %s" % pid)
        return self._projects.get(pid)


def empty_store() -> ProjectStore:
    """Legitimately empty project list (empty, not unknown)."""
    return ProjectStore(projects=[])


def unreadable_store() -> ProjectStore:
    """Store that fails every read (unknown, not empty)."""
    return ProjectStore(unreadable=True)


# --------------------------------------------------------------------------
# open_work
# --------------------------------------------------------------------------


def normalize_open_reason(reason: Union[str, OpenReason]) -> str:
    if isinstance(reason, OpenReason):
        return reason.value
    raw = str(reason).strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "no_such_project": OpenReason.NO_SUCH_PROJECT.value,
        "nosuchproject": OpenReason.NO_SUCH_PROJECT.value,
        "missing_project": OpenReason.NO_SUCH_PROJECT.value,
        "project_store_unreadable": OpenReason.PROJECT_STORE_UNREADABLE.value,
        "store_unreadable": OpenReason.PROJECT_STORE_UNREADABLE.value,
        "backing_store_unreadable": OpenReason.PROJECT_STORE_UNREADABLE.value,
        "workspace_locked": OpenReason.WORKSPACE_LOCKED.value,
        "locked": OpenReason.WORKSPACE_LOCKED.value,
        "capability_absent": OpenReason.CAPABILITY_ABSENT.value,
        "missing_capability": OpenReason.CAPABILITY_ABSENT.value,
        "capability_missing": OpenReason.CAPABILITY_ABSENT.value,
    }
    if raw not in aliases:
        raise ValueError(
            "unknown open reason %r — must be one of %s" % (reason, list(OPEN_REASONS))
        )
    return aliases[raw]


def open_work(
    project_id: Optional[str] = None,
    *,
    store: Optional[ProjectStore] = None,
    inventory_row: Optional[InventoryRow] = None,
    capability_present: Optional[bool] = None,
    force_reason: Optional[Union[str, OpenReason]] = None,
    root: Optional[Path] = None,
) -> Union[OpenedWork, CannotOpen]:
    """Open one project or return ``CannotOpen`` with an enumerated reason.

    Authorization:

    * If ``capability_present`` is False, or ``inventory_row`` fails
      ``may_authorize_live_control``, return ``capability_absent``.
    * If ``force_reason`` is set (fault injection / tests), return that
      CannotOpen without further store I/O.
    * Otherwise consult ``store`` (default: empty store).
    """
    if force_reason is not None:
        reason = normalize_open_reason(force_reason)
        return CannotOpen(
            reason=reason,
            detail=OPEN_REASON_LABELS.get(reason, reason),
            project_id=str(project_id or ""),
        )

    # Capability gate.
    cap_ok = _capability_ok(inventory_row, capability_present, root=root)
    if not cap_ok:
        return CannotOpen(
            reason=OpenReason.CAPABILITY_ABSENT.value,
            detail=OPEN_REASON_LABELS[OpenReason.CAPABILITY_ABSENT.value],
            project_id=str(project_id or ""),
        )

    proj_store = store if store is not None else empty_store()

    # No project id → list path: empty vs unreadable.
    if project_id is None or str(project_id).strip() == "":
        try:
            projects = proj_store.list_projects()
        except ProjectStoreError:
            return CannotOpen(
                reason=OpenReason.PROJECT_STORE_UNREADABLE.value,
                detail=OPEN_REASON_LABELS[
                    OpenReason.PROJECT_STORE_UNREADABLE.value
                ],
            )
        if not projects:
            # Legitimate empty list is not CannotOpen — callers that render
            # the project list use NamedState.empty. For open_work with no
            # target, treat as no_such_project only when a specific id was
            # requested; bare open with empty list returns a sentinel.
            return CannotOpen(
                reason=OpenReason.NO_SUCH_PROJECT.value,
                detail="no projects in scope",
            )
        # Ambiguous multi-project open without id → no_such_project.
        return CannotOpen(
            reason=OpenReason.NO_SUCH_PROJECT.value,
            detail="project id required",
        )

    pid = str(project_id).strip()
    try:
        rec = proj_store.get(pid)
    except ProjectStoreError:
        return CannotOpen(
            reason=OpenReason.PROJECT_STORE_UNREADABLE.value,
            detail=OPEN_REASON_LABELS[OpenReason.PROJECT_STORE_UNREADABLE.value],
            project_id=pid,
        )
    except WorkspaceLockedError as exc:
        return CannotOpen(
            reason=OpenReason.WORKSPACE_LOCKED.value,
            detail=str(exc) or OPEN_REASON_LABELS[OpenReason.WORKSPACE_LOCKED.value],
            project_id=pid,
        )

    if rec is None:
        return CannotOpen(
            reason=OpenReason.NO_SUCH_PROJECT.value,
            detail=OPEN_REASON_LABELS[OpenReason.NO_SUCH_PROJECT.value],
            project_id=pid,
        )
    if rec.locked or pid in getattr(proj_store, "_locked", ()):
        return CannotOpen(
            reason=OpenReason.WORKSPACE_LOCKED.value,
            detail=OPEN_REASON_LABELS[OpenReason.WORKSPACE_LOCKED.value],
            project_id=pid,
        )

    return OpenedWork(
        project_id=rec.project_id,
        label=rec.label or rec.project_id,
        path=rec.path,
        meta=dict(rec.meta),
    )


def list_projects_state(
    store: Optional[ProjectStore] = None,
) -> NamedState:
    """Trichotomy for the project list surface: empty vs unknown.

    * store unreadable → ``NamedState.unknown``
    * store readable and zero projects → ``NamedState.empty``
    * store readable with projects → ``NamedState.ok``
    """
    proj_store = store if store is not None else empty_store()
    try:
        projects = proj_store.list_projects()
    except ProjectStoreError:
        return NamedState.unknown
    if not projects:
        return NamedState.empty
    return NamedState.ok


def open_reason_named_state(reason: Union[str, OpenReason]) -> NamedState:
    """Map an open reason to its surface NamedState."""
    token = normalize_open_reason(reason)
    return OPEN_REASON_STATE[token]


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
        # No inventory and no explicit flag → not authorized (fail closed).
        return False
    return may_authorize_live_control(inventory_row, root=root)


def _as_record(p: Union[ProjectRecord, Mapping[str, Any]]) -> ProjectRecord:
    if isinstance(p, ProjectRecord):
        return p
    return ProjectRecord(
        project_id=str(p.get("project_id") or p.get("id") or "").strip(),
        label=str(p.get("label") or p.get("name") or ""),
        path=str(p.get("path") or ""),
        locked=bool(p.get("locked", False)),
        meta=dict(p.get("meta") or {}),
    )


__all__ = [
    "OPEN_REASONS",
    "OPEN_REASON_LABELS",
    "OPEN_REASON_STATE",
    "OpenReason",
    "OpenedWork",
    "CannotOpen",
    "ProjectStoreError",
    "WorkspaceLockedError",
    "ProjectRecord",
    "ProjectStore",
    "empty_store",
    "unreadable_store",
    "normalize_open_reason",
    "open_work",
    "list_projects_state",
    "open_reason_named_state",
]
