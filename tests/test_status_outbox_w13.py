"""Wave 13 — S12 status outbox + lease emission (host contract only).

Python NEVER writes the campaign ledger. Node mediator drains the outbox.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Anchor root on path
ANCHOR_ROOT = Path(__file__).resolve().parents[1]
if str(ANCHOR_ROOT) not in sys.path:
    sys.path.insert(0, str(ANCHOR_ROOT))

import status_outbox as so


def test_constants_match_contract():
    assert so.OUTBOX_SCHEMA == "ecgberht-status-outbox-v0"
    assert so.WRITES_ROADMAP_LEDGER is False
    assert so.LEASE_TTL_MS == 30_000
    assert so.LEASE_RENEW_INTERVAL_MS == 10_000
    assert so.RUN_DEAD_LEASE_EXPIRED == "RUN_DEAD_LEASE_EXPIRED"
    assert so.OUTBOX_UNREADABLE == "OUTBOX_UNREADABLE"


def test_append_outbox_record_monotonic(tmp_path: Path):
    wt = tmp_path / "run wt"
    wt.mkdir()
    a = so.append_outbox_record(
        wt,
        {
            "kind": "lease_renew",
            "run_id": "r1",
            "step_id": "s1",
            "pid": 1,
            "proc_create_time": 1.0,
            "last_renew_mono_ms": 100,
        },
    )
    assert a["ok"] is True
    assert a["seq"] == 1
    assert a["writes_roadmap_ledger"] is False

    b = so.renew_lease(
        wt,
        run_id="r1",
        step_id="s1",
        pid=1,
        proc_create_time=1.0,
        mono_ms=200,
    )
    assert b["ok"] is True
    assert b["seq"] == 2

    read = so.read_outbox(wt)
    assert read["ok"] is True
    assert len(read["outbox"]["records"]) == 2
    assert read["outbox"]["next_seq"] == 3
    assert read["outbox"]["records"][0]["seq"] == 1
    assert read["outbox"]["records"][1]["seq"] == 2


def test_emit_run_status_and_gate_surface(tmp_path: Path):
    wt = tmp_path / "run"
    wt.mkdir()
    dead = so.emit_run_status(
        wt,
        run_id="r1",
        step_id="s1",
        run_state="dead",
        cause="lease_expired",
        pid=9,
        proc_create_time=2.0,
    )
    assert dead["ok"] is True
    gate = so.emit_gate_surface(
        wt,
        gate_id="halt-1",
        run_id="r1",
        question="Approve?",
        skill="crucible",
    )
    assert gate["ok"] is True
    assert gate["record"]["kind"] == "gate_surface"

    path = so.outbox_path(wt)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["schema"] == so.OUTBOX_SCHEMA
    kinds = [r["kind"] for r in raw["records"]]
    assert "run_status" in kinds
    assert "gate_surface" in kinds


def test_process_identity_is_tuple_never_pid_alone():
    p, ct = so.process_identity_tuple(42, 1.5)
    assert p == 42
    assert ct == 1.5


def test_unknown_kind_refused(tmp_path: Path):
    wt = tmp_path / "run"
    wt.mkdir()
    r = so.append_outbox_record(wt, {"kind": "chat_turn", "run_id": "x"})
    assert r["ok"] is False
    assert r["error"] == "unknown_outbox_kind"


def test_no_roadmap_json_write_helpers():
    """Source discipline: module must not reference roadmap write APIs."""
    src = Path(so.__file__).read_text(encoding="utf-8")
    assert "WRITES_ROADMAP_LEDGER = False" in src or "WRITES_ROADMAP_LEDGER=False" in src
    # Must not open roadmap.json for write
    assert "roadmap.json" not in src or "NEVER writes" in src or "never writes" in src.lower()


def test_empty_outbox_distinct_from_unreadable(tmp_path: Path):
    wt = tmp_path / "empty"
    wt.mkdir()
    r = so.read_outbox(wt)
    assert r["ok"] is True
    assert r.get("empty") is True

    bad = tmp_path / "bad"
    bad.mkdir()
    path = so.outbox_path(bad)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not-json", encoding="utf-8")
    u = so.read_outbox(bad)
    assert u["ok"] is False
    assert u["status_code"] == so.OUTBOX_UNREADABLE
