"""Build tooling for the Anchor sleep cycle 2026-07-28 (v1.2) effort.

Every module in this package is contained under
``planning/sleep-2026-07-28/stage2/`` and writes only inside that root —
see :mod:`tools.containment_smoke`, which is the machine proof of that claim.

W1 (Phase 0) ships four modules here:

* :mod:`tools.containment_smoke` — write-target containment + root foreign
  artifact byte-identity + the escape-attempt suite.
* :mod:`tools.coverage_toolchain_probe` — the honest record of what coverage
  tooling actually exists on this box.
* :mod:`tools.verification_task_triple` — the John task-triple schema, the
  live-John HALT, and the Phase-0 GO decision.
* :mod:`tools.artifact_ledger` — the shared-artifact ledger parser, validator,
  and sign-off gate.
"""
