"""Serialized decision-gate queue + died→sweep-card state machine
(steward-chamber W10, C5/C7 — E2/E5/F4).

Three jobs, one chamber-sidecar store (``.anchor/chamber/gates.json``):

**1. The serialized FIFO decision-gate queue** (E5) — decisions are PROSE
CARDS that serialize: the queue is durable, visible as state
(:func:`queue_state`), and HEAD-ONLY at the render layer — exactly one card
shows (:func:`render_gate_queue_html`); the next appears only after the head
is resolved or skipped (:func:`resolve_gate` / :func:`skip_gate`, which
refuse a non-head gate by name — serialization is a law here, not a habit).
A double-render is a NAMED finding (:func:`double_render_finding`), never a
silent second card.

**2. The died→sweep-card state machine** (C5) — a run that ended
``died``/``quiet``/``timeout`` registers a SWEEP-PENDING death
(:func:`on_run_death`, wired into ``commission_session.finish_run``). From
that moment the state machine OVERRIDES any composed narrative next-move
(:func:`overriding_next_move`, consumed by ``chamber_directive``) and the
**E2 enqueue gate** holds: a re-commission CANNOT enqueue — at
:func:`enqueue_gate` for a re-commission card AND at the W2-proven
``commission_session.confirm_and_launch`` seam via :func:`enqueue_guard` —
until the containment-checked sweep card is BOUND into the queue
(:func:`bind_sweep_card`). The refusal carries the named finding
:data:`FINDING_E2_BLOCKED`. The guard FAILS CLOSED on an unreadable store.

**3. The two-tier containment-checked worktree sweep** (F4,
:func:`run_sweep`) — tier 1 lands declared-deliverable-glob matches onto
the step (a ``step_yield`` projection event via the W4 writer); tier 2
``git status --porcelain``s the worktree into an explicit 'unclaimed
changes' card. EVERY swept path passes :func:`sweep_containment` — symlink-
AND junction/reparse-resolved (``Path.resolve``), refused by NAME when it
escapes the swept root ('..', absolute, a link pointing out) or when it
CONTAINS the swept root (the reverse direction), and tier-1 landings are
additionally checked against the PROJECT root (worktree/project containment
both directions). Unclaimed content is listed BY PATH ONLY — never read,
never executed, and the queue render escapes it (F5) so it is never markup.

Contention law (co-landed refusal cases, re-run by W12): a sweep card binds
AT THE HEAD; a directive/decision card holding the head is RE-QUEUED behind
it — never dropped (:data:`FINDING_CONTENTION` records the deterministic
resolution) — and a run dying WHILE a gate is held routes into this state
machine without touching the held gate.

Durability rides ``chamber_projections`` (one sidecar discipline: kernel
file lock + temp/fsync/rename). Stdlib only; ``git`` is an external CLI
spawned ``shell=False`` with a fixed argv (never path content). Zero spine
writes — the store is chamber-sidecar derived data.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

import chamber_projections as _cp

SCHEMA = "anchor-chamber-gates-v1"
SWEEP_SCHEMA = "anchor-chamber-sweep-v1"

GATES_REL = os.path.join(_cp.CHAMBER_SIDECAR_REL, "gates.json")
GATES_LOCK_REL = GATES_REL + ".lock"

# ── Gate vocabulary ─────────────────────────────────────────────────────────
KIND_DIRECTIVE = "directive"
KIND_DECISION = "decision"
KIND_SWEEP = "sweep"
KIND_RECOMMISSION = "recommission"
GATE_KINDS = (KIND_DIRECTIVE, KIND_DECISION, KIND_SWEEP, KIND_RECOMMISSION)

STATUS_PENDING = "pending"
STATUS_RESOLVED = "resolved"
STATUS_SKIPPED = "skipped"

# ── Death / sweep state machine states ──────────────────────────────────────
DEATH_OUTCOMES = ("died", "quiet", "timeout")
DEATH_PENDING_SWEEP = "sweep-pending"
DEATH_SWEEP_BOUND = "sweep-bound"

# ── Named findings / errors (the refusals are named, never silent) ──────────
E2_ERROR = "recommission-blocked-before-sweep"
FINDING_E2_BLOCKED = "E2-RECOMMISSION-BEFORE-SWEEP-BOUND"
FINDING_DOUBLE_RENDER = "E5-DOUBLE-RENDER"
FINDING_CONTENTION = "W10-SWEEP-TAKES-HEAD-DIRECTIVE-REQUEUED"
FINDING_NEXT_MOVE_OVERRIDE = "W10-SWEEP-OVERRIDES-NEXT-MOVE"

ERROR_STORE_UNREADABLE = "gates-store-unreadable"
ERROR_NOT_HEAD = "not-queue-head"
ERROR_QUEUE_EMPTY = "queue-empty"
ERROR_UNKNOWN_KIND = "unknown-gate-kind"

# ── F4 sweep-containment refusal reasons ────────────────────────────────────
SWEEP_HOSTILE_PATH = "hostile-path-content"
SWEEP_ABSOLUTE = "absolute-path-refused"
SWEEP_TRAVERSAL = "parent-traversal-refused"
SWEEP_OUTSIDE = "outside-swept-root"
SWEEP_CONTAINS_ROOT = "contains-swept-root"
SWEEP_LANDS_OUTSIDE_PROJECT = "lands-outside-project"

_DRIVE_RE = re.compile(r"^[A-Za-z]:")

#: How many unclaimed paths a sweep card lists inline (the rest are counted —
#: a bound, honest cap; the full list stays on the sweep record).
UNCLAIMED_CARD_CAP = 12

GIT_TIMEOUT_S = 30


class GateStoreError(RuntimeError):
    """Named gate-store failure (``.error`` == :data:`ERROR_STORE_UNREADABLE`)."""

    def __init__(self, error: str, message: str):
        super().__init__(message)
        self.error = error


# ═════════════════════════════════════════════════════════════════════════════
# Store (chamber sidecar; same durability discipline as chamber_projections)
# ═════════════════════════════════════════════════════════════════════════════

def gates_path(folder) -> Path:
    return Path(folder) / GATES_REL


def _lock_path(folder) -> Path:
    return Path(folder) / GATES_LOCK_REL


def _empty_store() -> dict:
    return {"schema": SCHEMA, "seq": 0, "gates": [], "deaths": [],
            "last_contention": None}


def _load(folder) -> dict:
    p = gates_path(folder)
    if not p.exists():
        return _empty_store()
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise GateStoreError(
            ERROR_STORE_UNREADABLE,
            "gates store unreadable at %s: %s" % (GATES_REL, exc))
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        raise GateStoreError(
            ERROR_STORE_UNREADABLE,
            "gates store carries no %r schema" % SCHEMA)
    doc.setdefault("seq", 0)
    doc.setdefault("gates", [])
    doc.setdefault("deaths", [])
    doc.setdefault("last_contention", None)
    return doc


def _save(folder, doc: dict) -> None:
    _cp.atomic_write_json(gates_path(folder), doc)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _pending(doc: dict) -> list:
    return [g for g in doc["gates"] if g.get("status") == STATUS_PENDING]


def _head_of(doc: dict):
    pending = _pending(doc)
    return pending[0] if pending else None


def _safe_gate(g: dict, with_card: bool = False) -> dict:
    out = {"gate_id": g.get("gate_id"), "kind": g.get("kind"),
           "status": g.get("status"), "requeued": bool(g.get("requeued")),
           "session_id": g.get("session_id"),
           "enqueued_at": g.get("enqueued_at")}
    if with_card:
        out["text"] = (g.get("card") or {}).get("text")
        out["card"] = g.get("card")
    return out


# ═════════════════════════════════════════════════════════════════════════════
# The E2 enqueue gate (the engine-enforced law on the W2-proven seam)
# ═════════════════════════════════════════════════════════════════════════════

def unswept_deaths(folder) -> list:
    """Deaths whose containment-checked sweep card is NOT yet bound into the
    queue. Raises :class:`GateStoreError` on an unreadable store."""
    doc = _load(folder)
    return [d for d in doc["deaths"] if d.get("state") != DEATH_SWEEP_BOUND]


def enqueue_guard(folder) -> dict:
    """The E2 law as one callable, consumed by
    ``commission_session.confirm_and_launch`` (the W2-proven leg-b seam) and
    by :func:`enqueue_gate` for re-commission cards.

    ``{"ok": True}`` when nothing blocks; otherwise the NAMED refusal —
    never a silent pass. FAILS CLOSED on an unreadable store (a safety gate
    that cannot read its state refuses rather than guesses).
    """
    try:
        blocking = unswept_deaths(folder)
    except GateStoreError as exc:
        return {"ok": False, "error": exc.error,
                "finding": FINDING_E2_BLOCKED,
                "message": "the decision-gate store is unreadable — the E2 "
                           "enqueue gate fails CLOSED rather than enqueue a "
                           "re-commission blind: %s" % exc}
    if blocking:
        return {
            "ok": False,
            "error": E2_ERROR,
            "finding": FINDING_E2_BLOCKED,
            "blocking_deaths": [
                {"session_id": d.get("session_id"),
                 "outcome": d.get("outcome"), "state": d.get("state")}
                for d in blocking],
            "message": "a run on this campaign %s and its containment-checked "
                       "sweep card is not yet bound into the decision-gate "
                       "queue — the sweep comes before any re-commission (E2)"
                       % " / ".join(sorted({str(d.get("outcome"))
                                            for d in blocking})),
        }
    return {"ok": True}


# ═════════════════════════════════════════════════════════════════════════════
# Queue mutations (FIFO enqueue · head-insert sweep bind · head-only resolve)
# ═════════════════════════════════════════════════════════════════════════════

def enqueue_gate(folder, kind: str, card: dict, *, session_id=None,
                 source=None) -> dict:
    """Append one decision gate at the TAIL (FIFO). A ``recommission`` card
    additionally crosses the E2 enqueue gate and is REFUSED with the named
    finding while an unswept death stands — nothing is written on refusal."""
    if kind not in GATE_KINDS:
        return {"ok": False, "error": ERROR_UNKNOWN_KIND,
                "message": "unknown gate kind %r (kinds: %s)"
                           % (kind, ", ".join(GATE_KINDS))}
    if kind == KIND_RECOMMISSION:
        guard = enqueue_guard(folder)
        if not guard.get("ok"):
            return guard
    with _cp.file_lock(_lock_path(folder)):
        doc = _load(folder)
        doc["seq"] += 1
        gate = {
            "gate_id": "gate-%04d" % doc["seq"],
            "seq": doc["seq"],
            "kind": kind,
            "status": STATUS_PENDING,
            "card": dict(card or {}),
            "session_id": session_id,
            "source": source,
            "requeued": False,
            "enqueued_at": _now(),
        }
        doc["gates"].append(gate)
        _save(folder, doc)
    return {"ok": True, "gate": _safe_gate(gate, with_card=True)}


def bind_sweep_card(folder, sweep_result: dict, *, session_id=None,
                    commit: bool = True) -> dict:
    """Bind a completed sweep's card INTO the queue — AT THE HEAD.

    This is the state-machine transition that releases E2: the matching
    death flips to ``sweep-bound``. Queue-head contention resolves
    DETERMINISTICALLY: the sweep card takes the head; a pending gate that
    held it is RE-QUEUED immediately behind (marked, named finding recorded)
    — never dropped. Best-effort auto-commit of campaign state afterward
    (V3 landing class: sweep landing).
    """
    card = dict((sweep_result or {}).get("card") or {})
    sid = session_id or (sweep_result or {}).get("session_id") \
        or card.get("session_id")
    contention = None
    with _cp.file_lock(_lock_path(folder)):
        doc = _load(folder)
        doc["seq"] += 1
        gate = {
            "gate_id": "gate-%04d" % doc["seq"],
            "seq": doc["seq"],
            "kind": KIND_SWEEP,
            "status": STATUS_PENDING,
            "card": card,
            "session_id": sid,
            "source": "sweep-card-state-machine",
            "requeued": False,
            "enqueued_at": _now(),
        }
        held = _head_of(doc)
        if held is not None:
            # Deterministic contention resolution: the sweep takes the head;
            # the held gate is RE-QUEUED behind it (kept pending — a held
            # gate is never dropped by a death or a sweep).
            held["requeued"] = True
            contention = {"finding": FINDING_CONTENTION,
                          "requeued_gate_id": held["gate_id"],
                          "requeued_kind": held.get("kind"),
                          "sweep_gate_id": gate["gate_id"],
                          "at": _now()}
            doc["last_contention"] = contention
            idx = doc["gates"].index(held)
            doc["gates"].insert(idx, gate)
        else:
            doc["gates"].append(gate)
        death = None
        for d in doc["deaths"]:
            if sid and d.get("session_id") == sid:
                death = d
                break
        if death is None:
            death = {"session_id": sid, "commission_id": card.get("commission_id"),
                     "step_id": card.get("step_id"), "outcome": card.get("outcome"),
                     "state": DEATH_PENDING_SWEEP, "at": _now(),
                     "sweep_gate_id": None}
            doc["deaths"].append(death)
        death["state"] = DEATH_SWEEP_BOUND
        death["sweep_gate_id"] = gate["gate_id"]
        _save(folder, doc)
    if commit:
        _auto_commit(folder, "sweep landing bound to the gate queue")
    return {"ok": True, "gate": _safe_gate(gate, with_card=True),
            "contention": contention,
            "held_gate_kept": (contention or {}).get("requeued_gate_id")}


def _finish_gate(folder, gate_id: str, status: str, resolution,
                 commit: bool) -> dict:
    with _cp.file_lock(_lock_path(folder)):
        doc = _load(folder)
        head = _head_of(doc)
        if head is None:
            return {"ok": False, "error": ERROR_QUEUE_EMPTY,
                    "message": "no pending gate to %s" % status}
        if gate_id != head["gate_id"]:
            # E5 serialization law: ONLY the head may resolve/skip — a
            # deeper gate waits its turn, by name.
            return {"ok": False, "error": ERROR_NOT_HEAD,
                    "head": head["gate_id"], "gate_id": gate_id,
                    "message": "gate %s is not the queue head (%s is) — "
                               "gates serialize FIFO and only the head card "
                               "is decidable (E5)" % (gate_id, head["gate_id"])}
        head["status"] = status
        head["resolution"] = resolution
        head["resolved_at"] = _now()
        released = _head_of(doc)
        _save(folder, doc)
    if commit:
        _auto_commit(folder, "gate %s: %s" % (status, head.get("kind")))
    return {"ok": True, "gate": _safe_gate(head),
            "released": _safe_gate(released, with_card=True)
            if released is not None else None}


def resolve_gate(folder, gate_id: str, resolution=None,
                 commit: bool = True) -> dict:
    """Resolve the HEAD gate (refuses a non-head by name); releases the next
    pending card, returned as ``released``."""
    return _finish_gate(folder, gate_id, STATUS_RESOLVED,
                        resolution=(str(resolution)[:500] if resolution
                                    else None), commit=commit)


def skip_gate(folder, gate_id: str, commit: bool = True) -> dict:
    """Skip the HEAD gate (same serialization law as resolve)."""
    return _finish_gate(folder, gate_id, STATUS_SKIPPED, resolution=None,
                        commit=commit)


def _auto_commit(folder, label: str) -> None:
    """Best-effort campaign bank via the WIRED auto-commit
    (``commission_session.commit_campaign_state`` — wire-homing row
    ``auto_commit``, never reimplemented here). A commit hiccup never blocks
    a gate decision; V3's landing-scoped fixture proves the coverage."""
    try:
        import commission_session as _cs
        _cs.commit_campaign_state(folder, label)
    except Exception:
        pass


