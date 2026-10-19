# Paste this into a fresh Crucible session

> Combined, current-as-of-2026-06-17 Crucible brief for the Anchor calendar feature. Supersedes `run-2026-06-15/CRUCIBLE-PROMPT.md` — it folds in the ratified two-one-way-pipes scope reduction and the four vetted component picks from the 2026-06-17 options run. Everything below is decided; plan WITHIN it.

---

Plan a new Anchor feature: **a built-in, Google/Outlook-like calendar that displays the user's Google + Microsoft 365/Outlook calendars and keeps them in sync** — pull all their calendars in for display, and push Anchor's own events back out. This has been through TWO validated researchPrime studies and a set of user-ratified decisions; your job is to produce the frozen, Foreman-ready design + implementation plan. **Do NOT re-open the locked decisions below — plan to them.**

## Project context
Anchor is a single-user personal productivity app for J.C. Liechty at `C:\dev\Anchor`: plain-markdown files as the source of truth, a **stdlib-only** Python HTTP server (`anchor_gui.py`) that runs as a persistent Windows NSSM service named `anchor` on `http://localhost:8777` (bound `127.0.0.1`, runs as user `.\john`), with a CLI mirror (`anchor.py`). It serves a handful of **vendored static** JS/CSS assets (precedent: xterm.js, KaTeX, anchor-term) — there is **no npm/bundler/Node runtime in production**. There is one narrow precedent for an optional, lazily-imported pip-extra that degrades gracefully when absent: `[terminal]=pywinpty`. Read `CLAUDE.md` for architecture and idioms. The R&D surfaces v2–v9 are the precedent for how features are built here (Crucible-planned → Foreman-built, wave-by-wave, fully-stubbed healthcheck, per-wave UI sign-off).

## North Star (the locked objective)
Anchor faithfully **shows** the user's Google + Outlook calendars inside Anchor and keeps them in sync, **WITHOUT ever corrupting or losing real calendar data** and **WITHOUT breaking Anchor's local/private, single-service posture.** Success is FALSIFIED if: a sync operation can delete/duplicate/mangle an event the user created in their own calendar; or the dashboard render makes a synchronous network call; or it requires exposing a public inbound endpoint; or it silently stops syncing without surfacing the failure.

## The full research is on disk — read it first
- `planning/calendar-research/run-2026-06-15/` — `01-report.md`, `03-agent-impl.md` (the original engine spec, now partly DEFERRED — see locked decision 3), `DECISIONS.md` (locked decisions + the 2026-06-17 ratified amendment), `spike/SPIKE-FINDINGS.md` + `spike/RUNBOOK.md` (auth proof — infra is OBSERVED).
- `planning/calendar-research/run-2026-06-17/` — `01-report.md` (the options survey), `04-crucible-decision-addendum.md` (the component picks + scope reduction in detail), `lanes/`.

## LOCKED decisions (do not re-litigate — plan to these)

