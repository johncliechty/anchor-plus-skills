# Preview failure-state table

Build: Anchor sleep cycle 2026-07-28 (v1.2)
Wave: W18 — Phase 3: File preview via the shared human-friendly path
Surface: `preview`
Schema: failure-state-table/v1 (mapped through `artifacts/STATE-VOCABULARY-MAP.md`)

Surface-native language only (preview). Doctor-tile hygiene vocabulary is
honesty theater on this surface and must not appear.

**unknown** and **empty** are SEPARATE rows. Combining those two states into one
row is a build failure (hardening gates 0080/0081).

* **empty** — file read succeeded and the file is zero bytes (nothing to preview)
* **unknown** — type probe or file read failed (never looks empty)
* Binary content without a human-friendly renderer surfaces as a named
  `unsupported_preview` state plus a download affordance — never a raw dump

## Rows (machine-readable)

| hardening | state | user_visible | trigger |
|-----------|-------|--------------|---------|
| dependency-missing | unknown | unknown | preview path capability absent or not authorized — preview shows unknown (never empty) |
| dependency-slow-or-killed | timeout | timeout | preview dependency slow or killed during preview render |
| dependency-returns-garbage | measurement_failed | measurement_failed | preview dependency returned garbage payload, or content-type has no human-friendly renderer (unsupported_preview + download) |
| backing-store-unreadable | unknown | unknown | file type probe failed or file unreadable at preview — shows unknown; never empty; never "nothing to preview" |
| empty-but-valid | empty | empty | preview read succeeded; zero-byte file — preview empty (distinct from unknown) |
| empty-but-valid | zero_measured | zero_measured | preview extract ran over existing supported file; measured content units is 0 |

## Enumerated preview reasons (handler)

| reason | named_state | user_visible | trigger |
|--------|-------------|--------------|---------|
| ok | ok | ok | shared path extracted human-friendly text for docx/pptx/xlsx/pdf |
| unsupported_preview | measurement_failed | unsupported_preview | content-type has no human-friendly renderer — download affordance only; never raw byte dump |
| empty_file | empty | empty | zero-byte file; read succeeded (empty ≠ unknown) |
| probe_failed | unknown | unknown | type probe or file read failed (unknown ≠ empty) |
| extract_failed | measurement_failed | measurement_failed | supported format detected but extract failed |
| zero_measured | zero_measured | zero_measured | supported file present; extracted content units measured 0 |
| capability_absent | unknown | unknown | preview_path inventory source not authorized |

## Inventory source (CAPABILITY-INVENTORY)

* Control id: `preview_path`
* Label: preview path
* Collector: `anchor.files.preview.preview_bytes` / `preview_path`
* View: `anchor.ui.preview_view.render_preview_panel` via `render_state`

## Binary guard

* Rendered HTML must never contain the zip signature text `PK\x03\x04` or other
  raw byte signatures from Office/PDF payloads.
* Unsupported types render the visible token `unsupported_preview` and a
  Download link — never a text dump of the payload.

## Mapping notes

* `backing-store-unreadable` → **unknown** only (never empty, never a silent blank).
* `empty-but-valid` requires **empty** and **zero_measured** as separate rows.
* Zero-byte file must never render as "file type probe failed".
* Probe failure must never render as "nothing to preview".
* Surface actions: preview.
