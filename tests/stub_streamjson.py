#!/usr/bin/env python3
"""STUB runner that emits REAL ``claude -p --output-format stream-json`` output.

The other stubs (``fake_claude.py`` / ``stub_summarizer.py``) emit BARE text
lines — which is NOT what production ``claude`` emits. Production output is NDJSON
envelopes (``{"type":"assistant",...}`` / ``{"type":"result",...}``), and the
summarizer's old parser skipped every ``{"type":...}`` line, so it discarded
100% of the model's text in production (every cached project summary was empty).

This stub reproduces the production envelope shape so a test can prove the
summarizer extracts text from REAL stream-json — the regression guard for that
bug. Each line of ``STUB_STREAMJSON_CLAIMS`` (``\\n``-joined) becomes one line of
the model's answer, delivered BOTH as an ``assistant`` text frame and inside the
terminal ``result`` envelope (exactly as ``claude -p`` does). Exit 0.

NEVER live — a STUB only. Stdlib only.
"""
import json
import os
import sys


def main():
    counter = os.environ.get("STUB_STREAMJSON_COUNTER")
    if counter:
        try:
            with open(counter, "a", encoding="utf-8") as fh:
                fh.write("x")
        except OSError:
            pass

    raw = os.environ.get("STUB_STREAMJSON_CLAIMS", "")
    claims = [c for c in raw.split("\n") if c.strip() != ""]
    if not claims:
        claims = ["fake claim"]
    answer = "\n".join(claims)

    def emit(obj):
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()

    # 1. system init frame.
    emit({"type": "system", "subtype": "init", "session_id": "stub"})
    # 2. assistant text frame carrying the answer (content blocks).
    emit({"type": "assistant",
          "message": {"role": "assistant",
                      "content": [{"type": "text", "text": answer}]},
          "session_id": "stub"})
    # 3. terminal result envelope (the canonical -p final answer + cost).
    emit({"type": "result", "subtype": "success", "is_error": False,
          "result": answer, "total_cost_usd": 0.0,
          "usage": {"input_tokens": 1, "output_tokens": 1},
          "duration_ms": 1, "session_id": "stub"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
