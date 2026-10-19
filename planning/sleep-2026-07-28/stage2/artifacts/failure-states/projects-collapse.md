# Projects-collapse failure-state table

Build: Anchor sleep cycle 2026-07-28 (v1.2)
Wave: W19 — Phase 3: Projects collapsed by default + remembered preference
Surface: `projects_collapse`
Schema: failure-state-table/v1 (mapped through `artifacts/STATE-VOCABULARY-MAP.md`)

Surface-native language only (projects / collapse / preference / panel render).
Doctor-tile hygiene vocabulary is honesty theater on this surface and must not
appear.

**unknown** and **empty** are SEPARATE rows. Combining those two states into one
row is a build failure (hardening gates 0080/0081).

* **empty** — project list read succeeded and there are no projects
* **unknown** — project list could not be read, **or** preference store could
  not be read (preference path shows unknown; folders still fall back collapsed)
* Neither state is presented as a confident user expand/collapse choice

## Rows (machine-readable)

| hardening | state | user_visible | trigger |
|-----------|-------|--------------|---------|
| dependency-missing | unknown | unknown | projects_collapse capability absent — panel render shows unknown for unreadable paths (never empty-looking project list) |
| dependency-slow-or-killed | timeout | timeout | projects-collapse dependency slow or killed during panel render |
| dependency-returns-garbage | measurement_failed | measurement_failed | projects-collapse dependency returned garbage payload during panel render |
| backing-store-unreadable | unknown | unknown | project list unreadable **or** preference store unreadable — panel shows unknown; folders force-collapsed; never empty; never silent user choice |
| empty-but-valid | empty | empty | project list read succeeded; no projects — panel empty (distinct from unknown) |
| empty-but-valid | zero_measured | zero_measured | projects aggregation over existing scope measured total 0 |

## Enumerated projects-collapse reasons (handler / panel)

| reason | named_state | user_visible | trigger |
|--------|-------------|--------------|---------|
| ok | ok | ok | project list readable with folders; preference readable (or default collapsed) |
| default_collapsed | ok | ok | first-ever load — all folders collapsed, preference key ready |
| preference_store_unreadable | unknown | unknown | preference store could not be read — collapsed fallback + unknown preference (never silent user choice) |
| project_list_unreadable | unknown | unknown | project list could not be read (unknown ≠ empty) |
| no_projects | empty | empty | project list read succeeded with zero projects |
| stale_preference_key | ok | ok | stored preference key version mismatch — expand set ignored; collapsed default applied |
| preference_payload_garbage | unknown | unknown | preference payload unusable — treated as unreadable |

## Preference honesty

* Unreadable preference store → **unknown** on the preference panel via
  `render_state(NamedState.unknown)` plus visible detail
  "preference store unreadable — collapse default applied".
* Folders still render **collapsed** (class `collapsed` /
  `data-collapsed="true"`) so first paint never invents an expanded user choice.
* Empty project list never shares a row with unknown.

## Dual-profile note

Profiles `profile_A` and `profile_B` isolate expand sets under preference key
`projects.collapse.v1`. Cross-profile bleed is a build failure of the dual-profile
GWT, not a separate named state.

## Mapping notes

* `backing-store-unreadable` → **unknown** only (never empty, never a silent blank).
* `empty-but-valid` requires **empty** and **zero_measured** as separate rows.
* Project-list unknown and preference unknown both map to **unknown**; they are
  distinguished in visible detail text and `data-reason`, not by inventing a
  second NamedState member.
* Surface actions: projects, collapse, preference, panel render.
