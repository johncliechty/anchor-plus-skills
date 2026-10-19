# Status cadence failure-state table

Build: Anchor sleep cycle 2026-07-28 (v1.2)
Wave: W20 — Phase 3: Status cadence owned by Anchor from live telemetry with as_of + staleness
Surface: `cadence`
Schema: failure-state-table/v1 (mapped through `artifacts/STATE-VOCABULARY-MAP.md`)

Surface-native language only (tile render / status / cadence). Doctor-tile hygiene
vocabulary and index / rebuild / reconcile language are honesty theater on this
tile and must not appear.

**unknown** and **empty** are SEPARATE rows. Combining those two states into one
row is a build failure (hardening gates 0080/0081).

* **empty** — telemetry readable and there is legitimately no series (empty scope)
* **unknown** — telemetry unreachable / outage (never looks empty, never current)
* **stale** — sample age at or above the staleness threshold; age is shown
* **ok / fresh** — sample age under the threshold; may present as current

Every rendered status carries a mandatory **as_of** ISO stamp. No status renders
without as_of.

## Rows (machine-readable)

| hardening | state | user_visible | trigger |
|-----------|-------|--------------|---------|
| dependency-missing | unknown | unknown | cadence telemetry source absent or capability not authorized — status tile render shows unknown (never empty, never current-looking) |
| dependency-slow-or-killed | stale | stale | telemetry sample age at or above STALENESS_THRESHOLD_SECONDS (120s) — tile render shows stale with age; never current-looking |
| dependency-slow-or-killed | timeout | timeout | cadence telemetry dependency slow or killed during tile render |
| dependency-returns-garbage | measurement_failed | measurement_failed | cadence telemetry returned garbage payload during tile render |
| backing-store-unreadable | unknown | unknown | telemetry unreachable / outage — tile render shows unknown; never empty; never a confidently current-looking status |
| empty-but-valid | empty | empty | telemetry readable; legitimately no series (empty scope) — tile render empty (distinct from unknown) |
| empty-but-valid | ok | ok | live telemetry sample within freshness bound — tile render ok/fresh with mandatory as_of |

## Enumerated cadence reasons (handler)

| reason | named_state | user_visible | trigger |
|--------|-------------|--------------|---------|
| ok | ok | ok | live telemetry sample within freshness bound; as_of from telemetry |
| fresh | ok | ok | alias: sample age under STALENESS_THRESHOLD_SECONDS |
| stale | stale | stale | sample age >= threshold; age shown on tile |
| telemetry_outage | unknown | unknown | telemetry unreachable (TelemetryOutage) |
| empty_series | empty | empty | telemetry readable; no series |
| aged_sample | stale | stale | induced aged sample for GWT stale-with-age |
| capability_absent | unknown | unknown | cadence_telemetry inventory source not authorized |
| missing_as_of | unknown | unknown | status construction without as_of raises MissingAsOfError |

## Freshness × NamedState matrix

| freshness | named_state | age shown | current-looking allowed |
|-----------|-------------|-----------|-------------------------|
| fresh | ok | optional (under threshold) | yes |
| stale | stale | required | **no** |
| unknown | unknown | none | **no** |
| empty | empty | optional | **no** (not current; empty scope) |

## Named numeric bounds

* `STALENESS_THRESHOLD_SECONDS` = **120**
* `DEFAULT_CADENCE_INTERVAL_SECONDS` = **600** (10-minute status cadence)
* as_of: mandatory ISO-8601 on every CadenceTick / StatusSnapshot / rendered tile

## Telemetry source (CAPABILITY-INVENTORY)

* Control id: `cadence_telemetry`
* Label: cadence telemetry source
* Loop: `anchor.status.cadence.CadenceLoop`
* Reader: `anchor.status.cadence.read_status_snapshot`
* Staleness: `anchor.status.staleness.classify_staleness`
* Tile: `anchor.ui.status_view.render_status_tile` via `render_state`

## Mapping notes

* `backing-store-unreadable` → **unknown** only (never empty, never a silent blank, never current).
* `dependency-slow-or-killed` → **stale** (with age) when the sample is aged; timeout when the dependency itself is killed mid-read.
* `empty-but-valid` requires **empty** and **ok** as separate rows (fresh live status is ok, not zero_measured — cadence is not a numeral tile).
* **unknown** and **empty** are SEPARATE rows (hardening 0080/0081).
* Stale is never presented as current-looking: visible `stale` label + age.
* Surface actions: tile render, status, cadence.
