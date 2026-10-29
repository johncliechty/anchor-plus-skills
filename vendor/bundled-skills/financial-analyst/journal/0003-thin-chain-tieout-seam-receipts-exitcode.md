# 0003 — S-bundle: THE THIN CHAIN, tie-out crosses the seam, receipts, exit-code fix (2026-08-25)

John-ratified (decision #4: thin, not full spine). NS-03's "nothing ships without approval of
the vetted model" is now one real command instead of a dead letter:

1. **`bin/deal-chain.mjs`** — evaluate → tie-out → report → adversarial review → HALT for
   John. Fail-closed at every link: failing tie-out BLOCKS before any model seat is paid;
   review runs `--require-tie-out`; verdict is at most "GO — awaiting human ack"; exit 0 only
   on GO/UNREVIEWED-gates-passed. Deal scripts join with a 4-line `--chain-json` flag
   (snippet in SKILL.md).
2. **The tie-out record CROSSES the seam** (deal-review.mjs `tieOut`/`requireTieOut`): the
   charter no longer asserts "tie-out proved Excel==Python" on faith — the record's state
   (VERIFIED/FAILED/UNVERIFIED) is carried, gated, and stamped.
3. **RECEIPTS** (John's rider): every run — honest-stop included — emits
   `report hash · grounding · tie-out state · values hash · ts`; the footer line is required
   in deliverables; a missing receipt is visibly unverified.
4. **Exit-code bug CONFIRMED then fixed** (was an unverified audit flag): the old CLI exited
   0 for ANY honest-stop record, including `BLOCKED (grounding gate FAILED)` — a script
   trusting the exit code waved through ungrounded reports. Now 0 only on GO/UNREVIEWED.

VERIFIED ON THE REAL SURFACE: scratch vc_comp deal ran the FULL chain live (python 3.13
tie-out "2 nodes, max delta 0" → seam → review gates → receipt → HALT ask, exit 0), and an
ungrounded report exited 1 (first attempt at proving this read tail's exit code through a
pipe — pipe removed, real code observed). Hermetic suite 8/8. NOT yet observed: a real deal
through the chain — the next live deal is the standing rule's first datum.
provenance: genuine-execution.
