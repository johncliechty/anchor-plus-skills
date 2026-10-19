# E3 enforcement report — steward-chamber W12 (Phase-4 Close)

**Criterion (E3):** a resumed/re-briefed rewrite that regresses a
predicate-bearing correction CANNOT hand back; unassertable entries
are honestly demoted in every report.

## Published predicate-coverage threshold

`PREDICATE_COVERAGE_THRESHOLD = 0.5` (code-owned in
`chamber_corrections.py`; the committed record
`chamber/correction-triage.json` must match — divergence fails the
W11 suite).

## The one-time triage: every unassertable NAMED

### ecgberht:artifacts/fix-item-ledger.json (sibling root per the ECGBERHT_ROOT law; schema ecgberht-fix-item-ledger-v0)

| Entry | Outcome | Why |
|-------|---------|-----|
| A4-non-atomic-confirm-pair | demoted | prose defect record; evidence cites engine/job-lifecycle.mjs lines but carries no machine predicate and no must_contain/must_not_contain text |
| A5-derived-ingest-zero-callers | demoted | pre-decided audit outcome (PASS); no machine predicate derivable mechanically |
| A5-attention-delivery-needs-wire | demoted | scheduled wire item; no machine predicate derivable mechanically |

kept 0 · derived 0 · demoted 3 · coverage 0.0

### per-project .ecgberht/step-findings.json stores (owner engine/step-findings.mjs; read via chamber_corrections.findings_triage_input)

Step-findings rows are open campaign FACTS, prose by design (the owner's contract: 'durable, never authoritative'); a findings row enters the correction ledger only through record_correction, which enforces the W11 contract at the door. The triage function is the same one; W12's audit re-runs it over the live stores.

### per-project .anchor/chamber/corrections.json (the W11 chamber corrections store)

The store is born under the recording contract - it cannot accumulate un-triaged entries.

## The live guard (engine-enforced from W11 forward)

* `chamber_corrections.record_correction` REFUSES an entry with
  neither a machine predicate nor the explicit mark
  `unassertable — manual review` — the store only gains assertable entries.
* `chamber_corrections.handback_guard` blocks a handback whose
  rewrite regresses any predicate-bearing correction (named
  finding), FAILS CLOSED on an unreadable store, and lists the
  demoted remainder in EVERY report — never silently blessed.
* Re-verified end-to-end in this wave:
  `tests/test_chamber_cross_audit_w12.py` re-runs the W11
  handback-block negative path against the live seams.

**Honesty line:** legacy coverage is 0.0 — all 3 pre-existing
fix-item entries are prose and stand DEMOTED by name above. The
threshold binds the live store going forward, not the demoted
remainder.