# ═════════════════════════════════════════════════════════════════════════════
# Queue state (visible as state) + the HEAD-ONLY render (E5)
# ═════════════════════════════════════════════════════════════════════════════

def queue_state(folder) -> dict:
    """The queue as SAFE, durable, visible state: every gate's id/kind/status
    in queue order, the HEAD card's content (the ONLY card content served),
    the pending depth, the death rows, and the last contention record."""
    try:
        doc = _load(folder)
    except GateStoreError as exc:
        return {"ok": False, "error": exc.error, "schema": SCHEMA}
    head = _head_of(doc)
    return {
        "schema": SCHEMA,
        "ok": True,
        "queued_count": len(_pending(doc)),
        "head": _safe_gate(head, with_card=True) if head is not None else None,
        "gates": [_safe_gate(g) for g in doc["gates"]],
        "deaths": [{"session_id": d.get("session_id"),
                    "outcome": d.get("outcome"), "state": d.get("state"),
                    "sweep_gate_id": d.get("sweep_gate_id")}
                   for d in doc["deaths"]],
        "last_contention": doc.get("last_contention"),
    }


def double_render_finding(rendered_gate_ids) -> dict | None:
    """The named finding on any double-render: more than one card painted at
    once is :data:`FINDING_DOUBLE_RENDER` — never a silent second card."""
    ids = [g for g in (rendered_gate_ids or []) if g]
    if len(ids) <= 1:
        return None
    return {"finding": FINDING_DOUBLE_RENDER, "rendered": ids,
            "message": "the gate queue rendered %d cards at once — the "
                       "render layer is HEAD-ONLY (E5)" % len(ids)}


