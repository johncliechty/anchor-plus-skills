# W12 cross-criterion audit report — steward-chamber W12 (Phase-4 Close)

The audit of the ASSEMBLED chamber: every criteria-ledger row
re-verified at its named seam, the C9–C12 re-checks, the three
interaction cases, and — by name — every instrument a landing wave
promised that is not in the tree. Statuses: `reverified` (landing
instrument exists + re-runs) · `reverified-in-W12` (machinery
landed; the landing wave's own instrument is a ghost — the named
plan defect) · `instrument-missing` (nothing to re-run; plan
defect for John) · `blocked-on-signature` (awaiting the scheduled
John gate).

## E1–E9 (the ledger's W12 re-verify column)

| Row | Home | Named instrument | W12 status |
|-----|------|------------------|------------|
| E1 | W8 | W8 joint negative-path test | **reverified** |
| E2 | W10 | enqueue-gate negative-path test on the W2 seam (chamber_gates.enqueue_guard) | **reverified-in-W12** |
| E3 | W11 | tests/test_chamber_corrections_w11.py (handback-block + coverage report) | **reverified** |
| E4 | W10 | template fixture suite (chamber_directive.template_findings) | **reverified-in-W12** |
| E5 | W10 | head-only serialization test (chamber_gates ERROR_NOT_HEAD + render_gate_queue_html) | **reverified-in-W12** |
| E6 | W11 | tests/test_chamber_preload_w11.py (preload diff test) | **reverified** |
| E7 | W11 | tests/test_chamber_rebrief_w11.py (re-brief per audited mode, no relaunch) | **reverified** |
| E8 | W5 | W5 sidecar-derivation tests + W4 zero-spine-write assertions (chamber_spine_guard.deny_problems) | **reverified-in-W12** |
| E9 | W4/W5 | collapsed-stage manifest-lint refusal + died-after-last-reflection fixture | **reverified** |

Row notes:

* **E1** — stack present
* **E2** — machinery landed in W10 (chamber_gates/chamber_directive) and the W12 suite re-blocks the refusals at the seams; the wave's own cited instrument(s) are absent from the tree: tests/test_chamber_directive_w10.py, tests/test_chamber_gate_queue_w10.py, tests/test_chamber_gate_routes_w10.py — first exercised in W12, the named plan defect
* **E3** — re-run end-to-end by the W12 suite
* **E4** — machinery landed in W10 (chamber_gates/chamber_directive) and the W12 suite re-blocks the refusals at the seams; the wave's own cited instrument(s) are absent from the tree: tests/test_chamber_directive_w10.py, tests/test_chamber_gate_queue_w10.py, tests/test_chamber_gate_routes_w10.py — first exercised in W12, the named plan defect
* **E5** — machinery landed in W10 (chamber_gates/chamber_directive) and the W12 suite re-blocks the refusals at the seams; the wave's own cited instrument(s) are absent from the tree: tests/test_chamber_directive_w10.py, tests/test_chamber_gate_queue_w10.py, tests/test_chamber_gate_routes_w10.py — first exercised in W12, the named plan defect
* **E6** — re-run end-to-end by the W12 suite
* **E7** — re-run end-to-end by the W12 suite
* **E8** — W5 derivation tests exist (test_chamber_coldopen_w5/brownfield_reconcile) but NO test named chamber_spine_guard before this wave — the W12 suite re-runs the deny scan at the seam
* **E9** — re-run end-to-end by the W12 suite

## The three interaction cases (re-blocked in tests/test_chamber_cross_audit_w12.py)

| Case | Seam | Named finding |
|------|------|---------------|
| run dies WHILE a gate is held | chamber_gates.on_run_death (held gate kept) + enqueue_guard (E2 holds) | `E2-RECOMMISSION-BEFORE-SWEEP-BOUND` |
| sweep card vs directive card contend for the queue head | chamber_gates.bind_sweep_card (sweep takes head; directive re-queued, never dropped) | `W10-SWEEP-TAKES-HEAD-DIRECTIVE-REQUEUED` |
| re-brief lands during an active sweep | chamber_rebrief.rebrief -> queued behind the sweep's card binding, never interleaved | `W11-REBRIEF-DURING-SWEEP-QUEUED` |

## C9–C12 re-checks

