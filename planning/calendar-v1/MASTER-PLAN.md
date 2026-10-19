# Anchor Calendar v1 — MASTER PLAN

**Stage:** Crucible Stage 1 (Master Plan) · **Date:** 2026-06-20 · **Depth:** FULL
**Status:** DRAFT — awaiting John's Stage-1 approval (then → Stage 2 Implementation Plan)
**Research base:** `planning/calendar-research/run-2026-06-20/CONSOLIDATED-BRIEF.md` (vetted, merges run-2026-06-15 + run-2026-06-17)
**Build vehicle:** the trio — Foreman builds wave-by-wave; every wave fully-stubbed-healthchecked (never live Google/MS) + UI sign-off per the v2–v11 standard.

---

## 1. North Star (LOCKED 2026-06-20)

> **Anchor displays all of John's Google + Outlook/M365 calendars in a real calendar view, and pushes John's Anchor-owned events out to a dedicated Anchor-owned calendar in each provider — fully local and private (no cloud, no inbound/public network surface) — and it can NEVER corrupt, delete, or duplicate a human-created event in John's real calendars.**

**Falsifiers (any one fails the objective):**
- (a) any write path that can mutate a non-Anchor-owned event;
- (b) any inbound/public network surface or webhook dependency;
- (c) a sync bug that silently loses or duplicates events;
- (d) a calendar dependency that breaks `distro.py`'s stdlib-only scan *outside* the declared `[calendar]` extra;
- (e) a render path that makes a synchronous network call.

Every wave below must serve this North Star (the inclusion test). Anything that doesn't is cut or Grass-caught.

---

## 2. LOCKED architecture (from research; do not re-litigate)

- **Poll, don't webhook.** Background `threading.Thread(daemon=True)` poll (mirror `anchor_gui._trigger_session_summary`). Render reads cached `.anchor/calendar/state.json` ONLY — never a sync network call (falsifier e). Cadence 5–15 min foreground / hourly background.
- **Two native REST clients:** Google Calendar v3 (`events.list` + `syncToken`; `410`→full resync) + Microsoft Graph (`GET /me/calendarView/delta` — GA v1.0, NOT beta `/events/delta`; `@odata.deltaLink`; guard the `skipToken` infinite loop). Pull recurring series un-expanded (`singleEvents=false`).
- **Auth:** OAuth2 Auth-Code + PKCE (S256), installed/desktop client, loopback `http://127.0.0.1:<ephemeral>/callback` (never `localhost`, never 8777). `webbrowser.open()` consent. DPAPI user-scope token storage via `ctypes` (`CryptProtectData`) — service runs as `.\john`. Document the user+machine-bound DPAPI footgun.

## 3. Resolved decisions (locked for this plan)

| # | Decision | Resolution |
|---|---|---|
| A | OAuth implementation | **`[calendar]` optional pip-extra** (`msal` + `google-auth`), lazy/degrade like `[terminal]=pywinpty`, in `distro.py`'s scoped allowlist. Still DPAPI-wrap at rest. |
| B | Sync scope | **TWO one-way pipes** (push Anchor-owned → dedicated Anchor calendar; pull all others read-only). NO symmetric three-way merge. Symmetric merge DEFERRED behind the dual-writer tripwire (§8). |
| C1 | Recurrence expander | **(a) Accept `allenporter/ical` inside the `[calendar]` extra + distro allowlist** (John, 2026-06-20). Adds a compiled native wheel (pydantic) but only in the opt-in extra; avoids hand-rolling the silent-failure-prone recurrence engine. |
| C2 | Google OAuth posture | **Design for Production** (durable refresh for unattended sync); **build the token store to tolerate 7-day expiry** as a fallback; the 8-day durable-refresh spike confirms before write-back ships (John, 2026-06-20). |

## 4. Component picks (folded in)

