#!/usr/bin/env python3
"""Deterministic STUB runner for the Wave 6 summarizer tests.

Stands in for a live ``claude`` model call via the ``ANCHOR_RUNNER_CMD`` seam,
exactly like ``tests/fake_claude.py`` — but tailored so a test can:

  1. Make the model emit BOTH a grounded claim and a deliberately UNGROUNDED
     claim (``fake_claude`` can only emit generic ``fake-line N`` content), so
     the grounding-filter behaviour is observable.
  2. PROVE run-once: every invocation appends a byte to the counter file named
     by ``STUB_SUMMARIZER_COUNTER`` so the test can assert the model ran exactly
     once across two ``summarize_session`` calls.

Each line of ``STUB_SUMMARIZER_CLAIMS`` (``\\n``-joined) is emitted verbatim as
one candidate-claim stdout line. The trailing prompt the runner appends is
ignored (a real model would consume it). Exit 0.

  3. FAILURE mode (FIX 2): if ``STUB_SUMMARIZER_FAIL`` is set/truthy the stub
     exits NON-ZERO with no usable stdout, so the runner records the job as
     FAILED and the summarizer must NOT poison the cache.

NEVER live — a STUB only. Stdlib only.
"""
import os
import sys


def main():
    counter = os.environ.get("STUB_SUMMARIZER_COUNTER")
    if counter:
        # Append-only call log: one 'x' per invocation → len == call count.
        try:
            with open(counter, "a", encoding="utf-8") as fh:
                fh.write("x")
        except OSError:
            pass

    # FAILURE mode (FIX 2): when STUB_SUMMARIZER_FAIL is truthy, exit non-zero
    # with no usable output so the runner job is recorded as FAILED. The counter
    # is still bumped above so a test can prove the model WAS attempted.
    if os.environ.get("STUB_SUMMARIZER_FAIL"):
        sys.stderr.write("stub: simulated model failure\n")
        return 3

    raw = os.environ.get("STUB_SUMMARIZER_CLAIMS", "")
    claims = [c for c in raw.split("\n") if c.strip() != ""]
    if not claims:
        claims = ["fake claim"]
    for c in claims:
        sys.stdout.write(c + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
