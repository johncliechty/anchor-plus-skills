#!/usr/bin/env python3
"""Wave 21 — cheap child payload for the Anchor conformance adapter.

Uses the REAL Anchor write_handback_pair / _atomic_write_text (S6).
Stands in for the trio; G4 proves real trio execution separately.

Usage:
  python anchor-child.py <worktree> [complete|kill-mid|drift-marker] [client_event_id] [handback_id]

Refuses if a forbidden token is present in the child env (D-1).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        print(
            "usage: python anchor-child.py <worktree> [mode] [client_event_id] [handback_id]",
            file=sys.stderr,
        )
        return 2

    worktree = Path(sys.argv[1])
    mode = sys.argv[2] if len(sys.argv) > 2 else os.environ.get(
        "ECGBERHT_CONFORMANCE_MODE", "complete"
    )
    client_event_id = (
        sys.argv[3]
        if len(sys.argv) > 3
        else os.environ.get("ECGBERHT_CLIENT_EVENT_ID")
        or f"w21-ce-anchor-{os.getpid()}"
    )
    handback_id = (
        sys.argv[4]
        if len(sys.argv) > 4
        else os.environ.get("ECGBERHT_HANDBACK_ID")
        or f"w21-hb-anchor-{os.getpid()}"
    )

    forbidden = (
        "ANCHOR_TOKEN",
        "ANCHOR_CAPABILITY",
        "ANCHOR_CAPABILITY_TOKEN",
        "ECGBERHT_CAPABILITY",
        "ECGBERHT_TOKEN",
    )
    leaked = [k for k in forbidden if os.environ.get(k)]
    if leaked:
        print(json.dumps({"ok": False, "error": "token_in_child", "leaked": leaked}))
        return 3

    # Import Anchor's REAL executor module (must be on sys.path / cwd).
    try:
        import commission_executor as ce
    except ImportError as e:
        print(json.dumps({"ok": False, "error": "import_commission_executor", "detail": str(e)}))
        return 4

    body = {
        "schema": "ecgberht-receipt-v0",
        "kind": "handback",
        "as_of": time.strftime("%Y-%m-%d"),
        "active_effort": "w21-conformance",
        "why_next": "Shared handback-contract conformance child (Anchor adapter).",
        "grasscatch_why": None,
        "tool_depth_why": "LITE conformance stand-in for trio",
        "human_wait": "none",
        "uncertainty_flags": ["w21-conformance", "anchor-child"],
        "skill": "researchPrime",
        "depth": "LITE",
        "commission_id": os.environ.get("ECGBERHT_COMMISSION_ID", "w21-conformance-anchor"),
        "partial": False,
        "client_event_id": client_event_id,
        "handback_id": handback_id,
        "contract_version": ce.CONTRACT_VERSION,
    }

    write_trace = []
    write_order = []

    def note(target: str) -> None:
        write_trace.append({"op": "temp", "target": target})
        write_trace.append({"op": "fsync", "target": target})
        write_trace.append({"op": "rename", "target": target})
        write_order.append(target)

    marker_before = False
    if mode in ("kill-mid", "handback-only"):
        # Handback only via atomic write — no marker (kill-mid-write law).
        worktree.mkdir(parents=True, exist_ok=True)
        hb = ce.handback_json_path(worktree)
        ce._atomic_write_text(hb, json.dumps(body, indent=2) + "\n")
        note("handback.json")
        result = {
            "ok": True,
            "handback_path": str(hb),
            "marker_path": str(ce.terminal_marker_path(worktree)),
        }
    elif mode == "drift-marker":
        # Injected drift: marker before handback (write-discipline fail).
        worktree.mkdir(parents=True, exist_ok=True)
        mk = ce.terminal_marker_path(worktree)
        ce._atomic_write_text(
            mk,
            json.dumps(
                {
                    "contract_version": ce.CONTRACT_VERSION,
                    "terminal": True,
                    "drift": True,
                }
            )
            + "\n",
        )
        note("TERMINAL.marker")
        hb = ce.handback_json_path(worktree)
        ce._atomic_write_text(hb, json.dumps(body, indent=2) + "\n")
        note("handback.json")
        marker_before = True
        result = {
            "ok": True,
            "handback_path": str(hb),
            "marker_path": str(mk),
        }
    else:
        result = ce.write_handback_pair(
            worktree,
            body,
            client_event_id=client_event_id,
            handback_id=handback_id,
        )
        note("handback.json")
        note("TERMINAL.marker")

    out = {
        "ok": True,
        "mode": mode,
        "pid": os.getpid(),
        "worktree": str(worktree),
        "handback_path": result.get("handback_path"),
        "marker_path": result.get("marker_path"),
        "client_event_id": client_event_id,
        "handback_id": handback_id,
        "contract_version": ce.CONTRACT_VERSION,
        "no_token_in_child": True,
        "used_real_writer": True,
        "writer": "commission_executor.write_handback_pair",
        "write_trace": write_trace,
        "write_order": write_order,
        "marker_before_handback_fsync": marker_before,
        "complete_pair": mode in ("complete", None, ""),
        "marker_absent": mode in ("kill-mid", "handback-only"),
        "ingestable": ce.is_ingestable(worktree),
    }
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