_KIND_LABELS = {KIND_DIRECTIVE: "directive", KIND_DECISION: "decision",
                KIND_SWEEP: "worktree sweep", KIND_RECOMMISSION: "re-commission"}


def _esc(value) -> str:
    import html as _html
    return _html.escape(str(value if value is not None else ""), quote=True)


def _depth_line(queued: int) -> str:
    if queued <= 1:
        return "No further decision is queued behind this one." if queued \
            else "The decision queue is empty."
    return "%d more decision%s queued behind this card — one at a time." \
        % (queued - 1, "" if queued == 2 else "s")


def render_gate_queue_html(state: dict) -> str:
    """The HEAD-ONLY queue render (E5): exactly ONE prose card — the head —
    plus the queue depth as text. Every slot value is escaped (F5): swept
    paths and card prose are agent-influenced strings and enter the DOM as
    text, never markup."""
    if not isinstance(state, dict) or not state.get("ok", True):
        return ('<div class="gatequeue" data-error="1">'
                '<div class="gq-err">The decision queue is unreadable: '
                '%s</div></div>'
                % _esc((state or {}).get("error") or "unknown-error"))
    head = state.get("head")
    queued = int(state.get("queued_count") or 0)
    if not head:
        return ('<div class="gatequeue" data-empty="1">'
                '<div class="gq-empty">No decision is waiting.</div>'
                '<div class="gq-depth">%s</div></div>'
                % _esc(_depth_line(queued)))
    text = (head.get("text") or (head.get("card") or {}).get("text") or "")
    lines = "".join('<div class="gq-line">%s</div>' % _esc(ln)
                    for ln in str(text).splitlines() if ln.strip())
    return ('<div class="gatequeue" data-head="%s">'
            '<div class="gq-card gq-%s"><div class="gq-kind">%s</div>'
            '%s</div><div class="gq-depth">%s</div></div>'
            % (_esc(head.get("gate_id")),
               _esc(head.get("kind")),
               _esc(_KIND_LABELS.get(head.get("kind"), head.get("kind"))),
               lines,
               _esc(_depth_line(queued))))


