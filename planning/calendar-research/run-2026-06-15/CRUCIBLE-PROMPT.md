# Paste this into a fresh Crucible session

---

Plan a new Anchor feature: **a built-in calendar that does full two-way sync with the user's Google and Microsoft 365 / Outlook calendars** — import/display all their calendars AND push events back. This has already been through a validated researchPrime study and two locked user decisions; your job is to produce the frozen, Foreman-ready design + implementation plan. Do NOT re-open the locked decisions below — plan within them.

## Project context
Anchor is a single-user personal productivity app for J.C. Liechty at `C:\dev\Anchor`: plain-markdown files as the source of truth, a stdlib-only Python HTTP server (`anchor_gui.py`) that runs as a persistent Windows NSSM service named `anchor` on `http://localhost:8777` (bound 127.0.0.1, runs as user `.\john`), with a CLI mirror (`anchor.py`). Read `CLAUDE.md` for architecture and idioms. The R&D surfaces v2–v7 are the precedent for how features are built here (Crucible-planned → Foreman-built, wave-by-wave, fully-stubbed healthcheck, per-wave UI sign-off).

## North Star (the locked objective)
Anchor faithfully shows the user's Google + Outlook calendars inside Anchor and keeps a bidirectional sync, WITHOUT ever corrupting or losing real calendar data and WITHOUT breaking Anchor's local/private, single-service posture. Success is FALSIFIED if: the sync can delete/duplicate/mangle an event the user created in their own calendar; or the dashboard render makes a synchronous network call; or it requires exposing a public inbound endpoint; or it silently stops syncing without surfacing the failure.

## The full research + spike are on disk — read them first
- `planning/calendar-research/run-2026-06-15/01-report.md` (full report), `02-executive.md`, `03-agent-impl.md` (implementation handoff with the two-way engine spec), `evidence-ledger.jsonl`, `DECISIONS.md` (the locked decisions), and `spike/SPIKE-FINDINGS.md` + `spike/RUNBOOK.md` (auth proof).

## LOCKED decisions (do not re-litigate — plan to these)
1. **OAuth via an official `[calendar]` optional pip-extra** (`msal` for Microsoft + `google-auth`/`google-auth-oauthlib` for Google), declared lazily exactly like the existing `[terminal]=pywinpty` extra (in `pyproject.toml` + `distro.py`'s scoped import-allowlist; degrade gracefully to "calendar unavailable" when absent). Tokens still DPAPI-wrapped at rest (user scope).
2. **Full bidirectional two-way, built up front** (NOT a phased pull-only cut). Two non-negotiable framing constraints that fall out of this:
   - **Prerequisite (earliest wave): a richer calendar-event store under `.anchor/calendar/`** (ICS/JSON that faithfully holds RRULE recurrence, EXDATE overrides, VTIMEZONE, attendees). Markdown lines are lossy-by-construction for real events and must NOT be the calendar data model. Markdown deadlines/tasks remain their own source of truth and map INTO this store.
   - **Safety rail (non-negotiable): Anchor reads/displays ALL the user's calendars but only ever WRITES (create/update/delete) to a dedicated "Anchor"-owned calendar it creates in each provider.** It never holds a delete/update handle on a human-created event. Two-way editing of the user's PRIMARY calendars is explicitly OUT of scope (a possible future opt-in).

## Validated architecture (treat as established; design around it)
- **Poll, do not webhook** — a localhost service cannot receive Google/Graph push (both require a public HTTPS+CA-cert endpoint). Use Google `events.list`+`syncToken` and MS Graph `/me/calendarView/delta` (or `/events/delta`); handle `410 GONE` / token-loss → full resync as a normal path. Poll on a background daemon thread (mirror `anchor_gui._trigger_session_summary`); the dashboard render reads only a cached `.anchor/calendar/state.json`.
- **Two native REST clients** (Google Calendar API v3 + Microsoft Graph) over the `[calendar]` libs. CalDAV is out (Microsoft has none).
- **Auth:** OAuth2 Auth-Code + **PKCE**, **installed/desktop public client** (no embeddable secret — a "Web" client would trip `distro.py`'s no-secrets scan). Loopback `http://127.0.0.1:<ephemeral>/callback` (NOT 8777, which binds `SO_EXCLUSIVEADDRUSE`). `webbrowser.open()` for the one-time consent. **Do NOT gate PKCE on Microsoft's discovery doc** (it omits `code_challenge_methods_supported` though Graph supports S256 — confirmed by the spike). Google OAuth app must be in **Production** publishing status to escape the 7-day Testing-mode refresh-token revoke (may remain unverified for personal single-user use; calendar is a *sensitive*, not restricted, scope). Microsoft refresh tokens **rotate** — persist the new one each refresh.
- **Two-way correctness engine** (see `03-agent-impl.md` for the full spec): a persisted mapping table keyed by `iCalUID` + a last-synced baseline three-way merge (the Unison/vdirsyncer model), echo-loop suppression via ETag+self-marker, tombstones for deletions, and recurring master+exception handling (never rewrite a series `DTSTART`). Top failure modes to design against: echo/ping-pong loop, recurring-event corruption, duplicate-by-name, deleted-event resurrection, stale-after-410, cross-system clock-skew.

## Anchor build idioms to honor (verification standard is non-negotiable)
- New modules at repo root are auto-first-party (e.g. `calendar_auth.py`, `calendar_sync.py`, `calendar_store.py`); add `paths.calendar_dir()`. New HTTP routes on `AnchorHandler` (`/api/calendar/connect|callback|refresh|disconnect`, token-authed mutations). Read-only CLI mirror in `anchor.py` (`cal status`, `cal pull`).
- **Healthcheck must be FULLY STUBBED** — a fake HTTP responder seam (monkeypatch `urllib`/the client); walk PKCE→DPAPI round-trip→PULL→reconcile→write-back-to-stub; restore env + teardown. **NEVER hit live Google/Microsoft in any test or the healthcheck.** Mirror the existing `check_rnd_v*_surface` pattern.
- Every UI wave: rendered-DOM assertions (positive+negative) + a real Playwright+Chromium interaction test + an orchestrator screenshot + John's sign-off before merge. **Playwright is a DEV-ONLY dep, never imported by product code.**
- Storage under `.anchor/` is auto-excluded from distro builds; keep tokens there.

## Open item to gate on (not a blocker to planning)
The durable-refresh proof (does a Google Production-unverified app hold a refresh token past 7 days) runs as an 8-day spike in parallel (`spike/RUNBOOK.md`). Gate the first WRITE-BACK wave on its result; planning + the read/store waves don't depend on it.

## What I want from you (Crucible)
Run your normal Stage 0 (Intake & Framing — confirm/sharpen the North Star above) → Stage 1 (Master Plan) → Stage 2 (Implementation Plan + Foreman handoff), with the Shark-Tank adversarial loop. Produce frozen `planning/calendar-v1/MASTER-PLAN.md` + `planning/calendar-v1/IMPLEMENTATION-PLAN.md`, Foreman-ready, wave-structured. A sensible wave skeleton to refine (not prescriptive): (1) the richer `.anchor/calendar/` event store + the markdown↔store mapping; (2) the `[calendar]` extra + OAuth/PKCE/DPAPI auth module (Google + Microsoft); (3) incremental PULL + a real in-Anchor calendar display; (4) WRITE-BACK to the Anchor-owned calendar (gated on the durable-refresh spike); (5) the full two-way reconcile engine + conflict handling; (6) CLI mirror + fully-stubbed healthcheck + distro scan + docs/CLAUDE.md. Surface any risk that the locked decisions create and flag anything that should be John's call.