**1. OAuth via an official `[calendar]` optional pip-extra.** `msal` (Microsoft) + `google-auth`/`google-auth-oauthlib` (Google) for the OAuth token lifecycle, declared lazily exactly like `[terminal]=pywinpty` (in `pyproject.toml` + `distro.py`'s scoped import-allowlist; degrade to "calendar unavailable" when absent). Tokens DPAPI-wrapped at rest (user scope — service runs as `.\john`).

**2. Component picks (each survived a context-free adversarial Judge, 2026-06-17):**
- **UI widget → vendor `EventCalendar` (vkurko/calendar), MIT, zero-dependency ~35 KB standalone** (Svelte compiled away; no build step) into `vendor/event-calendar/`. FullCalendar v6 is the documented fallback if drag-create ergonomics/time-grid polish fall short. **The widget renders PRE-EXPANDED occurrence instances** — it has no client-side recurrence engine, so the backend owns 100% of recurrence correctness.
- **Event store → canonical RFC-5545 `.ics`-per-series + a `meta.json` sidecar** at `.anchor/calendar/<account>/events/<icalUID>.ics` (RECURRENCE-ID overrides = sibling VEVENTs sharing the UID). The **sidecar MUST retain the raw provider JSON** (esp. Graph): Microsoft Graph emits a *structured* `recurrencePattern`+`recurrenceRange`, not RRULE, and `relativeMonthly`/`relativeYearly` with multiple `daysOfWeek` ("first day that satisfies") has **no clean RRULE equivalent** → Graph→RRULE is provably lossy, so raw JSON is the only lossless source of truth. Markdown deadlines/tasks remain their own source of truth and map INTO this store.
- **Recurrence expander → `allenporter/ical` (Timeline), permissively licensed** — NOT the LGPL-3.0 `recurring-ical-events` (avoidable copyleft). Goes in the `[calendar]` extra with `icalendar` (BSD). `ics.py` is disqualified (no RRULE). Verify Timeline covers the full RRULE surface before locking.
- **Sync engine → hand-rolled** (no maintained Python Google↔Graph two-way engine exists), **referencing vdirsyncer's BSD `sync.py`** — copy its "a replica went empty ⇒ abort, don't propagate deletes" data-loss tripwire. Architecture = **direct REST** (no SaaS/unified service — they route data through their cloud + need a public webhook, both fatal to the North Star).

**3. Scope → TWO ONE-WAY PIPES, not a symmetric three-way merge (RATIFIED by John, 2026-06-17 — see `DECISIONS.md` amendment).** The safety rail (below) gives every event exactly one authoritative writer, which collapses the hard symmetric merge:
- **PUSH pipe:** Anchor-owned events → a dedicated **Anchor-owned calendar** Anchor creates in each provider. Echo-suppress via self-marker + recorded ETag; upsert by `iCalUID`.
- **PULL pipe:** ALL other calendars → Anchor, **read-only display**. ETag/sync-token change-detection only.
- **NO stored content baseline, NO symmetric conflict resolution, NO iCalUID-baseline three-way-merge engine** in this scope. The `03-agent-impl.md` mapping/baseline engine is **DEFERRED behind a tripwire.**
- **TRIPWIRE (the only condition that re-opens the merge):** a user is allowed to natively edit/delete, *inside Anchor*, an event that an external provider also mutates (two concurrent writers). Out of scope until explicitly chosen.

**4. Safety rail (non-negotiable).** Anchor reads/displays ALL the user's calendars but **only ever WRITES (create/update/delete) to the dedicated "Anchor"-owned calendar it creates in each provider.** It never holds a delete/update handle on a human-created event. This is the structural reason scope-decision 3 is safe.

## Validated architecture (treat as established; design around it)
- **Poll, do not webhook** — a localhost service cannot receive Google/Graph push (both require a public HTTPS + CA-cert endpoint). Use Google `events.list`+`syncToken` and **Microsoft Graph `/me/calendarView/delta` (GA v1.0 — NOT the beta `/events/delta`)**; handle `410 GONE` / token-loss → full resync as a normal path. Poll on a background daemon thread (mirror `anchor_gui._trigger_session_summary_on_finish`); the dashboard render reads only a cached `.anchor/calendar/state.json` — never a sync network call on render.
- **Two native REST clients** (Google Calendar API v3 + Microsoft Graph) over the `[calendar]` libs. CalDAV is out (Microsoft has none).
- **Auth:** OAuth2 Auth-Code + **PKCE**, **installed/desktop public client** (no embeddable secret — a "Web" client would trip `distro.py`'s no-secrets scan). Loopback `http://127.0.0.1:<ephemeral>/callback` (NOT 8777, which binds `SO_EXCLUSIVEADDRUSE`). `webbrowser.open()` for the one-time consent. **Do NOT gate PKCE on Microsoft's discovery doc** (it omits `code_challenge_methods_supported` though Graph supports S256 — confirmed by the spike). Google OAuth app must be in **Production** publishing status to escape the 7-day Testing-mode refresh-token revoke (may remain unverified for personal single-user use; calendar is a *sensitive*, not restricted, scope). Microsoft refresh tokens **rotate** — persist the new one each refresh. (All 5 of these OAuth facts re-confirmed against primary docs 2026-06-17; the TLS/PKCE/loopback/DPAPI infra is OBSERVED on this machine per the spike.)
- **Provider gotchas to encode as tests:** Google `nextSyncToken` only on the FINAL page; pull recurring `singleEvents=false`; deletions = `status:cancelled`. Graph: guard the `calendarView/delta` infinite-skipToken loop; `transactionId` for idempotent create; `@odata.etag`/`If-Match`→412; confirm MSA vs work/school authority. Recurrence override identity = key series by `iCalUID`, instance by `(iCalUID, original-start)` or you render ghost/duplicate occurrences.

## Anchor build idioms to honor (verification standard is non-negotiable)
- New modules at repo root are auto-first-party (e.g. `calendar_auth.py`, `calendar_sync.py`, `calendar_store.py`); add `paths.calendar_dir()`. New HTTP routes on `AnchorHandler` (`/api/calendar/connect|callback|refresh|disconnect`, token-authed mutations). Read-only CLI mirror in `anchor.py` (`cal status`, `cal pull`).
- **Healthcheck must be FULLY STUBBED** — a fake HTTP responder seam (monkeypatch `urllib`/the client); walk PKCE → DPAPI round-trip → PULL → expand → display-state → PUSH-to-stub; restore env + teardown. **NEVER hit live Google/Microsoft in any test or the healthcheck.** Mirror the existing `check_rnd_v*_surface` pattern.
- Every UI wave: rendered-DOM assertions (positive+negative) + a real Playwright+Chromium interaction test + an orchestrator screenshot + John's sign-off before merge. **Playwright is a DEV-ONLY dep, never imported by product code** (`distro.py`'s scan enforces this).
- Storage under `.anchor/` is auto-excluded from distro builds; keep tokens there.

## Open items to gate on (NOT blockers to planning)
1. **Graph-recurrence translation spike (1 day, the top residual risk):** enumerate every Graph `recurrencePattern` variant (daily/weekly/absoluteMonthly/relativeMonthly/absoluteYearly/relativeYearly × single & multiple `daysOfWeek` × `index` first..last) into a fixture table asserting clean-RRULE-round-trip OR explicit "sidecar-only, not RRULE-expressible". **Its lossy-cell count gates the recurrence-wave estimate** and proves the sidecar is load-bearing.
2. **Google durable-refresh proof (8-day, still pending from the 2026-06-15 spike RUNBOOK):** confirm a Production-but-unverified app holds a refresh token past 7 days. **Gate the WRITE-BACK (PUSH) wave on its result;** planning + the store/auth/pull waves don't depend on it.

## What I want from you (Crucible)
Run your normal Stage 0 (Intake & Framing — confirm/sharpen the North Star above and the locked decisions, surfacing anything that should be John's call) → Stage 1 (Master Plan) → Stage 2 (Implementation Plan + Foreman handoff), with the Shark-Tank adversarial loop. Produce frozen `planning/calendar-v1/MASTER-PLAN.md` + `planning/calendar-v1/IMPLEMENTATION-PLAN.md`, Foreman-ready and wave-structured.

A sensible wave skeleton to refine (not prescriptive):
1. **ICS+sidecar event store** + the markdown-deadline→store mapping + the `[calendar]` extra (`icalendar` + `allenporter/ical`, lazy/degrade like `pywinpty`, `distro.py` allowlist).
2. **Auth** — `[calendar]` (msal/google-auth) + PKCE loopback + DPAPI; reuse the OBSERVED 2026-06-15 spike harness.
3. **PULL pipe + EventCalendar display** — vendor the widget; background poll → normalize → expand via `allenporter/ical` → cache `state.json`; render month/week/day/list from pre-expanded occurrences; render reads cache only.
4. **PUSH pipe** — create the dedicated Anchor-owned calendar per provider; upsert Anchor's events by `iCalUID` + self-marker + ETag (gated on the 8-day durable-refresh spike).
5. **Recurrence hardening** — the Graph fixture table; override identity `(iCalUID, original-start)`; the empty-replica abort guard.
6. **CLI mirror + fully-stubbed `check_calendar_surface` healthcheck + distro scan + docs/CLAUDE.md.**

Surface any risk the locked decisions create, and flag anything that should be John's call rather than yours.
