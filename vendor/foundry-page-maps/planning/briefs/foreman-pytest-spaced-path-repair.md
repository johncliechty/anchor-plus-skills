# Focused formal repair: Foreman rejects real pytest events with spaces

This separately scoped validator repair is necessary to complete John's authorized researchPrime Refinement 2. Current-version real-use evidence: code jobs 20261006-200539-2de1c2 and 20261006-203327-a3cc8a both halted as VACUOUS despite their orchestrator-owned wave-1-gate.json receipts containing exit 0, 54 distinct PASSED lines, and a 54-passed summary. Ecgberht read those complete receipts and preserved them with journal/0019 and journal/0020 in the owning campaign. The supported --rootdir adjustment changed rootdir but not the spaced printed paths. This repair needs no external repository: use the captured sample below and create a fresh small real pytest fixture under a temporary directory with spaces. Do not read, stash, commit or change unrelated repositories. Do not rebuild researchPrime.

Exact per-test lines from the latest captured stdout (Windows separators):

```text
Foundry page and knowledge maps\researchprime\test_maps.py::test_complete_bundle PASSED [  1%]
Foundry page and knowledge maps\researchprime\test_maps.py::test_missing_or_unsafe_resource_targets_fail[resource] PASSED [  3%]
Foundry page and knowledge maps\researchprime\test_maps.py::test_browser_proof_bound_to_final_bytes PASSED [100%]
```

The full receipt contains 54 individual events, all PASSED, followed by `54 passed in 12.10s`; its exit code is 0. Construct honestly count-matched bounded fixtures; never attach that 54-count banner to only the three sample lines. Also cover equivalent POSIX separators and parameter IDs containing spaces, plus the negative cases below. The preceding repair job 20261006-204750-915071 stopped before coding on a dirty-sibling check selecting an unrelated parent repository from an external evidence reference. That reference has been removed from this self-contained brief; retain the guard, with no dirty-repository override.

Own only the narrow Foreman validator repair in an isolated C:/dev/trio worktree. Follow the existing formal improvement/usage-journal path; this is a reproduced regression repair, not new stages, architecture, policy or a broad speed redesign. In foreman/bin/wave-engine.mjs, looksLikePytest, hasRealTestEvents and countTestEvents require whitespace-free node identifiers. Recognize genuine verbose pytest event lines with spaces in POSIX/Windows paths and parameter IDs while still requiring node-id-before-status structure. Preserve skip/XFAIL/XPASS semantics, genuine failures, collection errors, summary consistency, forged-summary rejection, Node/TAP behavior and nonzero exits. No disabling guards, fabricated output or exceptions tied to this one project.

Add meaningful regressions to the existing test files using exact captured stdout, mixed results and negative summary-only/summary-section fixtures. Prove runGate accepts a fresh real pytest suite in a spaced directory and rejects a real failure there. Independently review and fix findings. Gate: node --test foreman/test/py-canonical.test.mjs foreman/test/wave-engine.test.mjs. Return precise changed files, regression and live-run evidence, reviewer findings and safe activation limits. Journal the observed defect and formal repair in Foreman's existing canonical journal/run-record system as applicable.

Do not edit Anchor, Foundry artifacts or its campaign state; no service restart, model-preference changes, swarm, product acceptance or slice closure. After this repair lands, Ecgberht will resume the preserved researchPrime candidate with real tests and its still-required independent review, then integrate and verify the live page. No new human report or record scripts.
