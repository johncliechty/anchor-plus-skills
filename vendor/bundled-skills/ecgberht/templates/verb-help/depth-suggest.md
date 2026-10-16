# Verb: depth-suggest

**Closed list:** yes · **Primary:** depth-suggest

Table-driven depth cell from Strip signals only (phase × uncertainty × human_wait × cost).

| Rule | Behavior |
|------|----------|
| Default bias | **LITE** |
| Unknown data shape | **SPIKE** |
| FULL | Only when an explicit table cell says so |
| human_wait blocks / out-of-scope | **refuse** |
| capacity=unknown | LITE bias flag; never silent FULL green |
| Free-form inflation | **Refused** (no ad-hoc LITE\|FULL\|SPIKE from argv) |
| Human override | Requires structured receipt: who / when / why / from→to |

Fixture matrix: `fixtures/dispatch-table-seed.json`. Module: `engine/dispatch-table.mjs`.
