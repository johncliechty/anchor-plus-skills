"""Session attach path — W11, Phase 3.

Timeout path classified as ``NamedState.timeout``, distinct from
``unknown_session``. Single error emission (double-print regression killed
at the handler/result layer by carrying one named state + one label).

``retry_contract`` returns a viable re-issue action or ``CannotRetry(reason)``;
the Retry control is not rendered when neither exists (the view hides rather
than emit a dead control).

Induced-fault reasons (frozen plan GWT + gate):

* ``timeout`` — attach exceeded the attach timeout
* ``unknown_session`` — session id absent / store could not name the session
* ``empty_session_list`` — list read succeeded and there are no sessions
* ``process_gone`` — underlying process is gone; retry is not viable
* ``capability_absent`` — attach/retry capability not authorized

Empty session list vs unreadable list (unknown) never collapse
(North Star: unknown ≠ empty).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Union

from anchor.ui.named_state import NamedState
from tools.capability_inventory import InventoryRow, may_authorize_live_control

# --------------------------------------------------------------------------
# Reasons (exhaustive for attach / retry)
# --------------------------------------------------------------------------


class AttachReason(str, Enum):
    """Enumerated attach / cannot-attach reasons (frozen plan — W11)."""

    TIMEOUT = "timeout"
    UNKNOWN_SESSION = "unknown_session"
    EMPTY_SESSION_LIST = "empty_session_list"
    PROCESS_GONE = "process_gone"
    CAPABILITY_ABSENT = "capability_absent"
    SESSION_STORE_UNREADABLE = "session_store_unreadable"


ATTACH_REASONS: tuple = tuple(r.value for r in AttachReason)

#: Fault-injection reasons named by the W11 gate (one induced fault each).
INDUCED_FAULT_REASONS: tuple = (
    AttachReason.TIMEOUT.value,
    AttachReason.UNKNOWN_SESSION.value,
    AttachReason.EMPTY_SESSION_LIST.value,
)

#: User-facing reason labels (surface-native attach language).
ATTACH_REASON_LABELS: Dict[str, str] = {
    AttachReason.TIMEOUT.value: "attach timed out",
    AttachReason.UNKNOWN_SESSION.value: "unknown session",
    AttachReason.EMPTY_SESSION_LIST.value: "empty session list",
    AttachReason.PROCESS_GONE.value: "session process gone",
    AttachReason.CAPABILITY_ABSENT.value: "attach capability absent",
    AttachReason.SESSION_STORE_UNREADABLE.value: "session store unreadable",
}

#: NamedState each reason renders as (timeout ≠ unknown; empty ≠ unknown).
ATTACH_REASON_STATE: Dict[str, NamedState] = {
    AttachReason.TIMEOUT.value: NamedState.timeout,
    # Unknown session / unreadable store → unknown (NEVER empty, NEVER timeout).
    AttachReason.UNKNOWN_SESSION.value: NamedState.unknown,
    AttachReason.SESSION_STORE_UNREADABLE.value: NamedState.unknown,
    # Legitimate empty list → empty (NEVER unknown).
    AttachReason.EMPTY_SESSION_LIST.value: NamedState.empty,
    # Process gone / capability absent → cannot_retry (retry not viable).
    AttachReason.PROCESS_GONE.value: NamedState.cannot_retry,
    AttachReason.CAPABILITY_ABSENT.value: NamedState.cannot_retry,
}

#: Reasons for which Retry is viable (re-issue attach).
RETRY_VIABLE_REASONS: frozenset = frozenset(
    {
        AttachReason.TIMEOUT.value,
    }
)

#: Reasons that force a named cannot-retry (no Retry control).
CANNOT_RETRY_REASONS: frozenset = frozenset(
    {
        AttachReason.PROCESS_GONE.value,
        AttachReason.UNKNOWN_SESSION.value,
        AttachReason.EMPTY_SESSION_LIST.value,
        AttachReason.CAPABILITY_ABSENT.value,
        AttachReason.SESSION_STORE_UNREADABLE.value,
    }
)


# --------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class AttachedSession:
    """Successfully attached session."""

    session_id: str
    label: str = ""
    process_alive: bool = True
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return True

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "session_id": self.session_id,
            "label": self.label,
            "process_alive": self.process_alive,
            "meta": dict(self.meta),
        }


@dataclass(frozen=True)
class CannotAttach:
    """Attach refused with a named reason and NamedState.

    Carries a single ``error_text`` so the view emits the failure **once**
    (double-print regression killed — no second channel invents a second
    copy of the same user-visible string).
    """

    reason: str
    detail: str = ""
    session_id: str = ""
    process_alive: bool = False

    @property
    def ok(self) -> bool:
        return False

    @property
    def named_state(self) -> NamedState:
        return ATTACH_REASON_STATE.get(self.reason, NamedState.unknown)

    @property
    def label(self) -> str:
        return ATTACH_REASON_LABELS.get(self.reason, self.reason)

    @property
    def error_text(self) -> str:
        """The single user-visible error string for this failure.

        Equals the NamedState label so render_state is the one emission
        channel; callers must not re-print this string beside render_state.
        """
        return self.named_state.label

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": False,
            "reason": self.reason,
            "detail": self.detail,
            "session_id": self.session_id,
            "process_alive": self.process_alive,
            "named_state": self.named_state.value,
            "label": self.label,
            "error_text": self.error_text,
        }


# --------------------------------------------------------------------------
# Retry contract
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class RetryAction:
    """A viable re-issue action for the Retry control."""

    action: str
    session_id: str = ""
    reason: str = ""
    detail: str = ""

    @property
    def ok(self) -> bool:
        return True

    @property
    def viable(self) -> bool:
        return True

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "viable": True,
            "action": self.action,
            "session_id": self.session_id,
            "reason": self.reason,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class CannotRetry:
    """Retry is not viable — named cannot-retry with a reason."""

    reason: str
    detail: str = ""
    session_id: str = ""

    @property
    def ok(self) -> bool:
        return False

    @property
    def viable(self) -> bool:
        return False

    @property
    def named_state(self) -> NamedState:
        return NamedState.cannot_retry

    @property
    def label(self) -> str:
        return ATTACH_REASON_LABELS.get(self.reason, self.reason)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": False,
            "viable": False,
            "reason": self.reason,
            "detail": self.detail,
            "session_id": self.session_id,
            "named_state": self.named_state.value,
            "label": self.label,
        }


def retry_contract(
    attach_result: Optional[Union[AttachedSession, CannotAttach]] = None,
    *,
    reason: Optional[Union[str, AttachReason]] = None,
    session_id: str = "",
    process_alive: Optional[bool] = None,
) -> Union[RetryAction, CannotRetry]:
    """Return a viable re-issue action or ``CannotRetry(reason)``.

    Rules (frozen plan):

    * timeout with a still-alive process → ``RetryAction`` re-issuing attach
    * process gone → ``CannotRetry(process_gone)`` — no Retry control
    * unknown session / empty list / capability absent / unreadable store →
      ``CannotRetry`` with that reason
    * success attach → no retry needed → ``CannotRetry`` with reason
      ``not_applicable`` is avoided; success returns ``CannotRetry`` with
      reason ``process_gone`` only when process is dead, else a RetryAction
      is not shown for success (view hides Retry when attach ok)

    The control is **not rendered** when the view receives ``CannotRetry``
    (named state instead) or when attach succeeded (no Retry slot).
    """
    # Resolve reason + session + process liveness from the attach result.
    rsn = ""
    sid = str(session_id or "")
    alive: Optional[bool] = process_alive

    if attach_result is not None:
        if isinstance(attach_result, AttachedSession):
            # Successful attach — Retry is not shown (no error to re-issue).
            return CannotRetry(
                reason=AttachReason.PROCESS_GONE.value
                if not attach_result.process_alive
                else AttachReason.CAPABILITY_ABSENT.value,
                detail="attach succeeded — retry not applicable",
                session_id=attach_result.session_id,
            )
        if isinstance(attach_result, CannotAttach):
            rsn = attach_result.reason
            sid = sid or attach_result.session_id
            if alive is None:
                alive = attach_result.process_alive

    if reason is not None:
        rsn = normalize_attach_reason(reason)

    if not rsn:
        # No context → cannot retry (fail closed; no dead Retry).
        return CannotRetry(
            reason=AttachReason.CAPABILITY_ABSENT.value,
            detail="no attach context for retry",
            session_id=sid,
        )

    rsn = normalize_attach_reason(rsn)

    # Process gone always wins — even if last failure was timeout.
    if rsn == AttachReason.PROCESS_GONE.value or alive is False:
        return CannotRetry(
            reason=AttachReason.PROCESS_GONE.value,
            detail=ATTACH_REASON_LABELS[AttachReason.PROCESS_GONE.value],
            session_id=sid,
        )

    if rsn in RETRY_VIABLE_REASONS:
        # Timeout (and process still alive / unknown) → re-issue attach.
        act = "action:attach"
        if sid:
            act = "action:attach:%s" % sid
        return RetryAction(
            action=act,
            session_id=sid,
            reason=rsn,
            detail="re-issue attach after %s" % rsn,
        )

    # All other named reasons → CannotRetry (no dead control).
    return CannotRetry(
        reason=rsn,
        detail=ATTACH_REASON_LABELS.get(rsn, rsn),
        session_id=sid,
    )


# --------------------------------------------------------------------------
# Injectable session store
# --------------------------------------------------------------------------


class SessionStoreError(Exception):
    """Raised when the session store cannot be read."""


class AttachTimeoutError(Exception):
    """Raised when attach exceeds the attach timeout."""


class ProcessGoneError(Exception):
    """Raised when the underlying session process is gone."""


@dataclass
class SessionRecord:
    """One session row from the attach store."""

    session_id: str
    label: str = ""
    process_alive: bool = True
    meta: Dict[str, Any] = field(default_factory=dict)


class SessionStore:
    """Minimal injectable session store for the attach path.

    Contract:

    * ``list_sessions()`` raises ``SessionStoreError`` when unreadable
    * ``get(session_id)`` returns None when the id is absent
    * ``attach(session_id)`` may raise ``AttachTimeoutError`` /
      ``ProcessGoneError`` / ``SessionStoreError``
    """

    def __init__(
        self,
        sessions: Optional[Sequence[Union[SessionRecord, Mapping[str, Any]]]] = None,
        *,
        unreadable: bool = False,
        timeout_ids: Optional[Iterable[str]] = None,
        gone_ids: Optional[Iterable[str]] = None,
    ) -> None:
        self._unreadable = bool(unreadable)
        self._timeout = set(str(x) for x in (timeout_ids or ()))
        self._gone = set(str(x) for x in (gone_ids or ()))
        self._sessions: Dict[str, SessionRecord] = {}
        for s in sessions or ():
            rec = _as_record(s)
            self._sessions[rec.session_id] = rec
            if not rec.process_alive:
                self._gone.add(rec.session_id)

    def list_sessions(self) -> List[SessionRecord]:
        if self._unreadable:
            raise SessionStoreError("session store unreadable")
        return list(self._sessions.values())

    def get(self, session_id: str) -> Optional[SessionRecord]:
        if self._unreadable:
            raise SessionStoreError("session store unreadable")
        return self._sessions.get(str(session_id).strip())

    def attach(self, session_id: str) -> SessionRecord:
        if self._unreadable:
            raise SessionStoreError("session store unreadable")
        sid = str(session_id).strip()
        if sid in self._timeout:
            raise AttachTimeoutError("attach timed out for %s" % sid)
        if sid in self._gone:
            raise ProcessGoneError("session process gone for %s" % sid)
        rec = self._sessions.get(sid)
        if rec is None:
            return None  # type: ignore[return-value]
        if not rec.process_alive:
            raise ProcessGoneError("session process gone for %s" % sid)
        return rec


def empty_session_store() -> SessionStore:
    """Legitimately empty session list (empty, not unknown)."""
    return SessionStore(sessions=[])


def unreadable_session_store() -> SessionStore:
    """Store that fails every read (unknown, not empty)."""
    return SessionStore(unreadable=True)


# --------------------------------------------------------------------------
# attach_session
# --------------------------------------------------------------------------


def normalize_attach_reason(reason: Union[str, AttachReason]) -> str:
    if isinstance(reason, AttachReason):
        return reason.value
    raw = str(reason).strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "timeout": AttachReason.TIMEOUT.value,
        "attach_timeout": AttachReason.TIMEOUT.value,
        "timed_out": AttachReason.TIMEOUT.value,
        "unknown_session": AttachReason.UNKNOWN_SESSION.value,
        "unknown": AttachReason.UNKNOWN_SESSION.value,
        "session_unknown": AttachReason.UNKNOWN_SESSION.value,
        "empty_session_list": AttachReason.EMPTY_SESSION_LIST.value,
        "empty": AttachReason.EMPTY_SESSION_LIST.value,
        "empty_sessions": AttachReason.EMPTY_SESSION_LIST.value,
        "process_gone": AttachReason.PROCESS_GONE.value,
        "gone": AttachReason.PROCESS_GONE.value,
        "process_dead": AttachReason.PROCESS_GONE.value,
        "capability_absent": AttachReason.CAPABILITY_ABSENT.value,
        "missing_capability": AttachReason.CAPABILITY_ABSENT.value,
        "capability_missing": AttachReason.CAPABILITY_ABSENT.value,
        "session_store_unreadable": AttachReason.SESSION_STORE_UNREADABLE.value,
        "store_unreadable": AttachReason.SESSION_STORE_UNREADABLE.value,
        "backing_store_unreadable": AttachReason.SESSION_STORE_UNREADABLE.value,
    }
    if raw not in aliases:
        raise ValueError(
            "unknown attach reason %r — must be one of %s"
            % (reason, list(ATTACH_REASONS))
        )
    return aliases[raw]


def attach_session(
    session_id: Optional[str] = None,
    *,
    store: Optional[SessionStore] = None,
    inventory_row: Optional[InventoryRow] = None,
    capability_present: Optional[bool] = None,
    force_reason: Optional[Union[str, AttachReason]] = None,
    root: Optional[Path] = None,
    attach_timeout_s: Optional[float] = None,
) -> Union[AttachedSession, CannotAttach]:
    """Attach to one session or return ``CannotAttach`` with a named reason.

    * ``force_reason`` (fault injection) returns that CannotAttach without
      further store I/O.
    * Capability gate: absent → ``capability_absent``.
    * Timeout is classified as ``NamedState.timeout`` (never unknown_session).
    * Missing session id after a successful list read of zero sessions →
      ``empty_session_list``; missing id in a non-empty list / absent id →
      ``unknown_session``.
    """
    if force_reason is not None:
        reason = normalize_attach_reason(force_reason)
        alive = reason not in (
            AttachReason.PROCESS_GONE.value,
            AttachReason.EMPTY_SESSION_LIST.value,
            AttachReason.UNKNOWN_SESSION.value,
            AttachReason.SESSION_STORE_UNREADABLE.value,
            AttachReason.CAPABILITY_ABSENT.value,
        )
        # Timeout may still have a live process (retry viable).
        if reason == AttachReason.TIMEOUT.value:
            alive = True
        if reason == AttachReason.PROCESS_GONE.value:
            alive = False
        return CannotAttach(
            reason=reason,
            detail=ATTACH_REASON_LABELS.get(reason, reason),
            session_id=str(session_id or ""),
            process_alive=alive,
        )

    cap_ok = _capability_ok(inventory_row, capability_present, root=root)
    if not cap_ok:
        return CannotAttach(
            reason=AttachReason.CAPABILITY_ABSENT.value,
            detail=ATTACH_REASON_LABELS[AttachReason.CAPABILITY_ABSENT.value],
            session_id=str(session_id or ""),
            process_alive=False,
        )

    sess_store = store if store is not None else empty_session_store()

    # No session id → list path: empty vs unreadable.
    if session_id is None or str(session_id).strip() == "":
        try:
            sessions = sess_store.list_sessions()
        except SessionStoreError:
            return CannotAttach(
                reason=AttachReason.SESSION_STORE_UNREADABLE.value,
                detail=ATTACH_REASON_LABELS[
                    AttachReason.SESSION_STORE_UNREADABLE.value
                ],
                process_alive=False,
            )
        if not sessions:
            return CannotAttach(
                reason=AttachReason.EMPTY_SESSION_LIST.value,
                detail=ATTACH_REASON_LABELS[
                    AttachReason.EMPTY_SESSION_LIST.value
                ],
                process_alive=False,
            )
        return CannotAttach(
            reason=AttachReason.UNKNOWN_SESSION.value,
            detail="session id required",
            process_alive=False,
        )

    sid = str(session_id).strip()

    # Optional timeout bound (tests may set 0 to force timeout semantics via
    # store timeout_ids; a non-positive bound alone does not invent timeout
    # without store cooperation — force_reason is the fault-injection seam).
    _ = attach_timeout_s

    try:
        rec = sess_store.get(sid)
    except SessionStoreError:
        return CannotAttach(
            reason=AttachReason.SESSION_STORE_UNREADABLE.value,
            detail=ATTACH_REASON_LABELS[
                AttachReason.SESSION_STORE_UNREADABLE.value
            ],
            session_id=sid,
            process_alive=False,
        )

    if rec is None:
        return CannotAttach(
            reason=AttachReason.UNKNOWN_SESSION.value,
            detail=ATTACH_REASON_LABELS[AttachReason.UNKNOWN_SESSION.value],
            session_id=sid,
            process_alive=False,
        )

    try:
        attached = sess_store.attach(sid)
    except AttachTimeoutError as exc:
        return CannotAttach(
            reason=AttachReason.TIMEOUT.value,
            detail=str(exc) or ATTACH_REASON_LABELS[AttachReason.TIMEOUT.value],
            session_id=sid,
            process_alive=True,  # timeout ≠ process gone; retry may be viable
        )
    except ProcessGoneError as exc:
        return CannotAttach(
            reason=AttachReason.PROCESS_GONE.value,
            detail=str(exc)
            or ATTACH_REASON_LABELS[AttachReason.PROCESS_GONE.value],
            session_id=sid,
            process_alive=False,
        )
    except SessionStoreError:
        return CannotAttach(
            reason=AttachReason.SESSION_STORE_UNREADABLE.value,
            detail=ATTACH_REASON_LABELS[
                AttachReason.SESSION_STORE_UNREADABLE.value
            ],
            session_id=sid,
            process_alive=False,
        )

    if attached is None:
        return CannotAttach(
            reason=AttachReason.UNKNOWN_SESSION.value,
            detail=ATTACH_REASON_LABELS[AttachReason.UNKNOWN_SESSION.value],
            session_id=sid,
            process_alive=False,
        )

    return AttachedSession(
        session_id=attached.session_id,
        label=attached.label or attached.session_id,
        process_alive=attached.process_alive,
        meta=dict(attached.meta),
    )


def list_sessions_state(store: Optional[SessionStore] = None) -> NamedState:
    """Trichotomy for the session list surface: empty vs unknown.

    * store unreadable → ``NamedState.unknown``
    * store readable and zero sessions → ``NamedState.empty``
    * store readable with sessions → ``NamedState.ok``
    """
    sess_store = store if store is not None else empty_session_store()
    try:
        sessions = sess_store.list_sessions()
    except SessionStoreError:
        return NamedState.unknown
    if not sessions:
        return NamedState.empty
    return NamedState.ok


def attach_reason_named_state(reason: Union[str, AttachReason]) -> NamedState:
    """Map an attach reason to its surface NamedState."""
    token = normalize_attach_reason(reason)
    return ATTACH_REASON_STATE[token]


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


def _as_record(s: Union[SessionRecord, Mapping[str, Any]]) -> SessionRecord:
    if isinstance(s, SessionRecord):
        return s
    return SessionRecord(
        session_id=str(s.get("session_id") or s.get("id") or "").strip(),
        label=str(s.get("label") or s.get("name") or ""),
        process_alive=bool(s.get("process_alive", s.get("alive", True))),
        meta=dict(s.get("meta") or {}),
    )


__all__ = [
    "ATTACH_REASONS",
    "ATTACH_REASON_LABELS",
    "ATTACH_REASON_STATE",
    "INDUCED_FAULT_REASONS",
    "RETRY_VIABLE_REASONS",
    "CANNOT_RETRY_REASONS",
    "AttachReason",
    "AttachedSession",
    "CannotAttach",
    "RetryAction",
    "CannotRetry",
    "SessionStoreError",
    "AttachTimeoutError",
    "ProcessGoneError",
    "SessionRecord",
    "SessionStore",
    "empty_session_store",
    "unreadable_session_store",
    "normalize_attach_reason",
    "attach_session",
    "retry_contract",
    "list_sessions_state",
    "attach_reason_named_state",
]