- **UI:** vendored **EventCalendar (vkurko, MIT)** in `vendor/event-calendar/` — **ship its LICENSE file** (no `license` field in package.json); FullCalendar **v6** is the named fallback (NOT v7 — adds a temporal-polyfill peer dep). Widget renders **pre-expanded** occurrences → the backend owns 100% of recurrence correctness.
- **Event store:** RFC-5545 **`.ics`-per-series + `meta.json` sidecar** under `.anchor/calendar/<account>/events/<icalUID>.ics`. **Sidecar MUST retain raw Graph JSON** (Graph `relativeMonthly`/`relativeYearly` with multiple `daysOfWeek` has no clean RRULE form — lossy). Override identity keyed `(iCalUID, original-start)`.
- **Sync engine:** hand-rolled two pipes; reference vdirsyncer's BSD `sync.py` — **copy its empty-replica "a replica went empty ⇒ abort, don't propagate deletes" guard** (cheap insurance against falsifier c).

---

## 5. Assumption map → premortem → mitigations

**Load-bearing assumptions:** (1) a Production-unverified Google app holds a durable refresh token for the sensitive scope — *UNVERIFIED, spike-gated*; (2) `ical`'s Timeline covers John's real RRULE surface — *spike-gated*; (3) Graph `recurrencePattern`→RRULE is lossy only in the enumerated relative-monthly/yearly cells — *spike-gated*; (4) the DPAPI/PKCE/loopback infra works — *OBSERVED, spike done*.

**Premortem — how v1 dies, and the mitigation baked into the plan:**