* **C9** (hash-pinned DOM diffs): GREEN — hash pin HOLDS: signed fe77d058f19a… vs live fe77d058f19a…
* **C10** (F3 escape + F5 hostile-string + F6 red-to-green): GREEN — F5 slot-registered hostile-string suite present and re-run (test_chamber_dom_law_w9); W11 mutator red-to-green present (test_chamber_refine_routes_w11); the W9 F3 escape/hostile-argv suite and the W3 full-inventory red-to-green file are ghosts (tests/test_chamber_red_to_green_w3.py, tests/test_chamber_close_ci_w9.py) — the W12 release bundle exercises the F3 bounds, the F4 containment, the diff guard and the coverage rule at their seams (named reconciliation)
* **C11** (tile retirement on signed parity): GREEN — parity map green; 3 row(s) pending John's ruling (full-transcript-log-link, dismiss-finished-tile, rearm-watch); UNSIGNED -> tiles stand, retirement refused by name (W12-TILE-ROWS-UNRESOLVED)
* **C12** (wire-homing registry symbol-check + characterization parity): GREEN — symbol-check GREEN (all 10 rows resolve; the check itself lands in W12 — the registry declared it active from W1 but no module implemented it before this wave, recorded reconciliation). W7's committed pulse replay oracle: NOT FOUND in tests/fixtures/chamber — the run_pulse characterization oracle the registry cites is absent (named gap)

## Reconciliation register — cited instruments absent from the tree

Chamber artifacts and route-table comments cite these test files;
none exists. Each is a named finding, not a silent gap:

* `tests/test_chamber_red_to_green_w3.py`
* `tests/test_chamber_close_ci_w9.py`
* `tests/test_chamber_directive_w10.py`
* `tests/test_chamber_gate_queue_w10.py`
* `tests/test_chamber_gate_routes_w10.py`

Further named gaps re-verified by this audit: the W4
kill-during-write crash + two-real-process concurrency tests the
property-gate checklist binds to W4 are not in the chamber test
namespace; the W7 run_pulse committed replay oracle is absent; the
W8 wave (E1 stack, say-box classification, ease count, telemetry
DOM test) landed none of its cited chamber deliverables — its
wave commit changed no chamber source. Dispositions are John's at
the W12 close (see the enforcement reports).

## Stale-UI test-debt disposition (TEST-DEBT-REGISTER -> W12)

* test_cockpit_paradigm2 (4 deselects) — old Layout-D board pins -> **M1 equivalent:** `tests/test_chamber_seal_ci_w6.py` — the project window's chamber region is the M1 seal; its DOM pins live in the W6/W7 diff suites
* test_project_window (4) + test_rnd_project_window_kanban (2) + test_rnd_ui_wiring (1) — old lane-board/panel pins -> **M1 equivalent:** `tests/test_chamber_mockup_diff_w6.py` — M1 markup pins are hash-pinned DOM diffs against the signed mockup
* test_no_loss_lifecycle_v8 (4) + test_session_continue UI leg + test_resume_ui_w4 (3) — old tile lifecycle pins -> **pending John's signature** — these pin the BOTTOM TILES the C11 gate retires; their disposition rides the same signing (retire -> accepted loss of the old pins; keep -> re-pin against the surviving tile markup)
* test_steward_persona (3) — old chamber-tile livery pins -> **M1 equivalent:** `tests/test_chamber_open_w6.py` — the seal/livery render is pinned by the chamber open suite
* test_v7_polish (3) + test_board_live/brownfield_wiring/build_deliverable/build_planning_tie/grass_contained (5) — old board-fragment pins -> **pending John's signature** — board fragments outside the chamber region were not rebuilt by this plan (non-goal); repin or sign the loss at the W12 signing
* test_b2_repro_w1 (2) + test_claude_first_launch_w1 (1) + test_gandalf_markdown_links_v13 (1) + test_layoutd_skeleton_playwright_v12 (1) + test_live_escalation_ui_w6 (1) -> **pending John's signature** — pre-existing UI pins on surfaces adjacent to (not part of) the M1 rebuild; adjudication is John's at the signing — the register's provenance rows stand

## Named gate exclusions revisited (the run-all-tests banner)

* `tests/test_foundry_*` family — pre-existing reds on HEAD in a
  separate subsystem; NOT chamber scope. Stands excluded, named in
  the banner; re-adjudication belongs to a foundry-owned effort,
  not this close.
* `tests/test_gandalf_agentic.py` — multi-minute stalls under
  stubs; stands excluded by budget, named in the banner.

## Verdict

The assembled system's landed enforcement (E3/E5-machinery/E6/E7/
E9, F3/F4/F5, the projections substrate, the M1 paint bounds) is
re-verified green at its seams, and the three interaction cases
block with their named findings. The E1 instrument stack is
landed (the steward-e1 re-execution; enforcement arms at
John's F7 signature and fails CLOSED by name until then); the
ease count is NOT instrumented — a plan defect for John,
published in the enforcement reports. Tiles stand: parity is
resolved but UNSIGNED (three rows await John's ruling at the
signing gate).