# ═════════════════════════════════════════════════════════════════════════════
# The died→sweep-card state machine
# ═════════════════════════════════════════════════════════════════════════════

def on_run_death(folder, record: dict) -> dict:
    """The died/quiet/timeout → sweep-card transition (wired into
    ``commission_session.finish_run``): register the death SWEEP-PENDING —
    from here the E2 gate holds and the composed narrative next-move is
    overridden. A HELD GATE IS NEVER TOUCHED: the queue's head stays exactly
    where it was (the co-landed died-while-gate-held refusal case).
    Idempotent per session. Also records the W4 ``run_death`` projection."""
    rec = record or {}
    outcome = rec.get("outcome")
    if outcome not in DEATH_OUTCOMES:
        return {"ok": True, "registered": False,
                "reason": "outcome-not-a-death", "outcome": outcome}
    sid = rec.get("session_id")
    with _cp.file_lock(_lock_path(folder)):
        doc = _load(folder)
        held = _head_of(doc)
        for d in doc["deaths"]:
            if sid and d.get("session_id") == sid:
                return {"ok": True, "registered": False,
                        "reason": "already-registered", "death": dict(d),
                        "held_gate_kept": held["gate_id"] if held else None}
        death = {"session_id": sid,
                 "commission_id": rec.get("commission_id"),
                 "step_id": rec.get("step_id"),
                 "skill": rec.get("skill"),
                 "outcome": outcome,
                 "state": DEATH_PENDING_SWEEP,
                 "sweep_gate_id": None,
                 "at": _now()}
        doc["deaths"].append(death)
        _save(folder, doc)
    try:
        _cp.record_run_death(folder, rec.get("commission_id"),
                             session_id=sid, outcome=outcome)
    except Exception:
        pass  # the sidecar event is derived data; the death row is the law
    return {"ok": True, "registered": True, "death": dict(death),
            "held_gate_kept": held["gate_id"] if held else None}


