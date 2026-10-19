# Ship / execute gate checklist

Plan workspace artifact for Shareable Anchor + Skills (W9).
Fail closed: live skill-tree vendoring is forbidden until every item is green.

Evaluate with `share_ci_ship_gate.evaluate_execute_ship_gate` / `evaluate_ship_gate_checklist`.

## Required items

- [ ] **`concurrent_skill_run_merged`** — Concurrent skill-run merged
- [ ] **`multi_repo_tags`** — Multi-repo freeze tags real (not PLACEHOLDER)
- [ ] **`clean_scan`** — Clean-scan green (no-leak)
- [ ] **`captain_signoff`** — Release captain checklist green
- [ ] **`john_go_ahead`** — John go-ahead recorded

## Linkage

- Concurrent skill-run + John go-ahead: W3 `share_sources.go_ahead_conditions_met`
- Multi-repo tags / SOURCES: W3 `share_sources` + `verify_freeze_manifest`
- Clean-scan: GREEN `distro.scan_staged_dir` + W2 dual scrub fixtures
- Captain sign-off: W8 `share_topology.evaluate_captain_checklist`
- Stranger E2E + CI matrices: W9 `share_ci_ship_gate`

## Rule

**Plan-complete ≠ ship-allowed.** PLACEHOLDER freeze tags + missing
go-ahead → execute gate fails closed; Foreman must not vendor live trees.