| Death | Mitigation (now a plan requirement) |
|---|---|
| **Echo display** — the PULL pipe reads ALL calendars *including Anchor's own dedicated calendar*, so pushed events render twice / fight the local copy *(Shark finding #1, BLOCKER)* | The pull pipe **excludes the Anchor-owned calendar id** from inbound display; Anchor's own events render from local `state.json`, never from a pull of its own calendar. Explicit wave acceptance criterion. |
| **Silent sync death** — the 7-day token expires (C2) or `invalid_grant` hits mid-background-poll; sync just stops; user thinks the calendar is current *(falsifier c-adjacent; Shark finding #3)* | The daemon detects `invalid_grant`/token-loss and surfaces an explicit **"Calendar needs re-auth"** state on the dashboard — **never a silent stop**. A poll-failure timestamp is visible. |
| **Recurring-event corruption on write** | Structurally prevented by the safety rail (write only to the Anchor-owned calendar) + override identity `(iCalUID, original-start)` + never rewrite a series `DTSTART`. |
| **Distro scan breaks** (falsifier d) | `ical`+pydantic live ONLY in the `[calendar]` extra + `distro.py` allowlist; Wave 1 adds a healthcheck assertion that the core import path stays stdlib-clean without the extra. |
| **The recurrence spike reveals a huge lossy-cell count** late | The Graph-recurrence enumeration spike is a **gate BEFORE the recurrence-hardening wave is estimated** (§7), not a discovery mid-build. |

---

## 6. Phased structure (master-plan altitude; Stage 2 decomposes to waves w/ acceptance criteria)

The dependency order is forced: store → auth → pull+display → push → harden → ship.

1. **Phase 1 — Event store + `[calendar]` extra foundation.** ICS-per-series + sidecar; `paths.calendar_dir()`; markdown-deadline→store mapping; declare the `[calendar]` extra (`msal`, `google-auth`, `icalendar`, `allenporter/ical`) + `distro.py` allowlist + the stdlib-clean-without-extra assertion. *Near-zero blast radius.*
2. **Phase 2 — Auth.** PKCE + loopback + DPAPI, thin wrappers over `msal`/`google-auth`. Reuse the OBSERVED 2026-06-15 spike harness. Production-posture config; token store tolerant of 7-day expiry; `invalid_grant`→re-auth surfaced state.
3. **Phase 3 — PULL pipe + EventCalendar display.** Both providers, incremental (syncToken/delta), `410`/token-loss→full resync, empty-replica abort guard. Expand recurrence via `ical` Timeline → render month/week/day. **Excludes the Anchor-owned calendar from inbound.** Render reads cache only.
4. **Phase 4 — PUSH pipe** to the dedicated Anchor-owned calendar (create-if-absent). Upsert by `iCalUID`; echo-suppress (self-marker + recorded ETag); Graph `transactionId` idempotent create. **Gated on the 8-day durable-refresh spike.**
5. **Phase 5 — Recurrence hardening.** The Graph `recurrencePattern` fixture table; sidecar-only fallback for lossy cells; override-identity correctness tests.
6. **Phase 6 — Ship.** CLI read-mirror (`cal status`/`cal pull`); fully-stubbed `check_calendar_surface` healthcheck (never live Google/MS); distro scan green; CLAUDE.md. *(PROJECT DONE.)*

---

## 7. Spikes & gates

- **Graph-recurrence enumeration spike (1 day, no accounts needed)** — enumerate every `recurrencePattern` variant into a clean-RRULE-vs-sidecar-only fixture table. **Gates the Phase-5 estimate.** Can run now / in parallel with Stage 2.
- **8-day durable-refresh spike** (needs John's Google app registration + consent + wall-clock) — confirms the Production-unverified durable-RT assumption. **Gates Phase 4 (write-back) only**, not planning. Runbook: `run-2026-06-15/spike/RUNBOOK.md`.
- **MSA vs work/school** — confirm which Microsoft account John connects (changes `/common` vs `/consumers` + RT reliability) before Phase 2 locks the authority.

## 8. Out of scope (v1) + the tripwire

- **Symmetric two-way merge** over dual-writer events — DEFERRED. **Tripwire:** returns ONLY when a user is allowed to natively edit/delete, *inside Anchor*, an event an external provider also mutates. Until then two one-way pipes are correct and sufficient.
- **Editing the user's PRIMARY calendars from Anchor** — explicitly out; a later opt-in.
- No SaaS aggregator (Nylas/Cronofy/Cal.com) — all require cloud + public webhook (falsifier b).

## 9. Verification standard (non-negotiable)

Every wave: a **fully-stubbed** healthcheck slice (fake HTTP responder seam; never live Google/MS). Every UI wave: DOM assertions + Playwright + Chromium interaction test + screenshot + John's sign-off (the v4 lesson). `distro.py` import scan stays green (only the declared `pywinpty` + the new scoped `[calendar]` allowlist). Playwright stays DEV-ONLY (`pytest.importorskip`), never in product code.

---

## 10. Shark-Tank record (Stage 1, FULL)

3 fresh-context Sharks (Skeptic / Contrarian / Analyst), each prompted to refute, North Star embedded. BLOCKER = ≥2 agree.

- **Finding #1 (Skeptic + Analyst agree → BLOCKER):** the pull pipe re-ingesting Anchor's own dedicated calendar causes echo/double-render. → **Resolved:** §5 + Phase 3 exclude-own-calendar acceptance criterion.
- **Finding #2 (Contrarian):** "the richer ICS store was justified as the *merge* prerequisite, which is now deferred — is it still needed?" → **Resolved (kept, re-justified):** markdown cannot hold RRULE/EXDATE/VTIMEZONE; faithful recurring **display** + the push source both require it. It earns its place under the new scope; it is no longer safety-gating. Not bloat (passes the inclusion test).
- **Finding #3 (Analyst):** silent sync death on the 7-day/`invalid_grant` path. → **Resolved:** §5 explicit "needs re-auth" surfaced state — no silent stop.
- **Convergence:** a second round produced no new AXIS finding (dry). Stage 1 converged.

---

**Next:** on John's approval → **Stage 2 Implementation Plan** (decompose Phases 1–6 into Foreman waves with per-wave `done-when` + Given/When/Then acceptance criteria), Shark-Tank to convergence, well-formedness gate (`locate-plan.mjs`), then the Foreman handoff doc-trio + `foreman.config.json`.
