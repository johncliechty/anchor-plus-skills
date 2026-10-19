# Re-architecture 2026-07 — gate artifacts (W1 · W2 · W3 · W4)

Ground-truth artifacts produced by the early instrumentation/rails waves
(frozen plan: `IMPLEMENTATION-PLAN.md` at the repo root). They are consumed
by later waves (C1 extraction sizing, C3 journal instrumentation, the W9/W17
spike-verdict decisions) and the MECHANICAL ones are REFRESHED by their gate
runs — never hand-edited.

| artifact | producer | refreshed by |
|---|---|---|
| `CENSUS-REPORT.json` / `CENSUS-REPORT.md` | `tools/interpolation_census.py` | every W1 gate run (`tests/test_rearch_2026_07.py::TestCensusGateArtifacts`) |
| `C1-AMENDMENT-REQUIRED.md` | same census | exists **iff** the census forces the C1 amendment (markup-emitting > threshold, or derived shrink < the ≥7,000-line bar); deleted when no longer required |
| `MUTATION-INVENTORY.json` | `tools/write_tripwire.py` | merge-accumulated by: (a) the W1 gate's representative product-mutation walk, (b) any full-suite run with `ANCHOR_WRITE_TRIPWIRE=inventory`, (c) any healthcheck run with the same env — suite + healthcheck fold into ONE inventory |
| `CONSUMER-INVENTORY.md` | W2 (hand-authored enumeration) | reviewed on any consumer change; its claims are held true by `TestW2ConsumerInventory` |
| `SPIKE-CONPTY-VERDICT.json` / `.md` | `tools/conpty_spike.py` | the W3 gate's deterministic **stub** leg (`TestW3ConPTYSpike`); the **real**-ConPTY leg is opt-in via `ANCHOR_SPIKE_REAL_CONPTY=1` — an un-run leg stays honestly `NOT YET RUN` |
| `SPIKE-COOKIE-WS-VERDICT.json` / `.md` | `tools/cookie_ws_spike.py` | the W3 gate's Playwright **desktop** leg (`TestW3CookieWSSpike`); the iPhone-**PWA** leg is a live manual runbook cell (`--record-pwa yes\|no`, run with John) |
| `PILLAR-DAG.md` | `pillar_flags.write_matrix_doc()` | every W3 gate run (`TestW3PillarFlags`) — the module is the single source of truth |
| `BUTLER-USER-STORIES.md` | W3 (hand-authored, binding) | the binding W12 envelope validation target; shape held by `TestW3ButlerStories` |
| `PROCESS-RAILS.md` | W3 (hand-authored, binding) | the codified standing rituals; shape held by `TestW3ProcessRails` |
| `APPENDIX-A-TRACEABILITY.md` | W3 (ledger) | diffed MECHANICALLY against the frozen plan's own citation lines by `TestW3AppendixALedger` (ideas 1–52 + mitigations 1–20, M-9 explicitly reconciled) |
| `../../static/project-window.js` | `tools/extract_project_window_js.py` (W4) | the W4 byte-parity gate (`TestW4ByteParityGate`) — minted VERBATIM from the census-certified zero-interpolation `_PROJECT_WINDOW_JS` raw string, which remains the single source of truth until W6; never hand-edited |

## How to run the full mutation-of-record sweep

```
set ANCHOR_WRITE_TRIPWIRE=inventory
python -m pytest tests            # whole suite, recorded
python anchor_healthcheck.py      # stubbed healthcheck walks, recorded
```

Both merge into `MUTATION-INVENTORY.json` (env override:
`ANCHOR_TRIPWIRE_INVENTORY=<path>`). Entries are
`{store, op, site, count}` with store paths normalized
(ids → `<id>`, numbers → `<n>`, `.tmp` twins folded onto their targets) and
sites given as line-number-free `file.py:function` so the artifact stays
stable and diffable.

## Enforce mode (the future C3 completeness gate)

`ANCHOR_WRITE_TRIPWIRE=enforce` arms the permanent gate that lands with the
journal (W12/W13): any `.anchor/` mutation not paired with a journal event
(`tools.write_tripwire.journal_event`) raises `TripwireViolation` naming the
write site. The journal path itself (`journal.jsonl` / `journal/` dirs) is
allowlisted. The pairing contract is already proven by
`tests/test_rearch_2026_07.py::TestTripwireEnforce`.