def overriding_next_move(folder) -> dict:
    """The state machine's next-move OVERRIDE (consumed by
    ``chamber_directive.compose_directive_card``): while a death is unswept —
    or its sweep card still holds the queue — the ONE next move IS the sweep,
    whatever any composed narrative says."""
    try:
        doc = _load(folder)
    except GateStoreError as exc:
        return {"override": False, "error": exc.error}
    unswept = [d for d in doc["deaths"] if d.get("state") != DEATH_SWEEP_BOUND]
    if unswept:
        d = unswept[-1]
        return {
            "override": True,
            "finding": FINDING_NEXT_MOVE_OVERRIDE,
            "state": DEATH_PENDING_SWEEP,
            "session_id": d.get("session_id"),
            "text": "A run %s (%s on %s): sweep its worktree before anything "
                    "else — no re-commission can enqueue until the "
                    "containment-checked sweep card is bound into the queue."
                    % (d.get("outcome") or "died",
                       d.get("skill") or "a skill",
                       d.get("step_id") or "a step"),
            "question": "Run the containment-checked sweep of the %s run now?"
                        % (d.get("outcome") or "died"),
        }
    head = _head_of(doc)
    if head is not None and head.get("kind") == KIND_SWEEP:
        return {
            "override": True,
            "finding": FINDING_NEXT_MOVE_OVERRIDE,
            "state": DEATH_SWEEP_BOUND,
            "session_id": head.get("session_id"),
            "text": "The sweep card for the died run holds the head of the "
                    "decision queue — deciding it is the one next move.",
            "question": "Resolve the sweep card at the head of the queue?",
        }
    return {"override": False}


