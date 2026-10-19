# Stop-summary failure-state table

Build: Anchor sleep cycle 2026-07-28 (v1.2)
Wave: W16 — Phase 3: Stop summary tile backed by real in-flight inventory
Surface: `stop-summary`
Schema: failure-state-table/v1 (mapped through `artifacts/STATE-VOCABULARY-MAP.md`)

Surface-native language only (stop / summary / tile render). Doctor-tile hygiene
vocabulary is honesty theater on this tile and must not appear.

**unknown** and **empty** are SEPARATE rows. Combining those two states into one
row is a build failure (hardening gates 0080/0081).

* **empty** — inventory read succeeded and nothing was in flight
* **unknown** — in-flight inventory could not be read (never looks empty)
* Counts on a successful stop summary are traceable to the inventory query
  named by CAPABILITY-INVENTORY control `stop_summary`

## Rows (machine-readable)

| hardening | state | user_visible | trigger |
|-----------|-------|--------------|---------|
| dependency-missing | unknown | unknown | stop-summary inventory source absent or capability not authorized — stop summary tile render shows unknown (never empty) |
| dependency-slow-or-killed | timeout | timeout | stop-summary inventory dependency slow or killed during tile render |
| dependency-returns-garbage | measurement_failed | measurement_failed | stop-summary inventory returned garbage payload during tile render |
| backing-store-unreadable | unknown | unknown | in-flight inventory unreadable at stop — tile render shows unknown; never empty; never "nothing was in flight" |
| empty-but-valid | empty | empty | stop inventory read succeeded; nothing was in flight — tile render empty (distinct from unknown) |
| empty-but-valid | zero_measured | zero_measured | stop inventory aggregation ran over existing scope; measured in-flight total is 0 |

## Enumerated stop-summary reasons (handler)

| reason | named_state | user_visible | trigger |
|--------|-------------|--------------|---------|
| ok | ok | ok | stop inventory query returned in-flight items with counts |
| inventory_unreadable | unknown | unknown | in-flight inventory read failed (unknown ≠ empty) |
| zero_items | empty | empty | inventory read succeeded with zero in-flight items |
| partial_items | ok | ok | some items only partially recovered; still listed with counts |
| zero_measured | zero_measured | zero_measured | scope exists; measured total count is 0 |
| capability_absent | unknown | unknown | stop_summary inventory source not authorized |

## Inventory source (CAPABILITY-INVENTORY)

* Control id: `stop_summary`
* Label: stop-summary inventory source
* Collector: `anchor.session.stop_summary.collect_stop_summary`
* Tile: `anchor.ui.stop_summary_tile.render_stop_summary_tile` via `render_state`

## Mapping notes

* `backing-store-unreadable` → **unknown** only (never empty, never a silent blank).
* `empty-but-valid` requires **empty** and **zero_measured** as separate rows.
* Unreadable inventory must never render as "nothing was in flight".
* Surface actions: stop, summary, tile render.
