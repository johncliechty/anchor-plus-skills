# Crucible Decision Addendum — Component Picks for the Anchor Calendar

> Append this to `planning/calendar-research/run-2026-06-15/CRUCIBLE-PROMPT.md`. It fills the four surfaces that prompt left as "design around it" with **specific, adversarially-vetted component choices**, and flags one scope change that is John's to ratify. Backend (poll-not-webhook · OAuth2-PKCE/DPAPI · two REST clients) is unchanged and locked.

## Vetted component picks (each survived a context-free Judge)

| Surface | Pick | License | Goes in | Caveat to plan around |
|---|---|---|---|---|
| **Calendar UI widget** | **EventCalendar (vkurko/calendar)** — vendored static; FullCalendar v6 = named fallback | MIT | `vendor/event-calendar/` (static, no build) | Renders **pre-expanded** occurrences only → backend owns 100% of recurrence correctness |
| **Event store** | **RFC-5545 `.ics`-per-series + `meta.json` sidecar** | n/a | `.anchor/calendar/<account>/events/<icalUID>.ics` + sidecar | Sidecar **MUST retain raw Graph JSON** (lossless source for Graph-only recurrence) |
| **Recurrence expander** | **`allenporter/ical` (Timeline)** — NOT LGPL `recurring-ical-events` | permissive | `[calendar]` extra (with `icalendar` BSD) | Verify Timeline covers the full RRULE surface before locking |
| **Sync engine** | **Hand-roll TWO one-way pipes**; reference vdirsyncer `sync.py`; copy its empty-replica abort guard | (own) | `calendar_sync.py` | See scope change below |
| **Architecture** | **Direct REST** (no SaaS, no unified lib — none fits local-private) | — | — | — |

## SCOPE CHANGE for Stage-0 ratification (narrows DECISIONS.md Decision B)

**Finding (Judge HIGH):** the locked safety rail — *Anchor only ever WRITES to its dedicated Anchor-owned calendar* — gives every event exactly one authoritative writer. That **collapses the symmetric three-way merge into two one-way pipes**:
- **PUSH pipe:** Anchor-owned events → provider (Anchor's dedicated calendar only). Echo-suppress via self-marker + recorded ETag.
- **PULL pipe:** all other calendars → Anchor, **read-only display**. ETag/sync-token change-detection (Google `syncToken`, Graph `/me/calendarView/delta`); `410`/token-loss → full resync.

No stored content baseline, no symmetric conflict resolution, **no richer-store-as-Wave-1 prerequisite for safety** (the store is still ICS+sidecar, but it isn't gating a dangerous merge). **Tripwire — full three-way merge returns ONLY when** a user is allowed to natively edit/delete *inside Anchor* an event that an external provider also mutates (two concurrent writers). Recommend: **ratify the reduction; defer symmetric merge behind that tripwire.**

## Corrections to the prior handoff
- **Graph delta endpoint:** use **`/me/calendarView/delta` (GA v1.0)** — `/events/delta` is **beta-only**. (`03-agent-impl.md` listed them as interchangeable.)
- **Recurrence expander:** prefer **`allenporter/ical`** (permissive) over `recurring-ical-events` (**LGPL-3.0**, an avoidable copyleft obligation).

## Gate before estimating the recurrence wave (cheapest de-risk)
**1-day spike:** enumerate every Graph `recurrencePattern` variant (daily / weekly / absoluteMonthly / relativeMonthly / absoluteYearly / relativeYearly × single & multiple `daysOfWeek` × `index` first/second/third/fourth/last) into a fixture table; for each assert **clean RRULE round-trip** OR an explicit **"sidecar-only, not RRULE-expressible"** flag. The lossy-cell count is the gate on the recurrence estimate and proves the sidecar is load-bearing. (Runs alongside the still-pending 8-day Google durable-refresh check from the 2026-06-15 spike RUNBOOK.)

## Suggested wave skeleton (refine in Stage 1)
1. **ICS+sidecar event store** + markdown-deadline → store mapping (+ `[calendar]` extra w/ `icalendar`+`allenporter/ical`; lazy/degrade like `pywinpty`; `distro.py` allowlist).
2. **Auth** (`[calendar]` + msal/google-auth, PKCE, DPAPI) — reuse the OBSERVED 2026-06-15 spike harness.
3. **PULL pipe + EventCalendar display** (vendor the widget; render month/week/day from expanded occurrences; render path reads `state.json` cache only).
4. **PUSH pipe** to the Anchor-owned dedicated calendar (gated on the 8-day durable-refresh spike result).
5. **Recurrence hardening** (the Graph fixture table; override identity `(iCalUID, original-start)`).
6. CLI mirror (`cal status`/`cal pull`) + **fully-stubbed `check_calendar_surface`** healthcheck (never live Google/MS) + distro scan + CLAUDE.md.

Every UI wave: DOM assertions + Playwright + screenshot + John's sign-off (the v2–v9 standard).