# ═════════════════════════════════════════════════════════════════════════════
# F4: symlink- and junction/reparse-resolved containment, BOTH directions
# ═════════════════════════════════════════════════════════════════════════════

def sweep_containment(root, rel):
    """Containment check for ONE swept path against ONE root.

    Returns ``(resolved_path, None)`` when contained, else ``(None,
    refusal_dict)`` with the NAMED reason. Security order: byte-level
    hostility first, then shape ('..', absolute/drive/UNC), then the
    symlink- and junction/reparse-resolving check (``Path.resolve`` resolves
    both for every existing component) against the resolved root — BOTH
    directions: a path escaping the root is refused (``outside-swept-root``)
    AND a path that resolves to the root or an ANCESTOR of it is refused
    (``contains-swept-root``) — claiming the root itself would sweep the
    world.
    """
    if not isinstance(rel, str) or not rel.strip():
        return None, {"reason": SWEEP_HOSTILE_PATH, "path": "",
                      "detail": "empty path"}
    if any(ord(ch) < 0x20 or ch == "\x7f" for ch in rel):
        return None, {"reason": SWEEP_HOSTILE_PATH, "path": rel[:200],
                      "detail": "control byte in path"}
    if rel.startswith(("/", "\\")) or _DRIVE_RE.match(rel):
        return None, {"reason": SWEEP_ABSOLUTE, "path": rel[:200]}
    segments = [s for s in re.split(r"[\\/]+", rel) if s and s != "."]
    if not segments:
        return None, {"reason": SWEEP_HOSTILE_PATH, "path": rel[:200],
                      "detail": "no path segments"}
    if any(s == ".." for s in segments):
        return None, {"reason": SWEEP_TRAVERSAL, "path": rel[:200]}
    try:
        base = Path(root).resolve()
        real = base.joinpath(*segments).resolve()
    except (OSError, ValueError) as exc:
        return None, {"reason": SWEEP_HOSTILE_PATH, "path": rel[:200],
                      "detail": str(exc)[:200]}
    if real == base or real in base.parents:
        return None, {"reason": SWEEP_CONTAINS_ROOT, "path": rel[:200]}
    if base not in real.parents:
        return None, {"reason": SWEEP_OUTSIDE, "path": rel[:200]}
    return real, None


def _pattern_shape_refusal(pattern: str):
    """Shape-check a declared-deliverable GLOB pattern before any glob runs
    (glob metacharacters are legal; '..', absolute, control bytes are not)."""
    if not isinstance(pattern, str) or not pattern.strip():
        return {"reason": SWEEP_HOSTILE_PATH, "path": "",
                "detail": "empty glob pattern"}
    if any(ord(ch) < 0x20 or ch == "\x7f" for ch in pattern):
        return {"reason": SWEEP_HOSTILE_PATH, "path": pattern[:200],
                "detail": "control byte in glob pattern"}
    if pattern.startswith(("/", "\\")) or _DRIVE_RE.match(pattern):
        return {"reason": SWEEP_ABSOLUTE, "path": pattern[:200]}
    if any(s == ".." for s in re.split(r"[\\/]+", pattern)):
        return {"reason": SWEEP_TRAVERSAL, "path": pattern[:200]}
    return None


# ═════════════════════════════════════════════════════════════════════════════
# The two-tier sweep
# ═════════════════════════════════════════════════════════════════════════════

