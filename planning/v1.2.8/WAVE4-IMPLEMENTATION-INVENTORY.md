# Wave 4 implementation inventory

Run: `steward-codex-anchor-2026-08-31`  
Baseline heads: Anchor `26faf661`; Trio `1f3acba`; Skill Foundry `b926060`.

This inventory is deliberately narrower than `git status`. All three working
trees were already heavily dirty, so an unstaged filename is not evidence that
this controller created the whole diff.

## Bounded-run implementation files

### Wave 1 — shared Trio seams and receipt truth

Ecgberht changes made by this controller:

- `C:/dev/Ecgberht/SKILL.md`
- `C:/dev/Ecgberht/engine/commission-proposal.mjs`
- `C:/dev/Ecgberht/engine/dialogue.mjs`
- `C:/dev/Ecgberht/engine/seat-hop.mjs`
- `C:/dev/Ecgberht/engine/seating.mjs`
- `C:/dev/Ecgberht/scripts/seat-call.mjs`
- `C:/dev/Ecgberht/templates/verb-help/seat-hop.md`
- `C:/dev/Ecgberht/test/seat-call-trio-adapter.test.mjs`
- `C:/dev/Ecgberht/test/w5-commission.test.mjs`
- `C:/dev/Ecgberht/test/w10-dialogue-seat-hop.test.mjs`
- `C:/dev/Ecgberht/test/w11-commission-proposal.test.mjs`
- `C:/dev/Ecgberht/journal/0096-chatgpt-trio-steward-seat.md`
- `C:/dev/Ecgberht/journal/runs/20260831T125507Z-steward-chatgpt-trio-adapter.json`

`engine/seat-tiers.mjs` already contained an in-progress ChatGPT tier change and
was preserved; this controller does not claim that file's broader dirty diff.

Tidy-Idy changes made by this controller:

- `skills/tidy-idy/engine/agent-seam.mjs`
- `skills/tidy-idy/engine/context.mjs`
- `skills/tidy-idy/bin/analyze.mjs`
- `skills/tidy-idy/bin/debate.mjs`
- `skills/tidy-idy/test/agent-seam-trio.test.mjs`
- `skills/tidy-idy/journal/0004-shared-trio-agent-seam.md`
- `skills/tidy-idy/journal/runs/20260831T130517Z-tidy-shared-trio-adapter.json`

Literature Review changes made by this controller:

- `skills/literature-review/SKILL.md`
- `skills/literature-review/bin/cli.mjs`
- `skills/literature-review/src/reviewSeatLabels.mjs`
- `skills/literature-review/src/seatTelemetry.mjs`
- `skills/literature-review/test/review-seat-labels.test.mjs`
- `skills/literature-review/test/seat-telemetry.test.mjs`
- `skills/literature-review/journal/0006-receipt-derived-seat-truth.md`
- `skills/literature-review/journal/runs/20260831T131433Z-literature-seat-truth.json`

Ramanujan received no production edit. Its boundary decision is recorded in
`planning/v1.2.8/RAMANUJAN-CODEX-BOUNDARY-DECISION.md`.

### Wave 2 — Anchor model-role controls

Files changed by this controller:

- `anchor_gui.py` — four-role capability matrix and dashboard controls; this is
  an overlap file containing substantial earlier user-owned changes.
- `tests/test_backend_chatgpt.py` — role matrix plus real browser persistence
  smoke; this file existed as an untracked in-progress test before the slice.
- `tests/test_settings_api.py` — capability response assertions with synthetic
  home/data paths; this is an overlap file.
- `planning/v1.2.8/SESSION.md` and controller artifacts.

Relevant pre-existing dependencies verified but not authored in Wave 2:

- `anchor_settings.py`, `job_runner.py`, `terminal_session.py`,
  `codex_adapter.py`, `tests/test_anchor_settings.py`,
  `tests/test_chatgpt_lane_routing.py`, and `tests/test_codex_adapter.py`.

### Wave 3 — existing cockpit slice verified

The controller made no new product edit in Wave 3. It verified the existing
morning-slice files:

- `anchor_gui.py`
- `dist_manifest.txt`
- `steward_cockpit/static/cockpit.html`
- `steward_cockpit/static/connections-demo.js`
- `tests/test_cockpit_demo_connections_2026_08_30.py`

These files provide the default project cockpit, the explicit classic escape,
two empty synthetic Calendar/Email states, and the local-only Gmail/Outlook
setup preview.

## Verified foundations, not newly authored here

- Trio's dirty `drivers/` tree is the shared receipt-bearing substrate frozen by
  the Wave 0 194-test driver gate.
- Jumper's shared-Trio integration was frozen by its 42-test gate.
- The current cockpit work-product-map/kickoff files and other Steward prototype
  edits predate this controller's bounded adapter/selectors work and remain
  user-owned overlap changes.

## Deliberate exclusions and quarantine

- `_mockups/dashboard-v2/` has four untracked files containing realistic
  historical project/task/calendar/mail samples. It has zero tracked files and
  is excluded by the deny-by-default distribution manifest. Never include it in
  a broad add/commit; sanitize or remove only with explicit user approval.
- No live model, Fable, OAuth, Gmail, Outlook, or external-provider call.
- No commit, push, merge, deployment, or global-preference write.
- No claim that unrelated dirty files belong to this run.

## Gate record entering Wave 4

| Gate | Result |
|---|---:|
| Trio drivers | 189 pass, 5 live skips, 0 fail |
| Jumper | 42 pass |
| Ecgberht shared Trio | 46 pass |
| Tidy-Idy shared Trio | 40 pass |
| Literature receipt truth | 31 pass |
| Ramanujan boundary | 64 pass |
| Anchor selectors/home/browser | 89 pass |
| Cockpit empty connections/distribution | 9 pass |

The Wave 4 rerun matrix will update the final evidence package; prior green
results are not treated as a substitute for the final bounded sweep.
