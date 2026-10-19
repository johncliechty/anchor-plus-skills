# Rollup Evidence

Build: Anchor sleep cycle 2026-07-28 (v1.2)
Wave: W4 — Phase 1: Rollup Evidence Gate (query + row count + sample row)

## Binding rules (machine-enforced in tools/rollup_evidence_gate.py)

- Verdicts: **PROVEN** | **NO_AGGREGATOR** | **READ_FAILED** only
- PROVEN sub-verdicts: **nonzero** | **zero_measured** | **empty** (binding definitions)
- Aggregator ran, zero rows, scope exists → **PROVEN / zero_measured** (never pending)
- Scope itself empty → **PROVEN / empty** (never merged with zero_measured)
- No aggregator → **NO_AGGREGATOR** → surface renders **pending** (names the aggregation wave)
- Query raises → **READ_FAILED** → surface renders **unknown** (never the same verdict as NO_AGGREGATOR)
- Cost agreement tolerance: **0 cents** (exact match)

## Rollups (criterion 3 — dashboard / workbench / session chrome × usage / time / cost)

### `dashboard_usage` — dashboard usage rollup

| field | value |
|-------|-------|
| verdict | **NO_AGGREGATOR** |
| sub-verdict | — |
| surface render | `pending` |
| query | `SELECT SUM(tokens) AS total FROM usage_events WHERE as_of BETWEEN :window_start AND :window_end` |
| row_count | 0 |
| sample_row | _(none)_ |
| total | — |
| run_timestamp | 2026-07-29T16:00:00Z |
| window | 2026-06-29..2026-07-29 |
| scope_size | 0 |
| aggregation_wave | W12-usage-time-aggregation |
| read_error | — |
| notes | Phase-1 bootstrap: no aggregator in stage2 tree — NO_AGGREGATOR; surface waves render pending |

### `dashboard_time` — dashboard time rollup

| field | value |
|-------|-------|
| verdict | **NO_AGGREGATOR** |
| sub-verdict | — |
| surface render | `pending` |
| query | `SELECT SUM(seconds) AS total FROM session_time WHERE as_of BETWEEN :window_start AND :window_end` |
| row_count | 0 |
| sample_row | _(none)_ |
| total | — |
| run_timestamp | 2026-07-29T16:00:00Z |
| window | 2026-06-29..2026-07-29 |
| scope_size | 0 |
| aggregation_wave | W12-usage-time-aggregation |
| read_error | — |
| notes | Phase-1 bootstrap: no aggregator in stage2 tree — NO_AGGREGATOR; surface waves render pending |

### `dashboard_cost` — dashboard cost rollup

| field | value |
|-------|-------|
| verdict | **NO_AGGREGATOR** |
| sub-verdict | — |
| surface render | `pending` |
| query | `SELECT SUM(cents) AS total FROM cost_events WHERE as_of BETWEEN :window_start AND :window_end` |
| row_count | 0 |
| sample_row | _(none)_ |
| total | — |
| run_timestamp | 2026-07-29T16:00:00Z |
| window | 2026-06-29..2026-07-29 |
| scope_size | 0 |
| aggregation_wave | W13-cost-aggregation |
| read_error | — |
| notes | Phase-1 bootstrap: no aggregator in stage2 tree — NO_AGGREGATOR; surface waves render pending |

### `workbench_usage` — workbench usage rollup

| field | value |
|-------|-------|
| verdict | **NO_AGGREGATOR** |
| sub-verdict | — |
| surface render | `pending` |
| query | `SELECT project_id, SUM(tokens) AS total FROM usage_events WHERE project_id = :pid GROUP BY project_id` |
| row_count | 0 |
| sample_row | _(none)_ |
| total | — |
| run_timestamp | 2026-07-29T16:00:00Z |
| window | 2026-06-29..2026-07-29 |
| scope_size | 0 |
| aggregation_wave | W12-usage-time-aggregation |
| read_error | — |
| notes | Phase-1 bootstrap: no aggregator in stage2 tree — NO_AGGREGATOR; surface waves render pending |