def _declared_deliverable(folder):
    import chamber_manifest as cm
    manifest = cm.load_manifest(folder)
    if not isinstance(manifest, dict) or "_unparseable" in manifest:
        return None
    d = manifest.get("deliverable")
    return d if isinstance(d, dict) and d.get("declared") else None


def _git_status_paths(worktree: Path) -> dict:
    """``git status --porcelain`` → ``{"paths": [rel...], "error": None}``.
    Fixed argv, ``shell=False``, cwd pinned to the worktree; a git hiccup is
    an HONEST named error, never a guess. Paths are DATA out of here —
    nothing is read, executed, or globbed from them."""
    try:
        res = subprocess.run(
            ["git", "status", "--porcelain"], cwd=str(worktree),
            capture_output=True, text=True, timeout=GIT_TIMEOUT_S,
            shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if os.name == "nt" else 0)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"paths": [], "error": "git-status-failed",
                "detail": str(exc)[:200]}
    if res.returncode != 0:
        return {"paths": [], "error": "git-status-failed",
                "detail": (res.stderr or res.stdout or "")[:200]}
    paths = []
    for line in (res.stdout or "").splitlines():
        if len(line) < 4:
            continue
        entry = line[3:]
        if " -> " in entry:  # rename: the NEW path is the swept fact
            entry = entry.split(" -> ", 1)[1]
        entry = entry.strip()
        if entry.startswith('"') and entry.endswith('"') and len(entry) >= 2:
            entry = entry[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        if entry:
            paths.append(entry)
    return {"paths": paths, "error": None}


def run_sweep(folder, record: dict) -> dict:
    """The two-tier containment-checked worktree sweep (F4). TOTAL — every
    failure is a named field on the result, and a card is ALWAYS produced
    (the death is only releasable through a bound card, so even an
    empty/failed sweep yields an honest card to bind).

    Tier 1 — declared-deliverable-glob matches, containment-checked against
    the WORKTREE root and against the PROJECT landing target (both
    directions), landed onto the step as a ``step_yield`` projection event.

    Tier 2 — ``git status --porcelain`` over the worktree → the 'unclaimed
    changes' card: paths ONLY, containment-checked, never executed.
    """
    rec = record or {}
    wt = str(rec.get("worktree_path") or "").strip()
    worktree = Path(wt) if wt else None
    worktree_present = bool(worktree and worktree.is_dir())

    sweep = {
        "schema": SWEEP_SCHEMA,
        "session_id": rec.get("session_id"),
        "commission_id": rec.get("commission_id"),
        "step_id": rec.get("step_id"),
        "skill": rec.get("skill"),
        "outcome": rec.get("outcome"),
        "worktree_present": worktree_present,
        "tier1": {"pattern": None, "claimed": [], "refused": [],
                  "note": None},
        "tier2": {"unclaimed": [], "refused": [], "error": None},
    }

    deliverable = _declared_deliverable(folder)
    if deliverable is None:
        sweep["tier1"]["note"] = "no-declared-deliverable"
    else:
        pattern = str(deliverable.get("output_path") or "")
        sweep["tier1"]["pattern"] = pattern[:300]
        shape = _pattern_shape_refusal(pattern)
        if shape is not None:
            sweep["tier1"]["refused"].append(shape)
        elif worktree_present:
            try:
                matches = sorted(worktree.glob(pattern.replace("\\", "/")))
            except (OSError, ValueError) as exc:
                matches = []
                sweep["tier1"]["refused"].append(
                    {"reason": SWEEP_HOSTILE_PATH, "path": pattern[:200],
                     "detail": str(exc)[:200]})
            for m in matches:
                if not m.is_file():
                    continue
                try:
                    rel = m.relative_to(worktree).as_posix()
                except ValueError:
                    rel = str(m)
                real, refused = sweep_containment(worktree, rel)
                if refused is not None:
                    sweep["tier1"]["refused"].append(refused)
                    continue
                # The other direction of the worktree/project pair: the
                # landing target project/<rel> must resolve INSIDE the
                # project (an existing junction/symlink at the landing path
                # redirecting outside refuses the landing by name).
                landing, land_refused = sweep_containment(folder, rel)
                if land_refused is not None:
                    land_refused = dict(land_refused)
                    land_refused["reason"] = SWEEP_LANDS_OUTSIDE_PROJECT \
                        if land_refused["reason"] in (SWEEP_OUTSIDE,
                                                      SWEEP_CONTAINS_ROOT) \
                        else land_refused["reason"]
                    sweep["tier1"]["refused"].append(land_refused)
                    continue
                sweep["tier1"]["claimed"].append({"path": rel})
        if sweep["tier1"]["claimed"]:
            try:
                _cp.record_step_yield(
                    folder, rec.get("commission_id"), rec.get("step_id"),
                    "sweep landed %d declared output(s): %s"
                    % (len(sweep["tier1"]["claimed"]),
                       ", ".join(c["path"]
                                 for c in sweep["tier1"]["claimed"][:6])),
                    session_id=rec.get("session_id"))
            except Exception:
                sweep["tier1"]["note"] = "step-yield-record-failed"

    if worktree_present:
        status = _git_status_paths(worktree)
        sweep["tier2"]["error"] = status["error"]
        if status.get("detail"):
            sweep["tier2"]["detail"] = status["detail"]
        for rel in status["paths"]:
            _, refused = sweep_containment(worktree, rel)
            if refused is not None:
                sweep["tier2"]["refused"].append(refused)
                continue
            sweep["tier2"]["unclaimed"].append({"path": rel})
    else:
        sweep["tier2"]["error"] = "worktree-missing"

    card_text = sweep_card_text(sweep)
    sweep_summary = {
        "claimed": [c["path"] for c in sweep["tier1"]["claimed"]],
        "unclaimed": [u["path"] for u in sweep["tier2"]["unclaimed"]],
        "refused": ([r for r in sweep["tier1"]["refused"]]
                    + [r for r in sweep["tier2"]["refused"]]),
        "worktree_present": worktree_present,
    }
    return {
        "ok": True,
        "session_id": rec.get("session_id"),
        "sweep": sweep,
        "card": {
            "kind": KIND_SWEEP,
            "text": card_text,
            "session_id": rec.get("session_id"),
            "commission_id": rec.get("commission_id"),
            "step_id": rec.get("step_id"),
            "outcome": rec.get("outcome"),
            "sweep": sweep_summary,
        },
    }


def sweep_card_text(sweep: dict) -> str:
    """The sweep card as compose-first PROSE (E4: context, then the
    recommendation, question LAST). Paths appear as text only."""
    t1 = sweep.get("tier1") or {}
    t2 = sweep.get("tier2") or {}
    skill = sweep.get("skill") or "a skill"
    step = sweep.get("step_id") or "a step"
    outcome = sweep.get("outcome") or "died"
    lines = []
    if sweep.get("worktree_present"):
        lines.append(
            "The %s run on step '%s' ended %s, so its worktree was swept "
            "before any re-commission can spend again." % (skill, step, outcome))
    else:
        lines.append(
            "The %s run on step '%s' ended %s; its worktree is no longer on "
            "disk, so the sweep found nothing to reclaim." % (skill, step, outcome))
    claimed = t1.get("claimed") or []
    if claimed:
        lines.append(
            "Tier 1 landed %d declared output file(s) onto the step: %s."
            % (len(claimed), ", ".join(c["path"] for c in claimed[:6])))
    elif t1.get("note") == "no-declared-deliverable":
        lines.append("Tier 1 found no declared deliverable to match against.")
    else:
        lines.append("Tier 1 matched no declared output in the worktree.")
    unclaimed = t2.get("unclaimed") or []
    if unclaimed:
        shown = [u["path"] for u in unclaimed[:UNCLAIMED_CARD_CAP]]
        more = len(unclaimed) - len(shown)
        tail = (" (and %d more)" % more) if more > 0 else ""
        lines.append(
            "Tier 2 found unclaimed changes, listed by path only and never "
            "executed: %s%s." % (", ".join(shown), tail))
    elif t2.get("error"):
        lines.append("Tier 2 could not read the worktree state (%s) — "
                     "nothing was claimed on its behalf." % t2["error"])
    else:
        lines.append("Tier 2 found no unclaimed changes in the worktree.")
    refused = (t1.get("refused") or []) + (t2.get("refused") or [])
    if refused:
        lines.append(
            "%d path(s) were REFUSED by the containment check (%s) and were "
            "not landed or listed as claimable."
            % (len(refused), ", ".join(sorted({r["reason"] for r in refused}))))
    lines.append(
        "My recommendation: keep what tier 1 landed, review the unclaimed "
        "paths above, and only then let the step spend again.")
    lines.append("")
    lines.append("Bind this sweep onto the step and release the queue?")
    return "\n".join(lines)
