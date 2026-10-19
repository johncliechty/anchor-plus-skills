# Capability Inventory

Build: Anchor sleep cycle 2026-07-28 (v1.2)
Wave: W3 — Phase 1: Capability Inventory harness (PRESENT / STUB / ABSENT with transcripts)

## Binding rules (machine-enforced in tools/capability_inventory.py)

- Verdicts: **PRESENT** | **STUB** | **ABSENT** only
- **STUB is never auto-downgraded to ABSENT**
- Every row requires a non-empty transcript path + SHA-256 source hash; missing either is `verdict without evidence` naming the control
- Staleness bound: **14 days** — a row older than that, or whose source hash no longer matches HEAD, is **STALE**
- STALE fails closed: treated as **UNKNOWN**, not the last verdict; may not authorize any live control until re-probed
- Replay authority: PRESENT from replay may authorize *documentation* only; shipping a live control requires a **live** probe inside the bound against a matching source hash
- STUB disposition is always **build it** (never wire it, never E1)

## Controls

| control | label | verdict | disposition | probe_date | evidence | source_hash | transcript | source_paths | notes |
|---------|-------|---------|-------------|------------|----------|-------------|------------|--------------|-------|
| `open` | open control | **ABSENT** | E1 candidate | 2026-07-29 | live | `92e59b17290ea71088567bab879af69a2c5084a068538df54be7d0c0efd7f5e7` | `artifacts/transcripts/open.json` | artifacts/inventory-sources/open.probe | no handler bound in stage2 tree at Phase-1 inventory |
| `run` | run control | **ABSENT** | E1 candidate | 2026-07-29 | live | `3b028ab3222eeb89ffcfff536e292fd2299f65d232156e5a009460b628f4262a` | `artifacts/transcripts/run.json` | artifacts/inventory-sources/run.probe | no handler bound in stage2 tree at Phase-1 inventory |
| `retry` | Retry (session attach) | **ABSENT** | E1 candidate | 2026-07-29 | live | `600a80322fc0e835c9eec732046d52df1ce2e39d20b05db2f83a0fbc6bd157e7` | `artifacts/transcripts/retry.json` | artifacts/inventory-sources/retry.probe | no handler bound in stage2 tree at Phase-1 inventory |
| `diagnose` | Diagnose (Doctor) | **STUB** | build it | 2026-07-29 | live | `736651887fc571a62ea4fc553ae8f5d85c04fe075e7528d96fcbced4c3f2f803` | `artifacts/transcripts/diagnose.json` | artifacts/inventory-sources/diagnose.probe | handler bound but returns canned seed — build it |
| `restart_run` | restart control — run context | **ABSENT** | E1 candidate | 2026-07-29 | live | `a7d10f9624c64cfa925e8f23db04f674bd837bf8c225c13b88799a7727bc77be` | `artifacts/transcripts/restart_run.json` | artifacts/inventory-sources/restart_run.probe | no handler bound in stage2 tree at Phase-1 inventory |
| `restart_session` | restart control — session context | **ABSENT** | E1 candidate | 2026-07-29 | live | `e5dce4b9fd7ed9f9dc41dbb2c3c004c655e0b33e5d0bc5d90bbf511f01796f92` | `artifacts/transcripts/restart_session.json` | artifacts/inventory-sources/restart_session.probe | no handler bound in stage2 tree at Phase-1 inventory |
| `restart_engine` | restart control — engine context | **ABSENT** | E1 candidate | 2026-07-29 | live | `0532a86a6201667405d4b19f414d8f50367affbbffc25b415dad92c6c3e5b418` | `artifacts/transcripts/restart_engine.json` | artifacts/inventory-sources/restart_engine.probe | no handler bound in stage2 tree at Phase-1 inventory |
| `restart_workbench` | restart control — workbench context | **ABSENT** | E1 candidate | 2026-07-29 | live | `512461ca3e9a6529bcdc57d9f21e98906ad2261381b3e624353d93932f6a710f` | `artifacts/transcripts/restart_workbench.json` | artifacts/inventory-sources/restart_workbench.probe | no handler bound in stage2 tree at Phase-1 inventory |
| `stop_summary` | stop-summary inventory source | **ABSENT** | E1 candidate | 2026-07-29 | live | `ed22841c8731d51e2ac524eaad0de06bc1f28f8b4485e0b59c2dcd636147f0be` | `artifacts/transcripts/stop_summary.json` | artifacts/inventory-sources/stop_summary.probe | no handler bound in stage2 tree at Phase-1 inventory |
| `preview_path` | preview path | **ABSENT** | E1 candidate | 2026-07-29 | live | `2b7c63cddb87234b3c8f95494723fbbbb5c6fb927582d653c8601b6879b14362` | `artifacts/transcripts/preview_path.json` | artifacts/inventory-sources/preview_path.probe | no handler bound in stage2 tree at Phase-1 inventory |
| `projects_collapse` | projects-collapse handler | **ABSENT** | E1 candidate | 2026-07-29 | live | `d09bf1bdead47114818937db22523313340812b4458d5acbbc2ca42ea3cb0416` | `artifacts/transcripts/projects_collapse.json` | artifacts/inventory-sources/projects_collapse.probe | no handler bound in stage2 tree at Phase-1 inventory |
| `cadence_telemetry` | cadence telemetry source | **ABSENT** | E1 candidate | 2026-07-29 | live | `1064f411a193248d44afe41883f02f0153f8ece361adaa8a7f6b51a874f82578` | `artifacts/transcripts/cadence_telemetry.json` | artifacts/inventory-sources/cadence_telemetry.probe | no handler bound in stage2 tree at Phase-1 inventory |
| `diagnose_claude` | Diagnose — Claude engine | **STUB** | build it | 2026-07-29 | live | `d17a04bd2b5dc6ce291492fc329811128382eaa2b57984ccd91d541a604f80c9` | `artifacts/transcripts/diagnose_claude.json` | artifacts/inventory-sources/diagnose_claude.probe | handler bound but returns canned seed — build it |
| `diagnose_gemini` | Diagnose — Gemini engine | **STUB** | build it | 2026-07-29 | live | `5d1779751b80abeb86478de0fcab802539089a24ad6421266241e19cbdcc3424` | `artifacts/transcripts/diagnose_gemini.json` | artifacts/inventory-sources/diagnose_gemini.probe | handler bound but returns canned seed — build it |
| `diagnose_grok` | Diagnose — Grok engine | **STUB** | build it | 2026-07-29 | live | `a8e7232ab8a866f88a73598d98dd9073e30cb4ef2aa46c73631898b812465f31` | `artifacts/transcripts/diagnose_grok.json` | artifacts/inventory-sources/diagnose_grok.probe | handler bound but returns canned seed — build it |

## Coverage

Required controls: 15
Recorded rows: 15
Missing: _(none)_
