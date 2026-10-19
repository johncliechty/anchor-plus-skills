#!/usr/bin/env python3
"""STUB agentic Gandalf runner — simulates the canonical skill run.

Wired via ``ANCHOR_RUNNER_CMD`` (override path appends the prompt as the trailing
argv). It mimics what a real ``run gandalf-heavy`` agent does: it WRITES a report
Markdown file to the path named in the prompt ("write the full report ... to this
exact path:\\n<path>"), then emits the production stream-json envelope whose final
text is a one-paragraph summary + a ``VERDICT:`` line — the shape ``run_gandalf``'s
agentic capture parses.

Env knobs:
- ``STUB_GANDALF_AGENTIC_NOREPORT=1`` — write NO report but STILL print a full
  summary + VERDICT, to exercise the honest "DONE + prose but no report -> failure"
  path (a green tile must require a real report).
- ``STUB_GANDALF_AGENTIC_EMPTY_REPORT=1`` — write a ZERO-BYTE report.md, to exercise
  the "empty report can't count as success" path.
- ``STUB_GANDALF_AGENTIC_ADVISOR=1`` — also write an ``advisor-output.json`` graded
  envelope (cross_model:true) next to the report, to exercise the graded-chip path.

NEVER live — a STUB only. Stdlib only. Exit 0.
"""
import json
import os
import re
import sys


def _report_path_from_prompt(argv):
    """The prompt is the trailing argv token; extract the report path after the
    'to this exact path:' marker."""
    for tok in reversed(argv):
        m = re.search(r"exact path:\s*\n?\s*(\S[^\n]*)", tok or "")
        if m:
            return m.group(1).strip()
    return ""


def main():
    argv = sys.argv[1:]
    noreport = os.environ.get("STUB_GANDALF_AGENTIC_NOREPORT") == "1"
    empty = os.environ.get("STUB_GANDALF_AGENTIC_EMPTY_REPORT") == "1"
    report_path = _report_path_from_prompt(argv)

    if report_path and not noreport:
        try:
            d = os.path.dirname(report_path)
            if d:
                os.makedirs(d, exist_ok=True)
            with open(report_path, "w", encoding="utf-8") as fh:
                if not empty:
                    fh.write("# Gandalf report (stub)\n\n"
                             "## Summary\nA coherent project with a clear objective.\n\n"
                             "## Weaknesses\nThin test coverage at the edges.\n\n"
                             "## Next steps\nAdd integration tests.\n")
                # empty → leave the file zero-byte
        except OSError:
            pass

    if os.environ.get("STUB_GANDALF_AGENTIC_ADVISOR") == "1" and report_path and not noreport:
        try:
            adv = os.path.join(os.path.dirname(report_path), "advisor-output.json")
            with open(adv, "w", encoding="utf-8") as fh:
                json.dump({
                    "schema_version": 1, "cross_model": True, "degraded": False,
                    "reasoning": "x", "verdict": "Graded cross-model read.",
                    "findings": [], "nitpicks": [], "elevations": [],
                    "risk_labels": [],
                }, fh)
        except OSError:
            pass

    # Always print a full summary + VERDICT (even in noreport mode) so the honest
    # gate is exercised on the "DONE + prose but no report" case, not just empty text.
    answer = (
        "This folder is a coherent project with a clear objective. Its key "
        "weakness is thin test coverage at the edges; the next step is to add "
        "integration tests.\n"
        "VERDICT: Broadly sound with a durability gap worth watching.")

    def emit(obj):
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()

    emit({"type": "system", "subtype": "init", "session_id": "stub-agentic"})
    emit({"type": "assistant",
          "message": {"role": "assistant",
                      "content": [{"type": "text", "text": answer}]},
          "session_id": "stub-agentic"})
    emit({"type": "result", "subtype": "success", "is_error": False,
          "result": answer, "total_cost_usd": 0.0,
          "usage": {"input_tokens": 1, "output_tokens": 1},
          "duration_ms": 1, "session_id": "stub-agentic"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
