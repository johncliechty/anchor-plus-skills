"""Mid-flight RE-BRIEF in the audited mode — live channel, acknowledgment
receipt on the step, NO relaunch (steward-chamber W11, C7 — E7) — plus the
co-landed re-brief-during-sweep contention refusal.

**The audited mode (machine record: ``chamber/rebrief-channel-audit.json``,
loaded by :func:`load_channel_audit`):** the W2 inbox audit's outcome is
LIVE-WITH-RECEIPT — the commission runtime demonstrably HAS a live
message-into-session channel: a commissioned run IS a live terminal session
whose stdin accepts writes through the WIRED paced-PTY path
(``pty_manager.py :: write`` — wire-homing row ``paced_pty``, whose M1
consumer is literally "say-box talk path + re-brief writes"). Boundary mode
(the V2 John-HALT branch) was therefore never entered. This module DELIVERS
on that channel; it NEVER relaunches: no session-start call of any kind,
no kill, no re-seed — one paced write onto the LIVE session's stdin, then a
durable acknowledgment receipt on the step.

**The contention law (co-landed, re-run by W12):** a re-brief landing
DURING an active sweep — an unswept death stands, or the sweep card holds
the queue head unresolved — is REFUSED-AND-QUEUED with the named finding
:data:`FINDING_REBRIEF_DURING_SWEEP`: the text is parked durably
(``queued`` rows, :func:`queued_rebriefs`; :func:`flush_queued` delivers
after the sweep clears), never interleaved into the sweep's decision
window, and never dropped.

Failure states: store unreadable → named ``rebrief-store-unreadable``
(fails closed); gates store unreadable → the contention check fails CLOSED
(a re-brief never lands blind past a sweep it cannot see); dead/unknown
session → named ``session-not-live`` refusal (an honest refusal, not a
relaunch); delivery failure → named ``delivery-failed`` with no receipt
minted (a receipt asserts delivery, never intent).

Stdlib only; the ONLY writes are the chamber-sidecar store and the paced
PTY write through the wired seam. Zero spine writes, no model call.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import chamber_projections as _cp

SCHEMA = "anchor-chamber-rebrief-v1"

ANCHOR_ROOT = Path(__file__).resolve().parent

#: The committed machine-readable channel-audit outcome record.
CHANNEL_AUDIT_PATH = ANCHOR_ROOT / "chamber" / "rebrief-channel-audit.json"
CHANNEL_AUDIT_SCHEMA_VERSION = 1

REBRIEF_REL = os.path.join(_cp.CHAMBER_SIDECAR_REL, "rebrief.json")
REBRIEF_LOCK_REL = REBRIEF_REL + ".lock"

MODE_LIVE = "live-with-receipt"
MODE_BOUNDARY = "next-step-boundary"

#: Named findings / errors.
FINDING_REBRIEF_DURING_SWEEP = "W11-REBRIEF-DURING-SWEEP-QUEUED"
ERROR_STORE_UNREADABLE = "rebrief-store-unreadable"
ERROR_SESSION_NOT_LIVE = "session-not-live"
ERROR_DELIVERY_FAILED = "delivery-failed"
ERROR_EMPTY_TEXT = "empty-rebrief-text"

#: The delivered re-brief is framed so the running skill sees it as an
#: explicit mid-flight brief update, not ambient chatter.
REBRIEF_FRAME = "MID-FLIGHT RE-BRIEF (applies now — acknowledge in your " \
                "next status update):"


class RebriefStoreError(RuntimeError):
    def __init__(self, error: str, message: str):
        super().__init__(message)
        self.error = error


def store_path(folder) -> Path:
    return Path(folder) / REBRIEF_REL


def _lock_path(folder) -> Path:
    return Path(folder) / REBRIEF_LOCK_REL


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _empty_store() -> dict:
    return {"schema": SCHEMA, "receipts": [], "queued": []}


def _load(folder) -> dict:
    p = store_path(folder)
    if not p.exists():
        return _empty_store()
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise RebriefStoreError(
            ERROR_STORE_UNREADABLE,
            "rebrief store unreadable at %s: %s" % (REBRIEF_REL, exc))
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        raise RebriefStoreError(
            ERROR_STORE_UNREADABLE,
            "rebrief store carries no %r schema" % SCHEMA)
    doc.setdefault("receipts", [])
    doc.setdefault("queued", [])
    return doc


def _save(folder, doc: dict) -> None:
    _cp.atomic_write_json(store_path(folder), doc)


# ═════════════════════════════════════════════════════════════════════════════
# The audited-mode record (machine-readable; the E7 design input)
# ═════════════════════════════════════════════════════════════════════════════

def load_channel_audit(path=None) -> dict:
    """The committed inbox/message-channel audit outcome. Raises on a
    missing/garbled record — the audited mode is a DESIGN INPUT; guessing
    it would un-fix exactly what the audit fixed."""
    p = Path(path) if path else CHANNEL_AUDIT_PATH
    return json.loads(p.read_text(encoding="utf-8"))


def audited_mode(path=None) -> str:
    return str(load_channel_audit(path).get("mode") or "")


# ═════════════════════════════════════════════════════════════════════════════
# The live delivery seam (the WIRED paced-PTY path; injectable for tests)
# ═════════════════════════════════════════════════════════════════════════════

def _default_deliver(session_id: str, data: str):
    """The wired channel: ``pty_manager.write`` — the paced-PTY path
    (wire-homing row ``paced_pty``; >512-char payloads chunk at 256 chars,
    paced, inside the owner). Resolved at call time so the stub backend and
    monkeypatched seams behave."""
    import pty_manager
    return pty_manager.write(session_id, data)


def _session_is_live(session_id: str) -> bool:
    """Liveness against the PTY table — the channel exists iff the session
    has a live PTY to write onto. Never spawns, never relaunches."""
    try:
        import pty_manager
        return str(session_id) in set(pty_manager.live_sessions())
    except Exception:
        return False


# ═════════════════════════════════════════════════════════════════════════════
# The re-brief (E7) + the co-landed sweep-contention refusal
# ═════════════════════════════════════════════════════════════════════════════

def _sweep_contention(folder) -> dict | None:
    """The active-sweep check. Truthy result == a sweep owns the decision
    window: an unswept death stands (E2 holding) or the sweep card holds
    the queue head unresolved. FAILS CLOSED on an unreadable gates store."""
    try:
        import chamber_gates as _cg
        try:
            unswept = _cg.unswept_deaths(folder)
        except _cg.GateStoreError as exc:
            return {"reason": "gates-store-unreadable", "detail": str(exc)}
        if unswept:
            return {"reason": "unswept-death",
                    "sessions": [d.get("session_id") for d in unswept]}
        state = _cg.queue_state(folder)
        head = state.get("head") if state.get("ok") else None
        if state.get("ok") is False:
            return {"reason": "gates-store-unreadable",
                    "detail": state.get("error")}
        if head is not None and head.get("kind") == _cg.KIND_SWEEP:
            return {"reason": "sweep-card-at-head",
                    "gate_id": head.get("gate_id")}
    except Exception as exc:  # a contention check that errors fails CLOSED
        return {"reason": "contention-check-failed", "detail": str(exc)[:200]}
    return None


def rebrief(folder, session_id: str, text: str, *, step_id=None,
            deliver=None) -> dict:
    """Deliver one mid-flight re-brief to the RUNNING commission session in
    the audited LIVE mode — no relaunch, ever.

    Order of law: (1) the co-landed contention refusal — during an active
    sweep the re-brief is refused AND queued durably behind the sweep with
    the named finding, never interleaved; (2) liveness — a dead/unknown
    session is an honest named refusal; (3) ONE paced write through the
    wired channel; (4) the acknowledgment RECEIPT persisted on the step
    (durable, inspectable — the E7 receipt the step surfaces).
    """
    sid = str(session_id or "").strip()
    body = str(text or "").strip()
    if not body:
        return {"ok": False, "error": ERROR_EMPTY_TEXT}

    contention = _sweep_contention(folder)
    if contention is not None:
        queued = {"session_id": sid, "step_id": step_id, "text": body,
                  "finding": FINDING_REBRIEF_DURING_SWEEP,
                  "contention": contention, "queued_at": _now()}
        with _cp.file_lock(_lock_path(folder)):
            try:
                doc = _load(folder)
            except RebriefStoreError as exc:
                return {"ok": False, "error": exc.error, "message": str(exc),
                        "finding": FINDING_REBRIEF_DURING_SWEEP}
            doc["queued"].append(queued)
            _save(folder, doc)
        return {"ok": False, "queued": True,
                "finding": FINDING_REBRIEF_DURING_SWEEP,
                "contention": contention,
                "message": "a sweep owns the decision window (%s) — the "
                           "re-brief is queued behind the sweep's card "
                           "binding, never interleaved (W11 contention law)"
                           % contention.get("reason")}

    if deliver is None:
        if not _session_is_live(sid):
            return {"ok": False, "error": ERROR_SESSION_NOT_LIVE,
                    "session_id": sid,
                    "message": "session %r has no live PTY — a re-brief "
                               "never relaunches; start/resume the session "
                               "explicitly instead" % sid}
        deliver = _default_deliver

    payload = "%s\n%s\n" % (REBRIEF_FRAME, body)
    try:
        deliver(sid, payload)
    except Exception as exc:
        return {"ok": False, "error": ERROR_DELIVERY_FAILED,
                "session_id": sid, "detail": str(exc)[:200]}

    receipt = {"session_id": sid, "step_id": step_id,
               "mode": MODE_LIVE, "chars": len(payload),
               "text": body, "delivered_at": _now()}
    with _cp.file_lock(_lock_path(folder)):
        try:
            doc = _load(folder)
        except RebriefStoreError as exc:
            # Delivered but unrecordable: honest partial — the caller is
            # told the receipt could not be minted.
            return {"ok": False, "error": exc.error, "delivered": True,
                    "message": str(exc)}
        doc["receipts"].append(receipt)
        _save(folder, doc)
    return {"ok": True, "mode": MODE_LIVE, "receipt": dict(receipt)}


def receipts_for_step(folder, step_id) -> list:
    """The acknowledgment receipts surfaced ON THE STEP (E7)."""
    try:
        doc = _load(folder)
    except RebriefStoreError:
        return []
    return [dict(r) for r in doc.get("receipts") or []
            if r.get("step_id") == step_id]


def receipts_for_session(folder, session_id) -> list:
    try:
        doc = _load(folder)
    except RebriefStoreError:
        return []
    return [dict(r) for r in doc.get("receipts") or []
            if r.get("session_id") == str(session_id)]


def queued_rebriefs(folder) -> list:
    try:
        doc = _load(folder)
    except RebriefStoreError:
        return []
    return [dict(q) for q in doc.get("queued") or []]


def flush_queued(folder, *, deliver=None) -> dict:
    """Deliver the parked re-briefs once the sweep has cleared. A still-
    active sweep keeps everything parked (the contention law holds here
    too). Delivery failures stay queued — never dropped."""
    contention = _sweep_contention(folder)
    if contention is not None:
        return {"ok": False, "still_contended": True,
                "finding": FINDING_REBRIEF_DURING_SWEEP,
                "contention": contention}
    delivered, kept = [], []
    with _cp.file_lock(_lock_path(folder)):
        try:
            doc = _load(folder)
        except RebriefStoreError as exc:
            return {"ok": False, "error": exc.error}
        pending = list(doc.get("queued") or [])
        doc["queued"] = []
        _save(folder, doc)
    for q in pending:
        out = rebrief(folder, q.get("session_id"), q.get("text"),
                      step_id=q.get("step_id"), deliver=deliver)
        (delivered if out.get("ok") else kept).append(
            {"queued": q, "result": out})
    if kept:  # re-park what could not deliver
        with _cp.file_lock(_lock_path(folder)):
            try:
                doc = _load(folder)
                doc["queued"].extend(k["queued"] for k in kept)
                _save(folder, doc)
            except RebriefStoreError:
                pass
    return {"ok": True, "delivered": len(delivered), "kept": len(kept)}