### `workbench_time` — workbench time rollup

| field | value |
|-------|-------|
| verdict | **NO_AGGREGATOR** |
| sub-verdict | — |
| surface render | `pending` |
| query | `SELECT project_id, SUM(seconds) AS total FROM session_time WHERE project_id = :pid GROUP BY project_id` |
| row_count | 0 |
| sample_row | _(none)_ |
| total | — |
| run_timestamp | 2026-07-29T16:00:00Z |
| window | 2026-06-29..2026-07-29 |
| scope_size | 0 |
| aggregation_wave | W12-usage-time-aggregation |
| read_error | — |
| notes | Phase-1 bootstrap: no aggregator in stage2 tree — NO_AGGREGATOR; surface waves render pending |

### `workbench_cost` — workbench cost rollup

| field | value |
|-------|-------|
| verdict | **NO_AGGREGATOR** |
| sub-verdict | — |
| surface render | `pending` |
| query | `SELECT project_id, SUM(cents) AS total FROM cost_events WHERE project_id = :pid GROUP BY project_id` |
| row_count | 0 |
| sample_row | _(none)_ |
| total | — |
| run_timestamp | 2026-07-29T16:00:00Z |
| window | 2026-06-29..2026-07-29 |
| scope_size | 0 |
| aggregation_wave | W13-cost-aggregation |
| read_error | — |
| notes | Phase-1 bootstrap: no aggregator in stage2 tree — NO_AGGREGATOR; surface waves render pending |

### `session_chrome_usage` — session chrome usage rollup

| field | value |
|-------|-------|
| verdict | **NO_AGGREGATOR** |
| sub-verdict | — |
| surface render | `pending` |
| query | `SELECT session_id, SUM(tokens) AS total FROM usage_events WHERE session_id = :sid GROUP BY session_id` |
| row_count | 0 |
| sample_row | _(none)_ |
| total | — |
| run_timestamp | 2026-07-29T16:00:00Z |
| window | 2026-06-29..2026-07-29 |
| scope_size | 0 |
| aggregation_wave | W12-usage-time-aggregation |
| read_error | — |
| notes | Phase-1 bootstrap: no aggregator in stage2 tree — NO_AGGREGATOR; surface waves render pending |

### `session_chrome_time` — session chrome time rollup

| field | value |
|-------|-------|
| verdict | **NO_AGGREGATOR** |
| sub-verdict | — |
| surface render | `pending` |
| query | `SELECT session_id, SUM(seconds) AS total FROM session_time WHERE session_id = :sid GROUP BY session_id` |
| row_count | 0 |
| sample_row | _(none)_ |
| total | — |
| run_timestamp | 2026-07-29T16:00:00Z |
| window | 2026-06-29..2026-07-29 |
| scope_size | 0 |
| aggregation_wave | W12-usage-time-aggregation |
| read_error | — |
| notes | Phase-1 bootstrap: no aggregator in stage2 tree — NO_AGGREGATOR; surface waves render pending |

### `session_chrome_cost` — session chrome cost rollup

| field | value |
|-------|-------|
| verdict | **NO_AGGREGATOR** |
| sub-verdict | — |
| surface render | `pending` |
| query | `SELECT session_id, SUM(cents) AS total FROM cost_events WHERE session_id = :sid GROUP BY session_id` |
| row_count | 0 |
| sample_row | _(none)_ |
| total | — |
| run_timestamp | 2026-07-29T16:00:00Z |
| window | 2026-06-29..2026-07-29 |
| scope_size | 0 |
| aggregation_wave | W13-cost-aggregation |
| read_error | — |
| notes | Phase-1 bootstrap: no aggregator in stage2 tree — NO_AGGREGATOR; surface waves render pending |

## Coverage

Required rollups: 9
Recorded rows: 9
Missing: _(none)_
Spot-check gate: **GO** — spot-check protocol satisfied
