#!/usr/bin/env python3
"""Anchor reaper ARMING LADDER + tamper-evident control plane (stdlib only).

Wave 8 of the *zombie-hunter → safe-to-arm* build. The reaper's destructive
capability is exposed as an incremental **log → freeze → kill** arming ladder
that is UNARMED by default and can only advance on a numeric bar recomputed
IN-PROCESS behind an authenticated, tamper-evident control plane. Nothing here
decides *who is an orphan* — that is :mod:`reaper` (the single liveness source)
and :mod:`freeze_state` (the reversible per-PID freeze). This module governs
*whether the reaper is allowed to act at all, and how far*.

────────────────────────────────────────────────────────────────────────────
THE LADDER (three rungs — criterion 10)
────────────────────────────────────────────────────────────────────────────
  • :data:`TIER_LOG`    — UNARMED / dry-run (the DEFAULT). The sweep classifies
                          and records owner-evidence receipts + ``would-kill``
                          telemetry markers, but touches NO process.
  • :data:`TIER_FREEZE` — FREEZE-ONLY, fully reversible, never a kill. Freezes
                          only confirmed-dead-owner + no-corroborated-signal
                          candidates and ABSTAINS on any corroborated positive
                          signal; every freeze is bounded by an auto-thaw
                          watchdog (:func:`auto_thaw_expired`).
  • :data:`TIER_KILL`   — may kill, but ONLY through :func:`reaper.kill_authorized`
                          re-derived from a FRESH live probe every sweep.

────────────────────────────────────────────────────────────────────────────
THE LOAD-BEARING SAFETY PROPERTIES (criteria 10, 12, 14)
────────────────────────────────────────────────────────────────────────────

1. **Unarmed by default + restart-durable brake.** With no persisted arm state
   the effective tier is :data:`TIER_LOG`. A ``.anchor/reaper.disarmed``
   kill-switch FILE forces dry-run regardless of the persisted tier
   (:func:`effective_tier`) — a brake that survives a restart because it is a
   file on disk, not in-memory state.

2. **Protect-only persistence.** The persisted ``armed`` tier only ENABLES the
   in-process gate to run; it can never, by itself, authorize a destructive
   action. Every kill is re-derived in-process from a fresh live probe via
   :func:`reaper.kill_authorized`. A test proves that a persisted ``kill`` tier
   with an ALIVE owner kills nothing.

3. **Authenticated control plane.** :func:`arm` / :func:`advance` / :func:`disarm`
   require the same shared-secret token as every other mutating Anchor endpoint
   (``paths.auth_ok``). An unauthenticated request is refused with NO state
   change.

4. **Tamper-evident, in-process-recomputed arm gate.** Every classify outcome is
   written as an append-only, HASH-CHAINED owner-evidence receipt under
   ``.anchor/`` (:func:`append_receipt`). The arm gate (:func:`evaluate_arm_gate`)
   (a) CHAIN-VERIFIES the receipt log, (b) RECOMPUTES the arm statistics from the
   verified chain — never trusting any *stored aggregate* — and (c) evaluates a
   FRESH in-process live snapshot. A forged/edited log (a broken hash chain) or
   an inflated stored aggregate both FAIL the gate.

5. **Consecutive-abstain health banner.** When the reaper abstains (degraded /
   could-not-observe liveness) for more than K consecutive sweeps
   (:func:`health_banner`), the dashboard surfaces a warning — the reaper is
   flying blind and must not be trusted to act.

Stdlib only. No third-party imports.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import paths as _paths
import freeze_state as _fz
import reaper as _reaper

_log = logging.getLogger("anchor.reaper_arming")


# ── The ladder ───────────────────────────────────────────────────────────────
TIER_LOG = "log"        #: UNARMED / dry-run — the DEFAULT. Never touches a process.
TIER_FREEZE = "freeze"  #: FREEZE-ONLY, fully reversible, never a kill.
TIER_KILL = "kill"      #: May kill, gated by a fresh in-process kill_authorized.

#: The ordered ladder. A rung may only be advanced ONE step at a time.
LADDER = (TIER_LOG, TIER_FREEZE, TIER_KILL)
VALID_TIERS = frozenset(LADDER)


# ── On-disk locations (all under the ONE .anchor/ dir freeze_state uses) ──────
ARM_STATE_NAME = "reaper_arm.json"
RECEIPTS_NAME = "reaper_receipts.jsonl"
DISARM_NAME = "reaper.disarmed"

#: Genesis previous-hash for the receipt chain (a fixed 64-hex sentinel).
GENESIS_HASH = "0" * 64


def anchor_dir() -> Path:
    """The ``.anchor/`` dir (shared with :mod:`freeze_state`)."""
    return _fz.anchor_dir()


def arm_state_path() -> Path:
    return anchor_dir() / ARM_STATE_NAME


def receipts_path() -> Path:
    return anchor_dir() / RECEIPTS_NAME


def disarm_path() -> Path:
    return anchor_dir() / DISARM_NAME


# ─────────────────────────────────────────────────────────────────────────────
# ARM STATE (persisted tier — restart-durable, protect-only)
# ─────────────────────────────────────────────────────────────────────────────

def load_arm_state() -> dict:
    """Load the persisted arm state, defaulting to UNARMED.

    Best-effort: a missing / unreadable / corrupt store returns the UNARMED
    default (``{"tier": TIER_LOG}``) — a corrupt arm file must never leave the
    daemon accidentally armed; it fails to the SAFE (dry-run) tier.
    """
    p = arm_state_path()
    if not p.exists():
        return {"tier": TIER_LOG}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError):
        return {"tier": TIER_LOG}
    if not isinstance(raw, dict):
        return {"tier": TIER_LOG}
    tier = raw.get("tier")
    if tier not in VALID_TIERS:
        tier = TIER_LOG
    raw["tier"] = tier
    return raw


def _save_arm_state(state: dict) -> None:
    """Persist the arm state atomically (tmp + ``os.replace`` under WRITE_LOCK)."""
    with _paths.WRITE_LOCK:
        d = anchor_dir()
        d.mkdir(parents=True, exist_ok=True)
        target = arm_state_path()
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        for attempt in range(40):
            try:
                os.replace(str(tmp), str(target))
                break
            except PermissionError:
                if attempt == 39:
                    raise
                time.sleep(0.005)


def persisted_tier() -> str:
    """The persisted arm tier (``TIER_LOG`` when unarmed/corrupt)."""
    return load_arm_state().get("tier", TIER_LOG)


def is_disarmed() -> bool:
    """Whether the ``.anchor/reaper.disarmed`` kill-switch brake is engaged.

    A restart-durable, out-of-band brake: an operator (or :func:`engage_brake`)
    drops this file to force the daemon to dry-run regardless of the persisted
    arm tier. Presence is the whole signal — content is ignored.
    """
    try:
        return disarm_path().exists()
    except Exception:
        return True  # fail SAFE: if we cannot tell, assume braked (dry-run)


def effective_tier() -> str:
    """The tier the daemon will ACTUALLY act at THIS sweep.

    The kill-switch brake WINS: if ``.anchor/reaper.disarmed`` is present the
    effective tier is forced to :data:`TIER_LOG` (dry-run) no matter what is
    persisted. Otherwise it is the persisted tier. Any fault → ``TIER_LOG``.
    """
    try:
        if is_disarmed():
            return TIER_LOG
        return persisted_tier()
    except Exception:
        return TIER_LOG


def engage_brake() -> None:
    """Drop the ``.anchor/reaper.disarmed`` kill-switch file (force dry-run)."""
    with _paths.WRITE_LOCK:
        d = anchor_dir()
        d.mkdir(parents=True, exist_ok=True)
        disarm_path().write_text(
            "reaper disarmed (kill-switch brake engaged)\n", encoding="utf-8")


def release_brake() -> bool:
    """Remove the kill-switch file. Returns whether it had been engaged."""
    with _paths.WRITE_LOCK:
        p = disarm_path()
        if p.exists():
            try:
                p.unlink()
                return True
            except OSError:
                return False
        return False


# ─────────────────────────────────────────────────────────────────────────────
# HASH-CHAINED, APPEND-ONLY OWNER-EVIDENCE RECEIPTS (criterion 12)
# ─────────────────────────────────────────────────────────────────────────────
# One JSON object per line. Two kinds:
#   • kind="decision" — the per-session owner-evidence receipt for one classify
#     outcome (predicates fired, identity tuple, positive-liveness +
#     corroboration, confirmed-death, age source, decision).
#   • kind="sweep"    — a per-sweep summary the arm gate + health banner read
#     (tier, clean?, abstained?, counts, arm_event?).
# Each line carries ``prev_hash`` + ``hash`` where
#   hash = sha256(prev_hash + canonical_json(payload_without_hash)).hexdigest()
# so ANY edit/insert/reorder breaks the chain from that point on. The genesis
# ``prev_hash`` is GENESIS_HASH. Append-only: a receipt is never rewritten.

def _canonical(payload: dict) -> str:
    """Deterministic JSON for hashing (sorted keys, no whitespace jitter)."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def _chain_hash(prev_hash: str, payload: dict) -> str:
    """The chained hash of ``payload`` given ``prev_hash``."""
    h = hashlib.sha256()
    h.update((prev_hash or GENESIS_HASH).encode("utf-8"))
    h.update(_canonical(payload).encode("utf-8"))
    return h.hexdigest()


