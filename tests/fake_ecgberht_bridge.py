#!/usr/bin/env python3
"""Deterministic stub for Ecgberht's commission-run bridge (steward run-loop).

Stands in for ``node scripts/commission-run-bridge.mjs <mode>`` so the pytest
gate NEVER spawns Node or a real seat call. Wired via the
``ANCHOR_ECGBERHT_BRIDGE_CMD`` indirection (same pattern as ANCHOR_RUNNER_CMD):
tests set ``ANCHOR_ECGBERHT_BRIDGE_CMD=python <abs>/tests/fake_ecgberht_bridge.py``.

Contract mirrored from the real bridge: mode on argv[1], payload as ONE JSON
object on stdin, one-line JSON reply on stdout, exit 0 iff ok.

Recording: when ``FAKE_BRIDGE_DIR`` is set, every call appends
``{mode, payload}`` as a JSON line to ``<dir>/calls.jsonl`` so tests can assert
exactly what crossed the seam. A file ``<dir>/reply-<mode>.json`` overrides the
canned reply for that mode; ``<dir>/fail-<mode>`` makes the mode fail.
"""
import json
import os
import sys
from pathlib import Path


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else None
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        print(json.dumps({"ok": False, "error": "payload_unparseable"}))
        return 1

    rec_dir = os.environ.get("FAKE_BRIDGE_DIR", "").strip()
    if rec_dir:
        d = Path(rec_dir)
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "calls.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"mode": mode, "payload": payload}) + "\n")
        override = d / f"reply-{mode}.json"
        if override.exists():
            reply = json.loads(override.read_text(encoding="utf-8"))
            print(json.dumps(reply))
            return 0 if reply.get("ok") else 1
        if (d / f"fail-{mode}").exists():
            print(json.dumps({"ok": False, "error": "forced_failure", "mode": mode}))
            return 1

    if mode == "propose-active":
        reply = {
            "ok": True,
            "mode": mode,
            "kind": "commission_proposal",
            "requires_confirm": True,
            "confirmed": False,
            "proposal_id": "prop-fake-1",
            "step_id": payload.get("step_id") or "s1",
            "step": {"name": "Order the syllabus decisions", "done_when": "decisions locked"},
            "skill": payload.get("skill") or "Crucible",
            "step_name": "Order the syllabus decisions",
        }
    elif mode == "confirm":
        prop = payload.get("proposal") or {}
        reply = {
            "ok": True,
            "mode": mode,
            "confirmed": True,
            "job": {
                "job_id": "job-fake-1",
                "commission_id": "comm-fake-1",
                "skill": prop.get("skill") or "Crucible",
                "step_id": prop.get("step_id") or "s1",
            },
        }
    elif mode == "ingest-run":
        run = payload.get("run") or {}
        reply = {
            "ok": True,
            "mode": mode,
            "outcome": run.get("outcome"),
            "report": {
                "say": "Fake report: the run stopped and here is what it means.",
                "produced": [],
                "needs": "Which option?" if run.get("outcome") == "asked" else None,
                "recommend": "Answer in the session.",
            },
            "raised": run.get("outcome") in ("asked", "quiet", "died", "timeout"),
            "handback": {"ok": True, "ingested": False, "reason": "no_ingestable_handback"},
        }
    else:
        reply = {"ok": False, "error": "unknown_mode", "mode": mode}

    print(json.dumps(reply))
    return 0 if reply.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
