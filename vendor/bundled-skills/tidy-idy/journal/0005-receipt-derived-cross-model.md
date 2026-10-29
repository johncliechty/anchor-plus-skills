# 0005 — cross_model is derived from receipts, never asserted

- **id**: 0005-receipt-derived-cross-model
- **skill**: tidy-idy @ 2026-08-31
- **situation**: Fable adversarial review (ChatGPT-foundation Wave 4 completion) confirmed a P1: `bin/tidy.mjs` wrote `cross_model: true, models: null` as a literal into every run record while the freshly wired seam receipts were collected and discarded — the exact unattested-verification claim the shared-Trio seam forbids.
- **observation**: `runAnalysis`/`runDebate` already accepted `options.onSeatReceipt`; the orchestrator simply never passed it. `bin/compress.mjs` had also missed the seam update — no target, so the compress seat's cwd/edit scope pointed at the invoker's cwd instead of the project being tidied.
- **outcome**: worked. tidy.mjs threads one receipt collector through all three stages and derives `cross_model` (attested served families > 1, failover-substituted serves excluded) and `models` from `trio.seat.v1` receipts; no receipts ⇒ `cross_model: false`. compress.mjs passes `target: projectPath` + env + onReceipt. Suite 494 pass / 1 capability skip, unchanged from baseline.
- **provenance**: genuine-execution (deterministic suite; no live model)