def _last_hash() -> str:
    """The ``hash`` of the final receipt on disk, or GENESIS_HASH when empty."""
    p = receipts_path()
    if not p.exists():
        return GENESIS_HASH
    last = None
    try:
        with p.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    last = line
    except OSError:
        return GENESIS_HASH
    if not last:
        return GENESIS_HASH
    try:
        return json.loads(last).get("hash") or GENESIS_HASH
    except (json.JSONDecodeError, ValueError):
        return GENESIS_HASH


def append_receipt(payload: dict) -> dict:
    """Append one hash-chained receipt line and return the stored record.

    ``payload`` is the receipt body WITHOUT chain fields; this function stamps
    ``prev_hash`` (the previous line's ``hash``) and ``hash`` (the chained hash of
    the body) and writes the whole line atomically-appended under WRITE_LOCK.
    Best-effort: a persistence failure is logged and the (unstamped) payload is
    returned — receipts must never break the sweep loop.
    """
    body = dict(payload)
    body.pop("prev_hash", None)
    body.pop("hash", None)
    try:
        with _paths.WRITE_LOCK:
            d = anchor_dir()
            d.mkdir(parents=True, exist_ok=True)
            prev = _last_hash()
            # Hash the body WITHOUT the chain fields — verify_chain recomputes the
            # link over exactly this (it strips ``hash``/``prev_hash``), so the two
            # must agree or every honest chain would fail to verify.
            new_hash = _chain_hash(prev, body)
            body["prev_hash"] = prev
            body["hash"] = new_hash
            with receipts_path().open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(body, ensure_ascii=False) + "\n")
        return body
    except Exception as e:  # pragma: no cover - persistence is best-effort
        _log.error("reaper receipt append failed: %s", e)
        return body


