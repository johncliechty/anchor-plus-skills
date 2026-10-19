# Cost Rollup Spot-Check

Build: Anchor sleep cycle 2026-07-28 (v1.2)
Wave: W4 — Phase 1: Rollup Evidence Gate

## Protocol (binding)

- **population** = every engine carrying cost instrumentation, over a named **30-day** window
- **minimum sample** = **20** sessions, or all sessions if fewer, and **at least 3 per engine**
- **independent source-row sum** = a second procedure that reads the source rows directly and does **not** import the aggregation module
- **independence rule** = the agent that authored or last edited the aggregation module may not compute the second side, and no single agent may compute both sides
- **agreement tolerance = 0 cents (exact match)** — 'never fabricates dollars' is absolute
- any disagreement, or any sampled engine the second procedure cannot compute, forces **measurement_failed** for that engine — never a 'provisional' number
- any attempt to sign **E2** against a measurement_failed cost surface is rejected by the exit register from W2

## Run receipt

| field | value |
|-------|-------|
| window_start | 2026-06-29 |
| window_end | 2026-07-29 |
| window_days | 30 |
| population_total | 21 |
| aggregator_agent_id | `agent-rollup-author` |
| source_row_agent_id | `agent-independent-auditor` |
| aggregation_module_author_id | `agent-rollup-author` |
| aggregation_module_path | `anchor/cost/aggregate.py` |
| protocol gate | **GO** |
| reason | spot-check protocol satisfied |
| notes | synthetic protocol exercise under stage2 containment — exact 0-cent agreement; independent source-row agent |

## Per-engine results

| engine | pop | sampled | aggregated_cents | source_row_sum_cents | computable | status | notes |
|--------|-----|---------|------------------|----------------------|------------|--------|-------|
| `claude` | 7 | 7 | 1250 | 1250 | yes | **agreed** | — |
| `gemini` | 7 | 7 | 980 | 980 | yes | **agreed** | — |
| `grok` | 7 | 7 | 640 | 640 | yes | **agreed** | — |

## Measurement-failed engines

_(none)_

## Independence attestation

- aggregator side computed by: `agent-rollup-author`
- source-row side computed by: `agent-independent-auditor`
- aggregation module author/last-editor: `agent-rollup-author`
- sides differ: **yes**
- author ≠ source-row agent: **yes**
