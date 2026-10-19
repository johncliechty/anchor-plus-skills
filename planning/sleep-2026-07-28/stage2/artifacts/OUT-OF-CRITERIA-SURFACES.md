# Out-of-Criteria Surfaces

Build: Anchor sleep cycle 2026-07-28 (v1.2)
Wave: W21 — Phase 4 close-out

Each surface outside the ten criteria is closed as **fixed**, **disabled**, or a **signed E3** with proof the surface is already honest (or removed). E3 is rejected while a dead control remains.

| surface | closure | proof |
|---------|---------|-------|
| named-state demo document (named_state.generate_html) | fixed | W6 render_state primitive only — not a user North-Star control; emits labelled states, no dead clickables |
| cost zero×state matrix demo (cost_view.generate_html_zero_matrix) | fixed | W13 harness surface routes every cell through render_cost; no fabricated $0.00 outside measured |
| restart contract matrix panel | fixed | W17 documentation panel of preserved/lost contracts; live restart controls remain exactly-one per context |
| reason-matrix / cannot-reason catalog panels | fixed | Catalog tiles enumerate named cannot-* states via render_state; not live affordances bound to missing capabilities |
| EARLY-SLICE-PARTIAL honesty label | fixed | Explicit PARTIAL disclosure after W10; not a control surface; prevents over-claim of North Star |

## Closure rules

- **fixed** — surface rendered honest (named state / no dead control)
- **disabled** — surface removed from view / not emitted
- **signed E3** — exit register E3 with John confirmation; surface already honest
- Dead control on an out-of-criteria surface → finding; E3 refused until fixed/removed