def read_receipts() -> list:
    """Every receipt on disk, oldest-first (best-effort; corrupt lines skipped)."""
    p = receipts_path()
    if not p.exists():
        return []
    out = []
    try:
        with p.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except (json.JSONDecodeError, ValueError):
                    # A corrupt line is a chain break — keep a sentinel so
                    # verify_chain reports tampering rather than silently healing.
                    out.append({"__corrupt__": True})
    except OSError:
        return []
    return out


def verify_chain(receipts=None) -> tuple:
    """Verify the receipt hash chain. Returns ``(ok: bool, first_bad_index: int)``.

    Recomputes every link's hash from its predecessor: any edited body, forged
    hash, inserted/removed/reordered line, or corrupt line makes a recomputed
    hash mismatch the stored one — ``ok`` is ``False`` and ``first_bad_index`` is
    the 0-based index of the first broken link (``-1`` when the chain is intact).
    An EMPTY log is a valid (trivially-intact) chain.
    """
    recs = read_receipts() if receipts is None else list(receipts)
    prev = GENESIS_HASH
    for i, rec in enumerate(recs):
        if not isinstance(rec, dict) or rec.get("__corrupt__"):
            return (False, i)
        stored_hash = rec.get("hash")
        stored_prev = rec.get("prev_hash")
        if stored_prev != prev or not stored_hash:
            return (False, i)
        body = {k: v for k, v in rec.items() if k not in ("hash", "prev_hash")}
        if _chain_hash(prev, body) != stored_hash:
            return (False, i)
        prev = stored_hash
    return (True, -1)


# ─────────────────────────────────────────────────────────────────────────────
# BUILDING RECEIPTS FROM A CLASSIFY DECISION
# ─────────────────────────────────────────────────────────────────────────────

# Per-session decisions a receipt may record.
DECISION_KEEP = "keep"
DECISION_ABSTAIN = "abstain"
DECISION_WOULD_FREEZE = "would-freeze"
DECISION_WOULD_KILL = "would-kill"
DECISION_FREEZE = "freeze"
DECISION_KILL = "kill"


def _age_source(record, snapshot) -> str:
    """Which defensible birth signal(s) the age was derived from."""
    has_created = _reaper._coerce_epoch(record.get("created_at")) is not None
    has_pid_start = _reaper._coerce_epoch(
        _reaper._pid_start_time(record, snapshot)) is not None
    if has_created and has_pid_start:
        return "created_at+pid_start"
    if has_created:
        return "created_at"
    if has_pid_start:
        return "pid_start"
    return "unknown"


def build_decision_receipt(record, snapshot, decision, *, now=None) -> dict:
    """Assemble the owner-evidence receipt body for ONE session decision.

    Captures everything the plan enumerates: the predicates that fired, the
    launch-time identity tuple, the positive-liveness signals + the corroboration
    result, the confirmed-death result, the age source, and the decision. Pure —
    returns the body dict (NOT yet chained); :func:`append_receipt` stamps it.
    """
    if now is None:
        now = time.time()
    sid = record.get("session_id")
    signals = None
    owners = set()
    try:
        if snapshot is not None:
            signals = snapshot.positive_liveness.get(sid)
            owners = _reaper.live_owner_ids(snapshot)
    except Exception:
        signals = None
        owners = set()

    pid = record.get("pid")
    identity = {
        "pid": pid,
        "proc_create_time": record.get("proc_create_time"),
        "live_create_time": getattr(signals, "owner_create_time", None),
        "image_path": None,
    }
    try:
        if snapshot is not None and pid is not None:
            tup = snapshot.pid_identity.get(int(pid))
            if tup is not None:
                identity["image_path"] = tup[2]
    except Exception:
        pass

    corroborated = _reaper.has_corroborated_positive(signals)
    confirmed_dead = bool(getattr(signals, "owner_confirmed_dead", False))
    positive = {
        "owner_alive": bool(getattr(signals, "owner_alive", False)),
        "owner_confirmed_dead": confirmed_dead,
        "index_lock": bool(getattr(signals, "index_lock", False)),
        "heartbeat_fresh": bool(getattr(signals, "heartbeat_fresh", False)),
        "socket_owned": bool(getattr(signals, "socket_owned", False)),
        "work_mtime_fresh": bool(getattr(signals, "work_mtime_fresh", False)),
        "cpu_active": bool(getattr(signals, "cpu_active", False)),
        "owner_probe_unknown": bool(getattr(signals, "owner_probe_unknown", False)),
    }
    try:
        age_protected = _reaper.age_protected(record, snapshot, now=now)
    except Exception:
        age_protected = True
    predicates = {
        "has_live_owner": sid in owners,
        "corroborated_positive": corroborated,
        "confirmed_dead": confirmed_dead,
        "age_protected": bool(age_protected),
    }
    return {
        "kind": "decision",
        "ts": now,
        "session_id": sid,
        "decision": decision,
        "predicates": predicates,
        "identity": identity,
        "positive_liveness": positive,
        "corroborated_positive": corroborated,
        "confirmed_dead": confirmed_dead,
        "age_source": _age_source(record, snapshot),
    }


