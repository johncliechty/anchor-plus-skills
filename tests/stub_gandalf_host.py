#!/usr/bin/env python3
"""STUB Stage-B host — a runnable stand-in for ``gandalf-run.mjs``.

Wired in via ``ANCHOR_GANDALF_HOST_CMD`` (e.g. ``python tests/stub_gandalf_host.py``)
so a Gandalf engine test never invokes real ``node`` / the real Skill-Foundry
host. It reads the RAW draft on stdin (exactly as ``gandalf-run.mjs`` does) and
emits a canned GRADED ``advisor-output.json`` (the 9 required top-level keys per
``schema/advisor-output.schema.json``) on stdout, exit 0.

Honesty knobs (so the degrade path is testable):
- ``STUB_GANDALF_HOST_FAIL=1`` → write an honest stderr reason + exit 1 (the
  host's malformed/non-conformant non-zero-exit contract).
- ``STUB_GANDALF_HOST_BADJSON=1`` → emit non-JSON on stdout (unparseable output).
- ``STUB_GANDALF_HOST_DEGRADED=1`` → set ``degraded:true`` on the graded output.
- ``STUB_GANDALF_HOST_CROSSMODEL=1`` → set ``cross_model:true``.
- ``STUB_GANDALF_HOST_VERDICT`` → override the top-level verdict text.

The stub honors the real host's stdin contract; it does NOT re-implement the
seam pass — it returns a deterministic, schema-shaped graded object so the Anchor
flow (parse → validate → render → store) is exercised end-to-end. NEVER live.
Stdlib only.
"""
import json
import os
import sys


def _flag(name):
    raw = os.environ.get(name)
    return bool(raw) and raw.strip().lower() not in ("0", "", "false", "no")


def main():
    # Read (and ignore the content of) the raw draft, honoring the stdin contract.
    try:
        _ = sys.stdin.read()
    except Exception:
        _ = ""

    if _flag("STUB_GANDALF_HOST_FAIL"):
        sys.stderr.write("gandalf-run(stub): conformance failure — no output "
                         "written.\nforced failure for the degrade test\n")
        return 1

    if _flag("STUB_GANDALF_HOST_BADJSON"):
        sys.stdout.write("this is not json — host produced garbage\n")
        sys.stdout.flush()
        return 0

    verdict = (os.environ.get("STUB_GANDALF_HOST_VERDICT")
               or "This is broadly sound, with one durability gap worth watching.")

    graded = {
        "schema_version": "1",
        "cross_model": _flag("STUB_GANDALF_HOST_CROSSMODEL"),
        "degraded": _flag("STUB_GANDALF_HOST_DEGRADED"),
        "reasoning": "The deterministic seam pass stamped the raw draft; "
                     "elevations land SPECULATIVE (no independent challenger ran).",
        "verdict": verdict,
        "findings": [
            {
                "id": "d-1",
                "kind": "diagnose",
                "rung": "OBSERVED",
                "reasoning": "The test gate runs green at the documented baseline.",
                "verdict": "The build is in a healthy, tested state.",
                "severity": "minor",
                "gandalf_core": {"protocol": "PROTOCOL v2"},
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
                "tier": "SPECULATIVE",
                "value_if_true": "medium",
                "rung": "UNVERIFIED",
                "reasoning": "A periodic re-analysis would catch drift earlier "
                             "(no independent refutation ran).",
                "verdict": "Consider scheduling a recurring read.",
            }
        ],
        "risk_labels": [
            {"leg": "diagnose", "tier": "SPECULATIVE", "rung": "OBSERVED"}
        ],
    }

    sys.stdout.write(json.dumps(graded, indent=2, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
