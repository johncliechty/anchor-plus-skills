#!/usr/bin/env python3
"""STUB Stage-A runner — emits a canned Gandalf RAW draft in a result envelope.

Wired in via ``ANCHOR_RUNNER_CMD`` (like ``tests/fake_claude.py`` /
``tests/stub_streamjson.py``) so a Gandalf engine test never calls real
``claude``. It emits the production stream-json envelope shape (a terminal
``{"type":"result","result":"<raw draft JSON>"}`` line) carrying ONE compact
RAW-draft JSON object per ``runtime/RAW-DRAFT-CONTRACT.md`` — the un-stamped
findings/elevations the host then grades.

Override the emitted draft via ``STUB_GANDALF_DRAFT`` (a JSON string). When set
to the literal ``UNPARSEABLE``, emit prose with NO balanced JSON object so the
Stage-A unparseable-draft degrade path can be exercised. Exit 0.

NEVER live — a STUB only. Stdlib only.
"""
import json
import os
import sys


#: A minimal but contract-valid RAW draft (the model's un-stamped output).
_DEFAULT_DRAFT = {
    "reasoning": "The project has a clear objective and a coherent structure; the "
                 "trio docs are present and the test gate is green.",
    "verdict": "This is broadly sound, with one durability gap worth watching.",
    "findings": [
        {
            "id": "d-1",
            "kind": "diagnose",
            "rung": "OBSERVED",
            "reasoning": "The test gate runs green at the documented baseline.",
            "verdict": "The build is in a healthy, tested state.",
            "severity": "minor",
        }
    ],
    "nitpicks": [
        {
            "id": "n-1",
            "rung": "CLAIMED",
            "reasoning": "A few docstrings drift from the current behavior.",
            "verdict": "Minor doc drift; low stakes.",
        }
    ],
    "elevations": [
        {
            "id": "e-1",
            "value_if_true": "medium",
            "rung": "UNVERIFIED",
            "reasoning": "A periodic re-analysis would catch drift earlier.",
            "verdict": "Consider scheduling a recurring read.",
            "what_would_refute_it": "If drift never recurs across three release "
                                    "cycles, the scheduling cost is unjustified.",
        }
    ],
}


def main():
    counter = os.environ.get("STUB_GANDALF_COUNTER")
    if counter:
        try:
            with open(counter, "a", encoding="utf-8") as fh:
                fh.write("x")
        except OSError:
            pass

    raw = (os.environ.get("STUB_GANDALF_DRAFT") or "").strip()
    if raw == "UNPARSEABLE":
        answer = "I analyzed the project but could not produce structured output."
    elif raw:
        answer = raw
    else:
        answer = json.dumps(_DEFAULT_DRAFT, ensure_ascii=False)

    def emit(obj):
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()

    emit({"type": "system", "subtype": "init", "session_id": "stub-gandalf"})
    emit({"type": "assistant",
          "message": {"role": "assistant",
                      "content": [{"type": "text", "text": answer}]},
          "session_id": "stub-gandalf"})
    emit({"type": "result", "subtype": "success", "is_error": False,
          "result": answer, "total_cost_usd": 0.0,
          "usage": {"input_tokens": 1, "output_tokens": 1},
          "duration_ms": 1, "session_id": "stub-gandalf"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