# ─────────────────────────────────────────────────────────────────────────────
# SWEEP SUMMARIES + THE ARM STATISTICS (recomputed from the VERIFIED chain)
# ─────────────────────────────────────────────────────────────────────────────

def record_sweep(tier, *, clean, abstained, counts=None, arm_event=False,
                 now=None) -> dict:
    """Append a hash-chained per-sweep summary receipt.

    ``clean``     — the sweep observed a good (non-degraded) snapshot AND produced
                    no false-positive: it COUNTS toward the arm bar.
    ``abstained`` — the sweep could NOT observe liveness (degraded/None snapshot):
                    it feeds the consecutive-abstain health banner and RESETS the
                    clean-sweep streak.
    ``arm_event`` — this sweep is the passing sweep recorded at an arm/advance.
    """
    if now is None:
        now = time.time()
    return append_receipt({
        "kind": "sweep",
        "ts": now,
        "tier": tier,
        "clean": bool(clean),
        "abstained": bool(abstained),
        "counts": dict(counts or {}),
        "arm_event": bool(arm_event),
    })


@dataclass(frozen=True)
class ArmStats:
    """Arm statistics RECOMPUTED from the verified receipt chain.

    ``chain_ok``      — the receipt hash chain verified (no tampering);
    ``clean_streak``  — trailing run of consecutive CLEAN sweeps (the arm bar);
    ``abstain_streak``— trailing run of consecutive ABSTAIN sweeps (health banner);
    ``total_sweeps``  — number of sweep summaries in the chain.
    """
    chain_ok: bool = False
    clean_streak: int = 0
    abstain_streak: int = 0
    total_sweeps: int = 0


def receipt_stats() -> ArmStats:
    """Recompute :class:`ArmStats` from the on-disk chain — the ONLY source.

    NEVER reads a stored aggregate: the streaks are recomputed by walking the
    VERIFIED chain, so an inflated ``clean_streak`` written into the arm-state
    file (or anywhere else) cannot clear the arm bar. If the chain does not
    verify, ``chain_ok`` is ``False`` and both streaks are 0 (an untrustworthy
    log grants NO arm progress).
    """
    recs = read_receipts()
    ok, _bad = verify_chain(recs)
    if not ok:
        return ArmStats(chain_ok=False, clean_streak=0, abstain_streak=0,
                        total_sweeps=0)
    sweeps = [r for r in recs if isinstance(r, dict) and r.get("kind") == "sweep"]
    clean_streak = 0
    for r in reversed(sweeps):
        if r.get("clean"):
            clean_streak += 1
        else:
            break
    abstain_streak = 0
    for r in reversed(sweeps):
        if r.get("abstained"):
            abstain_streak += 1
        else:
            break
    return ArmStats(chain_ok=True, clean_streak=clean_streak,
                    abstain_streak=abstain_streak, total_sweeps=len(sweeps))


# ─────────────────────────────────────────────────────────────────────────────
# THE ARM GATE — chain-verify + in-process recompute + fresh live probe
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class GateResult:
    """The outcome of evaluating the arm gate for a target tier."""
    passed: bool = False
    reason: str = ""
    target_tier: str = ""
    clean_streak: int = 0
    required: int = 0
    chain_ok: bool = False
    live_ok: bool = False


def _next_tier(current: str) -> Optional[str]:
    """The rung one step above ``current`` in the ladder, or ``None`` at the top."""
    try:
        i = LADDER.index(current)
    except ValueError:
        i = 0
    if i + 1 < len(LADDER):
        return LADDER[i + 1]
    return None


