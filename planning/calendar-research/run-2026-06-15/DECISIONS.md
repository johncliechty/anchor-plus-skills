# Locked Decisions — Anchor Calendar Integration (John, 2026-06-15)

These resolve the two open questions from `01-report.md` §2. They are the locked scope for the Crucible planning session.

## Decision A — OAuth implementation: **`[calendar]` optional extra** (Option 1, the Judge's pick)
- Use the providers' own first-party libraries — **`msal`** (Microsoft) + **`google-auth`** (Google) — for the OAuth token lifecycle, declared as a **lazy, optional pip extra** exactly like `[terminal]=pywinpty`.
- Declared in `pyproject.toml` as `calendar = [...]` AND added to `distro.py`'s scoped import-allowlist (the calendar module only). Must degrade gracefully ("calendar unavailable") when absent, like the `PtyUnavailable` pattern.
- Still **DPAPI-wrap the token cache at rest** (user scope — service runs as `.\john`).

## Decision B — Scope: **full bidirectional two-way, up front** (Option 2 — John's original ask)
- Build full symmetric two-way sync over Google + Microsoft, not the phased pull-only-first cut.
- **PREREQUISITE (mandatory, first build wave):** replace the markdown-line storage model for calendar data with a **richer event store under `.anchor/calendar/`** (ICS/JSON that can faithfully hold RRULE recurrence, EXDATE overrides, VTIMEZONE, attendees). Markdown lines are lossy-by-construction for real events; two-way over arbitrary events is unsafe until this lands. Markdown deadlines/tasks remain their own source of truth and map INTO this store.
- **SAFETY RAIL (non-negotiable):** Anchor reads/displays ALL of the user's calendars, but **only ever writes (create/update/delete) to a dedicated "Anchor"-owned calendar** in each provider. It never holds a delete/update handle on a human-created event. Two-way editing of the user's PRIMARY calendars is a later, explicitly-opted-in step, NOT part of this scope.
- Full two-way engine per `03-agent-impl.md`: iCalUID-keyed mapping table + last-synced-baseline three-way merge (Unison/vdirsyncer model), echo-suppression via etag+self-marker, tombstones, recurring master+exception handling.

## Decision B — AMENDMENT (RATIFIED by John, 2026-06-17): two one-way pipes, NOT a symmetric three-way merge
The 2026-06-17 best-in-class options run (`planning/calendar-research/run-2026-06-17/`) found — and a context-free Judge ruled HIGH confidence — that the **safety rail above already makes the *symmetric* part of "full two-way" unnecessary.** Because Anchor only ever WRITES to its own dedicated calendar, **every event has exactly one authoritative writer**, which collapses the hard symmetric three-way merge into **two one-way pipes**:
- **PUSH pipe:** Anchor-owned events → the dedicated Anchor calendar in each provider. Echo-suppress via self-marker + recorded ETag. Upsert by `iCalUID`.
- **PULL pipe:** ALL other calendars → Anchor, **read-only display**. ETag/sync-token change-detection (Google `syncToken`; Graph **`/me/calendarView/delta`** — GA, NOT the beta `/events/delta`); `410`/token-loss → full resync as a normal path.

**RATIFIED:** Build the two one-way pipes. Do **NOT** build the iCalUID-baseline three-way merge engine now. There is **no stored content baseline and no symmetric conflict resolution** in scope. The richer `.anchor/calendar/` event store is still built (it's how recurrence is held faithfully) but it is **no longer gating a dangerous merge** — it serves display + the push pipe.

**TRIPWIRE — the deferred symmetric merge returns ONLY when:** a user is allowed to natively edit or delete, *inside Anchor*, an event that an external provider also mutates (i.e. any event with two concurrent independent writers). Until that feature is explicitly chosen, two one-way pipes are correct and sufficient. This supersedes the earlier "full symmetric two-way + mapping-table three-way-merge engine" framing of Decision B above; the iCalUID mapping/baseline engine in `03-agent-impl.md` is now DEFERRED behind this tripwire.

**Component picks ratified alongside (from the 2026-06-17 run — see `run-2026-06-17/04-crucible-decision-addendum.md`):** UI widget = vendored **EventCalendar (vkurko, MIT, zero-dep)**; event store = **RFC-5545 `.ics`-per-series + `meta.json` sidecar that retains raw Graph JSON**; recurrence expander = **`allenporter/ical` (permissive)**, NOT the LGPL `recurring-ical-events`; sync engine = **hand-rolled**, referencing vdirsyncer's BSD `sync.py`; architecture = **direct REST** (no SaaS).

## Unchanged locked architecture (from the validated research)
- **Poll, don't webhook** (localhost can't receive push). Google `syncToken` + Graph `/delta` on a background daemon thread; render reads cache only.
- **Two native REST clients** (Google Calendar v3 + MS Graph); no CalDAV.
- **Auth:** OAuth2 Auth-Code + PKCE, **installed/desktop** client type, loopback `127.0.0.1:<ephemeral>/callback` (not 8777). Google OAuth app → **Production** publishing status (escape the 7-day Testing-mode refresh-token revoke); calendar = sensitive scope, may stay unverified for personal use.

## Build path
1. **De-risk spike first (~50 LOC):** real loopback+PKCE against one real Google + one real M365 app registration; fetch a page of events; leave a token 8 days to confirm durable refresh. Upgrades the feasibility claims from CORROBORATED → OBSERVED.
2. **Crucible** → freeze `planning/calendar-v1/` (MASTER-PLAN + IMPLEMENTATION-PLAN), wave 1 = the richer event store, then auth, then pull+display, then write-back to the Anchor-owned calendar, then the full two-way reconcile engine.
3. **Foreman** → build wave-by-wave; every wave stubbed-healthchecked (never live Google/MS) + UI sign-off (the v2–v7 standard).
