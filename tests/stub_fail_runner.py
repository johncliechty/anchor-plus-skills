#!/usr/bin/env python3
"""STUB runner that always FAILS (non-zero exit) — for the no-cache-poison test.

The summarizer's FIX 2 must refuse to cache a summary when the runner job failed
(status != DONE). This stub emits nothing and exits 1, so a finish-triggered
summary generation surfaces ``RUN_FAILED`` and leaves the cache untouched
(retryable). NEVER live — a STUB only. Stdlib only.
"""
import sys

if __name__ == "__main__":
    sys.stderr.write("stub fail runner: deliberate non-zero exit\n")
    sys.exit(1)