def evaluate_arm_gate(target_tier, *, snapshot=None, records=None,
                      min_sweeps=None, now=None, probe=None) -> GateResult:
    """Whether the ladder may advance to ``target_tier`` RIGHT NOW.

    THREE independent gates, ALL required (criterion 12):

      1. **Chain-verify** the receipt log — a forged/edited log FAILS here.
      2. **In-process recompute** the clean-sweep streak from the VERIFIED chain
         (never a stored aggregate) and require it ≥ the numeric bar
         (``ANCHOR_REAPER_ARM_MIN_SWEEPS``) — an under-bar log FAILS here.
      3. **Fresh live probe** — build a live snapshot at arm time (or use the one
         supplied) and require it NON-degraded, so arming is judged against the
         live harness, never a stale aggregate.

    Defensively bounded: any fault → not-passed (never arm on uncertainty).
    """
    if target_tier not in (TIER_FREEZE, TIER_KILL):
        return GateResult(passed=False, reason=f"not an armable tier: {target_tier}",
                          target_tier=target_tier)
    if min_sweeps is None:
        min_sweeps = _paths.reaper_arm_min_sweeps()

    # (1)+(2): chain-verify then recompute from the verified chain.
    stats = receipt_stats()
    if not stats.chain_ok:
        return GateResult(passed=False, reason="receipt chain failed verification "
                          "(tampered/forged log)", target_tier=target_tier,
                          required=min_sweeps, chain_ok=False)
    if stats.clean_streak < min_sweeps:
        return GateResult(passed=False,
                          reason=f"under bar: {stats.clean_streak}/{min_sweeps} "
                                 "consecutive clean sweeps",
                          target_tier=target_tier, clean_streak=stats.clean_streak,
                          required=min_sweeps, chain_ok=True)

    # (3): a FRESH in-process live snapshot at arm time.
    live_ok = False
    try:
        snap = snapshot
        if snap is None:
            snap = _reaper.build_snapshot(records=records, probe=probe, now=now)
        live_ok = snap is not None and not getattr(snap, "degraded", False)
    except Exception:
        live_ok = False
    if not live_ok:
        return GateResult(passed=False, reason="live harness degraded at arm time",
                          target_tier=target_tier, clean_streak=stats.clean_streak,
                          required=min_sweeps, chain_ok=True, live_ok=False)

    return GateResult(passed=True, reason="ok", target_tier=target_tier,
                      clean_streak=stats.clean_streak, required=min_sweeps,
                      chain_ok=True, live_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# THE CONTROL PLANE — token-authed arm / advance / disarm
# ─────────────────────────────────────────────────────────────────────────────

def _unauth(current):
    return {"ok": False, "error": "unauthorized", "changed": False,
            "tier": current}


def _advance_to(target_tier, provided_token, *, snapshot=None, records=None,
                min_sweeps=None, now=None, probe=None) -> dict:
    """Shared arm/advance body: auth → gate → persist the passing sweep + tier."""
    current = persisted_tier()
    if not _paths.auth_ok(provided_token):
        # Refused with NO state change (criterion 10 / control-plane).
        return _unauth(current)
    if is_disarmed():
        return {"ok": False, "changed": False, "tier": current,
                "error": "kill-switch brake engaged (.anchor/reaper.disarmed); "
                         "release it before arming"}
    gate = evaluate_arm_gate(target_tier, snapshot=snapshot, records=records,
                             min_sweeps=min_sweeps, now=now, probe=probe)
    if not gate.passed:
        return {"ok": False, "changed": False, "tier": current,
                "error": gate.reason, "gate": _gate_dict(gate)}
    if now is None:
        now = time.time()
    # Record the passing sweep as the ARM EVENT (into the tamper-evident chain).
    record_sweep(target_tier, clean=True, abstained=False, arm_event=True,
                 counts={"arm_from": current, "arm_to": target_tier}, now=now)
    _save_arm_state({
        "tier": target_tier,
        "armed_at": now,
        "armed_from": current,
        "clean_streak_at_arm": gate.clean_streak,
    })
    return {"ok": True, "changed": True, "tier": target_tier,
            "gate": _gate_dict(gate)}


def _gate_dict(gate: GateResult) -> dict:
    return {"passed": gate.passed, "reason": gate.reason,
            "target_tier": gate.target_tier, "clean_streak": gate.clean_streak,
            "required": gate.required, "chain_ok": gate.chain_ok,
            "live_ok": gate.live_ok}


def arm(provided_token, *, snapshot=None, records=None, min_sweeps=None,
        now=None, probe=None) -> dict:
    """ARM the first rung: advance from :data:`TIER_LOG` to :data:`TIER_FREEZE`.

    Token-authed (``paths.auth_ok``); refused with no state change when the token
    is invalid. Gated by :func:`evaluate_arm_gate`. Idempotent-ish: arming when
    already at/above FREEZE just re-affirms the gate for FREEZE.
    """
    current = persisted_tier()
    if current in (TIER_FREEZE, TIER_KILL):
        # Already armed at/above the freeze rung — auth-check then no-op.
        if not _paths.auth_ok(provided_token):
            return _unauth(current)
        return {"ok": True, "changed": False, "tier": current,
                "note": "already armed at or above freeze"}
    return _advance_to(TIER_FREEZE, provided_token, snapshot=snapshot,
                       records=records, min_sweeps=min_sweeps, now=now, probe=probe)


def advance(provided_token, *, snapshot=None, records=None, min_sweeps=None,
            now=None, probe=None) -> dict:
    """ADVANCE one rung up the ladder (log→freeze→kill), gated at each step.

    Token-authed; refused with no state change when unauthed. Refuses to advance
    a rung whose numeric bar is unmet (:func:`evaluate_arm_gate`). A no-op at the
    top rung.
    """
    current = persisted_tier()
    nxt = _next_tier(current)
    if nxt is None:
        if not _paths.auth_ok(provided_token):
            return _unauth(current)
        return {"ok": True, "changed": False, "tier": current,
                "note": "already at the top rung"}
    return _advance_to(nxt, provided_token, snapshot=snapshot, records=records,
                       min_sweeps=min_sweeps, now=now, probe=probe)


def disarm(provided_token, *, now=None, engage=True) -> dict:
    """DISARM: drop back to :data:`TIER_LOG` (dry-run) — always allowed if authed.

    Token-authed; refused with no state change when unauthed. Disarming is never
    gated — the reaper may always be made SAFER. By default it also engages the
    restart-durable kill-switch brake (``.anchor/reaper.disarmed``) so the disarm
    survives a restart even if the arm-state file is later restored.
    """
    current = persisted_tier()
    if not _paths.auth_ok(provided_token):
        return _unauth(current)
    if now is None:
        now = time.time()
    _save_arm_state({"tier": TIER_LOG, "disarmed_at": now, "disarmed_from": current})
    if engage:
        try:
            engage_brake()
        except Exception:  # pragma: no cover - brake is best-effort
            pass
    record_sweep(TIER_LOG, clean=False, abstained=False,
                 counts={"disarmed_from": current}, now=now)
    return {"ok": True, "changed": current != TIER_LOG, "tier": TIER_LOG,
            "braked": bool(engage)}


# ─────────────────────────────────────────────────────────────────────────────
# THE AUTO-THAW WATCHDOG (bounds every freeze — criterion 10, freeze-only rung)
# ─────────────────────────────────────────────────────────────────────────────

def auto_thaw_expired(*, now=None, resume=None) -> tuple:
    """Thaw every persisted freeze whose auto-thaw deadline has passed.

    A freeze bounded by a ``thaw_deadline`` (set by :func:`freeze_only_sweep`) is
    automatically resumed once ``now`` passes it, so a freeze can never be
    forgotten forever. Restart-durable: the deadline rides the persisted
    :class:`freeze_state.FrozenEntry`, so a sweep after a restart still thaws an
    expired freeze. Returns the tuple of thawed session ids. Best-effort.
    """
    if now is None:
        now = time.time()
    thawed = []
    try:
        entries = _fz.load_frozen()
    except Exception:
        return ()
    for sid, entry in entries.items():
        deadline = getattr(entry, "thaw_deadline", None)
        if (entry.state == _fz.STATE_FROZEN and deadline is not None
                and now >= deadline):
            try:
                _fz.thaw_session(sid, resume=resume)
                thawed.append(sid)
            except Exception:  # pragma: no cover - thaw is best-effort
                pass
    return tuple(thawed)


# ─────────────────────────────────────────────────────────────────────────────
# THE ARMED SWEEP — dispatches by effective tier; every action re-derived live
# ─────────────────────────────────────────────────────────────────────────────

def armed_sweep(records, snapshot, *, killer=None, freezer=None, resume=None,
                revalidate=None, now=None, probe=None, apply=True,
                write_receipts=True) -> dict:
    """Run ONE sweep at the current effective tier over ``records``/``snapshot``.

    The tier is :func:`effective_tier` (the kill-switch brake forces LOG). Every
    destructive action is RE-DERIVED in-process from the live ``snapshot`` via
    :func:`reaper.kill_authorized` — a persisted ``kill`` tier never kills a
    session whose owner is alive. The freeze-only tier freezes only
    confirmed-dead-owner + no-corroborated-signal candidates and ABSTAINS on any
    corroborated positive signal; each freeze is bounded by the auto-thaw
    watchdog. Writes owner-evidence receipts + a per-sweep summary into the
    tamper-evident chain (when ``write_receipts``).

    Returns a report dict. ``apply=False`` forces a pure dry-run classification
    regardless of tier (no process is ever touched).
    """
    if now is None:
        now = time.time()
    tier = effective_tier()
    report = {
        "tier": tier, "swept_at": now, "degraded": False,
        "frozen": [], "killed": [], "would_freeze": [], "would_kill": [],
        "abstained": [], "kept": [], "deferred": [], "protected": [],
    }
    recs = list(records or [])

    # Auto-thaw any expired freezes first (self-healing watchdog).
    try:
        auto_thaw_expired(now=now, resume=resume)
    except Exception:
        pass

    # Degraded/None snapshot → an ABSTAIN sweep: observe nothing, act on nothing.
    if snapshot is None or getattr(snapshot, "degraded", False):
        report["degraded"] = True
        for rec in recs:
            report["abstained"].append(rec.get("session_id"))
        if write_receipts:
            for rec in recs:
                append_receipt(build_decision_receipt(
                    rec, snapshot, DECISION_ABSTAIN, now=now))
            record_sweep(tier, clean=False, abstained=True,
                         counts={"abstained": len(recs)}, now=now)
        return report

    # Bounded destructive plan (blast cap + boot grace + lineage + kill_authorized).
    try:
        plan = _reaper.plan_sweep(recs, snapshot, now=now, revalidate=revalidate,
                                  probe=probe)
    except Exception:
        plan = _reaper.SweepPlan()
    to_act = set(plan.to_act)
    report["deferred"] = list(plan.deferred)
    report["protected"] = list(plan.protected)

    if killer is None:
        try:
            import proc_probe
            killer = proc_probe.tree_kill
        except Exception:  # pragma: no cover
            killer = lambda _p: False

    owners = _reaper.live_owner_ids(snapshot)
    receipts = []
    for rec in recs:
        sid = rec.get("session_id")
        if not sid:
            continue
        signals = snapshot.positive_liveness.get(sid)
        try:
            verdict = _reaper.classify(rec, owners, snapshot.positive_liveness)
        except Exception:
            verdict = _reaper.VERDICT_ABSTAIN

        decision = DECISION_KEEP
        if sid in to_act:
            # A confirmed-dead-owner orphan, past every bound (kill_authorized).
            if tier == TIER_LOG or not apply:
                decision = DECISION_WOULD_KILL
                if apply and write_receipts:
                    try:
                        _fz.mark_would_kill(rec, now=now, reason="reaper dry-run")
                    except Exception:
                        pass
            elif tier == TIER_FREEZE:
                # Belt-and-suspenders: never freeze on a corroborated signal.
                if _reaper.has_corroborated_positive(signals):
                    decision = DECISION_ABSTAIN
                else:
                    deadline = now + _paths.reaper_freeze_max_secs()
                    try:
                        out = _fz.freeze_session(
                            rec, suspend=freezer, now=now,
                            reason="reaper freeze-only tier",
                            thaw_deadline=deadline)
                        decision = (DECISION_FREEZE if out.get("ok")
                                    else DECISION_ABSTAIN)
                    except Exception:
                        decision = DECISION_ABSTAIN
            elif tier == TIER_KILL:
                # Re-derive authorization from the LIVE snapshot every time — a
                # persisted 'kill' tier NEVER kills without this fresh check.
                try:
                    authorized = _reaper.kill_authorized(
                        rec, snapshot, revalidate=revalidate)
                except Exception:
                    authorized = False
                if authorized:
                    try:
                        killer(rec.get("pid"))
                    except Exception:  # pragma: no cover - killer is injected
                        pass
                    decision = DECISION_KILL
                else:
                    decision = DECISION_WOULD_KILL
        else:
            # Not an authorized candidate. A KILL verdict (live, unowned — no
            # positive proof of death, possibly a corroborated positive signal)
            # is conservatively ABSTAINED, never acted on by any tier; every
            # other verdict is a plain KEEP.
            if verdict in (_reaper.VERDICT_KILL, _reaper.VERDICT_ABSTAIN):
                decision = DECISION_ABSTAIN
            else:
                decision = DECISION_KEEP

        _bucket(report, decision, sid)
        if write_receipts:
            receipts.append(build_decision_receipt(rec, snapshot, decision, now=now))

    if write_receipts:
        for body in receipts:
            append_receipt(body)
        # A non-degraded sweep observed cleanly and (by construction) mis-acted on
        # nothing — it COUNTS toward the arm bar.
        record_sweep(
            tier, clean=True, abstained=False,
            counts={k: len(report[k]) for k in
                    ("frozen", "killed", "would_kill", "abstained", "kept")},
            now=now)
    return report


def _bucket(report, decision, sid):
    if decision == DECISION_FREEZE:
        report["frozen"].append(sid)
    elif decision == DECISION_KILL:
        report["killed"].append(sid)
    elif decision == DECISION_WOULD_FREEZE:
        report["would_freeze"].append(sid)
    elif decision == DECISION_WOULD_KILL:
        report["would_kill"].append(sid)
    elif decision == DECISION_ABSTAIN:
        report["abstained"].append(sid)
    else:
        report["kept"].append(sid)


# ─────────────────────────────────────────────────────────────────────────────
# HEALTH BANNER (consecutive-abstain streak) + reaper-explain (read-only)
# ─────────────────────────────────────────────────────────────────────────────

def health_banner(*, k=None) -> Optional[dict]:
    """The dashboard health banner, or ``None`` when nothing is wrong.

    Trips when the reaper has ABSTAINED (degraded / could-not-observe liveness)
    for MORE than ``K`` consecutive sweeps (``ANCHOR_REAPER_ABSTAIN_BANNER_K``) —
    a signal the liveness inputs are broken and the reaper is flying blind. Also
    trips (informationally) when the receipt chain fails verification.
    """
    if k is None:
        k = _paths.reaper_abstain_banner_k()
    stats = receipt_stats()
    if not stats.chain_ok:
        return {"tripped": True, "kind": "chain-tampered",
                "message": "Reaper receipt chain failed verification — the "
                           "owner-evidence log may be tampered.",
                "streak": 0, "threshold": k}
    if stats.abstain_streak > k:
        return {"tripped": True, "kind": "abstain-streak",
                "streak": stats.abstain_streak, "threshold": k,
                "message": (f"Reaper has ABSTAINED for {stats.abstain_streak} "
                            f"consecutive sweeps (> {k}) — liveness inputs may be "
                            "broken; the reaper is flying blind and will not act.")}
    return None


def explain(records=None, *, snapshot=None, probe=None, now=None) -> dict:
    """A read-only diagnostic dump — the reaper-explain inspection surface.

    Returns the current snapshot summary, the live-owner set, each session's
    classification + its latest owner-evidence receipt, the current arm tier +
    distance-to-bar, the disarm/brake state, and the abstain-streak health
    banner. NEVER runs the model / kills / freezes — pure inspection.
    """
    if now is None:
        now = time.time()
    if records is None:
        try:
            import session_registry
            records = session_registry.list_sessions(status="running")
        except Exception:
            records = []
    if snapshot is None:
        try:
            snapshot = _reaper.build_snapshot(records=records, probe=probe, now=now)
        except Exception:
            snapshot = None

    owners = set()
    degraded = True
    try:
        if snapshot is not None:
            owners = _reaper.live_owner_ids(snapshot)
            degraded = bool(getattr(snapshot, "degraded", False))
    except Exception:
        owners = set()

    latest = _latest_decision_by_session()
    sessions = []
    for rec in records or []:
        sid = rec.get("session_id")
        try:
            verdict = _reaper.classify_record(rec, snapshot)
        except Exception:
            verdict = _reaper.VERDICT_ABSTAIN
        try:
            authorized = _reaper.kill_authorized(rec, snapshot)
        except Exception:
            authorized = False
        sessions.append({
            "session_id": sid,
            "classification": verdict,
            "has_live_owner": sid in owners,
            "kill_authorized": bool(authorized),
            "latest_receipt": latest.get(sid),
        })

    tier = persisted_tier()
    eff = effective_tier()
    stats = receipt_stats()
    required = _paths.reaper_arm_min_sweeps()
    nxt = _next_tier(tier)
    distance = None
    if nxt is not None:
        distance = max(0, required - stats.clean_streak)
    return {
        "persisted_tier": tier,
        "effective_tier": eff,
        "disarmed": is_disarmed(),
        "degraded": degraded,
        "live_owner_ids": sorted(o for o in owners if o),
        "sessions": sessions,
        "arm": {
            "tier": tier,
            "next_tier": nxt,
            "clean_streak": stats.clean_streak,
            "required": required,
            "distance_to_bar": distance,
            "abstain_streak": stats.abstain_streak,
            "chain_ok": stats.chain_ok,
            "total_sweeps": stats.total_sweeps,
        },
        "health_banner": health_banner(),
    }


def _latest_decision_by_session() -> dict:
    """Map session_id → its most-recent decision receipt (chain order)."""
    out = {}
    for rec in read_receipts():
        if isinstance(rec, dict) and rec.get("kind") == "decision":
            sid = rec.get("session_id")
            if sid:
                out[sid] = rec
    return out


def format_explain(dump: dict) -> str:
    """Render :func:`explain`'s dict as a compact text report for the CLI."""
    lines = []
    lines.append("REAPER STATUS")
    lines.append(f"  persisted tier : {dump.get('persisted_tier')}")
    eff = dump.get("effective_tier")
    brake = " (kill-switch brake ENGAGED — forced dry-run)" if dump.get("disarmed") else ""
    lines.append(f"  effective tier : {eff}{brake}")
    lines.append(f"  degraded probe : {dump.get('degraded')}")
    arm = dump.get("arm", {}) or {}
    nxt = arm.get("next_tier")
    if nxt:
        lines.append(f"  arm bar        : {arm.get('clean_streak')}/{arm.get('required')} "
                     f"clean sweeps (need {arm.get('distance_to_bar')} more to reach "
                     f"'{nxt}')")
    else:
        lines.append(f"  arm bar        : at top rung ({arm.get('clean_streak')} "
                     "clean sweeps)")
    lines.append(f"  abstain streak : {arm.get('abstain_streak')} "
                 f"(chain_ok={arm.get('chain_ok')}, sweeps={arm.get('total_sweeps')})")
    banner = dump.get("health_banner")
    if banner:
        lines.append(f"  HEALTH BANNER  : {banner.get('message')}")
    lines.append(f"  live owners    : {', '.join(dump.get('live_owner_ids') or []) or '(none)'}")
    sessions = dump.get("sessions", []) or []
    lines.append(f"  running sessions ({len(sessions)}):")
    for s in sessions:
        lines.append(f"    - {s.get('session_id')}: {s.get('classification')} "
                     f"(owner={s.get('has_live_owner')}, "
                     f"kill_authorized={s.get('kill_authorized')})")
    return "\n".join(lines)
