# Release captain checklist

John (or the release captain) signs this gate before a public release. Items are **machine-checkable** via `share_topology.evaluate_captain_checklist`. **Fail closed:** any red item means the release is **not** ship-allowed.

## Required items

- [ ] **`freeze_tags`** — Freeze tags present (no PLACEHOLDER remaining)
- [ ] **`clean_scan_green`** — Clean-scan green (no-leak)
- [ ] **`sources_complete`** — SOURCES.md / multi-repo pin complete
- [ ] **`package_matrix_green`** — Package matrix green (A|B only; B contains A)
- [ ] **`stranger_install_smoke`** — Stranger install smoke green
- [ ] **`sanitizer_red_team_green`** — Feedback sanitizer red-team green

## Evaluation

```python
from share_topology import evaluate_captain_checklist
report = evaluate_captain_checklist({
    'freeze_tags': True,
    'clean_scan_green': True,
    'sources_complete': True,
    'package_matrix_green': True,
    'stranger_install_smoke': True,
    'sanitizer_red_team_green': True,
})
# report['ship_allowed'] is True only when every item is green
```

## Linkage

- Freeze / SOURCES: W3 `share_sources` + `verify_freeze_manifest`
- Clean-scan / matrix: W3 `share_publish` + W1 package matrix
- Sanitizer red-team: W6 `share_feedback` unit/red-team suite
- Stranger smoke: W9 E2E harness (`share_ci_ship_gate.run_stranger_install_e2e`; status may be injected here)
- Execute/ship gate (live vendoring): W9 `share_ci_ship_gate.evaluate_execute_ship_gate` + plan-workspace `SHIP-GATE-CHECKLIST.md`
