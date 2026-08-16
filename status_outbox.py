#!/usr/bin/env python3
"""Anchor S12 status outbox — PRODUCER #1 (host contract only).

Wave 13 of the Ecgberht steward-handoff plan. This module:

  * appends monotonic-seq status records to a fsync'd outbox (temp + fsync +
    rename, Windows sharing-violation retry — same pattern as session_registry)
  * renews a durable lease on an interval (no lease/heartbeat existed in
    job_runner — this is the emission substrate)
  * tracks process identity as (pid, proc_create_time) — never pid alone
  * NEVER writes the campaign ledger / roadmap.json (the Node mediator drains
    the outbox and emits status_flip through the Wave-6 single writer)

NS v5 non-goal: no propose/confirm, reflection, attention derivation, or
roadmap/status law in Anchor Python.

Stdlib only.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Optional

# ── Contract constants (must match Ecgberht engine/status-outbox.mjs) ────────

OUTBOX_SCHEMA = "ecgberht-status-outbox-v0"
OUTBOX_REL_PARTS = (".ecgberht", "status", "outbox.json")

# Lease law (must match engine/lease-law.mjs)
LEASE_TTL_MS = 30_000
LEASE_RENEW_INTERVAL_MS = 10_000
LEASE_STALE_FRACTION = 0.8
LEASE_HYSTERESIS_MS = 2_000

# Failure status codes (Master-Plan P6 table — host surfaces them; Node owns law)
LAUNCH_INTENT_STRANDED = "LAUNCH_INTENT_STRANDED"
RUN_DEAD_LEASE_EXPIRED = "RUN_DEAD_LEASE_EXPIRED"
STATUS_SEQUENCE_GAP = "STATUS_SEQUENCE_GAP"
OUTBOX_UNREADABLE = "OUTBOX_UNREADABLE"
NO_LIVE_RUNS = "NO_LIVE_RUNS"
RUN_LIVENESS_UNKNOWN = "RUN_LIVENESS_UNKNOWN"

WRITES_ROADMAP_LEDGER = False  # pin: Python NEVER writes the ledger

OUTBOX_EVENT_KINDS = frozenset(
    {
        "lease_renew",
        "run_status",
        "gate_surface",
        "launch_intent",
        "park",
        "unpark",
    }
)

# Bounded retry for Windows sharing-violation on os.replace (session_registry pattern)
_REPLACE_RETRIES = 40
_REPLACE_BACKOFF_S = 0.005


def _atomic_replace(tmp: str, target: str) -> None:
    """os.replace with bounded retry over transient Windows sharing violations."""
    for attempt in range(_REPLACE_RETRIES):
        try:
            os.replace(tmp, target)
            return
        except PermissionError:
            if attempt == _REPLACE_RETRIES - 1:
                raise
            time.sleep(_REPLACE_BACKOFF_S)


def atomic_write_json(target: Path, payload: dict) -> None:
    """Write JSON via temp + fsync + rename (S12 durability)."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2) + "\n"
    tmp = target.with_name(
        f".{target.name}.tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    )
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass
        _atomic_replace(str(tmp), str(target))
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def outbox_path(worktree: Path | str) -> Path:
    return Path(worktree).joinpath(*OUTBOX_REL_PARTS)


def empty_outbox(producer: str = "anchor") -> dict:
    return {
        "schema": OUTBOX_SCHEMA,
        "producer": producer,
        "records": [],
        "next_seq": 1,
    }


def read_outbox(worktree: Path | str) -> dict:
    """Read outbox. Unreadable → named failure (not empty)."""
    path = outbox_path(worktree)
    if not path.is_file():
        return {
            "ok": True,
            "exists": False,
            "path": str(path),
            "outbox": empty_outbox(),
            "empty": True,
        }
    try:
        raw = path.read_text(encoding="utf-8")
        if not raw.strip():
            return {
                "ok": True,
                "exists": True,
                "path": str(path),
                "outbox": empty_outbox(),
                "empty": True,
            }
        value = json.loads(raw)
        if not isinstance(value, dict):
            return {
                "ok": False,
                "status_code": OUTBOX_UNREADABLE,
                "user_text": (
                    "Status outbox unreadable — last durable status shown with its timestamp."
                ),
                "path": str(path),
            }
        records = value.get("records") if isinstance(value.get("records"), list) else []
        return {
            "ok": True,
            "exists": True,
            "path": str(path),
            "outbox": {
                "schema": value.get("schema") or OUTBOX_SCHEMA,
                "producer": value.get("producer") or "anchor",
                "records": records,
                "next_seq": int(value.get("next_seq") or (len(records) + 1)),
            },
        }
    except (OSError, json.JSONDecodeError) as e:
        return {
            "ok": False,
            "status_code": OUTBOX_UNREADABLE,
            "user_text": (
                "Status outbox unreadable — last durable status shown with its timestamp."
            ),
            "path": str(path),
            "detail": str(e),
        }


def append_outbox_record(
    worktree: Path | str,
    record: dict,
    *,
    producer: str = "anchor",
) -> dict:
    """Append one record with monotonic seq. Single appender per run."""
    if not isinstance(record, dict):
        return {"ok": False, "error": "record_not_object"}
    kind = record.get("kind")
    if kind not in OUTBOX_EVENT_KINDS:
        return {
            "ok": False,
            "error": "unknown_outbox_kind",
            "kind": kind,
            "allowed": sorted(OUTBOX_EVENT_KINDS),
        }

    path = outbox_path(worktree)
    read = read_outbox(worktree)
    if not read.get("ok"):
        return read
    box = dict(read["outbox"])
    box["producer"] = box.get("producer") or producer
    records = list(box.get("records") or [])
    seq = int(box.get("next_seq") or (len(records) + 1))
    entry = dict(record)
    entry["seq"] = seq
    entry["producer"] = box["producer"]
    if "wall_at" not in entry:
        entry["wall_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    records.append(entry)
    box["records"] = records
    box["next_seq"] = seq + 1
    box["schema"] = OUTBOX_SCHEMA
    atomic_write_json(path, box)
    return {
        "ok": True,
        "seq": seq,
        "record": entry,
        "path": str(path),
        "store": "S12",
        "writes_roadmap_ledger": WRITES_ROADMAP_LEDGER,
    }


def process_identity_tuple(
    pid: Optional[int] = None,
    proc_create_time: Optional[float] = None,
) -> tuple[Optional[int], Optional[float]]:
    """Identity is always (pid, proc_create_time) — never pid alone."""
    p = int(pid) if pid is not None else None
    ct = float(proc_create_time) if proc_create_time is not None else None
    return (p, ct)


def renew_lease(
    worktree: Path | str,
    *,
    run_id: str,
    step_id: Optional[str] = None,
    pid: Optional[int] = None,
    proc_create_time: Optional[float] = None,
    mono_ms: Optional[int] = None,
    producer: str = "anchor",
) -> dict:
    """Renew a durable lease as an S12 outbox record (interval caller)."""
    now_mono = int(mono_ms) if mono_ms is not None else int(time.monotonic() * 1000)
    p, ct = process_identity_tuple(pid, proc_create_time)
    return append_outbox_record(
        worktree,
        {
            "kind": "lease_renew",
            "run_id": run_id,
            "step_id": step_id,
            "pid": p,
            "proc_create_time": ct,
            "last_renew_mono_ms": now_mono,
            "ttl_ms": LEASE_TTL_MS,
            "renew_interval_ms": LEASE_RENEW_INTERVAL_MS,
        },
        producer=producer,
    )


def emit_run_status(
    worktree: Path | str,
    *,
    run_id: str,
    step_id: str,
    run_state: str,
    cause: Optional[str] = None,
    pid: Optional[int] = None,
    proc_create_time: Optional[float] = None,
    producer: str = "anchor",
) -> dict:
    """Emit a run_status record (mediator will status_flip through the spine)."""
    p, ct = process_identity_tuple(pid, proc_create_time)
    return append_outbox_record(
        worktree,
        {
            "kind": "run_status",
            "run_id": run_id,
            "step_id": step_id,
            "run_state": run_state,
            "cause": cause,
            "pid": p,
            "proc_create_time": ct,
            "client_event_id": f"status:{producer}:{run_id}:{run_state}:{cause or 'none'}",
        },
        producer=producer,
    )


def emit_gate_surface(
    worktree: Path | str,
    *,
    gate_id: str,
    run_id: str,
    question: Optional[str] = None,
    step_id: Optional[str] = None,
    skill: str = "crucible",
    halt_class: str = "EXTERNALLY-OBSERVABLE",
    producer: str = "anchor",
) -> dict:
    """First-class gate_surface outbox event."""
    return append_outbox_record(
        worktree,
        {
            "kind": "gate_surface",
            "gate_id": gate_id,
            "run_id": run_id,
            "step_id": step_id,
            "question": question,
            "skill": skill,
            "halt_class": halt_class,
            "client_event_id": f"gate:{run_id}:{gate_id}",
        },
        producer=producer,
    )


def lease_soft_stale_after_ms(ttl_ms: int = LEASE_TTL_MS) -> int:
    return int(ttl_ms * LEASE_STALE_FRACTION)
